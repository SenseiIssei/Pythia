"""The owner's server, laid out by the bot: categories, channels, topics, the role, the welcome post.

Idempotent and additive: what is missing is created, what is there is kept. A channel or
category is found by name; an owner's channel of the same name is used as it is (never
moved, renamed or deleted), only made private and given a topic when it has none. Private
means: @everyone may not view it, the owner and the bot (its member and the role "Pythia")
may. Overwrites of other roles or members stay as they are.

plan() is pure (the steps for a snapshot of the channels, for the tests); apply() reads the
guild, runs the steps, pins the welcome post in #status, opens the DM channel to the owner
and writes the map of channel ids to the state file, which the lab reads (shared read only
as <data>/discord/channels.json):

  {"guild_id", "role_id", "channels": {"briefing": id, ...}, "categories": {...},
   "dm": the owner's DM channel, "welcome_id", "updated_ms"}
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from .rest import DiscordError, Rest

# Permission bits (Discord's numbers).
ADD_REACTIONS = 1 << 6
VIEW_CHANNEL = 1 << 10
SEND_MESSAGES = 1 << 11
MANAGE_MESSAGES = 1 << 13
EMBED_LINKS = 1 << 14
ATTACH_FILES = 1 << 15
READ_MESSAGE_HISTORY = 1 << 16
USE_APPLICATION_COMMANDS = 1 << 31
# Only bits the bot has itself (it cannot grant more), the read side for the owner plus writing.
OWNER_ALLOW = (VIEW_CHANNEL | SEND_MESSAGES | READ_MESSAGE_HISTORY | EMBED_LINKS | ATTACH_FILES | ADD_REACTIONS
               | USE_APPLICATION_COMMANDS)
BOT_ALLOW = (VIEW_CHANNEL | SEND_MESSAGES | READ_MESSAGE_HISTORY | EMBED_LINKS | ATTACH_FILES | ADD_REACTIONS
             | MANAGE_MESSAGES)

ROLE_NAME = "Pythia"
ROLE_COLOR = 0x3987E5
CATEGORY, TEXT = 4, 0
REASON = "Pythia: Server-Layout"

LAYOUT: list[tuple[str, list[tuple[str, str]]]] = [
    ("📊 Übersicht", [
        ("briefing", "Das Morgen-Briefing um 9:00 Berlin: pump.fun, Echtgeld, Paper, Lab, Sammeln, Markt. "
                     "Kommt auch als Direktnachricht."),
        ("status", "Was wohin kommt (angepinnt) und die Befehle /status, /trades, /konten, /lab. Nur lesen."),
    ]),
    ("💰 Echtgeld", [
        ("pumpfun-trades", "Jede Echtgeld-Order des pump.fun-Bots mit Chart, die Farbe nach Ergebnis. "
                           "Kommt auch als Direktnachricht."),
        ("konten", "Echtgeld-Fills der Kraken- und Alpaca-Autopiloten. Kommt auch als Direktnachricht. "
                   "Kontostände: /konten."),
    ]),
    ("🧪 Lab", [
        ("studien", "Neue Studien-Ergebnisse, die Strategiefabrik und der Forschungsdirektor."),
        ("paper-buecher", "Der Forward-Bericht: jedes Paper-Buch und jeder Autopilot gegen seinen Backtest."),
        ("modelle", "Entscheidungen des Modell-Zoos: befördert, verworfen, behalten."),
    ]),
    ("🃏 Sammeln", [
        ("pokemon", "Pokemon-Karten: günstige Karten gegen ihren fairen Wert, die Spielgeld-Sammlung."),
        ("cs2-skins", "CS2-Skins: Hinweise, Trends am Steam-Markt, das Spielgeld-Portfolio."),
    ]),
    ("📰 Markt", [
        ("news", "Neue Krypto-Schlagzeilen, die mit einer Münze zuerst."),
    ]),
]
CHANNELS = [name for _, chans in LAYOUT for name, _ in chans]

WELCOME_TITLE = "Willkommen bei Pythia"


def welcome_embed() -> dict:
    """The pinned post in #status: what goes where, and the commands."""
    lines = []
    for cat, chans in LAYOUT:
        lines.append(f"**{cat}**")
        lines += [f"#{name}: {topic}" for name, topic in chans]
        lines.append("")
    lines += ["**Befehle** (nur für dich, nur lesen; keiner handelt, schaltet scharf, ändert Limits "
              "oder berührt den Notschalter):",
              "/status  pump.fun live: an oder aus, Wallet, P&L heute, Einsatz, offene Positionen",
              "/trades  die letzten 10 Echtgeld-Trades",
              "/konten  Echtgeld- und Paper-Konten",
              "/lab  die neuesten Studien und der Modell-Zoo",
              "",
              "Alle Kanäle sind privat: nur du und Pythia sehen sie."]
    return {"title": WELCOME_TITLE, "description": "\n".join(lines), "color": ROLE_COLOR,
            "footer": {"text": "Pythia"}}


# ---------------------------------------------------------------- the plan

def overwrites(guild_id: str, owner_id: str, bot_id: str, role_id: str | None) -> list[dict]:
    """Private: @everyone (the role with the guild's id) may not view; the owner and the bot may."""
    out = [{"id": str(guild_id), "type": 0, "allow": "0", "deny": str(VIEW_CHANNEL)}]
    if role_id:
        out.append({"id": str(role_id), "type": 0, "allow": str(BOT_ALLOW), "deny": "0"})
    out.append({"id": str(bot_id), "type": 1, "allow": str(BOT_ALLOW), "deny": "0"})
    out.append({"id": str(owner_id), "type": 1, "allow": str(OWNER_ALLOW), "deny": "0"})
    return out


def fix_overwrites(existing: list[dict], wanted: list[dict]) -> list[dict]:
    """The overwrites to PUT so the wanted bits hold: allow bits added (and taken out of deny),
    deny bits added (and taken out of allow). Other bits and other overwrites stay."""
    have = {str(o.get("id")): o for o in existing or []}
    out = []
    for wo in wanted:
        o = have.get(wo["id"])
        a0, d0 = (int(o.get("allow") or 0), int(o.get("deny") or 0)) if o else (0, 0)
        a = (a0 | int(wo["allow"])) & ~int(wo["deny"])
        d = (d0 | int(wo["deny"])) & ~int(wo["allow"])
        if o is None or a != a0 or d != d0:
            out.append({"id": wo["id"], "type": wo["type"], "allow": str(a), "deny": str(d)})
    return out


def find_channel(channels: list[dict], name: str, parent_id: str | None) -> dict | None:
    """A text channel by name, the one in our category first."""
    texts = [c for c in channels if c.get("type") == TEXT and c.get("name") == name]
    return next((c for c in texts if parent_id and str(c.get("parent_id")) == str(parent_id)), None) or \
        (texts[0] if texts else None)


def find_category(channels: list[dict], name: str) -> dict | None:
    return next((c for c in channels if c.get("type") == CATEGORY and c.get("name") == name), None)


def plan(channels: list[dict], guild_id: str, owner_id: str, bot_id: str, role_id: str | None) -> list[dict]:
    """The steps that make the guild match LAYOUT, in order: create_category, create_channel
    (its parent by the category's name), overwrite (one PUT each), topic. Empty when it does."""
    want = overwrites(guild_id, owner_id, bot_id, role_id)
    steps: list[dict] = []
    for cat_name, chans in LAYOUT:
        cat = find_category(channels, cat_name)
        if cat is None:
            steps.append({"op": "create_category", "name": cat_name,
                          "body": {"name": cat_name, "type": CATEGORY, "permission_overwrites": want}})
        else:
            steps += [{"op": "overwrite", "channel": str(cat["id"]), "name": cat_name, "body": ow}
                      for ow in fix_overwrites(cat.get("permission_overwrites"), want)]
        for name, topic in chans:
            ch = find_channel(channels, name, cat["id"] if cat else None)
            if ch is None:
                steps.append({"op": "create_channel", "name": name, "category": cat_name,
                              "body": {"name": name, "type": TEXT, "topic": topic, "permission_overwrites": want}})
                continue
            steps += [{"op": "overwrite", "channel": str(ch["id"]), "name": name, "body": ow}
                      for ow in fix_overwrites(ch.get("permission_overwrites"), want)]
            if not str(ch.get("topic") or "").strip():
                steps.append({"op": "topic", "channel": str(ch["id"]), "name": name, "body": {"topic": topic}})
    return steps


def channel_map(channels: list[dict]) -> tuple[dict[str, str], dict[str, str]]:
    """(channel name -> id, category name -> id) of the layout's channels that exist."""
    chans, cats = {}, {}
    for cat_name, items in LAYOUT:
        cat = find_category(channels, cat_name)
        if cat:
            cats[cat_name] = str(cat["id"])
        for name, _ in items:
            ch = find_channel(channels, name, cat["id"] if cat else None)
            if ch:
                chans[name] = str(ch["id"])
    return chans, cats


# ---------------------------------------------------------------- applying it

def run_steps(rest: Rest, guild_id: str, steps: list[dict], channels: list[dict], log=print) -> int:
    """Run the plan's steps; returns how many went through. A step Discord refuses is logged and
    skipped, so one missing permission does not stop the rest."""
    cat_ids = {c["name"]: str(c["id"]) for c in channels if c.get("type") == CATEGORY}
    done = 0
    for s in steps:
        try:
            if s["op"] == "create_category":
                cat_ids[s["name"]] = str(rest.post(f"/guilds/{guild_id}/channels", s["body"], REASON)["id"])
            elif s["op"] == "create_channel":
                body = dict(s["body"])
                if cat_ids.get(s["category"]):
                    body["parent_id"] = cat_ids[s["category"]]
                rest.post(f"/guilds/{guild_id}/channels", body, REASON)
            elif s["op"] == "overwrite":
                ow = s["body"]
                rest.put(f"/channels/{s['channel']}/permissions/{ow['id']}",
                         {"type": ow["type"], "allow": ow["allow"], "deny": ow["deny"]}, REASON)
            elif s["op"] == "topic":
                rest.patch(f"/channels/{s['channel']}", s["body"], REASON)
            done += 1
            log(f"layout: {s['op']} {s['name']}")
        except DiscordError as e:
            log(f"layout: {s['op']} {s['name']} refused ({e})")
    return done


def ensure_role(rest: Rest, guild_id: str, bot_id: str, log=print) -> str | None:
    """The role "Pythia" (the bot's own integration role when it has that name), given to the bot."""
    try:
        roles = rest.get(f"/guilds/{guild_id}/roles") or []
        role = next((r for r in roles if r.get("name") == ROLE_NAME), None)
        if role is None:
            role = rest.post(f"/guilds/{guild_id}/roles", {"name": ROLE_NAME, "color": ROLE_COLOR, "permissions": "0",
                                                            "hoist": False, "mentionable": False}, REASON)
            log("layout: role Pythia created")
        if not role.get("managed"):
            member = rest.get(f"/guilds/{guild_id}/members/{bot_id}") or {}
            if str(role["id"]) not in [str(r) for r in member.get("roles") or []]:
                rest.put(f"/guilds/{guild_id}/members/{bot_id}/roles/{role['id']}", None, REASON)
                log("layout: role Pythia given to the bot")
        return str(role["id"])
    except DiscordError as e:
        log(f"layout: role not set ({e})")
        return None


def pinned(rest: Rest, channel_id: str) -> list[dict]:
    """The pinned messages (the newer pins endpoint, the older one when that is not there)."""
    try:
        got = rest.get(f"/channels/{channel_id}/messages/pins") or {}
        return [i.get("message") or {} for i in got.get("items") or []] if isinstance(got, dict) else list(got)
    except DiscordError as e:
        if e.status != 404:
            raise
        return list(rest.get(f"/channels/{channel_id}/pins") or [])


def pin(rest: Rest, channel_id: str, message_id: str, log=print) -> bool:
    for path in (f"/channels/{channel_id}/messages/pins/{message_id}", f"/channels/{channel_id}/pins/{message_id}"):
        try:
            rest.put(path, None, REASON)
            return True
        except DiscordError as e:
            if e.status != 404:
                log(f"layout: welcome post not pinned ({e}; the bot may need Pin Messages)")
                return False
    return False


def ensure_welcome(rest: Rest, channel_id: str, bot_id: str, known_id: str | None, log=print) -> str | None:
    """The welcome post in #status, pinned once; edited when its text changed. Never posted twice:
    the one we wrote before (known_id) is used even when the pin did not work."""
    emb = welcome_embed()

    def ours(m: dict) -> bool:
        return str((m.get("author") or {}).get("id")) == str(bot_id) and \
            any(e.get("title") == WELCOME_TITLE for e in m.get("embeds") or [])

    try:
        pins = pinned(rest, channel_id)
        msg = next((m for m in pins if ours(m)), None)
        is_pinned = msg is not None
        if msg is None and known_id:
            try:
                m = rest.get(f"/channels/{channel_id}/messages/{known_id}")
                msg = m if ours(m or {}) else None
            except DiscordError:
                msg = None
        if msg is None:
            msg = rest.post(f"/channels/{channel_id}/messages", {"embeds": [emb], "allowed_mentions": {"parse": []}})
            log("layout: welcome post written")
        elif (msg.get("embeds") or [{}])[0].get("description") != emb["description"]:
            rest.patch(f"/channels/{channel_id}/messages/{msg['id']}", {"embeds": [emb]})
            log("layout: welcome post updated")
        if not is_pinned and pin(rest, channel_id, str(msg["id"]), log):
            log("layout: welcome post pinned")
        return str(msg["id"])
    except DiscordError as e:
        log(f"layout: welcome post not written ({e})")
        return known_id


def read_state(path: Path) -> dict:
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def write_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1, ensure_ascii=False), encoding="utf-8")
    os.chmod(tmp, 0o644)
    tmp.replace(path)


def apply(rest: Rest, guild_id: str, owner_id: str, state_path: Path, log=print, now_ms: int | None = None) -> dict:
    """Lay out the guild and write the state file; returns the state."""
    guild_id, owner_id = str(guild_id), str(owner_id)
    state = read_state(state_path)
    bot_id = str(rest.get("/users/@me")["id"])
    role_id = ensure_role(rest, guild_id, bot_id, log)
    channels = rest.get(f"/guilds/{guild_id}/channels") or []
    steps = plan(channels, guild_id, owner_id, bot_id, role_id)
    if steps:
        run_steps(rest, guild_id, steps, channels, log)
        channels = rest.get(f"/guilds/{guild_id}/channels") or []
    chans, cats = channel_map(channels)
    dm = state.get("dm")
    try:
        dm = str(rest.post("/users/@me/channels", {"recipient_id": owner_id})["id"])
    except DiscordError as e:
        log(f"layout: no DM channel to the owner ({e})")
    welcome = state.get("welcome_id")
    if chans.get("status"):
        welcome = ensure_welcome(rest, chans["status"], bot_id, welcome if state.get("guild_id") == guild_id else None,
                                 log)
    state = {"guild_id": guild_id, "role_id": role_id, "channels": chans, "categories": cats, "dm": dm,
             "welcome_id": welcome, "updated_ms": now_ms or int(time.time() * 1000)}
    write_state(state_path, state)
    log(f"layout: {len(chans)} of {len(CHANNELS)} channels in the map, {len(steps)} step(s) this time")
    return state
