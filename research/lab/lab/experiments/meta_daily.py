"""C14: meta-labeling the daily entries of the breakout book.

    python -m lab.experiments.meta_daily            (--refit-m2 recomputes the cached M2 scores)

Pre-registered in results/meta_daily.md (the part above the marker was
committed before this file existed). The book is `breakout_top10` (Donchian
20/10 on the 10 most liquid coins of each day, no regime, 40 % vol sizing).
A LightGBM classifier sees what is known at the close of a breakout day (M2
score, volatility, breakout strength, volume, BTC regime, breadth, funding,
liquidity) and predicts whether the trade entered at that close ends above a
70 bps round trip at the book's own exit. Quarterly walk-forward from 2021-07,
purged (a fold trains only on trades that closed at least 10 days before it
starts), isotonic calibration on earlier out-of-sample predictions. Three
uses of the probability (skip below average, skip the worst quarter, size by
it) are run through the book's own weight function and fam_common's
simulator and judged from 2024 at Alpaca-like costs against the unfiltered
book, a random-skip null, a twin on the 15 Alpaca coins and a fill a day late.

Writes results/meta_daily.md (below the marker) and
<agent-strategies>/reports/meta_daily.json.
"""

from __future__ import annotations

import json
import math
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from types import SimpleNamespace

import numpy as np
import polars as pl
from scipy import stats

from . import fam_breakout, fam_common as fc
from . import regime_hmm as rh
from . import tsmom_tranches as tt

NAME = "meta_daily"
MARKER = "<!-- generated below by lab.experiments.meta_daily; edit above this line only -->"
ENTRY_N, EXIT_N, SLOTS, TOP_BOOK, TOP_EVENTS = 20, 10, 10, 10, 30
START = 60
ROUND_TRIP = 0.0070                      # Alpaca taker 25 bps plus about 10 bps slippage, per side
COSTS = {"maker 15bps": 0.0015, "taker 35bps": 0.0035, "41bps": 0.0041}
BASE = "taker 35bps"
EMBARGO_D = 10
MIN_CAL = 100
Z_CAP = 1.5
FIRST_TEST = int(datetime(2021, 7, 1, tzinfo=timezone.utc).timestamp() * 1e6)
M2_FIRST_TEST = int(datetime(2020, 10, 1, tzinfo=timezone.utc).timestamp() * 1e6)
AUC_FROM = int(datetime(2022, 1, 1, tzinfo=timezone.utc).timestamp() * 1e6)
YEARS = (2022, 2023, 2024, 2025, 2026)
YEARS_OOS = (2024, 2025, 2026)
PARAMS = dict(objective="binary", n_estimators=200, learning_rate=0.03, num_leaves=7, min_child_samples=30,
              subsample=0.8, subsample_freq=1, colsample_bytree=0.8, reg_lambda=5.0, n_jobs=4, verbose=-1,
              random_state=0)
FEATURES = ["m2_score", "m2_rank",
            "vol30", "vol7_30", "rv1_30", "har_vol",
            "bo_dist", "range_pos", "ret_vol", "r7", "r28", "vol_surge",
            "btc_ma200", "btc_r28", "breadth50", "breadth_bo",
            "fund7", "fund7_mkt",
            "age", "log_adv28", "liq_rank"]
USES = ("S1", "S2", "Z")
DIAGNOSTIC = ("raw half", "raw quarter")          # not registered, not counted, cannot pass anything
REFERENCE = ("unfiltered", "unfiltered · a day late (reference)")
NULL_DRAWS, BOOT_DRAWS = 1000, 4000
AUC_BOOT = 2000
PRIOR_TRIALS = 265
HERE_TRIALS = 10


# ---------------------------------------------------------------------------
# The book, with an entry filter
# ---------------------------------------------------------------------------

def book_weights(P, cols: np.ndarray, allowed: np.ndarray, mult: np.ndarray | None = None,
                 n: int = ENTRY_N, slots: int = SLOTS) -> tuple[np.ndarray, np.ndarray]:
    """fam_breakout.breakout_weights (regime off) with each entry's size multiplied by mult[t, j].

    An entry whose multiplier is 0 is skipped; the coin can enter on a later
    signal day. Returns (W, entered), entered (T, N) bool marks the entries made.
    """
    px = P.px[:, cols]
    hi = fc.rolling_extreme(px, n, "max")
    lo = fc.rolling_extreme(px, n // 2, "min")
    with np.errstate(invalid="ignore"):
        enter = (px > hi) & allowed[:, cols]
        leave = (px < lo) | ~P.alive[:, cols]
    with np.errstate(invalid="ignore", divide="ignore"):
        size = np.minimum(fam_breakout.COIN_VOL / (P.sigma[:, cols] * np.sqrt(365)) / slots, 1.0 / slots)
    size = np.nan_to_num(size)
    if mult is not None:
        size = size * np.clip(np.nan_to_num(mult[:, cols], nan=1.0), 0.0, None)
    T, N = P.px.shape
    W = np.full((T, N), np.nan)
    entered = np.zeros((T, N), dtype=bool)
    held = np.zeros(len(cols), dtype=bool)
    for t in range(T):
        row = np.full(len(cols), np.nan)
        ex = held & leave[t]
        en = ~held & enter[t] & (size[t] > 0)
        row[ex] = 0.0
        row[en] = size[t, en]
        held = (held & ~ex) | en
        W[t, cols] = row
        entered[t, cols] = en
    W[:, np.setdiff1d(np.arange(N), cols)] = 0.0
    return W, entered


def candidates(P, cols: np.ndarray, allowed: np.ndarray, mult: np.ndarray | None = None,
               n: int = ENTRY_N) -> np.ndarray:
    """Cells where the book (with this filter) faced an entry decision: signal, allowed, not held."""
    px = P.px[:, cols]
    hi = fc.rolling_extreme(px, n, "max")
    lo = fc.rolling_extreme(px, n // 2, "min")
    with np.errstate(invalid="ignore"):
        enter = (px > hi) & allowed[:, cols] & np.isfinite(P.sigma[:, cols]) & (P.sigma[:, cols] > 0)
        leave = (px < lo) | ~P.alive[:, cols]
    m = np.ones_like(px) if mult is None else np.nan_to_num(mult[:, cols], nan=1.0)
    out = np.zeros(P.px.shape, dtype=bool)
    held = np.zeros(len(cols), dtype=bool)
    for t in range(px.shape[0]):
        ex = held & leave[t]
        cand = ~held & enter[t]
        en = cand & (m[t] > 0)
        held = (held & ~ex) | en
        out[t, cols] = cand
    return out


def late(W: np.ndarray, k: int = 1) -> np.ndarray:
    """The same decisions filled k closes late (the first k rows leave everything as it is)."""
    out = np.full_like(W, np.nan)
    out[k:] = W[:-k]
    return out


def sub_panel(P, cols: np.ndarray):
    """What fam_common.simulate reads, restricted to some columns (the others carry no weight)."""
    return SimpleNamespace(traded=P.traded[:, cols], perp_ok=P.perp_ok[:, cols], ret=P.ret[:, cols],
                           funding=P.funding[:, cols], alive=P.alive[:, cols])


def run_book(P, cols: np.ndarray, W: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    g, tv, le, _ = fc.simulate(sub_panel(P, cols), W[:, cols], start=START)
    return g, tv, le


# ---------------------------------------------------------------------------
# Events and labels
# ---------------------------------------------------------------------------

def signals(P, n: int = ENTRY_N) -> np.ndarray:
    """Close above the highest close of the previous n days, with a usable vol (the book sizes by it)."""
    hi = fc.rolling_extreme(P.px, n, "max")
    with np.errstate(invalid="ignore"):
        return (P.px > hi) & np.isfinite(P.sigma) & (P.sigma > 0)


def exits(P, n: int = ENTRY_N) -> tuple[np.ndarray, np.ndarray]:
    """For a trade entered at the close of every cell: (exit row, trade return), -1 / NaN if still open.

    The exit is the first later close below the lowest close of the previous
    n/2 days, or the coin's last close if its series ends first.
    """
    T, N = P.px.shape
    lo = fc.rolling_extreme(P.px, n // 2, "min")
    with np.errstate(invalid="ignore"):
        leave = (P.px < lo) | ~P.alive
    last = np.where(P.alive.any(0), T - 1 - np.argmax(P.alive[::-1], 0), -1)
    ex = np.full((T, N), -1, dtype=np.int64)
    nxt = np.full(N, -1, dtype=np.int64)
    for t in range(T - 1, -1, -1):
        ex[t] = nxt
        nxt = np.where(leave[t], t, nxt)
    # A non-alive exit row means the series ended: the trade closes at its last close.
    j = np.broadcast_to(np.arange(N), (T, N))
    # (Entered at the very last close: closed at once, return 0.)
    dead = (ex >= 0) & ~P.alive[np.maximum(ex, 0), j]
    ex = np.where(dead, last[None, :], ex)
    ex = np.where((ex >= 0) & P.alive & ((ex > np.arange(T)[:, None]) | dead), ex, -1)
    with np.errstate(invalid="ignore", divide="ignore"):
        r = np.where(ex >= 0, P.px[np.maximum(ex, 0), j] / P.px - 1, np.nan)
    return ex, r


def training_events(sig: np.ndarray, allowed: np.ndarray, ex: np.ndarray) -> np.ndarray:
    """Per coin, the book's state machine on `allowed`: a new event only after the previous one exited.

    Events whose trade is still open end the coin's sequence (no label, and no
    later event could be known not to overlap)."""
    T, N = sig.shape
    ev = np.zeros((T, N), dtype=bool)
    cand = sig & allowed
    for j in range(N):
        free = 0
        for t in np.flatnonzero(cand[:, j]):
            if t < free:
                continue
            ev[t, j] = True
            if ex[t, j] < 0:
                break
            free = ex[t, j] + 1
    return ev


# ---------------------------------------------------------------------------
# Features (all known at the close of day t)
# ---------------------------------------------------------------------------

def features(P, m2: np.ndarray | None = None, sig: np.ndarray | None = None) -> dict[str, np.ndarray]:
    T, N = P.px.shape
    rv, qv = P.extra["rv"], P.extra["qv"]
    sig = signals(P) if sig is None else sig
    f: dict[str, np.ndarray] = {}
    m2 = np.full((T, N), np.nan) if m2 is None else m2
    f["m2_score"] = m2
    f["m2_rank"] = fc.xs_rank(m2, P.eligible)
    with np.errstate(invalid="ignore", divide="ignore"):
        rv7 = fc.rolling(rv, 7, 5)
        rv30 = fc.rolling(rv, 30, 20)
        f["vol30"] = P.sigma
        f["vol7_30"] = np.sqrt(rv7) / P.sigma
        f["rv1_30"] = np.sqrt(rv) / P.sigma
        f["har_vol"] = np.sqrt((rv + rv7 + rv30) / 3)
        hi = fc.rolling_extreme(P.px, ENTRY_N, "max")
        lo = fc.rolling_extreme(P.px, ENTRY_N, "min")
        f["bo_dist"] = np.log(P.px / hi) / P.sigma
        f["range_pos"] = (P.px - lo) / (hi - lo)
        f["ret_vol"] = P.ret / P.sigma
        lp = np.log(P.px)
        for k in (7, 28):
            r = np.full((T, N), np.nan)
            r[k:] = lp[k:] - lp[:-k]
            f[f"r{k}"] = r
        q = np.where(P.alive, qv, np.nan)
        prev = np.full((T, N), np.nan)
        prev[1:] = fc.rolling(q, 20, 15)[:-1]
        f["vol_surge"] = q / prev
        bpx = P.px[:, P.btc]
        ma = fc.rolling(bpx[:, None], 200, 200)[:, 0]
        br = np.full(T, np.nan)
        br[28:] = np.log(bpx[28:] / bpx[:-28])
        top50 = P.top_liquid(50)
        above = P.px > fc.rolling(P.px, 50, 40)
        breadth50 = (above & top50).sum(1) / np.maximum(top50.sum(1), 1)
        top30 = P.top_liquid(TOP_EVENTS)
        breadth_bo = (sig & top30).sum(1) / np.maximum(top30.sum(1), 1)
        fund = np.where(P.perp_ok, P.funding, np.nan)
        fund7 = np.where(P.perp_ok, fc.rolling(fund, 7, 1, "sum"), np.nan)
        top20 = P.top_liquid(20)
        f20 = np.where(top20 & np.isfinite(fund7), fund7, np.nan)
        cnt = np.isfinite(f20).sum(1)
        fmkt = np.where(cnt > 0, np.nansum(f20, 1) / np.maximum(cnt, 1), np.nan)
        for k, v in (("btc_ma200", bpx / ma), ("btc_r28", br), ("breadth50", breadth50),
                     ("breadth_bo", breadth_bo), ("fund7_mkt", fmkt)):
            f[k] = np.broadcast_to(v[:, None], (T, N))
        f["fund7"] = fund7
        f["age"] = np.where(P.alive, P.age, np.nan).astype(float)
        f["log_adv28"] = np.log(P.adv28)
        score = np.where(P.eligible, P.adv28, -np.inf)
        rank = np.argsort(np.argsort(-score, axis=1), axis=1) + 1
        f["liq_rank"] = np.where(P.eligible, rank, np.nan).astype(float)
    assert set(f) == set(FEATURES)
    return f


def design(f: dict[str, np.ndarray], ti: np.ndarray, ji: np.ndarray) -> np.ndarray:
    return np.column_stack([f[k][ti, ji] for k in FEATURES]).astype(np.float64)


def m2_scores(refit: bool = False) -> pl.DataFrame:
    """picks.py's out-of-sample LambdaRank score per (day, coin segment), walk-forward from 2020-10."""
    cache = fc.OUT / "cache" / "meta_daily_m2.parquet"
    if refit or not cache.exists():
        import lightgbm as lgb

        from ..cv import walk_forward
        from . import picks
        raw = picks.build_raw(with_perp=False)
        R = picks.rank_cross_section(raw, picks.FEATURES)
        days = R["day"].to_numpy()
        X = R.select(picks.FEATURES).to_numpy().astype(np.float32)
        y = R["label"].to_numpy()
        fwd = R["fwd"].to_numpy()
        score = np.full(len(y), np.nan)
        for fold in walk_forward(days, M2_FIRST_TEST, embargo_h=picks.HORIZON * 24):
            tr = fold.train & np.isfinite(fwd)
            if tr.sum() < 1000:
                continue
            order = np.argsort(days[tr], kind="stable")
            _, group = np.unique(days[tr][order], return_counts=True)
            m = lgb.LGBMRanker(**picks.PARAMS).fit(X[tr][order], y[tr][order].astype(np.int32), group=group)
            score[fold.test] = m.predict(X[fold.test])
            print(f"  M2 {fold.name}: {int(tr.sum()):,} train rows", flush=True)
        ok = np.isfinite(score)
        cache.parent.mkdir(parents=True, exist_ok=True)
        pl.DataFrame({"day": days[ok], "symbol": R["symbol"].to_numpy()[ok], "score": score[ok]}).write_parquet(cache)
    return pl.read_parquet(cache)


def m2_matrix(P, refit: bool = False) -> np.ndarray:
    s = m2_scores(refit)
    di = {int(d): i for i, d in enumerate(P.days)}
    ni = {n: j for j, n in enumerate(P.names)}
    m = np.full(P.px.shape, np.nan)
    for d, sym, v in zip(s["day"].to_numpy(), s["symbol"].to_list(), s["score"].to_numpy()):
        t, j = di.get(int(d)), ni.get(sym)
        if t is not None and j is not None:
            m[t, j] = v
    return m


# ---------------------------------------------------------------------------
# Walk-forward meta-model
# ---------------------------------------------------------------------------

@dataclass
class Meta:
    p: np.ndarray        # (T, N) calibrated probability on predicted cells, NaN elsewhere
    raw: np.ndarray      # (T, N) raw probability
    pbar: np.ndarray     # (T, N) the fold's training base rate
    thr25: np.ndarray    # (T, N) the fold's S2 threshold
    folds: list
    importance: dict
    q_raw: np.ndarray | None = None   # (T, N, 2) 25th and 50th percentile of the calibration set's raw scores


def quarter_starts(days: np.ndarray, first: int) -> list[int]:
    from ..cv import quarter_starts as qs
    return [s for s in qs(int(days.min()), int(days.max())) if s >= first]


def isotonic(x: np.ndarray, y: np.ndarray):
    from sklearn.isotonic import IsotonicRegression
    return IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip").fit(x, y)


def walk_forward(P, f: dict[str, np.ndarray], ev: np.ndarray, pred: np.ndarray, ex: np.ndarray,
                 label: np.ndarray, first: int = FIRST_TEST, params: dict | None = None,
                 log: bool = True) -> Meta:
    """Quarterly folds from `first`. A fold starting at s trains on the events (ev) whose label is
    known (ex >= 0) and whose exit is at least EMBARGO_D days before s, and predicts every cell of
    `pred` inside the quarter. Calibration: isotonic on earlier folds' out-of-sample predictions of
    events resolved by the same cutoff (at least MIN_CAL, else raw)."""
    import lightgbm as lgb
    params = PARAMS if params is None else params
    T, N = ev.shape
    days = P.days
    ex_day = np.where(ex >= 0, days[np.maximum(ex, 0)], np.iinfo(np.int64).max)
    p = np.full((T, N), np.nan)
    raw = np.full((T, N), np.nan)
    pbar = np.full((T, N), np.nan)
    thr = np.full((T, N), np.nan)
    qraw = np.full((T, N, 2), np.nan)
    eti, etj = np.nonzero(ev & (ex >= 0))
    Xe, ye, exd, ed = design(f, eti, etj), label[eti, etj], ex_day[eti, etj], days[eti]
    oos_raw = np.full(len(eti), np.nan)      # out-of-sample raw prediction of each event, once made
    starts = quarter_starts(days, first)
    folds, gains = [], np.zeros(len(FEATURES))
    for k, s in enumerate(starts):
        e = starts[k + 1] if k + 1 < len(starts) else int(days.max()) + 1
        cut = s - EMBARGO_D * fc.DAY_US
        tr = (exd <= cut) & (ed < s)
        rows = (days >= s) & (days < e)
        ti, tj = np.nonzero(pred & rows[:, None])
        if tr.sum() < 200 or len(ti) == 0 or len(np.unique(ye[tr])) < 2:
            continue
        m = lgb.LGBMClassifier(**params).fit(Xe[tr], ye[tr])
        gains += m.booster_.feature_importance("gain")
        r = m.predict_proba(design(f, ti, tj))[:, 1]
        base = float(ye[tr].mean())
        cal = np.isfinite(oos_raw) & (exd <= cut)
        if cal.sum() >= MIN_CAL:
            iso = isotonic(oos_raw[cal], ye[cal])
            pc = iso.predict(r)
            t25 = float(np.percentile(iso.predict(oos_raw[cal]), 25))
            qr = np.percentile(oos_raw[cal], [25, 50])
        else:
            # Too few earlier out-of-sample events: raw probabilities, and the S2 cut from the
            # model's own predictions on its training events (not registered; first folds only).
            pc = r
            t25 = float(np.percentile(m.predict_proba(Xe[tr])[:, 1], 25))
            qr = np.percentile(m.predict_proba(Xe[tr])[:, 1], [25, 50])
        raw[ti, tj], p[ti, tj], pbar[ti, tj], thr[ti, tj] = r, pc, base, t25
        qraw[ti, tj] = qr
        # Remember the out-of-sample predictions of this quarter's events for later calibration.
        evq = (ed >= s) & (ed < e)
        if evq.any():
            oos_raw[evq] = m.predict_proba(Xe[evq])[:, 1]
        d = datetime.fromtimestamp(s / 1e6, tz=timezone.utc)
        row = {"fold": f"{d.year}Q{(d.month - 1) // 3 + 1}", "train_events": int(tr.sum()), "base_rate": base,
               "calibrated": bool(cal.sum() >= MIN_CAL), "cal_events": int(cal.sum()), "pred_cells": int(len(ti)),
               "test_events": int(evq.sum()), "s2_cut": t25}
        yq = ye[evq]
        row["auc"] = auc(oos_raw[evq], yq) if len(np.unique(yq)) == 2 else float("nan")
        folds.append(row)
        if log:
            print(f"  meta {row['fold']}: train {row['train_events']}, base {base:.2f}, "
                  f"cal {row['cal_events']}, auc {row['auc']:.3f}", flush=True)
    imp = dict(zip(FEATURES, (gains / max(gains.sum(), 1e-12)).tolist()))
    return Meta(p, raw, pbar, thr, folds, imp, qraw)


def multipliers(meta: Meta, use: str) -> np.ndarray:
    """Entry multiplier per cell: 1 where there is no prediction (the book unchanged)."""
    p, pbar = meta.p, meta.pbar
    has = np.isfinite(p)
    with np.errstate(invalid="ignore", divide="ignore"):
        if use == "S1":
            m = (p >= pbar).astype(float)
        elif use == "S2":
            m = (p > meta.thr25).astype(float)
        elif use == "Z":
            m = np.clip(p / pbar, 0.0, Z_CAP)
        elif use in ("raw half", "raw quarter"):
            # Unregistered diagnostic: skip the cells whose raw score is in the calibration set's
            # bottom half or quarter (raw scores have no isotonic ties).
            m = (meta.raw >= meta.q_raw[..., 1 if use == "raw half" else 0]).astype(float)
        else:
            raise ValueError(use)
    return np.where(has, m, 1.0)


# ---------------------------------------------------------------------------
# Measuring
# ---------------------------------------------------------------------------

def auc(s: np.ndarray, y: np.ndarray) -> float:
    """Mann-Whitney AUC with ties counted half."""
    y = np.asarray(y).astype(bool)
    n1, n0 = int(y.sum()), int((~y).sum())
    if n1 == 0 or n0 == 0:
        return float("nan")
    r = stats.rankdata(s)
    return float((r[y].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def auc_band(s: np.ndarray, y: np.ndarray, block: np.ndarray, rng: np.random.Generator,
             draws: int = AUC_BOOT) -> tuple[float, float]:
    """5 % and 95 % of the AUC over a bootstrap of whole blocks of events (calendar months)."""
    ub = np.unique(block)
    idx = [np.flatnonzero(block == b) for b in ub]
    out = []
    for _ in range(draws):
        pick = rng.integers(0, len(ub), len(ub))
        sel = np.concatenate([idx[i] for i in pick])
        a = auc(s[sel], y[sel])
        if np.isfinite(a):
            out.append(a)
    return float(np.percentile(out, 5)), float(np.percentile(out, 95))


def net(g: np.ndarray, tv: np.ndarray, c: float) -> np.ndarray:
    return g - c * np.r_[0.0, tv[:-1]]


def year_of(days: np.ndarray) -> np.ndarray:
    return days.astype("datetime64[us]").astype("datetime64[Y]").astype(int) + 1970


def describe(P, name: str, g: np.ndarray, tv: np.ndarray, ex: np.ndarray) -> dict:
    oos = P.days >= fc.SPLIT
    sel = (P.days >= AUC_FROM) & (P.days < fc.SPLIT)
    yr = year_of(P.days)
    row: dict = {"variant": name}
    for k, c in COSTS.items():
        po = fc.perf(net(g, tv, c)[oos])
        row[f"oos_{k}"] = po["sharpe"]
        row[f"cagr_{k}"] = po["cagr"]
        row[f"dd_{k}"] = po["max_dd"]
    x = net(g, tv, COSTS[BASE])
    row["2022_23"] = fc.perf(x[sel])["sharpe"]
    for y in YEARS:
        row[f"y{y}"] = fc.perf(x[yr == y])["sharpe"]
    row["turnover_yr"] = float(tv[oos].sum() / (oos.sum() / 365))
    row["expo"] = float(ex[oos].mean())
    return row


def sharpe_ann(x: np.ndarray) -> float:
    return rh.sharpe_d(x) * math.sqrt(365)


def paired_boot(a: np.ndarray, b: np.ndarray, rng: np.random.Generator, draws: int = BOOT_DRAWS,
                block: int = tt.BOOT_BLOCK) -> dict:
    """Stationary bootstrap of the days, the same draw for both series: Sharpe(a) - Sharpe(b)."""
    n = len(a)
    idx = np.empty((draws, n), dtype=np.int64)
    idx[:, 0] = rng.integers(0, n, draws)
    jump = rng.random((draws, n)) < 1 / block
    fresh = rng.integers(0, n, (draws, n))
    for i in range(1, n):
        idx[:, i] = np.where(jump[:, i], fresh[:, i], (idx[:, i - 1] + 1) % n)

    def sr(x):
        s = x[idx]
        sd = s.std(1)
        return np.where(sd > 0, s.mean(1) / np.where(sd > 0, sd, 1), 0.0) * math.sqrt(365)
    d = sr(a) - sr(b)
    return {"share_above_0": float((d > 0).mean()), "p05": float(np.percentile(d, 5)),
            "p95": float(np.percentile(d, 95))}


def reliability(p: np.ndarray, y: np.ndarray, bins: int = 10) -> list[dict]:
    q = np.quantile(p, np.linspace(0, 1, bins + 1))
    b = np.clip(np.searchsorted(q, p, side="right") - 1, 0, bins - 1)
    return [{"decile": i + 1, "mean_p": float(p[b == i].mean()), "hit_rate": float(y[b == i].mean()),
             "events": int((b == i).sum())} for i in range(bins) if (b == i).any()]


# ---------------------------------------------------------------------------
# The study
# ---------------------------------------------------------------------------

def alpaca_mask(P) -> np.ndarray:
    return np.array([b in tt.ALPACA and "~" not in n for b, n in zip(P.bases, P.names)])


def alpaca_allowed(P, n: int = TOP_BOOK) -> np.ndarray:
    ok = P.eligible & alpaca_mask(P)[None, :]
    score = np.where(ok, P.adv28, -np.inf)
    rank = np.argsort(np.argsort(-score, axis=1), axis=1)
    return ok & (rank < n)


def main() -> None:
    t0 = time.time()
    P = fc.load_panel()
    print(f"panel {P.T} days x {P.N} segments, to "
          f"{np.datetime64(int(P.days[-1]), 'us').astype('datetime64[D]')}", flush=True)
    top10, top30 = P.top_liquid(TOP_BOOK), P.top_liquid(TOP_EVENTS)
    cols = np.flatnonzero(top10.any(0))
    alp = alpaca_allowed(P)
    acols = np.flatnonzero(alp.any(0))

    # The unfiltered book must be the sweep's own.
    W0, ent0 = book_weights(P, cols, top10)
    Wref = fam_breakout.breakout_weights(P, cols, top10, ENTRY_N, SLOTS, regime=False)
    assert np.array_equal(np.isnan(W0), np.isnan(Wref)) and np.allclose(np.nan_to_num(W0), np.nan_to_num(Wref))
    g0, tv0, ex0 = run_book(P, cols, W0)
    gref = fc.simulate(P, Wref, start=START)[0]
    assert np.allclose(g0, gref), "the restricted simulator does not reproduce the sweep's"

    sig = signals(P)
    ex, tr_ret = exits(P)
    label = np.where(ex >= 0, (tr_ret - ROUND_TRIP > 0).astype(float), np.nan)
    ev = training_events(sig, top30, ex)
    pred = sig & (top30 | alp)
    print(f"signal cells {int(sig.sum()):,}, events {int(ev.sum()):,}, to predict {int(pred.sum()):,}", flush=True)

    m2 = m2_matrix(P, refit="--refit-m2" in sys.argv)
    print(f"M2 scores on {int(np.isfinite(m2).sum()):,} cells", flush=True)
    f = features(P, m2, sig)
    meta = walk_forward(P, f, ev, pred, ex, label)

    # ---- classifier quality on out-of-sample events from 2022
    rng = np.random.default_rng(20261014)
    month = P.days.astype("datetime64[us]").astype("datetime64[M]").astype(int)
    quality = {}
    for key, cells in (("events", ev), ("book entries", ent0)):
        m = cells & np.isfinite(meta.p) & np.isfinite(label) & (P.days >= AUC_FROM)[:, None]
        ti, tj = np.nonzero(m)
        pc, pr, y = meta.p[ti, tj], meta.raw[ti, tj], label[ti, tj]
        lo, hi = auc_band(pr, y, month[ti], rng)
        quality[key] = {"n": int(len(y)), "hit_rate": float(y.mean()), "auc_raw": auc(pr, y),
                        "auc_cal": auc(pc, y), "auc_p05": lo, "auc_p95": hi,
                        "brier": float(np.mean((pc - y) ** 2)),
                        "brier_base": float(np.mean((meta.pbar[ti, tj] - y) ** 2)),
                        "reliability": reliability(pc, y)}
        if key == "book entries":
            quality[key]["mean_ret_by_p_half"] = {
                "low": float(np.mean(tr_ret[ti, tj][pc < np.median(pc)])),
                "high": float(np.mean(tr_ret[ti, tj][pc >= np.median(pc)]))}
    print("quality", {k: (v["auc_raw"], v["auc_p05"]) for k, v in quality.items()}, flush=True)

    # ---- the books
    rows, nets, mults, entries = [], {}, {}, {}
    rows.append(describe(P, "unfiltered", g0, tv0, ex0))
    nets["unfiltered"] = (g0, tv0)
    Wa0, _ = book_weights(P, acols, alp)
    ga0, tva0, exa0 = run_book(P, acols, Wa0)
    rows.append(describe(P, "unfiltered · Alpaca coins", ga0, tva0, exa0))
    nets["unfiltered · Alpaca coins"] = (ga0, tva0)
    for use in USES:
        M = multipliers(meta, use)
        mults[use] = M
        W, ent = book_weights(P, cols, top10, M)
        entries[use] = ent
        g, tv, ex_ = run_book(P, cols, W)
        rows.append(describe(P, use, g, tv, ex_))
        nets[use] = (g, tv)
        Wa, _ = book_weights(P, acols, alp, M)
        g, tv, ex_ = run_book(P, acols, Wa)
        rows.append(describe(P, f"{use} · Alpaca coins", g, tv, ex_))
        nets[f"{use} · Alpaca coins"] = (g, tv)
        g, tv, ex_ = run_book(P, cols, late(W))
        rows.append(describe(P, f"{use} · a day late", g, tv, ex_))
        nets[f"{use} · a day late"] = (g, tv)
    g, tv, ex_ = run_book(P, cols, late(W0))
    rows.append(describe(P, "unfiltered · a day late (reference)", g, tv, ex_))
    nets["unfiltered · a day late (reference)"] = (g, tv)
    diag = []
    for use in DIAGNOSTIC:
        M = multipliers(meta, use)
        W, ent = book_weights(P, cols, top10, M)
        g, tv, ex_ = run_book(P, cols, W)
        cand = candidates(P, cols, top10, M) & (P.days >= FIRST_TEST)[:, None]
        diag.append({**describe(P, f"{use} (diagnostic)", g, tv, ex_),
                     "skip_rate": float(1 - (ent & cand).sum() / max(cand.sum(), 1))})
    print("books done", flush=True)

    # ---- entry statistics: how much each use skips, and its random null
    oos = P.days >= fc.SPLIT
    active = (P.days >= FIRST_TEST)[:, None]
    c = COSTS[BASE]
    nulls, skip = {}, {}
    for use in USES:
        M = mults[use]
        cand = candidates(P, cols, top10, M) & active
        ent = entries[use] & active
        skip[use] = {"candidates": int(cand.sum()), "entered": int(ent.sum()),
                     "skip_rate": float(1 - ent.sum() / max(cand.sum(), 1)),
                     "mean_mult_entered": float(M[ent].mean()) if ent.any() else float("nan")}
        sr = []
        nrng = np.random.default_rng(7 + USES.index(use))
        haspred = np.isfinite(meta.p)
        ent_cells = np.nonzero(ent)
        for _ in range(NULL_DRAWS):
            if use == "Z":
                # The same entries, their sizes shuffled among them.
                R = M.copy()
                R[ent_cells] = nrng.permutation(M[ent_cells])
            else:
                keep = nrng.random(M.shape) >= skip[use]["skip_rate"]
                R = np.where(haspred, keep.astype(float), 1.0)
            W, _ = book_weights(P, cols, top10, R)
            g, tv, _ = run_book(P, cols, W)
            sr.append(sharpe_ann(net(g, tv, c)[oos]))
        sr = np.array(sr)
        mine = sharpe_ann(net(*nets[use], c)[oos])
        nulls[use] = {"null_median": float(np.median(sr)), "null_p95": float(np.percentile(sr, 95)),
                      "share_beaten": float((mine > sr).mean())}
        print(f"null {use}: {nulls[use]}", flush=True)

    # ---- deflation over the pool (the 265 before this study plus the 10 counted here)
    trials = [n for n in nets if n not in REFERENCE]
    assert len(trials) == HERE_TRIALS, trials
    var, pool = rh.pooled_var([sharpe_ann(net(*nets[n], c)[oos]) for n in trials])
    n_total = pool["n_total"]
    for r in rows:
        r["deflated_p"] = rh.deflated(net(*nets[r["variant"]], c)[oos], n_total, var)
        r["boot_p05"], r["boot_p95"] = tt.boot_band(net(*nets[r["variant"]], c)[oos], rng)

    # ---- the registered gates
    def row(name: str) -> dict:
        return next(r for r in rows if r["variant"] == name)
    yr = year_of(P.days)
    base_x = net(g0, tv0, c)[oos]
    q = quality["events"]
    judged = []
    for use in USES:
        r, rb = row(use), row("unfiltered")
        x = net(*nets[use], c)[oos]
        pb = paired_boot(x, base_x, rng)
        years_ok = sum(r[f"y{y}"] >= rb[f"y{y}"] for y in YEARS_OOS)
        gate = {
            "1 AUC > 0.55, band low > 0.50": q["auc_raw"] > 0.55 and q["auc_p05"] > 0.50,
            "2 Sharpe above unfiltered, paired bootstrap >= 90 %": r[f"oos_{BASE}"] > rb[f"oos_{BASE}"]
            and pb["share_above_0"] >= 0.90,
            "3 beats 95 % of its null": nulls[use]["share_beaten"] >= 0.95,
            "4 at least as good in 2 of 3 years": years_ok >= 2,
            "5 Alpaca twin not worse": row(f"{use} · Alpaca coins")[f"oos_{BASE}"]
            >= row("unfiltered · Alpaca coins")[f"oos_{BASE}"],
        }
        judged.append({"use": use, "sharpe": r[f"oos_{BASE}"], "sharpe_unfiltered": rb[f"oos_{BASE}"],
                       "dd": r[f"dd_{BASE}"], "dd_unfiltered": rb[f"dd_{BASE}"],
                       "boot_share": pb["share_above_0"], "diff_p05": pb["p05"], "diff_p95": pb["p95"],
                       "years_ok": years_ok, "null_share": nulls[use]["share_beaten"],
                       "alpaca": row(f"{use} · Alpaca coins")[f"oos_{BASE}"],
                       "alpaca_unfiltered": row("unfiltered · Alpaca coins")[f"oos_{BASE}"],
                       "deflated_p": r["deflated_p"], "gate": gate, "gate_a": all(gate.values()),
                       "gate_b": r["deflated_p"] > 0.95})
    passing = [j for j in judged if j["gate_a"]]
    pick = max(passing, key=lambda j: j["sharpe"])["use"] if passing else None

    res = {"panel_end": str(np.datetime64(int(P.days[-1]), "us").astype("datetime64[D]")), "segments": P.N,
           "n_signal": int(sig.sum()), "n_events": int(ev.sum()), "n_events_labelled": int((ev & (ex >= 0)).sum()),
           "n_pred": int(pred.sum()), "event_hit_rate": float(np.nanmean(label[ev])),
           "m2_cells": int(np.isfinite(m2).sum()), "folds": meta.folds, "importance": meta.importance,
           "quality": quality, "rows": rows, "skip": skip, "nulls": nulls, "judged": judged, "pick": pick,
           "pool": pool, "trials": trials, "diagnostic": diag, "minutes": (time.time() - t0) / 60}
    write(res)
    print(f"done in {res['minutes']:.0f} min; pick {pick}", flush=True)


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def write(res: dict) -> None:
    pre = (fc.RESULTS_DIR / f"{NAME}.md").read_text(encoding="utf-8")
    pre = pre.split(MARKER)[0] + MARKER + "\n"
    q, qb, pool = res["quality"]["events"], res["quality"]["book entries"], res["pool"]
    md = [pre, f"\n## Results (generated {datetime.now(timezone.utc):%Y-%m-%d}, data to {res['panel_end']}, "
               f"{res['segments']} coin segments)\n\n"]
    if res["pick"]:
        verdict = (f"**Verdict: gate A holds for {res['pick']}.** It becomes an autopilot-only paper variant "
                   f"with its deflation result in the evidence.")
    else:
        jz = {j["use"]: j for j in res["judged"]}
        verdict = ("**Verdict: negative. No use of the classifier passes gate A; no paper book.** "
                   f"Out of sample the classifier ranks the trades worse than chance (AUC {q['auc_raw']:.2f} on "
                   f"the events from 2022, band {q['auc_p05']:.2f} to {q['auc_p95']:.2f}; {qb['auc_raw']:.2f} on "
                   f"the book's own entries). From 2024 at 35 bps the unfiltered book makes Sharpe "
                   f"{jz['Z']['sharpe_unfiltered']:.2f}; S1 {jz['S1']['sharpe']:.2f}, S2 {jz['S2']['sharpe']:.2f}, "
                   f"Z {jz['Z']['sharpe']:.2f}. Every gate fails for every use, and deflated p is "
                   f"{max(j['deflated_p'] for j in res['judged']):.2f} at best over {pool['n_total']} trials.")
    md.append(verdict + "\n\n")
    md.append(f"Events: {res['n_signal']:,} breakout cells on the panel, {res['n_events']:,} training events on "
              f"the top 30 ({res['n_events_labelled']:,} with a known exit; {res['event_hit_rate'] * 100:.0f} % "
              f"clear the 70 bps round trip), {res['n_pred']:,} cells predicted (top 30 plus the Alpaca top 10). "
              f"M2 scores on {res['m2_cells']:,} coin-days.\n\n")
    md.append("### The classifier (out-of-sample events from 2022)\n\n")
    qrows = [{"set": k, **{c: v[c] for c in ("n", "hit_rate", "auc_raw", "auc_cal", "auc_p05", "auc_p95",
                                             "brier", "brier_base")}}
             for k, v in res["quality"].items()]
    md.append(fc.table(qrows, ["set", "n", "hit_rate", "auc_raw", "auc_cal", "auc_p05", "auc_p95", "brier",
                               "brier_base"]))
    md.append("\n`auc_p05`/`auc_p95`: 90 % band from a bootstrap of whole months of events. `brier_base`: "
              "predicting each fold's training base rate. Book entries: mean trade return "
              f"{qb['mean_ret_by_p_half']['low'] * 100:.1f} % below the median probability, "
              f"{qb['mean_ret_by_p_half']['high'] * 100:.1f} % above it.\n\n")
    md.append("Reliability on the events (calibrated probability deciles):\n\n")
    md.append(fc.table(q["reliability"], ["decile", "mean_p", "hit_rate", "events"]))
    md.append("\nPer fold (AUC on that quarter's events, raw scores):\n\n")
    md.append(fc.table(res["folds"], ["fold", "train_events", "base_rate", "cal_events", "calibrated",
                                      "test_events", "auc", "s2_cut"]))
    md.append("\nFeature importance (share of total gain, all folds):\n\n")
    md.append(fc.table([{"feature": k, "gain_share": v} for k, v in
                        sorted(res["importance"].items(), key=lambda x: -x[1])], ["feature", "gain_share"]))
    md.append("\n### The registered gates (out of sample from 2024, 35 bps)\n\n")
    jrows = [{**{k: v for k, v in j.items() if k != "gate"},
              **{k.split(" ")[0]: v for k, v in j["gate"].items()}} for j in res["judged"]]
    md.append(fc.table(jrows, ["use", "sharpe_unfiltered", "sharpe", "dd_unfiltered", "dd", "boot_share",
                               "diff_p05", "diff_p95", "years_ok", "null_share", "alpaca_unfiltered", "alpaca",
                               "1", "2", "3", "4", "5", "gate_a", "deflated_p", "gate_b"]))
    md.append("\nGate A: 1 AUC on events > 0.55 and band low > 0.50; 2 Sharpe above the unfiltered book and the "
              "paired stationary bootstrap (block 20) above 0 in 90 % of draws; 3 beats 95 % of its random null; "
              "4 at least as good as the unfiltered book in 2 of 2024, 2025, 2026; 5 the Alpaca twin not worse "
              "than the unfiltered book on the Alpaca coins. Gate B: deflated p > 0.95 over "
              f"{pool['n_total']} trials.\n\n")
    md.append("Entries and nulls (from 2021-07, the filter's first quarter):\n\n")
    md.append(fc.table([{"use": u, **res["skip"][u], **res["nulls"][u]} for u in res["skip"]],
                       ["use", "candidates", "entered", "skip_rate", "mean_mult_entered", "null_median",
                        "null_p95", "share_beaten"]))
    md.append("\nS1 and S2: the same skip rate drawn at random over the predicted cells, "
              f"{NULL_DRAWS} times; Z: its multipliers shuffled among its own entries.\n\n")
    md.append("### Every book (out of sample from 2024)\n\n")
    cols = ["variant", "oos_maker 15bps", f"oos_{BASE}", "oos_41bps", f"cagr_{BASE}", f"dd_{BASE}",
            "turnover_yr", "expo", "boot_p05", "boot_p95", "deflated_p"]
    md.append(fc.table(res["rows"], cols))
    md.append("\n`boot_*`: 90 % stationary-bootstrap band of the Sharpe at 35 bps. Per year, Sharpe at 35 bps "
              "(2022 and 2023 are walk-forward for the classifier but the book was picked on them):\n\n")
    md.append(fc.table(res["rows"], ["variant", "2022_23"] + [f"y{y}" for y in YEARS]))
    md.append("\n### Unregistered diagnostic (not counted, not gated)\n\n"
              "S1 and S2 skip far more than half and a quarter of the entries: isotonic calibration of a "
              "score with no out-of-sample skill flattens the calibrated probability near the recent hit rate, "
              "which is below the training base rate (that includes 2020-21), and many cells tie at the S2 "
              "cut. To check that the negative result is not only that mechanism, the same book skips the "
              "cells whose raw score falls in the bottom half or bottom quarter of the calibration set's raw "
              "scores (no ties):\n\n")
    md.append(fc.table(res["diagnostic"], ["variant", "skip_rate", f"oos_{BASE}", f"dd_{BASE}", "2022_23"]
                       + [f"y{y}" for y in YEARS_OOS]))
    md.append(f"\n### Deflation\n\nPrior: {pool['prior_trials']} trials, variance backed out of the fast "
              f"strategies' bar (2.74 over 265); here {pool['mine']} trials at 35 bps. Pooled bar "
              f"{pool['sr0_annual']:.2f} over {pool['n_total']}. Trials counted here: "
              + "; ".join(res["trials"]) + f".\n\nTook {res['minutes']:.0f} min.\n")
    (fc.RESULTS_DIR / f"{NAME}.md").write_text("".join(md), encoding="utf-8")
    d = fc.OUT / "reports"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{NAME}.json").write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")


if __name__ == "__main__":
    main()
