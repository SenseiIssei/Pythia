"""limits=wallet for the pump.fun bot and the owner's master controls (the owner's decision 2026-10-23): the ack
key, the stake and the limits that follow the wallet, the old caps that no longer bind, the control file (bounds,
malformed, the override order), the pause (no buys, the exits go on) and its cards; without the key nothing changes.

Temp folders only, fake signers: no network, no real key, nothing sent.

Run from research/lab:  python -m pytest tests/test_pumpfun_wallet_limits.py
"""

from __future__ import annotations

import dataclasses
import json
import math

import pytest

from lab.pumpfun_rt import live_exec as LX
from lab.pumpfun_rt import pipeline as P
from lab.pumpfun_rt import sim
from lab.pumpfun_rt import sizing as Z
from test_pumpfun_live import ack_file, folders, make_gate  # noqa: F401 (folders: every file in tmp)
from test_pumpfun_pipeline import BUYERS, FakeBuilder, FakeSigner, OpenGate, strat
from test_pumpfun_rt import MINT, SOL, T0, Curve, Fixed

WALLET_ACK = "mode=test\nstrategy=P_pool60\nlimits=wallet\n{extra}I accept that I can lose all of it\n"


def wallet_ack(tmp_path, extra: str = "", line: bool = True):
    p = tmp_path / "ack"
    text = WALLET_ACK.format(extra=extra)
    p.write_text(text if line else text.replace(LX.ACCEPT_LINE, ""))
    return p


def wstake(balance, share=Z.SHARE, open_cost=0.0, peak=0.0, pnl=0.0, ceiling=math.inf, room=None):
    return Z.sized(balance_sol=balance, open_cost_sol=open_cost, peak_pnl_sol=peak, pnl_sol=pnl, live_trades=0,
                   live_mean=None, ceiling_sol=ceiling, share=share, wallet=True, room_sol=room)


# ---------------------------------------------------------------- the ack

def test_limits_wallet_needs_no_money_caps_and_takes_a_stake_share_up_to_half(tmp_path):
    a = LX.read_ack(wallet_ack(tmp_path))
    assert (a.mode, a.limits, a.stake_share, a.problems, a.wallet) == ("test", "wallet", None, (), True)
    assert (a.max_total_sol, a.max_daily_loss_sol, a.max_trade_sol) == (None, None, None)
    assert a.view()["limits"] == "wallet" and a.view()["stake_share"] is None
    a = LX.read_ack(wallet_ack(tmp_path, "stake_share=0.5\n"))
    assert a.stake_share == 0.5 and not a.problems
    # the old lines may stay in the file: they do not apply
    a = LX.read_ack(wallet_ack(tmp_path, "max_total_sol=2.0\nmax_trade_sol=0.25\nmax_daily_loss_sol=0.5\n"))
    assert not a.problems and a.max_total_sol is None and a.max_trade_sol is None
    for extra, words in (("stake_share=0.51\n", "at most 0.5"), ("stake_share=0\n", "above 0"),
                         ("stake_share=half\n", "must be a number")):
        assert any(words in w for w in LX.read_ack(wallet_ack(tmp_path, extra)).problems), extra
    assert any("lacks the line" in w for w in LX.read_ack(wallet_ack(tmp_path, line=False)).problems)
    assert Z.ACK_MAX_SHARE == 0.50 and Z.WALLET_MAX_SHARE == 1.00 and Z.SHARE == 0.10 and Z.MIN_STAKE_SOL == 0.05


def test_without_limits_wallet_the_ack_is_read_as_today_and_wallet_keys_are_refused(tmp_path):
    a = LX.read_ack(ack_file(tmp_path))
    assert (a.limits, a.stake_share, a.wallet, a.problems) == ("fixed", None, False, ())
    assert (a.max_total_sol, a.max_daily_loss_sol, a.max_trade_sol) == (1.0, 0.3, 0.02)
    p = tmp_path / "ack2"
    p.write_text(ack_file(tmp_path).read_text() + "stake_share=0.5\n")
    assert any("stake_share needs limits=wallet" in w for w in LX.read_ack(p).problems)
    p.write_text("mode=full\nrule=P_pool60\nmax_daily_loss_sol=0.5\nlimits=wallet\n")
    assert any("mode=test only" in w for w in LX.read_ack(p).problems)
    p.write_text(ack_file(tmp_path).read_text() + "limits=moon\n")
    assert any("limits must be wallet or fixed" in w for w in LX.read_ack(p).problems)
    p.write_text(ack_file(tmp_path).read_text() + "limits=fixed\n")
    assert LX.read_ack(p) == LX.read_ack(ack_file(tmp_path))
    # the owner's fixed numbers stay pinned
    assert (LX.TEST_MAX_TOTAL_SOL, LX.TEST_MAX_DAILY_LOSS_SOL, LX.TEST_MAX_TRADE_SOL) == (2.0, 0.5, 0.25)
    assert (Z.PROOF_CAP_SOL, Z.MAX_STAKE_SOL, Z.DAILY_LOSS_SHARE) == (0.10, 0.25, 0.25)


# ---------------------------------------------------------------- the stake

def test_the_wallet_stake_is_the_share_of_the_base_and_the_old_caps_do_not_bind():
    assert wstake(0.9) == (0.09, "10 % of 0.90 SOL (limits: wallet)")
    assert wstake(0.9, share=0.5)[0] == 0.45                          # the owner's alpha test
    assert wstake(3.0)[0] == 0.30                                     # above the proof cap and MAX_STAKE_SOL
    assert wstake(10.0, share=0.5)[0] == 5.0
    assert wstake(0.3)[0] == Z.MIN_STAKE_SOL                          # at least the minimum
    assert wstake(0.2) == (0.0, "stake paused: wallet under 0.25 SOL")  # the pause stays
    assert wstake(0.97)[0] == 0.09                                    # rounded down to 0.01
    assert wstake(1.0, share=7.0)[0] == 1.0                           # never above WALLET_MAX_SHARE
    assert wstake(1.0, share=1.0, room=(1.0 - 0.01) / 1.3)[0] == 0.76  # what the wallet can pay
    sol, why = wstake(1.0, room=0.03)
    assert sol == 0.0 and "cannot pay one trade" in why
    assert wstake(3.0, ceiling=0.2)[0] == 0.2                         # the owner's lower ceiling still rules


def test_a_drawdown_still_brakes_the_wallet_stake():
    sol, why = wstake(2.0, peak=0.4, pnl=0.0)                         # 17 %: half of 0.2
    assert sol == 0.1 and "drawdown 17 %: half" in why
    assert wstake(2.0, share=0.5, peak=0.4, pnl=0.0)[0] == 0.5        # half of 1.0
    assert wstake(2.0, share=0.5, peak=1.0, pnl=0.0)[0] == Z.MIN_STAKE_SOL   # 33 %: the minimum


def test_without_the_key_the_stake_is_unchanged_and_a_share_can_only_lower_it():
    old = dict(balance_sol=3.0, open_cost_sol=0.0, peak_pnl_sol=0.0, pnl_sol=0.0, live_trades=0, live_mean=None,
               ceiling_sol=0.25)
    assert Z.sized(**old)[0] == Z.PROOF_CAP_SOL                       # the proof cap still binds
    assert Z.sized(**old, share=0.5) == Z.sized(**old)                # higher: ignored
    assert Z.sized(**{**old, "balance_sol": 0.9}, share=0.05)[0] == 0.05
    assert Z.sized(**{**old, "balance_sol": 2.0}, share=0.05) == (0.1, "5 % of 2.00 SOL")


def test_the_share_in_force_owner_then_ack_then_default():
    assert LX.share_of(True, None, None)["share"] == Z.SHARE and LX.share_of(True, None, None)["source"] == "default"
    assert LX.share_of(True, 0.5, None) == {"share": 0.5, "source": "ack", "since": None, "ack_share": 0.5,
                                            "note": None}
    got = LX.share_of(True, 0.5, 0.75, 123)
    assert (got["share"], got["source"], got["since"]) == (0.75, "owner", 123)     # the app over the ack
    assert LX.share_of(True, None, 0.001)["share"] == LX.SHARE_MIN
    got = LX.share_of(False, 0.5, 0.05, 9)                            # without the key: the ack's share is ignored
    assert (got["share"], got["source"]) == (0.05, "owner")
    got = LX.share_of(False, None, 0.5, 9)
    assert (got["share"], got["source"]) == (Z.SHARE, "default") and "can only lower" in got["note"]


# ---------------------------------------------------------------- the limits

def test_effective_with_limits_wallet_has_no_fixed_money_caps_but_the_owners_lower_ones():
    ack = LX.Ack("test", "P_pool60", limits="wallet")
    lim, total = LX.effective(ack, {}, {})
    assert total is None and lim.max_open == P.HARD_MAX_OPEN
    assert math.isinf(lim.stake_sol) and math.isinf(lim.max_exposure_sol) and math.isinf(lim.max_daily_loss_sol)
    lim, total = LX.effective(ack, {"max_trade_sol": 0.2, "max_total_sol": 1.5, "max_open": 2}, {})
    assert (lim.stake_sol, total, lim.max_exposure_sol, lim.max_open) == (0.2, 1.5, 1.5, 2)
    lim, _ = LX.effective(ack, {}, {"PYTHIA_PUMPFUN_STAKE_SOL": "0.3", "PYTHIA_PUMPFUN_MAX_DAILY_LOSS_SOL": "2"})
    assert lim.stake_sol == 0.3 and lim.max_daily_loss_sol == 2.0     # the owner's own environment lowers
    lim, _ = LX.effective(ack, {}, {"PYTHIA_PUMPFUN_MAX_OPEN": "9"})
    assert lim.max_open == P.HARD_MAX_OPEN                            # open positions stay bounded
    full = LX.Ack("full", "P_pool60", 0.5, limits="wallet")           # never outside test mode
    assert not full.wallet and LX.effective(full, {}, {})[0] == LX.effective(LX.Ack("full", "P_pool60", 0.5), {}, {})[0]


def test_effective_without_the_key_is_todays():
    ack = LX.Ack("test", "P_pool60", 0.3, 1.0, 0.1)
    lim, total = LX.effective(ack, {}, {})
    assert (lim.stake_sol, lim.max_open, lim.max_exposure_sol, lim.max_daily_loss_sol, total) == (0.1, 5, 0.6, 0.3, 1.0)


# ---------------------------------------------------------------- the live book

def live(tmp_path, balance=0.9, extra="", clock=None):
    gate = OpenGate()
    gate.rule, gate.mode, gate.env = "X", "test", {}
    gate.ack = LX.read_ack(wallet_ack(tmp_path, extra))
    lim, total = LX.effective(gate.ack, {}, {})
    ex = LX.LiveExecutor(gate, FakeSigner(), FakeBuilder(), lim, clock=clock or (lambda: T0), start=False,
                         mode="test", max_total_sol=total, rule="X", wallet=True,
                         totals={"pnl_l": 0, "since_ms": None, "trades": 0, "total_alerted": False})
    ex.balance_l = None if balance is None else int(balance * SOL)
    eng = sim.Engine([], costs=Fixed())
    s = dataclasses.replace(strat(sl=0.99, ladder=((0.3, 1.0),), time_s=600), stake_sol=LX.NO_LIMIT)
    pipe = eng.add_pipe(P.Pipeline(eng, [s], ex, name="live", record=False))
    book = LX.LiveBook(pipe, ex, "X", alerts=False)
    pipe.on_close = book.on_close
    return eng, pipe, book, ex


def test_the_live_book_stakes_the_wallets_share_and_the_old_caps_do_not_bind(tmp_path, folders):
    for balance, extra, want in ((0.9, "", 0.09), (0.9, "stake_share=0.5\n", 0.45), (3.0, "", 0.30)):
        eng, pipe, book, ex = live(tmp_path, balance, extra)
        book.refresh_limits()
        assert ex.limits.stake_sol == want and pipe.risk["X"].limits.stake_sol == want, (balance, extra)
        assert ex.limits.max_exposure_sol == pytest.approx(balance - LX.RESERVE_SOL)
        assert ex.max_total_l is None and math.isinf(ex.limits.max_daily_loss_sol)
    eng, pipe, book, ex = live(tmp_path, 0.9, "stake_share=0.5\n")
    book.refresh_limits()
    assert ex._caps(P.Order(9, "buy", MINT, "curve", 10, int(0.45 * 1.3 * SOL), T0)) is None   # above 0.25
    ex.day_pnl_l = -int(5 * SOL)                                      # no daily loss limit beyond the wallet
    assert ex._caps(P.Order(9, "buy", MINT, "curve", 10, int(0.45 * 1.3 * SOL), T0)) is None
    assert ex._caps(P.Order(9, "buy", MINT, "curve", 10, int(0.46 * 1.3 * SOL), T0)) == "above the stake cap"
    ex.exposure[1] = int(0.45 * 1.3 * SOL)                            # the second one does not fit the base
    assert ex._caps(P.Order(9, "buy", MINT, "curve", 10, int(0.45 * 1.3 * SOL), T0)) == "max exposure"
    Curve(eng)
    del ex.exposure[1]
    eng.advance(T0 + 1)
    assert ex.pending[0]["order"].stake_l == int(0.45 * SOL)          # the pipeline's own stake is not capped
    st = book.status(None, None, None, [])
    assert st["limits"]["kind"] == "wallet" and st["limits"]["max_daily_loss_sol"] is None
    assert st["limits"]["max_total_sol"] is None and st["limits"]["max_trade_sol"] == 0.45
    assert st["stake"]["share"] == 0.5 and "limits: wallet" in st["stake"]["why"]
    assert st["control"]["limits"] == "wallet" and st["control"]["share_source"] == "ack" and st["low"] is None
    assert st["ack"]["limits"] == "wallet"
    json.dumps(st, allow_nan=False)                                   # no Infinity in the status file


def test_a_wallet_too_small_for_one_trade_is_said(tmp_path, folders):
    eng, pipe, book, ex = live(tmp_path, 0.2)
    book.refresh_limits()
    st = book.status(None, None, None, [])
    assert st["low"] == {"have": 0.2, "need": 0.25, "unit": "SOL"} and not st["on"]
    base = LX.base_status(ex.gate, [], None, int(0.1 * SOL), None)
    assert base["low"]["have"] == 0.1 and base["control"]["limits"] == "wallet"


def test_without_the_key_the_status_reads_fixed_and_has_no_low(tmp_path, folders):
    from test_pumpfun_sizing import live as fixed_live
    eng, pipe, book, ex = fixed_live(tmp_path, balance=0.2)
    book.refresh_limits()
    st = book.status(None, None, None, [])
    assert st["limits"]["kind"] == "fixed" and st["control"]["limits"] == "fixed" and st["low"] is None
    assert st["stake"] == {"sol": 0.0, "why": "stake paused: wallet under 0.25 SOL"}


def test_attach_with_limits_wallet_gives_the_pipeline_the_uncapped_stake(tmp_path, folders):
    class Rpc3:
        def balance(self, pubkey):
            return int(3.0 * SOL)

        def holdings(self, owner):
            return {}

    g = make_gate(tmp_path, ack=wallet_ack(tmp_path, "stake_share=0.5\n"))
    book = LX.attach(sim.Engine([]), g, rpc=Rpc3(), load=lambda p: FakeSigner(), alerts=False, start=False)
    assert book.exec.wallet and book.exec.limits.stake_sol == 1.5
    assert book.pipe.risk["P_pool60"].limits.stake_sol == 1.5 and math.isinf(book.pipe.strats["P_pool60"].stake_sol)
    g = make_gate(tmp_path, ack=ack_file(tmp_path, x=0.1))            # without the key: as today
    book = LX.attach(sim.Engine([]), g, rpc=Rpc3(), load=lambda p: FakeSigner(), alerts=False, start=False)
    assert not book.exec.wallet and book.exec.limits.stake_sol == 0.1
    assert book.pipe.strats["P_pool60"].stake_sol == P.HARD_STAKE_SOL


# ---------------------------------------------------------------- the control file

def test_the_control_file_is_checked_and_a_malformed_one_keeps_the_last_good_values(tmp_path):
    assert LX.parse_control({"share": 0.01}) and LX.parse_control({"share": 1.0})
    for bad in ({"share": 0.0099}, {"share": 1.01}, {"share": True}, {"share": "0.5"}, {"share": float("nan")},
                {"paused": "yes"}, {"paused": 1}, [], "x", None):
        assert LX.parse_control(bad) is None, bad
    got = LX.parse_control({"share": 0.5, "paused": True, "set_at": 5, "share_set_at": 4, "paused_at": 3})
    assert got == {"share": 0.5, "paused": True, "set_at": 5, "share_set_at": 4, "paused_at": 3}
    assert LX.parse_control({"share": None, "paused": False, "paused_at": 3})["paused_at"] is None
    now = [0.0]
    p = tmp_path / "control.json"
    c = LX.Control(p, clock=lambda: now[0])
    assert c.poll(force=True) == [] and c.share is None and not c.paused and c.ok
    p.write_text(json.dumps({"share": 0.5, "paused": False, "set_at": 10, "share_set_at": 10}))
    assert c.poll() == []                                             # not 2 s yet
    now[0] = 2.0
    assert c.poll() == ["share"] and c.share == 0.5
    now[0] = 4.0
    assert c.poll() == []                                             # unchanged: no change
    p.write_text("{not json")
    now[0] = 6.0
    assert c.poll() == [] and c.share == 0.5 and not c.ok
    p.write_text(json.dumps({"share": 3.0}))
    now[0] = 8.0
    assert c.poll() == [] and c.share == 0.5 and not c.ok
    p.write_text(json.dumps({"share": 0.5, "paused": True, "set_at": 20, "share_set_at": 10, "paused_at": 20}))
    now[0] = 10.0
    assert c.poll() == ["paused"] and c.paused and c.paused_since() == 20 and c.ok
    p.unlink()                                                        # no file: no share, no pause
    now[0] = 12.0
    assert c.poll() == ["resumed", "share"] and c.share is None and not c.paused


def write_control(**kw):
    p = LX.control_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"share": None, "paused": False, "set_at": T0, **kw}))
    return p


def test_the_owners_share_overrides_the_ack_with_limits_wallet_within_seconds(tmp_path, folders):
    eng, pipe, book, ex = live(tmp_path, 0.9, "stake_share=0.5\n")
    book.refresh_limits()
    assert ex.limits.stake_sol == 0.45
    write_control(share=1.0, share_set_at=T0)
    book.control.last = -1e18
    assert book.poll_control() == ["share"]
    assert ex.limits.stake_sol == 0.68                                # all of it the wallet can pay: one position
    st = book.status(None, None, None, [])
    assert (st["control"]["share"], st["control"]["share_source"], st["control"]["share_since"]) == (1.0, "owner", T0)
    write_control(share=0.05, share_set_at=T0)
    book.control.last = -1e18
    book.poll_control()
    assert ex.limits.stake_sol == 0.05


def test_without_the_key_the_owners_share_can_only_lower(tmp_path, folders):
    from test_pumpfun_sizing import live as fixed_live
    eng, pipe, book, ex = fixed_live(tmp_path, balance=0.9)
    book.refresh_limits()
    assert ex.limits.stake_sol == 0.09
    write_control(share=0.75, share_set_at=T0)
    book.control.last = -1e18
    book.poll_control()
    assert ex.limits.stake_sol == 0.09                                # higher: ignored, with a note
    assert "can only lower" in book.status(None, None, None, [])["control"]["note"]
    write_control(share=0.06, share_set_at=T0)
    book.control.last = -1e18
    book.poll_control()
    assert ex.limits.stake_sol == 0.05                                # 6 % of 0.9 = 0.054, rounded down


def test_the_pause_stops_new_buys_but_open_positions_keep_their_exits(tmp_path, folders):
    eng, pipe, book, ex = live(tmp_path, 0.9)
    book.refresh_limits()
    cv = Curve(eng)
    eng.advance(T0 + 1)
    assert len(pipe.pos) == 1 and ex.pending
    ex.drain()
    pipe.poll(T0 + 100)
    cv.buy(T0 + 900, int(0.09 * SOL), FakeSigner.pubkey)              # our own buy lands
    assert pipe.pos[0]["state"] == "open"
    write_control(paused=True, paused_at=T0 + 1_000)
    book.control.last = -1e18
    assert book.poll_control() == ["paused"]
    assert ex.ready() == "paused by the owner since " + LX.hhmm(T0 + 1_000)
    st = book.status(None, None, None, [])
    assert not st["on"] and st["refusing"].startswith("paused by the owner since") and st["control"]["paused"]
    o = P.Order(7, "buy", MINT, "curve", 10, int(0.09 * SOL), T0)
    pipe.pos[7] = {**pipe.pos[0], "pid": 7, "state": "pending"}
    ex.buy(o)                                                         # a new signal: refused, nothing sent
    assert 7 not in ex.pending
    pipe.pos.pop(7, None)
    cv.buy(T0 + 2_000, 15 * SOL, BUYERS[0])                           # the take-profit step
    ex.drain()
    pipe.poll(T0 + 2_100)
    assert ex.builder.built[-1][0] == "sell"                          # the exit still sells while paused
    write_control(paused=False)
    book.control.last = -1e18
    assert book.poll_control() == ["resumed"] and ex.paused_ms is None and ex.ready() is None


def test_the_pause_set_before_a_start_holds_from_the_first_signal_without_a_card(tmp_path, folders):
    write_control(paused=True, paused_at=T0)
    eng, pipe, book, ex = live(tmp_path, 0.9)
    assert ex.paused_ms == T0 and book.control.paused
    book.refresh_limits()
    Curve(eng)
    eng.advance(T0 + 1)
    assert not ex.pending


def test_a_change_posts_its_card(tmp_path, folders):
    import threading
    got, done = [], threading.Event()

    def poster(make):
        got.extend(make("de"))
        done.set()

    eng, pipe, book, ex = live(tmp_path, 0.9)
    book.alerts, book.poster = True, poster
    write_control(paused=True, paused_at=T0)
    book.control.last = -1e18
    book.poll_control()
    assert done.wait(5)
    assert got[0].title == "pump.fun bot: angehalten" and "keine neuen Käufe" in got[0].summary
    cards = LX.control_cards("onchain", ["resumed", "share"], {"share": 0.25, "share_source": "owner",
                                                                 "limits": "wallet"}, "en")
    assert [c.title for c in cards] == ["On-chain wallet: running again", "On-chain wallet: share changed"]
    assert "25 %" in cards[1].summary and "Limits: wallet" in cards[1].summary
    sent = []
    LX.post_control("pumpfun", ["share"], {"share": 0.5, "share_source": "ack", "limits": "wallet"},
                    send=lambda *a, **kw: sent.append((a, kw)))
    assert sent and sent[0][1]["discord"] == "trades" and sent[0][1]["urgent"]


def test_switching_limits_in_the_ack_needs_a_restart(tmp_path, folders):
    eng, pipe, book, ex = live(tmp_path, 0.9)
    ex.gate.ack = LX.read_ack(ack_file(tmp_path))                     # limits=wallet taken out
    ex.last_check = -1e18
    assert "restart the live service" in ex.ready()
