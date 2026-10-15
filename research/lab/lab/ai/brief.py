"""The daily market brief: one cheap Claude call (Haiku, through the Batches
API at half price) over facts Pythia already has, giving

  - for BTC, ETH and every coin a running autopilot trades: the probability
    that its close in 7 days is above the latest daily close, with one line
    of reason (structured JSON, checked here before anything is kept), and
  - three plain lines for the Telegram digest.

Every prediction is appended to <data>/ai/predictions.jsonl with what the base
rate and the momentum rule said at the same moment, and scored when its week
is over (lab.ai.score). The brief is written to reports/ai_brief/latest.json,
a lab feed the Research page and the Models page read; the digest
(lab.ops.notify) quotes its three lines.

Shadow only. Nothing reads these numbers to size, place or veto an order.

  python -m lab.ai.brief             once a day (jobs.yaml: ai-brief)
  python -m lab.ai.brief --dry-run   print the prompt and its size, call nothing
  python -m lab.ai.brief --force     a second brief the same day (a second call)

Exit 0 also when the call was not made because the budget said no or there is
no key: the engine has already said so (and alerted at the caps); a job
failure would only repeat it.
"""

from __future__ import annotations

import math
import sys
from datetime import datetime, timezone

from ..ops import notify
from . import engine, facts, score

FIXED = ("BTC", "ETH")
MAX_COINS = 12
MAX_TOKENS = 1500
BATCH_WAIT_SEC = 20 * 60
NAME = "ai_brief"

SYSTEM = """You write the daily market brief for Pythia, an automated paper-trading research system for crypto. \
The owner reads three lines of it on a phone, and every number you give is scored later against what happened.

You get today's facts: recent daily closes and returns, volatility, distance to the 200-day mean and to the \
one-year high, perpetual funding, the running autopilots (paper or demo money) and the headlines of the \
research lab's own reports. That is everything you know. You have no news feed. Do not invent news, events, \
flows, prices or figures that are not in the facts, and do not claim knowledge of anything after them.

For every coin listed under PREDICT give pUp7d: the probability that the coin's daily close 7 days after its \
latest close in the facts is ABOVE that latest close. Rules for the number:
- It is scored with the Brier score against what happens, next to two references: the coin's share of up \
weeks over the last year (usually between 0.45 and 0.55) and a momentum rule. A confident wrong number costs \
far more than an honest one near 0.5.
- Weekly crypto direction is close to a coin flip. Without a clear reason in the facts stay between 0.45 and \
0.55. Go beyond 0.40 to 0.60 only when several facts point the same way, and never beyond 0.25 to 0.75.
- Coins move together. If your reasons for two coins are the same market-wide reason, their numbers should \
be close.
- reason: one plain sentence, at most 20 words, naming the facts that moved you away from 0.5, or saying \
that nothing did.

Then summary: exactly three short lines for the owner, plain words, no markdown, no emoji, at most 25 words \
each: (1) what the market did and the overall picture, (2) what stands out in the autopilots or the lab \
reports, (3) what to watch this week. Never tell the owner to buy or sell anything: these numbers are a \
research record in shadow mode, they never trade. Do not use em dashes.

Answer with the JSON object only, in the schema given."""

SCHEMA = {
    "type": "object",
    "properties": {
        "predictions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "coin": {"type": "string"},
                    "pUp7d": {"type": "number"},
                    "reason": {"type": "string"},
                },
                "required": ["coin", "pUp7d", "reason"],
                "additionalProperties": False,
            },
        },
        "summary": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["predictions", "summary"],
    "additionalProperties": False,
}


def brief_dir():
    return notify.reports_root() / NAME


def today(now_ms: int) -> str:
    return datetime.fromtimestamp(now_ms / 1000, timezone.utc).strftime("%Y-%m-%d")


def pick_coins(state: dict | None) -> list[str]:
    out = list(FIXED)
    for c in facts.autopilot_coins(state):
        if c not in out:
            out.append(c)
    return out[:MAX_COINS]


def build_prompt(day: str, coins: list[str], closes: dict[str, score.Closes], state: dict | None,
                 funding: list[str], feeds: list[str]) -> str:
    lines = [f"DATE: {day} (UTC). Horizon: 7 days from each coin's latest close below.", "", "PRICES (daily closes):"]
    for c in coins:
        line = facts.price_line(c, closes.get(c) or [])
        if line:
            lines.append("- " + line)
    if funding:
        lines += ["", "FUNDING (perpetuals, settled):"] + ["- " + f for f in funding]
    aps = facts.autopilot_lines(state)
    lines += ["", "AUTOPILOTS (running):"] + (["- " + a for a in aps] if aps else ["- none running"])
    if feeds:
        lines += ["", "LAB REPORTS (headlines):"] + ["- " + f for f in feeds]
    lines += ["", "PREDICT: " + ", ".join(coins)]
    return "\n".join(lines)


def _clean(s, n: int) -> str:
    s = notify.nodash(" ".join(str(s or "").split()))
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def parse_answer(obj, coins: list[str]) -> tuple[dict[str, dict], list[str], list[str]]:
    """The model's JSON, checked: ({coin: {p, reason}}, three summary lines,
    problems). A prediction for a coin not asked for, a duplicate, or a
    probability that is not a number in [0, 1] is dropped and named."""
    preds: dict[str, dict] = {}
    problems: list[str] = []
    if not isinstance(obj, dict):
        return {}, [], ["the answer is not a JSON object"]
    raw = obj.get("predictions")
    if not isinstance(raw, list):
        problems.append("no predictions list")
        raw = []
    asked = set(coins)
    for it in raw:
        if not isinstance(it, dict):
            problems.append("a prediction that is not an object")
            continue
        coin = str(it.get("coin") or "").strip().upper()
        if coin not in asked:
            problems.append(f"{coin or '?'} was not asked for")
            continue
        if coin in preds:
            problems.append(f"{coin} twice, the first kept")
            continue
        try:
            p = float(it.get("pUp7d"))
        except (TypeError, ValueError):
            problems.append(f"{coin}: pUp7d is not a number")
            continue
        if not math.isfinite(p) or p < 0 or p > 1:
            problems.append(f"{coin}: pUp7d {p} is outside 0 to 1")
            continue
        preds[coin] = {"p": p, "reason": _clean(it.get("reason"), 200)}
    missing = [c for c in coins if c not in preds]
    if missing:
        problems.append("no prediction for " + ", ".join(missing))
    summary = [_clean(s, 220) for s in (obj.get("summary") or []) if isinstance(s, str) and s.strip()][:3]
    if len(summary) < 3:
        problems.append(f"{len(summary)} summary lines instead of 3")
    return preds, summary, problems


def ask(prompt: str, poster=None) -> dict:
    """The call: a batch at half price first; if it has not finished in 20
    minutes (it is cancelled and counted at its worst case), once directly."""
    try:
        return engine.complete("brief", SYSTEM, prompt, MAX_TOKENS, model=engine.ROUTINE, schema=SCHEMA,
                               effort="low", batch=True, batch_wait_sec=BATCH_WAIT_SEC, poster=poster)
    except engine.AiError as e:
        if e.kind != "timeout":
            raise
        notify.say(f"batch not finished in time ({e}); asking directly", err=True)
    return engine.complete("brief-direct", SYSTEM, prompt, MAX_TOKENS, model=engine.ROUTINE, schema=SCHEMA,
                           effort="low", batch=False, poster=poster)


def feed(day: str, now: int, coins: list[str], preds: dict[str, dict], summary: list[str], rows: list[dict],
         answer: dict, problems: list[str]) -> dict:
    items = []
    for c in coins:
        r = next((x for x in rows if x["coin"] == c), None)
        if r is None:
            continue
        items.append({"label": c, "value": f"{100 * r['p_llm']:.0f} % up in 7 days",
                      "detail": f"{r['reason']} Base rate {100 * r['p_base']:.0f} %, momentum rule {100 * r['p_momentum']:.0f} %.",
                      "importance": int(min(100, 200 * abs(r["p_llm"] - 0.5)))})
    head = summary[0] if summary else f"{len(rows)} seven-day calls, shadow only."
    usage = answer.get("usage") or {}
    return {
        "title": "AI brief", "status": "ok" if not problems else "watch", "headline": head,
        "updated_ms": now, "updatedMs": now, "items": items,
        "date": day, "generated_ms": now, "model": answer.get("servedBy") or answer.get("model"),
        "summary": summary, "predictions": rows, "problems": problems,
        "costUsd": answer.get("costUsd"), "batch": bool(answer.get("batchId")), "usage": usage,
        "caveat": "Shadow only: scored against a base rate and the momentum rule, never traded.",
    }


def run(now_ms: int | None = None, dry_run: bool = False, force: bool = False, state: dict | None = None,
        closes: dict[str, score.Closes] | None = None, loader=score.binance_closes, poster=None,
        funding_loader=None) -> int:
    now = now_ms or notify.clock_ms()
    day = today(now)
    latest = notify.read_json(brief_dir() / "latest.json") or {}
    if latest.get("date") == day and not force and not dry_run:
        notify.say(f"the brief for {day} exists; nothing called (--force for another)")
        score.run(now, loader=loader, closes=closes)
        return 0
    if state is None:
        state = notify.engine_state()
    coins = pick_coins(state)
    if closes is None:
        closes = score.closes_for(set(coins) | {r["coin"] for r in score.read_predictions()}, loader)
    usable = [c for c in coins if len(closes.get(c) or []) >= score.MIN_WINDOWS + score.HORIZON]
    if not usable:
        notify.say("no daily closes for any coin: no brief", err=True)
        return 1
    prompt = build_prompt(day, usable, closes, state, facts.funding_lines(usable, funding_loader), facts.feed_lines())
    if dry_run:
        notify.say(SYSTEM + "\n\n" + prompt)
        chars = len(SYSTEM) + len(prompt)
        notify.say(f"\n[dry run] about {chars // 4:,} input tokens, at most {MAX_TOKENS} out; nothing called")
        return 0
    try:
        answer = ask(prompt, poster)
    except engine.AiError as e:
        notify.say(f"no brief today: {e}", err=e.kind not in ("budget", "nokey"))
        score.run(now, closes=closes)
        return 0 if e.kind in ("budget", "nokey") else 1
    preds, summary, problems = parse_answer(answer.get("json"), usable)
    for p in problems:
        notify.say(f"brief: {p}", err=True)
    have = {(r["date"], r["coin"]) for r in score.read_predictions()}
    rows = []
    for c in usable:
        if c not in preds:
            continue
        ref = closes[c][-1]
        comp = score.comparators(closes[c])
        rows.append({
            "id": f"{day}:{c}", "date": day, "made_ms": now, "coin": c, "horizon_days": score.HORIZON,
            "ref_day": ref[0], "ref_close": ref[1], "resolve_day": score.resolve_day(ref[0]),
            "p_llm": preds[c]["p"], "reason": preds[c]["reason"], "p_base": comp["base"],
            "p_momentum": comp["momentum"], "momentum_sign": comp["momentum_sign"],
            "model": answer.get("servedBy") or answer.get("model") or engine.ROUTINE,
        })
    score.append_predictions([r for r in rows if (r["date"], r["coin"]) not in have])
    data = feed(day, now, usable, preds, summary, rows, answer, problems)
    notify.write_json(brief_dir() / "latest.json", data)
    notify.write_json(brief_dir() / f"{day}.json", data)
    sc = score.run(now, closes=closes)
    notify.say(f"brief {day}: {len(rows)} calls, ${float(answer.get('costUsd') or 0):.4f}. " + " / ".join(summary))
    notify.say(sc["verdict"])
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(argv or [])
    return run(dry_run="--dry-run" in argv, force="--force" in argv)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
