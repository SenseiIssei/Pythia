//! Maker execution on the Alpaca crypto demo route, end to end through the
//! daemon (`execution::cycle_orders`) against a scripted venue: resting at
//! the touch, re-pricing, the timeout fallback, partial fills, a restart with
//! an order open at the venue, and cancelling when an autopilot stops.

use super::autopilot::*;
use super::maker::*;
use super::*;
use crate::connectors::{
    Balance, BrokerOrder, ConnectorError, Environment, MarketConnector, OpenOrder, OrderRequest,
};
use crate::execution::{cycle_orders, ConnectorSource};
use crate::orderbook::{BookQuote, BookSnapshot};
use async_trait::async_trait;
use std::sync::{Arc, Mutex};

const BTC: &str = "crypto:BTC/USD";
const PX: f64 = 60_000.0;

// ── a scripted venue ────────────────────────────────────────────────────────

#[derive(Debug, Clone)]
struct VenueOrder {
    id: String,
    cid: String,
    symbol: String,
    qty: f64,
    limit: Option<f64>,
    ioc: bool,
    filled: f64,
    avg: f64,
    status: BrokerOrderStatus,
    raw: String,
}

impl VenueOrder {
    fn broker(&self) -> BrokerOrder {
        BrokerOrder {
            id: self.id.clone(),
            client_order_id: Some(self.cid.clone()),
            status: self.status,
            filled_qty: self.filled,
            avg_price: (self.filled > 0.0).then_some(self.avg),
            fee: 0.0,
            fee_base: 0.0,
            fee_unpriced: Vec::new(),
            raw_status: self.raw.clone(),
        }
    }
}

#[derive(Default)]
struct VenueState {
    orders: Vec<VenueOrder>,
    cancels: Vec<String>,
    /// Market orders and IOC limits fill at once at this price; an IOC
    /// fills `ioc_share` of its quantity and drops the rest.
    cross_px: f64,
    ioc_share: f64,
    /// Refuse every limit order (a price the venue does not accept).
    refuse_limits: bool,
}

#[derive(Clone, Default)]
struct Venue(Arc<Mutex<VenueState>>);

impl Venue {
    fn new() -> Self {
        let v = Venue::default();
        {
            let mut s = v.0.lock().unwrap();
            s.cross_px = PX + 20.0;
            s.ioc_share = 1.0;
        }
        v
    }

    fn orders(&self) -> Vec<VenueOrder> {
        self.0.lock().unwrap().orders.clone()
    }

    fn last(&self) -> VenueOrder {
        self.orders().pop().expect("an order reached the venue")
    }

    fn cancels(&self) -> usize {
        self.0.lock().unwrap().cancels.len()
    }

    /// The venue fills `qty` more of order `id` at `px` (cumulative average).
    fn fill(&self, id: &str, qty: f64, px: f64) {
        let mut s = self.0.lock().unwrap();
        let o = s.orders.iter_mut().find(|o| o.id == id).unwrap();
        let total = o.filled + qty;
        o.avg = (o.avg * o.filled + px * qty) / total;
        o.filled = total;
        if o.qty - total <= 1e-12 {
            o.status = BrokerOrderStatus::Filled;
            o.raw = "filled".into();
        } else {
            o.status = BrokerOrderStatus::PartiallyFilled;
            o.raw = "partially_filled".into();
        }
    }

    /// An order resting at the venue that the engine never heard back about.
    fn rest_unseen(&self, cid: &str, qty: f64, limit: f64) -> String {
        let mut s = self.0.lock().unwrap();
        let id = format!("v{}", s.orders.len() + 1);
        s.orders.push(VenueOrder {
            id: id.clone(),
            cid: cid.into(),
            symbol: "BTC/USD".into(),
            qty,
            limit: Some(limit),
            ioc: false,
            filled: 0.0,
            avg: 0.0,
            status: BrokerOrderStatus::Working,
            raw: "new".into(),
        });
        id
    }
}

#[async_trait]
impl MarketConnector for Venue {
    fn venue(&self) -> crate::connectors::Venue {
        crate::connectors::Venue::Crypto
    }
    fn is_live_ready(&self) -> bool {
        true
    }
    fn round_qty(&self, qty: f64, _symbol: &str) -> f64 {
        (qty * 1e6).trunc() / 1e6
    }
    async fn verify(&self) -> Result<String, ConnectorError> {
        Ok("scripted venue".into())
    }
    async fn submit_order(&self, req: OrderRequest) -> Result<BrokerOrder, ConnectorError> {
        let mut s = self.0.lock().unwrap();
        if s.refuse_limits && req.limit_price.is_some() {
            return Err(ConnectorError::Rejected("422 invalid limit price".into()));
        }
        let id = format!("v{}", s.orders.len() + 1);
        let mut o = VenueOrder {
            id,
            cid: req.client_order_id.clone().unwrap_or_default(),
            symbol: req.symbol.clone(),
            qty: req.qty,
            limit: req.limit_price,
            ioc: req.ioc,
            filled: 0.0,
            avg: 0.0,
            status: BrokerOrderStatus::Working,
            raw: "new".into(),
        };
        // A market order or an IOC fills now (an IOC partly, then is done).
        if req.limit_price.is_none() || req.ioc {
            let share = if req.ioc { s.ioc_share } else { 1.0 };
            o.filled = req.qty * share;
            o.avg = s.cross_px;
            o.status = if share >= 1.0 { BrokerOrderStatus::Filled } else { BrokerOrderStatus::Canceled };
            o.raw = if share >= 1.0 { "filled".into() } else { "canceled".into() };
        }
        let bo = o.broker();
        s.orders.push(o);
        Ok(bo)
    }
    async fn order_status(&self, broker_id: &str, _symbol: &str) -> Result<BrokerOrder, ConnectorError> {
        let s = self.0.lock().unwrap();
        s.orders
            .iter()
            .find(|o| o.id == broker_id)
            .map(VenueOrder::broker)
            .ok_or_else(|| ConnectorError::Rejected("404 order not found".into()))
    }
    async fn cancel_order(&self, broker_id: &str, _symbol: &str) -> Result<(), ConnectorError> {
        let mut s = self.0.lock().unwrap();
        s.cancels.push(broker_id.to_string());
        if let Some(o) = s.orders.iter_mut().find(|o| o.id == broker_id && !o.status.is_terminal()) {
            o.status = BrokerOrderStatus::Canceled;
            o.raw = "canceled".into();
        }
        Ok(())
    }
    async fn order_by_client_id(&self, cid: &str, _symbol: &str) -> Result<Option<BrokerOrder>, ConnectorError> {
        Ok(self.0.lock().unwrap().orders.iter().find(|o| o.cid == cid).map(VenueOrder::broker))
    }
    async fn open_orders(&self) -> Result<Vec<OpenOrder>, ConnectorError> {
        Ok(self
            .0
            .lock()
            .unwrap()
            .orders
            .iter()
            .filter(|o| !o.status.is_terminal())
            .map(|o| OpenOrder { order: o.broker(), symbol: o.symbol.clone() })
            .collect())
    }
    async fn balances(&self) -> Result<Vec<Balance>, ConnectorError> {
        Ok(vec![])
    }
}

/// The daemon's connectors: the scripted venue for everything.
struct Src(Venue);

impl ConnectorSource for Src {
    fn connector_for(
        &self,
        _venue: crate::connectors::Venue,
        _env: Environment,
        _paper: bool,
        _extended: bool,
    ) -> Result<Box<dyn MarketConnector>, String> {
        Ok(Box::new(self.0.clone()))
    }
    fn maker_venue(&self) -> Option<Box<dyn MarketConnector>> {
        Some(Box::new(self.0.clone()))
    }
}

// ── the engine ──────────────────────────────────────────────────────────────

/// Crypto demo on the Alpaca paper account, BTC at 60,000 with a fresh
/// book 59,990 / 60,010.
fn engine() -> Engine {
    let mut e = Engine::new();
    let now = e.now();
    let ids: Vec<String> = e.markets.iter().filter(|m| m.venue == crate::connectors::Venue::Crypto).map(|m| m.id.clone()).collect();
    for m in e.markets.iter_mut().filter(|m| m.venue == crate::connectors::Venue::Crypto) {
        m.updated_at = now;
        if m.id == BTC {
            m.price = PX;
        }
    }
    e.real_ids.extend(ids);
    e.bar_backed.insert(BTC.to_string());
    e.set_demo_venues([crate::connectors::Venue::Crypto].into_iter().collect(), Some(CostVenue::Alpaca), true);
    book(&mut e, PX - 10.0, PX + 10.0);
    e
}

fn book(e: &mut Engine, bid: f64, ask: f64) {
    let now = e.now();
    let quote = BookQuote::from_levels(CostVenue::Kraken, &[(bid, 1.0), (bid - 10.0, 2.0)], &[(ask, 1.0), (ask + 10.0, 2.0)], now)
        .unwrap();
    e.apply_books(&[BookSnapshot { id: BTC.into(), quote }]);
}

fn manual(e: &mut Engine) -> String {
    let i = e.ensure_manual_strategy();
    e.strategies[i].id.clone()
}

/// Run the daemon once against the scripted venue.
fn cycle(e: Engine, v: &Venue) -> Engine {
    let m = std::sync::Mutex::new(e);
    tokio::runtime::Builder::new_current_thread().build().unwrap().block_on(cycle_orders(&m, &Src(v.clone())));
    m.into_inner().unwrap()
}

fn row(e: &Engine, order_id: &str) -> Order {
    e.orders.iter().find(|o| o.id == order_id).cloned().unwrap()
}

/// The order id of the only in-flight order.
fn working(e: &Engine) -> String {
    let ids: Vec<&String> = e.inflight.keys().collect();
    assert_eq!(ids.len(), 1, "one order in flight");
    ids[0].clone()
}

fn journal_has(e: &Engine, needle: &str) -> bool {
    e.journal.iter().any(|j| j.message.contains(needle))
}

const REST_MS: i64 = 21_000;

// ── the tests ───────────────────────────────────────────────────────────────

#[test]
fn a_buy_rests_at_the_best_bid_and_a_fill_there_is_maker() {
    let v = Venue::new();
    let mut e = engine();
    let sid = manual(&mut e);
    e.place_order(&sid, BTC, Side::Buy, 1_200.0, RouteIntent::Demo).expect("routed");
    let e = cycle(e, &v);
    let o = v.last();
    assert_eq!(o.limit, Some(PX - 10.0), "at the best bid");
    assert!(!o.ioc);
    let id = working(&e);
    assert_eq!(o.cid, format!("pythia-{}-{id}", e.boot_tag), "the first order keeps the order's client id");
    assert!(journal_has(&e, "as a maker limit at 59990"));
    assert_eq!((row(&e, &id).order_type, row(&e, &id).limit_price), (OrderType::Limit, Some(PX - 10.0)));

    // Nothing filled yet and inside the rest time: no cancel, still working.
    let e = cycle(e, &v);
    assert_eq!(v.cancels(), 0);
    assert_eq!(row(&e, &id).status, OrderStatus::Pending);

    v.fill(&o.id, o.qty, PX - 10.0);
    let e = cycle(e, &v);
    let r = row(&e, &id);
    assert_eq!(r.status, OrderStatus::Filled);
    assert!((r.filled_qty - o.qty).abs() < 1e-12);
    assert_eq!((r.maker_qty, r.taker_qty), (Some(o.qty), Some(0.0)));
    // 10 below arrival is -1.67 bps of slippage, plus the 15 bps maker fee,
    // against 25 bps taker plus the modelled spread for a market order.
    let realised = r.realised_cost_bps.unwrap();
    assert!((realised - (15.0 - 10.0 / PX * 1e4)).abs() < 1e-6, "{realised}");
    assert!(r.modelled_cost_bps.unwrap() >= 25.0);
    assert!(e.positions.get(BTC).is_some_and(|p| p.demo && (p.qty - o.qty).abs() < 1e-12));
    assert!(e.inflight.is_empty());
    assert!(journal_has(&e, "filled as maker, resting at our limit 59990"));
    assert!(journal_has(&e, "done: 100% maker"));
}

#[test]
fn a_sell_rests_at_the_best_ask_and_a_marketable_limit_is_taker() {
    let v = Venue::new();
    let mut e = engine();
    let sid = manual(&mut e);
    // A book above the venue's: the "resting" sell crosses and fills better.
    e.place_order(&sid, BTC, Side::Buy, 600.0, RouteIntent::Demo).unwrap();
    let e = cycle(e, &v);
    let b = v.last();
    v.fill(&b.id, b.qty, PX - 10.0);
    let mut e = cycle(e, &v);
    e.place_order(&sid, BTC, Side::Sell, 600.0, RouteIntent::Demo).unwrap();
    let e = cycle(e, &v);
    let s = v.last();
    assert_eq!(s.limit, Some(PX + 10.0), "at the best ask");
    let id = working(&e);
    v.fill(&s.id, s.qty, PX + 25.0);
    let e = cycle(e, &v);
    let r = row(&e, &id);
    assert_eq!(r.status, OrderStatus::Filled);
    assert_eq!((r.maker_qty, r.taker_qty), (Some(0.0), Some(s.qty)), "filled better than the limit: it crossed");
    assert!(journal_has(&e, "was marketable when it arrived"));
}

#[test]
fn an_unfilled_limit_is_repriced_at_the_new_touch_after_the_rest_time() {
    let v = Venue::new();
    let mut e = engine();
    let sid = manual(&mut e);
    e.place_order(&sid, BTC, Side::Buy, 1_200.0, RouteIntent::Demo).unwrap();
    let mut e = cycle(e, &v);
    let first = v.last();
    let id = working(&e);

    // The market moves up; the rest time passes.
    book(&mut e, PX + 40.0, PX + 60.0);
    e.age_inflight_for_test(&id, REST_MS);
    let e = cycle(e, &v); // cancel, read it cancelled, queue the next limit
    assert_eq!(v.cancels(), 1);
    assert_eq!(v.orders().iter().find(|o| o.id == first.id).unwrap().status, BrokerOrderStatus::Canceled);
    let e = cycle(e, &v); // send it
    let second = v.last();
    assert_ne!(second.id, first.id);
    assert_eq!(second.limit, Some(PX + 40.0), "re-priced at the new best bid");
    assert!(!second.ioc);
    assert!((second.qty - first.qty).abs() < 1e-12, "nothing filled, the whole order again");
    assert_eq!(second.cid, format!("{}-m1", first.cid));
    let w = e.maker_work_for_test(&id).unwrap();
    assert_eq!((w.child, w.tries), (Child::Rest, 2));
    assert!(journal_has(&e, "did not fill in 20s"));
    assert_eq!(row(&e, &id).status, OrderStatus::Pending);
}

#[test]
fn after_the_last_try_the_rest_goes_marketable_ioc_then_market_and_the_order_completes() {
    let v = Venue::new();
    v.0.lock().unwrap().ioc_share = 0.5;
    let mut e = engine();
    e.set_maker_route(ALPACA_CRYPTO_DEMO, MakerSettings { enabled: true, rest_sec: 20, max_tries: 2, fallback_band_bps: 50.0 })
        .unwrap();
    let sid = manual(&mut e);
    e.place_order(&sid, BTC, Side::Buy, 1_200.0, RouteIntent::Demo).unwrap();
    let mut e = cycle(e, &v);
    let id = working(&e);
    let qty = v.last().qty;
    for _ in 0..2 {
        e.age_inflight_for_test(&id, REST_MS);
        e = cycle(e, &v); // cancel, queue the next
        e = cycle(e, &v); // send it
    }
    let orders = v.orders();
    // Two resting limits, then the IOC; the IOC filled half and the rest
    // went out as a market order in the same pass as its report.
    assert!(orders[0].limit.is_some() && !orders[0].ioc);
    assert!(orders[1].limit.is_some() && !orders[1].ioc);
    let ioc = &orders[2];
    assert!(ioc.ioc, "the fallback is immediate or cancel");
    // A band past the far side of the book (the ask), rounded up.
    let want = crate::connectors::alpaca::round_crypto_price((PX + 10.0) * 1.005, true);
    assert_eq!(ioc.limit, Some(want));
    let e = cycle(e, &v); // send the market order for the rest
    let orders = v.orders();
    assert_eq!(orders.len(), 4, "bounded: two rests, one IOC, one market order");
    let mkt = &orders[3];
    assert!(mkt.limit.is_none() && !mkt.ioc);
    assert!((mkt.qty - (qty - ioc.filled)).abs() < 1e-6, "only what is still open");
    let r = row(&e, &id);
    assert_eq!(r.status, OrderStatus::Filled);
    assert!((r.filled_qty - (ioc.filled + mkt.filled)).abs() < 1e-9);
    assert_eq!(r.maker_qty, Some(0.0));
    assert!((r.taker_qty.unwrap() - r.filled_qty).abs() < 1e-9);
    // All taker: 25 bps fee plus the 20 paid over arrival.
    assert!((r.realised_cost_bps.unwrap() - (25.0 + 20.0 / PX * 1e4)).abs() < 1e-6);
    assert!(e.inflight.is_empty());
    assert!(e.positions.get(BTC).is_some_and(|p| (p.qty - r.filled_qty).abs() < 1e-9));
}

#[test]
fn partial_fills_carry_over_into_the_next_limit_and_are_booked_once() {
    let v = Venue::new();
    let mut e = engine();
    let sid = manual(&mut e);
    e.place_order(&sid, BTC, Side::Buy, 1_200.0, RouteIntent::Demo).unwrap();
    let e = cycle(e, &v);
    let first = v.last();
    let id = working(&e);
    let qty = first.qty;

    v.fill(&first.id, qty * 0.4, PX - 10.0);
    let e = cycle(e, &v);
    let e = cycle(e, &v); // the same report twice books once
    assert_eq!(row(&e, &id).status, OrderStatus::Partial);
    assert!(e.positions.get(BTC).is_some_and(|p| (p.qty - qty * 0.4).abs() < 1e-12));

    let mut e = e;
    book(&mut e, PX - 5.0, PX + 15.0);
    e.age_inflight_for_test(&id, REST_MS);
    let e = cycle(e, &v);
    let e = cycle(e, &v);
    let second = v.last();
    assert_eq!(second.limit, Some(PX - 5.0));
    assert!((second.qty - qty * 0.6).abs() < 1e-6, "the next limit is for what is still open: {}", second.qty);
    v.fill(&second.id, second.qty, PX - 5.0);
    let e = cycle(e, &v);
    let r = row(&e, &id);
    assert_eq!(r.status, OrderStatus::Filled);
    let total = qty * 0.4 + second.qty;
    assert!((r.filled_qty - total).abs() < 1e-9, "{} vs {total}", r.filled_qty);
    let avg = (qty * 0.4 * (PX - 10.0) + second.qty * (PX - 5.0)) / total;
    assert!((r.avg_fill_price.unwrap() - avg).abs() < 1e-6);
    assert!((r.maker_qty.unwrap() - total).abs() < 1e-9, "both parts rested at their limits");
    let p = e.positions.get(BTC).unwrap();
    assert!((p.qty - total).abs() < 1e-9, "booked once: {} vs {total}", p.qty);
}

#[test]
fn a_restart_follows_the_open_order_and_cancels_an_orphan_from_an_earlier_run() {
    let v = Venue::new();
    let mut e = engine();
    let sid = manual(&mut e);
    e.place_order(&sid, BTC, Side::Buy, 1_200.0, RouteIntent::Demo).unwrap();
    let e = cycle(e, &v);
    let resting = v.last();
    let id = working(&e);
    // An order an earlier run left at the venue, and one the owner placed by hand.
    let orphan = v.rest_unseen("pythia-0badc0de-ord_3", 0.01, 59_000.0);
    let theirs = v.rest_unseen("by-hand", 0.01, 58_000.0);

    let saved = e.to_persisted();
    let mut e2 = engine();
    e2.apply_persisted(serde_json::from_value(serde_json::to_value(&saved).unwrap()).unwrap());
    assert!(e2.maker_work_for_test(&id).is_some(), "the maker state survives the restart");
    let e2 = cycle(e2, &v);
    let status = |id: &str| v.orders().into_iter().find(|o| o.id == id).unwrap().status;
    assert_eq!(status(&orphan), BrokerOrderStatus::Canceled, "nothing here knew it: cancelled");
    assert_eq!(status(&theirs), BrokerOrderStatus::Working, "not sent by Pythia: left alone");
    assert_eq!(status(&resting.id), BrokerOrderStatus::Working, "followed, not cancelled");
    assert!(journal_has(&e2, "Cancelled an open BTC/USD order left from an earlier run (client id pythia-0badc0de-ord_3"));

    // The check runs once per start.
    let e2 = cycle(e2, &v);
    assert_eq!(v.cancels(), 1);
    v.fill(&resting.id, resting.qty, PX - 10.0);
    let e2 = cycle(e2, &v);
    assert_eq!(row(&e2, &id).status, OrderStatus::Filled);
    assert!(e2.positions.get(BTC).is_some_and(|p| (p.qty - resting.qty).abs() < 1e-12));
}

#[test]
fn a_child_queued_before_the_restart_is_adopted_or_sent_again() {
    // Re-priced, and the next limit reached the venue but its answer was lost.
    let v = Venue::new();
    let mut e = engine();
    let sid = manual(&mut e);
    e.place_order(&sid, BTC, Side::Buy, 1_200.0, RouteIntent::Demo).unwrap();
    let mut e = cycle(e, &v);
    let id = working(&e);
    e.age_inflight_for_test(&id, REST_MS);
    let mut e = cycle(e, &v); // cancelled, next queued
    let out = e.drain_live_orders();
    assert_eq!(out.len(), 1);
    let sent = v.rest_unseen(&out[0].client_order_id, out[0].qty, out[0].limit_price.unwrap());

    let mut e2 = engine();
    e2.apply_persisted(serde_json::from_value(serde_json::to_value(e.to_persisted()).unwrap()).unwrap());
    let e2 = cycle(e2, &v);
    assert_eq!(
        v.orders().into_iter().find(|o| o.id == sent).unwrap().status,
        BrokerOrderStatus::Working,
        "adopted by its client id, not cancelled as an orphan"
    );
    v.fill(&sent, out[0].qty, out[0].limit_price.unwrap());
    let e2 = cycle(e2, &v);
    assert_eq!(row(&e2, &id).status, OrderStatus::Filled);

    // The same, but it never reached the venue: the order carries on.
    let v = Venue::new();
    let mut e = engine();
    let sid = manual(&mut e);
    e.place_order(&sid, BTC, Side::Buy, 1_200.0, RouteIntent::Demo).unwrap();
    let mut e = cycle(e, &v);
    let id = working(&e);
    e.age_inflight_for_test(&id, REST_MS);
    let mut e = cycle(e, &v);
    assert_eq!(e.drain_live_orders().len(), 1, "queued, then lost with the process");
    let mut e2 = engine();
    e2.apply_persisted(serde_json::from_value(serde_json::to_value(e.to_persisted()).unwrap()).unwrap());
    let e2 = cycle(e2, &v); // looked up: missing, so the next limit is queued
    let e2 = cycle(e2, &v);
    let next = v.last();
    assert!(next.limit.is_some() && next.cid.ends_with("-m2"), "{}", next.cid);
    assert!(e2.inflight.contains_key(&id));
}

#[test]
fn stopping_the_autopilot_cancels_its_resting_order_and_places_nothing_new() {
    let v = Venue::new();
    let mut e = engine();
    let mut c = AutopilotConfig {
        id: "mk".into(),
        name: "Maker test".into(),
        mode: AutopilotMode::Demo,
        venue: "alpaca".into(),
        asset_class: Some(crate::connectors::Venue::Crypto),
        capital_usd: 5_000.0,
        sleeves: vec![SleeveConfig { strategy_id: "ema-cross-1".into(), weight: 1.0 }],
        stop: StopRules::default(),
        flatten_on_stop: false,
        max_sleeves: None,
        repick_every_hours: None,
    };
    c.flatten_on_stop = false;
    let ap = e.autopilot_start(c, false, VenueCash::NotRead).expect("the autopilot starts");
    e.place_order("ema-cross-1", BTC, Side::Buy, 1_200.0, RouteIntent::Demo).expect("routed");
    let e = cycle(e, &v);
    let resting = v.last();
    let id = working(&e);
    v.fill(&resting.id, resting.qty * 0.25, PX - 10.0);
    let mut e = cycle(e, &v);

    e.autopilot_stop(&ap, Some(false)).unwrap();
    assert!(journal_has(&e, "stands down (autopilot \"Maker test\" stopped)"));
    let e = cycle(e, &v);
    assert_eq!(v.cancels(), 1);
    assert_eq!(v.orders().iter().find(|o| o.id == resting.id).unwrap().status, BrokerOrderStatus::Canceled);
    let e = cycle(e, &v);
    assert_eq!(v.orders().len(), 1, "nothing new is placed after the stop");
    let r = row(&e, &id);
    assert_eq!(r.status, OrderStatus::Partial, "the quarter that filled is kept");
    assert!((r.filled_qty - resting.qty * 0.25).abs() < 1e-12);
    assert!(e.inflight.is_empty());
}

#[test]
fn a_stand_down_before_the_next_limit_is_sent_ends_the_order_at_once() {
    let v = Venue::new();
    let mut e = engine();
    let sid = manual(&mut e);
    e.place_order(&sid, BTC, Side::Buy, 1_200.0, RouteIntent::Demo).unwrap();
    let mut e = cycle(e, &v);
    let id = working(&e);
    e.age_inflight_for_test(&id, REST_MS);
    // Cancel and read, but keep the next limit queued here.
    let m = std::sync::Mutex::new(e);
    let rt = tokio::runtime::Builder::new_current_thread().build().unwrap();
    rt.block_on(crate::execution::poll_inflight(&m, &Src(v.clone())));
    let mut e = m.into_inner().unwrap();
    assert_eq!(e.pending_live.len(), 1);
    let sids: HashSet<String> = [sid.clone()].into_iter().collect();
    e.maker_stand_down_for(&sids, "test");
    assert!(e.pending_live.is_empty(), "the queued limit never goes out");
    assert!(e.inflight.is_empty());
    assert_eq!(row(&e, &id).status, OrderStatus::Cancelled);
    assert_eq!(v.orders().len(), 1);
}

#[test]
fn a_refused_limit_falls_back_to_a_market_order() {
    let v = Venue::new();
    v.0.lock().unwrap().refuse_limits = true;
    let mut e = engine();
    let sid = manual(&mut e);
    e.place_order(&sid, BTC, Side::Buy, 1_200.0, RouteIntent::Demo).unwrap();
    let e = cycle(e, &v); // the limit is refused, a market order queued
    assert!(v.orders().is_empty());
    let id = working(&e);
    let e = cycle(e, &v);
    let o = v.last();
    assert!(o.limit.is_none());
    let r = row(&e, &id);
    assert_eq!(r.status, OrderStatus::Filled);
    assert!(journal_has(&e, "was refused (venue rejected order: 422 invalid limit price)"));
}

#[test]
fn stops_and_other_routes_keep_their_market_orders() {
    // A stop-loss exit never rests.
    let v = Venue::new();
    let mut e = engine();
    let sid = manual(&mut e);
    e.place_order(&sid, BTC, Side::Buy, 1_200.0, RouteIntent::Demo).unwrap();
    let e = cycle(e, &v);
    let b = v.last();
    v.fill(&b.id, b.qty, PX - 10.0);
    let mut e = cycle(e, &v);
    e.close_position(BTC, "stop-loss");
    let out = e.drain_live_orders();
    assert_eq!(out.len(), 1);
    assert!(out[0].limit_price.is_none() && out[0].style == bandit::ExecStyle::Cross, "the exit crosses");

    // The route switched off: market orders as before.
    let mut e = engine();
    e.set_maker_route(ALPACA_CRYPTO_DEMO, MakerSettings { enabled: false, ..MakerSettings::default() }).unwrap();
    let sid = manual(&mut e);
    e.place_order(&sid, BTC, Side::Buy, 1_200.0, RouteIntent::Demo).unwrap();
    let out = e.drain_live_orders();
    assert!(out[0].limit_price.is_none() && out[0].style == bandit::ExecStyle::Cross);

    // A demo exchange with keys of its own (Bybit) is another route: unchanged.
    let mut e = engine();
    e.set_demo_venues([crate::connectors::Venue::Crypto].into_iter().collect(), Some(CostVenue::Bybit), true);
    let sid = manual(&mut e);
    e.place_order(&sid, BTC, Side::Buy, 1_200.0, RouteIntent::Demo).unwrap();
    let out = e.drain_live_orders();
    assert!(out[0].limit_price.is_none() && out[0].style == bandit::ExecStyle::Cross);
    assert!(e.set_maker_route("demo:bybit:crypto", MakerSettings { enabled: true, ..MakerSettings::default() }).is_err());

    // Without a fresh book there is no touch to rest at.
    let mut e = engine();
    e.books.clear();
    let sid = manual(&mut e);
    e.place_order(&sid, BTC, Side::Buy, 1_200.0, RouteIntent::Demo).unwrap();
    assert!(e.drain_live_orders()[0].limit_price.is_none());
}

#[test]
fn the_route_setting_is_saved_and_shown() {
    let mut e = engine();
    assert!(e.state().live.maker_routes[ALPACA_CRYPTO_DEMO].enabled);
    let s = MakerSettings { enabled: true, rest_sec: 45, max_tries: 4, fallback_band_bps: 30.0 };
    e.set_maker_route(ALPACA_CRYPTO_DEMO, s).unwrap();
    let mut e2 = Engine::new();
    e2.apply_persisted(serde_json::from_value(serde_json::to_value(e.to_persisted()).unwrap()).unwrap());
    assert_eq!(e2.maker_routes()[ALPACA_CRYPTO_DEMO], s);
    let v = serde_json::to_value(e2.state()).unwrap();
    assert_eq!(v["live"]["makerRoutes"][ALPACA_CRYPTO_DEMO]["restSec"], 45);
    // A save from before the setting existed gets the default.
    let mut old = serde_json::to_value(e.to_persisted()).unwrap();
    old.as_object_mut().unwrap().remove("maker_routes");
    let mut e3 = Engine::new();
    e3.apply_persisted(serde_json::from_value(old).unwrap());
    assert!(e3.maker_routes()[ALPACA_CRYPTO_DEMO].enabled);
}
