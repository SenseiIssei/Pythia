"""Polymarket's public read-only endpoints, politely.

  Gamma  https://gamma-api.polymarket.com   market and event metadata, outcomes
  CLOB   https://clob.polymarket.com        price history, order books

No account and no key: every endpoint used here is public market data. The
published limits (docs.polymarket.com, "Rate limits", 2026-10) are per IP and
per 10 seconds: Gamma /markets 300, CLOB /prices-history 1,000, /book 1,500,
/books 500. This client stays far below them on purpose: one shared token
bucket, PYTHIA_PM_RPS requests a second (default 8, about 1 % of the
price-history limit), retries with backoff on 429 and 5xx, and it never
retries a 4xx that says the request itself was wrong.

Standard library only, thread-safe (the history backfill uses a few threads).
"""

from __future__ import annotations

import json
import os
import random
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
UA = "pythia-lab-research (read-only market data)"
PAGE = 100  # the keyset endpoint's maximum


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(f"HTTP {status}: {message}")
        self.status = status


class Bucket:
    """A token bucket shared by all threads: at most `rps` requests a second on average."""

    def __init__(self, rps: float, burst: float | None = None, clock=time.monotonic, sleep=time.sleep):
        self.rps = max(float(rps), 0.1)
        self.cap = float(burst if burst is not None else max(1.0, self.rps))
        self.tokens = self.cap
        self.clock, self.sleep = clock, sleep
        self.last = clock()
        self.lock = threading.Lock()

    def take(self) -> None:
        while True:
            with self.lock:
                now = self.clock()
                self.tokens = min(self.cap, self.tokens + (now - self.last) * self.rps)
                self.last = now
                if self.tokens >= 1.0:
                    self.tokens -= 1.0
                    return
                wait = (1.0 - self.tokens) / self.rps
            self.sleep(wait)


def _fetch(method: str, url: str, body: bytes | None, timeout: float) -> tuple[int, bytes]:
    req = urllib.request.Request(url, data=body, method=method,
                                 headers={"User-Agent": UA, "Accept": "application/json",
                                          **({"Content-Type": "application/json"} if body else {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, (e.read() if hasattr(e, "read") else b"")


class Client:
    """GET and POST JSON with the bucket and retries. `fetch(method, url, body, timeout)
    -> (status, bytes)` replaces the network in tests."""

    def __init__(self, rps: float | None = None, retries: int = 5, timeout: float = 45.0, fetch=None,
                 sleep=time.sleep):
        rps = rps if rps is not None else float(os.environ.get("PYTHIA_PM_RPS", "8"))
        self.bucket = Bucket(rps, sleep=sleep)
        self.retries, self.timeout = retries, timeout
        self.fetch = fetch or _fetch
        self.sleep = sleep
        self.calls = 0
        self.lock = threading.Lock()

    def request(self, method: str, url: str, params: dict | None = None, payload=None):
        if params:
            q = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None}, doseq=True)
            url = f"{url}?{q}"
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        last = "no attempt"
        for attempt in range(self.retries + 1):
            self.bucket.take()
            with self.lock:
                self.calls += 1
            try:
                status, raw = self.fetch(method, url, body, self.timeout)
            except (urllib.error.URLError, OSError, TimeoutError) as e:
                status, raw, last = 0, b"", f"{type(e).__name__}"
            if status == 200:
                try:
                    return json.loads(raw.decode("utf-8") or "null")
                except (ValueError, UnicodeDecodeError) as e:
                    raise ApiError(200, f"unreadable JSON ({e})")
            if status and 400 <= status < 500 and status != 429:
                raise ApiError(status, raw[:300].decode("utf-8", "replace"))
            last = last if status == 0 else f"HTTP {status}"
            if attempt < self.retries:
                self.sleep(min(60.0, (2 ** attempt) * (1.0 + random.random())))
        raise ApiError(0, f"gave up after {self.retries + 1} attempts ({last})")

    def get(self, url: str, params: dict | None = None):
        return self.request("GET", url, params)

    def post(self, url: str, payload):
        return self.request("POST", url, None, payload)

    # ------------------------------------------------------------ Gamma

    def markets(self, closed, **filters):
        """Every market matching the filters, page by page (keyset cursor). Yields dicts.
        `closed` True, False or "any" (any needs an identifier filter such as id)."""
        cur = None
        flag = closed if isinstance(closed, str) else ("true" if closed else "false")
        while True:
            q = {"limit": PAGE, "closed": flag, "include_tag": "true", **filters}
            if cur:
                q["after_cursor"] = cur
            d = self.get(f"{GAMMA}/markets/keyset", q) or {}
            for m in d.get("markets") or []:
                yield m
            cur = d.get("next_cursor")
            if not cur or not d.get("markets"):
                return

    # ------------------------------------------------------------ CLOB

    def history(self, token: str, fidelity: int = 1440, start_s: int | None = None, end_s: int | None = None):
        """[(t_s, p)] for one outcome token. Without start/end: the whole life
        (interval=max; only daily or 12-hour fidelity answers for long markets).
        With them: at most about 15 days at hourly fidelity."""
        q = {"market": token, "fidelity": int(fidelity)}
        if start_s is None:
            q["interval"] = "max"
        else:
            q["startTs"], q["endTs"] = int(start_s), int(end_s)
        d = self.get(f"{CLOB}/prices-history", q) or {}
        out = []
        for h in d.get("history") or []:
            try:
                out.append((int(h["t"]), float(h["p"])))
            except (KeyError, TypeError, ValueError):
                continue
        return out

    def books(self, tokens: list[str]) -> list[dict]:
        """Order books for up to 100 tokens per call."""
        out = []
        for i in range(0, len(tokens), 100):
            chunk = tokens[i:i + 100]
            d = self.post(f"{CLOB}/books", [{"token_id": t} for t in chunk])
            out.extend(d if isinstance(d, list) else [])
        return out
