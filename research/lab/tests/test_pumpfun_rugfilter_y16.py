"""Y16, a rug filter for P_pool0_wait: the three registered strategies and trials, the select filter on rug0t at its
base rate and at half of it, the single-feature rule (RUG_CUT, a value not known keeps the entry, none set skips "no
model"), the twins otherwise P_pool0_wait field for field, what the X0 books note (features, the slot buys, the
largest one-trade fall, the crash), R3's in-sample pick, the numbers, every strategy before Y16 trading exactly as
before, and the replay end to end. No network, no wallet.

Run from research/lab:  python -m pytest tests/test_pumpfun_rugfilter_y16.py
"""

from __future__ import annotations

import dataclasses
import json
import math

import pytest

from lab.pumpfun_rt import model as M
from lab.pumpfun_rt import pipeline as P
from lab.pumpfun_rt import rug16 as Y16
from lab.pumpfun_rt import selfeat as SF
from lab.pumpfun_rt import selmodel as SM
from lab.pumpfun_rt import sim
from lab.pumpfun_rt import store
from lab.pumpfun_rt import strategies as S
from test_pumpfun_exit_runners import Pool
from test_pumpfun_rt import BUYERS, DEV, SOL, T0, Curve, Fixed
from test_pumpfun_select_y9 import market, stub_models, write

Y16_NAMES = ["P_pool0_wait_norug", "P_pool0_wait_norug_half", "P_pool0_wait_rugcut"]
R1, R2, R3 = Y16_NAMES
OLD = P.STRATEGIES[:[s.name for s in P.STRATEGIES].index(R1)]   # every strategy before Y16


@pytest.fixture(autouse=True)
def small_models(monkeypatch):
    monkeypatch.setitem(M.PARAMS, "n_estimators", 30)
    monkeypatch.setitem(SM.PARAMS, "n_estimators", 30)


def same(a: dict, b: dict) -> bool:
    return {k: v for k, v in a.items() if k not in ("rule", "pid", "prob")} == {
        k: v for k, v in b.items() if k not in ("rule", "pid", "prob")}


def run_pool(models, names=("P_pool0_wait", *Y16_NAMES), ratio=1.5, select=True):
    eng = sim.Engine([], costs=Fixed(), strategies=[P.BY_NAME[n] for n in names], models=models, select=select)
    pool = Pool(eng)
    pool.to(T0 + 6_000, ratio)
    eng.advance(T0 + 400_000)
    return eng


# ---------------------------------------------------------------- the registered strategies

def test_the_y16_strategies_and_trials_are_what_the_prereg_says():
    names = [s.name for s in P.STRATEGIES]
    assert names[-3:] == Y16_NAMES and [n for _, n in Y16.VARIANTS] == ["P_pool0_wait"] + Y16_NAMES
    base = P.BY_NAME["P_pool0_wait"]
    flts = ({"select": {"rug0t": ("max", 1.0)}}, {"select": {"rug0t": ("max", 0.5)}}, {"cut": "Y16"})
    for n, flt in zip(Y16_NAMES, flts):
        s = P.BY_NAME[n]
        assert s.flt == flt and dataclasses.replace(s, name=base.name, label=base.label) == base
        assert (s.exits, s.p, s.stake_sol) == (base.exits, {"delay_s": 0, "wait_pool_s": 5}, 0.1)
    assert P.RUG_CUT == {"first5_share": ("max", 0.4078188248772218)} and base.flt == {}   # Y16's in-sample pick
    assert all(not s.flt.get("cut") for s in OLD)
    assert S.RUGFILTER_Y16_TRIALS == 12 == 3 * len(Y16.LIMITS) * len(Y16.LATENCIES)
    assert S.N_TRIALS == 22 + 1 + 12 + 54 + 135 + 140 + 1 + 6 + 5 + 10 + 10 + 4 + 12 + 16 + 12


# ---------------------------------------------------------------- the filters

MODEL = ("P_pool0_wait", R1, R2)


def test_the_rug_model_at_its_base_rate_and_at_half_of_it():
    ok = run_pool(stub_models(p_rug=0.1, base=0.2), MODEL)              # 0.1: at most half the base rate, both buy
    x0 = [t for t in ok.closed if t["rule"] == "P_pool0_wait"][0]
    for n in (R1, R2):
        t = [t for t in ok.closed if t["rule"] == n][0]
        assert same(t, x0) and t["prob"] == 0.1
    mid = run_pool(stub_models(p_rug=0.15, base=0.2), MODEL)
    assert {t["rule"] for t in mid.closed} == {"P_pool0_wait", R1} and mid.skipped[(R2, "model")] == 1
    high = run_pool(stub_models(p_rug=0.21, base=0.2), MODEL)
    assert {t["rule"] for t in high.closed} == {"P_pool0_wait"}
    assert high.skipped[(R1, "model")] == high.skipped[(R2, "model")] == 1
    none = run_pool({}, MODEL)
    assert none.skipped[(R1, "no model")] == none.skipped[(R2, "no model")] == 1
    assert [t["rule"] for t in none.closed] == ["P_pool0_wait"]


def test_the_single_feature_rule(monkeypatch):
    eng = run_pool({})                                          # the pick: no outside buyer here, so R3 buys
    assert {t["rule"] for t in eng.closed} == {"P_pool0_wait", R3}
    monkeypatch.setattr(P, "RUG_CUT", None)                     # no rule: R3 buys nothing
    eng = run_pool({})
    assert eng.skipped[(R3, "no model")] == 1 and [t["rule"] for t in eng.closed] == ["P_pool0_wait"]
    monkeypatch.setattr(P, "RUG_CUT", {"pool_sol": ("min", 1e9)})
    eng = run_pool({})
    assert eng.skipped[(R3, "rug rule")] == 1
    monkeypatch.setattr(P, "RUG_CUT", {"pool_sol": ("min", 1.0)})
    eng = run_pool({})
    a, b = (next(t for t in eng.closed if t["rule"] == n) for n in ("P_pool0_wait", R3))
    assert same(a, b) and b["prob"] > 1.0                       # prob: the feature's value
    monkeypatch.setattr(P, "RUG_CUT", {"creator_dump_rate": ("max", 0.0)})   # a new creator: not known, kept
    eng = run_pool({})
    assert {t["rule"] for t in eng.closed} == {"P_pool0_wait", R3}
    monkeypatch.setattr(P, "RUG_CUT", {"pool_sol": ("min", 1.0)})
    eng = run_pool({}, select=False)                            # an engine without the tracker (the live service's)
    assert eng.skipped[(R3, "no model")] == 1


def test_a_cut_given_as_a_dict_is_that_rule():
    s = dataclasses.replace(P.BY_NAME[R3], name="r3x", flt={"cut": {"pool_sol": ("max", 1.0)}})
    eng = sim.Engine([], costs=Fixed(), strategies=[s], select=True)
    pool = Pool(eng)
    pool.to(T0 + 6_000, 1.5)
    eng.advance(T0 + 400_000)
    assert eng.skipped[("r3x", "rug rule")] == 1 and not eng.closed


# ---------------------------------------------------------------- what the X0 books note

def noting(ratios, models=None, dump=False):
    eng = sim.Engine([], costs=Fixed(), models=models or {}, select=True)
    bundles = eng.add_pipe(Y16.Bundles(eng))
    s = dataclasses.replace(P.BY_NAME["P_pool0_wait"], name="P_pool0_wait@B@L100")
    pipe = eng.add_pipe(Y16.RugPipe(eng, [s], P.PaperExecutor(), name=s.name, note=True, bundles=bundles))
    cv = Curve(eng, mint="M" * 44, dev=DEV, t=T0 - 200_000, slot=7_000)
    cv.buy(T0 - 200_000, SOL, DEV, same_tx=True)               # the dev in the creation
    cv.slot -= 1
    cv.buy(T0 - 200_000, int(0.5 * SOL), BUYERS[0])             # two others in the same slot
    cv.slot -= 1
    cv.buy(T0 - 200_000, int(0.5 * SOL), BUYERS[1])
    cv.buy(T0 - 199_000, int(0.5 * SOL), BUYERS[2])             # a later slot
    pool = Pool(eng)
    t = T0 + 6_000
    for r in ratios:
        pool.to(t, r)
        t += 10_000
        eng.advance(t - 5_000)
    if dump:                                                    # one sale of 40 % of the pool's tokens: about -49 %
        pool.trade(t, False, base=int(pool.pb * 0.4), user=BUYERS[9])
    eng.advance(T0 + 400_000)
    pipe.finish(eng.now)
    return eng, pipe, bundles, cv


def test_the_slot_buys_count_other_wallets_in_the_first_slot():
    eng, _, bundles, cv = noting([1.0])
    f = bundles.features(cv.mint)
    assert f["bundle_n"] == 2.0 and 0 < f["bundle_share"] < 0.1
    assert math.isnan(bundles.features("unknown")["bundle_n"])


def test_the_x0_book_notes_features_the_fall_and_the_crash():
    _, pipe, _, _ = noting([1.05], models=stub_models(p_rug=0.3, base=0.2), dump=True)
    e = Y16.entries(pipe, [])
    assert len(e) == 1
    x = e[0]
    f = x["features"]
    assert f["pool_sol"] > 1 and f["p_rug0t"] == 0.3 and f["base_rug0t"] == 0.2 and "c_top10_share" in f
    assert x["max_drop"] >= Y16.CRASH_DROP and x["crash"]
    calm = Y16.entries(noting([1.05, 0.95, 1.5])[1], [])[0]
    assert calm["max_drop"] < Y16.CRASH_DROP and not calm["crash"] and calm["ret"] > 0


def test_noting_never_changes_the_book():
    a = run_pool({}, names=("P_pool0_wait",))
    _, pipe, _, _ = noting([1.5])
    t = pipe.closed[0]
    b = a.closed[0]
    assert {k: t[k] for k in ("ret", "exit_why", "legs")} == {k: b[k] for k in ("ret", "exit_why", "legs")}


# ---------------------------------------------------------------- R3's pick and the numbers

def ent(ret, crash=False, failed=False, t=T0, mint="a", **f):
    return {"mint": mint, "signal_ms": t, "ret": ret, "pnl_sol": ret * 0.1, "failed": failed, "crash": crash,
            "features": f, "exit_why": "stop", "real_ms": t, "hold_s": 1, "gapped": False, "peak": None}


def test_fires_and_the_model_rule():
    assert Y16.fires({"x": ("max", 0.5)}, {"x": 0.6}) and not Y16.fires({"x": ("max", 0.5)}, {"x": 0.5})
    assert Y16.fires({"x": ("min", 2.0)}, {"x": 1.0}) and not Y16.fires({"x": ("min", 2.0)}, {"x": math.nan})
    assert not Y16.fires({"x": ("min", 2.0)}, {})
    assert Y16.model_fires("rug0t", 1.0, {"p_rug0t": 0.3, "base_rug0t": 0.2})
    assert not Y16.model_fires("rug0t", 0.5, {"p_rug0t": 0.1, "base_rug0t": 0.2})
    assert Y16.model_fires("rug0t", 1.0, {"p_rug0t": math.nan, "base_rug0t": 0.2}) is None


def test_the_pick_keeps_the_best_mean_in_sample():
    e = [ent(0.2, pool_sol=80.0, c_top10_share=0.2) for _ in range(8)]
    e += [ent(-0.8, crash=True, pool_sol=50.0, c_top10_share=0.2), ent(-0.6, crash=True, pool_sol=55.0,
                                                                       c_top10_share=0.2)]
    pk = Y16.pick_cut(e)
    assert pk["n"] == 10 and pk["crashes"] == 2 and list(pk["rule"]) == ["pool_sol"]
    how, thr = pk["rule"]["pool_sol"]
    assert how == "min" and 55.0 <= thr <= 80.0
    best = pk["candidates"][0]
    assert best["kept"] == 8 and best["crashes_cut"] == 2 and best["mean"] == pytest.approx(0.2)
    assert Y16.pick_cut([])["rule"] == {}


def test_the_picker_fills_the_shared_cut_at_the_split():
    class FakePipe:
        note = True
        closed, failed, peaks, eng = [], [], {}, type("E", (), {"gaps": []})()
    cut = {}
    strats, _ = Y16.books(cut)
    r3 = [s for s, _ in strats if s.name.startswith(R3)]
    assert len(r3) == 4 and all(s.flt["cut"] is cut for s in r3) and not r3[0].flt["cut"]
    pk = Y16.Picker(FakePipe(), cut)
    pk.pick(T0)
    assert pk.result["n"] == 0 and cut == {}
    cut.update({"pool_sol": ("min", 60.0)})
    assert all(s.flt["cut"] == {"pool_sol": ("min", 60.0)} for s in r3)


def test_rule_on_x0s_entries_and_the_separation():
    e = [ent(0.25, mint="w", p_rug0t=0.05, base_rug0t=0.1, pool_sol=80.0),
         ent(-0.7, crash=True, mint="c", p_rug0t=0.3, base_rug0t=0.1, pool_sol=40.0),
         ent(0.2, mint="v", p_rug0t=0.07, base_rug0t=0.1, pool_sol=70.0),
         ent(-0.2, mint="s", pool_sol=60.0)]                    # no model: kept by R1 and R2
    r1 = Y16.rule_on(e, "R1", {})
    assert (r1["kept"], r1["cut"], r1["crashes_avoided"], r1["winners_lost"], r1["no_model"]) == (3, 1, 1, 0, 1)
    r2 = Y16.rule_on(e, "R2", {})
    assert (r2["cut"], r2["winners_lost"]) == (2, 1) and r2["cut_mean"] == pytest.approx((-0.7 + 0.2) / 2)   # at half
    r3 = Y16.rule_on(e, "R3", {"pool_sol": ("min", 65.0)})
    assert (r3["cut"], r3["crashes_avoided"], r3["winners_lost"]) == (2, 1, 0)
    assert Y16.rule_on(e, "R3", {})["cut"] == 0
    sep = {r["feature"]: r for r in Y16.separation(e)}
    assert sep["pool_sol"]["auc"] == 0.0 and sep["pool_sol"]["n_crash"] == 1 and sep["p_rug0t"]["auc"] == 1.0
    assert sep["bundle_n"]["auc"] is None and Y16.auc([1.0], [1.0]) == 0.5


def test_books_latency_and_limits():
    strats, costs = Y16.books()
    assert len(strats) == len(costs) == 16 and all(s.stake_sol == 0.1 for s, _ in strats)
    assert {sim.base_name(s) for s, _ in strats} == {"P_pool0"}
    assert [s.name for s, _ in strats][:4] == [f"{n}@A@L25" for _, n in Y16.VARIANTS]
    assert {lim.max_daily_loss_sol for _, lim in strats} == {0.25, 1.0}
    assert Y16.TAIL_MS >= 300_000 + 5_000 + 2 * 60_000


def test_the_live_check_reads_the_replays_features():
    res = {"last_features": {"B": {"m1": {"p_rug0t": 0.3, "base_rug0t": 0.1, "pool_sol": 40.0}}},
           "cut": {"pool_sol": ("min", 50.0)}}
    trades = [{"rule": "P_pool0_wait", "mint": "m1", "symbol": "ROOM", "signal_ms": T0 + 1, "ret": -0.52,
               "exit_why": "stop"},
              {"rule": "P_pool0_wait", "mint": "m2", "symbol": "X", "signal_ms": T0 + 2, "ret": 0.3, "exit_why": "take"},
              {"rule": "P_pool0", "mint": "m1", "signal_ms": T0 + 3, "ret": -0.9},
              {"rule": "P_pool0_wait", "mint": "m1", "signal_ms": T0 - 5, "ret": -0.9}]
    out = Y16.live_check(res, trades, T0)
    assert [r["symbol"] for r in out] == ["ROOM", "X"]
    assert out[0]["crash"] and out[0]["R1"] and out[0]["R2"] and out[0]["R3"]
    assert out[1]["seen"] is False and out[1]["R1"] is None and not out[1]["crash"]


# ---------------------------------------------------------------- nothing before Y16 changes

def test_every_strategy_before_y16_trades_exactly_as_before(tmp_path, monkeypatch):
    """One shared paper book of every strategy before Y16 on a synthetic record, without and with the Y16 books (R3
    with a rule): the closed trades, failed buys and skips of the old strategies are the same field for field (the
    pid aside)."""
    from test_pumpfun_trends_y10 import y10_models
    write(tmp_path, market(n=24, every_ms=1_500_000))
    monkeypatch.setattr(store, "base", lambda: tmp_path)
    monkeypatch.setattr(P, "RUG_CUT", {"pool_sol": ("min", 1.0)})
    days = store.days(tmp_path)

    def run(new: bool):
        eng = sim.Engine(S.RULES, costs=Fixed(), strategies=P.STRATEGIES if new else OLD,
                         models=y10_models() | {"sel_rug0t": stub_models(p_rug=0.1, base=0.2)["sel_rug0t"]},
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
    for n in Y16_NAMES:
        assert [t for t in b.closed if t["rule"] == n]


# ---------------------------------------------------------------- the replay end to end

def test_the_replay_runs_end_to_end_and_reports(tmp_path, monkeypatch):
    write(tmp_path, market(n=60, every_ms=4_000_000))
    monkeypatch.setattr(store, "base", lambda: tmp_path)
    monkeypatch.setattr("lab.pumpfun_rt.study.WARM_DAYS", 0)
    monkeypatch.setattr(SM, "MIN_TRAIN", 12)
    res = Y16.run(root=tmp_path, until_ms=T0 + 4 * 86_400_000, log=lambda *a: None)
    assert set(res["entries"]) == {f"{n}@{a}@{k}" for _, n in Y16.VARIANTS for a in Y16.LATENCIES
                                   for k in Y16.LIMITS}
    assert res["split_ms"] is not None and not res["open_at_end"]
    assert res["pick"]["at_ms"] == res["split_ms"] and res["pick"]["n"] > 0 and res["cut"] == res["pick"]["rule"]
    x0 = res["entries"]["P_pool0_wait@B@L100"]
    assert x0 and all("features" in x and "crash" in x for x in x0)
    assert all("features" not in x for x in res["entries"][f"{R1}@B@L100"] + res["entries"][f"{R3}@B@L100"])
    assert {w for _, w in res["skips"][f"{R1}@B@L100"]} <= {"model", "no model"}
    sk = [w for t, w in res["skips"][f"{R3}@B@L100"]]
    assert all(t >= res["split_ms"] for t, w in res["skips"][f"{R3}@B@L100"] if w == "rug rule")
    assert "no model" not in sk                                 # before the pick R3 is X0, after it has its rule
    ev = Y16.evaluate(res)
    for c in ev["versus"]:
        assert set(ev["versus"][c]) == {"R1", "R2", "R3"} == set(ev["on_x0"][c])
    lat = {k: Y16.RL.describe(c, n=500) for k, c in Y16.Y12.latencies().items()}
    md = Y16.report_md(res, ev, lat, Y16.live_check(res, [], T0))
    assert "Better than X0" in md and "\u2014" not in md and "R3's rule" in md and "What separates" in md
    json.dumps({"eval": ev, "pick": res["pick"]}, default=str)
