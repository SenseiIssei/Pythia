//! Centralised crypto exchanges — the `Venue::Crypto` execution layer.
//!
//! Pythia's crypto markets are exchange-agnostic (`crypto:BTC/USD`). Which
//! exchange actually *executes* is a user setting, so a strategy proven on
//! Kraken can be pointed at Binance without touching the strategy.
//!
//! Every venue here authenticates with an HMAC over a canonical string (see
//! [`super::sign`]) and speaks plain REST. They differ in three places, and
//! those three places are all this module has to normalise:
//!
//! | | symbol | market-buy size unit | order id |
//! |---|---|---|---|
//! | Kraken   | `XBTUSD`   | base | `txid` |
//! | Binance  | `BTCUSDT`  | base (`quantity`) | `orderId` |
//! | Bybit    | `BTCUSDT`  | quote *unless* `marketUnit=baseCoin` | `orderId` |
//! | OKX      | `BTC-USDT` | quote *unless* `tgtCcy=base_ccy` | `ordId` |
//!
//! That "market-buy size unit" column is the classic way to spend 10× what you
//! meant to, so each adapter pins it to the base currency explicitly.
//!
//! **Scope:** spot only. Grant the API key *trade* permission — never withdrawal.

mod binance;
mod bybit;
mod kraken;
mod okx;

use super::{
    Balance, BrokerOrder, BrokerPosition, ConnectorError, MarketConnector, OrderRequest, Venue,
};
use async_trait::async_trait;
use serde::{Deserialize, Serialize};
use std::time::Duration;

/// Every exchange Pythia knows how to route to.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Exchange {
    Kraken,
    Binance,
    Bybit,
    Okx,
    /// Coinbase Advanced Trade authenticates with ES256 JWTs rather than an
    /// HMAC. Listed so the UI can show it, but it refuses to trade rather than
    /// pretending — see `PROFIT-PLAN.md` for the plan to add it.
    Coinbase,
}

impl Exchange {
    pub const ALL: [Exchange; 5] = [
        Exchange::Kraken,
        Exchange::Binance,
        Exchange::Bybit,
        Exchange::Okx,
        Exchange::Coinbase,
    ];

    pub fn id(self) -> &'static str {
        match self {
            Exchange::Kraken => "kraken",
            Exchange::Binance => "binance",
            Exchange::Bybit => "bybit",
            Exchange::Okx => "okx",
            Exchange::Coinbase => "coinbase",
        }
    }

    pub fn label(self) -> &'static str {
        match self {
            Exchange::Kraken => "Kraken",
            Exchange::Binance => "Binance",
            Exchange::Bybit => "Bybit",
            Exchange::Okx => "OKX",
            Exchange::Coinbase => "Coinbase Advanced",
        }
    }

    pub fn parse(s: &str) -> Option<Exchange> {
        Exchange::ALL.into_iter().find(|e| e.id() == s.trim().to_ascii_lowercase())
    }

    /// Venues that need a third credential besides key + secret.
    pub fn needs_passphrase(self) -> bool {
        matches!(self, Exchange::Okx | Exchange::Coinbase)
    }

    /// Whether order routing is implemented for this venue.
    pub fn can_trade(self) -> bool {
        !matches!(self, Exchange::Coinbase)
    }

    /// The quote asset Pythia's `…/USD` markets map to here. Binance and Bybit
    /// have no USD spot book for most pairs; USDT is the liquid equivalent.
    fn usd_quote(self) -> &'static str {
        match self {
            Exchange::Kraken | Exchange::Coinbase => "USD",
            Exchange::Binance | Exchange::Bybit | Exchange::Okx => "USDT",
        }
    }

    /// Map `BTC/USD` onto this venue's symbol.
    pub fn symbol(self, pair: &str) -> String {
        let (base, quote) = split_pair(pair);
        let quote = if quote == "USD" { self.usd_quote() } else { quote.as_str() };
        match self {
            // Kraken still calls Bitcoin XBT.
            Exchange::Kraken => format!("{}{quote}", if base == "BTC" { "XBT" } else { base.as_str() }),
            Exchange::Binance | Exchange::Bybit => format!("{base}{quote}"),
            Exchange::Okx | Exchange::Coinbase => format!("{base}-{quote}"),
        }
    }
}

/// Split `BTC/USD` into (`BTC`, `USD`); a bare `BTC` is assumed USD-quoted.
fn split_pair(pair: &str) -> (String, String) {
    let up = pair.trim().to_ascii_uppercase();
    match up.split_once('/') {
        Some((b, q)) => (b.to_string(), q.to_string()),
        None => (up, "USD".to_string()),
    }
}

/// Public description of one exchange for the settings UI.
#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ExchangeInfo {
    pub id: &'static str,
    pub label: &'static str,
    pub needs_passphrase: bool,
    pub can_trade: bool,
    /// Whether credentials for it exist in the vault / env.
    pub configured: bool,
}

pub fn exchanges_with(configured: impl Fn(Exchange) -> bool) -> Vec<ExchangeInfo> {
    Exchange::ALL
        .into_iter()
        .map(|e| ExchangeInfo {
            id: e.id(),
            label: e.label(),
            needs_passphrase: e.needs_passphrase(),
            can_trade: e.can_trade(),
            configured: configured(e),
        })
        .collect()
}

/// The single `Venue::Crypto` connector, backed by whichever exchange the user
/// selected. Holds credentials for exactly one venue — swapping exchanges means
/// building a new connector, so a key can never be sent to the wrong host.
pub struct CexConnector {
    pub(crate) exchange: Exchange,
    pub(crate) key: String,
    pub(crate) secret: String,
    pub(crate) passphrase: String,
    pub(crate) http: reqwest::Client,
}

impl CexConnector {
    pub fn new(exchange: Exchange, key: String, secret: String, passphrase: String) -> Self {
        Self {
            exchange,
            key,
            secret,
            passphrase,
            http: reqwest::Client::builder()
                .timeout(Duration::from_secs(15))
                .build()
                .unwrap_or_default(),
        }
    }

    /// Build from a vault/env field map: `exchange`, `key`, `secret`,
    /// `passphrase`. An unknown or missing exchange id defaults to Kraken, the
    /// venue the rest of Pythia already pulls prices from.
    pub fn from_fields(get: impl Fn(&str) -> Option<String>) -> Self {
        let exchange = get("exchange")
            .as_deref()
            .and_then(Exchange::parse)
            .unwrap_or(Exchange::Kraken);
        Self::new(
            exchange,
            get("key").unwrap_or_default(),
            get("secret").unwrap_or_default(),
            get("passphrase").unwrap_or_default(),
        )
    }

    pub fn exchange(&self) -> Exchange {
        self.exchange
    }

    fn creds_ok(&self) -> Result<(), ConnectorError> {
        if !self.exchange.can_trade() {
            return Err(ConnectorError::Unimplemented(
                "Coinbase Advanced Trade needs ES256 JWT auth — not wired yet",
            ));
        }
        if self.key.trim().is_empty() || self.secret.trim().is_empty() {
            return Err(ConnectorError::NotConfigured(self.exchange.id().into()));
        }
        if self.exchange.needs_passphrase() && self.passphrase.trim().is_empty() {
            return Err(ConnectorError::NotConfigured(format!(
                "{} needs an API passphrase",
                self.exchange.label()
            )));
        }
        Ok(())
    }

    /// Read a response body, mapping HTTP-level failures. Exchange-level errors
    /// live *inside* a 200 body on most of these venues, so each adapter checks
    /// its own error field afterwards.
    pub(crate) async fn send(
        &self,
        rb: reqwest::RequestBuilder,
        what: &str,
    ) -> Result<serde_json::Value, ConnectorError> {
        let resp = rb.send().await.map_err(|e| ConnectorError::Network(e.to_string()))?;
        let code = resp.status().as_u16();
        let body = resp.text().await.unwrap_or_default();
        if !(200..300).contains(&code) {
            return Err(match code {
                401 | 403 => ConnectorError::Auth(format!("{} rejected the key on {what}", self.exchange.label())),
                429 => ConnectorError::Network(format!("{} rate limited on {what}", self.exchange.label())),
                500..=599 => ConnectorError::Network(format!("{} {code} on {what}", self.exchange.label())),
                _ => ConnectorError::Rejected(format!("{what} {code}: {}", body.trim())),
            });
        }
        if body.trim().is_empty() {
            return Ok(serde_json::Value::Null);
        }
        serde_json::from_str(&body).map_err(|e| ConnectorError::Network(format!("bad {what} payload: {e}")))
    }
}

#[async_trait]
impl MarketConnector for CexConnector {
    fn venue(&self) -> Venue {
        Venue::Crypto
    }

    fn is_live_ready(&self) -> bool {
        self.creds_ok().is_ok()
    }

    fn label(&self) -> String {
        self.exchange.label().to_string()
    }

    /// Spot lot sizes differ per pair and per venue; 8 decimals is inside every
    /// one of them, and dust below 1e-8 is not an order.
    fn round_qty(&self, qty: f64, _symbol: &str) -> f64 {
        let r = (qty * 1e8).trunc() / 1e8;
        if r < 1e-8 {
            0.0
        } else {
            r
        }
    }

    async fn verify(&self) -> Result<String, ConnectorError> {
        self.creds_ok()?;
        let bal = self.balances().await?;
        let usd: f64 = bal.iter().filter_map(|b| b.usd_value).sum();
        Ok(format!(
            "{} · {} assets · ≈${usd:.2} priced",
            self.exchange.label(),
            bal.len()
        ))
    }

    async fn preflight(&self, req: &OrderRequest) -> Result<(), ConnectorError> {
        self.creds_ok()?;
        // Spot cannot go short: selling what you do not hold is not an order,
        // it is a rejection with extra steps.
        if req.side == super::Side::Sell {
            let base = split_pair(&req.symbol).0;
            let held = self
                .balances()
                .await?
                .into_iter()
                .find(|b| b.asset.eq_ignore_ascii_case(&base))
                .map(|b| b.free)
                .unwrap_or(0.0);
            if req.qty > held + 1e-12 {
                return Err(ConnectorError::Preflight(format!(
                    "spot sell of {:.8} {base} but only {:.8} free on {} — spot cannot short",
                    req.qty,
                    held,
                    self.exchange.label()
                )));
            }
        }
        Ok(())
    }

    async fn submit_order(&self, req: OrderRequest) -> Result<BrokerOrder, ConnectorError> {
        self.creds_ok()?;
        match self.exchange {
            Exchange::Kraken => kraken::submit(self, req).await,
            Exchange::Binance => binance::submit(self, req).await,
            Exchange::Bybit => bybit::submit(self, req).await,
            Exchange::Okx => okx::submit(self, req).await,
            Exchange::Coinbase => Err(ConnectorError::Unimplemented("coinbase::submit_order")),
        }
    }

    async fn order_status(&self, broker_id: &str, symbol: &str) -> Result<BrokerOrder, ConnectorError> {
        self.creds_ok()?;
        let venue_symbol = self.exchange.symbol(symbol);
        match self.exchange {
            Exchange::Kraken => kraken::status(self, broker_id).await,
            Exchange::Binance => binance::status(self, broker_id, &venue_symbol).await,
            Exchange::Bybit => bybit::status(self, broker_id, &venue_symbol).await,
            Exchange::Okx => okx::status(self, broker_id, &venue_symbol).await,
            Exchange::Coinbase => Err(ConnectorError::Unimplemented("coinbase::order_status")),
        }
    }

    async fn cancel_order(&self, broker_id: &str, symbol: &str) -> Result<(), ConnectorError> {
        self.creds_ok()?;
        let venue_symbol = self.exchange.symbol(symbol);
        match self.exchange {
            Exchange::Kraken => kraken::cancel(self, broker_id).await,
            Exchange::Binance => binance::cancel(self, broker_id, &venue_symbol).await,
            Exchange::Bybit => bybit::cancel(self, broker_id, &venue_symbol).await,
            Exchange::Okx => okx::cancel(self, broker_id, &venue_symbol).await,
            Exchange::Coinbase => Err(ConnectorError::Unimplemented("coinbase::cancel_order")),
        }
    }

    /// Spot balances *are* the position set — there is nothing else to hold.
    async fn positions(&self) -> Result<Vec<BrokerPosition>, ConnectorError> {
        Ok(self
            .balances()
            .await?
            .into_iter()
            .filter(|b| b.total > 0.0 && !is_fiat(&b.asset))
            .map(|b| BrokerPosition {
                symbol: format!("{}/USD", b.asset),
                qty: b.total,
                avg_price: 0.0, // spot venues do not report a cost basis
                market_value: b.usd_value.unwrap_or(0.0),
            })
            .collect())
    }

    async fn balances(&self) -> Result<Vec<Balance>, ConnectorError> {
        self.creds_ok()?;
        match self.exchange {
            Exchange::Kraken => kraken::balances(self).await,
            Exchange::Binance => binance::balances(self).await,
            Exchange::Bybit => bybit::balances(self).await,
            Exchange::Okx => okx::balances(self).await,
            Exchange::Coinbase => Err(ConnectorError::Unimplemented("coinbase::balances")),
        }
    }
}

pub(crate) fn is_fiat(asset: &str) -> bool {
    matches!(
        asset.to_ascii_uppercase().as_str(),
        "USD" | "USDT" | "USDC" | "EUR" | "GBP" | "CHF" | "DAI" | "ZUSD" | "ZEUR"
    )
}

/// Kraken decorates asset codes (`XXBT`, `ZUSD`) and everyone spells Bitcoin
/// differently. Normalise so the wallet view does not show BTC three times.
pub(crate) fn normalize_asset(code: &str) -> String {
    let c = code.trim().to_ascii_uppercase();
    let c = c.strip_suffix(".F").unwrap_or(&c).to_string(); // Kraken earn/staked suffix
    let c = match c.as_str() {
        // Kraken's legacy X/Z prefixes on its original listings.
        "XXBT" | "XBT" => "BTC",
        "XETH" => "ETH",
        "XLTC" => "LTC",
        "XXRP" => "XRP",
        "XXDG" => "DOGE",
        "ZUSD" => "USD",
        "ZEUR" => "EUR",
        "ZGBP" => "GBP",
        other => other,
    };
    c.to_string()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn symbols_map_to_each_venues_dialect() {
        assert_eq!(Exchange::Kraken.symbol("BTC/USD"), "XBTUSD", "Kraken calls it XBT");
        assert_eq!(Exchange::Kraken.symbol("ETH/USD"), "ETHUSD");
        // No USD spot book on these — USD maps to the liquid stablecoin.
        assert_eq!(Exchange::Binance.symbol("BTC/USD"), "BTCUSDT");
        assert_eq!(Exchange::Bybit.symbol("SOL/USD"), "SOLUSDT");
        assert_eq!(Exchange::Okx.symbol("BTC/USD"), "BTC-USDT");
        assert_eq!(Exchange::Coinbase.symbol("BTC/USD"), "BTC-USD");
        // A non-USD quote is passed through untouched.
        assert_eq!(Exchange::Binance.symbol("ETH/BTC"), "ETHBTC");
    }

    #[test]
    fn pairs_split_with_a_usd_default() {
        assert_eq!(split_pair("btc/usd"), ("BTC".into(), "USD".into()));
        assert_eq!(split_pair("SOL"), ("SOL".into(), "USD".into()));
    }

    #[test]
    fn exchange_ids_round_trip() {
        for e in Exchange::ALL {
            assert_eq!(Exchange::parse(e.id()), Some(e));
            assert_eq!(Exchange::parse(&e.id().to_uppercase()), Some(e));
        }
        assert_eq!(Exchange::parse("mtgox"), None);
    }

    #[test]
    fn asset_codes_normalise_across_venues() {
        assert_eq!(normalize_asset("XXBT"), "BTC");
        assert_eq!(normalize_asset("XBT"), "BTC");
        assert_eq!(normalize_asset("ZUSD"), "USD");
        assert_eq!(normalize_asset("btc"), "BTC");
        assert_eq!(normalize_asset("SOL"), "SOL");
    }

    #[test]
    fn unconfigured_venues_fail_closed() {
        let c = CexConnector::new(Exchange::Kraken, String::new(), String::new(), String::new());
        assert!(!c.is_live_ready());
        // OKX without a passphrase is not ready even with key + secret.
        let okx = CexConnector::new(Exchange::Okx, "k".into(), "s".into(), String::new());
        assert!(!okx.is_live_ready());
        assert!(CexConnector::new(Exchange::Okx, "k".into(), "s".into(), "p".into()).is_live_ready());
        // Coinbase is listed but must never claim it can trade.
        let cb = CexConnector::new(Exchange::Coinbase, "k".into(), "s".into(), "p".into());
        assert!(!cb.is_live_ready());
    }

    #[test]
    fn from_fields_defaults_to_kraken() {
        let c = CexConnector::from_fields(|k| match k {
            "key" => Some("a".into()),
            "secret" => Some("b".into()),
            _ => None,
        });
        assert_eq!(c.exchange(), Exchange::Kraken);
    }
}
