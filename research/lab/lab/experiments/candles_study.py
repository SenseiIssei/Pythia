"""X15: candlestick patterns after costs, as pre-registered in results/candles_prereg.md.

    python -m lab.experiments.candles_study                 # every part
    python -m lab.experiments.candles_study --part A        # one part (A, B, C, D); later parts read A's cache

A  event study: forward returns after each of 80 signals (74 patterns, 6 derived) at
   1, 3, 5, 10 bars on crypto daily and 4h (the Alpaca coins, a survivorship-free
   twin), US ETFs and S&P 500 members daily; entry at the next bar's open; excess
   over the same bar's random entry; screened in sample (t >= 3, 100 events),
   confirmed out of sample (Holm over the candidates, the twin agreeing).
B  the best bullish signals per set as long-only slot books, with a late fill,
   double costs and the twin; against random books, the benchmark and the pool.
C  candle features added to M2 v2 (X11's panel and scores), rank IC from 2024.
D  candle filters on breakout_top10's entries, X6/X9's six gates.

Writes results/candles.md (PYTHIA_RESULTS or the repo's results/) and the JSON next
to the agent caches (PYTHIA_AGENT_OUT/reports).
"""

from __future__ import annotations

import argparse
import json
import math
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import polars as pl
from scipy import stats

from .. import candles, universe
from ..candles.derived import DERIVED, DERIVED_DIRECTION
from ..metrics import deflated_sharpe
from . import alpaca_universe as au
from . import candles_data as cd
from . import fam_breakout
from . import fam_common as fc
from . import flow_overlays as fo

NAME = "candles"
HORIZONS = (1, 3, 5, 10)
SCREEN_T, MIN_IS, MIN_OOS = 3.0, 100, 30
HOLM_ALPHA = 0.05
PERM_DRAWS = 2000
RANDOM_BOOKS = 200
SLOTS = {"CD": 10, "C4": 10, "EF": 5, "SP": 20}
PICKS_PER_SET = 3
SETS = ("CD", "C4", "EF", "SP")
CRYPTO = ("CD", "C4")
HAND_TRIALS = 948
PRIOR_TRIALS, PRIOR_SR0 = 377, 2.43
BOOT_DRAWS, BOOT_BLOCK = 5000, 20
C_PASS_T = 2.24
YEARS_CRYPTO = (2024, 2025, 2026)
SIGNALS = tuple(candles.NAMES) + DERIVED
RESULTS = Path(os.environ.get("PYTHIA_RESULTS", Path(__file__).resolve().parents[2] / "results"))
MARKER = "<!-- generated below by lab.experiments.candles_study -->"


def direction(name: str) -> int:
    return DERIVED_DIRECTION[name] if name in DERIVED_DIRECTION else candles.PATTERNS[name].direction


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------

def nw_t(x: np.ndarray, lag: int) -> float:
    x = np.asarray(x, float)
    x = x[np.isfinite(x)]
    n = len(x)
    if n < 3:
        return float("nan")
    e = x - x.mean()
    v = float(e @ e) / n
    for k in range(1, min(lag, n - 1) + 1):
        v += 2 * (1 - k / (lag + 1)) * float(e[k:] @ e[:-k]) / n
    return float(x.mean() / math.sqrt(v / n)) if v > 0 else float("nan")


def holm(pvals: list[float], alpha: float = HOLM_ALPHA) -> list[bool]:
    """Holm's step-down: which hypotheses are rejected at family-wise alpha."""
    order = np.argsort(pvals)
    m = len(pvals)
    out = [False] * m
    for i, k in enumerate(order):
        if pvals[k] <= alpha / (m - i):
            out[k] = True
        else:
            break
    return out


# ---------------------------------------------------------------------------
# Signals and forward returns on a bar set
# ---------------------------------------------------------------------------

def bar_signals(B: cd.BarSet, cols: slice | np.ndarray = slice(None)) -> dict[str, np.ndarray]:
    o, h, l, c, v = (a[:, cols] for a in (B.o, B.h, B.l, B.c, B.v))
    return candles.signals(o, h, l, c, v)


def one_signal(B: cd.BarSet, name: str, chunk: int = 150) -> np.ndarray:
    """(T, N) hits of one signal, a block of columns at a time (bounded memory)."""
    out = np.zeros((B.T, B.N), dtype=bool)
    for j0 in range(0, B.N, chunk):
        cols = np.arange(j0, min(B.N, j0 + chunk))
        out[:, cols] = bar_signals(B, cols)[name]
    return out


def forward(B: cd.BarSet, h: int) -> np.ndarray:
    """r[t, j] = close(t+h) / open(t+1) - 1, exit at the last close if the series ends first.
    NaN when there is no open at t+1 or the exit lies beyond the data."""
    T, N = B.T, B.N
    px, last = B.extra["px"], B.extra["last"]
    t = np.arange(T)[:, None]
    o1 = np.full((T, N), np.nan)
    o1[:-1] = B.o[1:]
    ex = np.minimum(t + h, last[None, :])
    ended = last < T - 1                                     # the series stopped before the data did
    known = (t + h <= T - 1) | (ended[None, :] & (last[None, :] < t + h))
    ok = known & (t + 1 <= last[None, :]) & (ex >= t + 1)
    pex = px[np.clip(ex, 0, T - 1), np.arange(N)[None, :]]
    with np.errstate(invalid="ignore", divide="ignore"):
        r = np.where(ok, pex / o1 - 1, np.nan)
    return r


def returns(B: cd.BarSet) -> tuple[dict, dict, dict]:
    """Per horizon: forward returns, valid masks (eligible and finite), same-bar mean."""
    R, V, base = {}, {}, {}
    for h in HORIZONS:
        r = forward(B, h)
        v = B.elig & np.isfinite(r)
        R[h], V[h] = r, v
        with np.errstate(invalid="ignore"):
            base[h] = np.where(v.any(1), np.where(v, r, 0).sum(1) / np.maximum(v.sum(1), 1), np.nan)
    return R, V, base


def accumulate(B: cd.BarSet, R: dict, V: dict, base: dict, chunk: int = 150) -> dict:
    """Per signal and horizon, per bar: summed excess (S), events (N), summed return (R),
    summed round-trip cost (C), events that win after cost (W)."""
    T = B.T
    rt = 2 * B.cost + B.sell_fee
    acc = {s: {h: {k: np.zeros(T) for k in "SNRCW"} for h in HORIZONS} for s in SIGNALS}
    for j0 in range(0, B.N, chunk):
        cols = np.arange(j0, min(B.N, j0 + chunk))
        hits = bar_signals(B, cols)
        for s in SIGNALS:
            m = hits[s]
            for h in HORIZONS:
                ev = m & V[h][:, cols]
                if not ev.any():
                    continue
                r = np.where(ev, R[h][:, cols], 0.0)
                a = acc[s][h]
                a["S"] += np.where(ev, r - base[h][:, None], 0.0).sum(1)
                a["N"] += ev.sum(1)
                a["R"] += r.sum(1)
                a["C"] += np.where(ev, rt[cols][None, :], 0.0).sum(1)
                a["W"] += (ev & (r > rt[cols][None, :])).sum(1)
        del hits
    return acc


def drift(R: dict, V: dict, mask: np.ndarray) -> dict:
    return {h: float(np.where(V[h][mask], R[h][mask], 0).sum() / max(V[h][mask].sum(), 1)) for h in HORIZONS}


def cell(a: dict, mask: np.ndarray, h: int, d: int) -> dict:
    N = a["N"][mask]
    n = int(N.sum())
    if n == 0:
        return {"n": 0, "ex_bps": float("nan"), "t": float("nan"), "r_bps": float("nan"), "net_bps": float("nan"),
                "win": float("nan"), "bars": 0}
    bars = N > 0
    m = d * a["S"][mask][bars] / N[bars]
    return {"n": n, "bars": int(bars.sum()), "ex_bps": float(m.mean() * 1e4), "t": nw_t(m, h),
            "r_bps": float(a["R"][mask].sum() / n * 1e4),
            "net_bps": float((a["R"][mask].sum() - a["C"][mask].sum()) / n * 1e4),
            "win": float(a["W"][mask].sum() / n)}


# ---------------------------------------------------------------------------
# Part A
# ---------------------------------------------------------------------------

def load_sets(P: fc.Panel) -> dict[str, cd.BarSet]:
    S = {"CD": cd.crypto_daily(P), "CD twin": cd.crypto_daily(P, twin=True),
         "C4": cd.crypto_4h(P), "C4 twin": cd.crypto_4h(P, twin=True)}
    S.update(cd.equities())
    return S


def part_a(sets: dict[str, cd.BarSet]) -> dict:
    rows, freq, drifts, coverage = [], [], {}, {}
    accs = {}
    for k, B in sets.items():
        t0 = time.time()
        R, V, base = returns(B)
        acc = accumulate(B, R, V, base)
        accs[k] = acc
        drifts[k] = {"is": drift(R, V, B.ins), "oos": drift(R, V, B.oos)}
        el = B.elig.sum()
        coverage[k] = {"instruments": B.N, "bars": int(B.T), "eligible_bars": int(el),
                       "eligible_is": int(B.elig[B.ins].sum()), "eligible_oos": int(B.elig[B.oos].sum()),
                       **({"no_candle_share": B.extra["no_candle_share"]} if "no_candle_share" in B.extra else {})}
        for s in SIGNALS:
            freq.append({"set": k, "signal": s,
                         "per_1000": float(acc[s][5]["N"].sum() / max(V[5].sum(), 1) * 1000)})
        print(f"  A {k}: {B.N} instruments x {B.T} bars, {time.time() - t0:.0f}s", flush=True)
    for k in SETS:
        for s in SIGNALS:
            for h in HORIZONS:
                a = accs[k][s][h]
                d = direction(s)
                if d == 0:
                    pre = cell(a, sets[k].ins, h, 1)
                    d = 1 if (pre["n"] and pre["ex_bps"] >= 0) else -1
                ri, ro = cell(a, sets[k].ins, h, d), cell(a, sets[k].oos, h, d)
                row = {"set": k, "signal": s, "h": h, "dir": d, "kind": "derived" if s in DERIVED else
                       candles.PATTERNS[s].kind, **{f"is_{x}": v for x, v in ri.items()},
                       **{f"oos_{x}": v for x, v in ro.items()},
                       "drift_is_bps": drifts[k]["is"][h] * 1e4, "drift_oos_bps": drifts[k]["oos"][h] * 1e4}
                if k in CRYPTO:
                    tw = cell(accs[f"{k} twin"][s][h], sets[f"{k} twin"].oos, h, d)
                    tw_is = cell(accs[f"{k} twin"][s][h], sets[f"{k} twin"].ins, h, d)
                    row.update({"twin_oos_n": tw["n"], "twin_oos_ex_bps": tw["ex_bps"], "twin_oos_t": tw["t"],
                                "twin_is_ex_bps": tw_is["ex_bps"], "twin_is_t": tw_is["t"]})
                row["candidate"] = bool(ri["n"] >= MIN_IS and np.isfinite(ri["t"]) and ri["t"] >= SCREEN_T)
                rows.append(row)
    cands = [r for r in rows if r["candidate"]]
    pv = [float(stats.norm.sf(r["oos_t"])) if (r["oos_n"] >= MIN_OOS and np.isfinite(r["oos_t"])) else 1.0
          for r in cands]
    rej = holm(pv) if cands else []
    for r, p, ok in zip(cands, pv, rej):
        r["oos_p"] = p
        twin_ok = (r["set"] not in CRYPTO) or (np.isfinite(r.get("twin_oos_ex_bps", np.nan))
                                               and r["twin_oos_ex_bps"] > 0)
        r["holds"] = bool(ok and r["oos_n"] >= MIN_OOS and twin_ok)
        r["tradeable"] = bool(r["holds"] and r["dir"] > 0 and r["oos_net_bps"] > 0
                              and r["oos_net_bps"] > r["drift_oos_bps"])
    return {"rows": rows, "freq": freq, "drift": drifts, "coverage": coverage, "n_cells": len(rows),
            "n_candidates": len(cands), "holm_m": len(cands)}


def permutation(B: cd.BarSet, signal: str, h: int, mask: np.ndarray, rng: np.random.Generator,
                draws: int = PERM_DRAWS) -> dict:
    """Random entry on the same bars: one random valid instrument per event, `draws` times."""
    R, V, _ = returns_h(B, h)
    hits = one_signal(B, signal) & V & mask[:, None]
    n = int(hits.sum())
    if n == 0:
        return {"n": 0}
    actual = float(R[hits].mean())
    tot = np.zeros(draws)
    for t in np.flatnonzero(hits.any(1)):
        k = int(hits[t].sum())
        pool = R[t][V[t]]
        tot += pool[rng.integers(0, len(pool), (draws, k))].sum(1)
    sim = tot / n
    d = direction(signal) or 1
    p = float(np.mean(sim >= actual)) if d > 0 else float(np.mean(sim <= actual))
    return {"n": n, "mean_bps": actual * 1e4, "random_mean_bps": float(sim.mean() * 1e4),
            "random_p95_bps": float(np.percentile(sim, 95) * 1e4), "random_p05_bps": float(np.percentile(sim, 5) * 1e4),
            "p": p}


def returns_h(B: cd.BarSet, h: int):
    r = forward(B, h)
    v = B.elig & np.isfinite(r)
    return r, v, None


# ---------------------------------------------------------------------------
# Part B: slot books
# ---------------------------------------------------------------------------

def book(B: cd.BarSet, E: np.ndarray, h: int, slots: int, cost_mult: float = 1.0, lag: int = 0,
         rng: np.random.Generator | None = None, entries: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray]:
    """Daily net returns of the slot book, and the number of entries decided at each bar's close.

    E[t] marks signals at the close of bar t. With lag, the signal of bar t - lag is used at
    the close of bar t. Entry at the next open with 1/slots of equity (as far as cash allows),
    exit at the close h bars later counting the entry bar, or at the instrument's last close.
    With rng and entries, the book instead buys `entries[t]` random valid instruments at each
    close (the null book)."""
    T, N = B.T, B.N
    px, O, last = B.extra["px"], B.o, B.extra["last"]
    cost = B.cost * cost_mult
    sell = B.sell_fee * cost_mult
    cash, eq_prev = 1.0, 1.0
    vals: dict[int, float] = {}
    exit_at: dict[int, int] = {}
    pending: list[int] = []
    bar_ret = np.zeros(T)
    n_in = np.zeros(T, dtype=np.int64)
    for t in range(T):
        for j in list(vals):
            p0, p1 = px[t - 1, j], px[t, j]
            if np.isfinite(p0) and np.isfinite(p1) and p0 > 0:
                vals[j] *= p1 / p0
        for j in pending:
            amt = min(eq_prev / slots, cash / (1 + cost[j]))
            if amt <= 0 or not (np.isfinite(O[t, j]) and O[t, j] > 0 and np.isfinite(px[t, j])):
                continue
            cash -= amt * (1 + cost[j])
            vals[j] = amt * px[t, j] / O[t, j]
        pending = []
        for j in list(vals):
            if t >= exit_at[j] or t >= last[j]:
                cash += vals.pop(j) * (1 - cost[j] - sell)
                exit_at.pop(j)
        eq = cash + sum(vals.values())
        bar_ret[t] = eq / eq_prev - 1 if eq_prev > 0 else 0.0
        eq_prev = eq
        if t + 1 >= T:
            break
        free = slots - len(vals)
        if free <= 0:
            continue
        ok_next = np.isfinite(O[t + 1]) & (t + 1 <= last)
        if rng is not None:
            k = int(entries[t]) if entries is not None else 0
            if k <= 0:
                continue
            cand = np.flatnonzero(B.elig[t] & ok_next)
            cand = cand[[c not in vals for c in cand]] if len(cand) else cand
            if not len(cand):
                continue
            pick = rng.choice(cand, size=min(k, free, len(cand)), replace=False)
        else:
            s = t - lag
            if s < 0:
                continue
            cand = np.flatnonzero(E[s] & ok_next)
            if not len(cand):
                continue
            cand = np.array([c for c in cand if c not in vals], dtype=np.int64)
            if not len(cand):
                continue
            pick = cand[np.argsort(-B.prio[t, cand], kind="stable")][:free]
        for j in pick:
            pending.append(int(j))
            exit_at[int(j)] = t + h
        n_in[t] = len(pick)
    lg = np.log1p(np.maximum(bar_ret, -0.999999))
    daily = np.expm1(np.bincount(B.day, weights=lg, minlength=len(B.days))[:len(B.days)])
    return daily, n_in


def day_masks(B: cd.BarSet) -> tuple[np.ndarray, np.ndarray]:
    d = B.days
    if np.issubdtype(d.dtype, np.datetime64):
        return (d >= cd.EQ_IS_FROM) & (d < cd.EQ_SPLIT), d >= cd.EQ_SPLIT
    return (d >= fc.IS_START) & (d < fc.SPLIT), d >= fc.SPLIT


def sharpe(x: np.ndarray, per_year: float) -> float:
    x = x[np.isfinite(x)]
    sd = x.std() if len(x) > 1 else 0.0
    return float(x.mean() / sd * math.sqrt(per_year)) if sd > 0 else 0.0


def perf(x: np.ndarray, per_year: float) -> dict:
    x = x[np.isfinite(x)]
    if len(x) < 2:
        return {"sharpe": 0.0, "cagr": 0.0, "max_dd": 0.0, "days": len(x)}
    eq = np.cumprod(1 + x)
    dd = 1 - eq / np.maximum.accumulate(eq)
    yrs = len(x) / per_year
    return {"sharpe": sharpe(x, per_year), "cagr": float(eq[-1] ** (1 / yrs) - 1) if eq[-1] > 0 else -1.0,
            "max_dd": float(dd.max()), "days": int(len(x))}


def benchmark(B: cd.BarSet, P: fc.Panel) -> np.ndarray:
    if B.name in CRYPTO or B.name.startswith("C"):
        return np.nan_to_num(P.ret[:, P.btc])
    s = B.extra["spy"]
    r = np.zeros(len(s))
    r[1:] = s[1:] / s[:-1] - 1
    return np.nan_to_num(r)


def pool_units(x: np.ndarray, per_year: float) -> tuple[float, int, float, float]:
    """A daily return series as the pool's per-calendar-day Sharpe and observation count."""
    sd = x.std()
    s = float(x.mean() / sd) if sd > 0 else 0.0
    k = per_year / 365
    return s * math.sqrt(k), int(round(len(x) / k)), float(stats.skew(x)) if sd > 0 else 0.0, \
        float(stats.kurtosis(x, fisher=False)) if sd > 0 else 3.0


def prior_var() -> float:
    g = 0.5772156649
    z = (1 - g) * stats.norm.ppf(1 - 1 / PRIOR_TRIALS) + g * stats.norm.ppf(1 - 1 / (PRIOR_TRIALS * math.e))
    return (PRIOR_SR0 / math.sqrt(365) / z) ** 2


def pool(mine_annual: list[float]) -> dict:
    v1, n1 = prior_var(), HAND_TRIALS
    fx = np.clip(fo.factory_sharpes(), -fc.SR_CLIP, fc.SR_CLIP) / math.sqrt(365)
    n2, v2 = len(fx), float(np.var(fx)) if len(fx) > 1 else 0.0
    x = np.clip(np.array(mine_annual), -fc.SR_CLIP, fc.SR_CLIP) / math.sqrt(365)
    n3, v3 = len(x), float(np.var(x)) if len(x) > 1 else 0.0
    n = n1 + n2 + n3
    v = (n1 * v1 + n2 * v2 + n3 * v3) / n
    return {"hand_trials": n1, "factory_trials": n2, "mine": n3, "n_total": n, "var": v,
            "sr0_annual": fc._sr0(v, n) * math.sqrt(365)}


def deflated_pool(x: np.ndarray, per_year: float, pl_: dict) -> float:
    s, n, sk, ku = pool_units(x, per_year)
    if 1 - sk * s + (ku - 1) / 4 * s ** 2 <= 0:
        return 0.0
    return deflated_sharpe(s, n, pl_["n_total"], pl_["var"], sk, ku)


def choose_picks(rows: list[dict]) -> dict[str, list[dict]]:
    out = {}
    for k in SETS:
        best = {}
        for r in rows:
            if r["set"] != k or r["dir"] <= 0 or direction(r["signal"]) <= 0:
                continue
            if r["is_n"] < MIN_IS or not np.isfinite(r["is_t"]):
                continue
            if not (r["is_net_bps"] > r["drift_is_bps"]):
                continue
            b = best.get(r["signal"])
            if b is None or r["is_t"] > b["is_t"]:
                best[r["signal"]] = r
        out[k] = sorted(best.values(), key=lambda r: -r["is_t"])[:PICKS_PER_SET]
    return out


def part_b(sets: dict[str, cd.BarSet], P: fc.Panel, A: dict, rng: np.random.Generator) -> dict:
    picks = choose_picks(A["rows"])
    trials, runs = [], []
    for k in SETS:
        B = sets[k]
        ins_d, oos_d = day_masks(B)
        bench = benchmark(B, P)
        yrs = B.years()
        for pk in picks[k]:
            s, h = pk["signal"], pk["h"]
            E = one_signal(B, s) & B.elig
            base, n_in = book(B, E, h, SLOTS[k])
            variants = {"base": base, "late": book(B, E, h, SLOTS[k], lag=1)[0],
                        "double cost": book(B, E, h, SLOTS[k], cost_mult=2.0)[0]}
            if k in CRYPTO:
                Bt = sets[f"{k} twin"]
                Et = one_signal(Bt, s) & Bt.elig
                variants["twin"] = book(Bt, Et, h, SLOTS[k])[0]
            rnd = np.array([sharpe(book(B, E, h, SLOTS[k], rng=rng, entries=n_in)[0][oos_d], B.per_year)
                            for _ in range(RANDOM_BOOKS)])
            row = {"set": k, "signal": s, "h": h, "is_t": pk["is_t"], "oos_t_event": pk["oos_t"],
                   "entries_oos": int(n_in[B.oos].sum()), "random_p95": float(np.percentile(rnd, 95)),
                   "random_median": float(np.median(rnd)),
                   "bench_oos": perf(bench[oos_d], B.per_year)["sharpe"],
                   "bench_dd": perf(bench[oos_d], B.per_year)["max_dd"]}
            for v, x in variants.items():
                po, pi = perf(x[oos_d], B.per_year), perf(x[ins_d], B.per_year)
                row[f"{v}_is"] = pi["sharpe"]
                row[f"{v}_oos"] = po["sharpe"]
                if v == "base":
                    row.update(cagr=po["cagr"], dd=po["max_dd"])
                trials.append((f"{k} {s} h{h} {v}", x[oos_d], B.per_year, po["sharpe"]))
            yo = np.unique(yrs[oos_d])
            row["years"] = {int(y): sharpe(base[oos_d & (yrs == y)], B.per_year) for y in yo}
            row["years_pos"] = int(sum(v > 0 for v in row["years"].values()))
            row["years_n"] = len(yo)
            row["exposure"] = None
            runs.append((row, base[oos_d], B.per_year))
            print(f"  B {k} {s} h{h}: base {row['base_oos']:.2f}", flush=True)
    pl_ = pool([t[3] for t in trials])
    for row, x, py in runs:
        row["deflated_p"] = deflated_pool(x, py, pl_)
        crypto = row["set"] in CRYPTO
        g = {"1 Sharpe > 0": row["base_oos"] > 0,
             "2 above random books": row["base_oos"] > row["random_p95"],
             "3 above the benchmark": row["base_oos"] > row["bench_oos"],
             "4 late > 0": row["late_oos"] > 0,
             "5 double cost > 0": row["double cost_oos"] > 0,
             "7 years": row["years_pos"] >= (2 if crypto else 7),
             "8 deflated": row["deflated_p"] > 0.95}
        if crypto:
            g["6 twin > 0"] = row["twin_oos"] > 0
        row["gates_failed"] = [k for k, ok in sorted(g.items()) if not ok]
        row["passes"] = all(g.values())
    return {"picks": {k: [{"signal": p["signal"], "h": p["h"], "is_t": p["is_t"]} for p in v]
                      for k, v in picks.items()},
            "rows": [r for r, _, _ in runs], "trials": [t[0] for t in trials],
            "trial_sharpes": [t[3] for t in trials], "pool": pl_}


# ---------------------------------------------------------------------------
# Part C: M2 features
# ---------------------------------------------------------------------------

def c_features(P: fc.Panel, pick_signals: list[str]) -> pl.DataFrame:
    """(day, symbol, c_*) for every coin-day of the sweep's panel with a candle."""
    f = pl.read_parquet(cd._cache("candles_daily.parquet"))
    m = cd._matrix(f, "day", P.days, P.names, ["open", "high", "low", "close", "qv"])
    o, h, l, c, v = m["open"], m["high"], m["low"], m["close"], m["qv"]
    s = candles.signals(o, h, l, c, v)
    sh = candles.shape_features(o, h, l, c)
    has = np.isfinite(o) & np.isfinite(h) & np.isfinite(l) & np.isfinite(c)
    net = s["net"].astype(float)
    net5 = fc.rolling(np.where(has, net, np.nan), 5, 1, "sum")
    cols = {"c_net": net, "c_net5": net5,
            "c_sr": s["bull_at_support"].astype(float) - s["bear_at_resistance"],
            "c_vol": s["bull_volume"].astype(float) - s["bear_volume"],
            "c_body": sh["c_body"], "c_upper": sh["c_upper"], "c_lower": sh["c_lower"]}
    for p in pick_signals:
        cols[f"c_pick_{p}"] = s[p].astype(float)
    T, N = P.T, P.N
    out = {"day": np.repeat(P.days, N), "symbol": np.tile(np.array(P.names), T)}
    for k, x in cols.items():
        out[k] = np.where(has, x, np.nan).ravel()
    df = pl.DataFrame(out)
    return df.filter(pl.col("c_net").is_not_nan())


def part_c(P: fc.Panel, pick_signals: list[str]) -> dict:
    from . import m2_v3
    src = Path(os.environ.get("PYTHIA_M2_CACHE", str(cd.ROOT / "agent-x11" / "cache")))
    ranked = pl.read_parquet(src / "m2_v3_ranked.parquet").with_row_index("_row")
    v2 = np.load(src / "m2_v3_scores_v2.npy")
    meta = json.loads((src / "m2_v3_scores_v2.json").read_text())
    assert meta["rows"] == ranked.height and len(v2) == ranked.height
    feats = c_features(P, pick_signals)
    newc = [c for c in feats.columns if c.startswith("c_")]
    j = ranked.join(feats, on=["day", "symbol"], how="left").sort("_row")
    assert j.height == ranked.height
    j = j.with_columns([pl.when(pl.col(c).is_nan()).then(None).otherwise(pl.col(c)).alias(c) for c in newc])
    j = j.with_columns([((pl.col(c).rank().over("day") - 1) / (pl.len().over("day") - 1).clip(1)).alias(c)
                        for c in newc]).drop("_row")
    cache = fc.OUT / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    path = cache / "x15_m2_candles.parquet"
    j.write_parquet(path)
    feats_c = m2_v3.V2 + newc
    sf = cache / "x15_m2_scores_c.npy"
    mf = cache / "x15_m2_scores_c.json"
    if sf.exists() and mf.exists() and json.loads(mf.read_text()) == {"feats": feats_c, "rows": j.height}:
        sc = np.load(sf)
    else:
        t0 = time.time()
        sc = m2_v3.walk(str(path), feats_c)
        np.save(sf, sc)
        mf.write_text(json.dumps({"feats": feats_c, "rows": j.height}))
        print(f"  C walk-forward {time.time() - t0:.0f}s", flush=True)
    day, fwd, sym = j["day"].to_numpy(), j["fwd"].to_numpy(), j["symbol"].to_numpy()
    every = np.ones(j.height, dtype=bool)
    alp = m2_v3.alpaca_mask(sym)
    ic_c, ic_2 = m2_v3.daily_ic(day, sc, fwd, every), m2_v3.daily_ic(day, v2, fwd, every)
    tests = {"H1 whole universe": m2_v3.compare(ic_c, ic_2, fc.SPLIT),
             "H2 Alpaca": m2_v3.compare(m2_v3.daily_ic(day, sc, fwd, alp, m2_v3.MIN_ALPACA),
                                        m2_v3.daily_ic(day, v2, fwd, alp, m2_v3.MIN_ALPACA), fc.SPLIT)}
    for v in tests.values():
        v["passes"] = bool(v.get("days") and v["diff"] > 0 and v["t"] > C_PASS_T and v["years_better"] >= 2)
    alone = {}
    for c in newc:
        x = j[c].to_numpy().astype(float)
        ic = m2_v3.daily_ic(day, np.where(np.isfinite(x), x, np.nan), fwd, every)
        o = ic.filter(pl.col("day") >= fc.SPLIT)["ic"].to_numpy()
        i = ic.filter(pl.col("day") < fc.SPLIT)["ic"].to_numpy()
        alone[c] = {"ic_is": float(np.nanmean(i)) if len(i) else float("nan"),
                    "ic_oos": float(np.nanmean(o)) if len(o) else float("nan"),
                    "t_oos": m2_v3.nw_t(o) if len(o) > 3 else float("nan")}
    imp = m2_v3.importance(j, feats_c) if hasattr(m2_v3, "importance") else []
    return {"tests": tests, "alone": alone, "features": newc, "rows": j.height,
            "coverage": float(j[newc[0]].is_not_null().mean()), "importance": imp[:30] if imp else []}


# ---------------------------------------------------------------------------
# Part D: breakout entry filter
# ---------------------------------------------------------------------------

def part_d(P: fc.Panel, rng: np.random.Generator) -> dict:
    from . import model_review as mr
    f = pl.read_parquet(cd._cache("candles_daily.parquet"))
    m = cd._matrix(f, "day", P.days, P.names, ["open", "high", "low", "close", "qv"])
    s = candles.signals(m["open"], m["high"], m["low"], m["close"], m["qv"])
    sh = candles.shape_features(m["open"], m["high"], m["low"], m["close"])
    with np.errstate(invalid="ignore"):
        filters = {"F1 no bearish pattern": s["bear_count"] == 0,
                   "F2 net at least 1": s["net"] >= 1,
                   "F3 close in the top third": sh["c_close_pos"] >= 2 / 3}
    alp = au.alpaca_mask(P)
    top10 = P.top_liquid(10)
    cols = np.flatnonzero(top10.any(0))
    ins, oos = fc.masks(P)
    base = fam_breakout.breakout_weights(P, cols, top10, 20, 10, regime=False)
    ones = np.ones(P.T)
    avail = np.ones(P.T, dtype=bool)
    refs = {}
    for ver, W in (("live", au.cash_left(base, alp)), ("twin", base)):
        refs[ver] = fo.describe(P, f"breakout_top10 {ver} alone", au.simulate(P, "breakout", W)[:3], ones, avail)
        refs[ver]["_net"] = fo.net(*au.simulate(P, "breakout", W)[:2], fo.COSTS[fo.BASE])
    rows, series = [], {}

    def add(name: str, W: np.ndarray, ver: str):
        g, tv, ex, _ = au.simulate(P, "breakout", W)
        r = fo.describe(P, name, (g, tv, ex), ones, avail)
        xo = fo.net(g, tv, fo.COSTS[fo.BASE])
        r["diff_sr"] = fo.sharpe_d((xo - refs[ver]["_net"])[oos]) * math.sqrt(365)
        rows.append(r)
        series[name] = (xo, refs[ver]["_net"])
        return r

    for k, F in filters.items():
        W = fam_breakout.breakout_weights(P, cols, top10 & F, 20, 10, regime=False)
        add(k, au.cash_left(W, alp), "live")
    pick = max(rows, key=lambda r: r[f"is_{fo.BASE}"])
    Fp = filters[pick["variant"]]
    Wp = fam_breakout.breakout_weights(P, cols, top10 & Fp, 20, 10, regime=False)
    late = add(pick["variant"] + " · one day late", au.cash_left(au.one_day_late(Wp), alp), "live")
    twin = add(pick["variant"] + " · twin", Wp, "twin")
    diffs = np.clip(np.array([r["diff_sr"] for r in rows]), -fc.SR_CLIP, fc.SR_CLIP) / math.sqrt(365)
    dvar = float(np.var(diffs))
    for r in rows:
        xo, xb = series[r["variant"]]
        r["deflated_p_diff"] = fo.deflated((xo - xb)[oos], len(rows), dvar)
    xo, xb = series[pick["variant"]]
    lo, hi = mr.boot_band(xo[oos], rng, xb[oos], BOOT_DRAWS, BOOT_BLOCK)
    ref, tref = refs["live"], refs["twin"]
    yb = sum(pick[f"y{y}"] > ref[f"y{y}"] for y in YEARS_CRYPTO)
    g = {"1 Sharpe and years": pick[f"oos_{fo.BASE}"] > ref[f"oos_{fo.BASE}"] and yb >= 2,
         "2 drawdown": pick["dd_35"] < ref["dd_35"],
         "3 band above 0": lo > 0,
         "4 one day late": late[f"oos_{fo.BASE}"] > ref[f"oos_{fo.BASE}"],
         "5 twin": twin[f"oos_{fo.BASE}"] >= tref[f"oos_{fo.BASE}"],
         "6 deflated improvement": pick["deflated_p_diff"] > 0.95}
    for v in refs.values():
        v.pop("_net", None)
    return {"rows": rows, "refs": list(refs.values()), "pick": pick["variant"], "diff_p05": lo, "diff_p95": hi,
            "years_better": int(yb), "gates_failed": [k for k, ok in g.items() if not ok], "passes": all(g.values()),
            "trial_sharpes": [r[f"oos_{fo.BASE}"] for r in rows]}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _json_default(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    return str(o)


def save(part: str, res: dict) -> None:
    d = fc.OUT / "reports"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{NAME}_{part}.json").write_text(json.dumps(res, default=_json_default), encoding="utf-8")


def load(part: str) -> dict | None:
    f = fc.OUT / "reports" / f"{NAME}_{part}.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--part", default="ABCD")
    args = ap.parse_args()
    rng = np.random.default_rng(20261020)
    cd.build_crypto()
    P = fc.load_panel()
    sets = load_sets(P) if any(p in args.part for p in "AB") else None
    if "A" in args.part:
        A = part_a(sets)
        save("A", A)
        # Permutation check for the cells that hold and for the B picks.
        perms = []
        for r in A["rows"]:
            if r.get("holds"):
                B = sets[r["set"]]
                perms.append({"set": r["set"], "signal": r["signal"], "h": r["h"],
                              **permutation(B, r["signal"], r["h"], B.oos, rng)})
        A["permutation"] = perms
        save("A", A)
    A = load("A")
    if "B" in args.part:
        Bres = part_b(sets, P, A, rng)
        Bres["permutation"] = []
        for k, ps in Bres["picks"].items():
            for p in ps:
                for w, m in (("oos", sets[k].oos), ("is", sets[k].ins)):
                    Bres["permutation"].append({"set": k, "signal": p["signal"], "h": p["h"], "window": w,
                                                **permutation(sets[k], p["signal"], p["h"], m, rng)})
        save("B", Bres)
    Bres = load("B")
    if "C" in args.part:
        picks_cd = [p["signal"] for p in (Bres or {}).get("picks", {}).get("CD", [])]
        save("C", part_c(P, picks_cd))
    if "D" in args.part:
        save("D", part_d(P, rng))
    from .candles_report import write
    write(load("A"), load("B"), load("C"), load("D"), panel_end=str(np.datetime64(int(P.days[-1]), "us")
                                                                   .astype("datetime64[D]")))


if __name__ == "__main__":
    main()
