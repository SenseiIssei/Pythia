"""The weekly review: one deeper Claude call (Sonnet, through the Batches API
at half price) over every study write-up, the lab's reports, the forward
evidence, the autopilots and the AI brief's own score, proposing the three
most promising next experiments.

Written to reports/ai/weekly.md (and a dated copy). Proposals only: nothing
reads this file to run anything; an experiment starts when the owner starts
it.

  python -m lab.ai.weekly             Sundays (jobs.yaml: ai-weekly)
  python -m lab.ai.weekly --dry-run   print the prompt and its size, call nothing
  python -m lab.ai.weekly --force     again this week (a second call)
"""

from __future__ import annotations

import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from ..ops import notify
from . import engine, facts, score

MAX_TOKENS = 8000
BATCH_WAIT_SEC = 50 * 60
STUDY_CHARS = 420
MAX_STUDIES = 40

SYSTEM = """You are the research director of Pythia, a paper-first trading research system run by one person. \
Once a week you read everything the lab has found and propose the three most promising next experiments.

What you get: a short excerpt of every study write-up (most recent first), the headlines of the lab's daily \
reports, the forward evidence (paper books and autopilots against their backtests), the running autopilots, \
how the daily AI brief's 7-day calls score against a base rate and a momentum rule, and last week's proposals. \
That is all you know. Do not invent results, numbers, data sources or papers that are not in the material.

How this lab works, and what a good proposal respects:
- Paper first. Nothing goes near real money until it has passed its gate out of sample and lived in shadow.
- Every test is walk-forward or on held-back data, with realistic costs (fees and slippage in basis points \
as the studies use them) and a correction for how many variants were tried. Most ideas fail; a clear, \
cheap failure is a good result.
- The pass or fail criterion is fixed before the run, in numbers.
- Prefer what the existing data and code can test within a day of compute over anything that needs new paid \
data or a new venue.
- Do not propose what a study already settled unless the material shows a reason to revisit it, and say \
what changed. Do not repeat last week's proposals unless one was not started and is still the best.

Write markdown. For each of the three, ranked by expected value for the effort:
## 1. <short title>
- Why now: the facts from the material that point here (name the study or report).
- Hypothesis: one sentence that can be false.
- Test: data, period, split, costs, the comparison it must beat.
- Pass if: the numbers decided in advance.
- Effort: compute and the owner's time, roughly.
- What could fool us: the most likely way a pass would be wrong.

After the three, one short paragraph: what the lab should stop doing or stop watching, if anything. \
Plain words, no hype, no em dashes. These are proposals for the owner to decide on; nothing runs them."""


def lab_root() -> Path:
    return Path(__file__).resolve().parents[2]


def ai_reports() -> Path:
    return notify.reports_root() / "ai"


def week_key(now_ms: int) -> str:
    d = datetime.fromtimestamp(now_ms / 1000, timezone.utc).isocalendar()
    return f"{d[0]}-W{d[1]:02d}"


def study_lines(results: Path | None = None, limit: int = MAX_STUDIES, chars: int = STUDY_CHARS) -> list[str]:
    """Title and the opening of each study write-up, most recently changed first."""
    d = results or (lab_root() / "results")
    files = sorted(d.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit] if d.is_dir() else []
    out = []
    for p in files:
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        lines = [ln.strip() for ln in text.splitlines()]
        title = next((ln.lstrip("# ").strip() for ln in lines if ln.startswith("#")), p.stem)
        body = " ".join(ln for ln in lines if ln and not ln.startswith("#") and not ln.startswith("|"))
        body = re.sub(r"\s+", " ", notify.nodash(body))
        out.append(f"[{p.stem}] {notify.nodash(title)}: {notify.short(body, chars)}")
    return out


def all_feed_names(root: Path | None = None) -> list[str]:
    rep = root or notify.reports_root()
    if not rep.is_dir():
        return []
    return sorted(p.parent.name for p in rep.glob("*/latest.json") if p.parent.name not in ("notify", "ai_brief"))


def evidence_lines(root: Path | None = None) -> list[str]:
    ev = notify.read_json((root or notify.reports_root()) / "learn" / "evidence.json") or {}
    out = []
    for k, v in sorted((ev.get("strategies") or {}).items())[:30]:
        if not isinstance(v, dict):
            continue
        ret, days = v.get("return_pct"), v.get("days")
        bits = [f"{k}: {v.get('status')}"]
        if isinstance(ret, (int, float)):
            bits.append(f"{ret:+.1f} %")
        if isinstance(days, (int, float)):
            bits.append(f"after {days:.0f} days")
        if v.get("since"):
            bits.append(f"since {v.get('since')}")
        out.append(" ".join(bits))
    return out


def brief_score_line() -> str | None:
    s = notify.read_json(score.scores_path())
    if not isinstance(s, dict):
        return None
    src = s.get("sources") or {}
    b = {k: (src.get(k) or {}).get("brier") for k in score.SOURCES}
    if b["llm"] is None:
        return s.get("verdict")
    return (f"{s.get('verdict')} Brier: LLM {b['llm']:.4f}, base rate {b['base']:.4f}, "
            f"momentum {b['momentum']:.4f} ({s.get('resolved')} resolved).")


def build_prompt(now_ms: int, state: dict | None, results: Path | None = None) -> str:
    day = datetime.fromtimestamp(now_ms / 1000, timezone.utc).strftime("%Y-%m-%d")
    parts = [f"DATE: {day} (UTC)", "", "STUDIES (newest first):"]
    parts += ["- " + s for s in study_lines(results)] or ["- none"]
    parts += ["", "LAB REPORTS (headlines):"] + ["- " + f for f in facts.feed_lines(all_feed_names(), items=4)]
    ev = evidence_lines()
    if ev:
        parts += ["", "FORWARD EVIDENCE (paper books and autopilots against their backtests):"] + ["- " + e for e in ev]
    aps = facts.autopilot_lines(state)
    parts += ["", "AUTOPILOTS (running):"] + (["- " + a for a in aps] if aps else ["- none running"])
    sl = brief_score_line()
    if sl:
        parts += ["", "AI BRIEF SCORE (7-day calls, shadow):", "- " + sl]
    prev = ai_reports() / "weekly.md"
    if prev.exists():
        try:
            parts += ["", "LAST WEEK'S PROPOSALS:", notify.short(prev.read_text(encoding="utf-8"), 2500)]
        except OSError:
            pass
    return "\n".join(parts)


def write(now_ms: int, answer: dict) -> Path:
    day = datetime.fromtimestamp(now_ms / 1000, timezone.utc).strftime("%Y-%m-%d")
    cost = float(answer.get("costUsd") or 0.0)
    head = (f"# Weekly AI review, {day}\n\n"
            f"*{answer.get('servedBy') or answer.get('model')}, ${cost:.3f}"
            f"{', batch' if answer.get('batchId') else ''}. Proposals only: nothing runs them; "
            f"the owner decides.*\n\n")
    md = head + notify.nodash(str(answer.get("text") or "").strip()) + "\n"
    d = ai_reports()
    d.mkdir(parents=True, exist_ok=True)
    for name in ("weekly.md", f"weekly-{day}.md"):
        tmp = d / (name + ".tmp")
        tmp.write_text(md, encoding="utf-8")
        tmp.replace(d / name)
    notify.write_json(d / "weekly.json", {"week": week_key(now_ms), "date": day, "generated_ms": now_ms,
                                          "model": answer.get("servedBy") or answer.get("model"),
                                          "costUsd": cost, "batch": bool(answer.get("batchId"))})
    return d / "weekly.md"


def run(now_ms: int | None = None, dry_run: bool = False, force: bool = False, state: dict | None = None,
        results: Path | None = None, poster=None) -> int:
    now = now_ms or notify.clock_ms()
    last = notify.read_json(ai_reports() / "weekly.json") or {}
    if last.get("week") == week_key(now) and not force and not dry_run:
        notify.say(f"the review for {week_key(now)} exists; nothing called (--force for another)")
        return 0
    if state is None:
        state = notify.engine_state()
    prompt = build_prompt(now, state, results)
    if dry_run:
        notify.say(SYSTEM + "\n\n" + prompt)
        notify.say(f"\n[dry run] about {(len(SYSTEM) + len(prompt)) // 4:,} input tokens, at most {MAX_TOKENS} out; nothing called")
        return 0
    try:
        answer = engine.complete("weekly", SYSTEM, prompt, MAX_TOKENS, model=engine.REVIEW, effort="medium",
                                 batch=True, batch_wait_sec=BATCH_WAIT_SEC, poster=poster)
    except engine.AiError as e:
        notify.say(f"no weekly review: {e}", err=e.kind not in ("budget", "nokey"))
        return 0 if e.kind in ("budget", "nokey") else 1
    if not str(answer.get("text") or "").strip():
        notify.say("the review came back empty", err=True)
        return 1
    p = write(now, answer)
    notify.say(f"weekly review written to {p} (${float(answer.get('costUsd') or 0):.3f})")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(argv or [])
    return run(dry_run="--dry-run" in argv, force="--force" in argv)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
