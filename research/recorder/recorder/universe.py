"""Every USDT spot pair Binance has ever listed, delisted ones included.

The exchange's live API only knows today's survivors. Training a model on
them alone teaches it that crypto coins go up, because the ones that went to
zero are missing. data.binance.vision keeps the archives of delisted pairs,
so the full list comes from its bucket listing instead.

    python -m recorder.universe            # prints the count and writes hist/universe.json
"""

from __future__ import annotations

import asyncio
import json
import re

import aiohttp

from . import config

BUCKET = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
# Not coins: stablecoins and fiat against USDT, and Binance's leveraged tokens.
STABLE = {"USDC", "BUSD", "TUSD", "FDUSD", "DAI", "PAX", "USDP", "UST", "USTC", "SUSD", "EUR", "GBP", "AUD",
          "TRY", "BRL", "RUB", "NGN", "UAH", "ZAR", "IDRT", "BIDR", "BKRW", "AEUR", "EURI", "USD1", "XUSD",
          "BFUSD", "USDE", "RLUSD", "PYUSD", "U"}
LEVERAGED = re.compile(r"(UP|DOWN|BULL|BEAR)$")


async def list_spot_usdt(http: aiohttp.ClientSession) -> list[str]:
    out, marker = [], ""
    while True:
        params = {"delimiter": "/", "prefix": "data/spot/monthly/klines/"}
        if marker:
            params["marker"] = marker
        async with http.get(BUCKET, params=params) as r:
            r.raise_for_status()
            x = await r.text()
        out += re.findall(r"<Prefix>data/spot/monthly/klines/([^/<]+)/</Prefix>", x)
        nxt = re.findall(r"<NextMarker>([^<]+)</NextMarker>", x)
        if "<IsTruncated>true</IsTruncated>" not in x or not nxt:
            break
        marker = nxt[0]
    coins = []
    for s in out:
        if not s.endswith("USDT"):
            continue
        base = s[:-4]
        if not base or base in STABLE or LEVERAGED.search(base):
            continue
        coins.append(s)
    return sorted(set(coins))


async def list_um_usdt(http: aiohttp.ClientSession) -> list[str]:
    """Every USDT-margined perpetual Binance ever listed (dated futures, with an
    underscore in the name, are left out)."""
    out, marker = [], ""
    while True:
        params = {"delimiter": "/", "prefix": "data/futures/um/monthly/klines/"}
        if marker:
            params["marker"] = marker
        async with http.get(BUCKET, params=params) as r:
            r.raise_for_status()
            x = await r.text()
        out += re.findall(r"<Prefix>data/futures/um/monthly/klines/([^/<]+)/</Prefix>", x)
        nxt = re.findall(r"<NextMarker>([^<]+)</NextMarker>", x)
        if "<IsTruncated>true</IsTruncated>" not in x or not nxt:
            break
        marker = nxt[0]
    return sorted({s for s in out if s.endswith("USDT") and "_" not in s})


def perp_base(symbol: str) -> str:
    """1000PEPEUSDT -> PEPE: the multiplier changes the price, not the return."""
    base = symbol[:-4]
    for p in ("1000000", "1000", "1M"):
        if base.startswith(p) and len(base) > len(p):
            return base[len(p):]
    return base


async def main() -> None:
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=120)) as http:
        syms = await list_spot_usdt(http)
    d = config.DATA_ROOT / "hist"
    d.mkdir(parents=True, exist_ok=True)
    (d / "universe.json").write_text(json.dumps(syms))
    print(len(syms), "USDT spot pairs, first", syms[:5])


if __name__ == "__main__":
    asyncio.run(main())
