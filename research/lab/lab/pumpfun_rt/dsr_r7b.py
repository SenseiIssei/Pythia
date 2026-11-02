"""R7b (results/dsr_bar_r7b_prereg.md): the pump.fun DSR per entry with F3's trial variance net of each trial's
sampling noise and an effective trial count. PAPER ONLY: reads F3's ledger, changes nothing a live bot, a wallet or
the engine reads. The simulation failed (results/dsr_bar_r7b.md): PASSED is False and the ladder keeps R7's bar.

  V_new = max(V_raw - M, M): V_raw the variance of the Sharpes per entry of F3's trials with MIN_ENTRIES, M the mean
          of their sampling variances q_i / n_i (q_i the fat-tail term of metrics.deflated_sharpe, n_i the entries)
  N_eff = clusters of F3's trials: the ones with no entries one cluster, the ones without EFF_MIN_DAYS of day P&L one
          each, the rest by average linkage on 1 - the correlation of their day P&L net of the market day (each series
          standardized, the mean standardized day taken out by a slope per trial), cut at 1 - EFF_CORR

    python -m lab.pumpfun_rt.dsr_r7b --sim [--reps 200] [--out /out/r7b_sim.json]   the simulation (c)
    python -m lab.pumpfun_rt.dsr_r7b --real [--root DIR] [--out ...]                old and new per candidate
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

PREREG = "results/dsr_bar_r7b_prereg.md"
MIN_ENTRIES = 20                           # factory.MIN_ENTRIES
EFF_CORR = 0.9                             # two trials whose residual day P&L correlates above this are one bet
EFF_MIN_DAYS = 5                           # days of P&L (and shared days) a trial needs to be clustered
SHARE = 0.8                                # a copy shares this much of its genome's entries
LOGN_SIGMA = 0.44                          # minus a lognormal, standardized: skew -1.46, kurtosis about 7.2
SEED = 20261102
REPS = 200
FALSE_MAX = 0.05
SHAPES = [(c, rho, t) for c in (1, 5, 25) for rho in (0.0, 0.1, 0.3) for t in ("normal", "f3")]
SMALL = (100, 5, 0.1, "f3")                # (trials, C, rho, tails) of the small family
REF = (5, 0.1, "f3")                       # the shape of the power runs
PLANTED = (0.25, 0.5)                      # in sample: one genome's true Sharpe per entry
FORWARD = (0.05, 0.1, 0.2, 0.3)            # forward: the candidate's true Sharpe per entry
FWD_ENTRIES, FWD_DAYS = 1_000, 10
PASSED = False                             # (c) failed on 2026-11-02 (results/dsr_bar_r7b.md): 16 of 19 shapes over 5 %


def _q(r: dict) -> float:
    s = float(r.get("sharpe", 0.0))
    q = 1 - float(r.get("skew", 0.0)) * s + (float(r.get("kurt", 3.0)) - 1) / 4 * s ** 2
    return q if q > 0 else 1.0


def noise_var(trials: list[dict]) -> dict:
    """(a): V_raw, M and V_new over the trials with MIN_ENTRIES entries and a finite Sharpe."""
    tr = [r for r in trials if r.get("entries", 0) >= MIN_ENTRIES and math.isfinite(float(r.get("sharpe", 0.0)))]
    if len(tr) < 2:
        return {"used": len(tr), "v_raw": 0.0, "m": 0.0, "v_new": 0.0}
    v = float(np.var([float(r["sharpe"]) for r in tr], ddof=1))
    m = float(np.mean([_q(r) / r["entries"] for r in tr]))
    return {"used": len(tr), "v_raw": v, "m": m, "v_new": max(v - m, m)}


def _resid(trials: list[dict]) -> tuple[list[list[str]], list[np.ndarray]]:
    """The day P&L of each trial standardized, net of the market day (a least-squares slope per trial)."""
    zs = []
    for r in trials:
        x = np.asarray(r["day_pnl"], dtype=float)
        zs.append(dict(zip(r["days"], (x - x.mean()) / x.std())))
    days = sorted({d for z in zs for d in z})
    mkt = {d: float(np.mean([z[d] for z in zs if d in z])) for d in days}
    out = []
    for z in zs:
        y = np.array(list(z.values()))
        m = np.array([mkt[d] for d in z])
        b = float(y @ m / (m @ m)) if float(m @ m) > 0 else 0.0
        out.append(y - b * m)
    return [list(z) for z in zs], out


def effective_trials(trials: list[dict]) -> dict:
    """(b): {"trials", "flat", "singles", "clustered", "clusters", "n_eff"} of F3's trials."""
    from scipy.cluster.hierarchy import fcluster, linkage
    flat = [r for r in trials if r.get("entries", 0) <= 0]
    ok = [r for r in trials if r.get("entries", 0) >= MIN_ENTRIES and len(r.get("day_pnl") or ()) >= EFF_MIN_DAYS
          and len(r["day_pnl"]) == len(r.get("days") or ()) and sum(v != 0 for v in r["day_pnl"]) >= EFF_MIN_DAYS
          and float(np.std(r["day_pnl"])) > 0]
    singles = len(trials) - len(flat) - len(ok)
    k = 0
    if len(ok) == 1:
        k = 1
    elif ok:
        days, res = _resid(ok)
        groups: dict[tuple, list[int]] = {}                  # trials of one night share their days
        for i, d in enumerate(days):
            groups.setdefault(tuple(d), []).append(i)
        C = np.zeros((len(ok), len(ok)))
        keys = list(groups)
        for a in range(len(keys)):
            for b in range(a, len(keys)):
                shared = [d for d in keys[a] if d in set(keys[b])]
                if len(shared) < EFF_MIN_DAYS:
                    continue
                ia, ib = groups[keys[a]], groups[keys[b]]
                pa, pb = [keys[a].index(d) for d in shared], [keys[b].index(d) for d in shared]
                A = np.array([res[i][pa] for i in ia])
                B = np.array([res[i][pb] for i in ib])
                A = A - A.mean(1, keepdims=True)
                B = B - B.mean(1, keepdims=True)
                na, nb = np.linalg.norm(A, axis=1), np.linalg.norm(B, axis=1)
                with np.errstate(invalid="ignore", divide="ignore"):
                    c = np.nan_to_num((A @ B.T) / np.outer(na, nb))
                C[np.ix_(ia, ib)] = c
                C[np.ix_(ib, ia)] = c.T
        D = np.clip(1 - C[np.triu_indices(len(ok), 1)], 0, 2)
        k = int(fcluster(linkage(D, "average"), t=1 - EFF_CORR, criterion="distance").max())
    return {"trials": len(trials), "flat": len(flat), "singles": singles, "clustered": len(ok), "clusters": k,
            "n_eff": k + singles + (1 if flat else 0)}


def pool(ledger: list[dict]) -> dict:
    """V_raw, M, V_new, F3's trial count and N_eff from F3's ledger (factory.trials_of)."""
    from . import factory as F
    tr = F.trials_of(ledger)
    e = effective_trials(tr)
    return {**noise_var(tr), "n_f3": len(tr), "n_eff_f3": e["n_eff"], "eff": e}


def sr0(var: float, n: int) -> float:
    from ..metrics import expected_max_sharpe
    return expected_max_sharpe(var, n)


def deflated(r: dict, var: float, n: int) -> float:
    """factory.deflated with the variance given: the DSR per entry on the effective entries by day."""
    from ..metrics import deflated_sharpe
    n_obs = float(r.get("n_eff", r.get("entries", 0)))
    if r.get("entries", 0) < 2 or n_obs < 2 or n < 1:
        return 0.0
    try:
        return deflated_sharpe(r["sharpe"], n_obs, n, var, r.get("skew", 0.0), r.get("kurt", 3.0))
    except ValueError:
        return 0.0


# ---------------------------------------------------------------- the simulation (c)

def shape_of(ledger: list[dict]) -> dict:
    """F3's shape: the nights (trials, days, whether day P&L is stored), the entries per trial, skew and kurtosis."""
    from . import factory as F
    tr = F.trials_of(ledger)
    nights: dict[str, list] = {}
    for r in tr:
        x = nights.setdefault(r.get("night", ""), [0, len(r.get("days") or ()), False])
        x[0] += 1
        x[2] = x[2] or "day_pnl" in r
    used = [r for r in tr if r.get("entries", 0) >= MIN_ENTRIES]
    return {"nights": [tuple(v) for _, v in sorted(nights.items())], "entries": [int(r.get("entries", 0)) for r in tr],
            "skew": float(np.median([r.get("skew", 0.0) for r in used])) if used else 0.0,
            "kurt": float(np.median([r.get("kurt", 3.0) for r in used])) if used else 3.0}


def _noise(rng, n: int, tails: str) -> np.ndarray:
    if tails == "normal":
        return rng.standard_normal(n)
    s2 = LOGN_SIGMA ** 2
    m, sd = math.exp(s2 / 2), math.sqrt((math.exp(s2) - 1) * math.exp(s2))
    return -(np.exp(LOGN_SIGMA * rng.standard_normal(n)) - m) / sd


def _stats(x: np.ndarray, day: np.ndarray, n_days: int) -> dict:
    from . import factory as F
    n = len(x)
    if n < 2:
        return {"entries": n, "sharpe": 0.0, "skew": 0.0, "kurt": 3.0, "n_eff": float(n)}
    sd = float(x.std(ddof=1))
    if sd <= 0:
        return {"entries": n, "sharpe": 0.0, "skew": 0.0, "kurt": 3.0, "n_eff": float(n)}
    m = float(x.mean())
    return {"entries": n, "sharpe": m / sd, "skew": float(((x - m) ** 3).mean() / sd ** 3),
            "kurt": float(((x - m) ** 4).mean() / sd ** 4), "n_eff": F.by_day(x, day, n_days)["n_eff"]}


def family(shape: dict, c: float, rho: float, tails: str, rng, k: int | None = None,
           edge: float = 0.0) -> list[dict]:
    """One synthetic F3 family: shape's nights (scaled to k trials), entries resampled, genomes with copies (C), a
    market day at rho, the tails; with edge, the first trial's genome has that true Sharpe per entry."""
    nights = shape["nights"]
    tot = sum(n for n, _, _ in nights)
    if k is not None and k != tot:
        nights = [(max(1, round(n * k / tot)), d, s) for n, d, s in nights]
    n_days = max(d for _, d, _ in nights)
    mkt = rng.standard_normal(n_days)
    w = math.sqrt(1 - rho ** 2)
    streams: list[dict[int, np.ndarray]] = []             # a genome's entries by day
    out, gen = [], []
    for n_tr, nd, stored in nights:
        for _ in range(n_tr):
            if streams and rng.random() < 1 - 1 / c:
                g = int(rng.integers(len(streams)))
            else:
                g = len(streams)
                streams.append({})
            gen.append(g)
            n = int(rng.choice(shape["entries"]))
            per = [n // nd + (d < n % nd) for d in range(nd)]
            xs, ds = [], []
            for d, kd in enumerate(per):
                if not kd:
                    continue
                s = streams[g].get(d, np.zeros(0))
                if len(s) < kd:
                    s = np.concatenate([s, _noise(rng, kd - len(s), tails)])
                    streams[g][d] = s
                sh = int(round(SHARE * kd))
                e = np.concatenate([s[:sh], _noise(rng, kd - sh, tails)])
                xs.append(rho * mkt[d] + w * e + (edge if g == 0 and edge else 0.0))
                ds.append(np.full(kd, d))
            x = np.concatenate(xs) if xs else np.zeros(0)
            day = np.concatenate(ds) if ds else np.zeros(0, dtype=int)
            r = _stats(x, day.astype(int), nd)
            r["days"] = [f"d{d}" for d in range(nd)]
            if stored:
                r["day_pnl"] = [float(v) for v in np.bincount(day.astype(int), weights=x, minlength=nd)]
            r["genome"] = g
            out.append(r)
    return out


def judge(fam: list[dict], extra_n: int = 0) -> dict:
    """The family's best trial (MIN_ENTRIES) judged in sample on the old bar and the new one."""
    nv = noise_var(fam)
    e = effective_trials(fam)
    used = [r for r in fam if r["entries"] >= MIN_ENTRIES]
    best = max(used, key=lambda r: r["sharpe"]) if used else None
    n_old, n_new = len(fam) + extra_n, e["n_eff"] + extra_n
    return {"v_raw": nv["v_raw"], "v_new": nv["v_new"], "n_old": n_old, "n_new": n_new,
            "sr0_old": sr0(nv["v_raw"], n_old), "sr0_new": sr0(nv["v_new"], n_new),
            "dsr_old": deflated(best, nv["v_raw"], n_old) if best else 0.0,
            "dsr_new": deflated(best, nv["v_new"], n_new) if best else 0.0,
            "best_genome": best["genome"] if best else None}


def forward(rng, sr: float, rho: float = 0.1, tails: str = "f3") -> dict:
    """A forward candidate: FWD_ENTRIES entries over FWD_DAYS days, true Sharpe per entry sr."""
    day = np.repeat(np.arange(FWD_DAYS), FWD_ENTRIES // FWD_DAYS)
    x = sr + rho * rng.standard_normal(FWD_DAYS)[day] + math.sqrt(1 - rho ** 2) * _noise(rng, len(day), tails)
    return _stats(x, day, FWD_DAYS)


def false_rate(shape: dict, c: float, rho: float, tails: str, reps: int, seed: int = SEED,
               k: int | None = None) -> dict:
    """The zero-edge rows of (c): false pass rates of both bars, mean N_eff against the true genome count, SR0."""
    rng = np.random.default_rng(seed)
    js, g = [], []
    for _ in range(reps):
        f = family(shape, c, rho, tails, rng, k)
        g.append(len({r["genome"] for r in f}))
        js.append(judge(f))
    return {"c": c, "rho": rho, "tails": tails, "trials": len(f), "reps": reps,
            "false_old": float(np.mean([j["dsr_old"] >= 0.95 for j in js])),
            "false_new": float(np.mean([j["dsr_new"] >= 0.95 for j in js])),
            "genomes": float(np.mean(g)), "n_eff": float(np.mean([j["n_new"] for j in js])),
            "sr0_old": float(np.mean([j["sr0_old"] for j in js])), "sr0_new": float(np.mean([j["sr0_new"] for j in js])),
            "v_raw": float(np.mean([j["v_raw"] for j in js])), "v_new": float(np.mean([j["v_new"] for j in js]))}


def _planted(shape: dict, mu: float, reps: int, seed: int) -> dict:
    c, rho, t = REF
    rng = np.random.default_rng(seed)
    js = [judge(family(shape, c, rho, t, rng, edge=mu)) for _ in range(reps)]
    return {"sr": mu, "power_old": float(np.mean([x["dsr_old"] >= 0.95 and x["best_genome"] == 0 for x in js])),
            "power_new": float(np.mean([x["dsr_new"] >= 0.95 and x["best_genome"] == 0 for x in js]))}


def simulate(shape: dict, reps: int = REPS, extra_n: int = 0, log=print, workers: int = 1) -> dict:
    """(c): every shape on its own seed (SEED + its index), so the workers change nothing but the time."""
    from concurrent.futures import ProcessPoolExecutor
    k, c0, rho0, t0 = SMALL
    jobs = [(false_rate, (shape, c, rho, t, reps, SEED + i)) for i, (c, rho, t) in enumerate(SHAPES)]
    jobs += [(false_rate, (shape, c0, rho0, t0, reps, SEED + 99, k))]
    jobs += [(_planted, (shape, mu, reps, SEED + 200 + j)) for j, mu in enumerate(PLANTED)]
    with ProcessPoolExecutor(max(1, workers)) as ex:
        res = [f.result() for f in [ex.submit(fn, *a) for fn, a in jobs]]
    for r in res:
        log(json.dumps(r))
    rows, planted = res[:len(SHAPES) + 1], res[len(SHAPES) + 1:]
    c, rho, t = REF
    rng = np.random.default_rng(SEED + 300)
    nulls = []
    for _ in range(reps):
        f = family(shape, c, rho, t, rng)
        nv, e = noise_var(f), effective_trials(f)
        nulls.append((nv["v_raw"], len(f) + extra_n, nv["v_new"], e["n_eff"] + extra_n))
    fwd = []
    for mu in FORWARD:
        cs = [forward(rng, mu) for _ in range(reps)]
        fwd.append({"sr": mu, "power_old": float(np.mean([deflated(x, a, b) >= 0.95 for x, (a, b, _, _) in
                                                          zip(cs, nulls)])),
                    "power_new": float(np.mean([deflated(x, v, n) >= 0.95 for x, (_, _, v, n) in zip(cs, nulls)]))})
        log(json.dumps(fwd[-1]))
    return {"shapes": rows, "planted": planted, "forward": fwd, "extra_n": extra_n,
            "passed": all(r["false_new"] <= FALSE_MAX for r in rows)}


def main(argv: list[str] | None = None) -> int:
    from . import factory as F
    ap = argparse.ArgumentParser(prog="lab.pumpfun_rt.dsr_r7b", description=__doc__.split("\n")[0])
    ap.add_argument("--sim", action="store_true")
    ap.add_argument("--real", action="store_true")
    ap.add_argument("--reps", type=int, default=REPS)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--root", default="/data")
    ap.add_argument("--out", default=None)
    a = ap.parse_args(sys.argv[1:] if argv is None else argv)
    root = Path(a.root)
    led = F.read_ledger(root / "pumpfun_rt" / "factory" / "ledger.jsonl")
    out: dict = {"shape": shape_of(led), "pool": {k: v for k, v in pool(led).items()}}
    if a.sim:
        from .. import metrics
        from ..ops import ladder
        extra = metrics.trial_pool(extra=ladder.pf_trials())["n_trials"]
        out["sim"] = simulate(out["shape"], a.reps, extra, workers=a.workers)
    if a.real:
        from ..ops import ladder
        from ..ops import notify
        out["real"] = ladder.pf_context(root, notify.clock_ms())["rules"]
    text = json.dumps(out, default=float, indent=1)
    if a.out:
        Path(a.out).write_text(text, encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
