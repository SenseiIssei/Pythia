"""Funding backfill: the monthly archive plus REST for the days it does not cover
yet. No network: the fixtures are real `GET /fapi/v1/fundingRate` replies
(BTCUSDT every 8 h, LPTUSDT every 4 h, 2026-10-01 to 2026-10-03)."""

from __future__ import annotations

import asyncio
import json
from datetime import date, timedelta
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from recorder import backfill as bf

FIX = Path(__file__).parent / "fixtures"
OCT = [date(2026, 10, 1), date(2026, 10, 2), date(2026, 10, 3)]


def rows(symbol: str) -> list[dict]:
    return json.loads((FIX / f"binance_um_fundingRate_{symbol}.json").read_text(encoding="utf-8"))


def archive_csv(times_ms: list[int], rate: float = 0.0001) -> bytes:
    """A monthly fundingRate archive as data.binance.vision ships it."""
    lines = ["calc_time,funding_interval_hours,last_funding_rate"]
    lines += [f"{t},8,{rate:.8f}" for t in times_ms]
    return ("\n".join(lines) + "\n").encode()


class FakeResponse:
    def __init__(self, status: int, body, headers: dict | None = None):
        self.status = status
        self.body = body
        self.headers = headers or {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def raise_for_status(self) -> None:
        if self.status >= 400:
            raise RuntimeError(f"HTTP {self.status}")

    async def json(self):
        return self.body


class FakeHttp:
    """Answers fundingRate like Binance: rows in [startTime, endTime], at most `limit`."""

    def __init__(self, data: list[dict], limited: int = 0):
        self.data = sorted(data, key=lambda r: r["fundingTime"])
        self.calls: list[dict] = []
        self.limited = limited

    def get(self, url: str, params: dict):
        self.calls.append({"url": url, **params})
        if self.limited:
            self.limited -= 1
            return FakeResponse(429, [], {"Retry-After": "0"})
        hit = [r for r in self.data if params["startTime"] <= r["fundingTime"] <= params["endTime"]]
        return FakeResponse(200, hit[: params["limit"]])


class FakeFetcher(bf.Fetcher):
    """Serves monthly archives from a dict, records every URL asked for."""

    def __init__(self, archives: dict[str, bytes]):
        self.archives = archives
        self.urls: list[str] = []
        self.stats = {"ok": 0, "missing": 0, "bad_checksum": 0, "skipped": 0}

    async def zip_csv(self, url: str) -> bytes | None:
        self.urls.append(url)
        if url in self.archives:
            return self.archives[url]
        self.stats["missing"] += 1
        return None


def rest(http: FakeHttp, stats: dict) -> bf.FundingRest:
    return bf.FundingRest(http, bf.Pacer(0.0), stats, base="https://fapi.test/fapi/v1")


def test_rest_rows_keep_the_archive_keys_and_split_by_utc_day():
    t = bf.funding_days(rows("BTCUSDT"))
    assert sorted(t) == OCT
    assert [x.num_rows for x in t.values()] == [3, 3, 3]
    first = t[OCT[0]]
    # fundingTime is the archive's calc_time to the millisecond (1790812800001 = 2026-10-01 00:00:00.001).
    assert first["funding_time_us"][0].as_py() == 1790812800001 * 1000
    assert first["funding_rate"][0].as_py() == pytest.approx(0.00007981)
    assert set(first["interval_hours"].to_pylist()) == {8}


def test_interval_comes_from_the_settlement_spacing():
    t = bf.funding_days(rows("LPTUSDT"))
    assert [x.num_rows for x in t.values()] == [6, 6, 6]
    assert {h for x in t.values() for h in x["interval_hours"].to_pylist()} == {4}
    lone = bf.funding_days(rows("BTCUSDT")[:1])
    assert lone[OCT[0]]["interval_hours"].to_pylist() == [8]


def test_rest_day_files_have_the_monthly_archive_schema(tmp_path):
    archive = bf.norm_funding(bf.read_csv(archive_csv([1790812800001]), None))
    assert bf.funding_days(rows("BTCUSDT"))[OCT[0]].schema == archive.schema


def test_gap_is_finished_days_without_a_month_or_day_file(tmp_path):
    today = date(2026, 10, 4)
    # Last month's archive is not out yet: all of September plus October 1 to 3.
    gap = bf.funding_gap(tmp_path, today)
    assert gap[0] == date(2026, 9, 1) and gap[-1] == date(2026, 10, 3) and len(gap) == 33
    (tmp_path / "2026-09.parquet").touch()
    (tmp_path / "2026-10-01.parquet").touch()
    assert bf.funding_gap(tmp_path, today) == OCT[1:]
    # Today is never in it: its settlements are not all in yet.
    assert bf.funding_gap(tmp_path, date(2026, 10, 1)) == []
    # Nothing before `since` (a perp listed on the 3rd has nothing to ask for before).
    assert bf.funding_gap(tmp_path, today, since=date(2026, 10, 3)) == [OCT[2]]


def test_fill_writes_the_gap_days_once(tmp_path):
    (tmp_path / "2026-09.parquet").touch()
    http, f = FakeHttp(rows("BTCUSDT")), FakeFetcher({})
    r = rest(http, f.stats)
    asyncio.run(bf.fill_funding_from_rest(f, r, tmp_path, "BTCUSDT", today=date(2026, 10, 4)))
    assert len(http.calls) == 1
    call = http.calls[0]
    assert call["url"] == "https://fapi.test/fapi/v1/fundingRate"
    assert call["symbol"] == "BTCUSDT" and call["limit"] == 1000
    assert call["startTime"] == 1790812800000            # 2026-10-01 00:00 UTC
    assert call["endTime"] == 1791072000000 - 1          # up to the end of 2026-10-03
    assert sorted(p.name for p in tmp_path.glob("2026-10-*.parquet")) == [f"{d}.parquet" for d in OCT]
    assert pq.read_table(tmp_path / "2026-10-02.parquet").num_rows == 3
    assert f.stats["rest_days"] == 3 and f.stats["rest"] == 1
    # The next run finds nothing to ask for.
    asyncio.run(bf.fill_funding_from_rest(f, r, tmp_path, "BTCUSDT", today=date(2026, 10, 4)))
    assert len(http.calls) == 1


def test_days_without_settlements_get_no_file(tmp_path):
    # Listed during October 2: nothing settled on the 1st, so no file for it.
    (tmp_path / "2026-09.parquet").touch()
    later = [r for r in rows("BTCUSDT") if r["fundingTime"] >= 1790899200000]
    f = FakeFetcher({})
    asyncio.run(bf.fill_funding_from_rest(f, rest(FakeHttp(later), f.stats), tmp_path, "X", today=date(2026, 10, 4)))
    assert sorted(p.name for p in tmp_path.glob("*-*-*.parquet")) == ["2026-10-02.parquet", "2026-10-03.parquet"]


def test_history_pages_through_full_replies(monkeypatch):
    monkeypatch.setattr(bf, "REST_LIMIT", 4)
    http = FakeHttp(rows("LPTUSDT"))
    got = asyncio.run(rest(http, {}).history("LPTUSDT", 1790812800000, 1791072000000 - 1))
    assert len(got) == 18
    assert len({r["fundingTime"] for r in got}) == 18
    assert len(http.calls) == 5                     # 4 + 4 + 4 + 4 + 2
    assert http.calls[1]["startTime"] == got[3]["fundingTime"] + 1


def test_rate_limit_waits_and_retries():
    http = FakeHttp(rows("BTCUSDT"), limited=2)
    stats: dict = {}
    got = asyncio.run(rest(http, stats).history("BTCUSDT", 1790812800000, 1791072000000 - 1))
    assert len(got) == 9 and len(http.calls) == 3 and stats["rest"] == 3


def test_rate_limit_gives_up_after_the_attempts(monkeypatch):
    monkeypatch.setattr(bf, "REST_ATTEMPTS", 2)
    http = FakeHttp(rows("BTCUSDT"), limited=5)
    with pytest.raises(RuntimeError):
        asyncio.run(rest(http, {}).history("BTCUSDT", 0, 1))
    assert len(http.calls) == 2


def test_pacer_spaces_requests():
    async def three():
        p = bf.Pacer(0.05)
        loop = asyncio.get_running_loop()
        t0 = loop.time()
        for _ in range(3):
            await p.wait()
        return loop.time() - t0
    assert asyncio.run(three()) >= 0.09


def test_monthly_archive_replaces_the_rest_days_and_daily_archives_are_not_asked_for(tmp_path):
    today = date.today()
    this_month = today.replace(day=1)
    prev = (this_month - timedelta(days=1)).replace(day=1)
    label = prev.strftime("%Y-%m")
    for d in (prev, prev + timedelta(days=1)):
        pq.write_table(bf.funding_days(rows("BTCUSDT"))[OCT[0]], tmp_path / f"{d}.parquet")
    running = tmp_path / f"{this_month}.parquet"
    pq.write_table(bf.funding_days(rows("BTCUSDT"))[OCT[0]], running)

    url = f"{bf.BASE}/futures/um/monthly/fundingRate/BTCUSDT/BTCUSDT-fundingRate-{label}.zip"
    f = FakeFetcher({url: archive_csv([bf.day_ms(prev), bf.day_ms(prev) + 8 * bf.HOUR_MS])})
    asyncio.run(bf.funding_job(f, None, tmp_path, "BTCUSDT", prev))

    assert (tmp_path / f"{label}.parquet").exists()
    assert not list(tmp_path.glob(f"{label}-*.parquet"))   # the REST days of that month are gone
    assert running.exists()                                 # the running month's are not
    assert f.urls == [url]                                  # no daily fundingRate archive (they do not exist)
    month = pq.read_table(tmp_path / f"{label}.parquet")
    assert month.schema == pq.read_table(running).schema
    # Every reader globs *.parquet in the folder: month file and day files concatenate as they are.
    assert pa.concat_tables([month, pq.read_table(running)]).num_rows == 5


def test_unpublished_last_month_keeps_its_rest_days(tmp_path):
    this_month = date.today().replace(day=1)
    prev = (this_month - timedelta(days=1)).replace(day=1)
    day = tmp_path / f"{prev}.parquet"
    pq.write_table(bf.funding_days(rows("BTCUSDT"))[OCT[0]], day)
    f = FakeFetcher({})
    asyncio.run(bf.funding_job(f, None, tmp_path, "BTCUSDT", prev))
    assert day.exists()
    assert not (tmp_path / f"{prev.strftime('%Y-%m')}.absent").exists()
    assert len(f.urls) == 1 and "/monthly/" in f.urls[0]
