"""Classic candlestick patterns, vectorised with numpy, no TA-Lib.

Every pattern is a function of a `Ctx` (the bars plus the measures derived
from them) and returns a boolean array of the bars' shape that is True on the
LAST bar of the pattern: the bar at whose close the pattern is complete. The
earliest it can be acted on is the next bar's open.

Bars are float arrays of shape (T,) or (T, N), time on axis 0. A NaN anywhere
a pattern looks means "no pattern" (every comparison with NaN is False, and no
definition negates a comparison).

Conventions. Bar 0 is the pattern's last bar, bar 1 the one before, and so on.

  body = |close - open|, top = max(open, close), bot = min(open, close)
  upper shadow = high - top, lower shadow = bot - low, range = high - low
  white: close > open; black: close < open; mid = (open + close) / 2
  A      the mean range of the `avg_n` bars BEFORE the pattern's first bar
         (bars n .. n + avg_n - 1 of an n-bar pattern), one yardstick for every
         size inside the pattern that the pattern itself cannot move
  doji   body <= doji * A          short body  body <= short * A
  long   body >= long * A          tiny shadow <= tiny * A
  short shadow <= shadow_short * A long shadow >= shadow_long * A
  near   two prices are equal when |a - b| <= near * A
  "at or below x" is <= x + near * A, "at or above x" is >= x - near * A,
  "inside [lo, hi]" is between lo - near * A and hi + near * A. The tolerance
         is what lets a 24/7 market (whose next open is the last close) show
         the classic shapes at all; it is the same for every market.
  window (a true gap): up when low > previous high, down when high < previous
         low, no tolerance. Patterns that need one (kicker, abandoned baby,
         tasuki gap, neck lines, ladder bottom, two crows) hardly ever fire on
         crypto; that is a property of the market, not of the code.
  trend  downtrend before the pattern: the close of the bar before its first
         bar is below that bar's `trend_n`-bar simple moving average; uptrend:
         above. Reversal patterns need the trend they reverse, continuation
         patterns the trend they continue; indecision patterns and single long
         lines need none.

Directions: +1 bullish, -1 bearish, 0 neutral (indecision). The registry
`PATTERNS` maps each name to its `Pattern` (bars, direction, kind, function,
definition); `detect` runs any subset on a set of bars.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np

BULL, BEAR, NEUTRAL = 1, -1, 0


@dataclass(frozen=True)
class Params:
    avg_n: int = 10            # bars in the average range A
    trend_n: int = 20          # SMA length for the trend before a pattern
    doji: float = 0.1          # doji: body <= doji * A
    short: float = 0.3         # short body: body <= short * A
    long: float = 0.7          # long body: body >= long * A
    tiny: float = 0.05         # no shadow: shadow <= tiny * A
    shadow_short: float = 0.1  # short shadow: shadow <= shadow_short * A
    shadow_long: float = 0.5   # long shadow: shadow >= shadow_long * A
    shadow_body: float = 2.0   # hammer family: the long shadow >= shadow_body * body
    near: float = 0.05         # equal prices and the tolerance of "at or below"
    penetration: float = 0.3   # stars: the third bar closes this far into the first bar's body
    sr_n: int = 20             # Donchian window for support and resistance
    sr_near: float = 0.5       # "at support": the pattern's low within sr_near * A of the window low
    vol_n: int = 20            # volume average window
    vol_mult: float = 1.5      # volume confirmation: the last bar's volume >= vol_mult x the average


DEFAULT = Params()


def _lag(x: np.ndarray, k: int) -> np.ndarray:
    if k == 0:
        return x
    out = np.full_like(x, np.nan)
    if k < x.shape[0]:
        out[k:] = x[:-k]
    return out


def rolling_mean(x: np.ndarray, n: int) -> np.ndarray:
    """Trailing mean over n rows including row t; NaN unless all n values are finite."""
    fin = np.isfinite(x)
    v = np.where(fin, x, 0.0)
    cs = np.cumsum(v, axis=0)
    cc = np.cumsum(fin, axis=0)
    s = cs.copy()
    c = cc.copy()
    s[n:] = cs[n:] - cs[:-n]
    c[n:] = cc[n:] - cc[:-n]
    out = np.where(c == n, s / n, np.nan)
    out[: n - 1] = np.nan
    return out


def rolling_extreme(x: np.ndarray, n: int, how: str) -> np.ndarray:
    """Trailing max or min over n rows including row t; NaN unless all n values are finite."""
    T = x.shape[0]
    out = np.full_like(x, np.nan)
    if T < n:
        return out
    from numpy.lib.stride_tricks import sliding_window_view
    w = sliding_window_view(x, n, axis=0)          # (T - n + 1, ..., n)
    f = np.max if how == "max" else np.min
    with np.errstate(invalid="ignore"):
        out[n - 1:] = f(w, axis=-1)                  # NaN propagates: an incomplete window is NaN
    return out


class Ctx:
    """The bars and every lagged measure a pattern asks for, computed once."""

    def __init__(self, o, h, l, c, v=None, params: Params = DEFAULT):
        self.p = params
        o, h, l, c = (np.asarray(a, dtype=float) for a in (o, h, l, c))
        bad = ~(np.isfinite(o) & np.isfinite(h) & np.isfinite(l) & np.isfinite(c))
        bad |= (h < np.maximum(o, c)) | (l > np.minimum(o, c))     # an impossible bar is no bar
        o, h, l, c = (np.where(bad, np.nan, a) for a in (o, h, l, c))
        top, bot = np.maximum(o, c), np.minimum(o, c)
        self.base = {"o": o, "h": h, "l": l, "c": c, "body": np.abs(c - o), "top": top, "bot": bot,
                     "upper": h - top, "lower": bot - l, "rng": h - l, "mid": (o + c) / 2}
        self.v = None if v is None else np.asarray(v, dtype=float)
        self.shape = o.shape
        self._avg = rolling_mean(self.base["rng"], params.avg_n)
        sma = rolling_mean(c, params.trend_n)
        with np.errstate(invalid="ignore"):
            self._trend = np.where(np.isfinite(sma) & np.isfinite(c), np.sign(c - sma), np.nan)
        self._cache: dict = {}

    def _get(self, key: str, k: int) -> np.ndarray:
        ck = (key, k)
        if ck not in self._cache:
            src = self.base[key] if key in self.base else {"avg": self._avg, "trend": self._trend}[key]
            self._cache[ck] = _lag(src, k)
        return self._cache[ck]

    def o(self, k): return self._get("o", k)
    def h(self, k): return self._get("h", k)
    def l(self, k): return self._get("l", k)
    def c(self, k): return self._get("c", k)
    def body(self, k): return self._get("body", k)
    def top(self, k): return self._get("top", k)
    def bot(self, k): return self._get("bot", k)
    def upper(self, k): return self._get("upper", k)
    def lower(self, k): return self._get("lower", k)
    def rng(self, k): return self._get("rng", k)
    def mid(self, k): return self._get("mid", k)

    def white(self, k): return self.c(k) > self.o(k)
    def black(self, k): return self.c(k) < self.o(k)

    def A(self, n: int) -> np.ndarray:
        """The yardstick of an n-bar pattern: the mean range of the avg_n bars before bar n-1."""
        return self._get("avg", n)

    def down(self, n: int) -> np.ndarray:
        """Downtrend before an n-bar pattern (judged at bar n)."""
        return self._get("trend", n) < 0

    def up(self, n: int) -> np.ndarray:
        return self._get("trend", n) > 0


@dataclass(frozen=True)
class Pattern:
    name: str
    bars: int
    direction: int
    kind: str          # "reversal", "continuation", "indecision", "strength"
    fn: Callable[[Ctx], np.ndarray]
    doc: str


PATTERNS: dict[str, Pattern] = {}


def pattern(name: str, bars: int, direction: int, kind: str):
    def deco(fn):
        PATTERNS[name] = Pattern(name, bars, direction, kind, fn, " ".join((fn.__doc__ or "").split()))
        return fn
    return deco


# --------------------------------------------------------------------------- shared shapes

def _doji(X: Ctx, k: int, A) -> np.ndarray:
    return X.body(k) <= X.p.doji * A


def _short(X: Ctx, k: int, A) -> np.ndarray:
    return X.body(k) <= X.p.short * A


def _small(X: Ctx, k: int, A) -> np.ndarray:
    """Short but not a doji."""
    return (X.body(k) > X.p.doji * A) & (X.body(k) <= X.p.short * A)


def _long(X: Ctx, k: int, A) -> np.ndarray:
    return X.body(k) >= X.p.long * A


def _real(X: Ctx, k: int, A) -> np.ndarray:
    """Not a short body."""
    return X.body(k) > X.p.short * A


def _near(X: Ctx, a, b, A) -> np.ndarray:
    return np.abs(a - b) <= X.p.near * A


def _at_or_below(X: Ctx, a, b, A) -> np.ndarray:
    return a <= b + X.p.near * A


def _at_or_above(X: Ctx, a, b, A) -> np.ndarray:
    return a >= b - X.p.near * A


def _inside(X: Ctx, x, lo, hi, A) -> np.ndarray:
    return (x >= lo - X.p.near * A) & (x <= hi + X.p.near * A)


def _body_inside(X: Ctx, k: int, j: int, A) -> np.ndarray:
    """Bar k's body inside bar j's body."""
    return (X.top(k) <= X.top(j) + X.p.near * A) & (X.bot(k) >= X.bot(j) - X.p.near * A)


def _hammer_shape(X: Ctx, A) -> np.ndarray:
    b, lo, up = X.body(0), X.lower(0), X.upper(0)
    return (_short(X, 0, A) & (lo >= X.p.shadow_body * b) & (lo >= X.p.shadow_long * A)
            & (up <= X.p.shadow_short * A))


def _inverted_shape(X: Ctx, A) -> np.ndarray:
    b, lo, up = X.body(0), X.lower(0), X.upper(0)
    return (_short(X, 0, A) & (up >= X.p.shadow_body * b) & (up >= X.p.shadow_long * A)
            & (lo <= X.p.shadow_short * A))


# --------------------------------------------------------------------------- one bar

@pattern("doji", 1, NEUTRAL, "indecision")
def doji(X):
    """Body at most doji x A."""
    return _doji(X, 0, X.A(1))


@pattern("long_legged_doji", 1, NEUTRAL, "indecision")
def long_legged_doji(X):
    """A doji with both shadows long (each at least shadow_long x A)."""
    A = X.A(1)
    return _doji(X, 0, A) & (X.upper(0) >= X.p.shadow_long * A) & (X.lower(0) >= X.p.shadow_long * A)


@pattern("rickshaw_man", 1, NEUTRAL, "indecision")
def rickshaw_man(X):
    """A long-legged doji whose body sits in the middle of the range (within 10 % of the range of its centre)."""
    centre = (X.h(0) + X.l(0)) / 2
    return long_legged_doji(X) & (np.abs(X.mid(0) - centre) <= 0.1 * X.rng(0))


@pattern("dragonfly_doji", 1, BULL, "reversal")
def dragonfly_doji(X):
    """A doji with no upper shadow (tiny) and a long lower shadow."""
    A = X.A(1)
    return _doji(X, 0, A) & (X.upper(0) <= X.p.tiny * A) & (X.lower(0) >= X.p.shadow_long * A)


@pattern("gravestone_doji", 1, BEAR, "reversal")
def gravestone_doji(X):
    """A doji with no lower shadow (tiny) and a long upper shadow."""
    A = X.A(1)
    return _doji(X, 0, A) & (X.lower(0) <= X.p.tiny * A) & (X.upper(0) >= X.p.shadow_long * A)


@pattern("four_price_doji", 1, NEUTRAL, "indecision")
def four_price_doji(X):
    """Open, high, low and close all but equal: the whole range at most tiny x A."""
    return X.rng(0) <= X.p.tiny * X.A(1)


@pattern("takuri", 1, BULL, "reversal")
def takuri(X):
    """A dragonfly doji whose lower shadow is at least one full A."""
    A = X.A(1)
    return _doji(X, 0, A) & (X.upper(0) <= X.p.tiny * A) & (X.lower(0) >= A)


@pattern("hammer", 1, BULL, "reversal")
def hammer(X):
    """After a downtrend: short body, lower shadow at least shadow_body x the body and at least shadow_long x A, upper shadow short."""
    return X.down(1) & _hammer_shape(X, X.A(1))


@pattern("hanging_man", 1, BEAR, "reversal")
def hanging_man(X):
    """The hammer's shape after an uptrend."""
    return X.up(1) & _hammer_shape(X, X.A(1))


@pattern("inverted_hammer", 1, BULL, "reversal")
def inverted_hammer(X):
    """After a downtrend: short body, upper shadow at least shadow_body x the body and at least shadow_long x A, lower shadow short."""
    return X.down(1) & _inverted_shape(X, X.A(1))


@pattern("shooting_star", 1, BEAR, "reversal")
def shooting_star(X):
    """The inverted hammer's shape after an uptrend."""
    return X.up(1) & _inverted_shape(X, X.A(1))


@pattern("marubozu_white", 1, BULL, "strength")
def marubozu_white(X):
    """Long white body, both shadows tiny."""
    A = X.A(1)
    return X.white(0) & _long(X, 0, A) & (X.upper(0) <= X.p.tiny * A) & (X.lower(0) <= X.p.tiny * A)


@pattern("marubozu_black", 1, BEAR, "strength")
def marubozu_black(X):
    """Long black body, both shadows tiny."""
    A = X.A(1)
    return X.black(0) & _long(X, 0, A) & (X.upper(0) <= X.p.tiny * A) & (X.lower(0) <= X.p.tiny * A)


@pattern("closing_marubozu_white", 1, BULL, "strength")
def closing_marubozu_white(X):
    """Long white body closing at the high (upper shadow tiny) with a lower shadow that is not tiny."""
    A = X.A(1)
    return X.white(0) & _long(X, 0, A) & (X.upper(0) <= X.p.tiny * A) & (X.lower(0) > X.p.tiny * A)


@pattern("closing_marubozu_black", 1, BEAR, "strength")
def closing_marubozu_black(X):
    """Long black body closing at the low (lower shadow tiny) with an upper shadow that is not tiny."""
    A = X.A(1)
    return X.black(0) & _long(X, 0, A) & (X.lower(0) <= X.p.tiny * A) & (X.upper(0) > X.p.tiny * A)


@pattern("belt_hold_bull", 1, BULL, "reversal")
def belt_hold_bull(X):
    """After a downtrend: a long white body opening at the low (lower shadow tiny)."""
    A = X.A(1)
    return X.down(1) & X.white(0) & _long(X, 0, A) & (X.lower(0) <= X.p.tiny * A)


@pattern("belt_hold_bear", 1, BEAR, "reversal")
def belt_hold_bear(X):
    """After an uptrend: a long black body opening at the high (upper shadow tiny)."""
    A = X.A(1)
    return X.up(1) & X.black(0) & _long(X, 0, A) & (X.upper(0) <= X.p.tiny * A)


@pattern("long_white", 1, BULL, "strength")
def long_white(X):
    """A long white body (long line)."""
    return X.white(0) & _long(X, 0, X.A(1))


@pattern("long_black", 1, BEAR, "strength")
def long_black(X):
    """A long black body (long line)."""
    return X.black(0) & _long(X, 0, X.A(1))


@pattern("spinning_top", 1, NEUTRAL, "indecision")
def spinning_top(X):
    """A short body that is not a doji, each shadow longer than the body."""
    A = X.A(1)
    return _small(X, 0, A) & (X.upper(0) > X.body(0)) & (X.lower(0) > X.body(0))


@pattern("high_wave", 1, NEUTRAL, "indecision")
def high_wave(X):
    """A short body that is not a doji with both shadows long."""
    A = X.A(1)
    return _small(X, 0, A) & (X.upper(0) >= X.p.shadow_long * A) & (X.lower(0) >= X.p.shadow_long * A)


# --------------------------------------------------------------------------- two bars

@pattern("engulfing_bull", 2, BULL, "reversal")
def engulfing_bull(X):
    """After a downtrend: a black bar, then a white bar opening at or below its close and closing above its open."""
    A = X.A(2)
    return (X.down(2) & X.black(1) & X.white(0) & _at_or_below(X, X.o(0), X.c(1), A) & (X.c(0) > X.o(1)))


@pattern("engulfing_bear", 2, BEAR, "reversal")
def engulfing_bear(X):
    """After an uptrend: a white bar, then a black bar opening at or above its close and closing below its open."""
    A = X.A(2)
    return (X.up(2) & X.white(1) & X.black(0) & _at_or_above(X, X.o(0), X.c(1), A) & (X.c(0) < X.o(1)))


@pattern("harami_bull", 2, BULL, "reversal")
def harami_bull(X):
    """After a downtrend: a long black bar, then a short body (not a doji, any colour) inside its body."""
    A = X.A(2)
    return X.down(2) & X.black(1) & _long(X, 1, A) & _small(X, 0, A) & _body_inside(X, 0, 1, A)


@pattern("harami_bear", 2, BEAR, "reversal")
def harami_bear(X):
    """After an uptrend: a long white bar, then a short body (not a doji, any colour) inside its body."""
    A = X.A(2)
    return X.up(2) & X.white(1) & _long(X, 1, A) & _small(X, 0, A) & _body_inside(X, 0, 1, A)


@pattern("harami_cross_bull", 2, BULL, "reversal")
def harami_cross_bull(X):
    """After a downtrend: a long black bar, then a doji inside its body."""
    A = X.A(2)
    return X.down(2) & X.black(1) & _long(X, 1, A) & _doji(X, 0, A) & _body_inside(X, 0, 1, A)


@pattern("harami_cross_bear", 2, BEAR, "reversal")
def harami_cross_bear(X):
    """After an uptrend: a long white bar, then a doji inside its body."""
    A = X.A(2)
    return X.up(2) & X.white(1) & _long(X, 1, A) & _doji(X, 0, A) & _body_inside(X, 0, 1, A)


@pattern("piercing", 2, BULL, "reversal")
def piercing(X):
    """After a downtrend: a long black bar, then a white bar opening at or below its close and closing above the middle of its body but below its open."""
    A = X.A(2)
    return (X.down(2) & X.black(1) & _long(X, 1, A) & X.white(0) & _at_or_below(X, X.o(0), X.c(1), A)
            & (X.c(0) > X.mid(1)) & (X.c(0) < X.o(1)))


@pattern("dark_cloud_cover", 2, BEAR, "reversal")
def dark_cloud_cover(X):
    """After an uptrend: a long white bar, then a black bar opening at or above its close and closing below the middle of its body but above its open."""
    A = X.A(2)
    return (X.up(2) & X.white(1) & _long(X, 1, A) & X.black(0) & _at_or_above(X, X.o(0), X.c(1), A)
            & (X.c(0) < X.mid(1)) & (X.c(0) > X.o(1)))


@pattern("tweezer_bottom", 2, BULL, "reversal")
def tweezer_bottom(X):
    """After a downtrend: a black bar, then a white bar with the same low (near)."""
    A = X.A(2)
    return X.down(2) & X.black(1) & X.white(0) & _near(X, X.l(0), X.l(1), A)


@pattern("tweezer_top", 2, BEAR, "reversal")
def tweezer_top(X):
    """After an uptrend: a white bar, then a black bar with the same high (near)."""
    A = X.A(2)
    return X.up(2) & X.white(1) & X.black(0) & _near(X, X.h(0), X.h(1), A)


@pattern("kicker_bull", 2, BULL, "reversal")
def kicker_bull(X):
    """A long black bar, then a long white bar opening above its open (a gap past the whole body). No trend needed."""
    A = X.A(2)
    return X.black(1) & _long(X, 1, A) & X.white(0) & _long(X, 0, A) & (X.o(0) > X.o(1))


@pattern("kicker_bear", 2, BEAR, "reversal")
def kicker_bear(X):
    """A long white bar, then a long black bar opening below its open. No trend needed."""
    A = X.A(2)
    return X.white(1) & _long(X, 1, A) & X.black(0) & _long(X, 0, A) & (X.o(0) < X.o(1))


@pattern("counterattack_bull", 2, BULL, "reversal")
def counterattack_bull(X):
    """After a downtrend: a long black bar, then a long white bar closing at its close (near); the white bar must have opened far lower."""
    A = X.A(2)
    return (X.down(2) & X.black(1) & _long(X, 1, A) & X.white(0) & _long(X, 0, A) & _near(X, X.c(0), X.c(1), A))


@pattern("counterattack_bear", 2, BEAR, "reversal")
def counterattack_bear(X):
    """After an uptrend: a long white bar, then a long black bar closing at its close (near)."""
    A = X.A(2)
    return (X.up(2) & X.white(1) & _long(X, 1, A) & X.black(0) & _long(X, 0, A) & _near(X, X.c(0), X.c(1), A))


@pattern("homing_pigeon", 2, BULL, "reversal")
def homing_pigeon(X):
    """After a downtrend: a long black bar, then a smaller black body inside its body."""
    A = X.A(2)
    return (X.down(2) & X.black(1) & _long(X, 1, A) & X.black(0) & (X.body(0) < X.body(1))
            & _body_inside(X, 0, 1, A))


@pattern("descending_hawk", 2, BEAR, "reversal")
def descending_hawk(X):
    """After an uptrend: a long white bar, then a smaller white body inside its body."""
    A = X.A(2)
    return (X.up(2) & X.white(1) & _long(X, 1, A) & X.white(0) & (X.body(0) < X.body(1))
            & _body_inside(X, 0, 1, A))


@pattern("matching_low", 2, BULL, "reversal")
def matching_low(X):
    """After a downtrend: a long black bar, then a black bar closing at its close (near)."""
    A = X.A(2)
    return X.down(2) & X.black(1) & _long(X, 1, A) & X.black(0) & _near(X, X.c(0), X.c(1), A)


@pattern("matching_high", 2, BEAR, "reversal")
def matching_high(X):
    """After an uptrend: a long white bar, then a white bar closing at its close (near)."""
    A = X.A(2)
    return X.up(2) & X.white(1) & _long(X, 1, A) & X.white(0) & _near(X, X.c(0), X.c(1), A)


@pattern("on_neck", 2, BEAR, "continuation")
def on_neck(X):
    """In a downtrend: a long black bar, then a white bar opening below its low and closing at its low (near)."""
    A = X.A(2)
    return (X.down(2) & X.black(1) & _long(X, 1, A) & X.white(0) & (X.o(0) < X.l(1))
            & _near(X, X.c(0), X.l(1), A))


@pattern("in_neck", 2, BEAR, "continuation")
def in_neck(X):
    """In a downtrend: a long black bar, then a white bar opening below its low and closing just above its close (by at most near x A)."""
    A = X.A(2)
    return (X.down(2) & X.black(1) & _long(X, 1, A) & X.white(0) & (X.o(0) < X.l(1)) & (X.c(0) > X.c(1))
            & (X.c(0) <= X.c(1) + X.p.near * A))


@pattern("thrusting", 2, BEAR, "continuation")
def thrusting(X):
    """In a downtrend: a long black bar, then a white bar opening below its low and closing into its body, but not above the middle."""
    A = X.A(2)
    return (X.down(2) & X.black(1) & _long(X, 1, A) & X.white(0) & (X.o(0) < X.l(1))
            & (X.c(0) > X.c(1) + X.p.near * A) & (X.c(0) <= X.mid(1)))


@pattern("separating_lines_bull", 2, BULL, "continuation")
def separating_lines_bull(X):
    """In an uptrend: a black bar, then a long white bar opening at its open (near) with no lower shadow."""
    A = X.A(2)
    return (X.up(2) & X.black(1) & X.white(0) & _long(X, 0, A) & _near(X, X.o(0), X.o(1), A)
            & (X.lower(0) <= X.p.tiny * A))


@pattern("separating_lines_bear", 2, BEAR, "continuation")
def separating_lines_bear(X):
    """In a downtrend: a white bar, then a long black bar opening at its open (near) with no upper shadow."""
    A = X.A(2)
    return (X.down(2) & X.white(1) & X.black(0) & _long(X, 0, A) & _near(X, X.o(0), X.o(1), A)
            & (X.upper(0) <= X.p.tiny * A))


@pattern("doji_star_bull", 2, BULL, "reversal")
def doji_star_bull(X):
    """After a downtrend: a long black bar, then a doji at or below its close."""
    A = X.A(2)
    return (X.down(2) & X.black(1) & _long(X, 1, A) & _doji(X, 0, A) & _at_or_below(X, X.top(0), X.c(1), A))


@pattern("doji_star_bear", 2, BEAR, "reversal")
def doji_star_bear(X):
    """After an uptrend: a long white bar, then a doji at or above its close."""
    A = X.A(2)
    return (X.up(2) & X.white(1) & _long(X, 1, A) & _doji(X, 0, A) & _at_or_above(X, X.bot(0), X.c(1), A))


# --------------------------------------------------------------------------- three bars

def _star_bull(X: Ctx, A, star) -> np.ndarray:
    return (X.down(3) & X.black(2) & _long(X, 2, A) & star & _at_or_below(X, X.top(1), X.c(2), A)
            & X.white(0) & (X.c(0) > X.c(2) + X.p.penetration * X.body(2)))


def _star_bear(X: Ctx, A, star) -> np.ndarray:
    return (X.up(3) & X.white(2) & _long(X, 2, A) & star & _at_or_above(X, X.bot(1), X.c(2), A)
            & X.black(0) & (X.c(0) < X.c(2) - X.p.penetration * X.body(2)))


@pattern("morning_star", 3, BULL, "reversal")
def morning_star(X):
    """After a downtrend: a long black bar, a short body at or below its close, then a white bar closing more than penetration x the first body above the first close."""
    A = X.A(3)
    return _star_bull(X, A, _short(X, 1, A))


@pattern("evening_star", 3, BEAR, "reversal")
def evening_star(X):
    """After an uptrend: a long white bar, a short body at or above its close, then a black bar closing more than penetration x the first body below the first close."""
    A = X.A(3)
    return _star_bear(X, A, _short(X, 1, A))


@pattern("morning_doji_star", 3, BULL, "reversal")
def morning_doji_star(X):
    """A morning star whose middle bar is a doji."""
    A = X.A(3)
    return _star_bull(X, A, _doji(X, 1, A))


@pattern("evening_doji_star", 3, BEAR, "reversal")
def evening_doji_star(X):
    """An evening star whose middle bar is a doji."""
    A = X.A(3)
    return _star_bear(X, A, _doji(X, 1, A))


@pattern("abandoned_baby_bull", 3, BULL, "reversal")
def abandoned_baby_bull(X):
    """After a downtrend: a long black bar, a doji whose whole range gaps below it (window), then a white bar whose range gaps above the doji and closes penetration x into the first body."""
    A = X.A(3)
    return (X.down(3) & X.black(2) & _long(X, 2, A) & _doji(X, 1, A) & (X.h(1) < X.l(2)) & X.white(0)
            & (X.l(0) > X.h(1)) & (X.c(0) > X.c(2) + X.p.penetration * X.body(2)))


@pattern("abandoned_baby_bear", 3, BEAR, "reversal")
def abandoned_baby_bear(X):
    """After an uptrend: a long white bar, a doji whose range gaps above it, then a black bar whose range gaps below the doji and closes penetration x into the first body."""
    A = X.A(3)
    return (X.up(3) & X.white(2) & _long(X, 2, A) & _doji(X, 1, A) & (X.l(1) > X.h(2)) & X.black(0)
            & (X.h(0) < X.l(1)) & (X.c(0) < X.c(2) - X.p.penetration * X.body(2)))


@pattern("three_white_soldiers", 3, BULL, "reversal")
def three_white_soldiers(X):
    """After a downtrend: three white bars, none short, each closing higher, each opening inside the previous body, each with a short upper shadow."""
    A = X.A(3)
    m = X.down(3) & (X.c(0) > X.c(1)) & (X.c(1) > X.c(2))
    for k in (0, 1, 2):
        m = m & X.white(k) & _real(X, k, A) & (X.upper(k) <= X.p.shadow_short * A)
    return m & _inside(X, X.o(1), X.o(2), X.c(2), A) & _inside(X, X.o(0), X.o(1), X.c(1), A)


@pattern("three_black_crows", 3, BEAR, "reversal")
def three_black_crows(X):
    """After an uptrend: three black bars, none short, each closing lower, each opening inside the previous body, each with a short lower shadow."""
    A = X.A(3)
    m = X.up(3) & (X.c(0) < X.c(1)) & (X.c(1) < X.c(2))
    for k in (0, 1, 2):
        m = m & X.black(k) & _real(X, k, A) & (X.lower(k) <= X.p.shadow_short * A)
    return m & _inside(X, X.o(1), X.c(2), X.o(2), A) & _inside(X, X.o(0), X.c(1), X.o(1), A)


@pattern("identical_three_crows", 3, BEAR, "reversal")
def identical_three_crows(X):
    """Three black crows where each bar opens at the previous close (near)."""
    A = X.A(3)
    return three_black_crows(X) & _near(X, X.o(1), X.c(2), A) & _near(X, X.o(0), X.c(1), A)


@pattern("three_inside_up", 3, BULL, "reversal")
def three_inside_up(X):
    """After a downtrend: a long black bar, a short body inside it, then a white bar closing above the first open."""
    A = X.A(3)
    return (X.down(3) & X.black(2) & _long(X, 2, A) & _short(X, 1, A) & _body_inside(X, 1, 2, A) & X.white(0)
            & (X.c(0) > X.o(2)))


@pattern("three_inside_down", 3, BEAR, "reversal")
def three_inside_down(X):
    """After an uptrend: a long white bar, a short body inside it, then a black bar closing below the first open."""
    A = X.A(3)
    return (X.up(3) & X.white(2) & _long(X, 2, A) & _short(X, 1, A) & _body_inside(X, 1, 2, A) & X.black(0)
            & (X.c(0) < X.o(2)))


@pattern("three_outside_up", 3, BULL, "reversal")
def three_outside_up(X):
    """After a downtrend: a bullish engulfing pair, then a white bar closing higher."""
    A = X.A(3)
    return (X.down(3) & X.black(2) & X.white(1) & _at_or_below(X, X.o(1), X.c(2), A) & (X.c(1) > X.o(2))
            & X.white(0) & (X.c(0) > X.c(1)))


@pattern("three_outside_down", 3, BEAR, "reversal")
def three_outside_down(X):
    """After an uptrend: a bearish engulfing pair, then a black bar closing lower."""
    A = X.A(3)
    return (X.up(3) & X.white(2) & X.black(1) & _at_or_above(X, X.o(1), X.c(2), A) & (X.c(1) < X.o(2))
            & X.black(0) & (X.c(0) < X.c(1)))


@pattern("upside_tasuki_gap", 3, BULL, "continuation")
def upside_tasuki_gap(X):
    """In an uptrend: a white bar, a white bar above a window, then a black bar opening inside the second body and closing inside the window."""
    return (X.up(3) & X.white(2) & X.white(1) & (X.l(1) > X.h(2)) & X.black(0) & (X.o(0) > X.o(1))
            & (X.o(0) < X.c(1)) & (X.c(0) < X.o(1)) & (X.c(0) > X.h(2)))


@pattern("downside_tasuki_gap", 3, BEAR, "continuation")
def downside_tasuki_gap(X):
    """In a downtrend: a black bar, a black bar below a window, then a white bar opening inside the second body and closing inside the window."""
    return (X.down(3) & X.black(2) & X.black(1) & (X.h(1) < X.l(2)) & X.white(0) & (X.o(0) < X.o(1))
            & (X.o(0) > X.c(1)) & (X.c(0) > X.o(1)) & (X.c(0) < X.l(2)))


@pattern("stick_sandwich", 3, BULL, "reversal")
def stick_sandwich(X):
    """After a downtrend: a black bar, a white bar trading wholly above its close (low above it), then a black bar closing at the first close (near)."""
    A = X.A(3)
    return (X.down(3) & X.black(2) & X.white(1) & (X.l(1) > X.c(2)) & X.black(0) & _near(X, X.c(0), X.c(2), A))


@pattern("unique_three_river", 3, BULL, "reversal")
def unique_three_river(X):
    """After a downtrend: a long black bar; a black bar opening no higher, closing higher and making a lower low; then a short white bar opening above that low and closing below the second close."""
    A = X.A(3)
    return (X.down(3) & X.black(2) & _long(X, 2, A) & X.black(1) & (X.c(1) > X.c(2)) & (X.o(1) <= X.o(2))
            & (X.l(1) < X.l(2)) & X.white(0) & _short(X, 0, A) & (X.c(0) < X.c(1)) & (X.o(0) > X.l(1)))


@pattern("tri_star_bull", 3, BULL, "reversal")
def tri_star_bull(X):
    """After a downtrend: three dojis, the middle one's body strictly below the other two."""
    A = X.A(3)
    return (X.down(3) & _doji(X, 2, A) & _doji(X, 1, A) & _doji(X, 0, A) & (X.top(1) < X.bot(2))
            & (X.top(1) < X.bot(0)))


@pattern("tri_star_bear", 3, BEAR, "reversal")
def tri_star_bear(X):
    """After an uptrend: three dojis, the middle one's body strictly above the other two."""
    A = X.A(3)
    return (X.up(3) & _doji(X, 2, A) & _doji(X, 1, A) & _doji(X, 0, A) & (X.bot(1) > X.top(2))
            & (X.bot(1) > X.top(0)))


@pattern("two_crows", 3, BEAR, "reversal")
def two_crows(X):
    """After an uptrend: a long white bar, a black body strictly above it, then a black bar opening inside the second body and closing inside the first."""
    A = X.A(3)
    return (X.up(3) & X.white(2) & _long(X, 2, A) & X.black(1) & (X.bot(1) > X.top(2)) & X.black(0)
            & (X.o(0) < X.o(1)) & (X.o(0) > X.c(1)) & (X.c(0) > X.o(2)) & (X.c(0) < X.c(2)))


@pattern("upside_gap_two_crows", 3, BEAR, "reversal")
def upside_gap_two_crows(X):
    """After an uptrend: a long white bar, a black body strictly above it, then a black bar engulfing the second body that still closes above the first close."""
    A = X.A(3)
    return (X.up(3) & X.white(2) & _long(X, 2, A) & X.black(1) & (X.bot(1) > X.top(2)) & X.black(0)
            & (X.o(0) > X.o(1)) & (X.c(0) < X.c(1)) & (X.c(0) > X.c(2)))


@pattern("advance_block", 3, BEAR, "reversal")
def advance_block(X):
    """After an uptrend: three white bars closing higher, each opening inside the previous body, the first long, the bodies shrinking and the second or third with an upper shadow that is not short."""
    A = X.A(3)
    return (X.up(3) & X.white(2) & X.white(1) & X.white(0) & (X.c(0) > X.c(1)) & (X.c(1) > X.c(2))
            & _inside(X, X.o(1), X.o(2), X.c(2), A) & _inside(X, X.o(0), X.o(1), X.c(1), A) & _long(X, 2, A)
            & (X.body(0) < X.body(1)) & (X.body(1) < X.body(2))
            & ((X.upper(0) > X.p.shadow_short * A) | (X.upper(1) > X.p.shadow_short * A)))


@pattern("deliberation", 3, BEAR, "reversal")
def deliberation(X):
    """After an uptrend: two long white bars closing higher, the second opening inside the first body, then a short white bar opening at or above the second close and closing higher still (a stalled advance)."""
    A = X.A(3)
    return (X.up(3) & X.white(2) & X.white(1) & X.white(0) & _long(X, 2, A) & _long(X, 1, A) & _short(X, 0, A)
            & (X.c(1) > X.c(2)) & (X.c(0) > X.c(1)) & _inside(X, X.o(1), X.o(2), X.c(2), A)
            & _at_or_above(X, X.o(0), X.c(1), A))


# --------------------------------------------------------------------------- four and five bars

@pattern("three_line_strike_bull", 4, BULL, "continuation")
def three_line_strike_bull(X):
    """In an uptrend: three white bars with rising closes, then a black bar opening at or above the third close and closing below the first open."""
    A = X.A(4)
    return (X.up(4) & X.white(3) & X.white(2) & X.white(1) & (X.c(2) > X.c(3)) & (X.c(1) > X.c(2))
            & X.black(0) & _at_or_above(X, X.o(0), X.c(1), A) & (X.c(0) < X.o(3)))


@pattern("three_line_strike_bear", 4, BEAR, "continuation")
def three_line_strike_bear(X):
    """In a downtrend: three black bars with falling closes, then a white bar opening at or below the third close and closing above the first open."""
    A = X.A(4)
    return (X.down(4) & X.black(3) & X.black(2) & X.black(1) & (X.c(2) < X.c(3)) & (X.c(1) < X.c(2))
            & X.white(0) & _at_or_below(X, X.o(0), X.c(1), A) & (X.c(0) > X.o(3)))


@pattern("rising_three_methods", 5, BULL, "continuation")
def rising_three_methods(X):
    """In an uptrend: a long white bar; three short bodies with falling closes, each bar's range inside the first bar's range; then a long white bar opening at or above the fourth close and closing above the first close."""
    A = X.A(5)
    m = X.up(5) & X.white(4) & _long(X, 4, A) & (X.c(3) > X.c(2)) & (X.c(2) > X.c(1))
    for k in (3, 2, 1):
        m = m & _short(X, k, A) & (X.h(k) <= X.h(4)) & (X.l(k) >= X.l(4))
    return m & X.white(0) & _long(X, 0, A) & _at_or_above(X, X.o(0), X.c(1), A) & (X.c(0) > X.c(4))


@pattern("falling_three_methods", 5, BEAR, "continuation")
def falling_three_methods(X):
    """In a downtrend: a long black bar; three short bodies with rising closes, each bar's range inside the first bar's range; then a long black bar opening at or below the fourth close and closing below the first close."""
    A = X.A(5)
    m = X.down(5) & X.black(4) & _long(X, 4, A) & (X.c(3) < X.c(2)) & (X.c(2) < X.c(1))
    for k in (3, 2, 1):
        m = m & _short(X, k, A) & (X.h(k) <= X.h(4)) & (X.l(k) >= X.l(4))
    return m & X.black(0) & _long(X, 0, A) & _at_or_below(X, X.o(0), X.c(1), A) & (X.c(0) < X.c(4))


@pattern("ladder_bottom", 5, BULL, "reversal")
def ladder_bottom(X):
    """After a downtrend: three black bars with lower opens and lower closes; a black bar with an upper shadow longer than its body; then a white bar opening above that body (a gap) and closing above its high."""
    m = X.down(5) & X.black(4) & X.black(3) & X.black(2)
    m = m & (X.o(3) < X.o(4)) & (X.o(2) < X.o(3)) & (X.c(3) < X.c(4)) & (X.c(2) < X.c(3))
    return m & X.black(1) & (X.upper(1) > X.body(1)) & X.white(0) & (X.o(0) > X.o(1)) & (X.c(0) > X.h(1))


# --------------------------------------------------------------------------- running them

NAMES = tuple(PATTERNS)
BULLISH = tuple(n for n, p in PATTERNS.items() if p.direction == BULL)
BEARISH = tuple(n for n, p in PATTERNS.items() if p.direction == BEAR)
NEUTRALS = tuple(n for n, p in PATTERNS.items() if p.direction == NEUTRAL)


def detect(o, h, l, c, names=None, params: Params = DEFAULT, v=None) -> dict[str, np.ndarray]:
    """{name: bool array} for the named patterns (all by default) on one set of bars."""
    X = Ctx(o, h, l, c, v, params)
    return {n: PATTERNS[n].fn(X) for n in (names or NAMES)}


def detect_chunked(o, h, l, c, names=None, params: Params = DEFAULT, chunk: int = 128) -> dict[str, np.ndarray]:
    """detect on a (T, N) panel, a block of columns at a time (bounded memory for big panels)."""
    o = np.asarray(o, dtype=float)
    if o.ndim == 1 or o.shape[1] <= chunk:
        return detect(o, h, l, c, names, params)
    names = names or NAMES
    out = {n: np.zeros(o.shape, dtype=bool) for n in names}
    for j in range(0, o.shape[1], chunk):
        s = slice(j, j + chunk)
        part = detect(o[:, s], np.asarray(h)[:, s], np.asarray(l)[:, s], np.asarray(c)[:, s], names, params)
        for n in names:
            out[n][:, s] = part[n]
    return out


def describe() -> list[dict]:
    """The registry as rows (name, bars, direction, kind, definition), for reports."""
    word = {BULL: "bullish", BEAR: "bearish", NEUTRAL: "neutral"}
    return [{"name": p.name, "bars": p.bars, "direction": word[p.direction], "kind": p.kind, "definition": p.doc}
            for p in PATTERNS.values()]
