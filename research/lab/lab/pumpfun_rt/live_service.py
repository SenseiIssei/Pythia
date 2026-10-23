"""The live pump.fun service: the one process that may trade real money. Started by the owner, by hand.

    python -m lab.pumpfun_rt.live_service             run until stopped (a long-running container)
    python -m lab.pumpfun_rt.live_service --once      check the gate, write the status once, exit

It is not a job and nothing starts it automatically (docs/PUMPFUN-LIVE.md and
research/ops/README.md, "Live trading"). It streams the same two programs as
the collector over its own connections, keeps no record of the market and runs
no paper book: an engine with the live book only (live_exec.attach), which is
there only when every gate of the live executor holds at start. With any gate
shut it still runs, trades nothing, and keeps the app's status current (the
reasons, the wallet's public address and balance), so the owner can see what is
missing; after fixing it, restart the service.

Every STATUS_S it writes, for the engine's read-only endpoints and the app:
  reports/pumpfun_rt/live_status.json   mode, on or off and why, address, SOL balance (getBalance),
                                        token holdings, open positions, today's and the total P&L,
                                        the ack's and the effective limits, the stake the wallet allows
                                        and why (sizing.py), the stops, the kill switch
  reports/pumpfun_rt/live_trades.json   the newest closed live trades
  reports/pumpfun_rt/execution.json     measured latency, slippage, fees against the paper model
                                        (measure.py; every ten minutes and with the daily card)
and at once when a position opens, changes or closes (the balance read again first). Every
second, when something moved, it writes
  reports/pumpfun_rt/live_feed.json     every trade on the coins the bot holds or just closed,
                                        for the app's live chart (live_feed.py)
With the owner's speed setting PYTHIA_PUMPFUN_WAKE (or PYTHIA_PUMPFUN_FAST) a result of the executor's
threads wakes the loop at once instead of at the next second (docs/LATENCY.md).
It reads reports/pumpfun_rt/live_settings.json (the app's lower limits) every
minute and reports/pumpfun_rt/control.json (the owner's share and pause from the app, live_exec.Control)
every 2 s; a change is in the status at once. It never opens the wallet file itself (live_exec does, once, after
every gate holds); it never sends money anywhere.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import sys
import time

from . import events as E
from . import live_exec as LX
from . import store
from .live_feed import LiveFeed

STATUS_S = 30.0
BALANCE_S = 30.0
HOLDINGS_S = 300.0
REPORT_S = 600.0
WARM_H = 12                                             # coins created this long before a start are adopted
LINKS = max(1, int(os.environ.get("PYTHIA_PF_LIVE_LINKS", "2")))
AMM_LINKS = max(1, int(os.environ.get("PYTHIA_PF_LIVE_AMM_LINKS", "2")))


def load_engine():
    """An engine with no rules and no paper books; the creator and wallet books and the categories
    as the collector last saved them (read only), for strategies whose filters need them."""
    from .live import paper_dir
    from .model import load
    from .sim import Engine
    from .tokens import CreatorBook
    from . import wallets as W
    book = wallets = cats = None
    try:
        book = CreatorBook.from_json(json.loads((paper_dir() / "creators.json").read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass
    try:
        wallets = W.WalletBook.from_json(json.loads((paper_dir() / "wallets.json").read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass
    try:
        from .categorize import BOOK_DAYS, CategoryIndex
        cats = CategoryIndex.load(mints=False, max_age_days=BOOK_DAYS)
    except Exception:
        cats = None
    models = {}
    try:
        models = load()
    except Exception:
        pass
    return Engine([], book=book, wallets=wallets, cats=cats, models=models, decisions=False)


def warm_tokens(engine, now_ms: int, hours: float = WARM_H, root=None) -> int:
    """Adopt every coin the collector recorded as created in the last `hours`: the engine only knows coins
    it saw created, so after a restart it would not see the migration of an older one (P_pool0 buys at
    the migration, mostly of coins made hours before). Returns how many were adopted."""
    import datetime as dt
    days = sorted({(dt.datetime.fromtimestamp(now_ms / 1000, dt.timezone.utc) - dt.timedelta(hours=h))
                   .strftime("%Y-%m-%d") for h in (hours, 0)})
    df = store.read("creates", days, root)
    if df.is_empty():
        return 0
    df = df.filter(df["t"] >= now_ms - int(hours * 3_600_000)).sort("t")
    return sum(1 for r in df.iter_rows(named=True) if engine.adopt(r, now_ms))


class Service:
    def __init__(self, gate: LX.LiveGate | None = None, engine=None, rpc=None, attach=LX.attach,
                 alerts: bool = True, start_worker: bool = True):
        self.gate = gate or LX.LiveGate()
        self.engine = engine
        self.rpc = rpc
        self._attach = attach
        self.alerts = alerts
        self.start_worker = start_worker
        self.book: LX.LiveBook | None = None
        self.why: list[str] = []
        self.address: str | None = None
        self.balance_l: int | None = None
        self.balance_t: int | None = None
        self.holdings: dict | None = None
        self.holdings_t: int | None = None                  # when the holdings above were read (wall ms)
        self.last = {"balance": -1e18, "holdings": -1e18, "report": -1e18, "gate": -1e18}
        self.feed = LiveFeed()
        self.feed_status: dict | None = None
        self.book_sig = None
        self.feed_err = False
        self.wake: asyncio.Event | None = None              # speed.wake: a worker result ends the wait at once

    def arm_wake(self, loop) -> bool:
        """With the owner's speed setting `wake`: every result of the executor's threads (a send's answer, a
        confirmation, a read) wakes the loop at once instead of at the next second. Nothing else changes."""
        if self.book is None or not getattr(self.book.exec.speed, "wake", False):
            return False
        self.wake = asyncio.Event()
        self.book.exec.on_result = lambda: loop.call_soon_threadsafe(self.wake.set)
        return True

    async def pause(self, most_s: float = 1.0) -> None:
        """The loop's wait: a second, or until a result or the executor's next timer (a sale's retry)."""
        if self.wake is None:
            await asyncio.sleep(most_s)
            return
        nxt = self.book.exec.next_wake_ms()
        if nxt is not None:
            most_s = max(0.01, min(most_s, (nxt - time.time() * 1000) / 1000))
        try:
            await asyncio.wait_for(self.wake.wait(), most_s)
        except asyncio.TimeoutError:
            pass
        self.wake.clear()

    def start(self) -> None:
        if self.engine is None:
            self.engine = load_engine()
        self.why = self.gate.check()
        self.address = self.gate.address
        if not self.why:
            try:
                self.book = self._attach(self.engine, self.gate, rpc=self.rpc, alerts=self.alerts,
                                         start=self.start_worker)
            except Exception as e:                          # e.g. an unreadable wallet file: nothing trades
                self.book = None
                self.why = [f"the live book could not start ({type(e).__name__})"]
            if self.book is not None:
                try:
                    n = warm_tokens(self.engine, int(time.time() * 1000))
                    print(f"live service: {n:,} coins from the last {WARM_H} h adopted, their migrations count",
                          flush=True)
                except Exception as e:                      # without them it still trades the coins it sees made
                    print(f"live service: older coins not adopted ({type(e).__name__}: {e})", flush=True)
                self.rpc = self.book.exec.builder.rpc
                self.address = self.book.exec.signer.pubkey
                self.refresh_holdings()
                self.book.adopt_leftovers(self.holdings)
        if self.book is None:
            print("live service: nothing trades. Why:\n  - " + "\n  - ".join(self.why or ["see the log above"])
                  + "\nFix it and restart the service.", flush=True)
        if self.rpc is None:
            try:
                self.rpc = LX.Rpc(self.gate.env.get(LX.ENV_RPC) or LX.DEFAULT_RPC)
            except ValueError as e:
                print(f"live service: no RPC for the balance ({e})", flush=True)

    # ------------------------------------------------------------ the stream
    def on_row(self, table: str, row: dict) -> None:
        if self.book is None:
            return
        from .sim import feed_row
        feed_row(self.engine, table, row)
        try:
            self.feed.observe(table, row, self.engine)
        except Exception as e:                              # the chart's problem, never the book's
            self._feed_failed(e)

    def _feed_failed(self, e: Exception) -> None:
        if not self.feed_err:
            self.feed_err = True
            print(f"live service: live feed {type(e).__name__}: {e}", flush=True)

    def tick(self, now_ms: int) -> None:
        if self.book is None:
            if time.monotonic() - self.last["gate"] >= LX.RECHECK_S:   # the reasons stay current for the app
                self.last["gate"] = time.monotonic()
                self.why = self.gate.check()
            return
        self.engine.advance(now_ms)
        for pipe in self.engine.pipes:
            pipe.poll(now_ms)
        self.book.tick(now_ms)

    def book_changed(self) -> bool:
        """A position opened, changed state or closed since the last call."""
        if self.book is None or self.book.pipe is None:
            return False
        recent = self.book.recent[0] if self.book.recent else {}
        sig = (tuple(sorted((p["pid"], p.get("state"), p.get("left")) for p in self.book.pipe.pos.values())),
               len(self.book.recent), recent.get("exit_ms"), tuple(sorted(self.book.exec.leftovers)),
               tuple(sorted(self.book.control.good.items())), self.book.control.ok)   # the owner's controls too
        changed, self.book_sig = sig != self.book_sig, sig
        return changed

    def feed_tick(self, now_ms: int) -> None:
        if self.book is None:
            return
        try:
            self.feed.sync(self.book, now_ms)
            st = self.light_status()
            if self.feed.dirty or st != self.feed_status:          # a trade on a held coin, the wallet, the P&L
                self.feed.dirty, self.feed_status = False, st
                LX.write_json(LX.reports_dir() / "live_feed.json", self.feed.snapshot(st))
        except Exception as e:
            self._feed_failed(e)

    def light_status(self) -> dict:
        ex = self.book.exec
        return {"on": ex.closed_why is None and ex.paused_ms is None, "balance_sol": None if self.balance_l is None else self.balance_l / 1e9,
                "balance_t": self.balance_t, "pnl_today_sol": ex.day_pnl_l / 1e9, "trades_today": ex.trades_today,
                "wins_today": ex.wins_today, "pnl_total_sol": ex.totals["pnl_l"] / 1e9,
                "trades_total": ex.totals["trades"], "exposure_sol": sum(ex.exposure.values()) / 1e9}

    # ------------------------------------------------------------ the wallet, read only
    def refresh_balance(self) -> None:
        if self.rpc is None or not self.address:
            return
        try:
            self.balance_l = self.rpc.balance(self.address)
            self.balance_t = int(time.time() * 1000)
            if self.book is not None:
                self.book.exec.balance_l = self.balance_l
        except Exception as e:
            print(f"live service: balance not read ({type(e).__name__}: {e})", flush=True)

    def refresh_holdings(self) -> None:
        """The wallet's tokens. A failed read keeps the last snapshot for the app, but not its time: the
        orphan check acts only on a read younger than a minute (live_exec.HOLDINGS_FRESH_MS)."""
        if self.rpc is None or not self.address:
            return
        try:
            self.holdings = self.rpc.holdings(self.address)
            self.holdings_t = int(time.time() * 1000)
        except Exception as e:
            print(f"live service: token holdings not read ({type(e).__name__}: {e})", flush=True)

    def periodic(self) -> None:
        """The slow, blocking part (RPC reads, the execution report): run off the stream's loop.
        It touches no book state; save() runs on the loop afterwards."""
        mono = time.monotonic()
        if mono - self.last["balance"] >= BALANCE_S:
            self.last["balance"] = mono
            self.refresh_balance()
        if mono - self.last["holdings"] >= HOLDINGS_S:
            self.last["holdings"] = mono
            self.refresh_holdings()
        if self.book is not None and mono - self.last["report"] >= REPORT_S:
            self.last["report"] = mono
            try:
                from . import measure
                measure.write_report()
            except Exception as e:
                print(f"live service: execution report not written ({type(e).__name__}: {e})", flush=True)

    # ------------------------------------------------------------ files
    def status(self) -> dict:
        if self.book is not None:
            return self.book.status(self.address, self.balance_t, self.holdings, self.why)
        return LX.base_status(self.gate, self.why, self.address, self.balance_l, self.balance_t, self.holdings)

    def save(self) -> None:
        d = LX.reports_dir()
        LX.write_json(d / "live_status.json", self.status())
        trades = self.book.recent if self.book is not None else LX.read_ledger(100)
        LX.write_json(d / "live_trades.json", {"t": int(time.time() * 1000), "trades": trades})
        if self.book is not None:
            if self.holdings_t is not None:               # a buy that landed after it was given up
                self.book.adopt_orphans(self.holdings, int(time.time() * 1000), read_ms=self.holdings_t)
            self.book.save_open()

    def stopped(self) -> None:
        """The service is going down: the app sees it as not running."""
        try:
            st = self.status()
            st.update(running=False, on=False, refusing="the live service stopped")
            LX.write_json(LX.reports_dir() / "live_status.json", st)
            if self.book is not None:
                self.book.save_open()
        except Exception as e:
            print(f"live service: final status not written ({type(e).__name__}: {e})", flush=True)


def feed_links(urls: list[str]) -> list[tuple[str, str, int]]:
    """(url, program, link) per stream link, spread over the feeds like collector.run: link k of each program
    on urls[k % len(urls)], so link 0 of both programs goes to the first provider."""
    return [(urls[k % len(urls)], p, k) for p in (E.PUMP, E.PUMP_AMM)
            for k in range(LINKS if p == E.PUMP else AMM_LINKS)]


def feeds_line(urls: list[str]) -> str:
    """The start line naming the feeds: scheme and host only, never a path, query or key."""
    from .latency import safe_url
    return "live service: feeds " + ", ".join(safe_url(u) for u in urls)


async def run(seconds: float | None = None, once: bool = False) -> int:
    svc = Service()
    svc.start()
    if once:
        await asyncio.to_thread(svc.periodic)
        svc.save()
        print(json.dumps({k: svc.status()[k] for k in ("mode", "rule", "on", "address", "balance_sol", "gate")},
                         indent=1), flush=True)
        return 0
    import aiohttp
    from .collector import Collector, feed_urls
    urls = feed_urls()                                       # the owner's providers first, the public one as fallback
    col = Collector(None, svc.on_row, amm=True, meta=False)
    try:                                                     # pools the collector saw migrate (read only)
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
    t_end = time.monotonic() + seconds if seconds else None
    last = beat = 0.0
    woken = svc.arm_wake(loop)
    async with aiohttp.ClientSession() as session:
        tasks = []
        if svc.book is not None:                             # nothing to stream for a book that is not there
            tasks = [asyncio.create_task(col.stream(session, u, p, k, stop)) for u, p, k in feed_links(urls)]
            print(feeds_line(urls), flush=True)
        print(f"live service: {'streaming' if tasks else 'status only'}", flush=True)
        try:
            while not stop.is_set():
                await svc.pause(1.0)
                svc.tick(col.clock.latest or int(time.time() * 1000))
                mono = time.monotonic()
                if woken and mono - beat < 0.95:
                    continue                               # woken early: the results are handled, the rest keeps its second
                beat = mono
                if svc.book_changed():                     # a fill or a close: the app sees it at once
                    svc.last["balance"] = -1e18
                    last = -1e18
                svc.feed_tick(int(time.time() * 1000))
                if mono - last >= STATUS_S:
                    last = mono
                    await asyncio.to_thread(svc.periodic)
                    try:
                        svc.save()                         # on the loop: no stream event changes the book meanwhile
                    except OSError as e:
                        print(f"live service: status not written ({e})", flush=True)
                if t_end is not None and mono >= t_end:
                    stop.set()
        finally:
            stop.set()
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            svc.stopped()
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="the live pump.fun service (started by the owner, by hand)")
    ap.add_argument("--seconds", type=float, default=None, help="stop after this many seconds")
    ap.add_argument("--once", action="store_true", help="check the gate, write the status once, exit")
    a = ap.parse_args(argv)
    return asyncio.run(run(a.seconds, a.once))


if __name__ == "__main__":
    sys.exit(main())
