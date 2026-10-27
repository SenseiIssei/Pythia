"""lab.cv (walk-forward with an embargo) and lab.labels (triple barrier)."""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pytest

from lab import cv, labels


def us(y, m, d=1, h=0):
    return int(datetime(y, m, d, h, tzinfo=timezone.utc).timestamp() * 1e6)


def test_quarter_starts():
    q = cv.quarter_starts(us(2023, 2, 10), us(2024, 1, 1))
    assert q == [us(2023, 1, 1), us(2023, 4, 1), us(2023, 7, 1), us(2023, 10, 1), us(2024, 1, 1)]
    assert cv.quarter_starts(us(2023, 12, 31), us(2023, 12, 31, 23)) == [us(2023, 10, 1)]


def test_walk_forward_never_trains_on_the_embargo_or_later():
    ts = np.arange(us(2022, 1, 1), us(2024, 3, 1), cv.HOUR_US, dtype=np.int64)
    folds = cv.walk_forward(ts, us(2023, 1, 1), embargo_h=48)
    assert [f.name for f in folds] == ["2023Q1", "2023Q2", "2023Q3", "2023Q4", "2024Q1"]
    covered = np.zeros(len(ts), dtype=bool)
    for f in folds:
        start = ts[f.test].min()
        assert ts[f.train].max() < start - 48 * cv.HOUR_US       # the embargo before the test period
        assert ts[f.train].max() == start - 48 * cv.HOUR_US - cv.HOUR_US
        assert not (f.train & f.test).any() and not (covered & f.test).any()
        covered |= f.test
    assert (covered == (ts >= us(2023, 1, 1))).all()            # every test bar once, nothing before the start
    assert ts[folds[-1].test].max() == ts.max()


def test_walk_forward_skips_an_empty_quarter():
    ts = np.concatenate([np.arange(us(2023, 1, 1), us(2023, 2, 1), cv.HOUR_US),
                         np.arange(us(2023, 7, 1), us(2023, 8, 1), cv.HOUR_US)]).astype(np.int64)
    assert [f.name for f in cv.walk_forward(ts, us(2023, 1, 1))] == ["2023Q1", "2023Q3"]


def bars(close, high=None, low=None):
    close = np.asarray(close, dtype=float)
    return close, (close if high is None else np.asarray(high, float)), (close if low is None else np.asarray(low, float))


def test_triple_barrier_upper_lower_and_time():
    sig = np.full(6, 0.01)
    w = 0.01 * np.sqrt(4)                                    # sigma * sqrt(horizon)
    up = 100 * np.exp(w)
    c, h, lo = bars([100, 100, 100, 100, 100, 100], high=[100, 100, up + 0.01, 100, 100, 100])
    i, r, hit = labels.triple_barrier(c, h, lo, np.array([0]), sig, 1.0, 1.0, 4, 0.001)
    assert (i[0], hit[0]) == (2, 1) and r[0] == pytest.approx(w - 0.001)
    dn = 100 * np.exp(-w)
    c, h, lo = bars([100] * 6, low=[100, dn - 0.01, 100, 100, 100, 100])
    i, r, hit = labels.triple_barrier(c, h, lo, np.array([0]), sig, 1.0, 1.0, 4, 0.0)
    assert (i[0], hit[0]) == (1, -1) and r[0] == pytest.approx(-w)
    c, h, lo = bars([100, 100.5, 101, 100.2, 100.4, 103])
    i, r, hit = labels.triple_barrier(c, h, lo, np.array([0, 3]), sig, 5.0, 5.0, 4, 0.0)
    assert i.tolist() == [4, 5] and hit.tolist() == [0, 0]   # the time limit, clipped at the last bar
    assert r[0] == pytest.approx(np.log(100.4 / 100)) and r[1] == pytest.approx(np.log(103 / 100.2))


def test_both_barriers_in_one_bar_take_the_loss():
    sig = np.full(4, 0.01)
    c, h, lo = bars([100, 100, 100, 100], high=[100, 200, 100, 100], low=[100, 50, 100, 100])
    _, r, hit = labels.triple_barrier(c, h, lo, np.array([0]), sig, 1.0, 1.0, 3, 0.0)
    assert hit[0] == -1 and r[0] < 0


def test_labels_never_look_past_the_horizon():
    sig = np.full(10, 0.01)
    c, h, lo = bars(np.full(10, 100.0))
    h2 = h.copy()
    h2[6] = 1000.0                                           # a spike after the horizon of the entry at 0
    a = labels.triple_barrier(c, h, lo, np.array([0]), sig, 1.0, 1.0, 5, 0.0)
    b = labels.triple_barrier(c, h2, lo, np.array([0]), sig, 1.0, 1.0, 5, 0.0)
    assert all(np.array_equal(x, y) for x, y in zip(a, b))


def test_non_overlapping_skips_signals_while_a_position_is_open():
    sig = np.array([1, 1, 0, 1, 1, 0, 0, 1], dtype=bool)
    assert labels.non_overlapping(sig, lambda i: i + 2) == [0, 3, 7]
    assert labels.non_overlapping(sig, lambda i: i) == [0, 1, 3, 4, 7]
