"""Keyless kline archives from data.binance.vision (through its S3 bucket endpoint).

    python -m lab.experiments.vision alpaca            # 5m bars of the Alpaca coins
    python -m lab.experiments.vision daily             # 1d bars of every USDT pair (the twin's ranking)
    python -m lab.experiments.vision twin              # 5m bars of every coin the twin ever holds

Files land in <PYTHIA_DATA>/hist/binance_spot/klines_<iv>/symbol=X/YYYY-MM.parquet
(months) and YYYY-MM-DD.parquet (days of the running month), the recorder's
layout. Existing files are skipped. Binance writes spot timestamps in
milliseconds before 2025 and in microseconds after; both are read as us.
"""

from __future__ import annotations

import io
import re
import sys
import time
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import polars as pl

from .. import data as labdata

BUCKET = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
COLS = ["open_time", "open", "high", "low", "close", "volume", "close_time", "quote_volume", "n_trades",
        "taker_base", "taker_quote", "ignore"]


def out_dir(iv: str, symbol: str) -> Path:
    return labdata.ROOT / "hist" / "binance_spot" / f"klines_{iv}" / f"symbol={symbol}"


def _get(url: str, tries: int = 4) -> bytes | None:
    for k in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            time.sleep(2 ** (k + 1))
        except Exception:
            time.sleep(2 ** (k + 1))
    return None


def list_prefixes(prefix: str) -> list[str]:
    """Every sub-prefix under `prefix` in the bucket (paginated)."""
    out, marker = [], ""
    while True:
        raw = _get(f"{BUCKET}?prefix={prefix}&delimiter=/&marker={marker}")
        if raw is None:
            break
        txt = raw.decode()
        got = re.findall(r"<Prefix>([^<]+)</Prefix>", txt)[1:]
        out += got
        nxt = re.search(r"<NextMarker>([^<]+)</NextMarker>", txt)
        if "<IsTruncated>true</IsTruncated>" not in txt or not nxt:
            break
        marker = nxt.group(1)
    return out


def list_files(prefix: str) -> list[str]:
    out, marker = [], ""
    while True:
        raw = _get(f"{BUCKET}?prefix={prefix}&marker={marker}")
        if raw is None:
            break
        txt = raw.decode()
        keys = re.findall(r"<Key>([^<]+)</Key>", txt)
        out += [k for k in keys if k.endswith(".zip")]
        if "<IsTruncated>true</IsTruncated>" not in txt or not keys:
            break
        marker = keys[-1]
    return out


def parse(raw: bytes) -> pl.DataFrame:
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        body = z.read(z.namelist()[0])
    df = pl.read_csv(io.BytesIO(body), has_header=False, new_columns=COLS, infer_schema_length=0)
    if df.height and not df[0, 0].isdigit():
        df = df.slice(1)
    ot = df["open_time"].cast(pl.Int64)
    ot = pl.Series(np.where(ot.to_numpy() < 10 ** 14, ot.to_numpy() * 1000, ot.to_numpy()))
    return pl.DataFrame({
        "open_time_us": ot,
        **{c: df[c].cast(pl.Float64) for c in ("open", "high", "low", "close", "volume", "quote_volume")},
        "n_trades": df["n_trades"].cast(pl.Int64),
    })


def fetch_symbol(symbol: str, iv: str, since: date, until: date) -> int:
    """Monthly archives for whole months in [since, until], daily ones for the rest. Returns files written."""
    d = out_dir(iv, symbol)
    have = {p.stem for p in d.glob("*.parquet")} if d.exists() else set()
    monthly = list_files(f"data/spot/monthly/klines/{symbol}/{iv}/")
    months = sorted(re.search(r"(\d{4}-\d{2})\.zip$", k).group(1) for k in monthly)
    months = [m for m in months if f"{since:%Y-%m}" <= m <= f"{until:%Y-%m}"]
    wrote = 0
    for m in months:
        if m in have:
            continue
        raw = _get(f"{BUCKET}/data/spot/monthly/klines/{symbol}/{iv}/{symbol}-{iv}-{m}.zip")
        if raw:
            d.mkdir(parents=True, exist_ok=True)
            parse(raw).write_parquet(d / f"{m}.parquet")
            wrote += 1
    # Days after the last monthly archive, up to `until`.
    last = max(months) if months else None
    day = date.fromisoformat(f"{last}-01") if last else since
    if last:
        day = (day.replace(day=28) + timedelta(days=4)).replace(day=1)
    while day <= until:
        s = f"{day:%Y-%m-%d}"
        if s not in have:
            raw = _get(f"{BUCKET}/data/spot/daily/klines/{symbol}/{iv}/{symbol}-{iv}-{s}.zip")
            if raw:
                d.mkdir(parents=True, exist_ok=True)
                parse(raw).write_parquet(d / f"{s}.parquet")
                wrote += 1
        day += timedelta(days=1)
    return wrote


def load(symbol: str, iv: str) -> pl.DataFrame:
    files = sorted(out_dir(iv, symbol).glob("*.parquet"))
    if not files:
        return pl.DataFrame()
    return pl.concat([pl.read_parquet(f) for f in files], how="vertical_relaxed").unique(
        "open_time_us", keep="last").sort("open_time_us")


def usdt_symbols() -> list[str]:
    """Every USDT spot pair the archive has ever published monthly klines for, delisted ones included."""
    ps = list_prefixes("data/spot/monthly/klines/")
    syms = [p.rstrip("/").split("/")[-1] for p in ps]
    return sorted(s for s in syms if s.endswith("USDT"))


def run_many(symbols: list[str], iv: str, since: date, until: date, par: int = 16) -> None:
    t = time.time()
    with ThreadPoolExecutor(par) as ex:
        for k, (s, n) in enumerate(zip(symbols, ex.map(lambda s: fetch_symbol(s, iv, since, until), symbols))):
            print(f"[{k + 1}/{len(symbols)}] {s} {iv}: {n} files ({time.time() - t:.0f}s)", flush=True)


def main() -> None:
    from . import fast_maker as fm
    what = sys.argv[1] if len(sys.argv) > 1 else "alpaca"
    until = date.fromisoformat(sys.argv[2]) if len(sys.argv) > 2 else fm.DATA_END
    if what == "alpaca":
        syms = sorted({s for ss in fm.SYMBOLS.values() for s in ss})
        run_many(syms, "5m", date(2020, 1, 1), until)
    elif what == "daily":
        syms = [s for s in usdt_symbols() if not fm.excluded_symbol(s)]
        print(f"{len(syms)} USDT symbols", flush=True)
        run_many(syms, "1d", fm.TWIN_RANK_SINCE, until, par=32)
    elif what == "twin":
        syms = fm.twin_symbols()
        print(f"{len(syms)} twin symbols", flush=True)
        run_many(syms, "5m", fm.TWIN_RANK_SINCE, until)
    else:
        raise SystemExit(f"unknown: {what}")


if __name__ == "__main__":
    main()
