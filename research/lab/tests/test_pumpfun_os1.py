"""OS1, a least-squares Monte Carlo exit and a conditional GPD crash exit for P_pool0 (os1): the registered trials and
latency, the replay's paths without step rows, the state from the path up to a time, the sale and the fall past the
latency, the path simulator (flowexit's with own signal times and the stop optional), Longstaff and Schwartz's
backward induction and its walk-forward, the GPD fit and its tail, VaR and ES, the calibration and the deflated
verdict. No network, no wallet.

Run from research/lab:  python -m pytest tests/test_pumpfun_os1.py
"""

from __future__ import annotations

import dataclasses
import math

import numpy as np
import pytest

from lab.pumpfun_rt import entry_e2 as E2
from lab.pumpfun_rt import flowexit as FX
from lab.pumpfun_rt import os1 as O
from lab.pumpfun_rt import pipeline as P
from lab.pumpfun_rt import sim
from test_pumpfun_exit_runners import Pool
from test_pumpfun_flow_exit_x14r2 import path, row
from test_pumpfun_rt import BUYERS, SOL, T0, Fixed


def test_the_trials_and_the_latency_are_the_registered_ones():
    ids = [t["id"] for t in O.trials()]
    assert ids == ["pumpfun:os1:E1", "pumpfun:os1:E2"] and all(t["family"] == "pumpfun" for t in O.trials())
    assert O.UNTIL_MS == E2.UNTIL_MS and O.costs().tx_lamports() == E2.LIVE_FEE_L and O.L_MS == 595.0
    assert O.E1_K == tuple(range(1, 60)) and O.E2_G[0] == 1 and O.E2_G[-1] == 299
    assert O.LAMBDAS == (0.02, 0.05, 0.10, 0.20, 0.30, 0.50) and O.CRASH == 0.30 and O.U_MAX == 0.20
    assert O.SIZINGS["live"] == P.Limits(0.05, 1, 0.6, 0.12) and O.SIZINGS["wide"] == P.Limits(0.1, 4, 0.6, 1.0)
    assert (O.TP, O.SL, O.TIME_S) == (0.30, 0.20, 300.0)


def test_the_replay_keeps_the_paths_without_step_rows():
    s = dataclasses.replace(P.BY_NAME["P_pool0"], name="P_pool0@N", p={"delay_s": 0, "base": "P_pool0"},
                            stake_sol=O.STAKE_SOL)
    eng = sim.Engine([], costs=Fixed(), rule_costs={s.name: Fixed()})
    pipe = eng.add_pipe(O.OS1Pipe(eng, s, {}))
    pool = Pool(eng)
    for i in range(20):
        pool.trade(T0 + 2_000 + 3_000 * i, i % 3 != 0, sol=SOL // 100, base=pool.pb // 200, user=BUYERS[50 + i % 5])
    eng.advance(T0 + FX.PATH_MS + 10_000)
    assert len(pipe.paths) == 1
    d = pipe.paths[0]
    assert d["land_ms"] == T0 + 1_000 and d["tokens"] > 0 and "X" not in d and "step_pt" not in d
    assert {"t", "x", "y", "fee", "buy", "dar", "bblast", "bbn"} <= set(d) and (d["buy"] == 0).sum() == 7


def test_the_state_reads_the_path_up_to_g_only():
    pa = path([1.0, 1.0, 1.1, 1.1, 1.1, 0.5], times=[T0, T0 + 1_000, T0 + 2_000, T0 + 3_000, T0 + 4_000, T0 + 30_000],
              buys=[-1, 0, 0, 0, 1, 0])
    pa.d["dar"][:] = [0.1, 0.2, 0.3, np.nan, 0.5, 0.6]
    pa.d["bblast"][:] = [np.nan, np.nan, T0 + 2_000, T0 + 2_000, T0 + 2_000, T0 + 2_000]
    z = O.states(pa, np.array([T0 + 3_500, T0 + 12_500, T0 + 60_000]))
    assert z[0, 0] == pytest.approx(math.log(pa.mult[3])) and z[0, 1:4].tolist() == [0, 1, 0]   # 3 sales: 3-5
    assert z[1, 1:4].tolist() == [1, 0, 0] and z[0, 4] == 0.0 and z[1, 4] == pytest.approx(0.5)  # one left in it
    assert z[0, 5] == 1 and z[2, 5] == 0                                  # the buyer's last buy 58 s before: over
    assert z[0, 6] == pytest.approx(3.5 / 300) and z[2, 0] == pytest.approx(math.log(pa.mult[5]))
    pb = path([1.0, 1.0, 1.1, 1.1, 1.1, 0.01], times=pa.t, buys=[-1, 0, 0, 0, 1, 0])
    pb.d["dar"][:], pb.d["bblast"][:] = pa.d["dar"], pa.d["bblast"]
    assert np.array_equal(O.states(pb, [T0 + 3_500])[:, :4], z[:1, :4])  # the future does not enter
    assert O.states(path([1.0, 1e-9, 2.0]), [T0 + 1_000, T0 + 2_000])[:, 0].tolist() == [O.R_CLIP[0], O.R_CLIP[1]]


def test_the_sale_lands_one_latency_later_and_the_fall_skips_it():
    pa = path([1.0, 0.5, 1.0, 0.8, 0.9], times=[T0, T0 + 300, T0 + 500, T0 + 5_000, T0 + 20_000])
    assert O.sale(pa, [T0])[0] == pytest.approx(pa.v[2] / pa.cost - 1)  # 595 ms later: the 0.5 is passed
    f = O.falls(pa, np.array([T0, T0 + 10_000.0, T0 + 30_000.0]))
    assert f[0] == pytest.approx(1 - pa.v[3] / pa.v[2]) and f[1] == pytest.approx(0.0) and f[2] == 0.0
    tau, cf = O.caps(path([1.0, 1.1, 1.31, 1.0]))
    assert tau == T0 + 2_000 and cf == pytest.approx(path([1.0, 1.1, 1.31, 1.0]).mult[2] - 1)
    tau, cf = O.caps(path([1.0, 1.1], times=[T0, T0 + 1_000]))
    assert tau == T0 + 300_000 and cf == pytest.approx(path([1.0, 1.1]).mult[1] - 1)


def test_the_simulator_is_flowexits_with_own_times_and_an_optional_stop():
    rng = np.random.default_rng(3)
    for _ in range(60):
        n = 80
        pa = path(np.cumprod(np.r_[1.0, 1 + rng.normal(0, 0.08, n - 1)]), times=[T0 + 4_000 * j for j in range(n)])
        for lat in (lambda leg: 600.0, lambda leg: 900.0 + 3_000 * leg):
            a, b = FX.simulate(pa, lat, 1_000), O.simulate(pa, lat, 1_000)
            assert (a["why"], a["pnl_l"], a["exit_ms"], a["legs"]) == (b["why"], b["pnl_l"], b["exit_ms"], b["legs"])
    pa = path([1.0, 0.9, 0.7, 0.7, 0.6])
    r = O.simulate(pa, lambda leg: 500.0, 0, np.array([T0 + 1_500.0]))
    assert r["why"] == "own" and r["sig_ms"] == T0 + 1_500 and r["got_l"] == pytest.approx(pa.v[2])
    assert O.simulate(pa, lambda leg: 500.0, 0, np.array([T0 + 1_500.0]), stop=False)["why"] == "own"
    assert O.simulate(pa, lambda leg: 500.0, 0, np.array([T0 + 3_000.0]))["why"] == "stop"
    r = O.simulate(pa, lambda leg: 500.0, 0, None, stop=False)
    assert r["why"] == "time" and r["legs"] == 1                       # no stop: held to the time stop
    assert O.simulate(path([1.0, 0.7, 1.31]), lambda leg: 500.0, 0, None, stop=False)["why"] == "take"


def lsm_paths(day: int, n: int = 160) -> list:
    """Half the paths: six sales at 50 s, then the value halves at 60 s; the rest drift to +10 %."""
    out = []
    for i in range(n):
        t0 = FX._utc(2026, 10, day, 2) + i * 400_000
        crash = i % 2 == 0
        tm = [t0, t0 + 1_000] + [t0 + 50_000 + 100 * j for j in range(6)] + [t0 + 60_000, t0 + 299_000]
        pr = [1.0, 1.0] + [1.0] * 6 + ([0.5, 0.5] if crash else [1.05, 1.1])
        pa = path(pr, times=tm, land_i=1, buys=[-1, 1] + [0 if crash else 1] * 6 + [1, 1])
        pa.d["signal_ms"] = t0
        out.append(pa)
    return out


def test_longstaff_schwartz_learns_to_sell_before_the_crash():
    paths = lsm_paths(20) + lsm_paths(21)
    tab = O.tables(paths)
    fits = O.lsm_fit(tab, tab["day"] == "2026-10-20")
    assert len(fits) == len(O.E1_K)
    k = 10                                                            # g = 55 s after the landing at 1 s: 54 s
    pred = O.ridge_predict(fits[k], O.basis(tab["Z1"][:160, k]))
    assert (pred[0::2] < 0).all() and (pred[1::2] > 0).all()
    wf = O.e1_walk(tab, log=lambda *a: None)
    assert all(f is None for f in wf["fire"][:160]) and wf["days"]["2026-10-20"]["fitted_k"] == 0
    assert wf["days"]["2026-10-21"]["train"] == 160 and wf["days"]["2026-10-21"]["fitted_k"] == len(O.E1_K)
    c = O.costs()
    rows = O.outcomes(paths[160:], [], c, 0, wf["fire"][160:], stop=False)
    crash = [x for x in rows if x["i"] % 2 == 0]
    assert all(x["why"] == "own" and x["ret"] > -0.05 for x in crash)
    assert all(x["why"] == "time" for x in rows if x["i"] % 2 == 1)
    assert O.lsm_fit(tab, np.zeros(len(paths), dtype=bool)) == {}
    stopped = path([1.0, 0.7, 0.7])
    rows = O.outcomes([stopped, stopped], [], c, 0, [None, None], [True, False])
    assert [x["why"] for x in rows] == ["stop", "time"]                 # a day without a fit: X0's trade


def test_the_training_mask_ends_before_the_day():
    a, b = lsm_paths(20, 2), lsm_paths(21, 2)
    b[0].land = FX._utc(2026, 10, 20, 23, 59) * 1.0
    tab = O.tables(a + b)
    tab["day"][2] = "2026-10-20"
    assert O.train_mask(tab, "2026-10-21").tolist() == [True, True, False, False]


def test_the_gpd_fit_and_its_tail():
    from scipy.stats import genpareto
    rng = np.random.default_rng(5)
    x = rng.normal(size=20_000)
    sig = np.exp(-3.0 + 0.5 * x)
    y = genpareto.rvs(0.2, scale=sig, random_state=rng)
    th = O.gpd_fit(x[:, None], y)
    assert th[0] == pytest.approx(-3.0, abs=0.05) and th[1] == pytest.approx(0.5, abs=0.05)
    assert th[2] == pytest.approx(0.2, abs=0.05)
    s = np.array([0.05, 0.1])
    assert O.gpd_tail(np.array([0.1, 0.1]), s, 0.2) == pytest.approx(genpareto.sf(0.1, 0.2, scale=s))
    assert O.gpd_tail(np.array([0.1]), np.array([0.05]), 0.0)[0] == pytest.approx(math.exp(-2))
    assert O.gpd_tail(np.array([0.3]), np.array([0.05]), -0.5)[0] == 0.0          # past the end at 0.1
    assert O.gpd_nll(np.array([0.0, 0.0, -0.5]), np.zeros((1, 1)), np.array([3.0])) == 1e10


def test_the_conditional_model_its_probability_var_and_es():
    rng = np.random.default_rng(7)
    n = 40_000
    Z = np.zeros((n, 7))
    Z[:, 0] = rng.normal(0, 0.1, n)
    Z[:, 3] = rng.random(n) < 0.2                                     # six sales or more: a fatter tail
    F = np.where(Z[:, 3] > 0, rng.beta(1, 3, n), rng.beta(1, 20, n))
    m = O.e2_fit(Z, F)
    assert m is not None and m["u"] <= O.U_MAX and m["exc"] >= O.E2_MIN_EXC
    z = np.zeros((2, 7))
    z[1, 3] = 1
    pr = O.e2_predict(m, z)
    assert pr["p"][1] > 5 * pr["p"][0] and pr["p"][1] == pytest.approx((F[Z[:, 3] > 0] > 0.3).mean(), abs=0.03)
    assert pr["p"][1] == pytest.approx(pr["pu"][1] * O.gpd_tail(np.array([0.3 - m["u"]]), pr["sigma"][1:], m["xi"])[0])
    q = 0.05 / pr["pu"][1]
    var = m["u"] + pr["sigma"][1] / m["xi"] * (q ** -m["xi"] - 1)
    assert pr["var"][1] == pytest.approx(var) and pr["es"][1] == pytest.approx(
        (var + pr["sigma"][1] - m["xi"] * m["u"]) / (1 - m["xi"]))
    assert pr["es"][1] > pr["var"][1] > m["u"]
    assert O.e2_fit(Z[:100], F[:100]) is None


def test_the_calibration_against_a_constant_hazard():
    tab = {"F2": np.array([[0.5, 0.0, 0.0, 0.4]])}
    wf = {"p": np.array([[0.9, 0.1, 0.1, 0.8]]), "base": np.full((1, 4), 0.5)}
    ca = O.calibration(tab, wf, np.array([True]))
    assert ca["n"] == 4 and ca["rate"] == 0.5 and ca["skill"] > 0.9 and ca["auc"] == 1.0
    assert sum(b["n"] for b in ca["bins"]) == 4


def test_the_verdict_is_deflated():
    base = [row(-0.2 if i % 3 == 0 else 0.1, 24 + i % 6, "stop" if i % 3 == 0 else "take", i=i) for i in range(60)]
    better = [dict(b, ret=b["ret"] + 0.05 * (1 + (i % 2))) for i, b in enumerate(base)]
    noise = list(np.random.default_rng(1).normal(0, 0.05, 50))
    v = O.verdict(better, base, noise, 200)
    assert v["higher"] and v["band_above"] and v["deflated"]["dsr"] > 0.95 and v["passes"]
    v = O.verdict(better, base)
    assert v["band_above"] and v["deflated"]["dsr"] is None and not v["passes"]   # no pool: no pass
    loud = list(np.random.default_rng(1).normal(0, 5.0, 50))
    assert not O.verdict(better, base, loud, 10 ** 6)["passes"]
    four = [r for r in base if r["day"] < "2026-10-28"]
    assert not O.verdict(four, four, noise, 200)["passes"]
