"""T4: features from Binance's bookDepth archive (lab.collect.book_depth), every perp of its universe from 2023.

  book_depth   the collector's hourly rows (<data>/book_depth/hourly, PYTHIA_BOOK_DEPTH): mean bid and ask
               notional within 0.2 % and 1 % of mid (0.2 % only once the files have it, early 2026), the mean
               cost of a 10k and a 100k USD market order (bps from mid, buy and sell averaged, linear between
               the levels), snapshots per hour. Daily: the hours weighted by snapshots, at least 12 hours.
               Known at the bucket's end (the book was public at its stamp; the archive publishes a day
               about 7 to 10 h after it, published_us in the rows, for a live use).
"""

from __future__ import annotations

import polars as pl

from ..collect import book_depth as bd
from . import registry as R

SRC = ("book_depth/hourly",)
COLS = ("bid02", "ask02", "bid1", "ask1", "cost10k", "cost100k")


def _none() -> pl.DataFrame:
    return pl.DataFrame(schema={"ts_us": pl.Int64, "asset": pl.String, "end_us": pl.Int64,
                                **{c: pl.Float64 for c in COLS}, "n": pl.Int64})


def book_table(freq: str, assets) -> pl.DataFrame:
    d = bd.out_dir() / "hourly"
    rows = []
    for p in sorted(d.glob("symbol=*")) if d.is_dir() else []:
        s = p.name.removeprefix("symbol=")
        a = bd.base_of(s)
        if not s.endswith("USDT") or (assets is not None and a not in assets):
            continue
        files = sorted(p.glob("*.parquet"))
        if files:
            rows.append(pl.concat([pl.read_parquet(f, columns=["ts_us", *COLS, "n"]) for f in files],
                                  how="vertical_relaxed").with_columns(asset=pl.lit(a)))
    if not rows:
        return _none()
    # one perp per coin: a coin with two (a plain and a 1000-prefixed one) keeps the hour's deeper book
    h = (pl.concat(rows, how="vertical_relaxed").with_columns(pl.col("n").cast(pl.Int64))
         .sort("asset", "ts_us", "bid1", descending=[False, False, True], nulls_last=True)
         .unique(["asset", "ts_us"], keep="first").sort("asset", "ts_us"))
    t = h if freq == "1h" else R.daily(h, {**{c: ("wmean", "n") for c in COLS}, "n": "sum"})
    return t.with_columns(end_us=pl.col("ts_us") + R.PERIOD[freq])


R.group(R.Group("book_depth", SRC, book_table))


def _sum(a: str, b: str) -> pl.Expr:
    return pl.col(a) + pl.col(b)


def _imb(a: str, b: str) -> pl.Expr:
    s = pl.col(a) + pl.col(b)
    return pl.when(s > 0).then((pl.col(a) - pl.col(b)) / s)


def _chg(a: str, b: str, lag_p: int | None = None):
    def fn(p):
        lag = 1 if lag_p is None else lag_p // p
        prev = (pl.col(a) + pl.col(b)).shift(lag).over("asset")
        ok = (pl.col("ts_us") - pl.col("ts_us").shift(lag).over("asset")) == p * lag
        return pl.when(ok & (prev > 0)).then((pl.col(a) + pl.col(b)) / prev - 1)
    return fn


for _lv, _b, _a in (("02", "bid02", "ask02"), ("1", "bid1", "ask1")):
    _pct = "0.2" if _lv == "02" else "1"
    R.register(R.Feature(f"bd_depth{_lv}_usd", "book_depth", SRC, "30s", 0, lambda p, b=_b, a=_a: _sum(b, a),
                         level=True, about=f"T4: Binance perp book, bid plus ask notional within {_pct} % of mid, USD"))
    R.register(R.Feature(f"bd_imb{_lv}", "book_depth", SRC, "30s", 0, lambda p, b=_b, a=_a: _imb(b, a),
                         about=f"T4: Binance perp book imbalance within {_pct} % of mid, (bid - ask) / (bid + ask)"))
    R.register(R.Feature(f"bd_depth{_lv}_chg", "book_depth", SRC, "30s", 0, _chg(_b, _a),
                         about=f"T4: Binance perp book depth within {_pct} % of mid, change over the bucket"))
R.register(R.Feature("bd_depth1_chg_24h", "book_depth", SRC, "30s", 0, _chg("bid1", "ask1", R.DAY), freqs=("1h",),
                     about="T4: Binance perp book depth within 1 % of mid, change over 24 hours"))
for _k, _usd in (("cost10k", "10k"), ("cost100k", "100k")):
    R.register(R.Feature(f"bd_{_k}_bps", "book_depth", SRC, "30s", 0, lambda p, c=_k: pl.col(c),
                         about=f"T4: Binance perp book, mean slippage from mid of a {_usd} USD market order, bps"))
