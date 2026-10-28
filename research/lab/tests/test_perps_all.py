"""T12b's collector of every perp on Hyperliquid and Kraken Futures (lab.collect.perps_all) on recorded
answers (tests/fixtures/perps_all, taken from the public endpoints on 2026-10-28, trimmed; no network):
resume after a cut, no duplicate hours, a delisted coin keeps its last listed day, a coin before its
listing absent, the health file, the job table.

Run from research/lab:  python -m pytest tests/test_perps_all.py
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import polars as pl
import pytest

from lab.collect import perps_all as P
from lab.collect import pit
from lab.ops import jobs

FIX = Path(__file__).parent / "fixtures" / "perps_all"
REPO_TABLE = Path(__file__).resolve().parents[2] / "ops" / "jobs.yaml"
UTC = timezone.utc
H = pit.HOUR_US
NOW = int(datetime(2026, 10, 28, 19, tzinfo=UTC).timestamp() * 1e6)


def fx(name: str):
    return json.loads((FIX / name).read_text())


@pytest.fixture(autouse=True)
def lake(tmp_path, monkeypatch):
    monkeypatch.setattr(pit, "FREE", tmp_path / "free")
    monkeypatch.setattr(P, "PAGE", 4)  # the recorded histories are short: page them by 4

    def no_net(*a, **k):
        raise AssertionError("no network in tests")

    monkeypatch.setattr(urllib.request, "urlopen", no_net)
    return tmp_path / "free"


class HL:
    """Hyperliquid's info API over the recorded histories: fundingHistory from startTime, PAGE rows."""

    def __init__(self, meta=None, cut_after: int | None = None):
        self.meta = meta or fx("hl_meta.json")
        self.hist = {c: fx(f"hl_funding_{c.lower()}.json") for c in ("BTC", "MATIC", "XTEN")}
        self.calls: list[dict] = []
        self.cut_after = cut_after

    def __call__(self, url, body=None, text=False):
        if self.cut_after is not None and len(self.calls) >= self.cut_after:
            raise RuntimeError("connection cut")
        self.calls.append(body)
        if body["type"] == "meta":
            return self.meta
        rows = [r for r in self.hist[body["coin"]] if r["time"] >= body["startTime"]]
        return rows[:P.PAGE]


class KF:
    def __init__(self, instruments=None, refuse=(), answers=None):
        self.instruments = instruments or fx("kf_instruments.json")
        self.refuse = set(refuse)
        self.answers = answers or {}
        self.calls: list[str] = []

    def __call__(self, url, body=None, text=False):
        self.calls.append(url)
        if url == P.KF_INSTRUMENTS:
            return self.instruments
        sym = parse_qs(urlparse(url).query)["symbol"][0]
        if sym in self.refuse:
            raise urllib.error.HTTPError(url, 400, "Argument invalid: symbol", {}, None)
        return self.answers.get(sym) or fx(f"kf_funding_{sym.lower()}.json")


def coin_hours(venue, coin):
    return P.read_coin(venue, coin)["ts_us"].to_list()


def test_hyperliquid_backfills_every_coin_and_a_second_run_only_appends():
    f = HL()
    doc = P.run(("hyperliquid",), fetch_hl=f, now=NOW)
    assert doc["errors"] == {}
    lst = P.read_listings("hyperliquid")
    assert set(lst) == {"BTC", "MATIC", "XTEN"}
    for c in ("BTC", "XTEN"):
        hours = coin_hours("hyperliquid", c)
        assert len(hours) == len(f.hist[c]) and hours == sorted(set(hours))
        assert all(h % H == 0 for h in hours)  # settlement times floored to the hour
        assert lst[c]["caught_up"] and not lst[c]["delisted"] and lst[c]["last_day"] is None
    btc = P.read_coin("hyperliquid", "BTC")
    assert btc["backfilled"].all() and (btc["known_us"] == btc["ts_us"]).all()
    assert btc.columns == P.COLS
    h = doc["tables"]["hyperliquid"]
    assert (h["coins"], h["done"], h["left"], h["delisted"]) == (3, 3, 0, 1)
    assert json.loads((pit.FREE / "perps_all" / "health.json").read_text())["tables"]["hyperliquid"]["done"] == 3
    # an hour later: one page for each live coin, nothing for the closed MATIC, nothing stored twice
    f2 = HL()
    f2.hist["XTEN"] = f.hist["XTEN"] + [{"coin": "XTEN", "fundingRate": "0.0000125", "premium": "0.0001",
                                          "time": f.hist["XTEN"][-1]["time"] + H // 1000 - 3}]
    P.run(("hyperliquid",), fetch_hl=f2, now=NOW + H)
    assert [b.get("coin") for b in f2.calls] == [None, "BTC", "XTEN"]
    xten = P.read_coin("hyperliquid", "XTEN")
    assert xten.height == len(f.hist["XTEN"]) + 1 and xten["ts_us"].n_unique() == xten.height


def test_resume_after_a_cut_gives_the_same_table_without_duplicate_hours():
    whole = HL()
    P.run(("hyperliquid",), fetch_hl=whole, now=NOW)
    ref = {c: P.read_coin("hyperliquid", c).drop("collected_us") for c in ("BTC", "MATIC", "XTEN")}
    for p in (pit.FREE / "perps_all").rglob("*"):
        if p.is_file():
            p.unlink()
    # a request cap that stops inside BTC's backfill, then a connection that dies mid-run
    doc = P.run(("hyperliquid",), fetch_hl=HL(), now=NOW, hl_requests=2)
    assert doc["requests"]["hyperliquid"] == 2
    assert doc["tables"]["hyperliquid"]["left"] == 3
    assert len(coin_hours("hyperliquid", "BTC")) == P.PAGE
    doc = P.run(("hyperliquid",), fetch_hl=HL(cut_after=2), now=NOW)  # the list, one page, then the cut
    assert "hyperliquid" in doc["errors"]
    assert len(coin_hours("hyperliquid", "BTC")) == 2 * P.PAGE  # the page before the cut is kept
    assert P.read_listings("hyperliquid")["BTC"]["caught_up"] is False
    for _ in range(40):
        if P.run(("hyperliquid",), fetch_hl=HL(), now=NOW, hl_requests=3)["tables"]["hyperliquid"]["left"] == 0:
            break
    for c, df in ref.items():
        got = P.read_coin("hyperliquid", c).drop("collected_us")
        assert got.equals(df), c
        assert got["ts_us"].n_unique() == got.height
    assert P.read_listings("hyperliquid")["MATIC"]["closed"]


def test_a_delisted_coin_keeps_its_last_listed_day_and_is_not_fetched_again():
    f = HL()
    P.run(("hyperliquid",), fetch_hl=f, now=NOW)
    e = P.read_listings("hyperliquid")["MATIC"]
    last_live = int(datetime(2024, 9, 9, 8, tzinfo=UTC).timestamp() * 1e6)  # the last settlement not 0/0
    assert e["delisted"] and e["closed"]
    assert e["last_ts_us"] == last_live and e["last_day"] == "2024-09-09"
    m = P.read_coin("hyperliquid", "MATIC")
    assert int(m["ts_us"].max()) == last_live  # the 0/0 settlements after the delisting are not stored
    lst = P.read_listings("hyperliquid")
    assert "MATIC" in P.on_venue(lst, date(2024, 9, 8))
    assert "MATIC" not in P.on_venue(lst, date(2024, 9, 9))
    assert "MATIC" not in P.on_venue(lst, date(2026, 10, 1))
    g = HL()
    P.run(("hyperliquid",), fetch_hl=g, now=NOW + 3 * H)
    assert "MATIC" not in [b.get("coin") for b in g.calls]
    assert P.read_listings("hyperliquid")["MATIC"]["last_day"] == "2024-09-09"


def test_a_coin_delisted_after_its_backfill_is_closed_at_its_last_live_hour():
    meta = fx("hl_meta.json")
    live = {"universe": [dict(u, isDelisted=False) if u["name"] == "MATIC" else u for u in meta["universe"]]}
    first = HL(meta=live)
    first.hist["MATIC"] = first.hist["MATIC"][:-10]  # seen live up to its last settlement
    P.run(("hyperliquid",), fetch_hl=first, now=NOW)
    assert not P.read_listings("hyperliquid")["MATIC"]["delisted"]
    P.run(("hyperliquid",), fetch_hl=HL(), now=NOW + H)  # now listed as delisted, 0/0 rows since
    e = P.read_listings("hyperliquid")["MATIC"]
    assert e["delisted"] and e["closed"] and e["last_day"] == "2024-09-09"
    assert P.read_coin("hyperliquid", "MATIC").height == len(first.hist["MATIC"])


def test_a_coin_before_its_listing_is_absent():
    P.run(fetch_hl=HL(), fetch_kf=KF(), now=NOW)
    hl = P.read_listings("hyperliquid")
    assert hl["XTEN"]["first_day"] == "2026-10-27"
    assert "XTEN" not in P.on_venue(hl, date(2026, 10, 27))
    assert "XTEN" in P.on_venue(hl, date(2026, 10, 28))
    assert "BTC" not in P.on_venue(hl, date(2023, 5, 12)) and "BTC" in P.on_venue(hl, date(2023, 5, 13))
    assert P.on_venue(hl, date(2023, 1, 1)) == []
    kf = P.read_listings("kraken_futures")
    assert set(kf) == {"PF_XBTUSD", "PF_EWZUSD"}  # PI_ (inverse) contracts are not perps of the list
    ewz = kf["PF_EWZUSD"]
    first_rate = int(datetime(2026, 10, 21, 12, tzinfo=UTC).timestamp() * 1e6)
    assert ewz["base"] == "EWZ" and ewz["first_ts_us"] == first_rate > ewz["opening_us"]  # opened 11:26
    assert ewz["first_day"] == "2026-10-21"
    assert "PF_EWZUSD" not in P.on_venue(kf, date(2026, 10, 21))
    assert "PF_EWZUSD" in P.on_venue(kf, date(2026, 10, 22))


def test_kraken_merges_runs_refreshes_politely_and_closes_a_delisted_symbol():
    f = KF()
    doc = P.run(("kraken_futures",), fetch_kf=f, now=NOW)
    assert doc["errors"] == {} and doc["tables"]["kraken_futures"]["done"] == 2
    xbt = P.read_coin("kraken_futures", "PF_XBTUSD")
    assert xbt.height == 30 and xbt["ts_us"].n_unique() == 30 and xbt["premium"].is_null().all()
    assert xbt["funding_rate"][-1] == pytest.approx(4.073275e-06)
    # within KF_REFRESH_US nothing is fetched but the list
    g = KF()
    P.run(("kraken_futures",), fetch_kf=g, now=NOW + H)
    assert g.calls == [P.KF_INSTRUMENTS]
    # the endpoint's window moves on: the stored history keeps the old hours, no hour twice
    moved = fx("kf_funding_pf_xbtusd.json")
    moved["rates"] = moved["rates"][10:] + [{"timestamp": "2026-10-29T08:00:00Z", "fundingRate": 0.1,
                                             "relativeFundingRate": 1e-06}]
    P.run(("kraken_futures",), fetch_kf=KF(answers={"PF_XBTUSD": moved}), now=NOW + 14 * H)
    xbt = P.read_coin("kraken_futures", "PF_XBTUSD")
    assert xbt.height == 31 and xbt["ts_us"].n_unique() == 31
    # XBT leaves the list; the endpoint refuses it: closed with its stored history and last day
    ins = fx("kf_instruments.json")
    ins["instruments"] = [i for i in ins["instruments"] if i["symbol"] != "PF_XBTUSD"]
    k = KF(instruments=ins, refuse={"PF_XBTUSD"})
    doc = P.run(("kraken_futures",), fetch_kf=k, now=NOW + 40 * H)
    e = P.read_listings("kraken_futures")["PF_XBTUSD"]
    assert e["delisted"] and e["closed"] and e["last_day"] == "2026-10-29"
    assert P.read_coin("kraken_futures", "PF_XBTUSD").height == 31
    assert "PF_XBTUSD" in P.on_venue(P.read_listings("kraken_futures"), date(2026, 10, 28))
    k2 = KF(instruments=ins)
    P.run(("kraken_futures",), fetch_kf=k2, now=NOW + 60 * H)
    assert not any("PF_XBTUSD" in u for u in k2.calls)


def test_kraken_request_cap_spreads_the_first_pass_over_runs():
    f = KF()
    doc = P.run(("kraken_futures",), fetch_kf=f, now=NOW, kf_requests=2)
    assert len(f.calls) == 2 and doc["tables"]["kraken_futures"]["left"] == 1
    P.run(("kraken_futures",), fetch_kf=KF(), now=NOW + H, kf_requests=2)
    assert P.run(("kraken_futures",), fetch_kf=KF(), now=NOW + 2 * H)["tables"]["kraken_futures"]["left"] == 0


def test_dry_run_writes_nothing():
    P.run(fetch_hl=HL(), fetch_kf=KF(), now=NOW, dry=True)
    assert not (pit.FREE / "perps_all").exists()


def test_job_dataset_and_feed_are_in_the_table_and_the_feed_reads_the_health_file(tmp_path):
    t = jobs.load_table(REPO_TABLE)
    job = t.jobs["free-perps-all"]
    assert job["command"] == "python -m lab.collect.perps_all" and job["alert"] is False
    assert job["timeout_s"] >= P.HL_REQUESTS * P.PACE_HL + P.KF_REQUESTS * P.PACE_KF
    assert any(d["path"] == "free/perps_all" for d in t.datasets)
    feed = next(f for f in t.feeds if f["name"] == "perps-all")
    assert feed["status"] == "free/perps_all/health.json" and feed["job"] == "free-perps-all"
    P.run(fetch_hl=HL(), fetch_kf=KF(), now=NOW)
    t.data = pit.FREE.parent
    now = datetime.fromtimestamp(NOW / 1e6, UTC)
    name, ok, detail = jobs.feed_check(t, feed, now)
    assert name == "feed perps-all" and not ok  # BTC's recorded history ends in 2023: a dead coin shows
    assert detail.startswith("hyperliquid") and "kraken_futures" not in detail
    P.write_health({"kraken_futures": P.venue_health("kraken_futures", NOW)}, {}, {})
    name, ok, detail = jobs.feed_check(t, feed, now)
    assert ok and "kraken_futures 1 h old, 205 rows" in detail
