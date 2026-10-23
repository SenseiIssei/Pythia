"""Pythia's messages through the Discord bot (lab.ops.notify with PYTHIA_DISCORD_BOT_TOKEN, mocked
HTTP): what goes to which channel and which also as a DM, the channel map from the bot's file or by
name, the webhook as the fallback, and lab.ops.discord_feed (forward report, studies, models, news).

Run from research/lab:  python -m pytest tests/test_discord_routes.py
"""

from __future__ import annotations

import json
import os
import time

import pytest

from lab.ops import discord_feed, notify

GUILD, OWNER = "900000000000000001", "900000000000000002"
DM = "920000000000000009"
TOKEN = "fake-bot-token-never-shown"
WEBHOOK = "https://discord.com/api/webhooks/123/secret-part"
IDS = {"briefing": "910000000000000001", "status": "910000000000000002", "pumpfun-trades": "910000000000000003",
       "konten": "910000000000000004", "studien": "910000000000000005", "paper-buecher": "910000000000000006",
       "modelle": "910000000000000007", "pokemon": "910000000000000008", "cs2-skins": "910000000000000009",
       "news": "910000000000000010"}
NOW = 1_792_747_281_647


@pytest.fixture()
def data(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTHIA_DATA", str(tmp_path))
    for k in ("PYTHIA_REPORTS", "PYTHIA_ALERT_FORMAT", "PYTHIA_ALERT_PREFIX", "PYTHIA_ALERT_WEBHOOK",
              "PYTHIA_TELEGRAM_BOT_TOKEN", "PYTHIA_TELEGRAM_CHAT_ID", "PYTHIA_ALERT_VIA", "PYTHIA_ALERT_LANG",
              "PYTHIA_DISCORD_CHANNELS", notify.DISCORD_ENV, notify.DISCORD_TRADES_ENV, notify.DISCORD_BOT_ENV,
              notify.DISCORD_GUILD_ENV, notify.DISCORD_OWNER_ENV):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("PYTHIA_AUTOPILOT_STATE_URL", "off")
    monkeypatch.setenv("PYTHIA_QUIET_HOURS", "off")
    monkeypatch.setattr(notify, "_DISCORD_IDS", {})
    return tmp_path


def write(root, rel: str, d) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d) if not isinstance(d, str) else d, encoding="utf-8")


class Bot:
    """A fake of notify.bot_request: records (method, path, body, image), answers like Discord."""

    def __init__(self, fail: set[str] | None = None, guild_channels: list[dict] | None = None):
        self.calls: list[tuple] = []
        self.fail = fail or set()
        self.guild_channels = guild_channels or []

    def __call__(self, method, path, body=None, image=None, timeout=15):
        self.calls.append((method, path, body, image))
        if any(path.startswith(f"/channels/{c}/") for c in self.fail):
            return 404, None
        if path == f"/guilds/{GUILD}/channels":
            return 200, self.guild_channels
        if path == "/users/@me/channels":
            return 200, {"id": DM}
        return 200, {"id": "1"}

    def posts(self) -> list[tuple[str, dict, bytes | None]]:
        return [(p.split("/")[2], b, img) for m, p, b, img in self.calls if m == "POST" and p.endswith("/messages")]


@pytest.fixture()
def bot(data, monkeypatch):
    monkeypatch.setenv(notify.DISCORD_BOT_ENV, TOKEN)
    monkeypatch.setenv(notify.DISCORD_OWNER_ENV, OWNER)
    write(data, "discord/channels.json", {"guild_id": GUILD, "channels": IDS, "dm": DM})
    fake = Bot()
    monkeypatch.setattr(notify, "bot_request", fake)
    return fake


def card(emoji="🟢", title="+5,0 % · X") -> notify.Card:
    return notify.Card(emoji, title, "pump.fun")


def test_the_routing_table():
    r = notify.DISCORD_ROUTES
    assert r["briefing"] == ("briefing", True) and r["trades"] == ("pumpfun-trades", True)
    assert r["fills"] == ("konten", True)
    assert {k: v[0] for k, v in r.items() if not v[1]} == {
        "status": "status", "forward": "paper-buecher", "studies": "studien", "models": "modelle",
        "pokemon": "pokemon", "cs2": "cs2-skins", "news": "news"}
    assert notify.DISCORD_CATEGORY_KINDS == {"studies": "studies", "models": "models", "pokemon": "pokemon",
                                             "cs2": "cs2"}
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "discord"))
    from pythia_discord import layout
    assert {v[0] for v in r.values()} == set(layout.CHANNELS), "every route has a channel in the bot's layout"


def test_a_trade_card_goes_to_its_channel_and_as_a_dm_with_its_chart(bot):
    res = notify.send_discord("trades", [card()], b"\x89PNG chart", "de", now=NOW)
    assert res["delivered"] and res["channel"] and res["dm"] and res["error"] is None
    (c1, p1, i1), (c2, p2, i2) = bot.posts()
    assert (c1, c2) == (IDS["pumpfun-trades"], DM) and i1 == i2 == b"\x89PNG chart"
    assert "username" not in p1 and p1["allowed_mentions"] == {"parse": []}
    assert p1["embeds"][0]["color"] == 0x2FB344 and p1["embeds"][0]["image"] == {"url": "attachment://chart.png"}


@pytest.mark.parametrize("kind,channel,dm", [("briefing", "briefing", True), ("fills", "konten", True),
                                             ("forward", "paper-buecher", False), ("studies", "studien", False),
                                             ("pokemon", "pokemon", False), ("cs2", "cs2-skins", False),
                                             ("news", "news", False), ("models", "modelle", False)])
def test_every_kind_reaches_its_channel(bot, kind, channel, dm):
    assert notify.send_discord(kind, [card()], lang="de", now=NOW)["delivered"]
    assert [c for c, _, _ in bot.posts()] == [IDS[channel]] + ([DM] if dm else [])


def test_send_routes_lab_categories_through_the_bot_only(bot):
    tg = lambda t: (True, None)   # noqa: E731
    res = notify.send("pokemon", [card("🃏", "Glurak")], poster=tg,
                      photos=[("https://images.example.org/card.png", "Glurak")])
    assert res["discord"]["delivered"]
    (cid, payload, img), = bot.posts()
    assert cid == IDS["pokemon"] and img is None
    assert payload["embeds"][0]["image"] == {"url": "https://images.example.org/card.png"}, "the card's picture"
    notify.send("trending", [card()], poster=tg)
    notify.send("studies", [card()], poster=tg, dry_run=True)
    assert len(bot.posts()) == 1, "trending has no channel; a dry run posts nothing"
    write(notify.data_root(), "reports/notify/settings.json", {"categories": [{"id": "cs2", "on": False}]})
    notify.send("cs2", [card()], poster=tg)
    assert len(bot.posts()) == 1, "the app's switch holds the bot too"
    notify.send("dailyPnl", [card("☀️", "Briefing")], poster=tg, discord="briefing")
    assert [c for c, _, _ in bot.posts()[1:]] == [IDS["briefing"], DM]


def test_without_the_token_categories_stay_off_discord(data, monkeypatch):
    monkeypatch.setenv(notify.DISCORD_ENV, WEBHOOK)
    got = []
    res = notify.send("pokemon", [card()], poster=lambda t: (True, None),
                      discord_poster=lambda u, p, i: got.append(u) or (True, None))
    assert "discord" not in res and got == [], "the webhook carries the briefing and trades only, as before"


def test_the_webhook_is_the_fallback_when_the_bot_fails(bot, monkeypatch):
    monkeypatch.setenv(notify.DISCORD_ENV, WEBHOOK)
    bot.fail = {IDS["pumpfun-trades"], DM}
    hooked = []
    res = notify.send_discord("trades", [card()], poster=lambda u, p, i: hooked.append((u, p)) or (True, None))
    assert res["delivered"] and hooked and hooked[0][0] == WEBHOOK and hooked[0][1]["username"] == "Pythia"
    assert TOKEN not in json.dumps(res)
    bot.fail.add(IDS["news"])
    res = notify.send_discord("news", [card()], poster=lambda u, p, i: hooked.append(u) or (True, None))
    assert not res["delivered"] and res["error"] and len(hooked) == 1, "news has no webhook"


def test_a_missing_channel_is_looked_up_by_name_once(data, monkeypatch):
    monkeypatch.setenv(notify.DISCORD_BOT_ENV, TOKEN)
    monkeypatch.setenv(notify.DISCORD_GUILD_ENV, GUILD)
    fake = Bot(guild_channels=[{"id": "940000000000000001", "type": 4, "name": "📰 Markt"},
                               {"id": "940000000000000002", "type": 0, "name": "news"}])
    monkeypatch.setattr(notify, "bot_request", fake)
    res = notify.send_discord("news", [card()], now=NOW)
    assert res["delivered"] and fake.posts()[0][0] == "940000000000000002", "no file: the guild's channels by name"
    res = notify.send_discord("briefing", [card()], now=NOW)
    assert not res["delivered"] and res["error"] == "#briefing: no channel; DM: no channel", "no #briefing, no owner"
    gets = [c for c in fake.calls if c[0] == "GET"]
    assert len(gets) == 2, "asked once for the map, once more for the missing channel"


def test_no_owner_no_dm_and_no_token_no_call(data, monkeypatch):
    assert notify.bot_request("GET", "/users/@me") == (0, None), "without a token nothing is sent"
    monkeypatch.setenv(notify.DISCORD_BOT_ENV, TOKEN)
    write(data, "discord/channels.json", {"channels": {"briefing": IDS["briefing"], "news": "../../evil"}})
    fake = Bot()
    monkeypatch.setattr(notify, "bot_request", fake)
    assert notify.discord_channels() == {"briefing": IDS["briefing"]}, "only snowflakes from the file"
    res = notify.send_discord("briefing", [card()])
    assert res["delivered"] and res["channel"] and not res["dm"] and "DM" in res["error"]


def test_the_bot_request_never_shows_the_token(data, monkeypatch):
    monkeypatch.setenv(notify.DISCORD_BOT_ENV, TOKEN)
    seen = {}

    class Resp:
        status = 200

        def read(self):
            return b'{"id": "5"}'

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def urlopen(req, timeout=None):
        seen["url"], seen["auth"] = req.full_url, req.get_header("Authorization")
        seen["ua"], seen["type"] = req.get_header("User-agent"), req.get_header("Content-type")
        return Resp()

    monkeypatch.setattr(notify.urllib.request, "urlopen", urlopen)
    assert notify.bot_request("POST", "/channels/1/messages", {"embeds": []}, b"img") == (200, {"id": "5"})
    assert seen["url"] == "https://discord.com/api/v10/channels/1/messages" and seen["auth"] == f"Bot {TOKEN}"
    assert seen["ua"].startswith("DiscordBot (") and seen["type"].startswith("multipart/form-data")
    assert TOKEN not in seen["url"]


def test_real_money_fills_go_to_konten_through_the_bot(bot):
    ap = {"config": {"name": "Kraken live", "mode": "live", "venue": "kraken",
                     "sleeves": [{"strategyId": "lab:b"}]}, "state": "running", "startCapital": 42.0}
    buy = {"id": "o1", "ts": NOW - 60_000, "strategyId": "lab:b", "marketId": "crypto:SOL/USD", "side": "buy",
           "status": "filled", "filledQty": 0.1, "avgFillPrice": 180.0, "mode": "live"}
    rows = [{"account": "main", "state": {"autopilots": [ap], "orders": []}}]
    notify.live_fills(NOW, rows=rows)
    rows[0]["state"]["orders"].append(buy)
    notify.live_fills(NOW, rows=rows)
    assert [c for c, _, _ in bot.posts()] == [IDS["konten"], DM]


# ---------------------------------------------------------------- the feed

def test_the_feed_remembers_first_then_posts_what_is_new(bot):
    root = notify.data_root()
    write(root, "reports/forward/latest.json", {"generated_ms": NOW - 9_000, "generated": "2026-10-23 06:15 UTC",
                                                "headline": "20 paper books: 7 too early", "status": "watch",
                                                "books": [{"name": "tsmom", "label": "Momentum", "days": 18,
                                                           "return_pct": -6.2, "status": "watch"}]})
    write(root, "reports/tsmom/latest.json", {"verdict": "Picked 28d"})
    write(root, "reports/learn/latest.json", {"verdict": "not a study"})
    write(root, "reports/models/latest.json", {"models": [{"code": "M2", "decisions": [
        {"date": "2026-10-01", "decision": "kept"}]}]})
    day = time.strftime("%Y-%m-%d", time.gmtime(NOW / 1000))
    write(root, f"ai/news/{day}.jsonl", json.dumps({"title": "Old news", "link": "https://news.example.org/1",
                                                    "published_us": (NOW - 7_200_000) * 1000}) + "\n")
    got = []
    poster = lambda kind, c: got.append((kind, c)) or True   # noqa: E731
    assert discord_feed.run(now=NOW, poster=poster) == 0 and got == [], "the first run only remembers"

    write(root, "reports/forward/latest.json", {"generated_ms": NOW, "generated": "2026-10-24 06:15 UTC",
                                                "headline": "21 paper books", "status": "watch", "books": []})
    p = root / "reports" / "tsmom" / "latest.json"
    p.write_text(json.dumps({"verdict": "Picked **28d**, passes", "passes": True}))
    os.utime(p, (time.time() + 60, time.time() + 60))
    write(root, "reports/carry/latest.json", {"rows": []})          # no verdict: nothing to say
    os.utime(root / "reports" / "carry" / "latest.json", (time.time() + 60, time.time() + 60))
    write(root, "reports/models/latest.json", {"models": [{"code": "M2", "decisions": [
        {"date": "2026-10-01", "decision": "kept"}, {"date": "2026-10-24", "decision": "promoted"}]}]})
    lines = [{"title": f"Headline {i}", "link": f"https://news.example.org/n{i}", "coins": ["BTC"] if i == 6 else [],
              "published_us": (NOW - i * 1000) * 1000} for i in range(2, 9)]
    with (root / "ai" / "news" / f"{day}.jsonl").open("a") as fh:
        fh.write("\n".join(json.dumps(x) for x in lines) + "\n")
    discord_feed.run(now=NOW + 60_000, poster=poster)
    kinds = [k for k, _ in got]
    assert kinds == ["forward", "studies", "models", "news"]
    cards = dict(got)
    assert cards["forward"].summary == "21 paper books" and cards["studies"].emoji == "🟢"
    assert "**" not in cards["studies"].summary and "M2" in cards["models"].parts[0].text
    news = cards["news"].render("discord", "en")
    assert news.count("news.example.org") == 5 and "Headline 6" in news.splitlines()[2], "a coin's headline first"
    assert "Old news" not in news
    got.clear()
    discord_feed.run(now=NOW + 120_000, poster=poster)
    assert got == [], "nothing twice; the two headlines beyond five were remembered, not held back"


def test_the_feed_through_the_bot_and_its_switches(bot):
    root = notify.data_root()
    write(root, "notify/discord_feed.json", {"studies": {}, "forward_ms": 0, "models": [], "news": []})
    write(root, "reports/tsmom/latest.json", {"verdict": "Picked 28d"})
    write(root, "reports/forward/latest.json", {"generated_ms": NOW, "headline": "x", "books": []})
    write(root, "reports/notify/settings.json", {"categories": [{"id": "studies", "on": False}]})
    discord_feed.run(["studies", "forward"], now=NOW)
    assert [c for c, _, _ in bot.posts()] == [IDS["paper-buecher"]], "studies switched off in the app"
    st = json.loads((root / "notify" / "discord_feed.json").read_text())
    assert "tsmom" in st["studies"] and st["forward_ms"] == NOW


def test_the_feed_needs_the_token(data):
    assert discord_feed.run(now=NOW) == 0
    assert not (notify.data_root() / "notify" / "discord_feed.json").exists()
