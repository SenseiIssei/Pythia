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

Funding is the exception: data.binance.vision publishes it only as monthly
archives, a few days after the month ends. The finished days the archive does
not cover yet (the running month, and last month until its archive appears)
come from the public REST endpoint `GET /fapi/v1/fundingRate` instead, for
every perpetual that is trading, in the same layout and schema (one
YYYY-MM-DD.parquet per UTC day). The monthly archive replaces those day files
once it exists. See `fill_funding_from_rest`.
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
from datetime import date, datetime, timedelta, timezone
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
    """Complete months from monthly archives (or glued from daily ones), the running month per day.

    `url_day=None` means the source has no daily archives (funding): finished
    months come only from the monthly archive, the running month is left to
    whatever else writes day files, and nothing asks for files that cannot exist.
    """
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
            elif url_day is None:
                continue  # last month, archive not published yet: keep any day files
            else:
                last =(m.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
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
        elif url_day is not None:
            for d in days(m, today - timedelta(days=1)):
                p = out_dir / f"{d.isoformat()}.parquet"
                if p.exists():
                    f.stats["skipped"] += 1
                    continue
                raw = await f.zip_csv(url_day(d.isoformat()))
                if raw is not None:
                    write(norm(read_csv(raw, names)), p)
                    f.stats["ok"] += 1


# --- Recent funding from REST ------------------------------------------------
#
# GET /fapi/v1/fundingRate is public and shares a limit of 500 requests per
# 5 minutes per IP with /fapi/v1/fundingInfo. The engine's coin ranking and the
# perp paper book call the same endpoint from this machine, so the backfill
# stays well under it: one request per symbol and night in the normal case,
# spaced by REST_INTERVAL_S across all jobs, and a 429/418 pauses every job for
# the Retry-After Binance sends.

REST_LIMIT = 1000          # rows per request, the endpoint's maximum
REST_INTERVAL_S = 0.8      # about 375 requests per 5 minutes at most
REST_ATTEMPTS = 5
HOUR_MS = 3_600_000
DAY_MS = 86_400_000


def utc_today() -> date:
    return datetime.now(timezone.utc).date()


def day_ms(d: date) -> int:
    return int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp() * 1000)


def month_end(m: date) -> date:
    return (m.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)


class Pacer:
    """Spaces requests across every job sharing it; `pause` holds them all."""

    def __init__(self, interval_s: float):
        self.interval = interval_s
        self.lock = asyncio.Lock()
        self.next_at = 0.0

    async def wait(self) -> None:
        loop = asyncio.get_running_loop()
        async with self.lock:
            delay = self.next_at - loop.time()
            if delay > 0:
                await asyncio.sleep(delay)
            self.next_at = max(self.next_at, loop.time()) + self.interval

    def pause(self, seconds: float) -> None:
        self.next_at = max(self.next_at, asyncio.get_running_loop().time() + seconds)


class FundingRest:
    """Settled funding of one perpetual from Binance's public REST endpoint."""

    def __init__(self, http, pacer: Pacer, stats: dict, base: str = config.BINANCE_UM_REST):
        self.http = http
        self.pacer = pacer
        self.stats = stats
        self.url = f"{base}/fundingRate"

    async def _page(self, params: dict) -> list[dict]:
        for _ in range(REST_ATTEMPTS):
            await self.pacer.wait()
            async with self.http.get(self.url, params=params) as r:
                self.stats["rest"] = self.stats.get("rest", 0) + 1
                if r.status in (418, 429):
                    # 429: over the limit; 418: banned for a while for ignoring 429s.
                    wait = float(r.headers.get("Retry-After") or 60)
                    log.warning("fundingRate %s, every job waits %.0f s", r.status, wait)
                    self.pacer.pause(wait)
                    continue
                r.raise_for_status()
                return await r.json()
        raise RuntimeError(f"fundingRate still limited after {REST_ATTEMPTS} attempts")

    async def history(self, symbol: str, start_ms: int, end_ms: int) -> list[dict]:
        """Every settlement with start_ms <= fundingTime <= end_ms, oldest first."""
        rows: list[dict] = []
        start = start_ms
        while start <= end_ms:
            page = await self._page({"symbol": symbol, "startTime": start, "endTime": end_ms,
                                     "limit": REST_LIMIT})
            rows += page
            if len(page) < REST_LIMIT:
                break
            start = int(page[-1]["fundingTime"]) + 1
        return rows


def funding_gap(out_dir: Path, today: date, since: date | None = None) -> list[date]:
    """Finished UTC days that neither a monthly archive nor an earlier REST run covers.

    Only last month and the running month can be in that state: an older month
    has its archive, or is marked absent because the perp did not trade.
    """
    this_month = today.replace(day=1)
    prev_month = (this_month - timedelta(days=1)).replace(day=1)
    gap = []
    for m in (prev_month, this_month):
        label = m.strftime("%Y-%m")
        if (out_dir / f"{label}.parquet").exists() or (out_dir / f"{label}.absent").exists():
            continue
        first = max(m, since) if since else m
        for d in days(first, min(month_end(m), today - timedelta(days=1))):
            if not (out_dir / f"{d.isoformat()}.parquet").exists():
                gap.append(d)
    return gap


def funding_days(rows: list[dict]) -> dict[date, pa.Table]:
    """REST rows -> one table per UTC day, in the schema `norm_funding` writes.

    The REST rows carry no interval, so `interval_hours` is the time since the
    previous settlement (the first row takes the gap to the next one, a lone
    row 8 h, Binance's default). `fundingTime` is the archive's `calc_time` to
    the millisecond, so the two sources agree on every key.
    """
    by_ms = {int(r["fundingTime"]): float(r["fundingRate"]) for r in rows}
    times = sorted(by_ms)
    gaps = [max(1, round((b - a) / HOUR_MS)) for a, b in zip(times, times[1:])]
    intervals = ([gaps[0]] if gaps else [8]) + gaps
    out: dict[date, list] = {}
    for ms, hours in zip(times, intervals):
        d = datetime.fromtimestamp(ms / 1000, timezone.utc).date()
        out.setdefault(d, []).append((ms, hours, by_ms[ms]))
    return {d: pa.table({
        "funding_time_us": pa.array([ms * 1000 for ms, _, _ in v], pa.int64()),
        "interval_hours": pa.array([h for _, h, _ in v], pa.int32()),
        "funding_rate": pa.array([x for _, _, x in v], pa.float64()),
    }) for d, v in out.items()}


async def fill_funding_from_rest(f: Fetcher, rest: FundingRest, out_dir: Path, symbol: str,
                                 since: date | None = None, today: date | None = None) -> None:
    """Writes YYYY-MM-DD.parquet for every finished day in the archive's gap.

    One request covers the whole gap (at most two months: 1488 rows for a 1 h
    perp, so two pages at worst). A day without settlements (before a listing)
    gets no file and is asked for again next night inside the same request.
    """
    today = today or utc_today()
    gap = funding_gap(out_dir, today, since)
    if not gap:
        return
    rows = await rest.history(symbol, day_ms(gap[0]), day_ms(today) - 1)
    tables = funding_days(rows)
    for d in gap:
        if d in tables:
            write(tables[d], out_dir / f"{d.isoformat()}.parquet")
            f.stats["rest_days"] = f.stats.get("rest_days", 0) + 1


async def trading_perps(http) -> set[str]:
    async with http.get(f"{config.BINANCE_UM_REST}/exchangeInfo") as r:
        r.raise_for_status()
        info = await r.json()
    return {s["symbol"] for s in info["symbols"]
            if s["status"] == "TRADING" and s.get("contractType") == "PERPETUAL"}


async def funding_job(f: Fetcher, rest: FundingRest | None, out_dir: Path, symbol: str, since: date) -> None:
    """Monthly archives first (a new one deletes the REST day files of its month),
    then REST for what the archives do not cover yet."""
    await monthly_then_daily(
        f, out_dir, since,
        lambda l: f"{BASE}/futures/um/monthly/fundingRate/{symbol}/{symbol}-fundingRate-{l}.zip",
        None, None, norm_funding, "funding_time_us")
    if rest is not None:
        await fill_funding_from_rest(f, rest, out_dir, symbol, since)


async def run(args) -> None:
    root = config.DATA_ROOT / "hist"
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=300)) as http:
        spot, perp = await load_symbols(http, config.UNIVERSE)
        f = Fetcher(http, args.parallel)
        rest = None if args.no_rest else FundingRest(http, Pacer(args.rest_interval), f.stats)
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
            for s in perp.values():  # load_symbols keeps trading perps only
                jobs.append(funding_job(f, rest, root / "binance_um" / "funding" / f"symbol={s}", s, since))
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

        if args.only == "um_all":
            # Every USDT perpetual ever listed: daily bars (when it existed, what it
            # cost, including the basis) and funding (what holding it paid or cost).
            from .universe import list_um_usdt
            perps = await list_um_usdt(http)
            (root / "um_universe.json").write_text(json.dumps(perps))
            log.info("perp universe: %d USDT perpetuals", len(perps))
            # Delisted perps keep their archives but get no REST requests.
            trading = await trading_perps(http) if rest is not None else set()
            since = date.fromisoformat(args.since or "2020-01-01")
            for s in perps:
                jobs.append(monthly_then_daily(
                    f, root / "binance_um" / "klines_1d" / f"symbol={s}", since,
                    lambda l, s=s: f"{BASE}/futures/um/monthly/klines/{s}/1d/{s}-1d-{l}.zip",
                    lambda l, s=s: f"{BASE}/futures/um/daily/klines/{s}/1d/{s}-1d-{l}.zip",
                    KLINE_COLS, norm_klines, "open_time_us"))
                jobs.append(funding_job(f, rest if s in trading else None,
                                        root / "binance_um" / "funding" / f"symbol={s}", s, since))

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
    ap.add_argument("--only", choices=["klines", "funding", "metrics", "klines_1h_all", "um_all"],
                    help="klines_1h_all: hourly bars of every USDT pair ever listed, run on its own")
    ap.add_argument("--since", help="YYYY-MM-DD")
    ap.add_argument("--parallel", type=int, default=16, help="concurrent downloads")
    ap.add_argument("--jobs", type=int, default=8, help="symbols worked on at once")
    ap.add_argument("--rest-interval", type=float, default=REST_INTERVAL_S,
                    help="seconds between fundingRate requests, across all jobs")
    ap.add_argument("--no-rest", action="store_true",
                    help="archives only: leave the days the funding archive does not cover yet empty")
    asyncio.run(run(ap.parse_args()))


if __name__ == "__main__":
    main()
