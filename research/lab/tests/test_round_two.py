"""The four studies registered together on 2026-10-21 late (positioning_xs,
taker_imbalance_xs, hedged_breakout, pead_xbrl) and the USD-M metrics collector.
No network: data are synthetic or canned.

Run from research/lab:  python -m pytest tests/test_round_two.py
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import numpy as np
import polars as pl
import pytest

from lab.collect import flow, um_metrics as um
from lab.experiments import fam_common as fc
from lab.experiments import hedged_breakout as hb
from lab.experiments import pead_xbrl as px
from lab.experiments import positioning_xs as px_pos
from lab.experiments import round_two as r2
from lab.experiments import taker_imbalance_xs as ti

DAY_US = 86_400_000_000


def us(y, m, d) -> int:
    return int(datetime(y, m, d, tzinfo=timezone.utc).timestamp() * 1e6)


def panel(ret: np.ndarray, start: int = us(2024, 1, 1)) -> fc.Panel:
    T, N = ret.shape
    px_ = np.cumprod(1 + np.nan_to_num(ret), 0)
    ones = np.ones((T, N), dtype=bool)
    return fc.Panel(days=start + np.arange(T, dtype=np.int64) * DAY_US, names=[f"C{i}USDT" for i in range(N)],
                    bases=[f"C{i}" for i in range(N)], close=px_, px=px_, high=px_, low=px_, ret=ret, alive=ones,
                    traded=ones, age=np.full((T, N), 100), adv28=np.tile(np.arange(N, 0, -1) * 1e7, (T, 1)),
                    sigma=np.full((T, N), 0.02), eligible=ones, perp_ok=ones, funding=np.zeros((T, N)),
                    btc_on=np.ones(T, dtype=bool), btc=0)


# ---------------------------------------------------------------- the pool and helpers

def test_pool_counts_the_registration():
    assert r2.HAND_TRIALS == 1353 and r2.TODAY_TRIALS == 24
    p = r2.pool([0.1, -0.2, 0.3])
    assert p["n_total"] == 1353 + p["factory_trials"] + 24
    assert "1,377 hand trials" in r2.pool_line(p)


def test_roll_handles_series_shorter_than_the_window():
    a = np.arange(76.0)[:, None]
    out = r2.roll(a, 90, 60)
    assert np.isnan(out[58, 0]) and out[70, 0] == pytest.approx(35.0)
    assert np.isnan(r2.roll(np.arange(30.0)[:, None], 90, 60)).all()
    assert r2.roll(np.arange(200.0)[:, None], 90, 60)[100, 0] == pytest.approx(55.5)


def test_zscore_uses_only_earlier_values():
    x = np.r_[np.tile([0.0, 2.0], 50), [11.0]][:, None]
    z = r2.zscore_own(x, 90, 60)
    assert z[100, 0] == pytest.approx(10.0)          # mean 1, sd 1 from the 90 days before
    x2 = x.copy()
    x2[100] = 1.0
    assert r2.zscore_own(x2, 90, 60)[99, 0] == pytest.approx(z[99, 0])


# ---------------------------------------------------------------- the metrics collector

CSV = (b"create_time,symbol,sum_open_interest,sum_open_interest_value,count_toptrader_long_short_ratio,"
       b"sum_toptrader_long_short_ratio,count_long_short_ratio,sum_taker_long_short_vol_ratio\n"
       b"2023-05-01 00:00:00,X,100,1000,2.0,1.0,2.0,1.0\n"
       b"2023-05-01 23:55:00,X,120,1300,8.0,4.0,2.0,1.0\n"
       b"2023-05-02 00:00:00,X,999,9999,9.0,9.0,9.0,9.0\n")


def test_day_row_keeps_the_day_and_takes_last_and_log_means():
    r = um.day_row(CSV, date(2023, 5, 1))
    assert r["day_us"] == us(2023, 5, 1) and r["n"] == 2
    assert r["oi"] == 120 and r["oi_value"] == 1300
    assert r["top_acct"] == pytest.approx(np.log(4.0)) and r["taker"] == pytest.approx(0.0)
    empty = um.day_row(None, date(2023, 5, 1))
    assert empty["n"] == 0 and np.isnan(empty["oi"])


def test_plan_takes_the_liquid_perps_with_a_lead():
    days = [us(2023, 1, 1) + i * DAY_US for i in range(10)]
    rows = []
    for d in days:
        rows += [{"day": d, "perp": "AUSDT", "perp_adv28": 3.0, "eligible": True},
                 {"day": d, "perp": "BUSDT", "perp_adv28": 2.0, "eligible": True},
                 {"day": d, "perp": "CUSDT", "perp_adv28": 1.0, "eligible": True}]
    p = um.plan(pl.DataFrame(rows), date(2021, 12, 1), 2, date(2023, 1, 20))
    assert set(p) == {"AUSDT", "BUSDT"}
    assert p["AUSDT"] == (date(2022, 9, 23), date(2023, 1, 20))     # 100 days lead, still ranked: to `until`


def test_collect_saves_rows_and_skips_stored_days(tmp_path, monkeypatch):
    monkeypatch.setattr(flow, "FLOW", tmp_path)
    monkeypatch.setattr(um, "FLOW", tmp_path)
    asked = []

    def fetch(url, pacer):
        asked.append(url)
        return CSV if "2023-05-01" in url else None

    got = um.collect("XUSDT", [date(2023, 5, 1), date(2023, 5, 2)], um.Pacer(1000), fetch)
    assert got == 1 and len(asked) == 2
    assert um.todo("XUSDT", date(2023, 5, 1), date(2023, 5, 3)) == [date(2023, 5, 3)]
    m = um.load()
    assert m.height == 1 and m["perp"][0] == "XUSDT"


# ---------------------------------------------------------------- positioning_xs

def test_crowding_needs_all_five_and_is_traded_contrarian():
    rng = np.random.default_rng(0)
    T = 200
    arrs = {c: rng.normal(0, 1, (T, 1)) for c in ("top_acct", "top_pos", "taker")}
    arrs["oi"] = np.exp(np.cumsum(rng.normal(0, 0.01, (T, 1)), 0))
    for c in ("top_acct", "top_pos", "taker"):
        arrs[c][150] = 10.0
    out = px_pos.signals(arrs)
    assert out["s_crowd"][150] < -1.5 and out["s_acct"][150] < -5
    assert np.isnan(out["s_crowd"][:60]).all()
    arrs["taker"][160] = np.nan
    assert np.isnan(px_pos.signals(arrs)["s_crowd"][160])


# ---------------------------------------------------------------- taker_imbalance_xs

def test_abnormal_share_against_the_days_before_the_window():
    T = 120
    vol = np.ones((T, 1))
    buy = np.full((T, 1), 0.5)
    buy[110] = 0.9
    out = ti.abnormal(buy / vol, buy, vol)
    assert out["s_A1"][110, 0] == pytest.approx(0.4) and out["s_A1"][109, 0] == pytest.approx(0.0)
    assert out["s_A1"][111, 0] == pytest.approx(0.5 - (0.5 * 89 + 0.9) / 90)
    assert out["s_A7"][110, 0] == pytest.approx(0.4 / 7)
    assert np.isnan(out["s_A1"][50, 0])


# ---------------------------------------------------------------- hedged_breakout

def test_coin_betas_and_the_hedge():
    rng = np.random.default_rng(2)
    T = 120
    b = rng.normal(0, 0.03, T)
    ret = np.column_stack([b, 2 * b + rng.normal(0, 0.001, T), rng.normal(0, 0.02, T)])
    ret[0] = np.nan
    P = panel(ret)
    beta = hb.coin_betas(P)
    assert np.isnan(beta[30, 1]) and beta[100, 1] == pytest.approx(2.0, abs=0.05) and beta[100, 0] == 1.0
    held = np.zeros((T, 3))
    held[100] = [0.0, 0.1, 0.1]
    beta[100, 2] = np.nan
    h = hb.hedge_ratio(held, beta)
    assert h[100] == pytest.approx(-(0.1 * beta[100, 1] + 0.1 * beta[100, 1])) and h[99] == 0.0


def test_hedge_leg_short_receives_positive_funding_and_trades_its_changes():
    ret = np.zeros((4, 1))
    ret[2, 0] = 0.10
    P = panel(ret)
    P.funding[:, 0] = 0.001
    h = np.array([0.0, -0.5, -0.5, 0.0])
    o = hb.hedge_leg(P, h, np.zeros(4))
    assert o["ret"][2] == pytest.approx(-0.5 * (0.10 - 0.001))
    assert o["tov"][1] == pytest.approx(0.5)
    assert o["funding"][1] == pytest.approx(0.0005)


# ---------------------------------------------------------------- pead_xbrl

D = np.datetime64


def rows_(*r):
    return [(rank, D(s), D(e), v, a, D(f)) for rank, s, e, v, a, f in r]


def test_facts_prefer_the_filings_own_value_and_stay_point_in_time():
    F = px.Facts(rows_((0, "2020-01-01", "2020-03-31", 1.0, "A1", "2020-05-01"),
                       (0, "2020-01-01", "2020-03-31", 0.25, "A2", "2021-05-01"),      # split-adjusted comparative
                       (2, "2020-01-01", "2020-03-31", 9.0, "A2", "2021-05-01")))      # basic, ranked below
    assert F.own(px.Q_DAYS, D("2020-03-31"), "A1") == 1.0
    assert F.own(px.Q_DAYS, D("2020-03-31"), "ZZ") == 1.0                              # earliest filed
    assert F.asof(px.Q_DAYS, D("2020-03-31"), "A2", D("2021-05-01")) == 0.25
    assert F.asof(px.Q_DAYS, D("2020-03-31"), "B", D("2020-12-31")) == 1.0
    assert F.asof(px.Q_DAYS, D("2020-03-31"), "B", D("2020-04-30")) is None


def test_q4_is_derived_from_the_year_minus_nine_months():
    F = px.Facts(rows_((0, "2020-01-01", "2020-09-30", 3.0, "Q3", "2020-11-01"),
                       (0, "2020-01-01", "2020-12-31", 5.0, "K", "2021-02-15")))
    v, der = px.quarter_eps(F, D("2020-12-31"), "K", D("2021-02-15"), "10-K", False)
    assert v == pytest.approx(2.0) and der
    assert px.quarter_eps(F, D("2020-12-31"), "K", D("2021-02-15"), "10-Q", False) == (None, False)


def test_sue_scales_by_the_previous_eight_differences(monkeypatch):
    ends = [np.datetime64("2015-03-31") + np.timedelta64(91 * i, "D") for i in range(16)]
    rows, fl = [], []
    for i, e in enumerate(ends):
        a = f"A{i}"
        f = e + np.timedelta64(30, "D")
        rows.append((0, e - np.timedelta64(90, "D"), e, 1.0 + (0.1 if i % 2 else 0.0) + (5.0 if i == 15 else 0.0), a, f))
        rows.append((0, e - np.timedelta64(455, "D"), e - np.timedelta64(365, "D"), 1.0, a, f))
        fl.append((f, e, a, "10-Q"))
    monkeypatch.setattr(px, "eps_facts", lambda cik: rows)
    monkeypatch.setattr(px, "filings", lambda cik: fl)
    ev = px.sue_events(1)
    assert len(ev) == 16 and np.isnan(ev[5]["sue"]) and np.isfinite(ev[6]["sue"])
    prev = [0.0 if i % 2 == 0 else 0.1 for i in range(7, 15)]
    assert ev[15]["sue"] == pytest.approx(5.1 / np.std(prev, ddof=1))


def test_deciles_use_only_earlier_events():
    base = np.datetime64("2015-01-01")
    evs = [{"filed": base + np.timedelta64(i, "D"), "sue": float(i % 50)} for i in range(300)]
    evs.append({"filed": base + np.timedelta64(300, "D"), "sue": 1e9})
    px.deciles(evs, None)
    assert evs[50]["dec"] == "" and evs[-1]["dec"] == "top" and evs[-1]["decile"] == 10
    assert sum(e["dec"] == "bottom" for e in evs[150:300]) > 0


def test_targets_enter_on_the_second_session_and_cap_weights():
    evs = [{"dec": "top", "f": 10, "j": 0}, {"dec": "top", "f": 10, "j": 1}, {"dec": "bottom", "f": 10, "j": 2}]
    t = px.targets(evs, "top", 5, 30, 3)
    assert min(t) == 11                                     # decided at the close of f+1, filled at f+2
    assert t[11].tolist() == [0.1, 0.1, 0.0]                # capped at 10 %
    assert 16 in t and t[16].sum() == 0.0                    # out at the open of f+2+H
    assert set(t) == {11, 16}
