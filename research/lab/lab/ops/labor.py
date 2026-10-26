"""The lab's evening card: one message at 20:00 Europe/Berlin to Telegram and Discord, "🧠 Labor".

What the research factories and A1's model zoo did today, from their reports only (fixed templates, no model is
asked anything), at most MAX_LINES lines:

  per factory    its line of the morning briefing (briefing.factory_line: trials, the bar, the best new
                 candidate held back, books, model settings adopted), or that it has no fresh report
                 (reports/pumpfun_rt/factory.json F3, reports/smallaccount/factory.json F2)
  books          the factories' paper books with their wallets in SOL and euro, the proposals for the owner
  zoo            the selector's pick per label and the changes of its last scored day (reports/pumpfun_rt/zoo.json)
  allocator      its pick and why (reports/pumpfun_rt/allocator.json); it never steers the live bot

A report counts when it was written in the last 24 hours. Without any, nothing is sent. Category "lab" (its switch
is on unless the engine's settings turn it off); Discord: the bot's #labor (#lab in English) when its channel map has
one, else the briefing's channel (or the webhook).

  python -m lab.ops.labor             send it when it is 20 o'clock in Berlin and it has not gone out today (the job
                                      runs at 18 and 19 UTC, so summer and winter time both hit 20)
  python -m lab.ops.labor --force     now, whatever the hour
  python -m lab.ops.labor --dry-run   print it, post nothing
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone

from . import briefing, i18n, notify
from .notify import Card, Line, _num, tr

HOUR = 20
DAY_MS = notify.DAY_MS
MAX_LINES = 8
CHANNEL = "labor"                          # the bot's German channel for the "lab" kind (DISCORD_ROUTES)


def due(now_ms: int, last_day: str | None) -> bool:
    """Eight in the evening in Berlin (summer or winter time) and not sent today yet."""
    t = notify.local_time(now_ms)
    return t.hour == HOUR and last_day != t.date().isoformat()


def today(d, now: int) -> dict | None:
    """The report when it was written in the last 24 hours, else None."""
    at = briefing.stamp_ms(d) if isinstance(d, dict) else None
    return d if at is not None and 0 <= now - at <= DAY_MS else None


def books_line(reps: dict, eur: float | None, lang: str) -> list:
    """The factories' running paper books, each wallet in SOL and euro (the report's own rate when none is given),
    and the proposals waiting for the owner."""
    out, props = [], []
    for code, _, _ in briefing.FACTORIES:
        rep = reps.get(code) or {}
        rate = eur or _num(rep.get("sol_eur"))
        for b in rep.get("books") or []:
            sol = _num((b or {}).get("sol"))
            if sol is None or not b.get("book"):
                continue
            out.append(f"{b['book']} {i18n.sol(sol, 3, lang)}" + (f" ({i18n.eur(sol * rate, 2, lang)})" if rate else ""))
        props += [str(p) for p in rep.get("proposals") or []]
    lines = [Line("; ".join(out[:5]) + (f" (+{len(out) - 5})" if len(out) > 5 else ""), tr("lb_books", lang))] if out else []
    if props:
        lines.append(Line(", ".join(props[:5]), tr("lb_proposals", lang)))
    return lines


def zoo_line(zoo: dict | None, lang: str) -> Line | None:
    """The selector's pick per label and the changes on its last scored day (the day before the report's)."""
    labels = (zoo or {}).get("labels") if isinstance(zoo, dict) else None
    if not isinstance(labels, dict):
        return None
    picks = [f"{k} {v['pick']}" for k, v in labels.items() if isinstance(v, dict) and v.get("pick")]
    if not picks:
        return None
    since = datetime.fromtimestamp(((_num(zoo.get("updated_ms")) or 0) - DAY_MS) / 1000, timezone.utc).strftime("%Y-%m-%d")
    changes = [f"{k} {c.get('from')}→{c.get('to')}" for k, v in labels.items() if isinstance(v, dict)
               for c in v.get("changes") or [] if isinstance(c, dict) and str(c.get("day") or "") >= since]
    text = tr("lb_zoo_picks", lang, picks=", ".join(picks))
    if changes:
        text += " · " + tr("lb_zoo_changes", lang, changes=", ".join(changes[:4]))
    return Line(text, tr("lb_zoo", lang))


def build(now: int, lang: str, eur: float | None = None, read=None) -> Card | None:
    """The card, or None when no report of today is there. `read(name, file)` gives a report (tests pass their own)."""
    read = read or (lambda name, file: notify.read_json(notify.reports_root() / name / file))
    reps = {code: today(read(folder, file), now) for code, folder, file in briefing.FACTORIES}
    zoo = today(read("pumpfun_rt", "zoo.json"), now)
    alloc = today(read("pumpfun_rt", "allocator.json"), now)
    if not any(reps.values()) and zoo is None and alloc is None:
        return None
    lines: list = []
    for code, _, _ in briefing.FACTORIES:
        ln = briefing.factory_line(code, reps[code], lang)
        lines.append(ln if ln is not None else Line(tr("lb_missing", lang), tr("bf_fac_" + code, lang)))
    lines += books_line(reps, eur, lang)
    lines += [x for x in (zoo_line(zoo, lang), briefing.alloc_line(alloc, lang)) if x is not None]
    return Card("🧠", tr("lb_title", lang, day=notify.day_label(now, lang)), tr("lb_summary", lang), lines[:MAX_LINES],
                tr("lb_footer", lang))


def discord_kind() -> str:
    """"lab" when the bot's channel map has #labor, else "briefing" (its channel, or the webhook)."""
    try:
        return "lab" if notify.discord_bot_token() and notify.discord_channels().get(CHANNEL) else "briefing"
    except Exception:  # noqa: BLE001 - the card goes to the briefing's place then
        return "briefing"


def run(now: int | None = None, force: bool = False, dry_run: bool = False, eur=notify.sol_eur, poster=None,
        discord_poster=None) -> int:
    now = now or notify.clock_ms()
    state_path = notify.data_root() / "notify" / "state.json"
    st = notify.read_json(state_path) or {}
    day = notify.local_time(now).date().isoformat()
    if not force and not due(now, st.get("last_labor")):
        notify.say("not 20 o'clock in Berlin, or the lab card went out today: nothing (use --force)")
        return 0
    lang = notify.alert_lang()
    rate = eur() if callable(eur) else eur
    card = build(now, lang, rate)
    if card is None:
        notify.say("no factory, zoo or allocator report of today: no lab card")
        return 0
    card.lang, card.remake = lang, (lambda lg: build(now, lg, rate) or card)
    res = notify.send("lab", [card], now=now, dry_run=dry_run, poster=poster, discord=discord_kind(),
                      discord_poster=discord_poster)
    if dry_run or res["reason"] in ("off", "quiet"):
        return 0
    discord_ok = (res.get("discord") or {}).get("delivered")
    if not res["delivered"] and not discord_ok and res["reason"] != "no destination":
        notify.say(f"lab card not delivered: {res['error']}", err=True)
        return 1
    notify.write_json(state_path, {**(notify.read_json(state_path) or {}), "last_labor": day})
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    return run(force="--force" in argv, dry_run="--dry-run" in argv)


if __name__ == "__main__":
    sys.exit(main())
