"""T8: what a forward record can prove, and when (results/forward_power_t8_prereg.md).

For every paper book of the forward report and every factory shadow:
  - the validated distribution: the backtest's exported daily net returns or a shadow's held-back
    days, cut at 2026-06-30 (R6, nothing from the lockbox); else the report's growth and volatility
    as a normal day (approximate); else none;
  - the days needed to show its validated Sharpe at 5 % with 80 % power: a fixed sample, and the
    sequential test below (the 80 % quantile of the first crossing over simulated records);
  - today's evidence, valid when looked at every day: a self-normalised mixture e-process
    (de la Pena; Robbins' mixture over a half-normal lambda) on the day's return for an edge above 0,
    and on the validated mean less the day's return for a fall below validation. Ville's inequality:
    a true null reaches 1 / ALPHA on any day with at most ALPHA probability;
  - a verdict each day: edge shown, below its band, consistent with validation (or no evidence yet).
Per family the records are pooled in a normal hierarchical model (numpy, a grid over tau), so many
short records add up; a Bayesian summary that never moves a book on its own.

    python -m lab.paper.power      reports/forward/power.{md,json}; lab.paper.forward_report calls it daily

Each book, shadow and family is one trial of R5's registry (counted only), registered before the
numbers are written. Reads journals and reports only: no book, gate, engine file or wallet changes;
evidence.json (the engine's) is not touched. G2's shadows log forecast losses, not returns: listed,
not tested.
"""

from __future__ import annotations

import csv
import json
import math
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
from scipy import stats

from .. import metrics, report
from ..factory import ledger as lg
from . import forward_report as fr

NAME = "power"
ALPHA, POWER = 0.05, 0.80
LEVEL = 1 / ALPHA
YEAR = 365
VAL_TO = "2026-06-30"                    # R6: validation ends here, the lockbox is never read
PATHS, CAP_DAYS, CHUNK, SEED = 1000, 30 * YEAR, YEAR, 8
REF_SHARPE, REF_DAYS = 1.0, 10           # no validated Sharpe: the test at 1.0 a year, its scale from 10 days
PRIOR_DAYS = 30                          # validation's weight in a member's sd, in days
TAU_MAX, TAU_GRID = 2.0, 400             # the family's spread of true Sharpes: uniform 0 to 2 a year
MIN_COMMON = 5
LADDER_PAPER_DAYS = 90                   # the provisional ladder's paper half (two_leads_t6.LADDER_PAPER_DAYS)
SOURCE = "results/forward_power_t8_prereg.md"
# Published validation numbers for books with no exported series and no report the forward report reads:
# book -> (annual Sharpe, CAGR, where).
PUBLISHED = {"perps_neutral": (1.74, 0.356, "T6 validation late at the costs of its era (results/two_leads_t6.md)")}
FAMILIES = (("momentum", ("tsmom", "small50_tsmom1", "small40_vol_target")),
            ("breakout", ("breakout_top10", "onchain_breakout_", "small100_breakout_sol3")),
            ("market-neutral", ("m4_ls", "m4_perps", "picks_ls", "perps_neutral", "funding_carry")),
            ("memes", ("memes_", "onchain_meme_", "pumpfun_")),
            ("trend", ("trend4h_pullback", "btc_gated", "small40_spy_trend", "onchain_longterm")))
VERDICTS = ("edge shown", "below its band", "consistent with validation", "no evidence yet")


def family_of(name: str, kind: str) -> str:
    if kind == "factory":
        return "factory shadows"
    if kind == "small":
        return "F2 shadows"
    for fam, prefixes in FAMILIES:
        if name.startswith(prefixes):
            return fam
    return name


# ---------------------------------------------------------------- the test

def z_sum() -> float:
    return float(stats.norm.ppf(1 - ALPHA) + stats.norm.ppf(POWER))


def fixed_days(sharpe_d: float) -> float:
    """Days of a fixed sample to reject a mean of 0 one-sided at ALPHA with POWER, at this daily Sharpe."""
    return (z_sum() / sharpe_d) ** 2 if sharpe_d > 0 else math.inf


def rho_for(mean_square: float, days: float) -> float:
    """The mixture's precision tuned to the horizon where the edge should show (Howard et al.'s rule)."""
    c = 2 * math.log(LEVEL) + math.log(1 + 2 * math.log(LEVEL))
    return mean_square * days / c


def log_e(S, V, rho):
    """log of the one-sided self-normalised mixture: 2 sqrt(rho / (rho + V)) exp(S^2 / 2(rho + V)) Phi(S / sqrt(rho + V))."""
    S, V = np.asarray(S, dtype=float), np.asarray(V, dtype=float)
    q = rho + V
    return math.log(2) + 0.5 * np.log(rho / q) + S ** 2 / (2 * q) + stats.norm.logcdf(S / np.sqrt(q))


def e_path(y: np.ndarray, rho: float) -> np.ndarray:
    """E after each day of y (the day's return less the null mean)."""
    y = np.asarray(y, dtype=float)
    return np.exp(log_e(np.cumsum(y), np.cumsum(y * y), rho))


def first_cross(e: np.ndarray) -> int | None:
    """Index of the first day E reaches 1 / ALPHA, or None."""
    hit = np.flatnonzero(np.asarray(e) >= LEVEL)
    return int(hit[0]) if len(hit) else None


def sequential_days(draw, rho: float, paths: int = PATHS, cap: int = CAP_DAYS, seed: int = SEED,
                    q: float = POWER) -> float:
    """Days by which a share q of simulated records has crossed (inf beyond cap). draw(rng, shape) gives days."""
    rng = np.random.default_rng(seed)
    S, V = np.zeros(paths), np.zeros(paths)
    hit = np.full(paths, np.inf)
    done = 0
    while done < cap:
        n = min(CHUNK, cap - done)
        y = draw(rng, (paths, n))
        s, v = S[:, None] + np.cumsum(y, 1), V[:, None] + np.cumsum(y * y, 1)
        crossed = log_e(s, v, rho) >= math.log(LEVEL)
        first = np.where(crossed.any(1), crossed.argmax(1) + 1 + done, np.inf)
        hit = np.minimum(hit, first)
        S, V, done = s[:, -1], v[:, -1], done + n
        if np.mean(np.isfinite(hit)) >= q:
            break
    k = float(np.quantile(hit, q, method="inverted_cdf"))   # the empirical quantile: no step into an open path
    return k if math.isfinite(k) else math.inf


# ---------------------------------------------------------------- what validation promised

def _cut(returns, first: str | None) -> np.ndarray:
    """Daily returns from `first`, one a calendar day, cut at VAL_TO."""
    r = np.asarray(returns, dtype=float)
    r = r[np.isfinite(r)]
    if first:
        keep = (date.fromisoformat(VAL_TO) - date.fromisoformat(first[:10])).days + 1
        r = r[:max(keep, 0)]
    return r


def _from_days(r: np.ndarray, source: str) -> dict | None:
    if len(r) < 30 or r.std() == 0:
        return None
    return {"mean": float(r.mean()), "sd": float(r.std()), "days": len(r), "method": "series", "source": source,
            "sample": r}


def _from_growth(cagr: float, vol: float, source: str) -> dict | None:
    if vol is None or vol <= 0 or cagr is None or cagr <= -1:
        return None
    return {"mean": math.log1p(cagr) / YEAR, "sd": vol / math.sqrt(YEAR), "days": None, "method": "approximate",
            "source": source, "sample": None}


def validated_book(book: str) -> dict | None:
    s = fr.load_series(book)
    if s is not None and float(s.get("period_days", 1)) == 1:
        v = _from_days(_cut(s["returns"], s.get("first")), f"{s.get('source', 'backtest')} to {VAL_TO}")
        if v:
            return v
    st = fr.report_stats(book)
    if st and st.get("vol"):
        v = _from_growth(st["cagr"], st["vol"], st["source"])
        if v:
            return v
    if book in PUBLISHED:
        sh, cagr, where = PUBLISHED[book]
        return _from_growth(cagr, math.log1p(cagr) / sh, where)
    return None


def validated_shadow(m: dict, kind: str) -> dict | None:
    h = m.get("holdout") or {}
    key = "oos_net_35bps" if kind == "factory" else "oos_returns_40"
    return _from_days(_cut(m.get(key) or [], h.get("oos_from")), f"held-back days from {h.get('oos_from')} to {VAL_TO}")


def annual(v: dict | None) -> float | None:
    return None if v is None else v["mean"] / v["sd"] * math.sqrt(YEAR)


# ---------------------------------------------------------------- forward records

def _by_date(rows: list[dict]) -> list[dict]:
    last: dict[str, dict] = {}
    for r in rows:
        if r.get("date"):
            last[r["date"]] = r
    return [last[d] for d in sorted(last)]


def _changes(dates: list[str], equity: list[float | None], start: float) -> tuple[list[str], np.ndarray]:
    out_d, out_r, prev = [], [], start
    for d, e in zip(dates, equity):
        if e is None or not prev:
            continue
        out_d.append(d)
        out_r.append(e / prev - 1)
        prev = e
    return out_d, np.array(out_r, dtype=float)


def book_record(book: str, root: Path | None = None) -> tuple[list[str], np.ndarray]:
    """The fresh record's dates and daily returns from the journal's equity."""
    rows, start, _ = fr.fresh_record(book, fr.read_journal(book, root))
    rows = _by_date(rows)
    return _changes([r["date"] for r in rows], [fr._f(r, "equity") for r in rows], start)


def _read_csv(p: Path) -> list[dict]:
    if not p.exists():
        return []
    with p.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def shadows(kind: str) -> list[tuple[dict, list[str], np.ndarray]]:
    """(meta, dates, daily returns) of every weekly factory (kind factory) or F2 (kind small) shadow."""
    d = (lg.factory_dir() if kind == "factory" else lg.small_dir()) / "shadow"
    out = []
    for p in sorted(d.glob("*.json")) if d.exists() else []:
        try:
            m = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        rows = _by_date(_read_csv(p.with_suffix(".csv")))
        if kind == "factory":
            dates = [r["date"] for r in rows if fr._f(r, "net_ret") is not None]
            x = np.array([fr._f(r, "net_ret") for r in rows if fr._f(r, "net_ret") is not None], dtype=float)
        else:
            dates, x = _changes([r["date"] for r in rows], [fr._f(r, "equity_eur") for r in rows],
                                float(m.get("capital_eur") or 0) or None)
        out.append((m, dates, x))
    return out


def g2_shadows() -> list[dict]:
    try:
        from ..models.factory import shadows_path
        return json.loads(shadows_path().read_text(encoding="utf-8")).get("members", [])
    except Exception:  # noqa: BLE001 - G2 not installed here or no file: nothing to list
        return []


# ---------------------------------------------------------------- one record

def _days_text(d: float | None) -> str:
    if d is None:
        return "n/a"
    if not math.isfinite(d):
        return f"more than {CAP_DAYS // YEAR} years" if d != -math.inf else "never"
    return f"{d:,.0f} days ({d / YEAR:.1f} years)"


def assess(name: str, kind: str, dates: list[str], x: np.ndarray, val: dict | None, sim: bool = True) -> dict:
    """Days needed, today's e-values and the verdict of one record against what validation promised."""
    x = np.asarray(x, dtype=float)
    n = len(x)
    row = {"name": name, "kind": kind, "family": family_of(name, kind), "days": n,
           "since": dates[0] if dates else None, "last": dates[-1] if dates else None,
           "return_pct": float(np.prod(1 + x) - 1) * 100 if n else 0.0,
           "sharpe_fwd": float(x.mean() / x.std() * math.sqrt(YEAR)) if n > 1 and x.std() > 0 else None,
           "validated": None, "fixed_days": None, "seq_days": None}
    ref_d = REF_SHARPE / math.sqrt(YEAR)
    if val is not None:
        sh_d = val["mean"] / val["sd"]
        row["validated"] = {"sharpe": sh_d * math.sqrt(YEAR), "mean_pct": val["mean"] * 100, "sd_pct": val["sd"] * 100,
                            "days": val["days"], "method": val["method"], "source": val["source"]}
        nf = fixed_days(sh_d)
        rho = rho_for(val["sd"] ** 2 + val["mean"] ** 2, nf if sh_d > 0 else fixed_days(ref_d))
        rho_below = rho_for(val["sd"] ** 2, nf if sh_d > 0 else fixed_days(ref_d))
        row["fixed_days"] = nf if sh_d > 0 else -math.inf
        if sh_d <= 0:
            row["seq_days"] = -math.inf
        elif nf > CAP_DAYS:
            row["seq_days"] = math.inf          # the sequential test needs at least the fixed sample's days
        elif sim:
            s = val["sample"]
            draw = ((lambda rng, shape: rng.choice(s, size=shape)) if s is not None else
                    (lambda rng, shape: rng.normal(val["mean"], val["sd"], shape)))
            row["seq_days"] = sequential_days(draw, rho)
        e_up = e_path(x, rho) if n else np.array([])
        e_dn = e_path(val["mean"] - x, rho_below) if n else np.array([])
        start = 0
    else:
        start = REF_DAYS
        if n > REF_DAYS and np.mean(x[:REF_DAYS] ** 2) > 0:
            rho = rho_for(float(np.mean(x[:REF_DAYS] ** 2)), fixed_days(ref_d))
            e_up = e_path(x[REF_DAYS:], rho)
        else:
            e_up = np.array([])
        e_dn = np.array([])
    up, dn = first_cross(e_up), first_cross(e_dn)
    row["e_edge"] = float(e_up[-1]) if len(e_up) else None
    row["e_edge_max"] = float(e_up.max()) if len(e_up) else None
    row["e_below"] = float(e_dn[-1]) if len(e_dn) else None
    row["e_below_max"] = float(e_dn.max()) if len(e_dn) else None
    row["edge_day"] = dates[start + up] if up is not None else None
    row["below_day"] = dates[dn] if dn is not None else None
    row["verdict"] = verdict(row)
    row["ladder"] = {"paper_days": n, "consistent": row["verdict"] in ("consistent with validation", "edge shown"),
                     "paper_ok": val is not None and row["below_day"] is None and n >= LADDER_PAPER_DAYS}
    return row


def verdict(row: dict) -> str:
    if row.get("below_day"):
        return "below its band"
    if row.get("edge_day"):
        return "edge shown"
    return "consistent with validation" if row.get("validated") else "no evidence yet"


# ---------------------------------------------------------------- pooled per family

def sigma_blend(x: np.ndarray, val: dict | None) -> float | None:
    if val is not None:
        ss = float(((x - x.mean()) ** 2).sum()) if len(x) else 0.0
        return math.sqrt((PRIOR_DAYS * val["sd"] ** 2 + ss) / (PRIOR_DAYS + max(len(x) - 1, 0)))
    return float(x.std(ddof=1)) if len(x) > 1 and x.std() > 0 else None


def mean_corr(series: list[dict]) -> float:
    """Mean pairwise correlation of the members' common days (at least MIN_COMMON), clipped to 0 to 1."""
    cs = []
    for i in range(len(series)):
        for j in range(i + 1, len(series)):
            a, b = series[i], series[j]
            common = sorted(set(a) & set(b))
            if len(common) < MIN_COMMON:
                continue
            u, v = np.array([a[d] for d in common]), np.array([b[d] for d in common])
            if u.std() > 0 and v.std() > 0:
                cs.append(float(np.corrcoef(u, v)[0, 1]))
    return float(np.clip(np.mean(cs), 0, 1)) if cs else 0.0


def hierarchical(m: np.ndarray, se: np.ndarray, tau_max: float = TAU_MAX / math.sqrt(YEAR), grid: int = TAU_GRID) -> dict:
    """Normal hierarchical model, mu flat, tau uniform on 0 to tau_max (BDA 5.4): the posterior of mu and of each
    theta, in the units of m."""
    m, se = np.asarray(m, dtype=float), np.asarray(se, dtype=float)
    tau = np.linspace(0, tau_max, grid)
    var = se[None, :] ** 2 + tau[:, None] ** 2
    w = 1 / var
    vmu = 1 / w.sum(1)
    mu = (w * m).sum(1) * vmu
    logp = 0.5 * np.log(vmu) - 0.5 * (np.log(var) + (m[None, :] - mu[:, None]) ** 2 * w).sum(1)
    p = np.exp(logp - logp.max())
    p /= p.sum()
    mean = float((p * mu).sum())
    sd = math.sqrt(max(float((p * (vmu + mu ** 2)).sum()) - mean ** 2, 0.0))
    xs = np.linspace(mean - 8 * sd, mean + 8 * sd, 4001) if sd > 0 else np.array([mean])
    cdf = (p[:, None] * stats.norm.cdf((xs[None, :] - mu[:, None]) / np.sqrt(vmu)[:, None])).sum(0)
    band = [float(np.interp(q, cdf, xs)) for q in (0.05, 0.95)] if sd > 0 else [mean, mean]
    shrink = se[None, :] ** 2 / var                        # 1 at tau 0: every theta is mu
    theta = (p[:, None] * (shrink * mu[:, None] + (1 - shrink) * m[None, :])).sum(0)
    return {"mean": mean, "sd": sd, "band": band, "p_pos": float((p * stats.norm.cdf(mu / np.sqrt(vmu))).sum()),
            "theta": [float(t) for t in theta], "tau_mean": float((p * tau).sum())}


def pool(rows: list[dict], records: dict[str, tuple[list[str], np.ndarray, dict | None]]) -> dict | None:
    """One family: the pooled forward Sharpe and the pooled gap to validation, both a year."""
    mem = []
    for r in rows:
        dates, x, val = records[r["name"]]
        sig = sigma_blend(x, val) if len(x) >= 2 else None
        if sig:
            mem.append((r["name"], dates, x, val, sig))
    if not mem:
        return None
    rho = mean_corr([dict(zip(d, x)) for _, d, x, _, _ in mem])
    deff = 1 + (len(mem) - 1) * rho
    a = math.sqrt(YEAR)
    m = np.array([x.mean() / s for _, _, x, _, s in mem])
    se = np.array([math.sqrt(deff / len(x)) for _, _, x, _, _ in mem])
    h = hierarchical(m, se)
    out = {"members": [n for n, *_ in mem], "days": int(sum(len(x) for _, _, x, _, _ in mem)), "corr": rho,
           "design_effect": deff, "sharpe": h["mean"] * a, "band": [b * a for b in h["band"]], "p_pos": h["p_pos"],
           "shrunk": {n: t * a for (n, *_), t in zip(mem, h["theta"])}, "gap": None}
    gm = [(i, val["mean"] / val["sd"]) for i, (_, _, _, val, _) in enumerate(mem) if val is not None]
    if gm:
        idx = [i for i, _ in gm]
        g = hierarchical(m[idx] - np.array([v for _, v in gm]), se[idx])
        out["gap"] = {"members": len(idx), "sharpe": g["mean"] * a, "band": [b * a for b in g["band"]],
                      "p_below": 1 - g["p_pos"]}
    return out


# ---------------------------------------------------------------- the run

def trials(rows: list[dict], families: list[str]) -> list[dict]:
    reg = {"book": "hand", "factory": "factory", "small": "small"}
    out = [{"id": f"{reg[r['kind']]}:t8:{r['name']}", "family": reg[r["kind"]], "n": 1, "sharpe": None,
            "source": SOURCE} for r in rows]
    for f in families:
        fam = "factory" if f == "factory shadows" else "small" if f == "F2 shadows" else "hand"
        out.append({"id": f"{fam}:t8:pool:{f}", "family": fam, "n": 1, "sharpe": None, "source": SOURCE})
    return out


def collect(root: Path | None = None) -> list[tuple[str, str, list[str], np.ndarray, dict | None]]:
    """(name, kind, dates, returns, validated) of every book with a record and every factory shadow."""
    out = []
    for b in [x["name"] for x in fr.paper_books(root)]:
        dates, x = book_record(b, root)
        if len(x):
            out.append((b, "book", dates, x, validated_book(b)))
    for kind in ("factory", "small"):
        for m, dates, x in shadows(kind):
            out.append((m["key"], kind, dates, x, validated_shadow(m, kind)))
    return out


def build(root: Path | None = None, now_ms: int | None = None, register: bool = True, sim: bool = True,
          log=print) -> dict:
    now_ms = now_ms or int(time.time() * 1000)
    recs = collect(root)
    fams = sorted({family_of(n, k) for n, k, *_ in recs})
    if register:
        try:
            metrics.register(trials([{"name": n, "kind": k} for n, k, *_ in recs], fams))   # before any number
        except OSError as e:
            log(f"power: the registry could not be written ({e}); the trials count when it can")
    rows = [assess(n, k, d, x, v, sim) for n, k, d, x, v in recs]
    by = {n: (d, x, v) for n, _, d, x, v in recs}
    families = {}
    for f in fams:
        p = pool([r for r in rows if r["family"] == f], by)
        if p:
            families[f] = p
    g2 = [{"key": m.get("key"), "status": m.get("status"), "scored_days": m.get("scored_days")} for m in g2_shadows()]
    return _finite({"generated": datetime.fromtimestamp(now_ms / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
                    "generated_ms": now_ms, "alpha": ALPHA, "power": POWER, "level": LEVEL, "val_to": VAL_TO,
                    "rows": rows, "families": families, "g2_shadows": g2, "counts": counts(rows)})


def counts(rows: list[dict]) -> dict:
    return {v: sum(r["verdict"] == v for r in rows) for v in VERDICTS}


def _finite(v):
    if isinstance(v, float):
        return v if math.isfinite(v) else (None if math.isnan(v) else ("inf" if v > 0 else "never"))
    if isinstance(v, dict):
        return {k: _finite(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_finite(x) for x in v]
    return v


def _num(v) -> float | None:
    if v == "inf":
        return math.inf
    if v == "never":
        return -math.inf
    return v


def _e(v) -> str:
    return "n/a" if v is None else f"{v:.2f}" if v < 100 else f"{v:,.0f}"


def headline(data: dict) -> str:
    c = data["counts"]
    need = [_num(r["seq_days"]) for r in data["rows"] if _num(r.get("seq_days")) is not None]
    fin = [d for d in need if math.isfinite(d) and d > 0]
    quick = f"the quickest needs {min(fin) / YEAR:.1f} years" if fin else "none can show its edge within 30 years"
    return (f"{len(data['rows'])} records: {c['edge shown']} with an edge shown, {c['below its band']} below their "
            f"validated band, {c['consistent with validation']} consistent with validation, {c['no evidence yet']} "
            f"without a validated Sharpe; {quick} at 5 % and 80 % power.")


def table_rows(data: dict) -> list[dict]:
    out = []
    for r in data["rows"]:
        v = r.get("validated") or {}
        out.append({"record": r["name"], "family": r["family"], "days": r["days"],
                    "return": f"{r['return_pct']:+.2f} %",
                    "validated_sharpe": f"{v['sharpe']:.2f} ({v['method']})" if v else "none",
                    "days_needed_fixed": _days_text(_num(r.get("fixed_days"))),
                    "days_needed_sequential": _days_text(_num(r.get("seq_days"))),
                    "e_edge": _e(r.get("e_edge")), "e_below": _e(r.get("e_below")), "verdict": r["verdict"]})
    return out


def family_rows(data: dict) -> list[dict]:
    out = []
    for f, p in data["families"].items():
        g = p.get("gap")
        out.append({"family": f, "members": len(p["members"]), "days": p["days"], "corr": f"{p['corr']:.2f}",
                    "pooled_sharpe": f"{p['sharpe']:+.2f} ({p['band'][0]:+.2f} to {p['band'][1]:+.2f})",
                    "p_above_0": f"{p['p_pos']:.2f}",
                    "gap_to_validation": (f"{g['sharpe']:+.2f} ({g['band'][0]:+.2f} to {g['band'][1]:+.2f}), "
                                          f"P below {g['p_below']:.2f}") if g else "n/a"})
    return out


def markdown(data: dict) -> str:
    lines = ["# Forward evidence: what each paper record can prove, and when\n",
             f"{data['generated']}. {headline(data)}\n",
             "Days needed: to tell the validated Sharpe from 0 at 5 % one-sided with 80 % power, from the validated "
             f"days only (365 a year; validation cut at {data['val_to']}); fixed sample and the sequential test used "
             "here (80 % of 1,000 simulated records found by then). e_edge: today's e-value against no edge, "
             "e_below: against the validated mean; either reaching 20 on any day decides (5 %, valid however often "
             "it is looked at). Below 1 is evidence the other way, 1 to 20 is not enough. "
             "Pre-registered in results/forward_power_t8_prereg.md.\n", "## Records\n",
             report.table(table_rows(data), ["record", "family", "days", "return", "validated_sharpe",
                                             "days_needed_fixed", "days_needed_sequential", "e_edge", "e_below",
                                             "verdict"]),
             "## Pooled per family\n",
             "A normal hierarchical model over the family's records (Sharpe a year, 90 % band), each record's error "
             "widened by the family's mean correlation; a Bayesian summary that never moves a book on its own.\n"]
    rows = family_rows(data)
    lines.append(report.table(rows, ["family", "members", "days", "corr", "pooled_sharpe", "p_above_0",
                                     "gap_to_validation"]) if rows else "No family has two days yet.\n")
    if data.get("g2_shadows"):
        lines.append(f"G2's {len(data['g2_shadows'])} shadow(s) log forecast losses, not returns: not tested here.\n")
    lines.append("T3's ladder is not on main; each row's `ladder` in power.json carries the paper half of the "
                 f"provisional ladder ({LADDER_PAPER_DAYS} days, never below its band).\n")
    return "\n".join(lines) + "\n"


def summary(data: dict) -> dict:
    """What the forward report's JSON keeps (and its section reads)."""
    return {"headline": headline(data), "counts": data["counts"],
            "books": {r["name"]: {**{k: r.get(k) for k in ("kind", "verdict", "days", "e_edge", "e_below", "fixed_days",
                                                            "seq_days", "edge_day", "below_day", "ladder")},
                                  "validated_sharpe": (r.get("validated") or {}).get("sharpe")}
                      for r in data["rows"]}}


def section(s: dict | None) -> list[str]:
    """The forward report's lines, from summary()."""
    if not s:
        return []
    out = ["## Forward evidence (T8)\n", s["headline"] + " Details: `reports/forward/power.md`.\n"]
    for name, r in s["books"].items():
        if r.get("kind") != "book":
            continue
        need = (f"needs {_days_text(_num(r.get('seq_days')))} at its validated Sharpe {r['validated_sharpe']:.2f}"
                if r.get("validated_sharpe") is not None else "no validated Sharpe")
        out.append(f"- `{name}`: {r['verdict']}, {r['days']} days, e {_e(r.get('e_edge'))} for an edge; {need}")
    return out + [""]


def write(data: dict) -> Path:
    d = report.REPORTS / fr.NAME
    d.mkdir(parents=True, exist_ok=True)
    (d / "power.md").write_text(markdown(data), encoding="utf-8")
    (d / "power.json").write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    return d / "power.md"


def run(root: Path | None = None, log=print) -> dict:
    data = build(root, log=log)
    write(data)
    return data


def main() -> int:
    data = run()
    print(markdown(data))
    return 0


if __name__ == "__main__":
    sys.exit(main())
