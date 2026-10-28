"""T9: the allocator weighted by posterior against drawn against equal, replayed over the recorded history. PAPER ONLY.

    python -m lab.pumpfun_rt.allocator_t9 run --out DIR [--replay FILE]

Pre-registered in results/allocator_t9_prereg.md. Two histories, each day decided on the days before it only:
  replay   R2's realistic replay of the record to UNTIL_MS at the live latency (smallwallet.replay, as A1 ran it;
           --replay reads a saved one, a run saves its own as replay.json), A1's test days (adaptive_a1.alloc_days)
  paper    the collector's realistic paper books since realistic_since, the full days before UNTIL_MS
Three policies on the same daily rewards (allocator.day_rewards, log growth at SHARE a trade):
  weighted the wallet split by allocator.decide's weights (mode "weighted": exact P(best), shared entries 1 / k)
  drawn    A1 as it ran (mode "drawn": one Thompson draw seeded by the day); also its band over SEEDS draws
  equal    the wallet split equally over the arms, no guard
Bands: 90 % over BOOT resamples of the days. DSR (R5's convention: higher is better, pass at 0.95) of the daily
difference weighted less drawn and weighted less equal over the registry's pool of all with this study's trials, and
over the study's own comparisons; the comparisons are trials in R5's registry (hand:t9:...), registered before any
number exists. Nothing here touches a paper book, the live bot or a wallet.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from .. import metrics
from . import adaptive_a1 as AA
from . import allocator as A

UNTIL_MS = int(datetime(2026, 10, 28, tzinfo=timezone.utc).timestamp() * 1000)
HISTORIES = ("replay", "paper")
POLICIES = ("weighted", "drawn", "equal")
VERSUS = ("drawn", "equal")
SEEDS = 1000
BOOT, BOOT_SEED, LEVEL = 10_000, 9, 0.90
MIN_DAYS = AA.MIN_ALLOC_DAYS
PASS = 0.95
SOURCE = "results/allocator_t9_prereg.md"


def trials() -> list[dict]:
    return [{"id": f"hand:t9:{h}:weighted_vs_{v}", "family": "hand", "n": 1, "sharpe": None, "source": SOURCE}
            for h in HISTORIES for v in VERSUS]


def policies(rewards: dict[str, dict[str, float]], shares: dict[str, dict[str, float]], days: list[str],
             seeds: int = SEEDS) -> dict:
    """Per day the three policies' rewards, the weights of both allocators and the drawn one's band over seeds."""
    arms = list(rewards)
    per_day, drawn_w = [], []
    for i, d in enumerate(days):
        w = A.decide(rewards, days[:i], d, shares=shares, mode="weighted")
        dr = A.decide(rewards, days[:i], d, mode="drawn")
        pick = dr["choice"]
        per_day.append({"day": d, "weighted": A.split_reward(w, rewards, d),
                        "drawn": rewards[pick][d] if pick else 0.0,
                        "equal": float(math.log(sum(math.exp(rewards[a][d]) for a in arms) / len(arms))),
                        "weights": {a: v["weight"] for a, v in w["arms"].items()}, "pick": pick,
                        "drawn_weights": {a: v["weight"] for a, v in dr["arms"].items()},
                        "arms": {a: rewards[a][d] for a in arms}})
        drawn_w.append([dr["arms"][a]["weight"] for a in arms])
    rng = np.random.default_rng(BOOT_SEED)
    tot = np.zeros(seeds)
    for x, w in zip(per_day, drawn_w):                      # the draw again with other seeds, the weights as they were
        w = np.array(w)
        if w.sum() > 0:
            k = rng.choice(len(arms), size=seeds, p=w / w.sum())
            tot += np.array([x["arms"][a] for a in arms])[k]
    return {"per_day": per_day, "drawn_seeds": tot}


def band(x: np.ndarray, boot: int = BOOT, level: float = LEVEL, seed: int = BOOT_SEED) -> tuple[float, float]:
    """The 90 % band of the sum of daily values over resampled days."""
    if len(x) == 0:
        return (math.nan, math.nan)
    rng = np.random.default_rng(seed)
    s = x[rng.integers(0, len(x), size=(boot, len(x)))].sum(axis=1)
    q = (1 - level) / 2
    return (float(np.quantile(s, q)), float(np.quantile(s, 1 - q)))


def assess(rewards: dict[str, dict[str, float]], shares: dict[str, dict[str, float]], days: list[str],
           pool: dict) -> dict:
    p = policies(rewards, shares, days)
    s = {k: np.array([x[k] for x in p["per_day"]]) for k in POLICIES}
    ds = p["drawn_seeds"]
    out = {"days": days, "per_day": p["per_day"],
           "total": {k: float(v.sum()) for k, v in s.items()},
           "band": {k: band(v) for k, v in s.items()},
           "drawn_seed_band": (float(np.quantile(ds, 0.05)), float(np.quantile(ds, 0.95))) if len(days) else None,
           "drawn_seed_mean": float(ds.mean()) if len(days) else None,
           "arms": {a: float(sum(rewards[a][d] for d in days)) for a in rewards}, "vs": {}}
    for v in VERSUS:
        x = s["weighted"] - s[v]
        r = AA.sharpe(x)
        r.update(total=float(x.sum()), band=band(x), dsr_all=metrics.dsr(x, pool) if len(x) > 1 else 0.0)
        out["vs"][v] = r
    out["enough_days"] = len(days) >= MIN_DAYS
    return out


def verdict(h: dict) -> bool:
    """Weighted beats drawn: enough days, DSR over the pool of all at 0.95 or more, the band above 0."""
    r = h["vs"]["drawn"]
    return bool(h["enough_days"] and r["dsr_all"] >= PASS and r["band"][0] > 0)


def paper_history(paper: Path | None = None, until_ms: int = UNTIL_MS,
                  taint: dict | None = None) -> tuple[dict, dict, list[str]]:
    """The arms' realistic paper rewards and shares; the late-row bug's trades (P1) skipped, counted in `taint`."""
    from . import realistic as R
    from .live import paper_dir
    paper = paper or paper_dir()
    since = float((R.read_json(paper / "state.json") or {}).get("realistic_since") or 0)
    days = A.full_days(since, until_ms) if since else []
    tr = A.paper_trades(paper, since, taint=taint)
    return A.day_rewards(tr, days), A.day_shares(tr, days), days


def replay_history(rep: dict, until_ms: int = UNTIL_MS) -> tuple[dict, dict, list[str]]:
    days = AA.alloc_days(rep, until_ms)
    tr = AA.entry_trades(rep["entries"])
    return A.day_rewards(tr, days), A.day_shares(tr, days), days


def study(hist: dict[str, tuple[dict, dict, list[str]]], register: bool = True, log=print) -> dict:
    tr = trials()
    if register:
        try:
            metrics.register(tr)                               # before any number exists
        except OSError as e:
            log(f"t9: the registry could not be written ({e}); the trials count when it can")
    pool = metrics.trial_pool(None, extra=tr)
    res = {h: assess(*v, pool) for h, v in hist.items()}
    comps = [r for h in res.values() for r in h["vs"].values()]
    AA.deflate(comps)                                         # "dsr" over the study's own comparisons
    for h in res.values():
        h["verdict"] = verdict(h)
    return {"histories": res, "pool": {"n_trials": pool["n_trials"], "sr0_annual": pool["sr0_annual"]},
            "trials": len(tr)}


# ---------------------------------------------------------------- the report

def _pc(x: float) -> str:
    return f"{x * 100:+.1f} %" if x is not None and math.isfinite(x) else "n/a"


def markdown(res: dict, run: str) -> str:
    md = ["# T9 allocator weighted by posterior: the replay", "",
          f"Run {run}. Pre-registration `{SOURCE}`. Reward: the day's log growth of a wallet at {A.SHARE * 100:g} % a "
          f"trade; weighted splits the wallet by the posterior weights (an entry shared by k strategies counted 1 / k "
          f"in each), drawn is A1's one draw a day, equal splits it in thirds. Bands 90 % over resampled days. DSR in "
          f"R5's convention (higher is better, pass at 0.95), over the registry's pool of all ({res['pool']['n_trials']:,}"
          f" trials, bar {res['pool']['sr0_annual']:.2f} a year) and over this study's {res['trials']} comparisons.", ""]
    for name, h in res["histories"].items():
        md += [f"## {name} ({len(h['days'])} days{', ' + h['days'][0] + ' to ' + h['days'][-1] if h['days'] else ''})",
               ""]
        if not h["days"]:
            md += ["No days.", ""]
            continue
        md += ["| day | " + " | ".join(A.ARMS) + " | weights (" + ", ".join(a.replace("P_pool", "") for a in A.ARMS)
               + ") | weighted | drawn (pick) | equal |", "|---|" + "---|" * (len(A.ARMS) + 4)]
        for x in h["per_day"]:
            md.append(f"| {x['day']} | " + " | ".join(_pc(x['arms'].get(a, math.nan)) for a in A.ARMS)
                      + " | " + " / ".join(f"{x['weights'].get(a, 0) * 100:.0f}" for a in A.ARMS)
                      + f" | {_pc(x['weighted'])} | {_pc(x['drawn'])} ({x['pick'] or 'out'}) | {_pc(x['equal'])} |")
        md += ["", "| policy | total log growth | band |", "|---|---|---|"]
        for k in POLICIES:
            md.append(f"| {k} | {_pc(h['total'][k])} | {_pc(h['band'][k][0])} to {_pc(h['band'][k][1])} |")
        md.append(f"| drawn, other seeds | {_pc(h['drawn_seed_mean'])} (mean) | {_pc(h['drawn_seed_band'][0])} to "
                  f"{_pc(h['drawn_seed_band'][1])} |")
        md += ["", "Arms alone: " + ", ".join(f"{a} {_pc(v)}" for a, v in h["arms"].items()) + ".", "",
               "| weighted less | total | band | daily Sharpe | DSR (pool of all) | DSR (study) |", "|---|---|---|---|---|---|"]
        for v, r in h["vs"].items():
            md.append(f"| {v} | {_pc(r['total'])} | {_pc(r['band'][0])} to {_pc(r['band'][1])} | {r['sharpe']:+.2f} | "
                      f"{r['dsr_all']:.3f} | {r['dsr']:.3f} |")
        md += ["", f"Weighted beats drawn: **{'yes' if h['verdict'] else 'no'}** (enough days: "
                   f"{'yes' if h['enough_days'] else 'no'}, {len(h['days'])} of {MIN_DAYS}).", ""]
    md += A.taint_line(res.get("tainted"))[1:]
    return "\n".join(md)


def run(out: Path, replay: Path | None = None, log=print) -> dict:
    if replay is not None:
        rep = json.loads(replay.read_text(encoding="utf-8"))
    else:
        from . import smallwallet as SW
        rep = SW.replay(until_ms=UNTIL_MS, log=log)
        out.mkdir(parents=True, exist_ok=True)
        (out / "replay.json").write_text(json.dumps(rep, default=str), encoding="utf-8")
    bad: dict[str, int] = {}
    res = study({"replay": replay_history(rep), "paper": paper_history(taint=bad)}, log=log)
    res["tainted"] = bad
    run_day = A.day_of(time.time() * 1000)
    out.mkdir(parents=True, exist_ok=True)
    (out / "allocator_t9.json").write_text(json.dumps(AA.jsonable(res), indent=1, default=str), encoding="utf-8")
    (out / "allocator_t9.md").write_text(markdown(res, run_day), encoding="utf-8")
    return res


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="lab.pumpfun_rt.allocator_t9")
    ap.add_argument("cmd", nargs="?", default="run", choices=("run",))
    ap.add_argument("--out", required=True)
    ap.add_argument("--replay", default=None)
    a = ap.parse_args(sys.argv[1:] if argv is None else argv)
    res = run(Path(a.out), Path(a.replay) if a.replay else None)
    print(markdown(res, A.day_of(time.time() * 1000)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
