"""The four perp studies registered together on 2026-10-21 (funding_carry, trend_shorts,
flush_long, kraken_funding_gap) and the experimental paper book funding_carry. No network:
data are synthetic.

Run from research/lab:  python -m pytest tests/test_perps_studies.py
"""

from __future__ import annotations

import numpy as np
import polars as pl
import pytest

from lab.experiments import fam_common as fc
from lab.experiments import flush_long as fl
from lab.experiments import funding_carry as fcy
from lab.experiments import kraken_funding_gap as kfg
from lab.experiments import perps_common as pc
from lab.experiments import trend_shorts as ts
from lab.experiments import xs_daily as xs
from lab.paper import funding_carry as book

DAY_US = 86_400_000_000


def panel(ret: np.ndarray, funding: np.ndarray | None = None, perp_ok: np.ndarray | None = None) -> fc.Panel:
    T, N = ret.shape
    px = np.cumprod(1 + np.nan_to_num(ret), 0)
    ones = np.ones((T, N), dtype=bool)
    return fc.Panel(days=np.arange(T, dtype=np.int64) * DAY_US, names=[f"C{i}USDT" for i in range(N)],
                    bases=[f"C{i}" for i in range(N)], close=px, px=px, high=px, low=px, ret=ret, alive=ones,
                    traded=ones, age=np.full((T, N), 100), adv28=np.full((T, N), 1e7), sigma=np.full((T, N), 0.02),
                    eligible=ones, perp_ok=ones if perp_ok is None else perp_ok,
                    funding=np.zeros((T, N)) if funding is None else funding, btc_on=np.ones(T, dtype=bool), btc=0)


# ---------------------------------------------------------------- common

def test_pool_counts_1777_trials():
    p = pc.pool([0.1, -0.2, 0.3])
    assert p["n_total"] == pc.HAND_TRIALS + p["factory_trials"] + pc.TODAY_TRIALS
    assert pc.HAND_TRIALS + pc.TODAY_TRIALS == 1177


@pytest.mark.parametrize("sym,coin", [("1000PEPEUSDT", "PEPE"), ("LUNAUSDT~0", "LUNA"), ("MATICUSDT", "POL"),
                                      ("BTCUSDT", "BTC"), ("XBT", "BTC")])
def test_coin_of(sym, coin):
    assert pc.coin_of(sym) == coin


# ---------------------------------------------------------------- trend_shorts

def test_perp_sim_longs_pay_and_shorts_receive_funding():
    ret = np.zeros((4, 2))
    ret[2] = [0.10, 0.10]
    f = np.full((4, 2), 0.001)
    P = panel(ret, f)
    W = np.array([[0.0, 0.0], [0.5, -0.5], [np.nan, np.nan], [np.nan, np.nan]])
    o = ts.sim(P, W, start=0)
    assert o["long_fund"][2] == pytest.approx(-0.0005) and o["short_fund"][2] == pytest.approx(0.0005)
    assert o["long_px"][2] == pytest.approx(0.05) and o["short_px"][2] == pytest.approx(-0.05)
    assert o["gross"][2] == pytest.approx(0.0)
    assert o["tov_long"][1] == pytest.approx(0.5) and o["tov_short"][1] == pytest.approx(0.5)


def test_perp_sim_opens_nothing_without_a_perp():
    ok = np.ones((3, 2), dtype=bool)
    ok[1, 1] = False
    P = panel(np.zeros((3, 2)), perp_ok=ok)
    o = ts.sim(P, np.array([[0.0, 0.0], [0.5, 0.5], [np.nan, np.nan]]), start=0)
    assert o["long_expo"][1] == pytest.approx(0.5)


def test_flip_counts_turnover_once_per_side():
    P = panel(np.zeros((4, 1)))
    o = ts.sim(P, np.array([[0.0], [0.3], [-0.2], [np.nan]]), start=0)
    assert o["tov_long"][2] == pytest.approx(0.3) and o["tov_short"][2] == pytest.approx(0.2)


def test_neutral_scales_without_forgetting_the_rule_book():
    P = panel(np.zeros((4, 2)))
    # The long is entered on day 1 while the short side is empty, the short on day 2.
    W = np.array([[0.0, 0.0], [0.4, np.nan], [np.nan, -0.2], [np.nan, np.nan]])
    o = ts.sim(P, W, neutral=True, start=0)
    assert o["long_expo"][1] == 0.0, "no short side: flat"
    assert o["long_expo"][2] == pytest.approx(0.2) and o["short_expo"][2] == pytest.approx(0.2), \
        "the long held by the rule comes back, scaled to the short side"


def test_combine_prefers_entries_then_exits():
    WL = np.array([[np.nan, 0.1, 0.0]])
    WS = np.array([[-0.1, 0.0, np.nan]])
    out = ts.combine(WL, WS)
    assert out[0].tolist() == pytest.approx([-0.1, 0.1, 0.0])


def test_donchian_short_mirrors_the_long():
    T = 60
    px = np.r_[np.full(30, 100.0), np.linspace(99, 70, 30)]
    ret = np.r_[np.nan, px[1:] / px[:-1] - 1][:, None]
    P = panel(ret)
    P.px[:] = px[:, None]
    W = ts.donchian_side(P, np.array([0]), np.ones((T, 1), dtype=bool), 20, 1, -1)
    first = int(np.flatnonzero(np.isfinite(W[:, 0]) & (W[:, 0] != 0))[0])
    assert first == 30 and W[first, 0] < 0, "short entered on the first close under the 20-day low"


# ---------------------------------------------------------------- funding_carry

def test_leg_split_adds_up_to_xs_book():
    rng = np.random.default_rng(1)
    T, N = 40, 30
    M = {"days": np.arange(T, dtype=np.int64) * DAY_US + xs.HOLDOUT, "R": rng.normal(0, 0.02, (T, N)),
         "fund": rng.normal(0, 0.001, (T, N)), "perp_adv28": rng.uniform(1, 2, (T, N)),
         "adv28_raw": np.ones((T, N)), "fund7_raw": np.zeros((T, N))}
    score = rng.normal(size=(T, N))
    g, _, f, _ = xs.book(M, score, 5, 3, fcy.N_LIQUID, True)
    lg = fcy.legs(M, score, 5, 3)
    lg.pop("per_coin")
    assert np.allclose(lg["long_px"] + lg["short_px"] + lg["long_fund"] + lg["short_fund"], g + f)


def test_late_shifts_one_day():
    s = np.arange(6.0).reshape(3, 2)
    assert np.isnan(fcy.late(s)[0]).all() and fcy.late(s)[1:].tolist() == s[:2].tolist()


# ---------------------------------------------------------------- flush_long

def test_events_keep_one_per_flush():
    a = pl.DataFrame({"day": np.arange(20) * DAY_US, "doi": [-0.06] * 20, "r3": [-0.06] * 20, "fund": [-1e-4] * 20})
    ev = fl.events(a, 0.05)
    assert (np.diff(ev["day"].to_numpy()) // DAY_US).tolist() == [7, 7]


def test_events_need_negative_funding():
    a = pl.DataFrame({"day": [0, DAY_US], "doi": [-0.06, -0.06], "r3": [-0.06, -0.06], "fund": [1e-4, -1e-4]})
    assert fl.events(a, 0.05)["day"].to_list() == [DAY_US]


def test_trade_ret_pays_funding_and_a_round_trip():
    ret = np.zeros((5, 1))
    ret[1:3] = 0.01
    f = np.zeros((5, 1))
    f[1:3] = -0.001
    P = panel(ret, f)
    r = fl.trade_ret(P, 0, 2, np.array([0]), 0.001)
    assert r == pytest.approx(1.01 ** 2 - 1 + 0.002 - 0.002)


# ---------------------------------------------------------------- kraken_funding_gap

def test_gap_book_enters_collects_and_exits():
    T = 200
    grid = np.arange(T, dtype=np.int64) * kfg.H + pc.SEED  # arbitrary origin, overwritten below
    D = {"grid": grid, "coins": ["A"], "rs": np.zeros((T, 1)), "rm": np.zeros((T, 1)),
         "kf": np.full((T, 1), 1e-4), "bf": np.zeros((T, 1))}
    D["kf"][120:] = -1e-4
    old = kfg.START, kfg.END
    try:
        kfg.START = "1970-01-01"
        kfg.END = "2100-01-01"
        D["grid"] = np.arange(T, dtype=np.int64) * kfg.H
        o = kfg.run(D, 0.5, 24)
    finally:
        kfg.START, kfg.END = old
    assert len(o["entries"]) == 1, "entered once when the 24 h gap passed 50 % a year"
    assert o["fund"][30] == pytest.approx(kfg.NOTIONAL * 1e-4)
    assert o["deployed"][-1] == 0.0, "left once Kraken's funding turned negative"
    assert o["cost"].sum() == pytest.approx(-2 * kfg.NOTIONAL * (kfg.SPOT_COST + kfg.PERP_COST))


# ---------------------------------------------------------------- the paper book

def candidates_frame() -> pl.DataFrame:
    n = 30
    return pl.DataFrame({"day": [5 * DAY_US] * n, "symbol": [f"C{i}USDT" for i in range(n)],
                         "perp": [f"C{i}USDT" for i in range(n)], "perp_adv28": np.linspace(1e8, 1e6, n),
                         "fund7_raw": np.linspace(-0.01, 0.01, n)})


def test_paper_candidates_rank_by_funding_among_listed():
    listing = {f"C{i}": f"PF_C{i}USD" for i in range(25)}
    c = book.candidates(candidates_frame(), 5 * DAY_US, {f"C{i}USDT" for i in range(30)}, listing)
    assert c.height == 25 and c["perp"][0] == "C0USDT", "lowest funding first, unlisted coins out"
    tr = book.new_tranche(c)
    assert sum(1 for x in tr.values() if x > 0) == book.K and sum(1 for x in tr.values() if x < 0) == book.K
    assert sum(tr.values()) == pytest.approx(0.0)
    assert tr["C0USDT"] == pytest.approx(0.5 / book.K / book.HOLD)


def test_paper_signal_is_signed_experimental_and_autopilot_only():
    listing = {f"C{i}": f"PF_C{i}USD" for i in range(25)}
    c = book.candidates(candidates_frame(), 5 * DAY_US, {f"C{i}USDT" for i in range(30)}, listing)
    tgt = book.book_of([book.new_tranche(c)] * 3)
    sig = book.signal(tgt, listing, 5 * DAY_US, 6 * DAY_US)
    assert sig["experimental"] is True and sig["autopilot_only"] is True and sig["asset_class"] == "perp"
    assert sig["lab_exposure"]["long"] == pytest.approx(0.5) and sig["lab_exposure"]["short"] == pytest.approx(-0.5)
    assert set(sig["venue_symbols"]) == set(sig["weights"])
    assert sig["evidence"]["experimental"] is True and sig["variant"].startswith(book.LABEL)
