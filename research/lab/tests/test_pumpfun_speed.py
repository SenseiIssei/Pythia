"""Y3, speed at a token's release: the detection latency (chain clock, buckets, endpoints that never show a
key), the speed tiers (chain order inside a slot, the run behind the creation, where each tier fills), the
block sample's bids, the fast path (templates byte for byte, the blockhash cache, the fee estimate, tips only
behind the owner's flag, a fake signer, nothing sent), the live gate for a Jito block engine, the collector's
provider feeds and the gRPC wire format, and the card's latency line. No network.

Run from research/lab:  python -m pytest tests/test_pumpfun_speed.py
"""

from __future__ import annotations

import base64
import hashlib
import json
import struct

import numpy as np
import pytest

from lab.pumpfun_rt import collector as COL
from lab.pumpfun_rt import curve as C
from lab.pumpfun_rt import events as E
from lab.pumpfun_rt import fastpath as F
from lab.pumpfun_rt import geyser as G
from lab.pumpfun_rt import latency as L
from lab.pumpfun_rt import live_exec as LX
from lab.pumpfun_rt import speed as SP
from lab.pumpfun_rt import store
from lab.pumpfun_rt import strategies as S
from lab.pumpfun_rt import txbuild as X

SOL = C.LAMPORTS
T0_S = 1_792_500_000
SLOT_MS = 216.0


def key(i: int) -> str:
    return E.b58(bytes([i]) * 32)


# ---------------------------------------------------------------- latency

def test_the_chain_clock_recovers_slot_times_from_whole_second_block_times():
    slots = np.arange(5_000, 9_000)
    true_ms = T0_S * 1000 + 123 + (slots - 5_000) * SLOT_MS
    clock = L.ChainClock(slots, true_ms // 1000)
    assert abs(clock.slot_ms() - SLOT_MS) < 0.5
    err = clock.at(slots) - true_ms
    assert abs(float(np.median(err))) < 30 and float(np.abs(err).max()) < 120


def test_detection_latency_buckets_and_clock_free_checks():
    slots = np.arange(10_000, 12_000)
    chain = T0_S * 1000 + (slots - 10_000) * SLOT_MS
    e_t = (chain + 300).astype(np.int64)                     # every slot's first event 300 ms after its block
    lag = np.array([100, 300, 500, 3_000, 30_000], dtype=float)
    c_slot = np.array([11_000, 11_100, 11_200, 11_300, 11_400])
    c_t = (T0_S * 1000 + (c_slot - 10_000) * SLOT_MS + lag).astype(np.int64)
    fr = {"c_t": c_t, "c_slot": c_slot, "c_mint": [key(i) for i in range(5)], "e_t": np.concatenate([e_t, c_t]),
          "e_slot": np.concatenate([slots, c_slot]), "e_bts": np.concatenate([chain // 1000, c_slot * 0]),
          "e_trade": np.concatenate([np.ones(len(slots), bool), np.zeros(5, bool)])}
    fr["e_bts"][len(slots):] = (T0_S * 1000 + (c_slot - 10_000) * SLOT_MS) // 1000
    res = L.measure(fr)
    assert res["n"] == 5 and abs(res["slot_ms"] - SLOT_MS) < 1
    assert res["buckets"]["slot"] == 1 and res["buckets"]["+1"] == 1 and res["buckets"]["+2"] == 1
    assert res["buckets"]["+10..49"] == 1 and res["buckets"]["+50"] == 1
    assert res["within_1s"] == pytest.approx(0.6)
    assert res["seen_tip_slots"]["p99"] > 100                # the 30 s one arrived after many newer slots
    md = L.report_md(res)
    assert "creations" in md and "—" not in md


def test_endpoints_take_their_token_from_the_environment_and_never_show_it():
    env = {"PYTHIA_SOLANA_WS_URLS": "wss://a.example/?api-key={token}, wss://b.example/ws",
           "PYTHIA_SOLANA_TOKEN": "s3cr3t"}
    urls = L.ws_urls(env)
    assert urls == ["wss://a.example/?api-key=s3cr3t", "wss://b.example/ws"]
    assert L.safe_url(urls[0]) == "wss://a.example" and "s3cr3t" not in L.safe_url(urls[0])
    assert L.ws_urls({"PYTHIA_SOLANA_WS_URLS": "wss://a.example/{token}"}) == [L.DEFAULT_WS]   # no token: left out
    assert L.ws_urls({}) == [L.DEFAULT_WS]


def test_the_probe_counts_slots_behind_the_endpoints_own_tip():
    p = L.Probe("wss://x.example/?k=1")
    p.on_slot(json.dumps({"params": {"result": {"slot": 1_010}}}))
    logs = [f"Program {E.PUMP} invoke [1]", "Program data: " + base64.b64encode(E.encode(
        "CreateEvent", {"mint": key(1), "timestamp": T0_S, "virtual_sol_reserves": 1})).decode(),
        f"Program {E.PUMP} success"]
    msg = {"params": {"result": {"context": {"slot": 1_000}, "value": {"err": None, "signature": "s", "logs": logs}}}}
    p.on_logs(json.dumps(msg), "confirmed", T0_S * 1000 + 2_000, keep_raw=1)
    r = p.result()
    assert r["endpoint"] == "wss://x.example" and r["confirmed"]["behind_tip_slots"]["p50"] == 10
    assert r["confirmed"]["creations"] == 1 and len(p.raw_creates) == 1


# ---------------------------------------------------------------- the tiers

def test_chain_order_follows_the_reserves_not_the_receive_order():
    start = 30 * SOL
    a = {"tx": 3, "i": 0, "buy": True, "sol": 2 * SOL, "vs": start + 2 * SOL}
    b = {"tx": 1, "i": 1, "buy": True, "sol": 1 * SOL, "vs": start + 3 * SOL}
    c = {"tx": 2, "i": 2, "buy": False, "sol": SOL // 2, "vs": start + 3 * SOL - SOL // 2}
    out, ok = SP.chain_order([b, c, a], start)
    assert [r["tx"] for r in out] == [3, 1, 2] and ok
    out, ok = SP.chain_order([b, c], start)                   # the chain is broken: receive order, flagged
    assert [r["tx"] for r in out] == [1, 2] and not ok


def tier_store(root):
    """A filler token trading every slot (the chain clock) and one token X whose creation slot holds the dev
    buy, a run of two buyers right behind it, and a later buyer; then one buy a slot, then the dev sells."""
    w = store.Writer(root)
    rng = np.random.default_rng(5)

    def chain_ms(slot):
        return T0_S * 1000 + (slot - 1_000) * SLOT_MS

    def add_trade(mint, slot, tx, user, buy, sol, st, k=0):
        vs, vt, rt, rs = st
        if buy:
            tok = int(vt * sol / (vs + sol))
            st = (vs + sol, vt - tok, rt - tok, rs + sol)
        else:
            tok = sol
            sol = int(vs * tok / (vt + tok))
            st = (vs - sol, vt + tok, rt + tok, rs - sol)
        w.add("trades", {"t": int(chain_ms(slot)) + 1_500 + k, "slot": slot, "tx": tx, "mint": mint, "buy": buy,
                         "sol": sol, "tok": tok, "user": user, "vs": st[0], "vt": st[1], "rt": st[2], "rs": st[3],
                         "fb": 95, "cfb": 30, "ix": "buy", "bts": int(chain_ms(slot) // 1000)})
        return st, tok

    fill = key(9)
    w.add("creates", {"t": int(chain_ms(999)) + 1_500, "slot": 999, "tx": 1, "sig": "f", "mint": fill,
                      "creator": key(8), "user": key(8), "vs": 30 * SOL, "vt": 1_073_000_000 * 10 ** 6,
                      "rt": C.INITIAL_RT, "bts": int(chain_ms(999) // 1000)})
    st_f = (30 * SOL, 1_073_000_000 * 10 ** 6, C.INITIAL_RT, 0)
    tx = 10
    for slot in range(1_000, 1_400):
        tx += 1
        st_f, _ = add_trade(fill, slot, tx, key(20 + slot % 5), True, int(0.001 * SOL), st_f)
    x, dev = key(1), key(2)
    st = (30 * SOL, 1_073_000_000 * 10 ** 6, C.INITIAL_RT, 0)
    w.add("creates", {"t": int(chain_ms(1_100)) + 1_500, "slot": 1_100, "tx": 5_000, "sig": "x", "mint": x,
                      "creator": dev, "user": dev, "vs": st[0], "vt": st[1], "rt": st[2],
                      "bts": int(chain_ms(1_100) // 1000)})
    st, dev_tok = add_trade(x, 1_100, 5_000, dev, True, 1 * SOL, st, 1)
    st, _ = add_trade(x, 1_100, 5_001, key(30), True, int(0.5 * SOL), st, 2)        # the run
    st, _ = add_trade(x, 1_100, 5_002, key(31), True, int(0.5 * SOL), st, 3)
    st, _ = add_trade(x, 1_100, 5_010, key(32), True, int(0.5 * SOL), st, 4)        # after a gap: not the run
    for slot in range(1_101, 1_160):
        st, _ = add_trade(x, slot, 6_000 + slot, key(40 + slot % 9), True, int(0.2 * SOL * (1 + rng.random())), st, 5)
    st, _ = add_trade(x, 1_160, 7_000, dev, False, dev_tok, st, 6)
    for slot in range(1_161, 1_300):
        st, _ = add_trade(x, slot, 7_000 + slot, key(40 + slot % 9), True, int(0.01 * SOL), st, 7)
    w.flush(T0_S * 1000)


def test_the_index_finds_the_dev_buy_and_the_run_behind_the_creation(tmp_path):
    tier_store(tmp_path)
    idx = SP.build_index(store.days(tmp_path), tmp_path)
    m = idx.mints[key(1)]
    assert m.slot == 1_100 and m.n_create == 1 and m.n_run == 2 and m.run_txs == 2
    a, r, b = idx.after_create(key(1)), idx.after_run(key(1)), idx.through(key(1), 1_100)
    assert a[0] < r[0] < b[0]                                 # SOL reserve rises with every buy
    assert abs(idx.slot_ms - SLOT_MS) < 2
    assert idx.slot_at(idx.time_of(1_150)) >= 1_150


def test_each_tier_fills_later_on_the_curve_and_nothing_is_sent(tmp_path, monkeypatch):
    tier_store(tmp_path)
    monkeypatch.setattr(store, "base", lambda: tmp_path)
    res = SP.run(root=tmp_path, log=lambda *a: None, exits=("t15",))
    got = {t["rule"]: t for t in res["closed"] if t["mint"] == key(1) and t["rule"].endswith("_all_t15")}
    order = [got[f"SP_{tier}_all_t15"]["entry_price"] for tier in ("S0f", "S0r", "S0b", "S1", "S2")]
    assert order == sorted(order) and order[0] < order[-1]
    ev = SP.evaluate(res)
    names = {r["name"] for r in ev["rows"]}
    assert "SP_S0f_all_t15" in names and "SP_NOW_all_t15" in names
    md = SP.report_md(res, ev, None, None)
    assert "| S0f | all | t15 |" in md and "—" not in md
    assert SP.N_TRIALS == S.SPEED_TRIALS == 135


def block_tx(i, signer, tok, fee, gains, spend=10 ** 9, mint=None):
    return {"i": i, "n": 1_000, "signer": signer, "buy": tok > 0, "tok": tok, "fee": fee,
            "prio": max(0, fee - 5_000), "spend": spend, "gains": gains}


def test_bids_count_priority_fees_and_tips_but_not_trade_fees():
    jito = sorted(X.JITO_TIP_ACCOUNTS)[0]
    fee_acct, relay = key(70), key(71)
    blocks = []
    for k in range(6):
        dev = key(100 + k)
        txs = [block_tx(10, dev, 5, 5_000, {fee_acct: 4_700_000}, 10 ** 9)]
        for j in range(3):
            spend = (j + 1) * 10 ** 8
            g = {fee_acct: int(spend * 0.0047)}
            if j == 0:
                g[jito] = 1_000_000
            if j == 1:
                g[relay] = 2_500_000 if k % 2 else 500_000
            txs.append(block_tx(11 + j, key(150 + 10 * k + j), 7, 5_000 + 100_000 * j, g, spend))
        blocks.append({"slot": k, "mint": key(200 + k), "txs": txs, "n": 1_000})
    tips, fees = SP.relay_accounts(blocks)
    assert fee_acct in fees and fee_acct not in tips and relay in tips and jito in tips
    s = SP.blocks_summary(blocks)
    assert s["with_snipers"] == 6 and s["share_of_snipers_in_a_run_behind_creation"] == 1.0
    assert s["jito_tip_share"] == pytest.approx(1 / 3)
    # the best bid of a slot: the relay tip plus its priority fee (0.0026) or the Jito tip (0.001), never the fee
    assert s["best_bid_sol"]["p50"] == pytest.approx(0.0018) and s["best_bid_sol"]["p99"] < 0.0027


def test_block_transactions_are_read_from_account_balances():
    mint, me, curve_acct, tip_acct = key(1), key(2), key(3), sorted(X.JITO_TIP_ACCOUNTS)[0]
    block = {"transactions": [
        {"meta": {"err": None, "fee": 5_000, "preBalances": [1, 1], "postBalances": [1, 1]},
         "transaction": {"accountKeys": [{"pubkey": key(9), "signer": True}, {"pubkey": key(8), "signer": False}]}},
        {"meta": {"err": None, "fee": 105_000, "preBalances": [10 ** 9, 0, 0], "postBalances": [10 ** 8, 899_000_000,
                                                                                               1_000_000],
                  "preTokenBalances": [], "postTokenBalances": [{"owner": me, "mint": mint,
                                                                 "uiTokenAmount": {"amount": "500"}}]},
         "transaction": {"accountKeys": [{"pubkey": me, "signer": True}, {"pubkey": curve_acct, "signer": False},
                                         {"pubkey": tip_acct, "signer": False}, {"pubkey": mint, "signer": False}]}}]}
    txs = SP.block_txs(block, mint)
    assert len(txs) == 1 and txs[0]["i"] == 1 and txs[0]["buy"] and txs[0]["tok"] == 500
    assert txs[0]["prio"] == 100_000 and txs[0]["gains"][tip_acct] == 1_000_000


# ---------------------------------------------------------------- the fast path

def fixed_rpc(calls=None):
    bh = E.b58(hashlib.sha256(b"bh").digest())

    def call(method, params):
        if calls is not None:
            calls.append(method)
        if method == "getLatestBlockhash":
            return {"value": {"blockhash": bh}}
        if method == "getRecentPrioritizationFees":
            return [{"slot": i, "prioritizationFee": f} for i, f in enumerate([0, 0, 100, 200, 300, 400, 10 ** 9])]
        raise ValueError(method)
    return call, bh


def test_a_patched_template_is_byte_for_byte_the_freshly_built_transaction():
    user = key(77)
    fp = F.bench_path(user)
    r = fp.on_message(F.synthetic_message(1))
    assert r is not None and r.tokens > 0 and r.max_cost_l == int(0.1 * SOL * 1.3)
    ev = next(e for n, e in E.events_of(json.loads(F.synthetic_message(1))["params"]["result"]["value"]["logs"])
              if n == "CreateEvent")
    info = X.CurveInfo(ev["mint"], X.TOKEN, fp.st.fee_recipient, ev["creator"])
    micro = fp.fees.micro()
    ixs = X.pump_buy(user, info, r.tokens, r.max_cost_l, micro * X.UNITS // 1_000_000)
    fresh = X.compile_message(user, ixs, fp.bh.text)
    tx = base64.b64decode(r.tx_b64)
    assert tx[0] == 1 and tx[65:] == fresh                   # one signature, then exactly that message
    sold = fp.sell(ev["mint"], r.tokens, 0)
    assert sold is not None and sold[1] >= 0


def test_program_ids_are_the_ones_on_chain():
    # Checked with getAccountInfo on mainnet (2026-10-22). One wrong letter in TOKEN once made every
    # transaction fail with ProgramAccountNotFound; only the simulation caught it.
    assert X.TOKEN == "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
    assert X.TOKEN_2022 == "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"
    assert X.ATA_PROGRAM == "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL"
    assert X.COMPUTE_BUDGET == "ComputeBudget111111111111111111111111111111"
    assert X.FEE_PROGRAM == "pfeeUxB6jkeY1Hxd7CsFCAjcbHA9rWtchMGdZ6VojVZ"
    assert X.SYSTEM == "11111111111111111111111111111111"
    assert X.PUMP == "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
    assert X.PUMP_AMM == "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"
    assert X.WSOL == "So11111111111111111111111111111111111111112"
    for k in (X.TOKEN, X.TOKEN_2022, X.ATA_PROGRAM, X.FEE_PROGRAM, X.PUMP, X.PUMP_AMM):
        assert len(X.b58decode(k)) == 32


def test_pump_buy_data_matches_the_programs_argument_layout():
    # amount u64, max_sol_cost u64, track_volume and partial_fill as one-byte OptionBool, both off
    info = X.CurveInfo(key(1), X.TOKEN, key(5), key(6))
    ix = next(i for i in X.pump_buy(key(77), info, 123, 456, 789) if i.program == X.PUMP)
    assert ix.data == X.discriminator("buy") + struct.pack("<QQ", 123, 456) + b"\x00\x00"
    assert X.ARGS[("pump", "buy")] == ["amount", "max_sol_cost", "track_volume", "partial_fill"]


def test_compile_template_knows_where_the_blockhash_and_the_data_are():
    user = key(77)
    info = X.CurveInfo(key(1), X.TOKEN, key(5), key(6))
    ixs = X.pump_buy(user, info, 123, 456, 789)
    c = X.compile_template(user, ixs, key(44))
    assert c.message[c.blockhash_at:c.blockhash_at + 32] == X.key(key(44))
    for i, ix in enumerate(ixs):
        assert c.message[c.data_at[i]:c.data_at[i] + len(ix.data)] == ix.data


def test_tips_only_with_the_owners_flag_to_a_jito_account_and_under_the_cap():
    user = key(77)
    jito = sorted(X.JITO_TIP_ACCOUNTS)[0]
    buy = X.pump_buy(user, X.CurveInfo(key(1), X.TOKEN, key(5), key(6)), 1, 1, 1)
    X.check_own(user, buy + [X.tip(user, jito, 100_000)], tip_ok=True)
    with pytest.raises(ValueError):
        X.check_own(user, buy + [X.tip(user, jito, 100_000)])                     # the flag is off
    with pytest.raises(ValueError):
        X.check_own(user, buy + [X.tip(user, jito, X.MAX_TIP_LAMPORTS + 1)], tip_ok=True)
    with pytest.raises(ValueError):
        X.check_own(user, buy + [X.tip(user, key(99), 100_000)], tip_ok=True)       # not a tip account
    with pytest.raises(ValueError):
        X.check_own(user, buy + [X.tip(user, jito, 1), X.tip(user, jito, 1)], tip_ok=True)
    call, _ = fixed_rpc()
    st = F.Static(user, key(5))
    with pytest.raises(ValueError):
        F.FastPath(st, F.FakeSigner(user), F.BlockhashCache(call), F.FeeEstimator(call, [E.PUMP]), tip_account=jito,
                   tip_l=1_000, jito=False)
    fp = F.bench_path(user, tip=True)
    r = fp.on_message(F.synthetic_message(2))
    assert r is not None and struct.pack("<IQ", 2, 100_000) in base64.b64decode(r.tx_b64)


def test_the_blockhash_is_cached_for_20_seconds_and_the_fee_is_a_capped_percentile():
    calls = []
    call, bh = fixed_rpc(calls)
    now = [0.0]
    cache = F.BlockhashCache(call, clock=lambda: now[0])
    assert cache.get() == X.key(bh)
    for s in (5, 10, 19.9):
        now[0] = s
        cache.tick()
    assert calls.count("getLatestBlockhash") == 1
    now[0] = 20.0
    cache.tick()
    assert calls.count("getLatestBlockhash") == 2
    fees = F.FeeEstimator(call, [E.PUMP], units=200_000, pct=50, floor=10, cap_sol=0.001)
    fees.refresh()
    assert fees.micro() == 300                                # the median of the non-zero fees
    fees.value = 10 ** 12
    assert fees.priority_lamports() <= 0.001 * SOL           # never above the cap
    assert F.FeeEstimator(call, [E.PUMP], cap_sol=1.0).cap <= F.HARD_MAX_PRIORITY_SOL * SOL * 10 ** 6 / X.UNITS
    with pytest.raises(ValueError):
        F.rpc_reader("https://x.example")("sendTransaction", [])


def test_the_benchmark_times_every_stage_and_the_dry_run_sends_nothing():
    res = F.bench(30)
    assert res["built"] == 30 and res["stages_us"]["ready"]["p50"] > 0
    assert res["sell_ready_template_us"]["n"] == 30
    s = F.DryRunSender(["https://a.example", "https://b.example"], "https://x.block-engine.example/api/v1/transactions",
                       env={"PYTHIA_PUMPFUN_JITO": "1"})
    rec = s.submit(base64.b64encode(b"\x01" + bytes(64) + b"m").decode(), key(1))
    assert rec["targets"] == 3 and rec["sent"] is False
    assert F.DryRunSender(["https://a.example"], "https://x.block-engine.example/api/v1/transactions",
                          env={}).submit("AQ==", key(1))["targets"] == 1


# ---------------------------------------------------------------- the live gate

def test_a_jito_block_engine_only_with_the_owners_switch_and_never_for_bundles():
    url = "https://mainnet.block-engine.jito.wtf/api/v1/transactions"
    assert LX.rpc_problems(url, {})                                          # switch off
    assert LX.rpc_problems(url, {"PYTHIA_PUMPFUN_JITO": "1"}) == []
    assert LX.rpc_problems("https://mainnet.block-engine.jito.wtf/api/v1/bundles", {"PYTHIA_PUMPFUN_JITO": "1"})
    assert LX.rpc_problems("http://mainnet.block-engine.jito.wtf/api/v1/transactions", {"PYTHIA_PUMPFUN_JITO": "1"})
    assert LX.rpc_problems("https://x.example/relay", {"PYTHIA_PUMPFUN_JITO": "1"})
    assert LX.rpc_problems("https://api.mainnet-beta.solana.com", {}) == []
    assert LX.send_problems({}) == []
    assert LX.send_problems({"PYTHIA_PUMPFUN_JITO_URL": url})                # a URL without the switch
    assert LX.send_problems({"PYTHIA_PUMPFUN_JITO_URL": url, "PYTHIA_PUMPFUN_JITO": "1"}) == []
    assert LX.send_problems({"PYTHIA_PUMPFUN_JITO": "1"})                    # the switch without an engine
    assert LX.send_problems({"PYTHIA_PUMPFUN_RPC_URLS": "https://a.example, http://b.example"})
    assert LX.send_problems({"PYTHIA_PUMPFUN_RPC_URLS": "https://a.example,https://b.example"}) == []


# ---------------------------------------------------------------- the collector's feeds

def test_provider_feeds_keep_the_public_endpoint_as_a_fallback():
    env = {"PYTHIA_SOLANA_WS_URLS": "wss://p.example/?k={token}", "PYTHIA_SOLANA_TOKEN": "t"}
    assert COL.feed_urls(env) == ["wss://p.example/?k=t", COL.DEFAULT_WS]
    assert COL.feed_urls({**env, "PYTHIA_PF_PUBLIC_FALLBACK": "0"}) == ["wss://p.example/?k=t"]
    assert COL.feed_urls({}) == [COL.DEFAULT_WS]
    assert COL.feed_commitment({"PYTHIA_SOLANA_COMMITMENT": "processed"}) == "processed"
    assert COL.feed_commitment({"PYTHIA_SOLANA_COMMITMENT": "finalized"}) == "confirmed"


def test_the_collector_counts_which_feed_was_first():
    col = COL.Collector(None)
    logs = [f"Program {E.PUMP} invoke [1]", "Program data: " + base64.b64encode(E.encode(
        "CreateEvent", {"mint": key(1), "creator": key(2), "user": key(2), "virtual_sol_reserves": 30 * SOL,
                        "virtual_token_reserves": 10 ** 15, "real_token_reserves": 10 ** 14})).decode(),
            f"Program {E.PUMP} success"]
    assert col.handle_tx(5, "sig1", False, logs, 1_000, "grpc") == 1
    assert col.handle_tx(5, "sig1", False, logs, 1_001, "wss://a.example") == 0
    assert col.first_by == {"grpc": 1} and col.heartbeat()["first_by_source"] == {"grpc": 1}


def test_the_geyser_wire_format_round_trips():
    req = G.subscribe_request([E.PUMP], "processed")
    assert E.PUMP.encode() in req and req.endswith(bytes([6 << 3, 0]))       # commitment processed = 0
    fields = list(G.fields(req))
    assert fields[0][0] == 3 and fields[-1] == (6, 0, 0)
    sig = bytes(range(64))
    meta = G._field(6, 2, b"Program log: a") + G._field(6, 2, b"Program log: b")
    info = G._field(1, 2, sig) + G._field(2, 0, 0) + G._field(4, 2, meta) + G._field(5, 0, 7)
    upd = G._field(1, 2, b"pump") + G._field(4, 2, G._field(1, 2, info) + G._field(2, 0, 123_456))
    kind, tx = G.parse_update(upd)
    assert kind == "tx" and tx["slot"] == 123_456 and tx["sig"] == E.b58(sig) and tx["index"] == 7
    assert tx["logs"] == ["Program log: a", "Program log: b"] and not tx["failed"]
    failed = G._field(4, 2, G._field(1, 2, G._field(4, 2, G._field(1, 2, b"\x01"))) + G._field(2, 0, 1))
    assert G.parse_update(failed)[1]["failed"]
    assert G.parse_update(G._field(6, 2, b""))[0] == "ping"
    assert G.target("https://grpc.example:10000/x?k=1") == "grpc.example:10000"


# ---------------------------------------------------------------- the card

def test_the_daily_card_says_how_late_we_see_new_tokens_in_both_languages():
    from lab.pumpfun_rt import card
    from test_i18n import no_english
    data = {"days": ["2026-10-20"], "latency": {"n": 100, "p50_ms": 14_900.0, "p90_ms": 43_700.0,
                                                "within_1s": 0.037, "within_2_slots": 0.025}}
    now = T0_S * 1000
    en = card.daily_card(data, None, {}, None, now, "en").render("telegram", "en")
    de = card.daily_card(data, None, {}, None, now, "de").render("telegram", "de")
    assert "14.9 s after their block" in en and "4% within a second" in en
    assert "14,9 s nach ihrem Block" in de
    no_english(de)
