"""Binance USD-M futures daily metrics for the liquid perpetuals, keyless, from data.binance.vision.

    python -m lab.collect.um_metrics [--panel PATH] [--since 2021-12-01] [--top 120] [--dry-run]

Registered for `positioning_xs` (results/positioning_xs_prereg.md). Binance publishes one
zip a day per perpetual with a row every five minutes (open interest, the top traders'
long/short account and position ratios, the all-accounts ratio, the taker buy/sell
volume ratio), from 2021-12-01 for most symbols. The recorder's backfill keeps the raw
rows only for the 20 lab coins; this keeps one row per symbol and UTC day for every
perpetual that ranked among the `--top` most liquid eligible perps of the `xs_daily`
panel on any day since `--since`, from 100 days before its first such day (the history
the study's z-scores need) to its last.

Per symbol and day (rows whose timestamp falls inside the UTC day; the snapshot
stamped 00:00 belongs to the day it opens, as in `xs_daily.perp_daily`):

  oi_value     open interest in USD, last snapshot of the day
  oi           open interest in contracts, last snapshot
  top_acct     mean log of the top traders' long/short account ratio
  top_pos      mean log of the top traders' long/short position ratio
  all_acct     mean log of the all-accounts long/short ratio
  taker        mean log of the taker buy/sell volume ratio
  n            snapshots that day (0: Binance has no file for the day)

Written to <data>/flow/um_metrics/<SYMBOL>.parquet; a run fetches only the days a
symbol's file does not have yet. Polite: one GET a file (the zip's own CRC is checked),
at most RATE requests a second over WORKERS threads, retries with backoff on 429, 5xx
and dropped connections. Public data only; nothing here can trade.
"""

from __future__ import annotations

import argparse
import http.client
import io
import math
import os
import sys
import threading
import time
import urllib.error
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import polars as pl

from ..data import ROOT
from .flow import FLOW

BASE = "https://data.binance.vision/data/futures/um/daily/metrics/{s}/{s}-metrics-{d}.zip"
UA = "pythia-lab um metrics collector (research, public archive)"
RATE = 25.0
WORKERS = 10
LEAD_DAYS = 100
FIRST_DAY = date(2021, 12, 1)
DAY_US = 86_400_000_000
COLS = ("oi_value", "oi", "top_acct", "top_pos", "all_acct", "taker")
SCHEMA = {"day_us": pl.Int64, **{c: pl.Float64 for c in COLS}, "n": pl.Int32}


def out_dir() -> Path:
    return FLOW / "um_metrics"


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

class Pacer:
    """At most `rate` requests a second across threads."""

    def __init__(self, rate: float):
        self.gap = 1.0 / rate
        self.lock = threading.Lock()
        self.next = 0.0

    def wait(self) -> None:
        with self.lock:
            now = time.monotonic()
            t = max(now, self.next)
            self.next = t + self.gap
        if t > now:
            time.sleep(t - now)


def get_zip(url: str, pacer: Pacer, tries: int = 6) -> bytes | None:
    """The first file of the zip at url, or None for a 404."""
    last: Exception | None = None
    for k in range(tries):
        pacer.wait()
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                blob = r.read()
            with zipfile.ZipFile(io.BytesIO(blob)) as z:
                name = z.namelist()[0]
                return z.read(name)            # raises on a bad CRC
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            last = e
            if e.code != 429 and e.code < 500 and e.code != 403:
                raise
            time.sleep(float(e.headers.get("Retry-After") or 0) or min(60.0, 2.0 ** k))
        except (OSError, http.client.HTTPException, zipfile.BadZipFile) as e:
            last = e
            time.sleep(min(60.0, 2.0 ** k))
    raise RuntimeError(f"{url}: no answer after {tries} tries ({last})")


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def _log_mean(x: pl.Series) -> float:
    v = x.cast(pl.Float64, strict=False).to_numpy()
    v = v[np.isfinite(v) & (v > 0)]
    return float(np.log(v).mean()) if len(v) else math.nan


def day_row(raw: bytes | None, day: date) -> dict:
    """One row for `day` from the raw CSV of its metrics file (n = 0 when there is none)."""
    d_us = int(datetime(day.year, day.month, day.day, tzinfo=timezone.utc).timestamp() * 1e6)
    row = {"day_us": d_us, **{c: math.nan for c in COLS}, "n": 0}
    if not raw:
        return row
    t = pl.read_csv(io.BytesIO(raw), infer_schema_length=0)
    if "create_time" not in t.columns or t.is_empty():
        return row
    ts = t["create_time"].str.strptime(pl.Datetime("us"), "%Y-%m-%d %H:%M:%S", strict=False).dt.epoch("us")
    t = t.with_columns(ts_us=ts).filter(pl.col("ts_us").is_not_null()
                                        & ((pl.col("ts_us") // DAY_US) * DAY_US == d_us)).sort("ts_us")
    if t.is_empty():
        return row
    last = t.tail(1)

    def lastf(c: str) -> float:
        try:
            v = float(last[c][0])
            return v if math.isfinite(v) else math.nan
        except (KeyError, TypeError, ValueError):
            return math.nan

    row.update(oi_value=lastf("sum_open_interest_value"), oi=lastf("sum_open_interest"),
               top_acct=_log_mean(t["count_toptrader_long_short_ratio"]) if "count_toptrader_long_short_ratio" in t.columns else math.nan,
               top_pos=_log_mean(t["sum_toptrader_long_short_ratio"]) if "sum_toptrader_long_short_ratio" in t.columns else math.nan,
               all_acct=_log_mean(t["count_long_short_ratio"]) if "count_long_short_ratio" in t.columns else math.nan,
               taker=_log_mean(t["sum_taker_long_short_vol_ratio"]) if "sum_taker_long_short_vol_ratio" in t.columns else math.nan,
               n=int(t.height))
    return row


# ---------------------------------------------------------------------------
# Plan and storage
# ---------------------------------------------------------------------------

def plan(panel: pl.DataFrame, since: date, top: int, until: date) -> dict[str, tuple[date, date]]:
    """{perp symbol: (first day, last day)}: perps that ranked among the `top` most liquid
    eligible perps (28-day perp volume) on some day from `since`, from LEAD_DAYS before
    their first such day (not before FIRST_DAY) to their last such day (to `until` while
    still ranked within the last 7 days)."""
    s_us = int(datetime(since.year, since.month, since.day, tzinfo=timezone.utc).timestamp() * 1e6)
    p = (panel.filter(pl.col("eligible") & pl.col("perp").is_not_null() & pl.col("perp_adv28").is_not_null())
         .select("day", "perp", "perp_adv28")
         .with_columns(rk=pl.col("perp_adv28").rank("ordinal", descending=True).over("day"))
         .filter((pl.col("rk") <= top) & (pl.col("day") >= s_us)))
    if p.is_empty():
        return {}
    end = int(p["day"].max())
    g = p.group_by("perp").agg(a=pl.col("day").min(), b=pl.col("day").max())
    out = {}
    for sym, a, b in g.iter_rows():
        first = max(FIRST_DAY, datetime.fromtimestamp(a / 1e6, timezone.utc).date() - timedelta(days=LEAD_DAYS))
        last = until if b >= end - 7 * DAY_US else datetime.fromtimestamp(b / 1e6, timezone.utc).date()
        if first <= last:
            out[str(sym)] = (first, last)
    return dict(sorted(out.items()))


def read_symbol(sym: str) -> pl.DataFrame:
    f = out_dir() / f"{sym}.parquet"
    return pl.read_parquet(f) if f.exists() else pl.DataFrame(schema=SCHEMA)


def save_symbol(sym: str, new: list[dict]) -> None:
    old = read_symbol(sym)
    df = pl.DataFrame(new, schema=SCHEMA) if new else pl.DataFrame(schema=SCHEMA)
    df = pl.concat([old, df], how="vertical_relaxed").unique("day_us", keep="last").sort("day_us")
    d = out_dir()
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / f"{sym}.tmp"
    df.write_parquet(tmp)
    os.replace(tmp, d / f"{sym}.parquet")


def todo(sym: str, first: date, last: date) -> list[date]:
    have = set(read_symbol(sym)["day_us"].to_list())
    out, d = [], first
    while d <= last:
        if int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp() * 1e6) not in have:
            out.append(d)
        d += timedelta(days=1)
    return out


def load(symbols: list[str] | None = None) -> pl.DataFrame:
    """Every stored symbol as one frame (perp, day_us, ...), days without a file dropped."""
    d = out_dir()
    files = sorted(d.glob("*.parquet")) if d.exists() else []
    frames = [pl.read_parquet(f).with_columns(perp=pl.lit(f.stem)) for f in files
              if symbols is None or f.stem in symbols]
    if not frames:
        return pl.DataFrame(schema={"perp": pl.Utf8, **SCHEMA})
    return pl.concat(frames, how="vertical_relaxed").filter(pl.col("n") > 0)


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

def collect(sym: str, days: list[date], pacer: Pacer, fetch=get_zip) -> int:
    """Fetch the days of one symbol and save them every 60 days of progress."""
    rows: list[dict] = []
    got = 0
    for i, d in enumerate(days):
        raw = fetch(BASE.format(s=sym, d=d.isoformat()), pacer)
        rows.append(day_row(raw, d))
        got += raw is not None
        if len(rows) >= 60 or i == len(days) - 1:
            save_symbol(sym, rows)
            rows = []
    return got


def run(panel_path: Path, since: date, top: int, dry: bool, until: date | None = None) -> dict:
    until = until or (datetime.now(timezone.utc).date() - timedelta(days=1))
    panel = pl.read_parquet(panel_path, columns=["day", "perp", "perp_adv28", "eligible"])
    pl_ = plan(panel, since, top, until)
    jobs = [(s, todo(s, a, b)) for s, (a, b) in pl_.items()]
    jobs = [(s, d) for s, d in jobs if d]
    n = sum(len(d) for _, d in jobs)
    print(f"um_metrics: {len(pl_)} symbols planned, {len(jobs)} with {n:,} days to fetch "
          f"(about {n / RATE / 3600:.1f} h at {RATE:.0f} a second)", flush=True)
    if dry:
        return {"symbols": len(pl_), "days": n}
    pacer = Pacer(RATE)
    done = {"files": 0, "symbols": 0}
    lock = threading.Lock()
    t0 = time.time()

    def one(job):
        s, days = job
        got = collect(s, days, pacer)
        with lock:
            done["files"] += got
            done["symbols"] += 1
            if done["symbols"] % 10 == 0:
                print(f"  {done['symbols']}/{len(jobs)} symbols, {done['files']:,} files, "
                      f"{time.time() - t0:.0f}s", flush=True)

    with ThreadPoolExecutor(WORKERS) as ex:
        list(ex.map(one, jobs))
    print(f"um_metrics: done, {done['files']:,} files in {time.time() - t0:.0f}s", flush=True)
    return {"symbols": len(pl_), "days": n, **done}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--panel", type=Path, default=ROOT / "lab-cache" / "xs_daily_panel.parquet")
    ap.add_argument("--since", type=date.fromisoformat, default=FIRST_DAY)
    ap.add_argument("--top", type=int, default=120)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    run(a.panel, a.since, a.top, a.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
