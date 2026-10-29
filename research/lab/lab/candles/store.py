"""C1: one candle API over every market Pythia looks at, every timeframe, point in time.

    from lab.candles.store import candles
    candles("BTC", "15m", "2026-10-01", "2026-10-02")      Binance spot, built from 1m
    candles("SPYx", "1h")                                   the token's deepest Solana pool (GeckoTerminal)
    candles("SPY", "1d")                                    the underlying (Yahoo)
    candles("BTC", "1m", source="kraken")                   built from the recorded Kraken trades

    python -m lab.candles.store compact    merge every month's parts into its file, finished months final
    python -m lab.candles.store report     the gap report: reports/candle_coverage_c1 (and results/ with
                                           PYTHIA_RESULTS)
    python -m lab.candles.store health     exit 1 when the live candles are stale (job candles-health)

candles(asset, timeframe, start, end, source=None, as_of=None) gives the bars opening in [start, end) for
1m 5m 15m 1h 4h 1d 1w (UTC buckets, weeks from Monday) with open, high, low, close, volume (base), quote
volume, trades, taker buy share, VWAP (quote over base volume), the source and `complete`. A bar is built
from the finest layer its source has for that span and only from sub-bars closed by as_of (default now);
a bar still forming, or whose layer ends before the bar does, has complete False. complete_only drops them.

Sources and their layers, finest first (a coarser layer fills only the span before or after the finer one):
  binance   hist/binance_spot/klines_1m (recorder backfill, 20 coins from 2020) with the store's binance_rest
            1m rows where the archive has none (its newest day lags about a day), then the archive's 5m,
            1h (683 pairs, PAXG among them) and 1d (from 2017). Asset BTC is BTCUSDT. A bar's source says
            the layer: binance (1m archive), binance_rest, binance_5m, binance_1h, binance_1d.
  kraken    1m built from the recorded Kraken trades (USD pairs), buy and sell volume split by the taker side,
            with ref_dev_bps: the close against Binance's 1m close of the minute (flagged above 50 bp)
  gecko     the deepest USDC or SOL pool of a Solana token on GeckoTerminal, 1h and 1d in USD, quote volume
            only, liquidity_usd read when the bar was collected (null in the backfill)
  yahoo     the underlyings' 1h bars (the last 730 days, sessions at :30) for timeframes below 1d, their 1d
            bars (open at 00:00 UTC of the trading day, known from the next UTC midnight) for 1d and 1w
The default source is binance when the asset has Binance data, else gecko, yahoo, kraken.

Point in time: an exchange bar is known at its close; only bars closed by as_of are read, the GeckoTerminal
liquidity only when its fetch was before as_of. Nothing in the store is a bar still forming: the collectors
drop it.

Storage (written by lab.candles.live) under <write root>/candles/:
  source=<s>/asset=<a>/tf=<tf>/<YYYY-MM>.parquet         a compacted month
  source=<s>/asset=<a>/tf=<tf>/<YYYY-MM>/part-*.parquet  rows written since, merged by compact()
  manifest.json      per source/asset/tf: first and last bar, rows, months (rows, parts, final), updated
Reads look in the write folder and the data folder (PYTHIA_WRITE_ROOT, PYTHIA_DATA), newest row wins. The
Binance archive is read where the recorder keeps it, never copied.
"""

from __future__ import annotations

import argparse
import fcntl
import itertools
import json
import os
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import polars as pl

from .. import data
from ..data import UNIVERSE

MIN = 60_000_000
HOUR = 60 * MIN
DAY = 24 * HOUR
TF = {"1m": MIN, "5m": 5 * MIN, "15m": 15 * MIN, "1h": HOUR, "4h": 4 * HOUR, "1d": DAY, "1w": 7 * DAY}
WEEK_OFF = 4 * DAY                    # 1970-01-01 was a Thursday: weeks start on Monday 00:00 UTC
SOURCES = ("binance", "binance_rest", "kraken", "gecko", "yahoo")
DEFAULT_ORDER = ("binance", "gecko", "yahoo", "kraken")
ARCHIVE = {"1m": "klines_1m", "5m": "klines_5m", "1h": "klines_1h", "1d": "klines_1d"}
DISAGREE_BPS = 50.0                   # Kraken's close more than 0.5 % from Binance's
CONFIG = Path(__file__).with_name("markets.json")
F, I = pl.Float64, pl.Int64
_SEQ = itertools.count()              # parts written in one run never share a name
STORE_SCHEMA = {"open_time_us": I, "close_time_us": I, "open": F, "high": F, "low": F, "close": F, "volume": F,
                "quote_volume": F, "trades": I, "taker_buy_volume": F, "taker_buy_quote_volume": F,
                "fetched_us": I, "liquidity_usd": F, "ref_dev_bps": F}
OUT_COLS = ["asset", "timeframe", "open_time_us", "close_time_us", "open", "high", "low", "close", "volume",
            "quote_volume", "trades", "taker_buy_share", "vwap", "source", "complete", "taker_buy_volume",
            "taker_buy_quote_volume", "liquidity_usd", "ref_dev_bps", "bars"]


def config() -> dict:
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def now_us() -> int:
    return int(time.time() * 1e6)


def to_us(t) -> int:
    """int (us), datetime or 'YYYY-MM-DD[THH:MM]' (UTC) to microseconds."""
    if isinstance(t, (int, np.integer)):
        return int(t)
    if isinstance(t, datetime):
        return int((t if t.tzinfo else t.replace(tzinfo=timezone.utc)).timestamp() * 1e6)
    return to_us(datetime.fromisoformat(str(t)))


def month_of(us: int) -> str:
    return datetime.fromtimestamp(us / 1e6, timezone.utc).strftime("%Y-%m")


def bucket(us, tf: str):
    off = WEEK_OFF if tf == "1w" else 0
    return (us - off) // TF[tf] * TF[tf] + off


def bucket_expr(tf: str) -> pl.Expr:
    off = WEEK_OFF if tf == "1w" else 0
    return (pl.col("open_time_us") - off) // TF[tf] * TF[tf] + off


# ---------------------------------------------------------------- where things are

def out_dir(root: Path | None = None) -> Path:
    return (root or data.WRITE_ROOT) / "candles"


def store_dirs(root: Path | None = None) -> list[Path]:
    """The folders read, lowest priority first: the data folder's, then the write folder's (it wins)."""
    if root is not None:
        return [root / "candles"]
    return list(dict.fromkeys([data.ROOT / "candles", data.WRITE_ROOT / "candles"]))


def key_dir(base: Path, source: str, asset: str, tf: str) -> Path:
    return base / f"source={source}" / f"asset={asset}" / f"tf={tf}"


def archive_dir(tf: str, asset: str, root: Path | None = None) -> Path:
    return (root or data.ROOT) / "hist" / "binance_spot" / ARCHIVE[tf] / f"symbol={asset}USDT"


def _month_ok(name: str, lo_m: str, hi_m: str) -> bool:
    return lo_m <= name[:7] <= hi_m


def _read(files: list[Path], columns=None) -> list[pl.DataFrame]:
    out = []
    for f in files:
        try:
            out.append(pl.read_parquet(f, columns=columns))
        except (OSError, pl.exceptions.PolarsError):
            continue                  # a part compacted away while it was listed
    return out


def norm(df: pl.DataFrame) -> pl.DataFrame:
    """Any rows to the store's columns, in its types, missing ones null."""
    if not df.height:
        return pl.DataFrame(schema=STORE_SCHEMA)
    return df.select([(pl.col(c) if c in df.columns else pl.lit(None)).cast(t).alias(c)
                      for c, t in STORE_SCHEMA.items()])


def read_archive(tf: str, asset: str, lo: int, hi: int, root: Path | None = None) -> pl.DataFrame:
    """The Binance archive's bars opening in [lo, hi), in the store's columns."""
    d = archive_dir(tf, asset, root)
    lo_m, hi_m = month_of(lo), month_of(max(lo, hi - 1))
    files = sorted(f for f in d.glob("*.parquet") if _month_ok(f.stem, lo_m, hi_m)) if d.is_dir() else []
    parts = _read(files)
    if not parts:
        return norm(pl.DataFrame())
    k = pl.concat(parts, how="diagonal_relaxed")
    if tf == "1d":
        k = k.rename({"day": "open_time_us", "qv": "quote_volume", "n": "trades", "taker_qv": "taker_buy_quote_volume"})
    elif tf == "5m":
        k = k.rename({"n_trades": "trades"}) if "n_trades" in k.columns else k
    k = k.with_columns(close_time_us=pl.col("open_time_us") + TF[tf])
    return norm(k).filter(pl.col("open_time_us").is_between(lo, hi, closed="left")).unique(
        "open_time_us", keep="last").sort("open_time_us")


def read_store(source: str, asset: str, tf: str, lo: int = 0, hi: int = 2**62, root: Path | None = None) -> pl.DataFrame:
    """The store's rows opening in [lo, hi): month files and their parts, the newest row of a bar wins."""
    lo_m, hi_m = month_of(max(lo, 0)), month_of(min(hi, 4_102_444_800_000_000) - 1)
    files = []
    for base in store_dirs(root):
        d = key_dir(base, source, asset, tf)
        if not d.is_dir():
            continue
        for m in sorted(p for p in d.glob("*.parquet") if _month_ok(p.stem, lo_m, hi_m)):
            files.append(m)
            files += sorted((d / m.stem).glob("part-*.parquet"))
        for sub in sorted(p for p in d.iterdir() if p.is_dir() and _month_ok(p.name, lo_m, hi_m)):
            if not (d / f"{sub.name}.parquet").exists():
                files += sorted(sub.glob("part-*.parquet"))
    parts = [norm(p) for p in _read(files)]
    if not parts:
        return norm(pl.DataFrame())
    return (pl.concat(parts).filter(pl.col("open_time_us").is_between(lo, hi, closed="left"))
            .unique("open_time_us", keep="last").sort("open_time_us"))


def store_assets(source: str, tf: str | None = None, root: Path | None = None) -> list[str]:
    out = set()
    for base in store_dirs(root):
        for d in (base / f"source={source}").glob("asset=*"):
            if tf is None or (d / f"tf={tf}").is_dir():
                out.add(d.name.removeprefix("asset="))
    return sorted(out)


def archive_assets(tf: str = "1m", root: Path | None = None) -> list[str]:
    d = (root or data.ROOT) / "hist" / "binance_spot" / ARCHIVE[tf]
    return sorted(p.name.removeprefix("symbol=").removesuffix("USDT") for p in d.glob("symbol=*USDT")) \
        if d.is_dir() else []


# ---------------------------------------------------------------- writing, the manifest, compaction

@contextmanager
def _locked(base: Path):
    base.mkdir(parents=True, exist_ok=True)
    with open(base / "manifest.lock", "w") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def read_manifest(root: Path | None = None) -> dict:
    for base in reversed(store_dirs(root)):
        try:
            return json.loads((base / "manifest.json").read_text())
        except (OSError, ValueError):
            continue
    return {"markets": {}}


def _write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, indent=1, sort_keys=True))
    os.replace(tmp, path)


def _write_parquet(df: pl.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    df.write_parquet(tmp, compression="zstd")
    os.replace(tmp, path)


def _month_stats(d: Path, month: str) -> dict:
    files = ([d / f"{month}.parquet"] if (d / f"{month}.parquet").exists() else []) + \
        sorted((d / month).glob("part-*.parquet"))
    t = [x for x in _read(files, ["open_time_us", "close_time_us"]) if x.height]
    t = pl.concat(t).unique("open_time_us") if t else None
    return {"rows": 0 if t is None else t.height, "parts": len(files) - (1 if (d / f"{month}.parquet").exists() else 0),
            "first_us": None if t is None else int(t["open_time_us"].min()),
            "last_end_us": None if t is None else int(t["close_time_us"].max())}


def _update_manifest(base: Path, source: str, asset: str, tf: str, months: list[str], now: int,
                     final: set[str] = frozenset()) -> None:
    with _locked(base):
        try:
            man = json.loads((base / "manifest.json").read_text())
        except (OSError, ValueError):
            man = {"markets": {}}
        e = man["markets"].setdefault(f"{source}/{asset}/{tf}", {"months": {}})
        d = key_dir(base, source, asset, tf)
        for m in months:
            s = _month_stats(d, m)
            prev = e["months"].get(m, {})
            e["months"][m] = {"rows": s["rows"], "parts": s["parts"], "final": bool(prev.get("final")) or m in final,
                              "first_us": s["first_us"], "last_end_us": s["last_end_us"]}
        ms = [v for v in e["months"].values() if v.get("rows")]
        e.update(first_us=min(v["first_us"] for v in ms) if ms else None,
                 last_end_us=max(v["last_end_us"] for v in ms) if ms else None,
                 rows=sum(v["rows"] for v in ms), updated_us=now)
        man["updated_us"] = now
        _write_json(base / "manifest.json", man)


def write(source: str, asset: str, tf: str, rows: pl.DataFrame, now: int | None = None,
          root: Path | None = None) -> int:
    """Append bars as one part per month they fall in; the manifest follows. Returns the rows written."""
    if source not in SOURCES or tf not in TF:
        raise ValueError(f"{source}/{tf}: unknown source or timeframe")
    rows = norm(rows).drop_nulls("open_time_us")
    if not rows.height:
        return 0
    now = now or now_us()
    base = out_dir(root)
    d = key_dir(base, source, asset, tf)
    rows = rows.with_columns(_m=pl.from_epoch("open_time_us", "us").dt.strftime("%Y-%m"))
    months = sorted(rows["_m"].unique().to_list())
    for m in months:
        _write_parquet(rows.filter(pl.col("_m") == m).drop("_m").sort("open_time_us"),
                       d / m / f"part-{now}-{os.getpid()}-{next(_SEQ):05d}.parquet")
    _update_manifest(base, source, asset, tf, months, now)
    return rows.height


def compact(now: int | None = None, root: Path | None = None, log=print) -> dict:
    """Merge every month's parts into its month file (newest row of a bar wins) and mark the months
    before the current one final. Only the write folder is touched."""
    now = now or now_us()
    base, cur = out_dir(root), month_of(now)
    merged = final = 0
    for d in sorted(base.glob("source=*/asset=*/tf=*")):
        source, asset, tf = (p.split("=", 1)[1] for p in d.relative_to(base).parts)
        months = sorted({p.stem for p in d.glob("*.parquet")} | {p.name for p in d.iterdir() if p.is_dir()})
        touched = []
        for m in months:
            parts = sorted((d / m).glob("part-*.parquet")) if (d / m).is_dir() else []
            if parts:
                files = ([d / f"{m}.parquet"] if (d / f"{m}.parquet").exists() else []) + parts
                t = pl.concat([norm(x) for x in _read(files)]).unique("open_time_us", keep="last").sort("open_time_us")
                _write_parquet(t, d / f"{m}.parquet")
                for p in parts:
                    p.unlink(missing_ok=True)
                merged += 1
            if (d / m).is_dir() and not any((d / m).iterdir()):
                (d / m).rmdir()
            touched.append(m)
        done = {m for m in touched if m < cur}
        final += len(done)
        _update_manifest(base, source, asset, tf, touched, now, final=done)
        log(f"  {source}/{asset}/{tf}: {len(touched)} months, {len(done)} final")
    return {"merged_months": merged, "final_months": final}


# ---------------------------------------------------------------- the API

def default_source(asset: str, root: Path | None = None) -> str | None:
    for s in DEFAULT_ORDER:
        if s == "binance":
            if any(archive_dir(tf, asset, root).is_dir() for tf in ARCHIVE) or asset in store_assets("binance_rest", "1m", root):
                return s
        elif asset in store_assets(s, None, root):
            return s
    return None


def layers(source: str, asset: str, tf: str, root: Path | None = None) -> list[tuple[str, object]]:
    """[(native timeframe, (lo, hi) -> rows with a src column)], finest first, the ones usable for tf."""
    def arc(native):
        label = "binance" if native == "1m" else f"binance_{native}"
        return lambda lo, hi: read_archive(native, asset, lo, hi, root).with_columns(src=pl.lit(label))

    def st(src, native):
        return lambda lo, hi: read_store(src, asset, native, lo, hi, root).with_columns(src=pl.lit(src))

    def one_minute(lo, hi):
        a, r = arc("1m")(lo, hi), st("binance_rest", "1m")(lo, hi)
        return pl.concat([r, a]).unique("open_time_us", keep="last").sort("open_time_us")   # the archive wins

    if source == "binance":
        out = [("1m", one_minute), ("5m", arc("5m")), ("1h", arc("1h")), ("1d", arc("1d"))]
    elif source == "kraken":
        out = [("1m", st("kraken", "1m"))]
    elif source == "gecko":
        out = [("1h", st("gecko", "1h")), ("1d", st("gecko", "1d"))]
    elif source == "yahoo":
        out = [("1h", st("yahoo", "1h"))] if TF[tf] < DAY else [("1d", st("yahoo", "1d"))]
    else:
        raise ValueError(f"unknown source {source}")
    return [(n, fn) for n, fn in out if TF[n] <= TF[tf] and TF[tf] % TF[n] == 0]


def _sum(c: str) -> pl.Expr:
    return pl.when(pl.col(c).is_not_null().any()).then(pl.col(c).sum()).alias(c)


def aggregate(sub: pl.DataFrame, tf: str, as_of: int, last_end: int) -> pl.DataFrame:
    """Sub-bars (store columns and src) to bars of tf; complete when the bar has ended by as_of and the
    layer's data reaches its end."""
    b = (sub.sort("open_time_us").with_columns(_b=bucket_expr(tf))
         .group_by("_b", maintain_order=True)
         .agg(pl.col("open").first(), pl.col("high").max(), pl.col("low").min(), pl.col("close").last(),
              *[_sum(c) for c in ("volume", "quote_volume", "trades", "taker_buy_volume", "taker_buy_quote_volume")],
              pl.col("liquidity_usd").drop_nulls().last(),
              pl.when(pl.col("ref_dev_bps").max().abs() >= pl.col("ref_dev_bps").min().abs())
              .then(pl.col("ref_dev_bps").max()).otherwise(pl.col("ref_dev_bps").min()).alias("ref_dev_bps"),
              pl.col("src").last().alias("source"), pl.len().alias("bars"), pl.col("open_time_us").min().alias("_first")))
    end = pl.col("_b") + TF[tf]
    vol = pl.col("volume")
    return b.with_columns(
        open_time_us=pl.col("_b"), close_time_us=end,
        vwap=pl.when(vol > 0).then(pl.col("quote_volume") / vol),
        taker_buy_share=pl.when(pl.col("quote_volume") > 0).then(pl.col("taker_buy_quote_volume") / pl.col("quote_volume"))
        .otherwise(pl.when(vol > 0).then(pl.col("taker_buy_volume") / vol)),
        complete=(end <= as_of) & (end <= last_end)).drop("_b")


def candles(asset: str, timeframe: str, start=None, end=None, source: str | None = None, as_of=None,
            complete_only: bool = False, root: Path | None = None) -> pl.DataFrame:
    """Bars of `asset` opening in [start, end) at `timeframe`, as known at as_of (default now). Columns
    OUT_COLS; empty when there is no data."""
    if timeframe not in TF:
        raise ValueError(f"timeframe {timeframe}: one of {', '.join(TF)}")
    asset = asset[:-4] if asset.endswith("USDT") and len(asset) > 4 else asset
    now = to_us(as_of) if as_of is not None else now_us()
    lo = to_us(start) if start is not None else 0
    hi = min(to_us(end) if end is not None else now, now)
    src = source or default_source(asset, root)
    empty = pl.DataFrame(schema={c: (pl.String if c in ("asset", "timeframe", "source") else pl.Boolean
                                     if c == "complete" else pl.UInt32 if c == "bars" else STORE_SCHEMA.get(c, F))
                                 for c in OUT_COLS})
    if src is None or hi <= lo:
        return empty
    p = TF[timeframe]
    r_lo, r_hi = bucket(lo, timeframe), bucket(hi - 1, timeframe) + 2 * p   # whole bars, one more to see the layer go on
    acc = None
    for _native, fn in layers(src, asset, timeframe, root):
        sub = fn(r_lo, r_hi)
        if not sub.height:
            continue
        sub = sub.filter(pl.col("close_time_us") <= now)
        if "fetched_us" in sub.columns:
            sub = sub.with_columns(liquidity_usd=pl.when(pl.col("fetched_us") <= now).then(pl.col("liquidity_usd")))
        if not sub.height:
            continue
        a = aggregate(sub, timeframe, now, int(sub["close_time_us"].max()))
        if acc is None:
            acc = a
            continue
        first, last = int(acc["_first"].min()), int(acc["close_time_us"].max())
        take = a.filter((pl.col("open_time_us") < first) | (pl.col("open_time_us") >= last))
        acc = pl.concat([acc.join(take.select("open_time_us"), on="open_time_us", how="anti"), take], how="diagonal_relaxed")
    if acc is None:
        return empty
    out = (acc.filter(pl.col("open_time_us").is_between(lo, hi, closed="left"))
           .with_columns(asset=pl.lit(asset), timeframe=pl.lit(timeframe)).sort("open_time_us"))
    if complete_only:
        out = out.filter(pl.col("complete"))
    return out.select(OUT_COLS).cast({c: t for c, t in empty.schema.items()})


def measures(bars: pl.DataFrame) -> pl.DataFrame:
    """Candle measures of one asset's bars (one timeframe, sorted): body, shadows and the close's place as
    shares of the range, the range as ln(high / low), taker buy share, close over VWAP minus 1, and the
    returns over 1, 4, 7, 24 and 168 bars (null across a gap)."""
    rng = pl.col("high") - pl.col("low")
    out = bars.with_columns(
        body=pl.when(rng > 0).then((pl.col("close") - pl.col("open")) / rng).otherwise(0.0),
        upper=pl.when(rng > 0).then((pl.col("high") - pl.max_horizontal("open", "close")) / rng).otherwise(0.0),
        lower=pl.when(rng > 0).then((pl.min_horizontal("open", "close") - pl.col("low")) / rng).otherwise(0.0),
        close_pos=pl.when(rng > 0).then((pl.col("close") - pl.col("low")) / rng).otherwise(0.5),
        range=pl.when(pl.col("low") > 0).then((pl.col("high") / pl.col("low")).log()),
        vwap_dist=pl.when(pl.col("vwap") > 0).then(pl.col("close") / pl.col("vwap") - 1))
    if not bars.height:
        return out.with_columns(*[pl.lit(None, F).alias(f"ret_{k}") for k in (1, 4, 7, 24, 168)])
    p = int(bars["close_time_us"][0] - bars["open_time_us"][0])
    for k in (1, 4, 7, 24, 168):
        prev = pl.col("close").shift(k)
        ok = (pl.col("open_time_us") - pl.col("open_time_us").shift(k)) == k * p
        out = out.with_columns(pl.when(ok & (prev > 0)).then(pl.col("close") / prev - 1).alias(f"ret_{k}"))
    return out


def disagreements(asset: str, start=None, end=None, bps: float = DISAGREE_BPS, root: Path | None = None) -> pl.DataFrame:
    """Kraken's 1m bars whose close is more than `bps` from Binance's of the same minute."""
    k = read_store("kraken", asset, "1m", to_us(start) if start is not None else 0,
                   to_us(end) if end is not None else 2**62, root)
    return k.filter(pl.col("ref_dev_bps").abs() > bps).select("open_time_us", "close", "ref_dev_bps")


# ---------------------------------------------------------------- coverage, the gap report, health

def _day(us) -> str:
    return "" if us is None else datetime.fromtimestamp(us / 1e6, timezone.utc).strftime("%Y-%m-%d %H:%M")


def open_times(source: str, asset: str, tf: str, root: Path | None = None) -> np.ndarray:
    """The sorted open times a native layer has (the archive and the REST fill together for binance 1m)."""
    parts = []
    if source == "binance":
        d = archive_dir(tf, asset, root)
        col = "day" if tf == "1d" else "open_time_us"
        parts += [x[col].to_numpy() for x in _read(sorted(d.glob("*.parquet")), [col])] if d.is_dir() else []
        if tf == "1m":
            parts.append(read_store("binance_rest", asset, "1m", root=root)["open_time_us"].to_numpy())
    else:
        parts.append(read_store(source, asset, tf, root=root)["open_time_us"].to_numpy())
    parts = [x for x in parts if len(x)]
    return np.unique(np.concatenate(parts)).astype(np.int64) if parts else np.empty(0, np.int64)


def gaps(t: np.ndarray, tf: str, session: bool = False) -> dict:
    """Missing bars between the first and the last; a session market (Yahoo) only counts breaks longer than
    four days (weekends and holidays are not gaps)."""
    if not len(t):
        return {"first_us": None, "last_us": None, "bars": 0, "missing": 0, "largest": []}
    p = TF[tf]
    d = np.diff(t)
    limit = 4 * DAY if session else p
    idx = np.nonzero(d > limit)[0]
    miss = (d[idx] // p - 1) if len(idx) else np.empty(0, np.int64)
    order = np.argsort(-miss)[:3]
    return {"first_us": int(t[0]), "last_us": int(t[-1]), "bars": int(len(t)), "missing": int(miss.sum()),
            "gaps": int(len(idx)),
            "largest": [f"{_day(int(t[idx[i]]) + p)} .. {_day(int(t[idx[i] + 1]))} ({int(miss[i])})" for i in order]}


def markets(root: Path | None = None) -> list[tuple[str, str, str, str]]:
    """(market, source, asset, native timeframe) the report covers: the lab's coins and PAXG on Binance,
    whatever the store has from Kraken, GeckoTerminal and Yahoo."""
    cfg = config()
    out = []
    for a in list(UNIVERSE) + [x for x in cfg.get("binance_extra", []) if x not in UNIVERSE]:
        for tf in ("1m", "1h", "1d"):
            if archive_dir(tf, a, root).is_dir() or (tf == "1m" and a in store_assets("binance_rest", "1m", root)):
                out.append((f"{a}USDT", "binance", a, tf))
    for s, label in (("kraken", "{}/USD"), ("gecko", "{} (Solana pool)"), ("yahoo", "{}")):
        for a in store_assets(s, None, root):
            for tf in ("1m", "1h", "1d"):
                if any(key_dir(b, s, a, tf).is_dir() for b in store_dirs(root)):
                    out.append((label.format(a), s, a, tf))
    return out


def coverage(root: Path | None = None, log=print) -> list[dict]:
    rows = []
    for market, source, asset, tf in markets(root):
        g = gaps(open_times(source, asset, tf, root), tf, session=source == "yahoo")
        rows.append({"market": market, "source": source, "asset": asset, "timeframe": tf, **g})
        log(f"  {market} {source} {tf}: {_day(g['first_us'])} .. {_day(g['last_us'])}, {g['missing']} missing")
    return rows


def disagreement_summary(root: Path | None = None) -> list[dict]:
    out = []
    for a in store_assets("kraken", "1m", root):
        k = read_store("kraken", a, "1m", root=root)
        cmp_ = k.filter(pl.col("ref_dev_bps").is_not_null())
        if not cmp_.height:
            continue
        bad = cmp_.filter(pl.col("ref_dev_bps").abs() > DISAGREE_BPS)
        out.append({"asset": a, "minutes": cmp_.height, "flagged": bad.height,
                    "median_abs_bps": float(cmp_["ref_dev_bps"].abs().median()),
                    "worst_bps": float(cmp_["ref_dev_bps"].abs().max()),
                    "worst_at": _day(int(cmp_.sort(pl.col("ref_dev_bps").abs())["open_time_us"][-1]))})
    return out


def report(cov: list[dict], dis: list[dict], now: int) -> str:
    lines = ["# C1: candle coverage", "",
             f"Written {_day(now)} UTC by `python -m lab.candles.store report`. One row per market, source and "
             "native timeframe; every timeframe from 1m to 1w is built from these by `lab.candles.store.candles` "
             "(a market with 1m has all seven, one with 1h has 1h, 4h, 1d, 1w). Missing: bars absent between the "
             "first and the last (Yahoo: only breaks longer than four days count). Largest gaps: from .. to "
             "(bars missing).", "",
             "| Market | Source | Native | From | Last bar | Bars | Missing | Gaps | Largest gaps |",
             "|---|---|---|---|---|---|---|---|---|"]
    for r in cov:
        lines.append(f"| {r['market']} | {r['source']} | {r['timeframe']} | {_day(r['first_us'])} | "
                     f"{_day(r['last_us'])} | {r['bars']:,} | {r['missing']:,} | {r.get('gaps', 0)} | "
                     f"{'; '.join(r['largest']) or '-'} |")
    lines += ["", "## Kraken against Binance, 1m closes", "",
              f"Kraken's USD close against Binance's USDT close of the same minute; above {DISAGREE_BPS:.0f} bp "
              "a minute is flagged (`ref_dev_bps` on the Kraken bars, `disagreements()`).", ""]
    if dis:
        lines += ["| Coin | Minutes compared | Flagged | Median abs bp | Worst bp | Worst at |", "|---|---|---|---|---|---|"]
        lines += [f"| {d['asset']} | {d['minutes']:,} | {d['flagged']:,} | {d['median_abs_bps']:.1f} | "
                  f"{d['worst_bps']:.0f} | {d['worst_at']} |" for d in dis]
    else:
        lines.append("No Kraken minutes compared yet.")
    return "\n".join(lines) + "\n"


def health(now: int | None = None, root: Path | None = None) -> tuple[bool, str]:
    """Red when a live source's newest bar is older than its limit (markets.json stale_min): the Binance
    REST fill and the Kraken candles by their newest, every GeckoTerminal pool (the configured tokens and
    coins and any in the store) on its own, 1h under stale_min gecko, 1d under gecko_1d (2 days)."""
    now = now or now_us()
    cfg = config()
    lim = cfg.get("stale_min", {})
    man = read_manifest(root).get("markets", {})
    bad, ok = [], []
    for src, tf in (("binance_rest", "1m"), ("kraken", "1m")):
        ends = {k.split("/")[1]: v.get("last_end_us") for k, v in man.items()
                if k.startswith(f"{src}/") and k.endswith(f"/{tf}") and v.get("last_end_us")}
        limit = float(lim.get(src, 30)) * MIN
        if not ends:
            bad.append(f"{src}: no candles yet")
            continue
        newest = max(ends.values())
        stale = sorted(a for a, e in ends.items() if now - e > limit)
        age = (now - newest) / MIN
        if now - newest > limit:
            bad.append(f"{src} {tf}: newest bar {age:.0f} min old")
        else:
            ok.append(f"{src} {tf} {age:.0f} min" + (f" (stale: {', '.join(stale[:5])})" if stale else ""))
    pools = list(dict.fromkeys(cfg.get("tokens", []) + cfg.get("coins", []) +
                               sorted({k.split("/")[1] for k in man if k.startswith("gecko/")})))
    for tf, limit in (("1h", float(lim.get("gecko", 180)) * MIN), ("1d", float(lim.get("gecko_1d", 2880)) * MIN)):
        late = []
        for a in pools:
            e = (man.get(f"gecko/{a}/{tf}") or {}).get("last_end_us")
            if not e:
                late.append(f"{a} none")
            elif now - e > limit:
                late.append(f"{a} {(now - e) / HOUR:.0f} h")
        if late:
            bad.append(f"gecko {tf}: {len(late)} of {len(pools)} pools over {limit / HOUR:.0f} h ({', '.join(late)})")
        elif pools:
            ok.append(f"gecko {tf} {len(pools)} pools")
    if bad:
        return False, "Candles stale: " + "; ".join(bad) + (f" (ok: {', '.join(ok)})" if ok else "")
    return True, "Candles ok: " + ", ".join(ok)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m lab.candles.store")
    ap.add_argument("command", choices=["compact", "report", "health"])
    a = ap.parse_args(argv)
    if a.command == "health":
        good, msg = health()
        print(msg)
        return 0 if good else 1
    if a.command == "compact":
        print(json.dumps(compact()))
        return 0
    from .. import report as rep
    now = now_us()
    cov, dis = coverage(), disagreement_summary()
    rep.write("candle_coverage_c1", report(cov, dis, now), {"coverage": cov, "disagreements": dis, "at_us": now})
    return 0


if __name__ == "__main__":
    sys.exit(main())
