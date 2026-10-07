//! Live order books for the cost model.
//!
//! `config/costs.json` holds calibrated *medians*: the typical half-spread and
//! the typical depth of each coin's book. A paper fill priced on the median is
//! honest on an average minute and wrong on every other one. When the book is
//! thin (a weekend night, a news spike) a real order pays more, and when it is
//! deep it pays less. This module turns a fresh top-20 snapshot into the two
//! numbers the cost model needs, and decides whether that snapshot may be used
//! at all.
//!
//! ## The definitions, and why they are fixed
//!
//! ```text
//!   half_spread_bps  (best_ask - best_bid) / mid / 2 * 10_000
//!   depth (per side) sum of price * qty over the 20 best levels of that side
//! ```
//!
//! Both are exactly what `research/lab` experiment `costs` measured when it
//! fitted `impactCoeff`. The coefficient only means something against the same
//! depth definition, so a live book with 5 levels or 50 levels would silently
//! mis-price impact. [`BOOK_LEVELS`] is therefore not a tuning knob.
//!
//! A buy takes the asks, a sell takes the bids, so impact uses the depth of the
//! side the order takes, not an average of both.
//!
//! ## Staleness
//!
//! A book is a picture of one moment. One that is older than [`MAX_BOOK_AGE_MS`]
//! says nothing reliable about the next fill, so it is ignored and the
//! calibrated default stands in. Every fill records which of the two it used
//! ([`CostSource`]), so the realised-versus-modelled table can say how much of
//! its "modelled" column came from a live book.

use serde::{Deserialize, Serialize};

use crate::connectors::Side;
use crate::costs::{CostModel, CostVenue};

/// Levels per side that count as depth. Must match the calibration (see the
/// module docs), which used the recorder's depth20 books.
pub const BOOK_LEVELS: usize = 20;

/// Older than this, a book is not used. Hosts poll every 30 s, so a fresh book
/// is at most about 30 s old; one missed poll makes it stale, and the fill
/// falls back to the calibrated default rather than trusting a minute-old book.
pub const MAX_BOOK_AGE_MS: i64 = 60_000;

/// Where the half-spread and depth of one cost estimate came from.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Default, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum CostSource {
    /// The calibrated median from `config/costs.json`. Also what every record
    /// from before live books existed was modelled on, hence the default.
    #[default]
    Default,
    /// A fresh top-20 book from the executing venue.
    Live,
}

impl CostSource {
    pub fn as_str(self) -> &'static str {
        match self {
            CostSource::Default => "default",
            CostSource::Live => "live",
        }
    }
}

/// The cost-relevant summary of one order book snapshot.
#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct BookQuote {
    /// Which exchange the book is from. A Kraken book says nothing about what a
    /// Binance fill costs, so it is only used while that venue executes.
    pub venue: CostVenue,
    pub mid: f64,
    /// Half the quoted spread against the mid, in bps.
    pub half_spread_bps: f64,
    /// Notional (quote currency) on the [`BOOK_LEVELS`] best bids: what a sell
    /// can take.
    pub bid_depth: f64,
    /// Notional on the best asks: what a buy can take.
    pub ask_depth: f64,
    /// When the snapshot was received, epoch millis. Local receipt time rather
    /// than the venue's stamp, because Binance's REST book carries none and the
    /// two must age the same way.
    pub ts: i64,
    /// The levels themselves, best first, so a paper market order can be
    /// filled by walking them (see [`BookQuote::walk`]). Fixed-size, so the
    /// quote stays `Copy`.
    #[serde(default)]
    pub bids: Ladder,
    #[serde(default)]
    pub asks: Ladder,
}

/// Up to [`BOOK_LEVELS`] `(price, qty)` levels of one side, best first.
#[derive(Debug, Clone, Copy, PartialEq, Default, Serialize, Deserialize)]
pub struct Ladder {
    levels: [(f64, f64); BOOK_LEVELS],
    len: u8,
}

impl Ladder {
    /// From levels already sorted best first; anything past
    /// [`BOOK_LEVELS`] is dropped.
    pub fn from_sorted(levels: &[(f64, f64)]) -> Ladder {
        let mut l = Ladder::default();
        for (i, lv) in levels.iter().take(BOOK_LEVELS).enumerate() {
            l.levels[i] = *lv;
            l.len = (i + 1) as u8;
        }
        l
    }

    pub fn levels(&self) -> &[(f64, f64)] {
        &self.levels[..self.len as usize]
    }

    pub fn is_empty(&self) -> bool {
        self.len == 0
    }
}

/// A market order filled against a book, level by level.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct BookWalk {
    /// Volume-weighted price of what the book's levels supplied.
    pub book_vwap: f64,
    /// Quantity the listed levels could supply, at most the order's.
    pub book_qty: f64,
    /// Levels touched, partially or fully.
    pub levels_used: usize,
    /// The order wanted more than the [`BOOK_LEVELS`] levels hold. What is
    /// left over has no price in this snapshot.
    pub exhausted: bool,
    /// Price of the last (worst) level touched.
    pub last_price: f64,
}

impl BookWalk {
    /// The whole order's average price: the walked part at its VWAP and an
    /// exhausted book's remainder at `beyond`, which the caller prices with
    /// the impact model. The remainder is never priced better than the last
    /// level walked: beyond the 20th level the book only gets worse.
    pub fn average_price(&self, qty: f64, side: Side, beyond: f64) -> f64 {
        let qty = qty.abs();
        let rest = (qty - self.book_qty).max(0.0);
        if qty <= 0.0 || rest <= 1e-12 {
            return self.book_vwap;
        }
        let beyond = match side {
            Side::Buy => beyond.max(self.last_price),
            Side::Sell => beyond.min(self.last_price),
        };
        (self.book_vwap * self.book_qty + beyond * rest) / qty
    }
}

impl BookQuote {
    /// Summarise raw levels as `(price, qty)` in any order. Levels beyond the
    /// best [`BOOK_LEVELS`] per side are ignored, as are non-positive or
    /// non-finite ones. `None` for an empty side or a crossed or locked book,
    /// which is a broken snapshot rather than a free trade.
    pub fn from_levels(
        venue: CostVenue,
        bids: &[(f64, f64)],
        asks: &[(f64, f64)],
        ts: i64,
    ) -> Option<BookQuote> {
        let clean = |levels: &[(f64, f64)]| -> Vec<(f64, f64)> {
            levels
                .iter()
                .copied()
                .filter(|(p, q)| p.is_finite() && q.is_finite() && *p > 0.0 && *q > 0.0)
                .collect()
        };
        let mut bids = clean(bids);
        let mut asks = clean(asks);
        bids.sort_by(|a, b| b.0.total_cmp(&a.0));
        asks.sort_by(|a, b| a.0.total_cmp(&b.0));
        bids.truncate(BOOK_LEVELS);
        asks.truncate(BOOK_LEVELS);

        let best_bid = bids.first()?.0;
        let best_ask = asks.first()?.0;
        if best_ask <= best_bid {
            return None;
        }
        let mid = (best_bid + best_ask) / 2.0;
        let notional = |side: &[(f64, f64)]| side.iter().map(|(p, q)| p * q).sum::<f64>();
        Some(BookQuote {
            venue,
            mid,
            half_spread_bps: (best_ask - best_bid) / mid / 2.0 * 10_000.0,
            bid_depth: notional(&bids),
            ask_depth: notional(&asks),
            ts,
            bids: Ladder::from_sorted(&bids),
            asks: Ladder::from_sorted(&asks),
        })
    }

    /// Fill a market order of `qty` (base units) against this snapshot: a buy
    /// lifts the asks from the best up, a sell hits the bids from the best
    /// down, each level at most its listed size. `None` when the side taken
    /// has no levels (a quote built without them) or the size is not
    /// positive.
    pub fn walk(&self, side: Side, qty: f64) -> Option<BookWalk> {
        let ladder = match side {
            Side::Buy => &self.asks,
            Side::Sell => &self.bids,
        };
        if ladder.is_empty() || !(qty > 0.0) || !qty.is_finite() {
            return None;
        }
        let (mut left, mut cost, mut got, mut used, mut last) = (qty, 0.0, 0.0, 0usize, 0.0);
        for &(px, size) in ladder.levels() {
            if left <= 1e-15 {
                break;
            }
            let take = size.min(left);
            cost += take * px;
            got += take;
            left -= take;
            used += 1;
            last = px;
        }
        Some(BookWalk {
            book_vwap: if got > 0.0 { cost / got } else { last },
            book_qty: got,
            levels_used: used,
            exhausted: left > 1e-12 * qty.max(1.0),
            last_price: last,
        })
    }

    /// How far the book's mid sits from `signal`, in bps, signed so that
    /// positive means the market moved against an order on `side` (up for a
    /// buy, down for a sell) between the signal and the book.
    pub fn drift_bps(&self, side: Side, signal: f64) -> Option<f64> {
        if !(signal > 0.0) || !(self.mid > 0.0) {
            return None;
        }
        let raw = (self.mid - signal) / signal * 10_000.0;
        Some(match side {
            Side::Buy => raw,
            Side::Sell => -raw,
        })
    }

    /// Depth on the side an order takes: a buy lifts the asks, a sell hits the
    /// bids.
    pub fn depth_for(&self, side: Side) -> f64 {
        match side {
            Side::Buy => self.ask_depth,
            Side::Sell => self.bid_depth,
        }
    }

    /// Young enough to describe the next fill. A snapshot stamped in the
    /// future (clock skew between hosts) is treated as fresh, not as broken.
    pub fn is_fresh(&self, now: i64) -> bool {
        now - self.ts <= MAX_BOOK_AGE_MS
    }
}

/// One market's book as a feed delivers it, keyed by engine market id
/// (`crypto:BTC/USD`), the same way [`crate::marketdata::BarSeries`] is.
#[derive(Debug, Clone, PartialEq)]
pub struct BookSnapshot {
    pub id: String,
    pub quote: BookQuote,
}

/// The inputs one order's cost estimate actually used.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct ExecCost {
    /// The calibrated model, with the half-spread replaced by the live one when
    /// a fresh book exists. Fees and the impact coefficient are never touched:
    /// they are properties of the venue and the fit, not of this minute.
    pub model: CostModel,
    /// Live depth of the side taken, or `None` for the calibrated default.
    pub depth: Option<f64>,
    pub source: CostSource,
    /// The book itself when `source` is live, for a paper fill to walk.
    pub book: Option<BookQuote>,
}

impl ExecCost {
    /// The calibrated defaults, no live book.
    pub fn calibrated(model: CostModel) -> ExecCost {
        ExecCost { model, depth: None, source: CostSource::Default, book: None }
    }

    /// Model one order against `book` when it is usable: from `venue`, fresh
    /// at `now`, and with depth on the side taken. Anything else falls back to
    /// the calibrated defaults, and says so in `source`.
    pub fn for_order(
        model: CostModel,
        venue: CostVenue,
        book: Option<&BookQuote>,
        side: Side,
        now: i64,
    ) -> ExecCost {
        let Some(b) = book else { return ExecCost::calibrated(model) };
        let depth = b.depth_for(side);
        if b.venue != venue || !b.is_fresh(now) || !(depth > 0.0) || !b.half_spread_bps.is_finite() {
            return ExecCost::calibrated(model);
        }
        ExecCost {
            model: CostModel { half_spread_bps: b.half_spread_bps, ..model },
            depth: Some(depth),
            source: CostSource::Live,
            book: Some(*b),
        }
    }

    /// Expected slippage for one aggressive side of `notional`, in bps.
    pub fn slippage_bps(&self, notional: f64) -> f64 {
        self.model.slippage_bps(notional, self.depth)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const NOW: i64 = 1_790_000_000_000;

    fn model() -> CostModel {
        // Shaped like a calibrated Kraken alt: 1 bp half-spread, 4 bps of
        // impact at the median depth of 40k.
        CostModel {
            taker_bps: 40.0,
            maker_bps: 25.0,
            half_spread_bps: 1.0,
            impact_coeff: 4.0,
            default_depth: 40_000.0,
            ..CostModel::FREE
        }
    }

    /// `n` levels a tick apart around 100.00 / 100.02, `qty` each.
    fn ladder(n: usize, qty: f64) -> (Vec<(f64, f64)>, Vec<(f64, f64)>) {
        let bids = (0..n).map(|i| (100.0 - i as f64 * 0.01, qty)).collect();
        let asks = (0..n).map(|i| (100.02 + i as f64 * 0.01, qty)).collect();
        (bids, asks)
    }

    #[test]
    fn half_spread_is_against_the_mid() {
        let (b, a) = ladder(5, 1.0);
        let q = BookQuote::from_levels(CostVenue::Kraken, &b, &a, NOW).unwrap();
        assert!((q.mid - 100.01).abs() < 1e-9);
        // 0.02 wide around 100.01: 0.01 / 100.01 = 0.99990 bps.
        assert!((q.half_spread_bps - 0.01 / 100.01 * 10_000.0).abs() < 1e-9, "{}", q.half_spread_bps);
    }

    #[test]
    fn depth_is_the_notional_on_the_twenty_best_levels_of_each_side() {
        // 30 levels of 2 coins on each side; only the best 20 count.
        let (b, a) = ladder(30, 2.0);
        let q = BookQuote::from_levels(CostVenue::Binance, &b, &a, NOW).unwrap();
        let want_bid: f64 = (0..20).map(|i| (100.0 - i as f64 * 0.01) * 2.0).sum();
        let want_ask: f64 = (0..20).map(|i| (100.02 + i as f64 * 0.01) * 2.0).sum();
        assert!((q.bid_depth - want_bid).abs() < 1e-6, "{} vs {want_bid}", q.bid_depth);
        assert!((q.ask_depth - want_ask).abs() < 1e-6, "{} vs {want_ask}", q.ask_depth);
        // A buy takes the asks, a sell the bids.
        assert_eq!(q.depth_for(Side::Buy), q.ask_depth);
        assert_eq!(q.depth_for(Side::Sell), q.bid_depth);
    }

    #[test]
    fn the_best_levels_are_chosen_by_price_not_by_arrival_order() {
        // Worst first, and with junk levels mixed in.
        let bids = vec![(99.0, 1.0), (0.0, 5.0), (99.5, 1.0), (f64::NAN, 1.0), (99.9, 1.0), (99.8, -1.0)];
        let asks = vec![(101.0, 1.0), (100.1, 1.0), (100.5, 0.0)];
        let q = BookQuote::from_levels(CostVenue::Kraken, &bids, &asks, NOW).unwrap();
        assert!((q.mid - 100.0).abs() < 1e-9, "best bid 99.9, best ask 100.1: {}", q.mid);
        assert!((q.bid_depth - (99.0 + 99.5 + 99.9)).abs() < 1e-9);
        assert!((q.ask_depth - (101.0 + 100.1)).abs() < 1e-9);
    }

    #[test]
    fn a_crossed_locked_or_one_sided_book_is_refused() {
        let crossed = BookQuote::from_levels(CostVenue::Kraken, &[(100.1, 1.0)], &[(100.0, 1.0)], NOW);
        let locked = BookQuote::from_levels(CostVenue::Kraken, &[(100.0, 1.0)], &[(100.0, 1.0)], NOW);
        let no_asks = BookQuote::from_levels(CostVenue::Kraken, &[(100.0, 1.0)], &[], NOW);
        assert!(crossed.is_none() && locked.is_none() && no_asks.is_none());
    }

    #[test]
    fn a_stale_book_is_ignored_and_the_default_stands_in() {
        let (b, a) = ladder(20, 1.0);
        let old = BookQuote::from_levels(CostVenue::Kraken, &b, &a, NOW - MAX_BOOK_AGE_MS - 1).unwrap();
        assert!(!old.is_fresh(NOW));
        let c = ExecCost::for_order(model(), CostVenue::Kraken, Some(&old), Side::Buy, NOW);
        assert_eq!(c, ExecCost::calibrated(model()));
        assert_eq!(c.source, CostSource::Default);

        let edge = BookQuote { ts: NOW - MAX_BOOK_AGE_MS, ..old };
        assert!(edge.is_fresh(NOW), "exactly at the limit still counts");
        let c = ExecCost::for_order(model(), CostVenue::Kraken, Some(&edge), Side::Buy, NOW);
        assert_eq!(c.source, CostSource::Live);
    }

    #[test]
    fn a_book_from_another_exchange_is_not_used() {
        let (b, a) = ladder(20, 1.0);
        let kraken = BookQuote::from_levels(CostVenue::Kraken, &b, &a, NOW).unwrap();
        let c = ExecCost::for_order(model(), CostVenue::Binance, Some(&kraken), Side::Buy, NOW);
        assert_eq!(c.source, CostSource::Default);
    }

    #[test]
    fn a_thin_live_book_raises_the_modelled_cost_and_a_deep_one_lowers_it() {
        let notional = 2_000.0;
        let calibrated = ExecCost::calibrated(model()).slippage_bps(notional);

        // Thin: 20 levels of 0.5 coin at ~100, about 1k a side against a 40k
        // median, and a spread three times the usual.
        let (b, a) = ladder(20, 0.5);
        let a: Vec<_> = a.into_iter().map(|(p, q)| (p + 0.04, q)).collect();
        let thin = BookQuote::from_levels(CostVenue::Kraken, &b, &a, NOW).unwrap();
        let t = ExecCost::for_order(model(), CostVenue::Kraken, Some(&thin), Side::Buy, NOW);
        assert_eq!(t.source, CostSource::Live);
        assert!(t.model.half_spread_bps > model().half_spread_bps);
        assert!(t.slippage_bps(notional) > calibrated, "{} vs {calibrated}", t.slippage_bps(notional));

        // Deep: 50 coins a level, about 100k a side, same tight spread.
        let (b, a) = ladder(20, 50.0);
        let deep = BookQuote::from_levels(CostVenue::Kraken, &b, &a, NOW).unwrap();
        let d = ExecCost::for_order(model(), CostVenue::Kraken, Some(&deep), Side::Sell, NOW);
        assert!(d.slippage_bps(notional) < calibrated, "{} vs {calibrated}", d.slippage_bps(notional));

        // The fee and the fitted coefficient are the venue's, never the book's.
        assert_eq!(t.model.taker_bps, 40.0);
        assert_eq!(d.model.impact_coeff, 4.0);
    }

    #[test]
    fn the_side_taken_decides_which_depth_prices_impact() {
        // Asks are thin, bids are deep: buying is the expensive direction.
        let bids: Vec<_> = (0..20).map(|i| (100.0 - i as f64 * 0.01, 100.0)).collect();
        let asks: Vec<_> = (0..20).map(|i| (100.02 + i as f64 * 0.01, 0.1)).collect();
        let q = BookQuote::from_levels(CostVenue::Kraken, &bids, &asks, NOW).unwrap();
        let buy = ExecCost::for_order(model(), CostVenue::Kraken, Some(&q), Side::Buy, NOW);
        let sell = ExecCost::for_order(model(), CostVenue::Kraken, Some(&q), Side::Sell, NOW);
        assert!(buy.slippage_bps(5_000.0) > 3.0 * sell.slippage_bps(5_000.0));
    }

    /// Asks 100 / 101 / 102 with 1 / 2 / 3 coins, bids 99 / 98 with 2 / 2.
    fn fixture() -> BookQuote {
        BookQuote::from_levels(
            CostVenue::Binance,
            &[(98.0, 2.0), (99.0, 2.0)],
            &[(102.0, 3.0), (100.0, 1.0), (101.0, 2.0)],
            NOW,
        )
        .unwrap()
    }

    #[test]
    fn a_buy_walks_the_asks_from_the_best_price_up() {
        let q = fixture();
        // 2.5 coins: 1 at 100, 1.5 at 101.
        let w = q.walk(Side::Buy, 2.5).unwrap();
        assert!((w.book_vwap - (100.0 + 1.5 * 101.0) / 2.5).abs() < 1e-12, "{}", w.book_vwap);
        assert_eq!((w.book_qty, w.levels_used, w.exhausted, w.last_price), (2.5, 2, false, 101.0));
        assert_eq!(w.average_price(2.5, Side::Buy, 0.0), w.book_vwap, "nothing beyond the book to price");
        // Exactly the first level.
        let one = q.walk(Side::Buy, 1.0).unwrap();
        assert_eq!((one.book_vwap, one.levels_used), (100.0, 1));
    }

    #[test]
    fn a_sell_walks_the_bids_down_and_running_out_is_flagged() {
        let q = fixture();
        let w = q.walk(Side::Sell, 6.0).unwrap();
        assert!(w.exhausted);
        assert_eq!((w.book_qty, w.levels_used, w.last_price), (4.0, 2, 98.0));
        assert!((w.book_vwap - 98.5).abs() < 1e-12);
        // The 2 coins beyond the book: a model price above the last bid is not
        // believed, the last bid is the best the rest can get.
        let avg = w.average_price(6.0, Side::Sell, 99.5);
        assert!((avg - (98.5 * 4.0 + 98.0 * 2.0) / 6.0).abs() < 1e-12, "{avg}");
        // A worse model price is used as is.
        let avg = w.average_price(6.0, Side::Sell, 90.0);
        assert!((avg - (98.5 * 4.0 + 90.0 * 2.0) / 6.0).abs() < 1e-12, "{avg}");
        // A buy beyond the asks is never cheaper than the last ask.
        let b = q.walk(Side::Buy, 10.0).unwrap();
        assert!(b.exhausted);
        assert!(b.average_price(10.0, Side::Buy, 50.0) >= b.book_vwap);
    }

    #[test]
    fn a_walk_needs_levels_and_a_size() {
        let q = fixture();
        assert!(q.walk(Side::Buy, 0.0).is_none());
        assert!(q.walk(Side::Buy, f64::NAN).is_none());
        let bare = BookQuote { asks: Ladder::default(), ..q };
        assert!(bare.walk(Side::Buy, 1.0).is_none(), "a quote without levels cannot be walked");
        // Only the best 20 levels are kept, best first.
        let many: Vec<_> = (0..30).map(|i| (200.0 - i as f64, 1.0)).collect();
        let asks: Vec<_> = (0..30).map(|i| (201.0 + i as f64, 1.0)).collect();
        let big = BookQuote::from_levels(CostVenue::Kraken, &many, &asks, NOW).unwrap();
        assert_eq!(big.asks.levels().len(), BOOK_LEVELS);
        assert_eq!(big.asks.levels()[0].0, 201.0);
        assert_eq!(big.bids.levels()[0].0, 200.0);
        assert!(big.walk(Side::Buy, 25.0).unwrap().exhausted);
    }

    #[test]
    fn drift_is_signed_against_the_order() {
        let q = fixture(); // mid 99.5
        assert!((q.drift_bps(Side::Buy, 99.0).unwrap() - 0.5 / 99.0 * 10_000.0).abs() < 1e-9, "price rose: a buy pays");
        assert!(q.drift_bps(Side::Sell, 99.0).unwrap() < 0.0, "price rose: a seller gains");
        assert_eq!(q.drift_bps(Side::Buy, 0.0), None);
    }

    #[test]
    fn a_quote_with_levels_still_round_trips_through_json() {
        let q = fixture();
        let back: BookQuote = serde_json::from_str(&serde_json::to_string(&q).unwrap()).unwrap();
        assert_eq!(back, q);
    }

    #[test]
    fn sources_serialise_as_plain_words() {
        assert_eq!(serde_json::to_value(CostSource::Live).unwrap(), "live");
        assert_eq!(serde_json::to_value(CostSource::Default).unwrap(), "default");
        assert_eq!(CostSource::default(), CostSource::Default);
    }
}
