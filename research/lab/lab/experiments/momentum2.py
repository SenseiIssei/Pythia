"""Momentum, round two: a market-regime filter and cross-sectional rotation.

Round one (tsmom.py) found long-only time-series momentum beats holding the
basket on drawdown but loses like it whenever BTC trades below its 200-day
average. Two follow-ups, both through the same gates:

A. The 16 round-one variants again, each with a regime filter: hold nothing
   while BTC closes below its 200-day average (Faber 2007; a long-standing
   rule, not one invented for this data). The filter idea came from looking at
   round one's out-of-sample regime split, so this family's evidence is
   weaker than the numbers suggest; that is why every variant tried in both
   rounds counts in the deflation below.
B. Cross-sectional rotation: each week hold the K coins with the strongest
   lookback return, if that return is positive, equal risk, with and without
   the same regime filter.

Selection per family on 2020 to 2023 only. All 50 variants from both rounds
are deflated together.
"""

from __future__ import annotations

import itertools

import numpy as np

from .. import report
from ..metrics import deflated_sharpe
from .tsmom import (COST, LOOKBACKS, MIN_HISTORY_D, REBAL, SPLIT, TARGET_VOL, DAY_US, daily_matrix, perf,
                    rolling_mean, target_weights)

XS_LOOKBACK = {"14d": 14, "28d": 28, "56d": 56}
XS_TOP = {"top 3": 3, "top 5": 5, "top 8": 8}
XS_TARGET = 0.40


def run(close: np.ndarray, weight_fn, rebal: int, start: int):
    T, N = close.shape
    ret = np.full_like(close, np.nan)
    ret[1:] = close[1:] / close[:-1] - 1
    w = np.zeros(N)
    gross, cost, net, expo = (np.zeros(T) for _ in range(4))
    for t in range(start, T - 1):
        r_next = np.nan_to_num(ret[t + 1])
        if t % rebal == 0:
            tgt = weight_fn(t)
            cost[t] = np.abs(tgt - w).sum() * COST
            w = tgt
        g = float(np.dot(w, r_next))
        gross[t + 1], net[t + 1], expo[t] = g, g - cost[t], w.sum()
        if 1 + g > 0:
            w = w * (1 + r_next) / (1 + g)
    return gross, cost, net, expo


def main() -> None:
    days, close, rv, names = daily_matrix()
    oos = days >= SPLIT
    ins = (days < SPLIT) & (days >= days[0] + 120 * DAY_US)
    sigma = np.sqrt(rolling_mean(rv, 30, 20))
    history = np.cumsum(np.isfinite(close), axis=0)
    btc = close[:, names.index("BTC")]
    ma200 = rolling_mean(btc[:, None], 200, 200)[:, 0]
    risk_on = np.nan_to_num(btc > ma200, nan=0.0).astype(bool)

    def xs_weights(t: int, L: int, K: int) -> np.ndarray:
        with np.errstate(invalid="ignore", divide="ignore"):
            score = close[t] / close[t - L] - 1
        ok = (history[t] >= MIN_HISTORY_D) & np.isfinite(score) & (score > 0) & np.isfinite(sigma[t]) & (sigma[t] > 0)
        idx = np.flatnonzero(ok)
        idx = idx[np.argsort(-score[idx])][:K]
        w = np.zeros(close.shape[1])
        if len(idx):
            w[idx] = XS_TARGET / (sigma[t, idx] * np.sqrt(365)) / K
            if w.sum() > 1:
                w /= w.sum()
        return w

    variants = []  # (family, name, gross, cost, net)
    for (lk, L), (rb, R), (tv, V), reg in itertools.product(LOOKBACKS.items(), REBAL.items(), TARGET_VOL.items(), (False, True)):
        fn = (lambda t, L=L, V=V, reg=reg: target_weights(close, sigma, history, t, L, V) * (risk_on[t] if reg else 1.0))
        g, c, n, e = run(close, fn, R, 200)
        fam = "A regime" if reg else "round one"
        variants.append((fam, f"{lk} · {rb} · vol {tv}" + (" · regime" if reg else ""), g, c, n, e))
    for (lk, L), (kk, K), reg in itertools.product(XS_LOOKBACK.items(), XS_TOP.items(), (False, True)):
        fn = (lambda t, L=L, K=K, reg=reg: xs_weights(t, L, K) * (risk_on[t] if reg else 1.0))
        g, c, n, e = run(close, fn, 7, 200)
        variants.append(("B rotation", f"rotation {lk} · {kk} · weekly" + (" · regime" if reg else ""), g, c, n, e))

    rows = []
    for fam, name, g, c, n, e in variants:
        pi, po = perf(n[ins]), perf(n[oos], c[oos])
        rows.append({"family": fam, "variant": name, "is_sharpe": pi["sharpe"], "oos_sharpe": po["sharpe"],
                     "oos_cagr": po["cagr"], "oos_max_dd": po["max_dd"], "oos_cost_yr": po["cost_yr"],
                     "avg_exposure": float(e[oos].mean())})
    n_obs = int(oos.sum())
    all_sr = np.array([r["oos_sharpe"] for r in rows]) / np.sqrt(365)
    for r in rows:
        r["deflated_p"] = deflated_sharpe(r["oos_sharpe"] / np.sqrt(365), n_obs, len(rows), float(np.var(all_sr)))

    by_name = {v[1]: v for v in variants}
    ret = np.full_like(close, np.nan)
    ret[1:] = close[1:] / close[:-1] - 1
    basket = np.array([np.nanmean(np.where(history[t - 1] >= MIN_HISTORY_D, ret[t], np.nan)) if t else 0.0
                       for t in range(len(days))])
    basket = np.nan_to_num(basket)
    b_oos = perf(basket[oos])

    picks, details = [], []
    for fam in ("A regime", "B rotation"):
        fam_rows = [r for r in rows if r["family"] == fam]
        best = max(fam_rows, key=lambda r: r["is_sharpe"])
        picks.append(best)
        _, _, g, c, n, _ = by_name[best["variant"]]
        paid = np.r_[0.0, c[:-1]]
        cost_rows = {f"{k}x": perf((g - k * paid)[oos])["sharpe"] for k in (1, 2, 3)}
        regime = {lab: perf(n[oos & m])["sharpe"] for lab, m in (("BTC above 200d", risk_on), ("BTC below 200d", ~risk_on))}
        share_pos = float(np.mean([r["oos_sharpe"] > 0 for r in fam_rows]))
        details.append({"family": fam, "pick": best["variant"], "is_sharpe": best["is_sharpe"],
                        "oos_sharpe": best["oos_sharpe"], "oos_cagr": best["oos_cagr"], "oos_max_dd": best["oos_max_dd"],
                        "deflated_p": best["deflated_p"], "sharpe_2x_cost": cost_rows["2x"],
                        "sharpe_3x_cost": cost_rows["3x"], "sharpe_btc_above": regime["BTC above 200d"],
                        "sharpe_btc_below": regime["BTC below 200d"], "family_positive_share": share_pos})

    lines = []
    for d in details:
        ok = d["deflated_p"] > 0.95 and d["sharpe_2x_cost"] > 0 and d["oos_max_dd"] < b_oos["max_dd"]
        lines.append(f"- **{d['family']}**: picked in-sample *{d['pick']}*. Out of sample Sharpe {d['oos_sharpe']:.2f}, "
                     f"{d['oos_cagr'] * 100:.1f} % a year, worst drawdown {d['oos_max_dd'] * 100:.0f} %, deflated p "
                     f"{d['deflated_p']:.2f}. {'Passes gates 1 to 6.' if ok else 'Does not pass gate 6.'}")
    md = (
        "# Momentum, round two: regime filter and rotation\n\n"
        f"Same data and costs as round one. {len(rows)} variants in total across both rounds, all deflated together. "
        f"Basket out of sample: Sharpe {b_oos['sharpe']:.2f}, drawdown {b_oos['max_dd'] * 100:.0f} %.\n\n"
        + "\n".join(lines) + "\n\n## Picks in detail\n\n"
        + report.table(details, ["family", "pick", "is_sharpe", "oos_sharpe", "oos_max_dd", "deflated_p",
                                 "sharpe_2x_cost", "sharpe_3x_cost", "sharpe_btc_above", "sharpe_btc_below",
                                 "family_positive_share"])
        + "\n## All variants, by in-sample Sharpe\n\n"
        + report.table(sorted(rows, key=lambda r: (r["family"], -r["is_sharpe"])),
                       ["family", "variant", "is_sharpe", "oos_sharpe", "oos_cagr", "oos_max_dd", "oos_cost_yr",
                        "avg_exposure", "deflated_p"])
    )
    report.write("momentum2", md, {"rows": rows, "details": details, "basket": b_oos})


if __name__ == "__main__":
    main()
