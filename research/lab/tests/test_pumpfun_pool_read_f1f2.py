"""F1 and F2 (2026-10-28): the pool's reserves read from the chain at its migration (poolread.py, the engine's
pool_state, the collector's pool worker, the store's columns) and the collector's tap of new coins for the live
service (collector.Tap and TapReader). No network, no wallet.

Run from research/lab:  python -m pytest tests/test_pumpfun_pool_read_f1f2.py
"""

from __future__ import annotations

import asyncio
import base64
import json

from lab.pumpfun_rt import collector as CL
from lab.pumpfun_rt import poolread as PR
from lab.pumpfun_rt import sim
from lab.pumpfun_rt import store
from lab.pumpfun_rt import txbuild as TB
from test_pumpfun_exit_runners import BASE0, QUOTE0, engine
from test_pumpfun_exits_y8 import LatePool
from test_pumpfun_rt import MINT, POOL, T0, key

BASE_VAULT, QUOTE_VAULT = key(41), key(42)


def pool_account(vq: int = -5_000_000) -> bytes:
    data = bytearray(300)
    for name, k in (("pool_base_token_account", BASE_VAULT), ("pool_quote_token_account", QUOTE_VAULT)):
        off = TB.OFFSETS[("Pool", name)]
        data[off:off + 32] = TB.key(k)
    off = TB.OFFSETS[("Pool", "virtual_quote_reserves")]
    data[off:off + 16] = vq.to_bytes(16, "little", signed=True)
    return bytes(data)


def vault(amount: int) -> bytes:
    data = bytearray(165)
    data[64:72] = amount.to_bytes(8, "little")
    return bytes(data)


def fake_rpc(accounts: dict[str, bytes | None], slot: int = 777):
    calls = []

    def call(method, params):
        calls.append((method, params))
        assert method == "getMultipleAccounts" and params[1]["commitment"] == "confirmed"
        vals = [None if accounts.get(k) is None else {"data": [base64.b64encode(accounts[k]).decode(), "base64"]}
                for k in params[0]]
        return {"result": {"context": {"slot": slot}, "value": vals}}
    return call, calls


# ---------------------------------------------------------------- the read

def test_the_read_takes_the_vaults_and_the_signed_virtual_quote():
    call, calls = fake_rpc({POOL: pool_account(), BASE_VAULT: vault(BASE0), QUOTE_VAULT: vault(QUOTE0)})
    row = PR.read(MINT, POOL, call=call, clock=lambda: T0 + 400)
    assert row == {"kind": "pool_state", "t": T0 + 400, "slot": 777, "tx": None, "mint": MINT, "user": None,
                   "pool": POOL, "pb": BASE0, "pq": QUOTE0, "vq": -5_000_000}
    assert [c[1][0] for c in calls] == [[POOL], [BASE_VAULT, QUOTE_VAULT]]
    assert set(row) <= {f.name for f in store.SCHEMAS["other"]}, "every field is a column of the store"


def test_no_row_while_the_pool_or_a_vault_is_not_there():
    assert PR.read(MINT, POOL, call=fake_rpc({})[0]) is None
    assert PR.read(MINT, POOL, call=fake_rpc({POOL: pool_account(), BASE_VAULT: vault(BASE0)})[0]) is None
    assert PR.read(MINT, POOL, call=fake_rpc({POOL: pool_account(), BASE_VAULT: vault(0),
                                              QUOTE_VAULT: vault(QUOTE0)})[0]) is None


def test_switches():
    assert PR.enabled({}) and not PR.enabled({"PYTHIA_PF_POOL_READ": "0"})
    assert PR.rpc_url({}) == PR.DEFAULT_RPC and PR.rpc_url({"PYTHIA_PF_POOL_RPC": " https://x "}) == "https://x"


# ---------------------------------------------------------------- the engine

def test_the_read_lets_the_wait_enter_before_any_pool_trade():
    eng = engine("P_pool0", "P_pool0_wait")
    LatePool(eng)
    eng.advance(T0 + 500)
    assert set(eng.pipes[0].waiting[MINT]) == {"P_pool0_wait"}
    sim.feed_row(eng, "other", {"kind": "pool_state", "t": T0 + 800, "slot": 60_000, "mint": MINT, "pool": POOL,
                                "pb": BASE0, "pq": QUOTE0 + 5 * 10 ** 6, "vq": -5 * 10 ** 6})
    tok = eng.tokens[MINT]
    assert (tok.pb, tok.pq) == (BASE0, QUOTE0) and tok.amm_slot == 60_000
    pos = list(eng.pipes[0].pos.values())
    assert [p["rule"] for p in pos] == ["P_pool0_wait"] and pos[0]["signal_ms"] == T0 + 800
    assert not eng.pipes[0].waiting and eng.skipped[("P_pool0", "no pool state")] == 1


def test_a_read_after_the_wait_or_once_the_stream_has_the_state_changes_nothing():
    eng = engine("P_pool0_wait")
    pool = LatePool(eng)
    eng.advance(T0 + 5_500)
    eng.pool_state(T0 + 6_000, MINT, POOL, BASE0, QUOTE0)
    assert eng.skipped[("P_pool0_wait", "no pool state")] == 1 and not eng.pipes[0].pos
    pool.open(T0 + 7_000)
    state = (eng.tokens[MINT].pb, eng.tokens[MINT].pq)
    eng.pool_state(T0 + 7_500, MINT, POOL, 1, 1)
    assert (eng.tokens[MINT].pb, eng.tokens[MINT].pq) == state
    eng.pool_state(T0 + 7_600, "unknown", POOL, BASE0, QUOTE0)    # a coin the engine does not know
    eng.pool_state(T0 + 7_700, MINT, "another pool", BASE0, QUOTE0)


# ---------------------------------------------------------------- the collector's worker

def test_a_migration_is_read_and_its_row_kept():
    rows = []
    col = CL.Collector(None, lambda table, row: rows.append((table, row)), amm=True, meta=False)

    async def go():
        col.loop, col.pool_q = asyncio.get_running_loop(), asyncio.Queue(maxsize=CL.POOL_QUEUE)
        n = {"k": 0}

        def read(mint, pool):
            n["k"] += 1
            return None if n["k"] == 1 else {"kind": "pool_state", "t": T0, "mint": mint, "pool": pool,
                                             "pb": BASE0, "pq": QUOTE0, "vq": 0}
        worker = asyncio.create_task(col.pool_worker(read))
        col.want_pool({"mint": MINT, "pool": POOL})
        col.want_pool({"mint": MINT, "pool": None})          # no pool: nothing to read
        for _ in range(100):
            await asyncio.sleep(0.03)
            if rows:
                break
        worker.cancel()
        return n["k"]
    CL.POOL_RETRY_S, old = 0.01, CL.POOL_RETRY_S
    try:
        reads = asyncio.run(go())
    finally:
        CL.POOL_RETRY_S = old
    assert reads == 2, "the first read found nothing yet, the second the pool"
    assert rows == [("other", {"kind": "pool_state", "t": T0, "mint": MINT, "pool": POOL, "pb": BASE0,
                               "pq": QUOTE0, "vq": 0})] and col.counts["pool_read"] == 1


def test_without_a_queue_a_migration_is_left_to_the_stream():
    col = CL.Collector(None, None)
    col.want_pool({"mint": MINT, "pool": POOL})
    assert col.counts["pool_read_dropped"] == 0 and col.pool_q is None


# ---------------------------------------------------------------- the tap

def test_the_tap_hands_over_each_new_coin_once_and_survives_a_rotation(tmp_path):
    p = tmp_path / "tap" / "creates.jsonl"
    tap = CL.Tap(p, max_bytes=400)
    reader = CL.TapReader(p)
    assert reader.poll() == []
    tap.add({"t": T0, "mint": "A", "creator": "C"})
    tap.add({"t": T0 + 1, "mint": "B", "creator": "C"})
    assert [r["mint"] for r in reader.poll()] == ["A", "B"] and reader.poll() == []
    with open(p, "a", encoding="utf-8") as fh:
        fh.write('{"t": 1, "mint": "half')                   # a line still being written waits
    assert reader.poll() == []
    with open(p, "a", encoding="utf-8") as fh:
        fh.write('"}\n')
    assert [r["mint"] for r in reader.poll()] == ["half"]
    for i in range(10):                                        # past max_bytes: rotated to .1
        tap.add({"t": T0 + i, "mint": f"M{i}", "creator": "C" * 30})
    assert (tmp_path / "tap" / "creates.jsonl.1").exists()
    reader.poll()
    tap.add({"t": T0, "mint": "Z", "creator": "C"})
    assert [r["mint"] for r in reader.poll()][-1] == "Z", "after a rotation the new file is read from its start"
    tap.close()


def test_a_reader_starts_at_the_end_and_without_a_file_reads_nothing(tmp_path):
    p = tmp_path / "creates.jsonl"
    assert CL.TapReader(p).poll() == []
    p.write_text(json.dumps({"mint": "old"}) + "\n")
    r = CL.TapReader(p)
    assert r.poll() == []
    with open(p, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"mint": "new"}) + "\n")
    assert [x["mint"] for x in r.poll()] == ["new"]


def test_a_creators_newer_coin_arriving_first_is_no_negative_time():
    import math
    from lab.pumpfun_rt.tokens import CreatorBook
    book = CreatorBook()
    book.created("C", T0 + 5_000)                              # the newer coin came first on the links
    snap = book.snapshot("C", T0)
    assert snap["since_s"] == 0.0 and math.log1p(snap["since_s"]) == 0.0
    assert book.snapshot("C", T0 + 8_000)["since_s"] == 3.0 and book.snapshot("D", T0)["since_s"] is None


def test_the_collector_taps_create_rows_only(tmp_path):
    col = CL.Collector(None, None)
    col.tap = CL.Tap(tmp_path / "c.jsonl")
    col.keep("creates", {"t": T0, "mint": "A"})
    col.keep("trades", {"t": T0, "mint": "A"})
    col.tap.close()
    assert [json.loads(x)["mint"] for x in (tmp_path / "c.jsonl").read_text().splitlines()] == ["A"]
