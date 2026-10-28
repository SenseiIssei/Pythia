"""Binance USD-M futures daily metrics for the liquid perpetuals, keyless, from data.binance.vision.

    python -m lab.collect.um_metrics [--panel PATH] [--since 2021-12-01] [--top 120] [--dry-run]
    python -m lab.collect.um_metrics --check-shift BTCUSDT,ETHUSDT,SOLUSDT [--around 2026-06-25] [--days 14]

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

`create_time` is the open of the row's 5-minute period: its taker ratio is the 5-minute kline's
opening then, before and after 2026-06-25 (T4, `--check-shift`, results/book_depth_t4.md; the
review had a reported change of meaning on that day), and its open interest is the snapshot at
the period's end (the recorder's 60 s open interest matches it 5 minutes after the stamp). The
day's last row, stamped 23:55, is the open interest at the day's close.

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
WORKERS = 24          # each thread waits on the archive; the threads, not RATE, set the pace below it
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
# create_time check (T4)
# ---------------------------------------------------------------------------

KLINES = "https://data.binance.vision/data/futures/um/daily/klines/{s}/5m/{s}-5m-{d}.zip"
LAGS = (-2, -1, 0, 1, 2)


def stamp_lags(metrics: bytes, klines: bytes, lags=LAGS) -> dict[int, float]:
    """{lag: correlation of log taker buy/sell ratios}: each metrics row against the 5-minute kline
    opening `lag` periods after its create_time (taker buy volume over the rest). The best lag is
    where create_time sits in the period: 0 when it is the period's open."""
    m = pl.read_csv(io.BytesIO(metrics), infer_schema_length=0)
    m = m.select(t=pl.col("create_time").str.strptime(pl.Datetime("us"), "%Y-%m-%d %H:%M:%S", strict=False)
                 .dt.epoch("us"), r=pl.col("sum_taker_long_short_vol_ratio").cast(pl.Float64, strict=False))
    k = pl.read_csv(io.BytesIO(klines), has_header=False, infer_schema_length=0)
    if not k.is_empty() and not str(k[0, 0]).isdigit():
        k = k.slice(1)
    k = k.select(t=pl.col(k.columns[0]).cast(pl.Int64) * 1000, v=pl.col(k.columns[5]).cast(pl.Float64),
                 b=pl.col(k.columns[9]).cast(pl.Float64)).filter(pl.col("v") > pl.col("b"))
    k = k.select("t", kr=(pl.col("b") / (pl.col("v") - pl.col("b"))).log())
    m = m.filter(pl.col("r") > 0).select("t", mr=pl.col("r").log())
    out = {}
    for lag in lags:
        j = m.with_columns(t=pl.col("t") + lag * 300_000_000).join(k, on="t")
        out[lag] = float(np.corrcoef(j["mr"], j["kr"])[0, 1]) if j.height > 10 else math.nan
    return out


def check_shift(symbols: list[str], around: date, days: int, fetch=get_zip) -> list[dict]:
    """Per symbol and day from `days` before `around` to `days` after: the lag correlations and the best
    lag. A one-period shift at `around` shows as a best lag that differs before and after."""
    pacer = Pacer(4.0)
    rows = []
    for s in symbols:
        for i in range(-days, days):
            d = (around + timedelta(days=i)).isoformat()
            m = fetch(BASE.format(s=s, d=d), pacer)
            k = fetch(KLINES.format(s=s, d=d), pacer)
            if not m or not k:
                continue
            c = stamp_lags(m, k)
            ok = {g: v for g, v in c.items() if math.isfinite(v)}
            rows.append({"symbol": s, "day": d, "after": i >= 0, **{f"lag{g:+d}": v for g, v in c.items()},
                         "best": max(ok, key=ok.get) if ok else None})
    return rows


def shift_verdict(rows: list[dict]) -> dict:
    """Per symbol the best lags before and after; shifted when they differ."""
    out = {}
    for s in dict.fromkeys(r["symbol"] for r in rows):
        b = sorted({r["best"] for r in rows if r["symbol"] == s and not r["after"]} - {None})
        a = sorted({r["best"] for r in rows if r["symbol"] == s and r["after"]} - {None})
        out[s] = {"before": b, "after": a, "shifted": b != a}
    return out


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
    ap.add_argument("--check-shift", default="", help="symbols: check create_time against the 5-minute klines")
    ap.add_argument("--around", type=date.fromisoformat, default=date(2026, 6, 25))
    ap.add_argument("--days", type=int, default=14)
    a = ap.parse_args(argv)
    if a.check_shift:
        rows = check_shift([s for s in a.check_shift.split(",") if s], a.around, a.days)
        for r in rows:
            print(r["symbol"], r["day"], " ".join(f"{k} {v:.3f}" for k, v in r.items() if k.startswith("lag")),
                  "best", r["best"])
        v = shift_verdict(rows)
        for s, x in v.items():
            print(f"{s}: best lag before {x['before']}, after {x['after']}: {'SHIFTED' if x['shifted'] else 'no shift'}")
        return 1 if any(x["shifted"] for x in v.values()) else 0
    run(a.panel, a.since, a.top, a.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
