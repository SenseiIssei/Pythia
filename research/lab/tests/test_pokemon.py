"""Pokemon cards: collector, studies, models, paper collection, alerts, daily job.

Everything runs on a made-up market (tests/pokemon_synth.py) served through a
fake HTTP opener; no network. Run from research/lab:  python -m pytest tests
"""

from __future__ import annotations

import json
import math
import sys
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

def test_alerts_moves_undervalued_and_cooldown(lake, monkeypatch):
    snap = pl.DataFrame({
        "card_id": ["a", "b", "c", "d"], "name": ["A", "B", "C", "D"], "set_name": ["S"] * 4,
        "price": [50.0, 50.0, 5.0, 40.0], "ret_1d": [math.log(1.3), math.log(1.05), math.log(2.0), None],
        "ret_7d": [None, None, None, None], "cm_trend": [40.0, 40.0, 4.0, 30.0], "cm_mom_1_7": [0.0, 0.0, 0.0, 0.5],
        "fv_log": [math.log(200.0), math.log(50.0), 0.0, math.log(40.0)],
        "fv_gap": [math.log(4.0), 0.0, 0.0, 0.0], "set_age_days": [400, 400, 400, 400],
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
