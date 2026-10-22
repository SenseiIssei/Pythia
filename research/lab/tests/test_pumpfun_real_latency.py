"""Y5, the pump.fun rules at the measured live latency: the latency models (the study's lognormal, the
measured buys and sales as a kernel density in log space, the 1.5 s send path), one draw per key coupled
across scenarios, the fees and the stake, the books per scenario, the entries and the positive rule, and the
replay end to end on a synthetic record. No network, no wallet.

Run from research/lab:  python -m pytest tests/test_pumpfun_real_latency.py
"""

from __future__ import annotations

import json
import math

import numpy as np
import pytest

from lab.pumpfun_rt import curve as C
from lab.pumpfun_rt import model as M
from lab.pumpfun_rt import pipeline as P
from lab.pumpfun_rt import reallat as RL
from lab.pumpfun_rt import sim
from lab.pumpfun_rt import strategies as S
from test_pumpfun_rt import BUYERS, SOL, T0, Curve, key

KEYS = [("P_cmig_model", key(30 + i % 40) + str(i), "buy") for i in range(4000)]


@pytest.fixture(autouse=True)
def small_models(monkeypatch):
    monkeypatch.setitem(M.PARAMS, "n_estimators", 30)


# ---------------------------------------------------------------- the latency models

def test_the_study_scenario_is_the_registered_fill_model_on_the_same_uniform():
    a = RL.scenarios()["A"]
    ln = RL.Lognormal(C.LAT_MEDIAN_MS, C.LAT_SIGMA, C.LAT_LO_MS, C.LAT_HI_MS)
    for k in KEYS[:200]:
        assert a.latency(*k) == pytest.approx(ln.quantile(RL.u_of(k))) == pytest.approx(C.Costs().latency(*k))


def test_silverman_on_the_logs_with_a_floor():
    logs = np.log(RL.MEASURED_BUY_MS)
    q25, q75 = np.quantile(logs, [0.25, 0.75])
    want = 0.9 * min(logs.std(ddof=1), (q75 - q25) / 1.34) * 4 ** -0.2
    assert RL.silverman(logs) == pytest.approx(want) and want > RL.BW_FLOOR
    assert RL.silverman(np.log([5000.0, 5100.0, 5200.0])) == RL.BW_FLOOR            # close points: the floor
    assert RL.silverman(np.log([5000.0])) == RL.BW_FLOOR


def test_the_measured_model_keeps_the_median_and_widens_the_tails():
    for pts in (RL.MEASURED_BUY_MS, RL.MEASURED_SELL_MS):
        m = RL.LogKDE(tuple(pts))
        xs = np.array([m.quantile(u) for u in np.linspace(0.001, 0.999, 999)])
        assert np.all(np.diff(xs) >= 0)                                             # a quantile function
        med = m.quantile(0.5)
        assert 0.75 * np.median(pts) < med < 1.25 * np.median(pts)
        assert m.quantile(0.1) < np.quantile(pts, 0.1) and m.quantile(0.9) > np.quantile(pts, 0.9)
        assert RL.CLIP_MS[0] <= xs.min() and xs.max() <= RL.CLIP_MS[1]
        for u in (0.1, 0.3, 0.5, 0.7, 0.9):                                         # cdf and quantile invert
            assert m.cdf(m.quantile(u)) == pytest.approx(u, abs=2e-3)
    assert RL.LogKDE((2000.0,), lo_ms=1000, hi_ms=2500).quantile(0.9999) == 2500     # clipped


def test_buys_and_sales_draw_from_their_own_model_legs_included():
    b = RL.scenarios()["B"]
    k = ("P_cmig_model", "m1")
    u_buy, u_sell, u_leg = RL.u_of(k + ("buy",)), RL.u_of(k + ("sell",)), RL.u_of(k + ("sell", 2))
    assert b.latency(*k, "buy") == pytest.approx(b.buy.quantile(u_buy))
    assert b.latency(*k, "sell") == pytest.approx(b.sell.quantile(u_sell))
    assert b.latency(*k, "sell", 2) == pytest.approx(b.sell.quantile(u_leg))
    buys = np.array([b.latency(*kk) for kk in KEYS])
    sells = np.array([b.latency(kk[0], kk[1], "sell") for kk in KEYS])
    assert 5_000 < np.median(buys) < 8_000 and 9_000 < np.median(sells) < 14_000
    assert np.median(sells) > np.median(buys)


def test_the_fast_path_lands_in_one_to_two_seconds():
    c = RL.scenarios()["C"]
    xs = np.array([c.latency(*k) for k in KEYS])
    assert xs.min() >= 1000 and xs.max() <= 2000 and abs(np.median(xs) - 1500) < 30
    assert 0.85 < np.mean((xs > 1000) & (xs < 2000))                               # rarely at the clip


def test_one_rank_per_key_across_scenarios():
    sc = RL.scenarios()
    a = np.array([sc["A"].latency(*k) for k in KEYS])
    for name in ("B", "C"):
        x = np.array([sc[name].latency(*k) for k in KEYS])
        order = np.argsort(a, kind="stable")
        inner = (a[order] > C.LAT_LO_MS) & (a[order] < C.LAT_HI_MS)
        assert np.all(np.diff(x[order][inner]) >= -1e-9)                            # monotone in the same uniform


def test_fees_and_the_tip():
    sc = RL.scenarios()
    for name in ("A", "B", "C"):
        assert sc[name].tx_lamports() == 1_005_000                                  # 0.001005 SOL, as measured
    assert sc["Ct"].tx_lamports() == 1_010_000
    assert RL.describe(sc["B"], n=2000)["tx_fee_sol"] == pytest.approx(0.001005)


def test_the_registered_measurements_are_the_executors_file():
    rows = [{"what": "fill", "side": "buy", "lat_ms": x, "sig": f"b{i}"} for i, x in enumerate(RL.MEASURED_BUY_MS)]
    rows += [{"what": "fill", "side": "sell", "lat_ms": x, "sig": f"s{i}"} for i, x in enumerate(RL.MEASURED_SELL_MS)]
    rows += [{"what": "fee", "sig": "b0", "fee_l": 1_005_000}, {"what": "failed", "side": "sell", "why": "x"}]
    buys, sells, fees = RL.from_measured(rows)
    assert tuple(buys) == RL.MEASURED_BUY_MS and tuple(sells) == RL.MEASURED_SELL_MS and fees == [RL.TX_FEE_SOL]
    assert np.median(buys) == pytest.approx(6616.5)


# ---------------------------------------------------------------- books and numbers

def test_every_rule_and_strategy_once_per_scenario_at_the_measured_stake():
    rules, strats, costs, judged = RL.books("E_d0_x1")
    assert len(judged) == len(S.RULES) + 1 + len(P.STRATEGIES) == 35
    assert len(rules) + len(strats) == len(costs) == len(RL.SCENARIOS) * len(judged) == S.REAL_LATENCY_TRIALS
    assert all(s.stake_sol == RL.STAKE_SOL for s in strats)
    mr = next(r for r in rules if r.name == "E_d0_x1+model@B")
    assert mr.p["model"] and sim.base_name(mr) == "E_d0_x1"                       # the study's draw key
    assert sim.base_name(next(s for s in strats if s.name == "P_cmig_model@C")) == "P_cmig_model"
    assert isinstance(costs["P_cmig_model@B"], RL.FillCosts) and costs["A_all_x1@A"] == C.Costs(
        priority_sol=RL.priority_for(RL.TX_FEE_SOL))


def test_a_failed_buy_is_an_entry_that_lost_its_fee_and_thirty_are_needed():
    pool = {"n_total": 2000, "var": 0.001}
    tr = [{"ret": 0.2, "pnl_sol": 0.006, "signal_ms": T0 + i * 3_600_000, "exit_ms": T0 + i * 3_600_000 + 9_000,
           "exit_why": "take", "slip": 0.01} for i in range(20)]
    fl = [{"pnl_sol": -0.001005, "signal_ms": T0 + 5, "land_ms": T0 + 6_000}]
    e = RL.entries(tr, fl)
    assert len(e) == 21 and e[-1]["ret"] == pytest.approx(-0.001005 / 0.03)
    s = RL.stats(tr, fl, ["2026-10-21"], pool)
    assert s["n"] == 21 and s["failed"] == 1 and s["win"] == pytest.approx(20 / 21)
    assert s["pnl_sol"] == pytest.approx(20 * 0.006 - 0.001005) and s["deflation"] == "stand-in"
    assert not s["positive"]                                                        # under 30 entries
    tr = tr + [dict(t, signal_ms=t["signal_ms"] + 20 * 3_600_000, exit_ms=t["exit_ms"] + 20 * 3_600_000)
               for t in tr]
    s = RL.stats(tr, fl, ["2026-10-21"], pool)
    assert s["n"] == 41 and s["band"][0] > 0
    assert s["positive"] == (s["z"] > RL.z_bar(2000))
    assert RL.z_bar(2000) == pytest.approx(4.06, abs=0.02)


# ---------------------------------------------------------------- end to end

def test_the_measured_latency_lands_later_on_the_same_signals(tmp_path, monkeypatch):
    """One snipe rule on one curve: the same signal fills later (at a worse price) under B than under A or C."""
    rule = next(r for r in S.RULES if r.name == "A_all_x1")
    sc = RL.scenarios()
    rules = [RL.scen_variant(rule, k) for k in RL.SCENARIOS]
    monkeypatch.setattr(sim, "STAKE", int(RL.STAKE_SOL * C.LAMPORTS))
    eng = sim.Engine(rules, rule_costs={r.name: sc[r.name.split("@")[1]] for r in rules})
    cv = Curve(eng)
    for i in range(40):                                         # steady buying for 20 s lifts the price
        cv.buy(T0 + 500 * (i + 1), int(0.1 * SOL), BUYERS[i % 60])
    eng.advance(T0 + 200_000)
    assert not eng.failed
    got = {t["rule"].split("@")[1]: t for t in eng.closed}
    assert set(got) == set(RL.SCENARIOS)
    assert got["B"]["lat_buy_ms"] > got["C"]["lat_buy_ms"] >= 1000 and got["C"]["lat_buy_ms"] <= 2000
    assert got["B"]["entry_price"] > got["C"]["entry_price"]
    assert got["Ct"]["pnl_sol"] == pytest.approx(got["C"]["pnl_sol"] - 2 * RL.TIP_SOL, abs=1e-9)
    assert sim.STAKE == int(0.03 * C.LAMPORTS)


def test_the_replay_runs_end_to_end_and_reports(tmp_path, monkeypatch):
    from lab.pumpfun_rt import store
    from test_pumpfun_rt import synth_store
    synth_store(tmp_path)
    monkeypatch.setattr(store, "base", lambda: tmp_path)
    monkeypatch.setattr("lab.pumpfun_rt.study.WARM_DAYS", 0)
    stake0 = sim.STAKE
    res = RL.run(root=tmp_path, until_ms=T0 + 3 * 86_400_000, log=lambda *a: None)
    assert sim.STAKE == stake0                                  # the engine's stake is put back
    live = [{"mint": res["closed"][0]["mint"] if res["closed"] else "x", "symbol": "SYM", "ret": "-0.08",
             "pnl_sol": "-0.0025", "exit_why": "time", "lat_buy_ms": "6616"}]
    ev = RL.evaluate(res["closed"], res["failed"], res["judged"], res["split_ms"], res["days"], live)
    assert set(ev["table"]) == set(RL.SCENARIOS)
    assert all(len(v) == 35 for v in ev["table"].values())
    assert ev["pool"]["mine"] == S.N_TRIALS
    assert {t["rule"].split("@")[1] for t in res["closed"]} <= set(RL.SCENARIOS)
    lat = {k: RL.describe(c, n=500) for k, c in RL.scenarios().items()}
    md = RL.report_md(res, ev, lat)
    assert "measured" in md and "\u2014" not in md and "C - B" in md
    json.dumps({"eval": ev, "latency": lat}, default=str)
    for t in res["closed"]:
        if t["rule"].startswith("P_"):
            assert t["stake_sol"] <= RL.STAKE_SOL + 1e-12
    assert math.isfinite(sum(t["pnl_sol"] for t in res["closed"]))
