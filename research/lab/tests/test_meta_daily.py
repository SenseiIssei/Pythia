"""C14, meta-labeling the daily breakout book: the book, the labels, the purge, the uses. No lab data.

Run from research/lab:  python -m pytest tests
"""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pytest
from sklearn.metrics import roc_auc_score

from lab.experiments import fam_breakout, fam_common as fc
from lab.experiments import meta_daily as md

T, N = 900, 14
T0 = int(datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp() * 1e6)


def make_panel(seed: int = 5) -> fc.Panel:
    rng = np.random.default_rng(seed)
    ret = rng.normal(0.002, 0.04, (T, N)) + 0.01 * np.sin(np.arange(T) / 25)[:, None]
    ret[0] = np.nan
    px = 100 * np.cumprod(1 + np.nan_to_num(ret), axis=0)
    alive = np.ones((T, N), dtype=bool)
    alive[600:, 4] = False                      # coin 4 is delisted at day 600
    alive[:150, 6] = False                      # coin 6 lists at day 150
    px[~alive] = np.nan
    ret[~alive] = np.nan
    ret[150, 6] = np.nan
    traded = alive.copy()
    close = np.where(traded, px, np.nan)
    days = T0 + np.arange(T, dtype=np.int64) * fc.DAY_US
    names = [f"C{j}USDT" for j in range(N)]
    names[0], names[1] = "BTCUSDT", "ETHUSDT"
    idx = np.arange(T)[:, None]
    first = np.argmax(alive, 0)
    age = np.where(alive, idx - first[None, :], -1)
    qv = np.where(alive, 1e7 * (N - np.arange(N))[None, :] * rng.lognormal(0, 0.3, (T, N)), np.nan)
    rv = np.where(alive, rng.gamma(2.0, 0.0008, (T, N)), np.nan)
    adv28 = np.where(alive, fc.rolling(qv, 28, 20), np.nan)
    sigma = np.sqrt(fc.rolling(rv, 30, 20))
    perp_ok = alive & (np.arange(N)[None, :] < 8)
    funding = np.where(perp_ok, rng.normal(1e-4, 2e-4, (T, N)), 0.0)
    return fc.Panel(days=days, names=names, bases=[fc.base_of(n) for n in names], close=close, px=px,
                    high=px, low=px, ret=ret, alive=alive, traded=traded, age=age, adv28=adv28, sigma=sigma,
                    eligible=alive & traded & (age >= 60) & (np.nan_to_num(adv28) > 1e6),
                    perp_ok=perp_ok, funding=funding, btc_on=np.arange(T) % 100 < 70, btc=0,
                    extra={"qv": qv, "rv": rv})


@pytest.fixture(scope="module")
def panel() -> fc.Panel:
    return make_panel()


def test_unfiltered_book_is_the_sweeps(panel):
    top = panel.top_liquid(5)
    cols = np.flatnonzero(top.any(0))
    ref = fam_breakout.breakout_weights(panel, cols, top, 20, 5, regime=False)
    W, ent = md.book_weights(panel, cols, top, slots=5)
    assert np.array_equal(np.isnan(W), np.isnan(ref))
    assert np.allclose(np.nan_to_num(W), np.nan_to_num(ref))
    W1, _ = md.book_weights(panel, cols, top, np.ones((T, N)), slots=5)
    assert np.allclose(np.nan_to_num(W1), np.nan_to_num(ref)) and np.array_equal(np.isnan(W1), np.isnan(ref))
    assert ent.sum() > 10
    # The restricted simulator gives the full one's numbers.
    g = md.run_book(panel, cols, W)[0]
    assert np.allclose(g, fc.simulate(panel, ref, start=md.START)[0])


def test_a_skipped_entry_can_enter_on_a_later_signal(panel):
    top = panel.top_liquid(5)
    cols = np.flatnonzero(top.any(0))
    W, ent = md.book_weights(panel, cols, top, slots=5)
    t, j = map(int, np.argwhere(ent)[0])
    M = np.ones((T, N))
    M[t, j] = 0.0
    W2, ent2 = md.book_weights(panel, cols, top, M, slots=5)
    assert not ent2[t, j]
    sig = md.signals(panel) & top
    nxt = [u for u in range(t + 1, T) if sig[u, j]]
    if nxt:
        assert ent2[nxt[0], j]
    # Zero everywhere: nothing is ever bought.
    Wz, entz = md.book_weights(panel, cols, top, np.zeros((T, N)), slots=5)
    assert not entz.any() and np.nansum(Wz) == 0
    # Halving every multiplier halves every entry size.
    Wh, enth = md.book_weights(panel, cols, top, np.full((T, N), 0.5), slots=5)
    assert np.array_equal(enth, ent)
    assert np.allclose(Wh[ent], W[ent] * 0.5)
    # Candidates of the unfiltered book are exactly its entries.
    assert np.array_equal(md.candidates(panel, cols, top), ent)


def test_exits_and_labels_on_a_hand_made_coin():
    px = np.array([10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29,
                   30, 31, 29, 30, 28, 26, 27, 25, 24, 30, 31, 32], dtype=float)
    Tn = len(px)
    alive = np.ones((Tn, 2), dtype=bool)
    alive[25:, 1] = False
    pxm = np.column_stack([px, px])
    pxm[~alive] = np.nan
    P = type("P", (), {})()
    P.px, P.alive = pxm, alive
    P.sigma = np.full((Tn, 2), 0.03)
    ex, r = md.exits(P)
    # Coin 0, entered at day 20 (30 above the highest of days 0..19, 29), exits at the first close below
    # the lowest of the previous 10 closes: day 27 closes at 25, under the 26 of days 17..26.
    lo = fc.rolling_extreme(pxm, 10, "min")
    first = next(u for u in range(21, Tn) if px[u] < lo[u, 0])
    assert ex[20, 0] == first == 27
    assert r[20, 0] == pytest.approx(px[27] / px[20] - 1)
    # Coin 1 dies after day 24: a trade entered on day 20 closes at the last close.
    assert ex[20, 1] == 24 and r[20, 1] == pytest.approx(px[24] / px[20] - 1)
    # Entered at the last close: closed at once.
    assert ex[24, 1] == 24 and r[24, 1] == 0.0
    # Coin 0 entered on day 29 is still open at the end: no label.
    assert ex[29, 0] == -1 and np.isnan(r[29, 0])


def test_training_events_do_not_overlap(panel):
    sig = md.signals(panel)
    top = panel.top_liquid(8)
    ex, _ = md.exits(panel)
    ev = md.training_events(sig, top, ex)
    assert ev.sum() > 20
    assert not (ev & ~(sig & top)).any()
    for j in range(N):
        ts = np.flatnonzero(ev[:, j])
        for a, b in zip(ts[:-1], ts[1:]):
            assert ex[a, j] >= 0 and b > ex[a, j]
        # No allowed signal is skipped while the coin is free.
        free = 0
        for t in np.flatnonzero((sig & top)[:, j]):
            if t >= free:
                assert ev[t, j]
                if ex[t, j] < 0:
                    break
                free = ex[t, j] + 1


def test_features_are_point_in_time(panel):
    import copy
    f = md.features(panel)
    assert set(f) == set(md.FEATURES) and len(md.FEATURES) == 21
    cut = 500
    Q = copy.deepcopy(panel)
    rng = np.random.default_rng(1)
    for a in (Q.px, Q.ret, Q.sigma, Q.adv28, Q.funding, Q.extra["rv"], Q.extra["qv"]):
        a[cut + 1:] *= rng.uniform(0.5, 1.5, a[cut + 1:].shape)
    g = md.features(Q)
    for k in md.FEATURES:
        assert np.allclose(f[k][:cut + 1], g[k][:cut + 1], equal_nan=True), k
        if k not in ("m2_score", "m2_rank", "age", "liq_rank"):
            assert not np.allclose(f[k][cut + 1:], g[k][cut + 1:], equal_nan=True), k
    # Funding is missing where there is no perpetual.
    assert np.isnan(f["fund7"][:, 10]).all() and np.isfinite(f["fund7"][100:, 2]).all()


def synthetic_events(seed: int = 0):
    """Days, features and events where the label depends on one feature."""
    rng = np.random.default_rng(seed)
    Tn, Nn = 1400, 30
    P = type("P", (), {})()
    P.days = int(datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp() * 1e6) + np.arange(Tn,
                                                                                         dtype=np.int64) * fc.DAY_US
    f = {k: rng.normal(size=(Tn, Nn)) for k in md.FEATURES}
    ev = rng.random((Tn, Nn)) < 0.05
    hold = rng.integers(1, 40, (Tn, Nn))
    ex = np.where(np.arange(Tn)[:, None] + hold < Tn, np.arange(Tn)[:, None] + hold, -1)
    y = (f["bo_dist"] + rng.normal(0, 0.7, (Tn, Nn)) > 0.2).astype(float)
    return P, f, ev, ex, y


def test_walk_forward_purges_and_learns():
    P, f, ev, ex, y = synthetic_events()
    first = int(datetime(2021, 1, 1, tzinfo=timezone.utc).timestamp() * 1e6)
    meta = md.walk_forward(P, f, ev, ev, ex, y, first=first, log=False)
    assert meta.folds
    starts = md.quarter_starts(P.days, first)
    ex_day = np.where(ex >= 0, P.days[np.maximum(ex, 0)], np.iinfo(np.int64).max)
    for row in meta.folds:
        yq, qq = int(row["fold"][:4]), int(row["fold"][-1])
        s = int(datetime(yq, 3 * qq - 2, 1, tzinfo=timezone.utc).timestamp() * 1e6)
        assert s in starts
        expect = ev & (ex >= 0) & (ex_day <= s - md.EMBARGO_D * fc.DAY_US) & (P.days[:, None] < s)
        assert row["train_events"] == int(expect.sum())
    # Nothing predicted before the first fold, every event after it.
    pre = P.days < first
    assert np.isnan(meta.p[pre]).all()
    assert np.isfinite(meta.p[~pre][ev[~pre]]).all()
    # It learns the planted feature, out of sample, and later folds are calibrated.
    m = ev & np.isfinite(meta.p) & (ex >= 0)
    assert md.auc(meta.raw[m], y[m]) > 0.75
    assert any(r["calibrated"] for r in meta.folds) and not meta.folds[0]["calibrated"]
    assert max(meta.importance, key=meta.importance.get) == "bo_dist"
    assert ((meta.p[m] >= 0) & (meta.p[m] <= 1)).all()


def test_walk_forward_does_not_see_the_future():
    """Labels of events that close after a fold's cutoff cannot change that fold's predictions."""
    P, f, ev, ex, y = synthetic_events(1)
    first = int(datetime(2021, 1, 1, tzinfo=timezone.utc).timestamp() * 1e6)
    a = md.walk_forward(P, f, ev, ev, ex, y, first=first, log=False)
    s = md.quarter_starts(P.days, first)[2]
    ex_day = np.where(ex >= 0, P.days[np.maximum(ex, 0)], np.iinfo(np.int64).max)
    y2 = y.copy()
    late_lab = ex_day > s - md.EMBARGO_D * fc.DAY_US
    y2[late_lab] = 1 - y2[late_lab]
    b = md.walk_forward(P, f, ev, ev, ex, y2, first=first, log=False)
    before = P.days < md.quarter_starts(P.days, first)[3]
    assert np.allclose(a.raw[before], b.raw[before], equal_nan=True)
    assert np.allclose(a.p[before], b.p[before], equal_nan=True)


def test_multipliers():
    p = np.array([[np.nan, 0.2, 0.5, 0.9]])
    meta = md.Meta(p=p, raw=p, pbar=np.full_like(p, 0.4), thr25=np.full_like(p, 0.3), folds=[], importance={})
    assert np.array_equal(md.multipliers(meta, "S1"), [[1, 0, 1, 1]])
    assert np.array_equal(md.multipliers(meta, "S2"), [[1, 0, 1, 1]])
    assert np.allclose(md.multipliers(meta, "Z"), [[1, 0.5, 1.25, 1.5]])


def test_late_fill_shifts_one_row():
    W = np.arange(12, dtype=float).reshape(4, 3)
    L = md.late(W)
    assert np.isnan(L[0]).all() and np.array_equal(L[1:], W[:-1])


def test_auc_and_bootstrap():
    rng = np.random.default_rng(0)
    s = rng.normal(size=500)
    y = (s + rng.normal(size=500) > 0).astype(float)
    assert md.auc(s, y) == pytest.approx(roc_auc_score(y, s))
    lo, hi = md.auc_band(s, y, np.arange(500) // 25, rng, draws=300)
    assert lo < md.auc(s, y) < hi
    x = rng.normal(0.001, 0.02, 400)
    pb = md.paired_boot(x, x, rng, draws=200)
    assert pb["share_above_0"] == 0 and pb["p05"] == pytest.approx(0) and pb["p95"] == pytest.approx(0)
    pb = md.paired_boot(x + 0.003, x, rng, draws=200)
    assert pb["share_above_0"] > 0.9


def test_reliability_bins():
    rng = np.random.default_rng(2)
    p = rng.uniform(size=1000)
    y = (rng.uniform(size=1000) < p).astype(float)
    rel = md.reliability(p, y)
    assert len(rel) == 10 and sum(r["events"] for r in rel) == 1000
    assert rel[-1]["hit_rate"] > rel[0]["hit_rate"]
