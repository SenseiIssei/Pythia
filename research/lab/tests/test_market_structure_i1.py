"""I1's calendar and lead-lag study on synthetic hours: the windows (New York's daylight saving, Deribit's
last Friday, the month turn), returns across gaps, every predictor known at its decision hour (bars after
it changed, nothing at or before it moves), a planted lead found and noise not, the report.

Run from research/lab:  python -m pytest tests/test_market_structure_i1.py
"""

from __future__ import annotations

import math
from datetime import date, datetime, timezone

import numpy as np
import polars as pl

from lab.experiments import market_structure_i1 as ms

UTC = timezone.utc
H = ms.HOUR_US


def us(*a) -> int:
    return int(datetime(*a, tzinfo=UTC).timestamp() * 1e6)


def hours(a: int, b: int) -> np.ndarray:
    return np.arange(a, b, H, dtype=np.int64)


def test_last_friday():
    assert ms.last_friday(2026, 10) == date(2026, 10, 30)
    assert ms.last_friday(2024, 3) == date(2024, 3, 29)
    assert ms.last_friday(2025, 12) == date(2025, 12, 26)
    assert ms.last_friday(2025, 2) == date(2025, 2, 28)


def test_windows_follow_new_york_and_the_expiry():
    g = hours(us(2024, 1, 1), us(2024, 8, 1))
    w = ms.windows(g, fomc={date(2024, 1, 31)}, cpi={date(2024, 1, 11)})
    at = {int(t): i for i, t in enumerate(g)}
    # winter: 09:00 New York is 14:00 UTC; summer 13:00 UTC
    assert w["US cash open"][at[us(2024, 1, 15, 14)]] and w["US cash open"][at[us(2024, 1, 15, 15)]]
    assert not w["US cash open"][at[us(2024, 1, 15, 13)]] and not w["US cash open"][at[us(2024, 1, 15, 16)]]
    assert w["US cash open"][at[us(2024, 7, 15, 13)]] and not w["US cash open"][at[us(2024, 7, 15, 15)]]
    assert not w["US cash open"][at[us(2024, 1, 13, 14)]]  # a Saturday
    assert w["US cash close"][at[us(2024, 1, 15, 20)]] and w["US cash close"][at[us(2024, 1, 15, 21)]]
    assert w["Asian open"][at[us(2024, 1, 15, 0)]] and not w["Asian open"][at[us(2024, 1, 14, 0)]]
    # the expiry on 2024-01-26 08:00 UTC: 24 hours before it, 24 after
    e = us(2024, 1, 26, 8)
    assert w["expiry 24h before"][at[e - H]] and w["expiry 24h before"][at[e - 24 * H]]
    assert not w["expiry 24h before"][at[e]] and not w["expiry 24h before"][at[e - 25 * H]]
    assert w["expiry 24h after"][at[e]] and w["expiry 24h after"][at[e + 23 * H]]
    assert not w["expiry 24h after"][at[e + 24 * H]]
    jan = (g >= us(2024, 1, 1)) & (g < us(2024, 2, 1))
    assert w["expiry 24h before"][jan].sum() == 24 and w["expiry 24h after"][jan].sum() == 24
    assert w["turn of month"][at[us(2024, 1, 31, 5)]] and w["turn of month"][at[us(2024, 2, 3, 23)]]
    assert not w["turn of month"][at[us(2024, 2, 4, 0)]]
    # FOMC on a New York day, the statement hours 14:00 and 15:00 New York (19:00 and 20:00 UTC in winter)
    assert w["FOMC day"].sum() == 24
    assert w["FOMC 14-16 NY"][at[us(2024, 1, 31, 19)]] and w["FOMC 14-16 NY"][at[us(2024, 1, 31, 20)]]
    assert w["FOMC 14-16 NY"].sum() == 2 and w["CPI 08-10 NY"].sum() == 2
    assert w["CPI 08-10 NY"][at[us(2024, 1, 11, 13)]]
    assert w["weekday Mon"][at[us(2024, 1, 15, 3)]] and w["weekend"][at[us(2024, 1, 13, 3)]]
    assert len(w) == 44


def test_returns_across_a_gap_and_forward_sums():
    g = hours(us(2024, 1, 1), us(2024, 1, 1, 6))
    open_us = np.array([g[0], g[1], g[2], g[4], g[5]])
    close = np.array([100.0, 101.0, 102.0, 104.0, 103.0])
    r = ms.grid_returns(open_us, close, g)
    assert math.isnan(r[0]) and math.isnan(r[3]) and math.isnan(r[4])
    assert r[1] == math.log(101 / 100) and r[5] == math.log(103 / 104)
    f = ms.fwd(np.array([1.0, 2.0, np.nan, 4.0, 5.0]), 2)
    assert f[0] == 3.0 and math.isnan(f[1]) and math.isnan(f[2]) and f[3] == 9.0 and math.isnan(f[4])


def test_occurrences_are_runs():
    m = np.array([0, 1, 1, 0, 1, 0, 1, 1, 1], dtype=bool)
    r = np.array([0, 1, 2, 0, 5, 0, np.nan, np.nan, 3.0])
    st, s = ms.occurrences(r, m)
    assert st.tolist() == [1, 4, 6]
    assert s[0] == 3 and s[1] == 5 and math.isnan(s[2])


def test_predictors_known_at_the_decision_hour():
    """Change everything that becomes known after T: nothing at or before T may move."""
    rng = np.random.default_rng(3)
    g = hours(us(2024, 3, 1), us(2024, 3, 11))
    T = g[120]
    idx = pl.DataFrame({"open_time_us": g[::2] + H // 2, "open": 100 + rng.random(len(g[::2])),
                        "close": 100 + rng.random(len(g[::2]))})
    fund = pl.DataFrame({"funding_time_us": g[::8], "funding_rate": rng.normal(0, 1e-4, len(g[::8]))})
    oi = pl.DataFrame({"ts_us": g, "oi_usd": 1e9 * (1 + rng.random(len(g)))})
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, len(g))))
    base = {"index": ms.index_lead(idx, g), "funding": ms.funding_lead(fund, g),
            "oi1": ms.oi_change(oi, g, 1), "oi4": ms.oi_change(oi, g, 4),
            "btc": ms.lag(ms.grid_returns(g, close, g))}
    late = lambda c, k: pl.col(c) + k  # noqa: E731
    idx2 = idx.with_columns(pl.when(pl.col("open_time_us") + H > T).then(late("close", 50.0))
                            .otherwise(pl.col("close")).alias("close"))
    fund2 = fund.with_columns(pl.when(pl.col("funding_time_us") > T).then(late("funding_rate", 0.01))
                              .otherwise(pl.col("funding_rate")).alias("funding_rate"))
    oi2 = oi.with_columns(pl.when(pl.col("ts_us") + H > T).then(late("oi_usd", 5e8))
                          .otherwise(pl.col("oi_usd")).alias("oi_usd"))
    c2 = np.where(g + H > T, close * 1.5, close)  # every bar closing after T
    moved = {"index": ms.index_lead(idx2, g), "funding": ms.funding_lead(fund2, g),
             "oi1": ms.oi_change(oi2, g, 1), "oi4": ms.oi_change(oi2, g, 4),
             "btc": ms.lag(ms.grid_returns(g, c2, g))}
    k = int(np.flatnonzero(g == T)[0])
    for name in base:
        a, b = base[name][:k + 1], moved[name][:k + 1]
        assert np.isfinite(a).sum() > 20, name
        assert np.array_equal(a, b, equal_nan=True), name
        assert not np.array_equal(base[name], moved[name], equal_nan=True), name  # the change did reach later hours


def test_index_bar_is_used_half_an_hour_after_it_ends_and_not_older_than_an_hour():
    g = hours(us(2024, 3, 4, 13), us(2024, 3, 4, 20))
    bars = pl.DataFrame({"open_time_us": [us(2024, 3, 4, 14, 30)], "open": [100.0], "close": [101.0]})
    x = ms.index_lead(bars, g)
    at = {int(t): i for i, t in enumerate(g)}
    assert math.isnan(x[at[us(2024, 3, 4, 15)]])  # the bar ends 15:30
    assert x[at[us(2024, 3, 4, 16)]] == math.log(1.01)
    assert math.isnan(x[at[us(2024, 3, 4, 17)]])


def test_planted_lead_passes_and_noise_does_not():
    rng = np.random.default_rng(7)
    g = hours(us(2023, 1, 1), us(2025, 1, 1))
    n = len(g)
    btc = rng.normal(0, 0.01, n)
    rets = {"BTC": btc, "ETH": btc + 0.8 * ms.lag(btc) + rng.normal(0, 0.002, n)}
    for c in ("SOL", "XRP", "DOGE"):
        rets[c] = rng.normal(0, 0.01, n)
    tests = ms.run_tests(g, rets, set(), set(), {}, {}, {})
    assert len({t["test"] for t in tests if t["family"] == "calendar"}) == 40  # no FOMC or CPI day given
    lead = [t for t in tests if t["family"] == "BTC leads alts" and t["asset"] == "ETH" and t["h"] == 1]
    assert lead and lead[0]["passed"] and lead[0]["ic"] > 0.5 and lead[0]["hold_trade_bps"] > 60
    noise = [t for t in tests if t["family"] == "calendar" or t["asset"] in ("SOL", "XRP", "DOGE")]
    assert noise and not any(t["passed"] for t in noise)
    assert all(t["cost_bps"] == 60 for t in tests if t["family"] == "BTC leads alts")
    out = {"generated": "x", "window": ["2023-01-01", "2024-12-31"], "hours": n, "index_bars": {}, "tests": tests}
    md = ms.tables(out)
    assert md.startswith(ms.MARKER) and "| calendar |" in md and "\u2014" not in md


def test_holm_counts_every_test():
    rng = np.random.default_rng(1)
    g = hours(us(2023, 6, 1), us(2024, 6, 1))
    rets = {"BTC": rng.normal(0, 0.01, len(g)), "ETH": rng.normal(0, 0.01, len(g))}
    tests = ms.run_tests(g, rets, set(), set(), {}, {}, {})
    m = len(tests)
    best = min(tests, key=lambda t: t["p"])
    assert math.isclose(best["p_holm"], min(1.0, best["p"] * m))
