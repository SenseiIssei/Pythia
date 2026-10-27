"""Features from the lab's other files: Binance's archives (long history) and the daily flow series.

  funding   hist/binance_um/funding: every settled funding rate of every USDT perpetual (from 2020), put on
            8 hours (rate * 8 / interval); known at its settlement. Hourly: the last settled rate; daily: the
            sum of the day's settlements (as the sweep's panel counts funding).
  oi        hist/binance_um/metrics (5-minute open interest of the 20 lab coins from 2022), the last value of
            each hour; hours the archive does not have yet (the newest days) from the recorder's 60 s open
            interest. Both count contracts, so a change is the same measure on either side of the seam.
  flow      lab.collect.flow's files (PYTHIA_FLOW, default <data>/flow): Deribit's BTC DVOL (daily candle,
            known an hour after its close), the 25-delta risk reversal at 30 days (snapshots, known at their
            time), DefiLlama's stablecoin supply (a day's value known an hour after the day), the Coinbase
            premium (Coinbase BTC-USD 1h close over Binance BTCUSDT's, known at the bar's close).
  D2        series a later collector may write next to them, used when the file is there and empty
            otherwise (every reader returns no rows without its file):
              fear_greed.parquet          day_us, value            (index of the day, known 1 h after it)
              hyperliquid_funding.parquet ts_us, asset, funding    (hourly funding, known at ts_us)
              macro.parquet               day_us, series, value    (dxy, us10y, spx, vix closes; known 1 day
                                                                    after the day: closes come out late)
              events.parquet              ts_us, [known_us]        (scheduled releases; known 7 days ahead
                                                                    without known_us)
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import polars as pl

from ..data import UNIVERSE, perp_symbol
from . import registry as R
from . import store

HOUR, DAY = R.HOUR, R.DAY
MACRO = ("dxy", "us10y", "spx", "vix")
EVENT_NOTICE = 7 * DAY


def flow_dir() -> Path:
    return Path(os.environ.get("PYTHIA_FLOW") or store.ROOT / "flow")


def _read(path: Path) -> pl.DataFrame:
    try:
        return pl.read_parquet(path) if path.exists() else pl.DataFrame()
    except (OSError, pl.exceptions.PolarsError):
        return pl.DataFrame()


def _hist(kind: str, symbol: str) -> pl.DataFrame:
    d = store.ROOT / "hist" / "binance_um" / kind / f"symbol={symbol}"
    files = sorted(d.glob("*.parquet"))
    return pl.concat([pl.read_parquet(f) for f in files], how="vertical_relaxed") if files else pl.DataFrame()


def _none() -> pl.DataFrame:
    return pl.DataFrame(schema={"ts_us": pl.Int64, "asset": pl.String, "end_us": pl.Int64})


def _symbols(kind: str, assets) -> dict[str, str]:
    """symbol -> asset of the archive folders, only the assets asked for (all when None)."""
    d = store.ROOT / "hist" / "binance_um" / kind
    syms = sorted(p.name.removeprefix("symbol=") for p in d.glob("symbol=*")) if d.is_dir() else []
    out = {}
    for s in syms:
        if not s.endswith("USDT"):
            continue
        a = pl.DataFrame({"symbol": [s]}).select(pl.col("symbol").str.replace(r"USDT$", "")
                                                  .str.replace(r"^(1000000|10000|1000)([A-Z])", "${2}")).item()
        if assets is None or a in assets:
            out[s] = a
    return out


# ---------------------------------------------------------------- Binance archives

def funding_table(freq: str, assets) -> pl.DataFrame:
    rows = []
    for s, a in _symbols("funding", assets).items():
        f = _hist("funding", s)
        if f.height:
            rows.append(f.select("funding_time_us", "interval_hours", "funding_rate").with_columns(asset=pl.lit(a)))
    if not rows:
        return _none()
    f = (pl.concat(rows, how="vertical_relaxed").unique(["asset", "funding_time_us"], keep="last")
         .sort("asset", "funding_time_us")
         .with_columns(f8=pl.col("funding_rate") * 8 / pl.col("interval_hours").fill_null(8).clip(1, 24)))
    if freq == "1h":
        return f.select(ts_us=pl.col("funding_time_us"), asset="asset", end_us=pl.col("funding_time_us"), f8="f8")
    return (f.with_columns(ts_us=((pl.col("funding_time_us") - 1) // DAY) * DAY)
            .group_by("asset", "ts_us").agg(pl.col("funding_rate").sum().alias("f8"))   # the day's sum, as paid
            .with_columns(end_us=pl.col("ts_us") + DAY))


def oi_table(freq: str, assets) -> pl.DataFrame:
    rows = []
    for a in (UNIVERSE if assets is None else [x for x in assets if x in UNIVERSE]):
        m = _hist("metrics", perp_symbol(a))
        if m.height:
            rows.append(m.select("ts_us", oi="sum_open_interest").with_columns(asset=pl.lit(a)))
    h = (pl.concat(rows, how="vertical_relaxed").sort("ts_us")
         .with_columns(ts_us=(pl.col("ts_us") // HOUR) * HOUR)
         .group_by("asset", "ts_us").agg(pl.col("oi").drop_nulls().last())) if rows else None
    live = R.table("perp", "1h", assets)
    if live.height and "oi" in live.columns:
        live = live.select("asset", "ts_us", "oi").drop_nulls("oi")
        h = live if h is None else pl.concat([h, live.join(h, on=["asset", "ts_us"], how="anti")],
                                             how="vertical_relaxed")
    if h is None or not h.height:
        return _none()
    h = h.sort("asset", "ts_us")
    t = h if freq == "1h" else R.daily(h, {"oi": "last"})
    return t.with_columns(end_us=pl.col("ts_us") + R.PERIOD[freq])


# ---------------------------------------------------------------- flow and D2

def _market(df: pl.DataFrame, end_shift: int) -> pl.DataFrame:
    return df.with_columns(asset=pl.lit(R.MARKET), end_us=pl.col("ts_us") + end_shift)


def _daily_market(name: str, col: str, freq: str, end_shift: int = DAY, filt=None) -> pl.DataFrame:
    d = _read(flow_dir() / f"{name}.parquet")
    if not d.height or col not in d.columns:
        return _none()
    if filt is not None:
        d = d.filter(filt)
    d = d.select(ts_us=pl.col("day_us").cast(pl.Int64), v=pl.col(col).cast(pl.Float64)).drop_nulls() \
        .unique("ts_us", keep="last").sort("ts_us")
    return _market(d, end_shift)


def dvol_table(freq: str, assets) -> pl.DataFrame:
    return _daily_market("dvol", "close", freq, filt=pl.col("currency") == "BTC")


def stables_table(freq: str, assets) -> pl.DataFrame:
    return _daily_market("stables", "total", freq)


def skew_table(freq: str, assets) -> pl.DataFrame:
    d = _read(flow_dir() / "skew.parquet")
    if not d.height:
        return _none()
    d = d.filter(pl.col("currency") == "BTC").select(t=pl.col("ts_us"), v=pl.col("rr25")).drop_nulls().sort("t")
    if freq == "1h":
        return d.select(ts_us="t", asset=pl.lit(R.MARKET), end_us="t", v="v")
    return (d.with_columns(ts_us=(pl.col("t") // DAY) * DAY).group_by("ts_us")
            .agg(pl.col("v").last()).sort("ts_us").with_columns(asset=pl.lit(R.MARKET), end_us=pl.col("ts_us") + DAY))


def coinbase_table(freq: str, assets) -> pl.DataFrame:
    cb = _read(flow_dir() / "coinbase_btcusd_1h.parquet")
    d = store.ROOT / "hist" / "binance_spot" / "klines_1h" / "symbol=BTCUSDT"
    files = sorted(d.glob("*.parquet"))
    if not cb.height or not files:
        return _none()
    bn = pl.concat([pl.read_parquet(f, columns=["open_time_us", "close"]) for f in files], how="vertical_relaxed")
    h = (cb.select("ts_us", cb="close")
         .join(bn.select(ts_us="open_time_us", bn="close").unique("ts_us"), on="ts_us")
         .with_columns(v=(pl.col("cb") / pl.col("bn") - 1) * 1e4, n=pl.lit(1.0)).sort("ts_us"))
    h = h.select("ts_us", "v", "n").with_columns(asset=pl.lit(R.MARKET))
    t = h if freq == "1h" else R.daily(h, {"v": ("wmean", "n")})
    return t.with_columns(end_us=pl.col("ts_us") + R.PERIOD[freq])


def fear_greed_table(freq: str, assets) -> pl.DataFrame:
    return _daily_market("fear_greed", "value", freq)


def macro_table(freq: str, assets) -> pl.DataFrame:
    """One row a day, a column <series>_chg5 each: the change over its last 5 observations (trading days;
    us10y as a difference)."""
    d = _read(flow_dir() / "macro.parquet")
    if not d.height or not {"day_us", "series", "value"} <= set(d.columns):
        return _none()
    d = (d.select(ts_us=pl.col("day_us").cast(pl.Int64), s=pl.col("series"), v=pl.col("value").cast(pl.Float64))
         .filter(pl.col("s").is_in(MACRO)).drop_nulls().unique(["ts_us", "s"], keep="last").sort("s", "ts_us"))
    prev = pl.col("v").shift(5).over("s")
    d = d.with_columns(c=pl.when(pl.col("s") == "us10y").then(pl.col("v") - prev)
                       .otherwise(pl.when(prev.abs() > 0).then(pl.col("v") / prev - 1)))
    w = d.pivot(on="s", index="ts_us", values="c").sort("ts_us")
    for s in MACRO:
        if s not in w.columns:
            w = w.with_columns(pl.lit(None, pl.Float64).alias(s))
    return _market(w.rename({s: f"{s}_chg5" for s in MACRO}), 2 * DAY)


def hl_table(freq: str, assets) -> pl.DataFrame:
    d = _read(flow_dir() / "hyperliquid_funding.parquet")
    if not d.height or not {"ts_us", "asset", "funding"} <= set(d.columns):
        return _none()
    h = (d.select(pl.col("ts_us").cast(pl.Int64), "asset", f=pl.col("funding").cast(pl.Float64))
         .with_columns(ts_us=(pl.col("ts_us") // HOUR) * HOUR).group_by("asset", "ts_us").agg(pl.col("f").last()))
    if assets is not None:
        h = h.filter(pl.col("asset").is_in(list(assets)))
    t = h.sort("asset", "ts_us").with_columns(n=pl.lit(1.0))
    t = t if freq == "1h" else R.daily(t, {"f": ("wmean", "n")}, min_hours=1)
    return t.with_columns(end_us=pl.col("ts_us") + R.PERIOD[freq])


def events_table(freq: str, assets) -> pl.DataFrame:
    """Per bucket: how many scheduled events fall in the 24 hours after its end and were known by then."""
    d = _read(flow_dir() / "events.parquet")
    if not d.height or "ts_us" not in d.columns:
        return _none()
    known = pl.col("known_us") if "known_us" in d.columns else pl.col("ts_us") - EVENT_NOTICE
    ev = d.select(e=pl.col("ts_us").cast(pl.Int64), k=known.cast(pl.Int64)).drop_nulls()
    p = R.PERIOD[freq]
    lo, hi = (int(ev["e"].min()) - EVENT_NOTICE) // p * p, int(ev["e"].max()) // p * p
    ts = np.arange(lo, hi + p, p, dtype=np.int64)
    v = np.zeros(len(ts))
    for e, k in ev.iter_rows():
        # a bucket counts the event when its end is in [max(k, e - 1 day), e)
        a = np.searchsorted(ts + p, max(k, e - DAY), side="left")
        b = np.searchsorted(ts + p, e, side="left")
        v[a:b] += 1
    return pl.DataFrame({"ts_us": ts, "asset": R.MARKET, "end_us": ts + p, "v": v})


# ---------------------------------------------------------------- groups and features

FUNDING_SRC = ("hist/binance_um/funding",)
R.group(R.Group("funding", FUNDING_SRC, funding_table))
R.group(R.Group("oi", ("hist/binance_um/metrics", "binance_um/open_interest"), oi_table))
R.group(R.Group("dvol", ("flow/dvol",), dvol_table))
R.group(R.Group("skew", ("flow/skew",), skew_table))
R.group(R.Group("stables", ("flow/stables",), stables_table))
R.group(R.Group("coinbase", ("flow/coinbase_btcusd_1h", "hist/binance_spot/klines_1h"), coinbase_table))
R.group(R.Group("fear_greed", ("flow/fear_greed",), fear_greed_table))
R.group(R.Group("macro", ("flow/macro",), macro_table))
R.group(R.Group("hl", ("flow/hyperliquid_funding",), hl_table))
R.group(R.Group("events", ("flow/events",), events_table))


def _v(p):
    return pl.col("v")


def _mkt_chg(col: str, days: int):
    """A market series' change over `days` days, from its daily rows only (none across a gap)."""
    def fn(p):
        prev = pl.col(col).shift(days)
        ok = (pl.col("ts_us") - pl.col("ts_us").shift(days)) == days * DAY
        return pl.when(ok & (prev.abs() > 0)).then(pl.col(col) / prev - 1)
    return fn


DAILY_AGE = {"1h": DAY, "1d": DAY}
R.register(R.Feature("funding_8h", "funding", FUNDING_SRC, "8h", 0, lambda p: pl.col("f8"),
                     max_age_us={"1h": 9 * HOUR, "1d": DAY},
                     about="Binance USD-M settled funding: hourly the last rate on 8 h, daily the day's sum"))
R.register(R.Feature("oi_chg", "oi", ("hist/binance_um/metrics", "binance_um/open_interest"), "5m", 0,
                     lambda p: R.pct_change("oi", p),
                     about="Binance USD-M open interest (contracts), change over the bucket"))
R.register(R.Feature("oi_chg_24h", "oi", ("hist/binance_um/metrics", "binance_um/open_interest"), "5m", 0,
                     lambda p: R.pct_change("oi", p, DAY // p),
                     about="Binance USD-M open interest, change over 24 hours", freqs=("1h",)))
R.register(R.Feature("dvol_btc", "dvol", ("flow/dvol",), "1d", HOUR, _v, market=True, max_age_us=DAILY_AGE,
                     about="Deribit BTC DVOL, daily close"))
R.register(R.Feature("skew_rr25_btc", "skew", ("flow/skew",), "1d", 0, _v, market=True,
                     max_age_us={"1h": 36 * HOUR, "1d": DAY},
                     about="Deribit BTC 25-delta risk reversal at 30 days (snapshot)"))
R.register(R.Feature("stables_chg7", "stables", ("flow/stables",), "1d", HOUR, _mkt_chg("v", 7), market=True,
                     max_age_us=DAILY_AGE, about="DefiLlama stablecoin supply, change over 7 days"))
R.register(R.Feature("coinbase_prem_bps", "coinbase", ("flow/coinbase_btcusd_1h", "hist/binance_spot/klines_1h"),
                     "1h", 0, _v, market=True, about="Coinbase BTC-USD over Binance BTCUSDT close, bp"))
R.register(R.Feature("fear_greed", "fear_greed", ("flow/fear_greed",), "1d", HOUR, _v, market=True,
                     max_age_us=DAILY_AGE, about="D2: Fear and Greed index"))
R.register(R.Feature("hl_funding", "hl", ("flow/hyperliquid_funding",), "1h", 0, lambda p: pl.col("f"),
                     max_age_us={"1h": 2 * HOUR, "1d": DAY}, about="D2: Hyperliquid funding rate"))
for _s in MACRO:
    R.register(R.Feature(f"macro_{_s}_chg5", "macro", ("flow/macro",), "1d", 0,
                         lambda p, c=f"{_s}_chg5": pl.col(c), market=True,
                         max_age_us={"1h": 4 * DAY, "1d": 4 * DAY},
                         about=f"D2: {_s} change over 5 days" + (" (difference)" if _s == "us10y" else "")))
R.register(R.Feature("event_next24h", "events", ("flow/events",), "1d", 0, _v, market=True,
                     about="D2: scheduled events in the next 24 hours, known by then"))
