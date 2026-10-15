"""W4: intraday strategies on US ETFs and large caps, flat at the close.

    python -m lab.experiments.intraday_equities                   (Alpaca when keys are set, else the proxy)
    python -m lab.experiments.intraday_equities --source proxy    (keyless: Oanda index CFD minutes, 2005 to 2020-05)
    python -m lab.experiments.intraday_equities --source alpaca   (needs APCA_API_KEY_ID and APCA_API_SECRET_KEY)
    options: --refresh (download again), --feed sip|iex, --event-days FILE.csv (extra no-trade dates, one per line)

Pre-registered in results/intraday_equities.md (the part above the first
generated marker was written before any number was seen). Each run replaces
only its own section of that file (proxy or alpaca) and writes JSON and
markdown to <reports>/intraday_equities/<source>-latest.*.

Data
  alpaca  Historical 5-minute bars from data.alpaca.markets (feed SIP, IEX when
          the account may not query SIP), adjustment=all, regular session only.
          Keys come from the environment and nothing else; they are never
          written anywhere. Cached per symbol and month as parquet under
          $PYTHIA_INTRADAY_DATA (default <PYTHIA_DATA>/intraday/alpaca-<feed>);
          the running month is always fetched again. A split after a month was
          cached leaves that month on the old scale: run with --refresh then.
  proxy   Oanda minute bars of the SPX500, NAS100 and US2000 CFDs from the
          public archive github.com/FutureSharks/financial-data (no key), as
          stand-ins for SPY, QQQ and IWM, cut to the regular session and
          resampled to 5 minutes, cached per instrument and month under
          $PYTHIA_INTRADAY_DATA (default <PYTHIA_DATA>/intraday/proxy).

Mechanics, as pre-registered: decisions on 5-minute bar closes fill at the
next bar's open; every position is closed at the open of the 15:55 bar; no new
entry after the 15:30 decision. Costs per side 2 bps SPY and QQQ, 3 bps IWM,
5 bps a large cap (doubled as the stress case), plus the SEC fee and FINRA TAF
on every sell (fees are not doubled). Each symbol is 1/N of the book.
"""

from __future__ import annotations

import io
import json
import math
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import polars as pl
from scipy import stats

from ..data import ROOT
from ..metrics import deflated_sharpe
from . import etf_trend as et

NAME = "intraday_equities"
RESULTS_DIR = Path(os.environ.get("PYTHIA_FAM_RESULTS", str(Path(__file__).resolve().parents[2] / "results")))
REPORTS = Path(os.environ.get("PYTHIA_REPORTS", ROOT / "reports"))
CACHE_ROOT = Path(os.environ.get("PYTHIA_INTRADAY_DATA", ROOT / "intraday"))

NB = 78                  # 5-minute bars 09:30 .. 15:55
EXIT_BAR = 77            # flat at the open of the 15:55 bar
LAST_ENTRY = 71          # the 15:30 decision (close of the 15:25 bar)
BAR_1000 = 5             # close of bar 5 is 10:00
BAR_1500 = 65            # close of bar 65 is 15:00
YEAR_DAYS = 252
LOOKBACK = 20

ETFS = ("SPY", "QQQ", "IWM")
CANDIDATES = ("AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "AMD", "NFLX", "JPM", "BAC", "XOM",
              "UNH", "LLY", "V", "MA", "COST", "WMT", "ORCL", "CRM", "ADBE", "INTC", "CSCO", "QCOM", "PEP", "KO", "PG",
              "JNJ", "HD", "MRK", "ABBV", "CVX", "WFC", "C", "DIS", "PYPL", "BA", "PLTR", "MU")
TOP_STOCKS = 20
COST_BPS = {"SPY": 2.0, "QQQ": 2.0, "IWM": 3.0}
STOCK_COST_BPS = 5.0
SEC_FEE = 27.80e-6       # USD per USD sold (SEC Section 31, the 2024-25 rate; conservative)
TAF_PER_SHARE = 0.000166  # FINRA TAF per share sold; the per-trade cap is ignored (conservative)

PROXY_URL = ("https://raw.githubusercontent.com/FutureSharks/financial-data/master/pyfinancialdata/data/"
             "currencies/oanda/{inst}/{y}/oanda-{inst}-{y}-{m}.csv")
PROXY = {"SPY": "SPX500_USD", "QQQ": "NAS100_USD", "IWM": "US2000_USD"}
PROXY_SCALE = {"SPY": 10.0, "QQQ": 40.0, "IWM": 10.0}   # index points per ETF dollar, only for the per-share TAF
PROXY_FIRST, PROXY_LAST = (2005, 1), (2020, 5)
PROXY_MIN_MINUTES = 300
PROXY_MIN_VOL_SHARE = 0.30

ALPACA_BARS = "https://data.alpaca.markets/v2/stocks/bars"
ALPACA_FROM = (2016, 1)

WINDOWS = {   # in sample from, out of sample from (pre-registered)
    "proxy": (np.datetime64("2005-01-01"), np.datetime64("2014-01-01")),
    "alpaca": (np.datetime64("2016-01-01"), np.datetime64("2021-01-01")),
}
RECENT = np.datetime64("2024-01-01")    # a reported sub-window of the out of sample, not a gate

# Deflation pools: (trials, published annual bar). The pre-registration named the
# 377 hand-study trials (README, bar 2.43); the global ledger now holds 677
# (results/factory_first_run.md, bar 2.45). Both are reported; gate 1 uses this study's 46.
PRIOR_POOLS = {"hand studies (pre-registered)": (377, 2.43), "global ledger now": (677, 2.45)}
SR_CLIP = 3.0
BOOT_DRAWS, BOOT_BLOCK = 5_000, 10
UA = {"User-Agent": "pythia-lab"}


class DataUnavailable(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Bars
# ---------------------------------------------------------------------------

@dataclass
class Bars:
    """5-minute regular-session bars on one calendar of market days.

    o, h, l, c, v are (S, D, NB), NaN on a day a symbol has no valid session;
    inside a valid day every bar is filled (a missing bar repeats the last close
    with zero volume). tp is the price used for VWAP (the bar's own VWAP when the
    source has it, else (h + l + c) / 3)."""
    dates: np.ndarray
    syms: list[str]
    o: np.ndarray
    h: np.ndarray
    l: np.ndarray
    c: np.ndarray
    v: np.ndarray
    tp: np.ndarray
    scale: np.ndarray          # (S,) price / scale = price of one share (for the TAF)
    source: str = "synthetic"
    notes: list[str] = field(default_factory=list)

    @property
    def S(self) -> int:
        return len(self.syms)

    @property
    def D(self) -> int:
        return len(self.dates)

    @property
    def valid(self) -> np.ndarray:
        return np.isfinite(self.o[:, :, 0])


def _fill_day(a: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    """Fill missing bars of one (D, NB) block: a gap repeats the last close,
    leading gaps take the first open. Rows with no bar at all stay NaN."""
    c = a["close"]
    have = np.isfinite(c)
    D = c.shape[0]
    idx = np.where(have, np.arange(NB)[None, :], -1)
    last = np.maximum.accumulate(idx, axis=1)
    rows = np.arange(D)[:, None]
    prev_c = np.where(last >= 0, c[rows, np.maximum(last, 0)], np.nan)
    first = np.argmax(have, axis=1)
    first_o = a["open"][np.arange(D), first]
    lead = last < 0
    fill = np.where(lead, first_o[:, None], prev_c)
    out = {}
    for k in ("open", "high", "low", "close", "tp"):
        out[k] = np.where(have, a[k], fill)
    out["volume"] = np.where(have, np.nan_to_num(a["volume"]), 0.0)
    none = ~have.any(axis=1)
    for k in out:
        out[k][none] = np.nan
    return out


def frame_to_blocks(df: pl.DataFrame) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    """A frame of (date, bar, open, high, low, close, volume[, tp]) as day x bar arrays."""
    if "tp" not in df.columns:
        df = df.with_columns(tp=(pl.col("high") + pl.col("low") + pl.col("close")) / 3)
    df = df.filter((pl.col("bar") >= 0) & (pl.col("bar") < NB))
    days = np.unique(df["date"].to_numpy().astype("datetime64[D]"))
    di = np.searchsorted(days, df["date"].to_numpy().astype("datetime64[D]"))
    bi = df["bar"].to_numpy().astype(np.int64)
    a = {}
    for k in ("open", "high", "low", "close", "volume", "tp"):
        x = np.full((len(days), NB), np.nan)
        x[di, bi] = df[k].to_numpy().astype(np.float64)
        a[k] = x
    return days, _fill_day(a)


def assemble(per_sym: dict[str, tuple[np.ndarray, dict]], valid: dict[str, np.ndarray], calendar: np.ndarray,
             scale: dict[str, float], source: str, notes: list[str] | None = None) -> Bars:
    """Put every symbol on one calendar; a symbol's day counts only where valid[sym] says so."""
    syms = list(per_sym)
    S, D = len(syms), len(calendar)
    arr = {k: np.full((S, D, NB), np.nan) for k in ("open", "high", "low", "close", "volume", "tp")}
    for j, s in enumerate(syms):
        days, a = per_sym[s]
        ok = valid[s] & np.isin(days, calendar)
        pos = np.searchsorted(calendar, days[ok])
        for k in arr:
            arr[k][j, pos] = a[k][ok]
    return Bars(dates=calendar, syms=syms, o=arr["open"], h=arr["high"], l=arr["low"], c=arr["close"],
                v=arr["volume"], tp=arr["tp"], scale=np.array([scale.get(s, 1.0) for s in syms]),
                source=source, notes=notes or [])


def _session(df: pl.DataFrame, ts: str) -> pl.DataFrame:
    """UTC timestamps (bar or minute start) to New York date and 5-minute bar index, regular session only."""
    ny = pl.col(ts).dt.convert_time_zone("America/New_York")
    mins = ny.dt.hour().cast(pl.Int32) * 60 + ny.dt.minute().cast(pl.Int32) - (9 * 60 + 30)
    return (df.with_columns(date=ny.dt.date(), m=mins)
            .filter((pl.col("m") >= 0) & (pl.col("m") < NB * 5))
            .with_columns(bar=(pl.col("m") // 5).cast(pl.Int64)))


# --- proxy -----------------------------------------------------------------

def months(first: tuple[int, int], last: tuple[int, int]) -> list[tuple[int, int]]:
    out, (y, m) = [], first
    while (y, m) <= last:
        out.append((y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def proxy_month(csv_text: str) -> pl.DataFrame:
    """One Oanda month (time UTC, close, high, low, open, volume) as 5-minute session bars
    with the number of minutes behind each bar."""
    df = pl.read_csv(io.StringIO(csv_text), schema_overrides={"time": pl.Utf8})
    if df.is_empty():
        return pl.DataFrame(schema={"date": pl.Date, "bar": pl.Int64, "open": pl.Float64, "high": pl.Float64,
                                    "low": pl.Float64, "close": pl.Float64, "volume": pl.Float64, "minutes": pl.Int64})
    df = df.with_columns(t=pl.col("time").str.to_datetime("%Y-%m-%d %H:%M:%S", time_zone="UTC"))
    df = _session(df, "t").sort("t")
    return (df.group_by("date", "bar", maintain_order=True)
            .agg(open=pl.col("open").first(), high=pl.col("high").max(), low=pl.col("low").min(),
                 close=pl.col("close").last(), volume=pl.col("volume").sum().cast(pl.Float64),
                 minutes=pl.len().cast(pl.Int64))
            .sort("date", "bar"))


def _fetch(url: str, headers: dict | None = None, timeout: float = 60) -> bytes:
    req = urllib.request.Request(url, headers={**UA, **(headers or {})})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and attempt < 4:
                time.sleep(2 ** (attempt + 1))
                continue
            raise
        except (urllib.error.URLError, OSError):
            if attempt == 4:
                raise
            time.sleep(2 ** (attempt + 1))
    raise RuntimeError("unreachable")


def load_proxy(refresh: bool = False, workers: int = 6, fetch=None) -> Bars:
    cache = CACHE_ROOT / "proxy"
    fetch = fetch or (lambda url: _fetch(url).decode("utf-8", "replace"))
    jobs = [(s, y, m) for s in PROXY for (y, m) in months(PROXY_FIRST, PROXY_LAST)]

    def one(job):
        s, y, m = job
        f = cache / PROXY[s] / f"{y}-{m:02d}.parquet"
        if f.exists() and not refresh:
            return
        try:
            df = proxy_month(fetch(PROXY_URL.format(inst=PROXY[s], y=y, m=m)))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return
            raise
        f.parent.mkdir(parents=True, exist_ok=True)
        df.write_parquet(f)

    try:
        with ThreadPoolExecutor(workers) as ex:
            list(ex.map(one, jobs))
    except (OSError, urllib.error.URLError) as e:
        raise DataUnavailable(f"proxy download failed: {e}") from e
    per, valid, notes = {}, {}, []
    for s, inst in PROXY.items():
        files = sorted((cache / inst).glob("*.parquet"))
        if not files:
            raise DataUnavailable(f"no proxy bars for {inst}")
        df = pl.concat([pl.read_parquet(f) for f in files]).unique(["date", "bar"], keep="last").sort("date", "bar")
        daily = df.group_by("date").agg(minutes=pl.col("minutes").sum(), vol=pl.col("volume").sum()).sort("date")
        days, a = frame_to_blocks(df.drop("minutes"))
        mins = daily["minutes"].to_numpy()
        vol = daily["vol"].to_numpy().astype(np.float64)
        valid[s] = proxy_valid(mins, vol)
        per[s] = (days, a)
        notes.append(f"{s} as {inst}: {valid[s].sum()} valid days of {len(days)} with session quotes")
    calendar = per["SPY"][0][valid["SPY"]]
    return assemble(per, valid, calendar, PROXY_SCALE, "proxy", notes)


def proxy_valid(minutes: np.ndarray, vol: np.ndarray) -> np.ndarray:
    """At least 300 session minutes and tick volume at least 30 % of the median of the
    previous 20 days that had the minutes (holiday quotes and half days drop out)."""
    full = minutes >= PROXY_MIN_MINUTES
    ok = np.zeros(len(minutes), dtype=bool)
    hist: list[float] = []
    for t in range(len(minutes)):
        if full[t]:
            med = np.median(hist[-LOOKBACK:]) if len(hist) >= LOOKBACK else None
            ok[t] = med is None or vol[t] >= PROXY_MIN_VOL_SHARE * med
            hist.append(vol[t])
    return ok


# --- Alpaca ------------------------------------------------------------------

def alpaca_keys() -> dict | None:
    k = (os.environ.get("APCA_API_KEY_ID") or "").strip()
    s = (os.environ.get("APCA_API_SECRET_KEY") or os.environ.get("APCA_API_SECRET") or "").strip()
    return {"APCA-API-KEY-ID": k, "APCA-API-SECRET-KEY": s} if k and s else None


def alpaca_month_json(sym: str, y: int, m: int, feed: str, headers: dict, get=None) -> list[dict]:
    """Every 5-minute bar of one symbol and month (all pages)."""
    get = get or (lambda url: json.loads(_fetch(url, headers)))
    start = datetime(y, m, 1, tzinfo=timezone.utc)
    end = datetime(y + (m == 12), m % 12 + 1, 1, tzinfo=timezone.utc)
    end = min(end, datetime.now(timezone.utc) - timedelta(minutes=20))   # SIP: nothing from the last 15 minutes
    out, token = [], None
    while True:
        q = {"symbols": sym, "timeframe": "5Min", "start": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
             "end": end.strftime("%Y-%m-%dT%H:%M:%SZ"), "adjustment": "all", "feed": feed, "limit": 10000,
             "sort": "asc"}
        if token:
            q["page_token"] = token
        js = get(f"{ALPACA_BARS}?{urllib.parse.urlencode(q)}")
        out += (js.get("bars") or {}).get(sym) or []
        token = js.get("next_page_token")
        if not token:
            return out


def alpaca_frame(rows: list[dict]) -> pl.DataFrame:
    schema = {"date": pl.Date, "bar": pl.Int64, "open": pl.Float64, "high": pl.Float64, "low": pl.Float64,
              "close": pl.Float64, "volume": pl.Float64, "tp": pl.Float64}
    if not rows:
        return pl.DataFrame(schema=schema)
    df = pl.DataFrame({"t": [r["t"] for r in rows], "open": [float(r["o"]) for r in rows],
                       "high": [float(r["h"]) for r in rows], "low": [float(r["l"]) for r in rows],
                       "close": [float(r["c"]) for r in rows], "volume": [float(r["v"]) for r in rows],
                       "tp": [float(r.get("vw") or (r["h"] + r["l"] + r["c"]) / 3) for r in rows]})
    df = df.with_columns(t=pl.col("t").str.to_datetime(time_zone="UTC"))
    return _session(df, "t").select(list(schema)).sort("date", "bar")


def load_alpaca(refresh: bool = False, feed: str = "sip", get=None, today: datetime | None = None) -> Bars:
    headers = alpaca_keys()
    if headers is None and get is None:
        raise DataUnavailable("APCA_API_KEY_ID / APCA_API_SECRET_KEY are not set")
    today = today or datetime.now(timezone.utc)
    cache = CACHE_ROOT / f"alpaca-{feed}"
    now_m = (today.year, today.month)
    notes = [f"feed {feed}, adjustment all, 5Min"]
    per, frames = {}, {}
    for s in ETFS + CANDIDATES:
        parts = []
        for (y, m) in months(ALPACA_FROM, now_m):
            f = cache / s / f"{y}-{m:02d}.parquet"
            if f.exists() and not refresh and (y, m) != now_m:
                parts.append(pl.read_parquet(f))
                continue
            try:
                df = alpaca_frame(alpaca_month_json(s, y, m, feed, headers or {}, get))
            except urllib.error.HTTPError as e:
                body = e.read().decode("utf-8", "replace")[:200] if hasattr(e, "read") else ""
                raise DataUnavailable(f"Alpaca {s} {y}-{m:02d}: HTTP {e.code} {body}") from e
            except (urllib.error.URLError, OSError) as e:
                raise DataUnavailable(f"Alpaca {s} {y}-{m:02d}: {e}") from e
            f.parent.mkdir(parents=True, exist_ok=True)
            df.write_parquet(f)
            parts.append(df)
            if get is None:
                time.sleep(0.32)            # 200 requests a minute on the free plan
        df = pl.concat(parts) if parts else pl.DataFrame()
        if df.is_empty():
            notes.append(f"{s}: no bars")
            continue
        frames[s] = df
        per[s] = frame_to_blocks(df)
    if "SPY" not in per:
        raise DataUnavailable("no SPY bars")
    # Market calendar: SPY's full sessions (a half day closes at 13:00 and is left out).
    d_spy, a_spy = per["SPY"]
    spy_bars = frames["SPY"].group_by("date").agg(n=pl.len(), last=pl.col("bar").max()).sort("date")
    full = (spy_bars["n"].to_numpy() >= 70) & (spy_bars["last"].to_numpy() >= EXIT_BAR)
    calendar = spy_bars["date"].to_numpy().astype("datetime64[D]")[full]
    valid = {}
    for s, df in frames.items():
        n = df.group_by("date").agg(n=pl.len()).sort("date")["n"].to_numpy()
        valid[s] = n >= NB // 2
    halfs = int((~full).sum())
    notes.append(f"{len(calendar)} full sessions; {halfs} SPY days left out as half days or incomplete")
    return assemble(per, valid, calendar, {}, "alpaca", notes)


# ---------------------------------------------------------------------------
# Daily features, all known at the bar where they are used
# ---------------------------------------------------------------------------

@dataclass
class Features:
    prev_close: np.ndarray     # (S, D) last regular close of the symbol's previous valid day
    std20: np.ndarray          # std of the previous 20 close-to-close returns
    gapz: np.ndarray           # (open / prev close - 1) / std20
    sigma5: np.ndarray         # std of 5-minute returns over the previous 20 days, x sqrt(12)
    range0: np.ndarray         # first bar's (high - low) / open
    range_med: np.ndarray      # median of range0 over the previous 20 days
    dollar_vol: np.ndarray     # session dollar volume


def _per_symbol(x: np.ndarray, valid: np.ndarray, fn) -> np.ndarray:
    """Apply fn to each symbol's series of valid days and scatter back to (S, D)."""
    out = np.full(x.shape, np.nan)
    for j in range(x.shape[0]):
        idx = np.flatnonzero(valid[j])
        if idx.size:
            out[j, idx] = fn(x[j, idx])
    return out


def _trailing(fn, n: int = LOOKBACK, min_n: int = LOOKBACK):
    """Statistic of the previous n values (the current one excluded)."""
    def go(s: np.ndarray) -> np.ndarray:
        out = np.full(s.size, np.nan)
        for t in range(min_n, s.size):
            w = s[max(0, t - n):t]
            w = w[np.isfinite(w)]
            if w.size >= min_n:
                out[t] = fn(w)
        return out
    return go


def features(B: Bars) -> Features:
    val = B.valid
    close = B.c[:, :, NB - 1]
    prev_close = _per_symbol(close, val, lambda s: np.r_[np.nan, s[:-1]])
    rcc = close / prev_close - 1
    std20 = _per_symbol(rcc, val, _trailing(lambda w: np.std(w, ddof=1), min_n=LOOKBACK - 1))
    with np.errstate(divide="ignore", invalid="ignore"):
        gapz = (B.o[:, :, 0] / prev_close - 1) / std20
        r5 = np.log(B.c[:, :, 1:] / B.c[:, :, :-1])
    n5 = np.isfinite(r5).sum(2)
    s1, s2 = np.nansum(r5, 2), np.nansum(r5 ** 2, 2)

    def pooled(stack: np.ndarray) -> np.ndarray:
        a, b, n = stack[:, 0], stack[:, 1], stack[:, 2]
        out = np.full(a.size, np.nan)
        for t in range(LOOKBACK, a.size):
            N = n[t - LOOKBACK:t].sum()
            if N > 2:
                m = a[t - LOOKBACK:t].sum() / N
                out[t] = math.sqrt(max(b[t - LOOKBACK:t].sum() / N - m * m, 0.0) * N / (N - 1))
        return out

    sigma5 = np.full(close.shape, np.nan)
    for j in range(B.S):
        idx = np.flatnonzero(val[j])
        if idx.size:
            sigma5[j, idx] = pooled(np.stack([s1[j, idx], s2[j, idx], n5[j, idx]], 1)) * math.sqrt(12)
    with np.errstate(divide="ignore", invalid="ignore"):
        range0 = (B.h[:, :, 0] - B.l[:, :, 0]) / B.o[:, :, 0]
    range_med = _per_symbol(range0, val, _trailing(np.median))
    dollar_vol = np.where(val, np.nansum(B.c * B.v, 2), np.nan)
    return Features(prev_close, std20, gapz, sigma5, range0, range_med, dollar_vol)


def universe(B: Bars, F: Features) -> np.ndarray:
    """(S, D) bool: the ETFs every day, plus on the first market day of each month the 20
    candidates with the highest mean dollar volume over the previous 20 market days
    (at least 15 of them valid), held for the month."""
    U = np.zeros((B.S, B.D), dtype=bool)
    etf = np.array([s in ETFS for s in B.syms])
    U[etf] = True
    cand = np.flatnonzero(~etf)
    if cand.size == 0:
        return U
    month = B.dates.astype("datetime64[M]")
    starts = np.flatnonzero(np.r_[True, month[1:] != month[:-1]])
    bounds = list(starts) + [B.D]
    for i, t in enumerate(starts):
        if t < LOOKBACK:
            continue
        w = F.dollar_vol[cand, t - LOOKBACK:t]
        ok = np.isfinite(w).sum(1) >= 15
        mean = np.nansum(w, 1) / np.maximum(np.isfinite(w).sum(1), 1)
        score = np.where(ok, mean, -np.inf)
        order = np.argsort(-score, kind="stable")
        pick = cand[order[:TOP_STOCKS]][np.isfinite(score[order[:TOP_STOCKS]])]
        U[pick, t:bounds[i + 1]] = True
    return U


# ---------------------------------------------------------------------------
# Rules: each returns the target position decided at the close of bar k,
# (S, D, NB), filled at the open of bar k + 1.
# ---------------------------------------------------------------------------

def rule_orb(B: Bars, F: Features, minutes: int, longshort: bool, stop: bool) -> np.ndarray:
    """First close beyond the opening range decides the day (one entry). Long-only
    takes only the upside breaks; a first break down leaves it in cash."""
    nb = minutes // 5
    with np.errstate(invalid="ignore"):
        H = np.max(B.h[:, :, :nb], 2)
        L = np.min(B.l[:, :, :nb], 2)
    pos = np.zeros((B.S, B.D))
    done = np.zeros((B.S, B.D), dtype=bool)
    tgt = np.zeros((B.S, B.D, NB))
    for k in range(nb, EXIT_BAR):
        ck = B.c[:, :, k]
        if k <= LAST_ENTRY:
            up = ~done & (ck > H)
            dn = ~done & (ck < L)
            pos = np.where(up, 1.0, pos)
            if longshort:
                pos = np.where(dn, -1.0, pos)
            done |= up | dn
        if stop:
            pos = np.where((pos > 0) & (ck < L), 0.0, pos)
            pos = np.where((pos < 0) & (ck > H), 0.0, pos)
        tgt[:, :, k] = pos
    return tgt


def rule_gap(B: Bars, F: Features, g: float, mode: str, longshort: bool) -> np.ndarray:
    """Decided at the first bar's close, only while the gap is still open then."""
    z, pc, c0 = F.gapz, F.prev_close, B.c[:, :, 0]
    with np.errstate(invalid="ignore"):
        up, dn = (z > g) & (c0 > pc), (z < -g) & (c0 < pc)
    if mode == "fade":
        pos = np.where(dn, 1.0, 0.0) + (np.where(up, -1.0, 0.0) if longshort else 0.0)
    else:
        pos = np.where(up, 1.0, 0.0) + (np.where(dn, -1.0, 0.0) if longshort else 0.0)
    tgt = np.zeros((B.S, B.D, NB))
    tgt[:, :, 0] = pos
    pcx = np.nan_to_num(pc)
    for k in range(1, EXIT_BAR):
        ck = B.c[:, :, k]
        with np.errstate(invalid="ignore"):
            if mode == "fade":
                pos = np.where((pos > 0) & (ck >= pcx), 0.0, pos)
                pos = np.where((pos < 0) & (ck <= pcx), 0.0, pos)
            else:
                pos = np.where((pos > 0) & (ck < pcx), 0.0, pos)
                pos = np.where((pos < 0) & (ck > pcx), 0.0, pos)
        tgt[:, :, k] = pos
    return tgt


def session_vwap(B: Bars) -> np.ndarray:
    pv = np.cumsum(np.nan_to_num(B.tp * B.v), 2)
    vv = np.cumsum(np.nan_to_num(B.v), 2)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(vv > 0, pv / np.where(vv > 0, vv, 1), B.c)


def rule_vwap(B: Bars, F: Features, kz: float, longshort: bool) -> np.ndarray:
    vw = session_vwap(B)
    with np.errstate(invalid="ignore", divide="ignore"):
        z = np.log(B.c / vw) / F.sigma5[:, :, None]
    pos = np.zeros((B.S, B.D))
    tgt = np.zeros((B.S, B.D, NB))
    for k in range(BAR_1000, EXIT_BAR):
        ck, vk, zk = B.c[:, :, k], vw[:, :, k], z[:, :, k]
        with np.errstate(invalid="ignore"):
            pos = np.where((pos > 0) & (ck >= vk), 0.0, pos)
            pos = np.where((pos < 0) & (ck <= vk), 0.0, pos)
            if k <= LAST_ENTRY:
                pos = np.where((pos == 0) & (zk < -kz), 1.0, pos)
                if longshort:
                    pos = np.where((pos == 0) & (zk > kz), -1.0, pos)
        tgt[:, :, k] = pos
    return tgt


def rule_momentum(B: Bars, F: Features, signal: str, longshort: bool) -> np.ndarray:
    with np.errstate(invalid="ignore", divide="ignore"):
        s = B.c[:, :, BAR_1000] / F.prev_close - 1
        if signal == "first+12th":
            s = s + (B.c[:, :, LAST_ENTRY] / B.c[:, :, BAR_1500] - 1)
    s = np.nan_to_num(s)
    pos = np.where(s > 0, 1.0, 0.0) + (np.where(s < 0, -1.0, 0.0) if longshort else 0.0)
    tgt = np.zeros((B.S, B.D, NB))
    tgt[:, :, LAST_ENTRY:EXIT_BAR] = pos[:, :, None]
    return tgt


def grid() -> list[dict]:
    g = []
    for m in (5, 15, 30):
        for ls in (False, True):
            for stop in (False, True):
                g.append({"family": "ORB", "name": f"ORB {m}m {'L/S' if ls else 'long'}{' stop' if stop else ''}",
                          "rule": "orb", "minutes": m, "longshort": ls, "stop": stop})
    for gz in (0.5, 1.0, 1.5):
        for mode in ("fade", "go"):
            for ls in (False, True):
                g.append({"family": "Gap", "name": f"Gap {mode} {gz} {'L/S' if ls else 'long'}",
                          "rule": "gap", "g": gz, "mode": mode, "longshort": ls})
    for kz in (1.0, 1.5, 2.0):
        for ls in (False, True):
            g.append({"family": "VWAP", "name": f"VWAP k {kz} {'L/S' if ls else 'long'}",
                      "rule": "vwap", "k": kz, "longshort": ls})
    for sig in ("first", "first+12th"):
        for ls in (False, True):
            g.append({"family": "Momentum", "name": f"EOD momentum {sig} {'L/S' if ls else 'long'}",
                      "rule": "momentum", "signal": sig, "longshort": ls})
    return g


def targets(B: Bars, F: Features, v: dict) -> np.ndarray:
    r = v["rule"]
    if r == "orb":
        return rule_orb(B, F, v["minutes"], v["longshort"], v["stop"])
    if r == "gap":
        return rule_gap(B, F, v["g"], v["mode"], v["longshort"])
    if r == "vwap":
        return rule_vwap(B, F, v["k"], v["longshort"])
    if r == "momentum":
        return rule_momentum(B, F, v["signal"], v["longshort"])
    raise ValueError(r)


def macro_days(dates: np.ndarray, extra: set | None = None) -> np.ndarray:
    """(D,) True on the first Friday of each month (the jobs report, by rule) and any extra date."""
    d = dates.astype("datetime64[D]")
    dow = (d.astype(np.int64) + 3) % 7                          # Monday 0
    dom = (d - d.astype("datetime64[M]").astype("datetime64[D]")).astype(np.int64) + 1
    out = (dow == 4) & (dom <= 7)
    if extra:
        out |= np.isin(d, np.array(sorted(extra), dtype="datetime64[D]"))
    return out


def abnormal_open(F: Features) -> np.ndarray:
    """(S, D) True when abs(gap z) > 3 or the first bar's range is above 3x its 20-day median."""
    with np.errstate(invalid="ignore"):
        return (np.abs(F.gapz) > 3) | (F.range0 > 3 * F.range_med)


# ---------------------------------------------------------------------------
# Simulation
# ---------------------------------------------------------------------------

def cost_per_side(syms: list[str]) -> np.ndarray:
    return np.array([COST_BPS.get(s, STOCK_COST_BPS) for s in syms]) / 1e4


@dataclass
class Sim:
    gross: np.ndarray       # (S, D) return of each symbol's slot on each day, before costs
    turnover: np.ndarray    # (S, D) sum of abs position changes (entries, exits, flips)
    fees: np.ndarray        # (S, D) SEC fee and TAF on the sells, as a return
    entries: np.ndarray     # (S, D) number of entries (a flip counts once)
    expo: np.ndarray        # (S, D) mean abs position over the session's bars

    def net(self, cost: np.ndarray, mult: float = 1.0) -> np.ndarray:
        return self.gross - mult * cost[:, None] * self.turnover - self.fees


def held_from_targets(tgt: np.ndarray, lag: int = 0) -> np.ndarray:
    """Position during the interval open(k) to open(k + 1), k = 0..NB-1; zero from the 15:55 open."""
    held = np.zeros_like(tgt)
    sh = 1 + lag
    held[:, :, sh:EXIT_BAR] = tgt[:, :, :EXIT_BAR - sh]
    return np.nan_to_num(held)


def simulate(B: Bars, held: np.ndarray, allow: np.ndarray | None = None) -> Sim:
    """P&L of positions entered and exited at bar opens. A position's return is
    measured from its own entry price (shares bought once, not rebalanced)."""
    val = B.valid
    mask = val if allow is None else val & allow
    held = np.where(mask[:, :, None], held, 0.0)
    held[:, :, EXIT_BAR:] = 0.0
    O = np.where(val[:, :, None], B.o, 1.0)
    prev = np.concatenate([np.zeros(held.shape[:2] + (1,)), held[:, :, :-1]], 2)
    change = held != prev
    start = np.maximum.accumulate(np.where(change, np.arange(NB)[None, None, :], 0), 2)
    entry = np.take_along_axis(O, start, 2)
    pnl = held[:, :, :-1] * (O[:, :, 1:] - O[:, :, :-1]) / entry[:, :, :-1]
    d = np.abs(held - prev)
    sold = np.maximum(prev - held, 0.0)
    share_px = O / B.scale[:, None, None]
    fees = (sold * (SEC_FEE + TAF_PER_SHARE / share_px)).sum(2)
    entries = ((held != 0) & change).sum(2).astype(float)
    return Sim(gross=pnl.sum(2), turnover=d.sum(2), fees=fees, entries=entries,
               expo=np.abs(held[:, :, :EXIT_BAR]).mean(2))


def book(sim: Sim, U: np.ndarray, cost: np.ndarray, mult: float = 1.0) -> np.ndarray:
    """(D,) daily book return: 1/N per member symbol, a member without a session holds cash."""
    n = U.sum(0)
    x = np.where(U, sim.net(cost, mult), 0.0).sum(0)
    return np.where(n > 0, x / np.maximum(n, 1), 0.0)


def drift_held(B: Bars) -> np.ndarray:
    held = np.zeros((B.S, B.D, NB))
    held[:, :, :EXIT_BAR] = 1.0
    return held


def buy_and_hold(B: Bars, F: Features, sym: str = "SPY") -> np.ndarray:
    """Close-to-close return of one symbol (price only on the proxy, dividends in on Alpaca's adjusted bars)."""
    j = B.syms.index(sym)
    with np.errstate(invalid="ignore", divide="ignore"):
        r = B.c[j, :, NB - 1] / F.prev_close[j] - 1
    return np.nan_to_num(r)


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------

sharpe, max_dd = et.sharpe, et.max_dd


def stationary_bootstrap(x: np.ndarray, y: np.ndarray | None = None, draws: int = BOOT_DRAWS,
                         block: int = BOOT_BLOCK, seed: int = 0) -> dict:
    """Politis-Romano stationary bootstrap (geometric blocks, mean `block` days) of the
    annual Sharpe of x, and of Sharpe(x) - Sharpe(y) on the same resampled days."""
    rng = np.random.default_rng(seed)
    n = x.size
    out_x, out_d = np.empty(draws), np.empty(draws)
    chunk = max(1, 2_000_000 // max(n, 1))
    ar = np.arange(n)
    for a in range(0, draws, chunk):
        m = min(chunk, draws - a)
        new = rng.random((m, n)) < 1.0 / block
        new[:, 0] = True
        starts = rng.integers(0, n, (m, n))
        last = np.maximum.accumulate(np.where(new, ar[None, :], 0), 1)
        idx = (np.take_along_axis(starts, last, 1) + (ar[None, :] - last)) % n
        xs = x[idx]
        sd = xs.std(1, ddof=1)
        sx = np.where(sd > 0, xs.mean(1) / np.where(sd > 0, sd, 1) * math.sqrt(YEAR_DAYS), 0.0)
        out_x[a:a + m] = sx
        if y is not None:
            ys = y[idx]
            sdy = ys.std(1, ddof=1)
            sy = np.where(sdy > 0, ys.mean(1) / np.where(sdy > 0, sdy, 1) * math.sqrt(YEAR_DAYS), 0.0)
            out_d[a:a + m] = sx - sy
    res = {"p05": float(np.quantile(out_x, 0.05)), "p50": float(np.median(out_x)),
           "p95": float(np.quantile(out_x, 0.95)), "share_above_0": float((out_x > 0).mean())}
    if y is not None:
        res.update(diff_p05=float(np.quantile(out_d, 0.05)), diff_p95=float(np.quantile(out_d, 0.95)),
                   diff_share_above_0=float((out_d > 0).mean()))
    return res


def _z(n: int) -> float:
    g = 0.5772156649
    return (1 - g) * stats.norm.ppf(1 - 1 / n) + g * stats.norm.ppf(1 - 1 / (n * math.e))


def pooled_deflation(row: dict, mine: list[float], prior_n: int, prior_bar: float) -> dict:
    """Deflated p of one row against the prior pool (variance backed out of its published
    annual bar) pooled with this study's trial Sharpes (annual, clipped at +-3)."""
    v1 = (prior_bar / _z(prior_n)) ** 2
    x = np.clip(np.array(mine), -SR_CLIP, SR_CLIP)
    v2 = float(np.var(x))
    n = prior_n + len(x)
    v = (prior_n * v1 + len(x) * v2) / n
    s = row["oos_sharpe"] / math.sqrt(YEAR_DAYS)
    p = deflated_sharpe(s, row["oos_days"], n, v / YEAR_DAYS, row["oos_skew"], row["oos_kurt"])
    return {"n_total": n, "bar_annual": math.sqrt(v) * _z(n), "p": p}


def per_year(dates: np.ndarray, x: np.ndarray, mask: np.ndarray) -> dict[int, float]:
    yr = dates.astype("datetime64[Y]").astype(int) + 1970
    return {int(y): float(np.prod(1 + x[mask & (yr == y)]) - 1) for y in np.unique(yr[mask])}


# ---------------------------------------------------------------------------
# The study
# ---------------------------------------------------------------------------

def evaluate(B: Bars, F: Features, U: np.ndarray, v: dict, cost: np.ndarray, windows, lag: int = 0,
             allow: np.ndarray | None = None) -> tuple[dict, np.ndarray, np.ndarray]:
    held = held_from_targets(targets(B, F, v), lag)
    sim = simulate(B, held, allow)
    x1, x2 = book(sim, U, cost, 1.0), book(sim, U, cost, 2.0)
    is_m, oos_m = windows
    row = {k: v[k] for k in v}
    row.update(is_sharpe=sharpe(x1[is_m]), oos_sharpe=sharpe(x1[oos_m]), oos_sharpe_2x=sharpe(x2[oos_m]),
               is_sharpe_2x=sharpe(x2[is_m]))
    s = et.summary(x1[oos_m])
    nU = np.maximum(U.sum(0), 1)
    ent = (np.where(U, sim.entries, 0).sum(0) / nU)[oos_m]
    gross = (np.where(U, sim.gross, 0).sum(0) / nU)[oos_m]
    trades = np.where(U, sim.entries, 0)[:, oos_m].sum()
    net_slot = np.where(U, sim.net(cost), 0)[:, oos_m].sum()
    row.update(oos_cagr=s["cagr"], oos_vol=s["vol"], oos_max_dd=s["max_dd"], oos_days=s["days"],
               oos_skew=s["skew"], oos_kurt=s["kurt"],
               trades_per_day=float(ent.mean()), oos_gross_yr=float(gross.mean() * YEAR_DAYS),
               net_bps_per_trade=float(net_slot / trades * 1e4) if trades else 0.0,
               expo=float((np.where(U, sim.expo, 0).sum(0) / nU)[oos_m].mean()))
    return row, x1, x2


def run(B: Bars, event_days: set | None = None) -> dict:
    F = features(B)
    U = universe(B, F)
    cost = cost_per_side(B.syms)
    is_from, oos_from = WINDOWS.get(B.source, WINDOWS["alpaca"])
    is_m = (B.dates >= is_from) & (B.dates < oos_from)
    oos_m = B.dates >= oos_from
    if not is_m.any() or not oos_m.any():
        raise DataUnavailable(f"data {B.dates[0]} to {B.dates[-1]} does not cover both windows")
    W = (is_m, oos_m)
    rows, series = [], {}
    for v in grid():
        r, x1, x2 = evaluate(B, F, U, v, cost, W)
        rows.append(r)
        series[v["name"]] = (x1, x2)
    pick = max(rows, key=lambda r: r["is_sharpe"])
    fam_picks = {}
    for fam in ("ORB", "Gap", "VWAP", "Momentum"):
        fam_picks[fam] = max((r for r in rows if r["family"] == fam), key=lambda r: r["is_sharpe"])
    long_pick = max((r for r in rows if not r["longshort"]), key=lambda r: r["is_sharpe"])

    macro = np.broadcast_to(~macro_days(B.dates, event_days)[None, :], (B.S, B.D))
    calm = ~abnormal_open(F)
    rob = {}
    for fam, p in fam_picks.items():
        base = {k: p[k] for k in ("family", "name", "rule", "minutes", "longshort", "stop", "g", "mode", "k", "signal")
                if k in p}
        for tag, lag, allow in (("one bar later", 1, None), ("macro-day filter", 0, macro),
                                ("abnormal-open filter", 0, calm)):
            v = dict(base, name=f"{p['name']} · {tag}", robustness=tag)
            r, x1, x2 = evaluate(B, F, U, v, cost, W, lag, allow)
            rows.append(r)
            series[v["name"]] = (x1, x2)
            rob[(fam, tag)] = r
    defl = et.deflate(rows, key="oos_sharpe")
    mine = [r["oos_sharpe"] for r in rows]
    pools = {k: pooled_deflation(pick, mine, n, bar) for k, (n, bar) in PRIOR_POOLS.items()}

    drift = simulate(B, drift_held(B))
    drift_x = book(drift, U, cost)
    spy = buy_and_hold(B, F)
    etf_U = U & np.array([s in ETFS for s in B.syms])[:, None]
    bench = {"session drift (open to 15:55, same symbols and costs)": drift_x,
             "SPY buy and hold" + (" (S&P 500 CFD, no dividends)" if B.source == "proxy" else ""): spy}

    def verdict(p: dict) -> dict:
        x = series[p["name"]][0]
        late = rob[(p["family"], "one bar later")]
        boot = stationary_bootstrap(x[oos_m], spy[oos_m])
        yrs = per_year(B.dates, x, oos_m)
        pos_share = float(np.mean([v > 0 for v in yrs.values()])) if yrs else 0.0
        gates = {
            "deflated p > 0.95 over this study's trials": p["deflated_p"] > 0.95,
            "OOS Sharpe >= half the in-sample one": p["is_sharpe"] > 0 and p["oos_sharpe"] >= 0.5 * p["is_sharpe"],
            "Sharpe > 0 with costs doubled": p["oos_sharpe_2x"] > 0,
            "bootstrap 90 % lower bound > 0": boot["p05"] > 0,
            "positive in >= 60 % of OOS years": pos_share >= 0.6,
            "Sharpe > 0 with fills one bar later": late["oos_sharpe"] > 0,
        }
        recent = (B.dates >= RECENT) & oos_m
        return {"name": p["name"], "row": p, "bootstrap": boot, "years": yrs, "pos_share": pos_share,
                "late_sharpe": late["oos_sharpe"], "gates": gates, "passes": all(gates.values()),
                "recent_sharpe": sharpe(x[recent]) if recent.sum() > 20 else None,
                "recent_days": int(recent.sum())}

    verdicts = {"overall": verdict(pick), **{f: verdict(p) for f, p in fam_picks.items()}}
    pick_x = series[pick["name"]][0]
    bench_rows = []
    for label, x in bench.items():
        s = et.summary(x[oos_m])
        bench_rows.append({"book": label, "is_sharpe": sharpe(x[is_m]), "oos_sharpe": s["sharpe"],
                           "oos_cagr": s["cagr"], "oos_vol": s["vol"], "oos_max_dd": s["max_dd"],
                           "recent_sharpe": sharpe(x[(B.dates >= RECENT) & oos_m]) if ((B.dates >= RECENT) & oos_m).sum() > 20 else None})
    # Information only (not a trial): the pick on the ETF leg alone.
    pick_sim = simulate(B, held_from_targets(targets(B, F, pick)))
    etf_only = book(pick_sim, etf_U, cost)
    return {
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": B.source, "notes": B.notes,
        "data": {"first": str(B.dates[0]), "last": str(B.dates[-1]), "days": int(B.D), "symbols": B.syms,
                 "is_days": int(is_m.sum()), "oos_days": int(oos_m.sum()),
                 "universe_mean": float(U.sum(0)[oos_m].mean())},
        "windows": {"in_sample_from": str(is_from), "oos_from": str(oos_from), "recent_from": str(RECENT)},
        "rows": rows, "deflation": defl, "pools": pools,
        "pick": pick["name"], "family_picks": {f: p["name"] for f, p in fam_picks.items()},
        "long_only_pick": {"name": long_pick["name"], "is_sharpe": long_pick["is_sharpe"],
                           "oos_sharpe": long_pick["oos_sharpe"], "oos_sharpe_2x": long_pick["oos_sharpe_2x"],
                           "deflated_p": long_pick["deflated_p"]},
        "benchmarks": bench_rows, "verdicts": verdicts,
        "corr_with_spy": float(np.corrcoef(pick_x[oos_m], spy[oos_m])[0, 1]) if pick_x[oos_m].std() > 0 else 0.0,
        "etf_leg_oos_sharpe": sharpe(etf_only[oos_m]),
        "passes": verdicts["overall"]["passes"],
    }


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def _begin(source: str) -> str:
    return f"<!-- generated below by lab.experiments.intraday_equities --source {source}; do not edit -->"


def _end(source: str) -> str:
    return f"<!-- end of the generated {source} section -->"


def splice(text: str, source: str, section: str) -> str:
    """Replace this source's generated section (or append it); everything else stays."""
    b, e = _begin(source), _end(source)
    block = f"{b}\n\n{section.rstrip()}\n\n{e}\n"
    if b in text and e in text:
        pre, rest = text.split(b, 1)
        post = rest.split(e, 1)[1].lstrip("\n")
        return pre + block + ("\n" + post if post else "")
    return text.rstrip() + "\n\n" + block


def _f(x, nd=2) -> str:
    return "n/a" if x is None else f"{x:.{nd}f}"


def markdown(res: dict) -> str:
    from ..report import table
    src = res["source"]
    title = {"proxy": "Proxy run (Oanda index CFDs as SPY, QQQ, IWM; no single stocks)",
             "alpaca": "Alpaca run (ETFs and the 20 most liquid of 40 large caps)"}.get(src, f"{src} run")
    d, w, ov = res["data"], res["windows"], res["verdicts"]["overall"]
    lines = [f"## {title}", "",
             f"Generated {res['generated']}. Data {d['first']} to {d['last']} ({d['days']} sessions), in sample "
             f"from {w['in_sample_from']} ({d['is_days']} days), out of sample from {w['oos_from']} "
             f"({d['oos_days']} days), {d['universe_mean']:.1f} symbols a day on average. "
             + " ".join(n.rstrip(".") + "." for n in res["notes"]), ""]
    n_pass = sum(v["passes"] for v in res["verdicts"].values())
    lines += [f"**Verdict: {'the overall pick passes' if ov['passes'] else 'nothing passes' if n_pass == 0 else 'the overall pick fails'}"
              f"{'' if src != 'proxy' else ' on the proxy (a pass here only marks it pending the Alpaca run)'}.** "
              f"Pick by in-sample Sharpe: {ov['name']}, out of sample Sharpe {ov['row']['oos_sharpe']:.2f} "
              f"({ov['row']['oos_sharpe_2x']:.2f} with costs doubled, {ov['late_sharpe']:.2f} filled a bar late), "
              f"in sample {ov['row']['is_sharpe']:.2f}; deflated p {ov['row']['deflated_p']:.2f} over "
              f"{res['deflation']['n_trials']} trials.", ""]
    cols = ["name", "is_sharpe", "oos_sharpe", "oos_sharpe_2x", "oos_cagr", "oos_max_dd", "trades_per_day",
            "net_bps_per_trade", "expo", "deflated_p"]
    lines += ["### Every trial (base cost; Sharpe from daily book returns, x sqrt 252)", "",
              table([r for r in res["rows"] if not r.get("robustness")], cols),
              "Robustness on each family's pick (counted):", "",
              table([r for r in res["rows"] if r.get("robustness")], cols)]
    df = res["deflation"]
    lines += [f"{df['n_trials']} trials in this study; the best of that many noise books would show an annual "
              f"Sharpe of about {df['expected_max_noise_sharpe_annual']:.2f}. Pooled with the lab's earlier trials: "
              + "; ".join(f"{k} {v['n_total']} trials, bar {v['bar_annual']:.2f}, deflated p {v['p']:.2f}"
                          for k, v in res["pools"].items()) + ".", ""]
    lines += ["### Benchmarks (out of sample)", "",
              table(res["benchmarks"], ["book", "is_sharpe", "oos_sharpe", "oos_cagr", "oos_vol", "oos_max_dd",
                                        "recent_sharpe"]),
              f"The pick's daily returns correlate {res['corr_with_spy']:.2f} with SPY's. "
              f"The pick on the ETF leg alone (information, not a trial): out of sample Sharpe "
              f"{res['etf_leg_oos_sharpe']:.2f}. Best long-only variant in sample (only a long-only pick can become "
              f"a book): {res['long_only_pick']['name']}, out of sample {res['long_only_pick']['oos_sharpe']:.2f} "
              f"({res['long_only_pick']['oos_sharpe_2x']:.2f} doubled), deflated p "
              f"{res['long_only_pick']['deflated_p']:.2f}.", ""]
    lines += ["### Gates, per pick", ""]
    gate_names = list(ov["gates"])
    head = ["pick", "trial"] + [str(i + 1) for i in range(len(gate_names))] + ["boot 5 %", "boot 95 %",
                                                                                 "minus SPY 5 to 95 %",
                                                                                 f"from {w['recent_from'][:4]}"]
    rows = []
    for k, v in res["verdicts"].items():
        b = v["bootstrap"]
        rows.append({"pick": k, "trial": v["name"], **{str(i + 1): ("pass" if v["gates"][g] else "FAIL")
                                                       for i, g in enumerate(gate_names)},
                     "boot 5 %": b["p05"], "boot 95 %": b["p95"],
                     "minus SPY 5 to 95 %": f"{b['diff_p05']:.2f} to {b['diff_p95']:.2f}",
                     f"from {w['recent_from'][:4]}": _f(v["recent_sharpe"])})
    lines += [table(rows, head), "Gates: " + "; ".join(f"{i + 1} {g}" for i, g in enumerate(gate_names)) + ".",
              "Bootstrap: stationary, mean block 10 days, 5,000 draws, of the out-of-sample Sharpe.", ""]
    years = sorted(ov["years"])
    lines += ["### The overall pick by year (out of sample, return at base cost)", "",
              table([{"year": y, "return": ov["years"][y]} for y in years], ["year", "return"])]
    return "\n".join(lines)


def write(res: dict) -> str:
    md = markdown(res)
    d = REPORTS / NAME
    d.mkdir(parents=True, exist_ok=True)
    from ..report import feed_header
    ov = res["verdicts"]["overall"]
    head = feed_header(f"Intraday US ETFs and large caps ({res['source']})",
                       "ok" if res["passes"] else "bad",
                       f"{ov['name']}: OOS Sharpe {ov['row']['oos_sharpe']:.2f}, "
                       f"{'passes' if res['passes'] else 'fails'} the bar",
                       [{"label": k, "value": f"{v['row']['oos_sharpe']:.2f}",
                         "status": "ok" if v["passes"] else "bad", "link": f"study:{NAME}"}
                        for k, v in res["verdicts"].items()])
    (d / f"{res['source']}-latest.md").write_text(md, encoding="utf-8")
    (d / f"{res['source']}-latest.json").write_text(json.dumps({**head, **res}, indent=2, default=str),
                                                     encoding="utf-8")
    path = RESULTS_DIR / f"{NAME}.md"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        text = f"# {NAME}\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(splice(text, res["source"], md), encoding="utf-8")
    return md


def read_event_days(path: str) -> set:
    out = set()
    for ln in Path(path).read_text(encoding="utf-8").splitlines():
        ln = ln.strip().split(",")[0]
        if ln and ln[0].isdigit():
            out.add(np.datetime64(ln[:10]))
    return out


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv

    def opt(name: str, default=None):
        return argv[argv.index(name) + 1] if name in argv and argv.index(name) + 1 < len(argv) else default

    source = opt("--source") or ("alpaca" if alpaca_keys() else "proxy")
    refresh = "--refresh" in argv
    events = read_event_days(opt("--event-days")) if opt("--event-days") else None
    try:
        if source == "alpaca":
            B = load_alpaca(refresh, feed=opt("--feed", "sip"))
        elif source == "proxy":
            B = load_proxy(refresh)
        else:
            print(f"{NAME}: unknown source {source}", file=sys.stderr)
            return 2
    except DataUnavailable as e:
        print(f"{NAME}: no data, nothing judged: {e}", file=sys.stderr)
        return 2
    res = run(B, events)
    print(write(res))
    return 0


if __name__ == "__main__":
    sys.exit(main())
