"""Jupiter's public quote and price API: what a swap would get right now, read only, no key.

  GET lite-api.jup.ag/swap/v1/quote?inputMint&outputMint&amount&slippageBps   ExactIn route
  GET lite-api.jup.ag/price/v3?ids=<mint>,<mint>                               USD prices

The keyless tier allows a few calls a second and says so in x-ratelimit-*
headers. The client paces every call (MIN_INTERVAL apart), retries timeouts,
429 and 5xx up to RETRIES times, waiting what Retry-After or x-ratelimit-reset
asks or else 1, 2, 4 s, and gives up with QuoteError. It never builds, signs or
sends a transaction: there is no call here to /swap.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field

BASE = "https://lite-api.jup.ag"
TIMEOUT = 10.0
RETRIES = 3
MIN_INTERVAL = 1.1      # seconds between calls, under the keyless tier's limit
MAX_WAIT = 30.0         # the longest a rate limit answer may make us wait
SLIPPAGE_BPS = 50       # the quote's tolerance; the paper fill takes outAmount, not the threshold


class QuoteError(RuntimeError):
    pass


@dataclass
class Quote:
    in_mint: str
    out_mint: str
    in_amount: int              # raw units
    out_amount: int             # raw units, what the route delivers before network fees
    price_impact_pct: float     # Jupiter's priceImpactPct as it reports it
    route_fee_bps: float | None  # the AMMs' fees on the route when the API names them (already inside out_amount)
    platform_fee_bps: float
    labels: list[str] = field(default_factory=list)
    slot: int | None = None

    def record(self) -> dict:
        return asdict(self)


def _f(v, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def parse_quote(d: dict) -> Quote:
    """A quote response to a Quote. Route fees are summed over the hops that name a
    fee in their own input or output token, each as a share of that leg weighted by
    the hop's percent (100 for sequential hops, the split share otherwise)."""
    if "outAmount" not in d or "inAmount" not in d:
        raise QuoteError(f"not a quote: {d.get('error') or str(d)[:200]}")
    try:
        return _parse(d)
    except (KeyError, TypeError, ValueError) as e:      # a malformed answer is a failed quote, not a crash
        raise QuoteError(f"not a quote ({type(e).__name__}: {e})") from e


def _parse(d: dict) -> Quote:
    fee, named = 0.0, False
    labels = []
    for hop in d.get("routePlan") or []:
        si = hop.get("swapInfo") or {}
        labels.append(si.get("label") or "?")
        amt, mint = si.get("feeAmount"), si.get("feeMint")
        if amt is None or not mint:
            continue
        base = _f(si.get("inAmount")) if mint == si.get("inputMint") else (
            _f(si.get("outAmount")) if mint == si.get("outputMint") else 0.0)
        if base > 0:
            fee += _f(amt) / base * _f(hop.get("percent"), 100.0) / 100
            named = True
    pf = d.get("platformFee") or {}
    return Quote(in_mint=d["inputMint"], out_mint=d["outputMint"], in_amount=int(d["inAmount"]),
                 out_amount=int(d["outAmount"]), price_impact_pct=_f(d.get("priceImpactPct")),
                 route_fee_bps=round(fee * 1e4, 3) if named else None, platform_fee_bps=_f(pf.get("feeBps")),
                 labels=labels, slot=d.get("contextSlot"))


def _urlopen(url: str, timeout: float) -> tuple[int, dict, bytes]:
    req = urllib.request.Request(url, headers={"User-Agent": "pythia-lab", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers or {}), e.read() or b""


class Jupiter:
    """`fetch(url, timeout) -> (status, headers, body)` replaces the network in tests."""

    def __init__(self, base: str = BASE, timeout: float = TIMEOUT, retries: int = RETRIES,
                 min_interval: float = MIN_INTERVAL, fetch=_urlopen, sleep=time.sleep, clock=time.time):
        self.base, self.timeout, self.retries, self.min_interval = base.rstrip("/"), timeout, retries, min_interval
        self.fetch, self.sleep, self.clock = fetch, sleep, clock
        self.calls = 0
        self._last = -1e18

    def _wait_for(self, headers: dict, attempt: int) -> float:
        h = {k.lower(): v for k, v in headers.items()}
        if h.get("retry-after"):
            return min(_f(h["retry-after"], 1.0), MAX_WAIT)
        if h.get("x-ratelimit-reset"):
            reset = _f(h["x-ratelimit-reset"])
            reset = reset / 1000 if reset > 1e11 else reset     # seconds or ms since the epoch
            if reset > 1e9:
                return min(max(reset - self.clock(), 0.5), MAX_WAIT)
        return float(2 ** attempt)

    def get(self, path: str, params: dict) -> dict:
        url = f"{self.base}{path}?{urllib.parse.urlencode(params)}"
        err = "no attempt"
        for attempt in range(self.retries + 1):
            gap = self._last + self.min_interval - self.clock()
            if gap > 0:
                self.sleep(gap)
            self._last = self.clock()
            self.calls += 1
            try:
                status, headers, body = self.fetch(url, self.timeout)
            except (OSError, TimeoutError) as e:      # URLError, timeouts, resets
                status, headers, body, err = 0, {}, b"", f"{type(e).__name__}: {e}"
            if status == 200:
                try:
                    return json.loads(body)
                except ValueError as e:
                    raise QuoteError(f"{path}: not JSON ({e})") from e
            if status:
                err = f"HTTP {status} {body[:200]!r}"
                if status != 429 and status < 500:
                    raise QuoteError(f"{path}: {err}")      # a bad request does not get better
            if attempt < self.retries:
                self.sleep(self._wait_for(headers, attempt))
        raise QuoteError(f"{path}: gave up after {self.retries + 1} tries ({err})")

    def quote(self, in_mint: str, out_mint: str, amount: int, slippage_bps: int = SLIPPAGE_BPS) -> Quote:
        """Refuses an answer for another pair, another amount or ExactOut: booked, it would fill
        the wrong coin at the wrong decimals or spend more than the account asked to."""
        if amount <= 0:
            raise QuoteError("a quote needs a positive amount")
        d = self.get("/swap/v1/quote", {"inputMint": in_mint, "outputMint": out_mint, "amount": int(amount),
                                        "slippageBps": int(slippage_bps), "swapMode": "ExactIn"})
        q = parse_quote(d)
        if (q.in_mint, q.out_mint, q.in_amount) != (in_mint, out_mint, int(amount)):
            raise QuoteError(f"the quote answers {q.in_amount} {q.in_mint} -> {q.out_mint}, "
                             f"not the {int(amount)} {in_mint} -> {out_mint} asked")
        if d.get("swapMode", "ExactIn") != "ExactIn" or q.out_amount <= 0:
            raise QuoteError(f"not an ExactIn quote with an out amount ({d.get('swapMode')}, {q.out_amount})")
        return q

    def prices(self, mints: list[str]) -> dict[str, float]:
        """USD price per mint; a mint Jupiter has no price for is left out."""
        out: dict[str, float] = {}
        for i in range(0, len(mints), 50):
            d = self.get("/price/v3", {"ids": ",".join(mints[i:i + 50])})
            for m, v in (d or {}).items():
                p = _f((v or {}).get("usdPrice"), 0.0) if isinstance(v, dict) else 0.0
                if p > 0:
                    out[m] = p
        return out
