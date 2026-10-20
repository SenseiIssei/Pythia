"""Signals built from the patterns: confluence, support and resistance, volume.

All of them are known at the close of the pattern's last bar, like the patterns.

  bull_count / bear_count   how many distinct bullish (bearish) patterns end on the bar
  net                       bull_count - bear_count
  bull_confluence           at least two bullish patterns end on the bar and no bearish one
  bear_confluence           the mirror
  bull_at_support           a bullish pattern whose lowest low lies within sr_near x A of
                            (or below) the lowest low of the sr_n bars before the pattern:
                            the lower Donchian bound
  bear_at_resistance        a bearish pattern whose highest high lies within sr_near x A of
                            (or above) the upper Donchian bound of the sr_n bars before it
  bull_volume / bear_volume a bullish (bearish) pattern whose last bar trades at least
                            vol_mult x the mean volume of the vol_n bars before that bar

Overlapping definitions (a dragonfly doji after a decline is also a hammer) count
once each in the counts; the counts are of named patterns, not of distinct ideas.
"""

from __future__ import annotations

import numpy as np

from .patterns import BEARISH, BULLISH, DEFAULT, PATTERNS, Ctx, Params, _lag, rolling_extreme, rolling_mean

DERIVED = ("bull_confluence", "bear_confluence", "bull_at_support", "bear_at_resistance", "bull_volume",
           "bear_volume")
DERIVED_DIRECTION = {"bull_confluence": 1, "bear_confluence": -1, "bull_at_support": 1, "bear_at_resistance": -1,
                     "bull_volume": 1, "bear_volume": -1}


def _pattern_extreme(X: Ctx, n: int, how: str) -> np.ndarray:
    """Lowest low (or highest high) over the pattern's n bars."""
    src = X.base["l"] if how == "min" else X.base["h"]
    return rolling_extreme(src, n, how)


def _donchian_before(X: Ctx, n: int, how: str) -> np.ndarray:
    """The Donchian bound of the sr_n bars before an n-bar pattern's first bar."""
    src = X.base["l"] if how == "min" else X.base["h"]
    return _lag(rolling_extreme(src, X.p.sr_n, how), n)


def at_support(X: Ctx, n: int) -> np.ndarray:
    lo = _pattern_extreme(X, n, "min")
    return lo <= _donchian_before(X, n, "min") + X.p.sr_near * X.A(n)


def at_resistance(X: Ctx, n: int) -> np.ndarray:
    hi = _pattern_extreme(X, n, "max")
    return hi >= _donchian_before(X, n, "max") - X.p.sr_near * X.A(n)


def volume_confirmed(X: Ctx) -> np.ndarray:
    """The bar's volume at least vol_mult x the mean of the vol_n bars before it."""
    if X.v is None:
        return np.zeros(X.shape, dtype=bool)
    avg = _lag(rolling_mean(X.v, X.p.vol_n), 1)
    return X.v >= X.p.vol_mult * avg


def derived(X: Ctx, hits: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    """Counts and the six derived signals from the pattern hits on the same bars."""
    z = np.zeros(X.shape, dtype=np.int16)
    bull = z.copy()
    bear = z.copy()
    sup = np.zeros(X.shape, dtype=bool)
    res = np.zeros(X.shape, dtype=bool)
    sr_cache: dict = {}
    for name, m in hits.items():
        p = PATTERNS.get(name)
        if p is None or p.direction == 0:
            continue
        if p.direction > 0:
            bull += m
            if (n := p.bars) not in sr_cache:
                sr_cache[n] = (at_support(X, n), at_resistance(X, n))
            sup |= m & sr_cache[n][0]
        else:
            bear += m
            if (n := p.bars) not in sr_cache:
                sr_cache[n] = (at_support(X, n), at_resistance(X, n))
            res |= m & sr_cache[n][1]
    vol = volume_confirmed(X)
    return {"bull_count": bull, "bear_count": bear, "net": bull.astype(np.int16) - bear,
            "bull_confluence": (bull >= 2) & (bear == 0), "bear_confluence": (bear >= 2) & (bull == 0),
            "bull_at_support": sup, "bear_at_resistance": res,
            "bull_volume": (bull > 0) & vol, "bear_volume": (bear > 0) & vol}


def signals(o, h, l, c, v=None, params: Params = DEFAULT) -> dict[str, np.ndarray]:
    """Every pattern plus the counts and derived signals, on one set of bars."""
    X = Ctx(o, h, l, c, v, params)
    hits = {n: p.fn(X) for n, p in PATTERNS.items()}
    return {**hits, **derived(X, hits)}


def shape_features(o, h, l, c, params: Params = DEFAULT) -> dict[str, np.ndarray]:
    """Continuous candle shape of each bar on the bar-before yardstick A (1-bar A):
    signed body (close - open) / A, upper and lower shadow / A, and the close's place
    in the bar's range (0 at the low, 1 at the high)."""
    X = Ctx(o, h, l, c, None, params)
    A = X.A(1)
    with np.errstate(invalid="ignore", divide="ignore"):
        return {"c_body": (X.c(0) - X.o(0)) / A, "c_upper": X.upper(0) / A, "c_lower": X.lower(0) / A,
                "c_close_pos": np.where(X.rng(0) > 0, (X.c(0) - X.l(0)) / X.rng(0), 0.5)}


__all__ = ["DERIVED", "DERIVED_DIRECTION", "at_resistance", "at_support", "derived", "shape_features", "signals",
           "volume_confirmed", "BULLISH", "BEARISH"]
