"""C6 study helpers on a synthetic panel. No lab data.

Run from research/lab:  python -m pytest tests
"""

from __future__ import annotations

import numpy as np
import pytest

from lab.experiments import blend_study as bl
from lab.experiments import fam_breakout, fam_volmom
from lab.experiments import fam_common as fc
from lab.experiments import m2_longonly as m2

T, N = 400, 6


@pytest.fixture()
def panel() -> fc.Panel:
    rng = np.random.default_rng(11)
    ret = rng.normal(0.001, 0.03, (T, N))
    ret[0] = np.nan
    px = 100 * np.cumprod(1 + np.nan_to_num(ret), axis=0)
    alive = np.ones((T, N), dtype=bool)
    alive[300:, 5] = False
    px[~alive] = np.nan
    ret[~alive] = np.nan
    traded = alive.copy()
    close = np.where(traded, px, np.nan)
    days = np.arange(T, dtype=np.int64) * fc.DAY_US
    names = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "ZZZUSDT", "DOGEUSDT"]
    idx = np.arange(T)[:, None]
    return fc.Panel(days=days, names=names, bases=[fc.base_of(n) for n in names], close=close, px=px,
                    high=px, low=px, ret=ret, alive=alive, traded=traded, age=np.where(alive, idx, -1),
                    adv28=np.where(alive, 1e7 * (N - np.arange(N))[None, :], np.nan),
                    sigma=np.full((T, N), 0.03), eligible=alive & traded & (idx >= 60),
                    perp_ok=np.zeros((T, N), dtype=bool), funding=np.zeros((T, N)),
                    btc_on=np.arange(T) % 100 < 70, btc=0)


def scores(seed: int = 3) -> dict[str, np.ndarray]:
    rng = np.random.default_rng(seed)
    s = rng.normal(size=(T, N))
    s[:100] = np.nan
    pct = np.argsort(np.argsort(s, axis=1), axis=1) / (N - 1)
    return {"score": s, "pct": np.where(np.isfinite(s), pct, np.nan), "abs_pred": s * 0.01}


def test_walk_forward_never_trains_inside_the_embargo():
    days = np.repeat(np.arange(200), 3).astype(np.int64) * fc.DAY_US
    X = np.zeros((len(days), 1))
    seen = []

    class Fit:
        def __init__(self, train):
            seen.append(train.copy())

        def predict(self, x):
            return np.ones(len(x))

    starts = [int(d) * fc.DAY_US for d in (100, 130, 160)]
    out = m2.walk_scores(days, Fit, X, starts, embargo_d=7, log=lambda *_: None)
    assert np.all(np.isnan(out[days < starts[0]]))
    assert np.all(out[days >= starts[0]] == 1)
    for s, tr in zip(starts, seen):
        assert days[tr].max() < s - 7 * fc.DAY_US


def test_month_starts():
    from datetime import datetime, timezone
    s = m2.month_starts(datetime(2022, 11, 1, tzinfo=timezone.utc),
                        int(datetime(2023, 2, 15, tzinfo=timezone.utc).timestamp() * 1e6))
    assert [datetime.fromtimestamp(x / 1e6, timezone.utc).month for x in s] == [11, 12, 1, 2]


def test_alpaca_mask_skips_other_coins_and_dead_segments(panel):
    panel.names[1] = "ETHUSDT~0"
    U = m2.alpaca_mask(panel, coins=("BTC", "ETH", "SOL", "DOGE"))
    assert U[:, [0, 2, 5]].any(0).all()
    assert not U[:, [1, 3, 4]].any()
    assert not U[:60].any()


def test_low_mask(panel):
    S = scores()
    U = panel.eligible
    low = m2.low_mask(U, S, ("pct", 0.5))
    assert np.array_equal(low, U & (np.nan_to_num(S["pct"], nan=1) < 0.5))
    worst = m2.low_mask(U, S, ("worst", 2))
    t = 200
    ok = np.flatnonzero(U[t])
    assert set(np.flatnonzero(worst[t])) == set(ok[np.argsort(S["score"][t, ok])[:2]])
    assert not worst[:100].any()                     # no score, never low


def test_unfiltered_books_are_the_sweep_rules(panel):
    U = panel.top_liquid(3)
    assert np.allclose(m2.tsmom_weights(panel, U), fam_volmom.base_weights(panel, 3, regime=True))
    cols = np.flatnonzero(U.any(0))
    a = m2.breakout_weights(panel, U, slots=3)
    b = fam_breakout.breakout_weights(panel, cols, U, 20, 3, regime=False)
    assert np.array_equal(np.isnan(a), np.isnan(b))
    assert np.allclose(np.nan_to_num(a), np.nan_to_num(b))


def test_tsmom_filter_only_empties_slots(panel):
    U = panel.eligible
    drop = m2.low_mask(U, scores(), ("worst", 2))
    base, filt = m2.tsmom_weights(panel, U), m2.tsmom_weights(panel, U, drop)
    assert np.all(filt[drop] == 0)
    assert np.allclose(filt[~drop], base[~drop])


def test_breakout_block_and_sell(panel):
    U = panel.eligible
    block = np.zeros((T, N), dtype=bool)
    block[:, 1] = True
    W = m2.breakout_weights(panel, U, block, sell=False)
    assert np.all(np.nan_to_num(W[:, 1]) == 0)       # never entered
    block = np.zeros((T, N), dtype=bool)
    block[250:, :] = True
    base = m2.breakout_weights(panel, U)
    sold = m2.breakout_weights(panel, U, block, sell=True)
    assert np.allclose(np.nan_to_num(sold[:250]), np.nan_to_num(base[:250]))
    g = bl.sim_long(panel, sold, start=60)
    assert np.all(g.expo[251:] == 0)


def test_topk_and_sticky_equal(panel):
    S = scores()
    U = panel.eligible
    mk = m2.topk_mask(S["score"], U, 2)
    t = 200
    ok = np.flatnonzero(U[t])
    assert set(np.flatnonzero(mk[t])) == set(ok[np.argsort(-S["score"][t, ok])[:2]])
    assert not mk[:100].any()
    W = m2.sticky_equal(U)
    assert np.allclose(W[60, U[60]], 1 / U[60].sum())
    assert np.all(np.isnan(W[61]))                   # same set: drift
    assert np.isfinite(W[300]).all()                 # coin 5 died: re-set


def test_one_tranche_is_daily_rebalancing(panel):
    W = fc.equal_weight(panel.eligible)
    a = m2.tranche_book(panel, W, 60, "x", n=1)
    b = bl.sim_long(panel, W, start=60)
    assert np.allclose(a.gross, b.gross) and np.allclose(a.turnover, b.turnover)
    seven = m2.tranche_book(panel, W, 60, "x")
    assert seven.turnover.sum() < b.turnover.sum()


def test_timing_signals(panel):
    S = scores()
    U = panel.eligible
    S["abs_pred"][:] = -0.01
    S["abs_pred"][150:] = 0.01
    sig = m2.timing_signals(panel, U, S)
    on = sig["M2-abs universe median >= 0"]
    assert not on[:150].any() and on[150:].all()
    rel = sig["15 mean pct >= 0.5"]
    assert not rel[:100].any()                       # unscored days stay in cash
