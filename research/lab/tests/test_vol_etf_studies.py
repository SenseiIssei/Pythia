"""The five studies registered on 2026-10-21: helpers that decide numbers, on synthetic data."""

from __future__ import annotations

import math
from datetime import date

import numpy as np
import polars as pl

from lab.experiments import btc_vrp as vrp
from lab.experiments import crypto_open_gap as og
from lab.experiments import treasury_premium as tp
from lab.experiments import vix_carry as vx
from lab.experiments import vol_etf_common as vc


def test_new_york_offset_follows_us_daylight_saving():
    assert vc.ny_offset_h(date(2024, 1, 5)) == 5
    assert vc.ny_offset_h(date(2024, 7, 5)) == 4
    assert vc.ny_offset_h(date(2024, 3, 9)) == 5 and vc.ny_offset_h(date(2024, 3, 10)) == 4
    assert vc.ny_offset_h(date(2024, 11, 2)) == 4 and vc.ny_offset_h(date(2024, 11, 3)) == 5
    assert vc.ny_offset_h(date(2006, 10, 28)) == 4 and vc.ny_offset_h(date(2006, 10, 29)) == 5
    # 16:00 New York on a winter day is 21:00 UTC
    assert vc.ny_us(date(2024, 1, 5), 16, 0) % vc.DAY_US == 21 * 3600 * 1_000_000


def test_pool_counts_the_batch():
    assert vc.HAND_TRIALS + 600 == 1740
    assert vc.BATCH_TRIALS == 8 + 4 + 2 + 2 + 6


def test_vx_expiry_is_a_wednesday_30_days_before_the_next_third_friday():
    e = vx.vx_expiry(2018, 2)
    assert e == date(2018, 2, 14) and e.weekday() == 2
    assert vx.vx_expiry(2020, 3) == date(2020, 3, 18)


def test_rebuilt_index_rolls_from_first_to_second_month():
    cal = np.arange(np.datetime64("2020-01-01"), np.datetime64("2020-06-30")).astype("datetime64[D]")
    cal = cal[np.is_busday(cal)]
    exps = [vx.vx_expiry(2020, m) for m in range(1, 8)]
    flat = {e: pl.DataFrame({"date": [date.fromisoformat(str(d)) for d in cal],
                             "price": [20.0 + i] * len(cal)}) for i, e in enumerate(exps)}
    r = vx.rebuild_index(flat, cal)
    ok = np.isfinite(r)
    assert ok.sum() > 50
    assert np.allclose(r[ok], 0.0)          # flat prices: no return, whatever the weights
    # a 10 % jump in every contract on one day is a 10 % index return that day
    jump = cal[60]
    up = {e: df.with_columns(price=pl.when(pl.col("date") >= date.fromisoformat(str(jump)))
                             .then(pl.col("price") * 1.1).otherwise(pl.col("price"))) for e, df in flat.items()}
    r2 = vx.rebuild_index(up, cal)
    assert abs(r2[60] - 0.10) < 1e-9


def test_vix_simulate_holds_from_the_next_close_and_charges_turnover():
    r = np.array([0.0, 0.10, 0.10, 0.10, 0.10])
    tgt = np.array([1.0, 1.0, 1.0, 1.0, 1.0])
    net, tov = vx.simulate(tgt, r, 1, 0.001)
    assert net[1] == -0.001 and tov[1] == 1.0       # bought at the close of day 1
    assert abs(net[2] - 0.10) < 1e-12               # earns from day 2
    late, _ = vx.simulate(tgt, r, 2, 0.0)
    assert late[2] == 0.0 and abs(late[3] - 0.10) < 1e-12


def test_covered_call_equals_cash_secured_put_at_the_money():
    S, K, tau, sig = 100.0, 100.0, 30 / 365, 0.6
    c, p = vrp.bs(S, K, tau, sig, True), vrp.bs(S, K, tau, sig, False)
    assert abs((c - p) - (S - K)) < 1e-9            # put-call parity at zero rates
    assert vrp.bs(90, 100, 0, 0.5, False) == 10


def test_ols_hc1_recovers_a_slope():
    rng = np.random.default_rng(1)
    x = rng.normal(size=2000)
    y = 0.5 * x + rng.normal(scale=0.1, size=2000)
    a, b, t = og.ols_hc1(x, y)
    assert abs(b - 0.5) < 0.02 and t > 50


def test_open_gap_rule_trades_only_above_the_round_trip():
    m = np.array([0.0005, 0.002, -0.003, np.nan])
    s = np.array([0.01, 0.01, -0.01, 0.01])
    r, pos = og.rule(m, s, 0.0005)
    assert list(pos) == [0.0, 1.0, -1.0, 0.0]
    assert abs(r[1] - (0.01 - 0.001)) < 1e-12
    assert abs(r[2] - (0.01 - 0.001 - og.BORROW)) < 1e-12


def test_treasury_coverage_needs_fresh_figures():
    pts = [(date(2024, 1, 1) + (date(2024, 1, 8) - date(2024, 1, 1)) * i,) * 2 for i in range(200)]
    assert tp.coverage(pts) > 0.99
    assert tp.coverage([(date(2023, 12, 31), date(2026, 2, 19))]) == 0.0


def test_boot_band_of_a_difference_with_itself_is_zero():
    x = np.random.default_rng(3).normal(0.001, 0.01, 400)
    lo, hi, _ = vc.boot_band(x, 365, x)
    assert lo == 0 and hi == 0
    assert math.isclose(vc.max_dd(np.array([0.1, -0.5, 0.2])), 0.5)
