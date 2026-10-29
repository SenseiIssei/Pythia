"""T1: the leak harness (lab.leak). One planted leak per kind that it must catch (a feature that reads t+1, a label
shifted one day used as an input, a centred rolling window, a genome and a book on tomorrow's return, a spec's tree
that reads tomorrow), the real functions on synthetic data that must pass, the factories' rejections, the health
lines and the weekly report. Synthetic data only. Run from research/lab: python -m pytest tests/test_leak.py
"""

from __future__ import annotations

import json
import random

import numpy as np
import polars as pl
import pytest

from lab import leak
from lab.factory import build, grammar, run as frun
from lab.features import registry as R
from lab.leak import __main__ as job, checks
from lab.models import daily
from lab.models import factory as F
from test_factory import synthetic_panel


@pytest.fixture(scope="module")
def panel():
    return synthetic_panel(T=900, n_other=12)


@pytest.fixture(scope="module")
def ctx(panel):
    return build.make_ctx(panel)


# ---------------------------------------------------------------- the harness itself

def test_arrays_a_read_of_t_plus_1_is_caught_with_its_first_t_and_column():
    x = np.cumsum(np.random.default_rng(0).normal(size=(300, 3)), 0)
    ok = leak.check(lambda a: np.vstack([np.full((1, 3), np.nan), np.diff(a, axis=0)]), x)
    assert ok["ok"] and ok["runs"] == 4 * 4 and not ok["leaks"]
    bad = leak.check(lambda a: np.vstack([np.diff(a, axis=0), np.full((1, 3), np.nan)]), x, columns=["a", "b", "c"])
    assert not bad["ok"]
    f = bad["first"]
    assert f["cut"] == "149" and f["first"] == "149" and f["column"] == "a"          # the row before the cut, first column
    assert {x["kind"] for x in bad["leaks"]} == {"shuffle", "shift", "nan", "recursive"}
    assert "leak: a at 149" in leak.reason(bad)


def test_a_full_sample_statistic_is_caught_and_the_recursive_check_sees_it():
    x = np.random.default_rng(1).normal(size=(200, 2))
    res = leak.check(lambda a: (a - a.mean(0)) / a.std(0), x)
    assert not res["ok"] and res["first"]["first"] == "0"                             # every row moves
    assert "recursive" in {x["kind"] for x in res["leaks"]}


def test_frames_a_centred_rolling_window_is_caught_a_trailing_one_passes():
    rng = np.random.default_rng(2)
    ts = 1_600_000_000_000_000 + np.repeat(np.arange(200), 2) * 86_400_000_000
    df = pl.DataFrame({"ts_us": ts, "asset": ["A", "B"] * 200, "v": rng.normal(size=400)}).with_columns(
        known_us=pl.col("ts_us"))
    roll = lambda c: lambda d: d.sort("asset", "ts_us").select(  # noqa: E731
        "known_us", "asset", m=pl.col("v").rolling_mean(5, center=c).over("asset"))
    assert leak.check(roll(False), df)["ok"]
    bad = leak.check(roll(True), df)
    assert not bad["ok"] and bad["first"]["column"] == "m"
    assert bad["first"]["first"] < bad["first"]["cut"]                               # two rows before the cut move


def test_a_function_that_breaks_on_changed_data_is_not_a_pass():
    x = np.ones((100, 2))

    def fragile(a):
        if np.isnan(a).any():
            raise ValueError("NaN")
        return a
    res = leak.check(fragile, x, kinds=("nan",), recursive=False)
    assert not res["ok"] and res["error"].startswith("ValueError") and leak.reason(res).startswith("could not check")


def test_dataclass_panels_keep_their_index_and_skip_caches(panel):
    q = leak.perturb_panel(panel, 500, "shuffle")
    assert np.array_equal(q.days, panel.days) and q.names == panel.names
    assert np.array_equal(q.px[:501], panel.px[:501], equal_nan=True) and not np.array_equal(q.px, panel.px, equal_nan=True)
    assert np.array_equal(q.extra["qv"][:501], panel.extra["qv"][:501], equal_nan=True)
    cut = leak.cut_panel(panel, 500)
    assert cut.T == 501 and cut.px.shape == (501, panel.N) and cut.btc_on.shape == (501,)


# ---------------------------------------------------------------- features

@pytest.fixture
def planted_features():
    from lab.features import candles as fcd
    R.register(R.Feature("leak_next", "candles", fcd.SRC, "60s", 0, lambda p: pl.col("ret").shift(-1).over("asset")))
    R.register(R.Feature("leak_centred", "candles", fcd.SRC, "60s", 0,
                         lambda p: pl.col("ret").rolling_mean(5, center=True).over("asset")))
    yield
    R.REGISTRY.pop("leak_next")
    R.REGISTRY.pop("leak_centred")


@pytest.mark.parametrize("freq", ["1h", "1d"])
def test_a_feature_that_reads_t_plus_1_or_a_centred_window_is_caught(planted_features, freq):
    t = checks.synthetic_table(["ret"], freq)
    for name in ("leak_next", "leak_centred"):
        res = checks.feature(name, freq, table=t)
        assert not res["ok"] and res["kind"] == "feature" and res["first"]["column"] == name, name
    assert checks.feature("cdl_ret", freq, table=t)["ok"]
    assert R._TABLES == {} or ("candles", freq, ("AAA", "BBB", "CCC")) not in R._TABLES     # the injected table is gone


def test_every_real_feature_passes():
    from lab import features
    for n in features.names():
        f = features.get(n)
        for fq in f.freqs:
            t = checks.synthetic_table(checks.feature_columns(n, fq), fq, f.market)
            res = checks.feature(n, fq, table=t)
            assert res["ok"], (n, fq, leak.reason(res))
    for fq in ("1h", "1d"):
        assert checks.candles(fq)["ok"]


# ---------------------------------------------------------------- the zoo's builders and G2's specs

@pytest.fixture(scope="module")
def hourly():
    return checks.synthetic_hourly(days=330).with_columns(known_us=pl.col("ts_us") + checks.HOUR)


def test_the_zoo_builders_pass(hourly):
    assert checks.check(checks.m8_builder, hourly, n_cuts=2)["ok"]
    fu, oi = checks.synthetic_perp(hourly)
    raw = {"hourly": hourly, "funding": fu.with_columns(known_us=pl.col("funding_time_us")),
           "oi": oi.with_columns(known_us=pl.col("ts_us") + checks.HOUR)}
    assert checks.check(checks.m10_builder, raw, n_cuts=2)["ok"]
    assert all(r["ok"] and r["data"] == "synthetic" for r in checks.zoo(real=False, n_cuts=2))


def test_a_label_shifted_one_day_as_an_input_is_caught(hourly):
    from lab.models import m8_direction as m8
    res = checks.check(lambda h: checks.m8_builder(h, m8.FEATURES + ["ret_next"]), hourly, n_cuts=2)
    assert not res["ok"] and res["first"]["column"] == "ret_next"
    from lab.models import m12_cross_asset as m12
    b, s = m12.synthetic(900)
    raw = {"btc": checks.closes_frame(b), "spy": checks.closes_frame(s)}
    res = checks.check(lambda r: checks.m12_builder(r, m12.FEATURES + ["target"]), raw, n_cuts=2)
    assert not res["ok"] and res["first"]["column"] == "target"


@pytest.fixture(scope="module")
def fwd():
    return F.fwd_panel(daily.enrich(daily.synthetic_daily(700, bases=("BTC", "ETH", "SOL", "XRP", "ADA"), seed=3)))


def g2spec(trees=()):
    return F.canonical_spec({"target": "fwd7", "features": ["ret1", "ret7", "h7"], "trees": list(trees),
                             "learner": "ridge", "params": {"alpha": 1.0}, "window": None})


def test_g2_specs_with_trees_pass_and_a_tree_on_tomorrow_is_rejected(fwd, monkeypatch):
    rng = random.Random(4)
    for _ in range(6):
        s = g2spec([grammar.random_tree(rng, F.tree_leaves())])
        assert checks.spec(fwd, s, n_cuts=2)["ok"], F.describe_spec(s)
    real = F.tree_column
    monkeypatch.setattr(F, "tree_column", lambda panel, tr: np.roll(real(panel, tr), -5))   # a row of tomorrow
    res = checks.spec(fwd, g2spec([{"op": "ret", "n": 5, "args": [{"op": "close"}]}]), n_cuts=2)
    assert not res["ok"] and res["first"]["column"] == "tree0"
    res = checks.spec(fwd, g2spec(), bad_inputs={"h7"})
    assert not res["ok"] and "h7" in leak.reason(res)


def test_g2_rejects_a_leaky_spec_before_its_look_and_never_holds_it(fwd, tmp_path, monkeypatch):
    monkeypatch.setenv("PYTHIA_MODEL_FACTORY_DIR", str(tmp_path / "mf"))
    monkeypatch.setenv("PYTHIA_REPORTS", str(tmp_path / "reports"))
    P = F.Panels({"fwd7": lambda: fwd})
    row = {"key": "k1", "target": "fwd7", "spec": g2spec(), "screen_pass": True, "fitness": 1.0}
    assert F.leak_reason(P, row, set()) is None
    assert "h7" in F.leak_reason(P, row, {"h7"})
    (tmp_path / "reports" / "leak").mkdir(parents=True)
    (tmp_path / "reports" / "leak" / "latest.json").write_text(json.dumps({"results": [
        {"kind": "zoo", "name": "M8", "ok": False, "first": {"kind": "shuffle", "column": "h7"}}]}))
    assert checks.bad_inputs() == {"h7"} and F.leak_reason(P, row) is not None
    F._append(F.holdout_path(), [{"key": "k1", "status": "leak", "why": "x"}])
    assert F.to_hold([row], F._jl(F.holdout_path())) == []


# ---------------------------------------------------------------- factory genomes

def test_real_tree_genomes_pass(ctx):
    rng = random.Random(8)
    for _ in range(4):
        g = grammar.random_tree_genome(rng)
        res = checks.genome(ctx, g, n_cuts=2)
        assert res["ok"] and res["kind"] == "genome" and res["name"] == grammar.key(g), grammar.describe(g)


def test_a_genome_on_tomorrows_return_is_rejected_logged_and_never_picked(ctx, tmp_path, monkeypatch):
    rng = random.Random(9)
    good, bad = grammar.random_tree_genome(rng), grammar.random_tree_genome(rng)
    real = build.weights

    def weights(c, g):
        W = real(c, g)
        if g is bad:                                  # hold whatever rises tomorrow
            up = np.zeros_like(W)
            up[:-1] = np.nan_to_num(c.ret[1:]) > 0
            return up / np.maximum(up.sum(1, keepdims=True), 1)
        return W
    monkeypatch.setattr(build, "weights", weights)
    picks = [{"key": "good", "genome": good}, {"key": "bad", "genome": bad, "behaviour": "b1"}]
    path = tmp_path / "leaks.jsonl"
    out = frun.leak_screen(ctx, picks, path, "r1", "2026-10-28", log=lambda *_: None)
    assert [x["key"] for x in out] == ["bad"]
    row = json.loads(path.read_text().splitlines()[0])
    assert row["key"] == "bad" and row["reason"].startswith("leak:") and row["first"]["column"] and row["behaviour"] == "b1"
    clean = [json.loads(x) for x in (tmp_path / "leak_passed.jsonl").read_text().splitlines()]   # the positive record
    assert [x["key"] for x in clean] == ["good"] and clean[0]["ok"] is True and clean[0]["reason"].startswith("no leak")
    assert len(path.read_text().splitlines()) == 1                  # the rejections' file holds rejections only


def test_f2_genomes_pass():
    from lab.factory import small
    from test_factory_small import EURUSD, synthetic
    days, crypto, etf = synthetic(T=1200)
    noise = {a: np.array([-20.0, -5.0, 0.0, 5.0, 20.0]) for a in small.UNDERLYING}
    c = small.make_ctx(days, crypto, etf, EURUSD, {"SPY": 0.003, "QQQ": 0.0, "GOLD": 0.01}, noise)
    rng = random.Random(3)
    for g in [small.random_genome(rng) for _ in range(2)] + [small.random_tree_genome(rng) for _ in range(2)]:
        assert checks.genome(c, g, n_cuts=2, small=True)["ok"], small.describe(g)


# ---------------------------------------------------------------- books

def test_a_book_on_tomorrows_return_is_caught(panel):
    def peek(P):
        W = np.zeros((P.T, P.N))
        W[:-1] = np.nan_to_num(P.ret[1:]) > 0
        return W
    res = checks.book("peek", peek, panel, n_cuts=2)
    assert not res["ok"] and res["kind"] == "book" and res["first"]["column"] in panel.names


@pytest.mark.parametrize("name", ["families", "families@alpaca", "smallaccount small50_tsmom1",
                                  "smallaccount small100_breakout_sol3", "exit_shadow live_books",
                                  "tranches_filtered tsmom_tranches_lowmax"])
def test_the_real_books_pass(panel, name):
    res = checks.book(name, checks.book_functions()[name], panel, n_cuts=2)
    assert res["ok"], leak.reason(res)


def test_held_carries_leave_forward():
    W = np.array([[np.nan, 0.5], [0.2, np.nan], [np.nan, 0.0]])
    assert np.array_equal(checks.held(W), [[0.0, 0.5], [0.2, 0.5], [0.2, 0.0]])
    assert set(checks.held({"a": W, "b": np.ones(3, dtype=bool)})) == {"a", "b"}


def test_the_panel_builder_is_checked_on_its_long_frame(panel):
    j = np.arange(panel.N)
    rows = [{"day": int(panel.days[t]), "symbol": panel.names[k], "close": panel.close[t, k], "high": panel.high[t, k],
             "low": panel.low[t, k], "rv": panel.extra["rv"][t, k], "qv": panel.extra["qv"][t, k], "n": 24}
            for t in range(400, panel.T) for k in j if np.isfinite(panel.close[t, k])]
    long = pl.DataFrame(rows)
    perp = pl.DataFrame({"day": panel.days[400:], "base": "BTC", "funding": 1e-4, "perp_qv": 1e6})
    res = checks.panel_builder(long, perp, n_cuts=2)
    assert res["kind"] == "book" and res["runs"] > 0 and res["error"] is None


# ---------------------------------------------------------------- the weekly job and the health lines

def test_the_weekly_report_names_every_red_line(tmp_path, monkeypatch):
    from lab import report
    monkeypatch.setattr(report, "REPORTS", tmp_path / "reports")
    red = {"kind": "book", "name": "peek", "ok": False, "runs": 4, "cuts": ["2026-01-01"], "error": None,
           "leaks": [{"kind": "shift", "cut": "2026-01-01", "first": "2025-12-31", "column": "BTCUSDT"}],
           "first": {"kind": "shift", "cut": "2026-01-01", "first": "2025-12-31", "column": "BTCUSDT"}}
    monkeypatch.setattr(job, "books", lambda: [red])
    monkeypatch.setattr(job, "features", lambda: [{**red, "kind": "feature", "name": "x 1d", "ok": True, "leaks": [],
                                                   "first": None}])
    monkeypatch.setattr(job, "specs", lambda: (_ for _ in ()).throw(OSError("no shadows file")))
    assert job.main(["--only", "features", "--only", "books", "--only", "specs"]) == 0
    d = json.loads((tmp_path / "reports" / "leak" / "latest.json").read_text())
    assert d["checked"] == 3 and d["red"] == 2
    md = (tmp_path / "reports" / "leak" / "latest.md").read_text()
    assert "| book | peek | leak: BTCUSDT at 2025-12-31" in md and "could not check: OSError" in md
    assert "\u2014" not in md


def test_health_has_a_red_line_per_leaking_feature_builder_or_book(tmp_path):
    from lab.ops import jobs
    from test_jobs import table
    t = table(tmp_path, '  - name: a\n    schedule: "0 4 * * *"\n    command: x')
    assert jobs.leak_lines(t) == []                                # no report yet: nothing
    p = tmp_path / "data" / "reports" / "leak" / "latest.json"
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps({"results": [
        {"kind": "feature", "name": "f 1d", "ok": False, "why": "leak: f 1d at 2026-01-01 moves"},
        {"kind": "book", "name": "families", "ok": True, "why": "no leak"},
        {"kind": "spec", "name": "abc", "ok": False, "why": "leak"},
        {"kind": "zoo", "name": "M8", "ok": False, "error": "OSError: x"}]}))
    lines = jobs.leak_lines(t)
    assert lines == [("leak feature f 1d", False, "leak: f 1d at 2026-01-01 moves"), ("leak zoo M8", False, "OSError: x")]
    names = [n for n, _, _ in jobs.health_checks(t)]
    assert "leak feature f 1d" in names and "leak spec abc" not in names


def test_the_job_is_in_the_table():
    from pathlib import Path
    y = (Path(__file__).resolve().parents[2] / "ops" / "jobs.yaml").read_text()
    i = y.index("- name: leak-check")
    block = y[i:y.index("\n\n", i)]
    assert "python -m lab.leak" in block and "lock: heavy" in block and 'schedule: "0 6 * * 0"' in block
