"""Entry point: python -m recorder"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
from datetime import datetime, timezone

import aiohttp

from . import config
from .binance import BinanceFutures, BinanceSpotBook, load_symbols
from .kraken import KrakenFeed, load_pairs
from .sink import Sinks, now_us
from .spread import SpreadLogger
from .state import State

log = logging.getLogger("recorder")
started_us = now_us()
STALE_S = 120
# Liquidations only arrive when someone gets liquidated; a quiet night is normal.
STALE_OVERRIDE_S = {"binance_liq": 1800}


def status(state: State, sinks: Sinks) -> dict:
    now = now_us()
    streams = {}
    for name, s in state.streams.items():
        limit = STALE_OVERRIDE_S.get(name, STALE_S)
        age = (now - (s.last_us or started_us)) / 1e6
        streams[name] = {
            "messages": s.messages, "age_s": round(age, 1),
            "stale": age > limit, "reconnects": s.reconnects,
            "errors": s.errors, "last_error": s.note,
        }
    return {
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "ok": all(not v["stale"] for v in streams.values()),
        "disk_free_gb": round(sinks.free_gb(), 1),
        "heavy_tables": "on" if sinks.heavy_allowed else "paused (low disk)",
        "streams": streams,
        "counters": state.counters,
        "tables": {k: {"written": t.written, "buffered": len(t.rows), "dropped": t.dropped}
                   for k, t in sinks.tables.items()},
    }


async def health_loop(state: State, sinks: Sinks) -> None:
    path = config.DATA_ROOT / "_health" / "status.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    while True:
        await asyncio.sleep(60)
        s = status(state, sinks)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(s, indent=2))
        os.replace(tmp, path)
        stale = [k for k, v in s["streams"].items() if v["stale"]]
        log.info("health ok=%s free=%.0fGB stale=%s written=%d",
                 s["ok"], s["disk_free_gb"], stale or "-",
                 sum(t["written"] for t in s["tables"].values()))


async def compact_loop(sinks: Sinks) -> None:
    while True:
        try:
            await asyncio.to_thread(sinks.compact_finished_days)
        except Exception:
            log.exception("compaction failed, parts stay as they are")
        await asyncio.sleep(3600)


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    config.DATA_ROOT.mkdir(parents=True, exist_ok=True)
    state = State()
    sinks = Sinks(config.DATA_ROOT, config.MIN_FREE_GB)

    timeout = aiohttp.ClientTimeout(total=30, sock_connect=10)
    async with aiohttp.ClientSession(timeout=timeout, headers={"User-Agent": "pythia-recorder/1"}) as http:
        pairs = await load_pairs(http, config.UNIVERSE)
        spot, perp = await load_symbols(http, config.UNIVERSE)
        bases = [b for b in config.UNIVERSE if f"{b}/USD" in pairs and b in spot]
        log.info("universe: %d cross-venue bases, %d kraken books, %d binance books, %d perps",
                 len(bases), len(pairs), len(spot), len(perp))

        kraken = KrakenFeed(http, sinks, state, pairs)
        bspot = BinanceSpotBook(http, sinks, state, spot)
        bfut = BinanceFutures(http, sinks, state, perp)
        spread = SpreadLogger(sinks, state, bases)

        tasks = [asyncio.create_task(c, name=n) for n, c in [
            ("kraken", kraken.run()), ("kraken_sample", kraken.sample_loop()),
            ("binance_spot", bspot.run()), ("binance_sample", bspot.sample_loop()),
            ("binance_futures", bfut.poll_loop()), ("binance_liq", bfut.liquidations()),
            ("spread", spread.run()),
            ("flush", sinks.flush_loop(config.FLUSH_S)),
            ("health", health_loop(state, sinks)), ("compact", compact_loop(sinks)),
        ]]

        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(sig, stop.set)
            except NotImplementedError:  # Windows dev runs
                pass

        done_task = asyncio.create_task(stop.wait())
        done, _ = await asyncio.wait([done_task, *tasks], return_when=asyncio.FIRST_COMPLETED)
        for t in done:
            if t is not done_task and t.exception():
                log.error("task %s crashed: %r", t.get_name(), t.exception())
        log.info("shutting down, flushing buffers")
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await sinks.flush()
        log.info("bye")


if __name__ == "__main__":
    asyncio.run(main())
