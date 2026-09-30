//! Alpaca connector — US equities (and, for accounts that have it, Alpaca's own
//! 24/7 crypto book).
//!
//!   · Paper base:   https://paper-api.alpaca.markets  (start here — real API, no real money)
//!   · Live base:    https://api.alpaca.markets
//!   · Auth:         APCA-API-KEY-ID + APCA-API-SECRET-KEY headers
//!
//! Alpaca issues a **separate** key pair per account, and each pair only
//! authenticates against its own endpoint. The caller picks the pair that
//! matches `paper_endpoint` (see `vault::alpaca_slot`); this connector never
//! falls back to the other account's keys.
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
//! ## Why submission is more than one POST
//!
//! 1. **A network error is not a rejection.** If the connection drops after the
//!    POST, the order may well have reached the exchange. Every submission
//!    carries a deterministic `client_order_id`, so a retry either wins the race
//!    or gets a duplicate error we resolve by looking the order up.
//! 2. **Entries go out in dollars, exits in shares.** Notional sizing needs no
//!    client-side rounding and never over-spends, but it cannot express "sell
//!    exactly what I hold".
//! 3. **Outside regular hours Alpaca takes whole-share DAY limit orders only.**
//!    Dollar-sized entries are converted to whole shares and the limit band is
//!    widened, instead of eating a 422 at the venue.
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
    /// Cap on marketable-limit slippage, in basis points. 0 → plain market order.
    slippage_bps: f64,
    /// Trade the pre/post-market sessions. Alpaca only accepts extended-hours
    /// orders as whole-share DAY limit orders, never market or notional.
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

/// A snapshot of the Alpaca account — used by the UI's connection test, the
/// PDT guard, preflight and the broker-status refresh. Safe, read-only; never
/// places an order.
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
    /// Whether the venue will accept *any* order right now.
    fn tradable(&self) -> Result<(), ConnectorError> {
        if self.account_blocked {
            return Err(ConnectorError::Preflight("Alpaca account is blocked".into()));
        }
        if self.trading_blocked {
            return Err(ConnectorError::Preflight("Alpaca trading is blocked on this account".into()));
        }
        if !self.status.eq_ignore_ascii_case("ACTIVE") {
            return Err(ConnectorError::Preflight(format!(
                "Alpaca account status is {} (needs ACTIVE)",
                self.status
            )));
        }
        Ok(())
    }
}

/// `GET /v2/clock`: the market session, straight from the broker. Beats
/// guessing from a local clock: it already knows about holidays, half-days and
/// DST.
#[derive(Debug, Clone, Deserialize, serde::Serialize)]
#[serde(rename_all(serialize = "camelCase", deserialize = "snake_case"))]
pub struct MarketClock {
    #[serde(default)]
    pub timestamp: String,
    pub is_open: bool,
    #[serde(default)]
    pub next_open: String,
    #[serde(default)]
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
        let open = hhmm_to_minutes(&self.session_open).or_else(|| hhmm_to_minutes(&self.open));
        let close = hhmm_to_minutes(&self.session_close).or_else(|| hhmm_to_minutes(&self.close));
        match (open, close) {
            (Some(o), Some(c)) => minute_of_day >= o && minute_of_day < c,
            _ => false,
        }
    }

    /// Exchange-local end of the extended session, for display.
    pub fn session_end(&self) -> String {
        if self.session_close.is_empty() {
            self.close.clone()
        } else {
            self.session_close.clone()
        }
    }
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

/// Everything the Alpaca order path needs, after the venue-agnostic
/// [`OrderRequest`] has been translated.
#[derive(Debug, Clone)]
pub struct AlpacaOrder {
    pub symbol: String,
    pub side: Side,
    pub sizing: Sizing,
    /// Reference price, used to derive the marketable-limit band.
    pub ref_price: f64,
    /// An explicit limit chosen upstream (the execution policy resting an order
    /// inside the spread). Sent as-is; `None` means "marketable".
    pub limit_price: Option<f64>,
    /// Stable id for idempotent resubmission. Empty means "none".
    pub client_order_id: String,
    /// True when this order reduces or closes an existing position. Closing
    /// orders are allowed to be fractional; opening shorts are not.
    pub reduce_only: bool,
    /// Alpaca's own crypto book: 24/7, GTC, never an extended-hours order.
    pub crypto: bool,
}

impl AlpacaConnector {
    pub fn new(key_id: Option<String>, secret: Option<String>, paper_endpoint: bool) -> Self {
        Self {
            key_id,
            secret,
            paper_endpoint,
            slippage_bps: 25.0,
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

    /// Cap on how far a marketable limit may cross the book. 0 disables the
    /// limit and sends a plain market order (during regular hours only).
    pub fn with_slippage_bps(mut self, bps: f64) -> Self {
        self.slippage_bps = bps.max(0.0);
        self
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
                    "HTTP {code} on {what}: are these {} keys? Paper and live accounts have separate key pairs; \
                     check they are saved in the right slot",
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

    /// GET a JSON resource under the trading API and decode it.
    async fn get_json<T: serde::de::DeserializeOwned>(&self, path: &str, what: &str) -> Result<T, ConnectorError> {
        let v = self.send(self.req(reqwest::Method::GET, path)?, what).await?;
        serde_json::from_value(v).map_err(|e| ConnectorError::Network(format!("bad {what} payload: {e}")))
    }

    /// Read-only account check for the UI's "test connection" button, the PDT
    /// guard and the broker-status refresh.
    pub async fn account(&self) -> Result<AlpacaAccount, ConnectorError> {
        let mut acct: AlpacaAccount = self.get_json("/v2/account", "account").await?;
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

    /// Is the US equity market open? Asked of the broker, never inferred
    /// locally. Cached briefly — the tick loop asks often.
    pub async fn clock(&self) -> Result<MarketClock, ConnectorError> {
        if let Some((at, c)) = self.clock_cache.lock().unwrap().clone() {
            if now_ms() - at < CLOCK_TTL_MS {
                return Ok(c);
            }
        }
        let c: MarketClock = self.get_json("/v2/clock", "clock").await?;
        *self.clock_cache.lock().unwrap() = Some((now_ms(), c.clone()));
        Ok(c)
    }

    /// Trading calendar for one exchange-local date.
    pub async fn calendar(&self, date: &str) -> Result<Vec<CalendarDay>, ConnectorError> {
        self.get_json(&format!("/v2/calendar?start={date}&end={date}"), "calendar").await
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

    async fn asset(&self, symbol: &str) -> Result<AssetInfo, ConnectorError> {
        if let Some((at, a)) = self.asset_cache.lock().unwrap().get(symbol).cloned() {
            if now_ms() - at < ASSET_TTL_MS {
                return Ok(a);
            }
        }
        // Crypto pairs carry a slash ("BTC/USD"); it has to survive the path.
        let path = format!("/v2/assets/{}", symbol.replace('/', "%2F"));
        let a: AssetInfo = self.get_json(&path, "asset").await?;
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

    /// Cancel every open order — the panic button behind the kill switch.
    pub async fn cancel_all_orders(&self) -> Result<(), ConnectorError> {
        self.send(self.req(reqwest::Method::DELETE, "/v2/orders")?, "cancel all").await?;
        Ok(())
    }

    async fn order_by_client_id(&self, client_order_id: &str) -> Result<Value, ConnectorError> {
        let path = format!("/v2/orders:by_client_order_id?client_order_id={client_order_id}");
        self.send(self.req(reqwest::Method::GET, &path)?, "order lookup").await
    }

    /// Build the submission body using this connector's own session setting.
    /// See [`Sizing`] for why exits are share-based.
    fn order_body(&self, o: &AlpacaOrder) -> Value {
        self.order_body_for(o, self.extended_hours)
    }

    /// Build the submission body for a given session: `extended` means the
    /// order is going into the pre/post-market session.
    fn order_body_for(&self, o: &AlpacaOrder, extended: bool) -> Value {
        let mut body = serde_json::json!({
            "symbol": o.symbol,
            "side": o.side.as_str(),
            // Crypto is 24/7 and wants GTC; equities use DAY so a stale order
            // cannot wake up and fill days later.
            "time_in_force": if o.crypto { "gtc" } else { "day" },
        });
        if !o.client_order_id.is_empty() {
            body["client_order_id"] = serde_json::json!(o.client_order_id);
        }
        match o.sizing {
            Sizing::Shares(q) => body["qty"] = serde_json::json!(format!("{q:.6}")),
            Sizing::Notional(n) => body["notional"] = serde_json::json!(format!("{n:.2}")),
        }

        // An explicit limit from the execution policy is honoured as-is: it is
        // the whole point of resting an order inside the spread.
        if let Some(limit) = o.limit_price.filter(|l| *l > 0.0) {
            body["type"] = serde_json::json!("limit");
            body["limit_price"] = serde_json::json!(format!("{limit:.2}"));
            if extended {
                body["extended_hours"] = serde_json::json!(true);
            }
            return body;
        }

        // A marketable limit gets market-like fill probability while refusing to
        // pay through a gapped or thin book. Outside regular hours a limit price
        // is not optional — Alpaca rejects market and notional orders there — so
        // the band is forced on even if slippage protection was configured off.
        let fractional = matches!(o.sizing, Sizing::Notional(_))
            || matches!(o.sizing, Sizing::Shares(q) if q.fract() > f64::EPSILON);
        let want_limit = (self.slippage_bps > 0.0 || extended) && o.ref_price > 0.0;
        if want_limit && !fractional {
            // Outside regular hours the book is thin, so a 25bps band often
            // sits inside the spread and never fills. Widen it there — this is
            // the price of trading a session with a fraction of the liquidity.
            let bps = if extended { self.slippage_bps.max(75.0) } else { self.slippage_bps };
            let band = o.ref_price * (bps / 10_000.0);
            let limit = match o.side {
                Side::Buy => o.ref_price + band,
                Side::Sell => (o.ref_price - band).max(0.01),
            };
            body["type"] = serde_json::json!("limit");
            body["limit_price"] = serde_json::json!(format!("{limit:.2}"));
            if extended {
                body["extended_hours"] = serde_json::json!(true);
            }
        } else {
            // Fractional quantities and notional orders are market-only at Alpaca.
            body["type"] = serde_json::json!("market");
        }
        body
    }

    /// Reshape an order for this connector's session setting.
    fn normalized_for_session(&self, o: &AlpacaOrder) -> Result<AlpacaOrder, ConnectorError> {
        self.normalized_for_session_in(o, self.extended_hours)
    }

    /// Reshape an order for the session it will actually trade in.
    ///
    /// Outside regular hours Alpaca accepts **whole-share DAY limit orders
    /// only** — no market orders, no notional sizing, no fractions. The engine
    /// sizes entries in dollars because that's better during the day, so those
    /// have to be converted here rather than rejected at the venue with a 422.
    fn normalized_for_session_in(&self, o: &AlpacaOrder, extended: bool) -> Result<AlpacaOrder, ConnectorError> {
        if !extended {
            return Ok(o.clone());
        }
        if o.ref_price <= 0.0 && o.limit_price.is_none() {
            return Err(ConnectorError::Rejected(
                "extended-hours orders need a limit price, but no reference price was available".into(),
            ));
        }
        let px = if o.ref_price > 0.0 { o.ref_price } else { o.limit_price.unwrap_or(0.0) };
        let shares = match o.sizing {
            Sizing::Notional(n) => (n / px).floor(),
            Sizing::Shares(q) => q.floor(),
        };
        if shares < 1.0 {
            return Err(ConnectorError::Rejected(format!(
                "extended hours needs at least one whole share; sized to {shares:.4} at {px:.2}"
            )));
        }
        Ok(AlpacaOrder { sizing: Sizing::Shares(shares), ..o.clone() })
    }

    /// Submit an Alpaca order and return as soon as the venue acknowledges it.
    /// The engine's order state machine takes it from there.
    pub async fn submit(&self, o: &AlpacaOrder) -> Result<BrokerOrder, ConnectorError> {
        // Guard the one sizing Alpaca silently refuses: you cannot open a short
        // in fractional shares. Better to reject here with a readable reason
        // than to eat a 422 from the venue. Checked before any network call.
        if o.side == Side::Sell && !o.reduce_only {
            if let Sizing::Shares(q) = o.sizing {
                if q.fract() > f64::EPSILON {
                    return Err(ConnectorError::Rejected(
                        "fractional short selling is not supported by Alpaca".into(),
                    ));
                }
            }
        }

        // Extended-hours shape only when opted in AND the regular session is
        // not running. An unknown clock reads as "not open": the whole-share
        // limit shape is accepted in both sessions, a market order is not.
        let extended = self.extended_hours
            && !o.crypto
            && !self.clock().await.map(|c| c.is_open).unwrap_or(false);
        let o = self.normalized_for_session_in(o, extended)?;
        let body = self.order_body_for(&o, extended);
        let cid = o.client_order_id.as_str();

        let rb = self
            .req(reqwest::Method::POST, "/v2/orders")?
            .header("content-type", "application/json")
            .json(&body);
        match self.send(rb, "submit").await {
            Ok(v) => parse_order(&v),
            // 422 with a duplicate client_order_id means a previous attempt
            // *did* land — adopt that order instead of double-submitting.
            Err(ConnectorError::Rejected(msg)) if !cid.is_empty() && msg.contains("client_order_id") => {
                parse_order(&self.order_by_client_id(cid).await?)
            }
            // The request may or may not have reached Alpaca. Look it up by the
            // deterministic client id before deciding it failed.
            Err(ConnectorError::Network(e)) if !cid.is_empty() => match self.order_by_client_id(cid).await {
                Ok(v) => parse_order(&v),
                Err(_) => Err(ConnectorError::Network(e)),
            },
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
        "canceled" | "cancelled" | "pending_cancel" | "done_for_day" => BrokerOrderStatus::Canceled,
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
        avg_price: num(v.get("filled_avg_price")).filter(|p| *p > 0.0),
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

    /// Translate the venue-agnostic request and submit it.
    ///
    /// Entries (buy, market, fractionable equity) go out in dollars; exits,
    /// limits and crypto go out in shares. Extended-hours reshaping and the
    /// marketable-limit band happen in [`AlpacaConnector::submit`].
    async fn submit_order(&self, req: OrderRequest) -> Result<BrokerOrder, ConnectorError> {
        let asset = self.asset(&req.symbol).await.ok();
        let crypto = asset.as_ref().map(AssetInfo::is_crypto).unwrap_or_else(|| req.symbol.contains('/'));
        let fractionable = asset.as_ref().map(|a| a.fractionable).unwrap_or(true);
        let ref_price = req.ref_price.or(req.limit_price).unwrap_or(0.0);
        let limit_price = if req.order_type == OrderType::Limit { req.limit_price } else { None };

        let notional_entry = req.side == Side::Buy
            && !req.reduce_only
            && limit_price.is_none()
            && !crypto
            && fractionable
            && ref_price > 0.0;
        let sizing = if notional_entry {
            Sizing::Notional((req.qty * ref_price * 100.0).round() / 100.0)
        } else {
            Sizing::Shares(req.qty)
        };

        let order = AlpacaOrder {
            symbol: req.symbol.clone(),
            side: req.side,
            sizing,
            ref_price,
            limit_price,
            client_order_id: req.client_order_id.clone().unwrap_or_default(),
            reduce_only: req.reduce_only,
            crypto,
        };
        self.submit(&order).await
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

    fn conn() -> AlpacaConnector {
        AlpacaConnector::new(Some("k".into()), Some("s".into()), true)
    }

    fn order(side: Side, sizing: Sizing) -> AlpacaOrder {
        AlpacaOrder {
            symbol: "AAPL".into(),
            side,
            sizing,
            ref_price: 200.0,
            limit_price: None,
            client_order_id: "pythia-test-1".into(),
            reduce_only: false,
            crypto: false,
        }
    }

    fn account(status: &str) -> AlpacaAccount {
        AlpacaAccount {
            status: status.into(),
            currency: "USD".into(),
            cash: "1000".into(),
            buying_power: "2000".into(),
            portfolio_value: "1000".into(),
            equity: "1000".into(),
            pattern_day_trader: false,
            daytrade_count: 0,
            trading_blocked: false,
            account_blocked: false,
            shorting_enabled: false,
            paper: true,
        }
    }

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
    fn terminal_states_cover_every_dead_order() {
        for s in ["filled", "canceled", "cancelled", "expired", "rejected", "done_for_day", "suspended"] {
            assert!(map_status(s).is_terminal(), "{s} should be terminal");
        }
        for s in ["new", "accepted", "pending_new", "partially_filled"] {
            assert!(!map_status(s).is_terminal(), "{s} is still working");
        }
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
    fn a_cancel_that_caught_a_partial_still_reports_the_shares() {
        // A cancelled-after-partial order still moved shares; dropping it would
        // leave the engine flat on paper and long in reality. The engine books
        // `filled_qty` whatever the terminal status says.
        let v: Value = serde_json::from_str(
            r#"{"id":"o1","status":"canceled","filled_qty":"2","filled_avg_price":"201.25"}"#,
        )
        .unwrap();
        let o = parse_order(&v).unwrap();
        assert!(o.status.is_terminal());
        assert_eq!(o.filled_qty, 2.0);
        assert_eq!(o.avg_price, Some(201.25));
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
        let mut a = account("ACTIVE");
        assert!(a.tradable().is_ok());
        a.trading_blocked = true;
        assert!(a.tradable().is_err());
        a.trading_blocked = false;
        a.status = "ONBOARDING".into();
        assert!(a.tradable().is_err());
    }

    #[test]
    fn qty_rounding_respects_a_non_fractionable_asset() {
        let c = conn();
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

    #[test]
    fn whole_share_orders_get_a_marketable_limit_band() {
        let body = conn().order_body(&order(Side::Buy, Sizing::Shares(3.0)));
        assert_eq!(body["type"], "limit");
        // 25bps above a $200 reference.
        assert_eq!(body["limit_price"], "200.50");
        assert_eq!(body["qty"], "3.000000");
        assert_eq!(body["client_order_id"], "pythia-test-1");
        assert_eq!(body["time_in_force"], "day");
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

    #[test]
    fn an_explicit_limit_from_the_execution_policy_is_sent_as_is() {
        // A passive order resting inside the spread must not be overwritten by
        // the marketable band, or the execution policy never gets to rest.
        let mut o = order(Side::Buy, Sizing::Shares(3.0));
        o.limit_price = Some(199.9);
        let body = conn().order_body(&o);
        assert_eq!(body["type"], "limit");
        assert_eq!(body["limit_price"], "199.90");
    }

    #[test]
    fn crypto_orders_are_good_til_cancelled() {
        let mut o = order(Side::Buy, Sizing::Shares(0.01));
        o.symbol = "BTC/USD".into();
        o.crypto = true;
        assert_eq!(conn().order_body(&o)["time_in_force"], "gtc");
    }

    #[tokio::test]
    async fn rejects_a_fractional_short_before_it_reaches_the_venue() {
        let err = conn().submit(&order(Side::Sell, Sizing::Shares(1.5))).await.unwrap_err();
        assert!(err.to_string().contains("fractional short"), "got: {err}");
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
    fn a_clock_without_a_timestamp_still_parses() {
        // Older or trimmed responses omit `timestamp`; the open flag is what
        // preflight needs, and the session check then reads "no session".
        let c: MarketClock = serde_json::from_str(r#"{"is_open":true}"#).unwrap();
        assert!(c.is_open);
        assert!(c.exchange_now().is_none());
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
    fn pdt_guard_only_bites_below_the_equity_floor() {
        let mut a = AlpacaAccount { equity: "10000".into(), daytrade_count: 3, ..account("ACTIVE") };
        assert!(a.day_trade_limit_reached(), "3 day trades under $25k is the cap");
        a.daytrade_count = 2;
        assert!(!a.day_trade_limit_reached());
        a.daytrade_count = 9;
        a.equity = "50000".into();
        assert!(!a.day_trade_limit_reached(), "PDT rule does not apply above $25k");
    }

    #[test]
    fn restricted_accounts_are_named() {
        let base = account("ACTIVE");
        assert!(base.is_restricted().is_none());

        let blocked = AlpacaAccount { trading_blocked: true, ..base.clone() };
        assert_eq!(blocked.is_restricted().as_deref(), Some("trading blocked"));

        let inactive = AlpacaAccount { status: "ONBOARDING".into(), ..base };
        assert!(inactive.is_restricted().unwrap().contains("ONBOARDING"));
    }
}
