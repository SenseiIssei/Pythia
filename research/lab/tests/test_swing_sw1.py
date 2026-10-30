"""SW1, swing rules on the rug-free universe at Hyperliquid's costs: the 1-hour variance, the panel, the hold grid,
the account (the 10 USD minimum, the position cap, leverage, funding, late fills, forced closes) and the trials.
Synthetic data only, no lab data.

Run from research/lab:  python -m pytest tests/test_swing_sw1.py
"""

from __future__ import annotations

import math

import numpy as np
import polars as pl
import pytest

from lab import leak
from lab.experiments import daytrade_dt1 as dt
from lab.experiments import swing_sw1 as sw

D0 = dt.dnum("2023-01-01")
B = 240                                     # warm-up rows before every test's own rows (rolling windows, 200-day MA)


def pad(c: np.ndarray) -> np.ndarray:
    """B rows of the first row's prices before c."""
    return np.vstack([np.repeat(c[:1], B, 0), c])


def daily(c: np.ndarray, names: list[str] | None = None, qv: float = 1e8) -> dt.Daily:
    """A Daily of closes c (T, M), open = previous close, high and low 1 % around, listed from the first row."""
    T, M = c.shape
    o = np.where(np.isfinite(c), np.vstack([c[:1], c[:-1]]), np.nan)
    names = names or (["BTCUSDT"] + [f"C{k}USDT" for k in range(1, M)])
    listed = np.where(np.isfinite(c), np.arange(T)[:, None] + 400, -1)
    return dt.Daily(D0, names, o, np.maximum(o, c) * 1.01, np.minimum(o, c) * 0.99, c, np.full((T, M), qv), listed)


def panel(c: np.ndarray, member: np.ndarray | None = None, sigma: float = 0.03) -> tuple[dt.Daily, object]:
    Dy = daily(c)
    member = np.ones(c.shape, dtype=bool) if member is None else member
    rv = np.full(c.shape, sigma ** 2)
    return Dy, sw.make_panel(Dy, np.arange(c.shape[1]), member, rv)


def market(c: np.ndarray, fund: float = 0.0, listed: np.ndarray | None = None):
    """The market of c after B warm-up rows: a test's row r is row B + r."""
    c = pad(c)
    listed = None if listed is None else np.vstack([np.ones((B, c.shape[1]), dtype=bool), listed])
    Dy, P = panel(c)
    cols = np.arange(c.shape[1])
    top = np.ones(c.shape, dtype=bool)
    return sw.make_market(P, Dy, cols, listed, np.full(c.shape, fund), top)


# ---------------------------------------------------------------- names, months, trials

def test_bases_drop_binances_multipliers():
    assert sw.base_of("1000PEPEUSDT") == "PEPE"
    assert sw.base_of("1000BONKUSDT") == "BONK"
    assert sw.base_of("1000000MOGUSDT") == "MOG"
    assert sw.base_of("1INCHUSDT") == "1INCH"
    assert sw.base_of("BTCUSDT") == "BTC"


def test_trials_are_222_unique_small_ids_with_the_prereg():
    assert len(sw.rules()) == 37
    T = sw.trials({})
    assert len(T) == 222 == len({t["id"] for t in T})
    assert all(t["family"] == "small" and t["source"] == sw.PREREG and t["id"].startswith("small:sw1:") for t in T)


def test_needed_months_take_two_months_before_and_stop_before_the_lockbox():
    c = np.full((dt.dnum("2026-12-31") - D0 + 1, 1), 100.0)
    Dy = daily(c)
    Q = np.zeros(c.shape, dtype=bool)
    Q[dt.dnum("2024-03-10") - D0, 0] = True
    Q[dt.dnum("2026-09-01") - D0, 0] = True
    plan = sw.needed_months(Dy, Q)
    assert plan == {"BTCUSDT": ["2024-01", "2024-02", "2024-03"]}


def test_hourly_variance_sums_squared_log_returns_and_skips_gaps():
    t0 = D0 * dt.DAY_MIN
    t = t0 + 60 * np.arange(48)
    c = 100 * np.exp(np.cumsum(np.r_[0.0, np.full(47, 0.01)]))
    h = pl.DataFrame({"t": t, "c": c.astype(np.float32), "qv": np.ones(48, dtype=np.float32)})
    g = sw.hourly_daily(h)
    assert g["day"].to_list() == [D0, D0 + 1]
    assert g["rv"][0] == pytest.approx(23 * 1e-4, rel=1e-3)        # the first hour has no return before it
    assert g["rv"][1] == pytest.approx(24 * 1e-4, rel=1e-3)
    gap = h.filter(pl.col("t") != t[30])                              # a missing hour: the hour after it has none
    assert sw.hourly_daily(gap)["rv"][1] == pytest.approx(22 * 1e-4, rel=1e-3)
    short = h.filter(pl.col("t") < t[30])                             # 6 hours on day 2: no variance that day
    assert sw.hourly_daily(short)["day"].to_list() == [D0]


# ---------------------------------------------------------------- the panel and the rules

def test_panel_sigma_is_the_30_day_mean_of_the_daily_variance_and_eligible_is_the_universe():
    c = np.full((260, 2), 100.0)
    member = np.zeros(c.shape, dtype=bool)
    member[240:, 1] = True
    _, P = panel(c, member, sigma=0.02)
    assert np.isnan(P.sigma[18, 0]) and P.sigma[19, 0] == pytest.approx(0.02)
    assert not P.eligible[:240, 1].any() and P.eligible[240:, 1].all() and not P.eligible[:, 0].any()
    assert P.bases == ["BTC", "C1"]


def test_h_breakout_time_stop_and_no_reentry_until_a_new_breakout():
    T = 80
    p = np.full(T, 100.0)
    p[40:] = 100 + np.arange(T - 40) + 1                              # breaks out on row 40, keeps rising
    c = pad(np.c_[np.full(T, 100.0), p])
    _, P = panel(c, sigma=0.02)
    W, k = sw.rule_weights(P, "H:N10:D5:K5")
    assert k == 5
    w = W[B:, 1]
    assert np.isnan(w[39]) and w[40] == pytest.approx(min(0.40 / (0.02 * math.sqrt(365)), 1.0))
    assert np.isnan(w[41:45]).all() and w[45] == 0.0                  # out after 5 days held
    assert (np.isnan(w[46:]) | (w[46:] == 0)).all()                   # still above the channel: blocked
    p2 = p.copy()
    p2[50] = 50.0                                                     # a close under the channel unblocks
    _, P2 = panel(pad(np.c_[np.full(T, 100.0), p2]), sigma=0.02)
    w2 = sw.rule_weights(P2, "H:N10:D5:K5")[0][B:, 1]
    assert np.nanmax(w2[51:]) > 0


def test_h_exits_at_the_opposite_channel():
    T = 60
    p = np.full(T, 100.0)
    p[30:33] = [110, 111, 112]
    p[33:] = 90.0
    _, P = panel(pad(np.c_[np.full(T, 100.0), p]), sigma=0.02)
    w = sw.rule_weights(P, "H:N10:D20:K5")[0][B:, 1]
    assert w[30] > 0 and w[33] == 0.0


def test_r_rules_run_on_the_panel():
    rng = np.random.default_rng(3)
    T = 320
    c = 100 * np.exp(np.cumsum(rng.normal(0.002, 0.03, (T, 4)), 0))
    Dy = daily(c, ["BTCUSDT", "ETHUSDT", "SOLUSDT", "1000BONKUSDT"])
    P = sw.make_panel(Dy, np.arange(4), np.ones(c.shape, dtype=bool), np.full(c.shape, 9e-4))
    for r in sw.R_RULES:
        W, k = sw.rule_weights(P, r)
        assert W.shape == (T, 4) and k is None
        assert np.nanmax(np.abs(np.nan_to_num(W))) <= 1.0 + 1e-9
    W = sw.rule_weights(P, "breakout_sol10")[0]
    assert np.nanmax(np.nan_to_num(W[:, 3])) > 0                      # 1000BONK has a Solana mint
    assert np.nanmin(np.nan_to_num(sw.rule_weights(P, "tsmom_top20_ls")[0])) <= 0


def test_h_weights_pass_the_leak_harness():
    rng = np.random.default_rng(5)
    T = 300
    c0 = 100 * np.exp(np.cumsum(rng.normal(0.003, 0.03, (T, 3)), 0))
    data = {"days": np.arange(T), "c": c0}

    def fn(X):
        c = np.where(np.isfinite(X["c"]), X["c"], 100.0)
        _, P = panel(c, sigma=0.03)
        return {"w": sw.rule_weights(P, "H:N10:D10:K5")[0]}
    res = leak.check(fn, data, cuts=[150, 220, 280], kinds=("shuffle", "nan"), recursive=False, name="sw1")
    assert res["ok"], res


# ---------------------------------------------------------------- the account

def one_entry(T: int = 10, w: float = 1.0, row: int = 2, coin: int = 1, M: int = 2) -> np.ndarray:
    W = np.full((B + T, M), np.nan)
    W[0] = 0.0
    W[B + row, coin] = w
    return W


def run(M, W, t0, t1, capital, slots=None, late=False) -> dict:
    return sw.simulate(M, W, B + t0, B + t1, capital, slots, late)


def test_ideal_account_earns_open_to_open_after_the_fee():
    c = np.c_[np.full(10, 100.0), 100 * 1.01 ** np.arange(10)]
    M = market(c)
    r = run(M, one_entry(), 1, 8, None)
    x = r["ret"]                                                      # rows 1..8
    assert x[0] == 0 and x[1] == 0                                     # decided at the close of row 2
    cost = sw.FEE + sw.SLIP_TOP
    assert x[2] == pytest.approx(0.01 - cost, abs=1e-9)                # bought at the open of row 3
    assert x[3] == pytest.approx(1.01 * 0.01 / (1.01 - cost), rel=1e-9)  # the position drifted with the price
    assert r["entries"] == 1 and r["sent"] == 1 and r["orders"] == 1


def test_late_fill_is_one_open_later():
    c = np.c_[np.full(10, 100.0), 100 * 1.01 ** np.arange(10)]
    M = market(c)
    on, late = run(M, one_entry(), 1, 8, None)["ret"], run(M, one_entry(), 1, 8, None, late=True)["ret"]
    assert late[2] == 0 and late[3] == pytest.approx(on[2])


def test_the_minimum_skips_small_entries_and_the_position_cap_binds():
    c = np.full((10, 4), 100.0)
    M = market(c)
    W = np.full((B + 10, 4), np.nan)
    W[0] = 0.0
    W[B + 2, 1:] = 0.15                                                    # 8.55 USD each at 57 USD: under 10
    r = run(M, W, 1, 8, 57.0)
    assert r["entries"] == 3 and r["sent"] == 0 and r["skip_min"] == 3 and r["orders"] == 0
    r = run(M, W, 1, 8, None)
    assert r["sent"] == 3 and r["skip_min"] == 0


def test_the_position_cap_binds_after_a_loss():
    c = np.full((12, 7), 100.0)
    c[5:, 1:6] = 50.0                                                  # the five positions halve
    M = market(c)
    W = np.full((B + 12, 7), np.nan)
    W[0] = 0.0
    W[B + 2, 1:6] = 0.2                                                # 11.4 USD each at 57 USD
    W[B + 7, 1] = 0.0                                                  # one goes: 4 open, room for 2 at 28 USD
    W[B + 7, 6] = 0.5                                                  # 0.5 / 1.3 of 28 USD is above 10 USD
    r = run(M, W, 1, 10, 57.0)
    assert r["sent"] == 5 and r["skip_cap"] == 1 and r["skip_min"] == 0
    assert run(M, W, 1, 10, None)["sent"] == 6


def test_h_slots_shrink_to_what_the_minimum_allows():
    c = np.full((10, 2), 100.0)
    M = market(c)
    W = one_entry(w=1.0)
    r = run(M, W, 1, 8, 57.0, slots=20)                        # 57 / min(20, 5) = 11.4 USD
    assert r["sent"] == 1 and r["costs"] == pytest.approx(11.4 * (sw.FEE + sw.SLIP_TOP))
    r = run(M, W, 1, 8, None, slots=20)
    assert r["costs"] == pytest.approx(0.05 * (sw.FEE + sw.SLIP_TOP))


def test_gross_is_capped_at_the_equity():
    c = np.full((10, 3), 100.0)
    M = market(c)
    W = np.full((B + 10, 3), np.nan)
    W[0] = 0.0
    W[B + 2, 1], W[B + 2, 2] = 1.0, -0.5
    r = run(M, W, 1, 8, None)
    assert r["traded"] == pytest.approx(1.0)


def test_a_small_resize_is_not_sent_but_a_full_close_is():
    c = np.full((12, 2), 100.0)
    M = market(c)
    W = one_entry(T=12, w=0.5)
    W[B + 4, 1] = 0.45                                                 # 2.85 USD less at 57 USD
    W[B + 6, 1] = 0.0
    r = run(M, W, 1, 10, 57.0)
    assert r["resize_skipped"] >= 1 and r["orders"] == 2


def test_funding_a_long_pays_a_positive_rate():
    c = np.full((10, 2), 100.0)
    r = run(market(c, fund=1e-3), one_entry(), 1, 8, None)
    assert r["ret"][3] == pytest.approx(-1e-3, rel=1e-2)
    W = one_entry(w=-1.0)
    assert run(market(c, fund=1e-3), W, 1, 8, None)["ret"][3] == pytest.approx(1e-3, rel=1e-2)


def test_a_coin_the_venue_stops_listing_is_closed_and_not_reopened():
    c = np.full((12, 2), 100.0)
    listed = np.ones(c.shape, dtype=bool)
    listed[6:, 1] = False
    r = run(market(c, listed=listed), one_entry(T=12), 1, 10, None)
    assert r["forced"] == 1 and r["orders"] == 1
    W = one_entry(T=12, row=7)                                         # an entry while not listed is never sent
    r = run(market(c, listed=listed), W, 1, 10, None)
    assert r["sent"] == 0 and r["orders"] == 0


def test_a_coins_last_bar_closes_it_at_its_close():
    c = np.c_[np.full(10, 100.0), np.r_[np.full(6, 100.0), 110.0, np.full(3, np.nan)]]
    r = run(market(c), one_entry(), 1, 8, None)
    assert r["forced"] == 1
    cost = sw.FEE + sw.SLIP_TOP
    assert r["ret"][5] == pytest.approx((0.10 - 1.1 * cost) / (1 - cost), rel=1e-9)


def test_the_account_starts_where_the_rule_stands():
    c = np.full((12, 2), 100.0)
    W = one_entry(T=12, row=2)
    r = run(market(c), W, 5, 10, None)                         # the entry was decided before the window
    assert r["entries"] == 1 and r["sent"] == 1


# ---------------------------------------------------------------- the numbers

def test_drawdown_cagr_and_the_bootstrap():
    x = np.array([0.1, -0.5, 0.2])
    assert sw.max_dd(x) == pytest.approx(0.5)
    assert sw.max_dd(np.array([-0.2, 0.1])) == pytest.approx(0.2)
    assert sw.cagr(np.zeros(365)) == pytest.approx(0.0)
    from lab import metrics
    idx = metrics.stationary_bootstrap(200, 500, 10, 7)
    assert sw.boot_q05(np.full(200, 1e-3), idx) == pytest.approx(1e-3)
