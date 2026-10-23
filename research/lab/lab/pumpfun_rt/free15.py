"""Y15: P_pool0_wait with a free ride after a fast spike (the stake and the fees back at +30 %, the rest rides a
trail), judged against P_pool0_wait at the paper model's latency and at the latency the live executor measures.
PAPER ONLY.

    python -m lab.pumpfun_rt.free15                     replay, print the report, write free15.{json,md}
    python -m lab.pumpfun_rt.free15 --out DIR           the same, written into DIR

Pre-registered in results/pumpfun_freeride_prereg.md. One replay of the record up to the cutoff with P_pool0_wait
(X0) and the four Y15 strategies (pipeline._build_y15), each its own book of at most 4 positions, under two latencies
(A the paper engine's model, B Y9's measured Sender fills) and two daily loss limits (L25 the live bot's 0.25 SOL,
L100 the code's cap of 1.0 SOL), every book drawing its latency with P_pool0's key, as Y12.

0.001005 SOL per transaction, 0.1 SOL a trade, trades open across a gap kept (Y8's rule). Out of sample: after the
middle of the record's time span (Y5 to Y12's split). Nothing here holds a wallet, reads a key, signs or sends
anything.
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
from . import lock12 as Y12
from . import pipeline as P
from . import reallat as RL

# ---------------------------------------------------------------- registered (results/pumpfun_freeride_prereg.md)

VARIANTS = (("X0", "P_pool0_wait"), ("V10", "P_pool0_wait_free10"), ("V30", "P_pool0_wait_free30"),
            ("VA", "P_pool0_wait_free_any"), ("V10T", "P_pool0_wait_free10_tight"))
KEY = Y12.KEY
UNTIL_MS = int(datetime(2026, 10, 23, 17, 0, tzinfo=timezone.utc).timestamp() * 1000)
TAIL_MS = 35 * 60_000                                   # a rest holds at most 30 min after the landing: all close inside
STAKE_SOL = 0.1
LIMITS = Y12.LIMITS
LIMIT_LABEL = Y12.LIMIT_LABEL
LATENCIES = Y12.LATENCIES
LATENCY_LABEL = Y12.LATENCY_LABEL
FIELDS = ("free_first_s", "free_ms", "free_part_sol", "free_floor", "free_high", "rest_cost_sol", "rest_pnl_sol",
          "rest_vs_take_sol")
latencies = Y12.latencies


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
    """exitlab.entries with the free ride's fields (pipeline._close): None where they are not set."""
    by = {(t["mint"], t["signal_ms"]): t for t in pipe.closed}
    out = XL.entries(pipe, gaps)
    for x in out:
        t = by.get((x["mint"], x["signal_ms"])) if not x["failed"] else None
        for k in FIELDS:
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
    log(f"free15: {len(days)} day(s) {days[0]} to {days[-1]}, record to {_utc(t_hi)}, entries to "
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
    log(f"free15: replay in {time.time() - t0:.0f} s, {len(eng.closed):,} closed, {len(eng.failed):,} failed buys")
    return {"days": days, "warm": warm, "span": (t_lo, t_hi), "until_ms": until_ms, "entry_until_ms": entry_until,
            "split_ms": split, "entries": {n: entries(p, eng.gaps) for n, p in pipes.items()},
            "skips": {n: p.skips for n, p in pipes.items()},
            "open_at_end": {n: len(p.pos) for n, p in pipes.items() if p.pos},
            "counts": dict(eng.counts), "gaps": list(eng.gaps)}


# ---------------------------------------------------------------- numbers

def ride_stats(e: list[dict], base: list[dict]) -> dict:
    """One book's free rides: how often the +30 % was seen and how often the spike rule fired (a partial sale), what
    the rests made over their cost (median, best, share above zero, P&L), what they gave up against selling them with
    the partial sale (rest_vs_take_sol, at that sale's price), their exits, and the whole trades against X0's trade on
    the same migration (same latency and limit, paired by mint and signal: X0 sold everything at its +30 % there)."""
    closed = [x for x in e if not x["failed"]]
    hit = [x for x in closed if x.get("free_first_s") is not None]
    f = [x for x in closed if x.get("free_ms") is not None]
    out = {"closed": len(closed), "hit30": len(hit), "n": len(f), "share": len(f) / len(closed) if closed else 0.0,
           "first_s": float(np.median([x["free_first_s"] for x in hit])) if hit else None}
    if not f:
        return out
    rr = np.array([x["rest_pnl_sol"] / x["rest_cost_sol"] for x in f])
    gave = np.array([x["rest_vs_take_sol"] for x in f])
    out.update(mean=float(np.mean([x["ret"] for x in f])), pnl_sol=float(sum(x["pnl_sol"] for x in f)),
               rest_median=float(np.median(rr)), rest_best=float(rr.max()), rest_worst=float(rr.min()),
               rest_up=float((rr > 0).mean()), rest_pnl_sol=float(sum(x["rest_pnl_sol"] for x in f)),
               rest_cost_sol=float(np.mean([x["rest_cost_sol"] for x in f])),
               vs_take_sol=float(gave.sum()), vs_take_up=float((gave > 0).mean()),
               part_sol=float(np.median([x["free_part_sol"] for x in f])),
               exits=dict(sorted(Counter(x["exit_why"] or "?" for x in f).items())))
    by = {(x["mint"], x["signal_ms"]): x for x in base if not x["failed"]}
    pairs = [(x, by[(x["mint"], x["signal_ms"])]) for x in f if (x["mint"], x["signal_ms"]) in by]
    out["paired"] = len(pairs)
    if pairs:
        out.update(x0_mean=float(np.mean([b["ret"] for _, b in pairs])),
                   own_pnl_sol=float(sum(a["pnl_sol"] for a, _ in pairs)),
                   x0_pnl_sol=float(sum(b["pnl_sol"] for _, b in pairs)),
                   better=float(np.mean([a["ret"] > b["ret"] for a, b in pairs])),
                   x0_exits=dict(sorted(Counter(b["exit_why"] or "?" for _, b in pairs).items())))
    return out


def evaluate(res: dict, keep_gapped: bool = True) -> dict:
    """Per latency and limit: every book's out-of-sample numbers (gapped trades kept, as Y8; keep_gapped=False a
    robustness line), the in-sample ones (reported, not judged), its free rides, and each variant against X0: the
    hour-paired band of the difference of the means over all entries and the total P&L (exits8.paired), and on the
    migrations both entered. A variant is better at a latency only if it is better under both limits."""
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
                table[c][x]["ride"] = ride_stats(ent[x], ent["X0"])
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
_band = Y12._band
_utc = Y12._utc


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
    md += ["", "| book | +30 % seen | its median s after landing | spike rule fired | of closed | partial sale SOL "
           "(median) | rest over its cost: median | best | worst | above zero | rests' P&L SOL | rests against selling "
           "them with the partial SOL | rest did better | exits |", "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for x, _ in VARIANTS[1:]:
        f = ev["table"][c][x]["ride"]
        first = "" if f["first_s"] is None else f"{f['first_s']:.1f}"
        head = f"| {x} | {f['hit30']} | {first} | {f['n']} | "
        if not f.get("n"):
            md.append(head + "0 % |" + " |" * 9)
            continue
        md.append(head + f"{f['share'] * 100:.0f} % | {f['part_sol']:.4f} | {pct(f['rest_median'])} | "
                  f"{pct(f['rest_best'])} | {pct(f['rest_worst'])} | {f['rest_up'] * 100:.0f} % | "
                  f"{f['rest_pnl_sol']:+.4f} | {f['vs_take_sol']:+.4f} | {f['vs_take_up'] * 100:.0f} % | "
                  + ", ".join(f"{w} {n}" for w, n in f["exits"].items()) + " |")
    md += ["", "| book | rides | their mean | their P&L SOL | paired with X0 | X0's mean there | X0's P&L there SOL | "
           "ride did better | X0's exits there |", "|---|---|---|---|---|---|---|---|---|"]
    for x, _ in VARIANTS[1:]:
        f = ev["table"][c][x]["ride"]
        if not f.get("n"):
            md.append(f"| {x} | 0 |" + " |" * 7)
            continue
        md.append(f"| {x} | {f['n']} | {pct(f['mean'])} | {f['pnl_sol']:+.3f} | {f['paired']} | "
                  f"{pct(f.get('x0_mean'))} | {f.get('x0_pnl_sol', 0.0):+.3f} | {f.get('better', 0.0) * 100:.0f} % | "
                  + ", ".join(f"{w} {n}" for w, n in f.get("x0_exits", {}).items()) + " |")
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
    md = ["# P_pool0_wait with a free ride after a fast spike (Y15)", "",
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
    ap.add_argument("--out", default=None, help="directory for free15.json and free15.md (default: the reports)")
    a = ap.parse_args(argv)
    from .. import report as rep
    out = Path(a.out) if a.out else rep.REPORTS / "pumpfun_rt"
    out.mkdir(parents=True, exist_ok=True)
    lat = {k: RL.describe(c) for k, c in latencies().items()}
    res = run(until_ms=a.until_ms)
    if res.get("empty"):
        print("free15: nothing recorded")
        return 1
    ev = evaluate(res)
    dropped = evaluate(res, keep_gapped=False)
    md = report_md(res, ev, dropped, lat)
    keep = {k: v for k, v in res.items() if k not in ("entries", "skips")}
    (out / "free15.json").write_text(json.dumps(keep | {"latency": lat, "eval": ev, "eval_gapped_dropped": dropped},
                                                indent=1, default=str), encoding="utf-8")
    (out / "free15.md").write_text(md, encoding="utf-8")
    (out / "free15_entries.json").write_text(json.dumps(res["entries"], default=str), encoding="utf-8")
    print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
