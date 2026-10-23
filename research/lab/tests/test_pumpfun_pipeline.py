"""The pump.fun trading pipeline (plan addendum 2): the pre-registered strategies, sizing and
risk limits, the exits (take-profit ladder, stop, trailing, dev sell, liquidity pull, time,
kill switch), paper and live executors behind one interface, the LOCKED live executor's gate
(nothing is ever read from a wallet file here: the live tests use a fake signer), the
transaction builder, wallet reputation, name categories through a fake AI endpoint, the
exit-model labels, feature-set adoption, the retrain, readiness and the cards. No network.

Run from research/lab:  python -m pytest tests/test_pumpfun_pipeline.py
"""

from __future__ import annotations

import json
import math
import struct
from datetime import datetime, timezone

import numpy as np
import pytest

from lab.pumpfun_rt import card as CARD
from lab.pumpfun_rt import categorize as CAT
from lab.pumpfun_rt import curve as C
from lab.pumpfun_rt import live_exec as LX
from lab.pumpfun_rt import model as M
from lab.pumpfun_rt import pipeline as P
from lab.pumpfun_rt import sim
from lab.pumpfun_rt import strategies as S
from lab.pumpfun_rt import tokens as T
from lab.pumpfun_rt import txbuild as X
from lab.pumpfun_rt import wallets as W
from test_pumpfun_rt import BUYERS, DEV, MINT, SOL, T0, Curve, Fixed, key


@pytest.fixture(autouse=True)
def small_models(monkeypatch, tmp_path):
    monkeypatch.setitem(M.PARAMS, "n_estimators", 30)
    monkeypatch.setattr(LX, "data_dir", lambda: tmp_path / "live")       # the live files stay in the test


def strat(name="X", entry="create", ladder=((0.3, 0.5), (0.8, 1.0)), sl=0.3, trail=(None, None), time_s=60,
          p=None, flt=None, risk=None, family="A") -> P.Strategy:
    ex = P.Exits(time_s, sl, ladder, trail[0], trail[1], risk=risk)
    return P.Strategy(name, family, entry, ladder[-1][0] if ladder else 0.0, sl, time_s,
                      p if p is not None else {"filter": "all"}, "test", exits=ex, flt=flt or {})


def paper(*strats, kill=None, models=None, **kw) -> sim.Engine:
    return sim.Engine([], costs=Fixed(), strategies=list(strats), kill=kill, models=models, **kw)


# ---------------------------------------------------------------- the registered strategies

def test_the_registered_strategies_are_what_the_plan_says():
    assert [s.name for s in P.STRATEGIES] == ["P_snipe_dev", "P_snipe_cmig", "P_press10", "P_mom_model", "P_p90",
                                              "P_p80_smart", "P_pool60", "P_cmig_model", "P_early10", "P_early30",
                                              "P_press10_hz", "P_pool60_hz", "P_pool0", "P_pool0_half_trail",
                                              "P_pool0_ladder3", "P_pool0_trail", "P_pool0_half_trail_guard",
                                              "P_pool0_half_trail_ext"]
    assert S.N_TRIALS == (len(S.RULES) + 1 + S.PIPELINE_TRIALS + S.X14_TRIALS + S.SPEED_TRIALS
                          + S.REAL_LATENCY_TRIALS + S.POOL0_TRIALS + S.EXIT_RUNNER_TRIALS)
    # P_pool0 copies E_d0_x1's exits exactly, without the dev-sell and pull exits; of Y7's variants on it only
    # the guard has them
    no_guard = {"P_pool0", "P_pool0_half_trail", "P_pool0_ladder3", "P_pool0_trail", "P_pool0_half_trail_ext"}
    for s in P.STRATEGIES:
        assert isinstance(s, S.Rule) and P.is_strategy(s)
        assert s.exits.ladder[-1][1] == 1.0 and 0 < s.exits.sl < 1 and s.exits.time_s > 0
        assert s.exits.dev_sell == s.exits.pull == (s.name not in no_guard) and s.stake_sol == 0.1
        gains = [g for g, _ in s.exits.ladder]
        assert gains == sorted(gains)
    assert P.BY_NAME["P_mom_model"].exits.risk == ("sell10_10", 2.0)


def test_hard_caps_can_only_be_lowered(monkeypatch):
    big = P.Limits(5.0, 50, 10.0, 99.0).capped()
    assert big == P.Limits(P.HARD_STAKE_SOL, P.HARD_MAX_OPEN, P.HARD_MAX_EXPOSURE_SOL, P.HARD_MAX_DAILY_LOSS_SOL)
    monkeypatch.setenv("PYTHIA_PUMPFUN_STAKE_SOL", "7")
    monkeypatch.setenv("PYTHIA_PUMPFUN_MAX_OPEN", "2")
    lim = P.env_limits()
    assert lim.stake_sol == P.HARD_STAKE_SOL and lim.max_open == 2


# ---------------------------------------------------------------- entries and exits on paper

def test_the_ladder_sells_in_steps_and_closes_on_the_last():
    eng = paper(strat(ladder=((0.3, 0.5), (0.8, 1.0)), sl=0.9, time_s=600))
    cv = Curve(eng)
    cv.buy(T0 + 2_000, 6 * SOL, BUYERS[0])                  # +40 %ish after we landed at T0 + 1000
    eng.advance(T0 + 4_000)
    p = next(iter(eng.pipes[0].pos.values()))
    assert p["legs"] == 1 and 0 < p["left"] < p["tokens"]   # half sold
    cv.buy(T0 + 5_000, 25 * SOL, BUYERS[1])                 # far past +80 %
    eng.advance(T0 + 8_000)
    t = eng.closed[0]
    assert t["exit_why"] == "take" and t["legs"] == 2 and t["ret"] > 0.3 and t["book"] == "paper"


def test_the_dev_selling_is_an_exit_in_the_same_slot_window():
    eng = paper(strat(sl=0.99, ladder=((5.0, 1.0),), time_s=600))
    cv = Curve(eng)
    dev_tok = cv.buy(T0, 2 * SOL, DEV, same_tx=True)
    cv.buy(T0 + 1_500, SOL, BUYERS[0])
    cv.sell(T0 + 3_000, dev_tok // 5, DEV)                  # 20 % of the dev's holding
    eng.advance(T0 + 10_000)
    t = eng.closed[0]
    assert t["exit_why"] == "dev_sell" and t["exit_signal_ms"] == T0 + 3_000 and t["exit_ms"] == T0 + 4_000


def test_a_large_holder_dumping_is_a_liquidity_pull():
    eng = paper(strat(sl=0.99, ladder=((5.0, 1.0),), time_s=600))
    cv = Curve(eng)
    whale = cv.buy(T0 + 1_200, 10 * SOL, BUYERS[0])          # after our landing, a big holder
    cv.sell(T0 + 4_000, whale, BUYERS[0])
    eng.advance(T0 + 10_000)
    assert eng.closed[0]["exit_why"] == "pull"


def test_trailing_stop_and_time_stop():
    eng = paper(strat(sl=0.99, ladder=((5.0, 1.0),), trail=(0.2, 0.15), time_s=600))
    cv = Curve(eng)
    a = cv.buy(T0 + 2_000, 8 * SOL, BUYERS[0])              # up well past +20 %
    for i in range(8):                                       # then small sales walk it down, none a pull
        cv.sell(T0 + 3_000 + i * 3_000, a // 15, BUYERS[0])
    eng.advance(T0 + 40_000)
    assert eng.closed and eng.closed[0]["exit_why"] == "trail"
    eng2 = paper(strat(sl=0.99, ladder=((5.0, 1.0),), time_s=20))
    Curve(eng2)
    eng2.advance(T0 + 30_000)
    t = eng2.closed[0]
    assert t["exit_why"] == "time" and t["exit_signal_ms"] == T0 + 21_000 and t["ret"] < 0


def test_a_buy_over_its_cost_limit_fails_and_books_the_fee():
    eng = paper(strat())
    cv = Curve(eng)
    cv.buy(T0 + 500, 25 * SOL, BUYERS[0])                   # the price runs away before we land
    eng.advance(T0 + 5_000)
    f = eng.failed[0]
    assert f["why"] == "slippage" and f["pnl_sol"] < 0 and not eng.pipes[0].pos
    assert eng.pipes[0].risk["X"].day_pnl_l < 0


def test_risk_limits_open_positions_exposure_and_daily_loss():
    s = strat(sl=0.99, ladder=((5.0, 1.0),), time_s=600)
    eng = paper(s)
    for i in range(7):
        Curve(eng, mint=key(30 + i), t=T0 + i * 10, slot=1000 + i * 100)
    eng.advance(T0 + 5_000)
    assert len(eng.pipes[0].pos) == 4                       # 4 x 0.13 SOL cost limit fits 0.6, a fifth does not
    assert eng.skipped[("X", "max exposure")] == 3
    r = P.Risk(P.Limits(max_daily_loss_sol=0.2))
    r.booked(T0, -int(0.25 * SOL))
    assert r.why_not(T0 + 1, int(0.13 * SOL)) == "daily loss stop"
    assert r.why_not(T0 + P.DAY_MS, int(0.13 * SOL)) is None          # a new UTC day


def test_the_kill_switch_stops_buys_and_sells_what_is_open(tmp_path):
    flag = tmp_path / "KILL"
    ks = P.KillSwitch([flag], every_s=0)
    eng = paper(strat(sl=0.99, ladder=((5.0, 1.0),), time_s=600), kill=ks)
    Curve(eng)
    eng.advance(T0 + 2_000)
    assert len(eng.pipes[0].pos) == 1
    flag.write_text("stop")
    eng.pipes[0].poll(T0 + 2_100)
    eng.advance(T0 + 5_000)
    assert eng.closed[0]["exit_why"] == "kill"
    Curve(eng, mint=key(40), t=T0 + 6_000, slot=5000)
    eng.advance(T0 + 9_000)
    assert eng.skipped[("X", "kill switch")] == 1


def test_sizing_never_spends_more_than_two_percent_of_the_curve():
    eng = paper(strat(sl=0.99, ladder=((5.0, 1.0),), time_s=600))
    tiny = 3 * SOL                                           # a curve with 3 SOL virtual: 0.06 SOL at most
    eng.create(T0, 1, MINT, DEV, tiny, 1_073 * 10 ** 12, C.INITIAL_RT)
    eng.advance(T0 + 100)
    p = next(iter(eng.pipes[0].pos.values()))
    assert p["stake_l"] == int(P.MAX_IMPACT * tiny)


def test_a_model_filter_needs_its_model():
    s = strat(flt={"model": {"up30": ("min", 1.25)}})
    eng = paper(s)
    Curve(eng)
    eng.advance(T0 + 2_000)
    assert eng.skipped[("X", "no model")] == 1 and not eng.pipes[0].pos


def test_the_cost_of_an_exact_amount_inverts_the_curve():
    vs, vt, rt = 30 * SOL, 1_073_000_000 * 10 ** 6, C.INITIAL_RT
    want = C.curve_buy(SOL // 10, vs, vt, rt, 125)
    assert abs(P.curve_cost(want, vs, vt, 125) - SOL // 10) <= 2
    assert P.pool_cost(10, 10, SOL, 25) > 10 ** 18


# ---------------------------------------------------------------- one interface, paper and live

class FakeSigner:
    pubkey = key(77)

    def sign(self, msg: bytes) -> bytes:
        return b"\x01" * 64


class FakeRpc:
    def __init__(self):
        self.sent = []

    def send(self, tx: bytes) -> str:
        self.sent.append(tx)
        return f"sig{len(self.sent)}"

    def statuses(self, sigs):
        return [None for _ in sigs]


class FakeBuilder:
    def __init__(self):
        self.rpc = FakeRpc()
        self.priority_l = 1_000_000
        self.built = []

    def build(self, user, o, pool, close):
        self.built.append((o.side, o.tokens, o.limit_l, close))
        return X.compile_message(user, [X.compute_limit(1000)], key(5))


class OpenGate:
    def __init__(self):
        self.why = []

    def check(self):
        return list(self.why)


def test_paper_and_live_executors_have_the_same_interface():
    for name in ("attach", "ready", "buy", "sell", "on_trade", "poll"):
        assert callable(getattr(P.PaperExecutor, name)) and callable(getattr(LX.LiveExecutor, name))


def test_the_live_executor_takes_its_fills_from_our_own_trades():
    gate = OpenGate()
    ex = LX.LiveExecutor(gate, FakeSigner(), FakeBuilder(), P.Limits(), clock=lambda: T0, start=False)
    eng = sim.Engine([], costs=Fixed())
    pipe = eng.add_pipe(P.Pipeline(eng, [strat(sl=0.99, ladder=((0.3, 1.0),), time_s=600)], ex, name="live",
                                   record=False))
    cv = Curve(eng)
    eng.advance(T0 + 1)
    assert len(pipe.pos) == 1 and ex.pending
    ex.drain()
    pipe.poll(T0 + 100)
    # the transaction's own signature, whatever the endpoint answered ("sig1")
    assert ex.pending[0]["sig"] == X.b58(b"\x01" * 64) and ex.builder.built[0][0] == "buy"
    cv.buy(T0 + 900, int(0.1 * SOL), FakeSigner.pubkey)     # our own buy lands on the curve
    p = pipe.pos[0]
    assert p["state"] == "open" and p["tokens"] > 0 and not ex.pending
    cv.buy(T0 + 2_000, 15 * SOL, BUYERS[0])                 # the take-profit step
    ex.drain()
    pipe.poll(T0 + 2_100)
    side, tokens, floor, close = ex.builder.built[-1]
    assert side == "sell" and tokens == p["tokens"] and floor > 0 and close
    cv.sell(T0 + 2_500, tokens, FakeSigner.pubkey)           # our sale on the stream
    assert not pipe.pos and pipe.closed[0]["exit_why"] == "take" and pipe.closed[0]["book"] == "live"
    assert not ex.exposure


def test_the_live_executor_refuses_above_its_own_caps_and_when_the_gate_shuts():
    gate = OpenGate()
    ex = LX.LiveExecutor(gate, FakeSigner(), FakeBuilder(), P.Limits(max_open=1), clock=lambda: T0, start=False)
    big = P.Order(1, "buy", MINT, "curve", 10, int(0.5 * SOL), T0)
    assert ex._caps(big) == "above the stake cap"
    ex.exposure[9] = 1
    assert ex._caps(P.Order(2, "buy", MINT, "curve", 10, int(0.1 * SOL), T0)) == "max open positions"
    gate.why = ["the kill switch file is there"]
    ex.last_check = -1e18
    assert "kill switch" in ex.ready()


# ---------------------------------------------------------------- the gate (no wallet file is ever read here)

def ready_report(tmp_path, rule="P_p90", ready=True, age_h=1):
    r = {"updated_ms": T0 - age_h * 3_600_000, "readiness": {rule: {"ready": ready, "days_ok": ready,
                                                                     "trades_ok": True, "positive_ok": True,
                                                                     "gates_ok": ready, "shadow_ok": ready}}}
    p = tmp_path / "latest.json"
    p.write_text(json.dumps(r))
    return p


FIELD_TYPES = {"buyback_fee_recipients": {"array": ["pubkey", 8]}, "is_mayhem_mode": "bool",
               "is_cashback_coin": "bool", "quote_mint": "pubkey", "base_mint": "pubkey",
               "pool_base_token_account": "pubkey", "pool_quote_token_account": "pubkey",
               "virtual_quote_reserves": "i128"}


def idl_types(prog):
    """The account types the builder reads, each field at its offset (padding between), as an IDL has them."""
    out = {}
    for type_name, fld in X.READS[prog]:
        out.setdefault(type_name, []).append((X.OFFSETS[(type_name, fld)], fld))
    types = []
    for type_name, fields in out.items():
        pos, rows = 8, []
        for off, fld in sorted(fields):
            if off > pos:
                rows.append({"name": f"pad_{off}", "type": {"array": ["u8", off - pos]}})
            rows.append({"name": fld, "type": FIELD_TYPES[fld]})
            pos = off + X._size(FIELD_TYPES[fld])
        types.append({"name": type_name, "type": {"kind": "struct", "fields": rows}})
    return types


def idl_docs():
    def doc(prog):
        return {"instructions": [{"name": ix, "discriminator": list(X.discriminator(ix)),
                                  "accounts": [{"name": n, "writable": n in X.WRITABLE, "signer": n in X.SIGNERS}
                                               for n in X.ACCOUNTS[(p, ix)]],
                                  "args": [{"name": a, "type": "u64"} for a in X.ARGS[(p, ix)]]}
                                 for (p, ix) in X.ACCOUNTS if p == prog],
                "types": idl_types(prog)}
    return doc("pump"), doc("amm")


def full_gate(tmp_path, monkeypatch, **over):
    ack = tmp_path / "ack"
    ack.write_text(over.get("ack", "rule=P_p90\nmax_daily_loss_sol=0.4\n"))
    idl = tmp_path / "idl"
    idl.mkdir()
    pump, amm = idl_docs()
    (idl / "pump.json").write_text(json.dumps(pump))
    (idl / "pump_amm.json").write_text(json.dumps(amm))
    wallet = tmp_path / "wallet-file"
    wallet.write_text("not a key: the gate only looks at the file, never reads it")
    if hasattr(wallet, "chmod"):
        wallet.chmod(0o600)
    (tmp_path / "wallet-file.pub").write_text(FakeSigner.pubkey + "\n")
    env = {"PYTHIA_PUMPFUN_LIVE": "1", "PYTHIA_PUMPFUN_KEYPAIR": str(wallet),
           "PYTHIA_PUMPFUN_RPC": "https://rpc.example.org"}
    env.update(over.get("env", {}))
    monkeypatch.setattr(LX, "crypto_ok", lambda: True)
    return LX.LiveGate(ack, ready_report(tmp_path, **over.get("report", {})), env=env, kill=lambda: False,
                       now_ms=lambda: T0, idl_path=idl)


def test_the_gate_is_shut_by_default_and_names_every_reason(tmp_path):
    g = LX.LiveGate(tmp_path / "none", tmp_path / "none.json", env={}, kill=lambda: True, now_ms=lambda: T0,
                    idl_path=tmp_path)
    why = " | ".join(g.check())
    for part in ("PYTHIA_PUMPFUN_LIVE is not 1", "no owner confirmation", "no readiness report", "kill switch",
                 "PYTHIA_PUMPFUN_KEYPAIR is not set", "no pump IDL"):
        assert part in why, part


def test_the_gate_opens_only_when_everything_holds(tmp_path, monkeypatch):
    g = full_gate(tmp_path, monkeypatch)
    assert g.check() == [] and g.rule == "P_p90" and g.max_loss == 0.4
    for over, words in (({"report": {"ready": False}}, "not ready"), ({"report": {"age_h": 48}}, "48 h old"),
                        ({"ack": "rule=P_nothing\nmax_daily_loss_sol=1"}, "not a pipeline strategy"),
                        ({"ack": "rule=P_p90\n"}, "max_daily_loss_sol"),
                        ({"env": {"PYTHIA_PUMPFUN_LIVE": "0"}}, "is not 1"),
                        ({"env": {"PYTHIA_PUMPFUN_RPC": "https://mainnet.block-engine.jito.wtf"}},
                         "PYTHIA_PUMPFUN_JITO is not 1"),             # Y3: Jito only with the owner's switch
                        ({"env": {"PYTHIA_PUMPFUN_RPC": "https://x.example/relay"}}, "relay"),
                        ({"env": {"PYTHIA_PUMPFUN_RPC": "http://rpc.example.org"}}, "https")):
        d = tmp_path / str(abs(hash(str(over))))
        d.mkdir()
        why = " | ".join(full_gate(d, monkeypatch, **over).check())
        assert words in why, (over, why)


def test_the_ack_daily_loss_is_capped_and_attach_stays_off_without_the_switch(tmp_path, monkeypatch, capsys):
    ack = tmp_path / "ack"
    ack.write_text("# the owner's confirmation\nrule: P_p90\nmax_daily_loss_sol: 25\n")
    a = LX.read_ack(ack)
    assert (a.mode, a.rule, a.max_daily_loss_sol, a.problems) == ("full", "P_p90", P.HARD_MAX_DAILY_LOSS_SOL, ())
    monkeypatch.delenv("PYTHIA_PUMPFUN_LIVE", raising=False)
    assert LX.attach(sim.Engine([])) is None
    monkeypatch.setenv("PYTHIA_PUMPFUN_LIVE", "1")
    g = LX.LiveGate(tmp_path / "none", tmp_path / "none.json", env={"PYTHIA_PUMPFUN_LIVE": "1"},
                    kill=lambda: False, now_ms=lambda: T0, idl_path=tmp_path)
    assert LX.attach(sim.Engine([]), g) is None
    assert "stays OFF" in capsys.readouterr().out


def test_the_signer_never_shows_its_key():
    s = LX.Signer(object(), key(77))
    assert "hidden" in repr(s) and "hidden" in str(s)


def test_the_live_module_is_the_only_one_that_could_sign_or_send():
    import inspect
    import pkgutil
    import lab.pumpfun_rt as pkg
    words = ("sendtransaction", "keypair", "private_key", "secret_key", "mnemonic", "load_signer")
    for m in pkgutil.iter_modules(pkg.__path__):
        src = inspect.getsource(__import__(f"lab.pumpfun_rt.{m.name}", fromlist=["x"])).lower()
        if m.name == "live_exec":
            continue
        if m.name == "wallet":                              # the owner's wallet tool makes keys, never signs or sends
            for w in ("sendtransaction", ".sign(", "urllib", "aiohttp", "notify", "simulatetransaction"):
                assert w not in src, f"wallet: {w}"
            continue
        for w in words:
            assert w not in src, f"{m.name}: {w}"
    src = inspect.getsource(LX)
    assert "Ed25519PrivateKey.generate" not in src and ".generate(" not in src     # never makes a key
    assert "Keypair(" not in src and "solders" not in src
    for url in ("https://mainnet.block-engine.jito.wtf/api/v1/bundles", "https://x.example/relay"):
        assert LX.rpc_problems(url)                         # bundles and relays are refused
    assert LX.rpc_problems("https://api.mainnet-beta.solana.com") == []


# ---------------------------------------------------------------- the transactions

def test_program_addresses_and_the_message_layout():
    assert X.pda([b"global"], X.PUMP) == "4wTV1YmiEkRvAtNtsSGPtUrqRYQMe5SKy2uB4Jjaxnjf"
    assert X.pda([b"__event_authority"], X.PUMP) == "Ce6TQqeHC9p8KetsN6JsjHK7UTZk7nasjjnr7XxXp9F1"
    user = key(77)
    info = X.CurveInfo(MINT, X.TOKEN, X.BUYBACK_FEE_RECIPIENTS[2])
    ixs = X.pump_buy(user, info, 1_000, 2_000, 1_000_000)
    msg = X.compile_message(user, ixs, key(5))
    assert msg[0] == 1 and msg[1] == 0                    # one signer, the payer, writable
    n = msg[3]
    keys = [X.b58(msg[4 + 32 * i: 36 + 32 * i]) for i in range(n)]
    assert keys[0] == user and X.PUMP in keys and X.COMPUTE_BUDGET in keys
    assert X.discriminator("buy_v3") in msg
    tx = X.transaction(msg, [b"\x02" * 64])
    assert tx[0] == 1 and tx.endswith(msg)
    with pytest.raises(ValueError):
        X.transaction(msg, [])
    assert X.shortvec(300) == bytes([0xAC, 0x02])


def test_the_idl_check_and_offsets_come_from_the_owners_copy():
    pump, amm = idl_docs()
    assert X.check_idl(pump, amm) == []
    bad = json.loads(json.dumps(pump))
    bad["instructions"][0]["accounts"].append({"name": "newAccount"})
    assert any("accounts differ" in w for w in X.check_idl(bad, amm))
    idl = X.Idl({"types": [{"name": "BondingCurve", "type": {"kind": "struct", "fields": [
        {"name": "virtual_token_reserves", "type": "u64"}, {"name": "virtual_quote_reserves", "type": "u64"},
        {"name": "real_token_reserves", "type": "u64"}, {"name": "real_quote_reserves", "type": "u64"},
        {"name": "token_total_supply", "type": "u64"}, {"name": "complete", "type": "bool"},
        {"name": "creator", "type": "pubkey"}, {"name": "is_mayhem_mode", "type": "bool"},
        {"name": "is_cashback_coin", "type": "bool"}, {"name": "quote_mint", "type": "pubkey"}]}}]})
    assert idl.offset("BondingCurve", "quote_mint") == X.OFFSETS[("BondingCurve", "quote_mint")] == 83
    data = bytes(83) + X.key(DEV) + bytes(10)
    assert X.read_key(data, idl.offset("BondingCurve", "quote_mint")) == DEV


def test_the_gate_compares_every_instruction_the_builder_uses_with_the_idl():
    pump, amm = idl_docs()
    assert {i["name"] for i in amm["instructions"]} == {"buy_exact_quote_in_v2", "sell_v2"}
    assert {i["name"] for i in pump["instructions"]} == {"buy_v3", "sell_v3"}

    def broken(doc, ix, how):
        d = json.loads(json.dumps(doc))
        i = next(x for x in d["instructions"] if x["name"] == ix)
        how(i, d)
        return d

    cases = [
        (broken(amm, "sell_v2", lambda i, d: i["accounts"].insert(14, {"name": "protocol_fee_recipient"})),
         "amm sell_v2: the IDL's accounts differ"),
        (broken(amm, "buy_exact_quote_in_v2", lambda i, d: i["args"].append({"name": "track_volume"})),
         "amm buy_exact_quote_in_v2: the IDL's arguments"),
        (broken(amm, "sell_v2", lambda i, d: i.update(discriminator=[0] * 8)), "discriminator"),
        (broken(amm, "sell_v2", lambda i, d: i.update(name="sell")), "amm sell_v2: not in the IDL"),
        (broken(amm, "sell_v2", lambda i, d: d["types"].pop()), "no fixed offset"),
    ]
    for doc, words in cases:
        why = " | ".join(X.check_idl(pump, doc))
        assert words in why, (words, why)
    order = broken(pump, "buy_v3", lambda i, d: i["accounts"].reverse())
    assert any("pump buy_v3: the IDL's accounts differ" in w for w in X.check_idl(order, amm))
    # the pool's virtual_quote_reserves must sit at a fixed offset (an i128 after fixed fields)
    t = next(x for x in amm["types"] if x["name"] == "Pool")
    t["type"]["fields"].insert(0, {"name": "label", "type": "string"})
    assert any("Pool.base_mint" in w for w in X.check_idl(pump, amm))


def test_pool_events_carry_the_signed_virtual_quote_reserves():
    from lab.pumpfun_rt import events as E
    ev = {"timestamp": 1, "base_amount_out": 5, "quote_amount_in": 7, "pool_base_token_reserves": 10 ** 15,
          "pool_quote_token_reserves": 80 * SOL, "pool": key(60), "user": key(77), "ix_name": "buy_exact_quote_in_v2",
          "virtual_quote_reserves": -1_234_567, "creator_fee_unclaimed": 9}
    for name in ("BuyEvent", "SellEvent"):
        raw = E.encode(name, ev)
        got = E.decode(name, raw)
        assert got["virtual_quote_reserves"] == -1_234_567 and got["creator_fee_unclaimed"] == 9
        assert E.REQUIRED[name] in got
        table, row = E.compact(name, got, T0, 1, 1)
        assert table == "amm" and row["vq"] == -1_234_567 and row["pq"] == 80 * SOL
        old = E.decode(name, raw[:8 + 8 * 14 + 32 * 2])                # an event from before the appended fields
        assert "virtual_quote_reserves" not in old and E.compact(name, old, T0, 1, 1)[1]["vq"] is None
    assert E.decode("BuyEvent", E.encode("BuyEvent", ev))["ix_name"] == "buy_exact_quote_in_v2"
    # the pool row's quote is the amount before fees, whichever field the buy instruction put it in
    exact_in = dict(ev, quote_amount_in=10_000_000, user_quote_amount_in=9_896_089)
    exact_out = dict(ev, ix_name="buy_v2", quote_amount_in=9_896_089, user_quote_amount_in=10_000_000)
    for e in (exact_in, exact_out):
        got = E.decode("BuyEvent", E.encode("BuyEvent", e))
        assert E.compact("BuyEvent", got, T0, 1, 1)[1]["quote"] == 9_896_089
    eng = sim.Engine([], costs=Fixed())
    cv = Curve(eng)
    eng.complete(T0 + 30_000, MINT)
    eng.migrate(T0 + 31_000, MINT, key(66), 85 * SOL, 206_900_000 * 10 ** 6)
    sim.feed_row(eng, "amm", {"t": T0 + 40_000, "mint": MINT, "buy": True, "base": 10 ** 9, "quote": SOL // 100,
                              "pb": 206_900_000 * 10 ** 6, "pq": 67 * SOL, "lpb": 20, "pfb": 5, "cfb": 5, "slot": 2000,
                              "user": key(77), "vq": -2 * SOL})
    tok = eng.tokens[MINT]
    assert tok.pq == 65 * SOL + SOL // 100 and cv is not None


def test_pool_trades_wrap_and_unwrap_sol():
    user = key(77)
    p = X.PoolInfo(key(60), MINT, X.WSOL, key(61), key(62), X.TOKEN, X.BUYBACK_FEE_RECIPIENTS[1])
    ixs = X.amm_buy(user, p, 5_000, 1_000, 1_000)
    progs = [ix.program for ix in ixs]
    assert progs.count(X.PUMP_AMM) == 1 and X.SYSTEM in progs and progs[-1] == X.TOKEN   # unwrapped at the end
    wrap = next(ix for ix in ixs if ix.program == X.SYSTEM)
    assert wrap.data == struct.pack("<IQ", 2, 5_000)                  # exactly the stake is wrapped
    msg = X.compile_message(user, ixs, key(5))
    assert msg[0] == 1


# ---------------------------------------------------------------- wallets and labels

def test_wallet_reputation_is_point_in_time():
    eng = sim.Engine([], costs=Fixed(), decisions=False)
    smart = BUYERS[0]
    for k in range(3):                                       # three tokens it bought early, two complete
        cv = Curve(eng, mint=key(80 + k), t=T0 + k * 100_000, slot=10_000 * (k + 1))
        cv.buy(T0 + k * 100_000 + 1_000, SOL, smart)
        if k < 2:
            eng.complete(T0 + k * 100_000 + 50_000, key(80 + k))
    r = eng.wallets.get(smart)
    assert r == [3, 2, 0] and W.smart(r) and not W.flipper(r)
    cv = Curve(eng, mint=key(90), t=T0 + 400_000, slot=90_000)
    cv.buy(T0 + 401_000, SOL, smart)
    f = eng.features(eng.tokens[key(90)], T0 + 402_000)
    assert f["w_smart_n"] == 1 and f["w_early_known"] == 1 and set(W.WALLET_FEATURES) <= set(f)


def test_exit_model_labels_in_the_decision_rows():
    eng = sim.Engine([], costs=Fixed(), decisions=True)
    cv = Curve(eng)
    dev_tok = cv.buy(T0, 2 * SOL, DEV, same_tx=True)
    for i in range(10):
        cv.buy(T0 + 500 + i * 300, SOL // 2, BUYERS[i])
    cv.sell(T0 + 12_000, dev_tok, DEV)                       # the dev dumps 9 s after the 3 s row
    for i in range(10):
        cv.buy(T0 + 20_000 + i * 2_000, SOL, BUYERS[20 + i])  # the price climbs after
    eng.advance(T0 + 400_000)
    eng.finish(T0 + 400_000)
    rows = {r["off"]: r for r in eng.row_dicts()}
    assert rows[3]["sell10_10"] == 1.0 and rows[3]["sell10_30"] == 1.0
    assert rows[30]["up10"] == 1.0
    assert set(sim.ALL_FEATURES) <= set(rows[3])


# ---------------------------------------------------------------- name categories

class FakeAi:
    def __init__(self, code="animal", status=200, cost=0.001):
        self.calls, self.code, self.status, self.cost = [], code, status, cost

    def __call__(self, url, body, tok, timeout):
        self.calls.append(body)
        n = sum(1 for line in body["user"].splitlines() if line[:1].isdigit())
        if self.status != 200:
            return self.status, {"error": "no"}
        return 200, {"json": {"items": [{"i": i, "c": self.code} for i in range(n)]}, "costUsd": self.cost}


def write_day(root, rows):
    from lab.pumpfun_rt import store
    w = store.Writer(root)
    for i, (name, sym) in enumerate(rows):
        w.add("creates", {"t": T0 + i, "slot": 10 + i, "tx": i, "sig": "s", "mint": key(100 + i) + str(i),
                          "creator": DEV, "vs": 30 * SOL, "vt": 10 ** 15, "rt": C.INITIAL_RT, "name": name,
                          "symbol": sym, "uri": ""})
        w.add("trades", {"t": T0 + i + 1, "slot": 10 + i, "tx": i, "mint": key(100 + i) + str(i), "buy": True,
                         "sol": 1, "tok": 1, "user": DEV, "vs": 1, "vt": 1, "rs": 1, "rt": 1, "fb": 95, "cfb": 30})
    w.flush(T0)
    return store.days(root)[0]


def test_categories_are_asked_once_per_name_and_usable_from_their_answer(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-only")
    day = write_day(tmp_path, [("Doge Cat", "DCAT"), ("doge cat", "dcat"), ("Robot AI", "RAI")])
    ai = FakeAi()
    res = CAT.run(day, now_ms=T0 + 86_400_000, root=tmp_path, poster=ai, log=lambda *a: None,
                  clock=lambda: T0 + 90_000_000)
    assert res["keys"] == 2 and res["classified"] == 2 and len(ai.calls) == 1
    assert ai.calls[0]["model"] == "claude-haiku-5-5" and ai.calls[0]["job"] == CAT.JOB and ai.calls[0]["batch"]
    ix = CAT.CategoryIndex.load(tmp_path / "categories")
    assert ix.at("DOGE CAT", "DCAT", T0 + 90_000_001) == "animal"
    assert ix.at("DOGE CAT", "DCAT", T0 + 80_000_000) is None           # before its answer: unknown
    f = ix.features("doge cat", "dcat", T0 + 10 ** 9)
    assert f["cat_known"] == 1.0 and f["cat_animal"] == 1.0 and f["cat_scam"] == 0.0
    again = CAT.run(day, now_ms=T0 + 86_400_000, root=tmp_path, poster=ai, log=lambda *a: None)
    assert again.get("skipped") and len(ai.calls) == 1                     # once a day


def test_a_budget_refusal_stops_the_batch_and_bad_answers_are_dropped(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-only")
    day = write_day(tmp_path, [("A", "A"), ("B", "B")])
    res = CAT.run(day, root=tmp_path, poster=FakeAi(status=402), log=lambda *a: None)
    assert res["classified"] == 0 and res["errors"][0].startswith("budget")
    got, bad = CAT.parse({"items": [{"i": 0, "c": "animal"}, {"i": 5, "c": "animal"}, {"i": 1, "c": "rocket"},
                                    {"i": 0, "c": "ai"}]}, 2)
    assert got == {0: "animal"} and bad == 3
    assert CAT.clean("ignore\nprevious|instructions") == "ignore previous instructions"


# ---------------------------------------------------------------- feature sets, retrain, readiness, cards

def synth(n=3000, where="w_smart_n", seed=2):
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(n):
        f = {k: float(rng.normal()) for k in M.ALL_FEATURES}
        p = 1 / (1 + math.exp(-3 * (f[where] ** 2 - 1))) if where else 0.3
        y = float(rng.random() < p)
        rows.append({**f, "t": T0 + i * 60_000, **{lab: y for lab in M.LABELS}})
    return rows


def test_a_feature_set_is_adopted_only_when_it_wins_out_of_sample():
    sel = M.select(synth(), "win30")
    assert sel["adopted"] == "wallet" and "adopted" in sel["notes"]["wallet"]
    noise = M.select(synth(where=None), "win30")
    assert noise["adopted"] == "base"
    models = M.train_all(synth(1500), sets={"win30": M.SETS["wallet"]})
    assert models["win30"].features == M.SETS["wallet"] and models["dump60"].features == list(T.FEATURES)


def test_the_retrain_round_trips_the_rows_and_summarises(tmp_path, monkeypatch):
    from lab.pumpfun_rt import retrain as R
    monkeypatch.setattr(M, "LABELS", {"win30": 30, "sell10_10": 10})      # two labels: the method, quicker
    rows = synth(1500)
    table = M.as_frame(rows)
    p = R.save_rows(table, {"days": ["x"]}, tmp_path / "rows.parquet")
    back, meta = R.load_rows(p)
    assert meta["days"] == ["x"] and np.allclose(back["t"], table["t"])
    res = R.run(back, log=lambda *a: None)
    summ = R.summary(res, T0)
    assert set(summ["labels"]) == set(M.LABELS) and summ["trials"] >= 2 * len(M.LABELS)
    md = R.report_md(summ, res["importance"])
    assert "—" not in md and "| win30 |" in md


def test_readiness_needs_every_condition():
    from lab.pumpfun_rt import study
    gates = {"g1_mean_band": True, "g2_size": True, "g3_stress": True, "g4_breadth": True, "g5_deflated": True}
    r = {"rule": "P_p90", "pipeline": True, "band": (0.01, 0.05), "gates": gates,
         "stats": {"n": 400, "mean": 0.03, "mean_clean": 0.02}}
    ok = study.readiness([r], 20, {"P_p90": {"n": 900, "mean": 0.02, "days": 31}})["P_p90"]
    assert ok["ready"]
    for shadow in ({"n": 900, "mean": 0.2, "days": 31}, {"n": 900, "mean": 0.02, "days": 12}, {}):
        assert not study.readiness([r], 20, {"P_p90": shadow} if shadow else {})["P_p90"]["ready"]
    assert not study.readiness([dict(r, stats={"n": 400, "mean": 0.03, "mean_clean": -0.01})], 20,
                               {"P_p90": {"n": 900, "mean": 0.02, "days": 31}})["P_p90"]["ready"]
    assert not study.readiness([r], 9, {"P_p90": {"n": 900, "mean": 0.02, "days": 31}})["P_p90"]["ready"]


def test_the_daily_card_in_english_and_german():
    from lab.ops import i18n
    from test_i18n import no_english
    y = "2026-10-19"
    data = {"record": {y: {"tokens": 90_000, "trades": 4_000_000, "completed": 900}}, "days": [y] * 3, "pick": "B_w3_x1",
            "results": [{"rule": "B_w3_x1", "passes": False}],
            "readiness": {"P_p90": {"days": 3, "trades": 40, "shadow_days": 2, "gates_ok": False, "positive_ok": True,
                                    "ready": False}}}
    models = {"labels": {"win30": {}, "up30": {}}, "useful": 1, "wallet_adopted": 1, "cat_adopted": 0}
    shadow = {"P_p90": {"n": 5, "wins": 2, "mean": 0.04, "pnl_sol": 0.02}, "B_w3_x1": {"n": 40, "wins": 8,
                                                                                       "mean": -0.09, "pnl_sol": -0.36}}
    now = int(datetime(2026, 10, 20, 7, tzinfo=timezone.utc).timestamp() * 1000)
    en = CARD.daily_card(data, models, shadow, None, now, "en").render("telegram", "en")
    de = CARD.daily_card(data, models, shadow, None, now, "de").render("telegram", "de")
    assert "Closest to live: P_p90" in en and "locked" in en and "P_p90" in de and "gesperrt" in de
    no_english(de)
    live = {"on": True, "rule": "P_p90", "trades_today": 3, "pnl_today_sol": -0.01}
    assert "ON for P_p90" in CARD.daily_card(data, None, {}, live, now, "en").render("telegram", "en")
    assert i18n.t("prt_daily_ready_n", "de", n=0, total=8).startswith("0 von 8")


def test_every_live_trade_has_a_card_in_both_languages():
    from test_i18n import no_english
    p = {"rule": "P_p90", "symbol": "TST", "mint": MINT, "exit_why": "dev_sell"}
    for kind, kw in (("bought", {"tokens": 3_000_000 * C.TOKEN_UNIT, "cost_l": SOL // 10}),
                     ("sold", {"tokens": 1, "got_l": SOL // 20}),
                     ("closed", {"rec": {"ret": -0.42, "pnl_sol": -0.042}}), ("buy_failed", {"why": "slippage"})):
        en = CARD.live_trade_card(kind, p, kw, "en", -0.05).render("telegram", "en")
        de = CARD.live_trade_card(kind, p, kw, "de", -0.05).render("telegram", "de")
        assert "LIVE" in en and "ECHTGELD" in de
        no_english(de)


def test_the_study_judges_the_strategies_and_writes_readiness(tmp_path, monkeypatch):
    from lab.pumpfun_rt import store, study
    from test_pumpfun_rt import synth_store
    synth_store(tmp_path)
    monkeypatch.setattr(store, "base", lambda: tmp_path)
    monkeypatch.setattr("lab.pumpfun_rt.study.WARM_DAYS", 0)
    res = study.run(now_ms=T0 + 3 * 86_400_000, root=tmp_path, log=lambda *a: None, shadow={})
    names = {r["rule"] for r in res["results"]}
    assert {s.name for s in P.STRATEGIES} <= names and len(res["readiness"]) == len(P.STRATEGIES)
    assert not any(v["ready"] for v in res["readiness"].values())
    data, md = study.report(res)
    assert "Readiness for real money" in md and "—" not in md and "readiness" in data
    json.dumps(data, default=str)
    assert "sell10_10" in res["table"] and len(res["table"]["t"]) == res["rows"]


def test_pool0_is_y5s_e_d0_x1_and_nothing_more():
    s, r = P.BY_NAME["P_pool0"], S.BY_NAME["E_d0_x1"]
    assert (s.family, s.entry, s.p) == (r.family, r.entry, r.p) == ("E", "migration", {"delay_s": 0})
    assert (s.exits.ladder, s.exits.sl, s.exits.time_s) == (((r.tp, 1.0),), r.sl, r.hold_s)
    assert not s.exits.dev_sell and not s.exits.pull and s.exits.trail_after is None and not s.flt
    assert s.stake_sol == 0.1 and P.HARD_STAKE_SOL == 0.25      # paper stakes 0.1; the live stake is sized
