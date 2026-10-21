"""Daily flow and positioning data that the lake does not get from the recorder. Data only.

Every source is public and keyless. Each run continues from what is stored
(with a few days of overlap, so a value that was still moving is replaced)
and the first run fetches the history back to 2019, so the same command is
the backfill and the daily update.

Sources and their limits
  coinbase   Coinbase Exchange public market data, BTC-USD 1h candles
             (GET /products/BTC-USD/candles, at most 300 candles a request;
             public endpoints allow about 10 requests a second per IP, we send
             about 3). The Coinbase premium is this against Binance BTCUSDT.
  upbit      Upbit quotation API, KRW-BTC day candles (GET /v1/candles/days,
             200 a request; the quotation group allows 10 a second, we send
             about 4). The Upbit day runs 00:00 to 24:00 UTC.
  fx         USD/KRW ECB reference rates through frankfurter.dev (open source,
             no key, no published limit; one request per year of history).
  stables    DefiLlama stablecoins API, circulating USD of USDT (id 1), USDC
             (id 2) and all stablecoins, daily (three requests a run).
  dvol       Deribit public API, BTC and ETH DVOL index, daily candles
             (public/get_volatility_index_data, 1000 a request).
  skew       Deribit public/get_book_summary_by_currency for BTC and ETH
             options: today's snapshot of every option (mark IV, underlying,
             open interest) and, from it, the 25-delta risk reversal and the
             at-the-money IV at 30 days. Deribit serves no history of these
             without a key, so this only accumulates from the first run.

Lake (under $PYTHIA_FLOW, default $PYTHIA_DATA/flow), each a single small file:
  coinbase_btcusd_1h.parquet   ts_us (hour open), open, high, low, close, volume
  upbit_krwbtc_1d.parquet      day_us, open, high, low, close, value_krw
  fx_usdkrw.parquet            day_us, usdkrw (ECB business days only)
  stables.parquet              day_us, usdt, usdc, total (USD)
  dvol.parquet                 day_us, currency, open, high, low, close
  skew.parquet                 ts_us, currency, days, rr25, atm_iv, call25_iv, put25_iv, n_options
  deribit_options/date=YYYY-MM-DD/<currency>.parquet   the raw option snapshot

    python -m lab.collect.flow                 every source
    python -m lab.collect.flow --only dvol,fx
    python -m lab.collect.flow --dry-run       fetch, print counts, write nothing
"""

from __future__ import annotations

import argparse
import http.client
import json
import math
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

import numpy as np
import polars as pl

from ..data import ROOT

FLOW = Path(os.environ.get("PYTHIA_FLOW", str(ROOT / "flow")))
UTC = timezone.utc
START = date(2019, 1, 1)
HOUR_US = 3_600_000_000
DAY_US = 24 * HOUR_US
OVERLAP_DAYS = 3
UA = "pythia-lab flow collector (research, daily)"

COINBASE = "https://api.exchange.coinbase.com"
UPBIT = "https://api.upbit.com/v1"
FRANKFURTER = "https://api.frankfurter.dev/v1"
LLAMA = "https://stablecoins.llama.fi"
DERIBIT = "https://www.deribit.com/api/v2/public"
SOURCES = ("coinbase", "upbit", "fx", "stables", "dvol", "skew")
SKEW_DAYS = 30.0

Fetch = Callable[[str], object]


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

def get_json(url: str, tries: int = 6, pause: float = 0.0) -> object:
    """GET a JSON document; 429 and 5xx are retried with backoff (Retry-After honoured)."""
    last: Exception | None = None
    for k in range(tries):
        if pause:
            time.sleep(pause)
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            last = e
            if e.code != 429 and e.code < 500:
                raise
            wait = float(e.headers.get("Retry-After") or 0) or min(60.0, 2.0 ** k)
            time.sleep(wait)
        except (OSError, http.client.HTTPException, json.JSONDecodeError) as e:
            # A reset or refused connection, a timeout (OSError, URLError is
            # one), a body cut short (IncompleteRead) or bad JSON: try again.
            last = e
            time.sleep(min(60.0, 2.0 ** k))
    raise RuntimeError(f"{url}: no answer after {tries} tries ({last})")


def paced(pause: float) -> Fetch:
    return lambda url: get_json(url, pause=pause)


def us_of(d: date) -> int:
    return int(datetime(d.year, d.month, d.day, tzinfo=UTC).timestamp() * 1e6)


def day_of(ts_us: int) -> date:
    return datetime.fromtimestamp(ts_us / 1e6, UTC).date()


def today() -> date:
    return datetime.now(UTC).date()


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

def read(name: str) -> pl.DataFrame | None:
    p = FLOW / f"{name}.parquet"
    return pl.read_parquet(p) if p.exists() else None


def merge(old: pl.DataFrame | None, new: pl.DataFrame, keys: list[str]) -> pl.DataFrame:
    """New rows replace stored rows with the same keys."""
    if old is None or old.is_empty():
        out = new
    elif new.is_empty():
        out = old
    else:
        out = pl.concat([old, new.select(old.columns)], how="vertical_relaxed")
    return out.unique(keys, keep="last").sort(keys)


def write(name: str, df: pl.DataFrame) -> None:
    FLOW.mkdir(parents=True, exist_ok=True)
    p = FLOW / f"{name}.parquet"
    tmp = p.with_suffix(".tmp")
    df.write_parquet(tmp)
    os.replace(tmp, p)


def resume_from(old: pl.DataFrame | None, col: str, start: date = START) -> date:
    if old is None or old.is_empty():
        return start
    return max(start, day_of(int(old[col].max())) - timedelta(days=OVERLAP_DAYS))


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------

def coinbase(fetch: Fetch, since: date, until: date) -> pl.DataFrame:
    """BTC-USD hourly candles from `since` to the end of `until`, 300 hours a request."""
    rows: list[list] = []
    t = datetime(since.year, since.month, since.day, tzinfo=UTC)
    end = datetime(until.year, until.month, until.day, tzinfo=UTC) + timedelta(days=1)
    while t < end:
        t2 = min(end, t + timedelta(hours=300))
        q = urllib.parse.urlencode({"granularity": 3600, "start": t.isoformat().replace("+00:00", "Z"),
                                    "end": (t2 - timedelta(seconds=1)).isoformat().replace("+00:00", "Z")})
        page = fetch(f"{COINBASE}/products/BTC-USD/candles?{q}")
        rows.extend(page if isinstance(page, list) else [])
        t = t2
    if not rows:
        return pl.DataFrame(schema={"ts_us": pl.Int64, "open": pl.Float64, "high": pl.Float64, "low": pl.Float64,
                                    "close": pl.Float64, "volume": pl.Float64})
    # [time, low, high, open, close, volume]; only completed hours are kept.
    now_us = int(datetime.now(UTC).timestamp() * 1e6)
    df = pl.DataFrame({"ts_us": [int(r[0]) * 1_000_000 for r in rows], "low": [float(r[1]) for r in rows],
                       "high": [float(r[2]) for r in rows], "open": [float(r[3]) for r in rows],
                       "close": [float(r[4]) for r in rows], "volume": [float(r[5]) for r in rows]})
    return (df.filter(pl.col("ts_us") + HOUR_US <= now_us).unique("ts_us", keep="last")
            .select("ts_us", "open", "high", "low", "close", "volume").sort("ts_us"))


def upbit(fetch: Fetch, since: date, market: str = "KRW-BTC") -> pl.DataFrame:
    """Day candles back to `since`, newest first from the API, 200 a request."""
    rows: list[dict] = []
    to: str | None = None
    while True:
        q = {"market": market, "count": 200}
        if to:
            q["to"] = to
        page = fetch(f"{UPBIT}/candles/days?{urllib.parse.urlencode(q)}")
        if not isinstance(page, list) or not page:
            break
        rows.extend(page)
        oldest = min(p["candle_date_time_utc"] for p in page)
        if datetime.fromisoformat(oldest).date() <= since or len(page) < 200:
            break
        to = oldest + "Z"
    if not rows:
        return pl.DataFrame(schema={"day_us": pl.Int64, "open": pl.Float64, "high": pl.Float64, "low": pl.Float64,
                                    "close": pl.Float64, "value_krw": pl.Float64})
    df = pl.DataFrame({
        "day_us": [us_of(datetime.fromisoformat(r["candle_date_time_utc"]).date()) for r in rows],
        "open": [float(r["opening_price"]) for r in rows], "high": [float(r["high_price"]) for r in rows],
        "low": [float(r["low_price"]) for r in rows], "close": [float(r["trade_price"]) for r in rows],
        "value_krw": [float(r["candle_acc_trade_price"]) for r in rows]})
    # Today's candle is still open: keep only closed days.
    return df.filter(pl.col("day_us") < us_of(today())).filter(pl.col("day_us") >= us_of(since)) \
        .unique("day_us", keep="last").sort("day_us")


def fx(fetch: Fetch, since: date, until: date) -> pl.DataFrame:
    """USD/KRW ECB reference rates, one request per calendar year."""
    out: dict[str, float] = {}
    y = since.year
    while y <= until.year:
        a = max(since, date(y, 1, 1))
        b = min(until, date(y, 12, 31))
        doc = fetch(f"{FRANKFURTER}/{a.isoformat()}..{b.isoformat()}?base=USD&symbols=KRW")
        for d, v in (doc.get("rates", {}) if isinstance(doc, dict) else {}).items():
            if "KRW" in v:
                out[d] = float(v["KRW"])
        y += 1
    days = sorted(k for k in out if date.fromisoformat(k) >= since)
    return pl.DataFrame({"day_us": [us_of(date.fromisoformat(d)) for d in days],
                         "usdkrw": [out[d] for d in days]}, schema={"day_us": pl.Int64, "usdkrw": pl.Float64})


def _llama_series(doc: object) -> dict[int, float]:
    out = {}
    for r in doc if isinstance(doc, list) else []:
        v = (r.get("totalCirculatingUSD") or {}).get("peggedUSD")
        if v is not None:
            out[int(r["date"]) * 1_000_000] = float(v)
    return out


def stables(fetch: Fetch) -> pl.DataFrame:
    """USDT, USDC and all stablecoins in circulation (USD), every day DefiLlama has."""
    usdt = _llama_series(fetch(f"{LLAMA}/stablecoincharts/all?stablecoin=1"))
    usdc = _llama_series(fetch(f"{LLAMA}/stablecoincharts/all?stablecoin=2"))
    total = _llama_series(fetch(f"{LLAMA}/stablecoincharts/all"))
    days = sorted(set(usdt) | set(usdc) | set(total))
    return pl.DataFrame({"day_us": days, "usdt": [usdt.get(d) for d in days], "usdc": [usdc.get(d) for d in days],
                         "total": [total.get(d) for d in days]},
                        schema={"day_us": pl.Int64, "usdt": pl.Float64, "usdc": pl.Float64, "total": pl.Float64})


def dvol(fetch: Fetch, since: date, currency: str) -> pl.DataFrame:
    """Daily DVOL candles from `since`, paged backwards through Deribit's continuation."""
    start_ms = us_of(since) // 1000
    end_ms = int(datetime.now(UTC).timestamp() * 1000)
    rows: list[list] = []
    while end_ms and end_ms > start_ms:
        q = urllib.parse.urlencode({"currency": currency, "start_timestamp": start_ms, "end_timestamp": end_ms,
                                    "resolution": "1D"})
        res = (fetch(f"{DERIBIT}/get_volatility_index_data?{q}") or {}).get("result", {})
        data = res.get("data") or []
        rows.extend(data)
        nxt = res.get("continuation")
        if not data or not nxt or nxt >= end_ms:
            break
        end_ms = int(nxt)
    df = pl.DataFrame({"day_us": [int(r[0]) * 1000 for r in rows], "open": [float(r[1]) for r in rows],
                       "high": [float(r[2]) for r in rows], "low": [float(r[3]) for r in rows],
                       "close": [float(r[4]) for r in rows]},
                      schema={"day_us": pl.Int64, "open": pl.Float64, "high": pl.Float64, "low": pl.Float64,
                              "close": pl.Float64})
    return (df.filter(pl.col("day_us") < us_of(today())).unique("day_us", keep="last")
            .with_columns(currency=pl.lit(currency)).sort("day_us"))


# ---------------------------------------------------------------------------
# 25-delta skew from an option snapshot
# ---------------------------------------------------------------------------

MONTHS = {m: i + 1 for i, m in enumerate(("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT",
                                          "NOV", "DEC"))}


def parse_instrument(name: str) -> tuple[datetime, float, str] | None:
    """BTC-27DEC26-100000-C -> (expiry 08:00 UTC, strike, 'C'); None if it does not parse."""
    try:
        _, exp, strike, kind = name.split("-")
        d = int(exp[:-5]); m = MONTHS[exp[-5:-2]]; y = 2000 + int(exp[-2:])
        return datetime(y, m, d, 8, tzinfo=UTC), float(strike.replace("d", ".")), kind
    except (ValueError, KeyError):
        return None


def bs_delta(fwd: float, strike: float, iv: float, t_years: float, kind: str) -> float:
    """Black-76 delta on the forward (rates at 0, as Deribit's inverse options are priced off the future)."""
    from scipy.stats import norm
    if iv <= 0 or t_years <= 0 or fwd <= 0 or strike <= 0:
        return float("nan")
    d1 = (math.log(fwd / strike) + 0.5 * iv * iv * t_years) / (iv * math.sqrt(t_years))
    return float(norm.cdf(d1)) if kind == "C" else float(norm.cdf(d1) - 1)


def skew_row(snap: list[dict], now: datetime, currency: str, target_days: float = SKEW_DAYS) -> dict | None:
    """25-delta risk reversal (call IV minus put IV) and ATM IV per expiry, interpolated in
    variance time to `target_days` between the two expiries around it (the nearest one when
    the target is outside)."""
    per: dict[datetime, list[tuple[float, float, str, float]]] = {}
    for o in snap:
        p = parse_instrument(o.get("instrument_name", ""))
        iv, fwd = o.get("mark_iv"), o.get("underlying_price")
        if p is None or not iv or not fwd:
            continue
        exp, k, kind = p
        t = (exp - now).total_seconds() / (365 * 86400)
        if t <= 2 / 365:
            continue
        per.setdefault(exp, []).append((k, float(iv) / 100, kind, float(fwd)))
    pts = []
    for exp, opts in sorted(per.items()):
        t = (exp - now).total_seconds() / (365 * 86400)
        calls = [(abs(bs_delta(f, k, iv, t, "C") - 0.25), iv) for k, iv, c, f in opts if c == "C"]
        puts = [(abs(bs_delta(f, k, iv, t, "P") + 0.25), iv) for k, iv, c, f in opts if c == "P"]
        atm = [(abs(math.log(k / f)), iv) for k, iv, c, f in opts]
        calls = [x for x in calls if math.isfinite(x[0])]
        puts = [x for x in puts if math.isfinite(x[0])]
        if not calls or not puts or not atm:
            continue
        c25, p25, a = min(calls)[1], min(puts)[1], min(atm)[1]
        pts.append((t * 365, c25, p25, a))
    if not pts:
        return None
    days = np.array([p[0] for p in pts])
    j = int(np.searchsorted(days, target_days))
    if j == 0 or j == len(pts):
        c, p, a = pts[0 if j == 0 else -1][1:]
        used = days[0 if j == 0 else -1]
    else:
        (d0, c0, p0, a0), (d1, c1, p1, a1) = pts[j - 1], pts[j]
        w = (target_days - d0) / (d1 - d0)
        c, p, a = c0 + w * (c1 - c0), p0 + w * (p1 - p0), a0 + w * (a1 - a0)
        used = target_days
    return {"ts_us": int(now.timestamp() * 1e6), "currency": currency, "days": float(used),
            "rr25": float(c - p), "atm_iv": float(a), "call25_iv": float(c), "put25_iv": float(p),
            "n_options": len(snap)}


def options_snapshot(fetch: Fetch, currency: str) -> list[dict]:
    q = urllib.parse.urlencode({"currency": currency, "kind": "option"})
    return (fetch(f"{DERIBIT}/get_book_summary_by_currency?{q}") or {}).get("result") or []


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

def run(only: set[str], dry: bool, fetch_for: Callable[[str], Fetch] | None = None) -> dict:
    fetch_for = fetch_for or (lambda src: paced({"coinbase": 0.35, "upbit": 0.25}.get(src, 0.2)))
    end = today() - timedelta(days=1)
    counts: dict[str, object] = {}
    errors: dict[str, str] = {}

    def step(src: str, fn: Callable[[], None]) -> None:
        if src not in only:
            return
        try:
            fn()
        except Exception as e:  # one source failing does not stop the others
            errors[src] = f"{type(e).__name__}: {e}"
            print(f"  {src}: FAILED {errors[src]}", flush=True)

    def save(name: str, new: pl.DataFrame, keys: list[str]) -> None:
        old = read(name)
        out = merge(old, new, keys)
        counts[name] = {"fetched": new.height, "stored": out.height}
        print(f"  {name}: fetched {new.height}, stored {out.height}", flush=True)
        if not dry:
            write(name, out)

    step("coinbase", lambda: save("coinbase_btcusd_1h", coinbase(
        fetch_for("coinbase"), resume_from(read("coinbase_btcusd_1h"), "ts_us"), end), ["ts_us"]))
    step("upbit", lambda: save("upbit_krwbtc_1d", upbit(
        fetch_for("upbit"), resume_from(read("upbit_krwbtc_1d"), "day_us")), ["day_us"]))
    step("fx", lambda: save("fx_usdkrw", fx(
        fetch_for("fx"), resume_from(read("fx_usdkrw"), "day_us", START) - timedelta(days=7), end), ["day_us"]))
    step("stables", lambda: save("stables", stables(fetch_for("stables")), ["day_us"]))

    def do_dvol() -> None:
        old = read("dvol")
        frames = []
        for cur in ("BTC", "ETH"):
            prev = old.filter(pl.col("currency") == cur) if old is not None else None
            frames.append(dvol(fetch_for("dvol"), resume_from(prev, "day_us", date(2021, 3, 1)), cur))
        save("dvol", pl.concat(frames), ["currency", "day_us"])

    step("dvol", do_dvol)

    def do_skew() -> None:
        now = datetime.now(UTC)
        rows = []
        for cur in ("BTC", "ETH"):
            snap = options_snapshot(fetch_for("skew"), cur)
            r = skew_row(snap, now, cur)
            if r:
                rows.append(r)
            if snap and not dry:
                d = FLOW / "deribit_options" / f"date={now.date().isoformat()}"
                d.mkdir(parents=True, exist_ok=True)
                keep = ("instrument_name", "mark_iv", "underlying_price", "open_interest", "volume", "bid_price",
                        "ask_price", "mark_price", "creation_timestamp")
                pl.DataFrame([{k: o.get(k) for k in keep} for o in snap],
                             infer_schema_length=None).write_parquet(d / f"{cur}.parquet")
        if rows:
            save("skew", pl.DataFrame(rows), ["currency", "ts_us"])

    step("skew", do_skew)
    return {"counts": counts, "errors": errors}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--only", default=",".join(SOURCES), help="comma-separated: " + ", ".join(SOURCES))
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    only = {s.strip() for s in a.only.split(",") if s.strip()}
    bad = only - set(SOURCES)
    if bad:
        ap.error(f"unknown source(s): {', '.join(sorted(bad))}")
    print(f"flow collector -> {FLOW}", flush=True)
    res = run(only, a.dry_run)
    if not a.dry_run:
        FLOW.mkdir(parents=True, exist_ok=True)
        (FLOW / "last_run.json").write_text(json.dumps({"at": datetime.now(UTC).isoformat(), **res}, indent=1),
                                            encoding="utf-8")
    # Every source failing is a failed job; one failing is logged and retried tomorrow (overlap).
    return 1 if res["errors"] and len(res["errors"]) == len(only) else 0


if __name__ == "__main__":
    sys.exit(main())
