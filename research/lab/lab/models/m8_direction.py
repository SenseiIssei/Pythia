"""M8: next-day direction and return quantiles for the coins Alpaca lists.

Target: the sign of the next UTC day's close-to-close log return, and its 10,
50 and 90 % quantiles. Features are known at the close of day d: returns over
1 to 30 days, realised-variance terms, trend gaps, volume shocks, the coin
against the market, BTC and market-wide returns and volatility, breadth.

Model: a small LightGBM classifier on the first 80 % of each training window,
Platt-calibrated on the last 20 % (so the probabilities mean what they say),
and three LightGBM quantile regressions on the return scaled by its 30-day
volatility. Baseline: the training window's share of up days (a constant
probability) and the training window's empirical quantiles of the scaled
return, times today's volatility.

Gate: lower log loss than the base rate out of sample with a Diebold-Mariano
p under 0.05, and lower average pinball loss over the three quantiles. Used
only if it passes; today nothing reads it but the Models page.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import polars as pl

from . import core, daily
from .core import Spec

ALPHAS = (0.1, 0.5, 0.9)
FEATURES = ["ret1", "ret3", "ret7", "ret14", "ret30", "h1", "h7", "h30", "dist_hi30", "ma50_gap", "ma200_gap",
            "qv_z", "tr_z", "rel_ret7", "rel_h7", "btc_ret1", "btc_ret7", "mkt_ret1", "mkt_ret7", "mkt_h7",
            "xs_disp", "breadth50", "dow_next"]
CLF = dict(n_estimators=200, learning_rate=0.03, num_leaves=7, min_child_samples=400, subsample=0.8,
           subsample_freq=1, colsample_bytree=0.8, reg_lambda=10.0, n_jobs=4, verbose=-1)
QR = dict(n_estimators=200, learning_rate=0.03, num_leaves=7, min_child_samples=400, subsample=0.8,
          subsample_freq=1, colsample_bytree=0.8, reg_lambda=10.0, n_jobs=4, verbose=-1)

SPEC = Spec(
    code="M8", name="m8_direction", title="Next-day direction and return quantiles",
    target="P(next UTC day's close-to-close return > 0), plus its 10/50/90 % quantiles",
    features=FEATURES, horizon="next UTC day", horizon_days=1,
    universe="the 15 coins the Alpaca paper account lists", metric="logloss",
    baseline="the training window's share of up days; its empirical return quantiles times 30-day vol",
    every_days=7, weekday=6, margin=0.001, first_test="2021-01-01", min_rows=300, min_days=21, min_train=2000,
    calendar=("dow_next",),
    use_rule="Informational. May be offered to a book only after it beats the base rate out of sample (gate) "
             "and live in shadow for 90 days; nothing reads it today.",
    results="model_zoo.md",
)


def load() -> pl.DataFrame:
    return panel_from(daily.daily_panel(daily.ALPACA))


def panel_from(p: pl.DataFrame) -> pl.DataFrame:
    """target = 1.0 if tomorrow is up, 0.0 if not, null where tomorrow is not known yet."""
    return p.with_columns(
        target=pl.when(pl.col("ret_next").is_null()).then(None).otherwise((pl.col("ret_next") > 0).cast(pl.Float64)),
        z_next=pl.col("ret_next") / pl.col("sigma"),
    ).filter(pl.col("sigma").is_not_null() & (pl.col("sigma") > 0))


def _X(frame: pl.DataFrame) -> np.ndarray:
    return frame.select(FEATURES).fill_null(np.nan).to_numpy().astype(np.float64)


def fit(frame: pl.DataFrame) -> dict:
    import lightgbm as lgb
    frame = frame.sort("ts_us")
    X, y = _X(frame), frame["target"].to_numpy().astype(float)
    ts = frame["ts_us"].to_numpy()
    cut = np.quantile(ts, 0.8)
    a, b = ts < cut, ts >= cut
    clf = lgb.LGBMClassifier(**CLF).fit(X[a], y[a])
    raw = clf.booster_.predict(X[b], raw_score=True)
    pa, pb = platt(raw, y[b])
    z = frame["z_next"].to_numpy().astype(float)
    okz = np.isfinite(z)
    qs = {a_: lgb.LGBMRegressor(objective="quantile", alpha=a_, **QR).fit(X[okz], z[okz]).booster_ for a_ in ALPHAS}
    return {"clf": clf.booster_, "platt": (pa, pb), "qr": qs, "base_rate": float(np.mean(y)),
            "base_q": {a_: float(np.quantile(z[okz], a_)) for a_ in ALPHAS}}


def platt(raw: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    """Logistic regression of the label on the raw score: p = 1 / (1 + exp(-(a * raw + b)))."""
    from sklearn.linear_model import LogisticRegression
    if len(np.unique(y)) < 2:
        return 1.0, 0.0
    lr = LogisticRegression(C=1.0).fit(raw.reshape(-1, 1), y)
    return float(lr.coef_[0, 0]), float(lr.intercept_[0])


def predict(fitted: dict, frame: pl.DataFrame) -> np.ndarray:
    raw = fitted["clf"].predict(_X(frame), raw_score=True)
    a, b = fitted["platt"]
    return 1 / (1 + np.exp(-(a * raw + b)))


def baseline(fitted: dict, frame: pl.DataFrame) -> np.ndarray:
    return np.full(frame.height, fitted["base_rate"])


def loss(y, p):
    return core.logloss(y, p)


def quantiles(fitted: dict, frame: pl.DataFrame) -> dict[float, np.ndarray]:
    X, s = _X(frame), frame["sigma"].to_numpy().astype(float)
    qs = {a: fitted["qr"][a].predict(X) for a in ALPHAS}
    # Quantile crossing: sort per row, then scale back to returns.
    m = np.sort(np.column_stack([qs[a] for a in ALPHAS]), axis=1)
    return {a: m[:, i] * s for i, a in enumerate(ALPHAS)}


def side(fitted: dict, frame: pl.DataFrame) -> dict[str, np.ndarray]:
    s = frame["sigma"].to_numpy().astype(float)
    out = {f"q{int(a * 100)}": v for a, v in quantiles(fitted, frame).items()}
    out.update({f"bq{int(a * 100)}": fitted["base_q"][a] * s for a in ALPHAS})
    return out


def _pinballs(h: pl.DataFrame) -> tuple[float, float]:
    y = h["ret_next"].to_numpy().astype(float)
    m = np.mean([np.mean(core.pinball(y, h[f"x_q{int(a * 100)}"].to_numpy(), a)) for a in ALPHAS])
    b = np.mean([np.mean(core.pinball(y, h[f"x_bq{int(a * 100)}"].to_numpy(), a)) for a in ALPHAS])
    return float(m), float(b)


def gate_extra(ev: dict) -> tuple[bool, str]:
    m, b = _pinballs(ev["holdout"])
    return m < b, f"quantile pinball {m * 1e4:.2f} vs {b * 1e4:.2f} bps for the baseline ({'lower' if m < b else 'not lower'})"


def extra(fitted: dict, panel: pl.DataFrame, ev: dict) -> dict:
    """Calibration, AUC, Brier, hit rate, quantile coverage and today's forecasts."""
    h = ev["holdout"]
    if h.is_empty():
        return {}
    from sklearn.metrics import roc_auc_score
    y, p = h["target"].to_numpy().astype(float), h["challenger"].to_numpy()
    pb = h["baseline_pred"].to_numpy()
    bins = np.clip((p * 10).astype(int), 0, 9)
    calib = [{"bin": f"{i / 10:.1f}-{(i + 1) / 10:.1f}", "rows": int((bins == i).sum()),
              "predicted": float(p[bins == i].mean()), "observed": float(y[bins == i].mean())}
             for i in range(10) if (bins == i).sum() >= 30]
    r = h["ret_next"].to_numpy().astype(float)
    pin_m, pin_b = _pinballs(h)
    cover = {f"q{int(a * 100)}": float(np.mean(r <= h[f"x_q{int(a * 100)}"].to_numpy())) for a in ALPHAS}
    latest = panel.filter(pl.col("target").is_null())
    today = []
    if not latest.is_empty():
        latest = latest.filter(pl.col("ts_us") == latest["ts_us"].max())
        pu, q = predict(fitted, latest), quantiles(fitted, latest)
        today = [{"symbol": s, "p_up": float(pu[i]), **{f"q{int(a * 100)}": float(q[a][i]) for a in ALPHAS}}
                 for i, s in enumerate(latest["symbol"].to_list())]
    return core.finite({
        "auc": float(roc_auc_score(y, p)) if len(np.unique(y)) == 2 else None,
        "brier": float(np.mean((p - y) ** 2)), "brier_baseline": float(np.mean((pb - y) ** 2)),
        "hit_rate": float(np.mean((p > 0.5) == (y > 0.5))), "up_share": float(y.mean()),
        "pinball_bps": pin_m * 1e4, "pinball_baseline_bps": pin_b * 1e4, "coverage": cover,
        "calibration": calib, "today": today,
        "today_from": core.iso(int(latest["ts_us"].max())) if not latest.is_empty() else None,
    })


def save(fitted: dict, folder: Path) -> None:
    core.lgb_dump(fitted["clf"], folder / "model.json")
    for a, bst in fitted["qr"].items():
        core.lgb_dump(bst, folder / f"q{int(a * 100)}.json")
    (folder / "params.json").write_text(json.dumps({
        "platt": list(fitted["platt"]), "base_rate": fitted["base_rate"],
        "base_q": {str(a): v for a, v in fitted["base_q"].items()}}), encoding="utf-8")


def restore(folder: Path) -> dict:
    p = json.loads((folder / "params.json").read_text(encoding="utf-8"))
    return {"clf": core.lgb_load(folder / "model.json"), "platt": tuple(p["platt"]), "base_rate": p["base_rate"],
            "qr": {a: core.lgb_load(folder / f"q{int(a * 100)}.json") for a in ALPHAS},
            "base_q": {float(k): v for k, v in p["base_q"].items()}}
