//! Paper connector — simulates fills against the last known price with a small
//! slippage + fee. This is the default connector and never touches a network or
//! real funds. It is the Rust mirror of the TypeScript `PaperEngine`.

use super::{ConnectorError, Fill, Market, MarketConnector, OrderRequest, Side, Venue};
use async_trait::async_trait;
use std::sync::Mutex;
use uuid::Uuid;

pub struct PaperConnector {
    venue: Venue,
    markets: Mutex<Vec<Market>>,
}

impl PaperConnector {
    pub fn new(venue: Venue, markets: Vec<Market>) -> Self {
        Self {
            venue,
            markets: Mutex::new(markets),
        }
    }

    fn price_of(&self, market_id: &str) -> Option<f64> {
        self.markets
            .lock()
            .ok()?
            .iter()
            .find(|m| m.id == market_id)
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

    async fn list_markets(&self) -> Result<Vec<Market>, ConnectorError> {
        Ok(self.markets.lock().map_err(|_| ConnectorError::Network("lock".into()))?.clone())
    }

    async fn place_order(&self, req: OrderRequest) -> Result<Fill, ConnectorError> {
        let mid = self
            .price_of(&req.market_id)
            .ok_or_else(|| ConnectorError::Rejected(format!("unknown market {}", req.market_id)))?;
        let slip = if req.side == Side::Buy { 1.0008 } else { 0.9992 };
        let price = mid * slip;
        let fee = price * req.qty * 0.0006;
        Ok(Fill {
            order_id: Uuid::new_v4().to_string(),
            market_id: req.market_id,
            side: req.side,
            qty: req.qty,
            price,
            fee,
            ts: chrono::Utc::now().timestamp_millis(),
        })
    }

    async fn cancel_order(&self, _order_id: &str) -> Result<(), ConnectorError> {
        Ok(()) // paper orders fill immediately; nothing to cancel
    }
}
