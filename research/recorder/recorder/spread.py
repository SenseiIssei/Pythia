"""Cross-venue spread logger: Kraken USD vs Binance USDT, converted through Kraken USDT/USD.

Observation only. The question it answers, after 30 days: does the executable
edge (both legs at the touch, before fees) ever exceed the round-trip cost?
"""

from __future__ import annotations

import asyncio

from . import config, schemas
from .sink import Sinks, now_us
from .state import State


def _bps(x: float, ref: float) -> float:
    return (x - ref) / ref * 1e4


class SpreadLogger:
    def __init__(self, sinks: Sinks, state: State, bases: list[str]):
        self.state = state
        self.bases = bases
        self.tbl = sinks.table("spread", "kraken_binance", schemas.SPREAD)

    async def run(self) -> None:
        while True:
            await asyncio.sleep(config.SPREAD_SAMPLE_S)
            self.sample()

    def sample(self) -> None:
        now = now_us()
        max_age = config.QUOTE_MAX_AGE_S * 1_000_000
        q = self.state.quotes
        usdt = q.get(("kraken", "USDT"))
        if usdt is None or now - usdt.ts_recv_us > max_age:
            return
        for base in self.bases:
            k, b = q.get(("kraken", base)), q.get(("binance", base))
            if k is None or b is None:
                continue
            if now - k.ts_recv_us > max_age or now - b.ts_recv_us > max_age:
                continue
            k_mid = (k.bid + k.ask) / 2
            b_mid_usd = (b.bid + b.ask) / 2 * (usdt.bid + usdt.ask) / 2
            buy_k = k.ask
            sell_b_usd = b.bid * usdt.bid
            buy_b_usd = b.ask * usdt.ask
            sell_k = k.bid
            self.tbl.add({
                "ts_recv_us": now,
                "base": base,
                "kraken_bid": k.bid, "kraken_ask": k.ask,
                "binance_bid": b.bid, "binance_ask": b.ask,
                "usdt_usd_bid": usdt.bid, "usdt_usd_ask": usdt.ask,
                "kraken_age_ms": (now - k.ts_recv_us) // 1000,
                "binance_age_ms": (now - b.ts_recv_us) // 1000,
                "mid_spread_bps": _bps(b_mid_usd, k_mid),
                "edge_buy_kraken_bps": _bps(sell_b_usd, buy_k),
                "edge_buy_binance_bps": _bps(sell_k, buy_b_usd),
            })
