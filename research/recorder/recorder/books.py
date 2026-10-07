"""Local order books for the venues added after Kraken and Binance: Bybit, OKX, Coinbase.

Every venue sends a snapshot and then changes. What differs is how a broken
book shows itself, so each venue checks what it can:

  Bybit     the update id `u` goes up by exactly one per message
  OKX       `prevSeqId` of each message is the `seqId` of the one before; a
            non-zero `checksum` is checked too (OKX sends 0 since 2026, checked
            2026-10-07, so in practice the sequence is the check)
  Coinbase  nothing in the feed; a book whose best bid stays at or above its
            best ask is broken (all venues get this check on top)

Resubscribing repairs a book, and a repair that never works must not turn into
a resubscribe loop (the Kraken lesson). `ResyncGuard` and `L2Book.verified`
make that impossible:

  * a failed check only counts once that check has passed for the symbol at
    least once. A check that never passes is a bug here, not a broken feed:
    the book keeps recording and the mismatch is only counted, as for Kraken
  * one resubscribe per symbol per minute at most
  * after ten in an hour the symbol is given up: it stops recording until the
    next restart, and the log and status.json say so
"""

from __future__ import annotations

import asyncio
import heapq
import logging
import time
from collections import deque
from datetime import datetime

import aiohttp

from . import config, schemas
from .net import reconnecting
from .sink import Sinks, now_us
from .state import Quote, State

log = logging.getLogger("books")

# A crossed book has to stay crossed this many messages in a row before it
# counts as broken: a batch can land between two halves of a price move.
CROSSED_LIMIT = 3


def iso_us(s: str | None) -> int | None:
    """ISO 8601 with a Z (Coinbase) to epoch microseconds; None if it does not parse."""
    if not s:
        return None
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    return int(d.timestamp() * 1_000_000)


class L2Book:
    """Price level -> size per side. Prices are floats: exchange tick sizes are
    far coarser than float resolution, and floats sort without Decimal's cost."""

    __slots__ = ("bids", "asks", "depth", "live", "broken", "verified", "sound",
                 "update_id", "ts_exch_us", "crossed_n")

    def __init__(self, depth: int | None = None) -> None:
        self.bids: dict[float, float] = {}
        self.asks: dict[float, float] = {}
        self.depth = depth          # the venue's window; None keeps the full book (Coinbase)
        self.live = False           # has a snapshot and no known corruption
        self.broken = False         # failed a verified check; waits for a resubscribe
        self.verified = False       # the venue's sequence or checksum check passed at least once
        self.sound = False          # was uncrossed at least once since its snapshot
        self.update_id: int | None = None
        self.ts_exch_us: int | None = None
        self.crossed_n = 0

    def reset(self) -> None:
        """A snapshot arrived: start over from it."""
        self.bids.clear()
        self.asks.clear()
        self.update_id = None
        self.crossed_n = 0
        self.sound = False
        self.broken = False
        self.live = True

    def set_level(self, side: dict, px: float, qty: float) -> None:
        if qty == 0:
            side.pop(px, None)
        else:
            side[px] = qty

    def apply(self, levels, is_bid: bool) -> None:
        """Levels as [price, size, ...] strings; size 0 deletes the level."""
        side = self.bids if is_bid else self.asks
        for lv in levels:
            self.set_level(side, float(lv[0]), float(lv[1]))
        self.trim(side, is_bid)

    def trim(self, side: dict, is_bid: bool) -> None:
        # Keep the venue's window. A level that falls out of it is not always
        # deleted by the venue and would come back as a phantom later.
        if self.depth and len(side) > self.depth + self.depth // 4:
            keep = heapq.nlargest(self.depth, side) if is_bid else heapq.nsmallest(self.depth, side)
            for px in set(side).difference(keep):
                self.set_level(side, px, 0)

    def best(self) -> tuple[float, float] | None:
        if not self.bids or not self.asks:
            return None
        return max(self.bids), min(self.asks)

    def top(self, n: int) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
        b = heapq.nlargest(n, self.bids)
        a = heapq.nsmallest(n, self.asks)
        return [(p, self.bids[p]) for p in b], [(p, self.asks[p]) for p in a]

    def crossed_too_long(self) -> bool:
        """Update the crossed-book count. True when a book that was uncrossed
        before has now been crossed CROSSED_LIMIT messages in a row."""
        bb = self.best()
        if bb is None:
            return False
        if bb[0] < bb[1]:
            self.crossed_n = 0
            self.sound = True
            return False
        self.crossed_n += 1
        return self.sound and self.crossed_n >= CROSSED_LIMIT

    def recordable(self) -> bool:
        return self.live and self.crossed_n == 0 and bool(self.bids) and bool(self.asks)


class ResyncGuard:
    def __init__(self, min_interval_s: float = 60, max_per_hour: int = 10, clock=time.monotonic):
        self.min_interval_s = min_interval_s
        self.max_per_hour = max_per_hour
        self.clock = clock
        self.history: dict[str, deque[float]] = {}
        self.given_up: set[str] = set()

    def allow(self, sym: str) -> bool:
        """May `sym` be resubscribed now? Records the attempt when it may."""
        if sym in self.given_up:
            return False
        now = self.clock()
        h = self.history.setdefault(sym, deque())
        while h and now - h[0] > 3600:
            h.popleft()
        if h and now - h[-1] < self.min_interval_s:
            return False
        if len(h) >= self.max_per_hour:
            self.given_up.add(sym)
            return False
        h.append(now)
        return True


class BookFeed:
    """One venue's books: the websocket session, resyncs, and the 5 s sample
    into `<source>/book20` with the same schema as Kraken and Binance."""

    name = ""           # stream name in status.json
    source = ""         # parquet source directory, also the venue key for quotes
    ws_url = ""
    depth: int | None = None

    def __init__(self, http: aiohttp.ClientSession | None, sinks: Sinks, state: State, bases: list[str]):
        self.http = http
        self.state = state
        self.bases = bases
        self.symbols: dict[str, str] = {}   # venue symbol -> base
        self.books: dict[str, L2Book] = {}
        self.guard = ResyncGuard()
        self.tbl = sinks.table(self.source, "book20", schemas.BOOK, heavy=True)
        self.st = state.stream(self.name)   # registered now, so a feed that never connects shows as stale
        self.ws: aiohttp.ClientWebSocketResponse | None = None
        self.pending: list[str] = []         # broken books to resubscribe, filled by handle()
        self.announced: set[str] = set()     # given-up symbols already logged

    # ---- venue specifics --------------------------------------------------

    async def load_symbols(self) -> dict[str, str]:
        raise NotImplementedError

    async def subscribe(self, symbols: list[str]) -> None:
        raise NotImplementedError

    async def unsubscribe(self, sym: str) -> None:
        raise NotImplementedError

    def handle(self, raw: str, recv: int) -> None:
        """Apply one message; a book that breaks goes through `self.fail`."""
        raise NotImplementedError

    def new_book(self) -> L2Book:
        return L2Book(self.depth)

    async def keepalive(self) -> None:
        """Application-level ping where the venue wants one. Default: none."""
        await asyncio.Event().wait()

    # ---- shared -----------------------------------------------------------

    def pick(self, bases_to_symbol: dict[str, str]) -> dict[str, str]:
        """Venue symbol -> base for every universe coin the venue lists; the rest is logged."""
        out = {bases_to_symbol[b]: b for b in self.bases if b in bases_to_symbol}
        missing = [b for b in self.bases if b not in bases_to_symbol]
        if missing:
            log.warning("not listed on %s, skipped: %s", self.name, missing)
        return out

    async def run(self) -> None:
        # Symbols load here, not in main: a venue whose REST API is down must
        # not stop Kraken and Binance from recording.
        while not self.symbols:
            try:
                self.symbols = await self.load_symbols()
                log.info("%s: %d books", self.name, len(self.symbols))
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self.st.errors += 1
                self.st.note = f"symbols: {type(e).__name__}: {e}"[:200]
                log.warning("%s: could not load symbols, retrying in 5 min: %s", self.name, self.st.note)
            if not self.symbols:
                await asyncio.sleep(300)
        await reconnecting(self.name, self.state, self._session, on_drop=self._invalidate)

    def _invalidate(self) -> None:
        for bk in self.books.values():
            bk.live = False

    async def _session(self) -> None:
        async with self.http.ws_connect(self.ws_url, heartbeat=30, max_msg_size=0) as ws:
            self.ws = ws
            self.pending.clear()
            await self.subscribe(sorted(self.symbols))
            log.info("%s connected, %d symbols", self.name, len(self.symbols))
            pinger = asyncio.create_task(self.keepalive())
            try:
                async for msg in ws:
                    if msg.type != aiohttp.WSMsgType.TEXT:
                        if msg.type in (aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSED):
                            break
                        continue
                    recv = now_us()
                    self.st.messages += 1
                    self.st.last_us = recv
                    self.handle(msg.data, recv)
                    while self.pending:
                        await self.resync(self.pending.pop())
            finally:
                pinger.cancel()
                self.ws = None
        raise ConnectionError("socket closed")

    def book(self, sym: str) -> L2Book:
        bk = self.books.get(sym)
        if bk is None:
            bk = self.books[sym] = self.new_book()
        return bk

    def fail(self, sym: str, bk: L2Book, what: str, verified: bool) -> None:
        """A check failed. Counted always; acted on only when that check has
        passed for this book before (`verified`)."""
        self.state.bump(f"{self.source}_{what}")
        if not verified:
            return
        bk.live = False
        bk.broken = True
        self.pending.append(sym)

    def after_update(self, sym: str, bk: L2Book, recv: int) -> None:
        """The crossed-book check every venue gets, and the latest quote."""
        if bk.crossed_too_long():
            self.fail(sym, bk, "crossed", verified=True)
            return
        bb = bk.best()
        if bb and bb[0] < bb[1]:
            self.state.quotes[(self.source, self.symbols.get(sym, sym))] = Quote(bb[0], bb[1], recv)

    async def resync(self, sym: str) -> None:
        if self.ws is None or self.ws.closed:
            return
        if not self.guard.allow(sym):
            if sym in self.guard.given_up and sym not in self.announced:
                self.announced.add(sym)
                self.state.bump(f"{self.source}_given_up")
                log.error("%s: %s broke %d times within an hour, not recorded until the next restart",
                          self.name, sym, self.guard.max_per_hour)
            return
        self.state.bump(f"{self.source}_resync")
        log.warning("%s: resubscribing %s", self.name, sym)
        await self.unsubscribe(sym)
        await self.subscribe([sym])

    async def maintain(self) -> None:
        """Retry books that broke while a resubscribe was not allowed yet."""
        for sym, bk in list(self.books.items()):
            if bk.broken and sym not in self.guard.given_up:
                await self.resync(sym)

    def sample(self, recv: int) -> int:
        n = 0
        for sym, bk in self.books.items():
            if not bk.recordable():
                continue
            b, a = bk.top(config.BOOK_DEPTH)
            self.tbl.add({
                "ts_recv_us": recv,
                "ts_exch_us": bk.ts_exch_us,
                "update_id": bk.update_id,
                "symbol": sym,
                "bid_px": [p for p, _ in b],
                "bid_qty": [q for _, q in b],
                "ask_px": [p for p, _ in a],
                "ask_qty": [q for _, q in a],
            })
            n += 1
        return n

    async def sample_loop(self) -> None:
        while True:
            await asyncio.sleep(config.BOOK_SAMPLE_S)
            try:
                await self.maintain()
            except Exception as e:  # a send on a dying socket; the session loop reconnects
                log.debug("%s maintain: %r", self.name, e)
            self.sample(now_us())
