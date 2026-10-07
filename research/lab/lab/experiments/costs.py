"""Calibrate the book half of config/costs.json from recorded order books (NEXT-STEPS §2).

The shipped cost numbers are guesses from typical quoted spreads. The recorder has
kept the 20 best levels of every Kraken and Binance book every 5 s since
2026-09-30, which is enough to measure three of the model's fields per coin:

  halfSpreadBps  mean of (ask - bid) / mid / 2 over the sample. The mean, not the
                 median: a cost model prices the average order, and spreads are
                 skewed, so the median would flatter it.
  defaultDepth   median notional (quote currency) on the 20 best levels of one
                 side, averaged over both sides. This is the definition the engine
                 must use when it later passes a live book in, because a depth20
                 feed reports exactly this number.
  impactCoeff    the square-root law impact = c * sqrt(N / depth). Market orders of
                 5 to 50 % of the median depth are walked through every sampled
                 book, both sides; impact is the walk's cost against the mid minus
                 the half-spread. c is the least-squares fit through the origin of
                 the mean impact against sqrt(N / depth).

Fees are not touched: they depend on the account's tier, not on the book.
One snapshot per minute per coin is used; neighbouring 5 s snapshots are nearly
the same book and would only add weight, not information.
"""

from __future__ import annotations

import numpy as np
import polars as pl

from .. import report
from ..data import UNIVERSE, live

SAMPLE_US = 60_000_000
FRACTIONS = [0.05, 0.10, 0.25, 0.50]  # order size as a share of the median depth
VENUES = {
    "kraken": ("kraken", lambda b: f"{b}/USD"),
    "binance": ("binance", lambda b: f"{b}USDT"),
}


def load(source: str) -> pl.DataFrame:
    """One snapshot per minute per symbol, across every recorded day."""
    # Snapshots come every 5 s, so the first 5 s of each minute hold about one per
    # symbol. Filtering on that before anything else keeps the list columns of the
    # other eleven out of memory.
    return (live(source, "book20")
            .select("ts_recv_us", "symbol", "bid_px", "bid_qty", "ask_px", "ask_qty")
            .filter(pl.col("ts_recv_us") % SAMPLE_US < 5_000_000)
            .with_columns(minute=pl.col("ts_recv_us") // SAMPLE_US)
            .unique(["symbol", "minute"], keep="first", maintain_order=True)
            .sort("symbol", "ts_recv_us")
            .collect(engine="streaming"))


def matrix(s: pl.Series) -> np.ndarray:
    """List column -> (n, 20) array, short books padded with NaN."""
    rows = s.to_list()
    width = max((len(r) for r in rows), default=0)
    out = np.full((len(rows), width), np.nan)
    for i, r in enumerate(rows):
        out[i, :len(r)] = r
    return out


def walk(px: np.ndarray, qty: np.ndarray, notional: float) -> np.ndarray:
    """Average fill price of a market order of `notional` quote currency taking
    these levels, best first. NaN where the 20 levels cannot fill it."""
    level = np.nan_to_num(px * qty)
    before = np.cumsum(level, axis=1) - level
    take = np.clip(notional - before, 0.0, level)            # quote spent per level
    coins = np.where(take > 0, take / np.where(px > 0, px, np.nan), 0.0).sum(axis=1)
    filled = take.sum(axis=1)
    return np.where(filled >= notional * (1 - 1e-9), filled / coins, np.nan)


def measure(df: pl.DataFrame) -> dict | None:
    bp, bq, ap, aq = (matrix(df[c]) for c in ("bid_px", "bid_qty", "ask_px", "ask_qty"))
    ok = (bp[:, 0] > 0) & (ap[:, 0] > bp[:, 0])
    bp, bq, ap, aq = bp[ok], bq[ok], ap[ok], aq[ok]
    if len(bp) < 1000:
        return None
    mid = (bp[:, 0] + ap[:, 0]) / 2
    half = (ap[:, 0] - bp[:, 0]) / mid / 2 * 1e4
    depth_side = (np.nansum(bp * bq, axis=1) + np.nansum(ap * aq, axis=1)) / 2
    depth = float(np.median(depth_side))

    xs, ys, unfilled = [], [], {}
    for f in FRACTIONS:
        n = f * depth
        buy = (walk(ap, aq, n) / mid - 1) * 1e4 - half
        sell = (1 - walk(bp, bq, n) / mid) * 1e4 - half
        imp = np.concatenate([buy, sell])
        unfilled[f] = float(np.isnan(imp).mean())
        imp = imp[~np.isnan(imp)]
        # One broken snapshot must not move the fit; the top 0.5 % is clipped, not dropped.
        imp = np.minimum(imp, np.quantile(imp, 0.995))
        xs.append(np.sqrt(f))
        ys.append(float(imp.mean()))
    x, y = np.array(xs), np.array(ys)
    coeff = float((x * y).sum() / (x * x).sum())
    fit_err = float(np.abs(coeff * x - y).max())

    return {
        "samples": int(len(bp)),
        "halfSpreadBps": float(half.mean()),
        "half_median": float(np.median(half)),
        "half_p90": float(np.quantile(half, 0.90)),
        "defaultDepth": depth,
        "depth_p10": float(np.quantile(depth_side, 0.10)),
        "impactCoeff": coeff,
        "fit_err_bps": fit_err,
        "impact_at": dict(zip(FRACTIONS, ys)),
        "unfilled_at_50pct": unfilled[0.50],
    }


def main() -> None:
    out: dict[str, dict] = {}
    span = {}
    for venue, (source, sym) in VENUES.items():
        df = load(source)
        if df.is_empty():
            continue
        span[venue] = (df["ts_recv_us"].max() - df["ts_recv_us"].min()) / 86_400e6
        out[venue] = {}
        for base in UNIVERSE:
            m = measure(df.filter(pl.col("symbol") == sym(base)))
            if m:
                out[venue][base] = m

    md = ["# Cost model calibration from recorded books\n",
          "What a taker actually pays against the mid on Kraken and Binance spot, measured, "
          "next to what `config/costs.json` assumes. Fees are not part of this; they come from "
          "the account tier.\n",
          "`halfSpreadBps` is the mean half-spread (what one aggressive side pays to the mid), "
          "`defaultDepth` the median notional on the 20 best levels of one side, `impactCoeff` "
          "the extra bps when an order is as large as that depth (square-root law, fitted on "
          "orders of 5 to 50 % of it). `fit_err_bps` is the worst gap between the fitted curve "
          "and the measured mean impact; small means the square-root law describes this book.\n"]
    for venue, rows in out.items():
        md.append(f"\n## {venue}, {span[venue]:.1f} days, one book per minute\n")
        table = [{"base": b, **{k: v for k, v in m.items() if k != "impact_at"},
                  **{f"impact_{int(f * 100)}pct": v for f, v in m["impact_at"].items()}}
                 for b, m in rows.items()]
        md.append(report.table(table, [
            "base", "samples", "halfSpreadBps", "half_median", "half_p90", "defaultDepth",
            "depth_p10", "impactCoeff", "fit_err_bps", "impact_5pct", "impact_25pct",
            "impact_50pct", "unfilled_at_50pct"]))
    md.append("\nThe numbers go into `config/costs.json` as per-symbol overrides (the `calibrated` "
              "block of the json), spread and impact to three significant figures, depth to two. "
              "Impact beyond the 20 recorded levels is the square-root law extrapolated, not "
              "measured; at Pythia's order sizes no order gets near that.\n")

    def sig(x: float, n: int) -> float:
        return float(f"{x:.{n}g}")

    calibrated = {
        venue: {b: {"halfSpreadBps": sig(m["halfSpreadBps"], 3),
                    "impactCoeff": sig(m["impactCoeff"], 3),
                    "defaultDepth": int(sig(m["defaultDepth"], 2))}
                for b, m in rows.items()}
        for venue, rows in out.items()
    }
    report.write("costs", "".join(md), {"span_days": span, "measured": out, "calibrated": calibrated})


if __name__ == "__main__":
    main()
