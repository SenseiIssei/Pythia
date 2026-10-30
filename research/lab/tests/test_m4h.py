"""M4H, reg7n at a small Hyperliquid account: the buffer's targets, the liquid and listed set, size rounding, the
10 USD minimum, fees, slippage, funding, late fills, the listing and funding windows, the spread proxy, the numbers
and the trials. Synthetic data only, no lab data.

Run from research/lab:  python -m pytest tests/test_m4h.py
"""

from __future__ import annotations

import math

import numpy as np
import polars as pl
import pytest

from lab.experiments import daytrade_dt1 as dt
from lab.experiments import m4h

D0 = dt.us("2024-01-01")
DAY = m4h.DAY_US


def world(T: int = 5, N: int = 30, r: float = 0.0, px: float = 1.0, fund: float = 0.0) -> dict:
    """N coins, score descending with the column (column 0 best), equal liquidity descending, price px, return r."""
    score = np.tile(-np.arange(N, dtype=float), (T, 1))
    liq = np.tile(1e9 - np.arange(N, dtype=float), (T, 1))
    R = np.full((T, N), r)
    P = np.full((T, N), px)
    F = np.full((T, N), fund)
    return {"days": D0 + np.arange(T) * DAY, "score": score, "liq": liq, "R": R, "R2": R.copy(), "P": P,
            "P2": P.copy(), "F": F, "F2": F.copy(), "Fb": np.zeros((T, N)), "slip": np.zeros((T, N)),
            "dec": [None] * N, "mult": np.ones(N)}


# ---------------------------------------------------------------- the book

def test_targets_enter_at_half_over_k_scaled_by_gross():
    w = np.zeros(30)
    idx = np.arange(30)
    t = m4h.targets(w, -np.arange(30, dtype=float), idx, 5, 1)
    assert np.allclose(t[:5], 0.1) and np.allclose(t[-5:], -0.1) and np.all(t[5:25] == 0)
    t2 = m4h.targets(w, -np.arange(30, dtype=float), idx, 5, 2)
    assert np.allclose(t2, 2 * t)


def test_targets_keep_held_names_inside_the_buffer_and_cut_them_back():
    score = -np.arange(30, dtype=float)
    w = np.zeros(30)
    w[12] = 0.35                                 # held long, rank 13 of 30: inside the best half, above the cap 0.2
    w[20] = -0.05                                # held short, rank 21: inside the worst half (15)
    t = m4h.targets(w, score, np.arange(30), 5, 1)
    assert t[12] == pytest.approx(0.2)           # cut back to gross / k
    assert t[20] == pytest.approx(-0.05)         # drifted weight kept
    assert (t > 0).sum() == 5 and (t < 0).sum() == 5
    w[12] = 0.05
    t = m4h.targets(w, np.r_[score[:12], -100.0, score[13:]], np.arange(30), 5, 1)
    assert t[12] < 0 or t[12] == 0               # dropped out of the best half: no longer long


def test_targets_hold_nothing_with_fewer_than_2k_names():
    assert not m4h.targets(np.zeros(30), -np.arange(30, dtype=float), np.arange(9), 5, 1).any()


def test_liquid_cuts_to_the_most_liquid_then_to_the_listed():
    score = np.r_[np.arange(150, dtype=float), np.nan]
    liq = np.r_[np.arange(150, dtype=float), 1e12]           # the most liquid has no score
    idx = m4h.liquid(score, liq, None)
    assert len(idx) == m4h.N_LIQUID and set(idx) == set(range(50, 150))
    listed = np.zeros(151, dtype=bool)
    listed[[10, 60, 70]] = True
    assert set(m4h.liquid(score, liq, listed)) == {60, 70}  # 10 is not among the 100 most liquid


# ---------------------------------------------------------------- Hyperliquid's sizes

def test_round_size_uses_the_coins_decimals():
    assert m4h.round_size(11.5, 60_000.0, 5) == pytest.approx(round(11.5 / 60_000, 5) * 60_000)
    assert m4h.round_size(11.5, 3.0, 0) == pytest.approx(12.0)
    assert m4h.round_size(11.5, 30.0, 0) == 0.0
    assert m4h.round_size(11.5, 3.0, None) == 11.5
    assert m4h.round_size(11.5, float("nan"), 2) == 11.5


def test_unit_mult_reads_k_coins_as_a_thousand():
    assert m4h.unit_mult("kPEPE") == 1000.0
    assert m4h.unit_mult("BTC") == 1.0 and m4h.unit_mult(None) == 1.0


# ---------------------------------------------------------------- the account

def test_minimum_skips_every_entry_under_10_usd():
    X = world()
    r = m4h.simulate(X, 0, 4, 10, 1, 115.0, 0.0, "base", None)           # 0.05 x 115 = 5.75 USD an entry
    assert r["sent"] == 0 and r["wanted"] == 20 * 5 and r["skip_min"] == r["wanted"]
    assert np.all(r["ret"] == 0) and r["end"] == 115.0
    r = m4h.simulate(X, 0, 4, 10, 1, 230.0, 0.0, "base", None)           # 11.5 USD
    assert r["sent"] == 20 and r["skip_min"] == 0


def test_the_ideal_account_has_no_minimum():
    r = m4h.simulate(world(), 0, 4, 10, 1, None, 0.0, "base", None)
    assert r["sent"] == 20 and r["end"] == pytest.approx(1.0)


def test_rounding_to_zero_counts_as_skipped():
    X = world(px=100.0)
    X["dec"] = [0] * 30                                                    # 11.5 USD at 100 USD a unit: 0 units
    r = m4h.simulate(X, 0, 2, 10, 1, 230.0, 0.0, "base", None)
    assert r["sent"] == 0 and r["skip_min"] == r["wanted"]


def test_fees_slippage_and_funding_are_charged():
    X = world(fund=0.001)
    X["slip"][:] = 0.0002
    r = m4h.simulate(X, 0, 0, 5, 1, None, 4.5e-4, "base", None)
    # gross 1 traded once: 4.5 + 2 bps; longs and shorts pay and receive the same funding: net 0
    assert r["fees"] == pytest.approx(4.5e-4) and r["slip"] == pytest.approx(2e-4)
    assert r["funding"] == pytest.approx(0.0)
    assert r["ret"][0] == pytest.approx(-6.5e-4)
    X["F"][:, 25:] = 0.0                                                    # only the longs' funding: they pay
    r = m4h.simulate(X, 0, 0, 5, 1, None, 0.0, "base", None, slip=False)
    assert r["funding"] == pytest.approx(0.5 * 0.001) and r["ret"][0] == pytest.approx(-0.0005)
    assert r["fund"][0] == pytest.approx(0.0005)


def test_missing_hyperliquid_funding_falls_back_to_binance():
    X = world()
    X["F"][:] = np.nan
    X["Fb"][:, :5] = 0.002
    r = m4h.simulate(X, 0, 0, 5, 1, None, 0.0, "base", None)
    assert r["funding"] == pytest.approx(0.5 * 0.002)


def test_late_fill_uses_the_late_returns_and_funding():
    X = world()
    X["R2"][:, :5] = 0.01                                                   # longs gain one hour later only
    assert m4h.simulate(X, 0, 0, 5, 1, None, 0.0, "base", None)["ret"][0] == pytest.approx(0.0)
    assert m4h.simulate(X, 0, 0, 5, 1, None, 0.0, "late", None)["ret"][0] == pytest.approx(0.005)


def test_returns_and_gross_two():
    X = world()
    X["R"][:, :5] = 0.02
    X["R"][:, 25:] = -0.02
    assert m4h.simulate(X, 0, 0, 5, 1, None, 0.0, "base", None)["ret"][0] == pytest.approx(0.02)
    assert m4h.simulate(X, 0, 0, 5, 2, None, 0.0, "base", None)["ret"][0] == pytest.approx(0.04)


def test_an_unlisted_held_coin_is_closed_and_full_closes_ignore_the_minimum():
    X = world()
    listed = np.ones((5, 30), dtype=bool)
    listed[1:, 0] = False
    r = m4h.simulate(X, 0, 1, 10, 1, 230.0, 0.0, "base", listed, keep_weights=True)
    assert r["W"][0, 0] > 0 and r["W"][1, 0] == 0                          # an 11.5 USD close is sent


def test_small_cut_backs_are_skipped_at_an_account_not_at_the_ideal():
    X = world()
    X["R"][0, 0] = 1.2                                                      # the best long more than doubles
    a = m4h.simulate(X, 0, 1, 10, 1, 230.0, 0.0, "base", None, keep_weights=True)
    i = m4h.simulate(X, 0, 1, 10, 1, None, 0.0, "base", None, keep_weights=True)
    assert i["cut_wanted"] == 1 and i["cut_skipped"] == 0 and i["W"][1, 0] == pytest.approx(0.1)
    # at 230 USD the long is 25.3 USD on 243.8 USD equity, the cut to 24.4 USD is under 10 USD
    assert a["cut_wanted"] == 1 and a["cut_skipped"] == 1 and a["W"][1, 0] > 0.1
    assert m4h.drift(a["W"], i["W"]) > 0


def test_an_account_at_zero_stops():
    X = world()
    X["R"][0, 25:] = 3.0                                                    # the shorts quadruple
    r = m4h.simulate(X, 0, 4, 5, 2, None, 0.0, "base", None)
    assert r["dead"] == 0 and r["ret"][0] == -1.0 and np.all(r["ret"][1:] == 0)


# ---------------------------------------------------------------- listing, funding windows, prices, spread

def test_listed_on_the_fill_day():
    days = D0 + np.arange(4) * DAY
    d0 = D0 // DAY
    m = m4h.listed_matrix(days, ["AUSDT", "BUSDT", None], {"AUSDT": (d0 + 2, None), "BUSDT": (d0, d0 + 2)})
    assert m[:, 0].tolist() == [False, True, True, True]
    assert m[:, 1].tolist() == [True, True, False, False]
    assert not m[:, 2].any()


def test_window_sums_take_times_in_the_half_open_period():
    h = m4h.HOUR_US
    ts = np.array([1, 2, 3, 4]) * h
    s, n = m4h.window_sums(ts, np.array([1.0, 2.0, 4.0, 8.0]), np.array([1 * h, 4 * h]), np.array([3 * h, 9 * h]))
    assert s.tolist() == [6.0, 0.0] and n.tolist() == [2, 0]


def test_hl_funding_reads_the_holding_hours(tmp_path):
    h = m4h.HOUR_US
    days = np.array([D0])
    ts = D0 + DAY + np.arange(1, 28) * h                                     # 01:00 of the fill day on
    pl.DataFrame({"ts_us": ts, "funding_rate": np.ones(27) * 1e-5}).write_parquet(tmp_path / "AAA.parquet")
    out = m4h.hl_funding(days, ["AAAUSDT", "BBBUSDT"], {"AAAUSDT": "AAA"}, np.array([0, 1]), root=tmp_path)
    # base (01:00, 01:00 next day]: 24 rates (02:00 .. 01:00); late (02:00, 02:00]: 24
    assert out["base"][0, 0] == pytest.approx(24e-5) and out["late"][0, 0] == pytest.approx(24e-5)
    assert math.isnan(out["base"][0, 1])


def test_late_returns_fall_back_to_the_on_time_return():
    P = np.ones((3, 2))
    C2 = np.array([[1.0, np.nan], [1.1, 2.0], [1.21, 2.0]])
    R = np.full((3, 2), 0.5)
    r = m4h.late_returns(P, C2, R)
    assert r[0, 0] == pytest.approx(0.1) and r[1, 0] == pytest.approx(0.1)
    assert r[0, 1] == 0.5 and r[2, 0] == 0.5


def test_ar_daily_takes_the_second_hourly_close():
    h = m4h.HOUR_US
    t = D0 + np.arange(48) * h
    c = 100 + np.arange(48, dtype=float)
    a = m4h.ar_daily(pl.DataFrame({"t": t, "h": c + 1, "l": c - 1, "c": c})).sort("day")
    assert a["c2"].to_list() == [101.0, 125.0]
    assert a["n"].to_list() == [24, 23]


def test_slippage_is_dt1s_proxy():
    T, N = 1, 25
    score = np.zeros((T, N))
    liq = np.arange(N, 0, -1, dtype=float)[None, :]
    spread = np.full((T, N), 0.001)
    spread[0, 21] = 0.003
    spread[0, 22] = 0.5
    spread[0, 23] = np.nan
    s = m4h.slippage(spread, liq, score)
    assert np.allclose(s[0, :20], m4h.SLIP_BASE)
    assert s[0, 20] == pytest.approx(m4h.SLIP_BASE)
    assert s[0, 21] == pytest.approx(m4h.SLIP_BASE + 0.001)
    assert s[0, 22] == m4h.SLIP_CAP and s[0, 23] == m4h.SLIP_CAP


# ---------------------------------------------------------------- numbers, benchmarks, trials

def test_stop_months_and_drawdown():
    days = D0 + np.arange(4) * DAY
    x = np.array([-0.1, -0.15, 0.0, 0.5])
    assert m4h.stop_day(x, days) == "2024-01-02"
    assert m4h.stop_day(np.zeros(4), days) is None
    assert m4h.max_dd(x) == pytest.approx(1 - 0.9 * 0.85)
    mo = m4h.months(np.array([0.1, 0.1]), np.array([dt.us("2024-01-30"), dt.us("2024-01-31")]))
    assert mo == {"2024-01": pytest.approx(0.1), "2024-02": pytest.approx(0.1)}


def test_etf_returns_land_on_the_fill_day(tmp_path):
    (tmp_path / "X.csv").write_text("Date,Close\n2024-01-02,100\n2024-01-03,110\n2026-07-01,1\n")
    days = np.array([dt.us("2024-01-01"), dt.us("2024-01-02"), dt.us("2024-01-03")])
    r = m4h.etf_returns(days, "X", root=tmp_path)
    assert r.tolist() == [0.0, pytest.approx(0.1), 0.0]


def test_eurusd_carries_the_last_rate(tmp_path):
    f = tmp_path / "fx.csv"
    f.write_text("date,eurusd\n2024-01-02,1.10\n2024-01-04,1.20\n")
    days = np.array([dt.us("2024-01-01"), dt.us("2024-01-02"), dt.us("2024-01-03")])
    assert m4h.eurusd(days, f).tolist() == [1.10, 1.10, 1.20]


def test_money_converts_usd_to_eur():
    fx = np.array([1.1, 1.2])
    m = m4h.money(np.array([0.0, 0.1]), fx, usd=230.0)
    assert m["end_usd"] == pytest.approx(253.0)
    assert m["gain_eur"] == pytest.approx(253.0 / 1.2 - 230.0 / 1.1)
    assert m4h.money(np.array([0.1]), fx, eur=200.0)["end_eur"] == pytest.approx(220.0)


def test_trials_are_97_unique_small_ones_with_their_in_sample_sharpe():
    is_sharpe = {m4h.cell_key(*c): 0.5 for c in m4h.cells()}
    T = m4h.trials(is_sharpe, 0.9)
    assert len(T) == 97 and len({t["id"] for t in T}) == 97
    assert all(t["family"] == "small" and t["sharpe"] is not None for t in T)
    assert m4h.CHECK_ID in {t["id"] for t in T}


def test_judge_cell_and_the_reason():
    rng = np.random.default_rng(1)
    days = D0 + np.arange(900) * DAY
    years = np.array([int(str(np.datetime64(int(d // DAY), "D"))[:4]) for d in days])
    good = 0.004 + 0.01 * rng.standard_normal(900)
    j = m4h.judge_cell({"ret": good}, {"ret": good}, years)
    assert j["pass"] and j["corr_ideal"] == pytest.approx(1.0)
    j = m4h.judge_cell({"ret": good}, {"ret": rng.standard_normal(900)}, years)
    assert not j["checks"]["correlation to the ideal book above 0.8"]
    ok = {n: True for n in j["checks"]}

    def row(passed, checks, nf=0.0):
        return {"pass": passed, "checks": checks, "sharpe_no_funding": nf}
    no_corr = {**ok, "correlation to the ideal book above 0.8": False}
    no_sharpe = {**ok, "Sharpe above 1.0": False}
    by = {}
    for k in m4h.KS:
        by[m4h.cell_key("ideal", k, 1, "base", "taker")] = row(True, ok)
    by[m4h.cell_key("230usd", 3, 1, "base", "taker")] = row(True, ok)
    by[m4h.cell_key("230usd", 5, 1, "base", "taker")] = row(False, no_corr)
    by[m4h.cell_key("230usd", 10, 1, "base", "taker")] = row(False, no_sharpe, nf=1.5)
    assert m4h.reason(by) == {3: "pass", 5: "minimum", 10: "funding"}
    by[m4h.cell_key("ideal", 10, 1, "base", "taker")] = row(False, no_sharpe)
    assert m4h.reason(by)[10] == "no edge"
    by[m4h.cell_key("ideal", 10, 1, "base", "taker")] = row(False, {**ok, "drawdown under 25 %": False})
    assert m4h.reason(by)[10] == "drawdown (the ideal account's too)"
