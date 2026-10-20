"""X9 model review: the pieces on synthetic data (rules, the penalty replay, IC and ensembles).

No network, no lab data. Run from research/lab:  python -m pytest tests
"""

from __future__ import annotations

import math

import numpy as np
import polars as pl

from lab.experiments import model_review as mr


def test_trailing_median_needs_history_and_uses_only_the_past():
    x = np.arange(400, dtype=float)
    m = mr.trailing(x, "median", w=365, min_obs=180)
    assert np.isnan(m[178]) and m[179] == np.median(x[:180])
    assert m[399] == np.median(x[35:400])


def test_scale_rule_cuts_exposure_when_the_downside_is_above_its_median():
    D = np.r_[np.full(300, 0.02), np.full(10, 0.04), np.full(10, 0.01)]
    S = mr.rule_scale(D)
    assert np.all(S[:179] == 1.0)                 # no history yet
    assert np.allclose(S[300:310], 0.5)           # twice the median: half
    assert np.all(S[310:] == 1.0)                 # calmer than usual: never above 1
    assert np.all(mr.rule_scale(np.full(5, np.nan)) == 1.0)


def test_cap_rule_halves_above_the_80th_percentile_only():
    rng = np.random.default_rng(0)
    D = np.abs(rng.normal(0.02, 0.005, 600))
    D[550] = 1.0
    S = mr.rule_cap(D)
    assert set(np.unique(S)) <= {0.5, 1.0}
    assert S[550] == 0.5
    assert 0.1 < np.mean(S[200:] == 0.5) < 0.3


def test_downside_maps_forecast_days_onto_panel_days():
    day = 86_400_000_000
    days = np.arange(5, dtype=np.int64) * day
    h = pl.DataFrame({"ts_us": [day, day, 3 * day], "symbol": ["A", "B", "A"], "q10": [-0.02, -0.04, -0.05]})
    D = mr.downside(days, h, "q10")
    assert np.isnan(D[0]) and math.isclose(D[1], 0.03) and np.isnan(D[2]) and math.isclose(D[3], 0.05)


def test_nw_t_is_large_for_a_shifted_series_and_small_for_noise():
    rng = np.random.default_rng(1)
    assert abs(mr.nw_t(rng.normal(0, 1, 2000))) < 3
    assert mr.nw_t(rng.normal(0.2, 1, 2000)) > 5


def test_band_low_is_a_low_quantile_that_grows_with_the_horizon():
    rng = np.random.default_rng(2)
    x = rng.normal(0.0005, 0.03, 1200)
    b = mr.band_low(x, np.arange(10, 40), rng, draws=2000)
    assert b[10] < 0 and b[39] < b[10]


def test_penalised_counts_from_the_quarter_start_after_ten_days():
    x = np.r_[np.zeros(5), np.full(40, -0.01)]
    qstart = np.zeros(45, dtype=int)
    band = {h: -0.05 for h in range(10, 93)}
    pen = mr.penalised(x, qstart, band, first=0)
    assert not pen[:9].any()                        # under 10 days: never
    assert not pen[9]                               # 10 days, -4.9 %: inside
    assert pen[15]                                  # 16 days, about -10 %: below


def test_auto_pick_weights_follow_scores_and_the_penalty():
    T = 50
    xs = {b: np.full(T, 0.001) for b in mr.BOOKS}
    expo = {b: np.ones(T) for b in mr.BOOKS}
    pen = {b: np.zeros(T, bool) for b in mr.BOOKS}
    pen["breakout"][20:] = True
    r0, W0 = mr.auto_pick(None, xs, expo, {b: np.zeros(T, bool) for b in mr.BOOKS}, 0.5, 0.0035)
    r1, W1 = mr.auto_pick(None, xs, expo, pen, 0.5, 0.0035)
    assert np.allclose(W0.sum(1), 1) and W0[0, 0] == W0.max()       # breakout scores highest
    assert W1[25, 0] < W0[25, 0]                                    # halved once penalised
    assert r1[21] < r0[21]                                          # the reallocation costs once


def test_daily_ic_and_ensemble():
    rng = np.random.default_rng(3)
    T, N = 30, 60
    a = rng.normal(size=(T, N))
    b = rng.normal(size=(T, N))
    fwd = a + 0.5 * b + rng.normal(size=(T, N))
    mask = np.ones((T, N), bool)
    ic_a = mr.daily_ic(a, fwd, mask)
    ic_e = mr.daily_ic(mr.ensemble([a, b], mask), fwd, mask)
    assert np.nanmean(ic_a) > 0.3 and np.nanmean(ic_e) > np.nanmean(ic_a) - 0.05
    assert mr.bottom_decile(a, fwd, mask, np.ones(T, bool)) < 0


def test_low_mask_ignores_unscored_coins_and_can_lag():
    pct = np.array([[0.1, np.nan, 0.9], [0.5, 0.2, np.nan]])
    assert mr.low_mask(pct).tolist() == [[True, False, False], [False, True, False]]
    assert mr.low_mask(pct, late=1).tolist() == [[False, False, False], [True, False, False]]


def test_static_score_matches_the_engine_formula():
    # Evidence::score with no gates: 1 + min(oos, 2) + 0.5 min(2x cost, 2) + p.
    assert math.isclose(mr.static_score(1.163, 1.045, 0.0095), 1 + 1.163 + 0.5225 + 0.0095)
    assert math.isclose(mr.static_score(-1, -1, 0), 1.0)


def test_shadow_is_off_by_default_and_records_before_it_scores(tmp_path, monkeypatch):
    from lab.paper import m2_lowvol_shadow as sh
    monkeypatch.delenv(sh.ENV, raising=False)
    assert not sh.enabled()
    monkeypatch.setenv(sh.ENV, "1")
    assert sh.enabled()
    rng = np.random.default_rng(4)
    syms = [f"C{i}USDT" for i in range(40)]
    score, vol = rng.normal(size=40), np.abs(rng.normal(0.03, 0.01, 40))
    ranks = sh.rankings(syms, score, vol)
    assert len(ranks) == 40 and all(0 <= a <= 1 and 0 <= b <= 1 for a, b in ranks.values())
    calmest = syms[int(np.argmin(vol))]
    loudest = syms[int(np.argmax(vol))]
    assert ranks[calmest][1] - ranks[calmest][0] > ranks[loudest][1] - ranks[loudest][0]
    day = 1_790_000_000_000_000 // 86_400_000_000 * 86_400_000_000
    sh.record(tmp_path, day, ranks, 1)
    sh.record(tmp_path, day, ranks, 2)                       # the same day is written once
    assert len((tmp_path / "shadow_m2_lowvol.jsonl").read_text().splitlines()) == 1
    assert sh.score(tmp_path, pl.DataFrame({"day": [], "symbol": [], "fwd": []},
                                           schema={"day": pl.Int64, "symbol": pl.Utf8, "fwd": pl.Float64}))["scored_days"] == 0
    fwd = -vol + 0.001 * rng.normal(size=40)                 # calm coins did better
    out = sh.score(tmp_path, pl.DataFrame({"day": [day] * 40, "symbol": syms, "fwd": fwd}))
    assert out["scored_days"] == 1 and out["mean_ic_ensemble"] > out["mean_ic_m2"]


def test_kelly_shrunk_matches_the_engine_estimate():
    # risk.rs: 2 wins of 1 %, 2 losses of 2 % -> p 0.5, b 0.5, raw -0.5, shrunk -0.5 * 4 / 34
    assert math.isclose(mr.kelly_shrunk([0.01, 0.01, -0.02, -0.02]), -0.5 * 4 / 34)
    assert math.isclose(mr.kelly_shrunk([0.01] * 3), 1.0 * 3 / 33)       # nothing lost: f = p
    assert math.isclose(mr.kelly_shrunk([-0.01] * 3), -1.0 * 3 / 33)     # nothing won
    assert math.isnan(mr.kelly_shrunk([]))


class _P:
    def __init__(self, px):
        self.px = px


def test_trim_returns_books_each_sale_against_the_average_entry_minus_fees():
    px = np.array([[100.0], [110.0], [121.0], [121.0]])
    held = np.array([[0.5], [0.6], [0.3], [0.0]])     # buy, top up, trim, exit
    gross = np.zeros(4)
    ev = mr.trim_returns(_P(px), held, gross, 0, 4)
    assert [t for t, _ in ev] == [2, 3]
    assert all(r < px[2, 0] / 100 - 1 for _, r in ev)   # the top-up at 110 raised the average entry
    assert all(r > 0 for _, r in ev)
