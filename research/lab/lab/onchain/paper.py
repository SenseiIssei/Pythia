"""The paper executor: a swap filled at Jupiter's quoted out amount, minus what Solana charges to land it.

Per swap Solana takes the base fee (5,000 lamports for the one signature) and
the priority fee we would bid (PYTHIA_ONCHAIN_PRIORITY_SOL, default 0.0001 SOL).
The paper account holds no SOL, so the fee is taken out of what the swap
delivers, converted at the quote's own price: a buy of N USDC gets the quoted
coin amount less the fee's worth of the coin, a sale gets the quoted USDC less
the fee. The rent a new token account locks (about 0.002 SOL, given back when
the account is closed) is not a cost and is not charged.

Every fill keeps its quote and two costs, both with the network fees, both
comparable to a Kraken fill's taker fee plus half spread:
  cost_bps      half the round trip: the received amount quoted straight back
                (route fees, price impact and the pools' spread both ways, halved)
                plus this swap's network fees. The honest one; costs a second quote.
  mid_cost_bps  against Jupiter's USD price read in the same run. That price comes
                from the same pools and moves a few bps either way of the fill,
                so a single value can be below zero.
Without the second quote (roundtrip=False, or it fails) cost_bps is the mid cost.
Nothing here signs or sends.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass

from . import mints as M
from .jupiter import Jupiter, QuoteError

BASE_FEE_SOL = 0.000005
PRIORITY_SOL = 0.0001


def priority_sol(env: dict | None = None) -> float:
    env = os.environ if env is None else env
    try:
        v = float(env.get("PYTHIA_ONCHAIN_PRIORITY_SOL", PRIORITY_SOL))
    except ValueError:
        return PRIORITY_SOL
    return v if 0 <= v <= 0.01 else PRIORITY_SOL


@dataclass
class Fill:
    side: str            # buy (USDC into the coin) or sell
    coin: str
    usdc: float          # USDC paid (buy) or received after the fee (sell)
    units: float         # coin units received after the fee (buy) or sold
    fee_sol: float
    fee_usdc: float
    cost_bps: float | None       # half the round trip plus the network fees (see above)
    mid_cost_bps: float | None   # against Jupiter's price, network fee included; None without a price
    quote: dict

    def record(self) -> dict:
        return asdict(self)


class PaperExecutor:
    """`prices` are Jupiter's USD prices by mint for this run (SOL's turns the fee into USDC)."""

    def __init__(self, client: Jupiter, prices: dict[str, float], priority: float | None = None,
                 roundtrip: bool = True):
        self.client, self.prices, self.roundtrip = client, prices, roundtrip
        self.fee_sol = BASE_FEE_SOL + (priority_sol() if priority is None else priority)

    def _mid(self, m: M.Mint) -> float | None:
        p, u = self.prices.get(m.mint), self.prices.get(M.USDC.mint)
        return p / u if p and u else None          # in USDC

    def fee_usdc(self) -> float:
        return self.fee_sol * (self._mid(M.SOL) or 0.0)

    def _half_roundtrip(self, q, fee_bps: float, fallback: float | None) -> float | None:
        if not self.roundtrip:
            return fallback
        try:
            back = self.client.quote(q.out_mint, q.in_mint, q.out_amount)
        except QuoteError:
            return fallback
        return (1 - back.out_amount / q.in_amount) / 2 * 1e4 + fee_bps

    def buy(self, coin: str, usdc: float) -> Fill:
        m = M.COINS[coin]
        q = self.client.quote(M.USDC.mint, m.mint, M.raw(M.USDC, usdc))
        paid, got = M.ui(M.USDC, q.in_amount), M.ui(m, q.out_amount)
        fee = self.fee_usdc()
        units = max(got - (fee * got / paid if paid > 0 else 0.0), 0.0)
        mid = self._mid(m)
        cost = (1 - units * mid / paid) * 1e4 if mid and paid > 0 else None
        rt = self._half_roundtrip(q, fee / paid * 1e4 if paid > 0 else 0.0, cost)
        return Fill("buy", coin, paid, units, self.fee_sol, fee, rt, cost, q.record())

    def sell(self, coin: str, units: float) -> Fill:
        m = M.COINS[coin]
        q = self.client.quote(m.mint, M.USDC.mint, M.raw(m, units))
        sold, got = M.ui(m, q.in_amount), M.ui(M.USDC, q.out_amount)
        fee = self.fee_usdc()
        usdc = max(got - fee, 0.0)
        mid = self._mid(m)
        cost = (1 - usdc / (sold * mid)) * 1e4 if mid and sold > 0 else None
        rt = self._half_roundtrip(q, fee / got * 1e4 if got > 0 else 0.0, cost)
        return Fill("sell", coin, usdc, sold, self.fee_sol, fee, rt, cost, q.record())
