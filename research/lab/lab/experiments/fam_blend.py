"""Family 8: dual momentum, trend + carry, and plain cross-sectional momentum.

  dual momentum   (Antonacci) each week, among the 50 most liquid coins, hold the
                  K with the best L-day return, but only those whose return is
                  positive (absolute momentum) AND above BTC's over the same
                  L days (relative momentum), while BTC is above its 200-day
                  average. Each coin sized to 40 % vol over K, capped at 100 %.
                  K 5 / 10 x L 28 / 56: 4 variants, spot long-only.
  trend + carry   the volmom base book (28-day trend, 20 most liquid, vol-sized,
                  daily) without the coins whose 7-day funding is in the top
                  third of the universe that day: trend where the longs are not
                  already crowded. With and without the regime filter: 2
                  variants, spot long-only.
  XS momentum L/S the no-model baseline for the market-neutral ranking book:
                  long the top quintile of the 50 most liquid coins by L-day
                  return, short the bottom quintile on perpetuals, weekly, half
                  the capital per side. L 28 / 56: 2 variants.
"""

from __future__ import annotations

import itertools

import numpy as np

from . import fam_common as fc
from .fam_volmom import base_weights

FAMILY = "blend"


def past_ret(P: fc.Panel, L: int) -> np.ndarray:
    out = np.full_like(P.px, np.nan)
    with np.errstate(invalid="ignore", divide="ignore"):
        out[L:] = P.px[L:] / P.px[:-L] - 1
    return out


def variants(P: fc.Panel) -> list[fc.Result]:
    out = []
    uni50 = P.top_liquid(50)
    weekly = fc.every(P, 7)
    for K, L in itertools.product((5, 10), (28, 56)):
        pr = past_ret(P, L)
        btc = pr[:, [P.btc]]
        with np.errstate(invalid="ignore"):
            ok = uni50 & np.isfinite(pr) & (pr > 0) & (pr > btc)
        score = np.where(ok, pr, -np.inf)
        rank = np.argsort(np.argsort(-score, axis=1), axis=1)
        held = ok & (rank < K)
        W = fc.vol_sized(P, held, 0.40, K) * P.btc_on[:, None]
        out.append(fc.run(P, FAMILY, "dual momentum", f"dual momentum · top {K} by {L}d · top 50 · regime", W,
                          weekly, start=60))
    f7 = fc.rolling(np.where(P.perp_ok, P.funding, np.nan), 7, 5, how="sum")
    for regime in (False, True):
        top20 = P.top_liquid(20)
        frk = fc.xs_rank(f7, top20 & np.isfinite(f7))
        crowded = np.nan_to_num(frk, nan=0) > 2 / 3
        W = base_weights(P, 20, regime)
        W = np.where(crowded, 0.0, W)
        out.append(fc.run(P, FAMILY, "trend + carry", "tsmom 28d · top 20 · not crowded by funding"
                          + (" · regime" if regime else ""), W, start=60))
    for L in (28, 56):
        pr = past_ret(P, L)
        rk = fc.xs_rank(pr, uni50 & np.isfinite(pr))
        with np.errstate(invalid="ignore"):
            win = uni50 & (rk > 0.8)
            lose = uni50 & (rk <= 0.2) & P.perp_ok
        W = 0.5 * fc.equal_weight(win) - 0.5 * fc.equal_weight(lose)
        out.append(fc.run(P, FAMILY, "XS momentum L/S", f"XS momentum {L}d · top 50 · quintiles · weekly", W,
                          weekly, start=60, spot_only=False))
    return out


if __name__ == "__main__":
    from .families import run_one
    run_one(FAMILY)
