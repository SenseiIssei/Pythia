"""Kraken spot, WebSocket v2: every trade, plus a local order book sampled on a timer.

The book is rebuilt from snapshot + deltas and checked against Kraken's CRC32
checksum. The checksum only triggers a resync once it has matched at least once
for that symbol: if the formatting rule here were wrong, every message would
mismatch and we would resubscribe forever instead of recording.
"""

from __future__ import annotations

import asyncio
import json
import logging
import zlib
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import aiohttp

from . import config, schemas
from .net import reconnecting
from .sink import Sinks, now_us
from .state import Quote, State

log = logging.getLogger("kraken")
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
US = timedelta(microseconds=1)
REST_ALIASES = {"XBT": "BTC", "XDG": "DOGE"}


def iso_us(s: str | None) -> int | None:
    if not s:
        return None
    return (datetime.fromisoformat(s) - EPOCH) // US


async def load_pairs(http: aiohttp.ClientSession, bases: list[str]) -> dict[str, tuple[int, int]]:
    """wsname -> (price decimals, qty decimals) for every base that trades against USD."""
    async with http.get(f"{config.KRAKEN_REST}/AssetPairs") as r:
        result = (await r.json())["result"]
    out: dict[str, tuple[int, int]] = {}
    for p in result.values():
        ws = p.get("wsname") or ""
        if "/" not in ws:
            continue
        b, q = ws.split("/")
        b = REST_ALIASES.get(b, b)
        if q == "USD":
            out[f"{b}/USD"] = (int(p["pair_decimals"]), int(p["lot_decimals"]))
    wanted = {f"{b}/USD" for b in bases} | {"USDT/USD"}
    missing = sorted(wanted - out.keys())
    if missing:
        log.warning("not listed on Kraken, skipped: %s", missing)
    return {k: v for k, v in out.items() if k in wanted}


class Book:
    __slots__ = ("bids", "asks", "ts_exch_us", "live", "verified")

    def __init__(self) -> None:
        self.bids: dict[Decimal, Decimal] = {}
        self.asks: dict[Decimal, Decimal] = {}
        self.ts_exch_us: int | None = None
        self.live = False       # has a snapshot and no known corruption
        self.verified = False   # checksum matched at least once

    def apply(self, side: dict, levels: list[dict], depth: int, is_bid: bool) -> None:
        for lv in levels:
            px, qty = lv["price"], lv["qty"]
            if qty == 0:
                side.pop(px, None)
            else:
                side[px] = qty
        if len(side) > depth:
            keep = sorted(side, reverse=is_bid)[:depth]
            for px in list(side):
                if px not in keep:
                    del side[px]

    def top(self, n: int) -> tuple[list, list]:
        b = sorted(self.bids.items(), key=lambda kv: kv[0], reverse=True)[:n]
        a = sorted(self.asks.items(), key=lambda kv: kv[0])[:n]
        return b, a

    def checksum(self, pdec: int, qdec: int) -> int:
        def fmt(x: Decimal, d: int) -> str:
            return f"{x:.{d}f}".replace(".", "").lstrip("0")

        b, a = self.top(10)
        s = "".join(fmt(p, pdec) + fmt(q, qdec) for p, q in a)
        s += "".join(fmt(p, pdec) + fmt(q, qdec) for p, q in b)
        return zlib.crc32(s.encode()) & 0xFFFFFFFF


class KrakenFeed:
    def __init__(self, http: aiohttp.ClientSession, sinks: Sinks, state: State, pairs: dict[str, tuple[int, int]]):
        self.http = http
        self.state = state
        self.pairs = pairs
        self.symbols = sorted(pairs)
        self.books: dict[str, Book] = {}
        self.trades = sinks.table("kraken", "trades", schemas.TRADES)
        self.book_tbl = sinks.table("kraken", "book20", schemas.BOOK, heavy=True)
        self.ws: aiohttp.ClientWebSocketResponse | None = None

    async def run(self) -> None:
        await reconnecting("kraken", self.state, self._session, on_drop=self._invalidate_books)

    def _invalidate_books(self) -> None:
        for bk in self.books.values():
            bk.live = False

    async def _subscribe_book(self, symbols: list[str]) -> None:
        await self.ws.send_json({"method": "subscribe", "params": {
            "channel": "book", "symbol": symbols, "depth": config.KRAKEN_BOOK_DEPTH, "snapshot": True}})

    async def _resync(self, sym: str) -> None:
        await self.ws.send_json({"method": "unsubscribe", "params": {
            "channel": "book", "symbol": [sym], "depth": config.KRAKEN_BOOK_DEPTH}})
        await self._subscribe_book([sym])

    async def _session(self) -> None:
        st = self.state.stream("kraken")
        async with self.http.ws_connect(config.KRAKEN_WS, heartbeat=30, max_msg_size=0) as ws:
            self.ws = ws
            trade_syms = [s for s in self.symbols if s != "USDT/USD"]
            await ws.send_json({"method": "subscribe", "params": {
                "channel": "trade", "symbol": trade_syms, "snapshot": False}})
            await self._subscribe_book(self.symbols)
            log.info("kraken connected, %d symbols", len(self.symbols))
            async for msg in ws:
                if msg.type != aiohttp.WSMsgType.TEXT:
                    if msg.type in (aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSED):
                        break
                    continue
                recv = now_us()
                st.messages += 1
                st.last_us = recv
                m = json.loads(msg.data, parse_float=Decimal)
                ch = m.get("channel")
                if ch == "trade":
                    self._on_trades(m, recv)
                elif ch == "book":
                    await self._on_book(m, recv)
                elif m.get("method") == "subscribe" and not m.get("success", True):
                    log.warning("kraken subscribe refused: %s", m.get("error"))
        raise ConnectionError("socket closed")

    def _on_trades(self, m: dict, recv: int) -> None:
        for t in m.get("data", []):
            self.trades.add({
                "ts_recv_us": recv,
                "ts_exch_us": iso_us(t.get("timestamp")),
                "symbol": t["symbol"],
                "side": t.get("side"),
                "price": float(t["price"]),
                "qty": float(t["qty"]),
                "ord_type": t.get("ord_type"),
                "trade_id": int(t["trade_id"]) if t.get("trade_id") is not None else None,
            })

    async def _on_book(self, m: dict, recv: int) -> None:
        depth = config.KRAKEN_BOOK_DEPTH
        for d in m.get("data", []):
            sym = d["symbol"]
            bk = self.books.get(sym)
            if m.get("type") == "snapshot" or bk is None:
                bk = self.books[sym] = Book() if bk is None else bk
                bk.bids.clear()
                bk.asks.clear()
                bk.live = True
            elif not bk.live:
                continue  # waiting for the snapshot after a resync
            bk.apply(bk.bids, d.get("bids", []), depth, True)
            bk.apply(bk.asks, d.get("asks", []), depth, False)
            bk.ts_exch_us = iso_us(d.get("timestamp")) or bk.ts_exch_us
            want = d.get("checksum")
            if want is not None:
                got = bk.checksum(*self.pairs[sym])
                if got == int(want):
                    if not bk.verified:
                        log.info("kraken checksum verified for %s", sym)
                    bk.verified = True
                else:
                    self.state.bump("kraken_checksum_mismatch")
                    if bk.verified:
                        bk.live = False
                        self.state.bump("kraken_resync")
                        await self._resync(sym)
                        continue
            if bk.bids and bk.asks:
                base = sym.split("/")[0]
                self.state.quotes[("kraken", base)] = Quote(
                    float(max(bk.bids)), float(min(bk.asks)), recv)

    async def sample_loop(self) -> None:
        while True:
            await asyncio.sleep(config.BOOK_SAMPLE_S)
            recv = now_us()
            for sym, bk in self.books.items():
                if not bk.live or not bk.bids or not bk.asks:
                    continue
                b, a = bk.top(config.BOOK_DEPTH)
                self.book_tbl.add({
                    "ts_recv_us": recv,
                    "ts_exch_us": bk.ts_exch_us,
                    "update_id": None,
                    "symbol": sym,
                    "bid_px": [float(p) for p, _ in b],
                    "bid_qty": [float(q) for _, q in b],
                    "ask_px": [float(p) for p, _ in a],
                    "ask_qty": [float(q) for _, q in a],
                })
