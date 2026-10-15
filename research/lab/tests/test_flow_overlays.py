"""X6 flow overlays on synthetic data: timing of every signal, the overlay arithmetic,
the walk-forward logit's purge, the trial count.

Run from research/lab:  python -m pytest tests/test_flow_overlays.py
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import numpy as np
import polars as pl
import pytest

from lab.collect import flow as flowsrc
from lab.experiments import flow_overlays as fo

DAY = fo.DAY_US


def fake_panel(T: int, start: str = "2021-01-01") -> SimpleNamespace:
    d0 = int(datetime.fromisoformat(start).replace(tzinfo=timezone.utc).timestamp() * 1e6)
    days = d0 + DAY * np.arange(T, dtype=np.int64)
    return SimpleNamespace(days=days, T=T, close=np.full((T, 1), 100.0), btc=0)


def test_scale_from_z_bands_and_missing():
    z = np.array([np.nan, -3.0, 0.4, 0.5, 1.4, 1.5, 3.0])
    assert fo.scale_from_z(z, +1, 0.5, 1.5).tolist() == [1, 1, 1, 0.5, 0.5, 0, 0]
    assert fo.scale_from_z(z, -1, 1.0, 2.0).tolist() == [1, 0, 1, 1, 1, 1, 1]


def test_zscore_is_point_in_time():
    rng = np.random.default_rng(1)
    x = rng.normal(size=600)
    z = fo.zscore(x)
    y = x.copy()
    y[400:] += 50.0
    z2 = fo.zscore(y)
    assert np.array_equal(np.isnan(z[:400]), np.isnan(z2[:400]))
    assert np.allclose(z[:400][np.isfinite(z[:400])], z2[:400][np.isfinite(z2[:400])])
    assert np.isnan(z[:fo.Z_MIN - 1]).all() and np.isfinite(z[fo.Z_MIN - 1])
    # The value of the day is part of its own window.
    w = x[400 - fo.Z_WINDOW + 1:401]
    assert z[400] == pytest.approx((x[400] - w.mean()) / w.std())


def test_overlay_arithmetic():
    g = np.array([0.0, 0.01, -0.02, 0.03, 0.01])
    tov = np.array([1.0, 0.0, 0.2, 0.0, 0.0])
    ex = np.array([1.0, 1.0, 1.0, 1.0, 1.0])
    go, tv, sx, S = fo.apply_overlay(g, tov, ex, np.ones(5))
    assert np.allclose(go, g) and np.allclose(tv, tov)
    S = np.array([1.0, 0.5, 0.5, 0.0, 1.0])
    go, tv, sx, _ = fo.apply_overlay(g, tov, ex, S)
    # The scale set at the close of t applies to the return of t+1.
    assert np.allclose(go, [0.0, 0.01, -0.01, 0.015, 0.0])
    assert np.allclose(tv, [1.0, 0.5, 0.1, 0.5, 1.0])
    go_late, _, _, S_late = fo.apply_overlay(g, tov, ex, S, late=1)
    assert S_late.tolist() == [1.0, 1.0, 0.5, 0.5, 0.0]
    assert np.allclose(go_late, [0.0, 0.01, -0.02, 0.015, 0.005])


def test_forward_return_window():
    r = np.array([0.0, 0.1, 0.1, -0.5, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
    f = fo.forward_return(r, 2)
    assert f[0] == pytest.approx(1.1 * 1.1 - 1)
    assert f[2] == pytest.approx(0.5 * 1.0 - 1)
    assert np.isnan(f[-2:]).all()


def test_walk_forward_logit_never_sees_labels_after_the_refit():
    T = 1200
    P = fake_panel(T, "2020-01-01")
    rng = np.random.default_rng(3)
    Z = rng.normal(size=(T, 3))
    y = (Z[:, 0] + rng.normal(size=T) > 0.8).astype(float)
    p1, S1, fits1 = fo.walk_forward_logit(P, Z, y, 0.1)
    qs = fo.quarter_starts(P)
    first = next(a for a in qs if np.isfinite(p1[a]))
    nxt = next(a for a in qs if a > first)
    y2 = y.copy()
    y2[first - fo.HORIZON:] = 1 - y2[first - fo.HORIZON:]
    p2, S2, _ = fo.walk_forward_logit(P, Z, y2, 0.1)
    assert np.allclose(p1[first:nxt], p2[first:nxt])
    assert np.isnan(p1[:first]).all()
    assert fits1[0]["rows"] >= fo.MIN_TRAIN
    assert set(np.unique(S1)) <= {0.0, 0.5, 1.0}
    # About 30 % of the training rows are above the 70th percentile: the scale is not stuck.
    assert 0.05 < (S1[first:] < 1).mean() < 0.6


def test_stables_used_one_day_after_their_stamp(tmp_path, monkeypatch):
    monkeypatch.setattr(flowsrc, "FLOW", tmp_path)
    P = fake_panel(5)
    pl.DataFrame({"day_us": P.days, "usdt": [1.0, 2, 3, 4, 5], "usdc": [10.0, 20, 30, 40, 50],
                  "total": [0.0] * 5}).write_parquet(tmp_path / "stables.parquet")
    v = fo.stable_supply(P)
    assert np.isnan(v[0]) and v[1:].tolist() == [11.0, 22.0, 33.0, 44.0]


def test_korean_premium_uses_the_last_ecb_rate(tmp_path, monkeypatch):
    monkeypatch.setattr(flowsrc, "FLOW", tmp_path)
    P = fake_panel(10)
    pl.DataFrame({"day_us": P.days, "open": 0.0, "high": 0.0, "low": 0.0, "close": 110_000.0 * np.ones(10),
                  "value_krw": 0.0}).write_parquet(tmp_path / "upbit_krwbtc_1d.parquet")
    # Rates only on days 0 and 4: days 1-3 use day 0's, 4-9 day 4's.
    pl.DataFrame({"day_us": P.days[[0, 4]], "usdkrw": [1000.0, 1100.0]}).write_parquet(tmp_path / "fx_usdkrw.parquet")
    x = fo.sig_kr_prem(P)
    # 7-day mean of 0.10 (days 0-3) and 0.0 (days 4-9), at least 5 values.
    assert np.isnan(x[3])
    assert x[4] == pytest.approx(0.4 / 5)
    assert x[9] == pytest.approx(0.1 / 7)


def test_trial_count_and_pool_constants():
    n_single = len(fo.SIGNALS) * 2 * len(fo.THRESHOLDS) * len(fo.BOOKS)
    n_combo = len(fo.FEATURE_SETS) * len(fo.COMBO_C) * len(fo.BOOKS)
    n_picks = len(fo.SIGNALS) * len(fo.BOOKS) + len(fo.BOOKS)
    assert n_single == 120 and n_combo == 12
    assert n_single + n_combo + 2 * n_picks == fo.HERE_TRIALS == 198
    assert fo.PRIOR_TRIALS + fo.PARALLEL_HAND == 608
    assert set(fo.FEATURE_SETS["long"]) < set(fo.SIGNALS) and fo.PRIMARY == ("long", 0.1)
