//! Read-only market data (Phase 1). Real, public, no-auth feeds:
//!   · Kraken     — spot crypto last/open price  (https://api.kraken.com)
//!   · Polymarket — Gamma API prediction odds     (https://gamma-api.polymarket.com)
//!
//! Every fetch is time-boxed and falls back to an empty result on any failure,
//! so the engine keeps running on its simulator if the network is down or a
//! venue is unreachable. Alpaca market data needs API keys → stays simulated
//! until keys are configured (Phase 2).

use serde_json::Value;
use std::time::Duration;

pub struct RealCrypto {
    pub id: String,
    pub symbol: String,
    pub price: f64,
    pub change24h: f64,
}

pub struct RealPrediction {
    pub id: String,
    pub symbol: String,
    pub price: f64, // YES outcome implied probability, 0..1
    pub liquidity: f64,
}

async fn get_json(url: &str) -> Option<Value> {
    let fut = async {
        reqwest::Client::new()
            .get(url)
            .header("User-Agent", "Pythia/0.1")
            .send()
            .await
            .ok()?
            .json::<Value>()
            .await
            .ok()
    };
    tokio::time::timeout(Duration::from_secs(5), fut).await.ok().flatten()
}

/// Kraken public Ticker for BTC/ETH/SOL. `c[0]` = last trade, `o` = today's open.
pub async fn fetch_kraken() -> Vec<RealCrypto> {
    let url = "https://api.kraken.com/0/public/Ticker?pair=XBTUSD,ETHUSD,SOLUSD";
    let Some(v) = get_json(url).await else { return vec![] };
    let Some(result) = v.get("result").and_then(Value::as_object) else { return vec![] };

    let mut out = Vec::new();
    for (key, val) in result {
        let last = val
            .get("c")
            .and_then(|c| c.get(0))
            .and_then(Value::as_str)
            .and_then(|s| s.parse::<f64>().ok());
        let open = val
            .get("o")
            .and_then(Value::as_str)
            .and_then(|s| s.parse::<f64>().ok());
        let (Some(last), Some(open)) = (last, open) else { continue };

        let (id, symbol) = if key.contains("XBT") || key.contains("BTC") {
            ("crypto:BTC/USD", "BTC/USD")
        } else if key.contains("ETH") {
            ("crypto:ETH/USD", "ETH/USD")
        } else if key.contains("SOL") {
            ("crypto:SOL/USD", "SOL/USD")
        } else {
            continue;
        };
        let change = if open != 0.0 { (last - open) / open } else { 0.0 };
        out.push(RealCrypto { id: id.into(), symbol: symbol.into(), price: last, change24h: change });
    }
    out
}

/// Polymarket Gamma API — a handful of active markets, highest volume first.
/// `outcomePrices` is a JSON-encoded string array; element 0 is the YES price.
pub async fn fetch_polymarket() -> Vec<RealPrediction> {
    let url = "https://gamma-api.polymarket.com/markets?closed=false&active=true&limit=12&order=volumeNum&ascending=false";
    let Some(v) = get_json(url).await else { return vec![] };
    let Some(arr) = v.as_array() else { return vec![] };

    let mut out = Vec::new();
    for m in arr {
        let question = m.get("question").and_then(Value::as_str).unwrap_or("");
        let slug = m.get("slug").and_then(Value::as_str).unwrap_or("");
        if question.is_empty() || slug.is_empty() {
            continue;
        }
        let price = m
            .get("outcomePrices")
            .and_then(Value::as_str)
            .and_then(|s| serde_json::from_str::<Vec<String>>(s).ok())
            .and_then(|prices| prices.first().and_then(|p| p.parse::<f64>().ok()));
        let Some(price) = price else { continue };
        if !(0.0..=1.0).contains(&price) {
            continue;
        }
        let liquidity = m.get("liquidityNum").and_then(Value::as_f64).unwrap_or(0.0);
        out.push(RealPrediction {
            id: format!("polymarket:{slug}"),
            symbol: question.to_string(),
            price,
            liquidity,
        });
        if out.len() >= 5 {
            break;
        }
    }
    out
}
