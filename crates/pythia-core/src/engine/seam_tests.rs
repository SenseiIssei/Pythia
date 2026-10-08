//! Tests for the seams between the autopilot, the demo route, the venue
//! fills and reconciliation: what the engine refuses at an autopilot's start,
//! what a broker correction does to an autopilot's books, and what happens to
//! a demo order that was in the air across a restart.

use super::autopilot::*;
use super::*;

const BTC: &str = "crypto:BTC/USD";

/// A fresh engine whose crypto prices count as real and fresh.
fn engine() -> Engine {
    let mut e = Engine::new();
    let now = e.now();
    let ids: Vec<String> = e.markets.iter().filter(|m| m.venue == Venue::Crypto).map(|m| m.id.clone()).collect();
    for m in e.markets.iter_mut().filter(|m| m.venue == Venue::Crypto) {
        m.updated_at = now;
    }
    e.real_ids.extend(ids);
    e
}

fn config(id: &str, mode: AutopilotMode, sleeves: &[&str]) -> AutopilotConfig {
    AutopilotConfig {
        id: id.into(),
        name: format!("Test {id}"),
        mode,
        venue: "kraken".into(),
        capital_usd: 1_000.0,
        sleeves: sleeves.iter().map(|s| SleeveConfig { strategy_id: s.to_string(), weight: 1.0 }).collect(),
        stop: StopRules::default(),
        flatten_on_stop: true,
    }
}

fn state_of(e: &Engine, sid: &str) -> StrategyState {
    e.strategy_config(sid).unwrap().state
}

// ── 4 · a broker correction inside an autopilot ────────────────────────────

fn set_price(e: &mut Engine, market: &str, price: f64) {
    let now = e.now();
    let m = e.markets.iter_mut().find(|m| m.id == market).unwrap();
    m.price = price;
    m.updated_at = now;
}

fn ap_status(e: &Engine, id: &str) -> AutopilotStatus {
    e.autopilot_statuses().into_iter().find(|s| s.config.id == id).unwrap()
}

/// An autopilot holding `qty` BTC bought at `px`, flagged as a real fill so
/// reconciliation treats it as the venue's.
fn owned_btc(stop: StopRules) -> (Engine, String, f64) {
    let mut e = engine();
    let mut c = config("rc", AutopilotMode::Paper, &["ema-cross-1"]);
    c.capital_usd = 10_000.0;
    c.stop = stop;
    let id = e.autopilot_start(c, false, VenueCash::NotRead).unwrap();
    let i = e.strategies.iter().position(|s| s.id == "ema-cross-1").unwrap();
    let m = e.markets.iter().find(|m| m.id == BTC).cloned().unwrap();
    let qty = 2_000.0 / m.price;
    e.fill(i, &m, Side::Buy, qty, m.price);
    e.positions.get_mut(BTC).unwrap().live = true;
    assert_eq!(ap_status(&e, &id).open_positions, 1);
    let held = e.positions[BTC].qty;
    (e, id, held)
}

fn venue_has(qty: f64) -> Vec<BrokerPosition> {
    vec![BrokerPosition { symbol: "BTC/USD".into(), qty, avg_price: 0.0, market_value: 0.0 }]
}

#[test]
fn a_correction_of_an_owned_position_is_booked_to_the_autopilot() {
    let (mut e, id, held) = owned_btc(StopRules::default());
    let avg = e.positions[BTC].avg_price;
    // The price falls 10 %: the autopilot is down on paper.
    set_price(&mut e, BTC, avg * 0.9);
    let before = ap_status(&e, &id);
    assert!(before.pnl < -150.0, "{}", before.pnl);

    // The venue holds only 60 % of it.
    assert_eq!(e.reconcile_positions(Venue::Crypto, &venue_has(held * 0.6), false), 1);
    let after = ap_status(&e, &id);
    assert!((after.equity - before.equity).abs() < 1e-6, "the correction moves no equity: {} then {}", before.equity, after.equity);
    assert_eq!(after.open_positions, 1, "the rest is still the autopilot's");
    assert!((e.positions[BTC].qty - held * 0.6).abs() < 1e-12, "the quantity follows the venue");
    // What the correction changed (the 40 % that went, and the entry price
    // the book now has for the rest) is booked as realised, loss included.
    let mark = avg * 0.9;
    let p = &e.positions[BTC];
    let changed = (mark - avg) * held - (mark - p.avg_price) * p.qty;
    assert!(changed < -60.0, "at least the removed part's loss: {changed}");
    assert!((after.by_sleeve[0].pnl - before.by_sleeve[0].pnl).abs() < 1e-6, "the sleeve keeps it too");
    let sleeve_realised = e.autopilots.iter().find(|a| a.config.id == id).unwrap().sleeves[0].realized;
    assert!((sleeve_realised - changed).abs() < 1e-6, "{sleeve_realised} vs {changed}");
    assert!(
        e.journal.iter().any(|j| j.message.contains("Test rc") && j.message.contains("corrected") && j.message.contains("Booked")),
        "journaled with the numbers"
    );
}

#[test]
fn a_correction_cannot_hide_a_stop() {
    // Max loss $150. The price falls until the autopilot is $200 down, and in
    // the same tick reconciliation finds the position gone at the venue.
    let (mut e, id, held) = owned_btc(StopRules { max_loss_usd: Some(150.0), ..StopRules::default() });
    let avg = e.positions[BTC].avg_price;
    set_price(&mut e, BTC, avg - 200.0 / held);
    assert_eq!(e.reconcile_positions(Venue::Crypto, &[], false), 1, "dropped from the book");
    assert!(e.positions.get(BTC).is_none());

    let s = ap_status(&e, &id);
    assert!(s.pnl < -150.0, "the loss is still the autopilot's after the correction: {}", s.pnl);
    assert_eq!(s.open_positions, 0);
    let now = e.now();
    e.autopilot_step(now);
    let s = ap_status(&e, &id);
    assert_eq!(s.state, AutopilotState::Stopped, "the max-loss stop fires");
    assert!(s.stop_reason.unwrap().contains("max loss"));
}

// ── 3 · a demo strategy and a paper autopilot ──────────────────────────────

#[test]
fn a_paper_autopilot_refuses_a_strategy_that_demo_trades_on_its_own() {
    let mut e = engine();
    e.set_demo_venues([Venue::Crypto].into_iter().collect(), Some(CostVenue::Bybit), true);
    e.set_strategy_state("ema-cross-1", StrategyState::Demo).unwrap();
    let err = e.autopilot_start(config("p", AutopilotMode::Paper, &["ema-cross-1"]), false, VenueCash::NotRead).unwrap_err();
    assert!(err.contains("demo-trades on its own"), "the same kind of sentence as for live: {err}");
    assert!(err.contains("set it to paper yourself"), "{err}");
    assert_eq!(state_of(&e, "ema-cross-1"), StrategyState::Demo, "not silently switched to paper");
    assert!(e.autopilot_statuses().is_empty());

    // A demo autopilot may take it: it keeps trading in demo there.
    e.autopilot_start(config("d", AutopilotMode::Demo, &["ema-cross-1"]), false, VenueCash::NotRead)
        .expect("demo takes a demo strategy");
}

// ── 2 · a demo whose prices are its own ────────────────────────────────────

#[test]
fn a_demo_autopilot_is_refused_on_a_demo_venue_without_real_prices() {
    let mut e = engine();
    // OKX demo keys: OKX runs its own demo book and does not document it as
    // the real market (docs/DEMO.md).
    e.set_demo_venues([Venue::Crypto].into_iter().collect(), Some(CostVenue::Okx), false);
    let err = e.autopilot_start(config("okx", AutopilotMode::Demo, &["ema-cross-1"]), false, VenueCash::NotRead).unwrap_err();
    assert!(err.contains("OKX"), "names the demo exchange: {err}");
    assert!(err.contains("own prices") && err.contains("stop rules"), "says why in a plain sentence: {err}");
    assert!(e.autopilot_statuses().is_empty(), "nothing started");
    assert_eq!(state_of(&e, "ema-cross-1"), StrategyState::Paper, "nothing was taken over");
    assert!(!e.state().live.demo_real_prices, "the UI is told the demo prices are not real");

    // A strategy set to Demo there keeps working, and the journal says what
    // its numbers are.
    e.set_strategy_state("ema-cross-1", StrategyState::Demo).expect("demo on OKX still works for one strategy");
    assert!(e.journal.iter().any(|j| j.message.contains("API test, not a price test")));
}

#[test]
fn a_demo_autopilot_on_a_real_price_demo_runs_on_and_names_the_demo_exchange() {
    let mut e = engine();
    e.set_demo_venues([Venue::Crypto].into_iter().collect(), Some(CostVenue::Bybit), true);
    // The page used to send the live exchange (Kraken) for a demo start; the
    // orders go to Bybit's demo account, so that is the autopilot's venue.
    let id = e.autopilot_start(config("by", AutopilotMode::Demo, &["ema-cross-1"]), false, VenueCash::NotRead).unwrap();
    let s = e.autopilot_statuses().into_iter().find(|s| s.config.id == id).unwrap();
    assert_eq!(s.config.venue, "bybit");
    assert!(e.state().live.demo_real_prices);
    assert!(e.journal.iter().any(|j| j.message.contains("in demo on Bybit")), "the start names Bybit");

    // A third exchange is neither the live nor the demo one: refused.
    let mut c = config("bn", AutopilotMode::Demo, &["multi-tf-1"]);
    c.venue = "binance".into();
    let err = e.autopilot_start(c, false, VenueCash::NotRead).unwrap_err();
    assert!(err.contains("Bybit") && err.contains("demo"), "{err}");
}

// ── 5 · a demo order across a restart ──────────────────────────────────────

/// A demo buy sent to Bybit's demo account that the venue had not
/// acknowledged yet when the process stopped, and the engine after the restart.
fn demo_order_across_restart() -> (Engine, LiveOrderOut) {
    let mut e = engine();
    e.set_demo_venues([Venue::Crypto].into_iter().collect(), Some(CostVenue::Bybit), true);
    let i = e.ensure_manual_strategy();
    let sid = e.strategies[i].id.clone();
    e.place_order(&sid, BTC, Side::Buy, 1_000.0, RouteIntent::Demo).expect("routed");
    let o = e.drain_live_orders().pop().expect("a demo order went out");
    let json = serde_json::to_string(&e.to_persisted()).unwrap();
    let mut back = Engine::new();
    back.apply_persisted(serde_json::from_str(&json).unwrap());
    back.set_demo_venues([Venue::Crypto].into_iter().collect(), Some(CostVenue::Bybit), true);
    (back, o)
}

fn filled_at_venue(o: &LiveOrderOut, px: f64) -> crate::connectors::BrokerOrder {
    let mut bo = crate::connectors::BrokerOrder::acknowledged("bybit-77", Some(o.client_order_id.clone()));
    bo.status = BrokerOrderStatus::Filled;
    bo.filled_qty = o.qty;
    bo.avg_price = Some(px);
    bo.raw_status = "Filled".into();
    bo
}

#[test]
fn an_unacknowledged_demo_order_is_looked_up_by_client_id_after_a_restart_and_booked() {
    let (mut e, o) = demo_order_across_restart();
    let ls = e.client_lookups();
    assert_eq!(ls.len(), 1, "the demo order is asked for, not dropped");
    assert_eq!((ls[0].order_id.as_str(), ls[0].client_order_id.as_str()), (o.order_id.as_str(), o.client_order_id.as_str()));
    assert!(ls[0].demo && ls[0].venue == Venue::Crypto && ls[0].symbol == "BTC/USD");
    assert!(e.live_polls().is_empty(), "there is no broker id to poll yet");
    assert!(e.in_flight_markets.contains(BTC), "no second order into that market meanwhile");
    assert!(e.journal.iter().any(|j| j.message.contains(&o.client_order_id) && j.message.contains("looking it up")));

    // It filled at the demo venue while Pythia was down.
    e.apply_lookup_found(&o.order_id, filled_at_venue(&o, 60_000.0));
    let p = e.positions.get(BTC).expect("the fill is booked");
    assert!(p.demo && !p.live && (p.qty - o.qty).abs() < 1e-12);
    let row = e.orders.iter().find(|x| x.id == o.order_id).unwrap();
    assert_eq!((row.status, row.route), (OrderStatus::Filled, FillRoute::Demo));
    assert!(e.client_lookups().is_empty() && e.live_polls().is_empty() && !e.in_flight_markets.contains(BTC));
    assert!(e.drain_fill_records().is_empty(), "demo, never taxed");
}

#[test]
fn a_demo_order_still_working_at_the_venue_is_followed_after_the_lookup() {
    let (mut e, o) = demo_order_across_restart();
    let mut bo = crate::connectors::BrokerOrder::acknowledged("bybit-78", Some(o.client_order_id.clone()));
    bo.raw_status = "New".into();
    e.apply_lookup_found(&o.order_id, bo);
    let polls = e.live_polls();
    assert_eq!(polls.len(), 1);
    assert_eq!((polls[0].broker_id.as_str(), polls[0].demo), ("bybit-78", true));
    assert!(e.client_lookups().is_empty());
}

#[test]
fn a_demo_order_the_venue_never_received_is_closed_with_nothing_filled() {
    let (mut e, o) = demo_order_across_restart();
    e.apply_lookup_missing(&o.order_id);
    let row = e.orders.iter().find(|x| x.id == o.order_id).unwrap();
    assert_eq!(row.status, OrderStatus::Rejected);
    assert!(row.reject_reason.as_deref().unwrap().contains("never reached the demo venue"));
    assert!(e.positions.get(BTC).is_none());
    assert!(e.client_lookups().is_empty() && !e.in_flight_markets.contains(BTC));
}

#[test]
fn a_demo_venue_that_cannot_answer_leaves_the_client_id_in_the_journal() {
    let (mut e, o) = demo_order_across_restart();
    e.apply_lookup_failed(&o.order_id, "No demo exchange is configured");
    let row = e.orders.iter().find(|x| x.id == o.order_id).unwrap();
    assert_eq!(row.status, OrderStatus::Rejected);
    let why = row.reject_reason.clone().unwrap();
    assert!(why.contains(&o.client_order_id) && why.contains("Check the demo account"), "{why}");
    assert!(e.journal.iter().any(|j| j.kind == JournalKind::Risk && j.message.contains(&o.client_order_id)));
    assert!(e.client_lookups().is_empty() && !e.in_flight_markets.contains(BTC));
}
