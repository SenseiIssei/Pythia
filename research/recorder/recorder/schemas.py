"""Parquet schemas. Times are int64 microseconds since the epoch, UTC."""

import pyarrow as pa

_levels = pa.list_(pa.float64())

TRADES = pa.schema([
    ("ts_recv_us", pa.int64()),
    ("ts_exch_us", pa.int64()),
    ("symbol", pa.string()),
    ("side", pa.string()),
    ("price", pa.float64()),
    ("qty", pa.float64()),
    ("ord_type", pa.string()),
    ("trade_id", pa.int64()),
])

BOOK = pa.schema([
    ("ts_recv_us", pa.int64()),
    ("ts_exch_us", pa.int64()),       # Kraken: last update; Binance: null (partial depth has no time)
    ("update_id", pa.int64()),        # Binance lastUpdateId; Kraken: null
    ("symbol", pa.string()),
    ("bid_px", _levels),
    ("bid_qty", _levels),
    ("ask_px", _levels),
    ("ask_qty", _levels),
])

PREMIUM = pa.schema([
    ("ts_recv_us", pa.int64()),
    ("ts_exch_us", pa.int64()),
    ("symbol", pa.string()),
    ("mark_price", pa.float64()),
    ("index_price", pa.float64()),
    ("funding_rate", pa.float64()),   # last settled / current estimate as published
    ("interest_rate", pa.float64()),
    ("next_funding_us", pa.int64()),
])

OPEN_INTEREST = pa.schema([
    ("ts_recv_us", pa.int64()),
    ("ts_exch_us", pa.int64()),
    ("symbol", pa.string()),
    ("open_interest", pa.float64()),  # in contracts (= coins for USD-M linear)
])

LIQUIDATIONS = pa.schema([
    ("ts_recv_us", pa.int64()),
    ("ts_exch_us", pa.int64()),
    ("symbol", pa.string()),
    ("side", pa.string()),
    ("order_type", pa.string()),
    ("price", pa.float64()),
    ("avg_price", pa.float64()),
    ("qty", pa.float64()),
    ("filled_qty", pa.float64()),
    ("status", pa.string()),
])

SPREAD = pa.schema([
    ("ts_recv_us", pa.int64()),
    ("base", pa.string()),
    ("kraken_bid", pa.float64()),     # USD
    ("kraken_ask", pa.float64()),
    ("binance_bid", pa.float64()),    # USDT
    ("binance_ask", pa.float64()),
    ("usdt_usd_bid", pa.float64()),   # Kraken USDT/USD
    ("usdt_usd_ask", pa.float64()),
    ("kraken_age_ms", pa.int32()),
    ("binance_age_ms", pa.int32()),
    ("mid_spread_bps", pa.float64()),       # (binance mid in USD - kraken mid) / kraken mid
    ("edge_buy_kraken_bps", pa.float64()),  # buy Kraken ask, sell Binance bid, USDT -> USD at bid
    ("edge_buy_binance_bps", pa.float64()), # buy Binance ask (USD -> USDT at ask), sell Kraken bid
])
