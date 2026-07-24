//! Alpaca equities connector (Phase 2 — live execution).
//!
//!   · Paper base:   https://paper-api.alpaca.markets  (start here — real API, no real money)
//!   · Live base:    https://api.alpaca.markets
//!   · Auth:         APCA-API-KEY-ID + APCA-API-SECRET-KEY headers
//!   · Constraints:  US market hours + Pattern Day Trader rules — enforced by the
//!                   risk manager before any order reaches this connector.
//!
//! Fails closed without a configured key id/secret.
//!
//! # Why the order path is more than one POST
//!
//! Three things can lose real money if you submit and hope:
//!
//! 1. **A working order is not a dead order.** If we stop polling and call the
//!    order rejected, the broker may still fill it minutes later — the engine
//!    then holds a position it does not know about, with no stop attached. So a
//!    timeout *cancels* first, then re-reads the terminal state.
//! 2. **Cancels race fills.** A cancel can lose to a fill, or land after a
//!    partial. Every exit path re-reads the order and settles whatever
//!    `filled_qty` actually says rather than assuming zero.
//! 3. **A network error is not a rejection.** If the connection drops after the
//!    POST, the order may well have reached the exchange. Every submission
//!    carries a deterministic `client_order_id`, so a retry either wins the race
//!    or gets a duplicate error we can resolve by looking the order up.

use super::{ConnectorError, Fill, Market, MarketConnector, OrderRequest, OrderType, Side, Venue};
use async_trait::async_trait;
use serde::Deserialize;
use std::time::Duration;

pub struct AlpacaConnector {
    key_id: Option<String>,
    secret: Option<String>,
    /// When true, routes to the paper endpoint even if keys are present.
    paper_endpoint: bool,
    /// Cap on marketable-limit slippage, in basis points. 0 → plain market order.
    slippage_bps: f64,
    /// Allow limit orders to work the 04:00–09:30 / 16:00–20:00 ET sessions.
    extended_hours: bool,
}

/// A snapshot of the Alpaca account — used by the UI's connection test, the
/// PDT guard, and startup reconciliation. Safe, read-only; never places an order.
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
    pub equity: String,
    #[serde(default)]
    pub pattern_day_trader: bool,
    /// Day trades used in the trailing 5 business days. Under $25k equity, a
    /// 4th one flags the account as a Pattern Day Trader and restricts it.
    #[serde(default)]
    pub daytrade_count: u32,
    #[serde(default)]
    pub trading_blocked: bool,
    #[serde(default)]
    pub account_blocked: bool,
    #[serde(default)]
    pub shorting_enabled: bool,
    /// Which endpoint answered (so the UI can show paper vs live).
    #[serde(default)]
    pub paper: bool,
}

impl AlpacaAccount {
    fn f(s: &str) -> f64 {
        s.parse::<f64>().unwrap_or(0.0)
    }
    pub fn equity_f64(&self) -> f64 {
        Self::f(&self.equity)
    }
    pub fn buying_power_f64(&self) -> f64 {
        Self::f(&self.buying_power)
    }
    /// True when one more day trade would trip the PDT restriction: FINRA
    /// allows three in five business days below $25,000 of equity.
    pub fn day_trade_limit_reached(&self) -> bool {
        self.equity_f64() < 25_000.0 && self.daytrade_count >= 3
    }
    /// Anything that means "do not send orders to this account".
    pub fn is_restricted(&self) -> Option<String> {
        if self.account_blocked {
            return Some("account blocked".into());
        }
        if self.trading_blocked {
            return Some("trading blocked".into());
        }
        if !self.status.eq_ignore_ascii_case("ACTIVE") {
            return Some(format!("account status {}", self.status));
        }
        None
    }
}

/// The market session, straight from the broker. Beats guessing from a local
/// clock: it already knows about holidays, half-days and DST.
#[derive(Debug, Clone, Deserialize, serde::Serialize)]
#[serde(rename_all(serialize = "camelCase", deserialize = "snake_case"))]
pub struct MarketClock {
    pub timestamp: String,
    pub is_open: bool,
    pub next_open: String,
    pub next_close: String,
}

impl MarketClock {
    /// Exchange-local date and minute-of-day, taken from the broker's own
    /// timestamp.
    ///
    /// `timestamp` is RFC3339 *with the exchange's offset*, so parsing it as a
    /// fixed-offset datetime yields New York wall-clock time directly. That
    /// sidesteps a timezone database entirely — and more importantly sidesteps
    /// getting DST wrong twice a year, which would silently shift every session
    /// boundary by an hour.
    pub fn exchange_now(&self) -> Option<(String, u32)> {
        let dt = chrono::DateTime::parse_from_rfc3339(&self.timestamp).ok()?;
        let local = dt.naive_local();
        Some((
            local.format("%Y-%m-%d").to_string(),
            chrono::Timelike::hour(&local) * 60 + chrono::Timelike::minute(&local),
        ))
    }
}

/// One row of the trading calendar. `open`/`close` bound regular hours;
/// `session_open`/`session_close` bound the extended sessions (typically
/// 04:00–20:00 ET). Times are exchange-local `HH:MM`.
#[derive(Debug, Clone, Deserialize, serde::Serialize)]
#[serde(rename_all(serialize = "camelCase", deserialize = "snake_case"))]
pub struct CalendarDay {
    pub date: String,
    pub open: String,
    pub close: String,
    #[serde(default)]
    pub session_open: String,
    #[serde(default)]
    pub session_close: String,
}

/// Parse an exchange time into minutes past midnight, accepting both `"09:30"`
/// and `"0930"` — the calendar endpoint has used each shape.
fn hhmm_to_minutes(s: &str) -> Option<u32> {
    let digits: String = s.chars().filter(|c| c.is_ascii_digit()).collect();
    if digits.len() != 4 {
        return None;
    }
    let h: u32 = digits[..2].parse().ok()?;
    let m: u32 = digits[2..].parse().ok()?;
    (h < 24 && m < 60).then_some(h * 60 + m)
}

impl CalendarDay {
    /// Is `minute_of_day` inside the extended session (pre-market through
    /// after-hours)? Falls back to regular hours when the venue doesn't report
    /// a session window, which is the conservative reading.
    pub fn in_extended_session(&self, minute_of_day: u32) -> bool {
        let open = hhmm_to_minutes(&self.session_open)
            .or_else(|| hhmm_to_minutes(&self.open));
        let close = hhmm_to_minutes(&self.session_close)
            .or_else(|| hhmm_to_minutes(&self.close));
        match (open, close) {
            (Some(o), Some(c)) => minute_of_day >= o && minute_of_day < c,
            _ => false,
        }
    }

    /// Exchange-local end of the extended session, for display.
    pub fn session_end(&self) -> String {
        if self.session_close.is_empty() { self.close.clone() } else { self.session_close.clone() }
    }
}

/// One open position as the broker sees it — the source of truth we reconcile
/// our own ledger against on startup.
#[derive(Debug, Clone, Deserialize, serde::Serialize)]
#[serde(rename_all(serialize = "camelCase", deserialize = "snake_case"))]
pub struct AlpacaPosition {
    pub symbol: String,
    /// Signed: negative for a short.
    pub qty: String,
    pub avg_entry_price: String,
    #[serde(default)]
    pub market_value: String,
    #[serde(default)]
    pub unrealized_pl: String,
}

impl AlpacaPosition {
    pub fn qty_f64(&self) -> f64 {
        self.qty.parse().unwrap_or(0.0)
    }
    pub fn avg_price_f64(&self) -> f64 {
        self.avg_entry_price.parse().unwrap_or(0.0)
    }
}

#[derive(Debug, Clone, Deserialize)]
struct AlpacaOrderResp {
    id: String,
    status: String,
    #[serde(default)]
    filled_qty: Option<String>,
    #[serde(default)]
    filled_avg_price: Option<String>,
}

impl AlpacaOrderResp {
    fn filled(&self) -> f64 {
        self.filled_qty.as_deref().and_then(|q| q.parse().ok()).unwrap_or(0.0)
    }
    fn avg_price(&self) -> Option<f64> {
        self.filled_avg_price.as_deref().and_then(|p| p.parse().ok()).filter(|p| *p > 0.0)
    }
    /// Terminal states: the broker will not act on this order again.
    fn is_terminal(&self) -> bool {
        matches!(
            self.status.as_str(),
            "filled" | "canceled" | "cancelled" | "expired" | "rejected" | "done_for_day" | "suspended"
        )
    }
}

/// How the connector should size an order on the wire.
///
/// Alpaca accepts a dollar `notional` OR a share `qty`, never both. Notional is
/// strictly better for entries — it needs no client-side rounding and never
/// over-spends — but it is **buy-side, fractionable, DAY-market only**, and
/// crucially cannot express "sell exactly what I hold". Exits therefore always
/// go out as `qty`.
#[derive(Debug, Clone, Copy, PartialEq)]
pub enum Sizing {
    Shares(f64),
    Notional(f64),
}

/// Everything the order path needs beyond the venue-agnostic [`OrderRequest`].
#[derive(Debug, Clone)]
pub struct AlpacaOrder {
    pub symbol: String,
    pub side: Side,
    pub sizing: Sizing,
    /// Reference price, used to derive the marketable-limit band.
    pub ref_price: f64,
    /// Stable id for idempotent resubmission.
    pub client_order_id: String,
    /// True when this order reduces or closes an existing position. Closing
    /// orders are allowed to be fractional; opening shorts are not.
    pub reduce_only: bool,
}

impl AlpacaConnector {
    pub fn new(key_id: Option<String>, secret: Option<String>, paper_endpoint: bool) -> Self {
        Self {
            key_id,
            secret,
            paper_endpoint,
            slippage_bps: 25.0,
            extended_hours: false,
        }
    }

    /// Build from a vault/env key map (fields `keyId`/`secret`, or Alpaca's own
    /// `APCA-API-KEY-ID`/`APCA-API-SECRET-KEY` names).
    pub fn from_fields(get: impl Fn(&str) -> Option<String>, paper_endpoint: bool) -> Self {
        let key_id = get("keyId").or_else(|| get("APCA_API_KEY_ID"));
        let secret = get("secret").or_else(|| get("APCA_API_SECRET_KEY"));
        Self::new(key_id, secret, paper_endpoint)
    }

    /// Cap on how far a marketable limit may cross the book. 0 disables the
    /// limit and sends a plain market order.
    pub fn with_slippage_bps(mut self, bps: f64) -> Self {
        self.slippage_bps = bps.max(0.0);
        self
    }

    pub fn with_extended_hours(mut self, on: bool) -> Self {
        self.extended_hours = on;
        self
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
        let client = reqwest::Client::builder()
            .timeout(Duration::from_secs(15))
            .build()
            .map_err(|e| ConnectorError::Network(e.to_string()))?;
        Ok((client, k, s))
    }

    /// GET a JSON resource under the trading API, mapping status codes to the
    /// error variants the UI distinguishes.
    async fn get_json<T: serde::de::DeserializeOwned>(&self, path: &str) -> Result<T, ConnectorError> {
        let (client, k, s) = self.client()?;
        let resp = client
            .get(format!("{}{path}", self.base_url()))
            .header("APCA-API-KEY-ID", k)
            .header("APCA-API-SECRET-KEY", s)
            .send()
            .await
            .map_err(|e| ConnectorError::Network(e.to_string()))?;
        let code = resp.status().as_u16();
        if !resp.status().is_success() {
            let body = resp.text().await.unwrap_or_default();
            return Err(if code == 401 || code == 403 {
                ConnectorError::Auth(format!("HTTP {code}"))
            } else {
                ConnectorError::Rejected(format!("{path} {code}: {body}"))
            });
        }
        resp.json::<T>().await.map_err(|e| ConnectorError::Network(e.to_string()))
    }

    /// Read-only account check for the UI's "test connection" button, the PDT
    /// guard and startup reconciliation.
    pub async fn account(&self) -> Result<AlpacaAccount, ConnectorError> {
        let mut acct: AlpacaAccount = self.get_json("/v2/account").await?;
        acct.paper = self.paper_endpoint;
        Ok(acct)
    }

    /// Is the US equity market open right now? Asked of the broker, never
    /// inferred locally — holidays and half-days are not worth reimplementing.
    pub async fn clock(&self) -> Result<MarketClock, ConnectorError> {
        self.get_json("/v2/clock").await
    }

    /// Every open position at the broker.
    pub async fn positions(&self) -> Result<Vec<AlpacaPosition>, ConnectorError> {
        self.get_json("/v2/positions").await
    }

    /// Trading calendar for one exchange-local date.
    pub async fn calendar(&self, date: &str) -> Result<Vec<CalendarDay>, ConnectorError> {
        self.get_json(&format!("/v2/calendar?start={date}&end={date}")).await
    }

    /// Where the market is right now: regular hours, extended session, or shut.
    ///
    /// Returns `(clock, extended_open, session_end)`. Extended hours matter
    /// because "the market is closed" is true for most of the day in European
    /// time zones — 4:00–20:00 ET is a far more useful window than 9:30–16:00,
    /// and Alpaca will accept limit orders across all of it.
    pub async fn session(&self) -> Result<(MarketClock, bool, Option<String>), ConnectorError> {
        let clock = self.clock().await?;
        if clock.is_open {
            // Regular hours are unambiguously inside the extended session; no
            // need to spend a second request to learn that.
            return Ok((clock, true, None));
        }
        let Some((date, minute)) = clock.exchange_now() else {
            return Ok((clock, false, None));
        };
        match self.calendar(&date).await {
            Ok(days) => match days.into_iter().find(|d| d.date == date) {
                // A date absent from the calendar is a weekend or holiday.
                Some(day) => {
                    let open = day.in_extended_session(minute);
                    let end = open.then(|| day.session_end());
                    Ok((clock, open, end))
                }
                None => Ok((clock, false, None)),
            },
            // Can't confirm a session → treat it as closed. Failing open here
            // would route orders into a market we couldn't verify was trading.
            Err(_) => Ok((clock, false, None)),
        }
    }

    /// Cancel every open order — the panic button behind the kill switch.
    pub async fn cancel_all_orders(&self) -> Result<(), ConnectorError> {
        let (client, k, s) = self.client()?;
        client
            .delete(format!("{}/v2/orders", self.base_url()))
            .header("APCA-API-KEY-ID", k)
            .header("APCA-API-SECRET-KEY", s)
            .send()
            .await
            .map_err(|e| ConnectorError::Network(e.to_string()))?;
        Ok(())
    }

    /// Build the submission body. See [`Sizing`] for why exits are share-based.
    fn order_body(&self, o: &AlpacaOrder) -> serde_json::Value {
        let side = match o.side {
            Side::Buy => "buy",
            Side::Sell => "sell",
        };
        let mut body = serde_json::json!({
            "symbol": o.symbol,
            "side": side,
            "time_in_force": "day",
            "client_order_id": o.client_order_id,
        });
        match o.sizing {
            Sizing::Shares(q) => body["qty"] = serde_json::json!(format!("{q:.6}")),
            Sizing::Notional(n) => body["notional"] = serde_json::json!(format!("{n:.2}")),
        }

        // A marketable limit gets market-like fill probability while refusing to
        // pay through a gapped or thin book. Extended-hours sessions accept
        // limit orders only, so the band is mandatory there.
        let fractional = matches!(o.sizing, Sizing::Notional(_))
            || matches!(o.sizing, Sizing::Shares(q) if q.fract() > f64::EPSILON);
        // Outside regular hours a limit price is not optional — Alpaca rejects
        // market and notional orders there — so the band is forced on even if
        // slippage protection was configured off.
        let want_limit = (self.slippage_bps > 0.0 || self.extended_hours) && o.ref_price > 0.0;
        if want_limit && !fractional {
                // Outside regular hours the book is thin, so a 25bps band often
            // sits inside the spread and never fills. Widen it there — this is
            // the price of trading a session with a fraction of the liquidity.
            let bps = if self.extended_hours { self.slippage_bps.max(75.0) } else { self.slippage_bps };
            let band = o.ref_price * (bps / 10_000.0);
            let limit = match o.side {
                Side::Buy => o.ref_price + band,
                Side::Sell => (o.ref_price - band).max(0.01),
            };
            body["type"] = serde_json::json!("limit");
            body["limit_price"] = serde_json::json!(format!("{limit:.2}"));
            if self.extended_hours {
                body["extended_hours"] = serde_json::json!(true);
            }
        } else {
            // Fractional quantities and notional orders are market-only at Alpaca.
            body["type"] = serde_json::json!("market");
        }
        body
    }

    /// Reshape an order for the session it will actually trade in.
    ///
    /// Outside regular hours Alpaca accepts **whole-share DAY limit orders
    /// only** — no market orders, no notional sizing, no fractions. The engine
    /// sizes entries in dollars because that's better during the day, so those
    /// have to be converted here rather than rejected at the venue with a 422.
    fn normalized_for_session(&self, o: &AlpacaOrder) -> Result<AlpacaOrder, ConnectorError> {
        if !self.extended_hours {
            return Ok(o.clone());
        }
        if o.ref_price <= 0.0 {
            return Err(ConnectorError::Rejected(
                "extended-hours orders need a limit price, but no reference price was available".into(),
            ));
        }
        let shares = match o.sizing {
            Sizing::Notional(n) => (n / o.ref_price).floor(),
            Sizing::Shares(q) => q.floor(),
        };
        if shares < 1.0 {
            return Err(ConnectorError::Rejected(format!(
                "extended hours needs at least one whole share; sized to {shares:.4} at {:.2}",
                o.ref_price
            )));
        }
        Ok(AlpacaOrder { sizing: Sizing::Shares(shares), ..o.clone() })
    }

    /// Submit, then resolve to a terminal outcome — never leaving a live order
    /// working that the engine believes is dead.
    pub async fn submit(&self, o: &AlpacaOrder) -> Result<Fill, ConnectorError> {
        let o = &self.normalized_for_session(o)?;
        let (client, k, s) = self.client()?;

        // Guard the one sizing Alpaca silently refuses: you cannot open a short
        // in fractional shares. Better to reject here with a readable reason
        // than to eat a 422 from the venue.
        if o.side == Side::Sell && !o.reduce_only {
            if let Sizing::Shares(q) = o.sizing {
                if q.fract() > f64::EPSILON {
                    return Err(ConnectorError::Rejected(
                        "fractional short selling is not supported by Alpaca".into(),
                    ));
                }
            }
        }

        let body = self.order_body(o);
        let resp = client
            .post(format!("{}/v2/orders", self.base_url()))
            .header("APCA-API-KEY-ID", k)
            .header("APCA-API-SECRET-KEY", s)
            .header("content-type", "application/json")
            .json(&body)
            .send()
            .await;

        let submitted = match resp {
            Ok(r) if r.status().is_success() => {
                r.json::<AlpacaOrderResp>().await.map_err(|e| ConnectorError::Network(e.to_string()))?
            }
            Ok(r) => {
                let code = r.status().as_u16();
                let msg = r.text().await.unwrap_or_default();
                // 422 with a duplicate client_order_id means a previous attempt
                // *did* land — adopt that order instead of double-submitting.
                if msg.contains("client_order_id") {
                    self.lookup_by_client_id(&client, k, s, &o.client_order_id).await?
                } else {
                    return Err(if code == 401 || code == 403 {
                        ConnectorError::Auth(format!("HTTP {code}"))
                    } else {
                        ConnectorError::Rejected(format!("submit {code}: {msg}"))
                    });
                }
            }
            Err(e) => {
                // The request may or may not have reached Alpaca. Look it up by
                // the deterministic client id before deciding it failed.
                match self.lookup_by_client_id(&client, k, s, &o.client_order_id).await {
                    Ok(found) => found,
                    Err(_) => return Err(ConnectorError::Network(e.to_string())),
                }
            }
        };

        let final_state = self.resolve(&client, k, s, &submitted).await?;
        self.to_fill(o, final_state)
    }

    /// Poll to a terminal state; on timeout, cancel and re-read so a partial
    /// fill is still accounted for and nothing is left working.
    async fn resolve(
        &self,
        client: &reqwest::Client,
        k: &str,
        s: &str,
        submitted: &AlpacaOrderResp,
    ) -> Result<AlpacaOrderResp, ConnectorError> {
        if submitted.is_terminal() {
            return Ok(submitted.clone());
        }
        for _ in 0..20 {
            tokio::time::sleep(Duration::from_millis(500)).await;
            let Ok(o) = self.order_by_id(client, k, s, &submitted.id).await else { continue };
            if o.is_terminal() {
                return Ok(o);
            }
        }
        // Still working after ~10s. Pull it, then read whatever actually filled.
        let _ = client
            .delete(format!("{}/v2/orders/{}", self.base_url(), submitted.id))
            .header("APCA-API-KEY-ID", k)
            .header("APCA-API-SECRET-KEY", s)
            .send()
            .await;
        tokio::time::sleep(Duration::from_millis(750)).await;
        self.order_by_id(client, k, s, &submitted.id).await
    }

    async fn order_by_id(
        &self,
        client: &reqwest::Client,
        k: &str,
        s: &str,
        id: &str,
    ) -> Result<AlpacaOrderResp, ConnectorError> {
        let resp = client
            .get(format!("{}/v2/orders/{id}", self.base_url()))
            .header("APCA-API-KEY-ID", k)
            .header("APCA-API-SECRET-KEY", s)
            .send()
            .await
            .map_err(|e| ConnectorError::Network(e.to_string()))?;
        if !resp.status().is_success() {
            return Err(ConnectorError::Rejected(format!("order lookup {}", resp.status())));
        }
        resp.json().await.map_err(|e| ConnectorError::Network(e.to_string()))
    }

    async fn lookup_by_client_id(
        &self,
        client: &reqwest::Client,
        k: &str,
        s: &str,
        client_order_id: &str,
    ) -> Result<AlpacaOrderResp, ConnectorError> {
        let resp = client
            .get(format!(
                "{}/v2/orders:by_client_order_id?client_order_id={client_order_id}",
                self.base_url()
            ))
            .header("APCA-API-KEY-ID", k)
            .header("APCA-API-SECRET-KEY", s)
            .send()
            .await
            .map_err(|e| ConnectorError::Network(e.to_string()))?;
        if !resp.status().is_success() {
            return Err(ConnectorError::Rejected("no order for that client id".into()));
        }
        resp.json().await.map_err(|e| ConnectorError::Network(e.to_string()))
    }

    /// Turn a terminal order into a [`Fill`], or an error naming what happened.
    /// A partial fill is a success — the engine must book the shares it owns.
    fn to_fill(&self, o: &AlpacaOrder, done: AlpacaOrderResp) -> Result<Fill, ConnectorError> {
        let qty = done.filled();
        if qty <= 0.0 {
            return Err(ConnectorError::Rejected(match done.status.as_str() {
                "rejected" => "broker rejected the order".into(),
                "expired" => "order expired unfilled".into(),
                "canceled" | "cancelled" => "cancelled unfilled (no liquidity inside the limit)".into(),
                other => format!("unfilled ({other})"),
            }));
        }
        let price = done
            .avg_price()
            .ok_or_else(|| ConnectorError::Rejected("filled but no average price".into()))?;
        Ok(Fill {
            order_id: done.id,
            market_id: format!("alpaca:{}", o.symbol),
            side: o.side,
            qty,
            price,
            fee: 0.0, // Alpaca US equities are commission-free
            ts: chrono::Utc::now().timestamp_millis(),
        })
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

    /// Trait-level entry point. `market_id` carries the ticker (e.g. "AAPL").
    /// Callers that know whether an order closes a position should prefer
    /// [`AlpacaConnector::submit`] so the fractional-short guard can tell the
    /// difference.
    async fn place_order(&self, req: OrderRequest) -> Result<Fill, ConnectorError> {
        let order = AlpacaOrder {
            symbol: req.market_id.clone(),
            side: req.side,
            sizing: Sizing::Shares(req.qty),
            ref_price: req.limit_price.unwrap_or(0.0),
            client_order_id: format!("pythia-{}", uuid::Uuid::new_v4()),
            reduce_only: req.side == Side::Sell,
        };
        let conn = if req.order_type == OrderType::Market {
            // The caller explicitly asked for a market order.
            AlpacaConnector {
                key_id: self.key_id.clone(),
                secret: self.secret.clone(),
                paper_endpoint: self.paper_endpoint,
                slippage_bps: 0.0,
                extended_hours: self.extended_hours,
            }
        } else {
            AlpacaConnector {
                key_id: self.key_id.clone(),
                secret: self.secret.clone(),
                paper_endpoint: self.paper_endpoint,
                slippage_bps: self.slippage_bps,
                extended_hours: self.extended_hours,
            }
        };
        conn.submit(&order).await
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

#[cfg(test)]
mod tests {
    use super::*;

    fn conn() -> AlpacaConnector {
        AlpacaConnector::new(Some("k".into()), Some("s".into()), true)
    }

    fn order(side: Side, sizing: Sizing) -> AlpacaOrder {
        AlpacaOrder {
            symbol: "AAPL".into(),
            side,
            sizing,
            ref_price: 200.0,
            client_order_id: "pythia-test-1".into(),
            reduce_only: false,
        }
    }

    #[test]
    fn whole_share_orders_get_a_marketable_limit_band() {
        let body = conn().order_body(&order(Side::Buy, Sizing::Shares(3.0)));
        assert_eq!(body["type"], "limit");
        // 25bps above a $200 reference.
        assert_eq!(body["limit_price"], "200.50");
        assert_eq!(body["qty"], "3.000000");
        assert_eq!(body["client_order_id"], "pythia-test-1");
    }

    #[test]
    fn sell_limit_sits_below_the_reference() {
        let body = conn().order_body(&order(Side::Sell, Sizing::Shares(3.0)));
        assert_eq!(body["limit_price"], "199.50");
        assert_eq!(body["side"], "sell");
    }

    #[test]
    fn fractional_and_notional_orders_stay_market() {
        // Alpaca only accepts fractional/notional sizing on market DAY orders,
        // so the limit band has to be dropped rather than silently 422 at submit.
        let frac = conn().order_body(&order(Side::Buy, Sizing::Shares(1.5)));
        assert_eq!(frac["type"], "market");
        assert!(frac.get("limit_price").is_none());

        let notional = conn().order_body(&order(Side::Buy, Sizing::Notional(250.0)));
        assert_eq!(notional["type"], "market");
        assert_eq!(notional["notional"], "250.00");
        assert!(notional.get("qty").is_none(), "qty and notional are mutually exclusive");
    }

    #[test]
    fn zero_slippage_means_a_plain_market_order() {
        let c = conn().with_slippage_bps(0.0);
        let body = c.order_body(&order(Side::Buy, Sizing::Shares(3.0)));
        assert_eq!(body["type"], "market");
    }

    #[tokio::test]
    async fn rejects_a_fractional_short_before_it_reaches_the_venue() {
        let err = conn().submit(&order(Side::Sell, Sizing::Shares(1.5))).await.unwrap_err();
        assert!(err.to_string().contains("fractional short"), "got: {err}");
    }

    #[test]
    fn partial_fills_are_booked_not_discarded() {
        // A cancelled-after-partial order still moved shares; dropping it would
        // leave the engine flat on paper and long in reality.
        let done = AlpacaOrderResp {
            id: "o1".into(),
            status: "canceled".into(),
            filled_qty: Some("2".into()),
            filled_avg_price: Some("201.25".into()),
        };
        let fill = conn().to_fill(&order(Side::Buy, Sizing::Shares(5.0)), done).unwrap();
        assert_eq!(fill.qty, 2.0);
        assert_eq!(fill.price, 201.25);
        assert_eq!(fill.market_id, "alpaca:AAPL");
    }

    #[test]
    fn a_zero_fill_is_an_error_with_the_reason() {
        let done = AlpacaOrderResp {
            id: "o1".into(),
            status: "rejected".into(),
            filled_qty: Some("0".into()),
            filled_avg_price: None,
        };
        let err = conn().to_fill(&order(Side::Buy, Sizing::Shares(5.0)), done).unwrap_err();
        assert!(err.to_string().contains("broker rejected"), "got: {err}");
    }

    #[test]
    fn extended_hours_converts_notional_to_whole_shares() {
        // Alpaca rejects notional and fractional sizing outside regular hours,
        // so a dollar-sized entry has to become whole shares before it's sent.
        let c = conn().with_extended_hours(true);
        let normalized = c.normalized_for_session(&order(Side::Buy, Sizing::Notional(750.0))).unwrap();
        assert_eq!(normalized.sizing, Sizing::Shares(3.0), "$750 at $200 → 3 whole shares");

        let frac = c.normalized_for_session(&order(Side::Buy, Sizing::Shares(4.8))).unwrap();
        assert_eq!(frac.sizing, Sizing::Shares(4.0), "rounds down, never up");

        let body = c.order_body(&normalized);
        assert_eq!(body["type"], "limit", "extended hours is limit-only");
        assert_eq!(body["extended_hours"], true);
        assert!(body.get("notional").is_none());
    }

    #[test]
    fn extended_hours_refuses_an_order_too_small_to_round() {
        let c = conn().with_extended_hours(true);
        let err = c.normalized_for_session(&order(Side::Buy, Sizing::Notional(150.0))).unwrap_err();
        assert!(err.to_string().contains("whole share"), "got: {err}");
    }

    #[test]
    fn extended_hours_widens_the_limit_band() {
        // A 25bps band inside a thin after-hours spread simply never fills.
        let day = conn().order_body(&order(Side::Buy, Sizing::Shares(3.0)));
        let ext = conn().with_extended_hours(true).order_body(&order(Side::Buy, Sizing::Shares(3.0)));
        let day_px: f64 = day["limit_price"].as_str().unwrap().parse().unwrap();
        let ext_px: f64 = ext["limit_price"].as_str().unwrap().parse().unwrap();
        assert!(ext_px > day_px, "after-hours buy limit {ext_px} should sit above the RTH one {day_px}");
    }

    #[test]
    fn extended_hours_forces_a_limit_even_with_slippage_protection_off() {
        // 0 bps means "plain market order" during the day, but a market order
        // outside RTH is rejected outright, so the band is not optional there.
        let c = conn().with_slippage_bps(0.0).with_extended_hours(true);
        let body = c.order_body(&order(Side::Buy, Sizing::Shares(3.0)));
        assert_eq!(body["type"], "limit");
    }

    #[test]
    fn extended_session_window_is_read_from_the_calendar() {
        let day = CalendarDay {
            date: "2026-07-24".into(),
            open: "09:30".into(),
            close: "16:00".into(),
            session_open: "04:00".into(),
            session_close: "20:00".into(),
        };
        assert!(!day.in_extended_session(3 * 60 + 59), "03:59 is before the pre-market open");
        assert!(day.in_extended_session(4 * 60), "04:00 opens the pre-market");
        assert!(day.in_extended_session(17 * 60 + 32), "17:32 is after-hours, still tradable");
        assert!(!day.in_extended_session(20 * 60), "20:00 closes it");
        assert_eq!(day.session_end(), "20:00");
    }

    #[test]
    fn a_day_without_a_session_window_falls_back_to_regular_hours() {
        let day = CalendarDay {
            date: "2026-07-24".into(),
            open: "09:30".into(),
            close: "16:00".into(),
            session_open: String::new(),
            session_close: String::new(),
        };
        assert!(day.in_extended_session(10 * 60));
        assert!(!day.in_extended_session(17 * 60), "no session data → don't invent an after-hours window");
    }

    #[test]
    fn exchange_time_comes_from_the_brokers_own_offset() {
        // Parsing the exchange's offset-aware timestamp gives New York wall
        // clock without a timezone database — and without getting DST wrong.
        let clock = MarketClock {
            timestamp: "2026-07-24T17:32:00-04:00".into(),
            is_open: false,
            next_open: "2026-07-27T09:30:00-04:00".into(),
            next_close: "2026-07-27T16:00:00-04:00".into(),
        };
        let (date, minute) = clock.exchange_now().expect("parsed");
        assert_eq!(date, "2026-07-24");
        assert_eq!(minute, 17 * 60 + 32);
    }

    #[test]
    fn hhmm_accepts_both_shapes_the_calendar_has_used() {
        assert_eq!(hhmm_to_minutes("09:30"), Some(570));
        assert_eq!(hhmm_to_minutes("0930"), Some(570));
        assert_eq!(hhmm_to_minutes("2000"), Some(1200));
        assert_eq!(hhmm_to_minutes("nonsense"), None);
        assert_eq!(hhmm_to_minutes("2560"), None);
    }

    #[test]
    fn terminal_states_cover_every_dead_order() {
        for s in ["filled", "canceled", "expired", "rejected", "done_for_day", "suspended"] {
            let o = AlpacaOrderResp { id: "o".into(), status: s.into(), filled_qty: None, filled_avg_price: None };
            assert!(o.is_terminal(), "{s} should be terminal");
        }
        for s in ["new", "accepted", "pending_new", "partially_filled"] {
            let o = AlpacaOrderResp { id: "o".into(), status: s.into(), filled_qty: None, filled_avg_price: None };
            assert!(!o.is_terminal(), "{s} is still working");
        }
    }

    #[test]
    fn pdt_guard_only_bites_below_the_equity_floor() {
        let mut a = AlpacaAccount {
            status: "ACTIVE".into(),
            currency: "USD".into(),
            cash: "1000".into(),
            buying_power: "2000".into(),
            portfolio_value: "10000".into(),
            equity: "10000".into(),
            pattern_day_trader: false,
            daytrade_count: 3,
            trading_blocked: false,
            account_blocked: false,
            shorting_enabled: true,
            paper: true,
        };
        assert!(a.day_trade_limit_reached(), "3 day trades under $25k is the cap");
        a.daytrade_count = 2;
        assert!(!a.day_trade_limit_reached());
        a.daytrade_count = 9;
        a.equity = "50000".into();
        assert!(!a.day_trade_limit_reached(), "PDT rule does not apply above $25k");
    }

    #[test]
    fn restricted_accounts_are_named() {
        let base = AlpacaAccount {
            status: "ACTIVE".into(),
            currency: "USD".into(),
            cash: "0".into(),
            buying_power: "0".into(),
            portfolio_value: "0".into(),
            equity: "0".into(),
            pattern_day_trader: false,
            daytrade_count: 0,
            trading_blocked: false,
            account_blocked: false,
            shorting_enabled: false,
            paper: true,
        };
        assert!(base.is_restricted().is_none());

        let blocked = AlpacaAccount { trading_blocked: true, ..base.clone() };
        assert_eq!(blocked.is_restricted().as_deref(), Some("trading blocked"));

        let inactive = AlpacaAccount { status: "ONBOARDING".into(), ..base };
        assert!(inactive.is_restricted().unwrap().contains("ONBOARDING"));
    }
}
