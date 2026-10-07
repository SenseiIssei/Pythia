//! Centralised crypto exchanges — the `Venue::Crypto` execution layer.
//!
//! Pythia's crypto markets are exchange-agnostic (`crypto:BTC/USD`). Which
//! exchange actually *executes* is a user setting, so a strategy proven on
//! Kraken can be pointed at Binance without touching the strategy.
//!
//! Every venue here speaks plain REST and signs each private request (see
//! [`super::sign`]): four with an HMAC over a canonical string, Coinbase with
//! a per-request ES256 JWT. They differ in three places, and those three
//! places are all this module has to normalise:
//!
//! | | symbol | market-buy size unit | order id |
//! |---|---|---|---|
//! | Kraken   | `XBTUSD`   | base | `txid` |
//! | Binance  | `BTCUSDT`  | base (`quantity`) | `orderId` |
//! | Bybit    | `BTCUSDT`  | quote *unless* `marketUnit=baseCoin` | `orderId` |
//! | OKX      | `BTC-USDT` | quote *unless* `tgtCcy=base_ccy` | `ordId` |
//! | Coinbase | `BTC-USD`  | base (`base_size`) | `order_id` |
//!
//! That "market-buy size unit" column is the classic way to spend 10× what you
//! meant to, so each adapter pins it to the base currency explicitly.
//!
//! **Scope:** spot only. Grant the API key *trade* permission — never withdrawal.

mod binance;
mod bybit;
mod coinbase;
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
    /// Coinbase Advanced Trade. Authenticates with a CDP API key (a key name
    /// plus an EC private key) and an ES256 JWT per request rather than an
    /// HMAC; see `coinbase.rs`.
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
        matches!(self, Exchange::Okx)
    }

    /// Whether order routing is implemented for this venue. Every venue in the
    /// registry trades now; a future venue that is listed before its adapter
    /// exists returns false here and is refused by `creds_ok`.
    pub fn can_trade(self) -> bool {
        match self {
            Exchange::Kraken | Exchange::Binance | Exchange::Bybit | Exchange::Okx | Exchange::Coinbase => true,
        }
    }

    /// What this venue calls the two credential fields, for the settings form.
    /// Coinbase's "key" is a key *name* and its "secret" a multi-line PEM.
    pub fn key_labels(self) -> (&'static str, &'static str) {
        match self {
            Exchange::Coinbase => ("API key name", "Private key (PEM)"),
            _ => ("API key", "API secret"),
        }
    }

    /// Plain-language instructions for creating a key with the right
    /// permissions on this venue, shown under its form.
    pub fn key_help(self) -> &'static str {
        match self {
            Exchange::Coinbase => {
                "Create the key at portal.cdp.coinbase.com under API Keys, as a Secret API key. Under \
                 Advanced settings choose ECDSA as the signature algorithm (Ed25519 keys do not work with \
                 Advanced Trade). Give it the View and Trade permissions and NOT Transfer, so it cannot move \
                 money off Coinbase, and add an IP allowlist with the address of the machine Pythia runs on. \
                 Paste the key name (organizations/.../apiKeys/...) and the whole private key, including the \
                 BEGIN and END lines."
            }
            Exchange::Okx => {
                "Create a trade-only API key with no withdrawal permission, bound to your IP, and enter the \
                 passphrase you chose for it."
            }
            _ => "Create a trade-only API key with no withdrawal permission, and restrict it to your IP address.",
        }
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
    /// Form labels for the key and secret fields.
    pub key_label: &'static str,
    pub secret_label: &'static str,
    /// The secret is a multi-line PEM block (Coinbase), so the form should
    /// offer a text area rather than a one-line password field.
    pub secret_multiline: bool,
    /// How to create a correctly scoped key, in plain language.
    pub key_help: &'static str,
}

pub fn exchanges_with(configured: impl Fn(Exchange) -> bool) -> Vec<ExchangeInfo> {
    Exchange::ALL
        .into_iter()
        .map(|e| {
            let (key_label, secret_label) = e.key_labels();
            ExchangeInfo {
                id: e.id(),
                label: e.label(),
                needs_passphrase: e.needs_passphrase(),
                can_trade: e.can_trade(),
                configured: configured(e),
                key_label,
                secret_label,
                secret_multiline: e == Exchange::Coinbase,
                key_help: e.key_help(),
            }
        })
        .collect()
}

/// Check a pasted credential set before it is stored, so a wrong paste is
/// caught on the settings page instead of at the first order. Only Coinbase
/// has a secret with structure worth checking (an EC private key); for the
/// HMAC venues any string is a well-formed secret. Errors never quote the key.
pub fn check_credentials(exchange: Exchange, key: &str, secret: &str) -> Result<(), String> {
    if exchange == Exchange::Coinbase {
        if key.trim().contains("BEGIN") {
            return Err("the key name field holds the private key; put the key name \
                        (organizations/.../apiKeys/...) there and the PEM block in the private key field"
                .into());
        }
        super::sign::cdp_signing_key(secret).map(|_| ())?;
    }
    Ok(())
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
            return Err(ConnectorError::Unimplemented("order routing for this exchange"));
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
        let mut summary = format!(
            "{} · {} assets · ≈${usd:.2} priced",
            self.exchange.label(),
            bal.len()
        );
        // Coinbase publishes the account's fee tier; show it, since it decides
        // whether a strategy's edge survives the fees there.
        if self.exchange == Exchange::Coinbase {
            if let Some((tier, maker, taker)) = coinbase::fee_tier(self).await {
                let tier = if tier.is_empty() { String::new() } else { format!("{tier}, ") };
                summary.push_str(&format!(
                    " · fee tier {tier}maker {:.2} % / taker {:.2} %",
                    maker * 100.0,
                    taker * 100.0
                ));
            }
        }
        Ok(summary)
    }

    async fn preflight(&self, req: &OrderRequest) -> Result<(), ConnectorError> {
        self.creds_ok()?;
        // Coinbase publishes its lot rules (minimum size, step, minimum order
        // value, halted books); refuse what it would refuse before sending.
        if self.exchange == Exchange::Coinbase {
            coinbase::preflight(self, req).await?;
        }
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
            Exchange::Coinbase => coinbase::submit(self, req).await,
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
            Exchange::Coinbase => coinbase::status(self, broker_id).await,
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
            Exchange::Coinbase => coinbase::cancel(self, broker_id).await,
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
            Exchange::Coinbase => coinbase::balances(self).await,
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
        // Coinbase needs a key name and a private key, and no passphrase.
        assert!(!CexConnector::new(Exchange::Coinbase, "k".into(), String::new(), String::new()).is_live_ready());
        assert!(CexConnector::new(Exchange::Coinbase, "k".into(), "pem".into(), String::new()).is_live_ready());
    }

    #[test]
    fn every_listed_exchange_can_trade_and_describes_its_key() {
        let list = exchanges_with(|_| false);
        assert_eq!(list.len(), Exchange::ALL.len());
        for info in &list {
            assert!(info.can_trade, "{} is listed but cannot trade", info.label);
            assert!(!info.key_help.is_empty());
        }
        let cb = list.iter().find(|i| i.id == "coinbase").unwrap();
        assert!(!cb.needs_passphrase, "a CDP key has no passphrase");
        assert!(cb.secret_multiline);
        assert_eq!(cb.key_label, "API key name");
        assert!(cb.key_help.contains("Trade") && cb.key_help.contains("NOT Transfer"));
        assert!(cb.key_help.contains("IP allowlist"));
        let okx = list.iter().find(|i| i.id == "okx").unwrap();
        assert!(okx.needs_passphrase && !okx.secret_multiline);
    }

    #[test]
    fn coinbase_credentials_are_checked_before_they_are_stored() {
        let sk = p256::SecretKey::from_slice(&[0x42u8; 32]).unwrap();
        let pem = sk.to_sec1_pem(Default::default()).unwrap().to_string();
        assert!(check_credentials(Exchange::Coinbase, "organizations/o/apiKeys/k", &pem).is_ok());
        assert!(check_credentials(Exchange::Coinbase, "organizations/o/apiKeys/k", "abc").is_err());
        // Pasted into the wrong field.
        let e = check_credentials(Exchange::Coinbase, &pem, &pem).unwrap_err();
        assert!(e.contains("key name field"), "{e}");
        assert!(!e.contains(pem.lines().nth(1).unwrap()), "never echo the key");
        // HMAC venues accept any non-empty string as a secret.
        assert!(check_credentials(Exchange::Kraken, "k", "s").is_ok());
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
