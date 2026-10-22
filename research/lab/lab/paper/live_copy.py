"""Copies of lab books for real money, so a live autopilot never shares a strategy with paper.

The engine runs a strategy in one mode at a time: a book that paper and demo
autopilots already use (breakout_top10 in Auto-Pick, the forward control and
Crypto + SPY) cannot also back a live autopilot. Stopping the paper runs would
end the forward evidence the readiness rule waits for. So each book named in
BOOKS gets a twin, <book>_live: the same weights, the same evidence, the same
validity, a strategy id of its own and "live copy" in its name. The owner's
live autopilot names the twin; the paper autopilots keep the original.

Run after the books are written (the job paper-live-copy, after paper-families):

    python -m lab.paper.live_copy              write every twin
    python -m lab.paper.live_copy --dry-run    print what it would write

A twin is written only from a fresh original and never outlives it: it carries
the original's valid_until_ms, so a missed lab run stops the live book exactly as
it stops the paper one.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(os.environ.get("PYTHIA_DATA", "/data"))
BOOKS = ["breakout_top10"]
SUFFIX = "_live"


def twin(sig: dict) -> dict:
    out = dict(sig)
    out["strategy"] = f"{sig['strategy']}{SUFFIX}"
    out["variant"] = f"{sig.get('variant') or sig['strategy']} (live copy)"
    out["live_copy_of"] = sig["strategy"]
    # Only an autopilot that names it runs it: an auto pick never adds the twin next to its original.
    out["evidence"] = {**(sig.get("evidence") or {}), "explicit_only": True}
    return out


def write_twins(root: Path | None = None, books: list[str] | None = None, now_ms: int | None = None,
                dry_run: bool = False) -> list[str]:
    root = ROOT if root is None else root
    now_ms = now_ms if now_ms is not None else int(time.time() * 1000)
    done = []
    for book in books or BOOKS:
        src = root / "signals" / book / "latest.json"
        try:
            sig = json.loads(src.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            print(f"live_copy: {book}: no readable signal ({e})", file=sys.stderr)
            continue
        if sig.get("strategy") != book or int(sig.get("valid_until_ms") or 0) < now_ms:
            print(f"live_copy: {book}: the signal is stale or not this book, no twin written", file=sys.stderr)
            continue
        t = twin(sig)
        if dry_run:
            print(json.dumps({k: t[k] for k in ("strategy", "variant", "valid_until_ms")}))
        else:
            d = root / "signals" / t["strategy"]
            d.mkdir(parents=True, exist_ok=True)
            tmp = d / "latest.json.tmp"
            tmp.write_text(json.dumps(t), encoding="utf-8")
            tmp.replace(d / "latest.json")
        done.append(t["strategy"])
    return done


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    done = write_twins(dry_run=a.dry_run)
    print(f"live_copy: {', '.join(done) or 'nothing'} written" + (" (dry run)" if a.dry_run else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
