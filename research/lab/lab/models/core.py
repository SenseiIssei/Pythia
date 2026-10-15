"""What every model in the zoo has, and the machinery that treats them all alike.

A model is a spec (target, features, horizon, universe, schedule, metric,
baseline, who may use it) plus a module with five functions:

  load()                      the real-data panel: one row per (ts_us, symbol)
                              with `target` (null where not yet known), the
                              features, and whatever the baseline needs
  fit(frame) -> fitted        trained on rows with a known target only
  predict(fitted, frame)      the primary forecast, one number per row
  baseline(fitted, frame)     the naive forecast it must beat, fitted on the
                              same rows (HAR, a base rate, the last value)
  loss(target, pred)          per-row loss, lower is better
  save(fitted, folder) / restore(folder)

and optionally extra(fitted, frame, ev) for secondary numbers (quantile
pinball, calibration, a regime label) that the card reports but no decision
rests on.

evaluate() runs a purged walk-forward (quarterly folds with an embargo of the
label horizon, or time blocks for small samples), scores model and baseline on
the same rows, tests the difference with Diebold-Mariano on per-period mean
losses, and applies the gate: lower mean loss than the baseline with a DM p
below GATE_P. A model that fails its gate is still kept as a candidate and
scored in shadow, but it is never promoted and nothing may use it.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import numpy as np
import polars as pl

from ..cv import walk_forward
from ..metrics import diebold_mariano

HOUR_US = 3_600_000_000
DAY_US = 24 * HOUR_US
DAY_MS = 86_400_000
GATE_P = 0.05
DRIFT_DAYS = 30
SHADOW_KEEP = 5000


class DataUnavailable(RuntimeError):
    """The model's data is not there (yet): not an error in the model."""


@dataclass
class Spec:
    code: str                 # M8
    name: str                 # folder and registry name, e.g. m8_direction
    title: str
    target: str               # what is forecast, in words
    features: list[str]
    horizon: str              # in words, e.g. "next UTC day"
    horizon_days: int         # embargo and DM lag
    universe: str
    metric: str               # logloss, qlike, mae, mse_z, rank_ic
    baseline: str             # what it must beat, in words
    every_days: int           # retrain period; 0 = not retrained here
    weekday: int | None = None
    higher_better: bool = False
    margin: float = 0.0       # promotion margin over the champion, in metric units
    relative: bool = False
    first_test: str = "2021-01-01"
    folds: str = "quarter"    # quarter or blocks
    min_rows: int = 200       # smallest champion window worth a decision
    min_days: int = 14
    min_train: int = 500      # smallest training set for a fold
    calendar: tuple[str, ...] = ()   # features set by the clock: nothing to drift
    managed_by: str = "zoo"   # zoo, learn (M1, M2 are retrained by the nightly loop) or retired
    status_note: str = ""
    used_by: list[str] = field(default_factory=list)
    use_rule: str = ""
    shadow: str = "lab"       # lab (scored here daily), engine (pythia-ml) or none
    results: str = ""         # results/<file>.md

    def public(self) -> dict:
        d = asdict(self)
        d["calendar"] = list(self.calendar)
        return d


def us(date: str) -> int:
    return int(datetime.fromisoformat(date).replace(tzinfo=timezone.utc).timestamp() * 1e6)


def iso(ts_us: int | float | None) -> str | None:
    if ts_us is None or not np.isfinite(ts_us):
        return None
    return datetime.fromtimestamp(ts_us / 1e6, timezone.utc).strftime("%Y-%m-%d")


# ---------------------------------------------------------------- losses

def logloss(y: np.ndarray, p: np.ndarray) -> np.ndarray:
    p = np.clip(np.asarray(p, float), 1e-6, 1 - 1e-6)
    y = np.asarray(y, float)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def qlike(y: np.ndarray, f: np.ndarray) -> np.ndarray:
    r = np.asarray(y, float) / np.asarray(f, float)
    return r - np.log(r) - 1


def absolute(y: np.ndarray, f: np.ndarray) -> np.ndarray:
    return np.abs(np.asarray(y, float) - np.asarray(f, float))


def squared(y: np.ndarray, f: np.ndarray) -> np.ndarray:
    return (np.asarray(y, float) - np.asarray(f, float)) ** 2


def pinball(y: np.ndarray, q: np.ndarray, alpha: float) -> np.ndarray:
    d = np.asarray(y, float) - np.asarray(q, float)
    return np.maximum(alpha * d, (alpha - 1) * d)


# ---------------------------------------------------------------- folds

@dataclass
class Fold:
    name: str
    train: np.ndarray
    test: np.ndarray


def folds_for(spec: Spec, ts: np.ndarray, known: np.ndarray) -> list[Fold]:
    """Quarterly walk-forward with the label horizon as embargo, or for small samples
    (demo fills) five expanding time blocks with the same embargo."""
    emb_h = max(spec.horizon_days, 1) * 24
    if spec.folds == "quarter":
        return [Fold(f.name, f.train, f.test) for f in walk_forward(ts, us(spec.first_test), embargo_h=emb_h)]
    order = np.sort(ts[known])
    if order.size < 2 * spec.min_train:
        return []
    cuts = np.quantile(order, np.linspace(spec.min_train / order.size, 1, 6))
    out = []
    for i in range(5):
        lo, hi = cuts[i], cuts[i + 1]
        test = (ts > lo) & (ts <= hi) if i else (ts >= lo) & (ts <= hi)
        train = ts < lo - emb_h * HOUR_US
        out.append(Fold(f"block{i + 1}", train, test))
    return out


# ---------------------------------------------------------------- evaluation

def per_period(ts: np.ndarray, loss: np.ndarray) -> np.ndarray:
    """Mean loss per timestamp, in time order (a panel day counts once in the DM test)."""
    df = pl.DataFrame({"t": ts, "l": loss}).group_by("t").agg(pl.col("l").mean()).sort("t")
    return df["l"].to_numpy()


def evaluate(mod, panel: pl.DataFrame) -> dict:
    """Walk-forward evaluation of one zoo module on its panel. Returns the numbers the
    card holds, the out-of-sample predictions (the registry's holdout) and the final
    model fitted on every row with a known target."""
    spec: Spec = mod.SPEC
    panel = panel.sort(["ts_us", "symbol"])
    ts = panel["ts_us"].to_numpy()
    known = panel["target"].is_not_null().to_numpy() & np.isfinite(panel["target"].fill_null(np.nan).to_numpy())
    pred = np.full(panel.height, np.nan)
    base = np.full(panel.height, np.nan)
    side_fn = getattr(mod, "side", None)
    side: dict[str, np.ndarray] = {}
    fold_rows = []
    for f in folds_for(spec, ts, known):
        tr = f.train & known
        te = f.test & known
        if tr.sum() < spec.min_train or te.sum() == 0:
            continue
        fitted = mod.fit(panel.filter(pl.Series(tr)))
        test = panel.filter(pl.Series(te))
        pred[te] = mod.predict(fitted, test)
        base[te] = mod.baseline(fitted, test)
        if side_fn:
            for k, v in side_fn(fitted, test).items():
                side.setdefault(k, np.full(panel.height, np.nan))[te] = v
        y = test["target"].to_numpy().astype(float)
        lm, lb = mod.loss(y, pred[te]), mod.loss(y, base[te])
        fold_rows.append({"fold": f.name, "from": iso(ts[te].min()), "rows": int(te.sum()),
                          "model": float(np.nanmean(lm)), "baseline": float(np.nanmean(lb))})
    ev_mask = known & np.isfinite(pred) & np.isfinite(base)
    out = {"folds": fold_rows, "rows_oos": int(ev_mask.sum())}
    if ev_mask.sum() == 0:
        out.update(model_score=None, baseline_score=None, gain_pct=None, dm_stat=None, dm_p=None,
                   gate={"passed": False, "why": "no out-of-sample rows: too little history for one fold"})
    else:
        y = panel["target"].to_numpy().astype(float)[ev_mask]
        lm, lb = mod.loss(y, pred[ev_mask]), mod.loss(y, base[ev_mask])
        sm, sb = float(np.nanmean(lm)), float(np.nanmean(lb))
        dm_s, dm_p = diebold_mariano(per_period(ts[ev_mask], lm), per_period(ts[ev_mask], lb),
                                     lag=max(spec.horizon_days, 1))
        gain = (sb - sm) / abs(sb) * 100 if sb else None
        passed = bool(sm < sb and np.isfinite(dm_p) and dm_p < GATE_P)
        why = (f"{spec.metric} {sm:.4f} vs {sb:.4f} for the baseline ({spec.baseline}), "
               f"{'lower' if sm < sb else 'not lower'}, DM p {dm_p:.3g}"
               + ("" if passed else f"; the gate needs lower and p < {GATE_P}"))
        wins = sum(r["model"] < r["baseline"] for r in fold_rows)
        out.update(model_score=sm, baseline_score=sb, gain_pct=gain, dm_stat=dm_s, dm_p=dm_p,
                   folds_won=wins, gate={"passed": passed, "why": why})
    hold = panel.with_columns(challenger=pl.Series(pred), baseline_pred=pl.Series(base),
                              **{f"x_{k}": pl.Series(v) for k, v in side.items()}).filter(pl.Series(ev_mask))
    out["holdout"] = hold
    gate_extra = getattr(mod, "gate_extra", None)
    if gate_extra and out["gate"]["passed"]:
        ok, why = gate_extra(out)
        out["gate"] = {"passed": bool(ok), "why": out["gate"]["why"] + "; " + why}
    fit_rows = panel.filter(pl.Series(known))
    out["fitted"] = mod.fit(fit_rows) if fit_rows.height >= spec.min_train else None
    out["train_from_us"] = int(fit_rows["ts_us"].min()) if fit_rows.height else None
    out["train_to_us"] = int(fit_rows["ts_us"].max()) if fit_rows.height else None
    out["train_rows"] = fit_rows.height
    out["feature_bins"] = {f: drift_bins(fit_rows[f].to_numpy().astype(float))
                           for f in spec.features if f not in spec.calendar and f in fit_rows.columns
                           and np.isfinite(fit_rows[f].fill_null(np.nan).to_numpy().astype(float)).sum() >= 50}
    extra = getattr(mod, "extra", None)
    out["extra"] = extra(out["fitted"], panel, out) if extra and out["fitted"] is not None else {}
    return out


def card(spec: Spec, ev: dict, version: str, now_ms: int) -> dict:
    return finite({
        "model": spec.name, "code": spec.code, "title": spec.title, "version": version, "trained_ms": now_ms,
        "target": spec.target, "horizon": spec.horizon, "universe": spec.universe, "features": spec.features,
        "metric": spec.metric, "higher_better": spec.higher_better, "baseline": spec.baseline,
        "train_from_us": ev.get("train_from_us"), "train_to_us": ev.get("train_to_us"),
        "train_rows": ev.get("train_rows"), "rows_oos": ev.get("rows_oos"),
        "model_score": ev.get("model_score"), "baseline_score": ev.get("baseline_score"),
        "gain_pct": ev.get("gain_pct"), "dm_stat": ev.get("dm_stat"), "dm_p": ev.get("dm_p"),
        "folds_won": ev.get("folds_won"), "folds": ev.get("folds"), "gate": ev.get("gate"),
        "extra": ev.get("extra") or {}, "feature_bins": ev.get("feature_bins") or {},
    })


def write_candidate(mod, ev: dict, folder: Path, now_ms: int) -> dict:
    """card.json, the model files and holdout.parquet in a fresh candidate folder."""
    folder.mkdir(parents=True, exist_ok=True)
    c = card(mod.SPEC, ev, folder.name, now_ms)
    if ev.get("fitted") is not None:
        mod.save(ev["fitted"], folder)
    (folder / "card.json").write_text(json.dumps(c, indent=2, allow_nan=False), encoding="utf-8")
    ev["holdout"].write_parquet(folder / "holdout.parquet")
    return c


def version_name(now_ms: int) -> str:
    return datetime.fromtimestamp(now_ms / 1000, timezone.utc).strftime("%Y%m%dT%H%M")


# ---------------------------------------------------------------- drift (same rules as pythia-ml drift.rs)

def drift_bins(col: np.ndarray) -> dict:
    v = col[np.isfinite(col)].astype(np.float64)
    edges = np.unique(np.quantile(v, np.linspace(0.1, 0.9, 9)))
    idx = np.searchsorted(edges, v, side="left")
    expected = np.bincount(idx, minlength=len(edges) + 1) / len(v)
    return {"edges": [float(e) for e in edges], "expected": [float(x) for x in expected],
            "lo": float(np.quantile(v, 0.005)), "hi": float(np.quantile(v, 0.995))}


def drift_check(bins: dict, values: np.ndarray, min_values: int = 48) -> dict | None:
    vals = np.asarray(values, float)
    vals = vals[np.isfinite(vals)]
    edges, expected = np.asarray(bins["edges"], float), np.asarray(bins["expected"], float)
    if len(expected) != len(edges) + 1 or vals.size < min_values:
        return None
    idx = np.searchsorted(edges, vals, side="left")
    obs = np.maximum(np.bincount(idx, minlength=len(expected)) / vals.size, 1e-4)
    exp = np.maximum(expected, 1e-4)
    psi = float(np.sum((obs - exp) * np.log(obs / exp)))
    outside = float(np.mean((vals < bins["lo"]) | (vals > bins["hi"])) * 100)
    level = "drift" if outside > 5 else "shift" if outside > 2 or psi > 0.25 else "stable"
    return {"psi": psi, "outside_pct": outside, "level": level}


def drift(card_: dict, panel: pl.DataFrame, days: int = DRIFT_DAYS) -> dict:
    """The champion's features over the last `days` days against its training bins."""
    if panel.is_empty():
        return {"level": "unknown", "features": [], "why": "no recent data"}
    t1 = int(panel["ts_us"].max())
    recent = panel.filter(pl.col("ts_us") > t1 - days * DAY_US)
    feats = []
    for f, b in (card_.get("feature_bins") or {}).items():
        if f not in recent.columns:
            continue
        c = drift_check(b, recent[f].fill_null(np.nan).to_numpy().astype(float))
        if c:
            feats.append({"feature": f, **c})
    if not feats:
        return {"level": "unknown", "features": [], "why": f"fewer than 48 recent values per input over {days} days"}
    level = "drift" if any(x["level"] == "drift" for x in feats) else \
        "shift" if any(x["level"] == "shift" for x in feats) else "stable"
    n_d = sum(x["level"] == "drift" for x in feats)
    why = (f"{n_d} of {len(feats)} inputs spent more than 5 % of the last {days} days outside the trained range"
           if n_d else f"all {len(feats)} inputs inside the trained range over the last {days} days")
    return {"level": level, "features": sorted(feats, key=lambda x: -x["outside_pct"]), "why": why,
            "window_from": iso(t1 - days * DAY_US), "window_to": iso(t1)}


# ---------------------------------------------------------------- live shadow scoring

def read_jsonl(p: Path) -> list[dict]:
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def shadow_forecasts(mod, fitted, panel: pl.DataFrame, version: str, now_ms: int, have: set) -> list[dict]:
    """Forecasts for the newest feature rows whose target is not known yet, written
    down before the outcome. Rows already recorded (ts_us, symbol) are skipped."""
    if panel.is_empty() or fitted is None:
        return []
    open_rows = panel.filter(pl.col("target").is_null())
    if open_rows.is_empty():
        return []
    open_rows = open_rows.filter(pl.col("ts_us") == open_rows["ts_us"].max())
    feats = open_rows.select(mod.SPEC.features).fill_null(np.nan).to_numpy().astype(float)
    open_rows = open_rows.filter(pl.Series(np.isfinite(feats).mean(1) >= 0.5))
    if open_rows.is_empty():
        return []
    p = mod.predict(fitted, open_rows)
    b = mod.baseline(fitted, open_rows)
    out = []
    for i, (t, s) in enumerate(zip(open_rows["ts_us"].to_list(), open_rows["symbol"].to_list())):
        if (int(t), str(s)) in have or not (np.isfinite(p[i]) and np.isfinite(b[i])):
            continue
        out.append({"ts_us": int(t), "symbol": str(s), "version": version, "pred": float(p[i]),
                    "baseline": float(b[i]), "recorded_ms": now_ms})
    return out


def shadow_score(mod, rows: list[dict], panel: pl.DataFrame) -> dict:
    """Score every recorded forecast whose target is now known, overall and per week."""
    if not rows or panel.is_empty():
        return {"rows": 0, "open": len(rows)}
    rec = pl.DataFrame(rows).select("ts_us", "symbol", "pred", "baseline", "recorded_ms").with_columns(
        pl.col("ts_us").cast(pl.Int64), pl.col("symbol").cast(pl.Utf8))
    tgt = panel.select("ts_us", "symbol", "target").drop_nulls("target").with_columns(
        pl.col("ts_us").cast(pl.Int64), pl.col("symbol").cast(pl.Utf8))
    j = rec.join(tgt, on=["ts_us", "symbol"], how="inner")
    if j.is_empty():
        return {"rows": 0, "open": len(rows)}
    y = j["target"].to_numpy().astype(float)
    lm, lb = mod.loss(y, j["pred"].to_numpy()), mod.loss(y, j["baseline"].to_numpy())
    sm, sb = float(np.mean(lm)), float(np.mean(lb))
    weeks = (pl.DataFrame({"w": j["ts_us"].to_numpy() // (7 * DAY_US) * (7 * DAY_US), "m": lm, "b": lb})
             .group_by("w").agg(model=pl.col("m").mean(), baseline=pl.col("b").mean(), rows=pl.len()).sort("w"))
    return finite({"rows": j.height, "open": len(rows) - j.height, "model": sm, "baseline": sb,
                   "gain_pct": (sb - sm) / abs(sb) * 100 if sb else None,
                   "win_rate": float(np.mean(lm < lb)), "since": iso(int(j["ts_us"].min())),
                   "weeks": [{"from": iso(int(r["w"])), "model": r["model"], "baseline": r["baseline"], "rows": r["rows"]}
                             for r in weeks.iter_rows(named=True)]})


# ---------------------------------------------------------------- small helpers

def finite(x):
    """NaN and infinities become None, recursively, so the JSON stays strict."""
    if isinstance(x, float):
        return x if math.isfinite(x) else None
    if isinstance(x, (np.floating,)):
        return finite(float(x))
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, dict):
        return {str(k): finite(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [finite(v) for v in x]
    return x


def lgb_dump(booster, path: Path) -> None:
    """LightGBM's own text file (Python reload) and its JSON dump (what pythia-ml's Gbdt evaluates)."""
    booster.save_model(str(path.with_suffix(".txt")))
    path.with_suffix(".json").write_text(json.dumps(booster.dump_model()), encoding="utf-8")


def lgb_load(path: Path):
    import lightgbm as lgb
    return lgb.Booster(model_file=str(path.with_suffix(".txt")))


Loader = Callable[[], pl.DataFrame]
