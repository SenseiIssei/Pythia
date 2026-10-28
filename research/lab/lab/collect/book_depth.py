"""Binance USD-M order book depth (bookDepth) for the lab's perpetuals, and Binance's delisting history.
Data only, point in time (lab.collect.pit). Keyless.

    python -m lab.collect.book_depth [--estimate] [--max-files N] [--symbols A,B] [--no-delistings] [--dry-run]

T4 (results/book_depth_t4_prereg.md). data.binance.vision has one zip a day per perpetual from
2023-01-01 with a snapshot about every 30 s: the cumulative depth (contracts) and notional (USD)
within 1, 2, 3, 4 and 5 % of mid on each side (negative percentages the bids), and within 0.2 %
since early 2026. Each zip has a .CHECKSUM (sha256); a file that fails it is not stored and is
fetched again next run.

Universe: the perps of lab.collect.um_metrics (its stored symbols: every USDT perp that ranked
among the 120 most liquid of the xs_daily panel, from 100 days before its first such day to its
last), over the days its metrics file covers from 2023-01-01, plus the 20 lab coins' perps.

Stored under <data>/book_depth (PYTHIA_BOOK_DEPTH):
  raw/symbol=<S>/<YYYY-MM>.parquet     ts_us (the snapshot), bid_0p2, bid_1 .. bid_5, ask_0p2,
                                       ask_1 .. ask_5 (notional USD, float32; 0.2 null before the
                                       file has it), published_us (the file's time in the archive),
                                       collected_us, known_us (= ts_us: the book was public when
                                       stamped, as D2 keeps market data), backfilled (true)
  hourly/symbol=<S>/<YYYY-MM>.parquet  ts_us (hour), bid02, ask02, bid1, ask1 (mean USD), cost10k,
                                       cost100k (mean bps, buy and sell averaged), n, n_fine
                                       (snapshots, with the 0.2 % level), published_us
  manifest/<S>.json                    day -> ok | missing (a gap in the archive) | bad (checksum)
  delistings.parquet                   symbol, base, kind (spot, perp, monitoring), announced_us,
                                       delisted_us, source (announcement, archive), article, and
                                       the point-in-time columns; the first value seen wins
  estimate.json, health.json           the size estimate; the health file `jobs.py checks` reads

Size rule: before fetching, the archive is listed (S3, one call per 1000 keys) and the zip bytes
of every day in the windows are scaled by the stored bytes per zip byte (measured on what is
stored, else RATIO). Over MAX_GB for the whole history while a backfill is left: the estimate is
logged and written, nothing is fetched, exit 1. A run fetches the newest days first, then the backfill oldest first,
at most --max-files files; months are written whole, so a killed run loses at most one month a
worker. Polite: at most RATE requests a second over WORKERS threads, 429 and 5xx retried.

A live system sees a day's file only once the archive publishes it (about 7 to 10 h after the
day, published_us); the features use the snapshot time like every other market series.
"""

from __future__ import annotations

import argparse
import hashlib
import http.client
import io
import json
import math
import os
import re
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

from . import pit, um_metrics
from ..data import ROOT, UNIVERSE, perp_symbol

UTC = timezone.utc
DAY_US = pit.DAY_US
HOUR_US = pit.HOUR_US
BUCKET = "data.binance.vision"
FILE = "https://data.binance.vision/data/futures/um/daily/bookDepth/{s}/{s}-bookDepth-{d}.zip"
LIST = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision?delimiter=/&prefix={p}&marker={m}"
PREFIX = "data/futures/um/daily/bookDepth/{s}/"
UA = "pythia-lab book depth collector (research, public archive)"
RATE = 20.0
WORKERS = 16          # each thread waits on the archive (about 0.7 s a request from here); RATE caps them
FIRST_DAY = date(2023, 1, 1)
MAX_GB = 40.0
RATIO = 0.26            # stored bytes per zip byte before 100 MB are stored (0.254 measured on 160 days of 4 perps, see the report)
RECENT_DAYS = 7         # fetched first; a symbol without a file in this many days counts as stopped
LEVELS = (0.2, 1.0, 2.0, 3.0, 4.0, 5.0)
SIZES = {"cost10k": 1e4, "cost100k": 1e5}


def _lv(p: float) -> str:
    return "0p2" if p == 0.2 else str(int(p))


BIDS = [f"bid_{_lv(p)}" for p in LEVELS]
ASKS = [f"ask_{_lv(p)}" for p in LEVELS]
RAW_SCHEMA = {"ts_us": pl.Int64, **{c: pl.Float32 for c in BIDS + ASKS}, "published_us": pl.Int64,
              "collected_us": pl.Int64, "known_us": pl.Int64, "backfilled": pl.Boolean}
HOURLY_COLS = ("bid02", "ask02", "bid1", "ask1", "cost10k", "cost100k")
HOURLY_SCHEMA = {"ts_us": pl.Int64, **{c: pl.Float64 for c in HOURLY_COLS}, "n": pl.Int32, "n_fine": pl.Int32,
                 "published_us": pl.Int64}


def out_dir() -> Path:
    return Path(os.environ.get("PYTHIA_BOOK_DEPTH") or ROOT / "book_depth")


def base_of(symbol: str) -> str:
    """The coin of a USDT perp (1000PEPEUSDT is PEPE), as lab.features names it."""
    return re.sub(r"^(1000000|10000|1000)(?=[A-Z])", "", symbol.removesuffix("USDT"))


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

class ChecksumError(ValueError):
    pass


def get(url: str, pacer: um_metrics.Pacer, tries: int = 6) -> bytes | None:
    """The body at url, None for a 404."""
    last: Exception | None = None
    for k in range(tries):
        pacer.wait()
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            last = e
            if e.code != 429 and e.code < 500 and e.code != 403:
                raise
            time.sleep(float(e.headers.get("Retry-After") or 0) or min(60.0, 2.0 ** k))
        except (OSError, http.client.HTTPException) as e:
            last = e
            time.sleep(min(60.0, 2.0 ** k))
    raise RuntimeError(f"{url}: no answer after {tries} tries ({last})")


def verify(blob: bytes, checksum: bytes | None) -> bytes:
    """The CSV inside the zip once its sha256 matches the .CHECKSUM file ("<hex>  <name>")."""
    want = (checksum or b"").decode("ascii", "replace").split()
    if not want or hashlib.sha256(blob).hexdigest() != want[0].lower():
        raise ChecksumError("sha256 does not match the .CHECKSUM file" if want else "no .CHECKSUM file")
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        return z.read(z.namelist()[0])


def listing(symbol: str, pacer: um_metrics.Pacer, fetch=None) -> dict[date, tuple[int, int]]:
    """{day: (zip bytes, published_us)} of the symbol's bookDepth zips in the archive (S3 listing)."""
    fetch = fetch or get
    out: dict[date, tuple[int, int]] = {}
    marker = ""
    while True:
        raw = fetch(LIST.format(p=PREFIX.format(s=symbol), m=marker), pacer)
        if raw is None:
            return out
        text = raw.decode("utf-8", "replace")
        keys = re.findall(r"<Contents><Key>([^<]+)</Key><LastModified>([^<]+)</LastModified>.*?<Size>(\d+)</Size>",
                          text)
        for key, mod, size in keys:
            m = re.search(r"-bookDepth-(\d{4}-\d{2}-\d{2})\.zip$", key)
            if m:
                pub = int(datetime.fromisoformat(mod.replace("Z", "+00:00")).timestamp() * 1e6)
                out[date.fromisoformat(m.group(1))] = (int(size), pub)
        nxt = re.search(r"<NextMarker>([^<]+)</NextMarker>", text)
        if "<IsTruncated>true</IsTruncated>" not in text or not (nxt or keys):
            return out
        marker = nxt.group(1) if nxt else keys[-1][0]


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def parse(raw: bytes, day: date, published_us: int, collected_us: int) -> pl.DataFrame:
    """One day's CSV (timestamp, percentage, depth, notional) to one row per snapshot inside the day."""
    t = pl.read_csv(io.BytesIO(raw), infer_schema_length=0)
    if not {"timestamp", "percentage", "notional"} <= set(t.columns) or t.is_empty():
        return pl.DataFrame(schema=RAW_SCHEMA)
    d_us = pit.us_of(day)
    t = (t.select(ts_us=pl.col("timestamp").str.strptime(pl.Datetime("us"), "%Y-%m-%d %H:%M:%S", strict=False)
                  .dt.epoch("us"),
                  p=pl.col("percentage").cast(pl.Float64, strict=False),
                  v=pl.col("notional").cast(pl.Float64, strict=False))
         .drop_nulls().filter((pl.col("ts_us") >= d_us) & (pl.col("ts_us") < d_us + DAY_US)))
    names = {**{-p: b for p, b in zip(LEVELS, BIDS)}, **{p: a for p, a in zip(LEVELS, ASKS)}}
    t = t.with_columns(col=pl.col("p").round(2).replace_strict(names, default=None)).drop_nulls("col")
    if t.is_empty():
        return pl.DataFrame(schema=RAW_SCHEMA)
    w = t.pivot(on="col", index="ts_us", values="v", aggregate_function="last").sort("ts_us")
    for c in BIDS + ASKS:
        if c not in w.columns:
            w = w.with_columns(pl.lit(None, pl.Float64).alias(c))
    w = w.select("ts_us", *BIDS, *ASKS).with_columns(published_us=pl.lit(published_us, pl.Int64))
    return pit.stamp(w, collected_us, known=pl.col("ts_us"), backfilled=True).select(
        [pl.col(c).cast(s) for c, s in RAW_SCHEMA.items()])


def cost_bps(cum: np.ndarray, size: float) -> np.ndarray:
    """(n,) mean slippage from mid in bps of a market order of `size` USD on one side, from (n, 6)
    cumulative notional at LEVELS (%), linear between the levels and 0 at mid. A missing 0.2 % level
    is the straight line to 1 % (the same line as without it); nan when size exceeds the 5 % depth."""
    c = np.array(cum, dtype=np.float64, copy=True)
    c[:, 0] = np.where(np.isfinite(c[:, 0]), c[:, 0], c[:, 1] * LEVELS[0] / LEVELS[1])
    c = np.maximum.accumulate(np.nan_to_num(c, nan=0.0), axis=1)
    n = np.concatenate([np.zeros((len(c), 1)), c], axis=1)
    p = np.concatenate([[0.0], LEVELS]) * 100.0                                   # bps
    lo, hi = n[:, :-1], n[:, 1:]
    q = np.clip(size, lo, hi)
    span = hi - lo
    with np.errstate(invalid="ignore", divide="ignore"):
        p_q = p[:-1] + np.where(span > 0, (q - lo) / span, 0.0) * (p[1:] - p[:-1])
    area = ((q - lo) * (p[:-1] + p_q) / 2).sum(axis=1)
    bad = ~np.isfinite(np.asarray(cum, dtype=np.float64)[:, 1:]).all(axis=1) | (n[:, -1] < size)
    return np.where(bad, np.nan, area / size)


def hourly(raw: pl.DataFrame) -> pl.DataFrame:
    """The snapshots of each UTC hour: mean depth at 0.2 and 1 %, mean cost to trade SIZES."""
    if raw.is_empty():
        return pl.DataFrame(schema=HOURLY_SCHEMA)
    b = raw.select(BIDS).to_numpy()
    a = raw.select(ASKS).to_numpy()
    costs = {k: (cost_bps(b, s) + cost_bps(a, s)) / 2 for k, s in SIZES.items()}
    t = raw.select("ts_us", "published_us", bid02="bid_0p2", ask02="ask_0p2", bid1="bid_1", ask1="ask_1") \
        .with_columns(**{k: pl.Series(v) for k, v in costs.items()}).with_columns(
            pl.col(c).cast(pl.Float64).fill_nan(None) for c in HOURLY_COLS)
    return (t.with_columns(ts_us=(pl.col("ts_us") // HOUR_US) * HOUR_US)
            .group_by("ts_us").agg(*[pl.col(c).mean() for c in HOURLY_COLS], n=pl.len().cast(pl.Int32),
                                   n_fine=pl.col("bid02").is_not_null().sum().cast(pl.Int32),
                                   published_us=pl.col("published_us").max())
            .select(list(HOURLY_SCHEMA)).sort("ts_us"))


# ---------------------------------------------------------------------------
# Plan and storage
# ---------------------------------------------------------------------------

def plan(until: date) -> dict[str, tuple[date, date]]:
    """{perp symbol: (first day, last day)}: um_metrics' stored symbols over their stored days from
    FIRST_DAY (to `until` while their file reaches the last 7 days), and the lab coins' perps."""
    out: dict[str, tuple[date, date]] = {}
    d = um_metrics.out_dir()
    for f in sorted(d.glob("*.parquet")) if d.exists() else []:
        try:
            days = pl.read_parquet(f, columns=["day_us"])["day_us"]
        except (OSError, pl.exceptions.PolarsError):
            continue
        if days.is_empty():
            continue
        a, b = pit.day_of(int(days.min())), pit.day_of(int(days.max()))
        last = until if b >= until - timedelta(days=RECENT_DAYS) else min(b, until)
        first = max(FIRST_DAY, a)
        if f.stem.endswith("USDT") and first <= last:
            out[f.stem] = (first, last)
    for c in UNIVERSE:
        out.setdefault(perp_symbol(c), (FIRST_DAY, until))
    return dict(sorted(out.items()))


def _json(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write(p: Path, payload) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    if isinstance(payload, pl.DataFrame):
        payload.write_parquet(tmp)
    else:
        tmp.write_text(json.dumps(payload, indent=1, sort_keys=True), encoding="utf-8")
    os.replace(tmp, p)


def manifest(symbol: str) -> dict[str, str]:
    return _json(out_dir() / "manifest" / f"{symbol}.json", {})


def month_path(kind: str, symbol: str, month: str) -> Path:
    return out_dir() / kind / f"symbol={symbol}" / f"{month}.parquet"


def todo(symbol: str, window: tuple[date, date], listed: dict[date, tuple[int, int]],
         man: dict[str, str]) -> tuple[list[date], list[date]]:
    """(days to fetch, gaps): listed days in the window not stored yet; unlisted days inside the
    listed range are the archive's gaps."""
    a, b = window
    fetch, gaps = [], []
    if not listed:
        return fetch, gaps
    lo, hi = min(listed), max(listed)
    d = a
    while d <= b:
        k = d.isoformat()
        if d in listed:
            if man.get(k) != "ok":
                fetch.append(d)
        elif lo < d < hi:
            gaps.append(d)
        d += timedelta(days=1)
    return fetch, gaps


def save_month(symbol: str, month: str, frames: list[pl.DataFrame]) -> int:
    """Merge new snapshots into the month (the first value of a snapshot wins), rebuild its hours."""
    p = month_path("raw", symbol, month)
    old = pl.read_parquet(p) if p.exists() else pl.DataFrame(schema=RAW_SCHEMA)
    new = pl.concat([old, *frames], how="vertical_relaxed").unique("ts_us", keep="first").sort("ts_us")
    _write(p, new)
    _write(month_path("hourly", symbol, month), hourly(new))
    return new.height


def collect_symbol(symbol: str, days: list[date], listed: dict[date, tuple[int, int]], pacer: um_metrics.Pacer,
                   fetch=None) -> dict:
    """Fetch, verify and store the days of one symbol, a month at a time; the manifest after each month."""
    fetch = fetch or get
    man = manifest(symbol)
    got = {"ok": 0, "bad": 0, "missing": 0, "bytes": 0}
    by_month: dict[str, list[date]] = {}
    for d in days:
        by_month.setdefault(d.strftime("%Y-%m"), []).append(d)
    for month, ds in by_month.items():
        frames = []
        for d in ds:
            url = FILE.format(s=symbol, d=d.isoformat())
            blob = fetch(url, pacer)
            if blob is None:
                man[d.isoformat()] = "missing"
                got["missing"] += 1
                continue
            try:
                raw = verify(blob, fetch(url + ".CHECKSUM", pacer))
            except (ChecksumError, zipfile.BadZipFile) as e:
                man[d.isoformat()] = "bad"
                got["bad"] += 1
                print(f"  {symbol} {d}: {e}; fetched again next run", flush=True)
                continue
            frames.append(parse(raw, d, listed.get(d, (0, pit.now_us()))[1], pit.now_us()))
            man[d.isoformat()] = "ok"
            got["ok"] += 1
            got["bytes"] += len(blob)
        if frames:
            save_month(symbol, month, frames)
        _write(out_dir() / "manifest" / f"{symbol}.json", man)
    return got


def estimate(jobs: dict[str, dict]) -> dict:
    """The size of the whole history and of what is still to fetch, from the listed zip sizes, scaled by
    the stored bytes per zip byte of what is stored (RATIO before 100 MB is)."""
    full = sum(j["listed"][d][0] for j in jobs.values() for d in j["window_days"])
    left = sum(j["listed"][d][0] for j in jobs.values() for d in j["fetch"])
    d = out_dir()
    have = sum(f.stat().st_size for k in ("raw", "hourly") for f in (d / k).rglob("*.parquet")) if d.exists() else 0
    ratio = have / (full - left) if full - left > 1e8 else RATIO
    return {"symbols": len(jobs), "days": sum(len(j["window_days"]) for j in jobs.values()),
            "files_left": sum(len(j["fetch"]) for j in jobs.values()),
            "gaps": sum(len(j["gaps"]) for j in jobs.values()), "zip_gb_full": full / 1e9, "zip_gb_left": left / 1e9,
            "ratio": ratio, "gb_full": full * ratio / 1e9, "gb_left": left * ratio / 1e9, "stored_gb": have / 1e9,
            "max_gb": MAX_GB}


# ---------------------------------------------------------------------------
# Delistings: Binance's announcements, else the archive
# ---------------------------------------------------------------------------

ANN_LIST = ("https://www.binance.com/bapi/composite/v1/public/cms/article/list/query"
            "?type=1&catalogId={c}&pageNo={p}&pageSize=50")
ANN_DETAIL = "https://www.binance.com/bapi/composite/v1/public/cms/article/detail/query?articleCode={code}"
CATALOG_DELIST = 161
CATALOG_NEWS = 49           # the monitoring tag announcements
DELIST_SCHEMA = {"symbol": pl.String, "base": pl.String, "kind": pl.String, "announced_us": pl.Int64,
                 "delisted_us": pl.Int64, "source": pl.String, "article": pl.String}
DELIST_KEYS = ["symbol", "kind", "source", "article"]
TICKER = re.compile(r"^[0-9A-Z]{2,15}$")
PERP = re.compile(r"\b((?:1000000|10000|1000)?[0-9A-Z]{2,20}USDT)\b")
DAY_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")


def _tickers(s: str) -> list[str]:
    parts = re.split(r",|\band\b|&", re.sub(r"\([^)]*\)", "", s))
    return [t for t in (p.strip() for p in parts) if TICKER.match(t)]


def _day_us(s: str | None) -> int | None:
    m = DAY_RE.search(s or "")
    return pit.us_of(date.fromisoformat(m.group(1))) if m else None


def parse_title(title: str) -> tuple[str | None, list[str], int | None]:
    """(kind, symbols, delisted_us) of one announcement title; kind None for anything else (pairs,
    margin, leveraged tokens, options, COIN-M only, Alpha, loans). A perp title without its symbols
    ("Multiple") gives kind perp and no symbols: the body names them."""
    t = " ".join(title.split())
    when = _day_us(t)
    if re.search(r"Monitoring Tag", t, re.I):
        if re.search(r"\bRemov", t, re.I):
            return None, [], None
        m = re.search(r"Include (.+?)(?: on \d{4}-\d{2}-\d{2}|$)", t)
        return ("monitoring", [f"{b}USDT" for b in _tickers(m.group(1))], None) if m else (None, [], None)
    # case-sensitive: a ticker (ALPHA, EARN) is upper case
    if re.search(r"Leveraged Tokens?|\bOptions\b|\bLoans?\b|Margin (?:Pairs?|Trading)|Trading Pairs?|Binance Alpha|"
                 r"\bEarn\b|\bStaking\b|Postponed|Dual Investment", t) and not re.search(r"Futures Contracts", t):
        return None, [], None
    if re.search(r"Futures|Perpetual|USDT-Margined|USD.-M", t):
        syms = PERP.findall(t)
        m = re.search(r"Delist (?:USDT-Margined )?(.+?) USDT-Margined", t)
        if m and not syms:
            syms = [f"{b}USDT" for b in _tickers(m.group(1))]
        if not syms and re.search(r"COIN-M", t) and not re.search(r"USD.-M|USDT", t):
            return None, [], None
        return "perp", syms, when
    m = re.search(r"Binance (?:Will|to) Delist (.+?) on (\d{4}-\d{2}-\d{2})", t)
    if m:
        return "spot", [f"{b}USDT" for b in _tickers(m.group(1))], _day_us(m.group(2))
    return None, [], None


def body_text(doc: dict) -> str:
    """The text of an article (its body is a JSON tree of nodes)."""
    try:
        body = json.loads((doc.get("data") or {}).get("body") or "{}")
    except (TypeError, ValueError):
        return ""
    out: list[str] = []

    def walk(n):
        if isinstance(n, dict):
            if n.get("node") == "text":
                out.append(str(n.get("text") or ""))
            for c in n.get("child") or []:
                walk(c)
    walk(body)
    return " ".join(out)


def _article_rows(a: dict, cat: int, fetch: pit.Fetch) -> list[dict]:
    title, rel = str(a.get("title") or ""), int(a.get("releaseDate") or 0) * 1000
    kind, syms, when = parse_title(title)
    if kind is None or (cat == CATALOG_NEWS and kind != "monitoring"):
        return []
    if kind == "perp" and not syms:
        text = body_text(fetch(ANN_DETAIL.format(code=a.get("code"))) or {})
        syms = sorted(set(PERP.findall(text)))
        when = when or _day_us(text)
    return [{"symbol": s, "base": base_of(s), "kind": kind, "announced_us": rel, "delisted_us": when,
             "source": "announcement", "article": str(a.get("id") or "")} for s in dict.fromkeys(syms)]


def catalog(fetch: pit.Fetch, cat: int, page: int = 1, stop_us: int | None = None,
            pages: int = 100) -> tuple[list[dict], int | None, str | None]:
    """(rows, next page, error) of one catalogue from `page`, newest first, at most `pages` pages, until
    an article older than stop_us or the last page (next page None). After an error (a 429 the
    retries did not get past) the rows read so far and the page to resume at."""
    rows: list[dict] = []
    for p in range(page, page + pages):
        try:
            doc = fetch(ANN_LIST.format(c=cat, p=p))
            arts = [a for c in ((doc or {}).get("data") or {}).get("catalogs") or [] for a in c.get("articles") or []]
            got = [r for a in arts for r in _article_rows(a, cat, fetch)]
        except Exception as e:  # keep what was read; the next run resumes here
            return rows, p, f"{type(e).__name__}: {e}"[:300]
        if not arts:
            return rows, None, None
        rows += got
        if stop_us is not None and min(int(a.get("releaseDate") or 0) * 1000 for a in arts) < stop_us:
            return rows, None, None
    return rows, page + pages, None


def announcements(fetch: pit.Fetch, since_us: int | None, max_pages: int = 100) -> list[dict]:
    """Rows of the delisting catalogue and the news catalogue's monitoring tags, newest pages first,
    until an article older than since_us (all pages when None)."""
    rows: list[dict] = []
    for cat in (CATALOG_DELIST, CATALOG_NEWS):
        got, _, err = catalog(fetch, cat, 1, since_us, max_pages)
        if err:
            raise RuntimeError(err)
        rows += got
    return rows


def archive_stops(listings: dict[str, dict[date, tuple[int, int]]], until: date) -> list[dict]:
    """Perps whose bookDepth files stopped more than RECENT_DAYS before `until`: delisted the day after
    the last file, announcement unknown (known two days after the last file, when the next is missing)."""
    rows = []
    for s, lst in listings.items():
        if lst and max(lst) < until - timedelta(days=RECENT_DAYS):
            last = pit.us_of(max(lst))
            rows.append({"symbol": s, "base": base_of(s), "kind": "perp", "announced_us": None,
                         "delisted_us": last + DAY_US, "source": "archive", "article": "",
                         "known": last + 2 * DAY_US})
    return rows


def delist_frame(rows: list[dict], collected: int) -> pl.DataFrame:
    if not rows:
        return pl.DataFrame(schema={**DELIST_SCHEMA, **{c: pl.Int64 for c in pit.PIT[:3]}, "backfilled": pl.Boolean})
    df = pl.DataFrame([{k: r.get(k) for k in DELIST_SCHEMA} | {"known": r.get("known") or r.get("announced_us")}
                       for r in rows], schema={**DELIST_SCHEMA, "known": pl.Int64})
    df = df.with_columns(ts_us=pl.coalesce("announced_us", "delisted_us"))
    return pit.stamp(df, collected, known=pl.col("known"), backfilled=True).drop("known")


def save_delistings(new: pl.DataFrame) -> dict:
    """Store the rows not stored yet (the first value seen for a key wins, as pit.append)."""
    p = out_dir() / "delistings.parquet"
    old = pl.read_parquet(p) if p.exists() else None
    if old is not None and not new.is_empty():
        new = new.select(old.columns).join(old.select(DELIST_KEYS), on=DELIST_KEYS, how="anti")
    new = new.unique(DELIST_KEYS, keep="first")
    out = new if old is None else pl.concat([old, new], how="vertical_relaxed")
    _write(p, out.sort("ts_us", "symbol"))
    print(f"  delistings: {new.height} new, {out.height} stored", flush=True)
    return {"new": new.height, "stored": out.height}


def read_delistings() -> pl.DataFrame:
    p = out_dir() / "delistings.parquet"
    return pl.read_parquet(p) if p.exists() else delist_frame([], 0)


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

def health(listings: dict[str, dict], errors: dict[str, str], now: int, dry: bool) -> dict:
    """Newest stored hour of the perps still in the archive (the oldest of them), gaps in their last
    7 days, the delisting table; the format of pit.write_health."""
    live = [s for s, lst in listings.items() if lst and max(lst) >= pit.day_of(now) - timedelta(days=RECENT_DAYS)]
    lasts, gaps, rows = [], 0, 0
    for s in live:
        files = sorted((out_dir() / "hourly" / f"symbol={s}").glob("*.parquet"))
        if not files:
            continue
        h = pl.read_parquet(files[-1], columns=["ts_us"])
        rows += h.height
        if h.height:
            lasts.append(int(h["ts_us"].max()))
            gaps += pit.gaps(h["ts_us"].to_list(), DAY_US, now)
    d = read_delistings()
    tables = {"hourly": {"rows": rows, "last_ts_us": min(lasts) if lasts else None, "gaps": gaps, "missing": [],
                         "schema_ok": True},
              "delistings": {"rows": d.height, "last_ts_us": int(d["collected_us"].max()) if d.height else None,
                             "gaps": 0, "missing": [], "schema_ok": True}}
    doc = {"at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), "source": "book_depth", "tables": tables,
           "errors": errors}
    if not dry:
        _write(out_dir() / "health.json", doc)
    return doc


def run(until: date | None = None, symbols: list[str] | None = None, max_files: int = 60_000,
        only_estimate: bool = False, delistings: bool = True, dry: bool = False, fetch=None,
        fetch_json: pit.Fetch | None = None) -> dict:
    until = until or (datetime.now(UTC).date() - timedelta(days=1))
    fetch = fetch or get
    pacer = um_metrics.Pacer(RATE)
    errors: dict[str, str] = {}
    pl_ = plan(until)
    if symbols:
        pl_ = {s: w for s, w in pl_.items() if s in symbols}
    jobs: dict[str, dict] = {}
    lock = threading.Lock()

    def lst(s):
        try:
            got = listing(s, pacer, fetch)
        except Exception as e:  # one symbol's listing failing does not stop the others
            with lock:
                errors[f"list {s}"] = f"{type(e).__name__}: {e}"[:300]
            return
        a, b = pl_[s]
        f, g = todo(s, (a, b), got, manifest(s))
        days = [d for d in got if a <= d <= b]
        with lock:
            jobs[s] = {"listed": got, "window_days": days, "fetch": f, "gaps": g}

    with ThreadPoolExecutor(WORKERS) as ex:
        list(ex.map(lst, list(pl_)))
    est = estimate(jobs)
    est["at"] = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"book_depth: {est['symbols']} symbols, {est['days']:,} days in the archive, {est['gaps']} gaps; "
          f"the whole history {est['zip_gb_full']:.1f} GB zipped, about {est['gb_full']:.1f} GB stored "
          f"(ratio {est['ratio']:.2f}), {est['files_left']:,} files left, about {est['gb_left']:.1f} GB", flush=True)
    if not dry:
        _write(out_dir() / "estimate.json", est)
    # the rule is for the backfill: once only the new days are left the store grows by them (the
    # dataset row of jobs.yaml watches its size)
    backfill = est["files_left"] > (RECENT_DAYS + 1) * max(1, est["symbols"])
    if est["gb_full"] > MAX_GB and backfill:
        print(f"book_depth: over the {MAX_GB:.0f} GB budget; nothing fetched, see estimate.json", flush=True)
        errors["budget"] = f"the whole history would take {est['gb_full']:.1f} GB (over {MAX_GB:.0f} GB)"
        health({s: j["listed"] for s, j in jobs.items()}, errors, pit.now_us(), dry)
        return {**est, "fetched": 0, "errors": errors}
    if only_estimate or dry:
        return {**est, "fetched": 0, "errors": errors}

    # every symbol's newest days first, then the backfill oldest first, at most max_files in all
    recent = until - timedelta(days=RECENT_DAYS)
    picked = {s: [d for d in j["fetch"] if d > recent] for s, j in jobs.items()}
    left = max_files - sum(len(v) for v in picked.values())
    for s, j in sorted(jobs.items()):
        old = [d for d in j["fetch"] if d <= recent][:max(0, left)]
        picked[s] += old
        left -= len(old)
    done = {"ok": 0, "bad": 0, "missing": 0, "bytes": 0}
    t0 = time.time()

    def one(s):
        try:
            got = collect_symbol(s, picked[s], jobs[s]["listed"], pacer, fetch)
        except Exception as e:  # one symbol failing does not stop the others
            with lock:
                errors[s] = f"{type(e).__name__}: {e}"[:300]
            return
        with lock:
            for k in done:
                done[k] += got[k]
            print(f"  {s}: {got['ok']} files ({done['ok']:,} in all, {time.time() - t0:.0f}s)", flush=True)

    with ThreadPoolExecutor(WORKERS) as ex:
        list(ex.map(one, [s for s, v in picked.items() if v]))
    if delistings:
        pit.step(errors, "delistings", lambda: update_delistings({s: j["listed"] for s, j in jobs.items()}, until,
                                                                 fetch_json or pit.paced(3.0)))
    health({s: j["listed"] for s, j in jobs.items()}, errors, pit.now_us(), False)
    print(f"book_depth: {done['ok']:,} files stored, {done['bad']} failed their checksum, "
          f"{done['missing']} gone, {time.time() - t0:.0f}s", flush=True)
    return {**est, "fetched": done["ok"], "bad": done["bad"], "errors": errors}


def update_delistings(listings: dict[str, dict], until: date, fetch_json: pit.Fetch) -> dict:
    """New announcements (back to 30 days before the newest stored), the history of each catalogue
    until it is complete (resumed at the page announcements.json names), the archive's stops of
    perps no announcement names. Rows read before an error are stored, then the error is raised."""
    old = read_delistings()
    ann = old.filter(pl.col("source") == "announcement")
    since = int(ann["announced_us"].max()) - 30 * DAY_US if ann.height else None
    sp = out_dir() / "announcements.json"
    state = _json(sp, {})
    rows, errs = [], []
    for cat in (CATALOG_DELIST, CATALOG_NEWS):
        st = state.get(str(cat)) or {"next": 1}
        if since is not None:
            got, _, err = catalog(fetch_json, cat, 1, since)
            rows += got
            if err:
                errs.append(f"catalogue {cat}: {err}")
                continue
        if st.get("next") is not None:
            got, nxt, err = catalog(fetch_json, cat, int(st["next"]))
            state[str(cat)] = {"next": nxt}
            rows += got
            if err:
                errs.append(f"catalogue {cat}: {err}")
    named = {r["symbol"] for r in rows if r["kind"] != "monitoring"} | set(
        ann.filter(pl.col("kind") != "monitoring")["symbol"].to_list())
    rows += [r for r in archive_stops(listings, until) if r["symbol"] not in named]
    res = save_delistings(delist_frame(rows, pit.now_us()))
    _write(sp, state)
    if errs:
        raise RuntimeError("; ".join(errs))
    return res


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--until", type=date.fromisoformat, default=None)
    ap.add_argument("--symbols", default="")
    ap.add_argument("--max-files", type=int, default=60_000)
    ap.add_argument("--estimate", action="store_true", help="list the archive and write the size estimate only")
    ap.add_argument("--no-delistings", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    res = run(a.until, [s for s in a.symbols.split(",") if s] or None, a.max_files, a.estimate,
              not a.no_delistings, a.dry_run)
    errors = res.get("errors") or {}
    return 1 if "budget" in errors else pit.exit_code(errors, (res.get("symbols") or 0) + 1)


if __name__ == "__main__":
    sys.exit(main())
