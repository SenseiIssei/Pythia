"""Macro, daily: US 2 and 10-year yields, VIX, the dollar index and gold, and a fixed calendar of
FOMC and US CPI release dates for event features. Data only, point in time (lab.collect.pit).

Sources, no key:
  FRED's public CSV (fred.stlouisfed.org/graph/fredgraph.csv?id=..., one request a series,
  at most one every 3 s): DGS2 and DGS10 (Treasury constant maturity, percent; the H.15 values
  of a day appear the next business day in the afternoon, New York time) and VIXCLS (VIX close).
  Yahoo's chart endpoint (query1.finance.yahoo.com/v8/finance/chart, as the lab's ETF studies
  use it, one request a symbol, one every 2 s): DX-Y.NYB (ICE dollar index), GC=F (gold front
  future), ^VIX (VIX, the same day, as a check on FRED's).
Each run continues from what is stored (10 days of overlap; stored values are kept) and the
first run fetches from 2017-01-01. A Yahoo bar is kept once its day has ended in UTC (the job
runs at 00:40 UTC, after the US close).

When a value became known, for backfilled rows (a row stored more than 30 hours after this
time counts as backfilled): FRED, the next weekday at 22:00 UTC; Yahoo, the next day at
00:00 UTC.

Table under $PYTHIA_FREE/macro, long (with ts_us, collected_us, known_us, backfilled):
  daily     ts_us (the day), series, value, source. Series: us2y, us10y, vix (FRED), dxy, gold,
            vix_yahoo (Yahoo)

The calendar is macro_calendar.json next to this file (2017 to 2027, the published schedules,
see its "about"); `calendar_features` turns it into daily event features.

    python -m lab.collect.macro [--dry-run]
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
import urllib.parse
from bisect import bisect_left, bisect_right
from datetime import date, datetime, timedelta
from pathlib import Path

import polars as pl

from . import pit

SOURCE = "macro"
START = date(2017, 1, 1)
OVERLAP_DAYS = 10
FRED = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={}&cosd={}"
YAHOO = "https://query1.finance.yahoo.com/v8/finance/chart/{}?period1={}&period2={}&interval=1d"
FRED_SERIES = {"us2y": "DGS2", "us10y": "DGS10", "vix": "VIXCLS"}
YAHOO_SERIES = {"dxy": "DX-Y.NYB", "gold": "GC=F", "vix_yahoo": "^VIX"}
LIVE_LAG_US = 30 * pit.HOUR_US
COLS = ["series", "value", "source"]
CALENDAR = Path(__file__).with_name("macro_calendar.json")


def parse_fred(text: str) -> dict[date, float]:
    """observation_date (or DATE), value; '.' and empty are missing."""
    rows = list(csv.reader(io.StringIO(text)))
    if not rows or len(rows[0]) < 2 or rows[0][0].lower() not in ("observation_date", "date"):
        raise ValueError(f"FRED: unexpected header {rows[0] if rows else None}")
    out = {}
    for r in rows[1:]:
        if len(r) >= 2 and r[1] not in ("", "."):
            out[date.fromisoformat(r[0])] = float(r[1])
    return out


def parse_yahoo(doc: object) -> dict[date, float]:
    """Daily closes by the exchange's local date."""
    res = ((doc or {}).get("chart") or {}).get("result") if isinstance(doc, dict) else None
    if not res:
        raise ValueError("Yahoo: no chart result")
    r = res[0]
    off = int((r.get("meta") or {}).get("gmtoffset") or 0)
    ts = r.get("timestamp") or []
    closes = ((r.get("indicators") or {}).get("quote") or [{}])[0].get("close") or []
    return {datetime.fromtimestamp(t + off, pit.UTC).date(): float(c) for t, c in zip(ts, closes) if c is not None}


def next_weekday(d: date) -> date:
    d += timedelta(days=1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def published_us(d: date, source: str) -> int:
    """The conservative time a backfilled value of day d became known."""
    if source == "fred":
        return pit.us_of(next_weekday(d)) + 22 * pit.HOUR_US
    return pit.us_of(d + timedelta(days=1))


def frame(series: dict[str, tuple[str, dict[date, float]]], now: int) -> pl.DataFrame:
    today = pit.day_of(now)
    rows = []
    for name, (src, vals) in series.items():
        for d, v in vals.items():
            if src == "yahoo" and d >= today:
                continue  # the day has not ended
            pub = published_us(d, src)
            late = now - pub > LIVE_LAG_US
            rows.append((pit.us_of(d), name, v, src, now, pub if late else now, late))
    return pl.DataFrame(rows, schema={"ts_us": pl.Int64, "series": pl.Utf8, "value": pl.Float64,
                                      "source": pl.Utf8, "collected_us": pl.Int64, "known_us": pl.Int64,
                                      "backfilled": pl.Boolean}, orient="row")


def since(name: str) -> date:
    last = pit.last_ts(SOURCE, "daily", "series", name)
    return START if last is None else max(START, pit.day_of(last) - timedelta(days=OVERLAP_DAYS))


def run(dry: bool = False, fred: pit.Fetch | None = None, yahoo: pit.Fetch | None = None,
        now: int | None = None) -> dict:
    fred = fred or pit.paced(3.0)
    yahoo = yahoo or pit.paced(2.0)
    now = now or pit.now_us()
    errors: dict[str, str] = {}
    series: dict[str, tuple[str, dict[date, float]]] = {}

    def one(name: str, src: str) -> None:
        a = since(name)
        if src == "fred":
            vals = parse_fred(fred(FRED.format(FRED_SERIES[name], a.isoformat()), text=True))
        else:
            sym = urllib.parse.quote(YAHOO_SERIES[name], safe="")
            vals = parse_yahoo(yahoo(YAHOO.format(sym, pit.us_of(a) // 1_000_000, now // 1_000_000)))
        series[name] = (src, {d: v for d, v in vals.items() if d >= a})

    for name in FRED_SERIES:
        pit.step(errors, name, lambda n=name: one(n, "fred"))
    for name in YAHOO_SERIES:
        pit.step(errors, name, lambda n=name: one(n, "yahoo"))
    if series:
        pit.append(SOURCE, "daily", frame(series, now), ["series", "ts_us"], dry)
    tables = {"daily": pit.table_health(SOURCE, "daily", COLS, pit.DAY_US, now, by="series", weekdays_only=True)}
    return pit.write_health(SOURCE, tables, errors, dry)


# ---------------------------------------------------------------------------
# The event calendar
# ---------------------------------------------------------------------------

def calendar(path: Path = CALENDAR) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def calendar_features(days: list[date], cal: dict | None = None) -> pl.DataFrame:
    """Per day: days to the next FOMC statement and CPI release (the schedule as published in
    advance: scheduled and cancelled meetings), days since the last one (what happened: scheduled
    and unscheduled), and whether the day is one. Days to the next are None past the file's end."""
    cal = cal or calendar()
    ahead = sorted(date.fromisoformat(r["date"]) for r in cal["fomc"] if r["kind"] in ("scheduled", "cancelled"))
    held = sorted(date.fromisoformat(r["date"]) for r in cal["fomc"] if r["kind"] in ("scheduled", "unscheduled"))
    cpi = sorted(date.fromisoformat(r["date"]) for r in cal["cpi"])

    def to_next(xs: list[date], d: date) -> int | None:
        i = bisect_left(xs, d)
        return (xs[i] - d).days if i < len(xs) else None

    def since_last(xs: list[date], d: date) -> int | None:
        i = bisect_right(xs, d)
        return (d - xs[i - 1]).days if i else None

    held_set, cpi_set = set(held), set(cpi)
    return pl.DataFrame({
        "day": days,
        "days_to_fomc": [to_next(ahead, d) for d in days], "days_since_fomc": [since_last(held, d) for d in days],
        "fomc_day": [d in held_set for d in days],
        "days_to_cpi": [to_next(cpi, d) for d in days], "days_since_cpi": [since_last(cpi, d) for d in days],
        "cpi_day": [d in cpi_set for d in days]},
        schema={"day": pl.Date, "days_to_fomc": pl.Int64, "days_since_fomc": pl.Int64, "fomc_day": pl.Boolean,
                "days_to_cpi": pl.Int64, "days_since_cpi": pl.Int64, "cpi_day": pl.Boolean})


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true", help="fetch and print counts, write nothing")
    a = ap.parse_args(argv)
    print(f"macro -> {pit.FREE / SOURCE}", flush=True)
    return pit.exit_code(run(a.dry_run)["errors"], len(FRED_SERIES) + len(YAHOO_SERIES))


if __name__ == "__main__":
    sys.exit(main())
