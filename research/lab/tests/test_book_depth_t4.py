"""T4 on small fixture files (tests/fixtures/book_depth_t4, no network): bookDepth parsing in both
formats, the checksum, a gap in the archive, resuming, the size rule, the cost of a market order,
the hourly and daily features and their leak check, the delisting table and the universe flag, and
the metrics create_time check.

Run from research/lab:  python -m pytest tests/test_book_depth_t4.py
"""

from __future__ import annotations

import hashlib
import io
import json
import math
import urllib.request
import zipfile
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import polars as pl
import pytest

from lab import universe
from lab.collect import book_depth as bd
from lab.collect import pit, um_metrics
from lab.features import book as fbook  # noqa: F401  (registers the book_depth features)
from lab.features import registry as R
from lab.leak import checks

FIX = Path(__file__).parent / "fixtures" / "book_depth_t4"
KEEPS_RAW = bd.keeps_raw                                      # the store fixture replaces it
UTC = timezone.utc
H, D = pit.HOUR_US, pit.DAY_US


def us(*a) -> int:
    return int(datetime(*a, tzinfo=UTC).timestamp() * 1e6)


def zipped(name: str, text: str) -> bytes:
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr(name, text)
    return b.getvalue()


def checksum(blob: bytes, name: str = "x.zip") -> bytes:
    return f"{hashlib.sha256(blob).hexdigest()}  {name}\n".encode()


@pytest.fixture(autouse=True)
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTHIA_BOOK_DEPTH", str(tmp_path / "book_depth"))
    monkeypatch.setattr(um_metrics, "out_dir", lambda: tmp_path / "um_metrics")
    monkeypatch.setattr(bd.um_metrics.Pacer, "wait", lambda self: None)
    monkeypatch.setattr(bd, "keeps_raw", lambda month: True)   # the raw rule has its own test

    def no_net(*a, **k):
        raise AssertionError("no network in tests")

    monkeypatch.setattr(urllib.request, "urlopen", no_net)
    R.clear()
    yield tmp_path / "book_depth"
    R.clear()


# ---------------------------------------------------------------- parsing and checksums

def test_parse_both_formats_one_row_per_snapshot_inside_the_day():
    old = bd.parse((FIX / "old.csv").read_bytes(), date(2023, 1, 1), us(2023, 7, 11), 5)
    assert old.height == 3                                    # the 2023-01-02 rows are another day
    assert old["bid_0p2"].null_count() == 3 and old["ask_0p2"].null_count() == 3
    assert old["bid_1"].to_list() == [1e6, 1.2e6, 1e6] and old["ask_5"][2] == 5e6
    assert (old["known_us"] == old["ts_us"]).all() and old["backfilled"].all()
    assert old["published_us"][0] == us(2023, 7, 11) and old["collected_us"][0] == 5
    assert old["ts_us"][0] == us(2023, 1, 1, 0, 6, 5)
    new = bd.parse((FIX / "new.csv").read_bytes(), date(2026, 10, 26), 0, 0)
    assert new.height == 2 and new["bid_0p2"].to_list() == [3e7, 2e7] and new["ask_0p2"].to_list() == [1e7, 2e7]
    assert list(new.schema) == list(bd.RAW_SCHEMA)


def test_verify_checks_the_sha256_and_a_bad_file_is_fetched_again(store):
    text = (FIX / "old.csv").read_text()
    blob = zipped("AAAUSDT-bookDepth-2023-01-01.csv", text)
    assert bd.verify(blob, checksum(blob)).decode() == text
    with pytest.raises(bd.ChecksumError):
        bd.verify(blob, checksum(blob + b"x"))
    with pytest.raises(bd.ChecksumError):
        bd.verify(blob, None)
    bad = {"n": 0}

    def fetch(url, pacer):
        if url.endswith(".CHECKSUM"):
            bad["n"] += 1
            return checksum(blob + b"corrupt")
        return blob
    listed = {date(2023, 1, 1): (len(blob), 0)}
    got = bd.collect_symbol("AAAUSDT", [date(2023, 1, 1)], listed, None, fetch)
    assert got["bad"] == 1 and got["ok"] == 0
    assert bd.manifest("AAAUSDT") == {"2023-01-01": "bad"}
    assert not bd.month_path("raw", "AAAUSDT", "2023-01").exists()
    # the next run fetches it again, and a good file then counts
    f, _ = bd.todo("AAAUSDT", (date(2023, 1, 1), date(2023, 1, 1)), listed, bd.manifest("AAAUSDT"))
    assert f == [date(2023, 1, 1)]
    got = bd.collect_symbol("AAAUSDT", f, listed, None, lambda u, p: checksum(blob) if u.endswith("CHECKSUM") else blob)
    assert got["ok"] == 1 and bd.manifest("AAAUSDT") == {"2023-01-01": "ok"}
    raw = pl.read_parquet(bd.month_path("raw", "AAAUSDT", "2023-01"))
    hourly = pl.read_parquet(bd.month_path("hourly", "AAAUSDT", "2023-01"))
    assert raw.height == 3 and hourly["n"].to_list() == [2, 1] and hourly["n_fine"].to_list() == [0, 0]


def test_listing_pages_and_a_gap_in_the_archive():
    pages = {"": (FIX / "list_1.xml").read_bytes(), "x": (FIX / "list_2.xml").read_bytes()}

    def fetch(url, pacer):
        return pages["" if url.endswith("marker=") else "x"]
    got = bd.listing("AAAUSDT", None, fetch)
    assert sorted(got) == [date(2023, 1, 1), date(2023, 1, 2), date(2023, 1, 4)]
    assert got[date(2023, 1, 2)] == (2000, us(2023, 7, 11, 8, 52, 11))
    f, gaps = bd.todo("AAAUSDT", (date(2023, 1, 1), date(2023, 1, 6)), got, {"2023-01-01": "ok"})
    assert f == [date(2023, 1, 2), date(2023, 1, 4)] and gaps == [date(2023, 1, 3)]
    est = bd.estimate({"AAAUSDT": {"listed": got, "window_days": list(got), "fetch": f, "gaps": gaps}})
    assert est["gaps"] == 1 and est["files_left"] == 2
    assert math.isclose(est["zip_gb_full"], 7000 / 1e9) and math.isclose(est["gb_left"], 6000 * bd.RATIO / 1e9)


# ---------------------------------------------------------------- the run: plan, budget, resume

def _um(tmp, sym, a: date, b: date):
    d = tmp / "um_metrics"
    d.mkdir(parents=True, exist_ok=True)
    days = [pit.us_of(a), pit.us_of(b)]
    pl.DataFrame({"day_us": days}).write_parquet(d / f"{sym}.parquet")


def _archive(days: dict[date, str]):
    """A fake archive of AAAUSDT: the listing, each day's zip and checksum."""
    blobs = {d: zipped("f.csv", t) for d, t in days.items()}
    xml = "<ListBucketResult><IsTruncated>false</IsTruncated>" + "".join(
        f"<Contents><Key>data/futures/um/daily/bookDepth/AAAUSDT/AAAUSDT-bookDepth-{d}.zip</Key>"
        f"<LastModified>{d}T09:00:00.000Z</LastModified><ETag>x</ETag><Size>{len(b)}</Size></Contents>"
        for d, b in blobs.items()) + "</ListBucketResult>"
    calls = []

    def fetch(url, pacer):
        calls.append(url)
        if "s3-ap-northeast-1" in url:
            return xml.encode() if "AAAUSDT" in url else None
        for d, b in blobs.items():
            if url.endswith(f"AAAUSDT-bookDepth-{d}.zip"):
                return b
            if url.endswith(f"AAAUSDT-bookDepth-{d}.zip.CHECKSUM"):
                return checksum(b)
        return None
    return fetch, calls


def _day_csv(day: date, k: float = 1.0) -> str:
    rows = ["timestamp,percentage,depth,notional"]
    for h in (0, 1):
        for p in (0.2, 1, 2, 3, 4, 5):
            for sgn in (-1, 1):
                rows.append(f"{day} 0{h}:00:05,{sgn * p:.2f},1,{k * p * 1e6:.1f}")
    return "\n".join(rows) + "\n"


def test_run_fetches_the_window_resumes_and_writes_health(store, tmp_path):
    days = {date(2026, 10, d): _day_csv(date(2026, 10, d)) for d in (20, 21, 23)}
    fetch, calls = _archive(days)
    _um(tmp_path, "AAAUSDT", date(2026, 10, 1), date(2026, 10, 23))
    res = bd.run(until=date(2026, 10, 23), symbols=["AAAUSDT"], fetch=fetch, delistings=False)
    assert res["fetched"] == 3 and res["gaps"] == 1 and not res["errors"]
    man = bd.manifest("AAAUSDT")
    assert man == {"2026-10-20": "ok", "2026-10-21": "ok", "2026-10-23": "ok"}
    h = pl.read_parquet(bd.month_path("hourly", "AAAUSDT", "2026-10"))
    assert h.height == 6 and h["n_fine"].sum() == 6 and h["published_us"][0] == us(2026, 10, 20, 9)
    doc = json.loads((store / "health.json").read_text())
    assert doc["tables"]["hourly"]["last_ts_us"] == us(2026, 10, 23, 1)
    # resumable: a second run fetches no file again
    calls.clear()
    res = bd.run(until=date(2026, 10, 23), symbols=["AAAUSDT"], fetch=fetch, delistings=False)
    assert res["fetched"] == 0 and not [c for c in calls if c.endswith(".zip")]


def test_health_ignores_new_archive_days_outside_the_window(store, tmp_path):
    old = [date(2023, 12, d) for d in (1, 2)]
    days = {d: _day_csv(d) for d in old + [date(2026, 10, 21), date(2026, 10, 22)]}
    fetch, _ = _archive(days)
    _um(tmp_path, "AAAUSDT", old[0], old[-1])                 # the lab followed it until 2023-12-02
    res = bd.run(until=date(2026, 10, 23), symbols=["AAAUSDT"], fetch=fetch, delistings=False)
    assert res["fetched"] == 2 and bd.manifest("AAAUSDT") == {"2023-12-01": "ok", "2023-12-02": "ok"}
    doc = json.loads((store / "health.json").read_text())
    assert doc["tables"]["hourly"]["last_ts_us"] is None, "a perp the lab no longer follows is not a stale feed"


def test_a_closed_month_keeps_its_hours_merges_late_days_and_loses_its_raw(store, tmp_path, monkeypatch):
    days = {date(2023, 3, d): _day_csv(date(2023, 3, d), k=d) for d in (1, 2, 3)}
    fetch, _ = _archive(days)
    _um(tmp_path, "AAAUSDT", date(2023, 3, 1), date(2023, 3, 3))
    listed = {d: (100, 0) for d in days}
    bd.collect_symbol("AAAUSDT", [date(2023, 3, 1), date(2023, 3, 2)], listed, None, fetch)
    raw, hours = bd.month_path("raw", "AAAUSDT", "2023-03"), bd.month_path("hourly", "AAAUSDT", "2023-03")
    whole = pl.read_parquet(hours)                            # built from raw while raw was kept
    assert raw.exists() and whole.height == 4
    monkeypatch.setattr(bd, "keeps_raw", lambda month: month >= "2026-10")
    assert bd.prune_raw() > 0 and not raw.exists() and hours.exists()
    bd.collect_symbol("AAAUSDT", [date(2023, 3, 3)], listed, None, fetch)   # a late day of the closed month
    merged = pl.read_parquet(hours)
    assert not raw.exists() and merged.height == 6
    assert merged.head(4).equals(whole), "the stored hours stay as they were"
    assert bd.prune_raw() == 0


def test_the_open_month_keeps_its_raw():
    today = datetime.now(UTC).date()
    assert KEEPS_RAW(today.strftime("%Y-%m")) and not KEEPS_RAW("2023-01")


def test_over_the_budget_nothing_is_fetched(store, tmp_path, monkeypatch):
    days = {date(2026, 1, d): _day_csv(date(2026, 1, d)) for d in range(1, 21)}
    fetch, calls = _archive(days)
    _um(tmp_path, "AAAUSDT", date(2026, 1, 1), date(2026, 1, 20))
    monkeypatch.setattr(bd, "MAX_GB", 1e-9)
    res = bd.run(until=date(2026, 1, 25), symbols=["AAAUSDT"], fetch=fetch, delistings=False)
    assert res["fetched"] == 0 and "budget" in res["errors"]
    assert not [c for c in calls if c.endswith(".zip")]
    est = json.loads((store / "estimate.json").read_text())
    assert est["gb_full"] > est["max_gb"] and est["files_left"] == 20


def test_plan_takes_um_metrics_symbols_from_2023_and_the_lab_perps(tmp_path):
    _um(tmp_path, "OLDUSDT", date(2022, 1, 1), date(2024, 5, 1))
    _um(tmp_path, "NEWUSDT", date(2024, 1, 1), date(2026, 10, 20))
    _um(tmp_path, "GONEUSDT", date(2021, 1, 1), date(2022, 6, 1))
    p = bd.plan(date(2026, 10, 25))
    assert p["OLDUSDT"] == (date(2023, 1, 1), date(2024, 5, 1))
    assert p["NEWUSDT"] == (date(2024, 1, 1), date(2026, 10, 25))
    assert "GONEUSDT" not in p
    assert p["BTCUSDT"] == (date(2023, 1, 1), date(2026, 10, 25)) and "1000PEPEUSDT" in p
    assert bd.base_of("1000PEPEUSDT") == "PEPE" and bd.base_of("BTCUSDT") == "BTC"


# ---------------------------------------------------------------- cost of a market order

def test_cost_of_a_market_order_on_a_uniform_book():
    # notional k per percent: the q-th dollar sits at q / k percent, the mean of Q dollars at Q / 2k
    k = 1e6
    cum = np.array([[0.2 * k, k, 2 * k, 3 * k, 4 * k, 5 * k]])
    for size in (1e4, 1e5, 2.5e6):
        assert math.isclose(bd.cost_bps(cum, size)[0], size / (2 * k) * 100, rel_tol=1e-12)
    # without the 0.2 % level the first segment is the line to 1 %: the same on this book
    no02 = cum.copy()
    no02[0, 0] = np.nan
    assert math.isclose(bd.cost_bps(no02, 1e5)[0], bd.cost_bps(cum, 1e5)[0])
    # beyond the 5 % depth: none
    assert np.isnan(bd.cost_bps(cum, 6e6)[0])
    # a thin first 0.2 %: the first 1k dollars cost more than on the straight line
    thin = np.array([[1e3, k, 2 * k, 3 * k, 4 * k, 5 * k]])
    assert bd.cost_bps(thin, 1e4)[0] > bd.cost_bps(no02, 1e4)[0]
    assert math.isclose(bd.cost_bps(thin, 1e3)[0], 10.0)        # half of 20 bps


# ---------------------------------------------------------------- features

def _hourly(store, sym: str, rows: list[tuple]):
    df = pl.DataFrame(rows, schema=["ts_us", "bid02", "ask02", "bid1", "ask1", "cost10k", "cost100k", "n"],
                      orient="row")
    df = df.with_columns(pl.col("n").cast(pl.Int32), n_fine=pl.col("n").cast(pl.Int32),
                         published_us=pl.col("ts_us") + D, **{c: pl.col(c).cast(pl.Float64) for c in
                                                             ("bid02", "ask02", "bid1", "ask1", "cost10k", "cost100k")})
    p = store / "hourly" / f"symbol={sym}" / "2026-10.parquet"
    p.parent.mkdir(parents=True, exist_ok=True)
    df.select(list(bd.HOURLY_SCHEMA)).write_parquet(p)


def test_hourly_and_daily_features(store):
    t0 = us(2026, 10, 1)
    rows = [(t0 + i * H, 1.0, 3.0, 10.0 + i, 30.0, 2.0, 5.0, 120) for i in range(24)]
    rows = [r for i, r in enumerate(rows) if i != 5]                   # an hour missing
    rows += [(t0 + D + i * H, 1.0, 1.0, 20.0, 20.0, 4.0, 8.0, 60) for i in range(12)]
    _hourly(store, "1000AAAUSDT", rows)
    v = R.values("bd_depth1_usd", "1h", ["AAA"])
    assert v.height == 35 and v["value"][0] == 40.0 and v["known_us"][0] == t0 + H
    assert R.values("bd_imb02", "1h", ["AAA"])["value"][0] == -0.5
    chg = R.values("bd_depth1_chg", "1h", ["AAA"])
    assert math.isclose(chg["value"][0], 41 / 40 - 1)
    assert us(2026, 10, 1, 6) not in chg["ts_us"].to_list()            # none across the gap
    # 24 rows back must be 24 hours back (as R.pct_change): after the gap only from hour 6
    assert R.values("bd_depth1_chg_24h", "1h", ["AAA"])["ts_us"].to_list() == [t0 + D + i * H for i in range(6, 12)]
    d = R.values("bd_cost10k_bps", "1d", ["AAA"])
    assert d["ts_us"].to_list() == [t0, t0 + D] and d["value"].to_list() == [2.0, 4.0]
    assert d["known_us"][0] == t0 + D
    dd = R.values("bd_depth1_chg", "1d", ["AAA"])
    mean0 = np.mean([10.0 + i for i in range(24) if i != 5]) + 30
    assert math.isclose(dd["value"][0], 40 / mean0 - 1)
    f = R.frame(["bd_depth02_usd", "bd_cost100k_bps"], ["AAA"], [t0 + 2 * H], "1h")
    assert f["bd_depth02_usd"][0] == 4.0 and f["bd_cost100k_bps"][0] == 5.0
    assert R.get("bd_depth1_usd").level and not R.get("bd_imb1").level


def test_every_book_feature_passes_the_leak_check():
    names = [n for n in R.names() if n.startswith("bd_")]
    assert len(names) == 11
    for n in names:
        for fq in R.get(n).freqs:
            res = checks.feature(n, fq)
            assert res["ok"], (n, fq, res)


def test_a_planted_leak_in_a_book_feature_is_caught():
    f = R.get("bd_depth1_usd")
    bad = R.Feature("bd_planted", "book_depth", f.sources, "30s", 0,
                    lambda p: (pl.col("bid1") + pl.col("ask1")).shift(-1).over("asset"))
    R.register(bad)
    try:
        assert not checks.feature("bd_planted", "1h")["ok"]
    finally:
        R.REGISTRY.pop("bd_planted")


# ---------------------------------------------------------------- delistings and the universe

def test_titles():
    k, s, w = bd.parse_title("Binance Will Delist EPIC, QUICK on 2026-10-28")
    assert (k, s, w) == ("spot", ["EPICUSDT", "QUICKUSDT"], us(2026, 10, 28))
    k, s, w = bd.parse_title("Binance Futures Will Delist PTBUSDT and MITOUSDT USDⓈ-M Perpetual Contracts (2026-10-23)")
    assert (k, s, w) == ("perp", ["PTBUSDT", "MITOUSDT"], us(2026, 10, 23))
    assert bd.parse_title("Binance Futures Will Delist 1000BTTC and YFII USDT-Margined Contracts")[:2] == \
        ("perp", ["1000BTTCUSDT", "YFIIUSDT"])
    assert bd.parse_title("Binance Futures Will Delist Multiple USDⓈ-M Perpetual Contracts (2025-11-21)")[:2] == \
        ("perp", [])
    assert bd.parse_title("Binance Will Extend the Monitoring Tag to Include ACT, BLUR, PIVX & QKC on 2026-06-18")[:2] \
        == ("monitoring", ["ACTUSDT", "BLURUSDT", "PIVXUSDT", "QKCUSDT"])
    assert bd.parse_title("Binance Futures Will Delist USDⓈ-M ALPHAUSDT Perpetual Contract (2025-09-23)")[:2] == \
        ("perp", ["ALPHAUSDT"])
    assert bd.parse_title("Binance Will Delist ALPHA, BSW, KMD, LEVER, LTO on 2025-07-04")[1][0] == "ALPHAUSDT"
    for t in ("Notice of Removal of Spot Trading Pairs - 2026-10-23",
              "Binance Alpha Will Remove PTB, AA, OWL (2026-10-23)",
              "Binance Will Delist SRM and RAY Margin Pairs and Binance Earn Products",
              "Binance to Delist and Cease Redemption for XRPUP and XRPDOWN Leveraged Tokens (2023-07-25)",
              "Binance Futures Will Delist COIN-M GMTUSD and DOGSUSD Perpetual Contracts (2025-10-28)",
              "Binance Will Delist All American-Style Daily Options",
              "Notice of Removal of Margin Trading Pairs - 2026-10-30"):
        assert bd.parse_title(t)[0] is None, t


def test_announcements_read_bodies_and_the_table_keeps_the_first_value(store):
    def fetch(url, body=None, text=False):
        if "detail" in url:
            return json.loads((FIX / "article.json").read_text())
        if "pageNo=1" not in url:
            return {"data": {"catalogs": [{"articles": []}]}}
        return json.loads((FIX / ("ann_delist.json" if "catalogId=161" in url else "ann_news.json")).read_text())
    rows = bd.announcements(fetch, None)
    got = {(r["symbol"], r["kind"]) for r in rows}
    assert got == {("PTBUSDT", "perp"), ("MITOUSDT", "perp"), ("EPICUSDT", "spot"), ("QUICKUSDT", "spot"),
                   ("AAAUSDT", "perp"), ("1000BBBUSDT", "perp"), ("BICOUSDT", "monitoring"), ("CVCUSDT", "monitoring")}
    bbb = [r for r in rows if r["symbol"] == "1000BBBUSDT"][0]
    assert bbb["base"] == "BBB" and bbb["delisted_us"] == us(2026, 10, 5) and bbb["announced_us"] == 1791168300000000
    stops = bd.archive_stops({"OLDUSDT": {date(2025, 3, 1): (1, 0)}, "AAAUSDT": {date(2026, 10, 25): (1, 0)}},
                             date(2026, 10, 26))
    assert [(r["symbol"], r["delisted_us"], r["known"]) for r in stops] == [("OLDUSDT", us(2025, 3, 2), us(2025, 3, 3))]
    df = bd.delist_frame(rows + stops, us(2026, 10, 28))
    assert bd.save_delistings(df)["new"] == len(rows) + 1
    t = bd.read_delistings()
    old = t.filter(pl.col("symbol") == "OLDUSDT")
    assert old["announced_us"][0] is None and old["known_us"][0] == us(2025, 3, 3) and old["source"][0] == "archive"
    ptb = t.filter(pl.col("symbol") == "PTBUSDT")
    assert ptb["known_us"][0] == 1792575001882000 and ptb["backfilled"][0]
    # a revision of a stored key does not replace it
    again = [dict(r, delisted_us=us(2027, 1, 1)) for r in rows]
    assert bd.save_delistings(bd.delist_frame(again, us(2026, 10, 29)))["new"] == 0
    assert bd.read_delistings().filter(pl.col("symbol") == "PTBUSDT")["delisted_us"][0] == us(2026, 10, 23)


def _panel(days: int = 10):
    d0 = us(2026, 10, 1)
    alive = np.ones((days, 3), dtype=bool)
    alive[:3, 2] = False                              # QQQ's current segment starts on day 3
    return SimpleNamespace(days=d0 + np.arange(days, dtype=np.int64) * D, bases=["PPP", "EEE", "QQQ"],
                           names=["PPPUSDT", "EEEUSDT", "QQQUSDT"], alive=alive, T=days)


def test_universe_drops_a_coin_from_the_day_its_delisting_was_announced():
    P = _panel()
    table = pl.DataFrame({"base": ["PPP", "EEE", "QQQ", "QQQ"], "kind": ["perp", "monitoring", "spot", "spot"],
                          "known_us": [us(2026, 10, 4, 15), us(2026, 10, 2), us(2026, 9, 1), us(2026, 10, 8, 23)]})
    days = universe.delisting_days(P, table)
    assert days.tolist() == [3, 10, 7]               # the monitoring tag does not count; QQQ's old asset ignored
    m = universe.tradable(P, ["PPP", "EEE", "QQQ"], table=table)
    assert m[:3, 0].all() and not m[3:, 0].any() and m[:, 1].all() and m[6, 2] and not m[7, 2]
    assert universe.tradable(P, ["PPP", "EEE", "QQQ"], drop_delisting=False, table=table).all()
    assert universe.delisting_days(P, table, kinds=("monitoring",)).tolist() == [10, 1, 10]
    late = pl.DataFrame({"base": ["PPP"], "kind": ["spot"], "known_us": [us(2026, 10, 11, 1)]})
    assert universe.delisting_days(P, late).tolist() == [10, 10, 10]


def test_universe_reads_the_stored_table_and_works_without_one(store):
    P = _panel()
    assert universe.delisting_days(P).tolist() == [10, 10, 10]
    rows = [{"symbol": "PPPUSDT", "base": "PPP", "kind": "spot", "announced_us": us(2026, 10, 5, 9),
             "delisted_us": us(2026, 10, 9), "source": "announcement", "article": "1"}]
    bd.save_delistings(bd.delist_frame(rows, us(2026, 10, 28)))
    assert universe.delisting_days(P).tolist() == [4, 10, 10]


# ---------------------------------------------------------------- the metrics create_time check

def _metrics_and_klines(shift: int, n: int = 288, seed: int = 0) -> tuple[bytes, bytes]:
    rng = np.random.default_rng(seed)
    t0 = us(2026, 6, 25)
    buy = rng.uniform(10, 20, n + 4)
    sell = rng.uniform(10, 20, n + 4)
    m = ["create_time,symbol,sum_open_interest,sum_open_interest_value,count_toptrader_long_short_ratio,"
         "sum_toptrader_long_short_ratio,count_long_short_ratio,sum_taker_long_short_vol_ratio"]
    k = ["open_time,open,high,low,close,volume,close_time,quote_volume,count,taker_buy_volume,"
         "taker_buy_quote_volume,ignore"]
    for i in range(n):
        ts = datetime.fromtimestamp((t0 + i * 300_000_000) / 1e6, UTC).strftime("%Y-%m-%d %H:%M:%S")
        j = i + 2 + shift
        m.append(f"{ts},X,1,1,1,1,1,{buy[j] / sell[j]}")
    for i in range(n + 4):
        ot = (t0 + (i - 2) * 300_000_000) // 1000
        k.append(f"{ot},1,1,1,1,{buy[i] + sell[i]},{ot + 299999},1,1,{buy[i]},1,0")
    return "\n".join(m).encode(), "\n".join(k).encode()


def test_stamp_lags_find_the_period_and_a_planted_shift():
    c = um_metrics.stamp_lags(*_metrics_and_klines(0))
    assert max(c, key=c.get) == 0 and c[0] > 0.999 and abs(c[1]) < 0.3
    c = um_metrics.stamp_lags(*_metrics_and_klines(1))
    assert max(c, key=c.get) == 1
    rows = [{"symbol": "X", "after": False, "best": 0}, {"symbol": "X", "after": True, "best": 1},
            {"symbol": "Y", "after": False, "best": 0}, {"symbol": "Y", "after": True, "best": 0}]
    v = um_metrics.shift_verdict(rows)
    assert v["X"]["shifted"] and not v["Y"]["shifted"]


def test_check_shift_walks_both_sides_of_the_date():
    pairs = {"before": _metrics_and_klines(0), "after": _metrics_and_klines(1)}

    def fetch(url, pacer):
        side = "after" if "2026-06-25" in url or "2026-06-26" in url else "before"
        return pairs[side][0 if "metrics" in url else 1]
    rows = um_metrics.check_shift(["X"], date(2026, 6, 25), 2, fetch)
    assert [r["day"] for r in rows] == ["2026-06-23", "2026-06-24", "2026-06-25", "2026-06-26"]
    assert [r["best"] for r in rows] == [0, 0, 1, 1]
    assert um_metrics.shift_verdict(rows)["X"] == {"before": [0], "after": [1], "shifted": True}


def test_the_announcement_history_resumes_after_a_429(store):
    pages = {161: [json.loads((FIX / "ann_delist.json").read_text())],
             49: [json.loads((FIX / "ann_news.json").read_text()), json.loads((FIX / "ann_news.json").read_text())]}
    pages[49][1]["data"]["catalogs"][0]["articles"] = [
        {"id": 1, "code": "a", "title": "Binance Will Extend the Monitoring Tag to Include OLD on 2023-01-02",
         "releaseDate": 1672560000000}]
    fail = {"on": True}

    def fetch(url, body=None, text=False):
        if "detail" in url:
            return json.loads((FIX / "article.json").read_text())
        cat = 161 if "catalogId=161" in url else 49
        page = int(url.split("pageNo=")[1].split("&")[0])
        if cat == 49 and page == 2 and fail["on"]:
            raise RuntimeError("HTTP Error 429: Too Many Requests")
        ps = pages[cat]
        return ps[page - 1] if page <= len(ps) else {"data": {"catalogs": [{"articles": []}]}}
    with pytest.raises(RuntimeError, match="429"):
        bd.update_delistings({}, date(2026, 10, 26), fetch)
    t = bd.read_delistings()
    assert {"PTBUSDT", "BICOUSDT"} <= set(t["symbol"].to_list()) and "OLDUSDT" not in t["symbol"].to_list()
    assert json.loads((store / "announcements.json").read_text()) == {"161": {"next": None}, "49": {"next": 2}}
    fail["on"] = False
    bd.update_delistings({}, date(2026, 10, 26), fetch)
    t = bd.read_delistings()
    assert "OLDUSDT" in t["symbol"].to_list() and t.filter(pl.col("symbol") == "BICOUSDT").height == 1
    assert json.loads((store / "announcements.json").read_text())["49"] == {"next": None}
