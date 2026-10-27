"""M1 (results/modern_models_m1.md): meta-labelling, a second model that says whether the primary signal's trade will
pay after costs, used as a filter in paper only. PAPER ONLY.

The primary signal is a book's target weights W (T days x n assets, decided at each close). A trade is a run of days
an asset is held: it opens at the close of t_in (weight 0 the day before, above 0 that day) and closes at the first
later close t_out where its weight is 0 again (still open at the end: no label yet). Its label is 1 when its log
return from the close of t_in to the close of t_out, less the round trip cost, is above 0. The label is known at the
close of t_out, so a meta model trained before a block starts sees only trades closed before it (walk).

Features at the close of t_in only (features): the asset's 7, 28 and 90-day returns, its 60-day vol, its distance
to its 100 and 200-day means, BTC's 28-day return and distance to its 200-day mean, how many assets the book holds
that day, the trade's weight, and the days since the asset's last trade closed. The filter (filtered) drops a trade
whose probability is under the cut: the asset is not bought, its weight is 0 from t_in until t_out, the rest of the
book is unchanged (the slot stays cash). Nothing here reaches an order: the study runs the filtered book through
the same simulator and costs as the unfiltered one and judges it by the same bar.
"""

from __future__ import annotations

import numpy as np

CUT = 0.5
FEATURES = ["ret7", "ret28", "ret90", "vol60", "ma100_gap", "ma200_gap", "btc_ret28", "btc_ma200_gap", "n_held",
            "weight", "days_since"]


def trades(W: np.ndarray) -> list[tuple[int, int, int]]:
    """(asset, t_in, t_out) of every trade; t_out = -1 for one still open at the last row."""
    T, n = W.shape
    out = []
    held = W > 1e-12
    for j in range(n):
        h = held[:, j]
        t = 0
        while t < T:
            if h[t] and (t == 0 or not h[t - 1]):
                e = t + 1
                while e < T and h[e]:
                    e += 1
                out.append((j, t, e if e < T else -1))
                t = e
            else:
                t += 1
    return sorted(out, key=lambda x: (x[1], x[0]))


def labels(px: np.ndarray, tr: list[tuple[int, int, int]], cost: float) -> np.ndarray:
    """1 / 0 per trade (NaN while open): log(px[t_out] / px[t_in]) less the round trip `cost` above 0."""
    y = np.full(len(tr), np.nan)
    for k, (j, a, b) in enumerate(tr):
        if b < 0 or not (np.isfinite(px[a, j]) and np.isfinite(px[b, j]) and px[a, j] > 0):
            continue
        y[k] = float(np.log(px[b, j] / px[a, j]) - cost > 0)
    return y


def _back(px: np.ndarray, t: int, j: int, lb: int) -> float:
    if t - lb < 0 or not (np.isfinite(px[t, j]) and np.isfinite(px[t - lb, j]) and px[t - lb, j] > 0):
        return np.nan
    return float(px[t, j] / px[t - lb, j] - 1)


def _gap(px: np.ndarray, t: int, j: int, m: int) -> float:
    if t + 1 < m:
        return np.nan
    w = px[t + 1 - m: t + 1, j]
    w = w[np.isfinite(w)]
    return float(px[t, j] / w.mean() - 1) if len(w) >= m // 2 and w.mean() > 0 else np.nan


def _vol(px: np.ndarray, t: int, j: int, n: int = 60) -> float:
    if t < n:
        return np.nan
    w = px[t - n: t + 1, j]
    with np.errstate(all="ignore"):
        r = np.diff(np.log(w))
    r = r[np.isfinite(r)]
    return float(r.std() * np.sqrt(365)) if len(r) >= n // 2 else np.nan


def features(px: np.ndarray, W: np.ndarray, tr: list[tuple[int, int, int]], btc: int) -> np.ndarray:
    """(trades, FEATURES) from prices and weights up to each trade's t_in only."""
    X = np.full((len(tr), len(FEATURES)), np.nan)
    last_close: dict[int, int] = {}
    closes = sorted((b, j) for j, _, b in tr if b >= 0)
    ci = 0
    for k, (j, a, _) in enumerate(tr):
        while ci < len(closes) and closes[ci][0] <= a:
            last_close[closes[ci][1]] = closes[ci][0]
            ci += 1
        X[k] = [_back(px, a, j, 7), _back(px, a, j, 28), _back(px, a, j, 90), _vol(px, a, j), _gap(px, a, j, 100),
                _gap(px, a, j, 200), _back(px, a, btc, 28), _gap(px, a, btc, 200), float((W[a] > 1e-12).sum()),
                float(W[a, j]), float(a - last_close[j]) if j in last_close else np.nan]
    return X


def known_at(tr: list[tuple[int, int, int]], T: int) -> np.ndarray:
    """The row index at whose close each trade's label is known (T for one still open: never inside the data)."""
    return np.array([b if b >= 0 else T for _, _, b in tr], dtype=float)


def filtered(W: np.ndarray, tr: list[tuple[int, int, int]], p: np.ndarray, cut: float = CUT) -> np.ndarray:
    """W with every trade whose probability is under `cut` left out (weight 0 from t_in to its close). A trade
    without a probability (no model yet) is kept."""
    W2 = W.copy()
    for (j, a, b), pk in zip(tr, p):
        if np.isfinite(pk) and pk < cut:
            W2[a: (b if b >= 0 else len(W)), j] = 0.0
    return W2
