"""The overnight study on synthetic data. No download: Yahoo and the bars are not needed.

Run from research/lab:  python -m pytest tests
"""

from __future__ import annotations

import math

import numpy as np
import polars as pl
import pytest

from lab.experiments import overnight as on


def sessions(n: int, start: str = "2015-01-02") -> np.ndarray:
    d0 = np.datetime64(start, "D")
    d = np.arange(d0, d0 + np.timedelta64(3 * n, "D"), dtype="datetime64[D]")
    return d[np.is_busday(d)][:n]


def series(dates, o, c, adj=None, split=None) -> dict:
    n = len(dates)
    return {"dates": dates, "open": np.asarray(o, float), "close": np.asarray(c, float),
            "adj": np.asarray(c if adj is None else adj, float),
            "split": np.ones(n) if split is None else np.asarray(split, float)}


def synthetic_panel(T: int = 900, seed: int = 1, start: str = "2015-01-02") -> on.Panel:
    rng = np.random.default_rng(seed)
    dates = sessions(T, start)
    out = {}
    for k, s in enumerate(("SPY", "QQQ", "IWM")):
        night = rng.normal(0.0006, 0.004, T)
        day = rng.normal(0.0, 0.008, T)
        close, opn = np.empty(T), np.empty(T)
        prev = 100.0 + k
        for t in range(T):
            opn[t] = prev * (1 + night[t])
            close[t] = opn[t] * (1 + day[t])
            prev = close[t]
        out[s] = series(dates, opn, close)
    return on.build_panel(out)


def test_yahoo_answer_round_trips_and_splits_rebuild_the_raw_price():
    payload = {"chart": {"result": [{
        "timestamp": [1577970000, 1578056400, 1578315600],          # 2020-01-02, 01-03, 01-06 (14:00 UTC)
        "events": {"splits": {"x": {"date": 1578315600, "numerator": 2, "denominator": 1}}},
        "indicators": {"quote": [{"open": [10.0, None, 11.0], "close": [10.5, 10.6, 11.2]}],
                       "adjclose": [{"adjclose": [10.0, 10.1, 11.2]}]}}]}}
    text = on.yahoo_ohlc_csv(payload)
    x = on.parse_ohlc(text)
    assert list(x["dates"].astype(str)) == ["2020-01-02", "2020-01-06"]          # the day without an open is dropped
    assert list(x["split"]) == [1.0, 2.0]
    P = on.build_panel({"SPY": x})
    # before the 2-for-1 split the unadjusted close was twice the split-adjusted one
    assert P.raw_close[P.dates == np.datetime64("2020-01-02"), 0][0] == pytest.approx(21.0)
    assert P.raw_close[P.dates == np.datetime64("2020-01-06"), 0][0] == pytest.approx(11.2)
    with pytest.raises(on.DataUnavailable):
        on.yahoo_ohlc_csv({"chart": {"result": None}})
    with pytest.raises(on.DataUnavailable):
        on.parse_ohlc("Date,Close\n2020-01-02,1\n")


def test_an_error_is_never_cached(tmp_path, monkeypatch):
    monkeypatch.setattr(on, "CACHE", tmp_path)
    with pytest.raises(on.DataUnavailable):
        on.load_csv("SPY", fetch=lambda s: "not a csv")
    assert not (tmp_path / "SPY.csv").exists()


def test_the_night_carries_the_dividend_and_the_parts_compound_to_the_total():
    d = sessions(3)
    # close 100, a 1.00 dividend goes ex on day 2: the price opens 99.0 and closes 99.5
    adj = [100 * (99 / 100), 99.0 * 1.0, 99.5]           # Yahoo scales history before the ex-date by (1 - 1/100)
    P = on.build_panel({"SPY": series(d, [100, 99.0, 99.4], [100, 99.0, 99.5], adj=adj)})
    N = on.nights(P)
    assert N.night[1, 0] == pytest.approx(0.0)           # 99 open + 1 dividend against 100: flat, not -1 %
    t = 2
    assert (1 + N.night[t, 0]) * (1 + N.day[t, 0]) - 1 == pytest.approx(N.total[t, 0])


def test_stale_years_and_young_symbols_are_not_traded():
    d = sessions(600)
    c = 100 + np.arange(600) * 0.1
    o = np.r_[c[0], c[:-1]]                              # every open equals the previous close
    o[300:] = c[299:-1] + 0.05                           # from day 300 the opens are real
    P = on.build_panel({"SPY": series(d, o, c)})
    N = on.nights(P)
    yrs = P.dates.astype("datetime64[Y]").astype(int) + 1970
    assert not N.valid[yrs == 2015].any()                # 2015 is all stale
    assert not N.valid[:on.HISTORY].any()                # and the first year has no history anyway
    assert N.valid[(yrs == 2017) & (np.arange(600) > 300)].all()


def test_calendar_rules():
    d = np.array(["2024-11-26", "2024-11-27", "2024-11-29", "2024-12-02", "2024-12-03", "2024-12-04",
                  "2024-12-05"], dtype="datetime64[D]")
    hol = on.holiday_nights(d)
    assert list(hol) == [False, False, True, False, False, False, False]     # Thanksgiving, not the weekend
    rank, last = on.month_position(d)
    assert list(rank) == [1, 2, 3, 1, 2, 3, 4] and list(last) == [False, False, True, False, False, False, True]


def test_rules_use_only_the_previous_close():
    P = synthetic_panel()
    N = on.nights(P)
    a = on.rule_masks(P, N)
    t = 700
    P.adj[t:, 0] *= 3.0                                   # a jump at the close of t ...
    N2 = on.nights(P)
    b = on.rule_masks(P, N2)
    for r in on.RULES:
        assert (a[r][:t + 1] == b[r][:t + 1]).all(), r    # ... cannot change the decision for the night into t


def test_costs_of_a_night():
    d = sessions(300)
    c = np.where(np.arange(300) % 2 == 0, 50.0, 51.0)    # open = close, so every move happens overnight
    P = on.build_panel({"SPY": series(d, c, c), "AAPL": series(d, c, c)})
    N = on.nights(P)
    hold = np.ones((P.T, P.N), dtype=bool)
    t = on.HISTORY + 5
    n = c[t] / c[t - 1] - 1

    def expect(side: float) -> float:
        return n - side - (1 + n) * (side + on.SEC_FEE) - on.TAF_PER_SHARE / c[t - 1]

    r, expo, live = on.sleeve_returns(P, N, ("SPY",), hold)
    assert N.night[t, 0] == pytest.approx(n) and r[t] == pytest.approx(expect(1e-4))
    r2, _, _ = on.sleeve_returns(P, N, ("SPY",), hold, cost_mult=2.0)
    assert r2[t] == pytest.approx(expect(2e-4))
    rs, _, _ = on.sleeve_returns(P, N, ("AAPL",), hold)
    assert rs[t] == pytest.approx(expect(3e-4))
    # a symbol the rule leaves out holds cash; its share is not spread over the others
    half = hold.copy()
    half[:, P.col("AAPL")] = False
    rb, eb, _ = on.sleeve_returns(P, N, ("SPY", "AAPL"), half)
    assert eb[t] == pytest.approx(0.5) and rb[t] == pytest.approx(r[t] / 2)


def test_bar_points_and_fill_nights():
    rows = []
    for day, base in (("2024-03-04", 100.0), ("2024-03-05", 101.0)):
        for b in range(78):
            rows.append({"date": day, "bar": b, "open": base + b * 0.01, "high": 0.0, "low": 0.0,
                         "close": base + b * 0.01 + 0.005, "volume": 1.0, "tp": 0.0})
    df = pl.DataFrame(rows).with_columns(pl.col("date").str.to_date())
    bp = on.bar_points(df)
    assert bp["o0"][1] == pytest.approx(101.0) and bp["c_last"][0] == pytest.approx(100.775)
    assert bp["c_m2"][0] == pytest.approx(100.755)       # bar 75 closes at 15:50
    d = np.array(["2024-03-04", "2024-03-05"], dtype="datetime64[D]")
    P = on.build_panel({"SPY": series(d, [100.0, 101.0], [100.775, 101.775])})
    N = on.nights(P)
    N.valid[:] = True
    f = on.fill_nights(P, N, {"SPY": bp})
    assert f["nights"]["F2"][1, 0] == pytest.approx(101.0 / 100.775 - 1)
    assert f["nights"]["F1"][1, 0] == pytest.approx(101.005 / 100.755 - 1)


def test_pool_reproduces_the_published_bar():
    v = on.published_var()
    from lab.experiments import fam_common as fc
    assert fc._sr0(v, on.POOL_PUBLISHED_TRIALS) * math.sqrt(365) == pytest.approx(on.POOL_PUBLISHED_SR0)
    p = on.pool([0.0] * 10)
    assert p["n_total"] == on.PRIOR_TRIALS + 10


def test_run_on_a_synthetic_panel():
    P = synthetic_panel(T=2000, start="2013-01-02")      # in sample to 2017, out of sample from 2018
    res = on.run(P, {}, ["SPY"], seed=1)
    assert len(res["rows"]) == 24 and res["pick"] in {r["name"] for r in res["rows"]}   # four sleeves have data
    assert not res["gates"]["Sharpe > 0 with fill models F1 and F2"]      # no bars, the gate cannot pass
    assert set(res["references"]) == {"U1 SPY", "U2 QQQ", "U3 IWM", "U4 SPY+QQQ+IWM"}
    md = on.markdown(res)
    assert "Verdict" in md and chr(0x2014) not in md          # no long dashes in the report
