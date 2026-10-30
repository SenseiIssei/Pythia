"""DT1: day trading on every liquid listed coin (no rug risk), flat by 23:55 UTC.

Pre-registered in results/daytrade_dt1_prereg.md; results in results/daytrade_dt1.md.

    PYTHIA_AGENT_OUT=<cache> python -m lab.experiments.daytrade_dt1 --fetch        # 1-minute klines, 2021-12 to 2026-06
    PYTHIA_AGENT_OUT=<cache> PYTHIA_TRIALS_REGISTRY=<registry> PYTHIA_REPORTS=<reports> \
        flock <heavy lock> python -m lab.experiments.daytrade_dt1 [--no-register] [--report]

The universe, point in time and survivorship free: every Binance USDT-M perp listed at least 180 days with a
trailing 30-day mean quote volume of 50 M USD (counts at 20 M and 100 M), no stablecoins, fiat, commodity, equity,
index or leveraged products; judged on the days Hyperliquid lists the coin (T12b's listing history, from
2023-05-12). Binance 1-minute klines from data.binance.vision. Three families of rules in the day-trading format
(entry at the open after the signal minute and one minute later, flat by 23:55 UTC, at most 5 positions, 0.25 % of
equity at risk per trade): S minute spikes (own, continuation and fade, with volume or taker confirmation, and BTC's
lead), D day patterns on HAR-PK's expected range (opening ranges, yesterday's high and low, VWAP reversion), P a
walk-forward LightGBM on the last hour's minutes. Costs: Hyperliquid taker 4.5 bps plus slippage from a minute-bar
spread proxy, Kraken Futures taker 5 bps, a maker case at 1.5 bps with fast_maker's trade-through fill model,
funding at its settlements. In sample 2022 to 2024, judged from 2025-01-01 to 2026-06-30; no minute after
2026-06-30 is downloaded or read (the lockbox). Every (rule, case) goes into R5's registry with its in-sample
Sharpe before any out-of-sample number. Nothing here changes a book, a gate, the engine or a wallet.
"""

from __future__ import annotations

import heapq
import io
import json
import math
import os
import sys
import time
import urllib.parse
import urllib.request
import warnings
import zipfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import polars as pl

from .. import data as labdata
from .. import metrics
from . import fast_maker as fm

NAME = "daytrade_dt1"
PREREG = "results/daytrade_dt1_prereg.md"
IS_FROM, IS_TO, OOS_FROM, OOS_TO, LOCKBOX = "2022-01-01", "2024-12-31", "2025-01-01", "2026-06-30", "2026-07-01"
FETCH_FROM = "2021-12"
HAR_FROM = "2020-01-01"
HL_FROM = "2023-05-12"
CACHE = Path(os.environ.get("PYTHIA_AGENT_OUT", str(labdata.ROOT / "agent-strategies"))) / "dt1"
BUCKET = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
HL_INFO = "https://api.hyperliquid.xyz/info"

MIN_LISTED = 180
VOL_N = 30
VOL_BARS = (20e6, 50e6, 100e6)
VOL_BAR = 50e6
GAP_DAYS = 30                     # a longer gap without a daily bar starts a new segment
DAY_MIN = 1440
CUT_MIN = 23 * 60 + 55            # every position out at the open of 23:55
SIG_N, SIG_MIN = 1440, 1000

N_POS = 5
RISK = 0.0025
CAP = 1.0
FEE_HL, FEE_KF, FEE_MAKER = 4.5e-4, 5.0e-4, 1.5e-4
SLIP_BASE, SLIP_CAP = 1e-4, 50e-4
TOP_N = 20
MAKER_REST = 3
HAIRCUT = fm.HAIRCUT
CASES = ("hl", "hl_late", "maker", "kf")
BOOT_DRAWS, BOOT_BLOCK, BOOT_SEED = 2000, 5.0, 7
DSR_PASS = 0.95
MIN_TRADES = 100
YEAR = 365

# Stablecoins and fiat (fast_maker's list and more), commodities, FX, indexes, equities and ETFs: never in the universe.
STABLE = fm.STABLE | {"USDC", "BUSD", "TUSD", "FDUSD", "USDP", "DAI", "USDE", "USTC", "FRAX", "USDBRL", "EURI"}
NOT_CRYPTO = {
    "PAXG", "XAUT", "XAU", "XAG", "XPT", "XPD", "COPPER", "NATGAS", "BTCDOM", "DEFI", "FOOTBALL", "BLUEBIRD",
    "KODEX200", "CSOPSAMSUNG2L", "CSOPSKHYNIX2L",
    "AAOI", "AAPL", "ACN", "ADBE", "AMAT", "AMC", "AMD", "AMZN", "ANET", "ANTHROPIC", "APLD", "APP", "ARM", "ASML",
    "ASTS", "AVGO", "AXTI", "BABA", "BITO", "BMNR", "BRKB", "BYD", "CBRS", "CIEN", "COHR", "COIN", "COST", "CRCL",
    "CRDO", "CRM", "CRWD", "CRWV", "CSCO", "CVNA", "CXMT", "DDOG", "DELL", "DIS", "DJT", "DKNG", "EBAY", "EWJ",
    "EWY", "EWZ", "FLNC", "GDX", "GEV", "GLW", "GME", "GOOGL", "HANA", "HANMI", "HIMS", "HK0625", "HK0700",
    "HK0992", "HK1810", "HOOD", "HPE", "HUT", "HYUNDAI", "IBM", "INTC", "INTW", "IONQ", "IREN", "IWM", "JPM",
    "KLAC", "KUAISHOU", "LGELECTRONICS", "LITE", "LLY", "LRCX", "MARA", "MDB", "MEITUAN", "META", "MRK", "MRNA",
    "MRVL", "MSFT", "MSTR", "MU", "NAVER", "NBIS", "NFLX", "NKE", "NOK", "NOW", "NVDA", "NVDL", "NVO", "OKLO",
    "OPENAI", "ORCL", "PANW", "PDD", "PLTR", "POPMART", "PYPL", "QCOM", "QQQ", "RDDT", "RIVN", "RKLB", "SAMSUNG",
    "SAMSUNGEM", "SHOP", "SKHYNIX", "SKHY", "SMCI", "SMH", "SNDK", "SNOW", "SOFI", "SONY", "SOXL", "SOXS", "SPCX",
    "SPY", "SQQQ", "TBT", "TEM", "TENCENT", "TMF", "TQQQ", "TSLA", "TSLL", "TSM", "TTWO", "TXN", "TZA", "UBER",
    "UNH", "UNITREE", "URNM", "UVXY", "WDC", "WMT", "XBI", "XLE", "XOM", "ZHIPU", "ZHONGJI",
}

DAY_US = 86_400_000_000
MIN_US = 60_000_000


def us(day: str) -> int:
    return int(datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp() * 1e6)


def day_str(d: int) -> str:
    """Day number (days since 1970-01-01) as YYYY-MM-DD."""
    return str(np.datetime64(int(d), "D"))


def dnum(day: str) -> int:
    return int(np.datetime64(day, "D").astype(np.int64))


# ---------------------------------------------------------------- the universe (daily bars, point in time)

def base_of(symbol: str) -> str:
    return symbol[:-4] if symbol.endswith("USDT") else symbol


def excluded(symbol: str) -> bool:
    """Stablecoins and fiat, commodity, equity, index and leveraged products."""
    b = base_of(symbol)
    return (b in STABLE or b in NOT_CRYPTO or b.endswith("DOM")
            or (b.endswith(("UP", "DOWN", "BULL", "BEAR")) and len(b) > 4))


def hl_to_binance(coin: str) -> str:
    """Hyperliquid's kX is Binance's 1000XUSDT, the rest XUSDT."""
    if coin.startswith("k") and coin[1:].isupper():
        return f"1000{coin[1:]}USDT"
    return f"{coin}USDT"


def load_daily(root: Path | None = None) -> pl.DataFrame:
    """symbol, day (day number), o h l c, qv of every perp's daily bars before the lockbox."""
    root = root or labdata.ROOT / "hist" / "binance_um" / "klines_1d"
    d = (pl.scan_parquet(str(root / "symbol=*" / "*.parquet"), hive_partitioning=True)
         .select("symbol", "open_time_us", "open", "high", "low", "close", "quote_volume").collect())
    return (d.with_columns(day=(pl.col("open_time_us") // DAY_US).cast(pl.Int64))
            .filter(pl.col("day") < dnum(LOCKBOX))
            .unique(["symbol", "day"], keep="last").sort(["symbol", "day"])
            .select("symbol", "day", o=pl.col("open"), h=pl.col("high"), l=pl.col("low"), c=pl.col("close"),
                    qv=pl.col("quote_volume")))


@dataclass
class Daily:
    """(D, M) arrays on one calendar of day numbers d0..d0+D-1 for M symbols (NaN where no bar)."""
    d0: int
    names: list[str]
    o: np.ndarray
    h: np.ndarray
    l: np.ndarray
    c: np.ndarray
    qv: np.ndarray
    listed: np.ndarray              # (D, M) days since the segment's first bar (-1 outside a segment)

    @property
    def D(self) -> int:
        return self.c.shape[0]

    def row(self, d: int) -> int:
        return d - self.d0


def to_daily(frame: pl.DataFrame) -> Daily:
    names = sorted(frame["symbol"].unique().to_list())
    d0, d1 = int(frame["day"].min()), int(frame["day"].max())
    D, M = d1 - d0 + 1, len(names)
    col = {s: j for j, s in enumerate(names)}
    arr = {k: np.full((D, M), np.nan) for k in ("o", "h", "l", "c", "qv")}
    r = frame["day"].to_numpy() - d0
    j = np.array([col[s] for s in frame["symbol"].to_list()], dtype=np.int64)
    for k in arr:
        arr[k][r, j] = frame[k].to_numpy()
    listed = np.full((D, M), -1, dtype=np.int64)
    for m in range(M):
        have = np.flatnonzero(np.isfinite(arr["c"][:, m]))
        if not len(have):
            continue
        starts = np.r_[0, np.flatnonzero(np.diff(have) > GAP_DAYS) + 1]
        ends = np.r_[starts[1:], len(have)]
        for a, b in zip(starts, ends):
            s, e = have[a], have[b - 1]
            listed[s:e + 1, m] = np.arange(e - s + 1)          # after a segment's last bar nothing is listed
    return Daily(d0, names, arr["o"], arr["h"], arr["l"], arr["c"], arr["qv"], listed)


def trailing_volume(qv: np.ndarray, n: int = VOL_N) -> np.ndarray:
    """(D, M): the mean quote volume of the n days before each day (missing days as 0); NaN for the first n rows."""
    x = np.nan_to_num(qv)
    cs = np.vstack([np.zeros((1, x.shape[1])), np.cumsum(x, 0)])
    out = np.full(qv.shape, np.nan)
    out[n:] = (cs[n:-1] - cs[:-n - 1]) / n
    return out


def qualifies(Dy: Daily, bar: float = VOL_BAR) -> np.ndarray:
    """(D, M) bool: in the universe on that day, from days before it only."""
    vol = trailing_volume(Dy.qv)
    prev_listed = np.vstack([np.full((1, Dy.listed.shape[1]), -1), Dy.listed[:-1]])   # yesterday's age
    ok = (prev_listed + 1 >= MIN_LISTED) & (Dy.listed >= 0) & (np.nan_to_num(vol) >= bar)
    ex = np.array([excluded(s) for s in Dy.names])
    return ok & ~ex[None, :]


def hl_listings(path: Path | None = None) -> dict[str, tuple[int, int | None]]:
    """{Binance symbol: (first listed day, last listed day or None)} from T12b's Hyperliquid listing history: listed
    from the day after the first funding record to the last settlement's day."""
    path = path or labdata.ROOT / "free" / "perps_all" / "hyperliquid" / "listings.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    out = {}
    for coin, v in raw.items():
        if not v.get("first_day"):
            continue
        last = v.get("last_day") if v.get("delisted") else None
        out[hl_to_binance(coin)] = (dnum(v["first_day"]) + 1, dnum(last) if last else None)
    return out


def kf_listings(path: Path | None = None) -> dict[str, int]:
    """{Binance symbol: first day} of Kraken Futures' perps from their opening time (today's list only)."""
    path = path or labdata.ROOT / "free" / "perps_all" / "kraken_futures" / "listings.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    out = {}
    for k, v in raw.items():
        if not k.startswith("PF_") or not v.get("opening_us"):
            continue
        b = v.get("base") or k[3:-3]
        sym = f"1000{b}USDT" if b in ("PEPE", "SHIB", "BONK", "FLOKI") else f"{b}USDT"
        out[sym] = int(v["opening_us"] // DAY_US) + 1
    return out


def listed_mask(Dy: Daily, lst: dict) -> np.ndarray:
    """(D, M) bool: listed on that day by a listing table {symbol: (first, last)} or {symbol: first}."""
    m = np.zeros(Dy.c.shape, dtype=bool)
    days = Dy.d0 + np.arange(Dy.D)
    for j, s in enumerate(Dy.names):
        v = lst.get(s)
        if v is None:
            continue
        first, last = v if isinstance(v, tuple) else (v, None)
        m[:, j] = (days >= first) & ((days <= last) if last is not None else True)
    return m


def universe_counts(Dy: Daily, hl: np.ndarray) -> list[dict]:
    """Per quarter from 2022: the mean and the most coins a day at 20 M, 50 M and 100 M, at 50 M on Hyperliquid,
    and the coins that ever qualify at 50 M."""
    Q = {b: qualifies(Dy, b) for b in VOL_BARS}
    days = Dy.d0 + np.arange(Dy.D)
    dt = days.astype("datetime64[D]")
    qtr = np.array([f"{str(x)[:4]}Q{(int(str(x)[5:7]) - 1) // 3 + 1}" for x in dt])
    rows = []
    for q in sorted(set(qtr[(days >= dnum(IS_FROM)) & (days <= dnum(OOS_TO))])):
        k = qtr == q
        r = {"quarter": q}
        for b in VOL_BARS:
            n = Q[b][k].sum(1)
            r[f"mean_{int(b / 1e6)}M"], r[f"max_{int(b / 1e6)}M"] = float(n.mean()), int(n.max())
        n = (Q[VOL_BAR] & hl)[k].sum(1)
        r["mean_50M_hl"], r["max_50M_hl"] = float(n.mean()), int(n.max())
        r["ever_50M"] = int(Q[VOL_BAR][k].any(0).sum())
        rows.append(r)
    return rows


def needed_months(Dy: Daily, Q: np.ndarray) -> dict[str, list[str]]:
    """{symbol: months to fetch}: every month with a qualifying day from 2022-01 and the month before it."""
    days = (Dy.d0 + np.arange(Dy.D)).astype("datetime64[D]")
    months = days.astype("datetime64[M]")
    keep = (days >= np.datetime64(IS_FROM)) & (days <= np.datetime64(OOS_TO))
    out = {}
    for j, s in enumerate(Dy.names):
        ms = np.unique(months[keep & Q[:, j]])
        if not len(ms):
            continue
        allm = sorted({str(m) for m in ms} | {str(m - np.timedelta64(1, "M")) for m in ms})
        out[s] = [m for m in allm if FETCH_FROM <= m <= OOS_TO[:7]]
    return out


# ---------------------------------------------------------------- 1-minute klines (data.binance.vision)

KCOLS = ["open_time", "open", "high", "low", "close", "volume", "close_time", "quote_volume", "count",
         "taker_buy_volume", "taker_buy_quote_volume", "ignore"]


def kdir(symbol: str) -> Path:
    return CACHE / "klines_1m" / f"symbol={symbol}"


def parse_klines(raw: bytes) -> pl.DataFrame:
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        body = z.read(z.namelist()[0])
    df = pl.read_csv(io.BytesIO(body), has_header=False, new_columns=KCOLS, infer_schema_length=0)
    if df.height and not df[0, 0].isdigit():
        df = df.slice(1)
    ot = df["open_time"].cast(pl.Int64).to_numpy()
    ot = np.where(ot < 10 ** 14, ot * 1000, ot)
    return pl.DataFrame({
        "t": (ot // MIN_US).astype(np.int64),
        **{k: df[c].cast(pl.Float32) for k, c in (("o", "open"), ("h", "high"), ("l", "low"), ("c", "close"),
                                                  ("qv", "quote_volume"), ("tb", "taker_buy_quote_volume"))},
        "n": df["count"].cast(pl.Int32),
    })


def fetch_month(symbol: str, month: str) -> str:
    """One month of a perp's 1-minute klines into the cache; 'have', 'ok', 'absent' or 'error'."""
    d = kdir(symbol)
    f = d / f"{month}.parquet"
    if f.exists() or (d / f"{month}.absent").exists():
        return "have"
    q = urllib.parse.quote(symbol)
    raw = fm_get(f"{BUCKET}/data/futures/um/monthly/klines/{q}/1m/{q}-1m-{month}.zip")
    d.mkdir(parents=True, exist_ok=True)
    if raw is None:
        (d / f"{month}.absent").write_text("")
        return "absent"
    try:
        parse_klines(raw).write_parquet(f)
    except Exception:
        return "error"
    return "ok"


def fm_get(url: str) -> bytes | None:
    from . import vision
    return vision._get(url)


def fetch(plan: dict[str, list[str]], par: int = 12) -> dict:
    jobs = [(s, m) for s, ms in sorted(plan.items()) for m in ms]
    t0, done, stat = time.time(), 0, {}
    with ThreadPoolExecutor(par) as ex:
        for r in ex.map(lambda sm: fetch_month(*sm), jobs):
            done += 1
            stat[r] = stat.get(r, 0) + 1
            if done % 200 == 0:
                print(f"fetch {done}/{len(jobs)} {stat} {time.time() - t0:.0f} s", flush=True)
    return stat


# ---------------------------------------------------------------- the expected range: HAR-PK, one pooled fit a quarter

HAR_LAGS = (1, 7, 30)


def rolling_mean_rows(x: np.ndarray, n: int) -> np.ndarray:
    """(D, M): the mean of rows i-n+1..i per column; NaN until n rows and wherever the window holds a NaN."""
    D = x.shape[0]
    out = np.full(x.shape, np.nan)
    if D < n:
        return out
    bad = np.vstack([np.zeros((1, x.shape[1])), np.cumsum(~np.isfinite(x), 0)])
    cs = np.vstack([np.zeros((1, x.shape[1])), np.cumsum(np.nan_to_num(x), 0)])
    m = (cs[n:] - cs[:-n]) / n
    out[n - 1:] = np.where(bad[n:] - bad[:-n] == 0, m, np.nan)
    return out


def quarter_days(first: str, last: str) -> list[int]:
    q = np.arange(np.datetime64(first, "M"), np.datetime64(last, "M") + np.timedelta64(1, "M"),
                  np.timedelta64(3, "M"))
    return [int(x) for x in q.astype("datetime64[D]").astype(np.int64)]


def har_pk(Dy: Daily, first: str = IS_FROM, last: str = OOS_TO) -> np.ndarray:
    """(D, M) ER: row d holds the forecast of day d's (H - L) / C[d-1], made at 00:00 of d from rows before d.
    RF1's HAR-PK (sqrt Parkinson on its means over 1, 7, 30 days, one QLIKE scale c = mean(y / g)), pooled over
    every non-excluded perp and refitted at each quarter start on all pairs whose target day is before it."""
    with np.errstate(invalid="ignore", divide="ignore"):
        v = np.sqrt(np.log(Dy.h / Dy.l) ** 2 / (4 * math.log(2)))
        v[~np.isfinite(v)] = np.nan
        zhl = (Dy.h - Dy.l) / np.vstack([np.full((1, Dy.c.shape[1]), np.nan), Dy.c[:-1]])
    X = [np.ones(v.shape)] + [rolling_mean_rows(v, n) for n in HAR_LAGS]
    ex = np.array([excluded(s) for s in Dy.names])
    ER = np.full(v.shape, np.nan)
    days = Dy.d0 + np.arange(Dy.D)
    h0 = dnum(HAR_FROM)
    qs = quarter_days(first, last)
    for qi, q0 in enumerate(qs):
        q1 = qs[qi + 1] if qi + 1 < len(qs) else dnum(LOCKBOX)
        # pairs (row i, target row i + 1) with h0 <= i + 1 < q0
        rows = np.flatnonzero((days[:-1] + 1 >= h0) & (days[:-1] + 1 < q0))
        Xi = np.stack([x[rows] for x in X], -1)[:, ~ex]           # (n, M', 4)
        yi, zi = v[rows + 1][:, ~ex], zhl[rows + 1][:, ~ex]
        ok = np.all(np.isfinite(Xi), -1) & np.isfinite(yi) & np.isfinite(zi)
        beta = np.linalg.lstsq(Xi[ok], yi[ok], rcond=None)[0]
        g = np.maximum(Xi[ok] @ beta, 1e-6)
        c = float(np.mean(zi[ok] / g))
        k = np.flatnonzero((days >= q0) & (days < q1))
        if not len(k) or k[0] == 0:
            continue
        Xf = np.stack([x[k - 1] for x in X], -1)                  # made from row d - 1
        ER[k] = np.maximum(c * (Xf @ beta), 1e-6)
    return ER


# ---------------------------------------------------------------- one month of minutes for every coin it needs

@dataclass
class Month:
    """(M, T) minute arrays from 00:00 of the warm-up day (the last day of the month before) to the month's end.
    t index i is minute m0 + i (minutes since 1970); column k is Daily column jd[k]."""
    month: str
    names: list[str]
    jd: np.ndarray
    m0: int
    o: np.ndarray
    h: np.ndarray
    l: np.ndarray
    c: np.ndarray
    qv: np.ndarray
    tb: np.ndarray
    ex: dict = field(default_factory=dict)

    @property
    def M(self) -> int:
        return self.c.shape[0]

    @property
    def T(self) -> int:
        return self.c.shape[1]

    @property
    def nd(self) -> int:
        return self.T // DAY_MIN

    @property
    def day0(self) -> int:
        return self.m0 // DAY_MIN


def month_days(month: str) -> tuple[int, int]:
    """(first day number, days) of a month."""
    a = np.datetime64(month, "M")
    d0, d1 = (x.astype("datetime64[D]").astype(np.int64) for x in (a, a + np.timedelta64(1, "M")))
    return int(d0), int(d1 - d0)


def build_month(month: str, symbols: list[str], Dy: Daily, root: Path | None = None) -> Month | None:
    root = root or CACHE / "klines_1m"
    d_first, nd = month_days(month)
    m0 = (d_first - 1) * DAY_MIN
    T = (nd + 1) * DAY_MIN
    prev = str(np.datetime64(month, "M") - np.timedelta64(1, "M"))
    names, frames = [], []
    for s in symbols:
        f = root / f"symbol={s}" / f"{month}.parquet"
        if not f.exists():
            continue
        parts = [pl.read_parquet(f)]
        fp = root / f"symbol={s}" / f"{prev}.parquet"
        if fp.exists():
            parts.insert(0, pl.read_parquet(fp).filter(pl.col("t") >= m0))
        names.append(s)
        frames.append(pl.concat(parts))
    if not names:
        return None
    M = len(names)
    arr = {k: np.full((M, T), np.nan, dtype=np.float32) for k in ("o", "h", "l", "c", "qv", "tb")}
    for i, df in enumerate(frames):
        df = df.filter((pl.col("t") >= m0) & (pl.col("t") < m0 + T)).unique("t", keep="last")
        idx = df["t"].to_numpy() - m0
        for k in arr:
            arr[k][i, idx] = df[k].to_numpy()
    col = {s: j for j, s in enumerate(Dy.names)}
    return Month(month, names, np.array([col[s] for s in names]), m0, **arr)


def ffill(x: np.ndarray) -> np.ndarray:
    """Forward fill along the time axis (NaN before the first value)."""
    ok = np.isfinite(x)
    idx = np.where(ok, np.arange(x.shape[1])[None, :], 0)
    np.maximum.accumulate(idx, axis=1, out=idx)
    out = x[np.arange(x.shape[0])[:, None], idx]
    out[~np.maximum.accumulate(ok, axis=1)] = np.nan
    return out


def prev_window(x: np.ndarray, n: int) -> tuple[np.ndarray, np.ndarray]:
    """(sum, count) of the finite values of x over t-n..t-1 per row (t itself excluded)."""
    ok = np.isfinite(x)
    cs = np.concatenate([np.zeros((x.shape[0], 1)), np.cumsum(np.where(ok, x, 0.0), 1, dtype=np.float64)], 1)
    cn = np.concatenate([np.zeros((x.shape[0], 1)), np.cumsum(ok, 1)], 1)
    T = x.shape[1]
    lo = np.maximum(np.arange(T) - n, 0)
    return cs[:, np.arange(T)] - cs[:, lo], cn[:, np.arange(T)] - cn[:, lo]


def derive(P: Month) -> Month:
    """Returns, the minute sigma of the previous 1,440 minutes, z, volume z, the taker-buy share, filled prices."""
    with np.errstate(invalid="ignore", divide="ignore"):
        cf = ffill(P.c.astype(np.float64))
        lc = np.log(P.c.astype(np.float64))
        r = np.full(lc.shape, np.nan)
        r[:, 1:] = lc[:, 1:] - lc[:, :-1]
        s2, n = prev_window(r ** 2, SIG_N)
        sig = np.where(n >= SIG_MIN, np.sqrt(s2 / np.maximum(n, 1)), np.nan)
        sig[sig <= 0] = np.nan
        z = r / sig
        lv = np.where(np.isfinite(P.qv), np.log1p(P.qv.astype(np.float64)), np.nan)
        s1, nv = prev_window(lv, SIG_N)
        s2v, _ = prev_window(lv ** 2, SIG_N)
        mu = s1 / np.maximum(nv, 1)
        sd = np.sqrt(np.maximum(s2v / np.maximum(nv, 1) - mu ** 2, 0))
        vz = np.where((nv >= SIG_MIN) & (sd > 0), (lv - mu) / sd, np.nan)
        tbs = P.tb / P.qv
        of = np.where(np.isfinite(P.o), P.o, np.c_[np.full((P.M, 1), np.nan), cf[:, :-1]])
    P.ex.update(cf=cf, r=r, sig=sig, z=z, vz=vz, tbs=tbs, of=of)
    return P


def ar_spread(P: Month) -> tuple[np.ndarray, np.ndarray]:
    """(M, nd) per day: the sum and count of Abdi and Ranaldo's 4 (c_t - eta_t)(c_t - eta_t+1) on log prices."""
    with np.errstate(invalid="ignore", divide="ignore"):
        c = np.log(P.c.astype(np.float64))
        eta = np.log((P.h.astype(np.float64) + P.l) / 2)
        x = np.full(c.shape, np.nan)
        x[:, :-1] = 4 * (c[:, :-1] - eta[:, :-1]) * (c[:, :-1] - eta[:, 1:])
    x = x.reshape(P.M, P.nd, DAY_MIN)
    ok = np.isfinite(x)
    return np.where(ok, x, 0).sum(2), ok.sum(2)


def day_view(x: np.ndarray, nd: int) -> np.ndarray:
    return x.reshape(x.shape[0], nd, DAY_MIN)


def so_far(P: Month) -> dict:
    """Per minute, within its UTC day up to and including it: high, low, VWAP (quote volume over the minute's
    typical price as the base volume)."""
    nd = P.nd
    with np.errstate(invalid="ignore", divide="ignore"):
        hi = np.fmax.accumulate(day_view(P.h.astype(np.float64), nd), axis=2).reshape(P.M, -1)
        lo = np.fmin.accumulate(day_view(P.l.astype(np.float64), nd), axis=2).reshape(P.M, -1)
        tp = (P.h.astype(np.float64) + P.l + P.c) / 3
        q = np.nan_to_num(P.qv.astype(np.float64))
        base = np.where(tp > 0, q / tp, 0)
        cq = np.cumsum(day_view(q, nd), axis=2).reshape(P.M, -1)
        cb = np.cumsum(day_view(base, nd), axis=2).reshape(P.M, -1)
        vwap = np.where(cb > 0, cq / cb, np.nan)
    return {"hi": hi, "lo": lo, "vwap": vwap}


# ---------------------------------------------------------------- the rules (164, the prereg's grid)

KS = (3, 4, 6)
CONFS = ("none", "vol", "taker")
HS = (1, 5, 15, 30, 60, 240)
ORB = {"utc30": (0, 30), "utc60": (0, 60), "us30": (810, 30), "us60": (810, 60)}
VWAP_M = (0.25, 0.5)
P_HS = (15, 60)
P_MARGINS = (0.0, 5e-4, 10e-4, 20e-4)
STOP_SIG, BR_TAKE, BR_STOP, BR_H = 3.0, 2.0, 1.0, 60
D_STOP = 0.5
LAST_ENTRY_D = 23 * 60
VWAP_FROM = 60
VZ_MIN, TB_HI, TB_LO, LEAD_ALT = 3.0, 0.7, 0.3, 1.0


def rules() -> list[str]:
    out = []
    for k in KS:
        for conf in CONFS:
            for side in ("cont", "fade"):
                out += [f"S-own:k{k}:{conf}:{side}:H{h}" for h in HS] + [f"S-own:k{k}:{conf}:{side}:bracket"]
    out += [f"S-lead:k{k}:H{h}" for k in KS for h in HS]
    out += [f"D-orb:{w}:{x}" for w in ORB for x in ("A", "B")] + ["D-prev:A", "D-prev:B"]
    out += [f"D-vwap:m{m}" for m in VWAP_M]
    out += [f"P-gbm:H{h}:m{int(m * 1e4)}" for h in P_HS for m in P_MARGINS]
    return out


def parse_rule(rule: str) -> dict:
    fam, *rest = rule.split(":")
    d = {"fam": fam}
    for p in rest:
        if p[0] == "k" and p[1:].isdigit():
            d["k"] = int(p[1:])
        elif p[0] == "H" and p[1:].isdigit():
            d["H"] = int(p[1:])
        elif p[0] == "m" and fam == "D-vwap":
            d["m"] = float(p[1:])
        elif p[0] == "m" and fam == "P-gbm":
            d["m"] = int(p[1:]) / 1e4
        elif p in CONFS:
            d["conf"] = p
        elif p in ("cont", "fade"):
            d["side"] = p
        elif p == "bracket":
            d["H"], d["bracket"] = BR_H, True
        elif p in ORB:
            d["win"] = p
        elif p in ("A", "B"):
            d["exit"] = p
    return d


# ---------------------------------------------------------------- a month's context and its candidates

@dataclass
class Ctx:
    """A month's minutes with what the rules read per (coin, day of the panel): day 0 is the warm-up day."""
    P: Month
    sf: dict
    qual: np.ndarray          # (M, nd) in the 50 M universe
    hl: np.ndarray            # (M, nd) and listed on Hyperliquid
    kf: np.ndarray            # (M, nd) listed on Kraken Futures
    er: np.ndarray            # (M, nd) expected range (fraction)
    pc: np.ndarray            # (M, nd) the previous day's close
    ph: np.ndarray            # (M, nd) the previous day's high
    plo: np.ndarray           # (M, nd) the previous day's low
    vol: np.ndarray           # (M, nd) 30-day mean quote volume
    slip: np.ndarray          # (M, nd) slippage a side
    fund_bn: list             # per coin (minutes, cumulative rates) of Binance's settlements
    fund_hl: list             # per coin, Hyperliquid's
    btc: int | None


def empty_cand() -> dict:
    return {"j": np.zeros(0, np.int64), "t": np.zeros(0, np.int64), "side": np.zeros(0), "prio": np.zeros(0),
            "ds": np.zeros(0), "tkd": np.zeros(0), "tkl": np.zeros(0), "hold": np.zeros(0, np.int64)}


def cand(j, t, side, prio, ds, hold, tkd=None, tkl=None) -> dict:
    n = len(j)
    return {"j": np.asarray(j, np.int64), "t": np.asarray(t, np.int64), "side": np.asarray(side, float),
            "prio": np.asarray(prio, float), "ds": np.asarray(ds, float),
            "tkd": np.full(n, np.nan) if tkd is None else np.asarray(tkd, float),
            "tkl": np.full(n, np.nan) if tkl is None else np.asarray(tkl, float),
            "hold": np.broadcast_to(np.asarray(hold, np.int64), (n,)).copy()}


def spike_base(C: Ctx, k: float, conf: str) -> tuple[np.ndarray, np.ndarray]:
    """(j, t) of the minutes with |z| >= k (and the confirmation) on universe days, the warm-up day left out."""
    z, P = C.P.ex["z"], C.P
    with np.errstate(invalid="ignore"):
        m = np.abs(z) >= k
        if conf == "vol":
            m &= P.ex["vz"] > VZ_MIN
        elif conf == "taker":
            m &= ((z > 0) & (P.ex["tbs"] > TB_HI)) | ((z < 0) & (P.ex["tbs"] < TB_LO))
    m[:, :DAY_MIN] = False
    m &= np.repeat(C.qual, DAY_MIN, axis=1)
    return np.nonzero(m)


def cand_spike(C: Ctx, r: dict, base: tuple | None = None) -> dict:
    j, t = base if base is not None else spike_base(C, r["k"], r["conf"])
    z, sig = C.P.ex["z"][j, t], C.P.ex["sig"][j, t]
    side = np.sign(z) * (1 if r["side"] == "cont" else -1)
    if r.get("bracket"):
        s = sig * math.sqrt(BR_H)
        return cand(j, t, side, np.abs(z), BR_STOP * s, BR_H, tkd=BR_TAKE * s)
    return cand(j, t, side, np.abs(z), STOP_SIG * sig * math.sqrt(r["H"]), r["H"])


def cand_lead(C: Ctx, r: dict) -> dict:
    if C.btc is None:
        return empty_cand()
    z = C.P.ex["z"]
    zb = z[C.btc]
    with np.errstate(invalid="ignore"):
        tb = np.flatnonzero((np.abs(zb) >= r["k"]) & (np.arange(len(zb)) >= DAY_MIN))
        if not len(tb):
            return empty_cand()
        za = z[:, tb]
        m = (np.abs(za) < LEAD_ALT) & C.qual[:, tb // DAY_MIN]
    m[C.btc] = False
    jj, kk = np.nonzero(m)
    t = tb[kk]
    day = t // DAY_MIN
    sig = C.P.ex["sig"][jj, t]
    return cand(jj, t, np.sign(zb[t]), C.vol[jj, day], STOP_SIG * sig * math.sqrt(r["H"]), r["H"])


def _first_true(m: np.ndarray) -> np.ndarray:
    """Per row the first True column, -1 if none."""
    f = np.argmax(m, axis=-1)
    return np.where(m.any(-1), f, -1)


def cand_orb(C: Ctx, r: dict) -> dict:
    P, nd = C.P, C.P.nd
    s0, w = ORB[r["win"]]
    h, l, c = (day_view(x.astype(np.float64), nd) for x in (P.h, P.l, P.c))
    with np.errstate(invalid="ignore"), warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        hi = np.nanmax(h[:, :, s0:s0 + w], axis=2)
        lo = np.nanmin(l[:, :, s0:s0 + w], axis=2)
    seg = c[:, :, s0 + w:LAST_ENTRY_D]
    with np.errstate(invalid="ignore"):
        fu, fd = _first_true(seg > hi[..., None]), _first_true(seg < lo[..., None])
    return _breakout(C, r, fu, fd, s0 + w)


def cand_prev(C: Ctx, r: dict) -> dict:
    P, nd = C.P, C.P.nd
    c = day_view(P.c.astype(np.float64), nd)[:, :, :LAST_ENTRY_D]
    with np.errstate(invalid="ignore"):
        fu, fd = _first_true(c > C.ph[..., None]), _first_true(c < C.plo[..., None])
    return _breakout(C, r, fu, fd, 0)


def _breakout(C: Ctx, r: dict, fu: np.ndarray, fd: np.ndarray, off: int) -> dict:
    """The first breakout either way per (coin, day) on universe days with an expected range; long above."""
    fu = np.where(fu >= 0, fu + off, 10 ** 6)
    fd = np.where(fd >= 0, fd + off, 10 ** 6)
    first = np.minimum(fu, fd)
    ok = (first < 10 ** 6) & C.qual & np.isfinite(C.er) & np.isfinite(C.pc)
    ok[:, 0] = False
    j, d = np.nonzero(ok)
    mod = first[j, d]
    side = np.where(fu[j, d] <= fd[j, d], 1.0, -1.0)
    t = d * DAY_MIN + mod
    er = C.er[j, d]
    tkl = None
    if r.get("exit") == "B":
        rng = er * C.pc[j, d]
        tkl = np.where(side > 0, C.sf["lo"][j, t] + rng, C.sf["hi"][j, t] - rng)
    return cand(j, t, side, C.vol[j, d], D_STOP * er, 10 ** 6, tkl=tkl)


def cand_vwap(C: Ctx, r: dict) -> dict:
    P, nd = C.P, C.P.nd
    c = P.c.astype(np.float64)
    band = np.repeat(r["m"] * C.er * C.pc, DAY_MIN, axis=1)
    with np.errstate(invalid="ignore"):
        dev = c - C.sf["vwap"]
        up, dn = dev > band, dev < -band
    mod = np.tile(np.arange(DAY_MIN), nd)[None, :]
    live = (mod >= VWAP_FROM) & (mod < LAST_ENTRY_D)
    fu = _first_true(day_view(up & live, nd))
    fd = _first_true(day_view(dn & live, nd))
    fu = np.where(fu >= 0, fu, 10 ** 6)
    fd = np.where(fd >= 0, fd, 10 ** 6)
    first = np.minimum(fu, fd)
    ok = (first < 10 ** 6) & C.qual & np.isfinite(C.er) & np.isfinite(C.pc)
    ok[:, 0] = False
    j, d = np.nonzero(ok)
    t = d * DAY_MIN + first[j, d]
    side = np.where(fu[j, d] <= fd[j, d], -1.0, 1.0)            # fade: above the VWAP goes short
    return cand(j, t, side, C.vol[j, d], D_STOP * C.er[j, d], 10 ** 6, tkl=C.sf["vwap"][j, t])


def candidates(C: Ctx, rule: str, cache: dict | None = None) -> dict:
    r = parse_rule(rule)
    if r["fam"] == "S-own":
        key = (r["k"], r["conf"])
        base = None
        if cache is not None:
            base = cache.get(key)
            if base is None:
                base = cache[key] = spike_base(C, r["k"], r["conf"])
        return cand_spike(C, r, base)
    if r["fam"] == "S-lead":
        return cand_lead(C, r)
    if r["fam"] == "D-orb":
        return cand_orb(C, r)
    if r["fam"] == "D-prev":
        return cand_prev(C, r)
    if r["fam"] == "D-vwap":
        return cand_vwap(C, r)
    raise ValueError(rule)


# ---------------------------------------------------------------- fills, exits and the book

THROUGH, FULL_DEPTH, VOL_CAP, BOOK_USD = fm.THROUGH, fm.FULL_DEPTH, fm.VOL_CAP, fm.BOOK_USD
EXEC = {"hl": (1, False), "hl_late": (2, False), "maker": (1, True)}
CELLS = 3_000_000           # candidates x path minutes held in memory at once


def _gather(x: np.ndarray, j: np.ndarray, idx: np.ndarray) -> np.ndarray:
    return x[j[:, None], np.minimum(idx, x.shape[1] - 1)]


def _rest_share(P: Month, j, L, side_buy, t0, n, cut, usd) -> tuple[np.ndarray, np.ndarray]:
    """A limit at L resting minutes t0..t0+n-1 (never at or past cut): (filled share, first fill minute or -1).
    fast_maker's trade-through rule: a fill needs 1 bp through, the whole order at 10 bps, at most 10 % of the
    minutes' quote volume."""
    idx = t0[:, None] + np.arange(n)[None, :]
    live = idx < cut[:, None]
    lo, hi, qv = (_gather(x, j, idx).astype(np.float64) for x in (P.l, P.h, P.qv))
    with np.errstate(invalid="ignore", divide="ignore"):
        depth = np.where(side_buy[:, None], (L[:, None] - lo) / L[:, None], (hi - L[:, None]) / L[:, None])
        sh = np.where(live & (depth >= THROUGH - 1e-12), np.minimum(1.0, depth / FULL_DEPTH), 0.0)
        sh = np.maximum.accumulate(sh, axis=1)
        capv = VOL_CAP * np.cumsum(np.where(live, np.nan_to_num(qv), 0), axis=1) / np.maximum(usd, 1e-9)[:, None]
        sh = np.maximum.accumulate(np.minimum(sh, capv), axis=1)
    share = sh[:, -1]
    first = _first_true(sh > 1e-12)
    return share, np.where(first >= 0, t0 + first, -1)


def outcomes(C: Ctx, cd: dict, lat: int, maker: bool) -> dict:
    """Every candidate as a trade on its own: entry, exit, gross return, legs, notional, funding. Rows that cannot
    trade (entry at or after 23:55, outside the universe, no price, a take not beyond the entry, a missed limit)
    have ok False."""
    n = len(cd["j"])
    chunk = max(500, int(CELLS // (min(int(cd["hold"].max()), DAY_MIN) + MAKER_REST))) if n else 1
    if n > chunk:
        parts = [outcomes(C, {k: v[a:a + chunk] for k, v in cd.items()}, lat, maker) for a in range(0, n, chunk)]
        return {k: np.concatenate([p[k] for p in parts]) for k in parts[0]}
    P = C.P
    j, t, side = cd["j"], cd["t"], cd["side"]
    e = t + lat
    day = e // DAY_MIN
    ok = (day >= 1) & (day < P.nd) & (e % DAY_MIN < CUT_MIN) & np.isfinite(cd["ds"]) & (cd["ds"] > 0)
    dd = np.clip(day, 0, P.nd - 1)
    ok &= C.qual[j, dd]
    cut = dd * DAY_MIN + CUT_MIN
    e = np.minimum(e, P.T - 1)
    x = np.minimum(e + cd["hold"], cut)
    of, cf = P.ex["of"], P.ex["cf"]
    notional = np.minimum(RISK / np.where(ok, cd["ds"], 1.0), CAP)
    if maker:
        L = np.where(np.isfinite(P.c[j, t]), P.c[j, t], cf[j, t]).astype(np.float64)
        share, t_in = _rest_share(P, j, L, side > 0, e, MAKER_REST, cut, notional * BOOK_USD)
        ok &= (share > 0) & (t_in >= 0) & np.isfinite(L)
        p0 = L
        t_in = np.where(t_in >= 0, t_in, e)
    else:
        share, t_in, p0 = np.ones(n), e, of[j, e]
        ok &= np.isfinite(p0) & (p0 > 0)
    p0 = np.where(ok, p0, 1.0)
    stop = p0 * (1 - side * cd["ds"])
    tk = np.where(np.isfinite(cd["tkl"]), cd["tkl"], p0 * (1 + side * cd["tkd"]))
    has_tk = np.isfinite(tk)
    ok &= ~has_tk | (side * (tk - p0) > 0)
    # the path from the entry minute to the minute before the time exit
    W = int(max(1, (x - t_in)[ok].max())) if ok.any() else 1
    idx = t_in[:, None] + np.arange(W)[None, :]
    live = idx < x[:, None]
    lo, hi, op = (_gather(a, j, idx).astype(np.float64) for a in (P.l, P.h, of))
    with np.errstate(invalid="ignore"):
        hs = live & np.where(side[:, None] > 0, lo <= stop[:, None], hi >= stop[:, None])
        thr = (1 + side * THROUGH) if maker else np.ones(n)
        tkm = (tk * thr)[:, None]
        ht = live & has_tk[:, None] & np.where(side[:, None] > 0, hi >= tkm, lo <= tkm)
    fs, ft = _first_true(hs), _first_true(ht)
    is_stop = (fs >= 0) & ((ft < 0) | (fs <= ft))
    is_take = ~is_stop & (ft >= 0)
    k_s = np.where(fs >= 0, fs, 0)
    o_s = op[np.arange(n), k_s]
    with np.errstate(invalid="ignore"):
        p_stop = np.where(side > 0, np.fmin(o_s, stop), np.fmax(o_s, stop))
    # time exit: taker at the open of x; maker: a limit at that open resting 3 minutes, the rest at the open after
    p_x = of[j, x]
    p_x = np.where(np.isfinite(p_x), p_x, cf[j, np.maximum(x - 1, 0)])
    ext_taker = np.ones(n)
    p_time, t_time = p_x.astype(np.float64), x.copy()
    if maker:
        x2 = np.minimum(x + MAKER_REST, cut)
        sm, _ = _rest_share(P, j, p_x.astype(np.float64), side < 0, x, MAKER_REST, cut,
                            notional * share * BOOK_USD)
        sm = np.where(x < cut, sm, 0.0)
        p_x2 = of[j, x2]
        p_x2 = np.where(np.isfinite(p_x2), p_x2, cf[j, np.maximum(x2 - 1, 0)])
        p_time = sm * p_x + (1 - sm) * p_x2
        t_time = np.where(sm < 1, x2, x)
        ext_taker = np.where(is_stop, 1.0, np.where(is_take, 0.0, 1 - sm))
    p_exit = np.where(is_stop, p_stop, np.where(is_take, tk, p_time))
    t_out = np.where(is_stop, t_in + k_s + 1, np.where(is_take, t_in + np.where(ft >= 0, ft, 0) + 1, t_time))
    ok &= np.isfinite(p_exit) & (p_exit > 0)
    with np.errstate(invalid="ignore", divide="ignore"):
        gross = side * (p_exit / p0 - 1)
    ok &= np.isfinite(gross)
    absm = P.m0 + np.c_[t_in, t_out]
    f_bn = side * funding_between(C.fund_bn, j, absm[:, 0], absm[:, 1])
    f_hl = side * funding_between(C.fund_hl, j, absm[:, 0], absm[:, 1])
    return {"ok": ok, "j": j, "day": dd, "t_in": t_in, "t_out": t_out, "prio": cd["prio"], "gross": gross,
            "ent_taker": np.full(n, 0.0 if maker else 1.0), "ext_taker": ext_taker, "notional": notional * share,
            "slip": C.slip[j, dd], "f_bn": f_bn, "f_hl": f_hl, "kf": C.kf[j, dd], "hl": C.hl[j, dd],
            "stop": is_stop, "take": is_take}


def funding_between(F: list, j: np.ndarray, a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """The sum of each coin's settled rates strictly between minutes a and b (absolute minute numbers)."""
    out = np.zeros(len(j))
    for jj in np.unique(j):
        f = F[jj]
        if f is None:
            continue
        mins, cum = f
        k = j == jj
        out[k] = cum[np.searchsorted(mins, b[k], side="left")] - cum[np.searchsorted(mins, a[k], side="right")]
    return out


def greedy(t_in: np.ndarray, t_out: np.ndarray, j: np.ndarray, prio: np.ndarray, n_pos: int = N_POS) -> np.ndarray:
    """Candidates in time order (ties by priority, larger first) take a slot if fewer than n_pos are open and their
    coin is not held; a slot frees at its exit minute."""
    order = np.lexsort((-prio, t_in))
    take = np.zeros(len(t_in), dtype=bool)
    ti, to, jj = t_in.tolist(), t_out.tolist(), j.tolist()
    heap: list = []
    busy: dict = {}
    for i in order.tolist():
        now = ti[i]
        while heap and heap[0][0] <= now:
            xo, jo = heapq.heappop(heap)
            if busy.get(jo) == xo:
                del busy[jo]
        if len(heap) >= n_pos or jj[i] in busy:
            continue
        take[i] = True
        heapq.heappush(heap, (to[i], jj[i]))
        busy[jj[i]] = to[i]
    return take


STATS = ("n", "g", "st", "ss", "sm", "f", "G", "ST", "SS", "SM", "F", "hold", "n_kf", "N")
K = len(STATS)


def day_stats(o: dict, sel: np.ndarray, venue: str, nd: int) -> np.ndarray:
    """(nd, K) per day of the panel: the sums the book and the per-trade numbers are built from (linear in the fee)."""
    out = np.zeros((nd, K))
    if not sel.any():
        return out
    d = o["day"][sel]
    nt, g, et, xt = o["notional"][sel], o["gross"][sel], o["ent_taker"][sel], o["ext_taker"][sel]
    st = et + xt
    sm = 2 - st
    ss = o["slip"][sel] * st
    f = o["f_hl" if venue == "hl" else "f_bn"][sel]
    cols = [np.ones(len(d)), g, st, ss, sm, f, nt * g, nt * st, nt * ss, nt * sm, nt * f,
            (o["t_out"] - o["t_in"])[sel], o["kf"][sel].astype(float), nt]
    for k, v in enumerate(cols):
        out[:, k] = np.bincount(d, weights=v, minlength=nd)
    return out


def run_rule_month(C: Ctx, rule: str, cache: dict | None = None, cd: dict | None = None) -> dict:
    """{(exec, universe): (nd, K)} for one rule over one month."""
    cd = cd if cd is not None else candidates(C, rule, cache)
    out = {}
    for ex, (lat, maker) in EXEC.items():
        o = outcomes(C, cd, lat, maker)
        for uni in ("bn", "hl"):
            m = o["ok"] & (o["hl"] if uni == "hl" else True)
            idx = np.flatnonzero(m)
            sel = np.zeros(len(m), dtype=bool)
            if len(idx):
                sel[idx[greedy(o["t_in"][idx], o["t_out"][idx], o["j"][idx], o["prio"][idx])]] = True
            out[(ex, uni)] = day_stats(o, sel, uni, C.P.nd)
    return out


# ---------------------------------------------------------------- the world: daily tables every month reads

@dataclass
class World:
    Dy: Daily
    Q: np.ndarray             # (D, M) in the 50 M universe
    hl: np.ndarray            # (D, M) listed on Hyperliquid
    kf: np.ndarray            # (D, M) listed on Kraken Futures
    er: np.ndarray            # (D, M) HAR-PK's expected range of the day
    vol: np.ndarray           # (D, M) 30-day mean quote volume before the day
    top: np.ndarray           # (D, M) among the day's 20 largest by it
    fund_bn: dict
    fund_hl: dict
    slip: np.ndarray | None = None


def load_funding(path: Path, tcol: str) -> tuple[np.ndarray, np.ndarray] | None:
    files = sorted(path.glob("*.parquet")) if path.is_dir() else ([path] if path.exists() else [])
    if not files:
        return None
    f = (pl.concat([pl.read_parquet(x, columns=[tcol, "funding_rate"]) for x in files], how="vertical_relaxed")
         .unique(tcol).sort(tcol).filter(pl.col(tcol) < us(LOCKBOX)))
    mins = (f[tcol].to_numpy() // MIN_US).astype(np.int64)
    return mins, np.r_[0.0, np.cumsum(np.nan_to_num(f["funding_rate"].to_numpy()))]


def build_world(Dy: Daily | None = None, symbols: list[str] | None = None) -> World:
    Dy = Dy or to_daily(load_daily())
    Q = qualifies(Dy)
    hl = listed_mask(Dy, hl_listings())
    kf = listed_mask(Dy, kf_listings())
    vol = trailing_volume(Dy.qv)
    ex = np.array([excluded(s) for s in Dy.names])
    v = np.where(np.isfinite(vol) & ~ex[None, :], vol, -1)
    rank = np.argsort(np.argsort(-v, axis=1), axis=1)
    top = (rank < TOP_N) & (v > 0)
    er = har_pk(Dy)
    symbols = symbols or [Dy.names[j] for j in np.flatnonzero(Q.any(0))]
    inv = {hl_to_binance(c): c for c in json.loads((labdata.ROOT / "free" / "perps_all" / "hyperliquid" /
                                                     "listings.json").read_text(encoding="utf-8"))}
    fb, fh = {}, {}
    for s in symbols:
        fb[s] = load_funding(labdata.ROOT / "hist" / "binance_um" / "funding" / f"symbol={s}", "funding_time_us")
        if s in inv:
            fh[s] = load_funding(labdata.ROOT / "free" / "perps_all" / "hyperliquid" / "funding" /
                                 f"{inv[s]}.parquet", "ts_us")
    return World(Dy, Q, hl, kf, er, vol, top, fb, fh)


def slip_table(W: World, ar: dict) -> np.ndarray:
    """(D, M) slippage a side: 1 bp for the day's top 20; for the rest 1 bp plus half the excess of the coin's
    Abdi-Ranaldo spread over the 30 days before the day over the top 20's median, at most 50 bps."""
    Dy = W.Dy
    S1, N1 = np.zeros(Dy.c.shape), np.zeros(Dy.c.shape)
    for (j, d), (s, n) in ar.items():
        S1[d - Dy.d0, j] += s
        N1[d - Dy.d0, j] += n
    cs = np.vstack([np.zeros((1, S1.shape[1])), np.cumsum(S1, 0)])
    cn = np.vstack([np.zeros((1, S1.shape[1])), np.cumsum(N1, 0)])
    D = Dy.D
    lo = np.maximum(np.arange(D) - VOL_N, 0)
    s, n = cs[np.arange(D)] - cs[lo], cn[np.arange(D)] - cn[lo]
    with np.errstate(invalid="ignore", divide="ignore"), warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        spread = np.where(n > 0, np.sqrt(np.maximum(s / np.maximum(n, 1), 0)), np.nan)
        ref = np.nanmedian(np.where(W.top, spread, np.nan), axis=1)
        slip = SLIP_BASE + np.maximum(0, (spread - np.nan_to_num(ref)[:, None]) / 2)
    slip = np.where(np.isfinite(slip), np.minimum(slip, SLIP_CAP), SLIP_CAP)
    return np.where(W.top, SLIP_BASE, slip)


def month_symbols(W: World, month: str) -> list[str]:
    d_first, nd = month_days(month)
    r0, r1 = d_first - W.Dy.d0, d_first - W.Dy.d0 + nd
    js = np.flatnonzero(W.Q[max(r0, 0):r1].any(0))
    names = [W.Dy.names[j] for j in js]
    return names if "BTCUSDT" in names else names + ["BTCUSDT"]


def make_ctx(W: World, P: Month) -> Ctx:
    Dy = W.Dy
    rows = P.day0 + np.arange(P.nd) - Dy.d0
    pick = lambda A: A[rows][:, P.jd].T                                          # noqa: E731
    prev = lambda A: np.vstack([np.full((1, A.shape[1]), np.nan), A[:-1]])[rows][:, P.jd].T  # noqa: E731
    slip = pick(W.slip) if W.slip is not None else np.full((P.M, P.nd), SLIP_BASE)
    fb = [W.fund_bn.get(s) for s in P.names]
    fh = [W.fund_hl.get(s) for s in P.names]
    q = pick(W.Q)
    return Ctx(P, so_far(P), q, q & pick(W.hl), pick(W.kf), pick(W.er), prev(Dy.c), prev(Dy.h), prev(Dy.l),
               pick(W.vol), slip, fb, fh, P.names.index("BTCUSDT") if "BTCUSDT" in P.names else None)


# ---------------------------------------------------------------- P: features at the decision points

P_EVERY = 15
FEATS = ("r1", "r5", "r15", "r60", "rg15", "rg60", "vz1", "vz15", "tb5", "tb60", "mod", "b1", "b5", "b15", "b60",
         "rso", "pos", "vw")


def _back(x: np.ndarray, j: np.ndarray, t: np.ndarray, n: int) -> np.ndarray:
    """(len, n) of x at minutes t-n+1..t."""
    idx = t[:, None] - np.arange(n)[None, ::-1]
    return x[j[:, None], np.maximum(idx, 0)]


def p_features(C: Ctx) -> dict:
    """Decision points every 15 minutes (the close of minutes 14, 29, ... of a day) of universe coins with a sigma
    and an expected range: the features of the prereg and the targets for H in P_HS (NaN past 23:55)."""
    P = C.P
    mod = np.arange(P.T) % DAY_MIN
    tt = np.flatnonzero((mod % P_EVERY == P_EVERY - 1) & (np.arange(P.T) >= DAY_MIN) & (mod + 1 < CUT_MIN))
    m = C.qual[:, tt // DAY_MIN] & np.isfinite(P.ex["sig"][:, tt]) & np.isfinite(C.er[:, tt // DAY_MIN])
    jj, kk = np.nonzero(m)
    t = tt[kk]
    d = t // DAY_MIN
    sig = P.ex["sig"][jj, t]
    lc = np.log(P.ex["cf"])
    F = {}
    with np.errstate(invalid="ignore", divide="ignore"), warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)             # all-NaN windows give NaN features
        F["r1"] = P.ex["z"][jj, t]
        for n in (5, 15, 60):
            F[f"r{n}"] = (lc[jj, t] - lc[jj, np.maximum(t - n, 0)]) / (sig * math.sqrt(n))
        for n in (15, 60):
            hi = np.nanmax(_back(P.h, jj, t, n), 1).astype(np.float64)
            lo = np.nanmin(_back(P.l, jj, t, n), 1).astype(np.float64)
            F[f"rg{n}"] = np.log(hi / lo) / (sig * math.sqrt(n))
        F["vz1"] = P.ex["vz"][jj, t]
        F["vz15"] = np.nanmean(_back(P.ex["vz"], jj, t, 15), 1)
        for n in (5, 60):
            F[f"tb{n}"] = np.nansum(_back(P.tb, jj, t, n), 1) / np.nansum(_back(P.qv, jj, t, n), 1)
        F["mod"] = (t % DAY_MIN).astype(float)
        if C.btc is not None:
            b = np.full(len(t), C.btc)
            sb = P.ex["sig"][b, t]
            F["b1"] = P.ex["z"][b, t]
            for n in (5, 15, 60):
                F[f"b{n}"] = (lc[b, t] - lc[b, np.maximum(t - n, 0)]) / (sb * math.sqrt(n))
        else:
            for n in (1, 5, 15, 60):
                F[f"b{n}"] = np.full(len(t), np.nan)
        er, pc = C.er[jj, d], C.pc[jj, d]
        hi, lo, c = C.sf["hi"][jj, t], C.sf["lo"][jj, t], P.ex["cf"][jj, t]
        F["rso"] = (hi - lo) / pc / er
        F["pos"] = (c - lo) / (hi - lo)
        F["vw"] = (c - C.sf["vwap"][jj, t]) / (er * pc)
        X = np.column_stack([F[k] for k in FEATS]).astype(np.float32)
        X[~np.isfinite(X)] = np.nan
        out = {"X": X, "jd": P.jd[jj], "sym_row": jj, "t": t + P.m0, "sig": sig, "day": d + P.day0}
        of = P.ex["of"]
        cut = d * DAY_MIN + CUT_MIN
        for h in P_HS:
            e, x = t + 1, t + 1 + h
            y = (of[jj, np.minimum(x, P.T - 1)] / of[jj, e] - 1) / (sig * math.sqrt(h))
            out[f"y{h}"] = np.where(x <= cut, np.clip(y, -6, 6), np.nan).astype(np.float32)
    return out


# ---------------------------------------------------------------- pass 0: spreads, the tail, P's features

def tail_month(C: Ctx, n: int = 10) -> list[dict]:
    """The n worst and best 1-minute log returns of a universe coin on a universe day (the warm-up day left out)."""
    r = C.P.ex["r"].copy()
    m = np.repeat(C.qual, DAY_MIN, axis=1)
    m[:, :DAY_MIN] = False
    r[~m | ~np.isfinite(r)] = np.nan
    flat = r.ravel()
    ok = np.flatnonzero(np.isfinite(flat))
    if not len(ok):
        return []
    o = ok[np.argsort(flat[ok])]
    out = []
    for k in list(o[:n]) + list(o[-n:]):
        j, t = divmod(int(k), C.P.T)
        out.append({"symbol": C.P.names[j], "minute": int(C.P.m0 + t), "ret": float(flat[k])})
    return out


_W: World | None = None


def prepare_month(month: str) -> dict:
    W = _W
    P = build_month(month, month_symbols(W, month), W.Dy)
    if P is None:
        return {"month": month, "ar": {}, "tail": []}
    derive(P)
    s, n = ar_spread(P)
    ar = {}
    for k in range(P.M):
        for dd in range(P.nd):
            if n[k, dd]:
                ar[(int(P.jd[k]), int(P.day0 + dd))] = (float(s[k, dd]), int(n[k, dd]))
    C = make_ctx(W, P)
    feats = p_features(C)
    d = CACHE / "p_feat"
    d.mkdir(parents=True, exist_ok=True)
    np.savez(d / f"{month}.npz", **{k: v for k, v in feats.items() if k != "sym_row"})
    return {"month": month, "ar": ar, "tail": tail_month(C), "coins": P.M}


# ---------------------------------------------------------------- passes over the months

def months(first: str = IS_FROM[:7], last: str = OOS_TO[:7]) -> list[str]:
    a = np.arange(np.datetime64(first, "M"), np.datetime64(last, "M") + np.timedelta64(1, "M"))
    return [str(m) for m in a]


def run_month(month: str, which: str = "SD") -> dict:
    """{rule: {(exec, universe): (days, K)}} with the month's day numbers, for the S and D rules ("SD") or the P
    rules from the saved predictions ("P")."""
    W = _W
    P = build_month(month, month_symbols(W, month), W.Dy)
    if P is None:
        return {"month": month, "days": [], "res": {}}
    derive(P)
    C = make_ctx(W, P)
    res = {}
    if which == "SD":
        cache: dict = {}
        for rule in rules():
            if not rule.startswith("P-"):
                res[rule] = {k: v[1:] for k, v in run_rule_month(C, rule, cache).items()}
    else:
        for rule in rules():
            if rule.startswith("P-"):
                cd = p_candidates(C, month, parse_rule(rule))
                res[rule] = {k: v[1:] for k, v in run_rule_month(C, rule, cd=cd).items()}
    return {"month": month, "days": list(range(P.day0 + 1, P.day0 + P.nd)), "res": res}


def pool_map(fn, items: list, workers: int):
    import multiprocessing as mp
    if workers <= 1:
        return [fn(x) for x in items]
    with mp.get_context("fork").Pool(workers, maxtasksperchild=4) as pool:
        return pool.map(fn, items, chunksize=1)


def _run_sd(m: str) -> dict:
    return run_month(m, "SD")


def _run_p(m: str) -> dict:
    return run_month(m, "P")


# ---------------------------------------------------------------- P: walk-forward LightGBM

GBM = dict(n_estimators=300, learning_rate=0.05, num_leaves=31, min_child_samples=2000, colsample_bytree=0.8,
           subsample=0.5, subsample_freq=1, reg_lambda=10.0, random_state=7, deterministic=True, n_jobs=4,
           verbose=-1)
P_MAX_ROWS = 3_000_000
P_FROM = "2022-07-01"


def load_p_features() -> dict:
    parts = [dict(np.load(f)) for f in sorted((CACHE / "p_feat").glob("*.npz"))]
    return {k: np.concatenate([p[k] for p in parts]) for k in parts[0]}


def fit_predict(F: dict, h: int, log=print) -> np.ndarray:
    """Walk-forward by quarter from P_FROM: each quarter's rows predicted by a model fitted on the rows of days
    before the quarter's first day minus one (the embargo), at most P_MAX_ROWS of them (a seeded sample)."""
    import lightgbm as lgb
    y = F[f"y{h}"]
    pred = np.full(len(y), np.nan)
    qs = quarter_days(P_FROM, OOS_TO)
    for qi, q0 in enumerate(qs):
        q1 = qs[qi + 1] if qi + 1 < len(qs) else dnum(LOCKBOX)
        tr = np.flatnonzero((F["day"] < q0 - 1) & np.isfinite(y))
        te = np.flatnonzero((F["day"] >= q0) & (F["day"] < q1))
        if not len(te) or len(tr) < 10_000:
            continue
        if len(tr) > P_MAX_ROWS:
            tr = np.sort(np.random.default_rng(7 + qi).choice(tr, P_MAX_ROWS, replace=False))
        m = lgb.LGBMRegressor(**GBM)
        m.fit(F["X"][tr], y[tr])
        pred[te] = m.predict(F["X"][te])
        log(f"P H{h} {day_str(q0)}: {len(tr)} rows, {len(te)} predicted")
    return pred


def p_candidates(C: Ctx, month: str, r: dict) -> dict:
    """Decision points of the month whose predicted move beats the round trip at Hyperliquid's taker cost plus
    the rule's margin; the side is the prediction's."""
    f = CACHE / "p_pred" / f"{month}.npz"
    if not f.exists():
        return empty_cand()
    z = dict(np.load(f))
    h = r["H"]
    row = {int(jd): k for k, jd in enumerate(C.P.jd)}
    jj = np.array([row.get(int(x), -1) for x in z["jd"]], dtype=np.int64)
    t = z["t"] - C.P.m0
    pred = z[f"pred{h}"]
    ok = (jj >= 0) & np.isfinite(pred)
    jj, t, pred, sig = jj[ok], t[ok], pred[ok], z["sig"][ok]
    move = np.abs(pred) * sig * math.sqrt(h)
    cost = 2 * (FEE_HL + C.slip[jj, t // DAY_MIN])
    go = move > cost + r["m"]
    return cand(jj[go], t[go], np.sign(pred[go]), (move - cost)[go], STOP_SIG * sig[go] * math.sqrt(h), h)


# ---------------------------------------------------------------- the numbers

CASE_FEES = {"hl": ("hl", FEE_HL, FEE_MAKER), "hl_late": ("hl_late", FEE_HL, FEE_MAKER),
             "maker": ("maker", FEE_HL, FEE_MAKER), "kf": ("hl", FEE_KF, FEE_MAKER)}
S_ = {k: i for i, k in enumerate(STATS)}


def net_parts(A: np.ndarray, case: str, haircut: float = 0.0) -> tuple[np.ndarray, np.ndarray]:
    """(per-day sum of net per trade, per-day book return) of a (days, K) stats array at the case's fees."""
    _, ft, fmk = CASE_FEES[case]
    s = lambda k: A[:, S_[k]]                                                  # noqa: E731
    per = s("g") - ft * s("st") - s("ss") - (fmk + haircut) * s("sm") - s("f")
    book = s("G") - ft * s("ST") - s("SS") - (fmk + haircut) * s("SM") - s("F")
    return per, book


def ann_sharpe(x: np.ndarray) -> float:
    x = np.asarray(x, float)
    return float(x.mean() / x.std() * math.sqrt(YEAR)) if len(x) > 1 and x.std() > 0 else 0.0


def boot_q05(per: np.ndarray, n: np.ndarray, idx: np.ndarray) -> float:
    """5 % quantile of the day-block bootstrap of the mean net per trade (sum of net over sum of trades)."""
    num, den = per[idx].sum(1), n[idx].sum(1)
    with np.errstate(invalid="ignore", divide="ignore"):
        v = num / den
    v = v[np.isfinite(v)]
    return float(np.quantile(v, 0.05)) if len(v) else float("nan")


def summarize(A: np.ndarray, case: str, idx: np.ndarray | None = None) -> dict:
    n = A[:, S_["n"]]
    per, book = net_parts(A, case)
    N = float(n.sum())
    g, ss, f, st, sm = (float(A[:, S_[k]].sum()) for k in ("g", "ss", "f", "st", "sm"))
    out = {"trades": int(N), "per_day": N / len(A) if len(A) else 0.0,
           "hold_min": float(A[:, S_["hold"]].sum() / N) if N else float("nan"),
           "gross_bps": g / N * 1e4 if N else float("nan"), "net_bps": float(per.sum() / N * 1e4) if N else float("nan"),
           "fee_be_bps": (g - ss - f) / (st + sm) * 1e4 if N else float("nan"),
           "funding_bps": f / N * 1e4 if N else float("nan"), "slip_bps": ss / max(st, 1) * 1e4,
           "kf_share": float(A[:, S_["n_kf"]].sum() / N) if N else float("nan"),
           "sharpe": ann_sharpe(book), "cagr": float(np.exp(np.sum(np.log1p(np.maximum(book, -0.99)))) **
                                                     (YEAR / max(len(book), 1)) - 1),
           "max_dd": max_dd(book), "exposure": float(A[:, S_["N"]].sum() / N) if N else float("nan")}
    if idx is not None:
        out["band05_bps"] = boot_q05(per, n, idx) * 1e4 if N else float("nan")
    return out


def max_dd(x: np.ndarray) -> float:
    if not len(x):
        return 0.0
    eq = np.cumprod(1 + np.maximum(x, -0.99))
    return float(np.max(1 - eq / np.maximum.accumulate(eq)))


# ---------------------------------------------------------------- the price check against Hyperliquid

def _post(body: dict) -> list | dict | None:
    req = urllib.request.Request(HL_INFO, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    for k in range(4):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read())
        except Exception:
            time.sleep(2 ** (k + 1))
    return None


def binance_day(symbol: str, day: str) -> pl.DataFrame | None:
    q = urllib.parse.quote(symbol)
    raw = fm_get(f"{BUCKET}/data/futures/um/daily/klines/{q}/1m/{q}-1m-{day}.zip")
    return parse_klines(raw) if raw else None


def price_check(W: World, n: int = 20, days: int = 3) -> dict:
    """Hyperliquid's public 1-minute candles against Binance's on the last days both publish, for the n coins with
    the largest 30-day volume on 2026-06-30 that Hyperliquid lists today. Prices only; no rule's number."""
    lst = json.loads((labdata.ROOT / "free" / "perps_all" / "hyperliquid" / "listings.json").read_text("utf-8"))
    live = {hl_to_binance(c): c for c, v in lst.items() if not v.get("delisted")}
    last = W.Dy.D - 1
    order = np.argsort(-np.nan_to_num(W.vol[last]))
    coins = [(W.Dy.names[j], live[W.Dy.names[j]]) for j in order if W.Dy.names[j] in live and W.Q[last, j]][:n]
    today = datetime.now(timezone.utc).date()
    cand_days = [str(today - timedelta(days=k)) for k in range(1, 6)]
    have = [d for d in cand_days if binance_day("BTCUSDT", d) is not None][:days]
    if not have:
        return {"days": [], "rows": []}
    t0 = us(min(have)) // 1000
    t1 = (us(max(have)) + DAY_US) // 1000
    t0 = max(t0, int(time.time() * 1000) - 4990 * 60_000)
    rows = []
    for sym, coin in coins:
        hl = _post({"type": "candleSnapshot", "req": {"coin": coin, "interval": "1m", "startTime": t0, "endTime": t1}})
        bn = [binance_day(sym, d) for d in have]
        bn = [b for b in bn if b is not None]
        if not hl or not bn:
            rows.append({"symbol": sym, "coin": coin, "minutes": 0})
            continue
        h = pl.DataFrame({"t": [int(x["t"]) // 60_000 for x in hl], "hc": [float(x["c"]) for x in hl]})
        b = pl.concat(bn).select("t", "c").with_columns(pl.col("c").cast(pl.Float64))
        j = h.join(b, on="t").sort("t")
        if j.height < 10:
            rows.append({"symbol": sym, "coin": coin, "minutes": j.height})
            continue
        scale = 1000.0 if coin.startswith("k") and not sym.startswith("1000") else 1.0
        g = np.abs(np.log(j["hc"].to_numpy() * scale / j["c"].to_numpy())) * 1e4
        rh, rb = np.diff(np.log(j["hc"].to_numpy())), np.diff(np.log(j["c"].to_numpy()))
        rows.append({"symbol": sym, "coin": coin, "minutes": j.height, "median_gap_bps": float(np.median(g)),
                     "p99_gap_bps": float(np.quantile(g, 0.99)), "ret_corr": float(np.corrcoef(rh, rb)[0, 1])})
    return {"days": sorted(have), "from_ms": t0, "rows": rows}


def daily_tail(W: World, n: int = 10) -> dict:
    """The worst and best close-to-close days and the deepest lows against the previous close of a universe coin
    on a universe day, 2022-01 to 2026-06."""
    Dy = W.Dy
    with np.errstate(invalid="ignore", divide="ignore"):
        pc = np.vstack([np.full((1, Dy.c.shape[1]), np.nan), Dy.c[:-1]])
        r = np.log(Dy.c / pc)
        lo = Dy.l / pc - 1
    days = Dy.d0 + np.arange(Dy.D)
    m = W.Q & ((days >= dnum(IS_FROM)) & (days <= dnum(OOS_TO)))[:, None]
    out = {}
    for key, x in (("close", r), ("low", lo)):
        x = np.where(m & np.isfinite(x), x, np.nan)
        flat = x.ravel()
        ok = np.flatnonzero(np.isfinite(flat))
        o = ok[np.argsort(flat[ok])]
        pick = list(o[:n]) + (list(o[-n:]) if key == "close" else [])
        out[key] = [{"symbol": Dy.names[k % Dy.c.shape[1]], "day": day_str(Dy.d0 + k // Dy.c.shape[1]),
                     "ret": float(flat[k])} for k in pick]
    return out


# ---------------------------------------------------------------- judgement

def window_rows(days: np.ndarray, first: str, last: str) -> np.ndarray:
    return np.flatnonzero((days >= dnum(first)) & (days <= dnum(last)))


def trials(is_sharpe: dict) -> list[dict]:
    return [{"id": f"hand:dt1:{r}:{c}", "family": "hand", "source": PREREG, "sharpe": is_sharpe.get((r, c))}
            for r in rules() for c in CASES]


def btc_daily(W: World, days: np.ndarray) -> np.ndarray:
    j = W.Dy.names.index("BTCUSDT")
    c = W.Dy.c[:, j]
    with np.errstate(invalid="ignore", divide="ignore"):
        r = c[1:] / c[:-1] - 1
    r = np.r_[np.nan, r]
    return np.nan_to_num(r[days - W.Dy.d0])


def judge(R: dict, days: np.ndarray, W: World, pool: dict) -> list[dict]:
    """One row per (rule, case): out of sample on the Hyperliquid universe against the prereg's pass rule, with the
    in-sample numbers and the Binance universe next to it."""
    oos = window_rows(days, OOS_FROM, OOS_TO)
    ins = window_rows(days, IS_FROM, IS_TO)
    idx = metrics.stationary_bootstrap(len(oos), BOOT_DRAWS, BOOT_BLOCK, BOOT_SEED)
    btc = ann_sharpe(btc_daily(W, days[oos]))
    rows = []
    for rule in rules():
        for case in CASES:
            ex = CASE_FEES[case][0]
            A_hl, A_bn = R[rule][(ex, "hl")], R[rule][(ex, "bn")]
            s = summarize(A_hl[oos], case, idx)
            sb = summarize(A_bn[oos], case)
            si = summarize(A_bn[ins], case)
            _, book = net_parts(A_hl[oos], case)
            late = None
            if case in ("hl", "kf"):
                late = summarize(R[rule][("hl_late", "hl")][oos], case)["net_bps"]
            d = metrics.dsr(book, pool)
            r = {"rule": rule, "case": case, **s, "is_sharpe": si["sharpe"], "is_net_bps": si["net_bps"],
                 "is_trades": si["trades"], "bn_sharpe": sb["sharpe"], "bn_net_bps": sb["net_bps"], "btc_sharpe": btc,
                 "late_net_bps": late, "dsr": d}
            fails = []
            if not (s["trades"] >= MIN_TRADES):
                fails.append(f"{s['trades']} trades")
            if not (np.isfinite(s["net_bps"]) and s["net_bps"] > 0):
                fails.append(f"net {s['net_bps']:.1f} bps")
            elif not (s.get("band05_bps", np.nan) > 0):
                fails.append(f"band 5 % {s['band05_bps']:.1f} bps")
            if not (s["sharpe"] > 0 and s["sharpe"] > btc):
                fails.append(f"Sharpe {s['sharpe']:.2f}")
            if late is not None and not (np.isfinite(late) and late > 0):
                fails.append(f"late {late:.1f} bps")
            if not d >= DSR_PASS:
                fails.append(f"DSR {d:.2f}")
            if not sb["sharpe"] > 0:
                fails.append(f"Binance universe {sb['sharpe']:.2f}")
            r["pass"] = not fails
            r["why"] = "; ".join(fails)
            rows.append(r)
    return rows


def p_picks(rows: list[dict]) -> dict:
    """Per H the margin with the best in-sample mean net per trade (Hyperliquid taker, Binance universe)."""
    out = {}
    for h in P_HS:
        cands = [r for r in rows if r["case"] == "hl" and r["rule"].startswith(f"P-gbm:H{h}:")
                 and np.isfinite(r["is_net_bps"])]
        if cands:
            out[h] = max(cands, key=lambda r: r["is_net_bps"])["rule"]
    return out


# ---------------------------------------------------------------- the report

HEAD = """# DT1: day trading on every liquid listed coin (no rug risk), flat by 23:55 UTC

Pre-registered in `results/daytrade_dt1_prereg.md` (committed before the first run). Code:
`lab.experiments.daytrade_dt1`, tests `tests/test_daytrade_dt1.py`. Paper only: nothing a live bot, a wallet or the
engine reads changed.
"""


def _f(v, nd: int = 2) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, (int, np.integer)):
        return str(int(v))
    if isinstance(v, (float, np.floating)):
        return "n/a" if not math.isfinite(v) else f"{v:.{nd}f}"
    return str(v)


def _table(rows: list[dict], cols: list[tuple[str, str, int]]) -> str:
    out = ["| " + " | ".join(h for _, h, _ in cols) + " |", "|" + "---|" * len(cols)]
    for r in rows:
        out.append("| " + " | ".join(_f(r.get(k), nd) for k, _, nd in cols) + " |")
    return "\n".join(out)


MAIN_COLS = [("rule", "rule", 0), ("trades", "trades", 0), ("per_day", "a day", 1), ("hold_min", "hold min", 0),
             ("gross_bps", "gross bps", 1), ("net_bps", "net bps", 1), ("band05_bps", "band 5 %", 1),
             ("fee_be_bps", "break-even fee", 1), ("is_sharpe", "Sharpe IS", 2), ("sharpe", "Sharpe OOS", 2),
             ("bn_sharpe", "Binance univ.", 2), ("late_net_bps", "late net bps", 1), ("dsr", "DSR", 3),
             ("why", "fails", 0)]


def markdown(o: dict) -> str:
    rows = o["rows"]
    md = [f"Generated {o['generated']}. Binance USD-M 1-minute klines {IS_FROM} to {OOS_TO} (no minute after it "
          f"downloaded or read: the lockbox untouched); in sample {IS_FROM} to {IS_TO}, judged out of sample "
          f"{OOS_FROM} to {OOS_TO} ({o['oos_days']} days) on the coins Hyperliquid listed each day. "
          f"{len(rules())} rules in {len(CASES)} cases, {len(rules()) * len(CASES)} trials in R5's registry "
          f"(hand family, each with its in-sample Sharpe, registered before any out-of-sample number); pool of all "
          f"{o['pool']['n_trials']} trials, noise bar {o['pool']['sr0_annual']:.2f} a year.", ""]
    passed = [r for r in rows if r["pass"]]
    md += ["## Verdict", ""]
    if passed:
        md.append(f"**{len(passed)} (rule, case) pass:** " + ", ".join(f"{r['rule']} ({r['case']})" for r in passed)
                  + ". Each becomes a paper book in its own later commit (PAPER ONLY).")
    else:
        md.append("**No day-trading rule passes. None earns money after the costs of a venue the owner can reach "
                  "with the significance the pass rule asks for, so nothing reaches a paper book.**")
    hl = [r for r in rows if r["case"] == "hl"]
    pos = [r for r in hl if np.isfinite(r["net_bps"]) and r["net_bps"] > 0 and r["trades"] >= MIN_TRADES]
    md += ["", f"- Hyperliquid taker, out of sample: {len(pos)} of {len(hl)} rules make more than 0 bps net per trade "
           f"(at least {MIN_TRADES} trades); {sum(r['sharpe'] > 0 for r in hl)} have a Sharpe above 0; BTC buy and hold "
           f"on the same days {o['btc_sharpe']:.2f}.",
           f"- Median break-even fee a side (Hyperliquid's taker is 4.5 bps): "
           f"{_f(float(np.nanmedian([r['fee_be_bps'] for r in hl])), 1)} bps; best "
           f"{_f(float(np.nanmax([r['fee_be_bps'] for r in hl if r['trades'] >= MIN_TRADES] or [np.nan])), 1)} bps.",
           f"- Maker case: {sum(1 for r in rows if r['case'] == 'maker' and r['net_bps'] > 0)} of {len(hl)} rules net "
           f"positive per filled trade; Kraken Futures: {sum(1 for r in rows if r['case'] == 'kf' and r['net_bps'] > 0)}.",
           f"- P picks (margin fitted in sample): " + ", ".join(f"H{h}: {v}" for h, v in o["p_picks"].items()) + ".",
           ""]
    md += ["## Universe (point in time, survivorship free)", "",
           "Coins a day by quarter: Binance USDT-M perps listed 180 days with the 30-day mean quote volume at the bar "
           "(stablecoins, fiat, commodity, equity, index and leveraged products out); `hl` the 50 M coins Hyperliquid "
           "listed that day (its listing history starts 2023-05-12); `ever` the coins in the 50 M universe on any day "
           "of the quarter.", "",
           _table(o["universe"], [("quarter", "quarter", 0), ("mean_20M", "20 M", 1), ("mean_50M", "50 M", 1),
                                  ("max_50M", "50 M most", 0), ("mean_100M", "100 M", 1), ("mean_50M_hl", "hl", 1),
                                  ("ever_50M", "ever 50 M", 0)]), ""]
    md += ["## The rug-like tail inside the universe", "",
           "Worst and best single minutes (log return of a 1-minute close) of a universe coin on a universe day:", "",
           _table([{**t, "when": str(np.datetime64(t["minute"], "m")), "pct": 100 * (math.exp(t["ret"]) - 1)}
                   for t in o["tail_min"]], [("symbol", "coin", 0), ("when", "minute (UTC)", 0), ("pct", "%", 1)]), "",
           "Worst and best days (close to close) and the deepest lows against the previous close:", "",
           _table([{**t, "pct": 100 * (math.exp(t["ret"]) - 1)} for t in o["tail_day"]["close"]],
                  [("symbol", "coin", 0), ("day", "day", 0), ("pct", "close %", 1)]), "",
           _table([{**t, "pct": 100 * t["ret"]} for t in o["tail_day"]["low"]],
                  [("symbol", "coin", 0), ("day", "day", 0), ("pct", "low %", 1)]), ""]
    pc = o.get("price_check") or {}
    md += ["## Binance minutes against Hyperliquid's", "",
           f"Hyperliquid's public `candleSnapshot` 1-minute closes against Binance's on {', '.join(pc.get('days', []))} "
           "(the only days its API gives; prices only, no rule's number):", "",
           _table(pc.get("rows", []), [("coin", "coin", 0), ("minutes", "minutes", 0),
                                       ("median_gap_bps", "median gap bps", 2), ("p99_gap_bps", "p99 gap bps", 1),
                                       ("ret_corr", "corr of 1m returns", 3)]), ""]
    by = {}
    for r in rows:
        by.setdefault(r["case"], []).append(r)
    md += ["## Every rule, Hyperliquid taker (the base case)", "",
           "Out of sample on the Hyperliquid universe unless marked: trades, trades a day, the mean hold, gross and net "
           "bps of notional per trade, the 5 % quantile of the day-block bootstrap of the net, the fee a side at "
           "which the net is zero, Sharpe in sample (Binance universe) and out of sample, the same rule on the whole "
           "Binance universe, one minute late, the DSR.", "", _table(by["hl"], MAIN_COLS), ""]
    small = [("rule", "rule", 0), ("trades", "trades", 0), ("net_bps", "net bps", 1), ("band05_bps", "band 5 %", 1),
             ("fee_be_bps", "break-even fee", 1), ("sharpe", "Sharpe OOS", 2), ("bn_sharpe", "Binance univ.", 2),
             ("dsr", "DSR", 3), ("why", "fails", 0)]
    md += ["## Maker case (1.5 bps, trade-through fills; missed entries stay missed)", "", _table(by["maker"], small), "",
           f"Maker sensitivity (not judged): with fast_maker's 3 bps adverse-selection haircut on every maker leg, "
           f"{o['haircut_pos']} rules stay net positive.", "",
           "## Kraken Futures taker (5 bps)", "", _table(by["kf"], small), "",
           "## One minute late (Hyperliquid taker)", "", _table(by["hl_late"], small), ""]
    md += ["## Notes", "",
           "- Equal risk: 0.25 % of equity at the stop, at most 1x equity a position and 5 positions; a book's Sharpe "
           "is over every day of the window, flat days as 0.",
           "- Slippage: 1 bp for the day's top 20 by 30-day volume, more by the Abdi-Ranaldo spread proxy for the rest "
           f"(median over traded rules {o['slip_med']:.1f} bps a side).",
           "- Funding at its settlements (Hyperliquid's hourly rates on the Hyperliquid universe, Binance's on the "
           "Binance universe); intraday it is small: "
           f"{o['funding_max']:.1f} bps per trade at most among the base-case rules.",
           "- Optional features: `book20` starts 2026-09-30 (inside the lockbox) and `um_metrics` holds 20 symbols "
           "from 2023-05: neither used.",
           f"- Kraken Futures listing (opening time, today's list): {100 * o['kf_share_med']:.0f} % median share of the "
           "Hyperliquid trades in coins Kraken Futures lists.", ""]
    return "\n".join(md)


# ---------------------------------------------------------------- main

def haircut_positive(R: dict, rows: np.ndarray) -> int:
    """Rules whose maker case stays net positive per trade with the 3 bps haircut on every maker leg."""
    n = 0
    for rule in rules():
        A = R[rule][("maker", "hl")][rows]
        per, _ = net_parts(A, "maker", HAIRCUT)
        n += int(A[:, S_["n"]].sum() > 0 and per.sum() > 0)
    return n


def assemble(parts: list[dict], days: np.ndarray) -> dict:
    pos = {int(d): k for k, d in enumerate(days)}
    R: dict = {}
    for p in parts:
        rows = np.array([pos.get(d, -1) for d in p["days"]])
        keep = rows >= 0
        for rule, res in p["res"].items():
            for key, A in res.items():
                tgt = R.setdefault(rule, {}).setdefault(key, np.zeros((len(days), K)))
                tgt[rows[keep]] += A[keep]
    return R


def main(argv: list[str] | None = None) -> int:
    global _W
    import pickle
    argv = sys.argv[1:] if argv is None else argv
    from .. import report
    rep = report.REPORTS / NAME
    if "--fetch" in argv:
        Dy = to_daily(load_daily())
        print(fetch(needed_months(Dy, qualifies(Dy))))
        return 0
    if "--report" in argv:
        o = json.loads((rep / "latest.json").read_text(encoding="utf-8"))
        from . import director_common as dc
        dc.write_results(NAME, markdown(o), HEAD)
        return 0
    register = "--no-register" not in argv
    workers = int(os.environ.get("DT1_WORKERS", "3"))
    t0 = time.time()
    log = lambda s: print(f"[{time.time() - t0:.0f} s] {s}", flush=True)       # noqa: E731
    _W = W = build_world()
    log("world ready")
    ms = months()
    p0f = CACHE / "pass0.pkl"
    if p0f.exists():
        p0 = pickle.loads(p0f.read_bytes())
    else:
        p0 = pool_map(prepare_month, ms, workers)
        p0f.write_bytes(pickle.dumps(p0))
    ar = {}
    for p in p0:
        ar.update(p["ar"])
    W.slip = slip_table(W, ar)
    log("pass 0 (spreads, tail, features) done")
    days = np.arange(dnum(IS_FROM), dnum(OOS_TO) + 1)
    sdf = CACHE / "pass_sd.pkl"
    if sdf.exists():
        R = pickle.loads(sdf.read_bytes())
    else:
        R = assemble(pool_map(_run_sd, ms, workers), days)
        sdf.write_bytes(pickle.dumps(R))
    log("S and D rules done")
    pf = CACHE / "pass_p.pkl"
    if pf.exists():
        R.update(pickle.loads(pf.read_bytes()))
    else:
        F = load_p_features()
        preds = {h: fit_predict(F, h, log) for h in P_HS}
        month_of = np.array([str(np.datetime64(int(d), "D").astype("datetime64[M]")) for d in F["day"]])
        (CACHE / "p_pred").mkdir(parents=True, exist_ok=True)
        for m in ms:
            k = month_of == m
            np.savez(CACHE / "p_pred" / f"{m}.npz", jd=F["jd"][k], t=F["t"][k], sig=F["sig"][k],
                     **{f"pred{h}": preds[h][k] for h in P_HS})
        del F
        RP = assemble(pool_map(_run_p, ms, workers), days)
        pf.write_bytes(pickle.dumps(RP))
        R.update(RP)
    log("P rules done")
    ins = window_rows(days, IS_FROM, IS_TO)
    is_sharpe = {}
    for rule in rules():
        for case in CASES:
            _, book = net_parts(R[rule][(CASE_FEES[case][0], "bn")][ins], case)
            is_sharpe[(rule, case)] = ann_sharpe(book)
    T = trials(is_sharpe)
    if register:
        metrics.register(T)                     # before any out-of-sample number
    pool = metrics.trial_pool(None, extra=T)
    rows = judge(R, days, W, pool)
    log("judged")
    Dy = W.Dy
    tail_min = sorted([t for p in p0 for t in p["tail"]], key=lambda t: t["ret"])
    hl_rows = [r for r in rows if r["case"] == "hl" and r["trades"]]
    oos = window_rows(days, OOS_FROM, OOS_TO)
    out = {"generated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "rows": rows,
           "pool": {k: pool[k] for k in ("n_trials", "var", "sr0_annual")}, "oos_days": int(len(oos)),
           "btc_sharpe": ann_sharpe(btc_daily(W, days[oos])), "p_picks": p_picks(rows),
           "universe": universe_counts(Dy, W.hl), "tail_min": tail_min[:10] + tail_min[-10:],
           "tail_day": daily_tail(W), "price_check": price_check(W),
           "haircut_pos": haircut_positive(R, oos),
           "slip_med": float(np.nanmedian([r["slip_bps"] for r in hl_rows])) if hl_rows else float("nan"),
           "funding_max": float(np.nanmax(np.abs([r["funding_bps"] for r in hl_rows]))) if hl_rows else 0.0,
           "kf_share_med": float(np.nanmedian([r["kf_share"] for r in hl_rows])) if hl_rows else float("nan"),
           "trials": [t["id"] for t in T], "passed": [f"{r['rule']}:{r['case']}" for r in rows if r["pass"]]}
    rep.mkdir(parents=True, exist_ok=True)
    (rep / "latest.json").write_text(json.dumps(out, indent=1, default=float), encoding="utf-8")
    from . import director_common as dc
    dc.write_results(NAME, markdown(out), HEAD)
    log(f"done; passed: {out['passed'] or 'none'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
