"""The real-time pump.fun collector, a long-running service. PAPER ONLY, read only.

    python -m lab.pumpfun_rt.collector             run until stopped (the container's command)
    python -m lab.pumpfun_rt.collector --seconds 60 --dry-run    a minute, counts printed, nothing written

Source: a Solana RPC websocket, `logsSubscribe` with a `mentions` filter on the
pump.fun program and, on a second connection, on the PumpSwap program
(commitment "confirmed"). Both programs log their events as Anchor events
(see events.py); the collector decodes them, keeps what the study needs
(store.py) and drops failed transactions, duplicates (a transaction that
touches both programs arrives on both streams) and PumpSwap trades of pools
it did not see a token migrate into. The endpoint is PYTHIA_SOLANA_WS
(default: the public mainnet endpoint, which documents 40 connections, 100
requests per 10 s and 100 MB per 30 s per IP; this uses two connections, two
requests per connect and about 10 to 20 MB per 30 s).

Why not PumpPortal: its free data websocket carries token creations and
migrations, but trades of a token cost 0.01 SOL per 10,000 events and need an
API key tied to a funded wallet. This project holds no wallet, so that is out.
pump.fun's own frontend API is not used either: its terms forbid bots.

Resilience: each stream reconnects with exponential backoff (1 s to 60 s, with
jitter) and records a "gap" row (from, to) for the time it was down, so no
study mistakes missing data for a quiet market. Memory is bounded: the write
buffers flush every 60 s or at 50,000 rows, the duplicate filter keeps the last
200,000 signatures, the pool map at most 20,000 pools for 24 h, the metadata
queue 2,000 tokens (more are dropped, and counted).

Every 30 s the collector writes <data>/pumpfun_rt/heartbeat.json (connected
streams, messages, events per table, the last event time, reconnects,
dropped metadata). `lab.pumpfun_rt.health` reads it for the job table.

Metadata: a token's metadata uri (set at creation) is fetched once, at most
META_PER_S a second, only from public IPFS or Arweave gateways (never pump.fun,
never a host the creator picked otherwise), at most 64 KB, and reduced to
flags (twitter, telegram, website, description length, image) in the table
"meta" with the time it was known.

The live shadow book (live.py) gets every event as it is decoded; it is paper
arithmetic and cannot trade.
"""

from __future__ import annotations

import argparse
import asyncio
import collections
import json
import os
import random
import signal
import sys
import time
import urllib.parse

from . import events as E
from . import store

DEFAULT_WS = "wss://api.mainnet-beta.solana.com"
COMMITMENT = "confirmed"
HEARTBEAT_S = 30.0
SIG_KEEP = 200_000
POOLS_MAX = 20_000
MIGRATED_KEEP_H = 24
META_QUEUE = 2_000
META_PER_S = 2.0
META_MAX_BYTES = 64_000
META_HOSTS = ("ipfs.io", "dweb.link", "cf-ipfs.com", "nftstorage.link", "arweave.net", "gateway.pinata.cloud",
              "mypinata.cloud", "w3s.link", "4everland.io", "ipfs.dweb.link")
RECV_TIMEOUT_S = 90.0


def now_ms() -> int:
    return int(time.time() * 1000)


def meta_url(uri: str) -> str | None:
    """The uri if it is an https link to a public IPFS or Arweave gateway, an ipfs:// uri
    rewritten to ipfs.io, else None (nothing else is ever fetched)."""
    if not uri:
        return None
    if uri.startswith("ipfs://"):
        return "https://ipfs.io/ipfs/" + uri[7:].lstrip("/")
    try:
        u = urllib.parse.urlsplit(uri)
    except ValueError:
        return None
    host = (u.hostname or "").lower()
    if u.scheme != "https" or not host or "pump.fun" in host:
        return None
    if any(host == h or host.endswith("." + h) for h in META_HOSTS):
        return uri
    return None


def meta_flags(doc) -> dict:
    """Socials and description flags from a metadata document (any shape)."""
    if not isinstance(doc, dict):
        return {"ok": False}
    ext = doc.get("extensions") if isinstance(doc.get("extensions"), dict) else {}

    def has(*keys):
        for k in keys:
            v = doc.get(k) or ext.get(k)
            if isinstance(v, str) and v.strip():
                return True
        return False
    desc = doc.get("description")
    return {"ok": True, "twitter": has("twitter", "x"), "telegram": has("telegram"),
            "website": has("website"), "desc_len": len(desc) if isinstance(desc, str) else 0,
            "image": has("image")}


class Collector:
    """Decodes stream messages into the store and hands each kept row to `on_row`."""

    def __init__(self, writer: store.Writer | None, on_row=None, amm: bool = True, meta: bool = True):
        self.writer = writer
        self.on_row = on_row
        self.amm = amm
        self.meta = meta
        self.sigs: collections.OrderedDict[str, None] = collections.OrderedDict()
        self.pools: dict[str, tuple[str, int]] = {}
        self.tx = 0
        self.counts: collections.Counter = collections.Counter()
        self.last_event_ms = 0
        self.connected: dict[str, bool] = {}
        self.reconnects = 0
        self.meta_q: asyncio.Queue | None = None
        self.started_ms = now_ms()

    # ------------------------------------------------------------ decoding
    def handle(self, text: str, recv_ms: int) -> int:
        """One websocket message. Returns the number of rows kept."""
        try:
            d = json.loads(text)
        except ValueError:
            self.counts["bad_json"] += 1
            return 0
        params = d.get("params") if isinstance(d, dict) else None
        if not params:
            if isinstance(d, dict) and d.get("error"):
                self.counts["rpc_error"] += 1
                print(f"collector: rpc error {d.get('error')}", file=sys.stderr)
            return 0
        res = params.get("result") or {}
        v = res.get("value") or {}
        slot = (res.get("context") or {}).get("slot") or 0
        self.counts["messages"] += 1
        if v.get("err") is not None:
            self.counts["failed_tx"] += 1
            return 0
        sig = v.get("signature") or ""
        if sig in self.sigs:
            self.counts["duplicate"] += 1
            return 0
        self.sigs[sig] = None
        if len(self.sigs) > SIG_KEEP:
            self.sigs.popitem(last=False)
        evs = E.events_of(v.get("logs") or [])
        if not evs:
            return 0
        self.tx += 1
        kept = 0
        for name, ev in evs:
            c = E.compact(name, ev, recv_ms, slot, self.tx, sig if name == "CreateEvent" else "")
            if c is None:
                continue
            table, row = c
            if table == "amm":
                hit = self.pools.get(row["pool"])
                if hit is None or recv_ms - hit[1] > MIGRATED_KEEP_H * 3_600_000:
                    continue
                row["mint"] = hit[0]
            elif table == "other" and row["kind"] == "migrate":
                self.remember_pool(row["pool"], row["mint"], recv_ms)
            kept += self.keep(table, row)
            if table == "creates" and self.meta:
                self.queue_meta(row)
        if kept:
            self.last_event_ms = recv_ms
        return kept

    def keep(self, table: str, row: dict) -> int:
        self.counts[table] += 1
        if self.writer is not None:
            self.writer.add(table, row)
        if self.on_row is not None:
            try:
                self.on_row(table, row)
            except Exception as e:                        # the shadow book never stops the collector
                self.counts["shadow_error"] += 1
                if self.counts["shadow_error"] <= 5:
                    print(f"collector: shadow book error {type(e).__name__}: {e}", file=sys.stderr)
        return 1

    def remember_pool(self, pool: str, mint: str, ms: int) -> None:
        self.pools[pool] = (mint, ms)
        if len(self.pools) > POOLS_MAX:
            cut = ms - MIGRATED_KEEP_H * 3_600_000
            self.pools = {k: v for k, v in self.pools.items() if v[1] >= cut}
            while len(self.pools) > POOLS_MAX:
                self.pools.pop(next(iter(self.pools)))

    def gap(self, program: str, t0: int, t1: int) -> None:
        if t1 - t0 < 1000:
            return
        self.counts["gaps"] += 1
        self.keep("other", {"kind": "gap", "t": t1, "slot": None, "tx": None, "mint": None, "user": program,
                            "pool": None, "sol": None, "tok": None, "t0": t0})

    # ------------------------------------------------------------ metadata
    def queue_meta(self, row: dict) -> None:
        if self.meta_q is None:
            return
        url = meta_url(row.get("uri") or "")
        if url is None:
            self.counts["meta_skipped"] += 1
            return
        try:
            self.meta_q.put_nowait((row["mint"], url))
        except asyncio.QueueFull:
            self.counts["meta_dropped"] += 1

    async def meta_worker(self, session) -> None:
        import aiohttp
        gap = 1.0 / META_PER_S
        while True:
            mint, url = await self.meta_q.get()
            t0 = time.monotonic()
            flags = {"ok": False}
            try:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10), allow_redirects=False,
                                       headers={"User-Agent": "pythia-lab (paper research, read only)"}) as r:
                    if r.status == 200:
                        raw = await r.content.read(META_MAX_BYTES + 1)
                        if len(raw) <= META_MAX_BYTES:
                            flags = meta_flags(json.loads(raw.decode("utf-8", "replace")))
                    elif r.status == 429:
                        self.counts["meta_429"] += 1
                        await asyncio.sleep(30)
            except (asyncio.TimeoutError, aiohttp.ClientError, ValueError, UnicodeError, OSError):
                pass
            self.counts["meta_fetched"] += 1
            self.keep("meta", {"t": now_ms(), "mint": mint, **flags})
            await asyncio.sleep(max(0.0, gap - (time.monotonic() - t0)))

    # ------------------------------------------------------------ streams
    async def stream(self, session, url: str, program: str, stop: asyncio.Event) -> None:
        import aiohttp
        backoff = 1.0
        down_since = None
        while not stop.is_set():
            try:
                async with session.ws_connect(url, heartbeat=30, max_msg_size=16 << 20, compress=0) as ws:
                    await ws.send_str(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "logsSubscribe",
                                                  "params": [{"mentions": [program]}, {"commitment": COMMITMENT}]}))
                    self.connected[program] = True
                    if down_since is not None:
                        self.gap(program, down_since, now_ms())
                    first = True
                    while not stop.is_set():
                        try:
                            msg = await asyncio.wait_for(ws.receive(), timeout=RECV_TIMEOUT_S)
                        except asyncio.TimeoutError:
                            print(f"collector: {program[:4]} silent for {RECV_TIMEOUT_S:.0f} s, reconnecting",
                                  file=sys.stderr)
                            break
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            self.handle(msg.data, now_ms())
                            if first:
                                backoff, first = 1.0, False
                        elif msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED,
                                          aiohttp.WSMsgType.CLOSING, aiohttp.WSMsgType.ERROR):
                            print(f"collector: {program[:4]} closed ({msg.type.name} {msg.data})", file=sys.stderr)
                            break
            except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as e:
                print(f"collector: {program[:4]} {type(e).__name__}: {e}", file=sys.stderr)
            if self.connected.get(program):
                down_since = now_ms()
            elif down_since is None:
                down_since = now_ms()
            self.connected[program] = False
            if stop.is_set():
                break
            self.reconnects += 1
            await asyncio.sleep(backoff * (0.5 + random.random()))
            backoff = min(60.0, backoff * 2)

    def heartbeat(self) -> dict:
        return {"t": now_ms(), "started_ms": self.started_ms, "connected": dict(self.connected),
                "last_event_ms": self.last_event_ms, "reconnects": self.reconnects, "counts": dict(self.counts),
                "pools": len(self.pools), "rows_written": self.writer.rows_written if self.writer else 0,
                "last_write_ms": self.writer.last_write_ms if self.writer else 0,
                "meta_queue": self.meta_q.qsize() if self.meta_q is not None else None}


async def run(seconds: float | None = None, dry_run: bool = False) -> dict:
    import aiohttp
    url = os.environ.get("PYTHIA_SOLANA_WS") or DEFAULT_WS
    amm = os.environ.get("PYTHIA_PF_AMM", "1") != "0"
    meta = os.environ.get("PYTHIA_PF_META", "1") != "0" and not dry_run
    writer = None if dry_run else store.Writer()
    shadow = None
    if not dry_run and os.environ.get("PYTHIA_PF_SHADOW", "1") != "0":
        from .live import Shadow
        shadow = Shadow.load()
    col = Collector(writer, shadow.on_row if shadow else None, amm=amm, meta=meta)
    hb = store.base() / "heartbeat.json"
    if writer is not None:
        try:                                              # the time the collector was not running is a gap
            last = json.loads(hb.read_text(encoding="utf-8")).get("last_event_ms") or 0
            if last:
                col.gap(E.PUMP, last, now_ms())
                if amm:
                    col.gap(E.PUMP_AMM, last, now_ms())
        except (OSError, ValueError):
            pass
        try:
            for k, v in json.loads((store.base() / "pools.json").read_text(encoding="utf-8")).items():
                col.pools[k] = (v[0], int(v[1]))
        except (OSError, ValueError, TypeError, IndexError):
            pass
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for s in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(s, stop.set)
        except (NotImplementedError, RuntimeError):
            pass
    if meta:
        col.meta_q = asyncio.Queue(maxsize=META_QUEUE)
    t_end = time.monotonic() + seconds if seconds else None
    last_hb = last_prune = 0.0
    async with aiohttp.ClientSession() as session:
        tasks = [asyncio.create_task(col.stream(session, url, E.PUMP, stop))]
        if amm:
            tasks.append(asyncio.create_task(col.stream(session, url, E.PUMP_AMM, stop)))
        if meta:
            tasks.append(asyncio.create_task(col.meta_worker(session)))
        print(f"collector: streaming {'pump.fun and PumpSwap' if amm else 'pump.fun'} logs, "
              f"{'dry run' if dry_run else 'writing to ' + str(store.base())}", flush=True)
        try:
            while not stop.is_set():
                await asyncio.sleep(1.0)
                if shadow is not None:
                    shadow.tick(now_ms())
                if writer is not None and writer.due():
                    batches = writer.take()
                    await asyncio.to_thread(writer.write, batches)
                mono = time.monotonic()
                if mono - last_hb >= HEARTBEAT_S:
                    last_hb = mono
                    beat = col.heartbeat()
                    if shadow is not None:
                        beat["shadow"] = shadow.status()
                    if writer is not None:
                        await asyncio.to_thread(store.write_json, hb, beat)
                        await asyncio.to_thread(store.write_json, store.base() / "pools.json",
                                                {k: list(v) for k, v in col.pools.items()})
                        if shadow is not None:
                            await asyncio.to_thread(shadow.save)
                    else:
                        print(json.dumps(beat), flush=True)
                if writer is not None and mono - last_prune >= 3600:
                    last_prune = mono
                    gone = await asyncio.to_thread(store.prune)
                    if gone:
                        print(f"collector: over the size budget, deleted {', '.join(gone)}", flush=True)
                if t_end is not None and mono >= t_end:
                    stop.set()
        finally:
            stop.set()
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            if writer is not None:
                writer.flush()
                store.write_json(hb, col.heartbeat())
            if shadow is not None:
                shadow.save()
    return col.heartbeat()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--seconds", type=float, default=None, help="stop after this many seconds")
    ap.add_argument("--dry-run", action="store_true", help="count only, write nothing")
    a = ap.parse_args(argv)
    beat = asyncio.run(run(a.seconds, a.dry_run))
    print(json.dumps(beat, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
