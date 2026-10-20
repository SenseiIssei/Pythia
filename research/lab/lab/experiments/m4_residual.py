"""Does the funding-aware M4 long/short (reg7n) earn anything beyond the low-vol factor and BTC?

    python -m lab.experiments.m4_residual

Pre-registered in results/m4_residual_prereg.md (committed before this file ran).
Rebuilds, from xs_daily's cache (panel and round-three walk-forward scores of the
2026-10-07 run), the reg7n book (10/10 of the 100 most liquid perps, rank buffer
50 %) and the low-vol book of the same shape, checks the reg7n book against the
cached pick series, fits reg7n's daily net return at 41 bps on the low-vol book and
BTC over 2022-2023, freezes the betas and judges the residual (intercept kept) in
the holdout 2024-01-01 to 2026-09-28. Writes results/m4_residual.md below the
marker and <reports>/m4_residual/latest.{md,json}.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import numpy as np
import polars as pl

from .. import report
from . import director_common as dc
from . import xs_daily as xs

NAME = "m4_residual"
HOLDOUT_END = "2026-09-28"
COSTS = {"15bps": xs.COSTS["15bps"], "41bps": xs.COSTS["41bps"]}
JUDGED = "41bps"
YEARS_FIT = (2022, 2023)
YEARS_OOS = (2024, 2025, 2026)
PICK_CACHE = "xs_daily_pick_long_short_funding-aware.parquet"
MATCH_TOL = 1e-9
ROLL = 365


def books() -> tuple[np.ndarray, dict[str, dict], np.ndarray]:
    """(days, {reg7n, lowvol: gross, turnover, funding}, BTC's R1), from xs_daily's cache."""
    P = xs.build_panel()
    P, _ = xs.add_net_labels(P)
    E = xs.ranked(P.with_columns(adv28_raw=pl.col("adv28"), r1_raw=pl.col("r1"), r28_raw=pl.col("r28"),
                                 fund7_raw=pl.col("fund7"), vol28_raw=pl.col("vol28")))
    S = pl.read_parquet(xs.CACHE / "xs_daily_scores_net.parquet").select("day", "symbol", "reg7n")
    E = E.join(S, on=["day", "symbol"], how="left").filter(pl.col("day") >= xs.FIRST_TEST)
    E = E.with_columns(lowvol=-pl.col("vol28_raw"))
    M = xs.matrices(E, P.filter(pl.col("day") >= xs.FIRST_TEST), ["reg7n", "lowvol"])
    out = {}
    for name in ("reg7n", "lowvol"):
        g, tu, fu, ex = xs.book_buffer(M, M[name], 10, 0.5, 100)
        out[name] = {"gross": g, "turnover": tu, "funding": fu, "exposure": ex}
    bi = list(M["syms"]).index("BTCUSDT")
    return M["days"], out, np.nan_to_num(M["R"][:, bi])


def check_cache(days: np.ndarray, b: dict) -> dict:
    c = pl.read_parquet(xs.CACHE / PICK_CACHE)
    cd = c["day"].to_numpy()
    assert np.array_equal(cd, days), "the cached pick's days differ from the rebuilt panel's"
    diff = {k: float(np.max(np.abs(c[k].to_numpy() - b[k]))) for k in ("gross", "funding", "turnover")}
    if max(diff.values()) > MATCH_TOL:
        raise SystemExit(f"the rebuilt reg7n book does not match the cached pick series: {diff}")
    return diff


def ols(y: np.ndarray, X: np.ndarray) -> tuple[np.ndarray, float]:
    A = np.column_stack([np.ones(len(y)), X])
    coef, *_ = np.linalg.lstsq(A, y, rcond=None)
    resid = y - A @ coef
    r2 = 1 - resid.var() / y.var() if y.var() > 0 else 0.0
    return coef, float(r2)


def ols_se(y: np.ndarray, X: np.ndarray) -> np.ndarray:
    A = np.column_stack([np.ones(len(y)), X])
    coef, *_ = np.linalg.lstsq(A, y, rcond=None)
    e = y - A @ coef
    s2 = e @ e / (len(y) - A.shape[1])
    return np.sqrt(np.diag(s2 * np.linalg.inv(A.T @ A)))


def main() -> None:
    days, B, btc = books()
    diff = check_cache(days, B["reg7n"])
    years = dc.years_of(days)
    fit = days < xs.HOLDOUT
    hold = (days >= xs.HOLDOUT) & (days <= dc.us(HOLDOUT_END))
    res: dict = {"generated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "cache_match": diff,
                 "fit_from": dc.day_str(days[fit][0]), "fit_to": dc.day_str(days[fit][-1]),
                 "hold_from": dc.day_str(days[hold][0]), "hold_to": dc.day_str(days[hold][-1]),
                 "hold_days": int(hold.sum()), "by_cost": {}}
    trial = None
    for cname, cost in COSTS.items():
        net = {k: b["gross"] + b["funding"] - b["turnover"] * cost for k, b in B.items()}
        X = np.column_stack([net["lowvol"], btc])
        coef, r2 = ols(net["reg7n"][fit], X[fit])
        se = ols_se(net["reg7n"][fit], X[fit])
        a, b1, b2 = (float(v) for v in coef)
        R = net["reg7n"] - b1 * net["lowvol"] - b2 * btc
        lo, hi, above = dc.boot_band(R[hold])
        coef_h, r2_h = ols(net["reg7n"][hold], X[hold])
        se_h = ols_se(net["reg7n"][hold], X[hold])
        row = {"cost": cname, "alpha_fit_ann": a * 365, "b_lowvol": b1, "b_btc": b2,
               "se_alpha_fit_ann": float(se[0] * 365), "se_b_lowvol": float(se[1]), "se_b_btc": float(se[2]),
               "r2_fit": r2, "r2_hold_frozen": float(1 - R[hold].var() / net["reg7n"][hold].var()),
               "reg7n_hold": dc.sharpe(net["reg7n"][hold]), "lowvol_hold": dc.sharpe(net["lowvol"][hold]),
               "btc_hold": dc.sharpe(btc[hold]), "reg7n_fit": dc.sharpe(net["reg7n"][fit]),
               "lowvol_fit": dc.sharpe(net["lowvol"][fit]), "btc_fit": dc.sharpe(btc[fit]),
               "corr_hold": float(np.corrcoef(net["reg7n"][hold], net["lowvol"][hold])[0, 1]),
               "corr_fit": float(np.corrcoef(net["reg7n"][fit], net["lowvol"][fit])[0, 1]),
               "R_hold": dc.sharpe(R[hold]), "R_hold_mean_ann": float(R[hold].mean() * 365),
               "R_hold_dd": dc.perf(R[hold])["max_dd"],
               "boot_p05": lo, "boot_p95": hi, "boot_above0": above,
               "refit_alpha_ann": float(coef_h[0] * 365), "refit_se_alpha_ann": float(se_h[0] * 365),
               "refit_b_lowvol": float(coef_h[1]), "refit_b_btc": float(coef_h[2]), "refit_r2": r2_h,
               "refit_alpha_t": float(coef_h[0] / se_h[0]) if se_h[0] > 0 else 0.0}
        for y in YEARS_FIT + YEARS_OOS:
            m = (years == y) & (fit | hold)
            row[f"R{y}"] = dc.sharpe(R[m])
            row[f"R{y}_mean_ann"] = float(R[m].mean() * 365)
            row[f"reg7n{y}"] = dc.sharpe(net["reg7n"][m])
            row[f"lowvol{y}"] = dc.sharpe(net["lowvol"][m])
        # Rolling one-year betas over the whole span (information only).
        roll = []
        for end in np.flatnonzero(fit | hold):
            if end + 1 < ROLL or (end + 1 - ROLL) % 91:
                continue
            sl = slice(end + 1 - ROLL, end + 1)
            cf, _ = ols(net["reg7n"][sl], X[sl])
            roll.append({"to": dc.day_str(days[end]), "alpha_ann": float(cf[0] * 365), "b_lowvol": float(cf[1]),
                         "b_btc": float(cf[2])})
        row["rolling"] = roll
        res["by_cost"][cname] = row
        if cname == JUDGED:
            trial = R[hold]
            judged = row
    pl_ = dc.pool([judged["R_hold"]])
    judged["deflated_p"] = dc.deflated(trial, pl_)
    res["pool"] = pl_
    yrs_neg = sum(judged[f"R{y}"] < 0 for y in YEARS_OOS)
    checks = {"1 holdout Sharpe above 0.5": judged["R_hold"] > 0.5,
              "2 bootstrap 5 % above 0": judged["boot_p05"] > 0,
              "3 positive in 2024, 2025 and 2026": all(judged[f"R{y}"] > 0 for y in YEARS_OOS),
              "4 positive in 2023 (in the fit window)": judged["R2023"] > 0}
    passed = all(checks.values())
    killed = judged["R_hold"] <= 0.25 or yrs_neg >= 2
    res["checks"] = checks
    res["verdict"] = "pass" if passed else ("kill" if killed else "inconclusive")
    res["confirmed"] = passed and judged["deflated_p"] > 0.95
    write(res)


def write(res: dict) -> None:
    j, pl_ = res["by_cost"][JUDGED], res["pool"]
    v = {"pass": "**Pass.** reg7n earns beyond the low-vol factor and BTC.",
         "kill": "**Kill.** M4's long/short is the low-vol factor plus BTC exposure plus funding avoidance.",
         "inconclusive": "**Inconclusive.** Not shown to earn beyond the factor."}[res["verdict"]]
    md = ["# M4 reg7n beyond the low-vol factor and BTC: results\n",
          f"Generated {res['generated']}. Registered in `results/m4_residual_prereg.md` before the run.\n",
          f"Fit {res['fit_from']} to {res['fit_to']}, holdout {res['hold_from']} to {res['hold_to']} "
          f"({res['hold_days']} days). Both books 10/10 of the 100 most liquid perps, rank buffer 50 %, funding "
          "charged; the rebuilt reg7n book matches xs_daily's cached pick series (largest difference "
          f"{max(res['cache_match'].values()):.1e}).\n",
          f"## Verdict\n\n{v}\n"]
    for k, ok in res["checks"].items():
        md.append(f"- {k}: {'yes' if ok else 'no'}")
    md.append(f"\nDeflated p of R over the pool: {j['deflated_p']:.4f}"
              + (" (confirmed)." if res["confirmed"] else "."))
    md.append("\n## Frozen betas and the residual\n")
    rows = list(res["by_cost"].values())
    md.append(dc.table(rows, ["cost", "alpha_fit_ann", "se_alpha_fit_ann", "b_lowvol", "se_b_lowvol", "b_btc", "se_b_btc",
                              "r2_fit", "r2_hold_frozen", "corr_fit", "corr_hold"], ".3f"))
    md.append("\n")
    md.append(dc.table(rows, ["cost", "reg7n_fit", "lowvol_fit", "btc_fit", "reg7n_hold", "lowvol_hold", "btc_hold",
                              "R_hold", "R_hold_mean_ann", "boot_p05", "boot_p95", "boot_above0"]))
    md.append(f"\nR = reg7n - b_lowvol x lowvol - b_btc x BTC with the betas from the fit window (intercept kept in R). "
              f"Bootstrap: stationary, mean block {dc.BOOT_BLOCK} days, {dc.BOOT_DRAWS} draws, seed {dc.BOOT_SEED}, "
              "5 % and 95 % of R's annual Sharpe. `alpha_fit_ann` and `R_hold_mean_ann` are daily means x 365.\n")
    md.append("\n## By year (Sharpe; 2022 and 2023 are the fit window)\n")
    yr_rows = []
    for c, r in res["by_cost"].items():
        for y in YEARS_FIT + YEARS_OOS:
            yr_rows.append({"cost": c, "year": y, "reg7n": r[f"reg7n{y}"], "lowvol": r[f"lowvol{y}"], "R": r[f"R{y}"],
                            "R_mean_ann": r[f"R{y}_mean_ann"]})
    md.append(dc.table(yr_rows, ["cost", "year", "reg7n", "lowvol", "R", "R_mean_ann"]))
    md.append("\n## Refitted on the holdout (information only, not judged)\n")
    md.append(dc.table(rows, ["cost", "refit_alpha_ann", "refit_se_alpha_ann", "refit_alpha_t", "refit_b_lowvol",
                              "refit_b_btc", "refit_r2"], ".3f"))
    md.append("\n## Rolling one-year betas at 41 bps (information only)\n")
    md.append(dc.table(j["rolling"], ["to", "alpha_ann", "b_lowvol", "b_btc"], ".3f"))
    md.append(f"\n## Pool\n\n{pl_['n_total']:,} trials ({pl_['hand_trials']:,} hand, {pl_['factory_trials']} factory, "
              f"{pl_['today_trials']} registered today); the best noise trial sits at an annual Sharpe of about "
              f"{pl_['sr0_annual']:.2f}.\n")
    text = "\n".join(md)
    dc.write_results(NAME, text)
    report.write(NAME, text, res)


if __name__ == "__main__":
    main()
