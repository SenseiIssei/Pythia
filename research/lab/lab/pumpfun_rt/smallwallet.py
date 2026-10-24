"""R2: pump.fun strategies for a small wallet (0.55 and 1.1 SOL, about 50 and 100 EUR) under realistic execution.
PAPER ONLY.

    python -m lab.pumpfun_rt.smallwallet run --out DIR     the replay, the wallet bootstrap, smallwallet.{json,md}

Pre-registered in results/pumpfun_smallwallet_r2_prereg.md. One replay of the record to UNTIL_MS with R1's realistic
model fitted to the live orders of the 7 days to the cutoff (realistic.py): each candidate is a realistic book at
0.1 SOL without a slot, exposure or loss limit (Rec), so every signal has its realistic outcome, with the reserves at
its buy and its sale; the Y9 select models (on R2's realistic label rows, labels_r2.RealLabelPipe) and et_alive5m are
trained at the end of each day for the next (trends10.day_models). Out of sample: the full UTC days from the first one
on which every candidate has its models.

The wallet (simulate): the live sizing with limits=wallet (sizing._wallet, floor 0 as the owner has it, the brake on or
off), at most 2 % of the pool's SOL, at most max_open positions, no daily loss limit, no top-up; a trade's return at
another stake rescaled from its 0.1 SOL fill on the reserves at the buy and the sale (scaled); the fixed fees as
recorded. The bootstrap: PATHS paths of HORIZON days, each day drawn with replacement from the out-of-sample days, the
same draws for every setting. Nothing here holds a wallet, reads a key, signs or sends anything.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import math
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from . import curve as C
from . import pipeline as P
from . import realistic as R
from . import sizing as Z

# ---------------------------------------------------------------- registered (results/pumpfun_smallwallet_r2_prereg.md)

CANDIDATES = ("P_pool0_wait", "P_pool0_wait_lock", "P_pool0_wait_run20", "P_pool0_wait_free10_tight",
              "P_pool0_top30", "P_pool5_top30t", "P_hot5")
SHARES = (0.10, 0.25, 0.50, 1.00)
MAX_OPEN = (1, 2, 3)
BRAKES = (True, False)
STARTS = (0.55, 1.1)
PATHS = 2_000
HORIZON = 30
SEED = 20261024
UNTIL_MS = int(datetime(2026, 10, 24, tzinfo=timezone.utc).timestamp() * 1000)
TAIL_MS = 15 * 60_000
STAKE_SOL = 0.1
EUR_PER_SOL = 91.0                         # reports/pumpfun_rt/target_eur.json of 2026-10-24 (21.93 EUR for 0.24 SOL)
TARGET_EUR = {0.55: 100.0, 1.1: 200.0}     # days to 100 EUR from 50, to 200 EUR from 100
DOUBLE, LOST = 2.0, 0.2
FLOOR_SOL = 0.0                            # the owner's floor: all in until the wallet cannot pay MIN_STAKE_SOL
DAY_MS = 86_400_000
LIMITS = P.Limits(STAKE_SOL, 1_000, math.inf, math.inf)


# ---------------------------------------------------------------- the replay

class Rec(R.Book):
    """A realistic book at 0.1 SOL without limits that notes the reserves (pool SOL, else the curve's virtual SOL) at
    the buy and at the close of each trade, for the stake's own impact at another size."""

    @staticmethod
    def _q(tok) -> int:
        if tok is None:
            return 0
        return int(tok.pq or 0) if not tok.on_curve else int(tok.vs or 0)

    def bought(self, pid: int, at: float, tokens: int, cost_l: int, fee_l: int) -> None:
        p = self.pos.get(pid)
        if p is not None:
            p["q_in"] = self._q(self.eng.tokens.get(p["mint"]))
        super().bought(pid, at, tokens, cost_l, fee_l)

    def _close(self, p: dict, at: float) -> None:
        q_out = self._q(self.eng.tokens.get(p["mint"]))
        super()._close(p, at)
        self.closed[-1].update(q_in=p.get("q_in", 0), q_out=q_out, cost_sol=p["cost_l"] / C.LAMPORTS,
                               fees_sol=p["fees_l"] / C.LAMPORTS)


def entries(pipe: Rec) -> list[dict]:
    """Every signal's outcome: a closed trade (cost, proceeds and fees at 0.1 SOL, the reserves) or a failed buy or
    pre-send skip (its fee, 0 for a skip), in signal order."""
    out = [{"mint": t["mint"], "signal_ms": t["signal_ms"], "exit_ms": t["exit_ms"], "failed": False,
            "cost": t["cost_sol"], "proceeds": t["proceeds_sol"], "fees": t["fees_sol"], "pnl": t["pnl_sol"],
            "q_in": t["q_in"] / C.LAMPORTS, "q_out": t["q_out"] / C.LAMPORTS, "gap": bool(t.get("gap"))}
           for t in pipe.closed]
    out += [{"mint": f["mint"], "signal_ms": f["signal_ms"], "exit_ms": f["land_ms"], "failed": True, "cost": 0.0,
             "proceeds": 0.0, "fees": -f["pnl_sol"], "pnl": f["pnl_sol"], "q_in": 0.0, "q_out": 0.0,
             "why": R._why(f), "gap": False} for f in pipe.failed]
    return sorted(out, key=lambda e: e["signal_ms"])


def replay(root=None, until_ms: int = UNTIL_MS, log=print, model: R.Model | None = None) -> dict:
    from . import early as EA
    from . import labels_r2 as L2
    from . import select9 as S9
    from . import selfeat as SF
    from . import selmodel as SM
    from . import sim, store
    from . import trends10 as T10
    from . import wallets as W
    from .study import WARM_DAYS, WINDOW_DAYS, span_of, warm_book
    model = model or R.Model(R.fit(R._measured(), until_ms))
    all_days = [d for d in store.days(root) if d <= SF.day_of(until_ms - 1)]
    days = all_days[-WINDOW_DAYS:]
    if not days:
        return {"empty": True}
    warm = [d for d in all_days if d < days[0]][-WARM_DAYS:]
    t_lo, t_hi = span_of(days, root)
    t_hi = min(t_hi, until_ms)
    log(f"r2: {len(days)} day(s) {days[0]} to {days[-1]}, record to {t_hi}, warm-up {len(warm)}")
    t0 = time.time()
    eng = sim.Engine([], book=warm_book(warm, root), decisions=False, entry_until=t_hi - TAIL_MS,
                     wallets=W.warm(warm, root), snipers=EA.warm_snipers(warm, root), select=True, trend=True,
                     early_rows=True)
    eng.early.keep_frac = 0.0                              # rows only: et_alive5m
    dm = S9.DayModels()
    dm.eng = eng
    eng.models = dm
    lab = eng.add_pipe(L2.RealLabelPipe(eng, model))
    pipes = {}
    for name in CANDIDATES:
        s = dataclasses.replace(P.BY_NAME[name], stake_sol=STAKE_SOL)
        eng.rule_costs[s.name] = R.RealCosts(model=model)
        pipes[name] = eng.add_pipe(Rec(eng, [s], R.RealExecutor(model), name=f"r2:{name}"))
        pipes[name].risk[s.name].limits = LIMITS              # a measuring book: Risk() would cap it
    trained = {}

    def next_day(day: str, n: int) -> None:
        nd = (datetime.strptime(day, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
        ms = T10.day_models(lab.table(), T10.early_snapshot(eng.early), SM.day_start(nd))
        dm.by_day[nd] = ms
        trained[nd] = T10.usable(ms)
        log(f"r2: {day} done ({n:,} events, {time.time() - t0:.0f} s); models for {nd}: {trained[nd]}")
    sim.replay(days, eng, root, progress=next_day, until_ms=t_hi)
    log(f"r2: replay in {time.time() - t0:.0f} s")
    return {"days": days, "span": (t_lo, t_hi), "trained": trained, "fit": model.fit.to_json(),
            "entries": {n: entries(p) for n, p in pipes.items()}, "gaps": list(eng.gaps),
            "skipped": {f"{k[0]}: {k[1]}": v for k, v in eng.skipped.items() if k[0] in pipes}}


NEEDS = {"P_pool0_top30": ("win0",), "P_pool5_top30t": ("win5t",), "P_hot5": ("et_alive5m",)}


def oos_days(days: list[str], trained: dict, until_ms: int = UNTIL_MS) -> list[str]:
    """The full UTC days from the first one on which every candidate has its models, before the cutoff."""
    need = {m for c in CANDIDATES for m in NEEDS.get(c, ())}
    last = datetime.fromtimestamp(until_ms / 1000, timezone.utc).strftime("%Y-%m-%d")
    first = next((d for d in days if need <= set(trained.get(d) or ())), None)
    return [d for d in days if first is not None and first <= d < last]


# ---------------------------------------------------------------- one day's entries as arrays

def day_start(d: str) -> int:
    return int(datetime.strptime(d, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000)


def day_arrays(es: list[dict], day: str) -> dict:
    """The day's entries (signalled that UTC day) as arrays, times in ms from the day's start."""
    t0 = day_start(day)
    es = [e for e in es if t0 <= e["signal_ms"] < t0 + DAY_MS]
    f = lambda k: np.array([float(e[k]) for e in es], dtype=float)
    return {"sig": f("signal_ms") - t0, "exit": f("exit_ms") - t0, "failed": np.array([e["failed"] for e in es]),
            "cost": f("cost"), "proceeds": f("proceeds"), "fees": f("fees"), "q_in": f("q_in"), "q_out": f("q_out"),
            "n": len(es)}


def scaled(stake, cost0, proceeds0, q_in, q_out):
    """The proceeds of a trade bought for `stake` SOL instead of cost0, on the recorded reserves: the buy's tokens
    k = (stake / cost0) (Q_in + cost0) / (Q_in + stake) times the recorded ones, sold into the pool's Q_out with
    x = proceeds0 / Q_out: (1 + x) / (1 + k x) of k times the recorded proceeds (constant product, the percentage
    fees with them; the fixed fees do not scale)."""
    stake, cost0, proceeds0, q_in, q_out = (np.asarray(v, dtype=float) for v in (stake, cost0, proceeds0, q_in, q_out))
    ok = (cost0 > 0) & (q_in > 0)
    k = np.where(ok, stake / np.where(cost0 > 0, cost0, 1) * (q_in + cost0) / np.where(q_in + stake > 0, q_in + stake,
                                                                                       1), 0.0)
    x = np.where(q_out > 0, proceeds0 / np.where(q_out > 0, q_out, 1), 0.0)
    return np.where(ok, proceeds0 * k * (1 + x) / (1 + k * x), proceeds0 * stake / np.where(cost0 > 0, cost0, 1))


def stake_vec(base, bal, peak, pnl, share, brake):
    """sizing.sized with limits=wallet and the floor FLOOR_SOL (sizing._wallet: the share of the base, at least the
    minimum, the brake where on, at most what the wallet can pay, rounded down to 0.01 SOL, 0 under the minimum),
    for arrays."""
    stake = np.maximum(share * base, Z.MIN_STAKE_SOL)
    fall = peak - pnl
    den = bal + fall
    dd = np.where((fall > 0) & (den > 0), fall / np.where(den > 0, den, 1), 0.0)
    braked = np.where(dd > Z.BRAKE_MIN, Z.MIN_STAKE_SOL,
                      np.where(dd > Z.BRAKE_HALF, np.maximum(stake / 2, Z.MIN_STAKE_SOL), stake))
    stake = np.where(brake, braked, stake)
    room = np.maximum(0.0, bal - R.RESERVE_SOL) / (1 + C.SLIP_TOL)
    stake = np.minimum(stake, room)
    stake = np.maximum(0.0, np.floor(stake * 100 + 1e-9) / 100)
    stake = np.where(stake < Z.MIN_STAKE_SOL, 0.0, stake)
    return np.where(base < FLOOR_SOL, 0.0, stake)


# ---------------------------------------------------------------- the wallet paths

def simulate(day_list: list[dict], draws: np.ndarray, max_open: int, share, brake, start) -> dict:
    """Every path (rows of `draws`: day indices into day_list, one per day of the path) for every config (share,
    brake, start: arrays of one value per config) at once: the wallet's equity (cash plus what the open positions
    cost) at each day's end, the first day it reached 2x and 20 % of the start, and the end (open positions at their
    recorded value)."""
    n_paths, horizon = draws.shape
    share, brake, start = (np.repeat(np.asarray(v), n_paths) for v in (share, brake, start))
    n = len(start)
    pidx = np.tile(np.arange(n_paths), n // n_paths)
    cash, pnl, peak = start.astype(float).copy(), np.zeros(n), np.zeros(n)
    k = max_open
    ex = np.full((n, k), np.inf)                           # an open slot's exit time (ms from the path's start)
    cost = np.zeros((n, k))
    val = np.zeros((n, k))                                 # its proceeds less every fixed fee, at its exit
    eq_day = np.zeros((n, horizon))
    won, lost = np.zeros(n, dtype=bool), np.zeros(n, dtype=bool)
    trades = np.zeros(n)

    def close(rows, t):
        due = ex[rows] <= t
        if not due.any():
            return
        got = np.where(due, val[rows], 0.0).sum(axis=1)
        paid = np.where(due, cost[rows], 0.0).sum(axis=1)
        cash[rows] += got
        pnl[rows] += got - paid
        peak[rows] = np.maximum(peak[rows], pnl[rows])
        e, c, v = ex[rows], cost[rows], val[rows]
        e[due], c[due], v[due] = np.inf, 0.0, 0.0
        ex[rows], cost[rows], val[rows] = e, c, v

    def mark(rows):
        eq = cash[rows] + cost[rows].sum(axis=1)
        w = (eq >= DOUBLE * start[rows]) & ~lost[rows]
        lo = (eq <= LOST * start[rows]) & ~won[rows]
        won[rows] |= w
        lost[rows] |= lo

    for day in range(horizon):
        base_t = day * DAY_MS
        for di, d in enumerate(day_list):
            rows = np.flatnonzero(draws[pidx, day] == di)
            if not len(rows) or not d["n"]:
                continue
            for j in range(d["n"]):
                t = base_t + d["sig"][j]
                close(rows, t)
                n_open = np.isfinite(ex[rows]).sum(axis=1)
                held = cost[rows].sum(axis=1)
                s = stake_vec(cash[rows] + held, cash[rows], peak[rows], pnl[rows], share[rows], brake[rows])
                if d["q_in"][j] > 0:
                    s = np.minimum(s, math.floor(P.MAX_IMPACT * d["q_in"][j] * 100) / 100)
                go = (n_open < k) & (s > 0)
                if not go.any():
                    continue
                r = rows[go]
                if d["failed"][j]:
                    cash[r] -= d["fees"][j]
                    pnl[r] -= d["fees"][j]
                    peak[r] = np.maximum(peak[r], pnl[r])
                else:
                    sg = s[go]
                    slot = np.argmax(~np.isfinite(ex[r]), axis=1)
                    cash[r] -= sg
                    ex[r, slot] = base_t + d["exit"][j]
                    cost[r, slot] = sg
                    val[r, slot] = scaled(sg, d["cost"][j], d["proceeds"][j], d["q_in"][j], d["q_out"][j]) \
                        - d["fees"][j]
                    trades[r] += 1
                mark(rows)
        allr = np.arange(n)
        close(allr, base_t + DAY_MS)
        mark(allr)
        eq_day[:, day] = cash + cost.sum(axis=1)
    end = cash + val.sum(axis=1)
    held = np.isfinite(ex).any(axis=1)
    room = np.maximum(0.0, cash - R.RESERVE_SOL) / (1 + C.SLIP_TOL)
    ruin = ~held & (room < Z.MIN_STAKE_SOL)
    return {"eq_day": eq_day, "end": end, "won": won, "lost": lost, "ruin": ruin, "trades": trades,
            "n_paths": n_paths}


def outcome(sim: dict, c: int, start: float, target_sol: float) -> dict:
    """The numbers of config c (its block of paths)."""
    n = sim["n_paths"]
    sl = slice(c * n, (c + 1) * n)
    eq, end = sim["eq_day"][sl], sim["end"][sl]
    hit = eq >= target_sol
    first = np.where(hit.any(axis=1), hit.argmax(axis=1) + 1, np.inf)
    d7 = eq[:, min(6, eq.shape[1] - 1)]
    return {"start": start, "p10": float(np.quantile(end, 0.1)), "median": float(np.median(end)),
            "p90": float(np.quantile(end, 0.9)), "mean": float(end.mean()),
            "d7_p10": float(np.quantile(d7, 0.1)), "d7_median": float(np.median(d7)),
            "d7_p90": float(np.quantile(d7, 0.9)),
            "p_double": float(sim["won"][sl].mean()), "p_lost80": float(sim["lost"][sl].mean()),
            "p_ruin": float(sim["ruin"][sl].mean()), "days_target": float(np.median(first)),
            "p_target": float(np.isfinite(first).mean()), "trades": float(np.median(sim["trades"][sl])),
            "path_median": [float(x) for x in np.median(eq, axis=0)],
            "path_p10": [float(x) for x in np.quantile(eq, 0.1, axis=0)],
            "path_p90": [float(x) for x in np.quantile(eq, 0.9, axis=0)]}


def search(entries_by: dict[str, list[dict]], days: list[str], paths: int = PATHS, horizon: int = HORIZON,
           seed: int = SEED, log=print) -> list[dict]:
    """Every setting of the grid on the same bootstrap draws."""
    rng = np.random.default_rng(seed)
    draws = rng.integers(0, len(days), size=(paths, horizon))
    cfg = [(s, b, w) for w in STARTS for s in SHARES for b in BRAKES]
    out = []
    for name in entries_by:
        dl = [day_arrays(entries_by[name], d) for d in days]
        for mo in MAX_OPEN:
            t0 = time.time()
            sim = simulate(dl, draws, mo, [c[0] for c in cfg], [c[1] for c in cfg], [c[2] for c in cfg])
            for i, (s, b, w) in enumerate(cfg):
                out.append({"strategy": name, "share": s, "max_open": mo, "brake": b,
                            **outcome(sim, i, w, TARGET_EUR[w] / EUR_PER_SOL)})
            log(f"r2: {name} max_open {mo} in {time.time() - t0:.0f} s")
    return out


def expectation(es: list[dict], days: list[str], draws: int = 5_000, seed: int = SEED) -> dict:
    """The mean P&L per entry at 0.1 SOL (failed buys and skips included) over the days, a 90 % day-bootstrap band,
    and the mean per closed trade."""
    by = [[e["pnl"] for e in es if day_start(d) <= e["signal_ms"] < day_start(d) + DAY_MS] for d in days]
    allp = [x for b in by for x in b]
    tr = [e["pnl"] / e["cost"] for e in es if not e["failed"] and e["cost"] > 0
          and day_start(days[0]) <= e["signal_ms"] < day_start(days[-1]) + DAY_MS] if days else []
    if not allp:
        return {"n": 0}
    rng = np.random.default_rng(seed)
    sums, cnts = np.array([sum(b) for b in by]), np.array([len(b) for b in by])
    idx = rng.integers(0, len(by), size=(draws, len(by)))
    m = sums[idx].sum(axis=1) / np.maximum(cnts[idx].sum(axis=1), 1)
    return {"n": len(allp), "trades": len(tr), "mean_sol": float(np.mean(allp)), "lo": float(np.quantile(m, 0.05)),
            "hi": float(np.quantile(m, 0.95)), "per_trade": float(np.mean(tr)) if tr else None,
            "per_day": [float(sum(b)) for b in by]}


def picks(rows: list[dict], start: float = STARTS[0]) -> dict:
    """(a) the highest median wallet after HORIZON days, (b) the highest chance to double before -80 %, (c) the
    lowest chance of ruin with a median above the start; distinct, a repeat taking the next of its own order."""
    rs = [r for r in rows if r["start"] == start]
    key = lambda r: (r["strategy"], r["share"], r["max_open"], r["brake"])
    orders = {"a": sorted(rs, key=lambda r: (-r["median"], -r["p_double"])),
              "b": sorted(rs, key=lambda r: (-r["p_double"], -r["median"])),
              "c": sorted([r for r in rs if r["median"] > r["start"]], key=lambda r: (r["p_ruin"], -r["median"]))}
    out, seen = {}, set()
    for k in ("a", "b", "c"):
        for r in orders[k]:
            if key(r) not in seen:
                out[k] = r
                seen.add(key(r))
                break
    return out


def book_name(r: dict) -> str:
    """A paper book's name: the strategy, the share, the slots, b with the brake or n without."""
    return f"{r['strategy']}_sw{int(round(r['share'] * 100))}o{r['max_open']}{'b' if r['brake'] else 'n'}"


# ---------------------------------------------------------------- the report

def _eur(sol: float) -> str:
    return f"{sol * EUR_PER_SOL:.0f}"


def markdown(res: dict) -> str:
    rows, ex, days = res["rows"], res["expectation"], res["oos_days"]

    def line(r):
        d = "n/a" if not math.isfinite(r["days_target"]) else f"{r['days_target']:.0f}"
        return (f"| {r['strategy']} | {r['share'] * 100:.0f} % | {r['max_open']} | {'on' if r['brake'] else 'off'} | "
                f"{r['median']:.2f} ({_eur(r['median'])}) | {r['p10']:.2f} to {r['p90']:.2f} | {r['mean']:.2f} | "
                f"{r['p_double'] * 100:.0f} % | {r['p_ruin'] * 100:.0f} % | {d} ({r['p_target'] * 100:.0f} %) |")
    head = ["| strategy | share | max open | brake | median SOL after 30 days (EUR) | 10 to 90 % | mean | 2x before "
            "-80 % | ruin | days to target (paths there) |", "|---|---|---|---|---|---|---|---|---|---|"]
    md = [f"Out of sample: {', '.join(days)} ({len(days)} days). {PATHS:,} paths of {HORIZON} days, days drawn with "
          f"replacement. 1 SOL = {EUR_PER_SOL:g} EUR.", "",
          "Per entry at 0.1 SOL (failed buys and skips included), realistic execution:", "",
          "| strategy | entries | closed | mean P&L per entry SOL | 90 % band | mean per trade | P&L per day SOL |",
          "|---|---|---|---|---|---|---|"]
    for name in CANDIDATES:
        e = ex.get(name) or {}
        if not e.get("n"):
            md.append(f"| {name} | 0 | | | | | |")
            continue
        md.append(f"| {name} | {e['n']} | {e['trades']} | {e['mean_sol']:+.4f} | {e['lo']:+.4f} to {e['hi']:+.4f} | "
                  f"{'' if e['per_trade'] is None else format(e['per_trade'] * 100, '+.1f') + ' %'} | "
                  f"{', '.join(format(x, '+.2f') for x in e['per_day'])} |")
    for w in STARTS:
        rs = [r for r in rows if r["start"] == w]
        md += ["", f"Start {w} SOL ({_eur(w)} EUR), target {TARGET_EUR[w]:.0f} EUR: the ten highest medians", "",
               *head, *[line(r) for r in sorted(rs, key=lambda r: -r["median"])[:10]], "",
               f"Start {w} SOL: the ten highest chances to double before -80 %", "", *head,
               *[line(r) for r in sorted(rs, key=lambda r: -r["p_double"])[:10]], "",
               f"Start {w} SOL: the best setting of each strategy by its median", "", *head,
               *[line(max((r for r in rs if r["strategy"] == n), key=lambda r: r["median"]))
                 for n in CANDIDATES if any(r["strategy"] == n for r in rs)]]
    pk = res.get("picks") or {}
    md += ["", "The picks (start 0.55 SOL): " + "; ".join(
        f"{k}) {book_name(r)}: median {r['median']:.2f} SOL, 2x {r['p_double'] * 100:.0f} %, ruin "
        f"{r['p_ruin'] * 100:.0f} %" for k, r in pk.items())]
    return "\n".join(md) + "\n"


def run(out: Path | None = None, until_ms: int = UNTIL_MS, log=print, paths: int = PATHS) -> dict:
    rep = replay(until_ms=until_ms, log=log)
    if rep.get("empty"):
        return rep
    days = oos_days(rep["days"], rep["trained"], until_ms)
    log(f"r2: out of sample {days}")
    rows = search(rep["entries"], days, paths=paths, log=log) if days else []
    res = {"days": rep["days"], "oos_days": days, "trained": rep["trained"], "fit": rep["fit"], "rows": rows,
           "expectation": {n: expectation(e, days) for n, e in rep["entries"].items()}, "skipped": rep["skipped"],
           "gaps": rep["gaps"], "picks": picks(rows)}
    if out is not None:
        out.mkdir(parents=True, exist_ok=True)
        (out / "smallwallet.md").write_text(markdown(res), encoding="utf-8")
        (out / "smallwallet.json").write_text(json.dumps(res, default=str), encoding="utf-8")
        (out / "smallwallet_entries.json").write_text(json.dumps(rep["entries"], default=str), encoding="utf-8")
    return res


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="lab.pumpfun_rt.smallwallet")
    ap.add_argument("cmd", nargs="?", default="run", choices=("run",))
    ap.add_argument("--out", default=None)
    ap.add_argument("--paths", type=int, default=PATHS)
    a = ap.parse_args(sys.argv[1:] if argv is None else argv)
    res = run(Path(a.out) if a.out else R.reports_dir(), paths=a.paths)
    if res.get("empty"):
        print("r2: no recorded days")
        return 1
    print(markdown(res))
    return 0


if __name__ == "__main__":
    sys.exit(main())
