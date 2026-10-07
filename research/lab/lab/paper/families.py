"""Paper forward tests of two candidates from the strategy-family sweep. No real money.

Neither passed the deflation gate (see results/families_summary.md); they run
so that forward evidence accumulates, labelled as such:

  tsmom_top20     28d time-series momentum on the 20 most liquid coins OF EACH
                  DAY, regime filter, unscaled. The survivorship-free twin of
                  tsmom_regime (which trades today's 20 survivors), so the two
                  journals show what survivorship was worth.     since 2026-10-07
  breakout_top10  Donchian 20/10 on the 10 most liquid coins of each day, no
                  regime. The sweep's most robust family.        since 2026-10-07

Each book's target comes from the SAME weight function the sweep used
(fam_volmom.base_weights, fam_breakout.breakout_weights) on a panel rebuilt
from the history files every run. Fills as in paper/tsmom.py: live Binance
touch plus the 10 bps taker fee, the modelled 15 bps per unit of turnover
journaled next to it.

The universe changes from day to day, so unlike paper/tsmom.py the state keeps
weights and marks per symbol rather than as a fixed vector. Lab-only: no signal
file, the engine already holds tsmom_regime on overlapping coins.

Per book: <data>/paper/<book>/state.json and journal.csv
"""

from __future__ import annotations

import csv
import json
import sys
import time
from datetime import datetime, timezone

import numpy as np

from ..data import ROOT
from ..experiments import fam_breakout, fam_common as fc, fam_volmom
from .tsmom import COST, START_EQUITY, TAKER, live_quotes

BOOKS = {
    "tsmom_top20": "28d · top 20 by volume each day · regime · unscaled (fails deflation, forward evidence only)",
    "breakout_top10": "Donchian 20/10 · top 10 by volume each day (fails deflation, forward evidence only)",
}


def targets(P: fc.Panel) -> dict[str, np.ndarray]:
    """Each book's full weight matrix, exactly as the sweep built it."""
    top10 = P.top_liquid(10)
    cols = np.flatnonzero(top10.any(0))
    return {
        "tsmom_top20": fam_volmom.base_weights(P, 20, regime=True),
        "breakout_top10": fam_breakout.breakout_weights(P, cols, top10, 20, 10, regime=False),
    }


def held_now(W: np.ndarray, t: int) -> np.ndarray:
    """The last decided weight of every column up to day t: what the backtest
    holds going into t, before drift. 0 where nothing was ever decided."""
    fin = np.isfinite(W[: t + 1])
    last = t - np.argmax(fin[::-1], axis=0)
    return np.where(fin.any(0), W[last, np.arange(W.shape[1])], 0.0)


def step(name: str, row_w: np.ndarray, P: fc.Panel, t: int, quotes: dict[str, tuple[float, float]],
         now_us: int, start_row: np.ndarray) -> dict:
    d = ROOT / "paper" / name
    d.mkdir(parents=True, exist_ok=True)
    state_file = d / "state.json"
    if state_file.exists():
        st = json.loads(state_file.read_text())
    else:
        st = {"variant": BOOKS[name], "started": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "equity": START_EQUITY, "weights": {}, "mid": {}}
        # A new book starts where the backtest stands, not flat: breakout only
        # writes a weight on the entry day, so "leave it" would never buy the
        # coins it already holds.
        row_w = np.where(np.isnan(row_w), start_row, row_w)
    equity = st["equity"]
    w: dict[str, float] = {s: float(x) for s, x in st["weights"].items()}
    mid = {s: (b + a) / 2 for s, (b, a) in quotes.items()}

    # Mark to market. A held coin without a live quote (delisted overnight) is
    # closed at its last mark, which is what the backtest does at a series end.
    gone = [s for s in w if s not in mid]
    rets = {s: mid[s] / st["mid"][s] - 1 for s in w if s in mid and st["mid"].get(s)}
    gross = sum(w[s] * r for s, r in rets.items())
    equity *= 1 + gross
    if 1 + gross > 0:
        w = {s: x * (1 + rets.get(s, 0.0)) / (1 + gross) for s, x in w.items()}
    for s in gone:
        w.pop(s)

    # Target: the sweep's row for the decision close. NaN means "leave as it is"
    # (breakout holds until its own exit), so the drifted weight stands.
    tgt: dict[str, float] = {}
    for j in np.flatnonzero(np.isfinite(row_w) & (row_w != 0) | np.isnan(row_w)):
        sym = P.names[j]
        if "~" in sym:          # a dead segment of a reused ticker cannot be traded
            continue
        x = row_w[j]
        x = w.get(sym, 0.0) if np.isnan(x) else float(x)
        if x > 0 and sym in mid:
            tgt[sym] = x
    syms = set(w) | set(tgt)
    delta = {s: tgt.get(s, 0.0) - w.get(s, 0.0) for s in syms}
    half = {s: (quotes[s][1] - quotes[s][0]) / mid[s] / 2 for s in syms if s in quotes}
    paper_cost = sum(abs(x) * (TAKER + half.get(s, 0.0)) for s, x in delta.items())
    model_cost = sum(abs(x) for x in delta.values()) * COST
    equity *= 1 - paper_cost
    # How far the live price had moved from the close the signal used (the sweep fills at that close)
    moved = [(abs(x), mid[s] / P.close[t, P.col(s)] - 1) for s, x in delta.items()
             if x and s in mid and np.isfinite(P.close[t, P.col(s)])]
    timing_bps = sum(a * m for a, m in moved) / max(sum(a for a, _ in moved), 1e-12) * 1e4

    row = {
        "date": datetime.fromtimestamp(now_us / 1e6, timezone.utc).strftime("%Y-%m-%d"),
        "equity": round(equity, 2),
        "gross_ret_pct": round(gross * 100, 4),
        "paper_cost_bps": round(paper_cost * 1e4, 2),
        "model_cost_bps": round(model_cost * 1e4, 2),
        "turnover": round(sum(abs(x) for x in delta.values()), 4),
        "exposure": round(sum(tgt.values()), 4),
        "held": len(tgt),
        "timing_drift_bps": round(timing_bps, 2),
        "weights": json.dumps({s[:-4]: round(x, 4) for s, x in sorted(tgt.items())}),
    }
    journal = d / "journal.csv"
    new = not journal.exists()
    with journal.open("a", newline="") as fh:
        wr = csv.DictWriter(fh, fieldnames=list(row))
        if new:
            wr.writeheader()
        wr.writerow(row)

    st.update(equity=equity, weights=tgt, mid={s: mid[s] for s in tgt})
    state_file.write_text(json.dumps(st, indent=2))
    return row


def main() -> int:
    now_us = time.time_ns() // 1000
    yesterday = (now_us // fc.DAY_US - 1) * fc.DAY_US
    P = fc.load_panel(fresh=True)
    if P.days[-1] < yesterday:
        print(f"history ends {datetime.fromtimestamp(P.days[-1] / 1e6, timezone.utc):%Y-%m-%d}, "
              "yesterday is missing; not rebalancing on stale data", file=sys.stderr)
        return 1
    t = int(np.flatnonzero(P.days == yesterday)[0])
    W = targets(P)
    held = set()
    for name in BOOKS:
        f = ROOT / "paper" / name / "state.json"
        if f.exists():
            held |= set(json.loads(f.read_text())["weights"])
    wanted = {P.names[j] for w in W.values() for j in np.flatnonzero(np.nan_to_num(w[t], nan=1.0) != 0)}
    quotes = live_quotes(sorted((held | wanted) - {s for s in wanted if "~" in s}))

    dry = "--dry-run" in sys.argv
    for name, w in W.items():
        if dry:
            now = held_now(w, t)
            row = {P.names[j]: round(float(now[j]), 4) for j in np.flatnonzero(now > 0)}
            print(name, "BTC above 200d" if P.btc_on[t] else "BTC below 200d", json.dumps(row))
            continue
        print(name, json.dumps(step(name, w[t], P, t, quotes, now_us, held_now(w, t))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
