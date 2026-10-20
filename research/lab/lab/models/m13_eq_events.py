"""M13: the next 20 days of an S&P 500 early-detection candidate, against SPY (X16 C).

Pre-registered in results/equities_training_prereg.md. Rows: every candidate
of the loosest breakout-on-volume (20-day high, volume 1.5x), gap-and-go (2 %)
and post-earnings (z >= 1) rules at the decision close, point-in-time members
from 1997. Target: the log return from the next open over 20 trading days
minus SPY's, over (63-day daily vol x sqrt 20), clipped at +-5. LightGBM
regression; baseline the training mean per family; loss squared error; the
zoo's purged quarterly walk-forward from 2000 with a 30-day embargo. Gate:
lower than the baseline with DM p under 0.05 (the study also applies Holm
over M13, M14 and M15).
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import polars as pl

from ..equities import features as fe
from . import core
from .core import Spec

FEATURES = fe.M13_FEATURES

SPEC = Spec(
    code="M13", name="m13_eq_events", title="Equity early-detection candidates (20 days vs SPY)",
    target="log return from the next open over 20 trading days minus SPY's, over 63-day vol x sqrt 20",
    features=FEATURES, horizon="next 20 trading days", horizon_days=20,
    universe="S&P 500 members (point in time) with a breakout, gap or earnings candidate", metric="mse",
    baseline="the training mean per family", every_days=0, first_test="2000-01-01", min_rows=500, min_days=60,
    min_train=5000, embargo_h=30 * 24, managed_by="retired",
    status_note="X16 C: see results/equities_training.md for its gate.",
    use_rule="Nothing reads it unless its gate and X16 C pass.", results="equities_training.md",
)


def load() -> pl.DataFrame:
    from ..experiments import equities_training as et
    return et.m13_panel()


def fit(frame: pl.DataFrame) -> dict:
    return fe.fit_lgb(frame.filter(pl.col("target").is_not_null()), FEATURES)


def predict(fitted: dict, frame: pl.DataFrame) -> np.ndarray:
    return fe.predict_lgb(fitted, frame, FEATURES)


def baseline(fitted: dict, frame: pl.DataFrame) -> np.ndarray:
    return fe.baseline_mean(fitted, frame)


def loss(y, p):
    return core.squared(y, p)


def save(fitted: dict, folder: Path) -> None:
    core.lgb_dump(fitted["model"], folder / "model.json")
    (folder / "params.json").write_text(json.dumps({"base": {str(k): v for k, v in fitted["base"].items()},
                                                    "mean": fitted["mean"]}), encoding="utf-8")


def restore(folder: Path) -> dict:
    p = json.loads((folder / "params.json").read_text(encoding="utf-8"))
    return {"model": core.lgb_load(folder / "model.json"), "base": {float(k): v for k, v in p["base"].items()},
            "mean": float(p["mean"])}
