"""Y5: the pump.fun rules and pipeline strategies at the latency the live test measured. PAPER ONLY.

    python -m lab.pumpfun_rt.reallat                    replay, print the report, write reallat.{json,md}
    python -m lab.pumpfun_rt.reallat --out DIR          the same, written into DIR

Pre-registered in results/pumpfun_real_latency_prereg.md. The study's own replay
(study.py: the split, pass 1 for the pick and the in-sample models) with every rule,
the model filter on the pick and every pipeline strategy filled under four scenarios:

  A    the study's assumption (curve.Costs: lognormal median 1 s, 0.4 to 3 s)
  B    the measured latency: a kernel density in log space of the live test's buys
       and, separately, of its sales (MEASURED_BUY_MS, MEASURED_SELL_MS)
  C    a faster send path: lognormal median 1.5 s, clipped to 1 to 2 s
  Ct   C with an extra 0.000005 SOL tip per transaction

The same fee per transaction (0.001005 SOL, measured) and stake (0.03 SOL) everywhere.
A draw is keyed as in the study (rule, token, leg), one uniform per key through the
scenario's quantile function, so a signal draws the same rank in every scenario.
Nothing here holds a wallet, reads a key, signs or sends anything; the live test's
files are only read.
"""

from __future__ import annotations

import argparse
import csv
import dataclasses
import hashlib
import json
import math
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import cached_property
from pathlib import Path

import numpy as np

from . import curve as C

# ---------------------------------------------------------------- what the live test measured (registered)

MEASURED_BUY_MS = (2391.0, 4852.0, 8381.0, 8770.0)      # signal to landing, the executor's 4 buy fills
MEASURED_SELL_MS = (6940.0, 11817.0, 17179.0)           # exit signal to landing, the 3 sales the stream saw
TX_FEE_SOL = 0.001005                                   # every measured transaction: 5,000 base + 0.001 priority
STAKE_SOL = 0.03
TIP_SOL = 0.000005
BW_FLOOR = 0.25                                         # the kernel's bandwidth in log space, at least
CLIP_MS = (1_000.0, 60_000.0)
FAST = {"median_ms": 1_500.0, "sigma": 0.175, "lo_ms": 1_000.0, "hi_ms": 2_000.0}
UNTIL_MS = int(datetime(2026, 10, 22, 21, 0, tzinfo=timezone.utc).timestamp() * 1000)
SCENARIOS = ("A", "B", "C", "Ct")
SCENARIO_LABEL = {"A": "(a) the study's assumption", "B": "(b) measured", "C": "(c) 1.5 s send path",
                  "Ct": "(c) + 0.000005 SOL tip"}
MIN_ENTRIES = 30
ALPHA = 0.05
BASE_RULE = "P_cmig_model"


# ---------------------------------------------------------------- latency models

def u_of(key: tuple) -> float:
    """The study's uniform for a latency key (curve.Costs.latency hashes the same way)."""
    h = hashlib.blake2b(repr(key).encode(), digest_size=8).digest()
    return (int.from_bytes(h, "big") + 0.5) / 2 ** 64


def _phi(x: np.ndarray) -> np.ndarray:
    from scipy.special import ndtr
    return ndtr(x)


@dataclass(frozen=True)
class Lognormal:
    """median x exp(sigma z), clipped to [lo, hi] (ms)."""
    median_ms: float
    sigma: float
    lo_ms: float
    hi_ms: float

    def quantile(self, u: float) -> float:
        ms = self.median_ms * math.exp(self.sigma * C._norm_ppf(u))
        return min(self.hi_ms, max(self.lo_ms, ms))


def silverman(logs: np.ndarray, floor: float = BW_FLOOR) -> float:
    """Silverman's rule on the logs, 0.9 x min(sd, IQR / 1.34) x n^-0.2, never under `floor`."""
    x = np.asarray(logs, dtype=float)
    if len(x) < 2:
        return floor
    sd = float(x.std(ddof=1))
    q25, q75 = np.quantile(x, [0.25, 0.75])
    spread = min(sd, float(q75 - q25) / 1.34) if q75 > q25 else sd
    return max(floor, 0.9 * spread * len(x) ** -0.2)


@dataclass(frozen=True)
class LogKDE:
    """A kernel density of measured latencies in log space (a lognormal kernel on each point), clipped
    to [lo, hi] ms: the measured quantiles, widened."""
    points_ms: tuple
    lo_ms: float = CLIP_MS[0]
    hi_ms: float = CLIP_MS[1]
    floor: float = BW_FLOOR

    @cached_property
    def bandwidth(self) -> float:
        return silverman(np.log(np.asarray(self.points_ms, dtype=float)), self.floor)

    @cached_property
    def _grid(self) -> tuple[np.ndarray, np.ndarray]:
        logs = np.log(np.asarray(self.points_ms, dtype=float))
        h = self.bandwidth
        g = np.linspace(logs.min() - 8 * h, logs.max() + 8 * h, 8001)
        cdf = _phi((g[:, None] - logs[None, :]) / h).mean(axis=1)
        return g, cdf

    def cdf(self, ms: float) -> float:
        """The mixture's distribution function before the clip."""
        g, F = self._grid
        return float(np.interp(math.log(max(ms, 1e-9)), g, F))

    def quantile(self, u: float) -> float:
        g, F = self._grid
        ms = math.exp(float(np.interp(u, F, g)))
        return min(self.hi_ms, max(self.lo_ms, ms))


@dataclass(frozen=True)
class FillCosts(C.Costs):
    """curve.Costs with one latency model for buys and one for sales."""
    buy: object = field(default=None)
    sell: object = field(default=None)

    def latency(self, *key) -> float:
        m = self.sell if "sell" in key else self.buy
        return float(m.quantile(u_of(key)))

    def tx_lamports(self) -> int:
        return C.BASE_FEE_LAMPORTS + int(round(self.priority_sol * C.LAMPORTS))


def priority_for(tx_fee_sol: float) -> float:
    """The priority fee that makes curve.Costs.tx_lamports() equal a fee per transaction."""
    return round(tx_fee_sol - C.BASE_FEE_LAMPORTS / C.LAMPORTS, 9)


def scenarios(buy_ms=MEASURED_BUY_MS, sell_ms=MEASURED_SELL_MS) -> dict[str, C.Costs]:
    prio = priority_for(TX_FEE_SOL)
    fast = Lognormal(FAST["median_ms"], FAST["sigma"], FAST["lo_ms"], FAST["hi_ms"])
    lo, hi = CLIP_MS
    return {
        "A": C.Costs(priority_sol=prio),
        "B": FillCosts(lat_median_ms=float(np.median(buy_ms)), lat_lo_ms=lo, lat_hi_ms=hi, priority_sol=prio,
                       buy=LogKDE(tuple(buy_ms)), sell=LogKDE(tuple(sell_ms))),
        "C": FillCosts(lat_median_ms=fast.median_ms, lat_lo_ms=fast.lo_ms, lat_hi_ms=fast.hi_ms, priority_sol=prio,
                       buy=fast, sell=fast),
        "Ct": FillCosts(lat_median_ms=fast.median_ms, lat_lo_ms=fast.lo_ms, lat_hi_ms=fast.hi_ms,
                        priority_sol=prio + TIP_SOL, buy=fast, sell=fast),
    }


def describe(costs: C.Costs, n: int = 20_000) -> dict:
    """p10, p50 and p90 of a scenario's buy and sale draws (ms) over n synthetic keys, and its fee."""
    out = {"tx_fee_sol": costs.tx_lamports() / C.LAMPORTS}
    for side in ("buy", "sell"):
        xs = np.array([costs.latency("describe", i, side) for i in range(n)])
        out[side] = {"p10": float(np.quantile(xs, 0.1)), "p50": float(np.median(xs)),
                     "p90": float(np.quantile(xs, 0.9)), "min": float(xs.min()), "max": float(xs.max())}
    if isinstance(costs, FillCosts) and isinstance(costs.buy, LogKDE):
        out["bandwidth"] = {"buy": costs.buy.bandwidth, "sell": costs.sell.bandwidth}
    return out


def from_measured(rows: list[dict]) -> tuple[list[float], list[float], list[float]]:
    """Buy and sale latencies (ms) and fees per transaction (SOL) of the executor's measured.jsonl rows."""
    fills = [r for r in rows if r.get("what") == "fill" and r.get("lat_ms") is not None]
    buys = [float(r["lat_ms"]) for r in fills if r.get("side") == "buy"]
    sells = [float(r["lat_ms"]) for r in fills if r.get("side") == "sell"]
    fees = [int(r["fee_l"]) / C.LAMPORTS for r in rows if r.get("what") == "fee" and r.get("fee_l")]
    return buys, sells, fees


# ---------------------------------------------------------------- books

def scen_variant(r, sc: str):
    """The same rule or strategy under `<name>@<scenario>`; its latency key stays the original's."""
    return dataclasses.replace(r, name=f"{r.name}@{sc}", p={**r.p, "base": r.p.get("base") or r.name})


def books(pick: str) -> tuple[list, list, dict, list]:
    """(rules, strategies, rule_costs, judged) for pass 2: every rule, the model filter on the pick and every
    pipeline strategy (at STAKE_SOL), once per scenario."""
    from . import pipeline as P
    from . import sim
    from . import strategies as S
    sc_costs = scenarios()
    mr = sim.model_rule(S.BY_NAME[pick])
    judged = list(S.RULES) + [mr] + [dataclasses.replace(s, stake_sol=STAKE_SOL) for s in P.STRATEGIES]
    rules, strats, costs = [], [], {}
    for sc in SCENARIOS:
        for r in judged:
            v = scen_variant(r, sc)
            (strats if P.is_strategy(r) else rules).append(v)
            costs[v.name] = sc_costs[sc]
    return rules, strats, costs, judged


# ---------------------------------------------------------------- numbers

def entries(trades: list[dict], failed: list[dict], stake_sol: float = STAKE_SOL) -> list[dict]:
    """Closed trades and failed buys as entries; a failed buy is a trade that lost its fee."""
    out = [{"ret": t["ret"], "pnl_sol": t["pnl_sol"], "signal_ms": t["signal_ms"]} for t in trades]
    out += [{"ret": f["pnl_sol"] / stake_sol, "pnl_sol": f["pnl_sol"], "signal_ms": f["signal_ms"]} for f in failed]
    return out


def z_bar(n_total: int, alpha: float = ALPHA) -> float:
    """The one-sided Bonferroni bar over the whole pool (the stand-in for the deflation)."""
    from scipy.stats import norm
    return float(norm.ppf(1 - alpha / max(1, n_total)))


def stats(trades: list[dict], failed: list[dict], days_oos: list[str], pool: dict) -> dict:
    from .study import boot_mean, daily_pnl, deflated_p
    e = entries(trades, failed)
    out = {"n": len(e), "trades": len(trades), "failed": len(failed)}
    if not e:
        return out | {"positive": False}
    r = np.array([x["ret"] for x in e])
    pnl = np.array([x["pnl_sol"] for x in e])
    lo, hi = boot_mean(e)
    mean = float(r.mean())
    se = (hi - lo) / 3.29 if math.isfinite(lo) and math.isfinite(hi) and hi > lo else math.nan
    z = mean / se if math.isfinite(se) and se > 0 else math.nan
    dp = deflated_p(daily_pnl(trades, failed, days_oos), pool)
    bar = z_bar(pool["n_total"])
    deflation_ok = (dp > 0.95) if dp is not None else bool(math.isfinite(z) and z > bar)
    slips = [t["slip"] for t in trades if t.get("slip") is not None]
    out.update(mean=mean, median=float(np.median(r)), win=float((pnl > 0).mean()), pnl_sol=float(pnl.sum()),
               band=(lo, hi), z=z, z_bar=bar, deflated_p=dp, deflation="study" if dp is not None else "stand-in",
               deflation_ok=bool(deflation_ok), slip_median=float(np.median(slips)) if slips else None,
               lat_buy_median_ms=float(np.median([t["lat_buy_ms"] for t in trades if t.get("lat_buy_ms") is not None]))
               if any(t.get("lat_buy_ms") is not None for t in trades) else None,
               exits={w: sum(1 for t in trades if t.get("exit_why") == w)
                      for w in sorted({t.get("exit_why") or "?" for t in trades})})
    out["positive"] = bool(len(e) >= MIN_ENTRIES and mean > 0 and math.isfinite(lo) and lo > 0 and deflation_ok)
    return out


def evaluate(closed: list[dict], failed: list[dict], judged: list, split: int, days: list[str],
             live: list[dict] | None = None, log=print) -> dict:
    from . import study
    from .study import boot_diff, daily_pnl
    by = defaultdict(lambda: {"is": [], "oos": [], "fis": [], "foos": []})
    for t in closed:
        by[t["rule"]]["oos" if t["signal_ms"] >= split else "is"].append(t)
    for f in failed:
        by[f["rule"]]["foos" if f["signal_ms"] >= split else "fis"].append(f)
    split_day = datetime.fromtimestamp(split / 1000, timezone.utc).strftime("%Y-%m-%d")
    days_is = [d for d in days if d <= split_day]
    days_oos = [d for d in days if d >= split_day]
    sharpes = []
    for sc in SCENARIOS:
        for r in judged:
            d = by[f"{r.name}@{sc}"]
            x = daily_pnl(d["is"], d["fis"], days_is)
            sharpes.append(float(x.mean() / x.std() * math.sqrt(365)) if len(x) > 1 and x.std() > 0 else 0.0)
    pool = study.pool(sharpes)
    table: dict[str, dict[str, dict]] = {sc: {} for sc in SCENARIOS}
    ent: dict[tuple, list] = {}
    for sc in SCENARIOS:
        for r in judged:
            d = by[f"{r.name}@{sc}"]
            table[sc][r.name] = stats(d["oos"], d["foos"], days_oos, pool)
            table[sc][r.name]["is_n"] = len(d["is"]) + len(d["fis"])
            ent[(sc, r.name)] = entries(d["oos"], d["foos"])
    fast = {}
    for r in judged:
        b, c, ct = (table[k][r.name] for k in ("B", "C", "Ct"))
        if not b.get("n") or not c.get("n"):
            continue
        lo, hi = boot_diff(ent[("C", r.name)], ent[("B", r.name)])
        fast[r.name] = {"mean_b": b.get("mean"), "mean_c": c.get("mean"), "diff": c["mean"] - b["mean"],
                        "band": (lo, hi), "pnl_b": b["pnl_sol"], "pnl_c": c["pnl_sol"],
                        "pnl_diff": c["pnl_sol"] - b["pnl_sol"], "n_b": b["n"], "n_c": c["n"],
                        "tip_cost": (ct["mean"] - c["mean"]) if ct.get("n") else None,
                        "tip_pnl": (ct["pnl_sol"] - c["pnl_sol"]) if ct.get("n") else None}
    better = {}
    base = ent.get(("B", BASE_RULE)) or []
    mb = table["B"].get(BASE_RULE, {}).get("mean")
    for r in judged:
        if r.name == BASE_RULE:
            continue
        s = table["B"][r.name]
        if s.get("n", 0) < MIN_ENTRIES or not base or mb is None:
            continue
        lo, hi = boot_diff(ent[("B", r.name)], base)
        better[r.name] = {"mean": s["mean"], "base_mean": mb, "diff": s["mean"] - mb, "band": (lo, hi),
                          "better": bool(s["mean"] > mb and math.isfinite(lo) and lo > 0)}
    calib = calibrate(closed, failed, live or [])
    return {"pool": pool, "table": table, "fast": fast, "better_than_base": better, "calibration": calib,
            "days_oos": days_oos, "days_is": days_is}


def calibrate(closed: list[dict], failed: list[dict], live: list[dict]) -> list[dict]:
    """The live test's tokens where the replay's P_cmig_model books signalled them (any half), next to the
    live result."""
    out = []
    for lv in live:
        row = {"symbol": lv.get("symbol"), "live_ret": _f(lv.get("ret")), "live_pnl_sol": _f(lv.get("pnl_sol")),
               "live_exit": lv.get("exit_why"), "live_lat_buy_ms": _f(lv.get("lat_buy_ms"))}
        for sc in SCENARIOS:
            name = f"{BASE_RULE}@{sc}"
            t = next((t for t in closed if t["rule"] == name and t["mint"] == lv.get("mint")), None)
            f = next((f for f in failed if f["rule"] == name and f["mint"] == lv.get("mint")), None)
            row[sc] = ({"ret": t["ret"], "exit": t.get("exit_why"), "slip": t.get("slip")} if t is not None else
                       {"failed": f["why"]} if f is not None else None)
        out.append(row)
    return out


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def read_live_ledger(path: Path) -> list[dict]:
    try:
        with path.open(newline="", encoding="utf-8") as fh:
            return list(csv.DictReader(fh))
    except OSError:
        return []


# ---------------------------------------------------------------- the run

def run(root=None, until_ms: int = UNTIL_MS, log=print) -> dict:
    """The study's pass 1 (pick, in-sample models), then every book under every scenario on the record."""
    from . import early as EA
    from . import exitpol as XP
    from . import model as M
    from . import sim, store
    from . import strategies as S
    from . import wallets as W
    from .categorize import CategoryIndex
    from .study import WARM_DAYS, WINDOW_DAYS, MIN_IS_TRADES, X14_KEEP_DAYS, span_of, trade_stats, warm_book
    cutoff_day = datetime.fromtimestamp(until_ms / 1000, timezone.utc).strftime("%Y-%m-%d")
    all_days = [d for d in store.days(root) if d <= cutoff_day]
    days = all_days[-WINDOW_DAYS:]
    if not days:
        return {"empty": True}
    warm = [d for d in all_days if d < days[0]][-WARM_DAYS:]
    t_lo, t_hi = span_of(days, root)
    t_hi = min(t_hi, until_ms)
    split = t_lo + (t_hi - t_lo) // 2
    log(f"reallat: {len(days)} day(s) {days[0]} to {days[-1]}, record to "
        f"{datetime.fromtimestamp(t_hi / 1000, timezone.utc):%Y-%m-%d %H:%M} UTC, split at "
        f"{datetime.fromtimestamp(split / 1000, timezone.utc):%Y-%m-%d %H:%M} UTC, warm-up {len(warm)} day(s)")
    cats = CategoryIndex.load(None if root is None else Path(root) / "categories")
    keep = min(1.0, X14_KEEP_DAYS / max(1, len(days)))

    # pass 1, exactly the study's: the registered fill model, 0.1 SOL, the pick and the in-sample models
    t0 = time.time()
    e1 = sim.Engine(S.RULES, book=warm_book(warm, root), decisions=True, entry_until=split,
                    wallets=W.warm(warm, root), cats=cats, early_rows=True, snipers=EA.warm_snipers(warm, root))
    e1.early.keep_frac = keep
    sim.replay(days, e1, root, until_ms=min(split + 45 * 60_000, until_ms))
    by_rule = defaultdict(list)
    for t in e1.closed:
        if t["signal_ms"] < split:
            by_rule[t["rule"]].append(t)
    cands = [(trade_stats(v)["mean"], trade_stats(v)["pnl_sol"], r) for r, v in by_rule.items()
             if len(v) >= MIN_IS_TRADES]
    pick = max(cands)[2] if cands else S.DEFAULT_PICK
    models = M.train_all(e1.table(), until_ms=split)
    try:
        models.update(XP.fit_live(e1.early.tables(), until_ms=split, log=log))
    except Exception as e:                                       # as the study: the X14 books then wait
        log(f"reallat: X14 in-sample models failed ({type(e).__name__}: {e})")
    del e1
    log(f"reallat: pass 1 in {time.time() - t0:.0f} s, pick {pick}, models {sorted(models)}")

    # pass 2: every book under every scenario, 0.03 SOL
    t0 = time.time()
    rules, strats, costs, judged = books(pick)
    stake0 = sim.STAKE
    sim.STAKE = int(STAKE_SOL * C.LAMPORTS)
    try:
        e2 = sim.Engine(rules, book=warm_book(warm, root), decisions=False, model=M.Filter(models), rule_costs=costs,
                        strategies=strats, wallets=W.warm(warm, root), cats=cats, models=models,
                        snipers=EA.warm_snipers(warm, root))
        sim.replay(days, e2, root, until_ms=until_ms)
    finally:
        sim.STAKE = stake0
    log(f"reallat: pass 2 in {time.time() - t0:.0f} s, {len(e2.closed):,} closed, {len(e2.failed):,} failed buys")
    return {"days": days, "warm": warm, "split_ms": split, "span": (t_lo, t_hi), "until_ms": until_ms, "pick": pick,
            "models": sorted(models), "closed": e2.closed, "failed": e2.failed, "judged": judged,
            "skipped": {f"{k[0]}: {k[1]}": v for k, v in e2.skipped.items()}, "counts": dict(e2.counts)}


# ---------------------------------------------------------------- report

def pct(x) -> str:
    return "n/a" if x is None or (isinstance(x, float) and not math.isfinite(x)) else f"{x * 100:+.1f} %"


def report_md(res: dict, ev: dict, lat: dict) -> str:
    def ms(d):
        return f"{d['p50'] / 1000:.1f} s ({d['p10'] / 1000:.1f} to {d['p90'] / 1000:.1f})"
    md = ["# pump.fun rules at the measured latency (Y5)", "",
          f"Record {res['days'][0]} to {datetime.fromtimestamp(res['span'][1] / 1000, timezone.utc):%Y-%m-%d %H:%M} "
          f"UTC, split {datetime.fromtimestamp(res['split_ms'] / 1000, timezone.utc):%Y-%m-%d %H:%M} UTC, pick "
          f"{res['pick']}. Stake {STAKE_SOL} SOL. Out of sample.", "",
          "| scenario | buy, median (10 to 90 %) | sale | fee per transaction |", "|---|---|---|---|"]
    for sc in SCENARIOS:
        d = lat[sc]
        md.append(f"| {SCENARIO_LABEL[sc]} | {ms(d['buy'])} | {ms(d['sell'])} | {d['tx_fee_sol']:.6f} SOL |")
    p = ev["pool"]
    md += ["", f"Pool {p['n_total']} trials; stand-in deflation bar z > {z_bar(p['n_total']):.2f}.", ""]
    for sc in SCENARIOS:
        md += [f"## {SCENARIO_LABEL[sc]}", "",
               "| rule | entries | failed | mean | median | win | P&L SOL | band of mean | z | deflated p | positive |",
               "|---|---|---|---|---|---|---|---|---|---|---|"]
        rows = sorted(ev["table"][sc].items(), key=lambda kv: -(kv[1].get("mean") if kv[1].get("mean") is not None
                                                                else -9))
        for name, s in rows:
            if not s.get("n"):
                md.append(f"| {name} | 0 | 0 | n/a | n/a | n/a | +0.000 | n/a | n/a | n/a | no |")
                continue
            b = s["band"]
            md.append(f"| {name} | {s['n']} | {s['failed']} | {pct(s['mean'])} | {pct(s['median'])} | "
                      f"{s['win'] * 100:.0f} % | {s['pnl_sol']:+.3f} | {pct(b[0])} to {pct(b[1])} | "
                      + ("n/a" if not math.isfinite(s["z"]) else f"{s['z']:+.2f}") + " | "
                      + ("n/a" if s["deflated_p"] is None else f"{s['deflated_p']:.2f}") + " | "
                      + ("yes" if s["positive"] else "no") + " |")
        md.append("")
    md += ["## The 1.5 s send path against today (C minus B)", "",
           "| rule | mean B | mean C | C - B | band | P&L B | P&L C | tip cost per trade |", "|---|---|---|---|---|---|---|---|"]
    for name, f in sorted(ev["fast"].items(), key=lambda kv: -kv[1]["diff"]):
        md.append(f"| {name} | {pct(f['mean_b'])} | {pct(f['mean_c'])} | {pct(f['diff'])} | {pct(f['band'][0])} to "
                  f"{pct(f['band'][1])} | {f['pnl_b']:+.3f} | {f['pnl_c']:+.3f} | {pct(f['tip_cost'])} |")
    md += ["", f"## Against {BASE_RULE} at (b)", "", "| rule | mean | P_cmig_model | difference | band | better |",
           "|---|---|---|---|---|---|"]
    for name, b in sorted(ev["better_than_base"].items(), key=lambda kv: -kv[1]["diff"]):
        md.append(f"| {name} | {pct(b['mean'])} | {pct(b['base_mean'])} | {pct(b['diff'])} | {pct(b['band'][0])} to "
                  f"{pct(b['band'][1])} | {'yes' if b['better'] else 'no'} |")
    if ev.get("calibration"):
        md += ["", "## The live test's tokens in the replay", "",
               "| token | live return | live exit | " + " | ".join(SCENARIOS) + " |", "|---|---|---|" + "---|" * 4]
        for c in ev["calibration"]:
            cells = []
            for sc in SCENARIOS:
                x = c.get(sc)
                cells.append("not signalled" if x is None else f"failed: {x['failed']}" if "failed" in x
                             else f"{pct(x['ret'])} ({x['exit']})")
            md.append(f"| {c['symbol']} | {pct(c['live_ret'])} | {c['live_exit']} | " + " | ".join(cells) + " |")
    return "\n".join(md) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--until-ms", type=int, default=UNTIL_MS)
    ap.add_argument("--out", default=None, help="directory for reallat.json and reallat.md (default: the reports)")
    ap.add_argument("--live-ledger", default=None, help="the live test's ledger.csv (read only)")
    a = ap.parse_args(argv)
    from .. import report as rep
    from ..data import ROOT
    out = Path(a.out) if a.out else rep.REPORTS / "pumpfun_rt"
    out.mkdir(parents=True, exist_ok=True)
    live_path = Path(a.live_ledger) if a.live_ledger else ROOT / "live" / "pumpfun_rt" / "ledger.csv"
    live = read_live_ledger(live_path)
    lat = {sc: describe(c) for sc, c in scenarios().items()}
    res = run(until_ms=a.until_ms)
    if res.get("empty"):
        print("reallat: nothing recorded")
        return 1
    ev = evaluate(res["closed"], res["failed"], res["judged"], res["split_ms"], res["days"], live)
    md = report_md(res, ev, lat)
    keep = {k: v for k, v in res.items() if k not in ("closed", "failed", "judged")}
    (out / "reallat.json").write_text(json.dumps(keep | {"latency": lat, "eval": ev}, indent=1, default=str),
                                      encoding="utf-8")
    (out / "reallat.md").write_text(md, encoding="utf-8")
    print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
