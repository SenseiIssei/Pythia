"""C2 (results/perps_books_c2_prereg.md) on answers recorded from the public endpoints on 2026-11-23
(tests/fixtures/perps_books, no network): the books cut to 20 levels best first, each book's universe, a 429 backed
off and named, the rebalance snapshots, a replay of the job over a first partial day and a full day on a fake clock
(the coverage report, the feed row green, red under 90 %), the storage budget and the job table.

Run from research/lab:  python -m pytest tests/test_perps_books_c2.py
"""

from __future__ import annotations

import io
import json
import re
import urllib.error
from datetime import datetime, timezone
from email.message import Message
from pathlib import Path

import polars as pl
import pytest

from lab import report
from lab.collect import perps_books as pb
from lab.ops import jobs

FIX = Path(__file__).parent / "fixtures" / "perps_books"
REPO_TABLE = Path(__file__).resolve().parents[2] / "ops" / "jobs.yaml"
UTC = timezone.utc
MIN_US = 60_000_000
PERPS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "1000PEPEUSDT", "DOGEUSDT", "XRPUSDT", "ADAUSDT"]


def us(*a) -> int:
    return int(datetime(*a, tzinfo=UTC).timestamp() * 1e6)


def fix(name: str):
    return json.loads((FIX / name).read_text())


class Clock:
    def __init__(self, t_us: int):
        self.t = t_us / 1e6
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.t

    def sleep(self, s: float) -> None:
        self.slept.append(s)
        self.t += s


class Answers:
    """The recorded answers by URL and body; `refuse` lists venues that answer 429 (n times, or always)."""

    def __init__(self, refuse: dict[str, int] | None = None, retry_after: str | None = None):
        self.refuse, self.retry_after = dict(refuse or {}), retry_after
        self.calls: list[str] = []

    def _429(self, venue: str, url: str):
        n = self.refuse.get(venue)
        if n is None or n == 0:
            return
        self.refuse[venue] = n - 1
        h = Message()
        if self.retry_after:
            h["Retry-After"] = self.retry_after
        raise urllib.error.HTTPError(url, 429, "Too Many Requests", h, io.BytesIO(b""))

    def __call__(self, url: str, body: dict | None = None):
        if url == pb.BINANCE_INFO:
            return fix("binance_exchange_info.json")
        if url == pb.KF_INSTRUMENTS:
            return fix("kf_instruments.json")
        if url.startswith("https://futures.kraken.com/derivatives/api/v3/orderbook"):
            self.calls.append("kf")
            self._429("kraken_futures", url)
            return fix(f"kf_book_{url.split('symbol=')[1]}.json")
        if url == pb.HL_INFO and body == {"type": "metaAndAssetCtxs"}:
            return fix("hl_meta.json")
        if url == pb.HL_INFO and body.get("type") == "l2Book":
            self.calls.append("hl")
            self._429("hyperliquid", url)
            return fix(f"hl_book_{body['coin']}.json")
        raise AssertionError(f"unexpected call {url} {body}")


@pytest.fixture(autouse=True)
def lake(tmp_path, monkeypatch):
    data = tmp_path / "data"
    monkeypatch.setenv("PYTHIA_PERPS_BOOKS", str(data / "perps_books"))
    monkeypatch.setenv("PYTHIA_CACHE", str(data / "lab-cache"))
    monkeypatch.setattr(report, "REPORTS", data / "reports")
    monkeypatch.setattr(pb, "ROOT", data)
    monkeypatch.setattr(pb, "N_LIQUID", 4)
    # the panel: the newest day without perp columns yet (as the cached file often is), the day before with them
    d1, d2 = us(2026, 11, 21), us(2026, 11, 22)
    adv = {p: 1e9 / (i + 1) for i, p in enumerate(PERPS)}
    rows = [{"day": d1, "symbol": p.replace("1000", ""), "perp": p, "perp_adv28": adv[p]} for p in PERPS]
    rows += [{"day": d2, "symbol": p.replace("1000", ""), "perp": None, "perp_adv28": None} for p in PERPS]
    (data / "lab-cache").mkdir(parents=True)
    pl.DataFrame(rows, schema={"day": pl.Int64, "symbol": pl.Utf8, "perp": pl.Utf8, "perp_adv28": pl.Float64}
                 ).write_parquet(data / "lab-cache" / "xs_daily_panel.parquet")
    # the books hold DOGE (outside the 4 most liquid) and XRP (Kraken's fixture does not list it)
    for book, pos in (("m4_perps", {"weights": {"DOGEUSDT": 0.03, "XRPUSDT": -0.02, "BTCUSDT": 0.0}}),
                      ("m4_hl_small", {"units": {"DOGE": 150.0, "XRP": -3.0}})):
        (data / "paper" / book).mkdir(parents=True)
        (data / "paper" / book / "state.json").write_text(json.dumps(pos))
    return data


def one_run(t_us: int, answers=None):
    c = Clock(t_us)
    return pb.run(fetch=answers or Answers(), sleep=c.sleep, clock=c), c


# ---------------------------------------------------------------- parsing and the universe

def test_books_are_cut_to_20_levels_best_first():
    ts, (bp, bs), (ap, az) = pb.parse_kraken(fix("kf_book_PF_XBTUSD.json"))
    raw = fix("kf_book_PF_XBTUSD.json")["orderBook"]
    assert raw["bids"][0][0] < raw["bids"][-1][0]                # Kraken sends bids worst first
    assert len(bp) == len(bs) == len(ap) == len(az) == pb.LEVELS
    assert bp == sorted(bp, reverse=True) and ap == sorted(ap) and bp[0] < ap[0]
    stamp = fix("kf_book_PF_XBTUSD.json")["serverTime"].replace("Z", "+00:00")
    assert bp[0] == max(x[0] for x in raw["bids"]) and ts == int(datetime.fromisoformat(stamp).timestamp() * 1e6)
    ts, (bp, bs), (ap, az) = pb.parse_hl(fix("hl_book_BTC.json"))
    assert len(bp) == len(ap) == pb.LEVELS and bp[0] < ap[0] and ts == fix("hl_book_BTC.json")["time"] * 1000
    with pytest.raises(ValueError):
        pb.parse_kraken({"result": "error", "error": "Unavailable"})
    with pytest.raises(ValueError):
        pb.parse_hl({"levels": []})


def test_each_book_gets_its_own_universe_with_its_held_coins():
    perps, day = pb.liquid(pb.panel_path(), pb.binance_live(fix("binance_exchange_info.json")))
    assert day == "2026-11-21" and perps == ["BTCUSDT", "ETHUSDT", "SOLUSDT", "1000PEPEUSDT"]
    d = pb.build_universe({v: pb.Venue(v, Answers(), lambda s: None) for v in pb.VENUES}, Answers())
    kf = [(u["coin"], u["symbol"], u["held"]) for u in d["kraken_futures"]]
    # PEPE is not on Kraken's fixture, ADA is suspended, XRP unlisted; DOGE is held and fell out of the 4
    assert kf == [("BTC", "PF_XBTUSD", False), ("ETH", "PF_ETHUSD", False), ("SOL", "PF_SOLUSD", False),
                  ("DOGE", "PF_DOGEUSD", True)]
    hl = [(u["symbol"], u["held"]) for u in d["hyperliquid"]]
    assert hl == [("BTC", False), ("ETH", False), ("SOL", False), ("kPEPE", False), ("DOGE", True)]


# ---------------------------------------------------------------- rate limits

def test_a_429_is_backed_off_and_recovers():
    a = Answers(refuse={"kraken_futures": 2}, retry_after="3")
    doc, c = one_run(us(2026, 11, 23, 10, 0, 3), a)
    assert doc["runs"]["kraken_futures"]["taken"] == 4 and doc["runs"]["kraken_futures"]["n429"] == 2
    assert 3.0 in c.slept and doc["errors"] == {} and "429" in doc["notes"]["kraken_futures 429"]


def test_a_venue_that_keeps_answering_429_stops_and_the_feed_row_names_it(lake):
    a = Answers(refuse={"hyperliquid": 99})
    doc, c = one_run(us(2026, 11, 23, 10, 0, 3), a)
    assert [s for s in c.slept if s >= 2] == [2.0, 4.0, 8.0]      # then the venue stops for this run
    assert a.calls.count("hl") == pb.TRIES_429 and doc["runs"]["hyperliquid"]["taken"] == 0
    assert doc["runs"]["kraken_futures"]["taken"] == 4 and doc["exit"] == 0
    assert "HTTP 429 from Hyperliquid (its rate limit)" in doc["errors"]["hyperliquid"]
    t = jobs.load_table(REPO_TABLE)
    t.data = lake
    feed = next(f for f in t.feeds if f["name"] == "perps-books")
    name, ok, detail = jobs.feed_check(t, feed, datetime(2026, 11, 23, 10, 2, tzinfo=UTC))
    assert name == "feed perps-books" and not ok and "HTTP 429 from Hyperliquid (its rate limit)" in detail


# ---------------------------------------------------------------- rebalance

def test_the_rebalance_minute_takes_the_books_venue_first():
    doc, _ = one_run(us(2026, 11, 23, 6, 0, 2))
    df = pl.read_parquet(pb.day_file("hyperliquid", "2026-11-23"))
    kf = pl.read_parquet(pb.day_file("kraken_futures", "2026-11-23"))
    assert df["rebalance"].all() and not kf["rebalance"].any()
    assert df["collected_us"].max() <= kf["collected_us"].min()  # Hyperliquid went first at 06:00
    one_run(us(2026, 11, 23, 5, 15, 2))
    kf = pl.read_parquet(pb.day_file("kraken_futures", "2026-11-23"))
    assert kf.filter(pl.col("slot_us") == us(2026, 11, 23, 5, 15))["rebalance"].all()


def test_rebalance_times_are_the_books_job_schedules():
    t = jobs.load_table(REPO_TABLE)
    for venue, job in (("kraken_futures", "paper-m4-perps"), ("hyperliquid", "paper-m4-hl-small")):
        minute, hour = t.jobs[job]["schedule"].split()[:2]
        assert pb.REBALANCE[venue] == (int(hour), int(minute)) and pb.BOOKS[venue] in t.jobs[job]["command"]


# ---------------------------------------------------------------- the job replayed

def test_job_replay_over_a_partial_and_a_full_day(lake):
    """Every 5 minutes from 22:00 on 11-22 to 00:00 on 11-24: the first day is partial and never judged, 11-23 is
    full and green; then 11-24 loses one run in five (231 of 288) and 11-25's first run turns the feed red."""
    start = us(2026, 11, 22, 22)
    slot = pb.SLOT_US
    for k in range((us(2026, 11, 24) - start) // slot + 1):
        doc, _ = one_run(start + k * slot + 3_000_000)
    assert doc["errors"] == {} and doc["exit"] == 0
    st = pb.load_state()
    assert st["first_day"] == {"kraken_futures": "2026-11-22", "hyperliquid": "2026-11-22"}
    c = pb.coverage("kraken_futures", "2026-11-23", st["days"]["2026-11-23"]["kraken_futures"])
    assert c["coverage"] == 1.0 and c["seen"] == c["expected"] == 4 and c["per_symbol_min"] == pb.SLOTS_DAY
    assert c["empty_slots"] == 0 and c["rebalance"] == 4
    md = (lake / "reports" / "perps_books" / "latest.md").read_text()
    assert re.search(r"\| Kraken Futures \| 2026-11-23 \| 4 / 4 \| 288 / 288 \| 100.0 % \| 0 \| 0 \| 0 min \| 4 \| 0 \|",
                     md)
    assert "| Hyperliquid | 2026-11-22 (first day, 24 slots) | 5 / 5 | 24 / 24 | 100.0 % |" in md  # from its first slot
    t = jobs.load_table(REPO_TABLE)
    t.data = lake
    feed = next(f for f in t.feeds if f["name"] == "perps-books")
    name, ok, detail = jobs.feed_check(t, feed, datetime(2026, 11, 24, 0, 2, tzinfo=UTC))
    assert ok and "kraken_futures 0 h old" in detail

    for k in range(1, pb.SLOTS_DAY + 1):
        if k % 5:
            doc, _ = one_run(us(2026, 11, 24) + k * slot + 3_000_000)
    red = doc["errors"]["coverage kraken_futures"]
    assert red.startswith("2026-11-24 80.") and "under 90 %" in red and "coverage hyperliquid" in doc["errors"]
    name, ok, detail = jobs.feed_check(t, feed, datetime(2026, 11, 25, 0, 2, tzinfo=UTC))
    assert not ok and "coverage kraken_futures failed: 2026-11-24 80." in detail
    md = pb.write_report(pb.load_state(), us(2026, 11, 25, 0, 2))
    assert "| Kraken Futures | 2026-11-24 | 4 / 4 | 231 / 231 | 80.2 % **red** |" in md


def test_storage_over_the_budget_is_red(monkeypatch):
    one_run(us(2026, 11, 22, 23, 50, 3))
    monkeypatch.setattr(pb, "BUDGET_MB", 0.001)
    doc, _ = one_run(us(2026, 11, 23, 0, 5, 3))
    assert doc["errors"]["storage"].startswith("2026-11-22 0 MB over both venues (budget 0.001 MB a day)")


def test_a_failed_universe_keeps_the_last_and_without_one_the_run_fails(lake):
    one_run(us(2026, 11, 22, 12, 0, 3))
    (lake / "lab-cache" / "xs_daily_panel.parquet").unlink()
    doc, _ = one_run(us(2026, 11, 23, 12, 0, 3))
    assert doc["notes"]["universe"].startswith("kept 2026-11-22") and doc["exit"] == 0
    assert doc["runs"]["kraken_futures"]["taken"] == 4
    pb.state_path().unlink()
    doc, _ = one_run(us(2026, 11, 23, 12, 5, 3))
    assert "universe" in doc["errors"] and doc["exit"] == 1


# ---------------------------------------------------------------- the table

def test_job_dataset_and_feed_are_in_the_table():
    t = jobs.load_table(REPO_TABLE)
    job = t.jobs["perps-books"]
    assert job["command"] == "python -m lab.collect.perps_books" and job["schedule"] == "*/5 * * * *"
    assert "heavy" not in job["locks"] and job["timeout_s"] > pb.DEADLINE_S and job["alert"] is False
    ds = next(d for d in t.datasets if d["name"] == "perps-books")
    assert ds["path"] == "perps_books" and ds["max_gb"] * 1000 >= 365 * pb.BUDGET_MB / 3
    feed = next(f for f in t.feeds if f["name"] == "perps-books")
    assert feed["status"] == "perps_books/health.json" and feed["job"] == "perps-books"
    assert feed["max_age_s"] == 30 * 60
