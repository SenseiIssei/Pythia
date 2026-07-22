//! Crypto exchange connector (Phase 2), CCXT-shaped so venues are swappable.
//!
//! First target: Kraken spot.
//!   · Market data:  GET https://api.kraken.com/0/public/Ticker
//!   · Auth:         API key + secret, HMAC-SHA512 signed private endpoints
//!   · Scope:        spot only in v1; grant TRADE permission, NOT withdrawal
//!
//! Fails closed without a configured key/secret.

use super::{ConnectorError, Fill, Market, MarketConnector, OrderRequest, Venue};
use async_trait::async_trait;

#[derive(Default)]
pub struct CryptoConnector {
    api_key: Option<String>,
    api_secret: Option<String>,
}

impl CryptoConnector {
    pub fn new(api_key: Option<String>, api_secret: Option<String>) -> Self {
        Self { api_key, api_secret }
    }
}

#[async_trait]
impl MarketConnector for CryptoConnector {
    fn venue(&self) -> Venue {
        Venue::Crypto
    }

    fn is_live_ready(&self) -> bool {
        self.api_key.is_some() && self.api_secret.is_some()
    }

    async fn list_markets(&self) -> Result<Vec<Market>, ConnectorError> {
        Err(ConnectorError::Unimplemented("crypto::list_markets"))
    }

    async fn place_order(&self, _req: OrderRequest) -> Result<Fill, ConnectorError> {
        if !self.is_live_ready() {
            return Err(ConnectorError::NotConfigured("crypto".into()));
        }
        Err(ConnectorError::Unimplemented("crypto::place_order"))
    }

    async fn cancel_order(&self, _order_id: &str) -> Result<(), ConnectorError> {
        Err(ConnectorError::Unimplemented("crypto::cancel_order"))
    }
}
