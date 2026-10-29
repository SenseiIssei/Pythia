"""R6: the validation window, the lockbox and its log, one trial per behaviour, the deflated excess bar, effective N
and PBO (results/factory_lockbox_r6.md). Synthetic data only, no network.

Run from research/lab:  python -m pytest tests/test_factory_lockbox.py
"""

from __future__ import annotations

import math
import random

import numpy as np
import pytest

from lab import history, metrics, report
from lab.experiments import fam_common as fc
from lab.factory import build, evaluate, grammar, ledger, run, shadow, small

from test_factory import synthetic_panel
from test_factory_small import EURUSD, make_venue
from test_factory_small import synthetic as small_synthetic


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTHIA_FACTORY_DIR", str(tmp_path / "factory"))
    monkeypatch.setenv("PYTHIA_FACTORY_SEED", str(tmp_path / "no_seed"))
    monkeypatch.setenv("PYTHIA_FACTORY_SMALL_SEED", str(tmp_path / "no_small_seed"))
    monkeypatch.delenv("PYTHIA_FACTORY_SMALL_DIR", raising=False)
    monkeypatch.setattr(report, "REPORTS", tmp_path / "reports")
    monkeypatch.delenv("PYTHIA_RESULTS", raising=False)
    return tmp_path


@pytest.fixture(scope="module")
def long_ctx():
    """2020-01-01 to 2026-11-04: in sample, validation and 127 lockbox days."""
    return build.make_ctx(synthetic_panel(T=2500))


def _sr_daily(annual: float) -> float:
    return annual / math.sqrt(365)


def _fill_family(n: int, seed: int = 0, is_days: int = 2190) -> None:
    """n noise genomes in the factory ledger, their in-sample excess Sharpes those of pure noise over is_days."""
    rng = np.random.default_rng(seed)
    x = rng.normal(0, 0.02, (is_days, n))
    ex = x.mean(0) / x.std(0) * math.sqrt(365)
    raw = ex + rng.normal(1.0, 1.0, n)                 # the raw Sharpes carry beta: wider and shifted
    ledger.Ledger().add([{"key": f"n{i}", "behaviour": f"b{i}", "is_sharpe": float(raw[i]),
                          "is_excess_sharpe": float(ex[i]), "fitness": 0.0} for i in range(n)])


# ---------------------------------------------------------------- windows

def test_validation_ends_before_the_lockbox(long_ctx):
    w = evaluate.windows(long_ctx)
    lb0 = int(np.flatnonzero(w["lockbox"])[0])
    assert long_ctx.days[lb0] == evaluate.LOCKBOX_START and not (w["oos"] & w["lockbox"]).any()
    assert long_ctx.days[w["oos"]][-1] < evaluate.LOCKBOX_START <= long_ctx.days[w["lockbox"]][0]
    assert not (w["is"] & w["oos"]).any()


def test_nothing_but_the_lockbox_look_reads_the_lockbox(long_ctx):
    """Prices after 2026-07-01 moved: the in-sample row and every held-back number stay the same."""
    lb0 = int(np.flatnonzero(evaluate.windows(long_ctx)["lockbox"])[0])
    other = build.make_ctx(synthetic_panel(T=2500, bump=(lb0 + 1, 0.2)))
    g = grammar.random_genome(random.Random(4))
    pool = {"n_trials": 100, "var": 1e-4, "sr0_annual": 1.0, "excess_var": 1e-4, "excess_sr0_annual": 1.0}
    a, b = evaluate.in_sample(long_ctx, g, "x"), evaluate.in_sample(other, g, "x")
    assert a["is_sharpe"] == b["is_sharpe"] and a["behaviour"] == b["behaviour"]
    ha = evaluate.holdout(long_ctx, g, pool, evaluate.btc_benchmark(long_ctx))
    hb = evaluate.holdout(other, g, pool, evaluate.btc_benchmark(other))
    for k in ("oos_sharpe_35bps", "oos_excess_sharpe", "deflated_p", "oos_late_sharpe", "oos_to"):
        assert ha[k] == hb[k]
    assert ha["oos_to"] == "2026-06-30"


def test_small_validation_ends_before_the_lockbox():
    days, crypto, etf = small_synthetic()
    c = small.make_ctx(days, crypto, etf, EURUSD, {"SPY": 0.0, "QQQ": 0.0, "GOLD": 0.0},
                       {a: np.zeros(5) for a in small.UNDERLYING})
    w = small.windows(c)
    assert small._day(c, w["oos"][1]) == "2026-06-30" and small._day(c, w["lockbox"][0]) == "2026-07-01"


# ---------------------------------------------------------------- one trial per behaviour

def test_equal_returns_are_one_behaviour():
    x = np.array([0.01, -0.0, np.nan, 0.02])
    assert grammar.behaviour(x) == grammar.behaviour(np.array([0.01, 0.0, 0.0, 0.02 + 1e-13]))
    assert grammar.behaviour(x) != grammar.behaviour(np.array([0.01, 0.0, 0.0, 0.021]))
    assert len(grammar.behaviour(x)) == 16


def test_equivalent_trees_are_one_trial(home, long_ctx):
    """btc > ma_100 and z_100(btc) > 0 under different keys: the same returns, one trial, one holdout pick."""
    g = grammar.random_genome(random.Random(5))
    r1 = evaluate.in_sample(long_ctx, g, "x")
    r2 = {**r1, "key": "otherkey0000"}              # another key, the same book
    L = ledger.Ledger()
    base = L.n_trials()
    L.add([run.strip(r1), run.strip(r2)])
    assert L.by_key["otherkey0000"]["same_as"] == r1["key"]
    assert L.trials() == 1 and L.n_trials() == base + 1
    assert ledger.Ledger().by_key["otherkey0000"]["same_as"] == r1["key"]     # read back from the file
    ids = {t["id"] for t in metrics.read_registry()}
    assert f"factory:{r1['key']}" in ids and "factory:otherkey0000" not in ids
    assert ledger.Ledger().pool()["same_behaviour"] == 1
    checked = {r1["behaviour"]}                       # held back once under the first key
    assert run.pick_for_holdout(long_ctx, ledger.Ledger(), checked) == []


# ---------------------------------------------------------------- the deflated excess bar

def test_excess_variance_comes_from_the_registry(home):
    p0 = ledger.Ledger().pool()
    assert p0["excess_from"] == "raw" and p0["excess_var"] == p0["var"]
    _fill_family(200)
    p = ledger.Ledger().pool()
    ex = [r["excess_sharpe"] for r in metrics.read_registry() if r["family"] == "factory"]
    assert p["excess_from"] == "excess" and p["excess_trials"] == 200 == len(ex)
    assert p["excess_var"] == pytest.approx(np.var(np.clip(ex, -3, 3) / math.sqrt(365)))
    assert p["n_trials"] == metrics.trial_pool()["n_trials"]          # N stays the registry's, one count
    assert p["excess_sr0_annual"] < p["sr0_annual"]                    # beta no longer sets the bar


def test_a_noise_ledger_passes_at_most_5_percent_and_a_planted_edge_mostly(home):
    """The judged-by test: 200 runs, each picks the 6 best of 300 noise genomes in sample and checks them on 912
    validation days; a run passes when any of them clears the bar. A planted edge of excess Sharpe 3 a year (in
    sample and held back) passes in most runs."""
    _fill_family(300)
    pool = ledger.Ledger().pool()
    rng = np.random.default_rng(1)
    noise_pass = planted_pass = 0
    runs, M, T_is, T_oos = 200, 300, 2190, 912
    for _ in range(runs):
        ins = rng.normal(0, 0.02, (T_is, M))
        best = np.argsort(ins.mean(0) / ins.std(0))[-6:]
        oos = rng.normal(0, 0.02, (T_oos, M))[:, best]
        noise_pass += any(ledger.deflated_excess(oos[:, j], pool) > evaluate.DEFLATED_BAR for j in range(6))
        edge = rng.normal(_sr_daily(3.0) * 0.02, 0.02, T_oos)
        planted_pass += ledger.deflated_excess(edge, pool) > evaluate.DEFLATED_BAR
    assert noise_pass / runs <= 0.05
    assert planted_pass / runs > 0.8


def test_holdout_deflates_the_excess_over_btc(home, long_ctx):
    _fill_family(100)
    pool = ledger.Ledger().pool()
    g = grammar.random_genome(random.Random(6))
    h = evaluate.holdout(long_ctx, g, pool, evaluate.btc_benchmark(long_ctx))
    gross, tov, _ = build.run(long_ctx, g)
    w = evaluate.windows(long_ctx)
    x = build.net(gross, tov, build.COSTS["35bps"])[w["oos"]]
    ex = x - np.nan_to_num(long_ctx.P.ret[:, long_ctx.P.btc])[w["oos"]]
    assert h["deflated_p"] == pytest.approx(metrics.dsr(ex, {"n_trials": pool["n_trials"], "var": pool["excess_var"]}))
    assert h["dsr_raw"] == pytest.approx(ledger.deflated(x, pool)) and h["pool_sr0"] == pool["excess_sr0_annual"]
    assert "excess over BTC" in evaluate.bar_gates(evaluate.in_sample(long_ctx, g, "x"), h)["deflated"]["why"]
    # the audit (2026-10-29): the row carries the family's DSR and the excess series the ladder recomputes from
    assert h["family_trials"] == pool["family_trials"] > 0
    assert h["dsr_family"] == pytest.approx(metrics.dsr(ex, {"n_trials": pool["family_trials"], "var": pool["excess_var"]}))
    assert len(h["oos_excess_returns"]) == len(ex) and h["oos_excess_returns"][-1] == pytest.approx(ex[-1], abs=1e-7)


# ---------------------------------------------------------------- effective N and PBO

def test_effective_n_counts_clusters():
    rng = np.random.default_rng(2)
    base = rng.normal(0, 0.02, (1000, 3))
    xs = [base[:, i % 3] + rng.normal(0, 0.002, 1000) for i in range(30)]
    assert evaluate.effective_n(xs)["effective_n"] == 3
    assert evaluate.effective_n(xs + [np.zeros(1000), np.zeros(1000)]) == {"genomes": 32, "effective_n": 4,
                                                                            "corr": evaluate.EFF_CORR}
    assert evaluate.effective_n([rng.normal(0, 1, 500) for _ in range(20)])["effective_n"] == 20


def test_pbo_is_high_for_noise_and_low_for_a_real_edge():
    rng = np.random.default_rng(3)
    noise = [rng.normal(0, 0.02, 1600) for _ in range(40)]
    p = evaluate.pbo(noise)
    assert 0.3 < p["pbo"] < 0.8 and p["combos"] == math.comb(16, 8) and p["genomes"] == 40
    edge = [rng.normal(_sr_daily(4.0) * 0.02, 0.02, 1600)] + [rng.normal(_sr_daily(1.0) * 0.02, 0.02, 1600)
                                                             for _ in range(39)]
    assert evaluate.pbo(edge)["pbo"] < 0.1
    assert evaluate.pbo([np.zeros(500), rng.normal(0, 1, 500)]) is None


# ---------------------------------------------------------------- the lockbox and its log

def _held(c, g, pool, dsr=0.99):
    h = evaluate.holdout(c, g, pool, evaluate.btc_benchmark(c))
    h.update(deflated_p=dsr, genome=g, gates={k: {"passed": True, "why": "ok"} for k in evaluate.SHADOW_GATES})
    return h


def test_the_weekly_run_looks_once_per_behaviour_and_logs_every_look(home, long_ctx, monkeypatch):
    pool = ledger.Ledger().pool()
    btc = evaluate.btc_benchmark(long_ctx)
    g1, g2 = grammar.random_genome(random.Random(7)), grammar.random_genome(random.Random(8))
    held = [_held(long_ctx, g1, pool), {**_held(long_ctx, g1, pool), "key": "clone0000000"},
            _held(long_ctx, g2, pool, dsr=0.5)]   # the clone has g1's behaviour; g2 fails the excess bar
    monkeypatch.setattr(small, "load_market", lambda *a: pytest.fail("no F2 candidate, no market load"))
    out = run.lockbox_step(long_ctx, pool, btc, held, "r1", "2026-11-04", log=lambda *_: None)
    assert [x["key"] for x in out["this_run"]] == [held[0]["key"]] and out["all"] == 1 and out["error"] is None
    x = ledger.lockbox_looks()[0]
    assert x["look"] == 1 and x["looks"] == 1 and x["factory"] == "factory" and x["lockbox_from"] == "2026-07-01"
    assert x["lockbox_days"] == 127 and x["validation_dsr"] == 0.99
    again = run.lockbox_step(long_ctx, pool, btc, held, "r2", "2026-11-11", log=lambda *_: None)
    assert again["this_run"] == [] and len(ledger.lockbox_looks()) == 1
    gate = evaluate.lockbox_gate(held[1]["key"], held[1]["behaviour"])      # the clone shares the look
    assert gate["passed"] == (x["dsr"] >= evaluate.LOCKBOX_BAR) and "lockbox look 1" in gate["why"]
    assert evaluate.lockbox_gate(held[2]["key"], held[2]["behaviour"]) == {
        "passed": False, "why": "never looked at in the lockbox"}


def test_no_look_while_the_lockbox_is_short(home):
    c = build.make_ctx(synthetic_panel(T=2390))            # 17 lockbox days
    pool = ledger.Ledger().pool()
    out = run.lockbox_step(c, pool, evaluate.btc_benchmark(c), [_held(c, grammar.random_genome(random.Random(7)),
                                                                       pool)], "r", "d", log=lambda *_: None)
    assert out["this_run"] == [] and ledger.lockbox_looks() == []


def test_lockbox_dsr_deflates_over_every_look(home, long_ctx):
    g = grammar.random_genome(random.Random(9))
    pool = ledger.Ledger().pool()
    first = evaluate.lockbox(long_ctx, g, pool)
    for i in range(50):
        ledger.log_look({"factory": "small", "key": f"k{i}"})
    later = evaluate.lockbox(long_ctx, g, pool)
    assert later["looks"] == 51 and first["looks"] == 1
    assert later["dsr"] <= first["dsr"] and later["lockbox_excess_sharpe"] == first["lockbox_excess_sharpe"]


def test_f2_survivors_are_looked_at_by_the_weekly_run_only(home, monkeypatch):
    days, crypto, etf = small_synthetic()
    c = small.make_ctx(days, crypto, etf, EURUSD, {"SPY": 0.003, "QQQ": 0.0, "GOLD": 0.01},
                       {a: np.array([-20.0, -5.0, 0.0, 5.0, 20.0]) for a in small.UNDERLYING})
    v = make_venue()
    monkeypatch.setattr(small, "gates", lambda r, h: {"all": {"passed": True, "why": "forced"}})
    monkeypatch.setattr(small.lg, "deflated_excess", lambda x, pool, n=None: 0.99)
    d = small.run(c, v, 8, "2026-12-20", log=lambda *_: None)
    assert ledger.lockbox_looks() == []                    # the daily mode never looks
    queued = [h for h in d["holdout"] if h.get("excess_passed")]
    assert queued and "weekly lockbox look" in queued[0]["why"]
    looks = small.lockbox_step("w1", log=lambda *_: None, market=(c, v))
    assert len(looks) == len({h["behaviour"] for h in queued}) and looks[0]["factory"] == "small"
    assert [x["look"] for x in looks] == list(range(1, len(looks) + 1))
    assert small.lockbox_step("w2", log=lambda *_: None, market=(c, v)) == []
    md = small.markdown(small.run(c, v, 8, "2026-12-21", log=lambda *_: None))
    assert "## Lockbox looks" in md and "effective N" in md and "PBO" in md


def test_the_weekly_report_states_pbo_and_effective_n(home, monkeypatch):
    P = synthetic_panel()
    monkeypatch.setattr(history, "load_long_panel", lambda fetch=False, fresh=False: P)
    d = run.weekly(30, False, "2026-10-31", log=lambda *_: None)
    run.publish(d)
    md = (report.REPORTS / "factory" / "latest.md").read_text(encoding="utf-8")
    assert "effective N:" in md and "PBO" in md and "## The bar after R6" in md and "\u2014" not in md
    assert d["night"]["effective_n"]["effective_n"] <= d["night"]["effective_n"]["genomes"]
    assert d["lockbox"] == {"this_run": [], "all": 0, "error": None}         # the panel ends in 2024
    assert all("is_returns" not in r for r in ledger.Ledger().rows)
    assert all(r.get("behaviour") for r in ledger.Ledger().rows)
