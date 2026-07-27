//! Read-only market data. Real feeds:
//!   · Kraken     — spot crypto last/open price  (https://api.kraken.com, no auth)
//!   · Polymarket — Gamma API prediction odds     (https://gamma-api.polymarket.com, no auth)
//!   · Alpaca     — equity snapshots              (https://data.alpaca.markets, needs keys)
//!
//! Every fetch is time-boxed and falls back to an empty result on any failure,
//! so the engine keeps running on its simulator if the network is down or a
//! venue is unreachable.

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
    /// NO outcome price. YES + NO should be 1; when it is not, that gap is a
    /// model-free arbitrage (see `forecast::coherence`), so it is worth carrying.
    pub no_price: Option<f64>,
    pub liquidity: f64,
    /// Resolution time in epoch millis, when the venue states one. Drives the
    /// time-decay damping in the forecasters — a market resolving tomorrow has
    /// far less left to learn than one resolving in a year.
    pub end_at: Option<i64>,
}

pub struct RealEquity {
    pub id: String,
    pub symbol: String,
    pub price: f64,
    pub change24h: f64,
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

/// Kraken public Ticker for the crypto universe. `c[0]` = last trade, `o` = open.
pub async fn fetch_kraken() -> Vec<RealCrypto> {
    let url = "https://api.kraken.com/0/public/Ticker?pair=XBTUSD,ETHUSD,SOLUSD,ADAUSD,DOTUSD,LINKUSD,AVAXUSD,XRPUSD,LTCUSD";
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

        let sym = kraken_symbol(key);
        let Some(sym) = sym else { continue };
        let change = if open != 0.0 { (last - open) / open } else { 0.0 };
        out.push(RealCrypto { id: format!("crypto:{sym}"), symbol: sym.into(), price: last, change24h: change });
    }
    out
}

/// Map a Kraken pair key (e.g. "XXBTZUSD", "AVAXUSD") to our symbol.
fn kraken_symbol(key: &str) -> Option<&'static str> {
    if key.contains("XBT") || key.contains("BTC") {
        Some("BTC/USD")
    } else if key.contains("ETH") {
        Some("ETH/USD")
    } else if key.contains("SOL") {
        Some("SOL/USD")
    } else if key.contains("ADA") {
        Some("ADA/USD")
    } else if key.contains("AVAX") {
        Some("AVAX/USD")
    } else if key.contains("DOT") {
        Some("DOT/USD")
    } else if key.contains("LINK") {
        Some("LINK/USD")
    } else if key.contains("LTC") {
        Some("LTC/USD")
    } else if key.contains("XRP") {
        Some("XRP/USD")
    } else {
        None
    }
}

/// The equity universe we pull real quotes for (mirrors the engine's Alpaca seeds).
pub const ALPACA_SYMBOLS: [&str; 5] = ["AAPL", "NVDA", "MSFT", "AMZN", "TSLA"];

/// Alpaca multi-symbol snapshots → real last-trade price + daily change.
///
/// `GET /v2/stocks/snapshots?symbols=…&feed=iex` on data.alpaca.markets. `iex`
/// is the free-tier feed; paid plans can pass `sip`. Price prefers the latest
/// trade and falls back to the daily bar's close; change is measured against the
/// previous daily close. Outside market hours these simply stop moving — which
/// is correct, and the risk manager's staleness gate still applies.
pub async fn fetch_alpaca(key_id: &str, secret: &str, feed: &str) -> Vec<RealEquity> {
    if key_id.trim().is_empty() || secret.trim().is_empty() {
        return vec![];
    }
    let url = format!(
        "https://data.alpaca.markets/v2/stocks/snapshots?symbols={}&feed={}",
        ALPACA_SYMBOLS.join(","),
        feed
    );
    let fut = async {
        reqwest::Client::new()
            .get(&url)
            .header("APCA-API-KEY-ID", key_id)
            .header("APCA-API-SECRET-KEY", secret)
            .send()
            .await
            .ok()?
            .json::<Value>()
            .await
            .ok()
    };
    let Some(v) = tokio::time::timeout(Duration::from_secs(5), fut).await.ok().flatten() else {
        return vec![];
    };
    parse_snapshots(&v)
}

/// Map an Alpaca `/v2/stocks/snapshots` payload to our equity rows. Split out
/// so the field mapping is unit-testable without a network call or keys.
fn parse_snapshots(v: &Value) -> Vec<RealEquity> {
    let Some(map) = v.as_object() else { return vec![] };

    let mut out = Vec::new();
    for (symbol, snap) in map {
        // latest trade price, else today's close
        let price = snap
            .get("latestTrade")
            .and_then(|t| t.get("p"))
            .and_then(Value::as_f64)
            .or_else(|| snap.get("dailyBar").and_then(|b| b.get("c")).and_then(Value::as_f64));
        let Some(price) = price.filter(|p| *p > 0.0) else { continue };

        let prev = snap
            .get("prevDailyBar")
            .and_then(|b| b.get("c"))
            .and_then(Value::as_f64)
            .or_else(|| snap.get("dailyBar").and_then(|b| b.get("o")).and_then(Value::as_f64));
        let change = match prev {
            Some(p) if p > 0.0 => (price - p) / p,
            _ => 0.0,
        };

        out.push(RealEquity {
            id: format!("alpaca:{symbol}"),
            symbol: symbol.clone(),
            price,
            change24h: change,
        });
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
        // `outcomePrices` is a JSON-encoded string array: ["0.62","0.38"].
        let prices: Vec<f64> = m
            .get("outcomePrices")
            .and_then(Value::as_str)
            .and_then(|s| serde_json::from_str::<Vec<String>>(s).ok())
            .map(|v| v.iter().filter_map(|p| p.parse::<f64>().ok()).collect())
            .unwrap_or_default();
        let Some(&price) = prices.first() else { continue };
        if !(0.0..=1.0).contains(&price) {
            continue;
        }
        let no_price = prices.get(1).copied().filter(|p| (0.0..=1.0).contains(p));
        let liquidity = m.get("liquidityNum").and_then(Value::as_f64).unwrap_or(0.0);
        out.push(RealPrediction {
            id: format!("polymarket:{slug}"),
            symbol: question.to_string(),
            price,
            no_price,
            liquidity,
            end_at: parse_end_date(m),
        });
        if out.len() >= 8 {
            break;
        }
    }
    out
}

/// Gamma reports resolution as an ISO-8601 timestamp under `endDate` (older
/// payloads use `end_date_iso`). Absent or unparseable is fine — the forecasters
/// fall back to a neutral damping rather than guessing a date.
fn parse_end_date(m: &Value) -> Option<i64> {
    let raw = m
        .get("endDate")
        .or_else(|| m.get("end_date_iso"))
        .and_then(Value::as_str)?;
    chrono::DateTime::parse_from_rfc3339(raw)
        .ok()
        .map(|d| d.timestamp_millis())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_alpaca_snapshot_payload() {
        // Shape per Alpaca /v2/stocks/snapshots: latestTrade.p is the last price,
        // prevDailyBar.c the previous close.
        let v: Value = serde_json::from_str(
            r#"{
              "AAPL": {
                "latestTrade": {"p": 231.5, "s": 100},
                "dailyBar": {"o": 228.0, "c": 231.0},
                "prevDailyBar": {"o": 225.0, "c": 227.0}
              },
              "TSLA": {
                "dailyBar": {"o": 250.0, "c": 244.0},
                "prevDailyBar": {"c": 248.0}
              },
              "BADD": { "dailyBar": {"o": 1.0} }
            }"#,
        )
        .unwrap();

        let rows = parse_snapshots(&v);
        let aapl = rows.iter().find(|r| r.symbol == "AAPL").expect("AAPL");
        assert_eq!(aapl.id, "alpaca:AAPL");
        assert_eq!(aapl.price, 231.5, "prefers the latest trade price");
        assert!((aapl.change24h - (231.5 - 227.0) / 227.0).abs() < 1e-9, "change vs prev close");

        // No latestTrade → falls back to the daily close.
        let tsla = rows.iter().find(|r| r.symbol == "TSLA").expect("TSLA");
        assert_eq!(tsla.price, 244.0);
        assert!(tsla.change24h < 0.0);

        // No usable price → skipped entirely rather than emitting a zero.
        assert!(!rows.iter().any(|r| r.symbol == "BADD"));
    }

    #[tokio::test]
    async fn alpaca_without_keys_is_a_no_op() {
        assert!(fetch_alpaca("", "", "iex").await.is_empty());
    }

    #[test]
    fn resolution_dates_parse_from_both_field_spellings() {
        let a: Value = serde_json::json!({"endDate": "2026-09-01T12:00:00Z"});
        let b: Value = serde_json::json!({"end_date_iso": "2026-09-01T12:00:00Z"});
        assert_eq!(parse_end_date(&a), parse_end_date(&b));
        assert!(parse_end_date(&a).unwrap() > 0);

        // A missing or malformed date is not fatal — the forecasters cope.
        assert_eq!(parse_end_date(&serde_json::json!({})), None);
        assert_eq!(parse_end_date(&serde_json::json!({"endDate": "soon"})), None);
    }
}
