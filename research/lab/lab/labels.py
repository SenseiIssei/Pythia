"""Triple-barrier labels (Lopez de Prado, AFML ch. 3).

An event enters at the close of bar i. It exits at whichever comes first:
  upper barrier  close_i * exp(+up * sigma * sqrt(horizon))
  lower barrier  close_i * exp(-dn * sigma * sqrt(horizon))
  time limit     close of bar i + horizon
sigma is the per-bar volatility known at entry. When one bar touches both
barriers we cannot tell the order from hourly highs and lows, so the loss is
assumed first. That makes every result here slightly pessimistic, on purpose.
"""

from __future__ import annotations

import numpy as np


def triple_barrier(close: np.ndarray, high: np.ndarray, low: np.ndarray, entries: np.ndarray,
                   sigma: np.ndarray, up: float, dn: float, horizon: int, cost: float):
    """Returns (exit_idx, net log return, which barrier: 1 upper, -1 lower, 0 time)."""
    n = len(close)
    exit_idx = np.empty(len(entries), dtype=np.int64)
    ret = np.empty(len(entries))
    hit = np.empty(len(entries), dtype=np.int8)
    for k, i in enumerate(entries):
        p0 = close[i]
        w = sigma[i] * np.sqrt(horizon)
        ub, lb = p0 * np.exp(up * w), p0 * np.exp(-dn * w)
        last = min(i + horizon, n - 1)
        exit_px, j_exit, h = close[last], last, 0
        for j in range(i + 1, last + 1):
            if low[j] <= lb:
                exit_px, j_exit, h = lb, j, -1
                break
            if high[j] >= ub:
                exit_px, j_exit, h = ub, j, 1
                break
        exit_idx[k] = j_exit
        ret[k] = np.log(exit_px / p0) - cost
        hit[k] = h
    return exit_idx, ret, hit


def non_overlapping(signal: np.ndarray, exit_of) -> list[int]:
    """Take signals in order, skipping any that fire while a previous position is open."""
    out, busy_until = [], -1
    for i in np.flatnonzero(signal):
        if i <= busy_until:
            continue
        out.append(int(i))
        busy_until = exit_of(int(i))
    return out
