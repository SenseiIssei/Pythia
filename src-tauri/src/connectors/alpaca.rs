//! Alpaca equities connector (Phase 2).
//!
//!   · Paper base:   https://paper-api.alpaca.markets  (start here!)
//!   · Live base:    https://api.alpaca.markets
//!   · Auth:         APCA-API-KEY-ID + APCA-API-SECRET-KEY headers
//!   · Constraints:  US market hours + Pattern Day Trader rules — enforced by the
//!                   risk manager before any order reaches this connector.
//!
//! Fails closed without a configured key id/secret.

use super::{ConnectorError, Fill, Market, MarketConnector, OrderRequest, Venue};
use async_trait::async_trait;

pub struct AlpacaConnector {
    key_id: Option<String>,
    secret: Option<String>,
    /// When true, routes to the paper endpoint even if keys are present.
    paper_endpoint: bool,
}

impl AlpacaConnector {
    pub fn new(key_id: Option<String>, secret: Option<String>, paper_endpoint: bool) -> Self {
        Self { key_id, secret, paper_endpoint }
    }

    fn base_url(&self) -> &'static str {
        if self.paper_endpoint {
            "https://paper-api.alpaca.markets"
        } else {
            "https://api.alpaca.markets"
        }
    }
}

#[async_trait]
impl MarketConnector for AlpacaConnector {
    fn venue(&self) -> Venue {
        Venue::Alpaca
    }

    fn is_live_ready(&self) -> bool {
        self.key_id.is_some() && self.secret.is_some()
    }

    async fn list_markets(&self) -> Result<Vec<Market>, ConnectorError> {
        let _ = self.base_url();
        Err(ConnectorError::Unimplemented("alpaca::list_markets"))
    }

    async fn place_order(&self, _req: OrderRequest) -> Result<Fill, ConnectorError> {
        if !self.is_live_ready() {
            return Err(ConnectorError::NotConfigured("alpaca".into()));
        }
        Err(ConnectorError::Unimplemented("alpaca::place_order"))
    }

    async fn cancel_order(&self, _order_id: &str) -> Result<(), ConnectorError> {
        Err(ConnectorError::Unimplemented("alpaca::cancel_order"))
    }
}
