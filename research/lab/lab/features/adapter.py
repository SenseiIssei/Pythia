"""The feature store as the factories' feature source.

There is no model factory (lab.models.factory) yet: model_frame() is what one would call, a matrix of any
registered features on its own (asset, time) rows. The strategy factory's expression trees take a feature
as a leaf "f.<name>" (factory/grammar.py); build.leaf asks daily_matrix() for it on the panel's closes, and
the weekly search draws the features whose cached coverage spans enough of its in-sample window
(drawable()).
"""

from __future__ import annotations

import numpy as np
import polars as pl

from . import registry as R
from . import store


def model_frame(names: list[str], rows: pl.DataFrame, freq: str = "1h") -> tuple[np.ndarray, list[str]]:
    """X (len(rows), len(names)) for rows with columns ts_us (the time a prediction is made) and asset,
    in the rows' order; NaN where a feature is not known at that time."""
    if not rows.height:
        return np.empty((0, len(names))), list(names)
    f = R.frame(names, rows["asset"].unique().to_list(), rows["ts_us"].to_list(), freq)
    x = rows.select("ts_us", "asset").with_row_index("_i").join(f, on=["ts_us", "asset"], how="left").sort("_i")
    return x.select(names).cast(pl.Float64).fill_null(np.nan).to_numpy(), list(names)


def daily_matrix(name: str, assets: list[str], closes: np.ndarray) -> np.ndarray:
    """(T, len(assets)) the daily feature known at each close (us); (T, 1) for a market feature."""
    f = R.get(name)
    cols = [R.MARKET] if f.market else list(dict.fromkeys(assets))
    fr = R.frame([name], ["_"] if f.market else cols, closes, "1d")
    w = fr.pivot(on="asset", index="ts_us", values=name)
    idx = pl.DataFrame({"ts_us": np.asarray(closes, dtype=np.int64)})
    w = idx.join(w, on="ts_us", how="left")
    if f.market:
        return w.select(pl.col("_").cast(pl.Float64)).fill_null(np.nan).to_numpy() if "_" in w.columns \
            else np.full((len(closes), 1), np.nan)
    pos = {a: i for i, a in enumerate(cols)}
    out = np.full((len(closes), len(cols)), np.nan)
    for a in cols:
        if a in w.columns:
            out[:, pos[a]] = w[a].cast(pl.Float64).fill_null(np.nan).to_numpy()
    return out[:, [pos[a] for a in assets]]


def drawable(start_us: int, end_us: int, min_share: float = 0.5, cov: dict | None = None) -> list[str]:
    """Features whose cached coverage (coverage.json of the nightly build) starts early enough to cover at
    least `min_share` of [start_us, end_us); an empty list without a coverage file."""
    cov = store.read_coverage() if cov is None else cov
    out = []
    for n in R.names():
        c = cov.get("features", {}).get(n)
        if not c or c.get("first_us") is None or end_us <= start_us:
            continue
        span = min(end_us, c["last_us"]) - max(start_us, c["first_us"])
        if span >= min_share * (end_us - start_us):
            out.append(n)
    return out
