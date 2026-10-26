"""Y15, P_pool0_wait with a free ride after a fast spike: the four registered strategies and trials, P_pool0_wait's
exits before the +30 %, the partial sale that brings back the stake and the fees, a later +30 % sold whole, the rest's
trail, floor and hard stop, the time stop not touching the rest (also while the partial sale is in flight), a failed
partial sale tried again, the fields only where they belong, every strategy before Y15 trading exactly as before, and
the replay's helpers end to end. No network, no wallet.

Run from research/lab:  python -m pytest tests/test_pumpfun_freeride_y15.py
"""

from __future__ import annotations

import dataclasses
import json
import math

import pytest

from lab.pumpfun_rt import curve as C
from lab.pumpfun_rt import free15 as Y15
from lab.pumpfun_rt import model as M
from lab.pumpfun_rt import pipeline as P
from lab.pumpfun_rt import reallat as RL
from lab.pumpfun_rt import select9 as Y9
from lab.pumpfun_rt import selfeat as SF
from lab.pumpfun_rt import sim
from lab.pumpfun_rt import store
from lab.pumpfun_rt import strategies as S
from test_pumpfun_exit_runners import Pool, closed, engine
from test_pumpfun_rt import T0, Fixed

Y15_NAMES = ["P_pool0_wait_free10", "P_pool0_wait_free30", "P_pool0_wait_free_any", "P_pool0_wait_free10_tight"]
V10, V30, VA, V10T = Y15_NAMES
OLD = P.STRATEGIES[:[s.name for s in P.STRATEGIES].index(V10)]   # every strategy before Y15
LAND = T0 + 1_000                                     # Fixed latency: the buy lands 1 s after the migration
TIME = LAND + 300_000
FEE = Fixed().tx_lamports()
FIELDS = ("free_first_s", "free_ms", "free_part_sol", "free_floor", "free_high", "rest_cost_sol", "rest_pnl_sol",
          "rest_vs_take_sol")


@pytest.fixture(autouse=True)
def small_models(monkeypatch):
    monkeypatch.setitem(M.PARAMS, "n_estimators", 30)


def five():
    eng = engine("P_pool0_wait", *Y15_NAMES)
    return eng, Pool(eng)


def pos(eng, name) -> dict | None:
    got = [p for p in eng.pipes[0].pos.values() if p["rule"] == name]
    return got[0] if got else None


def walk(eng, pool, t, *ratios):
    """The price through the ratios, 10 s apart, each sale landed before the next."""
    for r in ratios:
        pool.to(t, r)
        t += 10_000
        eng.advance(t - 5_000)
    return t


def same(a: dict, b: dict, skip=()) -> bool:
    return {k: v for k, v in a.items() if k not in ("rule", "pid", *skip)} == {
        k: v for k, v in b.items() if k not in ("rule", "pid", *skip)}


# ---------------------------------------------------------------- the registered strategies

def test_the_y15_strategies_and_trials_are_what_the_prereg_says():
    names = [s.name for s in P.STRATEGIES]
    assert names[-10:-6] == Y15_NAMES and [n for _, n in Y15.VARIANTS] == ["P_pool0_wait"] + Y15_NAMES
    base = P.BY_NAME["P_pool0_wait"]
    for n, fr in zip(Y15_NAMES, ((10, 0.20, 1800), (30, 0.20, 1800), (None, 0.20, 1800), (10, 0.10, 1800))):
        s = P.BY_NAME[n]
        assert s.exits.free == fr and dataclasses.replace(s.exits, free=None) == base.exits
        assert (s.family, s.entry, s.p, s.flt, s.stake_sol, s.tp, s.sl, s.hold_s) == (
            "E", "migration", {"delay_s": 0, "wait_pool_s": 5}, {}, 0.1, 0.30, 0.20, 300)
    assert all(s.exits.free is None for s in OLD) and P.Exits(300, 0.2).free is None
    assert base.exits == P.Exits(300, 0.20, ((0.30, 1.0),), dev_sell=False, pull=False)
    assert S.FREE_Y15_TRIALS == 16 == 4 * len(Y15.LIMITS) * len(Y15.LATENCIES)
    assert S.N_TRIALS == 22 + 1 + 12 + 54 + 135 + 140 + 1 + 6 + 5 + 10 + 10 + 4 + 12 + 16 + 12 + 4


# ---------------------------------------------------------------- P_pool0_wait's exits before the +30 %

@pytest.mark.parametrize("ratio,why", [(0.7, "stop"), (1.1, "time")])
def test_the_stop_and_the_time_stop_are_p_pool0_wait_field_for_field(ratio, why):
    eng, pool = five()
    walk(eng, pool, T0 + 20_000, ratio)
    eng.advance(TIME + 1_500)
    a = closed(eng, "P_pool0_wait")
    assert a["exit_why"] == why
    for n in Y15_NAMES:
        b = closed(eng, n)
        assert same(a, b) and not any(k in b for k in FIELDS)


def test_a_later_spike_sells_all_as_p_pool0_wait_where_the_window_is_over():
    eng, pool = five()
    walk(eng, pool, T0 + 20_000, 1.5)                   # the first +30 % 19 s after the landing
    a = closed(eng, "P_pool0_wait")
    assert a["exit_why"] == "take"
    for n in (V10, V10T):
        b = closed(eng, n)
        assert same(a, b, ("free_first_s",)) and b["free_first_s"] == pytest.approx(19.0, abs=0.01)
        assert "free_ms" not in b
    for n in (V30, VA):                                  # inside 30 s and without a window: the free ride
        h = pos(eng, n)
        assert h["free"] is not None and 0 < h["left"] < h["tokens"] and h["legs"] == 1


# ---------------------------------------------------------------- the partial sale and the rest

def test_a_fast_spike_sells_the_stake_and_the_fees_back_and_the_rest_rides_its_trail():
    eng, pool = five()
    t = walk(eng, pool, T0 + 3_000, 1.5)                # +30 % 2 s after the landing
    assert closed(eng, "P_pool0_wait")["exit_why"] == "take"
    for n in Y15_NAMES:
        h = pos(eng, n)
        fr = h["free"]
        assert h["legs"] == 1 and h["exit_why"] is None and not h.get("exiting") and h["step"] == 1
        assert fr["part_l"] - fr["part_fee_l"] >= h["cost_l"] + FEE   # the stake, the buy's fee and the sale's back
        # decided at the first trade over +30 % (the share about (stake + 2 fees) / 1.3), landed a second later higher
        assert fr["part_l"] - fr["part_fee_l"] < (h["cost_l"] + FEE) * 1.5 / 1.3
        assert 0.70 < fr["part_tokens"] / h["tokens"] < 0.80 and fr["keep"] == h["left"]
        assert fr["floor"] > 1.3 and fr["high"] >= fr["floor"]
    t = walk(eng, pool, t, 2.4, 2.1)                    # the rest's high, then -12.5 %: only the tight trail
    x = closed(eng, V10T)
    assert x["exit_why"] == "free_trail" and x["legs"] == 2 and x["rest_pnl_sol"] > 0 and x["free_high"] > 2.0
    for n in (V10, V30, VA):
        assert pos(eng, n)["left"] > 0
    walk(eng, pool, t, 1.85)                            # -23 % from the high: over the floor, under the 20 % trail
    for n in (V10, V30, VA):
        x = closed(eng, n)
        assert x["exit_why"] == "free_trail" and x["legs"] == 2 and x["free_first_s"] == pytest.approx(2.0, abs=0.01)
        assert x["free_ms"] == pytest.approx(LAND + x["free_first_s"] * 1000) and x["rest_vs_take_sol"] > 0 and x["rest_pnl_sol"] > 0
        assert x["pnl_sol"] == pytest.approx(x["proceeds_sol"] - 0.1 - 3 * FEE / C.LAMPORTS, abs=1e-9)
        assert x["free_part_sol"] + x["rest_pnl_sol"] + x["rest_cost_sol"] == pytest.approx(
            x["proceeds_sol"] - 2 * FEE / C.LAMPORTS, abs=1e-9)
        assert x["ret"] > closed(eng, "P_pool0_wait")["ret"]


def test_the_rest_goes_at_the_partial_sales_price():
    eng, pool = five()
    t = walk(eng, pool, T0 + 3_000, 1.5)
    walk(eng, pool, t, 1.45)                            # under the partial sale's price, over every trail
    for n in Y15_NAMES:
        x = closed(eng, n)
        assert x["exit_why"] == "free_floor" and x["legs"] == 2 and x["rest_vs_take_sol"] < 0
        assert x["pnl_sol"] > 0                         # the stake came back: the trade is still a gain


def test_the_time_stop_leaves_the_rest_and_the_hard_stop_sells_it():
    eng, pool = five()
    walk(eng, pool, T0 + 3_000, 1.5)
    eng.advance(TIME + 1_500)
    for n in Y15_NAMES:
        assert pos(eng, n)["left"] > 0 and pos(eng, n)["legs"] == 1
    eng.advance(LAND + 1_800_000 + 1_500)
    for n in Y15_NAMES:
        x = closed(eng, n)
        assert x["exit_why"] == "free_time" and x["exit_signal_ms"] == LAND + 1_800_000 and x["legs"] == 2


def test_the_time_stop_while_the_partial_sale_is_in_flight_leaves_the_rest():
    eng, pool = engine(VA), None
    pool = Pool(eng)
    pool.to(TIME - 500, 1.5)                           # the +30 % half a second before the time stop
    eng.advance(TIME + 5_000)                           # the partial sale lands 500 ms after it
    h = pos(eng, VA)
    assert h["free"] is not None and h["left"] > 0 and "time_due" not in h and h["legs"] == 1
    walk(eng, pool, TIME + 10_000, 1.4)
    assert closed(eng, VA)["exit_why"] == "free_floor"


def held_back(eng):
    """The paper executor without its sales: each is noted and lands only when the test says so."""
    pipe = eng.pipes[0]
    sent = []
    pipe.exec.sell = lambda o: sent.append(o)
    return pipe, sent


def test_a_failed_partial_sale_is_tried_again_and_keeps_its_first_decision():
    eng = engine(V10)
    pool = Pool(eng)
    pipe, sent = held_back(eng)
    pool.to(T0 + 3_000, 1.5)
    h = pos(eng, V10)
    assert [o.why for o in sent] == ["free_part"] and h["free_part"] == sent[0].tokens and h["step"] == 1
    first = h["free_first_ms"]
    pool.to(T0 + 20_000, 1.1)                          # under +30 % when the failure comes back
    pipe.sell_failed(h["pid"], T0 + 20_500, "under the floor", FEE)
    assert h["step"] == 0 and "free_part" not in h and "free" not in h and len(sent) == 1
    pool.to(T0 + 30_000, 1.5)                          # 29 s after the landing: the decision of 2 s stands
    assert [o.why for o in sent] == ["free_part"] * 2 and h["free_first_ms"] == first
    assert sent[1].tokens < h["left"]


def test_a_failed_partial_sale_leaves_the_time_stop_as_before():
    eng = engine(V10)
    pool = Pool(eng)
    pipe, sent = held_back(eng)
    pool.to(T0 + 3_000, 1.5)
    h = pos(eng, V10)
    pool.to(T0 + 20_000, 1.1)
    pipe.sell_failed(h["pid"], T0 + 20_500, "under the floor", FEE)
    pipe.exec.sell = P.PaperExecutor.sell.__get__(pipe.exec)
    eng.advance(TIME + 1_500)
    x = closed(eng, V10)
    assert x["exit_why"] == "time" and x["legs"] == 1 and "free_ms" not in x
    assert x["free_first_s"] == pytest.approx(2.0, abs=0.01)


# ---------------------------------------------------------------- nothing before Y15 changes

def test_every_strategy_before_y15_trades_exactly_as_before(tmp_path, monkeypatch):
    """One shared paper book of every strategy before Y15 on a synthetic record, without and with the Y15 books: the
    closed trades, failed buys and skips of the old strategies are the same field for field (the pid aside)."""
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
    assert [t for t in b.closed if t["rule"] in Y15_NAMES]
    assert not any(k in t for t in b.closed if t["rule"] in old for k in FIELDS)


# ---------------------------------------------------------------- the replay's helpers

def test_books_latency_and_limits():
    strats, costs = Y15.books()
    assert len(strats) == len(costs) == 20 and all(s.stake_sol == 0.1 for s, _ in strats)
    assert {sim.base_name(s) for s, _ in strats} == {"P_pool0"}
    assert [s.name for s, _ in strats][:5] == [f"{n}@A@L25" for _, n in Y15.VARIANTS]
    assert {lim.max_daily_loss_sol for _, lim in strats} == {0.25, 1.0}
    a, b = costs["P_pool0_wait_free10@A@L100"], costs["P_pool0_wait_free10@B@L100"]
    assert type(a) is C.Costs and (a.lat_median_ms, a.lat_lo_ms, a.lat_hi_ms) == (
        C.Costs().lat_median_ms, C.Costs().lat_lo_ms, C.Costs().lat_hi_ms)
    assert b.buy.points_ms == Y9.SENDER_BUY_MS and b.sell.points_ms == Y9.SENDER_SELL_MS
    assert a.tx_lamports() == b.tx_lamports() == 1_005_000
    assert Y15.TAIL_MS >= 1_800_000 + 5_000 + 2 * RL.CLIP_MS[1]


def e(mint, ret, why="take", first=None, free=None, rest=None, gave=None, failed=False):
    return {"mint": mint, "signal_ms": T0, "ret": ret, "pnl_sol": ret * 0.1, "exit_why": why, "failed": failed,
            "free_first_s": first, "free_ms": free, "free_part_sol": 0.102 if free else None,
            "rest_cost_sol": 0.022 if free else None, "rest_pnl_sol": rest, "rest_vs_take_sol": gave}


def test_ride_stats():
    base = [e("a", 0.28), e("b", 0.27), e("c", -0.2, "stop"), e("d", 0.29)]
    xs = [e("a", 0.40, "free_trail", 2.0, T0, 0.011, 0.005), e("b", 0.25, "free_floor", 5.0, T0, -0.0022, -0.001),
          e("d", 0.29, "take", 40.0), e("x", 0.10, "free_time", 1.0, T0, 0.0, 0.0), e("c", -0.2, "stop"),
          e("f", -0.01, "failed buy", failed=True)]
    f = Y15.ride_stats(xs, base)
    assert (f["closed"], f["hit30"], f["n"], f["paired"]) == (5, 4, 3, 2) and f["share"] == pytest.approx(0.6)
    assert f["first_s"] == pytest.approx(3.5) and f["rest_best"] == pytest.approx(0.5)
    assert f["rest_median"] == pytest.approx(0.0) and f["rest_worst"] == pytest.approx(-0.1)
    assert f["rest_up"] == pytest.approx(1 / 3) and f["vs_take_sol"] == pytest.approx(0.004)
    assert f["x0_mean"] == pytest.approx(0.275) and f["better"] == pytest.approx(0.5)
    assert f["exits"] == {"free_floor": 1, "free_time": 1, "free_trail": 1} and f["x0_exits"] == {"take": 2}
    assert Y15.ride_stats([e("d", 0.29, "take", 40.0)], base) == {"closed": 1, "hit30": 1, "n": 0, "share": 0.0,
                                                                   "first_s": 40.0}


def test_the_replay_runs_end_to_end_and_reports(tmp_path, monkeypatch):
    from test_pumpfun_select_y9 import market, write
    write(tmp_path, market(n=24, every_ms=1_500_000))
    monkeypatch.setattr(store, "base", lambda: tmp_path)
    monkeypatch.setattr("lab.pumpfun_rt.study.WARM_DAYS", 0)
    res = Y15.run(root=tmp_path, until_ms=T0 + 3 * 86_400_000, log=lambda *a: None)
    assert set(res["entries"]) == {f"{n}@{a}@{k}" for _, n in Y15.VARIANTS for a in Y15.LATENCIES
                                   for k in Y15.LIMITS}
    assert res["entry_until_ms"] == res["span"][1] - Y15.TAIL_MS and not res["open_at_end"]
    for a in Y15.LATENCIES:
        for k in Y15.LIMITS:
            assert res["entries"][f"P_pool0_wait@{a}@{k}"]
            assert all(x["free_ms"] is None for x in res["entries"][f"P_pool0_wait@{a}@{k}"])
    ev = Y15.evaluate(res)
    assert set(ev["better"]) == {"A", "B"} and set(ev["better"]["B"]) == {"V10", "V30", "VA", "V10T"}
    assert set(ev["versus"]) == {"A@L25", "A@L100", "B@L25", "B@L100"}
    dropped = Y15.evaluate(res, keep_gapped=False)
    lat = {k: RL.describe(c, n=500) for k, c in Y15.latencies().items()}
    md = Y15.report_md(res, ev, dropped, lat)
    assert "measured live latency" in md and "spike rule fired" in md and "\u2014" not in md and "V10T" in md
    json.dumps({"eval": ev, "latency": lat}, default=str)
    assert not math.isnan(ev["table"]["B@L100"]["V10"].get("mean", 0.0))
