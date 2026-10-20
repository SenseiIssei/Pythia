//! The candle patterns against the research lab: the lab's hand-built
//! fixtures (`research/lab/tests/test_candles.py`), its near misses and trend
//! and missing-bar rules, the parity file the lab writes
//! (`tests/fixtures/candles_parity.json`, see `lab.candles.export_fixture`),
//! and the `candles` strategy kind on top.

use super::candles::{self, CandleCtx, CandleParams, PATTERNS};
use super::strategies::{self, run_strategy, run_strategy_with_candles};
use super::*;
use serde_json::Value;

type Bar = (f64, f64, f64, f64);

/// n bars with range 2: falling black bars ending at a close of 101, or rising
/// white ones ending at 99 (the lab's `prefix`).
fn prefix(kind: &str, n: usize) -> Vec<Bar> {
    (0..n)
        .map(|i| {
            let i = i as f64;
            if kind == "down" {
                let o = 150.0 - 2.0 * i;
                let c = o - 1.0;
                (o, o + 0.5, c - 0.5, c)
            } else {
                let o = 50.0 + 2.0 * i;
                let c = o + 1.0;
                (o, c + 0.5, o - 0.5, c)
            }
        })
        .collect()
}

fn ctx_of(bars: &[Bar], v: Option<&[f64]>) -> CandleCtx {
    let col = |f: fn(&Bar) -> f64| bars.iter().map(f).collect::<Vec<f64>>();
    CandleCtx::new(&col(|b| b.0), &col(|b| b.1), &col(|b| b.2), &col(|b| b.3), v, CandleParams::default())
}

fn bars_of(kind: &str, tail: &[Bar]) -> Vec<Bar> {
    let mut b = prefix(kind, 25);
    b.extend_from_slice(tail);
    b
}

fn run(kind: &str, tail: &[Bar]) -> CandleCtx {
    ctx_of(&bars_of(kind, tail), None)
}

fn fires_last(x: &CandleCtx, name: &str) -> bool {
    x.fires(candles::pattern(name).unwrap_or_else(|| panic!("unknown pattern {name}")), x.len() - 1)
}

/// (o, h, l, c) per bar, oldest first; the pattern must fire on the last bar.
const FIXTURES: &[(&str, &str, &[Bar])] = &[
    // one bar
    ("doji", "down", &[(100.0, 101.0, 99.0, 100.05)]),
    ("long_legged_doji", "down", &[(100.0, 101.2, 98.8, 100.05)]),
    ("rickshaw_man", "down", &[(100.0, 101.2, 98.8, 100.05)]),
    ("dragonfly_doji", "down", &[(100.0, 100.05, 98.5, 100.02)]),
    ("gravestone_doji", "down", &[(100.0, 101.5, 99.97, 100.02)]),
    ("four_price_doji", "down", &[(100.0, 100.05, 99.98, 100.01)]),
    ("takuri", "down", &[(100.0, 100.05, 97.9, 100.02)]),
    ("hammer", "down", &[(100.0, 100.6, 98.5, 100.5)]),
    ("hanging_man", "up", &[(99.0, 99.6, 97.5, 99.5)]),
    ("inverted_hammer", "down", &[(100.0, 101.7, 99.9, 100.5)]),
    ("shooting_star", "up", &[(99.0, 100.7, 98.9, 99.5)]),
    ("marubozu_white", "down", &[(100.0, 101.55, 99.97, 101.5)]),
    ("marubozu_black", "down", &[(101.5, 101.53, 99.95, 100.0)]),
    ("closing_marubozu_white", "down", &[(100.0, 101.55, 99.5, 101.5)]),
    ("closing_marubozu_black", "down", &[(101.5, 102.0, 99.95, 100.0)]),
    ("belt_hold_bull", "down", &[(100.0, 102.0, 99.95, 101.6)]),
    ("belt_hold_bear", "up", &[(99.0, 99.05, 97.0, 97.4)]),
    ("long_white", "down", &[(100.0, 102.0, 99.5, 101.6)]),
    ("long_black", "down", &[(101.6, 102.0, 99.5, 100.0)]),
    ("spinning_top", "down", &[(100.0, 101.0, 99.2, 100.4)]),
    ("high_wave", "down", &[(100.0, 101.5, 98.5, 100.4)]),
    // two bars
    ("engulfing_bull", "down", &[(101.0, 101.3, 99.8, 100.0), (99.98, 101.6, 99.7, 101.4)]),
    ("engulfing_bear", "up", &[(99.0, 100.2, 98.9, 100.0), (100.02, 100.3, 98.4, 98.6)]),
    ("harami_bull", "down", &[(101.0, 101.2, 98.8, 99.0), (99.5, 100.3, 99.3, 100.0)]),
    ("harami_bear", "up", &[(99.0, 101.2, 98.8, 101.0), (100.5, 100.7, 99.8, 100.0)]),
    ("harami_cross_bull", "down", &[(101.0, 101.2, 98.8, 99.0), (99.9, 100.3, 99.6, 100.0)]),
    ("harami_cross_bear", "up", &[(99.0, 101.2, 98.8, 101.0), (100.05, 100.4, 99.8, 100.0)]),
    ("piercing", "down", &[(101.0, 101.2, 98.8, 99.0), (98.95, 100.6, 98.7, 100.5)]),
    ("dark_cloud_cover", "up", &[(99.0, 101.2, 98.8, 101.0), (101.05, 101.3, 99.4, 99.5)]),
    ("tweezer_bottom", "down", &[(101.0, 101.2, 99.0, 99.5), (99.5, 100.6, 99.05, 100.4)]),
    ("tweezer_top", "up", &[(99.0, 101.0, 98.8, 100.5), (100.5, 101.05, 99.6, 99.8)]),
    ("kicker_bull", "down", &[(101.0, 101.05, 99.0, 99.05), (101.5, 103.2, 101.45, 103.1)]),
    ("kicker_bear", "up", &[(99.0, 101.05, 98.95, 101.0), (98.5, 98.55, 96.8, 96.9)]),
    ("counterattack_bull", "down", &[(101.0, 101.2, 98.8, 99.0), (97.0, 99.1, 96.9, 99.02)]),
    ("counterattack_bear", "up", &[(99.0, 101.2, 98.8, 101.0), (103.0, 103.1, 100.9, 101.02)]),
    ("homing_pigeon", "down", &[(101.0, 101.2, 98.8, 99.0), (100.5, 100.7, 99.3, 99.5)]),
    ("descending_hawk", "up", &[(99.0, 101.2, 98.8, 101.0), (99.5, 100.7, 99.3, 100.5)]),
    ("matching_low", "down", &[(101.0, 101.2, 98.8, 99.0), (99.8, 100.0, 98.9, 99.05)]),
    ("matching_high", "up", &[(99.0, 101.2, 98.8, 101.0), (100.2, 101.1, 100.0, 101.05)]),
    ("on_neck", "down", &[(101.0, 101.2, 98.8, 99.0), (98.0, 98.85, 97.9, 98.8)]),
    ("in_neck", "down", &[(101.0, 101.2, 98.8, 99.0), (98.0, 99.1, 97.9, 99.05)]),
    ("thrusting", "down", &[(101.0, 101.2, 98.8, 99.0), (98.0, 99.8, 97.9, 99.6)]),
    ("separating_lines_bull", "up", &[(101.0, 101.1, 99.8, 100.0), (101.02, 102.8, 100.98, 102.6)]),
    ("separating_lines_bear", "down", &[(99.0, 100.2, 98.9, 100.0), (99.02, 99.05, 97.3, 97.5)]),
    ("doji_star_bull", "down", &[(101.0, 101.2, 98.8, 99.0), (98.9, 99.2, 98.6, 98.95)]),
    ("doji_star_bear", "up", &[(99.0, 101.2, 98.8, 101.0), (101.05, 101.4, 100.8, 101.1)]),
    // three bars
    ("morning_star", "down", &[(101.0, 101.2, 98.8, 99.0), (98.9, 99.2, 98.3, 98.6), (98.7, 100.5, 98.6, 100.3)]),
    ("evening_star", "up", &[(99.0, 101.2, 98.8, 101.0), (101.1, 101.7, 100.8, 101.4), (101.3, 101.4, 99.5, 99.7)]),
    ("morning_doji_star", "down", &[(101.0, 101.2, 98.8, 99.0), (98.9, 99.2, 98.5, 98.85), (98.7, 100.5, 98.6, 100.3)]),
    ("evening_doji_star", "up", &[(99.0, 101.2, 98.8, 101.0), (101.1, 101.5, 100.8, 101.15), (101.3, 101.4, 99.5, 99.7)]),
    ("abandoned_baby_bull", "down", &[(101.0, 101.2, 98.8, 99.0), (98.2, 98.5, 97.9, 98.22), (98.8, 100.5, 98.7, 100.3)]),
    ("abandoned_baby_bear", "up", &[(99.0, 101.2, 98.8, 101.0), (101.8, 102.1, 101.5, 101.82), (101.2, 101.3, 99.5, 99.7)]),
    ("three_white_soldiers", "down", &[(100.0, 101.05, 99.8, 101.0), (100.8, 101.85, 100.6, 101.8), (101.6, 102.65, 101.4, 102.6)]),
    ("three_black_crows", "up", &[(100.0, 100.2, 98.95, 99.0), (99.2, 99.4, 98.15, 98.2), (98.4, 98.6, 97.35, 97.4)]),
    ("identical_three_crows", "up", &[(100.0, 100.2, 98.95, 99.0), (99.02, 99.2, 97.97, 98.0), (98.02, 98.2, 96.97, 97.0)]),
    ("three_inside_up", "down", &[(101.0, 101.2, 98.8, 99.0), (99.5, 100.3, 99.3, 100.0), (100.0, 101.6, 99.9, 101.5)]),
    ("three_inside_down", "up", &[(99.0, 101.2, 98.8, 101.0), (100.5, 100.7, 99.8, 100.0), (100.0, 100.1, 98.4, 98.5)]),
    ("three_outside_up", "down", &[(101.0, 101.3, 99.8, 100.0), (99.98, 101.6, 99.7, 101.4), (101.4, 102.3, 101.2, 102.1)]),
    ("three_outside_down", "up", &[(99.0, 100.2, 98.9, 100.0), (100.02, 100.3, 98.4, 98.6), (98.6, 98.7, 97.6, 97.8)]),
    ("upside_tasuki_gap", "up", &[(99.0, 100.6, 98.9, 100.5), (101.2, 102.6, 101.1, 102.5), (102.0, 102.1, 100.7, 100.8)]),
    ("downside_tasuki_gap", "down", &[(101.0, 101.1, 99.4, 99.5), (98.8, 98.9, 97.3, 97.4), (98.0, 99.1, 97.9, 99.0)]),
    ("stick_sandwich", "down", &[(101.0, 101.1, 99.4, 99.5), (99.7, 100.8, 99.6, 100.6), (100.6, 100.7, 99.4, 99.52)]),
    ("unique_three_river", "down", &[(101.0, 101.2, 98.8, 99.0), (100.5, 100.6, 98.5, 99.3), (98.7, 99.2, 98.6, 99.1)]),
    ("tri_star_bull", "down", &[(100.0, 100.3, 99.7, 100.05), (99.3, 99.5, 99.1, 99.32), (99.8, 100.1, 99.6, 99.85)]),
    ("tri_star_bear", "up", &[(100.0, 100.3, 99.7, 100.05), (100.7, 100.9, 100.5, 100.72), (100.1, 100.4, 99.9, 100.15)]),
    ("two_crows", "up", &[(99.0, 101.2, 98.8, 101.0), (101.8, 102.0, 101.3, 101.4), (101.6, 101.7, 99.6, 99.8)]),
    ("upside_gap_two_crows", "up", &[(99.0, 101.2, 98.8, 101.0), (101.8, 102.0, 101.3, 101.5), (102.0, 102.1, 101.1, 101.2)]),
    ("advance_block", "up", &[(99.0, 100.7, 98.9, 100.6), (100.4, 101.8, 100.3, 101.5), (101.3, 102.3, 101.2, 101.9)]),
    ("deliberation", "up", &[(99.0, 100.7, 98.9, 100.6), (100.5, 102.2, 100.4, 102.1), (102.1, 102.7, 102.0, 102.5)]),
    // four and five bars
    ("three_line_strike_bull", "up", &[(99.0, 100.1, 98.9, 100.0), (100.0, 101.1, 99.9, 101.0), (101.0, 102.1, 100.9, 102.0), (102.05, 102.2, 98.7, 98.9)]),
    ("three_line_strike_bear", "down", &[(101.0, 101.1, 99.9, 100.0), (100.0, 100.1, 98.9, 99.0), (99.0, 99.1, 97.9, 98.0), (97.95, 101.2, 97.8, 101.1)]),
    ("rising_three_methods", "up", &[(99.0, 101.2, 98.8, 101.0), (100.9, 101.1, 100.4, 100.6), (100.6, 100.8, 100.1, 100.3), (100.3, 100.5, 99.8, 100.0), (99.98, 101.9, 99.9, 101.8)]),
    ("falling_three_methods", "down", &[(101.0, 101.1, 98.8, 99.0), (99.1, 99.6, 98.9, 99.4), (99.4, 99.9, 99.2, 99.7), (99.7, 100.2, 99.5, 100.0), (100.02, 100.1, 97.9, 98.0)]),
    ("ladder_bottom", "down", &[(101.0, 101.1, 99.9, 100.0), (100.5, 100.6, 99.2, 99.3), (99.8, 99.9, 98.4, 98.5), (98.6, 99.6, 97.9, 98.0), (98.8, 100.1, 98.7, 100.0)]),
];

fn fixture(name: &str) -> (&'static str, &'static [Bar]) {
    let (_, kind, tail) = FIXTURES.iter().find(|f| f.0 == name).unwrap();
    (kind, tail)
}

// ── the registry ───────────────────────────────────────────────────────────

#[test]
fn registry_is_large_and_every_pattern_has_a_fixture() {
    assert_eq!(PATTERNS.len(), 74);
    let mut names: Vec<&str> = PATTERNS.iter().map(|p| p.name).collect();
    names.sort();
    names.dedup();
    assert_eq!(names.len(), PATTERNS.len(), "pattern names are unique");
    let mut fx: Vec<&str> = FIXTURES.iter().map(|f| f.0).collect();
    fx.sort();
    assert_eq!(fx, names, "one fixture per pattern");
    for p in &PATTERNS {
        assert!((1..=5).contains(&p.bars), "{}", p.name);
        assert!([-1, 0, 1].contains(&p.direction), "{}", p.name);
    }
    for k in 1..=3 {
        assert!(PATTERNS.iter().filter(|p| p.bars == k).count() >= 15);
    }
}

#[test]
fn directions_match_the_names() {
    for p in &PATTERNS {
        let n = p.name;
        if n.ends_with("_bull") || ["hammer", "inverted_hammer", "piercing", "morning_star", "takuri"].contains(&n) {
            assert_eq!(p.direction, candles::BULL, "{n}");
        }
        if n.ends_with("_bear") || ["hanging_man", "shooting_star", "dark_cloud_cover", "evening_star"].contains(&n) {
            assert_eq!(p.direction, candles::BEAR, "{n}");
        }
    }
}

// ── the lab's fixtures ─────────────────────────────────────────────────────

#[test]
fn every_pattern_fires_on_its_fixture_and_not_on_the_early_prefix() {
    for (name, kind, tail) in FIXTURES {
        let x = run(kind, tail);
        assert!(fires_last(&x, name), "{name} did not fire on its own fixture");
        let p = candles::pattern(name).unwrap();
        for t in 0..CandleParams::default().avg_n {
            assert!(!x.fires(p, t), "{name} fired at {t}, before the yardstick exists");
        }
    }
}

#[test]
fn trend_decides_hammer_against_hanging_man() {
    let down = run("down", &[(100.0, 100.6, 98.5, 100.5)]);
    let up = run("up", &[(99.0, 99.6, 97.5, 99.5)]);
    assert!(fires_last(&down, "hammer") && !fires_last(&down, "hanging_man"));
    assert!(fires_last(&up, "hanging_man") && !fires_last(&up, "hammer"));
}

#[test]
fn near_misses_do_not_fire() {
    let cases: &[(&str, &str, &[Bar])] = &[
        ("doji", "down", &[(100.0, 101.0, 99.0, 100.3)]), // body 0.3 > 0.2
        ("hammer", "down", &[(100.0, 100.9, 98.5, 100.5)]), // upper shadow 0.4 > 0.2
        ("hammer", "down", &[(100.0, 100.6, 99.5, 100.5)]), // lower shadow 0.5 < 1.0
        ("engulfing_bull", "down", &[(101.0, 101.3, 99.8, 100.0), (99.98, 101.6, 99.7, 100.9)]), // closes below the open
        ("engulfing_bull", "down", &[(101.0, 101.3, 99.8, 100.0), (100.3, 101.6, 99.7, 101.4)]), // opens above close + near
        ("harami_bull", "down", &[(101.0, 101.2, 98.8, 99.8), (99.5, 100.3, 99.3, 100.0)]), // first body 1.2, not long
        ("piercing", "down", &[(101.0, 101.2, 98.8, 99.0), (98.95, 100.0, 98.7, 99.9)]), // below the midpoint
        // not 0.3 into the body
        ("morning_star", "down", &[(101.0, 101.2, 98.8, 99.0), (98.9, 99.2, 98.3, 98.6), (98.7, 99.7, 98.6, 99.5)]),
        // long upper shadow
        ("three_white_soldiers", "down", &[(100.0, 101.5, 99.8, 101.0), (100.8, 101.85, 100.6, 101.8), (101.6, 102.65, 101.4, 102.6)]),
        ("kicker_bull", "down", &[(101.0, 101.05, 99.0, 99.05), (99.05, 101.2, 99.0, 101.1)]), // no gap
        ("tweezer_bottom", "down", &[(101.0, 101.2, 99.0, 99.5), (99.5, 100.6, 99.2, 100.4)]), // lows 0.2 apart
        // doji high inside bar 1
        ("abandoned_baby_bull", "down", &[(101.0, 101.2, 98.8, 99.0), (98.2, 98.9, 97.9, 98.22), (98.8, 100.5, 98.7, 100.3)]),
    ];
    for (name, kind, tail) in cases {
        assert!(!fires_last(&run(kind, tail), name), "{name} fired on a near miss: {tail:?}");
    }
}

#[test]
fn the_tolerance_edges_are_the_labs() {
    // engulfing_bull: the open may sit up to near x A = 0.1 above the prior close.
    let at = run("down", &[(101.0, 101.3, 99.8, 100.0), (100.09, 101.6, 99.7, 101.4)]);
    let past = run("down", &[(101.0, 101.3, 99.8, 100.0), (100.11, 101.6, 99.7, 101.4)]);
    assert!(fires_last(&at, "engulfing_bull"));
    assert!(!fires_last(&past, "engulfing_bull"));
    // A doji's body is at most doji x A = 0.2.
    assert!(fires_last(&run("down", &[(100.0, 101.0, 99.0, 100.19)]), "doji"));
    assert!(!fires_last(&run("down", &[(100.0, 101.0, 99.0, 100.21)]), "doji"));
}

#[test]
fn reversal_needs_its_trend() {
    let (_, tail) = fixture("engulfing_bull");
    assert!(!fires_last(&run("up", tail), "engulfing_bull"));
    let (_, tail) = fixture("morning_star");
    assert!(!fires_last(&run("up", tail), "morning_star"));
}

#[test]
fn nan_and_impossible_bars_never_fire() {
    let (kind, tail) = fixture("engulfing_bull");
    let bars = bars_of(kind, tail);
    let n = bars.len();
    let mut nan = bars.clone();
    nan[n - 2].0 = f64::NAN;
    assert!(!fires_last(&ctx_of(&nan, None), "engulfing_bull"));
    let mut inf = bars.clone();
    inf[n - 1].2 = f64::NEG_INFINITY;
    assert!(!fires_last(&ctx_of(&inf, None), "engulfing_bull"));
    let mut impossible = bars.clone();
    impossible[n - 1].1 = impossible[n - 1].3 - 1.0; // high below the close: not a bar
    assert!(!fires_last(&ctx_of(&impossible, None), "engulfing_bull"));
    let mut low_above = bars.clone();
    low_above[n - 2].2 = low_above[n - 2].0 + 0.1; // low above the open of the black bar
    assert!(!fires_last(&ctx_of(&low_above, None), "engulfing_bull"));
    // A missing bar inside the yardstick window leaves A missing, so nothing fires.
    let mut gap = bars.clone();
    gap[n - 5].3 = f64::NAN;
    let x = ctx_of(&gap, None);
    assert!(x.hits_at(n - 1).is_empty(), "{:?}", x.hits_at(n - 1).iter().map(|p| p.name).collect::<Vec<_>>());
}

#[test]
fn too_few_bars_fire_nothing() {
    let x = ctx_of(&[(100.0, 100.6, 98.5, 100.5)], None);
    assert!(x.hits_at(0).is_empty());
    let empty = ctx_of(&[], None);
    assert!(empty.signals_last().is_none());
}

#[test]
fn no_lookahead() {
    // A pattern at bar t never changes when later bars change or are cut off.
    let mut bars = Vec::new();
    for (_, kind, tail) in FIXTURES.iter().take(30) {
        bars.extend(bars_of(kind, tail));
    }
    let full = ctx_of(&bars, None);
    let cut = 400.min(bars.len());
    let short = ctx_of(&bars[..cut], None);
    for t in 0..cut {
        let a: Vec<&str> = full.hits_at(t).iter().map(|p| p.name).collect();
        let b: Vec<&str> = short.hits_at(t).iter().map(|p| p.name).collect();
        assert_eq!(a, b, "bar {t}");
    }
}

// ── derived signals ────────────────────────────────────────────────────────

#[test]
fn counts_and_confluence() {
    let (kind, tail) = fixture("three_outside_up");
    let x = run(kind, tail);
    let last = x.len() - 1;
    let s = x.signals_at(last);
    let bull = s.hits.iter().filter(|p| p.direction > 0).count() as i32;
    assert!(s.bull_count == bull && bull >= 1);
    assert_eq!(s.net(), s.bull_count - s.bear_count);
    // The engulfing bar inside it: engulfing_bull and long_white end on the same bar.
    let prev = x.signals_at(last - 1);
    assert!(prev.fired("engulfing_bull") && prev.fired("long_white"));
    assert!(prev.bull_count >= 2);
    assert_eq!(prev.bull_confluence, prev.bear_count == 0);
}

#[test]
fn support_resistance_and_volume() {
    let (kind, tail) = fixture("hammer");
    let bars = bars_of(kind, tail);
    let n = bars.len();
    let mut v = vec![1.0; n];
    let s = ctx_of(&bars, Some(&v)).signals_last().unwrap();
    // The prefix falls all the way: the hammer's low (98.5) is the lowest of the last 20 bars.
    assert!(s.fired("hammer") && s.bull_at_support);
    assert!(!s.bull_volume);
    v[n - 1] = 2.0;
    assert!(ctx_of(&bars, Some(&v)).signals_last().unwrap().bull_volume);
    // Without volume there is no volume confirmation.
    assert!(!ctx_of(&bars, None).signals_last().unwrap().bull_volume);
    // A hammer far above the window's low is not at support.
    assert!(ctx_of(&bars, None).at_support(n - 1, 1));
    let mut low = bars.clone();
    for b in &mut low[n - 21..n - 1] {
        b.2 -= 30.0; // a long lower wick on every window bar
    }
    assert!(!ctx_of(&low, None).at_support(n - 1, 1));
}

#[test]
fn bearish_at_resistance() {
    let (kind, tail) = fixture("shooting_star");
    let s = run(kind, tail).signals_last().unwrap();
    assert!(s.fired("shooting_star") && s.bear_at_resistance);
}

// ── parity with the lab ────────────────────────────────────────────────────

const PARITY: &str = include_str!("../../tests/fixtures/candles_parity.json");

fn floats(v: &Value) -> Vec<f64> {
    v.as_array().unwrap().iter().map(|x| x.as_f64().unwrap_or(f64::NAN)).collect()
}

fn indices(v: &Value) -> Vec<usize> {
    v.as_array().unwrap().iter().map(|x| x.as_u64().unwrap() as usize).collect()
}

#[test]
fn parity_with_the_lab_on_every_pattern_and_bar() {
    let doc: Value = serde_json::from_str(PARITY).unwrap();

    // Same defaults and the same registry, in the same order.
    let p = &doc["params"];
    let d = CandleParams::default();
    assert_eq!(p["avg_n"].as_u64(), Some(d.avg_n as u64));
    assert_eq!(p["trend_n"].as_u64(), Some(d.trend_n as u64));
    assert_eq!(p["sr_n"].as_u64(), Some(d.sr_n as u64));
    assert_eq!(p["vol_n"].as_u64(), Some(d.vol_n as u64));
    for (k, v) in [
        ("doji", d.doji), ("short", d.short), ("long", d.long), ("tiny", d.tiny),
        ("shadow_short", d.shadow_short), ("shadow_long", d.shadow_long), ("shadow_body", d.shadow_body),
        ("near", d.near), ("penetration", d.penetration), ("sr_near", d.sr_near), ("vol_mult", d.vol_mult),
    ] {
        assert_eq!(p[k].as_f64(), Some(v), "param {k}");
    }
    let reg = doc["patterns"].as_array().unwrap();
    assert_eq!(reg.len(), PATTERNS.len());
    for (r, p) in reg.iter().zip(PATTERNS.iter()) {
        assert_eq!(r["name"].as_str(), Some(p.name));
        assert_eq!(r["bars"].as_u64(), Some(p.bars as u64), "{}", p.name);
        assert_eq!(r["direction"].as_i64(), Some(p.direction as i64), "{}", p.name);
        assert_eq!(r["kind"].as_str(), Some(p.kind.as_str()), "{}", p.name);
    }

    let mut bars_compared = 0usize;
    let mut fired: std::collections::BTreeSet<&str> = Default::default();
    let mut mismatches = Vec::new();
    for s in doc["series"].as_array().unwrap() {
        let name = s["name"].as_str().unwrap();
        let (o, h, l, c) = (floats(&s["o"]), floats(&s["h"]), floats(&s["l"]), floats(&s["c"]));
        let v = (!s["v"].is_null()).then(|| floats(&s["v"]));
        let x = CandleCtx::new(&o, &h, &l, &c, v.as_deref(), CandleParams::default());
        let n = x.len();
        bars_compared += n;
        let rows: Vec<_> = (0..n).map(|t| x.signals_at(t)).collect();

        for p in &PATTERNS {
            let want = indices(&s["hits"][p.name]);
            let got: Vec<usize> = (0..n).filter(|&t| rows[t].fired(p.name)).collect();
            if !want.is_empty() {
                fired.insert(p.name);
            }
            if want != got {
                mismatches.push(format!("{name} {}: lab {want:?} engine {got:?}", p.name));
            }
        }
        for dname in candles::DERIVED {
            let want = indices(&s["derived"][dname]);
            let got: Vec<usize> = (0..n).filter(|&t| rows[t].derived(dname).unwrap()).collect();
            if want != got {
                mismatches.push(format!("{name} {dname}: lab {want:?} engine {got:?}"));
            }
        }
        let counts: [(&str, fn(&candles::Signals) -> i32); 2] =
            [("bull_count", |r| r.bull_count), ("bear_count", |r| r.bear_count)];
        for (cname, get) in counts {
            let want: Vec<(usize, i32)> = s["counts"][cname]
                .as_array()
                .unwrap()
                .iter()
                .map(|e| (e[0].as_u64().unwrap() as usize, e[1].as_i64().unwrap() as i32))
                .collect();
            let got: Vec<(usize, i32)> = (0..n).filter(|&t| get(&rows[t]) != 0).map(|t| (t, get(&rows[t]))).collect();
            if want != got {
                mismatches.push(format!("{name} {cname}: lab {want:?} engine {got:?}"));
            }
        }
        if let Some(expect) = s.get("expect").and_then(|e| e.as_object()) {
            for (pname, idx) in expect {
                let t = idx.as_u64().unwrap() as usize;
                assert!(rows[t].fired(pname), "{name}: {pname} should fire at {t}");
            }
        }
    }
    assert!(mismatches.is_empty(), "{} mismatches:\n{}", mismatches.len(), mismatches.join("\n"));
    assert!(bars_compared > 5_000, "{bars_compared} bars");
    assert_eq!(fired.len(), PATTERNS.len(), "every pattern fires somewhere in the parity data");
}

// ── the strategy kind ──────────────────────────────────────────────────────

const BTC: &str = "crypto:BTC/USD";

fn ohlc(bars: &[Bar], volume: f64) -> Vec<Ohlc> {
    bars.iter()
        .enumerate()
        .map(|(i, b)| Ohlc { ts: 86_400_000 * i as i64, open: b.0, high: b.1, low: b.2, close: b.3, volume })
        .collect()
}

fn market(id: &str, price: f64) -> Market {
    let mut m = Engine::new().markets.into_iter().find(|m| m.id == id).expect("seeded market");
    m.price = price;
    m
}

/// The default candle strategy, switched on (paper) and pointed at BTC.
fn candle_cfg() -> StrategyConfig {
    let mut cfg = strategies::default_strategies().into_iter().find(|s| s.kind == StrategyKind::Candles).unwrap();
    cfg.state = StrategyState::Paper;
    cfg.universe = vec![BTC.into()];
    cfg
}

fn set(cfg: &mut StrategyConfig, key: &str, value: f64) {
    cfg.params.iter_mut().find(|p| p.key == key).unwrap_or_else(|| panic!("no param {key}")).value = value;
}

fn inputs(bars: &[Bar]) -> (HashMap<String, Market>, HashMap<String, Vec<f64>>, HashMap<String, Vec<Ohlc>>) {
    let markets = HashMap::from([(BTC.to_string(), market(BTC, bars.last().unwrap().3))]);
    let history = HashMap::from([(BTC.to_string(), bars.iter().map(|b| b.3).collect())]);
    let candles = HashMap::from([(BTC.to_string(), ohlc(bars, 1.0))]);
    (markets, history, candles)
}

#[test]
fn the_kind_serialises_as_candles() {
    assert_eq!(serde_json::to_string(&StrategyKind::Candles).unwrap(), "\"candles\"");
    let back: StrategyKind = serde_json::from_str("\"candles\"").unwrap();
    assert_eq!(back, StrategyKind::Candles);
}

#[test]
fn ships_paused_and_labelled_as_research() {
    let defaults = strategies::default_strategies();
    let c: Vec<_> = defaults.iter().filter(|s| s.kind == StrategyKind::Candles).collect();
    assert_eq!(c.len(), 1);
    assert_eq!(c[0].state, StrategyState::Paused);
    assert!(c[0].name.contains("research") && c[0].name.contains("no edge"), "{}", c[0].name);
    // Every bullish pattern can be switched on from the settings, and only those.
    let switches: Vec<&str> = c[0].params.iter().filter_map(|p| p.key.strip_prefix(strategies::CANDLE_PATTERN_PREFIX)).collect();
    assert_eq!(switches, candles::bullish().map(|p| p.name).collect::<Vec<_>>());
    assert!(strategies::candle_selection(c[0]).iter().any(|p| p.name == "hammer"));
}

#[test]
fn default_strategies_do_not_run_it() {
    let (kind, tail) = fixture("hammer");
    let (markets, history, candles) = inputs(&bars_of(kind, tail));
    for mut s in strategies::default_strategies().into_iter().filter(|s| s.kind == StrategyKind::Candles) {
        assert!(run_strategy_with_candles(&s, &markets, &history, &candles).is_empty(), "paused as shipped");
        s.universe = vec![BTC.into()];
        assert!(run_strategy_with_candles(&s, &markets, &history, &candles).is_empty(), "paused as shipped");
    }
}

#[test]
fn goes_long_when_its_pattern_fires_on_the_last_candle() {
    let (kind, tail) = fixture("hammer");
    let (markets, history, candles) = inputs(&bars_of(kind, tail));
    let out = run_strategy_with_candles(&candle_cfg(), &markets, &history, &candles);
    assert_eq!(out.len(), 1);
    assert_eq!(out[0].market_id, BTC);
    assert_eq!(out[0].side, Side::Buy);
    assert!(out[0].reason.contains("hammer") && out[0].reason.contains("last closed candle"), "{}", out[0].reason);
}

#[test]
fn nothing_when_paused() {
    let (kind, tail) = fixture("hammer");
    let (markets, history, candles) = inputs(&bars_of(kind, tail));
    let mut cfg = candle_cfg();
    cfg.state = StrategyState::Paused;
    assert!(run_strategy_with_candles(&cfg, &markets, &history, &candles).is_empty());
}

#[test]
fn nothing_without_candles() {
    let (kind, tail) = fixture("hammer");
    let (markets, history, _) = inputs(&bars_of(kind, tail));
    // Closes alone (the backtester's view, or a simulated market) are not candles.
    assert!(run_strategy(&candle_cfg(), &markets, &history).is_empty());
    assert!(run_strategy_with_candles(&candle_cfg(), &markets, &history, &HashMap::new()).is_empty());
    let empty = HashMap::from([(BTC.to_string(), Vec::new())]);
    assert!(run_strategy_with_candles(&candle_cfg(), &markets, &history, &empty).is_empty());
}

#[test]
fn nothing_when_no_pattern_fires_or_none_is_switched_on() {
    // A trending prefix alone: no switched-on reversal.
    let bars = prefix("down", 30);
    let (markets, history, candles) = inputs(&bars);
    assert!(run_strategy_with_candles(&candle_cfg(), &markets, &history, &candles).is_empty());
    // The hammer with the hammer switched off.
    let (kind, tail) = fixture("hammer");
    let (markets, history, candles) = inputs(&bars_of(kind, tail));
    let mut cfg = candle_cfg();
    set(&mut cfg, "pat.hammer", 0.0);
    assert!(run_strategy_with_candles(&cfg, &markets, &history, &candles).is_empty());
    for p in cfg.params.iter_mut() {
        if p.key.starts_with(strategies::CANDLE_PATTERN_PREFIX) {
            p.value = 0.0;
        }
    }
    assert!(run_strategy_with_candles(&cfg, &markets, &history, &candles).is_empty());
}

#[test]
fn min_bull_counts_the_switched_on_patterns() {
    // The hammer fixture's last bar is a hammer and nothing else bullish that is on.
    let (kind, tail) = fixture("hammer");
    let (markets, history, candles) = inputs(&bars_of(kind, tail));
    let mut cfg = candle_cfg();
    set(&mut cfg, "minBull", 2.0);
    assert!(run_strategy_with_candles(&cfg, &markets, &history, &candles).is_empty());
    // The engulfing bar is also a long white line: two once both are on.
    let (kind, tail) = fixture("engulfing_bull");
    let (markets, history, candles) = inputs(&bars_of(kind, tail));
    assert!(run_strategy_with_candles(&cfg, &markets, &history, &candles).is_empty());
    set(&mut cfg, "pat.long_white", 1.0);
    let out = run_strategy_with_candles(&cfg, &markets, &history, &candles);
    assert_eq!(out.len(), 1, "engulfing_bull + long_white");
    assert!(out[0].reason.contains("long_white + engulfing_bull"), "{}", out[0].reason);
}

#[test]
fn a_bearish_pattern_on_the_candle_blocks_the_entry() {
    // Every fixture whose last bar carries a bullish and a bearish pattern at
    // once: with the bullish ones switched on, noBear decides.
    let mut found = false;
    for (_, kind, tail) in FIXTURES {
        let bars = bars_of(kind, tail);
        let x = ctx_of(&bars, None);
        let s = x.signals_last().unwrap();
        let bull: Vec<&str> = s.hits.iter().filter(|p| p.direction > 0).map(|p| p.name).collect();
        if s.bear_count == 0 || bull.is_empty() {
            continue;
        }
        let (markets, history, candles) = inputs(&bars);
        let mut cfg = candle_cfg();
        for b in &bull {
            set(&mut cfg, &format!("pat.{b}"), 1.0);
        }
        assert!(run_strategy_with_candles(&cfg, &markets, &history, &candles).is_empty(), "noBear blocks {bull:?}");
        set(&mut cfg, "noBear", 0.0);
        assert_eq!(run_strategy_with_candles(&cfg, &markets, &history, &candles).len(), 1, "{bull:?}");
        found = true;
    }
    assert!(found, "some fixture ends on a bullish and a bearish pattern at once");
}

#[test]
fn support_and_volume_confirmation_gate_the_entry() {
    let (kind, tail) = fixture("hammer");
    let bars = bars_of(kind, tail);
    let (markets, history, mut candles) = inputs(&bars);
    let mut cfg = candle_cfg();
    set(&mut cfg, "atSupport", 1.0);
    assert_eq!(run_strategy_with_candles(&cfg, &markets, &history, &candles).len(), 1, "the hammer is at support");
    set(&mut cfg, "volume", 1.0);
    assert!(run_strategy_with_candles(&cfg, &markets, &history, &candles).is_empty(), "flat volume");
    candles.get_mut(BTC).unwrap().last_mut().unwrap().volume = 2.0;
    assert_eq!(run_strategy_with_candles(&cfg, &markets, &history, &candles).len(), 1, "volume 2x the mean");
}

#[test]
fn hold_keeps_the_signal_and_a_bearish_pattern_ends_it() {
    let (kind, tail) = fixture("hammer");
    let mut bars = bars_of(kind, tail);
    // Two quiet candles after the hammer: small, no pattern switched on.
    bars.push((100.5, 100.8, 100.3, 100.6));
    bars.push((100.6, 100.9, 100.4, 100.7));
    let (markets, history, candles) = inputs(&bars);
    let mut cfg = candle_cfg();
    assert!(run_strategy_with_candles(&cfg, &markets, &history, &candles).is_empty(), "hold 1: only the last candle");
    set(&mut cfg, "holdBars", 3.0);
    let out = run_strategy_with_candles(&cfg, &markets, &history, &candles);
    assert_eq!(out.len(), 1);
    assert!(out[0].reason.contains("2 candles ago"), "{}", out[0].reason);
    set(&mut cfg, "holdBars", 2.0);
    assert!(run_strategy_with_candles(&cfg, &markets, &history, &candles).is_empty(), "the hammer is 3 candles back");

    // A long black candle after the hammer is a bearish pattern: the signal ends.
    let mut bearish = bars_of(kind, tail);
    bearish.push((100.6, 100.7, 98.6, 98.8));
    let x = ctx_of(&bearish, None);
    assert!(x.signals_last().unwrap().bear_count > 0);
    let (markets, history, candles) = inputs(&bearish);
    set(&mut cfg, "holdBars", 3.0);
    assert!(run_strategy_with_candles(&cfg, &markets, &history, &candles).is_empty());
    set(&mut cfg, "exitOnBear", 0.0);
    assert_eq!(run_strategy_with_candles(&cfg, &markets, &history, &candles).len(), 1);
}

#[test]
fn the_engine_hands_its_candles_to_the_strategy() {
    // A 40-bar rise, a 25-bar fall, then a hammer: the 60-bar trend is still
    // up, so the engine's trend gate lets the long through.
    let mut bars: Vec<Bar> = Vec::new();
    for i in 0..40 {
        let o = 100.0 + 2.0 * i as f64;
        bars.push((o, o + 1.5, o - 0.5, o + 1.0));
    }
    for j in 0..25 {
        let o = 178.0 - 2.0 * j as f64;
        bars.push((o, o + 0.5, o - 1.5, o - 1.0));
    }
    bars.push((128.0, 128.6, 126.5, 128.5));
    assert!(fires_last(&ctx_of(&bars, None), "hammer"));
    // The feed's last candle is still forming; the engine drops it.
    let mut feed = ohlc(&bars, 1.0);
    feed.push(Ohlc { ts: 86_400_000 * bars.len() as i64, open: 128.5, high: 129.0, low: 128.0, close: 128.8, volume: 1.0 });

    let mut e = Engine::new();
    for s in e.strategies.iter_mut() {
        s.state = StrategyState::Paused;
    }
    let idx = e.strategies.iter().position(|s| s.kind == StrategyKind::Candles).expect("shipped");
    e.strategies[idx].state = StrategyState::Paper;
    e.strategies[idx].universe = vec![BTC.into()];
    e.apply_bars(&[BarSeries { id: BTC.into(), bars: feed }]);
    for _ in 0..5 {
        e.tick();
    }
    let sid = e.strategies[idx].id.clone();
    let signals: Vec<&str> = e
        .journal
        .iter()
        .filter(|j| j.kind == JournalKind::Signal && j.strategy_id.as_deref() == Some(sid.as_str()))
        .map(|j| j.message.as_str())
        .collect();
    assert!(signals.iter().any(|m| m.contains("hammer")), "journal: {signals:?}");
}
