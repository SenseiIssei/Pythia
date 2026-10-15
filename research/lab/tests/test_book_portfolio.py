"""The book portfolio study on synthetic return series. No market data.

Run from research/lab:  python -m pytest tests
"""

from __future__ import annotations

import numpy as np
import pytest

from lab.experiments import book_portfolio as bp


def days(n: int, start: str = "2020-01-01") -> np.ndarray:
    d0 = np.datetime64(start, "D")
    return np.arange(d0, d0 + np.timedelta64(n, "D"), dtype="datetime64[D]")


def test_inverse_vol_and_risk_parity():
    rng = np.random.default_rng(0)
    R = rng.normal(0, 1, (400, 3)) * np.array([0.01, 0.02, 0.04])
    w = bp.inv_vol(R, 400)
    assert w.sum() == pytest.approx(1.0) and w[0] > w[1] > w[2]
    assert w[0] / w[2] == pytest.approx(4.0, rel=0.25)
    rp = bp.risk_parity(R, 400)
    S = np.cov(R[310:400], rowvar=False) + bp.RIDGE * np.eye(3)
    rc = rp * (S @ rp)
    assert rc.max() / rc.min() == pytest.approx(1.0, abs=1e-3)
    assert np.allclose(bp.inv_vol(R, 5), 1 / 3)             # too little history: equal weight
    flat = np.zeros((200, 2))
    assert np.allclose(bp.inv_vol(flat, 200), 0.5)          # the floor keeps a book in cash finite


def test_weights_only_move_on_reweight_days_and_use_the_past():
    rng = np.random.default_rng(1)
    d = days(300)
    R = rng.normal(0, 0.01, (300, 4))
    W = bp.crypto_weights(R, "IV", d)
    moves = np.flatnonzero(np.abs(np.diff(W, axis=0)).sum(1) > 0) + 1
    assert all(d[t].astype(np.int64) % bp.REWEIGHT_DAYS == 0 for t in moves)
    R2 = R.copy()
    R2[250:] *= 10                                           # the future cannot change today's weights
    assert np.allclose(bp.crypto_weights(R2, "IV", d)[:251], W[:251])


def test_scales():
    rng = np.random.default_rng(2)
    base = rng.normal(0, 0.03, 300)                          # about 57 % a year
    s = bp.scale(base, "VT15")
    assert (s <= 1).all() and s[100] == pytest.approx(0.15 / bp.realised_vol(base)[100])
    crash = np.r_[np.zeros(10), np.full(12, -0.02), np.zeros(5)]       # 21.5 % down
    s = bp.scale(crash, "DDB")
    dd = 1 - np.cumprod(1 + crash) / np.maximum.accumulate(np.r_[1.0, np.cumprod(1 + crash)])[1:]
    assert s[0] == 1.0 and s[-1] == 0.25 and 0.5 in s
    assert (s[1:][dd[:-1] < 0.10] == 1.0).all()             # decided from yesterday's drawdown


def test_portfolio_costs_and_drift():
    R = np.zeros((5, 2))
    W = np.full((5, 2), 0.5)
    net, tov = bp.portfolio(R, W, np.array([0.0035, 0.0002]))
    assert net[0] == pytest.approx(-(0.5 * 0.0035 + 0.5 * 0.0002)) and (net[1:] == 0).all()
    R[1] = [0.10, 0.0]
    net, tov = bp.portfolio(R, W, np.array([0.0035, 0.0002]))
    g = 0.05
    held = np.array([0.55, 0.5]) / (1 + g)
    assert net[1] == pytest.approx(g) and tov[2] == pytest.approx(np.abs(0.5 - held).sum())


def test_regime_book_holds_only_listed_coins_and_only_risk_on():
    rng = np.random.default_rng(3)
    T, N = 400, 3
    close = 100 * np.cumprod(1 + rng.normal(0.002, 0.02, (T, N)), axis=0)
    rv = np.full((T, N), 0.02 ** 2)
    sigma = np.sqrt(rv)
    history = np.cumsum(np.isfinite(close), axis=0)
    on = np.ones(T, dtype=bool)
    all_in = bp.regime_returns(close, sigma, history, on, np.ones(N))
    none = bp.regime_returns(close, sigma, history, ~on, np.ones(N))
    one = bp.regime_returns(close, sigma, history, on, np.array([1.0, 0.0, 0.0]))
    assert (none == 0).all() and np.abs(all_in).sum() > 0
    only0 = bp.regime_returns(close[:, :1], sigma[:, :1], history[:, :1], on, np.ones(1))
    assert np.abs(one).sum() > 0 and not np.allclose(one, all_in)
    assert np.corrcoef(one[250:], only0[250:])[0, 1] > 0.99


def test_run_on_synthetic_books(monkeypatch):
    rng = np.random.default_rng(4)
    d = days(2400, "2019-11-01")
    common = rng.normal(0.0008, 0.02, len(d))
    books = {b: 0.5 * common + rng.normal(0.0003, 0.01, len(d)) for b in bp.BOOKS}
    weekday = np.is_busday(d)
    eq = {"spy": np.where(weekday, rng.normal(0.0005, 0.01, len(d)), 0.0),
          "overnight": np.where(weekday, rng.normal(0.0004, 0.006, len(d)), 0.0), "overnight_name": "U1 SPY · R1 trend"}
    monkeypatch.setattr(bp, "a_trial_sharpes", lambda: [])
    res = bp.run(d, books, eq, seed=1)
    assert len(res["rows"]) == 30 and res["pick"] in {r["name"] for r in res["rows"]}
    assert res["pool"]["n_total"] == bp.on.PRIOR_TRIALS + bp.A_TRIALS + 30
    assert set(res["gates"]) and res["best_book"] in bp.BOOKS
    md = bp.markdown(res)
    assert "Verdict" in md and "—" not in md
