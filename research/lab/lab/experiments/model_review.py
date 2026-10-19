"""X9: the model review's studies, as pre-registered in results/model_review_prereg.md.

    python -m lab.experiments.model_review            # a, b, d, e (c is lab.models.drift_study)
    python -m lab.experiments.model_review --part a   # one part; --refresh rebuilds the M8q holdout

a  M8q's 10 % quantile as an exposure overlay on the three daily books, against
   the same overlay from M8q's own baseline quantile (plain vol targeting) and
   against the book alone.
b  M2's bottom third as a filter on the long-only books (a confirmation of C6).
d  The auto pick's forward penalty, replayed on the books' history.
e  M2 averaged with momentum or low vol, judged by out-of-sample rank IC.

Everything long-only is judged out of sample from 2024 at 35 bps on the books as
the autopilot runs them on Alpaca (unlisted coins in cash), with X6's six gates.
Writes results/model_review_studies.md (the generated part) and
<agent-strategies>/reports/model_review.json.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import polars as pl
from scipy import stats

from . import alpaca_universe as au
from . import fam_breakout
from . import fam_common as fc
from . import flow_overlays as fo

NAME = "model_review"
DAY_US = fc.DAY_US
COSTS = fo.COSTS
BASE = fo.BASE
YEARS_OOS = (2024, 2025, 2026)
BOOKS = fo.BOOKS
ORIGINAL = au.ORIGINAL

# The pool (see the pre-registration): hand trials before this study at the
# variance backed out of the 377-trial bar, the factory's ledger, this study.
PRIOR_TRIALS, PRIOR_SR0 = 377, 2.43
HAND_TRIALS = 875
HERE_TRIALS = 29
TRIALS_A, TRIALS_B, TRIALS_D = 18, 9, 2

# a
WINDOW, WINDOW_MIN = 365, 180
CAP_Q, CAP_SCALE = 0.80, 0.5
PICK_FROM = int(np.datetime64("2021-07-01", "us").astype(np.int64))
# b
M2_CUT = 1 / 3
# d
FORWARD_FACTOR = 0.5
FORWARD_MIN_DAYS = 10
BAND_Q = 0.05
FWD_BOOT_BLOCK, FWD_BOOT_DRAWS = 5, 4000
# e
IC_SEL = (int(np.datetime64("2022-01-01", "us").astype(np.int64)), fc.SPLIT)
NW_LAG = 7
ENTRY_T = 2.0
PASS_T = 2.39
BOOT_DRAWS, BOOT_BLOCK = 5000, 20

RESULTS = Path(__file__).resolve().parents[2] / "results"


# ---------------------------------------------------------------------------
# Shared statistics
# ---------------------------------------------------------------------------

def boot_band(x: np.ndarray, rng: np.random.Generator, y: np.ndarray | None = None,
              draws: int = BOOT_DRAWS, block: int = BOOT_BLOCK) -> tuple[float, float]:
    """5 % and 95 % of the annual Sharpe (or of Sharpe(x) - Sharpe(y) on the same
    resampled days) over stationary-bootstrap resamples."""
    n = len(x)
    idx = np.empty((draws, n), dtype=np.int64)
    idx[:, 0] = rng.integers(0, n, draws)
    jump = rng.random((draws, n)) < 1 / block
    fresh = rng.integers(0, n, (draws, n))
    for i in range(1, n):
        idx[:, i] = np.where(jump[:, i], fresh[:, i], (idx[:, i - 1] + 1) % n)

    def sr(a: np.ndarray) -> np.ndarray:
        s = a[idx]
        sd = s.std(1)
        return np.where(sd > 0, s.mean(1) / np.where(sd > 0, sd, 1) * np.sqrt(365), 0.0)

    v = sr(x) if y is None else sr(x) - sr(y)
    return float(np.percentile(v, 5)), float(np.percentile(v, 95))


def nw_t(x: np.ndarray, lag: int = NW_LAG) -> float:
    """Newey-West t statistic of the mean of x (Bartlett weights)."""
    x = np.asarray(x, float)
    x = x[np.isfinite(x)]
    n = len(x)
    if n < 3:
        return float("nan")
    e = x - x.mean()
    v = float(e @ e) / n
    for k in range(1, min(lag, n - 1) + 1):
        v += 2 * (1 - k / (lag + 1)) * float(e[k:] @ e[:-k]) / n
    return float(x.mean() / math.sqrt(v / n)) if v > 0 else float("nan")


def prior_var() -> float:
    g = 0.5772156649
    z = (1 - g) * stats.norm.ppf(1 - 1 / PRIOR_TRIALS) + g * stats.norm.ppf(1 - 1 / (PRIOR_TRIALS * math.e))
    return (PRIOR_SR0 / math.sqrt(365) / z) ** 2


def pool(mine: list[float]) -> dict:
    """X6's pooled variance with this study's hand count."""
    v1, n1 = prior_var(), HAND_TRIALS
    fx = np.clip(fo.factory_sharpes(), -fc.SR_CLIP, fc.SR_CLIP) / math.sqrt(365)
    n2, v2 = len(fx), float(np.var(fx)) if len(fx) > 1 else 0.0
    x = np.clip(np.array(mine), -fc.SR_CLIP, fc.SR_CLIP) / math.sqrt(365)
    n3, v3 = len(x), float(np.var(x))
    n = n1 + n2 + n3
    v = (n1 * v1 + n2 * v2 + n3 * v3) / n
    return {"hand_trials": n1, "factory_trials": n2, "mine": n3, "n_total": n, "var": v,
            "sr0_annual": fc._sr0(v, n) * math.sqrt(365)}


def trailing(x: np.ndarray, how: str, q: float = 0.5, w: int = WINDOW, min_obs: int = WINDOW_MIN) -> np.ndarray:
    """Trailing median or quantile over the last w values up to and including t (NaN-aware)."""
    out = np.full(len(x), np.nan)
    for t in range(len(x)):
        s = x[max(0, t - w + 1):t + 1]
        s = s[np.isfinite(s)]
        if len(s) >= min_obs:
            out[t] = float(np.median(s)) if how == "median" else float(np.quantile(s, q))
    return out


# ---------------------------------------------------------------------------
# a. M8q as a risk tool
# ---------------------------------------------------------------------------

def m8q_holdout(refresh: bool = False) -> pl.DataFrame:
    """(ts_us, symbol, q10, q10_base): M8q's purged walk-forward predictions of the
    next day's 10 % quantile and its baseline's, from the code as it is."""
    cache = fc.OUT / "cache" / "x9_m8q_holdout.parquet"
    if cache.exists() and not refresh:
        return pl.read_parquet(cache)
    from ..models import core, m8_quantiles as m8q
    ev = core.evaluate(m8q, m8q.load())
    h = ev["holdout"]
    out = pl.DataFrame({"ts_us": h["ts_us"].cast(pl.Int64), "symbol": h["symbol"].cast(pl.Utf8),
                        "q10": core.as_array(h["challenger"])[:, 0], "q10_base": core.as_array(h["baseline_pred"])[:, 0],
                        "target": h["target"].cast(pl.Float64)})
    cache.parent.mkdir(parents=True, exist_ok=True)
    out.write_parquet(cache)
    print(f"  M8q holdout: {out.height} rows, pinball gain {ev.get('gain_pct')}, DM p {ev.get('dm_p')}", flush=True)
    return out


def downside(days: np.ndarray, h: pl.DataFrame, col: str) -> np.ndarray:
    """(T,) D_t = minus the mean over the coins of the 10 % quantile forecast made at the
    close of day t (for day t+1). NaN on days without a forecast."""
    m = h.group_by("ts_us").agg(d=-pl.col(col).mean()).sort("ts_us")
    t = np.searchsorted(days, m["ts_us"].to_numpy())
    ok = (t < len(days)) & (days[np.minimum(t, len(days) - 1)] == m["ts_us"].to_numpy())
    out = np.full(len(days), np.nan)
    out[t[ok]] = m["d"].to_numpy()[ok]
    return out


def rule_scale(D: np.ndarray) -> np.ndarray:
    """min(1, trailing median / D); 1 where there is no forecast or no history."""
    M = trailing(D, "median")
    with np.errstate(invalid="ignore", divide="ignore"):
        s = np.minimum(1.0, M / D)
    return np.where(np.isfinite(s) & (D > 0), s, 1.0)


def rule_cap(D: np.ndarray) -> np.ndarray:
    """0.5 when D is above its trailing 80th percentile, else 1."""
    Q = trailing(D, "quantile", CAP_Q)
    with np.errstate(invalid="ignore"):
        return np.where(np.isfinite(D) & np.isfinite(Q) & (D > Q), CAP_SCALE, 1.0)


RULES = {"scale": rule_scale, "cap": rule_cap}


def describe(P: fc.Panel, name: str, run: tuple, S: np.ndarray, avail: np.ndarray, **tags) -> dict:
    return fo.describe(P, name, run, S, avail, **tags)


def part_a(P: fc.Panel, B: dict, rng: np.random.Generator, refresh: bool = False) -> dict:
    ins, oos = fc.masks(P)
    h = m8q_holdout(refresh)
    D = {"m8q": downside(P.days, h, "q10"), "control": downside(P.days, h, "q10_base")}
    avail = np.zeros(P.T, dtype=bool)
    avail[1:] = np.isfinite(D["m8q"][:-1]) & (P.days[1:] >= PICK_FROM)
    c35 = COSTS[BASE]
    rows, series = [], {}

    def add(key, run, S, **tags):
        r = describe(P, key, run, S, avail, **tags)
        base = B[(tags["book"], tags.get("version", "live"))]
        xb, xo = fo.net(base[0], base[1], c35), fo.net(run[0], run[1], c35)
        r["diff_sr"] = fo.sharpe_d((xo - xb)[oos]) * math.sqrt(365)
        r["mean_scale_oos"] = float(S[oos].mean())
        rows.append(r)
        series[key] = (run, S, xo, xb)
        return r

    Ss = {(src, rule): RULES[rule](D[src]) for src in D for rule in RULES}
    for b in BOOKS:
        g, tv, ex = B[(b, "live")]
        for (src, rule), S in Ss.items():
            run = fo.apply_overlay(g, tv, ex, S)
            add(f"{src} {rule} · {b}", run, run[3], group="A", source=src, rule=rule, book=b)
    picks = []
    for b in BOOKS:
        cand = [r for r in rows if r["book"] == b and r["source"] == "m8q" and r["group"] == "A"]
        pk = max(cand, key=lambda r: r[f"is_{BASE}"] if math.isfinite(r[f"is_{BASE}"]) else -1e9)
        picks.append(pk)
        S = Ss[("m8q", pk["rule"])]
        g, tv, ex = B[(b, "live")]
        late = fo.apply_overlay(g, tv, ex, S, late=1)
        add(pk["variant"] + " · one day late", late, late[3], group="L", source="m8q", rule=pk["rule"], book=b)
        g, tv, ex = B[(b, "twin")]
        tw = fo.apply_overlay(g, tv, ex, S)
        add(pk["variant"] + " · twin", tw, tw[3], group="T", source="m8q", rule=pk["rule"], book=b, version="twin")
    assert len(rows) == TRIALS_A, len(rows)
    diag = {"first_forecast": fo.first_day(P, D["m8q"]),
            "corr_m8q_control_oos": float(np.corrcoef(D["m8q"][oos & np.isfinite(D["m8q"])],
                                                      D["control"][oos & np.isfinite(D["m8q"])])[0, 1]),
            "coverage_q10_oos": float(np.mean(h.filter(pl.col("ts_us") >= fc.SPLIT).select(
                (pl.col("target") <= pl.col("q10")).mean()).item())),
            "coverage_q10_base_oos": float(np.mean(h.filter(pl.col("ts_us") >= fc.SPLIT).select(
                (pl.col("target") <= pl.col("q10_base")).mean()).item()))}
    return {"rows": rows, "series": series, "picks": picks, "diag": diag}


# ---------------------------------------------------------------------------
# b. M2's bottom third as a filter
# ---------------------------------------------------------------------------

def m2_matrices(P: fc.Panel) -> dict[str, np.ndarray]:
    """C6's out-of-sample M2 scores as (T, N) matrices: score, pct, fwd."""
    s = pl.read_parquet(fc.OUT / "cache" / "m2_longonly_scores.parquet")
    di = {int(d): i for i, d in enumerate(P.days)}
    ni = {n: j for j, n in enumerate(P.names)}
    r = np.array([di.get(int(d), -1) for d in s["day"].to_numpy()])
    c = np.array([ni.get(n, -1) for n in s["symbol"].to_list()])
    m = (r >= 0) & (c >= 0)
    out = {}
    for k in ("score", "pct", "fwd"):
        x = np.full((P.T, P.N), np.nan)
        x[r[m], c[m]] = s[k].to_numpy()[m]
        out[k] = x
    return out


def low_mask(pct: np.ndarray, cut: float = M2_CUT, late: int = 0) -> np.ndarray:
    """Coins M2 ranks below `cut` of the day's universe; unscored coins are never low."""
    low = np.isfinite(pct) & (pct < cut)
    if late:
        low = np.r_[np.zeros((late, low.shape[1]), dtype=bool), low[:-late]]
    return low


def filtered_weights(P: fc.Panel, book: str, low: np.ndarray) -> np.ndarray:
    """The original book's targets with M2's filter: momentum drops the coin (slot stays
    empty), breakout cannot enter it (its exit is the book's own)."""
    if book == "breakout":
        top10 = P.top_liquid(10)
        cols = np.flatnonzero(top10.any(0))
        return fam_breakout.breakout_weights(P, cols, top10 & ~low, 20, 10, regime=False)
    W = au.originals(P)[book]
    return np.where(low, 0.0, W)


def part_b(P: fc.Panel, B: dict, rng: np.random.Generator) -> dict:
    ins, oos = fc.masks(P)
    alp = au.alpaca_mask(P)
    S2 = m2_matrices(P)
    first = np.flatnonzero(np.isfinite(S2["pct"]).any(1))[0]
    avail = np.zeros(P.T, dtype=bool)
    avail[first + 1:] = True
    c35 = COSTS[BASE]
    ones = np.ones(P.T)
    rows, series = [], {}
    # The unfiltered breakout through the same builder must equal the original book.
    same = np.allclose(np.nan_to_num(filtered_weights(P, "breakout", np.zeros((P.T, P.N), bool)), nan=-1),
                       np.nan_to_num(au.originals(P)["breakout"], nan=-1))

    def add(key, run, **tags):
        r = describe(P, key, run, ones, avail, **tags)
        base = B[(tags["book"], tags.get("version", "live"))]
        xb, xo = fo.net(base[0], base[1], c35), fo.net(run[0], run[1], c35)
        r["diff_sr"] = fo.sharpe_d((xo - xb)[oos]) * math.sqrt(365)
        rows.append(r)
        series[key] = (run, ones, xo, xb)
        return r

    picks = []
    for b in BOOKS:
        W = filtered_weights(P, b, low_mask(S2["pct"]))
        g, tv, ex, _ = au.simulate(P, b, au.cash_left(W, alp))
        picks.append(add(f"M2 bottom third · {b}", (g, tv, ex), group="B", book=b))
        Wl = filtered_weights(P, b, low_mask(S2["pct"], late=1))
        g, tv, ex, _ = au.simulate(P, b, au.cash_left(Wl, alp))
        add(f"M2 bottom third · {b} · one day late", (g, tv, ex), group="L", book=b)
        g, tv, ex, _ = au.simulate(P, b, W)
        add(f"M2 bottom third · {b} · twin", (g, tv, ex), group="T", book=b, version="twin")
        print(f"  b: {b} done", flush=True)
    assert len(rows) == TRIALS_B, len(rows)

    # Diagnostics: is M2 anti-momentum inside the books' universes, and does its skill live there?
    past = np.full_like(P.px, np.nan)
    with np.errstate(invalid="ignore", divide="ignore"):
        past[28:] = P.px[28:] / P.px[:-28] - 1
    diag = {"builder_matches_original_breakout": bool(same)}
    unis = {"top20 liquid": P.top_liquid(20), "top10 liquid": P.top_liquid(10), "alpaca": P.eligible & alp,
            "whole universe": np.isfinite(S2["score"])}
    for name, U in unis.items():
        corr, ic, bottom = [], [], []
        for t in np.flatnonzero(oos):
            m = U[t] & np.isfinite(S2["score"][t]) & np.isfinite(past[t]) & np.isfinite(S2["fwd"][t])
            if m.sum() < 5:
                continue
            corr.append(stats.spearmanr(S2["score"][t, m], past[t, m])[0])
            ic.append(stats.spearmanr(S2["score"][t, m], S2["fwd"][t, m])[0])
            lo = m & (S2["pct"][t] < M2_CUT)
            if lo.any() and (m & ~lo).any():
                bottom.append(float(S2["fwd"][t, lo].mean() - S2["fwd"][t, m & ~lo].mean()))
        diag[name] = {"days": len(ic), "corr_m2_mom28": float(np.nanmean(corr)) if corr else None,
                      "ic_7d": float(np.nanmean(ic)) if ic else None, "ic_t": nw_t(np.array(ic)) if ic else None,
                      "bottom_third_minus_rest_7d": float(np.mean(bottom)) if bottom else None,
                      "bottom_days": len(bottom)}
    return {"rows": rows, "series": series, "picks": picks, "diag": diag}


# ---------------------------------------------------------------------------
# d. The forward penalty, replayed
# ---------------------------------------------------------------------------

# Lab evidence as the paper books' signals carry it on 2026-10-19 (results files):
# OOS Sharpe (the lower of headline and survivorship-free), Sharpe at 2x cost, deflated p.
EVIDENCE = {"breakout": (1.163, 1.045, 0.0095), "tsmom_daily": (0.481, 0.266, 0.0002),
            "tsmom_tranches": (0.52, 0.41, 0.0)}


def static_score(oos: float, cost2: float, p: float, passed: int = 0, failed: int = 0) -> float:
    """Evidence::score for a lab book without a measured edge or live clearance."""
    s = 1.0 + passed + min(max(oos, 0.0), 2.0) + 0.5 * min(max(cost2, 0.0), 2.0) + min(max(p, 0.0), 1.0)
    return s / (1.0 + failed)


def band_low(x_is: np.ndarray, horizons: np.ndarray, rng: np.random.Generator,
             block: int = FWD_BOOT_BLOCK, draws: int = FWD_BOOT_DRAWS, q: float = BAND_Q) -> dict[int, float]:
    """The q quantile of the compounded return over h days, moving-block bootstrap of x_is."""
    n = len(x_is)
    lx = np.log1p(x_is)
    out = {}
    hmax = int(horizons.max())
    nb = -(-hmax // block)
    starts = rng.integers(0, n - block + 1, (draws, nb))
    idx = (starts[:, :, None] + np.arange(block)[None, None, :]).reshape(draws, nb * block)
    cum = np.cumsum(lx[idx], axis=1)
    for h in horizons:
        out[int(h)] = float(np.expm1(np.quantile(cum[:, int(h) - 1], q)))
    return out


def quarter_index(P: fc.Panel) -> np.ndarray:
    """(T,) index of the day's calendar quarter start in the panel."""
    qs = fo.quarter_starts(P)
    start = np.zeros(P.T, dtype=int)
    for a, b in zip(qs, qs[1:] + [P.T]):
        start[a:b] = a
    return start


def penalised(x: np.ndarray, qstart: np.ndarray, band: dict[int, float], first: int) -> np.ndarray:
    """(T,) bool: at the close of day t the book's return since its quarter's paper start
    (after at least FORWARD_MIN_DAYS days) is below the band for that many days."""
    out = np.zeros(len(x), dtype=bool)
    lx = np.log1p(np.nan_to_num(x))
    c = np.r_[0.0, np.cumsum(lx)]
    for t in range(first, len(x)):
        a = qstart[t]
        days = t - a + 1
        if days < FORWARD_MIN_DAYS or days not in band:
            continue
        ret = math.expm1(c[t + 1] - c[a])
        out[t] = ret < band[days]
    return out


def auto_pick(P: fc.Panel, xs: dict[str, np.ndarray], expo: dict[str, np.ndarray], pen: dict[str, np.ndarray],
              factor: float, cost: float) -> tuple[np.ndarray, np.ndarray]:
    """Daily re-pick over the books: weights proportional to score, the score times
    `factor` on penalised days. Returns the net daily return and the weights."""
    names = list(xs)
    base = np.array([static_score(*EVIDENCE[b]) for b in names])
    T = len(next(iter(xs.values())))
    W = np.zeros((T, len(names)))
    for t in range(T):
        s = base * np.array([factor if pen[b][t] else 1.0 for b in names])
        W[t] = s / s.sum()
    R = np.column_stack([xs[b] for b in names])
    E = np.column_stack([expo[b] for b in names])
    r = np.zeros(T)
    r[1:] = (W[:-1] * R[1:]).sum(1)
    dW = np.abs(np.diff(np.vstack([W[:1], W]), axis=0))
    r[1:] -= cost * (dW[:-1] * E[:-1]).sum(1)
    return r, W


def part_d(P: fc.Panel, B: dict, rng: np.random.Generator) -> dict:
    ins, oos = fc.masks(P)
    c35 = COSTS[BASE]
    first = int(np.flatnonzero(oos)[0])
    qstart = quarter_index(P)
    xs = {b: fo.net(B[(b, "live")][0], B[(b, "live")][1], c35) for b in BOOKS}
    expo = {b: B[(b, "live")][2] for b in BOOKS}
    hz = np.arange(FORWARD_MIN_DAYS, 93)
    is_mask = ins & (P.days >= fc.IS_START)
    bands = {b: band_low(xs[b][is_mask], hz, rng) for b in BOOKS}
    pen = {b: penalised(xs[b], qstart, bands[b], first) for b in BOOKS}
    rows, series = [], {}
    for name, factor in (("penalty 0.5 (today)", FORWARD_FACTOR), ("no penalty", 1.0)):
        r, W = auto_pick(P, xs, expo, pen, factor, c35)
        p = fc.perf(r[oos])
        yr = au.years_of(P)
        row = {"variant": name, "factor": factor, f"oos_{BASE}": p["sharpe"], "cagr_35": p["cagr"],
               "dd_35": p["max_dd"], **{f"y{y}": fc.perf(r[oos & (yr == y)])["sharpe"] for y in YEARS_OOS},
               **{f"w_{b}": float(W[oos, i].mean()) for i, b in enumerate(BOOKS)}}
        rows.append(row)
        series[name] = r
    assert len(rows) == TRIALS_D
    # Does a penalty day predict the book's next 30 days against the other books?
    nxt = {}
    for b in BOOKS:
        rel = []
        others = [o for o in BOOKS if o != b]
        f30 = fo.forward_return(xs[b], 30)
        fo30 = np.mean([fo.forward_return(xs[o], 30) for o in others], axis=0)
        d = f30 - fo30
        m_p = oos & pen[b] & np.isfinite(d)
        m_n = oos & ~pen[b] & np.isfinite(d)
        nxt[b] = {"penalised_days": int((oos & pen[b]).sum()), "oos_days": int(oos.sum()),
                  "next30_rel_when_penalised": float(d[m_p].mean()) if m_p.any() else None,
                  "next30_rel_otherwise": float(d[m_n].mean()) if m_n.any() else None}
        rel.append(nxt[b])
    both = np.mean([pen[b][oos] for b in BOOKS], axis=0)
    diag = {"scores": {b: static_score(*EVIDENCE[b]) for b in BOOKS}, "next30": nxt,
            "share_days_all_penalised": float(np.mean(both == 1.0)),
            "share_days_any_penalised": float(np.mean(both > 0))}
    return {"rows": rows, "series": series, "diag": diag}


# ---------------------------------------------------------------------------
# e. Ensembles, by rank IC
# ---------------------------------------------------------------------------

def pct_rank(x: np.ndarray, m: np.ndarray) -> np.ndarray:
    """Percentile ranks of x among the True entries of m (NaN elsewhere), 0 to 1."""
    out = np.full(len(x), np.nan)
    v = x[m]
    if len(v) > 1:
        out[m] = (stats.rankdata(v) - 1) / (len(v) - 1)
    return out


def daily_ic(signal: np.ndarray, fwd: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """(T,) Spearman IC across coins each day (NaN on days with under 20 coins)."""
    out = np.full(signal.shape[0], np.nan)
    for t in range(signal.shape[0]):
        m = mask[t] & np.isfinite(signal[t]) & np.isfinite(fwd[t])
        if m.sum() >= 20:
            out[t] = stats.spearmanr(signal[t, m], fwd[t, m])[0]
    return out


def bottom_decile(signal: np.ndarray, fwd: np.ndarray, mask: np.ndarray, rows: np.ndarray) -> float:
    """Mean over days of (the bottom decile's mean forward return - the day's mean)."""
    v = []
    for t in np.flatnonzero(rows):
        m = mask[t] & np.isfinite(signal[t]) & np.isfinite(fwd[t])
        if m.sum() < 20:
            continue
        cut = np.quantile(signal[t, m], 0.1)
        with np.errstate(invalid="ignore"):
            lo = m & (signal[t] <= cut)
        v.append(float(fwd[t, lo].mean() - fwd[t, m].mean()))
    return float(np.mean(v)) if v else float("nan")


def ensemble(parts: list[np.ndarray], mask: np.ndarray) -> np.ndarray:
    out = np.full(mask.shape, np.nan)
    for t in range(mask.shape[0]):
        m = mask[t] & np.all([np.isfinite(p[t]) for p in parts], axis=0)
        if m.sum() >= 2:
            out[t] = np.mean([pct_rank(p[t], m) for p in parts], axis=0)
    return out


def part_e(P: fc.Panel) -> dict:
    S2 = m2_matrices(P)
    mask = np.isfinite(S2["score"]) & np.isfinite(S2["fwd"])
    past = np.full_like(P.px, np.nan)
    with np.errstate(invalid="ignore", divide="ignore"):
        past[28:] = P.px[28:] / P.px[:-28] - 1
    sig = {"m2": S2["score"], "momentum28": past, "lowvol30": -P.sigma}
    sel = (P.days >= IC_SEL[0]) & (P.days < IC_SEL[1])
    hold = P.days >= fc.SPLIT
    yr = au.years_of(P)
    ics = {k: daily_ic(v, S2["fwd"], mask) for k, v in sig.items()}
    entry = {}
    for k, ic in ics.items():
        entry[k] = {"sel_ic": float(np.nanmean(ic[sel])), "sel_t": nw_t(ic[sel]),
                    "hold_ic": float(np.nanmean(ic[hold])), "hold_t": nw_t(ic[hold]),
                    "bottom_decile_hold": bottom_decile(sig[k], S2["fwd"], mask, hold)}
    joined = [k for k in ("momentum28", "lowvol30") if entry[k]["sel_ic"] > 0 and entry[k]["sel_t"] > ENTRY_T]
    combos = []
    if entry["m2"]["sel_ic"] > 0 and entry["m2"]["sel_t"] > ENTRY_T:
        for k in joined:
            combos.append(("m2", k))
        if len(joined) == 2:
            combos.append(("m2", *joined))
    tests = []
    for c in combos:
        e = ensemble([sig[k] for k in c], mask)
        ic = daily_ic(e, S2["fwd"], mask)
        diff = ic - ics["m2"]
        years = {y: float(np.nanmean(diff[hold & (yr == y)])) for y in YEARS_OOS}
        bd, bm = bottom_decile(e, S2["fwd"], mask, hold), entry["m2"]["bottom_decile_hold"]
        t = nw_t(diff[hold])
        ok = {"ic above M2": float(np.nanmean(ic[hold])) > entry["m2"]["hold_ic"],
              f"difference t > {PASS_T}": bool(np.isfinite(t) and t > PASS_T),
              "2 of 3 years": sum(v > 0 for v in years.values()) >= 2,
              "bottom decile not weaker": bd <= bm}
        tests.append({"ensemble": " + ".join(c), "hold_ic": float(np.nanmean(ic[hold])),
                      "m2_hold_ic": entry["m2"]["hold_ic"], "diff_t": t, "years_diff": years,
                      "bottom_decile_hold": bd, "m2_bottom_decile_hold": bm,
                      "failed": [k for k, v in ok.items() if not v], "passes": all(ok.values())})
    return {"entry": entry, "joined": joined, "tests": tests}


# ---------------------------------------------------------------------------
# Verdicts and the report
# ---------------------------------------------------------------------------

def gates(P: fc.Panel, part: dict, refs: dict, rng: np.random.Generator,
          control: dict | None = None) -> list[dict]:
    ins, oos = fc.masks(P)
    out = []
    rows = {r["variant"]: r for r in part["rows"]}
    for pk in part["picks"]:
        _, _, xo, xb = part["series"][pk["variant"]]
        late = rows[pk["variant"] + " · one day late"]
        twin = rows[pk["variant"] + " · twin"]
        ref, tref = refs[(pk["book"], "live")], refs[(pk["book"], "twin")]
        lo, hi = boot_band(xo[oos], rng, xb[oos])
        years_better = sum(pk[f"y{y}"] > ref[f"y{y}"] for y in YEARS_OOS)
        g = {
            "1 Sharpe and years": pk[f"oos_{BASE}"] > ref[f"oos_{BASE}"] and years_better >= 2,
            "2 drawdown": pk["dd_35"] < ref["dd_35"],
            "3 band above 0": lo > 0,
            "4 one day late": late[f"oos_{BASE}"] > ref[f"oos_{BASE}"],
            "5 twin": twin[f"oos_{BASE}"] >= tref[f"oos_{BASE}"],
            "6 deflated improvement": pk["deflated_p_diff"] > 0.95,
        }
        v = {"pick": pk["variant"], "book": ORIGINAL[pk["book"]], "rule": pk.get("rule"),
             "is_35": pk[f"is_{BASE}"], "oos_35": pk[f"oos_{BASE}"], "book_oos_35": ref[f"oos_{BASE}"],
             "oos_70": pk["oos_stress 70bps"], "book_oos_70": ref["oos_stress 70bps"],
             "dd": pk["dd_35"], "book_dd": ref["dd_35"], "years_better": years_better,
             "diff_p05": lo, "diff_p95": hi, "late_35": late[f"oos_{BASE}"], "twin_35": twin[f"oos_{BASE}"],
             "twin_book_35": tref[f"oos_{BASE}"], "deflated_p_diff": pk["deflated_p_diff"],
             "deflated_p_pool": pk["deflated_p_pool"]}
        if control is not None:
            c = control[(pk["book"], pk["rule"])]
            v["control_oos_35"] = c[f"oos_{BASE}"]
            g["7 above the control"] = pk[f"oos_{BASE}"] > c[f"oos_{BASE}"]
        v["gates_failed"] = [k for k, ok in g.items() if not ok]
        v["passes"] = all(g.values())
        out.append(v)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--part", default="abde")
    ap.add_argument("--refresh", action="store_true", help="rebuild the M8q holdout")
    args = ap.parse_args()
    rng = np.random.default_rng(20261020)
    P = fc.load_panel()
    ins, oos = fc.masks(P)
    print("books ...", flush=True)
    B = fo.run_books(P)
    refs = {}
    for (b, v), run in B.items():
        refs[(b, v)] = describe(P, f"{ORIGINAL[b]} {v} alone", run, np.ones(P.T), np.ones(P.T, dtype=bool),
                                book=b, version=v, kind="book")
    res: dict = {"panel_end": str(P.days[-1].astype("datetime64[us]").astype("datetime64[D]")),
                 "oos_days": int(oos.sum()), "refs": list(refs.values())}
    parts = {}
    if "a" in args.part:
        print("a: M8q overlay ...", flush=True)
        parts["a"] = part_a(P, B, rng, args.refresh)
    if "b" in args.part:
        print("b: M2 filter ...", flush=True)
        parts["b"] = part_b(P, B, rng)
    if "d" in args.part:
        print("d: forward penalty ...", flush=True)
        parts["d"] = part_d(P, B, rng)
    if "e" in args.part:
        print("e: ensembles ...", flush=True)
        res["e"] = part_e(P)

    # Deflation over everything counted in this study (all three parts run together).
    counted = [r for k in ("a", "b") if k in parts for r in parts[k]["rows"]]
    mine = [r[f"oos_{BASE}"] for r in counted] + [r[f"oos_{BASE}"] for r in parts.get("d", {}).get("rows", [])]
    if counted:
        pl_ = pool(mine)
        diffs = np.clip(np.array([r["diff_sr"] for r in counted]), -fc.SR_CLIP, fc.SR_CLIP) / math.sqrt(365)
        dvar = float(np.var(diffs))
        for k in ("a", "b"):
            if k not in parts:
                continue
            for r in parts[k]["rows"]:
                _, _, xo, xb = parts[k]["series"][r["variant"]]
                r["deflated_p_pool"] = fo.deflated(xo[oos], pl_["n_total"], pl_["var"])
                r["deflated_p_diff"] = fo.deflated((xo - xb)[oos], HERE_TRIALS, dvar)
        res["pool"] = pl_
        res["complete"] = len(mine) == HERE_TRIALS
    if "a" in parts:
        a = parts["a"]
        control = {(r["book"], r["rule"]): r for r in a["rows"] if r.get("source") == "control" and r["group"] == "A"}
        res["a"] = {"rows": a["rows"], "diag": a["diag"],
                    "verdicts": gates(P, a, refs, rng, control)}
    if "b" in parts:
        b = parts["b"]
        res["b"] = {"rows": b["rows"], "diag": b["diag"], "verdicts": gates(P, b, refs, rng)}
    if "d" in parts:
        d = parts["d"]
        x0, x1 = d["series"]["penalty 0.5 (today)"], d["series"]["no penalty"]
        lo, hi = boot_band(x1[oos], rng, x0[oos])
        diffs_d = (x1 - x0)[oos]
        r0, r1 = d["rows"]
        yb = sum(r1[f"y{y}"] > r0[f"y{y}"] for y in YEARS_OOS)
        dp = fo.deflated(diffs_d, HERE_TRIALS, float(np.var(np.clip(
            np.array([r["diff_sr"] for r in counted] or [0.0]), -fc.SR_CLIP, fc.SR_CLIP) / math.sqrt(365))))
        g = {"1 Sharpe and years": r1[f"oos_{BASE}"] > r0[f"oos_{BASE}"] and yb >= 2,
             "2 drawdown": r1["dd_35"] < r0["dd_35"], "3 band above 0": lo > 0, "6 deflated improvement": dp > 0.95}
        res["d"] = {"rows": d["rows"], "diag": d["diag"],
                    "verdict": {"diff_p05": lo, "diff_p95": hi, "years_better": yb, "deflated_p_diff": dp,
                                "gates_failed": [k for k, v in g.items() if not v], "passes": all(g.values())}}
    out = fc.OUT / "reports" / f"{NAME}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(_finite(res), indent=1), encoding="utf-8")
    print("wrote", out, flush=True)
    write(res)


def _finite(x):
    if isinstance(x, float):
        return x if math.isfinite(x) else None
    if isinstance(x, (np.floating,)):
        return _finite(float(x))
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (np.bool_,)):
        return bool(x)
    if isinstance(x, dict):
        return {str(k): _finite(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_finite(v) for v in x]
    return x


def _f(v, nd: int = 2) -> str:
    if v is None or (isinstance(v, float) and not math.isfinite(v)):
        return "n/a"
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, float):
        return f"{v:.{nd}f}"
    return str(v)


def write(res: dict) -> None:
    """The generated part of results/model_review_studies.md."""
    md = ["# X9 model review: the studies\n",
          "Generated by `python -m lab.experiments.model_review` from the pre-registration in "
          "`model_review_prereg.md`. Out of sample from 2024-01-01 to " + res["panel_end"] +
          f" ({res['oos_days']} days), 35 bps per unit of turnover, books as the autopilot runs them on "
          "Alpaca (unlisted coins in cash); the twin is the original book.\n"]
    if "pool" in res:
        p = res["pool"]
        md.append(f"Deflation pool: {p['n_total']} trials ({p['hand_trials']} hand, {p['factory_trials']} factory, "
                  f"{p['mine']} here; noise bar {p['sr0_annual']:.2f}).\n")
    md.append("\n## Books alone\n\n| book | version | OOS 15 | OOS 35 | OOS 70 | drawdown 35 | 2024 | 2025 | 2026 |\n"
              "|---|---|---|---|---|---|---|---|---|\n")
    for r in res["refs"]:
        md.append(f"| {ORIGINAL[r['book']]} | {r['version']} | {_f(r['oos_maker 15bps'])} | {_f(r['oos_taker 35bps'])} | "
                  f"{_f(r['oos_stress 70bps'])} | {_f(r['dd_35'] * 100, 1)} % | {_f(r['y2024'])} | {_f(r['y2025'])} | "
                  f"{_f(r['y2026'])} |\n")
    if "a" in res:
        a = res["a"]
        md.append("\n## a. M8q's 10 % quantile as an exposure overlay\n\n")
        dg = a["diag"]
        md.append(f"Forecasts from {dg['first_forecast']}. Out of sample the realised return fell below M8q's 10 % "
                  f"quantile on {_f(dg['coverage_q10_oos'] * 100, 1)} % of coin-days (baseline "
                  f"{_f(dg['coverage_q10_base_oos'] * 100, 1)} %); the market downside series of M8q and of its "
                  f"baseline correlate {_f(dg['corr_m8q_control_oos'])}.\n\n")
        md.append("| variant | IS 35 | OOS 35 | OOS 70 | drawdown | mean scale | diff Sharpe | 2024 | 2025 | 2026 |\n"
                  "|---|---|---|---|---|---|---|---|---|---|\n")
        for r in a["rows"]:
            md.append(f"| {r['variant']} | {_f(r['is_taker 35bps'])} | {_f(r['oos_taker 35bps'])} | "
                      f"{_f(r['oos_stress 70bps'])} | {_f(r['dd_35'] * 100, 1)} % | {_f(r['mean_scale_oos'])} | "
                      f"{_f(r['diff_sr'])} | {_f(r['y2024'])} | {_f(r['y2025'])} | {_f(r['y2026'])} |\n")
        md.append(_verdicts(a["verdicts"], control=True))
    if "b" in res:
        b = res["b"]
        md.append("\n## b. M2's bottom third as a filter\n\n")
        md.append("| variant | OOS 35 | OOS 70 | drawdown | diff Sharpe | 2024 | 2025 | 2026 |\n|---|---|---|---|---|---|---|---|\n")
        for r in b["rows"]:
            md.append(f"| {r['variant']} | {_f(r['oos_taker 35bps'])} | {_f(r['oos_stress 70bps'])} | "
                      f"{_f(r['dd_35'] * 100, 1)} % | {_f(r['diff_sr'])} | {_f(r['y2024'])} | {_f(r['y2025'])} | "
                      f"{_f(r['y2026'])} |\n")
        md.append(_verdicts(b["verdicts"]))
        md.append("\nDiagnostics from 2024 (not trials): M2 against 28-day momentum and M2's 7-day rank IC by "
                  "universe.\n\n| universe | days | corr(M2, mom28) | IC | IC t | bottom third minus rest, 7d |\n"
                  "|---|---|---|---|---|---|\n")
        for k, v in b["diag"].items():
            if isinstance(v, dict):
                md.append(f"| {k} | {v['days']} | {_f(v['corr_m2_mom28'])} | {_f(v['ic_7d'], 3)} | {_f(v['ic_t'])} | "
                          f"{_f((v['bottom_third_minus_rest_7d'] or float('nan')) * 100, 2)} % |\n")
        md.append(f"\nThe filter's breakout builder reproduces the original book: "
                  f"{_f(b['diag']['builder_matches_original_breakout'])}.\n")
    if "d" in res:
        d = res["d"]
        md.append("\n## d. The auto pick's forward penalty, replayed\n\n")
        md.append("Scores (lab terms only, no passport gate counted): " + ", ".join(
            f"{ORIGINAL[k]} {_f(v)}" for k, v in d["diag"]["scores"].items()) + ".\n\n")
        md.append("| variant | OOS 35 | CAGR | drawdown | 2024 | 2025 | 2026 | " +
                  " | ".join(f"weight {ORIGINAL[b]}" for b in BOOKS) + " |\n|---|---|---|---|---|---|---|" +
                  "---|" * len(BOOKS) + "\n")
        for r in d["rows"]:
            md.append(f"| {r['variant']} | {_f(r['oos_taker 35bps'])} | {_f(r['cagr_35'] * 100, 1)} % | "
                      f"{_f(r['dd_35'] * 100, 1)} % | {_f(r['y2024'])} | {_f(r['y2025'])} | {_f(r['y2026'])} | " +
                      " | ".join(_f(r[f'w_{b}']) for b in BOOKS) + " |\n")
        v = d["verdict"]
        md.append(f"\nNo penalty against today's: band of the Sharpe difference {_f(v['diff_p05'])} to "
                  f"{_f(v['diff_p95'])}, better in {v['years_better']} of 3 years, deflated p of the difference "
                  f"{_f(v['deflated_p_diff'])}; gates failed: {', '.join(v['gates_failed']) or 'none'}.\n\n")
        md.append("| book | penalised days | next 30 days vs the other books, penalised | otherwise |\n|---|---|---|---|\n")
        for b, x in d["diag"]["next30"].items():
            md.append(f"| {ORIGINAL[b]} | {x['penalised_days']} of {x['oos_days']} | "
                      f"{_f((x['next30_rel_when_penalised'] or float('nan')) * 100, 2)} % | "
                      f"{_f((x['next30_rel_otherwise'] or float('nan')) * 100, 2)} % |\n")
        md.append(f"\nAll three books penalised on {_f(d['diag']['share_days_all_penalised'] * 100, 1)} % of days, "
                  f"at least one on {_f(d['diag']['share_days_any_penalised'] * 100, 1)} %.\n")
    if "e" in res:
        e = res["e"]
        md.append("\n## e. Ensembles by rank IC (7-day label, M2's coin-days)\n\n| signal | IC 2022-23 | t | IC from 2024 | t | "
                  "bottom decile from 2024 |\n|---|---|---|---|---|---|\n")
        for k, v in e["entry"].items():
            md.append(f"| {k} | {_f(v['sel_ic'], 3)} | {_f(v['sel_t'])} | {_f(v['hold_ic'], 3)} | {_f(v['hold_t'])} | "
                      f"{_f(v['bottom_decile_hold'] * 100, 2)} % |\n")
        md.append(f"\nJoined M2 (positive selection-window IC with t above {ENTRY_T}): "
                  f"{', '.join(e['joined']) or 'none'}.\n")
        for t in e["tests"]:
            md.append(f"\n- **{t['ensemble']}**: IC {_f(t['hold_ic'], 3)} against M2's {_f(t['m2_hold_ic'], 3)}, "
                      f"difference t {_f(t['diff_t'])}, by year " +
                      ", ".join(f"{y} {_f(v, 4)}" for y, v in t["years_diff"].items()) +
                      f"; bottom decile {_f(t['bottom_decile_hold'] * 100, 2)} % against "
                      f"{_f(t['m2_bottom_decile_hold'] * 100, 2)} %. "
                      + ("Passes." if t["passes"] else f"Fails: {', '.join(t['failed'])}."))
        if not e["tests"]:
            md.append("\nNo ensemble could be formed.\n")
        md.append("\n")
    (RESULTS / f"{NAME}_studies.md").write_text("".join(md), encoding="utf-8", newline="\n")
    print("wrote", RESULTS / f"{NAME}_studies.md", flush=True)


def _verdicts(vs: list[dict], control: bool = False) -> str:
    head = ("\n| pick | OOS 35 | book | OOS 70 | book | drawdown | book | years better | band of diff | late | twin | twin book "
            + ("| control " if control else "") + "| deflated p diff | deflated p pool | gates failed |\n|---|---|---|---|---|---|---|---|---|---|---|---|"
            + ("---|" if control else "") + "---|---|---|\n")
    out = [head]
    for v in vs:
        out.append(f"| {v['pick']} | {_f(v['oos_35'])} | {_f(v['book_oos_35'])} | {_f(v['oos_70'])} | {_f(v['book_oos_70'])} | "
                   f"{_f(v['dd'] * 100, 1)} % | {_f(v['book_dd'] * 100, 1)} % | {v['years_better']} of 3 | "
                   f"{_f(v['diff_p05'])} to {_f(v['diff_p95'])} | {_f(v['late_35'])} | {_f(v['twin_35'])} | "
                   f"{_f(v['twin_book_35'])} | " + (f"{_f(v.get('control_oos_35'))} | " if control else "") +
                   f"{_f(v['deflated_p_diff'])} | {_f(v['deflated_p_pool'])} | "
                   f"{', '.join(v['gates_failed']) or 'none: passes'} |\n")
    return "".join(out)


if __name__ == "__main__":
    main()
