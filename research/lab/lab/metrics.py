"""Loss functions and tests used by every experiment."""

from __future__ import annotations

import math

import numpy as np
from scipy import stats


def qlike(realised_var: np.ndarray, forecast_var: np.ndarray) -> np.ndarray:
    """Patton's QLIKE, robust to noise in the realised-variance proxy. Lower is better, 0 is perfect."""
    ratio = realised_var / forecast_var
    return ratio - np.log(ratio) - 1.0


def r2(y: np.ndarray, pred: np.ndarray) -> float:
    return float(1.0 - np.mean((y - pred) ** 2) / np.var(y))


def diebold_mariano(loss_a: np.ndarray, loss_b: np.ndarray, lag: int = 24) -> tuple[float, float]:
    """DM test on loss_a - loss_b with a Newey-West variance. Negative stat: A is better.

    Returns (statistic, two-sided p-value).
    """
    d = loss_a - loss_b
    d = d[np.isfinite(d)]
    n = d.size
    dc = d - d.mean()
    var = np.dot(dc, dc) / n
    for k in range(1, lag + 1):
        w = 1.0 - k / (lag + 1)
        var += 2 * w * np.dot(dc[k:], dc[:-k]) / n
    stat = d.mean() / math.sqrt(var / n)
    return float(stat), float(2 * stats.norm.sf(abs(stat)))


def deflated_sharpe(sharpe: float, n_obs: int, n_trials: int, sharpe_var_trials: float,
                    skew: float = 0.0, kurt: float = 3.0) -> float:
    """Bailey and Lopez de Prado. Probability that the true Sharpe is above the best of
    n_trials pure-noise strategies. Sharpe values are per observation, not annualised."""
    if n_trials <= 1:
        sr0 = 0.0
    else:
        g = 0.5772156649
        sr0 = math.sqrt(sharpe_var_trials) * (
            (1 - g) * stats.norm.ppf(1 - 1 / n_trials) + g * stats.norm.ppf(1 - 1 / (n_trials * math.e)))
    denom = math.sqrt(1 - skew * sharpe + (kurt - 1) / 4 * sharpe ** 2)
    return float(stats.norm.cdf((sharpe - sr0) * math.sqrt(n_obs - 1) / denom))
