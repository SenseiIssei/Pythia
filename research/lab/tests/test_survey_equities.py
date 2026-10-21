"""The survey's equity studies (results/survey_equities_prereg.md): simulators, masks, signals.

Synthetic data only; nothing is downloaded. Run from research/lab:
python -m pytest tests/test_survey_equities.py
"""

from __future__ import annotations

import math

import numpy as np

from lab.equities import books as bk
from lab.equities import panel as pn
from lab.equities import xbrl
from lab.experiments import survey_equities as se


def days(n: int, start: str = "2010-01-04") -> np.ndarray:
    d = np.arange(np.datetime64(start), np.datetime64(start) + np.timedelta64(3 * n, "D"), dtype="datetime64[D]")
    d = d[((d.astype(np.int64) + 3) % 7) < 5]
    return d[:n]


def panel(close: np.ndarray, start: str = "2010-01-04") -> pn.Panel:
    T, N = close.shape
    return pn.panel_from_arrays(days(T, start), [f"S{j}" for j in range(N)], close, open_=close.copy(),
                                high=close.copy(), low=close.copy(), dv=np.full((T, N), 1e6))


def ctx_for(P: pn.Panel, events=()) -> se.Ctx:
    X = bk.inputs(P)
    ok = P.alive & P.traded
    return se.Ctx(S=P, E=P, X=X, ok=ok, spy=np.zeros(P.T), me=bk.month_ends(P.dates),
                  cik={s: 1000 + j for j, s in enumerate(P.names)}, has_cik=np.ones(P.N, bool), events=list(events))


def test_wsim_fills_next_open_and_charges_sales():
    close = np.full((10, 2), 100.0)
    close[5:, 0] = 110.0                       # +10 % from session 4's open to session 5's
    P = panel(close)
    sim = se.wsim(P, {1: np.array([1.0, 0.0]), 6: np.array([0.0, 0.0])})
    assert sim.expo[1] == 0 and sim.expo[2] == 1.0, "decided at the close of 1, filled at the open of 2"
    assert math.isclose(sim.gross[4], 0.10, rel_tol=1e-9)
    assert sim.tov[2] == 1.0 and sim.tov[7] == 1.0
    assert sim.fees[2] == 0 and sim.fees[7] > se.SEC * 0.99, "only the sale pays SEC fee and TAF"
    assert math.isclose(sim.net(5.0)[2], -5e-4)


def test_overlay_is_active_return_net_of_both_sides():
    close = np.full((6, 2), 100.0)
    close[3:, 0] = 102.0
    P = panel(close)
    W = np.zeros((6, 2))
    W[2:4, 0] = 0.5
    base = np.full(6, 0.001)
    act, tov, cost = se.overlay(P, W, base, 5.0, 5.0)
    assert math.isclose(act[2], 0.5 * (0.02 - 0.001))
    assert tov[2] == 0.5 and tov[4] == 0.5
    assert cost[2] > 0.5 * 10e-4 and cost[4] > 0.5 * 10e-4


def test_expected_dates_use_last_year_and_skip_an_early_report():
    T = 400
    P = panel(np.full((T, 1), 50.0))
    d = P.dates
    first = d[20]
    ctx = ctx_for(P, [("S0", 1000, str(first), "8-K")])
    ev = se.ep_events(ctx)
    c = se.ep_candidates(ctx, ev, e=5)
    assert len(c) == 1
    j, iE, t = c[0]
    assert d[iE] >= first + np.timedelta64(364, "D") and d[iE - 1] < first + np.timedelta64(364, "D")
    assert t == iE - 6
    # The company already reported 10 days before the expected date: nothing to act on.
    early = first + np.timedelta64(354, "D")
    ctx2 = ctx_for(P, [("S0", 1000, str(first), "8-K"), ("S0", 1000, str(early), "8-K")])
    c2 = se.ep_candidates(ctx2, se.ep_events(ctx2), e=5)
    assert all(abs(i - iE) > 5 for _, i, _ in c2)
    W = se.ep_weights(ctx, c, 5, 1)
    assert W[iE - 5, 0] == 1 / se.EP_K and W[iE, 0] == 1 / se.EP_K and W[iE + 1, 0] == 0


def test_turn_of_month_mask_and_book():
    d = days(80, "2015-01-02")
    m = se.tom_masks(d)
    w = m["[-1, +3]"]
    mon = d.astype("datetime64[M]")
    last = np.r_[mon[1:] != mon[:-1], True]
    first = np.r_[True, mon[1:] != mon[:-1]]
    assert w[last].all() and w[first].all()
    assert not w[np.flatnonzero(first)[1] + 3]
    ret = np.full(len(d), 0.01)
    hold = np.zeros(len(d), bool)
    hold[10:13] = True
    x = se.tom_book(ret, hold, np.full(len(d), 100.0), 2.0)
    assert x[9] == 0 and x[13] == 0
    assert math.isclose(x[10], 0.01 - 2e-4) and math.isclose(x[11], 0.01)
    assert x[12] < 0.01 - 2e-4, "the sale pays the spread, the SEC fee and TAF"
    # 2001-09-10 was not a known holiday eve
    d2 = np.array(["2001-09-07", "2001-09-10", "2001-09-17", "2001-09-18"], dtype="datetime64[D]")
    assert not se.tom_masks(d2)["pre-holiday"].any()


def test_deletion_positions_and_haircut():
    close = np.full((40, 2), 10.0)
    close[25:, 1] = np.nan                     # S1's series ends at session 24
    close[24, 1] = 3.0
    P = panel(close)
    W, spans = se.del_positions(P, [(0, 5), (1, 10)], H=20, entry_lag=6)
    assert spans[0] == (0, 11, 31) and spans[1] == (1, 16, 25)
    assert W[16, 0] == 0.5 and W[30, 0] == 1.0
    R, hit = se.haircut_returns(P)
    assert hit == [1] and R[24, 1] < -0.29


def test_seasonality_signal_is_last_years_same_month():
    T = 1400
    P = panel(np.full((T, 1), 100.0), "2000-01-03")
    c = P.close.copy()
    mon = P.dates.astype("datetime64[M]")
    # every March gains 10 %, nothing else moves
    k = 1.0
    for t in range(1, T):
        if (mon[t].astype(int) % 12) == 2 and mon[t] != mon[t - 1]:
            k *= 1.10
        c[t, 0] = 100 * k
    P = panel(c, "2000-01-03")
    ctx = ctx_for(P)
    sig = se.seas_signal(ctx, "1-5")
    me = np.flatnonzero(ctx.me)
    feb_ends = [t for t in me if (P.dates[t].astype("datetime64[M]").astype(int) % 12) == 1]
    t = feb_ends[-1]
    assert math.isclose(sig[t, 0], 0.10, rel_tol=1e-6), "before March: last years' Marches"
    jan_ends = [t for t in me if (P.dates[t].astype("datetime64[M]").astype(int) % 12) == 0]
    assert abs(sig[jan_ends[-1], 0]) < 1e-9


def test_xbrl_reduces_gross_profit_and_shares_point_in_time():
    import polars as pl
    rows = [
        (1, "Revenues", "USD", "2019-01-01", "2019-12-31", 100.0, "10-K", "FY", "2020-02-20", "a1"),
        (1, "CostOfRevenue", "USD", "2019-01-01", "2019-12-31", 60.0, "10-K", "FY", "2020-02-20", "a1"),
        (1, "Assets", "USD", "", "2019-12-31", 200.0, "10-K", "FY", "2020-02-20", "a1"),
        (1, "Assets", "USD", "", "2018-12-31", 180.0, "10-K", "FY", "2020-02-20", "a1"),
        (1, "EntityCommonStockSharesOutstanding", "shares", "", "2020-02-10", 70.0, "10-K", "FY", "2020-02-20", "a1"),
        (1, "EntityCommonStockSharesOutstanding", "shares", "", "2020-02-10", 30.0, "10-K", "FY", "2020-02-20", "a1"),
    ]
    f = pl.DataFrame(rows, schema=["cik", "concept", "unit", "start", "end", "val", "form", "fp", "filed", "accn"],
                     orient="row")
    g = xbrl.annual_gpa(f)
    assert g[1] == [(np.datetime64("2020-02-20"), np.datetime64("2019-12-31"), 0.2)]
    s = xbrl.shares_series(f)
    assert s[1] == [(np.datetime64("2020-02-20"), np.datetime64("2020-02-10"), 100.0)], "share classes summed"
