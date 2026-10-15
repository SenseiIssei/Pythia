"""CS2 Steam market trends: the csgotrader snapshot collector (mock fetch, no
network), links, groups, changes, momentum, spreads after fees, drops, the
alerts and the daily summary.

Run from research/lab:  python -m pytest tests/test_cs2_trends.py
"""

from __future__ import annotations

import gzip
import json
import math
from datetime import date, datetime, timedelta, timezone

import numpy as np
import polars as pl
import pytest

from lab.collect import cs2 as collect
from lab.cs2 import market, trends
from lab.ops import notify

NOW = int(datetime(2026, 10, 15, 14, 40, tzinfo=timezone.utc).timestamp() * 1000)
WATCH = {"cases": [{"name": "Fever Case", "released": "2025-03-31"}], "events": []}


@pytest.fixture(autouse=True)
def quiet_env(monkeypatch):
    for k in ("PYTHIA_ALERT_WEBHOOK", "PYTHIA_TELEGRAM_BOT_TOKEN", "PYTHIA_TELEGRAM_CHAT_ID", "PYTHIA_ALERT_VIA"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("PYTHIA_QUIET_HOURS", "off")


# ---------------------------------------------------------------- the collector

def steam_file(n: int = 6000, extra: dict | None = None) -> dict:
    d = {f"P250 | Sand Dune {i} (Field-Tested)": {"last_24h": 1.0 + i / 1000, "last_7d": 1.0, "last_30d": 1.0,
                                                  "last_90d": 1.0} for i in range(n)}
    d.update(extra or {})
    return d


class Net:
    def __init__(self, data: dict, modified: str = "Thu, 15 Oct 2026 13:25:07 GMT", fx: dict | None = None,
                 fx_status: int = 200):
        self.data, self.modified, self.fx, self.fx_status = data, modified, fx or {"USD": 1, "EUR": 0.9}, fx_status
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, url, headers):
        self.calls.append((url, headers))
        if url == collect.CSGOTRADER_STEAM:
            return 200, gzip.compress(json.dumps(self.data).encode()), {"Content-Encoding": "gzip",
                                                                       "Last-Modified": self.modified}
        if url == collect.CSGOTRADER_FX:
            return self.fx_status, json.dumps(self.fx).encode(), {}
        raise AssertionError(f"unexpected request {url}")


def test_steam_market_snapshot_is_dated_by_the_file_and_taken_once(tmp_path):
    net = Net(steam_file(extra={"Bad": {"last_24h": -1, "last_7d": None, "last_30d": "x", "last_90d": 0},
                                "AK-47 | Redline (Field-Tested)": {"last_24h": None, "last_7d": 42.8,
                                                                    "last_30d": 43.5, "last_90d": 43.9}}),
              modified="Wed, 14 Oct 2026 13:25:07 GMT")
    rep = collect.steam_market(tmp_path, fetch=net, now_ms=NOW)
    assert rep["ok"] and rep["day"] == "2026-10-14", "a file rebuilt yesterday is yesterday's snapshot"
    assert rep["items"] == 6001 and rep["eur_per_usd"] == 0.9 and rep["fx_source"] == "csgotrader"
    assert all(h.get("Accept-Encoding") == "gzip" for _, h in net.calls)
    assert all(u.startswith("https://prices.csgotrader.app/") for u, _ in net.calls), "nothing on Steam itself"
    df = pl.read_parquet(tmp_path / "cs2" / "daily" / "steam_market" / "date=2026-10-14.parquet")
    ak = df.filter(pl.col("name") == "AK-47 | Redline (Field-Tested)").row(0, named=True)
    assert ak["usd_24h"] is None and ak["usd_7d"] == 42.8 and "Bad" not in df["name"].to_list()
    again = collect.steam_market(tmp_path, fetch=net, now_ms=NOW + 3_600_000)
    assert again["ok"] and again.get("skipped") and len(net.calls) == 3, "one GET to see the date, no second store"


def test_steam_market_keeps_the_last_rate_and_refuses_a_broken_file(tmp_path):
    collect.steam_market(tmp_path, fetch=Net(steam_file()), now_ms=NOW)
    rep = collect.steam_market(tmp_path, fetch=Net(steam_file(), modified="Fri, 16 Oct 2026 13:25:07 GMT",
                                                   fx_status=503), now_ms=NOW + 86_400_000)
    assert rep["ok"] and rep["eur_per_usd"] == 0.9 and rep["fx_source"] == "last known"
    small = collect.steam_market(tmp_path, fetch=Net(steam_file(10), modified="Sat, 17 Oct 2026 13:25:07 GMT"),
                                 now_ms=NOW + 2 * 86_400_000)
    assert not small["ok"] and "only 10 items" in small["errors"][0]
    assert not (tmp_path / "cs2" / "daily" / "steam_market" / "date=2026-10-17.parquet").exists()


def test_the_steam_market_flag_runs_only_that_part(monkeypatch):
    seen = []
    monkeypatch.setattr(collect, "steam_market", lambda force=False: (seen.append(force), {"ok": True})[1])
    monkeypatch.setattr(collect, "run", lambda **k: pytest.fail("the hourly collector must not run"))
    assert collect.main(["--steam-market", "--force"]) == 0 and seen == [True]


def test_skinport_items_keep_their_own_page():
    df = collect.parse_items([{"market_hash_name": "AK-47 | Redline (Field-Tested)",
                               "item_page": "https://skinport.com/item/ak-47-redline-field-tested", "min_price": 22},
                              {"market_hash_name": "X", "item_page": "javascript:alert(1)"}], NOW)
    assert df["item_page"].to_list() == ["https://skinport.com/item/ak-47-redline-field-tested", None]


# ---------------------------------------------------------------- links and groups

def test_links_encode_the_whole_name():
    assert trends.steam_url("StatTrak™ AK-47 | Redline (Field-Tested)") == (
        "https://steamcommunity.com/market/listings/730/StatTrak%E2%84%A2%20AK-47%20%7C%20Redline%20%28Field-Tested%29")
    assert trends.steam_url("★ Karambit | Doppler (Factory New)").endswith("%E2%98%85%20Karambit%20%7C%20Doppler%20%28Factory%20New%29")
    assert trends.steam_url("Sticker | Team Liquid (Holo) | Paris 2023 / 50%").endswith("Paris%202023%20%2F%2050%25")
    assert trends.skinport_url("StatTrak™ Zeus x27 | Tosai (Well-Worn)") == \
        "https://skinport.com/item/stattrak-zeus-x27-tosai-well-worn"
    assert trends.skinport_url("★ Karambit | Doppler (Factory New)") == "https://skinport.com/item/karambit-doppler-factory-new"
    assert trends.skinport_url("X", "https://skinport.com/item/own-page") == "https://skinport.com/item/own-page"
    assert trends.skinport_url("X", "https://evil.example/item") == "https://skinport.com/item/x"
    for u in (trends.steam_url("A&B <c> \"d\""), trends.skinport_url("A&B <c> \"d\"")):
        assert notify.safe_url(u) == u


def test_groups():
    g = trends.group_of
    assert g("Fever Case") == "case" and g("Austin 2025 Legends Sticker Capsule") == "capsule"
    assert g("Sticker | Crown (Foil)") == "sticker" and g("Sticker Slab | ZywOo (Holo) | Budapest 2025") == "sticker slab"
    assert g("★ Karambit | Fade (Factory New)") == "knife or glove"
    assert g("AK-47 | Redline (Field-Tested)") == "skin, Field-Tested"
    assert g("StatTrak™ M4A4 | Howl (Minimal Wear)") == "skin, Minimal Wear"
    assert g("Austin 2025 Mirage Souvenir Package") == "capsule"
    assert trends.tier_of(0.5) == "under 1 EUR" and trends.tier_of(150) == "100 EUR or more" and trends.tier_of(None) is None


# ---------------------------------------------------------------- the analysis

def write_day(root, day: date, rows: list[dict], fx: float = 0.9) -> None:
    p = root / "cs2" / "daily" / "steam_market" / f"date={day.isoformat()}.parquet"
    p.parent.mkdir(parents=True, exist_ok=True)
    pl.DataFrame([{**r, "eur_per_usd": fx, "source_updated": day.isoformat(), "fetched_ms": 0} for r in rows],
                 schema=collect.STEAM_MARKET_SCHEMA).write_parquet(p)


def write_skinport(root, day: date, rows: list[dict]) -> None:
    p = root / "cs2" / "daily" / "skinport" / f"date={day.isoformat()}.parquet"
    p.parent.mkdir(parents=True, exist_ok=True)
    full = []
    for r in rows:
        x = {"name": r["name"], "min_price": r["ask"], "item_page": None, "quantity": 50}
        for w in ("s24", "s7", "s30", "s90"):
            for s in ("min", "max", "avg", "median", "volume"):
                x[f"{w}_{s}"] = None
        x.update(s7_volume=r.get("sales7", 40), s7_median=r["ref"], s24_volume=0)
        full.append(x)
    pl.DataFrame(full, infer_schema_length=None).write_parquet(p)


def one_day(root) -> date:
    day = date(2026, 10, 15)
    rows = [
        # +30 % on the day against its week: a mover from the windows
        {"name": "AWP | Black Box (Field-Tested)", "usd_24h": 13.0, "usd_7d": 10.0, "usd_30d": 10.0, "usd_90d": 10.0},
        {"name": "Fever Case", "usd_24h": 1.0, "usd_7d": 1.0, "usd_30d": 1.0, "usd_90d": 1.0},
        # cheaper on Steam than Skinport sells it for: the cash route clears the fee
        {"name": "Sticker | Censored (Foil)", "usd_24h": 2.0, "usd_7d": 2.0, "usd_30d": 2.0, "usd_90d": 2.0},
        {"name": "★ Karambit | Doppler (Factory New)", "usd_24h": 600, "usd_7d": 600, "usd_30d": 600, "usd_90d": 600},
        {"name": "Cheap | Thing (Field-Tested)", "usd_24h": 0.5, "usd_7d": 0.2, "usd_30d": 0.2, "usd_90d": 0.2},
    ]
    rows += [{"name": f"P250 | Filler {i} (Field-Tested)", "usd_24h": 3.0, "usd_7d": 3.0, "usd_30d": 3.0,
              "usd_90d": 3.0} for i in range(20)]
    write_day(root, day, rows)
    sp = [{"name": r["name"], "ask": r["usd_24h"] * 0.9 / 1.6, "ref": r["usd_24h"] * 0.9 / 1.6} for r in rows]
    sp = [s if s["name"] != "Sticker | Censored (Foil)" else {**s, "ask": 2.6, "ref": 2.4} for s in sp]
    sp = [s if s["name"] != "★ Karambit | Doppler (Factory New)" else {**s, "ask": 900, "ref": 900} for s in sp]
    write_skinport(root, day, sp)
    return day


def test_first_day_uses_the_source_windows_and_finds_movers_and_spreads(tmp_path):
    day = one_day(tmp_path)
    s = trends.summarize(trends.history(tmp_path), market.latest_daily(tmp_path, "skinport"), watch=WATCH)
    assert s["basis"]["chg_1d"] == "no earlier snapshot" and "7-day average" in s["basis"]["chg_7d"]
    up = s["movers"]["up"]
    assert up[0]["name"] == "AWP | Black Box (Field-Tested)" and abs(up[0]["move"] - 0.3) < 1e-9
    assert all(m["name"] != "Cheap | Thing (Field-Tested)" for m in up), "under 1 EUR is not liquid"
    kinds = {(a["kind"], a["name"]) for a in s["alerts"]}
    assert ("mover", "AWP | Black Box (Field-Tested)") in kinds
    cash = [u for u in s["spread"]["unusual"] if u["why"] == "cash"]
    assert [u["name"] for u in cash] == ["Sticker | Censored (Foil)"]
    # 2.00 USD * 0.9 = 1.80 EUR on Steam; Skinport sells at min(2.59, 2.40) and keeps 8 %
    assert abs(cash[0]["to_skinport"] - (2.4 * 0.92 / 1.8 - 1)) < 1e-4
    assert all("Doppler" not in u["name"] for u in s["spread"]["unusual"]), "phases are left out"
    assert s["spread"]["median_premium"] == pytest.approx(0.6, abs=0.01)
    assert s["drops"]["new"] == [] and s["drops"]["around_last"] is None
    assert s["date"] == day.isoformat() and s["eurPerUsd"] == 0.9


def test_later_days_use_our_snapshots_and_find_new_cases_and_rising_ones(tmp_path):
    d0 = date(2026, 10, 1)
    base = [{"name": f"P250 | Filler {i} (Field-Tested)", "usd_24h": 3.0, "usd_7d": 3.0, "usd_30d": 3.0, "usd_90d": 3.0}
            for i in range(20)]
    for k in range(15):
        day = d0 + timedelta(days=k)
        case = 1.0 if k < 14 else 1.3  # the case jumps on the last day
        rows = base + [{"name": "Fever Case", "usd_24h": case, "usd_7d": 1.0, "usd_30d": 1.0, "usd_90d": 1.0}]
        if k == 14:
            rows.append({"name": "Brand New Case", "usd_24h": 5.0, "usd_7d": 5.0, "usd_30d": None, "usd_90d": None})
        write_day(tmp_path, day, rows)
    last = d0 + timedelta(days=14)
    write_skinport(tmp_path, last, [{"name": r["name"], "ask": 2.0, "ref": 2.0} for r in base]
                   + [{"name": "Fever Case", "ask": 0.7, "ref": 0.7, "sales7": 500},
                      {"name": "Brand New Case", "ask": 3.0, "ref": 3.0, "sales7": 500}])
    s = trends.summarize(trends.history(tmp_path), market.latest_daily(tmp_path, "skinport"), watch=WATCH)
    assert s["basis"]["chg_1d"] == "snapshot 2026-10-14" and s["basis"]["chg_7d"] == "snapshot 2026-10-08"
    fever = next(m for m in s["movers"]["up"] if m["name"] == "Fever Case")
    assert abs(fever["move"] - 0.3) < 1e-9 and abs(fever["chg_7d"] - 0.3) < 1e-9
    assert [n["name"] for n in s["drops"]["new"]] == ["Brand New Case"]
    assert [c["name"] for c in s["drops"]["rising_cases"]] == ["Fever Case"]
    al = s["drops"]["around_last"]
    assert al["items"] == ["Brand New Case"] and al["kind"] == "first seen"
    kinds = {a["kind"] for a in s["alerts"]}
    assert {"mover", "new_drop", "case_rise"} <= kinds


def test_a_recent_operation_or_drop_pool_event_is_the_last_drop(tmp_path):
    day = one_day(tmp_path)
    watch = {"cases": [{"name": "Fever Case", "released": "2025-03-31"}],
             "operations": [{"name": "Test Op", "start": "2026-10-05", "end": "2027-01-01", "case": "Op Case"}],
             "events": [{"date": "2026-10-10", "kind": "left_drop_pool", "items": ["Fever Case"]},
                        {"date": "not a date", "kind": "x"}]}
    hist = trends.history(tmp_path)
    df, _ = trends.frame(hist, market.latest_daily(tmp_path, "skinport"))
    d = trends.drops(hist, df, day, watch)
    assert [e["kind"] for e in d["recent"]] == ["operation start", "left_drop_pool"]
    al = d["around_last"]
    assert al["kind"] == "left_drop_pool" and al["items"] == ["Fever Case"] and al["days_ago"] == 5
    assert al["other_cases_since"] is None and "no snapshot from before" in al["other_cases_since_basis"]


def test_momentum_from_snapshots_finds_a_planted_trend(tmp_path):
    rng = np.random.default_rng(4)
    names = [f"AK-47 | Planted {i} (Field-Tested)" for i in range(120)]
    drift = rng.normal(0, 0.01, len(names))
    level = np.full(len(names), 10.0)
    d0 = date(2026, 9, 1)
    for k in range(40):
        level = level * np.exp(drift + rng.normal(0, 0.002, len(names)))
        write_day(tmp_path, d0 + timedelta(days=k), [{"name": n, "usd_24h": float(v), "usd_7d": float(v),
                                                      "usd_30d": float(v), "usd_90d": float(v)}
                                                     for n, v in zip(names, level)])
    hist = trends.history(tmp_path)
    m = trends.momentum_snapshots(hist, {n: "skin, Field-Tested" for n in names}, set(names))
    assert m["ready"] and m["rows"][0]["group"] == "all"
    a = m["rows"][0]
    assert a["ic"] > 0.5 and a["lean"] == "momentum" and a["days"] >= 20
    short = trends.momentum_snapshots(hist.filter(pl.col("date") < d0 + timedelta(days=10)), {}, set(names))
    assert not short["ready"] and short["waiting_days"] == 11


def test_alert_card_has_links_and_fits_telegram():
    found = [{"kind": "mover", "name": f"StatTrak™ AK-47 | Redline {i} (Field-Tested)", "group": "skin, Field-Tested",
              "eur": 40.0, "move": 0.31, "basis": "since yesterday's snapshot", "chg_7d": 0.2, "chg_30d": 0.1,
              "skinport_ask": 25.0, "skinport_sales7": 120, "steam_url": trends.steam_url(f"AK {i}"),
              "skinport_url": trends.skinport_url(f"AK {i}")} for i in range(10)]
    card = trends.alert_card(found)
    html = notify.render_post([card], "telegram")
    assert html == card.render("telegram"), "fits whole"
    assert html.count('<a href="https://steamcommunity.com/market/listings/730/') == trends.MAX_IN_CARD
    assert html.count('<a href="https://skinport.com/item/') == trends.MAX_IN_CARD
    assert "2 more on the CS2 page" in html and "Information only" in html and "—" not in html
    out, st = trends.fresh_alerts(found[:2], {}, "2026-10-15")
    assert len(out) == 2
    again, st = trends.fresh_alerts(found[:2], st, "2026-10-17")
    assert again == [], "3-day cooldown"
    later, _ = trends.fresh_alerts(found[:2], st, "2026-10-18")
    assert len(later) == 2


def test_run_posts_alerts_and_one_summary_a_day_and_writes_the_page_data(tmp_path, monkeypatch):
    one_day(tmp_path)
    monkeypatch.setattr(trends, "load_watchlist", lambda path=None: WATCH)
    monkeypatch.setenv("PYTHIA_TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setenv("PYTHIA_TELEGRAM_CHAT_ID", "42")
    monkeypatch.setenv("PYTHIA_DATA", str(tmp_path))
    posted = []
    s = trends.run(tmp_path, now_ms=NOW, poster=lambda text: (posted.append(text), (True, None))[1])
    assert len(posted) == 2 and "CS2 Steam market" in posted[0] and "Steam market</a>" in posted[0]
    assert "Liquid items, medians" in posted[1]
    saved = json.loads((tmp_path / "cs2" / "trends" / "latest.json").read_text(encoding="utf-8"))
    assert saved["date"] == "2026-10-15" and saved["movers"]["up"][0]["steam_url"].startswith("https://steamcommunity.com/")
    assert saved["groups"] and "skinport_url" in saved["movers"]["up"][0]
    rep = json.loads((tmp_path / "reports" / "cs2_trends" / "latest.json").read_text(encoding="utf-8"))
    assert rep["title"] == "CS2 Steam market" and rep["status"] in ("ok", "watch") and rep["items"]
    md = (tmp_path / "reports" / "cs2_trends" / "latest.md").read_text(encoding="utf-8")
    assert "Momentum or mean reversion" in md and "—" not in md and s["sent"][0]["delivered"]
    # the same day again: nothing new to say
    posted.clear()
    trends.run(tmp_path, now_ms=NOW + 3_600_000, poster=lambda text: (posted.append(text), (True, None))[1])
    assert posted == []
    text = (tmp_path / "cs2" / "trends" / "latest.json").read_text(encoding="utf-8")
    assert "NaN" not in text and "Infinity" not in text


def test_the_hourly_board_carries_the_trends(tmp_path):
    from lab.cs2 import run as cs2run
    one_day(tmp_path)
    trends.run(tmp_path, now_ms=NOW, send=False)
    st = json.loads((tmp_path / "cs2" / "trends" / "alerts_state.json").read_text(encoding="utf-8"))
    assert st.get("alerts") == {} and "last_summary" not in st, "--no-alerts marks nothing as said"
    assert not (tmp_path / "cs2" / "trends" / "alerts.jsonl").exists()
    # the hourly job needs a Skinport hourly snapshot; the trends ride along on its board
    p = tmp_path / "cs2" / "skinport_items" / "date=2026-10-15" / "1405.parquet"
    p.parent.mkdir(parents=True, exist_ok=True)
    collect.parse_items([{"market_hash_name": "Fever Case", "min_price": 0.6, "quantity": 100}], NOW).write_parquet(p)
    assert cs2run.main(["--refit"], root=tmp_path, now_ms=NOW) == 0
    board = json.loads((tmp_path / "reports" / "cs2" / "latest.json").read_text(encoding="utf-8"))
    assert board["steamTrends"]["date"] == "2026-10-15" and board["steamTrends"]["movers"]["up"]


def test_chart_draws_when_matplotlib_is_there(tmp_path):
    from lab.ops import charts
    if not charts.available():
        pytest.skip("no matplotlib")
    one_day(tmp_path)
    s = trends.summarize(trends.history(tmp_path), market.latest_daily(tmp_path, "skinport"), watch=WATCH)
    img = trends.make_chart(s, tmp_path / "cs2")
    assert img and img[:4] == b"\x89PNG"
    data = trends.chart_data(s)
    assert data["movers"][0][0] == "AWP | Black Box (Field-Tested)" and math.isclose(data["movers"][0][1], 30.0)
