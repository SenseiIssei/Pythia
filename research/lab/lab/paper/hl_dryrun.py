"""Hyperliquid execution for the M4H book, DRY RUN ONLY: the exact orders a bot would send, never sent.

results/m4h.md passed reg7n at a 230 USD account on Hyperliquid (not confirmed: DSR far below 0.95), so the
study's second step is this module: from the account's positions and the day's target it builds the orders a
Hyperliquid bot would place (coin, side, size rounded to the coin's size decimals, an IOC limit price 1 % through
the mid, reduce-only where it closes or cuts a position) and checks hard limits in code first. It has no key, no
signing and no network call; nothing here can place, sign or send an order or move money. lab.paper.m4_hl_small
runs it every day on its paper account and keeps the orders next to its journal. Going live needs the owner's yes
after at least 30 days of forward record and an API wallet he makes himself, and is not part of this module.

Hard limits (constants, no file or environment variable lifts them):
  account   the equity the book is sized on is at most MAX_ACCOUNT_USD (250 USD); a start above it is refused
  gross     the target's gross notional at most MAX_GROSS (2x) of that equity, else nothing is sent
  stop      at STOP_DRAWDOWN (-20 %) from the start equity: every position closed (reduce-only), stopped for good
            (the caller keeps the flag; only the owner clears it)
  switch    the file GO_FLAT in the book's folder: every position closed, nothing opened while it exists
  minimum   an order under MIN_ORDER_USD (10 USD) is not sent, unless it closes a whole position
"""

from __future__ import annotations

import math
from pathlib import Path

MAX_ACCOUNT_USD = 250.0
MAX_GROSS = 2.0
STOP_DRAWDOWN = 0.20
MIN_ORDER_USD = 10.0
LIMIT_THROUGH = 0.01            # IOC limit 1 % through the mid
PRICE_SIG, PERP_PX_DECIMALS = 5, 6
FLAT_FILE = "GO_FLAT"


def sizing_equity(equity: float) -> float:
    """The equity the book is sized on: the account's, at most MAX_ACCOUNT_USD."""
    return max(0.0, min(float(equity), MAX_ACCOUNT_USD))


def wire(x: float, nd: int) -> str:
    """A number as Hyperliquid's API takes it: nd decimals at most, no trailing zeros."""
    t = f"{x:.{nd}f}"
    return t.rstrip("0").rstrip(".") if "." in t else t


def size_str(units: float, dec: int) -> str:
    return wire(abs(units), dec)


def round_units(units: float, dec: int) -> float:
    return round(units, dec)


def price_str(px: float, dec: int) -> str:
    """Hyperliquid's perp price rule: at most 5 significant figures and at most 6 - szDecimals decimals (an
    integer price is always valid)."""
    if px >= 10 ** PRICE_SIG:
        return str(int(round(px)))
    sig = PRICE_SIG - 1 - int(math.floor(math.log10(px)))
    nd = max(0, min(sig, PERP_PX_DECIMALS - dec))
    return wire(round(px, nd), nd)


def limit_price(mid: float, is_buy: bool, dec: int) -> str:
    return price_str(mid * (1 + LIMIT_THROUGH if is_buy else 1 - LIMIT_THROUGH), dec)


def flat_switch(folder: Path) -> bool:
    return (Path(folder) / FLAT_FILE).exists()


def _order(coin: str, units: float, mid: float, dec: int, reduce_only: bool) -> dict:
    buy = units > 0
    return {"coin": coin, "side": "buy" if buy else "sell", "size": size_str(units, dec),
            "limit_px": limit_price(mid, buy, dec), "tif": "Ioc", "reduce_only": reduce_only,
            "notional_usd": round(abs(units) * mid, 2)}


def plan(positions: dict[str, float], targets: dict[str, float], mids: dict[str, float], decimals: dict[str, int],
         equity: float, start_equity: float, flat: bool = False, stopped: bool = False) -> dict:
    """The orders that take positions (signed units per coin) to targets (signed units), after the limits.

    Returns {"mode": "trade" | "flat" | "stopped" | "refused", "why", "stopped" (the flag to keep), "orders",
    "skipped"}: closes and cuts first (reduce-only), then opens and increases. Nothing is sent."""
    out = {"mode": "trade", "why": "", "stopped": bool(stopped), "orders": [], "skipped": []}
    if not (start_equity > 0) or start_equity > MAX_ACCOUNT_USD:
        return {**out, "mode": "refused", "why": f"start equity {start_equity:.2f} USD is not in (0, "
                f"{MAX_ACCOUNT_USD:.0f}] USD"}
    if stopped or equity <= start_equity * (1 - STOP_DRAWDOWN):
        out.update(mode="stopped", stopped=True, why=f"equity {equity:.2f} USD at or below {1 - STOP_DRAWDOWN:.0%} "
                   f"of the start {start_equity:.2f} USD: flat and stopped")
        targets = {}
    elif flat:
        out.update(mode="flat", why=f"{FLAT_FILE} is set: flat")
        targets = {}
    else:
        gross = sum(abs(u) * mids.get(c, float("nan")) for c, u in targets.items() if u)
        cap = MAX_GROSS * sizing_equity(equity)
        if not math.isfinite(gross) or gross > cap + 1e-9:
            return {**out, "mode": "refused", "why": f"target gross {gross:.2f} USD above {MAX_GROSS:.0f}x the "
                    f"sizing equity ({cap:.2f} USD) or a target without a price: nothing sent"}
    first, then = [], []
    for coin in sorted(set(positions) | set(targets)):
        p = float(positions.get(coin, 0.0))
        mid, dec = mids.get(coin), decimals.get(coin)
        if mid is None or not (mid > 0) or dec is None:
            if p or targets.get(coin):
                out["skipped"].append({"coin": coin, "why": "no price or size decimals"})
            continue
        t = round_units(float(targets.get(coin, 0.0)), dec)
        if abs(t - p) < 0.5 * 10 ** -dec:
            continue
        if p and (t == 0 or (t > 0) != (p > 0)):
            first.append(_order(coin, -p, mid, dec, True))           # a whole close: always sent
            p = 0.0
            if t == 0:
                continue
        delta = t - p
        reduce = p != 0 and abs(t) < abs(p)
        if abs(delta) * mid < MIN_ORDER_USD:
            out["skipped"].append({"coin": coin, "why": f"{abs(delta) * mid:.2f} USD under the "
                                   f"{MIN_ORDER_USD:.0f} USD minimum", "units": round(delta, dec)})
            continue
        (first if reduce else then).append(_order(coin, delta, mid, dec, reduce))
    out["orders"] = first + then
    return out
