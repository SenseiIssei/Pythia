"""A1: does the selector beat the best single model, does the allocator beat the best single strategy? PAPER ONLY.

    python -m lab.pumpfun_rt.adaptive_a1 run --out DIR [--replay FILE]

Pre-registered in results/pumpfun_adaptive_a1_prereg.md. Test 1 (models): the zoo (zoo.py) walked forward by UTC day
over the study's rows, the selector's rules (selector.choose, blend, isotonic out of fold) replayed day by day, against
the best single member in hindsight on the scored days. Test 2 (strategies): the allocator (allocator.decide) day by
day on the realistic replay of the record (smallwallet.replay, R1's model fitted to the live orders: the live
latency), against the best single arm in hindsight. Both deflated (metrics.deflated_sharpe) by the study's number of
comparisons. --replay reads a saved replay (its "days", "trained" and "entries") instead of replaying.
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

from . import allocator as A
from . import selector as S
from . import zoo as Z

UNTIL = "2026-10-26"                               # the record's last full day is the one before
UNTIL_MS = int(datetime(2026, 10, 26, tzinfo=timezone.utc).timestamp() * 1000)
PASS_P = 0.95
PASS_LABELS = 4
MIN_ALLOC_DAYS = 10
STAKE_SOL = 0.1


# ---------------------------------------------------------------- test 1: the selector

def selector_days(tab: dict, days: list[str], log=print) -> list[dict]:
    """The walk-forward of every member, the selector's pick, its calibrated probabilities and every candidate's
    probabilities (the blend's from the days before) per test day."""
    out, hist = [], []
    for i, x in enumerate(S.walk(tab, days, log=log)):
        prior = [o["raw"] for o in out][-S.N_DAYS:]
        ch = S.choose(hist) if hist else {"pick": Z.INCUMBENT, "retired": {}}
        p_sel, info = S.selected(x, prior, ch["pick"], ch["retired"])
        ps = S.with_blend(x, prior, ch["retired"])
        hist.append(S.stats(x["day"], ps, x["y"]))
        out.append({"day": x["day"], "raw": x, "pick": ch["pick"], "retired": dict(ch["retired"]),
                    "calibrated": info["calibrated"], "p_sel": p_sel, "p": ps, "y": x["y"], "t": x["t"],
                    "regime": x["regime"]})
    return out


def hourly(diff: np.ndarray, t: np.ndarray) -> np.ndarray:
    """Means of a per-row series per hour of decision time."""
    h = (t // S.HOUR_MS).astype(np.int64)
    u, inv = np.unique(h, return_inverse=True)
    return np.bincount(inv, weights=diff) / np.bincount(inv)


def sharpe(x: np.ndarray) -> dict:
    sd = float(np.std(x, ddof=1)) if len(x) > 1 else 0.0
    m = float(np.mean(x)) if len(x) else 0.0
    return {"n": int(len(x)), "mean": m, "sharpe": m / sd if sd > 0 else 0.0,
            "skew": float(((x - m) ** 3).mean() / sd ** 3) if sd > 0 else 0.0,
            "kurt": float(((x - m) ** 4).mean() / sd ** 4) if sd > 0 else 3.0}


def deflate(rows: list[dict]) -> None:
    """Adds "dsr" (the deflated probability) and "p" (1 - dsr) to each comparison, the trials being all of them."""
    from ..metrics import deflated_sharpe
    sh = [r["sharpe"] for r in rows if math.isfinite(r["sharpe"])]
    var = float(np.var(sh, ddof=1)) if len(sh) > 1 else 0.0
    for r in rows:
        try:
            r["dsr"] = deflated_sharpe(r["sharpe"], r["n"], len(rows), var, r["skew"], r["kurt"]) if r["n"] > 1 \
                else 0.0
        except ValueError:
            r["dsr"] = 0.0
        r["p"] = 1 - r["dsr"]


def model_test(rows: dict | None, sel: dict | None, until: str = UNTIL, log=print) -> dict:
    out = {"labels": {}, "comparisons": []}
    for label in S.LABELS:
        tab = S.table_for(label, rows, sel)
        if tab is None:
            out["labels"][label] = {"note": "no rows"}
            continue
        days = [d for d in sorted({S.day_of(x) for x in tab["t"]})[1:] if d < until]
        sd = selector_days(tab, days, log)
        scored = sd[1:]
        if not scored:
            out["labels"][label] = {"note": "fewer than two test days", "test_days": [x["day"] for x in sd]}
            continue
        y = np.concatenate([x["y"] for x in scored])
        t = np.concatenate([x["t"] for x in scored])
        ls = {"selector": Z.logloss_rows(np.concatenate([x["p_sel"] for x in scored]), y)}
        for c in scored[0]["p"]:
            if all(c in x["p"] for x in scored):
                ls[c] = Z.logloss_rows(np.concatenate([x["p"][c].astype(float) for x in scored]), y)
        members = [c for c in ls if c in Z.MEMBERS]
        best = min(members, key=lambda c: ls[c].mean())
        res = {"test_days": [x["day"] for x in sd], "scored_days": [x["day"] for x in scored], "rows": int(len(y)),
               "rate": float(y.mean()), "loss": {c: float(v.mean()) for c, v in ls.items()}, "best": best,
               "picks": {x["day"]: x["pick"] for x in sd}, "calibrated": {x["day"]: x["calibrated"] for x in sd},
               "retired": sd[-1]["retired"], "regimes": S.regime_table([x["raw"] for x in sd]),
               "per_day": {x["day"]: {c: float(Z.logloss_rows(p.astype(float), x["y"]).mean())
                                      for c, p in list(x["p"].items()) + [("selector", x["p_sel"])]} for x in sd}}
        for c in members:
            r = sharpe(hourly(ls[c] - ls["selector"], t))
            r.update(label=label, member=c, best=c == best)
            out["comparisons"].append(r)
        out["labels"][label] = res
    deflate(out["comparisons"])
    for label, res in out["labels"].items():
        if "best" in res:
            r = next(x for x in out["comparisons"] if x["label"] == label and x["best"])
            res["vs_best"] = {k: r[k] for k in ("n", "mean", "sharpe", "dsr", "p")}
            res["beats"] = bool(r["dsr"] >= PASS_P and r["mean"] > 0)
    n_beat = sum(1 for v in out["labels"].values() if v.get("beats"))
    out["trials"] = len(out["comparisons"])
    out["beats_labels"] = n_beat
    out["verdict"] = n_beat >= PASS_LABELS
    return out


# ---------------------------------------------------------------- test 2: the allocator

def entry_trades(entries: dict[str, list[dict]], arms=A.ARMS) -> dict[str, list[tuple[float, float]]]:
    """{arm: [(close ms, return over the 0.1 SOL stake)]}: closed trades and failed buys (their fee) alike."""
    return {a: [(float(e["exit_ms"]), float(e["pnl"]) / STAKE_SOL) for e in entries.get(a, [])] for a in arms}


def alloc_test(rewards: dict[str, dict[str, float]], days: list[str]) -> dict:
    """Each day the allocator decides on the days before it and earns its pick's reward (0 when it stays out)."""
    per_day = []
    for i, d in enumerate(days):
        res = A.decide(rewards, days[:i], d)
        pick = res["choice"]
        per_day.append({"day": d, "pick": pick, "reward": rewards[pick][d] if pick else 0.0,
                        "weighted": sum(v["weight"] * rewards[a][d] for a, v in res["arms"].items()),
                        "p_best": {a: v["p_best"] for a, v in res["arms"].items()},
                        "guarded": [a for a, v in res["arms"].items() if v["guarded"]]})
    alloc = np.array([x["reward"] for x in per_day])
    tot = {a: float(sum(rewards[a][d] for d in days)) for a in rewards}
    best = max(tot, key=tot.get) if tot else None
    comps = []
    for a in rewards:
        r = sharpe(alloc - np.array([rewards[a][d] for d in days]))
        r.update(arm=a, best=a == best)
        comps.append(r)
    deflate(comps)
    rb = next((r for r in comps if r["best"]), None)
    return {"days": days, "per_day": per_day, "total": tot, "allocator": float(alloc.sum()),
            "weighted": float(sum(x["weighted"] for x in per_day)), "best": best, "comparisons": comps,
            "vs_best": {k: rb[k] for k in ("n", "mean", "sharpe", "dsr", "p")} if rb else None,
            "verdict": bool(rb is not None and rb["dsr"] >= PASS_P and rb["mean"] > 0 and len(days) >= MIN_ALLOC_DAYS),
            "enough_days": len(days) >= MIN_ALLOC_DAYS}


def alloc_days(rep: dict, until_ms: int = UNTIL_MS) -> list[str]:
    """R2's out-of-sample rule for the arms: the full days on which every arm has its models."""
    from . import smallwallet as SW
    need = {m for c in A.ARMS for m in SW.NEEDS.get(c, ())}
    last = A.day_of(until_ms)
    first = next((d for d in rep["days"] if need <= set(rep["trained"].get(d) or ())), None)
    return [d for d in rep["days"] if first is not None and first <= d < last]


def forward(now_ms: int, log=print) -> dict:
    """The allocator on the collector's realistic paper books since they started (reported, not tested)."""
    from . import realistic as R
    from .live import paper_dir
    st = R.read_json(paper_dir() / "state.json") or {}
    since = float(st.get("realistic_since") or 0)
    days = A.full_days(since, now_ms) if since else []
    rw = A.day_rewards(A.paper_trades(paper_dir(), since), days)
    return {"since_ms": since, "days": days, "rewards": rw, "test": alloc_test(rw, days) if days else None}


# ---------------------------------------------------------------- the report

def _f(x, fmt="{:.4f}") -> str:
    return fmt.format(x) if Z.finite(x) else "n/a"


def markdown(res: dict) -> str:
    m, a = res["models"], res["alloc"]
    md = ["# A1 adaptive model zoo and strategy allocator: the run", "",
          f"Run {res['run']}. Pre-registration `results/pumpfun_adaptive_a1_prereg.md`.", "",
          f"## Test 1: selector against the best single model ({m['trials']} comparisons in the deflation)", "",
          "| label | scored days | rows | rate | selector | " + " | ".join(Z.MEMBERS) + " | blend | best | "
          "best less selector, per hour | deflated p | beats |", "|---|---|---|---|---|" + "---|" * len(Z.MEMBERS)
          + "---|---|---|---|---|"]
    for label, v in m["labels"].items():
        if "loss" not in v:
            md.append(f"| {label} | {v.get('note')} |" + " |" * (len(Z.MEMBERS) + 9))
            continue
        vb = v["vs_best"]
        md.append(f"| {label} | {len(v['scored_days'])} | {v['rows']:,} | {v['rate']:.3f} | "
                  f"{_f(v['loss']['selector'])} | " + " | ".join(_f(v["loss"].get(c)) for c in Z.MEMBERS)
                  + f" | {_f(v['loss'].get(S.BLEND))} | {v['best']} | {_f(vb['mean'], '{:+.5f}')} | "
                  f"{_f(vb['p'], '{:.3f}')} | {'yes' if v['beats'] else 'no'} |")
    md += ["", f"Selector beats the best model on {m['beats_labels']} of {len(m['labels'])} labels: "
               f"**{'yes' if m['verdict'] else 'no'}** (needs {PASS_LABELS}).", "",
           "Picks per test day: " + "; ".join(f"{k}: " + ", ".join(f"{d[5:]} {p}" for d, p in v["picks"].items())
                                             for k, v in m["labels"].items() if "picks" in v), "",
           "Per regime, the lowest log loss over the test days (blend from the days before):", "",
           "| label | " + " | ".join(S.REGIMES) + " |", "|---|" + "---|" * len(S.REGIMES)]
    for label, v in m["labels"].items():
        rg = v.get("regimes") or {}
        md.append(f"| {label} | " + " | ".join(f"{rg[r]['winner']} ({rg[r]['n']:,})" if r in rg else "n/a"
                                               for r in S.REGIMES) + " |")
    md += ["", f"## Test 2: allocator against the best single strategy (realistic replay, live latency)", ""]
    if a is None:
        md.append("No replay.")
    else:
        md += [f"Test days {', '.join(a['days'])}. Daily reward: log growth at {A.SHARE * 100:g} % a trade.", "",
               "| day | pick | " + " | ".join(A.ARMS) + " | allocator |", "|---|---|" + "---|" * (len(A.ARMS) + 1)]
        for x in a["per_day"]:
            md.append(f"| {x['day']} | {x['pick'] or 'out'} | "
                      + " | ".join(_f(res['rewards'][arm][x['day']] * 100, '{:+.1f} %') for arm in A.ARMS)
                      + f" | {x['reward'] * 100:+.1f} % |")
        vb = a["vs_best"] or {}
        md += ["", f"Totals: " + ", ".join(f"{k} {v * 100:+.1f} %" for k, v in a["total"].items())
               + f"; allocator {a['allocator'] * 100:+.1f} % (weighted {a['weighted'] * 100:+.1f} %). Best single "
               f"{a['best']}; allocator less best {_f(vb.get('mean', math.nan) * 100, '{:+.2f}')} points a day, "
               f"deflated p {_f(vb.get('p'), '{:.3f}')} (3 trials). Enough days: "
               f"{'yes' if a['enough_days'] else 'no'} ({len(a['days'])} of {MIN_ALLOC_DAYS}). "
               f"**{'yes' if a['verdict'] else 'no'}**."]
    fw = res.get("forward") or {}
    if fw.get("test"):
        md += ["", "Forward check on the realistic paper books since they started (not tested): "
               + "; ".join(f"{x['day']} pick {x['pick'] or 'out'} {x['reward'] * 100:+.1f} %"
                           for x in fw["test"]["per_day"])
               + "; arms " + ", ".join(f"{k} {v * 100:+.1f} %" for k, v in fw["test"]["total"].items()) + "."]
    return "\n".join(md) + "\n"


def jsonable(x):
    if isinstance(x, dict):
        return {str(k): jsonable(v) for k, v in x.items() if k != "raw"}
    if isinstance(x, (list, tuple)):
        return [jsonable(v) for v in x]
    if isinstance(x, np.ndarray):
        return None                                        # per-row arrays stay out of the file
    if isinstance(x, (np.floating, np.integer, np.bool_)):
        return x.item()
    return x


def run(out: Path, replay: Path | None = None, log=print) -> dict:
    from .retrain import load_rows
    from . import selmodel as SM
    now_ms = int(time.time() * 1000)
    rows, _ = load_rows()
    sel, _ = SM.load_rows()
    t0 = time.time()
    models = model_test(rows, sel, log=log)
    log(f"a1: test 1 in {time.time() - t0:.0f} s")
    if replay is not None:
        rep = json.loads(replay.read_text(encoding="utf-8"))
    else:
        from . import smallwallet as SW
        rep = SW.replay(until_ms=UNTIL_MS, log=log)
    days = alloc_days(rep)
    rw = A.day_rewards(entry_trades(rep["entries"]), days)
    res = {"run": A.day_of(now_ms), "models": models, "alloc": alloc_test(rw, days) if days else None,
           "rewards": rw, "forward": forward(now_ms, log)}
    out.mkdir(parents=True, exist_ok=True)
    (out / "adaptive_a1.json").write_text(json.dumps(jsonable(res), indent=1, default=str), encoding="utf-8")
    (out / "adaptive_a1.md").write_text(markdown(res), encoding="utf-8")
    return res


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="lab.pumpfun_rt.adaptive_a1")
    ap.add_argument("cmd", nargs="?", default="run", choices=("run",))
    ap.add_argument("--out", required=True)
    ap.add_argument("--replay", default=None)
    a = ap.parse_args(sys.argv[1:] if argv is None else argv)
    res = run(Path(a.out), Path(a.replay) if a.replay else None)
    print(markdown(res))
    return 0


if __name__ == "__main__":
    sys.exit(main())
