"""M1 (results/modern_models_m1.md): time-series foundation models, zero shot, as forecasters and as features. PAPER ONLY.

Two pretrained forecasters that need no training on our data, each pinned by revision and downloaded once into
<data>/models/hub (factory.pinned_file):

  chronos_bolt_small   Amazon Chronos-Bolt small (48M parameters, Apache 2.0): the 10/50/90 % quantiles of the
                       next value from up to CONTEXT past values
  timesfm_2_5          Google TimesFM 2.5 200M for PyTorch (Apache 2.0), the newest open checkpoint that runs on
                       CPU: TimesFM 3.0 (2026-09) is under Google's TimesFM Non-Commercial License (no production
                       use, no commercial decisions), so it is not used

forecast_panel gives every row of a daily panel (one row per (ts_us, symbol)) the quantiles of the next day's value
of one column, forecast from that symbol's values up to and including the row's day only (a test changes every later
value and gets the same forecast). Forecasts are cached per model, revision, column, symbol, day and context length
(<data>/models/fm_cache), so a rerun or a second study pays nothing; a run stops at its time budget and leaves the
rest NaN, said in its info. Inference on CPU, PYTHIA_ML_THREADS threads, batches of BATCH series.

The study (lab.experiments.modern_m1) judges them by the zoo's gate against the zoo's incumbents (M8q's return
quantiles, M10's daily variance) and baselines on the same out-of-sample rows, and as inputs to the incumbents'
own LightGBM refitted on the same folds. Nothing a book or the engine reads uses them.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import polars as pl

from . import factory as F

QUANTILES = (0.1, 0.5, 0.9)
CONTEXT = 512
MIN_CONTEXT = 60
BATCH = 256


@dataclass(frozen=True)
class Pin:
    repo: str
    revision: str
    licence: str
    kind: str


PINS = {
    "chronos_bolt_small": Pin("amazon/chronos-bolt-small", "772f3d25d38aec6d914c8949dab4462e2d46f5d8",
                              "Apache-2.0", "chronos"),
    "timesfm_2_5": Pin("google/timesfm-2.5-200m-pytorch", "1d952420fba87f3c6dee4f240de0f1a0fbc790e3",
                       "Apache-2.0", "timesfm"),
}


def cache_dir() -> Path:
    from ..data import ROOT
    return Path(os.environ.get("PYTHIA_FM_CACHE", str(ROOT / "models" / "fm_cache")))


class Forecaster:
    """quantiles(contexts) -> (n, 3): the 10, 50 and 90 % quantiles of the value after each context."""
    name = ""
    revision = ""

    def quantiles(self, contexts: list[np.ndarray]) -> np.ndarray:
        raise NotImplementedError


class Chronos(Forecaster):
    def __init__(self, name: str = "chronos_bolt_small"):
        try:
            import torch
            from chronos import BaseChronosPipeline
        except ImportError:
            raise F.Unavailable("chronos-forecasting and torch are not installed (the ML image)") from None
        pin = PINS[name]
        torch.set_num_threads(F.threads())
        self.name, self.revision, self.torch = name, pin.revision, torch
        self.pipe = BaseChronosPipeline.from_pretrained(str(F.pinned_file(pin.repo, pin.revision)),
                                                        device_map="cpu", dtype=torch.float32)

    def quantiles(self, contexts):
        q, _ = self.pipe.predict_quantiles([self.torch.tensor(c, dtype=self.torch.float32) for c in contexts],
                                           prediction_length=1, quantile_levels=list(QUANTILES))
        return q[:, 0, :].numpy().astype(float)


class TimesFM(Forecaster):
    def __init__(self, name: str = "timesfm_2_5"):
        try:
            import timesfm
            import torch
        except ImportError:
            raise F.Unavailable("timesfm and torch are not installed (the ML image)") from None
        pin = PINS[name]
        torch.set_num_threads(F.threads())
        self.name, self.revision = name, pin.revision
        self.m = timesfm.TimesFM_2p5_200M_torch.from_pretrained(str(F.pinned_file(pin.repo, pin.revision)))
        self.m.compile(timesfm.ForecastConfig(max_context=CONTEXT, max_horizon=128, normalize_inputs=True,
                                              per_core_batch_size=64, use_continuous_quantile_head=True,
                                              fix_quantile_crossing=True, infer_is_positive=False))

    def quantiles(self, contexts):
        _, qs = self.m.forecast(horizon=1, inputs=[np.asarray(c, float) for c in contexts])
        # qs[..., 0] is the mean, then the 10 % to 90 % deciles
        return np.asarray(qs)[: len(contexts), 0, [1, 5, 9]].astype(float)


def load(name: str) -> Forecaster:
    return {"chronos": Chronos, "timesfm": TimesFM}[PINS[name].kind](name)


# ---------------------------------------------------------------- the cache

class Cache:
    """One parquet a model, revision and column: symbol, ts_us, n_ctx, q10, q50, q90."""

    def __init__(self, model: str, revision: str, column: str, root: Path | None = None):
        self.path = (root or cache_dir()) / f"{model}_{revision[:8]}" / f"{column}.parquet"
        self.rows: dict[tuple, tuple] = {}
        if self.path.exists():
            d = pl.read_parquet(self.path)
            for s, t, n, a, b, c in d.iter_rows():
                self.rows[(s, int(t), int(n))] = (a, b, c)
        self.new = 0

    def get(self, key: tuple):
        return self.rows.get(key)

    def put(self, key: tuple, q) -> None:
        self.rows[key] = tuple(float(x) for x in q)
        self.new += 1

    def save(self) -> None:
        if not self.new:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        keys = list(self.rows)
        d = pl.DataFrame({"symbol": [k[0] for k in keys], "ts_us": [k[1] for k in keys], "n_ctx": [k[2] for k in keys],
                          **{f"q{int(a * 100)}": [self.rows[k][i] for k in keys] for i, a in enumerate(QUANTILES)}})
        tmp = self.path.with_suffix(".tmp")
        d.write_parquet(tmp)
        tmp.replace(self.path)
        self.new = 0


# ---------------------------------------------------------------- forecasting a panel

def contexts_for(values: np.ndarray, idx: np.ndarray, context: int = CONTEXT) -> list[np.ndarray]:
    """The past window of each row in idx: values up to and including the row, at most `context` of them."""
    v = np.where(np.isfinite(values), values, np.nan)
    return [v[max(0, i - context + 1): i + 1] for i in idx]


def forecast_panel(panel: pl.DataFrame, column: str, fc: Forecaster, start_us: int, budget_s: float,
                   transform=None, cache: Cache | None = None, min_context: int = MIN_CONTEXT,
                   context: int = CONTEXT, log=print) -> tuple[np.ndarray, dict]:
    """(panel.height, 3) quantiles of the next day's transform(column) per row from start_us (NaN before it, with
    less than min_context past values or past the budget), and what it cost."""
    t0 = time.time()
    out = np.full((panel.height, len(QUANTILES)), np.nan)
    pos = np.arange(panel.height)
    order = panel.with_columns(_i=pl.Series(pos)).sort(["symbol", "ts_us"])
    todo = []
    hit = 0
    for (sym,), g in order.group_by(["symbol"], maintain_order=True):
        v = g[column].fill_null(np.nan).to_numpy().astype(float)
        if transform is not None:
            with np.errstate(all="ignore"):
                v = transform(v)
        ts, ii = g["ts_us"].to_numpy(), g["_i"].to_numpy()
        want = np.flatnonzero((ts >= start_us) & (np.arange(len(v)) >= min_context - 1))
        for k, ctx in zip(want, contexts_for(v, want, context)):
            key = (str(sym), int(ts[k]), len(ctx))
            q = cache.get(key) if cache is not None else None
            if q is not None:
                out[ii[k]] = q
                hit += 1
            else:
                todo.append((ii[k], key, ctx))
    done = 0
    stopped = False
    for b in range(0, len(todo), BATCH):
        if time.time() - t0 > budget_s:
            stopped = True
            break
        chunk = todo[b: b + BATCH]
        q = fc.quantiles([c for _, _, c in chunk])
        for (i, key, _), row in zip(chunk, q):
            row = np.sort(row)
            out[i] = row
            if cache is not None:
                cache.put(key, row)
        done += len(chunk)
        if cache is not None and (b // BATCH) % 20 == 19:
            cache.save()
    if cache is not None:
        cache.save()
    info = {"model": fc.name, "revision": fc.revision, "column": column, "cached": hit, "computed": done,
            "left": len(todo) - done, "seconds": time.time() - t0, "complete": not stopped,
            "s_per_1000": (time.time() - t0) / done * 1000 if done else None}
    log(f"fm: {fc.name} {column}: {hit:,} cached, {done:,} computed, {len(todo) - done:,} left in "
        f"{info['seconds']:.0f} s" + (" (budget reached)" if stopped else ""))
    return out, info


def lognormal_mean(q: np.ndarray) -> np.ndarray:
    """Mean of a variable whose log has these 10/50/90 % quantiles, taken as normal: exp(median + s^2 / 2)."""
    s = (q[:, 2] - q[:, 0]) / (2 * 1.2815515655446004)
    return np.exp(q[:, 1] + np.maximum(s, 0.0) ** 2 / 2)
