"""Y7: exits that let P_pool0's runners run, at the latency the live executor measures since the Sender path.
PAPER ONLY.

    python -m lab.pumpfun_rt.exitlab                    replay, print the report, write exitlab.{json,md}
    python -m lab.pumpfun_rt.exitlab --out DIR          the same, written into DIR

Pre-registered in results/pumpfun_exit_runners_prereg.md. P_pool0 (X0) and the five Y7 strategies
(pipeline._build_y7, X1 to X5) replayed on the record, each as its own book of at most MAX_OPEN positions
with one shared Risk, under two scenarios:

  B    the measured latency: Y5's kernel density in log space (reallat.LogKDE) of the live executor's
       P_pool0 fills since the Sender path (SENDER_BUY_MS, SENDER_SELL_MS), buys and sales apart
  C    Y5's 1.5 s send path (lognormal median 1.5 s, clipped to 1 to 2 s), as a robustness line

0.001005 SOL per transaction plus the 0.000005 SOL Sender tip, 0.1 SOL a trade. Every book draws its
latency with P_pool0's key, so a migration lands at the same moment for all six: they differ by their
exits and by the slots their open positions hold. Judged out of sample at B against X0, paired by
migration. Nothing here holds a wallet, reads a key, signs or sends anything; the live executor's files
are only read.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import math
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from . import curve as C
from . import pipeline as P
from . import reallat as RL

# ---------------------------------------------------------------- registered (results/pumpfun_exit_runners_prereg.md)

VARIANTS = (("X0", "P_pool0"), ("X1", "P_pool0_half_trail"), ("X2", "P_pool0_ladder3"), ("X3", "P_pool0_trail"),
            ("X4", "P_pool0_half_trail_guard"), ("X5", "P_pool0_half_trail_ext"))
BASE = "P_pool0"
KEY = "P_pool0"                                         # every book's latency key: one draw per migration and leg
SENDER_FROM_MS = int(datetime(2026, 10, 22, 21, 41, tzinfo=timezone.utc).timestamp() * 1000)
UNTIL_MS = int(datetime(2026, 10, 23, 0, 0, tzinfo=timezone.utc).timestamp() * 1000)
TAIL_MS = 90 * 60_000                                   # entries stop this long before the cutoff: all close inside
# The executor's P_pool0 fills, signal to landing (ms), 2026-10-22 21:41 UTC to the cutoff; at or under 0 ms and
# under 1 s set to the 1 s floor and over 60 s to the 60 s cap, as the model's draws are clipped.
SENDER_BUY_MS = (1000.0, 21423.0, 10827.0, 1000.0, 29589.0, 60000.0)
SENDER_SELL_MS = (38000.0, 1000.0, 1000.0, 10589.0, 1000.0, 27313.0)
TX_FEE_SOL = RL.TX_FEE_SOL                              # 0.001005, as measured
TIP_SOL = RL.TIP_SOL                                    # the Sender tip, every transaction
STAKE_SOL = 0.1
MAX_OPEN = 4                                            # the live budget, 0.4 SOL at 0.1 a trade
LIMITS = P.Limits(STAKE_SOL, MAX_OPEN, P.HARD_MAX_EXPOSURE_SOL, P.HARD_MAX_DAILY_LOSS_SOL)
PEAK_H_MS = 3_600_000                                   # the peak after entry: the best sale within an hour of landing
RUNNER_GAINS = (1.0, 5.0)                               # +100 %, +500 %
SCENARIOS = ("B", "C")
JUDGED = "B"
SCENARIO_LABEL = {"B": "(b) measured since the Sender path", "C": "(c) 1.5 s send path"}
MIN_HOURS = 10                                          # a band from fewer hours means nothing (study.MIN_BLOCKS)


# ---------------------------------------------------------------- latency

def sender_fills(rows: list[dict], since_ms: int = SENDER_FROM_MS, until_ms: int = UNTIL_MS,
                 rule: str = BASE) -> tuple[list[float], list[float]]:
    """Buy and sale latencies (ms) of the executor's measured.jsonl: test-mode fills of `rule` with lat_ms, logged
    from since_ms to until_ms; clipped to the model's 1 to 60 s (a landing at or before the signal is 1 s)."""
    lo, hi = RL.CLIP_MS
    buys, sells = [], []
    for r in rows:
        if r.get("what") != "fill" or r.get("lat_ms") is None or r.get("mode") != "test" or r.get("rule") != rule:
            continue
        t = r.get("t")
        if t is None or not since_ms <= t <= until_ms:
            continue
        x = min(hi, max(lo, float(r["lat_ms"])))
        if r.get("side") == "buy":
            buys.append(x)
        elif r.get("side") == "sell":
            sells.append(x)
    return buys, sells


def scenarios(buy_ms=SENDER_BUY_MS, sell_ms=SENDER_SELL_MS) -> dict[str, C.Costs]:
    prio = RL.priority_for(TX_FEE_SOL + TIP_SOL)
    fast = RL.Lognormal(RL.FAST["median_ms"], RL.FAST["sigma"], RL.FAST["lo_ms"], RL.FAST["hi_ms"])
    lo, hi = RL.CLIP_MS
    return {
        "B": RL.FillCosts(lat_median_ms=float(np.median(buy_ms)), lat_lo_ms=lo, lat_hi_ms=hi, priority_sol=prio,
                          buy=RL.LogKDE(tuple(buy_ms)), sell=RL.LogKDE(tuple(sell_ms))),
        "C": RL.FillCosts(lat_median_ms=fast.median_ms, lat_lo_ms=fast.lo_ms, lat_hi_ms=fast.hi_ms, priority_sol=prio,
                          buy=fast, sell=fast),
    }


# ---------------------------------------------------------------- books

class PeakPipe(P.Pipeline):
    """A pipeline book that also follows each bought position's best possible sale (all its tokens at the pool's
    price after the fee) for PEAK_H_MS after the landing, after the position has closed too, and notes every
    signal it could not take."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.watch: dict[str, list] = {}                # mint -> [[pid, tokens, cost_l, land_ms, max_l], ...]
        self.peaks: dict[int, dict] = {}
        self.skips: list[tuple[int, str]] = []

    def signal(self, s, tok, t: float) -> None:
        before = self.eng.next_pid
        n0 = {w: c for (n, w), c in self.eng.skipped.items() if n == s.name}
        super().signal(s, tok, t)
        if self.eng.next_pid == before:
            why = next((w for (n, w), c in self.eng.skipped.items() if n == s.name and c > n0.get(w, 0)), "?")
            self.skips.append((int(t), why))

    def bought(self, pid: int, at: float, tokens: int, cost_l: int, fee_l: int) -> None:
        p = self.pos.get(pid)
        if p is not None and p["state"] == "pending":
            v = self.eng.sale_value(self.eng.tokens.get(p["mint"]), tokens, self.eng.cost_of(p["rule"])) or 0
            self.watch.setdefault(p["mint"], []).append([pid, tokens, cost_l, int(at), float(v)])
        super().bought(pid, at, tokens, cost_l, fee_l)

    def on_trade(self, tok, t: float, buy: bool, user: str, tok_amt: int, venue: str) -> None:
        ws = self.watch.get(tok.mint)
        if ws:
            keep = []
            for w in ws:
                if t > w[3] + PEAK_H_MS:
                    self._peak_done(w, True)
                    continue
                v = self.eng.sale_value(tok, w[1], self.eng.costs)
                if v is not None and v > w[4]:
                    w[4] = float(v)
                keep.append(w)
            if keep:
                self.watch[tok.mint] = keep
            else:
                self.watch.pop(tok.mint, None)
        super().on_trade(tok, t, buy, user, tok_amt, venue)

    def _peak_done(self, w: list, complete: bool) -> None:
        self.peaks[w[0]] = {"max_l": w[4], "cost_l": w[2], "ret": w[4] / w[2] - 1 if w[2] > 0 else math.nan,
                            "complete": complete}

    def finish(self, t_end: float) -> None:
        for ws in self.watch.values():
            for w in ws:
                self._peak_done(w, t_end >= w[3] + PEAK_H_MS)
        self.watch.clear()


def books() -> tuple[list[P.Strategy], dict[str, C.Costs]]:
    """Every variant once per scenario, `<name>@<scenario>`, at STAKE_SOL; the latency key stays P_pool0's."""
    sc = scenarios()
    out, costs = [], {}
    for k in SCENARIOS:
        for _, name in VARIANTS:
            s = P.BY_NAME[name]
            v = dataclasses.replace(s, name=f"{name}@{k}", p={**s.p, "base": KEY}, stake_sol=STAKE_SOL)
            out.append(v)
            costs[v.name] = sc[k]
    return out, costs


# ---------------------------------------------------------------- numbers

def entries(pipe: PeakPipe) -> list[dict]:
    """Closed trades and failed buys of one book; a failed buy is an entry that lost its fee. The peak after
    entry (best sale value over the cost, before the fixed fees) where the hour after landing was seen."""
    out = []
    for t in pipe.closed:
        pk = pipe.peaks.get(t["pid"])
        out.append({"mint": t["mint"], "signal_ms": t["signal_ms"], "real_ms": t["exit_ms"], "ret": t["ret"],
                    "pnl_sol": t["pnl_sol"], "exit_why": t.get("exit_why"), "hold_s": t.get("hold_s"),
                    "legs": t.get("legs"), "failed": False, "symbol": t.get("symbol"),
                    "peak": pk["ret"] if pk is not None and pk["complete"] else None})
    for f in pipe.failed:
        out.append({"mint": f["mint"], "signal_ms": f["signal_ms"], "real_ms": f["land_ms"],
                    "ret": f["pnl_sol"] / STAKE_SOL, "pnl_sol": f["pnl_sol"], "exit_why": "failed buy",
                    "hold_s": None, "legs": 0, "failed": True, "symbol": None, "peak": None})
    return sorted(out, key=lambda e: (e["real_ms"], e["signal_ms"]))


def max_drawdown(pnl_in_order: list[float]) -> float:
    """The largest fall of the cumulative P&L from its running high (the high starts at 0), SOL."""
    cum = np.cumsum(np.asarray(pnl_in_order, dtype=float))
    if not len(cum):
        return 0.0
    high = np.maximum.accumulate(np.concatenate([[0.0], cum]))[1:]
    return float((high - cum).max())


def hours(e: list[dict]) -> int:
    return len({x["signal_ms"] // 3_600_000 for x in e})


def stats(e: list[dict]) -> dict:
    from .study import boot_mean
    out = {"n": len(e), "failed": sum(1 for x in e if x["failed"])}
    if not e:
        return out
    r = np.array([x["ret"] for x in e])
    pnl = np.array([x["pnl_sol"] for x in e])
    total = float(pnl.sum())
    k = max(1, math.ceil(0.05 * len(e)))
    top = float(np.sort(pnl)[::-1][:k].sum())
    lo, hi = boot_mean(e) if hours(e) >= MIN_HOURS else (math.nan, math.nan)
    held = [x["hold_s"] for x in e if x["hold_s"] is not None]
    out.update(mean=float(r.mean()), median=float(np.median(r)), pnl_sol=total, win=float((pnl > 0).mean()),
               band=(lo, hi), max_dd_sol=max_drawdown([x["pnl_sol"] for x in e]), top5_n=k, top5_sol=top,
               top5_share=top / total if total > 0 else None, hold_s=float(np.median(held)) if held else None,
               exits=dict(sorted(Counter(x["exit_why"] or "?" for x in e).items())),
               peak_known=sum(1 for x in e if x["peak"] is not None))
    out["runners"] = {}
    for g in RUNNER_GAINS:
        run = [x for x in e if x["peak"] is not None and x["peak"] > g]
        rr = np.array([x["ret"] for x in run])
        pk = np.array([x["peak"] for x in run])
        out["runners"][f"{g:g}"] = {"n": len(run), "mean_ret": float(rr.mean()) if len(run) else None,
                                    "mean_peak": float(pk.mean()) if len(run) else None,
                                    "capture": float(rr.sum() / pk.sum()) if len(run) else None,
                                    "capture_median": float(np.median(rr / pk)) if len(run) else None}
    return out


def versus(e: list[dict], base: list[dict]) -> dict:
    """mean(variant) - mean(X0) on the migrations both entered, the hour-block 90 % band (study.boot_diff)."""
    from .study import boot_diff
    common = {x["mint"] for x in e} & {x["mint"] for x in base}
    a = [x for x in e if x["mint"] in common]
    b = [x for x in base if x["mint"] in common]
    if not a:
        return {"n": 0, "diff": None, "band": (math.nan, math.nan)}
    lo, hi = boot_diff(a, b) if hours(a) >= MIN_HOURS else (math.nan, math.nan)
    return {"n": len(a), "diff": float(np.mean([x["ret"] for x in a]) - np.mean([x["ret"] for x in b])),
            "band": (lo, hi), "pnl_diff": float(sum(x["pnl_sol"] for x in a) - sum(x["pnl_sol"] for x in b))}


def evaluate(res: dict) -> dict:
    split = res["split_ms"]
    table: dict[str, dict] = {k: {} for k in SCENARIOS}
    is_table: dict[str, dict] = {k: {} for k in SCENARIOS}
    ent: dict[tuple, list] = {}
    for k in SCENARIOS:
        for x, name in VARIANTS:
            e = res["entries"][f"{name}@{k}"]
            oos = [y for y in e if y["signal_ms"] >= split]
            ent[(k, x)] = oos
            table[k][x] = stats(oos) | {"name": name}
            is_table[k][x] = stats([y for y in e if y["signal_ms"] < split]) | {"name": name}
            sk = [w for t, w in res["skips"][f"{name}@{k}"] if t >= split]
            table[k][x]["skipped"] = dict(sorted(Counter(sk).items()))
    vs: dict[str, dict] = {k: {} for k in SCENARIOS}
    for k in SCENARIOS:
        b = table[k]["X0"]
        for x, name in VARIANTS[1:]:
            v = versus(ent[(k, x)], ent[(k, "X0")])
            lo = v["band"][0]
            v["better"] = bool(v["n"] and math.isfinite(lo) and lo > 0
                               and table[k][x].get("pnl_sol", -math.inf) > b.get("pnl_sol", math.inf))
            vs[k][x] = v
    return {"table": table, "in_sample": is_table, "versus": vs}


def calibrate(res: dict, live: list[dict]) -> list[dict]:
    """The live P_pool0 trades in the Sender era up to the cutoff next to X0's replay of the same migration."""
    out = []
    for lv in live:
        sig = RL._f(lv.get("signal_ms"))
        if lv.get("rule") != BASE or sig is None or not SENDER_FROM_MS <= sig <= res["until_ms"]:
            continue
        row = {"symbol": lv.get("symbol"), "live_ret": RL._f(lv.get("ret")), "live_exit": lv.get("exit_why")}
        for k in SCENARIOS:
            got = next((y for y in res["entries"][f"{BASE}@{k}"] if y["mint"] == lv.get("mint")), None)
            row[k] = None if got is None else {"ret": got["ret"], "exit": got["exit_why"]}
        out.append(row)
    return out


# ---------------------------------------------------------------- the run

def run(root=None, until_ms: int = UNTIL_MS, buy_ms=SENDER_BUY_MS, sell_ms=SENDER_SELL_MS, log=print) -> dict:
    """The six books under both scenarios in one replay of the record up to until_ms; entries stop TAIL_MS before."""
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
    entry_until = t_hi - TAIL_MS
    split = t_lo + (t_hi - t_lo) // 2                       # as Y5: the middle of the record's time span
    log(f"exitlab: {len(days)} day(s) {days[0]} to {days[-1]}, record to "
        f"{datetime.fromtimestamp(t_hi / 1000, timezone.utc):%Y-%m-%d %H:%M} UTC, entries to "
        f"{datetime.fromtimestamp(entry_until / 1000, timezone.utc):%Y-%m-%d %H:%M} UTC, split at "
        f"{datetime.fromtimestamp(split / 1000, timezone.utc):%Y-%m-%d %H:%M} UTC, warm-up {len(warm)} day(s)")
    t0 = time.time()
    strats, costs = books()
    if (tuple(buy_ms), tuple(sell_ms)) != (SENDER_BUY_MS, SENDER_SELL_MS):
        sc = scenarios(buy_ms, sell_ms)
        costs = {n: sc[n.split("@")[1]] for n in costs}
    eng = sim.Engine([], book=warm_book(warm, root), decisions=False, rule_costs=costs, entry_until=entry_until,
                     wallets=W.warm(warm, root), snipers=EA.warm_snipers(warm, root))
    pipes = {s.name: eng.add_pipe(PeakPipe(eng, [s], P.PaperExecutor(), limits=LIMITS, name=s.name))
             for s in strats}
    sim.replay(days, eng, root, until_ms=t_hi)
    for pipe in pipes.values():
        pipe.finish(eng.now)
        gapped = {(c["pid"]) for c in pipe.closed if c.get("gap")
                  or any(g0 < c["exit_ms"] and c["signal_ms"] < g1 for g0, g1 in eng.gaps)}
        pipe.closed = [c for c in pipe.closed if c["pid"] not in gapped]       # as the engine's drop_gapped
    log(f"exitlab: replay in {time.time() - t0:.0f} s, {len(eng.closed):,} closed, {len(eng.failed):,} failed buys")
    return {"days": days, "warm": warm, "span": (t_lo, t_hi), "until_ms": until_ms, "entry_until_ms": entry_until,
            "split_ms": split, "entries": {n: entries(p) for n, p in pipes.items()},
            "skips": {n: p.skips for n, p in pipes.items()},
            "open_at_end": {n: len(p.pos) for n, p in pipes.items() if p.pos},
            "counts": dict(eng.counts), "gaps": list(eng.gaps)}


# ---------------------------------------------------------------- report

pct = RL.pct


def _band(b) -> str:
    return f"{pct(b[0])} to {pct(b[1])}"


def report_md(res: dict, ev: dict, lat: dict, calib: list[dict]) -> str:
    def ms(d):
        return f"{d['p50'] / 1000:.1f} s ({d['p10'] / 1000:.1f} to {d['p90'] / 1000:.1f})"

    def utc(x):
        return f"{datetime.fromtimestamp(x / 1000, timezone.utc):%Y-%m-%d %H:%M} UTC"
    md = ["# P_pool0's exits for runners (Y7)", "",
          f"Record {res['days'][0]} to {utc(res['span'][1])}, entries to {utc(res['entry_until_ms'])}, split "
          f"{utc(res['split_ms'])}. Stake {STAKE_SOL} SOL, at most {MAX_OPEN} open per book. Out of sample.", "",
          "| scenario | buy, median (10 to 90 %) | sale | fee per transaction |", "|---|---|---|---|"]
    for k in SCENARIOS:
        d = lat[k]
        md.append(f"| {SCENARIO_LABEL[k]} | {ms(d['buy'])} | {ms(d['sell'])} | {d['tx_fee_sol']:.6f} SOL |")
    for k in SCENARIOS:
        md += ["", f"## {SCENARIO_LABEL[k]}", "",
               "| book | strategy | entries | failed | mean | median | win | P&L SOL | band of mean | max DD SOL | "
               "top 5 % | peak > +100 % | capture | peak > +500 % | capture | blocked (max open) |",
               "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for x, _ in VARIANTS:
            s = ev["table"][k][x]
            if not s.get("n"):
                md.append(f"| {x} | {s['name']} | 0 | | | | | | | | | | | | | |")
                continue
            r1, r5 = s["runners"]["1"], s["runners"]["5"]
            share = "n/a" if s["top5_share"] is None else f"{s['top5_share'] * 100:.0f} %"
            md.append(f"| {x} | {s['name']} | {s['n']} | {s['failed']} | {pct(s['mean'])} | {pct(s['median'])} | "
                      f"{s['win'] * 100:.0f} % | {s['pnl_sol']:+.3f} | {_band(s['band'])} | {s['max_dd_sol']:.3f} | "
                      f"{s['top5_sol']:+.3f} ({share}) | {r1['n']} | {_cap(r1)} | {r5['n']} | {_cap(r5)} | "
                      f"{s['skipped'].get('max open positions', 0)} |")
        md += ["", f"Against X0 at {SCENARIO_LABEL[k]}, paired by migration:", "",
               "| book | migrations both entered | mean difference | band | P&L difference SOL | total P&L higher | "
               "better |", "|---|---|---|---|---|---|---|"]
        for x, _ in VARIANTS[1:]:
            v = ev["versus"][k][x]
            higher = ev["table"][k][x].get("pnl_sol", -math.inf) > ev["table"][k]["X0"].get("pnl_sol", math.inf)
            md.append(f"| {x} | {v['n']} | {pct(v['diff'])} | {_band(v['band'])} | "
                      + (f"{v['pnl_diff']:+.3f}" if v.get("pnl_diff") is not None else "n/a")
                      + f" | {'yes' if higher else 'no'} | {'yes' if v['better'] else 'no'} |")
        md += ["", "Exits (out of sample): " + "; ".join(
            f"{x} " + ", ".join(f"{w} {c}" for w, c in ev["table"][k][x].get("exits", {}).items()) for x, _ in VARIANTS)]
    md += ["", "## In sample (not judged)", "", "| book | entries | mean | P&L SOL (b) | mean (c) |", "|---|---|---|---|---|"]
    for x, _ in VARIANTS:
        b, c = ev["in_sample"]["B"][x], ev["in_sample"]["C"][x]
        md.append(f"| {x} | {b['n']} | {pct(b.get('mean'))} | {b.get('pnl_sol', 0):+.3f} | {pct(c.get('mean'))} |")
    if calib:
        md += ["", "## The live P_pool0 trades in the replay", "", "| token | live return | live exit | X0 (b) | X0 (c) |",
               "|---|---|---|---|---|"]
        for c in calib:
            cells = ["not entered" if c.get(k) is None else f"{pct(c[k]['ret'])} ({c[k]['exit']})" for k in SCENARIOS]
            md.append(f"| {c['symbol']} | {pct(c['live_ret'])} | {c['live_exit']} | " + " | ".join(cells) + " |")
    return "\n".join(md) + "\n"


def _cap(r: dict) -> str:
    return "n/a" if r["capture"] is None else f"{r['capture'] * 100:.0f} %"


def read_jsonl(path: Path) -> list[dict]:
    out = []
    try:
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        pass
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--until-ms", type=int, default=UNTIL_MS)
    ap.add_argument("--out", default=None, help="directory for exitlab.json and exitlab.md (default: the reports)")
    ap.add_argument("--live-dir", default=None, help="the live executor's folder (read only)")
    a = ap.parse_args(argv)
    from .. import report as rep
    from ..data import ROOT
    out = Path(a.out) if a.out else rep.REPORTS / "pumpfun_rt"
    out.mkdir(parents=True, exist_ok=True)
    live_dir = Path(a.live_dir) if a.live_dir else ROOT / "live" / "pumpfun_rt"
    buys, sells = sender_fills(read_jsonl(live_dir / "measured.jsonl"), until_ms=a.until_ms)
    if (tuple(buys), tuple(sells)) != (SENDER_BUY_MS, SENDER_SELL_MS):
        print(f"exitlab: the measured file now gives buys {buys} and sales {sells}; the registered points are used")
    lat = {k: RL.describe(c) for k, c in scenarios().items()}
    res = run(until_ms=a.until_ms)
    if res.get("empty"):
        print("exitlab: nothing recorded")
        return 1
    ev = evaluate(res)
    calib = calibrate(res, RL.read_live_ledger(live_dir / "ledger.csv"))
    md = report_md(res, ev, lat, calib)
    keep = {k: v for k, v in res.items() if k not in ("entries", "skips")}
    (out / "exitlab.json").write_text(json.dumps(keep | {"latency": lat, "eval": ev, "calibration": calib,
                                                         "sender_fills": {"buy": buys, "sell": sells}},
                                                 indent=1, default=str), encoding="utf-8")
    (out / "exitlab.md").write_text(md, encoding="utf-8")
    print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
