"""Binance: spot top-20 book (sampled), USD-M funding, open interest and liquidations.

Binance trades and klines are not recorded live: data.binance.vision publishes
them as daily dumps, and backfill.py fetches those. Only what the dumps lack is
recorded here.
"""

from __future__ import annotations

import asyncio
import json
import logging

import aiohttp

from . import config, schemas
from .net import reconnecting as _reconnecting
from .sink import Sinks, now_us
from .state import Quote, State

log = logging.getLogger("binance")


async def load_symbols(http: aiohttp.ClientSession, bases: list[str]) -> tuple[dict[str, str], dict[str, str]]:
    """base -> spot symbol, base -> perp symbol (PEPE trades as 1000PEPEUSDT)."""
    async with http.get(f"{config.BINANCE_SPOT_REST}/exchangeInfo", params={"permissions": "SPOT"}) as r:
        spot_all = {s["symbol"] for s in (await r.json())["symbols"] if s["status"] == "TRADING"}
    async with http.get(f"{config.BINANCE_UM_REST}/exchangeInfo") as r:
        perp_all = {s["symbol"] for s in (await r.json())["symbols"]
                    if s["status"] == "TRADING" and s.get("contractType") == "PERPETUAL"}
    spot, perp = {}, {}
    for b in bases:
        if f"{b}USDT" in spot_all:
            spot[b] = f"{b}USDT"
        for cand in (f"{b}USDT", f"1000{b}USDT"):
            if cand in perp_all:
                perp[b] = cand
                break
    for label, got in (("spot", spot), ("perp", perp)):
        missing = [b for b in bases if b not in got]
        if missing:
            log.warning("not listed on Binance %s, skipped: %s", label, missing)
    return spot, perp


class BinanceSpotBook:
    def __init__(self, http: aiohttp.ClientSession, sinks: Sinks, state: State, spot: dict[str, str]):
        self.http = http
        self.state = state
        self.by_symbol = {s: b for b, s in spot.items()}
        self.latest: dict[str, tuple[int, dict]] = {}
        self.tbl = sinks.table("binance", "book20", schemas.BOOK, heavy=True)

    async def run(self) -> None:
        await _reconnecting("binance_spot", self.state, self._session)

    async def _session(self) -> None:
        st = self.state.stream("binance_spot")
        streams = "/".join(f"{s.lower()}@depth20@1000ms" for s in self.by_symbol)
        # Binance drops every connection at 24 h; the loop above reconnects.
        async with self.http.ws_connect(f"{config.BINANCE_SPOT_WS}?streams={streams}",
                                        heartbeat=60, max_msg_size=0) as ws:
            log.info("binance spot connected, %d symbols", len(self.by_symbol))
            async for msg in ws:
                if msg.type != aiohttp.WSMsgType.TEXT:
                    if msg.type in (aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSED):
                        break
                    continue
                recv = now_us()
                st.messages += 1
                st.last_us = recv
                m = json.loads(msg.data)
                sym = m["stream"].split("@")[0].upper()
                d = m["data"]
                self.latest[sym] = (recv, d)
                if d["bids"] and d["asks"]:
                    self.state.quotes[("binance", self.by_symbol[sym])] = Quote(
                        float(d["bids"][0][0]), float(d["asks"][0][0]), recv)
        raise ConnectionError("socket closed")

    async def sample_loop(self) -> None:
        while True:
            await asyncio.sleep(config.BOOK_SAMPLE_S)
            cutoff = now_us() - config.QUOTE_MAX_AGE_S * 1_000_000
            for sym, (recv, d) in self.latest.items():
                if recv < cutoff:
                    continue
                self.tbl.add({
                    "ts_recv_us": recv,
                    "ts_exch_us": None,
                    "update_id": d.get("lastUpdateId"),
                    "symbol": sym,
                    "bid_px": [float(p) for p, _ in d["bids"]],
                    "bid_qty": [float(q) for _, q in d["bids"]],
                    "ask_px": [float(p) for p, _ in d["asks"]],
                    "ask_qty": [float(q) for _, q in d["asks"]],
                })


class BinanceFutures:
    def __init__(self, http: aiohttp.ClientSession, sinks: Sinks, state: State, perp: dict[str, str]):
        self.http = http
        self.state = state
        self.symbols = sorted(perp.values())
        self.premium = sinks.table("binance_um", "premium", schemas.PREMIUM)
        self.oi = sinks.table("binance_um", "open_interest", schemas.OPEN_INTEREST)
        self.liq = sinks.table("binance_um", "liquidations", schemas.LIQUIDATIONS)

    async def poll_loop(self) -> None:
        st = self.state.stream("binance_um_rest")
        wanted = set(self.symbols)
        while True:
            try:
                async with self.http.get(f"{config.BINANCE_UM_REST}/premiumIndex") as r:
                    r.raise_for_status()
                    rows = await r.json()
                recv = now_us()
                for p in rows:
                    if p["symbol"] not in wanted:
                        continue
                    self.premium.add({
                        "ts_recv_us": recv,
                        "ts_exch_us": int(p["time"]) * 1000,
                        "symbol": p["symbol"],
                        "mark_price": float(p["markPrice"]),
                        "index_price": float(p["indexPrice"]),
                        "funding_rate": float(p["lastFundingRate"]),
                        "interest_rate": float(p["interestRate"]),
                        "next_funding_us": int(p["nextFundingTime"]) * 1000,
                    })
                for sym in self.symbols:
                    async with self.http.get(f"{config.BINANCE_UM_REST}/openInterest", params={"symbol": sym}) as r:
                        r.raise_for_status()
                        o = await r.json()
                    self.oi.add({
                        "ts_recv_us": now_us(),
                        "ts_exch_us": int(o["time"]) * 1000,
                        "symbol": sym,
                        "open_interest": float(o["openInterest"]),
                    })
                    await asyncio.sleep(0.1)
                st.messages += 1
                st.last_us = now_us()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                st.errors += 1
                st.note = f"{type(e).__name__}: {e}"[:200]
                log.warning("futures poll failed: %s", st.note)
            await asyncio.sleep(config.FUTURES_POLL_S)

    async def liquidations(self) -> None:
        await _reconnecting("binance_liq", self.state, self._liq_session)

    async def _liq_session(self) -> None:
        st = self.state.stream("binance_liq")
        # All symbols, not only the universe: liquidation cascades spill across coins.
        async with self.http.ws_connect(f"{config.BINANCE_UM_WS}/!forceOrder@arr",
                                        heartbeat=60, max_msg_size=0) as ws:
            log.info("binance liquidations connected")
            async for msg in ws:
                if msg.type != aiohttp.WSMsgType.TEXT:
                    if msg.type in (aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSED):
                        break
                    continue
                recv = now_us()
                st.messages += 1
                st.last_us = recv
                o = json.loads(msg.data)["o"]
                self.liq.add({
                    "ts_recv_us": recv,
                    "ts_exch_us": int(o["T"]) * 1000,
                    "symbol": o["s"],
                    "side": o["S"],
                    "order_type": o["o"],
                    "price": float(o["p"]),
                    "avg_price": float(o["ap"]),
                    "qty": float(o["q"]),
                    "filled_qty": float(o["z"]),
                    "status": o["X"],
                })
        raise ConnectionError("socket closed")
