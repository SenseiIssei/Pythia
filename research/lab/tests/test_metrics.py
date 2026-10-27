"""metrics.deflated_sharpe and the trial registry (R5)."""

from __future__ import annotations

import json
import math

import numpy as np
import pytest
from scipy import stats

from lab import metrics


def test_deflated_sharpe_matches_the_papers_example():
    # Bailey and Lopez de Prado (2014): 100 trials, variance of annual trial Sharpes 0.5, 1,250 days,
    # skew -3, kurtosis 10, an annual Sharpe of 2.5 (250 days a year): SR0 0.1132 a day, DSR 0.9004.
    var = 0.5 / 250
    assert metrics.expected_max_sharpe(var, 100) == pytest.approx(0.1132, abs=1e-4)
    d = metrics.deflated_sharpe(2.5 / math.sqrt(250), 1250, 100, var, -3.0, 10.0)
    assert d == pytest.approx(0.9004, abs=1e-3)


def test_one_trial_is_the_probabilistic_sharpe():
    assert metrics.deflated_sharpe(0.0, 500, 1, 0.01) == pytest.approx(0.5)
    sr = 0.05
    assert metrics.deflated_sharpe(sr, 401, 1, 0.01) == pytest.approx(stats.norm.cdf(sr * 20 / math.sqrt(1 + sr ** 2 / 2)))


def test_deflated_sharpe_moves_the_right_way():
    base = metrics.deflated_sharpe(0.08, 1000, 50, 0.0005)
    assert metrics.deflated_sharpe(0.08, 1000, 500, 0.0005) < base          # more trials, a higher bar
    assert metrics.deflated_sharpe(0.08, 1000, 50, 0.001) < base           # more spread, a higher bar
    assert metrics.deflated_sharpe(0.10, 1000, 50, 0.0005) > base           # a better Sharpe
    assert metrics.deflated_sharpe(0.08, 3000, 50, 0.0005) > base           # a longer record
    assert metrics.deflated_sharpe(0.08, 1000, 50, 0.0005, -2.0, 3.0) < base   # left skew
    assert metrics.deflated_sharpe(0.08, 1000, 50, 0.0005, 0.0, 12.0) < base   # fat tails
    assert 0.0 <= base <= 1.0


def test_published_bar_and_the_seed():
    assert metrics.expected_max_sharpe(metrics.prior_var(), 377) * math.sqrt(365) == pytest.approx(2.43, abs=1e-9)
    hand = sum(b["n"] for b in metrics.TRIAL_SEED if b["family"] == "hand")
    small = sum(b["n"] for b in metrics.TRIAL_SEED if b["family"] == "small")
    assert hand == 1377 and small == 61 + 8 + 1
    assert len({b["id"] for b in metrics.TRIAL_SEED}) == len(metrics.TRIAL_SEED)
    assert "\u2014" not in json.dumps(metrics.TRIAL_SEED)


def test_registry_reads_its_n_and_variance_by_family_and_in_all():
    p = metrics.trial_pool()
    assert not metrics.registry_path().exists()           # reading never writes
    assert p["family"] == "all" and p["n_trials"] == 1377 + 70
    assert p["var"] == pytest.approx(metrics.prior_var())  # only the hand blocks carry a variance yet
    assert metrics.trial_pool("hand")["n_trials"] == 1377 and metrics.trial_pool("small")["n_trials"] == 70
    assert metrics.trial_pool("nothing")["n_trials"] == 0
    rng = np.random.default_rng(1)
    sh = rng.normal(0.5, 1.0, 300)
    added = metrics.register([{"id": f"small:g{i}", "family": "small", "source": "test", "sharpe": float(x)}
                              for i, x in enumerate(sh)])
    assert len(added) == 300
    small = metrics.trial_pool("small")
    v = float(np.var(np.clip(sh, -3, 3) / math.sqrt(365)))
    assert small["n_trials"] == 370 and small["var"] == pytest.approx(v)
    allp = metrics.trial_pool()
    assert allp["n_trials"] == 1377 + 370
    assert allp["var"] == pytest.approx((1377 * metrics.prior_var() + 300 * v) / 1677)
    assert allp["sr0_annual"] == pytest.approx(metrics.expected_max_sharpe(allp["var"], 1747) * math.sqrt(365))
    # deflated_sharpe without a count reads the registry
    s = 0.1
    assert metrics.deflated_sharpe(s, 900) == pytest.approx(metrics.deflated_sharpe(s, 900, 1747, allp["var"]))
    assert metrics.deflated_sharpe(s, 900, family="small") == pytest.approx(
        metrics.deflated_sharpe(s, 900, 370, small["var"]))


def test_registry_is_append_only_and_counts_an_id_once():
    p = metrics.registry_path()
    first = metrics.register([{"id": "factory:a", "family": "factory", "sharpe": 1.0}])
    assert [r["id"] for r in first] == ["factory:a"]
    lines = p.read_text().splitlines()
    assert len(lines) == len(metrics.TRIAL_SEED) + 1       # the seed is written with the first line
    assert metrics.register([{"id": "factory:a", "family": "factory", "sharpe": 9.0}]) == []
    assert p.read_text().splitlines() == lines              # nothing rewritten
    with p.open("a") as fh:
        fh.write('{"id": "torn"')
    assert metrics.trial_pool("factory")["n_trials"] == 1
    extra = [{"id": "factory:a", "family": "factory"}, {"id": "factory:b", "family": "factory"}]
    assert metrics.trial_pool("factory", extra=extra)["n_trials"] == 2   # extra counted once with the file's


def test_dsr_of_a_series():
    rng = np.random.default_rng(2)
    pool = {"n_trials": 100, "var": 0.5 / 365}
    good, flat = rng.normal(0.004, 0.01, 1500), np.zeros(100)
    assert metrics.dsr(good, pool) > 0.95 > metrics.dsr(rng.normal(0, 0.01, 1500), pool)
    assert metrics.dsr(flat, pool) == 0.0
    assert 0.0 <= metrics.dsr(good) <= 1.0                 # the registry's pool of all by default
