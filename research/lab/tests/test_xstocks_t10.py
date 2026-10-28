"""T10's xStocks collector on recorded answers (tests/fixtures/xstocks, SPYx on 2026-10-28, no network): the
record through lab.collect.pit, a missing field, an error page, a corporate action, the premium against the last
close known, the report next to R10's series, the job, dataset and feed row.

Run from research/lab:  python -m pytest tests/test_xstocks_t10.py
"""

from __future__ import annotations

import json
import math
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from lab import metrics
from lab import report as rp
from lab.collect import pit
from lab.collect import xstocks as xs
from lab.ops import jobs

FIX = Path(__file__).parent / "fixtures" / "xstocks"
REPO_TABLE = Path(__file__).resolve().parents[2] / "ops" / "jobs.yaml"
UTC = timezone.utc
H = pit.HOUR_US
SYMS = {"SPYx": ("SPY", "SPY")}


def fx(name: str):
    p = FIX / name
    return p.read_text() if p.suffix == ".html" else json.loads(p.read_text())


def us(*a) -> int:
    return int(datetime(*a, tzinfo=UTC).timestamp() * 1e6)


NOW = us(2026, 10, 28, 0, 0, 40)         # the 00:00 UTC run, 40 s late


@pytest.fixture(autouse=True)
def lake(tmp_path, monkeypatch):
    monkeypatch.setattr(pit, "FREE", tmp_path / "free")
    monkeypatch.setattr(rp, "REPORTS", tmp_path / "reports")
    monkeypatch.setenv("PYTHIA_TRIALS_REGISTRY", str(tmp_path / "trials" / "registry.jsonl"))
    monkeypatch.delenv("PYTHIA_RESULTS", raising=False)

    def no_net(*a, **k):
        raise AssertionError("no network in tests")

    monkeypatch.setattr(urllib.request, "urlopen", no_net)
    return tmp_path


ROUTES = {"/price-data": "price_data.json", "/multiplier": "multiplier.json", "/system/status/": "status.json",
          "/proof-of-reserves/": "proof_of_reserves.json", "/oracles/": "oracles.json",
          "/corporate-actions/history": "actions_history.json", "/corporate-actions/upcoming": "actions_upcoming.json"}


def fetcher(over: dict | None = None, seen: list | None = None):
    """The recorded answer of each endpoint; `over` replaces one by route (a value, or an exception to raise)."""
    over = over or {}

    def fetch(url, body=None, text=False):
        if seen is not None:
            seen.append(url)
        for route, name in ROUTES.items():
            if route in url:
                got = over.get(route, None)
                if isinstance(got, Exception):
                    raise got
                return got if route in over else fx(name)
        raise AssertionError(f"unexpected url {url}")
    return fetch


CLOSES = {"SPY": (np.array(["2026-10-23", "2026-10-26", "2026-10-27"], dtype="datetime64[D]"),
                  np.array([760.0, 765.37, 769.66]))}


def run(**k):
    return xs.run(fetch=k.pop("fetch", fetcher()), now=k.pop("now", NOW), syms=SYMS, closes=CLOSES, **k)


# ---------------------------------------------------------------- the record

def test_records_every_table_point_in_time():
    seen: list[str] = []
    doc = run(fetch=fetcher(seen=seen))
    assert doc["errors"] == {}
    q = pit.read("xstocks", "quotes").row(0, named=True)
    assert q["ts_us"] == us(2026, 10, 28) and q["collected_us"] == NOW and q["known_us"] == NOW and not q["backfilled"]
    assert q["quote_usd"] == 769.93 and math.isclose(q["multiplier"], 1.005714560286254)
    assert q["multiplier_next"] is None and q["multiplier_next_us"] is None and q["halted"] is False
    r = pit.read("xstocks", "reserves").row(0, named=True)
    assert math.isclose(r["shares_held"], 89778.99856414) and math.isclose(r["supply"], 88888.349881338910343)
    assert r["por_us"] == us(2026, 10, 28, 5, 8, 34) + 603_000 and json.loads(r["holdings"])[0]["provider"] == "Alpaca"
    o = pit.read("xstocks", "oracles")
    assert sorted(o["provider"].to_list()) == ["Chainlink", "Pyth"]
    a = pit.read("xstocks", "actions")
    assert a.height == 6 and set(a["status"]) == {"Initial", "Scheduled"}
    assert a["backfilled"].all() and (a["known_us"] == a["ts_us"] + H).all()      # all months old: backfilled
    assert set(doc["tables"]) == {"quotes", "reserves"} and doc["tables"]["quotes"]["schema_ok"]
    assert all("?network=Solana" in u for u in seen if "/multiplier" in u or "/oracles/" in u)
    assert any("symbol=SPYx&page=1&pageSize=100" in u for u in seen)


def test_a_second_run_keeps_the_first_values_and_adds_the_next_hour():
    run()
    run(now=NOW + 30 * 60 * 1_000_000)                      # 00:30: the same hour, the first value stays
    run(fetch=fetcher({"/price-data": {"quote": 771.0}}), now=NOW + 12 * H)
    q = pit.read("xstocks", "quotes").sort("ts_us")
    assert q["ts_us"].to_list() == [us(2026, 10, 28), us(2026, 10, 28, 12)]
    assert q["quote_usd"].to_list() == [769.93, 771.0]
    assert pit.read("xstocks", "actions").height == 6 and pit.as_of(q, NOW + H).height == 1


def test_a_missing_field_is_empty_and_a_missing_price_is_an_error():
    por = fx("proof_of_reserves.json")
    del por["sharesHeld"]
    doc = run(fetch=fetcher({"/price-data": {"quote": None}, "/proof-of-reserves/": por,
                             "/multiplier": {"error": "Validation error", "details": [{"field": "network"}]}}))
    assert "quotes" in doc["errors"] and "no quote" in doc["errors"]["quotes"]
    assert pit.read("xstocks", "quotes") is None or pit.read("xstocks", "quotes").is_empty()
    r = pit.read("xstocks", "reserves").row(0, named=True)
    assert r["shares_held"] is None and r["supply"] is not None
    # a multiplier without an answer leaves the quote, its raw unit's premium empty
    doc = run(fetch=fetcher({"/multiplier": {"error": "Validation error"}, "/system/status/": RuntimeError("down")}),
              now=NOW + 12 * H)
    q = pit.read("xstocks", "quotes").row(-1, named=True)
    assert "quotes" not in doc["errors"] and q["multiplier"] is None and q["halted"] is None
    p = xs.premium(pit.read("xstocks", "quotes"), CLOSES)
    assert p[-1]["unit_bps"] is None and p[-1]["nav_bps"] is not None
    # an action without its event id cannot be keyed: dropped, the rest kept
    h = fx("actions_history.json")
    del h["nodes"][0]["eventId"]
    assert len(xs.parse_actions("SPYx", h)) == len(h["nodes"]) - 1


def test_an_error_page_fails_its_part_only():
    page = fx("error_page.html")
    doc = run(fetch=fetcher({"/proof-of-reserves/": page, "/oracles/": {"error": "Unexpected server error"}}))
    assert set(doc["errors"]) == {"reserves", "oracles"} and "not a JSON object" in doc["errors"]["reserves"]
    assert "Unexpected server error" in doc["errors"]["oracles"]
    assert pit.read("xstocks", "quotes").height == 1 and pit.read("xstocks", "actions").height == 6
    assert pit.exit_code(doc["errors"], 4) == 0
    every = {r: RuntimeError("no answer after 5 tries") for r in ROUTES}
    assert pit.exit_code(run(fetch=fetcher(every), now=NOW + 12 * H)["errors"], 4) == 1
    with pytest.raises(ValueError, match="not a JSON object"):
        xs.parse_quote("SPYx", "SPY", page, None, None)
    with pytest.raises(ValueError, match="answered for"):
        xs.parse_reserves("QQQx", fx("proof_of_reserves.json"))


def test_a_corporate_action_split_and_its_correction():
    split = fx("actions_split.json")
    rows = {r["ca_type"]: r for r in xs.parse_actions("APHx", split) + xs.parse_actions("HONx", split)}
    fs, rs = rows["ForwardSplit"], rows["ReverseSplit"]
    assert (fs["from_units"], fs["to_units"], fs["multiplier_old"], fs["multiplier_new"]) == (1.0, 2.0, 1.0, 2.0)
    assert (rs["from_units"], rs["to_units"]) == (2.0, 1.0) and math.isclose(rs["multiplier_new"], 0.5120473566533945)
    assert fs["effective_us"] == us(2026, 9, 3, 8, 45) and fs["ts_us"] == us(2026, 9, 3, 8, 9, 43) + 581_000
    # an action created an hour before the run is live; its correction later is a new row, the first kept
    h = fx("actions_history.json")
    new = dict(h["nodes"][0], eventId="e-new", version=1, status="Initial", caType="CashDividend",
               createdTimeUtc="2026-10-27T23:00:00.000Z", grossCashflowUsd="1.9")
    run(fetch=fetcher({"/corporate-actions/history": {**h, "nodes": h["nodes"] + [new]}}))
    fix = dict(new, version=2, status="Corrected", grossCashflowUsd="2.0", createdTimeUtc="2026-10-28T10:00:00.000Z")
    changed = dict(new, grossCashflowUsd="9.9")             # a silent revision of the same key: ignored
    run(fetch=fetcher({"/corporate-actions/history": {**h, "nodes": h["nodes"] + [changed, fix]}}), now=NOW + 12 * H)
    a = pit.read("xstocks", "actions").filter(pl.col("event_id") == "e-new").sort("version")
    assert a["gross_usd"].to_list() == [1.9, 2.0] and a["status"].to_list() == ["Initial", "Corrected"]
    assert not a["backfilled"].any() and a["known_us"].to_list() == [NOW, NOW + 12 * H]


def test_paging_follows_has_next_page():
    h = fx("actions_history.json")
    pages = {1: {**h, "page": {**h["page"], "hasNextPage": True}, "nodes": h["nodes"][:2]},
             2: {**h, "page": {**h["page"], "currentPage": 2}, "nodes": h["nodes"][2:]}}
    seen = []

    def fetch(url, body=None, text=False):
        seen.append(url)
        return pages[int(url.split("page=")[1].split("&")[0])]
    assert len(xs._pages(fetch, xs.API + "/corporate-actions/history", "SPYx")) == len(h["nodes"])
    assert len(seen) == 2


def test_epoch_of_unstated_unit():
    t = us(2026, 11, 2)
    assert xs._epoch_us(t / 1e6) == t and xs._epoch_us(t / 1e3) == t and xs._epoch_us(float(t)) == t
    q = xs.parse_quote("SPYx", "SPY", {"quote": 1.0}, {"currentMultiplier": 1.01, "newMultiplier": 1.02,
                                                       "activationDateTime": t / 1e3, "reason": "Dividend"}, {})
    assert q["multiplier_next"] == 1.02 and q["multiplier_next_us"] == t and q["multiplier_reason"] == "Dividend"


def test_tokens_are_the_small_books_xstocks(tmp_path):
    assert xs.tokens() == {"SPYx": ("SPY", "SPY")}            # S2's snapshot: SPYx, not PAXG
    assert xs.tokens(tmp_path / "missing.json") == xs.DEFAULT


# ---------------------------------------------------------------- the premium

def test_premium_uses_the_last_close_known_at_the_record():
    q = pl.DataFrame({"ts_us": [us(2026, 10, 28), us(2026, 10, 28, 12), us(2026, 10, 25), us(2026, 10, 27, 22)],
                      "symbol": ["SPYx"] * 4, "underlying": ["SPY"] * 4, "quote_usd": [774.0, 775.0, 764.0, 774.5],
                      "multiplier": [1.005, 1.005, 1.005, None], "halted": [False] * 4})
    p = {r["at"]: r for r in xs.premium(q, CLOSES)}
    a = p["2026-10-28T00:00Z"]
    assert a["midnight"] and a["close_date"] == "2026-10-27"
    assert math.isclose(a["nav_bps"], round((774.0 / 769.66 - 1) * 1e4, 3))              # a quote is one share
    assert math.isclose(a["unit_bps"], round((774.0 * 1.005 / 769.66 - 1) * 1e4, 3))    # a raw unit is m shares
    assert p["2026-10-28T12:00Z"]["close_date"] == "2026-10-27" and not p["2026-10-28T12:00Z"]["midnight"]
    assert p["2026-10-25T00:00Z"]["close_date"] == "2026-10-23"                 # Sunday: Friday's close
    assert p["2026-10-27T22:00Z"]["close_date"] == "2026-10-27" and p["2026-10-27T22:00Z"]["unit_bps"] is None
    early = q.with_columns(ts_us=pl.lit(us(2026, 10, 27, 20)))
    assert {r["close_date"] for r in xs.premium(early, CLOSES)} == {"2026-10-26"}   # before 21:00 UTC: the day before
    assert xs.premium(q, {}) == []


def test_report_next_to_r10_registers_its_trial_first(lake):
    run()
    run(fetch=fetcher({"/price-data": {"quote": 772.0}}), now=NOW + 12 * H)
    d = json.loads((lake / "reports" / "xstocks" / "latest.json").read_text())
    t = d["tokens"]["SPYx"]
    assert t["midnight_nav"]["n"] == 1 and t["all_nav"]["n"] == 2 and t["all_unit"]["n"] == 2
    assert math.isclose(t["midnight_nav"]["mean_bps"], round((769.93 / 769.66 - 1) * 1e4, 2))
    assert t["r10_us"]["n"] > 100 and t["s2_close"]["n"] > 50 and t["r10_last"] >= "2026-10-01"
    assert t["actions"] == 6 and t["last_action"]["ca_type"] == "CashDividend"
    assert [r["close_date"] for r in t["side_by_side"]] == ["2026-10-27", "2026-10-27"]
    assert t["side_by_side"][1]["r10_dev_bps"] is None                        # 12:00 has no R10 counterpart
    cov = d["reserves"]["SPYx"]
    assert math.isclose(cov["cover"], round(89778.99856414 / (88888.349881338910343 * 1.005714560286254), 5))
    md = (lake / "reports" / "xstocks" / "latest.md").read_text()
    assert "SPYx on SPY" in md and "\u2014" not in md
    reg = metrics.read_registry()
    assert sum(r["id"] == xs.TRIAL["id"] for r in reg) == 1
    assert metrics.trial_pool("small")["n_trials"] == sum(int(r.get("n") or 1) for r in reg if r["family"] == "small")


def test_dry_run_writes_nothing(lake):
    doc = run(dry=True)
    assert doc["errors"] == {} and not (lake / "free").exists() and not (lake / "reports").exists()


# ---------------------------------------------------------------- the job

def test_job_dataset_and_feed_in_jobs_yaml(tmp_path):
    t = jobs.load_table(REPO_TABLE)
    j = t.jobs["xstocks-collect"]
    assert j["command"] == "python -m lab.collect.xstocks" and j["kind"] == "lab" and j.get("enabled", True)
    minute, hour = j["schedule"].split()[:2]
    assert minute == "0" and "0" in hour.split(",")                           # 00:00 UTC, the decision time
    ds = next(d for d in t.datasets if d["name"] == "xstocks")
    assert ds["path"] == "free/xstocks" and 12 < ds["max_age_h"] <= 26
    f = next(f for f in t.feeds if f["job"] == "xstocks-collect")
    assert f["status"] == f"free/{xs.SOURCE}/health.json"


def test_the_feed_row_reads_the_collectors_health(tmp_path, monkeypatch):
    t = jobs.load_table(REPO_TABLE)
    f = next(f for f in t.feeds if f["job"] == "xstocks-collect")
    monkeypatch.setattr(pit, "FREE", tmp_path / "data" / "free")
    t.data = tmp_path / "data"
    run()
    at = datetime.fromtimestamp(NOW / 1e6, UTC)
    p = tmp_path / "data" / "free" / "xstocks" / "health.json"
    doc = json.loads(p.read_text())
    doc["at"] = at.strftime("%Y-%m-%dT%H:%M:%SZ")
    p.write_text(json.dumps(doc))
    name, ok, detail = jobs.feed_check(t, f, at)
    assert ok and "quotes 0 h old" in detail and "reserves 0 h old" in detail
    late = datetime.fromtimestamp((NOW + 2 * 24 * H) / 1e6, UTC)
    assert not jobs.feed_check(t, f, late)[1]
