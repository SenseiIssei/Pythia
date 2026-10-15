"""Daily coin panels for the zoo, from the recorder's 1-minute bars (data.binance.vision history).

One row per (UTC day, coin): everything in a row is known at the end of that
day. Built on vol_daily.coin_daily (realised variance from 1-minute returns,
HAR terms, volume shocks, a calendar frame so "next day" is the next calendar
day), plus returns over more horizons and market-wide columns.
"""

from __future__ import annotations

import numpy as np
import polars as pl

from .core import DAY_US, DataUnavailable

# The coins the Alpaca paper account lists (tsmom_tranches.ALPACA).
ALPACA = ("BTC", "ETH", "SOL", "XRP", "DOGE", "ADA", "AVAX", "LINK", "LTC", "DOT", "BCH", "UNI", "AAVE", "PEPE", "FIL")


def coin_frames(bases, loader=None) -> list[pl.DataFrame]:
    if loader is None:
        from ..experiments.vol_daily import coin_daily as loader
    frames = []
    for b in bases:
        f = loader(b)
        if f is not None and not f.is_empty():
            frames.append(f)
    if not frames:
        raise DataUnavailable("no 1-minute history for any coin under <data>/hist/binance_spot/klines_1m")
    return frames


def enrich(frames: list[pl.DataFrame]) -> pl.DataFrame:
    """Per-coin extra returns and trend, then market and BTC columns by day."""
    out = []
    for f in frames:
        lc = pl.col("close").log()
        out.append(f.sort("day").with_columns(
            ret3=lc - lc.shift(3), ret14=lc - lc.shift(14),
            ma50_gap=lc - pl.col("close").rolling_mean(50, min_samples=40).log(),
            ma200_gap=lc - pl.col("close").rolling_mean(200, min_samples=150).log(),
            ret_next=pl.col("ret").shift(-1),
        ).select(sorted(set(f.columns) | {"ret3", "ret14", "ma50_gap", "ma200_gap", "ret_next"})))
    p = pl.concat(out, how="diagonal_relaxed")
    btc = p.filter(pl.col("symbol") == "BTC").select(
        "day", btc_ret1="ret1", btc_ret7="ret7", btc_h1="h1", btc_h7="h7", btc_trend200="ma200_gap")
    mkt = p.group_by("day").agg(
        mkt_ret1=pl.col("ret1").mean(), mkt_ret7=pl.col("ret7").mean(), mkt_h1=pl.col("h1").mean(),
        mkt_h7=pl.col("h7").mean(), mkt_h30=pl.col("h30").mean(), xs_disp=pl.col("ret1").std(),
        breadth50=(pl.col("ma50_gap") > 0).cast(pl.Float64).mean(), n_coins=pl.col("close").count())
    mkt = mkt.sort("day").with_columns(
        mkt_vol_pct=pl.col("mkt_h30").rolling_map(_last_pct, window_size=365, min_samples=120))
    p = (p.join(btc, on="day", how="left").join(mkt, on="day", how="left")
         .with_columns(rel_ret7=pl.col("ret7") - pl.col("mkt_ret7"), rel_h7=pl.col("h7") - pl.col("mkt_h7"),
                       sigma=pl.col("rw30").sqrt()))
    return p.rename({"day": "ts_us"}).sort(["ts_us", "symbol"])


def _last_pct(s: pl.Series) -> float:
    """Where the last value sits within the window: 0 lowest, 1 highest (the vol regime)."""
    a = s.to_numpy()
    a = a[np.isfinite(a)]
    if a.size < 2:
        return float("nan")
    return float(np.mean(a[:-1] <= a[-1]))


def daily_panel(bases=ALPACA, loader=None) -> pl.DataFrame:
    return enrich(coin_frames(bases, loader))


def synthetic_daily(n_days: int = 1500, bases=("BTC", "ETH", "SOL", "XRP", "ADA"), seed: int = 0,
                    start_us: int = 1_514_764_800_000_000) -> list[pl.DataFrame]:
    """coin_daily-shaped frames from a GARCH-like process with a regime switch, for tests."""
    from ..experiments.vol_daily import _ewma
    rng = np.random.default_rng(seed)
    days = start_us + np.arange(n_days, dtype=np.int64) * DAY_US
    regime = (np.sin(np.arange(n_days) / 120) > 0).astype(float)
    common = rng.standard_normal(n_days)
    frames = []
    for k, b in enumerate(bases):
        var = np.empty(n_days)
        r = np.empty(n_days)
        v = 0.0012
        for t in range(n_days):
            v = 0.00004 + 0.85 * v + 0.1 * (r[t - 1] ** 2 if t else v) + 0.0004 * regime[t]
            var[t] = v
            r[t] = np.sqrt(v) * (0.6 * common[t] + 0.8 * rng.standard_normal())
        rv = var * np.exp(rng.normal(0, 0.4, n_days) - 0.08)
        close = 100 * (k + 1) * np.exp(np.cumsum(r))
        f = pl.DataFrame({"day": days, "close": close, "high": close * np.exp(np.sqrt(rv)),
                          "low": close * np.exp(-np.sqrt(rv)), "rv": rv, "qv": np.exp(rng.normal(15, 0.5, n_days)),
                          "trades": np.exp(rng.normal(9, 0.4, n_days)), "symbol": [b] * n_days})
        lrv = (pl.col("rv") + 1e-12).log()
        lc = pl.col("close").log()
        f = f.with_columns(ret=lc - lc.shift(1)).with_columns(
            y1=pl.col("rv").shift(-1), h1=lrv, h1_l1=lrv.shift(1), h1_l2=lrv.shift(2),
            h7=(pl.col("rv").rolling_mean(7, min_samples=5) + 1e-12).log(),
            h30=(pl.col("rv").rolling_mean(30, min_samples=20) + 1e-12).log(),
            h90=(pl.col("rv").rolling_mean(90, min_samples=60) + 1e-12).log(),
            dn_share7=pl.lit(0.5), jump7=pl.lit(0.2), ret1=pl.col("ret"), ret7=lc - lc.shift(7),
            ret30=lc - lc.shift(30), absret1=pl.col("ret").abs(),
            park1=((pl.col("high") / pl.col("low")).log() ** 2 + 1e-12).log(),
            qv_z=(pl.col("qv") + 1).log() - (pl.col("qv").rolling_mean(30, min_samples=20) + 1).log(),
            tr_z=(pl.col("trades") + 1).log() - (pl.col("trades").rolling_mean(30, min_samples=20) + 1).log(),
            dist_hi30=lc - pl.col("high").rolling_max(30, min_samples=20).log(),
            dow_next=(((pl.col("day") // DAY_US) + 1 + 3) % 7).cast(pl.Float64),
            rw30=pl.col("rv").rolling_mean(30, min_samples=20),
            fund1=pl.lit(None, pl.Float64), fund7=pl.lit(None, pl.Float64),
            oi_chg1=pl.lit(None, pl.Float64), oi_chg7=pl.lit(None, pl.Float64))
        f = f.with_columns(ewma=_ewma(f["ret"].to_numpy() ** 2, 0.94), ewma_rv=_ewma(f["rv"].to_numpy(), 0.94))
        frames.append(f)
    return frames
