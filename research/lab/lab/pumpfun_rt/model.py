"""The learned model of the first seconds and minutes of a pump.fun token.

Rows come from the engine (sim.Engine with decisions on): every plain token at
3, 10, 30, 60, 120 and 300 s after creation while on its curve, with the
features of tokens.Token.features (events before t only) and four labels:

  dump60   the creator sells half or more of what it held at t within 60 s
  mig      the curve completes within 6 h of creation
  win30    a paper buy at t (latency, fees, slippage tolerance as in curve.py)
           sold at t + 30 s ends above 0 after every cost
  win300   the same, sold at t + 5 min

Method (results/pumpfun_realtime_plan.md): LightGBM with fixed parameters,
isotonic calibration on the last 20 % of each training window by time, purged
walk-forward over FOLDS folds of decision time (a training row's label window
must end EMBARGO before the fold starts), against the training base rate and
a logistic regression on six plain features. Retrained daily on every row,
the newest MAX_ROWS at most; the files go to <data>/models/pumpfun_rt/.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

from ..data import ROOT
from . import strategies as S
from .categorize import CAT_FEATURES
from .tokens import FEATURES
from .wallets import WALLET_FEATURES

# label -> how far its window reaches after the decision, in seconds (the purge horizon).
# The first four are the registered ones; the rest are plan addendum 2's exit models
# (a landing is at most 3 s after the decision).
LABELS = {"dump60": 60, "win30": 30, "win300": 300, "mig": 6 * 3600,
          "sell10_10": 10, "sell10_30": 30, "up10": 13, "up30": 33, "up120": 123}
# Feature sets in the order they are tried (plan addendum 2): a larger set is adopted for a
# label only if it beats the set before it out of sample by ADOPT_AUC and in ADOPT_FOLDS of the folds.
SETS = {"base": list(FEATURES), "wallet": list(FEATURES) + WALLET_FEATURES,
        "wallet+cat": list(FEATURES) + WALLET_FEATURES + CAT_FEATURES, "cat": list(FEATURES) + CAT_FEATURES}
ALL_FEATURES = list(FEATURES) + WALLET_FEATURES + CAT_FEATURES
ADOPT_AUC = 0.005
ADOPT_FOLDS = 0.8
EMBARGO_MS = 10 * 60_000
FOLDS = 5
MAX_ROWS = 3_000_000
MIN_TRAIN, MIN_TEST = 500, 100
SIMPLE = ["unique_buyers", "net_sol", "progress", "dev_sold", "age_s", "buys_10s"]
PARAMS = dict(n_estimators=300, learning_rate=0.05, num_leaves=31, min_child_samples=200, colsample_bytree=0.8,
              subsample=0.8, subsample_freq=1, verbose=-1, n_jobs=2)
USEFUL_AUC = 0.55


def model_dir() -> Path:
    return ROOT / "models" / "pumpfun_rt"


def as_frame(rows) -> dict[str, np.ndarray]:
    """Columns as numpy arrays, from the engine's table or a list of row dicts."""
    if isinstance(rows, dict):
        return rows
    cols = ["t"] + ALL_FEATURES + list(LABELS)
    return {c: np.array([float(r[c]) if r.get(c) is not None else math.nan for r in rows], dtype=float)
            for c in cols}


def matrix(rows, features: list[str] = FEATURES) -> np.ndarray:
    fr = as_frame(rows)
    n = len(fr["t"]) if "t" in fr else len(next(iter(fr.values())))
    return np.column_stack([fr[f] if f in fr else np.full(n, math.nan) for f in features]) if n else \
        np.zeros((0, len(features)))


def subset(fr: dict[str, np.ndarray], mask: np.ndarray) -> dict[str, np.ndarray]:
    return {k: v[mask] for k, v in fr.items()}


# ---------------------------------------------------------------- metrics

def auc(p: np.ndarray, y: np.ndarray) -> float:
    from scipy import stats
    pos, neg = p[y == 1], p[y == 0]
    if not len(pos) or not len(neg):
        return math.nan
    r = stats.rankdata(np.r_[pos, neg])
    return float((r[:len(pos)].sum() - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg)))


def brier(p: np.ndarray, y: np.ndarray) -> float:
    return float(np.mean((p - y) ** 2)) if len(y) else math.nan


def logloss(p: np.ndarray, y: np.ndarray) -> float:
    q = np.clip(p, 1e-6, 1 - 1e-6)
    return float(-np.mean(y * np.log(q) + (1 - y) * np.log(1 - q))) if len(y) else math.nan


def ece(p: np.ndarray, y: np.ndarray, bins: int = 10) -> float:
    if not len(y):
        return math.nan
    idx = np.minimum((p * bins).astype(int), bins - 1)
    tot = 0.0
    for b in range(bins):
        m = idx == b
        if m.any():
            tot += m.sum() * abs(p[m].mean() - y[m].mean())
    return float(tot / len(y))


def reliability(p: np.ndarray, y: np.ndarray, bins: int = 10) -> list[dict]:
    idx = np.minimum((p * bins).astype(int), bins - 1)
    out = []
    for b in range(bins):
        m = idx == b
        if m.sum():
            out.append({"bin": f"{b / bins:.1f}-{(b + 1) / bins:.1f}", "n": int(m.sum()),
                        "predicted": round(float(p[m].mean()), 4), "observed": round(float(y[m].mean()), 4)})
    return out


def scores(p: np.ndarray, y: np.ndarray, base: float) -> dict:
    b = brier(p, y)
    bb = brier(np.full(len(y), base), y)
    return {"n": int(len(y)), "rate": float(y.mean()) if len(y) else math.nan, "auc": auc(p, y), "brier": b,
            "brier_skill": 1 - b / bb if bb and bb > 0 else math.nan, "logloss": logloss(p, y), "ece": ece(p, y)}


# ---------------------------------------------------------------- fitting

class Fitted:
    """A calibrated LightGBM classifier: booster text, isotonic knots, base rate."""

    def __init__(self, booster, knots_x, knots_y, base: float, features: list[str]):
        self.booster, self.kx, self.ky, self.base, self.features = booster, knots_x, knots_y, base, features

    def predict(self, X: np.ndarray) -> np.ndarray:
        if self.booster is None:
            return np.full(len(X), self.base)
        raw = self.booster.predict(X)
        if self.kx is None or len(self.kx) < 2:
            return np.clip(raw, 0, 1)
        return np.interp(raw, self.kx, self.ky)

    def to_json(self) -> dict:
        return {"booster": self.booster.model_to_string() if self.booster is not None else None,
                "knots_x": list(map(float, self.kx)) if self.kx is not None else None,
                "knots_y": list(map(float, self.ky)) if self.ky is not None else None,
                "base": self.base, "features": self.features}

    @classmethod
    def from_json(cls, d: dict) -> "Fitted":
        booster = None
        if d.get("booster"):
            import lightgbm as lgb
            booster = lgb.Booster(model_str=d["booster"])
        kx = np.array(d["knots_x"]) if d.get("knots_x") else None
        ky = np.array(d["knots_y"]) if d.get("knots_y") else None
        return cls(booster, kx, ky, float(d["base"]), list(d["features"]))


def fit(X: np.ndarray, y: np.ndarray, features: list[str] = FEATURES) -> Fitted:
    """LightGBM on the first 80 % (rows in time order), isotonic on the last 20 %."""
    import lightgbm as lgb
    from sklearn.isotonic import IsotonicRegression
    base = float(y.mean()) if len(y) else 0.0
    if len(y) < MIN_TRAIN or y.min() == y.max():
        return Fitted(None, None, None, base, features)
    cut = int(len(y) * 0.8)
    clf = lgb.LGBMClassifier(**PARAMS)
    clf.fit(X[:cut], y[:cut])
    booster = clf.booster_
    raw = booster.predict(X[cut:])
    kx = ky = None
    if len(set(y[cut:].tolist())) == 2:
        iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0).fit(raw, y[cut:])
        kx, ky = iso.X_thresholds_, iso.y_thresholds_
    return Fitted(booster, kx, ky, base, features)


def logistic(Xtr: np.ndarray, ytr: np.ndarray, Xte: np.ndarray) -> np.ndarray:
    from sklearn.linear_model import LogisticRegression
    med = np.nanmedian(Xtr, axis=0)
    med = np.where(np.isfinite(med), med, 0.0)

    def prep(X):
        Z = np.where(np.isfinite(X), X, med)
        return Z
    A = prep(Xtr)
    mu, sd = A.mean(axis=0), A.std(axis=0)
    sd = np.where(sd > 0, sd, 1.0)
    if ytr.min() == ytr.max():
        return np.full(len(Xte), float(ytr.mean()))
    lr = LogisticRegression(max_iter=500).fit((A - mu) / sd, ytr)
    return lr.predict_proba((prep(Xte) - mu) / sd)[:, 1]


def labelled(rows, label: str) -> dict[str, np.ndarray]:
    """The rows with this label known, in time order."""
    fr = as_frame(rows)
    m = np.isfinite(fr[label])
    sub = subset(fr, m)
    order = np.argsort(sub["t"], kind="stable")
    return {k: v[order] for k, v in sub.items()}


def evaluate(rows, label: str, folds: int = FOLDS, features: list[str] | None = None,
             max_rows: int | None = None) -> dict:
    """Purged walk-forward of the model and both baselines on one label (the newest max_rows rows)."""
    features = list(features or FEATURES)
    rs = labelled(rows, label)
    if max_rows:
        rs = {k: v[-max_rows:] for k, v in rs.items()}
    n = len(rs["t"])
    out = {"label": label, "rows": int(n), "folds": [], "features": len(features)}
    if n < MIN_TRAIN + MIN_TEST:
        out["verdict"] = f"too few labelled rows ({n})"
        return out
    t = rs["t"]
    y = rs[label]
    X = matrix(rs, features)
    Xs = matrix(rs, SIMPLE)
    horizon = LABELS[label] * 1000 + EMBARGO_MS
    edges = np.quantile(t, np.linspace(0, 1, folds + 2))
    pooled = {"model": [], "logistic": [], "base": [], "y": []}
    beat = 0
    for i in range(1, folds + 1):
        lo, hi = edges[i], edges[i + 1]
        te = (t >= lo) & ((t < hi) if i < folds else (t <= hi))
        tr = t + horizon < lo
        if tr.sum() < MIN_TRAIN or te.sum() < MIN_TEST:
            continue
        m = fit(X[tr], y[tr], features)
        pm = m.predict(X[te])
        pl_ = logistic(Xs[tr], y[tr], Xs[te])
        base = float(y[tr].mean())
        f = {"fold": i, "train": int(tr.sum()), "test": int(te.sum()), "model": scores(pm, y[te], base),
             "logistic": scores(pl_, y[te], base), "base_rate": base}
        if f["model"]["brier"] < f["logistic"]["brier"]:
            beat += 1
        out["folds"].append(f)
        pooled["model"].append(pm)
        pooled["logistic"].append(pl_)
        pooled["base"].append(np.full(te.sum(), base))
        pooled["y"].append(y[te])
    if not out["folds"]:
        out["verdict"] = "no fold had enough rows before its embargo"
        return out
    yy = np.concatenate(pooled["y"])
    base_all = float(np.concatenate(pooled["base"]).mean())
    pm, pl_ = np.concatenate(pooled["model"]), np.concatenate(pooled["logistic"])
    out["pooled"] = {"model": scores(pm, yy, base_all), "logistic": scores(pl_, yy, base_all),
                     "base": scores(np.concatenate(pooled["base"]), yy, base_all)}
    out["reliability"] = reliability(pm, yy)
    out["beats_logistic_folds"] = beat
    pm_s = out["pooled"]["model"]
    need = max(1, math.ceil(0.8 * len(out["folds"])))
    useful = (pm_s["auc"] > USEFUL_AUC and pm_s["brier_skill"] > 0 and beat >= need)
    out["useful"] = bool(useful)
    out["verdict"] = (f"useful: AUC {pm_s['auc']:.3f}, Brier skill {pm_s['brier_skill']:+.3f}, beats the logistic "
                      f"baseline in {beat} of {len(out['folds'])} folds" if useful else
                      f"not useful: AUC {pm_s['auc']:.3f}, Brier skill {pm_s['brier_skill']:+.3f}, beats the "
                      f"logistic baseline in {beat} of {len(out['folds'])} folds")
    return out


def importance(m: Fitted, top: int = 12) -> list[tuple[str, float]]:
    if m.booster is None:
        return []
    g = m.booster.feature_importance(importance_type="gain")
    tot = g.sum() or 1.0
    return sorted(((f, float(v / tot)) for f, v in zip(m.features, g)), key=lambda x: -x[1])[:top]


def train_all(rows, until_ms: int | None = None, sets: dict[str, list[str]] | None = None) -> dict[str, Fitted]:
    """One calibrated model per label on every labelled row (whose window ends before until_ms),
    each with its adopted feature set (`sets`, the base features otherwise)."""
    out = {}
    for label, h in LABELS.items():
        rs = labelled(rows, label)
        if until_ms is not None:
            rs = subset(rs, rs["t"] + h * 1000 + EMBARGO_MS < until_ms)
        rs = {k: v[-MAX_ROWS:] for k, v in rs.items()}
        feats = list((sets or {}).get(label) or FEATURES)
        out[label] = fit(matrix(rs, feats), rs[label], feats)
    return out


def better(cand: dict, prev: dict) -> tuple[bool, str]:
    """Plan addendum 2: a larger feature set is adopted only if its pooled out-of-sample AUC is
    ADOPT_AUC above the smaller set's and its Brier score is lower in ADOPT_FOLDS of the folds."""
    pc, pp = (cand.get("pooled") or {}).get("model"), (prev.get("pooled") or {}).get("model")
    if not pc or not pp:
        return False, "not enough rows"
    prev_b = {f["fold"]: f["model"]["brier"] for f in prev.get("folds", [])}
    both = [(f["model"]["brier"], prev_b[f["fold"]]) for f in cand.get("folds", []) if f["fold"] in prev_b]
    wins = sum(1 for a, b in both if a < b)
    d = pc["auc"] - pp["auc"]
    ok = bool(both) and d >= ADOPT_AUC and wins >= math.ceil(ADOPT_FOLDS * len(both))
    return ok, f"AUC {d:+.4f}, Brier lower in {wins} of {len(both)} folds"


def select(rows, label: str, max_rows: int | None = None, folds: int = FOLDS) -> dict:
    """Base, then base plus wallet features, then the adopted set plus categories (plan addendum 2).
    Returns every evaluation, the adopted set's name and features, and the decisions."""
    evs = {"base": evaluate(rows, label, folds, SETS["base"], max_rows)}
    adopted = "base"
    notes = {}
    evs["wallet"] = evaluate(rows, label, folds, SETS["wallet"], max_rows)
    ok, why = better(evs["wallet"], evs["base"])
    notes["wallet"] = ("adopted: " if ok else "kept out: ") + why
    if ok:
        adopted = "wallet"
    nxt = "wallet+cat" if adopted == "wallet" else "cat"
    evs[nxt] = evaluate(rows, label, folds, SETS[nxt], max_rows)
    ok, why = better(evs[nxt], evs[adopted])
    notes["cat"] = ("adopted: " if ok else "kept out: ") + why
    if ok:
        adopted = nxt
    return {"label": label, "evals": evs, "adopted": adopted, "features": SETS[adopted], "notes": notes,
            "trials": len(evs)}


def save(models: dict[str, Fitted], meta: dict, d: Path | None = None) -> Path:
    d = d or model_dir()
    d.mkdir(parents=True, exist_ok=True)
    for label, m in models.items():
        tmp = d / f"{label}.json.tmp"
        tmp.write_text(json.dumps(m.to_json()), encoding="utf-8")
        tmp.replace(d / f"{label}.json")
    (d / "meta.json").write_text(json.dumps(meta, indent=1, default=str), encoding="utf-8")
    return d


def load(d: Path | None = None) -> dict[str, Fitted]:
    d = d or model_dir()
    out = {}
    for label in LABELS:
        p = d / f"{label}.json"
        if p.exists():
            try:
                out[label] = Fitted.from_json(json.loads(p.read_text(encoding="utf-8")))
            except (OSError, ValueError, KeyError):
                pass
    from .exitpol import load_models                     # X14: the early and exit models, the hazard policy
    out.update(load_models(d))
    from .selmodel import load_models as sel_models      # Y9: the select models and their thresholds
    out.update(sel_models(d))
    return out


class Filter:
    """The pre-registered model filter: enter only when the calibrated probability of the
    rule's round-trip label is at least FILTER_LIFT times that label's training base rate."""

    def __init__(self, models: dict[str, Fitted]):
        self.models = models

    @staticmethod
    def label_for(rule: S.Rule) -> str:
        return "win30" if rule.hold_s <= 60 else "win300"

    def allow(self, rule: S.Rule, features: dict) -> tuple[bool, float | None]:
        m = self.models.get(self.label_for(rule))
        if m is None or m.booster is None:
            return False, None
        x = np.array([[float(features.get(f, math.nan)) for f in m.features]], dtype=float)
        p = float(m.predict(x)[0])
        return p >= S.FILTER_LIFT * m.base, p
