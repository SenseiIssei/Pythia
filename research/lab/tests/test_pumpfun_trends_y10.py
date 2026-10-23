"""Y10, the Trends page's measures in our models and strategies: the registered strategies and trials, the trend
tracker's features (what they count, and no look-ahead: a value at t reads only trades before the boundary at or
before t), the triggers of the trend strategies and the filter's wiring, the models with the trend features, the
study's helpers, the meme rule on the trend ranks, and every strategy before Y10 trading exactly as before with the
Y10 books and the tracker next to it. No network, no wallet.

Run from research/lab:  python -m pytest tests/test_pumpfun_trends_y10.py
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from lab.onchain import meme as ME
from lab.pumpfun_rt import exitpol as XP
from lab.pumpfun_rt import model as M
from lab.pumpfun_rt import pipeline as P
from lab.pumpfun_rt import select9 as Y9
from lab.pumpfun_rt import selfeat as SF
from lab.pumpfun_rt import selmodel as SM
from lab.pumpfun_rt import sim
from lab.pumpfun_rt import strategies as S
from lab.pumpfun_rt import trendfeat as TF
from lab.pumpfun_rt import trends10 as Y10
from test_pumpfun_exit_runners import Pool
from test_pumpfun_rt import BUYERS, MINT, SOL, T0, Curve, Fixed, key
from test_pumpfun_select_y9 import Stub, feed, market, stub_models

Y10_NAMES = ["P_pool0_top30t", "P_pool5_top30t", "P_hot5", "P_fresh3", "P_pool0_heat"]
OLD = P.STRATEGIES[:[s.name for s in P.STRATEGIES].index(Y10_NAMES[0])]   # every strategy before Y10
STEP = TF.STEP_MS


@pytest.fixture(autouse=True)
def small_models(monkeypatch):
    monkeypatch.setitem(M.PARAMS, "n_estimators", 30)
    monkeypatch.setitem(SM.PARAMS, "n_estimators", 30)


def y10_models(p_alive=0.9, alive_base=0.5) -> dict:
    out = stub_models()
    out["sel_policy"] = {k: {"0.3": 0.5} for k in ("win0", "win5", "win0t", "win5t")}
    out["et_alive5m"] = M.Fitted(Stub(p_alive), None, None, alive_base, XP.trend_features())
    return out


# ---------------------------------------------------------------- the registered strategies

def test_the_y10_strategies_and_trials_are_what_the_prereg_says():
    names = [s.name for s in P.STRATEGIES]
    assert names[-10:-5] == Y10_NAMES and [n for _, n in Y10.VARIANTS][3:] == Y10_NAMES
    base = P.BY_NAME["P_pool0"]
    for n in Y10_NAMES:
        s = P.BY_NAME[n]
        assert (s.exits, s.stake_sol, s.tp, s.sl, s.hold_s) == (base.exits, 0.1, 0.30, 0.20, 300)
    assert P.BY_NAME["P_pool0_top30t"].flt == {"select": {"win0t": ("top", 0.3)}}
    assert P.BY_NAME["P_pool5_top30t"].flt == {"select": {"win5t": ("top", 0.3)}}
    assert P.BY_NAME["P_pool5_top30t"].p == {"delay_s": 5}
    hot = P.BY_NAME["P_hot5"]
    assert (hot.family, hot.entry, hot.p, hot.flt) == ("C", "trend", {"list": "hot", "top": 5, "rising": True},
                                                       {"trend": {"alive": "et_alive5m"}})
    fresh = P.BY_NAME["P_fresh3"]
    assert (fresh.family, fresh.entry, fresh.p, fresh.flt) == (
        "E", "trend", {"list": "fresh", "top": 3, "from_s": 120, "to_s": 600}, {})
    heat = P.BY_NAME["P_pool0_heat"]
    assert (heat.family, heat.entry, heat.p, heat.flt) == ("E", "migration", {"delay_s": 0}, {"trend": {"heat": 1.0}})
    for s in OLD:                                               # nothing before Y10 has a trend filter or entry
        assert "trend" not in s.flt and s.entry != "trend"
        assert not any(k.endswith("t") for k in (s.flt.get("select") or {}))
    assert S.TRENDS_Y10_TRIALS == 10 == len(Y10.JUDGED) * len(Y10.LIMITS)
    assert Y10.UNTIL_MS == 1_792_764_000_000                    # 2026-10-23 14:00 UTC
    assert Y10.LIMITS == Y9.LIMITS and Y10.COUNTERPART == {"A1": "S2", "A2": "S4"}


def test_books_latency_fees_and_limits():
    strats, costs = Y10.books()
    assert len(strats) == len(costs) == 16 and all(s.stake_sol == 0.1 for s, _ in strats)
    assert {sim.base_name(s) for s, _ in strats} == {"P_pool0"}
    b = next(iter(costs.values()))
    assert b.buy.points_ms == Y9.SENDER_BUY_MS and b.tx_lamports() == 1_005_000


# ---------------------------------------------------------------- the features

def test_the_tracker_ranks_shares_buyers_and_heat_on_closed_buckets_only():
    eng = sim.Engine([], costs=Fixed(), trend=True)
    a, b, c = Curve(eng, mint=key(1), t=T0), Curve(eng, mint=key(2), t=T0), Curve(eng, mint=key(3), t=T0)
    a.buy(T0 + 1_000, 3 * SOL, BUYERS[0])
    a.buy(T0 + 2_000, SOL, BUYERS[1])
    b.buy(T0 + 3_000, 2 * SOL, BUYERS[2])
    c.buy(T0 + 4_000, SOL, BUYERS[3])
    tr = eng.trend
    f = tr.features(eng.tokens[key(1)], T0 + STEP - 1)          # the bucket is still open: nothing counted
    assert f["tr_vol_5m"] == 0 and f["tr_rank_5m"] == 1 and f["mkt_buy_sol_15m"] == 0
    c.buy(T0 + STEP + 500, 5 * SOL, BUYERS[4])                   # in the next bucket: not counted at T0 + STEP
    fa, fb, fc = (tr.features(eng.tokens[key(i)], T0 + STEP + 600) for i in (1, 2, 3))
    assert (fa["tr_rank_1m"], fb["tr_rank_1m"], fc["tr_rank_1m"]) == (1, 2, 3)
    assert fa["tr_vol_5m"] == pytest.approx(4.0) and fa["tr_share_5m"] == pytest.approx(4 / 7)
    assert fa["tr_ubuyers_1m"] == 2 and fa["tr_ubuyers_prev_1m"] == 0 and fa["tr_n_5m"] == 3
    assert fa["mkt_buy_sol_15m"] == pytest.approx(7.0) and fa["mkt_pools_15m"] == 0
    assert math.isnan(fa["mkt_heat_rel"]) and math.isnan(fa["fp_rank"])
    assert fa["tr_speed_pm"] > 0
    fc2 = tr.features(eng.tokens[key(3)], T0 + 2 * STEP)
    assert fc2["tr_rank_1m"] == 1 and fc2["tr_vol_5m"] == pytest.approx(6.0)
    # one minute later the first bucket left the 1-minute window (a coin without a buy ranks after those with
    # one), not the 5-minute one
    fa3 = tr.features(eng.tokens[key(1)], T0 + 60_000 + STEP)
    assert fa3["tr_rank_1m"] == 2 and fa3["tr_rank_5m"] == 2 and fa3["tr_ubuyers_1m"] == 0
    assert fa3["tr_ubuyers_prev_1m"] == 2
    assert tr.top(5, 2, TF.boundary(T0 + 60_000 + STEP)) == [key(3), key(1)]


def test_fresh_pools_are_ranked_by_their_pools_sol_and_heat_needs_its_history():
    eng = sim.Engine([], costs=Fixed(), trend=True)
    p1 = Pool(eng, mint=key(1), t=T0)
    p2 = Pool(eng, mint=key(2), t=T0 + 30_000)
    p1.trade(T0 + 40_000, True, sol=SOL)
    p2.trade(T0 + 41_000, True, sol=3 * SOL)
    tr = eng.trend
    f1, f2 = (tr.features(eng.tokens[key(i)], T0 + 50_000) for i in (1, 2))
    assert (f1["fp_n"], f1["fp_rank"], f2["fp_rank"]) == (2, 2, 1) and f1["mkt_pools_15m"] == 2
    assert f2["fp_vol_5m"] == pytest.approx(3.0 + 0.001, rel=1e-3) and f2["fp_rel"] > 2
    assert f1["fp_age_s"] == pytest.approx(50.0) and f2["fp_age_s"] == pytest.approx(20.0)
    assert tr.heat_ok(T0 + 50_000, 1.0) is None                 # under 3 hours of history
    assert tr.fresh(TF.boundary(T0 + 30 * 60_000 + STEP)) == [key(2)]   # the first one is no longer fresh


def test_the_heat_switch_compares_with_the_median_of_the_previous_six_hours():
    eng = sim.Engine([], costs=Fixed(), trend=True)
    cv = Curve(eng, t=T0)
    for i in range(4 * 360):                                    # 4 hours, one small buy per bucket
        cv.buy(T0 + i * STEP + 1, SOL // 100, BUYERS[i % 60])
    t = T0 + 4 * 3_600_000
    tr = eng.trend
    assert tr.heat_ok(t, 1.0) is True                           # flat: at its median
    assert tr.heat_ok(t, 1.5) is False
    med = tr.heat_median(TF.boundary(t))
    assert med == pytest.approx(tr.heat_now(TF.boundary(t)))
    assert tr.features(eng.tokens[MINT], t)["mkt_heat_rel"] == pytest.approx(1.0)


def test_no_look_ahead_the_features_at_t_equal_a_record_cut_before_its_boundary():
    """Every label row's and early row's trend features equal those of the same record fed only up to the last
    event before the boundary at or before the row's time (so no trade at or after it can matter)."""
    ev = market(n=5, every_ms=1_200_000)
    eng = sim.Engine([], costs=Fixed(), select=True, trend=True, early_rows=True)
    eng.early.keep_frac = 0.0
    lab = eng.add_pipe(SF.LabelPipe(eng))
    feed(eng, ev)
    eng.finish(ev[-1][1]["t"] + 1)
    early = eng.early.rows.frame()
    assert len(lab.rows) >= 6 and len(early["t"]) >= 20
    asks = [(r["mint"], r["t"], r) for r in lab.rows]
    mints = eng.early.mints
    for i in range(0, len(early["t"]), max(1, len(early["t"]) // 12)):
        row = {k: early[k][i] for k in TF.TREND_FEATURES}
        asks.append((mints[int(early["tid"][i])], early["t"][i], row))
    for mint, t, row in asks:
        cut = sim.Engine([], costs=Fixed(), select=True, trend=True)
        B = TF.boundary(t)
        for table, r in ev:
            if r["t"] >= B:
                break
            feed(cut, [(table, r)])
        tok = cut.tokens.get(mint)
        if tok is None:                                         # created after the boundary: nothing to compare
            continue
        f = cut.trend.features(tok, t)
        for k in TF.TREND_FEATURES:
            a, b = row[k], f[k]
            assert (math.isnan(a) and math.isnan(b)) or a == pytest.approx(b), (k, t, a, b)


# ---------------------------------------------------------------- the triggers and the filter

def hot_market(eng, rising=True):
    """Six curves: coin i buys (6 - i) SOL a bucket for a minute; coin 0's buyers grow in the second minute."""
    cvs = [Curve(eng, mint=key(40 + i), t=T0) for i in range(6)]
    for k in range(12):
        for i, cv in enumerate(cvs):
            n = (1 + k // 6) if (i == 0 and rising) else 1
            for j in range(n):
                cv.buy(T0 + k * STEP + 100 + j, (6 - i) * SOL // 10, BUYERS[(7 * i + j + (k % 6)) % 60])
    return cvs


def test_the_hot_trigger_needs_the_top_5_a_plain_curve_and_rising_buyers():
    eng = sim.Engine([], costs=Fixed(), trend=True)
    hot_market(eng)
    B = TF.boundary(T0 + 12 * STEP)
    eng.trend.roll(B)
    s = P.BY_NAME["P_hot5"]
    assert eng.trend.top(5, 5, B) == [key(40 + i) for i in range(5)]
    assert eng.trend.candidates(s, eng, B) == [key(40)]          # the only one with more buyers than a minute ago
    flat = sim.Engine([], costs=Fixed(), trend=True)
    hot_market(flat, rising=False)
    flat.trend.roll(B)
    assert flat.trend.candidates(s, flat, B) == []


def test_the_hot_strategy_enters_at_a_boundary_with_the_model_and_skips_without_it():
    def run(models):
        eng = sim.Engine([], costs=Fixed(), strategies=[P.BY_NAME["P_hot5"]], models=models, trend=True)
        hot_market(eng)
        eng.advance(T0 + 20 * STEP)
        eng.finish(T0 + 20 * STEP + 400_000)
        return eng
    ok = run(y10_models())
    pos = [p for pipe in ok.pipes for p in pipe.pos.values()] + ok.closed + ok.failed
    mints = [p["mint"] for p in pos]
    # in the first minutes every coin has more buyers than the minute before; the sixth is never in the top 5
    assert mints and len(set(mints)) == len(mints) and set(mints) <= {key(40 + i) for i in range(5)}
    assert all(p["signal_ms"] % STEP == 0 for p in pos)
    bad, none = run(y10_models(p_alive=0.4)), run({})
    asked = bad.skipped[("P_hot5", "model")]                    # every signal (one may have hit the exposure cap)
    assert not bad.closed and asked >= len(mints) and none.skipped[("P_hot5", "no model")] == asked
    assert not none.closed


def test_the_fresh_trigger_waits_two_minutes_and_takes_the_top_3():
    eng = sim.Engine([], costs=Fixed(), strategies=[P.BY_NAME["P_fresh3"]], trend=True)
    pools = [Pool(eng, mint=key(50 + i), t=T0 + i * 1_000) for i in range(4)]
    for k in range(70):
        for i, p in enumerate(pools):
            p.trade(T0 + 5_000 + k * 2_000 + i, True, sol=(4 - i) * SOL // 10, user=BUYERS[(k + i) % 60])
    eng.advance(T0 + 200_000)
    sig = sorted((p["mint"], p["signal_ms"]) for pipe in eng.pipes for p in pipe.pos.values())
    sig += sorted((t["mint"], t["signal_ms"]) for t in eng.closed)
    assert sorted(m for m, _ in sig) == [key(50), key(51), key(52)]
    for m, t in sig:
        mig = eng.tokens[m].migrate_t
        assert 120_000 <= t - mig <= 130_000 and t % STEP == 0


def test_the_heat_filter_skips_without_history_and_when_the_market_is_cold():
    def run(cold: bool, hours=4):
        eng = sim.Engine([], costs=Fixed(), strategies=[P.BY_NAME["P_pool0_heat"]], trend=True)
        cv = Curve(eng, mint=key(9), t=T0 - hours * 3_600_000)
        for i in range(hours * 360):
            cv.buy(T0 - hours * 3_600_000 + i * STEP + 1, SOL // (1000 if cold and i > hours * 300 else 100),
                   BUYERS[i % 60])
        Pool(eng, t=T0)
        eng.advance(T0 + 400_000)
        return eng
    assert [t["rule"] for t in run(False).closed] == ["P_pool0_heat"]
    assert run(True).skipped[("P_pool0_heat", "model")] == 1
    assert run(False, hours=2).skipped[("P_pool0_heat", "no model")] == 1
    off = sim.Engine([], costs=Fixed(), strategies=[P.BY_NAME["P_pool0_heat"]])   # no tracker (the live service)
    Pool(off, t=T0)
    off.advance(T0 + 400_000)
    assert off.skipped[("P_pool0_heat", "no model")] == 1 and off.trend is None and off.trend_tick is None


def test_the_trend_select_filters_use_the_trend_models():
    eng = sim.Engine([], costs=Fixed(), strategies=[P.BY_NAME["P_pool0_top30t"]], models=y10_models(),
                     select=True, trend=True)
    Pool(eng).to(T0 + 6_000, 1.5)
    eng.advance(T0 + 400_000)
    assert [t["rule"] for t in eng.closed] == ["P_pool0_top30t"]
    models = y10_models()
    del models["sel_win0t"]
    eng = sim.Engine([], costs=Fixed(), strategies=[P.BY_NAME["P_pool0_top30t"]], models=models, select=True,
                     trend=True)
    Pool(eng)
    eng.advance(T0 + 400_000)
    assert eng.skipped[("P_pool0_top30t", "no model")] == 1


# ---------------------------------------------------------------- every strategy before Y10

def test_every_strategy_before_y10_trades_exactly_as_before(tmp_path, monkeypatch):
    """One shared paper book of every strategy before Y10 on a synthetic record, without the trend tracker and the
    Y10 strategies, and with them, the Y10 books trading (models that pass): the closed trades, failed buys and
    skips of the old strategies are the same field for field (the pid aside, as Y9's test)."""
    from lab.pumpfun_rt import store
    from test_pumpfun_select_y9 import write
    write(tmp_path, market(n=24, every_ms=1_500_000))
    monkeypatch.setattr(store, "base", lambda: tmp_path)
    days = store.days(tmp_path)

    def run(new: bool):
        eng = sim.Engine(S.RULES, costs=Fixed(), strategies=P.STRATEGIES if new else OLD, models=y10_models(),
                         select=True, trend=new)
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
    assert {t["rule"] for t in b.closed} & set(Y10_NAMES)       # the Y10 books did trade next to them
    assert {t["rule"] for t in a.closed} >= {"P_pool0"}


# ---------------------------------------------------------------- the models

def test_the_trend_models_see_the_trend_features_and_wait_for_rows_that_have_them():
    from test_pumpfun_select_y9 import table
    tb = table(n=600)
    ms = SM.train(tb)
    assert all(ms[f"sel_{k}"].booster is None for k in SM.TREND_LABELS)
    assert "win0t" not in ms["sel_policy"] and ms["sel_rows"]["win0t"] == 0
    rng = np.random.default_rng(4)
    tb["tr_rank_5m"] = rng.integers(1, 30, len(tb["t"])).astype(float)
    ms = SM.train(tb)
    assert all(ms[f"sel_{k}"].booster is not None for k in SM.LABELS)
    assert ms["sel_win0t"].features == SF.SEL0 + TF.TREND_FEATURES
    assert ms["sel_win5t"].features == SF.SEL5 + TF.TREND_FEATURES
    assert set(ms["sel_policy"]) == set(SM.LABELS)
    wf = SM.walk_forward(tb)
    assert set(wf) == set(SM.LABELS)
    mc = Y10.model_compare(wf)
    assert [(r["y9"], r["trend"]) for r in mc] == list(Y10.MODEL_PAIRS) and all(r["n"] == r["n_trend"] for r in mc)


def test_the_early_trend_model_is_e_s_fit_with_the_trend_features():
    rng = np.random.default_rng(2)
    n = 900
    fr = {c: np.full(n, np.nan) for c in E_COLS()}
    fr["t"] = np.sort(rng.integers(T0, T0 + 3 * 86_400_000, n)).astype(float)
    fr["kind"] = rng.integers(0, 8, n).astype(float)
    x = rng.normal(size=n)
    fr["buys_5s"], fr["tr_rank_5m"] = x, rng.normal(size=n)
    fr["alive5m"] = (x + 0.3 * rng.normal(size=n) > 0).astype(float)
    m = XP.fit_trend(fr, "alive5m", until_ms=fr["t"][600])
    assert m.booster is not None and m.features == XP.trend_features()
    late = fr["t"] + 300_000 + XP.EMBARGO_MS >= fr["t"][600]
    assert m.base == pytest.approx(fr["alive5m"][~late].mean())
    assert XP.has_trend(fr) and not XP.has_trend({k: v for k, v in fr.items() if k != "tr_rank_5m"})


def E_COLS():
    from lab.pumpfun_rt import early as E
    return E.ROW_META + XP.trend_features() + E.ROW_LABELS


def test_the_early_snapshot_does_not_stop_labels_that_are_still_coming():
    ev = market(n=3, every_ms=1_200_000)
    eng = sim.Engine([], costs=Fixed(), trend=True, early_rows=True)
    eng.early.keep_frac = 0.0
    feed(eng, ev[:len(ev) // 2])
    snap = Y10.early_snapshot(eng.early)
    pending = len(eng.early.rows.pending)
    assert pending and len(snap["t"]) == eng.early.rows.n
    feed(eng, ev[len(ev) // 2:])
    eng.finish(ev[-1][1]["t"] + 4_000_000)
    after = eng.early.rows.frame()
    assert np.isfinite(after["alive5m"]).sum() > np.isfinite(snap["alive5m"]).sum()


# ---------------------------------------------------------------- the study's helpers

def entry(t, ret, mint="m"):
    return {"mint": mint, "signal_ms": t, "real_ms": t + 60_000, "ret": ret, "pnl_sol": ret * 0.1, "failed": False,
            "exit_why": "time", "gapped": False, "hold_s": 60.0, "legs": 1, "peak": None, "peak_held": None}


def test_the_rule_needs_a_band_above_zero_and_more_pnl():
    from lab.pumpfun_rt import exitlab as XL
    base = [entry(T0 + h * 3_600_000 + i, -0.05 + 0.01 * (i % 3), f"b{h}{i}") for h in range(12) for i in range(3)]
    good = [entry(T0 + h * 3_600_000 + i, 0.10 + 0.01 * (i % 3), f"g{h}{i}") for h in range(12) for i in range(3)]
    v = Y10.judge(good, base, XL.stats(good), XL.stats(base))
    assert v["better"] and v["band"][0] > 0 and v["pnl_higher"]
    v = Y10.judge(base, good, XL.stats(base), XL.stats(good))
    assert not v["better"]
    few = good[:6]                                              # two hours: no band, no
    v = Y10.judge(few, base, XL.stats(few), XL.stats(base))
    assert not v["better"] and math.isnan(v["band"][0])


def test_evaluate_and_the_out_of_sample_day():
    trained = {"2026-10-21": {"models": ["win0", "win5"]},
               "2026-10-22": {"models": ["win0", "win5", "win0t", "win5t", "et_alive5m"]}}
    assert Y10.oos_day(["2026-10-20", "2026-10-21", "2026-10-22"], trained) == "2026-10-22"
    split = T0 + 86_400_000
    ents = {f"{n}@{k}": [entry(split + h * 3_600_000, 0.01 * (x == "T2"), f"{n}{h}") for h in range(12)]
            for k in Y10.LIMITS for x, n in Y10.VARIANTS}
    res = {"split_ms": split, "entries": ents, "skips": {k: [] for k in ents}}
    ev = Y10.evaluate(res)
    assert set(ev["better"]) == set(Y10.JUDGED) and set(ev["improves"]) == {"A1", "A2"}
    assert ev["better"]["T2"] and not ev["better"]["T1"]         # +1 % in every hour against 0; the same as X0
    assert ev["table"]["L25"]["X0"]["n"] == 12


# ---------------------------------------------------------------- the meme rule on the trend ranks

def test_the_meme_candidates_carry_the_trend_ranks_and_trend_top_uses_them():
    now = T0
    doc = {"written_ms": now - 5_000, "lists": {
        "hot": [{"mint": key(70 + i), "migrated": i != 1, "migrate_ms": now - 10 * 60_000, "badges": []}
                for i in range(7)],
        "fresh": [{"mint": key(80 + i), "migrate_ms": now - (3 + i) * 60_000, "badges": []} for i in range(4)]}}
    c = ME.merge(ME.from_trends(doc, now))
    assert c[key(70)]["ranks"] == {"hot": 1} and c[key(72)]["ranks"] == {"hot": 3}
    assert key(71) not in c and c[key(82)]["ranks"] == {"fresh": 3}
    why = {m: ME.entry_why("trend_top", x, now) for m, x in c.items()}
    assert why[key(70)] is None and why[key(74)] is None
    assert "top 5" in why[key(75)]                               # sixth in the hot list
    assert "5 min" in why[key(80)] and "5 min" in why[key(81)]   # 3 and 4 minutes after the migration
    assert why[key(82)] is None and "top 5" in why[key(83)]      # fourth of the fresh pools
    low = {**c[key(70)], "trends": {**c[key(70)]["trends"], "badges": ["win_low"]}}
    assert "low" in ME.entry_why("trend_top", low, now)
    rug = {**c[key(70)], "trends": {**c[key(70)]["trends"], "badges": ["rug_risk"]}}
    assert "rug" in ME.entry_why("trend_top", rug, now)
    for r in ("fresh_win", "momentum_trail", "organic_trend"):  # the earlier rules read no rank
        assert ME.entry_why(r, c[key(80)], now) == ME.entry_why(r, {**c[key(80)], "ranks": {}}, now)
    assert list(ME.RULES)[-1] == "trend_top"                     # last: the earlier rules spend the checks first
