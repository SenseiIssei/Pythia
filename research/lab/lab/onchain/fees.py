"""The priority fee for stage 2's own swaps (docs/ONCHAIN-STAGE2.md, section 5; docs/LATENCY.md): from the
recent prioritization fees of the accounts the swap writes, capped. Read only: it is handed a reader for
getRecentPrioritizationFees and builds, signs and sends nothing. Stage 1 (paper.py) keeps its fixed fee.

    fee = FeeCache(lambda accounts: rpc.call("getRecentPrioritizationFees", [accounts]))
    micro, lamports = fee.get(writable_accounts, units)

The percentile is the 50th (what Jupiter's /build calls "high"), at least FLOOR_MICRO, and the total priority
fee of one transaction never above MAX_PRIORITY_SOL (0.0005 SOL, the design's cap).

The cheapest path (a book with "cheap" in lab.onchain.book.BOOKS, onchain_longterm; speed does not matter
there): cheap_price bids the CHEAP_PCTS[attempt - 1] percentile of the same fees, at least FLOOR_MICRO, each
new attempt (a blockhash that passed without landing, live_exec.MAX_ATTEMPTS) at least CHEAP_STEP x the last,
and the transaction's priority fee never above CHEAP_MAX_PRIORITY_L (0.00002 SOL a swap).
"""

from __future__ import annotations

import time

LAMPORTS = 1_000_000_000
MAX_PRIORITY_SOL = 0.0005
PCT = 50
FLOOR_MICRO = 1_000                 # micro-lamports per compute unit
EVERY_S = 10.0
CHEAP_MAX_PRIORITY_L = 20_000       # 0.00002 SOL a swap on the cheapest path
CHEAP_PCTS = (25, 50, 75)           # the percentile bid on the first, second and third attempt
CHEAP_STEP = 1.5                    # a new attempt bids at least this much over the last one


def from_fees(rows, units: int, pct: int = PCT, cap_sol: float = MAX_PRIORITY_SOL) -> tuple[int, int]:
    """(micro-lamports per compute unit, the transaction's priority fee in lamports) from the rows of
    getRecentPrioritizationFees: the pct percentile of the non-zero fees, at least the floor, and the total at most
    cap_sol (never above MAX_PRIORITY_SOL)."""
    units = max(1, int(units))
    cap_sol = min(max(0.0, cap_sol), MAX_PRIORITY_SOL)
    fees = sorted(int(r.get("prioritizationFee") or 0) for r in rows or [] if isinstance(r, dict))
    fees = [f for f in fees if f > 0]
    micro = FLOOR_MICRO
    if fees:
        micro = max(micro, fees[min(len(fees) - 1, int(round((len(fees) - 1) * pct / 100)))])
    micro = min(micro, int(cap_sol * LAMPORTS * 1_000_000 // units))
    return micro, micro * units // 1_000_000


class FeeCache:
    """The estimate per set of accounts, read again when older than every_s; a failed read keeps the last one
    (or the floor)."""

    def __init__(self, read, every_s: float = EVERY_S, clock=time.monotonic, cap_sol: float = MAX_PRIORITY_SOL):
        self.read, self.every, self.clock, self.cap = read, every_s, clock, cap_sol
        self.hits: dict[tuple, tuple[float, list]] = {}

    def get(self, accounts: list[str], units: int) -> tuple[int, int]:
        k = tuple(sorted(set(accounts)))[:128]
        hit = self.hits.get(k)
        if hit is None or self.clock() - hit[0] >= self.every:
            try:
                hit = (self.clock(), list(self.read(list(k)) or []))
            except Exception:
                hit = (self.clock(), hit[1] if hit else [])
            self.hits[k] = hit
        return from_fees(hit[1], units, cap_sol=self.cap)


def cheap_price(rows, units: int, attempt: int = 1, prev_micro: int | None = None) -> tuple[int, int]:
    """The cheapest path's (micro-lamports per compute unit, priority fee in lamports) for this attempt: the
    attempt's percentile of the recent fees (the floor without any), at least CHEAP_STEP x the last attempt's
    price, the total at most CHEAP_MAX_PRIORITY_L (and so far below MAX_PRIORITY_SOL)."""
    pct = CHEAP_PCTS[min(max(attempt, 1), len(CHEAP_PCTS)) - 1]
    cap = CHEAP_MAX_PRIORITY_L / LAMPORTS
    micro, _ = from_fees(rows, units, pct, cap_sol=cap)
    if prev_micro:
        micro = max(micro, int(prev_micro * CHEAP_STEP))
    units = max(1, int(units))
    micro = min(micro, CHEAP_MAX_PRIORITY_L * 1_000_000 // units)
    return micro, micro * units // 1_000_000
