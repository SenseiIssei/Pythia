"""Y8, P_pool0 with a -10 % stop, a sell-pressure exit and an entry that waits for the pool: the five registered
strategies, the press exit (fires, does not fire, counts only trades since the landing, off by default), the wait
entry (enters at the pool's first trade within 5 s, skips after, changes nothing where the state is known or the
parameter is absent), and the replay's helpers (books, latency points, stops, the hour-paired difference, the run
end to end). No network, no wallet.

Run from research/lab:  python -m pytest tests/test_pumpfun_exits_y8.py
"""

from __future__ import annotations

import dataclasses
import json
import math

import numpy as np
import pytest

from lab.pumpfun_rt import exitlab as XL
from lab.pumpfun_rt import exits8 as X8
from lab.pumpfun_rt import model as M
from lab.pumpfun_rt import pipeline as P
from lab.pumpfun_rt import reallat as RL
from lab.pumpfun_rt import sim
from lab.pumpfun_rt import store
from lab.pumpfun_rt import strategies as S
from test_pumpfun_exit_runners import BASE0, QUOTE0, Pool, closed, e, engine
from test_pumpfun_rt import BUYERS, MINT, POOL, SOL, T0, Curve, Fixed


@pytest.fixture(autouse=True)
def small_models(monkeypatch):
    monkeypatch.setitem(M.PARAMS, "n_estimators", 30)


class LatePool(Pool):
    """A migration whose pool has no trade yet: its state comes with the first trade (`open`)."""

    def __init__(self, eng: sim.Engine, mint=MINT, t=T0, slot=50_000):
        self.eng, self.mint, self.slot = eng, mint, slot
        Curve(eng, mint=mint, t=t - 120_000, slot=slot - 40_000)
        eng.complete(t, mint)
        self.pb, self.pq = BASE0, QUOTE0
        eng.migrate(t, mint, POOL, 85 * SOL, BASE0)

    def open(self, t):
        self.trade(t, True, SOL // 1000)


# ---------------------------------------------------------------- the registered strategies

def test_the_y8_strategies_are_what_the_prereg_says():
    names = [n for _, n in X8.VARIANTS]
    all_names = [s.name for s in P.STRATEGIES]
    i = all_names.index(names[1])
    assert names[0] == "P_pool0" and all_names[i:i + 5] == names[1:]
    base = P.BY_NAME["P_pool0"]
    for n in names[1:]:
        s = P.BY_NAME[n]
        assert (s.family, s.entry, s.flt, s.stake_sol) == ("E", "migration", {}, 0.1)
        assert s.p == ({"delay_s": 0, "wait_pool_s": 5} if "wait" in n else {"delay_s": 0})
        assert (s.exits.ladder, s.exits.time_s, s.exits.dev_sell, s.exits.pull) == (((0.30, 1.0),), 300, False, False)
        assert s.exits.sl == (0.10 if n.endswith("sl10") else 0.20) and s.tp == 0.30
        assert s.exits.press_exit == ((5.0, 0.08) if n.endswith("press") else None)
        assert dataclasses.replace(s.exits, sl=0.20, press_exit=None) == base.exits
    for s in P.STRATEGIES:                                     # nothing else has the new exit or the wait (Y11's
        if s.name not in names[1:] and s.exits.runner is None and s.exits.lock is None and s.exits.free is None:
            assert s.exits.press_exit is None and "wait_pool_s" not in s.p      # Y11, Y12, Y15: P_pool0_wait + one exit


def test_the_trials_are_counted():
    assert S.EXITS_Y8_TRIALS == 5 == len(X8.VARIANTS) - 1
    assert S.N_TRIALS == 22 + 1 + 12 + 54 + 135 + 140 + 1 + 6 + 5 + 10 + 10 + 4 + 12 + 16


# ---------------------------------------------------------------- the press exit

def test_the_press_exit_fires_on_a_net_outflow_over_8_percent_within_5_s():
    eng = engine("P_pool0", "P_pool0_press")
    pool = Pool(eng)
    pool.trade(T0 + 5_000, True, sol=SOL // 10)                # after both landed (1 s)
    ref = eng.tokens[MINT].pq
    k = pool.pb * pool.pq
    pool.trade(T0 + 6_000, False, base=int(k / (pool.pq - 0.045 * ref) - pool.pb), user=BUYERS[30])
    eng.advance(T0 + 7_000)
    assert not eng.closed                                      # 4.5 %: nothing yet
    pool.trade(T0 + 8_000, False, base=int(k / (pool.pq - 0.04 * ref) - pool.pb), user=BUYERS[31])
    eng.advance(T0 + 12_000)
    t = closed(eng, "P_pool0_press")
    assert t["exit_why"] == "press" and t["exit_signal_ms"] == T0 + 8_000 and t["ret"] < 0
    assert [x["rule"] for x in eng.closed] == ["P_pool0_press"] and len(eng.pipes[0].pos) == 1   # no stop for X0


def test_the_press_exit_does_not_fire_spread_over_more_than_5_s_or_on_trades_before_the_landing():
    eng = engine("P_pool0_press")
    pool = Pool(eng)
    k = pool.pb * pool.pq
    pool.trade(T0 + 500, False, base=int(k / (pool.pq * 0.95) - pool.pb), user=BUYERS[30])   # before the landing
    eng.advance(T0 + 1_500)
    ref = eng.pipes[0].pos[next(iter(eng.pipes[0].pos))]["entry_pq"]
    assert ref == eng.tokens[MINT].pq
    for i in range(3):                                         # 3 sales of 3 % each, 3 s apart: 6 % in any 5 s
        k = pool.pb * pool.pq
        pool.trade(T0 + 2_000 + 3_000 * i, False, base=int(k / (pool.pq - 0.03 * ref) - pool.pb), user=BUYERS[31 + i])
    pool.trade(T0 + 9_000, True, sol=SOL // 10)
    eng.advance(T0 + 12_000)
    assert not eng.closed and eng.pipes[0].pos
    assert not P.press_trigger(eng.tokens[MINT], T0 + 8_000, T0 + 1_000, 5.0, 0.08, ref)
    assert P.press_trigger(eng.tokens[MINT], T0 + 8_000, T0 + 1_000, 10.0, 0.08, ref)   # the 9 % over 10 s
    assert not P.press_trigger(eng.tokens[MINT], T0 + 8_000, T0 + 1_000, 5.0, 0.08, 0)   # no reference: never


def test_without_the_field_nothing_changes():
    assert P.Exits(300, 0.2).press_exit is None
    eng = engine("P_pool0")
    pool = Pool(eng)
    eng.advance(T0 + 1_500)
    assert "entry_pq" not in next(iter(eng.pipes[0].pos.values()))
    k = pool.pb * pool.pq
    pool.trade(T0 + 3_000, False, base=int(k / (pool.pq * 0.915) - pool.pb), user=BUYERS[30])   # 8.5 % out
    eng.advance(T0 + 400_000)
    assert closed(eng, "P_pool0")["exit_why"] == "time" and not eng.pipes[0].waiting


# ---------------------------------------------------------------- the wait entry

def test_the_wait_enters_at_the_pools_first_trade_within_5_s():
    eng = engine("P_pool0", "P_pool0_wait", "P_pool0_wait_press", "P_pool0_wait_sl10")
    pool = LatePool(eng)
    eng.advance(T0 + 1_000)
    assert eng.skipped[("P_pool0", "no pool state")] == 1 and set(eng.pipes[0].waiting[MINT]) == {
        "P_pool0_wait", "P_pool0_wait_press", "P_pool0_wait_sl10"}
    pool.open(T0 + 3_000)
    eng.advance(T0 + 3_500)
    pos = eng.pipes[0].pos.values()
    assert {p["rule"] for p in pos} == {"P_pool0_wait", "P_pool0_wait_press", "P_pool0_wait_sl10"}
    assert all(p["signal_ms"] == T0 + 3_000 for p in pos) and not eng.pipes[0].waiting
    eng.advance(T0 + 10_000)
    assert not any(n == "no pool state" and r != "P_pool0" for r, n in eng.skipped)


def test_the_wait_skips_after_5_s():
    eng = engine("P_pool0", "P_pool0_wait")
    pool = LatePool(eng)
    eng.advance(T0 + 5_500)
    assert eng.skipped[("P_pool0_wait", "no pool state")] == 1 and not eng.pipes[0].waiting
    pool.open(T0 + 6_000)
    eng.advance(T0 + 400_000)
    assert not eng.closed and not eng.failed and not eng.pipes[0].pos


def test_with_the_state_known_the_wait_enters_at_the_migration_as_p_pool0():
    eng = engine("P_pool0", "P_pool0_wait")
    pool = Pool(eng)
    pool.to(T0 + 5_000, 1.5)
    eng.advance(T0 + 10_000)
    a, b = closed(eng, "P_pool0"), closed(eng, "P_pool0_wait")
    assert a["signal_ms"] == b["signal_ms"] == T0 and {k: v for k, v in a.items() if k not in ("rule", "pid")} == {
        k: v for k, v in b.items() if k not in ("rule", "pid")}


def test_the_peak_book_notes_a_wait_in_vain_as_one_skip():
    eng = sim.Engine([], costs=Fixed())
    pipe = eng.add_pipe(XL.PeakPipe(eng, [P.BY_NAME["P_pool0_wait"]], P.PaperExecutor(), limits=X8.LIMITS,
                                    name="P_pool0_wait"))
    LatePool(eng)
    eng.advance(T0 + 2_000)
    assert pipe.skips == []                                     # still waiting: not a skip
    eng.advance(T0 + 6_000)
    assert pipe.skips == [(T0 + 5_000, "no pool state")]


# ---------------------------------------------------------------- the replay's helpers

def test_books_latency_fees_and_limits():
    strats, costs = X8.books()
    assert len(strats) == len(costs) == 12 and all(s.stake_sol == 0.1 for s in strats)
    assert {sim.base_name(s) for s in strats} == {"P_pool0"}
    assert strats[3].p["wait_pool_s"] == 5 and strats[3].name == "P_pool0_wait@B"
    sc = X8.scenarios()
    assert all(c.tx_lamports() == 1_005_000 for c in sc.values())
    assert sc["B"].buy.points_ms == X8.SENDER_BUY_MS and sc["B"].sell.points_ms == X8.SENDER_SELL_MS
    assert len(X8.SENDER_BUY_MS) == len(X8.SENDER_SELL_MS) == 26
    assert all(RL.CLIP_MS[0] <= x <= RL.CLIP_MS[1] for x in X8.SENDER_BUY_MS + X8.SENDER_SELL_MS)
    assert X8.LIMITS == P.Limits(0.1, 4, 0.6, 0.25) and X8.LIMITS.capped() == X8.LIMITS


def test_stops_and_the_hour_paired_difference_over_all_entries():
    xs = [dict(e(-0.3, "a", 1), exit_why="stop"), dict(e(-0.2, "b", 2), exit_why="stop"), e(0.3, "c", 3)]
    st = X8.stops(xs, 0.10)
    assert st["n"] == 2 and st["mean"] == pytest.approx(-0.25) and st["below"] == pytest.approx(-0.15)
    assert X8.stops([e(0.1, "x", 1)], 0.2)["mean"] is None
    base = [e(0.0, f"m{i}", i) for i in range(12)]
    var = [e(0.1, f"m{i}", i) for i in range(12)] + [e(0.1, "extra", 5)]   # an entry X0 did not take counts
    v = X8.paired(var, base)
    assert v["diff"] == pytest.approx(0.1) and v["band"][0] == pytest.approx(0.1)
    assert math.isnan(X8.paired(var[:4], base)["band"][0])


def synth_late(root, n=24, seed=4):
    """Migrations every 25 minutes whose first pool trade comes 1 s before (the state known at the migration) or
    1, 2, 3, 5, 6, 7 or 8 s after the migration; slots follow the time."""
    rng = np.random.default_rng(seed)
    w = store.Writer(root)
    tx = 50_000
    from lab.pumpfun_rt import curve as C
    from test_pumpfun_rt import key
    for k in range(n):
        t = T0 + 300_000 + k * 1_500_000
        mint, dev = key(60 + k % 40) + "w" + str(k), key(200 + k % 7)
        vs, vt, rt = 30 * SOL, 1_073_000_000 * 10 ** 6, C.INITIAL_RT
        tx += 1
        w.add("creates", {"t": t - 60_000, "slot": slot_of(t - 60_000), "tx": tx, "sig": "s", "mint": mint,
                          "creator": dev, "vs": vs, "vt": vt, "rt": rt, "name": "N", "symbol": f"W{k}",
                          "uri": "https://ipfs.io/ipfs/x"})
        sol = 85 * SOL
        tok = int(vt * sol / (vs + sol))
        tx += 1
        w.add("trades", {"t": t - 30_000, "slot": slot_of(t - 30_000), "tx": tx, "mint": mint, "buy": True,
                         "sol": sol, "tok": tok, "user": BUYERS[k % 60], "vs": vs + sol, "vt": vt - tok, "rs": sol,
                         "rt": rt - tok, "fb": 95, "cfb": 30, "ix": "buy"})
        w.add("other", {"kind": "complete", "t": t, "slot": slot_of(t), "tx": tx, "mint": mint})
        w.add("other", {"kind": "migrate", "t": t, "slot": slot_of(t), "tx": tx, "mint": mint, "pool": "W" + str(k),
                        "sol": 85 * SOL, "tok": BASE0})
        pb, pq = BASE0, QUOTE0
        first = (-1_000, 1_000, 2_000, 3_000, 5_000, 6_000, 7_000, 8_000)[k % 8]
        for j in range(150):
            tx += 1
            buy = bool(rng.random() < [0.35, 0.5, 0.6][k % 3])
            if buy:
                q = int(SOL * (0.3 + 2 * rng.random()))
                b = int(pb * q / (pq + q))
            else:
                b = int(pb * 0.01 * (1 + 3 * rng.random()))
                q = int(pq * b / (pb + b))
            tt = t + first + j * 2_000
            w.add("amm", {"t": tt, "slot": slot_of(tt), "tx": tx, "pool": "W" + str(k), "mint": mint,
                          "buy": buy, "base": b, "quote": q, "user": BUYERS[int(rng.integers(0, 60))], "pb": pb,
                          "pq": pq, "lpb": 20, "pfb": 5, "cfb": 5})
            pb, pq = (pb - b, pq + q) if buy else (pb + b, pq - q)
    w.flush(T0)


def slot_of(t: int) -> int:
    return 5_000_000 + (t - T0) // 10


def test_the_replay_runs_end_to_end_and_reports(tmp_path, monkeypatch):
    synth_late(tmp_path)
    monkeypatch.setattr(store, "base", lambda: tmp_path)
    monkeypatch.setattr("lab.pumpfun_rt.study.WARM_DAYS", 0)
    res = XL.run(root=tmp_path, until_ms=T0 + 3 * 86_400_000, log=lambda *a: None, books_costs=X8.books(),
                 limits=X8.LIMITS, tail_ms=X8.TAIL_MS)
    assert set(res["entries"]) == {f"{n}@{k}" for _, n in X8.VARIANTS for k in X8.SCENARIOS}
    assert res["entry_until_ms"] == res["span"][1] - X8.TAIL_MS and not res["open_at_end"]
    sk = {n: Counter_of(res["skips"][n]) for n in res["skips"]}
    for k in X8.SCENARIOS:            # of the 23 before the entries stop: 3 known, 12 within 5 s, 8 later
        assert sk[f"P_pool0@{k}"]["no pool state"] == 20 and sk[f"P_pool0_sl10@{k}"]["no pool state"] == 20
        assert sk[f"P_pool0_wait@{k}"]["no pool state"] == sk[f"P_pool0_wait_sl10@{k}"]["no pool state"] == 8
    x0 = {x["mint"] for x in res["entries"]["P_pool0@B"]}
    x3 = {x["mint"] for x in res["entries"]["P_pool0_wait@B"]}
    assert x0 and len(x3 - x0) >= 6
    ev = X8.evaluate(res)
    assert set(ev["versus"]["B"]) == {x for x, _ in X8.VARIANTS[1:]}
    assert ev["table"]["B"]["X2"]["press"]["n"] > 0 and ev["table"]["B"]["X0"]["press"]["n"] == 0
    dropped = X8.evaluate(res, keep_gapped=False)
    lat = {k: RL.describe(c, n=500) for k, c in X8.scenarios().items()}
    live = X8.live_stops([{"rule": "P_pool0", "signal_ms": str(XL.SENDER_FROM_MS + 1), "ret": "-0.4",
                           "pnl_sol": "-0.04", "exit_why": "stop"}])
    assert live == {"n": 1, "pnl_sol": -0.04, "mean": -0.4, "stops": 1, "stop_mean": -0.4}
    md = X8.report_md(res, ev, dropped, lat, [], live)
    assert "better than X0" in md and "\u2014" not in md and "X5" in md and "no pool state" in md
    json.dumps({"eval": ev, "latency": lat}, default=str)


def Counter_of(skips):
    from collections import Counter
    return Counter(w for _, w in skips)
