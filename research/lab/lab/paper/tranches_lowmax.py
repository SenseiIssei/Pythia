"""EXPERIMENTAL shadow paper book: tsmom_tranches without lottery coins. No real money.

    python -m lab.paper.tranches_lowmax              step the book and write its engine signal
    python -m lab.paper.tranches_lowmax --dry-run    print holdings, flags, signal and evidence; write nothing

Proposed by the xs_factors study (results/crypto_own_prereg.md, results/xs_factors.md):
of 18 factor and book picks, only the MAX filter on tsmom_tranches passed the
registered gates against the book alone (Sharpe and years, drawdown, bootstrap band,
a day late, the survivorship-free twin) and against gated BTC. Its improvement FAILED
deflation, so it runs as an experiment (lab.paper.experimental):

  tsmom_tranches_lowmax   tsmom_tranches' targets (28-day momentum on the 20 most
                          liquid coins of each day, BTC 200-day regime, seven weekly
                          tranches with a 50 % band), except that a coin in the worst
                          third by MAX (its largest daily return over the last 28
                          days) among the 50 most liquid eligible coins that day gets
                          a target of 0. The freed weight stays in cash.

The book is the tranche book of lab.paper.families (same panel, same simulator, same
fills: live Binance touch plus the taker fee, the modelled cost journaled next to
it), so its journal sits next to tsmom_tranches' and the two can be compared day by
day. Engine signal: <data>/signals/tsmom_tranches_lowmax/latest.json, the combined
weights of the seven tranches after the decision close restricted to the engine's
coins, marked experimental and autopilot_only: the engine never runs it on its own,
the auto pick never picks it, and no autopilot runs it until one names
`lab:tsmom_tranches_lowmax` as a sleeve.

The job (research/ops/jobs.yaml, paper-tranches-lowmax) is added disabled.

Per book: <data>/paper/tsmom_tranches_lowmax/state.json and journal.csv
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone

import numpy as np

from ..data import ROOT
from ..experiments import crypto_own as co
from ..experiments import fam_common as fc
from ..experiments import tsmom_tranches as tranches
from ..experiments import xs_factors
from . import experimental as ex
from .families import ENGINE_COINS, SIGNAL_VALID_MS, step_tranches
from .tsmom import live_quotes, save_signal

NAME = "tsmom_tranches_lowmax"


def targets(P: fc.Panel) -> tuple[np.ndarray, np.ndarray]:
    """(the filtered targets, the flags): tsmom_tranches' targets with the MAX worst third at 0."""
    flags = xs_factors.max_flags(P)
    return co.filt(tranches.targets(P), flags), flags


def signal(P: fc.Panel, W: np.ndarray, t: int, now_us: int) -> dict:
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
        "strategy": NAME,
        "variant": ex.BOOKS[NAME]["variant"],
        "as_of_ms": int(P.days[t]) // 1000,
        "generated_ms": now_us // 1000,
        "valid_until_ms": now_us // 1000 + SIGNAL_VALID_MS,
        "quote": "USD",
        "weights": weights,
        "regime_on": bool(P.btc_on[t]),
        "evidence": ex.evidence(NAME),
        "dropped": sorted(dropped),
        "dropped_weight": round(sum(dropped.values()), 6),
        "lab_exposure": round(float(w.sum()), 6),
        "cadence": "daily",
    }
    return ex.mark(sig, NAME)


def main() -> int:
    now_us = time.time_ns() // 1000
    yesterday = (now_us // fc.DAY_US - 1) * fc.DAY_US
    dry = "--dry-run" in sys.argv
    P = fc.load_panel(fresh=True)
    if P.days[-1] < yesterday:
        ends = f"{datetime.fromtimestamp(P.days[-1] / 1e6, timezone.utc):%Y-%m-%d}"
        if not dry:
            print(f"history ends {ends}, yesterday is missing; not rebalancing on stale data", file=sys.stderr)
            return 1
        t = P.T - 1
    else:
        t = int(np.flatnonzero(P.days == yesterday)[0])
    W, flags = targets(P)
    sig = signal(P, W, t, now_us)
    if dry:
        now = tranches.book_weights(P, W, t)
        print(NAME, "BTC above 200d" if P.btc_on[t] else "BTC below 200d",
              json.dumps({P.names[j]: round(float(now[j]), 4) for j in np.flatnonzero(now > 0)}))
        print(NAME, "flagged by MAX today", sorted(fc.base_of(P.names[j]) for j in np.flatnonzero(flags[t])))
        print(NAME, "signal", json.dumps(sig["weights"]), "dropped", sig["dropped"])
        print(NAME, "evidence", json.dumps({k: sig["evidence"].get(k) for k in (
            "oos_sharpe", "book_oos_sharpe", "sharpe_2x_cost", "oos_max_dd", "deflated_p", "verdict", "missing")}))
        return 0
    held = set()
    f = ROOT / "paper" / NAME / "state.json"
    if f.exists():
        st = json.loads(f.read_text())
        held |= {s for w in st.get("tranches", []) for s in w}
    wanted = {P.names[j] for j in np.flatnonzero(np.nan_to_num(W[t], nan=1.0) != 0)}
    quotes = live_quotes(sorted((held | wanted) - {s for s in wanted if "~" in s}))
    print(NAME, json.dumps(step_tranches(P, W, t, quotes, now_us, name=NAME)))
    save_signal(NAME, sig, now_us)
    return 0


if __name__ == "__main__":
    sys.exit(main())
