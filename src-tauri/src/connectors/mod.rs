//! Venue connectors. Every venue — Polymarket, a crypto exchange, Alpaca —
//! implements the same [`MarketConnector`] trait so the strategy engine and
//! order router are venue-agnostic. The [`paper::PaperConnector`] is the
//! reference implementation and the default in paper mode.

pub mod paper;
pub mod polymarket;
pub mod crypto;
pub mod alpaca;

use async_trait::async_trait;
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq, Hash)]
#[serde(rename_all = "lowercase")]
pub enum Venue {
    Polymarket,
    Crypto,
    Alpaca,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
pub enum Side {
    Buy,
    Sell,
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

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OrderRequest {
    pub market_id: String,
    pub side: Side,
    pub order_type: OrderType,
    pub qty: f64,
    pub limit_price: Option<f64>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Fill {
    pub order_id: String,
    pub market_id: String,
    pub side: Side,
    pub qty: f64,
    pub price: f64,
    pub fee: f64,
    pub ts: i64,
}

#[derive(Debug, thiserror::Error)]
pub enum ConnectorError {
    #[error("connector not configured: {0}")]
    NotConfigured(String),
    #[error("venue rejected order: {0}")]
    Rejected(String),
    #[error("network error: {0}")]
    Network(String),
    #[error("not yet implemented: {0}")]
    Unimplemented(&'static str),
}

/// The one interface every venue implements. Live connectors talk to real APIs;
/// the paper connector simulates fills against live/replayed prices.
#[async_trait]
pub trait MarketConnector: Send + Sync {
    fn venue(&self) -> Venue;

    /// True only when real API keys are present and validated. Until this is
    /// true, the order router refuses to route live orders here — fail closed.
    fn is_live_ready(&self) -> bool;

    /// Read-only market data (safe in any mode).
    async fn list_markets(&self) -> Result<Vec<Market>, ConnectorError>;

    /// Place an order. In paper mode this simulates a fill; in live mode it
    /// hits the venue. The risk manager has already approved by this point.
    async fn place_order(&self, req: OrderRequest) -> Result<Fill, ConnectorError>;

    /// Cancel a resting order by id.
    async fn cancel_order(&self, order_id: &str) -> Result<(), ConnectorError>;
}
