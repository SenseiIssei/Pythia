"""The daily job of the real-time pump.fun lab: the pre-registered rules on the record,
the model, the report, the pick for the shadow book and the daily card. PAPER ONLY.

    python -m lab.pumpfun_rt.study                 run, write reports/pumpfun_rt/, post the card
    python -m lab.pumpfun_rt.study --no-notify     the same without the card
    python -m lab.pumpfun_rt.study --dry-run       print the report, write and post nothing

Steps (results/pumpfun_realtime_plan.md):

 1. Finished days' part files are merged into one file per table (store.compact).
 2. The record is the last WINDOW_DAYS days; the creator history is warmed up on up
    to WARM_DAYS days before it (creations, completions and the creators' own sells).
 3. The split: the first half of the record's time span is in sample, the rest out.
 4. Pass 1 replays the in-sample half with every rule and the model's decision rows;
    the pick is the rule with the best in-sample mean net return per trade (30+
    trades), and a model for the filter is trained on in-sample rows only.
 5. Pass 2 replays the whole record with every rule, every rule at doubled latency
    and at tripled priority fee, and the pick with the model filter; out-of-sample
    numbers are the trades signalled after the split.
 6. The bar for every rule; deflation against the lab's global pool.
 7. The model: purged walk-forward of every label on pass 2's rows, against the base
    rate and a logistic regression; the daily model is trained on all rows and saved.
 8. reports/pumpfun_rt/latest.{md,json} (lab feed header), pick.json, the card.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone

import numpy as np

from .. import report as rep
from . import curve as C
from . import model as M
from . import sim
from . import store
from . import strategies as S
from .tokens import CreatorBook

NAME = "pumpfun_rt"
WINDOW_DAYS = 14
WARM_DAYS = 7
BOOK_SOL = 10.0
MIN_IS_TRADES = 30
GATE_DAYS, GATE_TRADES = 14, 300
BOOT_DRAWS = 5000
MIN_BLOCKS = 10
DAY_MS = 86_400_000
# The lab's pool before this study (see the plan): 377 hand trials to C16 at the published
# bar (Sharpe 2.43 over 377), 231 counted in parallel, overnight 39, book_portfolio 30,
# flow_overlays 198, the three 5-minute pump.fun rules; plus the factory's ledger.
PRIOR_HAND = 878
LAT_STRESS, PRIO_STRESS = 2.0, 3.0


def _day(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%d")


# ---------------------------------------------------------------- warm-up

def warm_book(days: list[str], root=None) -> CreatorBook:
    """The creator history from earlier days: who made what, what completed, who dumped."""
    import polars as pl
    book = CreatorBook()
    if not days:
        return book
    cr = store.read("creates", days, root).select("t", "mint", "creator", pl.col("user").alias("payer")).sort("t")
    ot = store.read("other", days, root).filter(pl.col("kind") == "complete").select("t", "mint")
    tr = store.read("trades", days, root).select("t", "mint", "user", "buy", "tok")
    dev = tr.join(cr.select("mint", "creator", "payer"), on="mint").filter(
        (pl.col("user") == pl.col("creator")) | (pl.col("user") == pl.col("payer")))
    agg = dev.group_by("mint").agg((pl.col("tok") * pl.col("buy")).sum().alias("bought"),
                                   (pl.col("tok") * (~pl.col("buy"))).sum().alias("sold"),
                                   pl.col("t").filter(~pl.col("buy")).min().alias("sell_t"))
    dumped = {r["mint"]: r["sell_t"] for r in agg.iter_rows(named=True)
              if r["bought"] and r["sold"] >= sim.DUMP * r["bought"]}
    events = [(r["t"], 0, r["creator"], r["mint"]) for r in cr.iter_rows(named=True)]
    owner = dict(zip(cr["mint"].to_list(), cr["creator"].to_list()))
    events += [(r["t"], 1, owner[r["mint"]], r["mint"]) for r in ot.iter_rows(named=True) if r["mint"] in owner]
    events += [(t or 0, 2, owner[m], m) for m, t in dumped.items() if m in owner]
    for t, k, creator, _ in sorted(events, key=lambda e: (e[0], e[1])):
        if k == 0:
            book.created(creator, t)
        elif k == 1:
            book.migrated(creator)
        else:
            book.dumped(creator)
    return book


# ---------------------------------------------------------------- numbers

def trade_stats(trades: list[dict], failed: list[dict] | None = None) -> dict:
    rets = np.array([t["ret"] for t in trades], dtype=float)
    n = len(rets)
    fail_pnl = sum(f["pnl_sol"] for f in failed or [])
    pnl = float(sum(t["pnl_sol"] for t in trades)) + fail_pnl
    out = {"n": n, "failed": len(failed or []), "pnl_sol": pnl}
    if n == 0:
        return out
    out.update(hit=float((rets > 0).mean()), mean=float(rets.mean()), median=float(np.median(rets)),
               q05=float(np.quantile(rets, 0.05)), q95=float(np.quantile(rets, 0.95)), best=float(rets.max()),
               worst=float(rets.min()), rugs=int((rets <= -0.9).sum()),
               dev_dumped=float(np.mean([bool(t.get("dev_dumped")) for t in trades])),
               broken=float(np.mean([bool(t.get("breaks")) for t in trades])),
               mean_clean=float(np.mean([t["ret"] for t in trades if not t.get("breaks")]))
               if any(not t.get("breaks") for t in trades) else None,
               hold_s=float(np.median([t["hold_s"] for t in trades])),
               why={w: sum(1 for t in trades if t.get("exit_why") == w) for w in ("take", "stop", "time", "stuck")})
    return out


def daily_pnl(trades: list[dict], failed: list[dict], days: list[str]) -> np.ndarray:
    by = defaultdict(float)
    for t in trades:
        by[_day(t["exit_ms"])] += t["pnl_sol"]
    for f in failed:
        by[_day(f["land_ms"])] += f["pnl_sol"]
    return np.array([by.get(d, 0.0) / BOOK_SOL for d in days])


def boot_mean(trades: list[dict], draws: int = BOOT_DRAWS, seed: int = 7) -> tuple[float, float]:
    """90 % band of the mean net return per trade, resampling whole hours (trades of one hour
    move together: one market, one mood)."""
    if not trades:
        return math.nan, math.nan
    by = defaultdict(list)
    for t in trades:
        by[t["signal_ms"] // 3_600_000].append(t["ret"])
    blocks = [np.array(v) for v in by.values()]
    if len(blocks) < MIN_BLOCKS:
        return math.nan, math.nan                    # a band from a handful of hours means nothing
    sums = np.array([b.sum() for b in blocks])
    lens = np.array([len(b) for b in blocks])
    rng = np.random.default_rng(seed)
    k = len(blocks)
    idx = rng.integers(0, k, size=(draws, k))
    m = sums[idx].sum(axis=1) / np.maximum(lens[idx].sum(axis=1), 1)
    return float(np.quantile(m, 0.05)), float(np.quantile(m, 0.95))


def boot_diff(a: list[dict], b: list[dict], draws: int = BOOT_DRAWS, seed: int = 11) -> tuple[float, float]:
    """90 % band of mean(a) - mean(b), resampling the same hours for both."""
    if not a or not b:
        return math.nan, math.nan
    hours = sorted({t["signal_ms"] // 3_600_000 for t in a + b})
    pos = {h: i for i, h in enumerate(hours)}
    sa, na, sb, nb = (np.zeros(len(hours)) for _ in range(4))
    for t in a:
        sa[pos[t["signal_ms"] // 3_600_000]] += t["ret"]
        na[pos[t["signal_ms"] // 3_600_000]] += 1
    for t in b:
        sb[pos[t["signal_ms"] // 3_600_000]] += t["ret"]
        nb[pos[t["signal_ms"] // 3_600_000]] += 1
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(hours), size=(draws, len(hours)))
    d = sa[idx].sum(1) / np.maximum(na[idx].sum(1), 1) - sb[idx].sum(1) / np.maximum(nb[idx].sum(1), 1)
    return float(np.quantile(d, 0.05)), float(np.quantile(d, 0.95))


def pool(mine_annual: list[float]) -> dict:
    """The global deflation pool with this study's trials in it."""
    from ..experiments import fam_common as fc
    from ..experiments import flow_overlays as fo
    v1 = fo.prior_var()
    try:
        fx = np.clip(fo.factory_sharpes(), -fc.SR_CLIP, fc.SR_CLIP) / math.sqrt(365)
    except Exception:
        fx = np.array([])
    x = np.clip(np.array([s for s in mine_annual if np.isfinite(s)] or [0.0]), -fc.SR_CLIP, fc.SR_CLIP) / math.sqrt(365)
    n1, n2, n3 = PRIOR_HAND, len(fx), S.N_TRIALS
    v2 = float(np.var(fx)) if len(fx) > 1 else 0.0
    v3 = float(np.var(x)) if len(x) > 1 else 0.0
    n = n1 + n2 + n3
    v = (n1 * v1 + n2 * v2 + n3 * v3) / n
    return {"hand_trials": n1, "factory_trials": n2, "mine": n3, "n_total": n, "var": v,
            "sr0_annual": fc._sr0(v, n) * math.sqrt(365)}


def deflated_p(x: np.ndarray, pl_: dict) -> float | None:
    from ..experiments import flow_overlays as fo
    if len(x) < 5 or x.std() == 0:
        return None
    return float(fo.deflated(x, pl_["n_total"], pl_["var"]))


def gates(name: str, oos: list[dict], oos_failed: list[dict], stress: dict[str, list[dict]], days_oos: list[str],
          pl_: dict, base: list[dict] | None = None) -> dict:
    st = trade_stats(oos, oos_failed)
    lo, hi = boot_mean(oos)
    span = (max(t["signal_ms"] for t in oos) - min(t["signal_ms"] for t in oos)) / DAY_MS if oos else 0.0
    daily = daily_pnl(oos, oos_failed, days_oos)
    pnl = st["pnl_sol"]
    top5 = sum(sorted((t["pnl_sol"] for t in oos), reverse=True)[:5])
    g = {
        "g1_mean_band": bool(st.get("mean", -1) > 0 and lo > 0),
        "g2_size": bool(st["n"] >= GATE_TRADES and span >= GATE_DAYS),
        "g3_stress": bool(all(trade_stats(v).get("mean", -1) > 0 for v in stress.values()) and stress),
        "g4_breadth": bool(pnl > 0 and top5 < 0.5 * pnl and len(daily) and (daily > 0).mean() >= 0.6),
    }
    dp = deflated_p(daily, pl_)
    g["g5_deflated"] = bool(dp is not None and dp > 0.95)
    if base is not None:
        dlo, dhi = boot_diff(oos, base)
        g["g6_model_beats_pick"] = bool(st.get("mean", -1) > trade_stats(base).get("mean", -1) and dlo > 0)
        st["diff_band"] = (dlo, dhi)
    return {"rule": name, "stats": st, "band": (lo, hi), "span_days": span, "deflated_p": dp,
            "daily_sharpe": float(daily.mean() / daily.std() * math.sqrt(365)) if len(daily) > 1 and daily.std() > 0
            else None, "gates": g, "passes": all(g.values())}


# ---------------------------------------------------------------- the run

def run(now_ms: int | None = None, window: int = WINDOW_DAYS, root=None, log=print) -> dict:
    now_ms = now_ms or int(time.time() * 1000)
    today = _day(now_ms)
    all_days = store.days(root)
    for d in all_days:
        if d < today:
            store.compact(d, root)
    days = all_days[-window:]
    if not days:
        return {"empty": True, "now_ms": now_ms}
    warm = [d for d in all_days if d < days[0]][-WARM_DAYS:]
    t_lo, t_hi = span_of(days, root)
    split = t_lo + (t_hi - t_lo) // 2
    log(f"{NAME}: {len(days)} day(s) {days[0]} to {days[-1]}, split at "
        f"{datetime.fromtimestamp(split / 1000, timezone.utc):%Y-%m-%d %H:%M} UTC, warm-up {len(warm)} day(s)")

    # pass 1: in sample
    t0 = time.time()
    e1 = sim.Engine(S.RULES, book=warm_book(warm, root), decisions=True, entry_until=split)
    sim.replay(days, e1, root, until_ms=split + 45 * 60_000)
    is_trades = [t for t in e1.closed if t["signal_ms"] < split]
    by_rule = defaultdict(list)
    for t in is_trades:
        by_rule[t["rule"]].append(t)
    cands = [(trade_stats(v)["mean"], trade_stats(v)["pnl_sol"], r) for r, v in by_rule.items()
             if len(v) >= MIN_IS_TRADES]
    pick = max(cands)[2] if cands else S.DEFAULT_PICK
    is_models = M.train_all(e1.table(), until_ms=split)
    log(f"{NAME}: pass 1 in {time.time() - t0:.0f} s, {len(is_trades)} in-sample trades, pick {pick}"
        + ("" if cands else f" (no rule had {MIN_IS_TRADES} in-sample trades: the default)"))

    # pass 2: everything
    t0 = time.time()
    base = C.Costs()
    rules = list(S.RULES)
    costs = {}
    for r in S.RULES:
        for suffix, c in (("lat2x", base.scaled(latency=LAT_STRESS)), ("prio3x", base.scaled(priority=PRIO_STRESS))):
            v = sim.variant(r, suffix)
            rules.append(v)
            costs[v.name] = c
    mr = sim.model_rule(S.BY_NAME[pick])
    rules.append(mr)
    e2 = sim.Engine(rules, book=warm_book(warm, root), decisions=True, model=M.Filter(is_models), rule_costs=costs)
    sim.replay(days, e2, root)
    log(f"{NAME}: pass 2 in {time.time() - t0:.0f} s, {len(e2.closed)} closed paper trades, {len(e2.rows)} model rows")

    trades = defaultdict(lambda: {"is": [], "oos": []})
    fails = defaultdict(lambda: {"is": [], "oos": []})
    for t in e2.closed:
        trades[t["rule"]]["oos" if t["signal_ms"] >= split else "is"].append(t)
    for f in e2.failed:
        fails[f["rule"]]["oos" if f["signal_ms"] >= split else "is"].append(f)
    days_oos = [d for d in days if d >= _day(split)]
    sharpes = []
    for r in S.RULES + [mr]:
        x = daily_pnl(trades[r.name]["is"], fails[r.name]["is"], [d for d in days if d <= _day(split)])
        sharpes.append(float(x.mean() / x.std() * math.sqrt(365)) if len(x) > 1 and x.std() > 0 else 0.0)
    pl_ = pool(sharpes)
    results = []
    for r in S.RULES + [mr]:
        stress = {} if r is mr else {s: trades[f"{r.name}@{s}"]["oos"] for s in ("lat2x", "prio3x")}
        g = gates(r.name, trades[r.name]["oos"], fails[r.name]["oos"], stress, days_oos, pl_,
                  base=trades[pick]["oos"] if r is mr else None)
        g.update(family=r.family, label=r.label, is_stats=trade_stats(trades[r.name]["is"], fails[r.name]["is"]),
                 stress={s: trade_stats(v) for s, v in stress.items()})
        results.append(g)

    # the model
    t0 = time.time()
    table = e2.table()
    evals = {label: M.evaluate(table, label) for label in M.LABELS}
    final = M.train_all(table)
    imp = {label: M.importance(m) for label, m in final.items()}
    log(f"{NAME}: model in {time.time() - t0:.0f} s; " + "; ".join(f"{k}: {v['verdict']}" for k, v in evals.items()))

    rec = record_stats(days, root)
    return {"now_ms": now_ms, "days": days, "warm": warm, "split_ms": split, "span": (t_lo, t_hi), "pick": pick,
            "picked_by": "in-sample mean" if cands else "default", "results": results, "pool": pl_,
            "evals": evals, "importance": imp, "models": final, "record": rec,
            "counts": {"pass1": dict(e1.counts), "pass2": dict(e2.counts)},
            "skipped": {f"{k[0]}: {k[1]}": v for k, v in e2.skipped.items() if "@" not in k[0]},
            "failed_why": dict(sorted(((w, sum(1 for f in e2.failed if f["why"] == w and "@" not in f["rule"]))
                                       for w in {f["why"] for f in e2.failed}), key=lambda x: -x[1])),
            "rows": len(table["t"])}


def span_of(days: list[str], root=None) -> tuple[int, int]:
    import polars as pl
    tr = store.read("trades", days, root).select(pl.col("t").min().alias("a"), pl.col("t").max().alias("b"))
    return int(tr["a"][0] or 0), int(tr["b"][0] or 0)


def record_stats(days: list[str], root=None) -> dict:
    """Per day: tokens created (plain SOL curves among them), curve trades, completions,
    migrations, gaps and their minutes."""
    import polars as pl
    out = {}
    for d in days:
        cr = store.read("creates", [d], root)
        ot = store.read("other", [d], root)
        n_tr = store.read("trades", [d], root).height
        plain = cr.filter(pl.col("quote").is_null() & ~pl.col("mayhem").fill_null(False)).height if cr.height else 0
        gaps = ot.filter(pl.col("kind") == "gap") if ot.height else ot
        out[d] = {"tokens": cr.height, "plain": plain, "trades": n_tr,
                  "completed": ot.filter(pl.col("kind") == "complete").height if ot.height else 0,
                  "migrated": ot.filter(pl.col("kind") == "migrate").height if ot.height else 0,
                  "gaps": gaps.height,
                  "gap_min": float(((gaps["t"] - gaps["t0"]).sum() or 0) / 60_000) if gaps.height else 0.0}
    return out


# ---------------------------------------------------------------- report

def pct(x) -> str:
    return "n/a" if x is None or (isinstance(x, float) and not math.isfinite(x)) else f"{x * 100:+.1f} %"


def report(res: dict) -> tuple[dict, str]:
    days = res["days"]
    rec = res["record"]
    n_days = len(days)
    early = n_days < GATE_DAYS
    tok = sum(v["tokens"] for v in rec.values())
    plain = sum(v["plain"] for v in rec.values())
    trd = sum(v["trades"] for v in rec.values())
    done = sum(v["completed"] for v in rec.values())
    gap_min = sum(v["gap_min"] for v in rec.values())
    results = res["results"]
    passed = [r for r in results if r["passes"]]
    pick = res["pick"]
    pick_row = next(r for r in results if r["rule"] == pick)
    mrow = next(r for r in results if r["rule"].endswith("+model"))
    useful = [k for k, v in res["evals"].items() if v.get("useful")]
    ps = pick_row["stats"]
    head = (f"Paper only. {n_days} day(s) of record: {tok:,} tokens ({plain:,} on plain SOL curves), {trd:,} curve "
            f"trades, {done:,} completed curves. ")
    if early:
        head += (f"Too early to judge (the bar needs {GATE_DAYS} days and {GATE_TRADES} out-of-sample trades). ")
    head += (f"Out of sample the pick {pick} made {ps['n']} trades, mean {pct(ps.get('mean'))} per trade, "
             f"{ps['pnl_sol']:+.2f} SOL; {len(passed)} of {len(results)} rules pass the bar. "
             f"The model beats its baselines on {len(useful)} of {len(res['evals'])} labels.")
    status = "bad" if not passed else "watch"
    items = [{"label": "Record", "value": f"{n_days} d", "status": "watch" if early else "ok",
              "detail": f"{tok:,} tokens, {plain:,} plain, {trd:,} trades, {done:,} completed, gaps {gap_min:.0f} min",
              "importance": 40}]
    for r in sorted(results, key=lambda r: -(r["stats"].get("mean") if r["stats"].get("mean") is not None else -9))[:8]:
        s = r["stats"]
        items.append({"label": f"pump.fun RT {r['rule']}", "value": pct(s.get("mean")),
                      "status": "ok" if r["passes"] else ("watch" if (s.get("mean") or -1) > 0 else "bad"),
                      "detail": f"{r['label']}. Out of sample {s['n']} trades, hit {pct(s.get('hit'))}, median "
                                f"{pct(s.get('median'))}, {s.get('rugs', 0)} at -90 % or worse, "
                                f"{s['pnl_sol']:+.2f} SOL" + (" (the pick)" if r["rule"] == pick else ""),
                      "link": "study:pumpfun_realtime", "importance": 30 if r["rule"] == pick else 20})
    for k, v in res["evals"].items():
        pm = (v.get("pooled") or {}).get("model") or {}
        items.append({"label": f"Model {k}", "value": f"AUC {pm.get('auc', float('nan')):.3f}" if pm else "n/a",
                      "status": "ok" if v.get("useful") else "watch", "detail": v.get("verdict", ""),
                      "importance": 15})
    data = {**rep.feed_header("pump.fun real-time lab", status, head, items, updated_ms=res["now_ms"]),
            "caveat": "Paper only: no wallet, no key, no transaction. Fills are modelled with latency; real "
                      "snipers are faster.",
            "pick": pick, "split_ms": res["split_ms"], "days": days, "record": rec,
            "results": [{k: v for k, v in r.items()} for r in results], "pool": res["pool"],
            "evals": res["evals"], "importance": res["importance"], "skipped": res["skipped"],
            "failed_why": res["failed_why"], "counts": res["counts"]}
    md = [f"# pump.fun real-time lab ({_day(res['now_ms'])})", "", data["caveat"], "", head, "",
          "## Record", "", "| day | tokens | plain SOL | curve trades | completed | migrated | gaps | gap min |",
          "|---|---|---|---|---|---|---|---|"]
    for d, v in rec.items():
        md.append(f"| {d} | {v['tokens']:,} | {v['plain']:,} | {v['trades']:,} | {v['completed']} | {v['migrated']} | "
                  f"{v['gaps']} | {v['gap_min']:.1f} |")
    q = res["counts"]["pass2"]
    if q.get("curve_trades"):
        md += ["", f"Completeness: {q['curve_trades']:,} trades on {q.get('curve_tokens', 0):,} plain curves; "
               f"{q.get('curve_breaks', 0):,} slots did not chain up (a trade the stream missed), "
               f"{q.get('curve_tokens_broken', 0) / max(1, q.get('curve_tokens', 1)):.0%} of the curves have at "
               f"least one. A trade whose hold spans one is marked; their share is the \"broken\" column."]
    md += ["", f"Split at {datetime.fromtimestamp(res['split_ms'] / 1000, timezone.utc):%Y-%m-%d %H:%M} UTC; "
           f"pick {pick} ({res['picked_by']}).", "",
           "## Rules out of sample", "",
           "| rule | trades | failed | hit | mean | median | 5 % | 95 % | worst | best | at -90 % | dev dumped | "
           "broken | mean, unbroken | P&L SOL | band of mean | lat 2x | prio 3x | in-sample mean (n) | passes |",
           "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in results:
        s, b, i = r["stats"], r["band"], r["is_stats"]
        stx = r.get("stress") or {}
        md.append(f"| {r['rule']} | {s['n']} | {s['failed']} | {pct(s.get('hit'))} | {pct(s.get('mean'))} | "
                  f"{pct(s.get('median'))} | {pct(s.get('q05'))} | {pct(s.get('q95'))} | {pct(s.get('worst'))} | "
                  f"{pct(s.get('best'))} | {s.get('rugs', 0)} | {pct(s.get('dev_dumped'))} | "
                  f"{pct(s.get('broken'))} | {pct(s.get('mean_clean'))} | {s['pnl_sol']:+.3f} | "
                  f"{pct(b[0])} to {pct(b[1])} | {pct((stx.get('lat2x') or {}).get('mean'))} | "
                  f"{pct((stx.get('prio3x') or {}).get('mean'))} | {pct(i.get('mean'))} ({i['n']}) | "
                  f"{'yes' if r['passes'] else 'no'} |")
    md += ["", "Gates (out of sample): g1 mean and its hour-block band above 0; g2 300+ trades over 14+ days; g3 "
           "above 0 at doubled latency and tripled priority fee; g4 best five under half the P&L and 60 % of days "
           "positive; g5 deflated p above 0.95; g6 (model) beats the pick, band of the difference above 0.", ""]
    for r in results:
        failed_g = [k for k, v in r["gates"].items() if not v]
        md.append(f"- {r['rule']}: " + ("passes every gate" if not failed_g else "fails " + ", ".join(failed_g))
                  + (f"; deflated p {r['deflated_p']:.2f}" if r["deflated_p"] is not None else "; deflated p n/a "
                     "(under 5 days)"))
    p = res["pool"]
    md += ["", f"Deflation pool: {p['n_total']} trials ({p['hand_trials']} hand, {p['factory_trials']} factory, "
           f"{p['mine']} here); the best of that many noise strategies shows an annual Sharpe of about "
           f"{p['sr0_annual']:.2f}.", "", "Failed buys: " + ", ".join(f"{k} {v}" for k, v in res["failed_why"].items()),
           "", "## Model", "", "| label | rows | folds | model AUC | Brier skill | ECE | logistic AUC | base rate | "
           "verdict |", "|---|---|---|---|---|---|---|---|---|"]
    for k, v in res["evals"].items():
        po = v.get("pooled") or {}
        pm, plg = po.get("model") or {}, po.get("logistic") or {}
        md.append(f"| {k} | {v['rows']} | {len(v.get('folds', []))} | {pm.get('auc', float('nan')):.3f} | "
                  f"{pm.get('brier_skill', float('nan')):+.3f} | {pm.get('ece', float('nan')):.3f} | "
                  f"{plg.get('auc', float('nan')):.3f} | {pm.get('rate', float('nan')):.3f} | {v.get('verdict', '')} |")
    for k, imp in res["importance"].items():
        if imp:
            md.append(f"\n{k} top features (gain): " + ", ".join(f"{f} {g:.2f}" for f, g in imp[:8]))
    return data, "\n".join(md) + "\n"


# ---------------------------------------------------------------- the daily card

def shadow_yesterday(now_ms: int) -> dict[str, dict]:
    """The live shadow books' trades closed yesterday (UTC), from the paper ledger."""
    import csv
    from .live import paper_dir
    y = _day(now_ms - DAY_MS)
    out: dict[str, list] = defaultdict(list)
    p = paper_dir() / "ledger.csv"
    if p.exists():
        with p.open(newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                if not r.get("exit_ms") or r.get("exit_why") == "restart" or r.get("gap") == "True":
                    continue
                if _day(int(float(r["exit_ms"]))) == y:
                    out[r["rule"]].append({"ret": float(r["ret"]), "pnl_sol": float(r["pnl_sol"])})
    return {k: {"n": len(v), "wins": sum(t["ret"] > 0 for t in v), "mean": float(np.mean([t["ret"] for t in v])),
                "pnl_sol": float(sum(t["pnl_sol"] for t in v))} for k, v in out.items()}


def daily_card(res: dict, shadow: dict, lang: str = "en"):
    from ..ops import i18n, notify
    t = i18n.t
    y = _day(res["now_ms"] - DAY_MS)
    rec = res["record"].get(y) or {"tokens": 0, "trades": 0, "completed": 0}
    lines = [t("prt_daily_record", lang, tokens=i18n.num(rec["tokens"], 0, lang),
               trades=i18n.num(rec["trades"], 0, lang), done=i18n.num(rec["completed"], 0, lang))]
    rows = []
    for book in (res["pick"], res["pick"] + "+model"):
        s = shadow.get(book)
        if s and s["n"]:
            lines.append(t("prt_daily_book", lang, book=book, n=s["n"], hit=s["wins"],
                           mean=i18n.frac_pct(s["mean"], 1, lang), pnl=f"{i18n.num(s['pnl_sol'], 3, lang, True)} SOL"))
            rows.append([book[:22], str(s["n"]), i18n.frac_pct(s["mean"], 1, lang),
                         i18n.num(s["pnl_sol"], 3, lang, True)])
        else:
            lines.append(t("prt_daily_book_none", lang, book=book))
    n_days = len(res["days"])
    passed = sum(1 for r in res["results"] if r["passes"])
    if n_days < GATE_DAYS:
        lines.append(t("prt_daily_early", lang, days=n_days))
    lines.append(t("prt_daily_study", lang, passed=passed, rules=len(res["results"]), pick=res["pick"]))
    lines.append(t("prt_daily_model", lang, useful=sum(1 for v in res["evals"].values() if v.get("useful")),
                   labels=len(res["evals"])))
    parts = [notify.Line(" ".join(lines[1:]))]
    if rows:
        parts.insert(0, notify.Table([t("prt_col_book", lang), t("prt_col_closed", lang), t("prt_col_mean", lang),
                                      t("prt_col_pnl", lang)], rows))
    parts.append(notify.Line(t("prt_caveat", lang)))
    return notify.Card("⚡", t("prt_daily_title", lang, day=i18n.iso_day(y, lang)), lines[0], parts,
                       footer=t("prt_footer", lang))


def save_outputs(res: dict, data: dict, md: str) -> None:
    rep.write(NAME, md, data)
    M.save(res["models"], {"trained_ms": res["now_ms"], "rows": res["rows"], "days": res["days"],
                           "evals": {k: {kk: vv for kk, vv in v.items() if kk != "folds"} for k, v in res["evals"].items()},
                           "features": res["models"][next(iter(res["models"]))].features if res["models"] else []})
    d = rep.REPORTS / NAME
    d.mkdir(parents=True, exist_ok=True)
    (d / "pick.json").write_text(json.dumps({"pick": res["pick"], "picked_by": res["picked_by"],
                                             "updated_ms": res["now_ms"], "split_ms": res["split_ms"]}, indent=1),
                                 encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-notify", action="store_true")
    ap.add_argument("--window", type=int, default=WINDOW_DAYS)
    a = ap.parse_args(argv)
    res = run(window=a.window)
    if res.get("empty"):
        print(f"{NAME}: nothing recorded yet")
        return 1
    data, md = report(res)
    if a.dry_run:
        print(md)
        return 0
    save_outputs(res, data, md)
    if not a.no_notify:
        from ..ops import notify
        notify.send("trending", [daily_card(res, shadow_yesterday(res["now_ms"]), notify.alert_lang())],
                    now=res["now_ms"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
