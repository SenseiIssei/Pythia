"""M1 (results/modern_models_m1.md): the model factory, the learners every model and study can draw on. PAPER ONLY.

A learner is a binary classifier behind one interface: fit(X, y) -> self and predict_proba(X) -> P(y = 1), one
float a row, NaN inputs allowed. LEARNERS is the only list that names them; a study asks for them by name and gets a
clear Unavailable (with the reason) for one that cannot run here, never a silent stand-in.

  base      the training rows' rate: the baseline every classifier must beat
  logit     logistic regression on every input (median fill, 1st/99th percentile clip, standardised)
  lgb       LightGBM, small and regularised (the lab image's booster)
  hgb       scikit-learn's histogram gradient boosting
  catboost  CatBoost, ordered boosting on the same inputs (the ML image, Dockerfile.ml)
  tabpfn    TabPFN v2, a transformer trained on synthetic tables that predicts in one forward pass from the
            training rows as its context (the ML image). The weights Prior-Labs/TabPFN-v2-clf at a pinned revision
            under the Prior Labs License 1.1 (Apache 2.0 with an attribution clause, commercial use allowed). The
            newer TabPFN 2.5, 2.6, 3 and 3.5 weights are non-commercial and, by their own terms, not for consumers
            in the sense of section 13 BGB, so not for a private person's trading research: not used. On CPU at most
            TABPFN_MAX_ROWS training rows and TABPFN_MAX_FEATURES inputs; a larger problem is skipped with the
            reason (TooLarge), never subsampled behind the study's back.

One bar for all of them (gate): lower mean loss than the baseline on the same out-of-sample rows and a
Diebold-Mariano p under core.GATE_P on the per-period mean losses, the zoo's gate (core.evaluate). A study that
compares several learners also deflates (metrics.deflated_sharpe) by the number it compared.

The pump.fun model zoo (lab.pumpfun_rt.zoo) has its own member list and the live retrain reads it, so nothing here
edits that list: zoo_members() wraps catboost and tabpfn in the zoo's Member interface and members() lends them
to its walk-forward for one study run only, putting the list back afterwards.
"""

from __future__ import annotations

import os
import warnings
from contextlib import contextmanager
from pathlib import Path

import numpy as np

from . import core

TABPFN_MAX_ROWS = int(os.environ.get("PYTHIA_TABPFN_MAX_ROWS", "3000"))
TABPFN_MAX_FEATURES = 500
TABPFN_ESTIMATORS = 2
TABPFN = {"repo": "Prior-Labs/TabPFN-v2-clf", "revision": "f851f2a3c941544733b712d8c0f96dfae9b28862",
          "file": "tabpfn-v2-classifier-finetuned-zk73skhh.ckpt",
          "licence": "Prior Labs License 1.1 (Apache 2.0 with an attribution clause)"}
CATBOOST = dict(iterations=300, learning_rate=0.05, depth=4, l2_leaf_reg=10.0, random_seed=0, verbose=False,
                allow_writing_files=False)
CLIP_Q = (1.0, 99.0)


class Unavailable(RuntimeError):
    """The learner's package or weights are not in this image (the ML image has them)."""


class TooLarge(RuntimeError):
    """The problem is larger than the learner may take on this machine."""


def hub_dir() -> Path:
    """Where pinned model weights live, downloaded once: <data>/models/hub."""
    from ..data import ROOT
    return Path(os.environ.get("PYTHIA_HUB_DIR", str(ROOT / "models" / "hub")))


def offline() -> bool:
    return os.environ.get("PYTHIA_HUB_OFFLINE", "") == "1" or os.environ.get("HF_HUB_OFFLINE", "") == "1"


def pinned_file(repo: str, revision: str, filename: str | None = None) -> Path:
    """A pinned file (or the whole repo at `revision`) from the hub dir; downloaded the first time unless offline."""
    try:
        from huggingface_hub import hf_hub_download, snapshot_download
    except ImportError:
        raise Unavailable("huggingface_hub is not installed (the ML image, research/lab/Dockerfile.ml)") from None
    kw = dict(revision=revision, cache_dir=str(hub_dir()))
    get = (lambda **k: hf_hub_download(repo, filename, **k)) if filename else (lambda **k: snapshot_download(repo, **k))
    try:
        return Path(get(local_files_only=True, **kw))
    except Exception:
        if offline():
            raise Unavailable(f"{repo}@{revision[:8]} is not in {hub_dir()} and downloads are off") from None
    return Path(get(**kw))


def threads() -> int:
    return int(os.environ.get("PYTHIA_ML_THREADS", "3"))


# ---------------------------------------------------------------- the learners

class Prep:
    """Median fill, a clip at the training rows' 1st and 99th percentiles, standardisation."""

    def fit(self, X: np.ndarray) -> "Prep":
        with np.errstate(all="ignore"), warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            med = np.nanmedian(X, axis=0) if len(X) else np.zeros(X.shape[1])
            self.med = np.where(np.isfinite(med), med, 0.0)
            Z = np.where(np.isfinite(X), X, self.med)
            self.lo, self.hi = np.percentile(Z, CLIP_Q[0], axis=0), np.percentile(Z, CLIP_Q[1], axis=0)
            Z = np.clip(Z, self.lo, self.hi)
            self.mu, sd = Z.mean(axis=0), Z.std(axis=0)
        self.sd = np.where(np.isfinite(sd) & (sd > 0), sd, 1.0)
        return self

    def __call__(self, X: np.ndarray) -> np.ndarray:
        Z = np.clip(np.where(np.isfinite(X), X, self.med), self.lo, self.hi)
        return (Z - self.mu) / self.sd


class Learner:
    NAME = ""
    NEEDS: tuple[str, ...] = ()                 # packages beyond the lab image's

    def __init__(self):
        self.base, self.ok = 0.5, False

    def _base(self, y: np.ndarray) -> bool:
        y = np.asarray(y, float)
        self.base = float(y.mean()) if len(y) else 0.5
        self.ok = len(y) >= 2 and y.min() != y.max()
        return self.ok

    def check(self, n_rows: int, n_features: int) -> None:
        """Raises TooLarge when the problem is too big for this learner here."""

    def fit(self, X: np.ndarray, y: np.ndarray) -> "Learner":
        raise NotImplementedError

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        raise NotImplementedError


class Base(Learner):
    NAME = "base"

    def fit(self, X, y):
        self._base(y)
        return self

    def predict_proba(self, X):
        return np.full(len(X), self.base)


class Logit(Learner):
    NAME = "logit"

    def fit(self, X, y):
        from sklearn.linear_model import LogisticRegression
        if self._base(y):
            self.prep = Prep().fit(X)
            self.m = LogisticRegression(max_iter=500, C=1.0).fit(self.prep(X), y.astype(int))
        return self

    def predict_proba(self, X):
        return self.m.predict_proba(self.prep(X))[:, 1] if self.ok else np.full(len(X), self.base)


class LGB(Learner):
    NAME = "lgb"
    PARAMS = dict(n_estimators=200, learning_rate=0.03, num_leaves=7, min_child_samples=50, subsample=0.8,
                  subsample_freq=1, colsample_bytree=0.8, reg_lambda=10.0, n_jobs=2, verbose=-1)

    def fit(self, X, y):
        import lightgbm as lgb
        if self._base(y):
            p = dict(self.PARAMS, min_child_samples=max(5, min(self.PARAMS["min_child_samples"], len(y) // 20)))
            self.m = lgb.LGBMClassifier(**p).fit(np.where(np.isinf(X), np.nan, X), y.astype(int))
        return self

    def predict_proba(self, X):
        return self.m.predict_proba(np.where(np.isinf(X), np.nan, X))[:, 1] if self.ok else np.full(len(X), self.base)


class HGB(Learner):
    NAME = "hgb"

    def _x(self, X):
        Z = np.where(np.isinf(X), np.nan, X)
        Z[:, self.empty] = 0.0
        return Z

    def fit(self, X, y):
        from sklearn.ensemble import HistGradientBoostingClassifier
        if self._base(y):
            self.empty = ~np.isfinite(X).any(axis=0)
            self.m = HistGradientBoostingClassifier(max_iter=150, learning_rate=0.05, max_leaf_nodes=7,
                                                    min_samples_leaf=max(5, min(50, len(y) // 20)),
                                                    l2_regularization=1.0, early_stopping=False,
                                                    random_state=0).fit(self._x(X), y.astype(int))
        return self

    def predict_proba(self, X):
        return self.m.predict_proba(self._x(X))[:, 1] if self.ok else np.full(len(X), self.base)


class CatBoost(Learner):
    NAME = "catboost"
    NEEDS = ("catboost",)

    def fit(self, X, y):
        from catboost import CatBoostClassifier
        if self._base(y):
            self.m = CatBoostClassifier(thread_count=threads(), **CATBOOST).fit(np.where(np.isinf(X), np.nan, X),
                                                                               y.astype(int))
        return self

    def predict_proba(self, X):
        return self.m.predict_proba(np.where(np.isinf(X), np.nan, X))[:, 1] if self.ok else np.full(len(X), self.base)


class TabPFN(Learner):
    NAME = "tabpfn"
    NEEDS = ("tabpfn", "torch")

    def check(self, n_rows, n_features):
        if n_rows > TABPFN_MAX_ROWS:
            raise TooLarge(f"TabPFN: {n_rows:,} training rows, over the CPU cap of {TABPFN_MAX_ROWS:,} "
                           "(PYTHIA_TABPFN_MAX_ROWS): skipped")
        if n_features > TABPFN_MAX_FEATURES:
            raise TooLarge(f"TabPFN: {n_features} inputs, over its limit of {TABPFN_MAX_FEATURES}: skipped")

    def fit(self, X, y):
        self.check(*X.shape)
        if not self._base(y):
            return self
        import torch
        from tabpfn import TabPFNClassifier
        torch.set_num_threads(threads())
        path = pinned_file(TABPFN["repo"], TABPFN["revision"], TABPFN["file"])
        self.empty = ~np.isfinite(X).any(axis=0)
        # ignore_pretraining_limits: its CPU limit of 1,000 rows gives way to ours (check), which is below its
        # pretraining limits of 10,000 rows and 500 inputs
        self.m = TabPFNClassifier(model_path=str(path), device="cpu", n_estimators=TABPFN_ESTIMATORS,
                                  ignore_pretraining_limits=True, random_state=0).fit(self._x(X), y.astype(int))
        return self

    def _x(self, X):
        Z = np.where(np.isinf(X), np.nan, X).astype(np.float32)
        Z[:, self.empty] = 0.0
        return Z

    def predict_proba(self, X):
        return self.m.predict_proba(self._x(X))[:, 1] if self.ok else np.full(len(X), self.base)


LEARNERS: dict[str, type[Learner]] = {c.NAME: c for c in (Base, Logit, LGB, HGB, CatBoost, TabPFN)}
BASELINE = "base"


def available(name: str) -> tuple[bool, str]:
    """(True, "") when the learner can run in this image, else (False, the reason)."""
    from importlib.util import find_spec
    missing = [p for p in LEARNERS[name].NEEDS if find_spec(p) is None]
    if missing:
        return False, f"{name}: {', '.join(missing)} not installed (the ML image, research/lab/Dockerfile.ml)"
    return True, ""


def make(name: str) -> Learner:
    ok, why = available(name)
    if not ok:
        raise Unavailable(why)
    return LEARNERS[name]()


# ---------------------------------------------------------------- the bar

def gate(ts: np.ndarray, loss_model: np.ndarray, loss_base: np.ndarray, lag: int = 1, what: str = "the baseline") -> dict:
    """The zoo's gate on the same rows: lower mean loss and a Diebold-Mariano p under core.GATE_P on per-period
    means (a timestamp counts once)."""
    from ..metrics import diebold_mariano
    ok = np.isfinite(loss_model) & np.isfinite(loss_base)
    if ok.sum() < 30:
        return {"passed": False, "rows": int(ok.sum()), "model": None, "other": None, "dm_p": None,
                "why": f"{int(ok.sum())} common rows: too few to judge"}
    lm, lb = float(loss_model[ok].mean()), float(loss_base[ok].mean())
    _, p = diebold_mariano(core.per_period(ts[ok], loss_model[ok]), core.per_period(ts[ok], loss_base[ok]),
                           lag=max(lag, 1))
    passed = bool(lm < lb and np.isfinite(p) and p < core.GATE_P)
    return {"passed": passed, "rows": int(ok.sum()), "model": lm, "other": lb,
            "gain_pct": (lb - lm) / abs(lb) * 100 if lb else None, "dm_p": float(p) if np.isfinite(p) else None,
            "why": f"{lm:.4f} vs {lb:.4f} for {what}, {'lower' if lm < lb else 'not lower'}, DM p {p:.3g}"
                   + ("" if passed else f"; the gate needs lower and p < {core.GATE_P}")}


def walk(X: np.ndarray, y: np.ndarray, t: np.ndarray, known: np.ndarray, blocks: list[tuple[float, float]],
         names: list[str], min_train: int = 50, log=print) -> dict:
    """Expanding walk-forward: for each test block [lo, hi) every learner trained on the rows whose label was known
    (known < lo) predicts the block's rows. {"p": {name: array, NaN outside the tests}, "skipped": {name: why},
    "seconds": {name: s}}. A learner that is unavailable or too large for a block is skipped with its reason."""
    import time
    out = {"p": {n: np.full(len(y), np.nan) for n in names}, "skipped": {}, "seconds": {n: 0.0 for n in names}}
    for lo, hi in blocks:
        tr = known < lo
        te = (t >= lo) & (t < hi)
        if tr.sum() < min_train or not te.any():
            continue
        for n in names:
            if n in out["skipped"] and not out["skipped"][n].startswith("TabPFN"):
                continue
            t0 = time.time()
            try:
                m = make(n)
                m.check(int(tr.sum()), X.shape[1])
                out["p"][n][te] = m.fit(X[tr], y[tr]).predict_proba(X[te])
            except (Unavailable, TooLarge) as e:
                out["skipped"][n] = str(e)
                log(f"model factory: {e}")
            out["seconds"][n] += time.time() - t0
    return out


# ---------------------------------------------------------------- the pump.fun zoo

def zoo_members() -> dict:
    """catboost and tabpfn in lab.pumpfun_rt.zoo's Member interface (fit(X, y, ctx), predict_proba, explain)."""
    from ..pumpfun_rt import zoo as Z

    def wrap(name: str):
        class M(Z.Member):
            NAME = name

            def fit(self, X, y, ctx):
                self._base(y)
                self.inner = make(name).fit(X, y)
                self.ok = self.inner.ok
                return self

            def predict_proba(self, X):
                return np.clip(self.inner.predict_proba(X), 0.0, 1.0)
        M.__name__ = f"Factory_{name}"
        return M
    return {n: wrap(n) for n in ("catboost", "tabpfn")}


@contextmanager
def members(names=("catboost", "tabpfn")):
    """Lends the factory's learners to the pump.fun zoo's walk-forward for one study run; the zoo's own list is
    put back afterwards, so the daily retrain never sees them."""
    from ..pumpfun_rt import zoo as Z
    saved = dict(Z.MEMBERS)
    try:
        Z.MEMBERS.update({k: v for k, v in zoo_members().items() if k in names})
        yield [n for n in names if n in Z.MEMBERS]
    finally:
        Z.MEMBERS.clear()
        Z.MEMBERS.update(saved)
