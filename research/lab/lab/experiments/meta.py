"""Meta-labeling on a long-only breakout. Masterplan phase 4.

Primary strategy (deliberately plain, crypto spot is long-only):
  enter long when the hourly close breaks the highest high of the previous 48 hours,
  one position per coin at a time.
Exit by triple barrier: +2 sigma / -1 sigma over 24 h, sigma from the last 24 h of
realised variance. Costs: 30 bps per round trip (Binance taker both legs plus
half-spreads), already in every return below.

Secondary model (the meta-label): LightGBM predicts whether a given breakout
hits the upper barrier first, from volatility state, flow, funding, open
interest and BTC context. Trades go through only above a probability threshold.

Walk-forward by quarter from 2022 (open-interest history starts then), with
purging: a training event must have EXITED a day before the test quarter starts.

The question: does filtering improve net return per trade and the Sharpe, after
deflating for the thresholds tried, against the unfiltered strategy and against
random entries with the same exits?
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

import lightgbm as lgb
import numpy as np
import polars as pl

from .. import report
from ..cv import HOUR_US, walk_forward
from ..data import UNIVERSE, funding, hourly, open_interest_hourly
from ..labels import non_overlapping, triple_barrier
from ..metrics import deflated_sharpe
from .vol import features as vol_features

LOOKBACK, HORIZON, UP, DN = 48, 24, 2.0, 1.0
COST = 0.0030
THRESHOLDS = [0.40, 0.45, 0.50, 0.55]
FIRST_TEST = int(datetime(2022, 7, 1, tzinfo=timezone.utc).timestamp() * 1e6)
PARAMS = dict(n_estimators=300, learning_rate=0.03, num_leaves=15, min_child_samples=200,
              subsample=0.8, subsample_freq=1, colsample_bytree=0.8, reg_lambda=5.0,
              n_jobs=4, verbose=-1)
FEATURES = ["har1", "har24", "har168", "park", "vol_z", "trades_z", "taker", "ret24", "seasonal",
            "hsin", "hcos", "dow", "btc_har1", "btc_har24", "btc_ret", "rel_har1",
            "brk_strength", "mom72", "dist_high168", "btc_mom72",
            "funding", "funding_7d", "oi_chg24", "oi_chg168"]


def coin_events(base: str, btc: pl.DataFrame, rng: np.random.Generator) -> tuple[pl.DataFrame, pl.DataFrame]:
    h = hourly(f"{base}USDT")
    f = vol_features(h).with_columns(
        sigma=(pl.col("rv").rolling_mean(24)).sqrt(),
        prior_high=pl.col("high").shift(1).rolling_max(LOOKBACK),
        high168=pl.col("high").rolling_max(168),
        ret72=pl.col("ret").rolling_sum(72),
        known_us=pl.col("ts_us") + HOUR_US,
    ).with_columns(
        brk_strength=(pl.col("close") / pl.col("prior_high")).log() / pl.col("sigma"),
        mom72=pl.col("ret72") / (pl.col("sigma") * np.sqrt(72)),
        dist_high168=(pl.col("close") / pl.col("high168")).log() / pl.col("sigma"),
    )
    f = f.join(btc, on="ts_us", how="left").with_columns(rel_har1=pl.col("har1") - pl.col("btc_har1"))

    fu = funding(base)
    if not fu.is_empty():
        fu = fu.with_columns(funding_7d=pl.col("funding_rate").rolling_mean(21)).rename({"funding_rate": "funding"})
        f = f.sort("known_us").join_asof(fu, left_on="known_us", right_on="funding_time_us", strategy="backward")
    else:
        f = f.with_columns(funding=pl.lit(None, pl.Float64), funding_7d=pl.lit(None, pl.Float64))
    oi = open_interest_hourly(base)
    if not oi.is_empty():
        oi = oi.with_columns(oi_chg24=(pl.col("oi_usd") / pl.col("oi_usd").shift(24)).log(),
                             oi_chg168=(pl.col("oi_usd") / pl.col("oi_usd").shift(168)).log())
        f = f.join(oi.select("ts_us", "oi_chg24", "oi_chg168"), on="ts_us", how="left")
    else:
        f = f.with_columns(oi_chg24=pl.lit(None, pl.Float64), oi_chg168=pl.lit(None, pl.Float64))
    f = f.sort("ts_us")

    close, high, low = (f[c].to_numpy() for c in ("close", "high", "low"))
    sigma = f["sigma"].fill_null(np.nan).to_numpy()
    ok = np.isfinite(sigma) & (sigma > 0)
    signal = (f["close"] > f["prior_high"]).fill_null(False).to_numpy() & ok

    def events(sig: np.ndarray) -> pl.DataFrame:
        idx_all = np.flatnonzero(sig)
        ex, _, _ = triple_barrier(close, high, low, idx_all, sigma, UP, DN, HORIZON, COST)
        exit_of = dict(zip(idx_all.tolist(), ex.tolist()))
        idx = np.array(non_overlapping(sig, exit_of.__getitem__), dtype=np.int64)
        ex, ret, hit = triple_barrier(close, high, low, idx, sigma, UP, DN, HORIZON, COST)
        ts = f["ts_us"].to_numpy()
        rows = f.with_row_index("_i").filter(pl.col("_i").is_in(idx.tolist())).drop("_i")
        return (rows.with_columns(
            exit_us=pl.Series(ts[ex] + HOUR_US), net=pl.Series(ret), hit=pl.Series(hit),
            label=pl.Series((ret > 0).astype(np.int8))))

    ev = events(signal)
    # Random entries: same count, same exit rule, uniform over valid hours.
    rand_sig = np.zeros(len(close), dtype=bool)
    valid = np.flatnonzero(ok[:len(close) - HORIZON])
    rand_sig[rng.choice(valid, size=min(len(valid), max(1, 3 * ev.height)), replace=False)] = True
    rev = events(rand_sig)
    return ev, rev


def stats(r: np.ndarray, years: float) -> dict:
    if len(r) < 2:
        return {"trades": int(len(r)), "hit": None, "mean_bps": None, "sum": None, "sharpe": None}
    per_year = len(r) / years
    return {"trades": int(len(r)), "hit": float((r > 0).mean()), "mean_bps": float(r.mean() * 1e4),
            "sum": float(r.sum()), "sharpe": float(r.mean() / r.std() * np.sqrt(per_year)),
            "sharpe_trade": float(r.mean() / r.std())}


def main() -> None:
    t0 = time.time()
    rng = np.random.default_rng(7)
    btc_h = vol_features(hourly("BTCUSDT"))
    btc = btc_h.select("ts_us", btc_har1="har1", btc_har24="har24", btc_ret="ret",
                       btc_mom72=pl.col("ret").rolling_sum(72) / ((pl.col("rv").rolling_mean(24)).sqrt() * np.sqrt(72)))
    evs, rands = [], []
    for b in UNIVERSE:
        ev, rev = coin_events(b, btc, rng)
        evs.append(ev.with_columns(symbol=pl.lit(b)))
        rands.append(rev.with_columns(symbol=pl.lit(b)))
        print(f"{b}: {ev.height} breakouts, mean net {ev['net'].mean() * 1e4:.1f} bps", flush=True)
    keep = ["ts_us", "exit_us", "symbol", "net", "hit", "label"] + FEATURES
    E = pl.concat([e.select(keep) for e in evs], how="vertical_relaxed").sort("ts_us")
    R = pl.concat([e.select("ts_us", "net") for e in rands]).sort("ts_us")

    ts, ex = E["ts_us"].to_numpy(), E["exit_us"].to_numpy()
    X = E.select(FEATURES).to_numpy().astype(np.float32)
    y = E["label"].to_numpy()
    net = E["net"].to_numpy()
    prob = np.full(len(y), np.nan)
    fold_rows = []
    for fold in walk_forward(ts, FIRST_TEST, embargo_h=0):
        test_start = ts[fold.test].min()
        train = ex < test_start - 24 * HOUR_US  # purge: label fully resolved a day before
        m = lgb.LGBMClassifier(**PARAMS).fit(X[train], y[train])
        prob[fold.test] = m.predict_proba(X[fold.test])[:, 1]
        r_all = net[fold.test]
        r_f = net[fold.test][prob[fold.test] > 0.5]
        fold_rows.append({"fold": fold.name, "train": int(train.sum()), "trades": int(fold.test.sum()),
                          "mean_all_bps": float(r_all.mean() * 1e4),
                          "taken_050": int(len(r_f)),
                          "mean_050_bps": float(r_f.mean() * 1e4) if len(r_f) else None})
        print(fold_rows[-1], flush=True)

    oos = ~np.isnan(prob)
    years = (ts[oos].max() - ts[oos].min()) / (365.25 * 24 * HOUR_US)
    rand_oos = R.filter(pl.col("ts_us") >= ts[oos].min())["net"].to_numpy()
    rows = [{"strategy": "random entries, same exits", **stats(rand_oos, years)},
            {"strategy": "breakout, unfiltered", **stats(net[oos], years)}]
    for th in THRESHOLDS:
        rows.append({"strategy": f"breakout + meta p>{th:.2f}", **stats(net[oos][prob[oos] > th], years)})
    trial_sharpes = [r["sharpe_trade"] for r in rows[1:] if r.get("sharpe_trade") is not None]
    sr_var = float(np.var(trial_sharpes)) if len(trial_sharpes) > 1 else 0.0
    for r in rows[1:]:
        if r.get("sharpe_trade") is not None:
            r["deflated_p"] = deflated_sharpe(r["sharpe_trade"], r["trades"], len(trial_sharpes), sr_var)
    auc = auc_score(y[oos], prob[oos])

    best = max(rows[2:], key=lambda r: r["sharpe"] or -9)
    base = rows[1]
    verdict = (
        f"Out of sample the meta-model ranks breakouts with AUC {auc:.3f}. "
        f"Unfiltered breakouts make {base['mean_bps']:.1f} bps per trade after costs (Sharpe {base['sharpe']:.2f}); "
        f"the best filter ({best['strategy']}) makes {best['mean_bps']:.1f} bps over {best['trades']} trades "
        f"(Sharpe {best['sharpe']:.2f}, deflated p {best.get('deflated_p', float('nan')):.3f}). "
        + ("That clears the bar for gate 6 and moves on to a paper forward test."
           if best.get("deflated_p", 0) > 0.95 and best["mean_bps"] > 0 else
           "That does not clear the deflated-Sharpe bar (needs > 0.95). Not a strategy yet.")
    )
    md = (
        "# Meta-labeling a long-only breakout\n\n"
        f"{E.height:,} breakouts across {E['symbol'].n_unique()} coins, out-of-sample from 2022Q3, "
        f"{len(fold_rows)} quarterly folds with purging. Barriers +{UP} / -{DN} sigma over {HORIZON} h, "
        f"{COST * 1e4:.0f} bps round-trip cost included. Run took {(time.time() - t0) / 60:.1f} min.\n\n"
        f"**Verdict:** {verdict}\n\n"
        + report.table(rows, ["strategy", "trades", "hit", "mean_bps", "sum", "sharpe", "deflated_p"])
        + "\n`sum` is the summed net log return of all trades (one unit per trade, no compounding, no "
        "sizing). `deflated_p` is the probability that the Sharpe beats the best of the variants tried by "
        "chance; it needs to be above 0.95.\n\n## Per quarter (threshold 0.50)\n\n"
        + report.table(fold_rows, ["fold", "train", "trades", "mean_all_bps", "taken_050", "mean_050_bps"])
    )
    report.write("meta_breakout", md, {"rows": rows, "folds": fold_rows, "auc": auc, "verdict": verdict})


def auc_score(y: np.ndarray, p: np.ndarray) -> float:
    from sklearn.metrics import roc_auc_score
    return float(roc_auc_score(y, p))


if __name__ == "__main__":
    main()
