"""Shared by the five studies registered together on 2026-10-21 (vix_carry, etf_routing,
crypto_open_gap, treasury_premium, btc_vrp): the pool they count into, deflation on a
series' own calendar, the bootstrap, Yahoo daily and hourly bars, Binance 1-minute BTC
and ETH prices at given instants, and New York session times.

The pool (results/vix_carry_prereg.md): 1,740 trials (1,140 hand trials at the variance
backed out of the published bar, 377 at 2.43, and the factory's 600 at their own) plus
this batch's 22 at their own variance, all in annual units: 1,762.
"""

from __future__ import annotations

import json
import math
import os
import time
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import polars as pl
from scipy import stats

from ..data import ROOT
from ..metrics import deflated_sharpe
from . import director_common as dc
from . import fam_common as fc

HAND_TRIALS = 1140
BATCH_TRIALS = 22            # vix_carry 8, etf_routing 4, crypto_open_gap 2, treasury_premium 2, btc_vrp 6
SEED = 20261021
BOOT_DRAWS, BOOT_BLOCK = 4000, 20
CACHE = Path(os.environ.get("PYTHIA_S3_DATA", ROOT / "agent-s3"))
YAHOO_D = ("https://query1.finance.yahoo.com/v8/finance/chart/{}?period1={}&period2={}"
           "&interval=1d&events=div%2Csplit")
YAHOO_H = "https://query1.finance.yahoo.com/v8/finance/chart/{}?range=730d&interval=60m"
DAY_US = 86_400_000_000
MIN_US = 60_000_000


class DataUnavailable(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Pool and deflation
# ---------------------------------------------------------------------------

def pool(batch_annual: list[float]) -> dict:
    """Pooled annual variance of trial Sharpes and the trial count (1,762).
    batch_annual: the annual Sharpes of this batch's trials known to the caller; they
    stand for all 22."""
    v1 = dc.prior_var() * 365
    fx = np.clip(dc.factory_sharpes(), -fc.SR_CLIP, fc.SR_CLIP)
    n2, v2 = len(fx), float(np.var(fx)) if len(fx) > 1 else 0.0
    x = np.clip(np.array(batch_annual, dtype=float), -fc.SR_CLIP, fc.SR_CLIP)
    v3 = float(np.var(x)) if len(x) > 1 else v1
    n1, n3 = HAND_TRIALS, BATCH_TRIALS
    n = n1 + n2 + n3
    v = (n1 * v1 + n2 * v2 + n3 * v3) / n
    return {"hand_trials": n1, "factory_trials": n2, "batch_trials": n3, "n_total": n, "var_annual": v,
            "sr0_annual": fc._sr0(v, n)}


def deflated(x: np.ndarray, pl_: dict, year: int) -> float:
    """Deflated Sharpe probability of a daily series on a calendar of `year` periods."""
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    sd = x.std()
    if sd == 0 or len(x) < 3:
        return 0.0
    s = x.mean() / sd
    sk, ku = float(stats.skew(x)), float(stats.kurtosis(x, fisher=False))
    if 1 - sk * s + (ku - 1) / 4 * s ** 2 <= 0:
        return 0.0
    return deflated_sharpe(s, len(x), pl_["n_total"], pl_["var_annual"] / year, sk, ku)


# ---------------------------------------------------------------------------
# Measuring
# ---------------------------------------------------------------------------

def sharpe(x: np.ndarray, year: int) -> float:
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    sd = x.std() if len(x) > 1 else 0.0
    return float(x.mean() / sd * math.sqrt(year)) if sd > 0 else 0.0


def max_dd(x: np.ndarray) -> float:
    eq = np.cumprod(1 + np.nan_to_num(np.asarray(x, dtype=float)))
    peak = np.maximum.accumulate(np.r_[1.0, eq])[1:]
    return float((1 - eq / peak).max()) if len(eq) else 0.0


def perf(x: np.ndarray, year: int) -> dict:
    x = np.nan_to_num(np.asarray(x, dtype=float))
    n = len(x)
    eq = float(np.prod(1 + x)) if n else 1.0
    cagr = eq ** (year / n) - 1 if n and eq > 0 else -1.0
    return {"sharpe": sharpe(x, year), "cagr": cagr, "vol": float(x.std() * math.sqrt(year)) if n > 1 else 0.0,
            "max_dd": max_dd(x), "days": n}


def boot_index(n: int, seed: int = SEED) -> np.ndarray:
    rng = np.random.default_rng(seed)
    idx = np.empty((BOOT_DRAWS, n), dtype=np.int64)
    idx[:, 0] = rng.integers(0, n, BOOT_DRAWS)
    jump = rng.random((BOOT_DRAWS, n)) < 1 / BOOT_BLOCK
    fresh = rng.integers(0, n, (BOOT_DRAWS, n))
    for i in range(1, n):
        idx[:, i] = np.where(jump[:, i], fresh[:, i], (idx[:, i - 1] + 1) % n)
    return idx


def boot_band(x: np.ndarray, year: int, y: np.ndarray | None = None, seed: int = SEED) -> tuple[float, float, float]:
    """Stationary bootstrap of Sharpe(x), or Sharpe(x) - Sharpe(y) on the same resampled days:
    (5 %, 95 %, share of draws above 0)."""
    x = np.nan_to_num(np.asarray(x, dtype=float))
    idx = boot_index(len(x), seed)

    def sr(a: np.ndarray) -> np.ndarray:
        s = a[idx]
        sd = s.std(1)
        return np.where(sd > 0, s.mean(1) / np.where(sd > 0, sd, 1) * math.sqrt(year), 0.0)

    v = sr(x) if y is None else sr(x) - sr(np.nan_to_num(np.asarray(y, dtype=float)))
    return float(np.percentile(v, 5)), float(np.percentile(v, 95)), float((v > 0).mean())


def boot_mean(x: np.ndarray, seed: int = SEED) -> tuple[float, float, float]:
    """Stationary bootstrap of the mean of x: (5 %, 95 %, share above 0)."""
    x = np.nan_to_num(np.asarray(x, dtype=float))
    idx = boot_index(len(x), seed)
    m = x[idx].mean(1)
    return float(np.percentile(m, 5)), float(np.percentile(m, 95)), float((m > 0).mean())


def by_year(x: np.ndarray, years: np.ndarray, year: int, which=None) -> dict[int, float]:
    out = {}
    for y in (which or sorted(set(int(v) for v in years))):
        m = years == y
        if m.sum() > 5:
            out[int(y)] = sharpe(x[m], year)
    return out


# ---------------------------------------------------------------------------
# New York time (US rules since 2007: second Sunday of March to first Sunday of November)
# ---------------------------------------------------------------------------

def _nth_sunday(y: int, m: int, n: int) -> date:
    d = date(y, m, 1)
    d += timedelta(days=(6 - d.weekday()) % 7)
    return d + timedelta(days=7 * (n - 1))


def ny_offset_h(d: date) -> int:
    """Hours to add to New York local time to get UTC on that date (4 in summer, 5 in winter)."""
    if d.year >= 2007:
        on, off = _nth_sunday(d.year, 3, 2), _nth_sunday(d.year, 11, 1)
    else:                    # first Sunday of April to the last Sunday of October
        on, off = _nth_sunday(d.year, 4, 1), _nth_sunday(d.year, 10, 5)
        if off.month != 10:
            off = _nth_sunday(d.year, 10, 4)
    return 4 if on <= d < off else 5


def ny_us(d: np.datetime64 | date, hh: int, mm: int) -> int:
    """Epoch microseconds of hh:mm New York time on session date d."""
    dd = d if isinstance(d, date) else date.fromisoformat(str(np.datetime64(d, "D")))
    t = datetime(dd.year, dd.month, dd.day, hh, mm, tzinfo=timezone.utc) + timedelta(hours=ny_offset_h(dd))
    return int(t.timestamp() * 1e6)


# ---------------------------------------------------------------------------
# Binance 1-minute prices
# ---------------------------------------------------------------------------

_MIN: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}


def minute_bars(symbol: str, start: str = "2020-01") -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(open_time_us, open, close) of every Binance 1-minute kline of `symbol` from `start`."""
    if symbol in _MIN:
        return _MIN[symbol]
    d = ROOT / "hist" / "binance_spot" / "klines_1m" / f"symbol={symbol}"
    files = sorted(f for f in d.glob("*.parquet") if f.stem[:7] >= start)
    if not files:
        raise DataUnavailable(f"no 1-minute klines for {symbol} under {d}")
    df = (pl.concat([pl.read_parquet(f, columns=["open_time_us", "open", "close"]) for f in files])
          .unique("open_time_us").sort("open_time_us"))
    out = (df["open_time_us"].to_numpy(), df["open"].to_numpy(), df["close"].to_numpy())
    _MIN[symbol] = out
    return out


def price_at(symbol: str, t_us: np.ndarray, start: str = "2020-01") -> np.ndarray:
    """The price at each instant: the open of the minute starting there, else the close of the
    last minute before it (at most 10 minutes back), else NaN."""
    ot, op, cl = minute_bars(symbol, start)
    t_us = np.asarray(t_us, dtype=np.int64)
    i = np.searchsorted(ot, t_us)
    out = np.full(len(t_us), np.nan)
    exact = (i < len(ot)) & (ot[np.minimum(i, len(ot) - 1)] == t_us)
    out[exact] = op[i[exact]]
    j = i - 1
    back = ~exact & (j >= 0)
    ok = back & (t_us - ot[np.maximum(j, 0)] <= 10 * MIN_US)
    out[ok] = cl[j[ok]]
    return out


# ---------------------------------------------------------------------------
# Yahoo
# ---------------------------------------------------------------------------

def _get_json(url: str, timeout: float = 30.0) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except (OSError, ValueError) as e:
        raise DataUnavailable(f"{url.split('?')[0]}: {e}") from e


def yahoo_daily(sym: str, refresh: bool = False, start: int = 946684800) -> pl.DataFrame:
    """date, open, high, low, close (split adjusted), adj (dividends too), split (ratio taking
    effect that day), raw_close (splits undone). Cached as CSV under <s3>/yahoo/."""
    f = CACHE / "yahoo" / f"{sym.replace('^', '_')}.csv"
    if f.exists() and not refresh:
        return pl.read_csv(f, try_parse_dates=True)
    url = YAHOO_D.format(sym.replace("^", "%5E"), start, int(time.time()))
    p = _get_json(url)
    try:
        r = p["chart"]["result"][0]
        ts = r["timestamp"]
        q = r["indicators"]["quote"][0]
        adj = (r["indicators"].get("adjclose") or [{"adjclose": q["close"]}])[0]["adjclose"]
    except (KeyError, IndexError, TypeError) as e:
        raise DataUnavailable(f"{sym}: not a Yahoo chart answer ({e})") from e
    splits = {}
    for s in ((r.get("events") or {}).get("splits") or {}).values():
        d = datetime.fromtimestamp(s["date"], timezone.utc).date()
        if s.get("denominator"):
            splits[d] = float(s["numerator"]) / float(s["denominator"])
    rows = []
    for t, o, h, lo, c, a in zip(ts, q["open"], q["high"], q["low"], q["close"], adj):
        if c is None or c <= 0 or a is None:
            continue
        # Yahoo stamps a session at its open in New York; the date is the New York date.
        d = (datetime.fromtimestamp(t, timezone.utc) - timedelta(hours=5)).date()
        rows.append((d, o if o and o > 0 else None, h, lo, c, a, splits.get(d, 1.0)))
    if not rows:
        raise DataUnavailable(f"{sym}: no valid day")
    df = (pl.DataFrame(rows, schema=["date", "open", "high", "low", "close", "adj", "split"], orient="row")
          .unique("date", keep="last").sort("date"))
    sp = df["split"].to_numpy()
    later = np.cumprod(sp[::-1])[::-1]
    after = np.r_[later[1:], 1.0]
    df = df.with_columns(raw_close=pl.Series(df["close"].to_numpy() * after))
    f.parent.mkdir(parents=True, exist_ok=True)
    df.write_csv(f)
    time.sleep(0.4)
    return df


def yahoo_hourly(sym: str, refresh: bool = False) -> pl.DataFrame:
    """Yahoo's 60-minute bars (the last 730 days): ts_us (bar start, UTC), open, close.
    Cached once per day of fetching under <s3>/yahoo_1h/."""
    f = CACHE / "yahoo_1h" / f"{sym}.csv"
    if f.exists() and not refresh:
        return pl.read_csv(f)
    p = _get_json(YAHOO_H.format(sym))
    try:
        r = p["chart"]["result"][0]
        ts = r["timestamp"]
        q = r["indicators"]["quote"][0]
    except (KeyError, IndexError, TypeError) as e:
        raise DataUnavailable(f"{sym}: not a Yahoo chart answer ({e})") from e
    rows = [(int(t) * 1_000_000, o, c) for t, o, c in zip(ts, q["open"], q["close"]) if o and c]
    df = pl.DataFrame(rows, schema=["ts_us", "open", "close"], orient="row").unique("ts_us").sort("ts_us")
    f.parent.mkdir(parents=True, exist_ok=True)
    df.write_csv(f)
    return df


def to_np_dates(s: pl.Series) -> np.ndarray:
    return s.to_numpy().astype("datetime64[D]")
