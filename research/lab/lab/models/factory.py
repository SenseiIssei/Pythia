"""M1 (results/modern_models_m1.md): the model factory, the learners every model and study can draw on. PAPER ONLY.

G2 (results/model_factory_g2.md, below the learners): the factory also makes models by itself, specs drawn and
mutated, screened in a purged walk-forward, held back over all trials, rotated through the zoo as shadows
(python -m lab.models.factory, job model-factory).

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

import hashlib
import json
import os
import random
import time
import warnings
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import polars as pl

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


# ================================================================ G2: specs made, judged and rotated by themselves
#
# python -m lab.models.factory [--budget S] [--status]   (job model-factory, daily; results/model_factory_g2.md)
#
# A spec is a target, a feature subset (the zoo's daily feature builders, plus up to two of G1's expression trees
# when lab.factory has them), a learner (LightGBM from a small space, ridge, logistic regression; no MLP: torch is
# not in the lab image) and a training window. Drawn at random (all of the first run, a third afterwards) or as a
# mutation of a target's best. Every spec is one trial in <data>/models/factory/ledger.jsonl, keyed by a hash of
# its settings; a spec tried before is never a new trial.
#
#   screen   quarterly walk-forward 2021-01-01 to 2023-12-31, expanding, purged: a training row's label ends
#            before the test block starts (ts + purge days < block start), so no train label overlaps a test one.
#            Against the trivial baseline and the zoo model it would replace, fitted in the same folds.
#   held back  2024-01-01 to 2026-06-30 (R6's validation; R6's lockbox from 2026-07-01 is never looked at here),
#            seen by at most HOLD_PER_RUN specs a run whose screen beat both; every look written to holdout.jsonl
#            before it is scored. The bar counts every trial: lower loss than the baseline and the incumbent with a
#            Diebold-Mariano p under core.GATE_P / N, N the ledger's trials (Bonferroni over all of them).
#   shadow   a spec that passes predicts every day (refit on all known rows) next to the incumbent; its forecasts
#            are logged before the outcome and scored against the baseline and the zoo's own logged forecasts
#            (models/zoo/<name>/shadow.jsonl). After ELIGIBLE_DAYS scored days the allocator may pick it; a member
#            worse than the baseline or the incumbent over its last RETIRE_DAYS scored days is retired.
#   leaks    before its look every spec goes through the leak harness (T1, lab.leak: its trees on the panel with the
#            rows after t changed or cut, no input the weekly leak check found leaking); a failing one is written to
#            holdout.jsonl as status "leak" with the reason and never held back.
#   allocator  per target a Thompson draw over the incumbent and the eligible shadows (Beta posteriors of the days
#            each had the lowest loss), written to picks.json for paper books only. Nothing live reads any of it.
#   T2       (results/overfit_yardsticks_prereg.md) per target the PBO by CSCV of the specs screened in the run
#            (minus their per-day mean loss in the screen window, metrics.cscv) with its rank logits, and for each
#            look a combinatorial purged CV of the screen window (cv.cpcv: CPCV_GROUPS groups, CPCV_TEST tested,
#            purge the target's purge days, embargo 1 % of the days, the spec and the baseline refitted on every
#            split, the spec's training window ignored): the paths' loss gain over the baseline in %, median and
#            10th percentile, one line per look in the report.
#
# Model losses are not daily Sharpes, so these trials stay out of the trial registry (metrics.trial_pool).

DAY_US = core.DAY_US
SCREEN_FROM, HOLD_FROM, HOLD_TO = "2021-01-01", "2024-01-01", "2026-07-01"
BUDGET_S = 1500                  # PYTHIA_MODEL_FACTORY_BUDGET or --budget: seconds a day for the search
HOLD_PER_RUN = 2
MAX_SHADOWS, NEW_SHADOWS = 6, 2
ELIGIBLE_DAYS, RETIRE_DAYS, ALLOC_DAYS = 30, 60, 90
RANDOM_SHARE = 1 / 3
TREE_SHARE = 0.3
MIN_TRAIN = 200                  # training rows a fold needs (M12 has about 250 a year)
EPS = 1e-12
CPCV_GROUPS, CPCV_TEST, CPCV_EMBARGO = 6, 2, 0.01     # T2: 15 splits, 5 paths

# target: kind (clf: a probability, logloss; var: a variance, QLIKE, fitted on its log; reg: a number, squared
# error, fitted as the change from `anchor` when there is one), the zoo model it would replace, the purge in days,
# the feature pool, whether trees apply (coin panels), the baseline in words.
TARGETS = {
    "m8": dict(kind="clf", incumbent="m8_direction", purge=1, trees=True,
               what="next UTC day up (M8's target)", baseline="the training rows' share of up days"),
    "m10": dict(kind="var", incumbent="m10_vol_regime", purge=1, trees=True,
                what="next UTC day's realised variance (M10's)", baseline="HAR on log 1, 7 and 30-day RV"),
    "m12": dict(kind="reg", incumbent="m12_cross_asset", purge=32, trees=False, anchor="z60",
                what="BTC and SPY correlation over the next 20 trading days, atanh (M12's)",
                baseline="the last 60 days' correlation"),
    "fwd7": dict(kind="reg", incumbent=None, purge=7, trees=True,
                 what="the strategy factory's forward return: next 7 days' log return over the 30-day vol scaled to 7 "
                      "days, less the day's cross-sectional mean (the 15 Alpaca coins)", baseline="no skill (0)"),
}
LEARNER_SPACE = {
    "lgb": {"n_estimators": [100, 200, 400], "learning_rate": [0.02, 0.05], "num_leaves": [3, 7, 15],
            "min_leaf": [50, 200, 800], "reg_lambda": [1.0, 10.0, 50.0]},
    "ridge": {"alpha": [0.1, 1.0, 10.0, 100.0]},
    "logit": {"C": [0.01, 0.1, 1.0]},
}
WINDOWS = [None, 365, 730, 1095]          # training window in days, None: everything before


def mf_dir() -> Path:
    from ..data import WRITE_ROOT
    return Path(os.environ.get("PYTHIA_MODEL_FACTORY_DIR", str(WRITE_ROOT / "models" / "factory")))


def reports_dir() -> Path:
    from .. import report
    return Path(os.environ.get("PYTHIA_REPORTS", str(report.REPORTS))) / "models"


def zoo_log(name: str) -> Path:
    from ..data import ROOT
    return ROOT / "models" / "zoo" / name / "shadow.jsonl"


def _day(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%d")


def _jl(p: Path) -> list[dict]:
    from ..factory.ledger import read_jsonl
    return read_jsonl(p)


def _append(p: Path, rows: list[dict]) -> None:
    from ..factory.ledger import append_jsonl
    append_jsonl(p, [core.finite(r) for r in rows])


def _write_json(p: Path, data) -> None:
    from ..factory.ledger import write_json
    write_json(p, core.finite(data))


def _read_json(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


# ---------------------------------------------------------------- panels

def fwd_panel(p: pl.DataFrame, h: int = 7, min_coins: int = 5) -> pl.DataFrame:
    """The coin panel with the strategy factory's forward return as target: log close h days on over the coin's
    30-day vol times sqrt(h), less the day's cross-sectional mean; null where the future is not known yet."""
    lc = pl.col("close").log()
    p = p.sort(["symbol", "ts_us"]).with_columns(
        z=((lc.shift(-h) - lc) / (pl.col("sigma") * np.sqrt(h))).over("symbol"))
    p = p.with_columns(zm=pl.col("z").mean().over("ts_us"), zn=pl.col("z").count().over("ts_us"))
    return (p.with_columns(target=pl.when(pl.col("zn") >= min_coins).then(pl.col("z") - pl.col("zm")).otherwise(None))
            .drop("z", "zm", "zn").filter(pl.col("sigma").is_not_null() & (pl.col("sigma") > 0))
            .sort(["ts_us", "symbol"]))


def _load(t: str) -> pl.DataFrame:
    from . import m8_direction as m8, m10_vol_regime as m10, m12_cross_asset as m12
    return {"m8": m8.load, "m10": m10.load, "m12": m12.load, "fwd7": lambda: fwd_panel(m8.coins_panel())}[t]()


def feature_pool(t: str, panel: pl.DataFrame) -> list[str]:
    """The zoo's feature builders: M8's and M10's inputs on the coin panels, M12's on its own."""
    from . import m8_direction as m8, m10_vol_regime as m10, m12_cross_asset as m12
    cand = m12.FEATURES if t == "m12" else list(dict.fromkeys(m8.FEATURES + m10.FEATURES))
    return [c for c in cand if c in panel.columns and panel[c].dtype.is_numeric()]


class Panels:
    """Each target's panel, loaded once per run (tests pass their own loaders)."""

    def __init__(self, loaders: dict | None = None):
        self.loaders, self.p, self.trees, self.inc = loaders, {}, {}, {}

    def get(self, t: str) -> pl.DataFrame:
        if t not in self.p:
            f = self.loaders[t]() if self.loaders else _load(t)
            self.p[t] = f.filter(pl.col("ts_us").is_not_null()).sort(["ts_us", "symbol"])
        return self.p[t]


def trees_available() -> bool:
    try:
        from ..factory import build, grammar  # noqa: F401
        return True
    except ImportError:
        return False


def tree_column(panel: pl.DataFrame, tree: dict) -> np.ndarray:
    """A G1 tree's value per panel row: the panel pivoted to (day, coin), the tree evaluated with lab.factory's
    operators (each reads only days up to the one it scores), read back per row."""
    from ..factory import build
    ts = panel["ts_us"].to_numpy()
    t0 = int(ts.min())
    di = ((ts - t0) // DAY_US).astype(int)
    syms, sj = np.unique(panel["symbol"].to_numpy().astype(str), return_inverse=True)
    T, n = int(di.max()) + 1, len(syms)

    def wide(col: str) -> np.ndarray:
        m = np.full((T, n), np.nan)
        if col in panel.columns:
            m[di, sj] = panel[col].fill_null(np.nan).to_numpy().astype(float)
        return m

    close, high, low = wide("close"), wide("high"), wide("low")
    btc = close[:, list(syms).index("BTC")][:, None] if "BTC" in syms else np.full((T, 1), np.nan)

    def leaf(name: str):
        if name == "close":
            return close
        if name == "volume":
            return wide("qv")
        if name == "range":
            with np.errstate(invalid="ignore", divide="ignore"):
                return (high - low) / close
        if name == "vol":
            return wide("sigma") * np.sqrt(365)
        if name == "btc":
            return btc
        return build.candle(high, low, close, name)

    x = np.broadcast_to(build.tree_values(tree, leaf, np.isfinite(close)), (T, n))
    return x[di, sj]


def tree_leaves() -> tuple:
    from ..factory import grammar
    return tuple(x for x in grammar.LEAVES if not x.startswith(grammar.FEATURE))


def matrix(P: Panels, t: str, spec: dict) -> np.ndarray:
    panel = P.get(t)
    cols = [panel[f].fill_null(np.nan).to_numpy().astype(float) for f in spec["features"]]
    for tr in spec.get("trees") or []:
        k = (t, json.dumps(tr, sort_keys=True))
        if k not in P.trees:
            P.trees[k] = tree_column(panel, tr)
        cols.append(P.trees[k])
    return np.column_stack(cols) if cols else np.zeros((panel.height, 0))


# ---------------------------------------------------------------- specs

def spec_key(spec: dict) -> str:
    return hashlib.sha1(json.dumps(spec, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:12]


def canonical_spec(s: dict) -> dict:
    from ..factory import grammar
    trees = sorted((grammar.canonical_tree(x) for x in s.get("trees") or []), key=grammar.tree_text) \
        if s.get("trees") else []
    return {"target": s["target"], "features": sorted(set(s["features"])), "trees": trees, "learner": s["learner"],
            "params": dict(sorted(s["params"].items())), "window": s.get("window")}


def learners_for(kind: str) -> tuple[str, ...]:
    return ("lgb", "logit") if kind == "clf" else ("lgb", "ridge")


def _params(rng: random.Random, learner: str) -> dict:
    return {k: rng.choice(v) for k, v in LEARNER_SPACE[learner].items()}


def random_spec(rng: random.Random, t: str, pool: list[str], trees: bool) -> dict:
    from ..factory import grammar
    k = rng.randint(min(3, len(pool)), min(12, len(pool)))
    tr = [grammar.random_tree(rng, tree_leaves()) for _ in range(rng.choice([1, 1, 2]))] \
        if trees and rng.random() < TREE_SHARE else []
    lr = rng.choice(learners_for(TARGETS[t]["kind"]))
    return canonical_spec({"target": t, "features": rng.sample(pool, k), "trees": tr, "learner": lr,
                           "params": _params(rng, lr), "window": rng.choice(WINDOWS)})


def mutate(spec: dict, rng: random.Random, pool: list[str], trees: bool) -> dict:
    """One change: a feature added, dropped or swapped, a learner setting, the learner, the window, a tree added,
    changed or dropped."""
    from ..factory import grammar
    s = json.loads(json.dumps(spec))
    moves = ["add", "drop", "swap", "param", "learner", "window"] + (["tree"] * 2 if trees else [])
    for _ in range(30):
        m = rng.choice(moves)
        out = [f for f in pool if f not in s["features"]]
        if m == "add" and out and len(s["features"]) < 16:
            s["features"].append(rng.choice(out))
        elif m == "drop" and len(s["features"]) > 2:
            s["features"].remove(rng.choice(s["features"]))
        elif m == "swap" and out and s["features"]:
            s["features"][rng.randrange(len(s["features"]))] = rng.choice(out)
        elif m == "param":
            k = rng.choice(list(LEARNER_SPACE[s["learner"]]))
            s["params"][k] = rng.choice(LEARNER_SPACE[s["learner"]][k])
        elif m == "learner":
            s["learner"] = rng.choice(learners_for(TARGETS[s["target"]]["kind"]))
            s["params"] = _params(rng, s["learner"])
        elif m == "window":
            s["window"] = rng.choice(WINDOWS)
        elif m == "tree":
            ts_ = s.get("trees") or []
            if ts_ and rng.random() < 0.3:
                ts_.pop(rng.randrange(len(ts_)))
            elif ts_ and rng.random() < 0.6:
                i = rng.randrange(len(ts_))
                ts_[i] = grammar.mutate_tree(ts_[i], rng, tree_leaves())
            elif len(ts_) < 2:
                ts_.append(grammar.random_tree(rng, tree_leaves()))
            s["trees"] = ts_
        else:
            continue
        c = canonical_spec(s)
        if spec_key(c) != spec_key(spec):
            return c
    return random_spec(rng, spec["target"], pool, trees)


def describe_spec(s: dict) -> str:
    p = ", ".join(f"{k} {v}" for k, v in s["params"].items())
    out = f"{s['learner']} ({p}) on {len(s['features'])} inputs"
    if s.get("trees"):
        from ..factory import grammar
        out += " + " + ", ".join(grammar.show_tree(x) for x in s["trees"])
    return out + (f", last {s['window']} days" if s.get("window") else ", all history")


# ---------------------------------------------------------------- fit, baseline, incumbent

class _Ridge:
    def __init__(self, alpha):
        self.alpha = alpha

    def fit(self, X, y):
        from sklearn.linear_model import Ridge
        self.prep = Prep().fit(X)
        self.m = Ridge(alpha=self.alpha).fit(self.prep(X), y)
        return self

    def predict(self, X):
        return self.m.predict(self.prep(X))


def _lgb(spec: dict, clf: bool, n: int):
    import lightgbm as lgb
    p = spec["params"]
    kw = dict(n_estimators=p["n_estimators"], learning_rate=p["learning_rate"], num_leaves=p["num_leaves"],
              min_child_samples=max(5, min(p["min_leaf"], n // 20)), reg_lambda=p["reg_lambda"], subsample=0.8,
              subsample_freq=1, colsample_bytree=0.8, n_jobs=threads(), verbose=-1, random_state=0)
    return lgb.LGBMClassifier(**kw) if clf else lgb.LGBMRegressor(**kw)


def fit_predict(t: str, spec: dict, Xtr, ytr, atr, Xte, ate) -> np.ndarray:
    """The spec's learner fitted on the training rows, its forecast for the test rows (a probability, a variance
    or a number as the target's kind says)."""
    kind = TARGETS[t]["kind"]
    Xtr, Xte = np.where(np.isinf(Xtr), np.nan, Xtr), np.where(np.isinf(Xte), np.nan, Xte)
    if kind == "clf":
        y = ytr.astype(int)
        if y.min() == y.max():
            return np.full(len(Xte), float(y.mean()))
        if spec["learner"] == "logit":
            from sklearn.linear_model import LogisticRegression
            prep = Prep().fit(Xtr)
            m = LogisticRegression(C=spec["params"]["C"], max_iter=500).fit(prep(Xtr), y)
            p = m.predict_proba(prep(Xte))[:, 1]
        else:
            p = _lgb(spec, True, len(y)).fit(Xtr, y).predict_proba(Xte)[:, 1]
        return np.clip(p, 1e-4, 1 - 1e-4)
    m = _Ridge(spec["params"]["alpha"]) if spec["learner"] == "ridge" else _lgb(spec, False, len(ytr))
    if kind == "var":
        ly = np.log(ytr + EPS)
        m.fit(Xtr, ly)
        rv = float(np.var(ly - m.predict(Xtr)))
        return np.exp(m.predict(Xte) + rv / 2)
    m.fit(Xtr, ytr - atr)
    return ate + m.predict(Xte)


def loss_of(t: str, y, f) -> np.ndarray:
    k = TARGETS[t]["kind"]
    return core.logloss(y, f) if k == "clf" else core.qlike(y, f) if k == "var" else core.squared(y, f)


def anchor(t: str, panel: pl.DataFrame) -> np.ndarray:
    a = TARGETS[t].get("anchor")
    return np.nan_to_num(panel[a].fill_null(np.nan).to_numpy().astype(float)) if a else np.zeros(panel.height)


def baseline_fit_predict(t: str, tr: pl.DataFrame, te: pl.DataFrame) -> np.ndarray:
    """The trivial baseline fitted on the same training rows: the base rate, HAR, the anchor carried forward, 0."""
    kind = TARGETS[t]["kind"]
    if kind == "clf":
        return np.full(te.height, float(tr["target"].mean()))
    if kind == "var":
        har = ["h1", "h7", "h30"]
        ly = np.log(tr["target"].to_numpy().astype(float) + EPS)
        Xh = np.column_stack([np.ones(tr.height), tr.select(har).fill_null(np.nan).to_numpy().astype(float)])
        ok = np.isfinite(Xh).all(1)
        beta = np.linalg.lstsq(Xh[ok], ly[ok], rcond=None)[0]
        rv = float(np.var(ly[ok] - Xh[ok] @ beta))
        Xt = np.column_stack([np.ones(te.height), te.select(har).fill_null(np.nan).to_numpy().astype(float)])
        return np.exp(Xt @ beta + rv / 2)
    return anchor(t, te)


def blocks(start: str, end: str) -> list[tuple[int, int]]:
    """Quarterly test blocks [lo, hi) from start to end."""
    out, y, m = [], int(start[:4]), int(start[5:7])
    lo = core.us(start)
    while lo < core.us(end):
        m += 3
        y, m = (y + 1, m - 12) if m > 12 else (y, m)
        hi = min(core.us(f"{y:04d}-{m:02d}-01"), core.us(end))
        out.append((lo, hi))
        lo = hi
    return out


def split(ts: np.ndarray, purge_days: int, lo: int, hi: int, window: int | None) -> tuple[np.ndarray, np.ndarray]:
    """(train, test) masks of one block: training rows whose label (ts + purge days) is known before the block
    starts, within the window; test rows inside [lo, hi)."""
    tr = ts + purge_days * DAY_US < lo
    if window:
        tr &= ts >= lo - window * DAY_US
    return tr, (ts >= lo) & (ts < hi)


def walk_spec(P: Panels, t: str, spec: dict, start: str, end: str, X: np.ndarray | None = None) -> tuple:
    """(forecast, baseline) for every row of the blocks from start to end, NaN elsewhere."""
    panel = P.get(t)
    ts, y = panel["ts_us"].to_numpy(), panel["target"].fill_null(np.nan).to_numpy().astype(float)
    a = anchor(t, panel)
    X = matrix(P, t, spec) if X is None else X
    pred, base = np.full(panel.height, np.nan), np.full(panel.height, np.nan)
    for lo, hi in blocks(start, end):
        tr, te = split(ts, TARGETS[t]["purge"], lo, hi, spec.get("window"))
        tr &= np.isfinite(y)
        if tr.sum() < MIN_TRAIN or not te.any():
            continue
        pred[te] = fit_predict(t, spec, X[tr], y[tr], a[tr], X[te], a[te])
        base[te] = baseline_fit_predict(t, panel.filter(pl.Series(tr)), panel.filter(pl.Series(te)))
    return pred, base


def walk_incumbent(P: Panels, t: str, start: str, end: str) -> np.ndarray | None:
    """The zoo model the spec would replace, fitted by its own module in the same purged folds (expanding, as the
    zoo trains it); None for a target without one. Once per run and window."""
    name = TARGETS[t]["incumbent"]
    if name is None:
        return None
    k = (t, start, end)
    if k not in P.inc:
        from . import zoo
        mod = zoo.module(name)
        panel = P.get(t)
        ts, y = panel["ts_us"].to_numpy(), panel["target"].fill_null(np.nan).to_numpy().astype(float)
        out = np.full(panel.height, np.nan)
        for lo, hi in blocks(start, end):
            tr, te = split(ts, TARGETS[t]["purge"], lo, hi, None)
            tr &= np.isfinite(y)
            if tr.sum() < MIN_TRAIN or not te.any():
                continue
            fitted = mod.fit(panel.filter(pl.Series(tr)))
            out[te] = np.asarray(mod.predict(fitted, panel.filter(pl.Series(te))), float)
        P.inc[k] = out
    return P.inc[k]


def judge(P: Panels, t: str, pred, base, inc, start: str, end: str) -> dict:
    """The spec against the baseline and the incumbent on the same scored rows of the window."""
    panel = P.get(t)
    ts, y = panel["ts_us"].to_numpy(), panel["target"].fill_null(np.nan).to_numpy().astype(float)
    ok = (ts >= core.us(start)) & (ts < core.us(end)) & np.isfinite(y) & np.isfinite(pred) & np.isfinite(base)
    if inc is not None:
        ok &= np.isfinite(inc)
    lag = TARGETS[t]["purge"]
    lm, lb = loss_of(t, y[ok], pred[ok]), loss_of(t, y[ok], base[ok])
    out = {"rows": int(ok.sum()), "days": int(len(np.unique(ts[ok]))), "base": gate(ts[ok], lm, lb, lag, "the baseline")}
    if inc is not None:
        out["inc"] = gate(ts[ok], lm, loss_of(t, y[ok], inc[ok]), lag, "the incumbent")
    gains = [g.get("gain_pct") for g in (out["base"], out.get("inc")) if g]
    out["fitness"] = min(gains) if gains and all(x is not None for x in gains) else None
    return out


def beats(j: dict, p_max: float) -> bool:
    """Lower than the baseline and the incumbent (when there is one), each with a DM p under p_max."""
    return all(g.get("other") is not None and g["model"] < g["other"] and g.get("dm_p") is not None
               and g["dm_p"] < p_max for g in (j.get("base"), j.get("inc")) if g is not None)


# ---------------------------------------------------------------- T2: PBO per target and CPCV of a look

def daily_loss(P: Panels, t: str, pred: np.ndarray, start: str, end: str) -> tuple[np.ndarray, np.ndarray]:
    """(days, mean loss per day) of a forecast over the window's scored rows."""
    panel = P.get(t)
    ts, y = panel["ts_us"].to_numpy(), panel["target"].fill_null(np.nan).to_numpy().astype(float)
    ok = (ts >= core.us(start)) & (ts < core.us(end)) & np.isfinite(y) & np.isfinite(pred)
    if not ok.any():
        return np.zeros(0, dtype=np.int64), np.zeros(0)
    u, inv = np.unique(ts[ok], return_inverse=True)
    lo = loss_of(t, y[ok], pred[ok])
    return u, np.bincount(inv, lo) / np.bincount(inv)


def target_pbo(series: dict[str, tuple]) -> dict | None:
    """PBO by CSCV of one target's specs on minus their per-day mean loss, over the days every spec scored."""
    from ..metrics import cscv
    xs = [v for v in series.values() if len(v[0])]
    if len(xs) < 2:
        return None
    days = xs[0][0]
    for d, _ in xs[1:]:
        days = np.intersect1d(days, d)
    M = np.column_stack([-v[np.searchsorted(d, days)] for d, v in xs]) if len(days) else np.zeros((0, len(xs)))
    return cscv(M, stat="mean")


def cpcv_spec(P: Panels, t: str, spec: dict, start: str = SCREEN_FROM, end: str = HOLD_FROM,
              n_groups: int = CPCV_GROUPS, k_test: int = CPCV_TEST) -> dict | None:
    """Combinatorial purged CV of a spec over a window: the window's scored rows in n_groups groups of days, every
    choice of k_test tested, training rows purged by the target's purge days and embargoed CPCV_EMBARGO of the days
    after each test group; the spec and the baseline refitted on each split. Returns the paths' loss gain over the
    baseline in % (median, 10th percentile). None when a split has too few training rows."""
    from .. import cv
    panel = P.get(t)
    ts, y = panel["ts_us"].to_numpy(), panel["target"].fill_null(np.nan).to_numpy().astype(float)
    rows = np.flatnonzero((ts >= core.us(start)) & (ts < core.us(end)) & np.isfinite(y))
    if not len(rows):
        return None
    tw, X, a = ts[rows], matrix(P, t, spec)[rows], anchor(t, panel)[rows]
    sub = panel[rows]
    ndays = len(np.unique(tw))
    splits = cv.cpcv(tw, n_groups, k_test, purge=TARGETS[t]["purge"] * DAY_US,
                     embargo=int(np.ceil(CPCV_EMBARGO * ndays)) * DAY_US)
    lm, lb = [], []
    for sp in splits:
        if sp.train.sum() < MIN_TRAIN:
            return None
        m, b = np.full(len(rows), np.nan), np.full(len(rows), np.nan)
        pr = fit_predict(t, spec, X[sp.train], y[rows][sp.train], a[sp.train], X[sp.test], a[sp.test])
        bs = baseline_fit_predict(t, sub.filter(pl.Series(sp.train)), sub.filter(pl.Series(sp.test)))
        m[sp.test], b[sp.test] = loss_of(t, y[rows][sp.test], pr), loss_of(t, y[rows][sp.test], bs)
        lm.append(m)
        lb.append(b)
    pm, pb = cv.assemble(splits, lm, n_groups, k_test, tw), cv.assemble(splits, lb, n_groups, k_test, tw)
    gains = []
    for x, z in zip(pm, pb):
        ok = np.isfinite(x) & np.isfinite(z)
        mb = float(z[ok].mean()) if ok.any() else float("nan")
        gains.append((mb - float(x[ok].mean())) / abs(mb) * 100 if ok.any() and mb else float("nan"))
    g = np.array(gains)
    g = g[np.isfinite(g)]
    if not len(g):
        return None
    return {"paths": len(g), "splits": len(splits), "groups": n_groups, "test_groups": k_test,
            "median": float(np.median(g)), "p10": float(np.percentile(g, 10))}


def look_line(h: dict, pbo: dict | None) -> str:
    """One line per look: the DM p against the baseline (lower is better), the target's PBO today, CPCV."""
    base = (h.get("held") or {}).get("base") or {}
    c = h.get("cpcv")
    dm = base.get("dm_p")
    cp = (f"CPCV of the screen median gain {c['median']:.2f} %, 10th percentile {c['p10']:.2f} % over {c['paths']} "
          f"paths" if c else "CPCV n/a")
    return (f"- {h['key']} ({h['target']}): DM p against the baseline {'n/a' if dm is None else f'{dm:.3g}'} (lower is "
            f"better, the bar p < {h['bar_p']:.2g}) · PBO of the target's specs today "
            f"{'n/a' if not pbo else format(pbo['pbo'], '.2f')} · {cp}")


# ---------------------------------------------------------------- ledger, search, held back

def ledger_path() -> Path:
    return mf_dir() / "ledger.jsonl"


def seed_dir() -> Path:
    """Trials made elsewhere and committed (results/model_factory_seed: the first run, made in the agent container on
    the server's data); every run merges them first, so they count on the server too and the bar does not start low."""
    default = Path(__file__).resolve().parents[2] / "results" / "model_factory_seed"
    return Path(os.environ.get("PYTHIA_MODEL_FACTORY_SEED", str(default)))


SEED_KEEP = ("key", "run", "target", "spec", "fitness", "screen_pass", "error")


def seed_row(r: dict) -> dict:
    """A ledger row without the words (they are rebuilt on import): the spec, its fitness and the screen's numbers."""
    out = {k: r[k] for k in SEED_KEEP if k in r}
    sc = r.get("screen") or {}
    out["screen"] = {"rows": sc.get("rows"), "days": sc.get("days"), **{
        k: {x: (sc.get(k) or {}).get(x) for x in ("passed", "model", "other", "gain_pct", "dm_p")}
        for k in ("base", "inc") if sc.get(k)}}
    return out


def export_seed(dest: Path) -> int:
    dest.mkdir(parents=True, exist_ok=True)
    rows = [seed_row(r) for r in _jl(ledger_path())]
    (dest / "ledger.jsonl").write_text("".join(json.dumps(core.finite(r), separators=(",", ":")) + "\n" for r in rows),
                                       encoding="utf-8")
    return len(rows)


def import_seed(src: Path | None = None) -> int:
    """The seed's trials not in the ledger yet, appended (idempotent, never rewrites a line)."""
    p = (src or seed_dir()) / "ledger.jsonl"
    have = {r["key"] for r in _jl(ledger_path())}
    new = [dict(r, what=describe_spec(r["spec"])) for r in _jl(p) if r.get("key") and r["key"] not in have]
    _append(ledger_path(), new)
    return len(new)


def trial(P: Panels, spec: dict, run: str, keep: dict | None = None) -> dict:
    """One spec through the screen: a ledger row (an error is a trial too). keep: gets the spec's per-day mean loss
    in the screen window under its key (T2's PBO; in memory only)."""
    t, t0 = spec["target"], time.time()
    row = {"key": spec_key(spec), "run": run, "target": t, "spec": spec, "what": describe_spec(spec)}
    try:
        pred, base = walk_spec(P, t, spec, SCREEN_FROM, HOLD_FROM)
        j = judge(P, t, pred, base, walk_incumbent(P, t, SCREEN_FROM, HOLD_FROM), SCREEN_FROM, HOLD_FROM)
        row.update(screen=j, fitness=j["fitness"], screen_pass=beats(j, core.GATE_P))
        if keep is not None:
            keep[row["key"]] = daily_loss(P, t, pred, SCREEN_FROM, HOLD_FROM)
    except Exception as e:                       # a broken spec is a failed trial, never a crashed run
        row.update(error=f"{type(e).__name__}: {e}"[:300], fitness=None, screen_pass=False)
    row["seconds"] = round(time.time() - t0, 2)
    return row


def draw(rng: random.Random, P: Panels, targets: list[str], rows: list[dict], have: set,
         share: float = RANDOM_SHARE) -> dict | None:
    """A new spec: random (a `share` of them; all of the first run) or a mutation of one of its target's ten best;
    None when 50 draws give only specs tried before."""
    trees = trees_available()
    for _ in range(50):
        t = rng.choice(targets)
        pool = feature_pool(t, P.get(t))
        tr = trees and TARGETS[t]["trees"]
        best = sorted((r for r in rows if r.get("target") == t and r.get("fitness") is not None),
                      key=lambda r: -r["fitness"])[:10]
        s = mutate(rng.choice(best)["spec"], rng, pool, tr) if best and rng.random() >= share \
            else random_spec(rng, t, pool, tr)
        if spec_key(s) not in have:
            return s
    return None


def holdout_path() -> Path:
    return mf_dir() / "holdout.jsonl"


def look(P: Panels, row: dict, n_trials: int, run: str) -> dict:
    """One spec's held-back look, written down before it is scored; passes with lower loss than the baseline and
    the incumbent at a DM p under GATE_P / n_trials."""
    bar = core.GATE_P / max(n_trials, 1)
    looks = _jl(holdout_path())
    _append(holdout_path(), [{"key": row["key"], "run": run, "status": "looking", "n_trials": n_trials, "bar_p": bar,
                              "look": sum(1 for x in looks if x.get("status") == "looking") + 1}])
    t, spec = row["target"], row["spec"]
    pred, base = walk_spec(P, t, spec, HOLD_FROM, HOLD_TO)
    j = judge(P, t, pred, base, walk_incumbent(P, t, HOLD_FROM, HOLD_TO), HOLD_FROM, HOLD_TO)
    out = {"key": row["key"], "run": run, "status": "done", "target": t, "n_trials": n_trials, "bar_p": bar,
           "held": j, "passed": beats(j, bar)}
    _append(holdout_path(), [out])
    return out


def leak_reason(P: Panels, row: dict, bad_inputs: set | None = None) -> str | None:
    """T1: the spec through the leak harness before its held-back look (lab.leak.checks.spec: its G1 trees on the
    target's panel with every row after t changed or cut, and no input the weekly check found leaking); None
    when it passes, else the reason."""
    from .. import leak
    from ..leak import checks
    res = checks.spec(P.get(row["target"]), row["spec"], checks.bad_inputs() if bad_inputs is None else bad_inputs)
    return None if res["ok"] else leak.reason(res)


def to_hold(rows: list[dict], looks: list[dict], n: int = HOLD_PER_RUN) -> list[dict]:
    """The best screen passes never held back (a look begun and not finished is taken again; one rejected by the
    leak harness is never taken)."""
    done = {x["key"] for x in looks if x.get("status") in ("done", "leak")}
    return sorted((r for r in rows if r.get("screen_pass") and r["key"] not in done),
                  key=lambda r: -(r.get("fitness") or 0))[:n]


# ---------------------------------------------------------------- shadows, retirement, the allocator

def shadows_path() -> Path:
    return mf_dir() / "shadows.json"


def shadow_log(key: str) -> Path:
    return mf_dir() / "shadow" / f"{key}.jsonl"


def shadow_forecast(P: Panels, m: dict, now_ms: int) -> int:
    """The member refitted on every known row (its window), its forecast and the baseline's for the newest rows
    whose outcome is still open, logged before the outcome; rows logged before are skipped."""
    t, spec = m["target"], m["spec"]
    panel = P.get(t)
    ts, y = panel["ts_us"].to_numpy(), panel["target"].fill_null(np.nan).to_numpy().astype(float)
    open_ = ~np.isfinite(y)
    if not open_.any():
        return 0
    te = open_ & (ts == ts[open_].max())
    tr, _ = split(ts, TARGETS[t]["purge"], int(ts[te].max()) + DAY_US, 0, spec.get("window"))
    tr &= np.isfinite(y)
    if tr.sum() < MIN_TRAIN:
        return 0
    X, a = matrix(P, t, spec), anchor(t, panel)
    te &= np.isfinite(X).mean(1) >= 0.5
    if not te.any():
        return 0
    p = fit_predict(t, spec, X[tr], y[tr], a[tr], X[te], a[te])
    b = baseline_fit_predict(t, panel.filter(pl.Series(tr)), panel.filter(pl.Series(te)))
    have = {(int(r["ts_us"]), str(r["symbol"])) for r in _jl(shadow_log(m["key"]))}
    new = [{"ts_us": int(tt), "symbol": str(s), "pred": float(pp), "baseline": float(bb), "recorded_ms": now_ms}
           for tt, s, pp, bb in zip(ts[te], panel["symbol"].to_numpy()[te], p, b)
           if (int(tt), str(s)) not in have and np.isfinite(pp) and np.isfinite(bb)]
    _append(shadow_log(m["key"]), new)
    return len(new)


def daily_losses(t: str, logged: list[dict], panel: pl.DataFrame, inc_rows: list[dict]) -> pl.DataFrame:
    """Per scored day: the member's, the baseline's and (where the zoo logged it) the incumbent's mean loss."""
    if not logged:
        return pl.DataFrame(schema={"ts_us": pl.Int64, "model": pl.Float64, "baseline": pl.Float64,
                                    "incumbent": pl.Float64})
    rec = pl.DataFrame([{k: r[k] for k in ("ts_us", "symbol", "pred", "baseline")} for r in logged]).with_columns(
        pl.col("ts_us").cast(pl.Int64), pl.col("symbol").cast(pl.Utf8))
    tgt = panel.select("ts_us", "symbol", "target").drop_nulls("target").with_columns(
        pl.col("ts_us").cast(pl.Int64), pl.col("symbol").cast(pl.Utf8))
    j = rec.join(tgt, on=["ts_us", "symbol"], how="inner")
    inc = [r for r in inc_rows if isinstance(r.get("pred"), (int, float))]
    if inc:
        j = j.join(pl.DataFrame([{"ts_us": int(r["ts_us"]), "symbol": str(r["symbol"]), "inc": float(r["pred"])}
                                 for r in inc]).unique(["ts_us", "symbol"], keep="last"),
                   on=["ts_us", "symbol"], how="left")
    else:
        j = j.with_columns(inc=pl.lit(None, pl.Float64))
    y = j["target"].to_numpy().astype(float)
    li = j["inc"].fill_null(np.nan).to_numpy().astype(float)
    j = j.with_columns(lm=pl.Series(loss_of(t, y, j["pred"].to_numpy())),
                       lb=pl.Series(loss_of(t, y, j["baseline"].to_numpy())),
                       li=pl.Series(loss_of(t, y, li)))
    return (j.group_by("ts_us").agg(model=pl.col("lm").mean(), baseline=pl.col("lb").mean(),
                                    incumbent=pl.col("li").fill_nan(None).mean()).sort("ts_us"))


def review(m: dict, d: pl.DataFrame, day: str) -> dict:
    """Days scored, eligibility after ELIGIBLE_DAYS, retirement when worse than the baseline or the incumbent over
    the last RETIRE_DAYS scored days (each on the days it has)."""
    n = d.height
    m["scored_days"] = n
    if n:
        m["model_loss"], m["baseline_loss"] = float(d["model"].mean()), float(d["baseline"].mean())
        inc = d.drop_nulls("incumbent")
        m["incumbent_loss"] = float(inc["incumbent"].mean()) if inc.height else None
    if m["status"] == "shadow" and n >= ELIGIBLE_DAYS:
        m.update(status="eligible", eligible_day=day)
    if n >= RETIRE_DAYS:
        last = d.tail(RETIRE_DAYS)
        why = None
        if last["model"].mean() >= last["baseline"].mean():
            why = f"worse than the baseline over its last {RETIRE_DAYS} scored days"
        inc = d.drop_nulls("incumbent").tail(RETIRE_DAYS)
        if why is None and inc.height >= RETIRE_DAYS and inc["model"].mean() >= inc["incumbent"].mean():
            why = f"worse than the incumbent over its last {RETIRE_DAYS} common days"
        if why:
            m.update(status="retired", retired_day=day, why=why)
    return m


def allocate(t: str, members: dict[str, pl.DataFrame], day: str, draws: int = 4000) -> dict:
    """Thompson sampling over the incumbent (the baseline for a target without one) and the eligible shadows:
    each arm's Beta(1 + days it had the lowest loss, 1 + the other days) over the last ALLOC_DAYS days every arm
    was scored; the pick is one draw seeded by the day, P(best) from `draws` draws. For paper books only."""
    arms = list(members)
    if len(arms) < 2:
        return {"target": t, "pick": arms[0] if arms else None, "arms": {a: {"p_best": 1.0} for a in arms},
                "days": 0, "why": "no shadow eligible yet: the incumbent stays"}
    j = None
    for a, d in members.items():
        f = d.select("ts_us", pl.col("loss").alias(a))
        j = f if j is None else j.join(f, on="ts_us", how="inner")
    j = j.drop_nulls().sort("ts_us").tail(ALLOC_DAYS)
    L = j.select(arms).to_numpy()
    wins = np.bincount(L.argmin(1), minlength=len(arms)) if len(L) else np.zeros(len(arms), int)
    a_, b_ = 1 + wins, 1 + len(L) - wins
    rng = np.random.default_rng(int(hashlib.sha1(f"{t}:{day}".encode()).hexdigest()[:8], 16))
    pick = arms[int(np.argmax(rng.beta(a_, b_)))]
    best = np.bincount(np.argmax(rng.beta(a_[:, None], b_[:, None], (len(arms), draws)), 0), minlength=len(arms))
    return {"target": t, "pick": pick, "days": int(len(L)),
            "arms": {a: {"wins": int(wins[i]), "p_best": float(best[i] / draws),
                         "mean_loss": float(L[:, i].mean()) if len(L) else None} for i, a in enumerate(arms)},
            "why": f"Thompson draw over {len(L)} common days"}


def shadow_step(P: Panels, now_ms: int, log=print) -> dict:
    """Every active member: forecast, score, review; then the allocator per target."""
    day = _day(now_ms)
    sh = _read_json(shadows_path(), {"members": []})
    retired, picks = [], {}
    for m in sh["members"]:
        if m["status"] == "retired":
            continue
        t = m["target"]
        try:
            m["logged_today"] = shadow_forecast(P, m, now_ms)
            inc = TARGETS[t]["incumbent"]
            d = daily_losses(t, _jl(shadow_log(m["key"])), P.get(t), _jl(zoo_log(inc)) if inc else [])
            m["_d"] = d
            review(m, d, day)
            if m["status"] == "retired":
                retired.append(m["key"])
        except core.DataUnavailable as e:
            log(f"model factory: shadow {m['key']} waits for data: {e}")
        except Exception as e:                   # one member's failure never stops the others or the search
            log(f"model factory: shadow {m['key']} failed today: {type(e).__name__}: {e}")
    for t in TARGETS:
        mine = [m for m in sh["members"] if m["target"] == t and m.get("_d") is not None]
        if not mine:
            continue
        inc_name = "incumbent" if TARGETS[t]["incumbent"] else "baseline"
        d0 = mine[0]["_d"]
        arms = {inc_name: d0.select("ts_us", loss=pl.col(inc_name)).drop_nulls()}
        for m in mine:
            if m["status"] == "eligible":
                arms[m["key"]] = m["_d"].select("ts_us", loss=pl.col("model"))
        picks[t] = allocate(t, arms, day)
    for m in sh["members"]:
        m.pop("_d", None)
    _write_json(shadows_path(), sh)
    _write_json(mf_dir() / "picks.json", {"day": day, "for": "paper books only", "picks": picks})
    return {"members": sh["members"], "retired_today": retired, "picks": picks}


def admit(passed: list[dict], rows_by_key: dict, day: str) -> list[str]:
    """Held-back passes into the zoo as shadows: at most NEW_SHADOWS a run, MAX_SHADOWS active."""
    sh = _read_json(shadows_path(), {"members": []})
    have = {m["key"] for m in sh["members"]}
    active = sum(1 for m in sh["members"] if m["status"] != "retired")
    new = []
    for h in passed:
        if h["key"] in have or len(new) >= NEW_SHADOWS or active + len(new) >= MAX_SHADOWS:
            continue
        r = rows_by_key[h["key"]]
        sh["members"].append({"key": h["key"], "target": r["target"], "spec": r["spec"], "what": r["what"],
                              "added_day": day, "status": "shadow", "scored_days": 0})
        new.append(h["key"])
    _write_json(shadows_path(), sh)
    return new


# ---------------------------------------------------------------- the run

def run(now_ms: int | None = None, budget_s: float | None = None, loaders: dict | None = None,
        targets: list[str] | None = None, max_trials: int | None = None, log=print) -> dict:
    """The daily run: the shadow step, new specs until the day's budget is spent (a rerun the same day only uses
    what is left), the held-back looks, admissions, the report. Resumable: every trial and look is on disk the
    moment it is made."""
    now_ms = now_ms or int(time.time() * 1000)
    day = _day(now_ms)
    budget_s = float(os.environ.get("PYTHIA_MODEL_FACTORY_BUDGET", BUDGET_S) if budget_s is None else budget_s)
    targets = targets or list(TARGETS)
    mf_dir().mkdir(parents=True, exist_ok=True)
    from ..factory.ledger import _try_lock, _unlock
    with (mf_dir() / ".lock").open("a+") as fh:
        if not _try_lock(fh):
            raise RuntimeError("another model factory run holds the lock")
        try:
            return _run(now_ms, day, budget_s, Panels(loaders), targets, max_trials, log)
        finally:
            _unlock(fh)


def _run(now_ms, day, budget_s, P, targets, max_trials, log) -> dict:
    t_start = time.time()
    st = _read_json(mf_dir() / "state.json", {})
    used = float(st.get("used_s") or 0) if st.get("day") == day else 0.0
    seeded = import_seed()
    if seeded:
        log(f"model factory: {seeded} trials merged from {seed_dir()}")
    sh = shadow_step(P, now_ms, log)
    rows = _jl(ledger_path())
    have = {r["key"] for r in rows}
    run_id = day
    rng = random.Random(f"{day}:{len(rows)}")
    share = RANDOM_SHARE if rows else 1.0
    new: list[dict] = []
    series: dict[str, tuple] = {}
    avg = 10.0
    while True:
        spent = used + time.time() - t_start
        if spent + avg * (1 + 2 * HOLD_PER_RUN) > budget_s or (max_trials is not None and len(new) >= max_trials):
            break
        s = draw(rng, P, targets, rows, have, share)
        if s is None:
            break
        r = trial(P, s, run_id, series)
        _append(ledger_path(), [r])
        rows.append(r)
        have.add(r["key"])
        new.append(r)
        avg = float(np.mean([x["seconds"] for x in new]))
        _write_json(mf_dir() / "state.json", {"day": day, "used_s": used + time.time() - t_start})
        log(f"model factory: {r['target']} {r['what']}: fitness {r.get('fitness')}, "
            f"{'screen passed' if r['screen_pass'] else 'failed'}{' (' + r['error'] + ')' if r.get('error') else ''}")
    n_trials = len(have)
    looks_done = []
    for r in to_hold(rows, _jl(holdout_path())):
        if r["target"] not in targets:
            continue
        if why := leak_reason(P, r):
            _append(holdout_path(), [{"key": r["key"], "run": run_id, "status": "leak", "target": r["target"],
                                      "why": why}])
            log(f"model factory: {r['key']} ({r['target']}) rejected before its held-back look: {why}")
            continue
        h = look(P, r, n_trials, run_id)
        try:
            h["cpcv"] = cpcv_spec(P, r["target"], r["spec"])
        except Exception as e:                   # noqa: BLE001 (a yardstick must not stop the run)
            h["cpcv"], h["cpcv_error"] = None, f"{type(e).__name__}: {e}"[:200]
        looks_done.append(h)
        log(f"model factory: held back {r['key']} ({r['target']}): {'PASSED' if h['passed'] else 'failed'} "
            f"at p < {h['bar_p']:.2g}")
    _write_json(mf_dir() / "state.json", {"day": day, "used_s": used + time.time() - t_start})
    passed = [h for h in _jl(holdout_path()) if h.get("status") == "done" and h.get("passed")]
    admitted = admit(passed, {r["key"]: r for r in rows}, day)
    if admitted:
        sh["members"] = _read_json(shadows_path(), {"members": []})["members"]
    pbo = {t: target_pbo({r["key"]: series[r["key"]] for r in new if r.get("target") == t and r["key"] in series})
           for t in targets}
    doc = summary(now_ms, rows, new, _jl(holdout_path()), looks_done, sh, admitted, n_trials, pbo)
    write_report(doc)
    return doc


def summary(now_ms, rows, new, looks, looks_done, sh, admitted, n_trials, pbo=None) -> dict:
    members = sh["members"]
    done = [x for x in looks if x.get("status") == "done"]
    best = sorted((r for r in new if r.get("fitness") is not None), key=lambda r: -r["fitness"])[:5]
    per = {t: {"trials": sum(1 for r in rows if r.get("target") == t),
               "screen_passes": sum(1 for r in rows if r.get("target") == t and r.get("screen_pass"))} for t in TARGETS}
    return core.finite({
        "updated_ms": now_ms, "day": _day(now_ms), "trials_today": len(new), "trials_ever": n_trials,
        "errors_today": sum(1 for r in new if r.get("error")), "bar_p": core.GATE_P / max(n_trials, 1),
        "screen_passes_today": sum(1 for r in new if r.get("screen_pass")),
        "held_today": len(looks_done), "passed_today": sum(1 for h in looks_done if h["passed"]),
        "held_ever": len(done), "passed_ever": sum(1 for h in done if h.get("passed")), "per_target": per,
        "best_today": [{"key": r["key"], "target": r["target"], "what": r["what"], "fitness": r["fitness"],
                        "screen_pass": r["screen_pass"]} for r in best],
        "looks_today": [{"key": h["key"], "target": h["target"], "passed": h["passed"], "bar_p": h["bar_p"],
                         "base": (h["held"].get("base") or {}).get("why"),
                         "inc": (h["held"].get("inc") or {}).get("why"), "cpcv": h.get("cpcv"),
                         "line": look_line(h, (pbo or {}).get(h["target"]))} for h in looks_done],
        "pbo": pbo or {},
        "admitted_today": admitted, "retired_today": sh.get("retired_today") or [],
        "shadows": [{k: m.get(k) for k in ("key", "target", "what", "status", "added_day", "scored_days",
                                            "model_loss", "baseline_loss", "incumbent_loss", "retired_day", "why")}
                    for m in members],
        "picks": sh.get("picks") or {},
    })


def markdown(d: dict) -> str:
    sh = d["shadows"]
    act = [m for m in sh if m["status"] != "retired"]
    out = [f"# Model factory (G2), {d['day']}", "",
           f"Trials today {d['trials_today']} ({d['errors_today']} errors), {d['trials_ever']} in all; "
           f"screen passes today {d['screen_passes_today']}. Held back today {d['held_today']}, passed "
           f"{d['passed_today']} ({d['held_ever']} held back and {d['passed_ever']} passed in all; the bar is a "
           f"DM p under {d['bar_p']:.2g}, 0.05 over {d['trials_ever']} trials). Shadows {len(act)} active "
           f"({sum(1 for m in act if m['status'] == 'eligible')} eligible), admitted today "
           f"{len(d['admitted_today'])}, retired today {len(d['retired_today'])}. Paper only: nothing live reads "
           "this.", "", "| target | trials | screen passes |", "|---|---|---|"]
    out += [f"| {t} | {v['trials']} | {v['screen_passes']} |" for t, v in d["per_target"].items()]
    if d["best_today"]:
        out += ["", "Best today (fitness: the smaller gain in % over the baseline and the incumbent, screen 2021-23):",
                "", "| id | target | spec | fitness | screen |", "|---|---|---|---|---|"]
        out += [f"| {r['key']} | {r['target']} | {r['what']} | {r['fitness']:.2f} | "
                f"{'passed' if r['screen_pass'] else 'failed'} |" for r in d["best_today"]]
    for h in d["looks_today"]:
        out += ["", f"Held back {h['key']} ({h['target']}): {'passed' if h['passed'] else 'failed'}; baseline: "
                f"{h['base']}" + (f"; incumbent: {h['inc']}" if h["inc"] else "")]
    pbo = {t: p for t, p in (d.get("pbo") or {}).items() if p}
    if pbo or d["looks_today"]:
        from ..metrics import logit_text
        out += ["", "Overfitting (T2): PBO by CSCV of each target's specs screened today (16 blocks, every split, "
                "minus the per-day mean loss), and one line per look:", ""]
        out += [f"- {t}: PBO {p['pbo']:.2f} over {p['genomes']} specs; {logit_text(p)}" for t, p in pbo.items()]
        out += [h["line"] for h in d["looks_today"] if h.get("line")]
    if sh:
        out += ["", "| shadow | target | status | since | scored days | loss | baseline | incumbent |",
                "|---|---|---|---|---|---|---|---|"]
        out += [f"| {m['key']} | {m['target']} | {m['status']} | {m['added_day']} | {m.get('scored_days') or 0} | "
                f"{_n(m.get('model_loss'))} | {_n(m.get('baseline_loss'))} | {_n(m.get('incumbent_loss'))} |"
                for m in sh]
    if d["picks"]:
        out += ["", "Allocator (paper books only): " + "; ".join(
            f"{t} {p.get('pick')} ({p.get('why')})" for t, p in d["picks"].items())]
    return "\n".join(out) + "\n"


def _n(v) -> str:
    return "-" if v is None else f"{v:.4f}"


def write_report(d: dict) -> None:
    """reports/models/factory.md and factory.json (the briefing's research factory line reads the json)."""
    from .. import report
    act = [m for m in d["shadows"] if m["status"] != "retired"]
    head = report.feed_header(
        "Model factory (G2)", "ok",
        f"{d['trials_today']} new specs, {d['passed_today']} passed held back, {len(act)} shadows",
        [{"label": t, "value": f"{v['trials']} trials, {v['screen_passes']} screen passes"}
         for t, v in d["per_target"].items()], d["updated_ms"])
    out = reports_dir()
    out.mkdir(parents=True, exist_ok=True)
    (out / "factory.md").write_text(markdown(d), encoding="utf-8")
    _write_json(out / "factory.json", {**head, **d})


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="python -m lab.models.factory", description="G2, the model factory (paper only)")
    ap.add_argument("--budget", type=float, default=None, help="seconds for the search today (PYTHIA_MODEL_FACTORY_BUDGET)")
    ap.add_argument("--targets", default="", help="comma list of " + ", ".join(TARGETS))
    ap.add_argument("--max-trials", type=int, default=None)
    ap.add_argument("--export-seed", default="", help="write the ledger's trials as a seed into this folder and stop")
    a = ap.parse_args(argv)
    if a.export_seed:
        print(f"{export_seed(Path(a.export_seed))} trials written to {a.export_seed}")
        return 0
    d = run(budget_s=a.budget, targets=[x for x in a.targets.split(",") if x] or None, max_trials=a.max_trials)
    print(markdown(d))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
