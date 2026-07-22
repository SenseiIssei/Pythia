//! Polymarket CLOB connector (Phase 2).
//!
//! Real implementation notes:
//!   · Market data:  GET https://clob.polymarket.com/markets  (+ Gamma API for metadata)
//!   · Auth:         EIP-712 signed L2 headers derived from a Polygon private key
//!   · Settlement:   USDC on Polygon; outcome tokens priced 0..1 = implied probability
//!   · ⚠ Geoblocked for US persons — see SAFETY.md. Legality is the operator's responsibility.
//!
//! Fails closed: with no configured key, `is_live_ready` is false and every
//! order attempt returns `NotConfigured`, so nothing can leak to the venue.

use super::{ConnectorError, Fill, Market, MarketConnector, OrderRequest, Venue};
use async_trait::async_trait;

#[derive(Default)]
pub struct PolymarketConnector {
    private_key: Option<String>, // loaded from the OS keychain, never from code
}

impl PolymarketConnector {
    pub fn new(private_key: Option<String>) -> Self {
        Self { private_key }
    }
}

#[async_trait]
impl MarketConnector for PolymarketConnector {
    fn venue(&self) -> Venue {
        Venue::Polymarket
    }

    fn is_live_ready(&self) -> bool {
        self.private_key.is_some()
    }

    async fn list_markets(&self) -> Result<Vec<Market>, ConnectorError> {
        // Read-only; safe without keys. TODO: fetch from CLOB/Gamma.
        Err(ConnectorError::Unimplemented("polymarket::list_markets"))
    }

    async fn place_order(&self, _req: OrderRequest) -> Result<Fill, ConnectorError> {
        if self.private_key.is_none() {
            return Err(ConnectorError::NotConfigured("polymarket".into()));
        }
        Err(ConnectorError::Unimplemented("polymarket::place_order"))
    }

    async fn cancel_order(&self, _order_id: &str) -> Result<(), ConnectorError> {
        Err(ConnectorError::Unimplemented("polymarket::cancel_order"))
    }
}
