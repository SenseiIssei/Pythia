"""Messages to the owner's phone: the daily digest, the weekly report, the health alarm and every lab post.

One design for everything (the same as the engine's alerts): a card with a
bold title and one leading emoji, one short summary line, the key numbers
aligned in a monospace block (signs, thousands separators, %, a green or red
circle for plus or minus), an optional footer. Telegram gets HTML
(parse_mode HTML) with every piece of text escaped; a Discord or Slack
webhook gets the same card in markdown. The daily digest and the weekly
report come with a chart (lab.ops.charts, matplotlib) sent as a photo.

  python -m lab.ops.notify                  the daily digest, with its chart
  python -m lab.ops.notify --dry-run        print it, post nothing
  python -m lab.ops.notify --weekly         the weekly report, Sundays at 18:00
                                            Europe/Berlin (run it hourly on
                                            Sunday afternoons; --force: now)
  python3 notify.py --pending               a digest now, if one was asked for
                                            (POST /api/alerts/digest writes
                                            reports/notify/request.json), and
                                            the note on what quiet hours held
                                            back; run every 5 minutes
  python3 notify.py --health <system.json>  the health alarm
  python3 notify.py --event <category> <title> [text]
                                            one card from a shell job

notify.py itself is standard library only, so the host can run it without the
lab image; without matplotlib a digest goes out without its chart.

Every post has a category with a switch in the app (Settings, Notifications).
The engine writes the switches and the quiet hours to
reports/notify/settings.json; this file reads them. In quiet hours (23:00 to
07:00 Europe/Berlin unless changed) a lab post is held back and listed in one
note once they are over; the health alarm waits for the end of quiet hours.

Environment: PYTHIA_TELEGRAM_BOT_TOKEN and PYTHIA_TELEGRAM_CHAT_ID (the
owner's Telegram chat), or PYTHIA_ALERT_WEBHOOK with PYTHIA_ALERT_FORMAT
(discord, the default, or slack), which wins when set. PYTHIA_ALERT_PREFIX
(the footer, default Pythia), PYTHIA_QUIET_HOURS (off, or 23:00-07:00, over
the settings file), PYTHIA_ALERT_VIA=engine (post lab cards through the
engine's POST /api/alerts/event instead of directly),
PYTHIA_AUTOPILOT_STATE_URL (the engine's GET /api/state for the charts,
default http://127.0.0.1:8788/api/state, off to skip), PYTHIA_DATA and
PYTHIA_REPORTS as for the rest of the lab.

Every digest (not a dry run) is written to reports/notify/latest.json as
{"ts", "text", "html", "delivered", "photo"}, which the engine's
GET /api/alerts shows as the last digest. A digest asked for on demand does
not move the snapshot the next daily digest counts today's trades and fees
from.

The bot token and the webhook URL are secrets: never printed, logged or
written to a file.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

DAY_MS = 86_400_000
WEEK_MS = 7 * DAY_MS
LIMITS = {"telegram": 4000, "discord": 1900, "slack": 3000}
MAX_CHARS = LIMITS["telegram"]
CAPTION_LIMIT = 1000
DEFAULT_STATE_URL = "http://127.0.0.1:8788/api/state"

# The same ids, labels and emoji as the engine (pythia-core alerts_settings.rs).
CATEGORIES: dict[str, tuple[str, str]] = {
    "trades": ("Trades", "💱"),
    "rebalances": ("Rebalances", "🔁"),
    "dailyPnl": ("Daily P&L", "📊"),
    "bigMoves": ("Big moves", "🌊"),
    "autopilot": ("Autopilot events", "🤖"),
    "risk": ("Risk", "🛡️"),
    "venue": ("Venue and data problems", "📡"),
    "models": ("Models", "🧠"),
    "studies": ("Studies and factory", "🧪"),
    "listings": ("Listings", "🆕"),
    "trending": ("Trending", "🔥"),
    "cs2": ("CS2", "🎮"),
    "pokemon": ("Pokemon", "🃏"),
    "weekly": ("Weekly report", "🗓️"),
}
DEFAULT_QUIET = {"enabled": True, "start": "23:00", "end": "07:00", "timezone": "Europe/Berlin"}
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def data_root() -> Path:
    return Path(os.environ.get("PYTHIA_DATA", "/data"))


def reports_root() -> Path:
    return Path(os.environ.get("PYTHIA_REPORTS", str(data_root() / "reports")))


def notify_dir() -> Path:
    """Where the last digest, the engine's digest requests and settings live."""
    return reports_root() / "notify"


def clock_ms() -> int:
    return int(time.time() * 1000)


def say(s: str, err: bool = False) -> None:
    """Print, whatever the console's encoding (a Windows console has no emoji)."""
    stream = sys.stderr if err else sys.stdout
    try:
        print(s, file=stream, flush=True)
    except UnicodeEncodeError:
        enc = getattr(stream, "encoding", None) or "ascii"
        print(s.encode(enc, "replace").decode(enc, "replace"), file=stream, flush=True)


# ---------------------------------------------------------------- numbers

def _num(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f and abs(f) != float("inf") else None


def esc(s) -> str:
    """Escape for Telegram's HTML parse mode."""
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def esc_attr(s) -> str:
    """Escape for an attribute value in double quotes (a link's href)."""
    return esc(s).replace('"', "&quot;")


def safe_url(u) -> str | None:
    """`u` when it is a plain http(s) URL with a host and no spaces, quotes or
    control characters; None otherwise. Links in a post come from data
    (APIs, our own builders), so they are checked before they are rendered."""
    if not isinstance(u, str):
        return None
    u = u.strip()
    if not u.lower().startswith(("https://", "http://")) or len(u) > 2000:
        return None
    if any(ord(c) <= 32 or c in '"<>\\`' or ord(c) == 127 for c in u):
        return None
    host = u.split("://", 1)[1].split("/", 1)[0].split("?", 1)[0]
    return u if host and "@" not in host else None


def money(v: float, dp: int = 2) -> str:
    """$12,345.68, or -$12.30."""
    s = f"{abs(v):,.{dp}f}"
    neg = v < 0 and any(c not in "0.," for c in s)
    return f"{'-' if neg else ''}${s}"


def signed_money(v: float, dp: int = 2) -> str:
    """+$12.30 or -$12.30."""
    m = money(v, dp)
    return m if m.startswith("-") else f"+{m}"


def signed_pct(v: float | None, dp: int = 2) -> str:
    """+1.20 % or -0.45 %; n/a for nothing."""
    if v is None:
        return "n/a"
    s = f"{v:+,.{dp}f}"
    if s.startswith("-") and not any(c not in "-0.," for c in s):
        s = "+" + s[1:]
    return f"{s} %"


def dot(v: float | None) -> str:
    """A green or red circle for plus or minus, white for zero."""
    if v is None:
        return ""
    if abs(v) < 1e-9:
        return "⚪"
    return "🟢" if v > 0 else "🔴"


def _cells(s: str) -> int:
    return sum(2 if ord(c) >= 0x1F000 else 1 for c in s)


def _ljust(s: str, w: int) -> str:
    return s + " " * max(w - _cells(s), 0)


def _rjust(s: str, w: int) -> str:
    return " " * max(w - _cells(s), 0) + s


def short(s: str, n: int) -> str:
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def nodash(s: str) -> str:
    return str(s).replace("\u2014", "-").replace("\u2013", "-")


# ---------------------------------------------------------------- cards

class Rows:
    """Aligned key numbers: (label, value, sign) where sign picks the circle."""

    def __init__(self, rows: list[tuple], title: str | None = None):
        self.title = title
        self.rows = [(str(r[0]), str(r[1]), r[2] if len(r) > 2 else None) for r in rows]

    def block(self) -> str:
        lw = max((_cells(r[0]) for r in self.rows), default=0)
        vw = max((_cells(r[1]) for r in self.rows), default=0)
        out = []
        for label, value, sign in self.rows:
            line = f"{_ljust(label, lw)}  {_rjust(value, vw)}"
            d = dot(sign)
            out.append(f"{line} {d}" if d else line.rstrip())
        return "\n".join(out)


class Table:
    """A small table: words left-aligned, numbers right-aligned."""

    def __init__(self, header: list[str], rows: list[list[str]], title: str | None = None, more: int = 0):
        self.title = title
        self.header = [str(h) for h in header]
        self.rows = [[str(c) for c in r] for r in rows]
        self.more = more

    def block(self) -> str:
        n = max([len(self.header)] + [len(r) for r in self.rows])
        w = [0] * n
        for r in [self.header] + self.rows:
            for i, c in enumerate(r):
                w[i] = max(w[i], _cells(c))
        numeric = [i > 0 and all((not r[i:i + 1]) or not r[i] or r[i][0] in "+-$0123456789" for r in self.rows)
                   for i in range(n)]

        def line(r):
            cols = [(_rjust if numeric[i] else _ljust)(r[i] if i < len(r) else "", w[i]) for i in range(n)]
            return " ".join(cols).rstrip()

        out = ([line(self.header)] if self.header else []) + [line(r) for r in self.rows]
        if self.more:
            out.append(f"+{self.more} more")
        return "\n".join(out)


class Line:
    """One line of words, with an optional bold lead: Health  all green."""

    def __init__(self, text: str, lead: str | None = None):
        self.text = text
        self.lead = lead


class Links:
    """One line of links, with an optional bold lead: Cardmarket · TCGplayer.
    Each link is (label, url); a link whose URL is not a plain http(s) URL is
    shown as its label only."""

    def __init__(self, links: list[tuple[str, str | None]], lead: str | None = None):
        self.links = [(str(label), safe_url(url)) for label, url in links]
        self.lead = lead
        self.title = None

    def render(self, fmt: str) -> str:
        out = []
        for label, url in self.links:
            if not url:
                out.append(esc(label) if fmt == "telegram" else label)
            elif fmt == "telegram":
                out.append(f'<a href="{esc_attr(url)}">{esc(label)}</a>')
            elif fmt == "slack":
                out.append(f"<{url}|{label.replace('|', '/').replace('>', '')}>")
            else:
                out.append(f"[{label.replace('[', '(').replace(']', ')')}](<{url}>)")
        return " · ".join(out)


class Card:
    def __init__(self, emoji: str, title: str, summary: str | None = None, parts: list | None = None,
                 footer: str | None = None):
        self.emoji = emoji
        self.title = title
        self.summary = summary
        self.parts = list(parts or [])
        self.footer = footer

    def render(self, fmt: str = "telegram") -> str:
        head = f"{self.emoji} {self.title}".strip()
        out: list[str] = []
        if fmt == "telegram":
            bold, ital, pre, e = (lambda s: f"<b>{s}</b>"), (lambda s: f"<i>{s}</i>"), \
                (lambda s: f"<pre>{s}</pre>"), esc
        elif fmt == "slack":
            bold, ital, pre, e = (lambda s: f"*{s}*"), (lambda s: f"_{s}_"), (lambda s: f"```{s}```"), str
        else:
            bold, ital, pre, e = (lambda s: f"**{s}**"), (lambda s: f"*{s}*"), (lambda s: f"```\n{s}\n```"), str
        out.append(bold(e(head)))
        if self.summary:
            out.append(e(self.summary))
        for p in self.parts:
            if isinstance(p, Line):
                out.append((bold(e(p.lead)) + " " if p.lead else "") + e(p.text))
                continue
            if isinstance(p, Links):
                out.append((bold(e(p.lead)) + " " if p.lead else "") + p.render(fmt))
                continue
            if p.title:
                out.append(bold(e(p.title)))
            if isinstance(p, Rows) and p.rows or isinstance(p, Table) and p.rows:
                out.append(pre(e(p.block())))
        if self.footer:
            out.append(ital(e(self.footer)))
        return "\n".join(out)


def render_post(cards: list[Card], fmt: str = "telegram", limit: int | None = None) -> str:
    """Cards as one post under `limit` characters: tables are shortened first,
    then words, then whole cards are left out with a count. Never cuts a tag."""
    limit = limit or LIMITS.get(fmt, MAX_CHARS)
    cards = [Card(c.emoji, c.title, c.summary, list(c.parts), c.footer) for c in cards]

    def join(cs, dropped=0):
        s = [c.render(fmt) for c in cs]
        if dropped:
            more = f"+{dropped} more in the app"
            s.append(f"<i>{more}</i>" if fmt == "telegram" else more)
        return "\n\n".join(s)

    out = join(cards)
    if len(out) <= limit:
        return out
    while True:
        tables = [p for c in cards for p in c.parts if isinstance(p, Table) and len(p.rows) > 3]
        if not tables:
            break
        t = max(tables, key=lambda t: len(t.rows))
        cut = min(3, len(t.rows) - 3)
        t.rows, t.more = t.rows[:-cut], t.more + cut
        out = join(cards)
        if len(out) <= limit:
            return out
    dropped = 0
    while len(cards) > 1 and len(join(cards, dropped)) > limit:
        cards.pop()
        dropped += 1
    while len(join(cards, dropped)) > limit and cards[0].parts:
        cards[0].parts.pop()
        dropped += 1
    if len(join(cards, dropped)) > limit and cards[0].summary:
        cards[0].summary = short(cards[0].summary, 200)
    return join(cards, dropped)


ANCHOR = re.compile(r'<a href="([^"]*)">(.*?)</a>', re.S)


def plain(text: str) -> str:
    """A post without markup, for the app and the log. A link keeps its URL
    after its label, so the plain fallback still leads somewhere."""
    text = ANCHOR.sub(lambda m: m.group(2) + " " + m.group(1).replace("&quot;", '"'), text)
    out, in_tag = [], False
    for ch in text:
        if ch == "<":
            in_tag = True
        elif ch == ">" and in_tag:
            in_tag = False
        elif not in_tag:
            out.append(ch)
    return "".join(out).replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")


def clip(text: str, limit: int = MAX_CHARS) -> str:
    """Plain text: keep whole lines while they fit, say so when some had to go."""
    text = nodash(text)
    if len(text) <= limit:
        return text
    out: list[str] = []
    tail = "(more in the reports)"
    for line in text.split("\n"):
        if len("\n".join(out + [line, tail])) > limit:
            break
        out.append(line)
    return "\n".join(out + [tail])[:limit]


def text_card(category: str, title: str, text: str, emoji: str | None = None) -> Card:
    """A card from plain text: the first line the summary, the rest as lines."""
    lines = [ln.strip() for ln in nodash(text).splitlines() if ln.strip()]
    summary = lines[0] if lines else None
    parts = [Line(ln[2:] if ln.startswith("- ") else ln, "•" if ln.startswith("- ") else None) for ln in lines[1:]]
    return Card(emoji or CATEGORIES.get(category, ("", "🔔"))[1], title, summary, parts)


# ---------------------------------------------------------------- settings and quiet hours

def read_json(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def write_json(p: Path, data) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, p)


def load_settings() -> dict:
    """{"on": {category: bool}, "quiet": {...}} from the engine's settings.json,
    PYTHIA_QUIET_HOURS over it. A category not listed is on."""
    raw = read_json(notify_dir() / "settings.json") or {}
    on = {}
    for c in raw.get("categories") or []:
        if isinstance(c, dict) and c.get("id") in CATEGORIES:
            on[c["id"]] = bool(c.get("on", True))
    quiet = dict(DEFAULT_QUIET)
    if isinstance(raw.get("quietHours"), dict):
        quiet.update({k: v for k, v in raw["quietHours"].items() if k in DEFAULT_QUIET})
    env = (os.environ.get("PYTHIA_QUIET_HOURS") or "").strip().lower()
    if env in ("off", "0", "no", "false"):
        quiet["enabled"] = False
    elif "-" in env:
        a, b = env.split("-", 1)
        if _hhmm(a) is not None and _hhmm(b) is not None:
            quiet.update(enabled=True, start=a.strip(), end=b.strip())
    return {"on": on, "quiet": quiet}


def enabled(settings: dict, category: str | None) -> bool:
    return category is None or settings.get("on", {}).get(category, True)


def _hhmm(s: str) -> int | None:
    try:
        h, m = (int(x) for x in str(s).strip().split(":"))
    except ValueError:
        return None
    return h * 60 + m if 0 <= h < 24 and 0 <= m < 60 else None


def _last_sunday(year: int, month: int) -> int:
    d = datetime(year, month + 1, 1) - timedelta(days=1) if month < 12 else datetime(year, 12, 31)
    return d.day - (d.weekday() + 1) % 7


def local_time(ms: int, tz: str = "Europe/Berlin") -> datetime:
    """The wall clock at `ms` in `tz`. Central European time (Berlin and its
    neighbours) by its summer time rule, so no time zone database is needed;
    another zone through zoneinfo when it is there, else UTC."""
    t = datetime.fromtimestamp(ms / 1000, timezone.utc)
    if tz in ("Europe/Berlin", "Europe/Vienna", "Europe/Zurich", "Europe/Paris", "Europe/Amsterdam",
              "Europe/Brussels", "Europe/Rome", "Europe/Madrid", "Europe/Prague", "Europe/Warsaw", "CET"):
        start = datetime(t.year, 3, _last_sunday(t.year, 3), 1, tzinfo=timezone.utc)
        end = datetime(t.year, 10, _last_sunday(t.year, 10), 1, tzinfo=timezone.utc)
        off = 2 if start <= t < end else 1
        return (t + timedelta(hours=off)).replace(tzinfo=None)
    try:
        from zoneinfo import ZoneInfo
        return t.astimezone(ZoneInfo(tz)).replace(tzinfo=None)
    except Exception:  # noqa: BLE001 - no tz database: UTC
        return t.replace(tzinfo=None)


def in_quiet(settings: dict, ms: int) -> bool:
    q = settings.get("quiet") or DEFAULT_QUIET
    if not q.get("enabled"):
        return False
    s, e = _hhmm(q.get("start", "")), _hhmm(q.get("end", ""))
    if s is None or e is None or s == e:
        return False
    t = local_time(ms, q.get("timezone") or "Europe/Berlin")
    m = t.hour * 60 + t.minute
    return s <= m < e if s < e else (m >= s or m < e)


# ---------------------------------------------------------------- the destination

def config() -> tuple[str | None, str, str]:
    """(url or None, format, prefix) from the environment. A webhook wins;
    without one, PYTHIA_TELEGRAM_BOT_TOKEN and PYTHIA_TELEGRAM_CHAT_ID."""
    prefix = os.environ.get("PYTHIA_ALERT_PREFIX", "Pythia").strip()
    url = (os.environ.get("PYTHIA_ALERT_WEBHOOK") or "").strip() or None
    if url is None:
        token = (os.environ.get("PYTHIA_TELEGRAM_BOT_TOKEN") or "").strip()
        if token and (os.environ.get("PYTHIA_TELEGRAM_CHAT_ID") or "").strip():
            return f"https://api.telegram.org/bot{token}/sendMessage", "telegram", prefix
        return None, "telegram", prefix
    fmt = (os.environ.get("PYTHIA_ALERT_FORMAT") or "discord").strip().lower()
    fmt = {"slack": "slack", "text": "slack", "telegram": "telegram"}.get(fmt, "discord")
    return url, fmt, prefix


def chat_id() -> str:
    return (os.environ.get("PYTHIA_TELEGRAM_CHAT_ID") or "").strip()


def body(fmt: str, text: str) -> dict:
    if fmt == "telegram":
        if len(text) > LIMITS["telegram"]:
            return {"chat_id": chat_id(), "text": plain(text)[: LIMITS["telegram"]], "disable_web_page_preview": True}
        return {"chat_id": chat_id(), "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
    return {"text": text} if fmt == "slack" else {"content": text}


def _request(req: urllib.request.Request, timeout: float) -> tuple[bool, str | None]:
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            code = r.status
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}"
    except (urllib.error.URLError, OSError, ValueError) as e:
        # Only the kind of failure: a message could quote the host or the token.
        reason = getattr(e, "reason", None)
        return False, f"not delivered ({type(reason).__name__ if isinstance(reason, BaseException) else type(e).__name__})"
    return (200 <= code < 300), (None if 200 <= code < 300 else f"HTTP {code}")


def post(url: str, fmt: str, text: str, timeout: float = 10) -> tuple[bool, str | None]:
    """POST one message. Returns (ok, error); the error never contains the URL.
    Telegram refusing the HTML (HTTP 400) gets the text once more as plain text."""
    def go(b: dict):
        req = urllib.request.Request(url, data=json.dumps(b).encode("utf-8"), method="POST",
                                     headers={"Content-Type": "application/json", "User-Agent": "pythia-notify"})
        return _request(req, timeout)

    ok, err = go(body(fmt, text))
    if not ok and fmt == "telegram" and err == "HTTP 400":
        ok, err = go({"chat_id": chat_id(), "text": plain(text)[: LIMITS["telegram"]]})
    return ok, err


def photo_body(chat: str, caption: str, image: bytes, boundary: str) -> bytes:
    """The multipart body of a Telegram sendPhoto with an HTML caption."""
    name, mime = ("chart.jpg", "image/jpeg") if image[:2] == b"\xff\xd8" else ("chart.png", "image/png")
    out = b""
    for k, v in (("chat_id", chat), ("caption", caption), ("parse_mode", "HTML")):
        out += f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode("utf-8")
    out += (f'--{boundary}\r\nContent-Disposition: form-data; name="photo"; filename="{name}"\r\n'
            f"Content-Type: {mime}\r\n\r\n").encode("utf-8")
    return out + image + f"\r\n--{boundary}--\r\n".encode("utf-8")


def post_photo(url: str, image: bytes, caption: str, timeout: float = 30) -> tuple[bool, str | None]:
    """A photo with its caption through Telegram's sendPhoto (url is the
    sendMessage URL of the bot)."""
    boundary = f"pythia{uuid.uuid4().hex}"
    req = urllib.request.Request(url.rsplit("/", 1)[0] + "/sendPhoto",
                                 data=photo_body(chat_id(), caption, image, boundary), method="POST",
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}",
                                          "User-Agent": "pythia-notify"})
    return _request(req, timeout)


MEDIA_GROUP_MAX = 10


def photos_body(chat: str, photos: list[tuple[str, str]]) -> tuple[str, dict] | None:
    """(Telegram method, JSON body) for pictures given by URL: sendPhoto for
    one, sendMediaGroup (an album) for two to ten. Telegram fetches the
    pictures itself. Only the first picture's caption is kept, the album's
    caption; it is HTML and cut to the caption limit. None without a usable
    URL."""
    ok = [(u, c) for u, c in ((safe_url(u), c) for u, c in photos) if u][:MEDIA_GROUP_MAX]
    if not ok:
        return None
    cap = ok[0][1] or ""
    if len(cap) > CAPTION_LIMIT:
        cap = esc(short(plain(cap), CAPTION_LIMIT - 20))
    if len(ok) == 1:
        return "sendPhoto", {"chat_id": chat, "photo": ok[0][0], "caption": cap, "parse_mode": "HTML"}
    media = [{"type": "photo", "media": u, **({"caption": cap, "parse_mode": "HTML"} if i == 0 and cap else {})}
             for i, (u, _) in enumerate(ok)]
    return "sendMediaGroup", {"chat_id": chat, "media": media}


def post_photos(url: str, photos: list[tuple[str, str]], timeout: float = 30) -> tuple[bool, str | None]:
    """Pictures by URL through the bot (url is its sendMessage URL). An album
    Telegram refuses (one picture it cannot fetch fails the whole album) is
    tried once more as the first picture alone."""
    b = photos_body(chat_id(), photos)
    if b is None:
        return False, "no picture"

    def go(method: str, body: dict):
        req = urllib.request.Request(url.rsplit("/", 1)[0] + "/" + method, data=json.dumps(body).encode("utf-8"),
                                     method="POST", headers={"Content-Type": "application/json",
                                                             "User-Agent": "pythia-notify"})
        return _request(req, timeout)

    ok, err = go(*b)
    if not ok and b[0] == "sendMediaGroup":
        one = photos_body(chat_id(), photos[:1])
        if one is not None:
            ok, err = go(*one)
    return ok, err


# ---------------------------------------------------------------- sending

def held_path() -> Path:
    return notify_dir() / "held.json"


def hold(category: str | None, cards: list[Card], ms: int) -> None:
    """Remember a post held back in quiet hours, for the note after them."""
    held = read_json(held_path()) or []
    for c in cards:
        held.append({"ts": ms, "category": category, "title": c.title})
    write_json(held_path(), held[-40:])


def send(category: str | None, cards: list[Card] | Card, image: bytes | None = None, urgent: bool = False,
         now: int | None = None, dry_run: bool = False, poster=None, hold_in_quiet: bool = True,
         photos: list[tuple[str, str]] | None = None) -> dict:
    """Post cards in one message (a photo first when there is an image).

    `photos` are pictures by URL with an HTML caption, (url, caption): on
    Telegram they go first as one album (sendMediaGroup, or sendPhoto for
    one), then the cards as the message; a webhook gets the cards only.

    `category` None is always sent. A category switched off is not sent
    (reason "off"); in quiet hours a post that is not urgent is held back
    (reason "quiet") and listed once they are over. `poster(text)` replaces
    the network (tests). Returns {"delivered", "error", "reason", "text",
    "html", "photo"}.
    """
    cards = [cards] if isinstance(cards, Card) else list(cards)
    now = now or clock_ms()
    url, fmt, prefix = config()
    if prefix and cards and prefix not in (cards[-1].footer or ""):
        cards[-1].footer = f"{cards[-1].footer} · {prefix}" if cards[-1].footer else prefix
    text = render_post(cards, fmt)
    res = {"delivered": False, "error": None, "reason": None, "text": plain(text), "html": text, "photo": False}
    settings = load_settings()
    if not urgent and not enabled(settings, category):
        res["reason"] = "off"
        say(f"[{category} is switched off] {res['text']}")
        return res
    if not urgent and in_quiet(settings, now):
        res["reason"] = "quiet"
        say(f"[quiet hours, held back] {res['text']}")
        if hold_in_quiet and not dry_run:
            hold(category, cards, now)
        return res
    say(res["text"])
    if dry_run:
        res["reason"] = "dry run"
        return res
    if poster is not None:
        ok, err = poster(text)
        res.update(delivered=ok, error=err)
        return res
    if (os.environ.get("PYTHIA_ALERT_VIA") or "").strip().lower() == "engine" and category and fits_event(cards):
        ok, err = via_engine(category, cards[0], image, urgent)
        res.update(delivered=ok, error=err)
        return res
    if not url:
        res["reason"] = "no destination"
        say("no destination set (PYTHIA_TELEGRAM_BOT_TOKEN and PYTHIA_TELEGRAM_CHAT_ID): printed only.")
        return res
    if photos and fmt == "telegram" and not image:
        ok, err = post_photos(url, photos)
        res["photo"] = ok
        if not ok:
            say(f"pictures not delivered: {err}", err=True)
    if image and fmt == "telegram":
        cap = render_post(cards, fmt, CAPTION_LIMIT)
        whole = cap == text
        if not whole:
            first = cards[0]
            cap = render_post([Card(first.emoji, first.title, first.summary, [], prefix or None)], fmt, CAPTION_LIMIT)
        ok, err = post_photo(url, image, cap)
        res["photo"] = ok
        if ok and whole:
            res.update(delivered=True)
            return res
        if not ok:
            say(f"chart not delivered: {err}", err=True)
    ok, err = post(url, fmt, text)
    res.update(delivered=ok, error=err)
    return res


def fits_event(cards: list[Card]) -> bool:
    """Whether a post is one card the event endpoint can carry whole: one
    block of numbers and one table at most, no lines of words. A digest is
    not; it goes straight to the chat."""
    if len(cards) != 1:
        return False
    parts = cards[0].parts
    return (not any(isinstance(p, (Line, Links)) for p in parts)
            and sum(isinstance(p, Rows) for p in parts) <= 1 and sum(isinstance(p, Table) for p in parts) <= 1)


def via_engine(category: str, card: Card, image: bytes | None, urgent: bool) -> tuple[bool, str | None]:
    """The card as POST /api/alerts/event on the engine, which sends it with
    its own switches, quiet hours, mute and limits."""
    rows = next((p for p in card.parts if isinstance(p, Rows)), None)
    table = next((p for p in card.parts if isinstance(p, Table)), None)
    ev: dict = {"category": category, "title": card.title, "text": card.summary or "", "urgent": urgent,
                "emoji": card.emoji}
    if rows:
        ev["rows"] = [{"label": r[0], "value": r[1], **({"sign": r[2]} if r[2] is not None else {})} for r in rows.rows]
    if table:
        ev["table"] = {"header": table.header, "rows": table.rows}
    if card.footer:
        ev["footer"] = card.footer
    if image:
        p = notify_dir() / "charts" / f"event-{clock_ms()}.png"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(image)
        ev["image"] = str(p)
    base = os.environ.get("PYTHIA_AUTOPILOT_STATE_URL", DEFAULT_STATE_URL)
    url = os.environ.get("PYTHIA_ALERT_EVENT_URL") or base.rsplit("/api/", 1)[0] + "/api/alerts/event"
    req = urllib.request.Request(url, data=json.dumps(ev).encode("utf-8"), method="POST",
                                 headers={"Content-Type": "application/json"})
    return _request(req, 10)


# ---------------------------------------------------------------- reading the engine

def engine_state(timeout: float = 15) -> dict | None:
    """GET /api/state of the autopilot engine, read only; None when off or down."""
    url = os.environ.get("PYTHIA_AUTOPILOT_STATE_URL", DEFAULT_STATE_URL).strip()
    if not url or url.lower() == "off":
        return None
    try:
        with urllib.request.urlopen(urllib.request.Request(url, method="GET"), timeout=timeout) as r:
            v = json.load(r)
        return v if isinstance(v, dict) else None
    except Exception:  # noqa: BLE001 - the engine being down only costs the chart
        return None


def btc_closes(start_ms: int, end_ms: int, timeout: float = 15) -> list[tuple[int, float]]:
    """BTCUSDT closes from Binance over the span, at most 1000 points; [] when
    it does not answer (the chart then draws BTC from the engine's numbers)."""
    span = max(end_ms - start_ms, 60_000)
    interval, step = next(((i, s) for i, s in (("5m", 300_000), ("15m", 900_000), ("1h", 3_600_000),
                                                ("4h", 14_400_000), ("1d", DAY_MS)) if span / s <= 1000),
                          ("1d", DAY_MS))
    url = (f"https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval={interval}"
           f"&startTime={int(start_ms)}&endTime={int(end_ms)}&limit=1000")
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            rows = json.load(r)
        return [(int(k[0]) + step, float(k[4])) for k in rows]
    except Exception:  # noqa: BLE001
        return []


def _charts():
    """lab.ops.charts when matplotlib is there, else None."""
    try:
        if __package__:
            from . import charts
        else:
            import charts  # type: ignore[no-redef]  # a copy next to this file
        return charts if charts.available() else None
    except Exception:  # noqa: BLE001
        return None


def chart_data(state: dict | None, since_ms: int | None, now: int, btc: list[tuple[int, float]] | None = None) -> dict | None:
    """What the chart draws, from GET /api/state: per active autopilot its
    equity in % (since its start, or since `since_ms`), BTC buy and hold over
    the same span, P&L per sleeve and the positions it holds."""
    aps = [a for a in (state or {}).get("autopilots") or [] if a.get("state") in ("running", "paused")]
    if not aps:
        return None
    lines, sleeves, held = [], [], set()
    starts = []
    for a in aps:
        name = (a.get("config") or {}).get("name") or "Autopilot"
        hist = sorted((r for r in a.get("history") or [] if isinstance(r, (list, tuple)) and len(r) == 2),
                      key=lambda r: r[0])
        t0 = max(int(a.get("startedMs") or 0), since_ms or 0)
        hist = [(int(t), float(e)) for t, e in hist if int(t) >= t0 - 60_000]
        base = float(a.get("startCapital") or 0) if not since_ms else (hist[0][1] if hist else 0)
        eq = _num(a.get("equity"))
        if eq is not None:
            hist.append((now, eq))
        if base > 0 and hist:
            lines.append({"name": name, "points": [(t, (e / base - 1) * 100) for t, e in hist]})
            starts.append(hist[0][0])
        for s in a.get("bySleeve") or []:
            if not s.get("dropped") or abs(_num(s.get("pnl")) or 0) > 0:
                label = s.get("name") or s.get("strategyId") or "?"
                sleeves.append((label if len(aps) == 1 else f"{name} · {label}", _num(s.get("pnl")) or 0.0))
        held.update(a.get("held") or [])
    positions = []
    for p in (state or {}).get("positions") or []:
        if p.get("marketId") in held:
            v = abs((_num(p.get("qty")) or 0) * (_num(p.get("lastPrice")) or 0))
            if v > 0:
                positions.append((str(p.get("symbol") or p.get("marketId")).split("/")[0], v))
    positions.sort(key=lambda x: -x[1])
    btc_line = []
    if btc and starts:
        t0 = min(starts)
        pts = [(t, p) for t, p in btc if t >= t0 - 3_600_000]
        if pts:
            b0 = pts[0][1]
            btc_line = [(t, (p / b0 - 1) * 100) for t, p in pts]
    elif len(aps) == 1 and _num(aps[0].get("btcReturnPct")) is not None and lines:
        # No price series: BTC from start to now as a straight dashed line.
        btc_line = [(lines[0]["points"][0][0], 0.0), (now, float(aps[0]["btcReturnPct"]))]
    return {"autopilots": lines, "btc": btc_line, "sleeves": sleeves, "positions": positions}


def make_chart(state: dict | None, since_ms: int | None, now: int, title: str, subtitle: str,
               btc_fetch=btc_closes) -> bytes | None:
    """The PNG for a digest or report, or None (no matplotlib, no autopilot)."""
    ch = _charts()
    if ch is None or not state:
        return None
    aps = [a for a in state.get("autopilots") or [] if a.get("state") in ("running", "paused")]
    if not aps:
        return None
    t0 = since_ms or min(int(a.get("startedMs") or now) for a in aps)
    data = chart_data(state, since_ms, now, btc_fetch(t0, now) if btc_fetch else None)
    if not data or not data["autopilots"]:
        return None
    path = notify_dir() / "charts" / f"chart-{now}.png"
    try:
        ch.render(data, path, title, subtitle)
        img = path.read_bytes()
    except Exception as e:  # noqa: BLE001 - a chart never stops the digest
        say(f"chart not drawn: {type(e).__name__}: {e}", err=True)
        return None
    finally:
        # Keep the last few for a look, not a growing folder.
        olds = sorted((notify_dir() / "charts").glob("chart-*.png"))
        for p in olds[:-5]:
            p.unlink(missing_ok=True)
    return img


# ---------------------------------------------------------------- the daily digest

def day_label(ms: int) -> str:
    t = local_time(ms)
    return f"{WEEKDAYS[t.weekday()]} {t.day} {MONTHS[t.month - 1]}"


FORWARD_WORDS = {"on_track": "✅ on track", "ok": "✅ ok", "watch": "👀 watch", "early": "🌱 early",
                 "below": "🔻 below", "behind": "🔻 behind"}


def autopilot_parts(learn: dict | None, prev: dict, now: int) -> tuple[list[Rows], dict, list[float], list[str]]:
    """One block per running autopilot, the snapshot for tomorrow, today's $
    per autopilot and the ones without numbers."""
    parts, snap, today, missing = [], {}, [], []
    for a in (learn or {}).get("autopilots") or []:
        if a.get("state") != "running":
            continue
        eq, start = _num(a.get("equity")), _num(a.get("start_capital"))
        trades, fees = int(_num(a.get("trades")) or 0), _num(a.get("fees")) or 0.0
        key = str(a.get("id") or a.get("name"))
        snap[key] = {"trades": trades, "fees": fees, "at": now}
        title = f"{a.get('name', 'Autopilot')} · {a.get('mode') or '?'}"
        if eq is None:
            missing.append(title)
            continue
        rows = [("Equity", money(eq))]
        day_pct = _num(a.get("pnl_day_pct"))
        if day_pct is not None and day_pct > -100:
            d_usd = eq - eq / (1 + day_pct / 100)
            today.append(d_usd)
            rows.append(("Today", f"{signed_money(d_usd)} {signed_pct(day_pct)}", d_usd))
        tot_pct = _num(a.get("pnl_total_pct"))
        if start:
            rows.append(("Since start", f"{signed_money(eq - start)} {signed_pct(tot_pct)}", eq - start))
        vs, btc = _num(a.get("vs_btc_total_pts")), _num(a.get("btc_total_pct"))
        if vs is not None:
            rows.append(("vs BTC", f"{vs:+.2f} pts", vs))
        if btc is not None:
            rows.append(("BTC", signed_pct(btc)))
        p = prev.get(key)
        if p and 0 < now - int(p.get("at") or 0) <= 36 * 3_600_000 and trades >= int(p.get("trades") or 0):
            rows.append(("Trades today", f"{trades - int(p['trades'])} · fees {money(max(fees - float(p.get('fees') or 0), 0))}"))
        else:
            rows.append(("Trades", f"{trades} total · fees {money(fees)}"))
        parts.append(Rows(rows, title))
    return parts, snap, today, missing


def forward_line(forward: dict | None) -> Line:
    if not forward:
        return Line("no report", "Forward test")
    books = [b for b in forward.get("books") or [] if b.get("name")]
    if not books:
        return Line("no paper books", "Forward test")
    words = " · ".join(f"{b['name']} {FORWARD_WORDS.get(str(b.get('status')), str(b.get('status') or 'unknown').replace('_', ' '))}"
                       for b in books)
    return Line(words, "Forward test")


def health_line(health: dict | None, now: int) -> Line:
    if not health:
        return Line("no health check found", "Health")
    red = [c for c in health.get("checks") or [] if not c.get("ok")]
    try:
        at = datetime.strptime(health.get("at"), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
        age_h = (now / 1000 - at) / 3600
    except (TypeError, ValueError):
        age_h = None
    late = f" (last check {age_h:.0f} h ago)" if age_h is not None and age_h > 2 else ""
    if not red:
        return Line(f"✅ all green{late}", "Health")
    names = "; ".join(f"{c.get('name')} ({short(c.get('detail') or '', 60)})" for c in red)
    return Line(f"🔴 {len(red)} red: {names}{late}", "Health")


def digest_card(learn: dict | None, forward: dict | None, health: dict | None, prev: dict, now: int) -> tuple[Card, dict]:
    parts, snap, today, missing = autopilot_parts(learn, prev, now)
    if learn is None:
        summary = "No learning report found."
    elif parts or missing:
        n = len(parts) + len(missing)
        word = "autopilot" if n == 1 else "autopilots"
        if today:
            total = sum(today)
            summary = f"{n} {word} running, {signed_money(total)} today {dot(total)}"
        else:
            summary = f"{n} {word} running."
        btc_day = next((_num(a.get("btc_day_pct")) for a in learn.get("autopilots") or []
                        if a.get("state") == "running" and _num(a.get("btc_day_pct")) is not None), None)
        if btc_day is not None:
            summary += f" · BTC {signed_pct(btc_day)}"
    else:
        err = (learn.get("engine") or {}).get("error")
        summary = f"No autopilot running{f' ({short(err, 80)})' if err else ''}."
    # A phone screen: six autopilots, the rest are in the app.
    lines: list = list(parts[:6])
    if len(parts) > 6:
        lines.append(Line(f"{len(parts) - 6} more autopilots in the app"))
    lines += [Line("no equity reported", m) for m in missing]
    if learn is not None:
        gen = _num(learn.get("generated_ms"))
        if gen is not None and now - gen > 30 * 3_600_000:
            lines.append(Line(f"the last report is from {learn.get('generated')}, not today's", "Learning"))
    lines.append(forward_line(forward))
    lines.append(health_line(health, now))
    if learn and learn.get("headline"):
        lines.append(Line(short(nodash(learn["headline"]), 220), "Learning"))
    return Card("📊", f"Daily · {day_label(now)}", nodash(summary), lines), snap


def digest(learn: dict | None, forward: dict | None, health: dict | None, prev: dict, now: int,
           fmt: str = "telegram") -> tuple[str, dict]:
    """The digest as posted (HTML for Telegram) and the snapshot for tomorrow."""
    card, snap = digest_card(learn, forward, health, prev, now)
    return render_post([card], fmt), snap


def daily(dry_run: bool = False, now_ms: int | None = None, keep_snapshot: bool = True,
          request_ts: int | None = None, chart: bool = True) -> int:
    """The digest. `keep_snapshot` False (an on-demand digest) leaves the
    snapshot of trades and fees alone; `request_ts` is the request it answers."""
    now = now_ms or clock_ms()
    rep = reports_root()
    state_path = data_root() / "notify" / "state.json"
    st = read_json(state_path) or {}
    card, snap = digest_card(read_json(rep / "learn" / "latest.json"), read_json(rep / "forward" / "latest.json"),
                             read_json(data_root() / "_health" / "system.json"), st.get("autopilots") or {}, now)
    image = None
    if chart and not dry_run:
        image = make_chart(engine_state(), None, now, "Equity since start", day_label(now))
    res = send("dailyPnl", [card], image=image, now=now, dry_run=dry_run, hold_in_quiet=False)
    if dry_run or res["reason"] == "off":
        return 0
    if res["reason"] == "quiet":
        # Asked for again: --pending sends it once quiet hours are over.
        write_json(notify_dir() / "request.json", {"ts": now, "source": "quiet"})
        return 0

    latest = {"ts": now, "text": res["text"], "html": res["html"], "delivered": res["delivered"], "photo": res["photo"]}
    if request_ts is not None:
        latest["request"] = request_ts
    write_json(notify_dir() / "latest.json", latest)
    if res["reason"] == "no destination":
        return 0
    if not res["delivered"]:
        say(f"digest not delivered: {res['error']}", err=True)
        return 1
    if keep_snapshot:
        write_json(state_path, {**st, "autopilots": snap, "last_digest_ms": now})
    return 0


# ---------------------------------------------------------------- the weekly report

def _equity_at(hist: list, ms: int) -> float | None:
    best = None
    for row in sorted(hist or [], key=lambda r: r[0]):
        if int(row[0]) <= ms:
            best = float(row[1])
        else:
            break
    return best if best is not None else (float(sorted(hist)[0][1]) if hist else None)


def weekly_card(state: dict | None, prev: dict, now: int, btc_week_pct: float | None) -> tuple[Card, dict]:
    t0 = now - WEEK_MS
    a0, a1 = local_time(t0 + 3_600_000), local_time(now)
    span = (f"{a0.day} to {a1.day} {MONTHS[a1.month - 1]}" if a0.month == a1.month
            else f"{a0.day} {MONTHS[a0.month - 1]} to {a1.day} {MONTHS[a1.month - 1]}")
    aps = [a for a in (state or {}).get("autopilots") or [] if a.get("state") in ("running", "paused")]
    snap: dict = {}
    if state is None:
        return Card("🗓️", f"Weekly · {span}", "The engine did not answer: no numbers this week."), snap
    if not aps:
        return Card("🗓️", f"Weekly · {span}", "No autopilot is running."), snap
    parts: list = []
    week_total = 0.0
    sleeves: list[tuple[str, float]] = []
    for a in aps:
        cfg = a.get("config") or {}
        name, mode = cfg.get("name") or "Autopilot", cfg.get("mode") or "?"
        eq = _num(a.get("equity")) or 0.0
        start = _num(a.get("startCapital")) or 0.0
        hist = [r for r in a.get("history") or [] if isinstance(r, (list, tuple)) and len(r) == 2]
        began = int(a.get("startedMs") or now)
        e0 = start if began >= t0 else (_equity_at(hist, t0) or start)
        wk = eq - e0
        wk_pct = (eq / e0 - 1) * 100 if e0 else None
        week_total += wk
        rows = [("Equity", money(eq)), ("This week", f"{signed_money(wk)} {signed_pct(wk_pct)}", wk)]
        if start:
            rows.append(("Since start", f"{signed_money(eq - start)} {signed_pct((eq / start - 1) * 100)}", eq - start))
        if wk_pct is not None and btc_week_pct is not None:
            rows.append(("vs BTC", f"{wk_pct - btc_week_pct:+.2f} pts", wk_pct - btc_week_pct))
        dd = _num(a.get("drawdownPct"))
        if dd is not None:
            rows.append(("Below peak", f"{dd:.2f} %"))
        key = str(cfg.get("id") or name)
        trades = int(_num(a.get("trades")) or 0)
        snap[key] = {"trades": trades, "at": now}
        p = prev.get(key)
        if p and trades >= int(p.get("trades") or 0) and now - int(p.get("at") or 0) <= 8 * DAY_MS:
            rows.append(("Trades", f"{trades - int(p['trades'])} this week"))
        else:
            rows.append(("Trades", f"{trades} since start"))
        parts.append(Rows(rows, f"{name} · {mode}"))
        for s in a.get("bySleeve") or []:
            sleeves.append((s.get("name") or "?", _num(s.get("pnl")) or 0.0))
    if len(sleeves) > 1:
        best, worst = max(sleeves, key=lambda x: x[1]), min(sleeves, key=lambda x: x[1])
        parts.append(Line(f"{best[0]} {signed_money(best[1])} · worst {worst[0]} {signed_money(worst[1])}",
                          "Best sleeve"))
    n = len(aps)
    summary = f"{n} {'autopilot' if n == 1 else 'autopilots'}: {signed_money(week_total)} this week {dot(week_total)}"
    if btc_week_pct is not None:
        summary += f" · BTC {signed_pct(btc_week_pct)}"
    return Card("🗓️", f"Weekly · {span}", summary, parts), snap


def weekly_due(now: int) -> bool:
    """Sunday from 18:00 Europe/Berlin (once a week: the state says whether
    it went out, so a run at 19:00 catches a missed or quiet 18:00)."""
    t = local_time(now)
    return t.weekday() == 6 and t.hour >= 18


def weekly(dry_run: bool = False, now: int | None = None, force: bool = False, state: dict | None = None,
           btc_fetch=btc_closes) -> int:
    now = now or clock_ms()
    st_path = data_root() / "notify" / "state.json"
    st = read_json(st_path) or {}
    t = local_time(now)
    week_id = f"{t.isocalendar()[0]}-W{t.isocalendar()[1]:02d}"
    if not force and not weekly_due(now):
        say("not Sunday 18:00 in Berlin: no weekly report (use --force)")
        return 0
    if not force and st.get("last_weekly") == week_id:
        say(f"the weekly report for {week_id} went out already")
        return 0
    state = state if state is not None else engine_state()
    btc = btc_fetch(now - WEEK_MS, now) if btc_fetch else []
    btc_pct = (btc[-1][1] / btc[0][1] - 1) * 100 if len(btc) >= 2 and btc[0][1] else None
    card, snap = weekly_card(state, st.get("weekly") or {}, now, btc_pct)
    image = None if dry_run else make_chart(state, now - WEEK_MS, now, "Equity this week", card.title.split(" · ", 1)[-1],
                                            btc_fetch=lambda a, b: btc)
    res = send("weekly", [card], image=image, now=now, dry_run=dry_run, hold_in_quiet=False)
    if dry_run or res["reason"] in ("off", "quiet", "no destination"):
        return 0
    if not res["delivered"]:
        say(f"weekly report not delivered: {res['error']}", err=True)
        return 1
    write_json(st_path, {**st, "weekly": snap, "last_weekly": week_id})
    return 0


# ---------------------------------------------------------------- on demand, and after quiet hours

def flush_held(now: int | None = None) -> int:
    """After quiet hours: one note with what they held back."""
    now = now or clock_ms()
    held = read_json(held_path()) or []
    if not held:
        return 0
    settings = load_settings()
    if in_quiet(settings, now):
        return 0
    q = settings["quiet"]
    rows = []
    for h in held[:30]:
        t = local_time(int(h.get("ts") or now))
        rows.append([f"{t.hour:02d}:{t.minute:02d}", short(h.get("title") or "?", 40)])
    n = len(held)
    card = Card("🌙", "Quiet hours are over",
                f"{n} lab {'post was' if n == 1 else 'posts were'} held back from {q['start']} to {q['end']}.",
                [Table(["Time", "Post"], rows, more=max(n - 30, 0))])
    res = send(None, [card], now=now)
    if res["delivered"] or res["reason"] == "no destination":
        held_path().unlink(missing_ok=True)
        return 0
    return 1


def pending(now_ms: int | None = None) -> int:
    """A digest now when reports/notify/request.json asks for one after the
    last digest. One request gets one digest, delivered or not: the result is
    in latest.json, and the operator can ask again. Then the note on what
    quiet hours held back, if they are over."""
    now = now_ms or clock_ms()
    flush_held(now)
    ask = read_json(notify_dir() / "request.json") or {}
    req = _num(ask.get("ts"))
    if req is None:
        say("no digest request")
        return 0
    last = read_json(notify_dir() / "latest.json") or {}
    # `request` too: the engine's clock may run ahead of this one.
    answered = max(_num(last.get("ts")) or 0, _num(last.get("request")) or 0)
    if req <= answered:
        say("no new digest request")
        return 0
    # The morning digest held by quiet hours is the daily one: it moves the snapshot.
    return daily(now_ms=now, keep_snapshot=ask.get("source") == "quiet", request_ts=int(req))


# ---------------------------------------------------------------- the health alarm

def health_step(system: dict | None, st: dict) -> tuple[Card | None, dict]:
    """(card to post or None, new state). Counts runs, not calls: the same
    system.json (same `at`) is counted once."""
    st = dict(st)
    if not system:
        return None, st
    at = system.get("at")
    if at and at == st.get("last_at"):
        return None, st
    st["last_at"] = at
    if system.get("ok"):
        was = st.get("posted")
        st.update(bad_runs=0, posted=False)
        if was:
            return Card("✅", "Health check all green again", f"Since the check at {at}."), st
        return None, st
    st["bad_runs"] = int(st.get("bad_runs") or 0) + 1
    if st["bad_runs"] >= 2 and not st.get("posted"):
        st["posted"] = True
        red = [c for c in system.get("checks") or [] if not c.get("ok")]
        parts = [Line(short(c.get("detail") or "", 160), str(c.get("name"))) for c in red] or [Line("no check named")]
        card = Card("🩺", f"Health check red for {st['bad_runs']} runs",
                    f"{len(red)} {'check' if len(red) == 1 else 'checks'} not ok at {at}.", parts)
        return card, st
    return None, st


def health(path: Path, now: int | None = None) -> int:
    state_path = path.with_name("alert_state.json")
    before = read_json(state_path) or {}
    card, st = health_step(read_json(path), before)
    if card:
        res = send("venue", [card], now=now, hold_in_quiet=False)
        if res["reason"] == "quiet":
            # Said after quiet hours: the next bad run tries again. A recovery
            # in the night is not worth a message.
            st["posted"] = False
        elif res["reason"] is None and not res["delivered"]:
            say(f"health alert not delivered: {res['error']}", err=True)
            return 1  # state not saved: the next run tries again
    write_json(state_path, st)
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if "--health" in argv:
        i = argv.index("--health")
        path = Path(argv[i + 1]) if i + 1 < len(argv) else data_root() / "_health" / "system.json"
        return health(path)
    if "--pending" in argv:
        return pending()
    if "--weekly" in argv:
        return weekly(dry_run="--dry-run" in argv, force="--force" in argv)
    if "--event" in argv:
        i = argv.index("--event")
        rest = argv[i + 1:]
        if len(rest) < 2 or rest[0] not in CATEGORIES:
            say(f"usage: notify.py --event <{'|'.join(CATEGORIES)}> <title> [text]", err=True)
            return 2
        card = Card(CATEGORIES[rest[0]][1], rest[1], rest[2] if len(rest) > 2 else None)
        res = send(rest[0], [card], urgent="--urgent" in argv)
        return 0 if res["delivered"] or res["reason"] else 1
    return daily(dry_run="--dry-run" in argv)


if __name__ == "__main__":
    sys.exit(main())
