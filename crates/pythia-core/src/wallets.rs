//! Wallets — one balance sheet across every place the user keeps money.
//!
//! Three kinds of account land in the same view:
//!
//! - **Broker** — Alpaca. Cash and buying power.
//! - **Exchange** — Kraken, Binance, Bybit, OKX. Per-asset spot balances.
//! - **On-chain** — a *watch-only* address on an EVM chain, Solana or Bitcoin.
//!
//! ## Why on-chain is watch-only, and stays that way
//!
//! An exchange API key can be scoped to trade-without-withdrawal and revoked
//! from a web page. A wallet private key cannot: whoever holds it can move
//! everything, forever. Pythia therefore reads on-chain balances from a public
//! address and never asks for, stores, or accepts a seed phrase or private key.
//! Trading against self-custodied funds means depositing to a venue you can
//! revoke — which is a decision for the user to make deliberately, not a
//! checkbox in a settings page.
//!
//! Everything here is read-only and failure-tolerant: an unreachable chain or a
//! rate-limited RPC turns into an `error` string on that one account, never a
//! failed snapshot.

use crate::connectors::cex::{normalize_asset, CexConnector, Exchange};
use crate::connectors::{alpaca::AlpacaConnector, Balance, MarketConnector};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::HashMap;
use std::time::Duration;

const HTTP_TIMEOUT: Duration = Duration::from_secs(8);

/// Chains Pythia can read a balance from without an API key.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Chain {
    Ethereum,
    Polygon,
    Arbitrum,
    Optimism,
    Base,
    Bsc,
    Solana,
    Bitcoin,
}

impl Chain {
    pub const ALL: [Chain; 8] = [
        Chain::Ethereum,
        Chain::Polygon,
        Chain::Arbitrum,
        Chain::Optimism,
        Chain::Base,
        Chain::Bsc,
        Chain::Solana,
        Chain::Bitcoin,
    ];

    pub fn id(self) -> &'static str {
        match self {
            Chain::Ethereum => "ethereum",
            Chain::Polygon => "polygon",
            Chain::Arbitrum => "arbitrum",
            Chain::Optimism => "optimism",
            Chain::Base => "base",
            Chain::Bsc => "bsc",
            Chain::Solana => "solana",
            Chain::Bitcoin => "bitcoin",
        }
    }

    pub fn label(self) -> &'static str {
        match self {
            Chain::Ethereum => "Ethereum",
            Chain::Polygon => "Polygon",
            Chain::Arbitrum => "Arbitrum One",
            Chain::Optimism => "Optimism",
            Chain::Base => "Base",
            Chain::Bsc => "BNB Smart Chain",
            Chain::Solana => "Solana",
            Chain::Bitcoin => "Bitcoin",
        }
    }

    pub fn parse(s: &str) -> Option<Chain> {
        let s = s.trim().to_ascii_lowercase();
        Chain::ALL.into_iter().find(|c| c.id() == s)
    }

    /// The chain's native asset — the only thing we read. Token balances would
    /// need a per-token contract call and an indexer; see `PROFIT-PLAN.md`.
    pub fn native_asset(self) -> &'static str {
        match self {
            Chain::Ethereum | Chain::Arbitrum | Chain::Optimism | Chain::Base => "ETH",
            Chain::Polygon => "POL",
            Chain::Bsc => "BNB",
            Chain::Solana => "SOL",
            Chain::Bitcoin => "BTC",
        }
    }

    /// A public, keyless endpoint. Rate-limited and best-effort by design — a
    /// wallet view that fails is a cosmetic problem, not a trading one.
    fn rpc_url(self) -> &'static str {
        match self {
            Chain::Ethereum => "https://ethereum-rpc.publicnode.com",
            Chain::Polygon => "https://polygon-bor-rpc.publicnode.com",
            Chain::Arbitrum => "https://arbitrum-one-rpc.publicnode.com",
            Chain::Optimism => "https://optimism-rpc.publicnode.com",
            Chain::Base => "https://base-rpc.publicnode.com",
            Chain::Bsc => "https://bsc-rpc.publicnode.com",
            Chain::Solana => "https://api.mainnet-beta.solana.com",
            Chain::Bitcoin => "https://blockstream.info/api",
        }
    }

    fn is_evm(self) -> bool {
        !matches!(self, Chain::Solana | Chain::Bitcoin)
    }

    /// Smallest-unit → whole-unit divisor.
    fn decimals(self) -> f64 {
        match self {
            Chain::Solana => 1e9,   // lamports
            Chain::Bitcoin => 1e8,  // satoshi
            _ => 1e18,              // wei
        }
    }
}

/// One address the user asked Pythia to watch.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct WatchedAddress {
    pub chain: Chain,
    pub address: String,
    #[serde(default)]
    pub label: String,
}

impl WatchedAddress {
    /// Cheap shape check so an obvious typo is caught here rather than turning
    /// into a confusing RPC error later.
    pub fn validate(&self) -> Result<(), String> {
        let a = self.address.trim();
        if a.is_empty() {
            return Err("address is empty".into());
        }
        match self.chain {
            Chain::Solana => {
                if !(32..=44).contains(&a.len()) || !a.chars().all(|c| c.is_ascii_alphanumeric()) {
                    return Err("Solana addresses are 32–44 base58 characters".into());
                }
            }
            Chain::Bitcoin => {
                if a.len() < 26 || !a.chars().all(|c| c.is_ascii_alphanumeric()) {
                    return Err("that does not look like a Bitcoin address".into());
                }
            }
            evm => {
                if !a.starts_with("0x") || a.len() != 42 || !a[2..].chars().all(|c| c.is_ascii_hexdigit()) {
                    return Err(format!("{} needs a 0x-prefixed 40-hex-digit address", evm.label()));
                }
            }
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
pub enum WalletKind {
    Broker,
    Exchange,
    Onchain,
}

/// One account in the unified balance sheet.
#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct WalletAccount {
    pub id: String,
    pub kind: WalletKind,
    pub provider: String,
    pub label: String,
    /// Credentials/address present and the venue answered.
    pub connected: bool,
    /// Whether Pythia can route orders here (never true for on-chain).
    pub can_trade: bool,
    pub balances: Vec<Balance>,
    pub usd_total: f64,
    /// Why this account is empty, when it is. Shown verbatim in the UI.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
}

impl WalletAccount {
    fn failed(id: &str, kind: WalletKind, provider: &str, label: &str, err: String) -> Self {
        Self {
            id: id.into(),
            kind,
            provider: provider.into(),
            label: label.into(),
            connected: false,
            can_trade: false,
            balances: vec![],
            usd_total: 0.0,
            error: Some(err),
        }
    }
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct WalletsSnapshot {
    pub accounts: Vec<WalletAccount>,
    /// Sum of everything we could price. Assets with no USD price are excluded
    /// rather than counted as zero, so this never silently understates.
    pub usd_total: f64,
    /// Assets held but not priced — the UI says so instead of pretending.
    pub unpriced: Vec<String>,
    pub updated_at: i64,
}

/// Everything needed to build a snapshot, gathered by the caller from its own
/// credential store (OS keychain on desktop, environment on the server).
#[derive(Debug, Clone, Default)]
pub struct WalletSources {
    /// Alpaca key id + secret, and whether to read the paper account.
    pub alpaca: Option<(String, String, bool)>,
    /// Per-exchange (key, secret, passphrase).
    pub exchanges: Vec<(Exchange, String, String, String)>,
    pub addresses: Vec<WatchedAddress>,
}

impl WalletSources {
    pub fn is_empty(&self) -> bool {
        self.alpaca.is_none() && self.exchanges.is_empty() && self.addresses.is_empty()
    }
}

/// Read every configured account. Never fails as a whole: each account either
/// reports balances or reports why it could not.
pub async fn snapshot(sources: &WalletSources) -> WalletsSnapshot {
    let mut accounts: Vec<WalletAccount> = Vec::new();

    if let Some((key, secret, paper)) = &sources.alpaca {
        accounts.push(alpaca_account(key, secret, *paper).await);
    }
    for (exchange, key, secret, passphrase) in &sources.exchanges {
        accounts.push(exchange_account(*exchange, key, secret, passphrase).await);
    }
    for w in &sources.addresses {
        accounts.push(onchain_account(w).await);
    }

    // Price whatever is still unpriced, in one public call.
    let wanted: Vec<String> = accounts
        .iter()
        .flat_map(|a| a.balances.iter())
        .filter(|b| b.usd_value.is_none() && b.total > 0.0)
        .map(|b| b.asset.clone())
        .collect::<std::collections::BTreeSet<_>>()
        .into_iter()
        .collect();
    let prices = if wanted.is_empty() { HashMap::new() } else { usd_prices(&wanted).await };

    let mut unpriced: Vec<String> = Vec::new();
    for a in &mut accounts {
        for b in &mut a.balances {
            if b.usd_value.is_none() {
                match prices.get(&b.asset) {
                    Some(p) => b.usd_value = Some(b.total * p),
                    None if b.total > 0.0 => unpriced.push(b.asset.clone()),
                    None => {}
                }
            }
        }
        a.usd_total = a.balances.iter().filter_map(|b| b.usd_value).sum();
    }
    unpriced.sort();
    unpriced.dedup();

    WalletsSnapshot {
        usd_total: accounts.iter().map(|a| a.usd_total).sum(),
        accounts,
        unpriced,
        updated_at: chrono::Utc::now().timestamp_millis(),
    }
}

async fn alpaca_account(key: &str, secret: &str, paper: bool) -> WalletAccount {
    let conn = AlpacaConnector::new(Some(key.into()), Some(secret.into()), paper);
    let label = conn.label();
    match conn.balances().await {
        Ok(balances) => WalletAccount {
            id: "alpaca".into(),
            kind: WalletKind::Broker,
            provider: "Alpaca".into(),
            label,
            connected: true,
            can_trade: true,
            usd_total: balances.iter().filter_map(|b| b.usd_value).sum(),
            balances,
            error: None,
        },
        Err(e) => WalletAccount::failed("alpaca", WalletKind::Broker, "Alpaca", &label, e.to_string()),
    }
}

async fn exchange_account(ex: Exchange, key: &str, secret: &str, passphrase: &str) -> WalletAccount {
    let id = format!("cex:{}", ex.id());
    let conn = CexConnector::new(ex, key.into(), secret.into(), passphrase.into());
    match conn.balances().await {
        Ok(balances) => WalletAccount {
            id,
            kind: WalletKind::Exchange,
            provider: ex.label().into(),
            label: ex.label().into(),
            connected: true,
            can_trade: ex.can_trade(),
            usd_total: balances.iter().filter_map(|b| b.usd_value).sum(),
            balances,
            error: None,
        },
        Err(e) => WalletAccount::failed(&id, WalletKind::Exchange, ex.label(), ex.label(), e.to_string()),
    }
}

async fn onchain_account(w: &WatchedAddress) -> WalletAccount {
    let id = format!("{}:{}", w.chain.id(), w.address);
    let label = if w.label.trim().is_empty() {
        format!("{} · {}", w.chain.label(), shorten(&w.address))
    } else {
        w.label.clone()
    };
    if let Err(e) = w.validate() {
        return WalletAccount::failed(&id, WalletKind::Onchain, w.chain.label(), &label, e);
    }
    match native_balance(w).await {
        Ok(amount) => WalletAccount {
            id,
            kind: WalletKind::Onchain,
            provider: w.chain.label().into(),
            label,
            connected: true,
            can_trade: false, // watch-only, always
            balances: vec![Balance {
                asset: w.chain.native_asset().into(),
                free: amount,
                total: amount,
                usd_value: None, // priced below
            }],
            usd_total: 0.0,
            error: None,
        },
        Err(e) => WalletAccount::failed(&id, WalletKind::Onchain, w.chain.label(), &label, e),
    }
}

fn shorten(addr: &str) -> String {
    if addr.len() <= 14 {
        return addr.to_string();
    }
    format!("{}…{}", &addr[..8], &addr[addr.len() - 4..])
}

fn client() -> reqwest::Client {
    reqwest::Client::builder().timeout(HTTP_TIMEOUT).build().unwrap_or_default()
}

/// Native-asset balance for one watched address.
async fn native_balance(w: &WatchedAddress) -> Result<f64, String> {
    let raw = match w.chain {
        Chain::Bitcoin => bitcoin_balance(&w.address).await?,
        Chain::Solana => {
            let v = json_rpc(w.chain.rpc_url(), "getBalance", serde_json::json!([w.address])).await?;
            v.get("value").and_then(Value::as_f64).ok_or("no balance in response")?
        }
        _ => {
            let v = json_rpc(
                w.chain.rpc_url(),
                "eth_getBalance",
                serde_json::json!([w.address, "latest"]),
            )
            .await?;
            let hex = v.as_str().ok_or("no balance in response")?;
            hex_to_f64(hex)?
        }
    };
    Ok(raw / w.chain.decimals())
}

/// Minimal JSON-RPC 2.0 call; returns the `result` member.
async fn json_rpc(url: &str, method: &str, params: Value) -> Result<Value, String> {
    let body = serde_json::json!({"jsonrpc": "2.0", "id": 1, "method": method, "params": params});
    let resp = client()
        .post(url)
        .json(&body)
        .send()
        .await
        .map_err(|e| format!("{method}: {e}"))?;
    if !resp.status().is_success() {
        return Err(format!("{method}: HTTP {}", resp.status().as_u16()));
    }
    let v: Value = resp.json().await.map_err(|e| format!("{method}: {e}"))?;
    if let Some(err) = v.get("error") {
        let msg = err.get("message").and_then(Value::as_str).unwrap_or("rpc error");
        return Err(format!("{method}: {msg}"));
    }
    v.get("result").cloned().ok_or_else(|| format!("{method}: no result"))
}

async fn bitcoin_balance(address: &str) -> Result<f64, String> {
    let url = format!("{}/address/{address}", Chain::Bitcoin.rpc_url());
    let resp = client().get(&url).send().await.map_err(|e| e.to_string())?;
    if !resp.status().is_success() {
        return Err(format!("HTTP {}", resp.status().as_u16()));
    }
    let v: Value = resp.json().await.map_err(|e| e.to_string())?;
    // Confirmed balance = funded − spent, in satoshi.
    let stats = v.get("chain_stats").ok_or("no chain_stats")?;
    let funded = stats.get("funded_txo_sum").and_then(Value::as_f64).unwrap_or(0.0);
    let spent = stats.get("spent_txo_sum").and_then(Value::as_f64).unwrap_or(0.0);
    Ok((funded - spent).max(0.0))
}

/// `0x1a2b…` → f64. Balances beyond 2^53 wei lose precision, which at 1e18 wei
/// per ETH means we are exact to ~0.000000001 ETH — far below anything visible.
fn hex_to_f64(hex: &str) -> Result<f64, String> {
    let s = hex.trim_start_matches("0x");
    if s.is_empty() {
        return Ok(0.0);
    }
    let mut acc = 0.0f64;
    for c in s.chars() {
        let d = c.to_digit(16).ok_or_else(|| format!("bad hex quantity: {hex}"))?;
        acc = acc * 16.0 + d as f64;
    }
    Ok(acc)
}

/// Best-effort USD prices from Kraken's public ticker (no key needed). Assets
/// Kraken does not list stay unpriced rather than being guessed at.
async fn usd_prices(assets: &[String]) -> HashMap<String, f64> {
    let mut out = HashMap::new();
    let pairs: Vec<String> = assets
        .iter()
        .filter_map(|a| kraken_pair(a).map(str::to_string))
        .collect();
    // Stablecoins are their own price; no need to ask.
    for a in assets {
        if matches!(a.as_str(), "USD" | "USDT" | "USDC" | "DAI") {
            out.insert(a.clone(), 1.0);
        }
    }
    if pairs.is_empty() {
        return out;
    }

    let url = format!("https://api.kraken.com/0/public/Ticker?pair={}", pairs.join(","));
    let Ok(resp) = client().get(&url).send().await else { return out };
    let Ok(v) = resp.json::<Value>().await else { return out };
    let Some(result) = v.get("result").and_then(Value::as_object) else { return out };

    for (key, val) in result {
        let Some(asset) = kraken_result_asset(key) else { continue };
        let last = val
            .get("c")
            .and_then(|c| c.get(0))
            .and_then(Value::as_str)
            .and_then(|s| s.parse::<f64>().ok());
        if let Some(p) = last.filter(|p| *p > 0.0) {
            out.insert(asset, p);
        }
    }
    out
}

/// Our asset code → the Kraken USD pair to quote it with.
fn kraken_pair(asset: &str) -> Option<&'static str> {
    Some(match asset {
        "BTC" => "XBTUSD",
        "ETH" => "ETHUSD",
        "SOL" => "SOLUSD",
        "ADA" => "ADAUSD",
        "DOT" => "DOTUSD",
        "LINK" => "LINKUSD",
        "AVAX" => "AVAXUSD",
        "XRP" => "XRPUSD",
        "LTC" => "LTCUSD",
        "POL" => "POLUSD",
        "BNB" => "BNBUSD",
        "DOGE" => "XDGUSD",
        "ATOM" => "ATOMUSD",
        "UNI" => "UNIUSD",
        "AAVE" => "AAVEUSD",
        _ => return None,
    })
}

/// Reverse of [`kraken_pair`] over Kraken's own result keys, which carry its
/// legacy asset spellings (`XXBTZUSD`, `XETHZUSD`, `SOLUSD`).
fn kraken_result_asset(key: &str) -> Option<String> {
    let base = key
        .strip_suffix("ZUSD")
        .or_else(|| key.strip_suffix("USD"))?;
    if base.is_empty() {
        return None;
    }
    let a = normalize_asset(base);
    Some(if a == "XDG" { "DOGE".into() } else { a })
}

// ── free cash for an autopilot ──────────────────────────────────────────────

/// The quote cash an account can spend right now, in USD: free US dollars and
/// dollar stablecoins. Coins already held are not cash, and neither are other
/// fiat currencies, which would need a conversion first.
pub fn free_usd_cash(balances: &[Balance]) -> f64 {
    balances
        .iter()
        .filter(|b| matches!(normalize_asset(&b.asset).as_str(), "USD" | "USDT" | "USDC"))
        .map(|b| b.free.max(0.0))
        .sum()
}

/// Read the free cash at a venue (a cost venue id such as "kraken" or
/// "alpaca") before a live autopilot starts: its amount may not exceed it.
///
/// Read-only, like everything in this module. The autopilot trades the money
/// the owner put into that account; nothing here or anywhere else in Pythia can
/// deposit, withdraw or transfer it, and a watched wallet stays watched.
pub async fn available_cash(creds: &crate::execution::Credentials, venue: &str, paper: bool) -> Result<f64, String> {
    use crate::costs::CostVenue;
    match CostVenue::parse(venue) {
        Some(CostVenue::Alpaca) => {
            let conn = creds.alpaca_connector(paper, false)?;
            let account = conn.account().await.map_err(|e| e.to_string())?;
            // Settled cash, never margin: buying power can be a multiple of it.
            let cash: f64 = account.cash.trim().parse().unwrap_or(0.0);
            Ok(cash.min(account.buying_power_f64()).max(0.0))
        }
        Some(CostVenue::Polymarket) => Err("Polymarket has no order path in Pythia".into()),
        Some(cv) => {
            let Some((ex, key, secret, passphrase)) = &creds.exchange else {
                return Err(format!("no API keys for {venue} are set"));
            };
            if CostVenue::for_exchange(*ex) != cv {
                return Err(format!("the exchange with keys is {}, not {venue}", ex.label()));
            }
            let conn = CexConnector::new(*ex, key.clone(), secret.clone(), passphrase.clone());
            let balances = conn.balances().await.map_err(|e| e.to_string())?;
            Ok(free_usd_cash(&balances))
        }
        None => Err(format!("unknown venue {venue}")),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn free_cash_is_free_dollars_and_dollar_stablecoins_only() {
        let b = |asset: &str, free: f64, total: f64| Balance { asset: asset.into(), free, total, usd_value: None };
        let balances = [b("USD", 700.0, 1_000.0), b("USDT", 50.0, 50.0), b("USDC", 25.0, 25.0), b("BTC", 0.5, 0.5), b("EUR", 300.0, 300.0)];
        // 300 USD is held in open orders, the coins are not cash, EUR needs converting first.
        assert_eq!(free_usd_cash(&balances), 775.0);
    }

    #[test]
    fn evm_addresses_are_shape_checked() {
        let good = WatchedAddress {
            chain: Chain::Ethereum,
            address: "0x742d35Cc6634C0532925a3b844Bc454e4438f44e".into(),
            label: String::new(),
        };
        assert!(good.validate().is_ok());

        for bad in ["742d35Cc6634C0532925a3b844Bc454e4438f44e", "0xdeadbeef", "0xZZZd35Cc6634C0532925a3b844Bc454e4438f44e", ""] {
            let w = WatchedAddress { chain: Chain::Ethereum, address: bad.into(), label: String::new() };
            assert!(w.validate().is_err(), "{bad} should be rejected");
        }
    }

    #[test]
    fn non_evm_addresses_use_their_own_rules() {
        let sol = WatchedAddress {
            chain: Chain::Solana,
            address: "9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM".into(),
            label: String::new(),
        };
        assert!(sol.validate().is_ok());
        // An EVM address is not a Solana address.
        let wrong = WatchedAddress { chain: Chain::Solana, address: "0xdead".into(), label: String::new() };
        assert!(wrong.validate().is_err());

        let btc = WatchedAddress {
            chain: Chain::Bitcoin,
            address: "bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq".into(),
            label: String::new(),
        };
        assert!(btc.validate().is_ok());
    }

    #[test]
    fn hex_quantities_convert_including_the_empty_and_zero_cases() {
        assert_eq!(hex_to_f64("0x0").unwrap(), 0.0);
        assert_eq!(hex_to_f64("0x").unwrap(), 0.0);
        assert_eq!(hex_to_f64("0xde0b6b3a7640000").unwrap(), 1e18, "1 ETH in wei");
        assert_eq!(hex_to_f64("0xff").unwrap(), 255.0);
        assert!(hex_to_f64("0xnope").is_err());
    }

    #[test]
    fn wei_converts_to_whole_units() {
        assert_eq!(hex_to_f64("0xde0b6b3a7640000").unwrap() / Chain::Ethereum.decimals(), 1.0);
        assert_eq!(1e8 / Chain::Bitcoin.decimals(), 1.0, "satoshi → BTC");
        assert_eq!(1e9 / Chain::Solana.decimals(), 1.0, "lamports → SOL");
    }

    #[test]
    fn kraken_result_keys_map_back_to_our_asset_codes() {
        assert_eq!(kraken_result_asset("XXBTZUSD").as_deref(), Some("BTC"));
        assert_eq!(kraken_result_asset("XETHZUSD").as_deref(), Some("ETH"));
        assert_eq!(kraken_result_asset("SOLUSD").as_deref(), Some("SOL"));
        assert_eq!(kraken_result_asset("XDGUSD").as_deref(), Some("DOGE"));
        // A non-USD pair must not be mistaken for one.
        assert_eq!(kraken_result_asset("ETHXBT"), None);
    }

    #[test]
    fn every_chain_has_an_endpoint_and_a_native_asset() {
        for c in Chain::ALL {
            assert!(c.rpc_url().starts_with("https://"), "{}", c.id());
            assert!(!c.native_asset().is_empty());
            assert_eq!(Chain::parse(c.id()), Some(c));
        }
    }

    #[test]
    fn addresses_shorten_for_display_without_losing_the_ends() {
        let s = shorten("0x742d35Cc6634C0532925a3b844Bc454e4438f44e");
        assert!(s.starts_with("0x742d35") && s.ends_with("f44e"));
        assert_eq!(shorten("short"), "short");
    }

    #[tokio::test]
    async fn an_empty_source_set_produces_an_empty_snapshot_not_an_error() {
        let s = snapshot(&WalletSources::default()).await;
        assert!(s.accounts.is_empty());
        assert_eq!(s.usd_total, 0.0);
    }

    #[tokio::test]
    async fn a_bad_address_reports_on_that_account_only() {
        let sources = WalletSources {
            addresses: vec![WatchedAddress { chain: Chain::Ethereum, address: "0xnope".into(), label: "typo".into() }],
            ..Default::default()
        };
        let s = snapshot(&sources).await;
        assert_eq!(s.accounts.len(), 1);
        assert!(!s.accounts[0].connected);
        assert!(s.accounts[0].error.is_some());
        assert!(!s.accounts[0].can_trade, "on-chain is never tradable");
    }

    #[test]
    fn stablecoins_are_priced_without_a_network_call() {
        // usd_prices short-circuits these; kraken_pair deliberately has no entry.
        assert_eq!(kraken_pair("USDT"), None);
        assert_eq!(kraken_pair("BTC"), Some("XBTUSD"));
    }
}
