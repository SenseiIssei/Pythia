"""Bars for the candlestick study (X15): crypto daily and 4h OHLCV from the hourly
klines, US ETFs and S&P 500 members daily from the point-in-time equities file.

    python -m lab.experiments.candles_data          # build the crypto caches (once)

Crypto. One pass over every USDT pair's hourly segments (`picks.hourly_segments`,
reused tickers split): the sweep's daily panel rows (`picks.daily_from_hourly`,
written to `<agent out>/cache/daily_panel.parquet` so `fam_common.load_panel`
reads the same days), the day's open (first hour's open), and 4-hour bars on the
UTC grid (at least 3 of 4 hours). Equities. `equities_ranking`'s file: open,
high, low and close scaled by adjusted close / close (dividends count), share
volume, point-in-time S&P 500 membership; rows spliced from CRSP carry no open,
high or low and give no candle.

Every set becomes a `BarSet`: (T, N) arrays, eligibility, a priority for slots,
per-side costs, the in-sample and out-of-sample masks, and the UTC or calendar
day of every bar (to compound bar returns into days).
"""

from __future__ import annotations

import json
import shutil
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone

import numpy as np
import polars as pl

from .. import universe
from ..data import ROOT
from . import fam_common as fc

DAY_US = fc.DAY_US
H4_US = 4 * fc.HOUR_US
CRYPTO_SPLIT = fc.SPLIT
EQ_START = np.datetime64("1997-01-01")
EQ_IS_FROM = np.datetime64("1998-01-01")
EQ_SPLIT = np.datetime64("2016-01-01")
CRYPTO_COST = 0.0035
ETF_COST = {"SPY": 0.0001, "QQQ": 0.0001}
ETF_COST_OTHER = 0.0002
STOCK_COST = 0.0005
SEC_FEE = 27.80e-6
ETFS = ("SPY", "QQQ", "IWM", "DIA", "MDY", "XLB", "XLE", "XLF", "XLI", "XLK", "XLP", "XLU", "XLV", "XLY", "XLC",
        "XLRE", "EFA", "EEM", "TLT", "IEF", "LQD", "HYG", "GLD", "SLV", "VNQ")
TWIN_TOP = 30
PRIORITY_N = 28


@dataclass
class BarSet:
    name: str
    ts: np.ndarray              # (T,) bar start, us (crypto) or datetime64[D] (equities)
    names: list[str]
    o: np.ndarray
    h: np.ndarray
    l: np.ndarray
    c: np.ndarray
    v: np.ndarray
    elig: np.ndarray            # (T, N) a signal on this bar may be traded
    prio: np.ndarray            # (T, N) slot priority (28-bar mean dollar volume)
    cost: np.ndarray            # (N,) cost per side
    sell_fee: float
    ins: np.ndarray             # (T,) in-sample bars
    oos: np.ndarray             # (T,) out-of-sample bars
    day: np.ndarray             # (T,) day index of each bar (into `days`)
    days: np.ndarray            # (D,) the days (us or datetime64[D])
    per_year: float             # days per year for annualising (365 crypto, 252 equities)
    extra: dict = field(default_factory=dict)

    @property
    def T(self) -> int:
        return len(self.ts)

    @property
    def N(self) -> int:
        return len(self.names)

    def years(self) -> np.ndarray:
        """(D,) calendar year of each day."""
        d = self.days
        if np.issubdtype(d.dtype, np.datetime64):
            return d.astype("datetime64[Y]").astype(int) + 1970
        return np.array([datetime.fromtimestamp(int(x) / 1e6, timezone.utc).year for x in d])


# ---------------------------------------------------------------------------
# Crypto caches
# ---------------------------------------------------------------------------

def _cache(name: str):
    return fc.OUT / "cache" / name


def _symbol_frames(sym: str) -> list[tuple[pl.DataFrame, pl.DataFrame]]:
    from .picks import daily_from_hourly, hourly_segments
    out = []
    segs = hourly_segments(sym)
    for j, seg in enumerate(segs):
        name = sym if j == len(segs) - 1 else f"{sym}~{j}"
        d = daily_from_hourly(seg, name)
        if d.height < 30:
            continue
        op = (seg.with_columns(day=(pl.col("open_time_us") // DAY_US) * DAY_US)
              .group_by("day", maintain_order=True).agg(open=pl.col("open").first()))
        d = d.join(op, on="day", how="left")
        b4 = (seg.with_columns(ts=(pl.col("open_time_us") // H4_US) * H4_US)
              .group_by("ts", maintain_order=True)
              .agg(open=pl.col("open").first(), high=pl.col("high").max(), low=pl.col("low").min(),
                   close=pl.col("close").last(), qv=pl.col("quote_volume").sum(), n=pl.len())
              .filter(pl.col("n") >= 3).with_columns(symbol=pl.lit(name)))
        out.append((d, b4))
    return out


def build_crypto(fresh: bool = False) -> None:
    """Write daily_panel.parquet (the sweep's format), candles_daily.parquet and candles_4h.parquet."""
    if not fresh and all(_cache(n).exists() for n in ("daily_panel.parquet", "candles_daily.parquet",
                                                         "candles_4h.parquet")):
        return
    t0 = time.time()
    syms = json.loads((ROOT / "hist" / "universe.json").read_text(encoding="utf-8"))
    syms = [s for s in syms if s not in fc.EXCLUDE and s.isascii() and not fc._is_stock_token(s)]
    days, fours = [], []
    with ThreadPoolExecutor(8) as ex:
        for i, fr in enumerate(ex.map(_symbol_frames, syms)):
            for d, b4 in fr:
                days.append(d)
                fours.append(b4)
            if i % 100 == 0:
                print(f"  crypto bars {i}/{len(syms)} {time.time() - t0:.0f}s", flush=True)
    d = pl.concat(days, how="vertical_relaxed").sort(["symbol", "day"])
    _cache("x").parent.mkdir(parents=True, exist_ok=True)
    d.select("day", "symbol", "close", "high", "low", "rv", "qv", "n").write_parquet(_cache("daily_panel.parquet"))
    d.select("day", "symbol", "open", "high", "low", "close", "qv").write_parquet(_cache("candles_daily.parquet"))
    pl.concat(fours, how="vertical_relaxed").sort(["symbol", "ts"]).write_parquet(_cache("candles_4h.parquet"))
    src = ROOT / "agent-strategies" / "cache" / "perp_daily.parquet"
    if not _cache("perp_daily.parquet").exists() and src.exists():
        shutil.copy(src, _cache("perp_daily.parquet"))
    print(f"crypto caches written, {time.time() - t0:.0f}s", flush=True)


def _matrix(frame: pl.DataFrame, key: str, keys: np.ndarray, names: list[str], cols: list[str]) -> dict:
    ki = {int(k): i for i, k in enumerate(keys)}
    ni = {n: j for j, n in enumerate(names)}
    f = frame.filter(pl.col("symbol").is_in(names))
    r = np.array([ki.get(int(x), -1) for x in f[key].to_numpy()])
    c = np.array([ni[s] for s in f["symbol"].to_list()])
    ok = r >= 0
    out = {}
    for col in cols:
        m = np.full((len(keys), len(names)), np.nan)
        m[r[ok], c[ok]] = f[col].to_numpy().astype(float)[ok]
        out[col] = m
    return out


def _twin_cols(P: fc.Panel) -> tuple[np.ndarray, np.ndarray]:
    top = P.top_liquid(TWIN_TOP)
    return top, np.flatnonzero(top.any(0))


def crypto_daily(P: fc.Panel, twin: bool = False) -> BarSet:
    """CD: the Alpaca coins (current segment of each), or the twin's 30 most liquid of each day."""
    if twin:
        top, cols = _twin_cols(P)
        elig_full = top
    else:
        cols = np.flatnonzero(universe.mask(P, universe.ALPACA))
        elig_full = P.eligible
    names = [P.names[j] for j in cols]
    f = pl.read_parquet(_cache("candles_daily.parquet"))
    m = _matrix(f, "day", P.days, names, ["open", "high", "low", "close", "qv"])
    T = P.T
    ins = (P.days < CRYPTO_SPLIT)
    return BarSet("CD twin" if twin else "CD", P.days, names, m["open"], m["high"], m["low"], m["close"], m["qv"],
                  elig_full[:, cols] & np.isfinite(m["open"]), np.nan_to_num(P.adv28[:, cols]),
                  np.full(len(cols), CRYPTO_COST), 0.0, ins, ~ins, np.arange(T), P.days, 365.0,
                  extra={"cols": cols, "px": P.px[:, cols], "last": P.extra["last"][cols]})


def crypto_4h(P: fc.Panel, twin: bool = False) -> BarSet:
    """C4: 4-hour bars of the same coins; eligibility and priority of the last completed UTC day."""
    if twin:
        top, cols = _twin_cols(P)
        elig_d = top
    else:
        cols = np.flatnonzero(universe.mask(P, universe.ALPACA))
        elig_d = P.eligible
    names = [P.names[j] for j in cols]
    f = pl.read_parquet(_cache("candles_4h.parquet")).filter(pl.col("symbol").is_in(names))
    t0, t1 = int(P.days[0]), int(P.days[-1]) + DAY_US
    ts = np.arange(t0, t1, H4_US, dtype=np.int64)
    m = _matrix(f, "ts", ts, names, ["open", "high", "low", "close", "qv"])
    dprev = (ts + H4_US - t0) // DAY_US - 1                  # last completed UTC day at the bar's close
    ok = dprev >= 0
    dclip = np.clip(dprev, 0, P.T - 1)
    elig = np.where(ok[:, None], elig_d[dclip][:, cols], False) & np.isfinite(m["open"])
    prio = np.where(ok[:, None], np.nan_to_num(P.adv28[dclip][:, cols]), 0.0)
    day = (ts - t0) // DAY_US
    ins = ts < CRYPTO_SPLIT
    close = m["close"]
    # Close carried forward inside each coin's life (exits after a missing bar or the end).
    fin = np.isfinite(close)
    idx = np.arange(len(ts))[:, None]
    first = np.where(fin.any(0), np.argmax(fin, 0), len(ts))
    last = np.where(fin.any(0), len(ts) - 1 - np.argmax(fin[::-1], 0), -1)
    alive = (idx >= first[None, :]) & (idx <= last[None, :])
    fidx = np.maximum.accumulate(np.where(fin, idx, 0), axis=0)
    px = np.where(alive, close[fidx, np.arange(len(names))[None, :]], np.nan)
    return BarSet("C4 twin" if twin else "C4", ts, names, m["open"], m["high"], m["low"], close, m["qv"], elig, prio,
                  np.full(len(cols), CRYPTO_COST), 0.0, ins, ~ins, day, P.days, 365.0,
                  extra={"cols": cols, "px": px, "last": last})


# ---------------------------------------------------------------------------
# Equities
# ---------------------------------------------------------------------------

def _eq_frames():
    from . import equities_ranking as er
    files = er.load_files()
    px = pl.read_parquet(files["prices.parquet"])
    mem = pl.read_parquet(files["membership_intervals.parquet"])
    return px, mem


def _eq_set(name: str, px: pl.DataFrame, tickers: list[str], member: dict | None, cost: np.ndarray,
            dates: np.ndarray) -> BarSet:
    f = (px.filter(pl.col("ticker").is_in(tickers))
         .with_columns(date=pl.col("date").cast(pl.Date))
         .filter(pl.col("date") >= EQ_START.astype(object))
         .filter(pl.col("adj_close") > 0)
         .unique(["ticker", "date"], keep="last")
         .with_columns(k=pl.col("adj_close") / pl.col("close")))
    T, N = len(dates), len(tickers)
    ci = {t: j for j, t in enumerate(tickers)}
    r = np.searchsorted(dates, f["date"].to_numpy().astype("datetime64[D]"))
    c = np.array([ci[t] for t in f["ticker"].to_list()])
    k = f["k"].to_numpy()

    def mat(col: str, scale: bool) -> np.ndarray:
        m = np.full((T, N), np.nan)
        x = f[col].to_numpy().astype(float)
        m[r, c] = x * k if scale else x
        return m
    O, H, L, C = mat("open", True), mat("high", True), mat("low", True), mat("adj_close", False)
    V = mat("volume", False)
    # A row without open, high or low (CRSP) keeps its close for returns but has no candle.
    nocandle = ~(np.isfinite(O) & np.isfinite(H) & np.isfinite(L))
    O = np.where(nocandle, np.nan, O)
    H = np.where(nocandle, np.nan, H)
    L = np.where(nocandle, np.nan, L)
    fin = np.isfinite(C)
    idx = np.arange(T)[:, None]
    first = np.where(fin.any(0), np.argmax(fin, 0), T)
    last = np.where(fin.any(0), T - 1 - np.argmax(fin[::-1], 0), -1)
    alive = (idx >= first[None, :]) & (idx <= last[None, :])
    fidx = np.maximum.accumulate(np.where(fin, idx, 0), axis=0)
    pxf = np.where(alive, C[fidx, np.arange(N)[None, :]], np.nan)
    dv = np.where(np.isfinite(V) & np.isfinite(C), V * C, np.nan)
    prio = np.nan_to_num(fc.rolling(dv, PRIORITY_N, 20))
    if member is None:
        mm = alive.copy()
        elig = np.isfinite(O) & np.isfinite(C)
    else:
        mm = np.zeros((T, N), dtype=bool)
        for t, spans in member.items():
            j = ci.get(t)
            if j is None:
                continue
            for a, b in spans:
                lo = np.searchsorted(dates, np.datetime64(a, "D"))
                hi = T if b is None else np.searchsorted(dates, np.datetime64(b, "D"))
                mm[lo:hi, j] = True
        elig = mm & np.isfinite(O) & np.isfinite(C)
    ins = (dates >= EQ_IS_FROM) & (dates < EQ_SPLIT)
    oos = dates >= EQ_SPLIT
    live = mm & alive & np.isfinite(C)
    no_candle = {"in_sample": float((live & nocandle)[ins].sum() / max(live[ins].sum(), 1)),
                 "out_of_sample": float((live & nocandle)[oos].sum() / max(live[oos].sum(), 1))}
    return BarSet(name, dates, list(tickers), O, H, L, C, V, elig, prio, cost, SEC_FEE, ins, oos, np.arange(T),
                  dates, 252.0, extra={"px": pxf, "last": last, "no_candle_share": no_candle})


def equities(which: str = "both") -> dict[str, BarSet]:
    px, mem = _eq_frames()
    px = px.with_columns(date=pl.col("date").cast(pl.Date))
    dates = np.array(sorted(px.filter((pl.col("ticker") == "SPY") & (pl.col("date") >= EQ_START.astype(object)))
                            ["date"].unique().to_list()), dtype="datetime64[D]")
    out = {}
    if which in ("both", "EF"):
        have = set(px["ticker"].unique().to_list())
        etfs = [t for t in ETFS if t in have]
        cost = np.array([ETF_COST.get(t, ETF_COST_OTHER) for t in etfs])
        out["EF"] = _eq_set("EF", px, etfs, None, cost, dates)
    if which in ("both", "SP"):
        m = mem.with_columns(pl.col("start").cast(pl.Date), pl.col("end").cast(pl.Date))
        spans: dict[str, list] = {}
        for t, a, b in m.select("ticker", "start", "end").iter_rows():
            spans.setdefault(t, []).append((a, b))
        tick = sorted(set(spans) & set(px["ticker"].unique().to_list()))
        out["SP"] = _eq_set("SP", px, tick, spans, np.full(len(tick), STOCK_COST), dates)
    spy = _eq_set("SPY", px, ["SPY"], None, np.array([0.0]), dates).extra["px"][:, 0]
    for b in out.values():
        b.extra["spy"] = spy
    return out


if __name__ == "__main__":
    build_crypto(fresh=True)
