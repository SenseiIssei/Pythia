//! Autopilots side by side: every autopilot is a virtual sub-account with a
//! book of its own (`engine::pos_key`) on one venue account. Two of them hold
//! the same coin, every fill from the shared Alpaca paper account lands in
//! the book of the autopilot whose order it was, the reconciliation compares
//! Alpaca with the sum over every book, a restart keeps the books apart, a
//! save from before books is migrated without a trade, and stopping one
//! autopilot leaves the others exactly as they were. Deterministic: prices
//! are set by hand and the venue's answers are handed in.

use super::autopilot::*;
use super::demo_reconcile::PairStatus;
use super::*;
use crate::marketdata::{BarSeries, Ohlc};

const BTC: &str = "crypto:BTC/USD";
const ETH: &str = "crypto:ETH/USD";
const SOL: &str = "crypto:SOL/USD";

fn mark_real(e: &mut Engine) {
    let now = e.now();
    let ids: Vec<String> = e.markets.iter().filter(|m| m.symbol.contains('/')).map(|m| m.id.clone()).collect();
    for m in e.markets.iter_mut().filter(|m| m.symbol.contains('/')) {
        m.updated_at = now;
    }
    e.real_ids.extend(ids);
}

/// Real, fresh crypto prices; paper autopilots.
fn engine() -> Engine {
    let mut e = Engine::new();
    mark_real(&mut e);
    e
}

/// What the autopilot engine runs with: crypto demo orders on the Alpaca
/// paper account, idle lab books, market orders (maker execution off, so a
/// test does not have to hand in order books).
fn host_setup(e: &mut Engine) {
    e.set_lab_books_idle(true);
    e.set_demo_venues([Venue::Crypto, Venue::Alpaca].into_iter().collect(), Some(CostVenue::Alpaca), true);
    e.set_maker_route(maker::ALPACA_CRYPTO_DEMO, maker::MakerSettings::default()).unwrap();
    mark_real(e);
}

fn demo_engine() -> Engine {
    let mut e = Engine::new();
    host_setup(&mut e);
    e
}

fn config(id: &str, capital: f64, sleeves: &[&str]) -> AutopilotConfig {
    AutopilotConfig {
        id: id.into(),
        name: format!("AP {id}"),
        mode: AutopilotMode::Paper,
        venue: "kraken".into(),
        asset_class: None,
        capital_usd: capital,
        sleeves: sleeves.iter().map(|s| SleeveConfig { strategy_id: s.to_string(), weight: 1.0 }).collect(),
        stop: StopRules::default(),
        flatten_on_stop: true,
        max_sleeves: None,
        repick_every_hours: None,
        portfolio: false,
    }
}

/// A demo autopilot on the Alpaca paper account (crypto).
fn demo_config(id: &str, capital: f64, sleeves: &[&str]) -> AutopilotConfig {
    let mut c = config(id, capital, sleeves);
    c.mode = AutopilotMode::Demo;
    c.venue = "alpaca".into();
    c.asset_class = Some(Venue::Crypto);
    c
}

fn start(e: &mut Engine, c: AutopilotConfig) -> String {
    e.autopilot_start(c, false, VenueCash::NotRead).expect("the autopilot starts")
}

fn status(e: &Engine, id: &str) -> AutopilotStatus {
    e.autopilot_statuses().into_iter().find(|s| s.config.id == id).expect("the autopilot exists")
}

fn idx(e: &Engine, sid: &str) -> usize {
    e.strategies.iter().position(|s| s.id == sid).unwrap()
}

fn market(e: &Engine, id: &str) -> Market {
    e.markets.iter().find(|m| m.id == id).cloned().unwrap()
}

fn buy_intent(market: &str) -> strategies::SignalIntent {
    strategies::SignalIntent { market_id: market.into(), side: Side::Buy, size: 1.0, confidence: 1.0, reason: "test".into() }
}

/// A full-strength buy signal of `sid` on `market`, for the autopilot `book`.
fn signal_in(e: &mut Engine, book: &str, sid: &str, market_id: &str) {
    let i = idx(e, sid);
    let m = market(e, market_id);
    e.place_from_intent(book, i, &m, &buy_intent(market_id));
}

fn qty_in(e: &Engine, book: &str, market: &str) -> f64 {
    e.positions.get(&pos_key(book, market)).map(|p| p.qty).unwrap_or(0.0)
}

fn set_price(e: &mut Engine, market: &str, price: f64) {
    let now = e.now();
    let m = e.markets.iter_mut().find(|m| m.id == market).unwrap();
    m.price = price;
    m.updated_at = now;
}

fn filled(qty: f64, px: f64, fee: f64) -> LiveUpdate {
    LiveUpdate {
        status: BrokerOrderStatus::Filled,
        filled_qty: qty,
        avg_price: Some(px),
        fee,
        fee_base: 0.0,
        fee_unpriced: Vec::new(),
        raw_status: "filled".into(),
    }
}

fn journal_has(e: &Engine, needle: &str) -> bool {
    e.journal.iter().any(|j| j.message.contains(needle))
}

fn lab_signal(strategy: &str, generated: i64, weights: &[(&str, f64)]) -> crate::lab::LabSignal {
    crate::lab::LabSignal {
        strategy: strategy.into(),
        variant: strategy.into(),
        as_of_ms: generated - 3_600_000,
        generated_ms: generated,
        valid_until_ms: generated + 36 * 3_600_000,
        quote: "USD".into(),
        weights: weights.iter().map(|(k, v)| (k.to_string(), *v)).collect(),
        regime_on: Some(true),
        evidence: crate::lab::LabEvidence { oos_sharpe: Some(0.8), deflated_p: Some(0.97), ..Default::default() },
        autopilot_only: false,
        dropped: vec![],
        asset_class: None,
        experimental: false,
    }
}

// ── two autopilots, one coin ───────────────────────────────────────────────

#[test]
fn two_autopilots_hold_the_same_coin_each_in_its_own_book() {
    let mut e = engine();
    let a = start(&mut e, config("a", 10_000.0, &["ema-cross-1"]));
    let b = start(&mut e, config("b", 4_000.0, &["ema-cross-1"]));
    // Both run the strategy on BTC: the markets are not taken by the first.
    for id in [&a, &b] {
        assert!(status(&e, id).by_sleeve[0].markets.contains(&BTC.to_string()), "{id} trades BTC");
    }
    assert_eq!(e.entry_books("ema-cross-1"), vec![a.clone(), b.clone()], "one signal is an entry for each of them");
    assert_eq!(e.entry_books("multi-tf-1"), vec![String::new()], "a strategy no autopilot runs trades the main book");

    let cash0 = e.cash;
    signal_in(&mut e, &a, "ema-cross-1", BTC);
    signal_in(&mut e, &b, "ema-cross-1", BTC);
    let (qa, qb) = (qty_in(&e, &a, BTC), qty_in(&e, &b, BTC));
    assert!(qa > 0.0 && qb > 0.0, "both hold BTC: {qa} and {qb}");
    assert!((qa / qb - 2.5).abs() < 0.01, "each sized from its own capital (10,000 against 4,000): {}", qa / qb);
    assert_eq!(qty_in(&e, "", BTC), 0.0, "and the main book holds none");
    let sa = status(&e, &a);
    let sb = status(&e, &b);
    assert_eq!((sa.open_positions, sb.open_positions), (1, 1));
    assert!(sa.fees > 0.0 && sb.fees > 0.0 && (sa.fees / sb.fees - 2.5).abs() < 0.01, "each pays its own fees");
    // Its own cash: what its equity holds beyond its position.
    let px = e.price_of(BTC);
    assert!((sa.cash - (sa.equity - qa * px)).abs() < 1e-6, "{}", sa.cash);
    // The account pays for both, once each.
    let spent = cash0 - e.cash;
    assert!((spent - (10_000.0 - sa.cash) - (4_000.0 - sb.cash)).abs() < 1e-6, "the account's cash is the sum: {spent}");

    // A move of BTC moves each by its own quantity.
    set_price(&mut e, BTC, px * 1.1);
    let (ea, eb) = (status(&e, &a).equity, status(&e, &b).equity);
    assert!((ea - sa.equity - qa * px * 0.1).abs() < 1e-6);
    assert!((eb - sb.equity - qb * px * 0.1).abs() < 1e-6);

    // The Positions page sees two rows, one per book, with whose they are.
    let rows: Vec<PositionView> = e.state().positions.into_iter().filter(|p| p.market_id == BTC).collect();
    assert_eq!(rows.len(), 2);
    let ra = rows.iter().find(|r| r.book.as_deref() == Some(a.as_str())).unwrap();
    assert_eq!((ra.key.as_str(), ra.book_name.as_deref()), (pos_key(&a, BTC).as_str(), Some("AP a")));
    let order = e.orders.iter().find(|o| o.book.as_deref() == Some(b.as_str())).expect("the order row names its book");
    assert_eq!(order.market_id, BTC);
}

#[test]
fn a_flatten_by_key_closes_one_book_and_a_market_id_closes_them_all() {
    let mut e = engine();
    let a = start(&mut e, config("a", 10_000.0, &["ema-cross-1"]));
    let b = start(&mut e, config("b", 10_000.0, &["ema-cross-1"]));
    signal_in(&mut e, &a, "ema-cross-1", BTC);
    signal_in(&mut e, &b, "ema-cross-1", BTC);
    let qb = qty_in(&e, &b, BTC);
    e.flatten(&pos_key(&a, BTC));
    assert_eq!(qty_in(&e, &a, BTC), 0.0);
    assert_eq!(qty_in(&e, &b, BTC), qb, "the other book untouched");
    assert_eq!((status(&e, &a).trades, status(&e, &b).trades), (1, 0), "the close is booked to its own autopilot");
    assert!(journal_has(&e, "Flattened crypto:BTC/USD (autopilot \"AP a\")"));
    e.flatten(BTC);
    assert_eq!(qty_in(&e, &b, BTC), 0.0, "a bare market id closes every book there");
}

// ── the shared Alpaca paper account ────────────────────────────────────────

#[test]
fn fills_from_the_shared_paper_account_are_booked_to_the_autopilot_whose_order_it_was() {
    let mut e = demo_engine();
    let a = start(&mut e, demo_config("a", 10_000.0, &["ema-cross-1"]));
    let b = start(&mut e, demo_config("b", 5_000.0, &["ema-cross-1"]));
    signal_in(&mut e, &a, "ema-cross-1", BTC);
    signal_in(&mut e, &b, "ema-cross-1", BTC);
    let out = e.drain_live_orders();
    assert_eq!(out.len(), 2, "each autopilot sends its own order to the one account: {out:?}");
    assert!(out.iter().all(|o| o.demo && o.market_id == BTC && o.side == Side::Buy));
    assert!(e.in_flight_markets.contains(&pos_key(&a, BTC)) && e.in_flight_markets.contains(&pos_key(&b, BTC)));
    let book_of = |e: &Engine, o: &LiveOrderOut| e.orders.iter().find(|r| r.id == o.order_id).and_then(|r| r.book.clone()).unwrap();
    let (oa, ob) = if book_of(&e, &out[0]) == a { (&out[0], &out[1]) } else { (&out[1], &out[0]) };
    assert_eq!(book_of(&e, ob), b);

    // The venue fills them in the other order, at other prices and fees.
    let px = e.price_of(BTC);
    e.apply_live_ack(&ob.order_id, "alp-b");
    e.apply_live_ack(&oa.order_id, "alp-a");
    e.apply_live_update(&ob.order_id, filled(ob.qty, px * 1.002, 0.7));
    e.apply_live_update(&oa.order_id, filled(oa.qty, px * 0.999, 1.3));
    let (pa, pb) = (&e.positions[&pos_key(&a, BTC)], &e.positions[&pos_key(&b, BTC)]);
    assert!((pa.qty - oa.qty).abs() < 1e-12 && (pa.avg_price - px * 0.999).abs() < 1e-9 && pa.demo);
    assert!((pb.qty - ob.qty).abs() < 1e-12 && (pb.avg_price - px * 1.002).abs() < 1e-9 && pb.demo);
    let (sa, sb) = (status(&e, &a), status(&e, &b));
    assert!((sa.fees - 1.3).abs() < 1e-9 && (sb.fees - 0.7).abs() < 1e-9, "each fee to its own: {} {}", sa.fees, sb.fees);
    assert_eq!((sa.orders, sb.orders), (1, 1));
    assert!(e.in_flight_markets.is_empty());

    // An exit of one book sells that book's coins, not the account's.
    e.flatten(&pos_key(&b, BTC));
    let sell = e.drain_live_orders().pop().expect("b's close");
    assert!(sell.side == Side::Sell && (sell.qty - ob.qty).abs() < 1e-9, "b sells what b holds: {} of {}", sell.qty, ob.qty);
}

#[test]
fn the_paper_account_reconcile_compares_alpaca_with_the_sum_over_every_book() {
    let mut e = demo_engine();
    let a = start(&mut e, demo_config("a", 10_000.0, &["ema-cross-1"]));
    let b = start(&mut e, demo_config("b", 5_000.0, &["ema-cross-1"]));
    signal_in(&mut e, &a, "ema-cross-1", BTC);
    signal_in(&mut e, &b, "ema-cross-1", BTC);
    let px = e.price_of(BTC);
    for (o, n) in e.drain_live_orders().into_iter().zip(1..) {
        e.apply_live_ack(&o.order_id, &format!("alp-{n}"));
        e.apply_live_update(&o.order_id, filled(o.qty, px, 0.0));
    }
    let (qa, qb) = (qty_in(&e, &a, BTC), qty_in(&e, &b, BTC));
    let venue = |q: f64| vec![BrokerPosition { symbol: "BTC/USD".into(), qty: q, avg_price: px, market_value: q * px }];

    // Alpaca holds the sum: agreed, nothing changes.
    assert_eq!(e.apply_demo_reconcile(&venue(qa + qb), &[]), 0);
    let c = e.demo_reconcile().unwrap().pairs.into_iter().find(|p| p.symbol == "BTC/USD").unwrap();
    assert_eq!(c.status, PairStatus::Ok);
    assert!((c.pythia - (qa + qb)).abs() < 1e-12 && c.markets.len() == 2, "{c:?}");

    // Alpaca holds 10 % less than the sum (no fee watch can explain it): the
    // venue wins, each book takes its share, each autopilot's equity is the
    // same just before and just after.
    e.alpaca_fees.clear();
    let (ea, eb) = (status(&e, &a).equity, status(&e, &b).equity);
    let short = (qa + qb) * 0.9;
    assert_eq!(e.apply_demo_reconcile(&venue(short), &[]), 0, "settled, not a mismatch");
    let c = e.demo_reconcile().unwrap().pairs.into_iter().find(|p| p.symbol == "BTC/USD").unwrap();
    assert_eq!(c.status, PairStatus::Corrected, "{}", c.note);
    assert!(c.note.contains("2 books hold"), "{}", c.note);
    assert!((qty_in(&e, &a, BTC) - qa * 0.9).abs() < 1e-12 && (qty_in(&e, &b, BTC) - qb * 0.9).abs() < 1e-12);
    assert!((status(&e, &a).equity - ea).abs() < 1e-6 && (status(&e, &b).equity - eb).abs() < 1e-6);
    assert!(journal_has(&e, "AP a\": BTC/USD corrected against Alpaca paper"));
    assert!(journal_has(&e, "AP b\": BTC/USD corrected against Alpaca paper"));
}

#[test]
fn an_order_of_another_book_on_the_other_side_of_the_symbol_waits_for_it() {
    // Two books, one account: a buy of one resting while the other sells
    // could meet at the venue (Alpaca refuses that as a potential wash trade).
    let mut e = demo_engine();
    let a = start(&mut e, demo_config("a", 10_000.0, &["ema-cross-1"]));
    let b = start(&mut e, demo_config("b", 10_000.0, &["ema-cross-1"]));
    signal_in(&mut e, &a, "ema-cross-1", BTC);
    let oa = e.drain_live_orders().pop().unwrap();
    e.apply_live_ack(&oa.order_id, "alp-a");
    e.apply_live_update(&oa.order_id, filled(oa.qty, e.price_of(BTC), 0.0));
    signal_in(&mut e, &b, "ema-cross-1", BTC);
    let ob = e.drain_live_orders().pop().unwrap();
    e.apply_live_ack(&ob.order_id, "alp-b");

    // a stops while b's buy is still at the venue: a's sell waits, and says why.
    e.autopilot_stop(&a, None).unwrap();
    assert!(e.drain_live_orders().is_empty(), "no sell next to b's working buy");
    assert!(journal_has(&e, "the two could meet as a wash trade"));
    assert_eq!(status(&e, &a).open_positions, 1, "still a's, to be closed");
    // A demo position needs no live routing: the stop says what it waits for.
    let said = status(&e, &a).last_action.unwrap_or_default();
    assert!(!said.contains("real position"), "{said}");
    assert!(said.contains("1 position(s) wait for another autopilot's order in the same coin"), "{said}");
    // While it waits, no "Exit" is claimed at every tick.
    let now = e.now();
    for _ in 0..3 {
        e.autopilot_step(now);
    }
    assert!(e.drain_live_orders().is_empty());
    assert!(!journal_has(&e, "Exit crypto:BTC/USD"), "nothing went out, so no exit is claimed");
    // b's buy fills; the next step closes a.
    e.apply_live_update(&ob.order_id, filled(ob.qty, e.price_of(BTC), 0.0));
    let now = e.now();
    e.autopilot_step(now);
    let out = e.drain_live_orders();
    assert_eq!(out.len(), 1, "{out:?}");
    assert_eq!(out[0].side, Side::Sell);
    assert!((qty_in(&e, &b, BTC) - ob.qty).abs() < 1e-12, "b untouched");
}

// ── capital on the shared paper account ────────────────────────────────────

#[test]
fn demo_autopilots_together_never_get_more_than_the_paper_account_holds() {
    let mut e = demo_engine();
    let read = |x: f64| VenueCash::Read(x);
    assert!(e.autopilot_needs_paper_equity(Some(&demo_config("x", 1.0, &["ema-cross-1"])), None));
    assert!(!e.autopilot_needs_paper_equity(Some(&config("x", 1.0, &["ema-cross-1"])), None), "paper is the engine's own account");

    e.autopilot_start(demo_config("a", 30_000.0, &["ema-cross-1"]), false, read(50_000.0)).unwrap();
    let err = e.autopilot_start(demo_config("b", 30_000.0, &["multi-tf-1"]), false, read(50_000.0)).unwrap_err();
    assert!(
        err.contains("The Alpaca paper account holds $50,000.00, of which $30,000.00 is already given to the other demo autopilots on it, so $20,000.00 is left, not $30,000.00"),
        "{err}"
    );
    assert!(err.contains("Lower another autopilot's amount"), "{err}");
    let err = e.autopilot_start(demo_config("b", 1_000.0, &["multi-tf-1"]), false, VenueCash::Failed("timeout".into())).unwrap_err();
    assert!(err.contains("Could not read the Alpaca paper account (timeout)"), "{err}");
    e.autopilot_start(demo_config("b", 20_000.0, &["multi-tf-1"]), false, read(50_000.0)).unwrap();

    // Full now. Lowering a's amount frees room for a third.
    let err = e.autopilot_start(demo_config("c", 15_000.0, &["ema-cross-1"]), false, read(50_000.0)).unwrap_err();
    assert!(err.contains("so $0.00 is left"), "{err}");
    let upd = AutopilotUpdate { capital_usd: Some(10_000.0), ..Default::default() };
    e.autopilot_update("a", upd, false, VenueCash::NotRead).unwrap();
    e.autopilot_start(demo_config("c", 15_000.0, &["ema-cross-1"]), false, read(50_000.0)).unwrap();
    // And a raise is checked the same way, against the others.
    let upd = AutopilotUpdate { capital_usd: Some(16_000.0), ..Default::default() };
    let err = e.autopilot_update("a", upd.clone(), false, read(50_000.0)).unwrap_err();
    assert!(err.contains("so $15,000.00 is left, not $16,000.00"), "{err}");
    assert!(e.autopilot_needs_paper_equity(None, Some("a")));
    let upd = AutopilotUpdate { capital_usd: Some(15_000.0), ..Default::default() };
    e.autopilot_update("a", upd, false, read(50_000.0)).unwrap();
}

// ── one lab book in several autopilots ─────────────────────────────────────

#[test]
fn one_lab_book_runs_in_two_autopilots_each_with_its_own_money() {
    let mut e = demo_engine();
    let now = e.now();
    e.apply_lab_signal(lab_signal("tsmom_tranches", now, &[("BTC", 0.5), ("ETH", 0.25)]));
    let a = start(&mut e, demo_config("a", 10_000.0, &["lab:tsmom_tranches"]));
    let b = start(&mut e, demo_config("b", 2_000.0, &["lab:tsmom_tranches"]));
    assert!(journal_has(&e, "Also running in other autopilots, each in its own book: Lab · tsmom_tranches (also in \"AP a\")"));
    e.run_lab_books();
    let px_btc = e.price_of(BTC);
    let out = e.drain_live_orders();
    assert_eq!(out.len(), 4, "two coins for each of them: {out:?}");
    for (o, n) in out.iter().zip(1..) {
        e.apply_live_ack(&o.order_id, &format!("alp-{n}"));
        e.apply_live_update(&o.order_id, filled(o.qty, o.ref_price, 0.0));
    }
    assert!((qty_in(&e, &a, BTC) * px_btc - 5_000.0).abs() < 60.0, "half of a's 10,000");
    assert!((qty_in(&e, &b, BTC) * px_btc - 1_000.0).abs() < 15.0, "half of b's 2,000");
    assert!(e.lab_done.contains_key(&pos_key(&a, "lab:tsmom_tranches")) && e.lab_done.contains_key(&pos_key(&b, "lab:tsmom_tranches")));
    // Done for this signal in both: nothing more goes out.
    e.run_lab_books();
    assert!(e.drain_live_orders().is_empty());

    // Stopping a closes a's book only; b keeps running the lab book and
    // follows its next signal in its own book.
    let qb = qty_in(&e, &b, BTC);
    e.autopilot_stop(&a, None).unwrap();
    let closes = e.drain_live_orders();
    assert_eq!(closes.len(), 2);
    assert!(closes.iter().all(|o| o.side == Side::Sell));
    assert!(closes.iter().all(|o| e.in_flight_markets.contains(&pos_key(&a, &o.market_id))), "a's own positions");
    assert_eq!(qty_in(&e, &b, BTC), qb);
    assert_eq!(status(&e, &b).state, AutopilotState::Running);
    assert_eq!(e.strategy_config("lab:tsmom_tranches").unwrap().state, StrategyState::Paper, "still claimed by b");
    assert!(journal_has(&e, "Still running for the other autopilots, which are untouched: Lab · tsmom_tranches (in \"AP b\")"));
    for (o, n) in closes.iter().zip(10..) {
        e.apply_live_ack(&o.order_id, &format!("alp-{n}"));
        e.apply_live_update(&o.order_id, filled(o.qty, o.ref_price, 0.0));
    }
    e.apply_lab_signal(lab_signal("tsmom_tranches", now + 1, &[("SOL", 0.5)]));
    e.run_lab_books();
    let out = e.drain_live_orders();
    assert!(!out.is_empty() && out.iter().all(|o| e.in_flight_markets.contains(&pos_key(&b, &o.market_id))), "b alone rebalances");
    assert!(out.iter().any(|o| o.market_id == SOL && o.side == Side::Buy));
}

#[test]
fn a_small_demo_book_names_orders_under_alpacas_minimum_instead_of_sending_them() {
    // The safe account: $95 on Alpaca paper. 6 % in BTC is a $5.70 order,
    // which Alpaca refuses (403, "cost basis must be >= minimal amount of
    // order 10"); it is named once and not sent, the rest goes out.
    let mut e = demo_engine();
    let now = e.now();
    e.apply_lab_signal(lab_signal("tsmom_regime", now, &[("BTC", 0.06), ("ETH", 0.30)]));
    let id = start(&mut e, demo_config("safe", 95.0, &["lab:tsmom_regime"]));
    e.run_lab_books();
    let out = e.drain_live_orders();
    assert_eq!(out.len(), 1, "{out:?}");
    assert_eq!(out[0].market_id, ETH);
    assert!(journal_has(&e, "under the venue's minimum order of $10, so not sent and left as they are: BTC/USD ($5.70)"));
    assert!(e.lab_done.contains_key(&pos_key(&id, "lab:tsmom_regime")), "the rebalance is done, not retried");
    e.run_lab_books();
    assert!(e.drain_live_orders().is_empty());
    // On paper the floor stays at $5: nothing to name there.
    let mut p = engine();
    p.set_lab_books_idle(true);
    p.apply_lab_signal(lab_signal("tsmom_regime", now, &[("BTC", 0.06), ("ETH", 0.30)]));
    start(&mut p, config("paper", 95.0, &["lab:tsmom_regime"]));
    p.run_lab_books();
    assert!(!journal_has(&p, "under the venue's minimum order"));
}

// ── stop, restart, migration ───────────────────────────────────────────────

#[test]
fn rounding_dust_left_in_a_stopped_book_is_written_off_once() {
    let mut e = engine();
    let a = start(&mut e, config("a", 10_000.0, &["ema-cross-1"]));
    signal_in(&mut e, &a, "ema-cross-1", BTC);
    // What a sale rounded to the venue's decimals leaves: billionths of a coin.
    e.positions.get_mut(&pos_key(&a, BTC)).unwrap().qty = 3e-9;
    let orders = e.orders.len();
    e.autopilot_stop(&a, None).unwrap();
    assert_eq!(qty_in(&e, &a, BTC), 0.0);
    assert_eq!(e.orders.len(), orders, "nothing to sell");
    assert!(journal_has(&e, "written off"));
    assert!(!journal_has(&e, "Exit crypto:BTC/USD"));
    let s = status(&e, &a);
    assert_eq!((s.state, s.open_positions), (AutopilotState::Stopped, 0));
}

#[test]
fn stopping_one_autopilot_leaves_the_other_untouched() {
    let mut e = engine();
    let a = start(&mut e, config("a", 10_000.0, &["ema-cross-1"]));
    let b = start(&mut e, config("b", 10_000.0, &["ema-cross-1"]));
    for id in [&a, &b] {
        signal_in(&mut e, id, "ema-cross-1", BTC);
        signal_in(&mut e, id, "ema-cross-1", ETH);
    }
    let before = status(&e, &b);
    let held_b = (qty_in(&e, &b, BTC), qty_in(&e, &b, ETH));
    e.autopilot_stop(&a, None).unwrap();
    assert_eq!((qty_in(&e, &a, BTC), qty_in(&e, &a, ETH)), (0.0, 0.0), "a flattened its own book");
    assert_eq!((qty_in(&e, &b, BTC), qty_in(&e, &b, ETH)), held_b, "b's positions are exactly as they were");
    let after = status(&e, &b);
    assert_eq!(after.state, AutopilotState::Running);
    assert_eq!((after.trades, after.orders, after.open_positions), (before.trades, before.orders, before.open_positions));
    assert!((after.fees - before.fees).abs() < 1e-12 && (after.equity - before.equity).abs() < 1e-9);
    assert_eq!(e.strategy_config("ema-cross-1").unwrap().state, StrategyState::Paper, "b still runs it");
    assert!(e.autopilot_entry_allowed(&b, "ema-cross-1", SOL));
    // And when b stops too, the strategy is paused.
    e.autopilot_stop(&b, None).unwrap();
    assert_eq!(e.strategy_config("ema-cross-1").unwrap().state, StrategyState::Paused);
    assert!(e.positions.is_empty());
}

#[test]
fn a_restart_keeps_every_book_apart() {
    let mut e = demo_engine();
    let a = start(&mut e, demo_config("a", 10_000.0, &["ema-cross-1"]));
    let b = start(&mut e, demo_config("b", 5_000.0, &["ema-cross-1"]));
    signal_in(&mut e, &a, "ema-cross-1", BTC);
    signal_in(&mut e, &b, "ema-cross-1", BTC);
    let out = e.drain_live_orders();
    // a's fills; b's order is still at the venue when the process stops.
    let (oa, ob) = {
        let book = |o: &LiveOrderOut| e.orders.iter().find(|r| r.id == o.order_id).and_then(|r| r.book.clone()).unwrap();
        if book(&out[0]) == a { (out[0].clone(), out[1].clone()) } else { (out[1].clone(), out[0].clone()) }
    };
    e.apply_live_ack(&oa.order_id, "alp-a");
    e.apply_live_ack(&ob.order_id, "alp-b");
    e.apply_live_update(&oa.order_id, filled(oa.qty, e.price_of(BTC), 0.5));
    let (sa, sb) = (status(&e, &a), status(&e, &b));

    let saved = serde_json::to_string(&e.to_persisted()).unwrap();
    assert!(saved.contains(&format!("\"{a}|{BTC}\"")), "saved under the book's key");
    let mut r = Engine::new();
    r.apply_persisted(serde_json::from_str(&saved).unwrap());
    host_setup(&mut r);
    assert!(!r.journal.iter().any(|j| j.message.contains("now keeps a book of its own")), "nothing to migrate in a save with books");
    let (ra, rb) = (status(&r, &a), status(&r, &b));
    assert!((ra.equity - sa.equity).abs() < 1e-9 && (rb.equity - sb.equity).abs() < 1e-9);
    assert_eq!((ra.open_positions, rb.open_positions), (1, 0));
    assert!((qty_in(&r, &a, BTC) - oa.qty).abs() < 1e-12 && r.positions[&pos_key(&a, BTC)].demo);
    assert!(r.in_flight_markets.contains(&pos_key(&b, BTC)), "b's order is followed again, in b's book");
    // b's order fills after the restart: b's, not a's.
    r.apply_live_update(&ob.order_id, filled(ob.qty, r.price_of(BTC), 0.25));
    assert!((qty_in(&r, &b, BTC) - ob.qty).abs() < 1e-12);
    assert!((qty_in(&r, &a, BTC) - oa.qty).abs() < 1e-12);
    assert!((status(&r, &b).fees - 0.25).abs() < 1e-12 && (status(&r, &a).fees - 0.5).abs() < 1e-12);
}

/// The live autopilot as it was saved before books existed: one autopilot on
/// the whole Alpaca paper account with three lab books netted per coin, its
/// coins in the one shared book under their market ids, `owned` naming them.
fn old_style_save() -> (serde_json::Value, String, usize, String) {
    let mut e = demo_engine();
    let now = e.now();
    e.apply_lab_signal(lab_signal("breakout_top10", now, &[("BTC", 0.2), ("ETH", 0.1), ("SOL", 0.1), ("ADA", 0.05), ("DOT", 0.05)]));
    e.apply_lab_signal(lab_signal("tsmom_tranches", now, &[("BTC", 0.1), ("LINK", 0.1), ("AVAX", 0.05), ("XRP", 0.05), ("LTC", 0.05)]));
    e.apply_lab_signal(lab_signal("tsmom_regime", now, &[("DOGE", 0.05), ("BCH", 0.05), ("TRX", 0.05), ("SUI", 0.05), ("NEAR", 0.05), ("ATOM", 0.05), ("UNI", 0.05)]));
    let id = start(
        &mut e,
        demo_config("ap_29742", 95_000.0, &["lab:breakout_top10", "lab:tsmom_tranches", "lab:tsmom_regime"]),
    );
    e.run_lab_books();
    let out = e.drain_live_orders();
    assert!(out.len() >= 15, "about fifteen coins: {}", out.len());
    // All but the last fill; the last is still at the venue.
    let pending = out.last().unwrap().order_id.clone();
    for (o, n) in out.iter().zip(1..) {
        e.apply_live_ack(&o.order_id, &format!("alp-{n}"));
        if o.order_id != pending {
            e.apply_live_update(&o.order_id, filled(o.qty, o.ref_price, 0.0));
        }
    }
    let held = status(&e, &id).open_positions;
    // Rewrite the save the way the old engine wrote it.
    let mut v = serde_json::to_value(e.to_persisted()).unwrap();
    for entry in v["positions"].as_array_mut().unwrap() {
        let pair = entry.as_array_mut().unwrap();
        let market = split_key(pair[0].as_str().unwrap()).1.to_string();
        pair[0] = serde_json::Value::String(market);
        let o = pair[1].as_object_mut().unwrap();
        o.remove("book");
        o.remove("market_id");
    }
    for entry in v["inflight"].as_array_mut().unwrap() {
        entry.as_array_mut().unwrap()[1].as_object_mut().unwrap().remove("book");
    }
    for w in v["alpaca_fees"].as_array_mut().unwrap() {
        w.as_object_mut().unwrap().remove("book");
    }
    for o in v["orders"].as_array_mut().unwrap() {
        o.as_object_mut().unwrap().remove("book");
    }
    let done = v["lab_done"].as_object().unwrap().clone();
    let old: serde_json::Map<String, serde_json::Value> =
        done.into_iter().map(|(k, val)| (split_key(&k).1.to_string(), val)).collect();
    v["lab_done"] = serde_json::Value::Object(old);
    let refs = v["ref_prices"].as_object().unwrap().clone();
    v["ref_prices"] = serde_json::Value::Object(refs.into_iter().map(|(k, val)| (split_key(&k).1.to_string(), val)).collect());
    let text = v.to_string();
    assert!(!text.contains("ap_29742|"), "no book keys left: the old format");
    (v, id, held, pending)
}

#[test]
fn an_old_save_moves_the_running_autopilot_into_its_own_book_without_a_trade() {
    let (v, id, held, pending) = old_style_save();
    assert!(held >= 14, "{held} positions held");
    let mut r = Engine::new();
    r.apply_persisted(serde_json::from_value(v.clone()).unwrap());
    host_setup(&mut r);

    // Every position is in the autopilot's book, exactly as it was.
    let s = status(&r, &id);
    assert_eq!(s.state, AutopilotState::Running);
    assert_eq!(s.open_positions, held);
    assert!(r.positions.values().all(|p| p.book == id && p.demo), "nothing left in the main book");
    assert_eq!(r.positions.len(), held);
    let old_positions = v["positions"].as_array().unwrap();
    for entry in old_positions {
        let market = entry[0].as_str().unwrap();
        let p = &r.positions[&pos_key(&id, market)];
        assert_eq!(p.qty, entry[1]["qty"].as_f64().unwrap(), "{market}: the quantity is untouched");
        assert_eq!(p.avg_price, entry[1]["avg_price"].as_f64().unwrap());
    }
    let equity_saved: f64 = {
        let mut e2 = Engine::new();
        e2.apply_persisted(serde_json::from_value(v.clone()).unwrap());
        status(&e2, &id).equity
    };
    assert!((s.equity - equity_saved).abs() < 1e-9);
    assert!(s.equity > 90_000.0 && s.equity < 95_001.0, "{}", s.equity);
    // The order still at the venue is the autopilot's, and so are the fees
    // Alpaca has still to post.
    assert!(r.in_flight_markets.iter().all(|k| k.starts_with("ap_29742|")) && r.in_flight_markets.len() == 1);
    assert_eq!(r.orders.iter().find(|o| o.id == pending).unwrap().book.as_deref(), Some(id.as_str()));
    assert!(!r.alpaca_fees.is_empty() && r.alpaca_fees.iter().all(|w| w.book == id));
    // Each lab book's last signal is kept for the autopilot: nothing is
    // bought or sold again after the restart.
    for sid in ["lab:breakout_top10", "lab:tsmom_tranches", "lab:tsmom_regime"] {
        assert!(r.lab_done.contains_key(&pos_key(&id, sid)), "{sid}");
    }
    r.run_lab_books();
    assert!(r.drain_live_orders().is_empty(), "the migration trades nothing");
    assert!(r.journal.iter().any(|j| j.message.contains("Autopilot \"AP ap_29742\" now keeps a book of its own")
        && j.message.contains("Nothing was sold or bought")));

    // The pending order fills: booked in the autopilot's book.
    let f = r.inflight[&pending].clone();
    r.apply_live_update(&pending, filled(f.qty, f.arrival, 0.0));
    assert_eq!(status(&r, &id).open_positions, held + 1);

    // A second restart finds books and moves nothing (the journal it brings
    // back has the one line from the first).
    let saved = serde_json::to_string(&r.to_persisted()).unwrap();
    let mut r2 = Engine::new();
    r2.apply_persisted(serde_json::from_str(&saved).unwrap());
    let said = |e: &Engine| e.journal.iter().filter(|j| j.message.contains("now keeps a book of its own")).count();
    assert_eq!((said(&r), said(&r2)), (1, 1));
    assert_eq!(r2.positions.len(), held + 1);
    // And a second autopilot may now run the same lab books next to it.
    host_setup(&mut r2);
    let now = r2.now();
    r2.apply_lab_signal(lab_signal("tsmom_regime", now, &[("BTC", 0.1)]));
    let second = start(&mut r2, demo_config("second", 1.0, &["lab:tsmom_regime"]));
    assert_eq!(status(&r2, &second).open_positions, 0);
}

// ── benchmarks ─────────────────────────────────────────────────────────────

/// Five-minute BTC candles from `from` to now, flat at `px`.
fn btc_candles(e: &mut Engine, from: i64, px: f64) {
    let now = e.now();
    let mut bars: Vec<Ohlc> = Vec::new();
    let mut t = from - 600_000;
    while t <= now {
        bars.push(Ohlc { ts: t, open: px, high: px, low: px, close: px, volume: 1.0 });
        t += 300_000;
    }
    e.apply_bars(&[BarSeries { id: BTC.into(), bars }]);
}

#[test]
fn an_autopilot_saved_without_a_btc_start_gets_it_from_the_candle_at_its_start() {
    let mut e = engine();
    let id = start(&mut e, config("old", 1_000.0, &["ema-cross-1"]));
    let started = e.now() - 3 * 3_600_000;
    {
        let ap = e.autopilots.iter_mut().find(|a| a.config.id == id).unwrap();
        ap.btc_start = None;
        ap.started_ms = started;
    }
    btc_candles(&mut e, started, 50_000.0);
    set_price(&mut e, BTC, 55_000.0);
    assert_eq!(status(&e, &id).btc_return_pct, None);
    let now = e.now();
    e.autopilot_step(now);
    let s = status(&e, &id);
    assert!((s.btc_return_pct.unwrap() - 10.0).abs() < 1e-9, "{:?}", s.btc_return_pct);
    let b = s.benchmark.unwrap();
    assert_eq!((b.symbol.as_str(), b.name.as_str()), ("BTC/USD", "BTC buy and hold"));
    assert!((b.return_pct.unwrap() - 10.0).abs() < 1e-9);
    assert!((b.excess_pct.unwrap() + 10.0).abs() < 1e-6, "flat against BTC's +10 %: {:?}", b.excess_pct);
    assert!(b.note.unwrap().contains("filled in after the fact"));
    assert!(b.from_ms.is_none(), "from its start");
}

#[test]
fn without_a_candle_the_btc_comparison_starts_now_and_says_so() {
    let mut e = engine();
    let id = start(&mut e, config("old", 1_000.0, &["ema-cross-1"]));
    {
        let ap = e.autopilots.iter_mut().find(|a| a.config.id == id).unwrap();
        ap.btc_start = None;
        ap.started_ms -= 30 * 86_400_000;
    }
    let now = e.now();
    e.autopilot_step(now);
    assert_eq!(status(&e, &id).btc_return_pct, None, "it looks for a candle first");
    e.autopilot_step(now + BENCH_WAIT_MS);
    let s = status(&e, &id);
    assert_eq!(s.btc_return_pct, Some(0.0), "never null for long: compared from now");
    let b = s.benchmark.unwrap();
    assert_eq!(b.from_ms, Some(now + BENCH_WAIT_MS));
    assert!(b.note.unwrap().contains("comparison starts"), "said in its status");
    // The note survives a restart, and nothing is filled twice.
    let mut r = Engine::new();
    r.apply_persisted(e.to_persisted());
    let rs = status(&r, &id);
    assert_eq!(rs.benchmark.unwrap().from_ms, Some(now + BENCH_WAIT_MS));
}

#[test]
fn an_autopilot_of_us_shares_is_held_against_spy() {
    let mut e = engine();
    e.apply_alpaca(&[RealEquity { id: SPY_ID.into(), symbol: "SPY".into(), price: 500.0, change24h: 0.0 }]);
    let mut c = config("shares", 1_000.0, &["breakout-1"]);
    c.venue = "alpaca".into();
    let id = start(&mut e, c);
    e.apply_alpaca(&[RealEquity { id: SPY_ID.into(), symbol: "SPY".into(), price: 510.0, change24h: 0.0 }]);
    let b = status(&e, &id).benchmark.unwrap();
    assert_eq!((b.symbol.as_str(), b.name.as_str()), ("SPY", "SPY buy and hold"));
    assert!((b.return_pct.unwrap() - 2.0).abs() < 1e-9);
    e.autopilot_stop(&id, None).unwrap();
    e.apply_alpaca(&[RealEquity { id: SPY_ID.into(), symbol: "SPY".into(), price: 400.0, change24h: 0.0 }]);
    assert!((status(&e, &id).benchmark.unwrap().return_pct.unwrap() - 2.0).abs() < 1e-9, "frozen at the stop");
}

#[test]
fn the_comparison_numbers_are_on_every_status() {
    let mut e = engine();
    let id = start(&mut e, config("cmp", 1_000.0, &["ema-cross-1"]));
    signal_in(&mut e, &id, "ema-cross-1", BTC);
    let px = e.price_of(BTC);
    let now = e.now();
    set_price(&mut e, BTC, px * 1.2);
    e.autopilot_step(now + 60_000);
    set_price(&mut e, BTC, px * 0.9);
    e.autopilot_step(now + 120_000);
    let s = status(&e, &id);
    assert!(s.max_drawdown_pct > s.drawdown_pct - 1e-9 && s.max_drawdown_pct > 0.0, "{s:?}");
    assert_eq!(max_drawdown_pct(&[(0, 100.0), (1, 120.0), (2, 90.0), (3, 110.0)], 105.0), 25.0);
    let json = serde_json::to_value(&s).unwrap();
    for k in ["benchmark", "cash", "maxDrawdownPct", "btcReturnPct", "history", "fees", "trades"] {
        assert!(json.get(k).is_some(), "{k} reaches the UI: {json}");
    }
    assert!(json["benchmark"].get("excessPct").is_some());
}
