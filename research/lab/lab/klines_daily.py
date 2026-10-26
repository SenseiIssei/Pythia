"""Daily Binance spot klines from data.binance.vision, cached in the data lake.

    python -m lab.klines_daily DOGEUSDT SHIBUSDT ...

The archive keeps every pair Binance ever listed, delisted ones included, as
monthly zips of 1d klines plus daily zips for the running month. Each finished
month is cached once under <data>/hist/binance_spot/klines_1d/symbol=<S>/
<YYYY-MM>.parquet; the running month is rebuilt from its daily files on every
call. Columns: day (UTC start, us), open, high, low, close, volume, qv (quote
volume, USDT), n (trade count), taker_qv. Binance switched spot timestamps
from milliseconds to microseconds in 2025; both are read.

The archive host is tried first, its storage bucket second (the same files).
Standard library plus polars only.
"""

from __future__ import annotations

import io
import re
import sys
import urllib.error
import urllib.request
import zipfile
from datetime import date, datetime, timedelta, timezone

import polars as pl

from .data import ROOT

HOSTS = ("https://data.binance.vision", "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision")
BUCKET = HOSTS[1]
COLS = ["open_time", "open", "high", "low", "close", "volume", "close_time", "qv", "n", "taker_base",
        "taker_qv", "ignore"]
DAY_US = 86_400_000_000


def cache_dir(symbol: str):
    return ROOT / "hist" / "binance_spot" / "klines_1d" / f"symbol={symbol}"


def _get(path: str, timeout: float = 30) -> bytes | None:
    """The file at `path` from the first host that has it; None on 404 everywhere."""
    last: Exception | None = None
    for h in HOSTS:
        try:
            with urllib.request.urlopen(f"{h}/{path}", timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                last = None
                continue
            last = e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last = e
    if last is not None:
        raise last
    return None


def parse_zip(raw: bytes) -> pl.DataFrame:
    """One kline zip (CSV inside, with or without a header) to the cached columns."""
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        text = z.read(z.namelist()[0]).decode()
    lines = [x for x in text.splitlines() if x.strip()]
    if lines and not lines[0][:1].isdigit():
        lines = lines[1:]
    if not lines:
        return empty()
    rows = [x.split(",") for x in lines]
    ot = [int(r[0]) for r in rows]
    # Milliseconds have 13 digits, microseconds 16.
    day = [t * 1000 if t < 10 ** 14 else t for t in ot]
    day = [(t // DAY_US) * DAY_US for t in day]
    f = lambda i: [float(r[i]) for r in rows]  # noqa: E731
    return pl.DataFrame({"day": day, "open": f(1), "high": f(2), "low": f(3), "close": f(4), "volume": f(5),
                         "qv": f(7), "n": [int(float(r[8])) for r in rows], "taker_qv": f(10)},
                        schema={"day": pl.Int64, "open": pl.Float64, "high": pl.Float64, "low": pl.Float64,
                                "close": pl.Float64, "volume": pl.Float64, "qv": pl.Float64, "n": pl.Int64,
                                "taker_qv": pl.Float64})


def empty() -> pl.DataFrame:
    return pl.DataFrame(schema={"day": pl.Int64, "open": pl.Float64, "high": pl.Float64, "low": pl.Float64,
                                "close": pl.Float64, "volume": pl.Float64, "qv": pl.Float64, "n": pl.Int64,
                                "taker_qv": pl.Float64})


def list_months(symbol: str) -> list[str]:
    """YYYY-MM of every monthly 1d archive the bucket holds for `symbol`."""
    url = f"{BUCKET}?prefix=data/spot/monthly/klines/{symbol}/1d/&delimiter=/"
    with urllib.request.urlopen(url, timeout=30) as r:
        raw = r.read().decode()
    return sorted(set(re.findall(rf"{symbol}-1d-(\d{{4}}-\d{{2}})\.zip</Key>", raw)))


def fetch(symbol: str, today: date | None = None, verbose: bool = False, until: str | None = None,
          months: list[str] | None = None) -> pl.DataFrame:
    """Every daily bar of `symbol` up to yesterday (UTC), finished months cached. `until` (YYYY-MM): only the
    months before it, no daily files (the long history before the hourly panel); `months`: the archive's
    listing when the caller has it already."""
    today = today or datetime.now(timezone.utc).date()
    d = cache_dir(symbol)
    d.mkdir(parents=True, exist_ok=True)
    have = {p.stem for p in d.glob("*.parquet")}
    try:
        months = list_months(symbol) if months is None else months
    except (urllib.error.URLError, OSError) as e:
        if not have:
            raise
        print(f"  {symbol}: listing failed ({e}), using the cache", flush=True)
        months = sorted(have)
    cur = min(f"{today:%Y-%m}", until or "9999-99")
    for m in months:
        if m in have or m >= cur:
            continue
        raw = _get(f"data/spot/monthly/klines/{symbol}/1d/{symbol}-1d-{m}.zip")
        if raw is None:
            continue
        parse_zip(raw).write_parquet(d / f"{m}.parquet")
        if verbose:
            print(f"  {symbol} {m}", flush=True)
    frames = [pl.read_parquet(p) for p in sorted(d.glob("*.parquet")) if until is None or p.stem < until]
    if until is not None:
        return pl.concat(frames, how="vertical_relaxed").unique("day", keep="last").sort("day") if frames else empty()
    # The running month (and last month, if its monthly zip is not out yet) from daily files.
    last_cached = max([p.stem for p in d.glob("*.parquet")], default="")
    start = date(today.year, today.month, 1)
    if last_cached and last_cached < f"{(start - timedelta(days=1)):%Y-%m}":
        start = (start - timedelta(days=1)).replace(day=1)
    if months or have:
        day = start
        while day < today:
            raw = _get(f"data/spot/daily/klines/{symbol}/1d/{symbol}-1d-{day:%Y-%m-%d}.zip")
            if raw is not None:
                frames.append(parse_zip(raw))
            day += timedelta(days=1)
    if not frames:
        return empty()
    return pl.concat(frames, how="vertical_relaxed").unique("day", keep="last").sort("day")


def main(argv: list[str]) -> int:
    for s in argv:
        df = fetch(s, verbose=True)
        print(f"{s}: {df.height} days", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
