"""The live pump.fun bot's own latency (execution.md showed signal to order at a median 2.9 s, p90 18.7 s): every
order carries the receive time of the stream row that decided it and the moment the engine took that row (after a
wait for the coin's creation), the report breaks each fill into receive, decide, build, send and land per day; the
gate's files and a new day are read on the service's tick, not at the signal; with prefetch a migration's pool
accounts are read as the migration comes in, so the pool buy builds without a read. A replay through the service's
own path decides exactly the same with every speed setting on as with every one off (the dynamic fee aside: it
changes what a transaction pays, never what is decided).

Temp folders only, fake signers and nodes: no network, no real key, nothing sent.

Run from research/lab:  python -m pytest tests/test_pumpfun_live_speed.py
"""

from __future__ import annotations

import dataclasses
import json
import os
import random
import time

import pytest

from lab.pumpfun_rt import curve as C
from lab.pumpfun_rt import live_exec as LX
from lab.pumpfun_rt import live_service as LS
from lab.pumpfun_rt import measure as MS
from lab.pumpfun_rt import pipeline as P
from lab.pumpfun_rt import sim
from lab.pumpfun_rt import txbuild as X
from test_pumpfun_latency import FAST
from test_pumpfun_live import CountingSigner
from test_pumpfun_live_match import CREATE, MIGRATE, POOL_BUY, PUBLIC
from test_pumpfun_pipeline import FakeBuilder, FakeSigner, OpenGate
from test_pumpfun_rt import BUYERS, DEV, MINT, POOL, SOL, T0, key, note

RULE = "P_pool0_wait"
LIMITS = P.Limits(0.05, 5, 0.6, 0.3)


@pytest.fixture(autouse=True)
def folders(monkeypatch, tmp_path):
    from lab import report as rep
    monkeypatch.setattr(LX, "data_dir", lambda: tmp_path / "live")
    monkeypatch.setattr(rep, "REPORTS", tmp_path / "reports")
    monkeypatch.setattr(P, "kill_paths", lambda: [tmp_path / "etc-kill", tmp_path / "data-kill"])
    return tmp_path


class Node:
    """Every account read answers a pool of the token the test names for it (and GlobalConfig's buyback list)."""

    def __init__(self, pools=None):
        self.pools = pools if pools is not None else {POOL: MINT}
        self.reads, self.fail = 0, False

    def account(self, pubkey):
        self.reads += 1
        if self.fail:
            raise RuntimeError("no account yet")
        data = bytearray(1000)
        for off, k in ((43, self.pools.get(pubkey, MINT)), (75, X.WSOL), (139, key(61)), (171, key(62))):
            data[off:off + 32] = X.key(k)
        for i, r in enumerate(X.BUYBACK_FEE_RECIPIENTS):
            data[643 + 32 * i:675 + 32 * i] = X.key(r)
        return bytes(data), X.TOKEN

    def blockhash(self):
        return key(5)

    def send(self, tx, skip_preflight=False):
        return X.b58(tx[1:65])

    def statuses(self, sigs):
        return [None for _ in sigs]

    def fee_of(self, sig):
        return None


def service(speed=LX.Speed(), builder=None, now=None, rule=RULE, limits=LIMITS):
    """The live service's path from a websocket message to the executor, on a clock the test moves."""
    now = now if now is not None else [T0]
    gate = OpenGate()
    gate.rule, gate.mode = rule, "test"
    ex = LX.LiveExecutor(gate, CountingSigner(), builder or FakeBuilder(), limits, clock=lambda: now[0], start=False,
                         mode="test", max_total_sol=None, rule=rule, speed=speed,
                         totals={"pnl_l": 0, "since_ms": None, "trades": 0, "total_alerted": False})
    ex.verify_sales = False
    eng = sim.Engine([])
    pipe = eng.add_pipe(P.Pipeline(eng, [P.BY_NAME[rule]], ex, limits=limits, name="live", record=False))
    book = LX.LiveBook(pipe, ex, rule, alerts=False)
    pipe.on_skip, pipe.on_event = book.on_skip, book.on_event                # as live_exec.attach
    svc = LS.Service(gate=gate, engine=eng, alerts=False, start_worker=False)
    svc.book = book
    return svc, LS.LiveCollector(None, svc.on_row, amm=True, meta=False), pipe, ex


def measured():
    return [json.loads(x) for x in (LX.data_dir() / "measured.jsonl").read_text(encoding="utf-8").splitlines()]


def fill(ex, pipe, t):
    """The stream's trade of our own buy: booked and measured."""
    ex.drain()
    pipe.poll(t)
    pend = ex.pending[0]
    o = pend["order"]                                                       # filled at the signal's price
    ex.on_trade("amm", {"t": t, "mint": MINT, "buy": True, "sol": int(o.stake_l / 1.0125), "tok": o.tokens,
                        "user": FakeSigner.pubkey, "fee_bps": 125, "sig": pend["sig"]})


# ---------------------------------------------------------------- the stamps

def test_a_live_row_keeps_its_receive_time_next_to_its_slot_time():
    rows = []
    col = LS.LiveCollector(None, lambda tb, r: rows.append((tb, r)), amm=True, meta=False)
    col.handle(note("b", 200, POOL_BUY), T0 + 50, PUBLIC)                  # slot 200 first seen here (no pool yet)
    col.handle(note("c", 100, CREATE), T0 + 900, PUBLIC)                    # an older slot, delivered late
    assert [tb for tb, _ in rows] == ["creates"]
    assert rows[0][1]["recv_ms"] == T0 + 900 and rows[0][1]["t"] == T0 + 50   # timed by the slots seen before it


def test_an_order_carries_the_receive_and_engine_time_of_the_row_that_decided_it():
    now = [T0]
    svc, col, pipe, ex = service(now=now)
    col.handle(note("c", 100, CREATE), T0, PUBLIC)
    col.handle(note("m", 101, MIGRATE), T0 + 400, PUBLIC)
    now[0] = T0 + 830                                                       # the engine takes the row 30 ms later
    col.handle(note("b", 102, POOL_BUY), T0 + 800, PUBLIC)
    pend = ex.pending[0]
    assert pend["recv_ms"] == T0 + 800 and pend["fed_ms"] == T0 + 830 and pend["sent_ms"] == T0 + 830
    assert ex.cause is None                                                 # only while a row is handled
    fill(ex, pipe, T0 + 2_000)
    m = [r for r in measured() if r["what"] == "fill"][0]
    assert (m["recv_ms"], m["fed_ms"], m["queued_ms"]) == (T0 + 800, T0 + 830, T0 + 830)
    sp = MS.split(measured())["buy"]["steps"]
    assert sp["signal_to_received"]["n"] == 1 and sp["received_to_fed"]["median"] == 30
    assert sp["fed_to_queued"]["median"] == 0


def test_a_wait_for_the_coins_creation_shows_as_its_own_step():
    now = [T0]
    svc, col, pipe, ex = service(now=now)
    col.handle(note("m", 101, MIGRATE), T0, PUBLIC)                         # the links race: no creation yet
    col.handle(note("b", 102, POOL_BUY), T0 + 400, PUBLIC)
    assert not ex.pending
    now[0] = T0 + 3_000
    col.handle(note("c", 101, CREATE), T0 + 3_000, PUBLIC)                  # held rows follow it now
    pend = ex.pending[0]
    assert pend["recv_ms"] == T0 + 400 and pend["fed_ms"] == T0 + 3_000
    fill(ex, pipe, T0 + 4_000)
    assert MS.split(measured())["buy"]["steps"]["received_to_fed"]["median"] == 2_600


def test_an_order_from_the_services_tick_has_no_receive_time():
    now = [T0]
    svc, col, pipe, ex = service(now=now)
    col.handle(note("c", 100, CREATE), T0, PUBLIC)
    col.handle(note("m", 101, MIGRATE), T0 + 400, PUBLIC)
    col.handle(note("b", 102, POOL_BUY), T0 + 800, PUBLIC)
    fill(ex, pipe, T0 + 1_000)
    now[0] = T0 + 2_000
    pipe.kill = lambda: True                                                # the kill switch sells on the tick
    svc.tick(T0 + 2_000)
    sale = [p for p in ex.pending.values() if p["side"] == "sell"][0]
    assert sale["recv_ms"] is None and sale["fed_ms"] == T0 + 2_000


# ---------------------------------------------------------------- the gate and the day, off the signal's path

class CountingGate(OpenGate):
    def __init__(self):
        super().__init__()
        self.checks = 0

    def check(self):
        self.checks += 1
        return super().check()


def test_the_tick_reads_the_gate_before_a_signal_would_have_to(monkeypatch):
    svc, col, pipe, ex = service()
    gate = ex.gate = CountingGate()
    gate.rule, gate.mode = RULE, "test"
    clock = [1_000.0]
    monkeypatch.setattr(LX.time, "monotonic", lambda: clock[0])
    ex.last_check = clock[0]
    clock[0] += LX.RECHECK_S - LX.GATE_LEAD_S - 0.1
    svc.book.tick(T0)
    assert gate.checks == 0                                                 # not yet
    clock[0] += 0.2
    svc.book.tick(T0)
    assert gate.checks == 1                                                 # the tick read it, early
    clock[0] += LX.GATE_LEAD_S                                              # a signal where ready() used to read
    assert ex.ready() is None and gate.checks == 1
    gate.why = ["the kill switch file is there"]
    clock[0] += LX.RECHECK_S - LX.GATE_LEAD_S
    svc.book.tick(T0)
    assert "kill switch" in ex.ready() and gate.checks == 2                 # a shut gate is seen as before


def test_without_a_tick_ready_still_reads_the_gate_every_minute(monkeypatch):
    svc, col, pipe, ex = service()
    gate = ex.gate = CountingGate()
    gate.rule, gate.mode = RULE, "test"
    clock = [1_000.0]
    monkeypatch.setattr(LX.time, "monotonic", lambda: clock[0])
    ex.last_check = clock[0]
    clock[0] += LX.RECHECK_S - 0.1
    ex.ready()
    assert gate.checks == 0
    clock[0] += 0.2
    gate.why = ["PYTHIA_PUMPFUN_LIVE is not 1"]
    assert "not 1" in ex.ready() and gate.checks == 1


def test_a_new_day_is_rolled_on_the_tick_not_by_the_first_buy():
    now = [T0]
    svc, col, pipe, ex = service(now=now)
    day = ex.day
    now[0] += P.DAY_MS
    rolled = []
    real = ex.recompute
    ex.recompute = lambda: (rolled.append(1), real())
    svc.book.tick(now[0])
    assert ex.day == day + 1 and rolled == [1]
    ex._caps(P.Order(0, "buy", MINT, "pool", 10, int(0.05 * SOL), now[0]))
    assert rolled == [1]                                                    # nothing left for the buy to do


# ---------------------------------------------------------------- a migration's pool, read ahead of its buy

def real_builder(monkeypatch, node=None):
    monkeypatch.setattr(random, "choice", lambda xs: sorted(xs)[0])
    b = LX.Builder(node or Node(), (None, None))
    return b


def test_with_prefetch_a_migrations_pool_is_read_as_it_comes_and_the_buy_builds_without_a_read(monkeypatch):
    node = Node()
    b = real_builder(monkeypatch, node)
    now = [T0]
    svc, col, pipe, ex = service(speed=FAST, builder=b, now=now)
    col.handle(note("c", 100, CREATE), T0, PUBLIC)
    col.handle(note("m", 101, MIGRATE), T0 + 400, PUBLIC)
    assert list(ex.warmed) == [POOL] and ex.warm_q.qsize() == 1
    b.hash = (time.monotonic(), key(5))                                     # the blockhash prefetch's part
    ex.drain()
    assert node.reads == 3                                                  # config, the token's program, the pool
    col.handle(note("m2", 101, MIGRATE), T0 + 450, PUBLIC)                  # the same pool again: not asked twice
    assert ex.warm_q.empty()
    col.handle(note("b", 102, POOL_BUY), T0 + 800, PUBLIC)
    ex.drain()
    assert node.reads == 3                                                  # the buy read nothing
    plain = real_builder(monkeypatch, Node())
    plain.hash = b.hash
    o = ex.pending[0]["order"]
    assert b.build(FakeSigner.pubkey, o, POOL, False) == plain.build(FakeSigner.pubkey, o, POOL, False)


def test_without_prefetch_nothing_is_read_ahead(monkeypatch):
    node = Node()
    svc, col, pipe, ex = service(speed=LX.Speed(), builder=real_builder(monkeypatch, node))
    col.handle(note("c", 100, CREATE), T0, PUBLIC)
    col.handle(note("m", 101, MIGRATE), T0 + 400, PUBLIC)
    ex.drain()
    assert node.reads == 0 and ex.warm_q.empty() and not ex.warmed


def test_a_curve_strategy_reads_no_pool_ahead(monkeypatch):
    node = Node()
    svc, col, pipe, ex = service(speed=FAST, builder=real_builder(monkeypatch, node), rule="P_cmig_model")
    col.handle(note("c", 100, CREATE), T0, PUBLIC)
    col.handle(note("m", 101, MIGRATE), T0 + 400, PUBLIC)
    assert ex.warm_q.empty()


def test_a_pool_not_readable_yet_is_left_to_the_buy_as_before(monkeypatch, capsys):
    node = Node()
    node.fail = True
    b = real_builder(monkeypatch, node)
    svc, col, pipe, ex = service(speed=FAST, builder=b)
    col.handle(note("c", 100, CREATE), T0, PUBLIC)
    col.handle(note("m", 101, MIGRATE), T0 + 400, PUBLIC)
    ex.drain()
    assert ex.warm_failed == 1 and "not read ahead" in capsys.readouterr().out
    assert not any(k.startswith("pool:") for k in b.cache)                  # nothing half cached
    node.fail = False
    b.hash = (time.monotonic(), key(5))
    col.handle(note("b", 102, POOL_BUY), T0 + 800, PUBLIC)
    ex.drain()
    assert ex.pending[0]["sig"] is None and not ex.results.empty()          # built and sent: the build read itself


def test_the_prefetch_thread_reads_a_migrations_pool_at_once_not_at_its_next_round():
    seen = []

    class Warm(FakeBuilder):
        def refresh(self):
            pass

        def warm(self, mint, pool):
            seen.append((mint, pool, time.monotonic()))

    gate = OpenGate()
    ex = LX.LiveExecutor(gate, None, Warm(), LIMITS, start=True, speed=LX.Speed(prefetch=True),
                         totals={"pnl_l": 0, "since_ms": None, "trades": 0, "total_alerted": False})
    try:
        time.sleep(0.05)                                                     # the thread is in its wait
        t0 = time.monotonic()
        ex.warm_pool(MINT, POOL)
        for _ in range(100):
            if seen:
                break
            time.sleep(0.005)
        assert seen and seen[0][:2] == (MINT, POOL)
        assert seen[0][2] - t0 < LX.PREFETCH_EVERY_S / 2
    finally:
        ex.stop()


# ---------------------------------------------------------------- the report

def fill_row(day_ms, side, signal, recv=None, fed=None, queued=None, built=None, sent=None, land=None, s2l=None):
    return {"what": "fill", "side": side, "signal_ms": day_ms + signal, "recv_ms": None if recv is None else day_ms + recv,
            "fed_ms": None if fed is None else day_ms + fed, "queued_ms": None if queued is None else day_ms + queued,
            "built_ms": None if built is None else day_ms + built, "sent_at_ms": None if sent is None else day_ms + sent,
            "land_ms": day_ms + land, "send_to_land_ms": s2l}


def test_the_report_breaks_every_fill_into_receive_decide_build_send_and_land_per_day():
    d1, d2 = 1_792_627_200_000, 1_792_713_600_000                          # 2026-10-22 and 2026-10-23, 00:00 UTC
    rows = [fill_row(d1, "buy", 0, land=4_000, s2l=1_000),                  # before the stamps: signal to order only
            fill_row(d2, "buy", 0, recv=2_000, fed=2_000, queued=2_001, built=2_051, sent=2_071, land=2_900),
            fill_row(d2, "buy", 0, recv=500, fed=3_500, queued=3_500, built=3_501, sent=3_520, land=4_000),
            fill_row(d2, "sell", 0, recv=100, fed=100, queued=100, built=101, sent=120, land=700)]
    ph = MS.phases(rows)
    assert ph["2026-10-22"]["buy"]["order"]["median"] == 3_000 and ph["2026-10-22"]["buy"]["receive"]["n"] == 0
    b = ph["2026-10-23"]["buy"]
    assert b["receive"]["n"] == 2 and b["decide"]["median"] == (1 + 3_000) / 2
    assert b["build"]["median"] == 25.5 and b["send"]["median"] == 19.5 and b["land"]["median"] == (829 + 480) / 2
    md = "\n".join(MS.phases_markdown(ph))
    assert "| 2026-10-22 | buy | 1 | 3.00 (3.00) |  |  |  |  |  |" in md
    assert "| 2026-10-23 | sell | 1 | 0.10 (0.10) | 0.10 (0.10) | 0.00 (0.00) | 0.00 (0.00) | 0.02 (0.02) | 0.58 (0.58) |" in md
    s = MS.summarise(rows)
    s["phases"] = ph
    out = MS.markdown(s)
    assert "## Per step, by day" in out
    assert "Receive:" in out and "Decide:" in out


def test_the_execution_report_carries_the_steps(tmp_path):
    LX.data_dir().mkdir(parents=True)
    d = 1_792_713_600_000
    (LX.data_dir() / "measured.jsonl").write_text(json.dumps(fill_row(d, "buy", 0, recv=900, fed=950, queued=951,
                                                                      built=960, sent=980, land=1_500)) + "\n")
    s = MS.write_report()
    assert s["phases"]["2026-10-23"]["buy"]["receive"]["median"] == 900
    md = (LX.reports_dir() / "execution.md").read_text()
    assert "## Per step, by day" in md and "| 2026-10-23 | buy | 1 |" in md
    assert "signal to received" in md and "received to the engine" in md


# ---------------------------------------------------------------- the replay: the same decisions either way

class ServiceReplay:
    """The live service's path over a stream of rows (Service.on_row, its tick every second of stream time), the
    executor with a real Builder over a fake node. Every order is filled LAT_MS of stream time after it was sent,
    by the token's state then, as our own trade on the stream, so every run gets the same fills."""

    LAT_MS = 1_000

    def __init__(self, speed, monkeypatch, rule=RULE, limits=P.Limits(0.1, 5, 0.6, 5.0)):
        self.now = [0]
        self.pools = {}
        self.node = Node(self.pools)
        monkeypatch.setattr(random, "choice", lambda xs: sorted(xs)[0])
        self.b = LX.Builder(self.node, (None, None))
        self.svc, _, self.pipe, self.ex = service(speed=speed, builder=self.b, now=self.now, rule=rule, limits=limits)
        self.speed = speed
        self.decisions = []
        hook = self.pipe.on_event

        def on_event(kind, p, kw):
            if kind in ("buy_sent", "sell_sent"):
                o = kw["order"]
                self.decisions.append((kind, o.mint, o.why, o.tokens, o.limit_l, o.signal_ms))
            elif kind == "closed":
                r = kw["rec"]
                self.decisions.append(("closed", r["mint"], r["exit_why"], round(r["pnl_sol"], 9)))
            hook(kind, p, kw)
        self.pipe.on_event = on_event
        self.next_tick = None
        self.buy_reads = []
        build = self.b.build

        def counted(user, o, pool, close):
            n = self.node.reads
            out = build(user, o, pool, close)
            if o.side == "buy":
                self.buy_reads.append(self.node.reads - n)
            return out
        self.b.build = counted

    def row(self, table, row):
        t = int(row.get("t") or self.now[0])
        self.now[0] = max(self.now[0], t)
        if table == "other" and row.get("kind") == "migrate" and row.get("pool"):
            self.pools[row["pool"]] = row["mint"]
        if self.next_tick is None:
            self.next_tick = self.now[0]
        while self.now[0] >= self.next_tick:
            self.svc.tick(self.next_tick)
            self.next_tick += 1_000
        self.svc.on_row(table, row)
        self.step(self.now[0])

    def step(self, t):
        ex = self.ex
        self.b.hash = (time.monotonic(), key(5))
        ex.drain()
        self.pipe.poll(t)
        for pid, pend in list(ex.pending.items()):
            if pend.get("sig") and t - pend["sent_ms"] >= self.LAT_MS:
                self.fill(pid, pend, t)
        ex.drain()
        if self.speed.prepare:
            ex.prefetch_once()

    def fill(self, pid, pend, t):
        o = pend["order"]
        tok = self.svc.engine.tokens.get(o.mint)
        if tok is None:
            return
        pool = o.venue == "pool"
        fee = tok.amm_fee_bps if pool else tok.fee_bps
        if o.side == "buy":
            if not pool or not tok.pq or not tok.pb:
                return
            tokens, sol = C.pool_buy(o.stake_l, tok.pb, tok.pq, fee), int(o.stake_l / (1 + fee / 10_000))
        else:
            v = self.svc.engine.sale_value(tok, o.tokens)
            if v is None:
                return
            tokens, sol = o.tokens, int(v / (1 - fee / 10_000))
        if tokens <= 0:
            return
        self.ex.on_trade("amm" if pool else "trades", {"t": t, "mint": o.mint, "buy": o.side == "buy", "sol": sol,
                                                       "tok": tokens, "user": FakeSigner.pubkey, "fee_bps": fee,
                                                       "sig": pend["sig"]})

    def finish(self):
        for k in range(1, 400):                                          # the time stops of what is still open
            t = self.now[0] + 1_000 * k
            self.svc.tick(t)
            self.step(t)


def migration_day(n=10, seed=5):
    """Coins that migrate into a pool and trade there: some up through +30 %, some down through -20 %, some flat
    into the time stop; some pools get their first trade within the 5 s wait, some only after it."""
    rnd = random.Random(seed)
    rows = []
    for i in range(n):
        mint, pool, t0 = key(150 + i), key(180 + i), T0 + i * 400_000
        rows.append((t0, 0, "creates", {"t": t0, "tx": 1, "mint": mint, "creator": DEV, "vs": 30 * SOL,
                                        "vt": 1_073_000_000 * 10 ** 6, "rt": C.INITIAL_RT, "name": "T", "symbol": "T",
                                        "uri": "u", "slot": 1_000 + i * 1_000}))
        tm = t0 + 60_000
        rows.append((tm, 1, "other", {"t": tm, "kind": "migrate", "mint": mint, "pool": pool, "sol": 85 * SOL,
                                      "tok": 206_900_000 * 10 ** 6, "slot": 1_100 + i * 1_000}))
        base, quote = 206_900_000 * 10 ** 6, 67 * SOL
        drift = (0.04, -0.04, 0.0)[i % 3]
        t = tm + (2_000 if i % 4 else 7_000)                              # every fourth pool is quiet too long
        for k in range(160):
            buy = rnd.random() < 0.5 + drift * 5
            if buy:
                sol = int(rnd.uniform(0.2, 3.0) * SOL)
                tok = base * sol // (quote + sol)
            else:
                tok = int(base * rnd.uniform(0.003, 0.04))
                sol = quote * tok // (base + tok)
            rows.append((t, 2 + k, "amm", {"t": t, "mint": mint, "buy": buy, "base": tok, "quote": sol, "pb": base,
                                           "pq": quote, "lpb": 20, "pfb": 5, "cfb": 5,
                                           "slot": 1_101 + i * 1_000 + k, "user": BUYERS[rnd.randrange(len(BUYERS))],
                                           "vq": 0, "sig": None}))
            base, quote = (base - tok, quote + sol) if buy else (base + tok, quote - sol)
            t += rnd.randint(200, 3_000)
    rows.sort(key=lambda r: (r[0], r[1]))
    return [(table, row) for _, _, table, row in rows]


# every setting that changes no number: the dynamic fee changes what a transaction pays (never what is decided)
SAME = dataclasses.replace(FAST, dynamic_fee=False)


def replay(rows, speed, monkeypatch, rule=RULE):
    r = ServiceReplay(speed, monkeypatch, rule=rule)
    for table, row in rows:
        r.row(table, row)
    r.finish()
    return r


def test_replay_through_the_services_path_decides_the_same_with_every_speed_setting_on(monkeypatch):
    rows = migration_day()
    off = replay(rows, LX.Speed(), monkeypatch)
    on = replay(rows, SAME, monkeypatch)
    entries = [d for d in off.decisions if d[0] == "buy_sent"]
    closes = [d for d in off.decisions if d[0] == "closed"]
    assert len(entries) >= 5 and len(closes) == len(entries)              # the day has trades to compare
    assert {d[2] for d in closes} >= {"take", "stop"}
    assert ("no pool state" in {k[1] for k in off.svc.engine.skipped if k[0] == RULE})
    assert on.decisions == off.decisions
    assert on.buy_reads and set(on.buy_reads) == {0}                      # every pool buy built without a read
    assert off.buy_reads and min(off.buy_reads) > 0                       # as before without prefetch


@pytest.mark.skipif(not os.environ.get("PYTHIA_REPLAY_DAY"), reason="a recorded day: PYTHIA_REPLAY_DAY=YYYY-MM-DD")
def test_replay_a_recorded_day_through_the_services_path_decides_the_same(monkeypatch):
    day, rule = os.environ["PYTHIA_REPLAY_DAY"], os.environ.get("PYTHIA_REPLAY_RULE", RULE)
    until = os.environ.get("PYTHIA_REPLAY_UNTIL_MS")
    rows = []
    for table, row in sim.day_events(day):
        if until and int(row.get("t") or 0) > int(until):
            break
        rows.append((table, row))
    runs = [replay(rows, speed, monkeypatch, rule) for speed in (LX.Speed(), SAME)]
    print(json.dumps({"day": day, "rule": rule, "decisions": len(runs[0].decisions),
                      "entries": sum(d[0] == "buy_sent" for d in runs[0].decisions),
                      "buys_built_without_a_read": sum(1 for x in runs[1].buy_reads if x == 0),
                      "same": runs[0].decisions == runs[1].decisions}))
    assert runs[0].decisions == runs[1].decisions
