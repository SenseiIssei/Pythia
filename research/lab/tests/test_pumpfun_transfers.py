"""Token transfers of migrated coins (transfers.py, 2026-10-29): the log triage of a notification (failed, a trade,
a token transfer), a getTransaction result (jsonParsed, written by hand in its recorded shape) into transfer rows
with the owners and an inner TransferChecked, the watch's subscriptions and expiry, the bounded fetch queue, the
worker, the collector's hook and the store's table. No network, no wallet.

Run from research/lab:  python -m pytest tests/test_pumpfun_transfers.py
"""

from __future__ import annotations

import asyncio
import collections
import json

from lab.pumpfun_rt import collector as CL
from lab.pumpfun_rt import events as E
from lab.pumpfun_rt import store
from lab.pumpfun_rt import transfers as TR
from test_pumpfun_rt import DEV, MINT, POOL, T0, key, logs_for, note

A, B, C, D = key(51), key(52), key(53), key(54)                       # wallets
ACC_A, ACC_B, ACC_C, ACC_D, ACC_AO, ACC_DO = (key(i) for i in range(61, 67))   # their token accounts
OTHER, ROUTER, ATA = key(70), key(71), "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL"
SIG, SLOT, BTS = "5igTransfer", 400_000_123, 1_792_450_100
CB = "ComputeBudget111111111111111111111111111111"


# ---------------------------------------------------------------- a getTransaction result, by hand

def amount(n: int) -> dict:
    return {"amount": str(n), "decimals": 6, "uiAmount": n / 1e6, "uiAmountString": str(n / 1e6)}


def bal(i: int, mint: str, owner: str, n: int, program: str = TR.TOKEN_2022) -> dict:
    return {"accountIndex": i, "mint": mint, "owner": owner, "programId": program, "uiTokenAmount": amount(n)}


def checked(src: str, dst: str, auth: str, n: int, h=None) -> dict:
    return {"program": "spl-token", "programId": TR.TOKEN_2022, "stackHeight": h,       # as mainnet labels it
            "parsed": {"type": "transferChecked", "info": {"source": src, "destination": dst, "authority": auth,
                                                           "mint": MINT, "tokenAmount": amount(n)}}}


def plain(src: str, dst: str, auth: str, n: int, program: str = TR.TOKEN, h=None) -> dict:
    return {"program": "spl-token", "programId": program, "stackHeight": h,
            "parsed": {"type": "transfer", "info": {"source": src, "destination": dst, "authority": auth,
                                                    "amount": str(n)}}}


def raw(program: str, h=None) -> dict:
    return {"programId": program, "accounts": [A], "data": "3Bxs4h24hBtQy9rw", "stackHeight": h}


KEYS = [A, C, ACC_A, ACC_B, ACC_C, ACC_D, ACC_AO, ACC_DO, ROUTER, TR.TOKEN_2022, TR.TOKEN, ATA, MINT, OTHER]


def tx_fixture() -> dict:
    """A wallet A and a wallet C both move the coin to B in one transaction (C through some router program, an
    inner TransferChecked), C also sends some to D with a plain Transfer, and A moves another coin to D."""
    return {
        "slot": SLOT, "blockTime": BTS, "version": 0,
        "meta": {
            "err": None, "fee": 10_000, "preBalances": [10 ** 9] * len(KEYS), "postBalances": [10 ** 9] * len(KEYS),
            "preTokenBalances": [bal(2, MINT, A, 5_000), bal(4, MINT, C, 9_000), bal(5, MINT, D, 0),
                                 bal(6, OTHER, A, 100, TR.TOKEN), bal(7, OTHER, D, 0, TR.TOKEN)],
            "postTokenBalances": [bal(2, MINT, A, 4_000), bal(3, MINT, B, 1_700), bal(4, MINT, C, 8_000),
                                  bal(5, MINT, D, 300), bal(6, OTHER, A, 58, TR.TOKEN),
                                  bal(7, OTHER, D, 42, TR.TOKEN)],
            "innerInstructions": [
                {"index": 1, "instructions": [raw(TR.TOKEN_2022, 2)]},                 # the new account, made
                {"index": 3, "instructions": [checked(ACC_C, ACC_B, C, 700, 2)]}],
            "logMessages": [], "loadedAddresses": {"writable": [], "readonly": []}, "status": {"Ok": None}},
        "transaction": {
            "signatures": [SIG, "5igOfC"],
            "message": {
                "accountKeys": [{"pubkey": k, "signer": k in (A, C), "writable": True,
                                 "source": "transaction"} for k in KEYS],
                "recentBlockhash": "11111111111111111111111111111111",
                "instructions": [
                    raw(CB),
                    {"program": "spl-associated-token-account", "programId": ATA, "stackHeight": None,
                     "parsed": {"type": "createIdempotent", "info": {"account": ACC_B, "mint": MINT, "wallet": B,
                                                                     "source": A}}},
                    checked(ACC_A, ACC_B, A, 1_000),
                    raw(ROUTER),
                    plain(ACC_AO, ACC_DO, A, 42),                                    # another coin: not kept
                    plain(ACC_C, ACC_D, C, 300, TR.TOKEN_2022)]}}}


def row(src, dst, n, ix, outer=None, swap=False) -> dict:
    return {"t": T0, "slot": SLOT, "bts": BTS, "sig": SIG, "mint": MINT, "src": src, "dst": dst, "amount": n,
            "ix": ix, "outer": outer, "swap": swap}


def test_a_transaction_becomes_rows_with_owners_and_the_inner_transfer():
    rows = TR.parse_tx(tx_fixture(), MINT, SIG, 0, T0)
    assert rows == [row(A, B, 1_000, "transferChecked"),
                    row(C, B, 700, "transferChecked", outer=ROUTER),      # inner: the router it ran in
                    row(C, D, 300, "transfer")]                           # plain: the mint from the balances
    assert set(rows[0]) <= set(store.SCHEMAS["transfers"].names), "every field is a column of the store"
    assert TR.parse_tx(tx_fixture(), OTHER, SIG, 0, T0)[0]["amount"] == 42
    failed = tx_fixture()
    failed["meta"]["err"] = {"InstructionError": [2, "Custom"]}
    assert TR.parse_tx(failed, MINT, SIG, 0, T0) == []


def test_owners_fall_back_to_the_authority_and_null():
    tx = tx_fixture()
    tx["meta"]["preTokenBalances"] = [b for b in tx["meta"]["preTokenBalances"] if b["accountIndex"] != 2]
    tx["meta"]["postTokenBalances"] = [b for b in tx["meta"]["postTokenBalances"] if b["accountIndex"] not in (2, 3)]
    first = TR.parse_tx(tx, MINT, SIG, 0, T0)[0]
    assert (first["src"], first["dst"], first["ix"]) == (A, None, "transferChecked")   # Checked names its mint


def test_a_trades_own_legs_are_no_rows_and_a_transfer_beside_it_is_marked():
    tx = tx_fixture()
    ins = tx["transaction"]["message"]["instructions"]
    ins.append(raw(E.PUMP_AMM))                                            # a sale, top-level: its legs inside
    tx["meta"]["innerInstructions"].append({"index": len(ins) - 1, "instructions": [
        checked(ACC_B, ACC_D, B, 1_700, 2)]})
    tx["meta"]["innerInstructions"][1]["instructions"] = [                 # the router: a PumpSwap call and after it
        raw(E.PUMP_AMM, 2), checked(ACC_C, ACC_D, C, 5, 3), raw(TR.TOKEN_2022, 3),   # its own move to B
        checked(ACC_C, ACC_B, C, 700, 2)]
    rows = TR.parse_tx(tx, MINT, SIG, 0, T0)
    assert [(r["src"], r["dst"], r["amount"], r["outer"]) for r in rows] == [
        (A, B, 1_000, None), (C, B, 700, ROUTER), (C, D, 300, None)]
    assert all(r["swap"] for r in rows)
    assert TR.parse_tx(tx_fixture(), MINT, SIG, 0, T0)[0]["swap"] is False


# ---------------------------------------------------------------- the logs

def token_lines(depth: int = 1, ix: str = "TransferChecked", program: str = TR.TOKEN_2022) -> list[str]:
    return [f"Program {program} invoke [{depth}]", f"Program log: Instruction: {ix}",
            f"Program {program} consumed 2000 of 200000 compute units", f"Program {program} success"]


def sale_lines() -> list[str]:
    return ([f"Program {E.PUMP_AMM} invoke [1]", "Program log: Instruction: Sell"] + token_lines(2)
            + token_lines(2) + [f"Program {E.PUMP_AMM} success"])


def test_the_logs_tell_a_trade_a_transfer_and_nothing():
    cb = [f"Program {CB} invoke [1]", f"Program {CB} success"]
    assert TR.log_kind(cb + token_lines()) == "transfer"
    assert TR.log_kind(cb + token_lines(ix="Transfer", program=TR.TOKEN)) == "transfer"
    assert TR.log_kind(cb + [f"Program {ROUTER} invoke [1]"] + token_lines(2) + [f"Program {ROUTER} success"]) \
        == "transfer"                                                      # inner, no trade
    assert TR.log_kind(sale_lines()) == "pump"                             # the trade's own legs
    assert TR.log_kind(logs_for((E.PUMP_AMM, "SellEvent", {"pool": POOL, "user": DEV}))) == "pump"
    assert TR.log_kind(token_lines() + sale_lines()) == "pump+transfer"    # a transfer and a sale in one
    assert TR.log_kind([f"Program {ROUTER} invoke [1]", "Program log: Instruction: Transfer",
                        f"Program {ROUTER} success"]) is None              # not a token program's line
    assert TR.log_kind(cb + token_lines(ix="InitializeAccount3") + token_lines(ix="Burn")) is None
    assert TR.log_kind(cb + ["Log truncated"]) == "transfer"               # unknown: the fetch decides
    assert TR.log_kind(sale_lines()[:3] + ["Log truncated"]) == "pump"


def silent_lines(depth: int = 1) -> list[str]:
    """An SPL Token call as mainnet logs it since 2026-10: no instruction name."""
    return [f"Program {TR.TOKEN} invoke [{depth}]", f"Program {TR.TOKEN} consumed 201 of 200000 compute units",
            f"Program {TR.TOKEN} success"]


def test_a_silent_spl_token_call_is_fetched_only_for_an_spl_token_coin():
    ata = ([f"Program {TR.ATA} invoke [1]", "Program log: CreateIdempotent"] + silent_lines(2)
           + [f"Program {TR.ATA} success"])
    assert TR.log_kind(ata) is None                                        # an account made: no transfer
    assert TR.log_kind(ata + silent_lines()) == "silent"
    assert TR.log_kind([f"Program {ROUTER} invoke [1]"] + silent_lines(2) + [f"Program {ROUTER} success"]) \
        == "silent"
    assert TR.log_kind(silent_lines() + sale_lines()) == "pump"            # wrapping SOL before a sale looks so
    assert TR.log_kind(silent_lines() + token_lines()) == "transfer"
    counts = collections.Counter()
    w = TR.TransferWatch(lambda t, r: None, counts, clock=lambda: T0)
    assert w.note(MINT, 1, "s1", False, silent_lines(), T0) == "silent"   # the coin's program not known yet
    w.spl[MINT] = False
    assert w.note(MINT, 1, "s2", False, silent_lines(), T0) == "silent"   # a Token-2022 coin
    w.spl[MINT] = True
    assert w.note(MINT, 1, "s3", False, silent_lines(), T0) == "queued"
    assert (counts["xfer_silent"], counts["xfer_spl_silent"], counts["xfer_queued"]) == (2, 1, 1)


def test_a_watch_asks_its_coins_token_program_once(monkeypatch):
    monkeypatch.setattr(TR, "TRANSFER_PER_S", 1000.0)
    w = TR.TransferWatch(lambda t, r: None, collections.Counter(), clock=lambda: T0)
    asked = []

    def owner(mint):
        asked.append(mint)
        return TR.TOKEN if mint == MINT else TR.TOKEN_2022

    async def go():
        task = asyncio.create_task(w.worker(lambda sig: None, owner))
        w.watch(MINT, T0)
        w.watch(key(81), T0)
        for _ in range(100):
            await asyncio.sleep(0.01)
            if len(w.spl) == 2:
                break
        task.cancel()
    asyncio.run(go())
    assert asked == [MINT, key(81)] and w.spl == {MINT: True, key(81): False}


def test_failed_trades_and_quiet_transactions_are_skipped_and_counted():
    counts = collections.Counter()
    w = TR.TransferWatch(lambda t, r: None, counts, clock=lambda: T0)
    assert w.note(MINT, 1, "s1", True, token_lines(), T0) == "failed"
    assert w.note(MINT, 1, "s2", False, sale_lines(), T0) == "pump"
    assert w.note(MINT, 1, "s3", False, token_lines(ix="Burn"), T0) == "none"
    assert w.note(MINT, 1, "s4", False, token_lines() + sale_lines(), T0) == "queued"
    assert w.note(MINT, 1, "s5", False, token_lines(), T0) == "queued"
    assert (counts["xfer_failed"], counts["xfer_pump"], counts["xfer_none"], counts["xfer_pump_transfer"],
            counts["xfer_queued"], counts["xfer_notes"]) == (1, 1, 1, 1, 2, 5)
    assert w.q.get_nowait() == ("s4", MINT, 1, T0)


def test_silent_spl_calls_wait_behind_logged_transfers(monkeypatch):
    monkeypatch.setattr(TR, "SPL_SILENT_QUEUE", 2)
    counts = collections.Counter()
    w = TR.TransferWatch(lambda t, r: None, counts, queue=5, clock=lambda: T0)
    w.spl[MINT] = True
    got = [w.note(MINT, 1, f"s{i}", False, silent_lines(), T0) for i in range(3)]
    assert got == ["queued", "queued", "skipped"]                          # the guesses stop at two waiting
    assert w.note(MINT, 1, "t1", False, token_lines(), T0) == "queued"    # a logged transfer still gets in
    assert (counts["xfer_spl_silent"], counts["xfer_spl_skipped"], counts["xfer_dropped"]) == (2, 1, 0)


def test_a_full_queue_drops_and_counts_and_never_waits():
    counts = collections.Counter()
    w = TR.TransferWatch(lambda t, r: None, counts, queue=2, clock=lambda: T0)
    got = [w.note(MINT, 1, f"s{i}", False, token_lines(), T0) for i in range(5)]
    assert got == ["queued", "queued", "dropped", "dropped", "dropped"]
    assert counts["xfer_dropped"] == 3 and w.q.qsize() == 2 and w.status()["queue"] == 2


# ---------------------------------------------------------------- the watch

def answer(req: int, result) -> str:
    return json.dumps({"jsonrpc": "2.0", "result": result, "id": req})


def notification(sub: int, sig: str, logs: list[str], err=None) -> str:
    return json.dumps({"jsonrpc": "2.0", "method": "logsNotification",
                       "params": {"result": {"context": {"slot": SLOT}, "value": {"signature": sig, "err": err,
                                                                                  "logs": logs}},
                                  "subscription": sub}})


def sent(w) -> list[dict]:
    out = [json.loads(x) for x in w.out]
    w.out.clear()
    return out


def test_a_watch_subscribes_ends_after_its_half_hour_and_unsubscribes():
    now = {"t": T0}
    counts = collections.Counter()
    w = TR.TransferWatch(lambda t, r: None, counts, max_mints=2, clock=lambda: now["t"])
    assert w.watch(MINT, T0) and not w.watch(MINT, T0)                     # once
    assert not w.watch(key(80), T0 - TR.TRANSFER_WATCH_MS)                 # its half hour is over already
    assert w.watch(key(81), T0 - 60_000)
    assert not w.watch(key(82), T0) and counts["xfer_watch_full"] == 1
    assert sent(w) == []                                                   # nothing sent before a connection
    w.up()
    reqs = sent(w)
    assert [(r["method"], r["params"]) for r in reqs] == [
        ("logsSubscribe", [{"mentions": [MINT]}, {"commitment": "confirmed"}]),
        ("logsSubscribe", [{"mentions": [key(81)]}, {"commitment": "confirmed"}])]
    w.on_message(answer(reqs[0]["id"], 77), T0)
    w.on_message(answer(reqs[1]["id"], 78), T0)
    assert w.subs == {77: MINT, 78: key(81)}
    assert w.on_message(notification(77, "s1", token_lines()), T0 + 5) == "queued"
    assert w.on_message(notification(77, "s2", token_lines(), err={"x": 1}), T0 + 5) == "failed"
    assert w.on_message(notification(99, "s3", token_lines()), T0 + 5) is None          # no such subscription
    now["t"] = T0 + TR.TRANSFER_WATCH_MS - 60_000
    assert w.expire() == [key(81)]
    assert [(r["method"], r["params"]) for r in sent(w)] == [("logsUnsubscribe", [78])]
    assert w.on_message(notification(78, "s4", token_lines()), now["t"]) is None        # ended: ignored
    now["t"] = T0 + TR.TRANSFER_WATCH_MS - 1
    assert w.expire() == []
    now["t"] = T0 + TR.TRANSFER_WATCH_MS
    assert w.expire() == [MINT] and not w.until and not w.subs
    assert counts["xfer_expired"] == 2 and counts["xfer_queued"] == 1


def test_an_answer_after_the_end_unsubscribes_and_a_lost_link_is_a_gap():
    now = {"t": T0}
    rows = []
    w = TR.TransferWatch(lambda t, r: rows.append((t, r)), collections.Counter(), clock=lambda: now["t"])
    w.watch(MINT, T0)
    w.up()
    req = sent(w)[0]["id"]
    now["t"] = T0 + TR.TRANSFER_WATCH_MS
    w.expire()
    w.on_message(answer(req, 5), now["t"])
    assert [(r["method"], r["params"]) for r in sent(w)] == [("logsUnsubscribe", [5])]
    w.watch(key(81), now["t"])
    w.up()
    sent(w)
    w.down()
    assert not w.connected and w.down_since == now["t"]
    now["t"] += 7_000
    w.up()
    assert rows == [("transfers", {"t": now["t"], "t0": now["t"] - 7_000, "ix": "gap"})]
    assert len(sent(w)) == 1 and w.down_since is None                      # subscribed again
    w.down()
    now["t"] += 500
    w.up()
    assert len(rows) == 1, "under a second is no gap"


# ---------------------------------------------------------------- the worker, the collector, the store

def test_the_worker_retries_a_missing_transaction_and_keeps_its_rows(monkeypatch):
    monkeypatch.setattr(TR, "TRANSFER_PER_S", 1000.0)
    monkeypatch.setattr(TR, "RETRY_S", 0.01)
    rows, counts = [], collections.Counter()
    w = TR.TransferWatch(lambda t, r: rows.append((t, r)), counts, clock=lambda: T0)
    calls = []

    def fetch(sig):
        calls.append(sig)
        if sig == "gone":
            return None
        return None if len(calls) == 1 else tx_fixture()

    async def go():
        task = asyncio.create_task(w.worker(fetch))
        w.note(MINT, SLOT, SIG, False, token_lines(), T0)
        w.note(MINT, SLOT, "gone", False, token_lines(), T0)
        for _ in range(200):
            await asyncio.sleep(0.01)
            if counts["xfer_missing"]:
                break
        task.cancel()
    asyncio.run(go())
    assert calls == [SIG, SIG, "gone", "gone"]
    assert [r for _, r in rows] == TR.parse_tx(tx_fixture(), MINT, SIG, SLOT, T0)
    assert {t for t, _ in rows} == {"transfers"}
    assert (counts["xfer_fetched"], counts["xfer_missing"], counts["xfer_checked"], counts["xfer_plain"]) == (
        1, 1, 2, 1)


def test_a_migration_starts_a_watch_and_the_heartbeat_says_so():
    col = CL.Collector(None, None, amm=True, meta=False)
    assert col.heartbeat()["transfers"] is None
    col.xfer = TR.TransferWatch(col.keep, col.counts, clock=lambda: T0)
    mig = {"user": DEV, "mint": MINT, "mint_amount": 1, "sol_amount": 1, "pool_migration_fee": 0,
           "bonding_curve": key(4), "timestamp": 1, "pool": POOL}
    col.handle(note("m1", 104, logs_for((E.PUMP, "CompletePumpAmmMigrationEvent", mig))), T0)
    assert col.xfer.until == {MINT: T0 + TR.TRANSFER_WATCH_MS}
    assert col.heartbeat()["transfers"] == {"watched": 1, "subscribed": 0, "connected": False,
                                            "queue": 1}                    # its token program, to be asked
    col.keep("transfers", row(A, B, 1, "transferChecked"))
    assert col.counts["transfers"] == 1


def test_a_watched_coins_pool_trade_from_the_transfer_link_fills_a_gap_once():
    rows = []
    col = CL.Collector(None, on_row=lambda tb, r: rows.append((tb, r)), amm=True, meta=False)
    col.xfer = TR.TransferWatch(col.keep, col.counts, clock=lambda: T0)
    col.xfer.on_tx = col.handle_tx
    mig = {"user": DEV, "mint": MINT, "mint_amount": 1, "sol_amount": 1, "pool_migration_fee": 0,
           "bonding_curve": key(4), "timestamp": 1, "pool": POOL}
    col.handle(note("m1", 104, logs_for((E.PUMP, "CompletePumpAmmMigrationEvent", mig))), T0)
    col.xfer.up()
    col.xfer.on_message(answer(sent(col.xfer)[0]["id"], 77), T0)
    sale = {"timestamp": 1, "base_amount_in": 10, "quote_amount_out": 5, "pool_base_token_reserves": 1000,
            "pool_quote_token_reserves": 100, "pool": POOL, "user": A}
    trade = logs_for((E.PUMP_AMM, "SellEvent", sale))
    assert col.xfer.on_message(notification(77, "d1", trade), T0 + 5) == "pump"     # not fetched
    assert col.xfer.on_message(notification(77, "d2", trade, err={"x": 1}), T0 + 5) == "failed"
    amm = [r for tb, r in rows if tb == "amm"]
    assert len(amm) == 1 and amm[0]["mint"] == MINT and not amm[0]["buy"]
    assert col.first_by["xfer"] == 1 and col.counts["failed_tx"] == 0
    assert col.handle(note("d1", 105, trade), T0 + 9) == 0                          # the program link, later
    assert col.counts["duplicate"] == 1 and len([1 for tb, _ in rows if tb == "amm"]) == 1


def test_the_switch():
    assert TR.enabled({}) and not TR.enabled({"PYTHIA_PF_TRANSFERS": "0"})
    assert TR.rpc_url({"PYTHIA_PF_POOL_RPC": "https://pool"}) == "https://pool"
    assert TR.rpc_url({"PYTHIA_PF_POOL_RPC": "https://pool", "PYTHIA_PF_TRANSFER_RPC": " https://x "}) == "https://x"


def test_the_store_keeps_transfers_by_day(tmp_path):
    w = store.Writer(tmp_path, budget_gb=1)
    for r in TR.parse_tx(tx_fixture(), MINT, SIG, 0, T0):
        w.add("transfers", r)
    w.add("transfers", {"t": T0 + 9, "t0": T0, "ix": "gap"})
    w.flush(T0)
    df = store.read("transfers", [store.day_of(T0)], tmp_path)
    assert df.height == 4 and df["amount"].to_list() == [1_000, 700, 300, None]
    assert df["outer"].to_list()[:2] == [None, ROUTER] and df["ix"].to_list()[-1] == "gap"
