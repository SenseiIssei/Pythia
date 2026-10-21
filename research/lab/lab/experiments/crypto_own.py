"""Three studies registered together on 2026-10-21 (results/crypto_own_prereg.md):

    python -m lab.experiments.crypto_own                 all three, then the shared gates
    python -m lab.experiments.crypto_own --only delist   one study (gate 6 then uses only its trials)

- delist_hazard (survey O3): a Binance delisting hazard model as an exclusion filter
- kr_premium_xs (survey O4): each coin's own Korean premium as a filter or tilt
- xs_factors: six cross-sectional factors as filters or tilts

All three change the targets of the three Alpaca books (breakout_top10, tsmom_top20,
tsmom_tranches with every coin Alpaca does not list in cash) and are judged out of
sample from 2024 at 35 bps against the book alone (X6's six gates) and against gated
BTC (gate 7). This module holds the shared harness: the panel, the books, the
modifications, the gates, the pool. Results: results/delist_hazard.md,
results/kr_premium_xs.md, results/xs_factors.md and <reports>/<name>/latest.*.
"""

from __future__ import annotations

import argparse
import math
from dataclasses import dataclass, field

import numpy as np
import polars as pl
from scipy import stats

from ..metrics import deflated_sharpe
from . import alpaca_universe as au
from . import director_common as dc
from . import fam_common as fc
from . import gated_btc as gb

LAST_DAY = "2026-10-20"
COST, STRESS = 0.0035, 0.0070
SEED = 20261021
BOOKS = au.BOOKS
ORIGINAL = au.ORIGINAL
YEARS_OOS = (2024, 2025, 2026)
# The pool before this registration (results/polymarket_study.md): 1,124 hand trials,
# Polymarket's 16, the factory ledger. This registration: 94, plus O9's 2 forward trials.
HAND_BEFORE = 1124 + 16
REG_TRIALS = 94
FORWARD_TRIALS = 2
STUDY_TRIALS = {"delist_hazard": 9, "kr_premium_xs": 13, "xs_factors": 72}


# ---------------------------------------------------------------------------
# Context: the panel, the books as they run, gated BTC per book
# ---------------------------------------------------------------------------

@dataclass
class Ctx:
    P: fc.Panel
    ins: np.ndarray
    oos: np.ndarray
    years: np.ndarray
    alp: np.ndarray
    O: dict
    base: dict = field(default_factory=dict)      # (book, ver) -> run tuple (g, tv, ex, held)
    base35: dict = field(default_factory=dict)    # (book, ver) -> net at 35 bps
    G: dict = field(default_factory=dict)         # book -> {"k", "net35", "net70"}


def net(g: np.ndarray, tv: np.ndarray, c: float) -> np.ndarray:
    return g - c * np.r_[0.0, tv[:-1]]


def build_ctx() -> Ctx:
    P = dc.cut_panel(fc.load_panel(), LAST_DAY)
    ins, oos = fc.masks(P)
    ctx = Ctx(P, ins, oos, dc.years_of(P.days), au.alpaca_mask(P), au.originals(P))
    for b in BOOKS:
        for ver in ("live", "twin"):
            run = au.simulate(P, b, start_targets(ctx, b, ver))
            ctx.base[(b, ver)] = run
            ctx.base35[(b, ver)] = net(run[0], run[1], COST)
    ret_btc = np.nan_to_num(P.ret[:, P.btc])
    g1, t1 = gb.sim_gate(ret_btc, P.btc_on, 1.0)
    sd1 = float(net(g1, t1, COST)[ins].std())
    for b in BOOKS:
        k = min(1.0, float(ctx.base35[(b, "live")][ins].std()) / sd1)
        gk, tk = gb.sim_gate(ret_btc, P.btc_on, k)
        ctx.G[b] = {"k": k, "net35": net(gk, tk, COST), "net70": net(gk, tk, STRESS)}
    print("context ready", flush=True)
    return ctx


def start_targets(ctx: Ctx, book: str, ver: str) -> np.ndarray:
    W = ctx.O[book]
    return au.cash_left(W, ctx.alp) if ver == "live" else W


# ---------------------------------------------------------------------------
# Modifications
# ---------------------------------------------------------------------------

def filt(W: np.ndarray, flag: np.ndarray) -> np.ndarray:
    """Flagged coins get a target of 0, also where the book says 'leave as is'."""
    return np.where(flag, 0.0, W)


def tilt(W: np.ndarray, q: np.ndarray) -> np.ndarray:
    """Positive targets times 1.5 - q (q the badness percentile, NaN: unchanged), each row
    scaled back to the sum its positive targets had. 'Leave as is' (NaN) stays."""
    m = np.where(np.isfinite(q), 1.5 - q, 1.0)
    pos = np.isfinite(W) & (W > 0)
    W2 = np.where(pos, W * m, W)
    s0 = np.where(pos, W, 0.0).sum(1, keepdims=True)
    s1 = np.where(pos, W2, 0.0).sum(1, keepdims=True)
    scale = np.where(s1 > 0, s0 / np.where(s1 > 0, s1, 1.0), 1.0)
    return np.where(pos, W2 * scale, W)


def late(M: np.ndarray) -> np.ndarray:
    """Decided at the close of t, applied at the close of t+1."""
    out = np.empty_like(M)
    out[1:] = M[:-1]
    out[0] = False if M.dtype == bool else np.nan
    return out


def apply(ctx: Ctx, book: str, ver: str, form: str, M: np.ndarray) -> tuple:
    W = start_targets(ctx, book, ver)
    W2 = filt(W, M) if form == "filter" else tilt(W, M)
    return au.simulate(ctx.P, book, W2)


def worst_third(q: np.ndarray) -> np.ndarray:
    return np.isfinite(q) & (q > 2 / 3)


def badness(score: np.ndarray, member: np.ndarray) -> np.ndarray:
    """Percentile rank in (0, 1] of score among member each day (higher score = worse)."""
    return fc.xs_rank(score, member)


# ---------------------------------------------------------------------------
# Measuring
# ---------------------------------------------------------------------------

def sharpe(x: np.ndarray) -> float:
    return dc.sharpe(x)


def year_sharpes(ctx: Ctx, x: np.ndarray) -> dict:
    return {y: sharpe(x[ctx.oos & (ctx.years == y)]) for y in YEARS_OOS}


@dataclass
class Trial:
    study: str
    key: str
    book: str | None
    kind: str              # "mod", "late", "twin" or "ls"
    net35: np.ndarray
    base35: np.ndarray | None
    is_sr: float = float("nan")
    oos_sr: float = float("nan")

    @property
    def diff(self) -> np.ndarray | None:
        return None if self.base35 is None else self.net35 - self.base35


def trial(ctx: Ctx, study: str, key: str, book: str | None, kind: str, run: tuple | np.ndarray,
          base35: np.ndarray | None) -> Trial:
    n35 = run if isinstance(run, np.ndarray) else net(run[0], run[1], COST)
    t = Trial(study, key, book, kind, n35, base35)
    t.is_sr = sharpe(n35[ctx.ins])
    t.oos_sr = sharpe(n35[ctx.oos])
    return t


def pick_row(ctx: Ctx, book: str, key: str, run: tuple, late_run: tuple, twin_run: tuple, **tags) -> dict:
    """The six gates against the book alone (gate 6 filled in later) and gate 7 against G."""
    P, oos = ctx.P, ctx.oos
    m35, m70 = net(run[0], run[1], COST), net(run[0], run[1], STRESS)
    b35 = ctx.base35[(book, "live")]
    b70 = net(ctx.base[(book, "live")][0], ctx.base[(book, "live")][1], STRESS)
    l35 = net(late_run[0], late_run[1], COST)
    t35 = net(twin_run[0], twin_run[1], COST)
    tb35 = ctx.base35[(book, "twin")]
    pm, pb = fc.perf(m35[oos]), fc.perf(b35[oos])
    ym, yb = year_sharpes(ctx, m35), year_sharpes(ctx, b35)
    lo, hi, above = dc.boot_band(m35[oos], b35[oos], seed=SEED)
    G = ctx.G[book]
    dG, dGb = m35 - G["net35"], b35 - G["net35"]
    glo, ghi, gabove = dc.boot_band(dG[oos], seed=SEED)
    changed = np.abs(m35 - b35)[oos] > 1e-12
    row = {"book": ORIGINAL[book], "variant": key, **tags,
           "is": sharpe(m35[ctx.ins]), "book_is": sharpe(b35[ctx.ins]),
           "oos": pm["sharpe"], "book_oos": pb["sharpe"], "dd": pm["max_dd"], "book_dd": pb["max_dd"],
           "cagr": pm["cagr"], "book_cagr": pb["cagr"],
           "oos70": sharpe(m70[oos]), "book_oos70": sharpe(b70[oos]),
           "diff_sr": sharpe((m35 - b35)[oos]), "band_lo": lo, "band_hi": hi, "band_above": above,
           "late": sharpe(l35[oos]), "twin": sharpe(t35[oos]), "twin_book": sharpe(tb35[oos]),
           "years_better": int(sum(ym[y] > yb[y] for y in YEARS_OOS)),
           **{f"y{y}": ym[y] for y in YEARS_OOS}, **{f"book_y{y}": yb[y] for y in YEARS_OOS},
           "g_k": G["k"], "g_oos": sharpe(G["net35"][oos]), "dg": sharpe(dG[oos]), "dg_book": sharpe(dGb[oos]),
           "dg_lo": glo, "dg_hi": ghi, "days_changed": float(changed.mean()),
           "expo": float(run[2][oos].mean()), "book_expo": float(ctx.base[(book, "live")][2][oos].mean()),
           "turnover_yr": float(run[1][oos].sum() / (oos.sum() / 365))}
    row["_diff"] = (m35 - b35)[oos]
    row["_m35"] = m35[oos]
    return row


def gates(row: dict) -> dict:
    g = {"1 Sharpe and 2 of 3 years": row["oos"] > row["book_oos"] and row["years_better"] >= 2,
         "2 drawdown": row["dd"] < row["book_dd"],
         "3 band above 0": row["band_lo"] > 0,
         "4 one day late": row["late"] > row["book_oos"],
         "5 twin": row["twin"] >= row["twin_book"],
         "6 deflated improvement": row.get("deflated_diff", 0.0) > 0.95,
         "7 beats gated BTC": row["dg"] > 0}
    return g


def verdict(row: dict) -> None:
    g = gates(row)
    row["gates_failed"] = [k for k, v in g.items() if not v]
    core = all(v for k, v in g.items() if not k.startswith("6"))
    row["passes"] = core
    row["confirmed"] = core and g["6 deflated improvement"] and row.get("deflated_pool", 0.0) > 0.95
    row["verdict"] = ("pass, confirmed" if row["confirmed"] else "pass, experimental") if core else "fail"


# ---------------------------------------------------------------------------
# The pool and deflation
# ---------------------------------------------------------------------------

def deflated(x: np.ndarray, n: int, var: float) -> float:
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    sd = x.std() if len(x) > 1 else 0.0
    if sd == 0:
        return 0.0
    s = x.mean() / sd
    sk, ku = float(stats.skew(x)), float(stats.kurtosis(x, fisher=False))
    if 1 - sk * s + (ku - 1) / 4 * s ** 2 <= 0:
        return 0.0
    return deflated_sharpe(s, len(x), n, var, sk, ku)


def pool(trial_sr: list[float]) -> dict:
    v1, n1 = dc.prior_var(), HAND_BEFORE
    fx = np.clip(dc.factory_sharpes(), -fc.SR_CLIP, fc.SR_CLIP) / math.sqrt(365)
    n2, v2 = len(fx), float(np.var(fx)) if len(fx) > 1 else 0.0
    x = np.clip(np.array(trial_sr, dtype=float), -fc.SR_CLIP, fc.SR_CLIP) / math.sqrt(365)
    v3 = float(np.var(x)) if len(x) > 1 else v1
    n3 = REG_TRIALS + FORWARD_TRIALS
    n = n1 + n2 + n3
    v = (n1 * v1 + n2 * v2 + n3 * v3) / n
    return {"hand_trials": n1, "factory_trials": n2, "registered_trials": n3, "counted_here": len(x),
            "n_total": n, "var": v, "sr0_annual": fc._sr0(v, n) * math.sqrt(365)}


def finalize(results: dict) -> dict:
    """Gate 6 over every counted trial of the studies that ran, the pool, the verdicts."""
    trials: list[Trial] = [t for r in results.values() for t in r["trials"]]
    expected = sum(STUDY_TRIALS[s] for s in results)
    assert len(trials) == expected, (len(trials), expected)
    pl_ = pool([t.oos_sr for t in trials])
    diffs = [t for t in trials if t.diff is not None]
    dsr = np.clip(np.array([sharpe(t.diff[CTX.oos]) for t in diffs]), -fc.SR_CLIP, fc.SR_CLIP) / math.sqrt(365)
    dvar = float(np.var(dsr)) if len(dsr) > 1 else 1.0 / 365
    for r in results.values():
        for row in r["picks"]:
            row["deflated_diff"] = deflated(row.pop("_diff"), REG_TRIALS, dvar)
            row["deflated_pool"] = deflated(row.pop("_m35"), pl_["n_total"], pl_["var"])
            verdict(row)
    return {"pool": pl_, "diff_var": dvar, "n_trials": len(trials)}


# ---------------------------------------------------------------------------
# Writing helpers
# ---------------------------------------------------------------------------

PICK_COLS = ["book", "variant", "is", "book_is", "oos", "book_oos", "oos70", "book_oos70", "cagr_pct", "dd_pct",
             "book_dd_pct", "years_better", "band_lo", "band_hi", "late", "twin", "twin_book", "deflated_diff",
             "deflated_pool", "dg", "dg_lo", "dg_hi", "dg_book", "days_changed_pct", "verdict"]


def pick_table(rows: list[dict]) -> str:
    tab = [{**r, "dd_pct": r["dd"] * 100, "book_dd_pct": r["book_dd"] * 100, "cagr_pct": r["cagr"] * 100,
            "days_changed_pct": r["days_changed"] * 100} for r in rows]
    return dc.table(tab, PICK_COLS)


def gates_lines(rows: list[dict]) -> list[str]:
    out = []
    for r in rows:
        f = ", ".join(r["gates_failed"]) if r["gates_failed"] else "none"
        out.append(f"- **{r['book']} · {r['variant']}**: {r['verdict']}. Sharpe {r['oos']:.2f} against the book's "
                   f"{r['book_oos']:.2f} (difference band {r['band_lo']:.2f} to {r['band_hi']:.2f}), a day late "
                   f"{r['late']:.2f}, twin {r['twin']:.2f} against {r['twin_book']:.2f}, drawdown "
                   f"{r['dd'] * 100:.0f} % against {r['book_dd'] * 100:.0f} %, minus gated BTC {r['dg']:.2f} "
                   f"(the book alone {r['dg_book']:.2f}). Failed: {f}.")
    return out


def pool_line(fin: dict) -> str:
    p = fin["pool"]
    return (f"Pool: {p['n_total']:,} trials ({p['hand_trials']:,} hand before this registration, "
            f"{p['factory_trials']} factory, {p['registered_trials']} registered on 2026-10-21 with O9's 2 forward "
            f"trials); the best noise trial sits at an annual Sharpe of about {p['sr0_annual']:.2f}. Gate 6 deflates "
            f"each improvement over the {REG_TRIALS} trials of the registration at the variance of the "
            f"{fin['n_trials']} trial difference Sharpes computed in this run.")


def ref_rows(ctx: Ctx) -> list[dict]:
    out = []
    for b in BOOKS:
        x = ctx.base35[(b, "live")]
        p = fc.perf(x[ctx.oos])
        G = ctx.G[b]
        out.append({"book": ORIGINAL[b], "is": sharpe(x[ctx.ins]), "oos": p["sharpe"], "dd_pct": p["max_dd"] * 100,
                    "cagr_pct": p["cagr"] * 100, "twin_oos": sharpe(ctx.base35[(b, "twin")][ctx.oos]),
                    "g_k": G["k"], "g_oos": sharpe(G["net35"][ctx.oos]),
                    "minus_g": sharpe((x - G["net35"])[ctx.oos])})
    return out


def refs_table(ctx: Ctx) -> str:
    return dc.table(ref_rows(ctx), ["book", "is", "oos", "cagr_pct", "dd_pct", "twin_oos", "g_k", "g_oos", "minus_g"])


def panel_column(P: fc.Panel, col: str) -> np.ndarray:
    """A column of the cached long panel as a (T, N) matrix aligned with P."""
    p = pl.read_parquet(fc.OUT / "cache" / "daily_panel.parquet", columns=["day", "symbol", col])
    di = {int(d): i for i, d in enumerate(P.days)}
    ni = {n: j for j, n in enumerate(P.names)}
    m = np.full((P.T, P.N), np.nan)
    rows = np.array([di.get(int(d), -1) for d in p["day"].to_numpy()])
    cols = np.array([ni.get(s, -1) for s in p["symbol"].to_list()])
    ok = (rows >= 0) & (cols >= 0)
    m[rows[ok], cols[ok]] = p[col].to_numpy().astype(float)[ok]
    return m


def fwd_log_return(P: fc.Panel, h: int) -> np.ndarray:
    """log(px[t+h] / px[t]); a coin whose series ends inside the horizon keeps the return to
    its last close; NaN where the horizon runs past the panel end for a coin still alive."""
    T, N = P.T, P.N
    ended = P.extra["last"] < T - 1
    last = np.minimum(P.extra["last"], T - 1)
    out = np.full((T, N), np.nan)
    lp = np.log(P.px)
    t_idx = np.arange(T)[:, None]
    tgt = np.minimum(t_idx + h, last[None, :])
    ok = P.alive & ((t_idx + h <= T - 1) | (ended[None, :] & (last[None, :] < t_idx + h)))
    tt_ = np.clip(tgt, 0, T - 1)
    vals = lp[tt_, np.arange(N)[None, :]] - lp
    out[ok] = vals[ok]
    return out


CTX: Ctx  # set in main


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="delist,kr,factors")
    a = ap.parse_args()
    only = {s.strip() for s in a.only.split(",")}
    global CTX
    CTX = build_ctx()
    from . import delist_hazard, kr_premium_xs, xs_factors
    mods = {"delist": delist_hazard, "kr": kr_premium_xs, "factors": xs_factors}
    results = {}
    for k in ("delist", "kr", "factors"):
        if k in only:
            print(f"== {mods[k].NAME}", flush=True)
            results[mods[k].NAME] = mods[k].compute(CTX)
    fin = finalize(results)
    for k in ("delist", "kr", "factors"):
        if k in only:
            mods[k].write(CTX, results[mods[k].NAME], fin)


if __name__ == "__main__":
    main()
