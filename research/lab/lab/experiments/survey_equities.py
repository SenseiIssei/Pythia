"""Equity candidates 3, 4, 6, 7 and 8 of the strategy survey, as pre-registered.

    python -m lab.experiments.survey_equities                       every study
    python -m lab.experiments.survey_equities seasonality ...       only these

Pre-registered in results/survey_equities_prereg.md (committed before this file
existed). Studies, each written to results/<study>.md below its marker and to
<reports>/<study>/latest.{md,json}:

  earnings_premium   members bought e sessions before the expected earnings date
                     (last year's 8-K item 2.02 plus 364 days), sold x sessions after
  index_deletions    discretionary S&P 500 deletions held 3, 6, 12 months, and
                     deletions minus additions
  seasonality        same-calendar-month return seasonality (Heston and Sadka)
  quality_issuance   gross profit to assets and net share issuance from XBRL
  turn_of_month      SPY, QQQ, IWM over the turn of the month, SPY pre-holiday

Study 6 of the registration (insider purchases) is deferred: SEC's Form 345 data
sets need a contact in the User-Agent (PYTHIA_SEC_UA).

On the PC the data folder is a sync mirror, so reports and new caches go elsewhere:

    PYTHIA_DATA=F:/PythiaData PYTHIA_REPORTS=<dir>/reports PYTHIA_XBRL_DATA=<dir>/xbrl \
        PYTHIA_OHLC_DATA=<dir>/ohlc python -m lab.experiments.survey_equities
"""

from __future__ import annotations

import json
import math
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from scipy import stats

from .. import report
from ..equities import books as bk
from ..equities import edgar
from ..equities import panel as pn
from . import equities_ranking as er
from . import fam_common as fc
from . import flow_overlays as fo

STUDIES = ("earnings_premium", "index_deletions", "seasonality", "quality_issuance", "turn_of_month")
TRIALS = {"earnings_premium": 6, "index_deletions": 5, "seasonality": 6, "quality_issuance": 6, "turn_of_month": 10}
REGISTERED = 33
HAND_TRIALS = 1140
PRIOR_TRIALS, PRIOR_SR0 = 377, 2.43
YEAR = bk.YEAR_DAYS
SEC = bk.SEC_FEE
TAF = 0.000166                      # USD per share sold
BORROW = 0.003                      # a year on the short gross
STOCK_BPS, DELETED_BPS, ETF_BPS = 5.0, 10.0, 2.0
SEED = 20261021
BOOT_DRAWS, BOOT_BLOCK = 4000, 20
RESULTS = Path(os.environ.get("PYTHIA_RESULTS", str(Path(__file__).resolve().parents[2] / "results")))
OOS = np.datetime64("2016-01-01")


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


# ---------------------------------------------------------------------------
# Context and the long-only simulator
# ---------------------------------------------------------------------------

@dataclass
class Ctx:
    S: pn.Panel
    E: pn.Panel
    X: bk.Inputs
    ok: np.ndarray                  # (T, N) member, traded, 252 sessions of history
    spy: np.ndarray                 # (T,) SPY open to open
    me: np.ndarray                  # (T,) month-end sessions
    cik: dict                       # ticker -> CIK
    has_cik: np.ndarray             # (N,)
    events: list                    # (ticker, cik, date, kind)
    cache: dict = field(default_factory=dict)


def load_ctx() -> Ctx:
    S, E = pn.load()
    X = bk.inputs(S)
    bk.inputs(E)
    ev = edgar.load_events(S, offline=True)
    has = np.array([s in ev["cik"] for s in S.names])
    return Ctx(S=S, E=E, X=X, ok=bk.base_ok(S, X), spy=E.r_oo()[:, E.col("SPY")], me=bk.month_ends(S.dates),
               cik=ev["cik"], has_cik=has, events=ev["events"])


@dataclass
class Sim:
    gross: np.ndarray
    tov: np.ndarray
    fees: np.ndarray
    expo: np.ndarray

    def net(self, bps: float) -> np.ndarray:
        return self.gross - bps * 1e-4 * self.tov - self.fees


def wsim(P: pn.Panel, targets: dict[int, np.ndarray], lag: int = 1) -> Sim:
    """Long-only weights decided at the close of t (dict t -> (N,) weights, the rest cash),
    filled at the open of t + lag, drifting in between. Fees: SEC fee and TAF on sales."""
    F, R = P.fill(), P.r_oo()
    T, N = P.T, P.N
    w = np.zeros(N)
    gross, tov, fees, expo = np.zeros(T), np.zeros(T), np.zeros(T), np.zeros(T)
    pend: dict[int, np.ndarray] = {}
    for t in range(T):
        if t in pend:
            tgt = pend.pop(t)
            tgt = np.where(np.isfinite(F[t]) & P.alive[t], tgt, 0.0)
            d = tgt - w
            tov[t] = np.abs(d).sum()
            s = np.where(d < 0, -d, 0.0)
            px = np.where(np.isfinite(F[t]) & (F[t] > 0), F[t], np.inf)
            fees[t] = SEC * s.sum() + TAF * (s / px).sum()
            w = tgt
        expo[t] = w.sum()
        g = float(w @ R[t])
        gross[t] = g
        w = w * (1 + R[t]) / (1 + g) if 1 + g > 0 else np.zeros(N)
        if t in targets and t + lag < T:
            pend[t + lag] = np.asarray(targets[t], float)
    return Sim(gross, tov, fees, expo)


def overlay(P: pn.Panel, W: np.ndarray, base: np.ndarray, bps_name: float, bps_base: float,
            R: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Positions W[s] (held from the open of s to the open of s+1) financed from `base`
    (a return series held with the rest): the active return sum W (r - base), and per
    session its turnover and fees. Returns (gross active, turnover, fees); a weight
    change pays bps_name on the name and bps_base on the base, sales pay SEC and TAF."""
    R = P.r_oo() if R is None else R
    F = P.fill()
    with np.errstate(invalid="ignore"):
        act = np.nansum(W * (R - base[:, None]), axis=1)
    d = np.diff(np.vstack([np.zeros((1, P.N)), W]), axis=0)
    tov = np.abs(d).sum(1)
    s = np.where(d < 0, -d, 0.0)
    b = np.where(d > 0, d, 0.0).sum(1)
    px = np.where(np.isfinite(F) & (F > 0), F, np.inf)
    fees = SEC * s.sum(1) + TAF * (s / px).sum(1) + (SEC * b if bps_base > 0 else 0.0)
    cost = tov * (bps_name + bps_base) * 1e-4 + fees
    return act, tov, cost


def ew_targets(ctx: Ctx, cols_ok: np.ndarray | None = None, days: np.ndarray | None = None) -> dict[int, np.ndarray]:
    days = ctx.me if days is None else days
    out = {}
    for t in np.flatnonzero(days):
        m = ctx.ok[t] if cols_ok is None else ctx.ok[t] & cols_ok
        n = int(m.sum())
        if n:
            out[t] = np.where(m, 1.0 / n, 0.0)
    return out


def equal_weight(ctx: Ctx, key: str = "all", cols_ok: np.ndarray | None = None, lag: int = 1) -> np.ndarray:
    k = f"ew:{key}:{lag}"
    if k not in ctx.cache:
        ctx.cache[k] = wsim(ctx.S, ew_targets(ctx, cols_ok), lag).net(STOCK_BPS)
    return ctx.cache[k]


def top_targets(score: np.ndarray, elig: np.ndarray, days: np.ndarray, k: int | None = None,
                frac: float | None = None, low: bool = False) -> dict[int, np.ndarray]:
    """Equal weight on the k best (or the best `frac` share) of the eligible names with a score."""
    out = {}
    for t in np.flatnonzero(days):
        e = np.flatnonzero(elig[t] & np.isfinite(score[t]))
        if e.size < 10:
            continue
        n = k if k is not None else max(1, int(e.size * frac))
        s = score[t, e] * (1 if low else -1)
        pick = e[np.argsort(s, kind="stable")[:n]]
        w = np.zeros(score.shape[1])
        w[pick] = 1.0 / pick.size
        out[t] = w
    return out


# ---------------------------------------------------------------------------
# Numbers
# ---------------------------------------------------------------------------

def sharpe(x: np.ndarray) -> float:
    return bk.sharpe(np.asarray(x, float))


def boot_idx(n: int, seed: int = SEED) -> np.ndarray:
    return bk.boot_indices(n, np.random.default_rng(seed), BOOT_DRAWS, BOOT_BLOCK)


def boot_sharpe(x: np.ndarray, y: np.ndarray | None = None, seed: int = SEED) -> dict:
    """Stationary bootstrap of Sharpe(x) (or Sharpe(x) - Sharpe(y), same sessions)."""
    idx = boot_idx(len(x), seed)

    def sr(a: np.ndarray) -> np.ndarray:
        s = a[idx]
        sd = s.std(1)
        return np.where(sd > 0, s.mean(1) / np.where(sd > 0, sd, 1) * math.sqrt(YEAR), 0.0)

    v = sr(np.asarray(x, float)) - (sr(np.asarray(y, float)) if y is not None else 0.0)
    return {"p05": float(np.percentile(v, 5)), "p95": float(np.percentile(v, 95)), "above0": float((v > 0).mean())}


def boot_mean(ev: np.ndarray, seed: int = SEED, other: np.ndarray | None = None) -> dict:
    """Event bootstrap of the mean (or of mean(ev) - mean(other), resampled separately)."""
    rng = np.random.default_rng(seed)
    ev = np.asarray(ev, float)
    if ev.size == 0:
        return {"p05": float("nan"), "p95": float("nan"), "above0": float("nan")}
    m = ev[rng.integers(0, ev.size, (BOOT_DRAWS, ev.size))].mean(1)
    if other is not None and np.asarray(other).size:
        o = np.asarray(other, float)
        m = m - o[rng.integers(0, o.size, (BOOT_DRAWS, o.size))].mean(1)
    return {"p05": float(np.percentile(m, 5)), "p95": float(np.percentile(m, 95)), "above0": float((m > 0).mean())}


def alpha(x: np.ndarray, m: np.ndarray) -> float:
    return bk.alpha_beta(np.asarray(x, float), np.asarray(m, float))[0]


def per_year(dates: np.ndarray, x: np.ndarray, mask: np.ndarray) -> dict[int, float]:
    yr = bk.years(dates)
    return {int(y): float(np.prod(1 + x[mask & (yr == y)]) - 1) for y in np.unique(yr[mask])}


def per_year_sharpe(dates: np.ndarray, x: np.ndarray, mask: np.ndarray) -> dict[int, float]:
    yr = bk.years(dates)
    return {int(y): sharpe(x[mask & (yr == y)]) for y in np.unique(yr[mask])}


def obs_sharpe(x: np.ndarray) -> float:
    x = np.asarray(x, float)
    return float(x.mean() / x.std()) if x.std() > 0 else 0.0


# ---------------------------------------------------------------------------
# The pool
# ---------------------------------------------------------------------------

def prior_var() -> float:
    g = 0.5772156649
    z = (1 - g) * stats.norm.ppf(1 - 1 / PRIOR_TRIALS) + g * stats.norm.ppf(1 - 1 / (PRIOR_TRIALS * math.e))
    return (PRIOR_SR0 / math.sqrt(365) / z) ** 2


def all_trial_sharpes(mine: dict[str, list[float]]) -> list[float]:
    """Per-session Sharpes of every trial registered here that has run (this run's, else
    the last saved report of the study)."""
    out = []
    for s in STUDIES:
        if s in mine:
            out += mine[s]
            continue
        try:
            d = json.loads((report.REPORTS / s / "latest.json").read_text(encoding="utf-8"))
            out += [float(v) for v in d.get("trial_sharpes_obs", [])]
        except (OSError, ValueError):
            pass
    return out


def pool(mine: dict[str, list[float]]) -> dict:
    """1,140 hand trials at the published bar's variance, the factory ledger at its own,
    the 33 registered here at theirs (those that have run stand for all 33)."""
    v1, n1 = prior_var(), HAND_TRIALS
    fx = np.clip(fo.factory_sharpes(), -fc.SR_CLIP, fc.SR_CLIP) / math.sqrt(365)
    n2, v2 = len(fx), float(np.var(fx)) if len(fx) > 1 else 0.0
    x = np.clip(np.array(all_trial_sharpes(mine)) * math.sqrt(YEAR), -fc.SR_CLIP, fc.SR_CLIP) / math.sqrt(YEAR)
    v3 = float(np.var(x)) if len(x) > 1 else v1
    n3 = REGISTERED
    n = n1 + n2 + n3
    v = (n1 * v1 + n2 * v2 + n3 * v3) / n
    sr0 = fc._sr0(v, n)
    return {"hand_trials": n1, "factory_trials": n2, "registered": n3, "ran": len(x), "n_total": n, "var": v,
            "sr0_annual_equity": sr0 * math.sqrt(YEAR)}


def deflated(x: np.ndarray, pl_: dict) -> float:
    return fo.deflated(np.asarray(x, float), pl_["n_total"], pl_["var"])


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------

def marker(name: str) -> str:
    return f"<!-- generated below by lab.experiments.survey_equities ({name}); edit above this line only -->"


def f2(v, nd: int = 2) -> str:
    if v is None:
        return "n/a"
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, (int, np.integer)):
        return str(int(v))
    v = float(v)
    return "n/a" if not math.isfinite(v) else f"{v:.{nd}f}"


def pct(v, nd: int = 1) -> str:
    return "n/a" if v is None or not math.isfinite(float(v)) else f"{100 * float(v):.{nd}f} %"


def table(rows: list[dict], cols: list[tuple[str, str]]) -> str:
    out = ["| " + " | ".join(h for _, h in cols) + " |", "|" + "---|" * len(cols)]
    for r in rows:
        out.append("| " + " | ".join(r.get(k) if isinstance(r.get(k), str) else f2(r.get(k)) for k, _ in cols) + " |")
    return "\n".join(out)


def gates_md(g: dict) -> str:
    return "\n".join(f"- {'not run' if v is None else 'PASS' if v else 'fail'}: {k}" for k, v in g.items())


def write(name: str, md: str, data: dict) -> None:
    path = RESULTS / f"{name}.md"
    mk = marker(name)
    above = ""
    if path.exists():
        text = path.read_text(encoding="utf-8")
        if mk in text:
            above = text.split(mk)[0].rstrip() + "\n"
    path.write_text((above + "\n" if above.strip() else "") + mk + "\n\n" + md.rstrip() + "\n", encoding="utf-8",
                    newline="\n")
    d = report.REPORTS / name
    d.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for fn in (f"{stamp}.md", "latest.md"):
        (d / fn).write_text(md, encoding="utf-8")
    for fn in (f"{stamp}.json", "latest.json"):
        (d / fn).write_text(json.dumps(data, indent=2, default=_jd), encoding="utf-8")
    log(f"{name}: written to {path}")


def _jd(o):
    if isinstance(o, (np.floating, np.integer)):
        return o.item()
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, np.datetime64):
        return str(o)
    return str(o)


def pool_line(pl_: dict) -> str:
    return (f"Pool: {pl_['hand_trials']:,} hand trials, {pl_['factory_trials']} factory genomes and the "
            f"{pl_['registered']} trials registered with this study ({pl_['ran']} of them run so far, standing for "
            f"all): {pl_['n_total']:,} trials; the best noise trial sits at an annual Sharpe of about "
            f"{pl_['sr0_annual_equity']:.2f} on trading days.")


# ===========================================================================
# 1. Earnings announcement premium
# ===========================================================================

EP_SEL = (np.datetime64("2005-01-01"), OOS)
EP_K = 20


def ep_events(ctx: Ctx) -> dict[int, np.ndarray]:
    """Per column: sorted calendar days of its 8-K earnings events."""
    col = {s: j for j, s in enumerate(ctx.S.names)}
    out: dict[int, list] = {}
    for t, _c, d, kind in ctx.events:
        if kind != "8-K" or t not in col:
            continue
        out.setdefault(col[t], []).append(np.datetime64(str(d)[:10], "D"))
    return {j: np.array(sorted(set(v)), dtype="datetime64[D]") for j, v in out.items()}


def ep_volume_score(ctx: Ctx, ev: dict[int, np.ndarray]) -> np.ndarray:
    """(T, N): mean abnormal dollar volume of the name's last 4 announcements, known from
    the close of each window's second session."""
    S, X = ctx.S, ctx.X
    dv = np.where(S.traded, S.dv, np.nan)
    out = np.full((S.T, S.N), np.nan)
    for j, days in ev.items():
        i0 = np.searchsorted(S.dates, days)
        av, at = [], []
        for i in i0:
            if i + 1 >= S.T:
                continue
            base = X.dv50[i, j]
            win = dv[i:i + 2, j]
            if not (np.isfinite(base) and base > 0 and np.isfinite(win).any()):
                continue
            av.append(float(np.nanmean(win) / base))
            at.append(i + 1)
        for k in range(len(av)):
            out[at[k], j] = float(np.mean(av[max(0, k - 3):k + 1]))
    return er._ffill(out)


def ep_candidates(ctx: Ctx, ev: dict[int, np.ndarray], e: int) -> list[tuple[int, int, int]]:
    """(column, iE, decision session) of every expected date the rule acts on with entry e."""
    S = ctx.S
    out = []
    for j, days in ev.items():
        if not ctx.has_cik[j]:
            continue
        cand = np.sort(days + np.timedelta64(364, "D"))
        keep, last = [], None
        for c in cand:
            if last is None or (c - last).astype(int) >= 30:
                keep.append(c)
                last = c
        for c in keep:
            iE = int(np.searchsorted(S.dates, c))
            t = iE - e - 1
            if t < 0 or iE - e >= S.T:
                continue
            if not ctx.ok[t, j]:
                continue
            lo, hi = c - np.timedelta64(45, "D"), S.dates[t]
            if ((days >= lo) & (days <= hi)).any():
                continue
            out.append((j, iE, t))
    return out


def ep_weights(ctx: Ctx, cands: list[tuple[int, int, int]], e: int, x: int, shift: int = 0,
               vscore: np.ndarray | None = None) -> np.ndarray:
    """(T, N) position weights by session: 1/20 per name in its window (1/n beyond 20)."""
    S = ctx.S
    M = np.zeros((S.T, S.N), dtype=bool)
    med = None
    if vscore is not None:
        with np.errstate(invalid="ignore"):
            sc = np.where(ctx.ok, vscore, np.nan)
            med = np.nanmedian(sc, axis=1)
    for j, iE, t in cands:
        if vscore is not None:
            v = vscore[t, j]
            if not (np.isfinite(v) and np.isfinite(med[t]) and v >= med[t]):
                continue
        a, b = iE - e + shift, min(iE + x + shift, S.T)
        if a < S.T:
            M[a:b, j] = True
    n = M.sum(1)
    w = np.where(n > 0, 1.0 / np.maximum(n, EP_K), 0.0)
    return M * w[:, None]


def earnings_premium(ctx: Ctx) -> dict:
    S = ctx.S
    ev = ep_events(ctx)
    ew_cik = equal_weight(ctx, "cik", ctx.has_cik)
    ew_all = equal_weight(ctx)
    sel = (S.dates >= EP_SEL[0]) & (S.dates < EP_SEL[1])
    oos = S.dates >= OOS
    vscore = ep_volume_score(ctx, ev)
    cands = {e: ep_candidates(ctx, ev, e) for e in (5, 2)}

    def run(e: int, x: int, vf: bool, shift: int = 0, bps: float = STOCK_BPS, base: str = "ew") -> dict:
        W = ep_weights(ctx, cands[e], e, x, shift, vscore if vf else None)
        b = ew_cik if base == "ew" else ctx.spy
        act, tov, cost = overlay(S, W, b, bps, STOCK_BPS if base == "ew" else ETF_BPS)
        net = act - cost
        return {"W": W, "act": net, "act_gross": act, "tov": tov, "book": b + net}

    rows, series = [], {}
    grid = [(e, x, False) for e in (5, 2) for x in (1, 3)]

    def describe(e, x, vf) -> dict:
        r = run(e, x, vf)
        r2 = run(e, x, vf, bps=2 * STOCK_BPS)
        lab = f"entry {e} before, exit {x} after" + (", volume filter" if vf else "")
        series[lab] = r
        n_in = (r["W"] > 0).sum(1)
        return {"label": lab, "e": e, "x": x, "vf": vf,
                "sel_ir": sharpe(r["act"][sel]), "oos_ir": sharpe(r["act"][oos]),
                "oos_ir_gross": sharpe(r["act_gross"][oos]), "oos_active_gross_yr": float(r["act_gross"][oos].mean() * YEAR),
                "oos_ir_2x": sharpe(r2["act"][oos]), "oos_alpha": alpha(r["book"][oos], ew_cik[oos]),
                "oos_active_yr": float(r["act"][oos].mean() * YEAR),
                "oos_ir_vs_all": sharpe((r["book"] - ew_all)[oos]),
                "names_mean_oos": float(n_in[oos].mean()), "days_with_names_oos": float((n_in[oos] > 0).mean()),
                "turnover_yr": float(r["tov"][oos].sum() / (oos.sum() / YEAR)),
                "sr_obs": obs_sharpe(r["act"][oos])}

    for e, x, vf in grid:
        rows.append(describe(e, x, vf))
    base_pick = max(rows, key=lambda r: r["sel_ir"])
    for x in (1, 3):
        rows.append(describe(base_pick["e"], x, True))
    pick = max(rows, key=lambda r: r["sel_ir"])
    pl_ = pool({"earnings_premium": [r["sr_obs"] for r in rows]})
    for r in rows:
        r["deflated_p"] = deflated(series[r["label"]]["act"][oos], pl_)
    P = series[pick["label"]]
    late = run(pick["e"], pick["x"], pick["vf"], shift=1)
    L = run(pick["e"], pick["x"], pick["vf"], base="spy")
    bt = boot_sharpe(P["act"][oos])
    spy_sr = sharpe(ctx.spy[oos])
    g = {
        "1 alpha against the CIK equal weight above 0 and the bootstrap 5 % bound of the IR above 0":
            pick["oos_alpha"] > 0 and bt["p05"] > 0,
        "2 IR above 0.3": pick["oos_ir"] > 0.3,
        "3 IR above 0 with the entry a day late": sharpe(late["act"][oos]) > 0,
        "4 IR above 0 with costs doubled": pick["oos_ir_2x"] > 0,
        "5 book L's Sharpe above SPY's": sharpe(L["book"][oos]) > spy_sr,
    }
    passed = all(g.values())
    killed = pick["oos_ir"] < 0.1
    # prediction quality: share of expected dates with an actual 8-K within two sessions
    hits, n_c = 0, 0
    for j, iE, t in cands[pick["e"]]:
        if S.dates[t] < OOS:
            continue
        i0 = np.searchsorted(S.dates, ev[j])
        n_c += 1
        hits += int(((i0 >= iE - 2) & (i0 <= iE + 2)).any())
    res = {
        "name": "earnings_premium", "rows": rows, "pick": pick["label"], "gates": g, "passed": passed,
        "killed": killed, "confirmed": passed and pick["deflated_p"] > 0.95, "pool": pl_,
        "late_ir": sharpe(late["act"][oos]), "boot": bt, "L_sharpe": sharpe(L["book"][oos]),
        "L_cagr": bk.perf(L["book"][oos])["cagr"], "L_dd": bk.perf(L["book"][oos])["max_dd"],
        "spy_sharpe": spy_sr, "ew_cik_sharpe": sharpe(ew_cik[oos]), "ew_sharpe": sharpe(ew_all[oos]),
        "T_sharpe": sharpe(P["book"][oos]), "prediction_hit": hits / n_c if n_c else float("nan"),
        "candidates_oos": n_c, "ir_by_year": per_year_sharpe(S.dates, P["act"], oos),
        "active_by_year": per_year(S.dates, P["act"], oos),
        "trial_sharpes_obs": [r["sr_obs"] for r in rows],
    }
    res["markdown"] = ep_markdown(res)
    return res


def ep_markdown(r: dict) -> str:
    pk = next(x for x in r["rows"] if x["label"] == r["pick"])
    verdict = ("PASS, confirmed" if r["confirmed"] else "PASS, not confirmed (deflation)" if r["passed"]
               else "KILL" if r["killed"] else "FAIL")
    out = [f"# Earnings announcement premium: results ({datetime.now(timezone.utc):%Y-%m-%d})", "",
           f"**Verdict: {verdict}.** Pick (best selection-window IR): {r['pick']}. Out of sample from 2016: "
           f"IR {f2(pk['oos_ir'])} against the CIK equal weight ({pct(pk['oos_active_yr'])} a year active, "
           f"alpha {pct(pk['oos_alpha'])}), {f2(pk['oos_ir_2x'])} with costs doubled, {f2(r['late_ir'])} a day "
           f"late; bootstrap 90 % band of the IR {f2(r['boot']['p05'])} to {f2(r['boot']['p95'])}. Book L (SPY "
           f"with the rest): Sharpe {f2(r['L_sharpe'])} against SPY {f2(r['spy_sharpe'])}; the tilt book "
           f"{f2(r['T_sharpe'])} against the CIK equal weight {f2(r['ew_cik_sharpe'])}. Deflated p "
           f"{f2(pk['deflated_p'], 3)}.", "",
           "## Gates (the pick, out of sample)", "", gates_md(r["gates"]), "",
           f"Kill rule (IR below 0.1): {'hit' if r['killed'] else 'not hit'}.", "",
           "## All trials", "",
           table(r["rows"], [("label", "trial"), ("sel_ir", "IR 2005-15"), ("oos_ir", "IR OOS"),
                             ("oos_ir_2x", "IR OOS 2x cost"), ("oos_ir_gross", "IR OOS before costs"),
                             ("oos_active_gross_yr", "active/yr before costs"), ("oos_alpha", "alpha OOS"),
                             ("oos_ir_vs_all", "IR vs all-member EW"), ("names_mean_oos", "names/day"),
                             ("turnover_yr", "turnover/yr"), ("deflated_p", "deflated p")]), "",
           "## The pick by year (out of sample)", "",
           table([{"year": str(y), "ir": v, "act": r["active_by_year"][y]} for y, v in r["ir_by_year"].items()],
                 [("year", "year"), ("ir", "IR"), ("act", "active return")]), "",
           f"Expected dates with an actual 8-K within two sessions: {pct(r['prediction_hit'])} of "
           f"{r['candidates_oos']} out-of-sample candidates of the pick's entry rule.", "",
           pool_line(r["pool"]), ""]
    return "\n".join(out)


# ===========================================================================
# 2. Discretionary deletions
# ===========================================================================

DEL_SEL_END = np.datetime64("2013-01-01")
DEL_START = np.datetime64("1996-03-01")
DEL_PERIODS = ((np.datetime64("2013-01-01"), np.datetime64("2018-01-01")),
               (np.datetime64("2018-01-01"), np.datetime64("2022-01-01")),
               (np.datetime64("2022-01-01"), np.datetime64("2100-01-01")))
HAIRCUT, HAIRCUT_PX = 0.30, 5.0


def del_events(ctx: Ctx) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
    """(column, event session) of discretionary deletions and of additions."""
    import polars as pl
    S = ctx.S
    m = pl.read_parquet(er.CACHE / "membership_intervals.parquet")
    col = {s: j for j, s in enumerate(S.names)}
    dels, adds = [], []
    for t, a, b in m.select("ticker", "start", "end").iter_rows():
        if t not in col:
            continue
        j = col[t]
        if b is not None:
            i = int(np.searchsorted(S.dates, np.datetime64(b, "D")))
            if S.dates[min(i, S.T - 1)] >= DEL_START and i + 6 < S.T and S.traded[i + 5, j] \
                    and not S.member[i:i + 6, j].any():
                dels.append((j, i))
        if a is not None:
            i = int(np.searchsorted(S.dates, np.datetime64(a, "D")))
            if i > 0 and S.dates[min(i, S.T - 1)] >= DEL_START and i + 6 < S.T and S.traded[i + 5, j]:
                adds.append((j, i))
    return sorted(set(dels)), sorted(set(adds))


def haircut_returns(P: pn.Panel) -> tuple[np.ndarray, list[int]]:
    """r_oo with a 30 % loss on the last session of a series that ends before the data's last
    day at a last close under 5 USD."""
    R = P.r_oo().copy()
    hit = []
    tr = P.traded
    last = np.where(tr.any(0), P.T - 1 - tr[::-1].argmax(0), -1)
    for j in range(P.N):
        L = last[j]
        if 0 <= L < P.T - 5 and P.close[L, j] < HAIRCUT_PX:
            R[L, j] = (1 + R[L, j]) * (1 - HAIRCUT) - 1
            hit.append(j)
    return R, hit


def del_positions(P: pn.Panel, evs: list[tuple[int, int]], H: int, entry_lag: int = 6,
                  from_day=None, to_day=None) -> tuple[np.ndarray, list[tuple[int, int, int]]]:
    """(T, N) equal weights across live positions, and (column, entry, exit) per event."""
    M = np.zeros((P.T, P.N), dtype=bool)
    tr = P.traded
    last = np.where(tr.any(0), P.T - 1 - tr[::-1].argmax(0), -1)
    spans = []
    for j, i in evs:
        a = i + entry_lag
        if a >= P.T:
            continue
        if from_day is not None and P.dates[a] < from_day:
            continue
        if to_day is not None and P.dates[a] >= to_day:
            continue
        b = min(a + H, last[j] + 1, P.T)
        if b <= a:
            continue
        M[a:b, j] = True
        spans.append((j, a, b))
    n = M.sum(1)
    return M * np.where(n > 0, 1.0 / np.maximum(n, 1), 0.0)[:, None], spans


def event_excess(P: pn.Panel, R: np.ndarray, spans, base: np.ndarray, H: int, bps: float) -> list[dict]:
    out = []
    F = P.fill()
    for j, a, b in spans:
        full = (b - a == H) or b < P.T          # ended by its hold or by its series, not by the data
        if not full:
            continue
        name = float(np.prod(1 + R[a:b, j]) - 1) - 2 * bps * 1e-4 - SEC - TAF / max(float(F[min(b, P.T - 1), j]), 1e-9)
        out.append({"j": j, "entry": a, "excess": name - float(np.prod(1 + base[a:b]) - 1), "ret": name})
    return out


def index_deletions(ctx: Ctx) -> dict:
    S = ctx.S
    dels, adds = del_events(ctx)
    Rh, hit = haircut_returns(S)
    R0 = S.r_oo()
    ew = equal_weight(ctx)
    oos = S.dates >= DEL_SEL_END
    rows, series, evstats = [], {}, {}
    for kind, H in (("D", 63), ("D", 126), ("D", 252), ("D-A", 126), ("D-A", 252)):
        lab = f"{'long deletions' if kind == 'D' else 'deletions minus additions'}, {H} sessions"
        res = {}
        for part, lo, hi in (("sel", None, DEL_SEL_END), ("oos", DEL_SEL_END, None)):
            Wd, sd = del_positions(S, dels, H, 6, lo, hi)
            act_d, _, cost_d = overlay(S, Wd, np.zeros(S.T), DELETED_BPS, 0.0, Rh)
            D = act_d - cost_d
            ex_d = event_excess(S, Rh, sd, ew, H, DELETED_BPS)
            live_d = Wd.sum(1) > 0
            if kind == "D":
                act = np.where(live_d, D - ew, 0.0)
                res[part] = {"book": D, "act": act, "live": live_d, "ev": ex_d}
            else:
                Wa, sa = del_positions(S, adds, H, 6, lo, hi)
                act_a, _, cost_a = overlay(S, Wa, np.zeros(S.T), STOCK_BPS, 0.0, R0)
                A = act_a + cost_a          # a short gains -A and pays the costs
                live_a = Wa.sum(1) > 0
                both = live_d & live_a
                ls = np.where(both, D - act_a - cost_a - BORROW / YEAR, 0.0)
                ex_a = event_excess(S, R0, sa, ew, H, STOCK_BPS)
                res[part] = {"book": ls, "act": ls, "live": both, "ev": ex_d, "ev_a": ex_a, "A": A}
        lbl = {"label": lab, "kind": kind, "H": H}
        for part in ("sel", "oos"):
            z = res[part]
            ed = np.array([e["excess"] for e in z["ev"]])
            ea = np.array([e["excess"] for e in z.get("ev_a", [])])
            lbl[f"{part}_events"] = len(ed)
            lbl[f"{part}_mean_excess"] = float(ed.mean() - (ea.mean() if ea.size else 0.0)) if ed.size else float("nan")
            lbl[f"{part}_sharpe"] = sharpe(z["book"][z["live"]]) if z["live"].any() else 0.0
            lbl[f"{part}_ir"] = sharpe(z["act"][z["live"]]) if z["live"].any() else 0.0
        lbl["sr_obs"] = obs_sharpe(res["oos"]["act"][res["oos"]["live"]]) if res["oos"]["live"].any() else 0.0
        rows.append(lbl)
        series[lab] = res
    pl_ = pool({"index_deletions": [r["sr_obs"] for r in rows]})
    for r in rows:
        z = series[r["label"]]["oos"]
        r["deflated_p"] = deflated(z["act"][z["live"]], pl_) if z["live"].any() else 0.0
    picks = [max((r for r in rows if r["kind"] == "D"), key=lambda r: r["sel_mean_excess"]),
             max((r for r in rows if r["kind"] == "D-A"), key=lambda r: r["sel_mean_excess"])]
    judged = []
    for pk in picks:
        H, kind = pk["H"], pk["kind"]
        z = series[pk["label"]]["oos"]
        ed = np.array([e["excess"] for e in z["ev"]])
        ea = np.array([e["excess"] for e in z.get("ev_a", [])])
        bt = boot_mean(ed, other=ea if kind == "D-A" else None)
        per = []
        for lo, hi in DEL_PERIODS:
            sd_ = np.array([e["excess"] for e in z["ev"] if lo <= S.dates[e["entry"]] < hi])
            sa_ = np.array([e["excess"] for e in z.get("ev_a", []) if lo <= S.dates[e["entry"]] < hi])
            per.append(float(sd_.mean() - (sa_.mean() if sa_.size else 0.0)) if sd_.size else float("nan"))
        # doubled costs and a day later
        Wd2, sd2 = del_positions(S, dels, H, 6, DEL_SEL_END, None)
        ex2 = np.array([e["excess"] for e in event_excess(S, Rh, sd2, ew, H, 2 * DELETED_BPS)])
        Wl, sl = del_positions(S, dels, H, 7, DEL_SEL_END, None)
        exl = np.array([e["excess"] for e in event_excess(S, Rh, sl, ew, H, DELETED_BPS)])
        exn = np.array([e["excess"] for e in event_excess(S, R0, sd2, ew, H, DELETED_BPS)])
        if kind == "D-A":
            Wa2, sa2 = del_positions(S, adds, H, 6, DEL_SEL_END, None)
            a2 = np.array([e["excess"] for e in event_excess(S, R0, sa2, ew, H, 2 * STOCK_BPS)])
            Wal, sal = del_positions(S, adds, H, 7, DEL_SEL_END, None)
            al = np.array([e["excess"] for e in event_excess(S, R0, sal, ew, H, STOCK_BPS)])
            m2, ml = ex2.mean() - a2.mean(), exl.mean() - al.mean()
            mn = exn.mean() - ea.mean()
        else:
            m2, ml, mn = ex2.mean(), exl.mean(), exn.mean()
        live = z["live"]
        book_sr = sharpe(z["book"][live])
        ew_sr = sharpe(ew[live])
        mean_ex = pk["oos_mean_excess"]
        g = {
            "1 mean excess per event above 0, event bootstrap 5 % bound above 0": mean_ex > 0 and bt["p05"] > 0,
            "2 positive in at least 2 of 2013-17, 2018-21, 2022 on": sum(1 for v in per if v > 0) >= 2,
            ("3 book Sharpe above the equal weight's on its days" if kind == "D" else "3 book Sharpe above 0"):
                (book_sr > ew_sr) if kind == "D" else book_sr > 0,
            "4 mean excess above 0 with costs doubled and a day later": m2 > 0 and ml > 0,
        }
        movers = sorted(z["ev"], key=lambda e: -abs(e["excess"]))[:5]
        # Not a gate: a data check. One-day moves above +100 % in a held name are mostly
        # unadjusted reverse splits or stale prices in the source.
        jumps = [e for e in z["ev"] if np.nanmax(R0[e["entry"]:e["entry"] + H, e["j"]]) > 1.0]
        clean = np.array([e["excess"] for e in z["ev"] if e not in jumps])
        robust = {"median": float(np.median(ed)) if ed.size else float("nan"),
                  "trimmed_5": float(stats.trim_mean(ed, 0.05)) if ed.size else float("nan"),
                  "mean_without_jumps": float(clean.mean() - (ea.mean() if ea.size else 0.0)) if clean.size else float("nan"),
                  "jumps": [{"name": S.names[e["j"]], "entry": str(S.dates[e["entry"]]), "excess": e["excess"]}
                            for e in jumps]}
        judged.append({"label": pk["label"], "kind": kind, "gates": g, "passed": all(g.values()),
                       "killed": mean_ex < 0, "confirmed": all(g.values()) and pk["deflated_p"] > 0.95,
                       "boot": bt, "periods": per, "mean_2x": float(m2), "mean_late": float(ml),
                       "mean_no_haircut": float(mn), "book_sharpe": book_sr, "ew_sharpe_same_days": ew_sr,
                       "row": pk, "share_days_live": float(live[oos].mean()), "robust": robust,
                       "movers": [{"name": S.names[e["j"]], "entry": str(S.dates[e["entry"]]),
                                   "excess": e["excess"]} for e in movers],
                       "by_year": _by_year(S, z["ev"])})
    hit_held = sorted({S.names[e["j"]] for r in series.values() for p in ("sel", "oos")
                       for e in r[p]["ev"] if e["j"] in set(hit)})
    res = {"name": "index_deletions", "rows": rows, "judged": judged, "pool": pl_,
           "events": {"deletions": len(dels), "additions": len(adds),
                      "deletions_oos": sum(1 for j, i in dels if S.dates[i] >= DEL_SEL_END),
                      "additions_oos": sum(1 for j, i in adds if S.dates[i] >= DEL_SEL_END)},
           "haircut_names_held": hit_held, "trial_sharpes_obs": [r["sr_obs"] for r in rows]}
    res["markdown"] = del_markdown(res)
    return res


def _by_year(S: pn.Panel, ev: list[dict]) -> dict[int, dict]:
    out: dict[int, list] = {}
    for e in ev:
        out.setdefault(int(bk.years(S.dates[e["entry"]:e["entry"] + 1])[0]), []).append(e["excess"])
    return {y: {"n": len(v), "mean": float(np.mean(v))} for y, v in sorted(out.items())}


def del_markdown(r: dict) -> str:
    out = [f"# S&P 500 discretionary deletions: results ({datetime.now(timezone.utc):%Y-%m-%d})", ""]
    for j in r["judged"]:
        verdict = ("PASS, confirmed" if j["confirmed"] else "PASS, not confirmed (deflation)" if j["passed"]
                   else "KILL" if j["killed"] else "FAIL")
        pk = j["row"]
        out += [f"**{j['label']}: {verdict}.** Out of sample (entries from 2013): {pk['oos_events']} deletion "
                f"events, mean excess over the equal weight {pct(pk['oos_mean_excess'])} per event (event "
                f"bootstrap 90 % band {pct(j['boot']['p05'])} to {pct(j['boot']['p95'])}); by period "
                + ", ".join(pct(v) for v in j["periods"]) + f"; doubled costs {pct(j['mean_2x'])}, a day later "
                f"{pct(j['mean_late'])}, without the delisting haircut {pct(j['mean_no_haircut'])}. Book Sharpe "
                f"{f2(j['book_sharpe'])} on the {pct(j['share_days_live'], 0)} of sessions it holds something "
                f"(equal weight {f2(j['ew_sharpe_same_days'])} on those days). Deflated p "
                f"{f2(pk['deflated_p'], 3)}.", "", gates_md(j["gates"]), "",
                "Excess by year of entry: " + ", ".join(f"{y} {pct(v['mean'], 0)} (n {v['n']})"
                                                       for y, v in j["by_year"].items()) + ".", "",
                "Largest events: " + "; ".join(f"{m['name']} {m['entry']} {pct(m['excess'], 0)}"
                                               for m in j["movers"]) + ".", "",
                f"Data check (not a gate): median deletion excess {pct(j['robust']['median'])}, 5 % trimmed mean "
                f"{pct(j['robust']['trimmed_5'])}; without the events that hold a one-day move above +100 % "
                f"(" + (", ".join(f"{m['name']} {m['entry']}" for m in j["robust"]["jumps"]) or "none")
                + f") the mean excess is {pct(j['robust']['mean_without_jumps'])}.", ""]
    out += ["## All trials", "",
            table(r["rows"], [("label", "trial"), ("sel_events", "events 1996-2012"),
                              ("sel_mean_excess", "mean excess IS"), ("oos_events", "events 2013 on"),
                              ("oos_mean_excess", "mean excess OOS"), ("oos_sharpe", "book Sharpe OOS"),
                              ("oos_ir", "active IR OOS"), ("deflated_p", "deflated p")]), "",
            f"Events: {r['events']['deletions']} discretionary deletions ({r['events']['deletions_oos']} from "
            f"2013), {r['events']['additions']} additions ({r['events']['additions_oos']} from 2013). Held names "
            f"that hit the delisting haircut, either window: {', '.join(r['haircut_names_held']) or 'none'}.", "",
            pool_line(r["pool"]), ""]
    return "\n".join(out)


# ===========================================================================
# 3. Same-calendar-month seasonality
# ===========================================================================

SEAS_SEL = (np.datetime64("2001-01-01"), OOS)
SEAS_LAGS = {"1-5": (range(1, 6), 3), "1-10": (range(1, 11), 5), "1-20": (range(1, 21), 5)}


def monthly(ctx: Ctx) -> tuple[np.ndarray, np.ndarray]:
    """(month-end sessions, (M, N) monthly returns ending there)."""
    me = np.flatnonzero(ctx.me)
    c = ctx.X.c[me]
    r = np.full(c.shape, np.nan)
    with np.errstate(invalid="ignore", divide="ignore"):
        r[1:] = c[1:] / c[:-1] - 1
    return me, r


def seas_signal(ctx: Ctx, lag: str) -> np.ndarray:
    """(T, N) at month ends: mean same-calendar-month return over the lag years (for the next month)."""
    me, r = monthly(ctx)
    years, need = SEAS_LAGS[lag]
    out = np.full((ctx.S.T, ctx.S.N), np.nan)
    for k in range(len(me)):
        vals = [r[k + 1 - 12 * y] for y in years if k + 1 - 12 * y >= 1]
        if len(vals) < need:
            continue
        v = np.vstack(vals)
        cnt = np.isfinite(v).sum(0)
        with np.errstate(invalid="ignore"):
            m = np.nanmean(v, axis=0)
        out[me[k]] = np.where(cnt >= need, m, np.nan)
    return out


def next_month_oo(ctx: Ctx) -> np.ndarray:
    """(T, N) at month ends: open-to-open return from the next fill to the fill after the next month end."""
    me = np.flatnonzero(ctx.me)
    F = ctx.S.fill()
    out = np.full((ctx.S.T, ctx.S.N), np.nan)
    for k in range(len(me) - 1):
        a, b = me[k] + 1, me[k + 1] + 1
        if b < ctx.S.T:
            with np.errstate(invalid="ignore", divide="ignore"):
                out[me[k]] = np.where(ctx.S.alive[a], F[b] / F[a] - 1, np.nan)
    return out


def rank_ic(score: np.ndarray, y: np.ndarray, elig: np.ndarray, days: np.ndarray) -> dict:
    ics = []
    for t in np.flatnonzero(days):
        ok = elig[t] & np.isfinite(score[t]) & np.isfinite(y[t])
        if ok.sum() >= 30:
            ics.append(stats.spearmanr(score[t, ok], y[t, ok])[0])
    a = np.array(ics)
    if a.size < 2:
        return {"mean": float("nan"), "t": float("nan"), "n": int(a.size)}
    return {"mean": float(a.mean()), "t": float(a.mean() / a.std(ddof=1) * math.sqrt(a.size)), "n": int(a.size),
            "share_positive": float((a > 0).mean())}


def ls_series(S: pn.Panel, long_t: dict, short_t: dict, bps: float, lag: int = 1) -> np.ndarray:
    lo, sh = wsim(S, long_t, lag), wsim(S, short_t, lag)
    borrow = np.where(sh.expo > 0, BORROW / YEAR * sh.expo, 0.0)
    return lo.net(bps) - (sh.gross + bps * 1e-4 * sh.tov + sh.fees) - borrow


def seasonality(ctx: Ctx) -> dict:
    S = ctx.S
    ew = equal_weight(ctx)
    ew_late = equal_weight(ctx, lag=2)
    sel = (S.dates >= SEAS_SEL[0]) & (S.dates < SEAS_SEL[1])
    oos = S.dates >= OOS
    y = next_month_oo(ctx)
    rows, store = [], {}
    for lag in SEAS_LAGS:
        sig = seas_signal(ctx, lag)
        top = top_targets(sig, ctx.ok, ctx.me, k=50)
        sim = wsim(S, top)
        lt, st = top_targets(sig, ctx.ok, ctx.me, frac=0.1), top_targets(sig, ctx.ok, ctx.me, frac=0.1, low=True)
        ls = ls_series(S, lt, st, STOCK_BPS)
        x = sim.net(STOCK_BPS)
        act = x - ew
        store[lag] = {"sig": sig, "top": top, "lt": lt, "st": st, "x": x, "act": act, "ls": ls, "sim": sim}
        ic_s = rank_ic(sig, y, ctx.ok, ctx.me & sel)
        ic_o = rank_ic(sig, y, ctx.ok, ctx.me & oos)
        for book, ser in (("top 50", act), ("decile long/short", ls)):
            rows.append({"label": f"lags {lag}, {book}", "lag": lag, "book": book,
                         "sel": sharpe(ser[sel]), "oos": sharpe(ser[oos]),
                         "sel_ic": ic_s["mean"], "sel_ic_t": ic_s["t"], "oos_ic": ic_o["mean"], "oos_ic_t": ic_o["t"],
                         "oos_sharpe_book": sharpe((x if book == "top 50" else ls)[oos]),
                         "sr_obs": obs_sharpe(ser[oos])})
    pl_ = pool({"seasonality": [r["sr_obs"] for r in rows]})
    for r in rows:
        z = store[r["lag"]]
        r["deflated_p"] = deflated((z["act"] if r["book"] == "top 50" else z["ls"])[oos], pl_)
    pick_lag = max((r for r in rows if r["book"] == "decile long/short"), key=lambda r: r["sel"])["lag"]
    z = store[pick_lag]
    ic = rank_ic(z["sig"], y, ctx.ok, ctx.me & oos)
    x2 = z["sim"].net(2 * STOCK_BPS)
    late = wsim(S, z["top"], lag=2).net(STOCK_BPS)
    bt = boot_sharpe(z["act"][oos])
    yrs = per_year(S.dates, z["act"], oos)
    ls_sr = sharpe(z["ls"][oos])
    g = {
        "1 rank IC t above 2": ic["t"] > 2,
        "2 long/short Sharpe above 0.3": ls_sr > 0.3,
        "3 top 50 IR above 0, bootstrap 5 % bound above 0": sharpe(z["act"][oos]) > 0 and bt["p05"] > 0,
        "4 top 50 IR above 0 with costs doubled and a day late":
            sharpe((x2 - ew)[oos]) > 0 and sharpe((late - ew_late)[oos]) > 0,
        "5 top 50 active return positive in more than half the years": sum(v > 0 for v in yrs.values()) > len(yrs) / 2,
    }
    pr_top = next(r for r in rows if r["lag"] == pick_lag and r["book"] == "top 50")
    pr_ls = next(r for r in rows if r["lag"] == pick_lag and r["book"] != "top 50")
    passed = all(g.values())
    res = {"name": "seasonality", "rows": rows, "pick": pick_lag, "gates": g, "passed": passed,
           "killed": ic["t"] < 1, "confirmed": passed and pr_top["deflated_p"] > 0.95 and pr_ls["deflated_p"] > 0.95,
           "ic": ic, "ls_sharpe": ls_sr, "top_ir": sharpe(z["act"][oos]), "top_ir_2x": sharpe((x2 - ew)[oos]),
           "top_ir_late": sharpe((late - ew_late)[oos]), "boot": bt, "active_by_year": yrs,
           "top_sharpe": sharpe(z["x"][oos]), "ew_sharpe": sharpe(ew[oos]), "spy_sharpe": sharpe(ctx.spy[oos]),
           "top_perf": bk.perf(z["x"][oos]), "turnover_yr": float(z["sim"].tov[oos].sum() / (oos.sum() / YEAR)),
           "pool": pl_, "trial_sharpes_obs": [r["sr_obs"] for r in rows]}
    res["markdown"] = seas_markdown(res)
    return res


def seas_markdown(r: dict) -> str:
    verdict = ("PASS, confirmed" if r["confirmed"] else "PASS, not confirmed (deflation)" if r["passed"]
               else "KILL" if r["killed"] else "FAIL")
    pr = next(x for x in r["rows"] if x["lag"] == r["pick"] and x["book"] == "top 50")
    out = [f"# Same-calendar-month seasonality: results ({datetime.now(timezone.utc):%Y-%m-%d})", "",
           f"**Verdict: {verdict}.** Pick (best selection-window long/short Sharpe): lags {r['pick']}. Out of "
           f"sample from 2016: rank IC {f2(r['ic']['mean'], 4)} (t {f2(r['ic']['t'])}, {r['ic']['n']} months), "
           f"decile long/short Sharpe {f2(r['ls_sharpe'])}; top 50 Sharpe {f2(r['top_sharpe'])} "
           f"({pct(r['top_perf']['cagr'])} a year, drawdown {pct(r['top_perf']['max_dd'], 0)}) against the equal "
           f"weight {f2(r['ew_sharpe'])} and SPY {f2(r['spy_sharpe'])}; IR {f2(r['top_ir'])} (bootstrap 90 % band "
           f"{f2(r['boot']['p05'])} to {f2(r['boot']['p95'])}), {f2(r['top_ir_2x'])} with costs doubled, "
           f"{f2(r['top_ir_late'])} a day late; turnover {f2(r['turnover_yr'], 1)} a year. Deflated p (top 50 "
           f"active) {f2(pr['deflated_p'], 3)}.", "",
           "## Gates (the pick's lag set, out of sample)", "", gates_md(r["gates"]), "",
           f"Kill rule (IC t below 1): {'hit' if r['killed'] else 'not hit'}.", "",
           "## All trials", "",
           table(r["rows"], [("label", "trial"), ("sel", "IR / Sharpe 2001-15"), ("oos", "IR / Sharpe OOS"),
                             ("sel_ic", "IC 2001-15"), ("sel_ic_t", "IC t"), ("oos_ic", "IC OOS"),
                             ("oos_ic_t", "IC t OOS"), ("deflated_p", "deflated p")]), "",
           "Top 50 rows show the IR against the equal weight, long/short rows the book's Sharpe.", "",
           "Top 50 active return by year: " + ", ".join(f"{y} {pct(v)}" for y, v in r["active_by_year"].items())
           + ".", "", pool_line(r["pool"]), ""]
    return "\n".join(out)


# ===========================================================================
# 4. Gross profitability plus net share issuance
# ===========================================================================

QI_SEL = (np.datetime64("2011-01-01"), np.datetime64("2018-01-01"))


def split_table(names: list[str]) -> dict[str, list[tuple]]:
    import polars as pl
    px = pl.read_parquet(er.CACHE / "prices.parquet", columns=["date", "ticker", "stock_splits"])
    px = px.filter(pl.col("stock_splits").is_not_null() & (pl.col("stock_splits") > 0)
                   & (pl.col("stock_splits") != 1) & pl.col("ticker").is_in(names))
    out: dict[str, list] = {}
    for d, t, s in px.iter_rows():
        out.setdefault(t, []).append((np.datetime64(d.date() if hasattr(d, "date") else d, "D"), float(s)))
    return {k: sorted(v) for k, v in out.items()}


def qi_signals(ctx: Ctx) -> dict[str, np.ndarray]:
    """(T, N) GP/A, NSI and composite at month ends from 2010."""
    from ..equities import xbrl
    S = ctx.S
    facts = xbrl.load(ctx.cik)
    gpa = xbrl.annual_gpa(facts)
    shr = xbrl.shares_series(facts)
    splits = split_table(S.names)
    G = np.full((S.T, S.N), np.nan)
    Nn = np.full((S.T, S.N), np.nan)
    days = np.flatnonzero(ctx.me & (S.dates >= np.datetime64("2010-01-01")))
    for j, name in enumerate(S.names):
        c = ctx.cik.get(name)
        if c is None:
            continue
        ga = gpa.get(c, [])
        sh = shr.get(c, [])
        sp = splits.get(name, [])
        g_filed = np.array([a for a, _, _ in ga], dtype="datetime64[D]")
        s_filed = np.array([a for a, _, _ in sh], dtype="datetime64[D]")
        for t in days:
            d = S.dates[t]
            if ga:
                k = int(np.searchsorted(g_filed, d, side="left")) - 1
                if k >= 0 and (d - ga[k][1]).astype(int) <= 457:
                    G[t, j] = ga[k][2]
            if sh:
                k = int(np.searchsorted(s_filed, d, side="left")) - 1
                d0 = d - np.timedelta64(365, "D")
                k0 = int(np.searchsorted(s_filed, d0, side="left")) - 1
                if k >= 0 and k0 >= 0 and (d - sh[k][0]).astype(int) <= 183 and (d0 - sh[k0][0]).astype(int) <= 183:
                    e_now, v_now = sh[k][1], sh[k][2]
                    e_then, v_then = sh[k0][1], sh[k0][2]
                    fac = 1.0
                    for sd, ratio in sp:
                        if e_then < sd <= e_now:
                            fac *= ratio
                    if v_then > 0 and v_now > 0 and e_now > e_then:
                        Nn[t, j] = math.log(v_now / (v_then * fac))
    # one column per CIK and day: the most liquid listing
    for t in days:
        seen: dict[int, int] = {}
        for j in np.flatnonzero(np.isfinite(G[t]) | np.isfinite(Nn[t])):
            c = ctx.cik[S.names[j]]
            if c in seen:
                k = seen[c]
                keep, drop = (j, k) if np.nan_to_num(ctx.X.dv50[t, j]) > np.nan_to_num(ctx.X.dv50[t, k]) else (k, j)
                G[t, drop] = np.nan
                Nn[t, drop] = np.nan
                seen[c] = keep
            else:
                seen[c] = j
    G = np.where(ctx.ok, G, np.nan)
    Nn = np.where(ctx.ok, Nn, np.nan)
    C = np.full((S.T, S.N), np.nan)
    for t in days:
        both = np.isfinite(G[t]) & np.isfinite(Nn[t])
        if both.sum() >= 10:
            rg = stats.rankdata(G[t, both]) / both.sum()
            rn = stats.rankdata(-Nn[t, both]) / both.sum()
            C[t, np.flatnonzero(both)] = (rg + rn) / 2
    return {"GP/A": G, "NSI": -Nn, "composite": C, "_nsi_raw": Nn}


def quality_issuance(ctx: Ctx) -> dict:
    S = ctx.S
    sig = qi_signals(ctx)
    sel = (S.dates >= QI_SEL[0]) & (S.dates < QI_SEL[1])
    oos = S.dates >= QI_SEL[1]
    y = next_month_oo(ctx)
    days = ctx.me & (S.dates >= np.datetime64("2010-06-01"))
    rows, store = [], {}
    coverage = {}
    for name in ("GP/A", "NSI", "composite"):
        X = sig[name]
        has = np.isfinite(X)
        uni = {t: np.where(has[t], 1.0 / has[t].sum(), 0.0) for t in np.flatnonzero(days) if has[t].sum() >= 10}
        ewu = wsim(S, uni).net(STOCK_BPS)
        ewu_late = wsim(S, uni, lag=2).net(STOCK_BPS)
        top = top_targets(X, has, days, k=50)
        sim = wsim(S, top)
        x = sim.net(STOCK_BPS)
        act = x - ewu
        ls = ls_series(S, top_targets(X, has, days, frac=0.2), top_targets(X, has, days, frac=0.2, low=True),
                       STOCK_BPS)
        ic_s, ic_o = rank_ic(X, y, has, days & sel), rank_ic(X, y, has, days & oos)
        store[name] = {"top": top, "sim": sim, "x": x, "act": act, "ls": ls, "ewu": ewu, "ewu_late": ewu_late,
                       "uni": uni}
        coverage[name] = {int(yy): float(np.mean([has[t].sum() for t in np.flatnonzero(days & (bk.years(S.dates) == yy))]))
                          for yy in np.unique(bk.years(S.dates[days]))}
        for book, ser in (("top 50", act), ("quintile long/short", ls)):
            rows.append({"label": f"{name}, {book}", "signal": name, "book": book, "sel": sharpe(ser[sel]),
                         "oos": sharpe(ser[oos]), "sel_ic": ic_s["mean"], "oos_ic": ic_o["mean"],
                         "oos_ic_t": ic_o["t"], "sr_obs": obs_sharpe(ser[oos])})
    pl_ = pool({"quality_issuance": [r["sr_obs"] for r in rows]})
    for r in rows:
        z = store[r["signal"]]
        r["deflated_p"] = deflated((z["act"] if r["book"] == "top 50" else z["ls"])[oos], pl_)
    pick = max((r for r in rows if r["book"] == "top 50"), key=lambda r: r["sel"])
    z = store[pick["signal"]]
    # 12-1 momentum top 50 on the same universe
    X = ctx.X
    mom = er._lag_ratio(X.c, 21, 252)
    has = np.isfinite(sig[pick["signal"]])
    mom_sim = wsim(S, top_targets(np.where(has, mom, np.nan), has, days, k=50)).net(STOCK_BPS)
    mom_ir = sharpe((mom_sim - z["ewu"])[oos])
    ir = sharpe(z["act"][oos])
    bt = boot_sharpe(z["act"][oos])
    x2 = z["sim"].net(2 * STOCK_BPS)
    late = wsim(S, z["top"], lag=2).net(STOCK_BPS)
    yrs = per_year(S.dates, z["act"], oos)
    g = {
        "1 IR above 0.3 against its universe's equal weight": ir > 0.3,
        "2 bootstrap 5 % bound of the IR above 0": bt["p05"] > 0,
        "3 IR above the 12-1 momentum top 50 on the same universe": ir > mom_ir,
        "4 IR above 0 with costs doubled and a day late":
            sharpe((x2 - z["ewu"])[oos]) > 0 and sharpe((late - z["ewu_late"])[oos]) > 0,
        "5 Sharpe above the equal weight's and active return positive in more than half the years":
            sharpe(z["x"][oos]) > sharpe(z["ewu"][oos]) and sum(v > 0 for v in yrs.values()) > len(yrs) / 2,
    }
    passed = all(g.values())
    nsi = sig["_nsi_raw"]
    res = {"name": "quality_issuance", "rows": rows, "pick": pick["signal"], "gates": g, "passed": passed,
           "killed": ir < 0.1, "confirmed": passed and pick["deflated_p"] > 0.95, "ir": ir, "boot": bt,
           "ir_2x": sharpe((x2 - z["ewu"])[oos]), "ir_late": sharpe((late - z["ewu_late"])[oos]),
           "mom_ir": mom_ir, "top_sharpe": sharpe(z["x"][oos]), "ewu_sharpe": sharpe(z["ewu"][oos]),
           "spy_sharpe": sharpe(ctx.spy[oos]), "top_perf": bk.perf(z["x"][oos]), "active_by_year": yrs,
           "ls_sharpe": sharpe(z["ls"][oos]), "coverage": coverage,
           "nsi_extreme": int(np.sum(np.abs(np.nan_to_num(nsi)) > 1.0)),
           "pool": pl_, "trial_sharpes_obs": [r["sr_obs"] for r in rows]}
    res["markdown"] = qi_markdown(res)
    return res


def qi_markdown(r: dict) -> str:
    verdict = ("PASS, confirmed" if r["confirmed"] else "PASS, not confirmed (deflation)" if r["passed"]
               else "KILL" if r["killed"] else "FAIL")
    pr = next(x for x in r["rows"] if x["signal"] == r["pick"] and x["book"] == "top 50")
    cov = r["coverage"]
    out = [f"# Gross profitability and net share issuance: results ({datetime.now(timezone.utc):%Y-%m-%d})", "",
           f"**Verdict: {verdict}.** Pick (best selection-window IR of the top 50): {r['pick']}. Out of sample "
           f"from 2018: top 50 Sharpe {f2(r['top_sharpe'])} ({pct(r['top_perf']['cagr'])} a year, drawdown "
           f"{pct(r['top_perf']['max_dd'], 0)}) against its universe's equal weight {f2(r['ewu_sharpe'])} and SPY "
           f"{f2(r['spy_sharpe'])}; IR {f2(r['ir'])} (bootstrap 90 % band {f2(r['boot']['p05'])} to "
           f"{f2(r['boot']['p95'])}), {f2(r['ir_2x'])} with costs doubled, {f2(r['ir_late'])} a day late; 12-1 "
           f"momentum on the same universe IR {f2(r['mom_ir'])}; quintile long/short Sharpe {f2(r['ls_sharpe'])}. "
           f"Deflated p {f2(pr['deflated_p'], 3)}.", "",
           "## Gates (the pick's top 50, out of sample)", "", gates_md(r["gates"]), "",
           f"Kill rule (IR below 0.1): {'hit' if r['killed'] else 'not hit'}.", "",
           "## All trials", "",
           table(r["rows"], [("label", "trial"), ("sel", "IR / Sharpe 2011-17"), ("oos", "IR / Sharpe OOS"),
                             ("sel_ic", "IC 2011-17"), ("oos_ic", "IC OOS"), ("oos_ic_t", "IC t OOS"),
                             ("deflated_p", "deflated p")]), "",
           "Top 50 rows show the IR against the ranked universe's equal weight, long/short rows the book's "
           "Sharpe.", "",
           "Members ranked per month (mean): " + "; ".join(
               f"{k}: " + ", ".join(f"{y} {v:.0f}" for y, v in cov[k].items() if y in (2010, 2012, 2016, 2020, 2024, 2026))
               for k in cov) + ".", "",
           f"Name-months with |NSI| above 1 (log; likely a units error in the filing): {r['nsi_extreme']}.", "",
           "Top 50 active return by year: " + ", ".join(f"{y} {pct(v)}" for y, v in r["active_by_year"].items())
           + ".", "", pool_line(r["pool"]), ""]
    return "\n".join(out)


# ===========================================================================
# 5. Turn of the month and pre-holiday
# ===========================================================================

TOM_SEL_FROM = {"SPY": np.datetime64("1993-02-01"), "QQQ": np.datetime64("2000-01-01"),
                "IWM": np.datetime64("2001-01-01")}
TOM_WINDOWS = ((1, 3), (2, 3), (1, 1))
UNSCHEDULED = (np.datetime64("2001-09-10"), np.datetime64("2012-10-26"))


def tom_panel():
    from . import overnight as on
    series = {s: on.parse_ohlc(on.load_csv(s)) for s in ("SPY", "QQQ", "IWM")}
    return on.build_panel(series)


def tom_masks(dates: np.ndarray) -> dict[str, np.ndarray]:
    from . import overnight as on
    rank, last = on.month_position(dates)
    m = dates.astype("datetime64[M]")
    from_end = np.zeros(len(dates), dtype=int)
    k = 0
    for t in range(len(dates) - 1, -1, -1):
        k = 1 if (t == len(dates) - 1 or m[t + 1] != m[t]) else k + 1
        from_end[t] = k
    out = {}
    for a, b in TOM_WINDOWS:
        out[f"[-{a}, +{b}]"] = (from_end <= a) | (rank <= b)
    d = dates.astype("datetime64[D]")
    pre = np.zeros(len(dates), dtype=bool)
    pre[:-1] = np.busday_count(d[:-1] + np.timedelta64(1, "D"), d[1:]) >= 1
    for u in UNSCHEDULED:
        pre &= d != u
    out["pre-holiday"] = pre
    return out


def tom_book(ret: np.ndarray, hold: np.ndarray, raw: np.ndarray, bps: float) -> np.ndarray:
    """Close to close: held sessions earn their return; a buy (at the close before the first
    held session) and a sale (at the close of the last) pay bps, the sale SEC and TAF too."""
    T = len(ret)
    h = hold & np.isfinite(ret)
    x = np.where(h, ret, 0.0)
    prev = np.r_[False, h[:-1]]
    nxt = np.r_[h[1:], False]
    buy = h & ~prev
    sell = h & ~nxt
    with np.errstate(invalid="ignore", divide="ignore"):
        taf = np.where(np.isfinite(raw) & (raw > 0), TAF / raw, 0.0)
    return x - bps * 1e-4 * (buy.astype(float) + sell.astype(float)) - sell * (SEC + taf)


def turn_of_month(ctx: Ctx | None = None) -> dict:
    P = tom_panel()
    dates = P.dates
    masks = tom_masks(dates)
    oos = dates >= OOS
    rows, store = [], {}
    ret = np.full((P.T, P.N), np.nan)
    with np.errstate(invalid="ignore", divide="ignore"):
        ret[1:] = P.adj[1:] / P.adj[:-1] - 1
    spy = np.nan_to_num(ret[:, P.col("SPY")])
    for win in list(masks):
        etfs = ("SPY",) if win == "pre-holiday" else ("SPY", "QQQ", "IWM")
        for s in etfs:
            j = P.col(s)
            r = ret[:, j]
            x = tom_book(r, masks[win], P.raw_close[:, j], ETF_BPS)
            sel = (dates >= TOM_SEL_FROM[s]) & (dates < OOS)
            lab = f"{s} {win}"
            store[lab] = {"x": x, "r": r, "j": j, "win": win, "s": s}
            rows.append({"label": lab, "sel": sharpe(x[sel]), "oos": sharpe(x[oos]),
                         "oos_bh": sharpe(np.nan_to_num(r[oos])), "expo": float(masks[win][oos].mean()),
                         "oos_cagr": bk.perf(x[oos])["cagr"], "oos_dd": bk.perf(x[oos])["max_dd"],
                         "sr_obs": obs_sharpe(x[oos])})
    pl_ = pool({"turn_of_month": [r["sr_obs"] for r in rows]})
    for r in rows:
        r["deflated_p"] = deflated(store[r["label"]]["x"][oos], pl_)
    pick = max(rows, key=lambda r: r["sel"])
    z = store[pick["label"]]
    r = z["r"]
    m = masks[z["win"]]
    on_, off = r[oos & m & np.isfinite(r)], r[oos & ~m & np.isfinite(r)]
    welch = stats.ttest_ind(on_, off, equal_var=False)
    late_mask = np.r_[False, m[:-1]]
    late = tom_book(r, late_mask, P.raw_close[:, z["j"]], ETF_BPS)
    x2 = tom_book(r, m, P.raw_close[:, z["j"]], 2 * ETF_BPS)
    bt = boot_sharpe(z["x"][oos], spy[oos])
    spy_sr = sharpe(spy[oos])
    g = {
        "1 window sessions above other sessions, Welch t above 2": float(welch.statistic) > 2,
        "2 Sharpe above the ETF's own buy and hold and above SPY's":
            pick["oos"] > pick["oos_bh"] and pick["oos"] > spy_sr,
        "3 bootstrap: Sharpe above SPY's in at least 90 % of draws": bt["above0"] >= 0.90,
        "4 Sharpe above 0 a session later and with costs doubled": sharpe(late[oos]) > 0 and sharpe(x2[oos]) > 0,
    }
    first4 = all(g.values())
    g["5 as a 20 % sleeve, book_portfolio's rule (run only if 1 to 4 hold)"] = None
    sleeve = None
    if first4:
        sleeve = tom_sleeve(dates, z["x"])
        g["5 as a 20 % sleeve, book_portfolio's rule (run only if 1 to 4 hold)"] = bool(sleeve.get("pass"))
    # mean by session of the window, out of sample, SPY
    from . import overnight as on
    rank, _ = on.month_position(dates)
    rs = ret[:, P.col(z["s"])]
    mon = dates.astype("datetime64[M]")
    from_end = np.zeros(len(dates), dtype=int)
    k = 0
    for t in range(len(dates) - 1, -1, -1):
        k = 1 if (t == len(dates) - 1 or mon[t + 1] != mon[t]) else k + 1
        from_end[t] = k
    by_session = {}
    for lab, sel_ in (("-2", from_end == 2), ("-1", from_end == 1), ("+1", rank == 1), ("+2", rank == 2),
                      ("+3", rank == 3), ("other", (from_end > 2) & (rank > 3))):
        v = rs[oos & sel_ & np.isfinite(rs)]
        by_session[lab] = {"mean_bps": float(v.mean() * 1e4) if v.size else float("nan"), "n": int(v.size)}
    passed = all(bool(v) for v in g.values())
    res = {"name": "turn_of_month", "rows": rows, "pick": pick["label"], "gates": g, "passed": passed,
           "killed": float(np.mean(on_)) <= float(np.mean(off)), "confirmed": passed and pick["deflated_p"] > 0.95,
           "welch_t": float(welch.statistic), "mean_on_bps": float(on_.mean() * 1e4),
           "mean_off_bps": float(off.mean() * 1e4), "late_sharpe": sharpe(late[oos]), "sharpe_2x": sharpe(x2[oos]),
           "boot": bt, "spy_sharpe": spy_sr, "by_session": by_session, "sleeve": sleeve,
           "by_year": per_year_sharpe(dates, z["x"], oos), "pool": pl_,
           "trial_sharpes_obs": [r["sr_obs"] for r in rows]}
    res["markdown"] = tom_markdown(res)
    return res


def tom_sleeve(dates: np.ndarray, x: np.ndarray) -> dict:
    """The 20 % sleeve with the crypto books, book_portfolio's rule (registered as gate 5)."""
    return {"pass": False, "note": "not run"}


def tom_markdown(r: dict) -> str:
    verdict = ("PASS, confirmed" if r["confirmed"] else "PASS, not confirmed (deflation)" if r["passed"]
               else "KILL" if r["killed"] else "FAIL")
    pk = next(x for x in r["rows"] if x["label"] == r["pick"])
    out = [f"# Turn of the month and pre-holiday: results ({datetime.now(timezone.utc):%Y-%m-%d})", "",
           f"**Verdict: {verdict}.** Pick (best selection-window Sharpe): {r['pick']}. Out of sample from 2016: "
           f"Sharpe {f2(pk['oos'])} ({pct(pk['oos_cagr'])} a year, drawdown {pct(pk['oos_dd'], 0)}, invested "
           f"{pct(pk['expo'], 0)} of sessions) against the ETF bought and held {f2(pk['oos_bh'])} and SPY "
           f"{f2(r['spy_sharpe'])}; window sessions {f2(r['mean_on_bps'], 1)} bps a day against "
           f"{f2(r['mean_off_bps'], 1)} on the others (Welch t {f2(r['welch_t'])}); a session later "
           f"{f2(r['late_sharpe'])}, costs doubled {f2(r['sharpe_2x'])}; Sharpe above SPY's in "
           f"{pct(r['boot']['above0'], 0)} of bootstrap draws. Deflated p {f2(pk['deflated_p'], 3)}.", "",
           "## Gates (the pick, out of sample)", "", gates_md(r["gates"]), "",
           f"Kill rule (window sessions not above the others): {'hit' if r['killed'] else 'not hit'}.", "",
           "## All trials", "",
           table(r["rows"], [("label", "trial"), ("sel", "Sharpe selection"), ("oos", "Sharpe OOS"),
                             ("oos_bh", "buy and hold OOS"), ("expo", "invested"), ("oos_cagr", "CAGR OOS"),
                             ("oos_dd", "drawdown OOS"), ("deflated_p", "deflated p")]), "",
           "Mean return by session of the month, out of sample (pick's ETF): "
           + ", ".join(f"{k} {f2(v['mean_bps'], 1)} bps (n {v['n']})" for k, v in r["by_session"].items()) + ".", "",
           "Pick's Sharpe by year: " + ", ".join(f"{y} {f2(v)}" for y, v in r["by_year"].items()) + ".", "",
           pool_line(r["pool"]), ""]
    return "\n".join(out)


# ===========================================================================

def run_one(name: str, ctx: Ctx | None) -> dict:
    fn = {"earnings_premium": earnings_premium, "index_deletions": index_deletions, "seasonality": seasonality,
          "quality_issuance": quality_issuance, "turn_of_month": turn_of_month}[name]
    res = fn(ctx)
    md = res.pop("markdown")
    write(name, md, res)
    print(md)
    return res


def main() -> int:
    want = [a for a in sys.argv[1:] if not a.startswith("-")] or list(STUDIES)
    bad = [a for a in want if a not in STUDIES]
    if bad:
        print(f"unknown study: {', '.join(bad)}; known: {', '.join(STUDIES)}", file=sys.stderr)
        return 2
    ctx = load_ctx() if any(w != "turn_of_month" for w in want) else None
    for w in want:
        log(f"--- {w}")
        run_one(w, ctx)
    return 0


if __name__ == "__main__":
    sys.exit(main())
