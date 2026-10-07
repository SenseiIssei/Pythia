//! The push side of the quote feed: Kraken's public websocket ticker (v2).
//!
//! One connection carries the last trade price of all twenty coins plus a
//! heartbeat every second, which replaces a ticker poll every twelve seconds
//! with prices that are at most a second old. Nothing here touches the
//! engine: the stream writes into a small shared snapshot and the drain loop
//! in [`super::runner`] hands it over once per tick, so a burst of trades
//! never takes the engine lock more than once.
//!
//! Reconnects back off exponentially, but only while sessions keep dying
//! young: a session that lived a minute was healthy, so the next attempt
//! starts after one second again. The recorder learned this the hard way
//! (`research/recorder/recorder/net.py`): without the reset, every routine
//! disconnect after an early flap cost a full minute of data.

use std::collections::HashMap;
use std::sync::Mutex;
use std::time::{Duration, Instant};

use futures_util::{SinkExt, StreamExt};
use serde_json::Value;
use tokio_tungstenite::tungstenite::Message;

use super::{FeedSource, StreamStatus};

pub const KRAKEN_WS: &str = "wss://ws.kraken.com/v2";
/// A session that lived this long was healthy: the backoff starts over.
pub const HEALTHY_SESSION: Duration = Duration::from_secs(60);
/// Kraken beats every second; this much silence is a dead socket.
const READ_TIMEOUT: Duration = Duration::from_secs(15);
const MAX_BACKOFF: Duration = Duration::from_secs(60);

/// Latest price per symbol plus the connection state, shared between the
/// stream task and the drain loop.
#[derive(Debug, Default)]
pub struct Shared {
    inner: Mutex<Snapshot>,
}

#[derive(Debug, Clone, Default)]
pub struct Snapshot {
    pub status: StreamStatus,
    /// Our symbol to (last price, 24 h change as a fraction).
    pub quotes: HashMap<String, (f64, f64)>,
}

impl Shared {
    pub fn snapshot(&self) -> Snapshot {
        self.inner.lock().map(|s| s.clone()).unwrap_or_default()
    }

    fn with(&self, f: impl FnOnce(&mut Snapshot)) {
        if let Ok(mut s) = self.inner.lock() {
            f(&mut s);
        }
    }
}

/// What one frame from Kraken means to us.
#[derive(Debug, PartialEq)]
pub enum Frame {
    Heartbeat,
    /// (symbol, last, 24 h change as a fraction).
    Ticker(Vec<(String, f64, f64)>),
    /// A refused subscription or a venue-side error.
    Error(String),
    Other,
}

/// Parse one text frame. Ticker frames look like
/// `{"channel":"ticker","type":"snapshot"|"update","data":[{"symbol":"BTC/USD","last":83436.7,"change_pct":-2.5,...}]}`.
pub fn parse_frame(text: &str) -> Frame {
    let Ok(v) = serde_json::from_str::<Value>(text) else { return Frame::Other };
    if v.get("success").and_then(Value::as_bool) == Some(false) {
        return Frame::Error(v.get("error").and_then(Value::as_str).unwrap_or("subscription refused").to_string());
    }
    match v.get("channel").and_then(Value::as_str) {
        Some("heartbeat") => Frame::Heartbeat,
        Some("ticker") => {
            let rows = v
                .get("data")
                .and_then(Value::as_array)
                .map(|rows| {
                    rows.iter()
                        .filter_map(|r| {
                            let sym = r.get("symbol")?.as_str()?.to_string();
                            let last = r.get("last")?.as_f64().filter(|p| p.is_finite())?;
                            let pct = r.get("change_pct").and_then(Value::as_f64).unwrap_or(0.0);
                            Some((sym, last, pct / 100.0))
                        })
                        .collect()
                })
                .unwrap_or_default();
            Frame::Ticker(rows)
        }
        _ => Frame::Other,
    }
}

fn now_ms() -> i64 {
    chrono::Utc::now().timestamp_millis()
}

/// The next wait after a session that lasted `lived`, given the last wait.
pub fn next_backoff(prev: Duration, lived: Duration) -> (Duration, Duration) {
    let wait = if lived >= HEALTHY_SESSION { Duration::from_secs(1) } else { prev };
    (wait, (wait * 2).min(MAX_BACKOFF))
}

/// Run the Kraken ticker stream forever for `symbols` (ours, `BTC/USD`).
pub async fn run_kraken(shared: std::sync::Arc<Shared>, symbols: Vec<String>) {
    shared.with(|s| {
        s.status.enabled = true;
        s.status.source = Some(FeedSource::KrakenWs);
    });
    let mut backoff = Duration::from_secs(1);
    loop {
        let started = Instant::now();
        let err = session(&shared, &symbols).await.err().unwrap_or_else(|| "closed".into());
        tracing::warn!("Kraken stream ended after {} s: {err}", started.elapsed().as_secs());
        shared.with(|s| {
            s.status.connected = false;
            s.status.since = None;
            s.status.reconnects += 1;
            s.status.last_error = Some(err);
            // A price from a dead session must not look current.
            s.quotes.clear();
        });
        let (wait, next) = next_backoff(backoff, started.elapsed());
        tokio::time::sleep(wait).await;
        backoff = next;
    }
}

async fn session(shared: &Shared, symbols: &[String]) -> Result<(), String> {
    let (mut ws, _) = tokio::time::timeout(Duration::from_secs(10), tokio_tungstenite::connect_async(KRAKEN_WS))
        .await
        .map_err(|_| "connect timed out".to_string())?
        .map_err(|e| format!("connect: {e}"))?;
    let sub = serde_json::json!({
        "method": "subscribe",
        "params": { "channel": "ticker", "symbol": symbols },
    });
    ws.send(Message::Text(sub.to_string())).await.map_err(|e| format!("subscribe: {e}"))?;
    let t = now_ms();
    shared.with(|s| {
        s.status.connected = true;
        s.status.since = Some(t);
        s.status.last_message = Some(t);
    });
    loop {
        let msg = tokio::time::timeout(READ_TIMEOUT, ws.next())
            .await
            .map_err(|_| format!("no message for {} s", READ_TIMEOUT.as_secs()))?;
        let msg = match msg {
            None => return Err("closed by the server".into()),
            Some(Err(e)) => return Err(e.to_string()),
            Some(Ok(m)) => m,
        };
        match msg {
            Message::Text(text) => {
                let frame = parse_frame(&text);
                let t = now_ms();
                shared.with(|s| {
                    s.status.last_message = Some(t);
                    match frame {
                        Frame::Ticker(rows) => {
                            for (sym, last, change) in rows {
                                s.quotes.insert(sym, (last, change));
                            }
                        }
                        Frame::Error(e) => s.status.last_error = Some(e),
                        Frame::Heartbeat | Frame::Other => {}
                    }
                });
            }
            Message::Ping(p) => ws.send(Message::Pong(p)).await.map_err(|e| e.to_string())?,
            Message::Close(_) => return Err("closed by the server".into()),
            _ => {}
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_ticker_heartbeat_and_refusals() {
        let t = r#"{"channel":"ticker","type":"update","data":[
            {"symbol":"BTC/USD","bid":83436.6,"bid_qty":0.5,"ask":83436.7,"ask_qty":1.2,"last":83436.7,
             "volume":1200.5,"vwap":84000.1,"low":82700.0,"high":85600.0,"change":-2179.0,"change_pct":-2.55},
            {"symbol":"DOGE/USD","last":0.1721,"change_pct":1.0}]}"#;
        match parse_frame(t) {
            Frame::Ticker(rows) => {
                assert_eq!(rows.len(), 2);
                assert_eq!(rows[0].0, "BTC/USD");
                assert_eq!(rows[0].1, 83_436.7);
                assert!((rows[0].2 + 0.0255).abs() < 1e-12, "percent becomes a fraction");
                assert_eq!(rows[1].0, "DOGE/USD", "v2 names DOGE as we do, not XDG");
            }
            other => panic!("{other:?}"),
        }
        assert_eq!(parse_frame(r#"{"channel":"heartbeat"}"#), Frame::Heartbeat);
        assert_eq!(
            parse_frame(r#"{"method":"subscribe","error":"Currency pair not supported FOO/USD","success":false}"#),
            Frame::Error("Currency pair not supported FOO/USD".into())
        );
        assert_eq!(parse_frame(r#"{"channel":"status","data":[{"system":"online"}]}"#), Frame::Other);
        assert_eq!(parse_frame("not json"), Frame::Other);
    }

    #[test]
    fn backoff_doubles_while_sessions_die_young_and_resets_after_a_healthy_one() {
        let s = Duration::from_secs;
        let (w, next) = next_backoff(s(1), s(0));
        assert_eq!((w, next), (s(1), s(2)));
        let (w, next) = next_backoff(next, s(3));
        assert_eq!((w, next), (s(2), s(4)));
        let (w, next) = next_backoff(s(32), s(5));
        assert_eq!((w, next), (s(32), s(60)), "capped at a minute");
        // An hour-long session ended: back to one second, not 60.
        let (w, next) = next_backoff(next, s(3600));
        assert_eq!((w, next), (s(1), s(2)));
    }

    /// By hand: `cargo test -p pythia-core live_stream -- --ignored --nocapture`.
    #[tokio::test]
    #[ignore]
    async fn live_stream_delivers_prices() {
        let shared = std::sync::Arc::new(Shared::default());
        let syms: Vec<String> = super::super::sources::universe().map(String::from).collect();
        let task = tokio::spawn(run_kraken(shared.clone(), syms));
        tokio::time::sleep(Duration::from_secs(8)).await;
        let snap = shared.snapshot();
        task.abort();
        println!("{:?} {} prices: {:?}", snap.status, snap.quotes.len(), snap.quotes.get("BTC/USD"));
        assert!(snap.status.connected, "{:?}", snap.status);
        assert!(snap.quotes.len() >= 15, "{} prices", snap.quotes.len());
    }
}
