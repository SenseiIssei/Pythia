"""Family 1: short-term cross-sectional reversal.

Idea (Jegadeesh 1990, Lehmann 1990; in crypto e.g. Liu, Tsyvinski and Wu 2022
find weekly reversal among small coins): last k days' losers bounce, winners
give some back. Rebalanced every k days.

Grid (12 variants):
  lookback k     1, 3, 7 days (holding = k days)
  universe       every eligible coin (60 days old, 1 M USD a day), or the 50 most liquid
  book           long-only: the bottom quintile, equal weight, fully invested (spot)
                 market-neutral: long the bottom quintile, short the top quintile on
                 perpetuals, half the capital per side (needs perps)
"""

from __future__ import annotations

import itertools

import numpy as np

from . import fam_common as fc

FAMILY = "reversal"
LOOKBACK = [1, 3, 7]
UNIVERSES = {"all eligible": None, "top 50 liquid": 50}
QUINTILE = 0.2


def variants(P: fc.Panel) -> list[fc.Result]:
    out = []
    for k, (uname, n), book in itertools.product(LOOKBACK, UNIVERSES.items(), ("long-only", "market-neutral")):
        uni = P.eligible if n is None else P.top_liquid(n)
        past = np.full_like(P.px, np.nan)
        with np.errstate(invalid="ignore", divide="ignore"):
            past[k:] = P.px[k:] / P.px[:-k] - 1
        rk = fc.xs_rank(past, uni & np.isfinite(past))
        losers = np.nan_to_num(rk) > 0
        losers &= rk <= QUINTILE
        if book == "long-only":
            W = fc.equal_weight(losers, 1.0)
        else:
            winners = (rk > 1 - QUINTILE) & P.perp_ok
            W = fc.equal_weight(losers, 0.5) - fc.equal_weight(winners, 0.5)
        name = f"{k}d losers · {uname} · {book}"
        out.append(fc.run(P, FAMILY, book, name, W, fc.every(P, k), start=60))
    return out


if __name__ == "__main__":
    from .families import run_one
    run_one(FAMILY)
