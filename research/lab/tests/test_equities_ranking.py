"""The S&P 500 ranking study (M9) on a synthetic panel. No market data is downloaded.

Run from research/lab:  python -m pytest tests
"""

from __future__ import annotations

from datetime import date

import numpy as np
import polars as pl
import pytest

from lab.experiments import equities_ranking as er
from lab.experiments import etf_trend as et


def frames(N: int = 80, seed: int = 5, start="2006-01-02", end="2018-06-29"):
    """Business days, N stocks plus SPY. Each stock has a slowly drifting
    expected return (so recent winners keep winning a little), stock 3 dies in
    2012 (its ticker is reused by a new company from 2014, as "S003" for the
    newcomer and "S003-201206" for the dead one), stock 4 joins the index in 2011."""
    rng = np.random.default_rng(seed)
    d = np.arange(np.datetime64(start), np.datetime64(end), dtype="datetime64[D]")
    d = d[((d.astype(np.int64) + 3) % 7) < 5]
    T = len(d)
    mu = np.cumsum(rng.normal(0, 0.00004, (T, N)), axis=0) + rng.normal(0.0003, 0.0004, N)
    r = mu + rng.normal(0, 0.015, (T, N)) + rng.normal(0.0002, 0.008, (T, 1))
    px = 50 * np.cumprod(1 + r, axis=0)
    names = [f"S{j:03d}" for j in range(N)]
    rows = []
    death = int(np.searchsorted(d, np.datetime64("2012-06-15")))
    reborn = int(np.searchsorted(d, np.datetime64("2014-01-02")))
    for j, s in enumerate(names):
        lo, hi = 0, T
        if j == 3:
            hi = death
            s = "S003-201206"
        vol = rng.lognormal(13, 0.5) * np.ones(hi - lo)
        rows.append(pl.DataFrame({"date": d[lo:hi], "ticker": s, "close": px[lo:hi, j], "volume": vol,
                                  "adj_close": px[lo:hi, j]}))
    rows.append(pl.DataFrame({"date": d[reborn:], "ticker": "S003", "close": px[reborn:, 0] * 0.1,
                              "volume": 1e5, "adj_close": px[reborn:, 0] * 0.1}))
    spy = 100 * np.cumprod(1 + r.mean(1))
    rows.append(pl.DataFrame({"date": d, "ticker": "SPY", "close": spy, "volume": 1e7, "adj_close": spy}))
    prices = pl.concat(rows).with_columns(pl.col("date").cast(pl.Datetime("us")))
    mem = [{"ticker": s, "start": date(2006, 1, 2), "end": None} for s in names if s not in ("S003", "S004")]
    mem += [{"ticker": "S003-201206", "start": date(2006, 1, 2), "end": date(2012, 6, 1)},
            {"ticker": "S004", "start": date(2011, 3, 1), "end": None}]
    members = pl.DataFrame(mem, schema={"ticker": pl.Utf8, "start": pl.Date, "end": pl.Date})
    return prices, members


@pytest.fixture(scope="module")
def panel() -> er.Panel:
    p, m = frames()
    return er.build_panel(p, m, start=np.datetime64("2006-01-01"))


def test_panel_is_point_in_time(panel):
    P = panel
    dead, joiner = P.names.index("S003-201206"), P.names.index("S004")
    assert "S003" not in P.names                       # in prices, never a member: not in the universe
    t_2011 = int(np.searchsorted(P.dates, np.datetime64("2011-01-03")))
    t_2013 = int(np.searchsorted(P.dates, np.datetime64("2013-01-02")))
    assert P.member[t_2011, dead] and not P.member[t_2013, dead]
    assert not P.member[t_2011, joiner] and P.member[t_2013, joiner]
    # A dead series carries its last price (zero return), and is no longer alive.
    assert not P.alive[t_2013, dead] and P.close[t_2013, dead] == P.close[t_2013 - 30, dead]
    assert np.isfinite(P.spy).all()


def test_features_never_look_ahead(panel):
    P = panel
    t = int(np.searchsorted(P.dates, np.datetime64("2012-03-01")))
    a = er.raw_features(P)
    Q = er.Panel(P.dates, P.names, P.close.copy(), P.dv.copy(), P.member, P.alive, P.spy.copy())
    Q.close[t + 1:] *= np.random.default_rng(0).lognormal(0, 0.2, Q.close[t + 1:].shape)
    Q.dv[t + 1:] *= 3
    Q.spy[t + 1:] *= 1.5
    b = er.raw_features(Q)
    for k in a:
        np.testing.assert_array_equal(np.nan_to_num(a[k][: t + 1], nan=-9), np.nan_to_num(b[k][: t + 1], nan=-9), err_msg=k)


def test_features_against_hand_computation(panel):
    P = panel
    f = er.raw_features(P)
    t, j = 1500, 10
    c = P.close[:, j]
    assert f["mom_12_1"][t, j] == pytest.approx(c[t - 21] / c[t - 252] - 1)
    assert f["dist_52wh"][t, j] == pytest.approx(c[t] / c[t - 251:t + 1].max() - 1)
    r = c[t - 62:t + 1] / c[t - 63:t] - 1
    assert f["vol_63"][t, j] == pytest.approx(r.std() * np.sqrt(252), rel=1e-6)


def test_labels_start_at_the_fill_and_keep_the_delisting_price(panel):
    P = panel
    y = er.labels(P, 5)
    t, j = 1000, 7
    assert y[t, j] == pytest.approx(P.close[t + 6, j] / P.close[t + 1, j] - 1)
    dead = P.names.index("S003-201206")
    last = int(np.flatnonzero(P.alive[:, dead])[-1])
    assert y[last - 2, dead] == pytest.approx(P.close[last, dead] / P.close[last - 1, dead] - 1)


def test_training_rows_are_purged_before_the_test_year():
    dates = np.arange(np.datetime64("2009-01-01"), np.datetime64("2011-01-01"), dtype="datetime64[D]")
    days = np.ones(len(dates), dtype=bool)
    s = int(np.searchsorted(dates, np.datetime64("2010-01-01")))
    tr = er.train_rows(days, dates, s, 20)
    last = int(np.flatnonzero(tr)[-1])
    assert last + 1 + 20 + er.EMBARGO < s and last + 1 + 20 + er.EMBARGO + er.TRAIN_EVERY >= s
    assert np.all(np.diff(np.flatnonzero(tr)) == er.TRAIN_EVERY)


def test_rank_buffer_keeps_held_names_inside_2k():
    days = np.array([True, True])
    s = np.array([[5, 4, 3, 2, 1, 0], [0, 1, 5, 4, 3, 2.0]])
    W = er.top_k(s, days, 2, buffer=False)
    assert list(np.flatnonzero(W[0] > 0)) == [0, 1] and list(np.flatnonzero(W[1] > 0)) == [2, 3]
    Wb = er.top_k(s, days, 2, buffer=True)
    # Day 2's top 4 are 2, 3, 4, 5: neither held name (0, 1) is in it, so both go.
    assert list(np.flatnonzero(Wb[1] > 0)) == [2, 3]
    s2 = np.array([[5, 4, 3, 2, 1, 0], [3.5, 1, 5, 4, 3, 2.0]])
    Wb = er.top_k(s2, days, 2, buffer=True)
    assert list(np.flatnonzero(Wb[1] > 0)) == [0, 2]   # 0 ranks 3rd (inside 2K) and stays
    assert np.allclose(np.nansum(Wb, 1), 1.0)


def test_cs_rank_ignores_masked_cells():
    x = np.array([[3.0, 1.0, np.nan, 2.0]])
    m = np.array([[True, True, True, False]])
    np.testing.assert_allclose(er.cs_rank(x, m), [[1.0, 0.0, np.nan, np.nan]])


def test_an_error_page_is_never_cached(tmp_path, monkeypatch):
    monkeypatch.setattr(er, "CACHE", tmp_path)
    with pytest.raises(er.DataUnavailable):
        er.load_files(get=lambda f: b"<html>rate limited</html>")
    assert not any(tmp_path.iterdir())

    def blocked(f):
        raise er.DataUnavailable(f"{f}: 403")
    with pytest.raises(er.DataUnavailable, match="403"):
        er.load_files(get=blocked)


def test_downloads_once_then_reads_the_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(er, "CACHE", tmp_path)
    p, m = frames(N=60, start="2010-01-04", end="2011-01-01")
    blobs = {}
    for name, df in (("prices.parquet", p), ("membership_intervals.parquet", m)):
        f = tmp_path / f"src_{name}"
        df.write_parquet(f)
        blobs[name] = f.read_bytes()
    P = er.load_panel(get=lambda f: blobs[f])
    assert P.N == 60 and (tmp_path / "prices.parquet").exists()
    P2 = er.load_panel(get=lambda f: pytest.fail("cached, no download"))
    assert P2.T == P.T


def test_the_study_runs_end_to_end(panel, monkeypatch):
    monkeypatch.setattr(er, "BOOT_DRAWS", 200)
    params = dict(er.PARAMS, n_estimators=20, min_child_samples=50, n_jobs=1)
    res = er.run(panel, params=params, cache=None)
    assert res["deflation"]["n_trials"] == 45 == len(res["rows"])
    assert sum(r["family"] == "M9" for r in res["rows"]) == 24
    assert all(0.0 <= r["deflated_p"] <= 1.0 for r in res["rows"])
    j = res["judged"]["M9"]
    assert set(j["gates"]) and isinstance(j["passes"], bool)
    assert min(j["per_year"]) == 2016
    # The planted persistence in expected returns is something a ranker can find.
    assert np.mean([v["oos"]["mean"] for v in res["rank_ic"].values()]) > 0
    md = er.markdown(res)
    assert "M9 pick" in md and "baseline pick" in md


def test_equal_weight_spreads_over_the_universe():
    elig = np.array([[True, True, False, False], [True, True, True, True]])
    W = er.equal_weight(elig, np.array([True, True]))
    np.testing.assert_allclose(W, [[0.5, 0.5, 0, 0], [0.25] * 4])


def test_simulated_book_charges_costs_on_the_fill_day():
    dates = np.arange(np.datetime64("2020-01-06"), np.datetime64("2020-01-11"), dtype="datetime64[D]")
    close = np.array([[1.0, 1.0], [1.0, 1.0], [1.1, 1.0], [1.1, 1.0], [1.1, 1.0]])
    P = er.Panel(dates, ["A", "B"], close, close, np.ones_like(close, bool), np.ones_like(close, bool), close[:, 0])
    W = np.full(close.shape, np.nan)
    W[0] = [1.0, 0.0]
    b = et.simulate(P, W)
    assert b.turnover[1] == 1.0 and b.gross[2] == pytest.approx(0.1) and b.gross[1] == 0.0
