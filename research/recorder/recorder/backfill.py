"""History from data.binance.vision: spot 1m klines, USD-M funding and metrics.

    python -m recorder.backfill                 # everything, defaults below
    python -m recorder.backfill --only klines --since 2024-01

Idempotent: a file that already exists is skipped, so a cron can rerun it.
Every archive is checked against its published SHA-256 before it is parsed.

Output:
  hist/binance_spot/klines_1m/symbol=X/YYYY-MM.parquet
  hist/binance_um/funding/symbol=X/YYYY-MM.parquet
  hist/binance_um/metrics/symbol=X/YYYY-MM.parquet
The running month is stored per day (YYYY-MM-DD.parquet) and folded into the
month file once the month is complete.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import io
import json
import logging
import os
import zipfile
from datetime import date, timedelta
from pathlib import Path

import aiohttp
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.csv as pcsv
import pyarrow.parquet as pq

from . import config
from .binance import load_symbols

log = logging.getLogger("backfill")
BASE = "https://data.binance.vision/data"

KLINE_COLS = ["open_time", "open", "high", "low", "close", "volume", "close_time",
              "quote_volume", "trades", "taker_buy_volume", "taker_buy_quote_volume", "ignore"]


def months(since: date, until: date):
    d = since.replace(day=1)
    while d <= until:
        yield d
        d = (d.replace(day=28) + timedelta(days=4)).replace(day=1)


def days(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


class Fetcher:
    def __init__(self, http: aiohttp.ClientSession, par: int):
        self.http = http
        self.sem = asyncio.Semaphore(par)
        self.stats = {"ok": 0, "missing": 0, "bad_checksum": 0, "skipped": 0}

    async def zip_csv(self, url: str) -> bytes | None:
        async with self.sem:
            async with self.http.get(url) as r:
                if r.status == 404:
                    self.stats["missing"] += 1
                    return None
                r.raise_for_status()
                blob = await r.read()
            async with self.http.get(url + ".CHECKSUM") as r:
                want = (await r.text()).split()[0] if r.status == 200 else None
        if want and hashlib.sha256(blob).hexdigest() != want:
            self.stats["bad_checksum"] += 1
            log.error("checksum mismatch, discarded: %s", url)
            return None
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            return z.read(z.namelist()[0])


def read_csv(raw: bytes, names: list[str] | None) -> pa.Table:
    has_header = raw[:1].isalpha()
    opts = pcsv.ReadOptions(column_names=None if has_header else names, autogenerate_column_names=False)
    return pcsv.read_csv(io.BytesIO(raw), read_options=opts)


def to_us(col: pa.ChunkedArray) -> pa.Array:
    """Binance switched spot dumps from ms to us on 2025-01-01. Normalise to us."""
    arr = pc.cast(col, pa.int64())
    return pc.if_else(pc.greater(arr, 10**14), arr, pc.multiply(arr, 1000))


def norm_klines(t: pa.Table) -> pa.Table:
    t = t.rename_columns(KLINE_COLS[: t.num_columns])
    out = {
        "open_time_us": to_us(t["open_time"]),
        "close_time_us": to_us(t["close_time"]),
    }
    for c in ("open", "high", "low", "close", "volume", "quote_volume",
              "taker_buy_volume", "taker_buy_quote_volume"):
        out[c] = pc.cast(t[c], pa.float64())
    out["trades"] = pc.cast(t["trades"], pa.int64())
    return pa.table(out)


def norm_funding(t: pa.Table) -> pa.Table:
    return pa.table({
        "funding_time_us": pc.multiply(pc.cast(t["calc_time"], pa.int64()), 1000),
        "interval_hours": pc.cast(t["funding_interval_hours"], pa.int32()),
        "funding_rate": pc.cast(t["last_funding_rate"], pa.float64()),
    })


def norm_metrics(t: pa.Table) -> pa.Table:
    ts = t["create_time"]
    if pa.types.is_timestamp(ts.type):  # the CSV reader usually infers it already
        ts = pc.cast(ts, pa.timestamp("us"))
    else:
        ts = pc.strptime(ts, format="%Y-%m-%d %H:%M:%S", unit="us")
    cols = {"ts_us": pc.cast(ts, pa.int64())}
    for c in t.column_names:
        if c not in ("create_time", "symbol"):
            cols[c] = pc.cast(t[c], pa.float64())
    return pa.table(cols)


def write(t: pa.Table, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    pq.write_table(t, tmp, compression="zstd")
    os.replace(tmp, path)


async def monthly_then_daily(f: Fetcher, out_dir: Path, since: date, url_month, url_day, names, norm,
                             sort_col: str, daily_only: bool = False) -> None:
    """Complete months from monthly archives (or glued from daily ones), the running month per day."""
    today = date.today()
    this_month = today.replace(day=1)
    for m in months(since, today):
        label = m.strftime("%Y-%m")
        month_file = out_dir / f"{label}.parquet"
        # A finished month with no archive at all (usually: before the listing)
        # is remembered, or every nightly run asks for ~30 files that cannot exist.
        absent = out_dir / f"{label}.absent"
        if month_file.exists() or absent.exists():
            f.stats["skipped"] += 1
            continue
        if m < this_month:
            raw = None if daily_only else await f.zip_csv(url_month(label))
            if raw is not None:
                write(norm(read_csv(raw, names)), month_file)
                f.stats["ok"] += 1
            elif not daily_only and (this_month - m).days > 40:
                # Monthly archives exist for every finished month a pair traded.
                # Missing one that old means it did not trade: no need to ask
                # for 30 daily files to confirm (across hundreds of pairs that
                # would be most of the requests).
                out_dir.mkdir(parents=True, exist_ok=True)
                absent.touch()
                continue
            else:
                last = (m.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
                raws = await asyncio.gather(*(f.zip_csv(url_day(d.isoformat())) for d in days(m, last)))
                parts = [norm(read_csv(r, names)) for r in raws if r is not None]
                if not parts:
                    if (this_month - m).days > 40:  # never for last month, it may still be published
                        out_dir.mkdir(parents=True, exist_ok=True)
                        absent.touch()
                    continue
                write(pa.concat_tables(parts).sort_by(sort_col), month_file)
                f.stats["ok"] += 1
            for stale in out_dir.glob(f"{label}-*.parquet"):
                stale.unlink()
        else:
            for d in days(m, today - timedelta(days=1)):
                p = out_dir / f"{d.isoformat()}.parquet"
                if p.exists():
                    f.stats["skipped"] += 1
                    continue
                raw = await f.zip_csv(url_day(d.isoformat()))
                if raw is not None:
                    write(norm(read_csv(raw, names)), p)
                    f.stats["ok"] += 1


async def run(args) -> None:
    root = config.DATA_ROOT / "hist"
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=300)) as http:
        spot, perp = await load_symbols(http, config.UNIVERSE)
        f = Fetcher(http, args.parallel)
        jobs = []
        if args.only in (None, "klines"):
            since = date.fromisoformat(args.since or "2020-01-01")
            for s in spot.values():
                jobs.append(monthly_then_daily(
                    f, root / "binance_spot" / "klines_1m" / f"symbol={s}", since,
                    lambda l, s=s: f"{BASE}/spot/monthly/klines/{s}/1m/{s}-1m-{l}.zip",
                    lambda l, s=s: f"{BASE}/spot/daily/klines/{s}/1m/{s}-1m-{l}.zip",
                    KLINE_COLS, norm_klines, "open_time_us"))
        if args.only in (None, "funding"):
            since = date.fromisoformat(args.since or "2020-01-01")
            for s in perp.values():
                jobs.append(monthly_then_daily(
                    f, root / "binance_um" / "funding" / f"symbol={s}", since,
                    lambda l, s=s: f"{BASE}/futures/um/monthly/fundingRate/{s}/{s}-fundingRate-{l}.zip",
                    lambda l, s=s: f"{BASE}/futures/um/daily/fundingRate/{s}/{s}-fundingRate-{l}.zip",
                    None, norm_funding, "funding_time_us"))
        if args.only in (None, "metrics"):
            since = date.fromisoformat(args.since or "2022-01-01")
            for s in perp.values():
                jobs.append(monthly_then_daily(
                    f, root / "binance_um" / "metrics" / f"symbol={s}", since,
                    lambda l, s=s: "",
                    lambda l, s=s: f"{BASE}/futures/um/daily/metrics/{s}/{s}-metrics-{l}.zip",
                    None, norm_metrics, "ts_us", daily_only=True))
        if args.only == "klines_1h_all":
            # Every USDT pair Binance ever listed, delisted ones included (no survivorship bias).
            from .universe import list_spot_usdt
            syms = await list_spot_usdt(http)
            (root / "universe.json").write_text(json.dumps(syms))
            log.info("broad universe: %d USDT pairs", len(syms))
            since = date.fromisoformat(args.since or "2020-01-01")
            for s in syms:
                jobs.append(monthly_then_daily(
                    f, root / "binance_spot" / "klines_1h" / f"symbol={s}", since,
                    lambda l, s=s: f"{BASE}/spot/monthly/klines/{s}/1h/{s}-1h-{l}.zip",
                    lambda l, s=s: f"{BASE}/spot/daily/klines/{s}/1h/{s}-1h-{l}.zip",
                    KLINE_COLS, norm_klines, "open_time_us"))

        async def guarded(job):
            try:
                await job
            except Exception:
                f.stats["failed_jobs"] = f.stats.get("failed_jobs", 0) + 1
                log.exception("job failed, rerun picks it up")

        step = args.jobs
        for i in range(0, len(jobs), step):
            await asyncio.gather(*(guarded(j) for j in jobs[i:i + step]))
            log.info("progress %d/%d jobs, %s", min(i + step, len(jobs)), len(jobs), f.stats)
        log.info("done: %s", f.stats)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=["klines", "funding", "metrics", "klines_1h_all"],
                    help="klines_1h_all: hourly bars of every USDT pair ever listed, run on its own")
    ap.add_argument("--since", help="YYYY-MM-DD")
    ap.add_argument("--parallel", type=int, default=16, help="concurrent downloads")
    ap.add_argument("--jobs", type=int, default=8, help="symbols worked on at once")
    asyncio.run(run(ap.parse_args()))


if __name__ == "__main__":
    main()
