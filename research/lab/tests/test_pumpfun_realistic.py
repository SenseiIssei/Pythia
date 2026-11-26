"""R1, realistic paper for pump.fun: the fit from the newest 50 live orders per field of any age (its fallback under
50, its source, count and age per field, the live twin's window unchanged), the seeded draws, the fill at the first
recorded trade after the landing (a spike gone by then is not captured), the pre-send skip and the 6040 on landing
of a pool buy, the drawn failures, the fees with and without the tip, the live sizing on the paper wallet, the
owner's settings, the calibration line and the daily job's files, the paper books' realistic default with their
_ideal twins until 2026-11-06, the ledger's new column, and the fit window study's comparison, receive lag check and
report. No network, no wallet.

Run from research/lab:  python -m pytest tests/test_pumpfun_realistic.py
"""

from __future__ import annotations

import csv
import json
import math

import pytest

from lab.pumpfun_rt import curve as C
from lab.pumpfun_rt import live
from lab.pumpfun_rt import live_exec as LX
from lab.pumpfun_rt import pipeline as P
from lab.pumpfun_rt import realistic as R
from lab.pumpfun_rt import sim
from test_pumpfun_exit_runners import QUOTE0, Pool
from test_pumpfun_rt import MINT, SOL, T0, Fixed, key

DAY = 86_400_000


def fixed_fit(buy=5_000.0, sell=4_000.0, send=500.0, fail=None, fee=200_000, tip=5_000) -> R.Fit:
    return R.Fit(R.Empirical((buy,)), R.Empirical((sell,)), R.Empirical((send,)), fee, tip, fail or {})


def engine_with(fit_: R.Fit, name: str = "P_pool0", wallet: bool = False, cfg: R.LiveConfig | None = None,
                ideal: bool = True):
    """An engine with the old book of `name` as <name>_ideal (1 s latency) and one realistic book of it: at 0.1 SOL
    without a wallet, else on a paper wallet with the live sizing."""
    eng = sim.Engine([], costs=Fixed(), strategies=[R.ideal(P.BY_NAME[name])] if ideal else None)
    model = R.Model(fit_, cfg or R.LiveConfig())
    if wallet:
        book = R.books(eng, [P.BY_NAME[name]], model)[0]
    else:
        eng.rule_costs[name] = R.RealCosts(model=model)
        book = eng.add_pipe(R.Book(eng, [P.BY_NAME[name]], R.RealExecutor(model), name="realistic",
                                   limits=P.Limits(0.1, 4, 0.6, 1.0)))
    return eng, book


def closed(eng, name) -> dict:
    got = [t for t in eng.closed if t["rule"] == name]
    assert len(got) == 1, (name, eng.closed, eng.failed, eng.skipped)
    return got[0]


# ---------------------------------------------------------------- the live numbers

def test_the_live_executors_numbers_are_the_models():
    assert R.POOL_BUY_TOL == LX.LIVE_POOL_BUY_TOL and R.RESERVE_SOL == LX.RESERVE_SOL
    assert R.TIP_L == LX.sender_tip_lamports({}) and R.RAN_AWAY == LX.RAN_AWAY
    assert R.RAN_AWAY_LANDING == LX.RAN_AWAY_LANDING
    assert R.START_SOL == 0.55 and R.MIN_ORDERS == 30 and R.FIT_N == 50


# ---------------------------------------------------------------- the fit

def measured(now, n_buy=40, n_sell=35, old=True, n_fee=51):
    rows = []
    for i in range(n_buy):
        rows.append({"t": now - 1000 * i, "what": "fill", "mode": "test", "side": "buy", "lat_ms": 1000.0 * (i + 1),
                     "send_to_land_ms": -100 if i == 0 else 500.0})
    for i in range(n_sell):
        rows.append({"t": now - 1000 * i, "what": "fill", "mode": "test", "side": "sell", "lat_ms": 200.0 * (i + 1)})
    rows += [{"t": now - 5, "what": "fee", "mode": "test", "fee_l": 300_000} for _ in range(n_fee)]
    rows += [{"t": now - 5, "what": "failed", "mode": "test", "side": "buy", "why": "not landed", "fee_l": 0}] * 3
    rows += [{"t": now - 5, "what": "failed", "mode": "test", "side": "buy", "fee_l": 1_005_000,
              "why": "failed on chain: {'InstructionError': [6, {'Custom': 6040}]}"}] * 2
    rows += [{"t": now - 5, "what": "failed", "mode": "test", "side": "buy", "fee_l": 0,
              "why": "RuntimeError: Transaction simulation failed"}]
    rows += [{"t": now - 5, "what": "failed", "mode": "test", "side": "sell", "why": "not landed", "fee_l": 0}] * 50
    if old:                                                   # after the fit's time, or not a live mode: not counted
        rows += [{"t": now + DAY, "what": "fill", "mode": "test", "side": "buy", "lat_ms": 1e6}] * 50
        rows += [{"t": now - 5, "what": "fill", "mode": "paper", "side": "buy", "lat_ms": 1e6}] * 50
    return rows


def test_the_fit_takes_the_newest_fifty_live_orders_per_field_of_any_age():
    now = T0
    f = R.fit(measured(now, n_buy=60, n_sell=55), now)
    assert isinstance(f.buy, R.Empirical) and len(f.buy.ms) == 50 and max(f.buy.ms) == 50_000   # the newest 50
    assert isinstance(f.sell, R.Empirical) and len(f.sell.ms) == 50
    assert min(f.send.ms) == 0.0                              # a landing reported before the send is the send's
    assert f.tip_l == R.TIP_L
    # failures over the newest 50 buy orders (the 6 failures and the 44 newest fills); 6040 is not drawn
    assert f.fail == pytest.approx({"not landed": 3 / 50, "simulation failed": 1 / 50})
    assert f.live["rate_6040"] == pytest.approx(2 / 50) and f.fail_fee["6040"] == 1_005_000
    assert f.live["source"] == {"buy": "live", "sell": "live", "send": "live", "fail": "live", "fee": "live"}
    assert f.fee_l == 300_000
    assert f.tx_l() == 305_000 and f.failed_l() == 300_000 and f.failed_l("not landed") == 0


def test_old_live_orders_count_when_no_newer_ones_exist_and_the_newest_win():
    now = T0 + 30 * DAY
    old = measured(T0, n_buy=50, n_sell=50, old=False)        # 30 days before the fit: a 7-day window held none
    f = R.fit(old, now)
    assert f.live["fields"]["buy"] == {"source": "live", "n": 50, "newest_ms": T0}
    assert isinstance(f.buy, R.Empirical) and R.describe(f.buy)["median"] == pytest.approx(25_500.0)
    newer = [{"t": now - 1000 * i, "what": "fill", "mode": "full", "side": "buy", "lat_ms": 1500.0}
             for i in range(50)]
    g = R.fit(old + newer, now)
    assert g.buy.ms == (1500.0,) * 50 and g.live["fields"]["buy"]["newest_ms"] == now
    assert len(g.sell.ms) == 50                               # each field counts its own orders


def test_the_age_stamp_of_each_field_is_in_the_report():
    now = T0 + 30 * DAY
    f = R.fit(measured(T0, n_buy=50, n_sell=10, old=False), now)
    assert R.field_stamp(f.live["fields"]["buy"], now) == ("live", "50", f"{_utc(T0)} UTC, 30.0 days old")
    assert R.field_stamp(f.live["fields"]["sell"], now)[:2] == ("fallback", "10")
    assert R.field_stamp(None, now) == ("fallback", "0", "none")
    d = {"updated_ms": now, "fit": f.to_json(), "calibration": {"line": "x"}, "config": {}}
    md = R.markdown(d)
    assert "newest 50 orders per field, of any age" in md
    assert f"| buy, signal to landing | 25.5 s" in md and f"| live | 50 | {_utc(T0)} UTC, 30.0 days old |" in md
    assert "| sale, decision to landing | 3.9 s" in md and "| fallback | 10 |" in md
    assert "\u2014" not in md


def test_under_fifty_live_orders_a_field_takes_the_fixed_fallback():
    f = R.fit(measured(T0, n_buy=10, n_sell=55, old=False, n_fee=31), T0)
    assert isinstance(f.buy, R.Lognormal) and f.buy.median_ms == 9_800.0
    assert isinstance(f.sell, R.Empirical) and isinstance(f.send, R.Lognormal)
    assert f.fail == R.FALLBACK_FAIL and f.live["source"]["fail"] == "fallback"   # 10 fills and 6 failures
    assert f.fee_l == R.FALLBACK_FEE_L and f.live["fields"]["fee"] == {"source": "fallback", "n": 31,
                                                                         "newest_ms": T0 - 5}
    f = R.fit(measured(T0, n_buy=49, n_sell=49, old=False), T0)
    assert isinstance(f.buy, R.Lognormal) and isinstance(f.sell, R.Lognormal)
    empty = R.fit([], T0)
    assert R.describe(empty.buy)["median"] == pytest.approx(9_800.0)
    assert R.describe(empty.sell)["median"] == pytest.approx(3_900.0)
    assert empty.fee_l == R.FALLBACK_FEE_L
    assert empty.live["fields"]["buy"] == {"source": "fallback", "n": 0, "newest_ms": None}


def test_the_live_twins_window_fit_is_unchanged():
    now = T0
    f = R.fit(measured(now), now, days=7)                     # all orders of the 7 days, at least 30 a side
    assert isinstance(f.buy, R.Empirical) and len(f.buy.ms) == 40 and max(f.buy.ms) == 40_000
    assert isinstance(f.sell, R.Empirical) and len(f.sell.ms) == 35
    assert f.fail == pytest.approx({"not landed": 3 / 46, "simulation failed": 1 / 46})
    assert R.fit(measured(now, n_buy=29, old=False), now, days=7).live["source"]["buy"] == "fallback"


def _utc(ms) -> str:
    from datetime import datetime, timezone
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M")


def test_the_fit_goes_through_its_file_and_the_fallback_before_the_first(tmp_path):
    f = R.fit(measured(T0), T0)
    g = R.Fit.from_json(json.loads(json.dumps(f.to_json())))
    assert g.buy == f.buy and g.sell == f.sell and g.fail == f.fail and g.fee_l == f.fee_l and g.live == f.live
    p = tmp_path / "realistic.json"
    assert R.describe(R.load_fit(p).buy)["median"] == pytest.approx(9_800.0)
    p.write_text(json.dumps({"fit": f.to_json()}))
    assert R.load_fit(p).buy == f.buy


def test_a_draw_is_seeded_by_its_key():
    f = R.fit(measured(T0, n_buy=50, n_sell=50), T0)
    c = R.RealCosts(model=R.Model(f, R.LiveConfig()))
    a = c.latency("P_pool0", MINT, "buy")
    assert a == c.latency("P_pool0", MINT, "buy") and a != c.latency("P_pool0", key(9), "buy")
    assert c.latency("P_pool0", MINT, "sell") in f.sell.ms or min(f.sell.ms) <= c.latency("P_pool0", MINT, "sell")
    assert c.tx_lamports() == f.tx_l()
    us = [R.u_of(("x", i)) for i in range(20_000)]
    two = R.Fit(fail={"not landed": 0.1, "simulation failed": 0.2})
    got = [two.draw_fail(u) for u in us]
    assert got.count("not landed") / len(us) == pytest.approx(0.1, abs=0.01)
    assert got.count("simulation failed") / len(us) == pytest.approx(0.2, abs=0.01)


# ---------------------------------------------------------------- fills

def test_the_buy_fills_at_the_first_trade_after_the_landing_not_at_a_spike_before_it():
    eng, book = engine_with(fixed_fit(), ideal=False)
    pool = Pool(eng)
    eng.advance(T0 + 1)
    pool.to(T0 + 1_000, 3.0)                                  # a spike, gone before the buy lands at T0 + 5 s
    pool.to(T0 + 3_000, 1.0)
    eng.advance(T0 + 5_500)
    p = next(iter(book.pos.values()))
    assert p["state"] == "pending"                            # landed, waiting for the coin's next trade
    pool.trade(T0 + 6_000, True, SOL // 100)
    assert p["state"] == "open" and p["land_ms"] == T0 + 6_000
    tokens = C.pool_buy(int(0.1 * SOL), pool.pb, pool.pq, 30)
    assert p["tokens"] == pytest.approx(tokens, rel=1e-6)     # the state after that trade, our stake's impact on it
    assert p["fees_l"] == 205_000                             # fee and tip


def test_a_pool_trade_handed_over_late_neither_fills_nor_sells_before_the_landing():
    eng, book = engine_with(fixed_fit(), ideal=False)
    pool = Pool(eng)
    eng.advance(T0 + 1)
    eng.advance(T0 + 7_000)                                   # landed at T0 + 5 s, waiting for a trade
    p = next(iter(book.pos.values()))
    assert p["state"] == "pending"
    pool.trade(T0 + 2_000, True, SOL // 100)                  # the collector's held row, timed by its old slot
    assert p["state"] == "open" and p["land_ms"] == T0 + 7_000, "filled when the row arrived, not before"
    pool.to(T0 + 3_000, 3.0)                                  # a late spike: seen now, after the landing
    eng.advance(T0 + 400_000)
    real = closed(eng, "P_pool0")
    assert real["exit_signal_ms"] >= real["land_ms"] and real["hold_s"] >= 0


def test_a_spike_sold_into_by_the_ideal_book_is_gone_when_the_realistic_sale_lands():
    eng, book = engine_with(fixed_fit())
    pool = Pool(eng)
    eng.advance(T0 + 1)
    pool.trade(T0 + 6_000, True, SOL // 1000)                 # the realistic buy fills here at about the open
    pool.to(T0 + 10_000, 1.6)                                 # +30 % reached: both books take
    pool.to(T0 + 12_000, 0.9)                                 # gone 2 s later
    pool.trade(T0 + 15_000, True, SOL // 1000)
    eng.advance(T0 + 400_000)
    ideal, real = closed(eng, "P_pool0_ideal"), closed(eng, "P_pool0")
    assert ideal["exit_why"] == real["exit_why"] == "take"
    assert ideal["ret"] > 0.3 and real["ret"] < 0
    assert real["exit_ms"] == T0 + 15_000 and real["stake_sol"] == pytest.approx(0.1)
    fees = real["proceeds_sol"] - real["stake_sol"] - real["pnl_sol"]
    assert fees == pytest.approx(2 * 205_000 / SOL)           # two landed transactions: fee and tip each


def test_a_replay_is_reproducible():
    def once():
        eng, _ = engine_with(R.fit(measured(T0), T0))
        pool = Pool(eng)
        for i in range(60):
            pool.trade(T0 + 1_000 * (i + 1), i % 3 != 0, SOL // 10 if i % 3 else 0, base=10 ** 12 if i % 3 == 0 else 0)
        eng.advance(T0 + 700_000)
        return [(t["rule"], t["land_ms"], t["exit_ms"], t["pnl_sol"]) for t in eng.closed], eng.failed
    assert once() == once()


def test_a_pool_buy_the_price_ran_away_from_before_its_send_is_a_skip_without_a_fee():
    eng, book = engine_with(fixed_fit(), name="P_pool0", wallet=True, ideal=False)
    pool = Pool(eng)
    eng.advance(T0 + 1)
    pool.to(T0 + 2_000, 2.2)                                  # at the send (T0 + 4.5 s) the price is up 120 %
    eng.advance(T0 + 4_600)
    assert not book.pos and len(eng.failed) == 1
    f = eng.failed[0]
    assert f["why"].startswith("price ran away (+") and f["pnl_sol"] == 0 and f["land_ms"] == T0 + 4_500
    assert eng.skipped[("P_pool0", R.RAN_AWAY)] == 1
    assert book.exec.wallet.pnl_l == 0


def test_a_pool_buy_under_its_bound_at_the_landing_is_6040_and_pays_the_fee_without_the_tip():
    eng, book = engine_with(fixed_fit(), name="P_pool0", wallet=True, ideal=False)
    pool = Pool(eng)
    eng.advance(T0 + 1)
    eng.advance(T0 + 5_500)                                   # checked at the send, landed at 5 s
    pool.trade(T0 + 6_000, True, QUOTE0 // 2)                 # the first trade after the landing: price x 2.25
    assert not book.pos and eng.failed[0]["why"] == R.RAN_AWAY_LANDING
    assert eng.failed[0]["pnl_sol"] == pytest.approx(-200_000 / SOL)
    assert book.exec.wallet.pnl_l == -200_000


def test_a_drawn_failure_lands_with_its_live_fee():
    f = fixed_fit(fail={"not landed": 1.0})
    eng, book = engine_with(f, ideal=False)
    Pool(eng)
    eng.advance(T0 + 6_000)
    assert eng.failed[0]["why"] == "not landed" and eng.failed[0]["pnl_sol"] == 0
    f = fixed_fit(fail={"other": 1.0})
    f.fail_fee["other"] = 123_000
    eng, book = engine_with(f, ideal=False)
    Pool(eng)
    eng.advance(T0 + 6_000)
    assert eng.failed[0]["why"] == "other" and eng.failed[0]["pnl_sol"] == pytest.approx(-123_000 / SOL)


# ---------------------------------------------------------------- the paper wallet

def test_the_paper_wallet_is_sized_as_the_live_bot():
    w = R.PaperWallet()
    lim, why = w.limits(0, R.LiveConfig())
    assert why is None and lim.stake_sol == 0.05 and lim.max_open == P.HARD_MAX_OPEN   # 10 % of 0.55, rounded down
    allin = R.LiveConfig(wallet=True, share=1.0, brake=False, floor_sol=0.0, max_open=1, ceiling_sol=math.inf)
    lim, why = w.limits(0, allin)
    assert lim.stake_sol == 0.41 and lim.max_open == 1        # what 0.54 SOL pays with the 30 % room
    assert lim.max_exposure_sol == pytest.approx(0.54) and math.isinf(lim.max_daily_loss_sol)
    w.book(-int(0.52 * SOL), -1.0)
    lim, why = w.limits(0, allin)
    assert lim.stake_sol == 0 and why.startswith("stake paused")
    lim, why = R.PaperWallet(pnl_l=-int(0.35 * SOL)).limits(0, R.LiveConfig())
    assert lim.stake_sol == 0 and "under 0.25 SOL" in why
    back = R.PaperWallet.from_json(json.loads(json.dumps(w.to_json())))
    assert back == w


def test_a_paused_paper_wallet_is_topped_up_once_nothing_is_open_and_one_that_cannot_pay_is_refused():
    eng, book = engine_with(fixed_fit(), wallet=True, ideal=False)
    w = book.exec.wallet
    w.book(-int(0.35 * SOL))                                  # 0.20 SOL: under the pause floor
    book.risk["P_pool0"].held[999] = 1                        # something still open: no top-up, a skip
    Pool(eng)
    eng.advance(T0 + 1)
    assert not book.pos and any(k[0] == "P_pool0" and k[1].startswith("stake paused") for k in eng.skipped)
    eng, book = engine_with(fixed_fit(), wallet=True, ideal=False)
    w = book.exec.wallet
    w.book(-int(0.35 * SOL))
    Pool(eng)
    eng.advance(T0 + 1)                                       # nothing open: back to 0.55 SOL, the buy goes out
    assert len(book.pos) == 1 and w.refills == 1 and w.topped_l == int(0.35 * SOL)
    assert w.pnl_l == -int(0.35 * SOL) and w.cash_l(0) == int(0.55 * SOL)
    assert not w.top_up() and w.refills == 1                  # a full wallet is not topped up again
    assert book.status()["wallet"]["refills"] == 1
    # the executor's own check, as live (the sizing keeps it from happening): 0.05 SOL cannot pay a 0.065 SOL buy
    eng, book = engine_with(fixed_fit(), wallet=True, ideal=False)
    book.exec.wallet.book(-int(0.50 * SOL))
    book.pos[7] = {"pid": 7, "rule": "P_pool0", "mint": MINT, "signal_ms": T0, "state": "pending"}
    book.risk["P_pool0"].hold(7, int(0.065 * SOL))
    book.exec.buy(P.Order(7, "buy", MINT, "pool", 10 ** 9, int(0.065 * SOL), T0, stake_l=int(0.05 * SOL)))
    assert eng.failed[0]["why"] == "refused: wallet balance too low" and eng.failed[0]["pnl_sol"] == 0
    assert not book.pos and book.exec.wallet.pnl_l == -int(0.50 * SOL)


def test_closed_trades_and_failed_fees_go_into_the_wallet_and_the_stake_follows():
    eng, book = engine_with(fixed_fit(), wallet=True)
    pool = Pool(eng)
    eng.advance(T0 + 1)
    pool.trade(T0 + 6_000, True, SOL // 1000)
    pool.to(T0 + 10_000, 1.6)
    pool.trade(T0 + 15_000, True, SOL // 1000)
    eng.advance(T0 + 400_000)
    real = closed(eng, "P_pool0")
    w = book.exec.wallet
    assert real["stake_sol"] == pytest.approx(0.05) and w.n == 1
    assert w.pnl_l == round(real["pnl_sol"] * SOL) and w.peak_l == max(0, w.pnl_l)
    assert book.status()["wallet"]["sol"] == pytest.approx(0.55 + real["pnl_sol"])


def test_the_owners_settings_are_read_from_the_live_files(tmp_path):
    assert R.LiveConfig.load(tmp_path) == R.LiveConfig()
    (tmp_path / "control.json").write_text(json.dumps({"share": 1.0, "brake": False, "floor_sol": 0.0,
                                                       "paused": True}))
    (tmp_path / "live_settings.json").write_text(json.dumps({"max_open": 1}))
    (tmp_path / "live_status.json").write_text(json.dumps({"ack": {"limits": "wallet", "stake_share": 0.5}}))
    c = R.LiveConfig.load(tmp_path)
    assert (c.wallet, c.share, c.brake, c.floor_sol, c.max_open, math.isinf(c.ceiling_sol)) == \
        (True, 1.0, False, 0.0, 1, True)
    (tmp_path / "live_status.json").write_text(json.dumps({"ack": {"mode": "test"}}))
    c = R.LiveConfig.load(tmp_path)                           # without limits=wallet the owner can only lower
    assert (c.wallet, c.share, c.brake, c.floor_sol, c.ceiling_sol) == (False, 0.1, True, None, P.HARD_STAKE_SOL)
    assert c.to_json()["ceiling_sol"] == P.HARD_STAKE_SOL
    (tmp_path / "live_settings.json").write_text(json.dumps({"max_open": "many", "max_trade_sol": 0.07}))
    c = R.LiveConfig.load(tmp_path)
    assert c.max_open == P.HARD_MAX_OPEN and c.ceiling_sol == 0.07


# ---------------------------------------------------------------- calibration and the daily job

def ledger_rows(n, d_ret, live=True, t0=T0):
    out = []
    for i in range(n):
        r = {"rule": R.TWIN, "mint": key(100 + i), "symbol": f"C{i}", "signal_ms": t0 + i * 60_000,
             "entry_price": 1.0, "exit_price": 1.1, "ret": 0.1}
        if live:
            r["mode"] = "test"
        else:
            r.update(signal_ms=t0 + i * 60_000 + 3_000, entry_price=1.02, exit_price=1.1 * (1 + d_ret),
                     ret=0.1 + d_ret)
        out.append(r)
    return out


def test_the_calibration_matches_the_same_coins_and_says_calibrated_within_5_points():
    lv = ledger_rows(12, 0) + [{"rule": "P_pool0", "mint": key(100), "signal_ms": T0, "ret": 9, "mode": "test"}]
    pp = ledger_rows(12, 0.03, live=False) + [dict(ledger_rows(1, 0, live=False)[0], mint=key(200))]
    pp.append(dict(ledger_rows(1, 0.0, live=False)[0], mint=key(101), signal_ms=T0 + 60_000 + 20 * 60_000))
    cal = R.calibrate(lv, pp, T0, T0 + DAY)
    assert cal["n"] == 12 and cal["live"] == 12 and cal["paper"] == 13
    assert cal["d_pts"] == pytest.approx(3.0) and cal["d_entry"] == pytest.approx(0.02)
    assert cal["d_exit"] == pytest.approx(0.03)
    assert R.verdict(cal, 7.0) == "calibrated" and R.verdict(cal, 6.5) == "not yet"
    far = R.calibrate(lv, ledger_rows(12, 0.08, live=False), T0, T0 + DAY)
    assert R.verdict(far, 7.0) == "not calibrated"
    few = R.calibrate(lv[:5], pp, T0, T0 + DAY)
    assert R.verdict(few, 7.0) == "not yet"
    assert "calibrated" in R.calib_line(cal, "calibrated", 7.0) and "+3.0 points" in R.calib_line(cal, "x", 7.0)


@pytest.fixture()
def files(tmp_path, monkeypatch):
    from lab import report as rep
    monkeypatch.setattr(rep, "REPORTS", tmp_path / "reports")
    monkeypatch.setattr(LX, "data_dir", lambda: tmp_path / "live")
    monkeypatch.setattr(live, "paper_dir", lambda: tmp_path / "paper")
    for d in ("reports/pumpfun_rt", "live", "paper"):
        (tmp_path / d).mkdir(parents=True)
    return tmp_path


def write_csv(p, rows):
    cols = sorted({k for r in rows for k in r})
    with p.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


def test_the_daily_job_refits_and_writes_the_calibration_line(files):
    now = T0 + 8 * DAY
    (files / "live" / "measured.jsonl").write_text("\n".join(json.dumps(r) for r in measured(now)) + "\n")
    write_csv(files / "live" / "ledger.csv", ledger_rows(12, 0, t0=now - 2 * DAY))
    write_csv(files / "paper" / "ledger.csv", ledger_rows(12, -0.02, live=False, t0=now - 2 * DAY))
    (files / "paper" / "state.json").write_text(json.dumps({"realistic_since": now - 7 * DAY - 1}))
    out = R.daily(now)
    rep = files / "reports" / "pumpfun_rt"
    d = json.loads((rep / "realistic.json").read_text())
    assert d["calibration"]["verdict"] == "calibrated" and d["calibration"]["n"] == 12
    assert R.load_fit(rep / "realistic.json").buy == R.fit(measured(now), now).buy
    md = (rep / "realistic.md").read_text()
    assert "live vs realistic paper" in md and "-2.0 points" in md and "\u2014" not in md
    R.daily(now + 60_000)
    rows = list(csv.DictReader((rep / "realistic_calib.csv").open()))
    assert len(rows) == 1 and rows[0]["verdict"] == "calibrated"   # one row a day
    (files / "paper" / "state.json").write_text(json.dumps({"realistic_since": now - DAY}))
    assert R.daily(now, write=False)["calibration"]["verdict"] == "not yet"
    assert out["config"]["share"] == 0.1


def test_the_job_is_in_the_table():
    from pathlib import Path
    text = (Path(__file__).resolve().parents[2] / "ops" / "jobs.yaml").read_text(encoding="utf-8")
    i = text.index("- name: pumpfun-rt-realistic")
    assert "command: python -m lab.pumpfun_rt.realistic" in text[i:i + 600]


LEDGER_COLS = ("rule,family,mint,name,symbol,created_ms,signal_ms,land_ms,exit_signal_ms,exit_ms,exit_why,signal_price,"
               "entry_price,exit_price,proceeds_sol,pnl_sol,ret,hold_s,prob,dev_dumped,migrated,gap,age_s,progress,"
               "lat_buy_ms,slip,stake_sol").split(",")


def big_ledger(p, now, n_other=12_000):
    """A paper ledger as the collector writes it: the twin's rows, a 10 EUR book's, an E1 book's, a tainted and a
    late row, and n_other rows of 40 other books on 300 coins (the bulk the job does not read whole)."""
    def row(rule, i, t, **kw):
        r = dict.fromkeys(LEDGER_COLS, "")
        r.update(rule=rule, family="P", mint=f"{i % 300:04d}".ljust(44, "m") + "pump", name=f"Coin {i}", symbol=f"C{i}",
                 created_ms=t - 30_000, signal_ms=t, land_ms=t + 1_500, exit_signal_ms=t + 60_000,
                 exit_ms=t + 61_000, exit_why="take", signal_price=3.1378e-08, entry_price=3.1378e-08 * 1.01,
                 exit_price=3.1378e-08 * 1.1, proceeds_sol=0.0934759, pnl_sol=0.0085340, ret=0.0853405,
                 hold_s=59.5, dev_dumped=False, migrated=False, gap=False, age_s=36.212, progress=0.0758465,
                 lat_buy_ms=1165.02, slip=-0.0145266, stake_sol=0.1)
        r.update(kw)
        return r
    t0 = now - 2 * DAY
    rows = [row(R.TWIN, i, t0 + i * 60_000 + 3_000, mint=key(100 + i)) for i in range(12)]
    rows += [row("P_pool0_10eur", i, t0 + i * 60_000, ret=0.01 * (i % 5 - 2)) for i in range(20)]
    rows += [row("P_pool0_wait@e1_b30", i, t0 + i * 60_000) for i in range(20)]
    rows.append(row("P_pool0_10eur", 7, t0, land_ms=t0 - 1, pnl_sol=-0.5))           # tainted: landed before its signal
    rows += [row(f"P_other{i % 40}", i, t0 + i * 1_000, pnl_sol=-0.001 * (i % 7)) for i in range(n_other)]
    rows.append(row("P_other3", 1, t0, exit_signal_ms=t0, land_ms=t0 + 5, pnl_sol=0.25))   # tainted: decided early
    with p.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=LEDGER_COLS)
        w.writeheader()
        w.writerows(rows)
    return rows


def test_the_ledger_is_read_in_one_pass_with_every_books_taint_and_the_read_books_whole(tmp_path, monkeypatch):
    p = tmp_path / "ledger.csv"
    big_ledger(p, T0 + 8 * DAY, n_other=2_000)
    full = R.read_csv(p)
    monkeypatch.setattr(R, "stale_keys", lambda: frozenset({R.stale_key(full[5]), R.stale_key(full[-3])}))
    rows, taint, st = R.read_ledger(p, R.daily_book)
    assert taint == R.taint_by_book(full) and set(taint) == {"P_pool0_10eur", "P_other3"}
    assert st == R.stale_by_book(full) and set(st) == {R.TWIN, "P_other38"}
    whole = [r for r in full if R.daily_book(r["rule"])]
    assert [r for r in rows if len(r) > 2] == whole and len(whole) == 12 + 21 + 20
    stubs = [r for r in rows if len(r) == 2]
    assert len(stubs) == 300 and {r["mint"] for r in stubs} | {r["mint"] for r in whole} == {r["mint"] for r in full}
    assert all(not R.daily_book(r["rule"]) for r in stubs)
    assert R.read_ledger(tmp_path / "none.csv", R.daily_book) == ([], {}, {})


def test_the_daily_job_holds_a_big_ledger_in_a_part_of_its_size_and_says_the_same(files, monkeypatch):
    """2026-11-25 and 11-26: the job was killed at its 1 GB (exit 137), the paper ledger (207 MB) read whole as dicts
    took 2.1 GB, P2's live_only copying every row once more (read whole, this fixture takes 7 times its size). The job
    now stays under the file's size and says what it said on the whole ledger."""
    import tracemalloc
    from lab.pumpfun_rt import selection_p2 as S
    from lab.pumpfun_rt import selection_p2r2 as S2
    from lab.pumpfun_rt import slippage_e1 as E
    monkeypatch.setattr(R, "sol_eur", lambda: 65.67)
    monkeypatch.setattr(S.metrics, "register", lambda *a, **k: None)
    now = T0 + 8 * DAY
    (files / "live" / "measured.jsonl").write_text("\n".join(json.dumps(r) for r in measured(now)) + "\n")
    write_csv(files / "live" / "ledger.csv", ledger_rows(12, 0, t0=now - 2 * DAY))
    (files / "paper" / "state.json").write_text(json.dumps({"realistic_since": now - 7 * DAY - 1}))
    big_ledger(files / "paper" / "ledger.csv", now)
    size = (files / "paper" / "ledger.csv").stat().st_size
    R.daily(now, write=False)                                 # once for what loads a single time (modules, files)
    tracemalloc.start()
    try:
        out = R.daily(now, write=False)
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    assert peak < size, (peak, size)
    full = R.read_csv(files / "paper" / "ledger.csv")
    assert out["calibration"]["n"] == 12 and out["calibration"] == R.calibrate(
        R.read_csv(files / "live" / "ledger.csv"), full, now - 7 * DAY, now) | {
        k: out["calibration"][k] for k in ("days", "verdict", "line")}
    assert out["tainted"] == 2 and out["selection"] == S.gate(files / "live", files / "paper", full, register=False)
    assert out["selection_r2"] == S2.gate(files / "live", files / "paper", full, register=False)
    assert out["slippage"] == E.forward(full, R.read_csv(files / "paper" / "failed.csv"))
    ten = R.ten_status({}, full, [], 65.67, out["selection"], now)
    assert out["ten"] == ten and ten[1]["tainted"] == 1 and ten[1]["trades"] == 20


# ---------------------------------------------------------------- the paper books

def test_the_paper_books_are_realistic_with_ideal_twins_until_the_date(files):
    model = R.Model(fixed_fit(), R.LiveConfig())
    sh = live.Shadow("A_all_x1", models=None, alerts=False, now_ms=T0, strategies=[P.BY_NAME["P_pool0"]],
                     realistic=True, real=model)
    names = sorted((p.name, s) for p in sh.engine.pipes for s in p.strats)
    assert names == [("paper", "P_pool0_ideal"), ("realistic", "P_pool0")]
    assert sh.engine.rule_by["P_pool0_ideal"].p["base"] == "P_pool0"
    pool = Pool(sh.engine)
    sh.tick(T0 + 1)
    pool.trade(T0 + 6_000, True, SOL // 1000)
    pool.to(T0 + 10_000, 1.6)
    pool.trade(T0 + 15_000, True, SOL // 1000)
    sh.tick(T0 + 400_000)
    sh.save()
    rows = {r["rule"]: r for r in csv.DictReader((files / "paper" / "ledger.csv").open())}
    assert float(rows["P_pool0"]["stake_sol"]) == pytest.approx(0.05)
    assert float(rows["P_pool0_ideal"]["stake_sol"]) == pytest.approx(0.1)
    st = json.loads((files / "paper" / "state.json").read_text())
    assert st["realistic_since"] == T0 and st["paper_wallets"]["P_pool0"]["n"] == 1
    later = live.Shadow("A_all_x1", models=None, alerts=False, now_ms=R.IDEAL_UNTIL_MS,
                        strategies=[P.BY_NAME["P_pool0"]], realistic=True, real=model)
    assert [p.name for p in later.engine.pipes] == ["realistic"]
    # the twin with the live tolerance is not run twice: the realistic P_pool0_wait has it
    both = live.Shadow("A_all_x1", models=None, alerts=False, now_ms=T0, realistic=True, real=model,
                       strategies=[P.BY_NAME["P_pool0_wait"], P.BY_NAME["P_pool0_wait_tol60"]])
    assert sorted(s for p in both.engine.pipes if p.name == "realistic" for s in p.strats) == ["P_pool0_wait"]


def test_the_collector_starts_realistic_and_keeps_the_wallets(files, monkeypatch):
    from lab.pumpfun_rt import model as M
    monkeypatch.setattr(M, "load", lambda: {})
    monkeypatch.setattr(R, "load_fit", lambda path=None: fixed_fit())
    (files / "paper" / "state.json").write_text(json.dumps({"pick": live.read_pick(), "totals": {"P_pool0": {"n": 3}},
                                                            "open": []}))
    sh = live.Shadow.load()
    assert sh.real is not None and "P_pool0_ideal" in sh.totals and "P_pool0" not in sh.totals
    assert any(p.name == "realistic" and "P_pool0_wait" in p.strats for p in sh.engine.pipes)
    sh.paper_wallets["P_pool0"].book(-1_000)
    since = sh.realistic_since
    sh.save()
    again = live.Shadow.load()
    assert again.paper_wallets["P_pool0"].pnl_l == -1_000 and again.realistic_since == since


def test_an_old_ledger_gets_the_stake_column_once(tmp_path):
    p = tmp_path / "ledger.csv"
    old = [c for c in live.LEDGER_COLS if c != "stake_sol"]
    write_csv(p, [{c: "1" for c in old}])
    live.append_csv(p, live.LEDGER_COLS, [{"rule": "P_pool0", "stake_sol": 0.05}])
    rows = list(csv.DictReader(p.open()))
    assert len(rows) == 2 and rows[0]["stake_sol"] == "" and rows[1]["stake_sol"] == "0.05"
    live.append_csv(p, live.LEDGER_COLS, [{"rule": "P_pool0", "stake_sol": 0.07}])
    assert list(csv.DictReader(p.open()))[2]["stake_sol"] == "0.07"


# ---------------------------------------------------------------- the fit window study

def window_run(rets, failed=0, fit_=None):
    t0 = 1_793_000_000_000                                    # inside the ladder's window
    es = [{"mint": key(i), "signal_ms": t0 + i * DAY // 4, "ret": r, "stake_sol": 0.1, "pnl_sol": r * 0.1,
           "entry_price": 1.0, "exit_why": "tp", "failed": False} for i, r in enumerate(rets)]
    es += [{"mint": key(100 + i), "signal_ms": t0 + i * 1000, "pnl_sol": -0.0002, "failed": True}
           for i in range(failed)]
    return {"days": ["2026-10-24", "2026-11-15"], "books": {b: es for b in R.WINDOW_BOOKS},
            "fit": (fit_ or R.Fit()).to_json(), "fit_ms": t0 + 20 * DAY}


def test_the_window_study_compares_the_two_fits_per_book_in_points():
    assert [t["id"] for t in R.window_trials()] == ["pumpfun:fit_window:P_pool0", "pumpfun:fit_window:P_pool0_wait",
                                                     "pumpfun:fit_window:recv_lag"]
    assert all(t["family"] == "pumpfun" and t["sharpe"] is None for t in R.window_trials())
    before, after = window_run([0.1, -0.1, 0.0, 0.2]), window_run([0.0, -0.1, 0.0, 0.1], failed=1)
    c = R.window_compare(before, after)
    assert c["P_pool0"]["fallback"]["n"] == 4 and c["P_pool0"]["new"]["n"] == 5     # a failed buy is an entry
    assert c["P_pool0"]["fallback"]["mean"] == pytest.approx(0.05)
    assert c["P_pool0"]["new"]["mean"] == pytest.approx((0.0 - 0.1 + 0.0 + 0.1 - 0.002) / 5)
    assert c["P_pool0"]["pts"] == pytest.approx(((0.0 - 0.1 + 0.0 + 0.1 - 0.002) / 5 - 0.05) * 100)
    assert c["P_pool0"]["new"]["lo"] is not None


def test_the_receive_lag_check_reads_the_ledgers_extra_time_over_the_draw():
    since = 1_793_000_000_000
    rows = [{"rule": "P_pool0", "signal_ms": since + i, "land_ms": since + i + 1500 + 300, "lat_buy_ms": 1500,
             "exit_why": "tp"} for i in range(10)]
    rows += [{"rule": "P_pool0", "signal_ms": since - DAY, "land_ms": since, "lat_buy_ms": 0},     # before the window
             {"rule": "P_cmig_model", "signal_ms": since, "land_ms": since + 99_000, "lat_buy_ms": 0}]
    live = [{"what": "fill", "side": "buy", "signal_ms": 1000, "recv_ms": 3200, "lat_ms": 2500},
            {"what": "fill", "side": "sell", "signal_ms": 1000, "recv_ms": 9000, "lat_ms": 500}]
    g = R.recv_lag(rows, live, since)
    assert g["paper"] == 10 and g["inside"] == 10 and g["verdict"] == "once"
    assert g["extra"]["median"] == pytest.approx(300) and g["live"] == 1 and g["recv"]["median"] == 2200
    early = rows + [{"rule": "P_pool0", "signal_ms": since, "land_ms": since + 500, "lat_buy_ms": 1500}]
    g = R.recv_lag(early, live, since)                        # a fill stamped before the landing: less, not more
    assert g["less"] == 1 and g["more"] == 0 and g["verdict"] == "once"
    rows.append({"rule": "P_pool0_wait", "signal_ms": since, "land_ms": since + 15_000 + 1500, "lat_buy_ms": 1500})
    g = R.recv_lag(rows, live, since)
    assert g["more"] == 1 and g["verdict"] == "check"         # 15 s more than the draw: the lag added again


def test_the_window_report_shows_both_columns_the_new_fits_stamps_and_the_lag():
    new = R.fit(measured(T0, n_buy=50, n_sell=50, old=False), T0)
    before, after = window_run([0.1, -0.1, 0.0, 0.2]), window_run([0.0, -0.1, 0.0, 0.1], fit_=new)
    after["fit_ms"] = T0 + 2 * DAY
    lag = R.recv_lag([], [], 0)
    md = R.window_markdown({"before": before, "after": after, "books": R.window_compare(before, after), "lag": lag,
                            "lag_text": ["counted once"]})
    assert "| P_pool0 | 4 | +5.0 % |" in md and "| P_pool0_wait |" in md and "| -5.0 |" in md
    assert f"| live | 50 | {_utc(T0)} UTC, 2.0 days old |" in md and "counted once" in md
    assert "\u2014" not in md
