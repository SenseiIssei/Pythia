"""Shared by the four perp studies registered together on 2026-10-21 from the strategy
survey (funding_carry, trend_shorts, flush_long, kraken_funding_gap): costs, the pool
they count into, the bootstrap seed and the Kraken Futures listing.

The pool: 1,140 hand trials after polymarket (1,124 before it plus its 16) at the
variance backed out of the published bar (377 trials at 2.43, as every hand study
since C16), the factory ledger's in-sample Sharpes, and the 37 trials registered
today (funding_carry 13, trend_shorts 12, flush_long 8, kraken_funding_gap 4), each
study's own at its own variance. 1,777 with the 600 genomes of the factory ledger.
"""

from __future__ import annotations

import json
import math
import urllib.request

import numpy as np

from . import director_common as dc
from . import fam_common as fc

HAND_TRIALS = 1140
TODAY_TRIALS = 37         # funding_carry 13 + trend_shorts 12 + flush_long 8 + kraken_funding_gap 4
SEED = 20261021

# Per unit of one-way turnover. Judged: Kraken Futures taker 5 bps plus 5 bps of
# half-spread (median half-spread of the 50th to 100th most traded PF perps 4.5 bps
# on 2026-10-21). Stress doubles it; 41 bps is the lab's earlier perp level; 0 is a
# zero-fee maker with no spread and no adverse selection, an upper bound only.
JUDGED, STRESS, LEGACY, MAKER0 = 0.0010, 0.0020, 0.0041, 0.0
COSTS = {"0bps": MAKER0, "10bps": JUDGED, "20bps": STRESS, "41bps": LEGACY}
ALPACA_TAKER = 0.0035

KRAKEN_INSTRUMENTS = "https://futures.kraken.com/derivatives/api/v3/instruments"
ALIASES = {"XBT": "BTC", "MATIC": "POL"}
MULTIPLIERS = ("1000000", "100000", "10000", "1000", "1M")


def pool(mine_annual: list[float]) -> dict:
    """The pooled per-day variance of trial Sharpes and the trial count (1,777).
    mine_annual: this study's trial Sharpes (annual); they stand for all 37 of today's trials."""
    v1, n1 = dc.prior_var(), HAND_TRIALS
    fx = np.clip(dc.factory_sharpes(), -fc.SR_CLIP, fc.SR_CLIP) / math.sqrt(dc.YEAR)
    n2, v2 = len(fx), float(np.var(fx)) if len(fx) > 1 else 0.0
    x = np.clip(np.array(mine_annual, dtype=float), -fc.SR_CLIP, fc.SR_CLIP) / math.sqrt(dc.YEAR)
    v3 = float(np.var(x)) if len(x) > 1 else v1
    n3 = TODAY_TRIALS
    n = n1 + n2 + n3
    v = (n1 * v1 + n2 * v2 + n3 * v3) / n
    return {"hand_trials": n1, "factory_trials": n2, "today_trials": n3, "mine": len(x), "n_total": n,
            "var": v, "sr0_annual": fc._sr0(v, n) * math.sqrt(dc.YEAR)}


def boot(x: np.ndarray, y: np.ndarray | None = None) -> tuple[float, float, float]:
    return dc.boot_band(np.asarray(x, dtype=float), None if y is None else np.asarray(y, dtype=float), seed=SEED)


def coin_of(symbol: str) -> str:
    """The coin a Binance symbol or segment names: 1000PEPEUSDT -> PEPE, LUNAUSDT~0 -> LUNA,
    MATICUSDT -> POL."""
    s = symbol.split("~")[0].upper()
    if s.endswith("USDT"):
        s = s[:-4]
    for p in MULTIPLIERS:
        if s.startswith(p) and len(s) > len(p):
            s = s[len(p):]
            break
    return ALIASES.get(s, s)


def kraken_listing(timeout: float = 30.0) -> dict[str, str]:
    """{coin: symbol} of the PF_ perpetuals Kraken Futures trades today (public, no key).
    Empty when the endpoint does not answer: the Kraken-listed rows are information only."""
    try:
        with urllib.request.urlopen(KRAKEN_INSTRUMENTS, timeout=timeout) as r:
            ans = json.loads(r.read().decode())
    except Exception:  # noqa: BLE001 - information only
        return {}
    out: dict[str, str] = {}
    for ins in ans.get("instruments") or []:
        sym = str(ins.get("symbol", ""))
        if not sym.startswith("PF_") or ins.get("tradeable") is not True or ins.get("suspended", False):
            continue
        base = ins.get("base") or (sym[3:-3] if sym.endswith("USD") else "")
        if base:
            out.setdefault(ALIASES.get(base, base), sym)
    return out
