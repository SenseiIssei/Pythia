"""D2's free data collectors on recorded answers (tests/fixtures/free_d2, no network): parsing,
paging, point in time (collected, known, backfilled, first value wins), the health file and the
health check's feed rows, the event calendar.

Run from research/lab:  python -m pytest tests/test_free_d2.py
"""

from __future__ import annotations

import json
import math
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import numpy as np
import polars as pl
import pytest

from lab.collect import defillama, deribit_vol, fear_greed, hyperliquid, macro, pit
from lab.ops import jobs

FIX = Path(__file__).parent / "fixtures" / "free_d2"
REPO_TABLE = Path(__file__).resolve().parents[2] / "ops" / "jobs.yaml"
UTC = timezone.utc
H = pit.HOUR_US
D = pit.DAY_US


def fx(name: str):
    p = FIX / name
    return p.read_text() if p.suffix == ".csv" else json.loads(p.read_text())


def us(*a) -> int:
    return int(datetime(*a, tzinfo=UTC).timestamp() * 1e6)


@pytest.fixture(autouse=True)
def lake(tmp_path, monkeypatch):
    monkeypatch.setattr(pit, "FREE", tmp_path / "free")

    def no_net(*a, **k):
        raise AssertionError("no network in tests")

    monkeypatch.setattr(urllib.request, "urlopen", no_net)
    return tmp_path / "free"


def q(url: str) -> dict:
    return {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}


# ---------------------------------------------------------------- point in time

def test_append_keeps_the_first_value_and_as_of_reads_only_what_was_known():
    a = pl.DataFrame({"ts_us": [1, 2], "x": [1.0, 2.0]})
    pit.append("s", "t", pit.stamp(a, 10), ["ts_us"])
    b = pl.DataFrame({"ts_us": [2, 3], "x": [20.0, 3.0]})  # a revision of 2 and a new 3
    out = pit.append("s", "t", pit.stamp(b, 50, known=pl.col("ts_us") + 40, backfilled=True), ["ts_us"])
    assert out == {"new": 1, "stored": 3}
    df = pit.read("s", "t")
    assert df["x"].to_list() == [1.0, 2.0, 3.0]
    assert df.columns == ["ts_us", "x", "collected_us", "known_us", "backfilled"]
    assert df["backfilled"].to_list() == [False, False, True]
    assert pit.as_of(df, 42)["ts_us"].to_list() == [1, 2]
    assert pit.as_of(df, 43)["ts_us"].to_list() == [1, 2, 3]


def test_known_is_never_before_the_time_described():
    df = pit.stamp(pl.DataFrame({"ts_us": [100]}), 10, known=5)
    assert df["known_us"].to_list() == [100]


def test_gaps_count_missing_steps_and_weekends_optionally():
    now = us(2026, 10, 26, 12)
    hours = [now - k * H for k in range(0, 48) if k not in (5, 6, 30)]
    assert pit.gaps(hours, H, now) == 3
    days = [us(2026, 10, d) for d in (19, 20, 21, 22, 23, 26)]  # Mon to Fri and Mon
    assert pit.gaps(days, D, us(2026, 10, 26, 23)) == 2
    assert pit.gaps(days, D, us(2026, 10, 26, 23), weekdays_only=True) == 0


# ---------------------------------------------------------------- Deribit

def test_surface_row_on_a_recorded_btc_book():
    book = fx("deribit_book_btc.json")
    now = datetime.fromtimestamp(book["recorded_ms"] / 1000, UTC)
    r = deribit_vol.surface_row(book["result"], now, "BTC")
    for d in deribit_vol.TENORS:
        assert 0.1 < r[f"atm_{d}"] < 1.5
        assert -0.3 < r[f"rr25_{d}"] < 0.3
        assert r[f"days_{d}"] == pytest.approx(d)
    calls = sum(o["open_interest"] for o in book["result"] if o["instrument_name"].endswith("-C"))
    puts = sum(o["open_interest"] for o in book["result"] if o["instrument_name"].endswith("-P"))
    assert (r["oi_call"], r["oi_put"]) == (pytest.approx(calls), pytest.approx(puts))
    assert r["pc_oi"] == pytest.approx(puts / calls)
    assert r["n_options"] == len(book["result"])
    assert deribit_vol.surface_row([], now, "BTC") is None


def test_dvol_pages_back_and_marks_old_candles_backfilled():
    page = fx("deribit_dvol_btc.json")["result"]["data"]
    last_open = page[-1][0] * 1000
    now = last_open + H + 30 * 60 * 1_000_000  # 30 minutes after the newest candle closed
    calls = []

    def fetch(url, body=None, text=False):
        p = q(url)
        calls.append(p)
        assert p["resolution"] == "3600"
        if len(calls) == 1:  # the recorded page, then one older page through the continuation
            return {"result": {"data": page, "continuation": page[0][0] - 1}}
        e = int(p["end_timestamp"])
        return {"result": {"data": [[e - 3_600_000, 1, 2, 0.5, 1.5]], "continuation": None}}

    df = deribit_vol.dvol(fetch, "BTC", page[0][0] - 10 * 3_600_000, now)
    assert len(calls) == 2
    assert df.height == len(page) + 1 and df["ts_us"].is_sorted()
    newest = df.row(-1, named=True)
    assert newest["backfilled"] is False and newest["known_us"] == now
    old = df.row(0, named=True)
    assert old["backfilled"] is True and old["known_us"] == old["ts_us"] + H


def test_deribit_run_end_to_end_writes_health_and_survives_one_failing_part(lake):
    book = fx("deribit_book_btc.json")
    page = fx("deribit_dvol_btc.json")["result"]["data"]
    now = book["recorded_ms"] * 1000

    def fetch(url, body=None, text=False):
        if "get_volatility_index_data" in url:
            return {"result": {"data": page, "continuation": None}}
        if q(url)["currency"] == "ETH":
            return {"result": []}
        return {"result": book["result"]}

    doc = deribit_vol.run(fetch=fetch, now=now)
    assert doc["errors"] == {}
    s = pit.read("deribit", "surface")
    assert s["currency"].to_list() == ["BTC"] and not s["backfilled"].any()
    assert json.loads((lake / "deribit" / "health.json").read_text())["tables"]["surface"]["rows"] == 1
    deribit_vol.run(fetch=fetch, now=now)  # the same snapshot again: nothing new
    assert pit.read("deribit", "dvol").height == 2 * len(page)

    def broken(url, body=None, text=False):
        if "get_volatility_index_data" in url:
            raise RuntimeError("down")
        return fetch(url)

    doc = deribit_vol.run(fetch=broken, now=now + H)
    assert "dvol" in doc["errors"] and "surface" not in doc["errors"]
    assert pit.exit_code(doc["errors"], 2) == 0 and pit.exit_code({"a": "x", "b": "y"}, 2) == 1


# ---------------------------------------------------------------- Hyperliquid

def test_hyperliquid_coins_and_snapshot():
    doc = fx("hyperliquid_ctx.json")
    coins = hyperliquid.coins_listed(doc[0], ("BTC", "ETH", "PEPE", "MATIC", "HYPE", "XTZ"))
    assert coins == ["BTC", "ETH", "kPEPE", "HYPE"]  # MATIC is delisted, XTZ not in the sample
    df = hyperliquid.contexts(doc, coins, us(2026, 10, 26, 23))
    btc = df.filter(pl.col("coin") == "BTC").row(0, named=True)
    ctx = doc[1][[u["name"] for u in doc[0]["universe"]].index("BTC")]
    assert btc["funding"] == float(ctx["funding"])
    assert btc["oi_usd"] == pytest.approx(float(ctx["openInterest"]) * float(ctx["oraclePx"]))
    assert btc["mark_premium"] == pytest.approx(float(ctx["markPx"]) / float(ctx["oraclePx"]) - 1)
    assert set(df["coin"]) == set(coins) and not df["backfilled"].any()


def test_hyperliquid_funding_pages_within_the_budget():
    rec = fx("hyperliquid_funding_btc.json")
    t0 = rec[0]["time"]
    calls = []

    def fetch(url, body=None, text=False):
        calls.append(body)
        assert body["type"] == "fundingHistory" and body["coin"] == "BTC"
        start = body["startTime"]
        # 1200 hourly settlements from t0, served 500 at a time
        return [{"coin": "BTC", "fundingRate": "0.0000125", "premium": "-0.0003", "time": t0 + k * 3_600_000}
                for k in range(1200) if t0 + k * 3_600_000 >= start][:hyperliquid.PAGE]

    now = (t0 + 1199 * 3_600_000) * 1000 + 10 * 60 * 1_000_000
    budget = [10]
    df = hyperliquid.funding(fetch, "BTC", t0, now, budget)
    assert len(calls) == 3 and budget == [7] and df.height == 1200
    assert df.row(-1, named=True)["backfilled"] is False
    assert df.row(0, named=True)["known_us"] == df.row(0, named=True)["ts_us"]
    budget = [1]
    assert hyperliquid.funding(fetch, "BTC", t0, now, budget).height == hyperliquid.PAGE and budget == [0]
    parsed = hyperliquid.funding(lambda u, b=None, text=False: rec, "BTC", t0, now, [1])
    assert parsed["funding_rate"].to_list()[0] == float(rec[0]["fundingRate"])


def test_hyperliquid_run_continues_from_what_is_stored(lake):
    doc = fx("hyperliquid_ctx.json")
    rec = fx("hyperliquid_funding_btc.json")
    seen = []

    def fetch(url, body=None, text=False):
        if body["type"] == "metaAndAssetCtxs":
            return doc
        seen.append((body["coin"], body["startTime"]))
        return [r for r in rec if r["time"] >= body["startTime"]] if body["coin"] == "BTC" else []

    now = rec[-1]["time"] * 1000 + H
    out = hyperliquid.run(fetch=fetch, now=now)
    assert out["errors"] == {}
    assert pit.read("hyperliquid", "funding").height == len(rec)
    seen.clear()
    hyperliquid.run(fetch=fetch, now=now + H)
    assert ("BTC", rec[-1]["time"] + 1) in seen
    assert pit.read("hyperliquid", "ctx").height == 2 * pit.read("hyperliquid", "ctx")["coin"].n_unique()


# ---------------------------------------------------------------- DefiLlama

def test_defillama_series_changes_and_closed_days(lake):
    usdc = fx("llama_usdc.json")
    tvl = fx("llama_tvl_solana.json")
    dex = fx("llama_dex_solana.json")
    last_day = int(usdc[-1]["date"]) * 1_000_000
    now = last_day + 3 * H  # the newest row is today's: dropped

    def fetch(url, body=None, text=False):
        if "stablecoincharts" in url:
            return usdc
        if "historicalChainTvl" in url:
            return tvl
        return dex

    out = defillama.run(fetch=fetch, now=now)
    assert out["errors"] == {}
    df = pit.read("defillama", "daily")
    assert set(df["series"]) == set(defillama.SERIES)
    assert df["ts_us"].max() < pit.us_of(pit.day_of(now))
    u = df.filter(pl.col("series") == "usdc").sort("ts_us")
    c = df.filter(pl.col("series") == "usdc_chg").sort("ts_us")
    assert c["value"][-1] == pytest.approx(u["value"][-1] - u["value"][-2])
    y = u.row(-1, named=True)  # yesterday, stored 3 hours after its close: live
    assert y["backfilled"] is False and y["known_us"] == now
    o = u.row(0, named=True)
    assert o["backfilled"] is True and o["known_us"] == o["ts_us"] + D + defillama.PUBLISH_US
    with pytest.raises(ValueError):
        defillama.chart_series({"error": "x"})


# ---------------------------------------------------------------- Fear and Greed

def test_fear_greed_history_once_then_ten_days(lake):
    rec = fx("fear_greed.json")
    asked = []

    def fetch(url, body=None, text=False):
        asked.append(q(url)["limit"])
        return rec

    newest = max(int(r["timestamp"]) for r in rec["data"]) * 1_000_000
    fear_greed.run(fetch=fetch, now=newest + 2 * H)
    fear_greed.run(fetch=fetch, now=newest + 3 * H)
    assert asked == ["0", "10"]
    df = pit.read("fear_greed", "daily")
    assert df.height == len(rec["data"]) and df["ts_us"].is_sorted()
    assert df.row(-1, named=True)["backfilled"] is False
    assert df.row(0, named=True)["known_us"] == df.row(0, named=True)["ts_us"] + fear_greed.PUBLISH_US
    assert set(df["classification"]) <= {"Extreme Fear", "Fear", "Neutral", "Greed", "Extreme Greed"}
    with pytest.raises(ValueError):
        fear_greed.parse({"metadata": {"error": "x"}}, 0)


# ---------------------------------------------------------------- Macro

def test_fred_and_yahoo_parse():
    f = macro.parse_fred(fx("fred_dgs10.csv"))
    assert date(2026, 10, 12) not in f and f[date(2026, 10, 1)] == 5.24
    with pytest.raises(ValueError):
        macro.parse_fred("<html>busy</html>")
    y = macro.parse_yahoo(fx("yahoo_gold.json"))
    assert all(d.weekday() < 5 for d in y) and len(y) > 5
    assert min(y.values()) > 1000


def test_macro_publication_times_and_today_dropped(lake):
    assert macro.published_us(date(2026, 10, 23), "fred") == us(2026, 10, 26, 22)  # Friday -> Monday
    assert macro.published_us(date(2026, 10, 22), "yahoo") == us(2026, 10, 23)
    now = us(2026, 10, 26, 23, 40)

    def fred(url, body=None, text=False):
        assert text
        return fx("fred_dgs10.csv")

    out = macro.run(fred=fred, yahoo=lambda url, body=None, text=False: fx("yahoo_gold.json"), now=now)
    assert out["errors"] == {}
    df = pit.read("macro", "daily")
    gold = df.filter(pl.col("series") == "gold")
    assert gold["ts_us"].max() == us(2026, 10, 23)  # the 26th has not ended
    ten = df.filter(pl.col("series") == "us10y").sort("ts_us")
    assert ten.row(-1, named=True)["backfilled"] is False  # Friday's, known Monday 22:00, stored 23:40
    assert ten.row(0, named=True)["backfilled"] is True
    assert set(df["source"]) == {"fred", "yahoo"}
    assert out["tables"]["daily"]["gaps"] == 0 or out["tables"]["daily"]["gaps"] <= 2


def test_calendar_file_has_the_published_schedules():
    cal = macro.calendar()
    sched = [date.fromisoformat(r["date"]) for r in cal["fomc"] if r["kind"] == "scheduled"]
    by_year = {y: sum(d.year == y for d in sched) for y in range(2017, 2028)}
    assert by_year == {y: (7 if y == 2020 else 8) for y in range(2017, 2028)}
    assert all(d.weekday() < 5 for d in sched)
    cpi = [date.fromisoformat(r["date"]) for r in cal["cpi"]]
    assert cpi == sorted(cpi) and len(set(cpi)) == len(cpi)
    assert {y: sum(d.year == y for d in cpi) for y in range(2017, 2028)} == \
        {y: (11 if y == 2025 else 12) for y in range(2017, 2028)}
    assert all(d.weekday() < 5 for d in cpi)
    assert date(2027, 12, 10) in cpi and date(2027, 12, 8) in sched


def test_calendar_features():
    f = macro.calendar_features([date(2020, 3, 14), date(2020, 3, 16), date(2024, 9, 18), date(2028, 1, 3)])
    r = f.rows(named=True)
    assert r[0]["days_to_fomc"] == 4  # the 18th as scheduled then; the 15th came unannounced
    assert r[1]["days_since_fomc"] == 1
    assert r[2]["fomc_day"] and r[2]["days_to_fomc"] == 0 and r[2]["days_since_fomc"] == 0
    assert r[3]["days_to_fomc"] is None and r[3]["days_to_cpi"] is None


# ---------------------------------------------------------------- health check rows

def feeds_table(tmp_path: Path, enabled: str = "true") -> jobs.Table:
    text = f"""
paths:
  data: {tmp_path}/data
  logs: {tmp_path}/logs
  locks: {tmp_path}/locks
  cron_dir: {tmp_path}/cron.d
  min_free_gb: 0
defaults:
  kind: host
jobs:
  - name: c
    schedule: "5 * * * *"
    command: x
    enabled: {enabled}
feeds:
  - name: src
    job: c
    status: free/src/health.json
    max_age: 3h
    max_gaps: 1
"""
    (tmp_path / "data").mkdir(exist_ok=True)
    p = tmp_path / "jobs.yaml"
    p.write_text(text)
    return jobs.load_table(p)


def write_status(tmp_path: Path, at: str, last_us: int, **h) -> None:
    p = tmp_path / "data" / "free" / "src" / "health.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    errors = h.pop("errors", {})
    t = {"rows": 10, "last_ts_us": last_us, "gaps": 0, "missing": [], "schema_ok": True, **h}
    p.write_text(json.dumps({"at": at, "tables": {"x": t}, "errors": errors}))


def test_feed_rows_green_stale_broken_and_missing(tmp_path):
    t = feeds_table(tmp_path)
    now = datetime(2026, 10, 27, 6, 0, tzinfo=UTC)
    row = lambda: jobs.feed_check(t, t.feeds[0], now)  # noqa: E731
    assert row() == ("feed src", False, "no status file free/src/health.json")
    write_status(tmp_path, "2026-10-27T05:05:00Z", us(2026, 10, 27, 5))
    name, ok, detail = row()
    assert ok and detail == "x 1 h old, 10 rows"
    write_status(tmp_path, "2026-10-27T05:05:00Z", us(2026, 10, 27, 1))
    assert not row()[1] and "x 5 h old" in row()[2]
    write_status(tmp_path, "2026-10-26T05:05:00Z", us(2026, 10, 27, 5))
    assert not row()[1] and "last run" in row()[2]
    write_status(tmp_path, "2026-10-27T05:05:00Z", us(2026, 10, 27, 5), gaps=4)
    assert "4 gaps" in row()[2]
    write_status(tmp_path, "2026-10-27T05:05:00Z", us(2026, 10, 27, 5), schema_ok=False, missing=["close"])
    assert "lacks close" in row()[2]
    write_status(tmp_path, "2026-10-27T05:05:00Z", us(2026, 10, 27, 5), errors={"dvol": "HTTPError 403"})
    assert not row()[1] and "dvol failed" in row()[2]
    checks = {n: ok for n, ok, _ in jobs.health_checks(t, now)}
    assert checks["feed src"] is False
    off = feeds_table(tmp_path / "off", "false") if (tmp_path / "off").mkdir() is None else None
    assert not any(n.startswith("feed ") for n, _, _ in jobs.health_checks(off, now))


def test_feed_table_is_checked(tmp_path):
    t = feeds_table(tmp_path)
    p = tmp_path / "jobs.yaml"
    p.write_text(p.read_text().replace("job: c", "job: nope"))
    with pytest.raises(jobs.TableError, match="unknown job"):
        jobs.load_table(p)
    p.write_text(p.read_text().replace("job: nope", "job: c").replace("free/src", "/abs/src"))
    with pytest.raises(jobs.TableError, match="relative"):
        jobs.load_table(p)
    assert t.feeds[0]["max_age_s"] == 3 * 3600


def test_repo_feeds_match_the_collectors():
    t = jobs.load_table(REPO_TABLE)
    by = {f["job"]: f for f in t.feeds}
    for mod in (deribit_vol, hyperliquid, defillama, fear_greed, macro):
        job = next(j for j in t.jobs.values() if j["command"] == f"python -m {mod.__name__}")
        assert by[job["name"]]["status"] == f"free/{mod.SOURCE}/health.json"
        assert job["kind"] == "lab" and not job["env_files"] and not job["volumes"] and job["network"] is None
    assert any(d["path"] == "free" for d in t.datasets)


def test_collector_writes_what_the_feed_row_reads(tmp_path, lake, monkeypatch):
    t = feeds_table(tmp_path)
    monkeypatch.setattr(pit, "FREE", tmp_path / "data" / "free")
    rec = fx("fear_greed.json")
    newest = max(int(r["timestamp"]) for r in rec["data"]) * 1_000_000
    monkeypatch.setattr(fear_greed, "SOURCE", "src")
    fear_greed.run(fetch=lambda url, body=None, text=False: rec, now=newest + 2 * H)
    at = datetime.fromtimestamp(newest / 1e6 + 2 * 3600, UTC)
    doc = json.loads((tmp_path / "data" / "free" / "src" / "health.json").read_text())
    doc["at"] = at.strftime("%Y-%m-%dT%H:%M:%SZ")
    (tmp_path / "data" / "free" / "src" / "health.json").write_text(json.dumps(doc))
    name, ok, detail = jobs.feed_check(t, t.feeds[0], at)
    assert ok and "daily 2 h old" in detail
    assert math.isclose(doc["tables"]["daily"]["rows"], len(rec["data"]))


# ---------------------------------------------------------------- the study's machinery

def test_study_asof_uses_only_known_rows_and_the_newest_described():
    from lab.experiments import data_free_d2 as st
    rows = pl.DataFrame({"ts_us": [1, 2, 3], "known_us": [10, 30, 20], "value": [1.0, 2.0, 3.0]})
    # at 25 rows 1 and 3 are known (3 is newer); at 35 row 2 arrives late but describes an older time
    assert st.asof_values(rows, [5, 15, 25, 35]).tolist()[1:] == [1.0, 3.0, 3.0]
    assert math.isnan(st.asof_values(rows, [5])[0])


def test_study_purged_ic_finds_a_planted_signal_and_not_noise():
    from lab.experiments import data_free_d2 as st
    rng = np.random.default_rng(3)
    x = rng.normal(size=2000)
    y = 0.3 * x + rng.normal(size=2000)
    r = st.purged_ic(x, y, 1)
    assert 0.2 < r["ic"] < 0.4 and r["p"] < 1e-6 and r["n_sub"] == 1000
    noise = st.purged_ic(rng.normal(size=2000), y, 7)
    assert abs(noise["t"]) < 3 and noise["n_sub"] == 250
    assert st.purged_ic(x[:150], y[:150], 1) is None  # too short
    # the partial IC: y driven by z alone, x a noisy copy of z, nothing left once z is out
    z = rng.normal(size=2000)
    y2, x2 = z + 0.1 * rng.normal(size=2000), z + rng.normal(size=2000)
    assert st.purged_ic(x2, y2, 1)["ic"] > 0.5 and abs(st.purged_ic(x2, y2, 1, z)["ic"]) < 0.1


def test_study_multiple_test_adjustments():
    from lab.experiments import data_free_d2 as st
    ps = [0.01, 0.04, 0.03, 0.5]
    assert st.holm(ps) == pytest.approx([0.04, 0.09, 0.09, 0.5])
    assert st.bh(ps) == pytest.approx([0.04, 0.04 * 4 / 3, 0.04 * 4 / 3, 0.5])


def test_study_targets_look_forward_only():
    from lab.experiments import data_free_d2 as st
    close = np.exp(np.cumsum(np.r_[0.0, np.tile([0.01, -0.01], 40)]))
    t = st.targets([date(2020, 1, 1)] * len(close), close, 1, 30)
    assert math.isnan(t["ret"][29]) and t["ret"][30] == pytest.approx(math.log(close[31] / close[30]))
    assert t["vol"][30] == pytest.approx(1.0)
    assert math.isnan(t["ret"][-1])
