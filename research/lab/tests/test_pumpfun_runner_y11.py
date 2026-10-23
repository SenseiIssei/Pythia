"""Y11, P_pool0_wait keeping a 20 % rest after its time stop: the two registered strategies and trials, the exits
before the time stop exactly P_pool0_wait's, the partial sale at the time stop, the rest's stop under the entry, its
fall from the high (armed only once above the entry), the hard stop (also while a sale is in flight), the kill
switch on the rest, the rest's numbers in the closed trade, every strategy before Y11 trading exactly as before, and
the replay's helpers end to end. No network, no wallet.

Run from research/lab:  python -m pytest tests/test_pumpfun_runner_y11.py
"""

from __future__ import annotations

import dataclasses
import json
import math

import pytest

from lab.pumpfun_rt import curve as C
from lab.pumpfun_rt import exitlab as XL
from lab.pumpfun_rt import model as M
from lab.pumpfun_rt import pipeline as P
from lab.pumpfun_rt import reallat as RL
from lab.pumpfun_rt import runner11 as Y11
from lab.pumpfun_rt import select9 as Y9
from lab.pumpfun_rt import selfeat as SF
from lab.pumpfun_rt import sim
from lab.pumpfun_rt import store
from lab.pumpfun_rt import strategies as S
from test_pumpfun_exit_runners import Pool, closed, engine
from test_pumpfun_rt import MINT, T0, Fixed

Y11_NAMES = ["P_pool0_wait_run20", "P_pool0_wait_run20w"]
OLD = P.STRATEGIES[:[s.name for s in P.STRATEGIES].index(Y11_NAMES[0])]   # every strategy before Y11
LAND = T0 + 1_000                                     # Fixed latency: the buy lands 1 s after the migration
TIME = LAND + 300_000                                 # the time stop; its sale lands 1 s later


@pytest.fixture(autouse=True)
def small_models(monkeypatch):
    monkeypatch.setitem(M.PARAMS, "n_estimators", 30)


def three():
    eng = engine("P_pool0_wait", *Y11_NAMES)
    return eng, Pool(eng)


def pos(eng, name) -> dict:
    got = [p for p in eng.pipes[0].pos.values() if p["rule"] == name]
    assert len(got) == 1
    return got[0]


# ---------------------------------------------------------------- the registered strategies

def test_the_y11_strategies_and_trials_are_what_the_prereg_says():
    names = [s.name for s in P.STRATEGIES]
    assert names[-5:-3] == Y11_NAMES and [n for _, n in Y11.VARIANTS] == ["P_pool0_wait"] + Y11_NAMES
    base = P.BY_NAME["P_pool0_wait"]
    for n, rn in zip(Y11_NAMES, ((0.20, 0.50, 0.30, 1800), (0.20, 0.70, 0.40, 3600))):
        s = P.BY_NAME[n]
        assert s.exits.runner == rn and dataclasses.replace(s.exits, runner=None) == base.exits
        assert (s.family, s.entry, s.p, s.flt, s.stake_sol, s.tp, s.sl, s.hold_s) == (
            "E", "migration", {"delay_s": 0, "wait_pool_s": 5}, {}, 0.1, 0.30, 0.20, 300)
    assert all(s.exits.runner is None for s in OLD) and P.Exits(300, 0.2).runner is None
    assert S.RUNNER_Y11_TRIALS == 4 == 2 * len(Y11.LIMITS)
    assert S.N_TRIALS == 22 + 1 + 12 + 54 + 135 + 140 + 1 + 6 + 5 + 10 + 10 + 4 + 12


# ---------------------------------------------------------------- before the time stop: P_pool0_wait's exits

@pytest.mark.parametrize("ratio,why", [(1.5, "take"), (0.7, "stop")])
def test_before_the_time_stop_the_runners_exit_exactly_as_p_pool0_wait(ratio, why):
    eng, pool = three()
    pool.to(T0 + 60_000, ratio)
    eng.advance(T0 + 70_000)
    a = closed(eng, "P_pool0_wait")
    assert a["exit_why"] == why and a["legs"] == 1 and "run_pnl_sol" not in a
    for n in Y11_NAMES:
        b = closed(eng, n)
        assert {k: v for k, v in a.items() if k not in ("rule", "pid")} == {
            k: v for k, v in b.items() if k not in ("rule", "pid")}


# ---------------------------------------------------------------- the partial sale and the rest

def test_the_time_stop_sells_80_percent_and_keeps_20():
    eng, pool = three()
    pool.trade(TIME - 10_000, True, sol=C.LAMPORTS // 100)
    eng.advance(TIME + 1_500)
    a = closed(eng, "P_pool0_wait")
    assert a["exit_why"] == "time" and a["exit_signal_ms"] == TIME
    for n in Y11_NAMES:
        p = pos(eng, n)
        rn = p["run"]
        assert rn["from_ms"] == TIME and rn["keep"] == int(p["tokens"] * 0.2) == p["left"]
        assert rn["part_tokens"] == p["tokens"] - rn["keep"] and rn["part_l"] > 0 and p["legs"] == 1
        assert not p["selling"] and not p.get("exiting") and 0.9 < rn["high"] < 1.0
    # the 80 % fetched 80 % of what the whole brought (a small pool impact aside)
    assert pos(eng, Y11_NAMES[0])["run"]["part_l"] == pytest.approx(0.8 * a["proceeds_sol"] * C.LAMPORTS, rel=0.01)


def test_the_rest_stops_at_minus_50_percent_and_the_wide_one_at_minus_70():
    eng, pool = three()
    eng.advance(TIME + 1_500)
    pool.to(TIME + 60_000, 0.45)                          # about -55 %: R1's stop, not R2's
    eng.advance(TIME + 70_000)
    r1 = closed(eng, "P_pool0_wait_run20")
    assert r1["exit_why"] == "run_stop" and r1["legs"] == 2 and r1["exit_signal_ms"] - TIME - 60_000 in range(4)
    assert r1["run_pnl_sol"] < -0.5 * r1["run_cost_sol"] and r1["run_vs_time_sol"] < 0
    assert pos(eng, "P_pool0_wait_run20w")["left"] > 0
    pool.to(TIME + 120_000, 0.25)                         # about -75 %
    eng.advance(TIME + 130_000)
    r2 = closed(eng, "P_pool0_wait_run20w")
    assert r2["exit_why"] == "run_stop" and r2["run_pnl_sol"] < -0.7 * r2["run_cost_sol"]
    # the -20 % stop does not apply to the rest: at -55 % R2 held on
    assert r2["exit_signal_ms"] - TIME - 120_000 in range(4)


def test_the_rest_trails_30_percent_under_its_high_once_above_the_entry():
    eng, pool = three()
    eng.advance(TIME + 1_500)
    pool.to(TIME + 60_000, 0.8)                           # under the entry: the trail is not armed, no -30 % sale
    eng.advance(TIME + 70_000)
    assert pos(eng, "P_pool0_wait_run20")["left"] > 0
    pool.to(TIME + 120_000, 2.0)                          # a pump after the time stop
    pool.to(TIME + 180_000, 1.5)                          # 25 % off the high: R1 holds (30 %), R2 holds (40 %)
    eng.advance(TIME + 190_000)
    assert pos(eng, "P_pool0_wait_run20")["run"]["high"] > 1.9
    pool.to(TIME + 240_000, 1.3)                          # 35 % off: R1 sells, R2 not yet
    eng.advance(TIME + 250_000)
    r1 = closed(eng, "P_pool0_wait_run20")
    assert r1["exit_why"] == "run_trail" and r1["exit_signal_ms"] - TIME - 240_000 in range(4)
    assert r1["run_pnl_sol"] > 0 and r1["run_vs_time_sol"] > 0 and r1["run_high"] > 1.9
    pool.to(TIME + 300_000, 1.1)                          # 45 % off: R2 sells
    eng.advance(TIME + 310_000)
    r2 = closed(eng, "P_pool0_wait_run20w")
    assert r2["exit_why"] == "run_trail" and r2["exit_signal_ms"] - TIME - 300_000 in range(4)
    # the whole position: the 80 % at the time stop and the rest later, every fee paid
    x0 = closed(eng, "P_pool0_wait")
    assert r1["pnl_sol"] > x0["pnl_sol"] and r1["legs"] == 2
    fees = 3 * Fixed().tx_lamports() / C.LAMPORTS            # the buy, the 80 % and the rest
    assert r1["pnl_sol"] == pytest.approx(r1["proceeds_sol"] - 0.1 - fees, abs=1e-9)


def test_the_hard_stop_sells_the_rest_at_30_and_60_minutes_after_the_landing():
    eng, pool = three()
    for i in range(1, 70):                                # a quiet pool: one small trade a minute
        pool.trade(T0 + i * 60_000, i % 2 == 0, sol=C.LAMPORTS // 1000, base=10 ** 6)
        eng.advance(T0 + i * 60_000 + 1)
    r1, r2 = closed(eng, "P_pool0_wait_run20"), closed(eng, "P_pool0_wait_run20w")
    assert r1["exit_why"] == r2["exit_why"] == "run_time"
    assert r1["exit_signal_ms"] == LAND + 1_800_000 and r2["exit_signal_ms"] == LAND + 3_600_000
    assert r1["exit_ms"] == LAND + 1_801_000 and r1["legs"] == 2


def test_the_hard_stop_waits_for_a_sale_in_flight_and_then_sells_the_rest():
    eng, pool = three()
    eng.advance(TIME + 1_500)
    pipe = eng.pipes[0]
    p = pos(eng, "P_pool0_wait_run20")
    p["selling"] = True                                    # as if a sale were still on its way
    pipe._run_end(LAND + 1_800_000, p["pid"])
    assert p["due"] == "run_time" and p["left"] > 0
    p["selling"] = False
    pipe._after_leg(p, LAND + 1_800_500)
    eng.advance(LAND + 1_802_000)
    assert closed(eng, "P_pool0_wait_run20")["exit_why"] == "run_time"


def test_the_kill_switch_sells_the_rest():
    state = {"kill": False}
    eng = sim.Engine([], costs=Fixed(), strategies=[P.BY_NAME[Y11_NAMES[0]]], kill=lambda: state["kill"])
    pool = Pool(eng)
    eng.advance(TIME + 1_500)
    state["kill"] = True
    pool.trade(TIME + 10_000, True, sol=C.LAMPORTS // 1000)
    eng.advance(TIME + 12_000)
    t = closed(eng, Y11_NAMES[0])
    assert t["exit_why"] == "kill" and t["run_cost_sol"] > 0


def test_a_failed_time_stop_sale_is_sent_again():
    eng, pool = three()
    eng.advance(TIME + 100)                                # the 80 % sale is in flight
    pipe = eng.pipes[0]
    p = pos(eng, "P_pool0_wait_run20")
    amount = p["run_part"]
    sent = []
    real = pipe._sell
    pipe._sell = lambda p_, t, a, f, w: (sent.append((a, f, w)), real(p_, t, a, f, w))
    pipe.sell_failed(p["pid"], TIME + 500, "under the floor", Fixed().tx_lamports())
    assert sent == [(amount, 0, "time_part")] and p["run_part"] == amount


# ---------------------------------------------------------------- nothing before Y11 changes

def test_every_strategy_before_y11_trades_exactly_as_before(tmp_path, monkeypatch):
    """One shared paper book of every strategy before Y11 on a synthetic record, without and with the Y11 books (the
    rests trading): the closed trades, failed buys and skips of the old strategies are the same field for field
    (the pid aside, as Y9's and Y10's tests)."""
    from test_pumpfun_select_y9 import market, write
    from test_pumpfun_trends_y10 import y10_models
    write(tmp_path, market(n=24, every_ms=1_500_000))
    monkeypatch.setattr(store, "base", lambda: tmp_path)
    days = store.days(tmp_path)

    def run(new: bool):
        eng = sim.Engine(S.RULES, costs=Fixed(), strategies=P.STRATEGIES if new else OLD, models=y10_models(),
                         select=True, trend=True)
        eng.add_pipe(SF.LabelPipe(eng))
        sim.replay(days, eng, tmp_path)
        return eng
    a, b = run(False), run(True)
    old = {s.name for s in OLD} | {r.name for r in S.RULES}

    def strip(xs):
        out = [{k: v for k, v in x.items() if k != "pid"} for x in xs if x["rule"] in old]
        return sorted(out, key=lambda x: (x["rule"], x["mint"], x["signal_ms"], x.get("exit_ms") or x.get("land_ms")))
    assert strip(a.closed) and strip(a.closed) == strip(b.closed) and strip(a.failed) == strip(b.failed)
    assert {k: v for k, v in a.skipped.items() if k[0] in old} == {k: v for k, v in b.skipped.items() if k[0] in old}
    rests = [t for t in b.closed if t["rule"] in Y11_NAMES and t.get("run_from_ms") is not None]
    assert rests and all(t["exit_why"].startswith("run_") for t in rests)
    assert not any("run_pnl_sol" in t for t in a.closed)


# ---------------------------------------------------------------- the replay's helpers

def test_books_latency_and_limits():
    strats, costs = Y11.books()
    assert len(strats) == len(costs) == 6 and all(s.stake_sol == 0.1 for s, _ in strats)
    assert {sim.base_name(s) for s, _ in strats} == {"P_pool0"}
    assert [s.name for s, _ in strats][:3] == ["P_pool0_wait@L25", "P_pool0_wait_run20@L25", "P_pool0_wait_run20w@L25"]
    assert {lim.max_daily_loss_sol for _, lim in strats} == {0.25, 1.0}
    b = costs["P_pool0_wait_run20@L100"]
    assert b.buy.points_ms == Y9.SENDER_BUY_MS and b.sell.points_ms == Y9.SENDER_SELL_MS and b.tx_lamports() == 1_005_000
    assert Y11.TAIL_MS >= 3_600_000 + 5_000 + 2 * RL.CLIP_MS[1]


def r(pnl, vs, cost=0.02, why="run_trail"):
    return {"run_from_ms": T0, "run_pnl_sol": pnl, "run_vs_time_sol": vs, "run_cost_sol": cost, "exit_why": why}


def test_rest_stats():
    xs = [r(0.01, 0.012), r(-0.015, -0.002, why="run_stop"), r(-0.001, 0.001, why="run_time"),
          {"run_from_ms": None, "exit_why": "take"}]
    s = Y11.rest_stats(xs)
    assert s["n"] == 3 and s["made_money"] == pytest.approx(1 / 3) and s["beat_time"] == pytest.approx(2 / 3)
    assert s["worst_sol"] == -0.015 and s["worst_ret"] == pytest.approx(-0.75) and s["best_sol"] == 0.01
    assert s["added_sol"] == pytest.approx(0.011) and s["exits"] == {"run_stop": 1, "run_time": 1, "run_trail": 1}
    assert Y11.rest_stats([{"run_from_ms": None}]) == {"n": 0}


def test_the_replay_runs_end_to_end_and_reports(tmp_path, monkeypatch):
    from test_pumpfun_select_y9 import market, write
    write(tmp_path, market(n=24, every_ms=1_500_000))
    monkeypatch.setattr(store, "base", lambda: tmp_path)
    monkeypatch.setattr("lab.pumpfun_rt.study.WARM_DAYS", 0)
    res = Y11.run(root=tmp_path, until_ms=T0 + 3 * 86_400_000, log=lambda *a: None)
    assert set(res["entries"]) == {f"{n}@{k}" for _, n in Y11.VARIANTS for k in Y11.LIMITS}
    assert res["entry_until_ms"] == res["span"][1] - Y11.TAIL_MS and not res["open_at_end"]
    for k in Y11.LIMITS:
        x0 = res["entries"][f"P_pool0_wait@{k}"]
        assert x0 and all(x["run_from_ms"] is None for x in x0)
    rests = [x for k in Y11.LIMITS for n in Y11_NAMES for x in res["entries"][f"{n}@{k}"]
             if x["run_from_ms"] is not None]
    assert rests and all(x["run_cost_sol"] == pytest.approx(0.02, rel=0.05) for x in rests)
    ev = Y11.evaluate(res)
    assert set(ev["better"]) == {"R1", "R2"} and set(ev["versus"]["L25"]) == {"R1", "R2"}
    dropped = Y11.evaluate(res, keep_gapped=False)
    lat = {k: RL.describe(c, n=500) for k, c in Y9.scenarios().items()}
    md = Y11.report_md(res, ev, dropped, lat)
    assert "better than X0" in md and "rest made money" in md and "\u2014" not in md and "R2" in md
    json.dumps({"eval": ev, "latency": lat}, default=str)
    assert not math.isnan(ev["table"]["L100"]["R1"].get("mean", 0.0))
    assert XL.hours([]) == 0
