"""Candlestick pattern library on hand-built bars. No lab data.

Every pattern has a fixture: 25 trending bars (each with range 2, so the
yardstick A is exactly 2 and a downtrend or uptrend is in place), then the
pattern's bars. With A = 2: doji body <= 0.2, short <= 0.6, long >= 1.4,
tiny shadow <= 0.1, short shadow <= 0.2, long shadow >= 1.0, near <= 0.1.

Run from research/lab:  python -m pytest tests/test_candles.py
"""

from __future__ import annotations

import numpy as np
import pytest

from lab import candles
from lab.candles import patterns as cp
from lab.candles.derived import at_support


def prefix(kind: str, n: int = 25) -> list[tuple[float, float, float, float]]:
    """n bars with range 2: falling black bars ending at a close of 101, or rising white ones ending at 99."""
    out = []
    for i in range(n):
        if kind == "down":
            o = 150 - 2 * i
            c = o - 1
            out.append((o, o + 0.5, c - 0.5, c))
        else:
            o = 50 + 2 * i
            c = o + 1
            out.append((o, c + 0.5, o - 0.5, c))
    return out


def arrays(bars):
    a = np.array(bars, dtype=float)
    return a[:, 0], a[:, 1], a[:, 2], a[:, 3]


def run(kind: str, tail, names=None):
    o, h, l, c = arrays(prefix(kind) + list(tail))
    return candles.detect(o, h, l, c, names)


# (o, h, l, c) per bar, oldest first; the pattern must fire on the last bar.
FIXTURES = {
    # one bar
    "doji": ("down", [(100, 101, 99, 100.05)]),
    "long_legged_doji": ("down", [(100, 101.2, 98.8, 100.05)]),
    "rickshaw_man": ("down", [(100, 101.2, 98.8, 100.05)]),
    "dragonfly_doji": ("down", [(100, 100.05, 98.5, 100.02)]),
    "gravestone_doji": ("down", [(100, 101.5, 99.97, 100.02)]),
    "four_price_doji": ("down", [(100, 100.05, 99.98, 100.01)]),
    "takuri": ("down", [(100, 100.05, 97.9, 100.02)]),
    "hammer": ("down", [(100, 100.6, 98.5, 100.5)]),
    "hanging_man": ("up", [(99, 99.6, 97.5, 99.5)]),
    "inverted_hammer": ("down", [(100, 101.7, 99.9, 100.5)]),
    "shooting_star": ("up", [(99, 100.7, 98.9, 99.5)]),
    "marubozu_white": ("down", [(100, 101.55, 99.97, 101.5)]),
    "marubozu_black": ("down", [(101.5, 101.53, 99.95, 100)]),
    "closing_marubozu_white": ("down", [(100, 101.55, 99.5, 101.5)]),
    "closing_marubozu_black": ("down", [(101.5, 102, 99.95, 100)]),
    "belt_hold_bull": ("down", [(100, 102, 99.95, 101.6)]),
    "belt_hold_bear": ("up", [(99, 99.05, 97, 97.4)]),
    "long_white": ("down", [(100, 102, 99.5, 101.6)]),
    "long_black": ("down", [(101.6, 102, 99.5, 100)]),
    "spinning_top": ("down", [(100, 101, 99.2, 100.4)]),
    "high_wave": ("down", [(100, 101.5, 98.5, 100.4)]),
    # two bars
    "engulfing_bull": ("down", [(101, 101.3, 99.8, 100), (99.98, 101.6, 99.7, 101.4)]),
    "engulfing_bear": ("up", [(99, 100.2, 98.9, 100), (100.02, 100.3, 98.4, 98.6)]),
    "harami_bull": ("down", [(101, 101.2, 98.8, 99), (99.5, 100.3, 99.3, 100)]),
    "harami_bear": ("up", [(99, 101.2, 98.8, 101), (100.5, 100.7, 99.8, 100)]),
    "harami_cross_bull": ("down", [(101, 101.2, 98.8, 99), (99.9, 100.3, 99.6, 100)]),
    "harami_cross_bear": ("up", [(99, 101.2, 98.8, 101), (100.05, 100.4, 99.8, 100)]),
    "piercing": ("down", [(101, 101.2, 98.8, 99), (98.95, 100.6, 98.7, 100.5)]),
    "dark_cloud_cover": ("up", [(99, 101.2, 98.8, 101), (101.05, 101.3, 99.4, 99.5)]),
    "tweezer_bottom": ("down", [(101, 101.2, 99, 99.5), (99.5, 100.6, 99.05, 100.4)]),
    "tweezer_top": ("up", [(99, 101, 98.8, 100.5), (100.5, 101.05, 99.6, 99.8)]),
    "kicker_bull": ("down", [(101, 101.05, 99, 99.05), (101.5, 103.2, 101.45, 103.1)]),
    "kicker_bear": ("up", [(99, 101.05, 98.95, 101), (98.5, 98.55, 96.8, 96.9)]),
    "counterattack_bull": ("down", [(101, 101.2, 98.8, 99), (97, 99.1, 96.9, 99.02)]),
    "counterattack_bear": ("up", [(99, 101.2, 98.8, 101), (103, 103.1, 100.9, 101.02)]),
    "homing_pigeon": ("down", [(101, 101.2, 98.8, 99), (100.5, 100.7, 99.3, 99.5)]),
    "descending_hawk": ("up", [(99, 101.2, 98.8, 101), (99.5, 100.7, 99.3, 100.5)]),
    "matching_low": ("down", [(101, 101.2, 98.8, 99), (99.8, 100, 98.9, 99.05)]),
    "matching_high": ("up", [(99, 101.2, 98.8, 101), (100.2, 101.1, 100, 101.05)]),
    "on_neck": ("down", [(101, 101.2, 98.8, 99), (98, 98.85, 97.9, 98.8)]),
    "in_neck": ("down", [(101, 101.2, 98.8, 99), (98, 99.1, 97.9, 99.05)]),
    "thrusting": ("down", [(101, 101.2, 98.8, 99), (98, 99.8, 97.9, 99.6)]),
    "separating_lines_bull": ("up", [(101, 101.1, 99.8, 100), (101.02, 102.8, 100.98, 102.6)]),
    "separating_lines_bear": ("down", [(99, 100.2, 98.9, 100), (99.02, 99.05, 97.3, 97.5)]),
    "doji_star_bull": ("down", [(101, 101.2, 98.8, 99), (98.9, 99.2, 98.6, 98.95)]),
    "doji_star_bear": ("up", [(99, 101.2, 98.8, 101), (101.05, 101.4, 100.8, 101.1)]),
    # three bars
    "morning_star": ("down", [(101, 101.2, 98.8, 99), (98.9, 99.2, 98.3, 98.6), (98.7, 100.5, 98.6, 100.3)]),
    "evening_star": ("up", [(99, 101.2, 98.8, 101), (101.1, 101.7, 100.8, 101.4), (101.3, 101.4, 99.5, 99.7)]),
    "morning_doji_star": ("down", [(101, 101.2, 98.8, 99), (98.9, 99.2, 98.5, 98.85), (98.7, 100.5, 98.6, 100.3)]),
    "evening_doji_star": ("up", [(99, 101.2, 98.8, 101), (101.1, 101.5, 100.8, 101.15),
                                 (101.3, 101.4, 99.5, 99.7)]),
    "abandoned_baby_bull": ("down", [(101, 101.2, 98.8, 99), (98.2, 98.5, 97.9, 98.22),
                                     (98.8, 100.5, 98.7, 100.3)]),
    "abandoned_baby_bear": ("up", [(99, 101.2, 98.8, 101), (101.8, 102.1, 101.5, 101.82),
                                   (101.2, 101.3, 99.5, 99.7)]),
    "three_white_soldiers": ("down", [(100, 101.05, 99.8, 101), (100.8, 101.85, 100.6, 101.8),
                                      (101.6, 102.65, 101.4, 102.6)]),
    "three_black_crows": ("up", [(100, 100.2, 98.95, 99), (99.2, 99.4, 98.15, 98.2), (98.4, 98.6, 97.35, 97.4)]),
    "identical_three_crows": ("up", [(100, 100.2, 98.95, 99), (99.02, 99.2, 97.97, 98.0),
                                     (98.02, 98.2, 96.97, 97.0)]),
    "three_inside_up": ("down", [(101, 101.2, 98.8, 99), (99.5, 100.3, 99.3, 100), (100, 101.6, 99.9, 101.5)]),
    "three_inside_down": ("up", [(99, 101.2, 98.8, 101), (100.5, 100.7, 99.8, 100), (100, 100.1, 98.4, 98.5)]),
    "three_outside_up": ("down", [(101, 101.3, 99.8, 100), (99.98, 101.6, 99.7, 101.4),
                                  (101.4, 102.3, 101.2, 102.1)]),
    "three_outside_down": ("up", [(99, 100.2, 98.9, 100), (100.02, 100.3, 98.4, 98.6), (98.6, 98.7, 97.6, 97.8)]),
    "upside_tasuki_gap": ("up", [(99, 100.6, 98.9, 100.5), (101.2, 102.6, 101.1, 102.5),
                                 (102, 102.1, 100.7, 100.8)]),
    "downside_tasuki_gap": ("down", [(101, 101.1, 99.4, 99.5), (98.8, 98.9, 97.3, 97.4), (98, 99.1, 97.9, 99)]),
    "stick_sandwich": ("down", [(101, 101.1, 99.4, 99.5), (99.7, 100.8, 99.6, 100.6),
                                (100.6, 100.7, 99.4, 99.52)]),
    "unique_three_river": ("down", [(101, 101.2, 98.8, 99), (100.5, 100.6, 98.5, 99.3), (98.7, 99.2, 98.6, 99.1)]),
    "tri_star_bull": ("down", [(100, 100.3, 99.7, 100.05), (99.3, 99.5, 99.1, 99.32), (99.8, 100.1, 99.6, 99.85)]),
    "tri_star_bear": ("up", [(100, 100.3, 99.7, 100.05), (100.7, 100.9, 100.5, 100.72),
                             (100.1, 100.4, 99.9, 100.15)]),
    "two_crows": ("up", [(99, 101.2, 98.8, 101), (101.8, 102, 101.3, 101.4), (101.6, 101.7, 99.6, 99.8)]),
    "upside_gap_two_crows": ("up", [(99, 101.2, 98.8, 101), (101.8, 102, 101.3, 101.5),
                                    (102, 102.1, 101.1, 101.2)]),
    "advance_block": ("up", [(99, 100.7, 98.9, 100.6), (100.4, 101.8, 100.3, 101.5), (101.3, 102.3, 101.2, 101.9)]),
    "deliberation": ("up", [(99, 100.7, 98.9, 100.6), (100.5, 102.2, 100.4, 102.1), (102.1, 102.7, 102, 102.5)]),
    # four and five bars
    "three_line_strike_bull": ("up", [(99, 100.1, 98.9, 100), (100, 101.1, 99.9, 101), (101, 102.1, 100.9, 102),
                                      (102.05, 102.2, 98.7, 98.9)]),
    "three_line_strike_bear": ("down", [(101, 101.1, 99.9, 100), (100, 100.1, 98.9, 99), (99, 99.1, 97.9, 98),
                                        (97.95, 101.2, 97.8, 101.1)]),
    "rising_three_methods": ("up", [(99, 101.2, 98.8, 101), (100.9, 101.1, 100.4, 100.6),
                                    (100.6, 100.8, 100.1, 100.3), (100.3, 100.5, 99.8, 100.0),
                                    (99.98, 101.9, 99.9, 101.8)]),
    "falling_three_methods": ("down", [(101, 101.1, 98.8, 99), (99.1, 99.6, 98.9, 99.4), (99.4, 99.9, 99.2, 99.7),
                                       (99.7, 100.2, 99.5, 100.0), (100.02, 100.1, 97.9, 98.0)]),
    "ladder_bottom": ("down", [(101, 101.1, 99.9, 100), (100.5, 100.6, 99.2, 99.3), (99.8, 99.9, 98.4, 98.5),
                               (98.6, 99.6, 97.9, 98.0), (98.8, 100.1, 98.7, 100.0)]),
}


def test_registry_is_large_and_every_pattern_has_a_fixture():
    assert len(candles.PATTERNS) >= 50
    assert set(FIXTURES) == set(candles.PATTERNS)
    for p in candles.PATTERNS.values():
        assert p.doc, p.name
        assert p.direction in (-1, 0, 1)
        assert 1 <= p.bars <= 5
    by_bars = {k: sum(p.bars == k for p in candles.PATTERNS.values()) for k in (1, 2, 3)}
    assert min(by_bars.values()) >= 15


@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_pattern_fires_on_its_fixture(name):
    kind, tail = FIXTURES[name]
    hits = run(kind, tail)
    assert hits[name][-1], f"{name} did not fire on its own fixture"
    # Nothing fires on the trending prefix before the pattern starts, except long lines and
    # the patterns the prefix itself forms.
    assert not hits[name][: candles.DEFAULT.avg_n].any()


def test_directions_match_the_names():
    for n, p in candles.PATTERNS.items():
        if n.endswith("_bull") or n in ("hammer", "inverted_hammer", "piercing", "morning_star", "takuri"):
            assert p.direction == 1, n
        if n.endswith("_bear") or n in ("hanging_man", "shooting_star", "dark_cloud_cover", "evening_star"):
            assert p.direction == -1, n


def test_trend_decides_hammer_against_hanging_man():
    bar = [(100, 100.6, 98.5, 100.5)]
    down = run("down", bar, ["hammer", "hanging_man"])
    up = run("up", [(99, 99.6, 97.5, 99.5)], ["hammer", "hanging_man"])
    assert down["hammer"][-1] and not down["hanging_man"][-1]
    assert up["hanging_man"][-1] and not up["hammer"][-1]


@pytest.mark.parametrize("name,kind,tail", [
    ("doji", "down", [(100, 101, 99, 100.3)]),                                   # body 0.3 > 0.2
    ("hammer", "down", [(100, 100.9, 98.5, 100.5)]),                             # upper shadow 0.4 > 0.2
    ("hammer", "down", [(100, 100.6, 99.5, 100.5)]),                             # lower shadow 0.5 < 1.0
    ("engulfing_bull", "down", [(101, 101.3, 99.8, 100), (99.98, 101.6, 99.7, 100.9)]),   # closes below the open
    ("engulfing_bull", "down", [(101, 101.3, 99.8, 100), (100.3, 101.6, 99.7, 101.4)]),   # opens above close + near
    ("harami_bull", "down", [(101, 101.2, 98.8, 99.8), (99.5, 100.3, 99.3, 100)]),        # first body 1.2, not long
    ("piercing", "down", [(101, 101.2, 98.8, 99), (98.95, 100, 98.7, 99.9)]),             # below the midpoint
    ("morning_star", "down", [(101, 101.2, 98.8, 99), (98.9, 99.2, 98.3, 98.6),
                              (98.7, 99.7, 98.6, 99.5)]),                                  # not 0.3 into the body
    ("three_white_soldiers", "down", [(100, 101.5, 99.8, 101), (100.8, 101.85, 100.6, 101.8),
                                      (101.6, 102.65, 101.4, 102.6)]),                    # long upper shadow
    ("kicker_bull", "down", [(101, 101.05, 99, 99.05), (99.05, 101.2, 99, 101.1)]),       # no gap
    ("tweezer_bottom", "down", [(101, 101.2, 99, 99.5), (99.5, 100.6, 99.2, 100.4)]),     # lows 0.2 apart
    ("abandoned_baby_bull", "down", [(101, 101.2, 98.8, 99), (98.2, 98.9, 97.9, 98.22),
                                     (98.8, 100.5, 98.7, 100.3)]),                         # doji high inside bar 1
])
def test_near_misses_do_not_fire(name, kind, tail):
    assert not run(kind, tail, [name])[name][-1]


def test_reversal_needs_its_trend():
    kind, tail = FIXTURES["engulfing_bull"]
    assert not run("up", tail, ["engulfing_bull"])["engulfing_bull"][-1]
    kind, tail = FIXTURES["morning_star"]
    assert not run("up", tail, ["morning_star"])["morning_star"][-1]


def test_nan_and_impossible_bars_never_fire():
    kind, tail = FIXTURES["engulfing_bull"]
    bars = prefix(kind) + tail
    o, h, l, c = arrays(bars)
    o2 = o.copy()
    o2[-2] = np.nan
    assert not candles.detect(o2, h, l, c, ["engulfing_bull"])["engulfing_bull"][-1]
    h2 = h.copy()
    h2[-1] = c[-1] - 1                                       # high below the close: not a bar
    assert not candles.detect(o, h2, l, c, ["engulfing_bull"])["engulfing_bull"][-1]


def test_panel_equals_columns_and_chunks():
    rng = np.random.default_rng(3)
    T, N = 300, 7
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.02, (T, N)), 0))
    o = np.r_[c[:1], c[:-1]] * np.exp(rng.normal(0, 0.003, (T, N)))
    h = np.maximum(o, c) * np.exp(np.abs(rng.normal(0, 0.01, (T, N))))
    l = np.minimum(o, c) * np.exp(-np.abs(rng.normal(0, 0.01, (T, N))))
    o[50, 2] = np.nan
    full = candles.detect(o, h, l, c)
    chunked = candles.detect_chunked(o, h, l, c, chunk=3)
    for j in range(N):
        one = candles.detect(o[:, j], h[:, j], l[:, j], c[:, j])
        for n in candles.NAMES:
            np.testing.assert_array_equal(full[n][:, j], one[n], err_msg=n)
            np.testing.assert_array_equal(chunked[n][:, j], one[n], err_msg=n)
    fired = sum(int(full[n].sum()) for n in candles.NAMES)
    assert fired > 0


def test_no_lookahead():
    """A pattern at bar t never changes when later bars change."""
    rng = np.random.default_rng(11)
    T = 400
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.02, T)))
    o = np.r_[c[0], c[:-1]]
    h = np.maximum(o, c) * 1.01
    l = np.minimum(o, c) * 0.99
    a = candles.signals(o, h, l, c, v=np.abs(rng.normal(1, 0.3, T)))
    cut = 250
    b = candles.signals(o[:cut], h[:cut], l[:cut], c[:cut], v=np.abs(rng.normal(1, 0.3, T))[:cut])
    for n in candles.NAMES:
        np.testing.assert_array_equal(a[n][:cut], b[n], err_msg=n)


def test_counts_and_confluence():
    kind, tail = FIXTURES["three_outside_up"]
    o, h, l, c = arrays(prefix(kind) + tail)
    s = candles.signals(o, h, l, c)
    bull = sum(s[n][-1] for n in candles.BULLISH)
    assert s["bull_count"][-1] == bull >= 1
    assert s["net"][-1] == s["bull_count"][-1] - s["bear_count"][-1]
    # The engulfing bar inside it: engulfing_bull and long_white end on the same bar.
    assert s["engulfing_bull"][-2] and s["long_white"][-2]
    assert s["bull_count"][-2] >= 2
    assert s["bull_confluence"][-2] == (s["bear_count"][-2] == 0)


def test_support_resistance_and_volume():
    kind, tail = FIXTURES["hammer"]
    bars = prefix(kind) + tail
    o, h, l, c = arrays(bars)
    v = np.ones(len(bars))
    s = candles.signals(o, h, l, c, v=v)
    # The prefix falls all the way: the hammer's low (98.5) is the lowest of the last 20 bars.
    assert s["hammer"][-1] and s["bull_at_support"][-1]
    assert not s["bull_volume"][-1]
    v[-1] = 2.0
    s = candles.signals(o, h, l, c, v=v)
    assert s["bull_volume"][-1]
    # A hammer far above the window's low is not at support.
    assert at_support(cp.Ctx(o, h, l, c), 1)[-1]
    l2 = l.copy()
    l2[-21:-1] -= 30                                         # a long lower wick on every window bar
    assert not at_support(cp.Ctx(o, h, l2, c), 1)[-1]


def test_bearish_at_resistance():
    kind, tail = FIXTURES["shooting_star"]
    o, h, l, c = arrays(prefix(kind) + tail)
    s = candles.signals(o, h, l, c)
    assert s["shooting_star"][-1] and s["bear_at_resistance"][-1]


def test_shape_features():
    o, h, l, c = arrays(prefix("down") + [(100, 101, 99, 100.5)])
    f = candles.shape_features(o, h, l, c)
    assert f["c_body"][-1] == pytest.approx(0.25)
    assert f["c_upper"][-1] == pytest.approx(0.25)
    assert f["c_lower"][-1] == pytest.approx(0.5)
    assert f["c_close_pos"][-1] == pytest.approx(0.75)


def test_describe_lists_every_pattern():
    rows = candles.describe()
    assert len(rows) == len(candles.PATTERNS)
    assert {r["direction"] for r in rows} == {"bullish", "bearish", "neutral"}
