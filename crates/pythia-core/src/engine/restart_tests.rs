//! A restart under a demo autopilot that holds a lab book: the engine is
//! saved, restored with cold estimates (no candles, no books, the volatility
//! model warming up) and run for an hour of engine time with no new lab
//! signal. Nothing may sell the lab book by itself. Deterministic: prices
//! are set by hand and the engine's clock is moved forward by the test.

use super::autopilot::*;
use super::*;
use crate::marketdata::{BarSeries, Ohlc};

const BTC: &str = "crypto:BTC/USD";
const ETH: &str = "crypto:ETH/USD";
const SOL: &str = "crypto:SOL/USD";
const COINS: [&str; 3] = [BTC, ETH, SOL];
const TICK_MS: i64 = 5_000;

fn mark_real(e: &mut Engine) {
    let now = e.now();
    let ids: Vec<String> = e.markets.iter().filter(|m| m.venue == Venue::Crypto).map(|m| m.id.clone()).collect();
    for m in e.markets.iter_mut().filter(|m| m.venue == Venue::Crypto) {
        m.updated_at = now;
    }
    e.real_ids.extend(ids);
}

/// What the host sets up on every boot of the autopilot engine: the Alpaca
/// paper account as the crypto demo route, its listed coins, idle lab books.
fn host_setup(e: &mut Engine) {
    e.set_lab_books_idle(true);
    e.set_demo_venues([Venue::Crypto, Venue::Alpaca].into_iter().collect(), Some(CostVenue::Alpaca), true);
    e.set_crypto_demo_listed(Some(["BTC/USD", "ETH/USD", "SOL/USD"].into_iter().map(String::from).collect()));
    mark_real(e);
}

fn signal(generated: i64) -> crate::lab::LabSignal {
    crate::lab::LabSignal {
        strategy: "tsmom_top20".into(),
        variant: "tsmom_top20".into(),
        as_of_ms: generated - 3_600_000,
        generated_ms: generated,
        valid_until_ms: generated + 36 * 3_600_000,
        quote: "USD".into(),
        weights: [("BTC", 0.3), ("ETH", 0.3), ("SOL", 0.3)].iter().map(|(k, v)| (k.to_string(), *v)).collect(),
        regime_on: Some(true),
        evidence: crate::lab::LabEvidence {
            oos_sharpe: Some(0.54),
            deflated_p: Some(0.97),
            ..Default::default()
        },
        autopilot_only: false,
        dropped: vec![],
        asset_class: None,
    }
}

/// Five-minute candles around `px` that move about 0.3 % a bar: an ATR
/// small enough that an ATR stop sits a few percent under the price.
fn bars(e: &Engine, px: f64) -> Vec<Ohlc> {
    let now = e.now();
    (0..80)
        .map(|i| {
            let c = px * (1.0 + if i % 2 == 0 { 0.003 } else { -0.003 });
            Ohlc { ts: now - (80 - i) * 300_000, open: px, high: c.max(px) * 1.001, low: c.min(px) * 0.999, close: c, volume: 1.0 }
        })
        .collect()
}

fn set_price(e: &mut Engine, market: &str, price: f64) {
    let now = e.now();
    let m = e.markets.iter_mut().find(|m| m.id == market).unwrap();
    m.price = price;
    m.updated_at = now;
}

/// A demo autopilot on the lab book, filled at the venue the way the Alpaca
/// paper account fills it: asynchronously, through `apply_live_update`.
fn holding_engine(trim_mult: f64) -> (Engine, String) {
    let mut e = Engine::new();
    host_setup(&mut e);
    let series: Vec<BarSeries> = COINS
        .iter()
        .map(|id| {
            let px = e.price_of(id);
            let mut b = bars(&e, px);
            // The forming bar, dropped by `apply_bars`.
            b.push(Ohlc { ts: e.now(), open: px, high: px, low: px, close: px, volume: 0.0 });
            BarSeries { id: id.to_string(), bars: b }
        })
        .collect();
    e.apply_bars(&series);
    let now = e.now();
    e.apply_lab_signal(signal(now));
    let cfg = AutopilotConfig {
        id: "top20".into(),
        name: "Top 20".into(),
        mode: AutopilotMode::Demo,
        venue: "alpaca".into(),
        asset_class: Some(Venue::Crypto),
        capital_usd: 99_500.0,
        sleeves: vec![SleeveConfig { strategy_id: "lab:tsmom_top20".into(), weight: 1.0 }],
        stop: StopRules::default(),
        flatten_on_stop: true,
        max_sleeves: None,
        repick_every_hours: None,
    };
    let id = e.autopilot_start(cfg, false, VenueCash::NotRead).expect("the autopilot starts");
    e.run_lab_books();
    let out = e.drain_live_orders();
    assert_eq!(out.len(), 3, "one buy per coin: {out:?}");
    for o in out {
        assert_eq!(o.side, Side::Buy);
        e.apply_live_update(
            &o.order_id,
            LiveUpdate {
                status: BrokerOrderStatus::Filled,
                filled_qty: o.qty,
                avg_price: Some(o.ref_price),
                fee: 0.0,
                fee_base: 0.0,
                fee_unpriced: Vec::new(),
                raw_status: "filled".into(),
            },
        );
    }
    if trim_mult > 0.0 {
        // The spike trim on, with a 10 % target: the book (held to the risk
        // caps at entry) is over twice that on the assumed volatilities of a
        // cold start.
        let mut limits = e.limits.clone();
        limits.vol_spike_trim_mult = trim_mult;
        limits.portfolio_vol_target_pct = 10.0;
        e.set_limits(limits);
    }
    for id in COINS {
        let p = &e.positions[id];
        assert!(p.demo && p.qty > 0.0 && p.strategy_id == "lab:tsmom_top20", "{id}: {}", p.qty);
    }
    (e, id)
}

/// Save, restore into a fresh process: no candles, no books, every
/// estimate cold.
fn restart(e: &Engine) -> Engine {
    let saved = serde_json::to_string(&e.to_persisted()).unwrap();
    let mut r = Engine::new();
    r.apply_persisted(serde_json::from_str(&saved).unwrap());
    host_setup(&mut r);
    r
}

/// An hour of 5-second ticks, with crypto falling `drop` over it the way it
/// did that night. Returns every order sent to the venue.
fn run_hour(e: &mut Engine, drop: f64) -> Vec<LiveOrderOut> {
    let start: HashMap<&str, f64> = COINS.iter().map(|id| (*id, e.price_of(id))).collect();
    let n = 3_600_000 / TICK_MS;
    let mut sent = Vec::new();
    for i in 1..=n {
        e.advance_clock_for_test(TICK_MS);
        let f = 1.0 - drop * i as f64 / n as f64;
        for id in COINS {
            set_price(e, id, start[id] * f);
        }
        e.tick();
        sent.extend(e.drain_live_orders());
    }
    sent
}

/// A fresh two-level book one basis point either side of the price.
fn book(e: &Engine, id: &str) -> crate::orderbook::BookSnapshot {
    let px = e.price_of(id);
    let (bid, ask) = (px * 0.9999, px * 1.0001);
    let quote = crate::orderbook::BookQuote::from_levels(
        CostVenue::Alpaca,
        &[(bid, 10.0), (bid * 0.999, 20.0)],
        &[(ask, 10.0), (ask * 1.001, 20.0)],
        e.now(),
    )
    .unwrap();
    crate::orderbook::BookSnapshot { id: id.into(), quote }
}

fn lab_sells(sent: &[LiveOrderOut]) -> Vec<String> {
    sent.iter()
        .filter(|o| o.side == Side::Sell && o.strategy_id == "lab:tsmom_top20")
        .map(|o| format!("{} {:.6} ({:?})", o.market_id, o.qty, o.style))
        .collect()
}

#[test]
fn a_lab_position_filled_at_the_venue_carries_no_atr_stop() {
    // The lab backtest had no stops, and `place_lab_order` clears them on a
    // paper fill. A demo fill is booked later, when the venue reports it, and
    // used to open the position with the ordinary 8 ATR stop and the 6 ATR
    // trailing stop.
    let (e, _) = holding_engine(0.0);
    for id in COINS {
        let p = &e.positions[id];
        assert_eq!((p.stop, p.target), (0.0, 0.0), "{id} has a stop of {}", p.stop);
    }
}

#[test]
fn a_restart_under_a_lab_autopilot_sells_nothing_in_the_next_hour() {
    let (e, id) = holding_engine(0.0);
    let held: HashMap<String, f64> = COINS.iter().map(|m| (m.to_string(), e.positions[*m].qty)).collect();
    let mut r = restart(&e);
    assert_eq!(r.autopilots[0].state, AutopilotState::Running);
    let sent = run_hour(&mut r, 0.06);
    assert!(lab_sells(&sent).is_empty(), "the restart sold the lab book: {:?}", lab_sells(&sent));
    for (m, q) in &held {
        assert!((r.positions[m].qty - q).abs() < 1e-12, "{m} moved");
    }
    assert_eq!(r.autopilots.iter().find(|a| a.config.id == id).unwrap().state, AutopilotState::Running);
}

#[test]
fn an_old_state_file_with_stops_on_lab_positions_has_them_cleared_on_restore() {
    // The state file from before the fix carries the ATR stops the venue
    // fills gave the lab positions. Restoring it must not arm them.
    let (mut e, _) = holding_engine(0.0);
    for id in COINS {
        let px = e.price_of(id);
        let p = e.positions.get_mut(id).unwrap();
        p.stop = px * 0.97;
        p.trail_ref = px;
    }
    let mut r = restart(&e);
    for id in COINS {
        assert_eq!(r.positions[id].stop, 0.0, "{id}");
    }
    let sent = run_hour(&mut r, 0.06);
    assert!(lab_sells(&sent).is_empty(), "{:?}", lab_sells(&sent));
}

#[test]
fn a_volatility_trim_waits_for_warm_estimates_on_a_lab_book() {
    // With the spike trim switched on, the cold restart has no candles: every
    // coin's volatility is the 5 %-a-day assumption and every pair counts as
    // fully correlated, so the book reads far over its target. That is an
    // assumption, not a spike, and must not sell the lab book.
    let (e, _) = holding_engine(2.0);
    let mut r = restart(&e);
    assert!(r.risk_status().portfolio_vol_pct > 20.0, "cold, the book reads over twice its 10 % target");
    let sent = run_hour(&mut r, 0.0);
    assert!(lab_sells(&sent).is_empty(), "{:?}", lab_sells(&sent));
    assert!(
        r.journal.iter().any(|j| j.kind == JournalKind::Risk && j.message.contains("waits for warm estimates")),
        "the held trim is journaled with its reason"
    );
}

#[test]
fn a_volatility_trim_on_a_warm_lab_book_rests_as_a_maker_order_and_says_why() {
    let (mut e, _) = holding_engine(2.0);
    // Warm: measured candles that swing hard (a real spike) on every coin.
    let series: Vec<BarSeries> = COINS
        .iter()
        .map(|id| {
            let px = e.price_of(id);
            let now = e.now();
            let mut b: Vec<Ohlc> = (0..80)
                .map(|i| {
                    let c = px * (1.0 + if i % 2 == 0 { 0.03 } else { -0.03 });
                    Ohlc { ts: now - (80 - i) * 300_000, open: px, high: c.max(px), low: c.min(px), close: c, volume: 1.0 }
                })
                .collect();
            b.push(Ohlc { ts: now, open: px, high: px, low: px, close: px, volume: 0.0 });
            BarSeries { id: id.to_string(), bars: b }
        })
        .collect();
    // No fresh book: the trim waits rather than crossing the spread.
    let mut sent = Vec::new();
    for _ in 0..(40 * 60_000 / TICK_MS) {
        e.advance_clock_for_test(TICK_MS);
        mark_real(&mut e);
        e.apply_bars(&series);
        e.tick();
        sent.extend(e.drain_live_orders());
    }
    assert!(lab_sells(&sent).is_empty(), "no book to rest a maker order on: {:?}", lab_sells(&sent));
    assert!(e.journal.iter().any(|j| j.kind == JournalKind::Risk && j.message.contains("no fresh order book")));
    // With a book, the trim goes out as a maker limit with its reason.
    for _ in 0..(61 * 60_000 / TICK_MS) {
        e.advance_clock_for_test(TICK_MS);
        mark_real(&mut e);
        e.apply_bars(&series);
        let books: Vec<crate::orderbook::BookSnapshot> = COINS.iter().map(|id| book(&e, id)).collect();
        e.apply_books(&books);
        e.tick();
        sent.extend(e.drain_live_orders());
        if !lab_sells(&sent).is_empty() {
            break;
        }
    }
    let sells: Vec<&LiveOrderOut> = sent.iter().filter(|o| o.side == Side::Sell).collect();
    assert!(!sells.is_empty(), "a warm spike is trimmed");
    assert!(sells.iter().all(|o| o.limit_price.is_some()), "as maker limits: {sells:?}");
    assert!(e.journal.iter().any(|j| j.kind == JournalKind::Risk && j.message.contains("Volatility spike")));
}

#[test]
fn a_sell_never_asks_the_venue_for_more_than_is_held_and_closes_without_dust() {
    // The PEPE refusal: the book held 490974559.154990673, the venue
    // 490974559.154990649. A float of that size carries six decimals, so the
    // engine sends the position rounded down to them, never the book's
    // nine-decimal print of it.
    let mut e = Engine::new();
    host_setup(&mut e);
    let book_qty = 490974559.154990673_f64;
    set_price(&mut e, SOL, 0.00001);
    let m = e.markets.iter().find(|m| m.id == SOL).cloned().unwrap();
    e.positions.insert(
        SOL.into(),
        PositionInternal {
            venue: m.venue,
            symbol: m.symbol.clone(),
            qty: book_qty,
            avg_price: 0.00001,
            strategy_id: "manual".into(),
            stop: 0.0,
            target: 0.0,
            trail_ref: 0.00001,
            live: false,
            demo: true,
        },
    );
    e.flatten(SOL);
    let out = e.drain_live_orders();
    assert_eq!(out.len(), 1, "{out:?}");
    let o = &out[0];
    assert_eq!(o.side, Side::Sell);
    assert!(o.qty <= book_qty);
    let available: f64 = "490974559.154990649".parse().unwrap();
    assert!(o.qty <= available, "{} asks for more than the venue holds", o.qty);
    assert_eq!(crate::connectors::alpaca_crypto::format_qty_plain(o.qty), "490974559.15499");
    // Filled in full: what the rounding left is not a position.
    e.apply_live_update(
        &o.order_id,
        LiveUpdate {
            status: BrokerOrderStatus::Filled,
            filled_qty: o.qty,
            avg_price: Some(0.00001),
            fee: 0.0,
            fee_base: 0.0,
            fee_unpriced: Vec::new(),
            raw_status: "filled".into(),
        },
    );
    assert!(!e.positions.contains_key(SOL), "{:?}", e.positions.get(SOL).map(|p| p.qty));
}

// ── the journal after an incident ──────────────────────────────────────────

#[test]
fn repetitive_notices_are_one_journal_line_a_minute() {
    let mut e = Engine::new();
    let before = e.journal.len();
    // Every 15 seconds for two minutes, the way forecasts settle.
    for i in 0..8 {
        e.log_rollup("settled", 12, |n| format!("{n} outcome forecast(s) settled · track records updated"));
        e.advance_clock_for_test(15_000);
        assert!(e.journal.len() - before <= 1 + i / 4 + 1);
    }
    let lines: Vec<&JournalEntry> = e.journal.iter().filter(|j| j.message.contains("outcome forecast(s) settled")).collect();
    assert!(lines.len() <= 3, "eight notices in two minutes are at most three lines: {}", lines.len());
    assert!(lines.iter().any(|j| j.message.contains("(4x this minute)") || j.message.contains("(3x this minute)")));
    assert!(e.journal.len() - before <= 3);
    assert!(e.events.iter().all(|j| !j.message.contains("settled")), "not an event");
}

#[test]
fn trades_risk_and_rejections_survive_a_flood_and_a_restart_in_the_event_ring() {
    let (mut e, _) = holding_engine(0.0);
    let trades = e.events.iter().filter(|j| j.kind == JournalKind::Order || j.kind == JournalKind::Fill).count();
    assert!(trades > 0, "the venue fills are events");
    // A flood of system notices that turns the journal over completely.
    for i in 0..1_500 {
        e.log(JournalKind::System, format!("Order book feed notice {i}"), None, None);
    }
    assert!(e.state().journal.iter().all(|j| j.kind == JournalKind::System), "the journal view has lost them");
    let kept = e.events.iter().filter(|j| j.kind == JournalKind::Order || j.kind == JournalKind::Fill).count();
    assert_eq!(kept, trades, "the ring has not");
    e.log(JournalKind::Risk, "Trim crypto:SOL/USD by 30%: test".into(), None, Some(SOL.into()));
    e.log(JournalKind::Reject, "Rejected SOL/USD: test".into(), None, Some(SOL.into()));

    let r = restart(&e);
    let ids = |v: &[JournalEntry]| v.iter().map(|j| j.id.clone()).collect::<Vec<_>>();
    assert!(ids(&r.events).ends_with(&ids(&e.events)), "saved in the state file, newest first");
    assert!(e.events[0].message.starts_with("Rejected"));
    let api = serde_json::to_value(r.state_with_events()).unwrap();
    assert_eq!(api["events"].as_array().unwrap().len(), r.events.len(), "exposed in /api/state");
    let tick = serde_json::to_value(r.state()).unwrap();
    assert!(tick.get("events").is_none(), "not pushed with every tick");

    // Capped at EVENT_RING, oldest dropped.
    let mut r = r;
    for i in 0..(EVENT_RING + 10) {
        r.log(JournalKind::Risk, format!("risk {i}"), None, None);
    }
    assert_eq!(r.events.len(), EVENT_RING);
    assert_eq!(r.events[0].message, format!("risk {}", EVENT_RING + 9));
}

#[test]
fn an_order_filled_in_parts_is_one_order_and_one_trade() {
    let (mut e, id) = holding_engine(0.0);
    let st = |e: &Engine| e.autopilot_statuses().into_iter().find(|s| s.config.id == id).unwrap();
    assert_eq!((st(&e).orders, st(&e).trades), (3, 0), "three buys, nothing closed");
    e.flatten(BTC);
    let out = e.drain_live_orders();
    let o = out.iter().find(|o| o.market_id == BTC).unwrap();
    let fill = |status, filled| LiveUpdate {
        status,
        filled_qty: filled,
        // Above the entry: every part realises a profit.
        avg_price: Some(o.ref_price * 1.01),
        fee: 0.0,
        fee_base: 0.0,
        fee_unpriced: Vec::new(),
        raw_status: "x".into(),
    };
    e.apply_live_update(&o.order_id, fill(BrokerOrderStatus::PartiallyFilled, o.qty * 0.3));
    e.apply_live_update(&o.order_id, fill(BrokerOrderStatus::PartiallyFilled, o.qty * 0.7));
    e.apply_live_update(&o.order_id, fill(BrokerOrderStatus::Filled, o.qty));
    assert!(!e.positions.contains_key(BTC));
    assert_eq!((st(&e).orders, st(&e).trades), (4, 1), "three fills of one sell are one order and one closed trade");
    // Counted the same after a restart.
    let r = restart(&e);
    let s = r.autopilot_statuses().into_iter().find(|s| s.config.id == id).unwrap();
    assert_eq!((s.orders, s.trades), (4, 1));
}
