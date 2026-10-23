"""Y11: P_pool0_wait keeping a 20 % rest after its time stop, judged against P_pool0_wait at the latency the live
executor measures. PAPER ONLY.

    python -m lab.pumpfun_rt.runner11                   replay, print the report, write runner11.{json,md}
    python -m lab.pumpfun_rt.runner11 --out DIR         the same, written into DIR

Pre-registered in results/pumpfun_runner_prereg.md. One replay of the record up to the cutoff with P_pool0_wait (X0)
and the two Y11 strategies (pipeline._build_y11, R1 and R2), each its own book of at most 4 positions, under the live
daily loss limit of 0.25 SOL (L25) and under the code's cap of 1.0 SOL (L100), both judged, every book drawing its
latency with P_pool0's key (a migration's buy and its time-stop sale land at the same moment in all three books).

Fills at Y9's registered latency (select9.SENDER_BUY_MS, SENDER_SELL_MS), 0.001005 SOL per transaction, 0.1 SOL a
trade, trades open across a gap kept (Y8's rule). Out of sample: after the middle of the record's time span (Y5 to
Y8's split). Nothing here holds a wallet, reads a key, signs or sends anything; the live executor's files are only
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
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from . import exitlab as XL
from . import exits8 as X8
from . import pipeline as P
from . import reallat as RL
from . import select9 as Y9

# ---------------------------------------------------------------- registered (results/pumpfun_runner_prereg.md)

VARIANTS = (("X0", "P_pool0_wait"), ("R1", "P_pool0_wait_run20"), ("R2", "P_pool0_wait_run20w"))
KEY = "P_pool0"                                         # every book's latency key, as Y8 to Y10
UNTIL_MS = int(datetime(2026, 10, 23, 15, 0, tzinfo=timezone.utc).timestamp() * 1000)
TAIL_MS = 75 * 60_000                                   # entries stop this long before the cutoff: all close inside
STAKE_SOL = 0.1
LIMITS = Y9.LIMITS
LIMIT_LABEL = Y9.LIMIT_LABEL
MIN_HOURS = XL.MIN_HOURS


def books() -> tuple[list[tuple[P.Strategy, P.Limits]], dict]:
    """Every variant once per limit, `<name>@<limit>`, at STAKE_SOL and Y9's measured latency, P_pool0's key."""
    b = Y9.scenarios()["B"]
    out, costs = [], {}
    for k, lim in LIMITS.items():
        for _, name in VARIANTS:
            s = P.BY_NAME[name]
            v = dataclasses.replace(s, name=f"{name}@{k}", p={**s.p, "base": KEY}, stake_sol=STAKE_SOL)
            out.append((v, lim))
            costs[v.name] = b
    return out, costs


def entries(pipe, gaps) -> list[dict]:
    """exitlab.entries with the rest's fields of a runner (pipeline._close): None where no rest was kept."""
    by = {(t["mint"], t["signal_ms"]): t for t in pipe.closed}
    out = XL.entries(pipe, gaps)
    for x in out:
        t = by.get((x["mint"], x["signal_ms"])) if not x["failed"] else None
        for k in ("run_from_ms", "run_high", "run_cost_sol", "run_pnl_sol", "run_vs_time_sol"):
            x[k] = None if t is None else t.get(k)
    return out


# ---------------------------------------------------------------- the run

def run(root=None, until_ms: int = UNTIL_MS, log=print, tail_ms: int = TAIL_MS) -> dict:
    from . import early as EA
    from . import sim, store
    from . import wallets as W
    from .study import WARM_DAYS, WINDOW_DAYS, span_of, warm_book
    cutoff_day = datetime.fromtimestamp(until_ms / 1000, timezone.utc).strftime("%Y-%m-%d")
    all_days = [d for d in store.days(root) if d <= cutoff_day]
    days = all_days[-WINDOW_DAYS:]
    if not days:
        return {"empty": True}
    warm = [d for d in all_days if d < days[0]][-WARM_DAYS:]
    t_lo, t_hi = span_of(days, root)
    t_hi = min(t_hi, until_ms)
    entry_until = t_hi - tail_ms
    split = t_lo + (t_hi - t_lo) // 2
    log(f"runner11: {len(days)} day(s) {days[0]} to {days[-1]}, record to {_utc(t_hi)}, entries to "
        f"{_utc(entry_until)}, split {_utc(split)}, warm-up {len(warm)} day(s)")
    t0 = time.time()
    strats, costs = books()
    eng = sim.Engine([], book=warm_book(warm, root), decisions=False, rule_costs=costs, entry_until=entry_until,
                     wallets=W.warm(warm, root), snipers=EA.warm_snipers(warm, root))
    pipes = {s.name: eng.add_pipe(XL.PeakPipe(eng, [s], P.PaperExecutor(), limits=lim, name=s.name))
             for s, lim in strats}
    sim.replay(days, eng, root, until_ms=t_hi)
    for pipe in pipes.values():
        pipe.finish(eng.now)
    log(f"runner11: replay in {time.time() - t0:.0f} s, {len(eng.closed):,} closed, {len(eng.failed):,} failed buys")
    return {"days": days, "warm": warm, "span": (t_lo, t_hi), "until_ms": until_ms, "entry_until_ms": entry_until,
            "split_ms": split, "entries": {n: entries(p, eng.gaps) for n, p in pipes.items()},
            "skips": {n: p.skips for n, p in pipes.items()},
            "open_at_end": {n: len(p.pos) for n, p in pipes.items() if p.pos},
            "counts": dict(eng.counts), "gaps": list(eng.gaps)}


# ---------------------------------------------------------------- numbers

def rest_stats(e: list[dict]) -> dict:
    """The rests of one book: how many entries kept one, the share whose rest made money (its sale proceeds after
    its own fee above its share of the buy's cost), the share that beat selling the rest with the 80 % (pro rata),
    the worst rest loss in SOL and over its cost, the sum of what the rests added against that sale, their exits."""
    r = [x for x in e if x.get("run_from_ms") is not None]
    if not r:
        return {"n": 0}
    pnl = np.array([x["run_pnl_sol"] for x in r])
    vs = np.array([x["run_vs_time_sol"] for x in r])
    cost = np.array([x["run_cost_sol"] for x in r])
    i = int(np.argmin(pnl))
    return {"n": len(r), "made_money": float((pnl > 0).mean()), "beat_time": float((vs > 0).mean()),
            "pnl_sol": float(pnl.sum()), "added_sol": float(vs.sum()), "worst_sol": float(pnl[i]),
            "worst_ret": float(pnl[i] / cost[i]) if cost[i] > 0 else None, "best_sol": float(pnl.max()),
            "exits": dict(sorted(Counter(x["exit_why"] or "?" for x in r).items()))}


def evaluate(res: dict, keep_gapped: bool = True) -> dict:
    """Per limit: every book's out-of-sample numbers (gapped trades kept, as Y8; keep_gapped=False a robustness line),
    the in-sample ones (reported, not judged), its rests, and R1 and R2 against X0: the hour-paired band of the
    difference of the means over all entries and the total P&L (exits8.paired), and on the migrations both entered."""
    split = res["split_ms"]
    table, is_table, vs = {}, {}, {}
    for k in LIMITS:
        table[k], is_table[k], vs[k] = {}, {}, {}
        ent = {}
        for x, name in VARIANTS:
            e = [y for y in res["entries"][f"{name}@{k}"] if keep_gapped or not y["gapped"]]
            oos = [y for y in e if y["signal_ms"] >= split]
            ent[x] = oos
            table[k][x] = XL.stats(oos) | {"name": name, "rest": rest_stats(oos), "hours": XL.hours(oos)}
            is_table[k][x] = XL.stats([y for y in e if y["signal_ms"] < split]) | {"name": name}
            sk = [w for t, w in res["skips"][f"{name}@{k}"] if t >= split]
            table[k][x]["skipped"] = dict(sorted(Counter(sk).items()))
        b = table[k]["X0"]
        for x, _ in VARIANTS[1:]:
            v = X8.paired(ent[x], ent["X0"])
            v["common"] = XL.versus(ent[x], ent["X0"])
            v["pnl_higher"] = table[k][x].get("pnl_sol", -math.inf) > b.get("pnl_sol", math.inf)
            lo = v["band"][0]
            v["better"] = bool(math.isfinite(lo) and lo > 0 and v["pnl_higher"])
            vs[k][x] = v
    better = {x: all(vs[k][x]["better"] for k in LIMITS) for x, _ in VARIANTS[1:]}
    return {"table": table, "in_sample": is_table, "versus": vs, "better": better}


# ---------------------------------------------------------------- report

pct = RL.pct


def _band(b) -> str:
    return f"{pct(b[0])} to {pct(b[1])}"


def _utc(x) -> str:
    return f"{datetime.fromtimestamp(x / 1000, timezone.utc):%Y-%m-%d %H:%M} UTC"


def _table(ev: dict, k: str) -> list[str]:
    md = ["| book | strategy | entries | hours | failed buys | mean | median | win | P&L SOL | band of mean | "
          "max DD SOL | max open | daily loss limit |", "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for x, _ in VARIANTS:
        s = ev["table"][k][x]
        sk = s["skipped"]
        tail = f"{sk.get('max open positions', 0)} | {sk.get('daily loss limit', 0) + sk.get('daily loss stop', 0)} |"
        if not s.get("n"):
            md.append(f"| {x} | {s['name']} | 0 | 0 |" + " |" * 7 + " " + tail)
            continue
        md.append(f"| {x} | {s['name']} | {s['n']} | {s['hours']} | {s['failed']} | {pct(s['mean'])} | "
                  f"{pct(s['median'])} | {s['win'] * 100:.0f} % | {s['pnl_sol']:+.3f} | {_band(s['band'])} | "
                  f"{s['max_dd_sol']:.3f} | " + tail)
    md += ["", "| book | rests kept | rest made money | rest beat selling at 300 s | rests' P&L SOL | "
           "added against the sale at 300 s, SOL | worst rest SOL | worst over its cost | best rest SOL | rest exits |",
           "|---|---|---|---|---|---|---|---|---|---|"]
    for x, _ in VARIANTS[1:]:
        r = ev["table"][k][x]["rest"]
        if not r.get("n"):
            md.append(f"| {x} | 0 |" + " |" * 8)
            continue
        md.append(f"| {x} | {r['n']} | {r['made_money'] * 100:.0f} % | {r['beat_time'] * 100:.0f} % | "
                  f"{r['pnl_sol']:+.4f} | {r['added_sol']:+.4f} | {r['worst_sol']:+.4f} | {pct(r['worst_ret'])} | "
                  f"{r['best_sol']:+.4f} | " + ", ".join(f"{w} {c}" for w, c in r["exits"].items()) + " |")
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


def report_md(res: dict, ev: dict, dropped: dict, lat: dict) -> str:
    def ms(d):
        return f"{d['p50'] / 1000:.1f} s ({d['p10'] / 1000:.1f} to {d['p90'] / 1000:.1f})"
    b = lat["B"]
    md = ["# P_pool0_wait with a 20 % rest after the time stop (Y11)", "",
          f"Record {res['days'][0]} to {_utc(res['span'][1])}, entries to {_utc(res['entry_until_ms'])}, split "
          f"{_utc(res['split_ms'])}. Stake {STAKE_SOL} SOL, at most 4 open per book; latency buy {ms(b['buy'])}, "
          f"sale {ms(b['sell'])}, {b['tx_fee_sol']:.6f} SOL per transaction. Out of sample, trades open across a gap "
          "kept.", "", "Better than X0 under both limits: " + ", ".join(
              f"{x} {'yes' if v else 'no'}" for x, v in ev["better"].items())]
    for k in LIMITS:
        md += ["", f"## Out of sample, {LIMIT_LABEL[k]}", ""] + _table(ev, k)
    for k in LIMITS:
        md += ["", f"## {LIMIT_LABEL[k]}, trades open across a gap left out (robustness)", ""] + _table(dropped, k)
    md += ["", "## In sample (not judged)", "", "| book | " + " | ".join(f"entries {k} | mean {k} | P&L SOL {k}"
                                                                         for k in LIMITS) + " |",
           "|---|" + "---|" * (3 * len(LIMITS))]
    for x, _ in VARIANTS:
        cells = []
        for k in LIMITS:
            s = ev["in_sample"][k][x]
            cells += [str(s["n"]), pct(s.get("mean")), f"{s.get('pnl_sol', 0):+.3f}"]
        md.append(f"| {x} | " + " | ".join(cells) + " |")
    if res.get("open_at_end"):
        md += ["", f"Open at the end of the record: {res['open_at_end']}"]
    return "\n".join(md) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--until-ms", type=int, default=UNTIL_MS)
    ap.add_argument("--out", default=None, help="directory for runner11.json and runner11.md (default: the reports)")
    ap.add_argument("--live-dir", default=None, help="the live executor's folder (read only)")
    a = ap.parse_args(argv)
    from .. import report as rep
    from ..data import ROOT
    out = Path(a.out) if a.out else rep.REPORTS / "pumpfun_rt"
    out.mkdir(parents=True, exist_ok=True)
    live_dir = Path(a.live_dir) if a.live_dir else ROOT / "live" / "pumpfun_rt"
    buys, sells = XL.sender_fills(XL.read_jsonl(live_dir / "measured.jsonl"), until_ms=a.until_ms)
    if (tuple(buys), tuple(sells)) != (Y9.SENDER_BUY_MS, Y9.SENDER_SELL_MS):
        print(f"runner11: the measured file now gives buys {buys} and sales {sells}; the registered points are used")
    lat = {k: RL.describe(c) for k, c in Y9.scenarios().items()}
    res = run(until_ms=a.until_ms)
    if res.get("empty"):
        print("runner11: nothing recorded")
        return 1
    ev = evaluate(res)
    dropped = evaluate(res, keep_gapped=False)
    md = report_md(res, ev, dropped, lat)
    keep = {k: v for k, v in res.items() if k not in ("entries", "skips")}
    (out / "runner11.json").write_text(json.dumps(keep | {"latency": lat, "eval": ev, "eval_gapped_dropped": dropped,
                                                          "sender_fills": {"buy": buys, "sell": sells}},
                                                  indent=1, default=str), encoding="utf-8")
    (out / "runner11.md").write_text(md, encoding="utf-8")
    (out / "runner11_entries.json").write_text(json.dumps(res["entries"], default=str), encoding="utf-8")
    print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
