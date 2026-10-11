"""The blend study's simulator, blend and breakout cadence on a synthetic panel. No lab data.

Run from research/lab:  python -m pytest tests
"""

from __future__ import annotations

import numpy as np
import pytest

from lab.experiments import blend_study as bl
from lab.experiments import fam_breakout
from lab.experiments import fam_common as fc

T, N = 400, 6


@pytest.fixture()
def panel() -> fc.Panel:
    rng = np.random.default_rng(7)
    ret = rng.normal(0.001, 0.03, (T, N))
    ret[0] = np.nan
    px = 100 * np.cumprod(1 + np.nan_to_num(ret), axis=0)
    alive = np.ones((T, N), dtype=bool)
    alive[300:, 5] = False                      # coin 5 is delisted at day 300
    px[~alive] = np.nan
    ret[~alive] = np.nan
    traded = alive.copy()
    traded[50, 2] = False                       # one day without a bar
    close = np.where(traded, px, np.nan)
    days = np.arange(T, dtype=np.int64) * fc.DAY_US
    names = [f"C{j}USDT" for j in range(N)]
    names[0] = "BTCUSDT"
    sigma = np.full((T, N), 0.03)
    idx = np.arange(T)[:, None]
    return fc.Panel(days=days, names=names, bases=[fc.base_of(n) for n in names], close=close, px=px,
                    high=px, low=px, ret=ret, alive=alive, traded=traded, age=np.where(alive, idx, -1),
                    adv28=np.where(alive, 1e7 * (N - np.arange(N))[None, :], np.nan), sigma=sigma,
                    eligible=alive & traded & (idx >= 60), perp_ok=np.zeros((T, N), dtype=bool),
                    funding=np.zeros((T, N)), btc_on=np.arange(T) % 100 < 70, btc=0)


def random_weights(seed: int = 1) -> np.ndarray:
    rng = np.random.default_rng(seed)
    W = rng.uniform(0, 0.2, (T, N)) * (rng.random((T, N)) < 0.7)
    W[rng.random((T, N)) < 0.1] = np.nan       # "leave as it is"
    return W


def test_band_zero_is_the_sweep_simulator(panel):
    W = random_weights()
    b = bl.sim_long(panel, W)
    g, tv, le, _ = fc.simulate(panel, W, start=bl.START)
    assert np.allclose(b.gross, g)
    assert np.allclose(b.turnover, tv)
    assert np.allclose(b.expo, le)


def test_weekly_rebalance_matches_the_sweep_simulator(panel):
    W = random_weights(2)
    mask = fc.every(panel, 7)
    b = bl.sim_long(panel, W, rebalance=mask)
    assert np.allclose(b.gross, fc.simulate(panel, W, mask, start=bl.START)[0])
    off = ~mask
    off[300] = False                            # the delisted coin is closed on its first dead day
    assert np.all(b.turnover[off] == 0)
    assert b.turnover.sum() < bl.sim_long(panel, W).turnover.sum()


def test_bands_only_cut_resizing(panel):
    W = random_weights(3)
    base = bl.sim_long(panel, W)
    band = bl.sim_long(panel, W, band=0.5)
    frozen = bl.sim_long(panel, W, band=np.inf)
    assert frozen.turnover.sum() <= band.turnover.sum() <= base.turnover.sum()


def test_band_inf_trades_entries_and_exits_only(panel):
    W = np.zeros((T, N))
    W[100:200, 1] = 0.1
    W[150:200, 1] = 0.12                        # a resize the band must skip
    b = bl.sim_long(panel, W, band=np.inf)
    traded_days = np.flatnonzero(b.turnover)
    assert set(traded_days) == {100, 200}
    assert b.turnover[100] == pytest.approx(0.1)


def test_one_sleeve_blend_is_the_sleeve(panel):
    s = bl.sim_long(panel, random_weights(4), "s")
    b = bl.blend([s], "equal capital", None)
    assert np.allclose(b.gross, s.gross)
    assert np.allclose(b.turnover[bl.START + 1:], s.turnover[bl.START + 1:])
    assert np.allclose(b.expo, s.expo)


def test_two_identical_sleeves_are_one(panel):
    s = bl.sim_long(panel, random_weights(5), "s")
    for wt in bl.WEIGHTINGS:
        b = bl.blend([s, s], wt, None)
        assert np.allclose(b.gross, s.gross)
        assert np.allclose(b.turnover[bl.START + 1:], s.turnover[bl.START + 1:])


def test_vol_target_never_levers_the_book(panel):
    a = bl.sim_long(panel, random_weights(6) * 3, "a")
    c = bl.sim_long(panel, random_weights(7) * 3, "c")
    for vt in (0.15, 0.25, 5.0):
        b = bl.blend([a, c], "inverse vol", vt)
        assert b.expo.max() <= 1 + 1e-9


def test_allocations_drift_between_resets(panel):
    """Two sleeves with different returns: equal capital is only restored on a re-set day,
    and the re-set is charged."""
    rng = np.random.default_rng(8)
    g1 = np.r_[np.zeros(bl.START + 1), rng.normal(0.01, 0.01, T - bl.START - 1)]
    g2 = np.zeros(T)
    one = np.ones(T)
    s1, s2 = bl.Book("up", g1, np.zeros(T), one), bl.Book("flat", g2, np.zeros(T), one)
    b = bl.blend([s1, s2], "equal capital", None)
    resets = np.arange(bl.START, T - 1, bl.REWEIGHT)
    assert np.all(b.turnover[resets[1:]] > 0)
    others = np.setdiff1d(np.arange(bl.START + 1, T - 1), resets)
    assert np.all(b.turnover[others] == 0)


def test_breakout_every_one_is_the_sweep_rule(panel):
    cols = np.arange(N)
    allowed = panel.eligible
    W1 = bl.breakout_every(panel, cols, allowed, 20, 5, regime=False, every=1)
    Wref = fam_breakout.breakout_weights(panel, cols, allowed, 20, 5, regime=False)
    assert np.array_equal(np.isnan(W1), np.isnan(Wref))
    assert np.allclose(np.nan_to_num(W1), np.nan_to_num(Wref))


def test_breakout_every_seven_decides_on_check_days_only(panel):
    cols = np.arange(N)
    W7 = bl.breakout_every(panel, cols, panel.eligible, 20, 5, regime=True, every=7)
    decided = np.isfinite(W7).any(1)
    assert np.all(np.arange(T)[decided] % 7 == 0)


def test_identical_series_have_no_sharpe_difference():
    rng = np.random.default_rng(9)
    x = rng.normal(0.001, 0.02, 300)
    idx = bl.boot_idx(len(x), 20, 200, rng)
    d = bl.boot_diff(x, x, idx)
    assert d["diff"] == 0 and d["p05"] == 0 and d["p95"] == 0
