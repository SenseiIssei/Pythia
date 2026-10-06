"""Funding carry, observation only. Is it worth building perpetuals support for?

Trade: buy the coin spot and short the same amount of the USD-M perpetual. Price
moves cancel; what is left is the funding the shorts receive (or pay). With no
leverage, half the capital buys spot and half margins the short, so the return
on capital is half the funding on the notional.

Rule: at each funding time, hold the pair on a coin while its average funding
over the last N periods is above a threshold, equal capital across held coins.
Costs per unit of notional: spot taker 10 bps + perp taker 5 bps + half-spreads,
about 18 bps to open both legs and 18 to close.

Not modelled, and all against the strategy: basis moves between spot and perp
while the pair is open, the margin needed to survive a squeeze on the short
leg, and exchange risk from holding both legs on one venue. Treat any result
here as an upper bound.
"""

from __future__ import annotations

import itertools
from datetime import datetime, timezone

import numpy as np
import polars as pl

from .. import report
from ..data import UNIVERSE, funding
from ..metrics import deflated_sharpe

SPLIT = int(datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp() * 1e6)
LEG_COST = 0.0018          # per unit notional, opening or closing both legs
WINDOW = {"1 day": 3, "7 days": 21, "21 days": 63}
THRESH_APR = {"0 %": 0.0, "5 %": 0.05, "10 %": 0.10, "20 %": 0.20}


def matrix() -> tuple[np.ndarray, np.ndarray, list[str]]:
    frames = []
    for b in UNIVERSE:
        f = funding(b)
        if f.is_empty():
            continue
        # 8h grid; coins on 4h intervals are summed into the 8h slot they fall in
        f = (f.with_columns(slot=(pl.col("funding_time_us") // (8 * 3600 * 10**6)) * (8 * 3600 * 10**6))
             .group_by("slot").agg(pl.col("funding_rate").sum().alias(b)))
        frames.append(f)
    m = frames[0]
    for f in frames[1:]:
        m = m.join(f, on="slot", how="full", coalesce=True)
    m = m.sort("slot")
    names = [c for c in m.columns if c != "slot"]
    return m["slot"].to_numpy(), m.select(names).to_numpy().astype(float), names


def backtest(rate: np.ndarray, window: int, thresh_apr: float) -> tuple[np.ndarray, np.ndarray]:
    T, N = rate.shape
    per_slot_thresh = thresh_apr / (3 * 365)
    held = np.zeros(N, dtype=bool)
    ret, invested = np.zeros(T), np.zeros(T)
    filled = np.nan_to_num(rate)
    csum = np.cumsum(filled, axis=0)
    cnt = np.cumsum(np.isfinite(rate), axis=0)
    for t in range(window, T - 1):
        n = cnt[t] - cnt[t - window]
        avg = np.where(n >= window * 0.8, (csum[t] - csum[t - window]) / np.maximum(n, 1), np.nan)
        want = np.isfinite(avg) & (avg > per_slot_thresh) & np.isfinite(rate[t + 1])
        k_old, k_new = held.sum(), want.sum()
        w_old = held / k_old if k_old else np.zeros(N)
        w_new = want / k_new if k_new else np.zeros(N)
        # notional per unit capital is half the weight; turnover in notional
        turnover = np.abs(w_new - w_old).sum() * 0.5
        funding_earned = 0.5 * np.dot(w_new, np.nan_to_num(rate[t + 1]))
        ret[t + 1] = funding_earned - turnover * LEG_COST
        invested[t + 1] = 1.0 if k_new else 0.0
        held = want
    return ret, invested


def perf(r: np.ndarray) -> dict:
    eq = np.cumprod(1 + r)
    dd = 1 - eq / np.maximum.accumulate(eq)
    per_year = 3 * 365
    return {"apr": float(r.mean() * per_year), "sharpe": float(r.mean() / r.std() * np.sqrt(per_year)) if r.std() else 0.0,
            "max_dd": float(dd.max()), "worst_slot_bps": float(r.min() * 1e4)}


def main() -> None:
    slots, rate, names = matrix()
    oos, ins = slots >= SPLIT, slots < SPLIT
    rows, rets = [], {}
    for (wk, W), (tk, th) in itertools.product(WINDOW.items(), THRESH_APR.items()):
        r, inv = backtest(rate, W, th)
        key = f"avg {wk} > {tk} a year"
        rets[key] = r
        pi, po = perf(r[ins]), perf(r[oos])
        rows.append({"variant": key, "is_apr": pi["apr"], "is_sharpe": pi["sharpe"], "oos_apr": po["apr"],
                     "oos_sharpe": po["sharpe"], "oos_max_dd": po["max_dd"], "oos_worst_slot_bps": po["worst_slot_bps"],
                     "oos_invested": float(inv[oos].mean())})
    chosen = max(rows, key=lambda r: r["is_sharpe"])
    n_obs = int(oos.sum())
    sr = np.array([r["oos_sharpe"] for r in rows]) / np.sqrt(3 * 365)
    dsr = deflated_sharpe(chosen["oos_sharpe"] / np.sqrt(3 * 365), n_obs, len(rows), float(np.var(sr)))
    raw = np.nanmean(rate[oos], axis=1) * 3 * 365
    by_year = (pl.DataFrame({"slot": slots, "r": rets[chosen["variant"]]})
               .with_columns(year=pl.from_epoch("slot", time_unit="us").dt.year())
               .group_by("year").agg(apr=pl.col("r").mean() * 3 * 365, invested=(pl.col("r") != 0).mean())
               .sort("year").to_dicts())
    verdict = (
        f"Picked in-sample: *{chosen['variant']}*. From 2024 on it earned {chosen['oos_apr'] * 100:.1f} % a year on capital "
        f"(Sharpe {chosen['oos_sharpe']:.1f}, worst drawdown {chosen['oos_max_dd'] * 100:.1f} %, invested "
        f"{chosen['oos_invested'] * 100:.0f} % of the time), deflated p {dsr:.2f}. The average funding across the "
        f"20 perps out of sample was {np.nanmean(raw) * 100:.1f} % a year on notional. "
        + ("Worth building perpetuals for, with the margin and basis risk handled first."
           if chosen["oos_apr"] > 0.05 and dsr > 0.95 else
           "Not worth building perpetuals for yet: after costs the yield is too thin for the risks not modelled here.")
    )
    md = (
        "# Funding carry: spot long, perp short\n\n"
        "Binance USD-M funding since 2020, 8-hour slots, returns on capital without leverage, costs included. "
        "Basis moves, margin calls and exchange risk are not modelled; read every number as an upper bound.\n\n"
        f"**Verdict:** {verdict}\n\n## Chosen variant by year\n\n"
        + report.table(by_year, ["year", "apr", "invested"])
        + "\n## All variants\n\n"
        + report.table(sorted(rows, key=lambda r: -r["is_sharpe"]),
                       ["variant", "is_apr", "is_sharpe", "oos_apr", "oos_sharpe", "oos_max_dd",
                        "oos_worst_slot_bps", "oos_invested"])
    )
    report.write("carry", md, {"rows": rows, "chosen": chosen, "deflated_p": dsr, "by_year": by_year})


if __name__ == "__main__":
    main()
