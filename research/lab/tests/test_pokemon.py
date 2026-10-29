"""Pokemon cards: collector, studies, models, paper collection, alerts, daily job.

Everything runs on a made-up market (tests/pokemon_synth.py) served through a
fake HTTP opener; no network. Run from research/lab:  python -m pytest tests
"""

from __future__ import annotations

import json
import math
import sys
import urllib.parse
from datetime import date
from pathlib import Path

import numpy as np
import polars as pl
import pytest

sys.path.insert(0, str(Path(__file__).parent))

from pokemon_synth import Market, build_lake  # noqa: E402

from lab.collect import pokemon as col  # noqa: E402
from lab.pokemon import alerts, collection, daily, model, study  # noqa: E402
from lab.pokemon import data as pdata  # noqa: E402


@pytest.fixture()
def lake(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTHIA_DATA", str(tmp_path))
    monkeypatch.setenv("PYTHIA_REPORTS", str(tmp_path / "reports"))
    for k in ("PYTHIA_ALERT_WEBHOOK", "PYTHIA_TELEGRAM_BOT_TOKEN", "PYTHIA_TELEGRAM_CHAT_ID", "PYTHIA_RESULTS",
              "POKEMONTCG_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    import lab.report
    monkeypatch.setattr(lab.report, "REPORTS", tmp_path / "reports")
    return tmp_path / "pokemon"


# ---------------------------------------------------------------- collector

def test_client_retries_with_backoff_and_honours_retry_after(tmp_path):
    m = Market(date(2026, 1, 1), n_sets=2, per_set=5)
    waits = []
    c = col.Client(opener=m.opener(fail_first=2), sleep=waits.append, spacing=0.0, backoff=0.5)
    d = c.get(f"{col.API}/sets?page=1&pageSize=250")
    assert len(d["data"]) == 2 and c.requests == 3
    assert waits == [1.0, 1.0], "Retry-After 1 s beats the 0.5 s and 1.0 s backoff"


def test_client_retries_a_cut_short_answer_and_a_reset_connection():
    import http.client
    m = Market(date(2026, 1, 1), n_sets=2, per_set=5)
    ok = m.opener()
    errors = [http.client.IncompleteRead(b"{\"data\": [", 4000), ConnectionResetError(10054, "reset"),
              http.client.RemoteDisconnected("closed")]

    def opener(url, headers, timeout):
        if errors:
            raise errors.pop(0)
        return ok(url, headers, timeout)

    waits = []
    c = col.Client(opener=opener, sleep=waits.append, spacing=0.0, backoff=0.5)
    d = c.get(f"{col.API}/sets?page=1&pageSize=250")
    assert len(d["data"]) == 2 and c.requests == 4 and waits == [0.5, 1.0, 2.0]
    # Every try cut short: a FetchError naming the kind, which the run's attempts handle.
    c = col.Client(opener=lambda *a: (_ for _ in ()).throw(http.client.IncompleteRead(b"", 10)),
                   sleep=lambda s: None, spacing=0.0, retries=3)
    with pytest.raises(col.FetchError, match="IncompleteRead"):
        c.get(f"{col.API}/sets")


def test_client_gives_up_on_client_errors_and_never_leaks_the_query():
    calls = []

    def opener(url, headers, timeout):
        calls.append(headers)
        return 403, {}, b""

    c = col.Client(opener=opener, sleep=lambda s: None, spacing=0.0, headers={"X-Api-Key": "k"})
    with pytest.raises(col.FetchError) as e:
        c.get(f"{col.API}/cards?q=secret")
    assert len(calls) == 1 and "secret" not in str(e.value) and "HTTP 403" in str(e.value)
    assert calls[0]["X-Api-Key"] == "k"


def test_client_spaces_requests(tmp_path):
    t = {"now": 0.0}
    slept = []

    def sleep(s):
        slept.append(round(s, 2))
        t["now"] += s

    m = Market(date(2026, 1, 1), n_sets=1, per_set=3)
    c = col.Client(opener=m.opener(), sleep=sleep, clock=lambda: t["now"], spacing=2.1)
    c.get(f"{col.API}/sets?page=1")
    c.get(f"{col.API}/sets?page=1")
    assert slept == [2.1]


def test_cache_makes_a_rerun_free(tmp_path):
    m = Market(date(2026, 1, 1), n_sets=1, per_set=3)
    c = col.Client(opener=m.opener(), sleep=lambda s: None, spacing=0.0, cache_dir=tmp_path)
    a = c.get(f"{col.API}/sets?page=1", cache_key="sets_1")
    c2 = col.Client(opener=lambda *a: (_ for _ in ()).throw(AssertionError("network")), cache_dir=tmp_path)
    assert c2.get("ignored", cache_key="sets_1") == a and c2.cache_hits == 1


def test_a_failed_run_is_tried_again_and_continues_from_the_cache(lake):
    m = Market(date(2026, 3, 1), n_sets=2, per_set=300)  # 600 cards: three pages
    inner = m.opener()
    seen = []

    def flaky(url, h, t):
        seen.append(url)
        # The third card page fails every try of the first attempt.
        if "/cards" in url and "page=3" in url and len([u for u in seen if "page=3" in u and "/cards" in u]) <= 2:
            return 502, {}, b""
        return inner(url, h, t)

    def attempt():
        cl = col.Client(opener=flaky, sleep=lambda s: None, spacing=0.0, retries=2,
                        cache_dir=lake / "_cache" / "2026-03-01")
        return col.collect("2026-03-01", min_usd=0.0, client=cl, log=lambda *a: None)

    pauses = []
    assert col.run_with_attempts(attempt, 3, 5.0, sleep=pauses.append) == 0
    assert pauses == [5.0], "one failed attempt, one pause"
    card_pages = [u for u in seen if "/cards" in u]
    assert sum("page=1&" in u for u in card_pages) == 1, "page 1 came from the cache the second time"
    assert pl.read_parquet(lake / "catalog.parquet").height == 600
    assert col.run_with_attempts(lambda: (_ for _ in ()).throw(col.FetchError("down")), 2, 1.0,
                                 sleep=lambda s: None) == 1


def _paged(m, seen, fail_page=None):
    """The market's opener that records card pages and refuses `fail_page` every try."""
    inner = m.opener()

    def opener(url, h, t):
        if "/cards" in url:
            page = int(urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["page"][0])
            seen.append(page)
            if page == fail_page:
                return 502, {}, b""
        return inner(url, h, t)
    return opener


def test_the_next_run_resumes_an_unfinished_snapshot_from_the_cursor(lake):
    m = Market(date(2026, 3, 1), n_sets=2, per_set=300)  # 600 cards: three pages
    cache = lake / "_cache" / "2026-03-01"
    seen: list[int] = []
    cl = col.Client(opener=_paged(m, seen, fail_page=3), sleep=lambda s: None, spacing=0.0, retries=2, cache_dir=cache)
    with pytest.raises(col.FetchError):
        col.collect("2026-03-01", min_usd=0.0, client=cl, log=lambda *a: None)
    cur = json.loads((lake / col.CURSOR).read_text())
    assert cur["date"] == "2026-03-01" and cur["pages"]["cards"]["page"] == 2, "pages 1 and 2 are done"
    # The timeout killed it: the next day finds it unfinished and finishes it under its own date.
    assert col.pending_snapshot(lake, "2026-03-02") == "2026-03-01"
    assert col.pending_snapshot(lake, "2026-03-01") is None, "today's own cursor is not a pending snapshot"
    assert col.pending_snapshot(lake, "2026-03-03") is None, "older than RESUME_DAYS: started afresh"
    seen.clear()
    logs: list[str] = []
    cl = col.Client(opener=_paged(m, seen), sleep=lambda s: None, spacing=0.0, cache_dir=cache)
    meta = col.collect("2026-03-01", min_usd=0.0, client=cl, log=logs.append)
    assert seen == [3], "only the page after the cursor went to the network"
    assert meta["resumed"] == {"cards": 2} and any("after page 2" in x for x in logs)
    assert pl.read_parquet(lake / "catalog.parquet").height == 600
    assert pl.read_parquet(lake / "cards" / "date=2026-03-01" / "cards.parquet").height == 600


def test_a_finished_snapshot_resets_the_cursor(lake):
    m = Market(date(2026, 3, 1), n_sets=2, per_set=300)
    seen: list[int] = []
    for day in ("2026-03-01", "2026-03-02"):
        cl = col.Client(opener=_paged(m, seen), sleep=lambda s: None, spacing=0.0, cache_dir=lake / "_cache" / day)
        meta = col.collect(day, min_usd=0.0, client=cl, log=lambda *a: None)
        assert not (lake / col.CURSOR).exists() and meta["resumed"] is None
    assert seen == [1, 2, 3, 1, 2, 3], "the second day starts at page 1"
    assert col.pending_snapshot(lake, "2026-03-03") is None
    # A cursor of another day or another query counts for nothing.
    c = col.Cursor(lake / col.CURSOR, "2026-03-04")
    c.mark("cards", "q=a", 5)
    assert col.Cursor.load(lake / col.CURSOR, "2026-03-04").done("cards", "q=a") == 5
    assert col.Cursor.load(lake / col.CURSOR, "2026-03-04").done("cards", "q=b") == 0
    assert col.Cursor.load(lake / col.CURSOR, "2026-03-05").pages == {}
    # A dry run and a --max-pages test neither read nor move it.
    col.collect("2026-03-04", min_usd=0.0, max_pages=1, client=col.Client(opener=m.opener(), sleep=lambda s: None,
                                                                          spacing=0.0), log=lambda *a: None)
    assert json.loads((lake / col.CURSOR).read_text())["pages"] == {"cards": {"query": "q=a", "page": 5}}


def test_main_finishes_yesterdays_snapshot_before_todays(lake, monkeypatch):
    calls = []
    monkeypatch.setattr(col, "collect", lambda snap, *a, **k: calls.append(snap) or {})

    class Now(col.datetime):
        @classmethod
        def now(cls, tz=None):
            return col.datetime(2026, 3, 2, 7, 5, tzinfo=col.timezone.utc)

    monkeypatch.setattr(col, "datetime", Now)
    assert col.main([]) == 0 and calls == [None], "nothing pending: today's only"
    (lake / "_cache" / "2026-03-01").mkdir(parents=True)
    (lake / col.CURSOR).write_text(json.dumps({"date": "2026-03-01", "pages": {"cards": {"query": "x", "page": 40}}}))
    calls.clear()
    assert col.main([]) == 0 and calls == ["2026-03-01", None]
    calls.clear()
    assert col.main(["--date", "2026-03-02"]) == 0 and calls == ["2026-03-02"], "an explicit date is taken as asked"


def test_one_stale_source_is_named_and_all_stale_is_red_after_the_studies(lake, monkeypatch, capsys):
    m = Market(date(2026, 3, 1), n_sets=3, per_set=20)
    meta = col.collect("2026-03-01", min_usd=1.0, client=col.Client(opener=m.opener(), sleep=lambda s: None,
                                                                    spacing=0.0), log=lambda *a: None)
    assert meta["stale"] is None or "never priced" in meta["stale"], "no dumps without --sealed"
    assert col.stale_sources(lake, "2026-03-04") == (
        False, "pokemon: stale prices on 2026-03-04: TCGplayer dumps (tcgcsv.com) never priced (limit 3 days)")
    red, line = col.stale_sources(lake, "2026-03-06")
    assert red and "no fresh price" in line and "TCGplayer (pokemontcg.io) since 2026-03-01 (5 days)" in line
    assert "Cardmarket (pokemontcg.io) since 2026-03-01 (5 days)" in line and "\u2014" not in line
    assert col.stale_sources(lake / "nothing", "2026-03-06")[1].count("never priced") == 3

    # Cardmarket frozen since 2026-01-01 on a day the dumps are fresh: named, not red.
    for f in (lake / "meta").glob("*.json"):
        f.unlink()
    frozen = {**meta, "date": "2026-03-06", "sealed": 5,
              "freshness": {**meta["freshness"], "cardmarket_newest": "2026-01-01"}}
    (lake / "meta" / "2026-03-06.json").write_text(json.dumps(frozen))

    class Now(daily.datetime):
        @classmethod
        def now(cls, tz=None):
            return daily.datetime(2026, 3, 6, 9, tzinfo=daily.timezone.utc)

    monkeypatch.setattr(daily, "datetime", Now)
    capsys.readouterr()
    assert daily.main(["--no-alerts", "--no-eval"]) == 0
    err = capsys.readouterr().err
    assert "stale prices on 2026-03-06" in err and "Cardmarket (pokemontcg.io) since 2026-01-01 (64 days)" in err
    assert "TCGplayer dumps" not in err
    rep = json.loads((lake.parent / "reports" / "pokemon" / "latest.json").read_text())
    assert "Cardmarket (pokemontcg.io) since 2026-01-01" in rep["meta"]["stale"]
    assert "- Stale: " in (lake.parent / "reports" / "pokemon" / "latest.md").read_text()

    # Every source stale: the studies still run on the old prices, then red.
    (lake / "meta" / "2026-03-06.json").write_text(json.dumps({**frozen, "date": "2026-03-01", "sealed": 5}))
    (lake / "meta" / "2026-03-06.json").rename(lake / "meta" / "2026-03-01.json")
    (lake / "ui" / "latest.json").unlink()
    assert daily.main(["--no-alerts", "--no-eval"]) == 1
    assert "no fresh price on 2026-03-06" in capsys.readouterr().err
    assert (lake / "ui" / "latest.json").exists(), "the studies still ran on the old prices"


def test_api_key_comes_from_the_environment_only(monkeypatch):
    monkeypatch.setenv("POKEMONTCG_API_KEY", " abc ")
    c = col.client_for(None)
    assert c.headers == {"X-Api-Key": "abc"} and c.spacing < 1
    monkeypatch.delenv("POKEMONTCG_API_KEY")
    c = col.client_for(None)
    assert c.headers == {} and c.spacing >= 2


def test_price_parsing_picks_the_dearest_printing():
    card = {"id": "x-1", "tcgplayer": {"updatedAt": "2026/10/14", "prices": {
        "normal": {"market": 1.0}, "holofoil": {"low": 3, "mid": 5, "market": 4.5}, "reverseHolofoil": {"mid": 2}}},
        "cardmarket": {"updatedAt": "2026/10/14", "prices": {"trendPrice": 3.9, "avg30": 4.2, "avg1": None}},
        "set": {"releaseDate": "2023/09/22"}}
    r = col.card_row(card, "2026-10-14")
    assert r["tp_variant"] == "holofoil" and r["tp_market"] == 4.5 and r["tp_updated"] == "2026-10-14"
    assert r["cm_trend"] == 3.9 and r["cm_avg1"] is None and r["release_date"] == "2023-09-22"
    assert col.keep(r, 4.0, 1.1) and not col.keep(r, 5.0, 1.1)
    r["tp_market"] = None
    assert col.keep(r, 4.0, 1.1), "3.9 EUR at 1.1 is 4.29 USD"
    assert col.usd_value(r, 1.1) == pytest.approx(4.29)


def test_collect_writes_the_lake_and_meta(lake):
    m = Market(date(2026, 3, 1), n_sets=3, per_set=20)
    meta = col.collect("2026-03-01", min_usd=1.0, client=col.Client(opener=m.opener(eurusd=1.17), sleep=lambda s: None,
                                                                    spacing=0.0), log=lambda *a: None)
    assert meta["cards_seen"] == 60 and 0 < meta["cards_kept"] <= 60 and meta["eurusd"] == 1.17
    assert (lake / "cards" / "date=2026-03-01" / "cards.parquet").exists()
    assert pl.read_parquet(lake / "sets" / "date=2026-03-01" / "sets.parquet").height == 3
    assert pl.read_parquet(lake / "catalog.parquet").height == 60, "the catalogue keeps cheap cards too"
    assert json.loads((lake / "fx.json").read_text())["eurusd"] == 1.17


def test_collect_falls_back_to_the_last_fx_rate(lake):
    lake.mkdir(parents=True)
    (lake / "fx.json").write_text(json.dumps({"date": "2026-02-28", "eurusd": 1.09}))
    m = Market(date(2026, 3, 1), n_sets=1, per_set=10)
    inner = m.opener()

    def opener(url, h, t):
        return (500, {}, b"") if "eurofxref" in url else inner(url, h, t)

    meta = col.collect("2026-03-01", min_usd=0.0, client=col.Client(opener=opener, sleep=lambda s: None, spacing=0.0,
                                                                    retries=2), log=lambda *a: None)
    assert meta["eurusd"] == 1.09 and meta["fx_source"] == "last known" and meta["errors"]


def test_sealed_keeps_products_without_a_card_number():
    groups = {"results": [{"groupId": 1, "name": "Stellar Crown", "publishedOn": "2024-09-13T00:00:00"}]}
    prods = {"results": [
        {"productId": 10, "name": "Stellar Crown Booster Box", "extendedData": []},
        {"productId": 11, "name": "Terapagos ex", "extendedData": [{"name": "Number", "value": "128/142"}]}]}
    prices = {"results": [{"productId": 10, "marketPrice": 160.5, "lowPrice": 150, "subTypeName": "Normal"},
                          {"productId": 11, "marketPrice": 30.0}]}

    def opener(url, h, t):
        body = groups if url.endswith("/groups") else prods if url.endswith("/products") else prices
        return 200, {}, json.dumps(body).encode()

    rows = col.fetch_sealed(col.Client(opener=opener, sleep=lambda s: None, spacing=0.0), "2026-10-15")
    assert [r["name"] for r in rows] == ["Stellar Crown Booster Box"] and rows[0]["market"] == 160.5


def test_new_sets_come_from_tcgcsv_singles_and_main_sets_are_always_taken():
    groups = {"results": [
        {"groupId": 1, "name": "SV08: Surging Sparks", "publishedOn": "2024-11-08T00:00:00"},
        {"groupId": 2, "name": "POP Series 4", "publishedOn": "2026-10-14T00:00:00"},
        {"groupId": 3, "name": "ME05: Pitch Black", "publishedOn": "2026-07-17T00:00:00"},
        {"groupId": 4, "name": "XY: Evolutions", "publishedOn": "2016-11-02T00:00:00"}]}
    prods = {g: {"results": [
        {"productId": g * 10, "name": f"Box {g} Booster Box", "extendedData": []},
        {"productId": g * 10 + 1, "name": f"Chase {g}", "extendedData": [{"name": "Number", "value": "200/190"},
                                                                         {"name": "Rarity", "value": "SIR"}]}]}
        for g in (1, 2, 3, 4)}
    prices = {g: {"results": [{"productId": g * 10, "marketPrice": 150.0 + g},
                              {"productId": g * 10 + 1, "marketPrice": 20.0 * g, "subTypeName": "Holofoil"},
                              {"productId": g * 10 + 1, "marketPrice": 1.0, "subTypeName": "Normal"}]}
              for g in (1, 2, 3, 4)}
    asked = []

    def opener(url, h, t):
        asked.append(url)
        if url.endswith("/groups"):
            return 200, {}, json.dumps(groups).encode()
        gid = int(url.rstrip("/").split("/")[-2])
        return 200, {}, json.dumps(prods[gid] if url.endswith("/products") else prices[gid]).encode()

    singles: list[dict] = []
    sealed = col.fetch_sealed(col.Client(opener=opener, sleep=lambda s: None, spacing=0.0), "2026-10-15",
                              groups_back=1, singles=singles)
    taken = {r["group_id"] for r in singles}
    assert taken == {1, 2, 3}, "the newest group plus the main sets of two years; not a 2016 set"
    assert {r["group_id"]: r["main_set"] for r in singles} == {1: True, 2: False, 3: True}
    assert all(r["market"] == 20.0 * r["group_id"] and r["sub_type"] == "Holofoil" for r in singles), "dearest printing"
    assert len(sealed) == 3
    s = pl.DataFrame(singles)
    cross = study.new_sets_cross(s, pl.DataFrame(sealed))
    assert [r["set"] for r in cross] == ["ME05: Pitch Black", "SV08: Surging Sparks"]
    assert cross[0]["age_days"] == 90 and cross[0]["booster_box_usd"] == 153.0 and cross[0]["top10_mean_usd"] == 60.0
    assert not study.new_sets_panel(s, 1)["ready"]


def test_new_sets_panel_follows_the_chase_basket():
    rows = []
    for day in range(45):
        d = (date(2026, 8, 1) + __import__("datetime").timedelta(days=day)).isoformat()
        for k in range(12):
            rows.append({"date": d, "group_id": 3, "group_name": "ME05", "published_on": "2026-07-17",
                         "main_set": True, "product_id": k, "market": (100.0 - k) * math.exp(-0.01 * day)})
    p = study.new_sets_panel(pl.DataFrame(rows), 45)
    assert p["ready"]
    young = {r["set_age"]: r for r in p["rows"]}["0-30 d"]
    assert young["sets"] == 1 and young["mean_30d_pct"] == pytest.approx(math.expm1(-0.3) * 100, rel=1e-6)


# ---------------------------------------------------------------- features and studies

def test_feature_rules():
    assert pdata.rarity_group("Special Illustration Rare") == "chase"
    assert pdata.rarity_group("Double Rare") == "ultra"
    assert pdata.rarity_group("Rare Holo") == "holo"
    assert pdata.rarity_group("Uncommon") == "common"
    # Real strings that a naive substring rule got wrong.
    assert pdata.rarity_group("Rare Holo VSTAR") == "ultra" and pdata.rarity_group("Holo Rare V") == "ultra"
    assert pdata.rarity_group("Rare Holo Star") == "chase" and pdata.rarity_group("Rare Shiny GX") == "chase"
    assert pdata.rarity_group("Rare ACE") == "chase" and pdata.rarity_group("MEGA_ATTACK_RARE") == "ultra"
    assert pdata.rarity_group("Pikachu Rare") == "rare" and pdata.rarity_group(None) == "other"
    assert pdata.character("Charizard ex") == "charizard"
    assert pdata.character("Pikachu VMAX") == "pikachu"
    assert pdata.character("Mewtwo GX") == "mew"
    assert pdata.character("Charmander") is None
    assert pdata.is_secret("201", 197) and not pdata.is_secret("SV49", 197) and not pdata.is_secret("12", 197)
    assert pdata.is_alt_art("Illustration Rare", False) and pdata.is_alt_art("Rare Ultra", True)
    assert not pdata.is_alt_art("Rare Ultra", False)


def test_returns_need_the_same_card_and_source(lake):
    build_lake(10, n_sets=2, per_set=10)
    df = pdata.with_returns(pdata.features(pdata.load_cards()))
    assert pdata.history_days(df) == 10
    first = df.filter(pl.col("date") == "2026-01-01")
    assert first["ret_1d"].null_count() == first.height, "nothing before the first day"
    later = df.filter(pl.col("date") == "2026-01-08")
    assert later["ret_1d"].null_count() == 0 and later["ret_7d"].null_count() == 0
    assert later["ret_30d"].null_count() == later.height
    y = pdata.forward_returns(df, 7)
    one = df.with_columns(y=y).filter((pl.col("card_id") == "s0-5") & (pl.col("date") == "2026-01-02"))
    p0 = df.filter((pl.col("card_id") == "s0-5") & (pl.col("date") == "2026-01-02"))["price"][0]
    p7 = df.filter((pl.col("card_id") == "s0-5") & (pl.col("date") == "2026-01-09"))["price"][0]
    assert one["y"][0] == pytest.approx(math.log(p7 / p0))


def test_premium_regression_finds_the_planted_charizard_premium(lake):
    build_lake(1, n_sets=12, per_set=40)
    df = pdata.with_returns(pdata.features(pdata.load_cards()))
    prem = study.premiums(study.latest(df))
    row = {r["feature"]: r for r in prem["rows"]}
    # Planted at 3x (+200 %); the measured premium must be large and significant.
    assert row["character: charizard"]["premium_pct"] > 80 and row["character: charizard"]["t"] > 3
    assert row["rarity: chase"]["premium_pct"] > row["rarity: rare"]["premium_pct"]
    assert prem["r2"] > 0.5


def test_reprint_events_and_marks():
    cat = pl.DataFrame({"card_id": ["a-1", "b-1", "n-1", "c-1"],
                        "name": ["Pikachu", "Pikachu", "Pikachu", "Bulbasaur"],
                        "text_key": ["Pikachu|60|Gnaw|", "Pikachu|60|Gnaw|", "Pikachu|70|Thunder|", "Bulbasaur|70||"],
                        "release_date": ["2020-01-01", "2026-09-01", "2026-09-10", "2021-01-01"]})
    ann = pl.DataFrame({"name": ["Bulbasaur"], "announced": ["2026-09-20"]})
    ev = study.reprint_events(cat, ann)
    assert set(map(tuple, ev.select("key", "by", "kind").rows())) == {
        ("Pikachu|60|Gnaw|", "text_key", "release"), ("Bulbasaur", "name", "announced")}, \
        "a new Pikachu card with other attacks is not a reprint"
    snap = cat.with_columns(date=pl.lit("2026-10-15"))
    m = study.mark_reprints(snap, ev)
    assert dict(m.select("card_id", "reprinted").rows()) == {"a-1": True, "b-1": False, "n-1": False, "c-1": True}
    # A lake from before text keys falls back to names.
    assert study.reprint_events(cat.drop("text_key"))["by"].unique().to_list() == ["name"]


def test_text_key_ignores_art_and_order():
    a = {"name": "Boss's Orders", "attacks": [], "abilities": []}
    b = {"name": "Pikachu", "hp": "60", "attacks": [{"name": "B"}, {"name": "A"}]}
    c = {"name": "Pikachu", "hp": "60", "attacks": [{"name": "A"}, {"name": "B"}], "images": {"small": "other"}}
    assert col.text_key(b) == col.text_key(c) == "Pikachu|60|A,B|" and col.text_key(a) == "Boss's Orders|||"


def test_studies_wait_for_history_then_report_panels(lake):
    build_lake(35, n_sets=6, per_set=20)
    df = pdata.with_returns(pdata.features(pdata.load_cards()))
    days = pdata.history_days(df)
    s = study.run(df, pdata.load_catalog(), None, days)
    assert s["release"]["panel"]["ready"] and any(r["set_days"] for r in s["release"]["panel"]["rows"])
    assert s["spread"]["cards"] > 0 and s["spread"]["median_pct"] > 0, "the synthetic US price is set above EU"
    short = study.run(df.filter(pl.col("date") <= "2026-01-05"), pdata.load_catalog(), None, 5)
    assert not short["release"]["panel"]["ready"] and short["release"]["panel"]["waiting_days"] == 25


# ---------------------------------------------------------------- models

def test_fair_value_is_out_of_fold_and_explains_prices(lake):
    build_lake(1, n_sets=10, per_set=40)
    df = pdata.features(pdata.load_cards())
    pred, info = model.fair_value(df)
    assert info["r2"] > 0.5 and info["grouped_by"] == "set"
    assert pl.Series(pred).is_finite().all()


def test_prior_rule_is_used_and_labelled_before_history(lake):
    build_lake(3, n_sets=6, per_set=20)
    df = pdata.with_returns(pdata.features(pdata.load_cards()))
    df, _ = model.add_fair_value(df)
    snap, st = model.predict(df)
    assert not st["validated"] and "prior rule" in st["sentence"] and "3 days" in st["sentence"]
    assert (snap["pred_src"] == "prior").all()
    assert snap["pred_90d"].abs().max() <= model.CLIP + 1e-9
    # Cheaper than fair value means a higher prior forecast, all else equal.
    one = snap.with_columns(fv_gap=pl.lit(0.5), cm_trend_30=pl.lit(0.0))
    two = snap.with_columns(fv_gap=pl.lit(-0.5), cm_trend_30=pl.lit(0.0))
    assert (model.prior(one, 90) > model.prior(two, 90)).all()


def test_walk_forward_is_purged_and_validates_a_real_signal(lake):
    build_lake(240, n_sets=8, per_set=30, signal=0.06)
    df = pdata.with_returns(pdata.features(pdata.load_cards()))
    df, _ = model.add_fair_value(df, lake / "_derived" / "fv")
    ev = model.walk_forward(df, 30)
    assert ev["test_months"] >= model.MIN_TEST_MONTHS
    assert ev["mean_rank_ic"] > 0.1 and ev["validated"], ev
    # The cache serves past days on the next run.
    assert len(list((lake / "_derived" / "fv").glob("*.parquet"))) == 240
    snap, st = model.predict(df)
    assert st["horizons"]["30"]["validated"] and set(snap["pred_src"].to_list()) <= {"model", "mixed"}


def test_walk_forward_does_not_validate_noise(lake):
    build_lake(240, n_sets=8, per_set=30, signal=0.0)
    df = pdata.with_returns(pdata.features(pdata.load_cards()))
    df, _ = model.add_fair_value(df, lake / "_derived" / "fv")
    ev = model.walk_forward(df, 30)
    assert ev["test_months"] >= model.MIN_TEST_MONTHS and not ev["validated"], ev
    assert "not validated" in model.status_sentence({30: ev, 90: {"test_months": 0}}, 240)


# ---------------------------------------------------------------- paper collection

def _snap(day: str, prices: dict[str, float], preds: dict[str, float]) -> pl.DataFrame:
    ids = list(prices)
    return pl.DataFrame({"date": [day] * len(ids), "card_id": ids, "name": ids, "set_name": ["S"] * len(ids),
                         "price": [prices[i] for i in ids], "tp_market": [prices[i] for i in ids],
                         "pred_90d": [preds.get(i, 0.0) for i in ids], "image_small": [None] * len(ids)})


def test_collection_buys_monthly_pays_costs_and_holds_90_days(tmp_path):
    d = tmp_path / "paper"
    prices = {f"c{i}": 20.0 for i in range(40)}
    preds = {f"c{i}": 0.4 - i * 0.01 for i in range(40)}
    st = collection.step(_snap("2026-01-01", prices, preds), d)
    assert len(st["holdings"]) == 10 and {h["card_id"] for h in st["holdings"]} == {f"c{i}" for i in range(10)}
    assert all(h["qty"] == 4 for h in st["holdings"]), "100 each at 20 * 1.03 + 1.5 = 22.1 a copy"
    assert st["equity"] < st["equity_market"] < collection.START, "costs on entry, more on exit"
    assert collection.step(_snap("2026-01-01", prices, preds), d)["last_date"] == "2026-01-01"
    assert len(collection.journal(d)) == 1, "a second run the same day changes nothing"
    # Next month the ranking flips, but 31 days is under the 90-day hold: no sale.
    flipped = {f"c{i}": 0.4 - (39 - i) * 0.01 for i in range(40)}
    st = collection.step(_snap("2026-02-01", prices, flipped), d)
    assert {h["card_id"] for h in st["holdings"]} == {f"c{i}" for i in range(10)}
    # After 90 days the holdings out of the top 30 are sold and replaced.
    st = collection.step(_snap("2026-04-01", prices, flipped), d)
    held = {h["card_id"] for h in st["holdings"]}
    assert held.isdisjoint({f"c{i}" for i in range(10)}) and len(held) == 10
    sells = [t for t in collection.trades(d) if t["side"] == "sell"]
    assert len(sells) == 10 and float(sells[0]["cash"]) == pytest.approx(4 * (20 * 0.85 - 1.0))


def test_collection_sells_a_card_whose_price_disappeared(tmp_path):
    d = tmp_path / "paper"
    collection.step(_snap("2026-01-01", {"a": 50.0, "b": 50.0}, {"a": 0.3, "b": 0.2}), d)
    st = collection.step(_snap("2026-02-01", {"b": 60.0}, {"b": 0.2}), d)
    assert [h["card_id"] for h in st["holdings"]] == ["b"]
    assert collection.trades(d)[-1]["why"] == "price missing"


def test_collection_never_buys_weak_forecasts(tmp_path):
    st = collection.step(_snap("2026-01-01", {"a": 50.0}, {"a": 0.01}), tmp_path / "p")
    assert st["holdings"] == [] and st["equity"] == collection.START


# ---------------------------------------------------------------- alerts

# 2026-10-15 12:00 UTC, 14:00 in Berlin: outside the quiet hours, so the
# alert tests do not depend on the hour they run at.
DAYTIME_MS = 1_792_065_600_000


def test_alerts_moves_undervalued_and_cooldown(lake, monkeypatch):
    monkeypatch.setattr(alerts.notify, "clock_ms", lambda: DAYTIME_MS)
    snap = pl.DataFrame({
        "card_id": ["a", "b", "c", "d"], "name": ["A", "B", "C", "D"], "set_name": ["S"] * 4,
        "price": [50.0, 50.0, 5.0, 40.0], "ret_1d": [math.log(1.3), math.log(1.05), math.log(2.0), None],
        "ret_7d": [None, None, None, None], "cm_trend": [40.0, 40.0, 4.0, 30.0], "cm_mom_1_7": [0.0, 0.0, 0.0, 0.5],
        "fv_log": [math.log(200.0), math.log(50.0), 0.0, math.log(40.0)],
        "fv_gap": [math.log(2.5), 0.0, 0.0, 0.0], "set_age_days": [400, 400, 400, 400],
        "pred_90d": [0.2, 0.0, 0.0, 0.0]})
    moves = alerts.strong_moves(snap)
    assert [m["card_id"] for m in moves] == ["d", "a"], "c is under $20; d by Cardmarket, no snapshot return"
    assert [u["card_id"] for u in alerts.undervalued(snap)] == ["a"]
    out = alerts.run(snap, lake, "2026-10-15", validated=False)
    assert "not validated" in out["text"] and "nothing is bought or sold" in out["text"]
    again = alerts.run(snap, lake, "2026-10-16", validated=False)
    assert again["moves"] == [] and again["undervalued"] == [], "7-day cooldown"
    later = alerts.run(snap, lake, "2026-10-22", validated=False)
    assert len(later["moves"]) == 2


def test_alerts_post_to_telegram(lake, monkeypatch):
    monkeypatch.setattr(alerts.notify, "clock_ms", lambda: DAYTIME_MS)
    sent = []
    monkeypatch.setenv("PYTHIA_TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setenv("PYTHIA_TELEGRAM_CHAT_ID", "42")
    monkeypatch.setattr(alerts.notify, "post", lambda url, fmt, text: (sent.append((url, fmt, text)), (True, None))[1])
    snap = pl.DataFrame({"card_id": ["a"], "name": ["A"], "set_name": ["S"], "price": [50.0],
                         "ret_1d": [math.log(0.7)], "ret_7d": [None], "cm_trend": [40.0], "cm_mom_1_7": [0.0],
                         "fv_log": [0.0], "fv_gap": [0.0], "set_age_days": [10], "pred_90d": [0.0]},
                        schema_overrides={"ret_7d": pl.Float64})
    out = alerts.run(snap, lake, "2026-10-15", validated=True)
    assert out["sent"] and sent[0][1] == "telegram" and "-30 %" in sent[0][2]


# ---------------------------------------------------------------- links and what an alert says per card

def test_links_use_the_api_product_pages_and_fall_back_to_an_encoded_search():
    from lab.pokemon import links
    assert links.cardmarket("https://prices.pokemontcg.io/cardmarket/sv3-125", "Charizard ex") == (
        "https://prices.pokemontcg.io/cardmarket/sv3-125", "product")
    assert links.tcgplayer("https://prices.pokemontcg.io/tcgplayer/sv3-125", "Charizard ex")[1] == "product"
    assert links.tcgplayer("https://www.tcgplayer.com/product/717605/x", "Mew ex")[1] == "product"
    # Missing, foreign host, plain http, wrong path on the API host, junk: a search for the exact name.
    for bad in (None, "", "https://evil.example/cardmarket/x", "http://prices.pokemontcg.io/cardmarket/x",
                "https://prices.pokemontcg.io/tcgplayer/x", "https://www.cardmarket.com/a b", 5):
        url, kind = links.cardmarket(bad, "Professor's Research")
        assert kind == "search" and url == ("https://www.cardmarket.com/en/Pokemon/Products/Search"
                                            "?searchString=Professor%27s%20Research")
    url, _ = links.cardmarket(None, "Pikachu & Zekrom-GX #1?x=<y>")
    assert url == ("https://www.cardmarket.com/en/Pokemon/Products/Search"
                   "?searchString=Pikachu%20%26%20Zekrom-GX%20%231%3Fx%3D%3Cy%3E"), "one parameter, nothing leaks"
    assert links.tcgplayer(None, "Mew ex - 152/128")[0] == (
        "https://www.tcgplayer.com/search/pokemon/product?productLineName=pokemon&q=Mew%20ex&view=grid")
    assert links.cardmarket(None, "  ")[0] is None and links.cardmarket(None, None) == (None, "none")
    assert links.search_name("Mew - R/RGB") == "Mew" and links.search_name("Gengar (Prime)") == "Gengar (Prime)"
    assert links.search_name("Porygon-Z") == "Porygon-Z" and links.search_name("Ho-Oh ex - 230") == "Ho-Oh ex"
    lk = links.for_card({"name": "Lugia", "url": "https://www.tcgplayer.com/product/714386/lugia"})
    assert lk["tcgplayerKind"] == "product" and lk["cardmarketKind"] == "search"


def _row(**kw):
    r = {"date": "2026-10-15", "card_id": "sv3-125", "name": "Charizard ex", "set_name": "Obsidian Flames",
         "number": "125", "rarity": "Special Illustration Rare", "tp_variant": "holofoil", "price": 120.5,
         "price_src": "tcgplayer", "tp_updated": "2026-10-15", "cm_trend": 98.0, "cm_avg_sell": 95.1,
         "cm_updated": "2026-07-01", "cm_fresh": False, "fv_log": math.log(180.0), "fv_gap": math.log(180 / 120.5),
         "pred_30d": 0.03, "pred_90d": 0.08, "ret_1d": math.log(1.25), "ret_7d": None, "ret_30d": None,
         "tp_url": "https://prices.pokemontcg.io/tcgplayer/sv3-125", "cm_url": None,
         "image_small": "https://images.pokemontcg.io/sv3/125.png", "set_age_days": 400, "cm_mom_1_7": None}
    r.update(kw)
    return r


def test_card_detail_has_everything_a_buyer_needs():
    d = alerts.detail(_row(), "2026-10-15", {"30": {"validated": False}, "90": {"validated": False}})
    assert d["eur_stale"] and d["eur_age_days"] == 106 and d["condition"] == "ungraded, holofoil printing"
    assert round(d["fair"], 2) == 180.0 and round(d["gap"], 3) == round(180 / 120.5 - 1, 3) and d["trust"] == "low"
    assert d["cardmarketKind"] == "search" and d["tcgplayerKind"] == "product"
    text = notify_text(alerts.card_parts(1, d))
    for want in ("1. Charizard ex", "Obsidian Flames #125", "Special Illustration Rare", "ungraded, holofoil printing",
                 "Now $120.50 (TCGplayer market, 2026-10-15)", "Cardmarket €98.00 trend, €95.10 avg sell",
                 "2026-07-01, ⚠️ 106 days old, stale", "Fair $180.00 (+49 % vs price)", "30 d +3 %", "90 d +8 %",
                 "trust: low", "Change 1 d +25 %", "Cardmarket search https://www.cardmarket.com/en/Pokemon/",
                 "TCGplayer https://prices.pokemontcg.io/tcgplayer/sv3-125"):
        assert want in text, want
    fresh = alerts.detail(_row(cm_updated="2026-10-10"), "2026-10-15")
    assert not fresh["eur_stale"] and "stale" not in alerts.price_line(fresh)
    none = alerts.detail(_row(cm_trend=None), "2026-10-15")
    assert "no Cardmarket price" in alerts.price_line(none)
    tested = alerts.detail(_row(), "2026-10-15", {"30": {"validated": True, "mean_rank_ic": 0.08, "test_months": 6},
                                                  "90": {"validated": True, "mean_rank_ic": 0.05, "test_months": 4}})
    assert tested["trust"] == "tested" and "rank IC 0.08 over 6 months" in tested["trust_words"]
    m = {"move": 0.25, "basis_key": "last"}
    assert alerts.change_line(d, m) == "Moved +25 % since the last snapshot", "the 1-day change is not said twice"
    de = notify_text(alerts.card_parts(1, d, m, "de"))
    for want in ("ungradiert, Druck holofoil", "Jetzt 120,50 $ (TCGplayer-Marktpreis, Do 15. Okt)",
                 "Cardmarket 98,00 € Trend, 95,10 € Durchschnittsverkauf", "⚠️ 106 Tage alt, veraltet",
                 "Fairer Wert 180,00 $ (+49 % ggü. Preis)", "Prognose 30 T +3 %, 90 T +8 %", "Vertrauen: niedrig",
                 "Bewegt +25 % seit dem letzten Stand", "Cardmarket-Suche https://www.cardmarket.com/"):
        assert want in de, want


def notify_text(parts) -> str:
    from lab.ops import notify
    return notify.plain(notify.Card("x", "T", parts=parts).render("telegram"))


def test_an_alert_is_top_five_with_pictures_links_and_fits_telegram(lake, monkeypatch):
    from lab.ops import notify
    sent = []
    monkeypatch.setattr(alerts.notify, "send", lambda cat, cards, photos=None, dry_run=False, **k: (
        sent.append((cat, cards, photos)), {"delivered": True, "reason": None, "error": None})[1])
    rows = [_row(card_id=f"c{i}", name=f"Card {i}", price=50.0 + i, ret_1d=math.log(1.3 + i / 100),
                 image_small=f"https://images.pokemontcg.io/x/{i}.png") for i in range(8)]
    snap = pl.DataFrame(rows, infer_schema_length=None)
    out = alerts.run(snap, lake, "2026-10-15", validated=False)
    assert len(out["moves"]) == 5 and out["sent"]
    cat, cards, photos = sent[0]
    assert cat == "pokemon" and len(photos) == 5 and photos[0][0] == "https://images.pokemontcg.io/x/7.png"
    assert "1. Card 7" in photos[0][1] and "$57.00" in photos[0][1]
    html = notify.render_post(cards, "telegram")
    assert html == "\n\n".join(c.render("telegram") for c in cards), "five cards fit one message whole"
    assert html.count('<a href="') == 10 and len(html) < notify.LIMITS["telegram"]
    assert "Information only" in html and "—" not in html
    assert "_row" not in json.dumps(out, default=str)


def test_new_sets_are_noted_once_with_their_dearest_singles(lake, monkeypatch):
    sent = []
    monkeypatch.setattr(alerts.notify, "send", lambda cat, cards, photos=None, dry_run=False, **k: (
        sent.append((cards, photos)), {"delivered": False, "reason": "no destination", "error": None})[1])
    def single(day, pid, gid, gname, pub, market, main=True):
        return {"date": day, "product_id": pid, "group_id": gid, "group_name": gname, "published_on": pub,
                "main_set": main, "name": f"Mew ex - {pid}/128", "number": f"{pid}/128", "rarity": "SIR",
                "image_url": f"https://tcgplayer-cdn.tcgplayer.com/product/{pid}_200w.jpg",
                "url": f"https://www.tcgplayer.com/product/{pid}/x", "sub_type": "Holofoil", "low": 1.0,
                "mid": 1.0, "market": market}
    rows = [single("2026-10-15", p, 1, "ME: New", "2026-10-01", 10.0 + p) for p in range(12)]
    rows += [single("2026-10-14", 11, 1, "ME: New", "2026-10-01", 20.0)]
    rows += [single("2026-10-15", 100 + p, 2, "SV: Old", "2025-01-01", 50.0) for p in range(12)]
    rows += [single("2026-10-15", 200 + p, 3, "Promos", "2026-10-10", 50.0, main=False) for p in range(12)]
    singles = pl.DataFrame(rows)
    snap = pl.DataFrame({"card_id": ["a"], "name": ["A"], "set_name": ["S"], "price": [5.0], "ret_1d": [None],
                         "ret_7d": [None], "cm_trend": [None], "cm_mom_1_7": [None], "fv_log": [0.0], "fv_gap": [0.0],
                         "set_age_days": [10], "pred_90d": [0.0]},
                        schema_overrides={"ret_1d": pl.Float64, "ret_7d": pl.Float64, "cm_trend": pl.Float64,
                                          "cm_mom_1_7": pl.Float64})
    out = alerts.run(snap, lake, "2026-10-15", validated=False, singles=singles)
    assert [s["set"] for s in out["newSets"]] == ["ME: New"]
    cards, photos = sent[0]
    text = notify_text(cards[0].parts)
    assert "1. Mew ex (ME: New #11/128" in text and "+5 %" in text, "the dearest first, with its change"
    assert "searchString=Mew%20ex" in text and "https://www.tcgplayer.com/product/11/x" in text
    assert "no fair value or forecast" in text.lower() and len(photos) == 5
    again = alerts.run(snap, lake, "2026-10-16", validated=False, singles=singles)
    assert again["newSets"] == [], "a set is noted once"


# ---------------------------------------------------------------- the daily job

def test_daily_job_writes_ui_report_collection_and_monthly(lake):
    m = Market(date(2026, 1, 20), n_sets=6, per_set=25)
    for _ in range(15):
        col.collect(m.day.isoformat(), min_usd=1.0, client=col.Client(opener=m.opener(), sleep=lambda s: None,
                                                                       spacing=0.0), log=lambda *a: None)
        daily.run(send_alerts=False, evaluate=False)
        m.step()
    ui = json.loads((lake / "ui" / "latest.json").read_text())
    assert ui["snapshot"] == "2026-02-03" and ui["historyDays"] == 15 and ui["cards"]
    c = ui["cards"][0]
    for k in ("id", "name", "image", "priceUsd", "change1dPct", "change30dPct", "pred30dPct", "pred90dPct", "predSrc",
              "fairUsd", "history"):
        assert k in c
    assert c["predSrc"] == "prior" and len(c["history"]) == 15
    assert ui["collection"]["started"] == "2026-01-20" and len(ui["collection"]["curve"]) == 15
    assert not ui["model"]["validated"] and "prior rule" in ui["model"]["sentence"]
    rep = json.loads((lake.parent / "reports" / "pokemon" / "latest.json").read_text())
    assert "prior rule" in rep["verdict"]
    md = (lake.parent / "reports" / "pokemon" / "latest.md").read_text()
    assert "Data and paper only" in md and "\u2014" not in md
    assert (lake.parent / "reports" / "pokemon" / "monthly" / "2026-01.md").exists(), "February's first run"
    text = (lake / "ui" / "latest.json").read_text()
    assert "NaN" not in text and "Infinity" not in text


def test_daily_without_a_snapshot_is_a_no_op(lake):
    assert daily.run() == {}


# ---------------------------------------------------------------- stale sources (found on the first real run)

def test_stale_cardmarket_does_not_count_as_todays_price():
    card = {"id": "x-2", "tcgplayer": {}, "cardmarket": {"updatedAt": "2026/07/01", "prices": {"trendPrice": 30.0}},
            "set": {"releaseDate": "2023/09/22"}}
    r = col.card_row(card, "2026-10-15")
    assert not col.fresh(r["cm_updated"], "2026-10-15", col.CM_FRESH_DAYS)
    assert col.fresh("2026-10-05", "2026-10-15", col.CM_FRESH_DAYS) and not col.fresh(None, "2026-10-15", 14)
    assert not col.keep(r, 2.0, 1.1), "a Cardmarket trend from July is not today's price"
    assert col.usd_value(r, 1.1) is None
    f = col.freshness([r, {**r, "cm_updated": "2026-10-14", "tp_market": 5.0, "tp_updated": "2026-10-15"}], "2026-10-15")
    assert f["cardmarket_cards"] == 2 and f["cardmarket_fresh"] == 1 and f["cardmarket_newest"] == "2026-10-14"
    assert f["tcgplayer_cards"] == 1 and f["tcgplayer_fresh"] == 1


def test_stale_cardmarket_rows_have_no_cardmarket_features():
    df = pl.DataFrame({
        "date": ["2026-10-15", "2026-10-15"], "card_id": ["a", "b"], "name": ["A", "B"], "rarity": ["Rare"] * 2,
        "number": ["1", "2"], "set_printed_total": [100, 100], "release_date": ["2025-01-01"] * 2,
        "supertype": ["Pokémon"] * 2, "price": [10.0, 10.0], "tp_market": [10.0, 10.0], "tp_low": [8.0, 12.0],
        "cm_trend": [9.0, 9.0], "cm_avg1": [9.0, 9.0], "cm_avg7": [8.0, 8.0], "cm_avg30": [7.0, 7.0],
        "cm_updated": ["2026-10-14", "2026-07-01"], "eurusd": [1.1, 1.1]})
    f = pdata.features(df)
    assert f["cm_fresh"].to_list() == [True, False] and f["cm_age_days"].to_list() == [1, 106]
    for c in ("cm_trend_30", "cm_mom_1_7", "cm_mom_7_30", "spread"):
        assert f[c][0] is not None and f[c][1] is None, c
    assert f["tp_low_gap"][0] == pytest.approx(math.log(0.8)) and f["tp_low_gap"][1] == pytest.approx(math.log(1.2))


def test_sets_are_rebuilt_from_the_cards_when_the_sets_endpoint_fails(lake):
    m = Market(date(2026, 3, 1), n_sets=3, per_set=10)
    inner = m.opener()

    def opener(url, h, t):
        return (500, {}, b"") if "/sets" in url else inner(url, h, t)

    meta = col.collect("2026-03-01", min_usd=0.0, client=col.Client(opener=opener, sleep=lambda s: None, spacing=0.0,
                                                                    retries=2), log=lambda *a: None)
    assert meta["sets_source"] == "cards" and any("sets" in e for e in meta["errors"])
    sets = pl.read_parquet(lake / "sets" / "date=2026-03-01" / "sets.parquet")
    assert sets.height == 3 and sets["release_date"].null_count() == 0
    assert meta["freshness"]["tcgplayer_fresh"] == meta["cards_kept"]


def test_promos_set_level_and_a_sober_prior():
    assert pdata.rarity_group("Promo") == "promo" and pdata.rarity_group("Rare Holo") == "holo"
    snap = pl.DataFrame({"set_id": ["a", "a", "a", "b"], "rarity_group": ["rare", "rare", "holo", "rare"],
                         "log_price": [1.0, 3.0, 5.0, 2.0]})
    s = model.with_set_level(snap)
    assert s["loo_set"].to_list() == [4.0, 3.0, 2.0, None], "the card's own price never counts"
    assert s["loo_set_rarity"].to_list() == [3.0, 1.0, None, None]
    g = model.prior_gap(np.array([0.0, 0.5, math.log(4.0), math.log(6.0), -math.log(6.0), np.nan]))
    assert g[0] == 0 and 0 < g[1] < 0.5 and g[1] < g[2] < model.GAP_CLIP, "smooth, no ties at the cap"
    assert g[3] == 0 and g[4] == 0 and g[5] == 0, "beyond a factor of 5 is model error"
    p = model.prior(pl.DataFrame({"fv_gap": [math.log(4.0), 0.0], "cm_trend_30": [None, None]},
                                 schema={"fv_gap": pl.Float64, "cm_trend_30": pl.Float64}), 90)
    assert 0.05 < p[0] < 0.12 and p[1] == 0


def test_feed_header_follows_the_lab_convention():
    meta = {"snapshot": "2026-10-15", "cards": 1234,
            "freshness": {"cardmarket_cards": 100, "cardmarket_fresh_share": 0.1, "cardmarket_newest": "2026-07-01"}}
    mstat = {"validated": False, "history_days": 1}
    coll = {"started": "2026-10-15", "returnPct": -24.0, "equity": 760.0, "start": 1000.0}
    al = {"moves": [{"name": "Charizard ex", "set": "151", "move": 0.4, "basis": "over 7 days", "price": 120.0}],
          "undervalued": []}
    top = [{"name": "Pikachu", "set": "Base", "pred90dPct": 12.0, "priceUsd": 20.0, "predSrc": "prior"}]
    now = daily.datetime(2026, 10, 15, 9, tzinfo=daily.timezone.utc)
    h = daily.feed(meta, mstat, coll, al, top, now=now)
    assert h["title"] == "Pokemon cards" and h["status"] == "watch" and h["updated_ms"] > 0
    assert "moved strongly" in h["headline"] and "by hand" in h["headline"]
    labels = [i["label"] for i in h["items"]]
    assert labels[0].startswith("Charizard ex") and "Cardmarket prices are stale" in labels
    assert all(0 <= i.get("importance", 0) <= 100 for i in h["items"])
    quiet = daily.feed(meta, mstat, coll, {"moves": [], "undervalued": []}, top, now=now)
    assert quiet["status"] == "ok" and "nothing unusual" in quiet["headline"]
    late = daily.feed(meta, mstat, coll, al, top, now=daily.datetime(2026, 10, 20, tzinfo=daily.timezone.utc))
    assert late["status"] == "bad" and "has not run for 5 days" in late["headline"]
    assert "—" not in json.dumps(h)
