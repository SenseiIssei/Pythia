"""Coinbase Exchange, public websocket `level2_batch`: the full book per coin, sampled to top 20 every 5 s.

The feed sends the whole book once (thousands of levels) and then changes in
50 ms batches. It carries no sequence number and no checksum, so the only sign
of a lost batch is a book whose best bid stays at or above its best ask (see
`books.L2Book.crossed_too_long`). Pairs are USD-quoted, as on Kraken.
"""

from __future__ import annotations

import json
import logging

from . import config
from .books import BookFeed, iso_us

log = logging.getLogger("coinbase")


class CoinbaseBooks(BookFeed):
    name = "coinbase"
    source = "coinbase"
    ws_url = config.COINBASE_WS
    depth = None   # the full book: Coinbase deletes every level it removes

    async def load_symbols(self) -> dict[str, str]:
        async with self.http.get(f"{config.COINBASE_REST}/products") as r:
            r.raise_for_status()
            rows = await r.json()
        return self.pick(parse_products(rows))

    async def subscribe(self, symbols: list[str]) -> None:
        await self.ws.send_json({"type": "subscribe", "product_ids": symbols, "channels": [config.COINBASE_CHANNEL]})

    async def unsubscribe(self, sym: str) -> None:
        await self.ws.send_json({"type": "unsubscribe", "product_ids": [sym], "channels": [config.COINBASE_CHANNEL]})

    def handle(self, raw: str, recv: int) -> None:
        m = json.loads(raw)
        kind = m.get("type")
        if kind == "error":
            log.warning("coinbase refused: %s %s", m.get("message"), m.get("reason"))
            return
        if kind not in ("snapshot", "l2update"):
            return
        sym = m.get("product_id")
        if sym not in self.symbols:
            return
        bk = self.book(sym)
        if kind == "snapshot":
            bk.reset()
            bk.apply(m.get("bids", []), True)
            bk.apply(m.get("asks", []), False)
        elif not bk.live:
            return  # waiting for the snapshot after a resubscribe or reconnect
        else:
            for side, px, qty in m.get("changes", []):
                bk.set_level(bk.bids if side == "buy" else bk.asks, float(px), float(qty))
        bk.ts_exch_us = iso_us(m.get("time")) or bk.ts_exch_us
        self.after_update(sym, bk, recv)


def parse_products(rows: list[dict]) -> dict[str, str]:
    """base -> product id for every USD pair that is online and trading."""
    return {r["base_currency"]: r["id"] for r in rows
            if r.get("quote_currency") == "USD" and r.get("status") == "online" and not r.get("trading_disabled")}
