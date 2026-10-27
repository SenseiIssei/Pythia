"""R9: a briefing that asks for decisions. Built from the recorded data folder of 2026-10-27
(tests/fixtures/briefing_2026-10-27, cut down from the lab's, no addresses): "To decide (n)" first by fixed rules,
the real-money card always there and coloured by state, readiness with the closest book and its days, the
"missing today" footer, under 2,000 characters; the lab's off switches (paper cards, Discord news, Discord in one
language) and the sent log the app reads.

Run from research/lab:  python -m pytest tests/test_briefing_r9.py
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pytest

from lab.ops import briefing, notify
from test_i18n import no_english

RECORDED = Path(__file__).parent / "fixtures" / "briefing_2026-10-27"
WEBHOOK = "https://discord.com/api/webhooks/123/secret-part"


def utc(*a) -> int:
    return int(datetime(*a, tzinfo=timezone.utc).timestamp() * 1000)


NOW = utc(2026, 10, 27, 16, 30)               # when the folder was recorded


@pytest.fixture()
def env(tmp_path, monkeypatch):
    for k in ("PYTHIA_REPORTS", "PYTHIA_ALERT_FORMAT", "PYTHIA_ALERT_PREFIX", "PYTHIA_ALERT_WEBHOOK",
              "PYTHIA_TELEGRAM_BOT_TOKEN", "PYTHIA_TELEGRAM_CHAT_ID", "PYTHIA_ALERT_VIA", "PYTHIA_ALERT_LANG",
              "PYTHIA_NOTIFY_ON", notify.DISCORD_ENV, notify.DISCORD_TRADES_ENV, notify.DISCORD_BOT_ENV,
              notify.DISCORD_GUILD_ENV, notify.DISCORD_OWNER_ENV):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("PYTHIA_AUTOPILOT_STATE_URL", "off")
    monkeypatch.setenv("PYTHIA_QUIET_HOURS", "off")
    monkeypatch.setenv("PYTHIA_LOCAL_LLM", "off")
    monkeypatch.setenv("PYTHIA_DATA", str(tmp_path))
    return tmp_path


@pytest.fixture()
def recorded(env):
    shutil.copytree(RECORDED, env, dirs_exist_ok=True)
    return env


def write(root, rel: str, d) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d) if not isinstance(d, str) else d, encoding="utf-8")


def build(lang: str, now: int = NOW, engines=None):
    cards, _ = briefing.build(now, lang, engines or [], briefing.read_ledger(), 160.0, {})
    return cards, briefing.text_of(cards, lang)


# ---------------------------------------------------------------- the recorded day

def test_the_recorded_day_lists_the_budget_the_local_model_and_the_stopped_bot_first(recorded):
    for lang in ("de", "en"):
        cards, text = build(lang)
        first = cards[0]
        assert first.title == ("Zu entscheiden (3)" if lang == "de" else "To decide (3)") and first.emoji == "🟠"
        items = [p.text for p in first.parts]
        assert items[0].startswith("pump.fun-Bot gestoppt seit Sa 24. Okt: gesamt -0,4766 SOL, Wallet 0,0415 SOL"
                                   if lang == "de" else "pump.fun bot stopped since Sat 24 Oct: -0.4766 SOL in all")
        assert items[1] == ("API-Budget überzogen: -165,80 $, die Lanes sind pausiert" if lang == "de"
                            else "API budget overspent: -$165.80, the lanes are paused")
        assert items[2] == ("local-llm ist rot: letzter Lauf mit Exit 125, 74-mal in Folge" if lang == "de"
                            else "local-llm is red: last run failed, exit 125, 74 in a row")
        assert text.startswith(f"🟠 {first.title}\n•"), "the first lines are the decisions"
        assert len(text) < 2000, len(text)
        assert not any("pokemon" in x for x in items), "a red job that touches neither real money nor the briefing"


def test_the_recorded_day_shows_the_stopped_bot_readiness_and_what_is_missing(recorded):
    cards, text = build("de")
    real = next(c for c in cards if c.title == "Echtgeld")
    assert real.emoji == "🛑", "stopped is not green, though its status file is three days old"
    assert "Der pump.fun-Bot steht seit Sa 24. Okt." in text and "Wallet     0,0415 SOL · 6,64 €" in text
    assert "am nächsten" in text and "7 von 9 Regeln, noch 42 Tage" in text, "the closest book and its days"
    assert "Fehlt heute: KI-Kurzbericht (zuletzt Sa 24. Okt)" in text
    assert cards[1].title.startswith("Guten Morgen") and "6 rot:" in text
    _, en = build("en")
    assert "Missing today: AI brief (last Sat 24 Oct)" in en and "closest" in en and "42 days to go" in en


def test_the_recorded_day_gives_way_from_the_end_to_stay_short(recorded):
    cards, text = build("de")
    titles = [c.title for c in cards]
    assert "Echtgeld" in titles and "Forschung" in titles, "real money and research stay"
    assert "Nachrichten" not in titles and "aus Platzgründen weggelassen: Nachrichten" in text, "named in the footer"
    assert cards[-1].footer.endswith(notify.tr("bf_footer", "de"))


# ---------------------------------------------------------------- the rules

def status(now: int, **kw) -> dict:
    return {"t": now - 60_000, "running": True, "on": True, "balance_sol": 0.5, "pnl_total_sol": 0.01,
            "stake": {"sol": 0.05}, **kw}


def ledger(now: int, *pnls: float) -> list[dict]:
    mid = briefing.local_midnight(now)
    return [{"exit_ms": mid - 3_600_000 * (i + 1), "pnl_sol": p, "stake_sol": 0.05, "ret": p / 0.05}
            for i, p in enumerate(pnls)]


def live_ap(state: str, equity: float, start: float = 100.0) -> dict:
    return {"state": {"autopilots": [{"state": state, "equity": equity, "startCapital": start,
                                      "config": {"mode": "live", "name": "Kraken BTC", "venue": "kraken"}}]}}


def test_each_rule_says_what_needs_the_owner(env):
    now = utc(2026, 10, 27, 8, 0)
    d = lambda **kw: briefing.decisions(now, "en", kw.get("status"), kw.get("ledger", []), kw.get("engines", []),
                                        kw.get("research"), kw.get("health"), kw.get("readiness"),
                                        kw.get("factories", {}))
    assert d(status=status(now), ledger=ledger(now, 0.01)) == [], "running and up: nothing"
    assert d(status=status(now), ledger=ledger(now, 0.01, -0.03))[0].startswith("pump.fun bot lost -0.0200 SOL")
    assert d(status=status(now, on=False, gate=["daily loss cap"]))[0] == "pump.fun bot paused: daily loss cap"
    assert d(status=status(now, t=now - 3 * 3_600_000))[0].startswith("pump.fun bot silent since")
    assert d(engines=[live_ap("paused", 101.0)]) == ["Kraken BTC (real money) is paused"]
    assert d(engines=[live_ap("running", 97.0)]) == ["Kraken BTC (real money) -3.0 % since its start"]
    assert d(engines=[live_ap("running", 103.0)]) == []
    assert d(research={"budget": {"balance_usd": 0.0, "left_usd": 12.0}}) == [], "not overspent"
    assert d(research={"budget": {"left_usd": -4.5, "paused": False}}) == ["API budget overspent: -$4.50"]
    red = {"checks": [{"name": "job pokemon", "ok": False, "detail": "x"}, {"name": "job briefing", "ok": False},
                      {"name": "pythia-pumpfun-live", "ok": False, "detail": "not running"},
                      {"name": "job learn", "ok": True}]}
    assert d(health=red) == ["briefing is red", "pythia-pumpfun-live is red: not running"]
    assert briefing.decisions(now, "de", None, [], [], None, red, None, {})[1] == "pythia-pumpfun-live ist rot: läuft nicht"
    ready = {"autopilots": [{"name": "Momentum", "on_account": True, "ready": True},
                            {"name": "Other", "on_account": False, "ready": True}]}
    assert d(readiness=ready) == ["Momentum is ready for a real-money proposal"]
    assert d(factories={"F3": {"winners": ["F3_00042"]}, "F2": None}) == ["F3: F3_00042 cleared the bar"]


def test_the_real_money_card_is_always_there_and_coloured_by_state(env):
    now = utc(2026, 10, 27, 8, 0)
    card = lambda st, led=(), eng=(): briefing.real_money_card(list(led), st, list(eng), now, 160.0, "de")[0]
    assert card(None).emoji == "⚪" and card(None).parts[0].text == "Kein Echtgeld aktiv"
    assert card(status(now), ledger(now, 0.01)).emoji == "🟢"
    assert card(status(now), ledger(now, -0.01)).emoji == "🔴"
    assert card(status(now, on=False, gate=["owner"])).emoji == "🟠"
    assert card(status(now, running=False, on=False)).emoji == "🛑"
    assert card(status(now, t=now - 5 * 86_400_000, running=False)).emoji == "🛑", "at any age"
    assert card(None, eng=[live_ap("running", 99.0)]).emoji == "🔴"
    assert card(None, eng=[live_ap("running", 101.0)]).emoji == "🟢"
    for c in (card(None), card(status(now, running=False)), card(status(now), ledger(now, 0.01, -0.002))):
        no_english(c.render("telegram", "de"))


def test_nothing_to_decide_is_one_green_line(env):
    now = utc(2026, 10, 27, 8, 0)
    write(env, "reports/pumpfun_rt/live_status.json", status(now))
    cards, text = build("de", now)
    assert cards[0].emoji == "🟢" and text.startswith("🟢 Heute nichts zu entscheiden\n\n☀️ Guten Morgen")
    assert cards[2].title == "Echtgeld" and cards[2].emoji == "🟢"
    no_english(notify.render_post(cards, "telegram", lang="de"))


def test_a_long_day_stays_under_two_thousand_characters(env):
    now = utc(2026, 10, 27, 8, 0)
    write(env, "reports/research/latest.json", {"updated_ms": now, "done": [
        {"title": f"Aufgabe {i} " + "x" * 50, "ok": i % 2 == 0, "at": now - 60_000, "why": "y " * 80} for i in range(9)]})
    write(env, "reports/models/latest.json", {"updated_ms": now, "models": [
        {"code": f"M{i}", "status": "shadow", "decisions": [{"date": "2026-10-26", "decision": "kept"}]} for i in range(30)]})
    write(env, "reports/trending/latest.json", {"updatedMs": now, "alpaca": {"BTC": {"change": 0.01}},
                                               "gainers": [{"coin": "ABC", "change": 0.3}]})
    for lang in ("de", "en"):
        cards, text = build(lang, now)
        assert len(text) < 2000 and cards[0].title.startswith(notify.tr("bf_decide_none", lang)[:5])


# ---------------------------------------------------------------- the switches and the sent log

def caller(module: str):
    """A send from `module`, as its own code would call it."""
    ns = {"__name__": module, "notify": notify}
    exec("def post(card, poster):\n    return notify.send('studies', [card], poster=poster)\n", ns)
    return ns["post"]


def test_paper_cards_are_off_until_switched_on(env, monkeypatch):
    sent = []
    poster = lambda text: sent.append(text) or (True, None)
    card = notify.Card("🎯", "Polymarket paper")
    for module in ("lab.polymarket.card", "lab.paper.pumpfun", "lab.pumpfun_rt.live"):
        assert caller(module)(card, poster)["reason"] == "off"
    assert not sent
    assert caller("lab.factory.run")(card, poster)["delivered"], "a study post has no lab switch"
    write(env, "notify/switches.json", {"on": {"polymarketPaper": True}})
    assert caller("lab.polymarket.card")(card, poster)["delivered"]
    assert caller("lab.paper.pumpfun")(card, poster)["reason"] == "off"
    monkeypatch.setenv("PYTHIA_NOTIFY_ON", "pumpfunPaper")
    assert caller("lab.paper.pumpfun")(card, poster)["delivered"], "the environment wins over the file"
    assert caller("lab.polymarket.card")(card, poster)["reason"] == "off"
    assert notify.send("studies", [card], poster=poster, switch="discordNews")["reason"] == "off"
    assert notify.lab_switches() == {"pumpfunPaper": True, "polymarketPaper": False, "discordNews": False,
                                     "discordBoth": False}


def test_discord_news_is_off_and_one_language_by_default(env, monkeypatch):
    calls = []
    monkeypatch.setenv(notify.DISCORD_BOT_ENV, "fake-token")
    monkeypatch.setattr(notify, "_DISCORD_IDS", {})
    write(env, "discord/channels.json", {"de": {"news": "910000000000000010", "studien": "910000000000000005"},
                                         "en": {"news": "911000000000000010", "studies": "911000000000000005"}})
    monkeypatch.setattr(notify, "bot_request", lambda m, p, b=None, image=None, timeout=15:
                        calls.append(p) or (200, {"id": "1"}))
    card = notify.Card("📰", "News")
    assert notify.send_discord("news", [card], lang="de")["reason"] == "off" and not calls
    assert notify.send_discord("studies", [card], lang="de")["delivered"]
    assert calls == ["/channels/910000000000000005/messages"], "German only, to the German channel"
    monkeypatch.setenv("PYTHIA_NOTIFY_ON", "discordNews,discordBoth")
    calls.clear()
    assert notify.send_discord("news", [card], lang="de")["delivered"]
    assert calls == ["/channels/910000000000000010/messages", "/channels/911000000000000010/messages"]


def test_the_sent_log_counts_today_for_the_app(env, monkeypatch):
    now = utc(2026, 10, 27, 8, 0)
    card = notify.Card("🧪", "Study done")
    ok, bad = (lambda t: (True, None)), (lambda t: (False, "HTTP 500"))
    notify.send("studies", [card], now=now, poster=ok)
    notify.send("studies", [card], now=now + 1, poster=bad)
    notify.send("studies", [card], now=now + 2, poster=ok, dry_run=True)
    caller("lab.polymarket.card")(card, ok)
    notify.send("trending", [card], now=now - 86_400_000, poster=ok)            # yesterday: in the log, not today
    write(env, "reports/notify/settings.json", {"categories": [{"id": "cs2", "on": False}]})
    notify.send("cs2", [card], now=now + 3, poster=ok)
    monkeypatch.setenv(notify.DISCORD_ENV, WEBHOOK)
    notify.send_discord("briefing", [card], lang="en", now=now + 4, poster=lambda u, p, i: (True, None))
    rows = notify.read_sent()
    assert len(rows) == 6, "no dry run"
    assert {r["outcome"] for r in rows} == {"sent", "failed", "off"} and all("secret" not in json.dumps(r) for r in rows)
    feed = json.loads((env / "reports" / "notify_sent" / "latest.json").read_text())
    items = {i["label"]: i["value"] for i in feed["items"]}
    assert items["count:sent"] == "2" and items["count:failed"] == "1" and items["count:off"] == "1", items
    assert items["via:telegram"] == "1" and items["via:discord"] == "1" and items["cat:studies"] == "1"
    assert items["switch:polymarketPaper"] == "off" and feed["title"] and feed["status"] == "watch"
    assert feed["headline"].startswith("today 2 sent (discord 1, telegram 1), 1 failed")
    assert "notify_sent" in briefing.NOT_STUDIES, "not a new study in the lab section"


def test_the_sent_log_keeps_its_tail(env, monkeypatch):
    monkeypatch.setattr(notify, "SENT_KEEP", 5)
    for i in range(12):
        notify.log_sent("telegram", "studies", [notify.Card("🧪", f"n{i}")], "sent", utc(2026, 10, 27, 8, 0) + i)
    rows = notify.read_sent()
    assert 5 <= len(rows) <= 10 and rows[-1]["title"] == "n11"


def test_the_briefing_run_posts_once_in_one_language_and_logs_it(recorded, monkeypatch):
    monkeypatch.setenv(notify.DISCORD_ENV, WEBHOOK)
    monkeypatch.setenv("PYTHIA_ALERT_LANG", "de")
    tg, dc = [], []
    assert briefing.run(NOW, force=True, engines=[], eur=lambda: 160.0, chart=False,
                        poster=lambda text: tg.append(text) or (True, None),
                        discord_poster=lambda url, payload, image: dc.append(payload) or (True, None)) == 0
    assert len(tg) == 1 and len(dc) == 1 and dc[0]["embeds"][0]["title"] == "🟠 Zu entscheiden (3)"
    assert len(notify.plain(tg[0])) < 2000
    out = [(r["via"], r["category"], r["outcome"]) for r in notify.read_sent()]
    assert out == [("telegram", "dailyPnl", "sent"), ("discord", "briefing", "sent")]
