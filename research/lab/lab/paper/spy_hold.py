"""Lab book of US shares: SPY bought and held, the equity sleeve of a registered forward test. No real money.

    python -m lab.paper.spy_hold              write this month's signal (once per calendar month)
    python -m lab.paper.spy_hold --dry-run    print the signal and whether it is due; write nothing

The SPY sleeve of "Crypto + SPY (forward test)" (results/equity_sleeve_prereg.md,
registered 2026-10-21): 80 % breakout_top10 and 20 % SPY bought and held, on the
Alpaca paper account, against breakout_top10 alone for 90 days.

The signal is always 100 % SPY. It is published once per calendar month (the first
run in a month); the engine trades a lab book only on a signal it has not traded
yet, so the SPY sleeve goes back to its share of the portfolio once a month, at
the first regular US session after the new signal, and drifts with the market in
between. The signal stays valid for 40 days, so it never goes stale between two
months.

Its evidence is SPY bought and held from results/book_portfolio.md (X7 B: out of
sample from 2024 on the crypto calendar), marked `explicit_only`: the engine's auto
pick, and with it the portfolio allocator, never picks it, whatever its numbers.
It runs only where an autopilot names `lab:spy_hold` as a sleeve, so no other
autopilot gets SPY because of this test.

Engine signal: <data>/signals/spy_hold/latest.json (and a dated copy).
"""

from __future__ import annotations

import json
import re
import sys
import time
from datetime import datetime, timezone

from ..experiments import fam_common as fc
from ..data import ROOT
from .tsmom import save_signal

NAME = "spy_hold"
VARIANT = "SPY bought and held · back to its share once a month (sleeve of the Crypto + SPY forward test)"
VALID_DAYS = 40
DAY_MS = 86_400_000
STUDY = "book_portfolio"
PREREG = "results/equity_sleeve_prereg.md"


def evidence(text: str | None = None) -> dict:
    """SPY bought and held from results/book_portfolio.md, marked explicit only. `missing`
    when the study's line is not where it should be (the signal still runs: the forward
    test does not depend on these numbers, they only describe the sleeve)."""
    if text is None:
        try:
            text = (fc.RESULTS_DIR / f"{STUDY}.md").read_text(encoding="utf-8")
        except OSError:
            text = ""
    base = {"report": STUDY, "explicit_only": True,
            "caveat": "SPY bought and held, out of sample from 2024 on the crypto calendar (zero on days without a "
                      "session). The equity sleeve came out of an after-the-fact count in X7 B (22 of 24 mixes); "
                      f"only the forward test ({PREREG}) decides whether it belongs in an autopilot.",
            "verdict": "sleeve of a registered forward test: runs only where an autopilot names it"}
    m = re.search(r"SPY buy and hold Sharpe ([0-9.]+), drawdown ([0-9.]+) %", text or "")
    if not m:
        return {**base, "missing": True}
    return {**base, "oos_sharpe": float(m.group(1)), "oos_max_dd": float(m.group(2)) / 100,
            "source": str(fc.RESULTS_DIR / f"{STUDY}.md")}


def month(ms: int) -> tuple[int, int]:
    d = datetime.fromtimestamp(ms / 1000, timezone.utc)
    return d.year, d.month


def due(prev: dict | None, now_ms: int) -> bool:
    """A new signal is due on the first run in a calendar month, or when the last one
    is missing, stale or not this book's."""
    if not prev or prev.get("strategy") != NAME:
        return True
    if int(prev.get("valid_until_ms") or 0) < now_ms:
        return True
    return month(int(prev.get("generated_ms") or 0)) != month(now_ms)


def signal(now_ms: int, ev: dict | None = None) -> dict:
    day = now_ms // DAY_MS * DAY_MS
    return {
        "strategy": NAME,
        "variant": VARIANT,
        "as_of_ms": day,
        "generated_ms": now_ms,
        "valid_until_ms": now_ms + VALID_DAYS * DAY_MS,
        "quote": "USD",
        "asset_class": "us_equity",
        "weights": {"SPY": 1.0},
        "autopilot_only": True,
        "evidence": ev if ev is not None else evidence(),
        "dropped": [],
        "dropped_weight": 0.0,
        "lab_exposure": 1.0,
        "cadence": "monthly",
        "forward_test": PREREG,
    }


def read_latest(root=None) -> dict | None:
    p = (ROOT if root is None else root) / "signals" / NAME / "latest.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def main(argv: list[str] | None = None, now_ms: int | None = None, root=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    now_ms = now_ms or int(time.time() * 1000)
    prev = read_latest(root)
    is_due = due(prev, now_ms)
    sig = signal(now_ms)
    if "--dry-run" in argv:
        print(NAME, "due" if is_due else "not due (already published this month)", json.dumps(sig["weights"]))
        print(NAME, "evidence", json.dumps({k: sig["evidence"].get(k) for k in ("oos_sharpe", "oos_max_dd", "explicit_only", "missing")}))
        return 0
    if not is_due:
        print(f"{NAME}: this month's signal is out already ({datetime.fromtimestamp(prev['generated_ms'] / 1000, timezone.utc):%Y-%m-%d}); nothing to do")
        return 0
    save_signal(NAME, sig, now_ms * 1000, root)
    print(NAME, json.dumps({"generated_ms": sig["generated_ms"], "weights": sig["weights"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
