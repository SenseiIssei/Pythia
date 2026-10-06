"""M2 · Picks: rank every tradable coin by its expected next-week return.

Universe: every USDT pair Binance ever listed (hist/universe.json, delisted
ones included), daily bars built from hourly klines. On each day a coin is
eligible when it has 60 days of history and traded at least 1 M USD a day on
average over the last 28 days. That is what makes this honest: the losers that
were later delisted are in the data, right up to their last day.

Model: LightGBM LambdaRank, one group per day, label = the forward 7-day
return bucketed into quintiles within the day. Features are cross-sectional
ranks (0..1) of momentum at several horizons, volatility, volume trend,
distance from highs and lows, BTC-relative momentum and liquidity.

Walk-forward by quarter from 2022, 7-day embargo (the label horizon).

Judged as a strategy: every 7 days hold the top K picks equally, long-only,
25 bps per unit of one-way turnover (alts cost more than BTC). Against:
  the equal-weight eligible universe, BTC, and the same top-K chosen by plain
  28-day momentum with no model (the bar M2 has to clear to be worth having).
All variants are deflated together.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone

import lightgbm as lgb
import numpy as np
import polars as pl

from .. import report
from ..cv import walk_forward
from ..data import HOUR_US, ROOT
from ..metrics import deflated_sharpe

DAY_US = 24 * HOUR_US
HORIZON = 7
COST = 0.0025
MIN_HISTORY_D = 60
MIN_ADV_USD = 1_000_000
FIRST_TEST = int(datetime(2022, 1, 1, tzinfo=timezone.utc).timestamp() * 1e6)
TOP_K = [5, 10, 20]
PARAMS = dict(objective="lambdarank", n_estimators=400, learning_rate=0.03, num_leaves=31,
              min_child_samples=200, subsample=0.8, subsample_freq=1, colsample_bytree=0.8,
              reg_lambda=5.0, n_jobs=4, verbose=-1, label_gain=list(range(5)))
FEATURES = ["r1", "r3", "r7", "r14", "r28", "r56", "vol7", "vol28", "vol_ratio", "volu_trend", "adv28",
            "dist_hi28", "dist_lo28", "skew7", "resid28", "age"]


GAP_SPLIT_US = 3 * DAY_US       # a longer trading gap starts a new series
JUMP_SPLIT = float(np.log(10))  # so does a tenfold price change within one hour


def hourly_segments(symbol: str) -> list[pl.DataFrame]:
    """A symbol's hourly bars, split where they stop being one continuous asset.

    Binance reuses symbols (LUNA after the crash relaunched as a new token under
    the same name) and redenominates tokens (QUICK, COCOS, SUN: the price jumps
    a thousandfold overnight). Bridging those makes thousandfold returns out of
    nothing. A gap of more than three days, or a tenfold move inside one hour,
    starts a new segment that is treated as a different coin.
    """
    d = ROOT / "hist" / "binance_spot" / "klines_1h" / f"symbol={symbol}"
    files = sorted(d.glob("*.parquet"))
    if not files:
        return []
    h = pl.concat([pl.read_parquet(f) for f in files], how="vertical_relaxed").unique("open_time_us").sort("open_time_us")
    h = h.with_columns(
        brk=((pl.col("open_time_us").diff() > GAP_SPLIT_US)
             | ((pl.col("close").log() - pl.col("close").shift(1).log()).abs() > JUMP_SPLIT)).fill_null(False)
    ).with_columns(seg=pl.col("brk").cum_sum())
    return [g.drop("brk", "seg") for _, g in h.group_by("seg", maintain_order=True)]


def daily_from_hourly(h: pl.DataFrame, symbol: str) -> pl.DataFrame:
    h = h.with_columns(r=(pl.col("close").log() - pl.col("close").shift(1).log()).fill_null(0.0))
    return (h.with_columns(day=(pl.col("open_time_us") // DAY_US) * DAY_US)
            .group_by("day", maintain_order=True)
            .agg(close=pl.col("close").last(), high=pl.col("high").max(), low=pl.col("low").min(),
                 rv=(pl.col("r") ** 2).sum(), qv=pl.col("quote_volume").sum(), n=pl.len(),
                 skew_num=(pl.col("r") ** 3).sum())
            .filter(pl.col("n") >= 20)
            .with_columns(symbol=pl.lit(symbol)))


def daily_bars(symbol: str) -> pl.DataFrame:
    """The latest continuous segment of a symbol, as daily bars."""
    segs = hourly_segments(symbol)
    return daily_from_hourly(segs[-1], symbol) if segs else pl.DataFrame()


def features(d: pl.DataFrame, btc: pl.DataFrame) -> pl.DataFrame:
    lc = pl.col("close").log()
    f = d.join(btc.select("day", btc_close="close"), on="day", how="left").with_columns(
        **{f"r{k}": lc - lc.shift(k) for k in (1, 3, 7, 14, 28, 56)},
        vol7=pl.col("rv").rolling_mean(7).sqrt(),
        vol28=pl.col("rv").rolling_mean(28).sqrt(),
        adv28=(pl.col("qv").rolling_mean(28) + 1).log(),
        volu_trend=(pl.col("qv").rolling_mean(7) + 1).log() - (pl.col("qv").rolling_mean(56) + 1).log(),
        dist_hi28=lc - pl.col("high").rolling_max(28).log(),
        dist_lo28=lc - pl.col("low").rolling_min(28).log(),
        skew7=pl.col("skew_num").rolling_sum(7) / (pl.col("rv").rolling_sum(7) ** 1.5 + 1e-12),
        age=pl.int_range(pl.len()).cast(pl.Float64),
        btc_r28=pl.col("btc_close").log() - pl.col("btc_close").log().shift(28),
    ).with_columns(vol_ratio=pl.col("vol7") / (pl.col("vol28") + 1e-12),
                   resid28=pl.col("r28") - pl.col("btc_r28"))
    # The label: exactly HORIZON calendar days ahead, not HORIZON rows (rows can skip days).
    ahead = d.select(day=pl.col("day") - HORIZON * DAY_US, close_ahead="close")
    f = f.join(ahead, on="day", how="left").with_columns(fwd=pl.col("close_ahead").log() - lc).drop("close_ahead")
    # A coin delisted inside the horizon keeps the return to its last close
    # (usually near the bottom). Dropping it would hide exactly the losers.
    last_close = d["close"][-1]
    n = f.height
    fwd = f["fwd"].to_numpy().copy()
    lcl = np.log(f["close"].to_numpy())
    tail = np.isnan(fwd) & (np.arange(n) >= n - HORIZON)
    delisted = d["day"][-1] < (datetime.now(timezone.utc).timestamp() * 1e6 - 3 * DAY_US)
    if delisted:
        fwd[tail] = np.log(last_close) - lcl[tail]
    return f.with_columns(fwd=pl.Series(fwd))


def build() -> pl.DataFrame:
    syms = json.loads((ROOT / "hist" / "universe.json").read_text())
    btc = daily_bars("BTCUSDT")
    frames = []
    for i, s in enumerate(syms):
        segs = hourly_segments(s)
        for j, seg in enumerate(segs):
            # Earlier segments of a reused or redenominated symbol become their own coin.
            name = s if j == len(segs) - 1 else f"{s}~{j}"
            d = daily_from_hourly(seg, name)
            if d.height < MIN_HISTORY_D + 10:
                continue
            frames.append(features(d, btc))
        if i % 100 == 0:
            print(f"{i}/{len(syms)} symbols", flush=True)
    p = pl.concat(frames, how="vertical_relaxed")
    p = p.filter((pl.col("age") >= MIN_HISTORY_D) & (pl.col("adv28") >= np.log(MIN_ADV_USD + 1)))
    p = p.drop_nulls(FEATURES)
    # Cross-sectional ranks per day: the model sees "where does this coin stand
    # today", which is comparable across years in a way raw returns are not.
    ranked = p.with_columns([((pl.col(c).rank().over("day") - 1) / (pl.len().over("day") - 1).clip(1)).alias(c)
                             for c in FEATURES])
    ranked = ranked.with_columns(
        label=((pl.col("fwd").rank().over("day") - 1) * 5 / pl.len().over("day")).floor().clip(0, 4).cast(pl.Int32))
    return ranked.filter(pl.len().over("day") >= 20).sort(["day", "symbol"])


def topk_returns(days: np.ndarray, sym: np.ndarray, score: np.ndarray, fwd: np.ndarray, k: int):
    """Every HORIZON days hold the top k by score, equal weight. Returns per-period net returns."""
    out_days, rets, prev = [], [], set()
    uniq = np.unique(days)
    for d in uniq[::HORIZON]:
        m = days == d
        if m.sum() < k:
            continue
        idx = np.flatnonzero(m)
        sel = idx[np.argsort(-score[idx])][:k]
        chosen = set(sym[sel])
        turnover = len(chosen ^ prev) / k if prev else 1.0  # one-way, as a share of the book
        gross = float(np.mean(np.expm1(fwd[sel])))
        rets.append(gross - turnover * COST)
        out_days.append(d)
        prev = chosen
    return np.array(out_days), np.array(rets)


def perf(r: np.ndarray) -> dict:
    per_year = 365 / HORIZON
    eq = np.cumprod(1 + r)
    dd = 1 - eq / np.maximum.accumulate(eq)
    return {"periods": len(r), "cagr": float(eq[-1] ** (per_year / len(r)) - 1) if len(r) else None,
            "sharpe": float(r.mean() / r.std() * np.sqrt(per_year)) if r.std() > 0 else 0.0,
            "max_dd": float(dd.max()) if len(r) else None}


def main() -> None:
    t0 = time.time()
    P = build()
    days = P["day"].to_numpy()
    X = P.select(FEATURES).to_numpy().astype(np.float32)
    y = P["label"].to_numpy()
    fwd = P["fwd"].to_numpy()
    sym = P["symbol"].to_numpy()
    print(f"panel {P.height:,} coin-days, {P['symbol'].n_unique()} coins, {len(np.unique(days))} days", flush=True)

    score = np.full(len(y), np.nan)
    folds = []
    for fold in walk_forward(days, FIRST_TEST, embargo_h=HORIZON * 24):
        tr = fold.train & np.isfinite(fwd)
        order = np.argsort(days[tr], kind="stable")
        Xt, yt, dt = X[tr][order], y[tr][order].astype(np.int32), days[tr][order]
        _, group = np.unique(dt, return_counts=True)
        m = lgb.LGBMRanker(**PARAMS).fit(Xt, yt, group=group)
        score[fold.test] = m.predict(X[fold.test])
        te = fold.test & np.isfinite(fwd)
        ic = [float(pl.DataFrame({"a": score[te & (days == d)], "b": fwd[te & (days == d)]})
                    .select(pl.corr("a", "b", method="spearman")).item() or 0.0)
              for d in np.unique(days[te])]
        folds.append({"fold": fold.name, "days": len(ic), "rank_ic": float(np.mean(ic))})
        print(folds[-1], flush=True)

    # Out-of-sample scores for the experiments built on M2 (picks_ls, the momentum filter).
    has_score = np.isfinite(score)
    pl.DataFrame({"day": days[has_score], "symbol": sym[has_score], "score": score[has_score],
                  "fwd": fwd[has_score], "adv_rank": P["adv28"].to_numpy()[has_score]}).write_parquet(
        ROOT / "reports" / "picks" / "scores.parquet")

    oos = np.isfinite(score) & np.isfinite(fwd)
    d_o, s_o, f_o, sy_o = days[oos], score[oos], fwd[oos], sym[oos]
    mom = P["r28"].to_numpy()[oos]  # cross-sectional rank of 28-day momentum: the no-model baseline
    rows, rets = [], {}
    for k in TOP_K:
        for name, sc in ((f"M2 top {k}", s_o), (f"28d momentum top {k}", mom)):
            dd, r = topk_returns(d_o, sy_o, sc, f_o, k)
            rets[name] = r
            rows.append({"strategy": name, **perf(r)})
    # Equal-weight eligible universe and BTC over the same periods
    uniq = np.unique(d_o)[::HORIZON]
    ew = np.array([float(np.mean(np.expm1(f_o[d_o == d]))) for d in uniq])
    btc = np.array([float(np.expm1(f_o[(d_o == d) & (sy_o == "BTCUSDT")]).mean()) if ((d_o == d) & (sy_o == "BTCUSDT")).any() else 0.0
                    for d in uniq])
    rows += [{"strategy": "equal-weight universe", **perf(ew)}, {"strategy": "BTC", **perf(btc)}]

    # Where does the skill sit? Mean next-week return per score decile, out of sample.
    dec_rows = []
    dfo = pl.DataFrame({"day": d_o, "score": s_o, "fwd": f_o, "sym": sy_o, "adv": P["adv28"].to_numpy()[oos]})
    dfo = dfo.with_columns(dec=((pl.col("score").rank().over("day") - 1) * 10 / pl.len().over("day")).floor().cast(pl.Int32))
    for row in dfo.group_by("dec").agg(mean_fwd=pl.col("fwd").mean(), n=pl.len()).sort("dec").iter_rows(named=True):
        dec_rows.append({"decile": int(row["dec"]) + 1, "mean_week_return_pct": float(np.expm1(row["mean_fwd"]) * 100),
                         "coin_days": row["n"]})
    # Does it hold among the liquid coins, or only in the tiny ones? Rank-IC within
    # the 50 most liquid coins of each day (adv28 is a cross-sectional rank here).
    liquid = dfo.filter(pl.col("adv").rank(descending=True).over("day") <= 50)
    ic_liquid = liquid.group_by("day").agg(ic=pl.corr("score", "fwd", method="spearman"))["ic"].drop_nans().mean()
    # Long the top decile, short the bottom one: the pure ranking skill (needs shorting,
    # which spot cannot do; shown to locate the edge, not as a strategy).
    ls = dfo.group_by("day").agg(
        top=pl.col("fwd").filter(pl.col("dec") == 9).mean(), bottom=pl.col("fwd").filter(pl.col("dec") == 0).mean()
    ).sort("day")
    ls_w = ls.with_columns(spread=pl.col("top").exp() - pl.col("bottom").exp())["spread"].drop_nulls().to_numpy()[::HORIZON]
    rows.append({"strategy": "top decile minus bottom decile (gross, needs shorts)", **perf(ls_w)})
    # Top-K held only while BTC is above its 200-day average (the momentum book's filter).
    btc_daily = daily_bars("BTCUSDT").select("day", "close").sort("day")
    btc_daily = btc_daily.with_columns(on=pl.col("close") > pl.col("close").rolling_mean(200))
    on = dict(zip(btc_daily["day"].to_list(), btc_daily["on"].to_list()))
    for k in TOP_K:
        dd, r = topk_returns(d_o, sy_o, s_o, f_o, k)
        r_reg = np.array([x if on.get(int(d)) else 0.0 for d, x in zip(dd, r)])
        rets[f"M2 top {k} · regime"] = r_reg
        rows.append({"strategy": f"M2 top {k} · regime", **perf(r_reg)})

    trial = [r for r in rows if r["strategy"].startswith(("M2", "28d"))]
    sr = np.array([r["sharpe"] for r in trial]) / np.sqrt(365 / HORIZON)
    for r in trial:
        r["deflated_p"] = deflated_sharpe(r["sharpe"] / np.sqrt(365 / HORIZON), r["periods"], len(trial), float(np.var(sr)))
    ics = np.array([f["rank_ic"] for f in folds if np.isfinite(f["rank_ic"]) and f["days"] > 0])
    ic_mean = float(ics.mean())
    ic_t = ic_mean / (ics.std() / np.sqrt(len(ics)) + 1e-12)
    best = max((r for r in rows if r["strategy"].startswith("M2")), key=lambda r: r["sharpe"])
    base = next(r for r in rows
                if r["strategy"] == best["strategy"].replace(" · regime", "").replace("M2", "28d momentum"))
    beats = best["sharpe"] > base["sharpe"] and best["deflated_p"] > 0.95
    verdict = (f"Rank-IC {ic_mean:.3f} out of sample (t {ic_t:.1f} across {len(ics)} quarters), "
               f"{ic_liquid:.3f} among the 50 most liquid coins of each day. "
               f"Best: {best['strategy']}, Sharpe {best['sharpe']:.2f}, drawdown {best['max_dd'] * 100:.0f} %, "
               f"deflated p {best['deflated_p']:.2f}; plain momentum with the same K: Sharpe {base['sharpe']:.2f}. "
               + ("M2 earns its place: better than the no-model baseline and survives deflation."
                  if beats else "M2 does not clear the bar yet (must beat plain momentum and survive deflation)."))
    md = ("# M2 · Picks, ranking every coin by next-week return\n\n"
          f"{P.height:,} coin-days, {P['symbol'].n_unique()} coins (delisted included), eligibility: "
          f"{MIN_HISTORY_D} days of history and {MIN_ADV_USD / 1e6:.0f} M USD daily volume. Weekly rebalance, "
          f"{COST * 1e4:.0f} bps per unit turnover, out of sample from 2022. Took {(time.time() - t0) / 60:.0f} min.\n\n"
          f"**Verdict:** {verdict}\n\n"
          + report.table(rows, ["strategy", "periods", "cagr", "sharpe", "max_dd", "deflated_p"])
          + "\n## Next-week return by score decile (10 = best score)\n\n"
          + report.table(dec_rows, ["decile", "mean_week_return_pct", "coin_days"])
          + "\n## Rank-IC per quarter\n\n" + report.table(folds, ["fold", "days", "rank_ic"]))
    report.write("picks", md, {"rows": rows, "folds": folds, "rank_ic": ic_mean, "rank_ic_t": ic_t,
                               "rank_ic_liquid50": ic_liquid, "deciles": dec_rows, "verdict": verdict})


if __name__ == "__main__":
    main()
