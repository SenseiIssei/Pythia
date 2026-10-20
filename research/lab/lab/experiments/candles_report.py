"""results/candles.md for the X15 study: everything below the marker is generated from the
part JSONs; the summary above the marker is written by hand and kept on every run."""

from __future__ import annotations

import math
from collections import Counter
from datetime import datetime, timezone

from .. import candles
from .candles_study import CRYPTO, HORIZONS, MARKER, NAME, RESULTS, SETS, SIGNALS


def _f(x, nd: int = 2) -> str:
    if x is None:
        return "n/a"
    if isinstance(x, bool):
        return "yes" if x else "no"
    if isinstance(x, int):
        return f"{x:,}"
    if isinstance(x, float):
        if not math.isfinite(x):
            return "n/a"
        return f"{x:,.{nd}f}" if abs(x) < 1e5 else f"{x:,.0f}"
    return str(x)


def table(rows: list[dict], cols: list[tuple[str, str]], nd: int = 2) -> str:
    head = "| " + " | ".join(h for _, h in cols) + " |\n|" + "---|" * len(cols) + "\n"
    return head + "".join("| " + " | ".join(_f(r.get(k), nd) for k, _ in cols) + " |\n" for r in rows)


def part_a_md(A: dict) -> list[str]:
    rows = A["rows"]
    out = ["## A. Event study\n\n"]
    cov = A["coverage"]
    out.append("Coverage (eligible instrument-bars):\n\n" + table(
        [{"set": k, **v, "nc_is": (v.get("no_candle_share") or {}).get("in_sample"),
          "nc_oos": (v.get("no_candle_share") or {}).get("out_of_sample")} for k, v in cov.items()],
        [("set", "set"), ("instruments", "instruments"), ("bars", "bars"), ("eligible_is", "eligible in sample"),
         ("eligible_oos", "eligible out of sample"), ("nc_is", "member days without a candle, in sample"),
         ("nc_oos", "same, out of sample")]) + "\n")
    dr = A["drift"]
    out.append("Drift (mean return of every eligible bar, entry next open, before costs, bps):\n\n" + table(
        [{"set": k, **{f"is{h}": dr[k]["is"][str(h)] * 1e4 if str(h) in dr[k]["is"] else dr[k]["is"][h] * 1e4
                       for h in HORIZONS},
          **{f"oos{h}": dr[k]["oos"][str(h)] * 1e4 if str(h) in dr[k]["oos"] else dr[k]["oos"][h] * 1e4
             for h in HORIZONS}} for k in dr],
        [("set", "set")] + [(f"is{h}", f"in sample {h}") for h in HORIZONS]
        + [(f"oos{h}", f"out of sample {h}") for h in HORIZONS], 1) + "\n")
    cands = [r for r in rows if r["candidate"]]
    holds = [r for r in cands if r.get("holds")]
    trade = [r for r in cands if r.get("tradeable")]
    by_set = Counter(r["set"] for r in cands)
    out.append(f"{A['n_cells']:,} cells (80 signals x 4 sets x 4 horizons). In-sample screen (at least "
               f"{100} events, t >= 3): **{len(cands)}** candidates ("
               + ", ".join(f"{k} {by_set.get(k, 0)}" for k in SETS)
               + f"). Out of sample (Holm over {A['holm_m']}, family 0.05, crypto twin agreeing): **{len(holds)}** "
               f"hold, **{len(trade)}** of them bullish and tradeable after costs.\n\n")
    # How many cells keep their sign.
    for k in SETS:
        sub = [r for r in rows if r["set"] == k and r["is_n"] >= 100 and r["oos_n"] >= 30
               and math.isfinite(r["is_t"]) and math.isfinite(r["oos_t"])]
        strong = [r for r in sub if abs(r["is_t"]) >= 2]
        keep = sum((r["is_t"] > 0) == (r["oos_t"] > 0) for r in strong)
        pos2 = sum(r["oos_t"] >= 2 for r in sub)
        out.append(f"- {k}: {len(sub)} cells with enough events; out of sample {pos2} have t >= 2 in the "
                   f"signal's direction (about {0.023 * len(sub):.0f} expected by chance); of the {len(strong)} "
                   f"with |t| >= 2 in sample, {keep} keep the sign.\n")
    out.append("\n")
    cols = [("set", "set"), ("signal", "signal"), ("h", "h"), ("dir", "dir"), ("is_n", "IS events"),
            ("is_ex_bps", "IS excess bps"), ("is_t", "IS t"), ("oos_n", "OOS events"),
            ("oos_ex_bps", "OOS excess bps"), ("oos_t", "OOS t"), ("oos_p", "OOS p"),
            ("twin_oos_ex_bps", "twin OOS excess bps"), ("oos_r_bps", "OOS mean bps"),
            ("oos_net_bps", "OOS net bps"), ("drift_oos_bps", "OOS drift bps"), ("holds", "holds"),
            ("tradeable", "tradeable")]
    if cands:
        out.append("### Every in-sample candidate\n\nExcess is over the same bar's random entry, signed by the "
                   "signal's direction (positive = the pattern did what it says). Net is the mean return minus the "
                   "round trip; drift is the mean of every eligible bar.\n\n")
        out.append(table(sorted(cands, key=lambda r: (r["set"], -r["is_t"])), cols, 1) + "\n")
    if A.get("permutation"):
        out.append("### Random entry on the same bars (2,000 draws)\n\n" + table(
            A["permutation"], [("set", "set"), ("signal", "signal"), ("h", "h"), ("n", "events"),
                               ("mean_bps", "mean bps"), ("random_mean_bps", "random mean bps"),
                               ("random_p05_bps", "random 5 %"), ("random_p95_bps", "random 95 %"), ("p", "p")], 1)
            + "\n")
    # Overview at h = 5.
    out.append("### Every signal at 5 bars\n\nIn-sample and out-of-sample t of the signed excess, and how often the "
               "signal fires (per 1,000 eligible bars). All four horizons are in the JSON.\n\n")
    freq = {(f["set"], f["signal"]): f["per_1000"] for f in A["freq"]}
    idx = {(r["set"], r["signal"], r["h"]): r for r in rows}
    ov = []
    for s in SIGNALS:
        o = {"signal": s, "dir": {1: "bull", -1: "bear", 0: "neutral"}[
            candles.PATTERNS[s].direction if s in candles.PATTERNS else (1 if s.startswith("bull") else -1)]}
        for k in SETS:
            r = idx.get((k, s, 5), {})
            o[f"{k}_f"] = freq.get((k, s))
            o[f"{k}_is"] = r.get("is_t")
            o[f"{k}_oos"] = r.get("oos_t")
        ov.append(o)
    cols = [("signal", "signal"), ("dir", "dir")]
    for k in SETS:
        cols += [(f"{k}_f", f"{k} per 1k"), (f"{k}_is", f"{k} IS t"), (f"{k}_oos", f"{k} OOS t")]
    out.append(table(ov, cols, 1) + "\n")
    return out


def part_b_md(B: dict) -> list[str]:
    out = ["## B. Long-only rules\n\n"]
    for k in SETS:
        ps = B["picks"].get(k, [])
        out.append(f"- {k} picks: " + (", ".join(f"{p['signal']} h{p['h']} (IS t {p['is_t']:.2f})" for p in ps)
                                       if ps else "none qualified") + "\n")
    out.append("\n")
    rows = []
    for r in B["rows"]:
        rows.append({**r, "years_txt": " ".join(f"{y}:{v:.2f}" for y, v in sorted(r["years"].items()))
                     if len(r["years"]) <= 3 else f"{r['years_pos']} of {r['years_n']}",
                     "failed": ", ".join(r["gates_failed"]) or "none"})
    cols = [("set", "set"), ("signal", "signal"), ("h", "h"), ("entries_oos", "OOS entries"), ("base_is", "IS Sharpe"),
            ("base_oos", "OOS Sharpe"), ("cagr", "CAGR"), ("dd", "max DD"), ("random_median", "random median"),
            ("random_p95", "random 95 %"), ("bench_oos", "benchmark"), ("late_oos", "late"),
            ("double cost_oos", "double cost"), ("twin_oos", "twin"), ("years_txt", "years"),
            ("deflated_p", "deflated p"), ("failed", "gates failed"), ("passes", "passes")]
    out.append(table(rows, cols) + "\n")
    out.append("Gates: 1 Sharpe > 0, 2 above the 95th percentile of 200 random books (same entries per bar, random "
               "eligible instruments), 3 above the benchmark (BTC or SPY bought and held, same days), 4 one bar "
               "late > 0, 5 double costs > 0, 6 twin > 0 (crypto), 7 positive years (2 of 3 crypto, 7 of 11 "
               "equities), 8 deflated p > 0.95 over the pool. Sharpe annualised over 365 days for crypto, 252 for "
               "equities.\n\n")
    if B.get("permutation"):
        out.append("Random entry on the same bars for the picks (2,000 draws):\n\n" + table(
            B["permutation"], [("set", "set"), ("signal", "signal"), ("h", "h"), ("window", "window"),
                               ("n", "events"), ("mean_bps", "mean bps"), ("random_mean_bps", "random mean bps"),
                               ("random_p95_bps", "random 95 %"), ("p", "p")], 1) + "\n")
    return out


def part_c_md(C: dict) -> list[str]:
    out = ["## C. Candle features in M2\n\n"]
    out.append(f"Group C ({', '.join(C['features'])}) joined to X11's M2 panel ({C['rows']:,} coin-days, "
               f"{C['coverage'] * 100:.1f} % with a candle). v2 + C against v2, mean daily rank IC on the 7-day "
               "label from 2024-01-01:\n\n")
    rows = []
    for k, v in C["tests"].items():
        rows.append({"test": k, **v, "by_year": " ".join(f"{y}:{d * 1e3:+.1f}" for y, d in sorted(v.get("by_year",
                                                                                                       {}).items()))})
    out.append(table(rows, [("test", "test"), ("days", "days"), ("ic", "IC v2 + C"), ("ic_base", "IC v2"),
                            ("diff", "difference"), ("t", "NW t"), ("by_year", "difference by year (x1000)"),
                            ("years_better", "years better"), ("passes", "passes")], 4) + "\n")
    out.append("Each input alone (within-day rank against the 7-day return):\n\n" + table(
        [{"feature": k, **v} for k, v in C["alone"].items()],
        [("feature", "feature"), ("ic_is", "IC before 2024"), ("ic_oos", "IC from 2024"), ("t_oos", "NW t")], 4)
        + "\n")
    if C.get("importance"):
        out.append("Gain share in one fit on all labelled days (top 12): " + ", ".join(
            f"{r['feature']} {r['gain_pct']:.1f} %" for r in C["importance"][:12]) + ".\n\n")
    return out


def part_d_md(D: dict) -> list[str]:
    out = ["## D. Candle filters on breakout_top10's entries\n\n"]
    rows = D["refs"] + D["rows"]
    out.append(table(rows, [("variant", "variant"), ("is_taker 35bps", "IS 35 bps"), ("oos_taker 35bps", "OOS 35 bps"),
                            ("oos_stress 70bps", "OOS 70 bps"), ("dd_35", "max DD"), ("cagr_35", "CAGR"),
                            ("turnover_yr", "turnover / yr"), ("y2024", "2024"), ("y2025", "2025"),
                            ("y2026", "2026"), ("deflated_p_diff", "deflated p of the difference")]) + "\n")
    out.append(f"Pick (best in-sample Sharpe): **{D['pick']}**. Bootstrap 90 % band of the Sharpe difference "
               f"against the book: {D['diff_p05']:.2f} to {D['diff_p95']:.2f}; better in {D['years_better']} of 3 "
               f"years. Gates failed: {', '.join(D['gates_failed']) or 'none'}. "
               f"**{'Passes' if D['passes'] else 'Fails'}.**\n\n")
    return out


def write(A: dict | None, B: dict | None, C: dict | None, D: dict | None, panel_end: str = "") -> None:
    path = RESULTS / f"{NAME}.md"
    head = path.read_text(encoding="utf-8").split(MARKER)[0] if path.exists() else (
        "# X15 candlestick patterns\n\nPre-registration: `candles_prereg.md`.\n\n")
    md = [head, MARKER, "\n\n", f"Generated {datetime.now(timezone.utc):%Y-%m-%d} by "
          f"`python -m lab.experiments.candles_study`; crypto panel to {panel_end}.\n\n"]
    if A:
        md += part_a_md(A)
    if B:
        md += part_b_md(B)
    if C:
        md += part_c_md(C)
    if D:
        md += part_d_md(D)
    if B:
        p = B["pool"]
        n_here = len(B["trials"]) + (len(D["rows"]) if D else 0)
        md.append(f"## The pool\n\n{p['hand_trials']} hand trials before this study, {p['factory_trials']} in the "
                  f"factory ledger, {len(B['trials'])} in part B and {len(D['rows']) if D else 0} in part D: "
                  f"**{p['hand_trials'] + p['factory_trials'] + n_here:,}**. Part B is deflated over its pool of "
                  f"{p['n_total']:,} (noise bar {p['sr0_annual']:.2f}); part D's improvement over its own 5 trials as "
                  f"registered. The next study starts from {p['hand_trials'] + n_here} hand trials.\n\n"
                  "Trials counted in part B: " + "; ".join(B["trials"]) + ".\n")
    RESULTS.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(md), encoding="utf-8")
