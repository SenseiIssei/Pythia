"""The language of the messages to the chat: the catalog has every key in
both languages, German numbers and dates, the setting (PYTHIA_ALERT_LANG over
settings.json), and a sample of every kind of message in German with no
English left in it.

Run from research/lab:  python -m pytest tests/test_i18n.py
"""

from __future__ import annotations

import json
import os
import re
import string
from datetime import date, datetime, timezone

import pytest

from lab.ops import charts, i18n, listings, notify, trending

NOW = int(datetime(2026, 10, 15, 6, 50, tzinfo=timezone.utc).timestamp() * 1000)

# English words that must not be in a German message. Trading words that are
# German enough (Sharpe, Drawdown, Stop, Take-Profit, Paper, Demo, Live, Coin,
# Orders, Autopilot, Backtest, Pool, Job) are not listed.
ENGLISH = set("""
the and of is are to at on by from with for its was were now not no new more
equity fees fee trades trade today since running week weekly daily
held back quiet hours post posts time health check checks green red report learning last
price value amount change ago muted range outside message alert alerts loss floor peak gain
buy sell bought sold side total best worst sleeve sleeves positions cash chart
strong moves cheap similar cards fair forecast data only nothing bought listing listed lists list
unknown keys pair coin coins first yet volume median watch hype risk high
tokens watched source answered gainers surges liquidity flags thin few sells pump
factory strategies tried trials noise bar sample held shadow books running promoted retired
fails passes forward month inputs trained retrain models challenger
gap drop sales days median against after fees funds lock steam wallet look page
""".split())
# Names and words in the samples that read the same in German.
SAME = {"coin", "coins", "median", "pool", "job", "demo", "paper", "live", "stop", "sharpe", "drawdown", "backtest", "memecoin",
        "orders", "cardmarket", "skinport", "steam", "alpaca", "kraken", "binance", "wallet", "hype", "dex",
        "fdv", "oos", "bps", "rmse", "har", "dm", "btc", "usd", "eur"}


def english_left(text: str) -> list[str]:
    # A compound (On-Chain-Token, Paper-Bücher) is one German word.
    words = re.findall(r"[A-Za-zÄÖÜäöüß]+(?:-[A-Za-zÄÖÜäöüß]+)*", notify.plain(text))
    return [w for w in words if w.lower() in ENGLISH and w.lower() not in SAME]


def no_english(text: str) -> None:
    left = english_left(text)
    assert not left, f"English left in the German text: {left}\n{notify.plain(text)}"
    assert "—" not in text, "no em dash"


# ---------------------------------------------------------------- the catalog

def fields(v) -> set[str]:
    parts = v if isinstance(v, tuple) else (v,)
    return {f for p in parts for _, f, _, _ in string.Formatter().parse(p) if f}


def test_every_key_is_in_both_languages_with_the_same_placeholders():
    en, de = i18n.CATALOG["en"], i18n.CATALOG["de"]
    assert set(en) == set(de), f"missing in German: {set(en) - set(de)}; missing in English: {set(de) - set(en)}"
    for k in en:
        assert isinstance(en[k], tuple) == isinstance(de[k], tuple), k
        assert fields(en[k]) == fields(de[k]), k
        for v in (en[k], de[k]):
            for p in v if isinstance(v, tuple) else (v,):
                assert "—" not in p, k


def test_every_german_text_renders_without_english():
    for k, v in i18n.CATALOG["de"].items():
        kw = {f: "X" for f in fields(v)}
        kw.pop("n", None)
        text = i18n.t(k, "de", n=2, **kw) if "n" in fields(v) or isinstance(v, tuple) else i18n.t(k, "de", **kw)
        assert text.strip(), k
        no_english(text)


def test_a_count_picks_one_or_many_and_a_missing_language_is_english():
    assert i18n.t("running", "en", n=1) == "1 autopilot running."
    assert i18n.t("running", "de", n=3) == "3 Autopiloten laufen."
    assert i18n.t("running", "fr", n=1) == "1 autopilot running."
    assert i18n.parse("Deutsch") == "de" and i18n.parse("en-GB") == "en" and i18n.parse("fr") is None


# ---------------------------------------------------------------- numbers and dates

def test_german_numbers():
    de = "de"
    assert i18n.money(1234.56, 2, de) == "1.234,56 $"
    assert i18n.money(-12.3, 2, de) == "-12,30 $"
    assert i18n.money(-0.001, 2, de) == "0,00 $", "no minus zero"
    assert i18n.signed_money(1234.5, 2, de) == "+1.234,50 $"
    assert i18n.signed_pct(3.2, 1, de) == "+3,2 %"
    assert i18n.signed_pct(-0.004, 2, de) == "+0,00 %"
    assert i18n.signed_pct(None, 2, de) == "k. A."
    assert i18n.num(12345.678, 2, de) == "12.345,68"
    assert i18n.frac_pct(0.123, 1, de) == "+12,3 %"
    assert i18n.times(2.5, 1, de) == "2,5x"
    assert i18n.short_money(3_400_000, de) == "3,4 Mio. $"
    assert i18n.short_money(1_200_000_000, de) == "1,2 Mrd. $"
    assert i18n.short_money(12_000, de) == "12,0 Tsd. $"
    assert i18n.short_money(950, de) == "950 $"
    assert i18n.plain_num(0.1234, de) == "0,1234"
    # English is as it was.
    assert i18n.money(12345.678) == "$12,345.68" and i18n.signed_pct(1.234) == "+1.23 %"
    assert i18n.frac_pct(0.123) == "+12.3%" and i18n.short_money(3_400_000) == "$3.4M"
    assert notify.money(1234.5, lang="en") == "$1,234.50" and notify.money(1234.5, lang="de") == "1.234,50 $"


def test_german_dates_in_berlin_time():
    assert i18n.day_label(date(2026, 10, 15), "de") == "Do 15. Okt"
    assert i18n.day_label(date(2026, 10, 15), "en") == "Thu 15 Oct"
    assert i18n.day_label(date(2026, 3, 2), "de") == "Mo 2. Mär"
    assert i18n.span(date(2026, 10, 9), date(2026, 10, 15), "de") == "9. bis 15. Okt"
    assert i18n.span(date(2026, 9, 28), date(2026, 10, 4), "de") == "28. Sep bis 4. Okt"
    assert i18n.span(date(2026, 9, 28), date(2026, 10, 4), "en") == "28 Sep to 4 Oct"
    assert i18n.iso_day("2026-10-15", "de") == "Do 15. Okt" and i18n.iso_day("2026-10-15", "en") == "2026-10-15"
    # 08:00 UTC in October is 10:00 in Berlin, in December 09:00.
    assert i18n.when_iso("2026-10-15T08:00:00Z", "de", notify.local_time) == "Do 15. Okt, 10:00"
    assert i18n.when_iso("2026-12-15T08:00:00Z", "de", notify.local_time) == "Di 15. Dez, 09:00"
    assert i18n.when_iso("2026-10-15T08:00:00Z", "en", notify.local_time) == "2026-10-15T08:00:00Z"
    assert notify.day_label(NOW, "de") == "Do 15. Okt"


def test_chart_words_amounts_and_dates():
    assert charts._money(31.2, "de") == "+31,20 $" and charts._money(31.2) == "+$31.20"
    assert charts._money(-1240, "de") == "-1.240 $" and charts._money(-1240) == "-$1,240"
    assert charts._money(12_500, "de") == "+12,5 Tsd. $" and charts._money(12_500) == "+$12.5k"
    assert charts._tick_money(0, True, "de") == "0 $" and charts._tick_money(40, True, "de") == "+40 $"
    assert charts._plain_money(950, "de") == "950 $"
    assert charts._pct_tick(0.5, "de") == "+0,5 %" and charts._pct_tick(3, "de") == "+3 %"
    assert charts._date_tick(datetime(2026, 10, 15), "de") == "15. Okt"
    assert charts._date_tick(datetime(2026, 10, 15), "en") == "15 Oct"
    assert i18n.t("pnl_per_sleeve", "de") == "GuV je Teilportfolio"


# ---------------------------------------------------------------- the setting

@pytest.fixture()
def reports(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTHIA_REPORTS", str(tmp_path))
    monkeypatch.delenv(i18n.ENV, raising=False)
    return tmp_path


def set_lang(root, lang: str, at: int) -> None:
    p = root / "notify" / "settings.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"categories": [], "language": lang}), encoding="utf-8")
    os.utime(p, ns=(at, at))


def test_the_language_comes_from_the_environment_then_the_settings_file(reports, monkeypatch):
    assert notify.alert_lang() == "en", "English without a setting"
    set_lang(reports, "de", 1_000_000_000_000_000_000)
    assert notify.alert_lang() == "de"
    set_lang(reports, "en", 1_000_000_001_000_000_000)
    assert notify.alert_lang() == "en", "a changed file is read again"
    set_lang(reports, "de", 1_000_000_002_000_000_000)
    monkeypatch.setenv(i18n.ENV, "en")
    assert notify.alert_lang() == "en", "PYTHIA_ALERT_LANG wins"
    monkeypatch.setenv(i18n.ENV, "klingon")
    assert notify.alert_lang() == "de", "a value that is no language leaves the setting"
    monkeypatch.delenv(i18n.ENV)
    (reports / "notify" / "settings.json").write_text("[1, 2]", encoding="utf-8")
    os.utime(reports / "notify" / "settings.json", ns=(1_000_000_003_000_000_000,) * 2)
    assert notify.alert_lang() == "en"


def test_the_settings_file_the_engine_writes_round_trips(reports):
    """The engine writes AlertSettings::view: "language" next to the switches."""
    view = {"categories": [{"id": "trades", "on": False}], "quietHours": {"enabled": False},
            "bigMoves": {"hourPct": 3, "dayPct": 8}, "language": "de", "languageEnv": None}
    (reports / "notify").mkdir(parents=True)
    (reports / "notify" / "settings.json").write_text(json.dumps(view), encoding="utf-8")
    assert notify.alert_lang() == "de"
    s = notify.load_settings()
    assert s["on"] == {"trades": False} and s["quiet"]["enabled"] is False


# ---------------------------------------------------------------- a sample of every kind, in German

def learn_report():
    return {
        "generated": "2026-10-15 06:30 UTC", "generated_ms": NOW - 20 * 60_000,
        "headline": "2 cost updates.", "headlines": {"de": "2 Kostenänderungen."},
        "engine": {"reachable": True, "error": None},
        "autopilots": [
            {"id": "ap1", "name": "Momentum", "mode": "demo", "state": "running", "equity": 1030.0,
             "start_capital": 1000.0, "fees": 3.5, "trades": 12, "pnl_day_pct": 1.0, "btc_day_pct": 0.5,
             "pnl_total_pct": 3.0, "btc_total_pct": 1.5, "vs_btc_total_pts": 1.5},
        ],
    }


def test_the_daily_digest_in_german():
    fwd = {"books": [{"name": "tsmom", "status": "on_track"}, {"name": "m4_ls", "status": "watch"}]}
    health = {"at": "2026-10-15T06:07:00Z", "ok": True, "checks": []}
    card, _ = notify.digest_card(learn_report(), fwd, health, {"ap1": {"trades": 10, "fees": 3.0, "at": NOW - 3_600_000}},
                                 NOW, "de")
    html = notify.render_post([card], lang="de")
    text = notify.plain(html)
    assert card.title == "Tagesbericht · Do 15. Okt"
    assert "1 Autopilot läuft, heute +10,20 $ 🟢 · BTC +0,50 %" in text, text
    assert "Momentum · Demo" in text and "1.030,00 $" in text and "+1,50 Pkt." in text
    assert "Abschlüsse heute" in text and "2 · Gebühren 0,50 $" in text
    assert "Vorwärtstest tsmom ✅ im Plan · m4_ls 👀 beobachten" in text
    assert "Systemzustand ✅ alles grün" in text and "Lernen 2 Kostenänderungen." in text
    no_english(html)
    # English reads as it did.
    en = notify.plain(notify.render_post([notify.digest_card(learn_report(), fwd, health, {}, NOW, "en")[0]], lang="en"))
    assert "Daily · Thu 15 Oct" in en and "1 autopilot running" in en and "Learning 2 cost updates." in en


def engine_state():
    start = NOW - 9 * notify.DAY_MS
    return {"autopilots": [
        {"config": {"id": "ap1", "name": "Momentum", "mode": "paper"}, "state": "running", "startedMs": start,
         "startCapital": 1000, "equity": 1031.0, "history": [[start, 1000], [NOW - notify.WEEK_MS, 1010]],
         "trades": 31, "drawdownPct": 1.2, "bySleeve": [{"name": "tsmom", "pnl": 31.2}, {"name": "m4", "pnl": -6.4}]}]}


def test_the_weekly_report_in_german():
    card, _ = notify.weekly_card(engine_state(), {"ap1": {"trades": 20, "at": NOW - notify.WEEK_MS}}, NOW, 1.0, "de")
    html = notify.render_post([card], lang="de")
    assert card.title == "Wochenbericht · 8. bis 15. Okt"
    text = notify.plain(html)
    assert "Diese Woche" in text and "11 diese Woche" in text and "Unter Höchststand" in text and "1,20 %" in text
    assert "Bestes Teilportfolio tsmom +31,20 $ · schwächstes m4 -6,40 $" in text
    assert "1 Autopilot: diese Woche +21,00 $" in text
    no_english(html)
    assert notify.weekly_card(None, {}, NOW, None, "de")[0].summary.startswith("Pythia hat nicht geantwortet")


def test_quiet_hours_note_and_health_alarm_in_german(reports, monkeypatch):
    set_lang(reports, "de", 1_000_000_000_000_000_000)
    monkeypatch.setenv("PYTHIA_DATA", str(reports))
    monkeypatch.setenv("PYTHIA_QUIET_HOURS", "off")
    for k in ("PYTHIA_ALERT_WEBHOOK", "PYTHIA_TELEGRAM_BOT_TOKEN", "PYTHIA_ALERT_PREFIX"):
        monkeypatch.delenv(k, raising=False)
    notify.write_json(notify.held_path(), [{"ts": NOW - i * 60_000, "category": "trending", "title": f"Meldung {i}"}
                                           for i in range(33)])
    sent = []
    monkeypatch.setattr(notify, "send", lambda cat, cards, **kw: sent.append(notify.render_post(cards)) or
                        {"delivered": True, "reason": None})
    assert notify.flush_held(NOW) == 0
    assert "Ruhezeit vorbei" in sent[0] and "33 Labor-Meldungen wurden von 23:00 bis 07:00" in sent[0]
    assert "Zeit" in sent[0] and "+3 weitere" in sent[0]
    no_english(sent[0])
    bad = {"at": "2026-10-15T08:00:00Z", "ok": False, "checks": [{"name": "Platte", "ok": False, "detail": "voll"}]}
    _, st = notify.health_step(bad, {})
    card, st = notify.health_step(dict(bad, at="2026-10-15T09:00:00Z"), st)
    html = notify.render_post([card])
    assert "Systemprüfung seit 2 Läufen rot" in html and "1 Prüfung nicht in Ordnung, Stand Do 15. Okt, 11:00." in html
    no_english(html)
    card, _ = notify.health_step({"at": "2026-10-15T10:00:00Z", "ok": True, "checks": []}, st)
    assert card.title == "Systemprüfung wieder grün" and card.summary == "Seit der Prüfung am Do 15. Okt, 12:00."
    # The post's own small words follow the setting too.
    long = notify.render_post([notify.Card("x", "y", "z" * 300) for _ in range(30)], limit=1000)
    assert "weitere in der App" in long
    assert notify.clip("a\n" * 3000, 100).endswith("(mehr in den Berichten)")


def test_cs2_alerts_in_german():
    from lab.cs2 import book

    gap = {"kind": "gap", "route": "to_steam", "name": "AK-47 | Redline", "strength": 0.082, "ask": 12.5, "list": 15.49}
    drop = {"kind": "drop", "name": "Kilowatt-Kiste", "strength": 0.31, "ref": 1234.5, "vs30": -0.31, "d24": -0.22,
            "sales7": 412}
    gap["text"], drop["text"] = book.describe(gap), book.describe(drop)
    assert gap["text"] == ("buy on Skinport at 12.50, list on Steam at 15.49: +8.2% after fees, paid in Steam wallet "
                           "funds"), "the app keeps the English"
    de = book.alert_text([gap, drop] + [dict(drop, name=f"Kiste {i}") for i in range(8)], "Pythia", lang="de")
    assert de.startswith("Pythia CS2: 10 zum Ansehen (nur Paper, wenn überhaupt von Hand handeln)")
    assert "- Preislücke: AK-47 | Redline: auf Skinport für 12,50 kaufen, auf Steam für 15,49 einstellen: +8,2 %" in de
    assert "- Kurssturz: Kilowatt-Kiste: jetzt 1.234,50, -22,0 % in 24 h, -31,0 % gegenüber dem 30-Tage-Median " \
           "(412 Verkäufe in 7 Tagen)" in de
    assert de.endswith("... und 2 weitere auf der CS2-Seite")
    no_english(de.replace("Redline", ""))
    # An alert kept before the numbers were: its text, whatever the language.
    assert book.describe({"kind": "gap", "text": "old"}, "de") == "old"


def test_cs2_weekly_line_in_german():
    from lab.cs2 import book, run

    st = {"positions": {"a": {}, "b": {}}, "last_trades": [{}, {}, {}]}
    de = run.weekly_message("Pythia", "Paper +3.00% since start, 2 positions.", book.START_EQUITY * 1.03, st, "de")
    assert de == "Pythia CS2 Woche: Paper +3,00 % seit Start, 2 Positionen. 3 Paper-Abschlüsse. Details auf der CS2-Seite."
    en = run.weekly_message("Pythia", "Paper +3.00% since start, 2 positions.", 0, st, "en")
    assert en == "Pythia CS2 weekly: Paper +3.00% since start, 2 positions. 3 paper trades. Details on the CS2 page."


def test_pokemon_message_in_german():
    from lab.pokemon import alerts

    moves = [{"name": "Glurak", "set": "Basis", "price": 1250.0, "move": 0.31, "basis_key": "7d"}]
    uv = [{"name": "Pikachu", "set": "Promo", "price": 12.5, "fair": 30.0, "gap": 1.4, "pred_90d": 0.12}]
    de = alerts.message(moves, uv, "2026-10-15", False, "Pythia", "de")
    assert de.splitlines()[0] == "Pythia Karten Do 15. Okt"
    assert "- Glurak (Basis): +31 % in 7 Tagen, jetzt 1.250,00 $" in de
    assert "- Pikachu (Promo): 12,50 $, fairer Wert 30,00 $ (+140 %), Prognose 90 T +12 %" in de
    assert de.endswith("Nur Daten und Paper; nichts wird gekauft oder verkauft.")
    no_english(de)
    en = alerts.message(moves, uv, "2026-10-15", True, "Pythia")
    assert "- Glurak (Basis): +31 % over 7 days, now $1,250.00" in en and en.startswith("Pythia cards 2026-10-15")


def test_listings_in_german():
    ev = {"event": "listed", "venue": "kraken", "symbol": "XYZ/USD", "base": "XYZ", "quote": "USD", "new_base": True,
          "alpaca_lists": False, "price": 0.1234}
    de = listings.alert_texts([ev], "Pythia", lang="de")
    assert de == ["Pythia neu gelistet: Kraken listet den neuen Coin XYZ: XYZ/USD. Alpaca: führt ihn nicht. "
                  "Erster Preis 0,1234 USD (XYZ/USD).\nNur zur Information: es wird nichts gekauft."]
    no_english(de[0])
    en = listings.alert_texts([ev], "Pythia")
    assert en == ["Pythia new listing: Kraken new coin XYZ: XYZ/USD. Alpaca: does not list it. "
                  "First price 0.1234 USD (XYZ/USD).\nInformation only: nothing is bought."]
    pair = dict(ev, venue="alpaca", new_base=False, alpaca_lists=None, price=None)
    no_english(listings.alert_line([pair], "de"))


def test_trending_in_german():
    s = {"change": 0.25, "qv_ratio": 4.2, "count_ratio": 3.1}
    card = trending.alert_card("DOGE", s, trending.i18n.t("tr_w7_line", "de"), "de")
    html = notify.render_post([card], lang="de")
    assert card.title == "DOGE bei Alpaca +25 % in 24 h"
    assert "4,2x des 28-Tage-Medians" in html and "solche Bewegungen drehen oft binnen Tagen." in html
    no_english(html)
    snap = {"ts": "2026-10-15T08:00:00Z", "alpaca": {"DOGE": s},
            "gainers": [{"coin": "PEPE", "change": 0.4}], "market_surges": [{"coin": "WIF", "qv_ratio": 5.0}],
            "dex": [{"symbol": "XYZ", "chain": "solana", "change_h24": 120, "liquidity_usd": 40_000,
                     "volume_h24": 1_200_000, "flags": ["thin liquidity", "few sells (honeypot?)"]}]}
    card = trending.digest_card(snap, None, "de")
    html = notify.render_post([card], lang="de")
    assert card.title == "Im Trend · Do 15. Okt"
    assert "+120 % 24 h, Liq. 40,0 Tsd. $, Vol. 1,2 Mio. $ [dünne Liquidität; wenige Verkäufe (Verkauf gesperrt?)]" in html
    assert "1 Alpaca-Coin mit Volumendaten, 1 On-Chain-Token beobachtet." in html
    no_english(html)
    en = notify.plain(notify.render_post([trending.digest_card(snap, None)], lang="en"))
    assert "Trending · 2026-10-15" in en and "+120% 24h, liq $40.0k, vol $1.2M [thin liquidity; few sells (honeypot?)]" in en


def factory_run():
    return {"run_id": "2026-10-17", "search": {"evaluated": 40}, "pool_after": {"n_trials": 400, "sr0_annual": 0.85},
            "top": [{"name": "mom20", "is_sharpe": 1.4}],
            "holdout": [{"name": "g1", "oos_sharpe_35bps": 0.6, "deflated_p": 0.3, "decision": "shadow"},
                        {"name": "g3", "oos_sharpe_35bps": -0.2, "deflated_p": 0.9, "decision": "stopped"}],
            "shadows": [{"status": "active", "key": "abcdef12", "days": 12, "return": 0.021}],
            "decisions": [{"status": "retired", "name": "g0", "reason": "deflated p 0.40 over 400 trials",
                           "failed": ["deflated", "forward"]},
                          {"status": "promoted", "name": "g2", "reason": "passes the bar and its forward month"}],
            "verdict": "1 genome(s) promoted to paper books after their forward month."}


def test_factory_digest_in_german():
    from lab.factory import writeup

    de = writeup.digest(factory_run(), "de")
    assert de.splitlines()[0] == ("Fabrik 2026-10-17: 40 neue Strategien getestet, jetzt 400 Versuche im Pool "
                                  "(Rauschschwelle Sharpe 0,85).")
    assert "- g1: OOS 0,60, defl. p 0,30, Schattenlauf" in de and "Schattenbücher in Betrieb: 1: abcdef 12 T +2,1 %." in de
    assert "Ausgemustert: g0 (scheitert an: Deflation, Vorwärtsmonat)" in de
    assert "Übernommen: g2 (besteht die Schwelle und den Vorwärtsmonat)" in de
    assert de.endswith("1 Genom(e) nach dem Vorwärtsmonat als Paper-Bücher übernommen.")
    no_english(de)
    en = writeup.digest(factory_run())
    assert "Retired: g0 (deflated p 0.40 over 400 trials)" in en and "Shadow books: 1 running: abcdef 12d +2.1%." in en


def test_model_alerts_in_german():
    from lab.models import train

    drift = {"kind": "drift", "code": "M10", "title": "Regime-aware daily volatility", "why": "2 of 9 inputs ...",
             "next": "2026-10-20", "worst": [("rv_24h", 7.0)], "n": 2, "total": 9, "days": 14}
    prom = {"kind": "promoted", "code": "M8", "title": "Next-day direction", "published": "v2026-10-15",
            "why": "logloss 0.6812 vs 0.6931 for the baseline (coin flip), lower, DM p 0.012"}
    de = [train.alert_line(i, "de") for i in (drift, prom)]
    assert de[0] == ("M10 Tagesvolatilität mit Regime: Eingaben außerhalb des Trainingsbereichs (rv_24h 7 %). 2 von 9 "
                     "Eingaben lagen mehr als 5 % der letzten 14 Tage außerhalb des Trainingsbereichs. Prognosen "
                     "können bis zum nächsten Training (Di 20. Okt) danebenliegen.")
    assert de[1] == ("M8 Richtung am nächsten Tag: Herausforderer als v2026-10-15 übernommen. logloss 0,6812 ggü. "
                     "0,6931 für die Vergleichsbasis (coin flip), niedriger, DM p 0,012")
    no_english(de[0])
    assert train.alert_line(drift, "en").startswith("M10 Regime-aware daily volatility: inputs outside the trained range")
    sent = []
    train.post_alerts([train.alert_line(i) for i in (drift, prom)], lambda t: sent.append(t) or (True, None),
                      [drift, prom], "de")
    assert sent[0].splitlines()[0].endswith(" Modelle") and "Herausforderer" in sent[0]


def test_learning_headline_in_german():
    from lab.ops import learn

    args = ([{"area": "costs"}, {"area": "costs"}, {"area": "gates"}], [{"model": "m8_direction", "decision": "promoted"}],
            [{"state": "running", "vs_btc_total_pts": 1.5}], [{"step": "sweep", "status": "failed"}])
    de = learn.headline(*args, lang="de")
    assert de == ("Übernommen: m8_direction; 2 Kostenänderungen; 1 Prüfänderung; fehlgeschlagen: sweep; "
                  "1 Autopilot läuft, +1,50 Punkte ggü. BTC seit Start.")
    assert learn.headline(*args) == ("Promoted m8_direction; 2 cost updates; 1 gate change; failed: sweep; "
                                     "1 autopilot running, best +1.50 points against BTC since start.")
    assert learn.headline([], [], [], [], "de") == "Nichts geändert."
