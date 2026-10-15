"""X7 A: the overnight drift. Buy at the close, sell at the next open, cash in the day.

    python -m lab.experiments.overnight                  (Yahoo daily OHLC, cached; the W4 5-minute cache for the fill checks)
    python -m lab.experiments.overnight --refresh        (downloads the daily data again)
    python -m lab.experiments.overnight --source alpaca  (also fetches missing 5-minute bars; needs APCA_API_KEY_ID
                                                          and APCA_API_SECRET_KEY in the environment)

Pre-registered in results/overnight.md (the part above the marker was
committed before this file existed). Writes that file below the marker and
<reports>/overnight/latest.{md,json}.

Data: Yahoo's chart API, open, close, adjusted close and splits from 1993,
cached as <data>/etf/ohlc/<SYM>.csv. The day's factor adjclose / close also
adjusts the open, so a night's return carries the dividend of its ex-date.
The 5-minute bars (adjustment all) only serve the fill checks and the
agreement of the two sources.
"""

from __future__ import annotations

import io
import json
import math
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
from scipy import stats

from ..data import ROOT
from ..metrics import deflated_sharpe
from . import fam_common as fc

NAME = "overnight"
MARKER = "<!-- generated below by lab.experiments.overnight; edit above this line only -->"

ETF3 = ("SPY", "QQQ", "IWM")
SECTORS = ("XLB", "XLE", "XLF", "XLI", "XLK", "XLP", "XLU", "XLV", "XLY")
STOCKS = ("AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "AVGO", "TSLA", "BRK-B", "JPM", "LLY", "V", "WMT", "ORCL",
          "MA", "XOM", "NFLX", "COST", "JNJ", "HD")
SYMBOLS = ETF3 + SECTORS + STOCKS
SLEEVES = {"U1 SPY": ("SPY",), "U2 QQQ": ("QQQ",), "U3 IWM": ("IWM",), "U4 SPY+QQQ+IWM": ETF3,
           "U5 sectors": SECTORS, "U6 large caps": STOCKS}
RULES = ("R0 always", "R1 trend", "R2 calm", "R3 stormy", "R4 turn of month", "R5 holiday")

YAHOO = ("https://query1.finance.yahoo.com/v8/finance/chart/{}?period1=725846400&period2={}"
         "&interval=1d&events=div%2Csplit")
CACHE = Path(os.environ.get("PYTHIA_OHLC_DATA", ROOT / "etf" / "ohlc"))
BARS_CACHE = Path(os.environ.get("PYTHIA_INTRADAY_DATA", ROOT / "intraday")) / "alpaca-sip"
IS_START = np.datetime64("2001-01-01")
SPLIT = np.datetime64("2018-01-01")
BARS_FROM = (2018, 1)
YEAR_DAYS = 252
HISTORY = 252
MA_DAYS, VOL_DAYS, VOL_MED_DAYS = 200, 20, 252
STALE_MAX = 0.05             # a symbol-year with more stale opens than this is not used
FILL_GUARD = 0.05            # a 5-minute night more than 5 % away from Yahoo's is a data error

COST_BPS = {"SPY": 1.0, "QQQ": 1.0}
ETF_COST_BPS = 2.0           # IWM and the sector ETFs
STOCK_COST_BPS = 3.0
SEC_FEE = 27.80e-6           # USD per USD sold
TAF_PER_SHARE = 0.000166     # USD per share sold

# The pool before this study: fast_maker's 841 (bar 2.73, annualised over 365)
# plus W4's 46 and W3's 21 that it did not include, at the same variance.
POOL_PUBLISHED_TRIALS, POOL_PUBLISHED_SR0 = 841, 2.73
PRIOR_TRIALS = 908
TRIALS_HERE = 39
BOOT_DRAWS, BOOT_BLOCK = 4_000, 20


class DataUnavailable(RuntimeError):
    pass


def cost_bps(sym: str) -> float:
    if sym in COST_BPS:
        return COST_BPS[sym]
    return STOCK_COST_BPS if sym in STOCKS else ETF_COST_BPS


# ---------------------------------------------------------------------------
# Daily data
# ---------------------------------------------------------------------------

def yahoo_ohlc_csv(payload: dict) -> str:
    """Yahoo's chart answer as Date,Open,Close,AdjClose,Split. Open and close are split
    adjusted, AdjClose also for dividends; Split is the ratio taking effect that day."""
    try:
        r = payload["chart"]["result"][0]
        ts = r["timestamp"]
        q = r["indicators"]["quote"][0]
        adj = r["indicators"]["adjclose"][0]["adjclose"]
    except (KeyError, IndexError, TypeError) as e:
        raise DataUnavailable(f"not a Yahoo chart answer: {e}") from e
    splits = {}
    for s in ((r.get("events") or {}).get("splits") or {}).values():
        d = datetime.fromtimestamp(s["date"], timezone.utc).date().isoformat()
        if s.get("denominator"):
            splits[d] = float(s["numerator"]) / float(s["denominator"])
    rows = ["Date,Open,Close,AdjClose,Split"]
    for t, o, c, a in zip(ts, q["open"], q["close"], adj):
        if o is None or c is None or a is None or o <= 0 or c <= 0 or a <= 0:
            continue
        d = datetime.fromtimestamp(t, timezone.utc).date().isoformat()
        rows.append(f"{d},{o},{c},{a},{splits.get(d, 1.0)}")
    if len(rows) < 2:
        raise DataUnavailable("Yahoo answer without a single valid day")
    return "\n".join(rows)


def download_yahoo(sym: str, timeout: float = 30.0) -> str:
    url = YAHOO.format(sym, int(datetime.now(timezone.utc).timestamp()))
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return yahoo_ohlc_csv(json.loads(r.read().decode("utf-8", "replace")))
    except (OSError, ValueError) as e:
        raise DataUnavailable(f"{sym} (Yahoo): {e}") from e


def parse_ohlc(text: str) -> dict[str, np.ndarray]:
    lines = [ln.strip() for ln in text.strip().splitlines() if ln.strip()]
    if not lines or lines[0].lower() != "date,open,close,adjclose,split":
        raise DataUnavailable(f"not an OHLC cache file: {lines[0][:60] if lines else 'empty'}")
    d, o, c, a, s = [], [], [], [], []
    for ln in lines[1:]:
        p = ln.split(",")
        d.append(np.datetime64(p[0]))
        o.append(float(p[1]))
        c.append(float(p[2]))
        a.append(float(p[3]))
        s.append(float(p[4]))
    order = np.argsort(np.array(d, dtype="datetime64[D]"), kind="stable")
    out = {"dates": np.array(d, dtype="datetime64[D]")[order], "open": np.array(o)[order],
           "close": np.array(c)[order], "adj": np.array(a)[order], "split": np.array(s)[order]}
    keep = np.r_[True, out["dates"][1:] != out["dates"][:-1]]
    return {k: v[keep] for k, v in out.items()}


def load_csv(sym: str, refresh: bool = False, fetch=download_yahoo) -> str:
    f = CACHE / f"{sym}.csv"
    if f.exists() and not refresh:
        return f.read_text(encoding="utf-8")
    text = fetch(sym)
    parse_ohlc(text)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(text, encoding="utf-8")
    return text


@dataclass
class Panel:
    dates: np.ndarray        # (T,) sessions (SPY's calendar)
    names: list[str]
    open: np.ndarray         # (T, N) split-adjusted open, NaN when the symbol has no row
    close: np.ndarray        # split-adjusted close
    adj: np.ndarray          # split and dividend adjusted close
    raw_close: np.ndarray    # the unadjusted close (for the per-share fee)
    stale_share: dict        # sym -> {year: share of stale opens}

    @property
    def T(self) -> int:
        return len(self.dates)

    @property
    def N(self) -> int:
        return len(self.names)

    def col(self, sym: str) -> int:
        return self.names.index(sym)


def build_panel(series: dict[str, dict[str, np.ndarray]]) -> Panel:
    names = [s for s in SYMBOLS if s in series] + sorted(set(series) - set(SYMBOLS))
    if "SPY" not in series:
        raise DataUnavailable("no SPY history, no calendar")
    dates = series["SPY"]["dates"]
    T, N = len(dates), len(names)
    O, C, A, R = (np.full((T, N), np.nan) for _ in range(4))
    stale: dict[str, dict[int, float]] = {}
    for j, s in enumerate(names):
        x = series[s]
        # unadjusted close: undo every split that takes effect after the day
        later = np.cumprod(x["split"][::-1])[::-1]
        after = np.r_[later[1:], 1.0]
        raw = x["close"] * after
        idx = np.searchsorted(dates, x["dates"])
        ok = (idx < T) & (dates[np.minimum(idx, T - 1)] == x["dates"])
        O[idx[ok], j], C[idx[ok], j], A[idx[ok], j], R[idx[ok], j] = x["open"][ok], x["close"][ok], x["adj"][ok], raw[ok]
        same = np.r_[False, np.isclose(x["open"][1:], x["close"][:-1], rtol=0, atol=1e-9 * x["close"][:-1])]
        yrs = x["dates"].astype("datetime64[Y]").astype(int) + 1970
        stale[s] = {int(y): float(same[yrs == y].mean()) for y in np.unique(yrs)}
    return Panel(dates, names, O, C, A, R, stale)


def load_panel(refresh: bool = False, fetch=download_yahoo) -> Panel:
    series, errors = {}, []
    for s in SYMBOLS:
        try:
            series[s] = parse_ohlc(load_csv(s, refresh, fetch))
        except DataUnavailable as e:
            errors.append(str(e))
        if fetch is download_yahoo and (refresh or not (CACHE / f"{s}.csv").exists()):
            time.sleep(0.5)
    if errors:
        raise DataUnavailable("; ".join(errors))
    return build_panel(series)


# ---------------------------------------------------------------------------
# Returns, availability and rules. Row t is the night that ENDS at the open of t.
# ---------------------------------------------------------------------------

@dataclass
class Nights:
    night: np.ndarray        # (T, N) close t-1 -> open t, dividends included
    day: np.ndarray          # open t -> close t
    total: np.ndarray        # close t-1 -> close t
    valid: np.ndarray        # (T, N) the night may be traded and counted
    fee_sell: np.ndarray     # (T, N) SEC fee and TAF on selling 1 USD bought at the close of t-1, as a share


def nights(P: Panel) -> Nights:
    f = P.adj / P.close
    night = np.full((P.T, P.N), np.nan)
    total = np.full((P.T, P.N), np.nan)
    with np.errstate(invalid="ignore", divide="ignore"):
        night[1:] = f[1:] * P.open[1:] / P.adj[:-1] - 1
        total[1:] = P.adj[1:] / P.adj[:-1] - 1
        day = P.close / P.open - 1
    first = np.where(np.isfinite(P.adj).any(0), np.argmax(np.isfinite(P.adj), 0), P.T)
    seasoned = np.arange(P.T)[:, None] >= (first[None, :] + HISTORY)
    yrs = P.dates.astype("datetime64[Y]").astype(int) + 1970
    year_ok = np.zeros((P.T, P.N), dtype=bool)
    for j, s in enumerate(P.names):
        good = {y for y, sh in P.stale_share[s].items() if sh < STALE_MAX}
        year_ok[:, j] = np.isin(yrs, list(good))
    valid = np.isfinite(night) & np.isfinite(day) & seasoned & year_ok
    fee = np.full((P.T, P.N), np.nan)
    with np.errstate(invalid="ignore", divide="ignore"):
        fee[1:] = SEC_FEE * (1 + night[1:]) + TAF_PER_SHARE / P.raw_close[:-1]
    return Nights(night, day, total, valid, np.nan_to_num(fee))


def rolling_mean(x: np.ndarray, w: int) -> np.ndarray:
    """Trailing mean over w rows (NaN until w finite values in the window)."""
    out = np.full(x.shape, np.nan)
    v = np.nan_to_num(x)
    c = np.isfinite(x).astype(float)
    cs, cc = np.cumsum(v, 0), np.cumsum(c, 0)
    s = cs[w - 1:] - np.vstack([np.zeros((1,) + x.shape[1:]), cs[:-w]])
    n = cc[w - 1:] - np.vstack([np.zeros((1,) + x.shape[1:]), cc[:-w]])
    with np.errstate(invalid="ignore", divide="ignore"):
        out[w - 1:] = np.where(n >= w, s / np.maximum(n, 1), np.nan)
    return out


def rolling_std(x: np.ndarray, w: int) -> np.ndarray:
    m = rolling_mean(x, w)
    m2 = rolling_mean(x * x, w)
    with np.errstate(invalid="ignore"):
        return np.sqrt(np.maximum(m2 - m * m, 0) * w / (w - 1))


def rolling_median_past(x: np.ndarray, w: int) -> np.ndarray:
    """Median of the last w finite values up to and including each row (NaN with fewer than w/2)."""
    out = np.full(x.shape, np.nan)
    for j in range(x.shape[1]):
        col = x[:, j]
        for t in range(x.shape[0]):
            win = col[max(0, t - w + 1):t + 1]
            win = win[np.isfinite(win)]
            if len(win) >= w // 2:
                out[t, j] = np.median(win)
    return out


def month_position(dates: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(rank of the session in its month from 1, True on the month's last session)."""
    m = dates.astype("datetime64[M]")
    first = np.r_[True, m[1:] != m[:-1]]
    last = np.r_[m[1:] != m[:-1], True]
    rank = np.zeros(len(dates), dtype=int)
    k = 0
    for t in range(len(dates)):
        k = 1 if first[t] else k + 1
        rank[t] = k
    return rank, last


def holiday_nights(dates: np.ndarray) -> np.ndarray:
    """True for the night ending at session t when a weekday without a session lies between t-1 and t."""
    out = np.zeros(len(dates), dtype=bool)
    d = dates.astype("datetime64[D]")
    out[1:] = np.busday_count(d[:-1] + np.timedelta64(1, "D"), d[1:]) >= 1
    return out


def rule_masks(P: Panel, N: Nights) -> dict[str, np.ndarray]:
    """(T, N) bool per rule for the night ending at t, from closes up to t-1 only."""
    above = np.zeros((P.T, P.N), dtype=bool)
    ma = rolling_mean(P.adj, MA_DAYS)
    with np.errstate(invalid="ignore"):
        above[1:] = (P.adj[:-1] > ma[:-1]) & np.isfinite(ma[:-1])
    vol = rolling_std(N.total, VOL_DAYS)
    med = rolling_median_past(vol, VOL_MED_DAYS)
    calm, storm = np.zeros_like(above), np.zeros_like(above)
    with np.errstate(invalid="ignore"):
        known = np.isfinite(vol[:-1]) & np.isfinite(med[:-1])
        calm[1:] = known & (vol[:-1] < med[:-1])
        storm[1:] = known & (vol[:-1] >= med[:-1])
    rank, last = month_position(P.dates)
    tom = np.broadcast_to((last | (rank <= 3))[:, None], (P.T, P.N))
    hol = np.broadcast_to(holiday_nights(P.dates)[:, None], (P.T, P.N))
    ones = np.ones((P.T, P.N), dtype=bool)
    return dict(zip(RULES, (ones, above, calm, storm, tom.copy(), hol.copy())))


# ---------------------------------------------------------------------------
# Sleeves
# ---------------------------------------------------------------------------

def side_costs(P: Panel, mult: float = 1.0) -> np.ndarray:
    return np.array([cost_bps(s) for s in P.names]) * 1e-4 * mult


def sleeve_returns(P: Panel, N: Nights, syms: tuple[str, ...], hold: np.ndarray, cost_mult: float = 1.0,
                   night: np.ndarray | None = None, valid: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Net return of the sleeve on each session, its share of capital held overnight and
    whether it was live (had any available symbol). Each available symbol gets 1/N."""
    cols = [P.col(s) for s in syms if s in P.names]
    nt = (N.night if night is None else night)[:, cols]
    va = (N.valid if valid is None else valid)[:, cols]
    h = hold[:, cols] & va
    c = side_costs(P, cost_mult)[cols]
    net = nt - c[None, :] - (1 + nt) * c[None, :] - N.fee_sell[:, cols]
    n_av = va.sum(1)
    live = n_av > 0
    with np.errstate(invalid="ignore", divide="ignore"):
        r = np.where(live, np.where(h, np.nan_to_num(net), 0.0).sum(1) / np.maximum(n_av, 1), 0.0)
        expo = np.where(live, h.sum(1) / np.maximum(n_av, 1), 0.0)
    return r, expo, live


def hold_returns(P: Panel, N: Nights, syms: tuple[str, ...], kind: str = "total") -> np.ndarray:
    """Buy and hold (kind total) or the day session at base costs (kind day), equal weight over
    the available symbols, rebalanced daily at the return level (no cost charged for that)."""
    cols = [P.col(s) for s in syms if s in P.names]
    va = N.valid[:, cols]
    if kind == "total":
        x = N.total[:, cols]
    else:
        c = side_costs(P)[cols]
        x = N.day[:, cols] - c[None, :] - (1 + N.day[:, cols]) * (c[None, :] + SEC_FEE)
    n = va.sum(1)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(n > 0, np.where(va, np.nan_to_num(x), 0.0).sum(1) / np.maximum(n, 1), 0.0)


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------

def sharpe(x: np.ndarray, year: int = YEAR_DAYS) -> float:
    sd = x.std(ddof=1) if x.size > 1 else 0.0
    return float(x.mean() / sd * math.sqrt(year)) if sd > 0 else 0.0


def max_dd(x: np.ndarray) -> float:
    if not x.size:
        return 0.0
    eq = np.cumprod(1 + x)
    peak = np.maximum.accumulate(np.r_[1.0, eq])[1:]
    return float(1 - (eq / peak).min())


def perf(x: np.ndarray, year: int = YEAR_DAYS) -> dict:
    yrs = x.size / year
    eq = float(np.prod(1 + x)) if x.size else 1.0
    return {"sharpe": sharpe(x, year), "cagr": eq ** (1 / yrs) - 1 if yrs > 0 and eq > 0 else -1.0,
            "vol": float(x.std(ddof=1) * math.sqrt(year)) if x.size > 1 else 0.0, "max_dd": max_dd(x),
            "days": int(x.size)}


def trial_stats(x: np.ndarray) -> dict:
    sd = x.std()
    return {"sr_daily": float(x.mean() / sd) if sd > 0 else 0.0,
            "skew": float(stats.skew(x)) if sd > 0 else 0.0,
            "kurt": float(stats.kurtosis(x, fisher=False)) if sd > 0 else 3.0, "n": int(x.size)}


def published_var() -> float:
    """Variance of daily trial Sharpes implied by the published bar (annualised over 365)."""
    g = 0.5772156649
    n = POOL_PUBLISHED_TRIALS
    z = (1 - g) * stats.norm.ppf(1 - 1 / n) + g * stats.norm.ppf(1 - 1 / (n * math.e))
    return (POOL_PUBLISHED_SR0 / math.sqrt(365) / z) ** 2


def pool(mine_daily: list[float], prior_trials: int = PRIOR_TRIALS, prior_extra: list[float] | None = None) -> dict:
    """The prior pool's variance pooled with this study's daily trial Sharpes (clipped at an
    annual +-3). prior_extra: daily Sharpes of trials counted after the published pool."""
    v1, n1 = published_var(), prior_trials
    extra = np.clip(np.array(prior_extra or []), -fc.SR_CLIP / math.sqrt(YEAR_DAYS), fc.SR_CLIP / math.sqrt(YEAR_DAYS))
    x = np.clip(np.array(mine_daily), -fc.SR_CLIP / math.sqrt(YEAR_DAYS), fc.SR_CLIP / math.sqrt(YEAR_DAYS))
    allx = np.r_[extra, x]
    n2, v2 = len(allx), float(np.var(allx)) if len(allx) > 1 else 0.0
    n = n1 + n2
    v = (n1 * v1 + n2 * v2) / n
    return {"prior_trials": n1, "mine": len(x), "extra": len(extra), "n_total": n, "var": v, "mine_var": v2,
            "sr0_daily": fc._sr0(v, n)}


def deflated(x: np.ndarray, n: int, var: float) -> float:
    s = trial_stats(x)
    if 1 - s["skew"] * s["sr_daily"] + (s["kurt"] - 1) / 4 * s["sr_daily"] ** 2 <= 0:
        return 0.0
    return deflated_sharpe(s["sr_daily"], s["n"], n, var, s["skew"], s["kurt"])


def boot_index(n: int, rng: np.random.Generator, draws: int = BOOT_DRAWS, block: int = BOOT_BLOCK) -> np.ndarray:
    """Stationary bootstrap indices (expected block length `block`)."""
    idx = np.empty((draws, n), dtype=np.int64)
    idx[:, 0] = rng.integers(0, n, draws)
    jump = rng.random((draws, n)) < 1 / block
    fresh = rng.integers(0, n, (draws, n))
    for i in range(1, n):
        idx[:, i] = np.where(jump[:, i], fresh[:, i], (idx[:, i - 1] + 1) % n)
    return idx


def boot_sharpes(x: np.ndarray, idx: np.ndarray, year: int = YEAR_DAYS) -> np.ndarray:
    s = x[idx]
    sd = s.std(1)
    return np.where(sd > 0, s.mean(1) / np.where(sd > 0, sd, 1) * math.sqrt(year), 0.0)


# ---------------------------------------------------------------------------
# 5-minute bars (fill checks)
# ---------------------------------------------------------------------------

def bar_points(df) -> dict[str, np.ndarray]:
    """Per New York date: open of the first bar, close of the first bar, close of the last bar
    (15:55 on a full day) and close of the bar two before it (15:45, i.e. the 15:50 price)."""
    import polars as pl
    g = (df.sort("date", "bar").group_by("date", maintain_order=True)
         .agg(first=pl.col("bar").first(), o0=pl.col("open").first(), c0=pl.col("close").first(),
              last=pl.col("bar").last(), c_last=pl.col("close").last(),
              c_m2=pl.col("close").filter(pl.col("bar") <= pl.col("bar").max() - 2).last())
         .filter(pl.col("first") == 0))
    return {"dates": g["date"].to_numpy().astype("datetime64[D]"), "o0": g["o0"].to_numpy(),
            "c0": g["c0"].to_numpy(), "c_last": g["c_last"].to_numpy(), "c_m2": g["c_m2"].to_numpy()}


def load_bars(symbols: tuple[str, ...], source: str = "cache", today: datetime | None = None) -> tuple[dict, list[str]]:
    """{sym: bar_points} from the W4 cache; with source alpaca, missing months (and the running
    one) are fetched with the keys from the environment and cached the same way."""
    import polars as pl
    from . import intraday_equities as ie
    today = today or datetime.now(timezone.utc)
    now_m = (today.year, today.month)
    headers = ie.alpaca_keys() if source == "alpaca" else None
    if source == "alpaca" and headers is None:
        raise DataUnavailable("APCA_API_KEY_ID / APCA_API_SECRET_KEY are not set")
    out, missing = {}, []
    for s in symbols:
        parts = []
        for (y, m) in ie.months(BARS_FROM, now_m):
            f = BARS_CACHE / s / f"{y}-{m:02d}.parquet"
            if f.exists() and not (headers and (y, m) == now_m):
                parts.append(pl.read_parquet(f))
            elif headers:
                df = ie.alpaca_frame(ie.alpaca_month_json(s.replace("-", "."), y, m, "sip", headers))
                f.parent.mkdir(parents=True, exist_ok=True)
                df.write_parquet(f)
                parts.append(df)
                time.sleep(0.32)
        if not parts:
            missing.append(s)
            continue
        df = pl.concat(parts).unique(["date", "bar"], keep="last")
        if df.is_empty():
            missing.append(s)
            continue
        out[s] = bar_points(df)
    return out, missing


def fill_nights(P: Panel, N: Nights, bars: dict) -> dict:
    """Overnight returns under the fill models, on the panel's grid (NaN where the bars miss or
    disagree with Yahoo by more than FILL_GUARD), plus the agreement of the two sources."""
    shape = (P.T, P.N)
    out = {k: np.full(shape, np.nan) for k in ("F1", "F2")}
    agree = {}
    for s, b in bars.items():
        if s not in P.names:
            continue
        j = P.col(s)
        idx = np.searchsorted(P.dates, b["dates"])
        ok = (idx < P.T) & (P.dates[np.minimum(idx, P.T - 1)] == b["dates"])
        o0, c0, cl, cm2 = (np.full(P.T, np.nan) for _ in range(4))
        o0[idx[ok]], c0[idx[ok]], cl[idx[ok]], cm2[idx[ok]] = b["o0"][ok], b["c0"][ok], b["c_last"][ok], b["c_m2"][ok]
        with np.errstate(invalid="ignore", divide="ignore"):
            f1 = np.r_[np.nan, c0[1:] / cm2[:-1] - 1]
            f2 = np.r_[np.nan, o0[1:] / cl[:-1] - 1]
        y = N.night[:, j]
        both = np.isfinite(f1) & np.isfinite(f2) & np.isfinite(y) & N.valid[:, j]
        bad = both & ((np.abs(f2 - y) > FILL_GUARD) | (np.abs(f1 - y) > FILL_GUARD))
        good = both & ~bad
        for k, v in (("F1", f1), ("F2", f2)):
            out[k][good, j] = v[good]
        if good.sum() > 20:
            agree[s] = {"nights": int(good.sum()), "dropped": int(bad.sum()),
                        "corr_f2": float(np.corrcoef(f2[good], y[good])[0, 1]),
                        "f2_minus_yahoo_bps": float((f2[good] - y[good]).mean() * 1e4),
                        "f1_minus_yahoo_bps": float((f1[good] - y[good]).mean() * 1e4)}
    return {"nights": out, "agree": agree}


# ---------------------------------------------------------------------------
# The study
# ---------------------------------------------------------------------------

def grid(P: Panel, N: Nights, masks: dict) -> list[dict]:
    rows = []
    for su, syms in SLEEVES.items():
        if not any(s in P.names for s in syms):
            continue
        for ru in RULES:
            r, expo, live = sleeve_returns(P, N, syms, masks[ru])
            rs, _, _ = sleeve_returns(P, N, syms, masks[ru], cost_mult=2.0)
            rows.append({"sleeve": su, "rule": ru, "name": f"{su} · {ru}", "r": r, "r_stress": rs, "expo": expo,
                         "live": live})
    return rows


def windows(P: Panel, live: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    ins = live & (P.dates >= IS_START) & (P.dates < SPLIT)
    oos = live & (P.dates >= SPLIT)
    return ins, oos


def pick_series(P: Panel | None = None) -> tuple[np.ndarray, np.ndarray, str]:
    """(dates, net returns at base costs, name) of the pre-registered pick, for book_portfolio."""
    P = P or load_panel()
    N = nights(P)
    rows = grid(P, N, rule_masks(P, N))
    for r in rows:
        ins, _ = windows(P, r["live"])
        r["is_sharpe"] = sharpe(r["r"][ins])
    pk = max(rows, key=lambda r: r["is_sharpe"])
    return P.dates, pk["r"], pk["name"]


def report_dir() -> Path:
    from ..report import REPORTS
    return REPORTS / NAME


def spy_total(P: Panel, N: Nights) -> np.ndarray:
    return np.nan_to_num(N.total[:, P.col("SPY")])


def run(P: Panel, bars: dict, missing_bars: list[str], seed: int = 20261015) -> dict:
    N = nights(P)
    masks = rule_masks(P, N)
    rows = grid(P, N, masks)
    rng = np.random.default_rng(seed)
    spy = spy_total(P, N)
    for r in rows:
        ins, oos = windows(P, r["live"])
        r["is_sharpe"] = sharpe(r["r"][ins])
        po = perf(r["r"][oos])
        r.update(oos_sharpe=po["sharpe"], oos_cagr=po["cagr"], oos_vol=po["vol"], oos_dd=po["max_dd"],
                 oos_sharpe_stress=sharpe(r["r_stress"][oos]), oos_expo=float(r["expo"][oos].mean()),
                 is_from=str(P.dates[ins][0]) if ins.any() else None)
    pk = max(rows, key=lambda r: r["is_sharpe"])
    ins_p, oos_p = windows(P, pk["live"])

    # Fill checks for the pick, on the symbols with bars.
    fills = fill_nights(P, N, bars)
    syms = SLEEVES[pk["sleeve"]]
    have = tuple(s for s in syms if s in bars)
    fill = {"symbols": list(have), "missing": [s for s in syms if s not in bars]}
    extra_trials = []
    if have:
        fv = np.isfinite(fills["nights"]["F2"]) & N.valid
        base_f, _, live_f = sleeve_returns(P, N, have, masks[pk["rule"]], valid=fv)
        m = live_f & (P.dates >= SPLIT)
        fill["window"] = [str(P.dates[m][0]), str(P.dates[m][-1])] if m.any() else None
        fill["yahoo_same_nights"] = perf(base_f[m])
        for k in ("F1", "F2"):
            x, _, _ = sleeve_returns(P, N, have, masks[pk["rule"]], night=np.nan_to_num(fills["nights"][k]), valid=fv)
            fill[k] = perf(x[m])
            extra_trials.append((f"{pk['name']} · fill {k}", x[m]))
    else:
        fill["window"] = None
    extra_trials.append((f"{pk['name']} · stress costs", pk["r_stress"][oos_p]))

    # Deflation over the pool: the 36 grid trials and the 3 checks.
    mine = [trial_stats(r["r"][windows(P, r["live"])[1]])["sr_daily"] for r in rows]
    mine += [trial_stats(x)["sr_daily"] for _, x in extra_trials]
    assert len(mine) == TRIALS_HERE or not have, len(mine)
    pl_ = pool(mine)
    for r in rows:
        r["deflated_p"] = deflated(r["r"][windows(P, r["live"])[1]], pl_["n_total"], pl_["var"])

    # References.
    refs = {}
    for su in dict.fromkeys(r["sleeve"] for r in rows):
        sy = SLEEVES[su]
        cols = [P.col(s) for s in sy if s in P.names]
        va = N.valid[:, cols]
        n_av = np.maximum(va.sum(1), 1)

        def gross(x: np.ndarray) -> np.ndarray:
            return np.where(va, np.nan_to_num(x[:, cols]), 0.0).sum(1) / n_av

        bh = hold_returns(P, N, sy, "total")
        dy = hold_returns(P, N, sy, "day")
        live = next(r["live"] for r in rows if r["sleeve"] == su)
        _, o = windows(P, live)
        refs[su] = {"buy and hold": perf(bh[o]), "day session": perf(dy[o]),
                    "oos_from": str(P.dates[o][0]) if o.any() else None,
                    "night_gross_cagr": perf(gross(N.night)[o])["cagr"], "day_gross_cagr": perf(gross(N.day)[o])["cagr"],
                    "series": bh}
    spy_o = spy[oos_p]
    own_bh = refs[pk["sleeve"]]["series"][oos_p]
    x = pk["r"][oos_p]
    idx = boot_index(len(x), rng)
    bs = boot_sharpes(x, idx)
    bd = bs - boot_sharpes(spy_o, idx)
    yr = P.dates.astype("datetime64[Y]").astype(int) + 1970
    per_year = {}
    for y in np.unique(yr[oos_p]):
        m = oos_p & (yr == y)
        per_year[int(y)] = {"pick": float(np.prod(1 + pk["r"][m]) - 1), "pick_sharpe": sharpe(pk["r"][m]),
                            "SPY": float(np.prod(1 + spy[m]) - 1), "SPY_sharpe": sharpe(spy[m])}
    spy_p = perf(spy_o)
    gates = {
        "Sharpe > 0 at base and stress costs": pk["oos_sharpe"] > 0 and pk["oos_sharpe_stress"] > 0,
        "Sharpe above SPY's and its own sleeve's buy and hold": pk["oos_sharpe"] > spy_p["sharpe"]
        and pk["oos_sharpe"] > sharpe(own_bh),
        "drawdown below SPY's": pk["oos_dd"] < spy_p["max_dd"],
        "Sharpe > 0 with fill models F1 and F2": bool(have) and fill["F1"]["sharpe"] > 0 and fill["F2"]["sharpe"] > 0,
        "deflated p > 0.95": pk["deflated_p"] > 0.95,
        "bootstrap 5 % of Sharpe above 0": float(np.quantile(bs, 0.05)) > 0,
    }
    stale = {s: {y: v for y, v in d.items() if v >= STALE_MAX} for s, d in P.stale_share.items()}
    return {
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "data": {"first": str(P.dates[0]), "last": str(P.dates[-1]), "symbols": P.names,
                 "first_close": {s: str(P.dates[np.argmax(np.isfinite(P.adj[:, j]))]) for j, s in enumerate(P.names)},
                 "stale_years": {s: v for s, v in stale.items() if v}},
        "rows": [{k: v for k, v in r.items() if k not in ("r", "r_stress", "expo", "live")} for r in rows],
        "pick": pk["name"], "pick_row": {k: v for k, v in pk.items() if k not in ("r", "r_stress", "expo", "live")},
        "oos_window": [str(P.dates[oos_p][0]), str(P.dates[oos_p][-1])],
        "pick_oos": perf(x), "spy_oos": spy_p, "own_bh_oos": perf(own_bh),
        "corr_with_spy": float(np.corrcoef(x, spy_o)[0, 1]),
        "references": {k: {kk: vv for kk, vv in v.items() if kk != "series"} for k, v in refs.items()},
        "bootstrap": {"p05": float(np.quantile(bs, 0.05)), "p95": float(np.quantile(bs, 0.95)),
                      "diff_spy_p05": float(np.quantile(bd, 0.05)), "diff_spy_p95": float(np.quantile(bd, 0.95)),
                      "share_above_0": float((bs > 0).mean())},
        "per_year": per_year, "fill": fill, "fill_agreement": fills["agree"], "missing_bars": missing_bars,
        "extra_trials": [n for n, _ in extra_trials], "pool": pl_, "gates": gates, "passes": all(gates.values()),
    }


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def pct(v: float | None) -> str:
    return "-" if v is None else f"{v * 100:.1f} %"


def markdown(res: dict) -> str:
    from ..report import table
    p, s, o = res["pick_oos"], res["spy_oos"], res["own_bh_oos"]
    pr = res["pick_row"]
    pool_ = res["pool"]
    sr0 = pool_["sr0_daily"] * math.sqrt(YEAR_DAYS)
    failed = [g for g, ok in res["gates"].items() if not ok]
    verdict = ("**Verdict: the pick passes every gate; a paper book is proposed below (not deployed).**"
               if res["passes"] else
               f"**Verdict: fails ({len(failed)} of 6 gates), no paper book.**")
    lines = [
        f"## Results (generated {res['generated'][:10]}, data {res['data']['first']} to {res['data']['last']})", "",
        verdict + f" The in-sample pick is {res['pick']} (in-sample Sharpe {pr['is_sharpe']:.2f} from "
        f"{pr['is_from']}). Out of sample ({res['oos_window'][0]} to {res['oos_window'][1]}) it makes Sharpe "
        f"{p['sharpe']:.2f}, {pct(p['cagr'])} a year, drawdown {pct(p['max_dd'])} at base costs "
        f"({pr['oos_sharpe_stress']:.2f} at stress), held {pct(pr['oos_expo'])} of the nights; SPY bought and held "
        f"{s['sharpe']:.2f}, {pct(s['cagr'])}, drawdown {pct(s['max_dd'])}; its own sleeve held {o['sharpe']:.2f}, "
        f"{pct(o['cagr'])}, drawdown {pct(o['max_dd'])}. Deflated p {pr['deflated_p']:.2f} over {pool_['n_total']} "
        f"trials (noise bar about {sr0:.2f} on 252 sessions).", ""]
    if failed:
        lines += ["Failed: " + "; ".join(failed) + ".", ""]

    lines += ["### Where the return comes from (out of sample, gross, equal weight)", "",
              "Each sleeve's nights and days before any cost, against holding it, and the day session at base costs.", ""]
    ref_rows = []
    for su, v in res["references"].items():
        ref_rows.append({"sleeve": su, "from": v["oos_from"], "nights, gross CAGR": pct(v["night_gross_cagr"]),
                         "days, gross CAGR": pct(v["day_gross_cagr"]),
                         "buy and hold Sharpe": v["buy and hold"]["sharpe"], "buy and hold CAGR": pct(v["buy and hold"]["cagr"]),
                         "buy and hold DD": pct(v["buy and hold"]["max_dd"]),
                         "day session net Sharpe": v["day session"]["sharpe"]})
    lines += [table(ref_rows, list(ref_rows[0])), ""]

    lines += ["### The 36 trials", "",
              "Sharpe over 252 sessions, net of spread, SEC fee and TAF; stress doubles the spread.", ""]
    grid_rows = [{"variant": r["name"], "IS Sharpe": r["is_sharpe"], "OOS Sharpe": r["oos_sharpe"],
                  "OOS stress": r["oos_sharpe_stress"], "OOS CAGR": pct(r["oos_cagr"]), "OOS DD": pct(r["oos_dd"]),
                  "nights held": pct(r["oos_expo"]), "deflated p": r["deflated_p"]} for r in res["rows"]]
    lines += [table(grid_rows, list(grid_rows[0])), ""]
    pos = sum(r["oos_sharpe"] > 0 for r in res["rows"])
    beat = sum(r["oos_sharpe"] > s["sharpe"] for r in res["rows"])
    lines += [f"{pos} of 36 are positive out of sample at base costs; {beat} beat SPY's buy and hold Sharpe.", ""]

    f = res["fill"]
    lines += ["### Can Alpaca fill it? The pick on 5-minute bars", ""]
    if f.get("window"):
        rows = [{"fill": "official open and close (Yahoo, the backtest)", **f["yahoo_same_nights"]},
                {"fill": "F1: buy at 15:50, sell at 09:35", **f["F1"]},
                {"fill": "F2: buy at the last trade before 16:00, sell at the first trade", **f["F2"]}]
        for r in rows:
            r["cagr"], r["max_dd"] = pct(r["cagr"]), pct(r["max_dd"])
        lines += [f"Symbols with bars: {', '.join(f['symbols'])}"
                  + (f"; missing (server run needed): {', '.join(f['missing'])}" if f["missing"] else "")
                  + f". Window {f['window'][0]} to {f['window'][1]}, base costs.", "",
                  table(rows, ["fill", "sharpe", "cagr", "max_dd", "days"]), ""]
    else:
        lines += [f"No 5-minute bars for {', '.join(f['missing'])} on this machine; the fill gate fails until the "
                  "server run (`--source alpaca`) has them.", ""]
    ag = res["fill_agreement"]
    if ag:
        rows = [{"symbol": k, **v} for k, v in ag.items()]
        lines += ["The fills against the official prices, per symbol (mean per night, 2018 on; a night more than "
                  f"{FILL_GUARD:.0%} away from Yahoo's is dropped as a data error):", "",
                  table(rows, ["symbol", "nights", "dropped", "corr_f2", "f2_minus_yahoo_bps",
                               "f1_minus_yahoo_bps"]), ""]

    b = res["bootstrap"]
    lines += ["### Pick: bootstrap and years", "",
              f"Stationary bootstrap (block {BOOT_BLOCK}, {BOOT_DRAWS} draws): Sharpe 90 % band {b['p05']:.2f} to "
              f"{b['p95']:.2f}, {b['share_above_0']:.0%} of draws above 0; minus SPY's {b['diff_spy_p05']:.2f} to "
              f"{b['diff_spy_p95']:.2f}. Correlation with SPY's daily return {res['corr_with_spy']:.2f}.", ""]
    yrows = [{"year": y, "pick": pct(v["pick"]), "pick Sharpe": v["pick_sharpe"], "SPY": pct(v["SPY"]),
              "SPY Sharpe": v["SPY_sharpe"]} for y, v in res["per_year"].items()]
    lines += [table(yrows, list(yrows[0])), ""]
    lines += ["### Gates", ""] + [f"- {'pass' if ok else 'FAIL'}: {g}" for g, ok in res["gates"].items()] + [""]

    lines += ["### Deflation pool", "",
              f"{pool_['prior_trials']} earlier trials at the variance backed out of the published bar "
              f"({POOL_PUBLISHED_SR0} over {POOL_PUBLISHED_TRIALS}) and this study's {pool_['mine']} (out of sample, "
              f"clipped at an annual +-3): {pool_['n_total']} trials. Equity Sharpes are per session, the crypto "
              f"pool's per calendar day; pooling them is an approximation.", "",
              "Counted beyond the grid: " + "; ".join(res["extra_trials"]) + ".", ""]
    st = res["data"]["stale_years"]
    lines += ["### Data", "",
              f"First valid close per symbol: " + ", ".join(f"{k} {v}" for k, v in res["data"]["first_close"].items()) + ".",
              ("Years left out for stale opens (share of opens equal to the previous close at or above 5 %): "
               + "; ".join(f"{k} " + ", ".join(str(y) for y in v) for k, v in st.items()) + ".") if st else
              "No symbol-year has 5 % or more stale opens.",
              "Missing 5-minute bars: " + (", ".join(res["missing_bars"]) or "none") + ".", ""]
    return "\n".join(lines)


def write(res: dict) -> str:
    from .. import report
    path = fc.RESULTS_DIR / f"{NAME}.md"
    try:
        head = path.read_text(encoding="utf-8").split(MARKER)[0]
    except OSError:
        head = f"# {NAME}\n\n"
    body = markdown(res)
    md = head + MARKER + "\n\n" + body
    path.write_text(md, encoding="utf-8")
    report.write(NAME, body, res)
    return md


def main() -> int:
    source = "alpaca" if "--source" in sys.argv and sys.argv[sys.argv.index("--source") + 1] == "alpaca" else "cache"
    try:
        P = load_panel(refresh="--refresh" in sys.argv)
    except DataUnavailable as e:
        print(f"{NAME}: no data, nothing judged: {e}", file=sys.stderr)
        return 2
    try:
        bars, missing = load_bars(SYMBOLS, source)
    except DataUnavailable as e:
        print(f"{NAME}: 5-minute bars: {e}", file=sys.stderr)
        return 2
    write(run(P, bars, missing))
    return 0


if __name__ == "__main__":
    sys.exit(main())
