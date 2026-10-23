"""Y9: models that pick the coins worth buying at the migration, judged against P_pool0 at the latency the live
executor measures. PAPER ONLY.

    python -m lab.pumpfun_rt.select9                    replay, print the report, write select9.{json,md}
    python -m lab.pumpfun_rt.select9 --out DIR          the same, written into DIR

Pre-registered in results/pumpfun_select_y9_prereg.md. One replay of the record up to the cutoff with:

  the label book   selfeat.LabelPipe: every plain migration bought as P_pool0 would, at the migration and 5 s after
                   it, no slot or loss limit; its rows carry the decision features and the labels
  the models       at the end of every UTC day the four select models (selmodel.train) are trained on the rows
                   decided at least 15 minutes before the next day starts and used through that next day (an
                   expanding window by day, DayModels); a day without a model skips the filters' signals
  the books        P_pool0 (X0) and the five Y9 strategies (pipeline._build_y9, S1 to S5), each its own book of at
                   most 4 positions, under the live daily loss limit of 0.25 SOL (L25, judged) and under the code's
                   cap of 1.0 SOL (L100, judged too: the 0.25 SOL limit stops a book for the day after two or three
                   stops, Y8), every book drawing its latency with P_pool0's key

Fills at the live executor's P_pool0 latency since the Sender path (Y5's kernel density in log space, buys and sales
apart), 0.001005 SOL per transaction, 0.1 SOL a trade. Out of sample: the days from the first one with all three
traded models. Nothing here holds a wallet, reads a key, signs or sends anything; the live executor's files are only
read.
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

from . import exitlab as XL
from . import exits8 as X8
from . import pipeline as P
from . import reallat as RL
from . import selfeat as SF
from . import selmodel as SM

# ---------------------------------------------------------------- registered (results/pumpfun_select_y9_prereg.md)

VARIANTS = (("X0", "P_pool0"), ("S1", "P_pool0_norug"), ("S2", "P_pool0_top30"), ("S3", "P_pool0_norug_top30"),
            ("S4", "P_pool5_top30"), ("S5", "P_pool0_smart2"))
BASE = "P_pool0"
UNTIL_MS = int(datetime(2026, 10, 23, 8, 0, tzinfo=timezone.utc).timestamp() * 1000)
TAIL_MS = 15 * 60_000                                   # entries stop this long before the cutoff: all close inside
# The executor's P_pool0 fills, signal to landing (ms), 2026-10-22 21:41 UTC to the cutoff, clipped to 1 to 60 s.
SENDER_BUY_MS = X8.SENDER_BUY_MS + (1165.0, 14912.0)
SENDER_SELL_MS = X8.SENDER_SELL_MS + (3916.0, 1000.0)
TX_FEE_SOL = RL.TX_FEE_SOL
STAKE_SOL = 0.1
LIMITS = {"L25": P.Limits(STAKE_SOL, 4, P.HARD_MAX_EXPOSURE_SOL, 0.25),
          "L100": P.Limits(STAKE_SOL, 4, P.HARD_MAX_EXPOSURE_SOL, P.HARD_MAX_DAILY_LOSS_SOL)}
LIMIT_LABEL = {"L25": "daily loss limit 0.25 SOL (live)", "L100": "daily loss limit 1.0 SOL (the code's cap)"}
TRADED = ("win0", "rug0", "win5")                       # the models the strategies use
MIN_HOURS = XL.MIN_HOURS


def scenarios(buy_ms=SENDER_BUY_MS, sell_ms=SENDER_SELL_MS):
    return XL.scenarios(buy_ms, sell_ms, fee_sol=TX_FEE_SOL)


def books() -> tuple[list[tuple[P.Strategy, P.Limits]], dict]:
    """Every variant once per limit, `<name>@<limit>`, at STAKE_SOL and the measured latency, P_pool0's key."""
    b = scenarios()["B"]
    out, costs = [], {}
    for k, lim in LIMITS.items():
        for _, name in VARIANTS:
            s = P.BY_NAME[name]
            v = dataclasses.replace(s, name=f"{name}@{k}", p={**s.p, "base": BASE}, stake_sol=STAKE_SOL)
            out.append((v, lim))
            costs[v.name] = b
    return out, costs


class DayModels(dict):
    """The engine's models in the walk-forward replay: those trained for the UTC day of the engine's clock (an
    action runs with the clock at its own time, so a signal uses the model of the day it is given on)."""

    def __init__(self):
        super().__init__()
        self.by_day: dict[str, dict] = {}
        self.eng = None

    def get(self, k, default=None):
        m = self.by_day.get(SF.day_of(self.eng.now)) if self.eng is not None else None
        return default if m is None else m.get(k, default)

    def __bool__(self) -> bool:
        return bool(self.by_day)


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
    log(f"select9: {len(days)} day(s) {days[0]} to {days[-1]}, record to {_utc(t_hi)}, entries to "
        f"{_utc(entry_until)}, warm-up {len(warm)} day(s)")
    t0 = time.time()
    strats, costs = books()
    eng = sim.Engine([], book=warm_book(warm, root), decisions=False, rule_costs=costs, entry_until=entry_until,
                     wallets=W.warm(warm, root), snipers=EA.warm_snipers(warm, root), select=True)
    dm = DayModels()
    dm.eng = eng
    eng.models = dm
    lab = eng.add_pipe(SF.LabelPipe(eng, scenarios()["B"]))
    pipes = {s.name: eng.add_pipe(XL.PeakPipe(eng, [s], P.PaperExecutor(), limits=lim, name=s.name))
             for s, lim in strats}
    trained: dict[str, dict] = {}

    def next_day(day: str, n: int) -> None:
        nd = (datetime.strptime(day, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
        ms = SM.train(lab.table(), until_ms=SM.day_start(nd))
        dm.by_day[nd] = ms
        trained[nd] = {"rows": ms["sel_rows"], "models": [k for k in SM.LABELS if ms["sel_" + k].booster is not None]}
        log(f"select9: {day} done ({n:,} events); models for {nd}: {trained[nd]}")
    sim.replay(days, eng, root, progress=next_day, until_ms=t_hi)
    for pipe in pipes.values():
        pipe.finish(eng.now)
    oos_day = next((d for d in days if set(TRADED) <= set((trained.get(d) or {}).get("models", ()))), None)
    log(f"select9: replay in {time.time() - t0:.0f} s, {len(lab.rows):,} label rows, out of sample from {oos_day}")
    return {"days": days, "warm": warm, "span": (t_lo, t_hi), "until_ms": until_ms, "entry_until_ms": entry_until,
            "oos_day": oos_day, "split_ms": SM.day_start(oos_day) if oos_day else None, "trained": trained,
            "table": lab.table(), "entries": {n: XL.entries(p, eng.gaps) for n, p in pipes.items()},
            "skips": {n: p.skips for n, p in pipes.items()},
            "open_at_end": {n: len(p.pos) for n, p in pipes.items() if p.pos},
            "counts": dict(eng.counts), "gaps": list(eng.gaps)}


# ---------------------------------------------------------------- numbers

def evaluate(res: dict) -> dict:
    """Per limit: every book's out-of-sample numbers (gapped trades kept, as Y8), the in-sample ones (reported, not
    judged), and each filter against X0: the hour-paired band of the difference of the means over all entries and
    the total P&L (X8.paired)."""
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
        b = table[k]["X0"]
        for x, _ in VARIANTS[1:]:
            v = X8.paired(ent[x], ent["X0"])
            v["common"] = XL.versus(ent[x], ent["X0"])
            v["pnl_higher"] = table[k][x].get("pnl_sol", -math.inf) > b.get("pnl_sol", math.inf)
            lo = v["band"][0]
            v["better"] = bool(math.isfinite(lo) and lo > 0 and v["pnl_higher"])
            vs[k][x] = v
    return {"table": table, "in_sample": is_table, "versus": vs}


def daily_deflated(res: dict, ev: dict) -> dict:
    """The deflated probability of each book's daily P&L out of sample in the lab's pool (study.deflated_p: n/a
    under 5 days)."""
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

pct = RL.pct


def _band(b) -> str:
    return f"{pct(b[0])} to {pct(b[1])}"


def _utc(x) -> str:
    return f"{datetime.fromtimestamp(x / 1000, timezone.utc):%Y-%m-%d %H:%M} UTC"


def _f(x, fmt="{:.3f}") -> str:
    return "n/a" if x is None or (isinstance(x, float) and not math.isfinite(x)) else fmt.format(x)


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
    md += ["", "| book | mean difference vs X0 | band (hours paired) | P&L difference SOL | total P&L higher | "
           "better than X0 | migrations both entered | their difference | band |",
           "|---|---|---|---|---|---|---|---|---|"]
    for x, _ in VARIANTS[1:]:
        v = ev["versus"][k][x]
        c = v["common"]
        d = ev["table"][k][x].get("pnl_sol", 0.0) - ev["table"][k]["X0"].get("pnl_sol", 0.0)
        md.append(f"| {x} | {pct(v['diff'])} | {_band(v['band'])} | {d:+.3f} | {'yes' if v['pnl_higher'] else 'no'} | "
                  f"{'yes' if v['better'] else 'no'} | {c['n']} | {pct(c['diff'])} | {_band(c['band'])} |")
    md += ["", "Exits: " + "; ".join(
        f"{x} " + ", ".join(f"{w} {c}" for w, c in ev["table"][k][x].get("exits", {}).items()) for x, _ in VARIANTS)]
    return md


def wf_md(wf: dict) -> list[str]:
    md = ["| label | rows tested | rate | AUC | logistic AUC | Brier skill | logistic Brier skill | mean return, all | "
          "top 30 % | under the base rate |", "|---|---|---|---|---|---|---|---|---|---|"]
    for k, v in wf.items():
        if not v.get("n"):
            md.append(f"| {k} | 0 | | | | | | | | |")
            continue
        pm, plg = v["model"], v["logistic"]
        md.append(f"| {k} | {v['n']} | {v['rate'] * 100:.1f} % | {_f(pm['auc'])} | {_f(plg['auc'])} | "
                  f"{_f(pm['brier_skill'], '{:+.3f}')} | {_f(plg['brier_skill'], '{:+.3f}')} | {pct(v['ret_all'])} | "
                  f"{pct(v['ret_top'])} ({v['n_top']}) | {pct(v['ret_below_base'])} ({v['n_below_base']}) |")
    md += ["", "| label | day | trained on | tested | AUC | logistic AUC | rate | base | top threshold |",
           "|---|---|---|---|---|---|---|---|---|"]
    for k, v in wf.items():
        for d in v["days"]:
            if not d.get("model"):
                md.append(f"| {k} | {d['day']} | {d['train']} | {d['test']} | no model | | | | |")
                continue
            md.append(f"| {k} | {d['day']} | {d['train']} | {d['test']} | {_f(d['auc'])} | {_f(d['logistic_auc'])} | "
                      f"{d['rate'] * 100:.1f} % | {d['base'] * 100:.1f} % | {_f(d['threshold'])} |")
    return md


def report_md(res: dict, ev: dict, wf: dict, lat: dict, defl: dict) -> str:
    def ms(d):
        return f"{d['p50'] / 1000:.1f} s ({d['p10'] / 1000:.1f} to {d['p90'] / 1000:.1f})"
    b = lat["B"]
    md = ["# Which coins to buy at the migration (Y9)", "",
          f"Record {res['days'][0]} to {_utc(res['span'][1])}, entries to {_utc(res['entry_until_ms'])}; out of "
          f"sample from {res['oos_day'] or 'n/a (no day had the models)'}. Stake {STAKE_SOL} SOL, at most 4 open "
          f"per book; latency buy {ms(b['buy'])}, sale {ms(b['sell'])}, {b['tx_fee_sol']:.6f} SOL per transaction. "
          "Trades open across a gap kept.", "", "## The models, walk-forward by day", ""] + wf_md(wf)
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
    ap.add_argument("--out", default=None, help="directory for select9.json and select9.md (default: the reports)")
    ap.add_argument("--live-dir", default=None, help="the live executor's folder (read only)")
    a = ap.parse_args(argv)
    from .. import report as rep
    from ..data import ROOT
    out = Path(a.out) if a.out else rep.REPORTS / "pumpfun_rt"
    out.mkdir(parents=True, exist_ok=True)
    live_dir = Path(a.live_dir) if a.live_dir else ROOT / "live" / "pumpfun_rt"
    buys, sells = XL.sender_fills(XL.read_jsonl(live_dir / "measured.jsonl"), until_ms=a.until_ms)
    if (tuple(buys), tuple(sells)) != (SENDER_BUY_MS, SENDER_SELL_MS):
        print(f"select9: the measured file now gives buys {buys} and sales {sells}; the registered points are used")
    lat = {k: RL.describe(c) for k, c in scenarios().items()}
    res = run(until_ms=a.until_ms)
    if res.get("empty"):
        print("select9: nothing recorded")
        return 1
    ev = evaluate(res)
    wf = SM.walk_forward(res["table"])
    defl = daily_deflated(res, ev)
    md = report_md(res, ev, wf, lat, defl)
    keep = {k: v for k, v in res.items() if k not in ("entries", "skips", "table")}
    (out / "select9.json").write_text(json.dumps(keep | {"latency": lat, "eval": ev, "walk_forward": wf,
                                                         "deflated": defl,
                                                         "sender_fills": {"buy": buys, "sell": sells}},
                                                 indent=1, default=str), encoding="utf-8")
    (out / "select9.md").write_text(md, encoding="utf-8")
    (out / "select9_entries.json").write_text(json.dumps(res["entries"], default=str), encoding="utf-8")
    SM.save_rows(res["table"], {"until_ms": res["until_ms"], "days": res["days"]}, out / "select9_rows.parquet")
    print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
