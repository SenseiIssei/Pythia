"""Falsification test for cross-venue spread trading (masterplan phase 3, BREAKTHROUGH §4).

Question: does the executable edge between Kraken USD and Binance USDT (both legs
at the touch, USDT converted at Kraken's touch) ever exceed the round-trip fees?
If it rarely does, the strategy does not exist at retail size and is not built.

Fees are not in the recorded edge. At the lowest tiers a round trip costs about
Kraken taker 40 bps + Binance taker 10 bps + the USDT/USD conversion; with maker
on Kraken about 25 + 10. Rebalancing between venues (withdrawals) comes on top.
"""

from __future__ import annotations

import polars as pl

from .. import report
from ..data import live

THRESHOLDS = [10, 25, 50, 75]  # bps
FEES_TAKER = 50.0               # Kraken taker 40 + Binance taker 10
SAMPLE_S = 15


def longest_run(mask: pl.Series) -> int:
    best = cur = 0
    for v in mask:
        cur = cur + 1 if v else 0
        best = max(best, cur)
    return best


def main() -> None:
    df = (live("spread", "kraken_binance").collect()
          .with_columns(edge=pl.max_horizontal("edge_buy_kraken_bps", "edge_buy_binance_bps"))
          .sort("ts_recv_us"))
    if df.is_empty():
        print("no spread data yet")
        return
    t0, t1 = df["ts_recv_us"].min(), df["ts_recv_us"].max()
    days = (t1 - t0) / 86_400e6

    rows = []
    for (base,), g in df.group_by(["base"], maintain_order=False):
        e = g["edge"]
        row = {
            "base": base,
            "samples": g.height,
            "coverage": g.height / (days * 86400 / SAMPLE_S),
            "mid_median": g["mid_spread_bps"].median(),
            "mid_p01": g["mid_spread_bps"].quantile(0.01),
            "mid_p99": g["mid_spread_bps"].quantile(0.99),
            "edge_median": e.median(),
            "edge_p99": e.quantile(0.99),
            "edge_max": e.max(),
            "kraken_spread_bps": ((g["kraken_ask"] - g["kraken_bid"]) / g["kraken_bid"] * 1e4).median(),
            "binance_spread_bps": ((g["binance_ask"] - g["binance_bid"]) / g["binance_bid"] * 1e4).median(),
        }
        for th in THRESHOLDS:
            row[f"pct_gt_{th}"] = float((e > th).mean() * 100)
        row["longest_gt_fees_s"] = longest_run(e > FEES_TAKER) * SAMPLE_S
        rows.append(row)
    rows.sort(key=lambda r: -r["edge_p99"])

    beats = [r for r in rows if r[f"pct_gt_50"] > 0]
    verdict = (
        "No coin cleared taker fees even once. At this size and these fee tiers the cross-venue "
        "spread trade does not exist."
        if not beats else
        f"{len(beats)} coin(s) cleared taker fees at least once: "
        + ", ".join(f"{r['base']} ({r['pct_gt_50']:.3f} % of samples, longest {r['longest_gt_fees_s']} s)" for r in beats)
        + ". Whether that survives rebalancing costs and latency needs the per-event view."
    )

    md = (
        f"# Cross-venue spread, Kraken USD vs Binance USDT\n\n"
        f"{days:.1f} days of data, {df.height:,} samples, {df['base'].n_unique()} coins.\n\n"
        f"**Edge** = what you would make buying on one venue and selling on the other at the touch, "
        f"before fees, best of both directions, in bps. Taker fees for the round trip are about {FEES_TAKER:.0f} bps.\n\n"
        f"**Verdict so far:** {verdict}\n\n"
        + report.table(rows, ["base", "samples", "coverage", "mid_median", "mid_p01", "mid_p99",
                              "edge_median", "edge_p99", "edge_max",
                              "pct_gt_10", "pct_gt_25", "pct_gt_50", "pct_gt_75",
                              "longest_gt_fees_s", "kraken_spread_bps", "binance_spread_bps"])
        + "\n`pct_gt_X` = share of 15-second samples with edge above X bps.\n"
    )
    report.write("spread", md, {"days": days, "samples": df.height, "rows": rows, "verdict": verdict})


if __name__ == "__main__":
    main()
