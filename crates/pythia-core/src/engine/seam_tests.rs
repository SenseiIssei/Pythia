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
