//! The polled side of the feeds: public REST endpoints of five venues, no keys.
//!
//! Every fetch answers `Result`: an error is a failed poll and counts against
//! the source (see [`super::FeedHealth::poll_failed`]), an empty `Ok` cannot
//! happen. Parsing is split from fetching so each venue's payload shape is
//! tested against a fixture without the network.
//!
//! Symbols: the universe is [`crate::coins::configured`] (`BTC/USD`...), and a
//! venue is only asked about the coins it lists ([`crate::coins::lists`]).
//! Kraken, Coinbase and Alpaca quote it in USD; Binance, Bybit and OKX in USDT,
//! the markets the recorder and the cost calibration used. USDT sits within a
//! few tenths of a percent of USD, far inside the sanity tolerance.

use std::sync::{Arc, OnceLock};
use std::time::Duration;

use serde_json::Value;

use super::FeedSource;
use crate::coins;
use crate::marketdata::{self, BarSeries, Ohlc, RealCrypto};
use crate::orderbook::{BookQuote, BookSnapshot, BOOK_LEVELS};
use crate::costs::CostVenue;

/// One client for every poll, so connections and TLS sessions are reused
/// instead of a handshake per request.
fn client() -> &'static reqwest::Client {
    static C: OnceLock<reqwest::Client> = OnceLock::new();
    C.get_or_init(|| {
        reqwest::Client::builder()
            .user_agent("Pythia/0.4")
            .pool_idle_timeout(Duration::from_secs(90))
            .build()
            .unwrap_or_default()
    })
}

async fn get(url: &str, secs: u64) -> Result<Value, String> {
    let fut = async {
        let r = client().get(url).send().await.map_err(|e| short(&e.to_string()))?;
        let status = r.status();
        if !status.is_success() {
            return Err(format!("HTTP {}", status.as_u16()));
        }
        r.json::<Value>().await.map_err(|e| format!("bad reply: {}", short(&e.to_string())))
    };
    tokio::time::timeout(Duration::from_secs(secs), fut).await.map_err(|_| format!("no answer in {secs} s"))?
}

fn short(s: &str) -> String {
    s.chars().take(120).collect()
}

fn num(x: Option<&Value>) -> Option<f64> {
    match x? {
        Value::String(s) => s.parse::<f64>().ok(),
        other => other.as_f64(),
    }
    .filter(|v| v.is_finite())
}

/// Our symbols, `BTC/USD` and so on: the configured universe.
pub fn universe() -> impl Iterator<Item = &'static str> {
    coins::configured().iter().copied()
}

/// The universe's coins `src` lists.
pub fn listed(src: FeedSource) -> impl Iterator<Item = &'static str> {
    universe().filter(move |s| coins::lists(src, s))
}

/// Engine market ids for the universe.
pub fn universe_ids() -> Vec<String> {
    universe().map(|s| format!("crypto:{s}")).collect()
}

fn base(symbol: &str) -> &str {
    symbol.split('/').next().unwrap_or(symbol)
}

/// The venue's name for one of our symbols.
pub fn venue_symbol(src: FeedSource, symbol: &str) -> String {
    let b = base(symbol);
    match src {
        FeedSource::KrakenWs => symbol.to_string(),
        FeedSource::Kraken => coins::coin(symbol).and_then(|c| c.kraken).map_or_else(|| format!("{b}USD"), |k| k.0.to_string()),
        FeedSource::Binance | FeedSource::BinanceVision | FeedSource::Bybit => format!("{b}USDT"),
        FeedSource::Coinbase => format!("{b}-USD"),
        FeedSource::Okx => format!("{b}-USDT"),
        FeedSource::Alpaca => symbol.to_string(),
    }
}

/// Back from a venue's name to ours, for the venues that answer for many
/// symbols at once.
fn our_symbol(src: FeedSource, venue_sym: &str) -> Option<&'static str> {
    universe().find(|s| venue_symbol(src, s) == venue_sym)
}

fn row(symbol: &str, price: f64, change: f64) -> RealCrypto {
    RealCrypto { id: format!("crypto:{symbol}"), symbol: symbol.to_string(), price, change24h: change }
}

fn nonempty<T>(v: Vec<T>, what: &str) -> Result<Vec<T>, String> {
    if v.is_empty() {
        Err(format!("no {what} in the reply"))
    } else {
        Ok(v)
    }
}

// ── quotes ───────────────────────────────────────────────────────────────

/// Last price and 24 h change for the universe, one request per venue.
pub async fn fetch_quotes(src: FeedSource) -> Result<Vec<RealCrypto>, String> {
    let syms: Vec<&str> = listed(src).collect();
    if syms.is_empty() {
        return Err(format!("{} lists none of the coins", src.label()));
    }
    match src {
        FeedSource::KrakenWs => Err("the stream is pushed, not polled".into()),
        FeedSource::Kraken => {
            let pairs: Vec<String> = syms.iter().map(|s| venue_symbol(src, s)).collect();
            let v = get(&format!("https://api.kraken.com/0/public/Ticker?pair={}", pairs.join(",")), 6).await?;
            if let Some(e) = v.get("error").and_then(Value::as_array).and_then(|a| a.first()) {
                return Err(format!("kraken: {e}"));
            }
            nonempty(marketdata::parse_kraken_ticker(&v), "prices")
        }
        FeedSource::Binance | FeedSource::BinanceVision => {
            let host = if src == FeedSource::Binance { "api.binance.com" } else { "data-api.binance.vision" };
            let list: Vec<String> = syms.iter().map(|s| format!("%22{}%22", venue_symbol(src, s))).collect();
            let url = format!("https://{host}/api/v3/ticker/24hr?type=MINI&symbols=%5B{}%5D", list.join(","));
            nonempty(parse_binance_tickers(&get(&url, 6).await?, src), "prices")
        }
        FeedSource::Coinbase => {
            let q: Vec<String> = syms.iter().map(|s| format!("product_ids={}", venue_symbol(src, s))).collect();
            let url = format!("https://api.coinbase.com/api/v3/brokerage/market/products?{}", q.join("&"));
            nonempty(parse_coinbase_products(&get(&url, 6).await?), "prices")
        }
        FeedSource::Bybit => {
            // Bybit has no multi-symbol ticker; all spot tickers is one request.
            let v = get("https://api.bybit.com/v5/market/tickers?category=spot", 8).await?;
            nonempty(parse_bybit_tickers(&v)?, "prices")
        }
        FeedSource::Okx => {
            let v = get("https://www.okx.com/api/v5/market/tickers?instType=SPOT", 8).await?;
            nonempty(parse_okx_tickers(&v)?, "prices")
        }
        FeedSource::Alpaca => {
            let url = format!("{ALPACA}/snapshots?symbols={}", alpaca_list(&syms));
            nonempty(parse_alpaca_snapshots(&get(&url, 8).await?), "prices")
        }
    }
}

/// Alpaca's public crypto data (v1beta3, US venue), keyless.
const ALPACA: &str = "https://data.alpaca.markets/v1beta3/crypto/us";

/// `BTC/USD,ETH/USD` with the slashes encoded.
fn alpaca_list(syms: &[&str]) -> String {
    syms.iter().map(|s| s.replace('/', "%2F")).collect::<Vec<_>>().join(",")
}

/// `{snapshots: {"BTC/USD": {latestTrade: {p}, latestQuote: {bp, ap},
/// dailyBar: {o, c}, prevDailyBar: {c}}}}`. The mark is the quote's mid while
/// the quote is sane (a thin coin's last trade can be minutes old), else the
/// last trade; the change is against the previous UTC day's close.
fn parse_alpaca_snapshots(v: &Value) -> Vec<RealCrypto> {
    let Some(map) = v.get("snapshots").and_then(Value::as_object) else { return vec![] };
    map.iter()
        .filter_map(|(vs, snap)| {
            let sym = our_symbol(FeedSource::Alpaca, vs)?;
            let (bid, ask) = (num(snap.pointer("/latestQuote/bp")), num(snap.pointer("/latestQuote/ap")));
            let mid = match (bid, ask) {
                (Some(b), Some(a)) if b > 0.0 && a >= b && (a - b) / a < 0.02 => Some((a + b) / 2.0),
                _ => None,
            };
            let price = mid
                .or_else(|| num(snap.pointer("/latestTrade/p")))
                .or_else(|| num(snap.pointer("/dailyBar/c")))
                .filter(|p| *p > 0.0)?;
            let prev = num(snap.pointer("/prevDailyBar/c")).or_else(|| num(snap.pointer("/dailyBar/o"))).filter(|p| *p > 0.0);
            Some(row(sym, price, prev.map_or(0.0, |p| (price - p) / p)))
        })
        .collect()
}

/// `[{symbol, openPrice, lastPrice, ...}]`, both 24 h rolling.
fn parse_binance_tickers(v: &Value, src: FeedSource) -> Vec<RealCrypto> {
    v.as_array()
        .map(|rows| {
            rows.iter()
                .filter_map(|r| {
                    let sym = our_symbol(src, r.get("symbol")?.as_str()?)?;
                    let last = num(r.get("lastPrice"))?;
                    let open = num(r.get("openPrice")).filter(|o| *o > 0.0);
                    Some(row(sym, last, open.map_or(0.0, |o| (last - o) / o)))
                })
                .collect()
        })
        .unwrap_or_default()
}

/// `{products: [{product_id: "BTC-USD", price, price_percentage_change_24h}]}`.
/// The change is in percent. A product Coinbase does not list is simply absent.
fn parse_coinbase_products(v: &Value) -> Vec<RealCrypto> {
    v.get("products")
        .and_then(Value::as_array)
        .map(|rows| {
            rows.iter()
                .filter_map(|r| {
                    let sym = our_symbol(FeedSource::Coinbase, r.get("product_id")?.as_str()?)?;
                    let price = num(r.get("price"))?;
                    let pct = num(r.get("price_percentage_change_24h")).unwrap_or(0.0);
                    Some(row(sym, price, pct / 100.0))
                })
                .collect()
        })
        .unwrap_or_default()
}

/// `{retCode: 0, result: {list: [{symbol, lastPrice, price24hPcnt}]}}`; the
/// change is a fraction.
fn parse_bybit_tickers(v: &Value) -> Result<Vec<RealCrypto>, String> {
    if v.get("retCode").and_then(Value::as_i64) != Some(0) {
        return Err(format!("bybit: {}", v.get("retMsg").and_then(Value::as_str).unwrap_or("error")));
    }
    Ok(v.pointer("/result/list")
        .and_then(Value::as_array)
        .map(|rows| {
            rows.iter()
                .filter_map(|r| {
                    let sym = our_symbol(FeedSource::Bybit, r.get("symbol")?.as_str()?)?;
                    Some(row(sym, num(r.get("lastPrice"))?, num(r.get("price24hPcnt")).unwrap_or(0.0)))
                })
                .collect()
        })
        .unwrap_or_default())
}

/// `{code: "0", data: [{instId: "BTC-USDT", last, open24h}]}`.
fn parse_okx_tickers(v: &Value) -> Result<Vec<RealCrypto>, String> {
    if v.get("code").and_then(Value::as_str) != Some("0") {
        return Err(format!("okx: {}", v.get("msg").and_then(Value::as_str).unwrap_or("error")));
    }
    Ok(v.get("data")
        .and_then(Value::as_array)
        .map(|rows| {
            rows.iter()
                .filter_map(|r| {
                    let sym = our_symbol(FeedSource::Okx, r.get("instId")?.as_str()?)?;
                    let last = num(r.get("last"))?;
                    let open = num(r.get("open24h")).filter(|o| *o > 0.0);
                    Some(row(sym, last, open.map_or(0.0, |o| (last - o) / o)))
                })
                .collect()
        })
        .unwrap_or_default())
}

// ── candles ──────────────────────────────────────────────────────────────

/// At most this many requests of one fan-out in flight: twenty at once is
/// what Kraken has always taken, but Coinbase allows ten a second.
const FAN_OUT: usize = 6;

/// One request per coin of `ids` (engine market ids), in parallel; coins that
/// fail are left out. `Err` only when every coin failed, with the first error.
async fn fan_out<T, F, Fut>(src: FeedSource, ids: &[String], each: F) -> Result<Vec<T>, String>
where
    T: Send + 'static,
    F: Fn(String, &'static str) -> Fut,
    Fut: std::future::Future<Output = Result<T, String>> + Send + 'static,
{
    let gate = Arc::new(tokio::sync::Semaphore::new(FAN_OUT));
    let handles: Vec<_> = listed(src)
        .filter(|sym| ids.iter().any(|id| id.strip_prefix("crypto:") == Some(*sym)))
        .map(|sym| {
            let fut = each(venue_symbol(src, sym), sym);
            let gate = gate.clone();
            tokio::spawn(async move {
                let _permit = gate.acquire_owned().await.map_err(|e| e.to_string())?;
                fut.await
            })
        })
        .collect();
    let (mut out, mut first_err) = (Vec::new(), None);
    for h in handles {
        match h.await {
            Ok(Ok(v)) => out.push(v),
            Ok(Err(e)) => {
                first_err.get_or_insert(e);
            }
            Err(e) => {
                first_err.get_or_insert(e.to_string());
            }
        }
    }
    if out.is_empty() {
        return Err(first_err.unwrap_or_else(|| "nothing fetched".into()));
    }
    Ok(out)
}

/// The venue's name for a candle interval, or `None` when it has no such bars.
fn interval_name(src: FeedSource, minutes: u32) -> Option<String> {
    Some(match src {
        FeedSource::Kraken => minutes.to_string(),
        FeedSource::Binance | FeedSource::BinanceVision => match minutes {
            1 | 5 | 15 | 30 => format!("{minutes}m"),
            60 => "1h".into(),
            1440 => "1d".into(),
            _ => return None,
        },
        FeedSource::Coinbase => match minutes {
            1 | 5 | 15 | 60 | 360 | 1440 => (minutes * 60).to_string(),
            _ => return None,
        },
        FeedSource::Bybit => match minutes {
            1 | 5 | 15 | 30 | 60 => minutes.to_string(),
            1440 => "D".into(),
            _ => return None,
        },
        FeedSource::Okx => match minutes {
            1 | 5 | 15 | 30 => format!("{minutes}m"),
            60 => "1H".into(),
            1440 => "1Dutc".into(),
            _ => return None,
        },
        FeedSource::Alpaca => match minutes {
            1 | 5 | 15 | 30 => format!("{minutes}Min"),
            60 => "1Hour".into(),
            1440 => "1Day".into(),
            _ => return None,
        },
        FeedSource::KrakenWs => return None,
    })
}

/// Candle history for the markets `ids` from one source. Every series is
/// whole from that source, oldest first, and may end with the still-forming
/// bar (the engine keeps only closed ones).
pub async fn fetch_candles(src: FeedSource, minutes: u32, ids: &[String]) -> Result<Vec<BarSeries>, String> {
    let iv = interval_name(src, minutes).ok_or_else(|| format!("{} has no {minutes}-minute candles", src.label()))?;
    // Alpaca answers from a start time; 720 bars back, like the others' limit.
    let since = chrono::Utc::now() - chrono::Duration::minutes(i64::from(minutes) * 720);
    let since = since.format("%Y-%m-%dT%H:%M:%SZ").to_string();
    fan_out(src, ids, move |vs, sym| {
        let url = match src {
            FeedSource::Kraken => format!("https://api.kraken.com/0/public/OHLC?pair={vs}&interval={iv}"),
            FeedSource::Binance => format!("https://api.binance.com/api/v3/klines?symbol={vs}&interval={iv}&limit=720"),
            FeedSource::BinanceVision => {
                format!("https://data-api.binance.vision/api/v3/klines?symbol={vs}&interval={iv}&limit=720")
            }
            FeedSource::Coinbase => format!("https://api.exchange.coinbase.com/products/{vs}/candles?granularity={iv}"),
            FeedSource::Bybit => {
                format!("https://api.bybit.com/v5/market/kline?category=spot&symbol={vs}&interval={iv}&limit=720")
            }
            FeedSource::Okx => format!("https://www.okx.com/api/v5/market/candles?instId={vs}&bar={iv}&limit=300"),
            FeedSource::Alpaca => {
                format!("{ALPACA}/bars?symbols={}&timeframe={iv}&start={since}&limit=1000&sort=asc", alpaca_list(&[&vs]))
            }
            FeedSource::KrakenWs => String::new(),
        };
        async move {
            let v = get(&url, 8).await?;
            let bars = parse_candles(src, &v).ok_or_else(|| format!("{sym}: no candles in the reply"))?;
            Ok(BarSeries { id: format!("crypto:{sym}"), bars })
        }
    })
    .await
}

/// Parse one coin's candles from any source, oldest first.
fn parse_candles(src: FeedSource, v: &Value) -> Option<Vec<Ohlc>> {
    let bar = |ts: i64, o: Option<f64>, h: Option<f64>, l: Option<f64>, c: Option<f64>, vol: Option<f64>| {
        Some(Ohlc { ts, open: o?, high: h?, low: l?, close: c?, volume: vol.unwrap_or(0.0) })
    };
    let rows = |x: Option<&Value>| x.and_then(Value::as_array).cloned().unwrap_or_default();
    let mut bars: Vec<Ohlc> = match src {
        FeedSource::Kraken => return marketdata::parse_kraken_ohlc(v),
        // [openTime ms, o, h, l, c, v, closeTime, ...]
        FeedSource::Binance | FeedSource::BinanceVision => rows(Some(v))
            .iter()
            .filter_map(|r| {
                let r = r.as_array()?;
                bar(num(r.first())? as i64, num(r.get(1)), num(r.get(2)), num(r.get(3)), num(r.get(4)), num(r.get(5)))
            })
            .collect(),
        // [time s, low, high, open, close, volume], newest first
        FeedSource::Coinbase => rows(Some(v))
            .iter()
            .filter_map(|r| {
                let r = r.as_array()?;
                bar(num(r.first())? as i64 * 1000, num(r.get(3)), num(r.get(2)), num(r.get(1)), num(r.get(4)), num(r.get(5)))
            })
            .collect(),
        // {retCode, result: {list: [[start ms, o, h, l, c, v, turnover]]}}, newest first
        FeedSource::Bybit => {
            if v.get("retCode").and_then(Value::as_i64) != Some(0) {
                return None;
            }
            rows(v.pointer("/result/list"))
                .iter()
                .filter_map(|r| {
                    let r = r.as_array()?;
                    bar(num(r.first())? as i64, num(r.get(1)), num(r.get(2)), num(r.get(3)), num(r.get(4)), num(r.get(5)))
                })
                .collect()
        }
        // {code: "0", data: [[ts ms, o, h, l, c, vol, ..., confirm]]}, newest first
        FeedSource::Okx => {
            if v.get("code").and_then(Value::as_str) != Some("0") {
                return None;
            }
            rows(v.get("data"))
                .iter()
                .filter_map(|r| {
                    let r = r.as_array()?;
                    bar(num(r.first())? as i64, num(r.get(1)), num(r.get(2)), num(r.get(3)), num(r.get(4)), num(r.get(5)))
                })
                .collect()
        }
        // {bars: {"BTC/USD": [{t: RFC 3339, o, h, l, c, v}]}}, one coin per request
        FeedSource::Alpaca => {
            let (_, rows) = v.get("bars")?.as_object()?.iter().next()?;
            rows.as_array()?
                .iter()
                .filter_map(|b| {
                    let ts = chrono::DateTime::parse_from_rfc3339(b.get("t")?.as_str()?).ok()?.timestamp_millis();
                    bar(ts, num(b.get("o")), num(b.get("h")), num(b.get("l")), num(b.get("c")), num(b.get("v")))
                })
                .collect()
        }
        FeedSource::KrakenWs => return None,
    };
    bars.retain(|b| b.close > 0.0 && b.low > 0.0 && b.high >= b.low);
    if bars.is_empty() {
        return None;
    }
    bars.sort_by_key(|b| b.ts);
    bars.dedup_by_key(|b| b.ts);
    Some(bars)
}

// ── books ────────────────────────────────────────────────────────────────

/// Top-20 books for the markets `ids` from one source, one request per coin.
pub async fn fetch_books(src: FeedSource, ids: &[String]) -> Result<Vec<BookSnapshot>, String> {
    if src == FeedSource::Alpaca {
        // One request answers for every coin.
        let syms: Vec<&str> =
            listed(src).filter(|sym| ids.iter().any(|id| id.strip_prefix("crypto:") == Some(*sym))).collect();
        if syms.is_empty() {
            return Err("Alpaca lists none of the coins asked about".into());
        }
        let v = get(&format!("{ALPACA}/latest/orderbooks?symbols={}", alpaca_list(&syms)), 8).await?;
        return nonempty(parse_alpaca_books(&v, chrono::Utc::now().timestamp_millis()), "books");
    }
    let host = match src {
        FeedSource::Kraken => "api.kraken.com",
        FeedSource::Binance => "api.binance.com",
        FeedSource::BinanceVision => "data-api.binance.vision",
        _ => return Err(format!("{} books are not used for costs", src.label())),
    };
    fan_out(src, ids, move |vs, sym| {
        let url = match src {
            FeedSource::Kraken => format!("https://{host}/0/public/Depth?pair={vs}&count={BOOK_LEVELS}"),
            _ => format!("https://{host}/api/v3/depth?symbol={vs}&limit={BOOK_LEVELS}"),
        };
        async move {
            let v = get(&url, 6).await?;
            let now = chrono::Utc::now().timestamp_millis();
            let quote = parse_book(src, &v, now).ok_or_else(|| format!("{sym}: no usable book"))?;
            Ok(BookSnapshot { id: format!("crypto:{sym}"), quote })
        }
    })
    .await
}

/// `{orderbooks: {"BTC/USD": {a: [{p, s}], b: [{p, s}], t}}}`, full depth:
/// the best `BOOK_LEVELS` of each side are kept.
fn parse_alpaca_books(v: &Value, now: i64) -> Vec<BookSnapshot> {
    let side = |x: Option<&Value>, bids: bool| -> Vec<(f64, f64)> {
        let mut lv: Vec<(f64, f64)> = x
            .and_then(Value::as_array)
            .map(|rows| rows.iter().filter_map(|r| Some((num(r.get("p"))?, num(r.get("s"))?))).collect())
            .unwrap_or_default();
        lv.sort_by(|a, b| if bids { b.0.total_cmp(&a.0) } else { a.0.total_cmp(&b.0) });
        lv.truncate(BOOK_LEVELS);
        lv
    };
    let Some(map) = v.get("orderbooks").and_then(Value::as_object) else { return vec![] };
    map.iter()
        .filter_map(|(vs, b)| {
            let sym = our_symbol(FeedSource::Alpaca, vs)?;
            let quote = BookQuote::from_levels(CostVenue::Alpaca, &side(b.get("b"), true), &side(b.get("a"), false), now)?;
            Some(BookSnapshot { id: format!("crypto:{sym}"), quote })
        })
        .collect()
}

fn parse_book(src: FeedSource, v: &Value, now: i64) -> Option<BookQuote> {
    match src {
        FeedSource::Kraken => marketdata::parse_kraken_depth(v, now),
        // The mirror is Binance's own book: same venue, same costs.
        FeedSource::Binance | FeedSource::BinanceVision => {
            marketdata::parse_binance_depth(v, now).filter(|q| q.venue == CostVenue::Binance)
        }
        _ => None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn j(s: &str) -> Value {
        serde_json::from_str(s).unwrap()
    }

    #[test]
    fn every_source_names_every_coin() {
        assert_eq!(venue_symbol(FeedSource::Kraken, "BTC/USD"), "XBTUSD");
        assert_eq!(venue_symbol(FeedSource::Kraken, "DOGE/USD"), "XDGUSD");
        assert_eq!(venue_symbol(FeedSource::Binance, "PEPE/USD"), "PEPEUSDT");
        assert_eq!(venue_symbol(FeedSource::Coinbase, "BTC/USD"), "BTC-USD");
        assert_eq!(venue_symbol(FeedSource::Bybit, "SUI/USD"), "SUIUSDT");
        assert_eq!(venue_symbol(FeedSource::Okx, "ETH/USD"), "ETH-USDT");
        assert_eq!(venue_symbol(FeedSource::KrakenWs, "DOGE/USD"), "DOGE/USD");
        for src in FeedSource::ALL {
            for sym in universe() {
                if src != FeedSource::Kraken && src != FeedSource::KrakenWs {
                    assert_eq!(our_symbol(src, &venue_symbol(src, sym)), Some(sym), "{src:?} {sym}");
                }
            }
        }
        assert_eq!(venue_symbol(FeedSource::Alpaca, "BONK/USD"), "BONK/USD");
        assert_eq!(venue_symbol(FeedSource::Kraken, "WIF/USD"), "WIFUSD");
        assert_eq!(universe_ids().len(), crate::coins::configured().len());
        assert!(listed(FeedSource::Kraken).all(|s| s != "HYPE/USD"));
        assert!(listed(FeedSource::Alpaca).all(|s| s != "TRX/USD"));
    }

    #[test]
    fn parses_binance_tickers() {
        let v = j(r#"[{"symbol":"BTCUSDT","openPrice":"85615.67","lastPrice":"83436.74"},
                      {"symbol":"PEPEUSDT","openPrice":"0.00000426","lastPrice":"0.00000406"},
                      {"symbol":"FOOUSDT","openPrice":"1","lastPrice":"2"}]"#);
        let rows = parse_binance_tickers(&v, FeedSource::Binance);
        assert_eq!(rows.len(), 2, "a coin outside the universe is ignored");
        assert_eq!(rows[0].id, "crypto:BTC/USD");
        assert_eq!(rows[0].price, 83_436.74);
        assert!((rows[0].change24h - (83_436.74 - 85_615.67) / 85_615.67).abs() < 1e-12);
        assert_eq!(rows[1].symbol, "PEPE/USD");
    }

    #[test]
    fn parses_coinbase_products_with_percent_change() {
        let v = j(r#"{"products":[{"product_id":"BTC-USD","price":"83397.4","price_percentage_change_24h":"-2.6"},
                                 {"product_id":"PEPE-USD","price":"0.00000406","price_percentage_change_24h":"-4.9"}]}"#);
        let rows = parse_coinbase_products(&v);
        assert_eq!(rows.len(), 2);
        assert!((rows[0].change24h + 0.026).abs() < 1e-12);
        assert!(parse_coinbase_products(&j(r#"{"error":"x"}"#)).is_empty());
    }

    #[test]
    fn parses_bybit_and_okx_tickers_and_their_errors() {
        let v = j(r#"{"retCode":0,"retMsg":"OK","result":{"category":"spot","list":[
            {"symbol":"BTCUSDT","lastPrice":"83438.1","price24hPcnt":"-0.0254"},
            {"symbol":"BTCUSDC","lastPrice":"83440","price24hPcnt":"-0.02"}]}}"#);
        let rows = parse_bybit_tickers(&v).unwrap();
        assert_eq!(rows.len(), 1);
        assert_eq!(rows[0].change24h, -0.0254);
        assert!(parse_bybit_tickers(&j(r#"{"retCode":10001,"retMsg":"params error"}"#)).unwrap_err().contains("params"));

        let v = j(r#"{"code":"0","data":[{"instId":"BTC-USDT","last":"83445","open24h":"85635.3"}],"msg":""}"#);
        let rows = parse_okx_tickers(&v).unwrap();
        assert_eq!(rows[0].id, "crypto:BTC/USD");
        assert!(rows[0].change24h < 0.0);
        assert!(parse_okx_tickers(&j(r#"{"code":"50011","msg":"rate limit","data":[]}"#)).is_err());
    }

    #[test]
    fn candles_from_every_source_come_out_oldest_first_in_millis() {
        let binance = j(r#"[[1791402900000,"83370.92","83440.01","83370.92","83434.68","56.3",1791403199999],
                            [1791403200000,"83434.67","83436.75","83434.67","83436.00","0.44",1791403499999]]"#);
        let coinbase = j(r#"[[1791402900,83322.46,83400.3,83330.03,83384.93,8.16],
                             [1791402600,83270.54,83360.44,83285.91,83328.92,32.1]]"#);
        let bybit = j(r#"{"retCode":0,"result":{"list":[["1791403200000","83434.7","83438.2","83428.4","83431.5","2.05","1"],
                                                       ["1791402900000","83370.8","83438.3","83370.8","83434.7","46.7","1"]]}}"#);
        let okx = j(r#"{"code":"0","data":[["1791403200000","83440.1","83448","83439.2","83439.3","0.43","1","1","0"],
                                           ["1791402900000","83374.8","83449.9","83374.8","83440.1","17.9","1","1","1"]]}"#);
        for (src, v) in [
            (FeedSource::Binance, &binance),
            (FeedSource::Coinbase, &coinbase),
            (FeedSource::Bybit, &bybit),
            (FeedSource::Okx, &okx),
        ] {
            let bars = parse_candles(src, v).unwrap_or_else(|| panic!("{src:?}"));
            assert_eq!(bars.len(), 2, "{src:?}");
            assert!(bars[0].ts < bars[1].ts, "{src:?} oldest first");
            assert!(bars[0].ts > 1_700_000_000_000, "{src:?} in millis");
            assert!(bars.iter().all(|b| b.high >= b.low && b.low > 0.0), "{src:?}");
        }
        // Coinbase's order is [time, low, high, open, close]: low and high are not swapped.
        let cb = parse_candles(FeedSource::Coinbase, &coinbase).unwrap();
        assert_eq!((cb[1].low, cb[1].high, cb[1].open, cb[1].close), (83_322.46, 83_400.3, 83_330.03, 83_384.93));
        assert!(parse_candles(FeedSource::Okx, &j(r#"{"code":"51001","data":[]}"#)).is_none());
    }

    #[test]
    fn intervals_a_venue_lacks_are_an_error_not_a_wrong_series() {
        assert_eq!(interval_name(FeedSource::Binance, 5).as_deref(), Some("5m"));
        assert_eq!(interval_name(FeedSource::Coinbase, 5).as_deref(), Some("300"));
        assert_eq!(interval_name(FeedSource::Coinbase, 30), None);
        assert_eq!(interval_name(FeedSource::Bybit, 1440).as_deref(), Some("D"));
        assert_eq!(interval_name(FeedSource::Okx, 60).as_deref(), Some("1H"));
        assert_eq!(interval_name(FeedSource::KrakenWs, 5), None);
    }

    #[test]
    fn the_binance_mirror_book_is_a_binance_book() {
        let v = j(r#"{"lastUpdateId":1,"bids":[["100.0","1"]],"asks":[["100.1","1"]]}"#);
        let q = parse_book(FeedSource::BinanceVision, &v, 7).unwrap();
        assert_eq!(q.venue, CostVenue::Binance);
        assert!(parse_book(FeedSource::Okx, &v, 7).is_none());
    }

    #[test]
    fn parses_alpaca_snapshots_with_the_quote_mid_as_the_mark() {
        let v = j(r#"{"snapshots":{
            "BTC/USD":{"latestTrade":{"p":83400.0},"latestQuote":{"bp":83390.0,"ap":83410.0},
                       "dailyBar":{"o":82000.0,"c":83400.0},"prevDailyBar":{"c":82000.0}},
            "BONK/USD":{"latestTrade":{"p":0.0000150},"latestQuote":{"bp":0.0,"ap":0.0000151},
                        "dailyBar":{"o":0.0000160,"c":0.0000150}},
            "WIF/USD":{"latestTrade":{"p":0.8},"latestQuote":{"bp":0.5,"ap":0.9}},
            "USDT/USD":{"latestTrade":{"p":1.0}},
            "SKY/USD":{"latestQuote":{"bp":0,"ap":0}}}}"#);
        let mut rows = parse_alpaca_snapshots(&v);
        rows.sort_by(|a, b| a.symbol.cmp(&b.symbol));
        let syms: Vec<&str> = rows.iter().map(|r| r.symbol.as_str()).collect();
        assert_eq!(syms, ["BONK/USD", "BTC/USD", "WIF/USD"], "a peg and a coin without a price are left out");
        assert_eq!(rows[1].price, 83_400.0, "the mid");
        assert!((rows[1].change24h - 1_400.0 / 82_000.0).abs() < 1e-12);
        assert_eq!(rows[0].price, 0.0000150, "a one-sided quote falls back to the last trade");
        assert!(rows[0].change24h < 0.0, "against the day's open without a previous close");
        assert_eq!(rows[2].price, 0.8, "a 44 % wide quote is no mark");
        assert!(parse_alpaca_snapshots(&j(r#"{"message":"rate limit"}"#)).is_empty());
    }

    #[test]
    fn parses_alpaca_candles_and_books() {
        let v = j(r#"{"bars":{"PEPE/USD":[
            {"t":"2026-10-15T10:05:00Z","o":0.0000043,"h":0.0000044,"l":0.0000042,"c":0.0000043,"v":1.2e9},
            {"t":"2026-10-15T10:00:00Z","o":0.0000042,"h":0.0000043,"l":0.0000042,"c":0.0000043,"v":9e8}]},
            "next_page_token":null}"#);
        let bars = parse_candles(FeedSource::Alpaca, &v).unwrap();
        assert_eq!(bars.len(), 2);
        assert!(bars[0].ts < bars[1].ts && bars[0].ts > 1_700_000_000_000);
        assert!(parse_candles(FeedSource::Alpaca, &j(r#"{"bars":{}}"#)).is_none());

        let v = j(r#"{"orderbooks":{"ETH/USD":{
            "a":[{"p":2567.0,"s":2.0},{"p":2566.5,"s":1.0}],
            "b":[{"p":2565.0,"s":1.0},{"p":2566.0,"s":3.0}],"t":"2026-10-15T10:00:00Z"},
            "XYZ/USD":{"a":[{"p":1,"s":1}],"b":[{"p":0.9,"s":1}]}}}"#);
        let books = parse_alpaca_books(&v, 7);
        assert_eq!(books.len(), 1, "a coin outside the universe is ignored");
        let q = &books[0].quote;
        assert_eq!(books[0].id, "crypto:ETH/USD");
        assert_eq!(q.venue, CostVenue::Alpaca);
        assert_eq!(q.mid, 2566.25, "sides sorted best first");
        assert!(parse_alpaca_books(&j(r#"{"code":429}"#), 7).is_empty());
        assert_eq!(interval_name(FeedSource::Alpaca, 5).as_deref(), Some("5Min"));
        assert_eq!(interval_name(FeedSource::Alpaca, 60).as_deref(), Some("1Hour"));
        assert_eq!(alpaca_list(&["BTC/USD", "BONK/USD"]), "BTC%2FUSD,BONK%2FUSD");
    }

    /// Run by hand (`cargo test -p pythia-core live_rest -- --ignored`) to
    /// check every venue still answers in the shape parsed here.
    #[tokio::test]
    #[ignore]
    async fn live_rest_every_source_answers() {
        let all = universe_ids();
        for src in [FeedSource::Kraken, FeedSource::Alpaca, FeedSource::Binance, FeedSource::Coinbase, FeedSource::Bybit, FeedSource::Okx] {
            let q = fetch_quotes(src).await.unwrap_or_else(|e| panic!("{src:?} quotes: {e}"));
            let c = fetch_candles(src, 5, &all).await.unwrap_or_else(|e| panic!("{src:?} candles: {e}"));
            println!("{src:?}: {} quotes, {} series, {} bars in the first", q.len(), c.len(), c[0].bars.len());
        }
        for src in [FeedSource::Kraken, FeedSource::Binance, FeedSource::BinanceVision, FeedSource::Alpaca] {
            let b = fetch_books(src, &all).await.unwrap_or_else(|e| panic!("{src:?} books: {e}"));
            println!("{src:?}: {} books", b.len());
        }
        // Only the coins asked about.
        let two = fetch_candles(FeedSource::Binance, 5, &all[..2]).await.unwrap();
        assert_eq!(two.len(), 2);
    }
}
