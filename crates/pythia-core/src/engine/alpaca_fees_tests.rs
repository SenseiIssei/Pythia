//! Alpaca crypto fees, from the fill to the posted activity. No network:
//! the activities are the JSON shapes from Alpaca's docs (see
//! `connectors::alpaca::CryptoFeeActivity`), parsed by the connector's own
//! parser and handed to the engine the way the daemon does.

use super::alpaca_fees::{ny_date, AlpacaFeeWatch};
use super::autopilot::*;
use super::*;
use crate::connectors::alpaca::{parse_fee_activities, CryptoFeeActivity};
use crate::tax::{fold_fees, RecordKind};

const BTC: &str = "alpaca:BTC/USD";
/// Tier 1 taker, the rate a first market order pays.
const RATE: f64 = 0.0025;
const PX: f64 = 60_000.0;

fn update(status: BrokerOrderStatus, filled: f64, price: f64) -> LiveUpdate {
    LiveUpdate {
        status,
        filled_qty: filled,
        avg_price: Some(price),
        fee: 0.0,
        fee_base: 0.0,
        fee_unpriced: Vec::new(),
        raw_status: format!("{status:?}"),
    }
}

/// An engine armed for real money on Alpaca, market open.
fn live_engine() -> Engine {
    let mut e = Engine::new();
    let now = e.now();
    e.set_broker_status(BrokerStatus {
        market_open: true,
        extended_open: true,
        session_end: None,
        next_open: None,
        day_trade_limit_reached: false,
        restricted: None,
        equity: 100_000.0,
        buying_power: 200_000.0,
        checked_at: now,
    });
    e.set_live(LiveConfig { armed: true, paper: false, dry_run: false, venues: vec![Venue::Alpaca], timeout_sec: 120, extended_hours: false });
    e
}

/// Buy about $1,000 of BTC on Alpaca for real and let it fill at `PX`
/// without a fee, which is what Alpaca's order object reports.
fn live_buy(e: &mut Engine) -> (String, f64) {
    e.live_order_for_test(BTC, Side::Buy, 1_000.0);
    let o = e.drain_live_orders().pop().expect("the buy went out");
    assert!(!o.paper && !o.demo, "a real-money order");
    e.apply_live_ack(&o.order_id, "alp-1");
    e.apply_live_update(&o.order_id, update(BrokerOrderStatus::Filled, o.qty, PX));
    (o.order_id, o.qty)
}

/// Alpaca's CFEE for a coin fee, in the docs' own shape, dated today.
fn cfee(id: &str, coins: f64, date: &str) -> Vec<CryptoFeeActivity> {
    let json = format!(
        r#"[{{"id":"{id}","activity_type":"CFEE","date":"{date}","net_amount":"0",
             "description":"Coin Pair Transaction Fee (Non USD)","symbol":"BTCUSD",
             "qty":"-{coins}","price":"{PX}","status":"executed"}}]"#
    );
    parse_fee_activities(&serde_json::from_str(&json).unwrap())
}

/// A fee in dollars on a sell. Not shown in the docs; read from `net_amount`.
fn usd_fee(id: &str, usd: f64, date: &str) -> Vec<CryptoFeeActivity> {
    let json = format!(
        r#"[{{"id":"{id}","activity_type":"CFEE","date":"{date}","net_amount":"-{usd}",
             "symbol":"BTC/USD","qty":"0","status":"executed"}}]"#
    );
    parse_fee_activities(&serde_json::from_str(&json).unwrap())
}

fn fees_of(e: &Engine, sid: &str) -> f64 {
    e.strategy_config(sid).unwrap().ledger.fees
}

#[test]
fn a_posted_coin_fee_books_the_coins_received_and_the_fee_in_dollars() {
    let mut e = live_engine();
    let (oid, qty) = live_buy(&mut e);
    assert!((e.positions[BTC].qty - qty).abs() < 1e-12, "booked as filled until the fee is known");
    assert_eq!(e.alpaca_fees.len(), 1, "the fill waits for its fee");
    let records = e.drain_fill_records();
    assert_eq!(records.len(), 1);
    let cash = e.cash;

    let today = ny_date(e.now());
    let coins = qty * RATE;
    e.apply_alpaca_fees(false, &cfee("20261008::a", coins, &today));

    let net = qty - coins;
    assert!((e.positions[BTC].qty - net).abs() < 1e-9, "the book holds what Alpaca holds: {}", e.positions[BTC].qty);
    assert!((fees_of(&e, "manual") - coins * PX).abs() < 1e-6, "the fee in dollars at the fill price");
    assert!((e.cash - cash).abs() < 1e-9, "no cash moves: the fill already paid for those coins");
    assert!(e.journal.iter().any(|j| j.message.contains("CFEE") && j.message.contains("taken from the position now")));

    // The tax record gets the fee for the same order, and the two lines
    // together read like a fill that reported its fee.
    let fee_lines = e.drain_fill_records();
    assert_eq!(fee_lines.len(), 1);
    assert_eq!(fee_lines[0].kind, RecordKind::Fee);
    assert_eq!(fee_lines[0].order_id, oid);
    let folded = fold_fees(&[records, fee_lines].concat());
    assert_eq!(folded.len(), 1);
    assert!((folded[0].qty - net).abs() < 1e-9 && (folded[0].fee - coins * PX).abs() < 1e-6, "{:?}", folded[0]);

    // Read again at the next poll: booked once.
    e.apply_alpaca_fees(false, &cfee("20261008::a", coins, &today));
    assert!((e.positions[BTC].qty - net).abs() < 1e-9);
    assert!((fees_of(&e, "manual") - coins * PX).abs() < 1e-6);
    assert!(e.drain_fill_records().is_empty());
}

#[test]
fn the_venues_position_books_the_fee_first_and_the_posting_only_confirms_it() {
    let mut e = live_engine();
    let (_, qty) = live_buy(&mut e);
    let coins = qty * RATE;
    let stop = e.positions[BTC].stop;

    // Alpaca already shows the coins gone.
    let venue = [BrokerPosition { symbol: "BTC/USD".into(), qty: qty - coins, avg_price: PX, market_value: 0.0 }];
    assert_eq!(e.reconcile_positions(Venue::Alpaca, &venue, false), 0, "a fee, not a difference");
    assert!((e.positions[BTC].qty - (qty - coins)).abs() < 1e-9);
    assert_eq!(e.positions[BTC].stop, stop, "a fee does not reset the stops");
    assert!((fees_of(&e, "manual") - coins * PX).abs() < 1e-6, "booked as a fee, not as a correction");
    assert!(!e.journal.iter().any(|j| j.message.contains("broker wins")));
    assert!(e.journal.iter().any(|j| j.message.contains("kept") && j.message.contains("crypto fee")));
    assert_eq!(e.reconcile_positions(Venue::Alpaca, &venue, false), 0, "and then they agree");

    // The posting at the end of the day changes nothing but the record.
    let today = ny_date(e.now());
    e.apply_alpaca_fees(false, &cfee("20261008::b", coins, &today));
    assert!((e.positions[BTC].qty - (qty - coins)).abs() < 1e-9, "not taken twice");
    assert!((fees_of(&e, "manual") - coins * PX).abs() < 1e-6, "not charged twice");
    assert!(e.journal.iter().any(|j| j.message.contains("already showed it")));
    let records = e.drain_fill_records();
    assert_eq!(records.iter().filter(|r| r.kind == RecordKind::Fee).count(), 1, "the record gets the posted fee");

    // A gap bigger than any fee is still a correction.
    let venue = [BrokerPosition { symbol: "BTC/USD".into(), qty: (qty - coins) / 2.0, avg_price: PX, market_value: 0.0 }];
    assert_eq!(e.reconcile_positions(Venue::Alpaca, &venue, false), 1);
    assert!(e.journal.iter().any(|j| j.message.contains("broker wins")));
}

#[test]
fn an_exit_sells_what_alpaca_holds_and_a_sells_fee_is_booked_in_dollars() {
    let mut e = live_engine();
    let (_, qty) = live_buy(&mut e);
    let coins = qty * RATE;
    e.drain_fill_records();
    let cash0 = e.cash;

    // The exit asks for the whole book; the connector sends what the venue
    // holds (see `AlpacaConnector::submit_order`), and that fills.
    e.flatten(BTC);
    let exit = e.drain_live_orders().pop().expect("the exit goes to Alpaca");
    assert!(exit.reduce_only && (exit.qty - qty).abs() < 1e-12);
    e.apply_live_ack(&exit.order_id, "alp-2");
    let sold = qty - coins;
    let sell_px = 61_000.0;
    e.apply_live_update(&exit.order_id, update(BrokerOrderStatus::Filled, sold, sell_px));
    assert!(e.positions.get(BTC).is_none(), "the leftover coins were the buy's fee, not a position");
    assert!((fees_of(&e, "manual") - coins * PX).abs() < 1e-6);
    assert!((e.cash - cash0 - sold * sell_px).abs() < 1e-6, "the sale's dollars, no more");
    assert_eq!(e.alpaca_fees.len(), 2, "the buy and the sell both wait for their posted fees");

    // End of day: Alpaca posts the buy's coins and the sell's dollars.
    let today = ny_date(e.now());
    let sell_fee = sold * sell_px * RATE;
    let mut posted = cfee("20261008::c", coins, &today);
    posted.extend(usd_fee("20261008::d", sell_fee, &today));
    assert_eq!(posted.len(), 2);
    e.apply_alpaca_fees(false, &posted);
    assert!(e.positions.get(BTC).is_none(), "still flat: nothing is taken twice");
    assert!((fees_of(&e, "manual") - (coins * PX + sell_fee)).abs() < 1e-6);
    assert!((e.cash - cash0 - (sold * sell_px - sell_fee)).abs() < 1e-6, "the sell's fee leaves the cash");
    let records = e.drain_fill_records();
    let fees: Vec<_> = records.iter().filter(|r| r.kind == RecordKind::Fee).collect();
    assert_eq!(fees.len(), 2);
    let sell_line = fees.iter().find(|r| r.side == Side::Sell).unwrap();
    assert_eq!(sell_line.qty, 0.0, "a fee in dollars takes no coins");
    assert!((sell_line.fee - sell_fee).abs() < 1e-6);
}

#[test]
fn a_fee_that_matches_no_waiting_fill_is_journaled_not_booked() {
    let mut e = live_engine();
    let (_, qty) = live_buy(&mut e);
    // Another day entirely, and another account.
    e.apply_alpaca_fees(false, &cfee("old", qty * RATE, "2020-01-02"));
    e.apply_alpaca_fees(true, &cfee("paper", qty * RATE, &ny_date(e.now())));
    assert!((e.positions[BTC].qty - qty).abs() < 1e-12);
    assert_eq!(fees_of(&e, "manual"), 0.0);
    assert_eq!(e.journal.iter().filter(|j| j.message.contains("matches no fill")).count(), 2);
}

#[test]
fn the_daemon_is_asked_to_read_fees_only_while_some_are_awaited() {
    let mut e = live_engine();
    assert!(e.alpaca_fee_queries().is_empty(), "nothing to wait for");
    live_buy(&mut e);
    let q = e.alpaca_fee_queries();
    assert_eq!(q.len(), 1);
    assert!(!q[0].paper, "the live account");
    assert!(q[0].after.ends_with('Z') && q[0].after.len() == 20, "{}", q[0].after);
    assert!(e.alpaca_fee_queries().is_empty(), "not again within half an hour");

    // A restart keeps the waiting fill and what was booked.
    let today = ny_date(e.now());
    e.apply_alpaca_fees(false, &cfee("seen-1", 1e-6, &today));
    let json = serde_json::to_string(&e.to_persisted()).unwrap();
    let mut back = Engine::new();
    back.apply_persisted(serde_json::from_str(&json).unwrap());
    assert_eq!(back.alpaca_fees.len(), 1);
    let fees = fees_of(&back, "manual");
    back.apply_alpaca_fees(false, &cfee("seen-1", 1e-6, &today));
    assert_eq!(fees_of(&back, "manual"), fees, "an activity booked before the restart is not booked again");

    // A week later it is no longer waited on.
    back.alpaca_fees[0].ts -= alpaca_fees::WATCH_KEEP_MS + 1;
    back.alpaca_fee_polled = 0;
    assert!(back.alpaca_fee_queries().is_empty());
    assert!(back.alpaca_fees.is_empty());
}

#[test]
fn equity_fills_are_never_watched() {
    let mut e = live_engine();
    e.live_order_for_test("alpaca:AAPL", Side::Buy, 1_000.0);
    let o = e.drain_live_orders().pop().unwrap();
    e.apply_live_ack(&o.order_id, "alp-3");
    e.apply_live_update(&o.order_id, update(BrokerOrderStatus::Filled, o.qty, 228.0));
    assert!(e.alpaca_fees.is_empty(), "US equities are commission-free");
}

#[test]
fn a_late_fee_is_paid_by_the_autopilot_whose_trade_caused_it() {
    // A paper autopilot holding BTC: the fee booking does not care which
    // route the fill came by, so the watch is set up by hand.
    let mut e = Engine::new();
    let now = e.now();
    let ids: Vec<String> = e.markets.iter().filter(|m| m.venue == Venue::Crypto).map(|m| m.id.clone()).collect();
    for m in e.markets.iter_mut().filter(|m| m.venue == Venue::Crypto) {
        m.updated_at = now;
    }
    e.real_ids.extend(ids);
    let cfg = AutopilotConfig {
        id: "fee".into(),
        name: "Fee test".into(),
        mode: AutopilotMode::Paper,
        venue: "kraken".into(),
        capital_usd: 10_000.0,
        sleeves: vec![SleeveConfig { strategy_id: "ema-cross-1".into(), weight: 1.0 }],
        stop: StopRules::default(),
        flatten_on_stop: true,
    };
    let id = e.autopilot_start(cfg, false, VenueCash::NotRead).unwrap();
    let market = "crypto:BTC/USD";
    let i = e.strategies.iter().position(|s| s.id == "ema-cross-1").unwrap();
    let m = e.markets.iter().find(|m| m.id == market).cloned().unwrap();
    let qty = 2_000.0 / m.price;
    e.fill(i, &m, Side::Buy, qty, m.price);
    let before = e.autopilot_statuses().into_iter().find(|s| s.config.id == id).unwrap();
    e.alpaca_fees.push(AlpacaFeeWatch {
        order_id: "o-ap".into(),
        market_id: market.into(),
        symbol: "BTC/USD".into(),
        side: Side::Buy,
        strategy_id: "ema-cross-1".into(),
        qty,
        price: m.price,
        ts: now,
        paper: true,
        demo: false,
        taxed: false,
        taken: 0.0,
        posted_coins: 0.0,
        posted_usd: 0.0,
    });
    let coins = qty * RATE;
    e.apply_alpaca_fees(true, &cfee("ap-1", coins, &ny_date(now)));
    let after = e.autopilot_statuses().into_iter().find(|s| s.config.id == id).unwrap();
    assert!((after.fees - before.fees - coins * m.price).abs() < 1e-6, "the autopilot paid it: {} then {}", before.fees, after.fees);
    // Less the fee, give or take the open P&L the fee coins carried.
    assert!((after.equity - (before.equity - coins * m.price)).abs() < 0.01, "and its equity shows it: {} then {}", before.equity, after.equity);
    assert!(e.journal.iter().any(|j| j.message.contains("Fee test")), "the journal names who paid");
}
