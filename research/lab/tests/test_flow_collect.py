"""The flow collector on canned answers: paging, closed bars only, merging, the skew maths.

Run from research/lab:  python -m pytest tests/test_flow_collect.py
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import polars as pl
import pytest

from lab.collect import flow

UTC = timezone.utc


def q(url: str) -> dict:
    return {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}


def test_coinbase_pages_of_300_hours_and_columns():
    calls = []

    def fetch(url):
        p = q(url)
        calls.append(p)
        a = datetime.fromisoformat(p["start"].replace("Z", "+00:00"))
        b = datetime.fromisoformat(p["end"].replace("Z", "+00:00"))
        out, t = [], a
        while t <= b:
            s = int(t.timestamp())
            out.append([s, 1.0, 3.0, 2.0, 2.5, 10.0])  # time, low, high, open, close, volume
            t += timedelta(hours=1)
        return out[::-1]  # newest first, as Coinbase answers

    df = flow.coinbase(fetch, date(2020, 1, 1), date(2020, 1, 30))
    assert len(calls) == math.ceil(30 * 24 / 300)
    assert df.height == 30 * 24
    assert df["ts_us"].is_sorted() and df["ts_us"].n_unique() == df.height
    row = df.row(0, named=True)
    assert (row["open"], row["high"], row["low"], row["close"]) == (2.0, 3.0, 1.0, 2.5)


def test_upbit_pages_back_until_since_and_drops_today():
    today = flow.today()
    days = [today - timedelta(days=i) for i in range(0, 500)]

    def fetch(url):
        p = q(url)
        to = datetime.fromisoformat(p["to"].replace("Z", "")).date() if "to" in p else today + timedelta(days=1)
        page = [d for d in days if d < to][:int(p["count"])]
        return [{"candle_date_time_utc": f"{d.isoformat()}T00:00:00", "opening_price": 1, "high_price": 2,
                 "low_price": 0.5, "trade_price": 1.5, "candle_acc_trade_price": 9} for d in page]

    since = today - timedelta(days=300)
    df = flow.upbit(fetch, since)
    assert df["day_us"].max() == flow.us_of(today - timedelta(days=1))
    assert df["day_us"].min() == flow.us_of(since)
    assert df.height == 300


def test_dvol_follows_continuation_backwards():
    end_seen = []
    base = flow.us_of(date(2021, 3, 24)) // 1000

    def fetch(url):
        p = q(url)
        e = int(p["end_timestamp"])
        end_seen.append(e)
        s = max(int(p["start_timestamp"]), e - 999 * 86_400_000)
        pts = list(range(max(s, base) // 86_400_000 * 86_400_000, e, 86_400_000))[-1000:]
        cont = pts[0] - 1 if pts and pts[0] > base else None
        return {"result": {"data": [[t, 1, 2, 0.5, 1.5] for t in pts], "continuation": cont}}

    df = flow.dvol(fetch, date(2021, 3, 1), "BTC")
    assert len(end_seen) >= 2
    assert df["day_us"].min() == base * 1000
    assert df["day_us"].n_unique() == df.height
    assert set(df["currency"]) == {"BTC"}


def test_fx_and_stables_parse():
    def fx_fetch(url):
        return {"rates": {"2020-01-02": {"KRW": 1159.87}, "2020-01-03": {"KRW": 1166.5}}}

    df = flow.fx(fx_fetch, date(2020, 1, 1), date(2020, 1, 5))
    assert df["usdkrw"].to_list() == [1159.87, 1166.5]

    def ll(url):
        v = 100.0 if "stablecoin=1" in url else 50.0 if "stablecoin=2" in url else 200.0
        return [{"date": "1577836800", "totalCirculatingUSD": {"peggedUSD": v}}]

    s = flow.stables(ll)
    assert s.row(0, named=True) == {"day_us": 1577836800000000, "usdt": 100.0, "usdc": 50.0, "total": 200.0}


def test_merge_replaces_overlap_and_resume_goes_back():
    old = pl.DataFrame({"day_us": [1, 2, 3], "x": [1.0, 2.0, 3.0]})
    new = pl.DataFrame({"day_us": [3, 4], "x": [30.0, 4.0]})
    m = flow.merge(old, new, ["day_us"])
    assert m["x"].to_list() == [1.0, 2.0, 30.0, 4.0]
    stored = pl.DataFrame({"day_us": [flow.us_of(date(2024, 5, 10))]})
    assert flow.resume_from(stored, "day_us") == date(2024, 5, 10) - timedelta(days=flow.OVERLAP_DAYS)
    assert flow.resume_from(None, "day_us") == flow.START


def _bs_iv_smile(k: float, f: float) -> float:
    # A put skew: IV rises as the strike falls.
    return 0.5 - 0.2 * math.log(k / f)


def test_skew_row_reads_a_put_skew_and_interpolates_to_30_days():
    now = datetime(2026, 10, 15, 12, tzinfo=UTC)
    f = 80_000.0
    snap = []
    for exp in (datetime(2026, 10, 30, 8, tzinfo=UTC), datetime(2026, 11, 27, 8, tzinfo=UTC)):
        code = f"{exp.day}{exp.strftime('%b').upper()}{exp.strftime('%y')}"
        for k in range(40_000, 140_001, 2_000):
            for kind in ("C", "P"):
                snap.append({"instrument_name": f"BTC-{code}-{k}-{kind}", "mark_iv": 100 * _bs_iv_smile(k, f),
                             "underlying_price": f})
    r = flow.skew_row(snap, now, "BTC")
    assert r is not None
    assert r["days"] == pytest.approx(30.0)
    assert r["rr25"] < 0 < r["put25_iv"] - r["call25_iv"]
    assert r["atm_iv"] == pytest.approx(0.5, abs=0.01)


def test_parse_instrument_and_delta():
    exp, k, kind = flow.parse_instrument("BTC-5JAN27-100000-C")
    assert (exp.year, exp.month, exp.day, exp.hour, k, kind) == (2027, 1, 5, 8, 100000.0, "C")
    assert flow.parse_instrument("BTC-PERPETUAL") is None
    c = flow.bs_delta(100.0, 100.0, 0.5, 0.25, "C")
    p = flow.bs_delta(100.0, 100.0, 0.5, 0.25, "P")
    assert c - p == pytest.approx(1.0)
    assert 0.5 < c < 0.56


def test_run_survives_one_failing_source(tmp_path, monkeypatch):
    monkeypatch.setattr(flow, "FLOW", tmp_path)

    def fetch_for(src):
        def f(url):
            if src == "fx":
                raise RuntimeError("down")
            return [{"date": "1577836800", "totalCirculatingUSD": {"peggedUSD": 1.0}}]
        return f

    res = flow.run({"fx", "stables"}, dry=False, fetch_for=fetch_for)
    assert "fx" in res["errors"] and "stables" not in res["errors"]
    assert (tmp_path / "stables.parquet").exists()
