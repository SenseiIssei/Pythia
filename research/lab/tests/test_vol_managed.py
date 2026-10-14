"""The vol-managed study's forecasts, books and overlays on synthetic data. No lab data.

Run from research/lab:  python -m pytest tests
"""

from __future__ import annotations

import numpy as np
import polars as pl

from lab.experiments import fam_common as fc
from lab.experiments import vol_managed as vm

T, N = 200, 3
T0 = 1_577_836_800_000_000      # 2020-01-01 UTC, us


def panel(seed: int = 5) -> fc.Panel:
    rng = np.random.default_rng(seed)
    ret = rng.normal(0.0, 0.03, (T, N))
    ret[0] = np.nan
    px = 100 * np.exp(np.nancumsum(np.nan_to_num(ret), 0))
    alive = np.ones((T, N), dtype=bool)
    alive[150:, 2] = False                      # coin 2 is delisted after day 149
    px = np.where(alive, px, np.nan)
    ret = np.where(alive, ret, np.nan)
    ret[150, 2] = np.nan
    rv = np.where(alive, ret ** 2 + 1e-4, np.nan)
    sigma = np.sqrt(fc.rolling(rv, 30, 20))
    z = np.zeros((T, N))
    days = T0 + np.arange(T, dtype=np.int64) * fc.DAY_US
    return fc.Panel(days=days, names=["BTCUSDT", "ETHUSDT", "SOLUSDT"], bases=["BTC", "ETH", "SOL"],
                    close=px, px=px, high=px, low=px, ret=ret, alive=alive, traded=alive.copy(), age=z,
                    adv28=z + 1e7, sigma=sigma, eligible=alive.copy(), perp_ok=np.zeros((T, N), dtype=bool),
                    funding=z, btc_on=np.arange(T) % 40 < 25, btc=0, extra={"rv": rv})


def test_ewma_is_point_in_time_and_waits_for_enough_data():
    x = np.random.default_rng(1).random((80, 2))
    a = vm.ewma(x)
    y = x.copy()
    y[50:] = 99.0                                # a different future must not change the past
    b = vm.ewma(y)
    assert np.allclose(a[:50], b[:50], equal_nan=True)
    assert np.isnan(a[: vm.MIN_OBS - 1]).all() and np.isfinite(a[vm.MIN_OBS - 1]).all()
    # One step of the recursion.
    assert np.isclose(a[40, 0], vm.LAMBDA * a[39, 0] + (1 - vm.LAMBDA) * x[40, 0])


def test_m1_daily_aggregate_uses_only_the_days_own_hours():
    ts = T0 + np.arange(48, dtype=np.int64) * fc.HOUR_US
    h = pl.DataFrame({"ts_us": ts, "symbol": ["BTCUSDT"] * 48, "rv": np.r_[np.full(24, 1.0), np.full(24, 2.0)],
                      "var_fc": np.r_[np.full(24, 0.5), np.full(24, 3.0)]})
    d = vm.m1_daily(h)
    assert d.height == 2
    assert np.allclose(d["m1_var"].to_numpy(), [12.0, 72.0])
    assert np.allclose(d["rv1m"].to_numpy(), [24.0, 48.0])


def test_scale_ratio_is_trailing():
    a = np.r_[np.full(100, 2.0), np.full(100, 8.0)][:, None]
    b = np.full((200, 1), 1.0)
    r = vm.scale_ratio(a, b, days=50, min_obs=10)
    assert np.isnan(r[8, 0]) and np.isclose(r[60, 0], 2.0) and np.isclose(r[199, 0], 8.0)
    assert np.isclose(r[110, 0], (39 * 2 + 11 * 8) / 50)


def test_managed_weights_cap_gate_and_equal_split():
    P = panel()
    mem = np.ones((T, N), dtype=bool)
    vol = np.full((T, N), 0.6)
    vol[:, 1] = 0.2                              # low vol: capped at 1 x its share
    vol[:, 2] = np.nan                           # no forecast: held at zero
    W = vm.managed_weights(P, mem, vol, 0.3, gate=False)
    assert np.allclose(W[:, 0], 0.5 / 3) and np.allclose(W[:, 1], 1 / 3) and np.allclose(W[:, 2], 0)
    Wg = vm.managed_weights(P, mem, vol, 0.3, gate=True)
    assert np.allclose(Wg[~P.btc_on], 0) and np.allclose(Wg[P.btc_on], W[P.btc_on])


def test_band_keeps_small_resizes_and_charges_turnover_once():
    P = panel()
    W = np.zeros((T, N))
    W[:, 0] = np.where(np.arange(T) < 100, 0.5, 0.55)   # a 10 % change inside a 25 % band
    g0, tv0, ex0 = vm.simulate(P, W, band=0.0)
    g1, tv1, ex1 = vm.simulate(P, W, band=0.25)
    assert tv1[vm.START] == 0.5                         # the entry always trades
    assert tv1[vm.START + 1:].sum() < tv0[vm.START + 1:].sum()
    # Without a band the book is rebalanced daily to the target: exposure is the target.
    assert np.allclose(ex0[vm.START:T - 1], W[vm.START:T - 1, 0])


def test_simulate_closes_a_delisted_coin_and_lag_shifts_the_trades():
    P = panel()
    W = np.zeros((T, N))
    W[70:, 2] = 0.3
    g, tv, ex = vm.simulate(P, W, band=0.1)
    assert ex[150:].max() == 0 and tv[150] > 0
    assert tv[70] == 0.3 and tv[vm.START:70].sum() == 0
    gl, tvl, _ = vm.simulate(P, W, band=0.1, lag=1)
    assert tvl[70] == 0 and tvl[71] == 0.3
    # The target decided at the close of t earns day t+1: gross = weight x return.
    assert np.isclose(g[71], 0.3 * P.ret[71, 2]) and g[70] == 0


def test_hold_weights_rebalance_monthly_and_on_membership_change():
    P = panel()
    mem = P.eligible.copy()
    W = vm.hold_weights(P, mem)
    reb = np.isfinite(W).all(1)
    assert reb[0] and reb[150]                   # first day; coin 2 leaves on day 150
    assert np.allclose(W[150], [0.5, 0.5, 0.0])
    first = [t for t in range(T) if str(np.datetime64(int(P.days[t]), "us").astype("datetime64[D]"))[8:] == "01"]
    assert all(reb[t] for t in first)
    assert not reb[1:31].any()


def test_overlay_scale_cap_band_and_point_in_time():
    f = np.r_[np.full(10, np.nan), np.full(40, 0.2), np.full(50, 0.4)]
    expo = np.full(100, 0.4)
    S = vm.overlay_scale(f, expo, c=0.3, band=0.1)
    assert np.allclose(S[:10], 1.0)
    assert np.allclose(S[10:50], 1.5) and np.allclose(S[50:], 0.75)
    assert (S * expo <= 1 + 1e-12).all()
    S2 = vm.overlay_scale(f, np.full(100, 0.9), c=0.3, band=0.1)
    assert np.allclose(S2[10:50], 1 / 0.9)       # never over 100 % invested
    assert vm.overlay_scale(f, expo, c=0.3, band=0.6)[49] == 1.0   # inside the band: stays at 1 (|1.5-1| < 0.9)


def test_overlay_returns_and_turnover():
    rng = np.random.default_rng(3)
    g = rng.normal(0, 0.02, 300)
    tov = np.full(300, 0.01)
    expo = np.full(300, 0.5)
    ins = np.zeros(300, dtype=bool)
    ins[60:200] = True
    go, tv, ex, c = vm.run_overlay(g, tov, expo, "RW30", 0.1, ins, start=0)
    f = vm.book_forecast(g, "RW30", 0)
    S = vm.overlay_scale(f, expo, c, 0.1)
    assert np.isclose(c, np.nanmedian(f[ins]))
    assert np.allclose(go[1:], S[:-1] * g[1:])
    assert np.allclose(tv[1:], S[1:] * tov[1:] + np.abs(np.diff(S)) * expo[1:])
    # The forecast at t uses returns up to t only.
    g2 = g.copy()
    g2[150:] *= 5
    assert np.allclose(vm.book_forecast(g2, "RW30", 0)[:150], f[:150], equal_nan=True)


def test_pool_adds_this_study_to_the_prior_265():
    v, pool = vm.pooled_var([0.5] * 91, -0.08)
    assert pool["n_total"] == 356 and pool["mine"] == 91
    # The prior alone reproduces fast_strategies' bar.
    assert abs(fc._sr0(vm.prior_var(), vm.PRIOR_TRIALS) * np.sqrt(365) - vm.PRIOR_SR0) < 1e-9


def test_registered_grid_size():
    n_grid = len(vm.ASSETS) * len(vm.FORECASTS) * len(vm.TVS) * len(vm.BANDS) * 2
    n_overlay = len(vm.OVERLAY_BOOKS) * len(vm.OVERLAY_FORECASTS) * len(vm.BANDS)
    picks = len(vm.ASSETS) + len(vm.OVERLAY_BOOKS)
    assert n_grid == 72 and n_overlay == 8
    assert n_grid + 3 + n_overlay + picks + 1 + len(vm.OVERLAY_BOOKS) == 91
