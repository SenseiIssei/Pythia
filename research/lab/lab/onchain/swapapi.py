"""Jupiter Swap V2 `/build`: a swap's raw instructions for our wallet, read only (docs/ONCHAIN-STAGE2.md, section 1).

  GET <base>/swap/v2/build?inputMint&outputMint&amount&taker&slippageBps&maxAccounts   ExactIn

The answer holds the quote (inAmount, outAmount, otherAmountThreshold, routePlan) and
the instruction groups (computeBudgetInstructions, setupInstructions, swapInstruction,
cleanupInstruction, otherInstructions, tipInstruction) and the lookup tables' addresses.
`parse_build` turns it into txbuild.Ix lists and keeps only the tables' ADDRESSES: their
contents are read from the chain by the executor, never taken from this answer. Jupiter's
compute budget instructions are dropped (the executor sets its own limit and a capped
price; Jupiter's price is kept as a suggestion), and a build with other or tip
instructions is refused (we never ask for them). Nothing here signs or sends; the guard
(guard.py) judges every instruction after the message is compiled.

The keyless tier allows 0.5 calls a second [J4]; with the owner's PYTHIA_JUPITER_API_KEY
(sent as x-api-key, never logged) the client goes to the keyed host.
"""

from __future__ import annotations

import base64
import os
import struct
from dataclasses import dataclass, field

from ..pumpfun_rt import txbuild as X
from .jupiter import Jupiter, QuoteError, parse_quote

KEYLESS_BASE = "https://lite-api.jup.ag"
KEYED_BASE = "https://api.jup.ag"
ENV_KEY = "PYTHIA_JUPITER_API_KEY"
KEYLESS_INTERVAL = 2.1                  # 0.5 calls a second
KEYED_INTERVAL = 1.1
MAX_ACCOUNTS = (48, 40)                 # the second try when the transaction is too large


def client(env=None, **kw) -> Jupiter:
    env = os.environ if env is None else env
    k = (env.get(ENV_KEY) or "").strip()
    return Jupiter(base=KEYED_BASE if k else KEYLESS_BASE, min_interval=KEYED_INTERVAL if k else KEYLESS_INTERVAL,  # gitleaks:allow (constant names, no secret)
                   api_key=k or None, **kw)


@dataclass
class Build:
    in_mint: str
    out_mint: str
    in_amount: int
    out_amount: int
    threshold: int                      # otherAmountThreshold, Jupiter's minimum with its slippage
    slippage_bps: int
    route_mints: list[str]
    labels: list[str]
    price_impact_pct: float
    setup: list[X.Ix]
    swap: X.Ix
    cleanup: list[X.Ix]
    tables: list[str]
    cu_price: int | None = None         # Jupiter's suggested micro-lamports per unit
    cu_limit: int | None = None
    raw: dict = field(default_factory=dict, repr=False)

    def ixs(self) -> list[X.Ix]:
        return self.setup + [self.swap] + self.cleanup


def parse_ix(d) -> X.Ix:
    if not isinstance(d, dict):
        raise QuoteError("an instruction that is not an object")
    try:
        accts = [(str(a["pubkey"]), bool(a.get("isSigner")), bool(a.get("isWritable"))) for a in d["accounts"]]
        return X.Ix(str(d["programId"]), accts, base64.b64decode(d.get("data") or ""))
    except (KeyError, TypeError, ValueError) as e:
        raise QuoteError(f"a malformed instruction ({type(e).__name__})") from e


def _list(v) -> list:
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def parse_build(d: dict) -> Build:
    if not isinstance(d, dict):
        raise QuoteError("not a build answer")
    if d.get("error") or d.get("errorCode"):
        raise QuoteError(f"build refused: {str(d.get('error') or d.get('errorCode'))[:200]}")
    q = d.get("quote") or d.get("quoteResponse") or d
    quote = parse_quote(q)
    if (q.get("swapMode") or "ExactIn") != "ExactIn":
        raise QuoteError("not an ExactIn route")
    mints = []
    for hop in q.get("routePlan") or []:
        si = hop.get("swapInfo") or {}
        for m in (si.get("inputMint"), si.get("outputMint")):
            if m and m not in mints:
                mints.append(m)
    if _list(d.get("otherInstructions")) or _list(d.get("tipInstruction")):
        raise QuoteError("the build carries other or tip instructions; we never ask for them")
    if not d.get("swapInstruction"):
        raise QuoteError("the build has no swap instruction")
    price = limit = None
    for ix in (parse_ix(x) for x in _list(d.get("computeBudgetInstructions"))):
        if ix.program != X.COMPUTE_BUDGET:
            raise QuoteError("a compute budget instruction of another program")
        if ix.data[:1] == b"\x03" and len(ix.data) == 9:
            price = struct.unpack_from("<Q", ix.data, 1)[0]
        elif ix.data[:1] == b"\x02" and len(ix.data) == 5:
            limit = struct.unpack_from("<I", ix.data, 1)[0]
    alts = d.get("addressesByLookupTableAddress")
    tables = list(alts) if isinstance(alts, dict) else [str(t) for t in _list(d.get("addressLookupTableAddresses"))]
    try:
        thr = int(q.get("otherAmountThreshold"))
        slip = int(q.get("slippageBps"))
    except (TypeError, ValueError) as e:
        raise QuoteError("the build has no threshold or slippage") from e
    return Build(quote.in_mint, quote.out_mint, quote.in_amount, quote.out_amount, thr, slip, mints, quote.labels,
                 quote.price_impact_pct, [parse_ix(x) for x in _list(d.get("setupInstructions"))],
                 parse_ix(d["swapInstruction"]), [parse_ix(x) for x in _list(d.get("cleanupInstruction"))],
                 tables, price, limit, d)


def build(jup: Jupiter, in_mint: str, out_mint: str, amount: int, taker: str, slippage_bps: int,
          max_accounts: int = MAX_ACCOUNTS[0]) -> Build:
    """One `/build` for `taker` (our wallet's public address). Checks that the answer is the swap we asked for."""
    if amount <= 0:
        raise QuoteError("a build needs a positive amount")
    b = parse_build(jup.get("/swap/v2/build", {"inputMint": in_mint, "outputMint": out_mint, "amount": int(amount),
                                                "taker": taker, "slippageBps": int(slippage_bps),
                                                "swapMode": "ExactIn", "maxAccounts": int(max_accounts)}))
    if (b.in_mint, b.out_mint, b.in_amount) != (in_mint, out_mint, int(amount)):
        raise QuoteError("the build is not the swap asked for")
    if b.slippage_bps > slippage_bps:
        raise QuoteError("the build carries more slippage than asked")
    return b
