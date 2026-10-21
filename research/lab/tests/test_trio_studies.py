"""The three studies registered together on 2026-10-21 in the evening
(perps_neutral_portfolio, attention_wiki, intraday_tsmom) and the page view collector.
No network: data are synthetic or canned.

Run from research/lab:  python -m pytest tests/test_trio_studies.py
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from urllib.parse import parse_qs, urlparse

import numpy as np
import polars as pl
import pytest

from lab.collect import flow, wiki
from lab.experiments import attention_wiki as aw
from lab.experiments import fam_common as fc
from lab.experiments import intraday_tsmom as it
from lab.experiments import perps_neutral_portfolio as pnp
from lab.experiments import trio_common as tc

DAY_US = 86_400_000_000
HOUR_US = 3_600_000_000


def us(y, m, d) -> int:
    return int(datetime(y, m, d, tzinfo=timezone.utc).timestamp() * 1e6)


def panel(ret: np.ndarray, start: int = us(2024, 1, 1)) -> fc.Panel:
    T, N = ret.shape
    px = np.cumprod(1 + np.nan_to_num(ret), 0)
    ones = np.ones((T, N), dtype=bool)
    return fc.Panel(days=start + np.arange(T, dtype=np.int64) * DAY_US, names=[f"C{i}USDT" for i in range(N)],
                    bases=[f"C{i}" for i in range(N)], close=px, px=px, high=px, low=px, ret=ret, alive=ones,
                    traded=ones, age=np.full((T, N), 100), adv28=np.tile(np.arange(N, 0, -1) * 1e7, (T, 1)),
                    sigma=np.full((T, N), 0.02), eligible=ones, perp_ok=ones, funding=np.zeros((T, N)),
                    btc_on=np.ones(T, dtype=bool), btc=0)


# ---------------------------------------------------------------- the pool

def test_pool_counts_the_registration():
    assert tc.HAND_TRIALS == 1328 and tc.TODAY_TRIALS == 25
    p = tc.pool([0.1, -0.2, 0.3])
    assert p["n_total"] == 1328 + p["factory_trials"] + 25
    assert "1,353 hand trials" in tc.pool_line(p)


# ---------------------------------------------------------------- perps_neutral_portfolio

def test_erc_matches_inverse_vol_without_correlation_and_equalises_risk():
    cov = np.diag([1.0, 4.0, 9.0])
    w = pnp.erc(cov)
    assert w == pytest.approx(np.array([1, 1 / 2, 1 / 3]) / (1 + 1 / 2 + 1 / 3), abs=1e-6)
    cov = np.array([[1.0, 0.5, -0.2], [0.5, 2.0, 0.1], [-0.2, 0.1, 0.5]])
    w = pnp.erc(cov)
    rc = w * (cov @ w)
    assert w.sum() == pytest.approx(1.0) and (w > 0).all()
    assert rc == pytest.approx(np.full(3, rc.mean()), rel=1e-5)


def test_target_methods():
    rng = np.random.default_rng(0)
    h = rng.normal(0, 1, (90, 3)) * np.array([0.01, 0.02, 0.04])
    assert pnp.target("EW", h) == pytest.approx(np.full(3, 1 / 3))
    iv = pnp.target("IV", h)
    assert iv[0] > iv[1] > iv[2] and iv.sum() == pytest.approx(1.0)


def test_combine_waits_for_history_reweights_monthly_and_charges_the_reweight():
    days = us(2024, 1, 1) + np.arange(120, dtype=np.int64) * DAY_US
    R = np.zeros((120, 3))
    R[:, 0] = 0.01
    TV = np.full((120, 3), 0.1)
    o = pnp.combine(R, TV, days, "EW", 0.001, 0)
    first = int(np.flatnonzero(np.isfinite(o["net"]))[0])
    assert first == pnp.MIN_OBS
    # The first weights are an entry: one unit of turnover charged at the cost.
    assert o["net"][first] == pytest.approx(0.01 / 3 - 0.001)
    # Between month starts the weights drift with the books (book 0 grows).
    assert o["w"][first + 5, 0] > o["w"][first + 1, 0]
    ms = np.flatnonzero(pnp.month_starts(days) & (np.arange(120) > first))
    assert o["w"][ms[0]] == pytest.approx(np.full(3, 1 / 3))
    assert o["turnover"][ms[0]] > 0.1


def test_on_calendar_books_an_xs_decision_on_the_next_day():
    cal = us(2024, 1, 1) + np.arange(5, dtype=np.int64) * DAY_US
    out = pnp.on_calendar(cal, cal[:3], np.array([1.0, 2.0, 3.0]), 1)
    assert np.isnan(out[0]) and out[1:4].tolist() == [1.0, 2.0, 3.0]


# ---------------------------------------------------------------- page view collector

def test_views_parse_and_quote_titles():
    seen = []

    def fetch(url):
        seen.append(url)
        return {"items": [{"timestamp": "2024010100", "views": 5}, {"timestamp": "2024010200", "views": 7}]}

    df = wiki.views(fetch, "$Trump", date(2024, 1, 1), date(2024, 1, 2))
    assert "%24Trump/daily/2024010100/2024010200" in seen[0]
    assert df["views"].to_list() == [5, 7] and df["day_us"][0] == us(2024, 1, 1)
    assert wiki.views(lambda u: None, "Gone", date(2024, 1, 1), date(2024, 1, 2)).is_empty()
    assert wiki.url_title("Solana (blockchain platform)") == "Solana_%28blockchain_platform%29"


def test_redirects_follow_continue():
    calls = []

    def fetch(url):
        q = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
        calls.append(q)
        if "rdcontinue" not in q:
            return {"continue": {"rdcontinue": "x", "continue": "||"},
                    "query": {"pages": {"1": {"redirects": [{"title": "BTC"}]}}}}
        return {"query": {"pages": {"1": {"redirects": [{"title": "Bitcoins"}]}}}}

    assert wiki.redirects(fetch, "Bitcoin") == ["BTC", "Bitcoins"]
    assert len(calls) == 2


def test_coin_views_sum_article_and_redirects_once_per_base():
    pv = pl.DataFrame({"title": ["A", "A-old", "P", "A"], "day_us": [1, 1, 1, 2], "views": [10, 5, 3, 4]})
    tt = pl.DataFrame({"base": ["X", "X", "M", "Q"], "article": ["A", "A", "P", "P"], "title": ["A", "A-old", "P", "P"]})
    cv = wiki.coin_views(pv, tt)
    assert cv.filter(pl.col("base") == "X")["views"].to_list() == [15, 4]
    assert cv.filter(pl.col("base") == "M")["views"].to_list() == [3]
    assert cv.filter(pl.col("base") == "Q")["views"].to_list() == [3]


def test_run_continues_with_overlap_and_writes_both_files(tmp_path, monkeypatch):
    monkeypatch.setattr(flow, "FLOW", tmp_path)
    monkeypatch.setattr(wiki, "ARTICLES", {"BTC": "Bitcoin"})
    asked = []

    def fetch(url):
        if "w/api.php" in url:
            return {"query": {"pages": {"1": {"redirects": [{"title": "Bitcoins"}]}}}}
        asked.append(url)
        part = url.split("/daily/")[1]
        a = datetime.strptime(part[:8], "%Y%m%d").date()
        return {"items": [{"timestamp": f"{a:%Y%m%d}00", "views": 1}]}

    s = wiki.run(False, fetch, until=date(2024, 3, 1))
    assert s["titles"] == 2 and (tmp_path / "wiki_pageviews.parquet").exists()
    assert all("/20150701" in u for u in asked)
    asked.clear()
    pl.DataFrame({"title": ["Bitcoin"], "day_us": [us(2024, 3, 1)], "views": [9]}).pipe(
        lambda d: flow.write("wiki_pageviews", d))
    wiki.run(False, fetch, until=date(2024, 3, 5))
    assert any("/2024022700" in u for u in asked)
    assert pl.read_parquet(tmp_path / "wiki_titles.parquet").height == 2


def test_mapping_has_no_dropped_coin():
    assert not set(wiki.ARTICLES) & set(wiki.DROPPED)
    assert not set(wiki.ARTICLES) & set(wiki.NO_ARTICLE)
    assert wiki.ARTICLES["MATIC"] == wiki.ARTICLES["POL"]


# ---------------------------------------------------------------- attention_wiki

def test_attention_uses_views_up_to_the_day_before():
    T = 200
    V = np.full((T, 1), 1000.0)
    V[150] = 100_000.0
    a = aw.attention(V)["att"][:, 0]
    assert a[150] == pytest.approx(0.0, abs=1e-12)          # the spike is not known on its own day
    assert a[151] > 1.0                                      # it is the next day
    assert np.isnan(a[aw.MIN_HISTORY - 1]) and np.isfinite(a[aw.MIN_HISTORY + 1])


def test_attention_needs_100_views_a_day():
    a = aw.attention(np.full((200, 1), 50.0))["att"]
    assert np.isnan(a).all()


def test_views_matrix_fills_zero_after_the_first_day_and_maps_segments():
    P = panel(np.zeros((5, 2)))
    P.bases[1] = "C0"   # a second segment of the same coin
    cv = pl.DataFrame({"base": ["C0", "C0"], "day_us": [int(P.days[1]), int(P.days[3])], "views": [10, 30]})
    V = aw.views_matrix(P, cv)
    assert np.isnan(V[0, 0]) and V[1:, 0].tolist() == [10, 0, 30, 0]
    assert np.array_equal(V[1:, 1], V[1:, 0])


def test_spikes_compare_with_the_past_only():
    a = np.r_[np.linspace(0, 1, 300), [2.0, 0.1]]
    s = aw.spikes(a)
    assert not s[:aw.SPIKE_MIN].any()
    assert s[300] and not s[301]


def test_long_short_weights_halves_on_rebalance_days_only():
    T, N = 14, 10
    P = panel(np.zeros((T, N)))
    s = np.tile(np.arange(N, dtype=float), (T, 1))
    W = aw.ls_weights(P, s, np.ones((T, N), dtype=bool))
    reb = np.flatnonzero(np.isfinite(W).all(1))
    assert len(reb) == 2 and reb[1] - reb[0] == 7
    w = W[reb[0]]
    assert w[0] == pytest.approx(0.25) and w[1] == pytest.approx(0.25)     # lowest attention long
    assert w[-1] == pytest.approx(-0.25) and w[-2] == pytest.approx(-0.25)  # highest attention short
    assert w.sum() == pytest.approx(0.0)


# ---------------------------------------------------------------- intraday_tsmom

def hourly(days: int, start: int = us(2024, 1, 1)) -> pl.DataFrame:
    t = start + np.arange(days * 24, dtype=np.int64) * HOUR_US
    close = 100.0 + np.arange(days * 24, dtype=float)
    return pl.DataFrame({"open_time_us": t, "close": close})


def test_hour_closes_pick_the_right_bars():
    h = hourly(3)
    days = us(2024, 1, 1) + np.arange(3, dtype=np.int64) * DAY_US
    px = it.hour_closes(h, days)
    # Day 1: 00:00 is the close of day 0's 23:00 bar (index 23), 22:00 the close of the 21:00 bar (24 + 21).
    assert px["p0"][1] == 100 + 23 and px["p22"][1] == 100 + 45 and px["p23"][1] == 100 + 46
    assert px["p24"][1] == 100 + 47 and px["p22_prev"][1] == 100 + 21
    assert np.isnan(px["p0"][0])


def test_rules_and_round_trip_costs():
    px = {k: np.array([v]) for k, v in {"p0": 100.0, "p22": 110.0, "p23": 99.0, "p24": 121.0, "p22_prev": 120.0}.items()}
    sA, rA, _ = it.signal_and_ret(px, "A")
    sB, _, _ = it.signal_and_ret(px, "B")
    sC, rC, _ = it.signal_and_ret(px, "C")
    assert sA[0] > 0 and sB[0] < 0 and sC[0] < 0
    d, pos = it.daily(sA, rA, 0.0005)
    assert pos[0] == 1 and d[0] == pytest.approx(0.1 - 0.001)
    d, pos = it.daily(sC, rC, 0.0005)
    assert pos[0] == -1 and d[0] == pytest.approx(-(121 / 99 - 1) - 0.001)
    d, pos = it.daily(np.array([np.nan]), rA, 0.0005)
    assert pos[0] == 0 and d[0] == 0


def test_slopes_find_momentum():
    rng = np.random.default_rng(1)
    x = rng.normal(0, 1, 2000)
    y = 0.2 * x + rng.normal(0, 1, 2000)
    b, t = it.slope_nw(x, y)
    assert b == pytest.approx(0.2, abs=0.06) and t > 4
    b2, t2 = it.slope_cluster(x, y, np.arange(2000) // 10)
    assert b2 == pytest.approx(b) and t2 > 3


# ---------------------------------------------------------------- the paper book perps_neutral

def test_paper_maps_coins_to_plain_perps_and_drops_expired_signals():
    from lab.paper import perps_neutral as pn
    m = pn.coin_to_perp({"BTCUSDT", "1000PEPEUSDT", "PEPEUSDT", "ETHUSDT"})
    assert m["BTC"] == "BTCUSDT" and m["PEPE"] == "PEPEUSDT"
    assert pn.sub_target({"valid_until_ms": 5, "weights": {"BTC": 0.1}}, 10) is None
    assert pn.sub_target({"valid_until_ms": 50, "weights": {"BTC": 0.1, "X": 0}}, 10) == {"BTC": 0.1}
    assert pn.sub_target(None, 10) is None


def test_paper_restricts_lowvol_legs_to_listed_coins_and_keeps_their_gross():
    from lab.paper import perps_neutral as pn
    w = {"A": 0.25, "B": 0.25, "C": -0.25, "D": -0.25}
    out = pn.restrict_legs(w, {"A": "PF_A", "C": "PF_C", "D": "PF_D"})
    assert out == pytest.approx({"A": 0.5, "C": -0.25, "D": -0.25})
    assert pn.restrict_legs(w, {"A": "PF_A"}) == {}


def test_paper_book_weights_start_then_erc_monthly_and_drift_between():
    from lab.paper import perps_neutral as pn
    w, how = pn.book_weights(None, [], True)
    assert w == pn.START_WEIGHTS and how.startswith("start")
    rng = np.random.default_rng(3)
    rets = [{"M4": float(a), "Carry": float(b), "LowVol": float(c)}
            for a, b, c in rng.normal(0, 1, (70, 3)) * np.array([0.01, 0.02, 0.01])]
    w, how = pn.book_weights(pn.START_WEIGHTS, rets, True)
    assert how.startswith("ERC") and sum(w.values()) == pytest.approx(1.0) and w["Carry"] < w["M4"]
    same, how = pn.book_weights({"M4": 0.5, "Carry": 0.2, "LowVol": 0.3}, rets, False)
    assert how == "drift" and same["M4"] == 0.5
    d = pn.drift({"M4": 0.5, "Carry": 0.5, "LowVol": 0.0}, {"M4": 0.10, "Carry": 0.0, "LowVol": 0.0})
    assert d["M4"] == pytest.approx(0.55 / 1.05) and sum(d.values()) == pytest.approx(1.0)


def test_paper_combines_nets_and_books_funding():
    from lab.paper import perps_neutral as pn
    tgt = pn.combined({"M4": 0.5, "Carry": 0.5, "LowVol": 0.0},
                      {"M4": {"BTC": 0.5, "X": -0.5}, "Carry": {"BTC": -0.5, "Y": 0.5}, "LowVol": {"Z": 1.0}})
    assert tgt == pytest.approx({"X": -0.25, "Y": 0.25})
    r = pn.book_return({"A": 0.5, "B": -0.5}, {"A": 100.0, "B": 100.0}, {"A": 110.0, "B": 110.0},
                       {"A": 0.001, "B": 0.001})
    assert r == pytest.approx(0.05 - 0.05 - 0.0005 + 0.0005)


def test_paper_signal_is_signed_experimental_and_autopilot_only():
    from lab.paper import perps_neutral as pn
    s = pn.signal({"BTC": 0.2, "DOGE": -0.2, "GONE": 0.1}, {"BTC": "PF_XBTUSD", "DOGE": "PF_DOGEUSD"}, 0, 10**15,
                  pn.START_WEIGHTS)
    assert s["experimental"] and s["autopilot_only"] and s["evidence"]["experimental"]
    assert s["weights"] == {"BTC": 0.2, "DOGE": -0.2} and s["venue_symbols"]["BTC"] == "PF_XBTUSD"
    assert s["lab_exposure"]["net"] == pytest.approx(0.0) and s["variant"].startswith("EXPERIMENT")
