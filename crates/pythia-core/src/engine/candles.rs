//! Classic candlestick patterns, a 1:1 port of the research lab's
//! `research/lab/lab/candles` (`patterns.py` and `derived.py`).
//!
//! The definitions, the parameter defaults, the tolerance rules, which
//! inequalities are strict and the handling of missing bars are the lab's,
//! exactly; `candles_parity.json` (written by `python -m
//! lab.candles.export_fixture`) holds the lab's hits on a few thousand bars and
//! the tests assert the same hits here, pattern by pattern and bar by bar.
//!
//! Conventions (see the lab module for the long form). A pattern is true on its
//! LAST bar, the bar at whose close it is complete. Bar 0 is that bar, bar 1 the
//! one before, and so on.
//!
//! * body = |close - open|, top = max(open, close), bot = min(open, close),
//!   upper shadow = high - top, lower shadow = bot - low, range = high - low,
//!   mid = (open + close) / 2; white: close > open, black: close < open.
//! * `A`, the yardstick of an n-bar pattern: the mean range of the `avg_n` bars
//!   before the pattern's first bar.
//! * trend before an n-bar pattern: the sign of close minus its `trend_n`-bar
//!   simple moving average, judged at the bar before the pattern's first bar.
//! * near: |a - b| <= near * A; "at or below x" is <= x + near * A, "at or
//!   above x" is >= x - near * A, "inside [lo, hi]" is between lo - near * A and
//!   hi + near * A. A window (a true gap) has no tolerance.
//! * A bar with a non-finite price, or an impossible one (high below the body
//!   or low above it), is no bar: all its prices count as missing, every
//!   comparison with a missing value is false and no definition negates a
//!   comparison, so nothing that looks at it fires. Rolling windows need every
//!   value in them present.
//!
//! Rolling means are taken the lab's way (a running sum over the whole series
//! and the difference of two of its entries), so the yardstick and the trend
//! carry the same rounding as numpy's and borderline bars agree too. Every
//! value at bar `t` depends on bars `0..=t` only.

use crate::marketdata::Ohlc;

pub const BULL: i8 = 1;
pub const BEAR: i8 = -1;
pub const NEUTRAL: i8 = 0;

/// Thresholds of the pattern definitions, the lab's `Params` with its defaults.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct CandleParams {
    /// Bars in the average range A.
    pub avg_n: usize,
    /// SMA length for the trend before a pattern.
    pub trend_n: usize,
    /// Doji: body <= doji * A.
    pub doji: f64,
    /// Short body: body <= short * A.
    pub short: f64,
    /// Long body: body >= long * A.
    pub long: f64,
    /// No shadow: shadow <= tiny * A.
    pub tiny: f64,
    /// Short shadow: shadow <= shadow_short * A.
    pub shadow_short: f64,
    /// Long shadow: shadow >= shadow_long * A.
    pub shadow_long: f64,
    /// Hammer family: the long shadow >= shadow_body * body.
    pub shadow_body: f64,
    /// Equal prices and the tolerance of "at or below".
    pub near: f64,
    /// Stars: the third bar closes this far into the first bar's body.
    pub penetration: f64,
    /// Donchian window for support and resistance.
    pub sr_n: usize,
    /// "At support": the pattern's low within sr_near * A of the window low.
    pub sr_near: f64,
    /// Volume average window.
    pub vol_n: usize,
    /// Volume confirmation: the last bar's volume >= vol_mult x the average.
    pub vol_mult: f64,
}

impl Default for CandleParams {
    fn default() -> Self {
        Self {
            avg_n: 10,
            trend_n: 20,
            doji: 0.1,
            short: 0.3,
            long: 0.7,
            tiny: 0.05,
            shadow_short: 0.1,
            shadow_long: 0.5,
            shadow_body: 2.0,
            near: 0.05,
            penetration: 0.3,
            sr_n: 20,
            sr_near: 0.5,
            vol_n: 20,
            vol_mult: 1.5,
        }
    }
}

/// What kind of statement a pattern makes.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PatternKind {
    Reversal,
    Continuation,
    Indecision,
    Strength,
}

impl PatternKind {
    pub fn as_str(self) -> &'static str {
        match self {
            PatternKind::Reversal => "reversal",
            PatternKind::Continuation => "continuation",
            PatternKind::Indecision => "indecision",
            PatternKind::Strength => "strength",
        }
    }
}

/// One named pattern: how many bars it spans, which way it points
/// ([`BULL`], [`BEAR`] or [`NEUTRAL`]) and its definition.
#[derive(Debug)]
pub struct Pattern {
    pub name: &'static str,
    pub bars: usize,
    pub direction: i8,
    pub kind: PatternKind,
    test: fn(&At) -> bool,
}

/// The bars and every measure the patterns ask for, computed once.
#[derive(Debug, Clone)]
pub struct CandleCtx {
    p: CandleParams,
    o: Vec<f64>,
    h: Vec<f64>,
    l: Vec<f64>,
    c: Vec<f64>,
    body: Vec<f64>,
    top: Vec<f64>,
    bot: Vec<f64>,
    upper: Vec<f64>,
    lower: Vec<f64>,
    rng: Vec<f64>,
    mid: Vec<f64>,
    avg: Vec<f64>,
    trend: Vec<f64>,
    v: Option<Vec<f64>>,
    vol_avg: Vec<f64>,
}

/// Trailing mean over n values including index t; NaN unless all n are finite.
/// Computed like the lab's numpy version (running sums and their differences)
/// so the result carries the same rounding.
pub fn rolling_mean(x: &[f64], n: usize) -> Vec<f64> {
    let mut cs = Vec::with_capacity(x.len());
    let mut cc = Vec::with_capacity(x.len());
    let (mut s, mut k) = (0.0f64, 0usize);
    for &v in x {
        if v.is_finite() {
            s += v;
            k += 1;
        } else {
            s += 0.0;
        }
        cs.push(s);
        cc.push(k);
    }
    (0..x.len())
        .map(|t| {
            if n == 0 || t + 1 < n {
                return f64::NAN;
            }
            let (sum, cnt) = if t >= n { (cs[t] - cs[t - n], cc[t] - cc[t - n]) } else { (cs[t], cc[t]) };
            if cnt == n {
                sum / n as f64
            } else {
                f64::NAN
            }
        })
        .collect()
}

/// Trailing max (or min) over the n values ending at index t; NaN when the
/// window is incomplete or holds a missing value.
fn window_extreme(x: &[f64], t: usize, n: usize, max: bool) -> f64 {
    if n == 0 || t + 1 < n || t >= x.len() {
        return f64::NAN;
    }
    let mut best = x[t + 1 - n];
    for &v in &x[t + 1 - n..=t] {
        if v.is_nan() {
            return f64::NAN;
        }
        if (max && v > best) || (!max && v < best) {
            best = v;
        }
    }
    best
}

fn sign(x: f64) -> f64 {
    if x > 0.0 {
        1.0
    } else if x < 0.0 {
        -1.0
    } else {
        0.0
    }
}

impl CandleCtx {
    /// Build from price columns of equal length (oldest first) and optional volume.
    pub fn new(o: &[f64], h: &[f64], l: &[f64], c: &[f64], v: Option<&[f64]>, params: CandleParams) -> Self {
        let n = o.len();
        assert!(h.len() == n && l.len() == n && c.len() == n, "price columns differ in length");
        if let Some(v) = v {
            assert_eq!(v.len(), n, "volume column differs in length");
        }
        let nan = f64::NAN;
        let mut cx = Self {
            p: params,
            o: vec![nan; n],
            h: vec![nan; n],
            l: vec![nan; n],
            c: vec![nan; n],
            body: vec![nan; n],
            top: vec![nan; n],
            bot: vec![nan; n],
            upper: vec![nan; n],
            lower: vec![nan; n],
            rng: vec![nan; n],
            mid: vec![nan; n],
            avg: Vec::new(),
            trend: Vec::new(),
            v: v.map(|v| v.to_vec()),
            vol_avg: Vec::new(),
        };
        for t in 0..n {
            let (bo, bh, bl, bc) = (o[t], h[t], l[t], c[t]);
            let finite = bo.is_finite() && bh.is_finite() && bl.is_finite() && bc.is_finite();
            // An impossible bar is no bar.
            if !finite || bh < bo.max(bc) || bl > bo.min(bc) {
                continue;
            }
            let (top, bot) = (bo.max(bc), bo.min(bc));
            cx.o[t] = bo;
            cx.h[t] = bh;
            cx.l[t] = bl;
            cx.c[t] = bc;
            cx.body[t] = (bc - bo).abs();
            cx.top[t] = top;
            cx.bot[t] = bot;
            cx.upper[t] = bh - top;
            cx.lower[t] = bot - bl;
            cx.rng[t] = bh - bl;
            cx.mid[t] = (bo + bc) / 2.0;
        }
        cx.avg = rolling_mean(&cx.rng, params.avg_n);
        let sma = rolling_mean(&cx.c, params.trend_n);
        cx.trend = (0..n)
            .map(|t| if sma[t].is_finite() && cx.c[t].is_finite() { sign(cx.c[t] - sma[t]) } else { nan })
            .collect();
        cx.vol_avg = match &cx.v {
            Some(v) => rolling_mean(v, params.vol_n),
            None => Vec::new(),
        };
        cx
    }

    /// Build from engine candles (volume included).
    pub fn from_ohlc(bars: &[Ohlc], params: CandleParams) -> Self {
        let col = |f: fn(&Ohlc) -> f64| bars.iter().map(f).collect::<Vec<f64>>();
        let (o, h, l, c, v) = (col(|b| b.open), col(|b| b.high), col(|b| b.low), col(|b| b.close), col(|b| b.volume));
        Self::new(&o, &h, &l, &c, Some(&v), params)
    }

    pub fn len(&self) -> usize {
        self.o.len()
    }

    pub fn is_empty(&self) -> bool {
        self.o.is_empty()
    }

    pub fn params(&self) -> &CandleParams {
        &self.p
    }

    fn at(&self, t: usize) -> At<'_> {
        At { x: self, t }
    }

    /// Whether `pattern` ends on bar `t` (false past the end).
    pub fn fires(&self, pattern: &Pattern, t: usize) -> bool {
        t < self.len() && (pattern.test)(&self.at(t))
    }

    /// Every pattern that ends on bar `t`, in registry order.
    pub fn hits_at(&self, t: usize) -> Vec<&'static Pattern> {
        PATTERNS.iter().filter(|p| self.fires(p, t)).collect()
    }

    /// An n-bar pattern ending on bar t sits at support: its lowest low lies
    /// within sr_near x A of (or below) the lowest low of the sr_n bars before
    /// the pattern.
    pub fn at_support(&self, t: usize, n: usize) -> bool {
        if t >= self.len() {
            return false;
        }
        let lo = window_extreme(&self.l, t, n, false);
        let don = if t >= n { window_extreme(&self.l, t - n, self.p.sr_n, false) } else { f64::NAN };
        lo <= don + self.p.sr_near * self.at(t).a(n)
    }

    /// The mirror of [`Self::at_support`] on the highs.
    pub fn at_resistance(&self, t: usize, n: usize) -> bool {
        if t >= self.len() {
            return false;
        }
        let hi = window_extreme(&self.h, t, n, true);
        let don = if t >= n { window_extreme(&self.h, t - n, self.p.sr_n, true) } else { f64::NAN };
        hi >= don - self.p.sr_near * self.at(t).a(n)
    }

    /// Bar t's volume is at least vol_mult x the mean of the vol_n bars before
    /// it. False without volume.
    pub fn volume_confirmed(&self, t: usize) -> bool {
        let Some(v) = &self.v else { return false };
        if t >= v.len() || t == 0 {
            return false;
        }
        v[t] >= self.p.vol_mult * self.vol_avg[t - 1]
    }

    /// Every pattern and the derived signals on bar `t`.
    pub fn signals_at(&self, t: usize) -> Signals {
        let hits = self.hits_at(t);
        let (mut bull, mut bear) = (0i32, 0i32);
        let (mut sup, mut res) = (false, false);
        for p in &hits {
            if p.direction > 0 {
                bull += 1;
                sup = sup || self.at_support(t, p.bars);
            } else if p.direction < 0 {
                bear += 1;
                res = res || self.at_resistance(t, p.bars);
            }
        }
        let vol = self.volume_confirmed(t);
        Signals {
            hits,
            bull_count: bull,
            bear_count: bear,
            bull_confluence: bull >= 2 && bear == 0,
            bear_confluence: bear >= 2 && bull == 0,
            bull_at_support: sup,
            bear_at_resistance: res,
            bull_volume: bull > 0 && vol,
            bear_volume: bear > 0 && vol,
        }
    }

    /// [`Self::signals_at`] on the last bar; `None` without bars.
    pub fn signals_last(&self) -> Option<Signals> {
        self.len().checked_sub(1).map(|t| self.signals_at(t))
    }
}

/// The patterns and derived signals on one bar (the lab's `signals` row).
#[derive(Debug, Clone)]
pub struct Signals {
    /// The patterns ending on the bar, in registry order.
    pub hits: Vec<&'static Pattern>,
    /// How many distinct bullish (bearish) patterns end on the bar.
    pub bull_count: i32,
    pub bear_count: i32,
    /// At least two bullish patterns and no bearish one (and the mirror).
    pub bull_confluence: bool,
    pub bear_confluence: bool,
    /// A bullish pattern at the lower Donchian bound before it (see
    /// [`CandleCtx::at_support`]); the bearish mirror at the upper bound.
    pub bull_at_support: bool,
    pub bear_at_resistance: bool,
    /// A bullish (bearish) pattern on a bar with confirming volume.
    pub bull_volume: bool,
    pub bear_volume: bool,
}

impl Signals {
    pub fn net(&self) -> i32 {
        self.bull_count - self.bear_count
    }

    pub fn fired(&self, name: &str) -> bool {
        self.hits.iter().any(|p| p.name == name)
    }

    /// A derived signal by its lab name (`bull_confluence` ... `bear_volume`).
    pub fn derived(&self, name: &str) -> Option<bool> {
        Some(match name {
            "bull_confluence" => self.bull_confluence,
            "bear_confluence" => self.bear_confluence,
            "bull_at_support" => self.bull_at_support,
            "bear_at_resistance" => self.bear_at_resistance,
            "bull_volume" => self.bull_volume,
            "bear_volume" => self.bear_volume,
            _ => return None,
        })
    }
}

/// The derived signals' names, as in the lab.
pub const DERIVED: [&str; 6] =
    ["bull_confluence", "bear_confluence", "bull_at_support", "bear_at_resistance", "bull_volume", "bear_volume"];

/// Every pattern and the derived signals on the last of `bars`.
pub fn detect_last(bars: &[Ohlc], params: CandleParams) -> Option<Signals> {
    CandleCtx::from_ohlc(bars, params).signals_last()
}

/// A pattern by its lab name.
pub fn pattern(name: &str) -> Option<&'static Pattern> {
    PATTERNS.iter().find(|p| p.name == name)
}

// ── one bar's view ─────────────────────────────────────────────────────────

/// The context seen from bar `t`: `o(k)` is the open k bars back, NaN before
/// the first bar.
struct At<'a> {
    x: &'a CandleCtx,
    t: usize,
}

impl At<'_> {
    fn lag(&self, a: &[f64], k: usize) -> f64 {
        if self.t >= k {
            a[self.t - k]
        } else {
            f64::NAN
        }
    }
    fn o(&self, k: usize) -> f64 {
        self.lag(&self.x.o, k)
    }
    fn h(&self, k: usize) -> f64 {
        self.lag(&self.x.h, k)
    }
    fn l(&self, k: usize) -> f64 {
        self.lag(&self.x.l, k)
    }
    fn c(&self, k: usize) -> f64 {
        self.lag(&self.x.c, k)
    }
    fn body(&self, k: usize) -> f64 {
        self.lag(&self.x.body, k)
    }
    fn top(&self, k: usize) -> f64 {
        self.lag(&self.x.top, k)
    }
    fn bot(&self, k: usize) -> f64 {
        self.lag(&self.x.bot, k)
    }
    fn upper(&self, k: usize) -> f64 {
        self.lag(&self.x.upper, k)
    }
    fn lower(&self, k: usize) -> f64 {
        self.lag(&self.x.lower, k)
    }
    fn rng(&self, k: usize) -> f64 {
        self.lag(&self.x.rng, k)
    }
    fn mid(&self, k: usize) -> f64 {
        self.lag(&self.x.mid, k)
    }
    fn white(&self, k: usize) -> bool {
        self.c(k) > self.o(k)
    }
    fn black(&self, k: usize) -> bool {
        self.c(k) < self.o(k)
    }
    /// The yardstick of an n-bar pattern.
    fn a(&self, n: usize) -> f64 {
        self.lag(&self.x.avg, n)
    }
    /// Downtrend before an n-bar pattern (judged at bar n).
    fn down(&self, n: usize) -> bool {
        self.lag(&self.x.trend, n) < 0.0
    }
    fn up(&self, n: usize) -> bool {
        self.lag(&self.x.trend, n) > 0.0
    }
    fn p(&self) -> &CandleParams {
        &self.x.p
    }

    // shared shapes
    fn doji(&self, k: usize, a: f64) -> bool {
        self.body(k) <= self.p().doji * a
    }
    fn short(&self, k: usize, a: f64) -> bool {
        self.body(k) <= self.p().short * a
    }
    /// Short but not a doji.
    fn small(&self, k: usize, a: f64) -> bool {
        self.body(k) > self.p().doji * a && self.body(k) <= self.p().short * a
    }
    fn long(&self, k: usize, a: f64) -> bool {
        self.body(k) >= self.p().long * a
    }
    /// Not a short body.
    fn real(&self, k: usize, a: f64) -> bool {
        self.body(k) > self.p().short * a
    }
    fn near(&self, x: f64, y: f64, a: f64) -> bool {
        (x - y).abs() <= self.p().near * a
    }
    fn at_or_below(&self, x: f64, y: f64, a: f64) -> bool {
        x <= y + self.p().near * a
    }
    fn at_or_above(&self, x: f64, y: f64, a: f64) -> bool {
        x >= y - self.p().near * a
    }
    fn inside(&self, x: f64, lo: f64, hi: f64, a: f64) -> bool {
        x >= lo - self.p().near * a && x <= hi + self.p().near * a
    }
    /// Bar k's body inside bar j's body.
    fn body_inside(&self, k: usize, j: usize, a: f64) -> bool {
        self.top(k) <= self.top(j) + self.p().near * a && self.bot(k) >= self.bot(j) - self.p().near * a
    }
    fn hammer_shape(&self, a: f64) -> bool {
        let (b, lo, up) = (self.body(0), self.lower(0), self.upper(0));
        self.short(0, a) && lo >= self.p().shadow_body * b && lo >= self.p().shadow_long * a && up <= self.p().shadow_short * a
    }
    fn inverted_shape(&self, a: f64) -> bool {
        let (b, lo, up) = (self.body(0), self.lower(0), self.upper(0));
        self.short(0, a) && up >= self.p().shadow_body * b && up >= self.p().shadow_long * a && lo <= self.p().shadow_short * a
    }
    fn star_bull(&self, a: f64, star: bool) -> bool {
        self.down(3)
            && self.black(2)
            && self.long(2, a)
            && star
            && self.at_or_below(self.top(1), self.c(2), a)
            && self.white(0)
            && self.c(0) > self.c(2) + self.p().penetration * self.body(2)
    }
    fn star_bear(&self, a: f64, star: bool) -> bool {
        self.up(3)
            && self.white(2)
            && self.long(2, a)
            && star
            && self.at_or_above(self.bot(1), self.c(2), a)
            && self.black(0)
            && self.c(0) < self.c(2) - self.p().penetration * self.body(2)
    }
}

// ── one bar ────────────────────────────────────────────────────────────────

fn doji(x: &At) -> bool {
    x.doji(0, x.a(1))
}
fn long_legged_doji(x: &At) -> bool {
    let a = x.a(1);
    x.doji(0, a) && x.upper(0) >= x.p().shadow_long * a && x.lower(0) >= x.p().shadow_long * a
}
fn rickshaw_man(x: &At) -> bool {
    let centre = (x.h(0) + x.l(0)) / 2.0;
    long_legged_doji(x) && (x.mid(0) - centre).abs() <= 0.1 * x.rng(0)
}
fn dragonfly_doji(x: &At) -> bool {
    let a = x.a(1);
    x.doji(0, a) && x.upper(0) <= x.p().tiny * a && x.lower(0) >= x.p().shadow_long * a
}
fn gravestone_doji(x: &At) -> bool {
    let a = x.a(1);
    x.doji(0, a) && x.lower(0) <= x.p().tiny * a && x.upper(0) >= x.p().shadow_long * a
}
fn four_price_doji(x: &At) -> bool {
    x.rng(0) <= x.p().tiny * x.a(1)
}
fn takuri(x: &At) -> bool {
    let a = x.a(1);
    x.doji(0, a) && x.upper(0) <= x.p().tiny * a && x.lower(0) >= a
}
fn hammer(x: &At) -> bool {
    x.down(1) && x.hammer_shape(x.a(1))
}
fn hanging_man(x: &At) -> bool {
    x.up(1) && x.hammer_shape(x.a(1))
}
fn inverted_hammer(x: &At) -> bool {
    x.down(1) && x.inverted_shape(x.a(1))
}
fn shooting_star(x: &At) -> bool {
    x.up(1) && x.inverted_shape(x.a(1))
}
fn marubozu_white(x: &At) -> bool {
    let a = x.a(1);
    x.white(0) && x.long(0, a) && x.upper(0) <= x.p().tiny * a && x.lower(0) <= x.p().tiny * a
}
fn marubozu_black(x: &At) -> bool {
    let a = x.a(1);
    x.black(0) && x.long(0, a) && x.upper(0) <= x.p().tiny * a && x.lower(0) <= x.p().tiny * a
}
fn closing_marubozu_white(x: &At) -> bool {
    let a = x.a(1);
    x.white(0) && x.long(0, a) && x.upper(0) <= x.p().tiny * a && x.lower(0) > x.p().tiny * a
}
fn closing_marubozu_black(x: &At) -> bool {
    let a = x.a(1);
    x.black(0) && x.long(0, a) && x.lower(0) <= x.p().tiny * a && x.upper(0) > x.p().tiny * a
}
fn belt_hold_bull(x: &At) -> bool {
    let a = x.a(1);
    x.down(1) && x.white(0) && x.long(0, a) && x.lower(0) <= x.p().tiny * a
}
fn belt_hold_bear(x: &At) -> bool {
    let a = x.a(1);
    x.up(1) && x.black(0) && x.long(0, a) && x.upper(0) <= x.p().tiny * a
}
fn long_white(x: &At) -> bool {
    x.white(0) && x.long(0, x.a(1))
}
fn long_black(x: &At) -> bool {
    x.black(0) && x.long(0, x.a(1))
}
fn spinning_top(x: &At) -> bool {
    let a = x.a(1);
    x.small(0, a) && x.upper(0) > x.body(0) && x.lower(0) > x.body(0)
}
fn high_wave(x: &At) -> bool {
    let a = x.a(1);
    x.small(0, a) && x.upper(0) >= x.p().shadow_long * a && x.lower(0) >= x.p().shadow_long * a
}

// ── two bars ───────────────────────────────────────────────────────────────

fn engulfing_bull(x: &At) -> bool {
    let a = x.a(2);
    x.down(2) && x.black(1) && x.white(0) && x.at_or_below(x.o(0), x.c(1), a) && x.c(0) > x.o(1)
}
fn engulfing_bear(x: &At) -> bool {
    let a = x.a(2);
    x.up(2) && x.white(1) && x.black(0) && x.at_or_above(x.o(0), x.c(1), a) && x.c(0) < x.o(1)
}
fn harami_bull(x: &At) -> bool {
    let a = x.a(2);
    x.down(2) && x.black(1) && x.long(1, a) && x.small(0, a) && x.body_inside(0, 1, a)
}
fn harami_bear(x: &At) -> bool {
    let a = x.a(2);
    x.up(2) && x.white(1) && x.long(1, a) && x.small(0, a) && x.body_inside(0, 1, a)
}
fn harami_cross_bull(x: &At) -> bool {
    let a = x.a(2);
    x.down(2) && x.black(1) && x.long(1, a) && x.doji(0, a) && x.body_inside(0, 1, a)
}
fn harami_cross_bear(x: &At) -> bool {
    let a = x.a(2);
    x.up(2) && x.white(1) && x.long(1, a) && x.doji(0, a) && x.body_inside(0, 1, a)
}
fn piercing(x: &At) -> bool {
    let a = x.a(2);
    x.down(2)
        && x.black(1)
        && x.long(1, a)
        && x.white(0)
        && x.at_or_below(x.o(0), x.c(1), a)
        && x.c(0) > x.mid(1)
        && x.c(0) < x.o(1)
}
fn dark_cloud_cover(x: &At) -> bool {
    let a = x.a(2);
    x.up(2)
        && x.white(1)
        && x.long(1, a)
        && x.black(0)
        && x.at_or_above(x.o(0), x.c(1), a)
        && x.c(0) < x.mid(1)
        && x.c(0) > x.o(1)
}
fn tweezer_bottom(x: &At) -> bool {
    let a = x.a(2);
    x.down(2) && x.black(1) && x.white(0) && x.near(x.l(0), x.l(1), a)
}
fn tweezer_top(x: &At) -> bool {
    let a = x.a(2);
    x.up(2) && x.white(1) && x.black(0) && x.near(x.h(0), x.h(1), a)
}
fn kicker_bull(x: &At) -> bool {
    let a = x.a(2);
    x.black(1) && x.long(1, a) && x.white(0) && x.long(0, a) && x.o(0) > x.o(1)
}
fn kicker_bear(x: &At) -> bool {
    let a = x.a(2);
    x.white(1) && x.long(1, a) && x.black(0) && x.long(0, a) && x.o(0) < x.o(1)
}
fn counterattack_bull(x: &At) -> bool {
    let a = x.a(2);
    x.down(2) && x.black(1) && x.long(1, a) && x.white(0) && x.long(0, a) && x.near(x.c(0), x.c(1), a)
}
fn counterattack_bear(x: &At) -> bool {
    let a = x.a(2);
    x.up(2) && x.white(1) && x.long(1, a) && x.black(0) && x.long(0, a) && x.near(x.c(0), x.c(1), a)
}
fn homing_pigeon(x: &At) -> bool {
    let a = x.a(2);
    x.down(2) && x.black(1) && x.long(1, a) && x.black(0) && x.body(0) < x.body(1) && x.body_inside(0, 1, a)
}
fn descending_hawk(x: &At) -> bool {
    let a = x.a(2);
    x.up(2) && x.white(1) && x.long(1, a) && x.white(0) && x.body(0) < x.body(1) && x.body_inside(0, 1, a)
}
fn matching_low(x: &At) -> bool {
    let a = x.a(2);
    x.down(2) && x.black(1) && x.long(1, a) && x.black(0) && x.near(x.c(0), x.c(1), a)
}
fn matching_high(x: &At) -> bool {
    let a = x.a(2);
    x.up(2) && x.white(1) && x.long(1, a) && x.white(0) && x.near(x.c(0), x.c(1), a)
}
fn on_neck(x: &At) -> bool {
    let a = x.a(2);
    x.down(2) && x.black(1) && x.long(1, a) && x.white(0) && x.o(0) < x.l(1) && x.near(x.c(0), x.l(1), a)
}
fn in_neck(x: &At) -> bool {
    let a = x.a(2);
    x.down(2)
        && x.black(1)
        && x.long(1, a)
        && x.white(0)
        && x.o(0) < x.l(1)
        && x.c(0) > x.c(1)
        && x.c(0) <= x.c(1) + x.p().near * a
}
fn thrusting(x: &At) -> bool {
    let a = x.a(2);
    x.down(2)
        && x.black(1)
        && x.long(1, a)
        && x.white(0)
        && x.o(0) < x.l(1)
        && x.c(0) > x.c(1) + x.p().near * a
        && x.c(0) <= x.mid(1)
}
fn separating_lines_bull(x: &At) -> bool {
    let a = x.a(2);
    x.up(2)
        && x.black(1)
        && x.white(0)
        && x.long(0, a)
        && x.near(x.o(0), x.o(1), a)
        && x.lower(0) <= x.p().tiny * a
}
fn separating_lines_bear(x: &At) -> bool {
    let a = x.a(2);
    x.down(2)
        && x.white(1)
        && x.black(0)
        && x.long(0, a)
        && x.near(x.o(0), x.o(1), a)
        && x.upper(0) <= x.p().tiny * a
}
fn doji_star_bull(x: &At) -> bool {
    let a = x.a(2);
    x.down(2) && x.black(1) && x.long(1, a) && x.doji(0, a) && x.at_or_below(x.top(0), x.c(1), a)
}
fn doji_star_bear(x: &At) -> bool {
    let a = x.a(2);
    x.up(2) && x.white(1) && x.long(1, a) && x.doji(0, a) && x.at_or_above(x.bot(0), x.c(1), a)
}

// ── three bars ─────────────────────────────────────────────────────────────

fn morning_star(x: &At) -> bool {
    let a = x.a(3);
    x.star_bull(a, x.short(1, a))
}
fn evening_star(x: &At) -> bool {
    let a = x.a(3);
    x.star_bear(a, x.short(1, a))
}
fn morning_doji_star(x: &At) -> bool {
    let a = x.a(3);
    x.star_bull(a, x.doji(1, a))
}
fn evening_doji_star(x: &At) -> bool {
    let a = x.a(3);
    x.star_bear(a, x.doji(1, a))
}
fn abandoned_baby_bull(x: &At) -> bool {
    let a = x.a(3);
    x.down(3)
        && x.black(2)
        && x.long(2, a)
        && x.doji(1, a)
        && x.h(1) < x.l(2)
        && x.white(0)
        && x.l(0) > x.h(1)
        && x.c(0) > x.c(2) + x.p().penetration * x.body(2)
}
fn abandoned_baby_bear(x: &At) -> bool {
    let a = x.a(3);
    x.up(3)
        && x.white(2)
        && x.long(2, a)
        && x.doji(1, a)
        && x.l(1) > x.h(2)
        && x.black(0)
        && x.h(0) < x.l(1)
        && x.c(0) < x.c(2) - x.p().penetration * x.body(2)
}
fn three_white_soldiers(x: &At) -> bool {
    let a = x.a(3);
    let mut m = x.down(3) && x.c(0) > x.c(1) && x.c(1) > x.c(2);
    for k in [0, 1, 2] {
        m = m && x.white(k) && x.real(k, a) && x.upper(k) <= x.p().shadow_short * a;
    }
    m && x.inside(x.o(1), x.o(2), x.c(2), a) && x.inside(x.o(0), x.o(1), x.c(1), a)
}
fn three_black_crows(x: &At) -> bool {
    let a = x.a(3);
    let mut m = x.up(3) && x.c(0) < x.c(1) && x.c(1) < x.c(2);
    for k in [0, 1, 2] {
        m = m && x.black(k) && x.real(k, a) && x.lower(k) <= x.p().shadow_short * a;
    }
    m && x.inside(x.o(1), x.c(2), x.o(2), a) && x.inside(x.o(0), x.c(1), x.o(1), a)
}
fn identical_three_crows(x: &At) -> bool {
    let a = x.a(3);
    three_black_crows(x) && x.near(x.o(1), x.c(2), a) && x.near(x.o(0), x.c(1), a)
}
fn three_inside_up(x: &At) -> bool {
    let a = x.a(3);
    x.down(3)
        && x.black(2)
        && x.long(2, a)
        && x.short(1, a)
        && x.body_inside(1, 2, a)
        && x.white(0)
        && x.c(0) > x.o(2)
}
fn three_inside_down(x: &At) -> bool {
    let a = x.a(3);
    x.up(3)
        && x.white(2)
        && x.long(2, a)
        && x.short(1, a)
        && x.body_inside(1, 2, a)
        && x.black(0)
        && x.c(0) < x.o(2)
}
fn three_outside_up(x: &At) -> bool {
    let a = x.a(3);
    x.down(3)
        && x.black(2)
        && x.white(1)
        && x.at_or_below(x.o(1), x.c(2), a)
        && x.c(1) > x.o(2)
        && x.white(0)
        && x.c(0) > x.c(1)
}
fn three_outside_down(x: &At) -> bool {
    let a = x.a(3);
    x.up(3)
        && x.white(2)
        && x.black(1)
        && x.at_or_above(x.o(1), x.c(2), a)
        && x.c(1) < x.o(2)
        && x.black(0)
        && x.c(0) < x.c(1)
}
fn upside_tasuki_gap(x: &At) -> bool {
    x.up(3)
        && x.white(2)
        && x.white(1)
        && x.l(1) > x.h(2)
        && x.black(0)
        && x.o(0) > x.o(1)
        && x.o(0) < x.c(1)
        && x.c(0) < x.o(1)
        && x.c(0) > x.h(2)
}
fn downside_tasuki_gap(x: &At) -> bool {
    x.down(3)
        && x.black(2)
        && x.black(1)
        && x.h(1) < x.l(2)
        && x.white(0)
        && x.o(0) < x.o(1)
        && x.o(0) > x.c(1)
        && x.c(0) > x.o(1)
        && x.c(0) < x.l(2)
}
fn stick_sandwich(x: &At) -> bool {
    let a = x.a(3);
    x.down(3) && x.black(2) && x.white(1) && x.l(1) > x.c(2) && x.black(0) && x.near(x.c(0), x.c(2), a)
}
fn unique_three_river(x: &At) -> bool {
    let a = x.a(3);
    x.down(3)
        && x.black(2)
        && x.long(2, a)
        && x.black(1)
        && x.c(1) > x.c(2)
        && x.o(1) <= x.o(2)
        && x.l(1) < x.l(2)
        && x.white(0)
        && x.short(0, a)
        && x.c(0) < x.c(1)
        && x.o(0) > x.l(1)
}
fn tri_star_bull(x: &At) -> bool {
    let a = x.a(3);
    x.down(3) && x.doji(2, a) && x.doji(1, a) && x.doji(0, a) && x.top(1) < x.bot(2) && x.top(1) < x.bot(0)
}
fn tri_star_bear(x: &At) -> bool {
    let a = x.a(3);
    x.up(3) && x.doji(2, a) && x.doji(1, a) && x.doji(0, a) && x.bot(1) > x.top(2) && x.bot(1) > x.top(0)
}
fn two_crows(x: &At) -> bool {
    let a = x.a(3);
    x.up(3)
        && x.white(2)
        && x.long(2, a)
        && x.black(1)
        && x.bot(1) > x.top(2)
        && x.black(0)
        && x.o(0) < x.o(1)
        && x.o(0) > x.c(1)
        && x.c(0) > x.o(2)
        && x.c(0) < x.c(2)
}
fn upside_gap_two_crows(x: &At) -> bool {
    let a = x.a(3);
    x.up(3)
        && x.white(2)
        && x.long(2, a)
        && x.black(1)
        && x.bot(1) > x.top(2)
        && x.black(0)
        && x.o(0) > x.o(1)
        && x.c(0) < x.c(1)
        && x.c(0) > x.c(2)
}
fn advance_block(x: &At) -> bool {
    let a = x.a(3);
    x.up(3)
        && x.white(2)
        && x.white(1)
        && x.white(0)
        && x.c(0) > x.c(1)
        && x.c(1) > x.c(2)
        && x.inside(x.o(1), x.o(2), x.c(2), a)
        && x.inside(x.o(0), x.o(1), x.c(1), a)
        && x.long(2, a)
        && x.body(0) < x.body(1)
        && x.body(1) < x.body(2)
        && (x.upper(0) > x.p().shadow_short * a || x.upper(1) > x.p().shadow_short * a)
}
fn deliberation(x: &At) -> bool {
    let a = x.a(3);
    x.up(3)
        && x.white(2)
        && x.white(1)
        && x.white(0)
        && x.long(2, a)
        && x.long(1, a)
        && x.short(0, a)
        && x.c(1) > x.c(2)
        && x.c(0) > x.c(1)
        && x.inside(x.o(1), x.o(2), x.c(2), a)
        && x.at_or_above(x.o(0), x.c(1), a)
}

// ── four and five bars ─────────────────────────────────────────────────────

fn three_line_strike_bull(x: &At) -> bool {
    let a = x.a(4);
    x.up(4)
        && x.white(3)
        && x.white(2)
        && x.white(1)
        && x.c(2) > x.c(3)
        && x.c(1) > x.c(2)
        && x.black(0)
        && x.at_or_above(x.o(0), x.c(1), a)
        && x.c(0) < x.o(3)
}
fn three_line_strike_bear(x: &At) -> bool {
    let a = x.a(4);
    x.down(4)
        && x.black(3)
        && x.black(2)
        && x.black(1)
        && x.c(2) < x.c(3)
        && x.c(1) < x.c(2)
        && x.white(0)
        && x.at_or_below(x.o(0), x.c(1), a)
        && x.c(0) > x.o(3)
}
fn rising_three_methods(x: &At) -> bool {
    let a = x.a(5);
    let mut m = x.up(5) && x.white(4) && x.long(4, a) && x.c(3) > x.c(2) && x.c(2) > x.c(1);
    for k in [3, 2, 1] {
        m = m && x.short(k, a) && x.h(k) <= x.h(4) && x.l(k) >= x.l(4);
    }
    m && x.white(0) && x.long(0, a) && x.at_or_above(x.o(0), x.c(1), a) && x.c(0) > x.c(4)
}
fn falling_three_methods(x: &At) -> bool {
    let a = x.a(5);
    let mut m = x.down(5) && x.black(4) && x.long(4, a) && x.c(3) < x.c(2) && x.c(2) < x.c(1);
    for k in [3, 2, 1] {
        m = m && x.short(k, a) && x.h(k) <= x.h(4) && x.l(k) >= x.l(4);
    }
    m && x.black(0) && x.long(0, a) && x.at_or_below(x.o(0), x.c(1), a) && x.c(0) < x.c(4)
}
fn ladder_bottom(x: &At) -> bool {
    let m = x.down(5)
        && x.black(4)
        && x.black(3)
        && x.black(2)
        && x.o(3) < x.o(4)
        && x.o(2) < x.o(3)
        && x.c(3) < x.c(4)
        && x.c(2) < x.c(3);
    m && x.black(1) && x.upper(1) > x.body(1) && x.white(0) && x.o(0) > x.o(1) && x.c(0) > x.h(1)
}

// ── registry ───────────────────────────────────────────────────────────────

const fn pat(name: &'static str, bars: usize, direction: i8, kind: PatternKind, test: fn(&At) -> bool) -> Pattern {
    Pattern { name, bars, direction, kind, test }
}

use PatternKind::{Continuation as CONT, Indecision as INDEC, Reversal as REV, Strength as STRONG};

/// Every pattern, in the lab's registry order.
pub static PATTERNS: [Pattern; 74] = [
    // one bar
    pat("doji", 1, NEUTRAL, INDEC, doji),
    pat("long_legged_doji", 1, NEUTRAL, INDEC, long_legged_doji),
    pat("rickshaw_man", 1, NEUTRAL, INDEC, rickshaw_man),
    pat("dragonfly_doji", 1, BULL, REV, dragonfly_doji),
    pat("gravestone_doji", 1, BEAR, REV, gravestone_doji),
    pat("four_price_doji", 1, NEUTRAL, INDEC, four_price_doji),
    pat("takuri", 1, BULL, REV, takuri),
    pat("hammer", 1, BULL, REV, hammer),
    pat("hanging_man", 1, BEAR, REV, hanging_man),
    pat("inverted_hammer", 1, BULL, REV, inverted_hammer),
    pat("shooting_star", 1, BEAR, REV, shooting_star),
    pat("marubozu_white", 1, BULL, STRONG, marubozu_white),
    pat("marubozu_black", 1, BEAR, STRONG, marubozu_black),
    pat("closing_marubozu_white", 1, BULL, STRONG, closing_marubozu_white),
    pat("closing_marubozu_black", 1, BEAR, STRONG, closing_marubozu_black),
    pat("belt_hold_bull", 1, BULL, REV, belt_hold_bull),
    pat("belt_hold_bear", 1, BEAR, REV, belt_hold_bear),
    pat("long_white", 1, BULL, STRONG, long_white),
    pat("long_black", 1, BEAR, STRONG, long_black),
    pat("spinning_top", 1, NEUTRAL, INDEC, spinning_top),
    pat("high_wave", 1, NEUTRAL, INDEC, high_wave),
    // two bars
    pat("engulfing_bull", 2, BULL, REV, engulfing_bull),
    pat("engulfing_bear", 2, BEAR, REV, engulfing_bear),
    pat("harami_bull", 2, BULL, REV, harami_bull),
    pat("harami_bear", 2, BEAR, REV, harami_bear),
    pat("harami_cross_bull", 2, BULL, REV, harami_cross_bull),
    pat("harami_cross_bear", 2, BEAR, REV, harami_cross_bear),
    pat("piercing", 2, BULL, REV, piercing),
    pat("dark_cloud_cover", 2, BEAR, REV, dark_cloud_cover),
    pat("tweezer_bottom", 2, BULL, REV, tweezer_bottom),
    pat("tweezer_top", 2, BEAR, REV, tweezer_top),
    pat("kicker_bull", 2, BULL, REV, kicker_bull),
    pat("kicker_bear", 2, BEAR, REV, kicker_bear),
    pat("counterattack_bull", 2, BULL, REV, counterattack_bull),
    pat("counterattack_bear", 2, BEAR, REV, counterattack_bear),
    pat("homing_pigeon", 2, BULL, REV, homing_pigeon),
    pat("descending_hawk", 2, BEAR, REV, descending_hawk),
    pat("matching_low", 2, BULL, REV, matching_low),
    pat("matching_high", 2, BEAR, REV, matching_high),
    pat("on_neck", 2, BEAR, CONT, on_neck),
    pat("in_neck", 2, BEAR, CONT, in_neck),
    pat("thrusting", 2, BEAR, CONT, thrusting),
    pat("separating_lines_bull", 2, BULL, CONT, separating_lines_bull),
    pat("separating_lines_bear", 2, BEAR, CONT, separating_lines_bear),
    pat("doji_star_bull", 2, BULL, REV, doji_star_bull),
    pat("doji_star_bear", 2, BEAR, REV, doji_star_bear),
    // three bars
    pat("morning_star", 3, BULL, REV, morning_star),
    pat("evening_star", 3, BEAR, REV, evening_star),
    pat("morning_doji_star", 3, BULL, REV, morning_doji_star),
    pat("evening_doji_star", 3, BEAR, REV, evening_doji_star),
    pat("abandoned_baby_bull", 3, BULL, REV, abandoned_baby_bull),
    pat("abandoned_baby_bear", 3, BEAR, REV, abandoned_baby_bear),
    pat("three_white_soldiers", 3, BULL, REV, three_white_soldiers),
    pat("three_black_crows", 3, BEAR, REV, three_black_crows),
    pat("identical_three_crows", 3, BEAR, REV, identical_three_crows),
    pat("three_inside_up", 3, BULL, REV, three_inside_up),
    pat("three_inside_down", 3, BEAR, REV, three_inside_down),
    pat("three_outside_up", 3, BULL, REV, three_outside_up),
    pat("three_outside_down", 3, BEAR, REV, three_outside_down),
    pat("upside_tasuki_gap", 3, BULL, CONT, upside_tasuki_gap),
    pat("downside_tasuki_gap", 3, BEAR, CONT, downside_tasuki_gap),
    pat("stick_sandwich", 3, BULL, REV, stick_sandwich),
    pat("unique_three_river", 3, BULL, REV, unique_three_river),
    pat("tri_star_bull", 3, BULL, REV, tri_star_bull),
    pat("tri_star_bear", 3, BEAR, REV, tri_star_bear),
    pat("two_crows", 3, BEAR, REV, two_crows),
    pat("upside_gap_two_crows", 3, BEAR, REV, upside_gap_two_crows),
    pat("advance_block", 3, BEAR, REV, advance_block),
    pat("deliberation", 3, BEAR, REV, deliberation),
    // four and five bars
    pat("three_line_strike_bull", 4, BULL, CONT, three_line_strike_bull),
    pat("three_line_strike_bear", 4, BEAR, CONT, three_line_strike_bear),
    pat("rising_three_methods", 5, BULL, CONT, rising_three_methods),
    pat("falling_three_methods", 5, BEAR, CONT, falling_three_methods),
    pat("ladder_bottom", 5, BULL, REV, ladder_bottom),
];

/// The bullish patterns, in registry order.
pub fn bullish() -> impl Iterator<Item = &'static Pattern> {
    PATTERNS.iter().filter(|p| p.direction == BULL)
}

/// The bearish patterns, in registry order.
pub fn bearish() -> impl Iterator<Item = &'static Pattern> {
    PATTERNS.iter().filter(|p| p.direction == BEAR)
}
