"""Writes the train/serve parity fixture for M2 (crates/pythia-ml/tests/fixtures/picks_parity.json).

M2 sees cross-sectional ranks of 19 raw features. The engine rebuilds the raw
features from live hourly spot bars and daily perpetual bars plus funding,
ranks them across the day's coins and walks the trees. This fixture pins the
Python side down for every step:

  hours -> raw features   a few real coins over an 80-day window of hourly
                          bars (and 30 days of perp bars and funding), against
                          what build_raw() computed from the full history
  raw -> ranks            the full cross-section of two real days, every
                          eligible coin, raw values in and ranked values out
  ranks -> score          a small LambdaRank model trained here, and (with
                          --model) the exported production model's outputs

    python -m lab.export.picks_parity --out <file> [--model <picks_7d/date dir>] [--day 2026-09-20]
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import lightgbm as lgb
import numpy as np
import polars as pl

from ..data import ROOT
from ..experiments.picks import DAY_US, FEATURES, PERP_FEATURES, build_raw, hourly_segments, rank_cross_section
from ..experiments.picks_ls import perp_base

FEATS = FEATURES + PERP_FEATURES
WINDOW_D = 80
PERP_WINDOW_D = 30
FIXED = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "PEPEUSDT"]  # PEPE: its perpetual is 1000PEPEUSDT


def day_us(s: str) -> int:
    return int(datetime.fromisoformat(s).replace(tzinfo=timezone.utc).timestamp() * 1e6)


def nullable(rows) -> list:
    return [[None if (v is None or (isinstance(v, float) and np.isnan(v))) else float(v) for v in r] for r in rows]


def perp_files(kind: str, symbol: str) -> pl.DataFrame:
    d = ROOT / "hist" / "binance_um" / kind / f"symbol={symbol}"
    files = sorted(d.glob("*.parquet"))
    return pl.concat([pl.read_parquet(f) for f in files], how="vertical_relaxed") if files else pl.DataFrame()


def coin_case(sym: str, raw: pl.DataFrame, day: int, perps: list[str]) -> dict:
    seg = hourly_segments(sym)[-1]
    lo, hi = day - (WINDOW_D - 1) * DAY_US, day + DAY_US
    hours = seg.filter((pl.col("open_time_us") >= lo) & (pl.col("open_time_us") < hi))
    want = raw.filter((pl.col("symbol") == sym) & (pl.col("day") >= lo) & (pl.col("day") <= day)).sort("day")
    anchor = want.filter(pl.col("day") == day)
    if anchor.is_empty():
        raise RuntimeError(f"{sym} is not eligible on the fixture day")
    base = sym[:-4]
    perp = {}
    plo = day - (PERP_WINDOW_D - 1) * DAY_US
    for p in perps:
        if perp_base(p) != base:
            continue
        k = perp_files("klines_1d", p)
        if k.is_empty():
            continue
        k = (k.unique("open_time_us").sort("open_time_us")
             .filter((pl.col("open_time_us") >= plo) & (pl.col("open_time_us") < hi)))
        f = perp_files("funding", p)
        if not f.is_empty():
            f = (f.unique("funding_time_us").sort("funding_time_us")
                 .filter((pl.col("funding_time_us") >= plo) & (pl.col("funding_time_us") < hi)))
        if k.is_empty():
            continue
        perp[p] = {
            "klines": nullable(k.select("open_time_us", "close", "quote_volume").rows()),
            "funding": nullable(f.select("funding_time_us", "funding_rate").rows()) if not f.is_empty() else [],
        }
    return {
        "symbol": sym,
        "hour_fields": ["open_time_us", "high", "low", "close", "quote_volume"],
        "hours": nullable(hours.select("open_time_us", "high", "low", "close", "quote_volume").rows()),
        "anchor": [day, float(anchor["age"][0])],
        "perp": perp,
        "want": nullable(want.select(["day"] + FEATS).rows()),
    }


def main() -> None:
    out = Path(sys.argv[sys.argv.index("--out") + 1]) if "--out" in sys.argv else ROOT / "fixtures" / "picks_parity.json"
    model_dir = Path(sys.argv[sys.argv.index("--model") + 1]) if "--model" in sys.argv else None
    day = day_us(sys.argv[sys.argv.index("--day") + 1] if "--day" in sys.argv else "2026-09-20")
    cross_days = [day_us("2024-06-01"), day]

    raw = build_raw(with_perp=True)
    ranked = rank_cross_section(raw, FEATS)
    perps = json.loads((ROOT / "hist" / "um_universe.json").read_text())

    # Plus the most liquid coin without a perpetual that day: the missing-value path.
    on_day = raw.filter(pl.col("day") == day)
    no_perp = on_day.filter(pl.col("fund7").is_null()).sort("adv28", descending=True)["symbol"][0]
    coins = [coin_case(s, raw, day, perps) for s in FIXED + [no_perp]]

    # A small ranker on real ranked rows, missing perp values included.
    train = ranked.filter((pl.col("day") >= day_us("2023-01-01")) & (pl.col("day") < day_us("2024-01-01"))).sort("day")
    _, group = np.unique(train["day"].to_numpy(), return_counts=True)
    tiny = lgb.LGBMRanker(objective="lambdarank", n_estimators=30, num_leaves=15, min_child_samples=50,
                          learning_rate=0.1, label_gain=list(range(5)), verbose=-1).fit(
        train.select(FEATS).to_numpy().astype(np.float32), train["label"].to_numpy(), group=group)
    prod = lgb.Booster(model_file=str(model_dir / "model.txt")) if model_dir else None

    cross = []
    for d in cross_days:
        r = raw.filter(pl.col("day") == d).sort("symbol")
        k = ranked.filter(pl.col("day") == d).sort("symbol")
        assert r["symbol"].to_list() == k["symbol"].to_list()
        X = k.select(FEATS).to_numpy().astype(np.float32)
        cross.append({
            "day": d,
            "symbols": r["symbol"].to_list(),
            "raw": nullable(r.select(FEATS).rows()),
            "ranked": nullable(k.select(FEATS).rows()),
            "pred_tiny": [float(v) for v in tiny.predict(X)],
            "pred_model": [float(v) for v in prod.predict(X)] if prod else None,
        })

    fx = {
        "feature_names": FEATS,
        "day": day,
        "coins": coins,
        "cross": cross,
        "tiny_model": tiny.booster_.dump_model(),
        "model_version": model_dir.name if model_dir else None,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(fx))
    print(f"{len(coins)} coins ({', '.join(c['symbol'] for c in coins)}), "
          f"cross-sections of {[len(c['symbols']) for c in cross]} coins, written to {out}")


if __name__ == "__main__":
    main()
