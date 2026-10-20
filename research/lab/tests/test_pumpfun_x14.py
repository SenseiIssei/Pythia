"""X14 (results/pumpfun_early_exit_plan.md): the early-detection rows and their labels, the positions'
paths and step rows, the exit-policy simulator against the pipeline itself, the hazard exit and the early
filter in the pipeline, the evaluation end to end, the models' round trip and the daily card line. No
network, nothing that could trade.

Run from research/lab:  python -m pytest tests/test_pumpfun_x14.py
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

import numpy as np
import pytest

from lab.pumpfun_rt import card as CARD
from lab.pumpfun_rt import early as E
from lab.pumpfun_rt import exitpol as X
from lab.pumpfun_rt import model as M
from lab.pumpfun_rt import pipeline as P
from lab.pumpfun_rt import sim
from test_pumpfun_rt import BUYERS, DEV, MINT, SOL, T0, Curve, Fixed, key


@pytest.fixture(autouse=True)
def small_models(monkeypatch):
    monkeypatch.setitem(M.PARAMS, "n_estimators", 20)


def early_engine(**kw) -> sim.Engine:
    return sim.Engine([], costs=Fixed(), early_rows=True, **kw)


def rows_of(eng) -> dict:
    tb = eng.early.tables()
    fr = tb["rows"]
    return {E.KINDS[int(k)]: {c: v[i] for c, v in fr.items()} for i, k in enumerate(fr["kind"])}, tb


# ---------------------------------------------------------------- rows and labels

def test_early_rows_at_every_age_and_milestone_with_their_labels():
    eng = early_engine()
    cv = Curve(eng)
    dev_tok = cv.buy(T0, 2 * SOL, DEV, same_tx=True)
    cv.buy(T0 + 1_000, SOL, BUYERS[0])                       # a sniper (within 2 s)
    for i in range(1, 12):
        cv.buy(T0 + 3_000 + i * 2_000, 2 * SOL, BUYERS[i])   # a steady run past 25 %
    cv.buy(T0 + 40_000, 40 * SOL, BUYERS[30])                 # far up: our early buys triple
    eng.advance(T0 + 100_000)
    cv.sell(T0 + 100_000, dev_tok, DEV)                      # the dev dumps at 100 s
    eng.advance(T0 + 2 * 3_600_000)
    eng.finish(T0 + 2 * 3_600_000)
    rows, tb = rows_of(eng)
    assert {"t5", "t10", "t20", "t30", "t60", "p25"} <= set(rows)
    r5 = rows["t5"]
    assert r5["filled"] == 1 and r5["snipers_2s"] == 1 and r5["buys_5s"] >= 1 and r5["holders"] >= 2
    assert r5["peak3x"] == 1.0 and r5["alive5m"] == 0.0     # the dev sold all within 5 minutes of t = 5 s
    assert rows["t60"]["peak3x"] == 0.0                      # bought after the jump: no 3x from there
    assert r5["mig1h"] == 0.0
    assert set(E.early_feature_list()) <= set(tb["rows"])
    pa = tb["paths"]
    assert len(pa["i_pos"]) == len(rows) and (pa["i_full"] == 1).all()
    t5_row = int(np.flatnonzero(tb["rows"]["kind"] == E.KIND_ID["t5"])[0])
    i5 = int(np.flatnonzero(pa["i_row"] == t5_row)[0])
    assert pa["p_flag"][int(pa["i_start"][i5]):int(pa["i_end"][i5])].max() == 1     # the dev sale is flagged
    st = tb["steps"]
    assert len(st["pos"]) and set(E.STEP_FEATURES) <= set(st)
    assert np.all(np.diff(st["t"][st["pos"] == st["pos"][0]]) >= E.STEP_EVERY_MS)


def test_a_failed_early_buy_has_no_peak_and_no_path():
    eng = early_engine()
    cv = Curve(eng)
    cv.buy(T0 + 5_500, 30 * SOL, BUYERS[0])                  # the price runs away before the 5 s buy lands
    eng.advance(T0 + 3_700_000)
    eng.finish(T0 + 3_700_000)
    rows, tb = rows_of(eng)
    assert rows["t5"]["filled"] == 0 and rows["t5"]["peak3x"] == 0.0


# ---------------------------------------------------------------- the simulator against the pipeline

def test_the_policy_simulator_matches_the_pipeline_on_the_same_path():
    ex = P.Exits(60, 0.3, ((0.5, 1.0),), None, None)
    s = P.EarlyStrategy("X5", "B", "checkpoint", 0.5, 0.3, 60, {"w_s": 5}, "test", exits=ex, flt={})
    eng = sim.Engine([], costs=Fixed(), strategies=[s], early_rows=True)
    cv = Curve(eng)
    cv.buy(T0, SOL, DEV, same_tx=True)
    for i in range(6):
        cv.buy(T0 + 7_000 + i * 1_500, 3 * SOL, BUYERS[i])    # up past +50 % after the 5 s landing
    eng.advance(T0 + 3_700_000)
    eng.finish(T0 + 3_700_000)
    pipe = [t for t in eng.closed if t["rule"] == "X5"][0]
    tb = eng.early.tables()
    data = {"paths": tb["paths"], "mints": tb["mints"], "gaps": tb["gaps"]}
    i = [k for k in range(len(tb["paths"]["i_pos"])) if tb["rows"]["kind"][int(tb["paths"]["i_row"][k])] == 0][0]
    pv = X.PathView(data["paths"], i)
    pol = X.Policy("TS", time_s=60, sl=0.3, tp=0.5, events=True)
    r = X.simulate(pol, pv, lambda leg: 1000.0, Fixed().tx_lamports())
    assert pipe["exit_why"] == "take" and r["why"] == "take"
    assert r["ret"] == pytest.approx(pipe["ret"], abs=1e-6)
    assert X.best_gain(pv, Fixed().tx_lamports()) >= r["pnl_l"]


def test_ladders_events_and_the_time_stop_in_the_simulator():
    eng = early_engine()
    cv = Curve(eng)
    dev_tok = cv.buy(T0, 3 * SOL, DEV, same_tx=True)
    cv.buy(T0 + 8_000, 12 * SOL, BUYERS[0])                   # +100 % or so for the 5 s buy
    cv.buy(T0 + 20_000, 40 * SOL, BUYERS[1])                  # far more
    cv.sell(T0 + 40_000, dev_tok // 2, DEV)                   # then the dev sells half
    eng.advance(T0 + 3_700_000)
    eng.finish(T0 + 3_700_000)
    tb = eng.early.tables()
    i = [k for k in range(len(tb["paths"]["i_pos"])) if tb["rows"]["kind"][int(tb["paths"]["i_row"][k])] == 0][0]
    pv = X.PathView(tb["paths"], i)
    tx = Fixed().tx_lamports()
    lad = X.simulate(X.Policy("L", sl=0.35, ladder=((0.5, 0.5), (50.0, 1.0)), events=True), pv, lambda l: 1000.0, tx)
    assert lad["legs"] == 2 and lad["why"] == "dev_sell" and lad["ret"] > 0.5
    no_ev = X.simulate(X.Policy("L", sl=0.95, ladder=((50.0, 1.0),), events=False, time_s=120), pv,
                       lambda l: 1000.0, tx)
    assert no_ev["why"] == "time" and no_ev["exit_ms"] == pytest.approx(pv.land + 121_000)
    cap = X.capture([lad, no_ev], [X.best_gain(pv, tx)] * 2)
    assert 0 < cap["ratio"] <= 1 and cap["never_above_cost"] == 0


def test_step_labels_dump_and_upside():
    eng = early_engine()
    cv = Curve(eng)
    cv.buy(T0, SOL, DEV, same_tx=True)
    a = cv.buy(T0 + 6_500, 10 * SOL, BUYERS[0])
    cv.buy(T0 + 9_000, 10 * SOL, BUYERS[1])                   # up within 30 s of the 6 s step
    cv.sell(T0 + 12_000, a, BUYERS[0])                        # down a lot within 10 s of the 9 s step
    eng.advance(T0 + 3_700_000)
    eng.finish(T0 + 3_700_000)
    tb = eng.early.tables()
    lab = X.step_labels(tb["paths"], tb["steps"], Fixed().tx_lamports())
    st = tb["steps"]
    first = st["pos"] == st["pos"][0]
    t = st["t"][first]
    assert lab["up30"][first][t == T0 + 6_000][0] > 0       # the landing step of the 5 s buy sees the run
    hit = lab["dump10"][first][t == T0 + 9_000]
    assert hit.size and hit[0] == 1.0


# ---------------------------------------------------------------- the pipeline's hazard exit and early filter

class Const:
    """A stand-in model: a constant prediction."""
    def __init__(self, v, base=0.1, features=None):
        self.v, self.base, self.booster, self.features = v, base, object(), features or ["tau_s"]

    def predict(self, X):
        return np.full(len(X), self.v)


def test_the_hazard_exit_sells_when_the_upside_is_below_the_weighted_loss():
    s = [x for x in P.STRATEGIES if x.name == "P_press10_hz"][0]
    hz = {"hz_dump10": Const(0.9), "hz_up30": Const(0.01), "hz_policy": X.HzPolicy(1.0, 0.5, {})}
    for models, why in ((hz, "hazard"), ({}, "time")):
        eng = sim.Engine([], costs=Fixed(), strategies=[s], models=dict(models))
        cv = Curve(eng)
        for i in range(12):
            cv.buy(T0 + 500 + i * 500, SOL // 2, BUYERS[i])      # 10+ buyers, 2+ SOL: P_press10's entry
        for i in range(30):
            cv.buy(T0 + 12_000 + i * 60_000, SOL // 100, BUYERS[20 + i % 20])
        eng.advance(T0 + 3_000_000)
        t = [c for c in eng.closed if c["rule"] == "P_press10_hz"]
        assert t and t[0]["exit_why"] == why, (why, t)


def test_the_early_strategy_needs_its_models_and_its_threshold():
    s = [x for x in P.STRATEGIES if x.name == "P_early10"][0]
    feats = E.early_feature_list()
    pol = X.HzPolicy(1.0, 0.5, {"peak3x": {"0.05": {"t10": 0.5}}})
    for models, entered in (({}, False), ({"e_peak3x": Const(0.9, features=feats), "e_alive5m": Const(0.9, 0.5, feats),
                                           "hz_policy": pol}, True),
                            ({"e_peak3x": Const(0.2, features=feats), "e_alive5m": Const(0.9, 0.5, feats),
                              "hz_policy": pol}, False)):
        eng = sim.Engine([], costs=Fixed(), strategies=[s], models=models)
        cv = Curve(eng)
        cv.buy(T0 + 1_000, SOL, BUYERS[0])
        eng.advance(T0 + 20_000)
        assert (eng.counts["pipe_signals"] == 1) == entered


# ---------------------------------------------------------------- end to end

def x14_data(tmp_path):
    from lab.pumpfun_rt import store
    from test_pumpfun_rt import synth_store
    synth_store(tmp_path, hours=8)
    eng = sim.Engine([], early_rows=True)
    sim.replay(store.days(tmp_path), eng, tmp_path)
    tb = eng.early.tables()
    E.save(tb, tmp_path / "rows", {"split_ms": None})
    return E.load(tmp_path / "rows")


def test_the_evaluation_runs_end_to_end_and_the_models_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(M, "MIN_TRAIN", 100)
    monkeypatch.setattr(M, "MIN_TEST", 30)
    monkeypatch.setattr(X, "MIN_STEPS", 100)
    monkeypatch.setattr(X, "DUMP_DROP", 0.02)                # the synthetic curves fall gently
    data = x14_data(tmp_path)
    assert len(data["rows"]["t"]) > 500 and len(data["paths"]["i_pos"]) > 100
    res = X.run(data, log=lambda *a: None)
    assert set(res["early"]) == set(E.LABELS) and len(res["exit"]["table"]) == len(X.GRID) == 38
    md = X.report_md(res, "2026-10-21")
    assert "—" not in md and "## 2. Exit timing" in md and "| peak3x |" in md
    assert res["hazard_models"]["is_with_preds"] > 0 and res["exit"]["judge"]["hz_pick"] is not None
    summ = X.summary(res)
    assert summ["pick"] in {p.name for p in X.GRID}
    import json
    json.dumps(X.jsonable(res), default=str)
    models = X.fit_live(data, k=2.0, log=lambda *a: None)
    X.save_models(models, tmp_path / "m")
    back = M.load(tmp_path / "m")
    assert back["hz_policy"].k == 2.0 and "e_peak3x" in back
    if "hz_up30" in models:
        f = {k: 0.0 for k in E.STEP_FEATURES}
        x = np.array([[f[k] for k in back["hz_up30"].features]])
        assert np.isfinite(back["hz_up30"].predict(x)).all()


def test_the_grid_is_what_the_plan_says():
    names = [p.name for p in X.GRID]
    assert len(names) == len(set(names)) == 38
    assert sum(p.hazard_k is not None for p in X.GRID) == 8
    assert X.E0.ladder == ((1.0, 0.5), (3.0, 1.0)) and X.E0.sl == 0.35 and X.E0.time_s == 1800
    assert P.E0.ladder == X.E0.ladder and P.HZ_EXITS.hazard and P.E0.trail_gap == X.E0.trail_gap


def test_the_daily_card_line_in_english_and_german():
    from test_i18n import no_english
    y = "2026-10-19"
    data = {"record": {y: {"tokens": 90_000, "trades": 4_000_000, "completed": 900}}, "days": [y], "results": []}
    models = {"labels": {}, "useful": 0, "x14": {"pick": "HZ1+ev", "base_pick": "TR25_50+ev", "capture_pick": 0.31,
                                                 "capture_base": 0.22, "prec5_peak3x": 0.12, "rate_peak3x": 0.02,
                                                 "lift5_peak3x": 6.0}}
    now = int(datetime(2026, 10, 20, 7, tzinfo=timezone.utc).timestamp() * 1000)
    en = CARD.daily_card(data, models, {}, None, now, "en").render("telegram", "en")
    de = CARD.daily_card(data, models, {}, None, now, "de").render("telegram", "de")
    assert "HZ1+ev keeps +31%" in en and "6.0x" in en
    assert "HZ1+ev" in de and "Dreifache" in de
    no_english(de)
    models["x14"]["capture_pick"] = math.nan
    assert "n/a" in CARD.daily_card(data, models, {}, None, now, "en").render("telegram", "en")


def test_nothing_new_can_sign_or_send():
    import inspect
    for mod in (E, X):
        src = inspect.getsource(mod)
        for word in ("Keypair", "sign(", "sendTransaction", "private_key", "secret"):
            assert word not in src, (mod.__name__, word)
    assert key(1)
