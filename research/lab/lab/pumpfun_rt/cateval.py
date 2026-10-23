"""P_pool0_wait with and without the live category rule (livecat.py, the owner's decision of 2026-10-23: no coin of
category celebrity, copycat or scam), on the recorded history with the daily categories. PAPER ONLY; the rule goes
live regardless, this only says what it would have done.

    python -m lab.pumpfun_rt.cateval                    replay, print the report, write cateval.{json,md}
    python -m lab.pumpfun_rt.cateval --out DIR          the same, written into DIR

One replay of the record up to the cutoff with two books per daily loss limit (L25 the live bot's 0.25 SOL, L100 the
code's cap; at most 4 open each, 0.1 SOL a trade, 0.001005 SOL a transaction) under the measured live latency (Y9's
Sender fills, lock12.latencies "B"), P_pool0's latency key in both: X0 P_pool0_wait as it ran, XC the same with the
rule (OfflineRule). Live, the classifier and the single call at the buy give nearly every coin its category before
the buy; the record's categories come from the daily job, written the next morning, so the offline rule takes a
name's category whenever it was written (no look-ahead in prices, only in that label) and keeps a coin without one
(counted). The daily answers predate the prompt's brand and people guidance, so they label fewer brand copies than
the live classifier will. Out of sample: after the middle of the record's time span (Y5 to Y15's split).
"""

from __future__ import annotations

import argparse
import dataclasses
import json
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
from .blocklist import DEFAULT_CATEGORIES

BASE = "P_pool0_wait"
VARIANTS = (("X0", False), ("XC", True))
KEY = Y12.KEY
UNTIL_MS = int(datetime(2026, 10, 23, 21, 0, tzinfo=timezone.utc).timestamp() * 1000)
TAIL_MS = 15 * 60_000
STAKE_SOL = 0.1
LIMITS = Y12.LIMITS
LIMIT_LABEL = Y12.LIMIT_LABEL
LATENCY = "B"
RUG = -0.5                                              # an entry that lost half or more: a rug
_utc = Y12._utc
pct = RL.pct


class OfflineRule:
    """Pipeline.category in a replay: a name's daily category whenever it was written; a coin without one is kept
    (counted at the buy). `enforce=False` only notes each coin's category (X0)."""

    def __init__(self, ix, blocked=DEFAULT_CATEGORIES, enforce: bool = True):
        from .categorize import name_key
        self.ix, self.blocked, self.enforce, self.key = ix, frozenset(blocked), enforce, name_key
        self.cat: dict[str, str | None] = {}
        self.unknown = 0

    def __call__(self, rule: str, tok, at_buy: bool = False) -> str | None:
        hit = self.ix.keys.get(self.key(getattr(tok, "name", "") or "", getattr(tok, "symbol", "") or ""))
        c = hit[1] if hit is not None else None
        self.cat[tok.mint] = c
        if c is None:
            self.unknown += int(at_buy)
            return None
        return f"category {c}" if self.enforce and c in self.blocked else None


def books() -> list[tuple[str, P.Strategy, P.Limits, bool]]:
    out = []
    for k, lim in LIMITS.items():
        for x, rule in VARIANTS:
            s = P.BY_NAME[BASE]
            out.append((x, dataclasses.replace(s, name=f"{BASE}@{x}@{k}", p={**s.p, "base": KEY}, stake_sol=STAKE_SOL),
                        lim, rule))
    return out


def run(root=None, until_ms: int = UNTIL_MS, log=print, tail_ms: int = TAIL_MS, ix=None) -> dict:
    from . import early as EA
    from . import sim, store
    from . import wallets as W
    from .categorize import CategoryIndex
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
    ix = ix if ix is not None else CategoryIndex.load(None if root is None else Path(root) / "categories", mints=False)
    log(f"cateval: {len(days)} day(s) {days[0]} to {days[-1]}, record to {_utc(t_hi)}, split {_utc(split)}, "
        f"{len(ix):,} names with a category")
    t0 = time.time()
    lat = Y12.latencies()[LATENCY]
    strats = books()
    eng = sim.Engine([], book=warm_book(warm, root), decisions=False, rule_costs={s.name: lat for _, s, _, _ in strats},
                     entry_until=entry_until, wallets=W.warm(warm, root), snipers=EA.warm_snipers(warm, root))
    pipes, rules = {}, {}
    for x, s, lim, enforce in strats:
        pipe = eng.add_pipe(XL.PeakPipe(eng, [s], P.PaperExecutor(), limits=lim, name=s.name))
        pipe.category = rules[s.name] = OfflineRule(ix, enforce=enforce)
        pipes[s.name] = pipe
    sim.replay(days, eng, root, until_ms=t_hi)
    for pipe in pipes.values():
        pipe.finish(eng.now)
    log(f"cateval: replay in {time.time() - t0:.0f} s, {len(eng.closed):,} closed, {len(eng.failed):,} failed buys")
    ent = {}
    for n, p in pipes.items():
        e = XL.entries(p, eng.gaps)
        for y in e:
            y["cat"] = rules[n].cat.get(y["mint"])
        ent[n] = e
    return {"days": days, "span": (t_lo, t_hi), "until_ms": until_ms, "split_ms": split, "entries": ent,
            "skips": {n: p.skips for n, p in pipes.items()}, "unknown_at_buy": {n: r.unknown for n, r in rules.items()},
            "gaps": list(eng.gaps)}


def _mean(e: list[dict]) -> float | None:
    return float(np.mean([x["ret"] for x in e])) if e else None


def evaluate(res: dict, blocked=DEFAULT_CATEGORIES) -> dict:
    """Per limit, out of sample: X0 and XC's numbers, X0's entries the rule would have left out (by category, the
    rugs among them, the winners), and XC against X0 (the hour-paired band of the difference of the means)."""
    split, out = res["split_ms"], {}
    for k in LIMITS:
        e0 = [y for y in res["entries"][f"{BASE}@X0@{k}"] if y["signal_ms"] >= split]
        ec = [y for y in res["entries"][f"{BASE}@XC@{k}"] if y["signal_ms"] >= split]
        cut = [y for y in e0 if y["cat"] in blocked]
        kept = [y for y in e0 if y["cat"] not in blocked]
        sk = Counter(w for t, w in res["skips"][f"{BASE}@XC@{k}"] if t >= split and w.startswith("category"))
        out[k] = {"X0": XL.stats(e0), "XC": XL.stats(ec), "kept": len(kept), "kept_mean": _mean(kept),
                  "cut": len(cut), "cut_mean": _mean(cut), "cut_pnl_sol": float(sum(y["pnl_sol"] for y in cut)),
                  "cut_by_cat": dict(sorted(Counter(y["cat"] for y in cut).items())),
                  "rugs_avoided": sum(1 for y in cut if y["ret"] <= RUG), "rugs_x0": sum(1 for y in e0 if y["ret"] <= RUG),
                  "winners_lost": sum(1 for y in cut if y["ret"] > 0), "winners_x0": sum(1 for y in e0 if y["ret"] > 0),
                  "no_category": sum(1 for y in e0 if y["cat"] is None), "skips": dict(sorted(sk.items())),
                  "versus": X8.paired(ec, e0), "cats_x0": dict(sorted(Counter(y["cat"] or "none" for y in e0).items()))}
    return out


def report_md(res: dict, ev: dict, lat: dict) -> str:
    b = lat[LATENCY]
    md = ["# P_pool0_wait with and without the category rule (celebrity, copycat, scam)", "",
          f"Record {res['days'][0]} to {_utc(res['span'][1])}, split {_utc(res['split_ms'])}, out of sample after it. "
          f"Measured live latency: buy {b['buy']['p50'] / 1000:.1f} s, sale {b['sell']['p50'] / 1000:.1f} s (median). "
          f"Stake {STAKE_SOL} SOL, at most 4 open, a rug is {RUG * 100:.0f} % or worse. The daily categories, taken "
          "whenever written; a coin without one is kept.", "",
          "| limit | X0 entries | X0 mean | X0 P&L SOL | XC entries | XC mean | XC P&L SOL | left out | their mean | "
          "their P&L SOL | rugs avoided | winners lost | without category | XC - X0 mean, band |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for k in LIMITS:
        v = ev[k]
        a, c = v["X0"], v["XC"]
        band = v["versus"]["band"]
        md.append(f"| {LIMIT_LABEL[k]} | {a['n']} | {pct(a.get('mean'))} | {a.get('pnl_sol', 0):+.3f} | {c['n']} | "
                  f"{pct(c.get('mean'))} | {c.get('pnl_sol', 0):+.3f} | {v['cut']} | {pct(v['cut_mean'])} | "
                  f"{v['cut_pnl_sol']:+.3f} | {v['rugs_avoided']} of {v['rugs_x0']} | {v['winners_lost']} of "
                  f"{v['winners_x0']} | {v['no_category']} | {pct(v['versus']['diff'])} ({pct(band[0])} to "
                  f"{pct(band[1])}) |")
    for k in LIMITS:
        md += ["", f"{LIMIT_LABEL[k]}: left out by category {ev[k]['cut_by_cat']}; X0's entries by category "
               f"{ev[k]['cats_x0']}; XC's category skips {ev[k]['skips']}"]
    return "\n".join(md) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--until-ms", type=int, default=UNTIL_MS)
    ap.add_argument("--out", default=None, help="directory for cateval.json and cateval.md (default: the reports)")
    a = ap.parse_args(argv)
    from .. import report as rep
    out = Path(a.out) if a.out else rep.REPORTS / "pumpfun_rt"
    out.mkdir(parents=True, exist_ok=True)
    lat = {LATENCY: RL.describe(Y12.latencies()[LATENCY])}
    res = run(until_ms=a.until_ms)
    if res.get("empty"):
        print("cateval: nothing recorded")
        return 1
    ev = evaluate(res)
    md = report_md(res, ev, lat)
    keep = {k: v for k, v in res.items() if k not in ("entries", "skips")}
    (out / "cateval.json").write_text(json.dumps(keep | {"latency": lat, "eval": ev}, indent=1, default=str),
                                      encoding="utf-8")
    (out / "cateval.md").write_text(md, encoding="utf-8")
    print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
