"""OS1: an optimal-stopping exit by least-squares Monte Carlo (E1) and a conditional peaks-over-threshold crash exit
(E2) for P_pool0, on the whole record at the latency the live executor measures since 2026-10-29. PAPER ONLY.

    python -m lab.pumpfun_rt.os1                        replay, fit, run both exits, write os1.{json,md}
    python -m lab.pumpfun_rt.os1 --out DIR              the same, written into DIR
    python -m lab.pumpfun_rt.os1 --cache FILE           the replay's paths kept in FILE (read again if it exists)
    python -m lab.pumpfun_rt.os1 --register-only        the 2 trials into R5's registry, nothing else

Pre-registered in results/pumpfun_os1_prereg.md. X14 r2's full replay (flowexit.FlowPipe, every P_pool0 signal at
0.05 SOL, no book limit) at E2's latency (entry_e2.costs()), each entry's pool path from the signal to the landing +
480 s; no step rows: the state at a decision time comes from the path up to it (the mark, the pool's sales of the last
10 s, the grouped early wallets' dump-at-risk, the buyback running, the age). E1 solves V(t, s) = max(sell now,
E[V(t + dt, s')]) by Longstaff and Schwartz's regressions on earlier days' paths, every sale landing L later, the take
and the 300 s time stop as caps and no -20 % stop. E2 fits the largest fall in the 10 s after L by a generalised
Pareto distribution over a threshold, its scale and the exceedance's probability functions of the same state (McNeil
and Frey's conditional EVT, pooled across coins), and sells P_pool0's position when P(fall > 30 %) is above a level
fitted in sample. Both walk-forward by UTC day, judged paired by entry against P_pool0 (X0). Nothing here holds a
wallet, reads a key, signs or sends anything; the live executor's files are not read (its latencies are E2's).
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import math
import pickle
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from . import curve as C
from . import entry_e2 as E2
from . import flowexit as FX
from . import pipeline as P
from . import reallat as RL

# ---------------------------------------------------------------- registered (results/pumpfun_os1_prereg.md)

PREREG = "results/pumpfun_os1_prereg.md"
BASE = FX.BASE
_utc = FX._utc
day_of = FX.day_of
UNTIL_MS = E2.UNTIL_MS                                  # E2's cutoff, 2026-10-29 19:30 UTC
TAIL_MS = 10 * 60_000                                   # signals stop this long before it: every position closes
OOS_FROM = FX.OOS_FROM                                  # in sample: the UTC days before 2026-10-24
STAKE_SOL = FX.STAKE_SOL
TP, SL, TIME_S = FX.TP, FX.SL, FX.TIME_S
L_MS = float(np.median(FX._clip(E2.LIVE_SELL_MS, *FX.CLIP_N)))   # the latency a model's sale is assumed to take
R_CLIP = (-3.0, math.log(1 + TP))
SELL_WIN_MS = 10_000
SELL_EDGES = (1, 3, 6)                                  # the sell buckets 0, 1-2, 3-5, 6+ (three dummies)
BB_GAP_MS = FX.BB_GAP_MS
# E1
DT_S = 5
E1_K = tuple(range(1, int(TIME_S) // DT_S))             # g_k = landing + 5 k s, k = 1 .. 59
RIDGE = 1e-3
E1_MIN_PATHS = 100
# E2
E2_STEP_S = 1
E2_G = tuple(range(1, int(TIME_S)))                     # g = landing + 1 .. 299 s
FALL_S = 10
CRASH = 0.30
U_Q, U_MAX = 0.90, 0.20
E2_MIN_ROWS, E2_MIN_EXC = 2_000, 100
XI_BOUNDS = (-0.95, 0.95)
LAMBDAS = (0.02, 0.05, 0.10, 0.20, 0.30, 0.50)
ES_Q = 0.95
CALIB_BINS = 5
DSR_PASS = 0.95
BOOT, SEED, MIN_DAYS = FX.BOOT, FX.SEED, FX.MIN_DAYS
SIZINGS = FX.SIZINGS
EXITS = ("E1", "E2")


def trials() -> list[dict]:
    return [{"id": f"pumpfun:os1:{k}", "family": "pumpfun", "n": 1, "sharpe": None, "source": PREREG} for k in EXITS]


costs = E2.costs


# ---------------------------------------------------------------- the replay (X14 r2's, paths only)

class OS1Rec(FX.Rec):
    """X14 r2's recording without the step rows: the path's columns are all the models read."""

    def step(self, eng, tok, t, v) -> None:
        return None

    def pack(self, complete: bool) -> dict:
        out = super().pack(complete)
        for k in ("X", "step_pt", "hk5", "hk30", "uid", "dq"):
            out.pop(k, None)
        return out


class OS1Pipe(FX.FlowPipe):
    def signal(self, s, tok, t: float) -> None:
        before = self.eng.next_pid
        P.Pipeline.signal(self, s, tok, t)
        if self.eng.next_pid > before and before in self.pos:
            self.recs[before] = OS1Rec(before, tok, t, FX.early_group(self.eng, tok), self.floor)
            self.rec_by_mint.setdefault(tok.mint, []).append(before)


def run(root=None, until_ms: int = UNTIL_MS, log=print) -> dict:
    """The full replay of every P_pool0 signal at the live latency, up to until_ms; signals stop TAIL_MS before."""
    from . import early as EA
    from . import sim, store
    from . import wallets as W
    from .study import span_of, warm_book
    days = [d for d in store.days(root) if d <= day_of(until_ms)]
    if not days:
        return {"empty": True}
    t_lo, t_hi = span_of(days[:1], root)[0], span_of(days[-1:], root)[1]
    t_hi = min(t_hi, until_ms)
    s = P.BY_NAME[BASE]
    strat = dataclasses.replace(s, name=f"{BASE}@N", p={**s.p, "base": BASE}, stake_sol=STAKE_SOL)
    c = costs()
    eng = sim.Engine([], book=warm_book([], root), decisions=False, rule_costs={strat.name: c},
                     entry_until=t_hi - TAIL_MS, wallets=W.warm([], root), snipers=EA.warm_snipers([], root))
    pipe = eng.add_pipe(OS1Pipe(eng, strat, {}))
    t0 = time.time()
    sim.replay(days, eng, root, until_ms=t_hi,
               progress=lambda d, n: log(f"os1: {d} {n:,} rows, {time.time() - t0:.0f} s, "
                                         f"{len(pipe.paths) + len(pipe.recs)} entries"))
    pipe.finish()
    log(f"os1: replay in {time.time() - t0:.0f} s")
    return {"days": days, "span": (t_lo, t_hi), "until_ms": until_ms, "entry_until_ms": t_hi - TAIL_MS,
            "paths": pipe.paths, "failed": [dict(f) for f in pipe.failed],
            "pipe_closed": [{x: cl.get(x) for x in ("pid", "mint", "exit_why", "ret", "exit_ms")}
                            for cl in pipe.closed],
            "skipped": {f"{n}|{w}": k for (n, w), k in eng.skipped.items() if n.startswith(BASE + "@")},
            "gaps": [tuple(g) for g in eng.gaps], "tx_l": c.tx_lamports()}


# ---------------------------------------------------------------- the state, the sale, the label

def states(pa: FX.Path_, g: np.ndarray) -> np.ndarray:
    """The state at each time g (ms) from the path up to g: r, the three sell dummies, dar, bb, age (n x 7)."""
    g = np.asarray(g, dtype=np.float64)
    d = pa.d
    i = np.maximum(np.searchsorted(pa.t, g, side="right") - 1, 0)
    m = pa.mult[i]
    with np.errstate(divide="ignore", invalid="ignore"):
        r = np.where(np.isfinite(m) & (m > 0), np.log(m), R_CLIP[0])
    r = np.clip(r, *R_CLIP)
    cs = np.concatenate([[0], np.cumsum(d["buy"] == 0)])
    lo = np.searchsorted(pa.t, g - SELL_WIN_MS, side="right")
    n = cs[i + 1] - cs[np.minimum(lo, i + 1)]
    e = SELL_EDGES
    dar = np.nan_to_num(d["dar"][i].astype(np.float64), nan=0.0)
    last = d["bblast"][i]
    with np.errstate(invalid="ignore"):
        bb = (np.isfinite(last) & (g - last <= BB_GAP_MS)).astype(np.float64)
    return np.column_stack([r, (n >= e[0]) & (n < e[1]), (n >= e[1]) & (n < e[2]), n >= e[2], dar, bb,
                            (g - pa.land) / (TIME_S * 1000)]).astype(np.float64)


def sale(pa: FX.Path_, g: np.ndarray) -> np.ndarray:
    """P(g): the value of a sale signalled at g, landing L later, over the cost, minus 1 (no value: -1)."""
    i = np.maximum(np.searchsorted(pa.t, np.asarray(g, dtype=np.float64) + L_MS, side="right") - 1, 0)
    return np.nan_to_num(pa.v[i], nan=0.0) / pa.cost - 1


def caps(pa: FX.Path_) -> tuple[float, float]:
    """E1's caps on a training path: the time they fire (the first take point, else the landing + 300 s) and their
    cash flow (the value then + L over the cost, minus 1)."""
    end = pa.land + TIME_S * 1000
    j = FX._first(np.isfinite(pa.mult) & (pa.mult >= 1 + TP), pa.jl)
    tau = min(float(pa.t[j]), end) if j is not None else end
    return tau, float(sale(pa, [tau])[0])


def falls(pa: FX.Path_, g: np.ndarray) -> np.ndarray:
    """F(g): the largest fall of the value in (g + L, g + L + 10 s] over the value at g + L (nan without a value)."""
    t, v = pa.t, pa.v
    a = np.maximum(np.searchsorted(t, np.asarray(g, dtype=np.float64) + L_MS, side="right") - 1, 0)
    b = np.searchsorted(t, np.asarray(g, dtype=np.float64) + L_MS + FALL_S * 1000, side="right")
    out = np.full(len(a), np.nan)
    for k in range(len(a)):
        v0 = v[a[k]]
        if not (np.isfinite(v0) and v0 > 0):
            continue
        seg = v[a[k] + 1:b[k]]
        seg = seg[np.isfinite(seg)]
        out[k] = min(max(1 - float(seg.min()) / v0, 0.0), 1.0) if len(seg) else 0.0
    return out


def tables(paths: list[FX.Path_]) -> dict:
    """Every path's E1 lattice (states, sales, caps) and E2 rows (states, falls)."""
    k1, g2 = np.array(E1_K, dtype=np.float64) * DT_S * 1000, np.array(E2_G, dtype=np.float64) * E2_STEP_S * 1000
    n = len(paths)
    Z1, S1 = np.zeros((n, len(k1), 7)), np.zeros((n, len(k1)))
    tau, cf0 = np.zeros(n), np.zeros(n)
    Z2, F2 = np.zeros((n, len(g2), 7)), np.zeros((n, len(g2)))
    for i, pa in enumerate(paths):
        Z1[i], S1[i] = states(pa, pa.land + k1), sale(pa, pa.land + k1)
        tau[i], cf0[i] = caps(pa)
        Z2[i], F2[i] = states(pa, pa.land + g2), falls(pa, pa.land + g2)
    return {"G1": k1, "Z1": Z1, "S1": S1, "tau": tau, "cf0": cf0, "G2": g2, "Z2": Z2, "F2": F2,
            "land": np.array([pa.land for pa in paths]), "day": np.array([day_of(pa.d["signal_ms"]) for pa in paths]),
            "end": np.array([pa.land for pa in paths]) + TIME_S * 1000 + L_MS + FALL_S * 1000}


def train_mask(tab: dict, d: str) -> np.ndarray:
    """The paths of the days before d whose last label window ends before d starts."""
    return (tab["day"] < d) & (tab["end"] < _utc(*map(int, d.split("-"))))


# ---------------------------------------------------------------- E1: least-squares Monte Carlo

def basis(Z: np.ndarray) -> np.ndarray:
    """r, r^2, r^3, dar, dar r, bb, bb r, the three sell dummies and r times each (the constant is the ridge's)."""
    r, s1, s2, s3, dar, bb = (Z[:, j] for j in range(6))
    return np.column_stack([r, r ** 2, r ** 3, dar, dar * r, bb, bb * r, s1, s2, s3, s1 * r, s2 * r, s3 * r])


def ridge(B: np.ndarray, y: np.ndarray, lam: float = RIDGE) -> tuple:
    """Ridge with a free constant, the columns standardised on these rows, the penalty lam times the rows."""
    mu, sd = B.mean(0), B.std(0)
    sd = np.where(sd > 0, sd, 1.0)
    X = np.column_stack([np.ones(len(B)), (B - mu) / sd])
    pen = np.diag([0.0] + [lam * len(B)] * B.shape[1])
    w = np.linalg.solve(X.T @ X + pen, X.T @ y)
    return mu, sd, w


def ridge_predict(f: tuple, B: np.ndarray) -> np.ndarray:
    mu, sd, w = f
    return w[0] + ((B - mu) / sd) @ w[1:]


def lsm_fit(tab: dict, rows: np.ndarray) -> dict[int, tuple]:
    """Longstaff and Schwartz on the training paths `rows` (a mask): from k = 59 down to 1 over the paths still open
    at g_k, CF - P(g_k) regressed on the basis; where the fit is below 0 the path exercises (CF = P(g_k))."""
    idx = np.flatnonzero(rows)
    if not len(idx):
        return {}
    G = tab["land"][idx, None] + tab["G1"][None, :]
    Z, S = tab["Z1"][idx], tab["S1"][idx]
    tau, cf = tab["tau"][idx], tab["cf0"][idx].copy()
    fits = {}
    for k in range(len(E1_K) - 1, -1, -1):
        op = tau > G[:, k]
        if op.sum() < E1_MIN_PATHS:
            continue
        B = basis(Z[op, k])
        f = ridge(B, cf[op] - S[op, k])
        fits[k] = f
        ex = np.flatnonzero(op)[ridge_predict(f, B) < 0]
        cf[ex] = S[ex, k]
    return fits


def e1_walk(tab: dict, log=print) -> dict:
    """Per UTC day, the regressions from the days before (train_mask); per path the times E1 sells at."""
    n = len(tab["day"])
    fire: list[np.ndarray | None] = [None] * n
    out = {"days": {}}
    for d in sorted(set(tab["day"].tolist())):
        tr, te = train_mask(tab, d), np.flatnonzero(tab["day"] == d)
        fits = lsm_fit(tab, tr)
        out["days"][d] = {"train": int(tr.sum()), "test": int(len(te)), "fitted_k": len(fits)}
        if not fits:
            continue
        m = np.zeros((len(te), len(E1_K)), dtype=bool)
        for k, f in fits.items():
            m[:, k] = ridge_predict(f, basis(tab["Z1"][te, k])) < 0
        for j, i in enumerate(te):
            fire[i] = tab["land"][i] + tab["G1"][m[j]]
        log(f"os1: E1 {d}: {int(tr.sum())} training paths, {len(fits)} of {len(E1_K)} k fitted")
    out["fire"] = fire
    return out


# ---------------------------------------------------------------- E2: conditional peaks over threshold

def _std(Z: np.ndarray) -> tuple:
    mu, sd = Z.mean(0), Z.std(0)
    return mu, np.where(sd > 0, sd, 1.0)


def logit_fit(X: np.ndarray, y: np.ndarray, lam: float = RIDGE) -> np.ndarray:
    """Logistic regression with a free constant, the mean log loss plus lam / 2 times the squared weights."""
    from scipy.optimize import minimize
    A = np.column_stack([np.ones(len(X)), X])

    def f(w):
        z = A @ w
        p = 1 / (1 + np.exp(-z))
        ll = np.mean(np.logaddexp(0, z) - y * z) + 0.5 * lam * float(w[1:] @ w[1:])
        g = A.T @ (p - y) / len(y)
        g[1:] += lam * w[1:]
        return ll, g
    w0 = np.zeros(A.shape[1])
    m = float(np.clip(y.mean(), 1e-4, 1 - 1e-4))
    w0[0] = math.log(m / (1 - m))
    return minimize(f, w0, jac=True, method="L-BFGS-B").x


def gpd_nll(th: np.ndarray, X: np.ndarray, y: np.ndarray) -> float:
    """The mean negative log likelihood of exceedances y under GPD(sigma = exp(c0 + c x), xi)."""
    xi = th[-1]
    ls = th[0] + X @ th[1:-1]
    s = np.exp(ls)
    if abs(xi) < 1e-6:
        return float(np.mean(ls + y / s))
    a = 1 + xi * y / s
    if np.any(a <= 0):
        return 1e10
    return float(np.mean(ls + (1 + 1 / xi) * np.log(a)))


def gpd_fit(X: np.ndarray, y: np.ndarray) -> np.ndarray:
    from scipy.optimize import minimize
    th0 = np.zeros(X.shape[1] + 2)
    th0[0], th0[-1] = math.log(max(float(y.mean()), 1e-4)), 0.1
    bounds = [(None, None)] * (X.shape[1] + 1) + [XI_BOUNDS]
    return minimize(gpd_nll, th0, args=(X, y), method="L-BFGS-B", bounds=bounds).x


def gpd_tail(x: np.ndarray, sigma: np.ndarray, xi: float) -> np.ndarray:
    """P(Y > x) of GPD(sigma, xi) at x >= 0: (1 + xi x / sigma)^(-1 / xi), the exponential at xi 0, 0 past the end."""
    if abs(xi) < 1e-6:
        return np.exp(-x / sigma)
    a = 1 + xi * x / sigma
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(a > 0, np.power(np.maximum(a, 1e-300), -1 / xi), 0.0)


def e2_fit(Z: np.ndarray, F: np.ndarray) -> dict | None:
    """u, the exceedance's logistic regression and the GPD of the exceedances on training rows; None under the
    registered minimum."""
    ok = np.isfinite(F)
    Z, F = Z[ok], F[ok]
    if len(F) < E2_MIN_ROWS:
        return None
    u = min(float(np.quantile(F, U_Q)), U_MAX)
    exc = F > u
    if exc.sum() < E2_MIN_EXC:
        return None
    mu, sd = _std(Z)
    X = (Z - mu) / sd
    w = logit_fit(X, exc.astype(np.float64))
    th = gpd_fit(X[exc], F[exc] - u)
    return {"u": u, "mu": mu, "sd": sd, "w": w, "th": th, "xi": float(th[-1]), "rows": int(len(F)),
            "exc": int(exc.sum()), "base": float((F > CRASH).mean())}


def e2_predict(m: dict, Z: np.ndarray) -> dict:
    """P(F > u), sigma, P(F > 0.30), the 95 % VaR and ES (nan where P(F > u) is at most 0.05) at states Z."""
    X = (Z - m["mu"]) / m["sd"]
    pu = 1 / (1 + np.exp(-(m["w"][0] + X @ m["w"][1:])))
    th, xi, u = m["th"], m["xi"], m["u"]
    sig = np.exp(th[0] + X @ th[1:-1])
    p = pu * gpd_tail(np.full(len(X), max(CRASH - u, 0.0)), sig, xi) if CRASH > u else pu
    var = np.full(len(X), np.nan)
    es = np.full(len(X), np.nan)
    ok = pu > 1 - ES_Q
    q = (1 - ES_Q) / pu[ok]
    var[ok] = u + (sig[ok] * np.log(1 / q) if abs(xi) < 1e-6 else sig[ok] / xi * (q ** (-xi) - 1))
    es[ok] = (var[ok] + sig[ok] - xi * u) / (1 - xi)
    return {"pu": pu, "sigma": sig, "p": p, "var": var, "es": es}


def e2_walk(tab: dict, log=print) -> dict:
    """Per UTC day, the model from the days before (train_mask); P(F > 0.30), VaR and ES at every row (nan on a day
    without a model)."""
    n, m2 = tab["Z2"].shape[:2]
    out = {"days": {}, "models": {}}
    for k in ("p", "var", "es", "base"):
        out[k] = np.full((n, m2), np.nan)
    for d in sorted(set(tab["day"].tolist())):
        tr, te = train_mask(tab, d), np.flatnonzero(tab["day"] == d)
        m = e2_fit(tab["Z2"][tr].reshape(-1, 7), tab["F2"][tr].ravel()) if tr.any() else None
        out["days"][d] = {"train": int(tr.sum()), "test": int(len(te)), "model": m is not None}
        if m is None:
            continue
        pr = e2_predict(m, tab["Z2"][te].reshape(-1, 7))
        for k in ("p", "var", "es"):
            out[k][te] = pr[k].reshape(len(te), m2)
        out["base"][te] = m["base"]
        out["models"][d] = m
        out["days"][d].update(u=m["u"], xi=m["xi"], rows=m["rows"], exc=m["exc"], base=m["base"])
        log(f"os1: E2 {d}: {m['rows']:,} rows, u {m['u']:.3f}, xi {m['xi']:+.3f}")
    return out


def e2_fire(tab: dict, wf: dict, lam: float) -> list[np.ndarray | None]:
    """Per path the times E2(lam) sells at: P(F > 0.30) above lam (None on a day without a model)."""
    out: list[np.ndarray | None] = []
    for i in range(len(tab["day"])):
        p = wf["p"][i]
        out.append(None if not np.isfinite(p).any() else tab["land"][i] + tab["G2"][np.nan_to_num(p, nan=0.0) > lam])
    return out


# ---------------------------------------------------------------- the exits on every entry

def simulate(pa: FX.Path_, lat, tx_l: int, own: np.ndarray | None = None, stop: bool = True) -> dict:
    """flowexit.simulate with the own exit as signal times (ms, sorted) and the -20 % stop optional: at each turn the
    earliest of the own time, the stop and the take (ties in that order), the time stop at the landing + 300 s; a take
    that would land under TP_FLOOR of its expected proceeds fails, pays its fee and stays due."""
    n = len(pa.t)
    fin = np.isfinite(pa.mult)
    stp = fin & (pa.mult <= 1 - SL) if stop else None
    take = fin & (pa.mult >= 1 + TP)
    start, now, legs = pa.jl, pa.land, 0
    t_end = pa.land + TIME_S * 1000
    while True:
        best = None
        if own is not None and len(own) and start < n:
            k = int(np.searchsorted(own, float(pa.t[start]), side="left"))
            if k < len(own):
                best = (float(own[k]), 0, "own", None)
        for pr, (why, m) in enumerate((("stop", stp), ("take", take)), 1):
            j = FX._first(m, start)
            if j is not None:
                c = (float(pa.t[j]), pr, why, j)
                if best is None or c[:2] < best[:2]:
                    best = c
        if best is None or max(best[0], now) >= t_end:
            sig, why, j = max(t_end, now), "time", None
        else:
            sig, why, j = max(best[0], now), best[2], best[3]
        land = sig + lat(legs)
        got = pa.value_at(land)
        legs += 1
        if why == "take" and got < P.TP_FLOOR * float(pa.v[j]):
            now = land
            start = max(pa.at(land), pa.jl)
            if now >= t_end:
                start = n
            continue
        pnl = got - pa.cost - (1 + legs) * tx_l
        return {"pnl_l": pnl, "why": why, "sig_ms": sig, "exit_ms": land, "legs": legs, "got_l": got, "j_sig": j}


def outcomes(paths: list[FX.Path_], failed: list[dict], c, tx_l: int, own: list | None = None,
             stop: bool | list[bool] = True, gaps=()) -> list[dict]:
    """flowexit.outcomes' rows for an exit given as own signal times per path (None: P_pool0's exits only), the stop
    on or off for all paths or per path."""
    stake = STAKE_SOL * C.LAMPORTS
    out = FX.outcomes([], failed, c, tx_l, "X0", gaps=gaps)
    for i, pa in enumerate(paths):
        r = simulate(pa, FX.lat_fn(c, pa.d["mint"]), tx_l, own[i] if own is not None else None,
                     stop[i] if isinstance(stop, list) else stop)
        s0, s1 = pa.d["signal_ms"], pa.land + TIME_S * 1000 + 60_000
        out.append({"i": i, "mint": pa.d["mint"], "signal_ms": s0, "day": day_of(s0), "ret": r["pnl_l"] / stake,
                    "pnl_sol": r["pnl_l"] / C.LAMPORTS, "why": r["why"], "exit_ms": r["exit_ms"], "legs": r["legs"],
                    "got_l": r["got_l"], "j_sig": r["j_sig"], "sig_ms": r["sig_ms"], "failed": False,
                    "hold_s": (r["exit_ms"] - pa.land) / 1000, "best_l": FX.best_gain(pa, tx_l), "pnl_l": r["pnl_l"],
                    "gapped": bool(any(g0 < s1 and s0 < g1 for g0, g1 in gaps))})
    return sorted(out, key=lambda e: (e["signal_ms"], e["mint"]))


def split(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    return [x for x in rows if x["day"] < OOS_FROM], [x for x in rows if x["day"] >= OOS_FROM]


# ---------------------------------------------------------------- the verdict

def f3_pool(root=None) -> tuple[list[float] | None, int]:
    """F3's per-entry Sharpes (the noise) and its trial count from its ledger; (None, 0) without it."""
    from . import factory as F
    from .. import data
    p = Path(root or data.ROOT) / "pumpfun_rt" / "factory" / "ledger.jsonl"
    if not p.exists():
        return None, 0
    sh, n = F.pool(F.read_ledger(p))
    return sh, n


def deflate(diff: np.ndarray, days: np.ndarray, sharpes: list[float] | None, n: int | None) -> dict:
    """The paired differences' Sharpe per entry on its effective entries clustered by day (factory.by_day),
    deflated against n trials with F3's Sharpes as the noise (factory.deflated); None without a pool."""
    from . import factory as F
    u = sorted(set(days.tolist()))
    ix = np.array([u.index(d) for d in days], dtype=int)
    sd = float(diff.std(ddof=1)) if len(diff) > 1 else 0.0
    r = {"entries": len(diff), "sharpe": float(diff.mean() / sd) if sd > 0 else 0.0,
         "skew": float(((diff - diff.mean()) ** 3).mean() / sd ** 3) if sd > 0 else 0.0,
         "kurt": float(((diff - diff.mean()) ** 4).mean() / sd ** 4) if sd > 0 else 3.0} | F.by_day(diff, ix, len(u))
    ok = sharpes is not None and len([v for v in sharpes if math.isfinite(v)]) >= 2 and n
    return {"sharpe": r["sharpe"], "n_eff": r["n_eff"], "n_trials": n,
            "dsr": F.deflated(r, sharpes, n) if ok else None, "bar": F.bar(sharpes, n) if ok else None}


def verdict(var: list[dict], base: list[dict], sharpes: list[float] | None = None, n: int | None = None) -> dict:
    """The registered rule: a higher mean on the same entries, the day-block band of the paired difference above 0,
    the deflated Sharpe of the paired differences at least DSR_PASS."""
    a = {(x["signal_ms"], x["mint"]): x for x in var}
    pairs = [(a[k]["ret"], b["ret"], b["day"], b["why"]) for b in base for k in [(b["signal_ms"], b["mint"])]
             if k in a]
    if not pairs:
        return {"n": 0, "diff": None, "band": (math.nan, math.nan), "passes": False}
    r1, r0 = np.array([p[0] for p in pairs]), np.array([p[1] for p in pairs])
    days = np.array([p[2] for p in pairs], dtype=object)
    diff = r1 - r0
    lo, hi = FX.day_band(diff, days)
    df = deflate(diff, days, sharpes, n)
    on = np.array([p[3] == "stop" for p in pairs])
    out = {"n": len(pairs), "diff": float(diff.mean()), "band": (lo, hi), "higher": bool(r1.mean() > r0.mean()),
           "band_above": bool(math.isfinite(lo) and lo > 0), "deflated": df, "x0_stops": int(on.sum()),
           "on_x0_stops": float(diff[on].mean()) if on.any() else None,
           "on_the_rest": float(diff[~on].mean()) if (~on).any() else None,
           "dsr_ok": bool(df["dsr"] is not None and df["dsr"] >= DSR_PASS)}
    out["passes"] = out["higher"] and out["band_above"] and out["dsr_ok"]
    return out


def summary(rows: list[dict], base: list[dict], tx_l: int, sharpes=None, n=None) -> dict:
    s = FX.stats(rows)
    s["verdict"] = verdict(rows, base, sharpes, n)
    s["verdict_no_gap"] = verdict([x for x in rows if not x["gapped"]], [x for x in base if not x["gapped"]],
                                  sharpes, n)
    s["books"] = {k: FX.book(rows, lim, tx_l) for k, lim in SIZINGS.items()}
    return s


# ---------------------------------------------------------------- E2's calibration and shortfall

def calibration(tab: dict, wf: dict, oos: np.ndarray) -> dict:
    """On the out-of-sample rows with a model: Brier against the constant hazard, AUC, five bins by the prediction."""
    from . import model as M
    p, y, b = wf["p"][oos].ravel(), tab["F2"][oos].ravel(), wf["base"][oos].ravel()
    ok = np.isfinite(p) & np.isfinite(y)
    p, y, b = p[ok], (y[ok] > CRASH).astype(np.float64), b[ok]
    if not len(p):
        return {"n": 0}
    bm, b0 = float(np.mean((p - y) ** 2)), float(np.mean((b - y) ** 2))
    out = {"n": int(len(p)), "rate": float(y.mean()), "brier": bm, "brier_const": b0,
           "skill": 1 - bm / b0 if b0 > 0 else None, "auc": M.auc(p, y), "bins": []}
    edges = np.quantile(p, np.linspace(0, 1, CALIB_BINS + 1))
    k = np.clip(np.searchsorted(edges, p, side="right") - 1, 0, CALIB_BINS - 1)
    for j in range(CALIB_BINS):
        m = k == j
        if m.any():
            out["bins"].append({"n": int(m.sum()), "pred": float(p[m].mean()), "obs": float(y[m].mean())})
    return out


def es_backtest(tab: dict, wf: dict, oos: np.ndarray) -> dict:
    """The rows where the 95 % VaR is defined: the share with F above it and on those the mean F and mean ES."""
    v, e, y = wf["var"][oos].ravel(), wf["es"][oos].ravel(), tab["F2"][oos].ravel()
    ok = np.isfinite(v) & np.isfinite(y)
    rows = int(np.isfinite(wf["p"][oos]).sum())
    if not ok.any():
        return {"n": 0, "rows": rows}
    hit = y[ok] > v[ok]
    return {"n": int(ok.sum()), "rows": rows, "share": float(hit.mean()), "expected": 1 - ES_Q,
            "f_mean": float(y[ok][hit].mean()) if hit.any() else None,
            "es_mean": float(e[ok][hit].mean()) if hit.any() else None, "es_all": float(np.mean(e[ok]))}


def stop_shortfall(paths: list[FX.Path_], tab: dict, wf: dict, x0: list[dict]) -> dict:
    """X0's out-of-sample stops: at the last whole second g before the stop's signal, the model's ES and
    P(F > 0.30) against what the stop lost, 1 - the value at its landing over the value at g + L."""
    rows = []
    for x in x0:
        if x["why"] != "stop" or x["i"] < 0 or x["day"] < OOS_FROM:
            continue
        i, pa = x["i"], paths[x["i"]]
        k = int(math.floor((x["sig_ms"] - pa.land - 1) / 1000)) - 1     # E2_G[k] = k + 1 s: before the signal
        if k < 0 or k >= len(E2_G) or not np.isfinite(wf["p"][i, k]):
            continue
        g = pa.land + tab["G2"][k]
        v0 = pa.value_at(g + L_MS)
        if v0 <= 0:
            continue
        rows.append({"p": float(wf["p"][i, k]), "es": float(wf["es"][i, k]), "lost": 1 - pa.value_at(x["exit_ms"]) / v0,
                     "after_s": (x["exit_ms"] - g) / 1000})
    if not rows:
        return {"n": 0}
    es = np.array([r["es"] for r in rows])
    lost = np.array([r["lost"] for r in rows])
    after = np.array([r["after_s"] for r in rows])
    return {"n": len(rows), "p_mean": float(np.mean([r["p"] for r in rows])),
            "es_n": int(np.isfinite(es).sum()), "es_mean": float(np.nanmean(es)) if np.isfinite(es).any() else None,
            "lost_mean": float(lost.mean()), "lost_median": float(np.median(lost)),
            "lost_mean_es": float(lost[np.isfinite(es)].mean()) if np.isfinite(es).any() else None,
            "after_median_s": float(np.median(after)), "after_over_10s": float((after > FALL_S + L_MS / 1000).mean())}


# ---------------------------------------------------------------- the evaluation

def evaluate(res: dict, log=print) -> dict:
    from .. import metrics
    c = costs()
    tx_l, gaps = res["tx_l"], res.get("gaps", ())
    paths = [FX.Path_(d) for d in res["paths"] if d.get("land_ms") is not None and d["tokens"] > 0]
    failed = res["failed"]
    x0 = FX.outcomes(paths, failed, c, tx_l, "X0", gaps=gaps)
    mine = outcomes(paths, failed, c, tx_l, gaps=gaps)
    same = [abs(a["ret"] - b["ret"]) < 1e-9 and a["why"] == b["why"] for a, b in zip(x0, mine)]
    sharpes, n_f3 = f3_pool()
    n_all = metrics.trial_pool(extra=trials())["n_trials"] + n_f3
    x0_in, x0_oos = split(x0)
    out = {"entries": len(x0), "paths": len(paths), "failed": len(failed), "in_sample": len(x0_in),
           "oos": len(x0_oos), "tx_l": tx_l, "L_ms": L_MS, "x0_check": float(np.mean(same)) if same else None,
           "n_trials": n_all, "f3_trials": n_f3, "f3_sharpes": len(sharpes or [])}
    out["x0"] = {"oos": summary(x0_oos, x0_oos, tx_l, sharpes, n_all), "in": FX.stats(x0_in)}
    tab = tables(paths)
    log(f"os1: {len(paths)} paths tabled")
    # E1
    w1 = e1_walk(tab, log)
    e1 = outcomes(paths, failed, c, tx_l, w1["fire"], [f is None for f in w1["fire"]], gaps)   # no fit: X0
    e1_in, e1_oos = split(e1)
    own = [x for x in e1_oos if x["why"] == "own"]
    out["E1"] = {"oos": summary(e1_oos, x0_oos, tx_l, sharpes, n_all), "in": FX.stats(e1_in),
                 "in_diff": verdict(e1_in, x0_in)["diff"], "days": w1["days"],
                 "own_up": sum(x["ret"] > 0 for x in own), "own_down": sum(x["ret"] <= 0 for x in own)}
    out["E1"]["passes"] = out["E1"]["oos"]["verdict"]["passes"]
    # E2
    w2 = e2_walk(tab, log)
    ins = [i for i, pa in enumerate(paths) if day_of(pa.d["signal_ms"]) < OOS_FROM]
    f_in = [f for f in failed if day_of(f["signal_ms"]) < OOS_FROM]
    grid = []
    for lam in LAMBDAS:
        fire = e2_fire(tab, w2, lam)
        r = outcomes([paths[i] for i in ins], f_in, c, tx_l, [fire[i] for i in ins], gaps=gaps)
        grid.append((lam, float(np.mean([x["ret"] for x in r])) if r else -math.inf))
    lam = max(grid, key=lambda g: g[1])[0] if grid else None    # max keeps the first of equals
    p_oos = w2["p"][tab["day"] >= OOS_FROM]
    p_ins = w2["p"][tab["day"] < OOS_FROM]
    above = {lv: {"in_rows": int((np.nan_to_num(p_ins) > lv).sum()), "oos_rows": int((np.nan_to_num(p_oos) > lv).sum()),
                  "oos_paths": int((np.nan_to_num(p_oos) > lv).any(axis=1).sum())} for lv in LAMBDAS}
    q = p_oos[np.isfinite(p_oos)]
    p_q = np.quantile(q, [0.5, 0.9, 0.99, 0.999, 1.0]).tolist() if len(q) else None
    e2 = outcomes(paths, failed, c, tx_l, e2_fire(tab, w2, lam), gaps=gaps)
    e2_in, e2_oos = split(e2)
    oos = tab["day"] >= OOS_FROM
    out["E2"] = {"lambda": lam, "grid": grid, "above": above, "p_quantiles": p_q,
                 "oos": summary(e2_oos, x0_oos, tx_l, sharpes, n_all),
                 "in": FX.stats(e2_in), "in_diff": verdict(e2_in, x0_in)["diff"], "days": w2["days"],
                 "calibration": calibration(tab, w2, oos), "es": es_backtest(tab, w2, oos),
                 "stops": stop_shortfall(paths, tab, w2, x0)}
    out["E2"]["passes"] = out["E2"]["oos"]["verdict"]["passes"]
    ok = [e for e in EXITS if out[e]["passes"]]
    out["pick"] = max(ok, key=lambda e: out[e]["oos"]["mean"]) if ok else None
    return out


# ---------------------------------------------------------------- report

pct = RL.pct


def _b(b) -> str:
    return f"{pct(b[0])} to {pct(b[1])}"


def _row(name: str, s: dict, base: bool = False) -> str:
    v = s["verdict"]
    bl, bw = s["books"]["live"], s["books"]["wide"]
    st = s.get("stops") or {}
    df = v.get("deflated") or {}
    dsr = "" if base else ("n/a" if df.get("dsr") is None else f"{df['dsr']:.3f}")
    ex = ", ".join(f"{k} {n}" for k, n in (s.get("exits") or {}).items())
    return (f"| {name} | {s['n']} | {pct(s.get('mean'))} | {pct(s.get('median'))} | {s.get('win', 0) * 100:.0f} % | "
            f"{s.get('pnl_sol', 0):+.3f} | {st.get('n', 0)}, {pct(st.get('mean'))} | {ex} | "
            f"{'' if base else pct(v['diff'])} | {'' if base else _b(v['band'])} | {dsr} | "
            f"{'' if base else ('yes' if v['passes'] else 'no')} | "
            f"{bl['n']}, {pct(bl['mean'])}, {bl['pnl_sol']:+.3f}, {bl['max_dd_sol']:.3f} | "
            f"{bw['n']}, {pct(bw['mean'])}, {bw['pnl_sol']:+.3f}, {bw['max_dd_sol']:.3f} |")


def report_md(res: dict, ev: dict) -> str:
    def utc(x):
        return f"{datetime.fromtimestamp(x / 1000, timezone.utc):%Y-%m-%d %H:%M} UTC"
    md = ["# OS1: least-squares Monte Carlo and conditional GPD exits for P_pool0 (os1)", "",
          f"Record {res['days'][0]} to {utc(res['span'][1])}, signals to {utc(res['entry_until_ms'])}; out of sample "
          f"from {OOS_FROM}. {STAKE_SOL} SOL, every P_pool0 signal entered, paired by entry; {ev['entries']} entries "
          f"({ev['failed']} failed buys), {ev['oos']} out of sample, {ev['tx_l']:,} lamports a transaction, L "
          f"{ev['L_ms']:.0f} ms. The simulator here reproduces flowexit's X0 on {(ev['x0_check'] or 0) * 100:.1f} % of "
          f"the entries. Deflation: {ev['n_trials']} trials ({ev['f3_trials']} of them F3's), F3's noise from "
          f"{ev['f3_sharpes']} Sharpes.", "", "## Out of sample", "",
          "| exit | entries | mean | median | win | P&L SOL | stops: n, mean | exits | vs X0 | band (days) | DSR | "
          "passes "
          "| live book: n, mean, P&L, max DD | wide book: n, mean, P&L, max DD |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
          _row("X0 (P_pool0)", ev["x0"]["oos"], True), _row("E1 (LSM)", ev["E1"]["oos"]),
          _row(f"E2 (GPD, lambda {ev['E2']['lambda']})", ev["E2"]["oos"])]
    for e in EXITS:
        v = ev[e]["oos"]["verdict_no_gap"]
        df = ev[e]["oos"]["verdict"]["deflated"]
        md += ["", f"{e}: in sample {pct(ev[e]['in'].get('mean'))} against X0 {pct(ev['x0']['in'].get('mean'))} "
               f"({pct(ev[e]['in_diff'])}); without trades open across a gap {pct(v['diff'])} ({_b(v['band'])}); "
               f"on X0's {ev[e]['oos']['verdict']['x0_stops']} stops {pct(ev[e]['oos']['verdict']['on_x0_stops'])}, on "
               f"the rest {pct(ev[e]['oos']['verdict']['on_the_rest'])}; paired Sharpe per entry {df['sharpe']:+.3f} "
               f"on {df['n_eff']:.0f} effective entries, bar "
               f"{df['bar'] if df['bar'] is None else format(df['bar'], '.3f')}."]
    e1 = ev["E1"]
    md += ["", "E1 days: " + "; ".join(f"{d} {x['train']} paths, {x['fitted_k']} k" for d, x in e1["days"].items())
           + f". Its own sales out of sample: {e1['own_up']} above the entry, {e1['own_down']} at or below."]
    e2 = ev["E2"]
    md += ["", "E2 days: " + "; ".join(
        f"{d} " + (f"u {x['u']:.3f}, xi {x['xi']:+.3f}, {x['exc']:,} of {x['rows']:,}, base {x['base']:.4f}"
                   if x["model"] else "no model") for d, x in e2["days"].items()),
           "", "E2 lambda grid in sample: " + ", ".join(f"{g}: {pct(m)}" for g, m in e2["grid"])
           + "; rows (seconds) above each level in sample and out of sample, positions out of sample: "
           + "; ".join(f"{lv}: {a['in_rows']:,}, {a['oos_rows']:,}, {a['oos_paths']}" for lv, a in e2["above"].items())
           + ("; P(F > 30 %) out of sample at 50/90/99/99.9/100 %: "
              + ", ".join(f"{q * 100:.2f} %" for q in e2["p_quantiles"]) if e2["p_quantiles"] else "")]
    ca = e2["calibration"]
    if ca.get("n"):
        md += ["", f"E2 calibration out of sample ({ca['n']:,} rows, rate of F > 30 % {ca['rate'] * 100:.2f} %): Brier "
               f"{ca['brier']:.5f} against {ca['brier_const']:.5f} for the constant hazard, skill "
               f"{ca['skill']:+.3f}, AUC {ca['auc']:.3f}; bins (predicted, observed, n): "
               + "; ".join(f"{b['pred'] * 100:.2f} %, {b['obs'] * 100:.2f} %, {b['n']:,}" for b in ca["bins"])]
    es = e2["es"]
    if es.get("n"):
        md += ["", f"E2 shortfall backtest: VaR 95 % defined on {es['n']:,} of {es['rows']:,} rows; F above it on "
               f"{es['share'] * 100:.1f} % (5 % expected), there mean F {pct(es['f_mean'])} against mean ES "
               f"{pct(es['es_mean'])}."]
    s = e2["stops"]
    if s.get("n"):
        md += ["", f"X0's stops out of sample ({s['n']}): the model before the signal P(F > 30 %) "
               f"{s['p_mean'] * 100:.1f} % "
               f"on average, ES {pct(s['es_mean'])} on {s['es_n']}; what the stops lost from g + L to the landing "
               f"{pct(s['lost_mean'])} (median {pct(s['lost_median'])}; {pct(s['lost_mean_es'])} where the ES is "
               f"defined); the landing a median {s['after_median_s']:.1f} s after g, "
               f"{s['after_over_10s'] * 100:.0f} % past the 10 s window."]
    md += ["", f"Pick: {ev['pick'] or 'none passes'}."]
    return "\n".join(md) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--until-ms", type=int, default=UNTIL_MS)
    ap.add_argument("--out", default=None, help="directory for os1.json and os1.md (default: the reports)")
    ap.add_argument("--cache", default=None, help="the replay, kept and read again")
    ap.add_argument("--no-register", action="store_true")
    ap.add_argument("--register-only", action="store_true", help="the trials into R5's registry, nothing else")
    ap.add_argument("--replay-only", action="store_true", help="the replay into --cache, nothing else")
    a = ap.parse_args(argv)
    from .. import metrics
    from .. import report as rep
    if not a.no_register:
        new = metrics.register(trials())                # before any number exists
        print(f"os1: {len(new)} trials registered")
    if a.register_only:
        return 0
    out = Path(a.out) if a.out else rep.REPORTS / "pumpfun_rt"
    out.mkdir(parents=True, exist_ok=True)
    cache = Path(a.cache) if a.cache else None
    if cache is not None and cache.exists():
        res = pickle.loads(cache.read_bytes())
    else:
        res = run(until_ms=a.until_ms)
        if res.get("empty"):
            print("os1: nothing recorded")
            return 1
        if cache is not None:
            cache.write_bytes(pickle.dumps(res, protocol=pickle.HIGHEST_PROTOCOL))
    if a.replay_only:
        return 0
    ev = evaluate(res)
    md = report_md(res, ev)
    keep = {k: v for k, v in res.items() if k not in ("paths", "failed", "pipe_closed")}
    (out / "os1.json").write_text(json.dumps(FX._clean(keep | {"eval": ev}), indent=1, default=str), encoding="utf-8")
    (out / "os1.md").write_text(md, encoding="utf-8")
    print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
