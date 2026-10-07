//! The feed layer as the engine lives it: what reaches the mark, what a stop
//! may act on, how a candle source switch is installed, and what the health
//! report and the webhook say. The source-choice rules themselves are tested
//! with a fake clock in `crate::feeds`.

use super::*;
use crate::feeds::{ws, DataKind, FeedConfig, FeedSource, StreamStatus};

const BTC: &str = "crypto:BTC/USD";

fn quote(id: &str, price: f64) -> RealCrypto {
    let symbol = id.trim_start_matches("crypto:").to_string();
    RealCrypto { id: id.into(), symbol, price, change24h: 0.0 }
}

/// An engine whose host runs the feeds, polled only (no stream).
fn fed() -> Engine {
    let mut e = Engine::new();
    e.start_feeds(FeedConfig { stream: false, ..FeedConfig::default() });
    e
}

fn long_btc(e: &mut Engine, stop: f64) {
    e.positions.insert(
        BTC.into(),
        PositionInternal {
            venue: Venue::Crypto,
            symbol: "BTC/USD".into(),
            qty: 0.1,
            avg_price: 80_000.0,
            strategy_id: "ema-cross-1".into(),
            stop,
            target: 0.0,
            trail_ref: 80_000.0,
            live: false,
        },
    );
}

fn journal_count(e: &Engine, needle: &str) -> usize {
    e.journal.iter().filter(|j| j.message.contains(needle)).count()
}

/// Forty closed 5-minute bars ending just before now, at `level`.
fn series(id: &str, level: f64) -> BarSeries {
    let iv = 300_000;
    let now = chrono::Utc::now().timestamp_millis();
    let last_open = now / iv * iv - iv;
    let bars = (0..40)
        .rev()
        .map(|k| {
            let c = level * (1.0 + k as f64 * 1e-4);
            Ohlc { ts: last_open - k * iv, open: c, high: c * 1.001, low: c * 0.999, close: c, volume: 1.0 }
        })
        .collect();
    BarSeries { id: id.into(), bars }
}

#[test]
fn a_refused_quote_never_becomes_the_mark_and_is_journaled_once() {
    let mut e = fed();
    let now = e.now();
    e.apply_feed_quotes(FeedSource::Kraken, Ok(vec![quote(BTC, 80_000.0)]), now);
    // Binance answers as the reference: accepted, but BTC stays on Kraken.
    e.apply_feed_quotes(FeedSource::Binance, Ok(vec![quote(BTC, 80_050.0)]), now);
    assert_eq!(e.price_of(BTC), 80_000.0);
    assert_eq!(e.feeds.current(DataKind::Quotes, BTC), Some(FeedSource::Kraken));

    // Kraken prints a fat finger, twice.
    e.apply_feed_quotes(FeedSource::Kraken, Ok(vec![quote(BTC, 104_000.0)]), now + 1);
    e.apply_feed_quotes(FeedSource::Kraken, Ok(vec![quote(BTC, 104_100.0)]), now + 2);
    assert_eq!(e.price_of(BTC), 80_000.0, "the bad tick is not the mark");
    assert_eq!(journal_count(&e, "quote refused"), 1, "said once per episode");
    let h = e.data_health();
    assert!(h.markets.iter().find(|m| m.market == BTC).unwrap().suspect.is_some());
    assert!(!h.rejections.is_empty());

    // A sane print clears it; the next bad one is a new episode.
    e.apply_feed_quotes(FeedSource::Kraken, Ok(vec![quote(BTC, 80_100.0)]), now + 3);
    assert_eq!(e.price_of(BTC), 80_100.0);
    e.apply_feed_quotes(FeedSource::Kraken, Ok(vec![quote(BTC, 40_000.0)]), now + 4);
    assert_eq!(journal_count(&e, "quote refused"), 2);
}

#[test]
fn a_bad_tick_does_not_trigger_a_stop() {
    let mut e = fed();
    let now = e.now();
    e.apply_feed_quotes(FeedSource::Kraken, Ok(vec![quote(BTC, 80_000.0)]), now);
    e.apply_feed_quotes(FeedSource::Binance, Ok(vec![quote(BTC, 80_020.0)]), now);
    long_btc(&mut e, 76_000.0);
    // A flash print far under the stop, which no other venue saw.
    e.apply_feed_quotes(FeedSource::Kraken, Ok(vec![quote(BTC, 50_000.0)]), now + 1);
    e.check_position_exits();
    assert!(e.positions.contains_key(BTC), "stopped out on a price that never was");

    // A real move through the stop, seen by both venues, does stop it.
    e.apply_feed_quotes(FeedSource::Binance, Ok(vec![quote(BTC, 75_000.0)]), now + 2);
    e.apply_feed_quotes(FeedSource::Kraken, Ok(vec![quote(BTC, 74_950.0)]), now + 3);
    e.check_position_exits();
    assert!(!e.positions.contains_key(BTC));
}

#[test]
fn a_stale_price_holds_stops_and_trims_until_a_fresh_one_arrives() {
    let mut e = fed();
    let now = e.now();
    e.apply_feed_quotes(FeedSource::Kraken, Ok(vec![quote(BTC, 70_000.0)]), now);
    // The feed then went quiet for a minute, with the price under the stop.
    e.markets.iter_mut().find(|m| m.id == BTC).unwrap().updated_at = now - 60_000;
    long_btc(&mut e, 76_000.0);
    e.check_position_exits();
    e.check_position_exits();
    assert!(e.positions.contains_key(BTC), "a stale price must not stop out");
    assert_eq!(journal_count(&e, "Stop check on crypto:BTC/USD held"), 1, "journaled once");
    e.trim_position(BTC, 0.5, "volatility spike trim");
    assert!((e.positions[BTC].qty - 0.1).abs() < 1e-12, "nor trim");

    // A fresh price at the same level: the stop acts, and the hold is over.
    let later = e.now();
    e.apply_feed_quotes(FeedSource::Kraken, Ok(vec![quote(BTC, 70_000.0)]), later);
    e.check_position_exits();
    assert!(!e.positions.contains_key(BTC));
}

#[test]
fn the_simulator_and_markets_without_a_feed_are_not_held() {
    // A seeded, never-fed market is the simulator's, which is always current.
    let mut e = Engine::new();
    long_btc(&mut e, 76_000.0);
    e.check_position_exits();
    assert!(!e.positions.contains_key(BTC), "the seed price is under the stop");
}

#[test]
fn a_candle_source_switch_installs_the_new_series_whole_and_takes_no_entry_on_it() {
    let mut e = fed();
    e.apply_feed_candles(FeedSource::Kraken, Ok(vec![series(BTC, 80_000.0)]), 5);
    assert_eq!(e.feeds.current(DataKind::Candles, BTC), Some(FeedSource::Kraken));
    assert!(e.is_bar_backed(BTC));

    e.apply_feed_candles(FeedSource::Kraken, Err("HTTP 520".into()), 5);
    e.apply_feed_candles(FeedSource::Kraken, Err("HTTP 520".into()), 5);
    e.apply_feed_candles(FeedSource::Binance, Ok(vec![series(BTC, 81_000.0)]), 5);
    assert_eq!(e.feeds.current(DataKind::Candles, BTC), Some(FeedSource::Binance));

    // Every bar is Binance's: nothing of the Kraken series is left in it.
    let bars = &e.ohlc[BTC];
    assert_eq!(bars.len(), 40);
    assert!(bars.iter().all(|b| b.close >= 81_000.0), "a Kraken bar survived the switch");
    assert_eq!(e.history[BTC].len(), 40);
    assert_eq!(e.signalled_bar.get(BTC), e.last_bar_ts.get(BTC), "no entry on the switch bar");
    assert_eq!(journal_count(&e, "different series"), 1);
    assert_eq!(e.data_health().kinds[1].failovers_24h, 1);

    // Kraken's answers while it is not the source do not touch the series.
    e.apply_feed_candles(FeedSource::Kraken, Ok(vec![series(BTC, 79_000.0)]), 5);
    assert!(e.ohlc[BTC].iter().all(|b| b.close >= 81_000.0));
}

#[test]
fn a_candle_series_that_is_behind_or_off_the_live_price_is_refused() {
    let mut e = fed();
    let now = e.now();
    e.apply_feed_quotes(FeedSource::Kraken, Ok(vec![quote(BTC, 80_000.0)]), now);
    // Last close 30 % away from the live mark.
    e.apply_feed_candles(FeedSource::Kraken, Ok(vec![series(BTC, 56_000.0)]), 5);
    assert!(!e.is_bar_backed(BTC));
    // An hour behind.
    let mut old = series(BTC, 80_000.0);
    old.bars.iter_mut().for_each(|b| b.ts -= 3_600_000);
    e.apply_feed_candles(FeedSource::Kraken, Ok(vec![old]), 5);
    assert!(!e.is_bar_backed(BTC));
    assert!(e.data_health().rejections.iter().any(|r| r.kind == DataKind::Candles && r.reason.contains("behind")));
    // The forming bar is never installed, whichever venue sends it.
    let mut with_forming = series(BTC, 80_000.0);
    let forming = with_forming.bars.last().unwrap().ts + 300_000;
    with_forming.bars.push(Ohlc { ts: forming, ..*with_forming.bars.last().unwrap() });
    e.apply_feed_candles(FeedSource::Kraken, Ok(vec![with_forming]), 5);
    assert!(e.ohlc[BTC].iter().all(|b| b.ts < forming));
}

#[test]
fn the_stream_feeds_the_mark_and_a_dead_stream_fails_over_to_rest() {
    let mut e = Engine::new();
    e.start_feeds(FeedConfig::default());
    let now = e.now();
    let mut snap = ws::Snapshot {
        status: StreamStatus { enabled: true, connected: true, last_message: Some(now), ..Default::default() },
        quotes: [("BTC/USD".to_string(), (80_000.0, -0.01))].into_iter().collect(),
    };
    e.apply_stream(snap.clone());
    assert_eq!(e.price_of(BTC), 80_000.0);
    assert_eq!(e.feeds.current(DataKind::Quotes, BTC), Some(FeedSource::KrakenWs));
    assert!(e.feed_needs_poll(DataKind::Quotes, FeedSource::Kraken), "19 coins have no stream price yet");
    // Once the stream carries every coin, REST rests.
    let mut all = snap.clone();
    all.quotes = e.feed_markets().iter().map(|id| (id.trim_start_matches("crypto:").to_string(), (100.0, 0.0))).collect();
    all.quotes.insert("BTC/USD".into(), (80_000.0, -0.01));
    e.apply_stream(all);
    assert!(!e.feed_needs_poll(DataKind::Quotes, FeedSource::Kraken), "REST rests while the stream is up");

    snap.status.connected = false;
    snap.status.last_error = Some("closed by the server".into());
    e.apply_stream(snap.clone());
    e.apply_stream(snap);
    assert!(e.feed_needs_failover(DataKind::Quotes));
    assert!(e.feed_needs_poll(DataKind::Quotes, FeedSource::Kraken));
    e.apply_feed_quotes(FeedSource::Kraken, Ok(vec![quote(BTC, 80_010.0)]), e.now());
    assert_eq!(e.feeds.current(DataKind::Quotes, BTC), Some(FeedSource::Kraken));
    assert_eq!(e.price_of(BTC), 80_010.0);
    assert!(journal_count(&e, "failed over from Kraken stream to Kraken (Kraken stream failed: closed by the server)") == 1);
    let h = e.data_health();
    assert_eq!(h.kinds[0].failovers_24h, 1);
    assert_eq!(h.stream.last_error.as_deref(), Some("closed by the server"));
}

#[test]
fn data_health_names_sources_ages_and_stale_markets() {
    let mut e = fed();
    // The feeds have been running for two minutes and only BTC has a price.
    let now = e.now();
    e.feeds = crate::feeds::FeedHealth::new(FeedConfig { stream: false, ..FeedConfig::default() });
    e.feeds.start(now - 120_000);
    e.apply_feed_quotes(FeedSource::Kraken, Ok(vec![quote(BTC, 80_000.0)]), now);
    let h = e.data_health();
    assert!(h.running);
    assert!(!h.ok);
    let q = &h.kinds[0];
    assert_eq!(q.kind, DataKind::Quotes);
    assert_eq!(q.primary, Some(FeedSource::Kraken));
    assert_eq!(q.active, Some(FeedSource::Kraken));
    assert_eq!(q.markets, 20);
    assert_eq!(q.stale.len(), 19, "every market but BTC");
    assert!(!q.stale.contains(&BTC.to_string()));
    assert_eq!(q.last_update_age_sec, Some(0));
    assert_eq!(q.sources[0].markets, 1);
    assert_eq!(h.kinds[2].primary, Some(FeedSource::Kraken), "books follow the executing venue");

    // Serialised under the names the UI and the health check read.
    let v = serde_json::to_value(e.state()).unwrap();
    assert_eq!(v["dataHealth"]["kinds"][0]["active"], "kraken");
    assert!(v["dataHealth"]["kinds"][0]["failovers24h"].is_number());
    assert!(v["dataHealth"]["kinds"][0]["lastUpdateAgeSec"].is_number());

    // Without a host running feeds there is nothing to be stale.
    let quiet = Engine::new().data_health();
    assert!(!quiet.running && quiet.ok);
}

#[test]
fn stale_data_alerts_the_webhook_once_and_its_recovery_once() {
    let mut e = fed();
    let t0 = e.now();
    e.drain_alerts();
    // No market has delivered anything; past the 30 s limit that is stale.
    e.check_data_alert(t0);
    e.check_data_alert(t0 + 60_000);
    e.check_data_alert(t0 + 4 * 60_000);
    assert!(e.drain_alerts().is_empty(), "a few minutes is not yet an alert");
    e.check_data_alert(t0 + 6 * 60_000);
    e.check_data_alert(t0 + 7 * 60_000);
    let alerts = e.drain_alerts();
    assert_eq!(alerts.len(), 1, "{alerts:?}");
    assert!(alerts[0].contains("Market data stale for 5 min"), "{}", alerts[0]);

    // Every market gets fresh quotes and candles.
    let ids = e.feed_markets();
    let now = e.now();
    let rows: Vec<RealCrypto> = ids.iter().map(|id| quote(id, 100.0)).collect();
    e.apply_feed_quotes(FeedSource::Kraken, Ok(rows), now);
    let bars: Vec<BarSeries> = ids.iter().map(|id| series(id, 100.0)).collect();
    e.apply_feed_candles(FeedSource::Kraken, Ok(bars), 5);
    e.check_data_alert(e.now());
    e.check_data_alert(e.now());
    let alerts = e.drain_alerts();
    assert_eq!(alerts.len(), 1, "{alerts:?}");
    assert!(alerts[0].contains("Market data recovered") && alerts[0].contains("quotes on Kraken"), "{}", alerts[0]);
    assert!(e.data_health().ok);
}

#[test]
fn books_from_the_mirror_count_as_the_executing_venue_and_off_books_are_refused() {
    let mut e = fed();
    e.set_crypto_cost_venue(Some(CostVenue::Binance));
    assert_eq!(e.feed_priority(DataKind::Books), vec![FeedSource::Binance, FeedSource::BinanceVision]);
    e.apply_feed_candles(FeedSource::Kraken, Ok(vec![series(BTC, 80_000.0)]), 5);
    let now = e.now();
    e.apply_feed_quotes(FeedSource::Kraken, Ok(vec![quote(BTC, 80_000.0)]), now);
    let book = |mid: f64| BookSnapshot {
        id: BTC.into(),
        quote: BookQuote::from_levels(CostVenue::Binance, &[(mid - 1.0, 1.0)], &[(mid + 1.0, 1.0)], now).unwrap(),
    };
    e.apply_feed_books(FeedSource::Binance, Err("HTTP 418".into()));
    e.apply_feed_books(FeedSource::Binance, Err("HTTP 418".into()));
    e.apply_feed_books(FeedSource::BinanceVision, Ok(vec![book(80_000.0)]));
    assert_eq!(e.feeds.current(DataKind::Books, BTC), Some(FeedSource::BinanceVision));
    assert!(e.books.contains_key(BTC));
    // A book 20 % off the mark is not a book of this market.
    e.books.clear();
    e.apply_feed_books(FeedSource::BinanceVision, Ok(vec![book(96_000.0)]));
    assert!(!e.books.contains_key(BTC));
}
