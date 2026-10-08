//! Venue connectors. Every venue — Polymarket, a crypto exchange, Alpaca —
//! implements the same [`MarketConnector`] trait so the strategy engine and
//! order router are venue-agnostic. The [`paper::PaperConnector`] is the
//! reference implementation and the default in paper mode.
//!
//! ## The order lifecycle contract
//!
//! An earlier version of this trait had a single `place_order` that submitted an
//! order and then *blocked* until it filled. That is wrong for a real broker:
//! a market order outside regular trading hours does not fill for hours, so the
//! caller either blocks the whole engine or gives up — and giving up while the
//! order is still working at the venue is how a bot ends up with a position it
//! does not know about.
//!
//! So the contract is split into three fast, non-blocking calls:
//!
//! 1. [`MarketConnector::submit_order`] — POST and return the broker's order id.
//! 2. [`MarketConnector::order_status`] — poll it, as often as you like.
//! 3. [`MarketConnector::cancel_order`] — give up *at the venue*, not just locally.
//!
//! The engine drives that state machine across ticks and only ever books a fill
//! the broker has actually reported. Positions can no longer drift.

pub mod alpaca;
pub mod cex;
pub mod paper;
pub mod polymarket;
pub mod sign;

use async_trait::async_trait;
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq, Hash)]
#[serde(rename_all = "lowercase")]
pub enum Venue {
    Polymarket,
    Crypto,
    Alpaca,
}

impl Venue {
    /// The vault / settings key this venue's credentials live under.
    pub fn key(self) -> &'static str {
        match self {
            Venue::Polymarket => "polymarket",
            Venue::Crypto => "crypto",
            Venue::Alpaca => "alpaca",
        }
    }
}

/// Which of a venue's two worlds a connector talks to.
///
/// `Live` is the real account with real money. `Demo` is the venue's own
/// demo or paper environment: the same API shape, a separate host (or a
/// header), separate keys and virtual funds. Every connector holds exactly one
/// environment and the keys that belong to it, so a live key can never be
/// sent to a demo host and a demo key never reaches the live one. See
/// `docs/DEMO.md` for which venues have a demo environment and how honest its
/// prices are.
#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq, Hash, Default)]
#[serde(rename_all = "lowercase")]
pub enum Environment {
    #[default]
    Live,
    Demo,
}

impl Environment {
    pub fn as_str(self) -> &'static str {
        match self {
            Environment::Live => "live",
            Environment::Demo => "demo",
        }
    }

    pub fn is_demo(self) -> bool {
        self == Environment::Demo
    }
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
pub enum Side {
    Buy,
    Sell,
}

impl Side {
    pub fn as_str(self) -> &'static str {
        match self {
            Side::Buy => "buy",
            Side::Sell => "sell",
        }
    }
    /// +1 for a buy, -1 for a sell — handy for signed quantities.
    pub fn sign(self) -> f64 {
        match self {
            Side::Buy => 1.0,
            Side::Sell => -1.0,
        }
    }
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
pub enum OrderType {
    Market,
    Limit,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Market {
    pub id: String,
    pub venue: Venue,
    pub symbol: String,
    /// For prediction markets this is the implied probability (0..1);
    /// for crypto/equity it is the last trade price.
    pub price: f64,
    pub updated_at: i64,
}

/// One order as the engine wants it placed. `symbol` is the *venue's* symbol
/// (e.g. `AAPL`, `XBTUSD`), not Pythia's market id.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OrderRequest {
    pub symbol: String,
    pub side: Side,
    pub order_type: OrderType,
    pub qty: f64,
    pub limit_price: Option<f64>,
    /// Last known price, for preflight maths (buying power, notional minimums).
    /// Not sent to the venue — a market order carries no price.
    pub ref_price: Option<f64>,
    /// Our own id, echoed back by the venue. Makes submission idempotent: if a
    /// response is lost in flight we can look the order up instead of resending.
    pub client_order_id: Option<String>,
    /// This order closes an existing position and must never flip it long/short.
    pub reduce_only: bool,
}

impl OrderRequest {
    pub fn market(symbol: impl Into<String>, side: Side, qty: f64) -> Self {
        Self {
            symbol: symbol.into(),
            side,
            order_type: OrderType::Market,
            qty,
            limit_price: None,
            ref_price: None,
            client_order_id: None,
            reduce_only: false,
        }
    }

    /// Notional value this order commits, as far as we can tell before it fills.
    pub fn notional(&self) -> Option<f64> {
        self.limit_price.or(self.ref_price).map(|p| p * self.qty)
    }
}

/// Where a submitted order stands at the venue. Every connector maps its own
/// vocabulary onto this so the engine has one state machine, not five.
#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
pub enum BrokerOrderStatus {
    /// Accepted, resting, nothing filled yet (new / accepted / pending_new / open).
    Working,
    PartiallyFilled,
    Filled,
    Canceled,
    Rejected,
    Expired,
}

impl BrokerOrderStatus {
    /// True once the venue will never fill any more of this order.
    pub fn is_terminal(self) -> bool {
        matches!(
            self,
            BrokerOrderStatus::Filled
                | BrokerOrderStatus::Canceled
                | BrokerOrderStatus::Rejected
                | BrokerOrderStatus::Expired
        )
    }
}

/// A venue's view of one order. `filled_qty`/`avg_price` are cumulative, which
/// is what every venue reports and what makes partial fills easy to book: the
/// engine settles the delta against what it has already recorded.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct BrokerOrder {
    pub id: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub client_order_id: Option<String>,
    pub status: BrokerOrderStatus,
    pub filled_qty: f64,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub avg_price: Option<f64>,
    /// Cumulative fees/commission charged so far, valued in the quote
    /// currency. A fee the venue took in the coin itself is included here at
    /// the fill price (and its coins are in `fee_base`).
    pub fee: f64,
    /// The part of the fee charged in the base coin, in coins. On a spot buy
    /// Bybit, OKX and Binance take their fee out of the coin bought, so the
    /// account receives `filled_qty - fee_base`: that is the position, not
    /// `filled_qty`. Zero when every fee was charged in the quote currency.
    #[serde(default)]
    pub fee_base: f64,
    /// Fees charged in a third asset the connector cannot price (Binance's
    /// BNB discount), as (asset, amount). Not in `fee`; the engine values
    /// them from its own prices when it can and journals them when it cannot.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub fee_unpriced: Vec<(String, f64)>,
    /// The venue's own status string, kept for the journal so a surprising
    /// rejection is debuggable without reading our mapping code.
    pub raw_status: String,
}

impl BrokerOrder {
    /// A submission the venue accepted and has not filled any of yet.
    pub fn acknowledged(id: impl Into<String>, client_order_id: Option<String>) -> Self {
        BrokerOrder {
            id: id.into(),
            client_order_id,
            status: BrokerOrderStatus::Working,
            filled_qty: 0.0,
            avg_price: None,
            fee: 0.0,
            fee_base: 0.0,
            fee_unpriced: Vec::new(),
            raw_status: "submitted".into(),
        }
    }
}

/// A position as the *venue* sees it — the ground truth for reconciliation.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct BrokerPosition {
    pub symbol: String,
    /// Signed: positive long, negative short.
    pub qty: f64,
    pub avg_price: f64,
    pub market_value: f64,
}

/// One asset balance at a venue (or on-chain address).
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Balance {
    pub asset: String,
    /// Available to trade / spend right now.
    pub free: f64,
    /// Free + locked in open orders.
    pub total: f64,
    /// Best-effort USD valuation; `None` when we cannot price the asset.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub usd_value: Option<f64>,
}

#[derive(Debug, thiserror::Error)]
pub enum ConnectorError {
    #[error("connector not configured: {0}")]
    NotConfigured(String),
    /// Credentials refused (401/403) — wrong keys, or paper keys against the
    /// live endpoint (or vice-versa). Distinct from a rejected order so the UI
    /// can say something useful.
    #[error("authentication failed — check your keys and the paper/live endpoint ({0})")]
    Auth(String),
    #[error("venue rejected order: {0}")]
    Rejected(String),
    /// The venue would certainly reject this order right now (market closed,
    /// asset not tradable, not enough buying power). Caught *before* submitting
    /// so the journal says why instead of echoing an opaque broker error.
    #[error("{0}")]
    Preflight(String),
    #[error("network error: {0}")]
    Network(String),
    #[error("not yet implemented: {0}")]
    Unimplemented(&'static str),
}

impl ConnectorError {
    /// Whether retrying the same call in a few seconds could plausibly work.
    /// Auth failures and rejections cannot; a dropped connection can.
    pub fn is_transient(&self) -> bool {
        matches!(self, ConnectorError::Network(_))
    }
}

/// The one interface every venue implements. Live connectors talk to real APIs;
/// the paper connector simulates fills against live/replayed prices.
///
/// Implementations must be *fast*: no method may block waiting for a fill. See
/// the module docs for the submit → poll → cancel contract.
#[async_trait]
pub trait MarketConnector: Send + Sync {
    fn venue(&self) -> Venue;

    /// True only when real API keys are present. Until this is true, the order
    /// router refuses to route live orders here — fail closed. Note this is a
    /// *cheap* check: it says keys exist, not that the venue accepted them. Use
    /// [`MarketConnector::verify`] for that.
    fn is_live_ready(&self) -> bool;

    /// Human-readable name for journals and the UI ("Alpaca (paper)", "Kraken").
    fn label(&self) -> String {
        format!("{:?}", self.venue())
    }

    /// Round a quantity to something the venue will accept (lot size, share
    /// precision). Returning 0 means "too small to trade here".
    fn round_qty(&self, qty: f64, _symbol: &str) -> f64 {
        qty
    }

    /// Read-only credential check. Hits the venue's account endpoint, so it also
    /// proves the key/endpoint pairing is right. Called before arming.
    async fn verify(&self) -> Result<String, ConnectorError>;

    /// Read-only market data (safe in any mode).
    async fn list_markets(&self) -> Result<Vec<Market>, ConnectorError> {
        Err(ConnectorError::Unimplemented("list_markets"))
    }

    /// Refuse orders the venue would certainly reject. Cheap and cached where
    /// possible; `Ok(())` means "worth submitting", not "will fill".
    async fn preflight(&self, _req: &OrderRequest) -> Result<(), ConnectorError> {
        Ok(())
    }

    /// Submit an order and return as soon as the venue acknowledges it. MUST NOT
    /// wait for a fill.
    async fn submit_order(&self, req: OrderRequest) -> Result<BrokerOrder, ConnectorError>;

    /// Current state of a previously submitted order. `symbol` is passed back
    /// because most exchanges key their order lookups on (symbol, id) rather
    /// than on the id alone.
    async fn order_status(&self, broker_id: &str, symbol: &str) -> Result<BrokerOrder, ConnectorError>;

    /// Cancel a resting order at the venue. Cancelling an already-terminal order
    /// is not an error.
    async fn cancel_order(&self, broker_id: &str, symbol: &str) -> Result<(), ConnectorError>;

    /// Open positions as the venue sees them — used to reconcile on startup and
    /// after any restart.
    async fn positions(&self) -> Result<Vec<BrokerPosition>, ConnectorError> {
        Ok(vec![])
    }

    /// Cash / asset balances, for the wallet view.
    async fn balances(&self) -> Result<Vec<Balance>, ConnectorError> {
        Ok(vec![])
    }
}

/// Parse a numeric field that a venue may send as a JSON number *or* a string
/// (Alpaca, Kraken and Binance all do the latter for money amounts).
pub(crate) fn num(v: Option<&serde_json::Value>) -> Option<f64> {
    match v? {
        serde_json::Value::Number(n) => n.as_f64(),
        serde_json::Value::String(s) => s.parse::<f64>().ok(),
        _ => None,
    }
}

/// Same, defaulting to 0.0 — for cumulative counters where absent means none.
pub(crate) fn num_or0(v: Option<&serde_json::Value>) -> f64 {
    num(v).unwrap_or(0.0)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn terminal_statuses_stop_the_state_machine() {
        assert!(!BrokerOrderStatus::Working.is_terminal());
        assert!(!BrokerOrderStatus::PartiallyFilled.is_terminal());
        for s in [
            BrokerOrderStatus::Filled,
            BrokerOrderStatus::Canceled,
            BrokerOrderStatus::Rejected,
            BrokerOrderStatus::Expired,
        ] {
            assert!(s.is_terminal(), "{s:?} must be terminal");
        }
    }

    #[test]
    fn numbers_parse_from_json_numbers_and_strings() {
        let v: serde_json::Value = serde_json::json!({"a": 1.5, "b": "2.25", "c": "oops", "d": null});
        assert_eq!(num(v.get("a")), Some(1.5));
        assert_eq!(num(v.get("b")), Some(2.25), "venues quote money as strings");
        assert_eq!(num(v.get("c")), None);
        assert_eq!(num(v.get("d")), None);
        assert_eq!(num(v.get("missing")), None);
        assert_eq!(num_or0(v.get("missing")), 0.0);
    }
}
