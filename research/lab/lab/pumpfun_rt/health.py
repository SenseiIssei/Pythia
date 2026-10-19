"""Health check of the real-time pump.fun collector (job `pumpfun-rt-health`).

    python -m lab.pumpfun_rt.health          exit 0 when fresh, 1 when not (the job turns red and alerts)

Fresh means: the newest trades part file was written in the last MAX_AGE_MIN
minutes, and the heartbeat is that recent too. pump.fun trades every second
of the day, so ten quiet minutes mean the collector or its stream is down.
"""

from __future__ import annotations

import argparse
import json
import sys
import time

from . import store

MAX_AGE_MIN = 10


def newest_part_ms(table: str = "trades") -> int:
    root = store.base() / table
    best = 0.0
    if not root.is_dir():
        return 0
    for d in sorted((p for p in root.iterdir() if p.is_dir() and p.name.startswith("date=")), reverse=True)[:2]:
        for f in d.glob("*.parquet"):
            best = max(best, f.stat().st_mtime)
    return int(best * 1000)


def check(now_ms: int | None = None, max_age_min: float = MAX_AGE_MIN) -> tuple[bool, str]:
    now_ms = now_ms or int(time.time() * 1000)
    lim = max_age_min * 60_000
    part = newest_part_ms()
    try:
        hb = json.loads((store.base() / "heartbeat.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        hb = {}
    beat = int(hb.get("t") or 0)
    problems = []
    if not part:
        problems.append("no trades written yet")
    elif now_ms - part > lim:
        problems.append(f"no trades written for {(now_ms - part) / 60_000:.0f} min")
    if not beat:
        problems.append("no heartbeat")
    elif now_ms - beat > lim:
        problems.append(f"heartbeat {(now_ms - beat) / 60_000:.0f} min old")
    down = [p[:4] for p, up in (hb.get("connected") or {}).items() if not up]
    c = hb.get("counts") or {}
    detail = (f"last trades part {(now_ms - part) / 1000:.0f} s ago, {c.get('trades', 0)} trades and "
              f"{c.get('creates', 0)} creations since start, {hb.get('reconnects', 0)} reconnects, "
              f"{c.get('gaps', 0)} gaps" + (f", streams down: {', '.join(down)}" if down else "")) if part else ""
    if problems:
        return False, "pump.fun collector: " + "; ".join(problems) + (f" ({detail})" if detail else "")
    return True, "pump.fun collector ok: " + detail


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--max-age-min", type=float, default=MAX_AGE_MIN)
    a = ap.parse_args(argv)
    ok, msg = check(max_age_min=a.max_age_min)
    print(msg)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
