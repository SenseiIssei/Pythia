"""Cross-sectional funding carry on perpetuals, judged on its residual after low vol and BTC.

    PYTHIA_CACHE=<fresh cache> python -m lab.experiments.funding_carry

Pre-registered in results/funding_carry_prereg.md (committed before this file ran).
On the xs_daily panel (rebuilt into PYTHIA_CACHE, the 2026-10-07 cache untouched):
long the k perps with the lowest recent funding, short the k with the highest, among
the 100 most liquid USDT perps of each day, in overlapping tranches (xs_daily.book),
funding paid and received, at Kraken Futures costs (10 bps per unit of one-way
turnover, 20 stress; 0 and 41 reported). The selection-window pick (2020-08 to 2023)
is regressed on the low-vol book of its own shape and on BTC over 2022-23, the betas
frozen, and the residual judged from 2024-01-01 to the end of the funding archive.
Writes results/funding_carry.md below the marker and <reports>/funding_carry/latest.*.
"""

from __future__ import annotations

import itertools
from datetime import datetime, timezone

import numpy as np
import polars as pl

from .. import report
from . import director_common as dc
from . import perps_common as pc
from . import xs_daily as xs
from .m4_residual import ols, ols_se

NAME = "funding_carry"
SIGNALS = {"F1": "fund1_raw", "F7": "fund7_raw", "F28": "fund28_raw"}
KS = (10, 20)
HOLDS = (3, 7)
N_LIQUID = 100
SEL_FROM = "2020-08-01"
FIT = (2022, 2023)
YEARS_OOS = (2024, 2025, 2026)
ROLL = 365


def label(sig: str, k: int, hold: int) -> str:
    return f"{sig} · {k}/{k} · " + ("3-day tranches" if hold == 3 else "weekly tranches")


# ---------------------------------------------------------------------------
# Matrices
# ---------------------------------------------------------------------------

def load() -> tuple[dict, int]:
    """Day x coin matrices from the xs_daily panel: R, fund (paid while held), the three
    funding signals, -vol28, liquidity, and net3 (for the IC, information only)."""
    P = xs.build_panel()
    P, fund_end = xs.add_net_labels(P)
    P = P.sort(["symbol", "day"]).with_columns(
        fund28_raw=pl.when(pl.col("perp").is_not_null())
        .then(pl.col("fund1").fill_null(0.0).rolling_sum(28, min_samples=20).over("symbol"))
        .otherwise(None),
        fund1_raw=pl.when(pl.col("perp").is_not_null()).then(pl.col("fund1")).otherwise(None),
        fund7_raw=pl.when(pl.col("perp").is_not_null()).then(pl.col("fund7")).otherwise(None),
    ).sort(["day", "symbol"])
    E = P.filter(pl.col("eligible")).with_columns(
        adv28_raw=pl.col("adv28"), r1_raw=pl.col("r1"), r28_raw=pl.col("r28"), lowvol=-pl.col("vol28"),
        **{f"s_{s}": -pl.col(c) for s, c in SIGNALS.items()})
    cols = [f"s_{s}" for s in SIGNALS] + ["lowvol", "net3"]
    M = xs.matrices(E, P, cols)
    return M, fund_end


def late(score: np.ndarray) -> np.ndarray:
    out = np.full_like(score, np.nan)
    out[1:] = score[:-1]
    return out


def restrict(M: dict, score: np.ndarray, coins: set[str]) -> np.ndarray:
    keep = np.array([pc.coin_of(s) in coins for s in M["syms"]])
    return np.where(keep[None, :], score, np.nan)


def run_book(M: dict, score: np.ndarray, k: int, hold: int) -> dict:
    g, tu, fu, ex = xs.book(M, score, k, hold, N_LIQUID, True)
    return {"gross": g, "turnover": tu, "funding": fu, "exposure": ex}


def legs(M: dict, score: np.ndarray, k: int, hold: int) -> dict[str, np.ndarray]:
    """xs_daily.book's long/short book again, split into the price return and the funding
    of each leg (the four add up to xs_daily.book's gross + funding; checked in main)."""
    R = np.nan_to_num(M["R"])
    F = M["fund"]
    T, N = R.shape
    liq = M["perp_adv28"]
    tl_, ts_ = [np.zeros(N) for _ in range(hold)], [np.zeros(N) for _ in range(hold)]
    out = {x: np.zeros(T) for x in ("long_px", "short_px", "long_fund", "short_fund")}
    # Per coin, summed over the holdout: price return and funding of each leg.
    hold_m = M["days"] >= xs.HOLDOUT
    per = {x: np.zeros(N) for x in ("long_px", "short_px", "long_fund", "short_fund")}
    for t in range(T):
        ok = np.isfinite(score[t]) & np.isfinite(liq[t])
        idx = np.flatnonzero(ok)
        idx = idx[np.argsort(-liq[t, idx])][:N_LIQUID]
        tl, ts = np.zeros(N), np.zeros(N)
        if len(idx) >= 2 * k:
            order = idx[np.argsort(-score[t, idx])]
            tl[order[:k]] = 0.5 / k
            ts[order[::-1][:k]] = -0.5 / k
        tl_[t % hold], ts_[t % hold] = tl, ts
        w = (sum(tl_) + sum(ts_)) / hold
        wl, ws = np.where(w > 0, w, 0.0), np.where(w < 0, w, 0.0)
        out["long_px"][t], out["short_px"][t] = float(wl @ R[t]), float(ws @ R[t])
        out["long_fund"][t], out["short_fund"][t] = -float(wl @ F[t]), -float(ws @ F[t])
        if hold_m[t]:
            per["long_px"] += wl * R[t]
            per["short_px"] += ws * R[t]
            per["long_fund"] -= wl * F[t]
            per["short_fund"] -= ws * F[t]
        g = float(w @ R[t])
        denom = 1 + g
        tl_ = [x * (1 + R[t]) / denom if denom > 0 else x for x in tl_]
        ts_ = [x * (1 + R[t]) / denom if denom > 0 else x for x in ts_]
    out["per_coin"] = per
    return out


def net(b: dict, cost: float) -> np.ndarray:
    return b["gross"] + b["funding"] - b["turnover"] * cost


def picks_today(M: dict, score: np.ndarray, k: int) -> tuple[list[set], list[set]]:
    """The k best and k worst by score among the day's 100 most liquid perps (fresh picks,
    not the tranche book), per day."""
    liq = M["perp_adv28"]
    longs, shorts = [], []
    for t in range(score.shape[0]):
        ok = np.isfinite(score[t]) & np.isfinite(liq[t])
        idx = np.flatnonzero(ok)
        idx = idx[np.argsort(-liq[t, idx])][:N_LIQUID]
        if len(idx) < 2 * k:
            longs.append(set()), shorts.append(set())
            continue
        order = idx[np.argsort(-score[t, idx])]
        longs.append(set(order[:k].tolist()))
        shorts.append(set(order[-k:].tolist()))
    return longs, shorts


# ---------------------------------------------------------------------------
# The study
# ---------------------------------------------------------------------------

def main() -> None:
    M, fund_end = load()
    days = M["days"]
    hold_end = min(int(fund_end), int(days[np.isfinite(M["R"]).any(1)][-1]))
    years = dc.years_of(days)
    sel = (days >= dc.us(SEL_FROM)) & (days < xs.HOLDOUT)
    fit = (years >= FIT[0]) & (years <= FIT[1])
    hold = (days >= xs.HOLDOUT) & (days <= hold_end)
    bi = list(M["syms"]).index("BTCUSDT")
    btc = np.nan_to_num(M["R"][:, bi])

    books, rows = {}, []
    for (sig, col), k, h in itertools.product(SIGNALS.items(), KS, HOLDS):
        b = run_book(M, M[f"s_{sig}"], k, h)
        name = label(sig, k, h)
        books[name] = b
        row = {"variant": name, "signal": sig, "k": k, "hold": h,
               "turnover_yr": float(b["turnover"][hold].sum() / (hold.sum() / 365)),
               "funding_ann_hold": float(b["funding"][hold].mean() * 365),
               "funding_ann_sel": float(b["funding"][sel].mean() * 365)}
        for c, v in pc.COSTS.items():
            n = net(b, v)
            row[f"sel_{c}"] = dc.sharpe(n[sel])
            row[f"hold_{c}"] = dc.sharpe(n[hold])
        n10 = net(b, pc.JUDGED)
        ph = dc.perf(n10[hold])
        row["hold_cagr"], row["hold_dd"] = ph["cagr"], ph["max_dd"]
        for y in YEARS_OOS:
            row[f"y{y}"] = dc.sharpe(n10[hold & (years == y)])
        rows.append(row)
        print(name, round(row["sel_10bps"], 2), round(row["hold_10bps"], 2), flush=True)

    pick = max(rows, key=lambda r: r["sel_10bps"])
    pname, pk, ph_ = pick["variant"], pick["k"], pick["hold"]
    P_b = books[pname]
    LV = run_book(M, M["lowvol"], pk, ph_)
    late_b = run_book(M, late(M[f"s_{pick['signal']}"]), pk, ph_)
    lg = legs(M, M[f"s_{pick['signal']}"], pk, ph_)
    per = lg.pop("per_coin")
    top = []
    for leg in ("long", "short"):
        tot = per[f"{leg}_px"] + per[f"{leg}_fund"]
        for i in np.argsort(-np.abs(per[f"{leg}_fund"]))[:6]:
            top.append({"leg": leg, "coin": str(M["syms"][i]), "funding_pct": float(per[f"{leg}_fund"][i] * 100),
                        "price_pct": float(per[f"{leg}_px"][i] * 100), "total_pct": float(tot[i] * 100)})
    fund_all = {leg: float((per[f"{leg}_fund"]).sum()) for leg in ("long", "short")}
    top6_share = {leg: float(np.sort(np.abs(per[f"{leg}_fund"]))[::-1][:6].sum() / max(abs(fund_all[leg]), 1e-12))
                  for leg in ("long", "short")}
    gap =np.abs(lg["long_px"] + lg["short_px"] + lg["long_fund"] + lg["short_fund"] - P_b["gross"] - P_b["funding"])
    assert gap.max() < 1e-12, f"leg split does not add up: {gap.max()}"
    leg_rows = []
    for y in FIT + YEARS_OOS:
        m = (years == y) & (fit | hold)
        leg_rows.append({"year": y, **{f"{x}_pct": float(lg[x][m].mean() * 365 * 100) for x in lg},
                         "costs_10bps_pct": float(-(P_b["turnover"][m] * pc.JUDGED).mean() * 365 * 100)})

    res: dict = {"generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                 "sel_from": dc.day_str(days[sel][0]), "sel_to": dc.day_str(days[sel][-1]),
                 "hold_from": dc.day_str(days[hold][0]), "hold_to": dc.day_str(days[hold][-1]),
                 "hold_days": int(hold.sum()), "rows": rows, "pick": pname, "by_cost": {}, "legs": leg_rows,
                 "top_funding": top, "top6_share": top6_share}
    trial_R = None
    for c, v in pc.COSTS.items():
        y_ = net(P_b, v)
        lv = net(LV, v)
        X = np.column_stack([lv, btc])
        coef, r2 = ols(y_[fit], X[fit])
        se = ols_se(y_[fit], X[fit])
        a, b1, b2 = (float(x) for x in coef)
        R = y_ - b1 * lv - b2 * btc
        lo, hi, above = pc.boot(R[hold])
        coef_h, r2_h = ols(y_[hold], X[hold])
        se_h = ols_se(y_[hold], X[hold])
        row = {"cost": c, "alpha_fit_ann": a * 365, "se_alpha_fit_ann": float(se[0] * 365), "b_lowvol": b1,
               "se_b_lowvol": float(se[1]), "b_btc": b2, "se_b_btc": float(se[2]), "r2_fit": r2,
               "corr_fit": float(np.corrcoef(y_[fit], lv[fit])[0, 1]),
               "corr_hold": float(np.corrcoef(y_[hold], lv[hold])[0, 1]),
               "pick_sel": dc.sharpe(y_[sel]), "pick_hold": dc.sharpe(y_[hold]),
               "lowvol_sel": dc.sharpe(lv[sel]), "lowvol_hold": dc.sharpe(lv[hold]), "btc_hold": dc.sharpe(btc[hold]),
               "R_hold": dc.sharpe(R[hold]), "R_hold_mean_ann": float(R[hold].mean() * 365),
               "boot_p05": lo, "boot_p95": hi, "boot_above0": above,
               "late_hold": dc.sharpe(net(late_b, v)[hold]),
               "refit_alpha_ann": float(coef_h[0] * 365), "refit_alpha_t": float(coef_h[0] / se_h[0]) if se_h[0] > 0 else 0.0,
               "refit_b_lowvol": float(coef_h[1]), "refit_b_btc": float(coef_h[2]), "refit_r2": r2_h}
        for y in FIT + YEARS_OOS:
            m = years == y
            row[f"R{y}"] = dc.sharpe(R[m & (fit | hold)])
            row[f"pick{y}"] = dc.sharpe(y_[m & (fit | hold)])
            row[f"lowvol{y}"] = dc.sharpe(lv[m & (fit | hold)])
        if v == pc.JUDGED:
            roll = []
            for end in np.flatnonzero(fit | hold):
                if end + 1 < ROLL or (end + 1 - ROLL) % 91:
                    continue
                sl = slice(end + 1 - ROLL, end + 1)
                cf, _ = ols(y_[sl], X[sl])
                roll.append({"to": dc.day_str(days[end]), "alpha_ann": float(cf[0] * 365),
                             "b_lowvol": float(cf[1]), "b_btc": float(cf[2])})
            row["rolling"] = roll
            trial_R = R[hold]
            res["pick_daily_hold"] = y_[hold]
        res["by_cost"][c] = row

    j = res["by_cost"]["10bps"]
    pl_ = pc.pool([r["hold_10bps"] for r in rows] + [j["R_hold"]])
    j["deflated_p"] = dc.deflated(trial_R, pl_)
    j["pick_deflated_p"] = dc.deflated(res.pop("pick_daily_hold"), pl_)
    res["pool"] = pl_

    # Legs, overlap with low vol, IC (information only).
    lp, sp = picks_today(M, M[f"s_{pick['signal']}"], pk)
    ll, sl_ = picks_today(M, M["lowvol"], pk)
    ov_l = [len(a & b) / pk for a, b, h in zip(lp, ll, hold) if h and a]
    ov_s = [len(a & b) / pk for a, b, h in zip(sp, sl_, hold) if h and a]
    res["overlap_long"] = float(np.mean(ov_l)) if ov_l else float("nan")
    res["overlap_short"] = float(np.mean(ov_s)) if ov_s else float("nan")
    ics = []
    for sig in SIGNALS:
        for lab_, m in (("selection", sel), ("holdout", hold)):
            s = M[f"s_{sig}"][m]
            y3 = M["net3"][m]
            d = np.repeat(days[m][:, None], s.shape[1], 1)
            ic = xs.daily_ic(d.ravel(), s.ravel(), y3.ravel())["ic"].to_numpy()
            ics.append({"signal": sig, "window": lab_, "ic_mean": float(np.mean(ic)) if len(ic) else float("nan"),
                        "ic_t": float(np.mean(ic) / np.std(ic) * np.sqrt(len(ic) / 3)) if len(ic) > 2 else float("nan"),
                        "days": len(ic)})
    res["ic"] = ics

    # The pick on the coins Kraken Futures lists today (not survivorship-free).
    listing = pc.kraken_listing()
    res["kraken_coins"] = len(listing)
    if listing:
        kb = run_book(M, restrict(M, M[f"s_{pick['signal']}"], set(listing)), pk, ph_)
        res["kraken_hold_10bps"] = dc.sharpe(net(kb, pc.JUDGED)[hold])
        res["kraken_sel_10bps"] = dc.sharpe(net(kb, pc.JUDGED)[sel])

    # Verdict.
    checks = {"1 holdout Sharpe above 0.5 at 10 bps and above 0 at 20 bps":
              pick["hold_10bps"] > 0.5 and pick["hold_20bps"] > 0,
              "2 positive in 2 of 2024, 2025, 2026": sum(pick[f"y{y}"] > 0 for y in YEARS_OOS) >= 2,
              "3 one day late above 0 at 10 bps": j["late_hold"] > 0,
              "4 residual above 0.3, bootstrap 5 % above 0": j["R_hold"] > 0.3 and j["boot_p05"] > 0}
    passed = all(checks.values())
    res["checks"] = checks
    res["verdict"] = "pass" if passed else ("kill" if j["R_hold"] <= 0.1 else "inconclusive")
    res["confirmed"] = passed and j["deflated_p"] > 0.95
    write(res)


def write(res: dict) -> None:
    j, pl_ = res["by_cost"]["10bps"], res["pool"]
    v = {"pass": "**Pass.** Funding carry earns beyond the low-vol book and BTC.",
         "kill": "**Kill.** Funding carry is a re-labelled low-vol bet (residual at or below 0.1).",
         "inconclusive": "**Not shown** to earn beyond low vol."}[res["verdict"]]
    md = ["# Funding carry on perpetuals: results\n",
          f"Generated {res['generated']}. Registered in `results/funding_carry_prereg.md` before the run.\n",
          f"Selection {res['sel_from']} to {res['sel_to']}, holdout {res['hold_from']} to {res['hold_to']} "
          f"({res['hold_days']} days). Books among the 100 most liquid USDT perps of each day, half the capital "
          "per side, funding paid and received, costs per unit of one-way turnover.\n",
          f"## Verdict\n\n{v} Pick: **{res['pick']}**.\n"]
    for k, ok in res["checks"].items():
        md.append(f"- {k}: {'yes' if ok else 'no'}")
    md.append(f"\nDeflated p of the residual over the pool: {j['deflated_p']:.4f}; of the pick itself: "
              f"{j['pick_deflated_p']:.4f}" + (" (confirmed)." if res["confirmed"] else "."))
    md.append("\n## All 12 books\n")
    tab = [{**r, "hold_dd_pct": r["hold_dd"] * 100, "hold_cagr_pct": r["hold_cagr"] * 100,
            "fund_hold_pct": r["funding_ann_hold"] * 100} for r in res["rows"]]
    md.append(dc.table(tab, ["variant", "sel_0bps", "sel_10bps", "hold_0bps", "hold_10bps", "hold_20bps", "hold_41bps",
                             "hold_cagr_pct", "hold_dd_pct", "y2024", "y2025", "y2026", "turnover_yr",
                             "fund_hold_pct"]))
    md.append("\n`sel_*` and `hold_*` are Sharpes (daily x sqrt 365) at that cost; CAGR, drawdown and the years at "
              "10 bps; `fund_hold_pct` is the funding the book received (+) or paid (-) a year in the holdout, "
              "both legs.\n")
    md.append("\n## The pick against the low-vol book of its shape and BTC\n")
    rows = list(res["by_cost"].values())
    md.append(dc.table(rows, ["cost", "alpha_fit_ann", "se_alpha_fit_ann", "b_lowvol", "se_b_lowvol", "b_btc",
                              "se_b_btc", "r2_fit", "corr_fit", "corr_hold"], ".3f"))
    md.append("\n")
    md.append(dc.table(rows, ["cost", "pick_sel", "lowvol_sel", "pick_hold", "lowvol_hold", "btc_hold", "late_hold",
                              "R_hold", "R_hold_mean_ann", "boot_p05", "boot_p95", "boot_above0"]))
    md.append(f"\nR = pick - b_lowvol x lowvol - b_btc x BTC with the betas fitted on 2022-2023 at each cost and frozen "
              f"(intercept kept). Bootstrap: stationary, mean block {dc.BOOT_BLOCK} days, {dc.BOOT_DRAWS} draws, seed "
              f"{pc.SEED}. `late_hold`: the pick on the previous day's scores. Judged row: 10bps.\n")
    md.append("\n## By year (Sharpe; 2022 and 2023 are the fit window)\n")
    yr = []
    for c, r in res["by_cost"].items():
        if c not in ("10bps", "41bps"):
            continue
        for y in FIT + YEARS_OOS:
            yr.append({"cost": c, "year": y, "pick": r[f"pick{y}"], "lowvol": r[f"lowvol{y}"], "R": r[f"R{y}"]})
    md.append(dc.table(yr, ["cost", "year", "pick", "lowvol", "R"]))
    md.append("\n## Where the pick's money comes from (per year, % of capital a year)\n")
    md.append(dc.table(res["legs"], ["year", "long_px_pct", "short_px_pct", "long_fund_pct", "short_fund_pct",
                                     "costs_10bps_pct"], ".1f"))
    md.append("\nPrice return and funding of each leg (funding received is positive), and the costs at 10 bps.\n")
    md.append(f"\nThe six coins with the most funding per leg in the holdout (sums of daily contributions, % of "
              f"capital; they carry {res['top6_share']['long'] * 100:.0f} % of the long leg's funding and "
              f"{res['top6_share']['short'] * 100:.0f} % of the short leg's):\n")
    md.append(dc.table(res["top_funding"], ["leg", "coin", "funding_pct", "price_pct", "total_pct"], ".1f"))
    md.append("\n## Overlap and signal skill (information only)\n")
    md.append(f"On an average holdout day the pick's fresh long list shares {res['overlap_long'] * 100:.0f} % of its "
              f"names with the low-vol book's, the short list {res['overlap_short'] * 100:.0f} %.\n")
    md.append(dc.table(res["ic"], ["signal", "window", "ic_mean", "ic_t", "days"], ".3f"))
    md.append("\nDaily Spearman IC of the score (minus funding) with the next 3 days' funding-net return over all "
              "eligible perps; t on non-overlapping 3-day blocks.\n")
    if res.get("kraken_coins"):
        md.append(f"\nRestricted to the {res['kraken_coins']} coins Kraken Futures lists today (not survivorship-free): "
                  f"selection {res['kraken_sel_10bps']:.2f}, holdout {res['kraken_hold_10bps']:.2f} at 10 bps.\n")
    md.append("\n## Refitted on the holdout (information only)\n")
    md.append(dc.table(rows, ["cost", "refit_alpha_ann", "refit_alpha_t", "refit_b_lowvol", "refit_b_btc",
                              "refit_r2"], ".3f"))
    md.append("\n## Rolling one-year betas at 10 bps (information only)\n")
    md.append(dc.table(j["rolling"], ["to", "alpha_ann", "b_lowvol", "b_btc"], ".3f"))
    md.append(f"\n## Pool\n\n{pl_['n_total']:,} trials ({pl_['hand_trials']:,} hand, {pl_['factory_trials']} factory, "
              f"{pl_['today_trials']} registered today); the best noise trial sits at an annual Sharpe of about "
              f"{pl_['sr0_annual']:.2f}.\n")
    text = "\n".join(md)
    dc.write_results(NAME, text)
    report.write(NAME, text, res)


if __name__ == "__main__":
    main()
