"""The Discord bot of research/discord, against a fake Discord (mocked HTTP): the server layout in
German and English is idempotent and additive and keeps the ids of the channels there were, every
channel is private to the owner and the bot, a welcome post in each #status is pinned once, the
slash commands answer only the owner, only read, and in the language of their channel.

Run from research/lab:  python -m pytest tests/test_discord_bot.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "discord"))

from pythia_discord import commands, layout  # noqa: E402
from pythia_discord.rest import DiscordError, Rest  # noqa: E402

GUILD, OWNER, BOT, STRANGER = "900000000000000001", "900000000000000002", "900000000000000003", "900000000000000004"
TOKEN = "fake-bot-token-never-shown"
NOW = 1_792_747_281_647
ADDRESS = "Wa11et1111111111111111111111111111111111111"


class FakeDiscord:
    """Just enough of Discord's REST API for the layout: roles, members, channels, overwrites,
    messages, pins, DMs. Every call is recorded as (method, path, body)."""

    def __init__(self, pins: str = "new", pin_status: int = 204):
        self.calls: list[tuple[str, str, object]] = []
        self.next_id = 910000000000000000
        self.roles = [{"id": GUILD, "name": "@everyone", "managed": False},
                      {"id": self.nid(), "name": "Pythia App", "managed": True}]
        self.members = {BOT: {"roles": [self.roles[1]["id"]]}}
        self.channels: list[dict] = []
        self.messages: dict[str, dict] = {}
        self.pinned: dict[str, list[str]] = {}
        self.pins, self.pin_status = pins, pin_status
        self.headers: list[dict] = []

    def nid(self) -> str:
        self.next_id += 1
        return str(self.next_id)

    def writes(self) -> list[tuple[str, str, object]]:
        return [c for c in self.calls if c[0] != "GET"]

    def __call__(self, method, url, headers, data):
        assert url.startswith("https://discord.com/api/v10/")
        self.headers.append(headers)
        path = url[len("https://discord.com/api/v10"):]
        body = json.loads(data) if data else None
        self.calls.append((method, path, body))
        out = self.route(method, path, body)
        if isinstance(out, int):
            return out, b'{"message": "no"}'
        return (200, json.dumps(out).encode()) if out is not None else (204, b"")

    def chan(self, cid) -> dict | None:
        return next((c for c in self.channels if c["id"] == cid), None)

    def route(self, m, path, body):
        g = f"/guilds/{GUILD}"
        if (m, path) == ("GET", "/users/@me"):
            return {"id": BOT, "username": "Pythia", "bot": True}
        if (m, path) == ("GET", f"{g}/roles"):
            return self.roles
        if (m, path) == ("POST", f"{g}/roles"):
            r = {"id": self.nid(), "managed": False, **body}
            self.roles.append(r)
            return r
        if mm := re.fullmatch(rf"{g}/members/(\d+)", path):
            return self.members.get(mm[1], 404)
        if mm := re.fullmatch(rf"{g}/members/(\d+)/roles/(\d+)", path):
            self.members[mm[1]]["roles"].append(mm[2])
            return None
        if (m, path) == ("GET", f"{g}/channels"):
            return self.channels
        if (m, path) == ("POST", f"{g}/channels"):
            c = {"id": self.nid(), "parent_id": None, "topic": None, "position": len(self.channels), **body}
            self.channels.append(c)
            return c
        if (m, path) == ("PATCH", f"{g}/channels"):
            for o in body:
                self.chan(o["id"])["position"] = o["position"]
            return None
        if mm := re.fullmatch(r"/channels/(\d+)/permissions/(\d+)", path):
            c = self.chan(mm[1])
            c["permission_overwrites"] = [o for o in c.get("permission_overwrites") or [] if o["id"] != mm[2]]
            c["permission_overwrites"].append({"id": mm[2], **body})
            return None
        if m == "PATCH" and (mm := re.fullmatch(r"/channels/(\d+)", path)):
            self.chan(mm[1]).update(body)
            return self.chan(mm[1])
        if (m, path) == ("POST", "/users/@me/channels"):
            return {"id": "920000000000000009", "type": 1}
        if mm := re.fullmatch(r"/channels/(\d+)/messages", path):
            msg = {"id": self.nid(), "channel_id": mm[1], "author": {"id": BOT}, **body}
            self.messages[msg["id"]] = msg
            return msg
        if mm := re.fullmatch(r"/channels/(\d+)/messages/(\d+)", path):
            if mm[2] not in self.messages:
                return 404
            if m == "PATCH":
                self.messages[mm[2]].update(body)
            return self.messages[mm[2]]
        if mm := re.fullmatch(r"/channels/(\d+)/(messages/pins|pins)(?:/(\d+))?", path):
            if (mm[2] == "pins") != (self.pins == "old"):
                return 404
            if m == "PUT":
                if self.pin_status != 204:
                    return self.pin_status
                self.pinned.setdefault(mm[1], []).append(mm[3])
                return None
            msgs = [self.messages[i] for i in self.pinned.get(mm[1], [])]
            return {"items": [{"message": x} for x in msgs], "has_more": False} if mm[2] != "pins" else msgs
        raise AssertionError(f"unexpected call {m} {path}")


def rest(fake) -> Rest:
    return Rest(TOKEN, transport=fake, sleep=lambda s: None)


def private(c: dict, role_id: str) -> None:
    ow = {o["id"]: o for o in c.get("permission_overwrites") or []}
    assert int(ow[GUILD]["deny"]) & layout.VIEW_CHANNEL, f"{c['name']}: @everyone may not view"
    assert not int(ow[GUILD]["allow"]) & layout.VIEW_CHANNEL
    for who in (OWNER, BOT, role_id):
        assert int(ow[who]["allow"]) & layout.VIEW_CHANNEL, f"{c['name']}: {who} may view"
    assert int(ow[OWNER]["allow"]) & layout.USE_APPLICATION_COMMANDS
    assert int(ow[BOT]["allow"]) & layout.SEND_MESSAGES and int(ow[BOT]["allow"]) & layout.ATTACH_FILES


# ---------------------------------------------------------------- the layout

def ordered(fake) -> list[str]:
    """The categories as Discord shows them, each followed by its channels."""
    key = lambda c: (int(c.get("position") or 0), int(c["id"]))   # noqa: E731
    out = []
    for cat in sorted((c for c in fake.channels if c["type"] == 4), key=key):
        out.append(cat["name"])
        out += ["#" + c["name"] for c in sorted((c for c in fake.channels if c.get("parent_id") == cat["id"]),
                                                key=key)]
    return out


def wanted_order() -> list[str]:
    return [x for lang in layout.LANGS for cat, chans in layout.LAYOUTS[lang]
            for x in [cat] + ["#" + n for n, _ in chans]]


def test_the_layout_creates_both_languages_once_and_then_nothing(tmp_path):
    fake = FakeDiscord()
    path = tmp_path / "channels.json"
    st = layout.apply(rest(fake), GUILD, OWNER, path, log=lambda s: None, now_ms=NOW)
    cats = [c for c in fake.channels if c["type"] == 4]
    texts = [c for c in fake.channels if c["type"] == 0]
    assert [c["name"] for c in cats] == ["🇩🇪 Übersicht", "🇩🇪 Echtgeld", "🇩🇪 Lab", "🇩🇪 Sammeln", "🇩🇪 Markt",
                                         "🇬🇧 Overview", "🇬🇧 Real money", "🇬🇧 Lab", "🇬🇧 Collecting", "🇬🇧 Markets"]
    assert len(texts) == 20 and layout.CHANNELS_BY_LANG["en"] == [
        "briefing", "status", "pumpfun-trades", "accounts", "studies", "paper-books", "models", "pokemon", "cs2-skins",
        "news"]
    assert ordered(fake) == wanted_order(), "German block first, then English, each in the layout's order"
    role = next(r for r in fake.roles if r["name"] == "Pythia")
    assert role["id"] in fake.members[BOT]["roles"] and role["permissions"] == "0", "a role without rights of its own"
    for c in fake.channels:
        private(c, role["id"])
    by_id = {c["id"]: c for c in fake.channels}
    for lang in layout.LANGS:
        for cat_name, chans in layout.LAYOUTS[lang]:
            for name, topic in chans:
                c = by_id[st[lang][name]]
                assert c["topic"] == topic and by_id[c["parent_id"]]["name"] == cat_name
    assert "Direktnachricht" in by_id[st["de"]["briefing"]]["topic"]
    assert "direct message" in by_id[st["en"]["briefing"]]["topic"], "topics in their language"
    assert st["de"]["briefing"] != st["en"]["briefing"] and st["channels"] == st["de"], "the old key, German"
    assert json.loads(path.read_text()) == st and st["dm"] == "920000000000000009" and st["guild_id"] == GUILD
    for lang, title in (("de", "Willkommen bei Pythia"), ("en", "Welcome to Pythia")):
        status = st[lang]["status"]
        assert fake.pinned[status] == [st["welcome"][lang]]
        emb = fake.messages[st["welcome"][lang]]["embeds"][0]
        assert emb["title"] == title == layout.WELCOME_TITLES[lang]
    assert st["welcome_id"] == st["welcome"]["de"]
    de_w, en_w = (fake.messages[st["welcome"][k]]["embeds"][0] for k in ("de", "en"))
    assert "Befehle" in de_w["description"] and "#konten" in de_w["description"]
    assert "Commands" in en_w["description"] and "#accounts" in en_w["description"]
    assert de_w["footer"]["text"] == "Pythia · Alpha" and en_w["footer"]["text"] == "Pythia · Alpha phase"
    assert all(h["Authorization"] == f"Bot {TOKEN}" and h["User-Agent"].startswith("DiscordBot (")
               for h in fake.headers)

    n = len(fake.calls)
    again = layout.apply(rest(fake), GUILD, OWNER, path, log=lambda s: None, now_ms=NOW)
    writes = [c for c in fake.calls[n:] if c[0] != "GET"]
    assert writes == [("POST", "/users/@me/channels", {"recipient_id": OWNER})], "the second run changes nothing"
    assert again == st and len(fake.channels) == 30 and len(fake.messages) == 2


def test_the_plan_is_idempotent_and_never_deletes():
    fake = FakeDiscord()
    steps = layout.plan([], GUILD, OWNER, BOT, "777")
    assert [s["op"] for s in steps].count("create_category") == 10
    assert [s["op"] for s in steps].count("create_channel") == 20
    layout.run_steps(rest(fake), GUILD, steps, [], log=lambda s: None)
    assert layout.plan(fake.channels, GUILD, OWNER, BOT, "777") == []
    assert not any(c[0] == "DELETE" for c in fake.calls)
    ops = {s["op"] for s in layout.plan(fake.channels + [{"id": "1", "type": 0, "name": "mine"}], GUILD, OWNER, BOT,
                                        "777")}
    assert ops == set(), "the owner's own channel is left alone"


def old_server(fake) -> dict:
    """The server as the German-only layout left it, and its channels.json."""
    want = layout.overwrites(GUILD, OWNER, BOT, fake.roles[1]["id"])
    old = [("📊 Übersicht", ["briefing", "status"]), ("💰 Echtgeld", ["pumpfun-trades", "konten"]),
           ("🧪 Lab", ["studien", "paper-buecher", "modelle"]), ("🃏 Sammeln", ["pokemon", "cs2-skins"]),
           ("📰 Markt", ["news"])]
    ids = {}
    for cat, names in old:
        c = {"id": fake.nid(), "type": 4, "name": cat, "parent_id": None, "position": len(fake.channels),
             "permission_overwrites": want}
        fake.channels.append(c)
        for n in names:
            ch = {"id": fake.nid(), "type": 0, "name": n, "parent_id": c["id"], "topic": "alt: " + n,
                  "position": len(fake.channels), "permission_overwrites": want}
            fake.channels.append(ch)
            ids[n] = ch["id"]
    return {"guild_id": GUILD, "role_id": fake.roles[1]["id"], "channels": ids, "categories": {}, "dm": None,
            "welcome_id": None, "updated_ms": NOW - 1}


def test_the_german_layout_becomes_the_german_block_and_keeps_its_ids(tmp_path):
    fake = FakeDiscord()
    before = old_server(fake)
    cat_ids = [c["id"] for c in fake.channels if c["type"] == 4]
    path = tmp_path / "channels.json"
    path.write_text(json.dumps(before))
    st = layout.apply(rest(fake), GUILD, OWNER, path, log=lambda s: None, now_ms=NOW)
    assert st["de"] == before["channels"] and st["channels"] == before["channels"], "every German id stays"
    assert [fake.chan(i)["name"] for i in cat_ids] == [n for n, _ in layout.LAYOUTS["de"]], "renamed in place"
    assert all(fake.chan(i)["topic"] == "alt: " + n for n, i in before["channels"].items()), "the owner's topics stay"
    assert set(st["en"]) == set(layout.CHANNELS_BY_LANG["en"]) and not set(st["en"].values()) & set(st["de"].values())
    assert ordered(fake) == wanted_order()
    assert not any(c[0] == "DELETE" for c in fake.calls) and len(fake.channels) == 30
    n = len(fake.calls)
    assert layout.apply(rest(fake), GUILD, OWNER, path, log=lambda s: None, now_ms=NOW) == st
    assert [c for c in fake.calls[n:] if c[0] != "GET"] == [("POST", "/users/@me/channels", {"recipient_id": OWNER})]


def test_the_order_is_put_right_in_one_patch():
    fake = FakeDiscord()
    layout.run_steps(rest(fake), GUILD, layout.plan([], GUILD, OWNER, BOT, "777"), [], log=lambda s: None)
    by = {c["name"]: c for c in fake.channels if c["type"] == 4}
    by["🇬🇧 Overview"]["position"], by["🇩🇪 Übersicht"]["position"] = by["🇩🇪 Übersicht"]["position"], 99
    steps = layout.plan(fake.channels, GUILD, OWNER, BOT, "777")
    assert [s["op"] for s in steps] == ["order"]
    layout.run_steps(rest(fake), GUILD, steps, fake.channels, log=lambda s: None)
    assert ordered(fake) == wanted_order() and layout.plan(fake.channels, GUILD, OWNER, BOT, "777") == []


def test_an_owners_channel_is_kept_moved_in_and_its_topic_kept(tmp_path):
    fake = FakeDiscord()
    own = {"id": "930000000000000001", "type": 0, "name": "news", "parent_id": None, "topic": "meine Nachrichten",
           "permission_overwrites": [{"id": "930000000000000077", "type": 0, "allow": "2048", "deny": "0"},
                                     {"id": GUILD, "type": 0, "allow": str(layout.VIEW_CHANNEL), "deny": "0"}]}
    mine = {"id": "930000000000000002", "type": 0, "name": "allgemein", "parent_id": None, "topic": None,
            "permission_overwrites": []}
    fake.channels += [own, mine]
    st = layout.apply(rest(fake), GUILD, OWNER, tmp_path / "c.json", log=lambda s: None)
    markt = next(c for c in fake.channels if c["name"] == "🇩🇪 Markt")
    assert st["de"]["news"] == own["id"] and own["parent_id"] == markt["id"] and own["topic"] == "meine Nachrichten"
    assert sum(c["name"] == "news" for c in fake.channels) == 2 and st["en"]["news"] != own["id"], \
        "one German #news (the owner's), one English"
    ow = {o["id"]: o for o in own["permission_overwrites"]}
    assert ow["930000000000000077"]["allow"] == "2048", "another role's overwrite stays"
    private(own, st["role_id"])
    assert mine["permission_overwrites"] == [] and mine["parent_id"] is None, "a channel not in the layout is untouched"


def test_the_overwrites_add_bits_and_keep_the_rest():
    want = layout.overwrites(GUILD, OWNER, BOT, None)
    have = [{"id": OWNER, "type": 1, "allow": str(layout.VIEW_CHANNEL | (1 << 4)), "deny": str(layout.SEND_MESSAGES)},
            {"id": GUILD, "type": 0, "allow": "0", "deny": str(layout.VIEW_CHANNEL | layout.SEND_MESSAGES)},
            {"id": BOT, "type": 1, "allow": str(layout.BOT_ALLOW), "deny": "0"}]
    fix = layout.fix_overwrites(have, want)
    assert [f["id"] for f in fix] == [OWNER], "only the owner's overwrite lacks bits"
    a = int(fix[0]["allow"])
    assert a & (1 << 4) and a & layout.OWNER_ALLOW == layout.OWNER_ALLOW and fix[0]["deny"] == "0"


def test_the_welcome_posts_are_written_once_even_when_they_cannot_be_pinned(tmp_path):
    fake = FakeDiscord(pins="old", pin_status=403)
    logs: list[str] = []
    st = layout.apply(rest(fake), GUILD, OWNER, tmp_path / "c.json", log=logs.append)
    assert st["welcome"]["de"] and st["welcome"]["en"] and fake.pinned == {} and any("Pin Messages" in s for s in logs)
    layout.apply(rest(fake), GUILD, OWNER, tmp_path / "c.json", log=logs.append)
    assert len(fake.messages) == 2, "the known posts are reused, not posted again"
    fake.pin_status = 204
    fake.messages[st["welcome_id"]]["embeds"][0]["description"] = "old text"
    layout.apply(rest(fake), GUILD, OWNER, tmp_path / "c.json", log=logs.append)
    assert fake.messages[st["welcome_id"]]["embeds"][0]["description"] == layout.welcome_embed("de")["description"]
    for lang in layout.LANGS:
        assert fake.pinned[st[lang]["status"]] == [st["welcome"][lang]], "pinned through the older endpoint"


def test_rest_waits_out_a_rate_limit_and_never_shows_the_token():
    calls, slept = [], []

    def transport(method, url, headers, data):
        calls.append(url)
        return (429, b'{"retry_after": 1.5}') if len(calls) == 1 else (403, b"{}")

    r = Rest(TOKEN, transport=transport, sleep=slept.append)
    with pytest.raises(DiscordError) as e:
        r.get("/users/@me")
    assert slept == [1.5] and len(calls) == 2 and e.value.status == 403
    assert TOKEN not in str(e.value) and TOKEN not in repr(r)


# ---------------------------------------------------------------- the slash commands

def status_sample() -> dict:
    return {"t": NOW - 20_000, "running": True, "on": True, "mode": "test", "rule": "P_pool0", "address": ADDRESS,
            "balance_sol": 0.724695411, "pnl_today_sol": -0.1275711, "trades_today": 22, "wins_today": 8,
            "pnl_total_sol": -0.032850396, "trades_total": 35, "gate": [], "refusing": None, "kill": False,
            "stops": {"daily": False, "total": False},
            "limits": {"max_trade_sol": 0.05, "max_open": 5, "max_daily_loss_sol": 0.18, "max_total_sol": 0.4},
            "stake": {"sol": 0.05, "why": "10 % of 0.72 SOL"},
            "positions": [{"pid": 3, "symbol": "KIMCHI", "cost_sol": 0.05, "mark_sol": 0.06, "state": "open"}]}


@pytest.fixture()
def reports(tmp_path):
    root = tmp_path / "reports"
    (root / "pumpfun_rt").mkdir(parents=True)
    (root / "pumpfun_rt" / "live_status.json").write_text(json.dumps(status_sample()))
    trades = [{"symbol": f"C{i}", "exit_ms": NOW - i * 60_000, "ret": 0.2 if i % 2 else -0.3,
               "pnl_sol": 0.01 if i % 2 else -0.015, "exit_why": "take" if i % 2 else "stop"} for i in range(14)]
    (root / "pumpfun_rt" / "live_trades.json").write_text(json.dumps({"t": NOW, "trades": trades[::-1]}))
    (root / "forward").mkdir()
    (root / "forward" / "latest.json").write_text(json.dumps({
        "generated": "2026-10-23 06:15 UTC",
        "books": [{"name": "tsmom", "status": "watch"}, {"name": "b2", "status": "on_track"}],
        "autopilots": [{"name": "ap1", "label": "Kraken live", "mode": "live", "venue": "kraken", "equity": 42.0,
                        "return_pct": 1.5},
                       {"name": "ap2", "label": "Crypto + SPY", "mode": "demo", "venue": "alpaca", "equity": 9977.41,
                        "return_pct": -0.2}]}))
    (root / "models").mkdir()
    (root / "models" / "latest.json").write_text(json.dumps({"models": [{"code": "M2", "status": "in use"},
                                                                        {"code": "M1", "status": "shadow"}]}))
    (root / "tsmom").mkdir()
    (root / "tsmom" / "latest.json").write_text(json.dumps({"verdict": "Picked **28d**: Sharpe 0.72 out of sample"}))
    (root / "learn").mkdir()
    (root / "learn" / "latest.json").write_text(json.dumps({"verdict": "not a study"}))
    return root


def test_only_the_owner_may_use_the_commands(reports):
    for name, _ in commands.COMMANDS:
        out = commands.respond(name, STRANGER, OWNER, NOW, reports)
        assert out == {"content": "nicht erlaubt", "embeds": [], "ephemeral": True}
        assert commands.respond(name, int(OWNER), OWNER, NOW, reports)["embeds"], "the id may come as a number"
    assert not commands.allowed(OWNER, "") and not commands.allowed("", "") and commands.allowed(OWNER, f" {OWNER} ")
    assert [n for n, _ in commands.COMMANDS] == ["status", "trades", "konten", "lab"]


def text_of(e: dict) -> str:
    return "\n".join([e["title"], e["description"]] + [f"{f['name']}: {f['value']}" for f in e.get("fields", [])]
                     + [(e.get("footer") or {}).get("text", "")])


def test_status_says_on_wallet_pnl_stake_and_positions(reports):
    e = commands.respond("status", OWNER, OWNER, NOW, reports)["embeds"][0]
    t = text_of(e)
    assert e["color"] == commands.GREEN and "🟢 an" in t and "Test (Alpha-Phase)" in t
    assert "Wa11…1111 · 0,7247 SOL" in t and ADDRESS not in t, "the wallet shortened"
    assert "P&L heute: -0,1276 SOL · 22 Trades, 8 gewonnen" in t and "P&L gesamt: -0,0329 SOL" in t
    assert "Einsatz: 0,0500 SOL" in t and "Offene Positionen (1): KIMCHI: 0,0500 SOL · +20,0 %" in t
    st = {**status_sample(), "on": False, "gate": ["the 24 h test gate is shut"], "t": NOW - 20_000}
    e = commands.status_embed(st, NOW)
    assert e["color"] == commands.ORANGE and "Warum: the 24 h test gate is shut" in e["description"]
    assert "läuft nicht" in commands.status_embed({**status_sample(), "t": NOW - 3_600_000}, NOW)["description"]
    assert "Notschalter" in commands.status_embed({**status_sample(), "kill": True}, NOW)["description"]
    assert "fehlt" in commands.status_embed(None, NOW)["description"]


def test_trades_lists_the_last_ten_newest_first(reports):
    e = commands.respond("trades", OWNER, OWNER, NOW, reports)["embeds"][0]
    lines = e["description"].splitlines()
    assert len(lines) == 10 and "**C0**" in lines[0] and "**C9**" in lines[9]
    assert lines[0].startswith("🔴") and "-30,0 % · -0,0150 SOL · stop" in lines[0]
    assert lines[1].startswith("🟢") and "+20,0 % · +0,0100 SOL · take" in lines[1]
    assert e["footer"]["text"].startswith("Summe -0,0250 SOL")
    assert commands.trades_embed([])["description"] == "Noch keine Trades."


def test_konten_and_lab_from_the_reports(reports):
    t = text_of(commands.respond("konten", OWNER, OWNER, NOW, reports)["embeds"][0])
    assert "pump.fun Wallet Wa11…1111: 0,7247 SOL" in t and "Kraken live (kraken): 42,00 $ · +1,5 %" in t
    assert "Paper und Demo (1): Crypto + SPY (alpaca): 9.977,41 $ · -0,2 %" in t
    assert "Paper-Bücher (2): 1 beobachten, 1 im Plan" in t or "Paper-Bücher (2): 1 im Plan, 1 beobachten" in t
    t = text_of(commands.respond("lab", OWNER, OWNER, NOW, reports)["embeds"][0])
    assert "**tsmom**" in t and "Picked 28d: Sharpe 0.72" in t and "learn" not in t
    assert "im Einsatz: M2" in t and "Schattenlauf: M1" in t


def test_the_commands_only_read(reports, monkeypatch):
    before = {p: p.read_bytes() for p in reports.rglob("*") if p.is_file()}
    for name, _ in commands.COMMANDS:
        commands.respond(name, OWNER, OWNER, NOW, reports)
    assert {p: p.read_bytes() for p in reports.rglob("*") if p.is_file()} == before
    src = (Path(commands.__file__)).read_text(encoding="utf-8")
    for word in ("write_text", "open(", "unlink", "KILL", "live_settings", "urllib", "requests"):
        assert word not in src, f"commands.py must not {word}"


def test_the_commands_answer_in_the_language_of_their_channel(reports, tmp_path):
    fake = FakeDiscord()
    st = layout.apply(rest(fake), GUILD, OWNER, tmp_path / "c.json", log=lambda s: None)
    assert commands.channel_lang(st["en"]["status"], st) == "en"
    assert commands.channel_lang(st["de"]["status"], st) == "de"
    assert commands.channel_lang(st["dm"], st) == "de", "the DM is German"
    assert commands.channel_lang("930000000000000005", st, st["categories"]["🇬🇧 Lab"]) == "en", "under a 🇬🇧 category"
    assert commands.channel_lang("930000000000000005", None) == "de" and commands.channel_lang(None, {}) == "de"
    out = commands.respond("status", OWNER, OWNER, NOW, reports, lang="en")
    t = text_of(out["embeds"][0])
    assert out["ephemeral"] and "🟢 on" in t and "test (Alpha phase)" in t and "Wa11…1111 · 0.7247 SOL" in t
    assert "P&L today: -0.1276 SOL · 22 trades, 8 won" in t and "Open positions (1): KIMCHI: 0.0500 SOL · +20.0 %" in t
    assert out["embeds"][0]["footer"]["text"].endswith("read only · Pythia · Alpha phase")
    assert out["embeds"][0]["timestamp"].startswith("2026-")
    de = commands.respond("status", OWNER, OWNER, NOW, reports)["embeds"][0]
    assert de["footer"]["text"].endswith("nur lesen · Pythia · Alpha") and [f["name"] for f in de["fields"]] == [
        "Modus", "Wallet", "P&L heute", "P&L gesamt", "Einsatz", "Offene Positionen (1)", "Grenzen"]
    assert [f["name"] for f in out["embeds"][0]["fields"]] == [
        "Mode", "Wallet", "P&L today", "P&L total", "Stake", "Open positions (1)", "Limits"], "the same order"
    t = text_of(commands.respond("konten", OWNER, OWNER, NOW, reports, lang="en")["embeds"][0])
    assert "pump.fun wallet Wa11…1111: 0.7247 SOL" in t and "Kraken live (kraken): $42.00 · +1.5 %" in t
    assert "Paper and demo (1): Crypto + SPY (alpaca): $9,977.41 · -0.2 %" in t and "watch" in t
    t = text_of(commands.respond("trades", OWNER, OWNER, NOW, reports, lang="en")["embeds"][0])
    assert "-30.0 % · -0.0150 SOL · stop" in t and t.splitlines()[-1].startswith("Total -0.0250 SOL")
    t = text_of(commands.respond("lab", OWNER, OWNER, NOW, reports, lang="en")["embeds"][0])
    assert "in use: M2" in t and "shadow: M1" in t
    assert commands.respond("lab", STRANGER, OWNER, NOW, reports, lang="en")["content"] == "not allowed"
    for name in ("status", "trades", "konten", "lab"):
        en = text_of(commands.respond(name, OWNER, OWNER, NOW, reports, lang="en")["embeds"][0])
        assert not re.search(r"\b(Stand|Einsatz|gesamt|keine|Konten|nur lesen|Summe|weitere)\b", en), (name, en)


def test_every_command_text_is_there_in_both_languages():
    de, en = commands.TEXT["de"], commands.TEXT["en"]
    assert set(de) == set(en)
    for k in de:
        assert set(re.findall(r"{(\w+)}", de[k])) == set(re.findall(r"{(\w+)}", en[k])), k
    assert set(commands.COMMANDS_EN) == {n for n, _ in commands.COMMANDS}
    assert set(commands.STATUS_DE) == set(commands.STATUS_EN)
    assert set(layout.WELCOME_TEXT["de"]) == set(layout.WELCOME_TEXT["en"])
    assert [len(c) for _, c in layout.LAYOUTS["de"]] == [len(c) for _, c in layout.LAYOUTS["en"]]
    for name, desc in commands.COMMANDS:
        assert len(desc) <= 100 and len(commands.COMMANDS_EN[name]) <= 100, "Discord's limit"
    assert "\u2014" not in (Path(commands.__file__).read_text() + Path(layout.__file__).read_text())
