"""Y12: P_pool0_wait with a ratcheting profit floor inside its 300 s, judged against P_pool0_wait at the paper
model's latency and at the latency the live executor measures. PAPER ONLY.

    python -m lab.pumpfun_rt.lock12                     replay, print the report, write lock12.{json,md}
    python -m lab.pumpfun_rt.lock12 --out DIR           the same, written into DIR

Pre-registered in results/pumpfun_lock_prereg.md. One replay of the record up to the cutoff with P_pool0_wait (X0)
and the three Y12 strategies (pipeline._build_y12, F1 to F3), each its own book of at most 4 positions, under two
latencies (A the paper engine's model, B Y9's measured Sender fills) and two daily loss limits (L25 the live bot's
0.25 SOL, L100 the code's cap of 1.0 SOL), every book drawing its latency with P_pool0's key (a migration's buy
lands at the same moment in all four books of a latency).

0.001005 SOL per transaction, 0.1 SOL a trade, trades open across a gap kept (Y8's rule). Out of sample: after the
middle of the record's time span (Y5 to Y11's split). Nothing here holds a wallet, reads a key, signs or sends
anything; the live executor's files are only read.
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

from . import curve as C
from . import exitlab as XL
from . import exits8 as X8
from . import pipeline as P
from . import reallat as RL
from . import select9 as Y9

# ---------------------------------------------------------------- registered (results/pumpfun_lock_prereg.md)

VARIANTS = (("X0", "P_pool0_wait"), ("F1", "P_pool0_wait_lock"), ("F2", "P_pool0_wait_lock_tight"),
            ("F3", "P_pool0_wait_lock_half"))
KEY = "P_pool0"                                         # every book's latency key, as Y8 to Y11
UNTIL_MS = int(datetime(2026, 10, 23, 16, 0, tzinfo=timezone.utc).timestamp() * 1000)
TAIL_MS = 15 * 60_000                                   # entries stop this long before the cutoff: all close inside
STAKE_SOL = 0.1
LIMITS = Y9.LIMITS
LIMIT_LABEL = Y9.LIMIT_LABEL
LATENCIES = ("A", "B")
LATENCY_LABEL = {"A": "the paper model's latency", "B": "the measured live latency"}
MIN_HOURS = XL.MIN_HOURS


def latencies() -> dict[str, C.Costs]:
    """A: the paper engine's own model (curve.Costs: median 1 s, 0.4 to 3 s, 0.001005 SOL a transaction); B: Y9's
    measured Sender fills (select9.scenarios()["B"], buy median about 10 s, sale about 4 s), as Y10 and Y11."""
    return {"A": C.Costs(priority_sol=RL.priority_for(Y9.TX_FEE_SOL)), "B": Y9.scenarios()["B"]}


def books() -> tuple[list[tuple[P.Strategy, P.Limits]], dict]:
    """Every variant once per latency and limit, `<name>@<latency>@<limit>`, at STAKE_SOL, P_pool0's key."""
    lat = latencies()
    out, costs = [], {}
    for a in LATENCIES:
        for k, lim in LIMITS.items():
            for _, name in VARIANTS:
                s = P.BY_NAME[name]
                v = dataclasses.replace(s, name=f"{name}@{a}@{k}", p={**s.p, "base": KEY}, stake_sol=STAKE_SOL)
                out.append((v, lim))
                costs[v.name] = lat[a]
    return out, costs


def entries(pipe, gaps) -> list[dict]:
    """exitlab.entries with the floor's fields (pipeline._close): None where no floor fired."""
    by = {(t["mint"], t["signal_ms"]): t for t in pipe.closed}
    out = XL.entries(pipe, gaps)
    for x in out:
        t = by.get((x["mint"], x["signal_ms"])) if not x["failed"] else None
        for k in ("lock_ms", "lock_sales"):
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
    log(f"lock12: {len(days)} day(s) {days[0]} to {days[-1]}, record to {_utc(t_hi)}, entries to "
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
    log(f"lock12: replay in {time.time() - t0:.0f} s, {len(eng.closed):,} closed, {len(eng.failed):,} failed buys")
    return {"days": days, "warm": warm, "span": (t_lo, t_hi), "until_ms": until_ms, "entry_until_ms": entry_until,
            "split_ms": split, "entries": {n: entries(p, eng.gaps) for n, p in pipes.items()},
            "skips": {n: p.skips for n, p in pipes.items()},
            "open_at_end": {n: len(p.pos) for n, p in pipes.items() if p.pos},
            "counts": dict(eng.counts), "gaps": list(eng.gaps)}


# ---------------------------------------------------------------- numbers

def floor_stats(e: list[dict], base: list[dict]) -> dict:
    """The entries of one book where a floor fired: their share of the closed trades, their mean return and P&L, and
    what X0 (the same latency and limit) did on the same migrations: its mean, its P&L, the share where the floor did
    better, X0's exits there. Paired by (mint, signal), so only where X0 entered the migration too."""
    closed = [x for x in e if not x["failed"]]
    f = [x for x in closed if x.get("lock_ms") is not None]
    if not f:
        return {"n": 0, "closed": len(closed)}
    by = {(x["mint"], x["signal_ms"]): x for x in base if not x["failed"]}
    pairs = [(x, by[(x["mint"], x["signal_ms"])]) for x in f if (x["mint"], x["signal_ms"]) in by]
    out = {"n": len(f), "closed": len(closed), "share": len(f) / len(closed),
           "mean": float(np.mean([x["ret"] for x in f])), "pnl_sol": float(sum(x["pnl_sol"] for x in f)),
           "exits": dict(sorted(Counter(x["exit_why"] or "?" for x in f).items())), "paired": len(pairs)}
    if pairs:
        out.update(x0_mean=float(np.mean([b["ret"] for _, b in pairs])),
                   x0_pnl_sol=float(sum(b["pnl_sol"] for _, b in pairs)),
                   lock_pnl_sol=float(sum(a["pnl_sol"] for a, _ in pairs)),
                   better=float(np.mean([a["ret"] > b["ret"] for a, b in pairs])),
                   x0_exits=dict(sorted(Counter(b["exit_why"] or "?" for _, b in pairs).items())))
    return out


def evaluate(res: dict, keep_gapped: bool = True) -> dict:
    """Per latency and limit: every book's out-of-sample numbers (gapped trades kept, as Y8; keep_gapped=False a
    robustness line), the in-sample ones (reported, not judged), its floors, and F1 to F3 against X0: the hour-paired
    band of the difference of the means over all entries and the total P&L (exits8.paired), and on the migrations
    both entered. A variant is better at a latency only if it is better under both limits."""
    split = res["split_ms"]
    table, is_table, vs = {}, {}, {}
    for a in LATENCIES:
        for k in LIMITS:
            c = f"{a}@{k}"
            table[c], is_table[c], vs[c] = {}, {}, {}
            ent = {}
            for x, name in VARIANTS:
                e = [y for y in res["entries"][f"{name}@{c}"] if keep_gapped or not y["gapped"]]
                oos = [y for y in e if y["signal_ms"] >= split]
                ent[x] = oos
                table[c][x] = XL.stats(oos) | {"name": name, "hours": XL.hours(oos)}
                is_table[c][x] = XL.stats([y for y in e if y["signal_ms"] < split]) | {"name": name}
                sk = [w for t, w in res["skips"][f"{name}@{c}"] if t >= split]
                table[c][x]["skipped"] = dict(sorted(Counter(sk).items()))
            b = table[c]["X0"]
            for x, _ in VARIANTS[1:]:
                table[c][x]["floor"] = floor_stats(ent[x], ent["X0"])
                v = X8.paired(ent[x], ent["X0"])
                v["common"] = XL.versus(ent[x], ent["X0"])
                v["pnl_diff"] = table[c][x].get("pnl_sol", 0.0) - b.get("pnl_sol", 0.0)
                v["pnl_higher"] = table[c][x].get("pnl_sol", -math.inf) > b.get("pnl_sol", math.inf)
                lo = v["band"][0]
                v["better"] = bool(math.isfinite(lo) and lo > 0 and v["pnl_higher"])
                vs[c][x] = v
    better = {a: {x: all(vs[f"{a}@{k}"][x]["better"] for k in LIMITS) for x, _ in VARIANTS[1:]} for a in LATENCIES}
    return {"table": table, "in_sample": is_table, "versus": vs, "better": better}


# ---------------------------------------------------------------- report

pct = RL.pct


def _band(b) -> str:
    return f"{pct(b[0])} to {pct(b[1])}"


def _utc(x) -> str:
    return f"{datetime.fromtimestamp(x / 1000, timezone.utc):%Y-%m-%d %H:%M} UTC"


def _table(ev: dict, c: str) -> list[str]:
    md = ["| book | strategy | entries | hours | failed buys | mean | median | win | P&L SOL | band of mean | "
          "max DD SOL | max open | daily loss limit |", "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for x, _ in VARIANTS:
        s = ev["table"][c][x]
        sk = s["skipped"]
        tail = f"{sk.get('max open positions', 0)} | {sk.get('daily loss limit', 0) + sk.get('daily loss stop', 0)} |"
        if not s.get("n"):
            md.append(f"| {x} | {s['name']} | 0 | 0 |" + " |" * 7 + " " + tail)
            continue
        md.append(f"| {x} | {s['name']} | {s['n']} | {s['hours']} | {s['failed']} | {pct(s['mean'])} | "
                  f"{pct(s['median'])} | {s['win'] * 100:.0f} % | {s['pnl_sol']:+.3f} | {_band(s['band'])} | "
                  f"{s['max_dd_sol']:.3f} | " + tail)
    md += ["", "| book | floor fired | of closed trades | their mean | their P&L SOL | paired with X0 | X0's mean there | "
           "X0's P&L there SOL | floor did better | X0's exits there | exits of the fired |",
           "|---|---|---|---|---|---|---|---|---|---|---|"]
    for x, _ in VARIANTS[1:]:
        f = ev["table"][c][x]["floor"]
        if not f.get("n"):
            md.append(f"| {x} | 0 |" + " |" * 9)
            continue
        md.append(f"| {x} | {f['n']} | {f['share'] * 100:.0f} % | {pct(f['mean'])} | {f['pnl_sol']:+.3f} | "
                  f"{f['paired']} | {pct(f.get('x0_mean'))} | {f.get('x0_pnl_sol', 0.0):+.3f} | "
                  f"{f.get('better', 0.0) * 100:.0f} % | " + ", ".join(f"{w} {n}" for w, n in f.get("x0_exits", {}).items())
                  + " | " + ", ".join(f"{w} {n}" for w, n in f["exits"].items()) + " |")
    md += ["", "| book | mean difference vs X0 | band (hours paired) | P&L difference SOL | total P&L higher | "
           "better than X0 | migrations both entered | their difference | band |",
           "|---|---|---|---|---|---|---|---|---|"]
    for x, _ in VARIANTS[1:]:
        v = ev["versus"][c][x]
        cm = v["common"]
        md.append(f"| {x} | {pct(v['diff'])} | {_band(v['band'])} | {v['pnl_diff']:+.3f} | "
                  f"{'yes' if v['pnl_higher'] else 'no'} | {'yes' if v['better'] else 'no'} | {cm['n']} | "
                  f"{pct(cm['diff'])} | {_band(cm['band'])} |")
    md += ["", "Exits: " + "; ".join(
        f"{x} " + ", ".join(f"{w} {n}" for w, n in ev["table"][c][x].get("exits", {}).items()) for x, _ in VARIANTS)]
    return md


def report_md(res: dict, ev: dict, dropped: dict, lat: dict) -> str:
    def ms(d):
        return f"{d['p50'] / 1000:.1f} s ({d['p10'] / 1000:.1f} to {d['p90'] / 1000:.1f})"
    md = ["# P_pool0_wait with a ratcheting profit floor (Y12)", "",
          f"Record {res['days'][0]} to {_utc(res['span'][1])}, entries to {_utc(res['entry_until_ms'])}, split "
          f"{_utc(res['split_ms'])}. Stake {STAKE_SOL} SOL, at most 4 open per book, "
          f"{lat['B']['tx_fee_sol']:.6f} SOL per transaction. Latency A (paper model) buy {ms(lat['A']['buy'])}, "
          f"sale {ms(lat['A']['sell'])}; B (measured live) buy {ms(lat['B']['buy'])}, sale {ms(lat['B']['sell'])}. "
          "Out of sample, trades open across a gap kept.", ""]
    for a in LATENCIES:
        md.append(f"Better than X0 under both limits, {LATENCY_LABEL[a]}: " + ", ".join(
            f"{x} {'yes' if v else 'no'}" for x, v in ev["better"][a].items()))
    for a in LATENCIES:
        for k in LIMITS:
            md += ["", f"## Out of sample, {LATENCY_LABEL[a]} ({a}), {LIMIT_LABEL[k]}", ""] + _table(ev, f"{a}@{k}")
    for a in LATENCIES:
        for k in LIMITS:
            md += ["", f"## {a}, {LIMIT_LABEL[k]}, trades open across a gap left out (robustness)", ""] + \
                _table(dropped, f"{a}@{k}")
    cs = [f"{a}@{k}" for a in LATENCIES for k in LIMITS]
    md += ["", "## In sample (not judged)", "", "| book | " + " | ".join(f"entries {c} | mean {c} | P&L SOL {c}"
                                                                         for c in cs) + " |",
           "|---|" + "---|" * (3 * len(cs))]
    for x, _ in VARIANTS:
        cells = []
        for c in cs:
            s = ev["in_sample"][c][x]
            cells += [str(s["n"]), pct(s.get("mean")), f"{s.get('pnl_sol', 0):+.3f}"]
        md.append(f"| {x} | " + " | ".join(cells) + " |")
    if res.get("open_at_end"):
        md += ["", f"Open at the end of the record: {res['open_at_end']}"]
    return "\n".join(md) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--until-ms", type=int, default=UNTIL_MS)
    ap.add_argument("--out", default=None, help="directory for lock12.json and lock12.md (default: the reports)")
    a = ap.parse_args(argv)
    from .. import report as rep
    out = Path(a.out) if a.out else rep.REPORTS / "pumpfun_rt"
    out.mkdir(parents=True, exist_ok=True)
    lat = {k: RL.describe(c) for k, c in latencies().items()}
    res = run(until_ms=a.until_ms)
    if res.get("empty"):
        print("lock12: nothing recorded")
        return 1
    ev = evaluate(res)
    dropped = evaluate(res, keep_gapped=False)
    md = report_md(res, ev, dropped, lat)
    keep = {k: v for k, v in res.items() if k not in ("entries", "skips")}
    (out / "lock12.json").write_text(json.dumps(keep | {"latency": lat, "eval": ev, "eval_gapped_dropped": dropped},
                                                indent=1, default=str), encoding="utf-8")
    (out / "lock12.md").write_text(md, encoding="utf-8")
    (out / "lock12_entries.json").write_text(json.dumps(res["entries"], default=str), encoding="utf-8")
    print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
