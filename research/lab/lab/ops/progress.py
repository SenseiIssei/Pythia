"""U1: how far Pythia is from real money, for the app's page `progress` (results/progress_page_u1_prereg.md).

Built from the reports only (read only, every 15 minutes, job `progress`) into reports/progress/latest.json; the
server serves it unchanged as GET /api/lab/progress. Five sections, each with the file it comes from, the time of
that file (its own updated_ms or generated_ms, else its modification time) and the age after which it is stale, so
the page never shows an old number as current. A missing report is `found: false`.

  reports/ladder/latest.json            the readiness ladder: each candidate's step and what is missing next
  reports/pumpfun_rt/realistic.json     P3's 10 EUR books (`ten`), the calibration line and P2's gap (`selection`)
  reports/paper_review/latest.json      the tsmom books' gate 7 (30 days and 30 rebalances)
  reports/weekly/latest.md              the newest weekly page (W1), its first lines

No new number and no trial: the reports' own numbers, sorted and copied. Never arms, changes or sends anything.

  python -m lab.ops.progress            write reports/progress/latest.json
  python -m lab.ops.progress --print    print it, write nothing
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import notify
from .lablive import ms_iso, scrub, stamp

HOUR_MS = 3_600_000
DAY_MS = 24 * HOUR_MS
WEEKLY_LINES = 12
GATE7_DAYS, GATE7_REBALANCES = 30, 30   # lab.paper.review.MIN_DAYS, MIN_REBALANCES
TEN_DAYS, TEN_GAP_PTS = 30, 2.0         # lab.pumpfun_rt.realistic.TEN_DAYS, TEN_GAP_PTS

LADDER = "reports/ladder/latest.json"
REALISTIC = "reports/pumpfun_rt/realistic.json"
REVIEW = "reports/paper_review/latest.json"
WEEKLY = "reports/weekly/latest.md"
# Stale after: the source's schedule plus slack (the ladder every 5 minutes with lablive, the others daily, W1 weekly).
STALE_MS = {LADDER: 2 * HOUR_MS, REALISTIC: 36 * HOUR_MS, REVIEW: 36 * HOUR_MS, WEEKLY: 8 * DAY_MS}

STEP_DE = {0: "keine", 1: "Idee", 2: "getestet", 3: "Schatten", 4: "Lockbox", 5: "Ausführung", 6: "größer"}
TEN_GATE_DE = {"days": f"{TEN_DAYS} Tage", "mean": "Mittel über 0", "band": "Band über 0",
               "gap": f"P2-Lücke unter {TEN_GAP_PTS:g} Punkten", "taint": "P1 raus"}
VERDICT_DE = {"not yet": "noch nicht", "calibrated": "kalibriert", "not calibrated": "nicht kalibriert"}


def _n(v) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def source(root: Path, rel: str, doc, now: int) -> dict:
    """The section's head: file, found, at_ms (the report's stamp, else its mtime), age, stale."""
    p = root / rel
    at = stamp(doc) if isinstance(doc, dict) else None
    if at is None and p.is_file():
        at = int(p.stat().st_mtime * 1000)
    found = doc is not None
    age = now - at if at else None
    return {"file": rel, "found": found, "at_ms": at, "at": ms_iso(at), "age_ms": age, "stale_ms": STALE_MS[rel],
            "stale": found and (age is None or age > STALE_MS[rel])}


def ladder(root: Path, now: int) -> dict:
    d = notify.read_json(root / LADDER)
    d = d if isinstance(d, dict) else None
    out = source(root, LADDER, d, now)
    rows = []
    for r in (d or {}).get("rows") or []:
        if not isinstance(r, dict):
            continue
        st = int(_n(r.get("step")) or 0)
        rows.append({"id": str(r.get("id") or r.get("name") or ""), "name": str(r.get("short") or r.get("name") or ""),
                     "kind": r.get("kind"), "study": r.get("study"), "step": st, "step_name": STEP_DE.get(st, str(st)),
                     "next": scrub(r.get("next_de") or r.get("next") or "", 240), "tainted": int(_n(r.get("tainted")) or 0)})
    rows.sort(key=lambda r: (-r["step"], r["name"].lower()))
    reg = (d or {}).get("registry") or {}
    top = rows[0]["step"] if rows else None
    return out | {"top_step": top, "top_name": STEP_DE.get(top) if top is not None else None,
                  "steps": {str(k): v for k, v in STEP_DE.items()},
                  "counts": {str(k): int(_n(v) or 0) for k, v in ((d or {}).get("counts") or {}).items()},
                  "n_trials": _n(reg.get("n_trials")), "sr0_annual": _n(reg.get("sr0_annual")), "rows": rows}


def ten(real: dict | None, head: dict) -> dict:
    """P3: started is False until one of the books has a wallet (the report's `started`)."""
    books = []
    for b in (real or {}).get("ten") or []:
        if not isinstance(b, dict):
            continue
        gate = b.get("gate") if isinstance(b.get("gate"), dict) else {}
        band = b.get("band") if isinstance(b.get("band"), list) and len(b["band"]) == 2 else None
        books.append({"book": b.get("book"), "strategy": b.get("strategy"), "started": b.get("started") is True,
                      "sol": _n(b.get("sol")), "eur": _n(b.get("eur")), "start_sol": _n(b.get("start_sol")),
                      "trades": int(_n(b.get("trades")) or 0), "mean": _n(b.get("mean")), "median": _n(b.get("median")),
                      "band": [_n(band[0]), _n(band[1])] if band else None, "days": _n(b.get("days")),
                      "need_days": TEN_DAYS, "can_pay": b.get("can_pay") is not False, "pass": b.get("pass") is True,
                      "gate": [{"id": k, "label": TEN_GATE_DE.get(k, k), "ok": gate[k] is True} for k in gate]})
    return head | {"started": any(b["started"] for b in books), "books": books}


def gap(real: dict | None, head: dict) -> dict:
    cal = (real or {}).get("calibration")
    cal = cal if isinstance(cal, dict) else None
    sel = (real or {}).get("selection")
    sel = sel if isinstance(sel, dict) else None
    c = None
    if cal is not None:
        days = _n(cal.get("days"))
        if days is None and _n(cal.get("from_ms")) and _n(cal.get("to_ms")):
            days = (cal["to_ms"] - cal["from_ms"]) / DAY_MS
        v = str(cal.get("verdict") or "")
        c = {"rule": cal.get("rule"), "pairs": int(_n(cal.get("n")) or 0), "live": int(_n(cal.get("live")) or 0),
             "paper": int(_n(cal.get("paper")) or 0), "days": days, "to_ms": _n(cal.get("to_ms")),
             "median_pts": _n(cal.get("d_pts")), "mean_pts": _n(cal.get("d_pts_mean")),
             "verdict": VERDICT_DE.get(v, v) or None}
    p2 = None
    if sel is not None:
        p2 = {"pts": _n(sel.get("pts")), "gate_pts": _n(sel.get("gate_pts")) or TEN_GAP_PTS, "pass": sel.get("pass") is True,
              "line": scrub(sel.get("line") or "", 300) or None}
    return head | {"calibration": c, "p2": p2}


def gate7(root: Path, now: int) -> dict:
    d = notify.read_json(root / REVIEW)
    d = d if isinstance(d, dict) else None
    books = []
    for b in (d or {}).get("books") or []:
        if not isinstance(b, dict) or not b.get("book"):
            continue
        days, reb = int(_n(b.get("days")) or 0), int(_n(b.get("rebalances")) or 0)
        books.append({"book": b["book"], "since": b.get("since"), "days": days, "rebalances": reb,
                      "need_days": GATE7_DAYS, "need_rebalances": GATE7_REBALANCES,
                      "ready": days >= GATE7_DAYS and reb >= GATE7_REBALANCES,
                      "paper_pct": _n(b.get("paper_return_pct")), "backtest_pct": _n(b.get("backtest_return_pct")),
                      "daily_corr": _n(b.get("daily_corr"))})
    return source(root, REVIEW, d, now) | {"books": books}


def weekly(root: Path, now: int) -> dict:
    p = root / WEEKLY
    try:
        text = p.read_text(encoding="utf-8")
    except OSError:
        text = None
    lines = [scrub(ln, 300) for ln in (text or "").splitlines() if ln.strip()][:WEEKLY_LINES]
    return source(root, WEEKLY, text, now) | {"lines": lines}


def build(root: Path | None = None, now: int | None = None) -> dict:
    root = Path(root) if root is not None else notify.data_root()
    now = now or int(datetime.now(timezone.utc).timestamp() * 1000)
    real = notify.read_json(root / REALISTIC)
    real = real if isinstance(real, dict) else None
    head = source(root, REALISTIC, real, now)
    return {"updated_ms": now, "generated": ms_iso(now), "prereg": "research/lab/results/progress_page_u1_prereg.md",
            "ladder": ladder(root, now), "ten": ten(real, head), "gap": gap(real, head), "gate7": gate7(root, now),
            "weekly": weekly(root, now)}


def out_path() -> Path:
    return notify.reports_root() / "progress" / "latest.json"


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    d = build()
    if "--print" in argv:
        notify.say(json.dumps(d, indent=1, ensure_ascii=False)[:20000])
        return 0
    notify.write_json(out_path(), d)
    stale = [k for k in ("ladder", "ten", "gate7", "weekly") if d[k]["stale"]]
    notify.say(f"progress: {len(d['ladder']['rows'])} candidates, top step {d['ladder']['top_step']}, "
               f"P3 {'started' if d['ten']['started'] else 'not started'}, stale {stale or 'none'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
