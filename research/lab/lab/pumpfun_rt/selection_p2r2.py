"""P2R2 (results/pumpfun_selection_gap_p2r2_prereg.md): P2's paper minus live gap on the realistic era only. PAPER
ONLY and read only on everything live: changes nothing a live bot, its sizing, a wallet or the engine reads.

    python -m lab.pumpfun_rt.selection_p2r2 [--live DIR] [--paper DIR] [--out results/pumpfun_selection_gap_p2r2.md]

P2's method and decomposition (selection_p2.compute) on the live trades and paper signals at or after P1's cut
(CUT_MS), the paper ledger's rows on a stale pool state left out and counted (realistic.stale, the pool state fix).
The band is R7's: each paper signal's and live trade's influence on a number summed by the UTC day of its signal, the
standard error clustered by day (G / (G - 1)), Student's t on G - 1. Under MIN_TRADES live trades or MIN_DAYS days with
a live trade: too few to judge. From the band the live trades still needed for a width under WIDTH_PTS. Five trials
in R5's registry, counted only, registered before the first number; realistic.daily writes the line under P2's, the
ladder shows it next to P2's, and P3's gate keeps reading P2's (a switch is the owner's decision).
"""

from __future__ import annotations

import argparse
import collections
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from .. import metrics
from . import realistic as R
from . import selection_p2 as S

PREREG = "results/pumpfun_selection_gap_p2r2_prereg.md"
OUT = Path(__file__).resolve().parents[2] / "results" / "pumpfun_selection_gap_p2r2.md"
CUT_MS = R.FIX_MS                         # P1's cut: live trades and paper signals from here
MIN_TRADES, MIN_DAYS = 30, 5              # under either: too few to judge
WIDTH_PTS = 2.0                           # the band's width the trades still needed aim at
KEYS = ("P_all", "P_m", "L_m", "L_all", "gap", "selection", "same_coins", "live_own")


def trials() -> list[dict]:
    return [{"id": f"hand:p2r2:{k}", "family": "hand", "n": 1, "sharpe": None, "source": PREREG}
            for k in ("paper_minus_live", "selection", "same_coins", "reasons", "stale_kept")]


def _day(ms) -> str:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%d")


# ---------------------------------------------------------------- R7's band, by linearization

def influence(sig: list[dict], live: list[tuple[float, float | None]]) -> dict:
    """{number: (estimate, per-day sum of each signal's and trade's influence on it)} and the days. A number is a
    smooth function of means, its influence per paper signal or live trade the linearization over the sample's size;
    a matched pair's live return goes with its paper signal."""
    ps = [x for x in sig if x["ret"] is not None]
    lt = [(t, r) for t, r in live if r is not None]
    n, m = len(ps), len(lt)
    days = sorted({_day(x["t"]) for x in ps} | {_day(t) for t, _ in lt})
    idx = {d: i for i, d in enumerate(days)}
    if not n or not m:
        return {"days": days, "est": {}, "by_day": {}}
    p = np.array([x["ret"] for x in ps], dtype=float)
    pair = np.array([x["reason"] == S.TRADED and x["live_ret"] is not None for x in ps], dtype=bool)
    pl = np.array([x["live_ret"] if x["live_ret"] is not None else 0.0 for x in ps], dtype=float)
    lv = np.array([r for _, r in lt], dtype=float)
    dp = np.array([idx[_day(x["t"])] for x in ps], dtype=int)
    dl = np.array([idx[_day(t)] for t, _ in lt], dtype=int)
    k = int(pair.sum())
    zp, zl = np.zeros(n), np.zeros(m)
    pa, la = p.mean(), lv.mean()
    f = {"P_all": (pa, (p - pa) / n, zl), "L_all": (la, zp, (lv - la) / m)}
    if k:
        pm, lm = p[pair].mean(), pl[pair].mean()
        f["P_m"] = (pm, np.where(pair, p - pm, 0.0) / k, zl)
        f["L_m"] = (lm, np.where(pair, pl - lm, 0.0) / k, zl)
        for g in S.REASONS:                                   # (n_r / n) (mean_r - P_m) = mean of w (p - P_m)
            w = np.array([x["reason"] == g for x in ps], dtype=bool) & ~pair
            if w.any():
                t = float(np.where(w, p - pm, 0.0).sum() / n)
                f[f"term:{g}"] = (t, (np.where(w, p - pm, 0.0) - t) / n - w.sum() / n * f["P_m"][1], zl)

    def lin(a, b, s=-1.0):
        return a[0] + s * b[0], a[1] + s * b[1], a[2] + s * b[2]
    f["gap"] = lin(f["P_all"], f["L_all"])
    if k:
        f["selection"], f["same_coins"], f["live_own"] = (lin(f["P_all"], f["P_m"]), lin(f["P_m"], f["L_m"]),
                                                          lin(f["L_m"], f["L_all"]))
    nd = len(days)
    by = {key: np.bincount(dp, weights=a, minlength=nd) + np.bincount(dl, weights=b, minlength=nd)
          for key, (_, a, b) in f.items()}
    return {"days": days, "est": {key: float(v[0]) for key, v in f.items()}, "by_day": by}


def r7(inf: dict) -> dict:
    """{number: {est, se, lo, hi}}: the clustered standard error (G / (G - 1)) and the t band; under two days no
    band (se, lo, hi None)."""
    from scipy import stats
    g = len(inf["days"])
    out = {}
    for key, est in inf["est"].items():
        if g < 2:
            out[key] = {"est": est, "se": None, "lo": None, "hi": None}
            continue
        se = math.sqrt(g / (g - 1) * float((inf["by_day"][key] ** 2).sum()))
        w = float(stats.t.ppf(0.975, g - 1)) * se
        out[key] = {"est": est, "se": se, "lo": est - w, "hi": est + w}
    return out


def width(se: float, n: int, g: int, big_n: float) -> float:
    """The R7 band's width (fraction of the stake) at big_n live trades, the days growing at n / g a day."""
    from scipy import stats
    gn = max(2, math.ceil(big_n * g / n))
    return 2 * float(stats.t.ppf(0.975, gn - 1)) * se * math.sqrt(n / big_n)


def needed(se: float | None, n: int, g: int, pts: float = WIDTH_PTS) -> dict | None:
    """The smallest number of live trades whose R7 band would be narrower than pts points (the width falls with
    more trades and more days, so a bisection), the trades more than now and the days of running at n / g a day."""
    if se is None or not n or g < 2:
        return None
    lim = pts / 100
    if width(se, n, g, n) < lim:
        return {"trades": n, "more": 0, "days": 0.0, "per_day": n / g}
    lo, hi = n, n
    while width(se, n, g, hi) >= lim:
        lo, hi = hi, hi * 2
    while hi - lo > 1:
        mid = (lo + hi) // 2
        lo, hi = (lo, mid) if width(se, n, g, mid) < lim else (mid, hi)
    return {"trades": hi, "more": hi - n, "days": (hi - n) / (n / g), "per_day": n / g}


# ---------------------------------------------------------------- the study

def compute(live: dict, paper: dict) -> dict:
    """P2 from the cut with the stale rows out (res), R7's band (band), the live trades and their days, the trades
    still needed, and the sensitivity with the stale rows kept (kept)."""
    res = S.compute(live, paper, since=CUT_MS, skip_stale=True)
    inf = influence(res["signals"], res["live"])
    band = r7(inf)
    lt = [t for t, r in res["live"] if r is not None]
    live_days = collections.Counter(_day(t) for t in lt)
    n, g = len(lt), len(inf["days"])
    need = needed((band.get("gap") or {}).get("se"), n, g)
    kept = S.compute(live, paper, since=CUT_MS)
    return {"res": res, "band": band, "days": inf["days"], "live_days": dict(sorted(live_days.items())),
            "n_live": n, "judged": n >= MIN_TRADES and len(live_days) >= MIN_DAYS, "needed": need,
            "kept": kept["gap"]}


def _pt(x) -> str:
    return "n/a" if x is None else f"{x * 100:+.1f}"


def _r7(b: dict, k: str) -> str:
    x = b.get(k) or {}
    return "n/a" if x.get("lo") is None else f"{x['lo'] * 100:+.1f} to {x['hi'] * 100:+.1f}"


def verdict(r: dict) -> str:
    g = r["res"]["gap"].get("gap")
    if g is None:
        return "not measured"
    if not r["judged"]:
        return f"too few to judge (under {MIN_TRADES} live trades or {MIN_DAYS} days)"
    return f"{'under' if g * 100 < S.GATE_PTS else 'not under'} {S.GATE_PTS:g} points"


def need_text(r: dict) -> str:
    x = r["needed"]
    if x is None:
        return "trades needed for a band under 2 points: n/a (no band)"
    return (f"a band under {WIDTH_PTS:g} points needs about {x['trades']:,} live trades ({x['more']:,} more, "
            f"{x['days']:,.0f} days of running at {x['per_day']:.1f} a day; at today's rate, the bot off, never)")


def line(r: dict) -> str:
    """The calibration report's line under P2's; P3's gate does not read it."""
    g = r["res"]["gap"]
    if g.get("gap") is None:
        return ("paper minus live on the realistic era only (P2R2): not measured (no live trade or no paper signal "
                f"from {R.FIX_DAY})")
    return (f"paper minus live on the realistic era only (P2R2, live trades from {R.FIX_DAY}, stale pool state rows "
            f"out): {_pt(g['gap'])} points a trade (R7 band {_r7(r['band'], 'gap')}; {r['n_live']} live trades on "
            f"{len(r['live_days'])} days, {g['n_paper']} paper signals, {g['n_pairs']} pairs; selection "
            f"{_pt(g.get('selection'))}, same coins {_pt(g.get('same_coins'))}, live's own trades "
            f"{_pt(g.get('live_own'))}): {verdict(r)}; {need_text(r)}; P3's gate reads P2's line, a switch is the "
            "owner's decision, results/pumpfun_selection_gap_p2r2.md")


def gate(live_dir: Path, paper_dir: Path, paper_rows: list[dict] | None = None, register: bool = True) -> dict:
    """realistic.json's `selection_r2`: {pts, band (R7), n_live, days_live, n_paper, judged, more, line}."""
    if register:
        metrics.register(trials())                            # before any number exists
    paper = {"ledger": R.read_csv(paper_dir / "ledger.csv") if paper_rows is None else paper_rows,
             "failed": R.read_csv(paper_dir / "failed.csv"), "skipped": S._jsonl(paper_dir / "skipped.jsonl")}
    r = compute(S.read_live(live_dir), paper)
    g, b = r["res"]["gap"], r["band"].get("gap") or {}
    return {"pts": None if g.get("gap") is None else g["gap"] * 100,
            "band": None if b.get("lo") is None else [b["lo"] * 100, b["hi"] * 100], "n_live": r["n_live"],
            "days_live": len(r["live_days"]), "n_paper": g["n_paper"], "judged": r["judged"],
            "more": (r["needed"] or {}).get("more"), "line": line(r)}


def markdown(r: dict, p2: str) -> str:
    res, g, b = r["res"], r["res"]["gap"], r["band"]
    kept = r["kept"]
    rows = [("paper, all its signals (P_all)", "P_all"), ("paper, the signals live traded (P_m)", "P_m"),
            ("live, the same trades (L_m)", "L_m"), ("live, all its trades (L_all)", "L_all"),
            ("**paper minus live on all live signals (P_all - L_all)**", "gap"),
            ("selection (P_all - P_m)", "selection"), ("same coins (P_m - L_m)", "same_coins"),
            ("live's own trades (L_m - L_all)", "live_own")]
    md = ["# P2R2: P2's paper minus live gap on the realistic era only", "",
          f"Pre-registration `{PREREG}`. P2's method and decomposition (`selection_p2.compute`, unchanged) on the "
          f"live trades and paper signals from {R.FIX_DAY} (P1's cut), all on the realistic paper model; the paper "
          "ledger's rows on a stale pool state left out and counted (`realistic.stale`, the pool state fix). Points a "
          "trade, each side on its own stake. R7's band: the standard error clustered by UTC day, t on G - 1 "
          f"degrees of freedom; P2's percentile band ({S.DRAWS:,} draws, seed {S.SEED}) next to it. Too few to judge "
          f"under {MIN_TRADES} live trades or {MIN_DAYS} days with a live trade. Five trials in R5's registry, "
          "counted only (`hand:p2r2:*`); no Sharpe, no DSR.", "",
          "## The answer", "",
          f"- {line(r)}.",
          f"- Next to it, P2's line as `realistic.md` reads it today: {p2}.",
          f"- With the stale rows kept (the paper before the fix): {_pt(kept.get('gap'))} points (P2's band "
          f"{S._band(kept, 'gap')}; {kept['n_paper']} paper signals, the sample's {res['left_out']['stale']} stale "
          "rows back in).",
          "", "## What it rests on", "",
          f"{r['n_live']} live closed trades on {len(r['live_days'])} UTC days, {g['n_paper']} paper signals with a "
          f"return, {g['n_pairs']} matched pairs; the band's G: {len(r['days'])} days with a signal or a trade "
          f"({', '.join(r['days']) or 'none'}). Paper rows left out: {res['left_out']['tainted']} tainted (P1), "
          f"{res['left_out']['restart']} closed by a restart, {res['left_out']['stale']} on a stale pool state.", "",
          "| UTC day | live trades |", "|---|---|"]
    md += [f"| {d} | {v} |" for d, v in r["live_days"].items()]
    md += ["", "## The gap and its parts", "",
           "| what | % or points a trade | R7 band (by day) | P2's band (percentile) |", "|---|---|---|---|"]
    md += [f"| {t} | {_pt(g.get(k))} | {_r7(b, k)} | {S._band(g, k)} |" for t, k in rows]
    md += ["", "The selection part by reason, (n_r / n) (mean_r - P_m), points a trade:", "",
           "| reason | points | R7 band | P2's band |", "|---|---|---|---|"]
    terms = sorted(((g.get(f"term:{x}") or 0.0, x) for x in S.REASONS), key=lambda x: -abs(x[0]))
    md += [f"| {x} | {_pt(v)} | {_r7(b, f'term:{x}')} | {S._band(g, f'term:{x}')} |" for v, x in terms if v]
    x = r["needed"]
    se = (b.get("gap") or {}).get("se")
    md += ["", "## The trades still needed", "",
           "With n live trades on G days and the gap's clustered standard error se, the smallest N with 2 t(0.975, "
           "G_N - 1) se sqrt(n / N) under 2 points, G_N = ceil(N G / n).", ""]
    md += ["No band, no number." if x is None else
           f"n {r['n_live']}, G {len(r['days'])}, se {se * 100:.1f} points: N = {x['trades']:,}, {x['more']:,} live "
           f"trades more, {x['days']:,.0f} days of running at {x['per_day']:.1f} trades a day. At today's rate (the "
           "bot off, no trade since its last) never."]
    md += ["", "## Every paper signal by its live outcome", "", *S.outcome_md(res["signals"]), ""]
    lo = res["live_only"]
    c = collections.Counter((y["rule"], y["why"]) for y in lo)
    md += ["## Live trades without a paper twin", "",
           f"{len(lo)} of {g['n_live']} live trades; live mean on them {S._pc(S._mean([y['ret'] for y in lo]))}.", "",
           "| rule | why paper did not take it | trades | live mean |", "|---|---|---|---|"]
    md += [f"| {a} | {k} | {v} | {S._pc(S._mean([y['ret'] for y in lo if (y['rule'], y['why']) == (a, k)]))} |"
           for (a, k), v in sorted(c.items(), key=lambda kv: (kv[0][0], -kv[1]))]
    return "\n".join(md) + "\n"


def run(live_dir: Path, paper_dir: Path, out: Path, register: bool = True, log=print) -> dict:
    if register:
        metrics.register(trials())                            # before any number exists
    live = S.read_live(live_dir)
    paper = S.read_paper(paper_dir)
    r = compute(live, paper)
    p2 = S.line(S.compute(live, paper))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(markdown(r, p2), encoding="utf-8")
    log(f"p2r2: {line(r)} -> {out}")
    return r


def main(argv: list[str] | None = None) -> int:
    from .live import paper_dir
    from .live_exec import data_dir
    ap = argparse.ArgumentParser(prog="lab.pumpfun_rt.selection_p2r2", description=__doc__.split("\n")[0])
    ap.add_argument("--live", default=None)
    ap.add_argument("--paper", default=None)
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args(sys.argv[1:] if argv is None else argv)
    run(Path(a.live) if a.live else data_dir(), Path(a.paper) if a.paper else paper_dir(), Path(a.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
