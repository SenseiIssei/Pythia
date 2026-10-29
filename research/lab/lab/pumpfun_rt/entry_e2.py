"""E2: entry filters for P_pool0 against farmed completions, linked wallets, wash trading and bad regimes, and a later
entry once the snipers hold little; on the whole record at the latency the live executor measures since 2026-10-29.
PAPER ONLY.

    python -m lab.pumpfun_rt.entry_e2                   replay, features, filters, write entry_e2.{json,md}
    python -m lab.pumpfun_rt.entry_e2 --out DIR         the same, written into DIR
    python -m lab.pumpfun_rt.entry_e2 --cache FILE      the replay kept in FILE (read again if it exists)
    python -m lab.pumpfun_rt.entry_e2 --register-only   the 29 trials into R5's registry, nothing else

Pre-registered in results/pumpfun_entry_e2_prereg.md. Every P_pool0 signal of the record is entered at 0.05 SOL with
no book limit (X14 r2's replay, flowexit.FlowPipe), at the live executor's latency since 2026-10-29 00:00 UTC (Y5's
kernel density of its P_pool0 fills). The engine keeps per coin on its curve the transaction, slot and wallet of its
trades (CurveRec), so at the signal: F1 how long the curve was idle before the completing transaction and how much
that transaction bought, F2 the price drop if the largest group of early wallets linked by a shared transaction or
slot sold into the pool, F3 the wash transactions (a wallet buying and selling about the same SOL in one
transaction). F4 the regime: a pause on the stop rate of the last closed entries, only if the outcomes cluster.
F5 the snipers' share of the supply along each entry's path, for a later entry. Each filter keeps or skips a P_pool0
signal and is judged against P_pool0 (X0) paired by migration. Nothing here holds a wallet, reads a key, signs or
sends anything; the live executor's files are only read, never its key or its wallet.
"""

from __future__ import annotations

import argparse
import bisect
import dataclasses
import json
import math
import pickle
import sys
import time
from array import array
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from . import curve as C
from . import flowexit as FX
from . import pipeline as P
from . import reallat as RL
from . import sim
from .tokens import SUPPLY

# ---------------------------------------------------------------- registered (results/pumpfun_entry_e2_prereg.md)

PREREG = "results/pumpfun_entry_e2_prereg.md"
BASE = FX.BASE
_utc = FX._utc
day_of = FX.day_of
SINCE_MS = _utc(2026, 10, 29)                           # the live fills from here
UNTIL_MS = _utc(2026, 10, 29, 19, 30)                   # the cutoff
TAIL_MS = 12 * 60_000                                   # signals stop this long before it: a 120 s late entry closes
OOS_FROM = FX.OOS_FROM                                  # in sample: the UTC days before 2026-10-24
# The executor's P_pool0 fills, signal to landing (ms), 2026-10-29 00:00 UTC to the cutoff, as logged.
LIVE_BUY_MS = FX.LIVE_BUY_MS + (-59,)
LIVE_SELL_MS = FX.LIVE_SELL_MS + (813, 461)
LIVE_FEE_L = 108_938                                    # the mean of the window's 66 transaction fees (lamports)
STAKE_SOL = FX.STAKE_SOL
PATH_MS = 600_000                                       # the path after the landing (a 120 s late entry's 300 s too)
EARLY_MS = 30_000                                       # F2's early buyers: within 30 s of the creation
WASH_TOL = 0.10                                         # F3: the buy and the sale within 10 % of the larger
F1_IDLE_S = (60.0, 300.0, 1800.0, None)                 # None: off
F1_SHARE = (0.05, 0.10, 0.20, 0.30, None)
F1_GRID = tuple((i, s) for i in F1_IDLE_S for s in F1_SHARE if not (i is None and s is None))
F2_DROP = FX.SL                                         # worse than the stop
F3_K = (1, 2, 5, 10, 25)
F4_N = (10, 20, 40)
F4_L = (0.4, 0.5, 0.6)
F4_GRID = tuple((n, lv) for n in F4_N for lv in F4_L)
F4_TEST_N, F4_MIG_MS, F4_K = 20, 3_600_000, (1, 2, 3)
F4_P = 0.05
F5_D = (0, 5, 15, 30, 60, 120)
F5_Q = (25, 50, 75)
KEEP_MIN = 0.30
BOOT, SEED, MIN_DAYS = FX.BOOT, FX.SEED, FX.MIN_DAYS
SIZINGS = FX.SIZINGS
FILTERS = ("F1", "F2", "F3", "F4")
F5_CELLS = tuple(f"F5_d{d}_q{q}" for d in F5_D for q in F5_Q)
F5_ALL = tuple(f"F5_d{d}_all" for d in F5_D)


def trials() -> list[dict]:
    ids = ["F1", "F2", "F3", "F4_test", "F4"] + list(F5_CELLS) + list(F5_ALL)
    return [{"id": f"pumpfun:entry_e2:{k}", "family": "pumpfun", "n": 1, "sharpe": None, "source": PREREG}
            for k in ids]


def costs() -> RL.FillCosts:
    nb, ns = FX._clip(LIVE_BUY_MS, *FX.CLIP_N), FX._clip(LIVE_SELL_MS, *FX.CLIP_N)
    return RL.FillCosts(lat_median_ms=float(np.median(nb)), lat_lo_ms=FX.CLIP_N[0], lat_hi_ms=FX.CLIP_N[1],
                        priority_sol=RL.priority_for(LIVE_FEE_L / C.LAMPORTS), buy=RL.LogKDE(nb, *FX.CLIP_N),
                        sell=RL.LogKDE(ns, *FX.CLIP_N))


# ---------------------------------------------------------------- the curve as the record holds it

class CurveRec:
    """One coin's curve: the transaction now trading (its first time and buy SOL), the last trade time before it,
    the early buys (transaction, slot, wallet) and the wash transactions so far."""

    __slots__ = ("cur_tx", "cur_t0", "cur_buy", "prev_t", "last_t", "early", "wash_n", "txu")

    def __init__(self):
        self.cur_tx = self.cur_t0 = self.prev_t = self.last_t = None
        self.cur_buy = 0
        self.early: list[tuple] = []
        self.wash_n = 0
        self.txu: dict[str, list] = {}

    def trade(self, t, tx, slot, buy: bool, sol: int, user: str, t0: int) -> None:
        if tx != self.cur_tx or self.cur_tx is None:
            self.wash_n += washes(self.txu)
            self.prev_t, self.cur_tx, self.cur_t0, self.cur_buy, self.txu = self.last_t, tx, t, 0, {}
        sol = int(sol or 0)
        if buy:
            self.cur_buy += sol
        u = self.txu.setdefault(user or "", [0, 0])
        u[0 if buy else 1] += sol
        self.last_t = t
        if buy and t - t0 <= EARLY_MS and len(self.early) < 400:
            self.early.append((tx, slot, user or ""))


def washes(txu: dict) -> int:
    """Wallets of one transaction that bought and sold on the curve, the two SOL amounts within WASH_TOL."""
    return sum(1 for u, (b, s) in txu.items() if u and b > 0 and s > 0 and abs(b - s) <= WASH_TOL * max(b, s))


def link_groups(early: list[tuple]) -> list[set]:
    """Early buyers linked by a shared transaction or slot (union-find); the groups of two or more wallets."""
    parent: dict[str, str] = {}

    def find(w):
        while parent[w] != w:
            parent[w] = parent[parent[w]]
            w = parent[w]
        return w
    first: dict[tuple, str] = {}
    for tx, slot, w in early:
        if not w:
            continue
        parent.setdefault(w, w)
        for k in (("tx", tx), ("slot", slot)):
            if k[1] is None:
                continue
            o = first.setdefault(k, w)
            a, b = find(o), find(w)
            if a != b:
                parent[b] = a
    groups: dict[str, set] = {}
    for w in parent:
        groups.setdefault(find(w), set()).add(w)
    return [g for g in groups.values() if len(g) >= 2]


def link_drop(x: float, h: float) -> float:
    """The pool's price drop if h tokens were sold into a pool holding x: 1 - (x / (x + h))^2."""
    return 1 - (x / (x + h)) ** 2 if x > 0 and h > 0 else 0.0


def curve_features(eng, tok) -> dict:
    """F1, F2 and F3 at the signal, from what the engine has seen of the coin's curve."""
    nan = math.nan
    cr = eng.curve.get(tok.mint)
    out = {"idle_s": nan, "idle_gap": False, "done_share": nan, "wash_n": nan, "link_drop": nan, "link_h": nan,
           "link_n": 0, "early_n": 0, "curve_seen": cr is not None}
    if cr is None or cr.cur_tx is None:
        return out
    a = cr.prev_t if cr.prev_t is not None else tok.t0
    if any(g0 < cr.cur_t0 and a < g1 for g0, g1 in eng.gaps):
        out["idle_gap"] = True                          # a stream gap: the idle time is not known
    else:
        out["idle_s"] = (cr.cur_t0 - a) / 1000
    out["done_share"] = cr.cur_buy / tok.rs if tok.rs else nan
    out["wash_n"] = float(cr.wash_n + washes(cr.txu))
    out["early_n"] = len({w for _, _, w in cr.early})
    best = (0.0, 0.0, 0)
    x = float(tok.pb)
    for g in link_groups(cr.early):
        h = float(sum(tok.hold.get(w, 0) for w in g))
        dr = link_drop(x, h)
        if dr > best[0] or (not best[2]):
            best = (dr, h, len(g))
    out["link_drop"], out["link_h"], out["link_n"] = best[0], best[1] / SUPPLY, best[2]
    return out


class E2Engine(sim.Engine):
    """sim.Engine that also keeps every curve's CurveRec (dropped when the coin is evicted) and every migration's
    time (F4's migration rate)."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.curve: dict[str, CurveRec] = {}
        self.mig_ms: list[float] = []

    def trade(self, t, tx, mint, buy, sol, tok_amt, user, vs, vt, rs, rt, fb, cfb, slot=None, sig=None) -> None:
        tok = self.tokens.get(mint)
        if tok is not None:
            cr = self.curve.get(mint)
            if cr is None:
                cr = self.curve[mint] = CurveRec()
            cr.trade(t, tx, slot, buy, sol, user, tok.t0)
        super().trade(t, tx, mint, buy, sol, tok_amt, user, vs, vt, rs, rt, fb, cfb, slot, sig=sig)

    def migrate(self, t, mint, pool, sol, tok_amt, bts=None) -> None:
        self.mig_ms.append(float(t))
        super().migrate(t, mint, pool, sol, tok_amt, bts)

    def _a_evict(self, at, mint) -> None:
        super()._a_evict(at, mint)
        if mint not in self.tokens:
            self.curve.pop(mint, None)


# ---------------------------------------------------------------- the replay

class E2Rec(FX.Rec):
    """X14 r2's recording with the snipers' share of the supply and the pool's own fee at every point, the curve
    features at the signal, and no step rows; kept also when the buy failed (F5 enters later)."""

    def __init__(self, pid: int, tok, t: float, group: set, fee_floor: int, snipers: set | None, feat: dict):
        self.snipers = snipers or set()
        self.snip_col, self.fee0_col = array("f"), array("f")
        self.feat = dict(feat, snip_known=snipers is not None)
        self.x0_failed = False
        super().__init__(pid, tok, t, group, fee_floor)

    def add(self, t, tok, buy, user, amt, dq, fresh) -> None:
        super().add(t, tok, buy, user, amt, dq, fresh)
        self.snip_col.append(sum(tok.hold.get(w, 0) for w in self.snipers) / SUPPLY)
        self.fee0_col.append(float(tok.amm_fee_bps))

    def landed(self, at, tokens, cost_l, fee_l) -> None:
        super().landed(at, tokens, cost_l, fee_l)
        self.end_ms = int(at) + PATH_MS

    def step(self, eng, tok, t, v) -> None:
        return None

    def pack(self, complete: bool) -> dict:
        out = super().pack(complete)
        out["snip"] = np.frombuffer(self.snip_col, dtype=np.float32).copy()
        out["fee0"] = np.frombuffer(self.fee0_col, dtype=np.float32).copy()
        out.update(feat=self.feat, x0_failed=self.x0_failed)
        for k in ("X", "step_pt", "dar", "hk5", "hk30", "bbn", "bblast"):     # not used here
            out.pop(k, None)
        return out


class E2Pipe(FX.FlowPipe):
    """P_pool0 at the live latency, every signal entered, each entry recorded as an E2Rec with its features."""

    def signal(self, s, tok, t: float) -> None:
        before = self.eng.next_pid
        P.Pipeline.signal(self, s, tok, t)
        if self.eng.next_pid > before and before in self.pos:
            st = self.eng.early.st.get(tok.mint)
            self.recs[before] = E2Rec(before, tok, t, set(), self.floor, set(st.snipers) if st is not None else None,
                                      curve_features(self.eng, tok))
            self.rec_by_mint.setdefault(tok.mint, []).append(before)

    def buy_failed(self, pid: int, at: float, why: str, fee_l: int) -> None:
        r = self.recs.get(pid)
        if r is not None:                               # kept: F5's later entry needs the path from the signal
            r.x0_failed = True
            r.end_ms = int(at) + PATH_MS
            self.eng.push(r.end_ms, "pipe", (self, "_rec_end", pid))
        P.Pipeline.buy_failed(self, pid, at, why, fee_l)

    def finish(self) -> None:
        for pid in list(self.recs):
            r = self._drop(pid)
            if r is not None and (r.land_ms is not None or r.x0_failed):
                self.paths.append(r.pack(False))


def run(root=None, until_ms: int = UNTIL_MS, log=print) -> dict:
    """The full replay of every P_pool0 signal at the live latency, up to until_ms; signals stop TAIL_MS before."""
    from . import early as EA
    from . import store
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
    eng = E2Engine([], book=warm_book([], root), decisions=False, rule_costs={strat.name: c},
                   entry_until=t_hi - TAIL_MS, wallets=W.warm([], root), snipers=EA.warm_snipers([], root))
    pipe = eng.add_pipe(E2Pipe(eng, strat, {}))
    t0 = time.time()
    sim.replay(days, eng, root, until_ms=t_hi,
               progress=lambda d, n: log(f"entry_e2: {d} {n:,} rows, {time.time() - t0:.0f} s, "
                                         f"{len(pipe.paths) + len(pipe.recs)} entries"))
    pipe.finish()
    log(f"entry_e2: replay in {time.time() - t0:.0f} s")
    return {"days": days, "span": (t_lo, t_hi), "until_ms": until_ms, "entry_until_ms": t_hi - TAIL_MS,
            "recs": pipe.paths, "failed": [dict(f) for f in pipe.failed],
            "pipe_closed": [{x: cl.get(x) for x in ("pid", "mint", "exit_why", "ret", "exit_ms")}
                            for cl in pipe.closed],
            "skipped": {f"{n}|{w}": k for (n, w), k in eng.skipped.items() if n.startswith(BASE + "@")},
            "gaps": [tuple(g) for g in eng.gaps], "tx_l": c.tx_lamports(), "mig_ms": list(eng.mig_ms)}


# ---------------------------------------------------------------- X0 and F5 on the paths

def key(x: dict) -> tuple:
    return (int(x["mig_ms"] if "mig_ms" in x else x["signal_ms"]), x["mint"])


def x0_rows(res: dict, c=None) -> list[dict]:
    """X0, P_pool0 as it is, on every entry (flowexit.outcomes); each row with its migration key."""
    c = c or costs()
    paths = [FX.Path_(d) for d in res["recs"] if d.get("land_ms") is not None and d["tokens"] > 0]
    rows = FX.outcomes(paths, res["failed"], c, res["tx_l"], "X0", gaps=res.get("gaps", ()))
    for x in rows:
        x["mig_ms"] = int(x["signal_ms"])
    return rows


def late_entry(d: dict, delay_ms: float, thr: float | None, c, tx_l: int, gaps=()) -> dict | None:
    """F5 on one recorded signal: at the signal + delay_ms, skip (None) when the snipers' share then is above thr
    (or not known); else buy at that state's expected tokens, land one buy draw later, fail under the expected over
    1 + SLIP_TOL (its fee lost), and exit as P_pool0 from that landing."""
    t = d["t"]
    sig = float(d["signal_ms"]) + delay_ms
    i = max(int(np.searchsorted(t, sig, side="right")) - 1, 0)
    if thr is not None and (not d["feat"].get("snip_known") or float(d["snip"][i]) > thr):
        return None
    x, y = int(d["x"][i]), int(d["y"][i])
    if x <= 0 or y <= 0:
        return None
    stake = min(int(STAKE_SOL * C.LAMPORTS), int(P.MAX_IMPACT * y))
    want = C.pool_buy(stake, x, y, int(d["fee0"][i]))
    if want <= 0:
        return None
    land = sig + c.latency(BASE, d["mint"], "buy")
    j = max(int(np.searchsorted(t, land, side="right")) - 1, 0)
    got = C.pool_buy(stake, int(d["x"][j]), int(d["y"][j]), int(d["fee"][j]))
    base = {"mig_ms": int(d["signal_ms"]), "mint": d["mint"], "signal_ms": int(sig), "day": day_of(d["signal_ms"]),
            "i": -1}
    if got <= 0 or got < want / (1 + C.SLIP_TOL):
        return {**base, "ret": -tx_l / (STAKE_SOL * C.LAMPORTS), "pnl_sol": -tx_l / C.LAMPORTS, "why": "failed buy",
                "exit_ms": land, "legs": 0, "failed": True, "hold_s": None, "best_l": None, "pnl_l": -tx_l,
                "gapped": False}
    pa = FX.Path_({**d, "land_ms": land, "j_land": j}, tokens=got, cost_l=stake)
    r = FX.simulate(pa, FX.lat_fn(c, d["mint"]), tx_l)
    s1 = land + FX.TIME_S * 1000 + 60_000
    return {**base, "ret": r["pnl_l"] / (STAKE_SOL * C.LAMPORTS), "pnl_sol": r["pnl_l"] / C.LAMPORTS, "why": r["why"],
            "exit_ms": r["exit_ms"], "legs": r["legs"], "failed": False, "hold_s": (r["exit_ms"] - land) / 1000,
            "best_l": FX.best_gain(pa, tx_l), "pnl_l": r["pnl_l"],
            "gapped": bool(any(g0 < s1 and sig < g1 for g0, g1 in gaps))}


# ---------------------------------------------------------------- F4: the regime

def regime(rows: list[dict], mig_ms: list[float], n_list=(F4_TEST_N,) + F4_N) -> dict:
    """Per entry (by key): the stop rate of the last n X0 entries closed before its signal (nan under n closed), the
    migrations of the last hour, and whether the last k closed entries were all losses."""
    done = sorted((x["exit_ms"], x["why"] == "stop", x["ret"] <= 0) for x in rows)
    ends = [e[0] for e in done]
    stop_cum = np.concatenate([[0], np.cumsum([e[1] for e in done])])
    loss = [e[2] for e in done]
    mig = sorted(mig_ms)
    out = {}
    for x in rows:
        t = x["signal_ms"]
        m = bisect.bisect_left(ends, t)
        f = {f"stop_rate_{n}": float((stop_cum[m] - stop_cum[m - n]) / n) if m >= n else math.nan for n in n_list}
        f["mig_1h"] = float(bisect.bisect_right(mig, t) - bisect.bisect_right(mig, t - F4_MIG_MS))
        for k in F4_K:
            f[f"lost_{k}"] = bool(m >= k and all(loss[m - k:m]))
        out[key(x)] = f
    return out


def runs_test(wins: np.ndarray) -> dict:
    """Wald-Wolfowitz: fewer runs than chance means clustering (one-sided p)."""
    from scipy.stats import norm
    w = np.asarray(wins, dtype=bool)
    n1, n2 = int(w.sum()), int((~w).sum())
    n = n1 + n2
    if n1 == 0 or n2 == 0 or n < 3:
        return {"n": n, "runs": None, "expected": None, "z": None, "p": None}
    runs = 1 + int((w[1:] != w[:-1]).sum())
    mu = 2 * n1 * n2 / n + 1
    var = 2 * n1 * n2 * (2 * n1 * n2 - n) / (n * n * (n - 1))
    z = (runs - mu) / math.sqrt(var) if var > 0 else 0.0
    return {"n": n, "runs": runs, "expected": mu, "z": z, "p": float(norm.cdf(z))}


def cluster_test(rows: list[dict], reg: dict) -> dict:
    """F4's gate on rows (one window, signal order): the runs test and the Spearman correlation with the stop rate of
    the last 20 closed entries; the mean after k losses and the correlation with the migration rate reported."""
    from scipy.stats import spearmanr
    rows = sorted(rows, key=lambda x: (x["signal_ms"], x["mint"]))
    r = np.array([x["ret"] for x in rows])
    out = {"n": len(rows), "runs": runs_test(r > 0)}
    for name, col in (("stop_rate", f"stop_rate_{F4_TEST_N}"), ("mig_rate", "mig_1h")):
        v = np.array([reg[key(x)][col] for x in rows])
        ok = np.isfinite(v)
        if ok.sum() >= 10 and np.ptp(v[ok]) > 0:
            rho, p = spearmanr(r[ok], v[ok])
            out[name] = {"n": int(ok.sum()), "rho": float(rho), "p": float(p)}
        else:
            out[name] = {"n": int(ok.sum()), "rho": None, "p": None}
    out["after_losses"] = {}
    for k in F4_K:
        m = np.array([reg[key(x)][f"lost_{k}"] for x in rows], dtype=bool)
        out["after_losses"][k] = {"n": int(m.sum()), "mean": float(r[m].mean()) if m.any() else None,
                                  "rest": float(r[~m].mean()) if (~m).any() else None}
    ru, sr = out["runs"], out["stop_rate"]
    out["clusters"] = bool((ru["p"] is not None and ru["p"] < F4_P)
                           or (sr["rho"] is not None and sr["rho"] < 0 and sr["p"] < F4_P))
    return out


# ---------------------------------------------------------------- the filters and the verdict

def _num(f: dict, k: str) -> float:
    v = f.get(k)
    return float(v) if v is not None else math.nan


def keeps(var: str, theta, f: dict) -> bool:
    """Whether filter var with its fitted theta keeps a signal with features f (a missing feature never skips)."""
    if var == "F1":
        idle, share = theta
        return not ((idle is not None and _num(f, "idle_s") >= idle)
                    or (share is not None and _num(f, "done_share") >= share))
    if var == "F2":
        return not _num(f, "link_drop") > F2_DROP
    if var == "F3":
        return not _num(f, "wash_n") >= theta
    if var == "F4":
        n, lv = theta
        return not _num(f, f"stop_rate_{n}") > lv
    raise ValueError(var)


def mean_band(kept: list[dict], base: list[dict], draws: int = BOOT, seed: int = SEED) -> tuple[float, float]:
    """90 % band of mean(kept) - mean(base), whole UTC days resampled (both on the same days); n/a under MIN_DAYS."""
    u = sorted({x["day"] for x in base})
    if len(u) < MIN_DAYS:
        return math.nan, math.nan
    ix = {d: i for i, d in enumerate(u)}
    sk, nk, s0, n0 = (np.zeros(len(u)) for _ in range(4))
    for x in kept:
        if x["day"] in ix:
            sk[ix[x["day"]]] += x["ret"]
            nk[ix[x["day"]]] += 1
    for x in base:
        s0[ix[x["day"]]] += x["ret"]
        n0[ix[x["day"]]] += 1
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(u), size=(draws, len(u)))
    with np.errstate(invalid="ignore", divide="ignore"):
        m = sk[idx].sum(axis=1) / nk[idx].sum(axis=1) - s0[idx].sum(axis=1) / n0[idx].sum(axis=1)
    m = m[np.isfinite(m)]
    if not len(m):
        return math.nan, math.nan
    return float(np.quantile(m, 0.05)), float(np.quantile(m, 0.95))


def judge(kept: list[dict], base: list[dict]) -> dict:
    """The registered rule: a higher mean per entry over what it keeps than X0's over all, the day-block band of
    the difference above 0, at least KEEP_MIN of X0's entries kept."""
    if not base:
        return {"n": len(kept), "share": None, "diff": None, "band": (math.nan, math.nan), "passes": False}
    r0 = np.array([x["ret"] for x in base])
    rk = np.array([x["ret"] for x in kept])
    kk = {key(x) for x in kept}
    skipped = [x["ret"] for x in base if key(x) not in kk]
    lo, hi = mean_band(kept, base)
    out = {"n": len(kept), "share": len(kept) / len(base), "diff": float(rk.mean() - r0.mean()) if len(rk) else None,
           "band": (lo, hi), "pnl_diff": float(sum(x["pnl_sol"] for x in kept) - sum(x["pnl_sol"] for x in base)),
           "skipped": len(skipped), "skipped_mean": float(np.mean(skipped)) if skipped else None}
    out["higher"] = bool(len(rk) and rk.mean() > r0.mean())
    out["band_above"] = bool(math.isfinite(lo) and lo > 0)
    out["kept_enough"] = out["share"] >= KEEP_MIN
    out["passes"] = out["higher"] and out["band_above"] and out["kept_enough"]
    return out


def fit(grid, rows_for, base_in: list[dict]) -> tuple:
    """The grid value with the highest in-sample mean per entry among those keeping at least KEEP_MIN of the
    in-sample entries (ties: the earlier); None without one. rows_for(theta) -> the kept in-sample rows."""
    best, out = None, []
    for g in grid:
        k = rows_for(g)
        share = len(k) / len(base_in) if base_in else 0.0
        mu = float(np.mean([x["ret"] for x in k])) if k else None
        out.append((g, mu, share))
        if mu is not None and share >= KEEP_MIN and (best is None or mu > best[1]):
            best = (g, mu)
    return (best[0] if best else None), out


def split(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    return [x for x in rows if x["day"] < OOS_FROM], [x for x in rows if x["day"] >= OOS_FROM]


def summary(kept: list[dict], base: list[dict], tx_l: int) -> dict:
    s = FX.stats(kept)
    s["judge"] = judge(kept, base)
    s["judge_no_gap"] = judge([x for x in kept if not x["gapped"]], [x for x in base if not x["gapped"]])
    srt = sorted(kept, key=lambda x: (x["signal_ms"], x["mint"]))
    s["books"] = {k: FX.book(srt, lim, tx_l) for k, lim in SIZINGS.items()}
    return s


def evaluate(res: dict, log=print) -> dict:
    c = costs()
    tx_l = res["tx_l"]
    x0 = x0_rows(res, c)
    feat = {(int(d["signal_ms"]), d["mint"]): d["feat"] for d in res["recs"]}
    reg = regime(x0, res.get("mig_ms", []))
    fx = {key(x): {**feat.get(key(x), {}), **reg[key(x)]} for x in x0}
    x0_in, x0_oos = split(x0)
    out = {"entries": len(x0), "in_sample": len(x0_in), "oos": len(x0_oos), "tx_l": tx_l,
           "failed": sum(x["failed"] for x in x0), "recs": len(res["recs"]), "filters": {}, "f5": {}}
    out["x0"] = {"oos": summary(x0_oos, x0_oos, tx_l), "in_sample": FX.stats(x0_in)}
    # the features: on how many signals each could be read
    fs = list(fx.values())
    out["coverage"] = {
        "curve_seen": sum(bool(f.get("curve_seen")) for f in fs), "idle_known": sum(_num(f, "idle_s") >= 0 for f in fs),
        "idle_gap": sum(bool(f.get("idle_gap")) for f in fs),
        "early_groups": sum((f.get("link_n") or 0) >= 2 for f in fs),
        "snip_known": sum(bool(f.get("snip_known")) for f in fs), "n": len(fs)}
    out["quantiles"] = {}
    for k in ("idle_s", "done_share", "wash_n", "link_drop", "link_h"):
        v = np.array([f.get(k) for f in fs if f.get(k) is not None], dtype=float)
        v = v[np.isfinite(v)]
        out["quantiles"][k] = np.quantile(v, [0.1, 0.25, 0.5, 0.75, 0.9]).tolist() if len(v) else None
    # F4's gate first
    out["f4_test"] = {"in_sample": cluster_test(x0_in, reg), "oos": cluster_test(x0_oos, reg)}
    clusters = out["f4_test"]["in_sample"]["clusters"]
    grids = {"F1": F1_GRID, "F2": (None,), "F3": F3_K, "F4": F4_GRID}
    for var in FILTERS:
        if var == "F4" and not clusters:
            out["filters"][var] = {"ran": False, "why": "the outcomes do not cluster in sample"}
            continue

        def rows_for(g, rows=x0_in, var=var):
            return [x for x in rows if keeps(var, g, fx[key(x)])]
        theta, grid = fit(grids[var], rows_for, x0_in)
        if var == "F2":
            theta = None
        f = {"ran": True, "theta": theta, "grid": grid}
        if theta is None and var != "F2":
            f.update(fitted=False, oos=None, passes=False)
        else:
            k_oos = rows_for(theta, x0_oos)
            f["oos"] = summary(k_oos, x0_oos, tx_l)
            f["in"] = FX.stats(rows_for(theta))
            f["passes"] = f["oos"]["judge"]["passes"]
            f["fitted"] = True
        out["filters"][var] = f
        log(f"entry_e2: {var} done")
    # F5: the thresholds from the in-sample shares at the signal, then every cell
    recs = res["recs"]
    s_in = np.array([float(d["snip"][0]) for d in recs
                     if day_of(d["signal_ms"]) < OOS_FROM and d["feat"].get("snip_known")])
    thr = {q: float(np.percentile(s_in, q)) for q in F5_Q} if len(s_in) else {q: math.nan for q in F5_Q}
    out["f5_thresholds"] = thr
    cells = {}
    for dl in F5_D:
        for q in list(F5_Q) + ["all"]:
            name = f"F5_d{dl}_{'q' + str(q) if q != 'all' else 'all'}"
            th = None if q == "all" else thr[q]
            rows = []
            for d in recs:
                r = late_entry(d, dl * 1000.0, th, c, tx_l, res.get("gaps", ()))
                if r is not None:
                    rows.append(r)
            cells[name] = rows
    base_in = x0_in
    fit_rows = {n: split(cells[n])[0] for n in F5_CELLS}
    pick, grid = fit(F5_CELLS, lambda n: fit_rows[n], base_in)
    out["f5"] = {"pick": pick, "grid": grid, "cells": {}}
    for n, rows in cells.items():
        r_in, r_oos = split(rows)
        out["f5"]["cells"][n] = {"oos": summary(r_oos, x0_oos, tx_l), "in": FX.stats(r_in),
                                 "in_share": len(r_in) / len(x0_in) if x0_in else None}
    out["f5"]["passes"] = bool(pick and out["f5"]["cells"][pick]["oos"]["judge"]["passes"])
    # the d 0 cell without a condition against X0: the late-entry code's check (same entries, same draws)
    a = {key(x): x for x in cells["F5_d0_all"]}
    same = [abs(a[key(x)]["ret"] - x["ret"]) < 0.01 for x in x0 if key(x) in a]
    out["f5"]["x0_check"] = {"n": len(same), "match": float(np.mean(same)) if same else None, "x0": len(x0)}
    ok = [v for v in FILTERS if out["filters"][v].get("passes")]
    if out["f5"]["passes"]:
        ok.append(pick)
    means = {v: (out["filters"][v]["oos"] if v in FILTERS else out["f5"]["cells"][v]["oos"])["mean"] for v in ok}
    out["pick"] = max(ok, key=lambda v: means[v]) if ok else None
    return out


# ---------------------------------------------------------------- report

pct = RL.pct


def _b(b) -> str:
    return f"{pct(b[0])} to {pct(b[1])}"


def _theta(var: str, th) -> str:
    if var == "F1" and th is not None:
        i, s = th
        return " or ".join(([f"idle {i:g} s"] if i is not None else []) + ([f"buy {s:g}"] if s is not None else []))
    if var == "F4" and th is not None:
        return f"last {th[0]}, above {th[1]:g}"
    if var == "F2":
        return f"drop above {F2_DROP:g}"
    return "" if th is None else f"{th:g}"


def _row(name: str, fitted: str, s: dict) -> str:
    j = s["judge"]
    bl, bw = s["books"]["live"], s["books"]["wide"]
    st = s.get("stops") or {}
    return (f"| {name} | {fitted} | {s['n']} | {(j['share'] or 0) * 100:.0f} % | {pct(s.get('mean'))} | "
            f"{pct(s.get('median'))} | {s.get('win', 0) * 100:.0f} % | {s.get('pnl_sol', 0):+.3f} | {st.get('n', 0)} | "
            f"{pct(j.get('skipped_mean'))} | {pct(j['diff'])} | {_b(j['band'])} | {'yes' if j['passes'] else 'no'} | "
            f"{bl['n']}, {pct(bl['mean'])}, {bl['pnl_sol']:+.3f} | {bw['n']}, {pct(bw['mean'])}, {bw['pnl_sol']:+.3f} |")


HEAD = ["| filter | fitted | kept | share | mean | median | win | P&L SOL | stops | X0 on the skipped | vs X0 | band (days) | "
        "passes | live book: n, mean, P&L | wide book: n, mean, P&L |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]


def report_md(res: dict, ev: dict) -> str:
    def utc(x):
        return f"{datetime.fromtimestamp(x / 1000, timezone.utc):%Y-%m-%d %H:%M} UTC"
    md = ["# E2: entry filters for P_pool0 (entry_e2)", "",
          f"Record {res['days'][0]} to {utc(res['span'][1])}, signals to {utc(res['entry_until_ms'])}; out of sample "
          f"from {OOS_FROM}. {STAKE_SOL} SOL, every P_pool0 signal entered, paired by migration; {ev['entries']} "
          f"entries ({ev['failed']} failed buys), {ev['oos']} out of sample, {ev['tx_l']:,} lamports a transaction.",
          "", "Coverage: " + ", ".join(f"{k} {v}" for k, v in ev["coverage"].items()),
          "", "Feature quantiles (10/25/50/75/90 %): " + "; ".join(
              f"{k} " + ", ".join(f"{q:.3g}" for q in v) for k, v in ev["quantiles"].items() if v)]
    def num(v, f):
        return format(v, f) if v is not None else "n/a"
    for w in ("in_sample", "oos"):
        x = ev["f4_test"][w]
        ru, sr, mr = x["runs"], x["stop_rate"], x["mig_rate"]
        md += ["", f"F4 test ({w}, {x['n']} entries): runs {num(ru['runs'], 'd')} against {num(ru['expected'], '.1f')} "
               f"expected, z {num(ru['z'], '+.2f')}, p {num(ru['p'], '.3f')}; stop rate of the last {F4_TEST_N} rho "
               f"{num(sr['rho'], '+.3f')} (p {num(sr['p'], '.3f')}, {sr['n']}); migrations of the last hour rho "
               f"{num(mr['rho'], '+.3f')} (p {num(mr['p'], '.3f')}); after k losses: "
               + "; ".join(f"k {k}: {pct(v['mean'])} on {v['n']} (rest {pct(v['rest'])})"
                           for k, v in x["after_losses"].items()) + f"; clusters: {'yes' if x['clusters'] else 'no'}"]
    md += ["", "## Out of sample", ""] + HEAD
    x0 = ev["x0"]["oos"]
    md.append(_row("X0 (P_pool0)", "", x0))
    for v in FILTERS:
        f = ev["filters"][v]
        if not f.get("ran"):
            md.append(f"| {v} | not run: {f['why']} |" + " |" * 13)
        elif not f.get("fitted"):
            md.append(f"| {v} | no cell keeps {KEEP_MIN:.0%} in sample |" + " |" * 13)
        else:
            md.append(_row(v, _theta(v, f["theta"]), f["oos"]))
    f5 = ev["f5"]
    md += ["", f"F5 thresholds (in-sample quantiles of the snipers' share at the signal): "
           + ", ".join(f"q{q} {v:.4f}" for q, v in ev["f5_thresholds"].items())
           + f"; pick in sample: {f5['pick'] or 'none'}; the d 0 cell without a condition matches X0 on "
           f"{(f5['x0_check']['match'] or 0) * 100:.1f} % of {f5['x0_check']['n']}.", ""] + HEAD
    for n, cell in f5["cells"].items():
        md.append(_row(n + (" (pick)" if n == f5["pick"] else ""), f"in {pct(cell['in'].get('mean'))}, "
                       f"{(cell['in_share'] or 0) * 100:.0f} % kept", cell["oos"]))
    ng = {v: ev["filters"][v]["oos"]["judge_no_gap"] for v in FILTERS
          if ev["filters"][v].get("fitted") and ev["filters"][v].get("oos")}
    if f5["pick"]:
        ng[f5["pick"]] = f5["cells"][f5["pick"]]["oos"]["judge_no_gap"]
    md += ["", "Without trades open across a gap: " + "; ".join(f"{v} {pct(j['diff'])} ({_b(j['band'])})"
                                                                for v, j in ng.items())]
    md += ["", "In-sample grids: " + "; ".join(
        f"{v} " + ", ".join(f"{_theta(v, g)}: {pct(mu)} ({sh * 100:.0f} %)" for g, mu, sh in ev["filters"][v]["grid"])
        for v in FILTERS if ev["filters"][v].get("ran"))]
    md += ["", f"Pick: {ev['pick'] or 'none passes'}."]
    return "\n".join(md) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--until-ms", type=int, default=UNTIL_MS)
    ap.add_argument("--out", default=None, help="directory for entry_e2.json and entry_e2.md (default: the reports)")
    ap.add_argument("--cache", default=None, help="the replay, kept and read again")
    ap.add_argument("--no-register", action="store_true")
    ap.add_argument("--register-only", action="store_true", help="the trials into R5's registry, nothing else")
    a = ap.parse_args(argv)
    from .. import metrics
    from .. import report as rep
    if not a.no_register:
        new = metrics.register(trials())                # before any number exists
        print(f"entry_e2: {len(new)} trials registered")
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
            print("entry_e2: nothing recorded")
            return 1
        if cache is not None:
            cache.write_bytes(pickle.dumps(res, protocol=pickle.HIGHEST_PROTOCOL))
    ev = evaluate(res)
    md = report_md(res, ev)
    keep = {k: v for k, v in res.items() if k not in ("recs", "failed", "pipe_closed", "mig_ms")}
    (out / "entry_e2.json").write_text(json.dumps(FX._clean(keep | {"eval": ev}), indent=1, default=str),
                                       encoding="utf-8")
    (out / "entry_e2.md").write_text(md, encoding="utf-8")
    print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
