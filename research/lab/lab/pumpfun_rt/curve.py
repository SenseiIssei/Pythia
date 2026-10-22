"""Bonding curve and pool arithmetic, and the execution model of every paper fill.

Units: lamports (1e-9 SOL) and raw token units (pump.fun tokens have 6
decimals). Prices are SOL per whole token.

The bonding curve is a constant product on VIRTUAL reserves (vs, vt): a buy
of n lamports into the curve gets vt * n / (vs + n) tokens, a sale of k tokens
pays vs * k / (vt + k) lamports. pump.fun charges its fee on top of a buy and
off the proceeds of a sale; the fee is what the token's own trades show
(protocol plus creator basis points, 95 + 30 at the time of writing, so 1.25 %
a side), DEFAULT_FEE_BPS when no trade shows it yet. The trades' recorded
reserves are the curve AFTER each trade (checked against consecutive trades:
the virtual SOL reserve moves by exactly the trade's SOL amount).

PumpSwap pools are a constant product on the base vault and the EFFECTIVE
quote reserves (the quote vault plus the pool's signed virtual_quote_reserves,
effective_quote); their events carry both BEFORE the trade (also checked).
Fees there are the LP, protocol and creator basis points of the pool's trades.

The execution model (we are not first):

  * Our order lands LATENCY after the signal: a lognormal draw with median
    LAT_MEDIAN_MS, clipped to [LAT_LO_MS, LAT_HI_MS] (400 ms to 3 s by
    default, what an ordinary RPC sender sees; nothing here models Jito
    bundles or co-location). The draw is seeded by the rule, the token and
    the leg, so a replay is reproducible.
  * It fills at the curve state after every trade received BEFORE the landing
    time, through the curve arithmetic above (so slippage is the curve's),
    pays the fee, a base fee and PRIORITY_SOL of priority fee per
    transaction. Our own trade does not move the recorded curve: buying and
    later selling into an unmoved curve charges the price impact twice, which
    errs against us.
  * A buy fails (only the transaction fee is lost) if the price at landing is
    more than SLIP_TOL above the price at the signal, or the curve completed
    before it landed.
  * A sale always fills, at whatever the curve or the pool pays at landing:
    if the creator or the top holders dumped before our sale landed, that is
    what we get, often next to nothing. A curve that completed before our sale
    landed is sold into the PumpSwap pool it migrated to (its recorded state,
    else the reserves the migration moved).
  * Token account rent (about 0.002 SOL) is assumed refunded when the account
    is closed after the sale, so it is not a cost.
"""

from __future__ import annotations

import hashlib
import math
import os
from dataclasses import dataclass

LAMPORTS = 1_000_000_000
TOKEN_UNIT = 1_000_000
DEFAULT_FEE_BPS = 125
BASE_FEE_LAMPORTS = 5_000
PRIORITY_SOL = float(os.environ.get("PYTHIA_PF_PRIORITY_SOL", "0.001"))
LAT_MEDIAN_MS = float(os.environ.get("PYTHIA_PF_LAT_MEDIAN_MS", "1000"))
LAT_LO_MS = float(os.environ.get("PYTHIA_PF_LAT_LO_MS", "400"))
LAT_HI_MS = float(os.environ.get("PYTHIA_PF_LAT_HI_MS", "3000"))
LAT_SIGMA = 0.5
SLIP_TOL = 0.30
INITIAL_RT = 793_100_000 * TOKEN_UNIT          # real tokens on a fresh curve (the token's own create row wins)


@dataclass(frozen=True)
class Costs:
    """The execution assumptions; the study's robustness checks double or triple them."""
    lat_median_ms: float = LAT_MEDIAN_MS
    lat_lo_ms: float = LAT_LO_MS
    lat_hi_ms: float = LAT_HI_MS
    priority_sol: float = PRIORITY_SOL
    slip_tol: float = SLIP_TOL
    fee_bps_floor: int = 0                     # a floor on the observed fee (a stress case sets one)

    def tx_lamports(self) -> int:
        return BASE_FEE_LAMPORTS + int(self.priority_sol * LAMPORTS)

    def latency(self, *key) -> float:
        """A reproducible latency draw in ms for this key."""
        h = hashlib.blake2b(repr(key).encode(), digest_size=8).digest()
        u = (int.from_bytes(h, "big") + 0.5) / 2 ** 64
        z = _norm_ppf(u)
        ms = self.lat_median_ms * math.exp(LAT_SIGMA * z)
        return min(self.lat_hi_ms, max(self.lat_lo_ms, ms))

    def scaled(self, latency: float = 1.0, priority: float = 1.0) -> "Costs":
        return Costs(self.lat_median_ms * latency, self.lat_lo_ms * latency, self.lat_hi_ms * latency,
                     self.priority_sol * priority, self.slip_tol, self.fee_bps_floor)


def _norm_ppf(p: float) -> float:
    """Inverse normal CDF (Acklam's rational approximation, plenty for a latency draw)."""
    a = (-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02, 1.383577518672690e+02,
         -3.066479806614716e+01, 2.506628277459239e+00)
    b = (-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02, 6.680131188771972e+01,
         -1.328068155288572e+01)
    c = (-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00, -2.549671010422189e+00,
         4.374664141464968e+00, 2.938163982698783e+00)
    d = (7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00, 3.754408661907416e+00)
    lo = 0.02425
    if p < lo:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
               ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    if p > 1 - lo:
        return -_norm_ppf(1 - p)
    q = p - 0.5
    r = q * q
    return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / \
           (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)


# ---------------------------------------------------------------- curve

def price(vs: float, vt: float) -> float:
    """SOL per whole token on a curve or pool with these reserves (lamports, raw tokens)."""
    if vt <= 0:
        return 0.0
    return (vs / LAMPORTS) / (vt / TOKEN_UNIT)


def curve_buy(lamports_in: int, vs: int, vt: int, rt: int, fee_bps: int) -> int:
    """Tokens a buy spending `lamports_in` (fee included) gets from the curve; at most what is left (rt)."""
    if lamports_in <= 0 or vs <= 0 or vt <= 0 or rt <= 0:
        return 0
    net = lamports_in / (1 + fee_bps / 10_000)
    return int(min(rt, vt * net / (vs + net)))


def curve_sell(tokens: int, vs: int, vt: int, fee_bps: int) -> int:
    """Lamports a sale of `tokens` gets from the curve, after the fee."""
    if tokens <= 0 or vs <= 0 or vt <= 0:
        return 0
    gross = vs * tokens / (vt + tokens)
    return int(gross * (1 - fee_bps / 10_000))


def effective_quote(vault: int, virtual: int | None) -> int:
    """A PumpSwap pool's effective quote reserves, what every pool price uses: the quote vault's balance
    plus Pool::virtual_quote_reserves, a signed sum (negative while fees kept by v2 trades wait in the
    vault, positive on a boosted pool). pump.fun guarantees it is never below zero; clipped all the same."""
    return max(0, int(vault) + int(virtual or 0))


def pool_buy(lamports_in: int, base: int, quote: int, fee_bps: int) -> int:
    if lamports_in <= 0 or base <= 0 or quote <= 0:
        return 0
    net = lamports_in / (1 + fee_bps / 10_000)
    return int(base * net / (quote + net))


def pool_sell(tokens: int, base: int, quote: int, fee_bps: int) -> int:
    if tokens <= 0 or base <= 0 or quote <= 0:
        return 0
    return int(quote * tokens / (base + tokens) * (1 - fee_bps / 10_000))


def progress(rt: int, rt0: int = INITIAL_RT) -> float:
    """How much of the curve's sellable tokens are gone (1.0 = complete)."""
    if rt0 <= 0:
        return 0.0
    return max(0.0, min(1.0, 1 - rt / rt0))
