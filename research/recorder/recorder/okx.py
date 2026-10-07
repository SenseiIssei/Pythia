"""OKX spot, public websocket v5 `books`: top-400 book per coin, sampled to top 20 every 5 s.

A snapshot on subscribe, then changes every 100 ms. Each message carries
`seqId` and `prevSeqId`; `prevSeqId` must be the `seqId` of the message
before, or a message was lost. (After maintenance OKX may restart the
numbering lower; that still chains through `prevSeqId`.) A quiet book gets an
empty message with `prevSeqId == seqId`.

The `checksum` is a signed CRC32 over the top 25 levels, bid and ask
alternating, as `price:size` with the strings exactly as sent. OKX has sent 0
there since 2026 (checked 2026-10-07); 0 is read as "no checksum", anything
else is checked under the same verified-once rule as Kraken's.
"""

from __future__ import annotations

import asyncio
import heapq
import json
import logging
import zlib

from . import config
from .books import BookFeed, L2Book

log = logging.getLogger("okx")


class OkxBook(L2Book):
    """Keeps the strings as sent, which the checksum is computed over."""

    __slots__ = ("raw_bids", "raw_asks", "checksum_ok")

    def __init__(self, depth: int | None = None) -> None:
        super().__init__(depth)
        self.raw_bids: dict[float, str] = {}
        self.raw_asks: dict[float, str] = {}
        self.checksum_ok = False   # a non-zero checksum has matched at least once

    def reset(self) -> None:
        super().reset()
        self.raw_bids.clear()
        self.raw_asks.clear()

    def set_level(self, side: dict, px: float, qty: float) -> None:
        raw = self.raw_bids if side is self.bids else self.raw_asks
        super().set_level(side, px, qty)
        if qty == 0:
            raw.pop(px, None)

    def apply(self, levels, is_bid: bool) -> None:
        side, raw = (self.bids, self.raw_bids) if is_bid else (self.asks, self.raw_asks)
        for lv in levels:
            px = float(lv[0])
            self.set_level(side, px, float(lv[1]))
            if px in side:
                raw[px] = f"{lv[0]}:{lv[1]}"
        self.trim(side, is_bid)

    def checksum(self) -> int:
        b = [self.raw_bids[p] for p in heapq.nlargest(25, self.bids)]
        a = [self.raw_asks[p] for p in heapq.nsmallest(25, self.asks)]
        parts: list[str] = []
        for i in range(max(len(b), len(a))):
            if i < len(b):
                parts.append(b[i])
            if i < len(a):
                parts.append(a[i])
        crc = zlib.crc32(":".join(parts).encode())
        return crc - (1 << 32) if crc >= 1 << 31 else crc


class OkxBooks(BookFeed):
    name = "okx_spot"
    source = "okx"
    ws_url = config.OKX_WS
    depth = config.OKX_BOOK_DEPTH

    def new_book(self) -> OkxBook:
        return OkxBook(self.depth)

    async def load_symbols(self) -> dict[str, str]:
        async with self.http.get(f"{config.OKX_REST}/instruments", params={"instType": "SPOT"}) as r:
            r.raise_for_status()
            body = await r.json()
        if str(body.get("code")) != "0":
            raise RuntimeError(f"instruments: {body.get('msg')}")
        return self.pick(parse_instruments(body["data"]))

    async def subscribe(self, symbols: list[str]) -> None:
        await self.ws.send_json({"op": "subscribe", "args": [{"channel": "books", "instId": s} for s in symbols]})

    async def unsubscribe(self, sym: str) -> None:
        await self.ws.send_json({"op": "unsubscribe", "args": [{"channel": "books", "instId": sym}]})

    async def keepalive(self) -> None:
        # OKX answers a plain "ping" with "pong"; it closes a silent connection after 30 s.
        while True:
            await asyncio.sleep(25)
            await self.ws.send_str("ping")

    def handle(self, raw: str, recv: int) -> None:
        if raw == "pong":
            return
        m = json.loads(raw)
        if "event" in m:
            if m["event"] == "error":
                log.warning("okx refused: %s %s", m.get("code"), m.get("msg"))
            return
        arg = m.get("arg") or {}
        if arg.get("channel") != "books":
            return
        sym = arg.get("instId")
        if sym not in self.symbols:
            return
        bk = self.book(sym)
        for d in m.get("data", []):
            seq, prev = int(d["seqId"]), int(d["prevSeqId"])
            if m.get("action") == "snapshot":
                bk.reset()
            elif not bk.live:
                return  # waiting for the snapshot after a resubscribe or reconnect
            elif bk.update_id is not None and prev != bk.update_id:
                self.fail(sym, bk, "gap", verified=bk.verified)
                if bk.broken:
                    return
            else:
                bk.verified = True
            bk.apply(d.get("bids", []), True)
            bk.apply(d.get("asks", []), False)
            bk.update_id = seq
            if d.get("ts"):
                bk.ts_exch_us = int(d["ts"]) * 1000
            want = int(d.get("checksum") or 0)
            if want != 0:
                if bk.checksum() == want:
                    bk.checksum_ok = True
                else:
                    self.fail(sym, bk, "checksum_mismatch", verified=bk.checksum_ok)
                    if bk.broken:
                        return
            self.after_update(sym, bk, recv)


def parse_instruments(rows: list[dict]) -> dict[str, str]:
    """base -> instId for every USDT spot pair that is live."""
    return {r["baseCcy"]: r["instId"] for r in rows if r.get("quoteCcy") == "USDT" and r.get("state") == "live"}
