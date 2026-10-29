"""RF1: does a forecast of tomorrow's range help the daily books as a filter, against honest baselines?

Pre-registered in results/range_forecast_rf1_prereg.md; results in results/range_forecast_rf1.md.

    PYTHIA_AGENT_OUT=<panel cache> PYTHIA_TRIALS_REGISTRY=<registry> PYTHIA_REPORTS=<reports> \
        flock <heavy lock> python -m lab.experiments.range_forecast_rf1 [--no-register] [--report]

A friend's TradingView indicator forecasts tomorrow's true range with GARCH(1,1) and calls a day good when the
forecast is above the 20-day average true range. Part A forecasts the next day's true range (judged) and high-low
range, as a fraction of today's close, for the 15 Alpaca coins (the sweep's daily panel with the bars before 2020,
a day's open the previous close) and SPY, QQQ, IWM (W4's 5-minute SIP cache, the regular session; the sector ETFs
have closes only and are dropped): GARCH(1,1) on returns, CARR(1,1) on the range, HAR on Parkinson, Garman-Klass,
Rogers-Satchell and Yang-Zhang, against yesterday's range, the 20-day average and EWMA 0.94, every forecast with one
QLIKE scale fitted in training, quarterly walk-forward from 2018. QLIKE and the good-day accuracy against the
persistence rule with Diebold-Mariano on validation. Part B, only for a group whose forecast passes A: three entry
filters (good days, range over the hold under three round trips, after a compression) on breakout_top10 as it runs
on Alpaca (35 bps) and W4's four long-only ETF picks (W4's costs), each against its own unfiltered book: CE up,
drawdown not worse, bootstrap band of the CE gain above 0, DSR of the excess at least 0.95. Every trial goes into R5's
registry before its validation number. Rows from 2026-07-01 on are dropped at load: the lockbox is never read.
Nothing here changes a book, a gate, the engine or a wallet.
"""

from __future__ import annotations

import json
import math
import sys
import time
import warnings
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import polars as pl
from scipy import optimize, signal, stats

from .. import metrics
from . import alpaca_universe as au
from . import director_common as dc
from . import fam_breakout
from . import fam_common as fc
from . import intraday_equities as ie

NAME = "range_forecast_rf1"
PREREG = "results/range_forecast_rf1_prereg.md"
WF_FROM, IS_TO, VAL_FROM, VAL_TO, LOCKBOX = "2018-01-01", "2023-12-31", "2024-01-01", "2026-06-30", "2026-07-01"
MIN_HIST = 365                                    # rows of an asset before its first fold
MODELS = ("GARCH", "CARR", "HAR-PK", "HAR-GK", "HAR-RS", "HAR-YZ")
BASELINES = ("RW1", "MA20", "EWMA")
KEYS = MODELS + BASELINES
TARGETS = ("tr", "hl")
HAR_LAGS = {"coins": (1, 7, 30), "etfs": (1, 5, 22)}
YEAR = {"coins": 365, "etfs": 252}
EWMA_L, ATR_N = 0.94, 20
YZ_K = 0.34 / (1.34 + 23 / 21)
FLOOR = 1e-6
DM_LAGS = 10
ALPHA = 0.05 / len(MODELS)
GAMMA = 3.0
BOOT_DRAWS, BOOT_BLOCK, BOOT_SEED = 2000, 20, 7
DSR_PASS = 0.95
COIN_COST, COIN_MAKER = 0.0035, 0.0015
COST_MULT = 6                                     # three round trips = six times the cost a side
SQ_WIN, SQ_MIN, SQ_Q, SQ_LOOK = 250, 120, 0.2, 5
ETF_RULES = ("ORB 15m long", "Gap go 1.5 long", "VWAP k 2.0 long", "EOD momentum first long")
FILTERS = ("good", "cost", "squeeze")
FRIEND = (23, 32)                                 # 72 % of 32 days
WINDOW_32 = 32


# ---------------------------------------------------------------- per asset series (rows of valid days)

def series(o: np.ndarray, h: np.ndarray, l: np.ndarray, c: np.ndarray) -> dict:
    """Per row: the true range (price), z_tr and z_hl (today's range over yesterday's close), the log return and
    the four daily variance estimates. Row 0 has no previous close (NaN where it is needed)."""
    pc = np.r_[np.nan, c[:-1]]
    with np.errstate(invalid="ignore", divide="ignore"):
        tr = np.maximum(h, pc) - np.minimum(l, pc)
        tr[0] = h[0] - l[0]
        hl2 = np.log(h / l) ** 2
        co = np.log(c / o)
        rs = np.log(h / c) * np.log(h / o) + np.log(l / c) * np.log(l / o)
        return {"tr": tr, "z_tr": tr / pc, "z_hl": (h - l) / pc, "ret": np.log(c / pc),
                "PK": hl2 / (4 * math.log(2)), "GK": np.maximum(0.5 * hl2 - (2 * math.log(2) - 1) * co ** 2, 0.0),
                "RS": np.maximum(rs, 0.0), "YZ": np.log(o / pc) ** 2 + YZ_K * co ** 2 + (1 - YZ_K) * np.maximum(rs, 0)}


def rolling_mean(x: np.ndarray, n: int) -> np.ndarray:
    """Mean of x[i-n+1..i]; NaN until n values and wherever the window holds a NaN."""
    out = np.full(len(x), np.nan)
    if len(x) < n:
        return out
    bad = np.r_[0, np.cumsum(~np.isfinite(x))]
    cs = np.r_[0.0, np.cumsum(np.nan_to_num(x))]
    m = (cs[n:] - cs[:-n]) / n
    out[n - 1:] = np.where(bad[n:] - bad[:-n] == 0, m, np.nan)
    return out


def recursion(x: np.ndarray, w: float, a: float, b: float, s0: float) -> np.ndarray:
    """s[0] = s0, s[j+1] = w + a x[j] + b s[j]: len(x) + 1 values (GARCH's variance, CARR's range)."""
    s = signal.lfilter([1.0], [1.0, -b], w + a * x, zi=[b * s0])[0]
    return np.r_[s0, s]


def _fit(x: np.ndarray, nll_of) -> tuple[float, float, float]:
    m = float(np.mean(x))
    start = np.array([m * 0.1, 0.1, 0.85])

    def nll(p):
        w, a, b = p
        if w <= 0 or a < 0 or b < 0 or a + b >= 0.999:
            return 1e12
        s = recursion(x, w, a, b, m)[:-1]
        if not np.all(s > 0):
            return 1e12
        return float(nll_of(s, x))
    res = optimize.minimize(nll, start, method="Nelder-Mead", options={"maxiter": 600, "xatol": 1e-8, "fatol": 1e-8})
    p = res.x if np.isfinite(res.fun) and res.fun < 1e12 else start
    return float(p[0]), float(p[1]), float(p[2])


def fit_garch(r2: np.ndarray) -> tuple[float, float, float]:
    """GARCH(1,1) by Gaussian QMLE on squared demeaned returns (the variance path starts at their mean)."""
    return _fit(r2, lambda s, x: 0.5 * np.sum(np.log(s) + x / s))


def fit_carr(R: np.ndarray) -> tuple[float, float, float]:
    """CARR(1,1) (Chou 2005) by exponential QMLE on the range (the path starts at its mean)."""
    return _fit(R, lambda s, x: np.sum(np.log(s) + x / s))


def quarter_starts(first: str = WF_FROM, last: str = VAL_TO) -> np.ndarray:
    q = np.arange(np.datetime64(first, "M"), np.datetime64(last, "M") + np.timedelta64(1, "M"), np.timedelta64(3, "M"))
    return q.astype("datetime64[D]")


def asset_forecasts(dates: np.ndarray, o, h, l, c, lags: tuple[int, int, int], keys=KEYS,
                    targets=TARGETS) -> dict[str, dict[str, np.ndarray]]:
    """{target: {key: f}} over the asset's rows: f[i] the forecast made at the close of row i of z[i + 1], walk-forward
    by quarter (parameters and scale fitted on the pairs whose target lies before the quarter), NaN outside a fold."""
    n = len(c)
    S = series(o, h, l, c)
    out = {t: {k: np.full(n, np.nan) for k in keys} for t in targets}
    sv = {e: np.sqrt(S[e]) for e in ("PK", "GK", "RS", "YZ")}
    har_x = {e: np.column_stack([np.ones(n)] + [rolling_mean(v, m) for m in lags]) for e, v in sv.items()}
    base = {}
    for t in targets:
        z = S[f"z_{t}"]
        ma = rolling_mean(z, ATR_N)
        ew = np.full(n, np.nan)
        if n > ATR_N + 1:                         # z[0] has no previous close: the first 20-day mean is at row 20
            ew[ATR_N:] = recursion(np.nan_to_num(z[ATR_N + 1:]), 0.0, 1 - EWMA_L, EWMA_L, ma[ATR_N])
        base[t] = {"RW1": z, "MA20": ma, "EWMA": ew}
    qs = quarter_starts()
    for qi, s in enumerate(qs):
        k0 = int(np.searchsorted(dates, s))
        k1 = int(np.searchsorted(dates, qs[qi + 1])) if qi + 1 < len(qs) else int(np.searchsorted(dates, np.datetime64(
            LOCKBOX), side="left"))
        if k0 < MIN_HIST or k1 <= k0:
            continue
        raw = {}
        if "GARCH" in keys:
            r = S["ret"][1:k1]
            mu = float(np.nanmean(r[:k0 - 1]))
            r2 = np.nan_to_num((r - mu) * 100) ** 2
            w, a, b = fit_garch(r2[:k0 - 1])
            path = recursion(r2, w, a, b, float(np.mean(r2[:k0 - 1])))        # path[i]: at row i for row i + 1
            raw["GARCH"] = {t: np.sqrt(path[:k1]) / 100 for t in targets}
        for e in ("PK", "GK", "RS", "YZ"):
            key = f"HAR-{e}"
            if key not in keys:
                continue
            X, y = har_x[e][:k1], np.r_[sv[e][1:k1], np.nan]
            tr = np.arange(k1) < k0 - 1
            ok = tr & np.all(np.isfinite(X), 1) & np.isfinite(y)
            beta = np.linalg.lstsq(X[ok], y[ok], rcond=None)[0]
            raw[key] = {t: np.maximum(X @ beta, FLOOR) for t in targets}
        for t in targets:
            z = S[f"z_{t}"]
            if "CARR" in keys:
                R = np.nan_to_num(z[1:k1])
                w, a, b = fit_carr(R[:k0 - 1])
                raw.setdefault("CARR", {})[t] = recursion(R, w, a, b, float(np.mean(R[:k0 - 1])))[:k1]
            for k in BASELINES:
                if k in keys:
                    raw.setdefault(k, {})[t] = base[t][k][:k1]
            y = np.r_[z[1:k1], np.nan]
            for k in keys:
                g = raw[k][t]
                with np.errstate(invalid="ignore", divide="ignore"):
                    q = y[:k0 - 1] / g[:k0 - 1]
                q = q[np.isfinite(q) & (g[:k0 - 1] > 0)]
                scale = float(q.mean()) if len(q) else np.nan
                out[t][k][k0:k1] = np.maximum(scale * g[k0:k1], FLOOR)
    return out


# ---------------------------------------------------------------- groups: (T, N) arrays on one calendar

def group_forecasts(G: dict, keys=KEYS, targets=TARGETS) -> dict:
    """Forecasts, targets and the friend's yardsticks of a group {name, days, names, o, h, l, c} as (T, N) arrays,
    each at the row of the close it is known at: f[target][key], y[target] (the next valid row's z), tr (today's
    true range in price), tr_next, atr20 (mean true range of the last 20 rows, today included), c."""
    T, N = G["c"].shape
    lags = HAR_LAGS[G["name"]]
    nan = lambda: np.full((T, N), np.nan)   # noqa: E731
    out = {"f": {t: {k: nan() for k in keys} for t in targets}, "y": {t: nan() for t in targets},
           "tr": nan(), "tr_next": nan(), "atr20": nan(), "c": nan()}
    for j in range(N):
        o, h, l, c = (G[k][:, j] for k in ("o", "h", "l", "c"))
        with np.errstate(invalid="ignore"):
            idx = np.flatnonzero(np.isfinite(o) & np.isfinite(h) & np.isfinite(l) & np.isfinite(c)
                                 & (o > 0) & (l > 0) & (c > 0) & (h >= l))
        if len(idx) < MIN_HIST + 2:
            continue
        S = series(o[idx], h[idx], l[idx], c[idx])
        F = asset_forecasts(G["days"][idx], o[idx], h[idx], l[idx], c[idx], lags, keys, targets)
        for t in targets:
            out["y"][t][idx[:-1], j] = S[f"z_{t}"][1:]
            for k in keys:
                out["f"][t][k][idx, j] = F[t][k]
        out["tr"][idx, j] = S["tr"]
        out["tr_next"][idx[:-1], j] = S["tr"][1:]
        out["atr20"][idx, j] = rolling_mean(S["tr"], ATR_N)
        out["c"][idx, j] = c[idx]
    return out


def coin_group(frame: pl.DataFrame | None = None) -> dict:
    """The 15 Alpaca coins (their current segments) from lab.history's long frame, cut before the lockbox; a day's
    open is the previous close (the close carried over a missing day)."""
    if frame is None:
        from .. import history
        frame = history.long_frame()
    names = sorted(s for s in frame["symbol"].unique().to_list() if "~" not in s and fc.base_of(s) in au.ALPACA)
    f = frame.filter(pl.col("symbol").is_in(names) & (pl.col("day") < dc.us(LOCKBOX)))
    days = np.arange(f["day"].min(), f["day"].max() + fc.DAY_US, fc.DAY_US, dtype=np.int64)
    T, N = len(days), len(names)
    ri = ((f["day"].to_numpy() - days[0]) // fc.DAY_US).astype(np.int64)
    ci = np.array([names.index(s) for s in f["symbol"].to_list()])
    G = {"name": "coins", "names": names, "days_us": days, "days": days.astype("datetime64[us]").astype("datetime64[D]")}
    for k in ("close", "high", "low"):
        m = np.full((T, N), np.nan)
        m[ri, ci] = f[k].to_numpy().astype(float)
        G[k[0]] = m
    px = G["c"].copy()
    for t in range(1, T):
        px[t] = np.where(np.isfinite(px[t]), px[t], px[t - 1])
    G["o"] = np.r_[np.full((1, N), np.nan), px[:-1]]
    return G


def load_etf_bars(root: Path | None = None, last: str = VAL_TO) -> ie.Bars:
    """W4's SIP 5-minute cache of SPY, QQQ and IWM, rows after `last` dropped before anything, on W4's calendar (SPY's
    full sessions) and W4's valid-day rule."""
    cache = (root or ie.CACHE_ROOT) / "alpaca-sip"
    cut = date.fromisoformat(last)
    per, frames = {}, {}
    for s in ie.ETFS:
        files = sorted((cache / s).glob("*.parquet"))
        if not files:
            raise ie.DataUnavailable(f"no cached bars of {s} under {cache}")
        df = pl.concat([pl.read_parquet(f) for f in files]).filter(pl.col("date") <= cut).sort("date", "bar")
        frames[s] = df
        per[s] = ie.frame_to_blocks(df)
    spy = frames["SPY"].group_by("date").agg(n=pl.len(), last=pl.col("bar").max()).sort("date")
    full = (spy["n"].to_numpy() >= 70) & (spy["last"].to_numpy() >= ie.EXIT_BAR)
    calendar = spy["date"].to_numpy().astype("datetime64[D]")[full]
    valid = {s: df.group_by("date").agg(n=pl.len()).sort("date")["n"].to_numpy() >= ie.NB // 2
             for s, df in frames.items()}
    return ie.assemble(per, valid, calendar, {}, "alpaca", [f"SIP cache to {last}, {len(calendar)} full sessions"])


def etf_group(B: ie.Bars) -> dict:
    """Daily OHLC of the regular session: the 09:30 bar's open, the session's high and low, the 15:55 bar's close."""
    with np.errstate(invalid="ignore"):
        h, l = np.nanmax(B.h, 2), np.nanmin(B.l, 2)
    ok = B.valid
    pick = lambda a: np.where(ok, a, np.nan).T   # noqa: E731
    days = B.dates.astype("datetime64[D]")
    return {"name": "etfs", "names": list(B.syms), "days": days,
            "days_us": days.astype("datetime64[us]").astype(np.int64),
            "o": pick(B.o[:, :, 0]), "h": pick(h), "l": pick(l), "c": pick(B.c[:, :, ie.NB - 1])}


# ---------------------------------------------------------------- Part A: losses and tests

def qlike(y: np.ndarray, f: np.ndarray) -> np.ndarray:
    with np.errstate(invalid="ignore", divide="ignore"):
        q = y / f
        return q - np.log(q) - 1.0


def dm_one_sided(d: np.ndarray, lags: int = DM_LAGS) -> tuple[float, float]:
    """DM on a daily loss difference (model - other); (statistic, one-sided p that the model is better)."""
    d = d[np.isfinite(d)]
    if len(d) < 30 or np.all(d == d[0]):
        return float("nan"), 1.0
    st, _ = metrics.diebold_mariano(d, np.zeros_like(d), lag=lags)
    return st, float(stats.norm.cdf(st))


def window_mask(days: np.ndarray, first: str | None, last: str | None) -> np.ndarray:
    m = np.ones(len(days), dtype=bool)
    if first:
        m &= days >= np.datetime64(first)
    if last:
        m &= days <= np.datetime64(last)
    return m


def part_a(G: dict, R: dict, keys=KEYS) -> dict:
    """Per target: QLIKE by window and year, DM against the baselines and the good-day accuracy against persistence,
    on the rows where every forecast exists; the verdict per model on TR."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)          # a day without a common row: an empty mean
        return _part_a(G, R, keys)


def _part_a(G: dict, R: dict, keys) -> dict:
    days = G["days"]
    yr = (days.astype("datetime64[Y]").astype(int) + 1970).astype(str)
    wins = {"2018-2023": window_mask(days, WF_FROM, IS_TO), "validation": window_mask(days, VAL_FROM, VAL_TO)}
    out = {"assets": G["names"], "targets": {}}
    for t in TARGETS:
        y = R["y"][t]
        F = R["f"][t]
        common = np.isfinite(y) & (y > 0)
        for k in keys:
            common &= np.isfinite(F[k])
        L = {k: np.where(common, qlike(y, F[k]), np.nan) for k in keys}
        good_ok = common & np.isfinite(R["atr20"]) & np.isfinite(R["tr_next"])
        actual = R["tr_next"] > R["atr20"]
        pred = {k: F[k] * R["c"] > R["atr20"] for k in keys}
        pred["persistence"] = R["tr"] > R["atr20"]
        miss = {k: np.where(good_ok, (p != actual).astype(float), np.nan) for k, p in pred.items()}
        rows = []
        for k in keys:
            row = {"model": k}
            for w, m in wins.items():
                row[f"qlike {w}"] = float(np.nanmean(L[k][m])) if np.isfinite(L[k][m]).any() else float("nan")
                row[f"acc {w}"] = 1 - float(np.nanmean(miss[k][m])) if np.isfinite(miss[k][m]).any() else float("nan")
                row[f"good share {w}"] = float(np.mean(pred[k][m][good_ok[m]])) if good_ok[m].any() else float("nan")
            row["rows validation"] = int(common[wins["validation"]].sum())
            v = wins["validation"]
            for b in BASELINES:
                if b == k:
                    continue
                with np.errstate(invalid="ignore"):
                    d = np.nanmean(np.where(common, L[k] - L[b], np.nan)[v], 1)
                st, p = dm_one_sided(d)
                row[f"gain vs {b} %"] = 100 * (1 - row["qlike validation"] / float(np.nanmean(L[b][v])))
                row[f"dm vs {b}"], row[f"p vs {b}"] = st, p
            with np.errstate(invalid="ignore"):
                d = np.nanmean((miss[k] - miss["persistence"])[v], 1)
            row["dm acc"], row["p acc"] = dm_one_sided(d)
            row["by year"] = {str(a): float(np.nanmean(L[k][yr == a])) for a in np.unique(yr[common.any(1)])}
            if k in MODELS:
                row["pass"] = bool(all(row[f"p vs {b}"] < ALPHA and row[f"gain vs {b} %"] > 0 for b in BASELINES)
                                   and row["p acc"] < ALPHA)
            rows.append(row)
        pers = {"model": "persistence"}
        for w, m in wins.items():
            pers[f"acc {w}"] = 1 - float(np.nanmean(miss["persistence"][m]))
            pers[f"good share {w}"] = float(np.mean(pred["persistence"][m][good_ok[m]]))
        acc_p = {w: pers[f"acc {w}"] for w in wins}
        for r in rows:
            r["beats persistence"] = bool(r["acc validation"] > acc_p["validation"])
        out["targets"][t] = {"rows": rows, "persistence": pers, "windows32": windows32(miss, G["days"], keys),
                             "base_rate": {w: float(np.mean(actual[m][good_ok[m]])) for w, m in wins.items()}}
    return out


def windows32(miss: dict, days: np.ndarray, keys) -> dict:
    """Per model on validation: the share of an asset's non-overlapping 32-day windows (rows in order) with the
    friend's 72 % or more right, and the 5 % and 95 % of the windows' accuracy."""
    v = window_mask(days, VAL_FROM, VAL_TO)
    out = {}
    for k in list(keys) + ["persistence"]:
        accs = []
        for j in range(miss[k].shape[1]):
            x = miss[k][v, j]
            x = x[np.isfinite(x)]
            for a in range(0, len(x) - WINDOW_32 + 1, WINDOW_32):
                accs.append(1 - x[a:a + WINDOW_32].mean())
        accs = np.array(accs)
        out[k] = {"windows": int(len(accs)), "share_72": float(np.mean(accs >= FRIEND[0] / FRIEND[1])) if len(accs)
                  else float("nan"), "p05": float(np.quantile(accs, 0.05)) if len(accs) else float("nan"),
                  "p95": float(np.quantile(accs, 0.95)) if len(accs) else float("nan")}
    return out


def friend_band() -> tuple[float, float]:
    ci = stats.binomtest(FRIEND[0], FRIEND[1]).proportion_ci(0.95)
    return float(ci.low), float(ci.high)


def chosen(A: dict) -> str | None:
    """The group's Part B forecast: of the models that pass on TR, the lowest 2018-2023 QLIKE."""
    ok = [r for r in A["targets"]["tr"]["rows"] if r.get("pass")]
    return min(ok, key=lambda r: r["qlike 2018-2023"])["model"] if ok else None


def leak_check(G: dict, cols=("BTCUSDT", "ETHUSDT")) -> dict:
    """T1's harness on the TR forecasts of two coins: every value after a cut changed, nothing before it may move."""
    from .. import leak
    js = [G["names"].index(c) for c in cols if c in G["names"]]
    data = {"days": G["days_us"], **{k: G[k][:, js] for k in ("o", "h", "l", "c")}}

    def fn(X):
        g = {"name": G["name"], "days": X["days"].astype("datetime64[us]").astype("datetime64[D]"),
             "names": list(cols), **{k: X[k] for k in ("o", "h", "l", "c")}}
        return group_forecasts(g, targets=("tr",))["f"]["tr"]
    T = len(G["days_us"])
    cuts = [int(np.searchsorted(G["days"], np.datetime64(d))) for d in ("2019-08-15", "2021-05-20", "2023-02-10",
                                                                         "2025-03-03")]
    return leak.check(fn, data, cuts=[c for c in cuts if 0 < c < T - 1], kinds=("shuffle", "nan"), name="rf1 tr")


# ---------------------------------------------------------------- Part B: the filters

def shift_next(X: np.ndarray, valid: np.ndarray) -> np.ndarray:
    """(T, N) the value at each column's previous valid row (what is known at the close before a session)."""
    out = np.full(X.shape, np.nan)
    for j in range(X.shape[1]):
        idx = np.flatnonzero(valid[:, j])
        out[idx[1:], j] = X[idx[:-1], j]
    return out


def squeeze_flags(f: np.ndarray, valid: np.ndarray) -> np.ndarray:
    """(T, N) True at a close when, at one of the five valid closes before it, the forecast was in the lowest fifth
    of the column's own previous 250 forecasts (at least 120)."""
    out = np.zeros(f.shape, dtype=bool)
    for j in range(f.shape[1]):
        idx = np.flatnonzero(valid[:, j] & np.isfinite(f[:, j]))
        x = f[idx, j]
        low = np.zeros(len(x), dtype=bool)
        for i in range(SQ_MIN, len(x)):
            w = x[max(0, i - SQ_WIN):i]
            low[i] = np.mean(w < x[i]) <= SQ_Q
        lowc = np.r_[0, np.cumsum(low)]
        for i in range(1, len(x)):
            a = max(0, i - SQ_LOOK)
            out[idx[i], j] = lowc[i] - lowc[a] > 0
    return out


def breakout_gated(P: fc.Panel, cols: np.ndarray, allowed: np.ndarray, n: int, slots: int,
                   gate: np.ndarray | None = None) -> np.ndarray:
    """fam_breakout.breakout_weights (no regime) with gate (T, N) as one more condition on an entry: a blocked
    breakout can enter at a later close where it still holds. gate None is the book as it runs."""
    px = P.px[:, cols]
    hi = fc.rolling_extreme(px, n, "max")
    lo = fc.rolling_extreme(px, n // 2, "min")
    g = np.ones((P.T, len(cols)), dtype=bool) if gate is None else gate[:, cols]
    with np.errstate(invalid="ignore"):
        enter = (px > hi) & allowed[:, cols] & g
        leave = (px < lo) | ~P.alive[:, cols]
    with np.errstate(invalid="ignore", divide="ignore"):
        size = np.minimum(fam_breakout.COIN_VOL / (P.sigma[:, cols] * np.sqrt(365)) / slots, 1.0 / slots)
    size = np.nan_to_num(size)
    W = np.full((P.T, P.N), np.nan)
    held = np.zeros(len(cols), dtype=bool)
    for t in range(P.T):
        row = np.full(len(cols), np.nan)
        ex = held & leave[t]
        en = ~held & enter[t] & (size[t] > 0)
        row[ex] = 0.0
        row[en] = size[t, en]
        held = (held & ~ex) | en
        W[t, cols] = row
    W[:, np.setdiff1d(np.arange(P.N), cols)] = 0.0
    return W


def runs(on: np.ndarray) -> list[tuple[int, int, int]]:
    """(column, start row, length) of every run of True in a (T, N) array."""
    out = []
    for j in range(on.shape[1]):
        x = np.r_[False, on[:, j], False].astype(np.int8)
        d = np.diff(x)
        for a, b in zip(np.flatnonzero(d == 1), np.flatnonzero(d == -1)):
            out.append((j, int(a), int(b - a)))
    return out


def ce(x: np.ndarray, year: int) -> float:
    return float(year * np.mean(x) - GAMMA / 2 * year * np.var(x)) if len(x) else float("nan")


def max_dd(x: np.ndarray) -> float:
    w = np.cumprod(1 + x)
    return float(np.max(1 - w / np.maximum.accumulate(w))) if len(x) else 0.0


def sharpe(x: np.ndarray, year: int) -> float:
    sd = x.std() if len(x) > 1 else 0.0
    return float(x.mean() / sd * math.sqrt(year)) if sd > 0 else 0.0


def judge(xf: np.ndarray, xb: np.ndarray, year: int, pool: dict) -> dict:
    """The four gates of one filtered book against its unfiltered book over the validation days."""
    idx = metrics.stationary_bootstrap(len(xf), BOOT_DRAWS, BOOT_BLOCK, BOOT_SEED)
    a, b = xf[idx], xb[idx]
    dce = year * (a.mean(1) - b.mean(1)) - GAMMA / 2 * year * (a.var(1) - b.var(1))
    r = {"ce": ce(xf, year), "ce_base": ce(xb, year), "dd": max_dd(xf), "dd_base": max_dd(xb),
         "sharpe": sharpe(xf, year), "sharpe_base": sharpe(xb, year),
         "cagr": float(np.prod(1 + xf) ** (year / len(xf)) - 1), "cagr_base": float(np.prod(1 + xb) ** (year / len(xb)) - 1),
         "dce_p05": float(np.quantile(dce, 0.05)), "dce_p95": float(np.quantile(dce, 0.95)),
         "dsr_excess": metrics.dsr(xf - xb, pool)}
    r["gates"] = {"1 CE up": bool(r["ce"] > r["ce_base"]), "2 drawdown not worse": bool(r["dd"] <= r["dd_base"]),
                  "3 band above 0": bool(r["dce_p05"] > 0), "4 DSR excess": bool(r["dsr_excess"] >= DSR_PASS)}
    r["pass"] = all(r["gates"].values())
    return r


def coin_books(P: fc.Panel, G: dict, R: dict, model: str) -> dict:
    """breakout_top10 as it runs on Alpaca and its three filtered books: {name: (net daily returns, held)} and the
    hold h (median days of the in-sample entries)."""
    alp = au.alpaca_mask(P)
    top10 = P.top_liquid(10)
    cols = np.flatnonzero(top10.any(0))
    gi = {n: j for j, n in enumerate(G["names"])}
    ti = np.searchsorted(G["days_us"], P.days)
    inside = (ti < len(G["days_us"])) & (G["days_us"][np.minimum(ti, len(G["days_us"]) - 1)] == P.days)

    def onto(X):
        M = np.full((P.T, P.N), np.nan)
        for n, j in gi.items():
            if n in P.names:
                M[inside, P.col(n)] = X[ti[inside], j]
        return M
    f, atr, c = onto(R["f"]["tr"][model]), onto(R["atr20"]), onto(R["c"])
    valid = np.isfinite(onto(G["c"]))
    is_m = (P.days <= dc.us(IS_TO)) & (np.arange(P.T) >= au.START)
    base = au.sim_daily(P, au.cash_left(breakout_gated(P, cols, top10, 20, 10), alp))
    held_on = base[3] > 0
    hold = [ln for j, a, ln in runs(held_on) if alp[j] and is_m[a]]
    h = float(np.median(hold)) if hold else 1.0
    with np.errstate(invalid="ignore"):
        gates = {"good": f * c > atr, "cost": f * math.sqrt(h) >= COST_MULT * COIN_COST,
                 "squeeze": squeeze_flags(f, valid)}
    out = {"base": base}
    for k, g in gates.items():
        g = np.where(alp[None, :], g & np.isfinite(f), True)
        out[k] = au.sim_daily(P, au.cash_left(breakout_gated(P, cols, top10, 20, 10, g), alp))
    return {"books": {k: (au.net(v[0], v[1], COIN_COST), au.net(v[0], v[1], COIN_MAKER), v[3])
                      for k, v in out.items()}, "hold": h, "days": P.days, "alp": alp}


def etf_books(B: ie.Bars, G: dict, R: dict, model: str) -> dict:
    """W4's four long-only picks on SPY, QQQ, IWM, unfiltered and with their filters (the forecast of the previous
    close): {rule: {filter: (daily book returns, entries (S, D))}} and each rule's hold as a share of the session."""
    F = ie.features(B)
    U = ie.universe(B, F)
    cost = ie.cost_per_side(B.syms)
    valid = B.valid.T
    f_prev = shift_next(R["f"]["tr"][model], valid).T
    c_prev, atr_prev = shift_next(R["c"], valid).T, shift_next(R["atr20"], valid).T
    sq_prev = shift_next(squeeze_flags(R["f"]["tr"][model], valid).astype(float), valid).T == 1
    is_m = B.dates <= np.datetime64(IS_TO)
    grid = {v["name"]: v for v in ie.grid()}
    out, holds = {}, {}
    for name in ETF_RULES:
        v = grid[name]
        held = ie.held_from_targets(ie.targets(B, F, v))
        sim = ie.simulate(B, held)
        bars = (held != 0).sum(2)
        per = np.where(sim.entries > 0, bars / np.maximum(sim.entries, 1), np.nan)[:, is_m]
        h = float(np.nanmedian(per) / ie.NB) if np.isfinite(per).any() else 1.0 / ie.NB
        holds[name] = h
        with np.errstate(invalid="ignore"):
            allows = {"good": f_prev * c_prev > atr_prev,
                      "cost": f_prev * math.sqrt(h) >= COST_MULT * cost[:, None]}
        if name.startswith("ORB"):
            allows["squeeze"] = sq_prev
        out[name] = {"base": (ie.book(sim, U, cost), sim.entries)}
        for k, a in allows.items():
            s2 = ie.simulate(B, held, a & np.isfinite(f_prev))
            out[name][k] = (ie.book(s2, U, cost), s2.entries)
    return {"books": out, "holds": holds}


def b_trials(group: str, ins: dict[str, float]) -> list[dict]:
    return [{"id": f"hand:rf1:{k}", "family": "hand", "source": PREREG, "n": 1, "sharpe": s} for k, s in ins.items()]


def a_trials() -> list[dict]:
    return [{"id": f"hand:rf1:fc:{m}:{t}", "family": "hand", "source": PREREG, "n": 1, "sharpe": None}
            for m in MODELS for t in TARGETS]


def part_b(group: str, books: dict, days: np.ndarray, year: int, register: bool, first: str) -> dict:
    """In-sample Sharpes (from `first` to the end of 2023) registered first, then the validation judgement of every
    filtered book."""
    is_m = window_mask(days, first, IS_TO)
    v = window_mask(days, VAL_FROM, VAL_TO)
    ins = {f"{b}:{k}": sharpe(x[is_m], year) for b, fs in books.items() for k, x in fs.items()}
    trials = b_trials(group, ins)
    if register:
        metrics.register(trials)
    pool = metrics.trial_pool(None, extra=trials)
    rows = []
    for b, fs in books.items():
        xb = fs["base"][v]
        for k, x in fs.items():
            if k == "base":
                continue
            r = {"book": b, "filter": k, "is_sharpe": ins[f"{b}:{k}"], "is_sharpe_base": ins[f"{b}:base"],
                 **judge(x[v], xb, year, pool)}
            rows.append(r)
    return {"rows": rows, "trials": [t["id"] for t in trials], "pool": {k: pool[k] for k in ("n_trials", "sr0_annual")}}


def entries_blocked(ent_f: np.ndarray, ent_b: np.ndarray) -> float:
    return float(1 - ent_f.sum() / ent_b.sum()) if ent_b.sum() else float("nan")


def run_b_coins(P: fc.Panel, G: dict, R: dict, model: str, register: bool) -> dict:
    cb = coin_books(P, G, R, model)
    days = P.days.astype("datetime64[us]").astype("datetime64[D]")
    books = {"breakout_top10": {k: v[0] for k, v in cb["books"].items()}}
    res = part_b("coins", books, days, YEAR["coins"], register, str(days[au.START]))
    v = window_mask(days, VAL_FROM, VAL_TO)
    alp = cb["alp"]

    def entries(held):
        on = held[:, alp] > 0
        return (on[1:] & ~on[:-1])[v[1:]]
    eb = entries(cb["books"]["base"][2])
    for r in res["rows"]:
        r["blocked"] = entries_blocked(entries(cb["books"][r["filter"]][2]), eb)
        r["entries_base"] = int(eb.sum())
        r["sharpe_15bps"] = sharpe(cb["books"][r["filter"]][1][v], YEAR["coins"])
    res["hold"] = cb["hold"]
    return res


def run_b_etfs(B: ie.Bars, G: dict, R: dict, model: str, register: bool) -> dict:
    eb = etf_books(B, G, R, model)
    books = {name: {k: v[0] for k, v in fs.items()} for name, fs in eb["books"].items()}
    res = part_b("etfs", books, B.dates.astype("datetime64[D]"), YEAR["etfs"], register, WF_FROM)
    v = window_mask(B.dates.astype("datetime64[D]"), VAL_FROM, VAL_TO)
    for r in res["rows"]:
        fs = eb["books"][r["book"]]
        r["blocked"] = entries_blocked(fs[r["filter"]][1][:, v], fs["base"][1][:, v])
        r["entries_base"] = int(fs["base"][1][:, v].sum())
    res["hold"] = eb["holds"]
    return res


# ---------------------------------------------------------------- report

HEAD = """# RF1: does a forecast of tomorrow's range help the daily books as a filter?

Pre-registered in `results/range_forecast_rf1_prereg.md` (committed before the first run). Code:
`lab.experiments.range_forecast_rf1`, tests `tests/test_range_forecast_rf1.py`. Paper only: nothing a live bot, a
wallet or the engine reads changed.
"""


def _f(v, nd: int = 3) -> str:
    if v is None:
        return "n/a"
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, (int, np.integer)):
        return f"{int(v):,}"
    v = float(v)
    return "n/a" if not math.isfinite(v) else f"{v:.{nd}f}"


def markdown(out: dict) -> str:
    md = [f"Generated {out['generated']}. Data to {VAL_TO} (rows from {LOCKBOX} dropped at load); walk-forward by "
          f"quarter from {WF_FROM[:4]}, validation {VAL_FROM} to {VAL_TO}. Trials: {', '.join(out['trials_a'])}"
          + (f", {', '.join(t for g in out['b'].values() if g for t in g['trials'])}" if out["b"] else "") + ".\n"]
    lo, hi = out["friend_band"]
    md.append(f"The friend's claim, 72 % on 32 days (23 of 32): its 95 % binomial band is {100 * lo:.0f} % to "
              f"{100 * hi:.0f} %.\n")
    lk = out["leak"]
    md.append(f"Leak check (T1's harness on the TR forecasts of BTC and ETH, every value after four cuts shuffled or "
              f"missing, and the data cut): {'no leak' if lk['ok'] else 'LEAK ' + str(lk.get('first') or lk.get('error'))}"
              f" ({lk.get('runs', 0)} runs).\n")
    for g, A in out["a"].items():
        md.append(f"## Part A, {g} ({', '.join(fc.base_of(n) if g == 'coins' else n for n in A['assets'])})\n")
        for t in TARGETS:
            T = A["targets"][t]
            md.append(f"### Target {'true range (judged)' if t == 'tr' else 'high-low range (reported)'}\n")
            cols = ["model", "qlike 2018-2023", "qlike validation", "gain vs RW1 %", "p vs RW1", "gain vs MA20 %",
                    "p vs MA20", "gain vs EWMA %", "p vs EWMA", "acc 2018-2023", "acc validation", "p acc",
                    "good share validation"] + (["pass"] if t == "tr" else [])
            md.append("| " + " | ".join(cols) + " |\n|" + "---|" * len(cols))
            for r in T["rows"] + [T["persistence"]]:
                md.append("| " + " | ".join(_f(r.get(c)) if c != "model" else r["model"] for c in cols) + " |")
            br = T["base_rate"]
            md.append(f"\nRows on validation: {T['rows'][0]['rows validation']:,} asset-days. Good days that happened "
                      f"(TR above the 20-day average): {100 * br['2018-2023']:.1f} % in 2018-2023, "
                      f"{100 * br['validation']:.1f} % on validation, so always saying \"not good\" is right "
                      f"{100 * (1 - br['validation']):.1f} % of the time. p: one-sided DM (Newey-West, {DM_LAGS} lags) "
                      f"on the per-day mean over assets; the bar is {ALPHA:.4f} (0.05 over 6).\n")
            yrs = sorted({y for r in T["rows"] for y in r["by year"]})
            md.append("QLIKE by year:\n\n| model | " + " | ".join(str(y) for y in yrs) + " |\n|---|"
                      + "---|" * len(yrs))
            for r in T["rows"]:
                md.append(f"| {r['model']} | " + " | ".join(_f(r["by year"].get(y)) for y in yrs) + " |")
            w = T["windows32"]
            md.append(f"\nThe friend's test on validation: 32-day windows (non-overlapping, per asset) with 72 % or more "
                      f"right: GARCH {100 * w['GARCH']['share_72']:.0f} % of {w['GARCH']['windows']} (5 % to 95 % of "
                      f"the windows' accuracy {100 * w['GARCH']['p05']:.0f} to {100 * w['GARCH']['p95']:.0f} %), "
                      f"persistence {100 * w['persistence']['share_72']:.0f} % ({100 * w['persistence']['p05']:.0f} to "
                      f"{100 * w['persistence']['p95']:.0f} %), MA20 {100 * w['MA20']['share_72']:.0f} %.\n")
        md.append(f"**Part B forecast for {g}:** {out['chosen'][g] or 'none passes, so no Part B for this group'}.\n")
    for g, B in out["b"].items():
        if not B:
            continue
        md.append(f"## Part B, {g}\n")
        hold = B["hold"]
        md.append("Hold h (median of the unfiltered book's in-sample entries): " + (
            f"{hold:.0f} days" if g == "coins" else ", ".join(f"{k} {100 * v:.1f} % of the session"
                                                              for k, v in hold.items())) + ".\n")
        cols = ["book", "filter", "is_sharpe", "is_sharpe_base", "sharpe", "sharpe_base", "ce", "ce_base", "dd",
                "dd_base", "dce_p05", "dce_p95", "dsr_excess", "blocked", "pass"]
        md.append("| " + " | ".join(cols) + " |\n|" + "---|" * len(cols))
        for r in B["rows"]:
            md.append("| " + " | ".join(_f(r.get(c)) if c not in ("book", "filter") else r[c] for c in cols) + " |")
        md.append(f"\nValidation {VAL_FROM} to {VAL_TO}; CE = annual mean - {GAMMA / 2:g} x annual variance; dce the "
                  f"bootstrap band (5 % to 95 %, block {BOOT_BLOCK}, {BOOT_DRAWS} draws) of the CE gain; blocked: share "
                  f"of the unfiltered book's validation entries the filter removes; DSR over {B['pool']['n_trials']:,}"
                  f" trials (noise bar {B['pool']['sr0_annual']:.2f} a year).\n")
    return "\n".join(md)


# ---------------------------------------------------------------- run

def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    from .. import report
    d = report.REPORTS / NAME
    if "--report" in argv:
        o = json.loads((d / "latest.json").read_text(encoding="utf-8"))
        dc.write_results(NAME, markdown(o), HEAD)
        return 0
    register = "--no-register" not in argv
    t0 = time.time()
    if register:
        metrics.register(a_trials())                      # before any number
    B = load_etf_bars()
    groups = {"coins": coin_group(), "etfs": etf_group(B)}
    print(f"data ready, {time.time() - t0:.0f} s", flush=True)
    lk = leak_check(groups["coins"])
    print(f"leak: {'ok' if lk['ok'] else lk['first'] or lk['error']}", flush=True)
    R, A, pick = {}, {}, {}
    for g, G in groups.items():
        R[g] = group_forecasts(G)
        A[g] = part_a(G, R[g])
        if not lk["ok"]:
            for r in A[g]["targets"]["tr"]["rows"]:
                r["pass"] = False
        pick[g] = chosen(A[g])
        print(f"part A {g}: {time.time() - t0:.0f} s, chosen {pick[g]}", flush=True)
    out_b = {"coins": None, "etfs": None}
    if pick["coins"]:
        P = dc.cut_panel(fc.load_panel(), VAL_TO)
        out_b["coins"] = run_b_coins(P, groups["coins"], R["coins"], pick["coins"], register)
    if pick["etfs"]:
        out_b["etfs"] = run_b_etfs(B, groups["etfs"], R["etfs"], pick["etfs"], register)
    out = {"generated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "a": A, "chosen": pick,
           "b": out_b, "leak": lk, "friend_band": friend_band(), "trials_a": [t["id"] for t in a_trials()],
           "passed": [f"{r['book']}:{r['filter']}" for g in out_b.values() if g for r in g["rows"] if r["pass"]]}
    d.mkdir(parents=True, exist_ok=True)
    (d / "latest.json").write_text(json.dumps(out, indent=1, default=float), encoding="utf-8")
    dc.write_results(NAME, markdown(out), HEAD)
    print(f"done in {time.time() - t0:.0f} s; passed: {out['passed'] or 'none'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
