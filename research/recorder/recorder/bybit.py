"""Bybit spot, public websocket v5: top-200 book per coin, sampled to top 20 every 5 s.

Bybit sends a snapshot on subscribe, then deltas every 100 ms. The update id
`u` goes up by one per message for a symbol, so a skipped number means a lost
delta. A snapshot can also arrive unasked (service restart, then `u` is 1) and
simply replaces the book. No checksum on spot.
"""

from __future__ import annotations

import asyncio
import json
import logging

from . import config
from .books import BookFeed

log = logging.getLogger("bybit")


class BybitBooks(BookFeed):
    name = "bybit_spot"
    source = "bybit"
    ws_url = config.BYBIT_WS
    depth = config.BYBIT_BOOK_DEPTH

    def topic(self, sym: str) -> str:
        return f"orderbook.{config.BYBIT_BOOK_DEPTH}.{sym}"

    async def load_symbols(self) -> dict[str, str]:
        listed: dict[str, str] = {}
        cursor = ""
        while True:
            params = {"category": "spot", "limit": "1000"}
            if cursor:
                params["cursor"] = cursor
            async with self.http.get(f"{config.BYBIT_REST}/instruments-info", params=params) as r:
                r.raise_for_status()
                body = await r.json()
            if body.get("retCode") != 0:
                raise RuntimeError(f"instruments-info: {body.get('retMsg')}")
            res = body["result"]
            listed.update(parse_instruments(res["list"]))
            cursor = res.get("nextPageCursor") or ""
            if not cursor:
                break
        return self.pick(listed)

    async def subscribe(self, symbols: list[str]) -> None:
        topics = [self.topic(s) for s in symbols]
        for i in range(0, len(topics), config.BYBIT_SUBSCRIBE_BATCH):
            await self.ws.send_json({"op": "subscribe", "args": topics[i:i + config.BYBIT_SUBSCRIBE_BATCH]})

    async def unsubscribe(self, sym: str) -> None:
        await self.ws.send_json({"op": "unsubscribe", "args": [self.topic(sym)]})

    async def keepalive(self) -> None:
        # Bybit drops a public connection without an application ping.
        while True:
            await asyncio.sleep(20)
            await self.ws.send_json({"op": "ping"})

    def handle(self, raw: str, recv: int) -> None:
        m = json.loads(raw)
        topic = m.get("topic")
        if not topic:
            if m.get("success") is False:
                log.warning("bybit refused: %s", m.get("ret_msg"))
            return
        if not topic.startswith("orderbook."):
            return
        d = m["data"]
        sym = d["s"]
        if sym not in self.symbols:
            return
        bk = self.book(sym)
        u = int(d["u"])
        if m.get("type") == "snapshot":
            bk.reset()
        elif not bk.live:
            return  # waiting for the snapshot after a resubscribe or reconnect
        elif bk.update_id is not None and u != bk.update_id + 1:
            if u <= bk.update_id:
                return  # a repeat of something already applied
            self.fail(sym, bk, "gap", verified=bk.verified)
            if bk.broken:
                return
        else:
            bk.verified = True
        bk.apply(d.get("b", []), True)
        bk.apply(d.get("a", []), False)
        bk.update_id = u
        bk.ts_exch_us = int(m["ts"]) * 1000 if m.get("ts") is not None else bk.ts_exch_us
        self.after_update(sym, bk, recv)


def parse_instruments(rows: list[dict]) -> dict[str, str]:
    """base -> symbol for every USDT spot pair that is trading."""
    return {r["baseCoin"]: r["symbol"] for r in rows
            if r.get("quoteCoin") == "USDT" and r.get("status") == "Trading"}
