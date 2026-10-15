"""C16, the books on the coins Alpaca lists: universes, cash-left, twin lists, simulator. No lab data.

Run from research/lab:  python -m pytest tests
"""

from __future__ import annotations

import numpy as np
import pytest

from lab.experiments import alpaca_universe as au
from lab.experiments import fam_breakout, fam_common as fc, fam_volmom
from lab.experiments import tsmom_tranches as tt

from test_tsmom_tranches import T, N, make_panel, weights


@pytest.fixture()
def panel() -> fc.Panel:
    return make_panel()


def test_alpaca_mask_takes_listed_bases_and_current_segments_only(panel):
    P = panel
    P.names[3], P.names[4] = "SOLUSDT", "LUNAUSDT"
    P.names[5] = "ETHUSDT~0"
    P.bases[:] = [fc.base_of(n) for n in P.names]
    m = au.alpaca_mask(P)
    assert m.tolist() == [True, True, False, True, False, False]


def test_top_within_matches_top_liquid_when_everything_is_a_member(panel):
    for k in (1, 3, 6):
        assert np.array_equal(au.top_within(panel, np.ones(N, dtype=bool), k), panel.top_liquid(k))


def test_top_within_never_picks_outside_the_list(panel):
    member = np.array([False, True, False, True, True, False])
    u = au.top_within(panel, member, 2)
    assert not u[:, ~member].any()
    assert (u.sum(1)[60:] == 2).all()
    # The two most liquid members (adv falls with the column index).
    assert u[100, 1] and u[100, 3] and not u[100, 4]


def test_tsmom_weights_is_base_weights_on_the_top_liquid_universe(panel):
    for k in (2, 4):
        assert np.allclose(au.tsmom_weights(panel, panel.top_liquid(k)),
                           fam_volmom.base_weights(panel, k, regime=True), equal_nan=True)


def test_breakout_on_is_the_paper_books_rule(panel):
    top = panel.top_liquid(3)
    cols = np.flatnonzero(top.any(0))
    ref = fam_breakout.breakout_weights(panel, cols, top, 20, 3, regime=False)
    assert np.allclose(au.breakout_on(panel, top, 20, 3), ref, equal_nan=True)


def test_cash_left_zeroes_unlisted_and_keeps_the_rest():
    W = np.array([[0.1, np.nan, 0.2], [np.nan, 0.3, 0.4]])
    alp = np.array([True, True, False])
    out = au.cash_left(W, alp)
    assert out[0, 0] == 0.1 and np.isnan(out[0, 1]) and out[0, 2] == 0.0
    assert np.isnan(out[1, 0]) and out[1, 1] == 0.3 and out[1, 2] == 0.0


def test_one_day_late_shifts_by_one_close():
    W = np.arange(12, dtype=float).reshape(4, 3)
    L = au.one_day_late(W)
    assert (L[0] == 0).all()
    assert np.array_equal(L[1:], W[:-1])


def test_sim_daily_is_the_sweeps_simulator(panel):
    for W in (weights(1), np.where(np.random.default_rng(2).random((T, N)) < 0.9, np.nan, weights(2))):
        g, tv, ex, held = au.sim_daily(panel, W)
        rg, rtv, rle, _ = fc.simulate(panel, W, start=au.START)
        assert np.allclose(g, rg)
        assert np.allclose(tv[:-1], rtv[:-1])      # the sweep does not trade its last close
        assert np.allclose(ex[:-1], rle[:-1])
        assert np.allclose(held.sum(1), ex)


def test_drifted_reproduces_the_turnover(panel):
    W = weights(4)
    g, tv, ex, held = au.sim_daily(panel, W)
    pre = au.drifted(panel, held)
    # Before coin 5 dies (day 300) the turnover at a close is exactly the trade from the drifted book.
    rows = np.arange(au.START + 1, 300)
    assert np.allclose(np.abs(held - pre).sum(1)[rows], tv[rows])


def test_activity_counts_entries_and_exits(panel):
    held = np.zeros((T, N))
    held[100:110, 1] = 0.5          # one round trip: two trades
    held[200:, 2] = 0.2             # one entry still open: one trade
    mask = np.zeros(T, dtype=bool)
    mask[90:] = True
    a = au.activity(panel, held, mask)
    months = mask.sum() / (365 / 12)
    assert a["trades_month"] == pytest.approx(3 / months)


def test_annual_lists_are_point_in_time_and_frozen(panel):
    member, lists = au.annual_lists(panel, size=3)
    yr = au.years_of(panel)
    for y, names in lists.items():
        assert len(names) <= 3
        rows = np.flatnonzero((yr == y) & member.any(1))
        # Frozen within the year: membership only ever shrinks (a coin dies), never grows.
        for a, b in zip(rows[:-1], rows[1:]):
            assert not (member[b] & ~member[a]).any()
    # A list chosen at the first close of a year uses no later data: moving adv after that close
    # does not change it.
    P2 = make_panel()
    t0 = int(np.flatnonzero(yr == yr[-1])[0])
    P2.adv28[t0 + 1:] = P2.adv28[t0 + 1:, ::-1]
    _, l2 = au.annual_lists(P2, size=3)
    assert l2 == lists


def test_tranche_path_is_the_paper_books_simulator(panel):
    W = weights(5)
    g, tv, ex, held = au.simulate(panel, "tsmom_tranches", W)
    rg, rtv, rex, _, _, _ = tt.simulate(panel, W)
    assert np.allclose(g, rg) and np.allclose(tv, rtv) and np.allclose(ex, rex)


def test_prior_variance_gives_back_the_published_bar():
    assert fc._sr0(au.prior_var(), au.PRIOR_TRIALS) * np.sqrt(365) == pytest.approx(au.PRIOR_SR0, rel=1e-9)


def test_trial_count_matches_the_registration():
    # C 3 + R 20 + T 20 + L 3
    assert 3 + 2 * (len(au.KS) * len(au.NS) + 2 * len(au.KS)) + 3 == au.HERE_TRIALS
