"""The zoo's calibrated drift rule on synthetic panels: a slow input that today's rule
always calls shifted, a fast one, and a real shift.

No network, no lab data. Run from research/lab:  python -m pytest tests
"""

from __future__ import annotations

import numpy as np
import polars as pl

from lab.models import core

DAY = core.DAY_US


def panel(n_days: int = 1500, n_coins: int = 10, seed: int = 0) -> pl.DataFrame:
    rng = np.random.default_rng(seed)
    days = np.arange(n_days, dtype=np.int64) * DAY
    # slow: a market-wide AR(1) near a unit root (one value a day, the same for every coin)
    slow = np.zeros(n_days)
    for t in range(1, n_days):
        slow[t] = 0.995 * slow[t - 1] + 0.1 * rng.standard_normal()
    rows = {"ts_us": np.repeat(days, n_coins), "symbol": np.tile([f"C{i}" for i in range(n_coins)], n_days),
            "slow": np.repeat(slow, n_coins), "fast": rng.standard_normal(n_days * n_coins)}
    return pl.DataFrame(rows)


def bins_of(p: pl.DataFrame) -> dict:
    return {f: core.drift_bins(p[f].to_numpy()) for f in ("slow", "fast")}


def test_todays_rule_calls_a_persistent_input_shifted_almost_always():
    p = panel()
    w = core.drift_windows(bins_of(p), p, 30)
    share = np.mean([x["checks"]["slow"]["level"] != "stable" for x in w])
    assert share > 0.5, share
    assert np.mean([x["checks"]["fast"]["level"] != "stable" for x in w]) < 0.05


def test_calibration_bounds_false_alarms_in_sample_and_still_sees_a_real_shift():
    p = panel()
    b = bins_of(p)
    w = core.drift_windows(b, p, 30)
    cal = core.drift_calibration(b, w, 30)
    assert cal is not None and cal["k"] >= 1
    assert cal["false_alarm_train"] <= core.CAL_FALSE_ALARM
    assert cal["cuts"]["slow"]["psi"] > 0.25 and cal["cuts"]["fast"]["psi"] == 0.25
    over = [core.calibrated_level(x["checks"], cal)[1] for x in w]
    assert np.mean([n >= cal["k"] for n in over]) <= core.CAL_FALSE_ALARM
    # "drift" (over 5 % outside the trained range) is left as it is: a persistent input
    # can still trip it, which is what the study measures.
    # The fast input moved by three standard deviations for a whole window is flagged.
    last = p.filter(pl.col("ts_us") >= p["ts_us"].max() - 29 * DAY).with_columns(fast=pl.col("fast") + 3.0)
    checks = {f: core.drift_check(b[f], last[f].to_numpy()) for f in b}
    assert core.calibrated_level(checks, cal)[0] != "stable"


def test_too_few_windows_give_no_calibration():
    p = panel(n_days=120)
    b = bins_of(p)
    assert core.drift_calibration(b, core.drift_windows(b, p, 30), 30) is None
