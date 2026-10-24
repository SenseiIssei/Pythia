"""Y16: a rug filter for P_pool0_wait, judged against P_pool0_wait at the paper model's latency and at the latency the
live executor measures. PAPER ONLY.

    python -m lab.pumpfun_rt.rug16                      replay, print the report, write rug16.{json,md}
    python -m lab.pumpfun_rt.rug16 --out DIR            the same, written into DIR

Pre-registered in results/pumpfun_rugfilter_prereg.md. One replay of the record up to the cutoff with the select and
trend trackers in the engine and:

  the label book   selfeat.LabelPipe (Y9's, as Y10): every plain migration bought as P_pool0 would; at the end of every
                   UTC day the select models are trained on what was decided and labelled before the next day starts
                   and used through that next day (select9.DayModels), so the rug models are walk-forward
  the books        P_pool0_wait (X0) and its three rug twins (pipeline._build_y16: R1 P(rug0t) at most its base rate,
                   R2 at most half of it, R3 the single-feature rule picked at the split), each its own book of at most
                   4 positions, under two latencies (A the paper engine's model, B Y9's measured Sender fills) and two
                   daily loss limits (L25 the live bot's 0.25 SOL, L100 the code's cap of 1.0 SOL), every book drawing
                   its latency with P_pool0's key
  the features     every X0 book notes at each signal what a decision may know (selfeat.decision_features, the pool's
                   SOL, P(rug0) and P(rug0t), the buys of other wallets in the slot of the coin's first trade, the dev's
                   sales so far) and, per position, the largest fall of the pool's price on one trade while held

Out of sample: from the first UTC day with the rug0t model (Y10's rule). At that moment R3's rule is picked on the
closed in-sample entries of X0 at B under 1.0 SOL (pick_cut) and R3 trades with it from then on; before, R3 is X0.
0.001005 SOL per transaction, 0.1 SOL a trade, trades open across a gap kept (Y8's rule). Nothing here holds a wallet,
reads a key, signs or sends anything.
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

from . import curve as C
from . import exitlab as XL
from . import exits8 as X8
from . import lock12 as Y12
from . import pipeline as P
from . import reallat as RL
from . import select9 as Y9
from . import selfeat as SF
from . import selmodel as SM
from .tokens import SUPPLY

# ---------------------------------------------------------------- registered (results/pumpfun_rugfilter_prereg.md)

VARIANTS = (("X0", "P_pool0_wait"), ("R1", "P_pool0_wait_norug"), ("R2", "P_pool0_wait_norug_half"),
            ("R3", "P_pool0_wait_rugcut"))
KEY = Y12.KEY
UNTIL_MS = int(datetime(2026, 10, 23, 23, 0, tzinfo=timezone.utc).timestamp() * 1000)
TAIL_MS = 15 * 60_000                                   # entries stop this long before the cutoff: all close inside
STAKE_SOL = 0.1
LIMITS = Y12.LIMITS
LIMIT_LABEL = Y12.LIMIT_LABEL
LATENCIES = Y12.LATENCIES
LATENCY_LABEL = Y12.LATENCY_LABEL
PICK_BOOK = "B@L100"                                    # R3's rule is picked on X0's in-sample entries of this book
CRASH_RET = -0.35                                       # a one-step crash: lost more than 35 % on the exit,
CRASH_DROP = 0.30                                       # or one pool trade took 30 % off the price while held
WIN = 0.0
# The features looked at (section 2 of the prereg), grouped as the task names them.
FEATURES = (("rug models", ("p_rug0t", "p_rug0")),
            ("the creator", ("dev_hold_share", "dev_buy_sol", "creator_prior", "creator_prior_migrated",
                             "creator_dump_rate")),
            ("top holders after the migration", ("c_top10_share", "top1_share", "top5_share")),
            ("liquidity", ("pool_sol",)),
            ("the curve", ("age_at_complete_s", "unique_buyers", "c_ubuyers_300")),
            ("bundled buys", ("bundle_n", "bundle_share", "first5_share")),
            ("the dev's sales", ("dev_sold_frac", "dev_sold_share")))
# R3's candidates: (feature, the side that looks like a rug), each cut at the in-sample entries' 10 % and 20 % tail.
CANDIDATES = (("c_top10_share", "max"), ("top5_share", "max"), ("dev_hold_share", "max"), ("first5_share", "max"),
              ("creator_dump_rate", "max"), ("dev_sold_frac", "max"), ("pool_sol", "min"),
              ("age_at_complete_s", "min"), ("unique_buyers", "min"), ("c_ubuyers_300", "min"))
TAILS = (0.10, 0.20)
NAN = float("nan")


def books(cut: dict | None = None) -> tuple[list[tuple[P.Strategy, P.Limits]], dict]:
    """Every variant once per latency and limit, `<name>@<latency>@<limit>`, at STAKE_SOL, P_pool0's key. The R3
    books share one cut dict (empty, so no filter, until the pick fills it)."""
    lat = Y12.latencies()
    cut = {} if cut is None else cut
    out, costs = [], {}
    for a in LATENCIES:
        for k, lim in LIMITS.items():
            for x, name in VARIANTS:
                s = P.BY_NAME[name]
                flt = {"cut": cut} if x == "R3" else s.flt
                v = dataclasses.replace(s, name=f"{name}@{a}@{k}", p={**s.p, "base": KEY}, stake_sol=STAKE_SOL,
                                        flt=flt)
                out.append((v, lim))
                costs[v.name] = lat[a]
    return out, costs


# ---------------------------------------------------------------- what the books note

class Bundles(P.Pipeline):
    """No strategy: per coin the other wallets that bought in the slot of its first curve trade (the creation's slot
    when the dev buys at the creation) and their tokens. Study code."""

    def __init__(self, eng):
        super().__init__(eng, [], P.PaperExecutor(), name="y16bundles", record=False)
        self.first: dict[str, list] = {}                      # mint -> [slot, wallets, tokens]

    def on_trade(self, tok, t: float, buy: bool, user: str, tok_amt: int, venue: str) -> None:
        if venue != "curve" or not tok.last_slot:
            return
        b = self.first.get(tok.mint)
        if b is None:
            b = self.first[tok.mint] = [tok.last_slot, set(), 0]
        if buy and tok.last_slot == b[0] and user not in tok.devs and user not in b[1]:
            b[1].add(user)
            b[2] += tok_amt

    def features(self, mint: str) -> dict:
        b = self.first.get(mint)
        return {"bundle_n": NAN, "bundle_share": NAN} if b is None else {"bundle_n": float(len(b[1])),
                                                                          "bundle_share": b[2] / SUPPLY}


class RugPipe(XL.PeakPipe):
    """A book; with `note` (the X0 books) it notes the features at each signal and each position's largest fall of
    the pool's price on one trade while held. Noting reads, it never changes what the book does."""

    def __init__(self, *a, note: bool = False, bundles: Bundles | None = None, **kw):
        super().__init__(*a, **kw)
        self.note, self.bundles = note, bundles
        self.feat: dict[tuple, dict] = {}                     # (mint, signal ms) -> features
        self.last: dict[str, dict] = {}                       # mint -> the features of its last signal
        self.px: dict[int, float] = {}
        self.drop: dict[int, float] = {}

    def snapshot(self, tok, t: float) -> dict:
        eng = self.eng
        f = SF.decision_features(eng, tok, t) if getattr(eng, "sel", None) is not None else eng.features(tok, int(t))
        f["pool_sol"] = tok.pq / C.LAMPORTS if tok.pq else NAN
        f["dev_sold_share"] = sum(tok.sold.get(d, 0) for d in tok.devs) / SUPPLY
        f.update(self.bundles.features(tok.mint) if self.bundles is not None else {"bundle_n": NAN,
                                                                                    "bundle_share": NAN})
        for label in ("rug0t", "rug0"):
            m = eng.models.get("sel_" + label)
            ok = m is not None and m.booster is not None
            f["p_" + label] = float(m.predict(np.array([[float(f.get(c, NAN)) for c in m.features]],
                                                       dtype=float))[0]) if ok else NAN
            f["base_" + label] = float(m.base) if ok else NAN
        return {k: (float(v) if isinstance(v, (int, float, np.floating)) else NAN) for k, v in f.items()}

    def signal(self, s, tok, t: float) -> None:
        if self.note and tok.pq and tok.pb:
            f = self.snapshot(tok, t)
            self.feat[(tok.mint, int(t))] = self.last[tok.mint] = f
        super().signal(s, tok, t)

    def bought(self, pid: int, at: float, tokens: int, cost_l: int, fee_l: int) -> None:
        super().bought(pid, at, tokens, cost_l, fee_l)
        p = self.pos.get(pid)
        tok = self.eng.tokens.get(p["mint"]) if p is not None else None
        if self.note and p is not None and p["state"] == "open" and tok is not None and tok.pq and tok.pb:
            self.px[pid], self.drop[pid] = C.price(tok.pq, tok.pb), 0.0

    def on_trade(self, tok, t: float, buy: bool, user: str, tok_amt: int, venue: str) -> None:
        if self.px and venue == "pool" and tok.pq and tok.pb:
            now = C.price(tok.pq, tok.pb)
            for pid in self.by_mint.get(tok.mint, ()):
                prev = self.px.get(pid)
                if prev:
                    self.drop[pid] = max(self.drop[pid], 1 - now / prev)
                    self.px[pid] = now
        super().on_trade(tok, t, buy, user, tok_amt, venue)

    def _close(self, p: dict, at: float) -> None:
        self.px.pop(p["pid"], None)
        super()._close(p, at)


def entries(pipe: RugPipe, gaps) -> list[dict]:
    """exitlab.entries with, for a noting book, the features at the signal, the largest one-trade fall while held and
    `crash` (a loss beyond CRASH_RET or a fall of CRASH_DROP; a failed buy is no crash)."""
    out = XL.entries(pipe, gaps)
    if not pipe.note:
        return out
    pid = {(t["mint"], t["signal_ms"]): t["pid"] for t in pipe.closed}
    for x in out:
        x["features"] = pipe.feat.get((x["mint"], x["signal_ms"])) or {}
        d = None if x["failed"] else pipe.drop.get(pid.get((x["mint"], x["signal_ms"])))
        x["max_drop"] = d
        x["crash"] = (not x["failed"]) and (x["ret"] < CRASH_RET or (d is not None and d >= CRASH_DROP))
    return out


# ---------------------------------------------------------------- R3's pick

def fires(cut: dict, f: dict) -> bool:
    """pipeline.Pipeline.cut_ok's test on noted features: True when the rule skips the entry (NaN keeps it)."""
    for name, (how, x) in cut.items():
        v = f.get(name, NAN)
        if v != v:
            continue
        if (how == "max" and v > x) or (how == "min" and v < x):
            return True
    return False


def model_fires(label: str, k: float, f: dict) -> bool | None:
    """R1 and R2 on noted features: P(label) above k x its base rate; None without the model."""
    p, b = f.get("p_" + label, NAN), f.get("base_" + label, NAN)
    return None if p != p or b != b else p > k * b


RULE_OF = {"R1": ("rug0t", 1.0), "R2": ("rug0t", 0.5)}


def pick_cut(e: list[dict]) -> dict:
    """R3's rule from closed in-sample entries with features (failed buys count, as entries that lost their fee): for
    each candidate the in-sample value at the tail (10 % or 20 % of the entries with the feature known) on its rug
    side; the rule keeping the highest mean return per entry wins, a tie to the one keeping more entries."""
    rows = []
    for name, how in CANDIDATES:
        v = np.array([x["features"].get(name, NAN) for x in e], dtype=float)
        v = v[np.isfinite(v)]
        if not len(v):
            continue
        for tail in TAILS:
            thr = float(np.quantile(v, 1 - tail if how == "max" else tail))
            cut = {name: (how, thr)}
            kept = [x for x in e if not fires(cut, x["features"])]
            if kept:
                rows.append({"feature": name, "how": how, "tail": tail, "threshold": thr, "kept": len(kept),
                             "cut": len(e) - len(kept), "mean": float(np.mean([x["ret"] for x in kept])),
                             "crashes_cut": sum(1 for x in e if x.get("crash") and fires(cut, x["features"]))})
    rows.sort(key=lambda r: (-r["mean"], -r["kept"]))
    return {"n": len(e), "mean_all": float(np.mean([x["ret"] for x in e])) if e else None,
            "crashes": sum(1 for x in e if x.get("crash")), "candidates": rows,
            "rule": {rows[0]["feature"]: (rows[0]["how"], rows[0]["threshold"])} if rows else {}}


class Picker:
    """At the split: R3's rule from X0's closed in-sample entries of PICK_BOOK, into the R3 books' shared cut."""

    def __init__(self, pipe: RugPipe, cut: dict):
        self.pipe, self.cut, self.result = pipe, cut, None

    def pick(self, at: float, _=None) -> None:
        e = [x for x in entries(self.pipe, self.pipe.eng.gaps) if x["signal_ms"] < at and x["features"]]
        self.result = pick_cut(e) | {"at_ms": int(at)}
        self.cut.update(self.result["rule"])


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
    log(f"rug16: {len(days)} day(s) {days[0]} to {days[-1]}, record to {Y12._utc(t_hi)}, entries to "
        f"{Y12._utc(entry_until)}, warm-up {len(warm)} day(s)")
    t0 = time.time()
    cut: dict = {}
    strats, costs = books(cut)
    eng = sim.Engine([], book=warm_book(warm, root), decisions=False, rule_costs=costs, entry_until=entry_until,
                     wallets=W.warm(warm, root), snipers=EA.warm_snipers(warm, root), select=True, trend=True)
    dm = Y9.DayModels()
    dm.eng = eng
    eng.models = dm
    lab = eng.add_pipe(SF.LabelPipe(eng, Y9.scenarios()["B"]))
    bundles = eng.add_pipe(Bundles(eng))
    pipes = {}
    for s, lim in strats:
        pipes[s.name] = eng.add_pipe(RugPipe(eng, [s], P.PaperExecutor(), limits=lim, name=s.name,
                                             note=s.name.startswith("P_pool0_wait@"), bundles=bundles))
    picker = Picker(pipes[f"P_pool0_wait@{PICK_BOOK}"], cut)
    trained: dict[str, dict] = {}
    state = {"split": None}

    def next_day(day: str, n: int) -> None:
        nd = (datetime.strptime(day, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
        ms = SM.train(lab.table(), until_ms=SM.day_start(nd))
        dm.by_day[nd] = ms
        has = getattr(ms.get("sel_rug0t"), "booster", None) is not None
        trained[nd] = {"rows": ms["sel_rows"], "rug0t": has}
        if has and state["split"] is None:                    # the first day with the model: out of sample from it
            state["split"] = SM.day_start(nd)
            eng.push(state["split"], "pipe", (picker, "pick", None))
        log(f"rug16: {day} done ({n:,} events); models for {nd}: rug0t {'yes' if has else 'no'} "
            f"(rows {ms['sel_rows']})")
    sim.replay(days, eng, root, progress=next_day, until_ms=t_hi)
    for pipe in pipes.values():
        pipe.finish(eng.now)
    log(f"rug16: replay in {time.time() - t0:.0f} s, {len(lab.rows):,} label rows, out of sample from "
        f"{Y12._utc(state['split']) if state['split'] else 'n/a'}, R3's rule {cut or 'none'}")
    return {"days": days, "warm": warm, "span": (t_lo, t_hi), "until_ms": until_ms, "entry_until_ms": entry_until,
            "split_ms": state["split"], "trained": trained, "pick": picker.result, "cut": dict(cut),
            "entries": {n: entries(p, eng.gaps) for n, p in pipes.items()},
            "skips": {n: p.skips for n, p in pipes.items()},
            "last_features": {a: pipes[f"P_pool0_wait@{a}@L100"].last for a in LATENCIES},
            "open_at_end": {n: len(p.pos) for n, p in pipes.items() if p.pos},
            "counts": dict(eng.counts), "gaps": list(eng.gaps)}


# ---------------------------------------------------------------- numbers

def auc(pos: list[float], neg: list[float]) -> float | None:
    """P(a crash's value > another entry's), ties half; None without both."""
    if not pos or not neg:
        return None
    a, b = np.asarray(pos)[:, None], np.asarray(neg)[None, :]
    return float((a > b).mean() + 0.5 * (a == b).mean())


def separation(e: list[dict]) -> list[dict]:
    """Per feature on closed entries with features: the crashes' and the rest's median and the AUC of the feature
    for a crash (above 0.5: higher in crashes), with the number of entries where it is known."""
    closed = [x for x in e if not x["failed"] and x.get("features")]
    out = []
    for group, names in FEATURES:
        for name in names:
            c = [x["features"].get(name, NAN) for x in closed if x["crash"]]
            r = [x["features"].get(name, NAN) for x in closed if not x["crash"]]
            c, r = [v for v in c if v == v], [v for v in r if v == v]
            out.append({"group": group, "feature": name, "n_crash": len(c), "n_rest": len(r),
                        "median_crash": float(np.median(c)) if c else None,
                        "median_rest": float(np.median(r)) if r else None, "auc": auc(c, r)})
    return out


def rule_on(e: list[dict], x: str, cut: dict) -> dict:
    """What rule x would have left out of X0's own entries (path-free: the slots and the loss limit as X0 had them):
    entries kept, crashes avoided, winners lost, the mean of the kept and of the cut, the cut's P&L. An entry
    without features or model counts as kept."""
    def hit(y):
        f = y.get("features") or {}
        return bool(model_fires(*RULE_OF[x], f)) if x in RULE_OF else bool(cut) and fires(cut, f)
    cutx = [y for y in e if hit(y)]
    kept = [y for y in e if not hit(y)]
    m = lambda z: float(np.mean([y["ret"] for y in z])) if z else None             # noqa: E731
    return {"entries": len(e), "kept": len(kept), "cut": len(cutx), "crashes": sum(1 for y in e if y.get("crash")),
            "crashes_avoided": sum(1 for y in cutx if y.get("crash")), "winners": sum(1 for y in e if y["ret"] > WIN),
            "winners_lost": sum(1 for y in cutx if y["ret"] > WIN), "kept_mean": m(kept), "cut_mean": m(cutx),
            "cut_pnl_sol": float(sum(y["pnl_sol"] for y in cutx)),
            "no_model": sum(1 for y in e if x in RULE_OF and model_fires(*RULE_OF[x], y.get("features") or {}) is None)}


def judge(e: list[dict], base: list[dict], s: dict, b: dict) -> dict:
    """Y8's rule: the hour-paired band of the difference of the means above zero and the higher total P&L."""
    v = X8.paired(e, base)
    v["common"] = XL.versus(e, base)
    v["pnl_diff"] = s.get("pnl_sol", 0.0) - b.get("pnl_sol", 0.0)
    v["pnl_higher"] = s.get("pnl_sol", -math.inf) > b.get("pnl_sol", math.inf)
    lo = v["band"][0]
    v["better"] = bool(math.isfinite(lo) and lo > 0 and v["pnl_higher"])
    return v


def evaluate(res: dict) -> dict:
    """Per latency and limit, out of sample (gapped trades kept): every book's numbers and skips, each twin against
    X0 (judged), each rule on X0's own entries, the crashes and the features that separate them; the in-sample
    numbers (reported, not judged). A twin beats P_pool0_wait at a latency only if better under both limits."""
    split = res["split_ms"]
    table, is_table, vs, on_x0, sep = {}, {}, {}, {}, {}
    for a in LATENCIES:
        for k in LIMITS:
            c = f"{a}@{k}"
            table[c], is_table[c], vs[c], on_x0[c] = {}, {}, {}, {}
            ent = {}
            for x, name in VARIANTS:
                e = res["entries"][f"{name}@{c}"]
                oos = [y for y in e if split is not None and y["signal_ms"] >= split]
                ent[x] = oos
                table[c][x] = XL.stats(oos) | {"name": name, "hours": XL.hours(oos)}
                is_table[c][x] = XL.stats([y for y in e if split is None or y["signal_ms"] < split]) | {"name": name}
                sk = [w for t, w in res["skips"][f"{name}@{c}"] if split is not None and t >= split]
                table[c][x]["skipped"] = dict(sorted(Counter(sk).items()))
            table[c]["X0"]["crashes"] = sum(1 for y in ent["X0"] if y.get("crash"))
            for x, _ in VARIANTS[1:]:
                vs[c][x] = judge(ent[x], ent["X0"], table[c][x], table[c]["X0"])
                on_x0[c][x] = rule_on(ent["X0"], x, res["cut"])
            sep[c] = separation(ent["X0"])
    better = {a: {x: all(vs[f"{a}@{k}"][x]["better"] for k in LIMITS) for x, _ in VARIANTS[1:]} for a in LATENCIES}
    return {"table": table, "in_sample": is_table, "versus": vs, "on_x0": on_x0, "separation": sep, "better": better}


def live_check(res: dict, trades: list[dict], since_ms: int, base: str = "P_pool0_wait") -> list[dict]:
    """The live book's closed trades since since_ms: each crash (as CRASH_RET; the one-trade fall is not in the
    journal) with what each rule says on the features the replay's X0 noted at that coin's last signal (B, 1.0 SOL),
    or n/a where the replay never signalled the coin (after the cutoff, or not seen)."""
    feats = res["last_features"].get("B") or {}
    out = []
    for t in sorted(trades, key=lambda t: t.get("signal_ms") or 0):
        if t.get("rule") != base or (t.get("signal_ms") or 0) < since_ms or t.get("ret") is None:
            continue
        f = feats.get(t["mint"])
        row = {"symbol": t.get("symbol"), "signal_ms": t["signal_ms"], "ret": t["ret"], "exit_why": t.get("exit_why"),
               "crash": t["ret"] < CRASH_RET, "seen": f is not None}
        for x in RULE_OF:
            row[x] = None if f is None else model_fires(*RULE_OF[x], f)
        row["R3"] = None if f is None or not res["cut"] else fires(res["cut"], f)
        out.append(row)
    return out


# ---------------------------------------------------------------- report

pct = RL.pct
_band = Y12._band
_utc = Y12._utc
_f = Y9._f


def _yn(v) -> str:
    return "n/a" if v is None else ("skips" if v else "buys")


def _table(ev: dict, c: str) -> list[str]:
    md = ["| book | strategy | entries | hours | failed buys | mean | median | win | P&L SOL | band of mean | "
          "max DD SOL | rule skips | no model | daily loss limit |", "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for x, _ in VARIANTS:
        s = ev["table"][c][x]
        sk = s["skipped"]
        tail = (f"{sk.get('model', 0) + sk.get('rug rule', 0)} | {sk.get('no model', 0)} | "
                f"{sk.get('daily loss limit', 0) + sk.get('daily loss stop', 0)} |")
        if not s.get("n"):
            md.append(f"| {x} | {s['name']} | 0 | 0 |" + " |" * 7 + " " + tail)
            continue
        md.append(f"| {x} | {s['name']} | {s['n']} | {s['hours']} | {s['failed']} | {pct(s['mean'])} | "
                  f"{pct(s['median'])} | {s['win'] * 100:.0f} % | {s['pnl_sol']:+.3f} | {_band(s['band'])} | "
                  f"{s['max_dd_sol']:.3f} | " + tail)
    md += ["", "| twin | mean difference vs X0 | band (hours paired) | P&L difference SOL | total P&L higher | "
           "better than X0 | on X0's entries: kept | crashes avoided | winners lost | mean of the kept | mean of the "
           "cut | P&L of the cut SOL |", "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for x, _ in VARIANTS[1:]:
        v, r = ev["versus"][c][x], ev["on_x0"][c][x]
        md.append(f"| {x} | {pct(v['diff'])} | {_band(v['band'])} | {v['pnl_diff']:+.3f} | "
                  f"{'yes' if v['pnl_higher'] else 'no'} | {'yes' if v['better'] else 'no'} | {r['kept']} of "
                  f"{r['entries']} | {r['crashes_avoided']} of {r['crashes']} | {r['winners_lost']} of {r['winners']} | "
                  f"{pct(r['kept_mean'])} | {pct(r['cut_mean'])} | {r['cut_pnl_sol']:+.3f} |")
    md += ["", "Exits: " + "; ".join(
        f"{x} " + ", ".join(f"{w} {n}" for w, n in ev["table"][c][x].get("exits", {}).items()) for x, _ in VARIANTS)]
    return md


def report_md(res: dict, ev: dict, lat: dict, live: list[dict] | None = None) -> str:
    def ms(d):
        return f"{d['p50'] / 1000:.1f} s ({d['p10'] / 1000:.1f} to {d['p90'] / 1000:.1f})"
    split = res["split_ms"]
    md = ["# A rug filter for P_pool0_wait (Y16)", "",
          f"Record {res['days'][0]} to {_utc(res['span'][1])}, entries to {_utc(res['entry_until_ms'])}, out of sample "
          f"from {_utc(split) if split else 'n/a'}. Stake {STAKE_SOL} SOL, at most 4 open per book, "
          f"{lat['B']['tx_fee_sol']:.6f} SOL per transaction. Latency A (paper model) buy {ms(lat['A']['buy'])}, "
          f"sale {ms(lat['A']['sell'])}; B (measured live) buy {ms(lat['B']['buy'])}, sale {ms(lat['B']['sell'])}. "
          f"A crash: a loss beyond {CRASH_RET * -100:.0f} % or one pool trade taking {CRASH_DROP * 100:.0f} % off the "
          "price while held. Trades open across a gap kept.", ""]
    pk = res.get("pick") or {}
    md.append(f"R3's rule, picked at the split on X0's {pk.get('n', 0)} closed in-sample entries ({PICK_BOOK}, mean "
              f"{pct(pk.get('mean_all'))}, {pk.get('crashes', 0)} crashes): " + (", ".join(
                  f"skip when {n} {'>' if h == 'max' else '<'} {v:.4g}" for n, (h, v) in res["cut"].items())
                  or "none"))
    for a in LATENCIES:
        md.append(f"Better than X0 under both limits, {LATENCY_LABEL[a]}: " + ", ".join(
            f"{x} {'yes' if v else 'no'}" for x, v in ev["better"][a].items()))
    for a in LATENCIES:
        for k in LIMITS:
            md += ["", f"## Out of sample, {LATENCY_LABEL[a]} ({a}), {LIMIT_LABEL[k]}", ""] + _table(ev, f"{a}@{k}")
    for a in LATENCIES:
        c = f"{a}@L100"
        md += ["", f"## What separates the crashes, X0's out-of-sample entries at {a}, 1.0 SOL "
                   f"({ev['table'][c]['X0'].get('crashes', 0)} crashes)", "",
               "| group | feature | crashes known | rest known | median, crashes | median, rest | AUC for a crash |",
               "|---|---|---|---|---|---|---|"]
        for r in ev["separation"][c]:
            md.append(f"| {r['group']} | {r['feature']} | {r['n_crash']} | {r['n_rest']} | "
                      f"{_f(r['median_crash'], '{:.4g}')} | {_f(r['median_rest'], '{:.4g}')} | {_f(r['auc'])} |")
    md += ["", "LP status: the record has no LP event per coin; every pool is made by the migration through the "
               "pump.fun program, the same for every coin, so it cannot separate."]
    if pk.get("candidates"):
        md += ["", "## R3's candidates (in sample)", "", "| feature | skip side | tail | threshold | kept | cut | "
               "crashes cut | mean of the kept |", "|---|---|---|---|---|---|---|---|"]
        for r in pk["candidates"]:
            md.append(f"| {r['feature']} | {'high' if r['how'] == 'max' else 'low'} | {r['tail'] * 100:.0f} % | "
                      f"{r['threshold']:.4g} | {r['kept']} | {r['cut']} | {r['crashes_cut']} | {pct(r['mean'])} |")
    if live:
        md += ["", "## The live book's trades in the window (the replay's features, B, 1.0 SOL)", "",
               "| signal UTC | coin | return | exit | crash | R1 | R2 | R3 |", "|---|---|---|---|---|---|---|---|"]
        for r in live:
            md.append(f"| {datetime.fromtimestamp(r['signal_ms'] / 1000, timezone.utc):%H:%M:%S} | {r['symbol']} | "
                      f"{pct(r['ret'])} | {r['exit_why']} | {'yes' if r['crash'] else ''} | {_yn(r['R1'])} | "
                      f"{_yn(r['R2'])} | {_yn(r['R3'])} |")
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
    md += ["", "Models per day: " + "; ".join(f"{d} rug0t {'yes' if v['rug0t'] else 'no'} (rows {v['rows']})"
                                              for d, v in res["trained"].items())]
    if res.get("open_at_end"):
        md += ["", f"Open at the end of the record: {res['open_at_end']}"]
    return "\n".join(md) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--until-ms", type=int, default=UNTIL_MS)
    ap.add_argument("--out", default=None, help="directory for rug16.json and rug16.md (default: the reports)")
    ap.add_argument("--live-since-ms", type=int,
                    default=int(datetime(2026, 10, 23, 15, 0, tzinfo=timezone.utc).timestamp() * 1000))
    a = ap.parse_args(argv)
    from .. import report as rep
    out = Path(a.out) if a.out else rep.REPORTS / "pumpfun_rt"
    out.mkdir(parents=True, exist_ok=True)
    lat = {k: RL.describe(c) for k, c in Y12.latencies().items()}
    res = run(until_ms=a.until_ms)
    if res.get("empty"):
        print("rug16: nothing recorded")
        return 1
    ev = evaluate(res)
    try:
        trades = json.loads((rep.REPORTS / "pumpfun_rt" / "live_trades.json").read_text(encoding="utf-8"))["trades"]
    except (OSError, ValueError, KeyError):
        trades = []
    live = live_check(res, trades, a.live_since_ms)
    md = report_md(res, ev, lat, live)
    keep = {k: v for k, v in res.items() if k not in ("entries", "skips", "last_features")}
    (out / "rug16.json").write_text(json.dumps(keep | {"latency": lat, "eval": ev, "live": live}, indent=1,
                                               default=str), encoding="utf-8")
    (out / "rug16.md").write_text(md, encoding="utf-8")
    (out / "rug16_entries.json").write_text(json.dumps(res["entries"], default=str), encoding="utf-8")
    print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
