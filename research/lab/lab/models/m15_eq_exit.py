"""M15: the remaining return of a held equity position over the next 10 days (X16 B1).

Pre-registered in results/equities_training_prereg.md. Rows: every day a
name is held by the X16 A1, A2 or A3 pick with its base exit (time stop).
Features: days held, log return since the entry fill, log distance below the
highest close since entry (and that over the 21-day vol), 5/21/63-day
momentum, 21-day vol, distance to the 52-week high, SPY's 21-day return and
200-day state, family. Target: the log return from the next open over 10
trading days, over (21-day daily vol x sqrt 10), clipped at +-5. LightGBM
regression; baseline the training mean per family; loss squared error; the
zoo's purged quarterly walk-forward from 2000 with a 16-day embargo.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import polars as pl

from ..equities import features as fe
from . import core
from .core import Spec

FEATURES = fe.M15_FEATURES

SPEC = Spec(
    code="M15", name="m15_eq_exit", title="Equity remaining return (exit model, 10 days)",
    target="log return of a held name from the next open over 10 trading days, over 21-day vol x sqrt 10",
    features=FEATURES, horizon="next 10 trading days", horizon_days=10,
    universe="names held by the X16 event books (A1, A2, A3 picks)", metric="mse",
    baseline="the training mean per family", every_days=0, first_test="2000-01-01", min_rows=500, min_days=60,
    min_train=5000, embargo_h=16 * 24, managed_by="retired",
    status_note="X16 B1: see results/equities_training.md for its gate.",
    use_rule="Nothing reads it unless its gate and X16 B1 pass.", results="equities_training.md",
)


def load() -> pl.DataFrame:
    from ..experiments import equities_training as et
    return et.m15_panel()


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
