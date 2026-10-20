"""SEC EDGAR, keyless: ticker to CIK, filing dates and earnings events (X16 A3).

SEC's fair access policy: a User-Agent that names the requester with a contact
address (PYTHIA_SEC_UA overrides the default), at most 10 requests a second
(this module keeps to 5), and only what is needed. Everything fetched is
cached under <data>/equities/edgar/ and fetched again only when asked
(`refresh`) or when a cached company file is older than `max_age_days`.

  company_tickers.json               SEC's current ticker -> CIK list
  submissions/CIK##########.json     a company's filing index (recent part)
  submissions/CIK##########-submissions-NNN.json   older pages
  events.parquet                     (ticker, cik, date, kind) earnings events

Ticker to CIK: the current list, then the dataset's renames (old -> new
ticker). Index members with neither have no CIK, so no events: mostly the
names that left the index (acquired or dead). Coverage per year is reported
by the study; the PEAD book is also held against the equal weight of the
members that have a CIK, which share that survivorship.

Earnings events: every 8-K with item 2.02 (results of operations), or item 12
before 2004-08-23, on its filing date; and every 10-Q or 10-K with no such
8-K in the 60 days before it, on its own filing date.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np

from ..experiments import equities_ranking as er

UA = os.environ.get("PYTHIA_SEC_UA", "Pythia research lab superwarper@t-online.de")
TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/{}"
MIN_INTERVAL = 0.2           # seconds between requests: 5 a second at most
ITEM_202_FROM = "2004-08-23"
QUARTERLY_LOOKBACK_DAYS = 60
FIRST_MEMBER_END = np.datetime64("2004-01-01")


def cache_dir() -> Path:
    return er.CACHE / "edgar"


class Client:
    """Polite GETs: one at a time, MIN_INTERVAL apart, retries on 429 and 5xx with backoff."""

    def __init__(self, ua: str = UA, min_interval: float = MIN_INTERVAL, opener=None, sleep=time.sleep):
        self.ua, self.min_interval, self.sleep = ua, min_interval, sleep
        self.opener = opener or urllib.request.urlopen
        self.last = 0.0
        self.requests = 0

    def get(self, url: str, tries: int = 4) -> bytes | None:
        """The body, or None for a 404 (a CIK without that page)."""
        for k in range(tries):
            wait = self.min_interval - (time.monotonic() - self.last)
            if wait > 0:
                self.sleep(wait)
            self.last = time.monotonic()
            self.requests += 1
            req = urllib.request.Request(url, headers={"User-Agent": self.ua, "Accept-Encoding": "identity"})
            try:
                with self.opener(req, timeout=60) as r:
                    return r.read()
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    return None
                if e.code in (403, 429, 500, 502, 503, 504) and k + 1 < tries:
                    self.sleep(2.0 * (k + 1) ** 2)
                    continue
                raise er.DataUnavailable(f"EDGAR {url}: HTTP {e.code}") from e
            except OSError as e:
                if k + 1 < tries:
                    self.sleep(2.0 * (k + 1))
                    continue
                raise er.DataUnavailable(f"EDGAR {url}: {e}") from e
        return None


def _fresh(p: Path, max_age_days: float | None) -> bool:
    if not p.exists():
        return False
    if max_age_days is None:
        return True
    return (time.time() - p.stat().st_mtime) < max_age_days * 86400


def ticker_map(client: Client, refresh: bool = False) -> dict[str, int]:
    """Current ticker -> CIK from SEC (dots as dashes, BRK.B -> BRK-B, the dataset's form)."""
    f = cache_dir() / "company_tickers.json"
    if refresh or not f.exists():
        body = client.get(TICKERS_URL)
        if not body:
            raise er.DataUnavailable("EDGAR company_tickers.json: empty")
        json.loads(body)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(body)
    d = json.loads(f.read_text(encoding="utf-8"))
    out: dict[str, int] = {}
    for v in d.values():
        t = str(v["ticker"]).upper().replace(".", "-")
        out.setdefault(t, int(v["cik_str"]))
    return out


def renames(refresh: bool = False, get=er.fetch) -> dict[str, str]:
    """The dataset's renames.csv (old ticker -> new), cached next to the price file."""
    f = er.CACHE / "renames.csv"
    if refresh or not f.exists():
        try:
            blob = get("renames.csv")
        except er.DataUnavailable:
            return {}
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(blob)
    out = {}
    for line in f.read_text(encoding="utf-8").splitlines()[1:]:
        p = line.strip().split(",")
        if len(p) >= 2 and p[0] and p[1]:
            out[p[0].strip().upper()] = p[1].strip().upper()
    return out


def cik_for(ticker: str, tickers: dict[str, int], ren: dict[str, str]) -> int | None:
    """A member's CIK. Suffixed tickers (AAL-199702: a recycled symbol's earlier owner) never
    match the current owner of the symbol."""
    t = ticker.upper().replace(".", "-")
    if t in tickers:
        return tickers[t]
    seen = set()
    while t in ren and t not in seen:
        seen.add(t)
        t = ren[t]
        if t in tickers:
            return tickers[t]
    return None


def submissions(client: Client, cik: int, max_age_days: float | None = 7.0) -> list[dict]:
    """Every filing of a company as dicts (form, filingDate, acceptanceDateTime, items),
    the recent part and every older page, from the cache when fresh enough."""
    d = cache_dir() / "submissions"
    d.mkdir(parents=True, exist_ok=True)
    name = f"CIK{cik:010d}.json"
    f = d / name
    if not _fresh(f, max_age_days):
        body = client.get(SUBMISSIONS_URL.format(name))
        if body is None:
            return []
        f.write_bytes(body)
    top = json.loads(f.read_text(encoding="utf-8"))
    filings = top.get("filings") or {}
    tables = [filings.get("recent") or {}]
    for page in filings.get("files") or []:
        pf = d / page["name"]
        if not pf.exists():               # older pages never change
            body = client.get(SUBMISSIONS_URL.format(page["name"]))
            if body is None:
                continue
            pf.write_bytes(body)
        tables.append(json.loads(pf.read_text(encoding="utf-8")))
    out = []
    for t in tables:
        forms = t.get("form") or []
        n = len(forms)
        dates = t.get("filingDate") or [""] * n
        acc = t.get("acceptanceDateTime") or [""] * n
        items = t.get("items") or [""] * n
        for i in range(n):
            out.append({"form": forms[i], "filingDate": dates[i], "acceptanceDateTime": acc[i],
                        "items": items[i] if i < len(items) else ""})
    return out


def _is_earnings_8k(f: dict) -> bool:
    if f["form"] != "8-K":
        return False
    items = {x.strip() for x in str(f.get("items") or "").split(",") if x.strip()}
    if "2.02" in items:
        return True
    return f["filingDate"] < ITEM_202_FROM and "12" in items


def earnings_events(filings: list[dict]) -> list[tuple[str, str]]:
    """(filing date, kind) of every earnings event: 8-K 2.02 (12 before 2004-08-23), and a
    10-Q or 10-K without such an 8-K in the 60 days before it."""
    eights = sorted({f["filingDate"] for f in filings if f.get("filingDate") and _is_earnings_8k(f)})
    out = [(d, "8-K") for d in eights]
    e8 = np.array(eights, dtype="datetime64[D]") if eights else np.array([], dtype="datetime64[D]")
    for f in filings:
        if f["form"] not in ("10-Q", "10-K") or not f.get("filingDate"):
            continue
        d = np.datetime64(f["filingDate"])
        lo = d - np.timedelta64(QUARTERLY_LOOKBACK_DAYS, "D")
        if e8.size and ((e8 >= lo) & (e8 <= d)).any():
            continue
        out.append((f["filingDate"], f["form"]))
    return sorted(set(out))


def build_events(S, refresh: bool = False, client: Client | None = None, max_age_days: float | None = 7.0,
                 log=print) -> dict:
    """Earnings events of every member whose membership ends after 2004 and that has a CIK.
    Returns {"events": [(ticker, cik, date, kind)], "cik": {ticker: cik}, "requests": n},
    cached as events.parquet; `refresh` refetches the company files."""
    import polars as pl
    client = client or Client()
    out_f = cache_dir() / "events.parquet"
    tick = ticker_map(client, refresh)
    ren = renames(refresh)
    end_member = np.array([S.dates[np.flatnonzero(S.member[:, j])[-1]] if S.member[:, j].any() else S.dates[0]
                           for j in range(S.N)])
    want = {S.names[j]: cik_for(S.names[j], tick, ren) for j in range(S.N) if end_member[j] >= FIRST_MEMBER_END}
    cik = {k: v for k, v in want.items() if v is not None}
    rows = []
    for i, (t, c) in enumerate(sorted(cik.items())):
        try:
            fl = submissions(client, c, 0.0 if refresh else max_age_days)
        except er.DataUnavailable as e:
            log(f"edgar: {t} ({c}) skipped: {e}")
            continue
        for d, kind in earnings_events(fl):
            rows.append((t, c, d, kind))
        if (i + 1) % 100 == 0:
            log(f"edgar: {i + 1} of {len(cik)} companies, {client.requests} requests")
    frame = pl.DataFrame(rows, schema=["ticker", "cik", "date", "kind"], orient="row")
    out_f.parent.mkdir(parents=True, exist_ok=True)
    frame.write_parquet(out_f)
    return {"events": rows, "cik": cik, "wanted": len(want), "requests": client.requests}


def load_events(S, refresh: bool = False, client: Client | None = None, offline: bool = False) -> dict:
    """The cached events (built when missing). `offline`: only the cache, else empty."""
    import polars as pl
    f = cache_dir() / "events.parquet"
    if f.exists() and not refresh:
        fr = pl.read_parquet(f)
        rows = list(fr.iter_rows())
        cik = {r[0]: int(r[1]) for r in rows}
        return {"events": rows, "cik": cik, "wanted": None, "requests": 0}
    if offline:
        return {"events": [], "cik": {}, "wanted": None, "requests": 0}
    return build_events(S, refresh, client, log=lambda m: print(m, file=sys.stderr, flush=True))


def event_matrix(S, events: list[tuple]) -> tuple[np.ndarray, np.ndarray]:
    """(T, N) bool: the first trading day on or after each event's filing date (window
    start), and (N,) bool: the member has a CIK."""
    col = {s: j for j, s in enumerate(S.names)}
    start = np.zeros((S.T, S.N), dtype=bool)
    has = np.zeros(S.N, dtype=bool)
    for t, _c, d, _k in events:
        j = col.get(t)
        if j is None:
            continue
        has[j] = True
        i = np.searchsorted(S.dates, np.datetime64(str(d)[:10], "D"))
        if i < S.T:
            start[i, j] = True
    return start, has
