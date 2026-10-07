//! Read-only market data. Real feeds:
//!   · Kraken     — spot crypto last/open price  (https://api.kraken.com, no auth)
//!   · Kraken / Binance — top-20 order books for the cost model (public, no auth)
//!   · Polymarket — Gamma API prediction odds     (https://gamma-api.polymarket.com, no auth)
//!   · Alpaca     — equity snapshots              (https://data.alpaca.markets, needs keys)
//!
//! Every fetch is time-boxed and falls back to an empty result on any failure,
//! so the engine keeps running on its simulator if the network is down or a
//! venue is unreachable.

use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::time::Duration;

use crate::costs::CostVenue;
use crate::orderbook::{BookQuote, BookSnapshot, BOOK_LEVELS};

pub struct RealCrypto {
    pub id: String,
    pub symbol: String,
    pub price: f64,
    pub change24h: f64,
}

/// One completed candle. `ts` is the bar's OPEN time in epoch millis, which is
/// what both venues stamp, so a bar is only ever appended once its successor
/// appears — we never signal on a half-formed bar.
#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
pub struct Ohlc {
    pub ts: i64,
    pub open: f64,
    pub high: f64,
    pub low: f64,
    pub close: f64,
    pub volume: f64,
}

/// A market's candle history, oldest first.
#[derive(Debug, Clone)]
pub struct BarSeries {
    /// Engine market id (e.g. `alpaca:AAPL`, `crypto:BTC/USD`).
    pub id: String,
    pub bars: Vec<Ohlc>,
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

/// The crypto universe on Kraken: (pair to request, the key Kraken answers
/// with, our symbol). Kraken renames some pairs in its replies (XBTUSD comes
/// back as XXBTZUSD, DOGE trades as XDG), so the reply key is matched exactly
/// rather than guessed from substrings. These are the 20 coins the research
/// lab trains and backtests on, so a lab strategy can trade all of them here.
pub const KRAKEN_PAIRS: [(&str, &str, &str); 20] = [
    ("XBTUSD", "XXBTZUSD", "BTC/USD"),
    ("ETHUSD", "XETHZUSD", "ETH/USD"),
    ("SOLUSD", "SOLUSD", "SOL/USD"),
    ("XRPUSD", "XXRPZUSD", "XRP/USD"),
    ("XDGUSD", "XDGUSD", "DOGE/USD"),
    ("ADAUSD", "ADAUSD", "ADA/USD"),
    ("AVAXUSD", "AVAXUSD", "AVAX/USD"),
    ("LINKUSD", "LINKUSD", "LINK/USD"),
    ("LTCUSD", "XLTCZUSD", "LTC/USD"),
    ("DOTUSD", "DOTUSD", "DOT/USD"),
    ("BCHUSD", "BCHUSD", "BCH/USD"),
    ("TRXUSD", "TRXUSD", "TRX/USD"),
    ("SUIUSD", "SUIUSD", "SUI/USD"),
    ("NEARUSD", "NEARUSD", "NEAR/USD"),
    ("ATOMUSD", "ATOMUSD", "ATOM/USD"),
    ("UNIUSD", "UNIUSD", "UNI/USD"),
    ("AAVEUSD", "AAVEUSD", "AAVE/USD"),
    ("XLMUSD", "XXLMZUSD", "XLM/USD"),
    ("PEPEUSD", "PEPEUSD", "PEPE/USD"),
    ("FILUSD", "FILUSD", "FIL/USD"),
];

/// Kraken public Ticker for the crypto universe. `c[0]` = last trade, `o` = open.
pub async fn fetch_kraken() -> Vec<RealCrypto> {
    let pairs: Vec<&str> = KRAKEN_PAIRS.iter().map(|(p, _, _)| *p).collect();
    let url = format!("https://api.kraken.com/0/public/Ticker?pair={}", pairs.join(","));
    let Some(v) = get_json(&url).await else { return vec![] };
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

/// Map a Kraken reply key (e.g. "XXBTZUSD", "AVAXUSD") to our symbol.
fn kraken_symbol(key: &str) -> Option<&'static str> {
    KRAKEN_PAIRS.iter().find(|(req, reply, _)| *reply == key || *req == key).map(|(_, _, sym)| *sym)
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

// ── candle history ──────────────────────────────────────────────────────────
//
// Quotes tell you where a market IS; indicators need to know where it HAS BEEN.
// Feeding a 1.5s tick loop's own random walk into an EMA produces a beautiful,
// completely meaningless signal — so every tradable market's indicator series
// comes from these real candle feeds instead, and the engine refuses to signal
// on a market it has no bars for.

/// Alpaca candles for the equity universe.
///
/// `GET /v2/stocks/bars?symbols=…&timeframe=…&start=…&feed=…`. `adjustment=split`
/// keeps the series continuous across stock splits — without it a 4:1 split
/// looks like a −75% crash and every trend strategy shorts into it.
pub async fn fetch_alpaca_bars(
    key_id: &str,
    secret: &str,
    feed: &str,
    timeframe: &str,
    lookback_days: i64,
) -> Vec<BarSeries> {
    if key_id.trim().is_empty() || secret.trim().is_empty() {
        return vec![];
    }
    let start = (chrono::Utc::now() - chrono::Duration::days(lookback_days)).to_rfc3339();
    let url = format!(
        "https://data.alpaca.markets/v2/stocks/bars?symbols={}&timeframe={}&start={}&feed={}&adjustment=split&sort=asc&limit=10000",
        ALPACA_SYMBOLS.join(","),
        timeframe,
        urlencode(&start),
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
    let Some(v) = tokio::time::timeout(Duration::from_secs(12), fut).await.ok().flatten() else {
        return vec![];
    };
    parse_alpaca_bars(&v)
}

/// Map an Alpaca `/v2/stocks/bars` payload to our series. Split out so the
/// field mapping is unit-testable without keys or a network call.
fn parse_alpaca_bars(v: &Value) -> Vec<BarSeries> {
    let Some(map) = v.get("bars").and_then(Value::as_object) else { return vec![] };
    let mut out = Vec::new();
    for (symbol, arr) in map {
        let Some(arr) = arr.as_array() else { continue };
        let mut bars: Vec<Ohlc> = arr
            .iter()
            .filter_map(|b| {
                Some(Ohlc {
                    ts: chrono::DateTime::parse_from_rfc3339(b.get("t")?.as_str()?)
                        .ok()?
                        .timestamp_millis(),
                    open: b.get("o")?.as_f64()?,
                    high: b.get("h")?.as_f64()?,
                    low: b.get("l")?.as_f64()?,
                    close: b.get("c")?.as_f64()?,
                    volume: b.get("v").and_then(Value::as_f64).unwrap_or(0.0),
                })
            })
            .filter(|b| b.close > 0.0)
            .collect();
        if bars.is_empty() {
            continue;
        }
        bars.sort_by_key(|b| b.ts);
        out.push(BarSeries { id: format!("alpaca:{symbol}"), bars });
    }
    out
}

/// Kraken OHLC for the crypto universe. The endpoint is single-pair, so this
/// fans out one request per pair and drops any that fail — a partial refresh is
/// better than none, and the engine only trades markets whose bars it has.
pub async fn fetch_kraken_bars(interval_min: u32) -> Vec<BarSeries> {
    // Fan out concurrently: twenty sequential 5s timeouts would stall the tick
    // loop for minutes on a bad network.
    let handles: Vec<_> = KRAKEN_PAIRS
        .iter()
        .map(|(pair, _, symbol)| {
            let url =
                format!("https://api.kraken.com/0/public/OHLC?pair={pair}&interval={interval_min}");
            let id = format!("crypto:{symbol}");
            tokio::spawn(async move {
                let bars = parse_kraken_ohlc(&get_json(&url).await?)?;
                Some(BarSeries { id, bars })
            })
        })
        .collect();

    let mut out = Vec::new();
    for h in handles {
        if let Ok(Some(s)) = h.await {
            out.push(s);
        }
    }
    out
}

/// Kraken returns `{result: {<canonical pair>: [[time, o, h, l, c, vwap, vol, count], …], last: …}}`
/// with numbers as strings. The canonical pair name differs from the requested
/// one (`XBTUSD` → `XXBTZUSD`), so we take the first non-`last` key.
fn parse_kraken_ohlc(v: &Value) -> Option<Vec<Ohlc>> {
    let result = v.get("result")?.as_object()?;
    let arr = result.iter().find(|(k, _)| k.as_str() != "last").map(|(_, v)| v)?.as_array()?;
    let num = |x: Option<&Value>| -> Option<f64> {
        match x? {
            Value::String(s) => s.parse::<f64>().ok(),
            other => other.as_f64(),
        }
    };
    let mut bars: Vec<Ohlc> = arr
        .iter()
        .filter_map(|row| {
            let r = row.as_array()?;
            Some(Ohlc {
                ts: num(r.first())? as i64 * 1000,
                open: num(r.get(1))?,
                high: num(r.get(2))?,
                low: num(r.get(3))?,
                close: num(r.get(4))?,
                volume: num(r.get(6)).unwrap_or(0.0),
            })
        })
        .filter(|b| b.close > 0.0)
        .collect();
    if bars.is_empty() {
        return None;
    }
    bars.sort_by_key(|b| b.ts);
    Some(bars)
}

// ── order books ─────────────────────────────────────────────────────────────
//
// Candles say where a market has been; the book says what crossing it costs
// right now. The cost model prices impact against the notional on the 20 best
// levels of the side an order takes (see `crate::orderbook`), so both venues
// are asked for exactly 20 levels. Public endpoints, no keys.

/// Top-20 books for the crypto universe on the exchange whose costs the engine
/// charges. Kraken and Binance are the two the cost model was calibrated on;
/// any other venue returns nothing and its fills keep the calibrated defaults.
///
/// Both endpoints are single-pair, so this fans out one request per coin like
/// [`fetch_kraken_bars`], and drops any that fail.
pub async fn fetch_books(venue: CostVenue) -> Vec<BookSnapshot> {
    let handles: Vec<_> = KRAKEN_PAIRS
        .iter()
        .filter_map(|(pair, _, symbol)| {
            let url = match venue {
                CostVenue::Kraken => {
                    format!("https://api.kraken.com/0/public/Depth?pair={pair}&count={BOOK_LEVELS}")
                }
                CostVenue::Binance => format!(
                    "https://api.binance.com/api/v3/depth?symbol={}&limit={BOOK_LEVELS}",
                    binance_symbol(symbol)
                ),
                _ => return None,
            };
            let id = format!("crypto:{symbol}");
            Some(tokio::spawn(async move {
                let v = get_json(&url).await?;
                let now = chrono::Utc::now().timestamp_millis();
                let quote = match venue {
                    CostVenue::Kraken => parse_kraken_depth(&v, now)?,
                    _ => parse_binance_depth(&v, now)?,
                };
                Some(BookSnapshot { id, quote })
            }))
        })
        .collect();

    let mut out = Vec::new();
    for h in handles {
        if let Ok(Some(s)) = h.await {
            out.push(s);
        }
    }
    out
}

/// `BTC/USD` → `BTCUSDT`. Binance quotes the universe in USDT; the recorder and
/// the cost calibration used the same books, so this is the market whose
/// spread and depth `config/costs.json` describes.
fn binance_symbol(symbol: &str) -> String {
    let base = symbol.split('/').next().unwrap_or(symbol);
    format!("{base}USDT")
}

/// One side of a book as `(price, qty)`. Both venues send `[price, qty, ...]`
/// rows with numbers as strings; Kraken appends a timestamp, which is ignored.
fn book_side(v: Option<&Value>) -> Vec<(f64, f64)> {
    let num = |x: Option<&Value>| -> Option<f64> {
        match x? {
            Value::String(s) => s.parse::<f64>().ok(),
            other => other.as_f64(),
        }
    };
    v.and_then(Value::as_array)
        .map(|rows| {
            rows.iter()
                .filter_map(|r| {
                    let r = r.as_array()?;
                    Some((num(r.first())?, num(r.get(1))?))
                })
                .collect()
        })
        .unwrap_or_default()
}

/// Kraken `Depth`: `{error: [], result: {<canonical pair>: {asks: [[p, v, ts]], bids: [...]}}}`.
/// The reply key is renamed (`XBTUSD` → `XXBTZUSD`), and there is exactly one
/// pair per request, so the first entry is the book.
fn parse_kraken_depth(v: &Value, now: i64) -> Option<BookQuote> {
    let (_, book) = v.get("result")?.as_object()?.iter().next()?;
    BookQuote::from_levels(CostVenue::Kraken, &book_side(book.get("bids")), &book_side(book.get("asks")), now)
}

/// Binance `depth`: `{lastUpdateId, bids: [[p, q]], asks: [[p, q]]}`. An error
/// (`{code, msg}`) has no sides and yields `None`.
fn parse_binance_depth(v: &Value, now: i64) -> Option<BookQuote> {
    BookQuote::from_levels(CostVenue::Binance, &book_side(v.get("bids")), &book_side(v.get("asks")), now)
}

/// Minimal percent-encoding for the RFC3339 timestamps we put in query strings
/// (`:` and `+` are the only characters that actually matter here).
fn urlencode(s: &str) -> String {
    s.chars()
        .map(|c| match c {
            ':' => "%3A".to_string(),
            '+' => "%2B".to_string(),
            _ => c.to_string(),
        })
        .collect()
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
        assert!(fetch_alpaca_bars("", "", "iex", "5Min", 5).await.is_empty());
    }

    #[test]
    fn parses_alpaca_bars_payload() {
        let v: Value = serde_json::from_str(
            r#"{"bars": {"AAPL": [
                 {"t":"2026-07-23T13:35:00Z","o":227.0,"h":228.0,"l":226.5,"c":227.8,"v":1200},
                 {"t":"2026-07-23T13:30:00Z","o":226.0,"h":227.2,"l":225.8,"c":227.0,"v":900}
               ]}, "next_page_token": null}"#,
        )
        .unwrap();

        let series = parse_alpaca_bars(&v);
        assert_eq!(series.len(), 1);
        assert_eq!(series[0].id, "alpaca:AAPL");
        // Out-of-order input is sorted oldest-first — indicators assume it.
        assert_eq!(series[0].bars.len(), 2);
        assert!(series[0].bars[0].ts < series[0].bars[1].ts);
        assert_eq!(series[0].bars[1].close, 227.8);
    }

    #[test]
    fn kraken_reply_keys_map_exactly() {
        // The renamed ones, and ones a substring match used to confuse.
        assert_eq!(kraken_symbol("XXBTZUSD"), Some("BTC/USD"));
        assert_eq!(kraken_symbol("XDGUSD"), Some("DOGE/USD"));
        assert_eq!(kraken_symbol("XXLMZUSD"), Some("XLM/USD"));
        assert_eq!(kraken_symbol("XLTCZUSD"), Some("LTC/USD"));
        assert_eq!(kraken_symbol("AAVEUSD"), Some("AAVE/USD"));
        assert_eq!(kraken_symbol("SOLUSD"), Some("SOL/USD"));
        assert_eq!(kraken_symbol("XETHZUSD"), Some("ETH/USD"));
        assert_eq!(kraken_symbol("SOMETHINGUSD"), None);
        let symbols: std::collections::HashSet<_> = KRAKEN_PAIRS.iter().map(|p| p.2).collect();
        assert_eq!(symbols.len(), 20, "no two pairs may claim the same symbol");
    }

    #[test]
    fn parses_kraken_ohlc_payload() {
        // Kraken sends numbers as strings and renames the pair (XBTUSD → XXBTZUSD).
        let v: Value = serde_json::from_str(
            r#"{"error":[],"result":{"XXBTZUSD":[
                 [1753000000,"67000.0","67200.0","66900.0","67100.0","67050.0","12.5",42],
                 [1753000300,"67100.0","67400.0","67050.0","67350.0","67200.0","9.1",31]
               ],"last":1753000300}}"#,
        )
        .unwrap();

        let bars = parse_kraken_ohlc(&v).expect("bars");
        assert_eq!(bars.len(), 2, "the `last` cursor key must not be read as a pair");
        assert_eq!(bars[0].ts, 1_753_000_000_000, "seconds are promoted to millis");
        assert_eq!(bars[1].close, 67_350.0);
        assert_eq!(bars[1].high, 67_400.0);
    }

    #[test]
    fn kraken_ohlc_rejects_an_empty_result() {
        let v: Value = serde_json::from_str(r#"{"error":["EQuery:Unknown asset pair"],"result":{}}"#).unwrap();
        assert!(parse_kraken_ohlc(&v).is_none());
    }

    #[test]
    fn parses_a_kraken_depth_payload() {
        // Shape per Kraken /0/public/Depth: strings for price and volume, a
        // timestamp third, and the pair renamed in the reply.
        let v: Value = serde_json::from_str(
            r#"{"error":[],"result":{"XXBTZUSD":{
                 "asks":[["67010.0","0.5",1790000000],["67000.0","1.0",1790000001]],
                 "bids":[["66990.0","2.0",1790000000],["66980.0","1.5",1790000002]]
               }}}"#,
        )
        .unwrap();
        let q = parse_kraken_depth(&v, 42).expect("book");
        assert_eq!(q.venue, CostVenue::Kraken);
        assert_eq!(q.ts, 42, "stamped with receipt time");
        assert!((q.mid - 66_995.0).abs() < 1e-9, "best ask 67000 even though it came second");
        assert!((q.half_spread_bps - 5.0 / 66_995.0 * 10_000.0).abs() < 1e-9);
        assert!((q.ask_depth - (67_010.0 * 0.5 + 67_000.0)).abs() < 1e-6);
        assert!((q.bid_depth - (66_990.0 * 2.0 + 66_980.0 * 1.5)).abs() < 1e-6);

        let err: Value = serde_json::from_str(r#"{"error":["EQuery:Unknown asset pair"]}"#).unwrap();
        assert!(parse_kraken_depth(&err, 42).is_none());
    }

    #[test]
    fn parses_a_binance_depth_payload() {
        let v: Value = serde_json::from_str(
            r#"{"lastUpdateId":1027024,
                "bids":[["3500.10","4.0"],["3500.00","10.0"]],
                "asks":[["3500.20","3.0"],["3500.30","0.0"]]}"#,
        )
        .unwrap();
        let q = parse_binance_depth(&v, 7).expect("book");
        assert_eq!(q.venue, CostVenue::Binance);
        assert!((q.half_spread_bps - 0.1 / 3500.15 / 2.0 * 10_000.0).abs() < 1e-9);
        assert!((q.bid_depth - (3500.10 * 4.0 + 3500.0 * 10.0)).abs() < 1e-6);
        // A zero-quantity level is no liquidity at all.
        assert!((q.ask_depth - 3500.20 * 3.0).abs() < 1e-6);

        let err: Value = serde_json::from_str(r#"{"code":-1121,"msg":"Invalid symbol."}"#).unwrap();
        assert!(parse_binance_depth(&err, 7).is_none());
    }

    #[test]
    fn binance_books_are_the_usdt_markets_the_calibration_used() {
        assert_eq!(binance_symbol("BTC/USD"), "BTCUSDT");
        assert_eq!(binance_symbol("PEPE/USD"), "PEPEUSDT");
    }

    #[tokio::test]
    async fn venues_without_a_calibrated_book_fetch_nothing() {
        // No request is even built for these, so this never touches the network.
        assert!(fetch_books(CostVenue::Okx).await.is_empty());
        assert!(fetch_books(CostVenue::Alpaca).await.is_empty());
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
