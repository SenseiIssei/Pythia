"""The real-time pump.fun lab: event decoding, the collector's bookkeeping, the store, the
curve arithmetic, the paper engine's honest fills (latency, dumps before our sale, failed
buys, completed curves), the slot clock, the model's purged walk-forward, the report and
the cards, and that nothing in the package can touch a wallet. No network.

Run from research/lab:  python -m pytest tests/test_pumpfun_rt.py
"""

from __future__ import annotations

import base64
import inspect
import json
import math
import pkgutil
import struct

import numpy as np
import pytest

from lab.pumpfun_rt import collector as COL
from lab.pumpfun_rt import curve as C
from lab.pumpfun_rt import events as E
from lab.pumpfun_rt import model as M
from lab.pumpfun_rt import sim
from lab.pumpfun_rt import store
from lab.pumpfun_rt import strategies as S
from lab.pumpfun_rt import tokens as T

T0 = 1_792_450_000_000
SOL = C.LAMPORTS


def key(i: int) -> str:
    return E.b58(bytes([i]) * 32)


MINT, DEV, POOL = key(1), key(2), key(3)
BUYERS = [key(10 + i) for i in range(60)]


@pytest.fixture(autouse=True)
def small_models(monkeypatch):
    """Fewer trees: the tests check the method, not the model's last digit."""
    monkeypatch.setitem(M.PARAMS, "n_estimators", 40)


# ---------------------------------------------------------------- encoding (the tests' side)

def enc(name: str, values: dict, upto: str | None = None) -> bytes:
    disc = next(d for d, (_, n) in E.DISC.items() if n == name)
    out = bytearray(disc)
    for field, kind in E.LAYOUTS[name]:
        v = values.get(field)
        if kind == E.PUBKEY:
            out += E.b58decode(v or E.DEFAULT_KEY).rjust(32, b"\0")
        elif kind == E.STRING:
            b = (v or "").encode()
            out += struct.pack("<I", len(b)) + b
        elif kind == E.SHAREHOLDERS:
            out += struct.pack("<I", 0)
        elif kind == E.I128:
            out += int(v or 0).to_bytes(16, "little", signed=True)
        else:
            size, fmt = E._FIXED[kind]
            out += struct.pack(fmt, v or 0)
        if field == upto:
            break
    return bytes(out)


def logs_for(*events: tuple[str, str, dict]) -> list[str]:
    lines = ["Program ComputeBudget111111111111111111111111111111 invoke [1]",
             "Program ComputeBudget111111111111111111111111111111 success"]
    for prog, name, vals in events:
        lines += [f"Program {prog} invoke [1]", f"Program log: Instruction: {name}",
                  "Program data: " + base64.b64encode(enc(name, vals)).decode(), f"Program {prog} success"]
    return lines


def note(sig: str, slot: int, logs: list[str], err=None) -> str:
    return json.dumps({"jsonrpc": "2.0", "method": "logsNotification",
                       "params": {"result": {"context": {"slot": slot},
                                             "value": {"signature": sig, "err": err, "logs": logs}},
                                  "subscription": 1}})


def test_base58_and_decoding_round_trip():
    raw = bytes(range(32))
    assert E.b58decode(E.b58(raw)) == raw
    assert E.b58(b"\0" * 32) == E.DEFAULT_KEY
    vals = {"mint": MINT, "sol_amount": 5 * SOL, "token_amount": 1234, "is_buy": True, "user": DEV, "timestamp": 99,
            "virtual_sol_reserves": 35 * SOL, "virtual_token_reserves": 900, "real_sol_reserves": 5 * SOL,
            "real_token_reserves": 800, "fee_basis_points": 95, "creator_fee_basis_points": 30, "ix_name": "buy"}
    ev = E.decode("TradeEvent", enc("TradeEvent", vals))
    for k, v in vals.items():
        assert ev[k] == v, k
    short = E.decode("TradeEvent", enc("TradeEvent", vals, upto="real_token_reserves"))   # an older, shorter event
    assert short["real_token_reserves"] == 800 and "fee_basis_points" not in short
    assert E.events_of(logs_for((E.PUMP, "TradeEvent", vals)))[0][0] == "TradeEvent"
    too_short = enc("TradeEvent", vals, upto="timestamp")
    lines = [f"Program {E.PUMP} invoke [1]", "Program data: " + base64.b64encode(too_short).decode(),
             f"Program {E.PUMP} success"]
    assert E.events_of(lines) == []                       # lacks the reserves: of no use, dropped


def test_program_data_is_attributed_by_the_invoke_stack():
    vals = {"mint": MINT, "is_buy": True, "virtual_sol_reserves": 1, "real_token_reserves": 1}
    data = "Program data: " + base64.b64encode(enc("TradeEvent", vals)).decode()
    other = "Someprogram1111111111111111111111111111111"
    lines = [f"Program {other} invoke [1]", data, f"Program {E.PUMP} invoke [2]", f"Program {E.PUMP} success",
             data, f"Program {other} success"]
    assert E.events_of(lines) == []                       # logged by another program: not ours
    lines = [f"Program {other} invoke [1]", f"Program {E.PUMP} invoke [2]", data, f"Program {E.PUMP} success",
             f"Program {other} success"]
    assert len(E.events_of(lines)) == 1


def create_vals(mint=MINT, dev=DEV, quote=None):
    return {"name": "Test", "symbol": "TST", "uri": "https://ipfs.io/ipfs/x", "mint": mint, "bonding_curve": key(4),
            "user": dev, "creator": dev, "timestamp": 1, "virtual_token_reserves": 1_073_000_000 * 10 ** 6,
            "virtual_sol_reserves": 30 * SOL, "real_token_reserves": C.INITIAL_RT,
            "token_total_supply": 10 ** 15, "quote_mint": quote or E.DEFAULT_KEY}


def test_collector_keeps_rows_drops_failures_duplicates_and_unknown_pools():
    rows = []
    col = COL.Collector(None, on_row=lambda tb, r: rows.append((tb, r)))
    logs = logs_for((E.PUMP, "CreateEvent", create_vals()))
    assert col.handle(note("s1", 100, logs), T0) == 1
    assert col.handle(note("s1", 100, logs), T0 + 5) == 0          # the same transaction from the other link
    assert col.handle(note("s2", 100, logs, err={"x": 1}), T0) == 0
    assert col.counts["duplicate"] == 1 and col.counts["failed_tx"] == 1
    buy = {"timestamp": 1, "base_amount_out": 10, "quote_amount_in": 5, "pool_base_token_reserves": 1000,
           "pool_quote_token_reserves": 100, "pool": POOL, "user": DEV}
    assert col.handle(note("s3", 105, logs_for((E.PUMP_AMM, "BuyEvent", buy))), T0 + 10) == 0   # pool unknown yet
    mig = {"user": DEV, "mint": MINT, "mint_amount": 206_900_000 * 10 ** 6, "sol_amount": 85 * SOL,
           "pool_migration_fee": 0, "bonding_curve": key(4), "timestamp": 1, "pool": POOL}
    assert col.handle(note("s4", 104, logs_for((E.PUMP, "CompletePumpAmmMigrationEvent", mig))), T0 + 20) == 2
    amm = [r for tb, r in rows if tb == "amm"]
    assert len(amm) == 1 and amm[0]["mint"] == MINT                 # the early trade, kept once its pool is known
    assert col.handle(note("s5", 106, logs_for((E.PUMP_AMM, "BuyEvent", buy))), T0 + 30) == 1
    assert [r["t"] for tb, r in rows if tb == "creates"] == [T0]


def test_a_gap_is_recorded_only_when_every_link_is_down():
    rows = []
    col = COL.Collector(None, on_row=lambda tb, r: rows.append(r))
    col.link_up(E.PUMP, 0)
    col.link_up(E.PUMP, 1)
    col.link_down(E.PUMP, 0)
    col.link_up(E.PUMP, 0)
    assert not [r for r in rows if r.get("kind") == "gap"]
    col.link_down(E.PUMP, 0)
    col.link_down(E.PUMP, 1)
    col.down_since[E.PUMP] -= 5_000
    col.link_up(E.PUMP, 1)
    gaps = [r for r in rows if r.get("kind") == "gap"]
    assert len(gaps) == 1 and gaps[0]["t"] - gaps[0]["t0"] >= 5_000 and gaps[0]["user"] == E.PUMP


def test_slot_clock_times_a_late_delivery_by_its_slot():
    clk = COL.SlotClock()
    assert clk.stamp(10, 1_000) == 1_000
    assert clk.stamp(11, 1_400) == 1_400
    assert clk.stamp(10, 9_000) == 1_000                  # a late copy of slot 10
    assert clk.stamp(9, 9_500) == 1_000                   # slot 9 seen only late: no later than slot 10
    st = store.slot_times([(10, 1_000), (11, 1_400), (9, 9_500), (12, 1_300)])
    assert st == {12: 1_300, 11: 1_300, 10: 1_000, 9: 1_000}


def test_meta_urls_only_public_gateways():
    assert COL.meta_url("ipfs://abc") == "https://ipfs.io/ipfs/abc"
    assert COL.meta_url("https://ipfs.io/ipfs/abc")
    assert COL.meta_url("https://pump.mypinata.cloud/ipfs/abc")
    assert COL.meta_url("https://metadata.pump.fun/x") is None
    assert COL.meta_url("http://ipfs.io/ipfs/abc") is None
    assert COL.meta_url("https://evil.example/x") is None
    assert COL.meta_flags({"twitter": "x", "description": "abc"})["twitter"] is True


# ---------------------------------------------------------------- store

def test_store_writes_reads_compacts_and_prunes(tmp_path):
    w = store.Writer(tmp_path, budget_gb=1)
    day1, day2 = T0 - 2 * 86_400_000, T0
    for t in (day1, day2):
        for i in range(3):
            w.add("trades", {"t": t + i, "slot": 1, "tx": i, "mint": MINT, "buy": True, "sol": 1, "tok": 2,
                             "user": DEV, "vs": 3, "vt": 4, "rs": 5, "rt": 6, "fb": 95, "cfb": 30, "ix": "buy",
                             "bts": 1})
        w.flush(t)
    w.add("trades", {"t": day2 + 9, "slot": 1, "tx": 9, "mint": MINT, "buy": False, "sol": 2 ** 70})  # overflow: null
    w.flush(day2 + 9)
    days = store.days(tmp_path)
    assert len(days) == 2
    df = store.read("trades", [days[1]], tmp_path)
    assert df.height == 4 and df["sol"].null_count() == 1
    assert store.compact(days[1], tmp_path) == 2
    assert store.read("trades", [days[1]], tmp_path).height == 4
    gone = store.prune(tmp_path, budget_bytes=1, today=days[1])
    assert gone == [days[0]] and store.days(tmp_path) == [days[1]]


# ---------------------------------------------------------------- curve

def test_curve_round_trip_costs_two_fees_and_the_impact():
    vs, vt, rt = 30 * SOL, 1_073_000_000 * 10 ** 6, C.INITIAL_RT
    tok = C.curve_buy(SOL // 10, vs, vt, rt, 125)
    back = C.curve_sell(tok, vs, vt, 125)
    assert 0.966 < back / (SOL / 10) < 0.972              # 1.25 % twice plus 0.33 % of impact paid twice
    assert C.curve_buy(SOL, vs, vt, 10, 125) == 10        # never more than is left on the curve
    assert C.pool_sell(C.pool_buy(SOL, 10 ** 12, 100 * SOL, 125), 10 ** 12, 100 * SOL, 125) < SOL


def test_latency_draws_are_bounded_reproducible_and_scale():
    c = C.Costs()
    draws = [c.latency("r", i, "buy") for i in range(2000)]
    assert min(draws) >= 400 and max(draws) <= 3000
    assert 800 < float(np.median(draws)) < 1250
    assert c.latency("r", 5, "buy") == c.latency("r", 5, "buy")
    c2 = c.scaled(latency=2.0, priority=3.0)
    assert c2.latency("r", 5, "buy") == pytest.approx(2 * c.latency("r", 5, "buy"))
    assert c2.tx_lamports() > 2.9 * c.tx_lamports() - 20_000


# ---------------------------------------------------------------- the engine

class Curve:
    """A plain pump.fun curve that emits consistent trade events into an engine."""

    def __init__(self, eng: sim.Engine, mint=MINT, dev=DEV, t=T0, slot=1000):
        self.eng, self.mint, self.dev = eng, mint, dev
        self.vs, self.vt, self.rt, self.rs = 30 * SOL, 1_073_000_000 * 10 ** 6, C.INITIAL_RT, 0
        self.slot, self.tx = slot, 1
        eng.create(t, self.tx, mint, dev, self.vs, self.vt, self.rt, "Test", "TST", "https://ipfs.io/ipfs/x")

    def buy(self, t, sol, user, same_tx=False):
        tok = int(self.vt * sol / (self.vs + sol))
        self.vs += sol
        self.vt -= tok
        self.rt -= tok
        self.rs += sol
        self._emit(t, True, sol, tok, user, same_tx)
        return tok

    def sell(self, t, tok, user):
        sol = int(self.vs * tok / (self.vt + tok))
        self.vs -= sol
        self.vt += tok
        self.rt += tok
        self.rs -= sol
        self._emit(t, False, sol, tok, user)

    def _emit(self, t, buy, sol, tok, user, same_tx=False):
        if not same_tx:
            self.tx += 1
            self.slot += 1
        self.eng.trade(t, self.tx, self.mint, buy, sol, tok, user, self.vs, self.vt, self.rs, self.rt, 95, 30,
                       self.slot)


def rule(name="T", entry="create", tp=0.5, sl=0.3, hold=15, **p) -> S.Rule:
    return S.Rule(name, "A", entry, tp, sl, hold, {"filter": "all", **p})


class Fixed(C.Costs):
    def latency(self, *key):
        return 1000.0


def test_the_buy_fills_at_the_curve_after_the_trades_before_it_lands():
    eng = sim.Engine([rule()], costs=Fixed())
    cv = Curve(eng)
    dev_tok = cv.buy(T0, 1 * SOL, DEV, same_tx=True)        # the dev buy, in the creation transaction
    assert dev_tok > 0
    cv.buy(T0 + 300, 3 * SOL, BUYERS[0])                    # a sniper lands before us
    cv.buy(T0 + 1500, 1 * SOL, BUYERS[1])                   # after our landing (T0 + 1000)
    eng.advance(T0 + 20_000)
    eng.finish(T0 + 20_000)
    t = eng.closed[0]
    assert t["land_ms"] == T0 + 1000
    assert t["entry_price"] > t["signal_price"] * 1.15      # we paid the sniper's price, not the launch price
    assert eng.tokens[MINT].dev_buy_l == 1 * SOL


def test_a_dump_before_our_sale_lands_is_ours_to_eat():
    eng = sim.Engine([rule(tp=0.5, sl=0.3, hold=15)], costs=Fixed())
    cv = Curve(eng)
    dev_tok = cv.buy(T0, 20 * SOL, DEV, same_tx=True)
    cv.buy(T0 + 2_000, 1 * SOL, BUYERS[0])                  # we hold from T0 + 1000
    cv.buy(T0 + 15_500, SOL // 10, BUYERS[1])               # time stop at T0 + 16000 -> sale lands T0 + 17000
    cv.sell(T0 + 16_500, dev_tok, DEV)                      # the dev dumps before our sale lands
    eng.advance(T0 + 30_000)
    t = eng.closed[0]
    assert t["exit_why"] == "time" and t["ret"] < -0.6 and t["dev_dumped"]


def test_take_profit_stop_and_failed_buys():
    eng = sim.Engine([rule(tp=0.5, sl=0.3, hold=60)], costs=Fixed())
    cv = Curve(eng)
    cv.buy(T0 + 2_000, 15 * SOL, BUYERS[0])                 # price jumps after we landed
    eng.advance(T0 + 5_000)
    assert eng.closed and eng.closed[0]["exit_why"] == "take" and eng.closed[0]["ret"] > 0.4
    eng2 = sim.Engine([rule()], costs=Fixed())
    cv2 = Curve(eng2)
    cv2.buy(T0 + 500, 25 * SOL, BUYERS[0])                  # +150 % before we land: over the 30 % tolerance
    eng2.advance(T0 + 5_000)
    assert not eng2.closed and eng2.failed[0]["why"] == "slippage" and eng2.failed[0]["pnl_sol"] < 0


def test_a_completed_curve_sells_into_the_pool():
    r = S.Rule("D", "D", "progress", 5.0, 0.99, 30, {"at": 0.8})
    eng = sim.Engine([r], costs=Fixed())
    cv = Curve(eng)
    cv.buy(T0 + 1_000, 60 * SOL, BUYERS[0])                 # crosses 80 %
    cv.buy(T0 + 3_000, 30 * SOL, BUYERS[1])                 # and completes the curve
    eng.complete(T0 + 3_000, MINT)
    eng.migrate(T0 + 3_001, MINT, POOL, 85 * SOL, 206_900_000 * 10 ** 6)
    eng.advance(T0 + 32_500)                                # the time stop fires; the pool is not seen yet
    assert not eng.closed                                   # the sale waits for a pool state
    eng.amm(T0 + 40_000, MINT, True, 10 ** 9, SOL // 100, 206_900_000 * 10 ** 6, 67 * SOL, 20, 5, 80, slot=2000)
    eng.advance(T0 + 60_000)
    t = eng.closed[0]
    assert t["migrated"] and t["proceeds_sol"] > 0 and t["exit_why"] == "time" and t["exit_ms"] > T0 + 40_000


def test_a_late_delivery_does_not_rewind_the_curve():
    tok = T.Token(MINT, DEV, T0, 1, 30 * SOL, 1_073 * 10 ** 12, C.INITIAL_RT, {})
    tok.trade(T0 + 10, 2, True, SOL, 10, BUYERS[0], 40 * SOL, 1_000 * 10 ** 12, 10 * SOL, 700 * 10 ** 12, 95, 30,
              slot=20)
    tok.trade(T0 + 20, 3, True, SOL, 10, BUYERS[1], 35 * SOL, 1_030 * 10 ** 12, 5 * SOL, 750 * 10 ** 12, 95, 30,
              slot=15)
    assert tok.vs == 40 * SOL and tok.n_buys == 2 and len(tok.buyers) == 2


def test_the_dev_is_the_creator_and_the_payer_of_the_creation():
    payer = key(99)
    tok = T.Token(MINT, DEV, T0, 7, 30 * SOL, 1_073 * 10 ** 12, C.INITIAL_RT, {}, user=payer)
    tok.trade(T0, 7, True, SOL, 10 ** 12, payer, 31 * SOL, 1_072 * 10 ** 12, SOL, 792 * 10 ** 12, 95, 30, slot=5)
    tok.trade(T0, 8, True, SOL, 10 ** 12, BUYERS[0], 32 * SOL, 1_071 * 10 ** 12, 2 * SOL, 791 * 10 ** 12, 95, 30,
              slot=6)
    assert tok.dev_buy_l == SOL and tok.dev_hold() == 10 ** 12 and tok.outside_buyers() == 1


def test_trades_of_one_slot_chain_up_in_any_order_and_a_missing_one_is_counted():
    tok = T.Token(MINT, DEV, T0, 1, 30 * SOL, 1_073 * 10 ** 12, C.INITIAL_RT, {})
    a = (True, SOL, 31 * SOL)                               # 30 -> 31
    b = (True, 2 * SOL, 33 * SOL)                           # 31 -> 33
    for buy, sol, vs in (b, a):                             # the later one arrives first
        tok.trade(T0, 2, buy, sol, 1, BUYERS[0], vs, 1_000 * 10 ** 12, vs - 30 * SOL, 700 * 10 ** 12, 95, 30,
                  slot=10)
    assert tok.vs == 33 * SOL and tok.slot_ok
    tok.trade(T0, 3, True, SOL, 1, BUYERS[1], 40 * SOL, 990 * 10 ** 12, 10 * SOL, 690 * 10 ** 12, 95, 30, slot=11)
    assert tok.vs == 40 * SOL and not tok.slot_ok          # 33 -> 39 was never received
    tok.trade(T0, 4, False, SOL, 1, BUYERS[1], 39 * SOL, 991 * 10 ** 12, 9 * SOL, 691 * 10 ** 12, 95, 30, slot=12)
    assert tok.breaks == 1 and tok.slot_ok


def test_gaps_drop_what_overlaps_them():
    eng = sim.Engine([rule(hold=15)], costs=Fixed())
    Curve(eng)
    eng.gap(T0 + 5_000, T0 + 8_000)
    eng.advance(T0 + 30_000)
    eng.drop_gapped()
    assert not eng.closed and eng.counts["closed_dropped_gap"] == 1


def test_decision_rows_and_labels():
    eng = sim.Engine([], costs=Fixed(), decisions=True)
    cv = Curve(eng)
    dev_tok = cv.buy(T0, 2 * SOL, DEV, same_tx=True)
    for i in range(12):
        cv.buy(T0 + 500 + i * 400, SOL // 2, BUYERS[i])
    cv.sell(T0 + 12_000, dev_tok, DEV)                      # dumps between the 10 s and 70 s marks
    eng.advance(T0 + 400_000)
    eng.finish(T0 + 400_000)
    rows = {r["off"]: r for r in eng.row_dicts()}
    assert rows[10]["unique_buyers"] >= 12 and rows[10]["dump60"] == 1.0
    assert rows[3]["dev_hold_share"] > 0 and math.isnan(rows[30]["dump60"])   # nothing left to dump at 30 s
    assert rows[10]["win30"] in (0.0, 1.0) and rows[10]["net30"] < 0          # bought into a dump
    assert all(set(T.FEATURES) <= set(r) for r in eng.row_dicts())


def test_the_stream_order_is_chain_order(tmp_path, monkeypatch):
    w = store.Writer(tmp_path)
    base = {"mint": MINT, "buy": True, "sol": 1, "tok": 1, "user": DEV, "vs": 30 * SOL, "vt": 10 ** 15,
            "rs": 0, "rt": C.INITIAL_RT, "fb": 95, "cfb": 30, "ix": "buy"}
    w.add("trades", {**base, "t": T0 + 9_000, "slot": 50, "tx": 1})        # slot 50 delivered late
    w.add("trades", {**base, "t": T0 + 1_000, "slot": 52, "tx": 2})
    w.add("trades", {**base, "t": T0 + 500, "slot": 51, "tx": 3})
    w.flush(T0)
    got = list(sim.day_events(store.days(tmp_path)[0], tmp_path))
    assert [r["slot"] for _, r in got] == [50, 51, 52]
    assert [r["t"] for _, r in got] == [T0 + 500, T0 + 500, T0 + 1_000]
    assert got[0][1]["recv_t"] == T0 + 9_000


# ---------------------------------------------------------------- the model

def synth_rows(n=3000, signal=True, seed=1):
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(n):
        f = {k: float(rng.normal()) for k in T.FEATURES}
        # nonlinear and in a feature the logistic baseline does not see, so only the model can find it
        p = 1 / (1 + math.exp(-3 * (f["top5_share"] ** 2 - 1))) if signal else 0.3
        y = float(rng.random() < p)
        rows.append({**f, "t": T0 + i * 60_000, "dump60": y, "win30": y, "win300": y, "mig": y})
    return rows


def test_the_model_finds_a_real_signal_and_not_a_fake_one():
    good = M.evaluate(synth_rows(), "win30")
    assert good["useful"] and good["pooled"]["model"]["auc"] > 0.8
    bad = M.evaluate(synth_rows(signal=False), "win30")
    assert not bad["useful"]


def test_walk_forward_purges_rows_whose_label_window_reaches_the_fold():
    rows = synth_rows(2000)
    ev = M.evaluate(rows, "mig")                           # a 6 h horizon on rows a minute apart
    ev30 = M.evaluate(rows, "win30")
    for f, g in zip(ev["folds"], ev30["folds"]):
        assert f["train"] < g["train"]                      # more is purged for the longer label


def test_the_filter_reads_the_rule_horizon_and_the_lift():
    rows = synth_rows(2000)
    models = M.train_all(rows)
    flt = M.Filter(models)
    assert flt.label_for(S.BY_NAME["A_all_x1"]) == "win30" and flt.label_for(S.BY_NAME["C_20in60_x2"]) == "win300"
    hi = {k: 0.0 for k in T.FEATURES} | {"top5_share": 2.5}
    lo = {k: 0.0 for k in T.FEATURES} | {"top5_share": 0.0}
    assert flt.allow(S.BY_NAME["A_all_x1"], hi)[0] and not flt.allow(S.BY_NAME["A_all_x1"], lo)[0]


def test_models_save_and_load(tmp_path):
    models = M.train_all(synth_rows(1500))
    M.save(models, {"x": 1}, tmp_path)
    back = M.load(tmp_path)
    X = M.matrix(synth_rows(50, seed=9))
    assert set(back) == set(M.LABELS)
    assert np.allclose(back["win30"].predict(X), models["win30"].predict(X))


# ---------------------------------------------------------------- the plan

def test_the_registered_rules_are_what_the_plan_says():
    from lab.pumpfun_rt import pipeline as P
    assert len(S.RULES) == 22
    assert len(P.STRATEGIES) == S.PIPELINE_TRIALS + S.POOL0_TRIALS + 5 + 5 + 5 + 5 + 2 == 35   # Y7 to Y11
    assert S.X14_TRIALS == 54
    # 135: Y3's speed tiers, 140: Y5's fill scenarios, 1: P_pool0, 6: Y7's exits (five new, P_pool0 judged again),
    # 5: Y8's, 10: Y9's (five filters under two daily loss limits), 10: Y10's (five books under two limits)
    assert S.N_TRIALS == 22 + 1 + 12 + 54 + 135 + 140 + 1 + 6 + 5 + 10 + 10 + 4
    assert len({r.name for r in S.RULES}) == 22
    assert {r.family for r in S.RULES} == set("ABCDE")
    assert S.DEFAULT_PICK in S.BY_NAME and S.STAKE_SOL == 0.1
    for r in S.RULES:
        assert 0 < r.sl < 1 and r.tp > 0 and r.hold_s > 0


def test_nothing_here_can_touch_a_wallet_or_send_a_transaction():
    import lab.pumpfun_rt as pkg
    for m in pkgutil.iter_modules(pkg.__path__):
        if m.name in ("live_exec", "wallet"):              # the live executor and the owner's wallet tool,
            continue                                       # checked in test_pumpfun_pipeline.py and test_pumpfun_live.py
        src = inspect.getsource(__import__(f"lab.pumpfun_rt.{m.name}", fromlist=["x"])).lower()
        for word in ("sendtransaction", "signtransaction", "keypair", "private_key", "privatekey", "secret_key",
                     "mnemonic", "seed phrase", "solana.rpc", "solders", "jupiter", "sendrawtransaction",
                     "simulatetransaction", "frontend-api", "pumpportal.fun/api/trade"):
            assert word not in src, f"{m.name}: {word}"
    src = inspect.getsource(COL)
    assert '"logsSubscribe"' in src and "sendTransaction" not in src


# ---------------------------------------------------------------- the study, end to end

def synth_store(root, hours=6, seed=3):
    """A few hours of synthetic tokens: most dumped by their dev, a few run."""
    rng = np.random.default_rng(seed)
    w = store.Writer(root)
    slot = 10_000
    tx = 0
    for k in range(hours * 40):
        t = T0 + k * 90_000
        mint, dev = key(100 + k % 150) + str(k), key(200 + k % 7)
        vs, vt, rt, rs = 30 * SOL, 1_073_000_000 * 10 ** 6, C.INITIAL_RT, 0
        tx += 1
        slot += 3
        w.add("creates", {"t": t, "slot": slot, "tx": tx, "sig": "s", "mint": mint, "creator": dev, "vs": vs,
                          "vt": vt, "rt": rt, "name": "N", "symbol": "SYM", "uri": "https://ipfs.io/ipfs/x"})
        held = {}
        run = rng.random() < 0.2
        for j in range(40):
            tt = t + j * 700 + int(rng.integers(0, 300))
            slot += 1
            tx += 1
            user = dev if j == 0 else BUYERS[int(rng.integers(0, 60))]
            sell = j > 3 and (rng.random() < (0.2 if run else 0.5)) and held.get(user)
            if j == 20 and not run and held.get(dev):
                user, sell = dev, True
            if sell:
                tok = held.pop(user)
                sol = int(vs * tok / (vt + tok))
                vs, vt, rt, rs = vs - sol, vt + tok, rt + tok, rs - sol
            else:
                sol = int(SOL * (0.5 if run else 0.2) * (1 + rng.random()))
                tok = int(vt * sol / (vs + sol))
                vs, vt, rt, rs = vs + sol, vt - tok, rt - tok, rs + sol
                held[user] = held.get(user, 0) + tok
            w.add("trades", {"t": tt, "slot": slot, "tx": tx, "mint": mint, "buy": not sell, "sol": sol, "tok": tok,
                             "user": user, "vs": vs, "vt": vt, "rs": rs, "rt": rt, "fb": 95, "cfb": 30, "ix": "buy"})
    w.flush(T0)


def test_the_study_runs_end_to_end_and_reports_with_the_feed_header(tmp_path, monkeypatch):
    synth_store(tmp_path)
    monkeypatch.setattr(store, "base", lambda: tmp_path)
    monkeypatch.setattr("lab.pumpfun_rt.study.WARM_DAYS", 0)
    from lab.pumpfun_rt import study
    res = study.run(now_ms=T0 + 3 * 86_400_000, root=tmp_path, log=lambda *a: None, shadow={})
    assert res["pick"] in S.BY_NAME
    from lab.pumpfun_rt import pipeline as P
    assert len(res["results"]) == len(S.RULES) + 1 + len(P.STRATEGIES)
    data, md = study.report(res)
    for k in ("title", "status", "headline", "updated_ms", "items"):
        assert k in data
    assert data["status"] in ("ok", "watch", "bad") and "Too early" in data["headline"]
    assert "—" not in md and "—" not in data["headline"]
    json.dumps(data, default=str)
    from lab.ops import i18n
    from lab.pumpfun_rt import card
    shadow = {res["pick"]: {"n": 3, "wins": 1, "mean": -0.2, "pnl_sol": -0.06}}
    data = json.loads(json.dumps(data, default=str))
    en = card.daily_card(data, None, shadow, None, res["now_ms"], "en").render("telegram", "en")
    de = card.daily_card(data, None, shadow, None, res["now_ms"], "de").render("telegram", "de")
    assert "Paper only" in en and "Nur Paper" in de and en != de
    from test_i18n import no_english
    no_english(de)
    assert i18n.t("prt_daily_title", "de", day="x").startswith("pump.fun Echtzeit")


def test_the_winner_card_in_english_and_german():
    from lab.pumpfun_rt import live
    rec = {"rule": "C_20in60_x1", "mint": MINT, "symbol": "TST", "ret": 2.5, "proceeds_sol": 0.35, "hold_s": 42,
           "exit_why": "take", "exit_ms": T0}
    en = live.winner_card(rec, "en").render("telegram", "en")
    de = live.winner_card(rec, "de").render("telegram", "de")
    assert "+250%" in en and "0.350 SOL" in en and "Gewinnmitnahme" in de and "0,350 SOL" in de
    from test_i18n import no_english
    no_english(de)


def test_the_shadow_book_trades_the_pick_and_logs_closes(tmp_path, monkeypatch):
    from lab.pumpfun_rt import live
    monkeypatch.setattr(live, "paper_dir", lambda: tmp_path)
    sh = live.Shadow("A_all_x1", models=None, alerts=False, now_ms=T0)
    eng = sh.engine
    cv = Curve(eng)
    cv.buy(T0 + 3_000, 15 * SOL, BUYERS[0])
    sh.tick(T0 + 60_000)
    sh.save()
    assert (tmp_path / "ledger.csv").exists() and sh.totals["A_all_x1"]["n"] == 1
    assert eng.skipped[("A_all_x1+model", "no model")] == 1          # no model yet: the filtered book waits
    st = json.loads((tmp_path / "state.json").read_text())
    assert st["pick"] == "A_all_x1"
