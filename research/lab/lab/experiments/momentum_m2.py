"""The momentum book with M2 as a loser filter. Long-only, no shorts needed.

The regime momentum book (momentum2: 28d, daily, vol 40 %, flat while BTC is
below its 200-day average) holds every coin of its 20 with positive momentum.
M2 is best at spotting coins that are about to fall. Here a coin is dropped
from the book on any day M2 ranks it in the bottom third of everything it
scored that day; the rest of the book is unchanged.

Compared over the period M2 has out-of-sample scores (2022 on), with and
without the filter, and for a few cut-offs. Every cut-off tried is counted.
"""

from __future__ import annotations

import numpy as np
import polars as pl

from .. import report
from ..data import ROOT
from ..metrics import deflated_sharpe
from .momentum2 import run
from .tsmom import DAY_US, daily_matrix, perf, rolling_mean, target_weights

CUTS = [0.0, 0.2, 1 / 3, 0.5]  # drop coins M2 ranks below this percentile (0 = no filter)


def main() -> None:
    days, close, rv, names = daily_matrix()
    sigma = np.sqrt(rolling_mean(rv, 30, 20))
    history = np.cumsum(np.isfinite(close), axis=0)
    btc = close[:, names.index("BTC")]
    ma200 = rolling_mean(btc[:, None], 200, 200)[:, 0]
    risk_on = np.nan_to_num(btc > ma200, nan=0.0).astype(bool)

    s = pl.read_parquet(ROOT / "reports" / "picks" / "scores.parquet")
    s = s.with_columns(pct=(pl.col("score").rank().over("day") - 1) / (pl.len().over("day") - 1).clip(1))
    pct = {(int(d), sym): p for d, sym, p in s.select("day", "symbol", "pct").iter_rows()}
    first = int(s["day"].min())
    window = days >= first

    rows, rets = [], {}
    for cut in CUTS:
        def fn(t: int, cut: float = cut) -> np.ndarray:
            w = target_weights(close, sigma, history, t, [28], 0.40) * (1.0 if risk_on[t] else 0.0)
            if cut > 0:
                for j, n in enumerate(names):
                    p = pct.get((int(days[t]), f"{n}USDT"))
                    if p is not None and p < cut:
                        w[j] = 0.0
            return w
        g, c, net, e = run(close, fn, 1, 200)
        name = "no filter" if cut == 0 else f"drop M2 bottom {cut * 100:.0f} %"
        rets[name] = net[window]
        rows.append({"variant": name, **perf(net[window], c[window]), "avg_exposure": float(e[window].mean())})
    sr = np.array([r["sharpe"] for r in rows]) / np.sqrt(365)
    n_obs = int(window.sum())
    for r in rows:
        r["deflated_p"] = deflated_sharpe(r["sharpe"] / np.sqrt(365), n_obs, len(rows) + 50, float(np.var(sr)))
    base = rows[0]
    best = max(rows[1:], key=lambda r: r["sharpe"])
    verdict = (f"Over {n_obs} days from 2022: without the filter Sharpe {base['sharpe']:.2f}, drawdown "
               f"{base['max_dd'] * 100:.0f} %; best filter ({best['variant']}) Sharpe {best['sharpe']:.2f}, drawdown "
               f"{best['max_dd'] * 100:.0f} %. "
               + ("The filter helps." if best["sharpe"] > base["sharpe"] + 0.1 and best["max_dd"] <= base["max_dd"] else
                  "The filter does not clearly help the 20 majors: M2's skill sits elsewhere."))
    md = ("# Momentum book with M2 as a loser filter\n\n"
          f"Regime momentum on the 20 lab coins, from {pl.from_epoch(pl.Series([first]), time_unit='us')[0]:%Y-%m-%d}. "
          "Deflated over these variants plus the 50 of the momentum rounds.\n\n"
          f"**Verdict:** {verdict}\n\n"
          + report.table(rows, ["variant", "sharpe", "cagr", "max_dd", "cost_yr", "avg_exposure", "deflated_p"]))
    report.write("momentum_m2", md, {"rows": rows, "verdict": verdict})


if __name__ == "__main__":
    main()
