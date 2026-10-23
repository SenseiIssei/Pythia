"""Our own wallet's tab and the alpha mode (lab.onchain: live_gate, live_exec, live_service, history, cards,
execution): the alpha gate and its hard maxima, the alpha cards, the history parser against recorded
transactions (deposit, swap, failed), the value chart's points, the measurement of every swap and the
execution report. No network, no key of anyone: every address is a hash of a made-up name.

Run from research/lab:  python -m pytest tests/test_onchain_wallet.py
"""

from __future__ import annotations

import json

import pytest

import test_onchain_live as T
from lab.onchain import cards as C
from lab.onchain import execution as E
from lab.onchain import history as H
from lab.onchain import live_exec as LX
from lab.onchain import live_gate as LG
from lab.onchain import live_service as SV
from lab.onchain import mints as M
from lab.pumpfun_rt import txbuild as X

A, W, OTHER, NOW, TODAY = T.A, T.W, T.OTHER, T.NOW, T.TODAY
USDC, SOL, JUP = M.USDC.mint, M.SOL.mint, M.COINS["JUP"].mint
BOOK = "onchain_breakout_top10_live"

ALPHA = """mode=alpha
books=onchain_breakout_top10_live
mints=SOL,USDC,BTC,ETH
book_usd=80
max_total_usd=100
max_trade_usd=25
max_daily_loss_usd=25
max_convert_usd=50
expires=2026-12-31
I accept that I can lose all of it
"""


# ---------------------------------------------------------------- the alpha gate

def test_the_alpha_maxima_are_in_code():
    assert (LG.ALPHA_MAX_TOTAL_USD, LG.ALPHA_MAX_TRADE_USD, LG.ALPHA_MAX_DAILY_LOSS_USD) == (100, 25, 25)
    assert LG.ALPHA_MAX_TOTAL_USD <= LG.TEST_MAX_TOTAL_USD and LG.ALPHA_MAX_TRADE_USD <= LG.TEST_MAX_TRADE_USD
    assert LG.hard_view("alpha")["max_trade_usd"] == 25 and LG.hard_view("alpha")["small_max_trade_usd"] == 25
    assert LG.hard_view(None)["max_total_usd"] == 500 and LG.hard_view(None)["mode"] is None


def test_the_alpha_ack_reads_and_refuses_above_its_maxima_and_without_the_line(tmp_path):
    p = tmp_path / "ack"
    p.write_text(ALPHA)
    a = LG.read_ack(p, TODAY)
    assert a.problems == () and a.mode == "alpha" and a.books == (BOOK,)
    assert (a.cap("total"), a.cap("trade"), a.cap("daily_loss"), a.cap("convert")) == (100, 25, 25, 50)
    for line, why in [("max_total_usd=101", "hard maximum 100"), ("max_trade_usd=26", "hard maximum 25"),
                      ("max_daily_loss_usd=30", "hard maximum 25"), ("max_convert_usd=101", "hard maximum 100"),
                      ("book_usd=150", "hard maximum 100")]:
        key = line.split("=")[0]
        p.write_text("\n".join(x for x in ALPHA.splitlines() if not x.startswith(key + "=")) + "\n" + line + "\n")
        assert any(why in w for w in LG.read_ack(p, TODAY).problems), line
    p.write_text(ALPHA.replace("I accept that I can lose all of it\n", ""))
    assert any("lacks the line" in w for w in LG.read_ack(p, TODAY).problems)
    p.write_text(ALPHA.replace("mode=alpha", "mode=live"))
    assert "mode must be test or alpha" in LG.read_ack(p, TODAY).problems[0]
    assert LG.Ack().cap("trade") == 0 and LG.Ack(mode="full", max_trade_usd=50).cap("trade") == 0


def alpha_gate(tmp_path):
    g = T.armed(tmp_path)
    (tmp_path / "ack").write_text(ALPHA)
    return g


def test_the_alpha_gate_keeps_every_other_gate(tmp_path):
    g = alpha_gate(tmp_path)
    assert g.check() == [] and g.ack.mode == "alpha"
    g.kill = lambda: True
    assert "the kill switch file is there" in g.check()
    g = alpha_gate(tmp_path)
    (tmp_path / "sim.json").write_text(json.dumps({"t": 0, "ok": True, "pubkey": W}))
    assert any("simulation is" in w for w in g.check())
    g = alpha_gate(tmp_path)
    g.env[LG.ENV_LIVE] = "0"
    assert any("PYTHIA_ONCHAIN_LIVE" in w for w in g.check())


def test_alpha_books_trade_without_the_proof_but_only_when_named():
    a = LG.Ack(mode="alpha", books=(BOOK,), mints=("SOL", "USDC"))
    assert LG.book_problems(BOOK, a, None, NOW) == []
    assert any("does not name" in w for w in LG.book_problems(BOOK, LG.Ack(mode="alpha"), None, NOW))
    assert any("no on-chain paper twin" in w for w in LG.book_problems("other", LG.Ack(mode="alpha", books=("other",)),
                                                                        None, NOW))
    t = LG.Ack(mode="test", books=(BOOK,), mints=("SOL", "USDC"))
    assert any("no proof report" in w for w in LG.book_problems(BOOK, t, None, NOW))     # test mode still needs it


def alpha_trader(tmp_path, monkeypatch, **kw):
    tr, fc = T.trader(tmp_path, monkeypatch, **kw)
    (tmp_path / "ack").write_text(ALPHA)
    assert tr.gate.check() == [] and tr.gate.ack.mode == "alpha"
    return tr, fc


def test_alpha_caps_are_the_lower_maxima_and_the_kill_switch_holds(tmp_path, monkeypatch):
    tr, fc = alpha_trader(tmp_path, monkeypatch, chain=T.FakeChain(usdc=90_000_000))
    v = T.view(tr)                                          # 90 USDC, 1 SOL, 0.00001 cbBTC: 101 USD
    assert "above the 25 USD" in tr.caps(LX.Swap("convert", "USDC", "SOL", 26_000_000), v, killed=False)
    assert "above max_total_usd" in tr.caps(LX.Swap("convert", "USDC", "SOL", 10_000_000), v, killed=False)
    assert tr.caps(LX.Swap("convert", "SOL", "USDC", 100_000_000), v, killed=False) is None
    (tmp_path / "live" / "days.json").unlink()
    tr, fc = alpha_trader(tmp_path, monkeypatch)
    v = T.view(tr)
    ok = LX.Swap("book", "USDC", "SOL", 10_000_000, book=BOOK)
    assert tr.caps(ok, v, killed=False) is None
    assert "kill switch" in tr.caps(ok, v, killed=True)
    assert "does not name" in tr.caps(LX.Swap("book", "USDC", "SOL", 10_000_000, book="other"), v, killed=False)
    (tmp_path / "live" / "days.json").unlink()
    LX.day_start_usd(v, 90.0)                               # 29 USD down today, above the 25 of the alpha mode
    assert "day's loss" in tr.caps(ok, v, killed=False)


class Chain20(T.FakeChain):
    """The fake chain for 20 USDC swaps (the book's 40 USD order in two pieces)."""

    def __call__(self, method, params):
        if method != "simulateTransaction":
            return super().__call__(method, params)
        self.sims += 1
        addrs = params[1]["accounts"]["addresses"]
        post = dict(self.acc)
        post[X.ata(W, USDC)] = T.tacc(USDC, W, 30_000_000)
        post[W] = T.G.Account(self.acc[W].lamports + self.out_raw - 40_000, X.SYSTEM, b"")
        return {"result": {"value": {"err": None, "unitsConsumed": 200_000,
                                     "accounts": [T.b64acc(post.get(k)) for k in addrs]}}}


def test_an_alpha_book_trades_without_the_proof_and_posts_its_card(tmp_path, monkeypatch):
    tr, fc = alpha_trader(tmp_path, monkeypatch, chain=Chain20(out_raw=1_998_000_000),
                          answer=T.build_answer(amount=20_000_000, out=1_998_000_000))
    posted = []
    monkeypatch.setattr(C, "post_alpha", lambda s, r, view=None, send=None: posted.append((s, r)))
    monkeypatch.setattr(SV.Service, "read_history", lambda self: None)
    svc = SV.Service(gate=tr.gate, trader=tr, load=lambda p: tr.signer, alerts=True)
    monkeypatch.setattr(SV, "_post", lambda title, text: None)
    svc.start()
    monkeypatch.setattr(LG, "proof_path", lambda: tmp_path / "no-proof.json")
    import lab.data
    monkeypatch.setattr(lab.data, "ROOT", tmp_path)
    sig = tmp_path / "signals" / "breakout_top10_live" / "latest.json"
    sig.parent.mkdir(parents=True)
    sig.write_text(json.dumps({"strategy": "breakout_top10_live", "as_of_ms": 1, "valid_until_ms": LX.now_ms() + 3_600_000,
                               "weights": {"SOL": 0.5}}))
    svc.run_books()
    assert svc.books == [{"book": BOOK, "allowed": True, "why": None}]
    planned = [o for o in LX._read_jsonl(LX.orders_path()) if o["what"] == "planned"]
    assert [o["in_raw"] for o in planned] == [20_000_000, 20_000_000]       # 40 USD as two swaps under the 25 cap
    assert len(fc.sent) >= 1 and posted and posted[0][1]["status"] == "filled" and posted[0][0].book == BOOK
    st = svc.status()
    assert st["mode"] == "alpha" and st["limits"]["max_trade_usd"] == 25 and st["hard"]["max_total_usd"] == 100
    ex = LX.read_execution()
    assert ex and ex[0]["mode"] == "alpha" and ex[0]["signal_ms"] is not None


# ---------------------------------------------------------------- the alpha cards

class S:
    def __init__(self, kind="book", src="USDC", dst="SOL", in_raw=20_000_000, book=BOOK):
        self.kind, self.src, self.dst, self.in_raw, self.book = kind, src, dst, in_raw, book


def test_alpha_cards_say_alpha_phase_and_take_their_colour_from_the_outcome():
    good = C.alpha_card(S(), {"status": "filled", "out_raw": 1_999_000_000, "in_usd": 20.0, "out_usd": 19.99,
                              "sig": A("sig")}, "de", 0.00004)
    assert good.emoji == "🟢" and "Alpha-Phase" in good.title and "USDC zu SOL" in good.title
    text = good.render("telegram", "de")
    assert "solscan.io/tx/" in text and "1.999 SOL" in text and "0.000040 SOL" in text
    assert "Alpha phase" in good.remake("en").title and good.discord
    dear = C.alpha_card(S(), {"status": "filled", "out_raw": 1, "in_usd": 20.0, "out_usd": 19.0}, "en")
    assert dear.emoji == "🟠"
    bad = C.alpha_card(S(kind="convert"), {"status": "failed", "why": "landed with an error (its fee is paid)"}, "de")
    assert bad.emoji == "🔴" and "fehlgeschlagen" in bad.title and "Umtausch" in bad.summary
    from lab.ops import notify
    assert notify.DISCORD_COLORS[good.emoji] != notify.DISCORD_COLORS[bad.emoji]


def test_alpha_cards_go_the_real_money_route_and_never_raise(monkeypatch):
    got = {}

    def send(category, cards, urgent=False, discord=None):
        got.update(category=category, cards=cards, urgent=urgent, discord=discord)
        return {"delivered": True}

    assert C.post_alpha(S(), {"status": "filled", "out_raw": 1, "in_usd": 1.0, "out_usd": 1.0}, send=send) == {"delivered": True}
    assert got["category"] == "trades" and got["urgent"] and got["discord"] == "trades"
    assert C.post_alpha(S(), {"status": "filled"}, send=lambda *a, **k: 1 / 0) is None


# ---------------------------------------------------------------- the history parser, recorded transactions

TIP = sorted(X.HELIUS_TIP_ACCOUNTS)[0]
OWNER = A("the owner's exchange")

# A deposit as getTransaction (jsonParsed) returns it: the owner's exchange pays the fee and sends 0.5 SOL.
DEPOSIT = {
    "slot": 371_000_001, "blockTime": 1_792_700_000,
    "transaction": {"signatures": [A("dep sig")], "message": {
        "accountKeys": [{"pubkey": OWNER, "signer": True, "writable": True, "source": "transaction"},
                        {"pubkey": W, "signer": False, "writable": True, "source": "transaction"},
                        {"pubkey": X.SYSTEM, "signer": False, "writable": False, "source": "transaction"}],
        "instructions": [{"program": "system", "programId": X.SYSTEM, "parsed": {
            "type": "transfer", "info": {"source": OWNER, "destination": W, "lamports": 500_000_000}}}]}},
    "meta": {"err": None, "fee": 5_000, "preBalances": [9_000_000_000, 0, 1], "postBalances": [8_499_995_000, 500_000_000, 1],
             "preTokenBalances": [], "postTokenBalances": [], "innerInstructions": [], "loadedAddresses": {"writable": [], "readonly": []}},
}

# A swap of ours: 20 USDC to 0.1 SOL through Jupiter with a priority fee and a Sender tip.
SWAP = {
    "slot": 371_000_050, "blockTime": 1_792_701_000,
    "transaction": {"signatures": [A("swap sig")], "message": {
        "accountKeys": [{"pubkey": W, "signer": True, "writable": True, "source": "transaction"},
                        {"pubkey": X.ata(W, USDC), "signer": False, "writable": True, "source": "transaction"},
                        {"pubkey": TIP, "signer": False, "writable": True, "source": "transaction"}],
        "instructions": [{"programId": X.COMPUTE_BUDGET, "data": "x"},
                         {"program": "system", "programId": X.SYSTEM, "parsed": {
                             "type": "transfer", "info": {"source": W, "destination": TIP, "lamports": 5_000}}}]}},
    "meta": {"err": None, "fee": 45_000, "preBalances": [500_000_000, 2_039_280, 0],
             "postBalances": [500_000_000 + 100_000_000 - 45_000 - 5_000, 2_039_280, 5_000],
             "preTokenBalances": [{"accountIndex": 1, "mint": USDC, "owner": W,
                                   "uiTokenAmount": {"amount": "50000000", "decimals": 6}}],
             "postTokenBalances": [{"accountIndex": 1, "mint": USDC, "owner": W,
                                    "uiTokenAmount": {"amount": "30000000", "decimals": 6}}],
             "innerInstructions": [], "loadedAddresses": {"writable": [A("pool")], "readonly": []}},
}

# A swap that opened our JUP account (its rent paid by us): 10 USDC to 25 JUP.
SWAP_NEW_ACCOUNT = {
    "slot": 371_000_060, "blockTime": 1_792_701_100,
    "transaction": {"signatures": [A("jup sig")], "message": {"accountKeys": [W, X.ata(W, USDC), X.ata(W, JUP)],
                                                               "instructions": []}},
    "meta": {"err": None, "fee": 25_000, "preBalances": [400_000_000, 2_039_280, 0],
             "postBalances": [400_000_000 - 25_000 - 2_039_280, 2_039_280, 2_039_280],
             "preTokenBalances": [{"accountIndex": 1, "mint": USDC, "owner": W, "uiTokenAmount": {"amount": "30000000", "decimals": 6}}],
             "postTokenBalances": [{"accountIndex": 1, "mint": USDC, "owner": W, "uiTokenAmount": {"amount": "20000000", "decimals": 6}},
                                   {"accountIndex": 2, "mint": JUP, "owner": W, "uiTokenAmount": {"amount": "25000000", "decimals": 6}}]},
}

# A swap that landed with an error: only the fee is gone, the tip transfer was rolled back.
FAILED = {
    "slot": 371_000_070, "blockTime": 1_792_702_000,
    "transaction": {"signatures": [A("fail sig")], "message": {
        "accountKeys": [{"pubkey": W, "signer": True, "writable": True}, {"pubkey": TIP, "signer": False, "writable": True}],
        "instructions": [{"program": "system", "programId": X.SYSTEM, "parsed": {
            "type": "transfer", "info": {"source": W, "destination": TIP, "lamports": 5_000}}}]}},
    "meta": {"err": {"InstructionError": [3, {"Custom": 6001}]}, "fee": 85_000,
             "preBalances": [600_000_000, 0], "postBalances": [599_915_000, 0],
             "preTokenBalances": [{"accountIndex": 2, "mint": USDC, "owner": W, "uiTokenAmount": {"amount": "30000000", "decimals": 6}}],
             "postTokenBalances": [{"accountIndex": 2, "mint": USDC, "owner": W, "uiTokenAmount": {"amount": "30000000", "decimals": 6}}]},
}


def test_history_parses_a_deposit():
    e = H.parse_tx(DEPOSIT, W)
    assert e["kind"] == "deposit" and e["ok"] and not e["ours"] and e["fee_sol"] == 0
    assert e["moves"] == [{"coin": "SOL", "mint": SOL, "amount": 0.5, "raw": 500_000_000}]
    assert e["sig"] == A("dep sig") and e["t"] == 1_792_700_000_000


def test_history_parses_a_swap_with_its_fee_split_and_price():
    e = H.parse_tx(SWAP, W)
    assert e["kind"] == "swap" and e["ours"] and (e["from"], e["to"]) == ("USDC", "SOL")
    assert e["from_amount"] == pytest.approx(20.0) and e["to_amount"] == pytest.approx(0.1)
    assert e["price"] == pytest.approx(200.0)                     # 1 SOL = 200 USDC
    assert e["fee_sol"] == pytest.approx(0.000045) and e["base_sol"] == pytest.approx(0.000005)
    assert e["priority_sol"] == pytest.approx(0.00004) and e["tip_sol"] == pytest.approx(0.000005)
    e = H.parse_tx(SWAP_NEW_ACCOUNT, W)
    assert e["kind"] == "swap" and (e["from"], e["to"]) == ("USDC", "JUP") and e["rent_sol"] == pytest.approx(0.00203928)
    assert [m["coin"] for m in e["moves"]] == ["USDC", "JUP"]      # the rent is not a SOL move


def test_history_parses_a_failed_swap_as_its_fee_only():
    e = H.parse_tx(FAILED, W)
    assert e["kind"] == "failed" and not e["ok"] and "6001" in e["err"]
    assert e["moves"] == [] and e["tip_sol"] == 0 and e["fee_sol"] == pytest.approx(0.000085)
    assert H.parse_tx(DEPOSIT, OTHER) is None and H.parse_tx(None, W) is None


def test_history_update_reads_only_what_is_new_and_retries_what_the_node_lacks(tmp_path, monkeypatch):
    monkeypatch.setattr(H, "history_path", lambda: tmp_path / "history.json")
    txs = {A("dep sig"): DEPOSIT, A("swap sig"): SWAP, A("fail sig"): None}
    asked = []

    class Rpc:
        def call(self, method, params):
            asked.append((method, params))
            if method == "getSignaturesForAddress":
                until = params[1].get("until")
                sigs = [A("fail sig"), A("swap sig"), A("dep sig")]
                return [{"signature": s} for s in (sigs[:sigs.index(until)] if until in sigs else sigs)]
            return txs.get(params[0])

    out = H.update(Rpc(), W, now_ms=NOW)
    assert [e["kind"] for e in out["entries"]] == ["swap", "deposit"] and out["pending"] == [A("fail sig")]
    txs[A("fail sig")] = FAILED
    asked.clear()
    out = H.update(Rpc(), W, now_ms=NOW)
    assert [e["kind"] for e in out["entries"]] == ["failed", "swap", "deposit"] and out["pending"] == []
    assert asked[0][1][1]["until"] == A("swap sig")
    assert [p[0] for p in asked if p[0] == "getTransaction"] == ["getTransaction"]      # only the pending one again
    assert json.loads((tmp_path / "history.json").read_text())["address"] == W


# ---------------------------------------------------------------- the value chart and the measurement

def test_value_points_every_15_minutes(tmp_path, monkeypatch):
    monkeypatch.setattr(LG, "reports_dir", lambda: tmp_path)
    v = LX.View(NOW, 1_000_000_000, {USDC: 5_000_000}, {SOL: 150.0, USDC: 1.0})
    assert SV.add_value(v, 155.0, NOW) and not SV.add_value(v, 156.0, NOW + 60_000)
    assert SV.add_value(v, 157.0, NOW + 900_000) and not SV.add_value(v, None, NOW + 2_000_000)
    pts = json.loads((tmp_path / "values.json").read_text())["points"]
    assert [p["usd"] for p in pts] == [155.0, 157.0] and pts[0]["prices"] == {"USDC": 1.0, "SOL": 150.0}


def test_every_sent_swap_is_measured(tmp_path, monkeypatch):
    tr, fc = T.trader(tmp_path, monkeypatch)
    r = tr.execute(LX.Swap("convert", "USDC", "SOL", 10_000_000, ref="c1", signal_ms=LX.now_ms() - 2_000), T.view(tr))
    assert r["status"] == "filled"
    rec = LX.read_execution()[0]
    assert rec["status"] == "filled" and rec["fee_l"] == 40_000 and rec["base_l"] == 5_000 and rec["priority_l"] == 35_000
    assert rec["signal_to_send_ms"] >= 2_000 and rec["send_to_land_ms"] is not None and rec["via"] == "rpc"
    assert rec["planned_out_raw"] == 999_000_000 and rec["out_raw"] == 999_000_000 and rec["quote_slip_bps"] == 0
    assert rec["block_ms"] == 1_792_712_000_000


# ---------------------------------------------------------------- the execution report

def row(i, land=800, fee=40_000, slip=2.0, status="filled"):
    return {"t": NOW + i, "mode": "alpha", "sig": f"s{i}", "status": status, "via": "sender+rpc",
            "signal_to_send_ms": 1_500, "plan_to_send_ms": 900, "send_to_land_ms": land, "fee_l": fee, "base_l": 5_000,
            "priority_l": fee - 5_000, "tip_l": 5_000, "sol_usd": 200.0, "planned_out_raw": 1000, "out_raw": 998,
            "quote_slip_bps": slip, "cost_bps": 5.0, "in_usd": 20.0, "out_usd": 19.99}


def test_the_execution_report_compares_with_pump_fun_and_kraken(tmp_path, monkeypatch):
    pump = {"fills": 65, "send_to_land_ms": {"n": 65, "median": 925.0, "p10": -321.2, "p90": 14317.0},
            "fee_sol": {"median": 0.001005, "p10": 0.001005, "p90": 0.001005, "n": 65},
            "slip_buy": {"n": 33, "median": 0.0206, "p10": -0.19, "p90": 0.19}}
    latest = {"summary": {"probes": [{"coin": "BTC", "onchain_oneway_bps": 1.5, "kraken_oneway_bps": 40.0},
                                     {"coin": "BONK", "onchain_oneway_bps": 7.7, "kraken_oneway_bps": 65.0}]}}
    rep = E.build([row(i) for i in range(6)], pump, latest, NOW)
    assert rep["onchain"]["swaps"] == 6 and rep["onchain"]["send_to_land_ms"]["median"] == 800
    assert rep["onchain"]["priority_sol"]["median"] == pytest.approx(0.000035)
    assert rep["onchain"]["total_cost_bps"]["median"] == pytest.approx((0.01 + 0.000045 * 200) / 20 * 1e4)
    assert rep["compare"]["faster"] == "onchain" and "pump.fun executor" in rep["compare"]["note"]
    assert rep["kraken"]["oneway_bps"]["median"] == pytest.approx(52.5) and rep["kraken"]["taker_bps"] == 40
    md = E.markdown(rep)
    assert "| send to land | 800 ms" in md and "925 ms" in md and "Kraken" in md and "\u2014" not in md
    slow = E.build([row(i, land=5_000) for i in range(6)], pump, latest, NOW)
    assert slow["compare"]["faster"] == "pumpfun"
    early = E.build([row(0)], pump, None, NOW)
    assert early["compare"]["faster"] is None and "Too early" in early["compare"]["note"]
    assert early["kraken"]["oneway_bps"]["median"] is None and "40.0 bps one way" in early["verdict"]
    import lab.report as R
    monkeypatch.setattr(R, "REPORTS", tmp_path)
    monkeypatch.setattr(LG, "data_dir", lambda: tmp_path / "live")
    (tmp_path / "live").mkdir()
    (tmp_path / "live" / "execution.jsonl").write_text("\n".join(json.dumps(row(i)) for i in range(3)) + "\nnot json\n")
    E.write(NOW)
    assert json.loads((tmp_path / "onchain" / "execution.json").read_text())["onchain"]["swaps"] == 3
    assert (tmp_path / "onchain" / "execution.md").read_text().startswith("# On-chain execution")
