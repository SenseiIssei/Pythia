"""Exports M2 (Picks v2, with perpetual features) for the engine's shadow scoring.

    python -m lab.experiments.picks --perp-features --export [--out DIR]
    python -m lab.export.picks [--out DIR]    # metrics from the last picks_v2 report

The first runs the usual walk-forward report and then exports; the second only
exports. Both train the final model on all
labelled history (exactly as paper/picks_ls.py does before a rebalance) and
writes, under <DIR or data/models>/picks_7d/<date>/:

  model.json   LightGBM's own tree dump, what crates/pythia-ml evaluates
  model.txt    the same model in LightGBM's native format (for the parity fixture)
  card.json    everything the engine needs to trust and explain the file:
               feature order and definitions, the ranking rule, eligibility,
               training window, out-of-sample metrics, raw-feature drift bins,
               age anchors per symbol, and probe rows with LightGBM's outputs

The engine refuses a model whose probes it cannot reproduce. It never trades
on this model: M2 runs in shadow mode, ranked weekly and scored a week later.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import lightgbm as lgb
import numpy as np
import polars as pl

from ..data import ROOT
from ..experiments.picks import (DAY_US, FEATURES, HORIZON, MIN_ADV_USD, MIN_HISTORY_D, PARAMS, PERP_FEATURES,
                                 daily_bars)
from ..experiments.vol import drift_bins

NAME = "picks_7d"

FEATURE_DEFINITIONS = {
    "r1": "log return of the daily close over 1 row (a row is a UTC day with at least 20 hourly bars)",
    "r3": "log return of the daily close over 3 rows",
    "r7": "log return of the daily close over 7 rows",
    "r14": "log return of the daily close over 14 rows",
    "r28": "log return of the daily close over 28 rows",
    "r56": "log return of the daily close over 56 rows",
    "vol7": "square root of the mean daily realised variance over 7 rows; daily variance = sum of squared hourly log returns",
    "vol28": "square root of the mean daily realised variance over 28 rows",
    "vol_ratio": "vol7 / (vol28 + 1e-12)",
    "volu_trend": "ln(mean quote volume over 7 rows + 1) - ln(mean quote volume over 56 rows + 1)",
    "adv28": "ln(mean daily quote volume in USDT over 28 rows + 1)",
    "dist_hi28": "ln(close) - ln(highest high over 28 rows)",
    "dist_lo28": "ln(close) - ln(lowest low over 28 rows)",
    "skew7": "sum of cubed hourly log returns over 7 rows / (sum of squared ones ^ 1.5 + 1e-12)",
    "resid28": "r28 minus BTC's log return between the same two rows of this coin",
    "age": "rows since the start of the coin's continuous history (data from 2020-01-01; a gap over 3 days "
           "or a tenfold hourly move starts a new history)",
    "fund7": "funding paid by a long over the last 7 rows of the coin's largest USDT perpetual that day "
             "(sum of daily sums); missing without a perpetual",
    "basis": "ln(perp close / (spot close * 10^m)), m = round(log10(perp close / spot close)) undoes "
             "multipliers like 1000PEPE; missing without a perpetual",
    "perp_share": "ln((perp quote volume + 1) / (spot quote volume + 1)); missing without a perpetual",
}

RANKING = ("Every feature is a cross-sectional rank within the UTC day: (rank - 1) / (n - 1) over all eligible "
           "coins, average rank for ties, n counts every eligible coin (also those whose perp features are "
           "missing); a missing value stays missing. Days with fewer than 20 eligible coins are not scored.")

# Where the engine's numbers can differ from the lab's, said once, here, and shown in the UI.
ENGINE_NOTES = [
    "age: the engine sees about 80 days of hourly bars, not the history since 2020. It continues the lab's "
    "count from the per-symbol anchors in this card; a coin listed after the export is counted from its first "
    "day with 20 hourly bars. Exact unless a coin had an outage day or a symbol reuse after the anchor.",
    "fund7: the lab sums funding in an order that is not fixed, so coins with the same 7-day funding get "
    "ranks that differ by float rounding only. The engine gives such ties their shared average rank.",
    "universe: the lab ranks every USDT pair in the Binance archive that was trading that day; the engine "
    "ranks the pairs Binance lists as trading now, minus stablecoins and leveraged tokens, the same filter "
    "the lab's universe uses.",
    "realised returns: a coin delisted during the week is scored at its last close, as in the lab; a coin "
    "whose bars cannot be fetched at all is left out of that week's Rank-IC.",
]


def clean(v):
    """NaN and infinities become null: the card is strict JSON (a quarter without
    test days reports a NaN Rank-IC, which serde refuses)."""
    if isinstance(v, dict):
        return {k: clean(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [clean(x) for x in v]
    if isinstance(v, (float, np.floating)):
        return float(v) if np.isfinite(v) else None
    if isinstance(v, np.integer):
        return int(v)
    return v


def age_anchors() -> dict[str, list[int]]:
    """Per symbol: [last day (us), age on that day] of its latest continuous history."""
    syms = json.loads((ROOT / "hist" / "universe.json").read_text())
    out = {}
    for s in syms:
        d = daily_bars(s)
        if d.is_empty():
            continue
        out[s] = [int(d["day"][-1]), int(d.height - 1)]
    return out


def train_final(P: pl.DataFrame, feats: list[str]) -> tuple[lgb.LGBMRanker, np.ndarray, np.ndarray]:
    """All labelled history, the same selection paper/picks_ls.py makes before a rebalance."""
    days = P["day"].to_numpy()
    fwd = P["fwd"].to_numpy()
    last_day = int(days.max())
    train = np.isfinite(fwd) & (days < last_day - HORIZON * DAY_US)
    order = np.argsort(days[train], kind="stable")
    X = P.select(feats).to_numpy().astype(np.float32)
    y = P["label"].to_numpy()
    Xt, yt, dt = X[train][order], y[train][order].astype(np.int32), days[train][order]
    _, group = np.unique(dt, return_counts=True)
    model = lgb.LGBMRanker(**PARAMS).fit(Xt, yt, group=group)
    return model, Xt, dt


def export_model(raw: pl.DataFrame, P: pl.DataFrame, feats: list[str], metrics: dict, out: str | None = None) -> Path:
    if feats != FEATURES + PERP_FEATURES:
        raise ValueError("the engine runs M2 v2 only: export with --perp-features")
    model, Xt, dt = train_final(P, feats)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    d = (Path(out) if out else ROOT / "models") / NAME / stamp
    d.mkdir(parents=True, exist_ok=True)
    (d / "model.json").write_text(json.dumps(model.booster_.dump_model()))
    model.booster_.save_model(str(d / "model.txt"))

    rng = np.random.default_rng(11)
    pick = rng.choice(len(Xt), size=64, replace=False)
    probe_x = Xt[pick].astype(np.float64)
    probe_x[:4, -3:] = np.nan  # a coin without a perpetual
    probe_x[4:6, :5] = np.nan  # and the missing-value path on the spot side
    probe_raw = model.predict(probe_x.astype(np.float32))

    recent = raw.filter(pl.col("day") >= raw["day"].max() - 365 * DAY_US)
    per_day = recent.group_by("day").agg(n=pl.len(), perp=pl.col("fund7").is_not_null().sum())
    importance = sorted(zip(feats, model.booster_.feature_importance("gain")), key=lambda x: -x[1])
    total_gain = sum(g for _, g in importance) or 1.0
    card = {
        "name": NAME,
        "model": "M2 v2 (Picks with perpetual features), LightGBM LambdaRank",
        "created": stamp,
        "target": "the coin's 7-day forward log return, ranked into quintiles within the day (LambdaRank label)",
        "output": "raw ranking score; only the order of scores within one day means anything",
        "horizon_days": HORIZON,
        "features": feats,
        "feature_definitions": {f: FEATURE_DEFINITIONS[f] for f in feats},
        "ranking": RANKING,
        "eligibility": {"min_history_days": MIN_HISTORY_D, "min_adv_usd": MIN_ADV_USD,
                        "min_history_rows": MIN_HISTORY_D + 10, "min_coins": 20,
                        "universe": "Binance spot USDT pairs, no stablecoins or fiat, no leveraged tokens"},
        "engine_notes": ENGINE_NOTES,
        "train_from_us": int(dt.min()), "train_to_us": int(dt.max()),
        "train_rows": int(len(Xt)), "train_days": int(len(np.unique(dt))),
        "n_trees": int(model.booster_.num_trees()),
        "lightgbm_params": PARAMS,
        "out_of_sample": {k: metrics[k] for k in ("rank_ic", "rank_ic_t", "rank_ic_liquid50", "folds", "deciles")},
        "verdict": metrics.get("verdict", ""),
        "importance_pct": {f: float(100 * g / total_gain) for f, g in importance},
        # Drift reference on the raw values: the ranks the model sees are uniform by construction.
        "raw_feature_bins": {f: drift_bins(raw[f].to_numpy().astype(np.float64)) for f in feats if f != "age"},
        "typical_day": {"eligible_coins": float(per_day["n"].mean()),
                        "with_perp_pct": float(100 * per_day["perp"].sum() / per_day["n"].sum())},
        "age_anchors": age_anchors(),
        "probe": {"x": [[None if np.isnan(v) else float(v) for v in row] for row in probe_x],
                  "raw": [float(v) for v in probe_raw]},
    }
    (d / "card.json").write_text(json.dumps(clean(card), indent=1, allow_nan=False))
    print(f"exported {card['n_trees']} trees, {card['train_rows']:,} rows, "
          f"{len(card['age_anchors'])} age anchors to {d}", flush=True)
    return d


def main() -> None:
    """Export without rerunning the walk-forward: the metrics come from the last
    `picks --perp-features` report on the same data. Writes nothing but the model folder."""
    import sys

    from ..experiments.picks import build_raw, rank_cross_section

    out = sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else None
    metrics = json.loads((ROOT / "reports" / "picks_v2" / "latest.json").read_text())
    feats = FEATURES + PERP_FEATURES
    raw = build_raw(with_perp=True)
    export_model(raw, rank_cross_section(raw, feats), feats, metrics, out)


if __name__ == "__main__":
    main()
