"""Family 7: low volatility and betting against beta in the crypto cross-section.

Frazzini and Pedersen (2014): leverage-constrained investors overpay for high
beta, so low-beta assets earn more per unit of risk. Tested on the most liquid
coins of each day, ranked weekly by
  vol 60d    realised volatility over the last 60 days (from hourly returns)
  beta 90d   beta to BTC over the last 90 daily returns
Books, rebalanced every 7 days:
  long-only         the lowest quintile, equal weight, fully invested (spot)
  dollar-neutral    long the lowest quintile, short the highest on perpetuals,
                    half the capital per side
  beta-neutral BAB  the same legs, each scaled by 1 / its average beta and then
                    normalised to 1x gross: net long in dollars, flat in beta

Grid (12 variants): measure vol / beta x universe top 50 / top 100 x 3 books.
"""

from __future__ import annotations

import itertools

import numpy as np

from . import fam_common as fc

FAMILY = "lowvol"
UNIVERSES = {"top 50": 50, "top 100": 100}
Q = 0.2


def betas(P: fc.Panel, w: int = 90) -> np.ndarray:
    r = P.ret
    b = np.broadcast_to(P.ret[:, [P.btc]], r.shape).copy()
    b = np.where(np.isfinite(r), b, np.nan)
    m = int(w * 0.7)
    mrb = fc.rolling(r * b, w, m)
    mr, mb = fc.rolling(r, w, m), fc.rolling(b, w, m)
    vb = fc.rolling(b * b, w, m) - mb ** 2
    with np.errstate(invalid="ignore", divide="ignore"):
        return (mrb - mr * mb) / vb


BOOKS = ("long-only", "dollar-neutral", "beta-neutral BAB")


def weights(P: fc.Panel, measure: str, n: int, book: str) -> np.ndarray:
    """Target weights (T, N); only rows on rebalance days are used."""
    beta = betas(P)
    score = np.sqrt(fc.rolling(P.extra["rv"], 60, 40)) if measure == "vol 60d" else beta
    uni = P.top_liquid(n) & np.isfinite(score) & np.isfinite(beta)
    rk = fc.xs_rank(score, uni)
    with np.errstate(invalid="ignore"):
        low = uni & (rk <= Q)
        high = uni & (rk > 1 - Q) & P.perp_ok
    if book == "long-only":
        return fc.equal_weight(low, 1.0)
    WL, WS = fc.equal_weight(low, 1.0), fc.equal_weight(high, 1.0)
    if book == "dollar-neutral":
        return 0.5 * WL - 0.5 * WS
    bL = np.nansum(WL * np.nan_to_num(beta), 1)
    bH = np.nansum(WS * np.nan_to_num(beta), 1)
    with np.errstate(invalid="ignore", divide="ignore"):
        aL = np.where(bL > 0.1, 1 / bL, 0.0)
        aH = np.where(bH > 0.1, 1 / bH, 0.0)
        g = aL + aH
        aL, aH = np.where(g > 0, aL / g, 0), np.where(g > 0, aH / g, 0)
    return aL[:, None] * WL - aH[:, None] * WS


def variants(P: fc.Panel) -> list[fc.Result]:
    out = []
    reb = fc.every(P, 7)
    for mname, (uname, n), book in itertools.product(("vol 60d", "beta 90d"), UNIVERSES.items(), BOOKS):
        W = weights(P, mname, n, book)
        sub = "spot long-only" if book == "long-only" else "market-neutral"
        out.append(fc.run(P, FAMILY, sub, f"{mname} · {uname} · {book}", W, reb, start=100,
                          spot_only=book == "long-only"))
    return out


def extra_markdown(P: fc.Panel) -> str:
    """Where did the market-neutral vol books earn their money, year by year?"""
    rows = []
    years = np.array([int(str(np.datetime64(int(d), "us"))[:4]) for d in P.days])
    for book in ("dollar-neutral", "beta-neutral BAB"):
        legs: dict = {}
        g, tv, _, _ = fc.simulate(P, weights(P, "vol 60d", 50, book), fc.every(P, 7), 100, legs)
        net = g - fc.COSTS["15bps"] * np.r_[0.0, tv[:-1]]
        for y in range(2020, years.max() + 1):
            m = years == y
            rows.append({"book": f"vol 60d · top 50 · {book}", "year": y,
                         "long_leg_pct": legs["long"][m].sum() * 100, "short_leg_pct": legs["short"][m].sum() * 100,
                         "funding_pct": legs["funding"][m].sum() * 100,
                         "costs_pct": -(g[m] - net[m]).sum() * 100, "net_pct": net[m].sum() * 100,
                         "sharpe": fc.perf(net[m])["sharpe"]})
    return ("\n## Market-neutral vol books by year (top 50, 15 bps, sums of daily contributions)\n\n"
            "The book is a bet that high-volatility coins (mostly recent listings) fall against the "
            "low-volatility majors. It pays when altcoins bleed (2022, 2024 to 2026: the short leg carries "
            "it) and loses or earns nothing when they rally (2020, 2023: the short leg gives back what the "
            "long leg makes). Funding is a heavy and growing drag: those shorts are crowded, so the shorts "
            "pay. In-sample Sharpe 0.3 to 0.5 against 2 out of sample says the out-of-sample years were the "
            "kind this bet likes, not that the bet got better.\n\n"
            + fc.table(rows, list(rows[0])))


if __name__ == "__main__":
    from .families import run_one
    run_one(FAMILY)
