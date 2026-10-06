"""Time-series momentum, done properly. Masterplan phase 6, candidate 1.

Long-only (crypto spot cannot short): a coin is held when its own past return
over the lookback is positive, sized so each held coin contributes the same
volatility, total exposure capped at 100 % (no leverage). Rebalanced daily or
weekly; between rebalances positions drift with prices. Costs: 15 bps per unit
of one-way turnover (Binance taker 10 bps plus half-spread).

Selection is honest: 16 variants, the one with the best in-sample Sharpe
(2020 to 2023) is picked BEFORE looking at 2024 onward, and its out-of-sample
Sharpe is deflated for the 16 tries. The full out-of-sample grid is shown too,
so a lone spike stands out against its neighbours (gate 4, plateau).

Known bias: the 20 coins are today's survivors. Coins that died between 2020
and now are missing, which flatters every long strategy here, the buy-and-hold
baselines included. Compare against the baselines, not against zero.
"""

from __future__ import annotations

import itertools
from datetime import datetime, timezone

import numpy as np
import polars as pl

from .. import report
from ..data import HOUR_US, UNIVERSE, hourly
from ..metrics import deflated_sharpe

COST = 0.0015
SPLIT = int(datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp() * 1e6)
DAY_US = 24 * HOUR_US
MIN_HISTORY_D = 120
LOOKBACKS = {"14d": [14], "28d": [28], "56d": [56], "blend 7-112d": [7, 14, 28, 56, 112]}
REBAL = {"daily": 1, "weekly": 7}
TARGET_VOL = {"40%": 0.40, "80%": 0.80}


def daily_matrix() -> tuple[np.ndarray, np.ndarray, np.ndarray, list[str]]:
    frames = []
    for b in UNIVERSE:
        h = hourly(f"{b}USDT")
        d = (h.with_columns(day=(pl.col("ts_us") // DAY_US) * DAY_US)
             .group_by("day").agg(close=pl.col("close").last(), rv=pl.col("rv").sum(), n=pl.len())
             .filter(pl.col("n") >= 20).select("day", pl.col("close").alias(b), pl.col("rv").alias(f"rv_{b}")))
        frames.append(d)
    m = frames[0]
    for f in frames[1:]:
        m = m.join(f, on="day", how="full", coalesce=True)
    m = m.sort("day")
    days = m["day"].to_numpy()
    close = m.select(UNIVERSE).to_numpy().astype(float)
    rv = m.select([f"rv_{b}" for b in UNIVERSE]).to_numpy().astype(float)
    return days, close, rv, UNIVERSE


def rolling_mean(a: np.ndarray, w: int, min_obs: int) -> np.ndarray:
    """Column-wise trailing mean over w rows, ignoring NaN, NaN where fewer than min_obs values."""
    v, c = np.nan_to_num(a), np.isfinite(a).astype(float)
    cs, cc = np.cumsum(v, 0), np.cumsum(c, 0)
    pad = np.zeros((w, a.shape[1]))
    s = cs - np.vstack([pad, cs[:-w]])
    n = cc - np.vstack([pad, cc[:-w]])
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(n >= min_obs, s / np.maximum(n, 1), np.nan)


def backtest(close: np.ndarray, rv: np.ndarray, lookbacks: list[int], rebal: int, target: float):
    T, N = close.shape
    ret = np.full_like(close, np.nan)
    ret[1:] = close[1:] / close[:-1] - 1
    # ex-ante daily vol from the last 30 days of realised variance
    sigma = np.sqrt(rolling_mean(rv, 30, 20))
    history = np.cumsum(np.isfinite(close), axis=0)
    w = np.zeros(N)
    gross, cost, net, expo, turnover = (np.zeros(T) for _ in range(5))
    for t in range(max(lookbacks) + 1, T - 1):
        r_next = np.nan_to_num(ret[t + 1])
        if (t % rebal) == 0:
            sig = np.zeros(N)
            for L in lookbacks:
                past = close[t] / close[t - L] - 1
                sig += np.where(np.isfinite(past) & (past > 0), 1.0, 0.0)
            sig /= len(lookbacks)
            ok = (history[t] >= MIN_HISTORY_D) & np.isfinite(sigma[t]) & (sigma[t] > 0) & np.isfinite(close[t])
            n_ok = max(int(ok.sum()), 1)
            tgt = np.where(ok, sig * (target / (sigma[t] * np.sqrt(365))) / n_ok, 0.0)
            tgt = np.nan_to_num(tgt)
            if tgt.sum() > 1.0:
                tgt /= tgt.sum()
            tv = np.abs(tgt - w).sum()
            turnover[t] = tv
            cost[t] = tv * COST
            w = tgt
        g = float(np.dot(w, r_next))
        gross[t + 1] = g
        net[t + 1] = g - cost[t]
        expo[t] = w.sum()
        w = w * (1 + r_next) / (1 + g) if (1 + g) > 0 else w
    return gross, cost, net, expo, turnover


def perf(r: np.ndarray, cost: np.ndarray | None = None) -> dict:
    r = r[np.isfinite(r)]
    eq = np.cumprod(1 + r)
    dd = 1 - eq / np.maximum.accumulate(eq)
    years = len(r) / 365
    out = {"cagr": float(eq[-1] ** (1 / years) - 1) if years > 0 else None,
           "vol": float(r.std() * np.sqrt(365)),
           "sharpe": float(r.mean() / r.std() * np.sqrt(365)) if r.std() > 0 else 0.0,
           "max_dd": float(dd.max()), "days": int(len(r))}
    if cost is not None:
        out["cost_yr"] = float(cost.sum() / years)
    return out


def main() -> None:
    days, close, rv, names = daily_matrix()
    oos = days >= SPLIT
    ins = (days < SPLIT) & (days >= days[0] + 120 * DAY_US)
    ret = np.full_like(close, np.nan)
    ret[1:] = close[1:] / close[:-1] - 1

    # Baselines
    history = np.cumsum(np.isfinite(close), axis=0)

    def ew_bh():
        out = np.zeros(len(days))
        for t in range(1, len(days)):
            hist = history[t - 1] >= MIN_HISTORY_D
            r = ret[t][hist & np.isfinite(ret[t])]
            out[t] = r.mean() if len(r) else 0.0
        return out
    base_ew = ew_bh()
    base_btc = np.nan_to_num(ret[:, names.index("BTC")])

    rows, results = [], {}
    for (lk, L), (rb, R), (tv, V) in itertools.product(LOOKBACKS.items(), REBAL.items(), TARGET_VOL.items()):
        g, c, n, e, to = backtest(close, rv, L, R, V)
        key = f"{lk} · {rb} · vol {tv}"
        results[key] = (g, c, n, e, to)
        pi, po = perf(n[ins]), perf(n[oos], c[oos])
        gross_oos = perf(g[oos])
        rows.append({"variant": key, "is_sharpe": pi["sharpe"], "oos_sharpe": po["sharpe"],
                     "oos_cagr": po["cagr"], "oos_max_dd": po["max_dd"], "oos_cost_yr": po["cost_yr"],
                     "oos_gross_sharpe": gross_oos["sharpe"], "avg_exposure": float(e[oos].mean()),
                     "turnover_yr": float(to[oos].sum() / (oos.sum() / 365))})
    chosen = max(rows, key=lambda r: r["is_sharpe"])
    oos_sr = np.array([r["oos_sharpe"] for r in rows]) / np.sqrt(365)
    n_obs = int(oos.sum())
    dsr = deflated_sharpe(chosen["oos_sharpe"] / np.sqrt(365), n_obs, len(rows), float(np.var(oos_sr)))
    pos_share = float(np.mean([r["oos_sharpe"] > 0 for r in rows]))
    b_ew, b_btc = perf(base_ew[oos]), perf(base_btc[oos])
    b_ew_is = perf(base_ew[ins])

    beats = chosen["oos_sharpe"] > b_ew["sharpe"] and chosen["oos_max_dd"] < b_ew["max_dd"]
    verdict = (
        f"Picked on 2020 to 2023 data: **{chosen['variant']}** (in-sample Sharpe {chosen['is_sharpe']:.2f}). "
        f"From 2024 on it made Sharpe {chosen['oos_sharpe']:.2f}, {chosen['oos_cagr'] * 100:.1f} % a year, "
        f"worst drawdown {chosen['oos_max_dd'] * 100:.0f} %, costs {chosen['oos_cost_yr'] * 100:.1f} % a year. "
        f"Equal-weight buy-and-hold of the same coins: Sharpe {b_ew['sharpe']:.2f}, drawdown {b_ew['max_dd'] * 100:.0f} %. "
        f"BTC alone: Sharpe {b_btc['sharpe']:.2f}, drawdown {b_btc['max_dd'] * 100:.0f} %. "
        f"Deflated for 16 variants the probability of real skill is {dsr:.2f} (needs > 0.95). "
        f"{pos_share * 100:.0f} % of all variants are positive out of sample. "
        + ("It beats holding the basket on both Sharpe and drawdown: a candidate for the paper forward test."
           if beats and dsr > 0.95 else
           "Not good enough for live money yet." if not beats else
           "Better than the basket, but the evidence is not strong enough after deflation.")
    )
    md = (
        "# Time-series momentum, long-only, vol-scaled\n\n"
        f"{len(names)} coins, daily bars, in-sample to 2023-12-31, out-of-sample {n_obs} days from 2024-01-01. "
        f"Costs {COST * 1e4:.0f} bps per unit turnover. Survivorship bias flatters every long strategy here, so "
        "compare with the baselines.\n\n"
        f"**Verdict:** {verdict}\n\n"
        "## Baselines\n\n"
        + report.table([{"baseline": "equal-weight basket", "is_sharpe": b_ew_is["sharpe"], **{f"oos_{k}": v for k, v in b_ew.items()}},
                        {"baseline": "BTC buy and hold", "is_sharpe": perf(base_btc[ins])["sharpe"], **{f"oos_{k}": v for k, v in b_btc.items()}}],
                       ["baseline", "is_sharpe", "oos_sharpe", "oos_cagr", "oos_max_dd", "oos_vol"])
        + "\n## All 16 variants\n\n"
        + report.table(sorted(rows, key=lambda r: -r["is_sharpe"]),
                       ["variant", "is_sharpe", "oos_sharpe", "oos_gross_sharpe", "oos_cagr", "oos_max_dd",
                        "oos_cost_yr", "avg_exposure", "turnover_yr"])
    )
    report.write("tsmom", md, {"rows": rows, "chosen": chosen, "deflated_p": dsr,
                               "baseline_ew": b_ew, "baseline_btc": b_btc, "verdict": verdict})


if __name__ == "__main__":
    main()
