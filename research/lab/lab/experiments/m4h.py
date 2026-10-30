"""M4H: the M4 reg7n long/short at a 200 EUR account on Hyperliquid, automated, after every cost.

Pre-registered in results/m4h_prereg.md; its first run stopped at the signal check, so it runs as M4H2
(results/m4h2_prereg.md: the check reported, not a stop; trial ids small:m4h2). Results in results/m4h.md.

    PYTHIA_CACHE=<xs_daily panel cache> PYTHIA_AGENT_OUT=<cache> PYTHIA_TRIALS_REGISTRY=<registry> \
        PYTHIA_REPORTS=<reports> flock <heavy lock> python -m lab.experiments.m4h [--no-register] [--report]

reg7n unchanged (T6b's walk-forward refit on xs_daily's panel cut at 2026-06-30, the 2026-10-07 score cache being
gone), the 100 most liquid perps of each day as xs_daily.book_buffer takes them and, out of sample, only the ones
Hyperliquid lists on the fill day (ranked and buffered among those, as m4_perps does for Kraken). k long and k short,
k 3, 5 or 10, the 50 % rank buffer, gross 1x or 2x. Fills at 01:00 UTC (the panel's entry price) and at 02:00 (the
second hourly close of Binance spot); Hyperliquid taker 4.5 bps plus DT1's spread proxy on 1-hour bars, or maker
1.5 bps; Hyperliquid's hourly funding (Binance's where Hyperliquid has no record, and in sample). Accounts of 115,
230 and 460 USD with Hyperliquid's size decimals and its 10 USD minimum, and an ideal account. In sample 2022-2023,
judged 2024-01-01 to 2026-06-28 (the last holding ends 2026-06-30); nothing from 2026-07-01 is read. Every cell goes
into R5's registry with its in-sample Sharpe before any out-of-sample number. Benchmarks: BTC, SPY and EUNL.DE held.
Nothing here changes a book, a gate, the engine or a wallet.
"""

from __future__ import annotations

import json
import math
import os
import sys
import time
import urllib.request
import warnings
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import polars as pl

from .. import data as labdata
from .. import metrics
from . import daytrade_dt1 as dt
from . import director_common as dc

NAME = "m4h"
PREREG = "results/m4h2_prereg.md"
IS_FROM, IS_TO = "2022-01-01", "2023-12-31"
OOS_FROM, OOS_TO = "2024-01-01", "2026-06-28"      # decision days; the last holding ends 2026-06-30
CUT = "2026-06-30"                                 # the panel's last row read
LOCKBOX = "2026-07-01"
YEARS_OOS = (2024, 2025, 2026)
CACHE = Path(os.environ.get("PYTHIA_AGENT_OUT", str(labdata.ROOT / "agent-strategies"))) / "m4h"
DAY_US = dt.DAY_US
HOUR_US = 3_600_000_000

FEE = {"taker": dt.FEE_HL, "maker": dt.FEE_MAKER}
SLIP_BASE, SLIP_CAP, TOP_N, SPREAD_N = dt.SLIP_BASE, dt.SLIP_CAP, 20, 30
MIN_ORDER = 10.0
ACCOUNTS = {"115usd": 115.0, "230usd": 230.0, "460usd": 460.0, "ideal": None}
KS, GROSS, FILLS, FEES = (3, 5, 10), (1, 2), ("base", "late"), ("taker", "maker")
N_LIQUID, EXIT_FRAC = 100, 0.5
JUDGED = {"account": "230usd", "fee": "taker", "fill": "base", "gross": 1}
PASS_SHARPE, PASS_DD, PASS_CORR, DSR_PASS = 1.0, 0.25, 0.8, 0.95
STOP = 0.20
CHECK_IS, CHECK_COST = 0.93, 0.0041                 # m4_residual's 2022-2023 Sharpe at 41 bps (M4H2: reported only)
CHECK_YEARS = {2024: 1.67, 2025: 2.43}
EUR_FUND = 200.0
YEAR = 365
HL_INFO = dt.HL_INFO
ETFS = {"SPY": "SPY", "EUNL": "EUNL.DE"}


# ---------------------------------------------------------------- the signal and the matrices

def load_matrices(log=print) -> dict:
    """xs_daily's matrices of the panel cut at CUT with reg7n's walk-forward scores (T6b's refit, cached), plus each
    column's Binance perp symbol."""
    from . import two_leads_t6 as t6
    from . import two_leads_t6b as t6b
    from . import xs_daily as xs
    P = xs.build_panel().filter(pl.col("day") <= dc.us(CUT))
    P, _ = xs.add_net_labels(P)
    path = CACHE / "reg7n_scores.parquet"
    if path.exists():
        S = pl.read_parquet(path)
    else:
        S = t6b.reg7n_scores(P, log)
        path.parent.mkdir(parents=True, exist_ok=True)
        S.write_parquet(path)
    E = xs.ranked(P.with_columns(adv28_raw=pl.col("adv28"), r1_raw=pl.col("r1"), r28_raw=pl.col("r28"),
                                 fund7_raw=pl.col("fund7"), vol28_raw=pl.col("vol28")))
    E = E.join(S, on=["day", "symbol"], how="left").filter(pl.col("day") >= xs.FIRST_TEST)
    M = t6.cut_matrices(xs.matrices(E, P.filter(pl.col("day") >= xs.FIRST_TEST), ["reg7n"]), CUT)
    perp = (P.filter(pl.col("perp").is_not_null()).sort("day").group_by("symbol").agg(pl.col("perp").last()))
    pm = dict(zip(perp["symbol"].to_list(), perp["perp"].to_list()))
    M["perp"] = [pm.get(s) for s in M["syms"]]
    M["P"] = panel_matrix(P, M["days"], M["syms"], "P")      # the entry price, for the size rounding
    return M


def panel_matrix(P: pl.DataFrame, days: np.ndarray, syms, col: str) -> np.ndarray:
    """(T, N) a panel column on the matrices' calendar and columns (NaN where missing)."""
    di = {int(d): i for i, d in enumerate(days)}
    si = {s: i for i, s in enumerate(syms)}
    f = P.filter(pl.col("day").is_in(days) & pl.col("symbol").is_in(list(syms))).select("day", "symbol", col).drop_nulls()
    m = np.full((len(days), len(syms)), np.nan)
    m[[di[int(d)] for d in f["day"].to_list()], [si[x] for x in f["symbol"].to_list()]] = f[col].to_numpy()
    return m


def spot_of(sym: str) -> str:
    """The Binance spot ticker of a panel column (an old segment X~0 is X's)."""
    return sym.split("~")[0]


def hourly(sym: str, root: Path | None = None) -> pl.DataFrame | None:
    """A spot symbol's 1-hour bars (t, h, l, c) from 2021-12 to the cut, nothing later."""
    d = (root or labdata.ROOT / "hist" / "binance_spot" / "klines_1h") / f"symbol={sym}"
    files = [f for f in sorted(d.glob("*.parquet")) if "2021-12" <= f.stem[:7] <= CUT[:7]]
    if not files:
        return None
    h = (pl.concat([pl.read_parquet(f, columns=["open_time_us", "high", "low", "close"]) for f in files],
                   how="vertical_relaxed").unique("open_time_us").sort("open_time_us")
         .filter(pl.col("open_time_us") < dt.us(LOCKBOX)))
    return h.select(t="open_time_us", h="high", l="low", c="close")


def ar_daily(h: pl.DataFrame) -> pl.DataFrame:
    """day (us), the sum and count of Abdi and Ranaldo's 4 (c_t - eta_t)(c_t - eta_t+1) on log prices of consecutive
    1-hour bars, the second hourly close (02:00) of the day."""
    t = h["t"].to_numpy()
    c = np.log(h["c"].to_numpy().astype(float))
    eta = np.log((h["h"].to_numpy() + h["l"].to_numpy()) / 2)
    x = np.full(len(c), np.nan)
    nxt = np.r_[t[1:] - t[:-1] == HOUR_US, False]
    x[:-1] = 4 * (c[:-1] - eta[:-1]) * (c[:-1] - eta[1:])
    x = np.where(nxt, x, np.nan)
    day = (t // DAY_US) * DAY_US
    f = pl.DataFrame({"day": day, "x": x, "t": t, "c": h["c"].to_numpy()})
    return f.group_by("day").agg(s=pl.col("x").fill_nan(None).sum(), n=pl.col("x").fill_nan(None).count(),
                                 c2=pl.col("c").filter(pl.col("t") % DAY_US == HOUR_US).first())


def spread_and_late(M: dict, cols: np.ndarray, log=print) -> tuple[np.ndarray, np.ndarray]:
    """(T, N) the 30-day Abdi-Ranaldo spread known at each decision (NaN without bars) and the 02:00 price of the
    fill day (NaN where missing), for the columns `cols`."""
    days = M["days"]
    T, N = len(days), len(M["syms"])
    S, C2 = np.full((T, N), np.nan), np.full((T, N), np.nan)
    di = {int(d): i for i, d in enumerate(days)}
    byspot: dict[str, list[int]] = {}
    for j in cols:
        byspot.setdefault(spot_of(M["syms"][j]), []).append(int(j))
    for n, (sym, js) in enumerate(sorted(byspot.items())):
        h = hourly(sym)
        if h is None or h.height < 48:
            continue
        a = ar_daily(h).sort("day")
        dd = a["day"].to_numpy()
        s, k = np.nan_to_num(a["s"].to_numpy().astype(float)), a["n"].to_numpy().astype(float)
        full = np.arange(dd.min(), dd.max() + DAY_US, DAY_US)
        pos = ((dd - dd.min()) // DAY_US).astype(np.int64)
        fs, fk, fc = np.zeros(len(full)), np.zeros(len(full)), np.full(len(full), np.nan)
        fs[pos], fk[pos] = s, k
        fc[pos] = a["c2"].to_numpy().astype(float)
        cs, ck = np.r_[0.0, np.cumsum(fs)], np.r_[0.0, np.cumsum(fk)]
        hi = np.arange(1, len(full) + 1)
        lo = np.maximum(hi - SPREAD_N, 0)
        with np.errstate(invalid="ignore", divide="ignore"):
            m = np.where(ck[hi] - ck[lo] > 0, (cs[hi] - cs[lo]) / np.maximum(ck[hi] - ck[lo], 1), np.nan)
        spread = np.sqrt(np.maximum(m, 0))
        for i, d in enumerate(full):
            r = di.get(int(d))
            if r is not None:
                S[r, js] = spread[i]                 # days d-29..d: known at the decision after day d
            r1 = di.get(int(d) - DAY_US)
            if r1 is not None:
                C2[r1, js] = fc[i]                   # the 02:00 close of day d+1 is decision day d's late fill
        if n % 100 == 0:
            log(f"  hourly {n}/{len(byspot)}")
    return S, C2


def slippage(spread: np.ndarray, liq: np.ndarray, score: np.ndarray) -> np.ndarray:
    """(T, N) a side: DT1's proxy. 1 bp for the day's TOP_N most liquid scored coins; for the rest 1 bp plus half the
    excess of the spread over the top's median, at most 50 bps; 50 bps without an estimate."""
    ok = np.isfinite(score) & np.isfinite(liq)
    v = np.where(ok, liq, -np.inf)
    rank = np.argsort(np.argsort(-v, axis=1), axis=1)
    top = (rank < TOP_N) & ok
    with np.errstate(invalid="ignore"):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            ref = np.nanmedian(np.where(top, spread, np.nan), axis=1)
        slip = SLIP_BASE + np.maximum(0, (spread - np.nan_to_num(ref)[:, None]) / 2)
    slip = np.where(np.isfinite(slip), np.minimum(slip, SLIP_CAP), SLIP_CAP)
    return np.where(top, SLIP_BASE, slip)


def late_returns(P: np.ndarray, C2: np.ndarray, R: np.ndarray) -> np.ndarray:
    """(T, N) returns from one 02:00 fill to the next; the 01:00 return where a 02:00 price is missing."""
    with np.errstate(invalid="ignore", divide="ignore"):
        r2 = np.vstack([C2[1:] / C2[:-1] - 1, np.full((1, C2.shape[1]), np.nan)])
    return np.where(np.isfinite(r2), r2, R)


# ---------------------------------------------------------------- Hyperliquid: listing, funding, size decimals

def hl_coins() -> dict[str, str]:
    """{Binance perp symbol: Hyperliquid coin} of T12b's listing history."""
    raw = json.loads((labdata.ROOT / "free" / "perps_all" / "hyperliquid" / "listings.json").read_text(encoding="utf-8"))
    return {dt.hl_to_binance(c): c for c in raw}


def listed_matrix(days: np.ndarray, perps: list[str | None], lst: dict[str, tuple[int, int | None]]) -> np.ndarray:
    """(T, N) bool: Hyperliquid lists the column's perp on the fill day (decision day + 1)."""
    fill = days // DAY_US + 1
    out = np.zeros((len(days), len(perps)), dtype=bool)
    for j, p in enumerate(perps):
        v = lst.get(p) if p else None
        if v is None:
            continue
        first, last = v
        out[:, j] = (fill >= first) & ((fill <= last) if last is not None else True)
    return out


def window_sums(ts: np.ndarray, rate: np.ndarray, a: np.ndarray, b: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """The sum and count of the rates with a time in (a, b] for each pair."""
    cs = np.r_[0.0, np.cumsum(rate)]
    i, j = np.searchsorted(ts, a, side="right"), np.searchsorted(ts, b, side="right")
    return cs[j] - cs[i], j - i


def hl_funding(days: np.ndarray, perps: list[str | None], coins: dict[str, str], cols: np.ndarray,
               root: Path | None = None) -> dict[str, np.ndarray]:
    """{base, late}: (T, N) Hyperliquid's funding over each holding period (fill, next fill], NaN without a record."""
    root = root or labdata.ROOT / "free" / "perps_all" / "hyperliquid" / "funding"
    out = {f: np.full((len(days), len(perps)), np.nan) for f in FILLS}
    for j in cols:
        c = coins.get(perps[j]) if perps[j] else None
        f = root / f"{c}.parquet" if c else None
        if f is None or not f.exists():
            continue
        x = (pl.read_parquet(f, columns=["ts_us", "funding_rate"]).unique("ts_us").sort("ts_us")
             .filter(pl.col("ts_us") < dt.us(LOCKBOX)))
        ts, rate = x["ts_us"].to_numpy(), np.nan_to_num(x["funding_rate"].to_numpy().astype(float))
        for fill, lag in (("base", 1), ("late", 2)):
            a = days + DAY_US + lag * HOUR_US
            s, n = window_sums(ts, rate, a, a + DAY_US)
            out[fill][:, j] = np.where(n > 0, s, np.nan)
    return out


def fetch_meta(path: Path | None = None) -> dict[str, int]:
    """{Hyperliquid coin: szDecimals} from the public meta endpoint (no key), cached; delisted coins included."""
    path = path or CACHE / "hl_meta.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    req = urllib.request.Request(HL_INFO, data=json.dumps({"type": "meta"}).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        meta = json.loads(r.read())
    out = {u["name"]: int(u["szDecimals"]) for u in meta.get("universe", [])}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=0, sort_keys=True), encoding="utf-8")
    return out


def unit_mult(coin: str | None) -> float:
    """Spot coins in one Hyperliquid size unit: kPEPE is 1,000 PEPE."""
    return 1000.0 if coin and coin.startswith("k") and coin[1:].isupper() else 1.0


def round_size(usd: float, px: float, dec: int | None) -> float:
    """The notional of the order Hyperliquid would take for usd at px: the size in units rounded to dec decimals
    (no rounding without dec or a price)."""
    if dec is None or not (px > 0) or not math.isfinite(px):
        return usd
    return round(usd / px, dec) * px


# ---------------------------------------------------------------- the account

def targets(w: np.ndarray, score: np.ndarray, idx: np.ndarray, k: int, gross: float) -> np.ndarray:
    """xs_daily.book_buffer's target on the weights w among the liquid (listed) set idx, scaled by gross: an
    entering name gets gross x 0.5 / k, a held one is cut back to gross / k, a name out of its side's best half
    leaves; fewer than 2k names: nothing held."""
    tgt = np.zeros(len(w))
    if len(idx) < 2 * k:
        return tgt
    e, cap = gross * 0.5 / k, gross / k
    exit_k = max(k, int(EXIT_FRAC * len(idx)))
    order = idx[np.argsort(-score[idx])]
    top_keep, bot_keep = set(order[:exit_k]), set(order[-exit_k:])
    longs = [i for i in np.flatnonzero(w > 0) if i in top_keep]
    shorts = [i for i in np.flatnonzero(w < 0) if i in bot_keep]
    tgt[longs] = np.minimum(w[longs], cap)
    tgt[shorts] = np.maximum(w[shorts], -cap)
    for i in order:
        if len(longs) >= k:
            break
        if i not in longs and i not in shorts:
            longs.append(i)
            tgt[i] = e
    for i in order[::-1]:
        if len(shorts) >= k:
            break
        if i not in shorts and i not in longs:
            shorts.append(i)
            tgt[i] = -e
    return tgt


def liquid(score_t: np.ndarray, liq_t: np.ndarray, listed_t: np.ndarray | None) -> np.ndarray:
    """The day's N_LIQUID scored coins with the highest perp volume, then (judged) only the listed ones."""
    ok = np.isfinite(score_t) & np.isfinite(liq_t)
    idx = np.flatnonzero(ok)
    idx = idx[np.argsort(-liq_t[idx])][:N_LIQUID]
    return idx[listed_t[idx]] if listed_t is not None else idx


def simulate(X: dict, t0: int, t1: int, k: int, gross: float, capital: float | None, fee: float, fill: str,
             listed: np.ndarray | None, slip: bool = True, keep_weights: bool = False) -> dict:
    """The account over decision days t0..t1 (rows). Each day: mark, the buffer's target on the drifted weights,
    orders at the fill (size rounded to the coin's decimals, under MIN_ORDER not sent unless a full close), the
    holding period's return and funding. capital None: the ideal account (equity a unit, no rounding, no minimum).
    Returns the daily returns, the funding share of each day, the counts and (keep_weights) the held weights."""
    R = np.nan_to_num(X["R2"] if fill == "late" else X["R"])
    F = X["F2"] if fill == "late" else X["F"]
    px = X["P2"] if fill == "late" else X["P"]
    S = X["slip"] if slip else np.zeros_like(R)
    N = R.shape[1]
    pos = np.zeros(N)
    eq = float(capital) if capital else 1.0
    n = t1 - t0 + 1
    out, fshare = np.zeros(n), np.zeros(n)
    W = np.zeros((n, N)) if keep_weights else None
    c = {"wanted": 0, "sent": 0, "skip_min": 0, "cut_wanted": 0, "cut_skipped": 0, "fees": 0.0, "slip": 0.0,
         "funding": 0.0, "eq_days": 0.0, "dead": None}
    dec, mult = X["dec"], X["mult"]
    for t in range(t0, t1 + 1):
        a = t - t0
        idx = liquid(X["score"][t], X["liq"][t], listed[t] if listed is not None else None)
        w = pos / eq
        tgt = targets(w, X["score"][t], idx, k, gross)
        start, cost_f, cost_s = eq, 0.0, 0.0
        for j in np.flatnonzero((tgt != 0) | (pos != 0)):
            goal = tgt[j] * eq
            if capital:
                goal = round_size(goal, px[t, j] * mult[j], dec[j])
            delta = goal - pos[j]
            cut = pos[j] != 0 and tgt[j] != 0 and abs(tgt[j]) < abs(w[j]) - 1e-12
            if pos[j] == 0 and tgt[j] != 0:
                c["wanted"] += 1
            elif cut:
                c["cut_wanted"] += 1
            if abs(delta) < 1e-12:
                if pos[j] == 0 and tgt[j] != 0:
                    c["skip_min"] += 1                # rounded to nothing
                continue
            if capital and goal != 0 and abs(delta) < MIN_ORDER:
                if pos[j] == 0:
                    c["skip_min"] += 1
                elif cut:
                    c["cut_skipped"] += 1
                continue
            if pos[j] == 0:
                c["sent"] += 1
            cost_f += abs(delta) * fee
            cost_s += abs(delta) * S[t, j]
            pos[j] = goal
        if W is not None:
            W[a] = pos / eq
        f_t = np.where(np.isfinite(F[t]), F[t], X["Fb"][t])
        fund = float(np.dot(pos, np.nan_to_num(f_t)))
        pnl = float(np.dot(pos, R[t]))
        pos = pos * (1 + R[t])
        eq = eq + pnl - fund - cost_f - cost_s
        c["fees"] += cost_f
        c["slip"] += cost_s
        c["funding"] += fund
        c["eq_days"] += start
        fshare[a] = fund / start
        if eq <= 0:
            out[a] = -1.0
            c["dead"] = int(t)
            break
        out[a] = eq / start - 1
    c["end"] = eq
    return {"ret": out, "fund": fshare, "W": W, **c}


# ---------------------------------------------------------------- numbers

def ann_sharpe(x: np.ndarray) -> float:
    x = np.asarray(x, float)
    return float(x.mean() / x.std() * math.sqrt(YEAR)) if len(x) > 1 and x.std() > 0 else 0.0


def cagr(x: np.ndarray) -> float:
    return float(np.exp(np.sum(np.log1p(np.maximum(x, -0.999)))) ** (YEAR / max(len(x), 1)) - 1)


def max_dd(x: np.ndarray) -> float:
    if not len(x):
        return 0.0
    e = np.cumprod(1 + np.maximum(x, -0.999))
    return float(np.max(1 - e / np.maximum.accumulate(np.r_[1.0, e])[1:]))


def stop_day(x: np.ndarray, days: np.ndarray) -> str | None:
    """The first decision day whose equity closes STOP or more below the start, or None."""
    e = np.cumprod(1 + np.maximum(x, -0.999))
    hit = np.flatnonzero(e <= 1 - STOP)
    return dc.day_str(int(days[hit[0]])) if len(hit) else None


def months(x: np.ndarray, days: np.ndarray) -> dict[str, float]:
    """{YYYY-MM: compounded return} by the month of the holding period's fill (decision day + 1)."""
    m = (days // DAY_US + 1).astype("datetime64[D]").astype("datetime64[M]").astype(str)
    out: dict[str, float] = {}
    for k in dict.fromkeys(m):
        out[k] = float(np.prod(1 + x[m == k]) - 1)
    return out


def drift(Wa: np.ndarray, Wi: np.ndarray) -> float:
    """The mean over days of half the sum of |account weight - ideal weight|."""
    return float(np.mean(0.5 * np.abs(Wa - Wi).sum(1)))


def cell_key(account: str, k: int, gross: int, fill: str, fee: str) -> str:
    return f"{account}:k{k}:g{gross}:{fill}:{fee}"


def cells() -> list[tuple[str, int, int, str, str]]:
    return [(a, k, g, f, fe) for a in ACCOUNTS for k in KS for g in GROSS for f in FILLS for fe in FEES]


def trial_id(key: str) -> str:
    return f"small:m4h2:{key}"


CHECK_ID = "small:m4h2:check_binance_10_10_41bps"


def trials(is_sharpe: dict[str, float], check_is: float) -> list[dict]:
    rows = [{"id": trial_id(cell_key(*c)), "family": "small", "source": PREREG,
             "sharpe": is_sharpe.get(cell_key(*c))} for c in cells()]
    return rows + [{"id": CHECK_ID, "family": "small", "source": PREREG, "sharpe": check_is}]


def judge_cell(r: dict, ideal: dict, years: np.ndarray) -> dict:
    """The five registered checks of one out-of-sample cell against its ideal account."""
    x = r["ret"]
    lo, hi, above = dc.boot_band(x)
    yrs = {y: float(x[years == y].mean()) if (years == y).any() else float("nan") for y in YEARS_OOS}
    corr = float(np.corrcoef(x, ideal["ret"])[0, 1]) if x.std() > 0 and ideal["ret"].std() > 0 else 0.0
    checks = {"Sharpe above 1.0": ann_sharpe(x) > PASS_SHARPE,
              "bootstrap 5 % above 0": lo > 0,
              "positive in 2024, 2025 and 2026": all(v > 0 for v in yrs.values()),
              "drawdown under 25 %": max_dd(x) < PASS_DD,
              "correlation to the ideal book above 0.8": corr > PASS_CORR}
    return {"boot_p05": lo, "boot_p95": hi, "boot_above0": above, "corr_ideal": corr,
            **{f"mean{y}": v for y, v in yrs.items()}, "checks": checks, "pass": all(checks.values())}


def window_rows(days: np.ndarray, first: str, last: str) -> tuple[int, int]:
    return int(np.searchsorted(days, dc.us(first))), int(np.searchsorted(days, dc.us(last), side="right")) - 1


def etf_returns(days: np.ndarray, sym: str, root: Path | None = None) -> np.ndarray:
    """A fund's close-to-close return of the fill day (decision day + 1), 0 on a day without a close."""
    f = (root or labdata.ROOT / "etf" / "daily") / f"{sym}.csv"
    e = pl.read_csv(f).select(d=pl.col("Date").str.to_date(), c=pl.col("Close").cast(pl.Float64)).drop_nulls()
    e = e.filter(pl.col("d") < pl.lit(LOCKBOX).str.to_date()).sort("d")
    r = dict(zip(e["d"].cast(pl.Int64).to_list()[1:], (e["c"].to_numpy()[1:] / e["c"].to_numpy()[:-1] - 1).tolist()))
    return np.array([r.get(int(d // DAY_US) + 1, 0.0) for d in days])


def eurusd(days: np.ndarray, path: Path | None = None) -> np.ndarray:
    """EUR/USD of each fill day, the last rate before it on days without one."""
    f = path or dc.RESULTS / "etf_books_eq1_eurusd.csv"
    e = pl.read_csv(f).select(d=pl.col("date").str.to_date().cast(pl.Int64), r=pl.col("eurusd").cast(pl.Float64))
    d, r = e["d"].to_numpy(), e["r"].to_numpy()
    i = np.clip(np.searchsorted(d, days // DAY_US + 1, side="right") - 1, 0, len(d) - 1)
    return r[i]


def money(x: np.ndarray, fx: np.ndarray, usd: float | None = None, eur: float | None = None) -> dict:
    """What an account made over the window: USD (start usd) or EUR (start eur, a USD series converted at fx)."""
    g = float(np.prod(1 + x))
    if eur is not None:
        return {"start_eur": eur, "end_eur": eur * g, "gain_eur": eur * (g - 1)}
    end_usd = usd * g
    return {"start_usd": usd, "end_usd": end_usd, "start_eur": usd / fx[0], "end_eur": end_usd / fx[-1],
            "gain_eur": end_usd / fx[-1] - usd / fx[0]}


def eur_band(x: np.ndarray, usd: float, fx: np.ndarray, idx: np.ndarray) -> tuple[float, float, float]:
    """The expected EUR a year of an account of usd (mean daily return x 365) and its 5 % and 95 % bootstrap bounds,
    at the window's mean rate."""
    m = x[idx].mean(1) * YEAR * usd / fx.mean()
    return float(x.mean() * YEAR * usd / fx.mean()), float(np.quantile(m, 0.05)), float(np.quantile(m, 0.95))


# ---------------------------------------------------------------- the run

def build(log=print) -> dict:
    """Every input of the simulation as (T, N) matrices on xs_daily's calendar."""
    M = load_matrices(log)
    log(f"matrices {len(M['days'])} days x {len(M['syms'])} columns")
    score, liq = M["reg7n"], M["perp_adv28"]
    ok = np.isfinite(score) & np.isfinite(liq)
    v = np.where(ok, liq, -np.inf)
    inset = (np.argsort(np.argsort(-v, axis=1), axis=1) < N_LIQUID) & ok
    cols = np.flatnonzero(inset.any(0))
    spread, C2 = spread_and_late(M, cols, log)
    coins = hl_coins()
    lst = dt.hl_listings()
    meta = fetch_meta()
    hl = hl_funding(M["days"], M["perp"], coins, cols)
    coin = [coins.get(p) if p else None for p in M["perp"]]
    X = {"days": M["days"], "syms": list(M["syms"]), "perp": M["perp"], "coin": coin, "score": score, "liq": liq,
         "R": M["R"], "R2": late_returns(M["P"], C2, M["R"]), "P": M["P"], "P2": np.where(np.isfinite(C2), C2, M["P"]),
         "Fb": M["fund"], "F_hl": hl["base"], "F2_hl": hl["late"],
         "slip": slippage(spread, liq, score), "listed": listed_matrix(M["days"], M["perp"], lst),
         "dec": [meta.get(c) if c else None for c in coin], "mult": np.array([unit_mult(c) for c in coin]),
         "inset": inset, "cols": cols, "spread": spread}
    return X


def run_cells(X: dict, t0: int, t1: int, listed: np.ndarray | None, log=print) -> dict:
    """Every cell over rows t0..t1; account cells carry their drift against the ideal account of the same cell."""
    res = {}
    for k in KS:
        for g in GROSS:
            for fill in FILLS:
                for fe in FEES:
                    ideal = simulate(X, t0, t1, k, g, None, FEE[fe], fill, listed, slip=fe == "taker",
                                     keep_weights=True)
                    for acc, cap in ACCOUNTS.items():
                        if cap is None:
                            r = ideal
                        else:
                            r = simulate(X, t0, t1, k, g, cap, FEE[fe], fill, listed, slip=fe == "taker",
                                         keep_weights=True)
                            r["drift"] = drift(r["W"], ideal["W"])
                            r["corr_ideal"] = float(np.corrcoef(r["ret"], ideal["ret"])[0, 1]) \
                                if r["ret"].std() > 0 and ideal["ret"].std() > 0 else 0.0
                        res[cell_key(acc, k, g, fill, fe)] = r
                    res[cell_key("ideal", k, g, fill, fe)]["drift"] = 0.0
                    res[cell_key("ideal", k, g, fill, fe)]["corr_ideal"] = 1.0
                    for r in (res[cell_key(a, k, g, fill, fe)] for a in ACCOUNTS):
                        r["W"] = None
            log(f"  k {k} gross {g} done")
    return res


def summary(r: dict, days: np.ndarray, cap: float | None) -> dict:
    x = r["ret"]
    mo = months(x, days)
    worst = min(mo, key=mo.get) if mo else None
    return {"sharpe": ann_sharpe(x), "cagr": cagr(x), "max_dd": max_dd(x), "mean_ann": float(x.mean() * YEAR),
            "end": r["end"] if cap else float(np.prod(1 + x)), "worst_month": worst,
            "worst_month_ret": mo.get(worst, float("nan")) if worst else float("nan"),
            "stop_day": stop_day(x, days), "wanted": r["wanted"], "sent": r["sent"],
            "skip_share": r["skip_min"] / r["wanted"] if r["wanted"] else float("nan"),
            "cut_wanted": r["cut_wanted"], "cut_skipped": r["cut_skipped"], "drift": r.get("drift", 0.0),
            "corr_ideal": r.get("corr_ideal", 1.0),
            "fees_ann": r["fees"] / r["eq_days"] * YEAR if r["eq_days"] else 0.0,
            "slip_ann": r["slip"] / r["eq_days"] * YEAR if r["eq_days"] else 0.0,
            "funding_ann": r["funding"] / r["eq_days"] * YEAR if r["eq_days"] else 0.0,
            "sharpe_no_funding": ann_sharpe(x + r["fund"]), "dead": r["dead"]}


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    from .. import report
    rep = report.REPORTS / NAME
    if "--report" in argv:
        o = json.loads((rep / "latest.json").read_text(encoding="utf-8"))
        dc.write_results(NAME, markdown(o), HEAD)
        return 0
    register = "--no-register" not in argv
    t_0 = time.time()
    log = lambda s: print(f"[{time.time() - t_0:.0f} s] {s}", flush=True)       # noqa: E731
    X = build(log)
    days = X["days"]
    X["F"], X["F2"] = np.full(X["R"].shape, np.nan), np.full(X["R"].shape, np.nan)
    i0, i1 = window_rows(days, IS_FROM, IS_TO)
    o0, o1 = window_rows(days, OOS_FROM, OOS_TO)

    # The check: the rebuilt original book on the Binance universe (xs_daily.book_buffer), in sample first.
    from . import xs_daily as xs
    Mc = {"R": X["R"], "fund": X["Fb"], "perp_adv28": X["liq"]}
    g, tu, fu, _ = xs.book_buffer(Mc, X["score"], 10, EXIT_FRAC, N_LIQUID)
    check = g + fu - tu * CHECK_COST
    check_is = ann_sharpe(check[i0:i1 + 1])
    log(f"check in sample {check_is:.2f} (m4_residual {CHECK_IS}; M4H2 reports it, M4H stopped on it)")

    # In sample: the Binance universe, Binance's funding, every cell; then the trials, before any later number.
    IS = run_cells(X, i0, i1, None, log)
    is_sharpe = {k: ann_sharpe(r["ret"]) for k, r in IS.items()}
    T = trials(is_sharpe, check_is)
    if register:
        metrics.register(T)
    pool = metrics.trial_pool(None, extra=T)
    pool_small = metrics.trial_pool("small", extra=T)
    log(f"{len(T)} trials registered; pool {pool['n_trials']}")

    # Out of sample: Hyperliquid's listed coins and its funding.
    X["F"], X["F2"] = X["F_hl"], X["F2_hl"]
    OOS = run_cells(X, o0, o1, X["listed"], log)
    od = days[o0:o1 + 1]
    years = dc.years_of(od)
    rows = []
    for key, r in OOS.items():
        acc, k, g_, fill, fe = key.split(":")
        cap = ACCOUNTS[acc]
        s = summary(r, od, cap)
        s.update(cell=key, account=acc, k=int(k[1:]), gross=int(g_[1:]), fill=fill, fee=fe, is_sharpe=is_sharpe[key],
                 is_cagr=cagr(IS[key]["ret"]), is_max_dd=max_dd(IS[key]["ret"]),
                 dsr=metrics.dsr(r["ret"], pool), dsr_small=metrics.dsr(r["ret"], pool_small))
        ideal = OOS[cell_key("ideal", int(k[1:]), int(g_[1:]), fill, fe)]
        s.update(judge_cell(r, ideal, years))
        s["by_year"] = {str(y): ann_sharpe(r["ret"][years == y]) for y in YEARS_OOS}
        s["months"] = months(r["ret"], od)
        rows.append(s)
    by = {r["cell"]: r for r in rows}
    judged = [by[cell_key(JUDGED["account"], k, JUDGED["gross"], JUDGED["fill"], JUDGED["fee"])] for k in KS]
    passing = [r for r in judged if r["pass"]]
    pick = max(passing, key=lambda r: r["is_sharpe"]) if passing else None

    # Benchmarks and money on the same days.
    fx = eurusd(od)
    bi = X["syms"].index("BTCUSDT")
    bench = {"BTC": np.nan_to_num(X["R"][o0:o1 + 1, bi])}
    for name, sym in ETFS.items():
        bench[name] = etf_returns(od, sym)
    to_eur = np.r_[fx[0], fx[:-1]] / fx                       # a USD return seen from EUR
    bench_eur = {"BTC": (1 + bench["BTC"]) * to_eur - 1, "SPY": (1 + bench["SPY"]) * to_eur - 1, "EUNL": bench["EUNL"]}
    bsum = {n: {"sharpe": ann_sharpe(x), "cagr": cagr(x), "max_dd": max_dd(x),
                "by_year": {str(y): float(np.prod(1 + x[years == y]) - 1) for y in YEARS_OOS},
                "eur": money(bench_eur[n], fx, eur=EUR_FUND)} for n, x in bench.items()}
    idx = metrics.stationary_bootstrap(len(od), dc.BOOT_DRAWS, dc.BOOT_BLOCK, dc.BOOT_SEED)
    money_rows = []
    for r in judged + [by[cell_key("230usd", k, 1, "late", "taker")] for k in KS]:
        x = OOS[r["cell"]]["ret"]
        e, lo, hi = eur_band(x, ACCOUNTS["230usd"], fx, idx)
        money_rows.append({"cell": r["cell"], **money(x, fx, usd=ACCOUNTS["230usd"]), "eur_year": e,
                           "eur_year_p05": lo, "eur_year_p95": hi, "worst_month": r["worst_month"],
                           "worst_month_ret": r["worst_month_ret"],
                           "by_year": {str(y): float(np.prod(1 + x[years == y]) - 1) for y in YEARS_OOS}})
    chk = {"is": check_is, "is_published": CHECK_IS,
           "is_by_year": {str(y): ann_sharpe(check[i0:i1 + 1][dc.years_of(days[i0:i1 + 1]) == y]) for y in (2022, 2023)},
           **{str(y): ann_sharpe(check[o0:o1 + 1][years == y]) for y in CHECK_YEARS},
           "published": {str(y): v for y, v in CHECK_YEARS.items()}}
    lst = X["listed"][o0:o1 + 1]
    inset = X["inset"][o0:o1 + 1]
    hl_rec = np.isfinite(X["F_hl"][o0:o1 + 1]) & inset & lst
    held = [d for d in X["dec"] if d is not None]
    out = {"generated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "rows": rows,
           "judged": [r["cell"] for r in judged], "passed": [r["cell"] for r in passing],
           "pick": pick["cell"] if pick else None, "confirmed": bool(pick and pick["dsr"] >= DSR_PASS),
           "reason": reason(by), "money": money_rows, "bench": bsum, "check": chk,
           "pool": {k: pool[k] for k in ("n_trials", "var", "sr0_annual")},
           "pool_small": {k: pool_small[k] for k in ("n_trials", "var", "sr0_annual")},
           "oos_days": int(len(od)), "oos_from": dc.day_str(int(od[0])), "oos_to": dc.day_str(int(od[-1])),
           "is_days": int(i1 - i0 + 1), "listed_mean": float((lst & inset).sum(1).mean()),
           "listed_min": int((lst & inset).sum(1).min()), "hl_funding_share": float(hl_rec.sum() / max((inset & lst).sum(), 1)),
           "dec_coins": len(held), "eurusd_mean": float(fx.mean()), "trials": [t["id"] for t in T]}
    rep.mkdir(parents=True, exist_ok=True)
    (rep / "latest.json").write_text(json.dumps(out, indent=1, default=float), encoding="utf-8")
    dc.write_results(NAME, markdown(out), HEAD)
    log(f"done; passed: {out['passed'] or 'none'}")
    return 0


def reason(by: dict) -> dict[int, str]:
    """Per k, why the judged cell fails (prereg): minimum, funding or no edge; 'pass' when it passes. An ideal
    account that fails on its drawdown alone is named so rather than 'no edge'."""
    out = {}
    for k in KS:
        a = by[cell_key("230usd", k, 1, "base", "taker")]
        i = by[cell_key("ideal", k, 1, "base", "taker")]
        first4 = [v for n, v in a["checks"].items() if "correlation" not in n]
        ideal4 = [v for n, v in i["checks"].items() if "correlation" not in n]
        ideal_dd = [v for n, v in i["checks"].items() if "correlation" not in n and "drawdown" not in n]
        if a["pass"]:
            out[k] = "pass"
        elif all(ideal_dd) and not all(ideal4):
            out[k] = "drawdown (the ideal account's too)"
        elif not all(ideal4):
            out[k] = "no edge"
        elif not all(first4) and a["sharpe_no_funding"] > PASS_SHARPE:
            out[k] = "funding"
        else:
            out[k] = "minimum"
    return out


# ---------------------------------------------------------------- the report

HEAD = """# M4H: the M4 reg7n long/short at a 200 EUR account on Hyperliquid, after every cost

Pre-registered in `results/m4h_prereg.md` (committed before the first run). Code: `lab.experiments.m4h`, tests
`tests/test_m4h.py`. Paper only: nothing a live bot, a wallet or the engine reads changed.
"""


def _f(v, nd: int = 2, pct: bool = False) -> str:
    if v is None:
        return "n/a"
    if isinstance(v, str):
        return v
    if isinstance(v, float) and not math.isfinite(v):
        return "n/a"
    return f"{v * 100:.{nd - 1}f} %" if pct else f"{v:.{nd}f}"


COLS = [("cell", "cell", None), ("sharpe", "Sharpe", 2), ("cagr", "CAGR", -2), ("max_dd", "max DD", -2),
        ("end", "end", 2), ("worst_month_ret", "worst month", -2), ("boot_p05", "boot 5 %", 2),
        ("corr_ideal", "corr ideal", 2), ("drift", "drift", 2), ("skip_share", "skipped", -2),
        ("cut_skipped", "cuts skipped", 0), ("fees_ann", "fees/yr", -2), ("slip_ann", "slip/yr", -2),
        ("funding_ann", "funding/yr", -2), ("dsr", "DSR", 3), ("is_sharpe", "IS Sharpe", 2), ("fails", "fails", None)]


def _cell(r: dict, key: str, nd) -> str:
    if key == "fails":
        return "pass" if r["pass"] else "; ".join(n for n, ok in r["checks"].items() if not ok)
    v = r.get(key)
    if nd is None:
        return str(v)
    if nd == 0:
        return str(int(v))
    return _f(v, abs(nd), pct=nd < 0)


def table(rows: list[dict]) -> str:
    out = ["| " + " | ".join(h for _, h, _ in COLS) + " |", "|" + "---|" * len(COLS)]
    for r in rows:
        out.append("| " + " | ".join(_cell(r, k, nd) for k, _, nd in COLS) + " |")
    return "\n".join(out)


def markdown(o: dict) -> str:
    rows = o["rows"]
    by = {r["cell"]: r for r in rows}
    md = [f"Generated {o['generated']}. xs_daily's panel cut at {CUT}, reg7n refit walk-forward (T6b), nothing from "
          f"{LOCKBOX} read. In sample {IS_FROM} to {IS_TO} ({o['is_days']} days, Binance universe, Binance funding); "
          f"judged {o['oos_from']} to {o['oos_to']} ({o['oos_days']} decision days) on the coins Hyperliquid lists of "
          f"the 100 most liquid perps (mean {o['listed_mean']:.0f} a day, at least {o['listed_min']}), Hyperliquid's "
          f"own funding on {o['hl_funding_share'] * 100:.0f} % of those coin-days. {len(o['trials'])} trials in R5's "
          f"registry (small family, with their in-sample Sharpes, registered before any out-of-sample number); pool "
          f"{o['pool']['n_trials']:,}, noise bar {o['pool']['sr0_annual']:.2f} a year (small {o['pool_small']['n_trials']}, "
          f"{o['pool_small']['sr0_annual']:.2f}).\n"]
    c = o["check"]
    md.append(f"Check, reported (M4H2; M4H stopped on it): the rebuilt 10/10 book on Binance at 41 bps makes a 2022-2023 "
              f"Sharpe of {c['is']:.2f} (m4_residual {c['is_published']}; 2022 {c['is_by_year']['2022']:.2f}, 2023 "
              f"{c['is_by_year']['2023']:.2f}), 2024 {c['2024']:.2f} ({c['published']['2024']}), 2025 {c['2025']:.2f} "
              f"({c['published']['2025']}).\n")
    md.append(f"Passed (230 USD, taker, on time, 1x): {', '.join(o['passed']) or 'none'}. Paper book k: "
              f"{o['pick'] or 'none'}; confirmed (DSR at least 0.95): {'yes' if o['confirmed'] else 'no'}. Why, by k: "
              + ", ".join(f"k {k}: {v}" for k, v in o["reason"].items()) + ".\n")
    md.append("## What 230 USD made, against 200 EUR in an ETF, the same days\n")
    md.append("| cell | end USD | EUR gained | EUR a year (5 % to 95 %) | worst month | 2024 | 2025 | 2026 |")
    md.append("|---|---|---|---|---|---|---|---|")
    for m in o["money"]:
        y = m["by_year"]
        md.append(f"| {m['cell']} | {m['end_usd']:.0f} | {m['gain_eur']:+.0f} | {m['eur_year']:+.0f} "
                  f"({m['eur_year_p05']:+.0f} to {m['eur_year_p95']:+.0f}) | {m['worst_month']} "
                  f"{_f(m['worst_month_ret'], 2, True)} | {_f(y['2024'], 2, True)} | {_f(y['2025'], 2, True)} | "
                  f"{_f(y['2026'], 2, True)} |")
    md.append("\n| held | Sharpe | CAGR | max DD | 200 EUR became | 2024 | 2025 | 2026 |")
    md.append("|---|---|---|---|---|---|---|---|")
    for n, b in o["bench"].items():
        y = b["by_year"]
        md.append(f"| {n} | {b['sharpe']:.2f} | {_f(b['cagr'], 2, True)} | {_f(b['max_dd'], 2, True)} | "
                  f"{b['eur']['end_eur']:.0f} EUR | {_f(y['2024'], 2, True)} | {_f(y['2025'], 2, True)} | "
                  f"{_f(y['2026'], 2, True)} |")
    md.append(f"\nEUR at the day's rate (mean {o['eurusd_mean']:.4f}); the ETFs' years in their own currency (EUNL "
              "EUR, SPY and BTC USD), 200 EUR in EUR. EUR a year: the mean daily return x 365 x 230 USD at the "
              "window's mean rate, the band the 5 % and 95 % of its stationary bootstrap.\n")
    md.append("## The judged cells and their siblings (out of sample)\n")
    md.append("Drift: the mean of half the sum of |account weight - ideal weight|; skipped: the share of wanted entries "
              "the 10 USD minimum (or rounding to zero) did not send; fees, slippage and funding as a share of equity a "
              "year; DSR over all trials.\n")
    for acc in ("230usd", "115usd", "460usd", "ideal"):
        for g in GROSS:
            sel = [by[cell_key(acc, k, g, f, fe)] for k in KS for f in FILLS for fe in FEES]
            md.append(f"\n### {acc}, gross {g}x\n")
            md.append(table(sel))
    md.append("\n## By year, 230 USD, taker, on time, 1x (Sharpe)\n")
    md.append("| k | 2024 | 2025 | 2026 | stop at -20 % |")
    md.append("|---|---|---|---|---|")
    for k in KS:
        r = by[cell_key("230usd", k, 1, "base", "taker")]
        md.append(f"| {k} | " + " | ".join(_f(r["by_year"][str(y)]) for y in YEARS_OOS)
                  + f" | {r['stop_day'] or 'never'} |")
    return "\n".join(md) + "\n"


if __name__ == "__main__":
    sys.exit(main())
