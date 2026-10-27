"""C1's candle measures as features: the lab's coins' Binance spot bars from lab.candles.store (1h and 1d,
built from the 1m archive and the REST fill, complete bars only), known at the bar's close.

  cdl_body        (close - open) / (high - low), 0 for a bar without range
  cdl_upper       upper shadow / range
  cdl_lower       lower shadow / range
  cdl_range       ln(high / low)
  cdl_taker       taker buy share of the quote volume
  cdl_vwap_dist   close / VWAP - 1
  cdl_ret         the bar's return (close over the previous close)
  cdl_ret_4h      over 4 hours (hourly only)
  cdl_ret_1d      over 24 hours (hourly only; daily that is cdl_ret)
  cdl_ret_1w      over 7 days
Returns need their neighbours: none across a missing bar.
"""

from __future__ import annotations

import polars as pl

from .. import data
from ..candles import store as cs
from ..data import UNIVERSE
from . import registry as R
from . import store

SRC = ("hist/binance_spot/klines_1m", "candles/source=binance_rest", "hist/binance_spot/klines_1h",
       "hist/binance_spot/klines_1d")
COLS = {"body": "body", "upper": "upper", "lower": "lower", "range": "range", "taker": "taker_buy_share",
        "vwap_dist": "vwap_dist"}


def candles_table(freq: str, assets) -> pl.DataFrame:
    root = None if store.ROOT == data.ROOT else store.ROOT       # the tests' lake, else the lab's folders
    rows = []
    for a in (UNIVERSE if assets is None else [x for x in assets if x in UNIVERSE]):
        b = cs.candles(a, freq, complete_only=True, root=root)
        if b.height:
            m = cs.measures(b)
            rows.append(m.select(ts_us="open_time_us", asset="asset", end_us="close_time_us", **COLS, ret="ret_1",
                                 ret_4h="ret_4", ret_1d="ret_24", ret_1w="ret_168" if freq == "1h" else "ret_7"))
    if not rows:
        return pl.DataFrame(schema={"ts_us": pl.Int64, "asset": pl.String, "end_us": pl.Int64})
    return pl.concat(rows, how="vertical_relaxed")


R.group(R.Group("candles", SRC, candles_table))


def _c(col):
    return lambda p: pl.col(col)


for _n, _about in (("body", "candle body over its range, signed"), ("upper", "upper shadow over the range"),
                   ("lower", "lower shadow over the range"), ("range", "ln(high / low) of the bar"),
                   ("taker", "taker buy share of the quote volume"), ("vwap_dist", "close over the bar's VWAP minus 1")):
    R.register(R.Feature(f"cdl_{_n}", "candles", SRC, "60s", 0, _c(_n), about=f"C1: {_about}, Binance spot"))
R.register(R.Feature("cdl_ret", "candles", SRC, "60s", 0, _c("ret"), about="C1: the bar's return, Binance spot"))
R.register(R.Feature("cdl_ret_4h", "candles", SRC, "60s", 0, _c("ret_4h"), freqs=("1h",),
                     about="C1: return over 4 hours, Binance spot"))
R.register(R.Feature("cdl_ret_1d", "candles", SRC, "60s", 0, _c("ret_1d"), freqs=("1h",),
                     about="C1: return over 24 hours, Binance spot"))
R.register(R.Feature("cdl_ret_1w", "candles", SRC, "60s", 0, _c("ret_1w"), about="C1: return over 7 days, Binance spot"))
