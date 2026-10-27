"""limits=wallet for the on-chain wallet trader and the owner's master controls (the owner's decision 2026-10-23):
the ack key, the caps that follow the wallet's value under the mode's hard maxima and a finite daily loss cap
(review R1 2026-10-27: no ack lifts them), every other refusal kept, the book's money from the owner's
share, the pause (no book trades, the converts go on) and its card; without the key nothing changes.

No network, no key of anyone: the fake chain and addresses of test_onchain_live.

Run from research/lab:  python -m pytest tests/test_onchain_wallet_limits.py
"""

from __future__ import annotations

import json
import math

import pytest

from lab.onchain import live_exec as LX
from lab.onchain import live_gate as LG
from lab.onchain import live_service as SV
from lab.onchain import mints as M
from lab.pumpfun_rt import live_exec as PX
from test_onchain_live import ACK, TODAY, FakeChain, trader, view

BOOK = "onchain_breakout_top10_live"
MONEY = ("max_total_usd", "max_trade_usd", "max_daily_loss_usd", "max_convert_usd")
WALLET_ACK = "\n".join(x for x in ACK.splitlines() if x.split("=")[0] not in MONEY) + "\nlimits=wallet\n"


def wallet(tr, text: str = WALLET_ACK) -> None:
    (tr.gate.ack_path).write_text(text)
    assert tr.gate.check() == []
    assert tr.gate.ack.wallet == ("limits=wallet" in text)


# ---------------------------------------------------------------- the ack and the caps

def test_limits_wallet_needs_no_money_lines_and_book_usd_stays_under_the_modes_maximum(tmp_path):
    p = tmp_path / "ack"
    p.write_text(WALLET_ACK)
    a = LG.read_ack(p, TODAY)
    assert a.problems == () and a.limits == "wallet" and a.wallet and a.book_usd == 150
    assert (a.max_total_usd, a.max_trade_usd, a.max_daily_loss_usd, a.max_convert_usd) == (None, None, None, None)
    assert a.view()["limits"] == "wallet"
    p.write_text(WALLET_ACK.replace("book_usd=150", "book_usd=50").replace("mode=test", "mode=alpha"))
    a = LG.read_ack(p, TODAY)
    assert a.problems == () and a.mode == "alpha" and a.book_usd == 50
    for mode, book in (("alpha", 101), ("test", 501)):      # above the mode's total maximum: refused
        p.write_text(WALLET_ACK.replace("book_usd=150", f"book_usd={book}").replace("mode=test", f"mode={mode}"))
        assert any("above the hard maximum" in w for w in LG.read_ack(p, TODAY).problems), mode
    p.write_text(WALLET_ACK + "max_total_usd=400\nmax_trade_usd=50\nmax_daily_loss_usd=10\n")   # they lower
    a = LG.read_ack(p, TODAY)
    assert a.problems == () and (a.max_total_usd, a.max_trade_usd, a.max_daily_loss_usd) == (400, 50, 10)
    for extra in ("max_total_usd=9999\n", "max_trade_usd=101\n", "max_daily_loss_usd=101\n", "max_convert_usd=251\n"):
        p.write_text(WALLET_ACK + extra)
        assert any("above the hard maximum" in w for w in LG.read_ack(p, TODAY).problems), extra
    p.write_text(WALLET_ACK.replace("limits=wallet", "limits=moon"))
    assert any("limits must be wallet or fixed" in w for w in LG.read_ack(p, TODAY).problems)
    p.write_text(WALLET_ACK.replace("I accept that I can lose all of it\n", ""))
    assert any("lacks the line" in w for w in LG.read_ack(p, TODAY).problems)
    p.write_text(ACK)                                       # without the key: as today
    a = LG.read_ack(p, TODAY)
    assert a.limits == "fixed" and not a.wallet and a.max_total_usd == 200
    assert LG.WALLET_MAX_SWAP_SHARE == 0.25
    assert (LG.ALPHA_MAX_TOTAL_USD, LG.ALPHA_MAX_TRADE_USD, LG.ALPHA_MAX_DAILY_LOSS_USD) == (100, 25, 25)


def test_the_caps_follow_the_wallets_value_only_with_the_key_and_never_above_the_maxima():
    a = LG.Ack("alpha", limits="wallet")
    assert (a.cap("total", 60), a.cap("trade", 60), a.cap("convert", 60), a.cap("daily_loss", 60)) == (60, 15, 60, 25)
    assert (a.cap("total", 1000), a.cap("trade", 1000), a.cap("convert", 1000)) == (100, 25, 100)   # alpha maxima
    assert a.cap("daily_loss", 1000) == 25 and a.cap("trade", None) == 0.0 and a.cap("total", 0) == 0.0
    t = LG.Ack("test", limits="wallet")
    assert (t.cap("total", 1000), t.cap("trade", 1000), t.cap("convert", 1000)) == (500, 100, 250)  # test maxima
    assert t.cap("daily_loss", 1000) == LG.WALLET_MAX_DAILY_LOSS_USD == LG.ALPHA_MAX_DAILY_LOSS_USD == 25
    o = LG.Ack("test", max_total_usd=300, max_trade_usd=40, max_daily_loss_usd=10, max_convert_usd=50, limits="wallet")
    assert (o.cap("total", 1000), o.cap("trade", 1000), o.cap("convert", 1000), o.cap("daily_loss", 1000)) == \
        (300, 40, 50, 10)                                   # the ack's own lines lower
    assert (o.cap("total", 100), o.cap("trade", 100)) == (100, 25)             # and the wallet's value too
    f = LG.Ack("alpha", max_total_usd=100, max_trade_usd=25, max_daily_loss_usd=25, max_convert_usd=100)
    assert (f.cap("total", 1000), f.cap("trade", 1000), f.cap("daily_loss", 1000)) == (100, 25, 25)
    assert f.cap("trade") == 25 and LG.Ack(limits="wallet").cap("trade", 1000) == 0.0   # no valid mode: nothing


def test_no_ack_or_wallet_value_lifts_a_hard_maximum_with_limits_wallet(tmp_path):
    for mode in LG.MODES:
        hard = LG.HARD[mode]
        # an Ack made past read_ack, with values far above the maxima: cap still holds them
        acks = (LG.Ack(mode, limits="wallet"),
                LG.Ack(mode, max_total_usd=1e9, max_trade_usd=1e9, max_daily_loss_usd=1e9, max_convert_usd=1e9,
                       limits="wallet"))
        for a in acks:
            for worth in (1.0, 50.0, 1e3, 1e6, 1e12, math.inf):
                for k in ("total", "trade", "convert", "daily_loss"):
                    got = a.cap(k, worth)
                    assert math.isfinite(got) and got <= hard[k], (mode, worth, k, got)
                assert a.cap("daily_loss", worth) <= LG.ALPHA_MAX_DAILY_LOSS_USD
        p = tmp_path / "ack"
        p.write_text(WALLET_ACK.replace("mode=test", f"mode={mode}").replace("book_usd=150", "book_usd=20"))
        a = LG.read_ack(p, TODAY)
        assert a.problems == () and a.wallet and a.book_usd <= hard["total"]
        assert max(a.cap(k, 1e9) for k in ("total", "trade", "convert", "daily_loss")) <= hard["total"]
    assert LG.hard_view("alpha")["wallet_max_daily_loss_usd"] == 25


def test_with_limits_wallet_the_money_caps_follow_the_wallet_and_every_other_refusal_stays(tmp_path, monkeypatch):
    tr, fc = trader(tmp_path, monkeypatch, chain=FakeChain(usdc=400_000_000, sol=30_000_000_000))
    v = view(tr)                                            # 400 + 300 + 1 USD
    big = LX.Swap("convert", "USDC", "SOL", 150_000_000)
    assert "above the 100 USD" in tr.caps(big, v, killed=False)               # today: the fixed caps
    assert "only sales into USDC" in tr.caps(LX.Swap("convert", "USDC", "SOL", 10_000_000), v, killed=False)
    wallet(tr)
    assert "above the 100 USD" in tr.caps(big, v, killed=False)               # a quarter of 701, but TEST_MAX 100
    assert "above max_total_usd" in tr.caps(LX.Swap("convert", "USDC", "SOL", 90_000_000), v, killed=False)  # 701
    (tmp_path / "w").mkdir()
    tr, fc = trader(tmp_path / "w", monkeypatch, chain=FakeChain(usdc=200_000_000, sol=20_000_000_000))
    wallet(tr)
    v = view(tr)                                            # 200 + 200 + 1 USD: under the test mode's 500
    big = LX.Swap("convert", "USDC", "SOL", 90_000_000)
    assert tr.caps(big, v, killed=False) is None                              # 90 is under a quarter of 401
    assert "USD a swap" in tr.caps(LX.Swap("convert", "USDC", "SOL", 101_000_000), v, killed=False)
    start = LX.day_start_usd(v, v.total_usd())
    LX.LX.write_json(LX.days_path(), {str(LX.day_of(v.t)): start + 26.0})   # 26 USD down today: the 25 USD cap
    assert "the day's loss reached" in tr.caps(big, v, killed=False)
    LX.LX.write_json(LX.days_path(), {str(LX.day_of(v.t)): start + 20.0})
    assert tr.caps(big, v, killed=False) is None
    LX.write_row({"t": LX.now_ms(), "kind": "convert", "from": "USDC", "to": "SOL", "in_usd": 150.0, "status": "filled"})
    assert tr.caps(big, v, killed=False) is None                              # 150 + 90 under the 250 a day
    (tmp_path / "w" / "live" / "ledger.csv").unlink()
    LX.write_row({"t": LX.now_ms(), "kind": "convert", "from": "USDC", "to": "SOL", "in_usd": 170.0, "status": "filled"})
    assert "convert limit" in tr.caps(big, v, killed=False)                   # TEST_MAX_CONVERT_USD, not 401
    (tmp_path / "w" / "live" / "ledger.csv").unlink()
    # everything else is refused as before
    assert "kill switch" in tr.caps(big, v, killed=True)
    assert "not among" in tr.caps(LX.Swap("convert", "USDC", "JUP", 10_000_000), v, killed=False)
    assert "holds less" in tr.caps(LX.Swap("convert", "USDC", "SOL", 300_000_000), v, killed=False)
    assert "does not name" in tr.caps(LX.Swap("book", "SOL", "USDC", 100_000_000, book="other"), v, killed=False)
    tr.reconciled = {"ok": False}
    assert "does not match the chain" in tr.caps(big, v, killed=False)
    tr.reconciled = {"ok": True}
    v.prices[M.COINS["ETH"].mint] = 4_000.0
    v.tokens[M.COINS["ETH"].mint] = 2_250_000              # 0.0225 WETH: 90 USD, a quarter of the 491 is 122.75
    assert "quarter" in tr.caps(LX.Swap("convert", "USDC", "ETH", 50_000_000), v, killed=False)
    v.sol_l = 1_000_000_000                                 # 10 USD of SOL left
    assert "SOL reserve" in tr.caps(LX.Swap("convert", "SOL", "USDC", 990_000_000), v, killed=False)
    v.prices.pop(M.USDC.mint)
    assert "USD" in tr.caps(big, v, killed=False)                             # no value, no swap


def test_a_book_order_above_a_quarter_of_the_wallet_is_split(tmp_path, monkeypatch):
    tr, fc = trader(tmp_path, monkeypatch, chain=FakeChain(usdc=400_000_000, sol=30_000_000_000))
    wallet(tr, WALLET_ACK.replace("book_usd=150", "book_usd=450"))
    swaps = LX.book_swaps(BOOK, tr.gate.ack, view(tr), {"SOL": 1.0})
    assert len(swaps) == 5 and sum(s.in_raw for s in swaps) == 400_000_000    # the wallet's 400 USDC
    assert all(s.in_raw / 1e6 <= LG.TEST_MAX_TRADE_USD for s in swaps)       # a quarter of 701, at most 100
    swaps = LX.book_swaps(BOOK, tr.gate.ack, view(tr), {"SOL": 1.0}, book_usd=90.0)    # the owner's share
    assert [(s.src, s.dst, s.in_raw) for s in swaps] == [("USDC", "SOL", 90_000_000)]


# ---------------------------------------------------------------- the service: status, share, pause

def service(tmp_path, monkeypatch, ack=WALLET_ACK, **kw):
    tmp_path.mkdir(exist_ok=True)
    tr, fc = trader(tmp_path, monkeypatch, **kw)
    wallet(tr, ack)
    svc = SV.Service(gate=tr.gate, trader=tr, load=lambda p: tr.signer, alerts=False)
    svc.start()
    return svc, tr, fc


def control(tmp_path, **kw):
    p = tmp_path / "reports" / "control.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"share": None, "paused": False, "set_at": 1, **kw}))


def test_the_status_says_limits_wallet_with_the_effective_caps(tmp_path, monkeypatch):
    svc, tr, fc = service(tmp_path, monkeypatch, chain=FakeChain(usdc=400_000_000, sol=30_000_000_000))
    svc.write_status()
    st = json.loads((tmp_path / "reports" / "status.json").read_text())
    lim = st["limits"]
    assert lim["kind"] == "wallet" and lim["max_daily_loss_usd"] == 25 and st["ack"]["limits"] == "wallet"
    assert lim["max_total_usd"] == 500 and lim["max_trade_usd"] == 100      # the wallet's 701 under TEST_MAX_*
    assert st["stops"] == {"daily": False, "total": True} and st["low"] is None   # 701 above 500: only sales
    c = st["control"]
    assert (c["limits"], c["share"], c["share_source"], c["book_usd"], c["paused"]) == ("wallet", None, "ack", 150, False)
    svc2, tr2, fc2 = service(tmp_path / "small", monkeypatch, chain=FakeChain(sol=10_000_000))
    assert svc2.status()["low"]["unit"] == "SOL" and svc2.status()["low"]["have"] == 0.01


def test_without_the_key_the_status_reads_fixed(tmp_path, monkeypatch):
    svc, tr, fc = service(tmp_path, monkeypatch, ack=ACK)
    st = svc.status()
    assert st["limits"]["kind"] == "fixed" and st["limits"]["max_total_usd"] == 200 and st["low"] is None
    assert st["limits"]["max_daily_loss_usd"] == 30 and st["control"]["limits"] == "fixed"


def test_the_owners_share_sets_the_books_money_and_without_the_key_only_lowers(tmp_path, monkeypatch):
    svc, tr, fc = service(tmp_path, monkeypatch, chain=FakeChain(usdc=400_000_000, sol=30_000_000_000))
    control(tmp_path, share=0.5, share_set_at=7)
    assert svc.poll_control() == ["share"]
    m = svc.books_money()
    assert (m["share"], m["source"], m["since"]) == (0.5, "owner", 7) and m["book_usd"] == pytest.approx(350.5)
    assert svc.status()["control"]["book_usd"] == pytest.approx(350.5)
    svc, tr, fc = service(tmp_path / "fixed", monkeypatch, ack=ACK, chain=FakeChain(usdc=400_000_000, sol=30_000_000_000))
    control(tmp_path / "fixed", share=0.5)
    svc.last["control"] = -1e18
    svc.poll_control()
    m = svc.books_money()                                   # 350 is above book_usd 150: ignored, with a note
    assert m["source"] == "ack" and m["book_usd"] == 150 and "can only lower" in m["note"]
    control(tmp_path / "fixed", share=0.1)
    svc.poll_control()
    assert svc.books_money()["book_usd"] == pytest.approx(70.1)


def test_a_malformed_control_file_keeps_the_last_good_values(tmp_path, monkeypatch):
    svc, tr, fc = service(tmp_path, monkeypatch)
    control(tmp_path, paused=True, paused_at=5)
    assert svc.poll_control() == ["paused"]
    (tmp_path / "reports" / "control.json").write_text("{broken")
    assert svc.poll_control() == []
    c = svc.status()["control"]
    assert c["paused"] and c["paused_since"] == 5 and c["control_ok"] is False


def book_ready(tmp_path, monkeypatch):
    monkeypatch.setattr(LG, "proof_path", lambda: tmp_path / "proof.json")
    (tmp_path / "proof.json").write_text(json.dumps({"updated_ms": LX.now_ms(), "books": {BOOK: {"passed": True}}}))
    import lab.data
    monkeypatch.setattr(lab.data, "ROOT", tmp_path)
    sig = tmp_path / "signals" / "breakout_top10_live" / "latest.json"
    sig.parent.mkdir(parents=True)
    sig.write_text(json.dumps({"strategy": "breakout_top10_live", "as_of_ms": 1,
                               "valid_until_ms": LX.now_ms() + 3_600_000, "weights": {"SOL": 0.5}}))


def planned():
    return [o for o in LX._read_jsonl(LX.orders_path()) if o["what"] == "planned"]


def test_the_pause_stops_book_trades_and_start_resumes_them(tmp_path, monkeypatch):
    svc, tr, fc = service(tmp_path, monkeypatch)
    sent = []
    monkeypatch.setattr(PX, "post_control", lambda bot, changes, ctl, send=None: sent.append((bot, changes, ctl)))
    svc.alerts = True
    book_ready(tmp_path, monkeypatch)
    control(tmp_path, paused=True, paused_at=1_792_712_000_000)
    assert svc.poll_control() == ["paused"]
    assert sent[0][0] == "onchain" and sent[0][1] == ["paused"] and sent[0][2]["paused"]
    svc.run_books()
    assert svc.books[0]["allowed"] is False and svc.books[0]["why"].startswith("paused by the owner since")
    assert not planned() and not fc.sent
    assert svc.status()["on"] and svc.status()["control"]["paused"]          # the converts still work
    assert tr.caps(LX.Swap("convert", "USDC", "SOL", 10_000_000), view(tr), killed=False) is None
    control(tmp_path, paused=False)
    assert svc.poll_control() == ["resumed"]
    svc.run_books()
    # the wallet's 50 USDC in pieces of at most a quarter of its 61 USD
    assert svc.books[0]["allowed"] and len(planned()) == 4 and sum(int(o["in_raw"]) for o in planned()) == 50_000_000
