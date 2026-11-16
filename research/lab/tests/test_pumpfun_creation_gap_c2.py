"""C2 (2026-11-16): the creations still missing after C1 and the PumpSwap gaps (results/pumpfun_creation_gap.md).
The creation read asks for version 1 transactions and tries a failed read again, each outcome is logged, coverage
counts a creation row on any day split into stream and late, the check is red under 95 % on a full day, and the lab's
links reconnect at once after a drop. The live service's collector does none of it. No network, no wallet.

Run from research/lab:  python -m pytest tests/test_pumpfun_creation_gap_c2.py
"""

from __future__ import annotations

import asyncio
import json

import aiohttp

from lab.pumpfun_rt import collector as CL
from lab.pumpfun_rt import coverage as CV
from lab.pumpfun_rt import events as E
from lab.pumpfun_rt import poolread as PR
from lab.pumpfun_rt import store
from test_pumpfun_coverage_c1 import mig
from test_pumpfun_rt import DEV, T0, create_vals, key, logs_for, note

A, B, C, D = key(81), key(82), key(83), key(84)
DAY = store.day_of(T0)
# the RPC's answer for a version 1 transaction asked with maxSupportedTransactionVersion 0 (recorded 2026-11-16)
V1_REFUSED = {"jsonrpc": "2.0", "id": 1, "error": {"code": -32015, "message": (
    'Transaction version (1) is not supported by the requesting client. Please try the request again with the '
    'following configuration parameter: "maxSupportedTransactionVersion": 1')}}


def chain(mint: str, pages: list[list[str]], fail: int = 0):
    """A recorded RPC for one curve: its signatures newest first, a version 1 creation transaction that the RPC refuses
    below version 1, and `fail` answers of 429 first."""
    calls, left = [], [fail]

    def call(method, params):
        if left[0]:
            left[0] -= 1
            raise RuntimeError("HTTP Error 429: Too Many Requests")
        calls.append((method, params))
        if method == "getSignaturesForAddress":
            k = sum(1 for m, _ in calls if m == method) - 1
            return {"result": [{"signature": s} for s in pages[k]] if k < len(pages) else []}
        if params[1].get("maxSupportedTransactionVersion", 0) < 1:
            return V1_REFUSED
        return {"result": {"slot": 7, "blockTime": T0 // 1000 - 86_400 * 90, "version": 1,
                           "meta": {"logMessages": logs_for((E.PUMP, "CreateEvent", create_vals(mint=mint)))}}}
    return call, calls


def test_a_version_1_creation_is_read(monkeypatch):
    monkeypatch.setattr(PR, "SIG_PAGE", 2)
    call, calls = chain(A, [["s4", "s3"], ["s2", "s1"], []])
    row = PR.creation(A, key(4), call=call, clock=lambda: T0)
    assert row["mint"] == A and row["sig"] == "s1" and row["t"] == T0 - 86_400_000 * 90 and row["late"] == T0
    assert calls[-1][1][1]["maxSupportedTransactionVersion"] == 1
    # C1's reader asked with version 0 and got the refusal, which the collector counted as a read error
    assert call("getTransaction", ["s1", {"maxSupportedTransactionVersion": 0}])["error"]["code"] == -32015
    # more signatures than the pages allowed: TooMany, not "no creation"; first_signature keeps its None
    many = chain(A, [["a", "b"]] * 5)[0]
    try:
        PR.creation(A, key(4), call=many, pages=3)
        raise AssertionError("TooMany expected")
    except PR.TooMany as e:
        assert "6" in str(e)
    assert PR.first_signature(chain(A, [["a", "b"]] * 5)[0], key(4), pages=3) is None
    assert PR.creation(A, key(4), call=chain(A, [[]])[0]) is None, "a curve without signatures"


def run_worker(col, read, events, until, rounds=300):
    async def go():
        col.loop, col.create_q = asyncio.get_running_loop(), asyncio.Queue(maxsize=CL.CREATE_QUEUE)
        worker = asyncio.create_task(col.create_worker(read))
        for sig, slot, logs in events:
            col.handle(note(sig, slot, logs), T0)
        for _ in range(rounds):
            await asyncio.sleep(0.01)
            if until():
                break
        worker.cancel()
    asyncio.run(go())


def completion(mint: str, sig: str, slot: int):
    return sig, slot, logs_for((E.PUMP, "CompleteEvent", {"user": DEV, "mint": mint, "bonding_curve": key(5),
                                                          "timestamp": 1}))


def test_a_failed_read_is_tried_again_and_every_outcome_is_logged(tmp_path, monkeypatch):
    monkeypatch.setattr(CL, "CREATE_RETRY_S", 0.01)
    monkeypatch.setattr(PR, "SIG_PAGE", 2)
    w = store.Writer(tmp_path)
    col = CL.Collector(w, None, amm=True, meta=False)
    col.backfill = True
    col.late_log = CL.Tap(tmp_path / "late_reads.jsonl")
    rpc = {A: chain(A, [["s1"]], fail=1)[0],              # a 429 first, then read
           B: chain(B, [["x", "y"]] * 60)[0],             # more than CREATE_PAGES pages
           C: chain(C, [["s1"]], fail=99)[0],             # never answers
           D: lambda m, p: {"result": {"slot": 1, "meta": {"logMessages": []}}} if m == "getTransaction"
           else {"result": [{"signature": "z"}]}}         # the oldest transaction holds no creation
    read = lambda mint, curve: PR.creation(mint, curve, rpc[mint], pages=CL.CREATE_PAGES)   # noqa: E731
    done = lambda: col.counts["create_read"] and col.counts["create_read_failed"]           # noqa: E731
    run_worker(col, read, [completion(m, f"k{i}", 10 + i) for i, m in enumerate((A, B, C, D))], done)
    col.late_log.close()
    log = [json.loads(x) for x in (tmp_path / "late_reads.jsonl").read_text().splitlines()]
    by = {}
    for r in log:
        by.setdefault(r["mint"], []).append((r["outcome"], r["try"]))
    assert by[A] == [("retry", 0), ("read", 1)]
    assert by[B] == [("pages", 0)], "a curve past the pages is not tried again"
    assert by[C] == [("retry", 0), ("retry", 1), ("retry", 2), ("failed", 3)] and CL.CREATE_TRIES == 4
    assert by[D] == [("empty", 0)]
    assert "429" in [r for r in log if r["mint"] == C][-1]["why"]
    w.flush(T0)
    assert store.read("creates_late", store.days(tmp_path) or [store.day_of(T0 - 86_400_000 * 90)],
                      tmp_path)["mint"].to_list() == [A]
    assert col.counts["create_missed"] == 4 and col.counts["create_read_error"] == 5


def test_a_read_dropped_for_a_full_queue_is_asked_again(tmp_path):
    col = CL.Collector(None, None, amm=True, meta=False)
    col.backfill = True
    col.late_log = CL.Tap(tmp_path / "late_reads.jsonl")

    async def go():
        col.loop, col.create_q = asyncio.get_running_loop(), asyncio.Queue(maxsize=1)
        col.handle(note(*completion(A, "kA", 1)), T0)
        col.handle(note(*completion(B, "kB", 2)), T0)
        await asyncio.sleep(0)
        assert col.create_q.qsize() == 1 and col.counts["create_read_dropped"] == 1
        col.create_q.get_nowait()
        col.handle(note("mB", 3, logs_for((E.PUMP, "CompletePumpAmmMigrationEvent", mig(B)))), T0 + 1)
        await asyncio.sleep(0)
        assert col.create_q.get_nowait()[0] == B, "B is asked again at its migration"
    asyncio.run(go())
    col.late_log.close()
    assert [json.loads(x)["outcome"] for x in (tmp_path / "late_reads.jsonl").read_text().splitlines()] == ["dropped"]


# ---------------------------------------------------------------- coverage

def recorded(root):
    """A recorded fragment of 2026-11-14's kind: A's creation came on the stream five days before its migration, B's
    was read late (its row on its creation day, months back), C's read failed, D's was never logged."""
    w = store.Writer(root)
    w.write({"creates": [{"t": T0 - 5 * 86_400_000, "mint": A}],
             "creates_late": [{"t": T0 - 90 * 86_400_000, "mint": B, "late": T0 + 9}],
             "other": [{"kind": "migrate", "t": T0 + 1_000 * k, "mint": m, "pool": f"p{k}"}
                       for k, m in enumerate((A, B, C, D))]
             + [{"kind": "pool_state", "t": T0 + 9_000, "mint": m, "pool": "p"} for m in (A, B, C, D)]})
    (root / "late_reads.jsonl").write_text("\n".join(json.dumps(r) for r in [
        {"t": T0, "mint": C, "outcome": "retry", "why": "RuntimeError: HTTP Error 429", "try": 0},
        {"t": T0 + 1, "mint": C, "outcome": "failed", "why": "RuntimeError: HTTP Error 429", "try": 3},
        {"t": T0 + 2, "mint": B, "outcome": "read", "why": "", "try": 0}]) + "\n")
    (root / "links.jsonl").write_text("\n".join(json.dumps(r) for r in [
        {"t": T0, "link": "PumpSwap/0", "why": "closed 1006", "up_s": 41.0, "texts": 800, "wait_s": 0.4},
        {"t": T0 + 5, "link": "PumpSwap/1", "why": "connect WSServerHandshakeError 429", "up_s": 0.2, "texts": 0,
         "wait_s": 1.1},
        {"t": T0 + 9, "link": "pump.fun/2", "why": "silent", "up_s": 300.0, "texts": 9000, "wait_s": 0.5},
        {"t": T0 - 86_400_000, "link": "PumpSwap/0", "why": "closed 1006", "up_s": 1, "texts": 2, "wait_s": 1}]) + "\n")


def test_coverage_counts_a_creation_on_any_day_and_splits_stream_and_late(tmp_path):
    recorded(tmp_path)
    res = CV.build([DAY], tmp_path, tmp_path / "none.json")
    m = res["days"][DAY]["migrated"]
    assert (m["coins"], m["creation"], m["creation_stream"], m["creation_late"]) == (4, 2, 1, 1)
    assert m["creation_share"] == 0.5 and m["creation_stream_share"] == 0.25 and m["creation_late_share"] == 0.25
    assert m["missing"] == {"n": 2, "by": {"failed": 1, "none logged": 1}, "why": {"RuntimeError: HTTP Error 429": 1}}
    links = res["days"][DAY]["links"]
    assert links["PumpSwap"] == {"drops": 2, "short": 2, "no_data": 1,
                                 "why": {"closed 1006": 1, "connect WSServerHandshakeError 429": 1}}
    assert links["pump.fun"]["drops"] == 1 and links["pump.fun"]["short"] == 0
    res["t"] = T0 + 86_400_000                            # written the next day: DAY is a full day
    md = CV.report_md(res)
    assert "| from stream | late |" in md and "25.0%" in md and "failed 1" in md and "none logged 1" in md
    assert "| PumpSwap | 2 | 2 | 1 |" in md and "—" not in md
    # a day written before C2 (no split) still renders
    old = json.loads(json.dumps(res))
    for k in ("creation_stream_share", "creation_late_share", "missing"):
        del old["days"][DAY]["migrated"][k]
    assert "n/a" in CV.report_md(old)


def test_the_check_is_red_under_95_percent_creation_on_a_full_day(tmp_path, monkeypatch):
    recorded(tmp_path)
    monkeypatch.setattr(CV, "CREATE_FROM", DAY)
    res = CV.build([DAY], tmp_path, tmp_path / "none.json")
    res["t"] = T0 + 86_400_000
    ok, msg = CV.check(res, res["t"])
    assert not ok and "creation coverage under 95.0%" in msg and "2 of 4" in msg and "failed 1" in msg
    res["t"] = T0 + 3_600_000                             # the same day still running: not judged
    assert CV.check(res, res["t"])[0]
    res["t"], res["create_from"] = T0 + 86_400_000, store.day_of(T0 + 86_400_000)
    assert CV.check(res, res["t"])[0], "a day before the fix is reported, not judged"
    full = json.loads(json.dumps(res))
    full["create_from"] = DAY
    full["days"][DAY]["migrated"].update(creation=19, coins=20, creation_share=0.95)
    assert CV.check(full, full["t"])[0], "95 % is enough"
    assert CV.CREATE_MIN == 0.95


# ---------------------------------------------------------------- the links

class FakeWS:
    def __init__(self, texts: int):
        self.msgs = [aiohttp.WSMessage(aiohttp.WSMsgType.TEXT, '{"jsonrpc":"2.0","result":1,"id":1}', None)]
        self.msgs += [aiohttp.WSMessage(aiohttp.WSMsgType.TEXT, note(f"s{k}", 1, []), None) for k in range(texts)]
        self.msgs.append(aiohttp.WSMessage(aiohttp.WSMsgType.CLOSE, 1006, None))
        self.close_code = 1006

    async def send_str(self, s):
        pass

    async def receive(self):
        return self.msgs.pop(0)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class FakeSession:
    """The public endpoint as it behaved since 2026-11-03: it takes the link, sends notifications, drops it within
    seconds; `stop` after `n` connects."""
    def __init__(self, stop, n: int, texts: int):
        self.stop, self.n, self.texts, self.connects = stop, n, texts, 0

    def ws_connect(self, url, **kw):
        self.connects += 1
        if self.connects >= self.n:
            self.stop.set()
        return FakeWS(self.texts)


def waits_of(col, texts: int, n: int = 6) -> list[float]:
    waits, real = [], asyncio.sleep

    async def sleep(s):
        waits.append(s)
        await real(0)

    async def go():
        stop = asyncio.Event()
        asyncio.sleep = sleep
        try:
            await col.stream(FakeSession(stop, n, texts), "wss://example.invalid", E.PUMP_AMM, 0, stop)
        finally:
            asyncio.sleep = real
    asyncio.run(go())
    return waits


def test_a_link_the_endpoint_drops_comes_back_at_once_in_the_lab(tmp_path, monkeypatch):
    monkeypatch.setattr(CL.random, "random", lambda: 0.5)
    lab = CL.Collector(None, None, amm=True, meta=False)
    lab.link_stats, lab.link_log = {}, CL.Tap(tmp_path / "links.jsonl")
    assert waits_of(lab, texts=3) == [0.5] * 5
    lab.link_log.close()
    st = lab.heartbeat()["links"]["PumpSwap/0"]
    assert st["drops"] == 5 and st["short"] == 5 and st["closed"] == 5 and st["no_data"] == 0
    rows = [json.loads(x) for x in (tmp_path / "links.jsonl").read_text().splitlines()]
    assert len(rows) == 5 and rows[0]["why"] == "closed 1006" and rows[0]["texts"] == 4
    # a link refused before any notification still backs off
    lab2 = CL.Collector(None, None, amm=True, meta=False)
    lab2.link_stats = {}
    assert waits_of(lab2, texts=0) == [0.5, 1.0, 2.0, 4.0, 8.0]
    assert lab2.link_stats["PumpSwap/0"]["no_data"] == 5
    # C1's backoff, which the live service keeps: every short life doubled the wait up to 60 s
    live = CL.Collector(None, None, amm=True, meta=False)
    assert waits_of(live, texts=3) == [0.5, 1.0, 2.0, 4.0, 8.0] and "links" not in live.heartbeat()


def test_the_live_service_collector_keeps_c1(monkeypatch):
    from lab.pumpfun_rt import live_service as LS
    col = LS.LiveCollector(None, None, amm=True, meta=False)
    assert col.link_stats is None and col.late_log is None and col.link_log is None and col.create_q is None
    assert LS.AMM_LINKS == int(__import__("os").environ.get("PYTHIA_PF_LIVE_AMM_LINKS", "2"))
    assert CL.AMM_LINKS == int(__import__("os").environ.get("PYTHIA_PF_AMM_LINKS", "3"))
