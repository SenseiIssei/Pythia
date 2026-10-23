"""Y12, P_pool0_wait with a ratcheting profit floor: the three registered strategies and trials, the take profit, the
stop and the time stop exactly P_pool0_wait's, no floor before its arm, the first and the second floor (the higher
arm decides), the half variant's two sales, a failed floor sale sent again, the floor's fields only where it fired,
every strategy before Y12 trading exactly as before, and the replay's helpers end to end. No network, no wallet.

Run from research/lab:  python -m pytest tests/test_pumpfun_lock_y12.py
"""

from __future__ import annotations

import dataclasses
import json
import math

import pytest

from lab.pumpfun_rt import curve as C
from lab.pumpfun_rt import lock12 as Y12
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

Y12_NAMES = ["P_pool0_wait_lock", "P_pool0_wait_lock_tight", "P_pool0_wait_lock_half"]
F1, F2, F3 = Y12_NAMES
OLD = P.STRATEGIES[:[s.name for s in P.STRATEGIES].index(F1)]   # every strategy before Y12
LAND = T0 + 1_000                                     # Fixed latency: the buy lands 1 s after the migration
TIME = LAND + 300_000
# Pool.to's ratio is over the opening price; the position's mark (its sale after the pool's fee over its cost) is
# about 0.99 x the ratio here: 1.12 marks about +10.9 %, 1.03 about +2.0 %.


@pytest.fixture(autouse=True)
def small_models(monkeypatch):
    monkeypatch.setitem(M.PARAMS, "n_estimators", 30)


def four():
    eng = engine("P_pool0_wait", *Y12_NAMES)
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


# ---------------------------------------------------------------- the registered strategies

def test_the_y12_strategies_and_trials_are_what_the_prereg_says():
    names = [s.name for s in P.STRATEGIES]
    assert names[-8:-5] == Y12_NAMES and [n for _, n in Y12.VARIANTS] == ["P_pool0_wait"] + Y12_NAMES
    base = P.BY_NAME["P_pool0_wait"]
    locks = (((0.10, 0.02, 1.0), (0.20, 0.10, 1.0)), ((0.08, 0.03, 1.0), (0.15, 0.09, 1.0)),
             ((0.10, 0.02, 0.5), (0.20, 0.10, 1.0)))
    for n, lk in zip(Y12_NAMES, locks):
        s = P.BY_NAME[n]
        assert s.exits.lock == lk and dataclasses.replace(s.exits, lock=None) == base.exits
        assert (s.family, s.entry, s.p, s.flt, s.stake_sol, s.tp, s.sl, s.hold_s) == (
            "E", "migration", {"delay_s": 0, "wait_pool_s": 5}, {}, 0.1, 0.30, 0.20, 300)
        assert [a for a, _, _ in lk] == sorted(a for a, _, _ in lk) and all(f < a for a, f, _ in lk)
    assert all(s.exits.lock is None for s in OLD) and P.Exits(300, 0.2).lock is None
    assert base.exits == P.Exits(300, 0.20, ((0.30, 1.0),), dev_sell=False, pull=False)
    assert S.LOCK_Y12_TRIALS == 12 == 3 * len(Y12.LIMITS) * len(Y12.LATENCIES)
    assert S.N_TRIALS == 22 + 1 + 12 + 54 + 135 + 140 + 1 + 6 + 5 + 10 + 10 + 4 + 12 + 16


# ---------------------------------------------------------------- P_pool0_wait's exits stay

@pytest.mark.parametrize("ratio,why", [(1.5, "take"), (0.7, "stop")])
def test_a_straight_take_profit_or_stop_is_p_pool0_wait_field_for_field(ratio, why):
    eng, pool = four()
    pool.to(T0 + 60_000, ratio)
    eng.advance(T0 + 70_000)
    a = closed(eng, "P_pool0_wait")
    assert a["exit_why"] == why and "lock_ms" not in a
    for n in Y12_NAMES:
        b = closed(eng, n)
        assert {k: v for k, v in a.items() if k not in ("rule", "pid")} == {
            k: v for k, v in b.items() if k not in ("rule", "pid")}


def test_no_floor_before_its_arm_and_the_time_stop_stays():
    eng, pool = four()
    walk(eng, pool, T0 + 20_000, 1.07, 0.95)            # about +6 %, under every arm, then back under the entry
    eng.advance(TIME + 1_500)
    a = closed(eng, "P_pool0_wait")
    assert a["exit_why"] == "time" and a["exit_signal_ms"] == TIME
    for n in Y12_NAMES:
        b = closed(eng, n)
        assert "lock_ms" not in b and {k: v for k, v in a.items() if k not in ("rule", "pid")} == {
            k: v for k, v in b.items() if k not in ("rule", "pid")}


# ---------------------------------------------------------------- the floors

def test_the_first_floor_sells_all_and_the_half_variant_half():
    eng, pool = four()
    t = walk(eng, pool, T0 + 20_000, 1.12, 1.05)         # armed (about +10.9 %), back to about +4 %: over both floors
    for n in Y12_NAMES:
        assert pos(eng, n)["left"] == pos(eng, n)["tokens"] and "lock_ms" not in pos(eng, n)
    walk(eng, pool, t, 1.025)                            # about +1.5 %: under +2 % (F1, F3) and +3 % (F2)
    for n in (F1, F2):
        x = closed(eng, n)
        assert x["exit_why"] == "lock" and x["lock_sales"] == 1 and x["legs"] == 1 and x["peak"] > 1.10
        assert x["lock_ms"] == x["exit_signal_ms"] and x["exit_signal_ms"] < TIME
    assert closed(eng, F2)["exit_signal_ms"] < closed(eng, F1)["exit_signal_ms"]   # +3 % comes first on the way down
    h = pos(eng, F3)
    assert h["left"] == h["tokens"] - (h["tokens"] - int(h["tokens"] * 0.5)) and h["legs"] == 1
    assert h["lock_sales"] == 1 and h["exit_why"] is None and not h.get("exiting") and not h["selling"]
    assert pos(eng, "P_pool0_wait")["left"] == pos(eng, "P_pool0_wait")["tokens"]
    eng.advance(TIME + 1_500)                            # the half variant's rest: the time stop as before
    x = closed(eng, F3)
    assert x["exit_why"] == "time" and x["legs"] == 2 and x["lock_sales"] == 1
    assert closed(eng, "P_pool0_wait")["exit_why"] == "time" and "lock_ms" not in closed(eng, "P_pool0_wait")


def test_the_second_floor_takes_over_once_its_arm_is_reached():
    eng, pool = four()
    t = walk(eng, pool, T0 + 20_000, 1.23, 1.13)         # about +21.8 %, back to about +11.9 %: over every floor
    assert all(pos(eng, n) is not None for n in Y12_NAMES)
    t = walk(eng, pool, t, 1.105)                        # about +9.4 %: under F1's and F3's +10 %, over F2's +9 %
    for n in (F1, F3):
        x = closed(eng, n)
        assert x["exit_why"] == "lock" and x["lock_sales"] == 1 and x["legs"] == 1 and x["ret"] > 0.05
    assert pos(eng, F2)["left"] > 0
    walk(eng, pool, t, 1.09)                             # about +7.9 %: under +9 %
    assert closed(eng, F2)["exit_why"] == "lock"
    assert pos(eng, "P_pool0_wait")["left"] > 0          # P_pool0_wait rides on to its time stop


def test_the_half_variant_sells_the_rest_at_the_second_floor():
    eng, pool = four()
    t = walk(eng, pool, T0 + 20_000, 1.12, 1.0)          # the first floor: half sold
    h = pos(eng, F3)
    assert h["lock_sales"] == 1 and h["left"] < h["tokens"]
    t = walk(eng, pool, t, 1.23)                         # the rest climbs past +20 %
    assert pos(eng, F3)["left"] == h["left"]             # the first floor does not sell twice
    walk(eng, pool, t, 1.105)
    x = closed(eng, F3)
    assert x["exit_why"] == "lock" and x["lock_sales"] == 2 and x["legs"] == 2
    fees = 3 * Fixed().tx_lamports() / C.LAMPORTS        # the buy and two sales
    assert x["pnl_sol"] == pytest.approx(x["proceeds_sol"] - 0.1 - fees, abs=1e-9)


def test_the_stop_still_applies_after_the_half():
    eng, pool = four()
    t = walk(eng, pool, T0 + 20_000, 1.12, 1.0)
    walk(eng, pool, t, 0.75)
    x = closed(eng, F3)
    assert x["exit_why"] == "stop" and x["lock_sales"] == 1 and x["legs"] == 2


def test_a_failed_floor_sale_is_sent_again():
    eng, pool = four()
    walk(eng, pool, T0 + 20_000, 1.12)
    pool.to(T0 + 40_000, 1.0)
    eng.advance(T0 + 40_100)                             # the floors' sales are in flight
    pipe = eng.pipes[0]
    sent = []
    real = pipe._sell
    pipe._sell = lambda p_, t, a, f, w: (sent.append((p_["rule"], a, f, w)), real(p_, t, a, f, w))
    h, f1 = pos(eng, F3), pos(eng, F1)
    amount = h["lock_part"]
    pipe.sell_failed(h["pid"], T0 + 40_500, "dropped", Fixed().tx_lamports())
    pipe.sell_failed(f1["pid"], T0 + 40_500, "dropped", Fixed().tx_lamports())
    assert sent == [(F3, amount, 0, "lock_part"), (F1, f1["tokens"], 0, "lock")]
    assert h["lock_part"] == amount and h["step"] == 0 and h["lock_sales"] == 1


# ---------------------------------------------------------------- nothing before Y12 changes

def test_every_strategy_before_y12_trades_exactly_as_before(tmp_path, monkeypatch):
    """One shared paper book of every strategy before Y12 on a synthetic record, without and with the Y12 books: the
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
    assert [t for t in b.closed if t["rule"] in Y12_NAMES]
    assert not any("lock_ms" in t for t in b.closed if t["rule"] in old)


# ---------------------------------------------------------------- the replay's helpers

def test_books_latency_and_limits():
    strats, costs = Y12.books()
    assert len(strats) == len(costs) == 16 and all(s.stake_sol == 0.1 for s, _ in strats)
    assert {sim.base_name(s) for s, _ in strats} == {"P_pool0"}
    assert [s.name for s, _ in strats][:4] == [f"{n}@A@L25" for _, n in Y12.VARIANTS]
    assert {lim.max_daily_loss_sol for _, lim in strats} == {0.25, 1.0}
    a, b = costs["P_pool0_wait_lock@A@L100"], costs["P_pool0_wait_lock@B@L100"]
    assert type(a) is C.Costs and (a.lat_median_ms, a.lat_lo_ms, a.lat_hi_ms) == (
        C.Costs().lat_median_ms, C.Costs().lat_lo_ms, C.Costs().lat_hi_ms)
    assert b.buy.points_ms == Y9.SENDER_BUY_MS and b.sell.points_ms == Y9.SENDER_SELL_MS
    assert a.tx_lamports() == b.tx_lamports() == 1_005_000
    assert Y12.TAIL_MS >= 300_000 + 5_000 + 2 * RL.CLIP_MS[1]


def e(mint, ret, why="time", lock=None, failed=False, t=T0):
    return {"mint": mint, "signal_ms": t, "ret": ret, "pnl_sol": ret * 0.1, "exit_why": why, "failed": failed,
            "lock_ms": lock}


def test_floor_stats():
    base = [e("a", -0.20, "stop"), e("b", 0.25, "time"), e("c", 0.30, "take"), e("d", 0.0)]
    xs = [e("a", 0.01, "lock", T0), e("b", 0.09, "lock", T0), e("c", 0.30, "take"), e("x", 0.02, "lock", T0),
          e("f", -0.01, failed=True)]
    f = Y12.floor_stats(xs, base)
    assert f["n"] == 3 and f["closed"] == 4 and f["share"] == pytest.approx(0.75) and f["paired"] == 2
    assert f["x0_mean"] == pytest.approx(0.025) and f["better"] == pytest.approx(0.5)
    assert f["x0_exits"] == {"stop": 1, "time": 1} and f["exits"] == {"lock": 3}
    assert f["pnl_sol"] == pytest.approx(0.012) and f["lock_pnl_sol"] == pytest.approx(0.010)
    assert Y12.floor_stats([e("c", 0.3, "take")], base) == {"n": 0, "closed": 1}


def test_the_replay_runs_end_to_end_and_reports(tmp_path, monkeypatch):
    from test_pumpfun_select_y9 import market, write
    write(tmp_path, market(n=24, every_ms=1_500_000))
    monkeypatch.setattr(store, "base", lambda: tmp_path)
    monkeypatch.setattr("lab.pumpfun_rt.study.WARM_DAYS", 0)
    res = Y12.run(root=tmp_path, until_ms=T0 + 3 * 86_400_000, log=lambda *a: None)
    assert set(res["entries"]) == {f"{n}@{a}@{k}" for _, n in Y12.VARIANTS for a in Y12.LATENCIES
                                   for k in Y12.LIMITS}
    assert res["entry_until_ms"] == res["span"][1] - Y12.TAIL_MS and not res["open_at_end"]
    for a in Y12.LATENCIES:
        for k in Y12.LIMITS:
            assert res["entries"][f"P_pool0_wait@{a}@{k}"]
            assert all(x["lock_ms"] is None for x in res["entries"][f"P_pool0_wait@{a}@{k}"])
    ev = Y12.evaluate(res)
    assert set(ev["better"]) == {"A", "B"} and set(ev["better"]["B"]) == {"F1", "F2", "F3"}
    assert set(ev["versus"]) == {"A@L25", "A@L100", "B@L25", "B@L100"}
    dropped = Y12.evaluate(res, keep_gapped=False)
    lat = {k: RL.describe(c, n=500) for k, c in Y12.latencies().items()}
    assert lat["A"]["buy"]["p50"] == pytest.approx(1000, rel=0.05) and lat["B"]["buy"]["p50"] > 5000
    md = Y12.report_md(res, ev, dropped, lat)
    assert "measured live latency" in md and "floor fired" in md and "\u2014" not in md and "F3" in md
    json.dumps({"eval": ev, "latency": lat}, default=str)
    assert not math.isnan(ev["table"]["B@L100"]["F1"].get("mean", 0.0))
