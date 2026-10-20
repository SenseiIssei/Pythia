"""M8q: next-day return quantiles for the coins Alpaca lists.

Target: the next UTC day's close-to-close log return, forecast as its 10, 50
and 90 % quantiles. Same rows and inputs as M8 (m8_direction.py).

Model: three LightGBM quantile regressions on the return scaled by the
coin's 30-day volatility (sorted per row so the quantiles never cross),
scaled back. Baseline: the training window's empirical quantiles of the
scaled return, times today's volatility, i.e. "the usual spread for this
coin at today's volatility". Loss: the pinball loss averaged over the three
quantiles. Gate: lower than the baseline with a Diebold-Mariano p under 0.05
on the per-day mean loss.

History: this was M8's second head, gated together with direction. The first
real run (15 October 2026) showed direction losing to the base rate while the
quantiles beat theirs, so the two are separate models now. That split came
after seeing the numbers; with two heads looked at, a Bonferroni bar is
p < 0.025, and the results file reports the quantile p against it.

Use: a coin's 10 % quantile is a one-day value at risk at today's market,
the 90 % its upside. No book reads it yet; a sizing or stop study would.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import polars as pl

from . import core
from . import m8_direction as m8
from .core import Spec

ALPHAS = (0.1, 0.5, 0.9)
FEATURES = m8.FEATURES
QR = dict(n_estimators=200, learning_rate=0.03, num_leaves=7, min_child_samples=400, subsample=0.8,
          subsample_freq=1, colsample_bytree=0.8, reg_lambda=10.0, n_jobs=4, verbose=-1)

SPEC = Spec(
    code="M8q", name="m8_quantiles", title="Next-day return range (10/50/90 % quantiles)",
    target="the 10, 50 and 90 % quantiles of the next UTC day's close-to-close log return",
    features=FEATURES, horizon="next UTC day", horizon_days=1,
    universe="the 15 coins the Alpaca paper account lists", metric="pinball",
    baseline="the training window's quantiles of the vol-scaled return, times today's 30-day vol",
    every_days=7, weekday=6, margin=0.0, first_test="2021-01-01", min_rows=300, min_days=21, min_train=2000,
    calendar=("dow_next",),
    use_rule="Informational. Only the 90 % quantile has skill (X9: q10 DM p 0.91); never offer q10 or q50 to a "
             "book. M8u (m8_upper) is the upper tail on its own; a trim on it failed (X11 c).",
    results="model_zoo.md",
)


def load() -> pl.DataFrame:
    return panel_from(m8.coins_panel())


def panel_from(p: pl.DataFrame) -> pl.DataFrame:
    """target = tomorrow's log return, null where tomorrow is not known yet."""
    return m8.panel_from(p).with_columns(target=pl.col("ret_next"))


def _X(frame: pl.DataFrame) -> np.ndarray:
    return frame.select(FEATURES).fill_null(np.nan).to_numpy().astype(np.float64)


def fit(frame: pl.DataFrame) -> dict:
    import lightgbm as lgb
    X = _X(frame)
    z = frame["z_next"].to_numpy().astype(float)
    ok = np.isfinite(z)
    qr = {a: lgb.LGBMRegressor(objective="quantile", alpha=a, **QR).fit(X[ok], z[ok]).booster_ for a in ALPHAS}
    return {"qr": qr, "base_q": {a: float(np.quantile(z[ok], a)) for a in ALPHAS}}


def predict(fitted: dict, frame: pl.DataFrame) -> np.ndarray:
    """(rows, 3): the 10, 50 and 90 % quantiles of tomorrow's log return."""
    X, s = _X(frame), frame["sigma"].to_numpy().astype(float)
    m = np.sort(np.column_stack([fitted["qr"][a].predict(X) for a in ALPHAS]), axis=1)
    return m * s[:, None]


def baseline(fitted: dict, frame: pl.DataFrame) -> np.ndarray:
    s = frame["sigma"].to_numpy().astype(float)
    return np.array([fitted["base_q"][a] for a in ALPHAS])[None, :] * s[:, None]


def loss(y, q):
    """Pinball loss per row, averaged over the three quantiles."""
    y, q = np.asarray(y, float), np.asarray(q, float)
    return np.mean([core.pinball(y, q[:, i], a) for i, a in enumerate(ALPHAS)], axis=0)


def extra(fitted: dict, panel: pl.DataFrame, ev: dict) -> dict:
    """Per quantile: pinball against the baseline with its own DM test, coverage; today's ranges."""
    from ..metrics import diebold_mariano
    h = ev["holdout"]
    if h.is_empty():
        return {}
    y = h["target"].to_numpy().astype(float)
    qm, qb = core.as_array(h["challenger"]), core.as_array(h["baseline_pred"])
    ts = h["ts_us"].to_numpy()
    per = []
    for i, a in enumerate(ALPHAS):
        lm, lb = core.pinball(y, qm[:, i], a), core.pinball(y, qb[:, i], a)
        st, p = diebold_mariano(core.per_period(ts, lm), core.per_period(ts, lb), lag=1)
        per.append({"quantile": f"q{int(a * 100)}", "pinball_bps": float(lm.mean() * 1e4),
                    "baseline_bps": float(lb.mean() * 1e4), "dm_p": p,
                    "coverage": float(np.mean(y <= qm[:, i])), "baseline_coverage": float(np.mean(y <= qb[:, i]))})
    width_m = float(np.mean(qm[:, 2] - qm[:, 0]))
    width_b = float(np.mean(qb[:, 2] - qb[:, 0]))
    inside = float(np.mean((y >= qm[:, 0]) & (y <= qm[:, 2])))
    latest = panel.filter(pl.col("target").is_null())
    today = []
    if not latest.is_empty():
        latest = latest.filter(pl.col("ts_us") == latest["ts_us"].max())
        q = predict(fitted, latest)
        today = [{"symbol": s, **{f"q{int(a * 100)}": float(q[j, i]) for i, a in enumerate(ALPHAS)}}
                 for j, s in enumerate(latest["symbol"].to_list())]
    return core.finite({"per_quantile": per, "band_width": width_m, "band_width_baseline": width_b,
                        "inside_10_90": inside, "today": today,
                        "today_from": core.iso(int(latest["ts_us"].max())) if not latest.is_empty() else None})


def save(fitted: dict, folder: Path) -> None:
    # model.json is the median booster (what the registry and the engine look for); q10 and q90 beside it.
    for a, bst in fitted["qr"].items():
        core.lgb_dump(bst, folder / ("model.json" if a == 0.5 else f"q{int(a * 100)}.json"))
    (folder / "params.json").write_text(json.dumps({"base_q": {str(a): v for a, v in fitted["base_q"].items()}}),
                                        encoding="utf-8")


def restore(folder: Path) -> dict:
    p = json.loads((folder / "params.json").read_text(encoding="utf-8"))
    return {"qr": {a: core.lgb_load(folder / ("model.json" if a == 0.5 else f"q{int(a * 100)}.json")) for a in ALPHAS},
            "base_q": {float(k): v for k, v in p["base_q"].items()}}
