"""Fair value and 30 / 90 day return forecasts for Pokemon cards.

Fair value (works from the first snapshot)
  A LightGBM regression of log price on what a card is: rarity group,
  character, alt art, secret number, set age, series, card type and the
  Cardmarket trend features. Fitted in five folds grouped by set, so every
  card's fair value comes from a model that never saw its set. The gap
  (fair / price - 1) says how cheap a card is next to similar cards. It is a
  description, not a forecast: nothing has shown yet that cheap-for-its-kind
  cards go up.

Forecast (needs our own history)
  The same features plus the card's own past returns from the snapshots and
  the fair-value gap, against the log return over the next 30 and 90 days.
  Walk-forward by month: train only on rows whose label ended before the
  test month began (purged by the horizon), with at least 45 days of
  labelled rows, test on the month. Judged by the
  rank correlation of forecast and outcome per test day (rank IC) and the
  mean absolute error against forecasting zero. A horizon counts as
  validated with at least 4 test months, mean rank IC above 0.03 with t
  above 2 over the months, and a lower error than zero. Before that every
  forecast shown is the prior below and says so.

Prior (until a horizon validates)
  A fixed rule, not fitted: 30 d = 0.04 x g + 0.30 x the fresh Cardmarket
  30-day trend; 90 d = 0.10 x g + 0.30 x trend, where g is log(fair / price)
  squashed towards a factor of 3 either way, and 0 beyond a factor of 5
  (model error; see `prior_gap`). Clipped to plus or minus 30 %. With
  Cardmarket stale (most cards since mid 2026) the trend term is zero. The
  paper collection following it is the rule's forward test.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import polars as pl

from . import data as pdata

HORIZONS = (30, 90)
MIN_TEST_MONTHS = 4
MIN_TRAIN_DAYS = 45
IC_MIN, T_MIN = 0.03, 2.0
CLIP = 0.3
# The first real snapshot showed fair-value gaps of 5x to 25x on old promos and
# vintage cards: model error, not bargains. The prior uses the gap clipped to
# a factor of 3 either way and only a small share of it.
GAP_CLIP = math.log(3.0)
GAP_IGNORE = math.log(5.0)
PRIOR = {30: (0.04, 0.30), 90: (0.10, 0.30)}
STATIC = ["rarity_group", "character", "series", "supertype", "subtypes", "printing"]
NUMERIC = ["alt_art", "secret", "set_age_days", "cm_mom_1_7", "cm_mom_7_30", "cm_trend_30", "dex", "number_pos",
           "set_printed_total", "hp"]
DYNAMIC = ["ret_7d", "ret_30d", "fv_gap", "tp_low_gap"]


def _lgbm(n: int = 300):
    """For prices: the cross-section is well explained, so a flexible model."""
    import lightgbm as lgb
    return lgb.LGBMRegressor(n_estimators=n, learning_rate=0.05, num_leaves=31, min_child_samples=20,
                             subsample=0.8, subsample_freq=1, colsample_bytree=0.8, reg_lambda=1.0, verbose=-1,
                             random_state=7)


def _lgbm_returns():
    """For returns: mostly noise, so a small, heavily regularised model with a
    robust loss (a few cards double or halve in a month)."""
    import lightgbm as lgb
    return lgb.LGBMRegressor(objective="huber", alpha=0.15, n_estimators=150, learning_rate=0.03, num_leaves=15,
                             min_child_samples=200, subsample=0.7, subsample_freq=1, colsample_bytree=0.8,
                             reg_lambda=10.0, verbose=-1, random_state=7)


def matrix(df: pl.DataFrame, cols: list[str], cats: dict[str, list[str]] | None = None
           ) -> tuple[np.ndarray, list[str], dict[str, list[str]]]:
    """Numeric matrix with categoricals as integer codes (LightGBM splits on them as numbers;
    the categories are few). `cats` fixes the codes between train and test."""
    cats = dict(cats or {})
    out, names = [], []
    for c in cols:
        if c not in df.columns:
            out.append(np.full(df.height, np.nan))
        elif c in STATIC:
            vals = df[c].cast(pl.Utf8).fill_null("").to_list()
            if c not in cats:
                cats[c] = sorted(set(vals))
            idx = {v: i for i, v in enumerate(cats[c])}
            out.append(np.array([idx.get(v, -1) for v in vals], dtype=float))
        else:
            out.append(df[c].cast(pl.Float64).fill_nan(None).to_numpy().astype(float))
        names.append(c)
    return np.column_stack(out) if out else np.empty((df.height, 0)), names, cats


# ---------------------------------------------------------------- fair value

def with_set_level(snap: pl.DataFrame) -> pl.DataFrame:
    """Leave-one-out mean log price of the OTHER cards of the same set
    (`loo_set`) and of the same set and rarity group (`loo_set_rarity`): how
    much collectors pay for this set, without the card's own price. Folds
    grouped by set still keep the model from learning any one set; these
    columns tell it how dear the set is. Without them the first real snapshot
    gave an out-of-fold R2 of 0.63 and fair values of 5x to 25x the price on
    old promos."""
    s = snap.with_columns(_lp=pl.col("log_price").cast(pl.Float64))
    out = s
    for name, keys in (("loo_set", ["set_id"]), ("loo_set_rarity", ["set_id", "rarity_group"])):
        tot, n = pl.col("_lp").sum().over(keys), pl.col("_lp").count().over(keys)
        out = out.with_columns(pl.when(n > 1).then((tot - pl.col("_lp")) / (n - 1)).alias(name))
    return out.drop("_lp")


FAIR_EXTRA = ["loo_set", "loo_set_rarity"]


def fair_value(snap: pl.DataFrame, folds: int = 5) -> tuple[np.ndarray, dict]:
    """Out-of-fold fair log price for each card of one snapshot, and the fit's R2."""
    cols = STATIC + NUMERIC + FAIR_EXTRA
    X, _, _ = matrix(with_set_level(snap), cols)
    y = snap["log_price"].to_numpy()
    sets = snap["set_id"].fill_null("?").to_list()
    uniq = sorted(set(sets))
    if len(uniq) < folds or snap.height < 50:
        return np.full(snap.height, np.nan), {"r2": None, "cards": snap.height, "note": "too few cards or sets"}
    rng = np.random.default_rng(11)
    fold_of = {s: i % folds for i, s in enumerate(rng.permutation(uniq))}
    f = np.array([fold_of[s] for s in sets])
    pred = np.full(snap.height, np.nan)
    for k in range(folds):
        tr, te = f != k, f == k
        m = _lgbm()
        m.fit(X[tr], y[tr])
        pred[te] = m.predict(X[te])
    ok = np.isfinite(pred)
    r2 = 1 - ((y[ok] - pred[ok]) ** 2).sum() / (((y[ok] - y[ok].mean()) ** 2).sum() or 1)
    return pred, {"r2": float(r2), "cards": int(ok.sum()), "folds": folds, "grouped_by": "set"}


def add_fair_value(df: pl.DataFrame, cache: Path | None = None) -> tuple[pl.DataFrame, dict]:
    """fv_log and fv_gap (log fair - log price) for every snapshot day, each day
    fitted on its own snapshot only. Past days come from `cache` when given
    (one parquet per day); the latest day is always refitted."""
    parts, info = [], {}
    days = df["date"].unique().sort().to_list()
    for d in days:
        snap = df.filter(pl.col("date") == d)
        f = cache / f"{d}.parquet" if cache else None
        if f is not None and d != days[-1] and f.exists():
            fv = pl.read_parquet(f)
            snap = snap.join(fv, on="card_id", how="left")
        else:
            pred, info = fair_value(snap)
            snap = snap.with_columns(fv_log=pl.Series(pred, dtype=pl.Float64))
            if f is not None:
                f.parent.mkdir(parents=True, exist_ok=True)
                snap.select("card_id", "fv_log").write_parquet(f)
        parts.append(snap.with_columns(fv_gap=pl.col("fv_log") - pl.col("log_price")))
    return pl.concat(parts, how="diagonal_relaxed"), info


# ---------------------------------------------------------------- forecast

def rank_ic(pred: np.ndarray, y: np.ndarray) -> float | None:
    from scipy.stats import spearmanr
    ok = np.isfinite(pred) & np.isfinite(y)
    if ok.sum() < 20 or np.std(pred[ok]) == 0:
        return None
    return float(spearmanr(pred[ok], y[ok]).statistic)


def walk_forward(df: pl.DataFrame, horizon: int) -> dict:
    """Monthly walk-forward of the forecast for one horizon. `df` has features, returns and fv_gap."""
    cols = STATIC + NUMERIC + DYNAMIC
    y_all = pdata.forward_returns(df, horizon)
    d = df.with_columns(_y=y_all, _d=pl.col("date").str.to_date(), _m=pl.col("date").str.slice(0, 7))
    months = d["_m"].unique().sort().to_list()
    results, preds = [], []
    for m in months:
        test = d.filter((pl.col("_m") == m) & pl.col("_y").is_not_null())
        if test.is_empty():
            continue
        start = test["_d"].min()
        # Purge: a training label must have ended before the test month starts.
        train = d.filter(pl.col("_y").is_not_null() & (pl.col("_d") + pl.duration(days=horizon) < start))
        if train.height < 500 or train["date"].n_unique() < MIN_TRAIN_DAYS:
            continue
        Xtr, _, cats = matrix(train, cols)
        Xte, _, _ = matrix(test, cols, cats)
        model = _lgbm_returns()
        model.fit(Xtr, train["_y"].to_numpy())
        p = model.predict(Xte)
        y = test["_y"].to_numpy()
        ics = []
        for day in test["date"].unique().to_list():
            mask = (test["date"] == day).to_numpy()
            ic = rank_ic(p[mask], y[mask])
            if ic is not None:
                ics.append(ic)
        results.append({"month": m, "rows": test.height, "rank_ic": float(np.mean(ics)) if ics else None,
                        "mae": float(np.mean(np.abs(p - y))), "mae_zero": float(np.mean(np.abs(y))),
                        "mean_return_pct": float(np.mean(y)) * 100})
        preds.append(test.select("card_id", "date").with_columns(pred=pl.Series(p), y=pl.Series(y)))
    ics = np.array([r["rank_ic"] for r in results if r["rank_ic"] is not None])
    mean_ic = float(ics.mean()) if len(ics) else None
    t = float(ics.mean() / (ics.std(ddof=1) / math.sqrt(len(ics)))) if len(ics) >= 3 and ics.std(ddof=1) > 0 else None
    mae = float(np.mean([r["mae"] for r in results])) if results else None
    mae0 = float(np.mean([r["mae_zero"] for r in results])) if results else None
    validated = bool(len(ics) >= MIN_TEST_MONTHS and mean_ic is not None and mean_ic > IC_MIN
                     and t is not None and t > T_MIN and mae is not None and mae < mae0)
    labelled = int(y_all.is_not_null().sum())
    return {"horizon": horizon, "labelled_rows": labelled, "test_months": len(results), "months": results,
            "mean_rank_ic": mean_ic, "ic_t": t, "mae": mae, "mae_zero": mae0, "validated": validated}


def fit_full(df: pl.DataFrame, horizon: int):
    cols = STATIC + NUMERIC + DYNAMIC
    y = pdata.forward_returns(df, horizon)
    tr = df.with_columns(_y=y).filter(pl.col("_y").is_not_null())
    X, _, cats = matrix(tr, cols)
    model = _lgbm_returns()
    model.fit(X, tr["_y"].to_numpy())
    return model, cats, cols


def prior_gap(gap: np.ndarray) -> np.ndarray:
    """The fair-value gap as the prior uses it: a gap beyond a factor of 5 is
    taken as model error and ignored, the rest squashed smoothly towards a
    factor of 3 (smoothly, so the ranking has no ties at the cap)."""
    g = np.asarray(gap, dtype=float)
    g = np.where(np.isfinite(g) & (np.abs(g) <= GAP_IGNORE), g, 0.0)
    return GAP_CLIP * np.tanh(g / GAP_CLIP)


def prior(snap: pl.DataFrame, horizon: int) -> np.ndarray:
    a, b = PRIOR[horizon]
    gap = prior_gap(snap["fv_gap"].cast(pl.Float64).fill_nan(None).fill_null(0.0).to_numpy())
    tr = snap["cm_trend_30"].cast(pl.Float64).fill_nan(None).fill_null(0.0).to_numpy()
    return np.clip(np.expm1(a * gap + b * np.log1p(np.clip(tr, -0.9, 3.0))), -CLIP, CLIP)


def status_sentence(evals: dict[int, dict], days: int) -> str:
    done = [h for h, e in evals.items() if e.get("validated")]
    if done:
        return (f"Validated out of sample for {', '.join(f'{h} d' for h in done)}; other horizons use the prior "
                "rule.") if len(done) < len(evals) else "Validated out of sample for 30 and 90 days."
    tested = {h: e for h, e in evals.items() if (e.get("test_months") or 0) >= MIN_TEST_MONTHS}
    tail = " Forecasts shown are the prior rule (fair-value gap and Cardmarket trend), not a fitted model."
    if tested:
        parts = [f"{h} d over {e['test_months']} months: rank IC {e.get('mean_rank_ic') or 0:.3f}, "
                 f"t {e.get('ic_t') or 0:.1f}, error {e.get('mae') or 0:.3f} vs {e.get('mae_zero') or 0:.3f} for zero"
                 for h, e in tested.items()]
        return "Tested out of sample and not validated (" + "; ".join(parts) + ")." + tail
    # Training labels for MIN_TRAIN_DAYS, the purge, then four test months whose labels must end.
    need = min(MIN_TRAIN_DAYS + 2 * h + 30 * MIN_TEST_MONTHS for h in evals) if evals else 0
    unit = "day" if days == 1 else "days"
    return (f"Not validated: {days} {unit} of our own price history, a first honest test needs about {need}." + tail)


def predict(df: pl.DataFrame, evaluate: bool = True) -> tuple[pl.DataFrame, dict]:
    """Today's forecasts for every card of the latest snapshot: pred_30d, pred_90d
    (simple returns) and pred_src ('model' or 'prior'), plus the evaluation."""
    snap = df.filter(pl.col("date") == df["date"].max())
    days = pdata.history_days(df)
    evals = {h: (walk_forward(df, h) if evaluate else {"validated": False, "test_months": 0}) for h in HORIZONS}
    out = snap
    for h in HORIZONS:
        if evals[h].get("validated"):
            model, cats, cols = fit_full(df, h)
            X, _, _ = matrix(snap, cols, cats)
            p = np.clip(np.expm1(model.predict(X)), -CLIP, CLIP)
        else:
            p = prior(snap, h)
        out = out.with_columns(pl.Series(f"pred_{h}d", p))
    out = out.with_columns(pred_src=pl.lit("model" if all(evals[h].get("validated") for h in HORIZONS)
                                           else ("mixed" if any(evals[h].get("validated") for h in HORIZONS)
                                                 else "prior")))
    return out, {"history_days": days, "horizons": {str(h): e for h, e in evals.items()},
                 "validated": any(e.get("validated") for e in evals.values()),
                 "sentence": status_sentence(evals, days)}
