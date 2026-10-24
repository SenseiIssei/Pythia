"""R2, pump.fun for a small wallet under realistic execution: the labels at the realistic entry and exit (decision
rows, early rows, the select label book with its rug window from the landing), the retrain's realistic and _ideal
tables, the wallet simulation (the live sizing with limits=wallet, the impact at another stake, slots, failed buys'
fees, ruin, the brake), the picks, and the small-wallet paper books with their fixed sizing, the daily report in EUR
and the card line. No network, no wallet.

Run from research/lab:  python -m pytest tests/test_pumpfun_smallwallet_r2.py
"""

from __future__ import annotations

import json
import math

import numpy as np
import pytest

from lab.pumpfun_rt import curve as C
from lab.pumpfun_rt import labels_r2 as L2
from lab.pumpfun_rt import pipeline as P
from lab.pumpfun_rt import realistic as R
from lab.pumpfun_rt import selfeat as SF
from lab.pumpfun_rt import sim
from lab.pumpfun_rt import sizing as Z
from lab.pumpfun_rt import smallwallet as SW
from test_pumpfun_exit_runners import Pool
from test_pumpfun_realistic import fixed_fit
from test_pumpfun_rt import BUYERS, DEV, MINT, SOL, T0, Curve, Fixed

DAY = 86_400_000
EM = "\u2014"                                                  # the em dash, never in a report


def model(**kw) -> R.Model:
    return R.Model(fixed_fit(**kw), R.LiveConfig())


def rising(eng, n=60, every=400, start=500, sol=SOL // 2, dev=2 * SOL):
    """A curve bought every `every` ms from T0 + start: its price rises all the way."""
    cv = Curve(eng)
    dev_tok = cv.buy(T0, dev, DEV, same_tx=True)
    for i in range(n):
        cv.buy(T0 + start + i * every, sol, BUYERS[i % 60])
    return cv, dev_tok


# ---------------------------------------------------------------- the labels

def test_the_columns_are_where_the_rows_and_the_retrain_look():
    assert sim.ROW_R == L2.ROW_R and all(c in sim.ROW_COLS for c in L2.ROW_R)
    from lab.pumpfun_rt import early as E
    from lab.pumpfun_rt import model as M
    assert E.ROW_R == L2.EARLY_R
    assert set(L2.REAL_ROW) <= set(M.LABELS) and set(L2.REAL_EARLY) <= set(E.LABELS)
    assert "dump60" not in L2.REAL_ROW and "mig" not in L2.REAL_ROW      # no execution in them
    assert L2.ideal_on(L2.IDEAL_UNTIL_MS - 1) and not L2.ideal_on(L2.IDEAL_UNTIL_MS) and L2.until_day() == "2026-11-07"


def test_a_decision_row_bought_later_pays_more_and_wins_less():
    eng = sim.Engine([], costs=Fixed(), decisions=True)
    eng.r2 = L2.Labels(eng, model(buy=5_000.0, sell=4_000.0))
    cv, dev_tok = rising(eng, n=30, sol=SOL // 10, dev=8 * SOL)   # slow enough to stay inside the cost limit
    cv.sell(T0 + 38_000, dev_tok, DEV)                       # the dev dumps after the old sale, before the new
    cv.buy(T0 + 400_000, SOL // 100, BUYERS[0])
    eng.advance(T0 + 800_000)
    eng.finish(T0 + 800_000)
    r = {x["off"]: x for x in eng.row_dicts()}[3]
    # the old sale landed at 31 s, before the dump; the realistic one lands at 37 s, fills at the next trade, the dump
    assert r["net30_r"] < 0 < r["net30"] and r["win30_r"] == 0.0 and r["win30"] == 1.0
    assert r["net300_r"] < r["net300"]                       # both sold after the dump: the later buy paid more
    assert r["up10_r"] == 1.0 and r["up120_r"] == 0.0       # filled at 8.1 s: higher 10 s on, under it after the dump


def test_the_fill_waits_for_the_next_trade_and_a_drawn_failure_loses_its_fee():
    eng = sim.Engine([], costs=Fixed(), decisions=True)
    lab = eng.r2 = L2.Labels(eng, model(buy=5_000.0))
    rising(eng, n=10)                                        # the last buy at T0 + 4.1 s
    eng.advance(T0 + 8_500)
    assert lab.wait.get(MINT)                                # landed at T0 + 8 s, waits for the coin's next trade
    eng.advance(T0 + 400_000)
    eng.finish(T0 + 400_000)
    assert not lab.wait                                      # nothing came within 2 s: the state as it stood
    eng = sim.Engine([], costs=Fixed(), decisions=True)
    eng.r2 = L2.Labels(eng, R.Model(fixed_fit(fail={"simulation failed": 1.0}), R.LiveConfig()))
    rising(eng, n=30)
    eng.advance(T0 + 400_000)
    eng.finish(T0 + 400_000)
    r = {x["off"]: x for x in eng.row_dicts()}[3]
    assert r["win30_r"] == 0.0 and r["net30_r"] == 0.0       # simulation failed: no fee, as live
    assert math.isnan(r["up10_r"])                           # no fill, no entry price


def test_without_r2_the_rows_have_no_realistic_labels():
    eng = sim.Engine([], costs=Fixed(), decisions=True)
    rising(eng, n=30)
    eng.advance(T0 + 400_000)
    eng.finish(T0 + 400_000)
    fr = eng.table()
    assert len(fr["t"]) and all(np.isnan(fr[c]).all() for c in L2.ROW_R)
    assert L2.realistic_rows(fr) is None


def test_the_early_rows_get_their_peaks_at_the_realistic_entry():
    eng = sim.Engine([], costs=Fixed(), early_rows=True)
    eng.r2 = L2.Labels(eng, model(buy=5_000.0))
    rising(eng, n=150, every=400)
    eng.advance(T0 + 4_000_000)
    eng.finish(T0 + 4_000_000)
    fr = eng.early.tables()["rows"]
    got = np.isfinite(fr["filled_r"])
    assert got.sum() > 0 and set(np.unique(fr["filled_r"][got])) <= {0.0, 1.0}
    assert set(np.unique(fr["peak3x_r"][got])) <= {0.0, 1.0}
    data = {"rows": fr}
    real = L2.realistic_early(data)
    assert real is not None and np.array_equal(real["rows"]["peak3x"], fr["peak3x_r"], equal_nan=True)


def test_the_select_label_book_measures_the_rug_from_the_landing():
    eng = sim.Engine([], costs=Fixed(), select=True)
    old = eng.add_pipe(SF.LabelPipe(eng, Fixed()))
    real = eng.add_pipe(L2.RealLabelPipe(eng, model(buy=5_000.0)))
    assert {s.name for s in real.strats.values()} == {"P_pool0_e0@y9real", "P_pool0_e5@y9real"}
    pool = Pool(eng)
    eng.advance(T0 + 1)
    pool.to(T0 + 3_000, 0.4)                                 # the crash comes before the realistic buy lands
    pool.trade(T0 + 6_000, True, SOL // 1000)
    for i in range(1, 70):
        pool.trade(T0 + 6_000 + i * 1_000, True, SOL // 1000)
    eng.advance(T0 + 400_000)
    a = next(r for r in old.rows if r["entry"] == 0)
    b = next(r for r in real.rows if r["entry"] == 0)
    assert a["rug"] == 1.0 and b["rug"] == 0.0               # measured from the landing, the crash is behind it
    assert b["ret"] == b["ret"] and a["ret"] == a["ret"]
    assert real.table()["rug"].tolist().count(0.0) >= 1


def test_the_retrain_trains_on_the_realistic_labels_and_keeps_the_old_twins(tmp_path, monkeypatch):
    from lab.pumpfun_rt import model as M
    from lab.pumpfun_rt import retrain as RT
    monkeypatch.setitem(M.PARAMS, "n_estimators", 20)
    rng = np.random.default_rng(3)
    n = 3_000
    table = {"t": T0 + np.arange(n) * 60_000.0, "created_ms": T0 + np.arange(n) * 60_000.0 - 3_000}
    for f in M.ALL_FEATURES:
        table[f] = rng.normal(size=n)
    for k in M.LABELS:
        table[k] = (rng.random(n) < 0.3).astype(float)
    for k, c in L2.REAL_ROW.items():
        table[c] = (table["progress"] + rng.normal(scale=0.5, size=n) > 0.5).astype(float)   # learnable
    res = RT.run(table, ideal=True, log=lambda *a: None)
    assert res["realistic"] and set(res["ideal"]) == set(L2.REAL_ROW)
    summ = RT.summary(res, T0)
    assert summ["labels"]["win30"]["auc"] > 0.7 > summ["ideal"]["win30"]["auc"]
    md = RT.report_md(summ, res["importance"])
    assert "realistic entry and exit" in md and "win30" in md and EM not in md
    monkeypatch.setattr(M, "model_dir", lambda: tmp_path / "models")
    monkeypatch.setattr(RT.rep, "REPORTS", tmp_path / "reports")
    RT.save(res, summ, {})
    assert (tmp_path / "models" / "win30.json").exists() and (tmp_path / "models" / "ideal" / "win30.json").exists()
    assert not (tmp_path / "models" / "ideal" / "dump60.json").exists()
    loaded = M.load(tmp_path / "models")                     # the books read the realistic ones only
    assert "win30" in loaded and json.loads((tmp_path / "models" / "meta.json").read_text())["realistic"]
    old = {k: v for k, v in table.items() if not k.endswith("_r")}
    res = RT.run(old, ideal=True, log=lambda *a: None)       # rows from before R2: the old labels, no twins
    assert not res["realistic"] and res["ideal"] == {}
    assert "no realistic labels yet" in RT.report_md(RT.summary(res, T0), res["importance"])


def test_the_retrain_runs_x14_on_the_realistic_peaks_and_keeps_the_old_twins(tmp_path, monkeypatch):
    from lab.pumpfun_rt import early as E
    from lab.pumpfun_rt import exitpol as X
    from lab.pumpfun_rt import model as M
    from lab.pumpfun_rt import retrain as RT
    from lab.pumpfun_rt import store
    from test_pumpfun_rt import synth_store
    monkeypatch.setattr(M, "MIN_TRAIN", 100)
    monkeypatch.setattr(M, "MIN_TEST", 30)
    monkeypatch.setattr(X, "MIN_STEPS", 100)
    monkeypatch.setitem(M.PARAMS, "n_estimators", 20)
    synth_store(tmp_path, hours=8)
    eng = sim.Engine([], early_rows=True)
    real = model(buy=3_000.0)
    eng.r2 = L2.Labels(eng, real)
    sim.replay(store.days(tmp_path), eng, tmp_path)
    E.save(eng.early.tables(), tmp_path / "rows", {"split_ms": None})
    monkeypatch.setattr(RT, "rows_path", lambda: tmp_path / "rows" / "latest.parquet")
    monkeypatch.setattr(M, "model_dir", lambda: tmp_path / "models")
    monkeypatch.setattr(RT.rep, "REPORTS", tmp_path / "reports")
    monkeypatch.setattr(R, "Model", lambda *a, **k: real)
    summ = RT.run_x14(T0, log=lambda *a: None)
    assert summ["realistic"]
    m = tmp_path / "models"
    assert (m / "e_peak3x.json").exists() and (m / "ideal" / "e_peak3x.json").exists()
    md = (tmp_path / "reports" / "pumpfun_rt" / "early_exit.md").read_text()
    assert "## R2: the labels" in md and "Against the old labels" in md and EM not in md


def test_the_retrain_trains_the_select_models_on_the_realistic_rows_and_the_old_twins(tmp_path, monkeypatch):
    from lab.pumpfun_rt import model as M
    from lab.pumpfun_rt import retrain as RT
    from lab.pumpfun_rt import selmodel as SM
    from lab.pumpfun_rt import store
    monkeypatch.setattr(store, "base", lambda: tmp_path)
    monkeypatch.setattr(M, "model_dir", lambda: tmp_path / "models")
    monkeypatch.setattr(RT.rep, "REPORTS", tmp_path / "reports")
    rng = np.random.default_rng(5)
    n = 900

    def table():
        t = {"t": SW.day_start("2026-10-21") + np.sort(rng.uniform(0, 3 * DAY, n)), "entry": rng.choice([0.0, 5.0], n)}
        for f in SF.ROW_COLS:
            if f not in t:
                t[f] = rng.normal(size=n)
        t["win"] = (t["pool_net_sol"] + rng.normal(size=n) > 0).astype(float)
        t["rug"] = (rng.random(n) < 0.2).astype(float)
        return t
    SM.save_rows(table(), {"labels": "realistic"})
    SM.save_rows(table(), {"labels": "ideal"}, SM.rows_path(L2.IDEAL))
    summ = RT.run_y9(SW.day_start("2026-10-24"), log=lambda *a: None)
    assert summ["labels"] == "realistic" and set(summ["ideal"]) >= {"win0", "win5"}
    m = tmp_path / "models"
    assert (m / "sel_win0.json").exists() and (m / "ideal" / "sel_win0.json").exists()
    md = (tmp_path / "reports" / "pumpfun_rt" / "select.md").read_text()
    assert "realistic entry and exit" in md and "old labels' twins" in md
    assert RT.run_y9(L2.IDEAL_UNTIL_MS, dry=True, log=lambda *a: None).get("ideal") is None   # two weeks, then off


# ---------------------------------------------------------------- the wallet

def test_the_vector_stake_is_the_live_sizing_with_limits_wallet():
    rng = np.random.default_rng(1)
    for _ in range(400):
        bal, held = rng.uniform(0, 3), rng.choice([0.0, rng.uniform(0, 1)])
        peak = rng.uniform(0, 2)
        pnl = peak - rng.uniform(0, 1.5)
        share, brake = rng.choice(SW.SHARES), bool(rng.integers(0, 2))
        room = max(0.0, bal - R.RESERVE_SOL) / (1 + C.SLIP_TOL)
        want, _ = Z.sized(balance_sol=bal, open_cost_sol=held, peak_pnl_sol=peak, pnl_sol=pnl, live_trades=0,
                          live_mean=None, ceiling_sol=math.inf, share=share, wallet=True, room_sol=room, brake=brake,
                          floor_sol=SW.FLOOR_SOL)
        got = SW.stake_vec(np.array([bal + held]), np.array([bal]), np.array([peak]), np.array([pnl]),
                           np.array([share]), np.array([brake]))[0]
        assert got == pytest.approx(want), (bal, held, peak, pnl, share, brake)


def test_a_bigger_stake_moves_the_price_against_itself():
    p = SW.scaled(0.1, 0.1, 0.12, 85.0, 90.0)
    assert float(p) == pytest.approx(0.12)
    big = SW.scaled(1.0, 0.1, 0.12, 85.0, 90.0)
    assert 1.0 < float(big) / 0.12 < 10 and float(big) < 1.2 * 0.995
    assert float(SW.scaled(0.5, 0.1, 0.12, 0.0, 0.0)) == pytest.approx(0.6)   # no reserves known: linear


def day(entries):
    es = [{"signal_ms": SW.day_start("2026-10-22") + e[0], "exit_ms": SW.day_start("2026-10-22") + e[1],
           "failed": e[2], "cost": 0.1, "proceeds": e[3], "fees": e[4], "q_in": 1e9, "q_out": 1e9, "pnl": 0.0}
          for e in entries]
    return SW.day_arrays(es, "2026-10-22")


def test_the_wallet_follows_the_sizing_the_slots_and_the_fees():
    d = day([(1_000, 60_000, False, 0.15, 0.0004),         # +50 % before fees
             (2_000, 30_000, False, 0.05, 0.0004),          # overlaps the first: only with two slots
             (100_000, 100_000, True, 0.0, 0.0002)])        # a failed buy: its fee
    draws = np.zeros((3, 1), dtype=int)
    one = SW.simulate([d], draws, 1, [0.5], [False], [1.0])
    stake = 0.5                                              # 50 % of 1.0 SOL
    assert one["end"][0] == pytest.approx(1.0 + stake * 0.5 - 0.0004 - 0.0002)
    assert one["trades"][0] == 1
    two = SW.simulate([d], draws, 2, [0.5], [False], [1.0])
    s2 = math.floor((0.5 - R.RESERVE_SOL) / (1 + C.SLIP_TOL) * 100) / 100   # the second stake: what is left
    assert two["trades"][0] == 2
    assert two["end"][0] == pytest.approx(1.0 + stake * 0.5 - 0.0004 + s2 * -0.5 - 0.0004 - 0.0002)


def test_a_wallet_that_cannot_pay_a_trade_is_ruined_and_the_brake_halves_the_stake():
    d = day([(1_000 + i * 70_000, 61_000 + i * 70_000, False, 0.01, 0.0004) for i in range(10)])   # -90 % each
    draws = np.zeros((1, 2), dtype=int)
    sim_ = SW.simulate([d], draws, 1, [1.0, 0.25, 0.25], [False, True, False], [0.55, 0.55, 0.55])
    assert sim_["ruin"][0] and sim_["lost"][0] and not sim_["won"][0]
    assert sim_["end"][1] > sim_["end"][2]                  # the brake cuts the stake after the fall
    out = SW.outcome(sim_, 0, 0.55, 100 / SW.EUR_PER_SOL)
    assert out["p_ruin"] == 1.0 and out["p_target"] == 0.0 and not math.isfinite(out["days_target"])
    win = day([(1_000, 2_000, False, 0.3, 0.0004)])         # x3 at once: 2x reached on day one
    w = SW.simulate([win], np.zeros((1, 1), dtype=int), 1, [1.0], [False], [0.55])
    o = SW.outcome(w, 0, 0.55, 100 / SW.EUR_PER_SOL)
    assert w["won"][0] and o["days_target"] == 1.0 and o["p_double"] == 1.0


def test_the_pool_caps_the_stake_at_two_percent_of_its_sol():
    es = [{"signal_ms": SW.day_start("2026-10-22") + 1_000, "exit_ms": SW.day_start("2026-10-22") + 2_000,
           "failed": False, "cost": 0.1, "proceeds": 0.2, "fees": 0.0, "q_in": 10.0, "q_out": 10.0, "pnl": 0.0}]
    d = SW.day_arrays(es, "2026-10-22")
    s = SW.simulate([d], np.zeros((1, 1), dtype=int), 1, [1.0], [False], [5.0])
    assert s["end"][0] == pytest.approx(5.0 + float(SW.scaled(0.2, 0.1, 0.2, 10.0, 10.0)) - 0.2)


def test_the_picks_are_distinct_and_the_out_of_sample_days_need_every_model():
    def r(strategy, median, p2, ruin, share=0.25):
        return {"strategy": strategy, "share": share, "max_open": 1, "brake": True, "start": 0.55, "median": median,
                "p_double": p2, "p_ruin": ruin}
    rows = [r("A", 0.9, 0.5, 0.2), r("B", 0.7, 0.4, 0.05), r("C", 0.5, 0.1, 0.0), r("D", 0.6, 0.45, 0.1)]
    pk = SW.picks(rows)
    assert pk["a"]["strategy"] == "A" and pk["b"]["strategy"] == "D" and pk["c"]["strategy"] == "B"
    assert SW.book_name(pk["a"]) == "A_sw25o1b"
    trained = {"2026-10-21": ["win0", "win5t"], "2026-10-22": ["win0", "win5t", "et_alive5m"],
               "2026-10-23": ["win0", "win5t", "et_alive5m"]}
    days = ["2026-10-20", "2026-10-21", "2026-10-22", "2026-10-23", "2026-10-24"]
    assert SW.oos_days(days, trained) == ["2026-10-22", "2026-10-23"]


def test_the_expectation_counts_failed_buys_and_bands_by_day():
    es = [{"signal_ms": SW.day_start("2026-10-22") + 1, "pnl": 0.01, "failed": False, "cost": 0.1},
          {"signal_ms": SW.day_start("2026-10-23") + 1, "pnl": -0.0002, "failed": True, "cost": 0.0}]
    e = SW.expectation(es, ["2026-10-22", "2026-10-23"])
    assert e["n"] == 2 and e["trades"] == 1 and e["mean_sol"] == pytest.approx(0.0049)
    assert e["lo"] <= e["mean_sol"] <= e["hi"] and e["per_trade"] == pytest.approx(0.1)


# ---------------------------------------------------------------- the paper books

SMALL = (("P_pool0_sw25o2b", "P_pool0", 0.25, 2, True),)


def test_a_small_wallet_book_sizes_its_own_wallet_whatever_the_owner_set():
    eng = sim.Engine([], costs=Fixed())
    owner = R.LiveConfig(wallet=True, share=1.0, brake=False, floor_sol=0.0, max_open=1)
    m = R.Model(fixed_fit(), owner)
    wallets = {}
    book = R.small_books(eng, m, wallets, small=SMALL)[0]
    assert set(wallets) == {"P_pool0_sw25o2b"} and book.exec.model.cfg.share == 0.25
    assert book.exec.model.cfg.max_open == 2 and book.exec.model.cfg.brake and book.exec.model.cfg.wallet
    m.fit = fixed_fit(buy=7_000.0)
    book.exec.model.reload()
    assert book.exec.model.fit is m.fit and book.exec.model.cfg.share == 0.25   # the day's fit, the sizing kept
    pool = Pool(eng)
    eng.advance(T0 + 1)
    pool.trade(T0 + 8_000, True, SOL // 1000)
    eng.advance(T0 + 9_000)
    p = next(iter(book.pos.values()))
    assert p["stake_l"] == int(0.13 * SOL)                   # 25 % of 0.55 SOL, rounded down to 0.01
    assert book.strats["P_pool0_sw25o2b"].p["base"] == "P_pool0"


def test_the_shadow_runs_the_small_books_next_to_the_others(tmp_path, monkeypatch):
    from lab.pumpfun_rt import live
    monkeypatch.setattr(live, "paper_dir", lambda: tmp_path)
    from lab.pumpfun_rt import strategies as S
    sh = live.Shadow(S.DEFAULT_PICK, alerts=False, strategies=[P.BY_NAME["P_pool0"]], realistic=True,
                     real=R.Model(fixed_fit(), R.LiveConfig()), now_ms=T0, small=SMALL)
    names = {s for p in sh.engine.pipes for s in p.strats}
    assert {"P_pool0", "P_pool0_ideal", "P_pool0_sw25o2b"} <= names
    sh.save()
    st = json.loads((tmp_path / "state.json").read_text())
    assert "P_pool0_sw25o2b" in st["paper_wallets"]
    full = live.Shadow(S.DEFAULT_PICK, alerts=False, realistic=True, real=R.Model(fixed_fit(), R.LiveConfig()),
                       now_ms=T0)                            # the collector's full set: the registered picks too
    names = {s for p in full.engine.pipes for s in p.strats}
    assert {x[0] for x in R.SMALL} <= names


def test_the_picks_in_the_code_are_the_results():
    assert len(R.SMALL) in (2, 3) and len({x[0] for x in R.SMALL}) == len(R.SMALL)
    for name, base, share, max_open, brake in R.SMALL:
        assert base in P.BY_NAME and base in SW.CANDIDATES and share in SW.SHARES and max_open in SW.MAX_OPEN
        assert name == SW.book_name({"strategy": base, "share": share, "max_open": max_open, "brake": brake})


def test_the_daily_report_and_the_card_show_the_wallets_in_euro(monkeypatch):
    st = {"paper_wallets": {"P_pool0_sw25o2b": {"start_l": int(0.55 * SOL), "pnl_l": int(0.11 * SOL), "n": 4,
                                                "refills": 0}}}
    rows = R.small_status(st, 90.0, small=SMALL)
    assert rows[0]["sol"] == pytest.approx(0.66) and rows[0]["eur"] == pytest.approx(59.4) and rows[0]["trades"] == 4
    assert R.small_status({}, None, small=SMALL)[0]["sol"] == R.START_SOL
    md = "\n".join(R.small_md(rows, 90.0))
    assert "59.40" in md and "P_pool0_sw25o2b" in md and EM not in md
    from lab.pumpfun_rt import card
    from test_i18n import no_english
    en = card.daily_card({}, None, {}, None, T0, "en", rows).render("telegram", "en")
    de = card.daily_card({}, None, {}, None, T0, "de", rows).render("telegram", "de")
    assert "Small-wallet" in en and "€59.40" in en and "59,40 €" in de
    no_english(de)


def test_the_euro_rate_falls_back_to_the_owners_target_file(tmp_path, monkeypatch):
    from lab.ops import notify
    monkeypatch.setattr(notify, "sol_eur", lambda *a, **k: None)
    monkeypatch.setattr(R, "reports_dir", lambda: tmp_path)
    assert R.sol_eur() is None
    (tmp_path / "target_eur.json").write_text(json.dumps({"value_eur": 21.93, "sol": 0.24}))
    assert R.sol_eur() == pytest.approx(91.375)
    monkeypatch.setattr(notify, "sol_eur", lambda *a, **k: 160.0)
    assert R.sol_eur() == 160.0


def test_the_search_runs_end_to_end_on_a_synthetic_record(tmp_path, monkeypatch):
    from lab.pumpfun_rt import store
    from test_pumpfun_rt import synth_store
    synth_store(tmp_path, hours=4)
    monkeypatch.setattr(store, "base", lambda: tmp_path)
    monkeypatch.setattr("lab.pumpfun_rt.study.WARM_DAYS", 0)
    monkeypatch.setattr(R, "_measured", lambda: [])
    res = SW.run(tmp_path / "out", until_ms=T0 + 2 * DAY, log=lambda *a: None, paths=20)
    assert set(res["expectation"]) == set(SW.CANDIDATES) and res["oos_days"] == [] and res["rows"] == []
    assert (tmp_path / "out" / "smallwallet.md").exists() and EM not in SW.markdown(res)
    days = ["2026-10-22", "2026-10-23"]
    es = {n: [{"signal_ms": SW.day_start(d) + 5_000 * (i + 1), "exit_ms": SW.day_start(d) + 5_000 * (i + 1) + 60_000,
               "failed": False, "cost": 0.1, "proceeds": 0.11 if i % 2 else 0.095, "fees": 0.0004, "q_in": 85.0,
               "q_out": 85.0, "pnl": 0.0} for d in days for i in range(5)] for n in SW.CANDIDATES[:2]}
    rows = SW.search(es, days, paths=50, horizon=5, log=lambda *a: None)
    assert len(rows) == 2 * len(SW.SHARES) * len(SW.MAX_OPEN) * len(SW.BRAKES) * len(SW.STARTS)
    assert all(len(r["path_median"]) == 5 for r in rows)
    md = SW.markdown({"rows": rows, "expectation": {n: SW.expectation(e, days) for n, e in es.items()},
                      "oos_days": days, "picks": SW.picks(rows)})
    assert "The picks" in md and EM not in md


def test_the_measuring_books_have_no_slot_exposure_or_loss_limit(monkeypatch):
    seen = {}
    monkeypatch.setattr(sim, "replay", lambda days, eng, root=None, **kw: seen.update(eng=eng))
    monkeypatch.setattr("lab.pumpfun_rt.store.days", lambda root=None: ["2026-10-22"])
    monkeypatch.setattr("lab.pumpfun_rt.study.span_of", lambda days, root=None: (T0, T0 + DAY))
    monkeypatch.setattr("lab.pumpfun_rt.study.warm_book", lambda days, root=None: None)
    monkeypatch.setattr("lab.pumpfun_rt.wallets.warm", lambda days, root=None: None)
    monkeypatch.setattr("lab.pumpfun_rt.early.warm_snipers", lambda days, root=None: None)
    SW.replay(until_ms=SW.day_start("2026-10-23"), log=lambda *a: None, model=model())
    books = [p for p in seen["eng"].pipes if isinstance(p, SW.Rec)]
    assert len(books) == len(SW.CANDIDATES)
    for b in books:
        lim = next(iter(b.risk.values())).limits
        assert lim.max_open >= 1000 and math.isinf(lim.max_exposure_sol) and math.isinf(lim.max_daily_loss_sol)


def test_r2_cannot_trade():
    import inspect
    for mod in (L2, SW):
        src = inspect.getsource(mod).lower()
        for word in ("sendtransaction", "keypair", "private_key", "solders", "live_exec.liveexecutor"):
            assert word not in src
