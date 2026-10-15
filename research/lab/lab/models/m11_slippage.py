"""M11: slippage of the engine's own demo market orders.

Data: the learning loop's ledger of finished demo orders on the Alpaca paper
account (<data>/learn/fills.jsonl, written by lab.ops.fills). Only filled
market orders count: they cross the spread, a limit order does not.

Target: realised slippage in bps (fill against the arrival price, positive
when it cost us). Features known when the order is sent: side, size (log
notional), the coin's half-spread and impact in the base cost table, the
cost model's own estimate, hour and weekday. Model: LightGBM on the absolute
loss (a median forecast, robust to the odd bad fill). Baseline: the engine's
cost model, i.e. the estimate it already uses (modelledSlippageBps).

Folds: five expanding time blocks with a one-day embargo; there are not
enough fills for quarters. It trains only once MIN_FILLS market fills exist;
until then it says how many it has. Gate: lower mean absolute error than the
cost model with DM p < 0.05. If it passes, it is the candidate replacement
for the learned cost table's per-symbol scaling (lab.ops.fills), reviewed by
the owner first; nothing switches automatically.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import polars as pl

from . import core
from .core import DataUnavailable, Spec

MIN_FILLS = 200
FEATURES = ["side_buy", "log_notional", "half_spread_bps", "impact_coeff", "modelled_bps", "hour", "weekday"]
PARAMS = dict(objective="l1", n_estimators=200, learning_rate=0.05, num_leaves=7, min_child_samples=20,
              subsample=0.8, subsample_freq=1, reg_lambda=5.0, n_jobs=2, verbose=-1)

SPEC = Spec(
    code="M11", name="m11_slippage", title="Slippage of demo market orders",
    target="realised slippage of a demo market order in bps (fill vs arrival price, positive = cost)",
    features=FEATURES, horizon="the order", horizon_days=1,
    universe="the engine's demo orders on the Alpaca paper account", metric="mae",
    baseline="the engine's cost model estimate for the same order (modelledSlippageBps)",
    every_days=7, weekday=0, margin=0.02, relative=True, folds="blocks", min_rows=50, min_days=7, min_train=60,
    calendar=("hour", "weekday"),
    use_rule="Candidate replacement for the learned cost table's per-symbol scaling, after the owner reviews it; "
             "nothing switches automatically.",
    results="model_zoo.md",
)


def load(ledger: dict | None = None, base: dict | None = None) -> pl.DataFrame:
    from ..ops import fills
    ledger = fills.read_ledger() if ledger is None else ledger
    if base is None:
        try:
            base = json.loads(fills.base_costs_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            base = None
    p = panel_from(list(ledger.values()), base)
    n = p.height
    if n < MIN_FILLS:
        raise DataUnavailable(f"{n} filled demo market orders in the ledger, needs {MIN_FILLS}")
    return p


def panel_from(orders: list[dict], base: dict | None) -> pl.DataFrame:
    from ..ops import fills
    rows = []
    for o in orders:
        if o.get("type") != "market" or o.get("status") not in ("filled", "partial"):
            continue
        try:
            real = float(o["realisedSlippageBps"])
            mod = float(o.get("modelledSlippageBps"))
            qty = float(o.get("filledQty") or o.get("qty") or 0)
            px = float(o.get("avgFillPrice") or 0)
            ts = int(o.get("ts") or 0)
        except (KeyError, TypeError, ValueError):
            continue
        if not (math.isfinite(real) and math.isfinite(mod) and qty > 0 and px > 0 and ts > 0):
            continue
        sym = fills.symbol_of(o.get("marketId"))
        m = (fills.resolve(base, fills.COST_VENUE, sym) if base else None) or {}
        d = datetime.fromtimestamp(ts / 1000, timezone.utc)
        rows.append({"ts_us": ts * 1000, "symbol": sym, "order_id": str(o.get("id")),
                     "side_buy": 1.0 if str(o.get("side", "")).lower() == "buy" else 0.0,
                     "log_notional": math.log(qty * px), "half_spread_bps": m.get("halfSpreadBps"),
                     "impact_coeff": m.get("impactCoeff"), "modelled_bps": mod, "hour": float(d.hour),
                     "weekday": float(d.weekday()), "target": real})
    if not rows:
        return pl.DataFrame(schema={"ts_us": pl.Int64, "symbol": pl.Utf8, "target": pl.Float64,
                                    **{f: pl.Float64 for f in FEATURES}})
    return pl.DataFrame(rows).with_columns(pl.col(FEATURES).cast(pl.Float64)).sort("ts_us")


def _X(frame: pl.DataFrame) -> np.ndarray:
    return frame.select(FEATURES).fill_null(np.nan).to_numpy().astype(np.float64)


def fit(frame: pl.DataFrame) -> dict:
    import lightgbm as lgb
    y = frame["target"].to_numpy().astype(float)
    return {"lgb": lgb.LGBMRegressor(**PARAMS).fit(_X(frame), y).booster_}


def predict(fitted: dict, frame: pl.DataFrame) -> np.ndarray:
    return fitted["lgb"].predict(_X(frame))


def baseline(fitted: dict, frame: pl.DataFrame) -> np.ndarray:
    return frame["modelled_bps"].to_numpy().astype(float)


def loss(y, f):
    return core.absolute(y, f)


def extra(fitted: dict, panel: pl.DataFrame, ev: dict) -> dict:
    h = ev["holdout"]
    if h.is_empty():
        return {}
    by = (h.with_columns(lm=(pl.col("target") - pl.col("challenger")).abs(),
                         lb=(pl.col("target") - pl.col("baseline_pred")).abs())
          .group_by("symbol").agg(fills=pl.len(), realised_median=pl.col("target").median(),
                                  model_mae=pl.col("lm").mean(), cost_model_mae=pl.col("lb").mean())
          .sort("fills", descending=True))
    return core.finite({"fills": panel.height, "by_symbol": by.to_dicts()})


def save(fitted: dict, folder: Path) -> None:
    core.lgb_dump(fitted["lgb"], folder / "model.json")


def restore(folder: Path) -> dict:
    return {"lgb": core.lgb_load(folder / "model.json")}


def synthetic_orders(n: int = 400, seed: int = 0, start_ms: int = 1_780_000_000_000) -> list[dict]:
    """Demo orders where real slippage grows with size and is worse on buys, which the
    cost model (a flat 2 bps) misses: a model that learns it must beat the cost model."""
    rng = np.random.default_rng(seed)
    out = []
    for i in range(n):
        sym = ("BTC/USD", "ETH/USD")[i % 2]
        px = 60000.0 if sym == "BTC/USD" else 3000.0
        notional = float(np.exp(rng.uniform(np.log(50), np.log(20000))))
        side = "buy" if rng.random() < 0.5 else "sell"
        real = 1.0 + 0.8 * np.log(notional / 50) + (1.5 if side == "buy" else 0.0) + rng.normal(0, 0.8)
        out.append({"id": f"o{i}", "ts": start_ms + i * 3_600_000, "marketId": f"crypto:{sym}", "side": side,
                    "type": "market", "qty": notional / px, "filledQty": notional / px, "avgFillPrice": px,
                    "status": "filled", "route": "demo", "realisedSlippageBps": float(real),
                    "modelledSlippageBps": 2.0})
    return out
