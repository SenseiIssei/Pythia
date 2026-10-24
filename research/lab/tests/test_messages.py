"""The owner's messages: the pump.fun real-money cards (Alpha phase, colour by outcome,
SOL and euro), their charts, the morning briefing at 09:00 Berlin across summer and
winter time, and Discord (embeds, the chart attached, mocked HTTP).

Run from research/lab:  python -m pytest tests/test_messages.py
"""

from __future__ import annotations

import json
import struct
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from lab.ops import briefing, charts, i18n, notify
from lab.pumpfun_rt import card as CARD
from test_i18n import no_english

SOL = 10 ** 9
MINT = "Mint1111111111111111111111111111111111111"
WEBHOOK = "https://discord.com/api/webhooks/123/secret-part"


def utc(*a) -> int:
    return int(datetime(*a, tzinfo=timezone.utc).timestamp() * 1000)


def png_size(b: bytes) -> tuple[int, int]:
    assert b[:8] == b"\x89PNG\r\n\x1a\n", "a PNG"
    return struct.unpack(">II", b[16:24])


@pytest.fixture()
def data(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTHIA_DATA", str(tmp_path))
    for k in ("PYTHIA_REPORTS", "PYTHIA_ALERT_FORMAT", "PYTHIA_ALERT_PREFIX", "PYTHIA_ALERT_WEBHOOK",
              "PYTHIA_TELEGRAM_BOT_TOKEN", "PYTHIA_TELEGRAM_CHAT_ID", "PYTHIA_ALERT_VIA", "PYTHIA_ALERT_LANG",
              notify.DISCORD_ENV, notify.DISCORD_TRADES_ENV):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("PYTHIA_AUTOPILOT_STATE_URL", "off")
    monkeypatch.setenv("PYTHIA_QUIET_HOURS", "off")
    return tmp_path


def write(root, rel: str, d) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d) if not isinstance(d, str) else d, encoding="utf-8")


def closed(ret: float, **kw) -> dict:
    stake = 0.0525
    rec = {"rule": "P_pool0", "mint": MINT, "symbol": "KIMCHINU", "stake_sol": stake,
           "proceeds_sol": stake * (1 + ret), "pnl_sol": stake * ret, "ret": ret, "hold_s": 299.6,
           "exit_why": "time", "lat_buy_ms": 1400, "slip": 0.016, "land_ms": utc(2026, 10, 22, 8, 0),
           "exit_ms": utc(2026, 10, 22, 8, 5), "entry_price": 4.0e-6, "exit_price": 4.0e-6 * (1 + ret)}
    return {**rec, **kw}


# ---------------------------------------------------------------- the pump.fun cards

def test_a_closed_trade_states_its_result_first_with_sol_and_euro():
    p = {"rule": "P_pool0", "symbol": "KIMCHINU", "mint": MINT}
    de = CARD.live_trade_card("closed", p, {"rec": closed(0.325)}, "de", -0.1276, mode="test", eur=158.2)
    assert de.emoji == "🟢" and de.title == "+32,5 % · KIMCHINU"
    text = notify.plain(de.render("telegram", "de"))
    for want in ("Alpha-Phase", "Einsatz", "0,0525 SOL · 8,31 €", "Erlös", "Ergebnis", "+0,0171 SOL · +2,70 €",
                 "Haltedauer", "5 min", "Ausstieg", "Zeitstopp", "1,4 s nach dem Signal", "Notschalter in der App"):
        assert want in text, (want, text)
    assert "TEST" not in text and "Echtgeld-TEST" not in text
    no_english(de.render("telegram", "de"))
    en = CARD.live_trade_card("closed", p, {"rec": closed(0.325)}, "en", -0.1276, mode="test", eur=158.2)
    text = notify.plain(en.render("telegram", "en"))
    assert en.title == "+32.5% · KIMCHINU" and "Alpha phase" in text and "+€2.70" in text and "time stop" in text
    # Without a euro rate the card shows SOL only.
    assert "€" not in notify.plain(CARD.live_trade_card("closed", p, {"rec": closed(0.1)}, "de", 0.0).render())


@pytest.mark.parametrize("ret, emoji", [(0.2, "🟢"), (-0.28, "🔴"), (0.001, "⚪"), (-0.004, "⚪")])
def test_the_colour_follows_the_outcome(ret, emoji):
    c = CARD.live_trade_card("closed", {"rule": "P_pool0", "symbol": "X", "mint": MINT}, {"rec": closed(ret)}, "de")
    assert c.emoji == emoji
    assert notify.DISCORD_COLORS[emoji] == {"🟢": 0x2FB344, "🔴": 0xE66767, "⚪": 0xA3A29A}[emoji]


def test_a_buy_is_blue_a_failure_orange_and_no_card_says_test():
    p = {"rule": "P_pool0", "symbol": "X", "mint": MINT}
    for lang in ("de", "en"):
        b = CARD.live_trade_card("bought", p, {"cost_l": SOL // 20, "tokens": 10 ** 12}, lang, mode="test", eur=150.0)
        f = CARD.live_trade_card("buy_failed", p, {"why": "slippage"}, lang, mode="test")
        s = CARD.live_stop_card("daily", 0.3, 0.3, "test", lang)
        d = CARD.live_daily_card(20_000, {"n": 2, "wins": 2, "pnl_sol": 0.02}, SOL, 0.02, None, "test", "P", lang, 150.0)
        assert (b.emoji, f.emoji, d.emoji) == ("🔵", "🟠", "🟢")
        for c in (b, f, s, d):
            assert "TEST" not in c.render("telegram", lang)
        assert "7,50 €" in notify.plain(b.render("telegram", "de")) if lang == "de" else "€7.50" in b.render()
    sold = CARD.live_leftover_card("sold", {"symbol": "X", "cost_l": SOL // 10, "got_l": SOL // 20}, "test", "de")
    assert sold.emoji == "🔴" and "Alpha-Phase" in sold.title


# ---------------------------------------------------------------- the charts

needs_mpl = pytest.mark.skipif(not charts.available(), reason="matplotlib not installed")


def feed(rec: dict, n: int = 120) -> dict:
    land = rec["land_ms"]
    pts = [[land - 60_000 + i * 3_000, rec["entry_price"] * (1 + 0.002 * (i % 17) - 0.01), 0.1, i % 2]
           for i in range(n)]
    return {"coins": [{"mint": rec["mint"], "land_ms": land, "entry_price": rec["entry_price"], "tp": 0.3,
                       "sl": 0.2, "points": pts}]}


@needs_mpl
def test_a_closed_trade_gets_a_phone_sized_chart_and_none_without_points():
    rec = closed(-0.18)
    img = CARD.trade_chart(rec, "de", feed=feed(rec))
    assert img is not None and png_size(img) == (1200, 900) and 20_000 < len(img) < 1_500_000
    few = feed(rec, n=3)                                       # a line instead of candles
    assert png_size(CARD.trade_chart(rec, "en", feed=few)) == (1200, 900)
    assert CARD.trade_chart(rec, "de", feed={"coins": []}) is None
    assert CARD.trade_chart(rec, "de", feed={"coins": [{**feed(rec)["coins"][0], "points": []}]}) is None
    other = {"coins": [{**feed(rec)["coins"][0], "land_ms": rec["land_ms"] + 1}]}
    assert CARD.trade_chart(rec, "de", feed=other) is None, "another position on the same coin"


def test_the_trade_chart_takes_the_plan_from_the_strategy_without_feed_lines():
    rec = closed(0.1, rule="P_pool0")
    f = feed(rec)
    del f["coins"][0]["tp"], f["coins"][0]["sl"]
    d = CARD.trade_chart_data(rec, f)
    assert d["tp"] and d["sl"] and d["exit"][0] == rec["exit_ms"] and d["entry"] == (rec["land_ms"], rec["entry_price"])


@needs_mpl
def test_the_daily_card_carries_the_days_cumulative_pnl():
    day = utc(2026, 10, 22) // 86_400_000
    ledger = [{"exit_ms": float(utc(2026, 10, 22, h)), "pnl_sol": v} for h, v in ((3, 0.01), (5, -0.03), (9, 0.004))]
    ledger.append({"exit_ms": float(utc(2026, 10, 21, 23)), "pnl_sol": 9.0})          # another day
    pts = CARD.day_curve(day, ledger)
    assert pts[0] == (day * 86_400_000, 0.0) and len(pts) == 4 and abs(pts[-1][1] + 0.016) < 1e-12
    img = CARD.day_chart(day, ledger, "de")
    assert png_size(img) == (1200, 840)
    assert CARD.day_chart(day, [], "de") is None


@needs_mpl
def test_every_chart_draws_in_the_dark_look(tmp_path):
    now = utc(2026, 10, 23, 7)
    aps = [{"name": f"A{k}", "points": [(now - i * 3_600_000, 0.1 * k) for i in range(48, 0, -1)]} for k in range(3)]
    p = charts.render_overview({"autopilots": aps, "pumpfun": [(now - 7_200_000, 0.0), (now, -0.03)]},
                               tmp_path / "o.png", "Morgen-Briefing", "Fr 23. Okt", "de")
    assert png_size(p.read_bytes()) == (1200, 1320)
    p = charts.render_overview({"autopilots": [], "pumpfun": []}, tmp_path / "e.png", "x", "", "de")
    assert png_size(p.read_bytes()) == (1200, 840)
    assert charts.BG == "#1a1a19" and charts.outcome_color(0.2) == charts.UP and charts.outcome_color(-0.2) == charts.DOWN
    assert charts.outcome_color(0.001) == charts.FLAT
    assert charts.candles([(0, 1.0), (1_000, 2.0), (4_999, 0.5), (5_000, 1.5)]) == [(0, 1.0, 2.0, 0.5, 0.5),
                                                                                   (5_000, 1.5, 1.5, 1.5, 1.5)]


# ---------------------------------------------------------------- the briefing at 9:00 in Berlin

@pytest.mark.parametrize("at, ok", [
    ((2026, 3, 28, 8, 0), True),      # winter time: 09:00 CET is 08:00 UTC
    ((2026, 3, 28, 7, 0), False),
    ((2026, 3, 29, 7, 0), True),      # summer time from 01:00 UTC on 29 March: 09:00 CEST is 07:00 UTC
    ((2026, 3, 29, 8, 0), False),
    ((2026, 10, 24, 7, 30), True),
    ((2026, 10, 25, 7, 0), False),    # winter time again from 01:00 UTC on 25 October
    ((2026, 10, 25, 8, 0), True),
    ((2026, 10, 25, 9, 0), False),
])
def test_nine_oclock_in_berlin_summer_and_winter(at, ok):
    assert briefing.due(utc(*at), None) is ok


def test_once_a_day():
    now = utc(2026, 10, 23, 7, 5)
    assert briefing.due(now, "2026-10-22") and not briefing.due(now, "2026-10-23")


def fill_lab(root, now: int) -> None:
    write(root, "live/pumpfun_rt/ledger.csv",
          "mode,rule,mint,exit_ms,pnl_sol,stake_sol,ret\n"
          f"test,P_pool0,{MINT},{now - 20 * 3_600_000},0.012,0.05,0.24\n"
          f"test,P_pool0,{MINT},{now - 19 * 3_600_000},-0.004,0.05,-0.08\n")
    write(root, "reports/pumpfun_rt/live_status.json",
          {"t": now - 60_000, "running": True, "on": True, "balance_sol": 0.72, "pnl_total_sol": -0.03,
           "stake": {"sol": 0.05}})
    write(root, "reports/models/latest.json", {"updated_ms": now - 3_600_000, "models": [
        {"code": "M2", "status": "in use"}, {"code": "M8u", "status": "shadow",
                                              "decisions": [{"date": "2026-10-22", "decision": "promoted"}]}]})
    write(root, "reports/pokemon/latest.json", {"updated_ms": now - 5 * 86_400_000,
                                                "collection": {"equity": 788.45, "returnPct": -21.15}})
    write(root, "reports/trending/latest.json", {"updatedMs": now - 600_000, "alpaca": {"BTC": {"change": -0.0065}},
                                                 "gainers": [{"coin": "BMT", "change": 0.32}]})


def test_the_briefing_is_built_from_the_files_and_leaves_out_stale_sections(data):
    now = utc(2026, 10, 23, 7, 0)
    fill_lab(data, now)
    for lang in ("de", "en"):
        cards, _ = briefing.build(now, lang, [], briefing.read_ledger(), 158.2, {})
        text = notify.plain(notify.render_post(cards, "telegram", lang=lang))
        assert ("Guten Morgen" if lang == "de" else "Good morning") in text
        assert ("pump.fun · Echtgeld" if lang == "de" else "pump.fun · real money") in text
        assert ("+0,0080 SOL · +1,27 €" if lang == "de" else "+0.0080 SOL · +€1.27") in text
        assert "M8u" in text and "BMT" in text
        assert "Pokémon" not in text, "five days old: left out"
        assert cards[0].emoji == "☀️" and cards[1].emoji == "🟢", "the head first, pump.fun green on a plus day"
        if lang == "de":
            no_english(notify.render_post(cards, "telegram", lang="de"))


def test_the_briefing_shows_the_research_lanes(data):
    now = utc(2026, 10, 23, 7, 0)
    fill_lab(data, now)
    write(data, "reports/research/latest.json", {
        "updated_ms": now - 600_000,
        "done": [{"title": "Bomber-Coins (Papier)", "ok": True, "at": now - 3_600_000, "why": "Nein, zu langsam."},
                 {"title": "Alt", "ok": True, "at": now - 3 * 86_400_000, "why": "zu alt"}],
        "running": [{"title": "Realistisches Papier (R1)", "since": now - 600_000}], "queued": 1, "held": ["A1"],
        "budget": {"balance_usd": 47.0, "left_usd": 30.5, "reserve_usd": 10.0, "paused": False}})
    cards, _ = briefing.build(now, "de", [], briefing.read_ledger(), 158.2, {})
    text = notify.plain(notify.render_post(cards, "telegram", lang="de"))
    assert "Forschung" in text and "Bomber-Coins" in text and "Nein, zu langsam." in text
    assert "zu alt" not in text, "only the last 24 hours"
    assert "Realistisches Papier (R1)" in text and "1 warten, 1 zurückgestellt" in text and "30,50" in text
    assert "1 Aufgabe fertig" in text, "in the summary"


def test_the_briefing_paper_line_shows_the_small_wallets_in_euro(data):
    now = utc(2026, 10, 23, 7, 0)
    fill_lab(data, now)
    write(data, "reports/smallaccount/latest.json", {"updated_ms": now - 3_600_000, "books": {
        "small50_tsmom1": {"capital_eur": 50.0, "equity_eur": 48.91},
        "small40_spy_trend": {"capital_eur": 40.0, "equity_eur": 40.5}}})
    for lang, want in (("de", ["Kleinkonten (Papier, EUR)", "small40_spy_trend 40,50 € (+0,50 €)",
                                "small50_tsmom1 48,91 € (-1,09 €)"]),
                       ("en", ["Small wallets (paper, EUR)", "small40_spy_trend €40.50 (+€0.50)"])):
        cards, _ = briefing.build(now, lang, [], briefing.read_ledger(), 158.2, {})
        text = notify.plain(notify.render_post(cards, "telegram", lang=lang))
        assert all(w in text for w in want), text
        if lang == "de":
            no_english(notify.render_post(cards, "telegram", lang="de"))
    assert "smallaccount" in briefing.NOT_STUDIES, "its own line, not a new study"
    assert briefing.small_line({"books": {}}, "de") is None and briefing.small_line(None, "en") is None


def test_the_briefing_goes_out_at_nine_once_to_telegram_and_discord(data, monkeypatch):
    now = utc(2026, 10, 23, 7, 0)
    fill_lab(data, now)
    monkeypatch.setenv(notify.DISCORD_ENV, WEBHOOK)
    tg, dc = [], []
    kw = dict(engines=[], eur=lambda: 150.0, chart=False, poster=lambda text: tg.append(text) or (True, None),
              discord_poster=lambda url, payload, image: dc.append((url, payload)) or (True, None))
    assert briefing.run(now - 3_600_000, **kw) == 0 and not tg, "08:00 in Berlin: not yet"
    assert briefing.run(now, **kw) == 0 and len(tg) == 1 and len(dc) == 1
    assert dc[0][0] == WEBHOOK and dc[0][1]["embeds"][0]["title"].startswith("☀️")
    state = json.loads((data / "notify" / "state.json").read_text())
    assert state["last_briefing"] == "2026-10-23"
    assert json.loads((data / "reports" / "notify" / "latest.json").read_text())["delivered"]
    assert briefing.run(now + 600_000, **kw) == 0 and len(tg) == 1, "once a day"
    write(data, "reports/notify/settings.json", {"categories": [{"id": "dailyPnl", "on": False}]})
    assert briefing.run(now + 86_400_000, **kw) == 0 and len(dc) == 1, "the switch holds Discord back too"


# ---------------------------------------------------------------- Discord

@pytest.fixture()
def hook():
    got: list[tuple[dict, bytes]] = []
    state = {"status": 204}

    class H(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            got.append((dict(self.headers), raw))
            self.send_response(state["status"])
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}/api/webhooks/1/token-part", got, state
    srv.shutdown()


@needs_mpl
def test_a_trade_card_is_a_discord_embed_with_its_chart(hook):
    url, got, state = hook
    rec = closed(0.325)
    c = CARD.live_trade_card("closed", {"rule": "P_pool0", "symbol": "KIMCHINU", "mint": MINT}, {"rec": rec}, "de",
                             mode="test", eur=150.0)
    img = CARD.trade_chart(rec, "de", feed=feed(rec))
    payload = notify.discord_payload([c], "de", img, utc(2026, 10, 23, 7))
    emb = payload["embeds"][0]
    assert emb["title"] == "🟢 +32,5 % · KIMCHINU" and emb["color"] == 0x2FB344
    assert emb["image"] == {"url": "attachment://chart.png"} and "```" not in emb["description"]
    assert [f["name"] for f in emb["fields"]][:3] == ["Einsatz", "Erlös", "Ergebnis"], "the numbers as fields, in order"
    assert emb["description"].endswith("*pump.fun · Echtgeld*"), "the card's own footer last"
    assert emb["footer"]["text"] == "Pythia · Alpha" and payload["allowed_mentions"] == {"parse": []}
    en = notify.discord_payload(notify.in_lang([c], "en"), "en", img, utc(2026, 10, 23, 7))["embeds"][0]
    assert en["title"] == "🟢 +32.5% · KIMCHINU" and en["color"] == 0x2FB344 and en["footer"]["text"] == \
        "Pythia · Alpha phase"
    assert len(en["fields"]) == len(emb["fields"]) and "Alpha phase" in en["description"], "the same layout in English"
    ok, err = notify.post_discord(url, payload, img)
    assert ok and err is None
    headers, raw = got[-1]
    assert headers["Content-Type"].startswith("multipart/form-data")
    assert b'name="payload_json"' in raw and b'name="files[0]"; filename="chart.png"' in raw and img in raw
    ok, _ = notify.post_discord(url, notify.discord_payload([c], "de"))
    assert ok and json.loads(got[-1][1])["embeds"][0]["color"] == 0x2FB344
    state["status"] = 404
    ok, err = notify.post_discord(url, payload)
    assert not ok and err == "HTTP 404" and "token-part" not in err


def test_discord_needs_its_webhook_and_never_raises(data, monkeypatch):
    card = notify.Card("🔵", "Kauf · X", "pump.fun")
    assert notify.send_discord("trades", [card])["reason"] == "no destination"
    monkeypatch.setenv(notify.DISCORD_ENV, "http://plain.example/hook")
    assert notify.discord_url("briefing") is None, "https only"
    monkeypatch.setenv(notify.DISCORD_ENV, WEBHOOK)
    assert notify.discord_url("trades") == WEBHOOK, "the trades fall back to the main webhook"
    monkeypatch.setenv(notify.DISCORD_TRADES_ENV, WEBHOOK + "-trades")
    assert notify.discord_url("trades") == WEBHOOK + "-trades" and notify.discord_url("briefing") == WEBHOOK

    def boom(url, payload, image):
        raise OSError("down")

    res = notify.send_discord("trades", [card], poster=boom)
    assert not res["delivered"] and res["error"] == "OSError"


def test_send_posts_to_discord_only_when_asked_and_switched_on(data, monkeypatch):
    monkeypatch.setenv(notify.DISCORD_ENV, WEBHOOK)
    got = []
    dp = lambda url, payload, image: got.append((payload, image)) or (True, None)   # noqa: E731
    card = notify.Card("🟢", "+5,0 % · X", "pump.fun", image=b"\x89PNG fake")
    notify.send("trades", [card], urgent=True, poster=lambda t: (True, None), discord_poster=dp)
    assert got == [], "a card without discord= stays on Telegram"
    res = notify.send("trades", [card], urgent=True, poster=lambda t: (True, None), discord="trades",
                      discord_poster=dp)
    assert res["discord"]["delivered"] and got[0][1] == b"\x89PNG fake", "the card's own chart is attached"
    write(data, "reports/notify/settings.json", {"categories": [{"id": "trades", "on": False}]})
    notify.send("trades", [card], poster=lambda t: (True, None), discord="trades", discord_poster=dp)
    assert len(got) == 1
    notify.send("trades", [card], dry_run=True, discord="trades", discord_poster=dp)
    assert len(got) == 1


def test_the_live_service_sends_trade_cards_to_discord_too(monkeypatch):
    monkeypatch.setenv("PYTHIA_ALERT_LANG", "de")
    from lab.pumpfun_rt import live_exec as LX
    calls = []
    monkeypatch.setattr(notify, "send", lambda cat, cards, **kw: calls.append((cat, cards, kw)))
    monkeypatch.setattr(notify, "sol_eur", lambda: 150.0)
    p = {"rule": "P_pool0", "symbol": "X", "mint": MINT}
    LX.post_cards(lambda lang: [LX._trade_card("closed", p, {"rec": closed(0.1)}, lang, 0.0, "test", None,
                                               chart_wait_s=0)])
    LX.post_cards(lambda lang: [LX._gate_card("x", "test", lang)])
    assert calls[0][2]["discord"] == "trades" and calls[0][2]["urgent"] and calls[1][2]["discord"] is None
    assert "€" in calls[0][1][0].render()
    de = calls[0][1][0]
    en = notify.in_lang([de], "en", "de")[0]
    assert en is not de and en.lang == "en" and en.render() != de.render(), "Discord gets the card in English too"
    assert notify.in_lang([de], de.lang)[0] is de
    LX.post_cards(lambda lang: 1 / 0)                         # a broken card never stops the book


def test_real_money_fills_go_to_discord_once(data, monkeypatch):
    monkeypatch.setenv(notify.DISCORD_ENV, WEBHOOK)
    ap = {"config": {"name": "Kraken live", "mode": "live", "venue": "kraken",
                     "sleeves": [{"strategyId": "lab:breakout_live"}]}, "state": "running", "startCapital": 42.0,
          "history": [[utc(2026, 10, 22), 42.0], [utc(2026, 10, 23), 43.1]]}
    buy = {"id": "o1", "ts": utc(2026, 10, 22, 10), "strategyId": "lab:breakout_live", "marketId": "crypto:SOL/USD",
           "side": "buy", "status": "filled", "filledQty": 0.1, "avgFillPrice": 180.0, "mode": "live"}
    paper = {**buy, "id": "o0", "mode": "paper"}
    rows = [{"account": "main", "state": {"autopilots": [ap], "orders": [paper, buy]}}]
    got = []
    poster = lambda url, payload, image: got.append(payload) or (True, None)   # noqa: E731
    assert notify.live_fills(utc(2026, 10, 23, 7), rows=rows, poster=poster) == 0 and got == [], "first run: remember"
    sell = {**buy, "id": "o2", "ts": utc(2026, 10, 23, 6), "side": "sell", "avgFillPrice": 198.0}
    rows[0]["state"]["orders"].append(sell)
    notify.live_fills(utc(2026, 10, 23, 7), rows=rows, poster=poster)
    notify.live_fills(utc(2026, 10, 23, 7, 2), rows=rows, poster=poster)
    assert len(got) == 1
    emb = got[0]["embeds"][0]
    assert emb["color"] == 0x2FB344 and "+10.0 %" in emb["title"] and "SOL" in emb["title"]


def test_sol_in_euro_from_the_engine_or_kraken(monkeypatch):
    monkeypatch.setattr(notify, "_SOL_EUR", {})
    monkeypatch.setenv("PYTHIA_AUTOPILOT_STATE_URL", "http://127.0.0.1:8788/api/state")
    asked = []

    def fetch(url):
        asked.append(url)
        if "pumpfun" in url:
            raise OSError("engine down")
        return {"error": [], "result": {"SOLEUR": {"c": ["158.20", "1"], "o": "150.0"}}}

    assert notify.sol_eur(fetch) == 158.2 and len(asked) == 2 and asked[0].endswith("/api/pumpfun/live")
    assert notify.sol_eur(fetch) == 158.2 and len(asked) == 2, "kept for a minute"
    assert notify.parse_sol_eur({"result": {}}) is None
    assert i18n.eur(-2.5, 2, "de", True) == "-2,50 €" and i18n.eur(2.5, 2, "en", True) == "+€2.50"
    assert i18n.duration(299.6, "de") == "5 min" and i18n.duration(42, "en") == "42 s"
    assert i18n.secs(850) == "850 ms" and i18n.secs(1400, "de") == "1,4 s"
