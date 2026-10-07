"""M6 · Daily volatility forecast for position sizing.

The momentum book sizes every coin by sigma = sqrt(30-day mean realised
variance). That is a forecast too, just an old one. This asks whether a
better forecast of the next day and the next week makes the sizing, and with
it the book, measurably better. It is the cheapest improvement on the list:
no new signal, no extra turnover by design.

Data: the 20 coins with 1-minute bars, daily realised variance = sum of
squared 1m log returns over the UTC day (from data.hourly). A day counts when
at least 20 hours were recorded.

Targets, known after the fact:
  1d   realised variance of day d+1
  7d   mean daily realised variance over d+1 .. d+7 (what a weekly book holds through)

Forecasts, all from data up to the end of day d:
  RW30   mean realised variance of the last 30 days: what tsmom and momentum2 use today
  EWMA   RiskMetrics, lambda 0.94, on squared close-to-close daily returns
  EWMA-RV  the same smoother on realised variance
  HAR    Corsi: log RV on log 1, 7 and 30 day RV, pooled OLS, refit per fold
  LGBM   gradient boosting on the HAR terms plus semivariance, jumps, signed
         returns, range, volume and trade shocks, BTC and market-wide RV, the
         weekday of the target day, and funding and open interest where the
         perp has them
Log-space forecasts are turned into variance with exp(pred + resid_var / 2).

Walk-forward by quarter from 2021, embargo 8 days. Losses: QLIKE (robust to
noise in the RV proxy) and R^2 in log space. Diebold-Mariano against HAR.

Then the part that pays: the same momentum book (momentum2's pick, 28-day,
daily, 40 % vol target, BTC 200-day regime) and a plain BTC vol-target book
(40 % target, at most 1x), each sized with every forecast. Variant choice on
2021-2023, holdout from 2024; 15 and 41 bps per unit of turnover. The sizing
variants are deflated together with the 50 momentum variants tried before.
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
from ..data import HOUR_US, ROOT, UNIVERSE, hourly, perp_symbol
from ..metrics import deflated_sharpe, diebold_mariano, qlike, r2

DAY_US = 24 * HOUR_US
EPS = 1e-12
FIRST_TEST = int(datetime(2021, 1, 1, tzinfo=timezone.utc).timestamp() * 1e6)
HOLDOUT = int(datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp() * 1e6)
COSTS = {"15bps": 0.0015, "41bps": 0.0041}
PRIOR_MOMENTUM_VARIANTS = 50
HAR_COLS = ["h1", "h7", "h30"]
FEATURES = ["h1", "h7", "h30", "h90", "h1_l1", "h1_l2", "dn_share7", "jump7", "ret1", "ret7", "ret30",
            "absret1", "park1", "qv_z", "tr_z", "dist_hi30", "btc_h1", "btc_h7", "mkt_h1", "mkt_h7",
            "rel_h7", "dow_next", "fund1", "fund7", "oi_chg1", "oi_chg7"]
PARAMS = dict(n_estimators=400, learning_rate=0.03, num_leaves=15, min_child_samples=300, subsample=0.8,
              subsample_freq=1, colsample_bytree=0.8, reg_lambda=5.0, n_jobs=8, verbose=-1)


def coin_daily(base: str) -> pl.DataFrame:
    h = hourly(f"{base}USDT")
    if h.is_empty():
        return h
    h = h.with_columns(day=(pl.col("ts_us") // DAY_US) * DAY_US)
    d = (h.group_by("day", maintain_order=True)
         .agg(close=pl.col("close").last(), high=pl.col("high").max(), low=pl.col("low").min(),
              rv=pl.col("rv").sum(), rv_dn=(pl.col("ret").clip(upper_bound=0) ** 2).sum(),
              rv_h=(pl.col("ret") ** 2).sum(), maxh=(pl.col("ret") ** 2).max(),
              qv=pl.col("volume_q").sum(), trades=pl.col("trades").sum(), n=pl.len())
         .filter(pl.col("n") >= 20).sort("day"))
    # Calendar frame so that "next day" means the next calendar day.
    cal = pl.DataFrame({"day": np.arange(int(d["day"][0]), int(d["day"][-1]) + 1, DAY_US, dtype=np.int64)})
    d = cal.join(d, on="day", how="left")
    lrv = (pl.col("rv") + EPS).log()
    r = pl.col("close").log() - pl.col("close").log().shift(1)
    f = d.with_columns(ret=r).with_columns(
        y1=pl.col("rv").shift(-1),
        h1=lrv,
        h1_l1=lrv.shift(1),
        h1_l2=lrv.shift(2),
        h7=(pl.col("rv").rolling_mean(7, min_samples=5) + EPS).log(),
        h30=(pl.col("rv").rolling_mean(30, min_samples=20) + EPS).log(),
        h90=(pl.col("rv").rolling_mean(90, min_samples=60) + EPS).log(),
        dn_share7=pl.col("rv_dn").rolling_sum(7, min_samples=5) / (pl.col("rv_h").rolling_sum(7, min_samples=5) + EPS),
        jump7=pl.col("maxh").rolling_sum(7, min_samples=5) / (pl.col("rv_h").rolling_sum(7, min_samples=5) + EPS),
        ret1=pl.col("ret"),
        ret7=pl.col("close").log() - pl.col("close").log().shift(7),
        ret30=pl.col("close").log() - pl.col("close").log().shift(30),
        absret1=pl.col("ret").abs(),
        park1=((pl.col("high") / pl.col("low")).log() ** 2 + EPS).log(),
        qv_z=(pl.col("qv") + 1).log() - (pl.col("qv").rolling_mean(30, min_samples=20) + 1).log(),
        tr_z=(pl.col("trades") + 1).log() - (pl.col("trades").rolling_mean(30, min_samples=20) + 1).log(),
        dist_hi30=pl.col("close").log() - pl.col("high").rolling_max(30, min_samples=20).log(),
        dow_next=(((pl.col("day") // DAY_US) + 1 + 3) % 7).cast(pl.Float64),
        rw30=pl.col("rv").rolling_mean(30, min_samples=20),
    )
    # y7: mean RV over d+1..d+7. rolling_mean over rows t-6..t, evaluated at t = d+7.
    f = f.with_columns(y7=pl.col("rv").rolling_mean(7, min_samples=6).shift(-7))
    # EWMA (RiskMetrics) on squared daily returns and on RV, seeded with the first 30 days.
    f = f.with_columns(ewma=_ewma(f["ret"].to_numpy() ** 2, 0.94), ewma_rv=_ewma(f["rv"].to_numpy(), 0.94))
    return f.with_columns(symbol=pl.lit(base))


def _ewma(x: np.ndarray, lam: float) -> pl.Series:
    out = np.full(len(x), np.nan)
    s, seen = np.nan, 0
    for i, v in enumerate(x):
        if np.isfinite(v):
            s = v if not np.isfinite(s) else lam * s + (1 - lam) * v
            seen += 1
        out[i] = s if seen >= 30 else np.nan
    return pl.Series(out)


def perp_feats(base: str) -> pl.DataFrame | None:
    from ..data import funding, open_interest_hourly
    fu = funding(base)
    if fu.is_empty():
        return None
    f = (fu.with_columns(day=((pl.col("funding_time_us") - 1) // DAY_US) * DAY_US)
         .group_by("day").agg(fd=pl.col("funding_rate").sum()).sort("day")
         .with_columns(fund1=pl.col("fd").abs(), fund7=pl.col("fd").rolling_sum(7, min_samples=1).abs()).drop("fd"))
    oi = open_interest_hourly(base)
    if not oi.is_empty():
        o = (oi.with_columns(day=(pl.col("ts_us") // DAY_US) * DAY_US).group_by("day").agg(oi=pl.col("oi_usd").last())
             .sort("day").with_columns(oi_chg1=pl.col("oi").log().diff(), oi_chg7=pl.col("oi").log() - pl.col("oi").log().shift(7))
             .drop("oi"))
        f = f.join(o, on="day", how="full", coalesce=True)
    else:
        f = f.with_columns(oi_chg1=pl.lit(None, pl.Float64), oi_chg7=pl.lit(None, pl.Float64))
    return f


def build() -> pl.DataFrame:
    frames = []
    for b in UNIVERSE:
        t = time.time()
        f = coin_daily(b)
        if f.is_empty():
            continue
        pf = perp_feats(b)
        if pf is not None:
            f = f.join(pf, on="day", how="left")
        else:
            f = f.with_columns(**{c: pl.lit(None, pl.Float64) for c in ("fund1", "fund7", "oi_chg1", "oi_chg7")})
        frames.append(f.select(sorted(set(f.columns))))
        print(f"{b}: {f.height} days, {time.time() - t:.0f}s", flush=True)
    p = pl.concat(frames, how="diagonal_relaxed")
    btc = p.filter(pl.col("symbol") == "BTC").select("day", btc_h1="h1", btc_h7="h7")
    mkt = p.group_by("day").agg(mkt_h1=pl.col("h1").mean(), mkt_h7=pl.col("h7").mean())
    p = p.join(btc, on="day", how="left").join(mkt, on="day", how="left").with_columns(rel_h7=pl.col("h7") - pl.col("mkt_h7"))
    return p.sort(["day", "symbol"])


def ols(x, y):
    X = np.column_stack([np.ones(len(x)), x])
    return np.linalg.lstsq(X, y, rcond=None)[0]


def forecasts(p: pl.DataFrame, target: str):
    """Out-of-sample variance forecasts for every row (NaN before the first fold)."""
    ok = p.select(pl.all_horizontal(pl.col(HAR_COLS + ["rw30", "ewma", "ewma_rv"]).is_not_null())).to_series().to_numpy()
    ts = p["day"].to_numpy()
    yv = p[target].to_numpy().astype(float)
    ly = np.log(yv + EPS)
    X = p.select(FEATURES).to_numpy().astype(np.float32)
    Xh = p.select(HAR_COLS).to_numpy().astype(float)
    out = {m: np.full(p.height, np.nan) for m in ("RW30", "EWMA", "EWMA-RV", "HAR", "LGBM")}
    folds = []
    for fold in walk_forward(ts, FIRST_TEST, embargo_h=8 * 24):
        tr = fold.train & ok & np.isfinite(ly) & (yv > 0)
        te = fold.test & ok
        b = ols(Xh[tr], ly[tr])
        rh = np.var(ly[tr] - (b[0] + Xh[tr] @ b[1:]))
        out["HAR"][te] = np.exp(b[0] + Xh[te] @ b[1:] + rh / 2)
        m = lgb.LGBMRegressor(**PARAMS).fit(X[tr], ly[tr])
        rl = np.var(ly[tr] - m.predict(X[tr]))
        out["LGBM"][te] = np.exp(m.predict(X[te]) + rl / 2)
        out["RW30"][te] = p["rw30"].to_numpy()[te]
        out["EWMA"][te] = p["ewma"].to_numpy()[te]
        out["EWMA-RV"][te] = p["ewma_rv"].to_numpy()[te]
        ev = te & np.isfinite(yv) & (yv > 0)
        row = {"target": target, "fold": fold.name, "rows": int(ev.sum())}
        for k in out:
            row[f"qlike_{k}"] = float(np.mean(qlike(yv[ev], out[k][ev])))
        folds.append(row)
    return out, folds


def momentum_book(sigma: np.ndarray, close: np.ndarray, history: np.ndarray, risk_on: np.ndarray):
    from .momentum2 import run
    from .tsmom import target_weights
    fn = lambda t: target_weights(close, sigma, history, t, [28], 0.40) * risk_on[t]  # noqa: E731
    return run(close, fn, 1, 200)


def btc_book(sigma_btc: np.ndarray, close_btc: np.ndarray):
    from .tsmom import COST
    T = len(close_btc)
    ret = np.r_[np.nan, close_btc[1:] / close_btc[:-1] - 1]
    w = 0.0
    gross, cost, expo = np.zeros(T), np.zeros(T), np.zeros(T)
    for t in range(30, T - 1):
        s = sigma_btc[t]
        tgt = min(1.0, 0.40 / (s * np.sqrt(365))) if np.isfinite(s) and s > 0 else 0.0
        cost[t] = abs(tgt - w) * COST
        w = tgt
        r = ret[t + 1] if np.isfinite(ret[t + 1]) else 0.0
        gross[t + 1] = w * r
        expo[t] = w
        w = w * (1 + r) / (1 + w * r) if 1 + w * r > 0 else w
    return gross, cost, gross - np.r_[0.0, cost[:-1]], expo


def perf(r):
    r = r[np.isfinite(r)]
    eq = np.cumprod(1 + r)
    yrs = len(r) / 365
    return {"sharpe": float(r.mean() / r.std() * np.sqrt(365)) if r.std() > 0 else 0.0,
            "cagr": float(eq[-1] ** (1 / yrs) - 1), "max_dd": float((1 - eq / np.maximum.accumulate(eq)).max()),
            "vol": float(r.std() * np.sqrt(365))}


def main() -> None:
    t0 = time.time()
    p = build()
    print(f"panel {p.height:,} coin-days", flush=True)
    res, fold_rows, summary = {}, [], []
    for target in ("y1", "y7"):
        fc, folds = forecasts(p, target)
        res[target] = fc
        fold_rows += folds
        yv = p[target].to_numpy().astype(float)
        ev = np.isfinite(fc["LGBM"]) & np.isfinite(yv) & (yv > 0) & np.all([np.isfinite(v) for v in fc.values()], axis=0)
        losses = {k: qlike(yv[ev], v[ev]) for k, v in fc.items()}
        dm_lag = 1 if target == "y1" else 7
        for k, v in fc.items():
            # Rows are ordered by day with up to 20 coins a day, so a Newey-West lag of
            # horizon x 20 rows spans the overlap of the labels and the cross-coin correlation.
            dm, dmp = diebold_mariano(losses[k], losses["HAR"], lag=dm_lag * 20) if k != "HAR" else (0.0, 1.0)
            summary.append({"target": "next day" if target == "y1" else "next 7 days", "model": k,
                            "qlike": float(losses[k].mean()), "r2_log": r2(np.log(yv[ev]), np.log(v[ev])),
                            "gain_vs_har_pct": float(100 * (1 - losses[k].mean() / losses["HAR"].mean())),
                            "gain_vs_rw30_pct": float(100 * (1 - losses[k].mean() / losses["RW30"].mean())),
                            "dm_stat_vs_har": dm, "dm_p_vs_har": dmp})
        print(summary[-5:], flush=True)

    # Sizing: daily sigma for each coin from each 7-day forecast (variance per day).
    from .tsmom import COST, MIN_HISTORY_D, daily_matrix, rolling_mean
    days, close, rv, names = daily_matrix()
    history = np.cumsum(np.isfinite(close), axis=0)
    btc = close[:, names.index("BTC")]
    ma200 = rolling_mean(btc[:, None], 200, 200)[:, 0]
    risk_on = np.nan_to_num(btc > ma200, nan=0.0).astype(bool)
    di = {int(d): i for i, d in enumerate(days)}
    ni = {n: j for j, n in enumerate(names)}
    rows_i = np.array([di.get(int(d), -1) for d in p["day"].to_numpy()])
    cols_j = np.array([ni.get(s, -1) for s in p["symbol"].to_numpy()])
    okm = (rows_i >= 0) & (cols_j >= 0)
    base_sigma = np.sqrt(rolling_mean(rv, 30, 20))  # exactly what the books use today
    sigmas = {}
    for k in ("RW30", "EWMA", "EWMA-RV", "HAR", "LGBM"):
        s = base_sigma.copy()
        v = res["y7"][k]
        m = okm & np.isfinite(v)
        s[rows_i[m], cols_j[m]] = np.sqrt(v[m])
        sigmas[k] = s
    start = int(np.searchsorted(days, FIRST_TEST))
    sel = (days >= FIRST_TEST) & (days < HOLDOUT)
    hold = days >= HOLDOUT
    book_rows, variants = [], []
    for k, s in sigmas.items():
        g, c, n, e = momentum_book(s, close, history, risk_on)
        variants.append(("momentum book", k, g, c, e))
        g2, c2, n2, e2 = btc_book(s[:, names.index("BTC")], btc)
        variants.append(("BTC vol target", k, g2, c2, e2))
    for book_name, k, g, c, e in variants:
        paid = np.r_[0.0, c[:-1]]
        row = {"book": book_name, "sizing": k}
        for cn, cv in COSTS.items():
            net = g - paid * cv / COST
            ps, ph = perf(net[sel]), perf(net[hold])
            row[f"sel_sharpe_{cn}"] = ps["sharpe"]
            row[f"hold_sharpe_{cn}"] = ph["sharpe"]
            row[f"hold_cagr_{cn}"] = ph["cagr"]
            row[f"hold_max_dd_{cn}"] = ph["max_dd"]
        row["hold_vol"] = perf(g[hold])["vol"]
        row["turnover_yr"] = float((c[hold] / COST).sum() / (hold.sum() / 365))
        row["avg_exposure"] = float(e[hold].mean())
        # How steady is the risk? Std of the 30-day rolling realised vol of the book, annualised.
        rr = g[hold]
        roll = np.array([rr[i - 30:i].std() * np.sqrt(365) for i in range(30, len(rr))])
        row["vol_of_vol"] = float(roll.std())
        book_rows.append(row)
    n_trials = PRIOR_MOMENTUM_VARIANTS + len(book_rows)
    n_obs = int(hold.sum())
    for cn in COSTS:
        srs = np.array([r[f"hold_sharpe_{cn}"] for r in book_rows]) / np.sqrt(365)
        for r in book_rows:
            r[f"deflated_p_{cn}"] = deflated_sharpe(r[f"hold_sharpe_{cn}"] / np.sqrt(365), n_obs, n_trials, float(np.var(srs)))

    s7 = {r["model"]: r for r in summary if r["target"] == "next 7 days"}
    s1 = {r["model"]: r for r in summary if r["target"] == "next day"}
    recent = [f for f in fold_rows if f["target"] == "y7"][-4:]
    stable = all(f["qlike_LGBM"] <= f["qlike_HAR"] * 1.02 for f in recent)
    fc_pass = s7["LGBM"]["gain_vs_har_pct"] > 0 and s7["LGBM"]["dm_p_vs_har"] < 0.05 and stable
    lines = []
    for bk in ("momentum book", "BTC vol target"):
        br = {r["sizing"]: r for r in book_rows if r["book"] == bk}
        best = max(br.values(), key=lambda r: r["sel_sharpe_15bps"])
        lines.append(f"- **{bk}**: sized with RW30 (today's rule) holdout Sharpe {br['RW30']['hold_sharpe_15bps']:.2f} / "
                     f"{br['RW30']['hold_sharpe_41bps']:.2f} (15 / 41 bps), drawdown {br['RW30']['hold_max_dd_15bps'] * 100:.0f} %; "
                     f"with LGBM {br['LGBM']['hold_sharpe_15bps']:.2f} / {br['LGBM']['hold_sharpe_41bps']:.2f}, drawdown "
                     f"{br['LGBM']['hold_max_dd_15bps'] * 100:.0f} %; with HAR {br['HAR']['hold_sharpe_15bps']:.2f}; "
                     f"with EWMA {br['EWMA']['hold_sharpe_15bps']:.2f}. Picked on 2021-2023: {best['sizing']}.")
    verdict = (f"Next 7 days: LGBM QLIKE {s7['LGBM']['gain_vs_har_pct']:.1f} % better than HAR "
               f"(DM p {s7['LGBM']['dm_p_vs_har']:.2g}), {s7['LGBM']['gain_vs_rw30_pct']:.1f} % better than the 30-day mean "
               f"the books use; next day: {s1['LGBM']['gain_vs_har_pct']:.1f} % vs HAR (DM p {s1['LGBM']['dm_p_vs_har']:.2g}). "
               + ("The forecast passes (better, significant, not worse than HAR in the last four quarters)."
                  if fc_pass else "The forecast does not pass the HAR bar."))
    md = (
        "# M6 · Daily volatility forecast for sizing\n\n"
        f"{p.height:,} coin-days, {len(UNIVERSE)} coins, walk-forward by quarter from 2021, 8-day embargo. "
        f"Took {(time.time() - t0) / 60:.0f} min.\n\n**Verdict:** {verdict}\n\n" + "\n".join(lines) + "\n\n"
        "## Forecast quality out of sample\n\n"
        + report.table(summary, ["target", "model", "qlike", "r2_log", "gain_vs_har_pct", "gain_vs_rw30_pct", "dm_p_vs_har"])
        + "\n## Books sized with each forecast (sel = 2021-2023, hold = 2024 on)\n\n"
        + report.table(book_rows, ["book", "sizing", "sel_sharpe_15bps", "hold_sharpe_15bps", "hold_sharpe_41bps",
                                   "hold_cagr_15bps", "hold_max_dd_15bps", "hold_vol", "vol_of_vol", "turnover_yr",
                                   "avg_exposure", "deflated_p_15bps", "deflated_p_41bps"])
        + f"\nDeflated over {n_trials} variants (the 50 momentum variants before plus these {len(book_rows)}).\n"
        + "\n## Per quarter, QLIKE\n\n"
        + report.table(fold_rows, ["target", "fold", "rows", "qlike_RW30", "qlike_EWMA", "qlike_EWMA-RV", "qlike_HAR", "qlike_LGBM"])
    )
    report.write("vol_daily", md, {"summary": summary, "books": book_rows, "folds": fold_rows,
                                   "forecast_passes": fc_pass, "n_trials": n_trials})
    if fc_pass and "--export" in __import__("sys").argv:
        export(p)


def export(p: pl.DataFrame) -> None:
    """Final 7-day model on all data, LightGBM JSON plus a card, into agent-models (not models/)."""
    import os
    from pathlib import Path
    yv = p["y7"].to_numpy().astype(float)
    ok = np.isfinite(yv) & (yv > 0) & p.select(pl.all_horizontal(pl.col(HAR_COLS).is_not_null())).to_series().to_numpy()
    X = p.select(FEATURES).to_numpy().astype(np.float32)[ok]
    ly = np.log(yv[ok] + EPS)
    m = lgb.LGBMRegressor(**PARAMS).fit(X, ly)
    resid = float(np.var(ly - m.predict(X)))
    Xh = p.select(HAR_COLS).to_numpy().astype(float)[ok]
    b = ols(Xh, ly)
    har_resid = float(np.var(ly - (b[0] + Xh @ b[1:])))
    out = Path(os.environ.get("PYTHIA_AGENT_MODELS", ROOT / "agent-models")) / "vol_daily_7d"
    out.mkdir(parents=True, exist_ok=True)
    (out / "model.json").write_text(json.dumps(m.booster_.dump_model()), encoding="utf-8")
    rng = np.random.default_rng(11)
    pick = rng.choice(len(X), size=64, replace=False)
    px = X[pick].astype(np.float64)
    px[:4, -4:] = np.nan  # the missing-perp path
    ts = p["day"].to_numpy()[ok]
    card = {
        "name": "vol_daily_7d", "created": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "target": "log of the mean daily realised variance over the next 7 UTC days (1m Binance spot log returns)",
        "output": "log variance per day; daily variance forecast = exp(output + residual_var / 2), daily sigma = sqrt of that",
        "residual_var": resid, "features": FEATURES,
        "feature_notes": "research/lab/lab/experiments/vol_daily.py coin_daily(), perp_feats(), build(); computed at the end of UTC day d",
        "train_from_us": int(ts.min()), "train_to_us": int(ts.max()), "rows": int(ok.sum()),
        "har": {"features": HAR_COLS, "intercept": float(b[0]), "coef": [float(x) for x in b[1:]], "residual_var": har_resid},
        "lightgbm_params": PARAMS,
        "probe": {"x": [[None if np.isnan(v) else float(v) for v in row] for row in px],
                  "raw": [float(v) for v in m.predict(px.astype(np.float32))]},
    }
    rep = json.loads((Path(report.REPORTS) / "vol_daily" / "latest.json").read_text(encoding="utf-8"))
    card["out_of_sample"] = rep["summary"]
    (out / "card.json").write_text(json.dumps(card, indent=2), encoding="utf-8")
    print(f"exported to {out}")


if __name__ == "__main__":
    main()
