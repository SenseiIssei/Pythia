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
  cdl_range_rel   the bar's range over the mean range of the last 20 bars (itself included)
C2 (shapes on more than one timeframe): the last 4 hours, 24 hours or 7 days as one candle (open of the
first bar, the highest high, the lowest low, the close of the bar), on the hourly grid 4h, 1d and 1w, on the
daily grid 1w:
  cdl_body_<tf>   body over the range, signed     cdl_upper_<tf>  upper shadow over the range
  cdl_lower_<tf>  lower shadow over the range     cdl_range_<tf>  ln(high / low)
Returns, the window candles and the range ratio need their neighbours: none across a missing bar.
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
SHAPES = ("body", "upper", "lower", "range")
WINDOWS = {"1h": {"4h": 4, "1d": 24, "1w": 168}, "1d": {"1w": 7}}   # freq -> window name -> bars
REL_BARS = 20


def windowed(m: pl.DataFrame, freq: str) -> pl.DataFrame:
    """One asset's measures (sorted, one timeframe) with the window candles and the range ratio: each only
    when all its bars are there, from the bars up to and including this one."""
    p = int(m["close_time_us"][0] - m["open_time_us"][0]) if m.height else 0

    def whole(k: int) -> pl.Expr:
        return (pl.col("open_time_us") - pl.col("open_time_us").shift(k - 1)) == (k - 1) * p
    out = []
    for name, k in WINDOWS[freq].items():
        o, h, lo = pl.col("open").shift(k - 1), pl.col("high").rolling_max(k), pl.col("low").rolling_min(k)
        rng = h - lo
        out += [pl.when(whole(k)).then(pl.when(rng > 0).then(x).otherwise(0.0)).alias(f"{s}_{name}")
                for s, x in (("body", (pl.col("close") - o) / rng),
                             ("upper", (h - pl.max_horizontal(o, pl.col("close"))) / rng),
                             ("lower", (pl.min_horizontal(o, pl.col("close")) - lo) / rng))]
        out.append(pl.when(whole(k) & (lo > 0)).then((h / lo).log()).alias(f"range_{name}"))
    mean = pl.col("range").rolling_mean(REL_BARS)
    out.append(pl.when(whole(REL_BARS) & (mean > 0)).then(pl.col("range") / mean).alias("range_rel"))
    return m.with_columns(out)


def candles_table(freq: str, assets) -> pl.DataFrame:
    root = None if store.ROOT == data.ROOT else store.ROOT       # the tests' lake, else the lab's folders
    rows = []
    for a in (UNIVERSE if assets is None else [x for x in assets if x in UNIVERSE]):
        b = cs.candles(a, freq, complete_only=True, root=root)
        if b.height:
            m = windowed(cs.measures(b), freq)
            more = [f"{s}_{w}" for w in WINDOWS[freq] for s in SHAPES] + ["range_rel"]
            rows.append(m.select("asset", *more, ts_us="open_time_us", end_us="close_time_us", **COLS, ret="ret_1",
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
R.register(R.Feature("cdl_range_rel", "candles", SRC, "60s", 0, _c("range_rel"),
                   about=f"C2: the bar's range over its mean of the last {REL_BARS} bars, Binance spot"))
for _w, _f in (("4h", ("1h",)), ("1d", ("1h",)), ("1w", ("1h", "1d"))):
    for _n, _about in (("body", "body over the range, signed"), ("upper", "upper shadow over the range"),
                       ("lower", "lower shadow over the range"), ("range", "ln(high / low)")):
        R.register(R.Feature(f"cdl_{_n}_{_w}", "candles", SRC, "60s", 0, _c(f"{_n}_{_w}"), freqs=_f,
                             about=f"C2: the last {_w} as one candle, {_about}, Binance spot"))
