"""M8u: the next day's 90 % return quantile for the coins Alpaca lists (X11 c).

X9 found M8q's skill only in its upper tail: the 90 % quantile beat its
baseline with DM p 7e-12, the 10 % quantile not at all (p 0.91). M8u keeps
only what works, pre-registered in results/model_upgrades_prereg.md (c1):

Target: the 90 % quantile of the next UTC day's close-to-close log return.
Model: one LightGBM quantile regression (alpha 0.9) on the return scaled by the
coin's 30-day volatility, M8q's inputs and parameters, scaled back.
Baseline: the training window's 90 % quantile of the scaled return times
today's volatility. Loss: the 0.9 pinball. Gate: lower than the baseline with
a Diebold-Mariano p under 0.05.

`ratio` (the forecast over the baseline's) is what the trim study reads:
below 1 the model expects less upside than usual at today's vol.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import polars as pl

from . import core
from . import m8_direction as m8
from . import m8_quantiles as m8q
from .core import Spec

ALPHA = 0.9
FEATURES = m8.FEATURES

SPEC = Spec(
    code="M8u", name="m8_upper", title="Next-day upside (90 % quantile)",
    target="the 90 % quantile of the next UTC day's close-to-close log return",
    features=FEATURES, horizon="next UTC day", horizon_days=1,
    universe="the 15 coins the Alpaca paper account lists", metric="pinball90",
    baseline="the training window's 90 % quantile of the vol-scaled return, times today's 30-day vol",
    every_days=7, weekday=6, margin=0.0, first_test="2021-01-01", min_rows=300, min_days=21, min_train=2000,
    calendar=("dow_next",),
    use_rule="Informational: tomorrow's upside per coin. A book may use it only through its own "
             "pre-registered study (X11 c2 tested a trim); nothing reads it today.",
    results="model_upgrades.md",
)


def load() -> pl.DataFrame:
    return m8q.load()


def _X(frame: pl.DataFrame) -> np.ndarray:
    return frame.select(FEATURES).fill_null(np.nan).to_numpy().astype(np.float64)


def fit(frame: pl.DataFrame) -> dict:
    import lightgbm as lgb
    X = _X(frame)
    z = frame["z_next"].to_numpy().astype(float)
    ok = np.isfinite(z)
    qr = lgb.LGBMRegressor(objective="quantile", alpha=ALPHA, **m8q.QR).fit(X[ok], z[ok]).booster_
    return {"qr": qr, "base_q": float(np.quantile(z[ok], ALPHA))}


def predict(fitted: dict, frame: pl.DataFrame) -> np.ndarray:
    return fitted["qr"].predict(_X(frame)) * frame["sigma"].to_numpy().astype(float)


def baseline(fitted: dict, frame: pl.DataFrame) -> np.ndarray:
    return fitted["base_q"] * frame["sigma"].to_numpy().astype(float)


def side(fitted: dict, frame: pl.DataFrame) -> dict[str, np.ndarray]:
    """The forecast over the baseline's (scale-free), kept in the holdout as x_ratio."""
    with np.errstate(invalid="ignore", divide="ignore"):
        return {"ratio": fitted["qr"].predict(_X(frame)) / fitted["base_q"]}


def loss(y, q):
    return core.pinball(np.asarray(y, float), np.asarray(q, float), ALPHA)


def extra(fitted: dict, panel: pl.DataFrame, ev: dict) -> dict:
    h = ev["holdout"]
    if h.is_empty():
        return {}
    y = h["target"].to_numpy().astype(float)
    qm, qb = h["challenger"].to_numpy().astype(float), h["baseline_pred"].to_numpy().astype(float)
    latest = panel.filter(pl.col("target").is_null())
    today = []
    if not latest.is_empty():
        latest = latest.filter(pl.col("ts_us") == latest["ts_us"].max())
        q = predict(fitted, latest)
        r = side(fitted, latest)["ratio"]
        today = [{"symbol": s, "q90": float(a), "ratio": float(b)} for s, a, b in zip(latest["symbol"].to_list(), q, r)]
    return core.finite({"coverage": float(np.mean(y <= qm)), "baseline_coverage": float(np.mean(y <= qb)),
                        "today": today,
                        "today_from": core.iso(int(latest["ts_us"].max())) if not latest.is_empty() else None})


def save(fitted: dict, folder: Path) -> None:
    core.lgb_dump(fitted["qr"], folder / "model.json")
    (folder / "params.json").write_text(json.dumps({"base_q": fitted["base_q"], "alpha": ALPHA}), encoding="utf-8")


def restore(folder: Path) -> dict:
    p = json.loads((folder / "params.json").read_text(encoding="utf-8"))
    return {"qr": core.lgb_load(folder / "model.json"), "base_q": float(p["base_q"])}
