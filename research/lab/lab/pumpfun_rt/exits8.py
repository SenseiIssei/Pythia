"""Y8: P_pool0 with a -10 % stop, a sell-pressure exit and an entry that waits for the pool's state, at the latency
the live executor measures since the Sender path. PAPER ONLY.

    python -m lab.pumpfun_rt.exits8                     replay, print the report, write exits8.{json,md}
    python -m lab.pumpfun_rt.exits8 --out DIR           the same, written into DIR
    python -m lab.pumpfun_rt.exits8 --daily-loss-sol 1  not registered (after the first result): another loss limit

Pre-registered in results/pumpfun_exits_y8_prereg.md. P_pool0 (X0) and the five Y8 strategies (pipeline._build_y8,
X1 to X5) replayed on the record by Y7's replay (exitlab.run: one book of at most 4 positions with one shared Risk
per variant, every book drawing its latency with P_pool0's key), the daily loss limit at 0.25 SOL, under two
scenarios:

  B    the measured latency: Y5's kernel density in log space of the live executor's P_pool0 fills from the Sender
       path to the cutoff (SENDER_BUY_MS, SENDER_SELL_MS), buys and sales apart
  C    Y5's 1.5 s send path, as a robustness line

0.001005 SOL per transaction, 0.1 SOL a trade. Judged out of sample at B against X0, paired by hour block, with the
trades open across a gap in the record kept. Nothing here holds a wallet, reads a key, signs or sends anything; the
live executor's files are only read.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import math
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from . import exitlab as XL
from . import pipeline as P
from . import reallat as RL

# ---------------------------------------------------------------- registered (results/pumpfun_exits_y8_prereg.md)

VARIANTS = (("X0", "P_pool0"), ("X1", "P_pool0_sl10"), ("X2", "P_pool0_press"), ("X3", "P_pool0_wait"),
            ("X4", "P_pool0_wait_press"), ("X5", "P_pool0_wait_sl10"))
BASE = "P_pool0"
UNTIL_MS = int(datetime(2026, 10, 23, 6, 0, tzinfo=timezone.utc).timestamp() * 1000)
TAIL_MS = 15 * 60_000                                   # entries stop this long before the cutoff: all close inside
# The executor's P_pool0 fills, signal to landing (ms), 2026-10-22 21:41 UTC to the cutoff, clipped to 1 to 60 s.
SENDER_BUY_MS = (1000.0, 21423.0, 10827.0, 1000.0, 29589.0, 60000.0, 8209.0, 18924.0, 1000.0, 28867.0, 1000.0,
                 12866.0, 19353.0, 6217.0, 12696.0, 37275.0, 17472.0, 1000.0, 19655.0, 9074.0, 13064.0, 1000.0,
                 6476.0, 8973.0, 2867.0, 9215.0)
SENDER_SELL_MS = (38000.0, 1000.0, 1000.0, 10589.0, 1000.0, 27313.0, 2916.0, 1000.0, 12852.0, 1000.0, 1000.0,
                  6158.0, 8030.0, 13321.0, 17593.0, 3537.0, 1000.0, 2330.0, 37000.0, 10020.0, 2905.0, 38000.0,
                  5205.0, 5317.0, 1890.0, 1000.0)
TX_FEE_SOL = RL.TX_FEE_SOL                              # 0.001005 SOL per transaction, as measured
STAKE_SOL = 0.1
LIMITS = P.Limits(STAKE_SOL, 4, P.HARD_MAX_EXPOSURE_SOL, 0.25)
SCENARIOS = XL.SCENARIOS
JUDGED = "B"
SCENARIO_LABEL = XL.SCENARIO_LABEL
MIN_HOURS = XL.MIN_HOURS


def scenarios(buy_ms=SENDER_BUY_MS, sell_ms=SENDER_SELL_MS):
    return XL.scenarios(buy_ms, sell_ms, fee_sol=TX_FEE_SOL)


def books(buy_ms=SENDER_BUY_MS, sell_ms=SENDER_SELL_MS) -> tuple[list[P.Strategy], dict]:
    """Every variant once per scenario, `<name>@<scenario>`, at STAKE_SOL; the latency key stays P_pool0's."""
    sc = scenarios(buy_ms, sell_ms)
    out, costs = [], {}
    for k in SCENARIOS:
        for _, name in VARIANTS:
            s = P.BY_NAME[name]
            v = dataclasses.replace(s, name=f"{name}@{k}", p={**s.p, "base": BASE}, stake_sol=STAKE_SOL)
            out.append(v)
            costs[v.name] = sc[k]
    return out, costs


# ---------------------------------------------------------------- numbers

def stops(e: list[dict], sl: float) -> dict:
    """The stop exits: their mean and median return per entry after every cost, and how far the mean lands below
    the stop's trigger (points of the stake)."""
    r = np.array([x["ret"] for x in e if x["exit_why"] == "stop"])
    if not len(r):
        return {"n": 0, "mean": None, "median": None, "below": None}
    return {"n": len(r), "mean": float(r.mean()), "median": float(np.median(r)), "below": float(r.mean() + sl)}


def paired(e: list[dict], base: list[dict]) -> dict:
    """mean(variant) - mean(X0) over all entries of each book, the same hours drawn for both (study.boot_diff);
    n/a under MIN_HOURS hours."""
    from .study import boot_diff
    if not e or not base:
        return {"diff": None, "band": (math.nan, math.nan)}
    ok = XL.hours(e) >= MIN_HOURS and XL.hours(base) >= MIN_HOURS
    lo, hi = boot_diff(e, base) if ok else (math.nan, math.nan)
    return {"diff": float(np.mean([x["ret"] for x in e]) - np.mean([x["ret"] for x in base])), "band": (lo, hi)}


def evaluate(res: dict, keep_gapped: bool = True) -> dict:
    """The registered numbers keep the closed trades open across a gap in the record; keep_gapped=False (a
    robustness line) leaves them out, as Y7's registered numbers did."""
    split = res["split_ms"]
    table: dict[str, dict] = {k: {} for k in SCENARIOS}
    is_table: dict[str, dict] = {k: {} for k in SCENARIOS}
    ent: dict[tuple, list] = {}
    for k in SCENARIOS:
        for x, name in VARIANTS:
            e = [y for y in res["entries"][f"{name}@{k}"] if keep_gapped or not y["gapped"]]
            oos = [y for y in e if y["signal_ms"] >= split]
            ent[(k, x)] = oos
            sl = P.BY_NAME[name].exits.sl
            table[k][x] = XL.stats(oos) | {"name": name, "stops": stops(oos, sl)}
            press = [y["ret"] for y in oos if y["exit_why"] == "press"]
            table[k][x]["press"] = {"n": len(press), "mean": float(np.mean(press)) if press else None}
            is_table[k][x] = XL.stats([y for y in e if y["signal_ms"] < split]) | {"name": name}
            sk = [w for t, w in res["skips"][f"{name}@{k}"] if t >= split]
            table[k][x]["skipped"] = dict(sorted(Counter(sk).items()))
    vs: dict[str, dict] = {k: {} for k in SCENARIOS}
    for k in SCENARIOS:
        b = table[k]["X0"]
        for x, _ in VARIANTS[1:]:
            v = paired(ent[(k, x)], ent[(k, "X0")])
            v["common"] = XL.versus(ent[(k, x)], ent[(k, "X0")])
            v["pnl_higher"] = table[k][x].get("pnl_sol", -math.inf) > b.get("pnl_sol", math.inf)
            lo = v["band"][0]
            v["better"] = bool(math.isfinite(lo) and lo > 0 and v["pnl_higher"])
            vs[k][x] = v
    return {"table": table, "in_sample": is_table, "versus": vs}


def live_stops(live: list[dict], since_ms: int = XL.SENDER_FROM_MS, until_ms: int = UNTIL_MS) -> dict:
    """The live P_pool0 trades from the Sender path to the cutoff: their count, P&L and stop exits (descriptive)."""
    rows = [r for r in live if r.get("rule") == BASE and RL._f(r.get("signal_ms")) is not None
            and since_ms <= RL._f(r.get("signal_ms")) < until_ms and RL._f(r.get("ret")) is not None]
    st = [RL._f(r["ret"]) for r in rows if r.get("exit_why") == "stop"]
    return {"n": len(rows), "pnl_sol": float(sum(RL._f(r.get("pnl_sol")) or 0.0 for r in rows)),
            "mean": float(np.mean([RL._f(r["ret"]) for r in rows])) if rows else None, "stops": len(st),
            "stop_mean": float(np.mean(st)) if st else None}


# ---------------------------------------------------------------- report

pct = RL.pct


def _band(b) -> str:
    return f"{pct(b[0])} to {pct(b[1])}"


def _table(ev: dict, k: str) -> list[str]:
    md = ["| book | strategy | entries | failed buys | mean | median | win | P&L SOL | band of mean | max DD SOL | "
          "stop exits | stop mean | below the trigger | press exits | no pool state | daily loss limit |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for x, _ in VARIANTS:
        s = ev["table"][k][x]
        if not s.get("n"):
            md.append(f"| {x} | {s['name']} | 0 |" + " |" * 13)
            continue
        st, sk = s["stops"], s["skipped"]
        md.append(f"| {x} | {s['name']} | {s['n']} | {s['failed']} | {pct(s['mean'])} | {pct(s['median'])} | "
                  f"{s['win'] * 100:.0f} % | {s['pnl_sol']:+.3f} | {_band(s['band'])} | {s['max_dd_sol']:.3f} | "
                  f"{st['n']} | {pct(st['mean'])} | {pct(st['below'])} | {s['press']['n']} | "
                  f"{sk.get('no pool state', 0)} | {sk.get('daily loss limit', 0) + sk.get('daily loss stop', 0)} |")
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


def report_md(res: dict, ev: dict, ev_dropped: dict, lat: dict, calib: list[dict], live: dict,
              limits: P.Limits = LIMITS) -> str:
    def ms(d):
        return f"{d['p50'] / 1000:.1f} s ({d['p10'] / 1000:.1f} to {d['p90'] / 1000:.1f})"

    def utc(x):
        return f"{datetime.fromtimestamp(x / 1000, timezone.utc):%Y-%m-%d %H:%M} UTC"
    md = ["# P_pool0: a -10 % stop, a sell-pressure exit, waiting for the pool (Y8)", "",
          f"Record {res['days'][0]} to {utc(res['span'][1])}, entries to {utc(res['entry_until_ms'])}, split "
          f"{utc(res['split_ms'])}. Stake {STAKE_SOL} SOL, at most {limits.max_open} open per book, daily loss limit "
          f"{limits.max_daily_loss_sol} SOL" + ("" if limits == LIMITS else " (not registered)")
          + ". Out of sample, trades open across a gap kept.", "",
          "| scenario | buy, median (10 to 90 %) | sale | fee per transaction |", "|---|---|---|---|"]
    for k in SCENARIOS:
        d = lat[k]
        md.append(f"| {SCENARIO_LABEL[k]} | {ms(d['buy'])} | {ms(d['sell'])} | {d['tx_fee_sol']:.6f} SOL |")
    for k in SCENARIOS:
        md += ["", f"## {SCENARIO_LABEL[k]}", ""] + _table(ev, k)
    md += ["", f"## {SCENARIO_LABEL[JUDGED]}, trades open across a gap left out (robustness)", ""]
    md += _table(ev_dropped, JUDGED)
    md += ["", "## In sample (not judged)", "", "| book | entries | mean | P&L SOL (b) | mean (c) |",
           "|---|---|---|---|---|"]
    for x, _ in VARIANTS:
        b, c = ev["in_sample"]["B"][x], ev["in_sample"]["C"][x]
        md.append(f"| {x} | {b['n']} | {pct(b.get('mean'))} | {b.get('pnl_sol', 0):+.3f} | {pct(c.get('mean'))} |")
    md += ["", "## The live P_pool0 trades (descriptive)", "",
           f"{live['n']} live trades from the Sender path to the cutoff, mean {pct(live['mean'])}, "
           f"P&L {live['pnl_sol']:+.3f} SOL; {live['stops']} stop exits at a mean {pct(live['stop_mean'])}."]
    if calib:
        md += ["", "| token | live return | live exit | X0 (b) | X0 (c) |", "|---|---|---|---|---|"]
        for c in calib:
            cells = ["not entered" if c.get(k) is None else f"{pct(c[k]['ret'])} ({c[k]['exit']})" for k in SCENARIOS]
            md.append(f"| {c['symbol']} | {pct(c['live_ret'])} | {c['live_exit']} | " + " | ".join(cells) + " |")
    return "\n".join(md) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--until-ms", type=int, default=UNTIL_MS)
    ap.add_argument("--out", default=None, help="directory for exits8.json and exits8.md (default: the reports)")
    ap.add_argument("--live-dir", default=None, help="the live executor's folder (read only)")
    ap.add_argument("--daily-loss-sol", type=float, default=LIMITS.max_daily_loss_sol)
    a = ap.parse_args(argv)
    limits = dataclasses.replace(LIMITS, max_daily_loss_sol=a.daily_loss_sol)
    from .. import report as rep
    from ..data import ROOT
    out = Path(a.out) if a.out else rep.REPORTS / "pumpfun_rt"
    out.mkdir(parents=True, exist_ok=True)
    live_dir = Path(a.live_dir) if a.live_dir else ROOT / "live" / "pumpfun_rt"
    buys, sells = XL.sender_fills(XL.read_jsonl(live_dir / "measured.jsonl"), until_ms=a.until_ms)
    if (tuple(buys), tuple(sells)) != (SENDER_BUY_MS, SENDER_SELL_MS):
        print(f"exits8: the measured file now gives buys {buys} and sales {sells}; the registered points are used")
    lat = {k: RL.describe(c) for k, c in scenarios().items()}
    res = XL.run(until_ms=a.until_ms, books_costs=books(), limits=limits, tail_ms=TAIL_MS)
    if res.get("empty"):
        print("exits8: nothing recorded")
        return 1
    ev = evaluate(res)
    dropped = evaluate(res, keep_gapped=False)
    ledger = RL.read_live_ledger(live_dir / "ledger.csv")
    calib = XL.calibrate(res, ledger)
    live = live_stops(ledger, until_ms=a.until_ms)
    md = report_md(res, ev, dropped, lat, calib, live, limits)
    keep = {k: v for k, v in res.items() if k not in ("entries", "skips")}
    (out / "exits8.json").write_text(json.dumps(keep | {"latency": lat, "eval": ev, "eval_gapped_dropped": dropped,
                                                        "calibration": calib, "live": live,
                                                        "sender_fills": {"buy": buys, "sell": sells}},
                                                indent=1, default=str), encoding="utf-8")
    (out / "exits8.md").write_text(md, encoding="utf-8")
    (out / "exits8_entries.json").write_text(json.dumps(res["entries"], default=str), encoding="utf-8")
    print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
