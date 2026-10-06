"""Gate 7 tracker: does the paper book behave like its backtest?

Runs right after the paper trader. For every book it lines the paper journal
up against the backtest of the same variant over the same days and reports:
  return, paper vs backtest, and the correlation of their daily returns
  costs, what the paper fills paid vs what the backtest assumed
  progress towards gate 7 (30 days and 30 rebalances)

A paper book that drifts away from its backtest means the backtest was wrong
about something (costs, timing, fills), and that has to be understood before
any real money follows it.

Report: <data>/reports/paper_review/latest.md
"""

from __future__ import annotations

import csv
from datetime import datetime, timezone

import numpy as np

from .. import report
from ..data import ROOT
from ..experiments.momentum2 import run
from ..experiments.tsmom import DAY_US, daily_matrix, rolling_mean, target_weights
from .tsmom import BOOKS, START_EQUITY

MIN_DAYS, MIN_REBALANCES = 30, 30


def journal(book: str) -> list[dict]:
    p = ROOT / "paper" / book / "journal.csv"
    if not p.exists():
        return []
    with p.open() as fh:
        return list(csv.DictReader(fh))


def main() -> None:
    days, close, rv, names = daily_matrix()
    sigma = np.sqrt(rolling_mean(rv, 30, 20))
    history = np.cumsum(np.isfinite(close), axis=0)
    btc = close[:, names.index("BTC")]
    ma200 = rolling_mean(btc[:, None], 200, 200)[:, 0]
    risk_on = np.nan_to_num(btc > ma200, nan=0.0).astype(bool)
    day_index = {int(d): i for i, d in enumerate(days)}

    rows, lines = [], []
    for book, cfg in BOOKS.items():
        j = journal(book)
        if not j:
            continue
        fn = (lambda t, cfg=cfg: target_weights(close, sigma, history, t, cfg["lookbacks"], cfg["target"])
              * (risk_on[t] if cfg["regime"] else 1.0))
        _, _, net, _ = run(close, fn, 1, 200)

        equity = np.array([float(r["equity"]) for r in j])
        paper_ret = np.diff(np.r_[START_EQUITY, equity]) / np.r_[START_EQUITY, equity[:-1]]
        # A journal row dated D marks from the previous run to D 04:00 UTC; the
        # nearest backtest day is the close-to-close return ending at D 00:00.
        bt_ret = []
        for r in j:
            d = int(datetime.strptime(r["date"], "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1e6)
            i = day_index.get(d - DAY_US)
            bt_ret.append(float(net[i]) if i is not None and i < len(net) else np.nan)
        bt_ret = np.array(bt_ret)
        rebalances = sum(1 for r in j if float(r["turnover"]) > 0.01)
        paper_cost = sum(float(r["paper_cost_bps"]) for r in j)
        model_cost = sum(float(r["model_cost_bps"]) for r in j)
        ok = np.isfinite(bt_ret)
        corr = float(np.corrcoef(paper_ret[ok][1:], bt_ret[ok][1:])[0, 1]) if ok.sum() >= 11 else None
        done = len(j) >= MIN_DAYS and rebalances >= MIN_REBALANCES
        row = {
            "book": book, "since": j[0]["date"], "days": len(j), "rebalances": rebalances,
            "paper_return_pct": (equity[-1] / START_EQUITY - 1) * 100,
            "backtest_return_pct": (np.prod(1 + np.nan_to_num(bt_ret[1:])) - 1) * 100,
            "daily_corr": corr,
            "cost_ratio": paper_cost / model_cost if model_cost > 0 else None,
            "gate7": "ready to judge" if done else f"{len(j)}/{MIN_DAYS} days, {rebalances}/{MIN_REBALANCES} rebalances",
        }
        rows.append(row)
        verdict = []
        if row["cost_ratio"] is not None:
            verdict.append(f"paper fills cost {row['cost_ratio']:.2f}x what the backtest assumes"
                           + (" (fine)" if row["cost_ratio"] <= 1.5 else " (too much: the cost model is optimistic)"))
        if corr is not None:
            verdict.append(f"daily returns correlate {corr:.2f} with the backtest"
                           + (" (fine)" if corr >= 0.7 else " (low: find out why before going further)"))
        lines.append(f"- **{book}** ({cfg['variant']}), since {row['since']}: paper "
                     f"{row['paper_return_pct']:+.2f} %, backtest {row['backtest_return_pct']:+.2f} %. "
                     + ("; ".join(verdict) + ". " if verdict else "Too early for comparisons. ")
                     + f"Gate 7: {row['gate7']}.")

    md = ("# Paper forward tests against their backtests\n\n"
          "Gate 7 needs at least 30 days and 30 rebalances, paper costs within 1.5x of the model "
          "and paper returns that move with the backtest.\n\n" + "\n".join(lines) + "\n\n"
          + report.table(rows, ["book", "since", "days", "rebalances", "paper_return_pct", "backtest_return_pct",
                                "daily_corr", "cost_ratio", "gate7"]))
    report.write("paper_review", md, {"books": rows})


if __name__ == "__main__":
    main()
