"""EXPERIMENT: breakout_top10's rule choosing only among the coins the on-chain wallet can hold.

lab.onchain.book mirrors breakout_top10_live, whose picks are mostly coins
without an SPL version (NEAR on 2026-10-23), so that book sits in cash. This one
runs the same rule, lab.paper.families.breakout_targets (Donchian 20/10 among
the 10 most liquid eligible coins each day, each entry sized to 40 % annual vol
over 10 slots, no regime filter, held until its own exit), with the positions as
the backtest holds them after the close (families.backtest_weights, drifted
since entry), on the same prices: the Binance spot daily panel paper-families
rebuilds each morning (lab.experiments.fam_common.load_panel, read from its
cache in PYTHIA_AGENT_OUT). Its universe is lab.onchain.mints.COINS; a coin of
that list without Binance history in the panel (JUP and POPCAT on 2026-10-23)
is left out and named in the signal's `no_history`. Cash is USDC.

  python -m lab.onchain.sol_book            daily: the targets, then the paper twin through Jupiter
  python -m lab.onchain.sol_book --dry-run  print the targets, write nothing

<data>/signals/onchain_breakout_sol/latest.json  the targets, in the format of the lab's
              signals. The on-chain live service trades them when the ack names the book
              (books=onchain_breakout_sol, docs/ONCHAIN-STAGE2.md). Marked experimental and
              autopilot_only: the exchange engine never runs it.
<data>/paper/onchain_breakout_sol/  the paper twin: lab.onchain.book's files and rules (1,000
              USDC, Jupiter quotes, journal on the 10,000 basis for the forward report)
reports/onchain_sol/  its cost report against Kraken. The per coin probes are the mirror book's.

Nothing here signs, sends or holds a key.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone

import numpy as np

from .. import universe as uni
from ..experiments import fam_common as fc
from ..paper import families as F
from ..paper.tsmom import save_signal
from . import book as B
from . import mints as M
from .jupiter import Jupiter, QuoteError, default_fetch

NAME = B.SOL_NAME
SIGNAL_VALID_MS = F.SIGNAL_VALID_MS


def universe() -> tuple[str, ...]:
    """The coins the book chooses among: every coin with a mint (USDC is the cash)."""
    return tuple(M.COINS)


def targets(P: fc.Panel) -> np.ndarray:
    """(T, N) breakout_top10's weight matrix choosing only among universe()."""
    return F.breakout_targets(P, uni.mask(P, universe()))


def signal(P: fc.Panel, W: np.ndarray, t: int, now_us: int) -> dict:
    """The targets after the close t: what the backtest holds, by coin."""
    w = F.backtest_weights(P, W, t)
    weights = {}
    for j in np.flatnonzero(w > 0):
        coin = fc.base_of(P.names[j])
        if "~" not in P.names[j] and coin in M.COINS and round(float(w[j]), 6) > 0:
            weights[coin] = round(float(w[j]), 6)
    missing = [c["coin"] for c in uni.coverage(P, universe()) if not c["in_panel"]]
    return {
        "strategy": NAME,
        "variant": B.SOL_VARIANT,
        "as_of_ms": int(P.days[t]) // 1000,
        "generated_ms": now_us // 1000,
        "valid_until_ms": now_us // 1000 + SIGNAL_VALID_MS,
        "quote": "USD",
        "weights": weights,
        "regime_on": None,
        "evidence": {"report": "onchain_sol", "missing": True, "experimental": True, "explicit_only": True,
                     "caveat": "breakout_top10's rule among the coins with a Solana mint; forward evidence only"},
        "autopilot_only": True,
        "experimental": True,
        "universe": list(universe()),
        "no_history": missing,
        "dropped": [],
        "dropped_weight": 0.0,
        "lab_exposure": round(float(w.sum()), 6),
        "cadence": "daily",
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    now_us = time.time_ns() // 1000
    yesterday = (now_us // fc.DAY_US - 1) * fc.DAY_US
    P = fc.load_panel()
    if P.days[-1] < yesterday:
        ends = f"{datetime.fromtimestamp(P.days[-1] / 1e6, timezone.utc):%Y-%m-%d}"
        if not a.dry_run:
            print(f"{NAME}: history ends {ends}, yesterday is missing; no new targets", file=sys.stderr)
            return 1
        t = P.T - 1
    else:
        t = int(np.flatnonzero(P.days == yesterday)[0])
    sig = signal(P, targets(P), t, now_us)
    print(f"{NAME}: targets {json.dumps(sig['weights'])}, exposure {sig['lab_exposure']:.4f}"
          + (f", no price history for {', '.join(sig['no_history'])}" if sig["no_history"] else ""))
    if a.dry_run:
        return 0
    save_signal(NAME, sig, now_us)
    client = Jupiter(fetch=default_fetch())
    try:
        row = B.step(client, root=B.WRITE_ROOT, probes=False, name=NAME)
    except QuoteError as e:
        print(f"{NAME}: {e}", file=sys.stderr)
        return 1
    print(f"{NAME}: {json.dumps(row)} ({client.calls} API calls)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
