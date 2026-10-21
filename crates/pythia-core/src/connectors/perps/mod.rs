//! Perpetual futures on a venue's DEMO account: the one place a short can be
//! opened (`Venue::Perps`).
//!
//! The research lab's best result is a market-neutral long/short on perps
//! (M4, `research/lab/results/m4_residual.md`). It cannot trade on Alpaca,
//! which has no perps, so this module routes it to a perps venue's demo
//! environment: virtual money, real API round trips, real funding.
//!
//! Two venues speak the same small interface here:
//!
//! | | demo host (orders) | public data host (marks, funding, contracts) | symbol | funding |
//! |---|---|---|---|---|
//! | Kraken Futures | `https://demo-futures.kraken.com` | `https://futures.kraken.com` | `PF_XBTUSD` | hourly, pro rata for the part of the hour held |
//! | Bybit (linear) | `https://api-demo.bybit.com` | `https://api.bybit.com` | `BTCUSDT` | every 8 h (some 4 h or 1 h), whoever holds at the settlement |
//!
//! **Kraken shut its futures demo down on 2026-07-14** (Kraken support,
//! "API testing environment (derivatives)", updated 2026-07-07; checked
//! 2026-10-21: every path on the demo host answers a 301 to the Kraken
//! website). The connector is complete and fails closed with that sentence
//! while the host redirects, so it starts working again unchanged if Kraken
//! brings the demo back at the same address. Bybit's Demo Trading runs on
//! mainnet prices and trading rules and is the route that trades today. See
//! `docs/KRAKEN-FUTURES-DEMO.md`.
//!
//! **Demo only, by construction.** [`PerpConnector`] has no live mode: its
//! order host is the venue's demo host and nothing else. A real-money perps
//! order is refused by the engine, by `execution::Credentials` and here, in
//! that order (the owner has not cleared the legal question of trading
//! derivatives with real money).
//!
//! Quantities are in the venue's own contract units (one coin for Kraken's
//! `PF_` contracts and Bybit's `BTCUSDT`, a thousand coins for Bybit's
//! `1000PEPEUSDT`); the engine's perps market quotes that same unit, so a
//! notional divided by its price is always a quantity the venue understands.

pub mod bybit;
pub mod kraken_futures;

use super::{
    Balance, BrokerOrder, BrokerPosition, ConnectorError, MarketConnector, OpenOrder, OrderRequest, Venue,
};
use async_trait::async_trait;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::sync::{OnceLock, RwLock};
use std::time::Duration;

/// The perps venues Pythia can route demo orders to.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum PerpExchange {
    /// Kraken Futures, multi-collateral linear perps (`PF_` symbols).
    KrakenFutures,
    /// Bybit v5, category `linear` (USDT-margined perpetuals).
    Bybit,
}

/// Why the Kraken Futures demo cannot be reached, in the owner's words.
pub const KRAKEN_DEMO_GONE: &str = "Kraken shut its futures demo environment (demo-futures.kraken.com) down on \
     2026-07-14; the host now redirects to the Kraken website. Kraken has not named a replacement. Use Bybit Demo \
     Trading for perps (PYTHIA_PERPS_DEMO=bybit, docs/KRAKEN-FUTURES-DEMO.md) or run the autopilot on paper";

/// The one sentence every refused real-money perps order carries.
pub const PERPS_LIVE_REFUSED: &str = "Real-money perpetuals are switched off: Pythia trades perps on a demo account \
     or on paper only. The owner has not cleared the legal question of trading derivatives with real money \
     (docs/KRAKEN-FUTURES-DEMO.md)";

impl PerpExchange {
    pub const ALL: [PerpExchange; 2] = [PerpExchange::KrakenFutures, PerpExchange::Bybit];

    /// The id used in settings, in `PYTHIA_PERPS_DEMO`, and as the cost venue
    /// in `config/costs.json`.
    pub fn id(self) -> &'static str {
        match self {
            PerpExchange::KrakenFutures => "kraken_futures",
            PerpExchange::Bybit => "bybit_perps",
        }
    }

    pub fn label(self) -> &'static str {
        match self {
            PerpExchange::KrakenFutures => "Kraken Futures",
            PerpExchange::Bybit => "Bybit perps",
        }
    }

    /// `kraken_futures` / `kraken-futures` / `kraken`, `bybit_perps` / `bybit`.
    pub fn parse(s: &str) -> Option<PerpExchange> {
        match s.trim().to_ascii_lowercase().replace('-', "_").as_str() {
            "kraken_futures" | "krakenfutures" | "kraken" => Some(PerpExchange::KrakenFutures),
            "bybit_perps" | "bybit" | "bybit_linear" => Some(PerpExchange::Bybit),
            _ => None,
        }
    }

    /// The demo host orders go to. There is no live host in this module.
    pub fn demo_base(self) -> &'static str {
        match self {
            // https://support.kraken.com/articles/360024809011-api-testing-environment-derivatives
            PerpExchange::KrakenFutures => "https://demo-futures.kraken.com",
            // https://bybit-exchange.github.io/docs/v5/demo
            PerpExchange::Bybit => "https://api-demo.bybit.com",
        }
    }

    /// The public, key-less market data host (marks, contract specs and
    /// funding rates are the real market's).
    pub fn data_base(self) -> &'static str {
        match self {
            PerpExchange::KrakenFutures => "https://futures.kraken.com",
            PerpExchange::Bybit => "https://api.bybit.com",
        }
    }

    /// The published base-tier fee rates (maker, taker), as fractions. Used
    /// when the venue's own answer carries no fee (Kraken's fills do not).
    /// Kraken: <https://www.kraken.com/features/fee-schedule> (0.02 % / 0.05 %);
    /// Bybit: <https://www.bybit.com/en/help-center/article/Trading-Fee-Structure> (0.02 % / 0.055 %).
    pub fn fee_rates(self) -> (f64, f64) {
        match self {
            PerpExchange::KrakenFutures => (0.0002, 0.0005),
            PerpExchange::Bybit => (0.0002, 0.00055),
        }
    }

    /// How often funding settles when the venue does not say.
    pub fn default_funding_period_ms(self) -> i64 {
        match self {
            PerpExchange::KrakenFutures => 3_600_000,
            PerpExchange::Bybit => 8 * 3_600_000,
        }
    }
}

/// One perpetual contract as the venue lists it.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct PerpInstrument {
    /// The lab's coin name: `BTC`, `PEPE`.
    pub coin: String,
    /// The venue's symbol: `PF_XBTUSD`, `1000PEPEUSDT`.
    pub symbol: String,
    /// Order sizes are multiples of this, in contract units.
    pub qty_step: f64,
    /// Smallest order, in contract units.
    pub min_qty: f64,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub max_qty: Option<f64>,
    /// Price increment.
    pub tick: f64,
    /// How often funding settles on this contract.
    pub funding_period_ms: i64,
}

impl PerpInstrument {
    /// `qty` rounded down to the step, or 0 when that is below the minimum.
    pub fn round_qty(&self, qty: f64) -> f64 {
        let q = floor_to_step(qty.abs(), self.qty_step);
        let q = match self.max_qty {
            Some(m) if m > 0.0 => q.min(floor_to_step(m, self.qty_step)),
            _ => q,
        };
        if q + 1e-12 < self.min_qty {
            0.0
        } else {
            q
        }
    }
}

/// Round down to a multiple of `step` (a step of 0 leaves it alone), with a
/// little tolerance so 0.3 / 0.1 is 3 steps and not 2.
pub fn floor_to_step(qty: f64, step: f64) -> f64 {
    if step.is_nan() || step <= 0.0 || !qty.is_finite() {
        return qty;
    }
    let n = (qty / step + 1e-9).floor();
    let decimals = decimals_of(step);
    let v = n * step;
    let f = 10f64.powi(decimals as i32);
    (v * f).round() / f
}

/// Decimal places a step needs (0.001 -> 3, 1 -> 0, 1000 -> 0).
pub fn decimals_of(step: f64) -> usize {
    if step.is_nan() || step <= 0.0 || step >= 1.0 {
        return 0;
    }
    let mut d = 0;
    let mut s = step;
    while d < 12 && (s - s.round()).abs() > 1e-9 {
        s *= 10.0;
        d += 1;
    }
    d
}

/// The mark and funding of one contract right now.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct PerpTicker {
    pub symbol: String,
    pub mark: f64,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub bid: Option<f64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub ask: Option<f64>,
    /// The funding rate the venue shows now, relative (0.0001 = 1 bp) per
    /// funding period; positive means longs pay shorts.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub funding_rate: Option<f64>,
    #[serde(default)]
    pub suspended: bool,
}

/// One settled funding period of one contract.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct FundingPoint {
    /// When the period ended and the funding was paid (epoch ms).
    pub settled_ms: i64,
    /// How long the period was.
    pub period_ms: i64,
    /// Relative rate for the period: a long pays `rate x notional`, a short
    /// receives it (and the other way round when it is negative).
    pub rate: f64,
    /// The same in dollars per contract unit, when the venue publishes it
    /// (Kraken's absolute `fundingRate`). Preferred: it needs no mark.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub per_unit_usd: Option<f64>,
    /// Paid for the part of the period a position was held (Kraken), not only
    /// by whoever holds at the settlement (Bybit).
    #[serde(default)]
    pub prorated: bool,
}

/// What the demo account has for margin.
#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct PerpAccount {
    /// Account value in USD including open P&L.
    pub equity: f64,
    /// What new positions can still use as initial margin.
    pub available_margin: f64,
    pub initial_margin: f64,
    /// Funding accrued on open positions, not yet in the balance (Kraken).
    #[serde(default)]
    pub unrealized_funding: f64,
}

// ── coins and symbols ─────────────────────────────────────────────────────

/// The coin a USDT-quoted perp symbol trades: `BTCUSDT` -> `BTC`,
/// `1000PEPEUSDT` -> `PEPE`, `SHIB1000USDT` -> `SHIB`, `MATICUSDT` -> `POL`.
pub fn coin_of_usdt_symbol(symbol: &str) -> Option<String> {
    let base = symbol.trim().to_ascii_uppercase();
    let base = base.strip_suffix("USDT")?;
    let mut b = base.to_string();
    for p in ["1000000", "100000", "10000", "1000", "1M"] {
        if let Some(rest) = b.strip_prefix(p) {
            if !rest.is_empty() && rest.chars().next().is_some_and(|c| c.is_ascii_alphabetic()) {
                b = rest.to_string();
                break;
            }
        }
    }
    if let Some(rest) = b.strip_suffix("1000") {
        if !rest.is_empty() {
            b = rest.to_string();
        }
    }
    Some(alias(&b))
}

/// One name per coin across venues and the lab.
pub fn alias(coin: &str) -> String {
    match coin.trim().to_ascii_uppercase().as_str() {
        "XBT" => "BTC".into(),
        "MATIC" => "POL".into(),
        c => c.to_string(),
    }
}

// ── the instrument list, shared by every connector of this process ──────────

fn registry() -> &'static RwLock<HashMap<String, PerpInstrument>> {
    static R: OnceLock<RwLock<HashMap<String, PerpInstrument>>> = OnceLock::new();
    R.get_or_init(|| RwLock::new(HashMap::new()))
}

/// Keep the venue's contract list for size checks (called after every read).
pub fn remember_instruments(list: &[PerpInstrument]) {
    if let Ok(mut r) = registry().write() {
        for i in list {
            r.insert(i.symbol.clone(), i.clone());
        }
    }
}

/// The contract a symbol names, if the list has been read.
pub fn instrument(symbol: &str) -> Option<PerpInstrument> {
    registry().read().ok()?.get(symbol).cloned()
}

// ── public market data (no keys) ────────────────────────────────────────────

/// A client for the public data hosts.
pub fn data_client() -> reqwest::Client {
    reqwest::Client::builder().timeout(Duration::from_secs(20)).build().unwrap_or_default()
}

/// Every tradable perpetual the venue lists, from its public data host.
pub async fn fetch_instruments(http: &reqwest::Client, ex: PerpExchange) -> Result<Vec<PerpInstrument>, ConnectorError> {
    let list = match ex {
        PerpExchange::KrakenFutures => kraken_futures::fetch_instruments(http).await?,
        PerpExchange::Bybit => bybit::fetch_instruments(http).await?,
    };
    remember_instruments(&list);
    Ok(list)
}

/// Marks and current funding of every perpetual.
pub async fn fetch_tickers(http: &reqwest::Client, ex: PerpExchange) -> Result<Vec<PerpTicker>, ConnectorError> {
    match ex {
        PerpExchange::KrakenFutures => kraken_futures::fetch_tickers(http).await,
        PerpExchange::Bybit => bybit::fetch_tickers(http).await,
    }
}

/// Settled funding of one contract after `since_ms`, oldest first.
pub async fn fetch_funding(
    http: &reqwest::Client,
    ex: PerpExchange,
    symbol: &str,
    since_ms: i64,
) -> Result<Vec<FundingPoint>, ConnectorError> {
    let mut v = match ex {
        PerpExchange::KrakenFutures => kraken_futures::fetch_funding(http, symbol).await?,
        PerpExchange::Bybit => bybit::fetch_funding(http, symbol, since_ms).await?,
    };
    v.retain(|p| p.settled_ms > since_ms);
    v.sort_by_key(|p| p.settled_ms);
    Ok(v)
}

/// GET a public JSON document. Redirects are not followed: a host that
/// redirects (Kraken's retired demo) is reported, never parsed as data.
pub(crate) async fn get_public(http: &reqwest::Client, url: &str, what: &str) -> Result<serde_json::Value, ConnectorError> {
    let resp = http.get(url).send().await.map_err(|e| ConnectorError::Network(format!("{what}: {e}")))?;
    let code = resp.status().as_u16();
    let body = resp.text().await.unwrap_or_default();
    if !(200..300).contains(&code) {
        return Err(match code {
            429 | 500..=599 => ConnectorError::Network(format!("{what} {code}")),
            _ => ConnectorError::Rejected(format!("{what} {code}: {}", body.chars().take(200).collect::<String>())),
        });
    }
    serde_json::from_str(&body).map_err(|e| ConnectorError::Network(format!("bad {what} payload: {e}")))
}

// ── the order connector ──────────────────────────────────────────────────────

/// Orders, positions and the account on one perps venue's DEMO account.
/// Holds the demo keys of exactly one venue and talks only to its demo host.
pub struct PerpConnector {
    pub(crate) exchange: PerpExchange,
    pub(crate) key: String,
    pub(crate) secret: String,
    pub(crate) http: reqwest::Client,
}

impl PerpConnector {
    /// The connector for `exchange`'s demo account. There is no other kind.
    pub fn demo(exchange: PerpExchange, key: String, secret: String) -> Self {
        Self {
            exchange,
            key,
            secret,
            // A redirect from the order host is an answer, not a detour: the
            // retired Kraken demo redirects every path to the website.
            http: reqwest::Client::builder()
                .timeout(Duration::from_secs(15))
                .redirect(reqwest::redirect::Policy::none())
                .build()
                .unwrap_or_default(),
        }
    }

    pub fn exchange(&self) -> PerpExchange {
        self.exchange
    }

    pub(crate) fn base(&self) -> &'static str {
        self.exchange.demo_base()
    }

    fn creds_ok(&self) -> Result<(), ConnectorError> {
        if self.key.trim().is_empty() || self.secret.trim().is_empty() {
            return Err(ConnectorError::NotConfigured(format!("{} demo keys", self.exchange.label())));
        }
        Ok(())
    }

    /// The account's margin numbers.
    pub async fn account(&self) -> Result<PerpAccount, ConnectorError> {
        self.creds_ok()?;
        match self.exchange {
            PerpExchange::KrakenFutures => kraken_futures::account(self).await,
            PerpExchange::Bybit => bybit::account(self).await,
        }
    }

    /// Read a private response, mapping HTTP-level failures; each venue
    /// checks its own error field afterwards.
    pub(crate) async fn send(&self, rb: reqwest::RequestBuilder, what: &str) -> Result<serde_json::Value, ConnectorError> {
        let resp = rb.send().await.map_err(|e| ConnectorError::Network(e.to_string()))?;
        let code = resp.status().as_u16();
        let body = resp.text().await.unwrap_or_default();
        if (300..400).contains(&code) {
            return Err(ConnectorError::NotConfigured(match self.exchange {
                PerpExchange::KrakenFutures => KRAKEN_DEMO_GONE.to_string(),
                PerpExchange::Bybit => format!("{} demo host answered a redirect ({code}) on {what}", self.exchange.label()),
            }));
        }
        if !(200..300).contains(&code) {
            return Err(match code {
                401 | 403 => ConnectorError::Auth(format!("{} demo rejected the key on {what}", self.exchange.label())),
                429 => ConnectorError::Network(format!("{} rate limited on {what}", self.exchange.label())),
                500..=599 => ConnectorError::Network(format!("{} {code} on {what}", self.exchange.label())),
                _ => ConnectorError::Rejected(format!("{what} {code}: {}", body.chars().take(300).collect::<String>())),
            });
        }
        if body.trim().is_empty() {
            return Ok(serde_json::Value::Null);
        }
        serde_json::from_str(&body).map_err(|e| ConnectorError::Network(format!("bad {what} payload: {e}")))
    }
}

#[async_trait]
impl MarketConnector for PerpConnector {
    fn venue(&self) -> Venue {
        Venue::Perps
    }

    fn is_live_ready(&self) -> bool {
        self.creds_ok().is_ok()
    }

    fn label(&self) -> String {
        format!("{} (demo)", self.exchange.label())
    }

    fn round_qty(&self, qty: f64, symbol: &str) -> f64 {
        match instrument(symbol) {
            Some(i) => i.round_qty(qty),
            None => qty,
        }
    }

    async fn verify(&self) -> Result<String, ConnectorError> {
        let a = self.account().await?;
        Ok(format!(
            "{} demo account: equity ${:.2}, available margin ${:.2}",
            self.exchange.label(),
            a.equity,
            a.available_margin
        ))
    }

    async fn preflight(&self, req: &OrderRequest) -> Result<(), ConnectorError> {
        self.creds_ok()?;
        if let Some(i) = instrument(&req.symbol) {
            if i.round_qty(req.qty) <= 0.0 {
                return Err(ConnectorError::Preflight(format!(
                    "{} {} is below the venue minimum of {} (step {})",
                    req.qty, req.symbol, i.min_qty, i.qty_step
                )));
            }
        }
        Ok(())
    }

    async fn submit_order(&self, req: OrderRequest) -> Result<BrokerOrder, ConnectorError> {
        self.creds_ok()?;
        let mut req = req;
        if let Some(i) = instrument(&req.symbol) {
            req.qty = i.round_qty(req.qty);
            if req.qty <= 0.0 {
                return Err(ConnectorError::Preflight(format!("{} below the venue minimum", req.symbol)));
            }
        }
        match self.exchange {
            PerpExchange::KrakenFutures => kraken_futures::submit(self, req).await,
            PerpExchange::Bybit => bybit::submit(self, req).await,
        }
    }

    async fn order_status(&self, broker_id: &str, symbol: &str) -> Result<BrokerOrder, ConnectorError> {
        self.creds_ok()?;
        match self.exchange {
            PerpExchange::KrakenFutures => kraken_futures::status(self, broker_id).await,
            PerpExchange::Bybit => bybit::status(self, broker_id, symbol).await,
        }
    }

    async fn cancel_order(&self, broker_id: &str, symbol: &str) -> Result<(), ConnectorError> {
        self.creds_ok()?;
        match self.exchange {
            PerpExchange::KrakenFutures => kraken_futures::cancel(self, broker_id).await,
            PerpExchange::Bybit => bybit::cancel(self, broker_id, symbol).await,
        }
    }

    async fn order_by_client_id(&self, client_order_id: &str, symbol: &str) -> Result<Option<BrokerOrder>, ConnectorError> {
        self.creds_ok()?;
        match self.exchange {
            PerpExchange::KrakenFutures => kraken_futures::by_client_id(self, client_order_id).await,
            PerpExchange::Bybit => bybit::by_client_id(self, client_order_id, symbol).await,
        }
    }

    async fn open_orders(&self) -> Result<Vec<OpenOrder>, ConnectorError> {
        self.creds_ok()?;
        match self.exchange {
            PerpExchange::KrakenFutures => kraken_futures::open_orders(self).await,
            PerpExchange::Bybit => bybit::open_orders(self).await,
        }
    }

    async fn positions(&self) -> Result<Vec<BrokerPosition>, ConnectorError> {
        self.creds_ok()?;
        match self.exchange {
            PerpExchange::KrakenFutures => kraken_futures::positions(self).await,
            PerpExchange::Bybit => bybit::positions(self).await,
        }
    }

    async fn balances(&self) -> Result<Vec<Balance>, ConnectorError> {
        let a = self.account().await?;
        Ok(vec![Balance { asset: "USD".into(), free: a.available_margin, total: a.equity, usd_value: Some(a.equity) }])
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn coins_are_named_the_lab_way_whatever_the_venue_calls_them() {
        assert_eq!(coin_of_usdt_symbol("BTCUSDT").as_deref(), Some("BTC"));
        assert_eq!(coin_of_usdt_symbol("1000PEPEUSDT").as_deref(), Some("PEPE"));
        assert_eq!(coin_of_usdt_symbol("10000LADYSUSDT").as_deref(), Some("LADYS"));
        assert_eq!(coin_of_usdt_symbol("1000000MOGUSDT").as_deref(), Some("MOG"));
        assert_eq!(coin_of_usdt_symbol("SHIB1000USDT").as_deref(), Some("SHIB"));
        assert_eq!(coin_of_usdt_symbol("MATICUSDT").as_deref(), Some("POL"));
        assert_eq!(coin_of_usdt_symbol("1INCHUSDT").as_deref(), Some("1INCH"), "a coin that starts with a digit stays");
        assert_eq!(coin_of_usdt_symbol("BTCUSD"), None);
        assert_eq!(alias("xbt"), "BTC");
    }

    #[test]
    fn sizes_round_down_to_the_step_and_below_the_minimum_to_nothing() {
        let i = PerpInstrument {
            coin: "BTC".into(),
            symbol: "PF_XBTUSD".into(),
            qty_step: 0.0001,
            min_qty: 0.0001,
            max_qty: Some(1200.0),
            tick: 1.0,
            funding_period_ms: 3_600_000,
        };
        assert_eq!(i.round_qty(0.123456), 0.1234);
        assert_eq!(i.round_qty(-0.123456), 0.1234, "a size is never negative; the side carries the sign");
        assert_eq!(i.round_qty(0.00009), 0.0);
        assert_eq!(i.round_qty(5000.0), 1200.0);
        let pepe = PerpInstrument { qty_step: 1000.0, min_qty: 1000.0, max_qty: None, ..i.clone() };
        assert_eq!(pepe.round_qty(123_456.0), 123_000.0);
        assert_eq!(floor_to_step(0.3, 0.1), 0.3, "0.3 is three steps of 0.1, not two");
        assert_eq!(decimals_of(0.001), 3);
        assert_eq!(decimals_of(1.0), 0);
        assert_eq!(decimals_of(1000.0), 0);
    }

    #[test]
    fn the_exchanges_parse_from_settings_and_never_name_a_live_order_host() {
        assert_eq!(PerpExchange::parse("Kraken-Futures"), Some(PerpExchange::KrakenFutures));
        assert_eq!(PerpExchange::parse("bybit"), Some(PerpExchange::Bybit));
        assert_eq!(PerpExchange::parse("binance"), None);
        for ex in PerpExchange::ALL {
            assert!(ex.demo_base().contains("demo"), "{ex:?} orders go to a demo host only");
            assert_eq!(PerpExchange::parse(ex.id()), Some(ex));
        }
        let c = PerpConnector::demo(PerpExchange::KrakenFutures, "k".into(), "s".into());
        assert_eq!(c.venue(), Venue::Perps);
        assert!(c.label().contains("demo"));
        assert!(!PerpConnector::demo(PerpExchange::Bybit, " ".into(), "s".into()).is_live_ready());
    }
}
