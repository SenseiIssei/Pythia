//! Engine-level tests for the Autopilot: starting and stopping, sleeve
//! budgets as fractions of the autopilot's capital, every stop rule firing
//! exactly at its threshold, pause and resume, restart persistence, the live
//! gates, market conflicts, the auto pick, and the absence of any path that
//! moves money. Deterministic: prices are set by hand and time is passed in.

use super::autopilot::*;
use super::*;

const BTC: &str = "crypto:BTC/USD";
const ETH: &str = "crypto:ETH/USD";

/// A fresh engine whose crypto prices count as real and fresh.
fn engine() -> Engine {
    let mut e = Engine::new();
    mark_real(&mut e);
    e
}

fn mark_real(e: &mut Engine) {
    let now = e.now();
    let ids: Vec<String> = e.markets.iter().filter(|m| m.venue == Venue::Crypto).map(|m| m.id.clone()).collect();
    for m in e.markets.iter_mut().filter(|m| m.venue == Venue::Crypto) {
        m.updated_at = now;
    }
    e.real_ids.extend(ids);
}

fn config(id: &str, capital: f64, sleeves: &[(&str, f64)], stop: StopRules) -> AutopilotConfig {
    AutopilotConfig {
        id: id.into(),
        name: format!("Test {id}"),
        mode: AutopilotMode::Paper,
        venue: "kraken".into(),
        asset_class: None,
        capital_usd: capital,
        sleeves: sleeves.iter().map(|(s, w)| SleeveConfig { strategy_id: s.to_string(), weight: *w }).collect(),
        stop,
        flatten_on_stop: true,
        max_sleeves: None,
        repick_every_hours: None,
        portfolio: false,
    }
}

fn start(e: &mut Engine, cfg: AutopilotConfig) -> String {
    e.autopilot_start(cfg, false, VenueCash::NotRead).expect("the autopilot starts")
}

fn status(e: &Engine, id: &str) -> AutopilotStatus {
    e.autopilot_statuses().into_iter().find(|s| s.config.id == id).expect("the autopilot exists")
}

fn idx(e: &Engine, sid: &str) -> usize {
    e.strategies.iter().position(|s| s.id == sid).unwrap()
}

fn state_of(e: &Engine, sid: &str) -> StrategyState {
    e.strategy_config(sid).unwrap().state
}

/// Enter through the real paper fill path, exactly where a strategy signal ends.
fn enter(e: &mut Engine, sid: &str, market: &str, notional: f64) {
    let i = idx(e, sid);
    let m = e.markets.iter().find(|m| m.id == market).cloned().unwrap();
    e.fill(i, &m, Side::Buy, notional / m.price, m.price);
}

fn set_price(e: &mut Engine, market: &str, price: f64) {
    let now = e.now();
    let m = e.markets.iter_mut().find(|m| m.id == market).unwrap();
    m.price = price;
    m.updated_at = now;
}

/// Move `market` to the price at which the autopilot's equity is `target`.
fn equity_to(e: &mut Engine, id: &str, market: &str, target: f64) {
    let eq = status(e, id).equity;
    let qty = e.positions[&pos_key(id, market)].qty;
    let p = e.price_of(market) + (target - eq) / qty;
    set_price(e, market, p);
    assert!((status(e, id).equity - target).abs() < 1e-7, "equity set to {target}");
}

fn step(e: &mut Engine) {
    let now = e.now();
    e.autopilot_step(now);
}

fn buy_intent(market: &str) -> strategies::SignalIntent {
    strategies::SignalIntent { market_id: market.into(), side: Side::Buy, size: 1.0, confidence: 1.0, reason: "test".into() }
}

fn market(e: &Engine, id: &str) -> Market {
    e.markets.iter().find(|m| m.id == id).cloned().unwrap()
}

/// Every book's position in `market` together, at the mark.
fn notional(e: &Engine, market: &str) -> f64 {
    e.positions.values().filter(|p| p.market == market).map(|p| p.qty * e.price_of(market)).sum()
}

/// Some book holds `market`.
fn holds(e: &Engine, market: &str) -> bool {
    e.positions.values().any(|p| p.market == market)
}

/// The quantity the book `book` holds in `market`.
fn qty_in(e: &Engine, book: &str, market: &str) -> f64 {
    e.positions.get(&pos_key(book, market)).map(|p| p.qty).unwrap_or(0.0)
}

fn journal_has(e: &Engine, needle: &str) -> bool {
    e.journal.iter().any(|j| j.message.contains(needle))
}

/// Research gates 1 to 6 green and a finished paper forward test.
fn make_live_ready(e: &mut Engine, id: &str) {
    let s = e.strategy_config(id).unwrap();
    e.store_research(validation::ResearchVerdict {
        strategy_id: id.into(),
        params: s.params.iter().map(|p| (p.key.clone(), p.value)).collect(),
        checked_at: e.now(),
        markets: 1,
        bars: 700,
        cost_venue: CostVenue::Kraken,
        gates: (1..=6).map(|g| validation::Gate::new(g, validation::GateStatus::Pass, "test", Some(1.0))).collect(),
    });
    let now = e.now();
    let s = e.strategies.iter_mut().find(|s| s.id == id).unwrap();
    s.ledger.paper_since = Some(now - 60 * 86_400_000);
    s.ledger.forward_trades = 40;
}

fn armed_crypto() -> LiveConfig {
    LiveConfig { armed: true, paper: false, dry_run: false, venues: vec![Venue::Crypto], timeout_sec: 120, extended_hours: false }
}

fn live_config(id: &str, capital: f64, sleeves: &[(&str, f64)]) -> AutopilotConfig {
    let mut c = config(id, capital, sleeves, StopRules { max_loss_pct: Some(10.0), ..Default::default() });
    c.mode = AutopilotMode::Live;
    c
}

// ── start, stop, budgets ───────────────────────────────────────────────────

#[test]
fn an_autopilot_runs_its_strategies_and_a_stop_closes_everything_and_pauses_them() {
    let mut e = engine();
    let id = start(&mut e, config("a", 1_000.0, &[("ema-cross-1", 1.0)], StopRules::default()));
    let s = status(&e, &id);
    assert_eq!(s.state, AutopilotState::Running);
    assert_eq!((s.start_capital, s.equity, s.peak_equity), (1_000.0, 1_000.0, 1_000.0));
    assert_eq!(state_of(&e, "ema-cross-1"), StrategyState::Paper);
    assert!(journal_has(&e, "Autopilot \"Test a\" started in paper on Kraken with $1,000.00"));

    enter(&mut e, "ema-cross-1", BTC, 500.0);
    let s = status(&e, &id);
    assert_eq!(s.open_positions, 1);
    assert!(s.fees > 0.0, "the entry paid its fee");
    assert!(s.equity < 1_000.0 && s.equity > 995.0, "costs only: {}", s.equity);

    e.autopilot_stop(&id, None).unwrap();
    let s = status(&e, &id);
    assert_eq!(s.state, AutopilotState::Stopped);
    assert_eq!(s.stop_reason.as_deref(), Some("stopped by you"));
    assert!(s.stopped_ms.is_some());
    assert_eq!(s.open_positions, 0);
    assert!(!holds(&e, BTC), "flattened on stop by default");
    assert_eq!(s.trades, 1);
    assert!((s.pnl - (s.equity - 1_000.0)).abs() < 1e-9);
    assert!(s.pnl < 0.0, "a round trip at an unchanged price costs fees and spread");
    assert_eq!(state_of(&e, "ema-cross-1"), StrategyState::Paused, "a stop halts its strategies");
    assert!(journal_has(&e, "stopped: stopped by you. Equity $"));
    assert!(e.autopilot_stop(&id, None).unwrap_err().contains("already stopped"));
    // Once stopped, its book takes nothing new, and the strategy is the
    // main book's again.
    assert!(!e.autopilot_entry_allowed(&id, "ema-cross-1", BTC));
    assert!(e.autopilot_entry_allowed("", "ema-cross-1", BTC));
}

#[test]
fn sleeve_budgets_are_fractions_of_the_autopilot_not_of_the_account() {
    let mut e = engine();
    let id = start(&mut e, config("b", 2_000.0, &[("ema-cross-1", 3.0), ("multi-tf-1", 1.0)], StopRules::default()));
    let s = status(&e, &id);
    let ema = s.by_sleeve.iter().find(|x| x.strategy_id == "ema-cross-1").unwrap();
    let mtf = s.by_sleeve.iter().find(|x| x.strategy_id == "multi-tf-1").unwrap();
    assert!((ema.weight - 0.75).abs() < 1e-12 && (mtf.weight - 0.25).abs() < 1e-12, "weights normalised");
    // The nine shared markets are dealt out in turn, heavier sleeve first.
    assert_eq!((ema.markets.len(), mtf.markets.len()), (5, 4));
    assert!(ema.markets.iter().all(|m| !mtf.markets.contains(m)), "no market belongs to two sleeves");

    let sz = e.autopilot_sizing(&id, "ema-cross-1").unwrap();
    assert!((sz.capital - 1_500.0).abs() < 1e-9 && sz.slots == 5.0 && (sz.room - 1_500.0).abs() < 1e-9);

    // A full-strength signal is sized from the sleeve's 1,500 over its 5
    // markets (x1.5), not from the 100,000 of the paper account.
    let target = ema.markets[0].clone();
    let i = idx(&e, "ema-cross-1");
    let m = market(&e, &target);
    e.place_from_intent(&id, i, &m, &buy_intent(&target));
    let n = notional(&e, &target);
    assert!((n - 450.0).abs() < 1.0, "sized from the sleeve: {n}");
    assert!(qty_in(&e, &id, &target) > 0.0, "in the autopilot's own book");

    // A strategy may not trade another sleeve's market in the autopilot's
    // book. Strategies outside it trade the main book, which is separate.
    assert!(!e.autopilot_entry_allowed(&id, "ema-cross-1", &mtf.markets[0]));
    assert!(e.autopilot_entry_allowed(&id, "multi-tf-1", &mtf.markets[0]));
    assert!(!e.autopilot_entry_allowed(&id, "rsi-1", &target));
    assert!(e.autopilot_entry_allowed("", "rsi-1", &target));
    assert!(!e.autopilot_entry_allowed("", "ema-cross-1", &target), "a strategy in an autopilot trades only there");
}

#[test]
fn an_entry_never_takes_the_sleeve_past_its_budget() {
    let mut e = engine();
    let id = start(&mut e, config("c", 100.0, &[("ema-cross-1", 1.0)], StopRules::default()));
    enter(&mut e, "ema-cross-1", BTC, 95.0);
    let room = e.autopilot_sizing(&id, "ema-cross-1").unwrap().room;
    assert!(room < 6.0, "about 5 dollars left: {room}");
    let equity_before = status(&e, &id).equity;
    let i = idx(&e, "ema-cross-1");
    let m = market(&e, ETH);
    e.place_from_intent(&id, i, &m, &buy_intent(ETH));
    let n = notional(&e, ETH);
    assert!(n > 0.0 && n <= room + 1e-6, "capped at the room left: {n} of {room}");
    let gross: f64 = [BTC, ETH].iter().map(|m| notional(&e, m)).sum();
    assert!(gross <= equity_before + 1e-6, "never more exposure than its equity");
    // With no room left, nothing more is opened.
    let m = market(&e, "crypto:SOL/USD");
    e.place_from_intent(&id, i, &m, &buy_intent("crypto:SOL/USD"));
    assert!(!holds(&e, "crypto:SOL/USD"));
}

// ── stop rules ─────────────────────────────────────────────────────────────

#[test]
fn max_loss_in_percent_fires_exactly_at_its_floor_and_flattens() {
    let mut e = engine();
    let id = start(&mut e, config("d", 1_000.0, &[("ema-cross-1", 1.0)], StopRules { max_loss_pct: Some(10.0), ..Default::default() }));
    enter(&mut e, "ema-cross-1", BTC, 500.0);
    assert!((status(&e, &id).floor_equity.unwrap() - 900.0).abs() < 1e-9);

    equity_to(&mut e, &id, BTC, 900.0 + 1e-6);
    step(&mut e);
    assert_eq!(status(&e, &id).state, AutopilotState::Running, "a millionth of a dollar above the floor keeps going");

    equity_to(&mut e, &id, BTC, 900.0);
    step(&mut e);
    let s = status(&e, &id);
    assert_eq!(s.state, AutopilotState::Stopped);
    assert!(s.stop_reason.as_deref().unwrap().starts_with("max loss of 10 % reached (equity $900.00, floor $900.00"));
    assert!(!holds(&e, BTC), "flattened");
    assert!(s.equity < 900.0 && s.equity > 898.0, "the exit paid its costs: {}", s.equity);
    assert_eq!(state_of(&e, "ema-cross-1"), StrategyState::Paused);
    assert!(e.drain_alerts().iter().any(|a| a.contains("max loss of 10 %")), "the stop is pushed as an alert");
    let typed = e.drain_alert_events();
    let kinds: Vec<_> = typed.iter().map(|a| a.kind).collect();
    assert!(kinds.contains(&crate::alerts::AlertKind::AutopilotStarted), "{kinds:?}");
    let floor = typed.iter().find(|a| a.kind == crate::alerts::AlertKind::FloorHit).expect("the floor is an operator alert");
    assert!(floor.text.contains("max loss of 10 % reached"), "{}", floor.text);
    assert!(!kinds.contains(&crate::alerts::AlertKind::AutopilotStopped));
}

#[test]
fn max_loss_in_dollars_fires_exactly_at_its_floor() {
    let mut e = engine();
    let id = start(&mut e, config("e", 1_000.0, &[("ema-cross-1", 1.0)], StopRules { max_loss_usd: Some(50.0), ..Default::default() }));
    enter(&mut e, "ema-cross-1", BTC, 500.0);
    equity_to(&mut e, &id, BTC, 950.0 + 1e-6);
    step(&mut e);
    assert_eq!(status(&e, &id).state, AutopilotState::Running);
    equity_to(&mut e, &id, BTC, 950.0);
    step(&mut e);
    let s = status(&e, &id);
    assert_eq!(s.state, AutopilotState::Stopped);
    assert!(s.stop_reason.unwrap().starts_with("max loss of $50.00 reached"));
    assert!(!holds(&e, BTC));
}

#[test]
fn a_take_profit_that_stops_finishes_exactly_at_the_target() {
    let mut e = engine();
    let stop = StopRules { take_profit_pct: Some(10.0), on_take_profit: OnTakeProfit::Stop, ..Default::default() };
    let id = start(&mut e, config("f", 1_000.0, &[("ema-cross-1", 1.0)], stop));
    enter(&mut e, "ema-cross-1", BTC, 500.0);
    assert!((status(&e, &id).target_equity.unwrap() - 1_100.0).abs() < 1e-9);
    equity_to(&mut e, &id, BTC, 1_100.0 - 1e-6);
    step(&mut e);
    assert_eq!(status(&e, &id).state, AutopilotState::Running);
    equity_to(&mut e, &id, BTC, 1_100.0);
    step(&mut e);
    let s = status(&e, &id);
    assert_eq!(s.state, AutopilotState::Finished);
    assert!(s.stop_reason.unwrap().starts_with("take profit of 10 % reached"));
    assert!(!holds(&e, BTC), "flattened");
    assert!(s.pnl > 95.0, "the profit is booked: {}", s.pnl);
}

#[test]
fn a_take_profit_that_locks_raises_the_floor_and_keeps_trading() {
    let mut e = engine();
    let stop = StopRules {
        max_loss_pct: Some(10.0),
        take_profit_pct: Some(10.0),
        on_take_profit: OnTakeProfit::Lock,
        ..Default::default()
    };
    let id = start(&mut e, config("g", 1_000.0, &[("ema-cross-1", 1.0)], stop));
    enter(&mut e, "ema-cross-1", BTC, 500.0);
    equity_to(&mut e, &id, BTC, 1_100.0);
    step(&mut e);
    let s = status(&e, &id);
    assert_eq!(s.state, AutopilotState::Running, "lock keeps going");
    assert!((s.floor_equity.unwrap() - 1_050.0).abs() < 1e-9, "half the gain is locked: {:?}", s.floor_equity);
    assert!((s.target_equity.unwrap() - 1_200.0).abs() < 1e-9, "the next target is one step up");
    assert!(journal_has(&e, "Floor raised to $1,050.00"));

    equity_to(&mut e, &id, BTC, 1_050.0 + 1e-6);
    step(&mut e);
    assert_eq!(status(&e, &id).state, AutopilotState::Running);
    equity_to(&mut e, &id, BTC, 1_050.0);
    step(&mut e);
    let s = status(&e, &id);
    assert_eq!(s.state, AutopilotState::Stopped);
    assert!(s.stop_reason.unwrap().starts_with("locked-in profit floor reached"));
    assert!(s.pnl > 45.0, "it kept most of the locked gain: {}", s.pnl);
}

#[test]
fn a_jump_over_several_targets_locks_the_highest_one() {
    let stop = StopRules { take_profit_pct: Some(10.0), on_take_profit: OnTakeProfit::Lock, ..Default::default() };
    assert_eq!(locked_floor(1_000.0, 10.0, 2), 1_100.0);
    let mut e = engine();
    let id = start(&mut e, config("h", 1_000.0, &[("ema-cross-1", 1.0)], stop));
    enter(&mut e, "ema-cross-1", BTC, 800.0);
    equity_to(&mut e, &id, BTC, 1_210.0);
    step(&mut e);
    let s = status(&e, &id);
    assert!((s.floor_equity.unwrap() - 1_100.0).abs() < 1e-9);
    assert!((s.target_equity.unwrap() - 1_300.0).abs() < 1e-9);
}

#[test]
fn the_trailing_floor_follows_the_peak_and_fires_at_it() {
    let mut e = engine();
    let stop = StopRules { max_loss_pct: Some(50.0), trailing_pct: Some(5.0), ..Default::default() };
    let id = start(&mut e, config("i", 1_000.0, &[("ema-cross-1", 1.0)], stop));
    enter(&mut e, "ema-cross-1", BTC, 500.0);
    // Before any gain the trailing floor sits 5 % under the starting capital.
    assert!((status(&e, &id).floor_equity.unwrap() - 950.0).abs() < 1e-9);
    equity_to(&mut e, &id, BTC, 1_100.0);
    step(&mut e);
    let s = status(&e, &id);
    assert!((s.peak_equity - 1_100.0).abs() < 1e-7);
    assert!((s.floor_equity.unwrap() - 1_045.0).abs() < 1e-6, "5 % under the peak: {:?}", s.floor_equity);
    equity_to(&mut e, &id, BTC, 1_045.0 + 1e-6);
    step(&mut e);
    assert_eq!(status(&e, &id).state, AutopilotState::Running);
    let floor = status(&e, &id).floor_equity.unwrap();
    equity_to(&mut e, &id, BTC, floor);
    step(&mut e);
    let s = status(&e, &id);
    assert_eq!(s.state, AutopilotState::Stopped);
    assert!(s.stop_reason.unwrap().starts_with("trailing floor reached"));
    assert!(!holds(&e, BTC));
}

#[test]
fn the_end_time_finishes_it_on_the_millisecond() {
    let mut e = engine();
    let end = e.now() + 3_600_000;
    let id = start(&mut e, config("j", 1_000.0, &[("ema-cross-1", 1.0)], StopRules { end_ms: Some(end), ..Default::default() }));
    enter(&mut e, "ema-cross-1", BTC, 500.0);
    e.autopilot_step(end - 1);
    assert_eq!(status(&e, &id).state, AutopilotState::Running);
    e.autopilot_step(end);
    let s = status(&e, &id);
    assert_eq!(s.state, AutopilotState::Finished);
    assert_eq!(s.stop_reason.as_deref(), Some("end time reached"));
    assert_eq!(s.stopped_ms, Some(end));
    assert!(!holds(&e, BTC));
}

#[test]
fn endless_means_no_end_time_and_no_target() {
    let mut e = engine();
    let id = start(&mut e, config("k", 1_000.0, &[("ema-cross-1", 1.0)], StopRules::default()));
    let s = status(&e, &id);
    assert!(s.floor_equity.is_none() && s.target_equity.is_none());
    assert!(journal_has(&e, "otherwise runs until you stop it"));
    let far = e.now() + 10 * 365 * 86_400_000;
    e.autopilot_step(far);
    assert_eq!(status(&e, &id).state, AutopilotState::Running);
}

// ── pause, resume, restart ─────────────────────────────────────────────────

#[test]
fn a_paused_autopilot_opens_nothing_but_its_stop_rules_still_apply() {
    let mut e = engine();
    let id = start(&mut e, config("l", 1_000.0, &[("ema-cross-1", 1.0)], StopRules { max_loss_pct: Some(10.0), ..Default::default() }));
    enter(&mut e, "ema-cross-1", BTC, 500.0);
    e.autopilot_pause(&id).unwrap();
    let s = status(&e, &id);
    assert_eq!(s.state, AutopilotState::Paused);
    assert_eq!(s.paused_reason.as_deref(), Some("paused by you"));
    assert!(!e.autopilot_entry_allowed(&id, "ema-cross-1", ETH), "no new entries while paused");
    assert!(!e.autopilot_entry_allowed("", "ema-cross-1", ETH), "and none outside it either");
    assert_eq!(state_of(&e, "ema-cross-1"), StrategyState::Paper, "pausing does not touch the strategy");
    assert!(e.autopilot_pause(&id).unwrap_err().contains("already paused"));

    e.autopilot_resume(&id).unwrap();
    assert_eq!(status(&e, &id).state, AutopilotState::Running);
    assert!(e.autopilot_entry_allowed(&id, "ema-cross-1", ETH));

    e.autopilot_pause(&id).unwrap();
    equity_to(&mut e, &id, BTC, 900.0);
    step(&mut e);
    let s = status(&e, &id);
    assert_eq!(s.state, AutopilotState::Stopped, "the floor protects a paused autopilot too");
    assert!(!holds(&e, BTC));
    assert!(e.autopilot_resume(&id).unwrap_err().contains("stopped"));
}

#[test]
fn a_restart_keeps_the_peak_the_floor_and_the_positions() {
    let mut e = engine();
    let stop = StopRules {
        max_loss_pct: Some(10.0),
        take_profit_pct: Some(10.0),
        on_take_profit: OnTakeProfit::Lock,
        trailing_pct: Some(5.0),
        ..Default::default()
    };
    let id = start(&mut e, config("m", 1_000.0, &[("ema-cross-1", 1.0)], stop));
    enter(&mut e, "ema-cross-1", BTC, 500.0);
    equity_to(&mut e, &id, BTC, 1_100.0);
    step(&mut e);
    equity_to(&mut e, &id, BTC, 1_080.0);
    step(&mut e);
    let before = status(&e, &id);
    assert!((before.peak_equity - 1_100.0).abs() < 1e-6);
    assert!((before.floor_equity.unwrap() - 1_050.0).abs() < 1e-6, "lock beats the trailing 1,045");

    let saved = serde_json::to_string(&e.to_persisted()).unwrap();
    let mut r = Engine::new();
    r.apply_persisted(serde_json::from_str(&saved).unwrap());
    mark_real(&mut r);
    let after = status(&r, &id);
    assert_eq!(after.state, AutopilotState::Running);
    assert!((after.peak_equity - before.peak_equity).abs() < 1e-9, "the peak survives");
    assert_eq!(after.floor_equity, before.floor_equity, "the floor survives");
    assert_eq!(after.target_equity, before.target_equity, "the take-profit step survives");
    assert!((after.equity - before.equity).abs() < 1e-6, "same positions, same prices, same equity");
    assert_eq!(after.open_positions, 1);
    assert_eq!(after.by_sleeve[0].markets, before.by_sleeve[0].markets);
    assert!(r.set_strategy_state("ema-cross-1", StrategyState::Paused).is_err(), "still claimed after the restart");

    equity_to(&mut r, &id, BTC, 1_050.0);
    step(&mut r);
    let s = status(&r, &id);
    assert_eq!(s.state, AutopilotState::Stopped, "the restored floor fires");
    assert!(s.stop_reason.unwrap().starts_with("locked-in profit floor reached"));
}

#[test]
fn the_equity_history_is_thinned_and_survives_a_restart() {
    let mut e = engine();
    let id = start(&mut e, config("n", 1_000.0, &[("ema-cross-1", 1.0)], StopRules::default()));
    let t0 = e.now();
    for k in 1..=700 {
        e.autopilot_step(t0 + k * 60_000);
    }
    let h = status(&e, &id).history;
    assert!(h.len() <= 300 && h.len() > 100, "thinned to at most 300 points: {}", h.len());
    assert!(h.windows(2).all(|w| w[0].0 < w[1].0), "in time order");
    assert_eq!(h.last().unwrap().0, t0 + 700 * 60_000, "the newest point is kept");
    let mut r = Engine::new();
    r.apply_persisted(e.to_persisted());
    assert_eq!(status(&r, &id).history, h);
}

#[test]
fn the_thinned_history_still_covers_every_day_of_a_long_run() {
    // Five days of one point a minute, thinned as the engine does whenever
    // the curve is full: the equity a day ago must still be in it.
    let t0 = 1_792_067_549_994_i64;
    let mut h: Vec<(i64, f64)> = vec![(t0, 10_000.0)];
    let n = 5 * 1_440;
    for k in 1..=n {
        h.push((t0 + k * 60_000, 10_000.0 + k as f64));
        if h.len() > 300 {
            h = thin_history(&h);
        }
    }
    let now = t0 + n * 60_000;
    assert!(h.len() <= 300 && h.len() > 100, "{}", h.len());
    assert_eq!(h.first().unwrap().0, t0, "the start stays");
    assert_eq!(h.last().unwrap().0, now, "the newest point stays");
    assert!(h.windows(2).all(|w| w[0].0 < w[1].0), "in time order");
    let day_ago = now - 86_400_000;
    let before = h.iter().rev().find(|p| p.0 <= day_ago).unwrap();
    assert!(day_ago - before.0 <= 2 * 3_600_000, "a point within two hours before a day ago: {}", day_ago - before.0);
    let biggest_gap = h.windows(2).map(|w| w[1].0 - w[0].0).max().unwrap();
    assert!(biggest_gap <= 3 * 3_600_000, "no hole longer than three hours: {biggest_gap}");
    assert_eq!(thin_history(&[]), vec![]);
    assert_eq!(thin_history(&[(1, 1.0), (2, 2.0)]), vec![(1, 1.0), (2, 2.0)]);
}

#[test]
fn it_is_held_against_bitcoin_over_its_own_run_and_lists_what_it_holds() {
    let mut e = engine();
    set_price(&mut e, BTC, 100_000.0);
    let id = start(&mut e, config("b", 1_000.0, &[("ema-cross-1", 1.0)], StopRules::default()));
    let s = status(&e, &id);
    assert_eq!(s.btc_return_pct, Some(0.0));
    assert!(s.held.is_empty(), "in cash at the start");

    enter(&mut e, "ema-cross-1", ETH, 300.0);
    let fee = e.orders[0].fee.expect("a paper fill knows its fee");
    assert!(fee > 0.0 && (fee - status(&e, &id).fees).abs() < 1e-9, "the order row carries the fee the autopilot paid");
    set_price(&mut e, BTC, 105_000.0);
    let s = status(&e, &id);
    assert!((s.btc_return_pct.unwrap() - 5.0).abs() < 1e-9, "BTC up 5 %: {:?}", s.btc_return_pct);
    assert_eq!(s.held, vec![ETH.to_string()]);

    // A restart keeps the start price.
    let mut r = Engine::new();
    r.apply_persisted(e.to_persisted());
    mark_real(&mut r);
    set_price(&mut r, BTC, 105_000.0);
    assert!((status(&r, &id).btc_return_pct.unwrap() - 5.0).abs() < 1e-9);

    // Once stopped, the comparison ends where the run ended.
    e.autopilot_stop(&id, None).unwrap();
    set_price(&mut e, BTC, 50_000.0);
    let s = status(&e, &id);
    assert!((s.btc_return_pct.unwrap() - 5.0).abs() < 1e-9, "frozen at the stop");
    assert!(s.held.is_empty());
}

#[test]
fn an_autopilot_saved_before_the_benchmark_has_none_rather_than_a_guess() {
    let mut e = engine();
    let id = start(&mut e, config("c", 1_000.0, &[("ema-cross-1", 1.0)], StopRules::default()));
    let mut v = serde_json::to_value(e.to_persisted()).unwrap();
    let aps = v.get_mut("autopilots").and_then(|a| a.as_array_mut()).expect("autopilots are saved");
    for ap in aps {
        let o = ap.as_object_mut().unwrap();
        o.remove("btcStart");
        o.remove("btcEnd");
    }
    let mut r = Engine::new();
    r.apply_persisted(serde_json::from_value(v).unwrap());
    assert_eq!(status(&r, &id).btc_return_pct, None);
}

// ── live ───────────────────────────────────────────────────────────────────

#[test]
fn live_is_refused_without_confirmation_arming_or_passports_and_says_why() {
    let mut e = engine();
    let c = live_config("live", 1_000.0, &[("ema-cross-1", 1.0)]);
    let cash = || VenueCash::Read(10_000.0);

    let err = e.autopilot_start(c.clone(), false, cash()).unwrap_err();
    assert!(err.contains("type the confirmation"), "{err}");
    let err = e.autopilot_start(c.clone(), true, cash()).unwrap_err();
    assert!(err.contains("not armed"), "{err}");
    assert!(err.contains("never arms anything itself"));

    e.set_live(LiveConfig { venues: vec![Venue::Alpaca], ..armed_crypto() });
    let err = e.autopilot_start(c.clone(), true, cash()).unwrap_err();
    assert!(err.contains("Kraken is not enabled for live routing"), "{err}");

    e.set_live(armed_crypto());
    let err = e.autopilot_start(c.clone(), true, cash()).unwrap_err();
    assert!(err.starts_with("EMA Cross · Crypto is not cleared for live"), "{err}");
    assert!(e.autopilot_statuses().is_empty(), "nothing started");
    assert_eq!(state_of(&e, "ema-cross-1"), StrategyState::Paper, "nothing changed");

    make_live_ready(&mut e, "ema-cross-1");
    let mut no_floor = c.clone();
    no_floor.stop = StopRules::default();
    let err = e.autopilot_start(no_floor, true, cash()).unwrap_err();
    assert!(err.contains("max-loss rule"), "{err}");
}

#[test]
fn live_is_refused_above_the_free_cash_at_the_venue() {
    let mut e = engine();
    e.set_live(armed_crypto());
    make_live_ready(&mut e, "pairs-1");
    make_live_ready(&mut e, "ema-cross-1");
    // Pairs holds BTC and ETH only, so a second autopilot has markets left.
    let c = live_config("live", 1_000.0, &[("pairs-1", 1.0)]);

    let err = e.autopilot_start(c.clone(), true, VenueCash::Read(500.0)).unwrap_err();
    assert!(err.contains("Kraken holds $500.00 of free cash, so $1,000.00 cannot be given"), "{err}");
    assert!(err.contains("never moves money") && err.contains("Exodus"), "names the money source: {err}");
    let err = e.autopilot_start(c.clone(), true, VenueCash::Failed("timed out".into())).unwrap_err();
    assert!(err.starts_with("Could not read the free cash at Kraken (timed out)"), "{err}");
    let err = e.autopilot_start(c.clone(), true, VenueCash::NotRead).unwrap_err();
    assert!(err.contains("was not read"), "{err}");

    // Exactly the free cash is fine.
    e.autopilot_start(c, true, VenueCash::Read(1_000.0)).unwrap();
    assert_eq!(state_of(&e, "pairs-1"), StrategyState::Live, "the autopilot set its strategy live");
    assert!(e.journal.iter().any(|j| j.kind == JournalKind::Risk && j.message.contains("started in LIVE on Kraken")));

    // A second live autopilot only gets what the first did not commit.
    let mut c2 = live_config("live2", 1_500.0, &[("ema-cross-1", 1.0)]);
    let err = e.autopilot_start(c2.clone(), true, VenueCash::Read(2_000.0)).unwrap_err();
    assert!(err.contains("of which $1,000.00 is already committed to other live autopilots"), "{err}");
    c2.capital_usd = 1_000.0;
    let id2 = e.autopilot_start(c2, true, VenueCash::Read(2_000.0)).unwrap();
    assert_eq!(status(&e, &id2).by_sleeve[0].markets.len(), 9, "its own book: every market of its universe, BTC and ETH too");
    // A live autopilot keeps its strategies to itself.
    let err = e.autopilot_start(live_config("live3", 1.0, &[("pairs-1", 1.0)]), true, VenueCash::Read(5_000.0)).unwrap_err();
    assert!(err.contains("A live autopilot runs its strategies alone"), "{err}");
}

#[test]
fn a_live_autopilot_sends_real_orders_and_pauses_when_live_is_disarmed() {
    let mut e = engine();
    e.set_live(armed_crypto());
    make_live_ready(&mut e, "ema-cross-1");
    let id = e.autopilot_start(live_config("live", 1_000.0, &[("ema-cross-1", 1.0)]), true, VenueCash::Read(1_000.0)).unwrap();

    let i = idx(&e, "ema-cross-1");
    let m = market(&e, BTC);
    e.place_from_intent(&id, i, &m, &buy_intent(BTC));
    let out = e.drain_live_orders();
    assert_eq!(out.len(), 1, "the entry went to the venue");
    assert!(!holds(&e, BTC), "and was not paper-filled");
    assert!(out[0].qty * out[0].ref_price <= 1_000.0 + 1e-6, "sized from the autopilot");

    e.set_live(LiveConfig { armed: false, ..armed_crypto() });
    assert!(!e.autopilot_entry_allowed(&id, "ema-cross-1", ETH), "disarmed: no entry is even considered");
    step(&mut e);
    let s = status(&e, &id);
    assert_eq!(s.state, AutopilotState::Paused);
    assert!(s.paused_reason.unwrap().contains("disarmed"));
    let err = e.autopilot_resume(&id).unwrap_err();
    assert!(err.starts_with("Cannot resume live: live routing is disarmed"), "{err}");

    e.set_live(armed_crypto());
    e.autopilot_resume(&id).unwrap();
    assert_eq!(status(&e, &id).state, AutopilotState::Running);
}

#[test]
fn a_live_autopilot_comes_back_paused_after_a_restart() {
    let mut e = engine();
    e.set_live(armed_crypto());
    make_live_ready(&mut e, "ema-cross-1");
    let id = e.autopilot_start(live_config("live", 1_000.0, &[("ema-cross-1", 1.0)]), true, VenueCash::Read(1_000.0)).unwrap();
    let mut r = Engine::new();
    r.apply_persisted(e.to_persisted());
    let s = status(&r, &id);
    assert_eq!(s.state, AutopilotState::Paused, "live arming is not saved, so nothing real happens until the owner arms");
    assert!(s.paused_reason.unwrap().starts_with("Pythia restarted, and live routing is disarmed"));
}

#[test]
fn a_demo_autopilot_needs_demo_keys_and_then_sends_demo_orders() {
    assert_eq!(AutopilotMode::Demo.route_intent(), RouteIntent::Demo);
    assert_eq!(AutopilotMode::Paper.route_intent(), RouteIntent::Paper);
    assert_eq!(AutopilotMode::Live.route_intent(), RouteIntent::Live);
    let mut e = engine();
    let mut c = config("demo", 1_000.0, &[("ema-cross-1", 1.0)], StopRules::default());
    c.mode = AutopilotMode::Demo;

    // No demo keys: refused before anything is claimed.
    let err = e.autopilot_start(c.clone(), false, VenueCash::NotRead).unwrap_err();
    assert!(err.contains("needs demo keys"), "{err}");

    // With demo keys the order goes out to the venue's demo account, not the live one.
    e.set_demo_venues([Venue::Crypto].into_iter().collect(), Some(e.crypto_venue), true);
    let id = start(&mut e, c);
    assert!(journal_has(&e, "Orders go to the venue's demo account"));
    let i = idx(&e, "ema-cross-1");
    let m = market(&e, BTC);
    e.place_from_intent(&id, i, &m, &buy_intent(BTC));
    let out = e.drain_live_orders();
    assert_eq!(out.len(), 1, "one demo order handed to the daemon");
    assert!(out[0].demo, "marked for the demo environment");
}

#[test]
fn nothing_anywhere_can_withdraw_or_transfer_money() {
    // Every file that talks to a venue or holds money. Order placement is the
    // only write path; there is no withdrawal, transfer or deposit call.
    let sources = [
        ("connectors/mod.rs", include_str!("../connectors/mod.rs")),
        ("connectors/alpaca.rs", include_str!("../connectors/alpaca.rs")),
        ("connectors/paper.rs", include_str!("../connectors/paper.rs")),
        ("connectors/polymarket.rs", include_str!("../connectors/polymarket.rs")),
        ("connectors/cex/mod.rs", include_str!("../connectors/cex/mod.rs")),
        ("connectors/cex/kraken.rs", include_str!("../connectors/cex/kraken.rs")),
        ("connectors/cex/binance.rs", include_str!("../connectors/cex/binance.rs")),
        ("connectors/cex/bybit.rs", include_str!("../connectors/cex/bybit.rs")),
        ("connectors/cex/okx.rs", include_str!("../connectors/cex/okx.rs")),
        ("connectors/cex/coinbase.rs", include_str!("../connectors/cex/coinbase.rs")),
        ("execution/mod.rs", include_str!("../execution/mod.rs")),
        ("wallets.rs", include_str!("../wallets.rs")),
        ("engine/autopilot.rs", include_str!("autopilot.rs")),
    ];
    let forbidden = [
        "fn withdraw",
        "fn transfer",
        "fn deposit",
        "fn send_funds",
        "/withdraw",
        "withdraw/apply",
        "withdrawfunds",
        "/transfers",
        "/transfer",
        "asset/transfer",
        "walletwithdraw",
        "\"withdraw\"",
    ];
    for (file, src) in sources {
        let lower = src.to_lowercase();
        for f in forbidden {
            assert!(!lower.contains(f), "{file} contains `{f}`: Pythia must never move money");
        }
    }
    // And the autopilot's own surface is orders only.
    let ap = include_str!("autopilot.rs");
    for name in ["pub fn autopilot_start", "pub fn autopilot_stop", "pub fn autopilot_pause", "pub fn autopilot_resume"] {
        assert!(ap.contains(name));
    }
}

// ── conflicts and the auto pick ────────────────────────────────────────────

#[test]
fn whole_set_strategies_claim_their_markets_first_and_the_rest_is_dealt_out() {
    let mut e = engine();
    // Pairs trades BTC and ETH as one set: it gets both, EMA the other seven.
    let id = start(&mut e, config("p", 1_000.0, &[("ema-cross-1", 2.0), ("pairs-1", 1.0)], StopRules::default()));
    let s = status(&e, &id);
    let pairs = s.by_sleeve.iter().find(|x| x.strategy_id == "pairs-1").unwrap();
    let ema = s.by_sleeve.iter().find(|x| x.strategy_id == "ema-cross-1").unwrap();
    assert_eq!(pairs.markets, vec![BTC.to_string(), ETH.to_string()]);
    assert_eq!(ema.markets.len(), 7);
    assert!(!ema.markets.contains(&BTC.to_string()));

    // Inside one autopilot two sleeves cannot share a market (one position
    // per market in its book): a second sleeve on the same set gets nothing.
    let err = e
        .autopilot_start(config("q", 1_000.0, &[("pairs-1", 2.0), ("ema-cross-1", 1.0), ("multi-tf-1", 1.0)], StopRules::default()), false, VenueCash::NotRead);
    assert!(err.is_ok(), "the three deal the markets out: {err:?}");
    // A second paper autopilot may run the same strategies on the same
    // markets: it trades them in a book of its own.
    let q = status(&e, "q");
    assert_eq!(q.by_sleeve.iter().find(|x| x.strategy_id == "pairs-1").unwrap().markets, vec![BTC.to_string(), ETH.to_string()]);
    assert!(journal_has(&e, "Also running in other autopilots, each in its own book"));

    // The owner cannot flip a claimed strategy behind the autopilots' backs.
    let err = e.set_strategy_state("ema-cross-1", StrategyState::Live).unwrap_err();
    assert!(err.contains("runs in the autopilot \"Test p\", \"Test q\""), "{err}");
}

#[test]
fn assigning_markets_is_exclusive_and_deterministic() {
    let w = |weight: f64, whole: bool, u: &[&str]| Want { weight, whole, net: false, universe: u.iter().map(|s| s.to_string()).collect() };
    let taken: HashSet<String> = ["d".to_string()].into_iter().collect();
    let out = assign_markets(
        &[w(1.0, false, &["a", "b", "c", "d", "e"]), w(3.0, false, &["a", "b", "c", "e"]), w(2.0, true, &["c", "f"])],
        &taken,
    );
    // The set claims c and f first; then the weight-3 sleeve deals before the weight-1 one.
    assert_eq!(out[2], vec!["c", "f"]);
    assert_eq!(out[1], vec!["a", "e"]);
    assert_eq!(out[0], vec!["b"]);
    // A set that overlaps a taken market gets nothing at all.
    let out = assign_markets(&[w(1.0, true, &["d", "g"])], &taken);
    assert!(out[0].is_empty());
}

#[test]
fn a_position_held_from_before_stays_outside_the_autopilot() {
    let mut e = engine();
    enter(&mut e, "ema-cross-1", ETH, 300.0);
    let id = start(&mut e, config("o", 1_000.0, &[("ema-cross-1", 1.0)], StopRules::default()));
    assert!(journal_has(&e, "Its strategies already hold ETH/USD elsewhere"));
    assert_eq!(status(&e, &id).open_positions, 0);
    // Its own book is empty, so it may trade ETH at once, next to the old one.
    enter(&mut e, "ema-cross-1", ETH, 100.0);
    assert_eq!(status(&e, &id).open_positions, 1);
    assert!(qty_in(&e, "", ETH) > 0.0 && qty_in(&e, &id, ETH) > 0.0, "two positions, two books");
    let before = status(&e, &id).equity;
    let half = e.price_of(ETH) * 0.5;
    set_price(&mut e, ETH, half);
    let loss_main = 300.0 * 0.5;
    assert!(before - status(&e, &id).equity < loss_main / 2.0, "the old position's loss is not the autopilot's");
    let s0 = status(&e, &id);
    e.flatten(ETH);
    let s = status(&e, &id);
    assert_eq!((s.trades, s.fees, s.open_positions), (s0.trades, s0.fees, 1), "and neither is its exit");
}

#[test]
fn a_flatten_from_the_positions_page_is_booked_to_the_autopilot() {
    let mut e = engine();
    let id = start(&mut e, config("fl", 1_000.0, &[("ema-cross-1", 1.0)], StopRules::default()));
    enter(&mut e, "ema-cross-1", BTC, 500.0);
    e.flatten(BTC);
    let s = status(&e, &id);
    assert_eq!((s.open_positions, s.trades), (0, 1));
    assert_eq!(s.by_sleeve[0].trades, 1);
    assert!((s.by_sleeve[0].pnl - s.pnl).abs() < 1e-9, "one sleeve, same P&L");
}

#[test]
fn stopping_without_flattening_hands_the_positions_back_at_their_price() {
    let mut e = engine();
    let id = start(&mut e, config("nf", 1_000.0, &[("ema-cross-1", 1.0)], StopRules::default()));
    enter(&mut e, "ema-cross-1", BTC, 500.0);
    equity_to(&mut e, &id, BTC, 1_020.0);
    e.autopilot_stop(&id, Some(false)).unwrap();
    assert!(holds(&e, BTC), "left open");
    let s = status(&e, &id);
    assert_eq!(s.open_positions, 0);
    assert!((s.equity - 1_020.0).abs() < 1e-7, "counted at its price when it stopped");
    let half = e.price_of(BTC) * 0.5;
    set_price(&mut e, BTC, half);
    assert!((status(&e, &id).equity - 1_020.0).abs() < 1e-7, "what happens to it later is not the autopilot's");
    assert!(journal_has(&e, "Left its 1 position(s) open"));
}

#[test]
fn auto_picks_runnable_strategies_by_evidence_and_explains_each() {
    let mut e = engine();
    let id = start(&mut e, config("auto", 1_000.0, &[], StopRules::default()));
    let s = status(&e, &id);
    assert!(!s.by_sleeve.is_empty());
    let ids: Vec<&str> = s.by_sleeve.iter().map(|x| x.strategy_id.as_str()).collect();
    assert!(ids.iter().all(|i| ["ema-cross-1", "multi-tf-1"].contains(i)), "only running crypto strategies: {ids:?}");
    assert!(!ids.contains(&"macd-1"), "a strategy paused on its evidence is never picked");
    assert!((s.by_sleeve.iter().map(|x| x.weight).sum::<f64>() - 1.0).abs() < 1e-9);
    for sl in &s.by_sleeve {
        assert!(sl.why.starts_with("Auto pick, ") && sl.why.contains("gates green") && sl.why.contains("% of the capital"), "{}", sl.why);
        assert!(sl.why.contains("its edge is not proven"), "nothing unvalidated is sold as proven: {}", sl.why);
        assert!(!sl.markets.is_empty());
    }

    // Live auto only takes strategies cleared for live.
    let mut e = engine();
    e.set_live(armed_crypto());
    let mut c = live_config("auto-live", 1_000.0, &[]);
    c.sleeves.clear();
    let err = e.autopilot_start(c.clone(), true, VenueCash::Read(1_000.0)).unwrap_err();
    assert!(err.contains("no strategy cleared for live"), "{err}");
    make_live_ready(&mut e, "multi-tf-1");
    let id = e.autopilot_start(c, true, VenueCash::Read(1_000.0)).unwrap();
    let s = status(&e, &id);
    assert_eq!(s.by_sleeve.len(), 1);
    assert_eq!(s.by_sleeve[0].strategy_id, "multi-tf-1");
    assert!(s.by_sleeve[0].why.contains("cleared for live"));
}

fn lab_signal(now: i64, weights: &[(&str, f64)]) -> crate::lab::LabSignal {
    crate::lab::LabSignal {
        strategy: "tsmom".into(),
        variant: "28d".into(),
        as_of_ms: now - 3_600_000,
        generated_ms: now,
        valid_until_ms: now + 36 * 3_600_000,
        quote: "USD".into(),
        weights: weights.iter().map(|(k, v)| (k.to_string(), *v)).collect(),
        regime_on: Some(true),
        evidence: crate::lab::LabEvidence { oos_sharpe: Some(1.1), deflated_p: Some(0.97), ..Default::default() },
        autopilot_only: false,
        dropped: vec![],
        asset_class: None,
        experimental: false,
    }
}

#[test]
fn a_lab_book_in_an_autopilot_rebalances_with_the_autopilots_money() {
    let mut e = engine();
    let now = e.now();
    e.apply_lab_signal(lab_signal(now, &[("BTC", 0.5), ("ETH", 0.25)]));
    let id = start(&mut e, config("lab", 10_000.0, &[("lab:tsmom", 1.0)], StopRules::default()));
    let s = status(&e, &id);
    let crypto = e.markets.iter().filter(|m| m.venue == Venue::Crypto).count();
    assert_eq!(s.by_sleeve[0].markets.len(), crypto, "a lab book claims every crypto market as one set");
    assert!(s.by_sleeve[0].why.contains("lab out-of-sample Sharpe 1.10, deflated p 0.97"), "{}", s.by_sleeve[0].why);
    e.run_lab_books();
    let btc = notional(&e, BTC);
    let eth = notional(&e, ETH);
    assert!((btc - 5_000.0).abs() < 60.0, "half of the autopilot's 10,000, not of the account: {btc}");
    assert!((eth - 2_500.0).abs() < 30.0, "{eth}");
    assert_eq!(status(&e, &id).open_positions, 2);

    // Paused: the book holds still even on a new signal.
    e.autopilot_pause(&id).unwrap();
    e.apply_lab_signal(lab_signal(now + 1, &[("BTC", 0.1)]));
    e.run_lab_books();
    assert!((notional(&e, BTC) - btc).abs() < 1e-9);

    // Stopped without flattening, its coins stay in its own book. The lab
    // book can join the next autopilot all the same: that one starts with an
    // empty book of its own.
    e.autopilot_stop(&id, Some(false)).unwrap();
    let id2 = start(&mut e, config("lab2", 10_000.0, &[("lab:tsmom", 1.0)], StopRules::default()));
    assert_eq!(status(&e, &id2).open_positions, 0);
    assert!(qty_in(&e, &id, BTC) > 0.0, "the first one's coins stay where they were");
    e.autopilot_stop(&id2, None).unwrap();

    // A lab book that trades on its own and holds coins in the main book
    // cannot be claimed: those coins would be left unmanaged.
    e.set_strategy_state("lab:tsmom", StrategyState::Paper).unwrap();
    e.lab_done.clear();
    e.run_lab_books();
    assert!(qty_in(&e, "", BTC) > 0.0, "the standalone run bought in the main book");
    let err = e.autopilot_start(config("lab3", 10_000.0, &[("lab:tsmom", 1.0)], StopRules::default()), false, VenueCash::NotRead).unwrap_err();
    assert!(err.contains("still holds coins from its own run"), "{err}");
}

// ── idle lab books (PYTHIA_LAB_BOOKS=idle) ─────────────────────────────────

/// The momentum book with the regime filter (reports/momentum2): gates 1 to 5
/// green, deflated p 0.86 over 50 variants.
fn regime_evidence() -> crate::lab::LabEvidence {
    crate::lab::LabEvidence {
        report: "momentum2".into(),
        is_sharpe: Some(1.97),
        oos_sharpe: Some(1.05),
        deflated_p: Some(0.86),
        sharpe_2x_cost: Some(0.93),
        variants_tried: Some(50),
        plateau_share: Some(1.0),
        regime_sharpes: [("BTC above 200d average".to_string(), 1.56), ("BTC below 200d average".to_string(), -0.4)]
            .into_iter()
            .collect(),
        regime_filter: true,
        ..Default::default()
    }
}

/// Donchian 20/10 on the top 10 (results/families_summary.md): no regime
/// filter, loses below the 200-day average, deflated p 0.01 over 100.
fn breakout_evidence() -> crate::lab::LabEvidence {
    crate::lab::LabEvidence {
        report: "families_summary".into(),
        is_sharpe: Some(1.40),
        oos_sharpe: Some(1.20),
        deflated_p: Some(0.01),
        sharpe_2x_cost: Some(1.08),
        variants_tried: Some(100),
        plateau_share: Some(1.0),
        plateau_variants: Some(6),
        regime_sharpes: [("BTC above 200d average".to_string(), 1.78), ("BTC below 200d average".to_string(), -0.55)]
            .into_iter()
            .collect(),
        regime_filter: false,
        ..Default::default()
    }
}

/// tsmom 28d on the top 20 of each day (results/families_summary.md).
fn top20_evidence() -> crate::lab::LabEvidence {
    crate::lab::LabEvidence {
        report: "families_summary".into(),
        is_sharpe: Some(1.44),
        oos_sharpe: Some(0.54),
        deflated_p: Some(0.0003),
        sharpe_2x_cost: Some(0.32),
        variants_tried: Some(100),
        plateau_share: Some(0.5625),
        plateau_variants: Some(16),
        regime_sharpes: [("BTC above 200d average".to_string(), 0.70), ("BTC below 200d average".to_string(), -2.29)]
            .into_iter()
            .collect(),
        regime_filter: true,
        ..Default::default()
    }
}

fn book(
    strategy: &str,
    generated: i64,
    weights: &[(&str, f64)],
    evidence: crate::lab::LabEvidence,
    autopilot_only: bool,
) -> crate::lab::LabSignal {
    crate::lab::LabSignal {
        strategy: strategy.into(),
        variant: strategy.into(),
        as_of_ms: generated - 3_600_000,
        generated_ms: generated,
        valid_until_ms: generated + 36 * 3_600_000,
        quote: "USD".into(),
        weights: weights.iter().map(|(k, v)| (k.to_string(), *v)).collect(),
        regime_on: None,
        evidence,
        autopilot_only,
        dropped: vec![],
        asset_class: None,
        experimental: false,
    }
}

/// An engine like the VPS autopilot engine: real prices, lab books idle.
fn idle_engine() -> Engine {
    let mut e = engine();
    e.set_lab_books_idle(true);
    e
}

fn held_by(e: &Engine, sid: &str) -> usize {
    e.positions.values().filter(|p| p.strategy_id == sid && p.qty.abs() > 1e-12).count()
}

#[test]
fn an_idle_lab_book_holds_nothing_does_not_trade_and_keeps_its_signal_up_to_date() {
    let mut e = idle_engine();
    let now = e.now();
    e.apply_lab_signal(book("breakout_top10", now, &[("BTC", 0.5), ("ETH", 0.25)], breakout_evidence(), false));
    assert_eq!(state_of(&e, "lab:breakout_top10"), StrategyState::Paused, "created idle, not in paper");
    assert!(journal_has(&e, "added, idle: it holds nothing and trades only inside an autopilot"));

    for _ in 0..3 {
        e.run_lab_books();
    }
    assert_eq!(held_by(&e, "lab:breakout_top10"), 0, "an idle book buys nothing");
    assert!(e.orders.iter().all(|o| o.strategy_id != "lab:breakout_top10"), "not even an order");

    // It cannot be switched on to trade by itself.
    let err = e.set_strategy_state("lab:breakout_top10", StrategyState::Paper).unwrap_err();
    assert!(err.contains("trades only inside an autopilot here, never on its own"), "{err}");
    assert_eq!(state_of(&e, "lab:breakout_top10"), StrategyState::Paused);

    // A new day: the signal and its evidence are replaced, and it still holds nothing.
    let mut ev = breakout_evidence();
    ev.oos_sharpe = Some(1.25);
    e.apply_lab_signal(book("breakout_top10", now + 86_400_000, &[("SOL", 0.1)], ev, false));
    let sig = &e.lab_signals["lab:breakout_top10"];
    assert_eq!(sig.generated_ms, now + 86_400_000);
    assert_eq!(sig.weights.keys().collect::<Vec<_>>(), vec!["SOL"]);
    assert_eq!(sig.evidence.oos_sharpe, Some(1.25));
    let gates = e.passport("lab:breakout_top10").unwrap().gates;
    assert_eq!(gates[5].status, validation::GateStatus::Fail, "gate 6 follows the new evidence: still fails deflation");
    e.run_lab_books();
    assert_eq!(held_by(&e, "lab:breakout_top10"), 0);
    assert_eq!(e.strategies.iter().filter(|s| s.id == "lab:breakout_top10").count(), 1, "one book, updated in place");
}

#[test]
fn an_autopilot_claims_an_idle_lab_book_rebalances_with_its_capital_and_stopping_makes_it_idle_again() {
    let mut e = idle_engine();
    let now = e.now();
    e.apply_lab_signal(book("tsmom_regime", now, &[("BTC", 0.5), ("ETH", 0.25)], regime_evidence(), false));
    let id = start(&mut e, config("lab", 10_000.0, &[("lab:tsmom_regime", 1.0)], StopRules::default()));
    assert_eq!(state_of(&e, "lab:tsmom_regime"), StrategyState::Paper, "claimed: it trades for the autopilot");
    e.run_lab_books();
    let (btc, eth) = (notional(&e, BTC), notional(&e, ETH));
    assert!((btc - 5_000.0).abs() < 60.0, "half of the autopilot's 10,000, not of the 100,000 account: {btc}");
    assert!((eth - 2_500.0).abs() < 30.0, "{eth}");
    let s = status(&e, &id);
    assert_eq!(s.open_positions, 2, "both positions are the autopilot's");
    assert!(s.fees > 0.0, "and so are their fees");

    // Stop with the default flatten: everything is closed and the book is idle again.
    e.autopilot_stop(&id, None).unwrap();
    assert_eq!(held_by(&e, "lab:tsmom_regime"), 0);
    assert_eq!(state_of(&e, "lab:tsmom_regime"), StrategyState::Paused);
    assert!(journal_has(&e, "Idle again, waiting for the next autopilot"));
    e.apply_lab_signal(book("tsmom_regime", now + 1, &[("BTC", 0.3)], regime_evidence(), false));
    e.run_lab_books();
    assert_eq!(held_by(&e, "lab:tsmom_regime"), 0, "idle again: a new signal moves nothing");

    // Flat, so the next autopilot can claim it, on its own capital.
    let id2 = start(&mut e, config("lab2", 2_000.0, &[("lab:tsmom_regime", 1.0)], StopRules::default()));
    e.run_lab_books();
    assert!((notional(&e, BTC) - 600.0).abs() < 10.0, "30 % of 2,000: {}", notional(&e, BTC));

    // Stopped without flattening, its coins stay open and unmanaged in its
    // book, and that is said. The next autopilot starts with a book of its
    // own, so the coins left in the old one do not keep the lab book out.
    e.autopilot_stop(&id2, Some(false)).unwrap();
    assert_eq!(held_by(&e, "lab:tsmom_regime"), 1);
    assert_eq!(state_of(&e, "lab:tsmom_regime"), StrategyState::Paused);
    assert!(journal_has(&e, "1 of them belong to a lab book, which carries no stops"));
    let id3 = start(&mut e, config("lab3", 2_000.0, &[("lab:tsmom_regime", 1.0)], StopRules::default()));
    e.run_lab_books();
    assert!((qty_in(&e, &id3, BTC) * e.price_of(BTC) - 600.0).abs() < 10.0, "lab3 buys its own 30 %");
    assert!(qty_in(&e, &id2, BTC) > 0.0, "and the coins lab2 left stay in lab2's book");
}

#[test]
fn an_autopilot_only_signal_keeps_its_book_idle_on_a_default_engine() {
    // No PYTHIA_LAB_BOOKS here: an ordinary lab book still runs standalone
    // exactly as before, but a signal marked autopilot-only stays idle.
    let mut e = engine();
    let now = e.now();
    e.apply_lab_signal(book("tsmom_regime", now, &[("BTC", 0.05)], regime_evidence(), false));
    e.apply_lab_signal(book("breakout_top10", now, &[("ETH", 0.05)], breakout_evidence(), true));
    assert_eq!(state_of(&e, "lab:tsmom_regime"), StrategyState::Paper);
    assert_eq!(state_of(&e, "lab:breakout_top10"), StrategyState::Paused);
    e.run_lab_books();
    assert_eq!(held_by(&e, "lab:tsmom_regime"), 1, "the standalone book trades as before");
    assert_eq!(held_by(&e, "lab:breakout_top10"), 0, "the autopilot-only book does not");
    assert!(e.set_strategy_state("lab:breakout_top10", StrategyState::Paper).is_err());

    // A book saved in paper and restored before its signal arrived (or
    // resumed by PYTHIA_LAB_ONLY) goes idle again with its next signal.
    let mut r = Engine::new();
    r.apply_persisted(e.to_persisted());
    mark_real(&mut r);
    r.set_strategy_state("lab:breakout_top10", StrategyState::Paper).unwrap();
    r.apply_lab_signal(book("breakout_top10", now + 1, &[("ETH", 0.05)], breakout_evidence(), true));
    assert_eq!(state_of(&r, "lab:breakout_top10"), StrategyState::Paused);
    assert!(journal_has(&r, "Lab book is idle: it trades only inside an autopilot"));
    r.run_lab_books();
    assert_eq!(held_by(&r, "lab:breakout_top10"), 0);
}

#[test]
fn turning_idle_on_pauses_running_lab_books_and_names_coins_they_still_hold() {
    let mut e = engine();
    let now = e.now();
    e.apply_lab_signal(book("tsmom_regime", now, &[("BTC", 0.05)], regime_evidence(), false));
    e.run_lab_books();
    assert_eq!(held_by(&e, "lab:tsmom_regime"), 1);
    e.set_lab_books_idle(true);
    assert_eq!(state_of(&e, "lab:tsmom_regime"), StrategyState::Paused);
    assert!(journal_has(&e, "it still holds BTC/USD from before, left open and unmanaged"));
    assert_eq!(held_by(&e, "lab:tsmom_regime"), 1, "nothing is sold behind the owner's back");
}

#[test]
fn auto_picks_the_lab_book_with_the_best_evidence_and_never_calls_it_proven() {
    let mut e = idle_engine();
    let now = e.now();
    let w = &[("BTC", 0.3), ("ETH", 0.2)];
    e.apply_lab_signal(book("tsmom_top20", now, w, top20_evidence(), true));
    e.apply_lab_signal(book("breakout_top10", now, w, breakout_evidence(), true));
    e.apply_lab_signal(book("tsmom_regime", now, w, regime_evidence(), false));
    let id = start(&mut e, config("auto", 10_000.0, &[], StopRules::default()));
    let s = status(&e, &id);
    // Lab books net their targets per coin, so up to three run together,
    // weighted by their scores; the built-ins on crypto have nothing left.
    let ids: Vec<&str> = s.by_sleeve.iter().map(|x| x.strategy_id.as_str()).collect();
    assert_eq!(ids, ["lab:tsmom_regime", "lab:breakout_top10", "lab:tsmom_top20"], "best evidence first");
    let scores: Vec<f64> = ids.iter().map(|i| e.evidence(i).score().unwrap()).collect();
    let total: f64 = scores.iter().sum();
    for (sl, sc) in s.by_sleeve.iter().zip(&scores) {
        assert!((sl.weight - sc / total).abs() < 1e-9, "weight proportional to score: {} vs {}", sl.weight, sc / total);
        assert!(sl.why.contains("netted per coin with the other 2 lab book(s)"), "{}", sl.why);
    }
    let sl = &s.by_sleeve[0];
    assert_eq!(sl.strategy_id, "lab:tsmom_regime", "5 gates green and deflated p 0.86 beat the families' candidates");
    assert_eq!(sl.markets.len(), e.markets.iter().filter(|m| m.venue == Venue::Crypto).count());
    assert!(sl.why.starts_with("Auto pick, the best evidence of the "), "{}", sl.why);
    assert!(
        sl.why.contains("lab out-of-sample Sharpe 1.05, deflated p 0.86 over 50 variants, Sharpe 0.93 with costs doubled"),
        "{}",
        sl.why
    );
    assert!(
        sl.why.contains(
            "it fails the deflation test (deflated p 0.86, 0.95 needed), so it is picked as the best available evidence, not as a proven edge"
        ),
        "{}",
        sl.why
    );
    let msg = s.last_action.unwrap();
    assert!(msg.contains("Auto passed over EMA Cross") && !msg.contains("passed over Lab"), "{msg}");
    assert!(msg.contains("re-runs the pick with fresh evidence every 24 h"), "{msg}");
    e.run_lab_books();
    // All three want BTC 0.3 and ETH 0.2: netted, still 0.3 and 0.2 of the 10,000.
    assert!((notional(&e, BTC) - 3_000.0).abs() < 40.0, "it rebalances with the autopilot's 10,000: {}", notional(&e, BTC));
    assert_eq!(e.positions.len(), 2, "one position per coin, not one per book");
    e.autopilot_stop(&id, None).unwrap();

    // Without the regime book, breakout's robustness beats top 20's weaker numbers.
    let mut e = idle_engine();
    e.apply_lab_signal(book("tsmom_top20", now, w, top20_evidence(), true));
    e.apply_lab_signal(book("breakout_top10", now, w, breakout_evidence(), true));
    let id = start(&mut e, config("auto2", 10_000.0, &[], StopRules::default()));
    let sl = status(&e, &id).by_sleeve.remove(0);
    assert_eq!(sl.strategy_id, "lab:breakout_top10");
    assert!(sl.why.contains("deflated p 0.01 over 100 variants, Sharpe 1.08 with costs doubled"), "{}", sl.why);
    assert!(sl.why.contains("it fails the deflation test (deflated p 0.01, 0.95 needed)"), "{}", sl.why);

    // A built-in with a green passport out-scores them all: it gets its
    // markets and the lab books, which would need all of crypto, are passed over.
    let mut e = idle_engine();
    e.apply_lab_signal(book("tsmom_regime", now, w, regime_evidence(), false));
    make_live_ready(&mut e, "multi-tf-1");
    let id = start(&mut e, config("auto3", 10_000.0, &[], StopRules::default()));
    let s = status(&e, &id);
    assert_eq!(s.by_sleeve[0].strategy_id, "multi-tf-1");
    assert!(!s.by_sleeve[0].why.contains("best available evidence"), "a green passport needs no caveat: {}", s.by_sleeve[0].why);
    assert!(s.by_sleeve.iter().all(|x| !x.strategy_id.starts_with("lab:")));
    assert_eq!(state_of(&e, "lab:tsmom_regime"), StrategyState::Paused, "passed over: still idle");
    assert!(s.last_action.unwrap().contains("Lab · tsmom_regime"));
}

#[test]
fn auto_skips_a_lab_book_whose_signal_has_expired() {
    let mut e = idle_engine();
    let old = e.now() - 48 * 3_600_000;
    e.apply_lab_signal(book("tsmom_regime", old, &[("BTC", 0.3)], regime_evidence(), false));
    let id = start(&mut e, config("auto", 1_000.0, &[], StopRules::default()));
    assert!(status(&e, &id).by_sleeve.iter().all(|x| x.strategy_id != "lab:tsmom_regime"), "a stale book would only hold cash");
}

#[test]
fn a_survivorship_free_measurement_lowers_the_lab_sharpe_and_the_pick_says_why() {
    let mut l = regime_evidence();
    l.oos_sharpe_survivorship_free = Some(0.54);
    l.caveat = Some("the same rule on the 20 most liquid coins of each day made Sharpe 0.54, not 1.05".into());
    let mut e = idle_engine();
    let now = e.now();
    e.apply_lab_signal(book("tsmom_regime", now, &[("BTC", 0.3)], l, false));
    let id = start(&mut e, config("auto", 1_000.0, &[], StopRules::default()));
    let s = status(&e, &id);
    let why = &s.by_sleeve.iter().find(|x| x.strategy_id == "lab:tsmom_regime").expect("still the only lab book").why;
    assert!(why.contains("Sharpe 0.54"), "the lower Sharpe is the one shown: {why}");
    assert!(!why.contains("Sharpe 1.05"), "{why}");
    assert!(why.contains("also, the same rule on the 20 most liquid coins"), "{why}");
}

#[test]
fn the_score_ranks_evidence_and_the_caveat_never_oversells() {
    let ev = |l: crate::lab::LabEvidence, passed: usize, failed: usize| Evidence {
        passed,
        failed,
        lab: true,
        lab_oos_sharpe: l.oos_sharpe,
        lab_deflated_p: l.deflated_p,
        lab_variants: l.variants_tried,
        lab_sharpe_2x_cost: l.sharpe_2x_cost,
        ..Default::default()
    };
    // Gates as lab::verdict judges them: regime 5 green / 1 red, breakout 4 / 2, top 20 3 / 3.
    let regime = ev(regime_evidence(), 5, 1);
    let breakout = ev(breakout_evidence(), 4, 2);
    let top20 = ev(top20_evidence(), 3, 3);
    let builtin = Evidence::default();
    let (r, b, t, n) = (regime.score().unwrap(), breakout.score().unwrap(), top20.score().unwrap(), builtin.score().unwrap());
    assert!((r - (1.0 + 5.0 + 1.05 + 0.465 + 0.86) / 2.0).abs() < 1e-9, "{r}");
    assert!((b - (1.0 + 4.0 + 1.20 + 0.54 + 0.01) / 3.0).abs() < 1e-9, "{b}");
    assert!(r > b && b > t && t > n, "regime {r:.3} > breakout {b:.3} > top 20 {t:.3} > an unchecked built-in {n:.3}");

    // A negative Sharpe adds nothing, it does not subtract below the gates.
    let mut losing = breakout_evidence();
    losing.oos_sharpe = Some(-0.5);
    losing.sharpe_2x_cost = Some(-0.9);
    assert!((ev(losing, 4, 2).score().unwrap() - (1.0 + 4.0 + 0.01) / 3.0).abs() < 1e-9);

    // Deflation passed and every gate green: no caveat. Failed: always one.
    let proven = Evidence { live_ready: true, lab: true, lab_deflated_p: Some(0.97), ..Default::default() };
    assert!(proven.caveat().is_none());
    let almost = Evidence { lab: true, lab_deflated_p: Some(0.97), ..Default::default() };
    assert_eq!(almost.caveat().unwrap(), "its edge is not proven: not every gate is green, so it is picked as the best available evidence");
    assert!(Evidence { lab: true, ..Default::default() }.caveat().unwrap().contains("gives no deflated Sharpe"));
    assert!(breakout.caveat().unwrap().starts_with("it fails the deflation test (deflated p 0.01, 0.95 needed)"));
    assert!(regime.auto_why(0, 1).starts_with("Auto pick, the only strategy it could run here (5 of 8 gates green, 1 failed"));
    assert!(breakout.auto_why(1, 4).starts_with("Auto pick, number 2 of 4 by evidence ("));
}

#[test]
fn evidence_weights_measured_edges_up_and_rules_out_no_edge() {
    let base = Evidence { passed: 3, ..Default::default() };
    let measured = Evidence { measured: true, kelly: 0.05, ..base.clone() };
    let ready = Evidence { live_ready: true, passed: 7, ..base.clone() };
    let failing = Evidence { failed: 2, ..base.clone() };
    assert!(measured.score().unwrap() > base.score().unwrap());
    assert!(ready.score().unwrap() > measured.score().unwrap());
    assert!(failing.score().unwrap() < base.score().unwrap());
    assert!(Evidence { no_edge: true, ..base.clone() }.score().is_none());
    assert!(measured.describe().contains("a measured edge (Kelly 0.050)"));
    assert_eq!(base.describe(), "3 of 8 gates green, no forward record yet");
}

// ── validation and the wire ────────────────────────────────────────────────

#[test]
fn a_bad_config_is_refused_in_plain_words() {
    let mut e = engine();
    let mut go = |c: AutopilotConfig| e.autopilot_start(c, false, VenueCash::NotRead).unwrap_err();
    assert!(go(config("v", 0.0, &[("ema-cross-1", 1.0)], StopRules::default())).contains("above zero"));
    assert!(go(config("v", 1_000.0, &[("ema-cross-1", 1.0)], StopRules { trailing_pct: Some(100.0), ..Default::default() }))
        .contains("trailing floor"));
    assert!(go(config("v", 1_000.0, &[("ema-cross-1", 1.0)], StopRules { max_loss_usd: Some(2_000.0), ..Default::default() }))
        .contains("at most the amount"));
    assert!(go(config("v", 1_000.0, &[("ema-cross-1", 1.0)], StopRules { end_ms: Some(1), ..Default::default() })).contains("past"));
    assert!(go(config("v", 1_000.0, &[("nope", 1.0)], StopRules::default())).contains("no strategy \"nope\""));
    assert!(go(config("v", 1_000.0, &[("prob-edge-1", 1.0)], StopRules::default())).contains("not this autopilot's venue"));
    assert!(go(config("v", 1_000_000.0, &[("ema-cross-1", 1.0)], StopRules::default())).contains("paper account holds $100,000.00"));
    let mut c = config("v", 1_000.0, &[("ema-cross-1", 1.0)], StopRules::default());
    c.venue = "binance".into();
    assert!(go(c).contains("Crypto here executes on Kraken"));
    let mut c = config("v", 1_000.0, &[("prob-edge-1", 1.0)], StopRules::default());
    c.venue = "polymarket".into();
    c.mode = AutopilotMode::Demo;
    assert!(go(c).contains("only run on paper"));
    // A strategy the owner runs live on its own is not quietly taken off live.
    make_live_ready(&mut e, "multi-tf-1");
    e.set_strategy_state("multi-tf-1", StrategyState::Live).unwrap();
    let err = e.autopilot_start(config("v", 1_000.0, &[("multi-tf-1", 1.0)], StopRules::default()), false, VenueCash::NotRead).unwrap_err();
    assert!(err.contains("runs live on its own. A paper autopilot would take it off live"), "{err}");
    let id = start(&mut e, config("v", 1_000.0, &[], StopRules::default()));
    assert!(status(&e, &id).by_sleeve.iter().all(|s| s.strategy_id != "multi-tf-1"), "auto leaves it alone too");
    assert_eq!(state_of(&e, "multi-tf-1"), StrategyState::Live);
    e.autopilot_stop(&id, None).unwrap();

    e.toggle_kill();
    let err = e.autopilot_start(config("w", 1_000.0, &[("ema-cross-1", 1.0)], StopRules::default()), false, VenueCash::NotRead).unwrap_err();
    assert!(err.contains("kill switch"));
}

#[test]
fn the_state_carries_autopilots_in_the_camel_case_the_ui_expects() {
    let mut e = engine();
    let id = start(&mut e, config("w", 1_000.0, &[("ema-cross-1", 1.0)], StopRules { max_loss_pct: Some(10.0), ..Default::default() }));
    let v = serde_json::to_value(e.state()).unwrap();
    let ap = &v["autopilots"][0];
    assert_eq!(ap["config"]["id"], id.as_str());
    assert_eq!(ap["config"]["capitalUsd"], 1_000.0);
    assert_eq!(ap["config"]["mode"], "paper");
    assert_eq!(ap["config"]["stop"]["maxLossPct"], 10.0);
    assert_eq!(ap["config"]["stop"]["onTakeProfit"], "stop");
    assert_eq!(ap["config"]["flattenOnStop"], true);
    assert_eq!(ap["state"], "running");
    assert!(ap["stopReason"].is_null());
    for key in ["startedMs", "startCapital", "equity", "pnl", "pnlPct", "peakEquity", "drawdownPct", "floorEquity", "trades", "fees", "lastAction"] {
        assert!(ap.get(key).is_some(), "missing {key}");
    }
    assert_eq!(ap["bySleeve"][0]["strategyId"], "ema-cross-1");
    assert!(ap["bySleeve"][0]["why"].as_str().unwrap().starts_with("Chosen by you"));
    assert!(ap["history"][0].is_array() && ap["history"][0][1] == 1_000.0);

    // And the command shape the UI sends deserialises, with every optional
    // stop rule left out.
    let cfg: AutopilotConfig = serde_json::from_value(serde_json::json!({
        "id": "", "name": "x", "mode": "demo", "venue": "kraken", "capitalUsd": 250,
        "sleeves": [], "stop": { "onTakeProfit": "lock" }, "flattenOnStop": false
    }))
    .unwrap();
    assert_eq!(cfg.mode, AutopilotMode::Demo);
    assert_eq!(cfg.stop.on_take_profit, OnTakeProfit::Lock);
    assert!(cfg.stop.max_loss_pct.is_none() && !cfg.flatten_on_stop);
}

// ── seams with demo, live, feeds and the book walk ─────────────────────────

/// A demo autopilot whose entries go out to the demo venue and wait there.
fn demo_engine(id: &str, capital: f64) -> (Engine, String) {
    let mut e = engine();
    e.set_demo_venues([Venue::Crypto].into_iter().collect(), Some(CostVenue::Bybit), true);
    let mut c = config(id, capital, &[("ema-cross-1", 1.0)], StopRules::default());
    c.mode = AutopilotMode::Demo;
    let id = start(&mut e, c);
    (e, id)
}

#[test]
fn orders_still_at_the_venue_count_against_the_sleeves_room() {
    // Demo and live entries fill when the venue says so. Until then the
    // autopilot has no position, so every signal in the same tick used to be
    // sized from the full room again and together they committed more than X.
    let (mut e, id) = demo_engine("pend", 1_000.0);
    let markets = status(&e, &id).by_sleeve[0].markets.clone();
    assert!(markets.len() >= 7, "a sleeve on many markets");
    let i = idx(&e, "ema-cross-1");
    for mk in &markets {
        let m = market(&e, mk);
        e.place_from_intent(&id, i, &m, &buy_intent(mk));
    }
    let out = e.drain_live_orders();
    assert!(out.len() > 1 && out.iter().all(|o| o.demo), "several demo entries went out: {}", out.len());
    let sent: f64 = out.iter().map(|o| o.qty * o.ref_price).sum();
    assert!(sent <= 1_000.0 + 1e-6, "orders in flight never commit more than the autopilot's $1,000: {sent}");
    let room = e.autopilot_sizing(&id, "ema-cross-1").unwrap().room;
    assert!(room < 1_000.0 - sent + 1e-6, "what is in flight is not room any more: {room}");

    // A partial fill moves part of it from "in flight" to "held": the room
    // stays what it was, give or take the fee.
    let o = &out[0];
    e.apply_live_ack(&o.order_id, "venue-1");
    let half = o.qty / 2.0;
    e.apply_live_update(
        &o.order_id,
        LiveUpdate { status: BrokerOrderStatus::PartiallyFilled, filled_qty: half, avg_price: Some(o.ref_price), fee: 0.0, fee_base: 0.0, fee_unpriced: Vec::new(), raw_status: "partially_filled".into() },
    );
    assert_eq!(status(&e, &id).open_positions, 1, "the partial fill is the autopilot's");
    let after = e.autopilot_sizing(&id, "ema-cross-1").unwrap().room;
    assert!((after - room).abs() < 1e-6, "no room appears out of a partial fill: {room} then {after}");
}

#[test]
fn an_entry_that_uses_the_last_room_leaves_exposure_within_equity_after_its_costs() {
    // The room is equity minus what is held, at the mark. The fill then pays
    // the walk past the mark and the fee out of that same equity, so an entry
    // sized to the whole room ended with more exposure than equity.
    let mut e = engine();
    let id = start(&mut e, config("cost", 100.0, &[("ema-cross-1", 1.0)], StopRules::default()));
    enter(&mut e, "ema-cross-1", BTC, 95.0);
    let i = idx(&e, "ema-cross-1");
    let m = market(&e, ETH);
    e.place_from_intent(&id, i, &m, &buy_intent(ETH));
    assert!(holds(&e, ETH), "the last room was used");
    let gross: f64 = [BTC, ETH].iter().map(|m| notional(&e, m)).sum();
    let equity = status(&e, &id).equity;
    assert!(gross <= equity + 1e-9, "exposure {gross} within the equity left after costs {equity}");
}

/// Age a market's price past the staleness limit, as a dead or refused feed does.
fn make_stale(e: &mut Engine, market: &str) {
    let old = e.now() - (e.limits.max_data_staleness_sec as i64 + 60) * 1000;
    e.markets.iter_mut().find(|m| m.id == market).unwrap().updated_at = old;
}

#[test]
fn a_stop_does_not_close_a_paper_position_at_a_stale_price() {
    // Every other exit waits for a fresh price; the autopilot's flatten booked
    // its paper close at whatever the last price was, minutes old.
    let mut e = engine();
    let id = start(&mut e, config("stale", 1_000.0, &[("ema-cross-1", 1.0)], StopRules::default()));
    enter(&mut e, "ema-cross-1", BTC, 500.0);
    make_stale(&mut e, BTC);
    e.autopilot_stop(&id, None).unwrap();
    assert!(holds(&e, BTC), "not closed at a stale price");
    let s = status(&e, &id);
    assert_eq!(s.open_positions, 1, "still the autopilot's, to be closed");
    let last = s.last_action.unwrap();
    assert!(last.contains("fresh price"), "says why it waits: {last}");
    assert!(!last.contains("live routing"), "and does not blame live routing: {last}");

    step(&mut e);
    assert!(holds(&e, BTC), "still waiting while the price is stale");
    let p = e.price_of(BTC);
    set_price(&mut e, BTC, p);
    step(&mut e);
    assert!(!holds(&e, BTC), "closed with the first fresh price");
    assert_eq!(status(&e, &id).open_positions, 0);
}

#[test]
fn a_demo_stop_says_its_closes_are_at_the_venue_not_that_live_routing_is_off() {
    let (mut e, id) = demo_engine("dstop", 1_000.0);
    let i = idx(&e, "ema-cross-1");
    let m = market(&e, BTC);
    e.place_from_intent(&id, i, &m, &buy_intent(BTC));
    let o = e.drain_live_orders().remove(0);
    e.apply_live_ack(&o.order_id, "venue-1");
    e.apply_live_update(
        &o.order_id,
        LiveUpdate { status: BrokerOrderStatus::Filled, filled_qty: o.qty, avg_price: Some(o.ref_price), fee: 0.1, fee_base: 0.0, fee_unpriced: Vec::new(), raw_status: "filled".into() },
    );
    assert_eq!(status(&e, &id).open_positions, 1);

    e.autopilot_stop(&id, None).unwrap();
    let out = e.drain_live_orders();
    assert_eq!(out.len(), 1, "the close went to the demo venue");
    assert!(out[0].demo && out[0].side == Side::Sell);
    let last = status(&e, &id).last_action.unwrap();
    assert!(!last.contains("live routing"), "a demo close in flight is not a live routing problem: {last}");
    assert!(last.contains("at the venue"), "{last}");

    // The close fills: booked to the stopped autopilot, nothing left.
    e.apply_live_ack(&out[0].order_id, "venue-2");
    e.apply_live_update(
        &out[0].order_id,
        LiveUpdate { status: BrokerOrderStatus::Filled, filled_qty: out[0].qty, avg_price: Some(o.ref_price * 1.01), fee: 0.1, fee_base: 0.0, fee_unpriced: Vec::new(), raw_status: "filled".into() },
    );
    let s = status(&e, &id);
    assert_eq!((s.open_positions, s.trades), (0, 1));
    assert!((s.fees - 0.2).abs() < 1e-9, "both demo fees are the autopilot's: {}", s.fees);
}

#[test]
fn a_demo_entry_that_fills_after_the_stop_is_booked_and_closed_again() {
    let (mut e, id) = demo_engine("late", 1_000.0);
    let i = idx(&e, "ema-cross-1");
    let m = market(&e, BTC);
    e.place_from_intent(&id, i, &m, &buy_intent(BTC));
    let o = e.drain_live_orders().remove(0);
    e.apply_live_ack(&o.order_id, "venue-1");
    e.autopilot_stop(&id, None).unwrap();
    assert_eq!(status(&e, &id).open_positions, 0, "nothing filled yet");

    e.apply_live_update(
        &o.order_id,
        LiveUpdate { status: BrokerOrderStatus::Filled, filled_qty: o.qty, avg_price: Some(o.ref_price), fee: 0.1, fee_base: 0.0, fee_unpriced: Vec::new(), raw_status: "filled".into() },
    );
    assert_eq!(status(&e, &id).open_positions, 1, "the late fill is the stopped autopilot's");
    step(&mut e);
    let out = e.drain_live_orders();
    assert_eq!(out.len(), 1, "and its close goes back to the demo venue");
    assert!(out[0].demo && out[0].side == Side::Sell);
}

// ── forward evidence in the auto pick ──────────────────────────────────────

/// One row of `reports/forward/evidence.json`.
fn fwd(days: f64, ret: f64, lo: f64, hi: f64) -> crate::lab::ForwardEvidence {
    crate::lab::ForwardEvidence {
        days,
        return_pct: Some(ret),
        band_low_pct: Some(lo),
        band_high_pct: Some(hi),
        band_method: Some("bootstrap".into()),
        status: String::new(),
        state: None,
        started_ms: None,
        experimental: false,
    }
}

fn forward_file(generated_ms: i64, books: &[(&str, crate::lab::ForwardEvidence)]) -> crate::lab::ForwardFile {
    crate::lab::ForwardFile {
        generated_ms,
        books: books.iter().map(|(k, v)| (k.to_string(), v.clone())).collect(),
        autopilots: Default::default(),
    }
}

/// The regime book and the breakout book, both idle, as on the autopilot engine.
fn two_books() -> Engine {
    let mut e = idle_engine();
    let now = e.now();
    let w = &[("BTC", 0.3), ("ETH", 0.2)];
    e.apply_lab_signal(book("breakout_top10", now, w, breakout_evidence(), true));
    e.apply_lab_signal(book("tsmom_regime", now, w, regime_evidence(), false));
    e
}

#[test]
fn a_forward_record_below_its_band_after_ten_days_halves_the_score_and_says_why() {
    let mut e = two_books();
    let base = e.evidence("lab:tsmom_regime").score().unwrap();
    let now = e.now();
    e.apply_lab_forward(forward_file(now, &[("tsmom_regime", fwd(12.0, -9.5, -4.0, 5.0))]));
    let ev = e.evidence("lab:tsmom_regime");
    assert!(ev.forward_below());
    assert!((ev.score().unwrap() - base * FORWARD_BELOW_FACTOR).abs() < 1e-9);
    assert!(
        ev.describe().contains("lab paper book 12 days at -9.50 %, below its backtest's range (-4.00 to +5.00 %), so its score is halved"),
        "{}",
        ev.describe()
    );
    assert!(ev.caveat().unwrap().contains("its forward record is below what its backtest led us to expect"));

    // Halved, regime (4.19 -> 2.09) falls behind breakout (2.25): both still
    // run, netted, but breakout now leads and regime gets the smaller weight.
    let id = start(&mut e, config("auto", 10_000.0, &[], StopRules::default()));
    let s = status(&e, &id);
    assert_eq!(s.by_sleeve[0].strategy_id, "lab:breakout_top10");
    assert_eq!(s.by_sleeve[1].strategy_id, "lab:tsmom_regime");
    assert!(s.by_sleeve[1].weight < s.by_sleeve[0].weight);
    assert!(s.by_sleeve[1].why.contains("so its score is halved"), "{}", s.by_sleeve[1].why);
}

#[test]
fn a_lab_book_whose_rebalancing_trims_lost_is_left_out_by_default_and_judged_by_the_forward_report_when_set() {
    // 35 trims each losing about a round trip of fees: "no edge" on the record,
    // which is what took breakout_top10 out of the main auto pick after a week.
    let mut e = two_books();
    let i = idx(&e, "lab:breakout_top10");
    for k in 0..35 {
        e.strategies[i].ledger.edge.record(if k % 6 == 0 { 0.002 } else { -0.005 });
    }
    e.strategies[i].ledger.forward_trades = 35;
    assert!(e.limits.lab_edge_from_trades, "on by default: the behaviour so far");
    let ev = e.evidence("lab:breakout_top10");
    assert!(ev.no_edge && ev.score().is_none());
    let id = start(&mut e, config("auto", 10_000.0, &[], StopRules::default()));
    let ids: Vec<String> = status(&e, &id).by_sleeve.into_iter().map(|b| b.strategy_id).collect();
    assert!(!ids.contains(&"lab:breakout_top10".to_string()), "{ids:?}");
    e.autopilot_stop(&id, None).unwrap();

    // Off: the trims neither measure nor rule out an edge; the lab evidence and
    // the forward report (here none yet) decide, and the record is still shown.
    let mut limits = e.limits.clone();
    limits.lab_edge_from_trades = false;
    e.set_limits(limits);
    let ev = e.evidence("lab:breakout_top10");
    assert!(!ev.no_edge && !ev.measured);
    assert!(ev.describe().contains("35 forward trades netting"), "{}", ev.describe());
    let id = start(&mut e, config("auto2", 10_000.0, &[], StopRules::default()));
    let ids: Vec<String> = status(&e, &id).by_sleeve.into_iter().map(|b| b.strategy_id).collect();
    assert!(ids.contains(&"lab:breakout_top10".to_string()), "{ids:?}");
    // A built-in strategy's record still counts: the setting is for lab books only.
    let j = idx(&e, "ema-cross-1");
    for _ in 0..35 {
        e.strategies[j].ledger.edge.record(-0.005);
    }
    assert!(e.evidence("ema-cross-1").no_edge);
    // A save from before the setting existed loads with it on.
    let old: RiskLimits = serde_json::from_value({
        let mut v = serde_json::to_value(RiskLimits::default()).unwrap();
        v.as_object_mut().unwrap().remove("labEdgeFromTrades");
        v
    })
    .unwrap();
    assert!(old.lab_edge_from_trades);
}

#[test]
fn under_ten_days_the_forward_record_changes_nothing() {
    let mut e = two_books();
    let base = e.evidence("lab:tsmom_regime").score().unwrap();
    let now = e.now();
    // Thirty points under its band, but only nine days in.
    e.apply_lab_forward(forward_file(now, &[("tsmom_regime", fwd(9.0, -30.0, -3.0, 4.0))]));
    let ev = e.evidence("lab:tsmom_regime");
    assert!(!ev.forward_below());
    assert_eq!(ev.score().unwrap(), base, "the score is exactly what it was without the report");
    assert!(ev.describe().contains("lab paper book 9 days at -30.00 %, too early to count (10 needed)"), "{}", ev.describe());
    assert!(!ev.caveat().unwrap().contains("forward record"));
    let id = start(&mut e, config("auto", 10_000.0, &[], StopRules::default()));
    let sl = &status(&e, &id).by_sleeve[0];
    assert_eq!(sl.strategy_id, "lab:tsmom_regime", "the pick is the one without forward data");
    assert!(sl.why.contains("too early to count"), "the reason is shown: {}", sl.why);
}

#[test]
fn an_old_report_and_a_record_inside_its_band_do_not_lower_the_pick() {
    let mut e = two_books();
    let base = e.evidence("lab:tsmom_regime").score().unwrap();
    let now = e.now();
    // Four days old: the daily job stopped, so its numbers are not used.
    e.apply_lab_forward(forward_file(now - FORWARD_STALE_MS - 3_600_000, &[("tsmom_regime", fwd(20.0, -9.0, -4.0, 5.0))]));
    let ev = e.evidence("lab:tsmom_regime");
    assert!(ev.forward.is_none() && ev.score().unwrap() == base);

    e.apply_lab_forward(forward_file(now, &[("tsmom_regime", fwd(15.0, 1.2, -4.0, 5.0))]));
    let ev = e.evidence("lab:tsmom_regime");
    assert_eq!(ev.score().unwrap(), base, "inside the band: no bonus, no penalty");
    assert!(ev.describe().contains("lab paper book 15 days at +1.20 %, inside its backtest's range (-4.00 to +5.00 %)"), "{}", ev.describe());

    // Above it: still no bonus, a lucky stretch buys nothing.
    e.apply_lab_forward(forward_file(now, &[("tsmom_regime", fwd(15.0, 9.0, -4.0, 5.0))]));
    assert_eq!(e.evidence("lab:tsmom_regime").score().unwrap(), base);
    // A built-in strategy is never matched to a lab book.
    e.apply_lab_forward(forward_file(now, &[("ema-cross-1", fwd(15.0, -9.0, -4.0, 5.0))]));
    assert!(e.evidence("ema-cross-1").forward.is_none());
}

#[test]
fn the_running_autopilot_carries_its_forward_status() {
    let mut e = engine();
    let id = start(&mut e, config("fw", 1_000.0, &[("ema-cross-1", 1.0)], StopRules::default()));
    // No report yet and one day old at most: too early.
    let f = status(&e, &id).forward.expect("a young autopilot is too early");
    assert_eq!(f.status, "early");
    assert!(f.days < 1.0);

    let started = status(&e, &id).started_ms;
    let now = e.now();
    let row = |days: f64, ret: f64, started_ms: Option<i64>| crate::lab::ForwardEvidence {
        state: Some("running".into()),
        started_ms,
        ..fwd(days, ret, -4.0, 5.0)
    };
    let mut file = forward_file(now, &[]);
    file.autopilots.insert(id.clone(), row(12.0, -6.0, Some(started)));
    e.apply_lab_forward(file.clone());
    let f = status(&e, &id).forward.unwrap();
    assert_eq!((f.status.as_str(), f.days, f.band_low_pct), ("below", 12.0, Some(-4.0)));

    file.autopilots.insert(id.clone(), row(12.0, 0.5, Some(started)));
    e.apply_lab_forward(file.clone());
    assert_eq!(status(&e, &id).forward.unwrap().status, "ok");

    let mut no_band = row(12.0, 0.5, Some(started));
    no_band.band_low_pct = None;
    no_band.band_high_pct = None;
    file.autopilots.insert(id.clone(), no_band);
    e.apply_lab_forward(file.clone());
    assert_eq!(status(&e, &id).forward.unwrap().status, "none");

    // A row from an earlier run under the same id is not this one's.
    file.autopilots.insert(id.clone(), row(12.0, -6.0, Some(started - 86_400_000)));
    e.apply_lab_forward(file);
    assert_eq!(status(&e, &id).forward.unwrap().status, "early", "falls back to its own age");

    // The camelCase the UI reads; and a stopped one carries none.
    let v = serde_json::to_value(e.state()).unwrap();
    assert_eq!(v["autopilots"][0]["forward"]["status"], "early");
    assert!(v["autopilots"][0]["forward"].get("bandLowPct").is_some());
    e.autopilot_stop(&id, None).unwrap();
    assert!(status(&e, &id).forward.is_none());
}

// ── correctness gaps found in review ───────────────────────────────────────

#[test]
fn money_and_percentages_never_print_a_negative_zero() {
    assert_eq!(usd(-0.004), "$0.00");
    assert_eq!(usd(-0.006), "-$0.01");
    assert_eq!(usd(-1_234.5), "-$1,234.50");
    assert_eq!(pct(-0.001), "0");
    assert_eq!(pct(-0.004), "0");
    assert_eq!(pct(-0.006), "-0.01");
    assert_eq!(pct(10.0), "10");
    assert_eq!(pct(-2.5), "-2.5");
}

#[test]
fn a_stale_price_never_raises_the_peak_or_takes_profit() {
    let mut e = engine();
    let stop = StopRules { take_profit_pct: Some(10.0), trailing_pct: Some(5.0), ..Default::default() };
    let id = start(&mut e, config("st", 1_000.0, &[("ema-cross-1", 1.0)], stop));
    enter(&mut e, "ema-cross-1", BTC, 500.0);
    equity_to(&mut e, &id, BTC, 1_120.0);
    make_stale(&mut e, BTC);
    step(&mut e);
    let s = status(&e, &id);
    assert_eq!(s.state, AutopilotState::Running, "a stale price is not a profit to finish on");
    let peak = e.autopilots.iter().find(|a| a.config.id == id).unwrap().peak_equity;
    assert!((peak - 1_000.0).abs() < 1e-9, "nor a peak for the trailing floor: {peak}");

    // The same price, confirmed by the feed: now it counts.
    let p = e.price_of(BTC);
    set_price(&mut e, BTC, p);
    step(&mut e);
    let s = status(&e, &id);
    assert_eq!(s.state, AutopilotState::Finished);
    assert!(s.stop_reason.unwrap().starts_with("take profit of 10 % reached"));
}

#[test]
fn a_loss_rule_still_fires_on_a_stale_price() {
    // Safety first: the floor does not wait for a feed.
    let mut e = engine();
    let id = start(&mut e, config("sl", 1_000.0, &[("ema-cross-1", 1.0)], StopRules { max_loss_pct: Some(10.0), ..Default::default() }));
    enter(&mut e, "ema-cross-1", BTC, 500.0);
    equity_to(&mut e, &id, BTC, 890.0);
    make_stale(&mut e, BTC);
    step(&mut e);
    assert_eq!(status(&e, &id).state, AutopilotState::Stopped);
}

#[test]
fn a_close_at_exactly_the_entry_price_is_a_closed_trade() {
    let mut e = engine();
    let id = start(&mut e, config("be", 1_000.0, &[("ema-cross-1", 1.0)], StopRules::default()));
    enter(&mut e, "ema-cross-1", BTC, 500.0);
    let i = idx(&e, "ema-cross-1");
    let m = market(&e, BTC);
    let key = pos_key(&id, BTC);
    let (qty, avg) = (e.positions[&key].qty, e.positions[&key].avg_price);
    // A fill at exactly the average entry price, as a venue can report it.
    e.settle_fill_on(&id, i, &m, Side::Sell, qty, avg, 0.05, avg, false, false, true);
    assert!(!holds(&e, BTC));
    let s = status(&e, &id);
    assert_eq!((s.open_positions, s.trades), (0, 1), "nothing realised, still one round trip");
    assert_eq!(s.by_sleeve[0].trades, 1);
}

#[test]
fn paper_autopilots_cannot_give_out_the_same_money_twice() {
    let mut e = engine();
    // Pairs holds BTC and ETH, EMA Cross the rest: no market conflict between them.
    start(&mut e, config("p1", 60_000.0, &[("pairs-1", 1.0)], StopRules::default()));
    let err = e
        .autopilot_start(config("p2", 50_000.0, &[("ema-cross-1", 1.0)], StopRules::default()), false, VenueCash::NotRead)
        .unwrap_err();
    assert!(
        err.contains("The paper account holds $100,000.00, of which $60,000.00 is already given to other paper autopilots, so $40,000.00 is left"),
        "{err}"
    );
    start(&mut e, config("p2", 40_000.0, &[("ema-cross-1", 1.0)], StopRules::default()));
}

#[test]
fn the_live_cash_check_counts_other_autopilots_whatever_the_venue_spelling() {
    let mut e = engine();
    e.set_live(armed_crypto());
    make_live_ready(&mut e, "pairs-1");
    make_live_ready(&mut e, "ema-cross-1");
    let mut c = live_config("live", 1_000.0, &[("pairs-1", 1.0)]);
    c.venue = " Kraken".into();
    let id = e.autopilot_start(c, true, VenueCash::Read(2_000.0)).unwrap();
    assert_eq!(status(&e, &id).config.venue, "kraken", "saved under the venue's id");
    let err = e.autopilot_start(live_config("live2", 1_500.0, &[("ema-cross-1", 1.0)]), true, VenueCash::Read(2_000.0)).unwrap_err();
    assert!(err.contains("of which $1,000.00 is already committed to other live autopilots"), "{err}");

    // A record saved before the venue was normalised still counts.
    e.autopilots.iter_mut().find(|a| a.config.id == id).unwrap().config.venue = "KRAKEN".into();
    let err = e.autopilot_start(live_config("live2", 1_500.0, &[("ema-cross-1", 1.0)]), true, VenueCash::Read(2_000.0)).unwrap_err();
    assert!(err.contains("already committed"), "{err}");
}

#[test]
fn a_late_fill_after_a_stop_without_flattening_is_handed_out_too() {
    let (mut e, id) = demo_engine("lateopen", 1_000.0);
    let i = idx(&e, "ema-cross-1");
    let m = market(&e, BTC);
    e.place_from_intent(&id, i, &m, &buy_intent(BTC));
    let o = e.drain_live_orders().remove(0);
    e.apply_live_ack(&o.order_id, "venue-1");
    e.autopilot_stop(&id, Some(false)).unwrap();

    e.apply_live_update(
        &o.order_id,
        LiveUpdate { status: BrokerOrderStatus::Filled, filled_qty: o.qty, avg_price: Some(o.ref_price), fee: 0.1, fee_base: 0.0, fee_unpriced: Vec::new(), raw_status: "filled".into() },
    );
    assert!(holds(&e, BTC), "the position is left open, as asked");
    let s = status(&e, &id);
    assert_eq!(s.open_positions, 0, "but not kept by the stopped autopilot");
    assert!((s.fees - 0.1).abs() < 1e-9, "its fee is still the autopilot's: {}", s.fees);
    assert!(journal_has(&e, "filled after it stopped without closing its positions"));
    step(&mut e);
    assert!(e.drain_live_orders().is_empty(), "and nothing closes it behind the owner's back");
    // It is not "still closing its positions", but its book still holds the
    // coin it left open: a new autopilot under the same id would mix it in.
    let mut c = config("lateopen", 1_000.0, &[("multi-tf-1", 1.0)], StopRules::default());
    c.mode = AutopilotMode::Demo;
    let err = e.autopilot_start(c.clone(), false, VenueCash::NotRead).unwrap_err();
    assert!(err.contains("still holds positions an earlier autopilot left open"), "{err}");
    // Once the owner closes it, the id is free again.
    e.flatten(&pos_key(&id, BTC));
    let close = e.drain_live_orders().remove(0);
    assert!(close.demo && close.side == Side::Sell, "closed at the demo venue");
    e.apply_live_ack(&close.order_id, "venue-2");
    e.apply_live_update(
        &close.order_id,
        LiveUpdate { status: BrokerOrderStatus::Filled, filled_qty: close.qty, avg_price: Some(o.ref_price), fee: 0.1, fee_base: 0.0, fee_unpriced: Vec::new(), raw_status: "filled".into() },
    );
    assert!(!holds(&e, BTC));
    assert!((status(&e, &id).fees - 0.1).abs() < 1e-9, "the close of a position it handed out is not its");
    e.autopilot_start(c, false, VenueCash::NotRead).unwrap();
}

#[test]
fn a_demo_autopilot_on_the_alpaca_paper_route_trades_the_coins_alpaca_lists_and_skips_the_rest() {
    let mut e = idle_engine();
    let now = e.now();
    // PYTHIA_DEMO_EXCHANGE=alpaca with only the Alpaca paper keys.
    e.set_demo_venues([Venue::Crypto, Venue::Alpaca].into_iter().collect(), Some(CostVenue::Alpaca), true);
    e.fresh_books_for_test();
    e.set_crypto_demo_listed(Some(["BTC/USD", "ETH/USD", "SOL/USD"].into_iter().map(String::from).collect()));
    e.apply_lab_signal(book("tsmom_regime", now, &[("BTC", 0.4), ("ETH", 0.2), ("SUI", 0.1)], regime_evidence(), false));

    // "alpaca" alone is US shares: auto finds nothing there and says where crypto is.
    let mut c = config("alp", 10_000.0, &[], StopRules::default());
    c.mode = AutopilotMode::Demo;
    c.venue = "alpaca".into();
    let err = e.autopilot_start(c.clone(), false, VenueCash::NotRead).unwrap_err();
    assert!(err.contains("pick Crypto"), "{err}");

    // What the page sends for crypto demo: the demo venue and the asset class.
    c.asset_class = Some(Venue::Crypto);
    let id = start(&mut e, c);
    let s = status(&e, &id);
    assert_eq!((s.config.venue.as_str(), s.config.asset_class), ("alpaca", Some(Venue::Crypto)));
    assert_eq!(s.by_sleeve.len(), 1);
    assert_eq!(s.by_sleeve[0].strategy_id, "lab:tsmom_regime");
    let mut markets = s.by_sleeve[0].markets.clone();
    markets.sort();
    assert_eq!(markets, vec![BTC.to_string(), ETH.to_string(), "crypto:SOL/USD".to_string()], "only the listed coins");
    assert!(journal_has(&e, "Crypto demo here is the Alpaca paper account; Alpaca does not list"));

    e.run_lab_books();
    let out = e.drain_live_orders();
    assert_eq!(out.len(), 2, "BTC and ETH go out, SUI is skipped: {out:?}");
    assert!(out.iter().all(|o| o.demo && !o.paper && o.venue == Venue::Crypto && o.side == Side::Buy));
    let sent = |m: &str| out.iter().find(|o| o.market_id == m).map(|o| o.qty * o.ref_price).unwrap();
    // Not renormalised: BTC keeps its 40 %, the 10 % meant for SUI stays in cash.
    assert!((sent(BTC) - 4_000.0).abs() < 60.0, "{}", sent(BTC));
    assert!((sent(ETH) - 2_000.0).abs() < 30.0, "{}", sent(ETH));
    let notes: Vec<&JournalEntry> = e.journal.iter().filter(|j| j.message.contains("not listed on Alpaca, the demo route")).collect();
    assert_eq!(notes.len(), 1, "said once for the rebalance");
    assert!(notes[0].message.contains("skipped SUI/USD"));
    assert!(!notes[0].message.contains("another strategy holds"), "{}", notes[0].message);

    // The paper and live routes do not use Alpaca for crypto.
    let mut p = config("alp-paper", 1_000.0, &[], StopRules::default());
    p.venue = "alpaca".into();
    p.asset_class = Some(Venue::Crypto);
    let err = e.autopilot_start(p, false, VenueCash::NotRead).unwrap_err();
    assert!(err.contains("only the demo route"), "{err}");
}

// ── several lab books in one autopilot: netting, attribution, re-pick ─────

const SOL: &str = "crypto:SOL/USD";

fn weights(w: &[(&str, f64)]) -> std::collections::BTreeMap<String, f64> {
    w.iter().map(|(k, v)| (k.to_string(), *v)).collect()
}

#[test]
fn netting_scales_each_book_by_its_sleeve_weight_and_splits_every_coin_by_share() {
    let a = weights(&[("BTC", 0.5), ("ETH", 0.5)]);
    let b = weights(&[("BTC", 0.25), ("SOL", 0.75), ("DOGE", -0.4)]);
    let c = weights(&[("BTC", 1.0)]);
    let (combined, shares) =
        net_lab_targets(&[("a".into(), 0.6, &a), ("b".into(), 0.4, &b), ("dropped".into(), 0.0, &c)]);
    let close = |x: f64, y: f64| (x - y).abs() < 1e-12;
    assert!(close(combined["BTC"], 0.6 * 0.5 + 0.4 * 0.25), "{combined:?}");
    assert!(close(combined["ETH"], 0.3));
    assert!(close(combined["SOL"], 0.3));
    assert!(!combined.contains_key("DOGE"), "long only: a negative weight is cash");
    assert!(close(combined.values().sum::<f64>(), 1.0), "two fully invested books net to a fully invested target");
    assert!(close(shares["BTC"]["a"], 0.75) && close(shares["BTC"]["b"], 0.25));
    assert!(close(shares["ETH"]["a"], 1.0) && !shares["ETH"].contains_key("b"));
    assert!(shares.values().all(|s| !s.contains_key("dropped")), "a book at weight zero adds nothing and owns nothing");
    for s in shares.values() {
        assert!(close(s.values().sum::<f64>(), 1.0));
    }
    // Nothing wanted: an empty target, all cash.
    let empty = weights(&[]);
    let (combined, shares) = net_lab_targets(&[("a".into(), 1.0, &empty)]);
    assert!(combined.is_empty() && shares.is_empty());
}

#[test]
fn lab_books_share_their_markets_with_each_other_and_with_no_one_else() {
    let u = |v: &[&str]| v.iter().map(|s| s.to_string()).collect::<Vec<_>>();
    let wants = vec![
        Want { weight: 0.5, whole: true, net: true, universe: u(&["BTC", "ETH", "SOL"]) },
        Want { weight: 0.3, whole: true, net: true, universe: u(&["BTC", "ETH", "SOL"]) },
        Want { weight: 0.1, whole: true, net: false, universe: u(&["ETH", "XRP"]) },
        Want { weight: 0.1, whole: false, net: false, universe: u(&["SOL", "ADA"]) },
    ];
    let out = assign_markets(&wants, &HashSet::new());
    assert_eq!(out[0], u(&["BTC", "ETH", "SOL"]));
    assert_eq!(out[1], u(&["BTC", "ETH", "SOL"]), "a second lab book nets on the same coins");
    assert!(out[2].is_empty(), "a pair set never shares a coin with the lab books");
    assert_eq!(out[3], u(&["ADA"]), "a built-in gets only what the lab books do not hold");
    // Another autopilot's market keeps both lab books out, all or nothing.
    let taken: HashSet<String> = ["SOL".to_string()].into_iter().collect();
    let out = assign_markets(&wants[..2], &taken);
    assert!(out[0].is_empty() && out[1].is_empty());
}

/// Regime wants BTC and ETH, breakout BTC and SOL, half each.
fn netted_engine(capital: f64) -> (Engine, String) {
    let mut e = idle_engine();
    let now = e.now();
    e.apply_lab_signal(book("tsmom_regime", now, &[("BTC", 0.5), ("ETH", 0.5)], regime_evidence(), false));
    e.apply_lab_signal(book("breakout_top10", now, &[("BTC", 0.5), ("SOL", 0.5)], breakout_evidence(), false));
    let id = start(&mut e, config("net", capital, &[("lab:tsmom_regime", 0.6), ("lab:breakout_top10", 0.4)], StopRules::default()));
    (e, id)
}

fn sleeve<'a>(s: &'a AutopilotStatus, sid: &str) -> &'a SleeveStatus {
    s.by_sleeve.iter().find(|b| b.strategy_id == sid).expect("the sleeve exists")
}

fn assert_adds_up(s: &AutopilotStatus) {
    let pnl: f64 = s.by_sleeve.iter().map(|b| b.pnl).sum();
    assert!((pnl - s.pnl).abs() < 1e-6, "the sleeves' P&L adds up to the autopilot's: {pnl} vs {}", s.pnl);
    let trades: u32 = s.by_sleeve.iter().map(|b| b.trades).sum();
    assert!(trades >= s.trades, "every closed trade is counted for each sleeve that held it");
}

#[test]
fn two_lab_books_net_into_one_position_per_coin_and_split_exposure_and_pnl_by_share() {
    let (mut e, id) = netted_engine(10_000.0);
    let s = status(&e, &id);
    assert_eq!(s.by_sleeve.len(), 2, "two lab books run in one autopilot");
    assert!(s.by_sleeve.iter().all(|b| b.markets.len() == e.markets.iter().filter(|m| m.venue == Venue::Crypto).count()));
    assert!(sleeve(&s, "lab:tsmom_regime").why.contains("netted per coin with the other 1 lab book(s)"));
    e.run_lab_books();

    // 0.6 x 0.5 + 0.4 x 0.5 of BTC, 0.6 x 0.5 of ETH, 0.4 x 0.5 of SOL.
    assert!((notional(&e, BTC) - 5_000.0).abs() < 60.0, "{}", notional(&e, BTC));
    assert!((notional(&e, ETH) - 3_000.0).abs() < 40.0, "{}", notional(&e, ETH));
    assert!((notional(&e, SOL) - 2_000.0).abs() < 30.0, "{}", notional(&e, SOL));
    assert_eq!(e.positions.len(), 3, "one position per coin");
    assert!(journal_has(&e, "Rebalanced toward the netted weights of 2 lab books (Lab · tsmom_regime 60 %, Lab · breakout_top10 40 %)"));
    let s = status(&e, &id);
    assert_eq!(s.open_positions, 3);
    let (r, b) = (sleeve(&s, "lab:tsmom_regime"), sleeve(&s, "lab:breakout_top10"));
    assert!((r.exposure - 6_000.0).abs() < 80.0, "regime: 60 % of BTC and all of ETH: {}", r.exposure);
    assert!((b.exposure - 4_000.0).abs() < 60.0, "breakout: 40 % of BTC and all of SOL: {}", b.exposure);
    assert!((r.exposure_pct + b.exposure_pct - 100.0).abs() < 2.0);
    assert!(s.waiting.is_none(), "it holds coins, it is not waiting");
    assert_adds_up(&s);
    let fees: f64 = e.autopilots[0].sleeves.iter().map(|x| x.fees).sum();
    assert!((fees - s.fees).abs() < 1e-9 && s.fees > 0.0, "fees split, none lost");

    // BTC up 10 %: its gain splits 60 / 40.
    let before = (r.pnl, b.pnl);
    let gain = notional(&e, BTC) * 0.1;
    let p = e.price_of(BTC);
    set_price(&mut e, BTC, p * 1.1);
    let s = status(&e, &id);
    assert!((sleeve(&s, "lab:tsmom_regime").pnl - before.0 - gain * 0.6).abs() < 1e-6);
    assert!((sleeve(&s, "lab:breakout_top10").pnl - before.1 - gain * 0.4).abs() < 1e-6);
    assert_adds_up(&s);

    // The next day regime wants nothing. Only the difference is traded: ETH
    // is sold (it was regime's alone), BTC comes down to breakout's 0.2.
    let regime_before = sleeve(&s, "lab:tsmom_regime").pnl;
    let now = e.now();
    e.apply_lab_signal(book("tsmom_regime", now + 1, &[], regime_evidence(), false));
    e.run_lab_books();
    assert!(!holds(&e, ETH), "ETH sold");
    let eq = status(&e, &id).equity;
    assert!((notional(&e, BTC) - 0.4 * 0.5 * eq).abs() < 60.0, "BTC down to breakout's share: {}", notional(&e, BTC));
    assert!(holds(&e, SOL), "SOL untouched");
    let s = status(&e, &id);
    let r = sleeve(&s, "lab:tsmom_regime");
    assert!(r.exposure < 1e-6, "regime holds nothing now: {}", r.exposure);
    assert!((r.pnl - regime_before).abs() < 25.0, "regime keeps the BTC gain it earned (less the fees of selling): {} vs {regime_before}", r.pnl);
    assert!(r.pnl > before.0 + gain * 0.6 - 25.0);
    assert_adds_up(&s);
}

#[test]
fn stopping_flattens_every_netted_position_and_idles_every_book() {
    let (mut e, id) = netted_engine(10_000.0);
    e.run_lab_books();
    assert_eq!(e.positions.len(), 3);
    e.autopilot_stop(&id, None).unwrap();
    let s = status(&e, &id);
    assert_eq!(s.state, AutopilotState::Stopped);
    assert!(e.positions.is_empty(), "every netted coin closed");
    assert_eq!(s.open_positions, 0);
    assert_eq!(state_of(&e, "lab:tsmom_regime"), StrategyState::Paused);
    assert_eq!(state_of(&e, "lab:breakout_top10"), StrategyState::Paused);
    assert!(journal_has(&e, "Closed its 3 position(s)"));
    assert_adds_up(&s);
    let r = sleeve(&s, "lab:tsmom_regime");
    let b = sleeve(&s, "lab:breakout_top10");
    assert_eq!((r.trades, b.trades), (2, 2), "BTC and ETH for regime, BTC and SOL for breakout");
    assert_eq!(s.trades, 3);
    // Both books are free again, for another autopilot.
    e.run_lab_books();
    assert!(e.positions.is_empty(), "idle again: nothing trades");
    start(&mut e, config("again", 5_000.0, &[("lab:breakout_top10", 1.0)], StopRules::default()));

    // Without flattening, the positions are handed out at their price.
    let (mut e, id) = netted_engine(10_000.0);
    e.run_lab_books();
    e.autopilot_stop(&id, Some(false)).unwrap();
    assert_eq!(e.positions.len(), 3, "left open");
    assert!(journal_has(&e, "3 of them belong to a lab book"));
}

#[test]
fn netted_books_come_back_after_a_restart_with_their_shares() {
    let (mut e, id) = netted_engine(10_000.0);
    e.run_lab_books();
    let p = e.price_of(BTC);
    set_price(&mut e, BTC, p * 1.05);
    let before = status(&e, &id);
    let saved = serde_json::to_string(&e.to_persisted()).unwrap();
    let mut r = Engine::new();
    r.apply_persisted(serde_json::from_str(&saved).unwrap());
    mark_real(&mut r);
    let after = status(&r, &id);
    assert_eq!(after.state, AutopilotState::Running);
    assert_eq!(after.config.repick_every_hours, None, "explicit sleeves are never re-picked");
    assert!((after.equity - before.equity).abs() < 1e-6);
    for b in &before.by_sleeve {
        let a = sleeve(&after, &b.strategy_id);
        assert!((a.pnl - b.pnl).abs() < 1e-6, "{}: the share of every coin survives", b.strategy_id);
        assert!((a.exposure - b.exposure).abs() < 1e-6);
        assert_eq!(a.weight, b.weight);
    }
    assert_eq!(r.autopilots[0].shares, e.autopilots[0].shares);
    assert_eq!(r.autopilots[0].lab_target, e.autopilots[0].lab_target);
    // Same signals, already traded: the restart trades nothing.
    let orders = r.orders.len();
    r.run_lab_books();
    assert_eq!(r.orders.len(), orders);
    r.autopilot_stop(&id, None).unwrap();
    assert!(r.positions.is_empty());
}

#[test]
fn auto_picks_up_to_n_lab_books_and_a_book_without_positive_evidence_is_left_out() {
    let mut e = idle_engine();
    let now = e.now();
    let w = &[("BTC", 0.3)];
    e.apply_lab_signal(book("tsmom_top20", now, w, top20_evidence(), true));
    e.apply_lab_signal(book("breakout_top10", now, w, breakout_evidence(), true));
    e.apply_lab_signal(book("tsmom_regime", now, w, regime_evidence(), false));
    let mut c = config("two", 10_000.0, &[], StopRules::default());
    c.max_sleeves = Some(2);
    let id = start(&mut e, c);
    let ids: Vec<String> = status(&e, &id).by_sleeve.into_iter().map(|b| b.strategy_id).collect();
    assert_eq!(ids, ["lab:tsmom_regime", "lab:breakout_top10"], "at most two, best evidence first");

    let mut e = idle_engine();
    let mut neg = top20_evidence();
    neg.oos_sharpe = Some(-0.3);
    e.apply_lab_signal(book("tsmom_top20", now, w, neg, true));
    e.apply_lab_signal(book("tsmom_regime", now, w, regime_evidence(), false));
    let id = start(&mut e, config("pos", 10_000.0, &[], StopRules::default()));
    let ids: Vec<String> = status(&e, &id).by_sleeve.into_iter().map(|b| b.strategy_id).collect();
    assert_eq!(ids, ["lab:tsmom_regime"], "a negative out-of-sample Sharpe is no evidence to weight");

    // Bad settings are refused in plain words.
    let mut e = idle_engine();
    let mut c = config("x", 1_000.0, &[], StopRules::default());
    c.max_sleeves = Some(0);
    assert!(e.autopilot_start(c, false, VenueCash::NotRead).unwrap_err().contains("Auto can pick 1 to 10"));
    let mut c = config("x", 1_000.0, &[("ema-cross-1", 1.0)], StopRules::default());
    c.repick_every_hours = Some(24.0);
    assert!(e.autopilot_start(c, false, VenueCash::NotRead).unwrap_err().contains("only applies when Pythia chooses"));
    let mut c = config("x", 1_000.0, &[], StopRules::default());
    c.repick_every_hours = Some(0.5);
    assert!(e.autopilot_start(c, false, VenueCash::NotRead).unwrap_err().contains("at most once an hour"));
    let mut c = config("x", 1_000.0, &[], StopRules::default());
    c.repick_every_hours = Some(0.0);
    let id = start(&mut e, c);
    assert_eq!(status(&e, &id).config.repick_every_hours, None, "0 turns it off");
    assert_eq!(status(&e, &id).next_repick_ms, None);
}

#[test]
fn a_repick_adds_and_drops_lab_books_gradually_and_says_why() {
    let mut e = idle_engine();
    let now = e.now();
    e.apply_lab_signal(book("tsmom_regime", now, &[("BTC", 0.5), ("ETH", 0.5)], regime_evidence(), false));
    let id = start(&mut e, config("re", 10_000.0, &[], StopRules::default()));
    let s = status(&e, &id);
    assert_eq!(s.config.repick_every_hours, Some(REPICK_DEFAULT_HOURS), "auto pick: every 24 h by default");
    assert_eq!(s.next_repick_ms, Some(s.started_ms + 24 * 3_600_000));
    assert_eq!(s.by_sleeve.len(), 1);
    e.run_lab_books();
    assert!((notional(&e, ETH) - 5_000.0).abs() < 60.0);

    // Not due yet: nothing happens.
    e.autopilot_step(now + 23 * 3_600_000);
    assert_eq!(status(&e, &id).by_sleeve.len(), 1);

    // A day later a second book has a signal: the re-pick adds it, by score.
    e.apply_lab_signal(book("breakout_top10", now, &[("BTC", 0.5), ("SOL", 0.5)], breakout_evidence(), false));
    let orders = e.orders.len();
    e.autopilot_step(now + 25 * 3_600_000);
    assert_eq!(e.orders.len(), orders, "a re-pick itself never trades");
    let s = status(&e, &id);
    assert_eq!(s.by_sleeve.len(), 2);
    let total = e.evidence("lab:tsmom_regime").score().unwrap() + e.evidence("lab:breakout_top10").score().unwrap();
    let wb = e.evidence("lab:breakout_top10").score().unwrap() / total;
    assert!((sleeve(&s, "lab:breakout_top10").weight - wb).abs() < 1e-9);
    assert!(sleeve(&s, "lab:breakout_top10").why.contains("added at a re-pick"));
    assert_eq!(state_of(&e, "lab:breakout_top10"), StrategyState::Paper, "claimed by the autopilot");
    let msg = s.last_action.clone().unwrap();
    assert!(msg.contains("re-ran its pick with fresh evidence and changed its lab books") && msg.contains("(new)"), "{msg}");
    assert!(msg.contains("nothing is sold off at once") && msg.contains("rebalance of the next lab signal"), "{msg}");
    assert_eq!(s.next_repick_ms, Some(now + 49 * 3_600_000));
    // No rebalance of its own on the signals already traded: the new weights,
    // and the new book, wait for the next signal.
    let btc = notional(&e, BTC);
    e.run_lab_books();
    assert_eq!(e.orders.len(), orders, "the re-pick's weights wait for the next lab signal");
    assert!(!holds(&e, SOL));
    // The next signals: one rebalance nets the new weights in: ETH comes
    // down, BTC stays, SOL arrives.
    e.apply_lab_signal(book("tsmom_regime", now + 2, &[("BTC", 0.5), ("ETH", 0.5)], regime_evidence(), false));
    e.apply_lab_signal(book("breakout_top10", now + 2, &[("BTC", 0.5), ("SOL", 0.5)], breakout_evidence(), false));
    e.run_lab_books();
    let wr = 1.0 - wb;
    assert!((notional(&e, ETH) - 10_000.0 * wr * 0.5).abs() < 80.0, "{}", notional(&e, ETH));
    assert!((notional(&e, BTC) - btc).abs() < 80.0, "BTC was wanted by both: barely traded");
    assert!((notional(&e, SOL) - 10_000.0 * wb * 0.5).abs() < 80.0);
    assert_adds_up(&status(&e, &id));

    // Regime loses its evidence: it is dropped to zero, kept for its record,
    // and its coins are sold down only where breakout does not want them.
    let mut bad = regime_evidence();
    bad.oos_sharpe = Some(-0.1);
    e.apply_lab_signal(book("tsmom_regime", now + 3, &[("BTC", 0.5), ("ETH", 0.5)], bad, false));
    e.autopilot_step(now + 50 * 3_600_000);
    let s = status(&e, &id);
    let r = sleeve(&s, "lab:tsmom_regime");
    assert!(r.dropped && r.weight == 0.0, "{r:?}");
    assert!((sleeve(&s, "lab:breakout_top10").weight - 1.0).abs() < 1e-9);
    assert!(s.last_action.unwrap().contains("Lab · tsmom_regime dropped"));
    e.apply_lab_signal(book("breakout_top10", now + 3, &[("BTC", 0.5), ("SOL", 0.5)], breakout_evidence(), false));
    e.run_lab_books();
    assert!(!holds(&e, ETH), "ETH was regime's alone");
    let eq = status(&e, &id).equity;
    assert!((notional(&e, BTC) - eq * 0.5).abs() < 80.0, "BTC kept at breakout's half: {}", notional(&e, BTC));
    let s = status(&e, &id);
    assert!(sleeve(&s, "lab:tsmom_regime").exposure < 1e-6);
    assert_adds_up(&s);

    // The same evidence again: nothing changes, and that is said.
    e.autopilot_step(now + 75 * 3_600_000);
    assert!(journal_has(&e, "the same strategies, no weight moving by more than 2 points, so nothing changes"));

    // The dropped book is still listed in this autopilot, and another one may
    // run it too, in its own book; stopping this one leaves the other alone.
    let other = start(&mut e, config("other", 1_000.0, &[("lab:tsmom_regime", 1.0)], StopRules::default()));
    e.autopilot_stop(&id, None).unwrap();
    assert!(e.positions.values().all(|p| p.book != id), "everything of its own closed");
    assert_eq!(state_of(&e, "lab:tsmom_regime"), StrategyState::Paper, "still running for the other autopilot");
    assert_eq!(status(&e, &other).state, AutopilotState::Running);
    assert!(journal_has(&e, "Still running for the other autopilots, which are untouched"));
    e.autopilot_stop(&other, None).unwrap();
    assert!(e.positions.is_empty());
    assert_eq!(state_of(&e, "lab:tsmom_regime"), StrategyState::Paused);
}

#[test]
fn with_nothing_to_hold_it_says_it_waits_in_cash_and_forces_nothing() {
    let mut e = idle_engine();
    let now = e.now();
    e.apply_lab_signal(book("breakout_top10", now, &[], breakout_evidence(), false));
    let id = start(&mut e, config("cash", 10_000.0, &[("lab:breakout_top10", 1.0)], StopRules::default()));
    e.run_lab_books();
    assert!(e.positions.is_empty());
    assert!(e.orders.iter().all(|o| o.strategy_id != "lab:breakout_top10"), "no trade forced");
    let s = status(&e, &id);
    let w = s.waiting.expect("it says it waits");
    assert!(w.starts_with("In cash, waiting for signals: its lab book wants no coins today."), "{w}");
    assert!(w.contains("never forces a trade"), "{w}");

    // A coin this route cannot trade is named as the reason.
    e.apply_lab_signal(book("breakout_top10", now + 1, &[("NOPE", 0.4)], breakout_evidence(), false));
    e.run_lab_books();
    let w = status(&e, &id).waiting.unwrap();
    assert!(w.contains("the lab wants only NOPE/USD, which cannot be traded here now"), "{w}");

    // Once it buys, it is no longer waiting; paused, it does not say so either.
    e.apply_lab_signal(book("breakout_top10", now + 2, &[("BTC", 0.4)], breakout_evidence(), false));
    e.run_lab_books();
    assert!(status(&e, &id).waiting.is_none());
    e.autopilot_pause(&id).unwrap();
    assert!(status(&e, &id).waiting.is_none());
}

#[test]
fn a_demo_autopilot_on_alpaca_shares_runs_an_etf_lab_book_on_the_paper_account() {
    let mut e = idle_engine();
    // The ETF markets come from the configured equity list; pinned here so
    // the test does not depend on the environment.
    let (markets, sim) = super::seed_markets_with(&["SPY".to_string(), "GLD".to_string()]);
    e.markets = markets;
    e.sim = sim;
    mark_real(&mut e);
    e.apply_alpaca(&[
        RealEquity { id: "alpaca:SPY".into(), symbol: "SPY".into(), price: 500.0, change24h: 0.0 },
        RealEquity { id: "alpaca:GLD".into(), symbol: "GLD".into(), price: 250.0, change24h: 0.0 },
    ]);
    e.set_demo_venues([Venue::Alpaca].into_iter().collect(), None, true);
    let now = e.now();
    let mut sig = book("etf_trend", now, &[("SPY", 0.5), ("GLD", 0.25)], regime_evidence(), true);
    sig.asset_class = Some(crate::lab::US_EQUITY.into());
    e.apply_lab_signal(sig);
    assert_eq!(state_of(&e, "lab:etf_trend"), StrategyState::Paused, "idle until an autopilot claims it");

    // "alpaca" without an asset class: US shares on the paper account.
    let mut c = config("etf", 10_000.0, &[("lab:etf_trend", 1.0)], StopRules::default());
    c.mode = AutopilotMode::Demo;
    c.venue = "alpaca".into();
    let id = start(&mut e, c);
    let s = status(&e, &id);
    assert_eq!(s.config.asset_class, Some(Venue::Alpaca));
    let mut markets = s.by_sleeve[0].markets.clone();
    markets.sort();
    assert!(markets.contains(&"alpaca:SPY".to_string()) && markets.contains(&"alpaca:GLD".to_string()));
    assert!(markets.iter().all(|m| m.starts_with("alpaca:") && !m.contains('/')), "{markets:?}");

    // Closed: nothing goes out. Open: both buys, in dollars of the autopilot's capital.
    e.run_lab_books();
    assert!(e.drain_live_orders().is_empty());
    e.set_broker_status(BrokerStatus {
        market_open: true,
        extended_open: true,
        session_end: None,
        next_open: None,
        day_trade_limit_reached: false,
        restricted: None,
        equity: 100_000.0,
        buying_power: 200_000.0,
        checked_at: e.now(),
    });
    e.run_lab_books();
    let out = e.drain_live_orders();
    assert_eq!(out.len(), 2, "{out:?}");
    assert!(out.iter().all(|o| o.demo && o.venue == Venue::Alpaca && o.side == Side::Buy));
    let sent = |m: &str| out.iter().find(|o| o.market_id == m).map(|o| o.qty * o.ref_price).unwrap();
    assert!((sent("alpaca:SPY") - 5_000.0).abs() < 1.0, "{}", sent("alpaca:SPY"));
    assert!((sent("alpaca:GLD") - 2_500.0).abs() < 1.0, "{}", sent("alpaca:GLD"));
}

// ── changing a running autopilot in place ─────────────────────────────────

fn sleeves_upd(s: &[(&str, f64)]) -> AutopilotUpdate {
    AutopilotUpdate {
        sleeves: Some(s.iter().map(|(id, w)| SleeveConfig { strategy_id: id.to_string(), weight: *w }).collect()),
        ..Default::default()
    }
}

/// Orders placed since `before` (the ids then): the newest come first.
fn orders_since<'a>(e: &'a Engine, before: &HashSet<String>) -> Vec<&'a Order> {
    e.orders.iter().filter(|o| !before.contains(&o.id)).collect()
}

fn order_ids(e: &Engine) -> HashSet<String> {
    e.orders.iter().map(|o| o.id.clone()).collect()
}

fn update(e: &mut Engine, id: &str, u: AutopilotUpdate) -> Result<String, String> {
    e.autopilot_update(id, u, false, VenueCash::NotRead)
}

/// top20 holds BTC and ETH; tranches wants BTC, less ETH, and SOL.
fn top20_running() -> (Engine, String) {
    let mut e = idle_engine();
    let now = e.now();
    e.apply_lab_signal(book("tsmom_top20", now, &[("BTC", 0.4), ("ETH", 0.4)], top20_evidence(), true));
    e.apply_lab_signal(book("tsmom_tranches", now, &[("BTC", 0.4), ("ETH", 0.2), ("SOL", 0.2)], top20_evidence(), true));
    let id = start(&mut e, config("sw", 10_000.0, &[("lab:tsmom_top20", 1.0)], StopRules::default()));
    e.run_lab_books();
    assert!((notional(&e, BTC) - 4_000.0).abs() < 60.0);
    assert!((notional(&e, ETH) - 4_000.0).abs() < 60.0);
    (e, id)
}

#[test]
fn an_update_switches_lab_books_in_place_and_never_sells_a_coin_both_want() {
    let (mut e, id) = top20_running();
    let before = status(&e, &id);
    let orders = e.orders.len();
    let ids = order_ids(&e);
    let msg = update(&mut e, &id, sleeves_upd(&[("lab:tsmom_tranches", 1.0)])).unwrap();
    assert!(msg.contains("Lab · tsmom_tranches 100 % (new)"), "{msg}");
    assert!(msg.contains("Lab · tsmom_top20 taken out (was 100 %)"), "{msg}");
    assert!(msg.contains("Its positions stay"), "{msg}");
    assert!(!msg.contains('\u{2014}'), "no em dashes: {msg}");
    assert!(journal_has(&e, "changed by you: strategies"));
    assert_eq!(e.orders.len(), orders, "the change itself trades nothing");
    assert_eq!(e.positions.len(), 2, "every position kept");
    assert_eq!(state_of(&e, "lab:tsmom_tranches"), StrategyState::Paper, "claimed by the autopilot");
    let s = status(&e, &id);
    assert_eq!(s.state, AutopilotState::Running);
    assert!((s.equity - before.equity).abs() < 1e-9, "a change moves no equity");
    let top = sleeve(&s, "lab:tsmom_top20");
    assert!(top.dropped && top.weight == 0.0, "{top:?}");
    assert!((sleeve(&s, "lab:tsmom_tranches").weight - 1.0).abs() < 1e-12);
    assert_eq!(s.config.sleeves.len(), 1);

    // The next rebalance trades only the difference: BTC (both want 40 %)
    // is not touched, ETH comes down to 20 %, SOL arrives.
    e.run_lab_books();
    let new = orders_since(&e, &ids);
    assert!(new.iter().all(|o| o.market_id != BTC), "BTC is wanted by both: {new:?}");
    assert!(new.iter().all(|o| !(o.market_id == ETH && o.side == Side::Buy)));
    let eth_sold: f64 = new.iter().filter(|o| o.market_id == ETH && o.side == Side::Sell).map(|o| o.filled_qty * o.avg_fill_price.unwrap_or(0.0)).sum();
    assert!((eth_sold - 2_000.0).abs() < 60.0, "ETH sold down by the difference only: {eth_sold}");
    assert!((notional(&e, SOL) - 2_000.0).abs() < 60.0, "{}", notional(&e, SOL));
    assert!((notional(&e, BTC) - 4_000.0).abs() < 1e-6);
    let s = status(&e, &id);
    assert_eq!(s.open_positions, 3);
    assert!(sleeve(&s, "lab:tsmom_top20").exposure < 1e-6, "every coin is re-attributed to the new book");
    assert!((sleeve(&s, "lab:tsmom_tranches").exposure - 8_000.0).abs() < 100.0);
    assert_adds_up(&s);

    // Restart: the new strategies, the dropped one and the shares come back,
    // and the same signal is not traded again.
    let saved = serde_json::to_string(&e.to_persisted()).unwrap();
    let mut r = Engine::new();
    r.set_lab_books_idle(true);
    r.apply_persisted(serde_json::from_str(&saved).unwrap());
    mark_real(&mut r);
    let after = status(&r, &id);
    assert_eq!(after.config.sleeves, s.config.sleeves);
    assert_eq!(after.by_sleeve.len(), 2);
    assert!(sleeve(&after, "lab:tsmom_top20").dropped);
    assert!((after.equity - s.equity).abs() < 1e-6);
    assert_eq!(after.last_action, s.last_action);
    let n = r.orders.len();
    r.run_lab_books();
    assert_eq!(r.orders.len(), n, "nothing traded twice after a restart");

    // A stopped autopilot is not changed.
    r.autopilot_stop(&id, None).unwrap();
    assert!(update(&mut r, &id, AutopilotUpdate { name: Some("x".into()), ..Default::default() }).unwrap_err().contains("is stopped"));
}

#[test]
fn a_lower_amount_brings_targets_down_at_the_next_rebalance_and_keeps_the_pnl() {
    let (mut e, id) = top20_running();
    let p = e.price_of(BTC);
    set_price(&mut e, BTC, p * 1.1);
    let before = status(&e, &id);
    let orders = e.orders.len();
    let ids = order_ids(&e);
    let msg = update(&mut e, &id, AutopilotUpdate { capital_usd: Some(5_000.0), ..Default::default() }).unwrap();
    assert!(msg.contains("amount $10,000.00 to $5,000.00") && msg.contains("nothing is sold at once"), "{msg}");
    assert_eq!(e.orders.len(), orders, "no fire sale");
    let s = status(&e, &id);
    assert!((s.start_capital - 5_000.0).abs() < 1e-9);
    assert!((s.pnl - before.pnl).abs() < 1e-6, "the P&L it earned stays its own");
    assert!((s.equity - (before.equity - 5_000.0)).abs() < 1e-6);
    assert!((s.peak_equity - (before.peak_equity - 5_000.0)).abs() < 1e-6);
    // The curve is rescaled with it: the cut is no crash and no drawdown.
    assert!(s.max_drawdown_pct < 0.5, "{}", s.max_drawdown_pct);
    let a = e.autopilots.iter().find(|a| a.config.id == id).unwrap();
    assert!(a.history.iter().all(|p| p.1 < 6_000.0), "{:?}", a.history);

    // The next day's signal is rebalanced with the smaller amount: positions
    // are sold down, not closed.
    let now = e.now();
    e.apply_lab_signal(book("tsmom_top20", now + 1, &[("BTC", 0.4), ("ETH", 0.4)], top20_evidence(), true));
    e.run_lab_books();
    let eq = status(&e, &id).equity;
    assert!((notional(&e, BTC) - 0.4 * eq).abs() < 30.0, "{} vs {}", notional(&e, BTC), 0.4 * eq);
    assert!((notional(&e, ETH) - 0.4 * eq).abs() < 30.0);
    let new = orders_since(&e, &ids);
    assert!(!new.is_empty() && new.iter().all(|o| o.side == Side::Sell), "{new:?}");

    // More than the paper account holds is refused, and so is a cut past the equity.
    let err = update(&mut e, &id, AutopilotUpdate { capital_usd: Some(10_000_000.0), ..Default::default() }).unwrap_err();
    assert!(err.contains("The paper account holds"), "{err}");
    let err = update(&mut e, &id, AutopilotUpdate { capital_usd: Some(0.0), ..Default::default() }).unwrap_err();
    assert!(err.contains("above zero"), "{err}");
    set_price(&mut e, BTC, p * 0.5);
    assert!(status(&e, &id).pnl < -10.0);
    let err = update(&mut e, &id, AutopilotUpdate { capital_usd: Some(1.0), ..Default::default() }).unwrap_err();
    assert!(err.contains("the amount can come down by less than that"), "{err}");
    let err = update(&mut e, &id, AutopilotUpdate::default()).unwrap_err();
    assert!(err.contains("Nothing to change"), "{err}");
}

#[test]
fn a_return_and_a_fee_share_are_measured_on_the_amount_it_worked_with() {
    let (mut e, id) = top20_running();
    e.advance_clock_for_test(3 * 86_400_000);
    update(&mut e, &id, AutopilotUpdate { capital_usd: Some(5_000.0), ..Default::default() }).unwrap();
    e.advance_clock_for_test(86_400_000);
    let a = e.autopilots.iter().find(|a| a.config.id == id).unwrap();
    assert_eq!(a.capital_log.len(), 2, "{:?}", a.capital_log);
    assert_eq!((a.capital_log[0].1, a.capital_log[1].1), (10_000.0, 5_000.0));
    let s = status(&e, &id);
    // Three days at $10,000, one at $5,000.
    assert!((s.avg_capital - 8_750.0).abs() < 1.0, "{}", s.avg_capital);
    assert!(s.curve_note.is_none());
}

/// ap_29742 as it was saved: started at $99,500, cut to $50,000 and then to
/// $20,000 within three minutes before its stop, with a curve from before
/// amounts rescaled it.
fn unscaled_curve() -> Vec<(i64, f64)> {
    let t0 = 1_791_847_382_430;
    let cut = 1_792_067_411_489;
    vec![
        (t0, 99_500.0),
        (t0 + 86_400_000, 98_099.0),
        (cut - 60_000, 97_612.3),
        (cut, 48_117.1),
        (cut + 60_000, 47_993.1),
        (cut + 120_000, 18_001.3),
        (cut + 180_000, 18_009.3),
    ]
}

#[test]
fn a_curve_saved_before_amounts_rescaled_it_is_repaired_from_its_steps() {
    let h = unscaled_curve();
    assert!(max_drawdown_pct(&h, 18_009.3) > 81.0, "the figure the audit found");
    let (fixed, log, note) = repair_curve(&h, 20_000.0, 20_000.0).expect("two steps no market makes");
    let dd = max_drawdown_pct(&fixed, 18_009.3);
    assert!(dd < 2.5, "the cut is no crash: {dd}");
    // Returns on either side of each step are kept.
    assert!((fixed[2].1 / fixed[0].1 - h[2].1 / h[0].1).abs() < 1e-12);
    assert!((fixed[4].1 / fixed[3].1 - 47_993.1 / 48_117.1).abs() < 1e-12);
    assert_eq!(log.len(), 3);
    assert!((log[0].1 - 99_500.0).abs() < 100.0 && (log[1].1 - 50_000.0).abs() < 100.0 && log[2].1 == 20_000.0, "{log:?}");
    assert_eq!((log[1].0, log[2].0), (h[3].0, h[5].0));
    assert!(note.starts_with("Curve repaired after the fact: 2 amount change(s)"), "{note}");
    // A curve without such a step, and in line with its peak, is left alone.
    let calm: Vec<(i64, f64)> = (0..50).map(|k| (k * 60_000, 10_000.0 * (1.0 + 0.001 * ((k % 7) as f64 - 3.0)))).collect();
    assert!(repair_curve(&calm, 10_000.0, 10_030.0).is_none());
}

#[test]
fn a_first_point_on_an_earlier_amount_is_brought_to_the_current_one() {
    // Started at $11,000, cut to $10,000 before the fix; thinning left only
    // the first point from before the cut.
    let h = vec![(0, 11_000.0), (5 * 86_400_000, 9_812.6), (5 * 86_400_000 + 60_000, 9_815.0)];
    let (fixed, log, note) = repair_curve(&h, 10_000.0, 10_026.0).expect("a point above the peak");
    assert_eq!(fixed[0].1, 10_000.0);
    assert!(max_drawdown_pct(&fixed, 9_815.0) < 2.0);
    assert_eq!(log, vec![(0, 10_000.0)]);
    assert!(note.contains("first 1 point(s) were on an earlier amount ($11000)"), "{note}");
}

#[test]
fn an_old_save_gets_its_curve_repaired_once_and_says_so() {
    let (mut e, id) = top20_running();
    let i = e.autopilots.iter().position(|a| a.config.id == id).unwrap();
    {
        let a = &mut e.autopilots[i];
        a.capital_log.clear();
        a.history = unscaled_curve();
        a.started_ms = a.history[0].0;
        a.start_capital = 20_000.0;
        a.peak_equity = 20_000.0;
        // Stopped a minute after the last cut, as ap_29742 was.
        a.stopped_ms = a.history.last().map(|p| p.0);
    }
    e.autopilot_curves_after_restore();
    let s = status(&e, &id);
    assert!(s.max_drawdown_pct < 5.0, "{}", s.max_drawdown_pct);
    assert!(s.curve_note.as_deref().is_some_and(|n| n.contains("rescaled after the fact")));
    assert!(s.avg_capital > 90_000.0, "it traded with about $99,500 nearly all the time: {}", s.avg_capital);
    assert!(e.journal.iter().any(|j| j.message.contains("Its worst drawdown reads")));
    let again = e.autopilots[i].history.clone();
    e.autopilot_curves_after_restore();
    assert_eq!(e.autopilots[i].history, again, "once");
}

#[test]
fn stop_rules_change_in_place_and_a_looser_max_loss_needs_confirmation() {
    let mut e = engine();
    let stop = StopRules { max_loss_pct: Some(10.0), ..Default::default() };
    let id = start(&mut e, config("rules", 1_000.0, &[("ema-cross-1", 1.0)], stop));
    enter(&mut e, "ema-cross-1", BTC, 500.0);
    e.autopilot_pause(&id).unwrap();

    // Tighter: no confirmation needed, works while paused, journaled.
    let tight = StopRules { max_loss_pct: Some(5.0), trailing_pct: Some(8.0), ..Default::default() };
    let msg = update(&mut e, &id, AutopilotUpdate { stop: Some(tight.clone()), ..Default::default() }).unwrap();
    assert!(msg.contains("stop rules: stops at a loss of 5 %"), "{msg}");
    let s = status(&e, &id);
    assert_eq!(s.state, AutopilotState::Paused, "a change does not resume it");
    assert_eq!(s.config.stop, tight);
    assert!((s.floor_equity.unwrap() - 950.0).abs() < 2.0, "{:?}", s.floor_equity);

    // Looser: refused without confirmation, in plain words, and nothing changes.
    let loose = StopRules { max_loss_pct: Some(20.0), ..Default::default() };
    let err = update(&mut e, &id, AutopilotUpdate { stop: Some(loose.clone()), ..Default::default() }).unwrap_err();
    assert!(err.contains("loosens the max-loss rule") && err.contains("$50.00 (5 %) to $200.00 (20 %)"), "{err}");
    assert_eq!(status(&e, &id).config.stop, tight);
    let err = update(&mut e, &id, AutopilotUpdate { stop: Some(StopRules::default()), ..Default::default() }).unwrap_err();
    assert!(err.contains("to no limit"), "removing it is looser too: {err}");
    // More money with the same % is a bigger loss in dollars.
    let err = update(&mut e, &id, AutopilotUpdate { capital_usd: Some(2_000.0), ..Default::default() }).unwrap_err();
    assert!(err.contains("loosens the max-loss rule"), "{err}");
    e.autopilot_update(&id, AutopilotUpdate { stop: Some(loose.clone()), ..Default::default() }, true, VenueCash::NotRead).unwrap();
    assert_eq!(status(&e, &id).config.stop, loose);

    // Rules that would end it on the spot are refused: that is what Stop is for.
    equity_to(&mut e, &id, BTC, 960.0);
    let err = update(&mut e, &id, AutopilotUpdate { stop: Some(StopRules { max_loss_pct: Some(3.0), ..Default::default() }), ..Default::default() })
        .unwrap_err();
    assert!(err.contains("would stop at once"), "{err}");
    let bad = StopRules { trailing_pct: Some(150.0), ..loose.clone() };
    assert!(update(&mut e, &id, AutopilotUpdate { stop: Some(bad), ..Default::default() }).unwrap_err().contains("trailing floor"));

    // A name, and the stop survives a restart and fires at its new level.
    update(&mut e, &id, AutopilotUpdate { name: Some("  Calm  ".into()), stop: Some(StopRules { max_loss_pct: Some(5.0), ..Default::default() }), ..Default::default() })
        .unwrap();
    let saved = serde_json::to_string(&e.to_persisted()).unwrap();
    let mut r = Engine::new();
    r.apply_persisted(serde_json::from_str(&saved).unwrap());
    mark_real(&mut r);
    let s = status(&r, &id);
    assert_eq!(s.config.name, "Calm");
    assert_eq!(s.config.stop.max_loss_pct, Some(5.0));
    equity_to(&mut r, &id, BTC, 950.0);
    step(&mut r);
    assert_eq!(status(&r, &id).state, AutopilotState::Stopped, "the changed rule fires after the restart");
}

#[test]
fn a_live_change_needs_the_confirmation_a_max_loss_rule_and_the_free_cash() {
    let mut e = engine();
    e.set_live(armed_crypto());
    make_live_ready(&mut e, "ema-cross-1");
    let id = e.autopilot_start(live_config("live", 1_000.0, &[("ema-cross-1", 1.0)]), true, VenueCash::Read(1_000.0)).unwrap();
    let name = || AutopilotUpdate { name: Some("Real".into()), ..Default::default() };

    let err = update(&mut e, &id, name()).unwrap_err();
    assert!(err.contains("type the confirmation"), "{err}");
    let err = e
        .autopilot_update(&id, AutopilotUpdate { stop: Some(StopRules::default()), ..Default::default() }, true, VenueCash::NotRead)
        .unwrap_err();
    assert!(err.contains("max-loss rule"), "{err}");

    // More money: only what the venue holds free.
    let more = |x: f64| AutopilotUpdate { capital_usd: Some(x), stop: Some(StopRules { max_loss_usd: Some(100.0), ..Default::default() }), ..Default::default() };
    let err = e.autopilot_update(&id, more(5_000.0), true, VenueCash::Read(1_000.0)).unwrap_err();
    assert!(err.contains("can have at most $1,000.00, not $5,000.00") && err.contains("never moves money"), "{err}");
    let err = e.autopilot_update(&id, more(5_000.0), true, VenueCash::NotRead).unwrap_err();
    assert!(err.contains("was not read"), "{err}");
    let err = e.autopilot_update(&id, more(5_000.0), true, VenueCash::Failed("timed out".into())).unwrap_err();
    assert!(err.contains("(timed out)"), "{err}");
    // Disarmed: no more money, no new strategies.
    e.set_live(LiveConfig { armed: false, ..armed_crypto() });
    let err = e.autopilot_update(&id, more(2_000.0), true, VenueCash::Read(5_000.0)).unwrap_err();
    assert!(err.contains("not armed"), "{err}");
    e.set_live(armed_crypto());
    // A strategy without a green passport cannot be added.
    let err = e.autopilot_update(&id, sleeves_upd(&[("ema-cross-1", 1.0), ("pairs-1", 1.0)]), true, VenueCash::NotRead).unwrap_err();
    assert!(err.contains("is not cleared for live"), "{err}");
    assert_eq!(status(&e, &id).config.capital_usd, 1_000.0, "nothing changed");

    e.autopilot_update(&id, more(2_000.0), true, VenueCash::Read(5_000.0)).unwrap();
    let s = status(&e, &id);
    assert_eq!(s.config.capital_usd, 2_000.0);
    assert!((s.floor_equity.unwrap() - 1_900.0).abs() < 1e-6);
    e.autopilot_update(&id, name(), true, VenueCash::NotRead).unwrap();
    assert_eq!(status(&e, &id).config.name, "Real");
    assert!(e.journal.iter().any(|j| j.kind == JournalKind::Risk && j.message.contains("changed by you: name")));
}

#[test]
fn an_update_can_hand_the_choice_to_the_auto_pick() {
    let (mut e, id) = top20_running();
    let msg = update(&mut e, &id, sleeves_upd(&[])).unwrap();
    let s = status(&e, &id);
    assert!(s.config.sleeves.is_empty());
    assert_eq!(s.config.repick_every_hours, Some(REPICK_DEFAULT_HOURS), "auto re-picks every 24 h by default");
    assert!(s.next_repick_ms.is_some());
    assert!(msg.contains("re-picks every 24 h"), "{msg}");
    assert!(s.by_sleeve.iter().any(|b| b.strategy_id == "lab:tsmom_top20" && !b.dropped), "its own book can be picked again");
    // And back to an explicit choice: re-picking stops.
    update(&mut e, &id, sleeves_upd(&[("lab:tsmom_tranches", 1.0)])).unwrap();
    assert_eq!(status(&e, &id).config.repick_every_hours, None);
}

// ── experimental lab books ─────────────────────────────────────────────────

/// W7's near miss as the lab writes it: a better headline than any book here,
/// but it failed deflation and runs as an experiment.
fn experiment(strategy: &str, generated: i64, weights: &[(&str, f64)]) -> crate::lab::LabSignal {
    let ev = crate::lab::LabEvidence {
        report: "memecoins".into(),
        is_sharpe: Some(1.67),
        oos_sharpe: Some(1.15),
        deflated_p: Some(0.01),
        sharpe_2x_cost: Some(0.94),
        variants_tried: Some(427),
        experimental: true,
        why_failed: Some("deflated p 0.01 over 427 trials".into()),
        ..Default::default()
    };
    let mut s = book(strategy, generated, weights, ev, true);
    s.variant = format!("EXPERIMENT, failed deflation · {strategy}");
    s.experimental = true;
    s
}

#[test]
fn auto_pick_never_picks_an_experiment_however_good_its_numbers() {
    let mut e = idle_engine();
    let now = e.now();
    let w = &[("BTC", 0.3), ("ETH", 0.2)];
    e.apply_lab_signal(experiment("memes_rotation", now, w));
    e.apply_lab_signal(book("tsmom_top20", now, w, top20_evidence(), true));
    assert_eq!(state_of(&e, "lab:memes_rotation"), StrategyState::Paused, "an experiment is idle until named");
    assert!(e.evidence("lab:memes_rotation").score().unwrap() > e.evidence("lab:tsmom_top20").score().unwrap(),
        "the experiment's numbers would win a pick");
    let id = start(&mut e, config("auto", 10_000.0, &[], StopRules::default()));
    let s = status(&e, &id);
    assert!(s.by_sleeve.iter().all(|b| b.strategy_id != "lab:memes_rotation" && !b.experimental));
    assert!(s.by_sleeve.iter().any(|b| b.strategy_id == "lab:tsmom_top20"));
    assert!(!s.last_action.unwrap_or_default().contains("memes_rotation"), "not even named as passed over");

    // Nor at a re-pick, nor when it is the only lab book there is.
    e.apply_lab_signal(experiment("trend4h_pullback", now, w));
    e.autopilot_step(now + 25 * 3_600_000);
    let s = status(&e, &id);
    assert!(s.by_sleeve.iter().all(|b| !b.strategy_id.contains("memes") && !b.strategy_id.contains("trend4h")));
    let mut e = idle_engine();
    e.apply_lab_signal(experiment("memes_rotation", now, w));
    if let Ok(id) = e.autopilot_start(config("only", 10_000.0, &[], StopRules::default()), false, VenueCash::NotRead) {
        assert!(status(&e, &id).by_sleeve.iter().all(|b| !b.strategy_id.starts_with("lab:")));
    }
    assert_eq!(state_of(&e, "lab:memes_rotation"), StrategyState::Paused);

    // A portfolio picks by evidence too: never an experiment.
    let mut e = idle_engine();
    e.apply_lab_signal(experiment("memes_rotation", now, w));
    e.apply_lab_signal(book("breakout_top10", now, w, breakout_evidence(), true));
    let mut c = config("pf", 10_000.0, &[], StopRules::default());
    c.portfolio = true;
    c.mode = AutopilotMode::Paper;
    if let Ok(id) = e.autopilot_start(c, false, VenueCash::NotRead) {
        assert!(status(&e, &id).by_sleeve.iter().all(|b| b.strategy_id != "lab:memes_rotation"));
    }
}

#[test]
fn an_experiment_named_as_a_sleeve_runs_and_says_experiment() {
    let mut e = idle_engine();
    let now = e.now();
    e.apply_lab_signal(experiment("memes_rotation", now, &[("BTC", 0.4)]));
    // A signal that forgot autopilot_only is still an experiment: idle, never standalone.
    let mut loose = experiment("memes_tsmom", now, &[("ETH", 0.1)]);
    loose.autopilot_only = false;
    loose.experimental = false; // only the evidence says it
    let mut plain = engine(); // lab books trade on their own here, unless they are autopilot-only
    plain.apply_lab_signal(loose.clone());
    assert_eq!(state_of(&plain, "lab:memes_tsmom"), StrategyState::Paused);
    plain.run_lab_books();
    assert!(plain.positions.is_empty(), "an experiment never trades on its own");

    let id = start(&mut e, config("exp", 10_000.0, &[("lab:memes_rotation", 1.0)], StopRules::default()));
    let s = status(&e, &id);
    let sl = sleeve(&s, "lab:memes_rotation");
    assert!(sl.experimental);
    assert!(sl.why.starts_with("Chosen by you; EXPERIMENT"), "{}", sl.why);
    assert!(sl.name.contains("EXPERIMENT, failed deflation"));
    e.run_lab_books();
    assert!((notional(&e, BTC) - 4_000.0).abs() < 50.0, "it trades with the autopilot's money: {}", notional(&e, BTC));
    // Its fills reach Telegram marked as an experiment.
    let lines: Vec<_> = e.alert_events.iter().filter_map(|a| a.trade.clone()).collect();
    assert!(!lines.is_empty() && lines.iter().all(|t| t.experiment), "{lines:?}");

    // A live autopilot never runs one, even when named.
    let mut e = idle_engine();
    e.apply_lab_signal(experiment("memes_rotation", now, &[("BTC", 0.4)]));
    e.set_live(armed_crypto());
    let err = e
        .autopilot_start(live_config("live", 1_000.0, &[("lab:memes_rotation", 1.0)]), true, VenueCash::Read(1_000.0))
        .unwrap_err();
    assert!(err.contains("is an experiment") && err.contains("never with real money"), "{err}");
}
