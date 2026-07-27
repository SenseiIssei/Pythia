//! Alpaca connector — US equities (and, for accounts that have it, Alpaca's own
//! 24/7 crypto book).
//!
//!   · Paper base:   https://paper-api.alpaca.markets  (start here — real API, no real money)
//!   · Live base:    https://api.alpaca.markets
//!   · Auth:         APCA-API-KEY-ID + APCA-API-SECRET-KEY headers
//!
//! Everything here is non-blocking: `submit_order` returns as soon as Alpaca
//! acknowledges the order, and the engine polls `order_status` across its own
//! ticks. See [`super`] for why that matters.
//!
//! ## What preflight catches
//!
//! Submitting an order that cannot possibly work produces a useless broker error
//! hours later. So before anything is sent we check, against short-lived caches:
//!
//! - the market clock (an equity market order at 03:00 CET fills at *tomorrow's*
//!   open, across an unknown overnight gap — we refuse rather than gamble),
//! - the asset (tradable at all? fractionable? shortable?),
//! - buying power for buys, and held quantity for sells.
//!
//! Fails closed without a configured key id/secret.

use super::{
    num, num_or0, Balance, BrokerOrder, BrokerOrderStatus, BrokerPosition, ConnectorError,
    MarketConnector, OrderRequest, OrderType, Side, Venue,
};
use async_trait::async_trait;
use serde::Deserialize;
use serde_json::Value;
use std::collections::HashMap;
use std::sync::Mutex;
use std::time::Duration;

/// How long a cached clock/asset/account answer stays good. Short enough that
/// arming right after the opening bell works, long enough that a busy tick loop
/// does not hammer the account endpoint.
const CLOCK_TTL_MS: i64 = 20_000;
const ACCOUNT_TTL_MS: i64 = 10_000;
const ASSET_TTL_MS: i64 = 3_600_000; // asset metadata changes ~never

pub struct AlpacaConnector {
    key_id: Option<String>,
    secret: Option<String>,
    /// When true, routes to the paper endpoint even if keys are present.
    paper_endpoint: bool,
    /// Trade the pre/post-market sessions with marketable limit orders. Alpaca
    /// only accepts extended-hours orders as DAY limit orders, never market.
    extended_hours: bool,
    /// Allow opening *short* equity positions. Off by default: shorts need a
    /// margin account, a locate, and cannot be fractional — three ways for a
    /// strategy that happily emits sell signals to get a wall of rejections.
    allow_shorts: bool,
    http: reqwest::Client,
    clock_cache: Mutex<Option<(i64, MarketClock)>>,
    account_cache: Mutex<Option<(i64, AlpacaAccount)>>,
    asset_cache: Mutex<HashMap<String, (i64, AssetInfo)>>,
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
    /// Remaining same-day round trips before the PDT rule bites (cash/margin
    /// accounts under $25k). Alpaca rejects the 4th; surfacing it lets the UI
    /// warn before a strategy burns them.
    #[serde(default)]
    pub daytrade_count: u32,
    /// Which endpoint answered (so the UI can show paper vs live).
    #[serde(default)]
    pub paper: bool,
}

impl AlpacaAccount {
    fn buying_power_f64(&self) -> f64 {
        self.buying_power.parse().unwrap_or(0.0)
    }
    /// Whether the venue will accept *any* order right now.
    fn tradable(&self) -> Result<(), ConnectorError> {
        if self.account_blocked {
            return Err(ConnectorError::Preflight("Alpaca account is blocked".into()));
        }
        if self.trading_blocked {
            return Err(ConnectorError::Preflight("Alpaca trading is blocked on this account".into()));
        }
        if self.status != "ACTIVE" {
            return Err(ConnectorError::Preflight(format!(
                "Alpaca account status is {} (needs ACTIVE)",
                self.status
            )));
        }
        Ok(())
    }
}

/// `GET /v2/clock` — is the US equity market open right now?
#[derive(Debug, Clone, Deserialize, serde::Serialize)]
#[serde(rename_all(serialize = "camelCase", deserialize = "snake_case"))]
pub struct MarketClock {
    pub is_open: bool,
    #[serde(default)]
    pub next_open: String,
    #[serde(default)]
    pub next_close: String,
}

/// `GET /v2/assets/{symbol}` — the subset that decides whether an order is legal.
#[derive(Debug, Clone, Deserialize)]
struct AssetInfo {
    #[serde(default)]
    status: String,
    #[serde(default)]
    tradable: bool,
    #[serde(default)]
    fractionable: bool,
    #[serde(default)]
    shortable: bool,
    #[serde(default)]
    class: String, // "us_equity" | "crypto"
}

impl AssetInfo {
    fn is_crypto(&self) -> bool {
        self.class == "crypto"
    }
}

impl AlpacaConnector {
    pub fn new(key_id: Option<String>, secret: Option<String>, paper_endpoint: bool) -> Self {
        Self {
            key_id,
            secret,
            paper_endpoint,
            extended_hours: false,
            allow_shorts: false,
            http: reqwest::Client::builder()
                .timeout(Duration::from_secs(15))
                .build()
                .unwrap_or_default(),
            clock_cache: Mutex::new(None),
            account_cache: Mutex::new(None),
            asset_cache: Mutex::new(HashMap::new()),
        }
    }

    pub fn with_extended_hours(mut self, on: bool) -> Self {
        self.extended_hours = on;
        self
    }

    pub fn with_shorts(mut self, on: bool) -> Self {
        self.allow_shorts = on;
        self
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

    fn creds(&self) -> Result<(&str, &str), ConnectorError> {
        let (Some(k), Some(s)) = (self.key_id.as_deref(), self.secret.as_deref()) else {
            return Err(ConnectorError::NotConfigured("alpaca".into()));
        };
        if k.trim().is_empty() || s.trim().is_empty() {
            return Err(ConnectorError::NotConfigured("alpaca".into()));
        }
        Ok((k, s))
    }

    fn req(&self, method: reqwest::Method, path: &str) -> Result<reqwest::RequestBuilder, ConnectorError> {
        let (k, s) = self.creds()?;
        Ok(self
            .http
            .request(method, format!("{}{path}", self.base_url()))
            .header("APCA-API-KEY-ID", k)
            .header("APCA-API-SECRET-KEY", s))
    }

    /// Send a request and map Alpaca's failure modes onto our error type. The
    /// 401/403 split matters: it is almost always paper keys pointed at the live
    /// endpoint (or the reverse), and saying so saves an hour.
    async fn send(&self, rb: reqwest::RequestBuilder, what: &str) -> Result<Value, ConnectorError> {
        let resp = rb.send().await.map_err(|e| ConnectorError::Network(e.to_string()))?;
        let code = resp.status().as_u16();
        let body = resp.text().await.unwrap_or_default();
        if !(200..300).contains(&code) {
            return Err(match code {
                401 | 403 => ConnectorError::Auth(format!(
                    "HTTP {code} on {what} — are these {} keys?",
                    if self.paper_endpoint { "paper" } else { "live" }
                )),
                429 => ConnectorError::Network(format!("rate limited on {what}")),
                500..=599 => ConnectorError::Network(format!("Alpaca {code} on {what}")),
                _ => ConnectorError::Rejected(format!("{what} {code}: {}", body.trim())),
            });
        }
        if body.trim().is_empty() {
            return Ok(Value::Null);
        }
        serde_json::from_str(&body).map_err(|e| ConnectorError::Network(format!("bad {what} payload: {e}")))
    }

    /// Read-only account check for the UI's "test connection" button.
    pub async fn account(&self) -> Result<AlpacaAccount, ConnectorError> {
        let v = self.send(self.req(reqwest::Method::GET, "/v2/account")?, "account").await?;
        let mut acct: AlpacaAccount =
            serde_json::from_value(v).map_err(|e| ConnectorError::Network(e.to_string()))?;
        acct.paper = self.paper_endpoint;
        *self.account_cache.lock().unwrap() = Some((now_ms(), acct.clone()));
        Ok(acct)
    }

    async fn account_cached(&self) -> Result<AlpacaAccount, ConnectorError> {
        if let Some((at, a)) = self.account_cache.lock().unwrap().clone() {
            if now_ms() - at < ACCOUNT_TTL_MS {
                return Ok(a);
            }
        }
        self.account().await
    }

    /// Is the US equity market open? Cached briefly — the tick loop asks often.
    pub async fn clock(&self) -> Result<MarketClock, ConnectorError> {
        if let Some((at, c)) = self.clock_cache.lock().unwrap().clone() {
            if now_ms() - at < CLOCK_TTL_MS {
                return Ok(c);
            }
        }
        let v = self.send(self.req(reqwest::Method::GET, "/v2/clock")?, "clock").await?;
        let c: MarketClock = serde_json::from_value(v).map_err(|e| ConnectorError::Network(e.to_string()))?;
        *self.clock_cache.lock().unwrap() = Some((now_ms(), c.clone()));
        Ok(c)
    }

    async fn asset(&self, symbol: &str) -> Result<AssetInfo, ConnectorError> {
        if let Some((at, a)) = self.asset_cache.lock().unwrap().get(symbol).cloned() {
            if now_ms() - at < ASSET_TTL_MS {
                return Ok(a);
            }
        }
        // Crypto pairs carry a slash ("BTC/USD"); it has to survive the path.
        let path = format!("/v2/assets/{}", symbol.replace('/', "%2F"));
        let v = self.send(self.req(reqwest::Method::GET, &path)?, "asset").await?;
        let a: AssetInfo = serde_json::from_value(v).map_err(|e| ConnectorError::Network(e.to_string()))?;
        self.asset_cache.lock().unwrap().insert(symbol.to_string(), (now_ms(), a.clone()));
        Ok(a)
    }

    /// Current signed quantity held in `symbol` (0 when flat). A 404 from Alpaca
    /// means "no position", which is an answer, not an error.
    async fn position_qty(&self, symbol: &str) -> Result<f64, ConnectorError> {
        let path = format!("/v2/positions/{}", symbol.replace('/', "%2F"));
        match self.send(self.req(reqwest::Method::GET, &path)?, "position").await {
            Ok(v) => Ok(num_or0(v.get("qty"))),
            Err(ConnectorError::Rejected(msg)) if msg.contains("404") => Ok(0.0),
            Err(e) => Err(e),
        }
    }
}

/// Map Alpaca's order status vocabulary onto ours. Anything unrecognised is
/// treated as still working — we would rather keep polling a live order than
/// declare it dead and lose track of a real position.
fn map_status(s: &str) -> BrokerOrderStatus {
    match s {
        "filled" => BrokerOrderStatus::Filled,
        "partially_filled" => BrokerOrderStatus::PartiallyFilled,
        "canceled" | "pending_cancel" | "done_for_day" => BrokerOrderStatus::Canceled,
        "rejected" => BrokerOrderStatus::Rejected,
        "expired" | "stopped" | "suspended" => BrokerOrderStatus::Expired,
        _ => BrokerOrderStatus::Working,
    }
}

fn parse_order(v: &Value) -> Result<BrokerOrder, ConnectorError> {
    let id = v
        .get("id")
        .and_then(Value::as_str)
        .ok_or_else(|| ConnectorError::Network("order response has no id".into()))?
        .to_string();
    let raw = v.get("status").and_then(Value::as_str).unwrap_or("unknown").to_string();
    Ok(BrokerOrder {
        id,
        client_order_id: v.get("client_order_id").and_then(Value::as_str).map(str::to_string),
        status: map_status(&raw),
        filled_qty: num_or0(v.get("filled_qty")),
        avg_price: num(v.get("filled_avg_price")),
        fee: 0.0, // Alpaca US equities are commission-free
        raw_status: raw,
    })
}

fn now_ms() -> i64 {
    chrono::Utc::now().timestamp_millis()
}

#[async_trait]
impl MarketConnector for AlpacaConnector {
    fn venue(&self) -> Venue {
        Venue::Alpaca
    }

    fn is_live_ready(&self) -> bool {
        self.creds().is_ok()
    }

    fn label(&self) -> String {
        format!("Alpaca ({})", if self.paper_endpoint { "paper" } else { "live" })
    }

    /// Alpaca takes up to 9 decimals on fractionable symbols. Anything below
    /// ~0.0001 share is worth less than the rounding and gets dropped.
    fn round_qty(&self, qty: f64, symbol: &str) -> f64 {
        let fractionable = self
            .asset_cache
            .lock()
            .unwrap()
            .get(symbol)
            .map(|(_, a)| a.fractionable || a.is_crypto())
            .unwrap_or(true);
        if fractionable {
            let r = (qty * 1e6).trunc() / 1e6;
            if r < 1e-4 {
                0.0
            } else {
                r
            }
        } else {
            qty.trunc()
        }
    }

    async fn verify(&self) -> Result<String, ConnectorError> {
        let a = self.account().await?;
        a.tradable()?;
        Ok(format!(
            "{} · {} · buying power ${:.2}",
            self.label(),
            a.status,
            a.buying_power_f64()
        ))
    }

    async fn preflight(&self, req: &OrderRequest) -> Result<(), ConnectorError> {
        let asset = self.asset(&req.symbol).await?;
        if !asset.tradable || asset.status != "active" {
            return Err(ConnectorError::Preflight(format!(
                "{} is not tradable at Alpaca (status {})",
                req.symbol, asset.status
            )));
        }

        // Equities respect the session clock; Alpaca crypto is 24/7.
        if !asset.is_crypto() {
            let clock = self.clock().await?;
            if !clock.is_open && !self.extended_hours {
                return Err(ConnectorError::Preflight(format!(
                    "US market closed — next open {}. Enable extended hours to trade the pre/post session.",
                    clock.next_open
                )));
            }
        }

        let account = self.account_cached().await?;
        account.tradable()?;

        match req.side {
            Side::Buy => {
                if let Some(notional) = req.notional() {
                    let bp = account.buying_power_f64();
                    if notional > bp {
                        return Err(ConnectorError::Preflight(format!(
                            "order needs ${notional:.2} but buying power is ${bp:.2}"
                        )));
                    }
                }
            }
            Side::Sell => {
                // Selling more than we hold is a short. Alpaca cannot short
                // fractionally at all, and will not short a non-shortable name.
                let held = self.position_qty(&req.symbol).await?;
                if req.qty > held + 1e-9 {
                    if req.reduce_only {
                        return Err(ConnectorError::Preflight(format!(
                            "exit wants {:.4} {} but the broker only shows {:.4}",
                            req.qty, req.symbol, held
                        )));
                    }
                    if !self.allow_shorts {
                        return Err(ConnectorError::Preflight(format!(
                            "selling {:.4} {} would open a short (held {:.4}); shorts are disabled",
                            req.qty, req.symbol, held
                        )));
                    }
                    if !asset.shortable {
                        return Err(ConnectorError::Preflight(format!("{} is not shortable", req.symbol)));
                    }
                    if req.qty.fract() > 1e-9 {
                        return Err(ConnectorError::Preflight(
                            "Alpaca cannot short fractional shares — round to whole shares".into(),
                        ));
                    }
                }
            }
        }
        Ok(())
    }

    async fn submit_order(&self, req: OrderRequest) -> Result<BrokerOrder, ConnectorError> {
        let asset = self.asset(&req.symbol).await.ok();
        let is_crypto = asset.as_ref().map(AssetInfo::is_crypto).unwrap_or(false);
        let session_open = if is_crypto {
            true
        } else {
            self.clock().await.map(|c| c.is_open).unwrap_or(true)
        };

        // Extended-hours orders MUST be DAY limit orders — Alpaca rejects a
        // market order outright. So outside regular hours we convert to a
        // marketable limit: crossed by 0.5% so it fills like a market order,
        // capped so a thin pre-market book cannot fill us at an absurd price.
        let use_extended = !session_open && self.extended_hours && !is_crypto;
        let limit = match (req.order_type, use_extended) {
            (OrderType::Limit, _) => req.limit_price,
            (OrderType::Market, true) => req.ref_price.map(|p| match req.side {
                Side::Buy => p * 1.005,
                Side::Sell => p * 0.995,
            }),
            (OrderType::Market, false) => None,
        };
        if use_extended && limit.is_none() {
            return Err(ConnectorError::Preflight(
                "extended-hours orders need a limit price and none could be derived".into(),
            ));
        }

        let mut body = serde_json::json!({
            "symbol": req.symbol,
            "qty": super::sign::trim_decimals(req.qty, 9),
            "side": req.side.as_str(),
            "type": if limit.is_some() { "limit" } else { "market" },
            // Crypto is 24/7 and wants GTC; equities use DAY so a stale order
            // cannot wake up and fill days later.
            "time_in_force": if is_crypto { "gtc" } else { "day" },
        });
        if let Some(l) = limit {
            body["limit_price"] = serde_json::json!(super::sign::trim_decimals(l, 2));
        }
        if use_extended {
            body["extended_hours"] = serde_json::json!(true);
        }
        if let Some(cid) = &req.client_order_id {
            body["client_order_id"] = serde_json::json!(cid);
        }

        let v = self
            .send(
                self.req(reqwest::Method::POST, "/v2/orders")?
                    .header("content-type", "application/json")
                    .json(&body),
                "submit",
            )
            .await?;
        parse_order(&v)
    }

    /// Alpaca keys orders on the id alone, so `symbol` is unused here.
    async fn order_status(&self, broker_id: &str, _symbol: &str) -> Result<BrokerOrder, ConnectorError> {
        let v = self
            .send(self.req(reqwest::Method::GET, &format!("/v2/orders/{broker_id}"))?, "order")
            .await?;
        parse_order(&v)
    }

    async fn cancel_order(&self, broker_id: &str, _symbol: &str) -> Result<(), ConnectorError> {
        match self
            .send(self.req(reqwest::Method::DELETE, &format!("/v2/orders/{broker_id}"))?, "cancel")
            .await
        {
            Ok(_) => Ok(()),
            // 404 (gone) and 422 (already terminal) both mean "nothing resting".
            Err(ConnectorError::Rejected(msg)) if msg.contains("404") || msg.contains("422") => Ok(()),
            Err(e) => Err(e),
        }
    }

    async fn positions(&self) -> Result<Vec<BrokerPosition>, ConnectorError> {
        let v = self.send(self.req(reqwest::Method::GET, "/v2/positions")?, "positions").await?;
        let Some(arr) = v.as_array() else { return Ok(vec![]) };
        Ok(arr
            .iter()
            .filter_map(|p| {
                Some(BrokerPosition {
                    symbol: p.get("symbol")?.as_str()?.to_string(),
                    qty: num(p.get("qty"))?,
                    avg_price: num_or0(p.get("avg_entry_price")),
                    market_value: num_or0(p.get("market_value")),
                })
            })
            .collect())
    }

    async fn balances(&self) -> Result<Vec<Balance>, ConnectorError> {
        let a = self.account().await?;
        let cash: f64 = a.cash.parse().unwrap_or(0.0);
        let currency = if a.currency.is_empty() { "USD".to_string() } else { a.currency.clone() };
        Ok(vec![Balance {
            asset: currency,
            free: a.buying_power_f64(),
            total: cash,
            usd_value: Some(cash),
        }])
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn maps_every_alpaca_status_we_can_receive() {
        assert_eq!(map_status("filled"), BrokerOrderStatus::Filled);
        assert_eq!(map_status("partially_filled"), BrokerOrderStatus::PartiallyFilled);
        assert_eq!(map_status("canceled"), BrokerOrderStatus::Canceled);
        assert_eq!(map_status("rejected"), BrokerOrderStatus::Rejected);
        assert_eq!(map_status("expired"), BrokerOrderStatus::Expired);
        // In-flight states must stay non-terminal so the engine keeps polling.
        for s in ["new", "accepted", "pending_new", "accepted_for_bidding", "calculated"] {
            assert_eq!(map_status(s), BrokerOrderStatus::Working, "{s}");
        }
        // An unknown status must NOT be mistaken for terminal.
        assert!(!map_status("something_alpaca_added_later").is_terminal());
    }

    #[test]
    fn parses_a_partially_filled_order() {
        let v: Value = serde_json::from_str(
            r#"{"id":"abc-123","client_order_id":"pythia-7","status":"partially_filled",
                "qty":"10","filled_qty":"4","filled_avg_price":"231.47"}"#,
        )
        .unwrap();
        let o = parse_order(&v).unwrap();
        assert_eq!(o.id, "abc-123");
        assert_eq!(o.client_order_id.as_deref(), Some("pythia-7"));
        assert_eq!(o.status, BrokerOrderStatus::PartiallyFilled);
        assert_eq!(o.filled_qty, 4.0);
        assert_eq!(o.avg_price, Some(231.47));
        assert!(!o.status.is_terminal(), "a partial fill is still working");
    }

    #[test]
    fn parses_an_unfilled_order_without_an_average_price() {
        // A brand-new order has filled_avg_price: null — that must not blow up.
        let v: Value = serde_json::from_str(r#"{"id":"x","status":"new","filled_qty":"0","filled_avg_price":null}"#).unwrap();
        let o = parse_order(&v).unwrap();
        assert_eq!(o.filled_qty, 0.0);
        assert_eq!(o.avg_price, None);
    }

    #[test]
    fn an_order_response_without_an_id_is_an_error_not_a_panic() {
        let v: Value = serde_json::from_str(r#"{"status":"new"}"#).unwrap();
        assert!(parse_order(&v).is_err());
    }

    #[test]
    fn missing_keys_fail_closed() {
        let c = AlpacaConnector::new(None, None, true);
        assert!(!c.is_live_ready());
        let blank = AlpacaConnector::new(Some("  ".into()), Some("".into()), true);
        assert!(!blank.is_live_ready(), "whitespace-only keys are not keys");
    }

    #[test]
    fn endpoint_follows_the_paper_flag() {
        assert_eq!(
            AlpacaConnector::new(Some("k".into()), Some("s".into()), true).base_url(),
            "https://paper-api.alpaca.markets"
        );
        assert_eq!(
            AlpacaConnector::new(Some("k".into()), Some("s".into()), false).base_url(),
            "https://api.alpaca.markets"
        );
    }

    #[test]
    fn blocked_accounts_are_refused_before_any_order() {
        let mut a = AlpacaAccount {
            status: "ACTIVE".into(),
            currency: "USD".into(),
            cash: "1000".into(),
            buying_power: "2000".into(),
            portfolio_value: "1000".into(),
            pattern_day_trader: false,
            trading_blocked: false,
            account_blocked: false,
            daytrade_count: 0,
            paper: true,
        };
        assert!(a.tradable().is_ok());
        a.trading_blocked = true;
        assert!(a.tradable().is_err());
        a.trading_blocked = false;
        a.status = "ONBOARDING".into();
        assert!(a.tradable().is_err());
    }

    #[test]
    fn qty_rounding_respects_a_non_fractionable_asset() {
        let c = AlpacaConnector::new(Some("k".into()), Some("s".into()), true);
        // Nothing cached → assume fractionable (Alpaca's common case).
        assert_eq!(c.round_qty(1.234_567_8, "AAPL"), 1.234_567);
        // Dust is dropped rather than sent and rejected.
        assert_eq!(c.round_qty(0.000_01, "AAPL"), 0.0);

        c.asset_cache.lock().unwrap().insert(
            "BRK.A".into(),
            (
                now_ms(),
                AssetInfo { status: "active".into(), tradable: true, fractionable: false, shortable: false, class: "us_equity".into() },
            ),
        );
        assert_eq!(c.round_qty(3.9, "BRK.A"), 3.0, "non-fractionable → whole shares");
    }
}
