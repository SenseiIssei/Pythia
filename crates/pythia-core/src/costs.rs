//! The cost model: what a trade costs before it has made a cent.
//!
//! A backtest that ignores costs is a random-number generator with a nice
//! chart. This module is the single answer to "what does one side of one order
//! cost here?", used by the paper fill, the research backtester, the validation
//! gates and the realised-slippage comparison. Nothing else in the crate is
//! allowed to invent a cost number.
//!
//! ## Where the numbers live
//!
//! In `config/costs.json` at the repo root, not in this file. The JSON is
//! embedded at build time with `include_str!`, so a binary always has sane
//! defaults, and it can be replaced at runtime with [`install`] or
//! [`load_file`], so recalibrating does not need a rebuild. The Python research
//! lab and the TypeScript paper engine read the same file, which keeps the three
//! from drifting apart.
//!
//! The shipped numbers are defaults from public fee schedules and typical quoted
//! spreads. They are meant to be calibrated from recorded data (Pythia's own
//! realised slippage, recorded order books), not trusted as measurements.
//!
//! ## The model, per side
//!
//! ```text
//!   fee         taker_bps (crossing) or maker_bps (resting)
//!   spread      half_spread_bps            paid by a taker, against the mid
//!   impact      impact_coeff * sqrt(notional / depth)
//! ```
//!
//! `depth` is the top-of-book depth in quote currency on the side the order
//! takes. When no live book is available the venue's `default_depth` stands in.
//! The square root is the empirical square-root law of market impact: doubling
//! the size does not double the impact, but it never makes it free either. At
//! `notional == depth` the impact is exactly `impact_coeff` bps.
//!
//! A round trip is two taker sides. Shorts additionally pay
//! `borrow_bps_yr` pro rata for as long as they are held.

use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
use std::sync::{Arc, OnceLock, RwLock};

/// The defaults, embedded at build time. See the module docs.
const EMBEDDED: &str = include_str!("../../../config/costs.json");

/// Every venue the cost table knows. Crypto venues are separate entries because
/// Kraken's 40 bps taker fee and Binance's 10 bps are not the same strategy.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum CostVenue {
    Kraken,
    Binance,
    Bybit,
    Okx,
    Coinbase,
    Alpaca,
    Polymarket,
}

impl CostVenue {
    pub const ALL: [CostVenue; 7] = [
        CostVenue::Kraken,
        CostVenue::Binance,
        CostVenue::Bybit,
        CostVenue::Okx,
        CostVenue::Coinbase,
        CostVenue::Alpaca,
        CostVenue::Polymarket,
    ];

    /// The key this venue has in `config/costs.json`.
    pub fn id(self) -> &'static str {
        match self {
            CostVenue::Kraken => "kraken",
            CostVenue::Binance => "binance",
            CostVenue::Bybit => "bybit",
            CostVenue::Okx => "okx",
            CostVenue::Coinbase => "coinbase",
            CostVenue::Alpaca => "alpaca",
            CostVenue::Polymarket => "polymarket",
        }
    }

    pub fn parse(s: &str) -> Option<CostVenue> {
        let s = s.trim().to_ascii_lowercase();
        CostVenue::ALL.into_iter().find(|v| v.id() == s)
    }

    /// The cost venue for an engine venue. `Venue::Crypto` is exchange-agnostic
    /// in the engine, so the caller says which exchange executes; Kraken, the
    /// exchange the price feed comes from, when it does not know.
    pub fn for_venue(venue: crate::connectors::Venue, exchange: Option<CostVenue>) -> CostVenue {
        match venue {
            crate::connectors::Venue::Alpaca => CostVenue::Alpaca,
            crate::connectors::Venue::Polymarket => CostVenue::Polymarket,
            crate::connectors::Venue::Crypto => exchange.unwrap_or(CostVenue::Kraken),
        }
    }

    /// The cost venue for a configured crypto exchange.
    pub fn for_exchange(ex: crate::connectors::cex::Exchange) -> CostVenue {
        use crate::connectors::cex::Exchange;
        match ex {
            Exchange::Kraken => CostVenue::Kraken,
            Exchange::Binance => CostVenue::Binance,
            Exchange::Bybit => CostVenue::Bybit,
            Exchange::Okx => CostVenue::Okx,
            Exchange::Coinbase => CostVenue::Coinbase,
        }
    }
}

/// Which side of the book an order takes.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Liquidity {
    /// Crosses the spread: pays the taker fee, the half-spread and impact.
    Taker,
    /// Rests and gets filled: pays only the maker fee.
    Maker,
}

/// Costs for one instrument on one venue. All `*_bps` fields are basis points.
#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct CostModel {
    /// Fee for an order that crosses the spread.
    pub taker_bps: f64,
    /// Fee for an order that rests and is filled.
    pub maker_bps: f64,
    /// Half the quoted spread, per side: what a taker pays against the mid.
    pub half_spread_bps: f64,
    /// Impact in bps when the order's notional equals the top-of-book depth;
    /// scaled by `sqrt(notional / depth)` otherwise.
    pub impact_coeff: f64,
    /// Annual borrow cost for a short, in bps per year.
    pub borrow_bps_yr: f64,
    /// Smallest order the venue accepts, in quote currency (approximate).
    pub min_notional: f64,
    /// Top-of-book depth (quote currency) assumed when no live book is known.
    #[serde(default)]
    pub default_depth: f64,
}

impl CostModel {
    /// No costs at all. For isolating how much of a result the cost model is.
    pub const FREE: CostModel = CostModel {
        taker_bps: 0.0,
        maker_bps: 0.0,
        half_spread_bps: 0.0,
        impact_coeff: 0.0,
        borrow_bps_yr: 0.0,
        min_notional: 0.0,
        default_depth: 0.0,
    };

    /// Market impact for one order, in bps.
    ///
    /// `depth` is the live top-of-book depth on the side the order takes, in
    /// quote currency. `None` (or a non-positive value) falls back to
    /// `default_depth`; with neither, impact is unknown and reported as zero
    /// rather than guessed twice.
    pub fn impact_bps(&self, notional: f64, depth: Option<f64>) -> f64 {
        let depth = depth.filter(|d| *d > 0.0).unwrap_or(self.default_depth);
        if depth <= 0.0 || notional <= 0.0 || self.impact_coeff <= 0.0 {
            return 0.0;
        }
        self.impact_coeff * (notional / depth).sqrt()
    }

    /// Price slippage for one aggressive side, in bps: half-spread plus impact.
    /// This is what a fill loses against the arrival price, before fees, and
    /// it is the number realised slippage is compared against.
    pub fn slippage_bps(&self, notional: f64, depth: Option<f64>) -> f64 {
        self.half_spread_bps + self.impact_bps(notional, depth)
    }

    /// Fee for one side.
    pub fn fee_bps(&self, liquidity: Liquidity) -> f64 {
        match liquidity {
            Liquidity::Taker => self.taker_bps,
            Liquidity::Maker => self.maker_bps,
        }
    }

    /// All-in cost of one side, in bps.
    pub fn side_cost_bps(&self, notional: f64, depth: Option<f64>, liquidity: Liquidity) -> f64 {
        match liquidity {
            Liquidity::Taker => self.taker_bps + self.slippage_bps(notional, depth),
            // A resting order is the spread, not a payer of it. Impact is also
            // not charged: a passive fill is someone else crossing into it.
            Liquidity::Maker => self.maker_bps,
        }
    }

    /// Expected cost of a full round trip (in and out, both crossing), in bps
    /// of the notional. This is the bar a single trade has to clear.
    pub fn round_trip_bps(&self, notional: f64, depth: Option<f64>) -> f64 {
        2.0 * self.side_cost_bps(notional, depth, Liquidity::Taker)
    }

    /// Borrow cost of holding a short for `days`, in bps.
    pub fn borrow_bps(&self, days: f64) -> f64 {
        self.borrow_bps_yr * days.max(0.0) / 365.0
    }

    /// Every cost component multiplied by `k`. Used by the cost-sensitivity
    /// gate: a strategy that dies at 2x costs dies live.
    pub fn scaled(&self, k: f64) -> CostModel {
        let k = k.max(0.0);
        CostModel {
            taker_bps: self.taker_bps * k,
            maker_bps: self.maker_bps * k,
            half_spread_bps: self.half_spread_bps * k,
            impact_coeff: self.impact_coeff * k,
            borrow_bps_yr: self.borrow_bps_yr * k,
            ..*self
        }
    }
}

/// A per-instrument override. Every field is optional; anything left out falls
/// through to the venue default.
#[derive(Debug, Clone, Copy, Default, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct CostOverride {
    pub taker_bps: Option<f64>,
    pub maker_bps: Option<f64>,
    pub half_spread_bps: Option<f64>,
    pub impact_coeff: Option<f64>,
    pub borrow_bps_yr: Option<f64>,
    pub min_notional: Option<f64>,
    pub default_depth: Option<f64>,
}

impl CostOverride {
    fn apply(&self, m: CostModel) -> CostModel {
        CostModel {
            taker_bps: self.taker_bps.unwrap_or(m.taker_bps),
            maker_bps: self.maker_bps.unwrap_or(m.maker_bps),
            half_spread_bps: self.half_spread_bps.unwrap_or(m.half_spread_bps),
            impact_coeff: self.impact_coeff.unwrap_or(m.impact_coeff),
            borrow_bps_yr: self.borrow_bps_yr.unwrap_or(m.borrow_bps_yr),
            min_notional: self.min_notional.unwrap_or(m.min_notional),
            default_depth: self.default_depth.unwrap_or(m.default_depth),
        }
    }
}

/// One venue's entry in the cost file.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct VenueCosts {
    #[serde(default)]
    pub label: String,
    #[serde(flatten)]
    pub model: CostModel,
    /// Keyed by base asset (`BTC`) or ticker (`AAPL`); a full symbol
    /// (`BTC/USD`) also works and wins over the base asset.
    #[serde(default)]
    pub symbols: BTreeMap<String, CostOverride>,
}

/// The whole cost file.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct CostTable {
    #[serde(default)]
    pub version: u32,
    pub venues: BTreeMap<String, VenueCosts>,
}

/// Used only for a venue the table does not list. Deliberately expensive: an
/// unknown venue should look costly, never free.
const UNKNOWN_VENUE: CostModel = CostModel {
    taker_bps: 50.0,
    maker_bps: 30.0,
    half_spread_bps: 25.0,
    impact_coeff: 25.0,
    borrow_bps_yr: 100.0,
    min_notional: 10.0,
    default_depth: 10_000.0,
};

impl CostTable {
    /// Parse a cost file. Refuses a table with a negative cost anywhere, which
    /// would make trading look like it pays.
    pub fn parse(json: &str) -> Result<CostTable, String> {
        let t: CostTable = serde_json::from_str(json).map_err(|e| format!("cost table: {e}"))?;
        for (venue, v) in &t.venues {
            check(venue, &v.model)?;
            for (sym, o) in &v.symbols {
                check(&format!("{venue}/{sym}"), &o.apply(v.model))?;
            }
        }
        Ok(t)
    }

    /// The model for one instrument on one venue.
    pub fn model_for(&self, venue: CostVenue, symbol: &str) -> CostModel {
        let Some(v) = self.venues.get(venue.id()) else { return UNKNOWN_VENUE };
        let sym = symbol.trim().to_ascii_uppercase();
        let base = sym.split(['/', '-']).next().unwrap_or(&sym).to_string();
        let ov = v.symbols.get(&sym).or_else(|| v.symbols.get(&base));
        match ov {
            Some(o) => o.apply(v.model),
            None => v.model,
        }
    }

    /// The venue-level default, ignoring per-symbol overrides.
    pub fn venue_model(&self, venue: CostVenue) -> CostModel {
        self.venues.get(venue.id()).map(|v| v.model).unwrap_or(UNKNOWN_VENUE)
    }
}

fn check(what: &str, m: &CostModel) -> Result<(), String> {
    let fields = [
        ("takerBps", m.taker_bps),
        ("makerBps", m.maker_bps),
        ("halfSpreadBps", m.half_spread_bps),
        ("impactCoeff", m.impact_coeff),
        ("borrowBpsYr", m.borrow_bps_yr),
        ("minNotional", m.min_notional),
        ("defaultDepth", m.default_depth),
    ];
    for (name, v) in fields {
        if !v.is_finite() || v < 0.0 {
            return Err(format!("cost table: {what}.{name} = {v} must be a finite number >= 0"));
        }
    }
    Ok(())
}

/// The table compiled into this binary.
pub fn embedded() -> CostTable {
    CostTable::parse(EMBEDDED).expect("config/costs.json must parse; a unit test guards this")
}

fn slot() -> &'static RwLock<Arc<CostTable>> {
    static SLOT: OnceLock<RwLock<Arc<CostTable>>> = OnceLock::new();
    SLOT.get_or_init(|| RwLock::new(Arc::new(embedded())))
}

/// The table in force right now: the embedded defaults unless a host
/// installed an override.
pub fn table() -> Arc<CostTable> {
    slot().read().map(|t| t.clone()).unwrap_or_else(|p| p.into_inner().clone())
}

/// Replace the table in force. Takes effect on the next fill or backtest.
pub fn install(table: CostTable) {
    match slot().write() {
        Ok(mut t) => *t = Arc::new(table),
        Err(p) => *p.into_inner() = Arc::new(table),
    }
}

/// Load and install a cost file, typically the repo's own `config/costs.json`
/// after it has been recalibrated. On error the table in force is unchanged.
pub fn load_file(path: &std::path::Path) -> Result<(), String> {
    let raw = std::fs::read_to_string(path).map_err(|e| format!("{}: {e}", path.display()))?;
    install(CostTable::parse(&raw)?);
    Ok(())
}

/// Shorthand for `table().model_for(venue, symbol)`.
pub fn model_for(venue: CostVenue, symbol: &str) -> CostModel {
    table().model_for(venue, symbol)
}

/// Gross, costs and net for one result, as three separate figures.
///
/// The decomposition always adds up: `net = gross - costs`. A strategy whose
/// costs eat a large share of its gross is a costs discovery, not a strategy
/// that needs tuning, so [`PnlBreakdown::cost_heavy`] flags it.
#[derive(Debug, Clone, Copy, Default, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct PnlBreakdown {
    /// What the trades made at reference prices with no fees, spread or impact.
    pub gross: f64,
    /// Fees plus slippage. Negative only when fills beat their reference
    /// price by more than the fees, which live limit orders can do.
    pub costs: f64,
    /// `gross - costs`.
    pub net: f64,
    /// `costs / gross` when gross is positive; `None` when there was no gross
    /// profit for costs to be a share of.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub cost_share: Option<f64>,
    /// Costs exceed [`COST_HEAVY_SHARE`] of gross, or there was no gross
    /// profit and costs were paid anyway.
    pub cost_heavy: bool,
}

/// Above this share of gross, costs are the story. `PROFIT-PLAN.md` §1.
pub const COST_HEAVY_SHARE: f64 = 0.40;

impl PnlBreakdown {
    pub fn new(gross: f64, costs: f64) -> PnlBreakdown {
        // Clean float noise to exactly zero, but never clamp a real negative:
        // the three figures must add up.
        let costs = if costs.abs() < 1e-12 { 0.0 } else { costs };
        let cost_share = (gross > 0.0).then(|| costs / gross);
        let cost_heavy = match cost_share {
            Some(s) => s > COST_HEAVY_SHARE,
            None => costs > 0.0,
        };
        PnlBreakdown { gross, costs, net: gross - costs, cost_share, cost_heavy }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_shipped_cost_file_parses_and_covers_every_venue() {
        let t = embedded();
        for v in CostVenue::ALL {
            assert!(t.venues.contains_key(v.id()), "config/costs.json is missing {}", v.id());
        }
    }

    #[test]
    fn the_shipped_fees_match_the_public_schedules() {
        let t = embedded();
        let k = t.venue_model(CostVenue::Kraken);
        assert_eq!((k.taker_bps, k.maker_bps), (40.0, 25.0), "Kraken lowest tier");
        let b = t.venue_model(CostVenue::Binance);
        assert_eq!((b.taker_bps, b.maker_bps), (10.0, 10.0));
        let y = t.venue_model(CostVenue::Bybit);
        assert_eq!((y.taker_bps, y.maker_bps), (10.0, 10.0));
        let o = t.venue_model(CostVenue::Okx);
        assert_eq!((o.taker_bps, o.maker_bps), (10.0, 8.0));
        let a = t.venue_model(CostVenue::Alpaca);
        assert_eq!((a.taker_bps, a.maker_bps), (0.0, 0.0), "equities are commission-free");
    }

    #[test]
    fn majors_are_cheaper_to_cross_than_alts_and_binance_tighter_than_kraken() {
        let t = embedded();
        let k_btc = t.model_for(CostVenue::Kraken, "BTC/USD");
        let k_alt = t.model_for(CostVenue::Kraken, "DOT/USD");
        let b_btc = t.model_for(CostVenue::Binance, "BTC/USD");
        assert!(k_btc.half_spread_bps < k_alt.half_spread_bps);
        assert!(b_btc.half_spread_bps < k_btc.half_spread_bps);
        assert!((1.0..=2.0).contains(&b_btc.half_spread_bps), "Binance majors ~1-2 bps");
        assert!((2.0..=5.0).contains(&k_btc.half_spread_bps), "Kraken majors ~2-5 bps");
        // An instrument nobody listed gets the venue default, which is the alt level.
        let unknown = t.model_for(CostVenue::Kraken, "PEPE/USD");
        assert_eq!(unknown.half_spread_bps, t.venue_model(CostVenue::Kraken).half_spread_bps);
    }

    #[test]
    fn overrides_match_full_symbols_and_base_assets_case_insensitively() {
        let t = embedded();
        let a = t.model_for(CostVenue::Kraken, "btc/usd");
        let b = t.model_for(CostVenue::Kraken, "BTC");
        assert_eq!(a, b);
        // Unchanged fields fall through to the venue.
        assert_eq!(a.taker_bps, 40.0);
    }

    #[test]
    fn impact_follows_the_square_root_law() {
        let m = CostModel { impact_coeff: 10.0, default_depth: 100_000.0, ..CostModel::FREE };
        assert!((m.impact_bps(100_000.0, None) - 10.0).abs() < 1e-9, "at notional == depth it is the coefficient");
        let quarter = m.impact_bps(25_000.0, None);
        assert!((quarter - 5.0).abs() < 1e-9, "a quarter of the depth costs half: {quarter}");
        // A live book overrides the default depth.
        assert!((m.impact_bps(100_000.0, Some(400_000.0)) - 5.0).abs() < 1e-9);
        // With no depth information at all, impact is unknown, not invented.
        let blind = CostModel { impact_coeff: 10.0, ..CostModel::FREE };
        assert_eq!(blind.impact_bps(1e6, None), 0.0);
    }

    #[test]
    fn a_round_trip_is_two_taker_sides() {
        let m = CostModel {
            taker_bps: 10.0,
            maker_bps: 2.0,
            half_spread_bps: 3.0,
            impact_coeff: 4.0,
            default_depth: 10_000.0,
            ..CostModel::FREE
        };
        // notional == depth: 10 fee + 3 spread + 4 impact per side.
        assert!((m.round_trip_bps(10_000.0, None) - 34.0).abs() < 1e-9);
        assert_eq!(m.side_cost_bps(10_000.0, None, Liquidity::Maker), 2.0, "a resting fill pays only its fee");
    }

    #[test]
    fn scaling_multiplies_costs_but_not_venue_facts() {
        let m = embedded().model_for(CostVenue::Kraken, "BTC/USD");
        let x2 = m.scaled(2.0);
        assert!((x2.round_trip_bps(1000.0, None) - 2.0 * m.round_trip_bps(1000.0, None)).abs() < 1e-9);
        assert_eq!(x2.min_notional, m.min_notional);
        assert_eq!(x2.default_depth, m.default_depth);
        assert_eq!(m.scaled(0.0).round_trip_bps(1e6, None), 0.0);
    }

    #[test]
    fn borrow_accrues_pro_rata() {
        let m = CostModel { borrow_bps_yr: 365.0, ..CostModel::FREE };
        assert!((m.borrow_bps(10.0) - 10.0).abs() < 1e-9);
        assert_eq!(m.borrow_bps(-3.0), 0.0);
    }

    #[test]
    fn a_negative_cost_is_refused_rather_than_making_trading_pay() {
        let bad = r#"{"venues":{"x":{"takerBps":-1,"makerBps":0,"halfSpreadBps":0,"impactCoeff":0,"borrowBpsYr":0,"minNotional":0}}}"#;
        assert!(CostTable::parse(bad).is_err());
        let bad_override = r#"{"venues":{"x":{"takerBps":1,"makerBps":0,"halfSpreadBps":0,"impactCoeff":0,"borrowBpsYr":0,"minNotional":0,"symbols":{"BTC":{"halfSpreadBps":-2}}}}}"#;
        assert!(CostTable::parse(bad_override).is_err());
    }

    #[test]
    fn an_unknown_venue_is_expensive_not_free() {
        let t = CostTable { version: 1, venues: BTreeMap::new() };
        assert!(t.model_for(CostVenue::Binance, "BTC").round_trip_bps(1000.0, None) > 100.0);
    }

    #[test]
    fn crypto_resolves_to_the_configured_exchange() {
        use crate::connectors::Venue;
        assert_eq!(CostVenue::for_venue(Venue::Crypto, None), CostVenue::Kraken);
        assert_eq!(CostVenue::for_venue(Venue::Crypto, Some(CostVenue::Binance)), CostVenue::Binance);
        assert_eq!(CostVenue::for_venue(Venue::Alpaca, Some(CostVenue::Binance)), CostVenue::Alpaca);
        assert_eq!(CostVenue::parse(" OKX "), Some(CostVenue::Okx));
    }

    #[test]
    fn the_breakdown_always_adds_up_and_flags_cost_heavy_results() {
        let ok = PnlBreakdown::new(100.0, 30.0);
        assert_eq!(ok.net, 70.0);
        assert!(!ok.cost_heavy);
        let heavy = PnlBreakdown::new(100.0, 41.0);
        assert!(heavy.cost_heavy, "41% of gross is over the 40% line");
        let losing = PnlBreakdown::new(-5.0, 10.0);
        assert_eq!(losing.net, -15.0);
        assert!(losing.cost_share.is_none());
        assert!(losing.cost_heavy, "paying costs on no gross profit is the worst case");
        assert!(!PnlBreakdown::new(0.0, 0.0).cost_heavy);
        // Fills better than reference: negative costs, still adding up.
        let improved = PnlBreakdown::new(10.0, -1.0);
        assert_eq!(improved.net, 11.0);
        assert!(!improved.cost_heavy);
    }

    #[test]
    fn the_breakdown_serialises_in_camel_case() {
        let v = serde_json::to_value(PnlBreakdown::new(10.0, 5.0)).unwrap();
        assert!(v.get("costShare").is_some());
        assert!(v.get("costHeavy").is_some());
        assert!(v.get("cost_heavy").is_none());
    }
}
