"""Y9 (results/pumpfun_select_y9_prereg.md): the models that decide at the migration whether to buy. PAPER ONLY.

Per label (win0, rug0: a buy at the migration; win5, rug5: 5 s after it; selfeat.LabelPipe's rows) a LightGBM
classifier with fixed parameters on the oldest 80 % of its training rows (time order), its probabilities not
recalibrated; the top-30 % threshold is the 70th percentile of its predictions on the newest 20 %, the base rate
the label's rate over all training rows. A row trains a model for a time T only if its decision was LABEL_H_MS
before T (its labels known by then). Fewer than MIN_TRAIN rows, or one class only: no model (the filter skips
"no model"). The logistic regression on the same features (model.logistic) is the baseline, judged next to it
walk-forward by UTC day (walk_forward), never traded.

The daily retrain (retrain.run_y9) trains on every row of the study's record and saves sel_<label>.json and
sel_policy.json next to the other models (model.load reads them), where the paper books pick them up.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

from . import model as M
from .selfeat import SEL0, SEL5, day_of
from .trendfeat import TREND_FEATURES

LABELS = {"win0": (0, "win"), "rug0": (0, "rug"), "win5": (5, "win"), "rug5": (5, "rug"),
          # Y10 (results/pumpfun_trends_y10_prereg.md): the same labels, the same parameters, the trend features added
          "win0t": (0, "win"), "rug0t": (0, "rug"), "win5t": (5, "win"), "rug5t": (5, "rug")}
Y9_LABELS = ("win0", "rug0", "win5", "rug5")
TREND_LABELS = ("win0t", "rug0t", "win5t", "rug5t")
PARAMS = dict(n_estimators=200, learning_rate=0.03, num_leaves=7, min_child_samples=20, subsample=0.8,
              subsample_freq=1, colsample_bytree=0.8, reg_lambda=1.0, verbose=-1, n_jobs=2)
MIN_TRAIN = 200
LABEL_H_MS = 15 * 60_000
TOP = 0.3
DAY_MS = 86_400_000


def features_for(label: str) -> list[str]:
    return (SEL0 if LABELS[label][0] == 0 else SEL5) + (TREND_FEATURES if label in TREND_LABELS else [])


def has_trend(table: dict) -> bool:
    """Rows written before Y10 have no trend columns: no trend model is trained on them."""
    return any(k in table and bool(np.isfinite(table[k]).any()) for k in TREND_FEATURES)


def rows_for(table: dict[str, np.ndarray], label: str, until_ms: float | None = None) -> dict[str, np.ndarray]:
    """The rows of the label's entry with the label known, in time order; with until_ms only those decided
    LABEL_H_MS before it."""
    entry, col = LABELS[label]
    m = (table["entry"] == entry) & np.isfinite(table[col])
    if until_ms is not None:
        m &= table["t"] + LABEL_H_MS < until_ms
    order = np.argsort(table["t"][m], kind="stable")
    return {k: v[m][order] for k, v in table.items()}


def fit(X: np.ndarray, y: np.ndarray, feats: list[str]) -> tuple[M.Fitted, float | None]:
    """(model, top threshold); a model without a booster (and no threshold) when it cannot be fitted."""
    import lightgbm as lgb
    base = float(y.mean()) if len(y) else 0.0
    cut = int(len(y) * 0.8)
    if len(y) < MIN_TRAIN or y[:cut].min() == y[:cut].max():
        return M.Fitted(None, None, None, base, feats), None
    clf = lgb.LGBMClassifier(**PARAMS)
    clf.fit(X[:cut], y[:cut])
    m = M.Fitted(clf.booster_, None, None, base, feats)
    return m, float(np.quantile(m.predict(X[cut:]), 1 - TOP))


def train(table: dict[str, np.ndarray], until_ms: float | None = None) -> dict:
    """{"sel_<label>": Fitted, ..., "sel_policy": {label: {"0.3": threshold}}, "sel_rows": {label: rows}}."""
    out, pol, n = {}, {}, {}
    for label in LABELS:
        if label in TREND_LABELS and not has_trend(table):
            out["sel_" + label], n[label] = M.Fitted(None, None, None, 0.0, features_for(label)), 0
            continue
        rs = rows_for(table, label, until_ms)
        feats = features_for(label)
        m, thr = fit(M.matrix(rs, feats), rs[LABELS[label][1]], feats)
        out["sel_" + label] = m
        n[label] = int(len(rs["t"]))
        if thr is not None:
            pol[label] = {str(TOP): thr}
    out["sel_policy"] = pol
    out["sel_rows"] = n
    return out


def predict(m: M.Fitted, f: dict) -> float:
    return float(m.predict(np.array([[float(f.get(k, math.nan)) for k in m.features]], dtype=float))[0])


def walk_forward(table: dict[str, np.ndarray]) -> dict:
    """Per label, every UTC day of the rows tested by a model trained on the rows before it (decided LABEL_H_MS
    before the day's start), the logistic regression on the same rows and the training base rate next to it; the
    pooled scores over every tested day and per day."""
    out = {}
    days = sorted({day_of(t) for t in table["t"]}) if len(table["t"]) else []
    for label, (entry, col) in LABELS.items():
        if label in TREND_LABELS and not has_trend(table):
            continue
        feats = features_for(label)
        pooled = {"model": [], "logistic": [], "base": [], "y": [], "ret": [], "top": []}
        per_day = []
        for d in days:
            start = day_start(d)
            tr = rows_for(table, label, start)
            allr = rows_for(table, label)
            te_m = (allr["t"] >= start) & (allr["t"] < start + DAY_MS)
            if not te_m.any():
                continue
            m, thr = fit(M.matrix(tr, feats), tr[col], feats)
            if m.booster is None:
                per_day.append({"day": d, "train": int(len(tr["t"])), "test": int(te_m.sum()), "model": False})
                continue
            Xte = M.matrix({k: v[te_m] for k, v in allr.items()}, feats)
            y = allr[col][te_m]
            pm = m.predict(Xte)
            pl_ = M.logistic(M.matrix(tr, feats), tr[col], Xte)
            pooled["model"].append(pm)
            pooled["logistic"].append(pl_)
            pooled["base"].append(np.full(len(y), m.base))
            pooled["y"].append(y)
            pooled["ret"].append(allr["ret"][te_m])
            pooled["top"].append(pm >= thr)
            per_day.append({"day": d, "train": int(len(tr["t"])), "test": int(len(y)), "model": True,
                            "auc": M.auc(pm, y), "logistic_auc": M.auc(pl_, y), "rate": float(y.mean()),
                            "base": m.base, "threshold": thr})
        res = {"label": label, "days": per_day}
        if pooled["y"]:
            y = np.concatenate(pooled["y"])
            pm, pl_, pb = (np.concatenate(pooled[k]) for k in ("model", "logistic", "base"))
            ret, top = np.concatenate(pooled["ret"]), np.concatenate(pooled["top"])
            below = pm < pb
            res.update(n=int(len(y)), rate=float(y.mean()), model=M.scores(pm, y, float(pb.mean())),
                       logistic=M.scores(pl_, y, float(pb.mean())), base=M.scores(pb, y, float(pb.mean())),
                       ret_all=float(ret.mean()), ret_top=float(ret[top].mean()) if top.any() else None,
                       n_top=int(top.sum()), ret_below_base=float(ret[below].mean()) if below.any() else None,
                       n_below_base=int(below.sum()))
        out[label] = res
    return out


def day_start(d: str) -> int:
    from datetime import datetime, timezone
    return int(datetime.strptime(d, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000)


# ---------------------------------------------------------------- files

def save(models: dict, d: Path | None = None) -> Path:
    d = d or M.model_dir()
    d.mkdir(parents=True, exist_ok=True)
    for label in LABELS:
        m = models.get("sel_" + label)
        if m is None:
            continue
        tmp = d / f"sel_{label}.json.tmp"
        tmp.write_text(json.dumps(m.to_json()), encoding="utf-8")
        tmp.replace(d / f"sel_{label}.json")
    tmp = d / "sel_policy.json.tmp"
    tmp.write_text(json.dumps({"policy": models.get("sel_policy") or {}, "rows": models.get("sel_rows") or {}}),
                   encoding="utf-8")
    tmp.replace(d / "sel_policy.json")
    return d


def load_models(d: Path) -> dict:
    out = {}
    for label in LABELS:
        p = d / f"sel_{label}.json"
        if p.exists():
            try:
                out["sel_" + label] = M.Fitted.from_json(json.loads(p.read_text(encoding="utf-8")))
            except (OSError, ValueError, KeyError):
                pass
    try:
        out["sel_policy"] = dict(json.loads((d / "sel_policy.json").read_text(encoding="utf-8")).get("policy") or {})
    except (OSError, ValueError, AttributeError):
        pass
    return out


def rows_path(suffix: str = "") -> Path:
    """The study's label rows (R2: realistic; suffix "_ideal" the old labels' twin)."""
    from .store import base
    return base() / "rows" / f"select{suffix}.parquet"


def save_rows(table: dict[str, np.ndarray], meta: dict, path: Path | None = None) -> Path:
    from .retrain import save_rows as save_
    return save_(table, meta, path or rows_path())


def load_rows(path: Path | None = None) -> tuple[dict[str, np.ndarray], dict]:
    from .retrain import load_rows as load_
    return load_(path or rows_path())
