"""P2 (results/pumpfun_selection_gap_p2_prereg.md): the selection gap between the live pump.fun bot and its paper
twin. PAPER ONLY and read only on everything live: reads the live bot's orders, ledger, skips and seen migrations and
the paper ledger, failed buys and skips; changes nothing a live bot, its sizing, a wallet or the engine reads.

    python -m lab.pumpfun_rt.selection_p2 [--live DIR] [--paper DIR] [--out results/pumpfun_selection_gap_p2.md]

Every paper signal of the rules the live bot ran (first row of a rule and coin, tainted and restart rows left out)
while a live run of that rule was on gets its live outcome: traded, buy failed (by kind), paused, refused by the
wallet or the brake, ran away before the send, not seen by the live feed, other. Every live trade without a paper
twin gets the paper's reason. Paper minus live on all live signals (P_all - L_all, points a trade) splits exactly
into selection (P_all - P_m), same coins (P_m - L_m) and live's own trades (L_m - L_all); the selection part into one
term per reason. Percentile bootstrap bands. Five trials in R5's registry, counted only, registered before the first
number; realistic.daily writes the gate line (under GATE_PTS to pass) into the calibration report.
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from .. import metrics
from . import realistic as R

PREREG = "results/pumpfun_selection_gap_p2_prereg.md"
OUT = Path(__file__).resolve().parents[2] / "results" / "pumpfun_selection_gap_p2.md"
RULES = ("P_pool0", "P_pool0_wait", "P_cmig_model")   # what the live bot ran
MATCH_MS = R.MATCH_MS                     # live records of a coin this close to the paper signal are its outcome
GATE_PTS = 2.0                            # the ladder's gate for pump.fun: paper minus live under this passes
DRAWS, SEED = 2_000, 0

TRADED, FAILED, PAUSED, REFUSED, RAN, UNSEEN, OTHER = (
    "traded", "buy failed", "paused", "refused by the wallet or the brake", "ran away before the send",
    "not seen by the live feed", "other")
REASONS = (TRADED, FAILED, PAUSED, REFUSED, RAN, UNSEEN, OTHER)
REFUSALS = ("stake paused", "max open positions", "max exposure", "above the stake cap", "daily loss", "total budget",
            "refused")
NO_LOG = "no live log yet"


def trials() -> list[dict]:
    return [{"id": f"hand:p2:{k}", "family": "hand", "n": 1, "sharpe": None, "source": PREREG}
            for k in ("paper_minus_live", "selection", "same_coins", "reasons", "paper_minus_live_realistic")]


def _jsonl(p: Path) -> list[dict]:
    out = []
    try:
        with p.open(encoding="utf-8") as fh:
            for line in fh:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        pass
    return out


def read_live(d: Path) -> dict:
    """The live bot's records, read only."""
    return {"orders": _jsonl(d / "orders.jsonl"), "ledger": R.read_csv(d / "ledger.csv"),
            "skipped": _jsonl(d / "skipped.jsonl"), "seen": _jsonl(d / "seen.jsonl"),
            "journal": _jsonl(d / "journal.jsonl")}


def read_paper(d: Path) -> dict:
    return {"ledger": R.read_csv(d / "ledger.csv"), "failed": R.read_csv(d / "failed.csv"),
            "skipped": _jsonl(d / "skipped.jsonl"),
            "since": (R.read_json(d / "state.json") or {}).get("realistic_since")}


# ---------------------------------------------------------------- when the live bot was on

def runs(live: dict) -> tuple[list[dict], int]:
    """([{run, rule, start, end}], runs left out for want of a rule). A run is the records sharing a run id (those
    without one: one unnamed run), on from its id's start second (unnamed: its first record) to its last record;
    its rule the commonest of its ledger, skipped and seen rows."""
    ts: dict[str, list[float]] = collections.defaultdict(list)
    rules: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for name, keys in (("orders", ("t",)), ("ledger", ("signal_ms", "exit_ms")), ("skipped", ("t",)),
                       ("seen", ("t",)), ("journal", ("t",))):
        for r in live.get(name) or []:
            run = str(r.get("run") or "")
            ts[run] += [v for v in (R._f(r.get(k)) for k in keys) if v is not None]
            if name in ("ledger", "skipped", "seen") and r.get("rule"):
                rules[run][r["rule"]] += 1
    out, dropped = [], 0
    for run, xs in ts.items():
        if not xs:
            continue
        if not rules[run]:
            dropped += 1
            continue
        m = re.match(r"(\d+)-", run)
        start = int(m.group(1)) * 1000 if m else min(xs)
        out.append({"run": run, "rule": rules[run].most_common(1)[0][0], "start": min(start, min(xs)),
                    "end": max(xs)})
    return sorted(out, key=lambda r: r["start"]), dropped


def on(rs: list[dict], rule: str, t: float) -> bool:
    """A run of the rule on at t, from MATCH_MS before its start (the live engine signals a few seconds after the
    paper's; the unnamed run starts at its first live signal)."""
    return any(r["rule"] == rule and r["start"] - MATCH_MS <= t <= r["end"] for r in rs)


# ---------------------------------------------------------------- the paper signals and their live outcome

def paper_signals(paper: dict, rs: list[dict]) -> tuple[list[dict], dict[str, int]]:
    """The first row (ledger or failed buy) of each rule and coin signalled while a live run of the rule was on:
    [{rule, mint, t, ret (None for a failed buy), symbol}], and the rows left out (tainted by P1, closed by a
    restart)."""
    left = {"tainted": 0, "restart": 0}
    first: dict[tuple[str, str], dict] = {}
    for src, rows in (("ledger", paper.get("ledger") or []), ("failed", paper.get("failed") or [])):
        for r in rows:
            t = R._f(r.get("signal_ms"))
            if r.get("rule") not in RULES or t is None or not r.get("mint") or not on(rs, r["rule"], t):
                continue
            if src == "ledger" and R.tainted(r):
                left["tainted"] += 1
                continue
            if src == "ledger" and r.get("exit_why") == "restart":
                left["restart"] += 1
                continue
            k = (r["rule"], r["mint"])
            if k not in first or t < first[k]["t"]:
                first[k] = {"rule": r["rule"], "mint": r["mint"], "t": t, "symbol": r.get("symbol") or "",
                            "ret": R._f(r.get("ret")) if src == "ledger" else None}
    return sorted(first.values(), key=lambda s: s["t"]), left


def skip_reason(why: str) -> tuple[str, str]:
    """(reason, detail) of a live skip's why."""
    w = str(why or "")
    detail = re.sub(r"\s*\(.*$", "", w).strip() or "?"
    lw = w.lower()
    if lw.startswith("paused by the owner"):
        return PAUSED, "paused by the owner"
    if any(lw.startswith(k) for k in REFUSALS):
        return REFUSED, detail
    if lw.startswith(R.RAN_AWAY) and R.RAN_AWAY_LANDING not in lw:
        return RAN, R.RAN_AWAY
    if lw.startswith("creation not seen") or lw.startswith("no pool state"):
        return UNSEEN, w
    return OTHER, detail


def near(xs, t: float, key: str = "t") -> list[dict]:
    return [x for x in xs if (v := R._f(x.get(key))) is not None and abs(v - t) <= MATCH_MS]


def outcome(live: dict, signals: list[dict]) -> list[dict]:
    """Each signal with its live outcome (reason, detail) and, when traded, the live trade it matched (live_ret,
    live_key: the ledger row's index)."""
    by_mint: dict[str, list[dict]] = collections.defaultdict(list)
    for o in live.get("orders") or []:
        if o.get("side") == "buy" and o.get("mint"):
            by_mint[o["mint"]].append(o)
    skips: dict[tuple[str, str], list[dict]] = collections.defaultdict(list)
    for k in live.get("skipped") or []:
        skips[(k.get("rule"), k.get("mint"))].append(k)
    seen: dict[str, list[dict]] = collections.defaultdict(list)
    for k in live.get("seen") or []:
        seen[k.get("mint")].append(k)
    seen_from = min((R._f(k.get("t")) for k in live.get("seen") or [] if R._f(k.get("t")) is not None),
                    default=None)
    trades: dict[tuple[str, str], list[tuple[int, dict]]] = collections.defaultdict(list)
    for i, r in enumerate(live.get("ledger") or []):
        if r.get("mode") in ("test", "full"):
            trades[(r.get("rule"), r.get("mint"))].append((i, r))
    used: set[int] = set()
    out = []
    for s in signals:
        o = near(by_mint.get(s["mint"], []), s["t"])
        x = {**s, "live_ret": None, "live_key": None}
        cands = sorted((abs(R._f(r.get("signal_ms")) - s["t"]), i, r) for i, r in trades[(s["rule"], s["mint"])]
                       if R._f(r.get("signal_ms")) is not None and i not in used
                       and abs(R._f(r.get("signal_ms")) - s["t"]) <= MATCH_MS)
        if cands:                                            # a live trade of the coin (a retried buy filled late)
            _, i, r = cands[0]
            used.add(i)
            x.update(reason=TRADED, detail=TRADED, live_ret=R._f(r.get("ret")), live_key=i)
        elif any(v.get("what") == "filled" for v in o):
            x.update(reason=TRADED, detail="traded, not closed")
        elif any(v.get("what") == "sent" for v in o):
            fails = [v for v in o if v.get("what") == "failed"]
            kind = R.fail_kind(fails[-1].get("why") or fails[-1].get("err")) if fails else None
            x.update(reason=FAILED, detail=kind or "no result")
        elif k := near(skips.get((s["rule"], s["mint"]), []), s["t"]):
            x["reason"], x["detail"] = skip_reason(k[0].get("why"))
        elif seen_from is not None and s["t"] >= seen_from - MATCH_MS:
            if near(seen.get(s["mint"], []), s["t"]):
                x.update(reason=OTHER, detail="seen, no decision")
            else:
                x.update(reason=UNSEEN, detail="never seen by the live service")
        else:
            x.update(reason=OTHER, detail=NO_LOG)
        out.append(x)
    return out


def live_only(live: dict, paper: dict, sig: list[dict]) -> list[dict]:
    """The live closed trades no paper signal matched, each with the paper's reason. "no paper record" says
    whether the paper twin had not started yet (before its rule's first paper row) or the collector still had the
    coin (a paper row of another book or a paper skip)."""
    used = {x["live_key"] for x in sig if x.get("live_key") is not None and x["ret"] is not None}
    pskip: dict[tuple[str, str], list[dict]] = collections.defaultdict(list)
    for k in paper.get("skipped") or []:
        pskip[(k.get("rule"), k.get("mint"))].append(k)
    prow: dict[tuple[str, str], list[dict]] = collections.defaultdict(list)
    for src in ("ledger", "failed"):
        for r in paper.get(src) or []:
            prow[(r.get("rule"), r.get("mint"))].append({**r, "_src": src})
    born: dict[str, float] = {}
    for (rule, _), rows in prow.items():
        for p in rows:
            if (v := R._f(p.get("signal_ms"))) is not None and v < born.get(rule, float("inf")):
                born[rule] = v
    known = {m for _, m in prow} | {k.get("mint") for k in paper.get("skipped") or []}
    out = []
    for i, r in enumerate(live.get("ledger") or []):
        t = R._f(r.get("signal_ms"))
        if i in used or r.get("mode") not in ("test", "full") or r.get("rule") not in RULES or t is None:
            continue
        k = (r["rule"], r.get("mint"))
        nr = near(prow.get(k, []), t, "signal_ms")
        if ps := near(pskip.get(k, []), t):
            why = re.sub(r"\s*\(.*$", "", str(ps[0].get("why") or "?")).strip()
        elif nr and all(p["_src"] == "failed" for p in nr):
            why = "paper buy failed"
        elif nr and all(p["_src"] == "failed" or R.tainted(p) for p in nr):
            why = "paper row tainted (P1)"
        elif nr and all(p["_src"] == "failed" or R.tainted(p) or p.get("exit_why") == "restart" for p in nr):
            why = "paper closed by a restart"
        elif nr:
            why = "paper's first entry of the coin matched elsewhere"
        elif prow.get(k):
            why = "paper entered at another time"
        elif t < born.get(r["rule"], float("inf")):
            why = "no paper record (the paper twin not started yet)"
        elif r.get("mint") in known:
            why = "no paper record (the collector had the coin)"
        else:
            why = "no paper record"
        out.append({"rule": r["rule"], "mint": r.get("mint"), "t": t, "ret": R._f(r.get("ret")), "why": why})
    return out


# ---------------------------------------------------------------- the gap

def _mean(xs) -> float | None:
    xs = [x for x in xs if x is not None]
    return float(np.mean(xs)) if xs else None


def gap(sig: list[dict], live_trades: list[float], draws: int = DRAWS, seed: int = SEED) -> dict:
    """P_all, P_m, L_m, L_all, the gap and its three parts, the per-reason terms of the selection part, each with
    a 95 % percentile bootstrap band (paper signals and live trades drawn independently)."""
    ps = [x for x in sig if x["ret"] is not None]
    lv = np.array([v for v in live_trades if v is not None], dtype=float)
    n, m = len(ps), len(lv)
    p = np.array([x["ret"] for x in ps], dtype=float)
    pair = np.array([x["reason"] == TRADED and x["live_ret"] is not None for x in ps], dtype=bool)
    pl = np.array([x["live_ret"] if x["live_ret"] is not None else np.nan for x in ps], dtype=float)
    grp = np.array([REASONS.index(x["reason"]) for x in ps], dtype=int)

    def stat(idx, jdx) -> dict:
        pp, pr, pg, pll = p[idx], pair[idx], grp[idx], pl[idx]
        pa = pp.mean() if len(pp) else np.nan
        pm = pp[pr].mean() if pr.any() else np.nan
        lm = pll[pr].mean() if pr.any() else np.nan
        la = lv[jdx].mean() if len(jdx) else np.nan
        d = {"P_all": pa, "P_m": pm, "L_m": lm, "L_all": la, "gap": pa - la, "selection": pa - pm,
             "same_coins": pm - lm, "live_own": lm - la}
        for gi, g in enumerate(REASONS):
            w = (pg == gi) & ~pr
            d[f"term:{g}"] = w.sum() / len(pp) * (pp[w].mean() - pm) if len(pp) and w.any() else 0.0
        return d
    est = stat(np.arange(n), np.arange(m))
    out = {"n_paper": n, "n_live": m, "n_pairs": int(pair.sum())}
    if not n or not m:
        return out | {k: None for k in est} | {"band": {}}
    rng = np.random.default_rng(seed)
    bs = [stat(rng.integers(0, n, n), rng.integers(0, m, m)) for _ in range(draws)]
    band = {}
    for k in est:
        xs = np.array([b[k] for b in bs], dtype=float)
        xs = xs[np.isfinite(xs)]
        band[k] = (float(np.percentile(xs, 2.5)), float(np.percentile(xs, 97.5))) if len(xs) else None
    return out | {k: (float(v) if np.isfinite(v) else None) for k, v in est.items()} | {"band": band}


def compute(live: dict, paper: dict, since: float | None = None) -> dict:
    """The whole study over every live run (since None) or over the signals and live trades at or after since."""
    rs, dropped = runs(live)
    sig, left = paper_signals(paper, rs)
    sig = outcome(live, sig)
    lo = live_only(live, paper, sig)
    lt = [r for r in live.get("ledger") or [] if r.get("mode") in ("test", "full") and r.get("rule") in RULES
          and R._f(r.get("signal_ms")) is not None]
    if since is not None:
        sig = [x for x in sig if x["t"] >= since]
        lo = [x for x in lo if x["t"] >= since]
        lt = [r for r in lt if R._f(r["signal_ms"]) >= since]
    g = gap(sig, [R._f(r.get("ret")) for r in lt])
    return {"runs": rs, "runs_dropped": dropped, "left_out": left, "signals": sig, "live_only": lo, "gap": g,
            "since": since}


# ---------------------------------------------------------------- the report

def _pc(x) -> str:
    return "n/a" if x is None else f"{x * 100:+.1f} %"


def _pt(x) -> str:
    return "n/a" if x is None else f"{x * 100:+.1f}"


def _band(g: dict, k: str) -> str:
    b = (g.get("band") or {}).get(k)
    return "n/a" if not b else f"{b[0] * 100:+.1f} to {b[1] * 100:+.1f}"


def gate_word(g: dict) -> str:
    if g.get("gap") is None:
        return "not measured"
    return "passes" if g["gap"] * 100 < GATE_PTS else "fails"


def line(res: dict) -> str:
    """The calibration report's line: paper minus live on all live signals, the number the ladder's gate reads."""
    g = res["gap"]
    if g.get("gap") is None:
        return "paper minus live on all live signals (P2): not measured (no live trade or no paper signal)"
    return (f"paper minus live on all live signals (P2, every live run): {_pt(g['gap'])} points a trade (band "
            f"{_band(g, 'gap')}; paper {_pc(g['P_all'])} on {g['n_paper']} signals, live {_pc(g['L_all'])} on "
            f"{g['n_live']} trades; selection {_pt(g['selection'])}, same coins {_pt(g['same_coins'])}, live's own "
            f"trades {_pt(g['live_own'])}): {gate_word(g)} the ladder's gate for pump.fun (under {GATE_PTS:g} "
            "points), results/pumpfun_selection_gap_p2.md")


def gate(live_dir: Path, paper_dir: Path, paper_rows: list[dict] | None = None, register: bool = True) -> dict:
    """realistic.json's `selection`, the number the ladder's gate for pump.fun reads: {pts (P_all - L_all over every
    live run, points a trade), band, pass (pts under GATE_PTS), n_paper, n_live, line}. paper_rows: the paper
    ledger when the caller has it read already."""
    if register:
        metrics.register(trials())                            # before any number exists
    paper = {"ledger": R.read_csv(paper_dir / "ledger.csv") if paper_rows is None else paper_rows,
             "failed": R.read_csv(paper_dir / "failed.csv"), "skipped": _jsonl(paper_dir / "skipped.jsonl")}
    res = compute(read_live(live_dir), paper)
    g = res["gap"]
    b = (g.get("band") or {}).get("gap")
    return {"pts": None if g.get("gap") is None else g["gap"] * 100,
            "band": None if not b else [b[0] * 100, b[1] * 100], "gate_pts": GATE_PTS,
            "pass": None if g.get("gap") is None else g["gap"] * 100 < GATE_PTS,
            "n_paper": g["n_paper"], "n_live": g["n_live"], "line": line(res)}


def _day(ms) -> str:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M")


def gap_md(g: dict) -> list[str]:
    rows = [("paper, all its signals (P_all)", "P_all"), ("paper, the signals live traded (P_m)", "P_m"),
            ("live, the same trades (L_m)", "L_m"), ("live, all its trades (L_all)", "L_all"),
            ("**paper minus live on all live signals (P_all - L_all)**", "gap"),
            ("selection (P_all - P_m)", "selection"), ("same coins (P_m - L_m)", "same_coins"),
            ("live's own trades (L_m - L_all)", "live_own")]
    md = [f"{g['n_paper']} paper signals with a return, {g['n_live']} live trades, {g['n_pairs']} matched pairs.", "",
          "| what | % or points a trade | 95 % band |", "|---|---|---|"]
    md += [f"| {t} | {_pt(g.get(k))} | {_band(g, k)} |" for t, k in rows]
    md += ["", "The selection part by reason, (n_r / n) (mean_r - P_m), points a trade:", "",
           "| reason | points | 95 % band |", "|---|---|---|"]
    terms = sorted(((g.get(f"term:{r}") or 0.0, r) for r in REASONS), key=lambda x: -abs(x[0]))
    md += [f"| {r} | {_pt(v)} | {_band(g, f'term:{r}')} |" for v, r in terms if v]
    return md


def outcome_md(sig: list[dict]) -> list[str]:
    md = ["| rule | reason | signals | with a return | paper mean |", "|---|---|---|---|---|"]
    by: dict[tuple[str, str], list[dict]] = collections.defaultdict(list)
    for x in sig:
        by[(x["rule"], x["reason"])].append(x)
        by[("all", x["reason"])].append(x)
    for (rule, why), xs in sorted(by.items(), key=lambda kv: (kv[0][0] == "all", kv[0][0],
                                                              REASONS.index(kv[0][1]))):
        rets = [x["ret"] for x in xs if x["ret"] is not None]
        md.append(f"| {rule} | {why} | {len(xs)} | {len(rets)} | {_pc(_mean(rets))} |")
    det: dict[tuple[str, str], list[dict]] = collections.defaultdict(list)
    for x in sig:
        if x["reason"] != TRADED:
            det[(x["reason"], x["detail"])].append(x)
    md += ["", "By detail (every rule):", "", "| reason | detail | signals | paper mean |", "|---|---|---|---|"]
    for (why, d), xs in sorted(det.items(), key=lambda kv: (REASONS.index(kv[0][0]), -len(kv[1]))):
        md.append(f"| {why} | {d} | {len(xs)} | {_pc(_mean([x['ret'] for x in xs]))} |")
    return md


def markdown(res: dict, real: dict) -> str:
    g = res["gap"]
    md = ["# P2: the selection gap between the live pump.fun bot and its paper twin", "",
          f"Pre-registration `{PREREG}`. Read only: `<data>/live/pumpfun_rt` (orders, ledger, skipped, seen, "
          "journal) and `<data>/paper/pumpfun_rt` (ledger, failed, skipped, state). Returns per trade on each side's "
          f"own stake; a live record of the coin within {MATCH_MS // 60_000} minutes of the paper signal is its "
          f"outcome. Bands: 95 % percentile bootstrap, {DRAWS:,} draws, seed {SEED}. Five trials in R5's registry, "
          "counted only (`hand:p2:*`); no Sharpe, no DSR.", "",
          "Beyond the pre-registration, fixed after the first run and before reading any gap: a run counts from "
          f"{MATCH_MS // 60_000} minutes before its start (the unnamed first run starts at its first live signal, "
          "2 s after the paper's signal of the same coin); a live trade of the coin within the window is traded even "
          "when its buy filled later (a buy that did not land, retried); \"no paper record\" says whether the paper "
          "twin had not started yet or the collector had the coin.", "",
          "## The answer", "",
          f"- {line(res)}.",
          f"- Realistic paper only (signals and live trades from {_day(real['since'])} UTC): "
          f"{_pt(real['gap'].get('gap'))} points (band {_band(real['gap'], 'gap')}; paper "
          f"{_pc(real['gap'].get('P_all'))} on {real['gap']['n_paper']} signals, live {_pc(real['gap'].get('L_all'))} "
          f"on {real['gap']['n_live']} trades)." if real.get("since") else "- No realistic_since in the paper state.",
          "", "## The live runs", "",
          f"{len(res['runs'])} runs with a rule ({res['runs_dropped']} without one left out), "
          f"{sum(r['end'] - r['start'] for r in res['runs']) / 3_600_000:.1f} hours on.", "",
          "| from (UTC) | to | rule |", "|---|---|---|"]
    md += [f"| {_day(r['start'])} | {_day(r['end'])[11:]} | {r['rule']} |" for r in res["runs"]]
    md += ["", f"Paper rows left out: {res['left_out']['tainted']} tainted (P1), {res['left_out']['restart']} closed "
           "by a restart.", "",
           "## Every paper signal by its live outcome", "", *outcome_md(res["signals"]), "",
           "## The gap, every live run", "", *gap_md(g), ""]
    if real.get("since"):
        md += [f"## The gap, realistic paper only (from {_day(real['since'])} UTC)", "", *gap_md(real["gap"]), ""]
    lo = res["live_only"]
    c = collections.Counter((x["rule"], x["why"]) for x in lo)
    md += ["## Live trades without a paper twin", "",
           f"{len(lo)} of {g['n_live']} live trades; live mean on them {_pc(_mean([x['ret'] for x in lo]))}.", "",
           "| rule | why paper did not take it | trades | live mean |", "|---|---|---|---|"]
    md += [f"| {r} | {k} | {v} | {_pc(_mean([x['ret'] for x in lo if (x['rule'], x['why']) == (r, k)]))} |"
           for (r, k), v in sorted(c.items(), key=lambda kv: (kv[0][0], -kv[1]))]
    return "\n".join(md) + "\n"


def run(live_dir: Path, paper_dir: Path, out: Path, register: bool = True, log=print) -> dict:
    if register:
        metrics.register(trials())                            # before any number exists
    live, paper = read_live(live_dir), read_paper(paper_dir)
    res = compute(live, paper)
    real = compute(live, paper, since=R._f(paper.get("since"))) if paper.get("since") else {"since": None}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(markdown(res, real), encoding="utf-8")
    log(f"p2: {line(res)} -> {out}")
    return {"all": res, "realistic": real}


def main(argv: list[str] | None = None) -> int:
    from .live import paper_dir
    from .live_exec import data_dir
    ap = argparse.ArgumentParser(prog="lab.pumpfun_rt.selection_p2", description=__doc__.split("\n")[0])
    ap.add_argument("--live", default=None)
    ap.add_argument("--paper", default=None)
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args(sys.argv[1:] if argv is None else argv)
    run(Path(a.live) if a.live else data_dir(), Path(a.paper) if a.paper else paper_dir(), Path(a.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
