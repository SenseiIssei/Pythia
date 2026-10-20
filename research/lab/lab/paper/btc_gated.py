"""EXPERIMENTAL paper book: BTC held only while it closes above its 200-day average. No real money.

    python -m lab.paper.btc_gated              step the book and write its engine signal
    python -m lab.paper.btc_gated --dry-run    print the gate, the signal and the evidence; write nothing

Proposed by the gated_btc study (results/gated_btc_prereg.md, results/gated_btc.md):
none of the four Alpaca books beat G, BTC at the books' own in-sample risk while its
close is above its 200-day average, with a bootstrap band above zero, and G at full
weight passed the registered gates G1 to G5. It FAILED deflation and its Sharpe from
2024 is below plain BTC's (it halves the drawdown instead), so it runs as an
experiment (lab.paper.experimental, results/experiments.md):

  btc_gated   all of the book in BTC on a close where BTC is above its 200-day
              average (the books' own gate, fam_common's rule), all cash otherwise;
              decided at the daily close, traded at the next run. At full weight
              the position never needs trimming between switches.

The panel is W7's daily-klines builder (lab.experiments.memecoins.build_panel) on
BTCUSDT alone, topped up from Binance's public klines endpoint when the archive has
not published yesterday yet. Paper fills: live Binance touch plus Alpaca's 25 bps
taker fee, the study's 35 bps per unit of turnover journaled next to it. Engine
signal: <data>/signals/btc_gated/latest.json, marked experimental and
autopilot_only, so the engine never runs it on its own, the auto pick never picks
it and no autopilot runs it until one names `lab:btc_gated` as a sleeve.

The job (research/ops/jobs.yaml, paper-btc-gated) is added disabled.

Per book: <data>/paper/btc_gated/state.json and journal.csv
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone

import numpy as np
import polars as pl

from ..experiments import fam_common as fc
from ..experiments import memecoins as w7
from . import experimental as ex
from .families import step
from .memes import rest_days
from .tsmom import live_quotes, save_signal

NAME = "btc_gated"
SYMBOL = "BTCUSDT"
ALPACA_TAKER = 0.0025
MODEL_COST = 0.0035
SIGNAL_VALID_MS = 36 * 3600 * 1000


def load_panel(now_ms: int) -> fc.Panel:
    frames = w7.load_frames((SYMBOL,))
    try:
        top = rest_days(SYMBOL, now_ms)
    except (OSError, ValueError, RuntimeError) as e:
        print(f"  {SYMBOL}: no top-up ({type(e).__name__})", file=sys.stderr)
        top = None
    if top is not None and top.height:
        old = frames.get(SYMBOL, w7.klines_daily.empty())
        frames[SYMBOL] = pl.concat([old, top], how="vertical_relaxed").unique("day", keep="first").sort("day")
    return w7.build_panel(frames)


def targets(P: fc.Panel) -> np.ndarray:
    """(T, 1): 1 on the closes where BTC is above its 200-day average, else 0."""
    W = np.zeros((P.T, P.N))
    W[:, P.btc] = P.btc_on.astype(float)
    return W


def signal(P: fc.Panel, W: np.ndarray, t: int, now_us: int) -> dict:
    x = float(W[t, P.btc])
    sig = {
        "strategy": NAME,
        "variant": ex.BOOKS[NAME]["variant"],
        "as_of_ms": int(P.days[t]) // 1000,
        "generated_ms": now_us // 1000,
        "valid_until_ms": now_us // 1000 + SIGNAL_VALID_MS,
        "quote": "USD",
        "weights": {"BTC": round(x, 6)} if x > 0 else {},
        "regime_on": bool(P.btc_on[t]),
        "evidence": ex.evidence(NAME),
        "dropped": [],
        "dropped_weight": 0.0,
        "lab_exposure": round(x, 6),
        "cadence": "daily",
    }
    return ex.mark(sig, NAME)


def main() -> int:
    now_us = time.time_ns() // 1000
    yesterday = (now_us // fc.DAY_US - 1) * fc.DAY_US
    dry = "--dry-run" in sys.argv
    P = load_panel(now_us // 1000)
    if P.days[-1] < yesterday:
        ends = f"{datetime.fromtimestamp(P.days[-1] / 1e6, timezone.utc):%Y-%m-%d}"
        if not dry:
            print(f"history ends {ends}, yesterday is missing; not rebalancing on stale data", file=sys.stderr)
            return 1
        t = P.T - 1
    else:
        t = int(np.flatnonzero(P.days == yesterday)[0])
    W = targets(P)
    sig = signal(P, W, t, now_us)
    if dry:
        print(NAME, "BTC above 200d" if P.btc_on[t] else "BTC below 200d", json.dumps(sig["weights"]))
        print(NAME, "evidence", json.dumps({k: sig["evidence"].get(k) for k in (
            "oos_sharpe", "sharpe_2x_cost", "oos_max_dd", "deflated_p", "verdict", "missing")}))
        return 0
    quotes = live_quotes([SYMBOL])
    row = step(NAME, W[t], P, t, quotes, now_us, W[t], label=ex.BOOKS[NAME]["variant"],
               taker=ALPACA_TAKER, model=MODEL_COST)
    save_signal(NAME, sig, now_us)
    print(NAME, json.dumps(row))
    return 0


if __name__ == "__main__":
    sys.exit(main())
