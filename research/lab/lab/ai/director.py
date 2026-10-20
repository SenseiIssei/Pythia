"""The research director: once a week one deep Claude call (Opus 5.5, adaptive
thinking at effort high, through the Batches API at half price) reads the
summary of every study write-up (results/*.md), the trial ledger (how many
trials the lab has counted and the noise bar they set), the forward evidence,
the autopilots, the lab's reports, the AI brief's and the strategy critic's
scores, the Sonnet weekly review and the drafts already written, and writes
three to five concrete pre-registration drafts for new studies:

  research/lab/proposals/<date>-<slug>.md   question, why now, data, design,
                                            trials, costs, pass rule, kill
                                            rule, effort, what could fool us
  reports/ai/director.json                  the index (and a copy of every
                                            draft under reports/ai/proposals/)

and one Telegram card listing them (category "studies").

Drafts only. Nothing reads them to run anything: the owner, or a later run
the owner starts, picks one up, fixes its numbers before any result exists
and moves it into results/ as the study's pre-registration.

  python -m lab.ai.director             Sundays (jobs.yaml: ai-director)
  python -m lab.ai.director --dry-run   print the prompt and its size, call nothing
  python -m lab.ai.director --force     again this week (a second call)

PYTHIA_AI_MODEL_DIRECTOR and PYTHIA_AI_EFFORT_DIRECTOR change the model and
the effort; PYTHIA_PROPOSALS the folder the drafts go to.
"""

from __future__ import annotations

import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from ..ops import i18n, notify
from . import engine, facts, score, weekly

DEFAULT_MODEL = engine.DEEP
DEFAULT_EFFORT = "high"
MAX_TOKENS = 32000
BATCH_WAIT_SEC = 55 * 60
STUDY_CHARS = 6000
TOP_TRIALS = 15
MIN_DRAFTS, MAX_DRAFTS = 3, 5
WHERE = "research/lab/proposals"
# Headings whose section is the study's summary, whatever else the write-up holds.
SUMMARY_HEADS = re.compile(r"summary|verdict|result|conclusion|bottom line|what we learned|answer|findings|decision",
                           re.IGNORECASE)

SYSTEM = """You are the research director of Pythia, a paper-first trading research lab run by one person. \
Once a week you read everything the lab has found and write three to five pre-registration drafts for the \
next studies. A draft is what the owner would commit before running a study: precise enough that someone \
else could run it and nobody could move the goalposts afterwards.

What you get: the summary of every study write-up (title, opening and the summary or verdict sections), the \
trial ledger (how many trials the lab has counted, the noise bar that sets for the best of them, the factory's \
best in-sample genomes and its held-back checks), the forward evidence of the paper books and autopilots \
against their backtests, every autopilot with its rules and record, the headlines of the lab's reports, how \
the daily AI brief's 7-day calls and the strategy critic's findings score, the weekly review written by \
another model, and the drafts already written in earlier weeks. That is all you know. Do not invent results, \
numbers, data sources, papers or code that are not in the material; when a draft needs something the \
material does not show exists, say so in its data section.

How this lab works, and what every draft must respect:
- Paper first. Nothing goes near real money until it has passed its gates out of sample and lived in shadow.
- Every test is walk-forward or on held-back data, at realistic costs (the bps the studies use: 35 bps per unit \
of one-way turnover on Alpaca crypto, 15 and 70 reported), with a weight decided at the close of day t earning \
day t+1.
- Every Sharpe trial counts toward the lab's pool and raises the deflation bar for everything after it. Count \
the trials of each draft exactly (the variants times the parameters times the books), keep the count small, \
and state the deflated p the winner must reach against the pool.
- Pass and kill rules are numbers fixed in advance, never "looks promising".
- Prefer what the existing data and code can test within a day of compute over anything that needs new paid \
data or a new venue. Name the existing module or data set the study would use when the material names it.
- Do not repeat what a study already settled unless the material shows a reason to revisit it, and say what \
changed. Do not repeat an earlier draft unless it was not started and is still the best; then say so.
- A cheap, clear failure is a good outcome. Rank the drafts by expected value for the effort.

For each draft fill every field of the schema: slug (lower case words joined by dashes, at most 6 words), \
title, question (one sentence that can be answered yes or no), whyNow (the facts from the material that point \
here, naming the studies or reports), builtOn (the study file stems it builds on), data (sources, period, \
universe, what exists and what is missing), design (split, signal, rules, the comparison it must beat), trials \
(one line per trial family with its count), trialCount (the total), costs, passRule, killRule, effort (compute \
and the owner's time), couldFoolUs (the most likely way a pass would be wrong), and line (one plain sentence for \
the owner's phone, at most 25 words). Then stopDoing: one short paragraph on what the lab should stop doing or \
stop watching, or an empty string. Plain words, no hype, no em dashes. These are drafts for the owner to \
decide on; nothing runs them."""

PROPOSAL = {
    "type": "object",
    "properties": {
        "slug": {"type": "string"}, "title": {"type": "string"}, "question": {"type": "string"},
        "whyNow": {"type": "string"}, "builtOn": {"type": "array", "items": {"type": "string"}},
        "data": {"type": "string"}, "design": {"type": "string"},
        "trials": {"type": "array", "items": {"type": "string"}}, "trialCount": {"type": "integer"},
        "costs": {"type": "string"}, "passRule": {"type": "string"}, "killRule": {"type": "string"},
        "effort": {"type": "string"}, "couldFoolUs": {"type": "string"}, "line": {"type": "string"},
    },
    "required": ["slug", "title", "question", "whyNow", "builtOn", "data", "design", "trials", "trialCount",
                 "costs", "passRule", "killRule", "effort", "couldFoolUs", "line"],
    "additionalProperties": False,
}
SCHEMA = {
    "type": "object",
    "properties": {"proposals": {"type": "array", "items": PROPOSAL}, "stopDoing": {"type": "string"}},
    "required": ["proposals", "stopDoing"],
    "additionalProperties": False,
}
SCHEMA_DE = {
    **SCHEMA,
    "properties": {**SCHEMA["properties"],
                   "linesDe": {"type": "array", "items": {"type": "string"}}, "stopDoingDe": {"type": "string"}},
    "required": ["proposals", "stopDoing", "linesDe", "stopDoingDe"],
}
GERMAN = ("\n\nThe owner reads the phone card in German: also give linesDe (each draft's line in plain German, "
          "in the same order) and stopDoingDe (stopDoing in German). Everything else stays in English.")
FIELDS = [("Question", "question"), ("Why now", "whyNow"), ("Data", "data"), ("Design", "design"),
          ("Costs", "costs"), ("Pass rule", "passRule"), ("Kill rule", "killRule"), ("Effort", "effort"),
          ("What could fool us", "couldFoolUs")]


def lab_root() -> Path:
    return Path(__file__).resolve().parents[2]


def proposals_dir() -> Path:
    return Path(os.environ.get("PYTHIA_PROPOSALS") or (lab_root() / "proposals"))


def ai_reports() -> Path:
    return notify.reports_root() / "ai"


def today(now_ms: int) -> str:
    return datetime.fromtimestamp(now_ms / 1000, timezone.utc).strftime("%Y-%m-%d")


# ---------------------------------------------------------------- what it reads

def study_summary(text: str, chars: int = STUDY_CHARS) -> tuple[str, str]:
    """(title, summary) of one write-up: the opening before the first section,
    then every section whose heading says summary, verdict, result and the
    like, then the rest of the opening sections, up to `chars`."""
    lines = text.splitlines()
    title = next((ln.lstrip("# ").strip() for ln in lines if ln.startswith("#")), "")
    sections: list[tuple[str, list[str]]] = [("", [])]
    for ln in lines:
        if re.match(r"^#{2,4}\s", ln):
            sections.append((ln.lstrip("# ").strip(), []))
        elif not re.match(r"^#\s", ln):
            sections[-1][1].append(ln)

    def body(rows: list[str]) -> str:
        return re.sub(r"\s+", " ", " ".join(r.strip() for r in rows if r.strip())).strip()

    picked = [body(sections[0][1])] if len(sections) else []
    picked += [f"[{h}] {body(b)}" for h, b in sections[1:] if SUMMARY_HEADS.search(h) and body(b)]
    picked += [f"[{h}] {body(b)}" for h, b in sections[1:] if not SUMMARY_HEADS.search(h) and body(b)]
    out = notify.nodash(" ".join(p for p in picked if p))
    return notify.nodash(title), out if len(out) <= chars else out[: chars - 1].rstrip() + "…"


def study_lines(results: Path | None = None, chars: int = STUDY_CHARS) -> list[str]:
    """Every write-up in results/, most recently changed first."""
    d = results or (lab_root() / "results")
    if not d.is_dir():
        return []
    out = []
    for p in sorted(d.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            title, summary = study_summary(p.read_text(encoding="utf-8", errors="replace"), chars)
        except OSError:
            continue
        out.append(f"[{p.stem}] {title or p.stem}: {summary}")
    return out


def _jsonl(p: Path) -> list[dict]:
    import json
    try:
        text = p.read_text(encoding="utf-8")
    except OSError:
        return []
    rows = []
    for line in text.splitlines():
        try:
            v = json.loads(line)
        except ValueError:
            continue
        if isinstance(v, dict):
            rows.append(v)
    return rows


def trial_lines(factory: Path | None = None, top: int = TOP_TRIALS) -> list[str]:
    """The trial ledger: the pool and its bar, the factory's best in-sample
    genomes and its held-back checks. The server's ledger when there is one,
    else the committed seed."""
    base = factory or Path(os.environ.get("PYTHIA_FACTORY_DIR", str(notify.data_root() / "factory")))
    if not (base / "ledger.jsonl").exists():
        base = lab_root() / "results" / "factory_seed"
    rows = _jsonl(base / "ledger.jsonl")
    out = []
    try:
        from ..factory import ledger as fl
        pool = fl.Ledger(base / "ledger.jsonl").pool()
        out.append(f"pool: {pool['prior_trials']} hand-study trials counted before the factory (bar at their "
                   f"publication) + {pool['factory_trials']} factory genomes = {pool['n_trials']} trials; the best "
                   f"of that many noise trials is expected at an annual Sharpe of {pool['sr0_annual']:.2f}. Studies "
                   f"since then count their own trials into the pool (see each write-up).")
    except Exception:  # noqa: BLE001 - no numpy/scipy here: the count alone
        out.append(f"factory ledger: {len(rows)} genomes (the hand studies' own trial counts are in their write-ups)")
    best = sorted((r for r in rows if isinstance(r.get("is_sharpe"), (int, float))),
                  key=lambda r: -r["is_sharpe"])[:top]
    for r in best:
        h = (f", halves {r['is_h1']:.2f} / {r['is_h2']:.2f}"
             if isinstance(r.get("is_h1"), (int, float)) and isinstance(r.get("is_h2"), (int, float)) else "")
        out.append(f"genome {r.get('key')} (run {r.get('run')}): {notify.nodash(str(r.get('name') or '?'))}; "
                   f"in-sample Sharpe {r['is_sharpe']:.2f}{h}")
    for h in _jsonl(base / "holdout.jsonl")[-10:]:
        def f(k: str, fmt: str = ".2f") -> str:
            v = h.get(k)
            return format(v, fmt) if isinstance(v, (int, float)) else "n/a"
        out.append(f"held-back check {h.get('key')} (run {h.get('run')}): {notify.nodash(str(h.get('name') or '?'))}; "
                   f"out-of-sample Sharpe {f('oos_sharpe_35bps')} at 35 bps, {f('oos_sharpe_70bps')} at 70 bps, "
                   f"deflated p {f('deflated_p', '.4f')} over {h.get('pool_trials')} trials; "
                   f"{h.get('decision')}: {notify.nodash(str(h.get('why') or ''))}")
    return out


def critic_line() -> str | None:
    s = notify.read_json(ai_reports() / "critic_score.json")
    return s.get("verdict") if isinstance(s, dict) else None


def draft_lines(root: Path | None = None) -> list[str]:
    d = root or proposals_dir()
    if not d.is_dir():
        return []
    out = []
    for p in sorted(d.glob("*.md"))[-30:]:
        try:
            first = next((ln.lstrip("# ").strip() for ln in p.read_text(encoding="utf-8").splitlines()
                          if ln.startswith("#")), p.stem)
        except OSError:
            continue
        out.append(f"{p.stem}: {notify.nodash(first)}")
    return out


def build_prompt(now_ms: int, state: dict | None, results: Path | None = None, factory: Path | None = None,
                 drafts: Path | None = None) -> str:
    parts = [f"DATE: {today(now_ms)} (UTC)", "", "STUDIES (newest first):"]
    parts += ["- " + s for s in study_lines(results)] or ["- none"]
    parts += ["", "TRIAL LEDGER:"] + ["- " + t for t in trial_lines(factory)]
    ev = weekly.evidence_lines()
    if ev:
        parts += ["", "FORWARD EVIDENCE (paper books and autopilots against their backtests):"] + ["- " + e for e in ev]
    aps = facts.autopilot_details(state, now_ms)
    parts += ["", "AUTOPILOTS:"] + (["- " + a for a in aps] if aps else ["- none running"])
    parts += ["", "LAB REPORTS (headlines):"] + ["- " + f for f in facts.feed_lines(weekly.all_feed_names(), items=4)]
    for title, line in (("AI BRIEF SCORE (7-day calls, shadow)", weekly.brief_score_line()),
                        ("STRATEGY CRITIC SCORE", critic_line())):
        if line:
            parts += ["", f"{title}:", "- " + line]
    wk = weekly.ai_reports() / "weekly.md"
    if wk.exists():
        try:
            parts += ["", "THIS WEEK'S REVIEW BY ANOTHER MODEL (a second opinion, not a source of facts):",
                      notify.short(wk.read_text(encoding="utf-8"), 6000)]
        except OSError:
            pass
    dl = draft_lines(drafts)
    parts += ["", "DRAFTS ALREADY WRITTEN (file: title):"] + (["- " + d for d in dl] if dl else ["- none yet"])
    parts += ["", f"Write {MIN_DRAFTS} to {MAX_DRAFTS} drafts."]
    return "\n".join(parts)


# ---------------------------------------------------------------- what it writes

def slugify(s: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", str(s or "").lower()).strip("-")
    return "-".join(s.split("-")[:8])[:60].strip("-") or "study"


def _clean(s, n: int = 4000) -> str:
    s = notify.nodash(str(s or "").strip())
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def parse_answer(obj, taken: set[str] | None = None) -> tuple[list[dict], str, list[str]]:
    """The drafts, checked: (drafts, stopDoing, problems). A draft without a
    question or a pass rule is dropped; slugs are made safe and unique."""
    problems: list[str] = []
    if not isinstance(obj, dict) or not isinstance(obj.get("proposals"), list):
        return [], "", ["no proposals list"]
    seen = set(taken or ())
    out = []
    for i, p in enumerate(obj["proposals"]):
        if not isinstance(p, dict):
            problems.append(f"draft {i + 1} is not an object")
            continue
        if not str(p.get("question") or "").strip() or not str(p.get("passRule") or "").strip():
            problems.append(f"draft {i + 1} has no question or no pass rule: dropped")
            continue
        slug = base = slugify(p.get("slug") or p.get("title"))
        k = 2
        while slug in seen:
            slug, k = f"{base}-{k}", k + 1
        seen.add(slug)
        d = {key: _clean(p.get(key)) for _, key in FIELDS}
        try:
            n = int(p.get("trialCount"))
        except (TypeError, ValueError):
            n = None
            problems.append(f"{slug}: no trial count")
        d.update(slug=slug, title=_clean(p.get("title"), 160) or slug, line=_clean(p.get("line"), 240),
                 trials=[_clean(t, 400) for t in p.get("trials") or [] if str(t).strip()][:20],
                 builtOn=[_clean(t, 80) for t in p.get("builtOn") or [] if str(t).strip()][:12], trialCount=n)
        out.append(d)
    if len(out) > MAX_DRAFTS:
        problems.append(f"{len(out)} drafts, the first {MAX_DRAFTS} kept")
        out = out[:MAX_DRAFTS]
    if len(out) < MIN_DRAFTS:
        problems.append(f"{len(out)} drafts instead of {MIN_DRAFTS} to {MAX_DRAFTS}")
    return out, _clean(obj.get("stopDoing"), 1500), problems


def markdown(d: dict, day: str, model: str) -> str:
    out = [f"# {d['title']}: pre-registration draft ({day})", "",
           f"*Draft by the research director ({model}, {day}). Nothing runs it. To start it, the owner fixes every "
           f"number below before any result exists, commits it as the study's pre-registration in `results/` and "
           f"counts its trials into the pool.*", ""]
    for head, key in FIELDS[:4]:
        out += [f"## {head}", "", d[key] or "(not given)", ""]
    n = d.get("trialCount")
    out += [f"## Trials ({n if n is not None else '?'})", ""] + [f"- {t}" for t in d["trials"] or ["(not given)"]] + [""]
    for head, key in FIELDS[4:]:
        out += [f"## {head}", "", d[key] or "(not given)", ""]
    if d["builtOn"]:
        out += ["## Built on", "", ", ".join(f"`{b}`" for b in d["builtOn"]), ""]
    return "\n".join(out)


def write(now_ms: int, drafts: list[dict], stop: str, answer: dict, problems: list[str],
          lines_de: list[str] | None = None, stop_de: str = "", root: Path | None = None) -> list[Path]:
    day = today(now_ms)
    model = answer.get("servedBy") or answer.get("model") or DEFAULT_MODEL
    d = root or proposals_dir()
    copies = ai_reports() / "proposals"
    paths = []
    for i, p in enumerate(drafts):
        md = markdown(p, day, model)
        name = f"{day}-{p['slug']}.md"
        for folder in (d, copies):
            try:
                folder.mkdir(parents=True, exist_ok=True)
                tmp = folder / (name + ".tmp")
                tmp.write_text(md, encoding="utf-8")
                tmp.replace(folder / name)
            except OSError as e:
                notify.say(f"draft {name} not written to {folder}: {e}", err=True)
        paths.append(d / name)
        p["file"] = name
        if lines_de and i < len(lines_de):
            p["lineDe"] = _clean(lines_de[i], 240)
    notify.write_json(ai_reports() / "director.json", {
        "week": weekly.week_key(now_ms), "date": day, "generated_ms": now_ms, "model": model,
        "costUsd": float(answer.get("costUsd") or 0.0), "batch": bool(answer.get("batchId")),
        "proposals": [{k: p.get(k) for k in ("slug", "title", "question", "line", "lineDe", "file", "trialCount",
                                             "passRule")} for p in drafts],
        "stopDoing": stop, "stopDoingDe": stop_de, "problems": problems,
        "note": "Drafts only: nothing runs them; the owner decides.",
    })
    return paths


def card(drafts: list[dict], stop: str, cost: float, lang: str, stop_de: str = "") -> notify.Card:
    parts: list = []
    for i, p in enumerate(drafts, 1):
        text = (p.get("lineDe") if lang == "de" else None) or p.get("line") or p["title"]
        parts.append(notify.Line(text, f"{i}."))
    s = (stop_de if lang == "de" else "") or stop
    if s:
        parts.append(notify.Line(notify.short(s, 400), i18n.t("dir_stop", lang)))
    return notify.Card("🧭", i18n.t("dir_title", lang, n=len(drafts)),
                       i18n.t("dir_summary", lang, where=WHERE, cost=i18n.money(cost, 2, lang)), parts)


def run(now_ms: int | None = None, dry_run: bool = False, force: bool = False, state: dict | None = None,
        results: Path | None = None, factory: Path | None = None, drafts_dir: Path | None = None, poster=None,
        send_poster=None) -> int:
    now = now_ms or notify.clock_ms()
    last = notify.read_json(ai_reports() / "director.json") or {}
    if last.get("week") == weekly.week_key(now) and not force and not dry_run:
        notify.say(f"the drafts for {weekly.week_key(now)} exist; nothing called (--force for another)")
        return 0
    if state is None:
        state = notify.engine_state()
    lang = notify.alert_lang()
    prompt = build_prompt(now, state, results, factory, drafts_dir)
    if lang == "de":
        prompt += GERMAN
    model, effort = engine.model_for("director", DEFAULT_MODEL), engine.effort_for("director", DEFAULT_EFFORT)
    if dry_run:
        notify.say(SYSTEM + "\n\n" + prompt)
        notify.say(f"\n[dry run] about {(len(SYSTEM) + len(prompt)) // 4:,} input tokens, at most {MAX_TOKENS} out, "
                   f"{model} at effort {effort}; nothing called")
        return 0
    try:
        answer = engine.complete("director", SYSTEM, prompt, MAX_TOKENS, model=model, effort=effort,
                                 schema=SCHEMA_DE if lang == "de" else SCHEMA, batch=True,
                                 batch_wait_sec=BATCH_WAIT_SEC, poster=poster)
    except engine.AiError as e:
        notify.say(f"no drafts this week: {e}", err=e.kind not in ("budget", "nokey"))
        return 0 if e.kind in ("budget", "nokey") else 1
    d = drafts_dir or proposals_dir()
    taken = {p.stem.split("-", 3)[-1] for p in d.glob(f"{today(now)}-*.md")} if d.is_dir() else set()
    drafts, stop, problems = parse_answer(answer.get("json"), taken)
    for p in problems:
        notify.say(f"director: {p}", err=True)
    if not drafts:
        notify.say("the director's answer held no usable draft", err=True)
        return 1
    obj = answer.get("json") or {}
    lines_de = [str(x) for x in obj.get("linesDe") or []] if lang == "de" else []
    stop_de = _clean(obj.get("stopDoingDe"), 1500) if lang == "de" else ""
    paths = write(now, drafts, stop, answer, problems, lines_de, stop_de, root=d)
    cost = float(answer.get("costUsd") or 0.0)
    notify.say(f"{len(paths)} drafts written to {d} (${cost:.3f})")
    notify.send("studies", card(drafts, stop, cost, lang, stop_de), now=now, poster=send_poster)
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(argv or [])
    return run(dry_run="--dry-run" in argv, force="--force" in argv)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
