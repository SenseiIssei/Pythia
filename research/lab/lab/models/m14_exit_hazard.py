"""M14: the remaining return of a coin a long-only crypto book holds, next 10 days (X16 B2).

Pre-registered in results/equities_training_prereg.md. Rows: every coin-day
held after the close by the original breakout_top10 or tsmom_top20 (every
coin, the survivorship-free daily panel), from 2020-08-01. Features: days
held (the longer spell of the two books), log return since the spell's entry
close, log distance below the spell's highest close and that in ATR(14)
units, 7 and 28-day momentum, 30-day vol, 7 over 30-day vol, log distance to
the 50-day average, 7 over 28-day quote volume, BTC's 28-day return and
200-day state. Target: the next 10 days' log return over (30-day vol x
sqrt 10), clipped at +-5. LightGBM regression (lab.equities.features.PARAMS);
baseline the training mean; loss squared error; the zoo's purged quarterly
walk-forward from 2021 with an 11-day embargo.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import polars as pl

from ..equities import features as fe
from . import core
from .core import Spec

FEATURES = ["days_held", "ret_entry", "dd_peak", "dd_atr", "mom7", "mom28", "vol30", "vol_ratio", "dist_ma50",
            "qv_ratio", "btc_mom28", "btc_on"]
H = 10

SPEC = Spec(
    code="M14", name="m14_exit_hazard", title="Crypto remaining return (exit model, 10 days)",
    target="next 10 days' log return of a held coin over 30-day vol x sqrt 10",
    features=FEATURES, horizon="next 10 days", horizon_days=10,
    universe="coins held by breakout_top10 or tsmom_top20 (original books, every coin)", metric="mse",
    baseline="the training mean", every_days=0, first_test="2021-01-01", min_rows=300, min_days=30,
    min_train=2000, embargo_h=11 * 24, managed_by="retired",
    status_note="Failed its gate in X16 (2026-10-20): squared error 1.090 vs 1.049 for the training mean "
                "(3.9 % higher), DM p 0.27, 8 of 23 quarters better, 16,140 out-of-fold coin-days from 2021. It "
                "times the market (BTC's 28-day return is 31 % of its gain) rather than the coin. Used by nothing.",
    use_rule="Nothing trades on it. A frozen fit (lab/models/frozen/m14_exit_shadow.txt) is read only by the "
             "pre-registered exit shadow (results/exit_shadow_prereg.md), which writes records, never orders.",
    results="exit_overlays.md",
)


def load() -> pl.DataFrame:
    from ..experiments import exit_overlays as xo
    return xo.m14_panel()


def fit(frame: pl.DataFrame) -> dict:
    return fe.fit_lgb(frame.filter(pl.col("target").is_not_null()), FEATURES)


def predict(fitted: dict, frame: pl.DataFrame) -> np.ndarray:
    return fe.predict_lgb(fitted, frame, FEATURES)


def baseline(fitted: dict, frame: pl.DataFrame) -> np.ndarray:
    return np.full(frame.height, fitted["mean"])


def loss(y, p):
    return core.squared(y, p)


def save(fitted: dict, folder: Path) -> None:
    core.lgb_dump(fitted["model"], folder / "model.json")
    (folder / "params.json").write_text(json.dumps({"mean": fitted["mean"]}), encoding="utf-8")


def restore(folder: Path) -> dict:
    p = json.loads((folder / "params.json").read_text(encoding="utf-8"))
    return {"model": core.lgb_load(folder / "model.json"), "base": {}, "mean": float(p["mean"])}
