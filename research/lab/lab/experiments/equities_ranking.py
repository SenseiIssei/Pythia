"""M9: cross-sectional ranking of S&P 500 stocks, for the Alpaca paper account.

    python -m lab.experiments.equities_ranking            (cached data and models)
    python -m lab.experiments.equities_ranking --refresh  (downloads the data again)
    python -m lab.experiments.equities_ranking --refit    (refits every model)

Why: the ETF trend study lost to 60/40 (results/etf_trend.md). The Alpaca
paper account trades US stocks at zero commission, so the next question is
whether a ranking model can choose stocks better than owning the index.

Data. Yahoo's chart API and Stooq are not reachable from every machine the lab
runs on, so the study reads a public, rebuilt-every-weekday dataset from
GitHub (github.com/Johnbrick123/sp500-data, release "data"):
  prices.parquet                daily OHLCV, split-adjusted close and split plus
                                dividend adjusted close, 1,338 tickers incl.
                                names that left the index or died (CRSP and
                                Tiingo history patched in where Yahoo purged it)
  membership_intervals.parquet  point-in-time S&P 500 membership, [start, end)
                                per ticker; reused tickers carry a suffix
                                (AAL-199702), so a recycled symbol is never
                                joined to the wrong company
Cached as <data>/equities/*.parquet. Survivorship: the universe on each day is
the index as it stood that day, and the names that later failed (Lehman,
WorldCom, SVB) are in it with their final prices. Volume is missing for about
30 % of member rows before 2006 (CRSP rows), none from 2017.

Pre-registered before any number on real data was seen. Every variant below is
counted in the deflation, the robustness checks included.

  Universe     S&P 500 members on the decision day with 252 days of history.
  Decisions    the last trading day of each week, filled at the NEXT day's
               close (the engine trades in the regular session after the signal
               is written), held a week, weights drifting. Long-only, equal
               weight 1/K, no leverage. A held name that dies earns its last
               price and sits in cash until the next rebalance.
  Features     at the decision close, closes up to that day only:
               momentum 1/3/6/12 months and 12-1, 1-week reversal, volatility
               21 and 63 days, beta to SPY 252 days, distance to the 52-week
               high, and (the "full" set only) a size proxy (log 63-day dollar
               volume) and volume trend (21 vs 126-day dollar volume); seven
               "sector-relative" versions (momentum 1/3/6/12-1, reversal, vol 63,
               52-week distance, minus the median of the name's cluster). There
               are no sector labels for dead names in free data, so sectors are
               statistical: k-means (10 clusters) on the members' standardised
               market-residual daily returns over the past 252 days, refitted
               on the first decision day of each month. Every feature is ranked
               across the day's universe to [0, 1].
  Labels       forward return from the fill close (t+1) over h = 5, 10, 20
               trading days, the delisting price included; relevance = the
               day's quintile (0 to 4).
  Model M9     LightGBM LambdaRank, fixed parameters (PARAMS), one model per
               horizon and feature set, refitted each January on every decision
               day (every second week) whose label ends at least 5 trading days
               before the year starts (purged, embargoed, expanding from 1997).
               (Set before any result: 400 trees on every week took 7 minutes
               a fit, 12 hours for the study; 200 trees at twice the rate.) The "full" set
               trains only on rows with volume (CRSP rows have none, and a
               missing value would tell the model "this name will be delisted").
  Books        top K = 20 / 50, with or without a rank buffer (a held name stays
               while it ranks in the top 2K).
                 M9: 3 horizons x 2 feature sets x 2 K x 2 buffers           24
  Baselines    12-1 momentum, low volatility (vol 63), 1-month reversal
               (losers), 52-week high (closest), top K 20 / 50, buffer or not 16
  Robustness   the M9 pick decided on each other weekday (4) and filled a day
               late (1)                                                        5
                                                                       total 45
  Windows      selection 2010 to 2015 (walk-forward predictions, never
               in-sample), out of sample from 2016-01-01 to the data's end.
               Costs 5 bps per side (per unit of turnover), 10 bps doubled.
  Pick         the M9 variant with the best selection-window information ratio
               against the equal-weight index (net of 5 bps); the baselines'
               pick likewise, judged by the same bar. Quality: there are no
               fundamentals in the data, so no quality proxy is tested.
  Benchmarks   SPY buy and hold; equal weight of the same point-in-time
               universe, rebalanced weekly at the same costs.

The lab's bar, all must hold out of sample at 5 bps:
  1. deflated p > 0.95 of the active return (book minus equal weight) over all
     45 trials (a long-only stock book always beats zero; beating the index is
     the claim)
  2. information ratio at least half the selection window's (which is > 0)
  3. information ratio > 0 at 10 bps
  4. Sharpe above SPY's and above equal weight's
  5. block bootstrap (20 days): Sharpe above equal weight's in >= 90 % of draws
  6. active return positive in more than half of the calendar years
"""

from __future__ import annotations

import json
import math
import os
import sys
import urllib.request
import warnings
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from scipy import stats

from ..data import ROOT
from ..metrics import deflated_sharpe
from . import etf_trend as et

NAME = "equities_ranking"
SOURCE = "https://github.com/Johnbrick123/sp500-data/releases/download/data/{}"
FILES = ("prices.parquet", "membership_intervals.parquet")
CACHE = Path(os.environ.get("PYTHIA_EQ_DATA", ROOT / "equities"))
MODEL_CACHE = Path(os.environ.get("PYTHIA_REPORTS", ROOT / "reports")) / "_cache" / NAME
START = np.datetime64("1996-01-01")
TRAIN_FROM = np.datetime64("1997-01-01")
SELECT_FROM, OOS_FROM = np.datetime64("2010-01-01"), np.datetime64("2016-01-01")
COSTS = {"5bps": 0.0005, "10bps": 0.0010}
YEAR_DAYS = 252
HISTORY = 252
EMBARGO = 5
HORIZONS = (5, 10, 20)
KS = (20, 50)
N_CLUSTERS = 10
BOOT_DRAWS = 5_000
SR_CLIP = 3.0
PARAMS = dict(objective="lambdarank", n_estimators=200, learning_rate=0.1, num_leaves=31, max_bin=63,
              min_child_samples=500, subsample=0.7, subsample_freq=1, colsample_bytree=0.8,
              reg_lambda=1.0, random_state=0, n_jobs=4, verbose=-1)
TRAIN_EVERY = 2             # train on every second decision day (half the overlap, half the time)

BASE_FEATURES = ("mom_21", "mom_63", "mom_126", "mom_252", "mom_12_1", "rev_5", "vol_21", "vol_63",
                 "beta_252", "dist_52wh")
VOLUME_FEATURES = ("size_dv63", "vol_trend")
REL_FEATURES = ("mom_21", "mom_63", "mom_126", "mom_12_1", "rev_5", "vol_63", "dist_52wh")
FEATURE_SETS = {
    "price": BASE_FEATURES + tuple(f"{f}_rel" for f in REL_FEATURES),
    "full": BASE_FEATURES + VOLUME_FEATURES + tuple(f"{f}_rel" for f in REL_FEATURES),
}
# Baselines: (feature, sign); the book holds the K names with the highest sign * feature.
BASELINES = {"momentum 12-1": ("mom_12_1", 1), "low volatility": ("vol_63", -1),
             "reversal 1m": ("mom_21", -1), "52-week high": ("dist_52wh", 1)}
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday")


class DataUnavailable(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

@dataclass
class Panel:
    dates: np.ndarray       # datetime64[D], trading days
    names: list[str]
    close: np.ndarray       # (T, N) split and dividend adjusted, carried forward after a series ends
    dv: np.ndarray          # (T, N) dollar volume (split-adjusted close x volume), NaN where unknown
    member: np.ndarray      # (T, N) bool, in the S&P 500 that day
    alive: np.ndarray       # (T, N) bool, between a series' first and last row
    spy: np.ndarray         # (T,) SPY adjusted close

    @property
    def T(self) -> int:
        return len(self.dates)

    @property
    def N(self) -> int:
        return len(self.names)

    def ret(self) -> np.ndarray:
        r = np.full(self.close.shape, np.nan)
        r[1:] = self.close[1:] / self.close[:-1] - 1
        return r


def fetch(fname: str, timeout: float = 300.0) -> bytes:
    req = urllib.request.Request(SOURCE.format(fname), headers={"User-Agent": "pythia-lab"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except OSError as e:
        raise DataUnavailable(f"{fname}: {e}") from e


def load_files(refresh: bool = False, get=fetch) -> dict[str, Path]:
    out = {}
    for fname in FILES:
        f = CACHE / fname
        if refresh or not f.exists():
            blob = get(fname)
            if blob[:4] != b"PAR1":                     # never cache an error page
                raise DataUnavailable(f"{fname}: not a parquet file")
            f.parent.mkdir(parents=True, exist_ok=True)
            tmp = f.with_suffix(".part")
            tmp.write_bytes(blob)
            tmp.replace(f)
        out[fname] = f
    return out


def build_panel(prices, members, start=START) -> Panel:
    """prices: polars frame (date, ticker, close, volume, adj_close); members:
    (ticker, start, end). One calendar of the days SPY or any member traded."""
    import polars as pl
    px = (prices.with_columns(pl.col("date").cast(pl.Date))
          .filter(pl.col("date") >= start.astype(object))
          .select("date", "ticker", "close", "volume", "adj_close")
          .filter(pl.col("adj_close") > 0)
          .unique(["ticker", "date"], keep="last"))
    mem = members.with_columns(pl.col("start").cast(pl.Date), pl.col("end").cast(pl.Date))
    keep = set(mem["ticker"].to_list()) & set(px["ticker"].unique().to_list())
    if "SPY" not in set(px["ticker"].unique().to_list()):
        raise DataUnavailable("no SPY in the price file")
    names = sorted(keep)
    dates = np.array(sorted(px["date"].unique().to_list()), dtype="datetime64[D]")
    col = {s: j for j, s in enumerate(names)}
    T, N = len(dates), len(names)
    close = np.full((T, N), np.nan)
    dv = np.full((T, N), np.nan)
    spy = np.full(T, np.nan)
    sub = px.filter(pl.col("ticker").is_in(names + ["SPY"]))
    d_idx = np.searchsorted(dates, sub["date"].to_numpy().astype("datetime64[D]"))
    tick = sub["ticker"].to_list()
    adj = sub["adj_close"].to_numpy()
    raw = (sub["close"] * sub["volume"]).to_numpy().astype(float)
    j = np.array([col.get(s, -1) for s in tick])
    is_spy = np.array([s == "SPY" for s in tick])
    m = j >= 0
    close[d_idx[m], j[m]] = adj[m]
    dv[d_idx[m], j[m]] = raw[m]
    spy[d_idx[is_spy]] = adj[is_spy]
    fin = np.isfinite(close)
    first = np.where(fin.any(0), fin.argmax(0), T)
    last = np.where(fin.any(0), T - 1 - fin[::-1].argmax(0), -1)
    t_ix = np.arange(T)[:, None]
    alive = (t_ix >= first[None, :]) & (t_ix <= last[None, :])
    close = _ffill(close)
    spy = _ffill(spy[:, None])[:, 0]
    member = np.zeros((T, N), dtype=bool)
    for s, a, b in mem.select("ticker", "start", "end").iter_rows():
        if s not in col:
            continue
        lo = np.searchsorted(dates, np.datetime64(a, "D"))
        hi = T if b is None else np.searchsorted(dates, np.datetime64(b, "D"))
        member[lo:hi, col[s]] = True
    member &= alive
    return Panel(dates=dates, names=names, close=close, dv=dv, member=member, alive=alive, spy=spy)


def load_panel(refresh: bool = False, get=fetch) -> Panel:
    import polars as pl
    files = load_files(refresh, get)
    return build_panel(pl.read_parquet(files["prices.parquet"]), pl.read_parquet(files["membership_intervals.parquet"]))


def _ffill(x: np.ndarray) -> np.ndarray:
    """Carry the last finite value forward down each column (NaN before the first)."""
    idx = np.where(np.isfinite(x), np.arange(x.shape[0])[:, None], -1)
    np.maximum.accumulate(idx, axis=0, out=idx)
    out = x[np.maximum(idx, 0), np.arange(x.shape[1])[None, :]]
    out[idx < 0] = np.nan
    return out


# ---------------------------------------------------------------------------
# Features: row t uses data up to the close of t only
# ---------------------------------------------------------------------------

def _roll_mean(x: np.ndarray, w: int, min_count: int) -> np.ndarray:
    fin = np.isfinite(x)
    c = np.cumsum(np.where(fin, x, 0.0), axis=0)
    n = np.cumsum(fin, axis=0)
    c = np.vstack([np.zeros((1,) + x.shape[1:]), c])
    n = np.vstack([np.zeros((1,) + x.shape[1:]), n])
    s = c[w:] - c[:-w]
    k = n[w:] - n[:-w]
    out = np.full(x.shape, np.nan)
    with np.errstate(invalid="ignore", divide="ignore"):
        out[w - 1:] = np.where(k >= min_count, s / np.maximum(k, 1), np.nan)
    return out


def _roll_max(x: np.ndarray, w: int) -> np.ndarray:
    from numpy.lib.stride_tricks import sliding_window_view
    out = np.full(x.shape, np.nan)
    v = sliding_window_view(np.where(np.isfinite(x), x, -np.inf), w, axis=0)
    m = v.max(axis=-1)
    out[w - 1:] = np.where(np.isfinite(m), m, np.nan)
    return out


def _lag_ratio(c: np.ndarray, a: int, b: int) -> np.ndarray:
    """c[t - a] / c[t - b] - 1 (a < b)."""
    out = np.full(c.shape, np.nan)
    out[b:] = c[b - a:c.shape[0] - a] / c[:c.shape[0] - b] - 1
    return out


def raw_features(P: Panel) -> dict[str, np.ndarray]:
    c = np.where(P.alive, P.close, np.nan)
    r = np.full(c.shape, np.nan)
    r[1:] = c[1:] / c[:-1] - 1
    m = np.full(P.T, np.nan)
    m[1:] = P.spy[1:] / P.spy[:-1] - 1
    f = {
        "mom_21": _lag_ratio(c, 0, 21), "mom_63": _lag_ratio(c, 0, 63), "mom_126": _lag_ratio(c, 0, 126),
        "mom_252": _lag_ratio(c, 0, 252), "mom_12_1": _lag_ratio(c, 21, 252), "rev_5": _lag_ratio(c, 0, 5),
    }
    for w in (21, 63):
        mu = _roll_mean(r, w, int(0.8 * w))
        f[f"vol_{w}"] = np.sqrt(np.maximum(_roll_mean(r * r, w, int(0.8 * w)) - mu * mu, 0) * YEAR_DAYS)
    mm = np.broadcast_to(m[:, None], r.shape)
    rm = np.where(np.isfinite(r), mm, np.nan)
    cov = _roll_mean(r * mm, 252, 200) - _roll_mean(r, 252, 200) * _roll_mean(rm, 252, 200)
    var = _roll_mean(rm * rm, 252, 200) - _roll_mean(rm, 252, 200) ** 2
    with np.errstate(invalid="ignore", divide="ignore"):
        f["beta_252"] = cov / var
    f["dist_52wh"] = c / _roll_max(c, 252) - 1
    dv = np.where(P.alive & (P.dv > 0), P.dv, np.nan)
    d63 = _roll_mean(dv, 63, 50)
    with np.errstate(invalid="ignore", divide="ignore"):
        f["size_dv63"] = np.log(d63)
        f["vol_trend"] = np.log(_roll_mean(dv, 21, 17) / _roll_mean(dv, 126, 100))
    return f


def eligible(P: Panel, f: dict[str, np.ndarray]) -> np.ndarray:
    return P.member & np.isfinite(f["mom_252"]) & np.isfinite(f["vol_63"]) & np.isfinite(f["dist_52wh"])


def month_starts(dates: np.ndarray, days: np.ndarray) -> np.ndarray:
    mon = dates.astype("datetime64[M]")
    out = np.zeros(len(dates), dtype=bool)
    seen = set()
    for t in np.flatnonzero(days):
        if mon[t] not in seen:
            out[t] = True
            seen.add(mon[t])
    return out


def clusters(P: Panel, elig: np.ndarray, days: np.ndarray, k: int = N_CLUSTERS) -> np.ndarray:
    """(T, N) cluster id on decision days (-1 = none), refitted on the first
    decision day of each month from the past 252 days of standardised
    market-residual returns; between refits a name keeps its label, a name
    without one gets -1 (it is compared with the whole market)."""
    from sklearn.cluster import KMeans
    r = np.where(P.alive, P.ret(), np.nan)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        ew = np.nanmean(np.where(P.member, r, np.nan), axis=1)
    resid = r - ew[:, None]
    lab = np.full(P.N, -1)
    out = np.full((P.T, P.N), -1, dtype=np.int16)
    refit = month_starts(P.dates, days)
    for t in np.flatnonzero(days):
        if refit[t] and t >= HISTORY:
            win = resid[t - HISTORY + 1:t + 1]
            ok = elig[t] & (np.isfinite(win).sum(0) >= 200)
            lab = np.full(P.N, -1)
            if ok.sum() >= 5 * k:
                x = np.nan_to_num(win[:, ok]).T
                x = (x - x.mean(1, keepdims=True)) / np.maximum(x.std(1, keepdims=True), 1e-12)
                lab[ok] = KMeans(k, n_init=3, random_state=0).fit_predict(x)
        out[t] = np.where(elig[t], lab, -1)
    return out


def cs_rank(x: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Per row, the rank of x among the masked finite cells, scaled to [0, 1]."""
    ok = mask & np.isfinite(x)
    big = np.where(ok, x, np.inf)
    order = np.argsort(big, axis=1, kind="stable")
    rk = np.empty_like(order)
    np.put_along_axis(rk, order, np.arange(x.shape[1])[None, :].repeat(x.shape[0], 0), axis=1)
    n = ok.sum(1, keepdims=True)
    with np.errstate(invalid="ignore", divide="ignore"):
        out = np.where(ok, rk / np.maximum(n - 1, 1), np.nan)
    return out


def features(P: Panel, days: np.ndarray) -> tuple[dict[str, np.ndarray], np.ndarray, np.ndarray]:
    """Ranked features on the decision days (NaN elsewhere), the eligibility
    mask and the cluster labels. Relative features: the raw feature minus the
    median of the name's cluster that day (minus the market median for -1)."""
    f = raw_features(P)
    elig = eligible(P, f)
    elig &= days[:, None]
    cl = clusters(P, elig, days)
    for name in REL_FEATURES:
        x = f[name]
        rel = np.full(x.shape, np.nan)
        for t in np.flatnonzero(days):
            row, e = x[t], elig[t] & np.isfinite(x[t])
            if not e.any():
                continue
            med = np.full(P.N, np.nanmedian(row[e]))
            for g in np.unique(cl[t][e]):
                if g >= 0:
                    sel = e & (cl[t] == g)
                    med[sel] = np.median(row[sel])
            rel[t] = np.where(e, row - med, np.nan)
        f[f"{name}_rel"] = rel
    ranked = {k: cs_rank(v, elig).astype(np.float32) for k, v in f.items()}
    return ranked, elig, cl


def labels(P: Panel, h: int) -> np.ndarray:
    """Return from the close of t+1 (the fill) to the close of t+1+h; a series
    that ends inside the window earns its last price (P.close is carried forward)."""
    y = np.full(P.close.shape, np.nan)
    if P.T > h + 1:
        y[:P.T - 1 - h] = P.close[1 + h:] / P.close[1:P.T - h] - 1
    return y


def relevance(y: np.ndarray, mask: np.ndarray, bins: int = 5) -> np.ndarray:
    rk = cs_rank(y, mask)
    return np.where(np.isfinite(rk), np.minimum((np.nan_to_num(rk) * bins).astype(int), bins - 1), -1)


# ---------------------------------------------------------------------------
# Walk-forward M9
# ---------------------------------------------------------------------------

def year_starts(dates: np.ndarray, first: np.datetime64) -> list[int]:
    yr = dates.astype("datetime64[Y]")
    return [int(np.flatnonzero(yr == y)[0]) for y in np.unique(yr) if y >= first.astype("datetime64[Y]")]


def train_rows(days: np.ndarray, dates: np.ndarray, s: int, h: int) -> np.ndarray:
    """Decision days usable for a model tested from index s: every TRAIN_EVERY-th
    one whose label (t+1 to t+1+h) ends at least EMBARGO days before s, from TRAIN_FROM."""
    t = np.arange(len(days))
    every = np.zeros(len(days), dtype=bool)
    every[np.flatnonzero(days)[::TRAIN_EVERY]] = True
    return every & (t + 1 + h + EMBARGO < s) & (dates >= TRAIN_FROM)


def fit_predict(P: Panel, X: dict[str, np.ndarray], elig: np.ndarray, days: np.ndarray,
                h: int, fs: str, params: dict | None = None, first_test=SELECT_FROM) -> tuple[np.ndarray, list]:
    """Scores (T, N) wherever elig holds from the first test year on, each year
    predicted by a model fitted only on what was known before it. Training rows
    are the (weekly) decision days `days` only."""
    import lightgbm as lgb
    params = dict(PARAMS if params is None else params)
    names = FEATURE_SETS[fs]
    y = labels(P, h)
    ok_x = elig.copy()
    if fs == "full":
        for v in VOLUME_FEATURES:
            ok_x &= np.isfinite(X[v])
    rel = relevance(y, ok_x)
    scores = np.full((P.T, P.N), np.nan)
    starts = year_starts(P.dates, first_test) + [P.T]
    importance = []
    for a, b in zip(starts[:-1], starts[1:]):
        tr = train_rows(days, P.dates, a, h)
        tt, jj = np.nonzero(ok_x & tr[:, None] & (rel >= 0))
        if tt.size < 1000:
            continue
        order = np.lexsort((jj, tt))
        tt, jj = tt[order], jj[order]
        xtr = np.column_stack([X[n][tt, jj] for n in names])
        _, grp = np.unique(tt, return_counts=True)
        model = lgb.LGBMRanker(**params)
        model.fit(xtr, rel[tt, jj], group=grp)
        importance.append(dict(zip(names, model.booster_.feature_importance("gain").tolist())))
        te = np.zeros(P.T, dtype=bool)
        te[a:b] = True
        ti, ji = np.nonzero(ok_x & te[:, None])
        if ti.size:
            scores[ti, ji] = model.predict(np.column_stack([X[n][ti, ji] for n in names]))
    return scores, importance


# ---------------------------------------------------------------------------
# Books
# ---------------------------------------------------------------------------

def top_k(score: np.ndarray, days: np.ndarray, k: int, buffer: bool) -> np.ndarray:
    """Equal-weight targets on the decision days: the K best scores, or with the
    buffer, the held names still in the top 2K first, then the best others."""
    W = np.full(score.shape, np.nan)
    held = np.zeros(score.shape[1], dtype=bool)
    for t in np.flatnonzero(days):
        s = score[t]
        ok = np.flatnonzero(np.isfinite(s))
        if ok.size < k:
            continue
        order = ok[np.argsort(-s[ok], kind="stable")]
        if buffer:
            keep = [j for j in order[:2 * k] if held[j]][:k]
            rest = [j for j in order if not held[j]][:k - len(keep)]
            pick = np.array(keep + rest, dtype=int)
        else:
            pick = order[:k]
        w = np.zeros(score.shape[1])
        w[pick] = 1.0 / k
        W[t] = w
        held = w > 0
    return W


def equal_weight(elig: np.ndarray, days: np.ndarray) -> np.ndarray:
    W = np.full(elig.shape, np.nan)
    for t in np.flatnonzero(days):
        n = elig[t].sum()
        if n:
            W[t] = np.where(elig[t], 1.0 / n, 0.0)
    return W


def spy_book(P: Panel) -> np.ndarray:
    return np.nan_to_num(np.r_[0.0, P.spy[1:] / P.spy[:-1] - 1])


def evaluate(P: Panel, W: np.ndarray, ew: np.ndarray, name: str, lag: int = 1) -> tuple[dict, et.Book]:
    """Row of numbers for a book: Sharpe and information ratio against the equal
    weight index (net, same costs), in the selection window and out of sample."""
    b = et.simulate(P, W, name, lag=lag)
    sel = (P.dates >= SELECT_FROM) & (P.dates < OOS_FROM)
    oos = P.dates >= OOS_FROM
    row = {"name": name}
    for c, cost in COSTS.items():
        x, act = b.net(cost), b.net(cost) - ew[c]
        row[f"sel_sharpe_{c}"] = et.sharpe(x[sel])
        row[f"sel_ir_{c}"] = et.sharpe(act[sel])
        row[f"oos_sharpe_{c}"] = et.sharpe(x[oos])
        row[f"oos_ir_{c}"] = et.sharpe(act[oos])
    x = b.net(COSTS["5bps"])[oos]
    act = x - ew["5bps"][oos]
    s = et.summary(x, b.turnover[oos])
    row.update(oos_cagr=s["cagr"], oos_max_dd=s["max_dd"], oos_turnover_yr=s["turnover_yr"],
               oos_active_yr=float(act.mean() * YEAR_DAYS), oos_days=int(oos.sum()),
               act_skew=float(stats.skew(act)) if act.std() > 0 else 0.0,
               act_kurt=float(stats.kurtosis(act, fisher=False)) if act.std() > 0 else 3.0)
    return row, b


def deflate(rows: list[dict], key: str = "oos_ir_5bps") -> dict:
    """Deflated Sharpe of each row's active return against all rows tried."""
    raw = np.array([r[key] for r in rows])
    var = float(np.var(np.clip(raw, -SR_CLIP, SR_CLIP) / math.sqrt(YEAR_DAYS)))
    for r in rows:
        s = r[key] / math.sqrt(YEAR_DAYS)
        denom = 1 - r["act_skew"] * s + (r["act_kurt"] - 1) / 4 * s ** 2
        r["deflated_p"] = 0.0 if denom <= 0 else deflated_sharpe(s, r["oos_days"], len(rows), var,
                                                                 r["act_skew"], r["act_kurt"])
    g, n = 0.5772156649, len(rows)
    sr0 = 0.0 if n <= 1 else math.sqrt(var) * ((1 - g) * stats.norm.ppf(1 - 1 / n) + g * stats.norm.ppf(1 - 1 / (n * math.e)))
    return {"n_trials": n, "sr_var_daily": var, "expected_max_noise_ir_annual": sr0 * math.sqrt(YEAR_DAYS)}


def rank_ic(score: np.ndarray, y: np.ndarray, days: np.ndarray, mask: np.ndarray) -> dict:
    ics = []
    for t in np.flatnonzero(days & mask):
        ok = np.isfinite(score[t]) & np.isfinite(y[t])
        if ok.sum() >= 30:
            ics.append(stats.spearmanr(score[t, ok], y[t, ok])[0])
    ics = np.array(ics)
    if ics.size < 2:
        return {"mean": float("nan"), "t": float("nan"), "n": int(ics.size)}
    return {"mean": float(ics.mean()), "t": float(ics.mean() / ics.std(ddof=1) * math.sqrt(ics.size)), "n": int(ics.size),
            "share_positive": float((ics > 0).mean())}


def gates(row: dict, b: et.Book, P: Panel, ew_book: et.Book, spy: np.ndarray) -> tuple[dict, dict]:
    oos = P.dates >= OOS_FROM
    x = b.net(COSTS["5bps"])[oos]
    e = ew_book.net(COSTS["5bps"])[oos]
    boot = et.block_bootstrap(x, e, draws=BOOT_DRAWS)
    yr = per_year_active(P, b.net(COSTS["5bps"]), ew_book.net(COSTS["5bps"]), oos)
    g = {
        "deflated p of the active return > 0.95": row["deflated_p"] > 0.95,
        "OOS IR >= half the selection window's (> 0)": row["sel_ir_5bps"] > 0 and row["oos_ir_5bps"] >= 0.5 * row["sel_ir_5bps"],
        "IR > 0 with costs doubled": row["oos_ir_10bps"] > 0,
        "Sharpe above SPY and equal weight": row["oos_sharpe_5bps"] > max(et.sharpe(spy[oos]), et.sharpe(e)),
        "bootstrap: Sharpe above equal weight in >= 90 % of draws": boot["diff_share_above_0"] >= 0.90,
        "active return positive in more than half the years": sum(v["active"] > 0 for v in yr.values()) > len(yr) / 2,
    }
    return g, {"bootstrap": boot, "per_year": yr}


def per_year_active(P: Panel, x: np.ndarray, e: np.ndarray, mask: np.ndarray) -> dict[int, dict]:
    yr = P.dates.astype("datetime64[Y]").astype(int) + 1970
    out = {}
    for y in np.unique(yr[mask]):
        m = mask & (yr == y)
        a, b = float(np.prod(1 + x[m]) - 1), float(np.prod(1 + e[m]) - 1)
        out[int(y)] = {"book": a, "equal_weight": b, "active": a - b}
    return out


# ---------------------------------------------------------------------------
# The study
# ---------------------------------------------------------------------------

def model_scores(P: Panel, X: dict, elig: np.ndarray, days: np.ndarray, refit: bool = False,
                 params: dict | None = None, cache: Path | None = MODEL_CACHE) -> tuple[dict, dict]:
    out, imp = {}, {}
    for h in HORIZONS:
        for fs in FEATURE_SETS:
            key = f"h{h}_{fs}"
            f = None if cache is None else cache / f"{key}.npz"
            if f is not None and f.exists() and not refit:
                z = np.load(f, allow_pickle=False)
                if z["scores"].shape == (P.T, P.N) and str(z["last"]) == str(P.dates[-1]):
                    out[key] = z["scores"]
                    imp[key] = json.loads(str(z["importance"]))
                    continue
            s, im = fit_predict(P, X, elig, days, h, fs, params)
            out[key], imp[key] = s, im
            if f is not None:
                f.parent.mkdir(parents=True, exist_ok=True)
                np.savez_compressed(f, scores=s, last=str(P.dates[-1]), importance=json.dumps(im))
            print(f"{NAME}: fitted {key}", file=sys.stderr, flush=True)
    return out, imp


def run(P: Panel, refit: bool = False, params: dict | None = None, cache: Path | None = MODEL_CACHE) -> dict:
    days = et.decision_days(P.dates)
    alt = {wd: et.decision_days(P.dates, wd) for wd in range(4)}
    any_day = days.copy()
    for d in alt.values():
        any_day |= d
    X, elig, _ = features(P, any_day)
    scores, importance = model_scores(P, X, elig, days, refit, params, cache)

    ew_w = equal_weight(elig, days)
    ew_book = et.simulate(P, ew_w, "equal weight")
    ew = {c: ew_book.net(cost) for c, cost in COSTS.items()}
    spy = spy_book(P)

    rows, books = [], {}
    for h in HORIZONS:
        for fs in FEATURE_SETS:
            for k in KS:
                for buf in (False, True):
                    name = f"M9 h{h} {fs} top {k}{' buffer' if buf else ''}"
                    r, b = evaluate(P, top_k(scores[f"h{h}_{fs}"], days, k, buf), ew, name)
                    r.update(family="M9", h=h, fs=fs, k=k, buffer=buf)
                    rows.append(r)
                    books[name] = b
    for label, (feat, sign) in BASELINES.items():
        sc = np.where(elig, sign * X[feat], np.nan)
        for k in KS:
            for buf in (False, True):
                name = f"{label} top {k}{' buffer' if buf else ''}"
                r, b = evaluate(P, top_k(sc, days, k, buf), ew, name)
                r.update(family="baseline", feature=feat, k=k, buffer=buf)
                rows.append(r)
                books[name] = b
    m9 = [r for r in rows if r["family"] == "M9"]
    pick = max(m9, key=lambda r: r["sel_ir_5bps"])
    base_pick = max((r for r in rows if r["family"] == "baseline"), key=lambda r: r["sel_ir_5bps"])
    sc = scores[f"h{pick['h']}_{pick['fs']}"]
    for wd, d in alt.items():
        name = f"{pick['name']} · {WEEKDAYS[wd]}"
        ew_d = et.simulate(P, equal_weight(elig, d), "ew")
        r, b = evaluate(P, top_k(sc, d, pick["k"], pick["buffer"]), {c: ew_d.net(v) for c, v in COSTS.items()}, name)
        r.update(family="robustness")
        rows.append(r)
        books[name] = b
    name = f"{pick['name']} · filled a day late"
    r, b = evaluate(P, top_k(sc, days, pick["k"], pick["buffer"]), ew, name, lag=2)
    r.update(family="robustness")
    rows.append(r)
    books[name] = b
    defl = deflate(rows)

    oos = P.dates >= OOS_FROM
    sel = (P.dates >= SELECT_FROM) & (P.dates < OOS_FROM)
    judged = {}
    for label, pr in (("M9", pick), ("baseline", base_pick)):
        g, extra = gates(pr, books[pr["name"]], P, ew_book, spy)
        judged[label] = {"pick": pr["name"], "row": pr, "gates": g, "passes": all(g.values()), **extra,
                         "oos": et.summary(books[pr["name"]].net(COSTS["5bps"])[oos], books[pr["name"]].turnover[oos])}
    ic = {}
    for h in HORIZONS:
        y = labels(P, h)
        for fs in FEATURE_SETS:
            ic[f"h{h}_{fs}"] = {"selection": rank_ic(scores[f"h{h}_{fs}"], y, days, sel),
                                "oos": rank_ic(scores[f"h{h}_{fs}"], y, days, oos)}
    imp = importance[f"h{pick['h']}_{pick['fs']}"]
    mean_imp = {k: float(np.mean([d[k] for d in imp])) for k in imp[0]} if imp else {}
    tot = sum(mean_imp.values()) or 1.0
    universe = elig[days & oos].sum(1)
    return {
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "data": {"first": str(P.dates[0]), "last": str(P.dates[-1]), "tickers": P.N,
                 "members_ever": int(P.member.any(0).sum()),
                 "universe_oos_median": float(np.median(universe)) if universe.size else 0.0,
                 "source": SOURCE.format("")},
        "selection": [str(SELECT_FROM), str(OOS_FROM)],
        "rows": rows,
        "deflation": defl,
        "judged": judged,
        "benchmarks_oos": {"SPY buy and hold": et.summary(spy[oos]),
                           "equal weight": et.summary(ew["5bps"][oos], ew_book.turnover[oos])},
        "benchmarks_sel": {"SPY buy and hold": et.sharpe(spy[sel]), "equal weight": et.sharpe(ew["5bps"][sel])},
        "rank_ic": ic,
        "importance_pick": {k: v / tot for k, v in sorted(mean_imp.items(), key=lambda kv: -kv[1])},
        "passes": judged["M9"]["passes"] or judged["baseline"]["passes"],
    }


def markdown(res: dict) -> str:
    from ..report import table
    d = res["data"]
    lines = [f"# {NAME} (M9)", "",
             f"Generated {res['generated']}. Point-in-time S&P 500, {d['members_ever']} names ever in the index "
             f"(dead ones included), data {d['first']} to {d['last']}. Selection window {res['selection'][0]} to "
             f"{res['selection'][1]} (walk-forward predictions), out of sample from {res['selection'][1]}; median "
             f"universe out of sample {d['universe_oos_median']:.0f} names. Costs 5 bps per side (10 bps doubled). "
             "Weekly, filled at the next close. IR = Sharpe of the book's daily return minus the equal-weight index's.", ""]
    bo, bs = res["benchmarks_oos"], res["benchmarks_sel"]
    lines += ["## Benchmarks", "", table([{"book": k, "sel_sharpe": bs[k], **v} for k, v in bo.items()],
                                         ["book", "sel_sharpe", "sharpe", "cagr", "vol", "max_dd"])]
    lines += ["## Rank IC of M9 (Spearman, weekly decision days)", "",
              table([{"model": k, "sel_ic": v["selection"]["mean"], "sel_t": v["selection"]["t"],
                      "oos_ic": v["oos"]["mean"], "oos_t": v["oos"]["t"], "oos_share_pos": v["oos"].get("share_positive")}
                     for k, v in res["rank_ic"].items()], ["model", "sel_ic", "sel_t", "oos_ic", "oos_t", "oos_share_pos"]),
              "t uses one IC per week; with 10 and 20-day labels the weeks overlap, so those t are too high.", ""]
    cols = ["name", "sel_ir_5bps", "oos_ir_5bps", "oos_ir_10bps", "oos_sharpe_5bps", "oos_cagr", "oos_max_dd",
            "oos_active_yr", "oos_turnover_yr", "deflated_p"]
    lines += ["## Every trial", "", table(res["rows"], cols)]
    df = res["deflation"]
    lines += [f"{df['n_trials']} trials; the best of that many noise books would show an information ratio of about "
              f"{df['expected_max_noise_ir_annual']:.2f}.", ""]
    for label, j in res["judged"].items():
        b = j["bootstrap"]
        lines += [f"## {label} pick: {j['pick']}", "",
                  table([{"book": j["pick"], **j["oos"]}], ["book", "sharpe", "cagr", "vol", "max_dd", "turnover_yr"]),
                  f"Block bootstrap (20 days, {BOOT_DRAWS} draws): Sharpe 90 % interval {b['p05']:.2f} to {b['p95']:.2f}; "
                  f"Sharpe minus equal weight's {b['diff_p05']:.2f} to {b['diff_p95']:.2f}, {b['diff_share_above_0']:.0%} above 0.", "",
                  table([{"year": y, **v} for y, v in sorted(j["per_year"].items())], ["year", "book", "equal_weight", "active"])]
        lines += [f"- {'pass' if ok else 'FAIL'}: {g}" for g, ok in j["gates"].items()]
        lines += ["", f"Verdict: {'passes the lab bar' if j['passes'] else 'does not pass the lab bar'}.", ""]
    if res["importance_pick"]:
        lines += ["## What the M9 pick's model uses (share of gain, mean over yearly fits)", "",
                  table([{"feature": k, "gain_share": v} for k, v in res["importance_pick"].items()], ["feature", "gain_share"])]
    return "\n".join(lines)


def main() -> int:
    from .. import report
    try:
        P = load_panel(refresh="--refresh" in sys.argv)
    except DataUnavailable as e:
        print(f"{NAME}: no data, nothing judged: {e}", file=sys.stderr)
        return 2
    res = run(P, refit="--refit" in sys.argv)
    report.write(NAME, markdown(res), res)
    return 0


if __name__ == "__main__":
    sys.exit(main())
