"""Kraken's spot fee, the lab's one source (results/kraken_fee_s1_prereg.md). Text in the repo, never downloaded.

Read by the dry run (lab.exec.dryrun.fee_rate), S1's paper books (the way there, lab.paper.smallaccount) and R10's
cost model (lab.experiments.smallaccount_r10.kraken_costs). A share of the order; the tier is the last whose 30-day
USD volume the account reached. A new account pays the first tier: 0.80 % taker on a spot pair.
"""

from __future__ import annotations

URL = "https://www.kraken.com/features/fee-schedule"
READ = "2026-10-28"
# Spot pairs (a coin against EUR or USD): 30-day USD volume, maker %, taker %.
FEE_SCHEDULE = ((0, 0.40, 0.80), (2_500, 0.30, 0.60), (10_000, 0.22, 0.38), (25_000, 0.20, 0.35),
                (50_000, 0.15, 0.30), (100_000, 0.12, 0.25), (250_000, 0.10, 0.22), (500_000, 0.08, 0.20),
                (1_000_000, 0.06, 0.18), (2_500_000, 0.04, 0.15), (5_000_000, 0.02, 0.12), (10_000_000, 0.0, 0.10))
# Stablecoin and FX pairs (USDC/EUR, EUR/USD): the first tier only, a small account never leaves it.
STABLE_SCHEDULE = ((0, 0.20, 0.20),)


def kraken_fee(vol_usd: float = 0.0, maker: bool = False, stable: bool = False, tiers=None) -> float:
    """The fee as a share of the order at a 30-day USD volume. `tiers` [(volume, %)]: a pair's own list from
    AssetPairs when Kraken fills it (the dry run), else the published schedule (spot, or stable)."""
    tiers = tiers or [(v, m if maker else t) for v, m, t in (STABLE_SCHEDULE if stable else FEE_SCHEDULE)]
    tiers = sorted((float(v), float(p)) for v, p in tiers)
    pct = tiers[0][1]
    for v, p in tiers:
        if vol_usd >= v:
            pct = p
    return pct / 100


def source(stable: bool = False) -> str:
    """What the fee is and where it comes from, for a report line."""
    kind = "stablecoin and FX pairs" if stable else "spot pairs"
    return f"Kraken's published fee schedule, {kind}, new-account tier: {URL}, read {READ}"
