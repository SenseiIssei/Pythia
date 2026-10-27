"""G2: the model factory's specs, purged walk-forward, bar over all trials, shadows, allocator, job and briefing line.

Synthetic panels only (lab.models.daily.synthetic_daily), no lab data. Run from research/lab:
python -m pytest tests/test_model_factory_g2.py
"""

from __future__ import annotations

import json
import random
import re
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from lab.models import daily
from lab.models import factory as F
from lab.models import m8_direction as m8
from lab.models import m10_vol_regime as m10
from lab.ops import briefing

DAY_US = 86_400_000_000
NOW_MS = 1_793_059_200_000                       # 2026-10-27
LAB = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def raw():
    return daily.enrich(daily.synthetic_daily(3220, bases=("BTC", "ETH", "SOL", "XRP", "ADA"), seed=3))


def planted(raw: pl.DataFrame, edge: float = 0.6) -> pl.DataFrame:
    """fwd7's panel with a target that ret1 explains (a real edge), open for the last 7 days."""
    p = F.fwd_panel(raw)
    rng = np.random.default_rng(0)
    r1 = p["ret1"].fill_null(0.0).to_numpy()
    y = edge * r1 / (np.std(r1) + 1e-12) + rng.standard_normal(p.height)
    last = p["ts_us"].max()
    return p.with_columns(target=pl.when(pl.col("ts_us") > last - 7 * DAY_US).then(None).otherwise(pl.Series(y)))


@pytest.fixture
def dirs(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTHIA_MODEL_FACTORY_DIR", str(tmp_path / "mf"))
    monkeypatch.setenv("PYTHIA_REPORTS", str(tmp_path / "reports"))
    monkeypatch.setenv("PYTHIA_MODEL_FACTORY_SEED", str(tmp_path / "no_seed"))
    monkeypatch.delenv("PYTHIA_MODEL_FACTORY_BUDGET", raising=False)
    monkeypatch.setattr(F, "zoo_log", lambda name: tmp_path / "zoo" / name / "shadow.jsonl")
    return tmp_path


def spec(t="fwd7", features=("ret1", "ret7", "h7"), learner="ridge", params=None, trees=(), window=None):
    return F.canonical_spec({"target": t, "features": list(features), "trees": list(trees), "learner": learner,
                             "params": params or {"alpha": 1.0}, "window": window})


# ---------------------------------------------------------------- folds and leakage

def test_blocks_are_quarters_and_training_labels_end_before_the_test_starts():
    b = F.blocks("2021-01-01", "2024-01-01")
    assert len(b) == 12 and b[0][0] == F.core.us("2021-01-01") and b[-1][1] == F.core.us("2024-01-01")
    assert all(hi == lo2 for (_, hi), (lo2, _) in zip(b, b[1:]))
    ts = F.core.us("2020-06-01") + np.arange(600) * DAY_US
    lo, hi = F.core.us("2021-07-01"), F.core.us("2021-10-01")
    for purge in (1, 7, 32):
        tr, te = F.split(ts, purge, lo, hi, None)
        assert np.all(ts[tr] + purge * DAY_US < lo)                 # no training label reaches the test block
        assert ts[tr].max() + (purge + 1) * DAY_US >= lo            # and nothing more is dropped
        assert np.all((ts[te] >= lo) & (ts[te] < hi))
    tr, _ = F.split(ts, 1, lo, hi, 365)
    assert ts[tr].min() >= lo - 365 * DAY_US


@pytest.mark.parametrize("t,learner,params,trees", [
    ("fwd7", "ridge", {"alpha": 1.0}, [{"op": "rank", "args": [{"op": "ret", "n": 5, "args": [{"op": "close"}]}]}]),
    ("m8", "lgb", {"n_estimators": 100, "learning_rate": 0.05, "num_leaves": 7, "min_leaf": 50, "reg_lambda": 1.0},
     [{"op": "z", "n": 20, "args": [{"op": "upper_w"}]}]),
    ("m10", "lgb", {"n_estimators": 100, "learning_rate": 0.05, "num_leaves": 7, "min_leaf": 50, "reg_lambda": 1.0}, []),
])
def test_changing_the_future_moves_no_score_before_it(raw, t, learner, params, trees):
    """Leakage: every row after a cut (features, prices, targets) replaced by noise, and the targets of rows whose
    label was not known by then too. Forecasts, baselines, the incumbent and tree inputs at or before the cut stay
    the same, and so does every loss whose label was known by then."""
    base = {"m8": lambda: m8.panel_from(raw), "m10": lambda: m10.panel_from(raw), "fwd7": lambda: F.fwd_panel(raw)}[t]()
    cut = F.core.us("2022-08-15")
    purge = F.TARGETS[t]["purge"]
    rng = np.random.default_rng(1)
    after = base["ts_us"].to_numpy() > cut
    unknown = base["ts_us"].to_numpy() + purge * DAY_US >= cut
    cols = [c for c in base.columns if c not in ("ts_us", "symbol") and base[c].dtype.is_numeric()]
    noise = {c: pl.when(pl.Series(after)).then(pl.Series(np.abs(rng.standard_normal(base.height)) + 0.1))
             .otherwise(pl.col(c)) for c in cols}
    changed = base.with_columns(**noise)
    tgt = (rng.random(base.height) > 0.5).astype(float) if t == "m8" else np.abs(rng.standard_normal(base.height)) + 0.01
    changed = changed.with_columns(target=pl.when(pl.Series(unknown)).then(pl.Series(tgt)).otherwise(pl.col("target")))
    feats = F.feature_pool(t, base)[:8]
    s = spec(t, feats, learner, params, trees)
    out = []
    for panel in (base, changed):
        P = F.Panels({t: lambda panel=panel: panel})
        pred, bl = F.walk_spec(P, t, s, "2021-01-01", "2023-01-01")
        inc = F.walk_incumbent(P, t, "2021-01-01", "2023-01-01") if t == "m8" else None
        y = P.get(t)["target"].fill_null(np.nan).to_numpy().astype(float)
        out.append((pred, bl, inc, F.matrix(P, t, s), F.loss_of(t, y, pred)))
    ts = base["ts_us"].to_numpy()
    before, scored = ts <= cut, (ts + purge * DAY_US < cut) & (ts >= F.core.us("2021-01-01"))
    (p0, b0, i0, x0, l0), (p1, b1, i1, x1, l1) = out
    assert np.isfinite(p0[before & (ts >= F.core.us("2021-01-01"))]).all()
    np.testing.assert_array_equal(p0[before], p1[before])
    np.testing.assert_array_equal(b0[before], b1[before])
    np.testing.assert_array_equal(x0[before], x1[before])
    np.testing.assert_array_equal(l0[scored], l1[scored])
    if i0 is not None:
        np.testing.assert_array_equal(i0[before], i1[before])
    assert not np.allclose(np.nan_to_num(p0[~before]), np.nan_to_num(p1[~before]))   # the future did change


def test_tree_inputs_read_only_the_past(raw):
    p = F.fwd_panel(raw)
    tree = {"op": "diff", "args": [{"op": "ma", "n": 10, "args": [{"op": "close"}]}, {"op": "z", "n": 20, "args": [{"op": "range"}]}]}
    x0 = F.tree_column(p, tree)
    cut = F.core.us("2021-03-01")
    q = p.with_columns(close=pl.when(pl.col("ts_us") > cut).then(pl.col("close") * 3.0).otherwise(pl.col("close")))
    x1 = F.tree_column(q, tree)
    m = p["ts_us"].to_numpy() <= cut
    np.testing.assert_array_equal(x0[m], x1[m])
    assert np.isfinite(x0[~m]).mean() > 0.5


# ---------------------------------------------------------------- specs

def test_a_spec_is_one_key_whatever_the_order_and_a_mutation_is_a_new_one():
    a = spec(features=("h7", "ret1", "ret7"))
    b = spec(features=("ret7", "h7", "ret1"))
    assert F.spec_key(a) == F.spec_key(b) and len(F.spec_key(a)) == 12
    rng = random.Random(0)
    pool = ["ret1", "ret3", "ret7", "h1", "h7", "h30", "qv_z"]
    for _ in range(20):
        m = F.mutate(a, rng, pool, True)
        assert F.spec_key(m) != F.spec_key(a) and m["target"] == "fwd7"
        assert m["learner"] in F.learners_for("reg")


@pytest.mark.parametrize("t", list(F.TARGETS))
def test_random_specs_fit_their_target(t):
    rng = random.Random(1)
    pool = ["a", "b", "c", "d", "e", "f"]
    for _ in range(20):
        s = F.random_spec(rng, t, pool, F.TARGETS[t]["trees"])
        assert s["learner"] in F.learners_for(F.TARGETS[t]["kind"]) and set(s["params"]) == set(F.LEARNER_SPACE[s["learner"]])
        assert 3 <= len(s["features"]) <= 6 and s["window"] in F.WINDOWS
        assert not s["trees"] or F.TARGETS[t]["trees"]
    assert "logit" not in F.learners_for("var") and "ridge" not in F.learners_for("clf")


# ---------------------------------------------------------------- the bar

def test_the_bar_counts_every_trial(raw, dirs):
    P = F.Panels({"fwd7": lambda: planted(raw, edge=0.12)})
    row = F.trial(P, spec(), "r1")
    assert row["screen_pass"] and row["fitness"] > 0 and "inc" not in row["screen"]
    h = F.look(P, row, 1, "r1")
    assert h["passed"] and h["bar_p"] == 0.05 and 0 < h["held"]["base"]["dm_p"] < 0.05
    n = int(0.05 / h["held"]["base"]["dm_p"] * 10) + 1          # as many trials as make that p ordinary
    for k in (n // 100 or 1, n):
        h = F.look(P, row, k, "r1")
        assert h["bar_p"] == pytest.approx(0.05 / k)
        assert h["passed"] == (h["held"]["base"]["dm_p"] < 0.05 / k)
    assert not h["passed"]
    looks = F._jl(F.holdout_path())
    assert [x["status"] for x in looks] == ["looking", "done"] * 3 and [x.get("look") for x in looks[::2]] == [1, 2, 3]
    j = {"base": {"model": 1.0, "other": 1.1, "dm_p": 0.01}, "inc": {"model": 1.0, "other": 0.9, "dm_p": 0.001}}
    assert not F.beats(j, 0.05)                                  # worse than the incumbent: no pass
    j["inc"]["other"] = 1.2
    assert F.beats(j, 0.05) and not F.beats(j, 0.005)


def test_noise_does_not_pass(raw, dirs):
    p = F.fwd_panel(raw)
    P = F.Panels({"fwd7": lambda: p})
    rng = random.Random(5)
    rows = [F.trial(P, F.random_spec(rng, "fwd7", F.feature_pool("fwd7", p), False), "r") for _ in range(4)]
    assert not any(r["screen_pass"] for r in rows)


# ---------------------------------------------------------------- the run, resumable

def test_run_spends_the_budget_resumes_and_never_repeats_a_trial(raw, dirs):
    L = {"fwd7": lambda: F.fwd_panel(raw)}
    d1 = F.run(NOW_MS, budget_s=10 ** 6, loaders=L, targets=["fwd7"], max_trials=3, log=lambda *_: None)
    d2 = F.run(NOW_MS, budget_s=10 ** 6, loaders=L, targets=["fwd7"], max_trials=2, log=lambda *_: None)
    rows = F._jl(F.ledger_path())
    assert d1["trials_today"] == 3 and d2["trials_today"] == 2 and d2["trials_ever"] == 5
    assert len({r["key"] for r in rows}) == len(rows) == 5
    st = json.loads((F.mf_dir() / "state.json").read_text())
    assert st["day"] == "2026-10-27" and st["used_s"] > 0
    d3 = F.run(NOW_MS, budget_s=st["used_s"], loaders=L, targets=["fwd7"], log=lambda *_: None)
    assert d3["trials_today"] == 0                               # the day's budget is spent
    assert (dirs / "reports" / "models" / "factory.md").exists()
    doc = json.loads((dirs / "reports" / "models" / "factory.json").read_text())
    assert doc["title"] == "Model factory (G2)" and doc["trials_ever"] == 5 and doc["updated_ms"] == NOW_MS


def test_the_seed_is_merged_once_and_counts(raw, dirs):
    L = {"fwd7": lambda: F.fwd_panel(raw)}
    F.run(NOW_MS, budget_s=10 ** 6, loaders=L, targets=["fwd7"], max_trials=2, log=lambda *_: None)
    assert F.export_seed(dirs / "seed") == 2
    line = (dirs / "seed" / "ledger.jsonl").read_text().splitlines()[0]
    assert re.match(r'^\{"key":"[0-9a-f]{12}",', line) and '"why"' not in line
    F.ledger_path().unlink()
    assert F.import_seed(dirs / "seed") == 2 and F.import_seed(dirs / "seed") == 0
    rows = F._jl(F.ledger_path())
    assert all(r["what"] == F.describe_spec(r["spec"]) for r in rows)
    d = F.run(NOW_MS + 86_400_000, budget_s=10 ** 6, loaders=L, targets=["fwd7"], max_trials=1, log=lambda *_: None)
    assert d["trials_ever"] == 3


def test_the_committed_seed_is_the_first_run():
    rows = [json.loads(x) for x in (LAB / "results" / "model_factory_seed" / "ledger.jsonl").read_text().splitlines()]
    assert len(rows) >= 1000 and len({r["key"] for r in rows}) == len(rows)
    assert {r["target"] for r in rows} == set(F.TARGETS) and not any(r["screen_pass"] for r in rows)
    assert all(F.spec_key(r["spec"]) == r["key"] for r in rows[:50])


def test_budget_from_the_environment(raw, dirs, monkeypatch):
    monkeypatch.setenv("PYTHIA_MODEL_FACTORY_BUDGET", "0")
    d = F.run(NOW_MS, loaders={"fwd7": lambda: F.fwd_panel(raw)}, targets=["fwd7"], log=lambda *_: None)
    assert d["trials_today"] == 0 and d["trials_ever"] == 0


def test_a_planted_edge_is_held_back_admitted_and_forecasts_in_shadow(raw, dirs):
    P = F.Panels({"fwd7": lambda: planted(raw)})
    row = F.trial(P, spec(), "r1")
    F._append(F.ledger_path(), [row])
    h = F.look(P, row, 1, "r1")
    assert h["passed"]
    assert F.to_hold([row], F._jl(F.holdout_path())) == []      # never held back twice
    assert F.admit([h], {row["key"]: row}, "2026-10-27") == [row["key"]]
    assert F.admit([h], {row["key"]: row}, "2026-10-28") == []  # once
    out = F.shadow_step(P, NOW_MS, log=lambda *_: None)
    logged = F._jl(F.shadow_log(row["key"]))
    last = P.get("fwd7")["ts_us"].max()
    assert len(logged) == 5 and {r["ts_us"] for r in logged} == {last}
    assert out["members"][0]["status"] == "shadow" and out["members"][0]["logged_today"] == 5
    F.shadow_step(P, NOW_MS + 3_600_000, log=lambda *_: None)
    assert len(F._jl(F.shadow_log(row["key"]))) == 5               # a row is logged once
    assert out["picks"]["fwd7"]["pick"] == "baseline"             # not eligible yet


def test_admit_takes_at_most_two_a_run_and_six_in_all(dirs):
    rows = {f"k{i}": {"key": f"k{i}", "target": "fwd7", "spec": spec(), "what": "x"} for i in range(9)}
    passed = [{"key": k} for k in rows]
    got = [F.admit(passed, rows, f"2026-10-{20 + i}") for i in range(5)]
    assert [len(g) for g in got] == [2, 2, 2, 0, 0]


# ---------------------------------------------------------------- shadows and the allocator

def days(model, baseline, incumbent=None, n=None):
    n = n or len(model)
    return pl.DataFrame({"ts_us": np.arange(n, dtype=np.int64) * DAY_US, "model": np.asarray(model, float),
                         "baseline": np.asarray(baseline, float),
                         "incumbent": np.asarray(incumbent if incumbent is not None else [None] * n, dtype=float)})


def test_eligible_after_30_days_retired_after_60_behind():
    m = {"status": "shadow"}
    F.review(m, days(np.full(29, 1.0), np.full(29, 1.1)), "d")
    assert m["status"] == "shadow" and m["scored_days"] == 29
    F.review(m, days(np.full(30, 1.0), np.full(30, 1.1)), "d30")
    assert m["status"] == "eligible" and m["eligible_day"] == "d30"
    F.review(m, days(np.full(80, 1.0), np.full(80, 1.1), np.full(80, 1.05)), "d80")
    assert m["status"] == "eligible"                              # ahead of both
    worse_base = {"status": "eligible"}
    F.review(worse_base, days(np.r_[np.full(20, 0.5), np.full(60, 1.2)], np.full(80, 1.1)), "x")
    assert worse_base["status"] == "retired" and "baseline" in worse_base["why"]
    worse_inc = {"status": "eligible"}
    F.review(worse_inc, days(np.full(70, 1.0), np.full(70, 1.1), np.full(70, 0.9)), "y")
    assert worse_inc["status"] == "retired" and "incumbent" in worse_inc["why"]
    early = {"status": "shadow"}
    F.review(early, days(np.full(59, 2.0), np.full(59, 1.0)), "z")
    assert early["status"] == "eligible"                          # 60 days before a verdict


def test_allocator_prefers_the_member_with_lower_losses_and_is_seeded_by_the_day():
    n = 90
    rng = np.random.default_rng(0)
    inc = pl.DataFrame({"ts_us": np.arange(n, dtype=np.int64) * DAY_US, "loss": 1.0 + 0.1 * rng.standard_normal(n)})
    good = inc.with_columns(loss=pl.col("loss") - 0.15)
    a = F.allocate("m8", {"incumbent": inc, "abc": good}, "2026-10-27")
    assert a["pick"] == "abc" and a["arms"]["abc"]["p_best"] > 0.95 and a["days"] == n
    assert F.allocate("m8", {"incumbent": inc, "abc": good}, "2026-10-27") == a
    alone = F.allocate("m8", {"incumbent": inc}, "2026-10-27")
    assert alone["pick"] == "incumbent" and "no shadow" in alone["why"]


def test_daily_losses_join_the_zoos_logged_forecasts(raw):
    p = m8.panel_from(raw)
    known = p.drop_nulls("target").tail(10)
    logged = [{"ts_us": int(t), "symbol": s, "pred": 0.6, "baseline": 0.5}
              for t, s in zip(known["ts_us"].to_list(), known["symbol"].to_list())]
    inc = [dict(r, pred=0.4) for r in logged[:5]]
    d = F.daily_losses("m8", logged, p, inc)
    assert d["model"].null_count() == 0 and d.height == known["ts_us"].n_unique()
    assert d["incumbent"].drop_nulls().len() >= 1
    empty = F.daily_losses("m8", [], p, [])
    assert empty.height == 0


# ---------------------------------------------------------------- job, briefing, docs

def test_the_job_runs_daily_after_three_under_the_heavy_lock():
    from lab.ops import jobs
    t = jobs.load_table(LAB.parent / "ops" / "jobs.yaml")
    j = t.jobs["model-factory"]
    minute, hour = j["schedule"].split()[:2]
    assert j["schedule"].endswith("* * *") and int(hour) >= 3 and j["enabled"]
    assert j["command"] == "python -m lab.models.factory" and "heavy" in j["lock"]
    assert int(j["env"]["PYTHIA_MODEL_FACTORY_BUDGET"]) > 0
    others = {x["schedule"] for n, x in t.jobs.items() if n != "model-factory" and x.get("schedule")}
    assert j["schedule"] not in others


def test_the_briefing_shows_the_model_factory_line(dirs):
    rep = {"trials_today": 40, "trials_ever": 1234, "held_today": 2, "passed_today": 1, "retired_today": ["x"],
           "shadows": [{"status": "shadow"}, {"status": "eligible"}, {"status": "retired"}]}
    en = briefing.model_factory_line(rep, "en")
    assert en.lead == "G2 models" and "40 specs last night" in en.text and "passed 1" in en.text
    assert "shadows 2 (1 eligible), 1 retired" in en.text
    de = briefing.model_factory_line(rep, "de")
    assert de.lead == "G2 Modelle" and "bestanden 1" in de.text and "\u2014" not in de.text
    assert briefing.model_factory_line(None, "en") is None
    assert [x.text for x in briefing.factory_section({"F3": None, "F2": None}, None, "en", rep)] == [en.text]
    assert briefing.factory_section({"F3": None, "F2": None}, None, "en", None) == []


def test_results_and_docs_name_the_factory():
    text = (LAB / "results" / "model_factory_g2.md").read_text(encoding="utf-8")
    assert "model-factory" in text and "\u2014" not in text
    assert "model-factory" in (LAB.parent / "ops" / "README.md").read_text(encoding="utf-8")
