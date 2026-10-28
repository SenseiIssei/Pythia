"""T11: cross-venue funding, Hyperliquid against Binance USD-M, delta neutral.

Pre-registered in results/hl_funding_t11_prereg.md; results in results/hl_funding_t11.md.

    PYTHIA_TRIALS_REGISTRY=<registry> PYTHIA_REPORTS=<reports> \
        flock <heavy lock> python -m lab.experiments.hl_funding_t11 [--no-register]

Hyperliquid's settled hourly funding (lab.collect.hyperliquid, point in time) against Binance's
USD-M settlements (8 h, or the interval in force) for the coins on both venues inside T5's PIT50.
Every day at 23:00 UTC the gap of the last W hours (its mean and the share of hours on the mean's
side) decides; the pair (short the venue with the higher funding, long the other, 10 % of capital
a leg) is filled one hour late at 00:00 and marked once a day (Binance's perp daily close,
Hyperliquid's as Binance spot times its hourly premium). Costs: both venues' taker fees of their
era plus T5's half-spread tiers (Hyperliquid one tier wider; at 10k a leg one more each). Inputs
cut at 2026-06-30 24:00: the lockbox is never read. Nothing here changes a book, the engine or a
wallet.
"""

from __future__ import annotations

import json
import math
import sys
import time
from datetime import datetime, timezone

import numpy as np
import polars as pl

from .. import metrics
from ..data import ROOT
from . import director_common as dc
from . import fam_common as fc
from . import pit_universe_t5 as t5

NAME = "hl_funding_t11"
H = 3_600_000_000
DAY_US = fc.DAY_US
FIRST, START, IS_TO, VAL_FROM, VAL_TO = "2023-05-12", "2023-05-13", "2023-12-31", "2024-01-01", "2026-06-30"
DECIDE_H = 23                           # the decision at 23:00 UTC, filled at the next 00:00 (one hour late)
THETAS, WINDOWS, PERSIST = (0.15, 0.30), (8, 24), 0.75
MAX_POS, LEG, MARGIN, BIG_MOVE = 10, 0.10, 0.5, 0.25
YEAR_H = 8760
BN_FEE = t5.PERP_FEE                    # USD-M taker, T5's
HL_FEES = (("2024-01-01", 0.00025), ("2025-05-01", 0.00035), (None, 0.00045))   # base-tier taker, until (excl.)
HALF = tuple(h for _, h in t5.SPREAD_TIERS) + (t5.SPREAD_BELOW,)
WIDER = {"1k": (0, 1), "10k": (1, 2)}  # tiers wider than the coin's own: (Binance, Hyperliquid)
GATE_SHARPE, GATE_CORR, MIN_ENTRIES, DSR_PASS, PBO_PASS = 0.5, 0.3, 20, 0.95, 0.2
PIT_N = 50


def base_of(coin: str) -> str:
    """Hyperliquid's name to the base: kPEPE (a thousand PEPE) is PEPE."""
    return coin[1:] if len(coin) > 1 and coin[0] == "k" and coin[1:].isupper() else coin


def variant(theta: float, W: int) -> str:
    return f"{round(theta * 100)}_{W}"


# ---------------------------------------------------------------- hourly funding (what the decision reads)

def hourly(hl: pl.DataFrame, bn: pl.DataFrame, coins: list[str], hours: np.ndarray) -> dict:
    """(Th, N) matrices on the hour grid, each row at the hour of its stamp: Hyperliquid's rate a hour and when it
    was known, its premium; Binance's settlement rate and its interval in hours (NaN where none). hl: ts_us, coin,
    funding_rate, known_us (and premium); bn: coin, funding_time_us, interval_hours, funding_rate."""
    Th, N = len(hours), len(coins)
    ci = {c: j for j, c in enumerate(coins)}
    out = {k: np.full((Th, N), np.nan) for k in ("hl", "hl_known", "prem", "bn", "bn_iv")}

    def put(df: pl.DataFrame, ts: str, cols: dict) -> None:
        if not df.height:
            return
        k = (df[ts].to_numpy() // H * H - hours[0]) // H
        j = np.array([ci.get(c, -1) for c in df["coin"].to_list()])
        ok = (k >= 0) & (k < Th) & (j >= 0)
        for name, col in cols.items():
            if col in df.columns:
                out[name][k[ok], j[ok]] = df[col].cast(pl.Float64).fill_null(np.nan).to_numpy()[ok]
    put(hl, "ts_us", {"hl": "funding_rate", "hl_known": "known_us", "prem": "premium"})
    put(bn, "funding_time_us", {"bn": "funding_rate", "bn_iv": "interval_hours"})
    return out


def ffill(x: np.ndarray) -> np.ndarray:
    """Forward fill along time (NaN before the first value)."""
    idx = np.where(np.isfinite(x), np.arange(len(x))[:, None], 0)
    np.maximum.accumulate(idx, axis=0, out=idx)
    return x[idx, np.arange(x.shape[1])[None, :]]


def gap(Hm: dict) -> np.ndarray:
    """(Th, N) the hourly gap a year: Hyperliquid's rate of the hour less Binance's last settled rate per hour."""
    with np.errstate(invalid="ignore", divide="ignore"):
        b = ffill(Hm["bn"] / Hm["bn_iv"])
    return (Hm["hl"] - b) * YEAR_H


def signals(Hm: dict, hours: np.ndarray, W: int, decide_h: int = DECIDE_H) -> tuple[np.ndarray, ...]:
    """(Td, N) at each day's decision hour K: the mean gap G over hours K-W to K-1 among rows known by then, the
    share of the W hours on G's side, and whether both venues list the coin (first rows known before K-W)."""
    g = gap(Hm)
    Td = (len(hours) - 1) // 24
    N = g.shape[1]
    G, share, listed = np.full((Td, N), np.nan), np.zeros((Td, N)), np.zeros((Td, N), dtype=bool)
    known = np.where(np.isfinite(Hm["hl_known"]), Hm["hl_known"], np.inf)
    first_hl = known.min(0)
    has_bn = np.isfinite(Hm["bn"])
    first_bn = np.where(has_bn.any(0), np.argmax(has_bn, 0), len(hours))
    for t in range(Td):
        K = 24 * t + decide_h
        if K - W < 0:
            continue
        w = g[K - W:K]
        use = np.isfinite(w) & (known[K - W:K] <= hours[K])
        n = use.sum(0)
        with np.errstate(invalid="ignore", divide="ignore"):
            m = np.where(n > 0, np.where(use, w, 0).sum(0) / n, np.nan)
        G[t] = m
        share[t] = (use & (np.sign(w) == np.sign(m)[None, :]) & (m != 0)[None, :]).sum(0) / W
        listed[t] = (first_hl <= hours[K - W]) & (first_bn < K - W)
    return G, share, listed


def decide(Hm: dict, hours: np.ndarray, elig: np.ndarray, theta: float, W: int) -> np.ndarray:
    """(Td, N) the pair held after each day's fill: +1 short Hyperliquid and long Binance, -1 the reverse, 0 none.
    Row t is decided at 23:00 of day t and filled at 00:00 of day t + 1. elig (Td, N): the day's universe and bars
    as known at the decision (the caller lags them)."""
    G, share, listed = signals(Hm, hours, W)
    Td, N = G.shape
    out = np.zeros((Td, N), dtype=np.int8)
    held = np.zeros(N, dtype=np.int8)
    for t in range(Td):
        ok = elig[t] & listed[t] & np.isfinite(G[t])
        g = np.nan_to_num(G[t])
        cur = held.copy()
        cur[(cur != 0) & (~ok | (g * cur <= 0))] = 0
        cand = np.flatnonzero((cur == 0) & ok & (np.abs(g) >= theta) & (share[t] >= PERSIST))
        free = MAX_POS - int((cur != 0).sum())
        if free > 0 and len(cand):
            pick = cand[np.argsort(-np.abs(g[cand]), kind="stable")][:free]
            cur[pick] = np.sign(g[pick]).astype(np.int8)
        out[t] = held = cur
    return out


# ---------------------------------------------------------------- the book

def daily_funding(Hm: dict, Td: int) -> tuple[np.ndarray, np.ndarray]:
    """(Td, N) Hyperliquid's and Binance's rates settled in day t's hours after 00:00 up to the next 00:00
    (a pair filled at 00:00 of day t is paid from the settlement after it)."""
    def day_sum(x: np.ndarray) -> np.ndarray:
        return np.nan_to_num(x[1:1 + 24 * Td]).reshape(Td, 24, -1).sum(1)
    return day_sum(Hm["hl"]), day_sum(Hm["bn"])


def marks(D: dict) -> tuple[np.ndarray, np.ndarray]:
    """(Td, N) daily returns of the two legs' marks at each day's close: Binance's perp close, and Hyperliquid's as
    Binance spot's close times (1 + its premium of the hour ending at the close). 0 where a mark is missing."""
    Td = len(D["days"])
    prem = ffill(D["prem"])[24:24 * Td + 1:24]
    hl = D["spot"] * (1 + np.nan_to_num(prem))

    def ret(p: np.ndarray) -> np.ndarray:
        p = ffill(p)
        r = np.zeros_like(p)
        with np.errstate(invalid="ignore", divide="ignore"):
            r[1:] = p[1:] / p[:-1] - 1
        return np.nan_to_num(r, posinf=0.0, neginf=0.0)
    return ret(D["perp"]), ret(hl)


def tier(vol: np.ndarray) -> np.ndarray:
    """T5's half-spread tier index of a 30-day median dollar volume (0 at 1 B or more, 4 below 1 M)."""
    v = np.nan_to_num(vol, nan=0.0)
    return sum((v < lo).astype(int) for lo, _ in t5.SPREAD_TIERS)


def hl_fee(days: np.ndarray) -> np.ndarray:
    out = np.full(len(days), HL_FEES[-1][1])
    for until, fee in reversed(HL_FEES[:-1]):
        out = np.where(days < dc.us(until), fee, out)
    return out


def costs(days: np.ndarray, vol: np.ndarray, size: str = "1k") -> np.ndarray:
    """(Td, N) cost of one side of the pair (both legs) per unit of a leg's notional, traded at day t's close, on
    the volume known at the previous close."""
    v = np.vstack([np.full((1, vol.shape[1]), np.nan), vol[:-1]])
    i = tier(v)
    half = np.array(HALF)
    wb, wh = WIDER[size]
    return BN_FEE + half[np.minimum(i + wb, 4)] + hl_fee(days)[:, None] + half[np.minimum(i + wh, 4)]


def book(D: dict, target: np.ndarray, size: str = "1k") -> dict:
    """Daily series on capital: net, funding, price, cost; pairs held, entries."""
    Td = len(D["days"])
    hf, bf = daily_funding(D, Td)
    rb, rh = marks(D)
    pos = np.vstack([np.zeros((1, target.shape[1])), target[:-1]]).astype(float)   # held over day t, traded from
    fund = LEG * (pos * (hf - bf)).sum(1)
    price = LEG * (pos * (rb - rh)).sum(1)
    cost = LEG * (np.abs(target - pos) * costs(D["days"], D["vol"], size)).sum(1)
    fee = LEG * (np.abs(target - pos) * (BN_FEE + hl_fee(D["days"]))[:, None]).sum(1)
    entries = ((target != 0) & (target != pos)).sum(1)
    move = np.where(pos != 0, np.maximum(np.abs(rb), np.abs(rh)), 0.0)
    return {"net": fund + price - cost, "funding": fund, "price": price, "cost": cost, "fee": fee,
            "pairs": (pos != 0).sum(1), "entries": entries, "move": move.max(1),
            "big_moves": (move >= BIG_MOVE).sum(1)}


def eligible(D: dict) -> np.ndarray:
    """(Td, N) what a decision at 23:00 of day t may use: PIT50 and both daily bars as of the close of day t - 1."""
    e = D["uni"] & np.isfinite(D["spot"]) & np.isfinite(D["perp"])
    return np.vstack([np.zeros((1, e.shape[1]), dtype=bool), e[:-1]])


def targets_frame(D: dict, theta: float, W: int):
    """The decision as a function of the funding rows (T1's frame mode): {"hl", "bn"} frames with known_us to one
    row per decision (ts_us its time, coin, side)."""
    el = eligible(D)
    dec = D["hours"][24 * np.arange(len(D["days"])) + DECIDE_H]

    def fn(fr: dict) -> pl.DataFrame:
        T = decide(hourly(fr["hl"], fr["bn"], D["coins"], D["hours"]), D["hours"], el, theta, W)
        Td, N = T.shape
        return pl.DataFrame({"ts_us": np.repeat(dec, N), "coin": D["coins"] * Td,
                             "side": T.reshape(-1).astype(float)})
    return fn


# ---------------------------------------------------------------- data

def binance_rows(coins: list[str], cut_us: int) -> tuple[pl.DataFrame, dict[str, np.ndarray]]:
    """Binance funding settlements (with known_us at the settlement) and daily perp closes {coin: (ts, close)}."""
    from .kraken_funding_gap import binance_perp
    fr, kl = [], {}
    for c in coins:
        s = binance_perp(base_of(c))
        if s is None:
            continue
        files = sorted((ROOT / "hist" / "binance_um" / "funding" / f"symbol={s}").glob("*.parquet"))
        if files:
            f = pl.concat([pl.read_parquet(p, columns=["funding_time_us", "interval_hours", "funding_rate"])
                           for p in files], how="vertical_relaxed")
            fr.append(f.unique("funding_time_us").filter(pl.col("funding_time_us") // H * H <= cut_us)
                      .with_columns(coin=pl.lit(c), known_us=pl.col("funding_time_us"),
                                    interval_hours=pl.col("interval_hours").cast(pl.Float64)))
        files = sorted((ROOT / "hist" / "binance_um" / "klines_1d" / f"symbol={s}").glob("*.parquet"))
        if files:
            k = pl.concat([pl.read_parquet(p, columns=["open_time_us", "close"]) for p in files],
                          how="vertical_relaxed").unique("open_time_us")
            kl[c] = (k["open_time_us"].to_numpy(), k["close"].to_numpy())
    bn = pl.concat(fr, how="vertical_relaxed") if fr else pl.DataFrame(
        schema={"funding_time_us": pl.Int64, "interval_hours": pl.Float64, "funding_rate": pl.Float64,
                "coin": pl.String, "known_us": pl.Int64})
    return bn.select("coin", "funding_time_us", "interval_hours", "funding_rate", "known_us"), kl


def load(P: fc.Panel | None = None) -> dict:
    """Everything on the day grid FIRST to VAL_TO and its hour grid (24 a day plus the closing hour)."""
    from .. import universe as U
    from ..collect import book_depth, hyperliquid, pit
    days = np.arange(dc.us(FIRST), dc.us(VAL_TO) + DAY_US, DAY_US, dtype=np.int64)
    hours = days[0] + np.arange(24 * len(days) + 1, dtype=np.int64) * H
    cut = int(hours[-1])
    hl = (pl.read_parquet(pit.FREE / hyperliquid.SOURCE / "funding.parquet",
                          columns=["ts_us", "coin", "funding_rate", "premium", "known_us"])
          .filter(pl.col("ts_us") // H * H <= cut))
    coins = sorted(hl["coin"].unique().to_list())
    P = P or dc.cut_panel(fc.load_panel(), VAL_TO)
    vol = U.median_volume(P)
    delist = book_depth.read_delistings()
    uni = U.pit(P, PIT_N, table=delist if len(delist) else None, vol=vol)
    col = {n: j for j, n in enumerate(P.names)}
    pi = np.searchsorted(P.days, days)
    inside = (pi < P.T) & (P.days[np.minimum(pi, P.T - 1)] == days)
    bn, kl = binance_rows(coins, cut)
    keep = [c for c in coins if f"{base_of(c)}USDT" in col and c in kl]
    N, Td = len(keep), len(days)
    spot, perp, v = (np.full((Td, N), np.nan) for _ in range(3))
    u = np.zeros((Td, N), dtype=bool)
    for j, c in enumerate(keep):
        k = col[f"{base_of(c)}USDT"]
        spot[inside, j] = P.close[pi[inside], k]
        v[inside, j] = vol[pi[inside], k]
        u[inside, j] = uni[pi[inside], k]
        ts, cl = kl[c]
        di = (ts - days[0]) // DAY_US
        ok = (di >= 0) & (di < Td)
        perp[di[ok], j] = cl[ok]
    btc = np.zeros(Td)
    btc[inside] = np.nan_to_num(P.ret[pi[inside], P.btc])
    Hm = hourly(hl, bn.filter(pl.col("coin").is_in(keep)), keep, hours)
    return {"days": days, "hours": hours, "coins": keep, "spot": spot, "perp": perp, "vol": v, "uni": u,
            "btc": btc, **Hm, "frames": {"hl": hl.filter(pl.col("coin").is_in(keep)).drop("premium"),
                                         "bn": bn.filter(pl.col("coin").is_in(keep))}}


# ---------------------------------------------------------------- measuring

def window(days: np.ndarray, a: str, b: str) -> np.ndarray:
    return (days >= dc.us(a)) & (days <= dc.us(b))


def stats_of(B: dict, m: np.ndarray, btc: np.ndarray) -> dict:
    x = B["net"][m]
    p = fc.perf(x)
    ent = int(B["entries"][m].sum())
    pair_days = int(B["pairs"][m].sum())
    c = float(np.corrcoef(x, btc[m])[0, 1]) if x.std() > 0 and btc[m].std() > 0 else 0.0
    return {"sharpe": p["sharpe"], "cagr": p["cagr"], "max_dd": p["max_dd"], "days": p["days"], "corr_btc": c,
            "entries": ent, "avg_pairs": float(B["pairs"][m].mean()),
            "avg_hold_days": pair_days / ent if ent else float("nan"),
            **{f"{k}_ann": float(B[k][m].mean() * 365) for k in ("funding", "price", "cost", "fee", "net")}}


def trial(id_: str, is_sharpe: float) -> dict:
    return {"id": id_, "family": "hand", "n": 1, "sharpe": float(is_sharpe),
            "source": "results/hl_funding_t11_prereg.md"}


def coin_table(D: dict, m_days: np.ndarray) -> list[dict]:
    """Per coin over the given days' hours: Hyperliquid's and Binance's mean funding a year (what a long pays),
    the mean gap, the share of hours with |gap| at least 15 % and 30 % a year (information only)."""
    hm = np.repeat(m_days, 24)
    hm = np.r_[False, hm][:len(D["hours"])]
    g = gap(D)[hm]
    with np.errstate(invalid="ignore", divide="ignore"):
        b = ffill(D["bn"] / D["bn_iv"])[hm] * YEAR_H
    h = D["hl"][hm] * YEAR_H
    rows = []
    for j, c in enumerate(D["coins"]):
        ok = np.isfinite(g[:, j])
        if ok.sum() < 24:
            continue
        rows.append({"coin": c, "hours": int(ok.sum()), "hl_ann_pct": float(h[ok, j].mean() * 100),
                     "binance_ann_pct": float(b[ok, j].mean() * 100), "gap_ann_pct": float(g[ok, j].mean() * 100),
                     "share_abs_gap_15": float((np.abs(g[ok, j]) >= 0.15).mean()),
                     "share_abs_gap_30": float((np.abs(g[ok, j]) >= 0.30).mean())})
    return sorted(rows, key=lambda r: -abs(r["gap_ann_pct"]))


def capacity_info(coins: list[str], cut_us: int) -> list[dict]:
    """Today's Hyperliquid open interest and day volume (the newest snapshot, after the windows), and T4's measured
    cost of a 10k USD market order on Binance's perp: its days inside the windows (to cut_us), from when, the mean
    there, and the mean over all its days (information; the registered rule charges the tiers)."""
    from ..collect import hyperliquid, pit
    rows = {}
    try:
        c = pl.read_parquet(pit.FREE / hyperliquid.SOURCE / "ctx.parquet").sort("ts_us").unique("coin", keep="last")
        for r in c.iter_rows(named=True):
            if r["coin"] in coins:
                rows[r["coin"]] = {"coin": r["coin"], "hl_oi_musd": (r["oi_usd"] or 0) / 1e6,
                                   "hl_day_volume_musd": (r["day_volume_usd"] or 0) / 1e6}
    except (OSError, pl.exceptions.PolarsError):
        pass
    try:
        from ..features import book
        t = book.book_table("1d", {base_of(c) for c in coins})
        inw = pl.col("ts_us") < cut_us
        m = t.group_by("asset").agg(depth_days_in_windows=inw.sum(), depth_from=pl.col("ts_us").min(),
                                    cost10k_in_windows_bps=pl.col("cost10k").filter(inw).mean(),
                                    cost10k_all_bps=pl.col("cost10k").mean())
        for r in m.iter_rows(named=True):
            for c in coins:
                if base_of(c) == r["asset"]:
                    rows.setdefault(c, {"coin": c}).update(
                        {k: v for k, v in r.items() if k != "asset"}, depth_from=dc.day_str(r["depth_from"]))
    except Exception:           # noqa: BLE001 (no depth files: the columns stay empty)
        pass
    return sorted(rows.values(), key=lambda r: -r.get("hl_oi_musd", 0))


def run(D: dict, register: bool = True, leak: bool = True, log=print) -> dict:
    days, btc = D["days"], D["btc"]
    ins, val = window(days, START, IS_TO), window(days, VAL_FROM, VAL_TO)
    el = eligible(D)
    keys = [(th, W) for th in THETAS for W in WINDOWS]
    T = {variant(th, W): decide(D, D["hours"], el, th, W) for th, W in keys}
    B = {k: book(D, t) for k, t in T.items()}
    is_s = {k: dc.sharpe(b["net"][ins]) for k, b in B.items()}
    pick = max(is_s, key=lambda k: is_s[k])
    B10 = book(D, T[pick], "10k")
    trials = [trial(f"hand:t11:hl_funding:{k}", s) for k, s in is_s.items()]
    trials.append(trial(f"hand:t11:hl_funding:{pick}:10k", dc.sharpe(B10["net"][ins])))
    if register:
        metrics.register(trials)                         # before any validation number exists
    log("  in sample " + ", ".join(f"{t['id'].split(':', 3)[-1]} {t['sharpe']:.2f}" for t in trials))
    extra = dc.ledger_trials() + trials
    p_all, p_fam = metrics.trial_pool(extra=extra), metrics.trial_pool("hand", extra=extra)
    x = B[pick]["net"][val]
    v = stats_of(B[pick], val, btc)
    lo, hi, _ = dc.boot_band(x)
    both = ins | val
    pbo = metrics.cscv(np.column_stack([B[k]["net"][both] for k in B]))
    th, W = next((th, W) for th, W in keys if variant(th, W) == pick)
    lk = None
    if leak:
        from .. import leak as L
        lk = L.check(targets_frame(D, th, W), D["frames"], time="known_us", out_time="ts_us", keys=("coin",),
                     name=f"t11 decision {pick}")
    gates = {"Sharpe above 0.5": v["sharpe"] > GATE_SHARPE, "bootstrap 5 % above 0": lo > 0,
             "correlation with BTC within +-0.3": abs(v["corr_btc"]) < GATE_CORR,
             "at least 20 entries": v["entries"] >= MIN_ENTRIES}
    from .two_leads_t6 import needed_sharpe
    cond = {"1 gates": all(gates.values()), "2 DSR all": metrics.dsr(x, p_all) >= DSR_PASS,
            "3 DSR family": metrics.dsr(x, p_fam) >= DSR_PASS,
            "4 PBO": pbo is not None and pbo["pbo"] < PBO_PASS, "5 leak": bool(lk and lk["ok"])}
    held = B[pick]["pairs"][val] > 0
    yrs = dc.years_of(days)
    by_year = {int(y): stats_of(B[pick], val & (yrs == y), btc) for y in np.unique(yrs[val])}
    return {"pick": pick, "is_sharpe": is_s, "coins": D["coins"],
            "variants": {k: {"is": stats_of(b, ins, btc), "val": stats_of(b, val, btc)} for k, b in B.items()},
            "val": v, "by_year": by_year, "val_10k": stats_of(B10, val, btc), "is_10k": stats_of(B10, ins, btc),
            "band": [lo, hi],
            "gates": gates, "dsr_all": metrics.dsr(x, p_all), "dsr_family": metrics.dsr(x, p_fam),
            "pool_all": {"n_trials": p_all["n_trials"], "sr0_annual": p_all["sr0_annual"]},
            "pool_family": {"n_trials": p_fam["n_trials"], "sr0_annual": p_fam["sr0_annual"]},
            "needed_sharpe": {"all": needed_sharpe(x, p_all), "family": needed_sharpe(x, p_fam)},
            "pbo": pbo,
            "leak": None if lk is None else {k: lk.get(k) for k in ("ok", "runs", "cuts", "first", "error")},
            "conditions": cond, "passes": all(cond.values()),
            "margin": {"max_move": float(B[pick]["move"][val].max()) if val.any() else 0.0,
                       "days_big_move": int((B[pick]["big_moves"][val] > 0).sum()), "days_held": int(held.sum())},
            "per_coin": coin_table(D, both), "trials": [t["id"] for t in trials],
            "from": dc.day_str(days[val][0]), "to": dc.day_str(days[val][-1]),
            "is_from": dc.day_str(days[ins][0]), "is_to": dc.day_str(days[ins][-1])}


# ---------------------------------------------------------------- the report

def _pct(v) -> str:
    return "n/a" if v is None or (isinstance(v, float) and not math.isfinite(v)) else f"{v * 100:.1f} %"


def markdown(out: dict) -> str:
    r = out["run"]
    md = [f"Generated {out['generated']}. Registered in `results/hl_funding_t11_prereg.md` before the run. "
          f"{len(r['coins'])} coins on both venues: {', '.join(r['coins'])}. In sample {r['is_from']} to "
          f"{r['is_to']}, validation {r['from']} to {r['to']}; inputs cut at {VAL_TO} 24:00, the lockbox not read. "
          f"Costs: {out['costs']}.\n", "## Every variant\n"]
    t = []
    for k, x in r["variants"].items():
        a, b = x["is"], x["val"]
        t.append({"variant (theta % _ W h)": k + (" (pick)" if k == r["pick"] else ""),
                  "IS Sharpe": a["sharpe"], "IS entries": a["entries"], "val Sharpe": b["sharpe"],
                  "val CAGR": _pct(b["cagr"]), "val DD": _pct(b["max_dd"]), "val corr BTC": b["corr_btc"],
                  "val entries": b["entries"], "avg pairs": b["avg_pairs"], "avg hold d": b["avg_hold_days"],
                  "funding / price / cost a year": f"{_pct(b['funding_ann'])} / {_pct(b['price_ann'])} / "
                                                   f"{_pct(-b['cost_ann'])}"})
    md.append(dc.table(t, list(t[0])) + "\n")
    md.append("Returns on all capital (10 % a leg, 2x margin a leg, at most 10 pairs); funding received net of paid, "
              "price the long leg's mark less the short's, costs both legs at entry and exit.\n")
    v, w = r["val"], r["val_10k"]
    md.append(f"## The pick {r['pick']} in validation\n\nSharpe {v['sharpe']:.2f} (90 % band {r['band'][0]:.2f} to "
              f"{r['band'][1]:.2f}), {_pct(v['cagr'])} a year, drawdown {_pct(v['max_dd'])}, correlation with BTC "
              f"{v['corr_btc']:+.2f}, {v['entries']} entries, {v['avg_pairs']:.1f} pairs on average.\n\n"
              f"Capacity: at 1k USD a leg as above; at 10k a leg (half spreads one tier wider) Sharpe "
              f"{w['sharpe']:.2f}, {_pct(w['cagr'])} a year, costs {_pct(-w['cost_ann'])} a year against "
              f"{_pct(-v['cost_ann'])}.\n\nOf the costs at 1k, taker fees {_pct(-v['fee_ann'])} a year and half "
              f"spreads {_pct(v['fee_ann'] - v['cost_ann'])}.\n")
    t = [{"year": y, "Sharpe": x["sharpe"], "net": _pct(x["net_ann"]), "funding": _pct(x["funding_ann"]),
          "price": _pct(x["price_ann"]), "cost": _pct(-x["cost_ann"]), "entries": x["entries"],
          "avg pairs": x["avg_pairs"]} for y, x in r["by_year"].items()]
    md.append("The pick by year of validation (a year on all capital):\n\n" + dc.table(t, list(t[0])) + "\n")
    pb, lk = r["pbo"], r["leak"]
    ev = {"1 gates": "; ".join(f"{k} {'yes' if x else 'no'}" for k, x in r["gates"].items()),
          "2 DSR all": f"{r['dsr_all']:.3f} over {r['pool_all']['n_trials']:,} trials (noise bar "
                       f"{r['pool_all']['sr0_annual']:.2f} a year)",
          "3 DSR family": f"{r['dsr_family']:.3f} over the hand family's {r['pool_family']['n_trials']:,} "
                          f"({r['pool_family']['sr0_annual']:.2f})",
          "4 PBO": f"{pb['pbo']:.2f} over {pb['genomes']} variants, {pb['combos']:,} splits" if pb else "n/a",
          "5 leak": ("not run" if lk is None else
                     f"no leak ({lk['runs']} runs at {', '.join(lk['cuts'])})" if lk["ok"] else
                     f"LEAK {lk['first']}" + (f" ({lk['error']})" if lk.get("error") else ""))}
    md.append(dc.table([{"condition": k, "result": "pass" if ok else "fail", "evidence": ev[k]}
                        for k, ok in r["conditions"].items()], ["condition", "result", "evidence"]) + "\n")
    md.append(f"**{'Passes: a lockbox look is due (not made here)' if r['passes'] else 'Fails'}.** The DSR bar on "
              f"this pool needs a validation Sharpe of about {r['needed_sharpe']['all']:.2f} (all) / "
              f"{r['needed_sharpe']['family']:.2f} (hand) on as many days.\n")
    mg = r["margin"]
    md.append(f"Margin: the largest one-day move of a held coin's mark in validation {_pct(mg['max_move'])}; "
              f"{mg['days_big_move']} of {mg['days_held']} held days with a move of 25 % or more (a 2x leg's margin "
              "half gone, a transfer between the venues needed that day).\n")
    md.append("## Hyperliquid against Binance funding per coin, in sample and validation (information only)\n")
    md.append(dc.table(r["per_coin"], list(r["per_coin"][0])) + "\n" if r["per_coin"] else "none\n")
    md.append("Mean funding a year a long pays (%), Binance's rate in force each hour; the share of hours with the "
              "gap at least 15 % / 30 % a year either way.\n")
    if out["capacity"]:
        md.append("## Capacity today (information, after the windows)\n")
        cols = ["coin", "hl_oi_musd", "hl_day_volume_musd", "depth_from", "depth_days_in_windows",
                "cost10k_in_windows_bps", "cost10k_all_bps"]
        md.append(dc.table([{c: x.get(c) for c in cols} for x in out["capacity"]], cols) + "\n")
        md.append("Hyperliquid's open interest and day volume in M USD from its newest snapshot; T4's measured cost "
                  "of a 10k USD market order on Binance's perp (bps from mid): its first day, its days inside the "
                  "windows and the mean there, and the mean over all its days. The registered rule charges T5's "
                  "tiers (Binance one tier wider at 10k).\n")
    md.append(f"Trials (R5's registry, hand family, before the validation numbers): {', '.join(r['trials'])}.\n")
    return "\n".join(md) + "\n"


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    register = "--no-register" not in argv
    t0 = time.time()
    D = load()
    print(f"data ready: {len(D['coins'])} coins, {time.time() - t0:.0f} s", flush=True)
    r = run(D, register)
    out = {"generated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "run": r,
           "capacity": capacity_info(D["coins"], int(D["hours"][-1])),
           "costs": f"Binance USD-M taker {BN_FEE * 1e4:.0f} bps, Hyperliquid's base taker 2.5 / 3.5 / 4.5 bps "
                    "(to 2023, 2024 to 2025-04, from 2025-05), T5's half-spread tiers (1 to 50 bps by the coin's "
                    "30-day median spot volume), Hyperliquid one tier wider, throughout (as registered; T4's depth "
                    "where it exists is shown below, not used)", "seconds": round(time.time() - t0)}
    from .. import report
    d = report.REPORTS / NAME
    d.mkdir(parents=True, exist_ok=True)
    (d / "latest.json").write_text(json.dumps(out, indent=1, default=float), encoding="utf-8")
    dc.write_results(NAME, markdown(out), "# T11: cross-venue funding, Hyperliquid against Binance\n")
    print(f"done in {out['seconds']} s; pick {r['pick']}, validation Sharpe {r['val']['sharpe']:.2f}, "
          f"passes {r['passes']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
