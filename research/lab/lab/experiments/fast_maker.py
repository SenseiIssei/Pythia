"""W15: faster crypto trades with resting maker orders only, on the 33 Alpaca coins.

    python -m lab.experiments.fast_maker --bars 5m      # the registered run (server, 5-minute bars)
    python -m lab.experiments.fast_maker --bars 1h      # the first run, on the 1h archive
    python -m lab.experiments.fast_maker --bars 1h --resolution
                                                        # plus the 1h against 5m check on the 15 coins
                                                        # with 1-minute history
    python -m lab.experiments.fast_maker check-fills    # bars against Binance aggTrades (downloads)

Pre-registered in results/fast_maker.md (the part above the marker was committed
before this file ran; the addendum says what the 1h run changes). Four families
(drop reversion, 4h trend with pullback entries, expansion after compression,
seasonality), 44 variants. Every entry and every exit is a resting limit: it
fills only where the price trades through it, partly by depth, never more than
10 % of the volume it rested through; every maker fill is booked 3 bps worse and
pays 15 bps; an exit still open 24 hours after its decision is sold at taker
cost. The same rules with every order filled at the close at 35 bps a side are
the reference.

Two passes. Pass 1 simulates each coin alone (its orders, fills and the P&L of
each round trip per UTC day, per dollar of order). Pass 2 is the book: orders in
time order, an order skipped if the open targets would pass 100 %, sized off the
equity at the start of its decision day, in dollars from 100 000 USD.

Writes results/fast_maker.md (1h) or results/fast_maker_5m.md (5m) and
<agent-strategies>/reports/fast_maker[_5m].json.
"""

from __future__ import annotations

import argparse
import heapq
import json
import math
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import polars as pl

from .. import data as labdata
from . import fam_common as fc

NAME = "fast_maker"
MARKER = "<!-- generated below by lab.experiments.fast_maker; edit above this line only -->"
DATA_END = date(2026, 10, 14)
TWIN_RANK_SINCE = date(2023, 9, 1)

# Alpaca's crypto list (36 assets, March 2026) without its three stablecoins
# (USDC, USDG, USDT): 33 coins. Binance spot symbols in time order; a renamed
# token is spliced (MATIC to POL, RNDR to RENDER, MKR to SKY).
SYMBOLS: dict[str, list[str]] = {
    "AAVE": ["AAVEUSDT"], "ADA": ["ADAUSDT"], "ARB": ["ARBUSDT"], "AVAX": ["AVAXUSDT"], "BAT": ["BATUSDT"],
    "BCH": ["BCHUSDT"], "BONK": ["BONKUSDT"], "BTC": ["BTCUSDT"], "CRV": ["CRVUSDT"], "DOGE": ["DOGEUSDT"],
    "DOT": ["DOTUSDT"], "ETH": ["ETHUSDT"], "FIL": ["FILUSDT"], "GRT": ["GRTUSDT"], "HYPE": ["HYPEUSDT"],
    "LDO": ["LDOUSDT"], "LINK": ["LINKUSDT"], "LTC": ["LTCUSDT"], "ONDO": ["ONDOUSDT"], "PAXG": ["PAXGUSDT"],
    "PEPE": ["PEPEUSDT"], "POL": ["MATICUSDT", "POLUSDT"], "RENDER": ["RNDRUSDT", "RENDERUSDT"],
    "SHIB": ["SHIBUSDT"], "SKY": ["MKRUSDT", "SKYUSDT"], "SOL": ["SOLUSDT"], "SUSHI": ["SUSHIUSDT"],
    "TRUMP": ["TRUMPUSDT"], "UNI": ["UNIUSDT"], "WIF": ["WIFUSDT"], "XRP": ["XRPUSDT"], "XTZ": ["XTZUSDT"],
    "YFI": ["YFIUSDT"],
}
# The 15 of them with 1-minute history on the PC (the resolution check).
ONE_MINUTE = ("AAVE", "ADA", "AVAX", "BCH", "BTC", "DOGE", "DOT", "ETH", "FIL", "LINK", "LTC", "PEPE", "SOL",
              "UNI", "XRP")

STABLE = {"USDC", "BUSD", "TUSD", "USDP", "PAX", "DAI", "FDUSD", "USDS", "USDSB", "SUSD", "UST", "USTC", "EUR",
          "GBP", "AUD", "TRY", "BRL", "RUB", "UAH", "NGN", "ZAR", "BIDR", "IDRT", "BVND", "AEUR", "EURI", "USD1",
          "XUSD", "USDE", "BFUSD", "RLUSD", "USDG", "PYUSD", "U"}

# Fill model and book (the registration's numbers).
BOOK_USD = 100_000.0
THROUGH = 1e-4            # a limit fills only 1 bp or more through it
FULL_DEPTH = 10e-4        # 10 bps through fills the whole order
VOL_CAP = 0.10            # never more than 10 % of the quote volume rested through
HAIRCUT = 3e-4            # adverse selection, every maker fill
MAKER_FEE = 15e-4
TAKER = 35e-4             # 25 bps fee plus about 10 bps slippage
EXIT_REPLACE_MIN = 15
FALLBACK_H = 24
COIN_VOL, SLOTS = 0.40, 10
VOL_HOURS = 30 * 24
MIN_AGE_D, MIN_ADV = 60, 1_000_000.0
TOP_TWIN = 33
YEARS_OOS = (2024, 2025, 2026)
LATENCY_BARS = 1

# The pool (see the addendum): 377 hand trials to C16 (bar 2.43), 111 hand
# trials counted in parallel since (listings 16, memecoins 50, equities 45),
# the factory's ledger (300 after its first run), this study's 53.
PRIOR_TRIALS, PRIOR_SR0 = 377, 2.43
PARALLEL_HAND = 111
REGISTERED_POOL = 430
TRIALS_HERE = 53

T0 = date(2020, 1, 1)
DAY_US = fc.DAY_US
HOUR_US = fc.HOUR_US


def us(d: date) -> int:
    return int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp() * 1e6)


T0_US = us(T0)
N_DAYS = (DATA_END - T0).days + 1
IS_START_D = (date(2020, 8, 1) - T0).days
SPLIT_D = (date(2024, 1, 1) - T0).days


def excluded_symbol(symbol: str) -> bool:
    """Stablecoins, fiat and leveraged tokens are never part of the twin."""
    base = symbol.split("~")[0][:-4]
    return base in STABLE or (base.endswith(("UP", "DOWN", "BULL", "BEAR")) and len(base) > 4)


# ---------------------------------------------------------------------------
# Variants
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Variant:
    family: str        # A B C D
    p: tuple           # sorted (key, value) pairs

    @property
    def d(self) -> dict:
        return dict(self.p)

    @property
    def label(self) -> str:
        d = self.d
        if self.family == "A":
            return f"A drop k {d['k']} · e {d['e']} · hold {d['H']}h"
        if self.family == "B":
            return (f"B {'EMA 24/96' if d['rule'] == 'ema' else 'Donchian 55/27'} · p {d['p']} · W {d['W'] // 60}h"
                    + (" · BTC gate" if d["gate"] else ""))
        if self.family == "C":
            return f"C squeeze q {d['q']} · e {d['e']} · hold {d['H']}h"
        if d["kind"] == "hours":
            return f"D best {d['k']} hours · N {d['N']}m"
        return f"D {d['kind']} · N {d['N']}m"


def variants() -> list[Variant]:
    out = []
    for k in (3, 5):
        for e in (0.0, 0.5):
            for H in (1, 4, 12):
                out.append(Variant("A", tuple(sorted({"k": k, "e": e, "H": H}.items()))))
    for rule in ("ema", "donchian"):
        for p in (0.5, 1.0):
            for W in (60, 240):
                for gate in (False, True):
                    out.append(Variant("B", tuple(sorted({"rule": rule, "p": p, "W": W, "gate": gate}.items()))))
    for q in (0.5, 0.7):
        for e in (0.0, 0.5):
            for H in (4, 12):
                out.append(Variant("C", tuple(sorted({"q": q, "e": e, "H": H}.items()))))
    for k in (2, 4):
        for N in (15, 30):
            out.append(Variant("D", tuple(sorted({"kind": "hours", "k": k, "N": N}.items()))))
    for kind in ("weekend", "weekdays"):
        for N in (15, 60):
            out.append(Variant("D", tuple(sorted({"kind": kind, "k": 0, "N": N}.items()))))
    return out


# ---------------------------------------------------------------------------
# Bars
# ---------------------------------------------------------------------------

def _read(files: list[Path]) -> pl.DataFrame:
    if not files:
        return pl.DataFrame()
    fr = [pl.read_parquet(f) for f in files]
    out = pl.concat([f.select("open_time_us", "open", "high", "low", "close", "quote_volume") for f in fr],
                    how="vertical_relaxed")
    return out.unique("open_time_us", keep="last").sort("open_time_us")


def _kdir(iv: str, symbol: str) -> Path:
    return labdata.ROOT / "hist" / "binance_spot" / f"klines_{iv}" / f"symbol={symbol}"


def segment_range(name: str) -> tuple[int, int] | None:
    """[first, last] open time of the 1h segment `name` (SYM or SYM~j), the sweep's splitting."""
    from .picks import hourly_segments
    sym, _, j = name.partition("~")
    segs = hourly_segments(sym)
    if not segs:
        return None
    s = segs[int(j)] if j else segs[-1]
    return int(s["open_time_us"].min()), int(s["open_time_us"].max())


def raw_bars(name: str, bar_min: int) -> pl.DataFrame:
    """One segment's bars at `bar_min` minutes: 1h from the 1h archive, 5m from 5m archives or
    from 1m history. Columns open_time_us, open, high, low, close, quote_volume."""
    rng = segment_range(name)
    if rng is None:
        return pl.DataFrame()
    sym = name.split("~")[0]
    if bar_min == 60:
        df = _read(sorted(_kdir("1h", sym).glob("*.parquet")))
    elif bar_min == 5:
        f5 = sorted(_kdir("5m", sym).glob("*.parquet"))
        if f5:
            df = _read(f5)
        else:
            f1 = sorted(_kdir("1m", sym).glob("*.parquet"))
            if not f1:
                return pl.DataFrame()
            m = _read(f1)
            step = 5 * 60_000_000
            df = (m.with_columns(open_time_us=(pl.col("open_time_us") // step) * step)
                  .group_by("open_time_us", maintain_order=True)
                  .agg(open=pl.col("open").first(), high=pl.col("high").max(), low=pl.col("low").min(),
                       close=pl.col("close").last(), quote_volume=pl.col("quote_volume").sum())
                  .sort("open_time_us"))
    else:
        raise ValueError(bar_min)
    if df.is_empty():
        return df
    return df.filter((pl.col("open_time_us") >= rng[0]) & (pl.col("open_time_us") < rng[1] + HOUR_US))


def splice(frames: list[pl.DataFrame]) -> pl.DataFrame:
    """Older series up to the first bar of the newer one, rescaled so the price does not jump.

    The factor is the median ratio of the two closes over the first week of overlap, or the
    new first close over the old last close when they do not overlap. Volume is not rescaled."""
    out = frames[0]
    for new in frames[1:]:
        if out.is_empty():
            out = new
            continue
        if new.is_empty():
            continue
        t_new = int(new["open_time_us"][0])
        ov = out.join(new.select("open_time_us", pl.col("close").alias("nc")), on="open_time_us", how="inner")
        ov = ov.filter(pl.col("open_time_us") < t_new + 7 * DAY_US)
        if ov.height:
            f = float((ov["nc"] / ov["close"]).median())
        else:
            f = float(new["close"][0]) / float(out["close"][-1])
        old = out.filter(pl.col("open_time_us") < t_new).with_columns(
            [pl.col(c) * f for c in ("open", "high", "low", "close")])
        out = pl.concat([old, new], how="vertical_relaxed")
    return out


@dataclass
class Coin:
    """A coin on the global bar grid from 2020-01-01 to DATA_END: NaN where no bar."""
    name: str
    bar_min: int
    high: np.ndarray        # float32 (5-minute grids are long)
    low: np.ndarray
    traded: np.ndarray      # bool, a bar printed
    qv: np.ndarray          # quote volume, 0 where no bar (float32)
    px: np.ndarray          # close forward-filled inside the coin's life, NaN outside (float64)
    first: int
    last: int
    extra: dict = field(default_factory=dict)

    @property
    def bph(self) -> int:
        return 60 // self.bar_min

    @property
    def bpd(self) -> int:
        return 1440 // self.bar_min

    @property
    def n(self) -> int:
        return len(self.px)


def n_bars(bar_min: int) -> int:
    return N_DAYS * 1440 // bar_min


def to_coin(name: str, df: pl.DataFrame, bar_min: int) -> Coin | None:
    nb = n_bars(bar_min)
    if df.is_empty():
        return None
    i = ((df["open_time_us"].to_numpy() - T0_US) // (bar_min * 60_000_000)).astype(np.int64)
    ok = (i >= 0) & (i < nb)
    if not ok.any():
        return None
    arr = {}
    for c in ("high", "low", "close", "quote_volume"):
        a = np.full(nb, np.nan)
        a[i[ok]] = df[c].to_numpy().astype(float)[ok]
        arr[c] = a
    traded = np.isfinite(arr["close"]) & (arr["close"] > 0)
    first = int(np.argmax(traded))
    last = int(nb - 1 - np.argmax(traded[::-1]))
    idx = np.arange(nb)
    fidx = np.maximum.accumulate(np.where(traded, idx, 0))
    px = np.where((idx >= first) & (idx <= last), arr["close"][fidx], np.nan)
    return Coin(name, bar_min, arr["high"].astype(np.float32), arr["low"].astype(np.float32), traded,
                np.nan_to_num(arr["quote_volume"]).astype(np.float32), px, first, last)


def load_coin(coin: str, bar_min: int) -> Coin | None:
    frames = [raw_bars(s, bar_min) for s in SYMBOLS[coin]]
    frames = [f for f in frames if not f.is_empty()]
    if not frames:
        return None
    return to_coin(coin, splice(frames), bar_min)


# ---------------------------------------------------------------------------
# Features (hour, 4h and day grids, all known at the close they are used at)
# ---------------------------------------------------------------------------

def _rms_prev(r: np.ndarray, w: int, min_obs: int) -> np.ndarray:
    """sqrt(mean(r^2)) over the w values BEFORE each index (NaN skipped, min_obs needed)."""
    x = np.where(np.isfinite(r), r * r, 0.0)
    m = np.isfinite(r).astype(float)
    cx, cm = np.r_[0.0, np.cumsum(x)], np.r_[0.0, np.cumsum(m)]
    n = len(r)
    i = np.arange(n)
    lo = np.maximum(i - w, 0)
    s, k = cx[i] - cx[lo], cm[i] - cm[lo]
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(k >= min_obs, np.sqrt(s / np.maximum(k, 1)), np.nan)


def _roll_prev_extreme(x: np.ndarray, w: int, how: str) -> np.ndarray:
    """max / min of the w values before each index (NaN where fewer than w finite)."""
    from numpy.lib.stride_tricks import sliding_window_view
    n = len(x)
    out = np.full(n, np.nan)
    if n <= w:
        return out
    v = sliding_window_view(x, w)[: n - w]             # windows ending at i-1, for i = w..n-1
    with np.errstate(invalid="ignore"):
        ok = np.isfinite(v).all(1)
        e = v.max(1) if how == "max" else v.min(1)
    out[w:] = np.where(ok, e, np.nan)
    return out


def ema(x: np.ndarray, span: int) -> np.ndarray:
    a = 2 / (span + 1)
    out = np.full_like(x, np.nan)
    cur = np.nan
    for t in range(len(x)):
        v = x[t]
        if not np.isfinite(v):
            continue
        cur = v if not np.isfinite(cur) else cur + a * (v - cur)
        out[t] = cur
    return out


def features(c: Coin) -> dict:
    """Everything the rules need, on the coin's own grids. Cached on the coin."""
    if "f" in c.extra:
        return c.extra["f"]
    bph, nb = c.bph, c.n
    H = nb // bph
    hc = c.px[bph - 1::bph][:H]                       # close at each hour's end
    hr = np.full(H, np.nan)
    with np.errstate(invalid="ignore", divide="ignore"):
        hr[1:] = hc[1:] / hc[:-1] - 1
    sig_prev = _rms_prev(hr, VOL_HOURS, int(VOL_HOURS * 0.8))      # up to the hour before
    rv24 = _rms_prev(np.r_[hr[1:], np.nan], 24, 20)                 # the last 24 hours incl. this one
    max24 = _roll_prev_extreme(hc, 24, "max")
    # 4h grid
    K = H // 4
    c4 = hc[3::4][:K]
    r4 = np.full(K, np.nan)
    with np.errstate(invalid="ignore", divide="ignore"):
        r4[1:] = c4[1:] / c4[:-1] - 1
    sig4 = _rms_prev(r4, VOL_HOURS // 4, int(VOL_HOURS // 4 * 0.8))
    ema_on = ema(c4, 24) > ema(c4, 96)
    hi55, lo27 = _roll_prev_extreme(c4, 55, "max"), _roll_prev_extreme(c4, 27, "min")
    don = np.zeros(K, dtype=bool)
    on = False
    for k in range(K):
        if not np.isfinite(c4[k]):
            on = False
        elif not on and np.isfinite(hi55[k]) and c4[k] > hi55[k]:
            on = True
        elif on and np.isfinite(lo27[k]) and c4[k] < lo27[k]:
            on = False
        don[k] = on
    # day grid: eligibility at the start of day d from days up to d-1
    D = N_DAYS
    qv_d = c.qv[: D * c.bpd].reshape(D, c.bpd).sum(1)
    traded_d = c.traded[: D * c.bpd].reshape(D, c.bpd).any(1)
    first_d = c.first // c.bpd
    alive_d = (np.arange(D) >= first_d) & (np.arange(D) <= c.last // c.bpd)
    cq = np.r_[0.0, np.cumsum(np.where(alive_d, qv_d, 0.0))]
    ca = np.r_[0.0, np.cumsum(alive_d.astype(float))]
    d = np.arange(D)
    lo = np.maximum(d - 28, 0)
    with np.errstate(invalid="ignore", divide="ignore"):
        adv = np.where(ca[d] - ca[lo] >= 20, (cq[d] - cq[lo]) / np.maximum(ca[d] - ca[lo], 1), np.nan)
    elig = alive_d & (d - first_d >= MIN_AGE_D) & (np.nan_to_num(adv) >= MIN_ADV)
    f = {"hc": hc, "hr": hr, "sig_prev": sig_prev, "rv24": rv24, "max24": max24, "c4": c4, "sig4": sig4,
         "ema_on": ema_on, "don_on": don, "adv": adv, "elig": elig, "traded_d": traded_d}
    c.extra["f"] = f
    return f


def sigma_at(c: Coin, f: dict, b: np.ndarray) -> np.ndarray:
    """Hourly vol at base bar b's close: hours ending at or before the close minus one hour."""
    close_min = (b + 1) * c.bar_min
    h = close_min // 60 - 1
    h = np.clip(h, 0, len(f["sig_prev"]) - 1)
    return f["sig_prev"][h]


def target_of(sig_h: float) -> float:
    if not np.isfinite(sig_h) or sig_h <= 0:
        return 0.0
    return min(COIN_VOL / (sig_h * math.sqrt(8760)), 1.0) / SLOTS


# ---------------------------------------------------------------------------
# Candidates: (decision bar, limit multiplier on the close, window bars, exit spec)
# ---------------------------------------------------------------------------

@dataclass
class Ctx:
    """What the book knows outside the coin: the BTC gate and, for the twin, the daily set."""
    gate_d: np.ndarray                  # (N_DAYS,) BTC close above its 200-day average at day d's close
    allowed_d: dict | None = None       # coin name -> (N_DAYS,) bool, in the twin's set at day d's close
    hours: tuple = ()                   # family D's hours of day, from the in-sample basket


def candidates(c: Coin, v: Variant, ctx: Ctx) -> tuple[np.ndarray, np.ndarray, int]:
    """Decision bars, limit multipliers and the entry window in bars, before eligibility."""
    f = features(c)
    d = v.d
    bph, nb = c.bph, c.n
    wbars = lambda minutes: max(1, -(-minutes // c.bar_min))
    if v.family == "A":
        b = np.arange(bph, nb)
        with np.errstate(invalid="ignore", divide="ignore"):
            r1 = c.px[b] / c.px[b - bph] - 1
        s = sigma_at(c, f, b)
        with np.errstate(invalid="ignore"):
            m = (r1 < -d["k"] * s) & (r1 < -0.02)
        b, s = b[m], s[m]
        return b, 1 - d["e"] * s, wbars(60)
    if v.family == "B":
        on = f["ema_on"] if d["rule"] == "ema" else f["don_on"]
        k = np.flatnonzero(on & np.isfinite(f["sig4"]))
        b = (k + 1) * 4 * bph - 1
        if d["gate"]:
            b = b[gate_at(ctx, c, b)]
            k = (b + 1) // (4 * bph) - 1
        return b, 1 - d["p"] * f["sig4"][k], wbars(d["W"])
    if v.family == "C":
        h = np.arange(len(f["hc"]))
        with np.errstate(invalid="ignore"):
            m = (f["rv24"] < d["q"] * f["sig_prev"]) & (f["hc"] > f["max24"])
        h = h[m]
        b = (h + 1) * bph - 1
        return b, 1 - d["e"] * f["sig_prev"][h], wbars(60)
    # D: the close before each window
    starts, _ = d_windows(c, v, ctx)
    return starts, np.ones(len(starts)), wbars(d["N"])


def d_windows(c: Coin, v: Variant, ctx: Ctx) -> tuple[np.ndarray, np.ndarray]:
    """Family D: (bar whose close starts the window, bar whose close ends it)."""
    d = v.d
    bph, bpd = c.bph, c.bpd
    days = np.arange(N_DAYS)
    if d["kind"] == "hours":
        sel = sorted(ctx.hours[: d["k"]])
        runs = hour_runs(sel)
        s, e = [], []
        for h0, m in runs:
            s.append(days * bpd + h0 * bph - 1)
            e.append(days * bpd + (h0 + m) * bph - 1)
        s, e = np.concatenate(s), np.concatenate(e)
    else:
        dow = (np.arange(N_DAYS) + date(2020, 1, 1).weekday()) % 7      # Monday 0
        first = 5 if d["kind"] == "weekend" else 0                        # Saturday or Monday 00:00
        length = 2 if d["kind"] == "weekend" else 5
        dd = days[dow == first]
        s = dd * bpd - 1
        e = (dd + length) * bpd - 1
    o = np.argsort(s, kind="stable")
    s, e = s[o], e[o]
    ok = (s >= 0) & (e < c.n)
    return s[ok], e[ok]


def hour_runs(sel: list[int]) -> list[tuple[int, int]]:
    """Consecutive UTC hours as (first hour, length), wrapping over midnight."""
    if not sel:
        return []
    s = set(sel)
    if len(s) == 24:
        return [(0, 24)]
    runs = []
    for h in sorted(s):
        if (h - 1) % 24 in s:
            continue
        m = 1
        while (h + m) % 24 in s:
            m += 1
        runs.append((h, m))
    return runs


def gate_at(ctx: Ctx, c: Coin, b: np.ndarray) -> np.ndarray:
    """BTC gate at bar b's close: the last daily close at or before it."""
    close_us_d = ((b + 1) * c.bar_min) // 1440          # day index whose start is at or before the close
    di = np.clip(close_us_d - 1, 0, N_DAYS - 1)
    return np.where(close_us_d >= 1, ctx.gate_d[di], False)


def day_of_decision(c: Coin, b: np.ndarray | int):
    """Index of the UTC day the order goes live in (the day after the decision's close instant)."""
    return ((np.asarray(b) + 1) * c.bar_min) // 1440


# ---------------------------------------------------------------------------
# Pass 1: one coin, one variant
# ---------------------------------------------------------------------------

@dataclass
class Trade:
    coin: str
    t_dec: int            # decision bar (global grid, after any lag), the order goes live at t_dec + 1
    dec_day: int          # the UTC day the order goes live in
    rank_key: float       # trailing 28-day quote volume, larger first
    target: float
    win_end: int          # last bar the entry rests in
    done: int             # last bar with an exit fill (= win_end when nothing filled)
    share: float          # filled share of the entry order
    d0: int = 0           # first day of the P&L arrays
    gross: np.ndarray | None = None      # (L,) daily P&L per dollar of order, before fees/haircut/fallback cost
    maker: np.ndarray | None = None      # (L,) maker notional per dollar of order
    fb: np.ndarray | None = None         # (L,) fallback (taker) notional per dollar of order
    stats: dict = field(default_factory=dict)


def _buy_fill(c: Coin, L: float, b0: int, nb: int, usd: float) -> tuple[np.ndarray, np.ndarray]:
    """Bars and share increments of a buy limit at L resting in bars b0..b0+nb-1."""
    b1 = min(b0 + nb, c.n)
    if b1 <= b0 or not np.isfinite(L) or L <= 0:
        return np.zeros(0, dtype=np.int64), np.zeros(0)
    lows = c.low[b0:b1]
    with np.errstate(invalid="ignore"):
        depth = np.where(np.isfinite(lows), (L - lows) / L, -1.0)
        share = np.where(depth >= THROUGH - 1e-12, np.minimum(1.0, depth / FULL_DEPTH), 0.0)
    cum = np.maximum.accumulate(share)
    if usd > 0:
        cum = np.minimum(cum, VOL_CAP * np.cumsum(c.qv[b0:b1], dtype=float) / usd)
    cum = np.maximum.accumulate(cum)
    inc = np.diff(np.r_[0.0, cum])
    k = np.flatnonzero(inc > 1e-12)
    return b0 + k, inc[k]


def _sell_fill(c: Coin, L: float, b0: int, nb: int, usd_left: float) -> tuple[np.ndarray, np.ndarray]:
    """Bars and shares (of what is left) of a sell limit at L resting in bars b0..b0+nb-1."""
    b1 = min(b0 + nb, c.n)
    if b1 <= b0 or not np.isfinite(L) or L <= 0:
        return np.zeros(0, dtype=np.int64), np.zeros(0)
    highs = c.high[b0:b1]
    with np.errstate(invalid="ignore"):
        depth = np.where(np.isfinite(highs), (highs - L) / L, -1.0)
        share = np.where(depth >= THROUGH - 1e-12, np.minimum(1.0, depth / FULL_DEPTH), 0.0)
    cum = np.maximum.accumulate(share)
    if usd_left > 0:
        cum = np.minimum(cum, VOL_CAP * np.cumsum(c.qv[b0:b1], dtype=float) / usd_left)
    cum = np.maximum.accumulate(cum)
    inc = np.diff(np.r_[0.0, cum])
    k = np.flatnonzero(inc > 1e-12)
    return b0 + k, inc[k]


def exit_maker(c: Coin, x0: int, qty: float, usd_per_qty: float):
    """Sell `qty` from the exit decision at bar x0: a limit at the close, re-placed every 15 minutes
    at the current close, the rest sold at the close at taker cost 24 hours after x0.

    Returns lists (bar, qty, price, is_maker) and the number of exit orders placed."""
    R = max(1, -(-EXIT_REPLACE_MIN // c.bar_min))
    F = FALLBACK_H * 60 // c.bar_min
    out = []
    left = qty
    x = x0
    orders = 0
    while left > 1e-12:
        if x >= c.last or x >= c.n - 1:          # the coin's data ends: sold at its last close
            xb = min(c.last, c.n - 1)
            out.append((xb, left, float(c.px[xb]), False))
            return out, orders
        if x >= x0 + F:
            out.append((x, left, float(c.px[x]), False))
            return out, orders
        L = float(c.px[x])
        nbars = min(R, x0 + F - x)
        orders += 1
        bars, inc = _sell_fill(c, L, x + 1, nbars, left * L * usd_per_qty)
        got = 0.0
        for bb, s in zip(bars, inc):
            q = left * s
            out.append((int(bb), q, L, True))
            got += q
        left -= got
        x += nbars
    return out, orders


def pnl_by_day(c: Coin, chunks: list[tuple[int, float, float]]) -> tuple[int, np.ndarray]:
    """Mark-to-market P&L per UTC day of signed (bar, qty, price) chunks (buys +, sells -)."""
    bars = np.array([k[0] for k in chunks], dtype=np.int64)
    q = np.array([k[1] for k in chunks])
    p = np.array([k[2] for k in chunks])
    o = np.argsort(bars, kind="stable")
    bars, q, p = bars[o], q[o], p[o]
    bpd = c.bpd
    d0, d1 = int(bars[0] // bpd), int(bars[-1] // bpd)
    ends = (np.arange(d0, d1 + 1) + 1) * bpd - 1
    k = np.searchsorted(bars, ends, side="right")
    Q = np.r_[0.0, np.cumsum(q)][k]
    C = np.r_[0.0, np.cumsum(q * p)][k]
    P = c.px[np.minimum(ends, c.n - 1)]
    V = np.where(np.abs(Q) > 1e-12, Q * np.nan_to_num(P) - C, -C)
    return d0, np.diff(np.r_[0.0, V])


def by_day(c: Coin, d0: int, L: int, bars: list[int], vals: list[float]) -> np.ndarray:
    out = np.zeros(L)
    for b, v in zip(bars, vals):
        out[b // c.bpd - d0] += v
    return out


def simulate_coin(c: Coin, v: Variant, ctx: Ctx, lag: int = 0, taker: bool = False,
                  from_day: int = 0) -> list[Trade]:
    """All orders one variant places in one coin, in time order (the coin is flat between trades)."""
    f = features(c)
    b, mult, W = candidates(c, v, ctx)
    if not len(b):
        return []
    d = v.d
    # eligibility and the twin's set at the decision (from days that have closed)
    dd = day_of_decision(c, b)
    ok = (dd < N_DAYS) & (dd >= from_day) & (b >= c.first) & (b + lag < c.last)
    ddc = np.clip(dd, 0, N_DAYS - 1)
    ok &= f["elig"][ddc]
    if ctx.allowed_d is not None:
        al = ctx.allowed_d.get(c.name)
        ok &= al[np.clip(ddc - 1, 0, N_DAYS - 1)] if al is not None else False
    ok &= c.traded[np.clip(b, 0, c.n - 1)]                    # a bar printed at the decision
    ok &= np.isfinite(mult)
    b, mult = b[ok], mult[ok]
    if v.family == "D":
        starts, ends = d_windows(c, v, ctx)
        end_of = dict(zip(starts.tolist(), ends.tolist()))
    bph4 = 4 * c.bph
    if v.family == "B":
        # the first 4h close at or after k where the trend (or the BTC gate) is off
        on = (f["ema_on"] if d["rule"] == "ema" else f["don_on"]).copy()
        K = len(on)
        if d["gate"]:
            on &= gate_at(ctx, c, (np.arange(K) + 1) * bph4 - 1)
        nxt_off = np.minimum.accumulate(np.where(~on, np.arange(K), K)[::-1])[::-1]
    sig_b = sigma_at(c, f, b)
    out: list[Trade] = []
    free = 0
    for t, m, sg in zip(b.tolist(), mult.tolist(), sig_b.tolist()):
        if t < free:
            continue
        tl = t + lag
        if tl >= c.n - 2:
            break
        px0 = float(c.px[tl])
        if not np.isfinite(px0) or px0 <= 0:
            continue
        tgt = target_of(sg)
        if tgt <= 0:
            continue
        dday = int(day_of_decision(c, tl))
        rank_key = float(np.nan_to_num(f["adv"][min(dday, N_DAYS - 1)]))
        usd = tgt * BOOK_USD
        if taker:
            fills_b, fills_s = np.array([tl]), np.array([1.0])
            L = px0
        else:
            L = px0 * m
            fills_b, fills_s = _buy_fill(c, L, tl + 1, W, usd)
        win_end = tl + W if not taker else tl
        share = float(fills_s.sum())
        tr = Trade(c.name, tl, dday, rank_key, tgt, win_end, win_end, share)
        tr.stats = {"orders": 1, "exit_orders": 0, "limit": L}
        if share <= 1e-12:
            out.append(tr)
            free = win_end + 1 - lag
            continue
        fb0 = int(fills_b[0])
        # exit decision bar
        if v.family in "AC":
            x0 = fb0 + d["H"] * c.bph
        elif v.family == "D":
            x0 = end_of.get(t, t + c.bpd) + lag
        else:
            k0 = (fb0 + 1) // bph4               # the first 4h close after the fill's bar
            k_off = int(nxt_off[k0]) if k0 < K else K
            x0 = (k_off + 1) * bph4 - 1 + lag if k_off < K else c.n - 1
        x0 = min(x0, c.n - 1)
        qty = share / L                          # coins per dollar of order
        if taker:
            ex = [(x0 if x0 <= c.last else c.last, qty, float(c.px[min(x0, c.last)]), False)]
            n_exit = 1
        else:
            ex, n_exit = exit_maker(c, x0, qty, BOOK_USD * tgt)
        buys = [(int(bb), s / L, L) for bb, s in zip(fills_b, fills_s)]
        sells = [(bb, -q, p) for bb, q, p, _ in ex]
        d0, g = pnl_by_day(c, buys + sells)
        Ld = len(g)
        if taker:
            maker = np.zeros(Ld)
            fb = by_day(c, d0, Ld, [bb for bb, _, _ in buys] + [bb for bb, _, _, _ in ex],
                        [q * p for _, q, p in buys] + [q * p for _, q, p, _ in ex])
        else:
            maker = by_day(c, d0, Ld, [bb for bb, _, _ in buys] + [bb for bb, _, _, mk in ex if mk],
                           [q * p for _, q, p in buys] + [q * p for _, q, p, mk in ex if mk])
            fb = by_day(c, d0, Ld, [bb for bb, _, _, mk in ex if not mk], [q * p for _, q, p, mk in ex if not mk])
        done = max(bb for bb, _, _, _ in ex)
        tr.done, tr.d0, tr.gross, tr.maker, tr.fb = int(done), d0, g, maker, fb
        buy_usd = share
        sell_usd = sum(q * p for _, q, p, _ in ex)
        mk_q = sum(q for _, q, _, mk in ex if mk)
        tr.stats.update({
            "exit_orders": n_exit, "hold_h": (done - fb0) * c.bar_min / 60,
            "gross_bps": (sell_usd / buy_usd - 1) * 1e4,
            "maker_exit_share": mk_q / qty, "fallback": mk_q < qty - 1e-12,
            "maker_per_filled": float(maker.sum()) / buy_usd, "fb_per_filled": float(fb.sum()) / buy_usd,
        })
        out.append(tr)
        free = max(done + 1, win_end + 1) - lag
    return out


# ---------------------------------------------------------------------------
# Pass 2: the book
# ---------------------------------------------------------------------------

# Cost scenarios as (cost per maker dollar, cost per fallback/taker dollar).
SCEN_MAKER = {"gross": (0.0, 0.0), "base": (MAKER_FEE + HAIRCUT, TAKER), "haircut 0": (MAKER_FEE, TAKER),
              "haircut 10": (MAKER_FEE + 10e-4, TAKER)}
SCEN_TAKER = {"taker": (0.0, TAKER), "taker gross": (0.0, 0.0)}


@dataclass
class Book:
    label: str
    rets: dict            # scenario -> (N_DAYS,) daily return
    taken: list           # the trades the book took
    skipped: int


def run_book(trades: list[Trade], scen: dict, label: str = "") -> Book:
    """Orders in time order (ties: larger 28-day volume first), skipped above 100 % open targets."""
    trades = sorted(trades, key=lambda t: (t.t_dec, -t.rank_key))
    win_heap: list = []     # (win_end, target, kept)
    done_heap: list = []    # (done, kept)
    cur = 0.0
    taken, skipped = [], 0
    for t in trades:
        while win_heap and win_heap[0][0] <= t.t_dec:
            _, tg, kept = heapq.heappop(win_heap)
            cur -= tg - kept
        while done_heap and done_heap[0][0] <= t.t_dec:
            _, kept = heapq.heappop(done_heap)
            cur -= kept
        if cur + t.target > 1.0 + 1e-9:
            skipped += 1
            continue
        cur += t.target
        kept = t.target * t.share
        heapq.heappush(win_heap, (t.win_end, t.target, kept))
        heapq.heappush(done_heap, (max(t.done, t.win_end), kept))
        taken.append(t)
    names = list(scen)
    a = np.array([scen[k][0] for k in names])
    bcost = np.array([scen[k][1] for k in names])
    S = len(names)
    # group the P&L by decision day; equity day by day
    by_dec: dict[int, list[Trade]] = {}
    for t in taken:
        if t.gross is None:
            continue
        by_dec.setdefault(min(t.dec_day, N_DAYS - 1), []).append(t)
    dollar = np.zeros((S, N_DAYS + 400))
    E = np.zeros((S, N_DAYS + 1))
    E[:, 0] = BOOK_USD
    for dd in range(N_DAYS):
        for t in by_dec.get(dd, ()):
            unit = t.gross[None, :] - a[:, None] * t.maker[None, :] - bcost[:, None] * t.fb[None, :]
            d0 = t.d0
            if d0 < dd:      # a taker entry at the close that ends the day before: book it on the live day
                off = dd - d0
                if unit.shape[1] <= off:
                    unit = unit.sum(1, keepdims=True)
                else:
                    unit = np.concatenate([unit[:, :off].sum(1, keepdims=True) + unit[:, off:off + 1],
                                           unit[:, off + 1:]], axis=1)
                d0 = dd
            L = unit.shape[1]
            dollar[:, d0:d0 + L] += t.target * E[:, dd][:, None] * unit
        E[:, dd + 1] = np.maximum(E[:, dd] + dollar[:, dd], 1e-6)
    rets = {k: dollar[i, :N_DAYS] / E[i, :N_DAYS] for i, k in enumerate(names)}
    return Book(label, rets, taken, skipped)


# ---------------------------------------------------------------------------
# Measuring
# ---------------------------------------------------------------------------

def day_masks() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    d = np.arange(N_DAYS)
    yr = np.array([(T0.toordinal() + i) for i in d])
    years = np.array([date.fromordinal(int(o)).year for o in yr])
    return (d >= IS_START_D) & (d < SPLIT_D), d >= SPLIT_D, years


def sharpe(x: np.ndarray) -> float:
    return fc.perf(x)["sharpe"]


def describe(label: str, fam: str, mk: Book, tk: Book, bar_min: int) -> dict:
    ins, oos, years = day_masks()
    row: dict = {"variant": label, "family": fam}
    row["is_base"] = sharpe(mk.rets["base"][ins])
    for k, x in (("gross", mk.rets["gross"]), ("base", mk.rets["base"]), ("taker", tk.rets["taker"]),
                 ("haircut 0", mk.rets["haircut 0"]), ("haircut 10", mk.rets["haircut 10"])):
        row[f"oos_{k}"] = sharpe(x[oos])
    po = fc.perf(mk.rets["base"][oos])
    row["cagr_base"], row["dd_base"] = po["cagr"], po["max_dd"]
    pt = fc.perf(tk.rets["taker"][oos])
    row["cagr_taker"], row["dd_taker"] = pt["cagr"], pt["max_dd"]
    for y in YEARS_OOS:
        row[f"y{y}"] = sharpe(mk.rets["base"][oos & (years == y)])
    row["years_pos"] = int(sum(row[f"y{y}"] > 0 for y in YEARS_OOS))
    n_oos = int(oos.sum())

    def in_oos(t: Trade) -> bool:
        return t.dec_day >= SPLIT_D

    tr = [t for t in mk.taken if in_oos(t)]
    rt = [t for t in tr if t.share > 1e-12]
    row["orders_day"] = sum(t.stats["orders"] + t.stats["exit_orders"] for t in tr) / n_oos
    row["entries_day"] = len(tr) / n_oos
    row["rt_day"] = len(rt) / n_oos
    row["fill_rate_orders"] = len(rt) / len(tr) if tr else float("nan")
    row["fill_rate_qty"] = float(np.mean([t.share for t in tr])) if tr else float("nan")
    if rt:
        w = np.array([t.share for t in rt])
        g = np.array([t.stats["gross_bps"] for t in rt])
        mpf = np.array([t.stats["maker_per_filled"] for t in rt])
        fpf = np.array([t.stats["fb_per_filled"] for t in rt])
        net = g - (MAKER_FEE + HAIRCUT) * 1e4 * mpf - TAKER * 1e4 * fpf
        row["maker_exit_share"] = float(np.average([t.stats["maker_exit_share"] for t in rt], weights=w))
        row["fallback_share"] = float(np.mean([t.stats["fallback"] for t in rt]))
        row["hold_h"] = float(np.mean([t.stats["hold_h"] for t in rt]))
        row["gross_bps_rt"] = float(np.average(g, weights=w))
        row["net_bps_rt"] = float(np.average(net, weights=w))
        M, Fb = float(np.average(mpf, weights=w)), float(np.average(fpf, weights=w))
        # the maker fee a side at which the average round trip nets zero
        row["fee_needed_bps"] = (row["gross_bps_rt"] - HAIRCUT * 1e4 * M - TAKER * 1e4 * Fb) / M if M > 0 else float("nan")
    else:
        for k in ("maker_exit_share", "fallback_share", "hold_h", "gross_bps_rt", "net_bps_rt", "fee_needed_bps"):
            row[k] = float("nan")
    tko = [t for t in tk.taken if in_oos(t) and t.share > 0]
    row["taker_rt_day"] = len(tko) / n_oos
    row["taker_gross_bps_rt"] = float(np.mean([t.stats["gross_bps"] for t in tko])) if tko else float("nan")
    row["skipped"] = mk.skipped
    return row


def trial_stats(x: np.ndarray) -> dict:
    from scipy import stats
    sd = x.std()
    return {"sr_daily": float(x.mean() / sd) if sd > 0 else 0.0,
            "skew": float(stats.skew(x)) if sd > 0 else 0.0,
            "kurt": float(stats.kurtosis(x, fisher=False)) if sd > 0 else 3.0, "n": len(x)}


def prior_var() -> float:
    from scipy import stats
    g = 0.5772156649
    z = (1 - g) * stats.norm.ppf(1 - 1 / PRIOR_TRIALS) + g * stats.norm.ppf(1 - 1 / (PRIOR_TRIALS * math.e))
    return (PRIOR_SR0 / math.sqrt(365) / z) ** 2


def factory_sharpes() -> np.ndarray:
    """In-sample Sharpes of the factory's ledger (the committed seed, plus the live ledger if any)."""
    from ..factory.ledger import read_jsonl, seed_dir, ledger_path
    rows = {r["key"]: r for r in read_jsonl(seed_dir() / "ledger.jsonl")}
    try:
        rows.update({r["key"]: r for r in read_jsonl(ledger_path())})
    except Exception:
        pass
    x = [r["is_sharpe"] for r in rows.values() if r.get("is_sharpe") is not None and math.isfinite(r["is_sharpe"])]
    return np.array(x)


def pool(mine: list[float]) -> dict:
    """The deflation pool: prior hand trials, the parallel hand trials, the factory, this study."""
    v1, n1 = prior_var(), PRIOR_TRIALS + PARALLEL_HAND
    fx = np.clip(factory_sharpes(), -fc.SR_CLIP, fc.SR_CLIP) / math.sqrt(365)
    n2, v2 = len(fx), float(np.var(fx)) if len(fx) > 1 else 0.0
    x = np.clip(np.array(mine), -fc.SR_CLIP, fc.SR_CLIP) / math.sqrt(365)
    n3, v3 = len(x), float(np.var(x))
    n = n1 + n2 + n3
    v = (n1 * v1 + n2 * v2 + n3 * v3) / n
    nr = PRIOR_TRIALS + n3
    vr = (PRIOR_TRIALS * v1 + n3 * v3) / nr
    return {"prior_trials": n1, "factory_trials": n2, "mine": n3, "n_total": n, "var": v,
            "sr0_annual": fc._sr0(v, n) * math.sqrt(365), "n_registered": nr, "var_registered": vr,
            "sr0_registered": fc._sr0(vr, nr) * math.sqrt(365), "factory_var": v2, "mine_var": v3}


def deflated(x: np.ndarray, n: int, var: float) -> float:
    from ..metrics import deflated_sharpe
    s = trial_stats(x)
    if 1 - s["skew"] * s["sr_daily"] + (s["kurt"] - 1) / 4 * s["sr_daily"] ** 2 <= 0:
        return 0.0
    return deflated_sharpe(s["sr_daily"], s["n"], n, var, s["skew"], s["kurt"])


def boot_band(x: np.ndarray, rng: np.random.Generator, draws: int = 4000, block: int = 20) -> tuple[float, float]:
    """5 % and 95 % of the annual Sharpe over stationary-bootstrap resamples (as tsmom_tranches)."""
    n = len(x)
    idx = np.empty((draws, n), dtype=np.int64)
    idx[:, 0] = rng.integers(0, n, draws)
    jump = rng.random((draws, n)) < 1 / block
    fresh = rng.integers(0, n, (draws, n))
    for i in range(1, n):
        idx[:, i] = np.where(jump[:, i], fresh[:, i], (idx[:, i - 1] + 1) % n)
    s = x[idx]
    sd = s.std(1)
    sr = np.where(sd > 0, s.mean(1) / np.where(sd > 0, sd, 1) * np.sqrt(365), 0.0)
    return float(np.percentile(sr, 5)), float(np.percentile(sr, 95))


# ---------------------------------------------------------------------------
# Context: BTC gate, the twin, family D's hours
# ---------------------------------------------------------------------------

def btc_gate(btc: Coin) -> np.ndarray:
    """(N_DAYS,) BTC daily close above its 200-day average, known at that day's close."""
    bpd = btc.bpd
    dc = btc.px[bpd - 1::bpd][:N_DAYS]
    ma = np.full(N_DAYS, np.nan)
    cs = np.r_[0.0, np.cumsum(np.nan_to_num(dc))]
    ok = np.r_[0, np.cumsum(np.isfinite(dc))]
    for i in range(199, N_DAYS):
        if ok[i + 1] - ok[i - 199] == 200:
            ma[i] = (cs[i + 1] - cs[i - 199]) / 200
    with np.errstate(invalid="ignore"):
        return np.nan_to_num(dc > ma, nan=0.0).astype(bool)


def btc_daily(btc: Coin) -> np.ndarray:
    dc = btc.px[btc.bpd - 1::btc.bpd][:N_DAYS]
    r = np.zeros(N_DAYS)
    with np.errstate(invalid="ignore", divide="ignore"):
        r[1:] = np.nan_to_num(dc[1:] / dc[:-1] - 1)
    return r


def best_hours(coins: list[Coin]) -> list[int]:
    """UTC hours ranked by the mean hourly return of the equal-weight basket of eligible coins, in sample."""
    tot, cnt = np.zeros(24), np.zeros(24)
    s_h, e_h = IS_START_D * 24, SPLIT_D * 24
    hod = np.arange(e_h - s_h) % 24
    num = np.zeros(e_h - s_h)
    den = np.zeros(e_h - s_h)
    for c in coins:
        f = features(c)
        r = f["hr"][s_h:e_h]
        el = np.repeat(f["elig"], 24)[s_h:e_h]
        m = np.isfinite(r) & el
        num += np.where(m, r, 0.0)
        den += m
    ew = np.where(den > 0, num / np.maximum(den, 1), np.nan)
    for h in range(24):
        x = ew[(hod == h) & np.isfinite(ew)]
        tot[h], cnt[h] = x.sum(), len(x)
    mean = tot / np.maximum(cnt, 1)
    return [int(h) for h in np.argsort(-mean, kind="stable")]


def twin_sets() -> tuple[dict, list[str]]:
    """Each day the 33 eligible USDT coins with the highest 28-day quote volume (sweep panel), stablecoins,
    fiat and leveraged tokens left out. Returns name -> (N_DAYS,) bool and the names ever in it from 2024."""
    P = fc.load_panel()
    keep = np.array([not excluded_symbol(n) for n in P.names])
    ok = P.eligible & keep[None, :]
    score = np.where(ok, P.adv28, -np.inf)
    rank = np.argsort(np.argsort(-score, axis=1), axis=1)
    top = ok & (rank < TOP_TWIN)
    out, names = {}, []
    off = (int(P.days[0]) - T0_US) // DAY_US
    split_p = SPLIT_D - off
    for j, n in enumerate(P.names):
        if not top[max(split_p - 1, 0):, j].any():
            continue
        a = np.zeros(N_DAYS, dtype=bool)
        lo, hi = max(0, off), min(N_DAYS, off + P.T)
        a[lo:hi] = top[lo - off:hi - off, j]
        out[n], names = a, names + [n]
    return out, names


def twin_symbols() -> list[str]:
    """Binance symbols the twin ever holds from 2024 (for `vision twin`)."""
    _, names = twin_sets()
    return sorted({n.split("~")[0] for n in names})


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

@dataclass
class Result:
    v: Variant
    mk: Book
    tk: Book
    row: dict


def run_variant(coins: list[Coin], v: Variant, ctx: Ctx, lag: int = 0, from_day: int = 0,
                label_suffix: str = "") -> Result:
    bar_min = coins[0].bar_min
    tm, tt = [], []
    for c in coins:
        tm += simulate_coin(c, v, ctx, lag=lag, from_day=from_day)
        tt += simulate_coin(c, v, ctx, lag=lag, taker=True, from_day=from_day)
    mk = run_book(tm, SCEN_MAKER, v.label + label_suffix)
    tk = run_book(tt, SCEN_TAKER, v.label + label_suffix)
    return Result(v, mk, tk, describe(v.label + label_suffix, v.family, mk, tk, bar_min))


def load_alpaca(bar_min: int, only: tuple | None = None) -> list[Coin]:
    out = []
    for k in SYMBOLS:
        if only is not None and k not in only:
            continue
        c = load_coin(k, bar_min)
        if c is None:
            print(f"  {k}: no bars", flush=True)
            continue
        out.append(c)
    return out


def load_twin(names: list[str], bar_min: int) -> list[Coin]:
    out = []
    for n in names:
        df = raw_bars(n, bar_min)
        c = to_coin(n, df, bar_min)
        if c is not None:
            out.append(c)
    return out


def walk_forward(results: list[Result]) -> tuple[np.ndarray, list[str]]:
    """Each quarter from 2024 trades the variant with the best base Sharpe on all data before it
    (from 2020-08). Switching between variants is not charged."""
    _, oos, years = day_masks()
    d = np.arange(N_DAYS)
    month = np.array([date.fromordinal(T0.toordinal() + int(i)).month for i in d])
    q = (month - 1) // 3
    out = np.zeros(N_DAYS)
    picks = []
    for y in YEARS_OOS:
        for k in range(4):
            m = (years == y) & (q == k)
            if not m.any():
                continue
            first = int(np.flatnonzero(m)[0])
            hist = (d >= IS_START_D) & (d < first)
            best = max(results, key=lambda r: sharpe(r.mk.rets["base"][hist]))
            out[m] = best.mk.rets["base"][m]
            picks.append(f"{y}Q{k + 1}: {best.row['variant']}")
    return out, picks


def main_run(bar_min: int, resolution: bool) -> None:
    t_start = time.time()
    tag = "1h" if bar_min == 60 else "5m"
    print(f"loading the 33 coins at {tag}", flush=True)
    coins = load_alpaca(bar_min)
    btc = next(c for c in coins if c.name == "BTC")
    gate = btc_gate(btc)
    hours = best_hours(coins)
    ctx = Ctx(gate_d=gate, hours=tuple(hours))
    _, oos, years = day_masks()
    res: dict = {"bars": tag, "data_end": str(DATA_END), "coins": [c.name for c in coins], "hours_ranked": hours,
                 "coin_first_bar": {c.name: str(date.fromordinal(T0.toordinal() + c.first * bar_min // 1440))
                                    for c in coins}}
    V = variants()
    results: list[Result] = []
    for i, v in enumerate(V):
        r = run_variant(coins, v, ctx)
        results.append(r)
        print(f"[{i + 1}/{len(V)}] {r.row['variant']}: IS {r.row['is_base']:.2f} OOS base {r.row['oos_base']:.2f} "
              f"taker {r.row['oos_taker']:.2f} rt/day {r.row['rt_day']:.2f} ({time.time() - t_start:.0f}s)",
              flush=True)
    trials: list[tuple[str, np.ndarray]] = [(r.row["variant"], r.mk.rets["base"][oos]) for r in results]
    # Picks per family, best in-sample Sharpe in the base case.
    picks = []
    for fam in "ABCD":
        cand = [r for r in results if r.v.family == fam]
        picks.append(max(cand, key=lambda r: r.row["is_base"]))
    print("twin", flush=True)
    tw_sets, tw_names = twin_sets()
    tw_coins = load_twin(tw_names, bar_min)
    tw_ctx = Ctx(gate_d=gate, allowed_d=tw_sets, hours=tuple(hours))
    judged = []
    rng = np.random.default_rng(20261015)
    checks = []
    for pk in picks:
        tw = run_variant(tw_coins, pk.v, tw_ctx, from_day=SPLIT_D - 1, label_suffix=" · survivorship-free twin")
        tw.row["is_base"] = float("nan")             # the twin is judged out of sample only
        late = run_variant(coins, pk.v, ctx, lag=LATENCY_BARS, label_suffix=" · one bar late")
        trials += [(tw.row["variant"], tw.mk.rets["base"][oos]), (late.row["variant"], late.mk.rets["base"][oos])]
        checks += [tw, late]
        judged.append((pk, tw, late))
    wf, wf_picks = walk_forward(results)
    trials.append(("walk-forward pick by quarter", wf[oos]))
    assert len(trials) == TRIALS_HERE, len(trials)
    pl_ = pool([trial_stats(x)["sr_daily"] * math.sqrt(365) for _, x in trials])
    res["pool"] = pl_
    btc_r = btc_daily(btc)
    pb = fc.perf(btc_r[oos])
    res["btc"] = {"oos_sharpe": pb["sharpe"], "cagr": pb["cagr"], "dd": pb["max_dd"],
                  **{f"y{y}": sharpe(btc_r[oos & (years == y)]) for y in YEARS_OOS}}
    out_j = []
    for pk, tw, late in judged:
        row = dict(pk.row)
        x = pk.mk.rets["base"][oos]
        p = deflated(x, pl_["n_total"], pl_["var"])
        p_reg = deflated(x, pl_["n_registered"], pl_["var_registered"])
        lo, hi = boot_band(x, rng)
        why = []
        if row["oos_base"] <= 0:
            why.append(f"Sharpe {row['oos_base']:.2f} <= 0")
        if not row["net_bps_rt"] > 0:
            why.append(f"net {row['net_bps_rt']:.0f} bps per round trip")
        if p <= 0.95:
            why.append(f"deflated p {p:.2f} <= 0.95")
        if tw.row["oos_base"] <= 0:
            why.append(f"twin {tw.row['oos_base']:.2f}")
        if late.row["oos_base"] <= 0:
            why.append(f"one bar late {late.row['oos_base']:.2f}")
        if row["years_pos"] < 2:
            why.append(f"positive in {row['years_pos']} of 3 years")
        row.update({"deflated_p": p, "deflated_p_430": p_reg, "boot_p05": lo, "boot_p95": hi,
                    "twin_oos": tw.row["oos_base"], "twin_net_bps": tw.row["net_bps_rt"],
                    "late_oos": late.row["oos_base"], "late_net_bps": late.row["net_bps_rt"],
                    "passes": not why, "verdict": "passes" if not why else "fails: " + "; ".join(why)})
        out_j.append(row)
    res["judged"] = out_j
    res["grid"] = [r.row for r in results]
    res["checks"] = [r.row for r in checks]
    res["walk_forward"] = {"oos": fc.perf(wf[oos]), "picks": wf_picks,
                           **{f"y{y}": sharpe(wf[oos & (years == y)]) for y in YEARS_OOS},
                           "deflated_p": deflated(wf[oos], pl_["n_total"], pl_["var"])}
    res["trials"] = [n for n, _ in trials]
    res["holds"] = hold_buckets(res["grid"])
    if resolution:
        res["resolution"] = resolution_check(V)
    res["runtime_s"] = time.time() - t_start
    write(res)


def hold_buckets(rows: list[dict]) -> list[dict]:
    out = []
    for lo, hi in ((0, 6), (6, 24), (24, 48), (48, 10_000)):
        b = [r for r in rows if np.isfinite(r["hold_h"]) and lo <= r["hold_h"] < hi]
        if not b:
            continue
        g = np.array([r["gross_bps_rt"] for r in b])
        out.append({"hold": f"{lo} to {hi} h" if hi < 10_000 else f"{lo} h and more", "variants": len(b),
                    "median_gross_bps": float(np.median(g)), "best_gross_bps": float(g.max()),
                    "median_net_bps": float(np.median([r["net_bps_rt"] for r in b])),
                    "median_fee_needed": float(np.median([r["fee_needed_bps"] for r in b])),
                    "median_fill_rate": float(np.median([r["fill_rate_orders"] for r in b])),
                    "positive_base": int(sum(r["oos_base"] > 0 for r in b))})
    return out


def resolution_check(V: list[Variant]) -> list[dict]:
    """All 44 variants on the 15 coins with 1-minute history, at 5-minute bars and at 1h bars."""
    out = []
    sets = {}
    for bm in (60, 5):
        print(f"resolution check: loading the 15 at {bm} min", flush=True)
        coins = load_alpaca(bm, only=ONE_MINUTE)
        btc = next(c for c in coins if c.name == "BTC")
        ctx = Ctx(gate_d=btc_gate(btc), hours=tuple(best_hours(coins)))
        sets[bm] = (coins, ctx)
    for i, v in enumerate(V):
        rows = {}
        for bm, (coins, ctx) in sets.items():
            rows[bm] = run_variant(coins, v, ctx).row
        out.append({"variant": v.label, "oos_base_1h": rows[60]["oos_base"], "oos_base_5m": rows[5]["oos_base"],
                    "net_bps_1h": rows[60]["net_bps_rt"], "net_bps_5m": rows[5]["net_bps_rt"],
                    "fill_rate_1h": rows[60]["fill_rate_orders"], "fill_rate_5m": rows[5]["fill_rate_orders"],
                    "rt_day_1h": rows[60]["rt_day"], "rt_day_5m": rows[5]["rt_day"],
                    "oos_taker_1h": rows[60]["oos_taker"], "oos_taker_5m": rows[5]["oos_taker"]})
        print(f"  [{i + 1}/{len(V)}] {v.label}: 1h {rows[60]['oos_base']:.2f} 5m {rows[5]['oos_base']:.2f}",
              flush=True)
    return out


# ---------------------------------------------------------------------------
# Check of the fill model against Binance aggTrades (server; downloads)
# ---------------------------------------------------------------------------

CHECK_COINS = ("BTC", "DOGE", "PEPE", "WIF")


def agg_trades(symbol: str, day: date) -> pl.DataFrame:
    """One day of Binance spot aggTrades (price, qty, time in us), cached under hist/binance_spot/aggtrades."""
    from .vision import BUCKET, _get
    import io
    import zipfile
    d = labdata.ROOT / "hist" / "binance_spot" / "aggtrades" / f"symbol={symbol}"
    f = d / f"{day:%Y-%m-%d}.parquet"
    if f.exists():
        return pl.read_parquet(f)
    raw = _get(f"{BUCKET}/data/spot/daily/aggTrades/{symbol}/{symbol}-aggTrades-{day:%Y-%m-%d}.zip")
    if raw is None:
        return pl.DataFrame()
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        body = z.read(z.namelist()[0])
    df = pl.read_csv(io.BytesIO(body), has_header=False, infer_schema_length=0)
    ts = df[df.columns[5]].cast(pl.Int64).to_numpy()
    ts = np.where(ts < 10 ** 14, ts * 1000, ts)
    out = pl.DataFrame({"ts_us": ts, "price": df[df.columns[1]].cast(pl.Float64),
                        "qty": df[df.columns[2]].cast(pl.Float64)})
    d.mkdir(parents=True, exist_ok=True)
    out.write_parquet(f)
    return out


def check_fills(bar_min: int = 5) -> None:
    """Families A and C entry orders on the four coins, decided on the two days of each quarter of
    2024 and 2025 with the most such orders: the bar rule against trades (filled when trades of at
    least the order's size print below the limit inside the window)."""
    coins = load_alpaca(bar_min, only=CHECK_COINS + ("BTC",))
    btc = next(c for c in coins if c.name == "BTC")
    ctx = Ctx(gate_d=btc_gate(btc))
    orders = []
    for c in coins:
        if c.name not in CHECK_COINS:
            continue
        for v in variants():
            if v.family not in "AC":
                continue
            for t in simulate_coin(c, v, ctx):
                day = date.fromordinal(T0.toordinal() + int(day_of_decision(c, t.t_dec)))
                if 2024 <= day.year <= 2025:
                    orders.append((c, v, t, day))
    by_q: dict = {}
    for o in orders:
        by_q.setdefault((o[3].year, (o[3].month - 1) // 3), {}).setdefault(o[3], []).append(o)
    sample = []
    for _, days in sorted(by_q.items()):
        for day in sorted(days, key=lambda d: -len(days[d]))[:2]:
            sample += days[day]
    rows = []
    for c, v, t, day in sample:
        sym = SYMBOLS[c.name][-1]
        L = t.stats["limit"]
        t_open = T0_US + (t.t_dec + 1) * c.bar_min * 60_000_000
        t_close = t_open + 60 * 60_000_000
        tr = pl.concat([agg_trades(sym, day), agg_trades(sym, date.fromordinal(day.toordinal() + 1))],
                       how="vertical_relaxed")
        if tr.is_empty():
            continue
        w = tr.filter((pl.col("ts_us") >= t_open) & (pl.col("ts_us") < t_close) & (pl.col("price") < L))
        need = t.target * BOOK_USD / L
        trade_fill = float(w["qty"].sum()) >= need
        bar_fill = t.share > 0
        rows.append({"coin": c.name, "variant": v.label, "day": str(day), "bar_fill": bar_fill,
                     "trade_fill": trade_fill})
    n = len(rows)
    agree = sum(r["bar_fill"] == r["trade_fill"] for r in rows)
    bar_only = sum(r["bar_fill"] and not r["trade_fill"] for r in rows)
    trade_only = sum(r["trade_fill"] and not r["bar_fill"] for r in rows)
    md = (f"\n## Check of the fill model against aggTrades (generated {datetime.now(timezone.utc):%Y-%m-%d})\n\n"
          f"{n} family A and C entry orders on {', '.join(CHECK_COINS)} ({bar_min}-minute bars). Bars and trades "
          f"agree on {agree} ({agree / max(n, 1) * 100:.0f} %); the bars fill where the trades do not in "
          f"{bar_only}, the trades fill where the bars do not in {trade_only}.\n")
    path = fc.RESULTS_DIR / f"{NAME}{'' if bar_min == 60 else '_5m'}.md"
    prev = path.read_text(encoding="utf-8") if path.exists() else ""
    path.write_text(prev.split("\n## Check of the fill model against aggTrades")[0] + md, encoding="utf-8")
    d = fc.OUT / "reports"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{NAME}_fills.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
    print(md)


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def pct(v) -> str:
    return "n/a" if v is None or not np.isfinite(v) else f"{v * 100:.0f} %"


def write(res: dict) -> None:
    tag = res["bars"]
    path = fc.RESULTS_DIR / (f"{NAME}.md" if tag == "1h" else f"{NAME}_5m.md")
    if tag == "1h":
        head = (fc.RESULTS_DIR / f"{NAME}.md").read_text(encoding="utf-8").split(MARKER)[0] + MARKER + "\n"
    else:
        head = ("# Fast trades with maker orders only, on the 33 Alpaca coins (W15), 5-minute bars\n\n"
                "`python -m lab.experiments.fast_maker --bars 5m`\n\nThe registered run. The pre-registration, "
                "its addendum and the 1h run are in `results/fast_maker.md`.\n\n")
    pool_, j, grid = res["pool"], res["judged"], res["grid"]
    passed = [r for r in j if r["passes"]]
    btc = res["btc"]
    wf = res["walk_forward"]
    pos_base = sum(r["oos_base"] > 0 for r in grid)
    pos_net = sum(r["net_bps_rt"] > 0 for r in grid if np.isfinite(r["net_bps_rt"]))
    pos_taker = sum(r["oos_taker"] > 0 for r in grid)
    pos_gross = sum(r["oos_gross"] > 0 for r in grid)
    best = max(grid, key=lambda r: r["oos_base"])
    fees = np.array([r["fee_needed_bps"] for r in grid if np.isfinite(r["fee_needed_bps"])])
    md = [head, f"\n## Results, {tag} bars (generated {datetime.now(timezone.utc):%Y-%m-%d}, data to "
                f"{res['data_end']})\n\n"]
    md.append(
        f"**Verdict: {'a pick passes, see the proposal below' if passed else 'nothing passes, no paper book'}.** "
        f"Out of sample (2024-01-01 to {res['data_end']}) {pos_base} of {len(grid)} variants have a Sharpe above 0 "
        f"in the base case (maker fills, 15 bps, 3 bps haircut), {pos_net} make money per round trip after costs, "
        f"{pos_taker} are positive with every order filled at the close at 35 bps a side and {pos_gross} before "
        f"any cost. The best base case out of sample, picked after the fact, is {best['variant']} at "
        f"{best['oos_base']:.2f}. The quarterly walk-forward pick makes {wf['oos']['sharpe']:.2f} (drawdown "
        f"{pct(wf['oos']['max_dd'])}). BTC buy and hold over the same days: Sharpe {btc['oos_sharpe']:.2f}, "
        f"{pct(btc['cagr'])} a year, drawdown {pct(btc['dd'])}. Across the grid the maker fee a side at which "
        f"the average round trip would net zero has a median of {np.median(fees):.1f} bps (best "
        f"{fees.max():.1f}); Alpaca charges 15. Deflation pool {pool_['n_total']} trials, noise bar Sharpe "
        f"{pool_['sr0_annual']:.2f} (registered pool {pool_['n_registered']}, bar {pool_['sr0_registered']:.2f}: "
        f"fewer trials, but this study's own spread of Sharpes is wide, so its bar is not lower).\n\n")
    fast = [r for r in grid if np.isfinite(r["hold_h"]) and r["hold_h"] < 48]
    slow = [r for r in grid if np.isfinite(r["hold_h"]) and r["hold_h"] >= 48]
    if fast:
        fg = np.array([r["gross_bps_rt"] for r in fast])
        ff = np.array([r["fee_needed_bps"] for r in fast])
        fb = max(fast, key=lambda r: r["oos_base"])
        md.append(
            f"**The question asked: holds under two days.** {len(fast)} variants hold under 48 hours on average "
            f"(families A and C, D's hours of day); {sum(r['oos_base'] > 0 for r in fast)} of them are positive "
            f"out of sample in the base case and {sum(r['oos_taker'] > 0 for r in fast)} at taker cost. Their "
            f"filled round trip earns a median {np.median(fg):.0f} bps before costs (best {fg.max():.0f}) against "
            f"36 bps for two resting legs; the maker fee a side at which the median one breaks even is "
            f"{np.median(ff):.1f} bps{' (below zero: it would need a rebate)' if np.median(ff) < 0 else ''}, and "
            f"{int((ff > 15).sum())} of {len(fast)} clear Alpaca's 15. Against the same rules filled at the close, "
            f"the resting fills change the gross per round trip by a median "
            f"{np.median([r['gross_bps_rt'] - r['taker_gross_bps_rt'] for r in fast]):+.0f} bps: the fee saved is "
            f"real, but a limit fills when the price comes to it, and the trades it misses are not the bad ones. "
            f"The best of them out of sample (after the fact) is {fb['variant']} at {fb['oos_base']:.2f}, "
            f"{fb['net_bps_rt']:.0f} bps net per round trip.")
        bs = [r for r in slow if r["family"] == "B"]
        if bs:
            md.append(
                f" The {len(slow)} variants that hold longer are not fast trades: family B (4h trend, pullback "
                f"entries) holds a median {np.median([r['hold_h'] for r in bs]) / 24:.0f} days and "
                f"{sum(r['oos_base'] > 0 for r in bs)} of its {len(bs)} variants are positive in the base case "
                f"(median {np.median([r['oos_base'] for r in bs]):.2f}, at taker cost "
                f"{np.median([r['oos_taker'] for r in bs]):.2f}); D's weekday and weekend windows hold 2 to 5 "
                f"days.")
        md.append("\n\n")
    md.append("### The picks against the pass rule\n\nPer family the best in-sample Sharpe in the base case. "
              "`rt_day` counts round trips across all coins per day out of sample, `fill_rate_orders` the share of "
              "entry orders with any fill, `net_bps_rt` the average round trip after the haircut, fees and fallback "
              "costs (weighted by the filled share), `fee_needed_bps` the maker fee a side at which it would be "
              "zero. `twin_oos` is the survivorship-free twin, `late_oos` the pick decided and priced one bar "
              "late. The band is a stationary bootstrap (blocks of 20 days) of the base case Sharpe.\n\n")
    md.append(fc.table(j, ["variant", "is_base", "oos_base", "oos_taker", "oos_gross", "rt_day", "fill_rate_orders",
                           "net_bps_rt", "fee_needed_bps", "dd_base", "y2024", "y2025", "y2026", "deflated_p",
                           "deflated_p_430", "boot_p05", "boot_p95", "twin_oos", "late_oos", "verdict"]))
    md.append("\n### Against BTC buy and hold (out of sample)\n\n| book | Sharpe | CAGR | max drawdown | 2024 | 2025 | "
              "2026 |\n|---|---|---|---|---|---|---|\n")
    md.append(f"| BTC buy and hold, no cost | {btc['oos_sharpe']:.2f} | {pct(btc['cagr'])} | {pct(btc['dd'])} | "
              f"{btc['y2024']:.2f} | {btc['y2025']:.2f} | {btc['y2026']:.2f} |\n")
    for r in j:
        md.append(f"| {r['variant']}, maker base | {r['oos_base']:.2f} | {pct(r['cagr_base'])} | {pct(r['dd_base'])} "
                  f"| {r['y2024']:.2f} | {r['y2025']:.2f} | {r['y2026']:.2f} |\n")
        md.append(f"| {r['variant']}, taker at the close | {r['oos_taker']:.2f} | {pct(r['cagr_taker'])} | "
                  f"{pct(r['dd_taker'])} | | | |\n")
    md.append(f"| walk-forward pick by quarter, maker base | {wf['oos']['sharpe']:.2f} | {pct(wf['oos']['cagr'])} | "
              f"{pct(wf['oos']['max_dd'])} | {wf['y2024']:.2f} | {wf['y2025']:.2f} | {wf['y2026']:.2f} |\n")
    md.append("\n### Sensitivity of the picks to the haircut (not trials)\n\n")
    md.append(fc.table(j, ["variant", "oos_haircut 0", "oos_base", "oos_haircut 10"]))
    md.append("\n### What a round trip earns, by holding time (all 44 variants, out of sample)\n\n"
              "A maker round trip costs 36 bps when both legs rest (2 x 15 fee + 2 x 3 haircut); at taker cost "
              "it is 70.\n\n")
    md.append(fc.table(res["holds"], ["hold", "variants", "median_gross_bps", "best_gross_bps", "median_net_bps",
                                      "median_fee_needed", "median_fill_rate", "positive_base"]))
    md.append("\n### Walk-forward pick by quarter\n\n" + "".join(f"- {p}\n" for p in wf["picks"]))
    cols = ["variant", "is_base", "oos_gross", "oos_base", "oos_taker", "cagr_base", "dd_base", "entries_day",
            "orders_day", "rt_day", "fill_rate_orders", "fill_rate_qty", "maker_exit_share", "fallback_share",
            "hold_h", "gross_bps_rt", "net_bps_rt", "fee_needed_bps", "taker_gross_bps_rt", "y2024", "y2025",
            "y2026", "skipped"]
    md.append("\n### All 44 variants (out of sample unless marked is_)\n\n`entries_day` entry orders and "
              "`orders_day` entry plus exit orders per day across all coins; `fill_rate_qty` the average filled "
              "share of an entry order; `maker_exit_share` the share of exit quantity sold as maker; "
              "`fallback_share` the share of round trips that needed the 24-hour taker fallback; "
              "`taker_gross_bps_rt` the same rules' round trip filled at the close; `skipped` entries (whole "
              "period) the 100 % limit refused.\n\n")
    md.append(fc.table(sorted(grid, key=lambda r: r["variant"]), cols))
    md.append("\n### Checks on the picks (twin from 2024 only)\n\n")
    md.append(fc.table(res["checks"], cols))
    if "resolution" in res:
        rs = res["resolution"]
        d_sr = np.array([r["oos_base_5m"] - r["oos_base_1h"] for r in rs])
        same_sign = sum((r["oos_base_5m"] > 0) == (r["oos_base_1h"] > 0) for r in rs)
        md.append(f"\n### Resolution check: 1h against 5-minute bars on the 15 coins with 1-minute history\n\n"
                  f"Not trials. Same code, same 15 coins, 5-minute bars built from the 1-minute history. The base "
                  f"case out-of-sample Sharpe moves by {np.median(d_sr):+.2f} at the median (5m minus 1h; range "
                  f"{d_sr.min():+.2f} to {d_sr.max():+.2f}); {same_sign} of {len(rs)} variants keep their sign; "
                  f"{sum(r['oos_base_5m'] > 0 for r in rs)} are positive at 5 minutes, "
                  f"{sum(r['oos_base_1h'] > 0 for r in rs)} at 1h.\n\n")
        md.append(fc.table(rs, ["variant", "oos_base_1h", "oos_base_5m", "net_bps_1h", "net_bps_5m",
                                "fill_rate_1h", "fill_rate_5m", "rt_day_1h", "rt_day_5m", "oos_taker_1h",
                                "oos_taker_5m"]))
    md.append(f"\n### Deflation pool\n\n{pool_['prior_trials']} hand trials with the variance backed out of the "
              f"published bar ({PRIOR_SR0} over {PRIOR_TRIALS}), the factory's {pool_['factory_trials']} with the "
              f"variance of their in-sample Sharpes, and this study's {pool_['mine']} (base case, out of sample, "
              f"clipped at +-3): bar {pool_['sr0_annual']:.2f} over {pool_['n_total']}. The registered pool "
              f"({pool_['n_registered']}: 377 plus this study) has a bar of {pool_['sr0_registered']:.2f}.\n\n"
              f"Family D's hours, ranked in sample (best first, UTC): {', '.join(map(str, res['hours_ranked']))}.\n\n"
              "Trials counted here: " + "; ".join(res["trials"]) + ".\n")
    path.write_text("".join(md), encoding="utf-8")
    d = fc.OUT / "reports"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{NAME}{'' if tag == '1h' else '_5m'}.json").write_text(json.dumps(res, indent=1, default=str),
                                                                  encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("what", nargs="?", default="run", choices=("run", "check-fills"))
    ap.add_argument("--bars", default="5m", choices=("5m", "1h"))
    ap.add_argument("--resolution", action="store_true")
    a = ap.parse_args()
    bm = 5 if a.bars == "5m" else 60
    if a.what == "check-fills":
        check_fills(bm)
    else:
        main_run(bm, a.resolution)


if __name__ == "__main__":
    main()
