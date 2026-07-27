//! Polymarket CLOB connector.
//!
//!   · Market data:  GET https://clob.polymarket.com/markets  (+ Gamma API for metadata)
//!   · Auth:         EIP-712 signed L2 headers derived from a Polygon private key
//!   · Settlement:   USDC on Polygon; outcome tokens priced 0..1 = implied probability
//!   · ⚠ Geoblocked for US persons — see SAFETY.md. Legality is the operator's responsibility.
//!
//! **Order routing is deliberately not implemented.** Unlike every other venue
//! here, trading Polymarket means holding a Polygon private key that can move
//! USDC directly — a wallet, not a revocable API key. Shipping that behind the
//! same one-click arm flow as a broker key would be a different risk category
//! wearing the same UI. The path to doing it properly (a signer the user
//! approves per session, an allowance cap on the exchange contract, a separate
//! arm gate) is written up in `PROFIT-PLAN.md`.
//!
//! Read-only odds already flow through `marketdata::fetch_polymarket`, so the
//! Prob-Edge strategy works on real prices in paper mode today.

use super::{
    BrokerOrder, ConnectorError, Market, MarketConnector, OrderRequest, Venue,
};
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

    /// Never live: even with a key present, this connector refuses to trade.
    fn is_live_ready(&self) -> bool {
        false
    }

    fn label(&self) -> String {
        "Polymarket (read-only)".into()
    }

    async fn verify(&self) -> Result<String, ConnectorError> {
        if self.private_key.is_none() {
            return Err(ConnectorError::NotConfigured("polymarket".into()));
        }
        Err(ConnectorError::Unimplemented(
            "Polymarket order signing is not wired — odds are read-only, orders stay paper",
        ))
    }

    async fn list_markets(&self) -> Result<Vec<Market>, ConnectorError> {
        // Read-only odds come from `marketdata::fetch_polymarket` (Gamma API).
        Err(ConnectorError::Unimplemented("polymarket::list_markets"))
    }

    async fn submit_order(&self, _req: OrderRequest) -> Result<BrokerOrder, ConnectorError> {
        Err(ConnectorError::Unimplemented("polymarket::submit_order"))
    }

    async fn order_status(&self, _broker_id: &str, _symbol: &str) -> Result<BrokerOrder, ConnectorError> {
        Err(ConnectorError::Unimplemented("polymarket::order_status"))
    }

    async fn cancel_order(&self, _broker_id: &str, _symbol: &str) -> Result<(), ConnectorError> {
        Err(ConnectorError::Unimplemented("polymarket::cancel_order"))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn polymarket_never_routes_an_order_even_with_a_key() {
        let c = PolymarketConnector::new(Some("0xdeadbeef".into()));
        assert!(!c.is_live_ready(), "a key present must not imply live routing");
        assert!(c.submit_order(OrderRequest::market("x", super::super::Side::Buy, 1.0)).await.is_err());
    }
}
