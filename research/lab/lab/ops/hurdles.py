"""The outside numbers the real money readiness check holds an autopilot against.

  inflation  the latest year-over-year consumer price change, from two keyless
             public sources, and the higher of the two:
               US CPI (FRED series CPIAUCSL, fredgraph.csv): the last month
               against the same month a year before;
               euro area HICP (Eurostat prc_hicp_minr, annual rate of change,
               all items): the owner lives in the euro area.
  sp500      the S&P 500 index by day (FRED series SP500, fredgraph.csv), for
             the "what would a plain index fund have made over the same days"
             line. A price index without dividends, so it slightly understates
             what an ETF paid; shown for information only, no rule reads it.

Everything is fetched at most once a day and cached in
<data>/readiness/macro.json. When a source does not answer, its last cached
value is used and marked as such; a source that never answered is missing.
Nothing here needs a key, and nothing is sent anywhere: plain GETs.
"""

from __future__ import annotations

import csv
import io
import json
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from ..data import ROOT
from . import guard

US_CPI_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=CPIAUCSL"
EA_HICP_URL = ("https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/prc_hicp_minr"
               "?geo=EA&unit=RCH_A&coicop18=TOTAL&lastTimePeriod=3")
SP500_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=SP500"
# Days of S&P 500 closes kept in the cache: enough for any autopilot's period.
SP500_KEEP_DAYS = 800
DAY_MS = 86_400_000

Fetch = Callable[[str], str]


def cache_path() -> Path:
    return ROOT / "readiness" / "macro.json"


def fetch_text(url: str, timeout: float = 20) -> str:
    req = urllib.request.Request(url, method="GET", headers={"User-Agent": "pythia-lab/1 (readiness check)"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def _date(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%d")


def fred_rows(text: str) -> list[tuple[str, float]]:
    """(date, value) rows of a fredgraph.csv; missing values (".") are skipped."""
    out = []
    for row in csv.reader(io.StringIO(text)):
        if len(row) < 2 or not row[0][:1].isdigit():
            continue
        try:
            out.append((row[0], float(row[1])))
        except ValueError:
            continue
    out.sort()
    return out


def us_cpi_yoy(text: str) -> dict | None:
    """The last month's CPI against the same month a year before, in %."""
    rows = dict(fred_rows(text))
    if not rows:
        return None
    last = max(rows)
    y, m = int(last[:4]), last[5:7]
    before = f"{y - 1}-{m}-01"
    if before not in rows or rows[before] <= 0:
        return None
    return {"pct": round((rows[last] / rows[before] - 1) * 100, 2), "month": last[:7],
            "source": "US CPI (FRED CPIAUCSL)"}


def ea_hicp_yoy(text: str) -> dict | None:
    """The newest annual rate of change in a Eurostat JSON-stat answer, in %."""
    d = json.loads(text)
    times = (((d.get("dimension") or {}).get("time") or {}).get("category") or {}).get("index") or {}
    values = d.get("value") or {}
    best = None
    for month, i in times.items():
        v = values.get(str(i)) if isinstance(values, dict) else (values[i] if i < len(values) else None)
        if v is not None and (best is None or month > best[0]):
            best = (month, float(v))
    if best is None:
        return None
    return {"pct": round(best[1], 2), "month": best[0], "source": "euro area HICP (Eurostat)"}


def _load_cache() -> dict:
    try:
        return json.loads(cache_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _refresh(name: str, url: str, parse, cache: dict, now_ms: int, fetch: Fetch) -> dict | None:
    """Today's value of one source, fetched once a day; the cached one when
    the source fails (marked cached), None when there never was one."""
    old = cache.get(name)
    if old and old.get("fetched_date") == _date(now_ms):
        return old
    try:
        v = parse(fetch(url))
        if v is None:
            raise ValueError("no usable value in the answer")
        v.update(fetched_ms=now_ms, fetched_date=_date(now_ms), cached=False)
        return v
    except Exception as e:  # noqa: BLE001 - a source being down is reported, the cache stands in
        if old:
            return {**old, "cached": True, "error": f"{type(e).__name__}: {e}"[:200]}
        return None


def load(now_ms: int | None = None, fetch: Fetch = fetch_text) -> dict:
    """{"inflation": {...}, "sp500": [(date, close), ...]} with the cache updated."""
    now_ms = now_ms or int(time.time() * 1000)
    cache = _load_cache()
    us = _refresh("us_cpi", US_CPI_URL, us_cpi_yoy, cache, now_ms, fetch)
    ea = _refresh("ea_hicp", EA_HICP_URL, ea_hicp_yoy, cache, now_ms, fetch)

    def parse_sp(text: str) -> dict | None:
        rows = fred_rows(text)[-SP500_KEEP_DAYS:]
        return {"closes": rows, "source": "S&P 500 index (FRED SP500, price only)"} if rows else None

    sp = _refresh("sp500", SP500_URL, parse_sp, cache, now_ms, fetch)
    new = {k: v for k, v in (("us_cpi", us), ("ea_hicp", ea), ("sp500", sp)) if v is not None}
    if new != cache:
        guard.write_json(cache_path(), new)
    return {"inflation": inflation(us, ea), "sp500": sp}


def inflation(us: dict | None, ea: dict | None) -> dict:
    """The higher of the two figures, and which one it was."""
    have = [x for x in (us, ea) if x and isinstance(x.get("pct"), (int, float))]
    if not have:
        return {"pct": None, "source": None, "month": None, "cached": None, "us": us and _slim(us),
                "ea": ea and _slim(ea)}
    top = max(have, key=lambda x: x["pct"])
    return {"pct": top["pct"], "source": top["source"], "month": top["month"], "cached": bool(top.get("cached")),
            "us": us and _slim(us), "ea": ea and _slim(ea)}


def _slim(x: dict) -> dict:
    return {k: x.get(k) for k in ("pct", "month", "source", "cached", "fetched_date")}


def index_return(sp: dict | None, start_ms: int, end_ms: int) -> float | None:
    """The S&P 500's change over [start, end] in %: last close on or before each day."""
    rows = (sp or {}).get("closes") or []
    if not rows:
        return None
    a, b = _date(start_ms), _date(end_ms)

    def close_on(day: str):
        best = None
        for d, v in rows:
            if d <= day:
                best = v
            else:
                break
        return best

    c0, c1 = close_on(a), close_on(b)
    if not c0 or not c1 or rows[0][0] > a:
        return None
    return (c1 / c0 - 1) * 100
