"""EXPERIMENTAL shadow paper books: tsmom_tranches with one coin filter each. No real money.

    python -m lab.paper.tranches_filtered              step both books and write their engine signals
    python -m lab.paper.tranches_filtered --dry-run    print holdings, flags, signals and evidence; write nothing
    python -m lab.paper.tranches_filtered --only tsmom_tranches_lowmax

Proposed by two studies registered together (results/crypto_own_prereg.md). Each filter
passed the registered gates on tsmom_tranches against the book alone (Sharpe and years,
drawdown, bootstrap band, a day late, the survivorship-free twin) and against gated BTC,
and each improvement FAILED deflation, so both run as experiments
(lab.paper.experimental):

  tsmom_tranches_lowmax   xs_factors: a coin in the worst third by MAX (its largest
                          daily return over the last 28 days) among the 50 most liquid
                          eligible coins that day gets a target of 0.
  tsmom_tranches_lowkr    kr_premium_xs: a coin in the worst third by its own Korean
                          premium (Upbit against Binance, minus BTC's, 7-day mean)
                          among the coins on both gets a target of 0. Upbit's history is
                          today's survivors, so this one is forward evidence only; it
                          needs the flow collector's upbit_all source (flow-collect).

Otherwise each is the tranche book of lab.paper.families (tsmom_tranches' targets, its
simulator, its fills: live Binance touch plus the taker fee, the modelled cost journaled
next to it); the freed weight stays in cash. Their journals sit next to tsmom_tranches'
and can be compared day by day. Engine signals: <data>/signals/<book>/latest.json, the
combined weights of the seven tranches after the decision close restricted to the
engine's coins, marked experimental and autopilot_only: the engine never runs them on
their own, the auto pick never picks them, and no autopilot runs one until it names
`lab:tsmom_tranches_lowmax` or `lab:tsmom_tranches_lowkr` as a sleeve.

The job (research/ops/jobs.yaml, paper-tranches-filtered) is added disabled.

Per book: <data>/paper/<book>/state.json and journal.csv
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from typing import Callable

import numpy as np

from ..data import ROOT
from ..experiments import crypto_own as co
from ..experiments import fam_common as fc
from ..experiments import kr_premium_xs
from ..experiments import tsmom_tranches as tranches
from ..experiments import xs_factors
from . import experimental as ex
from .families import ENGINE_COINS, SIGNAL_VALID_MS, step_tranches
from .tsmom import live_quotes, save_signal

FILTERS: dict[str, Callable[[fc.Panel], np.ndarray]] = {
    "tsmom_tranches_lowmax": xs_factors.max_flags,
    "tsmom_tranches_lowkr": kr_premium_xs.kr_flags,
}


def targets(P: fc.Panel, name: str) -> tuple[np.ndarray, np.ndarray]:
    """(the filtered targets, the flags): tsmom_tranches' targets with the flagged coins at 0."""
    flags = FILTERS[name](P)
    return co.filt(tranches.targets(P), flags), flags


def signal(name: str, P: fc.Panel, W: np.ndarray, t: int, now_us: int) -> dict:
    w = tranches.book_weights(P, W, t)
    weights: dict[str, float] = {}
    dropped: dict[str, float] = {}
    for j in np.flatnonzero(w > 0):
        sym, x = P.names[j], float(w[j])
        coin = fc.base_of(sym)
        if "~" not in sym and coin in ENGINE_COINS:
            if round(x, 6) > 0:
                weights[coin] = round(x, 6)
        else:
            label = sym[:-4] if "~" not in sym else sym
            dropped[label] = dropped.get(label, 0.0) + x
    sig = {
        "strategy": name,
        "variant": ex.BOOKS[name]["variant"],
        "as_of_ms": int(P.days[t]) // 1000,
        "generated_ms": now_us // 1000,
        "valid_until_ms": now_us // 1000 + SIGNAL_VALID_MS,
        "quote": "USD",
        "weights": weights,
        "regime_on": bool(P.btc_on[t]),
        "evidence": ex.evidence(name),
        "dropped": sorted(dropped),
        "dropped_weight": round(sum(dropped.values()), 6),
        "lab_exposure": round(float(w.sum()), 6),
        "cadence": "daily",
    }
    return ex.mark(sig, name)


def main() -> int:
    now_us = time.time_ns() // 1000
    yesterday = (now_us // fc.DAY_US - 1) * fc.DAY_US
    dry = "--dry-run" in sys.argv
    names = list(FILTERS)
    if "--only" in sys.argv:
        i = sys.argv.index("--only")
        names = [n for n in sys.argv[i + 1].split(",") if n in FILTERS] if i + 1 < len(sys.argv) else []
        if not names:
            print(f"--only needs one of {', '.join(FILTERS)}", file=sys.stderr)
            return 2
    P = fc.load_panel(fresh=True)
    if P.days[-1] < yesterday:
        ends = f"{datetime.fromtimestamp(P.days[-1] / 1e6, timezone.utc):%Y-%m-%d}"
        if not dry:
            print(f"history ends {ends}, yesterday is missing; not rebalancing on stale data", file=sys.stderr)
            return 1
        t = P.T - 1
    else:
        t = int(np.flatnonzero(P.days == yesterday)[0])
    failed = 0
    for name in names:
        try:
            W, flags = targets(P, name)
        except (OSError, ValueError) as e:      # e.g. the Upbit file is missing: the other book still runs
            print(f"{name}: skipped ({type(e).__name__}: {e})", file=sys.stderr)
            failed += 1
            continue
        sig = signal(name, P, W, t, now_us)
        if dry:
            now = tranches.book_weights(P, W, t)
            print(name, "BTC above 200d" if P.btc_on[t] else "BTC below 200d",
                  json.dumps({P.names[j]: round(float(now[j]), 4) for j in np.flatnonzero(now > 0)}))
            print(name, "flagged today", sorted(fc.base_of(P.names[j]) for j in np.flatnonzero(flags[t])))
            print(name, "signal", json.dumps(sig["weights"]), "dropped", sig["dropped"])
            print(name, "evidence", json.dumps({k: sig["evidence"].get(k) for k in (
                "oos_sharpe", "book_oos_sharpe", "sharpe_2x_cost", "oos_max_dd", "deflated_p", "verdict",
                "missing")}))
            continue
        held = set()
        f = ROOT / "paper" / name / "state.json"
        if f.exists():
            st = json.loads(f.read_text())
            held |= {s for w in st.get("tranches", []) for s in w}
        wanted = {P.names[j] for j in np.flatnonzero(np.nan_to_num(W[t], nan=1.0) != 0)}
        quotes = live_quotes(sorted((held | wanted) - {s for s in wanted if "~" in s}))
        print(name, json.dumps(step_tranches(P, W, t, quotes, now_us, name=name)))
        save_signal(name, sig, now_us)
    return 1 if failed == len(names) else 0


if __name__ == "__main__":
    sys.exit(main())
