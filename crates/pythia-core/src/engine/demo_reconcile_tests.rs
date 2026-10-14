//! The Alpaca paper route against Alpaca's own numbers: the per-pair
//! reconciliation, restarts with orders and positions at the venue, fees that
//! are never posted, and refusals that must not turn into a retry storm. No
//! network: the venue's answers are handed in the shapes the connector parses
//! them into, the way `execution::reconcile_demo` does.

use super::alpaca_fees::WATCH_KEEP_MS;
use super::demo_reconcile::PairStatus;
use super::*;
use crate::connectors::alpaca_crypto::{parse_open_orders, OpenOrder};

const BTC: &str = "crypto:BTC/USD";
const ABTC: &str = "alpaca:BTC/USD";
const PEPE: &str = "crypto:PEPE/USD";
const PX: f64 = 60_000.0;

/// Crypto demo orders on the Alpaca paper account (`PYTHIA_DEMO_EXCHANGE=alpaca`),
/// the Alpaca demo route too, prices real and fresh.
fn engine() -> (Engine, String) {
    let mut e = Engine::new();
    let now = e.now();
    let ids: Vec<String> = e.markets.iter().filter(|m| m.symbol.contains('/')).map(|m| m.id.clone()).collect();
    for m in e.markets.iter_mut().filter(|m| m.symbol.contains('/')) {
        m.updated_at = now;
    }
    e.real_ids.extend(ids);
    e.set_demo_venues([Venue::Crypto, Venue::Alpaca].into_iter().collect(), Some(CostVenue::Alpaca), true);
    let i = e.ensure_manual_strategy();
    let sid = e.strategies[i].id.clone();
    (e, sid)
}

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

/// A demo buy of `notional` in `market`, acknowledged as `broker_id`.
fn demo_buy(e: &mut Engine, sid: &str, market: &str, notional: f64, broker_id: &str) -> LiveOrderOut {
    e.place_order(sid, market, Side::Buy, notional, RouteIntent::Demo).expect("routed");
    let o = e.drain_live_orders().pop().expect("a demo order went out");
    e.apply_live_ack(&o.order_id, broker_id);
    o
}

/// A demo buy that fills in full at `px`.
fn filled_buy(e: &mut Engine, sid: &str, market: &str, notional: f64, px: f64) -> LiveOrderOut {
    let id = format!("alp-{}", e.seq + 1);
    let o = demo_buy(e, sid, market, notional, &id);
    e.apply_live_update(&o.order_id, update(BrokerOrderStatus::Filled, o.qty, px));
    o
}

/// A demo position put straight into the book.
fn hold(e: &mut Engine, market: &str, qty: f64, demo: bool, live: bool) {
    let m = e.markets.iter().find(|m| m.id == market).cloned().unwrap();
    e.positions.insert(
        market.into(),
        PositionInternal {
            venue: m.venue,
            symbol: m.symbol.clone(),
            qty,
            avg_price: m.price,
            strategy_id: "manual".into(),
            stop: 0.0,
            target: 0.0,
            trail_ref: m.price,
            live,
            demo,
        },
    );
}

fn at_alpaca(symbol: &str, qty: f64, avg: f64) -> BrokerPosition {
    BrokerPosition { symbol: symbol.into(), qty, avg_price: avg, market_value: qty * avg }
}

fn check(e: &Engine, pair: &str) -> super::demo_reconcile::PairCheck {
    e.demo_reconcile().expect("ran").pairs.into_iter().find(|p| p.symbol == pair).expect("the pair is listed")
}

fn journal_count(e: &Engine, needle: &str) -> usize {
    e.journal.iter().filter(|j| j.message.contains(needle)).count()
}

// ── (a) the comparison, per Alpaca pair ─────────────────────────────────────

#[test]
fn markets_that_share_a_pair_are_summed_and_agreement_is_quiet() {
    let (mut e, _) = engine();
    // crypto:BTC/USD on the crypto demo route and alpaca:BTC/USD on the
    // Alpaca demo route: one BTC position on the paper account.
    hold(&mut e, BTC, 0.01, true, false);
    hold(&mut e, ABTC, 0.002, true, false);
    let n = e.apply_demo_reconcile(&[at_alpaca("BTC/USD", 0.012, PX)], &[]);
    assert_eq!(n, 0);
    let c = check(&e, "BTC/USD");
    assert_eq!(c.status, PairStatus::Ok);
    assert!((c.pythia - 0.012).abs() < 1e-12 && c.markets.len() == 2, "{c:?}");
    assert_eq!(journal_count(&e, "Alpaca paper reconcile"), 0, "agreement is not journaled");
    let live = e.state().live;
    assert!(live.demo_reconcile.as_ref().is_some_and(|d| d.mismatches == 0 && d.checked_at > 0));
    let json = serde_json::to_value(&live).unwrap();
    assert!(json.get("demoReconcile").is_some(), "the UI reads it as demoReconcile: {json}");
}

#[test]
fn a_shared_pair_that_differs_is_reported_once_and_never_guessed() {
    let (mut e, _) = engine();
    hold(&mut e, BTC, 0.01, true, false);
    hold(&mut e, ABTC, 0.002, true, false);
    for _ in 0..3 {
        assert_eq!(e.apply_demo_reconcile(&[at_alpaca("BTC/USD", 0.009, PX)], &[]), 1);
    }
    let c = check(&e, "BTC/USD");
    assert_eq!(c.status, PairStatus::Mismatch);
    assert!((c.diff - 0.003).abs() < 1e-12 && c.diff_usd > 0.0, "{c:?}");
    assert_eq!(e.positions[BTC].qty, 0.01, "nothing changed");
    assert_eq!(e.positions[ABTC].qty, 0.002);
    assert_eq!(journal_count(&e, "Alpaca paper reconcile BTC/USD"), 1, "the same finding is journaled once");
    // New numbers are a new finding.
    e.apply_demo_reconcile(&[at_alpaca("BTC/USD", 0.008, PX)], &[]);
    assert_eq!(journal_count(&e, "Alpaca paper reconcile BTC/USD"), 2);
}

#[test]
fn the_only_demo_holder_follows_alpaca() {
    let (mut e, sid) = engine();
    let o = filled_buy(&mut e, &sid, "crypto:ETH/USD", 1_000.0, 2_500.0);
    // Half of it is gone at the venue: far more than a fee.
    let venue = o.qty / 2.0;
    e.apply_demo_reconcile(&[at_alpaca("ETH/USD", venue, 2_500.0)], &[]);
    assert_eq!(check(&e, "ETH/USD").status, PairStatus::Corrected);
    assert!((e.positions["crypto:ETH/USD"].qty - venue).abs() < 1e-12);
    // The next run finds them equal.
    e.apply_demo_reconcile(&[at_alpaca("ETH/USD", venue, 2_500.0)], &[]);
    assert_eq!(check(&e, "ETH/USD").status, PairStatus::Ok);
    // Gone at the venue entirely: gone from the book.
    e.apply_demo_reconcile(&[], &[]);
    assert!(!e.positions.contains_key("crypto:ETH/USD"));
}

#[test]
fn a_gap_the_unposted_fee_explains_is_booked_as_that_fee() {
    let (mut e, sid) = engine();
    let o = filled_buy(&mut e, &sid, BTC, 1_000.0, PX);
    let fees0 = e.strategy_config(&sid).unwrap().ledger.fees;
    let held = o.qty * (1.0 - 0.0025);
    e.apply_demo_reconcile(&[at_alpaca("BTC/USD", held, PX)], &[]);
    assert_eq!(check(&e, "BTC/USD").status, PairStatus::FeeTaken);
    assert!((e.positions[BTC].qty - held).abs() < 1e-9);
    let fees = e.strategy_config(&sid).unwrap().ledger.fees - fees0;
    assert!((fees - o.qty * 0.0025 * PX).abs() < 1e-6, "{fees}");
    assert!(e.journal.iter().any(|j| j.message.contains("kept") && j.message.contains("crypto fee")));
}

#[test]
fn nine_decimals_of_rounding_are_not_a_mismatch() {
    let (mut e, _) = engine();
    // The 13.10. PEPE buy, as the book might carry it after float maths.
    hold(&mut e, PEPE, 49_452_471.48288912, true, false);
    hold(&mut e, BTC, 0.0074710000004, true, false);
    let n = e.apply_demo_reconcile(&[at_alpaca("PEPE/USD", 49_452_471.482889, 0.0000042), at_alpaca("BTCUSD", 0.007471, PX)], &[]);
    assert_eq!(n, 0);
    assert_eq!(check(&e, "PEPE/USD").status, PairStatus::Ok);
    assert_eq!(check(&e, "BTC/USD").status, PairStatus::Ok, "BTCUSD is the same pair");
}

#[test]
fn a_live_paper_position_is_left_to_the_live_reconciliation() {
    let (mut e, _) = engine();
    e.live.paper = true;
    hold(&mut e, ABTC, 0.005, false, true);
    e.apply_demo_reconcile(&[at_alpaca("BTC/USD", 0.004, PX)], &[]);
    assert_eq!(check(&e, "BTC/USD").status, PairStatus::Mismatch);
    assert_eq!(e.positions[ABTC].qty, 0.005, "not the demo reconcile's to change");
}

#[test]
fn the_live_paper_reconcile_leaves_the_demo_books_coins_out_of_its_btc() {
    // Gap (1): alpaca:BTC/USD on the live arm's paper endpoint and
    // crypto:BTC/USD on the demo route hold one BTC position at Alpaca.
    let (mut e, _) = engine();
    e.set_live(LiveConfig { armed: true, paper: true, dry_run: false, venues: vec![Venue::Alpaca], timeout_sec: 60, extended_hours: false });
    hold(&mut e, BTC, 0.01, true, false);
    hold(&mut e, ABTC, 0.005, false, true);
    let changes = e.reconcile_positions(Venue::Alpaca, &[at_alpaca("BTC/USD", 0.015, PX)], false);
    assert_eq!(changes, 0, "0.015 is 0.01 demo plus 0.005 live: nothing to correct");
    assert_eq!(e.positions[ABTC].qty, 0.005);
    assert_eq!(e.positions[BTC].qty, 0.01);
    // Only the demo coins are there: the live position is gone.
    e.reconcile_positions(Venue::Alpaca, &[at_alpaca("BTC/USD", 0.01, PX)], false);
    assert!(!e.positions.contains_key(ABTC));
    assert_eq!(e.positions[BTC].qty, 0.01, "the demo position is never touched by the live reconcile");
    // And the demo reconcile sees both sides summed.
    hold(&mut e, ABTC, 0.005, false, true);
    assert_eq!(e.apply_demo_reconcile(&[at_alpaca("BTC/USD", 0.015, PX)], &[]), 0);
}

// ── (e) restarts ────────────────────────────────────────────────────────────

fn restart(e: &Engine) -> Engine {
    let json = serde_json::to_string(&e.to_persisted()).unwrap();
    let mut back = Engine::new();
    back.set_demo_venues([Venue::Crypto, Venue::Alpaca].into_iter().collect(), Some(CostVenue::Alpaca), true);
    back.apply_persisted(serde_json::from_str(&json).unwrap());
    back
}

fn open_order(id: &str, cid: &str, symbol: &str, qty: f64, filled: f64) -> OpenOrder {
    let v = serde_json::json!([{
        "id": id, "client_order_id": cid, "symbol": symbol, "asset_class": "crypto",
        "side": "buy", "qty": qty.to_string(), "filled_qty": filled.to_string(),
        "status": if filled > 0.0 { "partially_filled" } else { "new" }
    }]);
    parse_open_orders(&v).pop().unwrap()
}

#[test]
fn an_order_open_across_a_restart_is_followed_and_holds_its_pair() {
    let (mut e, sid) = engine();
    let o = demo_buy(&mut e, &sid, BTC, 1_000.0, "alp-open-1");
    let mut back = restart(&e);
    assert_eq!(back.live_polls().len(), 1, "followed again after the restart");
    // Alpaca: the order is open and nothing filled; no position.
    let open = open_order("alp-open-1", &o.client_order_id, "BTC/USD", o.qty, 0.0);
    assert_eq!(back.apply_demo_reconcile(&[], &[open]), 0);
    let d = back.demo_reconcile().unwrap();
    assert!(d.stray_orders.is_empty(), "it is Pythia's and followed: {d:?}");
    assert_eq!(d.open_orders, 1);
}

#[test]
fn a_partial_fill_across_a_restart_is_booked_once_and_then_matches() {
    let (mut e, sid) = engine();
    let o = demo_buy(&mut e, &sid, BTC, 1_000.0, "alp-part-1");
    let part = o.qty * 0.4;
    e.apply_live_update(&o.order_id, update(BrokerOrderStatus::PartiallyFilled, part, PX));
    assert!((e.positions[BTC].qty - part).abs() < 1e-12);
    let mut back = restart(&e);
    // While down, the rest filled: Alpaca holds all of it, the book 40 %.
    let venue = [at_alpaca("BTC/USD", o.qty, PX)];
    assert_eq!(back.apply_demo_reconcile(&venue, &[]), 0);
    assert_eq!(check(&back, "BTC/USD").status, PairStatus::Pending, "the order's own report settles it");
    assert!((back.positions[BTC].qty - part).abs() < 1e-12, "nothing corrected under an order in flight");
    // The first poll after the restart books the rest, once.
    back.apply_live_update(&o.order_id, update(BrokerOrderStatus::Filled, o.qty, PX));
    back.apply_live_update(&o.order_id, update(BrokerOrderStatus::Filled, o.qty, PX));
    assert!((back.positions[BTC].qty - o.qty).abs() < 1e-12);
    assert_eq!(back.apply_demo_reconcile(&venue, &[]), 0);
    assert_eq!(check(&back, "BTC/USD").status, PairStatus::Ok);
}

#[test]
fn an_open_order_pythia_does_not_follow_is_reported_and_its_pair_left_alone() {
    let (mut e, _) = engine();
    hold(&mut e, BTC, 0.01, true, false);
    let stray = open_order("alp-x", "pythia-old-ord_9", "BTC/USD", 0.01, 0.004);
    for _ in 0..2 {
        assert_eq!(e.apply_demo_reconcile(&[at_alpaca("BTC/USD", 0.014, PX)], &[stray.clone()]), 1);
    }
    assert_eq!(check(&e, "BTC/USD").status, PairStatus::StrayOrder);
    assert_eq!(e.positions[BTC].qty, 0.01, "not corrected while that order can fill");
    assert_eq!(journal_count(&e, "Alpaca paper has an open order"), 1);
    assert!(e.journal.iter().any(|j| j.message.contains("before a restart")));
    // Gone: the pair is corrected (one holder), and a new stray is said again.
    e.apply_demo_reconcile(&[at_alpaca("BTC/USD", 0.014, PX)], &[]);
    assert_eq!(check(&e, "BTC/USD").status, PairStatus::Corrected);
}

#[test]
fn a_position_missing_locally_is_adopted_only_when_one_market_can_own_it() {
    // Pythia traded SOL on the demo route only in crypto:SOL/USD; the book
    // lost the position (a fill while down whose order was closed unknown).
    let (mut e, sid) = engine();
    let o = filled_buy(&mut e, &sid, "crypto:SOL/USD", 500.0, 150.0);
    e.positions.remove("crypto:SOL/USD");
    e.apply_demo_reconcile(&[at_alpaca("SOLUSD", o.qty, 151.0)], &[]);
    let c = check(&e, "SOL/USD");
    assert_eq!(c.status, PairStatus::Adopted, "{c:?}");
    let p = &e.positions["crypto:SOL/USD"];
    assert!(p.demo && !p.live && (p.qty - o.qty).abs() < 1e-12 && p.avg_price == 151.0);
    assert_eq!(p.strategy_id, sid);

    // BTC was traded on both routes that land on the paper account: ambiguous.
    let (mut e, sid) = engine();
    filled_buy(&mut e, &sid, BTC, 1_000.0, PX);
    e.positions.remove(BTC);
    e.orders.insert(0, Order { market_id: ABTC.into(), venue: Venue::Alpaca, filled_qty: 0.001, ..e.orders[0].clone() });
    assert_eq!(e.apply_demo_reconcile(&[at_alpaca("BTC/USD", 0.02, PX)], &[]), 1);
    assert_eq!(check(&e, "BTC/USD").status, PairStatus::Untracked);
    assert!(!e.positions.contains_key(BTC) && !e.positions.contains_key(ABTC), "never guessed");

    // A pair Pythia never traded on this route: someone else's.
    let (mut e, _) = engine();
    assert_eq!(e.apply_demo_reconcile(&[at_alpaca("DOGE/USD", 100.0, 0.1)], &[]), 1);
    assert_eq!(check(&e, "DOGE/USD").status, PairStatus::Untracked);
    assert!(e.positions.is_empty());
}

#[test]
fn a_failed_read_is_kept_and_said_once() {
    let (mut e, _) = engine();
    e.demo_reconcile_failed("network error: timed out");
    e.demo_reconcile_failed("network error: timed out");
    assert_eq!(journal_count(&e, "could not read the account"), 1);
    let d = e.state().live.demo_reconcile.unwrap();
    assert_eq!(d.error.as_deref(), Some("network error: timed out"));
    assert_eq!(d.checked_at, 0, "never completed");
}

// ── (d) a fee Alpaca never posts ────────────────────────────────────────────

#[test]
fn a_fee_never_posted_is_booked_from_the_schedule_in_dollars_and_marked_estimated() {
    let (mut e, sid) = engine();
    let o = filled_buy(&mut e, &sid, BTC, 1_000.0, PX);
    let (cash0, fees0, qty0) = (e.cash, e.strategy_config(&sid).unwrap().ledger.fees, e.positions[BTC].qty);
    e.alpaca_fees[0].ts -= WATCH_KEEP_MS + 1;
    e.alpaca_fee_queries();
    assert!(e.alpaca_fees.is_empty(), "no longer waited on");
    let want = o.qty * PX * 25.0 / 10_000.0; // tier 1 taker: a demo order always crosses
    let fees = e.strategy_config(&sid).unwrap().ledger.fees - fees0;
    assert!((fees - want).abs() < 1e-6, "{fees} vs {want}");
    assert!((cash0 - e.cash - want).abs() < 1e-6, "out of the cash");
    assert_eq!(e.positions[BTC].qty, qty0, "the coins stay as the venue holds them");
    assert!(e.journal.iter().any(|j| j.message.contains("ESTIMATED fee")));
    let est = e.state().live.demo_reconcile.unwrap().estimated_fees;
    assert_eq!(est.len(), 1);
    assert!(est[0].paper && est[0].rate_bps == 25.0 && (est[0].usd - want).abs() < 1e-6);
    assert!(e.drain_fill_records().is_empty(), "never in the tax record");
    // Kept across a restart.
    assert_eq!(restart(&e).alpaca_fee_estimates().len(), 1);
}

#[test]
fn an_estimate_counts_what_the_venue_already_showed_and_a_posted_fee_is_never_estimated() {
    let (mut e, sid) = engine();
    let o = filled_buy(&mut e, &sid, BTC, 1_000.0, PX);
    // The venue showed a tenth of the fee gone; the estimate is the rest.
    let shown = o.qty * 0.00025;
    assert!(e.take_alpaca_fee_gap(BTC, shown, false, true, "test"));
    let fees0 = e.strategy_config(&sid).unwrap().ledger.fees;
    e.alpaca_fees[0].ts -= WATCH_KEEP_MS + 1;
    e.alpaca_fee_queries();
    let fees = e.strategy_config(&sid).unwrap().ledger.fees - fees0;
    assert!((fees - (o.qty * PX * 0.0025 - shown * PX)).abs() < 1e-6, "{fees}");

    // A fill whose fee was posted is never estimated.
    let (mut e, sid) = engine();
    filled_buy(&mut e, &sid, BTC, 1_000.0, PX);
    e.alpaca_fees[0].posted_coins = 1e-6;
    e.alpaca_fees[0].ts -= WATCH_KEEP_MS + 1;
    e.alpaca_fee_queries();
    assert!(e.alpaca_fee_estimates().is_empty());
}

// ── (c) refusals without a retry storm ──────────────────────────────────────

/// Clear the market backoffs, as if their time had passed.
fn time_passes(e: &mut Engine) {
    e.live_backoff_until.clear();
    e.route_backoff_until.clear();
}

#[test]
fn an_insufficient_balance_refusal_waits_and_is_journaled_once() {
    let (mut e, sid) = engine();
    let msg = r#"venue rejected order: submit 403: {"code":40310000,"message":"insufficient balance for USD (requested: 1000, available: 12.5)"}"#;
    e.place_order(&sid, BTC, Side::Buy, 1_000.0, RouteIntent::Demo).unwrap();
    let o = e.drain_live_orders().pop().unwrap();
    e.apply_live_reject(&o.order_id, msg);
    let err = e.place_order(&sid, BTC, Side::Buy, 1_000.0, RouteIntent::Demo).unwrap_err();
    assert!(err.contains("backing off"), "{err}");
    assert!(e.live_backoff_until[BTC] - e.now() > 14 * 60_000, "15 minutes, not one");
    assert!(e.route_paused_until(Venue::Crypto, true).is_none(), "the balance is not the route");
    // Another market on the route still goes.
    e.place_order(&sid, "crypto:ETH/USD", Side::Buy, 1_000.0, RouteIntent::Demo).expect("other markets are not held up");
    e.drain_live_orders();
    // Refused again after the wait: counted, not journaled.
    for _ in 0..3 {
        time_passes(&mut e);
        e.place_order(&sid, BTC, Side::Buy, 1_000.0, RouteIntent::Demo).unwrap();
        let o = e.drain_live_orders().pop().unwrap();
        e.apply_live_reject(&o.order_id, msg);
    }
    assert_eq!(journal_count(&e, "insufficient balance for USD"), 1);
    assert!(e.journal.iter().any(|j| j.message.contains("[insufficient balance: this market waits 15 min]")));
    // Every refused order still has its row and reason.
    let rows = e.orders.iter().filter(|o| o.market_id == BTC && o.status == OrderStatus::Rejected).count();
    assert_eq!(rows, 4);
}

#[test]
fn a_403_on_the_keys_pauses_the_whole_route() {
    let (mut e, sid) = engine();
    e.place_order(&sid, BTC, Side::Buy, 1_000.0, RouteIntent::Demo).unwrap();
    let o = e.drain_live_orders().pop().unwrap();
    let auth = crate::connectors::ConnectorError::Auth("HTTP 403 on submit: are these paper keys?".into()).to_string();
    e.apply_live_reject(&o.order_id, &auth);
    let until = e.route_paused_until(Venue::Crypto, true).expect("the route waits");
    assert!(until - e.now() > 14 * 60_000);
    let err = e.place_order(&sid, "crypto:ETH/USD", Side::Buy, 1_000.0, RouteIntent::Demo).unwrap_err();
    assert!(err.contains("backing off"), "every market on the route waits: {err}");
    assert!(e.route_paused_until(Venue::Alpaca, true).is_none(), "another route is not held up");
    assert!(e.state().live.demo_paused.iter().any(|(v, _)| *v == Venue::Crypto));
    assert!(e.drain_alerts().iter().any(|a| a.contains("403 forbidden")));
}

#[test]
fn a_size_below_the_minimum_is_skipped_with_one_note() {
    let (mut e, sid) = engine();
    let msg = crate::connectors::alpaca::below_minimum(0.00005, "BTC/USD", 0.0001);
    for _ in 0..4 {
        time_passes(&mut e);
        e.place_order(&sid, BTC, Side::Buy, 1_000.0, RouteIntent::Demo).unwrap();
        let o = e.drain_live_orders().pop().unwrap();
        e.apply_live_reject(&o.order_id, &format!("{msg}"));
    }
    assert_eq!(journal_count(&e, "below Alpaca's minimum order size"), 1, "one note, not one per signal");
    assert!(e.live_backoff_until[BTC] - e.now() > 29 * 60_000);
}

#[test]
fn a_wash_trade_waits_for_the_opposite_order_and_others_stay_as_before() {
    let (mut e, sid) = engine();
    e.place_order(&sid, BTC, Side::Buy, 1_000.0, RouteIntent::Demo).unwrap();
    let o = e.drain_live_orders().pop().unwrap();
    e.apply_live_reject(&o.order_id, r#"venue rejected order: submit 403: {"message":"potential wash trade detected. use complex orders"}"#);
    let wait = e.live_backoff_until[BTC] - e.now();
    assert!(wait > 4 * 60_000 && wait <= 5 * 60_000, "{wait}");
    assert!(e.journal.iter().any(|j| j.message.contains("[wash trade")));

    // An unclassified refusal: one minute, journaled every time, as before.
    for _ in 0..2 {
        time_passes(&mut e);
        e.place_order(&sid, "crypto:ETH/USD", Side::Buy, 1_000.0, RouteIntent::Demo).unwrap();
        let o = e.drain_live_orders().pop().unwrap();
        e.apply_live_reject(&o.order_id, "network error: connection reset");
    }
    assert_eq!(journal_count(&e, "connection reset"), 2);
    assert!(e.live_backoff_until["crypto:ETH/USD"] - e.now() <= LIVE_REJECT_BACKOFF_MS);
}

#[test]
fn refusals_in_a_row_past_the_threshold_alert_once_per_streak() {
    use crate::alerts::AlertKind;
    let (mut e, sid) = engine();
    e.set_alert_reject_threshold(2);
    let refuse = |e: &mut Engine, reason: &str| {
        time_passes(e);
        e.place_order(&sid, BTC, Side::Buy, 1_000.0, RouteIntent::Demo).unwrap();
        let o = e.drain_live_orders().pop().unwrap();
        e.apply_live_reject(&o.order_id, reason);
    };
    let rejects = |e: &mut Engine| e.drain_alert_events().into_iter().filter(|a| a.kind == AlertKind::OrderRejects).collect::<Vec<_>>();
    refuse(&mut e, "venue rejected order: submit 500: busy");
    refuse(&mut e, "venue rejected order: submit 500: busy");
    assert!(rejects(&mut e).is_empty(), "two is not more than two");
    refuse(&mut e, "venue rejected order: submit 500: busy");
    let a = rejects(&mut e);
    assert_eq!(a.len(), 1, "{a:?}");
    assert_eq!(a[0].key, "rejects:demo");
    assert!(a[0].text.starts_with("3 demo orders refused in a row (last: BTC/USD)"), "{}", a[0].text);
    refuse(&mut e, "venue rejected order: submit 500: busy");
    assert!(rejects(&mut e).is_empty(), "once per streak");
    // A fill ends the streak; a dry run never counts.
    e.note_route_fill(true);
    for _ in 0..4 {
        refuse(&mut e, "dry-run: not submitted");
    }
    assert!(rejects(&mut e).is_empty());
    for _ in 0..3 {
        refuse(&mut e, "venue rejected order: submit 500: busy");
    }
    assert_eq!(rejects(&mut e).len(), 1, "a new streak alerts again");
}
