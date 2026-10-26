"""Y14: the coins' social links (socialfeat.py) in our models and books, judged out of sample as Y10. PAPER ONLY.

    python -m lab.pumpfun_rt.social14                   the registered run (refuses before its cutoff), writes
                                                        social14.{json,md} into the reports
    python -m lab.pumpfun_rt.social14 --out DIR         the same, written into DIR
    python -m lab.pumpfun_rt.social14 --same DAY        the old strategies replayed on DAY without and with the
                                                        social tracker and the Y14 books: identical or not

Pre-registered in results/pumpfun_social_y14_prereg.md. The record has the social links only from the deploy that
turned the metadata fetch on (the table "meta" with x_kind); the cutoff is the end of the EVAL_DAYS-th full UTC day
after the first day with them (cutoff_ms). One replay of the record up to it with the trend and the social tracker in
the engine (warmed on the days before the window) and, as trends10.run:

  the label book   selfeat.LabelPipe: every plain migration bought as P_pool0 would, at the migration and 5 s after
  the early rows   early.Tracker's rows with the trend and social features; no paths or steps
  the models       at the end of every UTC day the select models (selmodel.train: Y9's, Y10's and Y14's) trained on what
                   was decided and labelled before the next day, used through that day (select9.DayModels)
  the books        P_pool0_wait (W0), Y9's and Y10's +5 s filters (S4, A2) and the two Y14 books (B1 P_pool5_top30s,
                   B2 P_pool0_wait_social), each its own book of at most 4 positions under the daily loss limits of
                   0.25 SOL (L25) and 1.0 SOL (L100), every book drawing its latency with P_pool0's key

Judged (Y9's rule under both limits): B1 against A2 (the same filter without the social features), B2 against W0.
The models: the Y10 twin and the Y14 twin walk-forward on the same rows (those written with the social tracker).
Nothing here holds a wallet, reads a key, signs or sends anything.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
import time
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

from . import exitlab as XL
from . import exitpol as XP
from . import pipeline as P
from . import select9 as Y9
from . import selfeat as SF
from . import selmodel as SM
from . import trends10 as T10

# ---------------------------------------------------------------- registered (results/pumpfun_social_y14_prereg.md)

VARIANTS = (("W0", "P_pool0_wait"), ("S4", "P_pool5_top30"), ("A2", "P_pool5_top30t"), ("B1", "P_pool5_top30s"),
            ("B2", "P_pool0_wait_social"))
JUDGED = {"B1": "A2", "B2": "W0"}                       # each against the book it differs from by Y14 alone
BASE = "P_pool0"
EVAL_DAYS = 7                                           # 2 to reach selmodel.MIN_TRAIN rows with metadata, 5 judged
TAIL_MS = Y9.TAIL_MS
STAKE_SOL = Y9.STAKE_SOL
LIMITS = Y9.LIMITS
LIMIT_LABEL = Y9.LIMIT_LABEL
SEL_TRADED = ("win5t", "win5s")                        # the out-of-sample days start with both
MODEL_PAIRS = (("win0t", "win0s"), ("rug0t", "rug0s"), ("win5t", "win5s"), ("rug5t", "rug5s"))
EARLY_COMPARED = ("alive5m", "peak3x")                  # et_ against es_, walk-forward (descriptive)
AUC_GAIN = 0.02                                         # a twin "improves" its model: AUC this much higher, Brier
                                                        # skill not lower, on the same rows


def first_social_day(root=None) -> str | None:
    """The first UTC day of the record whose metadata rows carry the social links."""
    from . import store
    for d in store.days(root):
        me = store.read("meta", [d], root)
        if len(me) and "x_kind" in me.columns and me["x_kind"].drop_nulls().len():
            return d
    return None


def cutoff_ms(root=None) -> int | None:
    """The end of the EVAL_DAYS-th full UTC day after the first day with the social links (None before any)."""
    d = first_social_day(root)
    return None if d is None else SM.day_start(d) + (EVAL_DAYS + 1) * SM.DAY_MS


def books() -> tuple[list[tuple[P.Strategy, P.Limits]], dict]:
    """Every variant once per limit, `<name>@<limit>`, at STAKE_SOL and Y9's latency, P_pool0's key."""
    b = Y9.scenarios()["B"]
    out, costs = [], {}
    for k, lim in LIMITS.items():
        for _, name in VARIANTS:
            s = P.BY_NAME[name]
            v = dataclasses.replace(s, name=f"{name}@{k}", p={**s.p, "base": BASE}, stake_sol=STAKE_SOL)
            out.append((v, lim))
            costs[v.name] = b
    return out, costs


def social_rows(table: dict) -> dict:
    """The rows written with the social tracker (soc_known not NaN): the Y10 and Y14 twins are compared on them."""
    if "soc_known" not in table or not len(table["t"]):
        return {k: v[:0] for k, v in table.items()}
    m = np.isfinite(table["soc_known"])
    return {k: v[m] for k, v in table.items()}


def usable(ms: dict) -> list[str]:
    return [k for k in SM.LABELS if getattr(ms.get("sel_" + k), "booster", None) is not None]


def oos_day(days: list[str], trained: dict) -> str | None:
    return next((d for d in days if set(SEL_TRADED) <= set((trained.get(d) or {}).get("models", ()))), None)


# ---------------------------------------------------------------- the run

def run(root=None, until_ms: int | None = None, log=print, tail_ms: int = TAIL_MS) -> dict:
    from . import early as EA
    from . import sim, store
    from . import socialfeat as SO
    from . import wallets as W
    from .study import WARM_DAYS, WINDOW_DAYS, span_of, warm_book
    until_ms = until_ms if until_ms is not None else cutoff_ms(root)
    if until_ms is None:
        return {"empty": True}
    cutoff_day = SF.day_of(until_ms - 1)
    all_days = [d for d in store.days(root) if d <= cutoff_day]
    days = all_days[-WINDOW_DAYS:]
    if not days:
        return {"empty": True}
    warm = [d for d in all_days if d < days[0]][-WARM_DAYS:]
    t_lo, t_hi = span_of(days, root)
    t_hi = min(t_hi, until_ms)
    entry_until = t_hi - tail_ms
    log(f"social14: {len(days)} day(s) {days[0]} to {days[-1]}, record to {Y9._utc(t_hi)}, entries to "
        f"{Y9._utc(entry_until)}, warm-up {len(warm)} day(s)")
    t0 = time.time()
    strats, costs = books()
    eng = sim.Engine([], book=warm_book(warm, root), decisions=False, rule_costs=costs, entry_until=entry_until,
                     wallets=W.warm(warm, root), snipers=EA.warm_snipers(warm, root), select=True, trend=True,
                     social=SO.warm(warm, root), early_rows=True)
    eng.early.keep_frac = 0.0                              # rows only: no paths or steps
    dm = Y9.DayModels()
    dm.eng = eng
    eng.models = dm
    lab = eng.add_pipe(SF.LabelPipe(eng, Y9.scenarios()["B"]))
    pipes = {s.name: eng.add_pipe(XL.PeakPipe(eng, [s], P.PaperExecutor(), limits=lim, name=s.name))
             for s, lim in strats}
    trained: dict[str, dict] = {}

    def next_day(day: str, n: int) -> None:
        nd = (datetime.strptime(day, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
        ms = SM.train(lab.table(), until_ms=SM.day_start(nd))
        dm.by_day[nd] = ms
        trained[nd] = {"rows": ms["sel_rows"], "models": usable(ms)}
        log(f"social14: {day} done ({n:,} events); models for {nd}: {trained[nd]}")
    sim.replay(days, eng, root, progress=next_day, until_ms=t_hi)
    for pipe in pipes.values():
        pipe.finish(eng.now)
    oos = oos_day(days, trained)
    log(f"social14: replay in {time.time() - t0:.0f} s, {len(lab.rows):,} label rows, {eng.early.rows.n:,} early "
        f"rows, out of sample from {oos}")
    return {"days": days, "warm": warm, "span": (t_lo, t_hi), "until_ms": until_ms, "entry_until_ms": entry_until,
            "oos_day": oos, "split_ms": SM.day_start(oos) if oos else None, "trained": trained,
            "table": lab.table(), "early": T10.early_snapshot(eng.early),
            "entries": {n: XL.entries(p, eng.gaps) for n, p in pipes.items()},
            "skips": {n: p.skips for n, p in pipes.items()},
            "open_at_end": {n: len(p.pos) for n, p in pipes.items() if p.pos},
            "counts": dict(eng.counts), "gaps": list(eng.gaps)}


# ---------------------------------------------------------------- numbers

def evaluate(res: dict) -> dict:
    """Per limit: every book's out-of-sample numbers (gapped trades kept), the in-sample ones (reported, not judged),
    each judged book against its counterpart by Y9's rule; better = better under both limits."""
    split = res["split_ms"]
    table, is_table, vs = {}, {}, {}
    for k in LIMITS:
        table[k], is_table[k], vs[k] = {}, {}, {}
        ent = {}
        for x, name in VARIANTS:
            e = res["entries"][f"{name}@{k}"]
            oos = [y for y in e if split is not None and y["signal_ms"] >= split]
            ent[x] = oos
            table[k][x] = XL.stats(oos) | {"name": name}
            is_table[k][x] = XL.stats([y for y in e if split is None or y["signal_ms"] < split]) | {"name": name}
            sk = [w for t, w in res["skips"][f"{name}@{k}"] if split is not None and t >= split]
            table[k][x]["skipped"] = dict(sorted(Counter(sk).items()))
            table[k][x]["hours"] = XL.hours(oos)
        for x, y in JUDGED.items():
            vs[k][x] = T10.judge(ent[x], ent[y], table[k][x], table[k][y])
    return {"table": table, "in_sample": is_table, "versus": vs,
            "better": {x: all(vs[k][x]["better"] for k in LIMITS) for x in JUDGED}}


def model_compare(wf: dict) -> list[dict]:
    """The Y10 twin and the Y14 twin on the same walk-forward rows; improves by the registered AUC_GAIN rule."""
    out = []
    for r in T10.model_compare(wf, MODEL_PAIRS):
        a, b, sa, sb = r["auc"], r["auc_trend"], r["brier_skill"], r["brier_skill_trend"]
        ok = None not in (a, b, sa, sb)
        out.append({"y10": r["y9"], "y14": r["trend"], "n": r["n"], "n_y14": r["n_trend"], "auc": a, "auc_y14": b,
                    "logistic_auc": r["logistic_auc"], "logistic_auc_y14": r["logistic_auc_trend"],
                    "brier_skill": sa, "brier_skill_y14": sb, "ret_top": r["ret_top"], "n_top": r["n_top"],
                    "ret_top_y14": r["ret_top_trend"], "n_top_y14": r["n_top_trend"],
                    "improves": bool(ok and b - a >= AUC_GAIN and sb >= sa)})
    return out


def early_compare(fr: dict, labels=EARLY_COMPARED) -> list[dict]:
    """X14's purged walk-forward of et_<label> and es_<label> on the early rows written with the social tracker."""
    sub = social_rows(fr)
    out = []
    for label in labels:
        if not len(sub["t"]):
            out.append({"label": label, "rows": 0})
            continue
        a = XP.evaluate_early(sub, label, XP.trend_features())
        b = XP.evaluate_early(sub, label, XP.social_features())
        g = lambda r: ((r.get("pooled") or {}).get("gbm") or {})                            # noqa: E731
        out.append({"label": label, "rows": a.get("rows"), "auc": g(a).get("auc"), "auc_y14": g(b).get("auc"),
                    "brier_skill": g(a).get("brier_skill"), "brier_skill_y14": g(b).get("brier_skill"),
                    "folds": len(a.get("folds", []))})
    return out


def coverage(table: dict) -> dict:
    """How many label rows had the coin's metadata, and what kind of X link."""
    k = table.get("soc_known")
    if k is None or not len(k):
        return {"rows": 0}
    m = np.isfinite(k)
    kinds = Counter(int(x) for x in table["soc_x_kind"][m & (k == 1)] if x == x)
    from .socialfeat import X_KINDS
    return {"rows": int(m.sum()), "known": int((k[m] == 1).sum()),
            "x_kind": {X_KINDS[i]: n for i, n in sorted(kinds.items())},
            "handle_reused": int(np.nansum(table["soc_handle_prev"][m] >= 1)),
            "tweet_reused": int(np.nansum(table["soc_tweet_prev"][m] >= 1))}


# ---------------------------------------------------------------- report

pct = Y9.pct
_band, _f, _utc = Y9._band, Y9._f, Y9._utc


def _table(ev: dict, k: str) -> list[str]:
    md = ["| book | strategy | entries | hours | mean | median | win | P&L SOL | band of mean | max DD SOL | "
          "no model | no social data | filtered out |", "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for x, _ in VARIANTS:
        s = ev["table"][k][x]
        sk = s["skipped"]
        tail = (f"{sk.get('no model', 0)} | {sk.get('no social data', 0)} | "
                f"{sk.get('model', 0) + sk.get('social rule', 0)} |")
        if not s.get("n"):
            md.append(f"| {x} | {s['name']} | 0 | 0 |" + " |" * 6 + " " + tail)
            continue
        md.append(f"| {x} | {s['name']} | {s['n']} | {s['hours']} | {pct(s['mean'])} | {pct(s['median'])} | "
                  f"{s['win'] * 100:.0f} % | {s['pnl_sol']:+.3f} | {_band(s['band'])} | {s['max_dd_sol']:.3f} | "
                  + tail)
    md += ["", "| book against | mean difference | band (hours paired) | P&L difference SOL | better | coins both "
               "entered | their difference |", "|---|---|---|---|---|---|---|"]
    for x, y in JUDGED.items():
        v = ev["versus"][k][x]
        d = ev["table"][k][x].get("pnl_sol", 0.0) - ev["table"][k][y].get("pnl_sol", 0.0)
        md.append(f"| {x} vs {y} | {pct(v['diff'])} | {_band(v['band'])} | {d:+.3f} | "
                  f"{'yes' if v['better'] else 'no'} | {v['common']['n']} | {pct(v['common']['diff'])} |")
    return md


def report_md(res: dict, ev: dict, mc: list[dict], ec: list[dict], cov: dict) -> str:
    md = ["# The coins' social links in our models and books (Y14)", "",
          f"Record {res['days'][0]} to {_utc(res['span'][1])}, entries to {_utc(res['entry_until_ms'])}; out of "
          f"sample from {res['oos_day'] or 'n/a (no day had both models)'}. Label rows with the social tracker "
          f"{cov.get('rows', 0)}, with the coin's metadata {cov.get('known', 0)}, X links {cov.get('x_kind', {})}.",
          "", "Verdict: " + "; ".join(f"{x} {'better' if ev['better'][x] else 'not better'} than {y}"
                                      for x, y in JUDGED.items()) + "; "
          + "; ".join(f"{r['y14']} {'improves' if r['improves'] else 'does not improve'} on {r['y10']}"
                      for r in mc) + ".", "",
          "## The models, Y10's twin and Y14's on the same rows", "",
          "| Y10 | Y14 | rows | AUC | AUC Y14 | logistic | logistic Y14 | Brier skill | Y14 | top 30 % | Y14 |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in mc:
        md.append(f"| {r['y10']} | {r['y14']} | {r['n'] or 0} | {_f(r['auc'])} | {_f(r['auc_y14'])} | "
                  f"{_f(r['logistic_auc'])} | {_f(r['logistic_auc_y14'])} | {_f(r['brier_skill'], '{:+.3f}')} | "
                  f"{_f(r['brier_skill_y14'], '{:+.3f}')} | {pct(r['ret_top'])} ({r['n_top'] or 0}) | "
                  f"{pct(r['ret_top_y14'])} ({r['n_top_y14'] or 0}) |")
    md += ["", "| early label | rows | AUC et_ | AUC es_ | Brier skill et_ | es_ |", "|---|---|---|---|---|---|"]
    for r in ec:
        md.append(f"| {r['label']} | {r.get('rows') or 0} | {_f(r.get('auc'))} | {_f(r.get('auc_y14'))} | "
                  f"{_f(r.get('brier_skill'), '{:+.3f}')} | {_f(r.get('brier_skill_y14'), '{:+.3f}')} |")
    for k in LIMITS:
        md += ["", f"## Out of sample, {LIMIT_LABEL[k]}", ""] + _table(ev, k)
    md += ["", "Models per day: " + "; ".join(f"{d} {v['models'] or 'none'}" for d, v in res["trained"].items())]
    return "\n".join(md) + "\n"


# ---------------------------------------------------------------- every strategy before Y14 as before

def same(day: str, root=None, log=print) -> dict:
    """The recorded day replayed with every rule and every strategy before Y14 (the study's engine without the
    social tracker), and again with the social tracker and every strategy: the closed trades, failed buys and
    skips of the old ones compared field by field (the pid aside, as Y9 to Y16)."""
    from . import sim, store
    from . import strategies as S
    from .model import load
    old = P.STRATEGIES[:-len(P._build_y14())]
    models = load()
    days = [d for d in store.days(root) if d == day]

    def go(new: bool):
        t0 = time.time()
        eng = sim.Engine(S.RULES, strategies=P.STRATEGIES if new else old, models=models, select=True, trend=True,
                         social=new)
        sim.replay(days, eng, root)
        log(f"social14: {day} {'with' if new else 'without'} Y14 in {time.time() - t0:.0f} s")
        return eng
    a, b = go(False), go(True)
    names = {s.name for s in old} | {r.name for r in S.RULES}

    def strip(xs):
        out = [{k: v for k, v in x.items() if k != "pid"} for x in xs if x["rule"] in names]
        return sorted(out, key=lambda x: (x["rule"], x["mint"], x["signal_ms"], x.get("exit_ms") or x.get("land_ms")))
    ca, cb, fa, fb = strip(a.closed), strip(b.closed), strip(a.failed), strip(b.failed)
    sa = {f"{k[0]}|{k[1]}": v for k, v in a.skipped.items() if k[0] in names}
    sb = {f"{k[0]}|{k[1]}": v for k, v in b.skipped.items() if k[0] in names}
    return {"day": day, "closed": len(ca), "failed": len(fa), "same_closed": ca == cb, "same_failed": fa == fb,
            "same_skipped": sa == sb, "y14_closed": sum(1 for t in b.closed if t["rule"] not in names)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default=None, help="directory for social14.json and social14.md (default: the reports)")
    ap.add_argument("--same", default=None, metavar="DAY", help="replay DAY without and with Y14 and compare")
    a = ap.parse_args(argv)
    from .. import report as rep
    out = Path(a.out) if a.out else rep.REPORTS / "pumpfun_rt"
    out.mkdir(parents=True, exist_ok=True)
    if a.same:
        r = same(a.same)
        print(json.dumps(r))
        (out / f"social14_same_{a.same}.json").write_text(json.dumps(r, indent=1), encoding="utf-8")
        return 0 if r["same_closed"] and r["same_failed"] and r["same_skipped"] else 1
    cut = cutoff_ms()
    if cut is None or cut > int(time.time() * 1000):
        first = first_social_day()
        print(f"social14: too early (first day with the social links {first or 'none yet'}; the registered run "
              f"needs {EVAL_DAYS} full days after it)")
        return 1
    res = run(until_ms=cut)
    if res.get("empty"):
        print("social14: nothing recorded")
        return 1
    ev = evaluate(res)
    wf = SM.walk_forward(social_rows(res["table"]))
    mc = model_compare(wf)
    ec = early_compare(res["early"])
    cov = coverage(res["table"])
    md = report_md(res, ev, mc, ec, cov)
    keep = {k: v for k, v in res.items() if k not in ("entries", "skips", "table", "early")}
    (out / "social14.json").write_text(json.dumps(keep | {"eval": ev, "models": mc, "early_models": ec,
                                                          "coverage": cov, "walk_forward": wf},
                                                  indent=1, default=str), encoding="utf-8")
    (out / "social14.md").write_text(md, encoding="utf-8")
    print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
