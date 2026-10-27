"""M1: the model factory's learners, the foundation-model forecasts, conformal intervals and meta-labelling.

No network, no lab data, no torch: the foundation models and TabPFN are tiny fakes. Run from research/lab:
python -m pytest tests/test_modern_m1.py
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from lab.experiments import modern_m1 as M1
from lab.models import conformal as CF
from lab.models import factory as F
from lab.models import fm
from lab.models import metalabel as ML

DAY_US = 86_400_000_000
T0 = 1_704_067_200_000_000                       # 2024-01-01
LAB = Path(__file__).resolve().parents[1]


def data(n=600, k=6, seed=1):
    rng = np.random.default_rng(seed)
    X = rng.standard_normal((n, k))
    y = (X[:, 0] + 0.5 * rng.standard_normal(n) > 0).astype(float)
    X[rng.random((n, k)) < 0.05] = np.nan
    return X, y


# ---------------------------------------------------------------- the model factory

def test_learner_list_has_catboost_next_to_lightgbm_and_tabpfn():
    names = list(F.LEARNERS)
    assert names.index("catboost") == names.index("hgb") + 1 and names.index("lgb") < names.index("catboost")
    assert "tabpfn" in names and F.BASELINE == "base"
    assert F.TABPFN["revision"] and len(F.TABPFN["revision"]) == 40 and "Prior Labs License" in F.TABPFN["licence"]


@pytest.mark.parametrize("name", ["base", "logit", "lgb", "hgb"])
def test_lab_image_learners_fit_and_predict(name):
    X, y = data()
    m = F.make(name).fit(X[:400], y[:400])
    p = m.predict_proba(X[400:])
    assert p.shape == (200,) and np.all((p >= 0) & (p <= 1))
    if name != "base":
        assert F.core.logloss(y[400:], p).mean() < F.core.logloss(y[400:], np.full(200, y[:400].mean())).mean()


def test_catboost_learns_when_installed():
    pytest.importorskip("catboost")
    X, y = data()
    p = F.make("catboost").fit(X[:400], y[:400]).predict_proba(X[400:])
    assert F.core.logloss(y[400:], p).mean() < F.core.logloss(y[400:], np.full(200, y[:400].mean())).mean()


def test_one_class_is_the_base_rate():
    X, _ = data(50)
    p = F.make("logit").fit(X, np.ones(50)).predict_proba(X)
    assert np.allclose(p, 1.0)


def test_missing_package_is_unavailable_with_the_reason(monkeypatch):
    import importlib.util
    real = importlib.util.find_spec
    monkeypatch.setattr(importlib.util, "find_spec", lambda n, *a: None if n in ("catboost", "tabpfn", "torch")
                        else real(n, *a))
    ok, why = F.available("catboost")
    assert not ok and "catboost" in why and "Dockerfile.ml" in why
    with pytest.raises(F.Unavailable):
        F.make("tabpfn")


def test_tabpfn_row_cap_skips_with_a_clear_message(monkeypatch):
    monkeypatch.setattr(F, "TABPFN_MAX_ROWS", 100)
    with pytest.raises(F.TooLarge, match="over the CPU cap of 100"):
        F.TabPFN().check(101, 10)
    F.TabPFN().check(100, 10)
    with pytest.raises(F.TooLarge):
        F.TabPFN().check(10, F.TABPFN_MAX_FEATURES + 1)


def test_pinned_file_offline_never_downloads(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTHIA_HUB_DIR", str(tmp_path))
    monkeypatch.setenv("PYTHIA_HUB_OFFLINE", "1")
    with pytest.raises(F.Unavailable):
        F.pinned_file("org/model", "0" * 40, "w.ckpt")


class Spy(F.Learner):
    NAME = "spy"
    seen: list = []

    def fit(self, X, y):
        Spy.seen.append(len(y))
        self._base(y)
        return self

    def predict_proba(self, X):
        return np.full(len(X), self.base)


def test_walk_trains_on_known_labels_only_and_reports_skips(monkeypatch):
    monkeypatch.setitem(F.LEARNERS, "spy", Spy)
    monkeypatch.setattr(F, "available", lambda n: (n != "tabpfn", "tabpfn: not installed"))
    Spy.seen = []
    X, y = data(300)
    t = np.arange(300, dtype=float)
    known = t + 10
    w = F.walk(X, y, t, known, [(100, 200), (200, 300)], ["spy", "tabpfn"], min_train=20, log=lambda *_: None)
    assert Spy.seen == [90, 190]                      # labels known before each block, not the 10 days before it
    assert np.isnan(w["p"]["spy"][:100]).all() and np.isfinite(w["p"]["spy"][100:]).all()
    assert "tabpfn" in w["skipped"] and np.isnan(w["p"]["tabpfn"]).all()


def test_gate_is_the_zoo_gate():
    rng = np.random.default_rng(3)
    ts = np.repeat(T0 + np.arange(200) * DAY_US, 5)
    base = rng.random(len(ts)) + 1.0
    better = F.gate(ts, base - 0.3, base, 1)
    same = F.gate(ts, base + 0.01 * rng.standard_normal(len(ts)), base, 1)
    assert better["passed"] and better["dm_p"] < 0.05
    assert not same["passed"] and "the gate needs lower" in same["why"]
    assert not F.gate(ts[:10], base[:10] - 1, base[:10])["passed"]


def test_members_are_lent_to_the_pumpfun_zoo_for_one_run_only(monkeypatch):
    from lab.pumpfun_rt import selector as S
    from lab.pumpfun_rt import zoo as Z
    monkeypatch.setitem(F.LEARNERS, "catboost", Spy)
    monkeypatch.setattr(F, "available", lambda n: (True, ""))
    before = dict(Z.MEMBERS)
    X, y = data(2400)
    t0 = 1_792_540_800_000                           # 2026-10-20 in ms
    t = t0 + np.sort(np.random.default_rng(2).uniform(0, 4 * 86_400_000, 2400))
    tab = {"label": "win0t", "family": "select", "kind": "any", "t": t, "y": y, "X": X,
           "features": [f"f{i}" for i in range(X.shape[1])], "h_ms": 600_000, "heat": X[:, :1]}
    with F.members(("catboost",)) as lent:
        assert lent == ["catboost"] and "catboost" in Z.MEMBERS
        out = S.walk(tab, ["2026-10-22", "2026-10-23"], ["catboost", "logit"], log=lambda *_: None)
    assert dict(Z.MEMBERS) == before
    assert all(set(x["p"]) == {"catboost", "logit"} for x in out)


# ---------------------------------------------------------------- foundation models

class Fake(fm.Forecaster):
    """The last value as the median, +-1 around it; counts its calls."""
    name, revision = "fake", "f" * 40

    def __init__(self):
        self.calls = 0

    def quantiles(self, contexts):
        self.calls += len(contexts)
        last = np.array([c[np.isfinite(c)][-1] for c in contexts])
        return np.column_stack([last + 1, last, last - 1])   # crossed on purpose: forecast_panel sorts them


def panel(n=120, syms=("A", "B"), seed=0):
    rng = np.random.default_rng(seed)
    rows = []
    for s in syms:
        v = rng.standard_normal(n).cumsum()
        rows += [{"ts_us": T0 + i * DAY_US, "symbol": s, "x": float(v[i])} for i in range(n)]
    return pl.DataFrame(rows).sort(["ts_us", "symbol"])


def test_forecast_uses_only_the_past_window_and_caches(tmp_path):
    p = panel()
    f = Fake()
    cache = fm.Cache("fake", f.revision, "x", root=tmp_path)
    Q, info = fm.forecast_panel(p, "x", f, T0 + 70 * DAY_US, 60, cache=cache, log=lambda *_: None)
    ts = p["ts_us"].to_numpy()
    m = ts >= T0 + 70 * DAY_US
    assert np.isnan(Q[~m]).all() and np.isfinite(Q[m]).all() and info["complete"]
    assert np.all(Q[m, 0] <= Q[m, 1]) and np.allclose(Q[m, 1], p["x"].to_numpy()[m])
    # every later value changed: the forecasts up to day 90 stay the same
    p2 = p.with_columns(x=pl.when(pl.col("ts_us") > T0 + 90 * DAY_US).then(pl.col("x") * 7 + 3).otherwise(pl.col("x")))
    Q2, _ = fm.forecast_panel(p2, "x", Fake(), T0 + 70 * DAY_US, 60, log=lambda *_: None)
    early = m & (ts <= T0 + 90 * DAY_US)
    assert np.allclose(Q[early], Q2[early])
    f2 = Fake()
    Q3, info3 = fm.forecast_panel(p, "x", f2, T0 + 70 * DAY_US, 60, cache=fm.Cache("fake", f.revision, "x", root=tmp_path),
                                  log=lambda *_: None)
    assert f2.calls == 0 and info3["cached"] == int(m.sum()) and np.allclose(Q3[m], Q[m])


def test_forecast_stops_at_the_budget_and_needs_a_context():
    p = panel(n=80)
    Q, info = fm.forecast_panel(p, "x", Fake(), T0, -1.0, log=lambda *_: None)
    assert not info["complete"] and info["computed"] == 0 and np.isnan(Q).all()
    Q, info = fm.forecast_panel(p, "x", Fake(), T0, 60, min_context=60, log=lambda *_: None)
    assert info["computed"] == 2 * (80 - 59)


def test_contexts_and_lognormal_mean():
    v = np.arange(10.0)
    c = fm.contexts_for(v, np.array([0, 5, 9]), context=4)
    assert [list(x) for x in c] == [[0.0], [2.0, 3.0, 4.0, 5.0], [6.0, 7.0, 8.0, 9.0]]
    q = np.array([[-1.2815515655446004, 0.0, 1.2815515655446004]])
    assert np.isclose(fm.lognormal_mean(q)[0], np.exp(0.5))
    for pin in fm.PINS.values():
        assert len(pin.revision) == 40 and pin.licence == "Apache-2.0"


# ---------------------------------------------------------------- conformal

def test_conformal_level_and_rolling_coverage():
    assert CF.level(np.arange(1.0, 11.0), 0.2) == 9.0          # ceil(11 * 0.8) = 9th of 10
    assert CF.level(np.arange(1.0, 4.0), 0.01) == np.inf
    rng = np.random.default_rng(0)
    days = np.repeat(np.arange(400), 10)
    ts = T0 + days * DAY_US
    y = rng.standard_normal(len(ts)) * 2.0
    lo, hi = np.full(len(ts), -1.0), np.full(len(ts), 1.0)        # far too narrow
    raw = CF.coverage(y, lo, hi)["coverage"]
    c = CF.rolling(ts, y, lo, hi, 0.2, window_days=90, min_cal=100)
    late = days >= 200
    cov = CF.coverage(y[late], c["lo"][late], c["hi"][late])["coverage"]
    assert raw < 0.5 and 0.76 < cov < 0.84
    assert np.isnan(c["q"][days < 10]).all()                       # too few calibration rows


def test_conformal_uses_only_earlier_days():
    rng = np.random.default_rng(1)
    days = np.repeat(np.arange(200), 5)
    ts = T0 + days * DAY_US
    y = rng.standard_normal(len(ts))
    z = np.zeros(len(ts))
    a = CF.rolling(ts, y, z, z, 0.2, window_days=60, min_cal=50)
    y2 = np.where(days >= 150, y * 50, y)
    b = CF.rolling(ts, y2, z, z, 0.2, window_days=60, min_cal=50)
    assert np.allclose(a["q"][days <= 150], b["q"][days <= 150], equal_nan=True)
    assert not np.allclose(a["q"][days > 152], b["q"][days > 152])


def test_width_scale_is_bounded_and_causal():
    days = np.arange(300)
    w = np.where(days < 200, 1.0, 4.0)
    s = CF.width_scale(T0 + days * DAY_US, w, window_days=60, min_cal=30)
    assert np.all((s >= CF.SCALE_LO) & (s <= CF.SCALE_HI))
    assert np.all(s[:30] == 1.0) and np.isclose(s[200], 0.25) and np.isclose(s[150], 1.0)


# ---------------------------------------------------------------- meta-labelling

def test_trades_labels_and_filter():
    W = np.zeros((10, 2))
    W[2:5, 0] = 0.5
    W[7:, 0] = 0.5
    W[0:3, 1] = 1.0
    tr = ML.trades(W)
    assert tr == [(1, 0, 3), (0, 2, 5), (0, 7, -1)]
    px = np.ones((10, 2))
    px[5, 0] = 1.02
    px[3, 1] = 1.005
    y = ML.labels(px, tr, 0.01)
    assert list(y[:2]) == [0.0, 1.0] and np.isnan(y[2])
    W2 = ML.filtered(W, tr, np.array([0.2, 0.9, np.nan]))
    assert (W2[0:3, 1] == 0).all() and (W2[2:5, 0] == 0.5).all() and (W2[7:, 0] == 0.5).all()
    assert list(ML.known_at(tr, 10)) == [3, 5, 10]


def test_meta_features_read_only_the_past():
    rng = np.random.default_rng(4)
    T, n = 400, 3
    px = np.exp(np.cumsum(rng.standard_normal((T, n)) * 0.02, axis=0))
    W = (rng.random((T, n)) > 0.7).astype(float) * 0.3
    tr = ML.trades(W)
    X = ML.features(px, W, tr, 0)
    k = next(i for i, x in enumerate(tr) if x[1] > 250)
    a = tr[k][1]
    px2, W2 = px.copy(), W.copy()
    px2[a + 1:] *= rng.uniform(0.5, 2.0, (T - a - 1, n))
    W2[a + 1:] = (rng.random((T - a - 1, n)) > 0.5) * 0.3
    tr2 = ML.trades(W2)
    k2 = next(i for i, x in enumerate(tr2) if x[:2] == tr[k][:2])
    X2 = ML.features(px2, W2, tr2, 0)
    assert np.allclose(X[k], X2[k2], equal_nan=True)
    assert X.shape == (len(tr), len(ML.FEATURES))


# ---------------------------------------------------------------- the study's pieces

def test_next_log_volume_and_its_baseline():
    rows = [{"ts_us": T0 + i * DAY_US, "symbol": "A", "qv": float(np.exp(i))} for i in range(10)]
    rows.append({"ts_us": T0 + 12 * DAY_US, "symbol": "A", "qv": 1.0})           # a gap: no target
    h = M1.next_log_volume(pl.DataFrame(rows))
    assert h["lqv_next"].to_list()[:3] == [1.0, 2.0, 3.0]
    assert h["lqv_next"][9] is None and h["lqv_base"][6] == pytest.approx(3.0) and h["lqv_base"][5] is None


def test_boot_sharpe_difference():
    rng = np.random.default_rng(5)
    a = rng.standard_normal(600) * 0.01 + 0.002
    b = rng.standard_normal(600) * 0.01
    r = M1.boot_sharpe_diff(a, b, draws=300)
    assert r["sharpe"] > r["other"] and r["p_better"] > 0.9
    assert M1.boot_sharpe_diff(a[:4], b[:4])["p_better"] is None


def test_rule_probability_is_fitted_before_each_block():
    rule = np.r_[np.ones(100), np.zeros(100), np.ones(100)]
    y = np.r_[np.ones(100), np.zeros(100), np.ones(100) * 0.0]
    t = np.arange(300.0)
    p = M1.rule_probability(rule, y, t + 7, t, [(200, 300)])
    assert np.isnan(p[:200]).all() and np.allclose(p[200:], 1.0)    # the rule was on in up weeks before 200


def test_markdown_of_a_small_run_has_no_em_dash():
    res = {"run": "2026-10-27", "timing": {"conformal": {"seconds": 1.0, "peak_mb": 100.0}},
           "parts": {"tabular": {"labels": {"win0t": {"note": "no rows"}}, "comparisons": [], "skipped":
                                 {"tabpfn": "tabpfn: tabpfn, torch not installed"}},
                     "fm": {"skipped": "no holdout of m8_quantiles"}}}
    md = M1.markdown(res)
    assert "\u2014" not in md and "tabpfn, torch not installed" in md and "## Runtime" in md


def test_dockerfile_ml_pins_every_package_and_uses_cpu_torch():
    s = (LAB / "Dockerfile.ml").read_text(encoding="utf-8")
    assert re.search(r"^FROM pythia-lab$", s, re.M)
    assert "download.pytorch.org/whl/cpu torch==" in s
    pkgs = re.findall(r"(?<=\s)([A-Za-z][A-Za-z0-9_.-]*)(==|>=|<=|~=)?([0-9][^\s\\]*)?(?=\s)",
                      s.split("pip install --no-cache-dir \\", 1)[1].split("&& python", 1)[0])
    names = [p[0] for p in pkgs]
    assert {"chronos-forecasting", "timesfm", "tabpfn", "catboost"} <= set(names)
    assert all(op == "==" for _, op, _ in pkgs)
    assert "\u2014" not in s


def test_ml_job_runs_the_study_in_the_ml_image():
    from lab.ops import jobs
    t = jobs.load_table(LAB.parent / "ops" / "jobs.yaml")
    j = t.jobs["modern-models"]
    assert j["image"] == "pythia-lab-ml" and j["code"] and j["command"].startswith("python -m lab.experiments.modern_m1")
    assert j["locks"] == ["heavy"] and j["resources"]["memory"] == "6g"
    assert [n for n, x in t.jobs.items() if x["image"] == "pythia-lab-ml"] == ["modern-models"]
