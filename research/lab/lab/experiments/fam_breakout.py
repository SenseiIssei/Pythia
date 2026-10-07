"""Family 3: Donchian / N-day breakout trend following, long-only.

The turtle rule on daily closes: enter when the close is above the highest
close of the previous N days, exit when it falls below the lowest close of the
previous N/2 days. Each entry is sized to 40 % annual vol over the number of
slots and capped at 1/slots, then left to drift until the exit (no daily
resizing, which would only add turnover).

Grid (12 variants):
  coins    BTC and ETH (benchmark BTC), or the 10 most liquid coins of each day
           (a coin can only be entered while it is in the top 10; once in, it
           stays until its own exit signal)
  N        20, 55, 100 days (exit N/2: 10, 27, 50)
  regime   off, or on: no entries and everything sold while BTC is below its
           200-day average
"""

from __future__ import annotations

import itertools

import numpy as np

from . import fam_common as fc

FAMILY = "breakout"
NS = [20, 55, 100]
COIN_VOL = 0.40


def breakout_weights(P: fc.Panel, cols: np.ndarray, allowed: np.ndarray, n: int, slots: int,
                     regime: bool) -> np.ndarray:
    px = P.px[:, cols]
    hi = fc.rolling_extreme(px, n, "max")
    lo = fc.rolling_extreme(px, n // 2, "min")
    with np.errstate(invalid="ignore"):
        enter = (px > hi) & allowed[:, cols]
        leave = (px < lo) | ~P.alive[:, cols]
    with np.errstate(invalid="ignore", divide="ignore"):
        size = np.minimum(COIN_VOL / (P.sigma[:, cols] * np.sqrt(365)) / slots, 1.0 / slots)
    size = np.nan_to_num(size)
    W = np.full((P.T, P.N), np.nan)
    held = np.zeros(len(cols), dtype=bool)
    for t in range(P.T):
        row = np.full(len(cols), np.nan)
        if regime and not P.btc_on[t]:
            row[:] = 0.0
            held[:] = False
        else:
            ex = held & leave[t]
            en = ~held & enter[t] & (size[t] > 0)
            row[ex] = 0.0
            row[en] = size[t, en]
            held = (held & ~ex) | en
        W[t, cols] = row
    W[:, np.setdiff1d(np.arange(P.N), cols)] = 0.0
    return W


def variants(P: fc.Panel) -> list[fc.Result]:
    top10 = P.top_liquid(10)
    ever = np.flatnonzero(top10.any(0))
    majors = np.array([P.col("BTCUSDT"), P.col("ETHUSDT")])
    sets = {"BTC+ETH": (majors, P.eligible, 2, "btc"), "top 10 liquid": (ever, top10, 10, "ew")}
    out = []
    for (sname, (cols, allowed, slots, bench)), n, regime in itertools.product(sets.items(), NS, (False, True)):
        W = breakout_weights(P, cols, allowed, n, slots, regime)
        name = f"Donchian {n}/{n // 2} · {sname}" + (" · regime" if regime else "")
        out.append(fc.run(P, FAMILY, sname, name, W, start=60, benchmark=bench, spot_only=True))
    return out


if __name__ == "__main__":
    from .families import run_one
    run_one(FAMILY)
