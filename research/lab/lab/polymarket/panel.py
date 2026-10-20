"""Point-in-time market states from the resolved set (results/polymarket_prereg.md, "Market states").

A decision time is every 00:00 UTC while a market is open (every full hour for
markets that lived under two days), from creation plus one hour to its close.
The price is the last history point at or before the decision time, from the
finest series that has one, at most 36 hours old. Every feature uses only
points at or before the decision time; the scheduled end date is known from
creation. Final volume and liquidity are not features (hindsight).
"""

from __future__ import annotations

import math
import warnings

import numpy as np
import polars as pl

from . import store

DAY_S, HOUR_S = 86_400, 3_600
MAX_AGE_S = 36 * HOUR_S
SHORT_LIFE_S = 2 * DAY_S
CLIP = 0.005
PRICE_EDGES = [0.0, 0.02, 0.05, 0.10, 0.20, 0.35, 0.50, 0.65, 0.80, 0.90, 0.95, 0.98, 1.0001]
PRICE_LABELS = ["0-2", "2-5", "5-10", "10-20", "20-35", "35-50", "50-65", "65-80", "80-90", "90-95", "95-98",
                "98-100"]
HORIZON_EDGES = [-1e9, 1, 3, 7, 30, 90, 1e9]
HORIZON_LABELS = ["<1d", "1-3d", "3-7d", "7-30d", "30-90d", ">90d"]
FEATURES = ["p", "logit_p", "edge_dist", "days_to_end", "days_since", "life_frac", "chg_1d", "chg_7d", "vol_7d",
            "hi", "lo", "neg_risk", "cat_code", "kind_code"]


def logit(p):
    p = np.clip(np.asarray(p, dtype=float), CLIP, 1 - CLIP)
    return np.log(p / (1 - p))


def price_bucket(p) -> np.ndarray:
    return np.clip(np.searchsorted(PRICE_EDGES, np.asarray(p, dtype=float), side="right") - 1, 0,
                   len(PRICE_LABELS) - 1)


def horizon_bucket(days) -> np.ndarray:
    return np.clip(np.searchsorted(HORIZON_EDGES, np.asarray(days, dtype=float), side="right") - 1, 0,
                   len(HORIZON_LABELS) - 1)


def load_resolved() -> tuple[pl.DataFrame | None, pl.DataFrame | None]:
    """The sampled resolved markets (with their end month as _month) and their history."""
    frames = []
    for f in sorted(store.path("resolved", "markets").glob("*.parquet")):
        d = store.read_parquet(f)
        if d is not None and d.height:
            frames.append(d.with_columns(pl.lit(f.stem).alias("_month")))
    mk = pl.concat(frames, how="diagonal_relaxed") if frames else None
    return mk, store.read_all("resolved/history")


def _series(h: pl.DataFrame) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    """market_id -> (t_s sorted, p), finer resolution winning on equal times."""
    rank = {"m10": 0, "h": 1, "d": 2}
    h = h.with_columns(pl.col("res").replace_strict(rank, default=3).alias("r")).sort(["market_id", "t_s", "r"])
    h = h.unique(subset=["market_id", "t_s"], keep="first", maintain_order=True)
    out = {}
    for (mid,), g in h.group_by(["market_id"], maintain_order=True):
        out[str(mid)] = (g["t_s"].to_numpy().astype(np.int64), g["p"].to_numpy().astype(float))
    return out


def _at(t: np.ndarray, p: np.ndarray, when: np.ndarray) -> np.ndarray:
    """Price at each time in `when` (last point at or before, at most MAX_AGE_S old), NaN otherwise."""
    i = np.searchsorted(t, when, side="right") - 1
    ok = i >= 0
    out = np.full(len(when), np.nan)
    ii = np.where(ok, i, 0)
    fresh = ok & (when - t[ii] <= MAX_AGE_S)
    out[fresh] = p[ii[fresh]]
    return out


def features(rec: dict, t: np.ndarray, p: np.ndarray, grid: np.ndarray, px: np.ndarray, created: int,
             end: int) -> list[dict]:
    """The feature rows at the decision times `grid` (seconds) with prices `px`, from the
    history (t, p) up to each time. Shared by the panel and the live book."""
    p1 = _at(t, p, grid - DAY_S)
    p7 = _at(t, p, grid - 7 * DAY_S)
    lg = logit(px)
    # 7-day realised volatility of daily logit changes, from the price at each of the last 8 days
    lags = np.stack([logit(_at(t, p, grid - k * DAY_S)) for k in range(8)], axis=1)
    d = -np.diff(lags, axis=1)
    cnt = np.sum(~np.isnan(d), axis=1)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        vol = np.where(cnt >= 3, np.nanstd(d, axis=1), np.nan)
    # life-to-date high and low (the price at the decision time included)
    j = np.searchsorted(t, grid, side="right") - 1
    cm_hi, cm_lo = np.maximum.accumulate(p), np.minimum.accumulate(p)
    hi = np.where(j >= 0, np.maximum(cm_hi[np.maximum(j, 0)], px), px)
    lo = np.where(j >= 0, np.minimum(cm_lo[np.maximum(j, 0)], px), px)
    to_end = (end - grid) / DAY_S
    since = (grid - created) / DAY_S
    life = np.clip(since / np.maximum(since + np.maximum(to_end, 0), 1e-9), 0, 1)
    rows = []
    for k in range(len(grid)):
        rows.append({
            "market_id": rec["id"], "event_id": rec.get("event_id") or rec["id"], "t_s": int(grid[k]),
            "p": float(px[k]), "logit_p": float(lg[k]),
            "edge_dist": float(min(px[k], 1 - px[k])), "days_to_end": float(to_end[k]),
            "days_since": float(since[k]), "life_frac": float(life[k]),
            "chg_1d": float(lg[k] - logit(p1[k])) if not math.isnan(p1[k]) else math.nan,
            "chg_7d": float(lg[k] - logit(p7[k])) if not math.isnan(p7[k]) else math.nan,
            "vol_7d": float(vol[k]), "hi": float(hi[k]), "lo": float(lo[k]),
            "neg_risk": float(bool(rec.get("neg_risk"))),
            "category": rec["category"], "kind": rec["kind"],
        })
    return rows


def _first(*vals):
    return next((v for v in vals if v is not None), None)


def states_for(rec: dict, t: np.ndarray, p: np.ndarray) -> list[dict]:
    created = _first(rec.get("created_ms"), rec.get("start_ms"))
    close = _first(rec.get("closed_ms"), rec.get("end_ms"))
    end = _first(rec.get("end_ms"), rec.get("closed_ms"))
    if created is None or close is None or close <= created or not len(t):
        return []
    created, close, end = created // 1000, close // 1000, end // 1000
    created = max(created, int(t[0]) - HOUR_S)
    step = HOUR_S if close - created < SHORT_LIFE_S else DAY_S
    first = ((created + HOUR_S) // step + 1) * step
    grid = np.arange(first, close, step, dtype=np.int64)
    if not len(grid):
        return []
    px = _at(t, p, grid)
    keep = ~np.isnan(px)
    if not keep.any():
        return []
    rows = features(rec, t, p, grid[keep], px[keep], created, end)
    for r in rows:
        r.update(close_s=int(close), y=float(rec["outcome"]), volume=float(rec.get("volume") or 0.0))
    return rows


def live_features(rec: dict, t: np.ndarray, p: np.ndarray, now_s: int, p_now: float) -> dict:
    """One feature row for an open market now, at the current price, from its history so far."""
    created = (rec.get("created_ms") or rec.get("start_ms") or 0) // 1000 or (int(t[0]) if len(t) else now_s)
    if len(t):
        created = max(created, int(t[0]) - HOUR_S)
    end = (rec.get("end_ms") or 0) // 1000
    keep = t < now_s
    t2 = np.append(t[keep], now_s).astype(np.int64)
    p2 = np.append(p[keep], p_now).astype(float)
    return features(rec, t2, p2, np.array([now_s], dtype=np.int64), np.array([p_now]), created, end)[0]


def build(markets: pl.DataFrame, hist: pl.DataFrame, log=print) -> pl.DataFrame:
    series = _series(hist)
    rows: list[dict] = []
    for i, rec in enumerate(markets.iter_rows(named=True)):
        s = series.get(str(rec["id"]))
        if s is None or rec.get("outcome") not in (0.0, 1.0):
            continue
        rows.extend(states_for(rec, s[0], s[1]))
        if (i + 1) % 20000 == 0:
            log(f"  panel: {i + 1} markets, {len(rows)} states")
    if not rows:
        return pl.DataFrame()
    df = encode(pl.DataFrame(rows, infer_schema_length=None))
    return df.with_columns(
        pl.from_epoch("t_s", time_unit="s").dt.year().alias("year"),
        (pl.from_epoch("t_s", time_unit="s").dt.year().cast(pl.Utf8) + "Q"
         + pl.from_epoch("t_s", time_unit="s").dt.quarter().cast(pl.Utf8)).alias("quarter"),
    )


CAT_ORDER = ("crypto", "culture", "economics", "finance", "geopolitics", "mentions", "other", "politics", "sports",
             "tech", "weather")
KIND_ORDER = ("event", "game", "updown")


def encode(df: pl.DataFrame) -> pl.DataFrame:
    """Fixed category and kind codes (the live model must code them the same way)."""
    return df.with_columns(
        pl.col("category").replace_strict({c: i for i, c in enumerate(CAT_ORDER)}, default=len(CAT_ORDER))
        .cast(pl.Float64).alias("cat_code"),
        pl.col("kind").replace_strict({c: i for i, c in enumerate(KIND_ORDER)}, default=len(KIND_ORDER))
        .cast(pl.Float64).alias("kind_code"),
    )
