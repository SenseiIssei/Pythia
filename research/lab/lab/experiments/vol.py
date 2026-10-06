"""Next-hour volatility forecast. Masterplan phase 4, the model with the best odds.

Direction is barely predictable; volatility clusters and is. This model feeds
position sizing, stop distances and the triple-barrier labels later on.

Target: log realised variance of the next hour, from 1m Binance spot log returns.
Baselines every candidate has to beat out of sample:
  naive  next hour = this hour
  HAR    Corsi's heterogeneous autoregression on 1h / 24h / 168h realised variance
Candidate:
  LGBM   gradient boosting on HAR terms plus range, volume, order flow, seasonality and BTC

Walk-forward by quarter from 2021, 24 h embargo, all coins pooled. Losses: MSE in
log space (reported as R^2) and QLIKE on the variance itself. Diebold-Mariano
says whether the LGBM gain over HAR is more than noise.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone

import lightgbm as lgb
import numpy as np
import polars as pl

from .. import report
from ..cv import HOUR_US, walk_forward
from ..data import ROOT, UNIVERSE, hourly
from ..metrics import diebold_mariano, qlike, r2

EPS = 1e-10
FIRST_TEST = int(datetime(2021, 1, 1, tzinfo=timezone.utc).timestamp() * 1e6)
HAR_COLS = ["har1", "har24", "har168"]
LGBM_PARAMS = dict(n_estimators=500, learning_rate=0.03, num_leaves=63, min_child_samples=500,
                   subsample=0.8, subsample_freq=1, colsample_bytree=0.8, reg_lambda=1.0,
                   n_jobs=4, verbose=-1)


def features(h: pl.DataFrame) -> pl.DataFrame:
    lrv = (pl.col("rv") + EPS).log()
    lvol = (pl.col("volume_q") + 1.0).log()
    ltr = (pl.col("trades") + 1.0).log()
    hour = (pl.col("ts_us") // HOUR_US) % 24
    f = h.with_columns(lrv=lrv).with_columns(
        y=pl.col("lrv").shift(-1),
        y_var=pl.col("rv").shift(-1),
        y_contiguous=(pl.col("ts_us").shift(-1) - pl.col("ts_us")) == HOUR_US,
        har1=pl.col("lrv"),
        har6=(pl.col("rv").rolling_mean(6) + EPS).log(),
        har24=(pl.col("rv").rolling_mean(24) + EPS).log(),
        har168=(pl.col("rv").rolling_mean(168) + EPS).log(),
        lrv_l1=pl.col("lrv").shift(1),
        lrv_l2=pl.col("lrv").shift(2),
        absret=pl.col("ret").abs(),
        negret=pl.min_horizontal(pl.col("ret"), pl.lit(0.0)),
        ret24=pl.col("ret").rolling_sum(24),
        park=((pl.col("high") / pl.col("low")).log() ** 2 + EPS).log(),
        vol_z=lvol - lvol.rolling_mean(168),
        trades_z=ltr - ltr.rolling_mean(168),
        taker=pl.col("taker_buy_q") / (pl.col("volume_q") + 1e-9) - 0.5,
        seasonal=pl.mean_horizontal([pl.col("lrv").shift(24 * k) for k in range(1, 8)]),
        hsin=(hour * (2 * np.pi / 24)).sin(),
        hcos=(hour * (2 * np.pi / 24)).cos(),
        dow=((pl.col("ts_us") // (24 * HOUR_US)) + 3) % 7,
    )
    return f.with_columns(seasonal=pl.col("seasonal") - pl.col("har168"))


FEATURES = ["har1", "har6", "har24", "har168", "lrv_l1", "lrv_l2", "absret", "negret", "ret24",
            "park", "vol_z", "trades_z", "taker", "seasonal", "hsin", "hcos", "dow",
            "btc_har1", "btc_har24", "btc_ret", "rel_har1"]


def build_panel() -> pl.DataFrame:
    frames = {}
    for b in UNIVERSE:
        t = time.time()
        h = hourly(f"{b}USDT")
        if h.is_empty():
            continue
        frames[b] = features(h)
        print(f"{b}: {h.height} hours, {time.time() - t:.0f}s", flush=True)
    btc = frames["BTC"].select("ts_us", btc_har1="har1", btc_har24="har24", btc_ret="ret")
    panel = pl.concat([
        f.join(btc, on="ts_us", how="left").with_columns(rel_har1=pl.col("har1") - pl.col("btc_har1"))
        for f in frames.values()
    ], how="vertical_relaxed")
    return (panel.filter(pl.col("y_contiguous") & (pl.col("rv") > 0) & (pl.col("y_var") > 0))
            .drop_nulls(FEATURES + ["y"]).sort("ts_us"))


def ols(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    X = np.column_stack([np.ones(len(x)), x])
    return np.linalg.lstsq(X, y, rcond=None)[0]


def ols_pred(beta: np.ndarray, x: np.ndarray) -> np.ndarray:
    return beta[0] + x @ beta[1:]


def main() -> None:
    t_start = time.time()
    panel = build_panel()
    ts = panel["ts_us"].to_numpy()
    X = panel.select(FEATURES).to_numpy().astype(np.float32)
    Xh = panel.select(HAR_COLS).to_numpy()
    y = panel["y"].to_numpy()
    yvar = panel["y_var"].to_numpy()
    sym = panel["symbol"].to_numpy()
    print(f"panel: {panel.height:,} rows, {len(FEATURES)} features", flush=True)

    preds = {m: np.full(len(y), np.nan) for m in ("naive", "har", "lgbm")}
    resid_var = {m: np.full(len(y), np.nan) for m in preds}
    fold_rows = []
    for fold in walk_forward(ts, FIRST_TEST):
        t = time.time()
        tr, te = fold.train, fold.test
        # naive
        preds["naive"][te] = Xh[te, 0]
        resid_var["naive"][te] = np.var(y[tr] - Xh[tr, 0])
        # HAR
        beta = ols(Xh[tr], y[tr])
        preds["har"][te] = ols_pred(beta, Xh[te])
        resid_var["har"][te] = np.var(y[tr] - ols_pred(beta, Xh[tr]))
        # LGBM
        m = lgb.LGBMRegressor(**LGBM_PARAMS).fit(X[tr], y[tr])
        preds["lgbm"][te] = m.predict(X[te])
        resid_var["lgbm"][te] = np.var(y[tr] - m.predict(X[tr]))
        row = {"fold": fold.name, "train_rows": int(tr.sum()), "test_rows": int(te.sum())}
        for k in preds:
            row[f"r2_{k}"] = r2(y[te], preds[k][te])
            row[f"qlike_{k}"] = float(np.mean(qlike(yvar[te], np.exp(preds[k][te] + resid_var[k][te] / 2))))
        fold_rows.append(row)
        print(f"{fold.name}: r2 har {row['r2_har']:.3f} lgbm {row['r2_lgbm']:.3f}  "
              f"qlike har {row['qlike_har']:.4f} lgbm {row['qlike_lgbm']:.4f}  ({time.time() - t:.0f}s)", flush=True)

    ok = ~np.isnan(preds["lgbm"])
    losses = {k: qlike(yvar[ok], np.exp(preds[k][ok] + resid_var[k][ok] / 2)) for k in preds}
    summary = {k: {"r2": r2(y[ok], preds[k][ok]), "qlike": float(losses[k].mean())} for k in preds}
    dm_stat, dm_p = diebold_mariano(losses["lgbm"], losses["har"])
    gain = 1 - summary["lgbm"]["qlike"] / summary["har"]["qlike"]

    sym_rows = []
    for s in np.unique(sym[ok]):
        mk = sym[ok] == s
        sym_rows.append({"symbol": s, "hours": int(mk.sum()),
                         "r2_har": r2(y[ok][mk], preds["har"][ok][mk]),
                         "r2_lgbm": r2(y[ok][mk], preds["lgbm"][ok][mk]),
                         "qlike_gain_pct": float(100 * (1 - losses["lgbm"][mk].mean() / losses["har"][mk].mean()))})
    sym_rows.sort(key=lambda r: -r["qlike_gain_pct"])

    # Final model on everything, exported for the Rust engine.
    final = lgb.LGBMRegressor(**LGBM_PARAMS).fit(X, y)
    final_resid = float(np.var(y - final.predict(X)))
    importance = sorted(zip(FEATURES, final.booster_.feature_importance("gain")), key=lambda x: -x[1])
    har_beta = ols(Xh, y)
    har_resid = float(np.var(y - ols_pred(har_beta, Xh)))
    passed = gain > 0 and dm_p < 0.05 and all(r["qlike_lgbm"] <= r["qlike_har"] * 1.02 for r in fold_rows[-4:])
    # Only a model that passes is published where the engine looks (models/vol_1h/<date>).
    # A failing retrain goes to vol_1h_rejected and the engine keeps the last good one.
    model_dir = export_model(final, X, final_resid, summary, gain, dm_p, ts, har_beta, har_resid,
                             "vol_1h" if passed else "vol_1h_rejected")
    verdict = (f"LGBM beats HAR by {gain * 100:.1f} % QLIKE out of sample (DM p = {dm_p:.2g}). "
               + ("It passes: better overall, significant, and not worse than HAR in any of the last four quarters."
                  if passed else "It does not pass the bar yet: the gain is not significant or not stable in recent quarters."))
    md = (
        "# Next-hour volatility forecast\n\n"
        f"{panel.height:,} coin-hours, {len(np.unique(sym))} coins, walk-forward by quarter from 2021, "
        f"{len(fold_rows)} folds, 24 h embargo. Run took {(time.time() - t_start) / 60:.0f} min.\n\n"
        f"**Verdict:** {verdict}\n\n"
        "## Out of sample, all folds\n\n"
        + report.table([{"model": k, **v} for k, v in summary.items()], ["model", "r2", "qlike"])
        + "\n## Per quarter\n\n"
        + report.table(fold_rows, ["fold", "test_rows", "r2_naive", "r2_har", "r2_lgbm", "qlike_har", "qlike_lgbm"])
        + "\n## Per coin\n\n"
        + report.table(sym_rows, ["symbol", "hours", "r2_har", "r2_lgbm", "qlike_gain_pct"])
        + "\n## What the final model uses (gain)\n\n"
        + report.table([{"feature": f, "gain_pct": 100 * g / sum(x[1] for x in importance)} for f, g in importance],
                       ["feature", "gain_pct"])
        + f"\nExported to `{model_dir}`.\n"
    )
    report.write("vol_1h", md, {"summary": summary, "qlike_gain": gain, "dm_stat": dm_stat, "dm_p": dm_p,
                                "passed": passed, "folds": fold_rows, "coins": sym_rows,
                                "importance": [(f, float(g)) for f, g in importance], "model_dir": str(model_dir)})


CALENDAR = {"hsin", "hcos", "dow"}  # set by the clock, not the market: nothing to drift


def drift_bins(col: np.ndarray) -> dict:
    """Reference for the engine's drift check: decile edges with ties collapsed, the
    share of training rows in each bin under the same `value <= edge` rule the
    engine uses, and the 0.5 % / 99.5 % range the trees have actually seen."""
    v = col[np.isfinite(col)].astype(np.float64)
    edges = np.unique(np.quantile(v, np.linspace(0.1, 0.9, 9)))
    idx = np.searchsorted(edges, v, side="left")  # first edge >= value, i.e. value <= edge
    expected = np.bincount(idx, minlength=len(edges) + 1) / len(v)
    return {"edges": [float(e) for e in edges], "expected": [float(x) for x in expected],
            "lo": float(np.quantile(v, 0.005)), "hi": float(np.quantile(v, 0.995))}


def export_model(model, X, resid_var, summary, gain, dm_p, ts, har_beta, har_resid, folder="vol_1h"):
    """Writes model.json (LightGBM's own tree dump, what the Rust engine evaluates),
    model.onnx (for tools that speak ONNX), and card.json.

    The card carries everything the engine needs to trust the file: the feature
    order, the HAR baseline it is scored against live, per-feature deciles of
    the training data for drift checks, and probe rows with the exact outputs
    LightGBM produced. The engine refuses a model whose probes do not match.
    """
    import onnxruntime as ort
    from onnxmltools import convert_lightgbm
    from onnxmltools.convert.common.data_types import FloatTensorType

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    d = ROOT / "models" / folder / stamp
    d.mkdir(parents=True, exist_ok=True)
    onx = convert_lightgbm(model, initial_types=[("features", FloatTensorType([None, X.shape[1]]))],
                           target_opset=15)
    (d / "model.onnx").write_bytes(onx.SerializeToString())
    sess = ort.InferenceSession(str(d / "model.onnx"))
    probe = X[-5000:]
    got = sess.run(None, {"features": probe})[0].ravel()
    max_err = float(np.max(np.abs(got - model.predict(probe))))
    if max_err > 1e-4:
        raise RuntimeError(f"ONNX output differs from LightGBM by {max_err}")
    (d / "model.json").write_text(json.dumps(model.booster_.dump_model()))
    rng = np.random.default_rng(11)
    pick = rng.choice(len(X), size=64, replace=False)
    probe_x = X[pick].astype(np.float64)
    probe_x[:4, :5] = np.nan  # make sure the missing-value path is exercised too
    deciles = np.linspace(0.1, 0.9, 9)
    card = {
        "probe": {"x": [[None if np.isnan(v) else float(v) for v in row] for row in probe_x],
                  "raw": [float(v) for v in model.predict(probe_x.astype(np.float32))]},
        "har": {"features": HAR_COLS, "intercept": float(har_beta[0]),
                "coef": [float(b) for b in har_beta[1:]], "residual_var": har_resid},
        "feature_deciles": {f: [float(q) for q in np.nanquantile(X[:, i], deciles)] for i, f in enumerate(FEATURES)},
        "feature_bins": {f: drift_bins(X[:, i]) for i, f in enumerate(FEATURES) if f not in CALENDAR},
        "name": "vol_1h",
        "created": stamp,
        "target": "log realised variance of the next hour, sum of squared 1m log returns, Binance spot",
        "output": "log variance; variance forecast = exp(output + residual_var / 2)",
        "residual_var": resid_var,
        "features": FEATURES,
        "feature_notes": "see research/lab/lab/experiments/vol.py features(); BTC columns come from BTCUSDT at the same hour",
        "train_from_us": int(ts.min()), "train_to_us": int(ts.max()),
        "out_of_sample": summary, "qlike_gain_vs_har": gain, "dm_p_vs_har": dm_p,
        "onnx_max_abs_err": max_err,
        "lightgbm_params": LGBM_PARAMS,
    }
    (d / "card.json").write_text(json.dumps(card, indent=2))
    return d


if __name__ == "__main__":
    main()
