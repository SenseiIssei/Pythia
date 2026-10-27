"""Pythia News: what happens in the lab as newspaper articles, for the app's News page (?page=news).

Every 30 minutes (job `news`) the sources below are read and turned into articles by fixed German templates (what
happened, what it means, the numbers, what comes next), written to reports/news/articles.json: newest first, at most
MAX_ARTICLES. Each article: id (stable), time, category (CATEGORIES), headline, teaser, body (Markdown, 150 to 600
words), tags, about (node ids of Lab Live: book:<name>, model:<code>, factory:F3, bot:pumpfun, job:<name>), source
(the file it was written from), importance (1 to 3) and a key number for the front page.

  lanes      <data>/reports/lanes/*.json, every research task's result, done or stopped, with its German report
  studies    results/*.md, a new or changed write-up: its verdict section (the first run writes only the newest ones)
  factories  F3 (reports/pumpfun_rt/factory.json), F2 (reports/smallaccount/factory.json), the strategy factory
             (reports/factory/latest.json), the pump.fun zoo's changes, the allocator's pick, the model zoo's verdicts
  books      the forward report's paper books: a book reaching its bar, a new high, a drawdown past its backtest's
  money      the live bots' status: switched on or off is news once (never the wallet's address)
  health     _health/jobs.json: a job turning red, or green again; a recorder stream going stale
  briefing   the morning briefing's text (reports/notify/latest.json)

Dedupe: one event, one id. The same id with other content edits the article and marks it updated. What the job
remembers between runs (hashes, states, peaks) is reports/news/state.json. A missing source is skipped, a broken
one too (the others still run).

The wording comes from the templates. If the local model (lab.ai.local, the relay of B4) answers within its budget,
it may reword the teaser of a new article; an answer with a number that is not in the facts is thrown away and the
template stays. The body is never reworded.

  python -m lab.ops.news             write reports/news/articles.json
  python -m lab.ops.news --no-llm    the templates only
  python -m lab.ops.news --print     print the new articles, write nothing
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import lablive, notify
from .lablive import de, de_pct, _num

CATEGORIES = ("Forschung", "Fabrik", "Modelle", "Daten", "Geld", "Betrieb", "Warnung")
MAX_ARTICLES = 300
MIN_WORDS, MAX_WORDS = 150, 600
FIRST_STUDIES = 10                    # the first run writes the newest write-ups only; the rest are remembered
POLISH_MAX = 6
LLM_BUDGET_SEC = 60
VERDICT = re.compile(r"(?i)\b(answer|verdict|result|conclusion|what it means|ergebnis|antwort|fazit|urteil)\b")
KEY = re.compile(r"[-+−]?\d+(?:[.,]\d+)?\s?(?:%|SOL|bps|EUR|USD|USDC|x\b)")
DATA_JOBS = ("collect", "free-", "candles", "backfill", "trending", "listings", "recorder", "dexscreener")

# Each category's background paragraph: it explains the kind of news to a reader who does not know the lab, and
# fills a short article up to MIN_WORDS.
BACKGROUND = {
    "Forschung": ("Zum Hintergrund: Jede Studie im Pythia-Labor wird vorher registriert. Das heißt, Frage, Daten, "
                  "Prüfung und die Hürde stehen fest, bevor ein Ergebnis gerechnet wird. So kann ein gutes Ergebnis "
                  "nicht nachträglich schöngerechnet werden. Was die Hürde nicht schafft, bleibt Papier. Was sie "
                  "schafft, läuft zuerst als Paper-Buch weiter, mit echten Kursen und echten Kosten, aber ohne echtes Geld."),
    "Fabrik": ("Zum Hintergrund: Die Fabriken des Labors suchen jede Nacht automatisch nach neuen Handelsregeln. Jeder "
               "Versuch landet im Ledger, damit die Hürde mit der Zahl der Versuche wächst: wer viel sucht, findet auch "
               "viel Zufall. Ein Kandidat zählt erst, wenn er auch auf zurückgehaltenen Tagen besteht, die die Suche nie "
               "gesehen hat. Danach läuft er als Schatten auf Papier, nie direkt mit echtem Geld."),
    "Modelle": ("Zum Hintergrund: Die Modelle des Labors laufen im Schatten. Sie sagen jeden Tag etwas voraus, und "
                "das wird gegen eine einfache Basislinie gewertet. Ein Modell ersetzt seinen Vorgänger nur, wenn es "
                "auf Daten besser ist, die es beim Training nicht gesehen hat. Kein Modell setzt allein eine Order, "
                "und keines ändert den Echtgeld-Bot."),
    "Daten": ("Zum Hintergrund: Alles im Labor hängt an den Daten. Der Rekorder zeichnet rund um die Uhr Orderbücher "
              "und Trades auf, dazu kommen Sammler für Funding, Optionen, Schlagzeilen und die pump.fun-Chain. Fällt "
              "ein Sammler aus, fehlen den Modellen und Studien später genau diese Stunden. Darum meldet die "
              "Gesundheitsprüfung jede Lücke sofort."),
    "Geld": ("Zum Hintergrund: Pythia arbeitet zuerst auf Papier. Ein Paper-Buch handelt mit echten Kursen und "
             "echten Kosten, aber ohne echtes Geld. Erst wenn ein Buch seine vorher festgelegte Hürde über genug Tage "
             "und Trades schafft, kommt echtes Geld überhaupt in Frage, und auch dann nur nach der Freigabe des "
             "Besitzers, mit festen Grenzen und einem Notaus."),
    "Betrieb": ("Zum Hintergrund: Das Labor läuft auf einem eigenen Server. Eine Jobtabelle legt fest, was wann läuft; "
                "jeder Lauf wird aufgezeichnet. Die Gesundheitsprüfung schaut jede Stunde auf jeden Job, jeden "
                "Container, jeden Datenstrom und die Platte. Das Morgenbriefing fasst den Stand jeden Tag um 9 Uhr "
                "Berliner Zeit zusammen."),
    "Warnung": ("Zum Hintergrund: Eine Warnung heißt nicht, dass Geld verloren ist. Sie heißt, dass etwas nicht so "
                "läuft, wie es soll, und dass jemand hinschauen sollte. Die meisten Warnungen erledigen sich mit dem "
                "nächsten Lauf. Bleibt eine bestehen, meldet die Gesundheitsprüfung sie weiter, bis sie behoben ist."),
}
GENERAL = ("Über Pythia News: Diese Artikel schreibt das Labor selbst, aus seinen eigenen Berichten und Statusdateien, "
           "nach festen Vorlagen. Jede Zahl steht so in der Quelle, die oben genannt ist. Ändert sich ein Ereignis, wird "
           "sein Artikel bearbeitet und als aktualisiert markiert. Was hier steht, ist ein Bericht und keine Empfehlung: "
           "Pythia handelt zuerst auf Papier, und über echtes Geld entscheidet allein der Besitzer. Die Karte Lab Live "
           "zeigt zu jedem Artikel, welche Teile des Labors betroffen sind.")
ABOUT = ("Über Pythia: Pythia ist ein Handelssystem, das zuerst auf Papier arbeitet. Das Labor sammelt Daten, prüft "
         "Ideen in vorher registrierten Studien, lässt Fabriken nach Regeln suchen und Modelle im Schatten "
         "vorhersagen. Was besteht, läuft als Paper-Buch weiter. Nur ein kleiner Bot handelt mit echtem Geld, mit "
         "festen Grenzen und einem Notaus, und nur, wenn der Besitzer ihn einschaltet.")
NEXT = {
    "Forschung": "Die Ergebnisse fließen in die nächste Runde des Forschungsplans; neue Fragen werden wieder vorher registriert.",
    "Fabrik": "Die nächste Nacht sucht weiter. Ein Kandidat, der besteht, erscheint hier als eigener Artikel.",
    "Modelle": "Der Zoo wertet weiter jeden Tag. Ein Wechsel der Auswahl erscheint hier als eigener Artikel.",
    "Daten": "Die Gesundheitsprüfung schaut weiter jede Stunde nach. Eine neue Lücke erscheint hier sofort.",
    "Geld": "Das Buch läuft weiter auf Papier. Über echtes Geld entscheidet allein der Besitzer.",
    "Betrieb": "Der nächste Lauf folgt nach der Jobtabelle; Pythia News berichtet, wenn sich etwas ändert.",
    "Warnung": "Die Gesundheitsprüfung schaut weiter jede Stunde nach. Wird es wieder grün, steht das hier.",
}


# ---------------------------------------------------------------- small helpers

def words(s: str) -> int:
    return len(re.findall(r"\S+", s or ""))


def clean(s, n: int | None = None) -> str:
    s = " ".join(notify.nodash(str(s or "")).split())
    return notify.short(s, n) if n else s


def day_of(ms) -> str:
    v = _num(ms)
    return datetime.fromtimestamp(v / 1000, timezone.utc).strftime("%Y-%m-%d") if v else ""


def de_day(ms) -> str:
    v = _num(ms)
    return datetime.fromtimestamp(v / 1000, timezone.utc).strftime("%d.%m.%Y") if v else "-"


def b(x: str) -> str:
    """A number in bold: the page highlights it."""
    return f"**{x}**"


def plain(text: str) -> str:
    """Markdown as one plain line: no headings, list marks, quotes, bold or code marks."""
    lines = [re.sub(r"^\s*(?:[-*+>]|\d+[.)])\s+", "", ln) for ln in str(text or "").splitlines()
             if ln.strip() and not ln.lstrip().startswith(("#", "|", "```"))]
    return clean(" ".join(lines).replace("**", "").replace("`", ""))


def demote(md: str) -> str:
    """A quoted report's headings below the article's own (## is the article's level)."""
    return re.sub(r"(?m)^#{1,3}\s+", "### ", md)


def sentences(text: str, n: int = 2) -> str:
    parts = re.split(r"(?<=[.!?])\s+", plain(text))
    return " ".join(p for p in parts[:n] if p)


def fit(body: str, category: str) -> str:
    """The body between MIN_WORDS and MAX_WORDS: the category's background fills a short one, a long one is cut
    after its last whole line that fits (a quoted report may be long)."""
    fill = ["\n\n## Hintergrund\n\n" + BACKGROUND[category], "\n\n" + GENERAL, "\n\n" + ABOUT]
    body = body.rstrip()
    while fill and words(body) < MIN_WORDS:
        body += fill.pop(0)
    if words(body) > MAX_WORDS:
        out, n = [], 0
        for line in body.splitlines():
            w = words(line)
            if n + w > MAX_WORDS - 8:
                out.append("\n*(gekürzt; der ganze Text steht in der Quelle)*")
                break
            out.append(line)
            n += w
        body = "\n".join(out)
    return body.strip()


def article(aid: str, time_ms: int, category: str, headline: str, teaser: str, sections: list[tuple[str, str]], *,
            tags=(), about=(), source: str = "", importance: int = 1, key: dict | None = None) -> dict:
    sections = list(sections) + ([("Quelle", f"`{source}`")] if source else [])
    body = "\n\n".join(f"## {h}\n\n{t.strip()}" if h else t.strip() for h, t in sections if t and t.strip())
    body = fit(lablive.scrub(body, None), category)
    a = {"id": aid, "time_ms": int(time_ms), "time": lablive.ms_iso(time_ms), "category": category,
         "headline": clean(lablive.scrub(headline, None), 140), "teaser": clean(lablive.scrub(teaser, None), 320),
         "body": body,
         "tags": sorted({str(t) for t in tags if t}), "about": sorted({str(x) for x in about if x}),
         "source": source, "importance": max(1, min(3, int(importance))), "key": key}
    a["hash"] = hashlib.sha1(json.dumps([a["headline"], a["teaser"], a["body"], a["key"]], ensure_ascii=False)
                             .encode("utf-8")).hexdigest()[:16]
    return a


def mentions(text: str, known: dict[str, str]) -> list[str]:
    """The Lab Live nodes a text names (books, models, factories, bots by their own names)."""
    out = set()
    for alias, nid in known.items():
        if re.search(r"(?<![\w-])" + re.escape(alias) + r"(?![\w-])", text or ""):
            out.add(nid)
    return sorted(out)


def key_of(text: str, label: str = "Kennzahl") -> dict | None:
    m = KEY.search(text or "")
    return {"label": label, "value": m.group(0).replace("−", "-")} if m else None


# ---------------------------------------------------------------- the sources

class Ctx:
    def __init__(self, root: Path, reports: Path, results: Path, now: int, state: dict, known: dict[str, str]):
        self.root, self.reports, self.results, self.now, self.state, self.known = root, reports, results, now, state, known


def src_lanes(c: Ctx) -> list[dict]:
    out = []
    d = c.reports / "lanes"
    for p in sorted(d.glob("*.json")) if d.is_dir() else []:
        r = notify.read_json(p)
        if not isinstance(r, dict) or not r.get("name"):
            continue
        name, title = str(r["name"]), clean(r.get("title") or r["name"], 100)
        done = r.get("status") == "done"
        at = int((_num(r.get("at")) or p.stat().st_mtime) * 1000)
        report = lablive.scrub(str(r.get("report") or ""), None).strip()
        reason = clean(r.get("reason"), 300)
        files = [str(f) for f in r.get("files") or [] if isinstance(f, str)]
        teaser = sentences(report, 2) if report else (
            f"Die Forschungsaufgabe „{title}“ ist abgeschlossen." if done else
            f"Die Forschungsaufgabe „{title}“ wurde gestoppt" + (f": {reason}" if reason else "."))
        what = (f"Die Aufgabe „{title}“ ({name}) ist am {de_day(at)} " + ("fertig geworden" if done else "gestoppt worden")
                + (f", Stand im Repository: Commit {clean(r.get('commit'), 12)}." if r.get("commit") else "."))
        sections = [("Was passiert ist", what)]
        if report:
            sections.append(("Der Bericht", demote(report)))
        if reason:
            sections.append(("Warum gestoppt" if not done else "Anmerkung", reason))
        sections.append(("Was es bedeutet",
                         "Das Ergebnis ist im Code und in den Berichten angekommen und läuft ab dem nächsten Einsatz mit."
                         if done else "Die Aufgabe hat nichts geändert, was läuft; sie wird neu geplant oder fallen gelassen."))
        sections.append(("Die Zahlen", f"Geänderte Dateien: {b(str(len(files)))}." + (
            "\n\n" + "\n".join(f"- `{f}`" for f in files[:12]) if files else "")))
        sections.append(("Wie es weitergeht", NEXT["Forschung"]))
        out.append(article(f"lane-{name}", at, "Forschung" if done else "Betrieb",
                           ("Erledigt: " if done else "Gestoppt: ") + title, teaser, sections,
                           tags=["aufgabe", "erledigt" if done else "gestoppt"],
                           about=mentions(f"{title} {report}", c.known), source=f"reports/lanes/{p.name}",
                           importance=2 if done else 1, key={"label": "Dateien geändert", "value": str(len(files))}))
    return out


def study_parts(text: str) -> tuple[str, str]:
    """The write-up's title and its verdict section (else its first paragraph)."""
    lines = text.splitlines()
    title = next((ln.lstrip("# ").strip() for ln in lines if ln.startswith("# ")), "")
    secs, cur, head = [], [], None
    for ln in lines:
        if ln.startswith("## "):
            if head is not None or cur:
                secs.append((head, "\n".join(cur).strip()))
            head, cur = ln[3:].strip(), []
        elif not ln.startswith("# "):
            cur.append(ln)
    secs.append((head, "\n".join(cur).strip()))
    verdict = next((t for h, t in secs if h and VERDICT.search(h) and t), "")
    if not verdict:
        verdict = next((t.split("\n\n")[0] for _, t in secs if t), "")
    return title, verdict


def src_studies(c: Ctx) -> list[dict]:
    d = c.results
    if not d.is_dir():
        return []
    first = "results" not in c.state
    seen = c.state.setdefault("results", {})
    files = sorted(d.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    out = []
    for i, p in enumerate(files):
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        h = hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]
        if seen.get(p.stem) == h:
            continue
        changed = p.stem in seen
        seen[p.stem] = h
        if first and i >= FIRST_STUDIES:
            continue
        title, verdict = study_parts(text)
        title = clean(title or p.stem.replace("_", " "), 110)
        verdict = notify.nodash(verdict)
        verdict = " ".join(verdict.split()[:320]) if words(verdict) > 320 else verdict
        prereg = p.stem.endswith(("_prereg", "_plan"))
        review = p.stem.startswith("review_")
        kind = "Vorregistriert" if prereg else "Prüfbericht" if review else "Studie"
        at = int(p.stat().st_mtime * 1000)
        what = (f"Im Labor ist {'eine neue Fassung' if changed else 'ein neuer Bericht'} von `results/{p.name}` "
                f"erschienen: „{title}“." + (" Es ist eine Vorregistrierung: Frage, Daten und Hürde stehen fest, "
                                             "gerechnet ist noch nichts." if prereg else ""))
        quote = "\n".join("> " + ln if ln.strip() else ">" for ln in verdict.splitlines()) if verdict else ""
        sections = [("Was passiert ist", what),
                    ("Das Urteil im Wortlaut" if not prereg else "Der Plan im Wortlaut", quote),
                    ("Was es bedeutet",
                     "Ein Ergebnis gilt nur so, wie es vorher registriert war. Was hier nicht besteht, wird nicht "
                     "eingesetzt; was besteht, läuft zuerst auf Papier." if not review else
                     "Ein Prüfbericht schaut von außen auf das ganze System. Seine Befunde werden einzeln abgearbeitet."),
                    ("Wie es weitergeht", NEXT["Forschung"])]
        k = key_of(verdict)
        out.append(article(f"study-{p.stem}", at, "Forschung", f"{kind}: {title}",
                           f"{kind}: „{title}“. " + (notify.short(sentences(verdict, 1), 220) if verdict else ""), sections,
                           tags=["studie", "vorregistrierung" if prereg else "pruefung" if review else "ergebnis"],
                           about=mentions(f"{title} {verdict}", c.known), source=f"results/{p.name}",
                           importance=3 if review else 1 if prereg else 2, key=k))
    return out


def src_factories(c: Ctx) -> list[dict]:
    out = []
    f3 = notify.read_json(c.reports / "pumpfun_rt" / "factory.json")
    if isinstance(f3, dict) and f3.get("night"):
        night = str(f3["night"])
        at = lablive.stamp(f3) or c.now
        best = next((x for x in f3.get("best") or [] if isinstance(x, dict) and x.get("id")), {})
        hold = next((x for x in f3.get("holdback") or [] if isinstance(x, dict) and x.get("id") == best.get("id")), {})
        bar = f3.get("bar") or {}
        books = [str(x.get("book")) for x in f3.get("books") or [] if isinstance(x, dict) and x.get("book")]
        props = [clean(x, 80) for x in f3.get("proposals") or []]
        n = int(_num(f3.get("trials_tonight")) or 0)
        head = (f"F3-Fabrik: {len(props)} Vorschlag für den Besitzer" if props else
                f"F3-Fabrik: {n} neue Versuche, bester Kandidat {best.get('id') or '-'}")
        nums = [f"- Versuche diese Nacht: {b(de(n, 0))}, insgesamt {b(de(f3.get('trials_ever'), 0))}",
                f"- Hürde (Sharpe): {b(de(bar.get('sharpe'), 3))} bei {de(bar.get('trials'), 0)} Versuchen"]
        if best:
            nums.append(f"- Bester Kandidat {best.get('id')}: {b(de(best.get('pnl_sol'), 3, 'SOL'))} auf "
                        f"{de(best.get('entries'), 0)} Einstiegen der Suchtage")
        if hold:
            nums.append(f"- Auf den zurückgehaltenen Tagen: {b(de(hold.get('pnl_sol'), 3, 'SOL'))} auf {de(hold.get('entries'), 0)} Einstiegen")
        nums.append(f"- Paper-Bücher der Fabrik: {b(str(len(books)))}")
        sections = [("Was passiert ist", f"Die pump.fun-Fabrik F3 hat in der Nacht zum {night} {n} neue Regeln ausprobiert."),
                    ("Die Zahlen", "\n".join(nums)),
                    ("Was es bedeutet", "Ein bester Kandidat der Suchtage ist noch kein Gewinner: erst die "
                                        "zurückgehaltenen Tage zeigen, ob er hält. " + (
                                            "Es liegen Vorschläge für den Besitzer vor: " + ", ".join(props) + "."
                                            if props else "Einen Vorschlag für den Besitzer gibt es diesmal nicht.")),
                    ("Wie es weitergeht", NEXT["Fabrik"])]
        out.append(article(f"factory-F3-{night}", at, "Fabrik", head,
                           f"Die F3-Fabrik hat {n} Regeln geprüft; der beste Kandidat ist {best.get('id') or 'keiner'}.",
                           sections, tags=["fabrik", "pumpfun", "F3"],
                           about=["factory:F3"] + [f"book:{x}" for x in books], source="reports/pumpfun_rt/factory.json",
                           importance=3 if props else 2, key={"label": "Versuche", "value": de(n, 0)}))
    f2 = notify.read_json(c.reports / "smallaccount" / "factory.json")
    if isinstance(f2, dict) and f2.get("run_id"):
        run = str(f2["run_id"])
        at = lablive.stamp(f2) or c.now
        ev = (f2.get("search") or {}).get("evaluated")
        pool = (f2.get("pool_after") or {}).get("n_trials")
        shadows = f2.get("shadows") or []
        sections = [("Was passiert ist", f"Die Fabrik für kleine Konten F2 hat am {run} {de(ev, 0)} neue Regeln für "
                                         "Wallets von 40 und 100 Euro gerechnet, zu echten Jupiter-Kosten."),
                    ("Die Zahlen", f"- Neu gerechnet: {b(de(ev, 0))}\n- Versuche im Pool: {b(de(pool, 0))}\n"
                                   f"- Schatten-Wallets: {b(str(len(shadows)))}"),
                    ("Der Bericht im Wortlaut", "> " + clean(f2.get("headline"), 400)),
                    ("Was es bedeutet", "Eine Regel kommt nur in eine Schatten-Wallet, wenn sie auf dem "
                                        "zurückgehaltenen Zeitraum besser ist als SPYx zu halten und nicht mehr als 20 % "
                                        "verliert."),
                    ("Wie es weitergeht", NEXT["Fabrik"])]
        out.append(article(f"factory-F2-{run}", at, "Fabrik", f"F2-Fabrik: {de(ev, 0)} Regeln für kleine Wallets geprüft",
                           f"Die F2-Fabrik hat {de(ev, 0)} Regeln geprüft; {len(shadows)} Schatten-Wallets laufen.",
                           sections, tags=["fabrik", "F2", "kleine-konten"], about=["factory:F2"],
                           source="reports/smallaccount/factory.json", importance=1,
                           key={"label": "Regeln geprüft", "value": de(ev, 0)}))
    fs = notify.read_json(c.reports / "factory" / "latest.json")
    if isinstance(fs, dict) and fs.get("run_id"):
        run = str(fs["run_id"])
        at = lablive.stamp(fs) or c.now
        pool = (fs.get("pool_after") or {}).get("n_trials")
        prom = fs.get("promoted") or []
        sections = [("Was passiert ist", f"Die Strategie-Fabrik hat ihren Lauf {run} beendet."),
                    ("Der Bericht im Wortlaut", "> " + clean(fs.get("headline") or fs.get("verdict"), 400)),
                    ("Die Zahlen", f"- Versuche im Pool: {b(de(pool, 0))}\n- Befördert: {b(str(len(prom)))}\n"
                                   f"- Schatten: {b(str(len(fs.get('shadows') or [])))}"),
                    ("Was es bedeutet", "Jeder Versuch hebt die Hürde für den nächsten. Befördert wird nur, was die "
                                        "zurückgehaltenen Prüfungen nach Kosten besteht."),
                    ("Wie es weitergeht", NEXT["Fabrik"])]
        out.append(article(f"factory-S-{run}", at, "Fabrik", f"Strategie-Fabrik: Lauf {run}, {len(prom)} befördert",
                           f"Die Strategie-Fabrik hat ihren Lauf {run} beendet; im Pool sind {de(pool, 0)} Versuche.",
                           sections, tags=["fabrik", "strategie"], about=["factory:strategy"],
                           source="reports/factory/latest.json", importance=3 if prom else 1,
                           key={"label": "Versuche im Pool", "value": de(pool, 0)}))
    return out


def src_models(c: Ctx) -> list[dict]:
    out = []
    zoo = notify.read_json(c.reports / "pumpfun_rt" / "zoo.json")
    for label, v in ((zoo or {}).get("labels") or {}).items() if isinstance(zoo, dict) else []:
        for ch in (v or {}).get("changes") or [] if isinstance(v, dict) else []:
            if not isinstance(ch, dict) or not ch.get("day"):
                continue
            day, fr, to = str(ch["day"]), clean(ch.get("from"), 30), clean(ch.get("to"), 30)
            at = lablive.iso_ms(day + "T12:00:00Z") or c.now
            sections = [("Was passiert ist", f"Der Selektor des pump.fun-Zoos hat für das Label {label} am {day} "
                                             f"gewechselt: von {b(fr)} zu {b(to)}."),
                        ("Warum", clean(ch.get("why"), 300) or "-"),
                        ("Die Zahlen", f"- Bewertete Tage: {b(str(v.get('days') or 0))}\n- Mitglieder: "
                                       + ", ".join(str(x) for x in v.get("members") or [])),
                        ("Was es bedeutet", "Der Zoo wählt das Modell, das auf den letzten Tagen außerhalb des "
                                            "Rauschbands vorne lag. Der Live-Bot bleibt davon unberührt."),
                        ("Wie es weitergeht", NEXT["Modelle"])]
            out.append(article(f"zoo-{label}-{day}-{to}", at, "Modelle", f"pump.fun-Zoo: {label} wechselt zu {to}",
                               f"Für das Label {label} wählt der Zoo jetzt {to} statt {fr}.", sections,
                               tags=["zoo", "pumpfun", label], about=[f"model:zoo-{label}"],
                               source="reports/pumpfun_rt/zoo.json", importance=2,
                               key={"label": "Neue Wahl", "value": to}))
    al = notify.read_json(c.reports / "pumpfun_rt" / "allocator.json")
    if isinstance(al, dict) and al.get("choice"):
        ch = str(al["choice"])
        prev = c.state.get("alloc_choice")
        if prev != ch:
            arm = (al.get("arms") or {}).get(ch) or {}
            at = lablive.stamp(al) or c.now
            sections = [("Was passiert ist", (f"Der Allokator wählt jetzt {b(ch)}" + (f" statt {prev}." if prev else "."))),
                        ("Warum", clean(al.get("why"), 400)),
                        ("Die Zahlen", f"- P(beste Regel): {b(de_pct(100 * (_num(arm.get('p_best')) or 0), 0, sign=False))}\n"
                                       f"- Gewicht: {b(de_pct(100 * (_num(arm.get('weight')) or 0), 0, sign=False))}\n"
                                       f"- Tage: {de(arm.get('days'), 0)}"),
                        ("Was es bedeutet", f"Der Allokator rät nur. Der Live-Bot behält die Regel des Besitzers "
                                            f"({clean(al.get('live_rule'), 40) or '-'})."),
                        ("Wie es weitergeht", NEXT["Modelle"])]
            out.append(article(f"alloc-{day_of(at)}-{ch}", at, "Modelle", f"Allokator wählt {ch}",
                               f"Der Allokator hält {ch} für die wahrscheinlich beste pump.fun-Regel.", sections,
                               tags=["allokator", "pumpfun"], about=["model:allocator", "bot:pumpfun"],
                               source="reports/pumpfun_rt/allocator.json", importance=2,
                               key={"label": "P(beste)", "value": de_pct(100 * (_num(arm.get("p_best")) or 0), 0, sign=False)}))
        c.state["alloc_choice"] = ch
    mz = notify.read_json(c.reports / "models" / "latest.json")
    for m in (mz or {}).get("models") or [] if isinstance(mz, dict) else []:
        if not isinstance(m, dict) or not m.get("code"):
            continue
        for d in m.get("decisions") or []:
            if not isinstance(d, dict) or d.get("decision") not in ("promoted", "rejected") or not d.get("date"):
                continue
            code, dec, day = str(m["code"]), str(d["decision"]), str(d["date"])
            title = clean(m.get("title") or m.get("name"), 80)
            word = "befördert" if dec == "promoted" else "abgelehnt"
            at = lablive.iso_ms(day + "T08:00:00Z") or c.now
            sections = [("Was passiert ist", f"Der Modell-Zoo hat am {day} über {code} ({title}) entschieden: "
                                             f"der Herausforderer wurde {b(word)}."),
                        ("Die Zahlen", f"- Herausforderer: {b(de(d.get('challenger_score'), 4))}\n"
                                       f"- Champion: {b(de(d.get('champion_score'), 4))}\n"
                                       f"- Neue Zeilen: {de(d.get('window_rows'), 0)}"),
                        ("Warum", clean(d.get("why"), 400) or "-"),
                        ("Was es bedeutet", "Befördert wird nur, wer auf Daten besser ist, die der Champion nie gesehen "
                                            "hat. Sonst bleibt der Champion."),
                        ("Wie es weitergeht", NEXT["Modelle"])]
            out.append(article(f"model-{code}-{day}-{dec}", at, "Modelle", f"{code} {title}: Herausforderer {word}",
                               f"Im Modell-Zoo wurde der Herausforderer von {code} {word}.", sections,
                               tags=["zoo", code, dec], about=[f"model:{code}"], source="reports/models/latest.json",
                               importance=3 if dec == "promoted" else 1, key={"label": code, "value": word}))
    return out


def src_books(c: Ctx) -> list[dict]:
    fw = notify.read_json(c.reports / "forward" / "latest.json")
    if not isinstance(fw, dict):
        return []
    at = lablive.stamp(fw) or c.now
    day = day_of(at)
    first = "peaks" not in c.state
    peaks, alarms, bars = c.state.setdefault("peaks", {}), c.state.setdefault("dd_alarm", {}), c.state.setdefault("bar", {})
    out = []
    for bk in fw.get("books") or []:
        if not isinstance(bk, dict) or not bk.get("name"):
            continue
        name = str(bk["name"])
        label = clean(bk.get("label") or name, 80)
        ret, dd, days = _num(bk.get("return_pct")), _num(bk.get("max_dd_pct")), _num(bk.get("days"))
        exp = bk.get("expected") or {}
        g7 = bk.get("gate7") or {}
        about = [f"book:{name}"]
        numbers = (f"- Rendite: {b(de_pct(ret))} nach {de(days, 0)} Tagen\n- Größter Rückgang: {b(de_pct(dd, sign=False))}\n"
                   f"- Erwartet laut Backtest: {de_pct(exp.get('low_pct'))} bis {de_pct(exp.get('high_pct'))}, "
                   f"Rückgang bis {de_pct(exp.get('dd_p95_pct'), sign=False)}\n"
                   f"- Hürde: {de(g7.get('days'), 0)} von {de(g7.get('days_needed'), 0)} Tagen, "
                   f"{de(g7.get('trades'), 0)} von {de(g7.get('trades_needed'), 0)} Trades")
        said = clean(bk.get("sentence"), 300)
        if g7.get("ready") and not bars.get(name):
            out.append(article(f"book-{name}-bar", at, "Geld", f"{label} erreicht seine Hürde",
                               f"Das Paper-Buch {label} hat genug Tage und Trades für ein Urteil: {de_pct(ret)} bisher.",
                               [("Was passiert ist", f"Das Paper-Buch {label} ({name}) hat am {day} seine vorher "
                                                     "festgelegte Mindestzahl an Tagen und Trades erreicht."),
                                ("Die Zahlen", numbers), ("Was der Bericht sagt", said),
                                ("Was es bedeutet", "Jetzt darf das Buch beurteilt werden. Echtes Geld kommt nur mit "
                                                    "der Freigabe des Besitzers in Frage."),
                                ("Wie es weitergeht", NEXT["Geld"])],
                               tags=["buch", "huerde"], about=about, source="reports/forward/latest.json", importance=3,
                               key={"label": "Rendite", "value": de_pct(ret)}))
        bars[name] = bool(g7.get("ready")) or bool(bars.get(name))
        peak = _num(peaks.get(name))
        if ret is not None and not first and ret > 0 and (days or 0) >= 3 and (peak is None or ret > peak + 0.05):
            out.append(article(f"book-{name}-high-{day}", at, "Geld", f"{label}: neues Hoch bei {de_pct(ret)}",
                               f"Das Paper-Buch {label} steht so hoch wie nie: {de_pct(ret)} nach {de(days, 0)} Tagen.",
                               [("Was passiert ist", f"Das Paper-Buch {label} ({name}) hat am {day} ein neues Hoch "
                                                     f"erreicht; das alte lag bei {de_pct(peak)}."),
                                ("Die Zahlen", numbers), ("Was der Bericht sagt", said),
                                ("Was es bedeutet", "Ein Hoch nach wenigen Wochen beweist noch keinen Vorteil; es zählt "
                                                    "erst das Urteil nach der Hürde."),
                                ("Wie es weitergeht", NEXT["Geld"])],
                               tags=["buch", "hoch"], about=about, source="reports/forward/latest.json", importance=1,
                               key={"label": "Rendite", "value": de_pct(ret)}))
        if ret is not None:
            peaks[name] = max(ret, peak if peak is not None else ret)
        lim = _num(exp.get("dd_p95_pct"))
        alarm = dd is not None and lim is not None and dd > lim
        if alarm and not alarms.get(name):
            out.append(article(f"book-{name}-dd-{day}", at, "Warnung", f"{label}: Rückgang über dem Backtest",
                               f"Das Paper-Buch {label} ist {de_pct(dd, sign=False)} unter seinem Hoch, mehr als der "
                               f"Backtest in 95 von 100 Fällen erwarten ließ ({de_pct(lim, sign=False)}).",
                               [("Was passiert ist", f"Der größte Rückgang des Paper-Buchs {label} ({name}) liegt am "
                                                     f"{day} bei {b(de_pct(dd, sign=False))}, die Grenze des Backtests bei "
                                                     f"{b(de_pct(lim, sign=False))}."),
                                ("Die Zahlen", numbers), ("Was der Bericht sagt", said),
                                ("Was es bedeutet", "Das Buch läuft schlechter, als sein Backtest vermuten ließ. Das ist "
                                                    "kein Verlust an echtem Geld, aber ein Grund, die Regel zu prüfen."),
                                ("Wie es weitergeht", NEXT["Warnung"])],
                               tags=["buch", "rueckgang"], about=about, source="reports/forward/latest.json",
                               importance=2, key={"label": "Rückgang", "value": de_pct(dd, sign=False)}))
        alarms[name] = bool(alarm)
    return out


def src_money(c: Ctx) -> list[dict]:
    out = []
    live = c.state.setdefault("live", {})
    ls = notify.read_json(c.reports / "pumpfun_rt" / "live_status.json")
    if isinstance(ls, dict):
        on = bool(ls.get("running")) and bool(ls.get("on"))
        state = "an" if on else "aus"
        if live.get("pumpfun") != state:
            gate = "; ".join(clean(g, 120) for g in ls.get("gate") or [] if isinstance(g, str))
            nums = (f"- Guthaben: {b(de(ls.get('balance_sol'), 3, 'SOL'))}\n"
                    f"- Ergebnis seit dem Start: {b(de(ls.get('pnl_total_sol'), 3, 'SOL'))} aus {de(ls.get('trades_total'), 0)} Trades\n"
                    f"- Heute: {de(ls.get('pnl_today_sol'), 3, 'SOL')} aus {de(ls.get('trades_today'), 0)} Trades\n"
                    f"- Regel: {clean(ls.get('rule'), 40) or '-'}, Modus {clean(ls.get('mode'), 20) or '-'}")
            sections = [("Was passiert ist", "Der Echtgeld-Bot für pump.fun ist " + (
                "eingeschaltet und handelt." if on else "ausgeschaltet. Er kauft nichts mehr.") + (
                f" Stand des Bots: {gate}." if gate and not on else "")),
                        ("Die Zahlen", nums),
                        ("Was es bedeutet", "Solange der Bot aus ist, geht kein echtes Geld in neue Trades. "
                                            "Die Paper-Bücher laufen weiter." if not on else
                         "Der Bot handelt mit echtem Geld, innerhalb seiner festen Grenzen und mit Notaus."),
                        ("Wie es weitergeht", "Ein- und ausschalten kann ihn nur der Besitzer. Pythia News meldet "
                                              "die nächste Änderung.")]
            out.append(article(f"live-pumpfun-{state}-{day_of(c.now)}", c.now, "Geld",
                               "Echtgeld-Bot für pump.fun " + ("läuft" if on else "ist aus"),
                               "Der Echtgeld-Bot für pump.fun ist " + ("eingeschaltet." if on else "ausgeschaltet.")
                               + f" Ergebnis seit dem Start: {de(ls.get('pnl_total_sol'), 3, 'SOL')}.", sections,
                               tags=["echtgeld", "pumpfun"], about=["bot:pumpfun"],
                               source="reports/pumpfun_rt/live_status.json", importance=3,
                               key={"label": "Ergebnis gesamt", "value": de(ls.get("pnl_total_sol"), 3, "SOL")}))
            live["pumpfun"] = state
    os_ = notify.read_json(c.reports / "onchain_live" / "status.json")
    if isinstance(os_, dict):
        on = bool(os_.get("running") or os_.get("on"))
        state = "an" if on else "aus"
        if live.get("onchain") != state:
            sections = [("Was passiert ist", "Der Echtgeld-Händler der eigenen Wallet ist " + (
                "eingeschaltet." if on else "ausgeschaltet.")),
                        ("Was es bedeutet", "Ohne Freigabe des Besitzers handelt er nicht; seine Grenzen stehen im Code."),
                        ("Wie es weitergeht", NEXT["Geld"])]
            out.append(article(f"live-onchain-{state}-{day_of(c.now)}", c.now, "Geld",
                               "On-chain-Händler " + ("läuft" if on else "ist aus"),
                               "Der Echtgeld-Händler der eigenen Wallet ist " + ("eingeschaltet." if on else "ausgeschaltet."),
                               sections, tags=["echtgeld", "onchain"], about=["bot:onchain"],
                               source="reports/onchain_live/status.json", importance=3, key=None))
            live["onchain"] = state
    return out


def src_health(c: Ctx) -> list[dict]:
    out = []
    hj = notify.read_json(c.root / "_health" / "jobs.json")
    seen = c.state.setdefault("health", {})
    for j in (hj or {}).get("jobs") or [] if isinstance(hj, dict) else []:
        if not isinstance(j, dict) or not j.get("name"):
            continue
        name = str(j["name"])
        red = j.get("enabled", True) and j.get("state") == "failed"
        now_state = "rot" if red else "grün"
        prev = seen.get(name)
        seen[name] = now_state
        if prev == now_state or (prev is None and not red):
            continue
        last = j.get("last") if isinstance(j.get("last"), dict) else {}
        when = str(last.get("end") or last.get("start") or lablive.ms_iso(c.now))
        at = lablive.iso_ms(when) or c.now
        data = any(k in name for k in DATA_JOBS)
        detail = lablive.scrub(j.get("detail") or "")
        nums = (f"- Fehlschläge in Folge: {b(de(j.get('consecutiveFailures'), 0))}\n"
                f"- Letzter Lauf: {when.replace('T', ' ').replace('Z', ' UTC')}\n"
                f"- Nächster Lauf: {str(j.get('nextRun') or '-').replace('T', ' ').replace('Z', ' UTC')}")
        if red:
            out.append(article(f"health-{name}-rot-{when[:16]}", at, "Warnung", f"Job {name} ist rot",
                               f"Der Job {name} ist fehlgeschlagen: {clean(detail, 160) or 'ohne Angabe'}.",
                               [("Was passiert ist", f"Der Job {b(name)} ist bei seinem letzten Lauf fehlgeschlagen."),
                                ("Was der Job tut", clean(j.get("description"), 300)),
                                ("Die Meldung", f"`{clean(detail, 300)}`" if detail else "Keine Meldung."),
                                ("Die Zahlen", nums),
                                ("Was es bedeutet", "Was dieser Job liefert, ist bis zum nächsten guten Lauf nicht "
                                                    "frisch." + (" Den Modellen und Studien fehlen dann Daten." if data else "")),
                                ("Wie es weitergeht", NEXT["Warnung"])],
                               tags=["gesundheit", "rot", name], about=[f"job:{name}"], source="_health/jobs.json",
                               importance=2, key={"label": "Fehlschläge", "value": de(j.get("consecutiveFailures"), 0)}))
        else:
            out.append(article(f"health-{name}-gruen-{when[:16]}", at, "Daten" if data else "Betrieb",
                               f"Job {name} ist wieder grün", f"Der Job {name} läuft wieder.",
                               [("Was passiert ist", f"Der Job {b(name)} ist nach einem Fehler wieder sauber gelaufen."),
                                ("Was der Job tut", clean(j.get("description"), 300)), ("Die Zahlen", nums),
                                ("Wie es weitergeht", NEXT["Daten" if data else "Betrieb"])],
                               tags=["gesundheit", "gruen", name], about=[f"job:{name}"], source="_health/jobs.json",
                               importance=1, key=None))
    st = notify.read_json(c.root / "_health" / "status.json")
    streams = st.get("streams") if isinstance(st, dict) and isinstance(st.get("streams"), dict) else {}
    ss = c.state.setdefault("streams", {})
    for k, v in streams.items():
        stale = bool(isinstance(v, dict) and v.get("stale"))
        prev = ss.get(k)
        ss[k] = stale
        if prev is None and not stale or prev == stale:
            continue
        at = lablive.iso_ms(st.get("at")) or c.now
        out.append(article(f"stream-{k}-{'alt' if stale else 'frisch'}-{lablive.ms_iso(at)[:13]}", at,
                           "Daten" if not stale else "Warnung",
                           f"Datenstrom {k} " + ("steht" if stale else "läuft wieder"),
                           f"Der Rekorder bekommt von {k} " + ("keine frischen Daten." if stale else "wieder Daten."),
                           [("Was passiert ist", f"Der Datenstrom {b(k)} des Rekorders ist " + (
                               "veraltet." if stale else "wieder frisch.")),
                            ("Die Zahlen", f"- Nachrichten bisher: {b(de(v.get('messages'), 0))}\n"
                                           f"- Neuverbindungen: {de(v.get('reconnects'), 0)}"),
                            ("Wie es weitergeht", NEXT["Daten"])],
                           tags=["rekorder", k], about=["src:recorder"], source="_health/status.json",
                           importance=2 if stale else 1, key=None))
    return out


def src_briefing(c: Ctx) -> list[dict]:
    d = notify.read_json(c.reports / "notify" / "latest.json")
    if not isinstance(d, dict) or not d.get("text") or not _num(d.get("ts")):
        return []
    at = int(d["ts"])
    lines = [lablive.scrub(ln) for ln in str(d["text"]).splitlines() if ln.strip()]
    top = clean(lines[1] if len(lines) > 1 else lines[0], 200)
    sections = [("Was passiert ist", f"Das Morgenbriefing vom {de_day(at)} ist " + (
        "an Telegram und Discord gegangen." if d.get("delivered") else "geschrieben worden.")),
                ("Das Briefing im Wortlaut", "\n".join(f"- {clean(ln, 300)}" for ln in lines[:40])),
                ("Wie es weitergeht", NEXT["Betrieb"])]
    return [article(f"briefing-{day_of(at)}", at, "Betrieb", f"Morgenbriefing vom {de_day(at)}", top, sections,
                    tags=["briefing"], about=mentions(" ".join(lines), c.known) + ["job:briefing"],
                    source="reports/notify/latest.json", importance=1, key=None)]


SOURCES = (("lanes", src_lanes), ("studies", src_studies), ("factories", src_factories), ("models", src_models),
           ("books", src_books), ("money", src_money), ("health", src_health), ("briefing", src_briefing))


# ---------------------------------------------------------------- merge and run

def merge(old: list[dict], new: list[dict], now: int) -> tuple[list[dict], list[dict]]:
    """Old and new by id: a new id is added, the same id with other content is edited and marked updated (its time
    stays). Returns (all articles newest first, at most MAX_ARTICLES; those that are new or changed)."""
    by = {a["id"]: a for a in old if isinstance(a, dict) and a.get("id")}
    touched = []
    for a in new:
        o = by.get(a["id"])
        if o is None:
            a = {**a, "updated": False, "updated_ms": None}
        elif o.get("hash") == a["hash"]:
            continue
        else:
            a = {**a, "time_ms": o.get("time_ms", a["time_ms"]), "time": o.get("time", a["time"]),
                 "updated": True, "updated_ms": now}
        by[a["id"]] = a
        touched.append(a)
    arts = sorted(by.values(), key=lambda x: (-(x.get("time_ms") or 0), x["id"]))[:MAX_ARTICLES]
    keep = {a["id"] for a in arts}
    return arts, [a for a in touched if a["id"] in keep]


def polish(touched: list[dict], summarize) -> None:
    """The local model may reword the teaser of the most important new articles; lab.ai.local keeps the template
    when the answer is late, empty or has a number that is not in the facts."""
    for a in sorted(touched, key=lambda x: -x["importance"])[:POLISH_MAX]:
        if a["importance"] < 2:
            continue
        facts = [a["headline"], a["teaser"]] + [ln.strip("- ").replace("**", "") for ln in a["body"].splitlines()
                                                if ln.startswith("- ")][:8]
        try:
            text = summarize(facts, a["teaser"], "de")
        except Exception:  # noqa: BLE001 - the template stays
            continue
        if isinstance(text, str) and text.strip() and "\u2014" not in text:
            a["teaser"] = clean(text, 320)


def news_dir() -> Path:
    return notify.reports_root() / "news"


def results_dir() -> Path:
    import os
    return Path(os.environ.get("PYTHIA_RESULTS") or (Path(__file__).resolve().parents[2] / "results"))


def run(root: Path | None = None, reports: Path | None = None, results: Path | None = None, now: int | None = None,
        summarize=None, write: bool = True) -> dict:
    given = root
    reports = reports or (notify.reports_root() if root is None else root / "reports")
    root = root or notify.data_root()
    results = results or results_dir()
    now = now or notify.clock_ms()
    out_dir = reports / "news"
    state = notify.read_json(out_dir / "state.json") or {}
    old = notify.read_json(out_dir / "articles.json") or {}
    try:
        known = lablive.aliases(lablive.build(given, now))
    except Exception:  # noqa: BLE001 - articles without links then
        known = {}
    c = Ctx(root, reports, results, now, state, known)
    new: list[dict] = []
    for name, fn in SOURCES:
        try:
            new += fn(c)
        except Exception as e:  # noqa: BLE001 - one broken source never holds back the others
            notify.say(f"news: source {name} failed ({type(e).__name__}: {e})", err=True)
    arts, touched = merge(old.get("articles") or [] if isinstance(old, dict) else [], new, now)
    if summarize is not None and touched:
        polish(touched, summarize)
    doc = {"updated_ms": now, "generated": lablive.ms_iso(now), "count": len(arts), "categories": list(CATEGORIES),
           "articles": arts}
    if write:
        notify.write_json(out_dir / "articles.json", doc)
        notify.write_json(out_dir / "state.json", {**state, "at": now})
    return {"doc": doc, "touched": touched}


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    summarize = None
    if "--no-llm" not in argv and "--print" not in argv:
        from ..ai import local
        summarize = local.summarizer(LLM_BUDGET_SEC, "news-articles", sentences=2)
    res = run(summarize=summarize, write="--print" not in argv)
    if "--print" in argv:
        for a in res["touched"]:
            notify.say(f"[{a['category']}] {a['headline']} ({a['id']}, {words(a['body'])} Wörter)")
        return 0
    notify.say(f"news: {res['doc']['count']} articles, {len(res['touched'])} new or changed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
