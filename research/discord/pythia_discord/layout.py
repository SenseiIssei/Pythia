"""The owner's server, laid out by the bot: categories, channels, topics, the role, the welcome posts.

Two language blocks, in this order: the German categories (🇩🇪 Übersicht, Echtgeld, Lab, Sammeln,
Markt), then the same in English (🇬🇧 Overview, Real money, Lab, Collecting, Markets), every
channel in both, the topics in their language, a pinned welcome post in both #status.

Idempotent and additive: what is missing is created, what is there is kept, nothing is deleted.
A German category under its old name (📊 Übersicht, ...) is renamed, so it keeps its id and its
channels. A German channel is the one of the last map (its id), else the one of that name in its
category, else one of that name anywhere outside the English block; found outside its category,
it is moved in (same id, so the map stays valid). An English channel is only ever the one of the
last map or the one of that name in its English category (#briefing, #status, #pokemon, ... have
the same name in both blocks). A channel is made private and given a topic when it has none;
the owner's topic stays. Private means: @everyone may not view it, the owner and the bot (its
member and the role "Pythia") may. Overwrites of other roles or members stay as they are. When
everything is there, the categories and channels are put in the layout's order (one PATCH).

plan() is pure (the steps for a snapshot of the channels, for the tests); apply() reads the
guild, runs the steps, pins the welcome posts, opens the DM channel to the owner and writes the
map of channel ids to the state file, which the lab reads (shared read only as
<data>/discord/channels.json):

  {"guild_id", "role_id", "de": {"briefing": id, "konten": id, ...}, "en": {"briefing": id,
   "accounts": id, ...}, "channels": the German map again (what code before the English block
   reads), "categories": {name: id}, "dm": the owner's DM channel, "welcome": {"de": id, "en": id},
   "welcome_id": the German one, "updated_ms"}
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
LANGS = ("de", "en")

# Per language, in the order shown: (category, [(channel, topic)]). Both lists have the same
# shape: the i-th channel of the i-th category is the same channel in the other language.
LAYOUTS: dict[str, list[tuple[str, list[tuple[str, str]]]]] = {
    "de": [
        ("🇩🇪 Übersicht", [
            ("briefing", "Das Morgen-Briefing um 9:00 Berlin: pump.fun, Echtgeld, Paper, Lab, Sammeln, Markt. "
                         "Kommt auch als Direktnachricht."),
            ("status", "Was wohin kommt (angepinnt) und die Befehle /status, /trades, /konten, /lab. Nur lesen."),
        ]),
        ("🇩🇪 Echtgeld", [
            ("pumpfun-trades", "Jede Echtgeld-Order des pump.fun-Bots mit Chart, die Farbe nach Ergebnis. "
                               "Kommt auch als Direktnachricht."),
            ("konten", "Echtgeld-Fills der Kraken- und Alpaca-Autopiloten. Kommt auch als Direktnachricht. "
                       "Kontostände: /konten."),
        ]),
        ("🇩🇪 Lab", [
            ("studien", "Neue Studien-Ergebnisse, die Strategiefabrik und der Forschungsdirektor."),
            ("paper-buecher", "Der Forward-Bericht: jedes Paper-Buch und jeder Autopilot gegen seinen Backtest."),
            ("modelle", "Entscheidungen des Modell-Zoos: befördert, verworfen, behalten."),
        ]),
        ("🇩🇪 Sammeln", [
            ("pokemon", "Pokemon-Karten: günstige Karten gegen ihren fairen Wert, die Spielgeld-Sammlung."),
            ("cs2-skins", "CS2-Skins: Hinweise, Trends am Steam-Markt, das Spielgeld-Portfolio."),
        ]),
        ("🇩🇪 Markt", [
            ("news", "Neue Krypto-Schlagzeilen, die mit einer Münze zuerst."),
        ]),
    ],
    "en": [
        ("🇬🇧 Overview", [
            ("briefing", "The morning briefing at 9:00 Berlin: pump.fun, real money, paper, lab, collecting, "
                         "markets. Also comes as a direct message."),
            ("status", "What goes where (pinned) and the commands /status, /trades, /konten, /lab. Read only."),
        ]),
        ("🇬🇧 Real money", [
            ("pumpfun-trades", "Every real-money order of the pump.fun bot with its chart, coloured by outcome. "
                               "Also comes as a direct message."),
            ("accounts", "Real-money fills of the Kraken and Alpaca autopilots. Also comes as a direct message. "
                         "Balances: /konten."),
        ]),
        ("🇬🇧 Lab", [
            ("studies", "New study results, the strategy factory and the research director."),
            ("paper-books", "The forward report: every paper book and autopilot against its backtest."),
            ("models", "The model zoo's decisions: promoted, rejected, kept."),
        ]),
        ("🇬🇧 Collecting", [
            ("pokemon", "Pokemon cards: cheap cards against their fair value, the play-money collection."),
            ("cs2-skins", "CS2 skins: alerts, Steam market trends, the play-money portfolio."),
        ]),
        ("🇬🇧 Markets", [
            ("news", "New crypto headlines, those naming a coin first."),
        ]),
    ],
}
LAYOUT = LAYOUTS["de"]                                       # the German block (the routes' channel names)
CHANNELS = [name for _, chans in LAYOUT for name, _ in chans]
CHANNELS_BY_LANG = {lang: [name for _, chans in LAYOUTS[lang] for name, _ in chans] for lang in LANGS}
# The German channel name -> its English twin (lab.ops.notify.DISCORD_EN has the same).
EN_NAMES = dict(zip(CHANNELS_BY_LANG["de"], CHANNELS_BY_LANG["en"]))
# The German categories' names before the English block: renamed in place, so their ids and channels stay.
OLD_CATEGORIES = {"🇩🇪 Übersicht": "📊 Übersicht", "🇩🇪 Echtgeld": "💰 Echtgeld", "🇩🇪 Lab": "🧪 Lab",
                  "🇩🇪 Sammeln": "🃏 Sammeln", "🇩🇪 Markt": "📰 Markt"}

WELCOME_TITLES = {"de": "Willkommen bei Pythia", "en": "Welcome to Pythia"}
WELCOME_TITLE = WELCOME_TITLES["de"]
WELCOME_TEXT = {
    "de": {"commands": "**Befehle** (nur für dich, nur lesen; keiner handelt, schaltet scharf, ändert Limits "
                       "oder berührt den Notschalter). Sie antworten in der Sprache des Kanals:",
           "status": "/status  pump.fun live: an oder aus, Wallet, P&L heute, Einsatz, offene Positionen",
           "trades": "/trades  die letzten 10 Echtgeld-Trades",
           "konten": "/konten  Echtgeld- und Paper-Konten",
           "lab": "/lab  die neuesten Studien und der Modell-Zoo",
           "private": "Alle Kanäle sind privat: nur du und Pythia sehen sie. Jede Nachricht kommt auf Deutsch "
                      "hier und auf Englisch im 🇬🇧-Block.",
           "footer": "Pythia · Alpha"},
    "en": {"commands": "**Commands** (for you only, read only; none of them trades, arms, changes a limit or "
                       "touches the kill switch). They answer in the channel's language:",
           "status": "/status  pump.fun live: on or off, wallet, P&L today, stake, open positions",
           "trades": "/trades  the last 10 real-money trades",
           "konten": "/konten  real-money and paper accounts",
           "lab": "/lab  the newest studies and the model zoo",
           "private": "Every channel is private: only you and Pythia see it. Every message comes in English "
                      "here and in German in the 🇩🇪 block.",
           "footer": "Pythia · Alpha phase"},
}


def welcome_embed(lang: str = "de") -> dict:
    """The pinned post in #status: what goes where, and the commands, in the channel's language."""
    w = WELCOME_TEXT[lang]
    lines = []
    for cat, chans in LAYOUTS[lang]:
        lines.append(f"**{cat}**")
        lines += [f"#{name}: {topic}" for name, topic in chans]
        lines.append("")
    lines += [w["commands"], w["status"], w["trades"], w["konten"], w["lab"], "", w["private"]]
    return {"title": WELCOME_TITLES[lang], "description": "\n".join(lines), "color": ROLE_COLOR,
            "footer": {"text": w["footer"]}}


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


def find_category(channels: list[dict], name: str | None) -> dict | None:
    return next((c for c in channels if name and c.get("type") == CATEGORY and c.get("name") == name), None)


def _pos(c: dict) -> tuple[int, int]:
    """Discord's order: by position, ties by id."""
    try:
        return int(c.get("position") or 0), int(c.get("id") or 0)
    except (TypeError, ValueError):
        return 0, 0


def resolve(channels: list[dict], known: dict | None = None) -> dict:
    """Which of the guild's channels is which part of the layout:
    {"cats": {(lang, i): category or None}, "chans": {(lang, name): channel or None}, "renames": [(category, new
    name)]}. `known` is the last map, {"de": {name: id}, "en": {name: id}}."""
    known = known or {}
    by_id = {str(c.get("id")): c for c in channels}
    texts = [c for c in channels if c.get("type") == TEXT]
    cats: dict = {}
    renames = []
    for lang in LANGS:
        for i, (cat_name, _) in enumerate(LAYOUTS[lang]):
            cat = find_category(channels, cat_name)
            if cat is None:
                cat = find_category(channels, OLD_CATEGORIES.get(cat_name))
                if cat is not None:
                    renames.append((cat, cat_name))
            cats[(lang, i)] = cat
    en_parents = {str(c["id"]) for (lang, _), c in cats.items() if lang == "en" and c}
    taken: set[str] = set()
    chans: dict = {}
    for lang in ("en", "de"):                    # English first: a German stray may never be an English one
        for i, (_, items) in enumerate(LAYOUTS[lang]):
            cat = cats[(lang, i)]
            for name, _ in items:
                k = str((known.get(lang) or {}).get(name) or "")
                ch = by_id.get(k) if k not in taken and (by_id.get(k) or {}).get("type") == TEXT else None
                same = [c for c in texts if c.get("name") == name and str(c["id"]) not in taken]
                if ch is None and cat:
                    ch = next((c for c in same if str(c.get("parent_id")) == str(cat["id"])), None)
                if ch is None and lang == "de":
                    ch = next((c for c in same if str(c.get("parent_id")) not in en_parents), None)
                if ch is not None:
                    taken.add(str(ch["id"]))
                chans[(lang, name)] = ch
    return {"cats": cats, "chans": chans, "renames": renames}


def plan(channels: list[dict], guild_id: str, owner_id: str, bot_id: str, role_id: str | None,
         known: dict | None = None) -> list[dict]:
    """The steps that make the guild match LAYOUTS, in order: rename (a German category's old name),
    create_category, overwrite (one PUT each), create_channel (its parent by the category's name),
    move (into its category), topic; when none of those is left, order (the positions, one PATCH).
    Empty when the guild matches."""
    want = overwrites(guild_id, owner_id, bot_id, role_id)
    r = resolve(channels, known)
    steps: list[dict] = [{"op": "rename", "channel": str(c["id"]), "name": new, "body": {"name": new}}
                         for c, new in r["renames"]]
    for lang in LANGS:
        for i, (cat_name, chans) in enumerate(LAYOUTS[lang]):
            cat = r["cats"][(lang, i)]
            if cat is None:
                steps.append({"op": "create_category", "name": cat_name,
                              "body": {"name": cat_name, "type": CATEGORY, "permission_overwrites": want}})
            else:
                steps += [{"op": "overwrite", "channel": str(cat["id"]), "name": cat_name, "body": ow}
                          for ow in fix_overwrites(cat.get("permission_overwrites"), want)]
            for name, topic in chans:
                ch = r["chans"][(lang, name)]
                if ch is None:
                    steps.append({"op": "create_channel", "name": name, "category": cat_name,
                                  "body": {"name": name, "type": TEXT, "topic": topic, "permission_overwrites": want}})
                    continue
                if cat is None or str(ch.get("parent_id")) != str(cat["id"]):
                    steps.append({"op": "move", "channel": str(ch["id"]), "name": name, "category": cat_name})
                steps += [{"op": "overwrite", "channel": str(ch["id"]), "name": name, "body": ow}
                          for ow in fix_overwrites(ch.get("permission_overwrites"), want)]
                if not str(ch.get("topic") or "").strip():
                    steps.append({"op": "topic", "channel": str(ch["id"]), "name": name, "body": {"topic": topic}})
    if any(s["op"] in ("rename", "create_category", "create_channel", "move") for s in steps):
        return steps                                         # the order once everything is in place
    order = positions(r)
    return steps + ([{"op": "order", "name": "positions", "body": order}] if order else [])


def positions(r: dict) -> list[dict]:
    """The PATCH body that puts the categories (German block, then English) and the channels in each
    in the layout's order; [] when they are. Other channels keep their place."""
    cats = [r["cats"][(lang, i)] for lang in LANGS for i in range(len(LAYOUTS[lang]))]
    out = []
    if sorted(cats, key=_pos) != cats:
        out += [{"id": str(c["id"]), "position": k} for k, c in enumerate(cats)]
    for lang in LANGS:
        for _, items in LAYOUTS[lang]:
            chans = [r["chans"][(lang, name)] for name, _ in items]
            if sorted(chans, key=_pos) != chans:
                out += [{"id": str(c["id"]), "position": k} for k, c in enumerate(chans)]
    return out


def channel_map(channels: list[dict], known: dict | None = None) -> tuple[dict[str, dict[str, str]], dict[str, str]]:
    """({"de": {name: id}, "en": {name: id}}, category name -> id) of the layout's channels that exist."""
    r = resolve(channels, known)
    chans: dict[str, dict[str, str]] = {lang: {} for lang in LANGS}
    for (lang, name), ch in r["chans"].items():
        if ch:
            chans[lang][name] = str(ch["id"])
    chans = {lang: {n: chans[lang][n] for n in CHANNELS_BY_LANG[lang] if n in chans[lang]} for lang in LANGS}
    cats = {LAYOUTS[lang][i][0]: str(c["id"]) for (lang, i), c in r["cats"].items() if c}
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
            elif s["op"] == "rename":
                rest.patch(f"/channels/{s['channel']}", s["body"], REASON)
                cat_ids[s["name"]] = s["channel"]
            elif s["op"] == "create_channel":
                body = dict(s["body"])
                if cat_ids.get(s["category"]):
                    body["parent_id"] = cat_ids[s["category"]]
                rest.post(f"/guilds/{guild_id}/channels", body, REASON)
            elif s["op"] == "move":
                if not cat_ids.get(s["category"]):
                    raise DiscordError(0, "PATCH", "no category " + s["category"])
                rest.patch(f"/channels/{s['channel']}", {"parent_id": cat_ids[s["category"]]}, REASON)
            elif s["op"] == "overwrite":
                ow = s["body"]
                rest.put(f"/channels/{s['channel']}/permissions/{ow['id']}",
                         {"type": ow["type"], "allow": ow["allow"], "deny": ow["deny"]}, REASON)
            elif s["op"] == "topic":
                rest.patch(f"/channels/{s['channel']}", s["body"], REASON)
            elif s["op"] == "order":
                rest.patch(f"/guilds/{guild_id}/channels", s["body"], REASON)
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


def ensure_welcome(rest: Rest, channel_id: str, bot_id: str, known_id: str | None, log=print,
                   lang: str = "de") -> str | None:
    """The welcome post in a #status, in its language, pinned once; edited when its text changed.
    Never posted twice: the one we wrote before (known_id) is used even when the pin did not work."""
    emb = welcome_embed(lang)

    def ours(m: dict) -> bool:
        return str((m.get("author") or {}).get("id")) == str(bot_id) and \
            any(e.get("title") == emb["title"] for e in m.get("embeds") or [])

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
            log(f"layout: welcome post ({lang}) written")
        elif any((msg.get("embeds") or [{}])[0].get(k) != emb[k] for k in ("description", "footer")):
            rest.patch(f"/channels/{channel_id}/messages/{msg['id']}", {"embeds": [emb]})
            log(f"layout: welcome post ({lang}) updated")
        if not is_pinned and pin(rest, channel_id, str(msg["id"]), log):
            log(f"layout: welcome post ({lang}) pinned")
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
    """Lay out the guild and write the state file; returns the state. The last map (also one
    written before the English block, "channels" only) keeps every known channel its id."""
    guild_id, owner_id = str(guild_id), str(owner_id)
    state = read_state(state_path)
    same = state.get("guild_id") == guild_id
    known = {"de": (state.get("de") or state.get("channels") or {}) if same else {},
             "en": (state.get("en") or {}) if same else {}}
    bot_id = str(rest.get("/users/@me")["id"])
    role_id = ensure_role(rest, guild_id, bot_id, log)
    channels = rest.get(f"/guilds/{guild_id}/channels") or []
    n = 0
    for _ in range(3):                    # creating and moving first, then the order (a refused step stops at 3)
        steps = plan(channels, guild_id, owner_id, bot_id, role_id, known)
        if not steps:
            break
        n += len(steps)
        run_steps(rest, guild_id, steps, channels, log)
        channels = rest.get(f"/guilds/{guild_id}/channels") or []
    chans, cats = channel_map(channels, known)
    dm = state.get("dm")
    try:
        dm = str(rest.post("/users/@me/channels", {"recipient_id": owner_id})["id"])
    except DiscordError as e:
        log(f"layout: no DM channel to the owner ({e})")
    welcome = dict(state.get("welcome") or {"de": state.get("welcome_id")}) if same else {}
    for lang in LANGS:
        if chans[lang].get("status"):
            welcome[lang] = ensure_welcome(rest, chans[lang]["status"], bot_id, welcome.get(lang), log, lang)
    state = {"guild_id": guild_id, "role_id": role_id, "de": chans["de"], "en": chans["en"], "channels": chans["de"],
             "categories": cats, "dm": dm, "welcome": welcome, "welcome_id": welcome.get("de"),
             "updated_ms": now_ms or int(time.time() * 1000)}
    write_state(state_path, state)
    log(f"layout: {len(chans['de'])} + {len(chans['en'])} of {len(CHANNELS)} + {len(CHANNELS_BY_LANG['en'])} "
        f"channels in the map, {n} step(s) this time")
    return state
