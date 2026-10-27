"""Microstructure features from what the recorder keeps: hourly per asset, built one UTC day at a time.

Every raw row is put in the hour of its ts_recv_us (when this machine had it), never of the exchange's
time, so an hour's row holds only what was known by its end (end_us = hour start + 1 h).

  book    the top-20 books of five venues (5 s): per snapshot the spread (ask - bid) / mid in bp, the
          notional within 10 and 50 bp of the mid on both sides (within the 20 recorded levels, so a deep
          book is cut off there), the imbalance (bid - ask) / (bid + ask) of that 50 bp notional; hourly
          means for Binance spot (the unprefixed features) and Kraken (kraken_*). All five venues give one
          mid a minute; Binance, Bybit and OKX quote USDT and are put in USD at Kraken's USDT/USD mid of
          the same minute (as recorded, none when it is missing), and the dispersion is (max - min) /
          median of the venues' mids in bp, for minutes with two venues or more.
  trades  every Kraken trade: buy and sell notional (the taker side Kraken reports), realised variance
          from the last price of each traded minute (returns between traded minutes of the same hour).
  perp    Binance USD-M (60 s): the funding rate as published (the running estimate), the mark's premium
          over the index in bp, open interest as recorded.
  liq     Binance USD-M liquidations: notional by side; a SELL order closes a long. Hours the stream wrote
          anything count as zero for a symbol without one, so a quiet hour is 0, not missing.
"""

from __future__ import annotations

import polars as pl

from ..data import UNIVERSE
from . import registry as R
from . import store

HOUR = R.HOUR
VENUES = ("binance", "kraken", "bybit", "okx", "coinbase")
BOOK_FEATURES = ("binance", "kraken")               # venues with their own book features
USDT_QUOTED = ("binance", "bybit", "okx")
BOOK_COLS = ("spread", "d10", "d50", "imb")
BOOK_SPEC = {**{f"{v}_n": "sum" for v in BOOK_FEATURES},
             **{f"{v}_{c}": ("wmean", f"{v}_n") for v in BOOK_FEATURES for c in BOOK_COLS},
             "disp_bps": ("wmean", "disp_n"), "disp_n": "sum"}
TRADES_SPEC = {"n": "sum", "buy_usd": "sum", "sell_usd": "sum", "rv2": "sum"}
PERP_SPEC = {"funding": "last", "prem_bps": ("wmean", "prem_n"), "prem_n": "sum", "oi": "last"}
LIQ_SPEC = {"liq_long_usd": "sum", "liq_short_usd": "sum"}


def spot_asset() -> pl.Expr:
    """BTC/USD, BTCUSDT, BTC-USDT, BTC-USD -> BTC (USDT/USD -> USDT)."""
    return pl.col("symbol").str.replace(r"(/USD|-USDT|-USD|USDT)$", "")


def perp_asset() -> pl.Expr:
    """BTCUSDT -> BTC, 1000PEPEUSDT -> PEPE; only USDT perpetuals."""
    return pl.col("symbol").str.replace(r"USDT$", "").str.replace(r"^(1000000|10000|1000)([A-Z])", "${2}")


def hour() -> pl.Expr:
    return (pl.col("ts_recv_us") // HOUR) * HOUR


def _empty(cols: dict) -> pl.DataFrame:
    return pl.DataFrame(schema={"ts_us": pl.Int64, "asset": pl.String, **cols})


# ---------------------------------------------------------------- book

def _within(side: str, bp: float) -> pl.Expr:
    px, q = pl.col(f"{side}_px"), pl.col(f"{side}_qty")
    dist = (px / pl.col("mid") - 1) if side == "ask" else (1 - px / pl.col("mid"))
    return (px * q * dist.list.eval((pl.element() <= bp * 1e-4).cast(pl.Float64))).list.sum()


def snapshots(venue: str, date: str) -> pl.DataFrame:
    """(ts_recv_us, asset, mid, spread, d10, d50, imb) of one venue's day, universe coins (and USDT on Kraken)."""
    b = store.read_raw(f"{venue}/book20", date, ["ts_recv_us", "symbol", "bid_px", "bid_qty", "ask_px", "ask_qty"])
    if not b.height:
        return pl.DataFrame()
    b0, a0 = pl.col("bid_px").list.first(), pl.col("ask_px").list.first()
    keep = set(UNIVERSE) | ({"USDT"} if venue == "kraken" else set())
    b = (b.with_columns(asset=spot_asset()).filter(pl.col("asset").is_in(sorted(keep)))
         .filter((b0 > 0) & (a0 > b0)).with_columns(mid=(b0 + a0) / 2))
    b = b.with_columns(b10=_within("bid", 10), a10=_within("ask", 10), b50=_within("bid", 50), a50=_within("ask", 50))
    return b.select("ts_recv_us", "asset", "mid",
                    spread=(a0 - b0) / pl.col("mid") * 1e4,
                    d10=pl.col("b10") + pl.col("a10"), d50=pl.col("b50") + pl.col("a50"),
                    imb=pl.when(pl.col("b50") + pl.col("a50") > 0)
                    .then((pl.col("b50") - pl.col("a50")) / (pl.col("b50") + pl.col("a50"))))


def book_day(date: str) -> pl.DataFrame:
    hourly, mids = [], []
    for v in VENUES:
        s = snapshots(v, date)
        if not s.height:
            continue
        mids.append(s.with_columns(minute=pl.col("ts_recv_us") // 60_000_000).sort("ts_recv_us")
                    .group_by("asset", "minute").agg(pl.col("mid").last()).with_columns(venue=pl.lit(v)))
        if v in BOOK_FEATURES:
            hourly.append(s.filter(pl.col("asset") != "USDT").with_columns(ts_us=hour())
                          .group_by("ts_us", "asset")
                          .agg(pl.len().cast(pl.Int64).alias(f"{v}_n"),
                               *[pl.col(c).mean().alias(f"{v}_{c}") for c in BOOK_COLS]))
        del s
    if not mids:
        return _empty({})
    m = pl.concat(mids)
    usdt = m.filter((pl.col("venue") == "kraken") & (pl.col("asset") == "USDT")).select("minute", usdt=pl.col("mid"))
    m = m.filter(pl.col("asset") != "USDT").join(usdt, on="minute", how="left")
    m = m.with_columns(mid=pl.when(pl.col("venue").is_in(USDT_QUOTED)).then(pl.col("mid") * pl.col("usdt"))
                       .otherwise(pl.col("mid"))).drop_nulls("mid")
    disp = (m.group_by("asset", "minute").agg(n=pl.len(), hi=pl.col("mid").max(), lo=pl.col("mid").min(),
                                              med=pl.col("mid").median())
            .filter(pl.col("n") >= 2)
            .with_columns(ts_us=(pl.col("minute") * 60_000_000 // HOUR) * HOUR,
                          d=(pl.col("hi") - pl.col("lo")) / pl.col("med") * 1e4)
            .group_by("ts_us", "asset").agg(disp_bps=pl.col("d").mean(), disp_n=pl.len().cast(pl.Int64)))
    out = disp
    for h in hourly:
        out = out.join(h, on=["ts_us", "asset"], how="full", coalesce=True)
    return out.sort("asset", "ts_us")


# ---------------------------------------------------------------- trades, perp, liquidations

def _zero_fill(h: pl.DataFrame, alive: pl.Series, cols: list[str]) -> pl.DataFrame:
    """Every asset of the day at every hour the stream wrote anything; a missing hour counts as zero."""
    grid = pl.DataFrame({"ts_us": alive.unique().sort()}).join(h.select("asset").unique(), how="cross")
    return grid.join(h, on=["ts_us", "asset"], how="left").with_columns(pl.col(cols).fill_null(0.0))


def trades_day(date: str) -> pl.DataFrame:
    t = store.read_raw("kraken/trades", date, ["ts_recv_us", "symbol", "side", "price", "qty"])
    if not t.height:
        return _empty({})
    t = t.with_columns(asset=spot_asset(), ts_us=hour(), usd=pl.col("price") * pl.col("qty")) \
        .filter(pl.col("asset").is_in(UNIVERSE) & (pl.col("price") > 0))
    alive = t["ts_us"]
    flow = t.group_by("ts_us", "asset").agg(
        n=pl.len().cast(pl.Float64),
        buy_usd=pl.col("usd").filter(pl.col("side") == "buy").sum(),
        sell_usd=pl.col("usd").filter(pl.col("side") == "sell").sum())
    px = (t.sort("ts_recv_us").with_columns(minute=pl.col("ts_recv_us") // 60_000_000)
          .group_by("asset", "ts_us", "minute").agg(pl.col("price").last()).sort("asset", "minute")
          .with_columns(r=pl.col("price").log().diff().over("asset", "ts_us"))
          .group_by("ts_us", "asset").agg(rv2=(pl.col("r") ** 2).sum()))
    h = flow.join(px, on=["ts_us", "asset"], how="left")
    return _zero_fill(h, alive, ["n", "buy_usd", "sell_usd", "rv2"]).sort("asset", "ts_us")


def perp_day(date: str) -> pl.DataFrame:
    p = store.read_raw("binance_um/premium", date, ["ts_recv_us", "symbol", "mark_price", "index_price", "funding_rate"])
    o = store.read_raw("binance_um/open_interest", date, ["ts_recv_us", "symbol", "open_interest"])
    out = None
    if p.height:
        out = (p.filter(pl.col("symbol").str.ends_with("USDT")).with_columns(asset=perp_asset(), ts_us=hour())
               .sort("ts_recv_us").group_by("ts_us", "asset")
               .agg(funding=pl.col("funding_rate").drop_nulls().last(),
                    prem_bps=((pl.col("mark_price") / pl.col("index_price") - 1) * 1e4)
                    .filter(pl.col("index_price") > 0).mean(),
                    prem_n=(pl.col("index_price") > 0).sum().cast(pl.Int64)))
    if o.height:
        oi = (o.filter(pl.col("symbol").str.ends_with("USDT")).with_columns(asset=perp_asset(), ts_us=hour())
              .sort("ts_recv_us").group_by("ts_us", "asset").agg(oi=pl.col("open_interest").drop_nulls().last()))
        out = oi if out is None else out.join(oi, on=["ts_us", "asset"], how="full", coalesce=True)
    return _empty({}) if out is None else out.sort("asset", "ts_us")


def liq_day(date: str) -> pl.DataFrame:
    q = store.read_raw("binance_um/liquidations", date, ["ts_recv_us", "symbol", "side", "avg_price", "filled_qty",
                                                         "price", "qty"])
    if not q.height:
        return _empty({})
    q = q.filter(pl.col("symbol").str.ends_with("USDT")).with_columns(
        asset=perp_asset(), ts_us=hour(),
        usd=pl.when(pl.col("filled_qty") > 0).then(pl.col("avg_price") * pl.col("filled_qty"))
        .otherwise(pl.col("price") * pl.col("qty")))
    alive = q["ts_us"]
    h = q.group_by("ts_us", "asset").agg(liq_long_usd=pl.col("usd").filter(pl.col("side") == "SELL").sum(),
                                        liq_short_usd=pl.col("usd").filter(pl.col("side") == "BUY").sum())
    return _zero_fill(h, alive, ["liq_long_usd", "liq_short_usd"]).sort("asset", "ts_us")


# ---------------------------------------------------------------- groups and features

def _cached(name: str, sources: tuple, build_day, spec: dict) -> R.Group:
    def table(freq: str, assets) -> pl.DataFrame:
        h = store.hourly(name)
        if assets is not None and h.height:
            h = h.filter(pl.col("asset").is_in(list(assets)))
        t = h if freq == "1h" else R.daily(h, spec)
        return t.with_columns(end_us=pl.col("ts_us") + R.PERIOD[freq]) if t.height else t.with_columns(
            end_us=pl.lit(None, pl.Int64))
    store.BUILDERS[name] = (sources, build_day)
    return R.group(R.Group(name, sources, table, cached=True))


BOOK_SRC = tuple(f"{v}/book20" for v in VENUES)
_cached("book", BOOK_SRC, book_day, BOOK_SPEC)
_cached("trades", ("kraken/trades",), trades_day, TRADES_SPEC)
_cached("perp", ("binance_um/premium", "binance_um/open_interest"), perp_day, PERP_SPEC)
_cached("liq", ("binance_um/liquidations",), liq_day, LIQ_SPEC)


def _col(c: str):
    return lambda p: pl.col(c)


for v, pre in (("binance", ""), ("kraken", "kraken_")):
    src = (f"{v}/book20",)
    R.register(R.Feature(f"{pre}spread_bps", "book", src, "5s", 0, _col(f"{v}_spread"),
                         about=f"{v} spot: mean quoted spread (ask - bid) / mid, bp"))
    R.register(R.Feature(f"{pre}depth10_usd", "book", src, "5s", 0, _col(f"{v}_d10"), level=True,
                         about=f"{v} spot: mean notional within 10 bp of the mid, both sides"))
    R.register(R.Feature(f"{pre}depth50_usd", "book", src, "5s", 0, _col(f"{v}_d50"), level=True,
                         about=f"{v} spot: mean notional within 50 bp of the mid (20 levels at most)"))
    R.register(R.Feature(f"{pre}book_imb", "book", src, "5s", 0, _col(f"{v}_imb"),
                         about=f"{v} spot: mean (bid - ask) / (bid + ask) of the 50 bp notional"))
    R.register(R.Feature(f"{pre}book_imb_chg", "book", src, "5s", 0,
                         lambda p, c=f"{v}_imb": R.change(c, p),
                         about=f"{v} spot: book_imb minus the bucket before (none after a gap)"))
R.register(R.Feature("xvenue_disp_bps", "book", BOOK_SRC, "5s", 0, _col("disp_bps"),
                     about="(max - min) / median of the five venues' minute mids in USD, bp, mean"))
R.register(R.Feature("trade_imb", "trades", ("kraken/trades",), "trade", 0,
                     lambda p: pl.when(pl.col("buy_usd") + pl.col("sell_usd") > 0)
                     .then((pl.col("buy_usd") - pl.col("sell_usd")) / (pl.col("buy_usd") + pl.col("sell_usd"))),
                     about="Kraken: (taker buy - taker sell) / both, notional"))
R.register(R.Feature("trade_usd", "trades", ("kraken/trades",), "trade", 0,
                     lambda p: pl.col("buy_usd") + pl.col("sell_usd"), level=True,
                     about="Kraken: traded notional, USD"))
R.register(R.Feature("rv_trades", "trades", ("kraken/trades",), "trade", 0,
                     lambda p: (pl.col("rv2") * (365 * R.DAY / p)).sqrt(),
                     about="Kraken: realised vol from 1-minute trade prices, annualised"))
R.register(R.Feature("funding_est", "perp", ("binance_um/premium",), "60s", 0, _col("funding"),
                     about="Binance USD-M: funding rate as published at the bucket's end"))
R.register(R.Feature("premium_bps", "perp", ("binance_um/premium",), "60s", 0, _col("prem_bps"),
                     about="Binance USD-M: mark over index, bp, mean"))
R.register(R.Feature("liq_long_usd", "liq", ("binance_um/liquidations",), "trade", 0, _col("liq_long_usd"),
                     level=True, about="Binance USD-M: longs liquidated, notional"))
R.register(R.Feature("liq_short_usd", "liq", ("binance_um/liquidations",), "trade", 0, _col("liq_short_usd"),
                     level=True, about="Binance USD-M: shorts liquidated, notional"))
