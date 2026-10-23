"""Y7, P_pool0's exits for runners: the five registered strategies, the trail's meaning, the later time stop
(Exits.time_after_step_s) and that without it the time stop is what it always was, the latency since the
Sender path, the books and their shared key, the numbers (drawdown, top 5 %, runners and capture, the paired
difference against X0) and the replay end to end on a synthetic record with migrations. No network, no wallet.

Run from research/lab:  python -m pytest tests/test_pumpfun_exit_runners.py
"""

from __future__ import annotations

import json
import math

import numpy as np
import pytest

from lab.pumpfun_rt import curve as C
from lab.pumpfun_rt import exitlab as XL
from lab.pumpfun_rt import model as M
from lab.pumpfun_rt import pipeline as P
from lab.pumpfun_rt import reallat as RL
from lab.pumpfun_rt import sim
from lab.pumpfun_rt import store
from lab.pumpfun_rt import strategies as S
from test_pumpfun_rt import BUYERS, MINT, POOL, SOL, T0, Curve, Fixed, key

BASE0 = 206_900_000 * 10 ** 6
QUOTE0 = 67 * SOL


@pytest.fixture(autouse=True)
def small_models(monkeypatch):
    monkeypatch.setitem(M.PARAMS, "n_estimators", 30)


class Pool:
    """A migrated token whose PumpSwap pool emits consistent trades (constant product, no fee in the reserves)."""

    def __init__(self, eng: sim.Engine, mint=MINT, t=T0, slot=50_000):
        self.eng, self.mint, self.slot = eng, mint, slot
        Curve(eng, mint=mint, t=t - 120_000, slot=slot - 40_000)
        eng.complete(t, mint)
        self.pb, self.pq = BASE0, QUOTE0
        self.trade(t, True, SOL // 1000)
        eng.migrate(t, mint, POOL, 85 * SOL, BASE0)

    def trade(self, t, buy: bool, sol: int = 0, base: int = 0, user=BUYERS[1]):
        if buy:
            base = int(self.pb * sol / (self.pq + sol))
        else:
            sol = int(self.pq * base / (self.pb + base))
        self.slot += 1
        self.eng.amm(t, self.mint, buy, base, sol, self.pb, self.pq, 20, 5, 5, slot=self.slot, user=user)
        self.pb, self.pq = (self.pb - base, self.pq + sol) if buy else (self.pb + base, self.pq - sol)

    def to(self, t, ratio: float, user=BUYERS[1]):
        """Move the price to `ratio` times the opening price (in a few trades, none a large holder's)."""
        k = self.pb * self.pq
        target = QUOTE0 * math.sqrt(ratio)
        steps = 4
        for i in range(steps):
            q = self.pq + (target - self.pq) / (steps - i)
            if q > self.pq:
                self.trade(t + i, True, sol=int(q - self.pq), user=BUYERS[2 + i])
            elif q < self.pq:
                self.trade(t + i, False, base=int(k / q - self.pb), user=BUYERS[2 + i])


def engine(*names, **kw) -> sim.Engine:
    return sim.Engine([], costs=Fixed(), strategies=[P.BY_NAME[n] for n in names], **kw)


def closed(eng, name) -> dict:
    got = [t for t in eng.closed if t["rule"] == name]
    assert len(got) == 1, (name, [t["rule"] for t in eng.closed], eng.skipped)
    return got[0]


# ---------------------------------------------------------------- the registered strategies

def test_the_y7_strategies_are_what_the_prereg_says():
    names = [n for _, n in XL.VARIANTS]
    all_names = [s.name for s in P.STRATEGIES]
    i = all_names.index("P_pool0")
    assert names[0] == "P_pool0" and all_names[i + 1:i + 6] == names[1:]
    base = P.BY_NAME["P_pool0"]
    for n in names[1:]:
        s = P.BY_NAME[n]
        assert (s.family, s.entry, s.p, s.flt) == (base.family, base.entry, base.p, base.flt) == (
            "E", "migration", {"delay_s": 0}, {})
        assert s.stake_sol == 0.1 and s.exits.sl == 0.20 and not s.exits.hazard and s.exits.risk is None
        assert s.exits.ladder[-1] == (50.0, 1.0)
        assert (s.exits.dev_sell, s.exits.pull) == ((True, True) if n == "P_pool0_half_trail_guard" else (False, False))
        assert (s.exits.time_after_step_s is None) == (n != "P_pool0_half_trail_ext")
    ex = {n: P.BY_NAME[n].exits for n in names}
    assert (ex["P_pool0_half_trail"].ladder, ex["P_pool0_half_trail"].trail_after, ex["P_pool0_half_trail"].trail_gap,
            ex["P_pool0_half_trail"].time_s) == (((0.30, 0.5), (50.0, 1.0)), 0.30, 0.30, 1800)
    assert (ex["P_pool0_ladder3"].ladder, ex["P_pool0_ladder3"].trail_after, ex["P_pool0_ladder3"].trail_gap,
            ex["P_pool0_ladder3"].time_s) == (((0.30, 0.34), (1.00, 0.67), (50.0, 1.0)), 0.30, 0.35, 3600)
    assert (ex["P_pool0_trail"].ladder, ex["P_pool0_trail"].trail_after, ex["P_pool0_trail"].trail_gap,
            ex["P_pool0_trail"].time_s) == (((50.0, 1.0),), 0.20, 0.25, 1800)
    import dataclasses
    assert ex["P_pool0_half_trail_guard"] == dataclasses.replace(ex["P_pool0_half_trail"], dev_sell=True, pull=True)
    assert ex["P_pool0_half_trail_ext"] == dataclasses.replace(ex["P_pool0_half_trail"], time_s=300,
                                                                 time_after_step_s=3600)
    for s in P.STRATEGIES:                                     # nothing before Y7 has the later time stop
        if s.name not in names[1:]:
            assert s.exits.time_after_step_s is None


def test_the_trials_are_counted():
    assert S.EXIT_RUNNER_TRIALS == 6 and len(XL.VARIANTS) == 6
    assert S.N_TRIALS == 22 + 1 + 12 + 54 + 135 + 140 + 1 + 6 + 5 + 10 + 10 + 4


def test_every_trail_fires_before_the_stop_once_armed():
    """The registered "stop -20 % until the first take profit": once a trail is armed (at or above the first
    step's gain where there is a step) it sells above 0.8 of the cost, so the stop no longer acts."""
    for _, n in XL.VARIANTS[1:]:
        ex = P.BY_NAME[n].exits
        assert (1 + ex.trail_after) * (1 - ex.trail_gap) > 1 - ex.sl
        if ex.ladder[0][0] < 1:
            assert ex.trail_after <= ex.ladder[0][0]


# ---------------------------------------------------------------- the exits on a pool

def test_x0_takes_thirty_percent_and_the_half_trail_lets_the_rest_run():
    eng = engine("P_pool0", "P_pool0_half_trail", "P_pool0_trail")
    pool = Pool(eng)
    pool.to(T0 + 5_000, 1.5)                                   # +50 %: X0 sells all, X1 half, X3 holds
    eng.advance(T0 + 8_000)
    x0 = closed(eng, "P_pool0")
    assert x0["exit_why"] == "take" and x0["legs"] == 1 and 0.3 < x0["ret"] < 0.6
    half = next(p for p in eng.pipes[0].pos.values() if p["rule"] == "P_pool0_half_trail")
    assert half["legs"] == 1 and half["left"] == int(half["tokens"] * (1 - 0.5))
    pool.to(T0 + 20_000, 3.0)                                  # runs on to 3x
    pool.to(T0 + 40_000, 2.4)                                  # 20 % off the peak: no trail yet for either
    eng.advance(T0 + 45_000)
    assert {p["rule"] for p in eng.pipes[0].pos.values()} == {"P_pool0_half_trail", "P_pool0_trail"}
    pool.to(T0 + 60_000, 2.2)                                  # 27 % off: X3's 25 % trail, not X1's 30 %
    eng.advance(T0 + 65_000)
    x3 = closed(eng, "P_pool0_trail")
    assert x3["exit_why"] == "trail" and x3["legs"] == 1 and x3["ret"] > 1.0
    pool.to(T0 + 80_000, 1.9)                                  # 37 % off the peak: X1's trail sells the rest
    eng.advance(T0 + 90_000)
    x1 = closed(eng, "P_pool0_half_trail")
    assert x1["exit_why"] == "trail" and x1["legs"] == 2 and x1["ret"] > x0["ret"]


def test_the_ladder3_sells_thirds_then_trails():
    eng = engine("P_pool0_ladder3")
    pool = Pool(eng)
    pool.to(T0 + 5_000, 1.5)
    eng.advance(T0 + 8_000)
    lad = next(iter(eng.pipes[0].pos.values()))
    assert lad["legs"] == 1 and lad["left"] == int(lad["tokens"] * (1 - 0.34))
    pool.to(T0 + 10_000, 2.3)                                  # past +100 %: the second third
    eng.advance(T0 + 14_000)
    assert lad["legs"] == 2 and lad["left"] == int(lad["tokens"] * (1 - 0.67))
    pool.to(T0 + 20_000, 1.6)                                  # 30 % off the peak: not yet
    eng.advance(T0 + 24_000)
    assert not eng.closed
    pool.to(T0 + 30_000, 1.4)                                  # 39 % off: the trail sells the last third
    eng.advance(T0 + 35_000)
    t = closed(eng, "P_pool0_ladder3")
    assert t["exit_why"] == "trail" and t["legs"] == 3 and t["ret"] > 0.3


def test_the_guard_leaves_on_a_pull_and_the_others_do_not():
    eng = engine("P_pool0_half_trail", "P_pool0_half_trail_guard")
    pool = Pool(eng)
    whale = BUYERS[41]
    pool.trade(T0, True, sol=14 * SOL, user=whale)             # a big holder (3.6 % of the supply), before our signal
    pool.to(T0 + 5_000, 2.1)                                   # about +44 % over our entry: both sell half
    eng.advance(T0 + 8_000)
    assert all(p["legs"] == 1 for p in eng.pipes[0].pos.values()) and len(eng.pipes[0].pos) == 2
    pool.trade(T0 + 20_000, False, base=eng.tokens[MINT].hold[whale], user=whale)   # dumps it all at once
    eng.advance(T0 + 25_000)
    g = closed(eng, "P_pool0_half_trail_guard")
    assert g["exit_why"] == "pull" and g["exit_signal_ms"] == T0 + 20_000
    x1 = closed(eng, "P_pool0_half_trail")
    assert x1["exit_why"] == "trail" and x1["exit_signal_ms"] == T0 + 20_000         # the price exit instead


def test_ext_keeps_300_s_until_the_step_then_an_hour():
    eng = engine("P_pool0_half_trail", "P_pool0_half_trail_ext")
    pool = Pool(eng)
    pool.to(T0 + 100_000, 1.5)                                 # the half sells at 100 s
    for k in range(1, 70):                                     # flat afterwards (trades every minute)
        pool.trade(T0 + 100_000 + k * 60_000, k % 2 == 0, sol=SOL // 100, base=10 ** 9)
    eng.advance(T0 + 3_700_000)
    land = T0 + 1_000
    x1, x5 = closed(eng, "P_pool0_half_trail"), closed(eng, "P_pool0_half_trail_ext")
    assert x1["exit_why"] == "time" and x1["exit_signal_ms"] == land + 1_800_000
    assert x5["exit_why"] == "time" and x5["exit_signal_ms"] == land + 3_600_000 and x5["legs"] == 2
    eng = engine("P_pool0_half_trail_ext")                     # no step: out at 300 s
    pool = Pool(eng)
    for k in range(1, 10):
        pool.trade(T0 + k * 60_000, k % 2 == 0, sol=SOL // 100, base=10 ** 9)
    eng.advance(T0 + 700_000)
    t = closed(eng, "P_pool0_half_trail_ext")
    assert t["exit_why"] == "time" and t["exit_signal_ms"] == land + 300_000 and t["legs"] == 1


# ---------------------------------------------------------------- the later time stop on the pipeline itself

def strat(time_s=10, after=None, ladder=((0.3, 0.5), (5.0, 1.0))) -> P.Strategy:
    ex = P.Exits(time_s, 0.9, ladder, dev_sell=False, pull=False, time_after_step_s=after)
    return P.Strategy("X", "A", "create", ladder[-1][0], 0.9, time_s, {"filter": "all"}, "test", exits=ex)


def run_curve(s: P.Strategy, events, until) -> tuple[sim.Engine, dict]:
    eng = sim.Engine([], costs=Fixed(), strategies=[s])
    cv = Curve(eng)
    for f in events:
        f(cv)
    eng.advance(until)
    return eng, (eng.closed[0] if eng.closed else None)


def test_without_the_new_field_the_time_stop_is_landing_plus_time_s_after_a_step_too():
    eng, t = run_curve(strat(time_s=10), [lambda cv: cv.buy(T0 + 2_000, 6 * SOL, BUYERS[0])], T0 + 30_000)
    assert t["legs"] == 2 and t["exit_why"] == "time" and t["exit_signal_ms"] == T0 + 1_000 + 10_000
    # the step's sale is still in flight at the time stop: the rest goes as soon as it is back, as before
    eng, t = run_curve(strat(time_s=2), [lambda cv: cv.buy(T0 + 2_500, 6 * SOL, BUYERS[0])], T0 + 30_000)
    assert t["legs"] == 2 and t["exit_why"] == "time" and t["exit_signal_ms"] == T0 + 3_500


def test_the_later_time_stop_after_a_filled_step():
    eng, t = run_curve(strat(time_s=10, after=60), [lambda cv: cv.buy(T0 + 2_000, 6 * SOL, BUYERS[0])], T0 + 30_000)
    assert t is None and eng.pipes[0].pos                          # held past 10 s: a step has filled
    eng.advance(T0 + 70_000)
    t = eng.closed[0]
    assert t["exit_why"] == "time" and t["exit_signal_ms"] == T0 + 1_000 + 60_000 and t["legs"] == 2
    eng, t = run_curve(strat(time_s=10, after=60), [], T0 + 30_000)   # no step: the first time stop
    assert t["exit_why"] == "time" and t["exit_signal_ms"] == T0 + 11_000 and t["legs"] == 1


def test_a_step_in_flight_at_the_time_stop_moves_it_once_it_fills_and_not_if_it_fails():
    eng, t = run_curve(strat(time_s=2, after=60), [lambda cv: cv.buy(T0 + 2_500, 6 * SOL, BUYERS[0])], T0 + 30_000)
    assert t is None                                               # filled at 3.5 s: moved to 61 s
    eng.advance(T0 + 70_000)
    assert eng.closed[0]["exit_signal_ms"] == T0 + 61_000 and eng.closed[0]["exit_why"] == "time"
    eng = sim.Engine([], costs=Fixed(), strategies=[strat(time_s=2, after=60)])
    cv = Curve(eng)
    dev = cv.buy(T0, 20 * SOL, cv.dev, same_tx=True)               # in the creation: our signal's state
    mine = cv.buy(T0 + 2_500, 10 * SOL, BUYERS[0])                 # +44 %: the half's sale goes out
    cv.sell(T0 + 2_800, mine, BUYERS[0])                           # both sell out before it lands:
    cv.sell(T0 + 2_900, dev, cv.dev)                               # it lands under its floor and fails
    eng.advance(T0 + 30_000)
    t = eng.closed[0]
    assert t["exit_why"] == "time" and t["exit_signal_ms"] == T0 + 3_500 and t["legs"] == 1


def test_a_dev_sale_while_a_step_is_in_flight_is_an_exit_only_where_the_strategy_has_it():
    def run(dev_sell: bool):
        ex = P.Exits(600, 0.9, ((0.3, 0.5), (5.0, 1.0)), dev_sell=dev_sell, pull=False)
        s = P.Strategy("X", "A", "create", 5.0, 0.9, 600, {"filter": "all"}, "test", exits=ex)
        eng = sim.Engine([], costs=Fixed(), strategies=[s])
        cv = Curve(eng)
        dev = cv.buy(T0, 2 * SOL, cv.dev, same_tx=True)
        cv.buy(T0 + 2_000, 7 * SOL, BUYERS[0])                     # the half's sale goes out, lands at 3 s
        cv.sell(T0 + 2_500, dev // 2, cv.dev)                      # the dev sells half meanwhile
        eng.advance(T0 + 20_000)
        return eng
    eng = run(True)                                                # as always: out as soon as the half is back
    assert eng.closed[0]["exit_why"] == "dev_sell" and eng.closed[0]["exit_signal_ms"] == T0 + 3_000
    eng = run(False)                                               # Y7: no dev-sell exit, the rest stays
    assert not eng.closed and next(iter(eng.pipes[0].pos.values()))["legs"] == 1


# ---------------------------------------------------------------- latency and books

def test_the_sender_fills_are_the_executors_p_pool0_rows_in_the_window():
    w0 = XL.SENDER_FROM_MS
    rows = [{"t": w0 - 1, "what": "fill", "mode": "test", "rule": "P_pool0", "side": "buy", "lat_ms": 7000},
            {"t": w0, "what": "fill", "mode": "test", "rule": "P_pool0", "side": "buy", "lat_ms": 472},
            {"t": w0 + 1, "what": "fill", "mode": "test", "rule": "P_pool0", "side": "buy", "lat_ms": -255},
            {"t": w0 + 2, "what": "fill", "mode": "test", "rule": "P_pool0", "side": "sell", "lat_ms": 38000},
            {"t": w0 + 3, "what": "fill", "mode": "test", "rule": "P_cmig_model", "side": "buy", "lat_ms": 9000},
            {"t": w0 + 4, "what": "fill", "mode": "full", "rule": "P_pool0", "side": "buy", "lat_ms": 9000},
            {"t": w0 + 5, "what": "fill", "mode": "test", "rule": "P_pool0", "side": "sell", "lat_ms": None},
            {"t": w0 + 6, "what": "failed", "mode": "test", "rule": "P_pool0", "side": "buy", "lat_ms": 9000},
            {"t": w0 + 7, "what": "fill", "mode": "test", "rule": "P_pool0", "side": "sell", "lat_ms": 99_000},
            {"t": XL.UNTIL_MS + 1, "what": "fill", "mode": "test", "rule": "P_pool0", "side": "sell", "lat_ms": 5000}]
    buys, sells = XL.sender_fills(rows)
    assert buys == [1000.0, 1000.0] and sells == [38000.0, 60000.0]
    assert len(XL.SENDER_BUY_MS) >= 3 and len(XL.SENDER_SELL_MS) >= 3
    assert all(RL.CLIP_MS[0] <= x <= RL.CLIP_MS[1] for x in XL.SENDER_BUY_MS + XL.SENDER_SELL_MS)


def test_scenarios_fees_and_the_shared_key():
    sc = XL.scenarios()
    assert set(sc) == set(XL.SCENARIOS) and all(c.tx_lamports() == 1_010_000 for c in sc.values())
    assert isinstance(sc["B"].buy, RL.LogKDE) and sc["B"].buy.points_ms == XL.SENDER_BUY_MS
    assert sc["B"].sell.points_ms == XL.SENDER_SELL_MS
    xs = [sc["C"].latency("P_pool0", MINT + str(i), "buy") for i in range(300)]
    assert 1000 <= min(xs) and max(xs) <= 2000
    strats, costs = XL.books()
    assert len(strats) == len(costs) == 12 and all(s.stake_sol == XL.STAKE_SOL for s in strats)
    assert {sim.base_name(s) for s in strats} == {"P_pool0"}
    assert costs["P_pool0_trail@B"] is sc["B"] or costs["P_pool0_trail@B"] == sc["B"]
    assert XL.LIMITS.max_open == 4 and XL.LIMITS.stake_sol == 0.1


def test_every_book_lands_the_same_migration_at_the_same_moment_and_slots_bind():
    strats, costs = XL.books()
    eng = sim.Engine([], rule_costs=costs)
    pipes = [eng.add_pipe(XL.PeakPipe(eng, [s], P.PaperExecutor(), limits=XL.LIMITS, name=s.name)) for s in strats]
    pools = [Pool(eng, mint=key(150 + i), t=T0 + i * 1_000, slot=60_000 + 1_000 * i) for i in range(5)]
    for k in range(1, 20):
        for i, pl in enumerate(pools):
            pl.trade(T0 + 10_000 + k * 3_000 + i, k % 2 == 0, sol=SOL // 50, base=10 ** 10)
    eng.advance(T0 + 400_000)
    for pipe in pipes:
        pipe.finish(eng.now)
        assert len(pipe.closed) + len(pipe.failed) + len(pipe.pos) == 4      # the fifth migration found 4 open
        assert pipe.skips and pipe.skips[0][1] == "max open positions"
    for sc in XL.SCENARIOS:
        lands = {p.name: sorted([(t["mint"], t["land_ms"]) for t in p.closed]
                                + [(q["mint"], q["land_ms"]) for q in p.pos.values()]) for p in pipes if p.name.endswith(sc)}
        assert len({json.dumps(v) for v in lands.values()}) == 1, lands
        for p in pipes:
            if p.name.endswith(sc):
                assert all(pk["ret"] > -0.1 for pk in p.peaks.values())


def test_a_spike_the_pool_does_not_hold_for_5_s_is_a_peak_but_not_a_held_one_and_gaps_are_marked():
    eng = sim.Engine([], costs=Fixed())
    pipe = eng.add_pipe(XL.PeakPipe(eng, [P.BY_NAME["P_pool0_trail"]], P.PaperExecutor(), limits=XL.LIMITS,
                                    name="P_pool0_trail"))
    pool = Pool(eng)
    pool.to(T0 + 10_000, 4.0)                                  # a spike to 4x ...
    eng.gap(T0 + 11_000, T0 + 11_500)                          # (the stream was down for half a second)
    pool.to(T0 + 12_000, 1.5)                                  # ... gone within 2 s; then 1.5x held
    for k in range(1, 40):
        pool.trade(T0 + 12_000 + k * 3_000, k % 2 == 0, sol=SOL // 100, base=10 ** 9)
    pool.to(T0 + 3_700_000, 1.2)
    pipe.finish(eng.now)
    pk = next(iter(pipe.peaks.values()))
    assert pk["complete"] and pk["ret"] > 2.5 and 0.3 < pk["ret_held"] < 0.6
    e = XL.entries(pipe, eng.gaps)
    assert len(e) == 1 and e[0]["exit_why"] == "trail" and e[0]["gapped"] and e[0]["peak_held"] == pk["ret_held"]
    res = {"split_ms": 0, "entries": {f"{n}@{k}": [] for _, n in XL.VARIANTS for k in XL.SCENARIOS},
           "skips": {f"{n}@{k}": [] for _, n in XL.VARIANTS for k in XL.SCENARIOS}}
    res["entries"]["P_pool0_trail@B"] = e
    assert XL.evaluate(res)["table"]["B"]["X3"]["n"] == 0                       # registered: left out
    assert XL.evaluate(res, keep_gapped=True)["table"]["B"]["X3"]["n"] == 1


# ---------------------------------------------------------------- numbers

def e(ret, mint, h, peak=None, failed=False, real=None):
    return {"ret": ret, "pnl_sol": ret * 0.1, "mint": mint, "signal_ms": T0 + h * 3_600_000,
            "real_ms": real if real is not None else T0 + h * 3_600_000 + 5_000, "exit_why": "x", "hold_s": 5.0,
            "legs": 1, "failed": failed, "symbol": None, "peak": peak}


def test_drawdown_top_share_runners_and_capture():
    assert XL.max_drawdown([0.1, -0.05, -0.1, 0.2, -0.3]) == pytest.approx(0.3)
    assert XL.max_drawdown([-0.1, 0.05]) == pytest.approx(0.1)               # the high starts at 0
    assert XL.max_drawdown([]) == 0.0
    xs = [e(0.3, f"m{i}", i, peak=0.4) for i in range(18)] + [e(2.0, "big", 18, peak=4.0),
                                                              e(-0.2, "dud", 19, peak=0.0)]
    xs.append(e(1.0, "huge", 20, peak=9.0))
    s = XL.stats(xs)
    assert s["n"] == 21 and s["top5_n"] == 2 and s["top5_sol"] == pytest.approx(0.3)
    assert s["top5_share"] == pytest.approx(0.3 / s["pnl_sol"])
    r1, r5 = s["runners"]["1"], s["runners"]["5"]
    assert r1["n"] == 2 and r1["capture"] == pytest.approx(3.0 / 13.0) and r5["n"] == 1
    assert r5["capture"] == pytest.approx(1.0 / 9.0) and math.isfinite(s["band"][0])
    assert XL.stats([e(-0.01, "f", 1, failed=True)])["failed"] == 1


def test_the_paired_difference_uses_only_migrations_both_entered():
    base = [e(0.1, f"m{i}", i) for i in range(12)] + [e(-0.5, "only_base", 3)]
    var = [e(0.2, f"m{i}", i) for i in range(12)] + [e(5.0, "only_var", 4)]
    v = XL.versus(var, base)
    assert v["n"] == 12 and v["diff"] == pytest.approx(0.1) and v["band"][0] == pytest.approx(0.1)
    assert math.isnan(XL.versus(var[:3], base)["band"][0])                          # under 10 hours: n/a


# ---------------------------------------------------------------- end to end

def synth_pools(root, n=40, seed=5):
    """Migrations every 20 minutes; each pool drifts down, sideways, up or runs for 80 minutes."""
    rng = np.random.default_rng(seed)
    w = store.Writer(root)
    slot, tx = 1_000_000, 0
    for k in range(n):
        t = T0 + k * 1_200_000
        mint, dev = key(120 + k % 100) + "p" + str(k), key(200 + k % 7)
        vs, vt, rt, rs = 30 * SOL, 1_073_000_000 * 10 ** 6, C.INITIAL_RT, 0
        slot += 5
        tx += 1
        w.add("creates", {"t": t - 60_000, "slot": slot, "tx": tx, "sig": "s", "mint": mint, "creator": dev,
                          "vs": vs, "vt": vt, "rt": rt, "name": "N", "symbol": f"S{k}", "uri": "https://ipfs.io/ipfs/x"})
        sol = 85 * SOL
        tok = int(vt * sol / (vs + sol))
        slot += 1
        tx += 1
        w.add("trades", {"t": t - 30_000, "slot": slot, "tx": tx, "mint": mint, "buy": True, "sol": sol, "tok": tok,
                         "user": BUYERS[k % 60], "vs": vs + sol, "vt": vt - tok, "rs": sol, "rt": rt - tok, "fb": 95,
                         "cfb": 30, "ix": "buy"})
        slot += 1
        w.add("other", {"kind": "complete", "t": t, "slot": slot, "tx": tx, "mint": mint})
        pb, pq = BASE0, QUOTE0
        drift = [-0.08, 0.0, 0.06, 0.2][k % 4]
        for j in range(400):
            tt = t + j * 12_000
            slot += 1
            tx += 1
            buy = bool(rng.random() < 0.5 + drift)
            if buy:
                q = int(SOL * 0.5 * (1 + rng.random()))
                b = int(pb * q / (pq + q))
            else:
                b = int(pb * 0.006 * (1 + rng.random()))
                q = int(pq * b / (pb + b))
            w.add("amm", {"t": tt, "slot": slot, "tx": tx, "pool": "P" + str(k), "mint": mint, "buy": buy, "base": b,
                          "quote": q, "user": BUYERS[int(rng.integers(0, 60))], "pb": pb, "pq": pq, "lpb": 20,
                          "pfb": 5, "cfb": 5})
            pb, pq = (pb - b, pq + q) if buy else (pb + b, pq - q)
            if j == 0:
                w.add("other", {"kind": "migrate", "t": tt, "slot": slot, "tx": tx, "mint": mint, "pool": "P" + str(k),
                                "sol": 85 * SOL, "tok": BASE0})
    w.flush(T0)


def test_the_replay_runs_end_to_end_and_reports(tmp_path, monkeypatch):
    synth_pools(tmp_path)
    monkeypatch.setattr(store, "base", lambda: tmp_path)
    monkeypatch.setattr("lab.pumpfun_rt.study.WARM_DAYS", 0)
    res = XL.run(root=tmp_path, until_ms=T0 + 3 * 86_400_000, log=lambda *a: None)
    assert set(res["entries"]) == {f"{n}@{k}" for _, n in XL.VARIANTS for k in XL.SCENARIOS}
    assert res["entry_until_ms"] == res["span"][1] - XL.TAIL_MS
    for name, es in res["entries"].items():
        assert es and all(x["signal_ms"] < res["entry_until_ms"] for x in es)
        assert all(x["peak"] is not None for x in es if not x["failed"])          # every hour after landing seen
    assert not res["open_at_end"]
    x0 = {x["mint"]: x for x in res["entries"]["P_pool0@B"]}
    x5 = {x["mint"]: x for x in res["entries"]["P_pool0_half_trail_ext@B"]}
    assert max(x["hold_s"] for x in x5.values() if x["hold_s"]) > 400 >= max(x["hold_s"] for x in x0.values()
                                                                             if x["hold_s"])
    ev = XL.evaluate(res)
    assert set(ev["table"]) == set(XL.SCENARIOS) and set(ev["versus"]["B"]) == {x for x, _ in XL.VARIANTS[1:]}
    lat = {k: RL.describe(c, n=500) for k, c in XL.scenarios().items()}
    live = [{"rule": "P_pool0", "mint": next(iter(x0)), "symbol": "SYM", "ret": "0.1", "exit_why": "take",
             "signal_ms": str(XL.SENDER_FROM_MS + 1)}]
    kept = XL.evaluate(res, keep_gapped=True)
    md = XL.report_md(res, ev, lat, XL.calibrate(dict(res, until_ms=XL.UNTIL_MS), live), kept)
    assert "not registered" in md and "held peak" in md
    assert "Against X0" in md and "\u2014" not in md and "X5" in md
    json.dumps({"eval": ev, "latency": lat}, default=str)
