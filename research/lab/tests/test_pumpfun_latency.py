"""The live pump.fun executor's speed settings (docs/LATENCY.md): the settings and their safe defaults, the
prepared sale, the blockhash and fee prefetch, the parallel send, kept connections, the signature websocket,
reads behind sends, the service's wake-up, the latency split, and a replay that the bot decides the same with
every setting on as with every setting off.

Temp folders only, fake signers and mocked endpoints: no network, no real key, nothing sent.

Run from research/lab:  python -m pytest tests/test_pumpfun_latency.py
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import os
import random
import threading
import time

import pytest

from lab.pumpfun_rt import curve as C
from lab.pumpfun_rt import fastpath as F
from lab.pumpfun_rt import live_exec as LX
from lab.pumpfun_rt import live_service as LS
from lab.pumpfun_rt import measure as MS
from lab.pumpfun_rt import pipeline as P
from lab.pumpfun_rt import sim
from lab.pumpfun_rt import txbuild as X
from test_pumpfun_live import (LANDED, LIMITS, ChainRpc, CountingSigner, SimRpc, chain_book, executor, open_position,
                               order_lines, own_tx, settle)
from test_pumpfun_pipeline import FakeBuilder, FakeSigner, OpenGate, strat
from test_pumpfun_rt import BUYERS, MINT, POOL, SOL, T0, Curve, Fixed, key

FAST = LX.Speed(prepare=True, prefetch=True, dynamic_fee=True, parallel=True, keepalive=True, ws_confirm=True,
                wake=True, send_first=True, status_ms=LX.FAST_STATUS_MS, grace_ms=LX.FAST_GRACE_MS)


@pytest.fixture(autouse=True)
def folders(monkeypatch, tmp_path):
    from lab import report as rep
    monkeypatch.setattr(LX, "data_dir", lambda: tmp_path / "live")
    monkeypatch.setattr(rep, "REPORTS", tmp_path / "reports")
    monkeypatch.setattr(P, "kill_paths", lambda: [tmp_path / "etc-kill", tmp_path / "data-kill"])
    monkeypatch.setattr(LX, "crypto_ok", lambda: True)
    return tmp_path


# ---------------------------------------------------------------- the settings

def test_every_speed_setting_is_off_unless_the_owner_sets_it():
    s = LX.speed_of({})
    assert s.on() == [] and s.status_ms == LX.CONFIRM_MS and s.grace_ms == LX.LANDED_GRACE_MS
    assert s.fee_cap_sol == C.PRIORITY_SOL                          # the dynamic fee never pays more than today
    assert s.ws_url == "wss://api.mainnet-beta.solana.com"
    f = LX.speed_of({LX.ENV_FAST: "1"})
    assert f.on() == list(LX.SPEED_SWITCHES) and f.status_ms == LX.FAST_STATUS_MS and f.grace_ms == 0
    one = LX.speed_of({LX.ENV_FAST: "1", "PYTHIA_PUMPFUN_PARALLEL_SEND": "0"})
    assert "parallel" not in one.on() and "prepare" in one.on()
    only = LX.speed_of({"PYTHIA_PUMPFUN_PREPARE_SELLS": "1"})
    assert only.on() == ["prepare"] and only.status_ms == LX.CONFIRM_MS


def test_the_speed_settings_can_only_make_the_timers_faster_and_the_fee_cap_stays_under_the_hard_maximum():
    s = LX.speed_of({"PYTHIA_PUMPFUN_STATUS_MS": "90000", "PYTHIA_PUMPFUN_LANDED_GRACE_MS": "99999",
                     "PYTHIA_PUMPFUN_FEE_CAP_SOL": "5"})
    assert s.status_ms == LX.CONFIRM_MS and s.grace_ms == LX.LANDED_GRACE_MS
    assert s.fee_cap_sol == F.HARD_MAX_PRIORITY_SOL
    assert LX.speed_of({"PYTHIA_PUMPFUN_STATUS_MS": "1"}).status_ms == 500      # no hammering of the node
    assert LX.speed_of({"PYTHIA_PUMPFUN_FEE_CAP_SOL": "nan"}).fee_cap_sol == C.PRIORITY_SOL
    assert LX.speed_of({LX.ENV_RPC: "https://rpc.example/?k=1"}).ws_url == "wss://rpc.example/?k=1"
    assert LX.speed_of({LX.ENV_RPC_WS: "http://plain"}).ws_url is None           # only wss


# ---------------------------------------------------------------- the prepared sale

class PoolRpc(SimRpc):
    def __init__(self):
        super().__init__()
        self.hashes = 0
        self.fees = [{"slot": i, "prioritizationFee": 1_000 * i} for i in range(150)]

    def blockhash(self):
        self.hashes += 1
        return key(100 + self.hashes)

    def recent_fees(self, accounts):
        return self.fees


def first(xs):
    return sorted(xs)[0]


def builder(monkeypatch, speed=FAST, sender=False):
    monkeypatch.setattr(random, "choice", first)                    # the same fee recipient and tip each time
    b = LX.Builder(PoolRpc(), (None, None))
    b.speed = speed
    if sender:
        b.sender, b.sender_tip_l = object(), 5_000
    return b


def sale(tokens=1_000_000, limit=0):
    return P.Order(7, "sell", MINT, "pool", tokens, limit, T0, "stop")


def test_a_prepared_sale_is_the_same_transaction_the_executor_would_build_and_passes_check_own(monkeypatch):
    b = builder(monkeypatch, sender=True)
    user = FakeSigner.pubkey
    assert b.prepare(user, sale(), POOL, True)
    ready = b.build(user, sale(), POOL, True)
    assert b.last_prepared
    plain = builder(monkeypatch, speed=LX.Speed(), sender=True)
    plain.hash = b.hash
    assert plain.build(user, sale(), POOL, True) == ready and not plain.last_prepared
    k, ixs, bh, msg = b.prepared[7]
    X.check_own(user, ixs, sender_tip_ok=True)
    assert msg == ready and X.HELIUS_MIN_TIP_LAMPORTS == 5_000
    seen = []
    real = X.check_own
    monkeypatch.setattr(X, "check_own", lambda *a, **kw: (seen.append(1), real(*a, **kw)))
    b.build(user, sale(), POOL, True)
    assert seen                                                      # checked again before it is signed


def test_a_prepared_sale_is_used_only_for_exactly_its_order(monkeypatch):
    b = builder(monkeypatch)
    user = FakeSigner.pubkey
    b.prepare(user, sale(), POOL, True)
    for o, close in ((sale(tokens=999_999), True), (sale(limit=5), True), (sale(), False)):
        b.build(user, o, POOL, close)
        assert not b.last_prepared
    b.priority_l += 1                                                # the fee changed: built again
    b.build(user, sale(), POOL, True)
    assert not b.last_prepared
    b.forget({})
    assert b.prepared == {}


def test_a_prepared_sale_follows_the_blockhash(monkeypatch):
    b = builder(monkeypatch)
    user = FakeSigner.pubkey
    b.prepare(user, sale(), POOL, True)
    old = b.prepared[7][2]
    b.hash = (time.monotonic() - LX.PREFETCH_BLOCKHASH_S - 1, b.hash[1])
    b.refresh()                                                      # the background refresh
    assert b.hash[1] != old
    b.prepare(user, sale(), POOL, True)
    assert b.prepared[7][2] == b.hash[1] and X.key(b.hash[1]) in b.prepared[7][3]
    n = b.rpc.hashes
    b.build(user, sale(), POOL, True)
    assert b.rpc.hashes == n and b.last_prepared                     # no blockhash read on the send's path


def test_without_prefetch_the_refresh_reads_no_blockhash(monkeypatch):
    b = builder(monkeypatch, speed=LX.Speed())
    b.refresh()
    assert b.rpc.hashes == 0 and b.hash is None


# ---------------------------------------------------------------- the dynamic fee

def test_the_dynamic_fee_follows_recent_fees_and_never_passes_its_cap(monkeypatch):
    b = builder(monkeypatch)
    b.fee_accounts = [POOL]
    fee = b.dynamic_fee()
    assert 0 < fee <= C.PRIORITY_SOL * C.LAMPORTS
    assert POOL in b.fees.accounts and set(X.BUYBACK_FEE_RECIPIENTS) <= set(b.fees.accounts)
    b.rpc.fees = [{"slot": 1, "prioritizationFee": 10 ** 12}]
    b.fees.at = -1e18
    cap = int(C.PRIORITY_SOL * C.LAMPORTS)
    assert cap - 1 <= b.dynamic_fee() <= cap                         # capped at today's fixed fee
    b.rpc.fees = [{"slot": 1, "prioritizationFee": 1}]
    b.fees.at = -1e18
    floor = F.FEE_FLOOR_MICRO * (X.UNITS + 100_000) // 1_000_000
    assert b.dynamic_fee() == floor                                  # quiet minutes: cheaper, not zero
    raised = builder(monkeypatch, speed=LX.speed_of({"PYTHIA_PUMPFUN_DYNAMIC_FEE": "1",
                                                     "PYTHIA_PUMPFUN_FEE_CAP_SOL": "1"}))
    raised.rpc.fees = [{"slot": 1, "prioritizationFee": 10 ** 12}]
    assert int(F.HARD_MAX_PRIORITY_SOL * C.LAMPORTS) - 1 <= raised.dynamic_fee() <= F.HARD_MAX_PRIORITY_SOL * C.LAMPORTS


def test_a_dynamic_fee_only_changes_the_unit_price_and_check_own_accepts_it(monkeypatch):
    b = builder(monkeypatch)
    b.dynamic_fee()
    ixs = b.ixs(FakeSigner.pubkey, sale(), POOL, True)
    X.check_own(FakeSigner.pubkey, ixs)
    plain = builder(monkeypatch, speed=LX.Speed())
    other = plain.ixs(FakeSigner.pubkey, sale(), POOL, True)
    assert [ix.program for ix in ixs] == [ix.program for ix in other]
    assert [ix.data for ix in ixs[2:]] == [ix.data for ix in other[2:]]   # only the compute budget differs


# ---------------------------------------------------------------- sending

class Endpoint:
    def __init__(self, answer=None, error=None, wait=0.0):
        self.answer, self.error, self.wait, self.got = answer, error, wait, []

    def send(self, tx, skip_preflight=False):
        time.sleep(self.wait)
        self.got.append((tx, skip_preflight))
        if self.error:
            raise self.error
        return self.answer


def test_the_parallel_send_gives_sender_and_the_rpc_the_same_bytes_and_takes_the_first_answer():
    rpc, snd = Endpoint("rpc-sig", wait=0.2), Endpoint("sender-sig")
    b = LX.Builder(rpc, (None, None))
    b.sender, b.speed = snd, LX.Speed(parallel=True)
    assert b.send(b"tx") == "sender-sig"
    time.sleep(0.3)
    assert snd.got == [(b"tx", True)] and rpc.got == [(b"tx", False)]   # Sender without, the RPC with preflight
    snd.error = RuntimeError("HTTP Error 503")
    assert b.send(b"tx2") == "rpc-sig"
    rpc.error = RuntimeError("HTTP Error 500")
    with pytest.raises(RuntimeError, match="Sender.*plain RPC|plain RPC.*Sender"):
        b.send(b"tx3")


def test_without_the_setting_sender_comes_first_and_the_rpc_only_as_the_fallback():
    rpc, snd = ChainRpc(), Endpoint("sender-sig")
    b = LX.Builder(rpc, (None, None))
    b.sender = snd
    assert b.send(b"\x01" + bytes(64) + b"m") == "sender-sig" and rpc.sent == []


class FakeConn:
    made = []

    def __init__(self, host, port, timeout=None):
        self.host, self.closed, self.n = host, False, 0
        FakeConn.made.append(self)
        self.fail = 0

    def request(self, method, path, body=None, headers=None):
        import http.client
        if self.fail:
            self.fail -= 1
            raise http.client.RemoteDisconnected("closed by the server")
        self.n += 1
        self.last = (method, path, body)

    def getresponse(self):
        conn = self

        class R:
            status = 200

            def read(self):
                return json.dumps({"result": conn.last[0] == "GET" or "sig"}).encode()
        return R()

    def close(self):
        self.closed = True


def test_a_kept_connection_is_reused_and_a_closed_one_replaced_once(monkeypatch):
    import http.client
    FakeConn.made = []
    monkeypatch.setattr(http.client, "HTTPSConnection", FakeConn)
    r = LX.Rpc("https://sender.example/fast?swqos_only=true", keepalive=True)
    assert r.call("sendTransaction", ["x"]) == "sig" and r.call("sendTransaction", ["y"]) == "sig"
    assert len(FakeConn.made) == 1 and FakeConn.made[0].last[1] == "/fast?swqos_only=true"
    assert r.ping() and FakeConn.made[0].last[:2] == ("GET", "/ping")
    FakeConn.made[0].fail = 1                                        # the server closed it while idle
    assert r.call("getHealth", []) == "sig" and len(FakeConn.made) == 2 and FakeConn.made[0].closed


# ---------------------------------------------------------------- the signature websocket

def test_the_websocket_reports_a_landing_with_or_without_an_error_once():
    got = []
    w = LX.SigWatcher("wss://x", lambda *a: got.append(a), clock=lambda: 42, start=False)
    w.watch("S1", 3)
    w.watch("S2", 4)
    m1, m2 = json.loads(w.message("S1")), json.loads(w.message("S2"))
    assert m1["method"] == "signatureSubscribe" and m1["params"] == ["S1", {"commitment": "confirmed"}]
    w.handle(json.dumps({"id": m1["id"], "result": 11}))
    w.handle(json.dumps({"id": m2["id"], "result": 12}))
    note = {"method": "signatureNotification", "params": {"subscription": 11, "result": {"value": {"err": None}}}}
    w.handle(json.dumps(note))
    w.handle(json.dumps(note))                                       # once
    w.handle(json.dumps({"method": "signatureNotification",
                         "params": {"subscription": 12, "result": {"value": {"err": {"InstructionError": [2, 1]}}}}}))
    assert got == [(3, "S1", LANDED, 42), (4, "S2", {"err": {"InstructionError": [2, 1]},
                                                     "confirmationStatus": "confirmed"}, 42)]
    w.watch("S3", 5)
    m3 = json.loads(w.message("S3"))
    w.handle(json.dumps({"id": m3["id"], "result": 13}))
    w.forget("S3")                                                   # booked meanwhile: nothing to say
    w.handle(json.dumps({"method": "signatureNotification", "params": {"subscription": 13,
                                                                      "result": {"value": {"err": None}}}}))
    w.handle("not json")
    assert len(got) == 2


class Watcher:
    def __init__(self):
        self.watched, self.forgot = [], []

    def watch(self, sig, pid):
        self.watched.append((sig, pid))

    def forget(self, sig):
        self.forgot.append(sig)


def fast_book(now, speed=FAST):
    ex, rpc, pipe, cv, book, cards = chain_book(now)
    ex.speed = speed
    ex.watcher = Watcher()
    return ex, rpc, pipe, cv, book, cards


def test_a_confirmed_order_is_read_back_and_booked_at_once_not_after_35_seconds(tmp_path):
    now = [T0]
    ex, rpc, pipe, cv, book, _ = fast_book(now)
    settle(ex, pipe, T0 + 100)
    sig = ex.pending[0]["sig"]
    assert ex.watcher.watched == [(sig, 0)]                          # subscribed before it was sent
    want = pipe.pos[0]["want"]
    rpc.txs[sig] = own_tx(-int(0.05 * SOL) - 1_005_000, 0, want)
    now[0] += 900
    ex._confirmed(0, sig, dict(LANDED), now[0])
    settle(ex, pipe, T0 + 1_000)
    p = pipe.pos[0]
    assert p["state"] == "open" and p["tokens"] == want and not ex.pending
    m = [r for r in MS.read_measured() if r.get("what") == "fill"][0]
    assert m["onchain"] and m["confirmed_ms"] == T0 + 900 and m["queued_ms"] == T0 and m["seen_ms"] == T0 + 900
    assert m["built_ms"] is not None and m["sent_at_ms"] is not None and ex.watcher.forgot == [sig]
    cv.buy(T0 + 1_400, int(0.05 * SOL), FakeSigner.pubkey)          # the stream's late copy: not booked twice
    assert pipe.pos[0]["tokens"] == want and not ex.leftovers


def test_right_after_a_confirmation_only_the_transaction_itself_is_booked(tmp_path):
    now = [T0]
    ex, rpc, pipe, cv, book, _ = fast_book(now)
    settle(ex, pipe, T0 + 100)
    sig = ex.pending[0]["sig"]
    rpc.held = {MINT: 123}
    ex._confirmed(0, sig, dict(LANDED), now[0])
    settle(ex, pipe, T0 + 200)                                       # the node has no transaction yet
    assert 0 in ex.pending and pipe.pos[0]["state"] == "pending"
    want = pipe.pos[0]["want"]
    rpc.txs[sig] = own_tx(-int(0.05 * SOL) - 1_005_000, 0, want)
    now[0] += LX.LANDED_RETRY_MS
    settle(ex, pipe, T0 + 300)
    assert pipe.pos[0]["tokens"] == want                            # exact, not the holdings' 123


def test_a_failed_landing_from_the_websocket_counts_its_fee_and_frees_the_buy(tmp_path):
    now = [T0]
    ex, rpc, pipe, cv, book, _ = fast_book(now)
    settle(ex, pipe, T0 + 100)
    sig = ex.pending[0]["sig"]
    ex._confirmed(0, sig, {"err": {"InstructionError": [3, {"Custom": 6002}]}, "confirmationStatus": "confirmed"},
                  now[0])
    settle(ex, pipe, T0 + 200)
    assert not pipe.pos and not ex.pending and not ex.exposure
    assert any(o["what"] == "failed" and o["sig"] == sig for o in order_lines())


def test_the_fast_status_poll_asks_after_two_seconds_and_the_slow_one_after_thirty(tmp_path):
    now = [T0]
    ex, rpc, pipe, cv, book, _ = fast_book(now, speed=LX.Speed(status_ms=LX.FAST_STATUS_MS, grace_ms=0))
    settle(ex, pipe, T0 + 100)
    now[0] += LX.FAST_STATUS_MS + 1
    pipe.poll(T0 + 200)
    assert ex.q.queue and ex.q.queue[-1][0] == "status"
    now = [T0]
    ex, rpc, pipe, cv, book, _ = chain_book(now)
    settle(ex, pipe, T0 + 100)
    now[0] += LX.FAST_STATUS_MS + 1
    pipe.poll(T0 + 200)
    assert not ex.q.queue


# ---------------------------------------------------------------- reads behind sends, the wake-up, stops

def test_reads_never_hold_up_a_send(tmp_path):
    now = [T0]
    ex, rpc, pipe, cv, book, _ = fast_book(now, speed=LX.Speed(send_first=True))
    p = open_position(ex, pipe, cv)
    assert not ex.q.queue and ex.rq.queue[-1][0] == "fee"           # the fill's fee read is on the reads' queue
    order = []
    real = ex.step
    ex.step = lambda item: (order.append(item[0]), real(item))
    pipe._sell_all(p, T0 + 2_000, "stop")
    ex.drain()
    assert order[0] == "send"                                        # the stop's sale goes before the fee read


def test_a_price_tick_through_the_stop_sends_the_sale_at_once_with_the_prepared_transaction(tmp_path):
    now = [T0]
    built = []

    class Ready(FakeBuilder):
        def __init__(self):
            super().__init__()
            self.prepared, self.last_prepared, self.fee_accounts = {}, False, []

        def prepare(self, user, o, pool, close):
            self.prepared[o.pid] = (o.mint, o.venue, o.tokens, o.limit_l, close)
            return True

        def forget(self, keep):
            pass

        def build(self, user, o, pool, close):
            self.last_prepared = self.prepared.get(o.pid) == (o.mint, o.venue, o.tokens, o.limit_l, close)
            built.append(self.last_prepared)
            return super().build(user, o, pool, close)

    ex, rpc, pipe, cv, book, _ = chain_book(now, builder=Ready())
    st = pipe.strats["X"]
    pipe.strats["X"] = dataclasses.replace(st, exits=dataclasses.replace(st.exits, sl=0.2, ladder=((9.0, 1.0),)))
    ex.speed = LX.Speed(prepare=True)
    held = cv.buy(T0 + 50, 20 * SOL, BUYERS[1])                      # a deep curve before our buy lands
    p = open_position(ex, pipe, cv)
    pipe.poll(T0 + 1_500)                                            # the service's second: the sale to prepare
    assert ex.want_sales[0][0].tokens == p["left"] and ex.want_sales[0][2] is True
    ex.prefetch_once()
    assert ex.builder.prepared[0][2] == p["left"]
    ex.drain()
    built.clear()
    t = T0 + 1_600
    while not ex.q.queue:                                            # then a slow slide (no pull)                                            # one small sale every 3 s, one tick each
        t += 3_000
        cv.sell(t, held // 60, BUYERS[1])
        assert t < T0 + 200_000
    assert ex.q.queue[0][0] == "send" and ex.q.queue[0][1].why == "stop"   # sent on that tick, no poll in between
    assert ex.q.queue[0][1].signal_ms == t
    ex.drain()
    assert built == [True]
    pipe.poll(t)
    assert any(o["what"] == "sent" and o.get("prepared") for o in order_lines())


def test_every_worker_result_wakes_the_service_and_a_retry_sets_its_next_wake(tmp_path):
    now = [T0]
    ex, rpc, pipe, cv, book, _ = fast_book(now)
    woke = []
    ex.on_result = lambda: woke.append(1)
    settle(ex, pipe, T0 + 100)
    assert woke                                                      # the send's answer
    assert ex.next_wake_ms() is None
    ex.deferred[0], ex.retry_at[0] = ("sell", None), T0 + 4_000
    assert ex.next_wake_ms() == T0 + 4_000


def test_the_service_waits_a_second_or_until_a_result(tmp_path):
    ex = executor(tmp_path, speed=LX.Speed(wake=True))

    class Book:
        exec = ex
    svc = LS.Service(gate=OpenGate(), engine=object(), attach=lambda *a, **k: None)
    svc.book = Book()

    async def go():
        loop = asyncio.get_running_loop()
        assert svc.arm_wake(loop)
        t = time.monotonic()
        threading.Timer(0.05, ex.on_result).start()
        await svc.pause(1.0)
        return time.monotonic() - t
    assert asyncio.run(go()) < 0.5
    svc2 = LS.Service(gate=OpenGate(), engine=object())
    svc2.book = type("B", (), {"exec": executor(tmp_path)})()
    assert not svc2.arm_wake(None)                                   # the setting is off: the plain second


def test_the_prefetch_round_never_raises_and_pings_sender_only_with_keepalive(tmp_path):
    ex = executor(tmp_path, speed=LX.Speed(keepalive=True))
    pings = []
    ex.builder.sender = type("S", (), {"ping": lambda self: pings.append(1) or True})()
    ex.builder.refresh = lambda: (_ for _ in ()).throw(RuntimeError("down"))
    ex.prefetch_once()
    ex.builder.refresh = lambda: None
    ex.prefetch_once()
    assert pings == [1]
    ex.prefetch_once()
    assert pings == [1]                                              # every SENDER_PING_S, not every round


# ---------------------------------------------------------------- the measurement

def test_the_split_puts_every_step_of_a_fill_in_its_column():
    new = {"what": "fill", "side": "sell", "signal_ms": 1_000, "queued_ms": 1_100, "built_ms": 1_101,
           "sent_at_ms": 1_300, "land_ms": 1_800, "confirmed_ms": 2_000, "seen_ms": 2_050, "t": 2_050, "sig": "a"}
    old = {"what": "fill", "side": "buy", "signal_ms": 0, "land_ms": 10_000, "send_to_land_ms": 9_000, "t": 47_000,
           "sig": "b", "onchain": True}
    sp = MS.split([new, old], [{"what": "sent", "sig": "b", "t": 1_800}])
    s = sp["sell"]["steps"]
    assert s["signal_to_queued"]["median"] == 100 and s["queued_to_built"]["median"] == 1
    assert s["built_to_sent"]["median"] == 199 and s["sent_to_landed"]["median"] == 500
    assert s["sent_to_confirmed"]["median"] == 700 and s["landed_to_seen"]["median"] == 250
    b = sp["buy"]
    assert b["steps"]["signal_to_queued"]["median"] == 1_000 and b["steps"]["queued_to_sent"]["median"] == 800
    assert b["steps"]["landed_to_seen"]["median"] == 37_000 and b["via"] == {"stream": 0, "chain": 1}
    assert b["landed_to_seen_by"]["chain"]["n"] == 1
    md = "\n".join(MS.split_markdown(sp))
    assert "landed to booked, fill from the chain" in md and "37.00" in md


def test_the_execution_report_carries_the_split(tmp_path):
    LX.write_measure({"what": "fill", "side": "buy", "signal_ms": 0, "land_ms": 500, "send_to_land_ms": 400,
                      "t": 600, "sig": "z", "lat_ms": 500})
    s = MS.write_report()
    assert s["split"]["buy"]["steps"]["signal_to_queued"]["n"] == 1
    assert "Where the time goes" in (LX.reports_dir() / "execution.md").read_text()


# ---------------------------------------------------------------- the replay: the same decisions either way

class ReplayBuilder(FakeBuilder):
    """The real Builder's speed surface without accounts: prepares, refreshes, sends in parallel (to fakes)."""

    def __init__(self):
        super().__init__()
        self.rpc = ChainRpc()
        self.prepared, self.last_prepared, self.fee_accounts, self.speed = {}, False, [], LX.Speed()
        self.used = 0

    def refresh(self):
        pass

    def prepare(self, user, o, pool, close):
        self.prepared[o.pid] = (o.mint, o.venue, o.tokens, o.limit_l, close)
        return True

    def forget(self, keep):
        for pid in [p for p in self.prepared if p not in keep]:
            self.prepared.pop(pid)

    def build(self, user, o, pool, close):
        self.last_prepared = self.prepared.get(o.pid) == (o.mint, o.venue, o.tokens, o.limit_l, close)
        self.used += self.last_prepared
        return X.compile_message(user, [X.compute_limit(1000 + o.pid)], key(5))

    def send(self, tx):
        return X.b58(tx[1:65])


class Replay:
    """A live book over a stream of rows. Every order is filled LAT_MS of stream time after it was sent, by the
    token's state then, as our own trade on the stream (so both runs get the same fills at the same times); the
    executor's wall clock is the stream's time."""

    LAT_MS = 1_000

    def __init__(self, strategies, speed: LX.Speed, limits=P.Limits(0.1, 5, 0.6, 5.0)):
        self.now = [0]
        gate = OpenGate()
        gate.rule, gate.mode = "X", "test"
        self.b = ReplayBuilder()
        self.ex = LX.LiveExecutor(gate, CountingSigner(), self.b, limits, clock=lambda: self.now[0], start=False,
                                  mode="test", max_total_sol=None, rule="X", speed=speed,
                                  totals={"pnl_l": 0, "since_ms": None, "trades": 0, "total_alerted": False})
        self.ex.verify_sales = False
        if speed.ws_confirm:
            self.ex.watcher = Watcher()
        self.eng = sim.Engine([], costs=Fixed())
        self.decisions = []
        self.pipe = self.eng.add_pipe(P.Pipeline(self.eng, list(strategies), self.ex, limits=limits, name="live",
                                                 record=False, on_event=self._event))
        self.speed = speed

    def _event(self, kind, p, kw):
        if kind in ("buy_sent", "sell_sent"):
            o = kw["order"]
            self.decisions.append((kind, o.mint, o.why, o.tokens, o.signal_ms))
        elif kind == "closed":
            r = kw["rec"]
            self.decisions.append(("closed", r["mint"], r["exit_why"], round(r["pnl_sol"], 9)))

    def row(self, table, row):
        t = int(row.get("t") or self.now[0])
        self.now[0] = max(self.now[0], t)
        sim.feed_row(self.eng, table, row)
        self.step(self.now[0])

    def step(self, t):
        ex = self.ex
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
        tok = self.eng.tokens.get(o.mint)
        if tok is None:
            return
        pool = o.venue == "pool"
        fee = tok.amm_fee_bps if pool else tok.fee_bps
        if o.side == "buy":
            if pool:
                if not tok.pq or not tok.pb:
                    return
                tokens, sol = C.pool_buy(o.stake_l, tok.pb, tok.pq, fee), int(o.stake_l / (1 + fee / 10_000))
            else:
                tokens = min(o.tokens, tok.rt)
                sol = int(P.curve_cost(tokens, tok.vs, tok.vt, fee) / (1 + fee / 10_000))
        else:
            v = self.eng.sale_value(tok, o.tokens)
            if v is None:
                return
            tokens, sol = o.tokens, int(v / (1 - fee / 10_000))
        if tokens <= 0:
            return
        self.ex.on_trade("amm" if pool else "trades", {"t": t, "mint": o.mint, "buy": o.side == "buy", "sol": sol,
                                                       "tok": tokens, "user": FakeSigner.pubkey, "fee_bps": fee,
                                                       "sig": pend["sig"]})


def synthetic_day(n=12, seed=3):
    """Coins with buyers, dumps and quiet stretches, as (table, row) in time order."""
    rnd = random.Random(seed)
    rows = []
    for i in range(n):
        mint, t0 = key(150 + i), T0 + i * 40_000
        vs, vt, rt = 30 * SOL, 1_073_000_000 * 10 ** 6, C.INITIAL_RT
        rows.append((t0, "creates", {"t": t0, "tx": 1, "mint": mint, "creator": key(240), "vs": vs, "vt": vt,
                                     "rt": rt, "name": "T", "symbol": "T", "uri": "u"}))
        t, rs = t0, 0
        for k in range(60):
            t += rnd.randint(100, 2_500)
            buy = rnd.random() < (0.7 if k < 20 else 0.35)
            if buy:
                sol = int(rnd.uniform(0.1, 2.0) * SOL)
                tok = int(vt * sol / (vs + sol))
                vs, vt, rt, rs = vs + sol, vt - tok, rt - tok, rs + sol
            else:
                tok = int(rnd.uniform(0.02, 0.15) * (C.INITIAL_RT - rt + 1))
                sol = int(vs * tok / (vt + tok))
                vs, vt, rt, rs = vs - sol, vt + tok, rt + tok, rs - sol
            rows.append((t, "trades", {"t": t, "tx": 2 + k, "mint": mint, "buy": buy, "sol": sol, "tok": tok,
                                       "user": BUYERS[rnd.randrange(len(BUYERS))], "vs": vs, "vt": vt, "rs": rs,
                                       "rt": rt, "fb": 95, "cfb": 30, "slot": 1000 + i * 1000 + k, "sig": None}))
    rows.sort(key=lambda r: r[0])
    return [(table, row) for _, table, row in rows]


def replay(rows, strategies, speed):
    r = Replay(strategies, speed)
    for table, row in rows:
        r.row(table, row)
    for k in range(1, 400):                                          # the time stops of what is still open
        r.step(r.now[0] + 1_000 * k)
    return r


def test_replay_every_speed_setting_on_decides_exactly_what_every_setting_off_decides():
    rows = synthetic_day()
    strategies = [strat(sl=0.2, ladder=((0.3, 0.5), (0.8, 1.0)), time_s=60)]
    off = replay(rows, strategies, LX.Speed())
    on = replay(rows, strategies, FAST)
    entries = [d for d in off.decisions if d[0] == "buy_sent"]
    closes = [d for d in off.decisions if d[0] == "closed"]
    assert len(entries) >= 5 and len(closes) >= 5                    # the day has trades to compare
    assert {d[2] for d in closes} & {"stop", "pull"}                 # protective exits among them
    assert on.decisions == off.decisions
    assert on.b.used > 0 and off.b.used == 0                          # the fast run did use prepared sales


@pytest.mark.skipif(not os.environ.get("PYTHIA_REPLAY_DAY"), reason="a recorded day: PYTHIA_REPLAY_DAY=YYYY-MM-DD")
def test_replay_a_recorded_day_decides_the_same_with_every_setting_on():
    day, rule = os.environ["PYTHIA_REPLAY_DAY"], os.environ.get("PYTHIA_REPLAY_RULE", "P_pool0")
    until = os.environ.get("PYTHIA_REPLAY_UNTIL_MS")
    s = [P.BY_NAME[rule]]
    runs = []
    for speed in (LX.Speed(), FAST):
        r = Replay(s, speed)
        for table, row in sim.day_events(day):
            if until and int(row.get("t") or 0) > int(until):
                break
            r.row(table, row)
        for k in range(1, 400):
            r.step(r.now[0] + 1_000 * k)
        runs.append(r)
    print(json.dumps({"day": day, "rule": rule, "decisions": len(runs[0].decisions),
                      "entries": sum(d[0] == "buy_sent" for d in runs[0].decisions),
                      "closed": sum(d[0] == "closed" for d in runs[0].decisions),
                      "prepared_used": runs[1].b.used, "same": runs[0].decisions == runs[1].decisions}))
    assert runs[0].decisions == runs[1].decisions
