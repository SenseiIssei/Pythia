"""The rebalance band replay (lab.experiments.rebalance_band) on a synthetic two-coin book.

Run from research/lab:  python -m pytest tests/test_rebalance_band.py
"""

from __future__ import annotations

import numpy as np
import pytest

from lab.experiments import rebalance_band as rb


def book():
    T = 6
    ret = np.zeros((T, 2))
    W = np.full((T, 2), np.nan)
    W[1] = [0.30, 0.0]          # entry into A
    W[2] = [0.306, 0.0]         # a 0.6 % resize of A
    W[3] = [0.306, 0.004]       # a small entry into B (0.4 %)
    W[4] = [0.0, 0.004]         # exit A
    traded = np.ones((T, 2), dtype=bool)
    alive = np.ones((T, 2), dtype=bool)
    return ret, W, traded, alive


def test_the_baseline_trades_every_difference_past_its_band_entries_and_exits_alike():
    ret, W, traded, alive = book()
    g, tov, ex = rb.replay(ret, W, traded, alive, 1, None)
    assert tov[1] == pytest.approx(0.30)
    assert tov[2] == pytest.approx(0.006), "0.6 % is past the 0.2 % band"
    assert tov[3] == pytest.approx(0.004)
    assert tov[4] == pytest.approx(0.306)


def test_a_resize_band_skips_small_resizes_and_never_an_entry_or_an_exit():
    ret, W, traded, alive = book()
    g, tov, ex = rb.replay(ret, W, traded, alive, 1, 0.01)
    assert tov[1] == pytest.approx(0.30), "an entry always trades"
    assert tov[2] == 0.0, "a 0.6 % resize stays inside a 1 % band"
    assert tov[3] == pytest.approx(0.004), "a small entry still trades, above the $10 minimum"
    assert tov[4] == pytest.approx(0.30), "the exit sells what is held"
    assert ex[4] == pytest.approx(0.004)


def test_costs_are_charged_the_day_after_and_the_rule_reads_in_and_out_of_sample():
    x = rb.net(np.array([0.0, 0.01, 0.0]), np.array([1.0, 0.0, 0.0]), 0.0035)
    assert x.tolist() == pytest.approx([0.0, 0.01 - 0.0035, 0.0])
    rows = []
    for book_ in ("a", "b"):
        for w in ("is", "oos"):
            rows.append({"book": book_, "b": None, "window": w, "cost_yr": 0.02, "sharpe": 1.0, "te": 0.0})
            rows.append({"book": book_, "b": 0.01, "window": w, "cost_yr": 0.014, "sharpe": 0.99, "te": 0.005})
            rows.append({"book": book_, "b": 0.02, "window": w, "cost_yr": 0.010, "sharpe": 0.95, "te": 0.02})
            rows.append({"book": book_, "b": 0.005, "window": w, "cost_yr": 0.018, "sharpe": 1.0, "te": 0.001})
    v = rb.judge(rows)
    assert v["pick"] == 0.01 and v["confirmed"], v
    assert v["in_sample_failures"]["2 %"], "2 % moves the Sharpe and tracks too loosely"
