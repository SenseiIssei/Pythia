"""C1 (2026-11-02): the lab's recorder completes what the stream lost (a migration it never brought: the pool is
known from the coin's canonical pool and read from the chain), keeps base_supply and can_boost, and reports its
daily coverage (coverage.py). No network, no wallet.

Run from research/lab:  python -m pytest tests/test_pumpfun_coverage_c1.py
"""

from __future__ import annotations

import json

import polars as pl

from lab.pumpfun_rt import collector as CL
from lab.pumpfun_rt import coverage as CV
from lab.pumpfun_rt import events as E
from lab.pumpfun_rt import poolread as PR
from lab.pumpfun_rt import store
from lab.pumpfun_rt import txbuild as TB
from test_pumpfun_pool_read_f1f2 import BASE_VAULT, QUOTE_VAULT, fake_rpc, pool_account, vault
from test_pumpfun_rt import DEV, T0, create_vals, key, logs_for, note

SOL = 10 ** 9
A, B, C = key(51), key(52), key(53)          # A migrates on the stream; B's and C's migrations are lost
DAY = store.day_of(T0)


def buy(pool: str, boost: bool = True) -> dict:
    return {"timestamp": T0 // 1000, "base_amount_out": 10, "quote_amount_in": 5, "pool_base_token_reserves": 1000,
            "pool_quote_token_reserves": 100, "pool": pool, "user": DEV, "can_boost": boost,
            "base_supply": 10 ** 15, "virtual_quote_reserves": 7}


def mig(mint: str) -> dict:
    return {"user": DEV, "mint": mint, "mint_amount": 1, "sol_amount": 85 * SOL, "bonding_curve": key(4),
            "timestamp": T0 // 1000, "pool": TB.canonical_pool(mint)}


def recorded_day() -> list[tuple[str, int, int, list[str]]]:
    """A recorded day as the stream handed it over: (signature, slot, receive ms, logs). B completes and trades in
    its pool, C only trades in its pool; neither migration came."""
    out = [(f"c{i}", 100 + i, T0 + i * 1000, logs_for((E.PUMP, "CreateEvent", create_vals(mint=m))))
           for i, m in enumerate((A, B, C))]
    out.append(("mA", 110, T0 + 10_000, logs_for((E.PUMP, "CompletePumpAmmMigrationEvent", mig(A)))))
    out.append(("kB", 111, T0 + 11_000, logs_for((E.PUMP, "CompleteEvent", {"user": DEV, "mint": B,
                                                                                "bonding_curve": key(5),
                                                                                "timestamp": T0 // 1000}))))
    out.append(("bB", 112, T0 + 12_000, logs_for((E.PUMP_AMM, "BuyEvent", buy(TB.canonical_pool(B))))))
    out.append(("bC", 113, T0 + 13_000, logs_for((E.PUMP_AMM, "BuyEvent", buy(TB.canonical_pool(C), False)))))
    out.append(("bX", 114, T0 + 14_000, logs_for((E.PUMP_AMM, "BuyEvent", buy(key(60))))))   # an old pool
    return out


def replay(backfill: bool, root=None):
    rows, wanted = [], []
    w = store.Writer(root) if root else None
    col = CL.Collector(w, lambda table, row: rows.append((table, row)), amm=True, meta=False)
    col.backfill = backfill
    col.want_pool = lambda row: wanted.append((row["mint"], row["pool"]))
    for sig, slot, ms, logs in recorded_day():
        col.handle(note(sig, slot, logs), ms)
    return col, rows, wanted, w


def test_a_recorded_day_with_lost_migrations_gets_their_pools():
    col, rows, wanted, _ = replay(True)
    assert wanted == [(A, TB.canonical_pool(A)), (B, TB.canonical_pool(B)), (C, TB.canonical_pool(C))]
    amm = [r for t, r in rows if t == "amm"]
    assert [r["mint"] for r in amm] == [B, C], "the old pool's trade stays dropped"
    assert amm[0]["can_boost"] is True and amm[0]["base_supply"] == 10 ** 15 and amm[1]["can_boost"] is False
    assert col.counts["migrate_missed_amm"] == 2 and not col.complete_wait
    # the same day without C1 (the live service's collector): the pools of B and C are never known
    col, rows, wanted, _ = replay(False)
    assert wanted == [(A, TB.canonical_pool(A))] and not [r for t, r in rows if t == "amm"]
    assert "base_supply" not in json.dumps(rows)


def test_a_completion_without_migration_reads_the_pool_after_the_wait():
    col = CL.Collector(None, None, amm=True, meta=False)
    col.backfill, wanted = True, []
    col.want_pool = lambda row: wanted.append(row["mint"])
    col.handle(note("kB", 111, logs_for((E.PUMP, "CompleteEvent", {"user": DEV, "mint": B, "bonding_curve": key(5),
                                                                   "timestamp": 1}))), T0)
    assert col.check_completes(T0 + CL.COMPLETE_WAIT_MS - 1) == 0 and not wanted
    assert col.check_completes(T0 + CL.COMPLETE_WAIT_MS) == 1 and wanted == [B]
    assert col.pools[TB.canonical_pool(B)][0] == B and col.counts["migrate_missed_complete"] == 1
    # its migration arriving late is stored, nothing is read twice
    assert col.handle(note("mB", 120, logs_for((E.PUMP, "CompletePumpAmmMigrationEvent", mig(B)))), T0 + 30_000) == 1
    assert wanted == [B]
    # a completion whose migration comes in time is not read by C1
    col.handle(note("kA", 130, logs_for((E.PUMP, "CompleteEvent", {"user": DEV, "mint": A, "bonding_curve": key(5),
                                                                   "timestamp": 1}))), T0)
    col.handle(note("mA", 131, logs_for((E.PUMP, "CompletePumpAmmMigrationEvent", mig(A)))), T0 + 1_000)
    assert col.check_completes(T0 + 60_000) == 0 and wanted == [B, A] and not col.complete_wait


def test_the_new_columns_are_stored_and_old_files_still_read(tmp_path):
    old = store.Writer(tmp_path)
    old.write({"amm": [{"t": T0, "pool": "p", "mint": A, "buy": True}]})
    pq_old = next((tmp_path / "amm" / f"date={DAY}").glob("*.parquet"))
    import pyarrow.parquet as pq
    t = pq.read_table(pq_old).drop(["base_supply", "can_boost"])        # a part written before C1
    pq.write_table(t, pq_old)
    _, _, _, w = replay(True, tmp_path)
    w.flush(T0)
    w.write({"other": [{"kind": "pool_state", "t": T0, "mint": B, "pool": "p", "pb": 1, "pq": 2, "vq": 3,
                        "base_supply": 10 ** 15, "can_boost": True}]})
    amm = store.read("amm", [DAY], tmp_path).sort("t")
    assert amm["can_boost"].to_list() == [None, True, False] and amm["base_supply"].to_list()[1:] == [10 ** 15] * 2
    sub = store.read("amm", [DAY], tmp_path, cols=["mint", "base_supply"])
    assert sub.height == 3 and sub["base_supply"].null_count() == 1
    ps = store.read("other", [DAY], tmp_path).filter(pl.col("kind") == "pool_state")
    assert ps["base_supply"].to_list() == [10 ** 15] and ps["can_boost"].to_list() == [True]
    assert store.compact(DAY, tmp_path) > 0 and store.read("amm", [DAY], tmp_path).height == 3


def test_the_read_with_supply_adds_the_mints_supply_and_the_boost_flag():
    mint = bytearray(82)
    mint[36:44] = (10 ** 15).to_bytes(8, "little")
    accts = {key(1): pool_account(vq=5), BASE_VAULT: vault(9), QUOTE_VAULT: vault(8), A: bytes(mint)}
    call, calls = fake_rpc(accts)
    row = PR.read(A, key(1), call=call, clock=lambda: T0, with_supply=True)
    assert row["base_supply"] == 10 ** 15 and row["can_boost"] is True and len(calls) == 2
    assert calls[1][1][0] == [BASE_VAULT, QUOTE_VAULT, A]
    assert set(row) <= {f.name for f in store.SCHEMAS["other"]}
    call, _ = fake_rpc({**accts, key(1): pool_account(vq=0)})
    assert PR.read(A, key(1), call=call, with_supply=True)["can_boost"] is False
    assert "base_supply" not in PR.read(A, key(1), call=call), "the live service's read is unchanged"


# ---------------------------------------------------------------- the coverage report

def coverage_store(root):
    w = store.Writer(root)
    w.write({"creates": [{"t": T0, "mint": A, "bts": T0 // 1000 - 2}, {"t": T0, "mint": B, "bts": T0 // 1000 - 4}],
             "other": [{"kind": "migrate", "t": T0 + 5_000, "mint": A, "pool": "pa", "bts": T0 // 1000 - 1},
                       {"kind": "pool_state", "t": T0 + 6_000, "mint": A, "pool": "pa", "pb": 1, "pq": 1},
                       {"kind": "complete", "t": T0 + 7_000, "mint": B, "bts": T0 // 1000 - 3},
                       {"kind": "migrate", "t": T0 + 8_000, "mint": C, "pool": "pc", "bts": T0 // 1000},
                       {"kind": "pool_state", "t": T0 + 9_000, "mint": C, "pool": "pc", "pb": 1, "pq": 1},
                       {"kind": "gap", "t": T0 + 20_000, "t0": T0 + 8_000, "user": E.PUMP_AMM},
                       {"kind": "gap", "t": T0 + 30_000, "t0": T0 + 27_000, "user": E.PUMP}],
             "amm": [{"t": T0 + 10_000, "pool": "pa", "mint": A, "bts": T0 // 1000 - 10}]})


def test_the_coverage_report_counts_the_record(tmp_path):
    coverage_store(tmp_path)
    live = tmp_path / "live_trades.json"
    live.write_text(json.dumps({"t": 0, "trades": [
        {"mint": A, "rule": "P_pool0", "signal_ms": T0 + 6_000}, {"mint": A, "rule": "P_pool0", "signal_ms": T0 + 9e3},
        {"mint": B, "rule": "P_pool0_wait", "signal_ms": T0 + 8_000},
        {"mint": C, "rule": "P_cmig_model", "signal_ms": T0 + 9_000},
        {"mint": key(70), "rule": "P_pool0", "signal_ms": T0 - 3 * 86_400_000}]}))
    res = CV.build([DAY], tmp_path, live)
    r = res["days"][DAY]
    assert r["migrated"] == {"coins": 3, "pool_state": 2, "creation": 2, "both": 1, "pool_state_share": 0.6667,
                             "creation_share": 0.6667, "both_share": 0.3333}
    assert r["live"] == {"mints": 3, "covered": 1, "no_creation": 1, "no_pool_state": 1, "share": 0.3333,
                         "missing": sorted([B, C])}
    g = r["gaps"]
    assert g["by_program"]["PumpSwap"] == {"n": 1, "total_s": 12.0, "max_s": 12.0}
    assert [x["len_s"] for x in g["longest"]] == [12.0, 3.0] and g["longest"][0]["program"] == "PumpSwap"
    assert r["clock"]["creates"] == {"n": 2, "median_s": 3.0, "p90_s": 3.8}
    assert r["clock"]["amm"]["median_s"] == 20.0 and r["clock"]["all"]["n"] == 6
    md = CV.report_md(res)
    assert DAY in md and "33.3%" in md and "\u2014" not in md
    # merged with an older report, at most KEEP_DAYS kept
    again = CV.build([DAY], tmp_path, live, old={"days": {"2026-01-01": r}})
    assert list(again["days"]) == ["2026-01-01", DAY]


def test_old_parts_without_a_block_time_or_the_new_columns_still_count(tmp_path):
    import pyarrow as pa
    import pyarrow.parquet as pq
    d = tmp_path / "other" / f"date={DAY}"
    d.mkdir(parents=True)
    pq.write_table(pa.table({"kind": ["migrate"], "t": [T0], "mint": [A], "pool": ["p"]}), d / "old.parquet")
    r = CV.day_coverage(DAY, [], tmp_path)
    assert r["migrated"]["coins"] == 1 and r["live"]["share"] is None and r["clock"]["all"]["n"] == 0


def test_the_check_turns_red_under_the_threshold_and_when_stale():
    def res(covered, mints, day="2026-11-04", t=T0):
        return {"t": t, "live_min": CV.LIVE_MIN, "c1_from": CV.C1_FROM, "days": {day: {
            "day": day, "live": {"mints": mints, "covered": covered, "no_creation": 0, "no_pool_state": mints - covered,
                                 "share": covered / mints if mints else None, "missing": []},
            "migrated": {"both_share": 0.99}, "clock": {"all": {"p90_s": 12.0}}}}}
    assert CV.check(res(10, 10), T0)[0] and CV.check(res(9, 10), T0)[0]
    ok, msg = CV.check(res(8, 10), T0)
    assert not ok and "under 90.0%" in msg and "8 of 10" in msg
    assert CV.check(res(0, 10, day="2026-10-30"), T0)[0], "a day before C1 is reported, not judged"
    assert CV.check(res(0, 0), T0)[0], "a day without live mints is no alarm"
    assert not CV.check(res(10, 10), T0 + (CV.STALE_H + 1) * 3_600_000)[0]
