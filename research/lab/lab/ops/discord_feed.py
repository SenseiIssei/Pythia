"""What only the Discord bot carries: the forward report, new study verdicts, model decisions, news.

The cards that also go to Telegram reach Discord through notify.send (the briefing, the
real-money trade cards, study, Pokemon and CS2 posts). This job adds four things that have
a channel of their own on the owner's server and no Telegram post, read from the files the
jobs already write:

  forward   reports/forward/latest.json, once per new report: the headline and the paper
            books (status, days, return) to #paper-buecher
  studies   every study report (reports/<study>/latest.json, the same set the briefing
            calls studies) that is new or rewritten: its verdict to #studien
  models    the model zoo's new decisions (promoted, rejected, kept; reports/models) to #modelle
  news      the news collector's new headlines (<data>/ai/news/<day>.jsonl), those naming a
            coin first, at most five a run, each a link, to #news

  python -m lab.ops.discord_feed               all four (every 10 minutes)
  python -m lab.ops.discord_feed news forward  only those
  python -m lab.ops.discord_feed --dry-run     print the cards, post nothing, remember nothing

Each card goes in German to the channel named here and in English to its twin in the 🇬🇧 block
(#paper-books, #studies, #models, #news): built twice from the same data (one(), notify.bilingual).

Nothing without PYTHIA_DISCORD_BOT_TOKEN. The first run of each part only remembers what is
there, so the owner's server does not fill with the past. What went out is remembered in
<data>/notify/discord_feed.json; a post that failed is tried again on the next run. The app's
switches hold (Studies and factory for studies, Models for the zoo).
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import i18n, notify
from .briefing import NOT_STUDIES
from .notify import Card, Line, Links, Table, _num, nodash, short

PARTS = ("forward", "studies", "models", "news")
STUDIES_PER_RUN = 5
NEWS_PER_RUN = 5
NEWS_KEEP = 600
BOOKS_SHOWN = 12
WORDS = {
    "en": {"forward": "Paper books", "books_head": ["Book", "Days", "Return", "Status"], "study": "Study",
           "models": "Model zoo", "models_sum": "{n} new decision(s)", "news": "News", "news_sum": "{n} new headlines",
           "footer": "Pythia lab"},
    "de": {"forward": "Paper-Bücher", "books_head": ["Buch", "Tage", "Rendite", "Status"], "study": "Studie",
           "models": "Modell-Zoo", "models_sum": "{n} neue Entscheidung(en)", "news": "News",
           "news_sum": "{n} neue Schlagzeilen", "footer": "Pythia Lab"},
}
STATUS_EMOJI = {"ok": "🟢", "on_track": "🟢", "pass": "🟢", "watch": "🟠", "below": "🔴", "behind": "🔴",
                "fail": "🔴", "failed": "🔴"}


def w(key: str, lang: str):
    return WORDS.get(lang, WORDS["en"])[key]


def one(make, lang: str) -> Card | None:
    """make(lang) -> a card (or None), built so Discord can post it in the other language too."""
    c = make(lang)
    if c is None:
        return None
    return notify.bilingual(lambda lg: [make(lg) if lg != lang else c], lang)[0]


def state_path() -> Path:
    return notify.data_root() / "notify" / "discord_feed.json"


def _mtime_ms(p: Path) -> int | None:
    try:
        return int(p.stat().st_mtime * 1000)
    except OSError:
        return None


# ---------------------------------------------------------------- the cards

def forward_card(rep: dict, lang: str) -> Card:
    books = [b for b in rep.get("books") or [] if isinstance(b, dict) and b.get("name")]
    rows = []
    for b in books[:BOOKS_SHOWN]:
        ret = _num(b.get("return_pct"))
        st = str(b.get("status") or "unknown")
        rows.append([notify.short_name(b.get("label") or b.get("name"), 22), str(int(_num(b.get("days")) or 0)),
                     notify.signed_pct(ret, 1, lang) if ret is not None else "-",
                     i18n.t("fw_" + st, lang) if "fw_" + st in i18n.CATALOG["en"] else st.replace("_", " ")])
    parts: list = [Table(w("books_head", lang), rows, more=max(0, len(books) - BOOKS_SHOWN))] if rows else []
    emoji = STATUS_EMOJI.get(str(rep.get("status") or ""), "📒")
    day = str(rep.get("generated") or "")[:10]
    return Card(emoji, f"{w('forward', lang)} {day}".strip(), short(nodash(str(rep.get("headline") or rep.get("verdict")
                                                                                or "")), 600),
                parts, footer=w("footer", lang))


def study_card(name: str, rep: dict, lang: str) -> Card | None:
    """A study's verdict, or None when the report has none to tell."""
    verdict = rep.get("verdict") or rep.get("headline")
    if not isinstance(verdict, str) or not verdict.strip():
        return None
    passes = rep.get("passes")
    st = str(rep.get("status") or "").lower()
    emoji = "🟢" if passes is True else "🔴" if passes is False else STATUS_EMOJI.get(st, "🧪")
    title = rep.get("title") if isinstance(rep.get("title"), str) else name.replace("_", " ")
    return Card(emoji, f"{w('study', lang)}: {short(nodash(title), 80)}",
                short(nodash(verdict.replace("**", "")), 900), [], footer=f"reports/{name}")


def models_card(news: list[str], lang: str) -> Card:
    return Card("🧠", w("models", lang), w("models_sum", lang).format(n=len(news)),
                [Line(", ".join(news[:12]))], footer=w("footer", lang))


def news_card(items: list[dict], lang: str) -> Card:
    links = [Links([(short(nodash(str(h["title"])), 110), h.get("link"))], "•") for h in items]
    return Card("📰", w("news", lang), w("news_sum", lang).format(n=len(items)), links, footer=w("footer", lang))


# ---------------------------------------------------------------- the parts

def forward_part(st: dict, lang: str, post) -> None:
    p = notify.reports_root() / "forward" / "latest.json"
    rep = notify.read_json(p)
    at = int(_num((rep or {}).get("generated_ms")) or _mtime_ms(p) or 0) if isinstance(rep, dict) else 0
    if not at:
        return
    if "forward_ms" in st and at > int(st["forward_ms"] or 0):
        if not post("forward", one(lambda lg: forward_card(rep, lg), lang)):
            return
    st["forward_ms"] = max(at, int(st.get("forward_ms") or 0))


def studies_part(st: dict, lang: str, post, root: Path | None = None) -> None:
    root = root or notify.reports_root()
    first = "studies" not in st
    seen = st.setdefault("studies", {})
    sent = 0
    try:
        dirs = sorted(root.iterdir())
    except OSError:
        return
    for d in dirs:
        p = d / "latest.json"
        if d.name in NOT_STUDIES or not p.is_file():
            continue
        at = _mtime_ms(p)
        if at is None or at <= int(seen.get(d.name) or 0):
            continue
        if not first:
            if sent >= STUDIES_PER_RUN:
                break                                        # the rest on the next run
            rep = notify.read_json(p)
            card = one(lambda lg: study_card(d.name, rep, lg), lang) if isinstance(rep, dict) else None
            if card is not None:
                if not post("studies", card):
                    continue
                sent += 1
        seen[d.name] = at


def models_part(st: dict, lang: str, post) -> None:
    rep = notify.read_json(notify.reports_root() / "models" / "latest.json")
    if not isinstance(rep, dict):
        return
    keys, decided = [], []
    for m in rep.get("models") or []:
        if not isinstance(m, dict) or not m.get("code"):
            continue
        for d in m.get("decisions") or []:
            if isinstance(d, dict) and d.get("decision") in ("promoted", "rejected", "kept"):
                keys.append(f"{m['code']}:{d.get('date')}:{d['decision']}")
                decided.append((m["code"], str(d["decision"]), d.get("date")))
    first = "models" not in st
    seen = set(st.get("models") or [])

    def new(lg: str) -> list[str]:
        return [f"{code} {i18n.word(dec, lg)} ({day})" for k, (code, dec, day) in zip(keys, decided) if k not in seen]

    if new(lang) and not first and not post("models", one(lambda lg: models_card(new(lg), lg), lang)):
        return
    st["models"] = sorted(seen | set(keys))[-NEWS_KEEP:]


def headlines(now: int, root: Path | None = None) -> list[dict]:
    """Today's and yesterday's headlines (UTC files), those naming a coin first, newest first."""
    root = root or notify.data_root() / "ai" / "news"
    items = []
    for k in (1, 0):
        day = datetime.fromtimestamp((now - k * notify.DAY_MS) / 1000, timezone.utc).strftime("%Y-%m-%d")
        try:
            text = (root / f"{day}.jsonl").read_text(encoding="utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            try:
                h = json.loads(line)
            except ValueError:
                continue
            if isinstance(h, dict) and h.get("title") and notify.safe_url(h.get("link")):
                items.append(h)
    items.sort(key=lambda h: (bool(h.get("coins")), _num(h.get("published_us")) or 0), reverse=True)
    return items


def news_part(st: dict, lang: str, post, now: int, root: Path | None = None) -> None:
    items = headlines(now, root)
    first = "news" not in st
    order = [k for k in st.get("news") or [] if isinstance(k, str)]
    seen = set(order)
    new, titles = [], set()
    for h in items:
        key = str(h.get("link"))
        if key in seen or h["title"] in titles:
            continue
        titles.add(h["title"])
        new.append(h)
    show = [] if first else new[:NEWS_PER_RUN]
    if show and not post("news", one(lambda lg: news_card(show, lg), lang)):
        return
    # Remember everything seen this run: an hour's twenty headlines are not posted one by one later.
    order += [str(h.get("link")) for h in new]
    st["news"] = order[-NEWS_KEEP:]


# ---------------------------------------------------------------- the run

def run(parts=PARTS, now: int | None = None, dry_run: bool = False, poster=None) -> int:
    """`poster(kind, card) -> bool` replaces notify.send_discord (tests)."""
    now = now or notify.clock_ms()
    if not notify.discord_bot_token() and poster is None and not dry_run:
        notify.say("no PYTHIA_DISCORD_BOT_TOKEN: nothing to do")
        return 0
    lang = notify.alert_lang()
    settings = notify.load_settings()
    st = notify.read_json(state_path()) or {}

    def post(kind: str, card: Card) -> bool:
        if dry_run:
            notify.say(f"[{kind}] " + notify.plain(card.render("telegram", lang)))
            return True
        if poster is not None:
            return bool(poster(kind, card))
        return bool(notify.send_discord(kind, [card], lang=lang, now=now).get("delivered"))

    def switched(kind: str):
        cat = {"studies": "studies", "models": "models"}.get(kind)
        return post if cat is None or notify.enabled(settings, cat) else (lambda k, c: True)

    for part in parts:
        try:
            if part == "forward":
                forward_part(st, lang, switched(part))
            elif part == "studies":
                studies_part(st, lang, switched(part))
            elif part == "models":
                models_part(st, lang, switched(part))
            elif part == "news":
                news_part(st, lang, switched(part), now)
        except Exception as e:  # noqa: BLE001 - one broken part never holds back the others
            notify.say(f"discord feed: {part} failed ({type(e).__name__}: {e})", err=True)
    if not dry_run:
        notify.write_json(state_path(), {**st, "at": now})
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    parts = [a for a in argv if a in PARTS] or list(PARTS)
    return run(parts, dry_run="--dry-run" in argv)


if __name__ == "__main__":
    sys.exit(main())
