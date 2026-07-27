//! Paper connector — simulates fills against the last known price with a small
//! slippage + fee. This is the default connector and never touches a network or
//! real funds. It is the Rust mirror of the TypeScript `PaperEngine`.
//!
//! It implements the same submit → poll → cancel lifecycle as the live venues so
//! the engine runs one code path in both modes; paper orders simply reach their
//! terminal state on the first poll.

use super::{
    Balance, BrokerOrder, BrokerOrderStatus, ConnectorError, Market, MarketConnector, OrderRequest,
    Side, Venue,
};
use async_trait::async_trait;
use std::collections::HashMap;
use std::sync::Mutex;
use uuid::Uuid;

pub struct PaperConnector {
    venue: Venue,
    markets: Mutex<Vec<Market>>,
    /// Orders we have "filled", so `order_status` can answer for them.
    filled: Mutex<HashMap<String, BrokerOrder>>,
}

impl PaperConnector {
    pub fn new(venue: Venue, markets: Vec<Market>) -> Self {
        Self {
            venue,
            markets: Mutex::new(markets),
            filled: Mutex::new(HashMap::new()),
        }
    }

    fn price_of(&self, symbol: &str) -> Option<f64> {
        self.markets
            .lock()
            .ok()?
            .iter()
            .find(|m| m.id == symbol || m.symbol == symbol)
            .map(|m| m.price)
    }
}

#[async_trait]
impl MarketConnector for PaperConnector {
    fn venue(&self) -> Venue {
        self.venue
    }

    fn is_live_ready(&self) -> bool {
        false // paper connector is, by definition, never live
    }

    fn label(&self) -> String {
        format!("{:?} (paper)", self.venue)
    }

    async fn verify(&self) -> Result<String, ConnectorError> {
        Ok("paper simulator — no venue contacted".into())
    }

    async fn list_markets(&self) -> Result<Vec<Market>, ConnectorError> {
        Ok(self.markets.lock().map_err(|_| ConnectorError::Network("lock".into()))?.clone())
    }

    async fn submit_order(&self, req: OrderRequest) -> Result<BrokerOrder, ConnectorError> {
        let mid = self
            .price_of(&req.symbol)
            .or(req.ref_price)
            .ok_or_else(|| ConnectorError::Rejected(format!("unknown market {}", req.symbol)))?;
        let slip = if req.side == Side::Buy { 1.0008 } else { 0.9992 };
        let price = mid * slip;
        let order = BrokerOrder {
            id: Uuid::new_v4().to_string(),
            client_order_id: req.client_order_id,
            status: BrokerOrderStatus::Filled,
            filled_qty: req.qty,
            avg_price: Some(price),
            fee: price * req.qty * 0.0006,
            raw_status: "paper-filled".into(),
        };
        self.filled.lock().unwrap().insert(order.id.clone(), order.clone());
        Ok(order)
    }

    async fn order_status(&self, broker_id: &str, _symbol: &str) -> Result<BrokerOrder, ConnectorError> {
        self.filled
            .lock()
            .unwrap()
            .get(broker_id)
            .cloned()
            .ok_or_else(|| ConnectorError::Rejected(format!("unknown paper order {broker_id}")))
    }

    async fn cancel_order(&self, _broker_id: &str, _symbol: &str) -> Result<(), ConnectorError> {
        Ok(()) // paper orders fill immediately; nothing to cancel
    }

    async fn balances(&self) -> Result<Vec<Balance>, ConnectorError> {
        Ok(vec![])
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn market(id: &str, price: f64) -> Market {
        Market { id: id.into(), venue: Venue::Crypto, symbol: id.into(), price, updated_at: 0 }
    }

    #[tokio::test]
    async fn a_paper_order_fills_immediately_and_stays_queryable() {
        let c = PaperConnector::new(Venue::Crypto, vec![market("BTC/USD", 30_000.0)]);
        let o = c.submit_order(OrderRequest::market("BTC/USD", Side::Buy, 0.5)).await.unwrap();
        assert_eq!(o.status, BrokerOrderStatus::Filled);
        assert_eq!(o.filled_qty, 0.5);
        assert!(o.avg_price.unwrap() > 30_000.0, "buys pay a little slippage");
        // The engine polls even paper orders — that must answer.
        let again = c.order_status(&o.id, "BTC/USD").await.unwrap();
        assert_eq!(again.id, o.id);
    }

    #[tokio::test]
    async fn an_unknown_market_is_rejected_not_guessed() {
        let c = PaperConnector::new(Venue::Crypto, vec![]);
        assert!(c.submit_order(OrderRequest::market("NOPE/USD", Side::Buy, 1.0)).await.is_err());
    }

    #[tokio::test]
    async fn the_paper_connector_is_never_live_ready() {
        let c = PaperConnector::new(Venue::Alpaca, vec![]);
        assert!(!c.is_live_ready());
    }
}
