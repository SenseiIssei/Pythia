"""Writes the train/serve parity fixture for crates/pythia-ml.

The Rust engine rebuilds every feature the volatility model sees. If one of
them is computed even slightly differently live than in training, the model
quietly answers a question it was never trained on. This fixture pins the
Python side down so a Rust test can check, to 1e-9:

  minutes -> hours   the 1m to 1h aggregation (realised variance included)
  hours -> features  all 21 features, nulls included, for ETH against BTC
  features -> output a small LightGBM model with missing values in training,
                     evaluated by the Rust tree walker

    python -m lab.export.parity     # writes <data>/fixtures/vol_parity.json
"""

from __future__ import annotations

import json

import lightgbm as lgb
import numpy as np
import polars as pl

from ..data import HOUR_US, ROOT, klines_1m
from ..experiments.vol import FEATURES, features

N_HOURS = 400
HOUR_COLS = ["ts_us", "open", "high", "low", "close", "ret", "rv", "volume_q", "taker_buy_q", "trades"]


def hourly_from(k: pl.DataFrame, symbol: str) -> pl.DataFrame:
    """Exactly data.hourly(), on a given minute frame."""
    return (
        k.with_columns(
            r=(pl.col("close").log() - pl.col("close").shift(1).log()).fill_null(0.0),
            ts_us=(pl.col("open_time_us") // HOUR_US) * HOUR_US,
        )
        .group_by("ts_us", maintain_order=True)
        .agg(open=pl.col("open").first(), high=pl.col("high").max(), low=pl.col("low").min(),
             close=pl.col("close").last(), ret=pl.col("r").sum(), rv=(pl.col("r") ** 2).sum(),
             volume_q=pl.col("quote_volume").sum(), taker_buy_q=pl.col("taker_buy_quote_volume").sum(),
             trades=pl.col("trades").sum(), minutes=pl.len())
        .filter(pl.col("minutes") >= 50)
        .with_columns(symbol=pl.lit(symbol))
        .sort("ts_us")
    )


def nullable(rows: list[list]) -> list[list]:
    return [[None if (v is None or (isinstance(v, float) and np.isnan(v))) else float(v) for v in r] for r in rows]


def main() -> None:
    k_btc, k_eth = klines_1m("BTCUSDT"), klines_1m("ETHUSDT")
    # Last N_HOURS hours of minutes, plus the minute before so the first return has its previous close
    cut = (int(k_eth["open_time_us"].max()) // HOUR_US - N_HOURS + 1) * HOUR_US
    k_eth = k_eth.filter(pl.col("open_time_us") >= cut - 60_000_000)
    k_btc = k_btc.filter(pl.col("open_time_us") >= cut - 60_000_000)

    h_eth = hourly_from(k_eth, "ETHUSDT").filter(pl.col("ts_us") >= cut)
    h_btc = hourly_from(k_btc, "BTCUSDT").filter(pl.col("ts_us") >= cut)

    f_eth = features(h_eth)
    f_btc = features(h_btc).select("ts_us", btc_har1="har1", btc_har24="har24", btc_ret="ret")
    f = (f_eth.join(f_btc, on="ts_us", how="left")
         .with_columns(rel_har1=pl.col("har1") - pl.col("btc_har1")))
    X = f.select(FEATURES).to_numpy().astype(np.float64)
    y = f["y"].to_numpy()

    ok = np.isfinite(y)
    tiny = lgb.LGBMRegressor(n_estimators=40, num_leaves=15, min_child_samples=10, learning_rate=0.1,
                             verbose=-1).fit(X[ok].astype(np.float32), y[ok])
    pred = tiny.predict(X.astype(np.float32))

    minutes = k_eth.head(181)  # three hours plus the leading minute
    mh = hourly_from(minutes, "ETHUSDT")

    out = {
        "feature_names": FEATURES,
        "hour_fields": HOUR_COLS,
        "eth_hours": nullable(h_eth.select(HOUR_COLS).rows()),
        "btc_hours": nullable(h_btc.select(HOUR_COLS).rows()),
        "eth_features": nullable(X.tolist()),
        "model": tiny.booster_.dump_model(),
        "pred": [float(v) for v in pred],
        "minute_fields": ["open_time_us", "open", "high", "low", "close", "quote_volume",
                          "taker_buy_quote_volume", "trades"],
        "minutes": nullable(minutes.select("open_time_us", "open", "high", "low", "close", "quote_volume",
                                           "taker_buy_quote_volume", "trades").rows()),
        "minute_hours": nullable(mh.select(HOUR_COLS + ["minutes"]).rows()),
    }
    d = ROOT / "fixtures"
    d.mkdir(parents=True, exist_ok=True)
    (d / "vol_parity.json").write_text(json.dumps(out))
    print(f"{len(out['eth_hours'])} ETH hours, {len(out['btc_hours'])} BTC hours, "
          f"{sum(ok)} labelled rows, {len(out['minute_hours'])} minute-built hours")


if __name__ == "__main__":
    main()
