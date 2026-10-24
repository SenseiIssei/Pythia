"""R1, realistic paper for pump.fun: the fit from the live orders (and its fallback under 30), the seeded draws, the
fill at the first recorded trade after the landing (a spike gone by then is not captured), the pre-send skip and the
6040 on landing of a pool buy, the drawn failures, the fees with and without the tip, the live sizing on the paper
wallet, the owner's settings, the calibration line and the daily job's files, the paper books' realistic default with
their _ideal twins until 2026-11-06, and the ledger's new column. No network, no wallet.

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
    assert R.START_SOL == 0.55 and R.MIN_ORDERS == 30 and R.FIT_DAYS == 7


# ---------------------------------------------------------------- the fit

def measured(now, n_buy=40, n_sell=35, old=True):
    rows = []
    for i in range(n_buy):
        rows.append({"t": now - 1000 * i, "what": "fill", "mode": "test", "side": "buy", "lat_ms": 1000.0 * (i + 1),
                     "send_to_land_ms": -100 if i == 0 else 500.0})
    for i in range(n_sell):
        rows.append({"t": now - 1000 * i, "what": "fill", "mode": "test", "side": "sell", "lat_ms": 200.0 * (i + 1)})
    rows += [{"t": now - 5, "what": "fee", "mode": "test", "fee_l": 300_000} for _ in range(31)]
    rows += [{"t": now - 5, "what": "failed", "mode": "test", "side": "buy", "why": "not landed", "fee_l": 0}] * 3
    rows += [{"t": now - 5, "what": "failed", "mode": "test", "side": "buy", "fee_l": 1_005_000,
              "why": "failed on chain: {'InstructionError': [6, {'Custom': 6040}]}"}] * 2
    rows += [{"t": now - 5, "what": "failed", "mode": "test", "side": "buy", "fee_l": 0,
              "why": "RuntimeError: Transaction simulation failed"}]
    rows += [{"t": now - 5, "what": "failed", "mode": "test", "side": "sell", "why": "not landed", "fee_l": 0}] * 50
    if old:                                                   # older than 7 days, or not a live mode: not counted
        rows += [{"t": now - 8 * DAY, "what": "fill", "mode": "test", "side": "buy", "lat_ms": 1e6}] * 50
        rows += [{"t": now - 5, "what": "fill", "mode": "paper", "side": "buy", "lat_ms": 1e6}] * 50
    return rows


def test_the_fit_takes_the_last_seven_days_of_live_orders():
    now = T0
    f = R.fit(measured(now), now)
    assert isinstance(f.buy, R.Empirical) and len(f.buy.ms) == 40 and max(f.buy.ms) == 40_000
    assert isinstance(f.sell, R.Empirical) and len(f.sell.ms) == 35
    assert min(f.send.ms) == 0.0                              # a landing reported before the send is the send's
    assert f.fee_l == 300_000 and f.tip_l == R.TIP_L
    # failures per buy order (40 fills + 6 failures); 6040 is not drawn (the bound makes it), its live rate reported
    assert f.fail == pytest.approx({"not landed": 3 / 46, "simulation failed": 1 / 46})
    assert f.live["rate_6040"] == pytest.approx(2 / 46) and f.fail_fee["6040"] == 1_005_000
    assert f.live["source"] == {"buy": "live", "sell": "live", "send": "live", "fail": "live"}
    assert 19_000 < R.describe(f.buy)["median"] < 22_000
    assert f.tx_l() == 305_000 and f.failed_l() == 300_000 and f.failed_l("not landed") == 0


def test_under_thirty_live_orders_a_side_takes_the_fixed_fallback():
    f = R.fit(measured(T0, n_buy=10, n_sell=40, old=False), T0)
    assert isinstance(f.buy, R.Lognormal) and f.buy.median_ms == 9_800.0
    assert isinstance(f.sell, R.Empirical) and isinstance(f.send, R.Lognormal)
    assert f.fail == R.FALLBACK_FAIL and f.live["source"]["fail"] == "fallback"
    empty = R.fit([], T0)
    assert R.describe(empty.buy)["median"] == pytest.approx(9_800.0)
    assert R.describe(empty.sell)["median"] == pytest.approx(3_900.0)
    assert empty.fee_l == R.FALLBACK_FEE_L


def test_the_fit_goes_through_its_file_and_the_fallback_before_the_first(tmp_path):
    f = R.fit(measured(T0), T0)
    g = R.Fit.from_json(json.loads(json.dumps(f.to_json())))
    assert g.buy == f.buy and g.sell == f.sell and g.fail == f.fail and g.fee_l == f.fee_l and g.live == f.live
    p = tmp_path / "realistic.json"
    assert R.describe(R.load_fit(p).buy)["median"] == pytest.approx(9_800.0)
    p.write_text(json.dumps({"fit": f.to_json()}))
    assert R.load_fit(p).buy == f.buy


def test_a_draw_is_seeded_by_its_key():
    f = R.fit(measured(T0), T0)
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
