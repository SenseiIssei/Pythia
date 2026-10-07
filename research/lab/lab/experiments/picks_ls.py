"""M2 market-neutral: long the best picks, short the worst, on perpetuals.

M2 ranks coins well (Rank-IC 0.14, monotonic deciles) but most of its skill
is in spotting losers, and crypto spot cannot short. This asks whether that
skill survives a realistic short book on Binance USD-M perpetuals:

  universe  on each rebalance day, the coins M2 scored that also had a live
            USDT perpetual that day, cut to the N most liquid perps by 28-day
            volume (a short you cannot fill does not count)
  book      long the top k, short the bottom k, equal weight, half the capital
            on each side (gross 1x, no leverage), rebalanced every 7 days
  returns   the perps' own 7-day returns (basis included); a perp delisted
            inside the week settles at its last close
  funding   longs pay positive funding, shorts receive it (and the reverse);
            summed over the holding week from the real funding history
  costs     10 bps per unit of one-way turnover (5 bps taker + half-spread on
            liquid perps), both legs

Out of sample from 2022 (M2's own walk-forward scores). Every variant tried
is deflated together. Not modelled: margin calls on a short squeeze inside
the week, and exchange risk from holding everything on one venue.

Also: M2 as a filter on the momentum book. Coins M2 ranks in the bottom
third of the whole universe that day are dropped from the 20-coin momentum
targets. Long-only, so it can use the loser-spotting without any shorts.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import numpy as np
import polars as pl

from .. import report
from ..data import HOUR_US, ROOT
from ..metrics import deflated_sharpe

DAY_US = 24 * HOUR_US
HORIZON = 7
COST = 0.0010
KS = [5, 10]
NS = [50, 100]


def perp_base(symbol: str) -> str:
    base = symbol[:-4]
    for p in ("1000000", "1000", "1M"):
        if base.startswith(p) and len(base) > len(p):
            return base[len(p):]
    return base


def perp_panel() -> pl.DataFrame:
    perps = json.loads((ROOT / "hist" / "um_universe.json").read_text())
    frames = []
    for s in perps:
        kd = ROOT / "hist" / "binance_um" / "klines_1d" / f"symbol={s}"
        files = sorted(kd.glob("*.parquet"))
        if not files:
            continue
        k = (pl.concat([pl.read_parquet(f) for f in files], how="vertical_relaxed")
             .unique("open_time_us").sort("open_time_us")
             .select(day=(pl.col("open_time_us") // DAY_US) * DAY_US, close="close", qv="quote_volume"))
        fd = ROOT / "hist" / "binance_um" / "funding" / f"symbol={s}"
        ffiles = sorted(fd.glob("*.parquet"))
        if ffiles:
            fu = (pl.concat([pl.read_parquet(f) for f in ffiles], how="vertical_relaxed")
                  .unique("funding_time_us")
                  .with_columns(day=(pl.col("funding_time_us") // DAY_US) * DAY_US)
                  .group_by("day").agg(funding=pl.col("funding_rate").sum()))
            k = k.join(fu, on="day", how="left")
        else:
            k = k.with_columns(funding=pl.lit(0.0))
        k = k.with_columns(pl.col("funding").fill_null(0.0)).sort("day")
        lc = pl.col("close").log()
        last_day = k["day"][-1]
        delisted = last_day < datetime.now(timezone.utc).timestamp() * 1e6 - 3 * DAY_US
        k = k.with_columns(
            # Funding paid by a long over the next HORIZON days (days d+1 .. d+HORIZON).
            fund_fwd=pl.col("funding").shift(-1).rolling_sum(HORIZON).shift(-(HORIZON - 1)),
            # What holding it cost or paid over the last three days: known when deciding.
            fund_past=pl.col("funding").rolling_sum(3, min_samples=1),
            adv28=pl.col("qv").rolling_mean(28),
        )
        # Exactly HORIZON calendar days ahead, not HORIZON rows.
        ahead = k.select(day=pl.col("day") - HORIZON * DAY_US, close_ahead="close")
        k = k.join(ahead, on="day", how="left").with_columns(fwd=pl.col("close_ahead").log() - lc).drop("close_ahead")
        if delisted:
            last = float(np.log(k["close"][-1]))
            k = k.with_columns(fwd=pl.when(pl.col("fwd").is_null()).then(pl.lit(last) - lc).otherwise(pl.col("fwd")),
                               fund_fwd=pl.col("fund_fwd").fill_null(0.0))
        frames.append(k.with_columns(base=pl.lit(perp_base(s)), perp=pl.lit(s)))
    return pl.concat(frames, how="vertical_relaxed")


def perf(r: np.ndarray) -> dict:
    py = 365 / HORIZON
    eq = np.cumprod(1 + r)
    return {"periods": len(r), "cagr": float(eq[-1] ** (py / len(r)) - 1),
            "sharpe": float(r.mean() / r.std() * np.sqrt(py)) if r.std() > 0 else 0.0,
            "max_dd": float((1 - eq / np.maximum.accumulate(eq)).max())}


def long_short(df: pl.DataFrame, k: int, n: int, cost: float = COST,
               paying_shorts: bool = True) -> tuple[np.ndarray, dict]:
    """`paying_shorts=False` skips short candidates whose funding over the last
    three days was negative: there the shorts pay the longs, so a crowded short
    hands back in funding what it makes in price."""
    days = sorted(df["day"].unique().to_list())[::HORIZON]
    rets, legs = [], {"long": [], "short": [], "funding": []}
    prev_l, prev_s = set(), set()
    for d in days:
        g = df.filter(pl.col("day") == d).sort("adv28", descending=True).head(n)
        g = g.sort("score", descending=True)
        lo = g.head(k)
        pool = g.tail(max(g.height - k, 0)) if paying_shorts else g.tail(max(g.height - k, 0)).filter(pl.col("fund_past") >= 0)
        if g.height < 2 * k or pool.height < k:
            # No book this week: flat, which still counts as a week (skipping it would flatter the Sharpe).
            rets.append(-(len(prev_l) + len(prev_s)) * 0.5 / k * cost if prev_l else 0.0)
            prev_l, prev_s = set(), set()
            continue
        sh = pool.tail(k)
        r_long = float(np.mean(np.expm1(lo["fwd"].to_numpy())))
        r_short = float(-np.mean(np.expm1(sh["fwd"].to_numpy())))
        f_long = -float(np.mean(lo["fund_fwd"].to_numpy()))   # longs pay positive funding
        f_short = float(np.mean(sh["fund_fwd"].to_numpy()))   # shorts receive it
        L, S = set(lo["perp"].to_list()), set(sh["perp"].to_list())
        # Each name carries 0.5 / k of capital; every name entering or leaving a side trades that much.
        traded = (len(L ^ prev_l) + len(S ^ prev_s)) * 0.5 / k
        net = 0.5 * (r_long + f_long) + 0.5 * (r_short + f_short) - traded * cost
        rets.append(net)
        legs["long"].append(0.5 * r_long)
        legs["short"].append(0.5 * r_short)
        legs["funding"].append(0.5 * (f_long + f_short))
        prev_l, prev_s = L, S
    return np.array(rets), {k_: float(np.sum(v)) for k_, v in legs.items()}


def main() -> None:
    import sys
    src = "picks_v2" if "--v2" in sys.argv else "picks"  # which M2 version's scores to trade
    scores = pl.read_parquet(ROOT / "reports" / src / "scores.parquet")
    scores = scores.with_columns(base=pl.col("symbol").str.strip_suffix("USDT"))
    perps = perp_panel()
    df = (scores.select("day", "base", "score")
          .join(perps.select("day", "base", "perp", "fwd", "fund_fwd", "fund_past", "adv28"), on=["day", "base"], how="inner")
          .drop_nulls(["fwd", "adv28", "score"])
          .with_columns(pl.col("fund_fwd").fill_null(0.0), pl.col("fund_past").fill_null(0.0)))
    print(f"{df.height:,} coin-days with a live perp, {df['perp'].n_unique()} perps", flush=True)

    rows, legs_rows, params = [], [], {}
    for paying in (True, False):
        for n in NS:
            for k in KS:
                r, legs = long_short(df, k, n, paying_shorts=paying)
                name = f"top {k} / bottom {k} of the {n} most liquid perps" + ("" if paying else " · no paying shorts")
                params[name] = (k, n, paying)
                rows.append({"strategy": name, **perf(r)})
                legs_rows.append({"strategy": name, "long_leg_sum": legs["long"], "short_leg_sum": legs["short"],
                                  "funding_sum": legs["funding"]})
    sr = np.array([r["sharpe"] for r in rows]) / np.sqrt(365 / HORIZON)
    for r in rows:
        r["deflated_p"] = deflated_sharpe(r["sharpe"] / np.sqrt(365 / HORIZON), r["periods"], len(rows), float(np.var(sr)))
    best = max(rows, key=lambda r: r["sharpe"])

    # Stress: the same book at 3x costs.
    k_b, n_b, paying_b = params[best["strategy"]]
    r3, _ = long_short(df, k_b, n_b, cost=COST * 3, paying_shorts=paying_b)
    stress = perf(r3)

    verdict = (f"Best: {best['strategy']}: Sharpe {best['sharpe']:.2f}, {best['cagr'] * 100:.0f} % a year, worst "
               f"drawdown {best['max_dd'] * 100:.0f} %, deflated p {best['deflated_p']:.2f}; at 3x costs Sharpe "
               f"{stress['sharpe']:.2f}. "
               + ("This is the first candidate that could justify building perpetuals support, with margin and "
                  "squeeze risk handled first." if best["deflated_p"] > 0.95 and stress["sharpe"] > 0.5 else
                  "Not strong enough to justify building perpetuals support yet."))
    md = ("# M2 market-neutral on perpetuals\n\n"
          f"{df.height:,} coin-days where M2 had a score and a USDT perpetual was live, {df['perp'].n_unique()} perps. "
          f"Weekly, half the capital per side, {COST * 1e4:.0f} bps per unit turnover, real funding.\n\n"
          f"**Verdict:** {verdict}\n\n"
          + report.table(rows, ["strategy", "periods", "cagr", "sharpe", "max_dd", "deflated_p"])
          + "\n## Where the return came from (sum of weekly contributions)\n\n"
          + report.table(legs_rows, ["strategy", "long_leg_sum", "short_leg_sum", "funding_sum"]))
    report.write("picks_ls_v2" if src == "picks_v2" else "picks_ls", md, {"rows": rows, "legs": legs_rows, "stress_3x": stress, "verdict": verdict})


if __name__ == "__main__":
    main()
