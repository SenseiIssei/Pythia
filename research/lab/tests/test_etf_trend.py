"""The ETF trend study on a synthetic panel. No market data: Stooq is not needed.

Run from research/lab:  python -m pytest tests
"""

from __future__ import annotations

import numpy as np
import pytest

from lab.experiments import etf_trend as et


def synthetic(T: int = 2600, seed: int = 3) -> et.Panel:
    """Business days from 2010, 15 ETFs, DBC listing a year and a half late,
    one ETF with a strong trend so momentum has something to find."""
    rng = np.random.default_rng(seed)
    dates = np.arange(np.datetime64("2010-01-04"), np.datetime64("2030-01-01"), dtype="datetime64[D]")
    dates = dates[((dates.astype(np.int64) + 3) % 7) < 5][:T]
    N = len(et.SYMBOLS)
    r = rng.normal(0.0002, 0.01, (len(dates), N))
    r[:, 1] += 0.0020                        # QQQ trends up
    close = 100 * np.cumprod(1 + r, axis=0)
    close[:400, et.SYMBOLS.index("DBC")] = np.nan
    return et.Panel(dates=dates, names=list(et.SYMBOLS), close=close)


def csv(dates, closes) -> str:
    rows = "\n".join(f"{d},{c},{c},{c},{c},1000" for d, c in zip(dates, closes))
    return "Date,Open,High,Low,Close,Volume\n" + rows + "\n"


def test_parses_stooq_and_refuses_an_error_page():
    d, c = et.parse_stooq(csv(["2020-01-03", "2020-01-02"], [2.0, 1.0]))
    assert list(d.astype(str)) == ["2020-01-02", "2020-01-03"] and list(c) == [1.0, 2.0]
    with pytest.raises(et.DataUnavailable):
        et.parse_stooq("Exceeded the daily hits limit")
    with pytest.raises(et.DataUnavailable):
        et.parse_stooq("Date,Open,High,Low,Close,Volume\n")


def test_an_error_page_is_never_cached(tmp_path, monkeypatch):
    monkeypatch.setattr(et, "CACHE", tmp_path)
    with pytest.raises(et.DataUnavailable):
        et.load_csv("SPY", fetch=lambda s: "No data")
    assert not (tmp_path / "SPY.csv").exists()
    et.load_csv("SPY", fetch=lambda s: csv(["2020-01-02"], [1.0]))
    assert (tmp_path / "SPY.csv").exists()
    assert et.load_csv("SPY", fetch=lambda s: pytest.fail("cached, no download")).startswith("Date")


def test_blocked_download_stops_the_study(tmp_path, monkeypatch):
    monkeypatch.setattr(et, "CACHE", tmp_path)

    def blocked(sym):
        raise et.DataUnavailable(f"{sym}: 403")
    with pytest.raises(et.DataUnavailable, match="SPY: 403"):
        et.load_panel(fetch=blocked)


def test_panel_carries_gaps_forward_inside_a_life_only():
    s = {"SPY": et.parse_stooq(csv(["2020-01-02", "2020-01-03", "2020-01-06"], [1, 2, 3])),
         "IEF": et.parse_stooq(csv(["2020-01-03", "2020-01-07"], [5, 6]))}
    P = et.build_panel(s)
    ief = P.close[:, P.col("IEF")]
    assert np.isnan(ief[0]) and list(ief[1:]) == [5, 5, 6]
    assert list(P.close[:, P.col("SPY")][:3]) == [1, 2, 3] and np.isnan(P.close[3, P.col("SPY")])


def test_decision_days_are_week_ends_and_weekdays():
    P = synthetic(30)
    d = et.decision_days(P.dates)
    dow = (P.dates.astype(np.int64) + 3) % 7
    assert (dow[d][:-1] == 4).all(), "no holidays in the synthetic calendar: every week ends on a Friday"
    mon = et.decision_days(P.dates, 0)
    assert (dow[mon] == 0).all() and mon.sum() == 6


def test_signals_use_only_the_past():
    P = synthetic()
    W = et.weights(P, "trend_vol", 126, target=0.1)
    t = 1500
    Q = et.Panel(P.dates, P.names, P.close.copy())
    Q.close[t + 1:] *= np.linspace(0.2, 5, P.T - t - 1)[:, None]
    W2 = et.weights(Q, "trend_vol", 126, target=0.1)
    assert np.array_equal(np.nan_to_num(W[: t + 1], nan=-1), np.nan_to_num(W2[: t + 1], nan=-1))


@pytest.mark.parametrize("v", et.grid())
def test_weights_are_long_only_and_never_levered(v):
    P = synthetic(1200)
    W = et.weights(P, v["kind"], v["L"], v.get("k", 0), v.get("target", 0.0))
    rows = W[np.isfinite(W).any(1)]
    assert rows.size and (rows >= 0).all() and (rows.sum(1) <= 1 + 1e-9).all()
    dbc = P.col("DBC")
    assert not W[:400 + et.MIN_HISTORY - 1, dbc][np.isfinite(W[:400 + et.MIN_HISTORY - 1, dbc])].any(), \
        "an ETF without a year of history is never held"


def test_dual_momentum_finds_the_trend():
    P = synthetic()
    W = et.weights(P, "dual_mom", 252, 3)
    rows = W[et.MIN_HISTORY:][np.isfinite(W[et.MIN_HISTORY:]).any(1)]
    assert (rows[:, 1] > 0).mean() > 0.9


def test_simulation_trades_a_day_late_and_charges_turnover():
    P = synthetic(300)
    W = np.full(P.close.shape, np.nan)
    W[100, 0] = 1.0
    W[100, 1:] = 0.0
    b = et.simulate(P, W)
    R = P.ret()
    assert b.gross[101] == 0 and b.turnover[101] == pytest.approx(1.0)
    assert b.gross[102] == pytest.approx(R[102, 0])
    assert b.net(0.001)[101] == pytest.approx(-0.001)
    # Buy and hold: no turnover after the first fill, and the book is SPY.
    spy = et.simulate(P, et.benchmark(P, "spy"), lag=0)
    first = int(np.flatnonzero(spy.turnover)[0])
    assert spy.turnover[first + 1:].sum() == 0
    assert np.allclose(spy.gross[first + 1:], R[first + 1:, 0])


def test_sixty_forty_rebalances_monthly():
    P = synthetic(300)
    W = et.benchmark(P, "6040")
    rows = np.flatnonzero(np.isfinite(W).any(1))
    assert 12 <= rows.size <= 15
    assert np.allclose(W[rows][:, P.col("SPY")], 0.6) and np.allclose(W[rows][:, P.col("IEF")], 0.4)


def test_bootstrap_and_deflation_behave():
    rng = np.random.default_rng(0)
    good = rng.normal(0.001, 0.01, 2500)
    b = et.block_bootstrap(good, rng.normal(0, 0.01, 2500), draws=400)
    assert b["p05"] < et.sharpe(good) < b["p95"] and b["share_above_0"] > 0.95
    rows = [{"oos_sharpe_5bps": s, "oos_skew": 0.0, "oos_kurt": 3.0, "oos_days": 2500}
            for s in rng.normal(0, 0.3, 19).tolist() + [1.6]]
    d = et.deflate(rows)
    assert d["n_trials"] == 20
    assert rows[-1]["deflated_p"] > 0.95 > max(r["deflated_p"] for r in rows[:-1])


def test_the_whole_study_runs_and_counts_every_trial():
    res = et.run(synthetic())
    assert len(res["rows"]) == len(et.grid()) + 4 == 20
    assert res["deflation"]["n_trials"] == 20
    assert set(res["gates"]) == {"deflated p > 0.95", "OOS Sharpe >= half in-sample", "Sharpe > 0 with costs doubled",
                                 "drawdown below SPY", "Sharpe above 60/40"}
    assert res["passes"] == all(res["gates"].values())
    assert "Gates" in et.markdown(res)


def test_yahoo_answer_becomes_a_stooq_shaped_csv_without_gaps_or_nulls():
    payload = {"chart": {"result": [{
        "timestamp": [946909800, 946996200, 947082600],
        "indicators": {"adjclose": [{"adjclose": [90.9, None, 88.1]}]},
    }]}}
    d, c = et.parse_stooq(et.yahoo_csv(payload))
    assert [str(x) for x in d] == ["2000-01-03", "2000-01-05"]
    assert list(c) == [90.9, 88.1]
    with pytest.raises(et.DataUnavailable):
        et.yahoo_csv({"chart": {"result": None}})
