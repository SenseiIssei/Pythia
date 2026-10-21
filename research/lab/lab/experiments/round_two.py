"""Shared by the four studies registered together on 2026-10-21 late (positioning_xs,
taker_imbalance_xs, hedged_breakout, pead_xbrl): the pool they count into, the bootstrap
seed and the perp books' common machinery (the xs_daily matrices with a new score, the
residual on the low-vol book and BTC, and the verdict of funding_carry's pass rule).

The pool (results/positioning_xs_prereg.md): 1,353 hand trials before this registration
(1,328 before the evening batch of 2026-10-21 plus its 25), at the variance backed out of
the published bar (377 trials at 2.43); the factory ledger as read at run time; and the 24
trials registered here, each study's own at its own variance.
"""

from __future__ import annotations

import math

import numpy as np

from . import director_common as dc
from . import fam_common as fc

HAND_TRIALS = 1328 + 25
STUDY_TRIALS = {"positioning_xs": 5, "taker_imbalance_xs": 13, "hedged_breakout": 2, "pead_xbrl": 4}
TODAY_TRIALS = sum(STUDY_TRIALS.values())
SEED = 20261021

# Perp costs per unit of one-way turnover (perps_common: Kraken Futures taker 5 bps plus
# half-spread; 2 bps is the maker fee with every order filled, an upper bound).
PERP_COSTS = {"2bps": 0.0002, "10bps": 0.0010, "20bps": 0.0020, "41bps": 0.0041}
JUDGED, STRESS = "10bps", "20bps"
YEARS_OOS = (2024, 2025, 2026)


def pool(mine: list[float], year: int = dc.YEAR) -> dict:
    """The pooled per-period variance of trial Sharpes and the trial count. mine: this
    study's trial Sharpes, annualised over `year` periods; they stand for all 24 trials."""
    v1, n1 = dc.prior_var(), HAND_TRIALS
    fx = np.clip(dc.factory_sharpes(), -fc.SR_CLIP, fc.SR_CLIP) / math.sqrt(dc.YEAR)
    n2, v2 = len(fx), float(np.var(fx)) if len(fx) > 1 else 0.0
    x = np.clip(np.array(mine, dtype=float), -fc.SR_CLIP, fc.SR_CLIP) / math.sqrt(year)
    v3 = float(np.var(x)) if len(x) > 1 else v1
    n3 = TODAY_TRIALS
    n = n1 + n2 + n3
    v = (n1 * v1 + n2 * v2 + n3 * v3) / n
    return {"hand_trials": n1, "factory_trials": n2, "today_trials": n3, "mine": len(x), "n_total": n,
            "var": v, "sr0_annual": fc._sr0(v, n) * math.sqrt(year)}


def pool_line(pl_: dict) -> str:
    return (f"Pool: {pl_['n_total']:,} trials ({pl_['hand_trials']:,} hand before this registration, "
            f"{pl_['factory_trials']} factory as read now, {pl_['today_trials']} registered together on "
            f"2026-10-21: positioning_xs 5, taker_imbalance_xs 13, hedged_breakout 2, pead_xbrl 4); the best noise "
            f"trial sits at an annual Sharpe of about {pl_['sr0_annual']:.2f}. The next study starts from "
            f"{HAND_TRIALS + TODAY_TRIALS:,} hand trials.")


def boot(x: np.ndarray, y: np.ndarray | None = None) -> tuple[float, float, float]:
    return dc.boot_band(np.asarray(x, dtype=float), None if y is None else np.asarray(y, dtype=float), seed=SEED)


# ---------------------------------------------------------------------------
# Perp cross-section books on the xs_daily panel (positioning_xs, taker_imbalance_xs)
# ---------------------------------------------------------------------------

def roll(a: np.ndarray, w: int, min_obs: int, how: str = "mean") -> np.ndarray:
    """fc.rolling, also for series shorter than the window (all NaN when min_obs cannot be met)."""
    if a.shape[0] < max(w, min_obs):
        if a.shape[0] < min_obs:
            return np.full(a.shape, np.nan)
        pad = np.full((w - a.shape[0],) + a.shape[1:], np.nan)
        return fc.rolling(np.concatenate([pad, a]), w, min_obs, how)[w - a.shape[0]:]
    return fc.rolling(a, w, min_obs, how)


def zscore_own(x: np.ndarray, window: int = 90, min_obs: int = 60, gap: int = 1) -> np.ndarray:
    """Column-wise z of x[t] against x[t-gap-window+1 .. t-gap] (its own trailing values,
    the current one excluded for gap >= 1), NaN with fewer than min_obs."""
    lag = np.full_like(x, np.nan)
    lag[gap:] = x[:-gap]
    mu = roll(lag, window, min_obs)
    m2 = roll(lag ** 2, window, min_obs)
    sd = np.sqrt(np.maximum(m2 - mu ** 2, 0.0))
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(sd > 0, (x - mu) / sd, np.nan)


def late(score: np.ndarray) -> np.ndarray:
    out = np.full_like(score, np.nan)
    out[1:] = score[:-1]
    return out


def run_book(M: dict, score: np.ndarray, k: int, hold: int) -> dict:
    from . import xs_daily as xs
    g, tu, fu, ex = xs.book(M, score, k, hold, 100, True)
    return {"gross": g, "turnover": tu, "funding": fu, "exposure": ex}


def net(b: dict, cost: float) -> np.ndarray:
    return b["gross"] + b["funding"] - b["turnover"] * cost


def book_row(name: str, b: dict, sel: np.ndarray, hold: np.ndarray, years: np.ndarray, btc: np.ndarray) -> dict:
    row = {"variant": name, "turnover_yr": float(b["turnover"][hold].sum() / (hold.sum() / 365)),
           "fund_hold_pct": float(b["funding"][hold].mean() * 365 * 100)}
    for c, v in PERP_COSTS.items():
        n = net(b, v)
        row[f"sel_{c}"] = dc.sharpe(n[sel])
        row[f"hold_{c}"] = dc.sharpe(n[hold])
    n10 = net(b, PERP_COSTS[JUDGED])
    p = dc.perf(n10[hold])
    row["hold_cagr_pct"], row["hold_dd_pct"] = p["cagr"] * 100, p["max_dd"] * 100
    row["corr_btc"] = float(np.corrcoef(n10[hold], btc[hold])[0, 1])
    for y in YEARS_OOS:
        row[f"y{y}"] = dc.sharpe(n10[hold & (years == y)])
    return row


def residual(M: dict, pick: dict, lowvol: dict, late_b: dict, fit: np.ndarray, sel: np.ndarray,
             hold: np.ndarray, years: np.ndarray, btc: np.ndarray) -> tuple[dict, np.ndarray, np.ndarray]:
    """funding_carry's residual test at every cost: OLS of the pick on the low-vol book of
    its shape and BTC over `fit`, betas frozen, R judged on `hold`. Returns the rows by
    cost, R at the judged cost on the holdout and the pick's holdout series there."""
    from .m4_residual import ols, ols_se
    out, r_j, p_j = {}, None, None
    for c, v in PERP_COSTS.items():
        y_ = net(pick, v)
        lv = net(lowvol, v)
        X = np.column_stack([lv, btc])
        coef, r2 = ols(y_[fit], X[fit])
        se = ols_se(y_[fit], X[fit])
        a, b1, b2 = (float(x) for x in coef)
        R = y_ - b1 * lv - b2 * btc
        lo, hi, above = boot(R[hold])
        row = {"cost": c, "alpha_fit_ann": a * 365, "se_alpha_fit_ann": float(se[0] * 365), "b_lowvol": b1,
               "se_b_lowvol": float(se[1]), "b_btc": b2, "se_b_btc": float(se[2]), "r2_fit": r2,
               "corr_fit": float(np.corrcoef(y_[fit], lv[fit])[0, 1]),
               "corr_hold": float(np.corrcoef(y_[hold], lv[hold])[0, 1]),
               "pick_sel": dc.sharpe(y_[sel]), "pick_hold": dc.sharpe(y_[hold]),
               "lowvol_sel": dc.sharpe(lv[sel]), "lowvol_hold": dc.sharpe(lv[hold]), "btc_hold": dc.sharpe(btc[hold]),
               "R_hold": dc.sharpe(R[hold]), "R_hold_mean_ann": float(R[hold].mean() * 365),
               "boot_p05": lo, "boot_p95": hi, "boot_above0": above,
               "late_hold": dc.sharpe(net(late_b, v)[hold])}
        for y in YEARS_OOS:
            row[f"R{y}"] = dc.sharpe(R[hold & (years == y)])
        out[c] = row
        if c == JUDGED:
            r_j, p_j = R[hold], y_[hold]
    return out, r_j, p_j


def checks(pick: dict, j: dict) -> dict:
    """funding_carry's pass rule, registered unchanged for both perp studies."""
    return {"1 holdout Sharpe above 0.5 at 10 bps and above 0 at 20 bps": pick["hold_10bps"] > 0.5
            and pick["hold_20bps"] > 0,
            "2 positive in 2 of 2024, 2025, 2026": sum(pick[f"y{y}"] > 0 for y in YEARS_OOS) >= 2,
            "3 one day late above 0 at 10 bps": j["late_hold"] > 0,
            "4 residual above 0.3, bootstrap 5 % above 0": j["R_hold"] > 0.3 and j["boot_p05"] > 0}


def ic_rows(M: dict, scores: dict[str, np.ndarray], labels: dict[str, tuple[np.ndarray, int]],
            windows: dict[str, np.ndarray]) -> list[dict]:
    """Daily Spearman IC of each score with each label among all scored coins with a
    label; t on non-overlapping blocks of the label's horizon."""
    from scipy import stats
    out = []
    for sname, s in scores.items():
        for lname, (y, h) in labels.items():
            for wname, m in windows.items():
                ics = []
                for t in np.flatnonzero(m):
                    ok = np.isfinite(s[t]) & np.isfinite(y[t])
                    if ok.sum() >= 10:
                        ics.append(stats.spearmanr(s[t, ok], y[t, ok])[0])
                a = np.array([v for v in ics if np.isfinite(v)])
                blocks = a[::h] if len(a) else a
                t_ = float(blocks.mean() / blocks.std(ddof=1) * math.sqrt(len(blocks))) if len(blocks) > 2 else math.nan
                out.append({"score": sname, "label": lname, "window": wname,
                            "ic_mean": float(a.mean()) if len(a) else math.nan, "ic_t": t_, "days": int(len(a))})
    return out


def overlap(M: dict, a: np.ndarray, b: np.ndarray, k: int, hold: np.ndarray) -> tuple[float, float]:
    """Mean share of the fresh k long (short) names of score a that score b also picks."""
    from .funding_carry import picks_today
    la, sa = picks_today(M, a, k)
    lb, sb = picks_today(M, b, k)
    ol = [len(x & y) / k for x, y, h in zip(la, lb, hold) if h and x]
    os_ = [len(x & y) / k for x, y, h in zip(sa, sb, hold) if h and x]
    return (float(np.mean(ol)) if ol else math.nan, float(np.mean(os_)) if os_ else math.nan)


# ---------------------------------------------------------------------------
# Signals per perp symbol, on a full daily calendar
# ---------------------------------------------------------------------------

def per_perp(frame, cols: list[str], fn, day_col: str = "day"):
    """Apply fn({col: (T, 1) array on a gap-free daily calendar}) -> {out: (T, 1) array}
    to each perp's rows of `frame` (perp, day_col, cols); returns (perp, day, outputs)
    on the calendar days. Days missing in the frame are NaN inside fn."""
    import polars as pl
    parts = []
    for (perp,), g in frame.sort(day_col).group_by(["perp"], maintain_order=True):
        d = g[day_col].to_numpy().astype(np.int64)
        cal = np.arange(d.min(), d.max() + fc.DAY_US, fc.DAY_US, dtype=np.int64)
        idx = ((d - cal[0]) // fc.DAY_US).astype(np.int64)
        arrs = {}
        for c in cols:
            a = np.full((len(cal), 1), np.nan)
            a[idx, 0] = g[c].cast(pl.Float64).to_numpy()
            arrs[c] = a
        out = fn(arrs)
        parts.append(pl.DataFrame({"perp": [perp] * len(cal), "day": cal,
                                   **{k: np.asarray(v, dtype=float).reshape(-1) for k, v in out.items()}}))
    return pl.concat(parts, how="vertical_relaxed")


def load_matrices(signals, score_cols: list[str], extra=None):
    """funding_carry.load's matrices with per-perp signals joined on the day's perp:
    (M, fund_end). `signals`: (perp, day, score_cols...). `extra(P)` may add columns to
    the panel before the matrices are built."""
    import polars as pl
    from . import xs_daily as xs
    P = xs.build_panel()
    P, fund_end = xs.add_net_labels(P)
    P = P.join(signals, on=["day", "perp"], how="left")
    if extra is not None:
        P = extra(P)
    E = P.filter(pl.col("eligible")).with_columns(
        adv28_raw=pl.col("adv28"), r1_raw=pl.col("r1"), r28_raw=pl.col("r28"), lowvol=-pl.col("vol28"),
        fund7_raw=pl.when(pl.col("perp").is_not_null()).then(pl.col("fund7")).otherwise(None))
    E = E.with_columns(*[pl.when(pl.col("perp").is_not_null()).then(pl.col(c)).otherwise(None).alias(c)
                         for c in score_cols])
    M = xs.matrices(E, P, score_cols + ["lowvol", "net3", "net7", "fwd1"])
    return M, fund_end


# ---------------------------------------------------------------------------
# The perp study: books, pick, residual, checks (funding_carry's machinery)
# ---------------------------------------------------------------------------

def perp_study(M: dict, fund_end: int, variants: list[tuple[str, str, int, int]], sel_from: str,
               fit_from: str, fit_to: str, ic_scores: dict[str, np.ndarray]) -> dict:
    """variants: (label, score key in M, k, hold). The pick is the highest selection-window
    Sharpe at 10 bps; the residual is fitted on [fit_from, fit_to]."""
    from datetime import datetime, timezone
    from . import funding_carry as fcy
    from . import perps_common as pc
    from . import xs_daily as xs
    days = M["days"]
    hold_end = min(int(fund_end), int(days[np.isfinite(M["R"]).any(1)][-1]))
    years = dc.years_of(days)
    sel = (days >= dc.us(sel_from)) & (days < xs.HOLDOUT)
    fit = (days >= dc.us(fit_from)) & (days <= dc.us(fit_to))
    hold = (days >= xs.HOLDOUT) & (days <= hold_end)
    bi = list(M["syms"]).index("BTCUSDT")
    btc = np.nan_to_num(M["R"][:, bi])
    books, rows = {}, []
    for name, key, k, h in variants:
        b = run_book(M, M[key], k, h)
        books[name] = b
        row = book_row(name, b, sel, hold, years, btc)
        row.update({"key": key, "k": k, "hold": h})
        rows.append(row)
        print(name, round(row["sel_10bps"], 2), round(row["hold_10bps"], 2), flush=True)
    pick = max(rows, key=lambda r: r["sel_10bps"])
    pb = books[pick["variant"]]
    lv = run_book(M, M["lowvol"], pick["k"], pick["hold"])
    lb = run_book(M, late(M[pick["key"]]), pick["k"], pick["hold"])
    by_cost, r_j, p_j = residual(M, pb, lv, lb, fit, sel, hold, years, btc)
    j = by_cost[JUDGED]
    pl_ = pool([r["hold_10bps"] for r in rows] + [j["R_hold"]])
    j["deflated_p"] = dc.deflated(r_j, pl_)
    j["pick_deflated_p"] = dc.deflated(p_j, pl_)
    lg = fcy.legs(M, M[pick["key"]], pick["k"], pick["hold"])
    lg.pop("per_coin")
    legs = []
    for y in sorted(set(years[sel | hold].tolist())):
        m = (years == y) & (sel | hold)
        legs.append({"year": int(y), **{f"{x}_pct": float(lg[x][m].mean() * 365 * 100) for x in lg},
                     "costs_10bps_pct": float(-(pb["turnover"][m] * PERP_COSTS[JUDGED]).mean() * 365 * 100)})
    ov_l, ov_s = overlap(M, M[pick["key"]], M["lowvol"], pick["k"], hold)
    cover = []
    for y in sorted(set(years[sel | hold].tolist())):
        m = (years == y) & (sel | hold)
        n = np.isfinite(M[pick["key"]][m]).sum(1)
        cover.append({"year": int(y), "median_scored": float(np.median(n)), "min_scored": int(n.min())})
    labels = {"fwd1": (M["fwd1"], 1), "net3": (M["net3"], 3), "net7": (M["net7"], 7)}
    ics = ic_rows(M, ic_scores, labels, {"selection": sel, "holdout": hold})
    res = {"generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "sel_from": dc.day_str(days[sel][0]), "sel_to": dc.day_str(days[sel][-1]),
           "hold_from": dc.day_str(days[hold][0]), "hold_to": dc.day_str(days[hold][-1]),
           "fit_from": dc.day_str(days[fit][0]), "fit_to": dc.day_str(days[fit][-1]),
           "hold_days": int(hold.sum()), "rows": rows, "pick": pick["variant"], "by_cost": by_cost,
           "legs": legs, "overlap_long": ov_l, "overlap_short": ov_s, "coverage": cover, "ic": ics, "pool": pl_}
    listing = pc.kraken_listing()
    res["kraken_coins"] = len(listing)
    if listing:
        kb = run_book(M, fcy.restrict(M, M[pick["key"]], set(listing)), pick["k"], pick["hold"])
        res["kraken_hold_10bps"] = dc.sharpe(net(kb, PERP_COSTS[JUDGED])[hold])
        res["kraken_sel_10bps"] = dc.sharpe(net(kb, PERP_COSTS[JUDGED])[sel])
    res["checks"] = checks(pick, j)
    passed = all(res["checks"].values())
    res["verdict"] = "pass" if passed else ("kill" if j["R_hold"] <= 0.1 else "inconclusive")
    res["confirmed"] = passed and j["deflated_p"] > 0.95
    return res


def perp_markdown(title: str, prereg: str, intro: str, res: dict) -> str:
    j, pl_ = res["by_cost"][JUDGED], res["pool"]
    pick = next(r for r in res["rows"] if r["variant"] == res["pick"])
    v = {"pass": "**Pass" + (", confirmed.**" if res["confirmed"] else ", experimental (fails deflation).**"),
         "kill": "**Kill.** The residual after the low-vol book and BTC is at or below 0.1.",
         "inconclusive": "**Fail.** Not shown to earn beyond the low-vol book and BTC."}[res["verdict"]]
    md = [f"# {title}: results\n",
          f"Generated {res['generated']}. Registered in `results/{prereg}` before the run.\n",
          intro + "\n",
          f"Selection {res['sel_from']} to {res['sel_to']}, holdout {res['hold_from']} to {res['hold_to']} "
          f"({res['hold_days']} days); residual fitted {res['fit_from']} to {res['fit_to']}. Books among the 100 "
          "most liquid USDT perps with a score, half the capital per side, funding paid and received, costs per "
          "unit of one-way turnover.\n",
          f"## Verdict\n\n{v} Pick: **{res['pick']}**.\n"]
    for k, ok in res["checks"].items():
        md.append(f"- {k}: {'yes' if ok else 'no'}")
    md.append(f"\nThe pick from 2024: Sharpe {pick['hold_10bps']:.2f} at 10 bps (2 bps {pick['hold_2bps']:.2f}, 20 bps "
              f"{pick['hold_20bps']:.2f}, 41 bps {pick['hold_41bps']:.2f}), {pick['hold_cagr_pct']:.1f} % a year, "
              f"drawdown {pick['hold_dd_pct']:.1f} %, correlation with BTC {pick['corr_btc']:+.2f}, years "
              f"{pick['y2024']:.2f} / {pick['y2025']:.2f} / {pick['y2026']:.2f}, a day late {j['late_hold']:.2f}. "
              f"Residual R {j['R_hold']:.2f} (band {j['boot_p05']:.2f} to {j['boot_p95']:.2f}). Deflated p of R over "
              f"the pool {j['deflated_p']:.4f}, of the pick itself {j['pick_deflated_p']:.4f}.\n")
    md.append("## All books\n")
    md.append(dc.table(res["rows"], ["variant", "sel_2bps", "sel_10bps", "hold_2bps", "hold_10bps", "hold_20bps",
                                     "hold_41bps", "hold_cagr_pct", "hold_dd_pct", "corr_btc", "y2024", "y2025",
                                     "y2026", "turnover_yr", "fund_hold_pct"]))
    md.append("\n`sel_*` and `hold_*` are Sharpes (daily x sqrt 365) at that cost; CAGR, drawdown, correlation with BTC "
              "and the years at 10 bps; `fund_hold_pct` is the funding the book received (+) or paid (-) a year in "
              "the holdout, both legs.\n")
    md.append("\n## The pick against the low-vol book of its shape and BTC\n")
    rows = list(res["by_cost"].values())
    md.append(dc.table(rows, ["cost", "alpha_fit_ann", "se_alpha_fit_ann", "b_lowvol", "se_b_lowvol", "b_btc",
                              "se_b_btc", "r2_fit", "corr_fit", "corr_hold"], ".3f"))
    md.append("\n")
    md.append(dc.table(rows, ["cost", "pick_sel", "lowvol_sel", "pick_hold", "lowvol_hold", "btc_hold", "late_hold",
                              "R_hold", "R_hold_mean_ann", "boot_p05", "boot_p95", "boot_above0", "R2024", "R2025",
                              "R2026"]))
    md.append(f"\nR = pick - b_lowvol x lowvol - b_btc x BTC with the betas fitted at each cost and frozen (intercept "
              f"kept). Bootstrap: stationary, mean block {dc.BOOT_BLOCK} days, {dc.BOOT_DRAWS} draws, seed {SEED}. "
              "`late_hold`: the pick on the previous day's scores. Judged row: 10bps.\n")
    md.append("\n## Where the pick's money comes from (per year, % of capital a year)\n")
    md.append(dc.table(res["legs"], ["year", "long_px_pct", "short_px_pct", "long_fund_pct", "short_fund_pct",
                                     "costs_10bps_pct"], ".1f"))
    md.append(f"\nOn an average holdout day the pick's fresh long list shares {res['overlap_long'] * 100:.0f} % of its "
              f"names with the low-vol book's, the short list {res['overlap_short'] * 100:.0f} %.\n")
    if res.get("kraken_coins"):
        md.append(f"\nRestricted to the coins of the {res['kraken_coins']} PF perpetuals Kraken Futures lists today "
                  f"(not survivorship-free): selection {res['kraken_sel_10bps']:.2f}, holdout "
                  f"{res['kraken_hold_10bps']:.2f} at 10 bps.\n")
    md.append("\n## Signal skill (information only)\n")
    md.append(dc.table(res["ic"], ["score", "label", "window", "ic_mean", "ic_t", "days"], ".3f"))
    md.append("\nDaily Spearman IC of each score (in the direction the book trades it) with the next day's log return "
              "(`fwd1`) and the next 3 and 7 days' funding-net log return, over every eligible coin with a score; t on "
              "non-overlapping blocks of the label's length.\n")
    md.append("\nScored coins per day (the pick's score):\n")
    md.append(dc.table(res["coverage"], ["year", "median_scored", "min_scored"]))
    md.append("\n## Pool\n\n" + pool_line(pl_) + "\n")
    return "\n".join(md)
