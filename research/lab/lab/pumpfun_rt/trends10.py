"""Y10: the Trends page's measures in our models and strategies, judged against P_pool0 at the latency the live executor
measures. PAPER ONLY.

    python -m lab.pumpfun_rt.trends10                   replay, print the report, write trends10.{json,md}
    python -m lab.pumpfun_rt.trends10 --out DIR         the same, written into DIR

Pre-registered in results/pumpfun_trends_y10_prereg.md. One replay of the record up to the cutoff with the trend
tracker (trendfeat.py) in the engine and:

  the label book   selfeat.LabelPipe (Y9's): every plain migration bought as P_pool0 would, at the migration and 5 s
                   after it; its rows now carry the trend features too
  the early rows   early.Tracker's rows (X14's: every plain curve at 5 to 60 s and at 25/50/75 %), with the trend
                   features; no paths or steps
  the models       at the end of every UTC day the select models (selmodel.train: Y9's four and the four with the trend
                   features) and the early model et_alive5m (exitpol.fit_trend) are trained on what was decided and
                   labelled before the next day starts, and used through that next day (select9.DayModels)
  the books        P_pool0 (X0), Y9's two top-30 % filters (S2, S4) and the five Y10 strategies (pipeline._build_y10,
                   A1, A2, T1 to T3), each its own book of at most 4 positions, under the daily loss limits of 0.25
                   SOL (L25) and 1.0 SOL (L100), every book drawing its latency with P_pool0's key

Fills at Y9's registered latency (select9.SENDER_BUY_MS, SENDER_SELL_MS: the executor has no new fill since),
0.001005 SOL per transaction, 0.1 SOL a trade. Out of sample: the days from the first one with every model a judged
book uses. Nothing here holds a wallet, reads a key, signs or sends anything; the live executor's files are only read.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import math
import sys
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from . import early as E
from . import exitlab as XL
from . import exitpol as XP
from . import exits8 as X8
from . import pipeline as P
from . import select9 as Y9
from . import selfeat as SF
from . import selmodel as SM

# ---------------------------------------------------------------- registered (results/pumpfun_trends_y10_prereg.md)

VARIANTS = (("X0", "P_pool0"), ("S2", "P_pool0_top30"), ("S4", "P_pool5_top30"), ("A1", "P_pool0_top30t"),
            ("A2", "P_pool5_top30t"), ("T1", "P_hot5"), ("T2", "P_fresh3"), ("T3", "P_pool0_heat"))
JUDGED = ("A1", "A2", "T1", "T2", "T3")
COUNTERPART = {"A1": "S2", "A2": "S4"}                  # (a): the Y9 filter the trend model is judged against too
BASE = "P_pool0"
UNTIL_MS = int(datetime(2026, 10, 23, 14, 0, tzinfo=timezone.utc).timestamp() * 1000)
TAIL_MS = Y9.TAIL_MS
STAKE_SOL = Y9.STAKE_SOL
LIMITS = Y9.LIMITS
LIMIT_LABEL = Y9.LIMIT_LABEL
SEL_TRADED = ("win0", "win5", "win0t", "win5t")         # the select models the books use
EARLY_TRADED = ("alive5m",)                             # et_<label>, T1's filter
EARLY_COMPARED = ("alive5m", "peak3x")                  # e_ against et_, walk-forward (descriptive)
MODEL_PAIRS = (("win0", "win0t"), ("rug0", "rug0t"), ("win5", "win5t"), ("rug5", "rug5t"))


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


def early_snapshot(tracker) -> dict[str, np.ndarray]:
    """The early rows as known now, in time order (exitpol.early_rows), without packing the rows still waiting for
    a label (packing them would stop their labels): a row's label is NaN until it is known; rows whose window
    meets a curve gap are dropped as early.Tracker.tables does."""
    rows = tracker.rows
    A = np.full((rows.n, len(rows.cols)), np.nan)
    if rows.chunks:
        got = np.vstack(rows.chunks)[:rows.n]
        A[:len(got)] = got
    for idx, row in rows.pending.items():
        A[idx] = [float(row[c]) if row.get(c) is not None else np.nan for c in rows.cols]
    fr = {c: A[:, i] for c, i in rows.col.items()}
    if len(fr["t"]):
        a, b = fr["created_ms"], fr["t"] + E.GAP_TAIL_MS
        bad = np.zeros(len(a), dtype=bool)
        for g0, g1 in tracker.gaps["curve"]:
            bad |= (g0 < b) & (a < g1)
        fr["dropped"] = bad.astype(float)
    return XP.early_rows({"rows": fr})


def day_models(lab_table: dict, early_fr: dict, until_ms: int) -> dict:
    """What the books may use through the day starting at until_ms: the select models and et_<label> of
    EARLY_TRADED, trained on what was decided and labelled before it."""
    ms = SM.train(lab_table, until_ms=until_ms)
    for label in EARLY_TRADED:
        ms["et_" + label] = XP.fit_trend(early_fr, label, until_ms)
    return ms


def usable(ms: dict) -> list[str]:
    out = [k for k in SM.LABELS if getattr(ms.get("sel_" + k), "booster", None) is not None]
    return out + [f"et_{k}" for k in EARLY_TRADED if getattr(ms.get("et_" + k), "booster", None) is not None]


def oos_day(days: list[str], trained: dict) -> str | None:
    need = set(SEL_TRADED) | {f"et_{k}" for k in EARLY_TRADED}
    return next((d for d in days if need <= set((trained.get(d) or {}).get("models", ()))), None)


# ---------------------------------------------------------------- the run

def run(root=None, until_ms: int = UNTIL_MS, log=print, tail_ms: int = TAIL_MS) -> dict:
    from . import early as EA
    from . import sim, store
    from . import wallets as W
    from .study import WARM_DAYS, WINDOW_DAYS, span_of, warm_book
    cutoff_day = SF.day_of(until_ms)
    all_days = [d for d in store.days(root) if d <= cutoff_day]
    days = all_days[-WINDOW_DAYS:]
    if not days:
        return {"empty": True}
    warm = [d for d in all_days if d < days[0]][-WARM_DAYS:]
    t_lo, t_hi = span_of(days, root)
    t_hi = min(t_hi, until_ms)
    entry_until = t_hi - tail_ms
    log(f"trends10: {len(days)} day(s) {days[0]} to {days[-1]}, record to {Y9._utc(t_hi)}, entries to "
        f"{Y9._utc(entry_until)}, warm-up {len(warm)} day(s)")
    t0 = time.time()
    strats, costs = books()
    eng = sim.Engine([], book=warm_book(warm, root), decisions=False, rule_costs=costs, entry_until=entry_until,
                     wallets=W.warm(warm, root), snipers=EA.warm_snipers(warm, root), select=True, trend=True,
                     early_rows=True)
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
        ms = day_models(lab.table(), early_snapshot(eng.early), SM.day_start(nd))
        dm.by_day[nd] = ms
        trained[nd] = {"rows": ms["sel_rows"], "models": usable(ms)}
        log(f"trends10: {day} done ({n:,} events); models for {nd}: {trained[nd]}")
    sim.replay(days, eng, root, progress=next_day, until_ms=t_hi)
    for pipe in pipes.values():
        pipe.finish(eng.now)
    oos = oos_day(days, trained)
    log(f"trends10: replay in {time.time() - t0:.0f} s, {len(lab.rows):,} label rows, {eng.early.rows.n:,} early "
        f"rows, out of sample from {oos}")
    return {"days": days, "warm": warm, "span": (t_lo, t_hi), "until_ms": until_ms, "entry_until_ms": entry_until,
            "oos_day": oos, "split_ms": SM.day_start(oos) if oos else None, "trained": trained,
            "table": lab.table(), "early": early_snapshot(eng.early),
            "entries": {n: XL.entries(p, eng.gaps) for n, p in pipes.items()},
            "skips": {n: p.skips for n, p in pipes.items()},
            "open_at_end": {n: len(p.pos) for n, p in pipes.items() if p.pos},
            "counts": dict(eng.counts), "gaps": list(eng.gaps)}


# ---------------------------------------------------------------- numbers

def judge(e: list[dict], base: list[dict], s: dict, b: dict) -> dict:
    """Y9's rule: the hour-paired band of the difference of the means above zero and the higher total P&L."""
    v = X8.paired(e, base)
    v["common"] = XL.versus(e, base)
    v["pnl_higher"] = s.get("pnl_sol", -math.inf) > b.get("pnl_sol", math.inf)
    lo = v["band"][0]
    v["better"] = bool(math.isfinite(lo) and lo > 0 and v["pnl_higher"])
    return v


def evaluate(res: dict) -> dict:
    """Per limit: every book's out-of-sample numbers (gapped trades kept, as Y8 and Y9), the in-sample ones
    (reported, not judged), every judged book against X0 and A1, A2 against their Y9 counterparts."""
    split = res["split_ms"]
    table, is_table, vs, vs_y9 = {}, {}, {}, {}
    for k in LIMITS:
        table[k], is_table[k], vs[k], vs_y9[k] = {}, {}, {}, {}
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
        for x in JUDGED:
            vs[k][x] = judge(ent[x], ent["X0"], table[k][x], table[k]["X0"])
        for x, y in COUNTERPART.items():
            vs_y9[k][x] = judge(ent[x], ent[y], table[k][x], table[k][y])
    better = {x: all(vs[k][x]["better"] for k in LIMITS) for x in JUDGED}
    improves = {x: all(vs_y9[k][x]["better"] for k in LIMITS) for x in COUNTERPART}
    return {"table": table, "in_sample": is_table, "versus": vs, "versus_y9": vs_y9, "better": better,
            "improves": improves}


def model_compare(wf: dict, pairs=MODEL_PAIRS) -> list[dict]:
    """Y9's model and the one with the trend features on the same walk-forward rows (descriptive)."""
    out = []
    for a, b in pairs:
        x, y = wf.get(a) or {}, wf.get(b) or {}
        auc = lambda v, k="model": ((v.get(k) or {}).get("auc") if v.get("n") else None)   # noqa: E731
        out.append({"y9": a, "trend": b, "n": x.get("n"), "n_trend": y.get("n"), "auc": auc(x), "auc_trend": auc(y),
                    "logistic_auc": auc(x, "logistic"), "logistic_auc_trend": auc(y, "logistic"),
                    "brier_skill": (x.get("model") or {}).get("brier_skill"),
                    "brier_skill_trend": (y.get("model") or {}).get("brier_skill"),
                    "ret_top": x.get("ret_top"), "n_top": x.get("n_top"), "ret_top_trend": y.get("ret_top"),
                    "n_top_trend": y.get("n_top")})
    return out


def early_compare(fr: dict, labels=EARLY_COMPARED) -> list[dict]:
    """X14's purged walk-forward (exitpol.evaluate_early) of e_<label> and et_<label> on the same rows."""
    out = []
    for label in labels:
        a = XP.evaluate_early(fr, label, E.early_feature_list())
        b = XP.evaluate_early(fr, label, XP.trend_features())
        g = lambda r: ((r.get("pooled") or {}).get("gbm") or {})                            # noqa: E731
        out.append({"label": label, "rows": a.get("rows"), "auc": g(a).get("auc"), "auc_trend": g(b).get("auc"),
                    "brier_skill": g(a).get("brier_skill"), "brier_skill_trend": g(b).get("brier_skill"),
                    "folds": len(a.get("folds", [])), "verdict": a.get("verdict"), "verdict_trend": b.get("verdict")})
    return out


def daily_deflated(res: dict) -> dict:
    """The deflated probability of each book's daily P&L out of sample in the lab's pool (n/a under 5 days)."""
    from .study import deflated_p, pool
    try:
        pl_ = pool([])
    except Exception:
        return {}
    out = {}
    for k in LIMITS:
        for x, name in VARIANTS:
            by: dict[str, float] = {}
            for y in res["entries"][f"{name}@{k}"]:
                if res["split_ms"] is not None and y["signal_ms"] >= res["split_ms"]:
                    by[SF.day_of(y["real_ms"])] = by.get(SF.day_of(y["real_ms"]), 0.0) + y["pnl_sol"]
            out[f"{x}@{k}"] = deflated_p(np.array(list(by.values())), pl_)
    return out


# ---------------------------------------------------------------- report

pct = Y9.pct
_band, _f, _utc = Y9._band, Y9._f, Y9._utc


def _table(ev: dict, k: str) -> list[str]:
    md = ["| book | strategy | entries | hours | failed buys | mean | median | win | P&L SOL | band of mean | "
          "max DD SOL | no model | filtered out | no pool state | daily loss limit |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for x, _ in VARIANTS:
        s = ev["table"][k][x]
        sk = s["skipped"]
        tail = (f"{sk.get('no model', 0)} | {sk.get('model', 0) + sk.get('filter', 0)} | "
                f"{sk.get('no pool state', 0)} | "
                f"{sk.get('daily loss limit', 0) + sk.get('daily loss stop', 0)} |")
        if not s.get("n"):
            md.append(f"| {x} | {s['name']} | 0 | 0 |" + " |" * 7 + " " + tail)
            continue
        md.append(f"| {x} | {s['name']} | {s['n']} | {s['hours']} | {s['failed']} | {pct(s['mean'])} | "
                  f"{pct(s['median'])} | {s['win'] * 100:.0f} % | {s['pnl_sol']:+.3f} | {_band(s['band'])} | "
                  f"{s['max_dd_sol']:.3f} | " + tail)
    for title, key, pairs in (("against X0", "versus", [(x, "X0") for x in JUDGED]),
                              ("against the Y9 filter", "versus_y9", list(COUNTERPART.items()))):
        md += ["", f"| book {title} | mean difference | band (hours paired) | P&L difference SOL | total P&L higher | "
                   "better | coins both entered | their difference | band |", "|---|---|---|---|---|---|---|---|---|"]
        for x, y in pairs:
            v = ev[key][k][x]
            c = v["common"]
            d = ev["table"][k][x].get("pnl_sol", 0.0) - ev["table"][k][y].get("pnl_sol", 0.0)
            md.append(f"| {x} vs {y} | {pct(v['diff'])} | {_band(v['band'])} | {d:+.3f} | "
                      f"{'yes' if v['pnl_higher'] else 'no'} | {'yes' if v['better'] else 'no'} | {c['n']} | "
                      f"{pct(c['diff'])} | {_band(c['band'])} |")
    md += ["", "Exits: " + "; ".join(
        f"{x} " + ", ".join(f"{w} {c}" for w, c in ev["table"][k][x].get("exits", {}).items()) for x, _ in VARIANTS)]
    return md


def models_md(mc: list[dict], ec: list[dict]) -> list[str]:
    md = ["| Y9 model | with trends | rows tested | AUC | AUC with trends | logistic AUC | logistic with trends | "
          "Brier skill | with trends | mean return of its top 30 % | with trends |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in mc:
        md.append(f"| {r['y9']} | {r['trend']} | {r['n'] or 0} | {_f(r['auc'])} | {_f(r['auc_trend'])} | "
                  f"{_f(r['logistic_auc'])} | {_f(r['logistic_auc_trend'])} | {_f(r['brier_skill'], '{:+.3f}')} | "
                  f"{_f(r['brier_skill_trend'], '{:+.3f}')} | {pct(r['ret_top'])} ({r['n_top'] or 0}) | "
                  f"{pct(r['ret_top_trend'])} ({r['n_top_trend'] or 0}) |")
    if ec:
        md += ["", "| early label | rows | folds | AUC e_ | AUC et_ (with trends) | Brier skill e_ | Brier skill et_ |",
               "|---|---|---|---|---|---|---|"]
        for r in ec:
            md.append(f"| {r['label']} | {r['rows']} | {r['folds']} | {_f(r['auc'])} | {_f(r['auc_trend'])} | "
                      f"{_f(r['brier_skill'], '{:+.3f}')} | {_f(r['brier_skill_trend'], '{:+.3f}')} |")
    return md


def report_md(res: dict, ev: dict, mc: list[dict], ec: list[dict], wf: dict, lat: dict, defl: dict) -> str:
    def ms(d):
        return f"{d['p50'] / 1000:.1f} s ({d['p10'] / 1000:.1f} to {d['p90'] / 1000:.1f})"
    b = lat["B"]
    md = ["# The Trends measures in our models and strategies (Y10)", "",
          f"Record {res['days'][0]} to {_utc(res['span'][1])}, entries to {_utc(res['entry_until_ms'])}; out of "
          f"sample from {res['oos_day'] or 'n/a (no day had the models)'}. Stake {STAKE_SOL} SOL, at most 4 open "
          f"per book; latency buy {ms(b['buy'])}, sale {ms(b['sell'])}, {b['tx_fee_sol']:.6f} SOL per transaction. "
          "Trades open across a gap kept.", "",
          "Verdict: " + "; ".join(f"{x} {'better than X0' if ev['better'][x] else 'not better than X0'}"
                                  for x in JUDGED) + "; " +
          "; ".join(f"{x} {'improves' if ev['improves'][x] else 'does not improve'} on {y}"
                    for x, y in COUNTERPART.items()) + ".",
          "", "## The models with and without the trend features, walk-forward", ""] + models_md(mc, ec)
    md += ["", "### Every select model, by day", ""] + Y9.wf_md(wf)
    for k in LIMITS:
        md += ["", f"## Out of sample, {LIMIT_LABEL[k]}", ""] + _table(ev, k)
    md += ["", "## In sample (not judged)", "", "| book | " + " | ".join(f"entries {k} | mean {k} | P&L SOL {k}"
                                                                         for k in LIMITS) + " |",
           "|---|" + "---|" * (3 * len(LIMITS))]
    for x, _ in VARIANTS:
        cells = []
        for k in LIMITS:
            s = ev["in_sample"][k][x]
            cells += [str(s["n"]), pct(s.get("mean")), f"{s.get('pnl_sol', 0):+.3f}"]
        md.append(f"| {x} | " + " | ".join(cells) + " |")
    if defl:
        md += ["", "Deflated probability of the daily P&L out of sample (n/a under 5 days): " + ", ".join(
            f"{k} {_f(v)}" for k, v in defl.items())]
    md += ["", "Models per day: " + "; ".join(f"{d} {v['models'] or 'none'} (rows {v['rows']})"
                                              for d, v in res["trained"].items())]
    return "\n".join(md) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--until-ms", type=int, default=UNTIL_MS)
    ap.add_argument("--out", default=None, help="directory for trends10.json and trends10.md (default: the reports)")
    ap.add_argument("--live-dir", default=None, help="the live executor's folder (read only)")
    a = ap.parse_args(argv)
    from .. import report as rep
    from ..data import ROOT
    out = Path(a.out) if a.out else rep.REPORTS / "pumpfun_rt"
    out.mkdir(parents=True, exist_ok=True)
    live_dir = Path(a.live_dir) if a.live_dir else ROOT / "live" / "pumpfun_rt"
    buys, sells = XL.sender_fills(XL.read_jsonl(live_dir / "measured.jsonl"), until_ms=a.until_ms)
    if (tuple(buys), tuple(sells)) != (Y9.SENDER_BUY_MS, Y9.SENDER_SELL_MS):
        print(f"trends10: the measured file now gives buys {buys} and sales {sells}; Y9's registered points are used")
    lat = {k: Y9.RL.describe(c) for k, c in Y9.scenarios().items()}
    res = run(until_ms=a.until_ms)
    if res.get("empty"):
        print("trends10: nothing recorded")
        return 1
    ev = evaluate(res)
    wf = SM.walk_forward(res["table"])
    mc = model_compare(wf)
    ec = early_compare(res["early"])
    defl = daily_deflated(res)
    md = report_md(res, ev, mc, ec, wf, lat, defl)
    keep = {k: v for k, v in res.items() if k not in ("entries", "skips", "table", "early")}
    (out / "trends10.json").write_text(json.dumps(keep | {"latency": lat, "eval": ev, "models": mc, "early_models": ec,
                                                          "walk_forward": wf, "deflated": defl,
                                                          "sender_fills": {"buy": buys, "sell": sells}},
                                                  indent=1, default=str), encoding="utf-8")
    (out / "trends10.md").write_text(md, encoding="utf-8")
    (out / "trends10_entries.json").write_text(json.dumps(res["entries"], default=str), encoding="utf-8")
    print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
