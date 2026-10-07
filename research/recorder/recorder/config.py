"""Recorder settings. Everything tunable lives here or in the environment."""

import os
from pathlib import Path

DATA_ROOT = Path(os.environ.get("PYTHIA_DATA", "/data"))

# Coins listed on Kraken (USD) and Binance (USDT spot + USD-M perp). Anything a
# venue does not list is dropped at startup and logged, never guessed.
UNIVERSE = [
    "BTC", "ETH", "SOL", "XRP", "DOGE", "ADA", "AVAX", "LINK", "LTC", "DOT",
    "BCH", "TRX", "SUI", "NEAR", "ATOM", "UNI", "AAVE", "XLM", "PEPE", "FIL",
]

BOOK_DEPTH = 20            # levels stored per side
KRAKEN_BOOK_DEPTH = 25     # levels subscribed (Kraken accepts 10/25/100/500/1000)
BOOK_SAMPLE_S = 5          # order book snapshot cadence
SPREAD_SAMPLE_S = 15       # cross-venue spread cadence
FUTURES_POLL_S = 60        # funding / open interest cadence
FLUSH_S = 120              # buffer -> parquet
QUOTE_MAX_AGE_S = 10       # older quotes do not count for the spread
MIN_FREE_GB = float(os.environ.get("PYTHIA_MIN_FREE_GB", "20"))

KRAKEN_WS = "wss://ws.kraken.com/v2"
KRAKEN_REST = "https://api.kraken.com/0/public"
BINANCE_SPOT_WS = "wss://stream.binance.com:9443/stream"
BINANCE_SPOT_REST = "https://api.binance.com/api/v3"
# Binance moved USD-M market streams behind /market; the bare /ws path accepts
# the subscription and then stays silent (checked 2026-09-30).
BINANCE_UM_WS = "wss://fstream.binance.com/market/ws"
BINANCE_UM_REST = "https://fapi.binance.com/fapi/v1"

# Books of the venues the cost model still guesses (NEXT-STEPS §2). Public
# feeds, no keys. PYTHIA_BOOK_VENUES turns one off without a code change, for
# example if the one CPU the container has is not enough.
BOOK_VENUES = [v.strip() for v in os.environ.get("PYTHIA_BOOK_VENUES", "bybit,okx,coinbase").split(",") if v.strip()]

BYBIT_WS = "wss://stream.bybit.com/v5/public/spot"
BYBIT_REST = "https://api.bybit.com/v5/market"
# Spot depths are 1, 50, 200, 1000. 200 pushes every 100 ms; 50 every 20 ms,
# five times the messages for the same top 20.
BYBIT_BOOK_DEPTH = 200
BYBIT_SUBSCRIBE_BATCH = 10   # Bybit takes at most 10 topics per spot subscribe

OKX_WS = "wss://ws.okx.com:8443/ws/v5/public"
OKX_REST = "https://www.okx.com/api/v5/public"
OKX_BOOK_DEPTH = 400         # the public `books` channel: 400 levels, 100 ms

COINBASE_WS = "wss://ws-feed.exchange.coinbase.com"
COINBASE_REST = "https://api.exchange.coinbase.com"
# `level2` needs an API key on Coinbase Exchange; `level2_batch` (shown as
# `level2_50` in the subscription reply) is the same book in 50 ms batches, keyless.
COINBASE_CHANNEL = "level2_batch"
