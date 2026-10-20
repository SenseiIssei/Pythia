"""The X15 candlestick study's machinery on synthetic bars. No lab data.

Run from research/lab:  python -m pytest tests/test_candles_study.py
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from lab.experiments import candles_data as cd
from lab.experiments import candles_study as cs


def barset(o, c, elig=None, cost=0.01, last=None) -> cd.BarSet:
    o = np.asarray(o, float)
    c = np.asarray(c, float)
    if o.ndim == 1:
        o, c = o[:, None], c[:, None]
    T, N = o.shape
    h = np.maximum(o, c) * 1.01
    l = np.minimum(o, c) * 0.99
    fin = np.isfinite(c)
    lst = np.array([np.flatnonzero(fin[:, j])[-1] for j in range(N)]) if last is None else np.asarray(last)
    idx = np.maximum.accumulate(np.where(fin, np.arange(T)[:, None], 0), axis=0)
    px = np.where(np.arange(T)[:, None] <= lst[None, :], c[idx, np.arange(N)[None, :]], np.nan)
    el = np.ones((T, N), dtype=bool) if elig is None else np.asarray(elig)
    ins = np.zeros(T, dtype=bool)
    ins[: T // 2] = True
    return cd.BarSet("CD", np.arange(T, dtype=np.int64) * cd.DAY_US + cd.CRYPTO_SPLIT, [f"X{j}" for j in range(N)],
                     o, h, l, c, np.ones((T, N)), el, np.ones((T, N)), np.full(N, cost), 0.0, ins, ~ins,
                     np.arange(T), np.arange(T, dtype=np.int64) * cd.DAY_US + cd.CRYPTO_SPLIT, 365.0,
                     extra={"px": px, "last": lst})


def test_forward_returns_enter_next_open_and_exit_h_bars_later():
    o = np.array([10, 11, 12, 13, 14, 15], float)
    c = np.array([10.5, 11.5, 12.5, 13.5, 14.5, 15.5], float)
    B = barset(o, c)
    r1, r3 = cs.forward(B, 1)[:, 0], cs.forward(B, 3)[:, 0]
    assert r1[0] == pytest.approx(11.5 / 11 - 1)
    assert r3[0] == pytest.approx(13.5 / 11 - 1)
    assert np.isnan(r3[3]) and np.isnan(r1[5])              # the exit is beyond the data


def test_forward_exits_a_dead_series_at_its_last_close():
    o = np.array([[10, 10], [11, 11], [12, 12], [np.nan, 13], [np.nan, 14]], float)
    c = np.array([[10, 10], [11, 11], [12, 12], [np.nan, 13], [np.nan, 14]], float)
    B = barset(o, c)
    r = cs.forward(B, 3)
    assert r[0, 0] == pytest.approx(12 / 11 - 1)             # dead after bar 2: out at its last close
    assert np.isnan(r[2, 0])                                 # no open after the end: no event


def test_holm():
    assert cs.holm([0.001, 0.03, 0.04]) == [True, False, False]
    assert cs.holm([0.001, 0.02, 0.04]) == [True, True, True]
    assert cs.holm([0.01, 0.02, 0.012]) == [True, True, True]
    assert cs.holm([0.5]) == [False]


def test_book_accounting_and_late_fill():
    T = 8
    o = np.array([10, 10, 10, 10, 11, 12, 12, 12], float)
    c = np.array([10, 10, 10, 11, 12, 12, 12, 12], float)
    B = barset(o, c, cost=0.01)
    E = np.zeros((T, 1), dtype=bool)
    E[2, 0] = True
    daily, n_in = cs.book(B, E, 2, 1)
    eq = np.cumprod(1 + daily)
    expect = (1 / 1.01) * (12 / 10) * (1 - 0.01)              # in at the open of 3, out at the close of 4
    assert eq[-1] == pytest.approx(expect)
    assert n_in[2] == 1 and n_in.sum() == 1
    late, _ = cs.book(B, E, 2, 1, lag=1)
    expect_late = (1 / 1.01) * (12 / 11) * (1 - 0.01)         # in at the open of 4, out at the close of 5
    assert np.cumprod(1 + late)[-1] == pytest.approx(expect_late)
    dbl, _ = cs.book(B, E, 2, 1, cost_mult=2.0)
    assert np.cumprod(1 + dbl)[-1] == pytest.approx((1 / 1.02) * 1.2 * 0.98)


def test_book_slots_take_the_most_liquid_and_skip_held():
    T, N = 10, 3
    o = np.full((T, N), 10.0)
    c = np.full((T, N), 10.0)
    B = barset(o, c, cost=0.0)
    B.prio[:] = np.array([1.0, 3.0, 2.0])
    E = np.zeros((T, N), dtype=bool)
    E[1] = True
    E[2, 1] = True                                           # already held: not bought again
    _, n_in = cs.book(B, E, 5, 2)
    assert n_in[1] == 2 and n_in[2] == 0


def test_random_books_use_the_same_entry_counts():
    T, N = 30, 4
    rng = np.random.default_rng(0)
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, (T, N)), 0))
    B = barset(c, c, cost=0.0)
    E = np.zeros((T, N), dtype=bool)
    E[3, 0] = E[10, 2] = True
    _, n_in = cs.book(B, E, 3, 2)
    _, n_r = cs.book(B, E, 3, 2, rng=np.random.default_rng(1), entries=n_in)
    np.testing.assert_array_equal(n_in, n_r)


def test_cell_signs_and_counts():
    T = 6
    a = {"S": np.array([0.01, 0, 0.02, 0, 0, 0]), "N": np.array([1, 0, 2, 0, 0, 0]),
         "R": np.array([0.02, 0, 0.03, 0, 0, 0]), "C": np.array([0.007, 0, 0.014, 0, 0, 0]),
         "W": np.array([1, 0, 1, 0, 0, 0])}
    m = np.ones(T, dtype=bool)
    x = cs.cell(a, m, 1, 1)
    assert x["n"] == 3 and x["bars"] == 2
    assert x["ex_bps"] == pytest.approx((0.01 + 0.01) / 2 * 1e4)
    assert x["r_bps"] == pytest.approx(0.05 / 3 * 1e4)
    assert x["net_bps"] == pytest.approx((0.05 - 0.021) / 3 * 1e4)
    assert cs.cell(a, m, 1, -1)["ex_bps"] == pytest.approx(-x["ex_bps"])


def test_accumulate_counts_every_event():
    rng = np.random.default_rng(4)
    T, N = 200, 5
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.03, (T, N)), 0))
    o = np.vstack([c[:1], c[:-1]]) * np.exp(rng.normal(0, 0.005, (T, N)))
    B = barset(o, c)
    B.h = np.maximum(o, c) * np.exp(np.abs(rng.normal(0, 0.02, (T, N))))
    B.l = np.minimum(o, c) * np.exp(-np.abs(rng.normal(0, 0.02, (T, N))))
    R, V, base = cs.returns(B)
    acc = cs.accumulate(B, R, V, base, chunk=2)
    hits = cs.bar_signals(B)
    for s in ("doji", "engulfing_bull", "bull_confluence"):
        assert acc[s][3]["N"].sum() == (hits[s] & V[3]).sum()
    # The same-bar mean makes the excess of "every bar" zero on each bar.
    allbars = V[1]
    e = np.where(allbars, R[1] - base[1][:, None], 0).sum(1)
    np.testing.assert_allclose(e, 0, atol=1e-12)


def test_pool_units_keep_the_annual_sharpe():
    rng = np.random.default_rng(2)
    x = rng.normal(0.0005, 0.01, 2520)
    s, n, _, _ = cs.pool_units(x, 252.0)
    annual = x.mean() / x.std() * math.sqrt(252)
    assert s * math.sqrt(365) == pytest.approx(annual)
    assert n == round(2520 * 365 / 252)
    s2, n2, _, _ = cs.pool_units(x, 365.0)
    assert s2 == pytest.approx(x.mean() / x.std()) and n2 == 2520


def test_choose_picks_needs_net_above_drift_and_takes_best_horizon():
    rows = [
        {"set": "CD", "signal": "hammer", "h": 1, "dir": 1, "is_n": 500, "is_t": 3.5, "is_net_bps": 5, "drift_is_bps": 2},
        {"set": "CD", "signal": "hammer", "h": 5, "dir": 1, "is_n": 500, "is_t": 4.0, "is_net_bps": 9, "drift_is_bps": 8},
        {"set": "CD", "signal": "piercing", "h": 3, "dir": 1, "is_n": 500, "is_t": 9.0, "is_net_bps": 1, "drift_is_bps": 3},
        {"set": "CD", "signal": "doji", "h": 3, "dir": 1, "is_n": 500, "is_t": 9.0, "is_net_bps": 50, "drift_is_bps": 3},
        {"set": "CD", "signal": "engulfing_bull", "h": 3, "dir": 1, "is_n": 50, "is_t": 9.0, "is_net_bps": 50,
         "drift_is_bps": 3},
    ]
    p = cs.choose_picks(rows)["CD"]
    assert [(r["signal"], r["h"]) for r in p] == [("hammer", 5)]
