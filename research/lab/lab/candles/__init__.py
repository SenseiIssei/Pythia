"""Candlestick patterns for the lab: definitions (`patterns`), derived signals
(`derived`). Pure numpy; no TA-Lib, no data access.

    from lab.candles import detect, signals, PATTERNS
"""

from .derived import DERIVED, DERIVED_DIRECTION, derived, shape_features, signals
from .patterns import (BEAR, BEARISH, BULL, BULLISH, DEFAULT, NAMES, NEUTRAL, NEUTRALS, PATTERNS, Ctx, Params,
                       describe, detect, detect_chunked)

__all__ = ["BEAR", "BEARISH", "BULL", "BULLISH", "DEFAULT", "DERIVED", "DERIVED_DIRECTION", "NAMES", "NEUTRAL",
           "NEUTRALS", "PATTERNS", "Ctx", "Params", "derived", "describe", "detect", "detect_chunked",
           "shape_features", "signals"]
