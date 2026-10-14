"""Volatility-managed long exposure on the Alpaca coins, and as an overlay on two books (C11).

    python -m lab.experiments.vol_managed            # --refit-m1 rebuilds the M1 forecasts

Pre-registered in results/vol_managed.md (the part above the marker was
committed before this file ran). Each day hold min(1, TV / forecast vol) of
BTC, of ETH, or of each coin of an equal-weight basket of the 15 coins Alpaca
lists, the rest in cash, with a no-trade band and an optional BTC 200-day
gate. Forecasts: the 30-day mean of realised variance (RW30, what the books
use), an EWMA of it, and M1 (vol.py's next-hour LightGBM) rebuilt point in
time and aggregated to a day. Overlays scale breakout_top10 and
tsmom_tranches by their own forecast vol. Judged out of sample from 2024 at
Alpaca taker cost (35 bps per unit of one-way turnover) against buy and hold
and the unscaled books; deflated over the lab's 265 earlier trials and the 91
counted here.

M1 rebuild: vol.py's features on 1m-derived hourly bars of its 20 coins,
pooled; walk-forward by quarter from 2021 with a 24 h embargo; trained on the
rows vol.py trains on, and predicting every hour whose features exist (vol.py
drops hours whose next hour is missing, which needs the future; a forecast
must not). Cached under <agent-strategies>/cache/m1_hourly_oos.parquet.
"""

from __future__ import annotations

import itertools
import math
import sys
from datetime import datetime, timezone

import numpy as np
import polars as pl

from . import fam_breakout
from . import fam_common as fc
from . import tsmom_tranches as tt

NAME = "vol_managed"
ALPACA = tt.ALPACA
IS_START = int(datetime(2021, 1, 1, tzinfo=timezone.utc).timestamp() * 1e6)
COSTS = {"gross": 0.0, "maker 15bps": 0.0015, "taker 35bps": 0.0035}
BASE = "taker 35bps"
ASSETS = ("BTC", "ETH", "basket")
FORECASTS = ("RW30", "EWMA", "M1")
TVS = (0.30, 0.50)
BANDS = (0.10, 0.25)
LAMBDA = 0.94
MIN_OBS = 30
RATIO_DAYS, RATIO_MIN = 365, 60
OVERLAY_BOOKS = ("breakout_top10", "tsmom_tranches")
OVERLAY_FORECASTS = ("RW30", "EWMA")
MAX_SCALE = 2.0
START = 60
YEARS = tuple(range(2021, 2027))
YEARS_OOS = (2024, 2025, 2026)
# fast_strategies' pool: 265 trials, best noise trial at an annual Sharpe of 2.74.
PRIOR_TRIALS, PRIOR_SR0 = 265, 2.74
MARKER = "<!-- generated below by lab.experiments.vol_managed; edit above this line only -->"


# ---------------------------------------------------------------------------
# Forecasts (daily variance of a coin, known at the close of day t)
# ---------------------------------------------------------------------------

def ewma(x: np.ndarray, lam: float = LAMBDA, min_obs: int = MIN_OBS) -> np.ndarray:
    """Column-wise EWMA of x (row t included), seeded at each column's first finite value.

    A missing row leaves the state as it is. NaN until min_obs finite values were seen."""
    out = np.full(x.shape, np.nan)
    cur = np.full(x.shape[1:], np.nan)
    n = np.zeros(x.shape[1:])
    for t in range(x.shape[0]):
        v = x[t]
        ok = np.isfinite(v)
        cur = np.where(ok & np.isnan(cur), v, cur)
        cur = np.where(ok, lam * cur + (1 - lam) * v, cur)
        n = n + ok
        out[t] = np.where(n >= min_obs, cur, np.nan)
    return out


def annual(var_daily: np.ndarray) -> np.ndarray:
    with np.errstate(invalid="ignore"):
        return np.sqrt(var_daily * 365)


def forecast_rw30(P: fc.Panel) -> np.ndarray:
    return annual(P.sigma ** 2)


def forecast_ewma(P: fc.Panel) -> np.ndarray:
    rv = np.where(P.alive, P.extra["rv"], np.nan)
    return annual(ewma(rv))


def m1_daily(h: pl.DataFrame) -> pl.DataFrame:
    """Daily aggregate of M1's hourly forecasts: (symbol, day, m1_var, rv1m).

    m1_var = 24 x the mean of the one-hour-ahead variance forecasts issued at the
    hourly closes of the day (rows whose hour starts in it; the last is issued at
    the day's close). rv1m = the day's 1m realised variance (at least 20 hours)."""
    return (h.with_columns(day=(pl.col("ts_us") // fc.DAY_US) * fc.DAY_US)
            .group_by(["symbol", "day"])
            .agg(m1_var=24 * pl.col("var_fc").mean(), rv1m=pl.col("rv").sum(), n=pl.len())
            .filter(pl.col("n") >= 20).drop("n").sort(["symbol", "day"]))


def scale_ratio(rv_panel: np.ndarray, rv1m: np.ndarray, days: int = RATIO_DAYS, min_obs: int = RATIO_MIN) -> np.ndarray:
    """Mean hourly-return RV over mean 1m RV, over the `days` up to and including t, both present."""
    both = np.isfinite(rv_panel) & np.isfinite(rv1m)
    a = fc.rolling(np.where(both, rv_panel, np.nan), days, min_obs)
    b = fc.rolling(np.where(both, rv1m, np.nan), days, min_obs)
    with np.errstate(invalid="ignore", divide="ignore"):
        return a / b


def forecast_m1(P: fc.Panel, daily: pl.DataFrame) -> np.ndarray:
    """M1's daily aggregate on the panel, rescaled to the panel's RV, annualised. NaN where M1 has none."""
    di = {int(d): i for i, d in enumerate(P.days)}
    m1 = np.full((P.T, P.N), np.nan)
    rv1 = np.full((P.T, P.N), np.nan)
    for (sym,), g in daily.group_by(["symbol"]):
        name = f"{sym}USDT" if not str(sym).endswith("USDT") else str(sym)
        if name not in P.names:
            continue
        j = P.col(name)
        for d, v, r in zip(g["day"].to_numpy(), g["m1_var"].to_numpy(), g["rv1m"].to_numpy()):
            t = di.get(int(d))
            if t is not None and P.alive[t, j]:
                m1[t, j], rv1[t, j] = v, r
    ratio = scale_ratio(np.where(P.alive, P.extra["rv"], np.nan), rv1)
    return annual(m1 * ratio)


def build_m1(refit: bool = False) -> tuple[pl.DataFrame, dict]:
    """Walk-forward out-of-sample hourly M1 (and HAR) forecasts for vol.py's 20 coins."""
    import json

    import lightgbm as lgb

    from ..cv import walk_forward
    from ..data import UNIVERSE, hourly
    from ..metrics import qlike
    from . import vol

    cache = fc.OUT / "cache" / "m1_hourly_oos.parquet"
    meta = cache.with_suffix(".json")
    if cache.exists() and meta.exists() and not refit:
        return pl.read_parquet(cache), json.loads(meta.read_text(encoding="utf-8"))
    frames = {}
    for b in UNIVERSE:
        h = hourly(f"{b}USDT")
        if h.is_empty():
            continue
        frames[b] = vol.features(h)
        print(f"  m1 {b}: {h.height} hours", flush=True)
    btc = frames["BTC"].select("ts_us", btc_har1="har1", btc_har24="har24", btc_ret="ret")
    panel = (pl.concat([f.join(btc, on="ts_us", how="left").with_columns(rel_har1=pl.col("har1") - pl.col("btc_har1"))
                        for f in frames.values()], how="vertical_relaxed")
             .drop_nulls(vol.FEATURES).sort("ts_us"))
    trainable = (panel["y_contiguous"].fill_null(False) & (panel["rv"] > 0) & (panel["y_var"].fill_null(0) > 0)
                 & panel["y"].is_not_null()).to_numpy()
    ts = panel["ts_us"].to_numpy()
    X = panel.select(vol.FEATURES).to_numpy().astype(np.float32)
    Xh = panel.select(vol.HAR_COLS).to_numpy()
    y = panel["y"].fill_null(np.nan).to_numpy()
    yvar = panel["y_var"].fill_null(np.nan).to_numpy()
    fc_l, fc_h = np.full(len(ts), np.nan), np.full(len(ts), np.nan)
    folds = []
    for fold in walk_forward(ts, vol.FIRST_TEST):
        tr = fold.train & trainable
        te = fold.test
        m = lgb.LGBMRegressor(**vol.LGBM_PARAMS).fit(X[tr], y[tr])
        rv_l = float(np.var(y[tr] - m.predict(X[tr])))
        fc_l[te] = np.exp(m.predict(X[te]) + rv_l / 2)
        beta = vol.ols(Xh[tr], y[tr])
        rv_h = float(np.var(y[tr] - vol.ols_pred(beta, Xh[tr])))
        fc_h[te] = np.exp(vol.ols_pred(beta, Xh[te]) + rv_h / 2)
        sc = te & trainable
        ql, qh = float(np.mean(qlike(yvar[sc], fc_l[sc]))), float(np.mean(qlike(yvar[sc], fc_h[sc])))
        folds.append({"fold": fold.name, "rows": int(sc.sum()), "qlike_m1": ql, "qlike_har": qh})
        print(f"  m1 {fold.name}: qlike har {qh:.4f} m1 {ql:.4f}", flush=True)
    ok = np.isfinite(fc_l) & trainable
    q_l, q_h = qlike(yvar[ok], fc_l[ok]), qlike(yvar[ok], fc_h[ok])
    from ..metrics import diebold_mariano
    _, dm_p = diebold_mariano(q_l, q_h)
    info = {"rows_scored": int(ok.sum()), "qlike_m1": float(q_l.mean()), "qlike_har": float(q_h.mean()),
            "gain_vs_har": float(1 - q_l.mean() / q_h.mean()), "dm_p": float(dm_p), "folds": folds,
            "coins": sorted(frames)}
    info["reproduced"] = bool(info["gain_vs_har"] > 0)
    out = pl.DataFrame({"ts_us": ts, "symbol": panel["symbol"].to_numpy(), "rv": panel["rv"].to_numpy(),
                        "var_fc": fc_l, "har_fc": fc_h}).filter(pl.col("var_fc").is_not_nan())
    cache.parent.mkdir(parents=True, exist_ok=True)
    out.write_parquet(cache)
    meta.write_text(json.dumps(info, indent=1), encoding="utf-8")
    return out, info


# ---------------------------------------------------------------------------
# Books
# ---------------------------------------------------------------------------

def simulate(P: fc.Panel, W: np.ndarray, band: float, start: int = START, lag: int = 0):
    """Long-only book holding full target rows W (T, N) from the close of day t, with tt's no-trade band.

    Returns (gross, turnover, exposure): the return earned on day t, the one-way
    turnover traded at the close of t (charged on t+1), the exposure after it.
    `lag` days late: the target decided at the close of t is traded at the close of t + lag."""
    T, N = W.shape
    if lag:
        W = np.vstack([np.zeros((lag, N)), W[:-lag]])
    w = np.zeros(N)
    gross, tov, expo = np.zeros(T), np.zeros(T), np.zeros(T)
    for t in range(start, T - 1):
        tgt = np.nan_to_num(W[t])
        tgt = np.where(P.traded[t] | (tgt == w), tgt, w)
        tgt = tt.band_target(w, tgt, band)
        tov[t] += np.abs(tgt - w).sum()
        w = tgt
        expo[t] = w.sum()
        r = np.nan_to_num(P.ret[t + 1])
        g = float(w @ r)
        gross[t + 1] = g
        w = w * (1 + r) / (1 + g) if 1 + g > 0 else np.zeros(N)
        dead = (w != 0) & ~P.alive[t + 1]
        if dead.any():
            tov[t + 1] += np.abs(w[dead]).sum()
            w[dead] = 0.0
    return gross, tov, expo


def alpaca_cols(P: fc.Panel) -> np.ndarray:
    return np.array([b in ALPACA and "~" not in n for b, n in zip(P.bases, P.names)])


def members(P: fc.Panel, asset: str, twin: bool = False) -> np.ndarray:
    """Bool (T, N): which coins the asset holds on day t (eligible on the panel's rule)."""
    m = np.zeros((P.T, P.N), dtype=bool)
    if asset in ("BTC", "ETH"):
        j = P.col(f"{asset}USDT")
        m[:, j] = P.alive[:, j] & P.traded[:, j]
        return m
    if twin:
        return P.top_liquid(len(ALPACA))
    return P.eligible & alpaca_cols(P)[None, :]


def managed_weights(P: fc.Panel, mem: np.ndarray, vol: np.ndarray, tv: float, gate: bool) -> np.ndarray:
    """(1 / n_t) x min(1, tv / vol) per member coin; a member without a forecast is held at zero."""
    n = mem.sum(1, keepdims=True)
    with np.errstate(invalid="ignore", divide="ignore"):
        e = np.where(mem & np.isfinite(vol) & (vol > 0), np.minimum(1.0, tv / vol), 0.0)
    W = e / np.maximum(n, 1)
    if gate:
        W = W * P.btc_on[:, None]
    return W


def hold_weights(P: fc.Panel, mem: np.ndarray, gate: bool = False) -> np.ndarray:
    """Equal weight among members, back to equal weight on the 1st of each month and when
    membership (or the gate) changes; drifts otherwise (NaN rows for fam_common.simulate)."""
    on = P.btc_on if gate else np.ones(P.T, dtype=bool)
    mem = mem & on[:, None]
    month = np.array([str(np.datetime64(int(d), "us").astype("datetime64[D]"))[8:] == "01" for d in P.days])
    change = np.r_[True, (mem[1:] != mem[:-1]).any(1)]
    W = np.full((P.T, P.N), np.nan)
    reb = month | change
    W[reb] = fc.equal_weight(mem[reb])
    return W


def run_hold(P: fc.Panel, mem: np.ndarray, gate: bool = False, lag: int = 0):
    W = hold_weights(P, mem, gate)
    if lag:
        W = np.vstack([np.zeros((lag, P.N)), W[:-lag]])
    g, tv, le, _ = fc.simulate(P, W, start=START)
    return g, tv, le


# ---------------------------------------------------------------------------
# Overlays
# ---------------------------------------------------------------------------

def book_forecast(g: np.ndarray, how: str, start: int) -> np.ndarray:
    """Annual vol of a book's daily returns known at the close of t (row t included)."""
    x = np.where(np.arange(len(g)) > start, g, np.nan)[:, None] ** 2
    if how == "RW30":
        v = fc.rolling(x, 30, 24)[:, 0]
    else:
        v = ewma(x)[:, 0]
    return annual(v)


def overlay_scale(f: np.ndarray, expo: np.ndarray, c: float, band: float) -> np.ndarray:
    """s_t = min(2, 1 / exposure_t, c / f_t), moved only when |new - s| > band x new. 1 until f exists."""
    T = len(f)
    S = np.ones(T)
    s = 1.0
    with np.errstate(invalid="ignore", divide="ignore"):
        cap = np.where(expo > 1e-9, 1.0 / np.maximum(expo, 1e-9), np.inf)
        raw = np.where(np.isfinite(f) & (f > 0), np.minimum(np.minimum(MAX_SCALE, cap), c / f), np.nan)
    for t in range(T):
        new = raw[t]
        if np.isfinite(new):
            new = float(min(new, cap[t]))
            if abs(new - s) > band * new or s > cap[t] + 1e-12:
                s = new
        S[t] = s
    return S


def run_overlay(g: np.ndarray, tov: np.ndarray, expo: np.ndarray, how: str, band: float, ins: np.ndarray,
                start: int, lag: int = 0):
    f = book_forecast(g, how, start)
    c = float(np.nanmedian(f[ins & np.isfinite(f)]))
    S = overlay_scale(f, expo, c, band)
    if lag:
        S = np.r_[np.ones(lag), S[:-lag]]
    go = np.zeros_like(g)
    go[1:] = S[:-1] * g[1:]
    tv = S * tov + np.abs(np.diff(np.r_[1.0, S])) * expo
    return go, tv, S * expo, c


def books(P: fc.Panel, alpaca_only: bool = False, lag: int = 0) -> dict:
    """(gross, turnover, exposure) of breakout_top10, tsmom_top20 (daily) and tsmom_tranches."""
    alp = alpaca_cols(P)
    top10 = P.top_liquid(10)
    ever = np.flatnonzero(top10.any(0))
    Wb = fam_breakout.breakout_weights(P, ever, top10, 20, 10, False)
    Wt = tt.targets(P)
    if alpaca_only:
        Wb = np.where(alp[None, :], Wb, 0.0)
        Wt = np.where(alp[None, :], Wt, 0.0)
    if lag:
        Wb = np.vstack([np.zeros((lag, P.N)), Wb[:-lag]])
        Wt = np.vstack([np.zeros((lag, P.N)), Wt[:-lag]])
    out = {}
    g, tv, le, _ = fc.simulate(P, Wb, start=START)
    out["breakout_top10"] = (g, tv, le)
    if not alpaca_only and not lag:
        g, tv, le, _ = fc.simulate(P, Wt, start=START)
        out["tsmom_top20"] = (g, tv, le)
    g, tv, ex, _, _, _ = tt.simulate(P, Wt)
    out["tsmom_tranches"] = (g, tv, ex)
    return out


# ---------------------------------------------------------------------------
# Measuring
# ---------------------------------------------------------------------------

def windows(P: fc.Panel) -> tuple[np.ndarray, np.ndarray]:
    return (P.days >= IS_START) & (P.days < fc.SPLIT), P.days >= fc.SPLIT


def net(g: np.ndarray, tv: np.ndarray, c: float) -> np.ndarray:
    return g - c * np.r_[0.0, tv[:-1]]


def describe(P: fc.Panel, name: str, g: np.ndarray, tv: np.ndarray, ex: np.ndarray, **tags) -> dict:
    ins, oos = windows(P)
    yr = np.array([int(str(np.datetime64(int(d), "us").astype("datetime64[Y]"))) for d in P.days])
    row: dict = {"variant": name, **tags}
    for k, c in COSTS.items():
        x = net(g, tv, c)
        row[f"is_{k}"] = fc.perf(x[ins])["sharpe"]
        row[f"oos_{k}"] = fc.perf(x[oos])["sharpe"]
    x = net(g, tv, COSTS[BASE])
    po = fc.perf(x[oos])
    row.update(cagr_35=po["cagr"], dd_35=po["max_dd"], vol_35=po["vol"])
    row["turnover_yr"] = float(tv[oos].sum() / (oos.sum() / 365))
    row["expo"] = float(ex[oos].mean())
    for y in YEARS:
        row[f"y{y}"] = fc.perf(x[(yr == y) & (P.days >= IS_START)])["sharpe"]
    row["years_pos"] = int(sum(row[f"y{y}"] > 0 for y in YEARS_OOS))
    on_prev = np.r_[False, P.btc_on[:-1]]
    row["oos_btc_above"] = fc.perf(x[oos & on_prev])["sharpe"]
    row["oos_btc_below"] = fc.perf(x[oos & ~on_prev])["sharpe"]
    return row


def prior_var() -> float:
    g = 0.5772156649
    from scipy import stats
    z = (1 - g) * stats.norm.ppf(1 - 1 / PRIOR_TRIALS) + g * stats.norm.ppf(1 - 1 / (PRIOR_TRIALS * math.e))
    return (PRIOR_SR0 / math.sqrt(365) / z) ** 2


def pooled_var(mine: list[float], prior_mean_annual: float) -> tuple[float, dict]:
    """fast_strategies.pooled_var with fast_strategies' pool of 265 as the prior."""
    n1, v1, m1 = PRIOR_TRIALS, prior_var(), prior_mean_annual / math.sqrt(365)
    x = np.clip(np.array(mine), -fc.SR_CLIP, fc.SR_CLIP) / math.sqrt(365)
    n2, v2, m2 = len(x), float(np.var(x)), float(np.mean(x))
    n = n1 + n2
    v = (n1 * v1 + n2 * v2 + n1 * n2 / n * (m1 - m2) ** 2) / n
    return v, {"prior_trials": n1, "prior_mean_annual": prior_mean_annual, "mine": n2,
               "mine_mean_annual": m2 * math.sqrt(365), "pooled_var": v, "n_total": n,
               "sr0_annual": fc._sr0(v, n) * math.sqrt(365)}


def sharpe_stats(x: np.ndarray) -> tuple[float, float, float]:
    from scipy import stats
    sd = x.std()
    if sd == 0:
        return 0.0, 0.0, 3.0
    return float(x.mean() / sd), float(stats.skew(x)), float(stats.kurtosis(x, fisher=False))


def label(asset: str, fcast: str, tv: float, band: float, gate: bool) -> str:
    return f"{asset} · {fcast} · TV {tv * 100:.0f} % · band {band * 100:.0f} %" + (" · BTC gate" if gate else "")


def forecast_quality(P: fc.Panel, F: dict[str, np.ndarray]) -> list[dict]:
    """QLIKE of each forecast against the next day's RV, Alpaca coins, in and out of sample."""
    from ..metrics import qlike
    ins, oos = windows(P)
    alp = alpaca_cols(P)
    nxt = np.full((P.T, P.N), np.nan)
    nxt[:-1] = np.where(P.alive[1:], P.extra["rv"][1:], np.nan)
    v = {k: f ** 2 / 365 for k, f in F.items()}
    ok = np.isfinite(nxt) & (nxt > 0) & alp[None, :] & P.alive
    for f in v.values():
        ok &= np.isfinite(f) & (f > 0)
    out = []
    for name, m in (("in sample", ins), ("out of sample", oos)):
        mm = ok & m[:, None]
        base = None
        for k, f in v.items():
            q = float(np.mean(qlike(nxt[mm], f[mm])))
            base = q if base is None else base
            out.append({"window": name, "forecast": k, "coin_days": int(mm.sum()), "qlike": q,
                        "gain_vs_rw30_pct": 100 * (1 - q / base)})
    return out


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    P = fc.load_panel()
    ins, oos = windows(P)
    h, m1info = build_m1("--refit-m1" in sys.argv)
    F = {"RW30": forecast_rw30(P), "EWMA": forecast_ewma(P)}
    if m1info["reproduced"]:
        F["M1"] = forecast_m1(P, m1_daily(h))
    else:   # the registered fallback: HAR on daily RV is not built unless M1 fails
        raise SystemExit("M1 not reproduced; the registered HAR-RV fallback is not implemented")
    res: dict = {"panel_end": str(np.datetime64(int(P.days[-1]), "us").astype("datetime64[D]")),
                 "segments": P.N, "m1": m1info, "forecast_quality": forecast_quality(P, F)}
    trials: list[tuple[str, np.ndarray]] = []
    rows, runs = [], {}

    # References: buy and hold, and the existing books.
    refs = {}
    for a in ASSETS:
        g, tv, ex = run_hold(P, members(P, a))
        refs[a] = describe(P, f"{a} · buy and hold", g, tv, ex, asset=a, kind="reference")
    bk = books(P)
    for k, (g, tv, ex) in bk.items():
        refs[k] = describe(P, k, g, tv, ex, asset=k, kind="reference")
    res["references"] = list(refs.values())

    # The grid.
    for a, fk, tv_, band, gate in itertools.product(ASSETS, FORECASTS, TVS, BANDS, (False, True)):
        mem = members(P, a)
        W = managed_weights(P, mem, F[fk], tv_, gate)
        g, tv, ex = simulate(P, W, band)
        name = label(a, fk, tv_, band, gate)
        row = describe(P, name, g, tv, ex, asset=a, forecast=fk, target_vol=tv_, band=band, gate=gate, kind="grid")
        rows.append(row)
        runs[name] = (g, tv, ex)
        trials.append((name, net(g, tv, COSTS[BASE])[oos]))
    gate_rows = []
    for a in ASSETS:
        g, tv, ex = run_hold(P, members(P, a), gate=True)
        name = f"{a} · gate only"
        gate_rows.append(describe(P, name, g, tv, ex, asset=a, kind="gate only"))
        trials.append((name, net(g, tv, COSTS[BASE])[oos]))

    # Overlays.
    ov_rows = []
    for b, fk, band in itertools.product(OVERLAY_BOOKS, OVERLAY_FORECASTS, BANDS):
        g0, tv0, ex0 = bk[b]
        g, tv, ex, c = run_overlay(g0, tv0, ex0, fk, band, ins, START)
        name = f"{b} · overlay {fk} · band {band * 100:.0f} %"
        row = describe(P, name, g, tv, ex, asset=b, forecast=fk, band=band, kind="overlay", c=c)
        ov_rows.append(row)
        runs[name] = (g, tv, ex)
        trials.append((name, net(g, tv, COSTS[BASE])[oos]))

    # Picks and their checks.
    picks = []
    bk_late = books(P, lag=1)
    bk_alp = books(P, alpaca_only=True)
    for a in ASSETS:
        pick = max([r for r in rows if r["asset"] == a], key=lambda r: r[f"is_{BASE}"])
        W = managed_weights(P, members(P, a), F[pick["forecast"]], pick["target_vol"], pick["gate"])
        g, tv, ex = simulate(P, W, pick["band"], lag=1)
        late = describe(P, pick["variant"] + " · filled one day late", g, tv, ex, kind="check")
        trials.append((late["variant"], net(g, tv, COSTS[BASE])[oos]))
        twin = None
        if a == "basket":
            vol = F[pick["forecast"]]
            note = ""
            if pick["forecast"] == "M1":   # M1 exists for its 20 coins only: RW30 elsewhere
                vol = np.where(np.isfinite(vol), vol, F["RW30"])
                note = " (RW30 where M1 has no forecast)"
            W = managed_weights(P, members(P, a, twin=True), vol, pick["target_vol"], pick["gate"])
            g, tv, ex = simulate(P, W, pick["band"])
            twin = describe(P, pick["variant"] + " · survivorship-free top 15" + note, g, tv, ex, kind="check")
            trials.append((twin["variant"], net(g, tv, COSTS[BASE])[oos]))
        picks.append({"pick": pick, "late": late, "twin": twin, "ref": refs[a]})
    for b in OVERLAY_BOOKS:
        pick = max([r for r in ov_rows if r["asset"] == b], key=lambda r: r[f"is_{BASE}"])
        g, tv, ex, _ = run_overlay(*bk_late[b], pick["forecast"], pick["band"], ins, START, lag=1)
        late = describe(P, pick["variant"] + " · filled one day late", g, tv, ex, kind="check")
        trials.append((late["variant"], net(g, tv, COSTS[BASE])[oos]))
        g, tv, ex, _ = run_overlay(*bk_alp[b], pick["forecast"], pick["band"], ins, START)
        twin = describe(P, pick["variant"] + " · Alpaca coins only", g, tv, ex, kind="check")
        trials.append((twin["variant"], net(g, tv, COSTS[BASE])[oos]))
        ga, tva, exa = bk_alp[b]
        twin["unscaled_oos_35"] = describe(P, b, ga, tva, exa)[f"oos_{BASE}"]
        picks.append({"pick": pick, "late": late, "twin": twin, "ref": refs[b]})

    from .fast_strategies import prior_mean_sharpe
    from ..metrics import deflated_sharpe
    var, pool = pooled_var([sharpe_stats(x)[0] * math.sqrt(365) for _, x in trials], prior_mean_sharpe())
    res["pool"] = pool
    res["n_trials_here"] = len(trials)
    res["trials"] = [n for n, _ in trials]
    rng = np.random.default_rng(20261014)
    judged = []
    for pk in picks:
        row, ref = pk["pick"], pk["ref"]
        g, tv, _ = runs[row["variant"]]
        x = net(g, tv, COSTS[BASE])[oos]
        s, sk, ku = sharpe_stats(x)
        p = deflated_sharpe(s, len(x), pool["n_total"], var, sk, ku)
        lo, hi = tt.boot_band(x, rng)
        why = []
        if row[f"oos_{BASE}"] <= 0:
            why.append(f"Sharpe at 35 bps {row[f'oos_{BASE}']:.2f} <= 0")
        if row[f"oos_{BASE}"] <= ref[f"oos_{BASE}"]:
            why.append(f"Sharpe below its reference ({row[f'oos_{BASE}']:.2f} vs {ref[f'oos_{BASE}']:.2f})")
        if row["kind"] == "grid" and row["dd_35"] >= ref["dd_35"]:
            why.append(f"drawdown not below buy and hold ({row['dd_35'] * 100:.0f} vs {ref['dd_35'] * 100:.0f} %)")
        if p <= 0.95:
            why.append(f"deflated p {p:.2f} <= 0.95")
        if pk["twin"] is not None and pk["twin"][f"oos_{BASE}"] <= 0:
            why.append(f"twin {pk['twin'][f'oos_{BASE}']:.2f}")
        if row["years_pos"] < 2:
            why.append(f"positive in {row['years_pos']} of 3 years")
        judged.append({**row, "ref_oos_35": ref[f"oos_{BASE}"], "ref_dd_35": ref["dd_35"], "deflated_p": p,
                       "boot35_p05": lo, "boot35_p95": hi,
                       "twin_oos_35": pk["twin"][f"oos_{BASE}"] if pk["twin"] else float("nan"),
                       "late_oos_35": pk["late"][f"oos_{BASE}"], "passes": not why,
                       "verdict": "passes" if not why else "fails: " + "; ".join(why)})
    res["judged"] = judged
    res["checks"] = [pk["late"] for pk in picks] + [pk["twin"] for pk in picks if pk["twin"]]
    res["grid"] = rows
    res["gate_only"] = gate_rows
    res["overlays"] = ov_rows
    res["beats_hold"] = beats_hold(rows, refs)
    write(res)


def beats_hold(rows: list[dict], refs: dict) -> list[dict]:
    out = []
    for a, fk in itertools.product(ASSETS, FORECASTS):
        r = [x for x in rows if x["asset"] == a and x["forecast"] == fk]
        ref = refs[a]
        out.append({"asset": a, "forecast": fk, "variants": len(r),
                    "beat_sharpe": sum(x[f"oos_{BASE}"] > ref[f"oos_{BASE}"] for x in r),
                    "beat_dd": sum(x["dd_35"] < ref["dd_35"] for x in r),
                    "median_oos_35": float(np.median([x[f"oos_{BASE}"] for x in r])),
                    "hold_oos_35": ref[f"oos_{BASE}"],
                    "median_is_35": float(np.median([x[f"is_{BASE}"] for x in r])),
                    "hold_is_35": ref[f"is_{BASE}"]})
    return out


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def write(res: dict) -> None:
    import json
    path = fc.RESULTS_DIR / f"{NAME}.md"
    pre = path.read_text(encoding="utf-8").split(MARKER)[0] + MARKER + "\n"
    pool, m1 = res["pool"], res["m1"]
    cols = ["variant", f"is_{BASE}", "oos_gross", "oos_maker 15bps", f"oos_{BASE}", "cagr_35", "dd_35", "vol_35",
            "turnover_yr", "expo"]
    years = ["variant"] + [f"y{y}" for y in YEARS] + ["oos_btc_above", "oos_btc_below"]
    jc = ["variant", f"oos_{BASE}", "ref_oos_35", "dd_35", "ref_dd_35", "y2024", "y2025", "y2026", "deflated_p",
          "boot35_p05", "boot35_p95", "twin_oos_35", "late_oos_35", "verdict"]
    passed = [r for r in res["judged"] if r["passes"]]
    md = [pre, f"\n## Results (generated {datetime.now(timezone.utc):%Y-%m-%d}, data to {res['panel_end']})\n\n",
          f"**Verdict: {'a variant passes' if passed else 'nothing passes'}.** Deflation pool {pool['n_total']} "
          f"trials (prior {pool['prior_trials']}, here {res['n_trials_here']}); the best noise trial is expected "
          f"at an annual Sharpe of about {pool['sr0_annual']:.2f}.\n\n",
          f"M1 rebuilt on {len(m1['coins'])} coins: walk-forward QLIKE {m1['qlike_m1']:.4f} against HAR "
          f"{m1['qlike_har']:.4f} ({m1['gain_vs_har'] * 100:.1f} % better, DM p {m1['dm_p']:.2g}, "
          f"{m1['rows_scored']:,} coin-hours): {'reproduced' if m1['reproduced'] else 'not reproduced'}.\n\n",
          "### The picks, judged against the pass rule\n\nPer asset and overlay book, the best in-sample Sharpe at "
          "35 bps. `ref` is buy and hold of the same asset (asset books) or the unscaled book (overlays); "
          "`twin_oos_35` the basket's survivorship-free twin or the overlay's Alpaca-only book.\n\n",
          fc.table(res["judged"], jc),
          "\n### References at the same costs\n\n", fc.table(res["references"], cols),
          "\n### How often vol management beats buy and hold (out of sample, 35 bps)\n\n",
          fc.table(res["beats_hold"], ["asset", "forecast", "variants", "beat_sharpe", "beat_dd", "median_is_35",
                                       "hold_is_35", "median_oos_35", "hold_oos_35"]),
          "\n### Forecast quality: QLIKE against the next day's RV, Alpaca coins\n\n",
          fc.table(res["forecast_quality"], ["window", "forecast", "coin_days", "qlike", "gain_vs_rw30_pct"])]
    for a in ASSETS:
        r = [x for x in res["grid"] if x["asset"] == a]
        md.append(f"\n### All {a} variants\n\n" + fc.table(r, cols))
    md.append("\n### Gate only and overlays\n\n" + fc.table(res["gate_only"] + res["overlays"], cols))
    md.append("\n### Checks on the picks\n\n" + fc.table(res["checks"], cols))
    md.append("\n### Per year (Sharpe at 35 bps) and by BTC regime: picks, references, checks\n\n"
              + fc.table(res["judged"] + res["references"] + res["checks"], years))
    md.append("\n### M1 rebuild per quarter (QLIKE, next hour)\n\n"
              + fc.table(m1["folds"], ["fold", "rows", "qlike_har", "qlike_m1"]))
    md.append(f"\n### Deflation pool\n\nPrior: fast_strategies' {pool['prior_trials']} trials, variance backed out "
              f"of its bar ({PRIOR_SR0}), mean {pool['prior_mean_annual']:.2f} (the sweep's 100). Here: "
              f"{pool['mine']} trials at 35 bps, mean {pool['mine_mean_annual']:.2f}, clipped at +-3. Pooled: bar "
              f"{pool['sr0_annual']:.2f} over {pool['n_total']}.\n\nTrials counted here: "
              + "; ".join(res["trials"]) + ".\n")
    path.write_text("".join(md), encoding="utf-8")
    d = fc.OUT / "reports"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{NAME}.json").write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")


if __name__ == "__main__":
    main()
