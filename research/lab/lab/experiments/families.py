"""The strategy-family sweep: run every fam_*.py, count every variant, judge the picks.

    python -m lab.experiments.families            # everything, reusing cached runs
    python -m lab.experiments.families --fresh     # recompute every family
    python -m lab.experiments.fam_reversal         # one family (its own table only)

Protocol, the same for every family:
  1. Every variant is simulated on the same survivorship-free daily panel
     (fam_common.py) with the same simulator and cost convention.
  2. In each sub-family the variant with the best IN-SAMPLE Sharpe at 15 bps
     (2020-08 to 2023) is picked before anything out of sample is looked at.
  3. The pick is judged out of sample (2024-01-01 on) at 15 and 41 bps.
  4. Its deflated Sharpe counts EVERY variant of EVERY family (the ensemble
     included), with the variance of all their out-of-sample Sharpes and the
     pick's own skew and kurtosis.
  5. Pass = deflated p > 0.95 AND Sharpe > 0 at 41 bps AND out-of-sample
     drawdown at 41 bps below the benchmark's (BTC for BTC/ETH-only books,
     the equal-weight universe otherwise; both are shown).
"""

from __future__ import annotations

import importlib
import sys

import numpy as np

from . import fam_common as fc

FAMILIES = ["reversal", "volmom", "breakout", "pairs", "season", "funding", "lowvol", "blend"]
COLS = ["variant", "is_sharpe_15bps", "oos_sharpe_15bps", "oos_sharpe_41bps", "oos_cagr_15bps", "oos_cagr_41bps",
        "oos_max_dd_15bps", "oos_max_dd_41bps", "turnover_yr", "avg_long", "avg_short",
        "oos_sharpe_btc_above", "oos_sharpe_btc_below"]


def compute(family: str, P: fc.Panel, fresh: bool) -> list[fc.Result]:
    if not fresh:
        cached = fc.load_family(family)
        if cached is not None:
            return cached
    mod = importlib.import_module(f"lab.experiments.fam_{family}")
    print(f"running {family} ...", flush=True)
    res = mod.variants(P)
    fc.save_family(family, res)
    return res


def run_one(family: str) -> None:
    P = fc.load_panel()
    res = compute(family, P, fresh=True)
    rows = [fc.measure(P, r) for r in res]
    fc.deflate(rows)
    print(fc.table(sorted(rows, key=lambda r: (r["sub"], -r["is_sharpe_15bps"])), ["sub"] + COLS + ["deflated_p"]))


def bench_rows(P: fc.Panel) -> dict:
    b = fc.benchmarks(P)
    ins, oos = fc.masks(P)
    out = {}
    for k, label in (("btc", "BTC buy and hold"), ("ew", "equal-weight universe")):
        pi, po = fc.perf(b[k][ins]), fc.perf(b[k][oos])
        on_prev = np.r_[False, P.btc_on[:-1]]
        out[k] = {"variant": label, "is_sharpe_15bps": pi["sharpe"], "oos_sharpe_15bps": po["sharpe"],
                  "oos_sharpe_41bps": po["sharpe"], "oos_cagr_15bps": po["cagr"], "oos_cagr_41bps": po["cagr"],
                  "oos_max_dd_15bps": po["max_dd"], "oos_max_dd_41bps": po["max_dd"], "turnover_yr": 0.0,
                  "avg_long": 1.0, "avg_short": 0.0,
                  "oos_sharpe_btc_above": fc.perf(b[k][oos & on_prev])["sharpe"],
                  "oos_sharpe_btc_below": fc.perf(b[k][oos & ~on_prev])["sharpe"]}
    return out


def reference_rows(P: fc.Panel, all_rows: list[dict]) -> list[dict]:
    """The existing paper candidate (tsmom.py rule on today's 20 survivors), through the same
    simulator and the same deflation bar. Not counted as a trial of this sweep: it was
    chosen in the earlier rounds (50 variants)."""
    from ..data import UNIVERSE
    from .tsmom import target_weights
    cols = [P.col(f"{b}USDT") for b in UNIVERSE]
    close, sigma = P.close[:, cols], P.sigma[:, cols]
    hist = np.cumsum(np.isfinite(close), axis=0)
    out = []
    for regime in (False, True):
        W = np.zeros((P.T, P.N))
        for t in range(200, P.T):
            W[t, cols] = target_weights(close, sigma, hist, t, [28], 0.40) * (P.btc_on[t] if regime else 1.0)
        r = fc.run(P, "reference", "survivors", "tsmom 28d · daily · vol 40% · 20 survivors"
                   + (" · regime" if regime else ""), W, start=200)
        out.append(fc.measure(P, r))
    tmp = [dict(x) for x in all_rows]
    for ref in out:
        rows = tmp + [ref]
        fc.deflate(rows)
        ref["note"] = "reference, not counted"
    return out


def judge(row: dict, bench: dict) -> tuple[bool, str]:
    b = bench[row["benchmark"]]
    why = []
    if row["deflated_p"] <= 0.95:
        why.append(f"deflated p {row['deflated_p']:.2f} <= 0.95")
    if row["oos_sharpe_41bps"] <= 0:
        why.append(f"Sharpe at 41 bps {row['oos_sharpe_41bps']:.2f} <= 0")
    if row["oos_max_dd_41bps"] >= b["oos_max_dd_15bps"]:
        why.append(f"drawdown {row['oos_max_dd_41bps'] * 100:.0f} % not below {b['variant']} "
                   f"{b['oos_max_dd_15bps'] * 100:.0f} %")
    return (not why), ("passes" if not why else "fails: " + "; ".join(why))


def main() -> None:
    fresh = "--fresh" in sys.argv
    P = fc.load_panel()
    bench = bench_rows(P)
    results: dict[str, list[fc.Result]] = {}
    for fam in FAMILIES:
        results[fam] = compute(fam, P, fresh)

    # In-sample picks of the base families feed the pre-specified ensemble.
    rows_by_fam = {fam: [fc.measure(P, r) for r in res] for fam, res in results.items()}
    from . import fam_ensemble
    sleeves = []
    for fam in FAMILIES:
        for sub in sorted({r["sub"] for r in rows_by_fam[fam]}):
            cand = [(row, res) for row, res in zip(rows_by_fam[fam], results[fam]) if row["sub"] == sub]
            row, res = max(cand, key=lambda x: x[0]["is_sharpe_15bps"])
            sleeves.append(res)
    ens = fam_ensemble.variants(P, sleeves) if fresh or fc.load_family("ensemble") is None else fc.load_family("ensemble")
    fc.save_family("ensemble", ens)
    results["ensemble"] = ens
    rows_by_fam["ensemble"] = [fc.measure(P, r) for r in ens]

    # Sensitivity only: the same deflation inside each family alone (fewer, more similar trials).
    for fam, rows in rows_by_fam.items():
        copies = [dict(r) for r in rows]
        fc.deflate(copies)
        for r, c in zip(rows, copies):
            r["deflated_p_family"] = c["deflated_p"]
    all_rows = [r for fam in results for r in rows_by_fam[fam]]
    dinfo = fc.deflate(all_rows)
    n_total = len(all_rows)
    reference = reference_rows(P, all_rows)

    summary, per_family_md = [], {}
    for fam in results:
        rows = rows_by_fam[fam]
        picks = []
        for sub in sorted({r["sub"] for r in rows}):
            cand = [r for r in rows if r["sub"] == sub]
            best = max(cand, key=lambda r: r["is_sharpe_15bps"])
            ok, why = judge(best, bench)
            best = dict(best, passes=ok, verdict=why,
                        sub_positive_share=float(np.mean([r["oos_sharpe_15bps"] > 0 for r in cand])),
                        sub_variants=len(cand))
            picks.append(best)
            summary.append(best)
        mod = importlib.import_module(f"lab.experiments.fam_{fam}")
        doc = (mod.__doc__ or "").strip()
        per_family_md[fam] = (
            f"# Family: {fam}\n\n```\n{doc}\n```\n\n"
            f"Survivorship-free Binance spot panel ({P.N} coin segments), in sample 2020-08 to 2023, out of sample "
            f"from 2024-01-01 ({int(fc.masks(P)[1].sum())} days). Net of 15 and 41 bps per unit of one-way turnover. "
            f"Deflated over all {n_total} variants of the whole sweep.\n\n"
            "## In-sample picks, judged out of sample\n\n"
            + fc.table(picks, ["sub", "variant", "is_sharpe_15bps", "oos_sharpe_15bps", "oos_sharpe_41bps",
                               "oos_cagr_41bps", "oos_max_dd_41bps", "turnover_yr", "deflated_p",
                               "sub_positive_share", "verdict"])
            + "\n## Benchmarks (no costs)\n\n" + fc.table(list(bench.values()), COLS)
            + "\n## Every variant\n\n"
            + fc.table(sorted(rows, key=lambda r: (r["sub"], -r["is_sharpe_15bps"])), ["sub"] + COLS + ["deflated_p"])
        )
        if hasattr(mod, "extra_markdown"):
            per_family_md[fam] += mod.extra_markdown(P)
        fc.write_result(f"family_{fam}", per_family_md[fam], {"rows": rows, "picks": picks})

    passing = [s for s in summary if s["passes"]]
    md = (
        "# Strategy families: the sweep\n\n"
        f"{len(results)} families, **{n_total} variants**, all deflated together. Survivorship-free Binance spot "
        f"panel of {P.N} coin segments (delisted coins included, reused tickers split), daily, in sample "
        "2020-08 to 2023, out of sample 2024-01-01 to "
        f"{np.datetime64(int(P.days[-1]), 'us').astype('datetime64[D]')}. Pick = best in-sample Sharpe at "
        "15 bps per sub-family; pass = deflated p > 0.95, Sharpe > 0 at 41 bps, drawdown below the benchmark.\n\n"
        f"Deflation: {n_total} trials, variance of their daily out-of-sample Sharpes {dinfo['sr_var_daily']:.2e} "
        f"(annual Sharpes winsorised at +-{fc.SR_CLIP:.0f}; raw {dinfo['sr_var_daily_raw']:.2e}). The best of "
        f"{n_total} noise strategies would be expected to show an annual Sharpe of about "
        f"{dinfo['expected_max_noise_sharpe_annual']:.2f}; a pick needs to clear that by a margin its own "
        "skew and kurtosis allow.\n\n"
        "## Benchmarks out of sample (no costs)\n\n" + fc.table(list(bench.values()), COLS)
        + "\n## Every pick\n\n"
        + fc.table(summary, ["family", "sub", "variant", "benchmark", "is_sharpe_15bps", "oos_sharpe_15bps",
                             "oos_sharpe_41bps", "oos_cagr_15bps", "oos_cagr_41bps", "oos_max_dd_41bps",
                             "turnover_yr", "oos_sharpe_btc_above", "oos_sharpe_btc_below", "deflated_p",
                             "sub_positive_share", "spot_only", "verdict"])
        + f"\n**Passing:** {', '.join(s['family'] + ' / ' + s['variant'] for s in passing) or 'none'}.\n"
        + "\n## How sensitive is the deflation verdict?\n\n"
        "deflated_p: the rule above (all trials, winsorised variance, own skew and kurtosis). "
        "rawvar: the variance without winsorising (stricter). null: the variance a pure-noise trial would "
        "have, 1/T (the textbook bar). family: only the trials of the pick's own family (more lenient, "
        "not the rule).\n\n"
        + fc.table(sorted(summary, key=lambda s: -s["oos_sharpe_15bps"]),
                   ["family", "variant", "oos_sharpe_15bps", "oos_skew", "oos_kurt", "deflated_p",
                    "deflated_p_rawvar", "deflated_p_null", "deflated_p_family"])
        + "\n## Reference: the existing paper candidate through the same bar\n\n"
        "Same simulator and costs, on the 20 coins of today's fixed universe (survivors). Deflated as if it "
        f"were trial {n_total + 1} of this sweep.\n\n"
        + fc.table(reference, ["variant", "is_sharpe_15bps", "oos_sharpe_15bps", "oos_sharpe_41bps",
                               "oos_cagr_41bps", "oos_max_dd_41bps", "turnover_yr", "oos_sharpe_btc_above",
                               "oos_sharpe_btc_below", "deflated_p", "deflated_p_null", "note"])
    )
    fc.write_result("families_summary", md, {"n_variants": n_total, "deflation": dinfo, "picks": summary,
                                             "benchmarks": bench, "reference": reference, "all_rows": all_rows})
    print(md)


if __name__ == "__main__":
    main()
