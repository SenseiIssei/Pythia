"""Shared ground for the strategy-family sweep (fam_*.py, run together by families.py).

One daily panel of every USDT pair Binance ever listed (hist/universe.json,
delisted ones included), with the symbol segmentation of picks.py: a reused
or redenominated ticker becomes a separate coin, so no return bridges two
different assets. One simulator for every family, one way of measuring, one
place where variants are counted.

Timing convention (the same as tsmom.py): day t is the UTC day starting at
`days[t]`; its close is the last hourly close of that day. A weight decided at
the close of day t earns the return of day t+1. Turnover traded at the close
of day t is charged against the return of day t+1.

Costs: every family reports net at 15 bps (Binance taker plus half-spread)
and at 41 bps (Kraken taker plus half-spread) per unit of one-way turnover.
Short legs are USD-M perpetuals: a coin can be shorted on day t only if its
perpetual traded that day, and a short receives (or pays) the real funding.
The short leg is priced off spot closes (basis ignored).

Delisted coins: a position in a coin whose series ends is closed at its last
close, and the exit is charged. In reality the last hours before a delisting
are usually worse than the last close, so this flatters longs in dying coins
and penalises shorts in them a little.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import polars as pl
from scipy import stats

from ..data import HOUR_US, ROOT
from ..metrics import deflated_sharpe

DAY_US = 24 * HOUR_US
SPLIT = int(datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp() * 1e6)
IS_START = int(datetime(2020, 8, 1, tzinfo=timezone.utc).timestamp() * 1e6)
COSTS = {"15bps": 0.0015, "41bps": 0.0041}
MIN_AGE_D = 60
MIN_ADV_USD = 1_000_000

OUT = Path(os.environ.get("PYTHIA_AGENT_OUT", str(ROOT / "agent-strategies")))
RESULTS_DIR = Path(__file__).resolve().parents[2] / "results"

# Not crypto risk: stablecoins and pegged dollars, gold, wrapped or staked
# duplicates of BTC, ETH and SOL. Tokenised stocks (the "...BUSDT" listings
# from 2026-06 on) are dropped by date below.
EXCLUDE = {
    "USDSUSDT", "USDSBUSDT", "USDSOLDUSDT", "FRAXUSDT", "KGSTUSDT", "PAXGUSDT", "XAUTUSDT",
    "WBTCUSDT", "WBETHUSDT", "BETHUSDT", "BNSOLUSDT",
}
STOCK_TOKENS_FROM = "2026-06"


def _is_stock_token(symbol: str) -> bool:
    if not symbol.endswith("BUSDT") or symbol in {"BNBUSDT"}:
        return False
    d = ROOT / "hist" / "binance_spot" / "klines_1h" / f"symbol={symbol}"
    files = sorted(d.glob("*.parquet"))
    return bool(files) and files[0].stem >= STOCK_TOKENS_FROM


def base_of(name: str) -> str:
    """BTCUSDT -> BTC, LUNAUSDT~0 -> LUNA."""
    return name.split("~")[0][:-4]


# ---------------------------------------------------------------------------
# The panel
# ---------------------------------------------------------------------------

def build_daily_panel(fresh: bool = False) -> pl.DataFrame:
    """Long frame (day, symbol, close, high, low, rv, qv, n), one row per traded day and segment."""
    cache = OUT / "cache" / "daily_panel.parquet"
    if cache.exists() and not fresh:
        return pl.read_parquet(cache)
    from .picks import daily_from_hourly, hourly_segments
    syms = json.loads((ROOT / "hist" / "universe.json").read_text(encoding="utf-8"))
    frames = []
    for i, s in enumerate(syms):
        if s in EXCLUDE or not s.isascii() or _is_stock_token(s):
            continue
        segs = hourly_segments(s)
        for j, seg in enumerate(segs):
            name = s if j == len(segs) - 1 else f"{s}~{j}"
            d = daily_from_hourly(seg, name)
            if d.height < 30:
                continue
            frames.append(d.select("day", "symbol", "close", "high", "low", "rv", "qv", "n"))
        if i % 100 == 0:
            print(f"  panel {i}/{len(syms)}", flush=True)
    p = pl.concat(frames, how="vertical_relaxed").sort(["symbol", "day"])
    cache.parent.mkdir(parents=True, exist_ok=True)
    p.write_parquet(cache)
    return p


def _perp_daily(fresh: bool = False) -> pl.DataFrame:
    """(day, base, funding, perp_qv): the largest USDT perpetual of each base per day."""
    cache = OUT / "cache" / "perp_daily.parquet"
    if cache.exists() and not fresh:
        return pl.read_parquet(cache)
    from .picks_ls import perp_panel
    pp = perp_panel()
    out = (pp.sort("qv", descending=True).group_by(["day", "base"]).first()
           .select("day", "base", "funding", perp_qv="qv").sort(["base", "day"]))
    cache.parent.mkdir(parents=True, exist_ok=True)
    out.write_parquet(cache)
    return out


def _oi_daily(fresh: bool = False) -> pl.DataFrame:
    """(day, base, oi_usd): open interest at the end of each day, for the coins with metrics."""
    cache = OUT / "cache" / "oi_daily.parquet"
    if cache.exists() and not fresh:
        return pl.read_parquet(cache)
    frames = []
    for d in sorted((ROOT / "hist" / "binance_um" / "metrics").glob("symbol=*")):
        sym = d.name.split("=", 1)[1]
        files = sorted(d.glob("*.parquet"))
        if not files:
            continue
        m = pl.concat([pl.read_parquet(f, columns=["ts_us", "sum_open_interest_value"]) for f in files],
                      how="vertical_relaxed").unique("ts_us").sort("ts_us")
        base = "PEPE" if sym == "1000PEPEUSDT" else sym[:-4]
        frames.append(m.with_columns(day=(pl.col("ts_us") // DAY_US) * DAY_US)
                      .group_by("day").agg(oi_usd=pl.col("sum_open_interest_value").last())
                      .with_columns(base=pl.lit(base)))
    out = pl.concat(frames).sort(["base", "day"])
    out.write_parquet(cache)
    return out


def rolling(a: np.ndarray, w: int, min_obs: int, how: str = "mean") -> np.ndarray:
    """Column-wise trailing mean or sum over w rows (row t included), ignoring NaN."""
    v, c = np.nan_to_num(a), np.isfinite(a).astype(float)
    cs, cc = np.cumsum(v, 0), np.cumsum(c, 0)
    pad = np.zeros((w,) + a.shape[1:])
    s = cs - np.concatenate([pad, cs[:-w]])
    n = cc - np.concatenate([pad, cc[:-w]])
    with np.errstate(invalid="ignore", divide="ignore"):
        if how == "sum":
            return np.where(n >= min_obs, s, np.nan)
        return np.where(n >= min_obs, s / np.maximum(n, 1), np.nan)


def rolling_extreme(a: np.ndarray, w: int, how: str = "max") -> np.ndarray:
    """Trailing max or min over the w rows BEFORE row t (row t excluded), NaN-aware."""
    T = a.shape[0]
    out = np.full_like(a, np.nan)
    f = np.fmax if how == "max" else np.fmin
    acc = np.full_like(a, np.nan)
    # Simple doubling would be faster; w is at most a few hundred and N small here.
    for k in range(1, w + 1):
        sh = np.full_like(a, np.nan)
        sh[k:] = a[:-k]
        acc = f(acc, sh)
    out[:] = acc
    out[:w] = np.nan
    return out


@dataclass
class Panel:
    days: np.ndarray            # (T,) day start, us
    names: list[str]            # (N,) segment names
    bases: list[str]
    close: np.ndarray           # raw close, NaN on days without a bar
    px: np.ndarray              # close forward-filled inside the segment's life, NaN outside
    high: np.ndarray
    low: np.ndarray
    ret: np.ndarray             # px[t] / px[t-1] - 1 inside the life, NaN outside
    alive: np.ndarray           # bool, inside [first, last] bar of the segment
    traded: np.ndarray          # bool, a bar exists on day t
    age: np.ndarray             # days since the first bar
    adv28: np.ndarray           # trailing 28-day mean quote volume
    sigma: np.ndarray           # daily vol from the last 30 days of realised variance
    eligible: np.ndarray        # alive, traded today, 60 days old, 1 M USD a day
    perp_ok: np.ndarray         # a USDT perpetual on the same base traded that day
    funding: np.ndarray         # funding rate summed over day t (0 where none)
    btc_on: np.ndarray          # BTC close above its 200-day average, known at the close
    btc: int                    # column of BTCUSDT
    extra: dict = field(default_factory=dict)

    @property
    def T(self) -> int:
        return len(self.days)

    @property
    def N(self) -> int:
        return len(self.names)

    def col(self, name: str) -> int:
        return self.names.index(name)

    def top_liquid(self, n: int, need_perp: bool = False) -> np.ndarray:
        """Bool (T, N): the n eligible coins with the highest 28-day volume each day."""
        ok = self.eligible & (self.perp_ok if need_perp else True)
        score = np.where(ok, self.adv28, -np.inf)
        rank = np.argsort(np.argsort(-score, axis=1), axis=1)
        return ok & (rank < n)


_PANEL: Panel | None = None


def load_panel(fresh: bool = False) -> Panel:
    global _PANEL
    if _PANEL is not None and not fresh:
        return _PANEL
    p = build_daily_panel(fresh)
    names = sorted(p["symbol"].unique().to_list())
    days = np.arange(p["day"].min(), p["day"].max() + DAY_US, DAY_US, dtype=np.int64)
    di = {int(d): i for i, d in enumerate(days)}
    ni = {n: j for j, n in enumerate(names)}
    T, N = len(days), len(names)
    rows = np.array([di[int(d)] for d in p["day"].to_numpy()])
    cols = np.array([ni[s] for s in p["symbol"].to_list()])

    def mat(c: str) -> np.ndarray:
        m = np.full((T, N), np.nan)
        m[rows, cols] = p[c].to_numpy().astype(float)
        return m

    close, high, low, rv, qv = mat("close"), mat("high"), mat("low"), mat("rv"), mat("qv")
    traded = np.isfinite(close)
    idx = np.arange(T)[:, None]
    first = np.where(traded.any(0), np.argmax(traded, 0), T)
    last = np.where(traded.any(0), T - 1 - np.argmax(traded[::-1], 0), -1)
    alive = (idx >= first[None, :]) & (idx <= last[None, :])
    fidx = np.where(traded, idx, 0)
    fidx = np.maximum.accumulate(fidx, axis=0)
    px = np.where(alive, close[fidx, np.arange(N)[None, :]], np.nan)
    ret = np.full((T, N), np.nan)
    with np.errstate(invalid="ignore", divide="ignore"):
        ret[1:] = np.where(alive[1:] & alive[:-1], px[1:] / px[:-1] - 1, np.nan)
    age = np.where(alive, idx - first[None, :], -1)
    adv28 = np.where(alive, rolling(np.where(alive, np.nan_to_num(qv), np.nan), 28, 20), np.nan)
    sigma = np.sqrt(rolling(rv, 30, 20))
    eligible = alive & traded & (age >= MIN_AGE_D) & (np.nan_to_num(adv28) >= MIN_ADV_USD)

    bases = [base_of(n) for n in names]
    perp = _perp_daily()
    perp = perp.filter(pl.col("day").is_in(days.tolist()))
    pbase = {}
    for j, b in enumerate(bases):
        pbase.setdefault(b, []).append(j)
    perp_ok = np.zeros((T, N), dtype=bool)
    funding = np.zeros((T, N))
    for d, b, f in zip(perp["day"].to_numpy(), perp["base"].to_list(), perp["funding"].to_numpy()):
        for j in pbase.get(b, ()):
            t = di.get(int(d))
            if t is not None and alive[t, j]:
                perp_ok[t, j] = True
                funding[t, j] = 0.0 if not np.isfinite(f) else f

    btc = ni["BTCUSDT"]
    bpx = px[:, btc]
    ma200 = rolling(bpx[:, None], 200, 200)[:, 0]
    btc_on = np.nan_to_num(bpx > ma200, nan=0.0).astype(bool)

    _PANEL = Panel(days, names, bases, close, px, high, low, ret, alive, traded, age, adv28, sigma,
                   eligible, perp_ok, funding, btc_on, btc, extra={"qv": qv, "rv": rv, "last": last,
                                                                   "first": first})
    return _PANEL


def oi_matrix(P: Panel) -> np.ndarray:
    """Open interest in USD at the end of each day, (T, N), NaN where there is none."""
    oi = _oi_daily()
    di = {int(d): i for i, d in enumerate(P.days)}
    m = np.full((P.T, P.N), np.nan)
    for b, g in oi.group_by("base"):
        b = b[0]
        cols = [j for j, x in enumerate(P.bases) if x == b and "~" not in P.names[j]]
        for d, v in zip(g["day"].to_numpy(), g["oi_usd"].to_numpy()):
            t = di.get(int(d))
            if t is not None:
                for j in cols:
                    m[t, j] = v
    return m


# ---------------------------------------------------------------------------
# One simulator
# ---------------------------------------------------------------------------

@dataclass
class Result:
    family: str
    sub: str          # sub-family; the in-sample pick is made per sub-family
    name: str
    gross: np.ndarray     # (T,) return earned on day t, before costs
    turnover: np.ndarray  # (T,) one-way turnover traded at the close of day t
    long_expo: np.ndarray
    short_expo: np.ndarray
    benchmark: str = "ew"     # "ew" equal-weight universe or "btc"
    spot_only: bool = True    # long-only spot: executable by the engine as lab-targets

    def net(self, cost: float) -> np.ndarray:
        return self.gross - cost * np.r_[0.0, self.turnover[:-1]]


def simulate(P: Panel, W: np.ndarray, rebalance: np.ndarray | None = None, start: int = 0,
             legs: dict | None = None) -> tuple:
    """Hold target weights W[t] from the close of day t.

    W: (T, N). Positive weights are spot longs, negative weights perpetual
    shorts. NaN in a rebalance row means "leave this coin as it is". Rows where
    `rebalance` is False are not traded at all; positions drift with prices.
    Returns (gross, turnover, long_expo, short_expo), each (T,). If `legs` is a
    dict, it is filled with the daily price return of the long leg, of the
    short leg, and the funding, which add up to gross.
    """
    if legs is not None:
        for k in ("long", "short", "funding"):
            legs[k] = np.zeros(W.shape[0])
    T, N = W.shape
    if rebalance is None:
        rebalance = np.ones(T, dtype=bool)
    w = np.zeros(N)
    gross, tov, le, se = (np.zeros(T) for _ in range(4))
    for t in range(start, T - 1):
        if rebalance[t]:
            tgt = W[t]
            tgt = np.where(np.isnan(tgt), w, tgt)
            # Only coins that trade today can be bought; shorts need a live perpetual.
            tgt = np.where(P.traded[t] | (tgt == w), tgt, w)
            # No perpetual today: no new or resized short, and an open one is closed.
            tgt = np.where((tgt < 0) & ~P.perp_ok[t], 0.0, tgt)
            tov[t] += np.abs(tgt - w).sum()
            w = tgt
        r = np.nan_to_num(P.ret[t + 1])
        f = P.funding[t + 1]
        g = float(np.dot(w, r) + np.dot(np.where(w < 0, -w, 0.0), f))
        gross[t + 1] = g
        if legs is not None:
            legs["long"][t + 1] = float(np.dot(np.where(w > 0, w, 0.0), r))
            legs["short"][t + 1] = float(np.dot(np.where(w < 0, w, 0.0), r))
            legs["funding"][t + 1] = float(np.dot(np.where(w < 0, -w, 0.0), f))
        le[t] = w[w > 0].sum()
        se[t] = -w[w < 0].sum()
        if 1 + g > 0:
            w = w * (1 + r) / (1 + g)
        else:
            w = np.zeros(N)
        # A coin whose series ended at t is closed at its last close.
        dead = (w != 0) & ~P.alive[t + 1]
        if dead.any():
            tov[t + 1] += np.abs(w[dead]).sum()
            w[dead] = 0.0
    return gross, tov, le, se


def run(P: Panel, family: str, sub: str, name: str, W: np.ndarray, rebalance=None, start: int = 0,
        benchmark: str = "ew", spot_only: bool | None = None) -> Result:
    g, tv, le, se = simulate(P, W, rebalance, start)
    if spot_only is None:
        spot_only = bool(np.nanmin(np.nan_to_num(W)) >= 0)
    return Result(family, sub, name, g, tv, le, se, benchmark, spot_only)


# ---------------------------------------------------------------------------
# Common weight builders
# ---------------------------------------------------------------------------

def vol_sized(P: Panel, held: np.ndarray, target_vol: float, slots: np.ndarray | int) -> np.ndarray:
    """Weight per held coin = target_vol / (annual vol) / slots, total capped at 1."""
    with np.errstate(invalid="ignore", divide="ignore"):
        w = np.where(held & np.isfinite(P.sigma) & (P.sigma > 0),
                     target_vol / (P.sigma * np.sqrt(365)), 0.0)
    slots = np.maximum(np.asarray(slots, dtype=float), 1.0)
    w = w / (slots[:, None] if np.ndim(slots) else slots)
    s = w.sum(1, keepdims=True)
    return np.where(s > 1, w / np.maximum(s, 1e-12), w)


def equal_weight(mask: np.ndarray, gross: float = 1.0) -> np.ndarray:
    n = mask.sum(1, keepdims=True)
    return np.where(mask, gross / np.maximum(n, 1), 0.0)


def xs_rank(score: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Cross-sectional percentile rank in (0, 1] among `mask`, NaN elsewhere."""
    s = np.where(mask & np.isfinite(score), score, np.nan)
    order = np.argsort(np.argsort(np.where(np.isnan(s), np.inf, s), axis=1), axis=1).astype(float)
    n = np.isfinite(s).sum(1, keepdims=True)
    return np.where(np.isfinite(s), (order + 1) / np.maximum(n, 1), np.nan)


def every(P: Panel, k: int) -> np.ndarray:
    """Rebalance mask: every k-th calendar day."""
    return (np.arange(P.T) % k) == 0


# ---------------------------------------------------------------------------
# Measuring
# ---------------------------------------------------------------------------

def masks(P: Panel) -> tuple[np.ndarray, np.ndarray]:
    ins = (P.days >= IS_START) & (P.days < SPLIT)
    oos = P.days >= SPLIT
    return ins, oos


def perf(r: np.ndarray) -> dict:
    r = r[np.isfinite(r)]
    if len(r) < 2:
        return {"sharpe": 0.0, "cagr": 0.0, "max_dd": 0.0, "vol": 0.0, "days": len(r)}
    eq = np.cumprod(1 + r)
    dd = 1 - eq / np.maximum.accumulate(eq)
    years = len(r) / 365
    sd = r.std()
    return {"sharpe": float(r.mean() / sd * np.sqrt(365)) if sd > 0 else 0.0,
            "cagr": float(eq[-1] ** (1 / years) - 1) if eq[-1] > 0 else -1.0,
            "max_dd": float(dd.max()), "vol": float(sd * np.sqrt(365)), "days": int(len(r))}


def benchmarks(P: Panel) -> dict[str, np.ndarray]:
    """Daily returns of BTC buy-and-hold and the equal-weight eligible universe (no costs)."""
    btc = np.nan_to_num(P.ret[:, P.btc])
    ew = np.zeros(P.T)
    for t in range(1, P.T):
        m = P.eligible[t - 1] & np.isfinite(P.ret[t])
        ew[t] = float(P.ret[t][m].mean()) if m.any() else 0.0
    return {"btc": btc, "ew": ew}


def measure(P: Panel, r: Result) -> dict:
    ins, oos = masks(P)
    years_oos = oos.sum() / 365
    row = {"family": r.family, "sub": r.sub, "variant": r.name, "benchmark": r.benchmark,
           "spot_only": r.spot_only}
    for label, c in COSTS.items():
        n = r.net(c)
        pi, po = perf(n[ins]), perf(n[oos])
        row[f"is_sharpe_{label}"] = pi["sharpe"]
        row[f"oos_sharpe_{label}"] = po["sharpe"]
        row[f"oos_cagr_{label}"] = po["cagr"]
        row[f"oos_max_dd_{label}"] = po["max_dd"]
    n15 = r.net(COSTS["15bps"])
    row["oos_vol"] = perf(n15[oos])["vol"]
    row["turnover_yr"] = float(r.turnover[oos].sum() / years_oos)
    row["avg_long"] = float(r.long_expo[oos].mean())
    row["avg_short"] = float(r.short_expo[oos].mean())
    # Regime of the return day = BTC state at the previous close (when the position was set).
    on_prev = np.r_[False, P.btc_on[:-1]]
    row["oos_sharpe_btc_above"] = perf(n15[oos & on_prev])["sharpe"]
    row["oos_sharpe_btc_below"] = perf(n15[oos & ~on_prev])["sharpe"]
    row["oos_days_below"] = int((oos & ~on_prev).sum())
    x = n15[oos]
    row["oos_skew"] = float(stats.skew(x)) if x.std() > 0 else 0.0
    row["oos_kurt"] = float(stats.kurtosis(x, fisher=False)) if x.std() > 0 else 3.0
    row["oos_days"] = int(oos.sum())
    return row


SR_CLIP = 3.0


def deflate(rows: list[dict], key: str = "oos_sharpe_15bps") -> dict:
    """Deflated Sharpe for every row against ALL rows given (the full count of tries).

    The variance of the trial Sharpes is taken over annual Sharpes winsorised
    at +-3: a handful of rules that trade every hour reach -20 to -50 from
    costs alone, which says nothing about how lucky a noise strategy can get
    and would raise the bar for every other variant. `deflated_p_rawvar` uses
    the raw variance (stricter). Each row's own skew and kurtosis are used:
    fat tails make a Sharpe less certain.
    """
    raw = np.array([r[key] for r in rows])
    var = float(np.var(np.clip(raw, -SR_CLIP, SR_CLIP) / np.sqrt(365)))
    var_raw = float(np.var(raw / np.sqrt(365)))
    for r in rows:
        s = r[key] / np.sqrt(365)
        denom = 1 - r["oos_skew"] * s + (r["oos_kurt"] - 1) / 4 * s ** 2
        if denom <= 0:
            r["deflated_p"] = r["deflated_p_rawvar"] = r["deflated_p_normal"] = 0.0
            continue
        r["deflated_p"] = deflated_sharpe(s, r["oos_days"], len(rows), var, r["oos_skew"], r["oos_kurt"])
        r["deflated_p_rawvar"] = deflated_sharpe(s, r["oos_days"], len(rows), var_raw, r["oos_skew"], r["oos_kurt"])
        r["deflated_p_normal"] = deflated_sharpe(s, r["oos_days"], len(rows), var)
        # Pure noise: every trial has true Sharpe 0, so its estimate varies by about 1/T.
        r["deflated_p_null"] = deflated_sharpe(s, r["oos_days"], len(rows), 1 / r["oos_days"], r["oos_skew"],
                                               r["oos_kurt"])
    return {"n_trials": len(rows), "sr_var_daily": var, "sr_var_daily_raw": var_raw,
            "expected_max_noise_sharpe_annual": _sr0(var, len(rows)) * np.sqrt(365)}


def _sr0(var: float, n: int) -> float:
    g = 0.5772156649
    return math.sqrt(var) * ((1 - g) * stats.norm.ppf(1 - 1 / n) + g * stats.norm.ppf(1 - 1 / (n * math.e)))


# ---------------------------------------------------------------------------
# Saving and reporting
# ---------------------------------------------------------------------------

def save_family(family: str, results: list[Result]) -> None:
    d = OUT / "runs"
    d.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(d / f"{family}.npz",
                        gross=np.array([r.gross for r in results]),
                        turnover=np.array([r.turnover for r in results]),
                        long_expo=np.array([r.long_expo for r in results]),
                        short_expo=np.array([r.short_expo for r in results]))
    (d / f"{family}.json").write_text(json.dumps(
        [{"family": r.family, "sub": r.sub, "name": r.name, "benchmark": r.benchmark, "spot_only": r.spot_only}
         for r in results], indent=1), encoding="utf-8")


def load_family(family: str) -> list[Result] | None:
    d = OUT / "runs"
    if not (d / f"{family}.npz").exists():
        return None
    z = np.load(d / f"{family}.npz")
    meta = json.loads((d / f"{family}.json").read_text(encoding="utf-8"))
    return [Result(m["family"], m["sub"], m["name"], z["gross"][i], z["turnover"][i], z["long_expo"][i],
                   z["short_expo"][i], m["benchmark"], m["spot_only"]) for i, m in enumerate(meta)]


def table(rows: list[dict], cols: list[str]) -> str:
    head = "| " + " | ".join(cols) + " |\n|" + "---|" * len(cols) + "\n"
    return head + "".join("| " + " | ".join(_fmt(r.get(c)) for c in cols) + " |\n" for r in rows)


def _fmt(v) -> str:
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, (float, np.floating)):
        if not math.isfinite(v):
            return "n/a"
        return f"{v:.2f}" if abs(v) < 100 else f"{v:,.0f}"
    return str(v)


def write_result(name: str, markdown: str, data: dict | list) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / f"{name}.md").write_text(markdown, encoding="utf-8")
    d = OUT / "reports"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.json").write_text(json.dumps(data, indent=1, default=str), encoding="utf-8")
