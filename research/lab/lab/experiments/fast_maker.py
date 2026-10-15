"""W15: faster crypto trades with resting maker orders only, on the 33 Alpaca coins.

    python -m lab.experiments.fast_maker
"""

from __future__ import annotations

from datetime import date

DATA_END = date(2026, 10, 14)
TWIN_RANK_SINCE = date(2023, 9, 1)

# Alpaca's crypto list (36 assets, March 2026) without its three stablecoins
# (USDC, USDG, USDT): 33 coins. Binance spot symbols in time order; a renamed
# token is spliced (MATIC to POL, RNDR to RENDER, MKR to SKY).
SYMBOLS: dict[str, list[str]] = {
    "AAVE": ["AAVEUSDT"], "ADA": ["ADAUSDT"], "ARB": ["ARBUSDT"], "AVAX": ["AVAXUSDT"], "BAT": ["BATUSDT"],
    "BCH": ["BCHUSDT"], "BONK": ["BONKUSDT"], "BTC": ["BTCUSDT"], "CRV": ["CRVUSDT"], "DOGE": ["DOGEUSDT"],
    "DOT": ["DOTUSDT"], "ETH": ["ETHUSDT"], "FIL": ["FILUSDT"], "GRT": ["GRTUSDT"], "HYPE": ["HYPEUSDT"],
    "LDO": ["LDOUSDT"], "LINK": ["LINKUSDT"], "LTC": ["LTCUSDT"], "ONDO": ["ONDOUSDT"], "PAXG": ["PAXGUSDT"],
    "PEPE": ["PEPEUSDT"], "POL": ["MATICUSDT", "POLUSDT"], "RENDER": ["RNDRUSDT", "RENDERUSDT"],
    "SHIB": ["SHIBUSDT"], "SKY": ["MKRUSDT", "SKYUSDT"], "SOL": ["SOLUSDT"], "SUSHI": ["SUSHIUSDT"],
    "TRUMP": ["TRUMPUSDT"], "UNI": ["UNIUSDT"], "WIF": ["WIFUSDT"], "XRP": ["XRPUSDT"], "XTZ": ["XTZUSDT"],
    "YFI": ["YFIUSDT"],
}

STABLE = {"USDC", "BUSD", "TUSD", "USDP", "PAX", "DAI", "FDUSD", "USDS", "USDSB", "SUSD", "UST", "USTC", "EUR",
          "GBP", "AUD", "TRY", "BRL", "RUB", "UAH", "NGN", "ZAR", "BIDR", "IDRT", "BVND", "AEUR", "EURI", "USD1",
          "XUSD", "USDE", "BFUSD", "RLUSD", "USDG", "PYUSD", "U"}


def excluded_symbol(symbol: str) -> bool:
    """Stablecoins, fiat and leveraged tokens are never part of the twin."""
    base = symbol[:-4]
    return (base in STABLE or base.endswith(("UP", "DOWN", "BULL", "BEAR")) and len(base) > 4)


def twin_symbols() -> list[str]:
    raise NotImplementedError
