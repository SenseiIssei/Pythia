//! The feed loops both hosts run: the server's `tick_loop` and the desktop
//! daemon spawn [`run`] once and stop polling crypto data themselves.
//!
//! Each kind gets its own task, so a slow candle fan-out never delays a quote
//! and none of them delays the engine tick (the tick loop used to await every
//! feed in line). The engine lock is only taken for the synchronous apply,
//! never across a request.
//!
//! Footprint with everything healthy: one websocket, one Binance reference
//! request a minute, twenty candle requests a minute and twenty book requests
//! every thirty seconds, the same as before minus the ticker poll every
//! twelve seconds. Fallback sources are only asked while a market needs them.

use std::sync::{Arc, Mutex};
use std::time::Duration;

use tokio::time::MissedTickBehavior;

use super::{sources, ws, DataKind, FeedConfig, FeedSource};
use crate::engine::Engine;

/// How often each loop wakes to check whether something is due.
const WAKE: Duration = Duration::from_millis(1500);
/// A failover round never runs more often than this.
const MIN_ROUND_GAP_MS: i64 = 3_000;

fn now_ms() -> i64 {
    chrono::Utc::now().timestamp_millis()
}

/// Run every crypto feed for `engine` forever. `bar_minutes` is read before
/// each candle round, so a changed timeframe takes effect without a restart.
pub async fn run(engine: Arc<Mutex<Engine>>, cfg: FeedConfig, bar_minutes: Arc<dyn Fn() -> u32 + Send + Sync>) {
    engine.lock().unwrap().start_feeds(cfg.clone());
    tracing::info!(
        "market data: quotes {}, candles {}, stream {}",
        cfg.quotes.iter().map(|s| s.id()).collect::<Vec<_>>().join(" > "),
        cfg.candles.iter().map(|s| s.id()).collect::<Vec<_>>().join(" > "),
        if cfg.stream { "on" } else { "off" }
    );
    let mut tasks = Vec::new();
    if cfg.stream && cfg.quotes.contains(&FeedSource::KrakenWs) {
        let shared = Arc::new(ws::Shared::default());
        let symbols = sources::universe().map(String::from).collect();
        tasks.push(tokio::spawn(ws::run_kraken(shared.clone(), symbols)));
        tasks.push(tokio::spawn(drain_loop(engine.clone(), shared)));
    }
    tasks.push(tokio::spawn(poll_loop(engine.clone(), DataKind::Quotes, cfg.quotes_every_ms, None)));
    tasks.push(tokio::spawn(poll_loop(engine.clone(), DataKind::Candles, cfg.candles_every_ms, Some(bar_minutes))));
    tasks.push(tokio::spawn(poll_loop(engine, DataKind::Books, cfg.books_every_ms, None)));
    for t in tasks {
        let _ = t.await;
    }
}

/// Hand the stream's latest prices to the engine once per wake.
async fn drain_loop(engine: Arc<Mutex<Engine>>, shared: Arc<ws::Shared>) {
    let mut iv = tokio::time::interval(WAKE);
    iv.set_missed_tick_behavior(MissedTickBehavior::Delay);
    loop {
        iv.tick().await;
        let snap = shared.snapshot();
        engine.lock().unwrap().apply_stream(snap);
    }
}

/// One kind's polling: a regular round every `every_ms`, an early one when a
/// market's source has gone stale, and for quotes the reference polls of the
/// sanity check. A round walks the priority list and asks each source only
/// if the engine says some market needs it.
async fn poll_loop(
    engine: Arc<Mutex<Engine>>,
    kind: DataKind,
    every_ms: i64,
    bar_minutes: Option<Arc<dyn Fn() -> u32 + Send + Sync>>,
) {
    let mut iv = tokio::time::interval(WAKE);
    iv.set_missed_tick_behavior(MissedTickBehavior::Delay);
    let mut last_round = i64::MIN / 2;
    // Early rounds start a quarter of the cadence apart and back off while
    // they do not help (every venue down, or a coin none of them serves), up
    // to the regular cadence, so an outage never turns into a request storm.
    let base_gap = (every_ms / 4).max(MIN_ROUND_GAP_MS);
    let mut early_gap = base_gap;
    loop {
        iv.tick().await;
        let now = now_ms();
        let failing = { engine.lock().unwrap().feed_needs_failover(kind) };
        if !failing {
            early_gap = base_gap;
        }
        let regular = now - last_round >= every_ms;
        let early = failing && now - last_round >= early_gap;
        if regular || early {
            if early && !regular {
                early_gap = (early_gap * 2).min(every_ms);
            }
            last_round = now;
            let minutes = bar_minutes.as_ref().map(|f| f()).unwrap_or(5);
            let order = { engine.lock().unwrap().feed_priority(kind) };
            for src in order.into_iter().filter(|s| !s.is_push()) {
                // Asked in turn, best first: once a source covers a market,
                // the ones below it are not asked about that market.
                let wanted = { engine.lock().unwrap().feed_wanted(kind, src) };
                if wanted.is_empty() {
                    continue;
                }
                poll_once(&engine, kind, src, minutes, &wanted).await;
            }
        }
        if kind == DataKind::Quotes {
            let reference = { engine.lock().unwrap().take_feed_reference() };
            if let Some(src) = reference {
                poll_once(&engine, kind, src, 0, &[]).await;
            }
        }
    }
}

async fn poll_once(engine: &Mutex<Engine>, kind: DataKind, src: FeedSource, minutes: u32, ids: &[String]) {
    match kind {
        // One request answers for every coin, so quotes are always asked whole.
        DataKind::Quotes => {
            let res = sources::fetch_quotes(src).await;
            engine.lock().unwrap().apply_feed_quotes(src, res, now_ms());
        }
        DataKind::Candles => {
            let res = sources::fetch_candles(src, minutes, ids).await;
            engine.lock().unwrap().apply_feed_candles(src, res, minutes);
        }
        DataKind::Books => {
            let res = sources::fetch_books(src, ids).await;
            engine.lock().unwrap().apply_feed_books(src, res);
        }
    }
}
