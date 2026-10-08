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
        capital_usd: capital,
        sleeves: sleeves.iter().map(|(s, w)| SleeveConfig { strategy_id: s.to_string(), weight: *w }).collect(),
        stop,
        flatten_on_stop: true,
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
    let qty = e.positions[market].qty;
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

fn notional(e: &Engine, market: &str) -> f64 {
    e.positions.get(market).map(|p| p.qty * e.price_of(market)).unwrap_or(0.0)
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
    assert!(!e.positions.contains_key(BTC), "flattened on stop by default");
    assert_eq!(s.trades, 1);
    assert!((s.pnl - (s.equity - 1_000.0)).abs() < 1e-9);
    assert!(s.pnl < 0.0, "a round trip at an unchanged price costs fees and spread");
    assert_eq!(state_of(&e, "ema-cross-1"), StrategyState::Paused, "a stop halts its strategies");
    assert!(journal_has(&e, "stopped: stopped by you. Equity $"));
    assert!(e.autopilot_stop(&id, None).unwrap_err().contains("already stopped"));
    // Once stopped, nothing is reserved any more.
    assert!(e.autopilot_entry_allowed("multi-tf-1", BTC));
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

    let sz = e.autopilot_sizing("ema-cross-1").unwrap();
    assert!((sz.capital - 1_500.0).abs() < 1e-9 && sz.slots == 5.0 && (sz.room - 1_500.0).abs() < 1e-9);

    // A full-strength signal is sized from the sleeve's 1,500 over its 5
    // markets (x1.5), not from the 100,000 of the paper account.
    let target = ema.markets[0].clone();
    let i = idx(&e, "ema-cross-1");
    let m = market(&e, &target);
    e.place_from_intent(i, &m, &buy_intent(&target));
    let n = notional(&e, &target);
    assert!((n - 450.0).abs() < 1.0, "sized from the sleeve: {n}");

    // A strategy may not trade another sleeve's market, and nobody else may
    // trade the autopilot's markets.
    assert!(!e.autopilot_entry_allowed("ema-cross-1", &mtf.markets[0]));
    assert!(e.autopilot_entry_allowed("multi-tf-1", &mtf.markets[0]));
    assert!(!e.autopilot_entry_allowed("rsi-1", &target));
}

#[test]
fn an_entry_never_takes_the_sleeve_past_its_budget() {
    let mut e = engine();
    let id = start(&mut e, config("c", 100.0, &[("ema-cross-1", 1.0)], StopRules::default()));
    enter(&mut e, "ema-cross-1", BTC, 95.0);
    let room = e.autopilot_sizing("ema-cross-1").unwrap().room;
    assert!(room < 6.0, "about 5 dollars left: {room}");
    let equity_before = status(&e, &id).equity;
    let i = idx(&e, "ema-cross-1");
    let m = market(&e, ETH);
    e.place_from_intent(i, &m, &buy_intent(ETH));
    let n = notional(&e, ETH);
    assert!(n > 0.0 && n <= room + 1e-6, "capped at the room left: {n} of {room}");
    let gross: f64 = [BTC, ETH].iter().map(|m| notional(&e, m)).sum();
    assert!(gross <= equity_before + 1e-6, "never more exposure than its equity");
    // With no room left, nothing more is opened.
    let m = market(&e, "crypto:SOL/USD");
    e.place_from_intent(i, &m, &buy_intent("crypto:SOL/USD"));
    assert!(!e.positions.contains_key("crypto:SOL/USD"));
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
    assert!(!e.positions.contains_key(BTC), "flattened");
    assert!(s.equity < 900.0 && s.equity > 898.0, "the exit paid its costs: {}", s.equity);
    assert_eq!(state_of(&e, "ema-cross-1"), StrategyState::Paused);
    assert!(e.drain_alerts().iter().any(|a| a.contains("max loss of 10 %")), "the stop is pushed as an alert");
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
    assert!(!e.positions.contains_key(BTC));
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
    assert!(!e.positions.contains_key(BTC), "flattened");
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
    assert!(!e.positions.contains_key(BTC));
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
    assert!(!e.positions.contains_key(BTC));
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
    assert!(!e.autopilot_entry_allowed("ema-cross-1", ETH), "no new entries while paused");
    assert!(!e.autopilot_entry_allowed("multi-tf-1", ETH), "its markets stay reserved");
    assert_eq!(state_of(&e, "ema-cross-1"), StrategyState::Paper, "pausing does not touch the strategy");
    assert!(e.autopilot_pause(&id).unwrap_err().contains("already paused"));

    e.autopilot_resume(&id).unwrap();
    assert_eq!(status(&e, &id).state, AutopilotState::Running);
    assert!(e.autopilot_entry_allowed("ema-cross-1", ETH));

    e.autopilot_pause(&id).unwrap();
    equity_to(&mut e, &id, BTC, 900.0);
    step(&mut e);
    let s = status(&e, &id);
    assert_eq!(s.state, AutopilotState::Stopped, "the floor protects a paused autopilot too");
    assert!(!e.positions.contains_key(BTC));
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
    assert_eq!(status(&e, &id2).by_sleeve[0].markets.len(), 7, "the seven markets Pairs does not hold");
}

#[test]
fn a_live_autopilot_sends_real_orders_and_pauses_when_live_is_disarmed() {
    let mut e = engine();
    e.set_live(armed_crypto());
    make_live_ready(&mut e, "ema-cross-1");
    let id = e.autopilot_start(live_config("live", 1_000.0, &[("ema-cross-1", 1.0)]), true, VenueCash::Read(1_000.0)).unwrap();

    let i = idx(&e, "ema-cross-1");
    let m = market(&e, BTC);
    e.place_from_intent(i, &m, &buy_intent(BTC));
    let out = e.drain_live_orders();
    assert_eq!(out.len(), 1, "the entry went to the venue");
    assert!(!e.positions.contains_key(BTC), "and was not paper-filled");
    assert!(out[0].qty * out[0].ref_price <= 1_000.0 + 1e-6, "sized from the autopilot");

    e.set_live(LiveConfig { armed: false, ..armed_crypto() });
    assert!(!e.autopilot_entry_allowed("ema-cross-1", ETH), "disarmed: no entry is even considered");
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
    start(&mut e, c);
    assert!(journal_has(&e, "Orders go to the venue's demo account"));
    let i = idx(&e, "ema-cross-1");
    let m = market(&e, BTC);
    e.place_from_intent(i, &m, &buy_intent(BTC));
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

    // A second autopilot cannot reuse a strategy, or a market the first holds.
    let err = e.autopilot_start(config("q", 1_000.0, &[("ema-cross-1", 1.0)], StopRules::default()), false, VenueCash::NotRead).unwrap_err();
    assert!(err.contains("already runs in the autopilot \"Test p\""), "{err}");
    let err = e.autopilot_start(config("q", 1_000.0, &[("multi-tf-1", 1.0)], StopRules::default()), false, VenueCash::NotRead).unwrap_err();
    assert!(err.contains("no market of its own left"), "{err}");

    // The owner cannot flip a claimed strategy behind the autopilot's back.
    let err = e.set_strategy_state("ema-cross-1", StrategyState::Live).unwrap_err();
    assert!(err.contains("runs in the autopilot \"Test p\""), "{err}");
}

#[test]
fn assigning_markets_is_exclusive_and_deterministic() {
    let w = |weight: f64, whole: bool, u: &[&str]| Want { weight, whole, universe: u.iter().map(|s| s.to_string()).collect() };
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
    assert!(journal_has(&e, "left outside the autopilot until closed: ETH/USD"));
    assert_eq!(status(&e, &id).open_positions, 0);
    let half = e.price_of(ETH) * 0.5;
    set_price(&mut e, ETH, half);
    assert!((status(&e, &id).equity - 1_000.0).abs() < 1e-9, "its loss is not the autopilot's");
    e.flatten(ETH);
    let s = status(&e, &id);
    assert_eq!((s.trades, s.fees), (0, 0.0), "and neither is its exit");
    // Once closed, the autopilot trades that market like any other.
    enter(&mut e, "ema-cross-1", ETH, 100.0);
    assert_eq!(status(&e, &id).open_positions, 1);
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
    assert!(e.positions.contains_key(BTC), "left open");
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

    // A lab book that already holds coins cannot start flat inside an autopilot.
    e.autopilot_stop(&id, Some(false)).unwrap();
    let err = e.autopilot_start(config("lab2", 10_000.0, &[("lab:tsmom", 1.0)], StopRules::default()), false, VenueCash::NotRead).unwrap_err();
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

    // Stopped without flattening, its coins stay open and unmanaged, and the
    // flatten rule's consequence is said: it cannot join the next one.
    e.autopilot_stop(&id2, Some(false)).unwrap();
    assert_eq!(held_by(&e, "lab:tsmom_regime"), 1);
    assert_eq!(state_of(&e, "lab:tsmom_regime"), StrategyState::Paused);
    assert!(journal_has(&e, "1 of them belong to a lab book, which carries no stops"));
    let err = e
        .autopilot_start(config("lab3", 2_000.0, &[("lab:tsmom_regime", 1.0)], StopRules::default()), false, VenueCash::NotRead)
        .unwrap_err();
    assert!(err.contains("still holds coins, left open when an autopilot stopped without closing them"), "{err}");
    e.flatten(BTC);
    start(&mut e, config("lab3", 2_000.0, &[("lab:tsmom_regime", 1.0)], StopRules::default()));
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
    assert_eq!(s.by_sleeve.len(), 1, "a lab book claims every crypto market, so it runs alone: {:?}", s.by_sleeve);
    let sl = &s.by_sleeve[0];
    assert_eq!(sl.strategy_id, "lab:tsmom_regime", "5 gates green and deflated p 0.86 beat the families' candidates");
    assert_eq!(sl.weight, 1.0);
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
    assert!(msg.contains("Auto passed over") && msg.contains("Lab · breakout_top10") && msg.contains("EMA Cross"), "{msg}");
    e.run_lab_books();
    assert!(notional(&e, BTC) > 2_900.0, "it rebalances with the autopilot's 10,000");
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
