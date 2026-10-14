"""M7, the HMM regime gate: filtered probabilities only, point-in-time refits, the gates. No lab data.

Run from research/lab:  python -m pytest tests
"""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pytest

from lab.experiments import fam_common as fc
from lab.experiments import regime_hmm as rh

from test_tsmom_tranches import make_panel, weights


def two_regimes(T: int = 700, seed: int = 3) -> np.ndarray:
    """Two features, a calm up state and a wild down state, switching in long blocks."""
    rng = np.random.default_rng(seed)
    state = (np.arange(T) // 90) % 2
    mean = np.where(state[:, None] == 0, [0.05, -1.0], [-0.06, 1.0])
    return mean + rng.normal(0, [0.03, 0.3], (T, 2))


def test_forward_filter_never_sees_the_future():
    X = two_regimes()
    fit = rh.fit_hmm(X[:400], 2)
    Z = (X - fit.mu) / fit.sd
    a = rh.forward_filter(Z, fit.startprob, fit.transmat, fit.means, fit.covars)
    Z2 = Z.copy()
    Z2[500:] = -Z2[500:] * 3
    b = rh.forward_filter(Z2, fit.startprob, fit.transmat, fit.means, fit.covars)
    assert np.allclose(a[:500], b[:500])
    assert not np.allclose(a[500:], b[500:])
    assert np.allclose(a.sum(1), 1)


def test_forward_filter_last_row_matches_hmmlearn():
    """On the last row the smoothed and the filtered probability are the same thing."""
    X = two_regimes()
    fit = rh.fit_hmm(X[:400], 2)
    Z = (X[:400] - fit.mu) / fit.sd
    a = rh.forward_filter(Z, fit.startprob, fit.transmat, fit.means, fit.covars)
    m = rh._model(2, 0)
    m.startprob_, m.transmat_, m.means_, m.covars_ = fit.startprob, fit.transmat, fit.means, fit.covars
    assert np.allclose(a[-1], m.predict_proba(Z)[-1], atol=1e-6)


def test_bull_state_is_the_one_with_positive_returns():
    X = two_regimes()
    fit = rh.fit_hmm(X, 2)
    bull = rh.bull_states(fit)
    assert bull.sum() == 1
    r7 = fit.means[:, 0] * fit.sd[0] + fit.mu[0]
    assert r7[bull][0] > 0 > r7[~bull][0]


def test_regime_is_point_in_time():
    """Changing the data after a day changes nothing on or before the last fit before that day."""
    X = two_regimes()
    T = len(X)
    t0 = int(datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp() * 1e6)
    days = t0 + np.arange(T, dtype=np.int64) * fc.DAY_US
    first_fit = int(days[300])
    a = rh.regime(X, 0, days, 2, first_fit)
    X2 = X.copy()
    cut = 520
    X2[cut:] = X2[cut:][::-1]
    b = rh.regime(X2, 0, days, 2, first_fit)
    assert np.isnan(a.p_bull[:300]).all()
    assert np.isfinite(a.p_bull[310:]).all()
    assert np.allclose(a.p_bull[:cut], b.p_bull[:cut], equal_nan=True)
    assert not np.allclose(a.p_bull[cut:], b.p_bull[cut:])
    # It finds the blocks: P(bull) is high in up blocks and low in down blocks, out of sample.
    up = ((np.arange(T) // 90) % 2 == 0) & (np.arange(T) >= 320)
    assert a.p_bull[up].mean() > 0.8 and a.p_bull[~up & (np.arange(T) >= 320)].mean() < 0.2


def test_switch_gate_has_hysteresis():
    p = np.array([np.nan, 0.7, 0.5, 0.45, 0.39, 0.5, 0.59, 0.61, 0.41])
    assert rh.switch_gate(p).tolist() == [1, 1, 1, 1, 0, 0, 0, 1, 1]
    assert rh.soft_gate(np.array([np.nan, 0.3, 1.2])).tolist() == [1.0, 0.3, 1.0]
    assert rh.lagged(np.array([0.0, 1.0, 0.0])).tolist() == [1.0, 0.0, 1.0]


def test_overlay_without_gate_is_the_book():
    """Holding 1 x the recorded holdings is fam_common.simulate on the weights themselves."""
    P = make_panel()
    W = weights()
    W[::3] = np.nan                           # rows that leave positions as they are
    g, tv, _, _ = fc.simulate(P, W, start=rh.START)
    H = rh.holdings(P, W)
    g2, tv2, _ = rh.gated(P, H, np.ones(P.T))
    assert np.allclose(g, g2)
    assert np.allclose(tv[rh.START + 1:], tv2[rh.START + 1:])


def test_overlay_off_is_flat_and_charges_the_switch():
    P = make_panel()
    H = rh.holdings(P, weights())
    s = np.ones(P.T)
    s[200:250] = 0.0
    g, tv, ex = rh.gated(P, H, s)
    assert np.all(g[201:251] == 0) and np.all(ex[200:250] == 0)
    assert tv[200] > 0.5 * H[200].sum() and tv[250] > 0.5 * H[250].sum()
