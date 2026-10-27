"""M1 (results/modern_models_m1.md): rolling split conformal intervals around a model's forecasts, and a paper sizing
variant on their width. PAPER ONLY.

Split conformal, rolling: for the rows of day d the calibration set is the rows of the WINDOW_DAYS before d whose
outcome was known before d started (the label horizon as embargo), never d itself or later. The nonconformity score
is the conformalised quantile regression one (Romano, Patterson and Candes 2019), s = max(lo - y, y - hi), with the
model's own interval [lo, hi]; for a point forecast lo = hi = f and s = |y - f|. The interval for day d is
[lo - q, hi + q] with q the ceil((n + 1)(1 - alpha)) / n empirical quantile of the n calibration scores: under
exchangeability within the window it covers at least 1 - alpha. Fewer than MIN_CAL calibration rows: no interval
(NaN), never a guess.

Sizing (width_scale): a position scaled by how narrow today's interval is against its own past, the median width of
the WINDOW_DAYS before over today's, clipped to [SCALE_LO, SCALE_HI] and never above full size; the study judges
the scaled book against the same book unscaled at the same costs.
"""

from __future__ import annotations

import math

import numpy as np

DAY_US = 86_400_000_000
WINDOW_DAYS = 180
MIN_CAL = 100
SCALE_LO, SCALE_HI = 0.25, 1.0


def level(scores: np.ndarray, alpha: float) -> float:
    """The split-conformal quantile of the calibration scores (inf when too few for the level asked)."""
    s = np.sort(scores[np.isfinite(scores)])
    n = len(s)
    k = math.ceil((n + 1) * (1 - alpha))
    return float(s[k - 1]) if 0 < k <= n else math.inf


def rolling(ts: np.ndarray, y: np.ndarray, lo: np.ndarray, hi: np.ndarray, alpha: float = 0.2,
            window_days: int = WINDOW_DAYS, embargo_days: int = 1, min_cal: int = MIN_CAL) -> dict:
    """Calibrated [lo - q, hi + q] per row with q from the window's earlier rows only. {"lo", "hi", "q"} arrays,
    NaN where the calibration set is too small."""
    ts = np.asarray(ts, dtype=np.int64)
    y, lo, hi = (np.asarray(a, float) for a in (y, lo, hi))
    score = np.maximum(lo - y, y - hi)
    day = ts // DAY_US
    order = np.argsort(day, kind="stable")
    ds, ss = day[order], score[order]
    q = np.full(len(y), np.nan)
    for d in np.unique(day):
        a = np.searchsorted(ds, d - window_days, side="left")
        # an outcome of a day e is known at the end of e + embargo_days - 1, so before d when e <= d - embargo_days
        b = np.searchsorted(ds, d - embargo_days, side="right")
        cal = ss[a:b]
        cal = cal[np.isfinite(cal)]
        if len(cal) >= min_cal:
            q[day == d] = level(cal, alpha)
    q = np.where(np.isfinite(q), q, np.nan)
    return {"lo": lo - q, "hi": hi + q, "q": q}


def coverage(y: np.ndarray, lo: np.ndarray, hi: np.ndarray) -> dict:
    ok = np.isfinite(y) & np.isfinite(lo) & np.isfinite(hi)
    if not ok.any():
        return {"rows": 0, "coverage": None, "width": None}
    inside = (y[ok] >= lo[ok]) & (y[ok] <= hi[ok])
    return {"rows": int(ok.sum()), "coverage": float(inside.mean()), "width": float(np.mean(hi[ok] - lo[ok]))}


def width_scale(ts: np.ndarray, width: np.ndarray, window_days: int = WINDOW_DAYS, min_cal: int = 30) -> np.ndarray:
    """Per row: the median interval width of the window's earlier days (all rows of them) over today's width,
    clipped to [SCALE_LO, SCALE_HI]; 1 where the history is too short or the width unknown."""
    ts = np.asarray(ts, dtype=np.int64)
    w = np.asarray(width, float)
    day = ts // DAY_US
    order = np.argsort(day, kind="stable")
    ds, ws = day[order], w[order]
    out = np.ones(len(w))
    for d in np.unique(day):
        a = np.searchsorted(ds, d - window_days, side="left")
        b = np.searchsorted(ds, d, side="left")
        past = ws[a:b]
        past = past[np.isfinite(past) & (past > 0)]
        m = day == d
        if len(past) >= min_cal:
            with np.errstate(all="ignore"):
                r = np.median(past) / w[m]
            out[m] = np.where(np.isfinite(r), np.clip(r, SCALE_LO, SCALE_HI), 1.0)
    return out
