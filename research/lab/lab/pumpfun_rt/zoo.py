"""A1 (results/pumpfun_adaptive_a1_prereg.md): the model zoo, every model behind one interface. PAPER ONLY.

A member is a class with a NAME, the label kinds it can serve (KINDS: "any", or "exit" for labels whose rows carry
the trade's exit time and return), fit(X, y, ctx), predict_proba(X) (the probability of the label, one float a row)
and explain(features, top) (its strongest features with a weight). The registry MEMBERS is the only place that names
them: adding or retiring a model is one line there and touches no other member. ctx is a dict: "label", "family"
("decision" for the study's decision rows, "select" for the migration rows), "params" (LightGBM's, the factory's
where F3 adopted some), "t" (decision times), "dur" (seconds from the decision to the exit), "ret" (the return).

  lgb     LightGBM as the daily retrain has it today: decision labels model.fit with model.params_for (F3's adopted
          settings, so the factory's tuning is reused and not repeated here), select labels selmodel.fit
  logit   logistic regression on every feature (median fill, 1st/99th percentile clip, standardised): the baseline
  hgb     scikit-learn's histogram gradient boosting, the second boosting library in the lab image (XGBoost and
          CatBoost are not in it; requirements.txt is unchanged)
  online  online logistic regression (SGD, log loss) updated in time order: on every row whose label is known,
          in the walk-forward hour by hour on the trades closed so far (stream)
  hazard  a discrete-time competing-risks model for "dump before +30 %": per row one line per interval of the
          holding time (EDGES) until its exit, a multinomial logistic regression of none / exit at a loss / exit
          at a gain on the features and the interval; P(win) is the chance the gain exit comes first. Only for the
          select win labels (their rows carry the label book's exit time and return)

Not built: the sequence model on the first seconds of trades (a 1D CNN or GRU). The lab image has no torch, and the
rows carry no per-second sequences (that needs a new replay pass of the raw trades); a member SEQ can be added to
MEMBERS once both exist, if it trains within 10 minutes on the VPS's CPU.
"""

from __future__ import annotations

import math
import warnings

import numpy as np

from . import model as M

EDGES = (0.0, 10.0, 30.0, 60.0, 120.0, 300.0)       # hazard intervals, seconds after the decision (the last open)
ONLINE_BATCH = 1_000
CLIP_Q = (1.0, 99.0)


class Prep:
    """Median fill, a clip at the training rows' 1st and 99th percentiles, standardisation."""

    def fit(self, X: np.ndarray) -> "Prep":
        with np.errstate(all="ignore"), warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)      # a column without a value: its median 0
            med = np.nanmedian(X, axis=0) if len(X) else np.zeros(X.shape[1])
            self.med = np.where(np.isfinite(med), med, 0.0)
            Z = np.where(np.isfinite(X), X, self.med)
            self.lo, self.hi = (np.percentile(Z, CLIP_Q[0], axis=0), np.percentile(Z, CLIP_Q[1], axis=0)) \
                if len(Z) else (self.med, self.med)
            Z = np.clip(Z, self.lo, self.hi)
            self.mu, sd = Z.mean(axis=0) if len(Z) else self.med, Z.std(axis=0) if len(Z) else np.ones(X.shape[1])
        self.sd = np.where(np.isfinite(sd) & (sd > 0), sd, 1.0)
        return self

    def __call__(self, X: np.ndarray) -> np.ndarray:
        Z = np.clip(np.where(np.isfinite(X), X, self.med), self.lo, self.hi)
        return (Z - self.mu) / self.sd


class Member:
    NAME = ""
    KINDS = ("any",)

    def __init__(self):
        self.base = 0.0
        self.ok = False                               # fitted with both classes

    def _base(self, y: np.ndarray) -> bool:
        self.base = float(y.mean()) if len(y) else 0.0
        self.ok = len(y) >= 2 and y.min() != y.max()
        return self.ok

    def fit(self, X: np.ndarray, y: np.ndarray, ctx: dict) -> "Member":
        raise NotImplementedError

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        raise NotImplementedError

    def stream(self, X: np.ndarray, t: np.ndarray, known_ms: np.ndarray, y: np.ndarray, step_ms: int) -> np.ndarray:
        """Predictions for rows in time order; a member that learns online updates itself as their labels become
        known (known_ms). The others predict them all at once."""
        return self.predict_proba(X)

    def explain(self, features: list[str], top: int = 8) -> list[tuple[str, float]]:
        return []


def _top(features: list[str], w: np.ndarray, top: int) -> list[tuple[str, float]]:
    w = np.abs(np.asarray(w, dtype=float))
    tot = float(w.sum()) or 1.0
    return sorted(((f, float(v / tot)) for f, v in zip(features, w)), key=lambda x: -x[1])[:top]


class LGB(Member):
    NAME = "lgb"

    def fit(self, X, y, ctx):
        from . import selmodel as SM
        self._base(y)
        feats = list(ctx.get("features") or [])
        if ctx.get("family") == "select":
            self.m, _ = SM.fit(X, y, feats)
        else:
            self.m = M.fit(X, y, feats, ctx.get("params"))
        self.ok = self.m.booster is not None
        return self

    def predict_proba(self, X):
        return np.clip(self.m.predict(X), 0.0, 1.0)

    def explain(self, features, top=8):
        return M.importance(self.m, top)


class Logit(Member):
    NAME = "logit"

    def fit(self, X, y, ctx):
        from sklearn.linear_model import LogisticRegression
        if not self._base(y):
            return self
        self.prep = Prep().fit(X)
        self.m = LogisticRegression(max_iter=500, C=1.0).fit(self.prep(X), y)
        return self

    def predict_proba(self, X):
        return self.m.predict_proba(self.prep(X))[:, 1] if self.ok else np.full(len(X), self.base)

    def explain(self, features, top=8):
        return _top(features, self.m.coef_[0], top) if self.ok else []


class HGB(Member):
    NAME = "hgb"

    def _x(self, X):
        """Infinities as missing, a column without a finite training value as zeros (the binning needs one)."""
        Z = np.where(np.isinf(X), np.nan, X)
        Z[:, self.empty] = 0.0
        return Z

    def fit(self, X, y, ctx):
        from sklearn.ensemble import HistGradientBoostingClassifier
        if not self._base(y):
            return self
        self.empty = ~np.isfinite(X).any(axis=0)
        small = ctx.get("family") == "select"
        self.m = HistGradientBoostingClassifier(max_iter=150 if small else 250, learning_rate=0.05,
                                                max_leaf_nodes=7 if small else 31,
                                                min_samples_leaf=20 if small else 200, l2_regularization=1.0,
                                                early_stopping=False, random_state=0).fit(self._x(X), y)
        return self

    def predict_proba(self, X):
        return self.m.predict_proba(self._x(X))[:, 1] if self.ok else np.full(len(X), self.base)


class Online(Member):
    """Logistic regression by SGD, fed in time order; the standardisation is the first training batch's."""
    NAME = "online"

    def fit(self, X, y, ctx):
        from sklearn.linear_model import SGDClassifier
        self._base(y)
        self.m = SGDClassifier(loss="log_loss", alpha=1e-4, learning_rate="constant", eta0=0.01, random_state=0)
        self.prep = Prep().fit(X[:max(ONLINE_BATCH, len(X) // 5)] if len(X) else X)
        self.seen, self.n, self.pos = False, 0, 0.0
        for i in range(0, len(y), ONLINE_BATCH):
            self.update(X[i:i + ONLINE_BATCH], y[i:i + ONLINE_BATCH])
        return self

    def update(self, X, y) -> None:
        if not len(y):
            return
        self.m.partial_fit(self.prep(X), y.astype(int), classes=np.array([0, 1]))
        self.n, self.pos = self.n + len(y), self.pos + float(y.sum())
        self.base = self.pos / self.n
        self.seen = 0 < self.pos < self.n                  # both classes seen: the model, else the rate so far

    def predict_proba(self, X):
        return self.m.predict_proba(self.prep(X))[:, 1] if self.seen else np.full(len(X), self.base)

    def stream(self, X, t, known_ms, y, step_ms):
        """Hour by hour (step_ms): predict the step's rows, then learn every row whose label became known by the
        step's end (rows before the step that closed in it included)."""
        out = np.empty(len(t))
        if not len(t):
            return out
        done = np.zeros(len(t), dtype=bool)
        lo = float(t[0])
        while lo <= t[-1]:
            hi = lo + step_ms
            m = (t >= lo) & (t < hi)
            if m.any():
                out[m] = self.predict_proba(X[m])
            k = ~done & (known_ms < hi) & (t < hi)
            if k.any():
                self.update(X[k], y[k])
                done |= k
            lo = hi
        return out

    def explain(self, features, top=8):
        return _top(features, self.m.coef_[0], top) if self.seen else []


class Hazard(Member):
    NAME = "hazard"
    KINDS = ("exit",)

    @staticmethod
    def intervals(dur: np.ndarray) -> np.ndarray:
        """The interval index a holding time ends in (the last one is open)."""
        return np.clip(np.searchsorted(np.asarray(EDGES[1:]), np.maximum(dur, 0.0), side="right"), 0, len(EDGES) - 1)

    def fit(self, X, y, ctx):
        from sklearn.linear_model import LogisticRegression
        if not self._base(y):
            return self
        self.prep = Prep().fit(X)
        Z = self.prep(X)
        k = self.intervals(np.asarray(ctx["dur"], dtype=float))
        cause = np.where(np.asarray(ctx["ret"], dtype=float) > 0, 2, 1)
        rows, ys = [], []
        for j in range(len(EDGES)):                   # person-period lines: alive at interval j
            a = k >= j
            if not a.any():
                continue
            rows.append(np.column_stack([Z[a], np.tile(np.eye(len(EDGES))[j], (int(a.sum()), 1))]))
            ys.append(np.where(k[a] == j, cause[a], 0))
        A, Y = np.vstack(rows), np.concatenate(ys)
        if len(set(Y.tolist())) < 3:
            self.ok = False
            return self
        self.m = LogisticRegression(max_iter=1000, C=1.0).fit(A, Y)
        return self

    def predict_proba(self, X):
        if not self.ok:
            return np.full(len(X), self.base)
        Z = self.prep(X)
        surv, p_up = np.ones(len(X)), np.zeros(len(X))
        cls = list(self.m.classes_)
        for j in range(len(EDGES)):
            h = self.m.predict_proba(np.column_stack([Z, np.tile(np.eye(len(EDGES))[j], (len(X), 1))]))
            hd, hu = h[:, cls.index(1)], h[:, cls.index(2)]
            if j == len(EDGES) - 1:                   # the open interval: every trade still held exits in it
                p_up += surv * hu / np.maximum(hu + hd, 1e-12)
            else:
                p_up += surv * hu
                surv = surv * np.clip(1 - hu - hd, 0.0, 1.0)
        return np.clip(p_up, 0.0, 1.0)

    def explain(self, features, top=8):
        if not self.ok:
            return []
        c = self.m.coef_[list(self.m.classes_).index(2)][:len(features)]
        return _top(features, c, top)


MEMBERS: dict[str, type[Member]] = {c.NAME: c for c in (LGB, Logit, HGB, Online, Hazard)}
BASELINE = "logit"
INCUMBENT = "lgb"                                     # today's model: the selector's first incumbent per label


def members_for(kind: str, names=None) -> list[str]:
    """The members that can serve a label of this kind ("any" or "exit"), in MEMBERS order."""
    return [n for n, c in MEMBERS.items() if (names is None or n in names) and ("any" in c.KINDS or kind in c.KINDS)]


def make(name: str) -> Member:
    return MEMBERS[name]()


def logloss_rows(p: np.ndarray, y: np.ndarray) -> np.ndarray:
    q = np.clip(p, 1e-6, 1 - 1e-6)
    return -(y * np.log(q) + (1 - y) * np.log(1 - q))


def finite(x) -> bool:
    return x is not None and isinstance(x, (int, float)) and math.isfinite(x)
