//! Alpaca equities connector (Phase 2 — live execution).
//!
//!   · Paper base:   https://paper-api.alpaca.markets  (start here — real API, no real money)
//!   · Live base:    https://api.alpaca.markets
//!   · Auth:         APCA-API-KEY-ID + APCA-API-SECRET-KEY headers
//!   · Constraints:  US market hours + Pattern Day Trader rules — enforced by the
//!                   risk manager before any order reaches this connector.
//!
//! Fails closed without a configured key id/secret. The trait's `place_order`
//! submits a market order and polls briefly for the terminal fill.

use super::{ConnectorError, Fill, Market, MarketConnector, OrderRequest, Side, Venue};
use async_trait::async_trait;
use serde::Deserialize;

pub struct AlpacaConnector {
    key_id: Option<String>,
    secret: Option<String>,
    /// When true, routes to the paper endpoint even if keys are present.
    paper_endpoint: bool,
}

/// A snapshot of the Alpaca account — used by the UI's connection test. Safe,
/// read-only; never used to place an order.
///
/// Alpaca sends snake_case (`buying_power`); the frontend expects camelCase. A
/// single `rename_all` would break one side — notably the `*_blocked` flags
/// would silently default to `false`, hiding a restricted account — so the two
/// directions are configured independently.
#[derive(Debug, Clone, Deserialize, serde::Serialize)]
#[serde(rename_all(serialize = "camelCase", deserialize = "snake_case"))]
pub struct AlpacaAccount {
    pub status: String,
    #[serde(default)]
    pub currency: String,
    #[serde(default)]
    pub cash: String,
    #[serde(default)]
    pub buying_power: String,
    #[serde(default)]
    pub portfolio_value: String,
    #[serde(default)]
    pub pattern_day_trader: bool,
    #[serde(default)]
    pub trading_blocked: bool,
    #[serde(default)]
    pub account_blocked: bool,
    /// Which endpoint answered (so the UI can show paper vs live).
    #[serde(default)]
    pub paper: bool,
}

#[derive(Debug, Deserialize)]
struct AlpacaOrderResp {
    id: String,
    status: String,
    #[serde(default)]
    filled_qty: Option<String>,
    #[serde(default)]
    filled_avg_price: Option<String>,
}

impl AlpacaConnector {
    pub fn new(key_id: Option<String>, secret: Option<String>, paper_endpoint: bool) -> Self {
        Self { key_id, secret, paper_endpoint }
    }

    /// Build from a vault/env key map (fields `keyId`/`secret`, or Alpaca's own
    /// `APCA-API-KEY-ID`/`APCA-API-SECRET-KEY` names).
    pub fn from_fields(get: impl Fn(&str) -> Option<String>, paper_endpoint: bool) -> Self {
        let key_id = get("keyId").or_else(|| get("APCA_API_KEY_ID"));
        let secret = get("secret").or_else(|| get("APCA_API_SECRET_KEY"));
        Self::new(key_id, secret, paper_endpoint)
    }

    fn base_url(&self) -> &'static str {
        if self.paper_endpoint {
            "https://paper-api.alpaca.markets"
        } else {
            "https://api.alpaca.markets"
        }
    }

    fn client(&self) -> Result<(reqwest::Client, &str, &str), ConnectorError> {
        let (Some(k), Some(s)) = (self.key_id.as_deref(), self.secret.as_deref()) else {
            return Err(ConnectorError::NotConfigured("alpaca".into()));
        };
        if k.trim().is_empty() || s.trim().is_empty() {
            return Err(ConnectorError::NotConfigured("alpaca".into()));
        }
        Ok((reqwest::Client::new(), k, s))
    }

    /// Read-only account check for the UI's "test connection" button.
    pub async fn account(&self) -> Result<AlpacaAccount, ConnectorError> {
        let (client, k, s) = self.client()?;
        let resp = client
            .get(format!("{}/v2/account", self.base_url()))
            .header("APCA-API-KEY-ID", k)
            .header("APCA-API-SECRET-KEY", s)
            .send()
            .await
            .map_err(|e| ConnectorError::Network(e.to_string()))?;
        if !resp.status().is_success() {
            let code = resp.status().as_u16();
            let body = resp.text().await.unwrap_or_default();
            return Err(if code == 401 || code == 403 {
                ConnectorError::Auth(format!("HTTP {code}"))
            } else {
                ConnectorError::Rejected(format!("account {code}: {body}"))
            });
        }
        let mut acct: AlpacaAccount =
            resp.json().await.map_err(|e| ConnectorError::Network(e.to_string()))?;
        acct.paper = self.paper_endpoint;
        Ok(acct)
    }

    async fn poll_fill(
        &self,
        client: &reqwest::Client,
        k: &str,
        s: &str,
        order_id: &str,
    ) -> Result<AlpacaOrderResp, ConnectorError> {
        // Market orders fill fast during RTH; poll a few times before giving up.
        for _ in 0..12 {
            tokio::time::sleep(std::time::Duration::from_millis(500)).await;
            let resp = client
                .get(format!("{}/v2/orders/{order_id}", self.base_url()))
                .header("APCA-API-KEY-ID", k)
                .header("APCA-API-SECRET-KEY", s)
                .send()
                .await
                .map_err(|e| ConnectorError::Network(e.to_string()))?;
            if !resp.status().is_success() {
                continue;
            }
            let o: AlpacaOrderResp =
                resp.json().await.map_err(|e| ConnectorError::Network(e.to_string()))?;
            match o.status.as_str() {
                "filled" => return Ok(o),
                "canceled" | "rejected" | "expired" => {
                    return Err(ConnectorError::Rejected(format!("order {}", o.status)))
                }
                _ => continue, // new / accepted / pending / partially_filled → keep polling
            }
        }
        Err(ConnectorError::Rejected(
            "not filled within timeout (market closed, or still working)".into(),
        ))
    }
}

#[async_trait]
impl MarketConnector for AlpacaConnector {
    fn venue(&self) -> Venue {
        Venue::Alpaca
    }

    fn is_live_ready(&self) -> bool {
        matches!((&self.key_id, &self.secret), (Some(k), Some(s)) if !k.trim().is_empty() && !s.trim().is_empty())
    }

    async fn list_markets(&self) -> Result<Vec<Market>, ConnectorError> {
        // Read-only equities quotes come from the market-data API (not needed for
        // the order path); the engine already carries Alpaca symbols.
        Err(ConnectorError::Unimplemented("alpaca::list_markets"))
    }

    async fn place_order(&self, req: OrderRequest) -> Result<Fill, ConnectorError> {
        let (client, k, s) = self.client()?;
        let side = match req.side {
            Side::Buy => "buy",
            Side::Sell => "sell",
        };
        // `market_id` carries the ticker (e.g. "AAPL") for Alpaca.
        let body = serde_json::json!({
            "symbol": req.market_id,
            "qty": format!("{:.4}", req.qty),
            "side": side,
            "type": "market",
            "time_in_force": "day",
        });
        let resp = client
            .post(format!("{}/v2/orders", self.base_url()))
            .header("APCA-API-KEY-ID", k)
            .header("APCA-API-SECRET-KEY", s)
            .header("content-type", "application/json")
            .json(&body)
            .send()
            .await
            .map_err(|e| ConnectorError::Network(e.to_string()))?;
        if !resp.status().is_success() {
            let code = resp.status().as_u16();
            let msg = resp.text().await.unwrap_or_default();
            return Err(if code == 401 || code == 403 {
                ConnectorError::Auth(format!("HTTP {code}"))
            } else {
                ConnectorError::Rejected(format!("submit {code}: {msg}"))
            });
        }
        let submitted: AlpacaOrderResp =
            resp.json().await.map_err(|e| ConnectorError::Network(e.to_string()))?;

        // If already filled on submit, use it; otherwise poll.
        let filled = if submitted.status == "filled" {
            submitted
        } else {
            self.poll_fill(&client, k, s, &submitted.id).await?
        };

        let price = filled
            .filled_avg_price
            .as_deref()
            .and_then(|p| p.parse::<f64>().ok())
            .ok_or_else(|| ConnectorError::Rejected("filled but no average price".into()))?;
        let qty = filled
            .filled_qty
            .as_deref()
            .and_then(|q| q.parse::<f64>().ok())
            .unwrap_or(req.qty);

        Ok(Fill {
            order_id: filled.id,
            market_id: req.market_id,
            side: req.side,
            qty,
            price,
            fee: 0.0, // Alpaca US equities are commission-free
            ts: chrono::Utc::now().timestamp_millis(),
        })
    }

    async fn cancel_order(&self, order_id: &str) -> Result<(), ConnectorError> {
        let (client, k, s) = self.client()?;
        client
            .delete(format!("{}/v2/orders/{order_id}", self.base_url()))
            .header("APCA-API-KEY-ID", k)
            .header("APCA-API-SECRET-KEY", s)
            .send()
            .await
            .map_err(|e| ConnectorError::Network(e.to_string()))?;
        Ok(())
    }
}
