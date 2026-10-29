"""X14 r2: an order-flow exit for the live P_pool0, on the whole record at the latency the live executor measures
since 2026-10-29 13:26 UTC. PAPER ONLY.

    python -m lab.pumpfun_rt.flowexit                   replay, measure, run the exits, write flowexit.{json,md}
    python -m lab.pumpfun_rt.flowexit --out DIR         the same, written into DIR
    python -m lab.pumpfun_rt.flowexit --cache FILE      the replay's paths kept in FILE (read again if it exists)

Pre-registered in results/pumpfun_flow_exit_x14r2_prereg.md. Every P_pool0 signal of the record is entered at
0.05 SOL with no book limit (EveryEntry, this replay only), under two scenarios:

  N    today's latency: Y5's kernel density in log space of the live executor's P_pool0 fills from 2026-10-29
       13:26 UTC to the cutoff (LIVE_BUY_MS, LIVE_SELL_MS, clipped 0.2 to 60 s), the mean fee of its transactions
  O    Y8's registered latency (exits8.SENDER_BUY_MS, SENDER_SELL_MS), a diagnostic only

For every filled entry the pool's path (every trade from the signal to the landing + PATH_MS, the state after it,
side, size, signer as a small number) and step rows (X14's step features and the flow features below, at the
landing and at every trade 1 s after the step before, for 300 s). The seven exits are simulated on the paths, the
same sale latency draw per entry and leg in every exit: paired by entry. Before them: the one-transaction stops,
the live stops split, the buyback's end. Nothing here holds a wallet, reads a key, signs or sends anything; the
live executor's files are only read, never its key or its wallet.
"""

from __future__ import annotations

import argparse
import dataclasses
import heapq
import json
import math
import pickle
import sys
import time
from array import array
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from . import curve as C
from . import early as E
from . import exitlab as XL
from . import exits8 as X8
from . import pipeline as P
from . import reallat as RL

# ---------------------------------------------------------------- registered (results/pumpfun_flow_exit_x14r2_prereg.md)

PREREG = "results/pumpfun_flow_exit_x14r2_prereg.md"
BASE = "P_pool0"


def _utc(*a) -> int:
    return int(datetime(*a, tzinfo=timezone.utc).timestamp() * 1000)


SINCE_MS = _utc(2026, 10, 29, 13, 26)                  # the 20 EUR live test of P_pool0 at 0.05 SOL
UNTIL_MS = _utc(2026, 10, 29, 18, 0)                   # the cutoff
TAIL_MS = 10 * 60_000                                   # signals stop this long before it: every position closes
OOS_FROM = "2026-10-24"                                 # in sample: the UTC days before
# The executor's P_pool0 fills, signal to landing (ms), 13:26 UTC to the cutoff, as logged.
LIVE_BUY_MS = (1036, 2177, 1065, 1395, 1778, 1205, 588, 3672, 1127, 659, 1721, 1375, 1666, 2928, 1353, 1586, 722,
               2851, 1353, 2966, 4420, 754, 823, 1088, 1565, 1221, 2669, 1219, 3717, 5125, 1341, 3278, 1992)
LIVE_SELL_MS = (600, 1553, 411, 458, 788, -17, 130, 648, 635, 607, -812, 3449, 546, 407, 7825, 1005, 416, 377, 906,
                546, 644, 407, 1505, 579, 429, -477, 2030, 645, 761, 538, 5599, 590)
LIVE_FEE_L = 108_837                                    # the mean of the window's 64 transaction fees (lamports)
CLIP_N = (200.0, 60_000.0)                              # a sale cannot land in the slot it was sent in
STAKE_SOL = 0.05
TP, SL, TIME_S = 0.30, 0.20, 300.0                      # P_pool0's exits
PATH_MS = 480_000                                       # the path after the landing (the buyback's +120 s too)
STEP_MS = 300_000
STEP_EVERY_MS = 1_000
DUMP_DROP, DUMP_S, UP_S = 0.25, 10, 30                  # X14's labels, here after the sale latency L
HZ_K = (0.5, 1.0, 2.0, 4.0)
F1_WIN_MS = 3_000
F1_THETA = (0.02, 0.04, 0.06, 0.08, 0.12)
F2_THETA = (0.05, 0.10, 0.15, 0.20)
DAR_Q = (0.50, 0.75, 0.90, 0.95)
T_GRID = (180.0, 240.0, 270.0)
BB_GAP_MS, BB_FALL, BB_MIN_BUYS, BB_FIRST_MS = 45_000, 0.10, 3, 120_000
EARLY_SLOT_MS = 30_000                                  # a bundle: two or more buyers in one slot of the first 30 s
HK_TAU_S = (5.0, 30.0)
BOOT, SEED = 5000, 11
MIN_DAYS = 5
ONE_TX_MAJORITY = 2 / 3
SIZINGS = {"live": P.Limits(0.05, 1, 0.6, 0.12), "wide": P.Limits(0.1, 4, 0.6, 1.0)}
VARIANTS = ("X0", "HZ", "F1", "F2", "DAR", "T", "BB")
GRIDS = {"HZ": HZ_K, "F1": F1_THETA, "F2": F2_THETA, "DAR": DAR_Q, "T": T_GRID}
SCENARIOS = ("N", "O")
JUDGED = "N"
SCENARIO_LABEL = {"N": "(N) today's latency, since 2026-10-29 13:26 UTC", "O": "(O) Y8's latency (diagnostic)"}
NEW_FEATURES = ["sl_move", "sl_net", "sl_sells", "sl_big", "dar", "dar_h", "hk5", "hk30", "bb_seen", "bb_buys",
                "bb_since_s", "bb_on"]
FEATURES = list(E.STEP_FEATURES) + NEW_FEATURES
MEASURES = ("one_tx", "live_stop_split", "buyback_end", "old_latency")


def trials() -> list[dict]:
    return [{"id": f"pumpfun:flow_x14r2:{k}", "family": "pumpfun", "n": 1, "sharpe": None, "source": PREREG}
            for k in VARIANTS + MEASURES]


def _clip(xs, lo: float, hi: float) -> tuple:
    return tuple(min(hi, max(lo, float(x))) for x in xs)


def scenarios() -> dict[str, RL.FillCosts]:
    nb, ns = _clip(LIVE_BUY_MS, *CLIP_N), _clip(LIVE_SELL_MS, *CLIP_N)
    lo, hi = RL.CLIP_MS
    return {
        "N": RL.FillCosts(lat_median_ms=float(np.median(nb)), lat_lo_ms=CLIP_N[0], lat_hi_ms=CLIP_N[1],
                          priority_sol=RL.priority_for(LIVE_FEE_L / C.LAMPORTS), buy=RL.LogKDE(nb, *CLIP_N),
                          sell=RL.LogKDE(ns, *CLIP_N)),
        "O": RL.FillCosts(lat_median_ms=float(np.median(X8.SENDER_BUY_MS)), lat_lo_ms=lo, lat_hi_ms=hi,
                          priority_sol=RL.priority_for(X8.TX_FEE_SOL), buy=RL.LogKDE(X8.SENDER_BUY_MS),
                          sell=RL.LogKDE(X8.SENDER_SELL_MS)),
    }


def lag_ms(k: str) -> float:
    """L: the median of the scenario's clipped sale points, the time a label skips (owner note 2)."""
    return float(np.median(_clip(LIVE_SELL_MS, *CLIP_N) if k == "N" else X8.SENDER_SELL_MS))


def day_of(ms) -> str:
    return datetime.fromtimestamp(float(ms) / 1000, timezone.utc).strftime("%Y-%m-%d")


# ---------------------------------------------------------------- the replay

class EveryEntry(P.Risk):
    """This study's full replay only: every P_pool0 signal is entered, no book limit; the books of section 6 apply
    the limits afterwards (book()). Never used by a paper book or the live executor."""

    def why_not(self, t: float, cost_l: int) -> str | None:
        return None

    def booked(self, t: float, pnl_l: int) -> None:
        return None


def early_group(eng, tok) -> set:
    """The grouped early wallets: the devs, the snipers (bought within 2 s of the creation) and every group of two
    or more early buyers whose first buy shares one slot time in the first 30 s on the curve (a bundle)."""
    out = set(tok.devs)
    st = eng.early.st.get(tok.mint)
    if st is not None:
        out |= set(st.snipers)
    by_t = defaultdict(list)
    for w, t0 in (getattr(tok.early, "wallets", None) or {}).items():
        if t0 - tok.t0 <= EARLY_SLOT_MS:
            by_t[t0].append(w)
    for ws in by_t.values():
        if len(ws) >= 2:
            out.update(ws)
    return out


POINT_D = ("t", "x", "y", "dq", "amt", "bblast")        # float64 columns of a path (times need them)
POINT_F = ("fee", "buy", "uid", "dar", "hk5", "hk30", "bbn")
POINT_I = ("slot",)


class Rec:
    """One entry's recording, from the signal to the landing + PATH_MS."""

    def __init__(self, pid: int, tok, t: float, group: set, fee_floor: int):
        self.pid, self.mint, self.symbol = pid, tok.mint, tok.symbol
        self.signal_ms, self.mig_ms = int(t), int(tok.migrate_t or t)
        self.sig_pb, self.sig_pq = int(tok.pb), int(tok.pq)
        self.group, self.floor = group, fee_floor
        self.cols = {c: array("d") for c in POINT_D} | {c: array("f") for c in POINT_F} | {"slot": array("q")}
        self.uid: dict[str, int] = {}
        self.hk = [0.0, 0.0]
        self.hk_t = float(t)
        self.cand: dict[str, list] = {}                 # signer -> [buys, sells or other pools, first, buy times]
        self.buyer = None
        self.bb_buys: list[float] = []
        self.land_ms = None
        self.tokens = self.cost_l = self.tx_l = 0
        self.j_land = 0
        self.end_ms = None
        self.peak_v, self.peak_ms = 0.0, 0.0
        self.last_step = -math.inf
        self.step_pt = array("q")
        self.X = array("f")
        self.sl = {}
        self.add(t, tok, None, "", 0, 0.0, True)        # point 0: the state at the signal

    def _hk(self, t: float) -> None:
        dt = (t - self.hk_t) / 1000
        if dt > 0:
            self.hk = [h * math.exp(-dt / tau) for h, tau in zip(self.hk, HK_TAU_S)]
            self.hk_t = t

    def add(self, t: float, tok, buy, user: str, amt: int, dq: float, fresh: bool) -> None:
        c = self.cols
        self._hk(t)
        if buy is False and user in self.group and tok.pb > amt:
            mark = amt / (tok.pb - amt)                 # tokens sold over the pool's tokens before the sale
            self.hk = [h + mark for h in self.hk]
        if self.buyer is None and user and buy is not None:
            k = self.cand.get(user)
            if k is None:
                k = self.cand[user] = [0, 0, t, []]
            if buy:
                k[0] += 1
                k[3].append(t)
            if not buy or not fresh:
                k[1] += 1
            if k[1] == 0 and k[0] >= BB_MIN_BUYS and k[2] - self.mig_ms <= BB_FIRST_MS:
                self.buyer = user
                self.bb_buys = list(k[3])
                self.cand = {}
        elif user and user == self.buyer and buy:
            self.bb_buys.append(t)
        x = float(tok.pb)
        h = float(sum(tok.hold.get(w, 0) for w in self.group))
        c["t"].append(float(t))
        c["x"].append(x)
        c["y"].append(float(tok.pq))
        c["dq"].append(float(dq))
        c["amt"].append(float(amt))
        c["fee"].append(float(max(tok.amm_fee_bps, self.floor)))
        c["buy"].append(-1.0 if buy is None else float(buy))
        c["uid"].append(float(-1 if not user else self.uid.setdefault(user, len(self.uid))))
        c["dar"].append(1 - (x / (x + h)) ** 2 if x > 0 else math.nan)
        c["hk5"].append(self.hk[0])
        c["hk30"].append(self.hk[1])
        c["bbn"].append(float(len(self.bb_buys)) if self.buyer is not None else 0.0)
        c["bblast"].append(self.bb_buys[-1] if self.buyer is not None and self.bb_buys else math.nan)
        c["slot"].append(int(tok.amm_slot or 0))

    def landed(self, at: float, tokens: int, cost_l: int, fee_l: int) -> None:
        self.land_ms, self.tokens, self.cost_l, self.tx_l = int(at), int(tokens), int(cost_l), int(fee_l)
        self.end_ms = int(at) + PATH_MS
        c = self.cols
        self.j_land = len(c["t"]) - 1
        t, x, y = c["t"], c["x"], c["y"]
        p0 = self.sig_pq / self.sig_pb if self.sig_pb else math.nan
        p1 = y[-1] / x[-1] if x[-1] else math.nan
        sells = [c["amt"][i] for i in range(1, len(t)) if c["buy"][i] == 0.0]
        self.sl = {"sl_move": math.log(p1 / p0) if p0 > 0 and p1 > 0 else math.nan,
                   "sl_net": sum(c["dq"][1:]) / self.sig_pq if self.sig_pq else math.nan,
                   "sl_sells": float(len(sells)), "sl_big": max(sells, default=0.0) / self.sig_pb if self.sig_pb else 0.0}

    def step(self, eng, tok, t: float, v: float) -> None:
        if v > self.peak_v:
            self.peak_v, self.peak_ms = v, t
        if t - self.last_step < STEP_EVERY_MS or t > self.land_ms + STEP_MS:
            return
        self.last_step = t
        cost = self.cost_l + self.tx_l
        f = eng.early.step_features(tok, t, v, cost, self.peak_v, self.land_ms, self.peak_ms)
        c = self.cols
        last = c["bblast"][-1]
        f.update(self.sl, dar=c["dar"][-1], dar_h=sum(tok.hold.get(w, 0) for w in self.group) / E.SUPPLY,
                 hk5=self.hk[0], hk30=self.hk[1], bb_seen=float(self.buyer is not None), bb_buys=c["bbn"][-1],
                 bb_since_s=(t - last) / 1000 if last == last else math.nan,
                 bb_on=float(last == last and t - last <= BB_GAP_MS))
        self.step_pt.append(len(c["t"]) - 1)
        self.X.extend(float(f.get(k, math.nan)) for k in FEATURES)

    def pack(self, complete: bool) -> dict:
        c = self.cols
        out = {k: np.frombuffer(c[k], dtype=np.float64).copy() for k in POINT_D}
        out |= {k: np.frombuffer(c[k], dtype=np.float32).copy() for k in POINT_F}
        out["slot"] = np.frombuffer(c["slot"], dtype=np.int64).copy()
        out.update(pid=self.pid, mint=self.mint, symbol=self.symbol, signal_ms=self.signal_ms, mig_ms=self.mig_ms,
                   land_ms=self.land_ms, tokens=self.tokens, cost_l=self.cost_l, tx_l=self.tx_l, j_land=self.j_land,
                   sig_pb=self.sig_pb, sig_pq=self.sig_pq, complete=complete, bb_buys=list(self.bb_buys),
                   step_pt=np.frombuffer(self.step_pt, dtype=np.int64).copy(),
                   X=np.frombuffer(self.X, dtype=np.float32).reshape(-1, len(FEATURES)).copy())
        return out


class FlowPipe(P.Pipeline):
    """P_pool0 at one scenario, every signal entered (EveryEntry), each entry recorded as a Rec; the pipeline's
    own P_pool0 exits still run (pipe.closed, a check of the path simulator)."""

    def __init__(self, eng, strategy: P.Strategy, users: dict):
        super().__init__(eng, [strategy], P.PaperExecutor(), limits=P.Limits(STAKE_SOL, 1, 0.6, 0.12),
                         name=strategy.name)
        self.risk = {k: EveryEntry(r.limits) for k, r in self.risk.items()}
        self.users = users                              # pool signer -> the one pool it traded, "" for more
        self.recs: dict[int, Rec] = {}
        self.rec_by_mint: dict[str, list[int]] = {}
        self.paths: list[dict] = []
        self.floor = eng.cost_of(strategy.name).fee_bps_floor

    def signal(self, s, tok, t: float) -> None:
        before = self.eng.next_pid
        super().signal(s, tok, t)
        if self.eng.next_pid > before and before in self.pos:
            self.recs[before] = Rec(before, tok, t, early_group(self.eng, tok), self.floor)
            self.rec_by_mint.setdefault(tok.mint, []).append(before)

    def bought(self, pid: int, at: float, tokens: int, cost_l: int, fee_l: int) -> None:
        r = self.recs.get(pid)
        if r is not None:
            r.landed(at, tokens, cost_l, fee_l)
            tok = self.eng.tokens.get(r.mint)
            if tok is not None:
                v = self.eng.sale_value(tok, r.tokens, self.eng.cost_of(self.pos[pid]["rule"]))
                r.step(self.eng, tok, at, float(v or 0))
            self.eng.push(r.end_ms, "pipe", (self, "_rec_end", pid))
        super().bought(pid, at, tokens, cost_l, fee_l)

    def buy_failed(self, pid: int, at: float, why: str, fee_l: int) -> None:
        self._drop(pid)
        super().buy_failed(pid, at, why, fee_l)

    def _drop(self, pid: int) -> Rec | None:
        r = self.recs.pop(pid, None)
        if r is not None:
            ps = self.rec_by_mint.get(r.mint, [])
            if pid in ps:
                ps.remove(pid)
            if not ps:
                self.rec_by_mint.pop(r.mint, None)
        return r

    def _rec_end(self, at: float, pid: int) -> None:
        r = self._drop(pid)
        if r is not None:
            self.paths.append(r.pack(True))

    def on_trade(self, tok, t: float, buy: bool, user: str, tok_amt: int, venue: str) -> None:
        if venue == "pool":
            prev = self.users.get(user) if user else None
            if user and prev != "":
                self.users[user] = tok.mint if prev in (None, tok.mint) else ""
            pids = self.rec_by_mint.get(tok.mint)
            if pids:
                w = tok.amm_win
                dq = float(w[-1][1] - w[-1][2]) if w and w[-1][0] == int(t) else 0.0
                for pid in tuple(pids):
                    r = self.recs[pid]
                    r.add(t, tok, bool(buy), user or "", int(tok_amt or 0), dq, prev in (None, tok.mint))
                    if r.land_ms is not None and r.tokens:
                        v = C.pool_sell(r.tokens, tok.pb, tok.pq, max(tok.amm_fee_bps, self.floor))
                        r.step(self.eng, tok, t, float(v))
        super().on_trade(tok, t, buy, user, tok_amt, venue)

    def finish(self) -> None:
        for pid in list(self.recs):
            r = self._drop(pid)
            if r is not None and r.land_ms is not None:
                self.paths.append(r.pack(False))


def books() -> tuple[list[P.Strategy], dict]:
    sc = scenarios()
    s = P.BY_NAME[BASE]
    out, costs = [], {}
    for k in SCENARIOS:
        v = dataclasses.replace(s, name=f"{BASE}@{k}", p={**s.p, "base": BASE}, stake_sol=STAKE_SOL)
        out.append(v)
        costs[v.name] = sc[k]
    return out, costs


def run(root=None, until_ms: int = UNTIL_MS, log=print) -> dict:
    """The full replay of every P_pool0 signal at both scenarios, up to until_ms; signals stop TAIL_MS before."""
    from . import early as EA
    from . import sim, store
    from . import wallets as W
    from .study import span_of, warm_book
    days = [d for d in store.days(root) if d <= day_of(until_ms)]
    if not days:
        return {"empty": True}
    t_lo, t_hi = span_of(days[:1], root)[0], span_of(days[-1:], root)[1]    # one day each: all of them at once
    t_hi = min(t_hi, until_ms)                                                # does not fit in memory
    strats, costs = books()
    eng = sim.Engine([], book=warm_book([], root), decisions=False, rule_costs=costs, entry_until=t_hi - TAIL_MS,
                     wallets=W.warm([], root), snipers=EA.warm_snipers([], root))
    users: dict[str, str] = {}
    pipes = {s.name.split("@")[1]: eng.add_pipe(FlowPipe(eng, s, users)) for s in strats}
    t0 = time.time()
    sim.replay(days, eng, root, until_ms=t_hi,
               progress=lambda d, n: log(f"flowexit: {d} {n:,} rows, {time.time() - t0:.0f} s, "
                                         + ", ".join(f"{k} {len(p.paths) + len(p.recs)}" for k, p in pipes.items())))
    for p in pipes.values():
        p.finish()
    log(f"flowexit: replay in {time.time() - t0:.0f} s")
    return {"days": days, "span": (t_lo, t_hi), "until_ms": until_ms, "entry_until_ms": t_hi - TAIL_MS,
            "paths": {k: p.paths for k, p in pipes.items()},
            "failed": {k: [dict(f) for f in p.failed] for k, p in pipes.items()},
            "pipe_closed": {k: [{x: c.get(x) for x in ("pid", "mint", "exit_why", "ret", "exit_ms")} for c in p.closed]
                            for k, p in pipes.items()},
            "skipped": {f"{n}|{w}": c for (n, w), c in eng.skipped.items() if n.startswith(BASE + "@")},
            "gaps": [tuple(g) for g in eng.gaps], "tx_l": {k: c.tx_lamports() for k, c in costs.items()}}


# ---------------------------------------------------------------- a path and the exits

class Path_:
    """One entry's path as arrays: the net sale value of all its tokens at every point, the landing's index."""

    def __init__(self, d: dict, tokens: int | None = None, cost_l: int | None = None):
        self.d = d
        self.t, self.x, self.y = d["t"], d["x"], d["y"]
        self.tokens = float(tokens if tokens is not None else d["tokens"])
        self.cost = float(cost_l if cost_l is not None else d["cost_l"])
        self.land = float(d["land_ms"])
        self.jl = int(d["j_land"])
        with np.errstate(divide="ignore", invalid="ignore"):
            g = np.floor(self.y * self.tokens / (self.x + self.tokens))
            v = np.floor(g * (1 - d["fee"].astype(np.float64) / 10_000))
        self.v = np.where((self.x > 0) & (self.y > 0), v, np.nan)
        self.mult = self.v / self.cost if self.cost > 0 else self.v * np.nan

    def at(self, ms: float) -> int:
        return max(int(np.searchsorted(self.t, ms, side="right")) - 1, 0)

    def value_at(self, ms: float) -> float:
        v = self.v[self.at(ms)]
        return float(v) if np.isfinite(v) else 0.0


def _first(mask: np.ndarray, start: int) -> int | None:
    if mask is None or start >= len(mask):
        return None
    m = np.flatnonzero(mask[start:])
    return int(m[0]) + start if len(m) else None


def masks(pa: Path_, var: str, theta, hz: np.ndarray | None = None) -> np.ndarray | None:
    """The points at which the variant's own exit fires (None: no own exit)."""
    d, n, jl = pa.d, len(pa.t), pa.jl
    after = np.arange(n) >= jl
    if var == "HZ":
        return hz
    if theta is None and var in ("F1", "F2", "DAR"):
        return None                                     # nothing fitted (no in-sample entries): P_pool0's exits
    if var == "F1":
        t = pa.t
        out = np.where(after, -d["dq"], 0.0)            # sales take SOL out of the pool; trades since the landing
        cs = np.concatenate([[0.0], np.cumsum(out)])
        lo = np.searchsorted(t, t - F1_WIN_MS, side="right")
        win = cs[np.arange(n) + 1] - cs[lo]
        return after & (win > theta * pa.y[jl])
    if var == "F2":
        m = np.zeros(n, dtype=bool)
        p0 = d["sig_pq"] / d["sig_pb"] if d["sig_pb"] else math.nan
        p1 = pa.y[jl] / pa.x[jl] if pa.x[jl] else math.nan
        m[jl] = bool(p0 > 0 and p1 <= (1 - theta) * p0)
        return m
    if var == "DAR":
        return after & (np.nan_to_num(d["dar"].astype(np.float64), nan=0.0) >= theta)
    if var == "BB":
        last = d["bblast"].astype(np.float64)
        seen = d["bbn"] >= BB_MIN_BUYS
        mult = np.where(after & np.isfinite(pa.mult), pa.mult, -np.inf)
        high = np.maximum.accumulate(mult)
        on = seen & np.isfinite(last) & (pa.t - last <= BB_GAP_MS)
        stopped = seen & np.isfinite(last) & (pa.t - last > BB_GAP_MS)
        return after & (stopped | (on & np.isfinite(pa.mult) & (pa.mult <= (1 - BB_FALL) * high)))
    return None


def simulate(pa: Path_, lat, tx_l: int, own: np.ndarray | None = None, time_s: float = TIME_S,
             own_why: str = "flow", own_first: bool = False) -> dict:
    """P_pool0's exits (+30 % all, -20 % stop all, the time stop) plus one own exit (`own`, the points where it
    fires) on one path. A sale is signalled at a point (or the time stop) and lands lat(leg) later at the state
    then; a take that would land under TP_FLOOR of its expected proceeds fails, pays its fee, stays due. own_first:
    the own exit is checked before the stop (the hazard, as the pipeline), else after it (as press_exit)."""
    n = len(pa.t)
    fin = np.isfinite(pa.mult)
    stop = fin & (pa.mult <= 1 - SL)
    take = fin & (pa.mult >= 1 + TP)
    start, now, legs = pa.jl, pa.land, 0
    t_end = pa.land + time_s * 1000
    while True:
        order = [("stop", stop), ("take", take)]
        if own is not None:
            order.insert(0 if own_first else 1, (own_why, own))
        best = None
        for why, m in order:
            j = _first(m, start)
            if j is not None and (best is None or j < best[0]):
                best = (j, why)
        if best is None or max(float(pa.t[best[0]]), now) >= t_end:
            sig, why, j = max(t_end, now), "time", None
        else:
            j, why = best
            sig = max(float(pa.t[j]), now)
        land = sig + lat(legs)
        got = pa.value_at(land)
        legs += 1
        if why == "take" and got < P.TP_FLOOR * float(pa.v[j]):
            now = land                                      # the take failed: checked again at the landing's state
            start = max(pa.at(land), pa.jl)
            if now >= t_end:
                start = n
            continue
        pnl = got - pa.cost - (1 + legs) * tx_l
        return {"pnl_l": pnl, "why": why, "sig_ms": sig, "exit_ms": land, "legs": legs, "got_l": got, "j_sig": j}


def best_gain(pa: Path_, tx_l: int) -> float:
    m = (np.arange(len(pa.t)) >= pa.jl) & (pa.t <= pa.land + TIME_S * 1000) & np.isfinite(pa.v)
    return float(np.nanmax(pa.v[m])) - pa.cost - 2 * tx_l if m.any() else -pa.cost - 2 * tx_l


def lat_fn(costs, mint: str):
    """The pipeline's own sale draw: key (P_pool0, mint, sell) for the first leg, (..., leg) after."""
    return lambda leg: costs.latency(BASE, mint, "sell") if leg == 0 else costs.latency(BASE, mint, "sell", leg)


# ---------------------------------------------------------------- labels and the walk-forward models

def labels(pa: Path_, L: float) -> dict[str, np.ndarray]:
    """dump10 and up30 at each step, from the value at t + L (the sale's landing): a drop inside the latency is
    not a label (owner note 2); drop10 the log of the lowest value over the value at t + L."""
    pt = pa.d["step_pt"]
    v = pa.v - pa.d["tx_l"]
    n = len(pt)
    dump, drop, up = np.full(n, np.nan), np.full(n, np.nan), np.full(n, np.nan)
    for s in range(n):
        tl = float(pa.t[pt[s]]) + L
        i = pa.at(tl)
        v0 = v[i]
        if not np.isfinite(v0) or v0 <= 0:
            continue
        a = i + 1
        b10 = int(np.searchsorted(pa.t, tl + DUMP_S * 1000, side="right"))
        b30 = int(np.searchsorted(pa.t, tl + UP_S * 1000, side="right"))
        seg = v[a:b10]
        seg = seg[np.isfinite(seg)]
        lo = float(seg.min()) if len(seg) else float(v0)
        dump[s] = float(lo <= (1 - DUMP_DROP) * v0)
        drop[s] = math.log(max(lo, 1.0) / v0)
        seg = v[a:b30]
        seg = seg[np.isfinite(seg)]
        up[s] = math.log(max(float(seg.max()), v0) / v0) if len(seg) else 0.0
    return {"dump10": dump, "drop10": drop, "up30": up}


def step_table(paths: list[Path_], L: float) -> dict:
    """Every step of every path: its path, its time, its entry's day, the features and labels."""
    rows = {"path": [], "t": [], "day": [], "X": [], "dump10": [], "drop10": [], "up30": []}
    for i, pa in enumerate(paths):
        pt = pa.d["step_pt"]
        if not len(pt):
            continue
        lb = labels(pa, L)
        rows["path"].append(np.full(len(pt), i))
        rows["t"].append(pa.t[pt])
        rows["day"].append(np.full(len(pt), day_of(pa.d["signal_ms"]), dtype=object))
        rows["X"].append(pa.d["X"])
        for k in ("dump10", "drop10", "up30"):
            rows[k].append(lb[k])
    if not rows["path"]:
        return {"n": 0}
    out = {k: np.concatenate(v) for k, v in rows.items() if k != "X"}
    out["X"] = np.vstack(rows["X"]).astype(np.float64)
    out["n"] = len(out["t"])
    return out


def walk_forward(st: dict, paths: list[Path_], L: float, log=print) -> dict:
    """Per UTC day d (by the entry's signal), the dump and upside models fitted on the steps of the days before d
    whose label windows end before d starts; d's steps scored by them. The first day has none."""
    from . import exitpol as XP
    from . import model as M
    n = st.get("n", 0)
    pd_, pu = np.full(n, np.nan), np.full(n, np.nan)
    loss = {}
    out = {"days": {}}
    if not n:
        return {"pd": pd_, "pu": pu, "loss": loss, **out}
    days = sorted(set(st["day"].tolist()))
    land = np.array([paths[int(i)].land for i in st["path"]])
    for d in days[1:]:
        d0 = _utc(*map(int, d.split("-")))
        tr = (st["day"] < d) & (land + STEP_MS + L + UP_S * 1000 < d0) & np.isfinite(st["dump10"])
        te = st["day"] == d
        if tr.sum() < M.MIN_TRAIN:
            continue
        o = np.argsort(st["t"][tr], kind="stable")
        Xtr, ytr = st["X"][tr][o], st["dump10"][tr][o]
        clf = M.fit(Xtr, ytr, FEATURES)
        reg = XP.fit_reg(Xtr, st["up30"][tr][o], FEATURES)
        if clf.booster is None:
            continue
        pd_[te] = clf.predict(st["X"][te])
        pu[te] = reg.predict(st["X"][te])
        dd = st["drop10"][tr][o][ytr == 1]
        loss[d] = float(-np.mean(dd)) if len(dd) else 0.0
        y = st["dump10"][te]
        ok = np.isfinite(y)
        sc = M.scores(pd_[te][ok], y[ok], float(ytr.mean())) if ok.sum() else {}
        out["days"][d] = {"train": int(tr.sum()), "test": int(te.sum()), "loss": loss[d],
                          "auc": sc.get("auc"), "brier_skill": sc.get("brier_skill"), "rate": sc.get("rate")}
        log(f"flowexit: models for {d}: {int(tr.sum()):,} training steps, AUC {sc.get('auc', math.nan):.3f}")
    return {"pd": pd_, "pu": pu, "loss": loss, **out}


def hz_masks(st: dict, wf: dict, paths: list[Path_], k: float) -> list[np.ndarray | None]:
    """Per path, the points where HZ(k) sells: a step with predicted up30 under k x P(dump10) x |L_loss|."""
    out: list[np.ndarray | None] = [None] * len(paths)
    if not st.get("n"):
        return out
    loss = np.array([wf["loss"].get(d, math.nan) for d in st["day"]])
    fire = np.isfinite(wf["pd"]) & (wf["pu"] < k * wf["pd"] * loss)
    first = np.searchsorted(st["path"], np.arange(len(paths)), side="left")    # a path's steps are one block
    for i in np.unique(st["path"][fire]):
        pa = paths[int(i)]
        a = int(first[int(i)])
        m = np.zeros(len(pa.t), dtype=bool)
        m[pa.d["step_pt"][fire[a:a + len(pa.d["step_pt"])]]] = True
        out[int(i)] = m
    return out


# ---------------------------------------------------------------- the exits on every entry

def outcomes(paths: list[Path_], failed: list[dict], costs, tx_l: int, var: str, theta=None,
             hz: list | None = None, gaps=()) -> list[dict]:
    """One row per entry (filled paths and failed buys) for one variant: return per entry over the stake."""
    stake = STAKE_SOL * C.LAMPORTS
    out = []
    for i, pa in enumerate(paths):
        own = masks(pa, var, theta, hz[i] if hz is not None else None) if var not in ("X0", "T") else None
        time_s = float(theta) if var == "T" and theta is not None else TIME_S
        r = simulate(pa, lat_fn(costs, pa.d["mint"]), tx_l, own, time_s, own_why={"HZ": "hazard"}.get(var, "flow"),
                     own_first=var == "HZ")
        s0, s1 = pa.d["signal_ms"], pa.land + TIME_S * 1000 + 60_000
        out.append({"i": i, "mint": pa.d["mint"], "signal_ms": s0, "day": day_of(s0), "ret": r["pnl_l"] / stake,
                    "pnl_sol": r["pnl_l"] / C.LAMPORTS, "why": r["why"], "exit_ms": r["exit_ms"], "legs": r["legs"],
                    "got_l": r["got_l"], "j_sig": r["j_sig"], "sig_ms": r["sig_ms"], "failed": False,
                    "hold_s": (r["exit_ms"] - pa.land) / 1000, "best_l": best_gain(pa, tx_l), "pnl_l": r["pnl_l"],
                    "gapped": bool(any(g0 < s1 and s0 < g1 for g0, g1 in gaps))})
    for f in failed:
        out.append({"i": -1, "mint": f["mint"], "signal_ms": f["signal_ms"], "day": day_of(f["signal_ms"]),
                    "ret": f["pnl_sol"] / STAKE_SOL, "pnl_sol": f["pnl_sol"], "why": "failed buy",
                    "exit_ms": f["land_ms"], "legs": 0, "failed": True, "hold_s": None, "best_l": None,
                    "pnl_l": f["pnl_sol"] * C.LAMPORTS, "gapped": False})
    return sorted(out, key=lambda e: (e["signal_ms"], e["mint"]))


def stats(e: list[dict]) -> dict:
    out = {"n": len(e), "failed": sum(1 for x in e if x["failed"])}
    if not e:
        return out
    r = np.array([x["ret"] for x in e])
    st = np.array([x["ret"] for x in e if x["why"] == "stop"])
    best = [(x["pnl_l"], x["best_l"]) for x in e if x.get("best_l") is not None and x["best_l"] > 0]
    out.update(mean=float(r.mean()), median=float(np.median(r)), pnl_sol=float(sum(x["pnl_sol"] for x in e)),
               win=float((r > 0).mean()), days=len({x["day"] for x in e}),
               exits=dict(sorted(Counter(x["why"] for x in e).items())),
               stops={"n": int(len(st)), "mean": float(st.mean()) if len(st) else None,
                      "median": float(np.median(st)) if len(st) else None,
                      "below": float(st.mean() + SL) if len(st) else None},
               capture=float(sum(a for a, _ in best) / sum(b for _, b in best)) if best else None,
               hold_s=float(np.median([x["hold_s"] for x in e if x["hold_s"] is not None] or [math.nan])))
    return out


def day_band(diff: np.ndarray, days: np.ndarray, draws: int = BOOT, seed: int = SEED) -> tuple[float, float]:
    """90 % band of the mean paired difference, whole UTC days resampled; n/a under MIN_DAYS days."""
    u = sorted(set(days.tolist()))
    if len(u) < MIN_DAYS:
        return math.nan, math.nan
    s = np.array([diff[days == d].sum() for d in u])
    c = np.array([(days == d).sum() for d in u], dtype=float)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(u), size=(draws, len(u)))
    m = s[idx].sum(axis=1) / np.maximum(c[idx].sum(axis=1), 1)
    return float(np.quantile(m, 0.05)), float(np.quantile(m, 0.95))


def verdict(var: list[dict], base: list[dict]) -> dict:
    """The registered rule: a higher mean on the same entries, the day-block band of the paired difference above 0,
    and its stops landing less badly than X0's (a variant without stops holds this)."""
    a = {(x["signal_ms"], x["mint"]): x for x in var}
    pairs = [(a[k]["ret"], b["ret"], b["day"], b["why"]) for b in base for k in [(b["signal_ms"], b["mint"])] if k in a]
    if not pairs:
        return {"n": 0, "diff": None, "band": (math.nan, math.nan), "passes": False}
    r1, r0 = np.array([p[0] for p in pairs]), np.array([p[1] for p in pairs])
    days = np.array([p[2] for p in pairs], dtype=object)
    diff = r1 - r0
    lo, hi = day_band(diff, days)
    sv, s0 = stats(var)["stops"], stats(base)["stops"]
    stop_ok = sv["n"] == 0 or (s0["mean"] is not None and sv["mean"] > s0["mean"])
    on_stops = np.array([p[3] == "stop" for p in pairs])
    out = {"n": len(pairs), "diff": float(diff.mean()), "band": (lo, hi), "higher": bool(r1.mean() > r0.mean()),
           "band_above": bool(math.isfinite(lo) and lo > 0), "stops_better": bool(stop_ok),
           "on_x0_stops": float(diff[on_stops].mean()) if on_stops.any() else None, "x0_stops": int(on_stops.sum())}
    out["passes"] = out["higher"] and out["band_above"] and out["stops_better"]
    return out


def book(e: list[dict], limits: P.Limits, tx_l: int) -> dict:
    """The entries in signal order through a pipeline.Risk with these limits; at 0.1 SOL an entry's P&L is twice its
    P&L at 0.05 plus one more fee per transaction (the impact is not simulated again)."""
    lim = limits.capped()
    k = lim.stake_sol / STAKE_SOL
    risk = P.Risk(lim)
    heap, taken, skipped = [], [], Counter()
    limit = int(lim.stake_sol * (1 + C.SLIP_TOL) * C.LAMPORTS)

    def close(until):
        while heap and heap[0][0] <= until:
            t, j, pnl = heapq.heappop(heap)
            risk.release(j)
            risk.booked(t, pnl)
            taken.append((t, pnl))
    for j, x in enumerate(e):
        close(x["signal_ms"])
        why = risk.why_not(x["signal_ms"], limit)
        if why:
            skipped[why] += 1
            continue
        pnl = x["pnl_l"] if x["failed"] else x["pnl_l"] * k + (k - 1) * (1 + x["legs"]) * tx_l
        risk.hold(j, limit)
        heapq.heappush(heap, (x["exit_ms"], j, pnl))
    close(math.inf)
    pnl = np.array([p for _, p in sorted(taken)]) / C.LAMPORTS
    return {"n": len(pnl), "skipped": dict(skipped), "mean": float(pnl.mean() / lim.stake_sol) if len(pnl) else None,
            "pnl_sol": float(pnl.sum()), "max_dd_sol": XL.max_drawdown(pnl.tolist())}


def fit_in_sample(var: str, paths: list[Path_], failed: list, costs, tx_l: int, hzf=None) -> tuple:
    """The grid value with the highest in-sample mean per entry (ties: the earlier); the grid's means."""
    ins = [i for i, pa in enumerate(paths) if day_of(pa.d["signal_ms"]) < OOS_FROM]
    sub = [paths[i] for i in ins]
    fl = [f for f in failed if day_of(f["signal_ms"]) < OOS_FROM]
    grid = GRIDS[var]
    if var == "DAR":
        pts = np.concatenate([pa.d["dar"][pa.jl:][pa.t[pa.jl:] <= pa.land + TIME_S * 1000] for pa in sub] or [[]])
        pts = pts[np.isfinite(pts)].astype(np.float64)
        grid = tuple(float(np.quantile(pts, q)) for q in DAR_Q) if len(pts) else ()
    means = []
    for g in grid:
        hz = None
        if var == "HZ":
            full = hzf(g)
            hz = [full[i] for i in ins]
        e = outcomes(sub, fl, costs, tx_l, var, g, hz)
        means.append(float(np.mean([x["ret"] for x in e])) if e else -math.inf)
    if not means:
        return None, []
    return grid[int(np.argmax(means))], list(zip(grid, means))


# ---------------------------------------------------------------- measured first (owner notes 2 and 3)

def crossing(pa: Path_, j_sig: int, level: float = 1 - SL) -> int | None:
    """The point whose trade first took the value to or under `level` of cost for good before j_sig."""
    m = pa.mult
    j = j_sig
    while j >= 1 and np.isfinite(m[j]) and m[j] <= level:
        j -= 1
    j += 1
    return j if 1 <= j <= j_sig and m[j] <= level else None


def one_tx(pa: Path_, j_sig: int, got_l: float) -> dict | None:
    """Was the stop's whole loss one pool transaction: the run of consecutive trades of the crossing's slot by its
    signer (and, wider, of its slot) took the value from above -20 % to at or under what the sale landed at."""
    j = crossing(pa, j_sig)
    if j is None:
        return None
    slot, uid = pa.d["slot"], pa.d["uid"]
    out = {}
    for name, same in (("tx", lambda a, b: slot[a] == slot[b] and uid[a] == uid[b]),
                       ("slot", lambda a, b: slot[a] == slot[b])):
        a = j
        while a - 1 >= 1 and same(a - 1, j):
            a -= 1
        b = j
        while b + 1 < len(pa.t) and same(b + 1, j):
            b += 1
        before, after = float(pa.mult[a - 1]), float(pa.mult[b])
        out[name] = bool(before > 1 - SL and after <= got_l / pa.cost)
        out[name + "_drop"] = after - before
    out["landed"] = got_l / pa.cost - 1
    return out


def one_tx_share(rows: list[dict]) -> dict:
    ok = [r for r in rows if r is not None]
    if not ok:
        return {"n": 0}
    one = [r for r in ok if r["tx"]]
    rest = [r for r in ok if not r["tx"]]
    share = len(one) / len(ok)
    return {"n": len(ok), "share_tx": share, "share_slot": sum(r["slot"] for r in ok) / len(ok),
            "landed_one": float(np.mean([r["landed"] for r in one])) if one else None,
            "landed_rest": float(np.mean([r["landed"] for r in rest])) if rest else None,
            "majority": share > ONE_TX_MAJORITY}


def live_rows(live_dir: Path, since_ms: int = SINCE_MS, until_ms: int = UNTIL_MS) -> list[dict]:
    """The live P_pool0 trades of the window (ledger.csv) with the stop's signal time and tokens from the sale's
    fill in measured.jsonl; only the records, never a key or the wallet."""
    led = RL.read_live_ledger(live_dir / "ledger.csv")
    fills, buys = {}, {}
    for r in XL.read_jsonl(live_dir / "measured.jsonl"):
        if r.get("what") == "fill" and r.get("rule") == BASE:
            (fills if r.get("side") == "sell" else buys)[(r.get("mint"), r.get("pid"))] = r
    out = []
    for r in led:
        sig = RL._f(r.get("signal_ms"))
        if r.get("rule") != BASE or sig is None or not since_ms <= sig <= until_ms:
            continue
        pid = int(float(r["pid"])) if r.get("pid") not in (None, "") else None
        f = fills.get((r.get("mint"), pid)) or {}
        b = buys.get((r.get("mint"), pid)) or {}
        out.append({"mint": r.get("mint"), "symbol": r.get("symbol"), "signal_ms": sig, "pid": pid,
                    "land_ms": RL._f(r.get("land_ms")), "exit_ms": RL._f(r.get("exit_ms")), "why": r.get("exit_why"),
                    "ret": RL._f(r.get("ret")), "stake_l": (RL._f(r.get("stake_sol")) or 0) * C.LAMPORTS,
                    "proceeds_l": (RL._f(r.get("proceeds_sol")) or 0) * C.LAMPORTS,
                    "pnl_sol": RL._f(r.get("pnl_sol")), "stop_sig_ms": RL._f(f.get("signal_ms")),
                    "tokens": f.get("tokens"), "lat_ms": RL._f(f.get("lat_ms")),
                    "sale_l": RL._f(f.get("sol_l")), "sale_slip": RL._f(f.get("slip")),
                    "cost_l": RL._f(b.get("sol_l")),
                    "sale_land_ms": RL._f(f.get("land_ms"))})
    return out


SLOT_MS = 400                                           # a Solana slot, about


def record_path(rows: list[dict]) -> dict:
    """One coin's pool trades from the record in chain order (slot, transaction) as a path: the state after each
    trade (effective quote), side, size, signer, slot, timed by store.slot_times. The record's receive times run
    3 to 25 s behind the live executor's own clock (its sales seen that much later), so a live trade is placed by
    its slot and its exact token amount, never by its time."""
    from . import store
    rows = sorted(rows, key=lambda r: (r.get("slot") or 0, r.get("tx") or 0))
    st = store.slot_times((r.get("slot"), r.get("t")) for r in rows)
    uid: dict[str, int] = {}
    cols = {k: [] for k in ("t", "x", "y", "dq", "amt", "fee", "buy", "uid", "slot")}
    for r in rows:
        pb, pq = int(r.get("pb") or 0), C.effective_quote(int(r.get("pq") or 0), r.get("vq"))
        base, quote = int(r.get("base") or 0), int(r.get("quote") or 0)
        x, y = (pb - base, pq + quote) if r["buy"] else (pb + base, pq - quote)
        cols["t"].append(float(st.get(r.get("slot"), r.get("t") or 0)))
        cols["x"].append(float(x))
        cols["y"].append(float(y))
        cols["dq"].append(float(quote if r["buy"] else -quote))
        cols["amt"].append(float(base))
        cols["fee"].append(float(sum(int(v) for v in (r.get("lpb"), r.get("pfb"), r.get("cfb")) if v is not None)))
        cols["buy"].append(float(bool(r["buy"])))
        cols["uid"].append(float(uid.setdefault(r.get("user") or "", len(uid))))
        cols["slot"].append(int(r.get("slot") or 0))
    out = {k: np.asarray(v, dtype=np.int64 if k == "slot" else np.float64) for k, v in cols.items()}
    n = len(rows)
    out.update(mint=rows[0]["mint"] if rows else None, land_ms=float(out["t"][0]) if n else 0.0, j_land=0,
               tokens=0, cost_l=0)
    return out


def exec_split(lv: dict) -> dict | None:
    """A live stop by the executor's own records: its mark at the stop's signal (the expected proceeds the sale
    was sent with, the fill over 1 + its slip), so the overshoot past -20 % at the trigger, the move during the
    sale's latency (fill against that mark: the path, any sandwich, all in one), each over the buy's SOL (what the
    stop compares with); `rest` the ledger's return less the fill (fees, the ledger's stake); `worse` the sale
    landed under the mark it was sent at."""
    cost, got, slip = lv.get("cost_l"), lv.get("sale_l"), lv.get("sale_slip")   # the stop's own basis
    if not cost or got is None or slip is None or slip <= -1:
        return None
    expect = got / (1 + slip)
    fill = got / cost - 1                               # the sale's SOL after the pool fee, before the fees
    return {"symbol": lv["symbol"], "ret": lv["ret"], "fill": fill, "mark_sig": expect / cost - 1,
            "overshoot": expect / cost - (1 - SL), "latency": (got - expect) / cost, "lat_ms": lv.get("lat_ms"),
            "rest": (lv["ret"] or 0) - fill, "worse": bool(got < expect)}


def live_split(lv: dict, d: dict) -> dict | None:
    """The gap from -20 % to a live stop's fill in points of the cost: the overshoot at the trigger, the path during
    the latency, a same-slot sandwich's front leg, our own impact, the pool fee; the transaction fees apart; the
    slippage setting 0 (min_out 0). Our buy and our sale are the coin's pool trades with exactly the tokens bought
    and sold (the first buy, then the first sale after it); the stop's signal is the state that many slots before
    our sale that the executor's sale latency spans (SLOT_MS a slot)."""
    tokens, cost = lv.get("tokens"), lv.get("cost_l") or lv["stake_l"]
    if not tokens or not cost or not len(d.get("t", ())):
        return None
    amt, buy, slot, uid = d["amt"], d["buy"], d["slot"], d["uid"]
    mine = np.flatnonzero(amt == float(tokens))
    kb = next((int(j) for j in mine if buy[j] == 1), None)
    k = next((int(j) for j in mine if buy[j] == 0 and (kb is None or j > kb)), None)
    if k is None:
        return {"found": False, "symbol": lv["symbol"], "why": "no pool sale of exactly its tokens in the record"}
    d = dict(d, tokens=tokens, cost_l=cost, land_ms=float(d["t"][kb if kb is not None else 0]),
             j_land=kb if kb is not None else 0)
    pa = Path_(d)
    x, y = pa.x, pa.y
    lat = max(0.0, float(lv.get("lat_ms") or 0.0))
    ns = max(1, int(round(lat / SLOT_MS)))
    lo = kb if kb is not None else 0
    js = max(lo, int(np.searchsorted(slot, slot[k] - ns, side="right")) - 1)
    pre = k - 1
    mid = lambda j: tokens * y[j] / x[j]                     # noqa: E731
    front, sandwich = pre, False
    if pre > lo and slot[pre] == slot[k] and buy[pre] == 0 and uid[pre] != uid[k]:
        s_ = uid[pre]
        a = pre
        while a - 1 > lo and slot[a - 1] == slot[k] and uid[a - 1] == s_:
            a -= 1
        back = any(slot[j] == slot[k] and uid[j] == s_ and buy[j] == 1 for j in range(k + 1, min(len(slot), k + 20)))
        if back:
            sandwich, front = True, a - 1
    gross = y[pre] * tokens / (x[pre] + tokens)
    got = lv.get("sale_l") or lv["proceeds_l"]          # the sale's SOL after the pool fee, before the fees
    parts = {"overshoot": mid(js) / cost - (1 - SL), "path": (mid(front) - mid(js)) / cost,
             "sandwich": (mid(pre) - mid(front)) / cost, "impact": (gross - mid(pre)) / cost,
             "pool_fee": (got - gross) / cost, "slippage_setting": 0.0}
    fill = got / cost - 1
    return {"found": True, "symbol": lv["symbol"], "fill": fill, "ret": lv["ret"], "gap": fill + SL,
            "rest": (lv["ret"] or 0) - fill, "sandwich_seen": sandwich, "lat_ms": lat,
            "slots": int(slot[k] - slot[js]), "trades_between": int(pre - js), **parts,
            "one_tx": one_tx(pa, max(js, lo + 1), got)}


def buyback(paths: list[dict]) -> dict:
    """Per entered pool, the inferred BOOST buyer's first and last buy after the migration and the pool's price
    around its last buy (log changes from 30 s before it to it, and from it to 30, 60, 120 s after)."""
    rows = []
    for d in paths:
        b = d["bb_buys"]
        if not b:
            rows.append({"seen": False})
            continue
        last = b[-1]
        pa = Path_(d)
        price = lambda ms: pa.y[pa.at(ms)] / pa.x[pa.at(ms)] if pa.x[pa.at(ms)] else math.nan   # noqa: E731
        p0 = price(last)
        r = {"seen": True, "first_s": (b[0] - d["mig_ms"]) / 1000, "last_s": (last - d["mig_ms"]) / 1000,
             "buys": len(b), "before30": math.log(p0 / price(last - 30_000)) if p0 > 0 else math.nan}
        for h in (30, 60, 120):
            ok = last + h * 1000 <= pa.t[-1] and d["complete"]
            r[f"after{h}"] = math.log(price(last + h * 1000) / p0) if ok and p0 > 0 else math.nan
        rows.append(r)
    seen = [r for r in rows if r["seen"]]
    out = {"pools": len(rows), "with_buyer": len(seen)}
    if seen:
        ls = np.array([r["last_s"] for r in seen])
        out.update(first_s=float(np.median([r["first_s"] for r in seen])), last_q=np.quantile(ls, [0.1, 0.25, 0.5,
                   0.75, 0.9]).tolist(), buys=float(np.median([r["buys"] for r in seen])),
                   hist={(f"{a}-{b}" if b < 1e9 else f"over {a}"): int(((ls > a) & (ls <= b)).sum()) for a, b in
                         ((0, 180), (180, 240), (240, 270), (270, 300), (300, 330), (330, 360), (360, 420), (420, 1e9))})
        for k in ("before30", "after30", "after60", "after120"):
            v = np.array([r[k] for r in seen])
            v = v[np.isfinite(v)]
            out[k] = {"n": int(len(v)), "mean": float(v.mean()) if len(v) else None,
                      "median": float(np.median(v)) if len(v) else None}
    return out


# ---------------------------------------------------------------- the whole evaluation

def evaluate(res: dict, live: list[dict] | None = None, log=print, amm_rows: dict | None = None) -> dict:
    """amm_rows: the record's pool trades of the live stops' coins (mint -> rows), for the live split."""
    sc = scenarios()
    out = {"scenarios": {}, "measured": {}}
    for k in SCENARIOS:
        raw = res["paths"][k]
        paths = [Path_(d) for d in raw if d.get("land_ms") is not None and d["tokens"] > 0]
        failed = res["failed"][k]
        tx_l = res["tx_l"][f"{BASE}@{k}"]
        L = lag_ms(k)
        st = step_table(paths, L)
        wf = walk_forward(st, paths, L, log)
        hz_cache: dict = {}

        def hzf(g):
            if g not in hz_cache:
                hz_cache[g] = hz_masks(st, wf, paths, g)
            return hz_cache[g]
        fits, rows = {}, {}
        for var in VARIANTS:
            theta, grid = (None, [])
            if var in GRIDS:
                theta, grid = fit_in_sample(var, paths, failed, sc[k], tx_l, hzf)
            fits[var] = {"theta": theta, "grid": grid}
            rows[var] = outcomes(paths, failed, sc[k], tx_l, var, theta, hzf(theta) if var == "HZ" else None,
                                 res.get("gaps", ()))
        tab, ins, vs, vs_gap, bk = {}, {}, {}, {}, {}
        for var in VARIANTS:
            e = rows[var]
            oos = [x for x in e if x["day"] >= OOS_FROM]
            tab[var] = stats(oos)
            ins[var] = stats([x for x in e if x["day"] < OOS_FROM])
            bk[var] = {s: book(oos, lim, tx_l) for s, lim in SIZINGS.items()}
        base = [x for x in rows["X0"] if x["day"] >= OOS_FROM]
        for var in VARIANTS[1:]:
            oos = [x for x in rows[var] if x["day"] >= OOS_FROM]
            vs[var] = verdict(oos, base)
            vs_gap[var] = verdict([x for x in oos if not x["gapped"]], [x for x in base if not x["gapped"]])
        # the pipeline's own P_pool0 against the path simulator's X0 (same entries, same draws)
        pc = {c["pid"]: c for c in res["pipe_closed"][k]}
        same = [(abs(pc[pa.d["pid"]]["ret"] - x["ret"]) < 0.01 and pc[pa.d["pid"]]["exit_why"] == x["why"])
                for pa, x in zip(paths, [y for y in sorted(rows["X0"], key=lambda z: z["i"]) if y["i"] >= 0])
                if pa.d["pid"] in pc]
        sc_out = {"entries": len(rows["X0"]), "paths": len(paths), "failed": len(failed), "steps": int(st.get("n", 0)),
                  "L_ms": L, "tx_l": tx_l, "fits": fits, "table": tab, "in_sample": ins, "versus": vs,
                  "versus_no_gap": vs_gap, "books": bk, "models": wf["days"],
                  "x0_check": {"n": len(same), "match": float(np.mean(same)) if same else None}}
        x0 = rows["X0"]
        ot = [one_tx(paths[x["i"]], x["j_sig"], x["got_l"]) for x in x0 if x["why"] == "stop" and x["i"] >= 0
              and x["day"] >= OOS_FROM]
        sc_out["one_tx_paper"] = one_tx_share(ot)
        out["scenarios"][k] = sc_out
        if k == JUDGED:
            out["measured"]["buyback"] = buyback([d for d in raw if d.get("land_ms") is not None])
            sp = []
            for lv in live or []:
                if lv["why"] != "stop":
                    continue
                rows = (amm_rows or {}).get(lv["mint"]) or []
                sp.append(live_split(lv, record_path(rows)) if rows else {"found": False, "symbol": lv["symbol"],
                                                                           "why": "no pool trade in the record"})
            out["measured"]["live_stops"] = sp
            ex = [exec_split(lv) for lv in live or [] if lv["why"] == "stop"]
            ex = [x for x in ex if x is not None]
            out["measured"]["live_exec"] = ex
            if ex:
                out["measured"]["live_exec_summary"] = {
                    "n": len(ex), "worse": sum(x["worse"] for x in ex) / len(ex),
                    **{k: float(np.mean([x[k] for x in ex])) for k in ("ret", "fill", "overshoot", "latency", "rest")}}
            out["measured"]["one_tx_live"] = one_tx_share([s.get("one_tx") for s in sp if s and s.get("found")])
            lv = live or []
            st_ = [x["ret"] for x in lv if x["why"] == "stop" and x["ret"] is not None]
            out["measured"]["live"] = {"n": len(lv), "stops": len(st_), "stop_mean": float(np.mean(st_)) if st_ else None,
                                       "pnl_sol": float(sum(x["pnl_sol"] or 0 for x in lv))}
        log(f"flowexit: {k} evaluated, {len(paths):,} paths")
    out["pick"] = pick(out["scenarios"][JUDGED])
    return out


def amm_rows_of(live: list[dict], root=None) -> dict:
    """The record's pool trades of the live stops' coins, read once per day."""
    from . import store
    import polars as pl
    want = {x["mint"] for x in live if x["why"] == "stop"}
    out: dict[str, list] = {}
    for d in sorted({day_of(x["signal_ms"]) for x in live if x["why"] == "stop"}):
        df = store.read("amm", [d], root).filter(pl.col("mint").is_in(list(want)))
        for r in df.to_dicts():
            out.setdefault(r["mint"], []).append(r)
    return out


def pick(sc: dict) -> str | None:
    ok = [v for v in VARIANTS[1:] if sc["versus"][v]["passes"]]
    return max(ok, key=lambda v: sc["table"][v]["mean"]) if ok else None


# ---------------------------------------------------------------- report

pct = RL.pct


def _b(b) -> str:
    return f"{pct(b[0])} to {pct(b[1])}"


def _theta(var: str, th) -> str:
    if th is None:
        return "" if var in ("X0", "BB") else "n/a"
    return f"k {th:g}" if var == "HZ" else (f"{th:g} s" if var == "T" else f"{th:.3g}")


def report_md(res: dict, ev: dict) -> str:
    def utc(x):
        return f"{datetime.fromtimestamp(x / 1000, timezone.utc):%Y-%m-%d %H:%M} UTC"
    md = ["# X14 r2: an order-flow exit for P_pool0 (flowexit)", "",
          f"Record {res['days'][0]} to {utc(res['span'][1])}, signals to {utc(res['entry_until_ms'])}; out of sample "
          f"from {OOS_FROM}. {STAKE_SOL} SOL, every P_pool0 signal entered, paired by entry."]
    m = ev["measured"]
    md += ["", "## Measured first", ""]
    for k in SCENARIOS:
        o = ev["scenarios"][k]["one_tx_paper"]
        if o.get("n"):
            md.append(f"- {SCENARIO_LABEL[k]}: {o['n']} X0 stops out of sample, one transaction {o['share_tx'] * 100:.0f} %"
                      f" (one slot {o['share_slot'] * 100:.0f} %); they land at {pct(o['landed_one'])}, the rest at "
                      f"{pct(o['landed_rest'])}.")
    o = m.get("one_tx_live") or {}
    if o.get("n"):
        md.append(f"- Live stops since 13:26 found in the record: {o['n']}, one transaction {o['share_tx'] * 100:.0f} %.")
    md += ["", "| live stop | fill | gap to -20 % | overshoot | path | sandwich | impact | pool fee | rest (fees) | "
           "sale latency | one tx |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for s in m.get("live_stops") or []:
        if not s or not s.get("found"):
            md.append(f"| {s.get('symbol') if s else '?'} | {(s or {}).get('why') or 'not found'} | | | | | | | | | |")
            continue
        md.append(f"| {s['symbol']} | {pct(s['fill'])} | {pct(s['gap'])} | {pct(s['overshoot'])} | {pct(s['path'])} | "
                  f"{pct(s['sandwich'])} | {pct(s['impact'])} | {pct(s['pool_fee'])} | {pct(s['rest'])} | "
                  f"{s['lat_ms'] / 1000:.1f} s, {s['slots']} slots, {s['trades_between']} trades | "
                  f"{'yes' if (s.get('one_tx') or {}).get('tx') else 'no'} |")
    md += ["", "| live stop (executor's records) | return | fill | mark at the signal | overshoot past -20 % | "
           "during the latency | rest (fees) | sale latency | landed under the mark |", "|---|---|---|---|---|---|---|---|---|"]
    for x in m.get("live_exec") or []:
        md.append(f"| {x['symbol']} | {pct(x['ret'])} | {pct(x['fill'])} | {pct(x['mark_sig'])} | {pct(x['overshoot'])} | "
                  f"{pct(x['latency'])} | {pct(x['rest'])} | {(x['lat_ms'] or 0) / 1000:.1f} s | "
                  f"{'yes' if x['worse'] else 'no'} |")
    es = m.get("live_exec_summary")
    if es:
        md.append(f"| mean of {es['n']} | {pct(es['ret'])} | {pct(es['fill'])} | | {pct(es['overshoot'])} | "
                  f"{pct(es['latency'])} | {pct(es['rest'])} | | {es['worse'] * 100:.0f} % |")
    bb = m.get("buyback") or {}
    if bb.get("with_buyer"):
        md += ["", f"Buyback: {bb['with_buyer']} of {bb['pools']} entered pools have an inferred buyer, median "
               f"{bb['buys']:.0f} buys, first {bb['first_s']:.0f} s after the migration; last buy (10/25/50/75/90 %) "
               + ", ".join(f"{q:.0f}" for q in bb["last_q"]) + " s; " + ", ".join(f"{a} s: {c}" for a, c in bb["hist"].items())
               + ". Price, log change: " + "; ".join(f"{k} {pct(bb[k]['mean'])} (median {pct(bb[k]['median'])}, "
                                                    f"{bb[k]['n']})" for k in ("before30", "after30", "after60", "after120"))]
    for k in SCENARIOS:
        s = ev["scenarios"][k]
        md += ["", f"## {SCENARIO_LABEL[k]}", "",
               f"{s['entries']} entries ({s['failed']} failed buys), {s['steps']:,} steps, L {s['L_ms']:.0f} ms, "
               f"{s['tx_l']:,} lamports a transaction; the path simulator's X0 matches the pipeline's P_pool0 on "
               f"{(s['x0_check']['match'] or 0) * 100:.1f} % of {s['x0_check']['n']} entries.", "",
               "| exit | fitted | entries | mean | median | win | P&L SOL | stops | stop mean | below -20 % | capture | "
               "vs X0 | band (days) | on X0's stops | passes | in sample |",
               "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for var in VARIANTS:
            t, i = s["table"][var], s["in_sample"][var]
            st = t.get("stops") or {}
            v = s["versus"].get(var)
            vs = "| | | |" if v is None else (f"{pct(v['diff'])} | {_b(v['band'])} | {pct(v['on_x0_stops'])} | "
                                              f"{'yes' if v['passes'] else 'no'} |")
            md.append(f"| {var} | {_theta(var, s['fits'][var]['theta'])} | {t['n']} | {pct(t.get('mean'))} | "
                      f"{pct(t.get('median'))} | {t.get('win', 0) * 100:.0f} % | {t.get('pnl_sol', 0):+.3f} | "
                      f"{st.get('n', 0)} | {pct(st.get('mean'))} | {pct(st.get('below'))} | {pct(t.get('capture'))} | "
                      f"{vs} {pct(i.get('mean'))} |")
        md += ["", "Exits: " + "; ".join(f"{v} " + ", ".join(f"{w} {c}" for w, c in s["table"][v].get("exits", {}).items())
                                        for v in VARIANTS)]
        md += ["", "Without trades open across a gap: " + "; ".join(
            f"{v} {pct(s['versus_no_gap'][v]['diff'])} ({_b(s['versus_no_gap'][v]['band'])})" for v in VARIANTS[1:])]
        md += ["", "| exit | live book (0.05 SOL, 1 open, 0.12 a day): entries | mean | P&L | max DD | skipped | "
               "wide (0.1, 4, 1.0): entries | mean | P&L | max DD |", "|---|---|---|---|---|---|---|---|---|---|"]
        for var in VARIANTS:
            a, b = s["books"][var]["live"], s["books"][var]["wide"]
            md.append(f"| {var} | {a['n']} | {pct(a['mean'])} | {a['pnl_sol']:+.3f} | {a['max_dd_sol']:.3f} | "
                      f"{sum(a['skipped'].values())} | {b['n']} | {pct(b['mean'])} | {b['pnl_sol']:+.3f} | "
                      f"{b['max_dd_sol']:.3f} |")
        md += ["", "Models (walk-forward by day): " + "; ".join(
            f"{d} AUC {x['auc']:.3f}, Brier skill {x['brier_skill']:+.3f}" for d, x in s["models"].items()
            if x.get("auc") is not None)]
        md += ["", "In-sample grids: " + "; ".join(
            f"{v} " + ", ".join(f"{g:.3g}: {pct(mu)}" for g, mu in s["fits"][v]["grid"]) for v in GRIDS)]
    md += ["", f"Pick: {ev['pick'] or 'none passes'}."]
    return "\n".join(md) + "\n"


def _clean(o):
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, float) and not math.isfinite(o):
        return None
    if isinstance(o, (np.floating, np.integer)):
        return _clean(o.item())
    return o


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--until-ms", type=int, default=UNTIL_MS)
    ap.add_argument("--out", default=None, help="directory for flowexit.json and flowexit.md (default: the reports)")
    ap.add_argument("--live-dir", default=None, help="the live executor's folder (read only)")
    ap.add_argument("--cache", default=None, help="the replay's paths, kept and read again")
    ap.add_argument("--no-register", action="store_true")
    a = ap.parse_args(argv)
    from .. import metrics
    from .. import report as rep
    from ..data import ROOT
    if not a.no_register:
        metrics.register(trials())                      # before any number exists
    out = Path(a.out) if a.out else rep.REPORTS / "pumpfun_rt"
    out.mkdir(parents=True, exist_ok=True)
    live_dir = Path(a.live_dir) if a.live_dir else ROOT / "live" / "pumpfun_rt"
    cache = Path(a.cache) if a.cache else None
    if cache is not None and cache.exists():
        res = pickle.loads(cache.read_bytes())
    else:
        res = run(until_ms=a.until_ms)
        if res.get("empty"):
            print("flowexit: nothing recorded")
            return 1
        if cache is not None:
            cache.write_bytes(pickle.dumps(res, protocol=pickle.HIGHEST_PROTOCOL))
    live = live_rows(live_dir, until_ms=a.until_ms)
    ev = evaluate(res, live, amm_rows=amm_rows_of(live))
    md = report_md(res, ev)
    keep = {k: v for k, v in res.items() if k not in ("paths", "failed", "pipe_closed")}
    (out / "flowexit.json").write_text(json.dumps(_clean(keep | {"eval": ev}), indent=1, default=str),
                                       encoding="utf-8")
    (out / "flowexit.md").write_text(md, encoding="utf-8")
    print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
