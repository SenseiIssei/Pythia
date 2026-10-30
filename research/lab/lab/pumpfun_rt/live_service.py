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

Decisions as the paper book's on the same events: a copy of a transaction with fewer log lines than a later one
(a provider next to the public endpoint) does not hide the later one's events (LiveCollector); a row of a coin the
engine does not know yet waits HOLD_MS for the coin's creation (the links race: a coin made and migrated in one
slot often has its migration first); the coins the collector wrote after the start are adopted once more after
REWARM_S. Every coin the live strategy does not buy has its reason in the status ("skipped") and one log line
(live_exec.LiveBook.on_skip, data/live/pumpfun_rt/skipped.jsonl). The paper books hold the same way (live.Hold).

What it saw (2026-10-23: two paper entries had no live record at all): every migration its stream hands it is
written once to data/live/pumpfun_rt/seen.jsonl, so a paper entry the live book did not take is either "never seen
by the live service" or has its reason; a migration of a pool strategy still without a buy or a reason NO_DECISION_S
after it came is a skip "no decision" with its log line (a bug, made visible); a row the engine fails on is logged
with its coin (the collector's own guard printed five and then nothing). A "no pool state" while every PumpSwap
link of the service was down says so (Pipeline.feed_down).

Its own latency (measure.py, "Per step, by day"): every row keeps its message's receive time, and an order carries
the receive time of the row that decided it and when the engine took that row (after a wait for the creation); the
gate's files and a new day are read on the tick, not at a signal; with prefetch a migration's pool accounts are read
as the migration comes in (LiveExecutor.warm_pool), so the pool buy builds without a read. The loop itself is idle
nearly all the time (a recorded day's rows cost about 0.04 % of it); what is left of signal to order is the
stream delivering the deciding event late, and the wait for a coin's creation.

Missing data (P2, 2026-10-28: about 170 decisions lost): each migration's pool is read from the chain as the
collector does (F1, poolread.py), so "no pool state" no longer waits on the stream for a pool trade; and every
second the coins the collector's own links saw created are adopted from its tap file (F2, collector.TapReader),
so a migration whose creation our links missed is not skipped for "creation not seen" while the collector has it.

The owner's provider (PYTHIA_SOLANA_WS_URLS, metered by data volume: the PumpSwap firehose alone burned its free
month in about 11 hours) is used only for the coins that matter (ProviderWatch): the program-wide links stream from
the public endpoint (PYTHIA_PF_PROVIDER_FIREHOSE=1 puts link 0 of each program on the provider again), and one
provider connection keeps a logsSubscribe on the pool (or bonding curve) of every coin the strategy waits on, holds
or has an order in flight for, at most PYTHIA_PF_PROVIDER_MAX_SUBS (20; the oldest watched coin goes first, a held
one never), unsubscribed as the coin is dropped, sold or its wait ends. Its events take the same path (the first
copy counts, by signature). Above PYTHIA_PF_PROVIDER_MB_DAY (40) received in a UTC day only held coins keep theirs
until 00:00 UTC, the status says so. Per transaction that came over both, which was first and by how many ms, and
the bytes per day go to data/live/pumpfun_rt/provider.json (latency.md, "provider vs public, watched coins").
Several providers (PYTHIA_SOLANA_WS_URLS, full URLs, comma separated) run side by side (Providers): one connection
each with the same subscriptions, the first copy by signature wins, the budget per provider; one that refuses its
first subscription (no logsSubscribe with mentions on its plan) is benched for the session, one that errors, refuses
later or runs out until its reconnect or 00:00 UTC, and the others carry on; latency.md has a row per provider.

Pool record (PoolRecord, the owner, 2026-10-30): every migrated pool's trades of its first PYTHIA_PF_LIVE_RECORD_S
(600) seconds, as this service took them and from which feed, go to data/live/pumpfun_rt/record/<day>.jsonl.gz for
the lab, since the collector's public links lose some coins entirely. Paper data: nothing here trades on it.

Name categories (livecat.py, the owner, 2026-10-23): every 30 s the new plain coins the stream saw created are
classified (the daily job's prompt, chunks and checks, the engine's metered endpoint and budget) into the same
cats.jsonl; the live strategy skips a coin of a blocked category (blocklist category: lines, celebrity, copycat and
scam by default) with "category celebrity" etc., and one that reaches the buy without a category is asked alone at
once (at most 1.5 s, the loop waits) or skipped "category unknown". The status's "categories" shows the classifier,
the blocked codes and the day's cost.
"""

from __future__ import annotations

import argparse
import asyncio
import collections
import json
import os
import signal
import sys
import time

from . import events as E
from . import live_exec as LX
from . import pipeline as P
from . import store
from .collector import COMMITMENT, DEFAULT_WS, Collector
from .live import HOLD_MS, HOLD_TABLES, Hold                # noqa: F401 - HOLD_* as before, for the tests
from .live_feed import LiveFeed

STATUS_S = 30.0
BALANCE_S = 30.0
HOLDINGS_S = 300.0
REPORT_S = 600.0
WARM_H = 12                                             # coins created this long before a start are adopted
LINKS = max(1, int(os.environ.get("PYTHIA_PF_LIVE_LINKS", "2")))
AMM_LINKS = max(1, int(os.environ.get("PYTHIA_PF_LIVE_AMM_LINKS", "2")))
NO_DECISION_S = HOLD_MS / 1000 + 30                     # a seen migration without a buy or a reason by then: a skip
SEEN_KEEP = 5_000
ERRORS_SHOWN = 20
TRUNCATED = "Log truncated"                             # the runtime's last line when a transaction's logs were cut
REWARM_S = 90.0                                         # the collector writes every 60 s: adopt once more after that
PROVIDER_MAX_SUBS = max(1, int(os.environ.get("PYTHIA_PF_PROVIDER_MAX_SUBS", "20")))
PROVIDER_MB_DAY = float(os.environ.get("PYTHIA_PF_PROVIDER_MB_DAY", "40"))
WATCH_SRC = "watch "                                    # the source label of the targeted provider stream
RACED_KEEP = 20_000
LEADS_KEEP = 5_000                                      # leads kept per day for the percentiles
PROVIDER_DAYS = 14
RECORD_S = float(os.environ.get("PYTHIA_PF_LIVE_RECORD_S", "600"))   # PoolRecord's window after a migration; 0: off
RECORD_FLUSH_S = 5.0
RECORD_BUFFER = 50_000                                  # rows waiting for their write (more are dropped, and counted)
RECORD_DAYS = 30


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


def recent_creates(now_ms: int, hours: float = WARM_H, root=None) -> list[dict]:
    """The create rows the collector recorded in the last `hours`, oldest first."""
    import datetime as dt
    days = sorted({(dt.datetime.fromtimestamp(now_ms / 1000, dt.timezone.utc) - dt.timedelta(hours=h))
                   .strftime("%Y-%m-%d") for h in (hours, 0)})
    df = store.read("creates", days, root)
    if df.is_empty():
        return []
    return list(df.filter(df["t"] >= now_ms - int(hours * 3_600_000)).sort("t").iter_rows(named=True))


def warm_tokens(engine, now_ms: int, hours: float = WARM_H, root=None) -> int:
    """Adopt every coin the collector recorded as created in the last `hours`: the engine only knows coins
    it saw created, so after a restart it would not see the migration of an older one (P_pool0 buys at
    the migration, mostly of coins made hours before). Returns how many were adopted."""
    return sum(1 for r in recent_creates(now_ms, hours, root) if engine.adopt(r, now_ms))


class LiveCollector(Collector):
    """The collector's decoding with a duplicate filter by events, not by signature alone. A transaction comes
    over every link; with a provider next to the public endpoint the first copy can be a short one (its logs
    cut off or missing), and taking its signature as seen dropped the full copy with the creation or the
    migration in it, without a trace. A later copy with more log lines hands on only the events past those the
    first copy gave (under the transaction's own number); an equal or shorter one is a duplicate as before.
    With `race` set (Providers.raced) a transaction that came over a targeted provider stream and over a program
    link hands it the provider's lead in ms (negative: the public copy was first) and the provider's source, once
    per provider."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.race = None
        self.raced: collections.OrderedDict[str, list] = collections.OrderedDict()   # signatures of watched copies
        self.record: PoolRecord | None = None
        self.src = ""                                       # the feed of the transaction being handled

    def handle_tx(self, slot: int, sig: str, failed: bool, logs: list[str], recv_ms: int, src: str = "ws") -> int:
        self.src = src
        had = None if failed else self.sigs.get(sig)       # (log lines, tx number, feed, receive ms) of the copy taken
        if not failed and self.race is not None:
            self._race(sig, had, src, recv_ms)
        lines = len(logs) - (1 if logs and logs[-1] == TRUNCATED else 0)
        if had is None or lines <= had[0]:
            new = not failed and sig not in self.sigs
            tx = self.tx
            kept = super().handle_tx(slot, sig, failed, logs, recv_ms, src)
            if new:
                self.sigs[sig] = (lines, self.tx if self.tx != tx else None, src, recv_ms)
            return kept
        n, tx0, first, t0 = had
        self.counts["short_copy"] += 1
        if self.counts["short_copy"] <= 5:
            print(f"live service: a copy from {first} had {n} of {lines} log lines; the events it lacked "
                  f"came from {src}", flush=True)
        # the data lines the first copy had are left out (the invoke lines stay): only the new events decode
        rest = [x for x in logs[:n] if not x.startswith("Program data:")] + logs[n:]
        del self.sigs[sig]
        tx = self.tx
        if tx0 is not None:
            self.tx = tx0 - 1
        kept = super().handle_tx(slot, sig, failed, rest, recv_ms, src)
        if tx0 is None:                                      # the first copy had no events: these got a new number
            tx0 = self.tx if self.tx != tx else None
        else:
            self.tx = tx
        self.sigs[sig] = (lines, tx0, first, t0)
        return kept

    def _race(self, sig: str, had: tuple | None, src: str, recv_ms: int) -> None:
        """Per signature of a watched copy: the first public copy's receive ms and each provider's; every provider
        that has both hands its lead to `race` once (several providers: each against the public copy)."""
        w = src.startswith(WATCH_SRC)
        rec = self.raced.get(sig)
        if rec is None:
            if not w:
                return                                      # no provider's copy yet: had keeps the public one
            rec = self.raced[sig] = [None, {}]              # public receive ms, provider source -> receive ms
            if len(self.raced) > RACED_KEEP:
                self.raced.popitem(last=False)
            if had is not None and not had[2].startswith(WATCH_SRC):
                rec[0] = had[3]
        if w:
            if src in rec[1]:
                return
            rec[1][src] = recv_ms
        elif rec[0] is None:
            rec[0] = recv_ms
        else:
            return
        if rec[0] is None:
            return
        for s, t in rec[1].items():
            if t is None:
                continue
            rec[1][s] = None                                # counted once
            try:
                self.race(rec[0] - t, s)
            except Exception as e:                          # a measurement never stops the stream
                print(f"live service: provider race {type(e).__name__}", flush=True)

    def keep(self, table: str, row: dict, chain_ms: int | None = None, sig: str | None = None) -> int:
        """As the collector's, and the live copy keeps its message's receive time (`recv_ms`, wall ms) next to
        its slot time: an order this row decides carries both (measure.split, the receive step)."""
        row["recv_ms"] = row.get("t")
        if self.record is not None:
            self.record.add(table, row, chain_ms, sig, self.src, self.pools)
        return super().keep(table, row, chain_ms, sig)


class PoolRecord:
    """Every migrated coin's PumpSwap trades for its first RECORD_S seconds, as the live service saw them, in
    data/live/pumpfun_rt/record/<UTC day>.jsonl.gz (one gzip member per write; gzip reads them as one file). The
    collector's record missed every pool trade of 10 of the 34 live coins of 2026-10-29, both rugs among them, in
    the gaps of its public links; the live service has these coins from its own links and, for the coins it
    watches or holds, from the owner's provider, so this costs no extra data. One line a row: the table, the row
    as kept (receive ms in t and recv_ms), chain_ms (slot time), sig and src (the feed of the copy taken: the
    public endpoint or "watch <provider>"); the migration and pool-state rows ("other") of those coins and every
    gap of the live links too. PAPER DATA ONLY: nothing reads it to trade, and a failure to write it is counted
    and never stops the service (status "record")."""

    def __init__(self, window_s: float = RECORD_S, root=None, now=time.time):
        self.window_ms = window_s * 1000
        self.root = root
        self.now = now
        self.buf: list[str] = []
        self.counts = collections.Counter()
        self.last = 0.0

    def dir(self):
        return (self.root if self.root is not None else LX.data_dir() / "record")

    def add(self, table: str, row: dict, chain_ms, sig, src: str, pools: dict) -> None:
        try:
            if table == "amm":
                hit = pools.get(row.get("pool"))
                if hit is None or row.get("t", 0) - hit[1] > self.window_ms:
                    return
            elif table != "other" or row.get("kind") not in ("migrate", "pool_state", "gap"):
                return
            if len(self.buf) >= RECORD_BUFFER:
                self.counts["dropped"] += 1
                return
            self.buf.append(json.dumps({"table": table, **row, "chain_ms": chain_ms, "sig": sig, "src": src},
                                       separators=(",", ":"), default=str))
            self.counts["rows"] += 1
        except Exception:                                   # a record never stops a trade
            self.counts["errors"] += 1

    def due(self) -> bool:
        return bool(self.buf) and time.monotonic() - self.last >= RECORD_FLUSH_S

    def flush(self) -> int:
        """Appends the waiting rows to today's file (run off the event loop); old files go after RECORD_DAYS."""
        import gzip
        self.last = time.monotonic()
        lines, self.buf = self.buf, []
        if not lines:
            return 0
        try:
            d = self.dir()
            d.mkdir(parents=True, exist_ok=True)
            day = utc_day(self.now())
            with gzip.open(d / f"{day}.jsonl.gz", "at", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
            self.counts["written"] += len(lines)
            for old in sorted(d.glob("*.jsonl.gz"))[:-RECORD_DAYS]:
                old.unlink()
        except Exception as e:
            self.counts["errors"] += 1
            if self.counts["errors"] <= 5:
                print(f"live service: record not written ({type(e).__name__}: {e})", flush=True)
        return len(lines)

    def status(self) -> dict:
        return {"window_s": self.window_ms / 1000, **self.counts}


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
        self.hold: Hold | None = None                       # rows of a coin not known yet, until its creation
        self.seen: collections.OrderedDict = collections.OrderedDict()   # migrations seen (written once)
        self.watch: collections.OrderedDict = collections.OrderedDict()  # mint -> monotonic s, until looked at
        self.errors = 0
        self.tapped = 0                                     # F2: coins adopted from the collector's tap
        self.prov: Providers | None = None                  # the targeted provider streams (only with a provider)
        self.record: PoolRecord | None = None               # the first minutes of every pool, as seen here
        self.w_since: dict[str, float] = {}                 # mint -> monotonic s since the strategy waits on it
        self.cats = None                                    # livecat.LiveClassifier (with a live book)
        self.cat_gate = None                                # livecat.CategoryGate, the pipeline's category rule

    def _hold(self) -> Hold:
        if self.hold is None:
            self.hold = Hold(self.engine, self._feed, on_lost=self._lost, clock=lambda: time.monotonic())
        self.hold.engine = self.engine                      # set by start() when not given
        return self.hold

    @property
    def held(self) -> dict:
        """mint -> [(monotonic s, table, row)] until its creation (live.Hold)."""
        return self._hold().held

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
                self.attach_categories()
        if self.book is None:
            print("live service: nothing trades. Why:\n  - " + "\n  - ".join(self.why or ["see the log above"])
                  + "\nFix it and restart the service.", flush=True)
        if self.rpc is None:
            try:
                self.rpc = LX.Rpc(self.gate.env.get(LX.ENV_RPC) or LX.DEFAULT_RPC)
            except ValueError as e:
                print(f"live service: no RPC for the balance ({e})", flush=True)

    def attach_categories(self) -> None:
        """The live name categories (livecat.py): the classifier of the stream's new coins and the entry rule on the
        live book's pipeline, over the engine's category index (read on, as the classifier appends)."""
        from . import categorize as K
        from . import livecat as LC
        pipe = getattr(self.book, "pipe", None)
        if pipe is None:
            return
        ix = getattr(self.engine, "cats", None)
        if getattr(ix, "path", None) is None:
            try:
                ix = K.CategoryIndex.load(mints=False, max_age_days=K.BOOK_DAYS)
            except Exception:                               # noqa: BLE001 - an empty index: the classifier fills it
                ix = K.CategoryIndex()

        def name_of(mint):
            t = self.engine.tokens.get(mint)
            return (t.name, t.symbol) if t is not None else None

        self.cats = LC.LiveClassifier(ix, lookup=name_of)
        self.cat_gate = LC.CategoryGate(ix, block=pipe.blocked, cls=self.cats)
        pipe.category = self.cat_gate
        blocked = self.cat_gate.blocked()
        print(f"live service: name categories every {LC.EVERY_S:g} s ({len(ix):,} names known); " + (
              f"never bought: {', '.join(sorted(blocked))}; a coin without one is asked at once (at most "
              f"{LC.ONE_TIMEOUT_S:g} s), else skipped" if blocked else
              "the gate is off (category:none), the classifier keeps classifying"), flush=True)

    # ------------------------------------------------------------ the stream
    def on_row(self, table: str, row: dict) -> None:
        """A row from the stream. A row of a coin the engine does not know yet waits up to HOLD_MS for its
        creation and follows it then: the links race, and a migration that came before the creation (the coin
        made and migrated in one slot, the creation late on a slow link) was dropped by the engine for good."""
        if self.book is None:
            return
        mint = row.get("mint")
        if self.cats is not None and table in ("creates", "trades"):
            try:
                self.cats.observe(table, row)
            except Exception as e:                          # the categories never stop the book
                print(f"live service: categories {type(e).__name__}: {e}", flush=True)
        try:
            if table == "other" and row.get("kind") == "migrate":
                self.saw(mint)
                if self.pool_rule():
                    self.book.exec.warm_pool(mint, row.get("pool"))  # with prefetch: its buy builds without a read
            if self._hold().row(table, row):
                return
            self._feed(table, row)
            if table == "creates" and mint in self.held:
                self.release([mint])
        except Exception as e:                              # the collector's guard would hide it after five
            self.errors += 1
            if self.errors <= ERRORS_SHOWN or self.errors % 1000 == 0:
                print(f"live service: a {table} row of {str(mint)[:8]} failed ({type(e).__name__}: {e}); "
                      f"{self.errors} so far", flush=True)

    def saw(self, mint: str | None) -> None:
        """A migration on the stream: once in seen.jsonl, and watched until the live book bought it or said why."""
        if not mint or mint in self.seen:
            return
        self.seen[mint] = None
        self.watch[mint] = time.monotonic()
        while len(self.seen) > SEEN_KEEP:
            self.seen.popitem(last=False)
        LX.write_seen({"t": int(time.time() * 1000), "mint": mint, "rule": self.book.rule, "run": LX.RUN_ID})

    def undecided(self) -> None:
        """A seen migration of a pool strategy that has neither a buy nor a reason NO_DECISION_S later is a skip
        "no decision" with its log line: whatever the cause, a paper entry never goes without a reason."""
        if not self.pool_rule():
            return
        cut = time.monotonic() - NO_DECISION_S
        while self.watch and next(iter(self.watch.values())) < cut:
            m, _ = self.watch.popitem(last=False)
            if m not in self.book.skip_seen and m not in self.book.bought:
                self.engine.skipped[(self.book.rule, "no decision")] += 1
                self.book.on_skip(self.book.rule, m, "no decision")

    def pool_rule(self) -> bool:
        """The live strategy buys pools at their migration (P_pool0, P_pool0_wait)."""
        s = P.BY_NAME.get(getattr(self.book, "rule", None))
        return s is not None and s.family == "E" and s.entry == "migration" and hasattr(self.book, "exec")

    def release(self, mints) -> None:
        """The held rows of these coins, in the order they came, once the engine knows the coin."""
        self._hold().release(mints)

    def purge(self) -> None:
        """Held rows older than HOLD_MS are dropped (trades of coins made before the adopted hours, mostly); a
        migration among them is a skip of a migration strategy, "creation not seen", with its log line."""
        self._hold().purge()

    def _lost(self, mint: str) -> None:
        rule = self.book.rule if self.book is not None else None
        if getattr(P.BY_NAME.get(rule), "entry", None) == "migration":
            self.engine.skipped[(rule, "creation not seen")] += 1
            self.book.on_skip(rule, mint, "creation not seen")

    def rewarm(self, rows: list[dict], now_ms: int) -> int:
        """Adopt the coins the collector wrote after the start (made in the minute before it) and feed what
        was held for them."""
        n = sum(1 for r in rows if self.engine.adopt(r, now_ms))
        self.release([m for m in list(self.held) if m in self.engine.tokens])
        return n

    def _feed(self, table: str, row: dict) -> None:
        from .sim import feed_row
        ex = getattr(self.book, "exec", None)
        if ex is not None:                                  # an order this row decides: its receive and engine time
            ex.cause = (row.get("recv_ms"), int(ex.clock()))
        try:
            feed_row(self.engine, table, row)
        finally:
            if ex is not None:
                ex.cause = None
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
        self.purge()
        self.undecided()
        ex = self.book.exec
        ex.cause = (None, int(ex.clock()))                  # an order from a timer: no stream row behind it
        try:
            self.engine.advance(now_ms)
            for pipe in self.engine.pipes:
                pipe.poll(now_ms)
            self.book.tick(now_ms)
        finally:
            ex.cause = None
        if self.prov is not None:
            try:
                self.prov.want(*self.watching())
            except Exception as e:                          # the provider's stream never stops the book
                print(f"live service: provider plan {type(e).__name__}: {e}", flush=True)

    def account(self, mint: str) -> str:
        """The account a coin's trades mention: its PumpSwap pool once migrated, else its bonding curve."""
        tok = self.engine.tokens.get(mint) if self.engine is not None else None
        if getattr(tok, "pool", None):
            return tok.pool
        from .txbuild import key, pda
        return pda([b"bonding-curve", key(mint)], E.PUMP)

    def watching(self) -> tuple[dict, set]:
        """(account -> monotonic s since the strategy waits on the coin, accounts of coins held or with an order
        in flight, a leftover from before a restart too) for the targeted provider stream."""
        pipe = getattr(self.book, "pipe", None)
        if pipe is None:
            return {}, set()
        now = time.monotonic()
        for m in [m for m in self.w_since if m not in pipe.waiting]:
            del self.w_since[m]
        mints = set(pipe.by_mint)
        mints |= {lo.get("mint") for lo in getattr(self.book.exec, "leftovers", {}).values() if lo.get("mint")}
        held = {self.account(m) for m in mints}
        return {self.account(m): self.w_since.setdefault(m, now) for m in pipe.waiting}, held

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
            st = self.book.status(self.address, self.balance_t, self.holdings, self.why)
        else:
            st = LX.base_status(self.gate, self.why, self.address, self.balance_l, self.balance_t, self.holdings)
        if self.prov is not None:
            st["provider"] = self.prov.status()
        if self.record is not None:
            st["record"] = self.record.status()
        if self.cat_gate is not None:
            st["categories"] = dict(self.cat_gate.status(), classifier=self.cats.status() if self.cats else None)
        return st

    def save(self) -> None:
        d = LX.reports_dir()
        LX.write_json(d / "live_status.json", self.status())
        trades = self.book.recent if self.book is not None else LX.read_ledger(100)
        LX.write_json(d / "live_trades.json", {"t": int(time.time() * 1000), "trades": trades})
        if self.book is not None:
            if self.holdings_t is not None:               # a buy that landed after it was given up
                self.book.adopt_orphans(self.holdings, int(time.time() * 1000), read_ms=self.holdings_t)
            self.book.save_open()
        if self.prov is not None:
            self.prov.save()

    def stopped(self) -> None:
        """The service is going down: the app sees it as not running."""
        try:
            st = self.status()
            st.update(running=False, on=False, refusing="the live service stopped")
            LX.write_json(LX.reports_dir() / "live_status.json", st)
            if self.book is not None:
                self.book.save_open()
            if self.prov is not None:
                self.prov.save()
        except Exception as e:
            print(f"live service: final status not written ({type(e).__name__}: {e})", flush=True)


def utc_day(t_s: float) -> str:
    import datetime as dt
    return dt.datetime.fromtimestamp(t_s, dt.timezone.utc).strftime("%Y-%m-%d")


class ProviderWatch:
    """One targeted provider stream: ONE websocket to one of the owner's providers with a logsSubscribe per watched
    or held coin (`mentions` takes one address per subscription), so the metered data is only these coins'
    transactions. Providers.want hands it the wanted accounts (the same on every provider); the connection
    subscribes what is new, unsubscribes what is gone, resubscribes everything after a reconnect (backoff 0.5 s to
    60 s), and hands each notification to the collector under the source WATCH_SRC + label (the duplicate filter by
    signature keeps the first copy). At most max_subs at once: held coins always, then the newest watched ones. The
    bytes it receives count per UTC day; above mb_day only held coins keep theirs until the next day, and not even
    those while another provider is up. Benched (its time counted per day): a refused first subscription (no
    logsSubscribe with mentions on its plan) for the session, said once in the log; a later refusal, an error or a
    closed link until the reconnect; the day's budget until 00:00 UTC. Only scheme and host are ever printed."""

    def __init__(self, url: str, col=None, max_subs: int | None = None, mb_day: float | None = None,
                 now=time.time, commitment: str = COMMITMENT, label: str | None = None):
        from .latency import safe_url
        self.url = url
        self.host = safe_url(url)
        self.label = label or self.host                     # the host, "#2" on a second plan of the same host
        self.src = WATCH_SRC + self.label
        self.col = col
        self.max_subs = max_subs or PROVIDER_MAX_SUBS
        self.mb_day = PROVIDER_MB_DAY if mb_day is None else mb_day
        self.now = now
        self.commitment = commitment
        self.target: dict[str, bool] = {}                   # account -> held
        self.watched = 0
        self.cut = 0                                        # watched coins left out (the cap or the budget)
        self.subs: dict[str, int] = {}                      # account -> subscription id
        self.pending: dict[int, str] = {}                   # request id -> account, until the answer
        self.next_id = 1
        self.connected = False
        self.connects = 0
        self.refused = 0
        self.accepted = 0                                   # subscriptions it took this session
        self.out = False                                    # benched for the session: no logsSubscribe mentions
        self.leave: str | None = None                       # why the open link is to be left (a refusal)
        self.down: str | None = None                        # why the link is down, until the reconnect
        self.mark_t: float | None = None                    # the benched time counted up to here
        self.days: dict[str, dict] = self.load()

    # ------------------------------------------------------------ the plan
    def today(self) -> dict:
        d = utc_day(self.now())
        if d not in self.days:
            self.days[d] = {"bytes": 0, "n": 0, "first": 0, "leads": [], "benched_s": 0.0}
            for old in sorted(self.days)[:-PROVIDER_DAYS]:
                del self.days[old]
        return self.days[d]

    def paused(self) -> bool:
        return self.today()["bytes"] > self.mb_day * 1e6

    def benched(self) -> str | None:
        """Why this provider does not carry its share now, None while it does (or has not connected yet)."""
        if self.out:
            return "unsupported"
        if self.down:
            return self.down
        return "budget" if self.paused() else None

    def active(self) -> bool:
        return self.connected and self.benched() is None

    def mark(self) -> None:
        """Counts the time since the last mark as benched if it is now (called before every change)."""
        t = self.now()
        if self.mark_t is not None and self.benched() and t > self.mark_t:
            self.today()["benched_s"] = round(self.today().get("benched_s", 0.0) + t - self.mark_t, 1)
        self.mark_t = t

    def want(self, watched: dict[str, float], held: set[str], others: bool = False) -> None:
        """The accounts to stream now: every held one, then the newest watched ones up to max_subs (none while
        the day's budget is used up, and then no held one either while another provider is up; nothing at all
        once benched for the session)."""
        self.mark()
        rest = sorted((a for a in watched if a not in held), key=lambda a: -watched[a])
        paused = self.paused()
        keep = set() if self.out or (paused and others) else held
        room = 0 if self.out or paused else max(0, self.max_subs - len(keep))
        self.target = {a: True for a in keep} | {a: False for a in rest[:room]}
        self.watched, self.cut = len(rest), max(0, len(rest) - room)

    def plan(self) -> list[str]:
        """The requests that bring the subscriptions to the target (sent on the open connection)."""
        out = []
        asked = set(self.pending.values())
        for a in self.target:
            if a not in self.subs and a not in asked:
                rid, self.next_id = self.next_id, self.next_id + 1
                self.pending[rid] = a
                out.append(json.dumps({"jsonrpc": "2.0", "id": rid, "method": "logsSubscribe",
                                       "params": [{"mentions": [a]}, {"commitment": self.commitment}]}))
        for a in [a for a in self.subs if a not in self.target]:
            rid, self.next_id = self.next_id, self.next_id + 1
            out.append(json.dumps({"jsonrpc": "2.0", "id": rid, "method": "logsUnsubscribe",
                                   "params": [self.subs.pop(a)]}))
        return out

    def on_connect(self) -> None:
        self.mark()
        self.subs.clear()
        self.pending.clear()
        self.connected = True
        self.connects += 1
        self.leave = self.down = None

    def on_down(self, why: str = "error") -> None:
        self.mark()
        self.subs.clear()
        self.pending.clear()
        self.connected = False
        self.down = None if self.out else why

    def on_message(self, text: str, recv_ms: int) -> None:
        self.today()["bytes"] += len(text.encode("utf-8", "replace"))
        try:
            d = json.loads(text)
        except ValueError:
            return
        if not isinstance(d, dict):
            return
        if d.get("method") == "logsNotification":
            if self.col is not None:
                self.col.handle(text, recv_ms, self.src)
            return
        a = self.pending.pop(d.get("id"), None) if isinstance(d.get("id"), int) else None
        if a is None:
            return
        if isinstance(d.get("result"), int):
            self.subs[a] = d["result"]
            self.accepted += 1
            return
        self.refused += 1
        err = d.get("error") if isinstance(d.get("error"), dict) else {}
        code = err.get("code") if isinstance(err.get("code"), int) else None   # never its message (it can hold the URL)
        self.mark()
        if not self.accepted:                               # the very first refused: not on this plan
            self.out = True
            self.target = {}
            self.leave = "unsupported"
            print(f"live service: provider {self.label} refused logsSubscribe with mentions (code {code}): "
                  "benched for this session, the others carry on", flush=True)
            return
        self.leave = "refused"                              # it took some before: a limit, back after the backoff
        if self.refused <= 5:
            print(f"live service: provider {self.label} refused a subscription (code {code}): benched until the "
                  "reconnect", flush=True)

    def raced(self, lead_ms: float, src: str | None = None) -> None:
        """A transaction that came over this stream and over a program link: the provider's lead (ms)."""
        t = self.today()
        t["n"] += 1
        t["first"] += lead_ms > 0
        if len(t["leads"]) < LEADS_KEEP:
            t["leads"].append(int(lead_ms))

    # ------------------------------------------------------------ the connection
    async def run(self, session, stop: asyncio.Event) -> None:
        import random

        import aiohttp
        backoff = 0.5
        while not stop.is_set() and not self.out:
            t_conn = time.monotonic()
            why = "closed"
            try:
                # websocket pings on: an idle targeted stream must not be closed by the provider
                async with session.ws_connect(self.url, heartbeat=30, max_msg_size=16 << 20, compress=0) as ws:
                    self.on_connect()
                    while not stop.is_set() and not self.leave:
                        for m in self.plan():
                            await ws.send_str(m)
                        try:
                            msg = await asyncio.wait_for(ws.receive(), timeout=0.5)
                        except asyncio.TimeoutError:
                            continue
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            self.on_message(msg.data, int(time.time() * 1000))
                        elif msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED,
                                          aiohttp.WSMsgType.CLOSING, aiohttp.WSMsgType.ERROR):
                            break
                    why = self.leave or why
            except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as e:
                # the message of a failed connect can carry the URL with its key: never printed
                print(f"live service: provider {self.label} {type(e).__name__}", flush=True)
                why = "error"
            self.on_down(why)
            if stop.is_set() or self.out:
                break
            if time.monotonic() - t_conn > 60:
                backoff = 0.5
            await asyncio.sleep(backoff * (0.5 + random.random()))
            backoff = min(60.0, backoff * 2)

    # ------------------------------------------------------------ status and file
    def status(self) -> dict:
        self.mark()
        t = self.today()
        held = sum(1 for v in self.target.values() if v)
        paused = self.paused()
        why = {"unsupported": "refused logsSubscribe with mentions: benched for this session",
               "budget": f"provider budget of {self.mb_day:g} MB used today: watched coins on the public feed until "
                         "00:00 UTC, held coins keep theirs only while no other provider is up"}
        b = self.benched()
        return {"host": self.label, "connected": self.connected, "subs": len(self.subs), "held": held,
                "watched": self.watched, "left_out": self.cut, "mb_today": round(t["bytes"] / 1e6, 3),
                "mb_day": self.mb_day, "paused": paused, "benched": b,
                "benched_min_today": round(t.get("benched_s", 0.0) / 60, 1),
                "why": why.get(b, f"link {b}, back after the backoff" if b else None)}

    @staticmethod
    def path():
        return LX.data_dir() / "provider.json"

    def load(self) -> dict:
        """This provider's days from the file (a file of one provider, as task 90 wrote it, counts for its host)."""
        try:
            f = json.loads(self.path().read_text(encoding="utf-8"))
            provs = f.get("providers")
            if isinstance(provs, dict):
                d = (provs.get(self.label) or {}).get("days") or {}
            else:
                d = (f.get("days") or {}) if f.get("host") == self.label else {}
            return {k: {"bytes": int(v.get("bytes") or 0), "n": int(v.get("n") or 0),
                        "first": int(v.get("first") or 0), "leads": list(v.get("leads") or [])[:LEADS_KEEP],
                        "benched_s": float(v.get("benched_s") or 0)}
                    for k, v in d.items() if isinstance(v, dict)}
        except (OSError, ValueError, TypeError, AttributeError):
            return {}

    def save(self) -> None:
        """data/live/pumpfun_rt/provider.json, under providers -> label: per UTC day the bytes received, the
        transactions over both, how often the provider was first, its leads (ms) and its benched seconds; the
        label as scheme and host only."""
        try:
            self.mark()
            self.today()
            try:
                provs = json.loads(self.path().read_text(encoding="utf-8")).get("providers")
            except (OSError, ValueError, AttributeError):
                provs = None
            provs = provs if isinstance(provs, dict) else {}
            provs[self.label] = {"host": self.label, "benched": self.benched(), "days": self.days}
            LX.write_json(self.path(), {"t": int(self.now() * 1000), "mb_day": self.mb_day, "providers": provs})
        except OSError as e:
            print(f"live service: provider file not written ({type(e).__name__})", flush=True)


class Providers:
    """Every provider of the owner side by side (PYTHIA_SOLANA_WS_URLS, several full URLs): one ProviderWatch each,
    the same subscriptions on every one, the first copy by signature wins, each with its own day's budget
    (PYTHIA_PF_PROVIDER_MB_DAY each) and its own bench; the others carry on while one is benched."""

    def __init__(self, urls: list[str], col=None, **kw):
        from .latency import safe_url
        self.all: list[ProviderWatch] = []
        for u in urls:
            host = label = safe_url(u)
            i = 2
            while label in {w.label for w in self.all}:
                label, i = f"{host}#{i}", i + 1
            self.all.append(ProviderWatch(u, col, label=label, **kw))
        self.max_subs = self.all[0].max_subs if self.all else PROVIDER_MAX_SUBS
        self.mb_day = self.all[0].mb_day if self.all else PROVIDER_MB_DAY

    def labels(self) -> str:
        return ", ".join(w.label for w in self.all)

    def want(self, watched: dict[str, float], held: set[str]) -> None:
        for w in self.all:
            w.want(watched, held, others=any(o.active() for o in self.all if o is not w))

    def raced(self, lead_ms: float, src: str | None = None) -> None:
        for w in self.all:
            if w.src == src:
                w.raced(lead_ms)

    def status(self) -> dict:
        ps = [w.status() for w in self.all]
        return {"providers": ps, "up": sum(1 for w in self.all if w.active()), "of": len(ps),
                "subs": sum(p["subs"] for p in ps), "mb_today": round(sum(p["mb_today"] for p in ps), 3),
                "paused": bool(ps) and all(p["paused"] for p in ps),
                "why": "; ".join(f"{p['host']}: {p['why']}" for p in ps if p["why"]) or None}

    def save(self) -> None:
        for w in self.all:
            w.save()

    def run(self, session, stop: asyncio.Event) -> list:
        return [asyncio.create_task(w.run(session, stop)) for w in self.all]


def provider_urls(urls: list[str], env=None) -> list[str]:
    """The owner's providers among the feeds (all of them), empty without one."""
    env = os.environ if env is None else env
    public = (env.get("PYTHIA_SOLANA_WS") or "").strip() or DEFAULT_WS
    return [u for u in urls if u != public]


def firehose_urls(urls: list[str], env=None) -> list[str]:
    """The feeds of the program-wide links: the public endpoint only (a provider meters by data volume and the
    firehose is all of it), unless PYTHIA_PF_PROVIDER_FIREHOSE=1 spreads them over every feed again."""
    env = os.environ if env is None else env
    if env.get("PYTHIA_PF_PROVIDER_FIREHOSE", "0") == "1":
        return urls
    public = (env.get("PYTHIA_SOLANA_WS") or "").strip() or DEFAULT_WS
    return [u for u in urls if u == public] or [public]


def feed_links(urls: list[str]) -> list[tuple[str, str, int]]:
    """(url, program, link) per stream link, spread over the feeds like collector.run: link k of each program
    on urls[k % len(urls)] (run hands it firehose_urls: the public endpoint only, unless the owner asks)."""
    return [(urls[k % len(urls)], p, k) for p in (E.PUMP, E.PUMP_AMM)
            for k in range(LINKS if p == E.PUMP else AMM_LINKS)]


def feeds_line(urls: list[str]) -> str:
    """The start line naming the feeds: scheme and host only, never a path, query or key."""
    from .latency import safe_url
    return "live service: feeds " + ", ".join(safe_url(u) for u in urls)


async def classify_loop(svc: Service, stop: asyncio.Event, every_s: float | None = None) -> None:
    """The live classifier (livecat.LiveClassifier): every EVERY_S the new coins, in a thread off the loop."""
    from . import livecat as LC
    every_s = LC.EVERY_S if every_s is None else every_s
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), every_s)
            break
        except asyncio.TimeoutError:
            pass
        job = svc.cats.take() if svc.cats is not None else None
        if job is None:
            continue
        try:
            await asyncio.to_thread(svc.cats.classify, *job)
        except Exception as e:                              # the next run asks again
            svc.cats.busy = False
            print(f"live service: categories run {type(e).__name__}: {e}", flush=True)


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
    from .collector import feed_urls
    urls = feed_urls()                                       # the owner's providers first, the public one as fallback
    links = firehose_urls(urls)                              # the program-wide links: the public endpoint
    provs = provider_urls(urls)                              # the coins watched or held: every provider
    col = LiveCollector(None, svc.on_row, amm=True, meta=False)
    if svc.book is not None and svc.book.pipe is not None:     # "no pool state" while our PumpSwap links were down
        svc.book.pipe.feed_down = lambda a, b: col.was_down(E.PUMP_AMM, a, b)
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
    t_warm = time.monotonic() + REWARM_S if svc.book is not None else None
    last = beat = 0.0
    woken = svc.arm_wake(loop)
    from . import poolread
    from .collector import POOL_QUEUE, TapReader
    pool_read = svc.book is not None and svc.pool_rule() and poolread.enabled()
    if pool_read:                                            # F1: the pool read at its migration, as the collector
        col.loop, col.pool_q = loop, asyncio.Queue(maxsize=POOL_QUEUE)
    tap = TapReader() if svc.book is not None and os.environ.get("PYTHIA_PF_TAP", "1") != "0" else None
    async with aiohttp.ClientSession() as session:
        tasks = []
        if svc.book is not None:                             # nothing to stream for a book that is not there
            tasks = [asyncio.create_task(col.stream(session, u, p, k, stop)) for u, p, k in feed_links(links)]
            print(feeds_line(links), flush=True)
            if pool_read:
                tasks.append(asyncio.create_task(col.pool_worker()))
                print("live service: each migration's pool is read from the chain (F1)", flush=True)
            if tap is not None:
                print("live service: the collector's new coins are adopted every second (F2)", flush=True)
            if RECORD_S > 0:
                svc.record = col.record = PoolRecord()
                print(f"live service: every pool's first {RECORD_S:g} s go to {col.record.dir()} (paper data)",
                      flush=True)
            if svc.cats is not None:
                tasks.append(asyncio.create_task(classify_loop(svc, stop)))
            if provs:
                svc.prov = Providers(provs, col)
                col.race = svc.prov.raced
                tasks += svc.prov.run(session, stop)
                print(f"live service: watched and held coins also from {svc.prov.labels()} (at most "
                      f"{svc.prov.max_subs}, {svc.prov.mb_day:g} MB a day each)", flush=True)
        print(f"live service: {'streaming' if tasks else 'status only'}", flush=True)
        try:
            while not stop.is_set():
                await svc.pause(1.0)
                if tap is not None:                        # F2: a coin our links missed, from the collector at once
                    try:
                        rows = await asyncio.to_thread(tap.poll)
                        if rows:
                            svc.tapped += svc.rewarm(rows, int(time.time() * 1000))
                    except Exception as e:                 # the store's adoption at start still holds
                        print(f"live service: tap {type(e).__name__}: {e}", flush=True)
                svc.tick(col.clock.latest or int(time.time() * 1000))
                if col.record is not None and col.record.due():
                    await asyncio.to_thread(col.record.flush)
                mono = time.monotonic()
                if t_warm is not None and mono >= t_warm:
                    t_warm = None
                    try:
                        now = int(time.time() * 1000)
                        n = svc.rewarm(await asyncio.to_thread(recent_creates, now), now)
                        print(f"live service: {n:,} more coins adopted from the collector's next write", flush=True)
                    except Exception as e:
                        print(f"live service: second adoption failed ({type(e).__name__}: {e})", flush=True)
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
            if col.record is not None:
                col.record.flush()
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
