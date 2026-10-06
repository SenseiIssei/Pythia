//! Engine-level tests for the portfolio risk layer: correlation-adjusted
//! exposure, Kelly on measured edge and drawdown de-risking. Kept out of the
//! big test module in `mod.rs` so the two can change independently.

use super::*;

/// Deterministic returns: a shared factor times `beta` plus noise of its own,
/// seeded per market. `beta = 1, noise = 0` makes markets move as one.
fn closes(price: f64, seed: u64, beta: f64, noise: f64) -> Vec<f64> {
    let mut s = seed.wrapping_mul(0x9E37_79B9_7F4A_7C15) | 1;
    let mut rnd = move || {
        s ^= s << 13;
        s ^= s >> 7;
        s ^= s << 17;
        (s >> 11) as f64 / (1u64 << 53) as f64 - 0.5
    };
    let mut p = price;
    (0..60)
        .map(|i| {
            let common = ((i as f64 * 1.7).sin() + (i as f64 * 0.31).cos() * 0.5) * 0.01;
            p *= 1.0 + beta * common + noise * rnd() * 0.02;
            p
        })
        .collect()
}

const CRYPTO: [&str; 9] = [
    "crypto:BTC/USD",
    "crypto:ETH/USD",
    "crypto:SOL/USD",
    "crypto:ADA/USD",
    "crypto:DOT/USD",
    "crypto:LINK/USD",
    "crypto:AVAX/USD",
    "crypto:XRP/USD",
    "crypto:LTC/USD",
];

/// Hold `notional` of a market on the manual book, paid for out of cash so
/// equity stays where it was.
fn hold(e: &mut Engine, id: &str, notional: f64) {
    let price = e.price_of(id);
    e.cash -= notional;
    e.positions.insert(
        id.into(),
        PositionInternal {
            venue: Venue::Crypto,
            symbol: id.split(':').nth(1).unwrap_or(id).into(),
            qty: notional / price,
            avg_price: price,
            strategy_id: "manual".into(),
            stop: 0.0,
            target: 0.0,
            trail_ref: price,
            live: false,
        },
    );
}

fn buy_intent(market: &str) -> strategies::SignalIntent {
    strategies::SignalIntent {
        market_id: market.into(),
        side: Side::Buy,
        size: 1.0,
        confidence: 1.0,
        reason: "test".into(),
    }
}

fn market(e: &Engine, id: &str) -> Market {
    e.markets.iter().find(|m| m.id == id).cloned().unwrap()
}

/// Eight crypto longs of 5k each on 100k equity: 40k gross, which is the
/// correlated-exposure cap when they move as one.
fn crypto_book(beta: f64, noise: f64) -> Engine {
    let mut e = Engine::new();
    for (i, id) in CRYPTO.iter().enumerate() {
        let price = e.price_of(id);
        e.history.insert(id.to_string(), closes(price, i as u64 + 1, beta, noise));
    }
    for id in &CRYPTO[..8] {
        hold(&mut e, id, 5_000.0);
    }
    e
}

fn strategy_idx(e: &Engine) -> usize {
    e.strategies.iter().position(|s| s.state != StrategyState::Paused && s.id != "manual").unwrap()
}

#[test]
fn ten_crypto_longs_are_one_trade_and_the_next_one_is_refused() {
    let mut e = crypto_book(1.0, 0.0);
    let st = e.state();
    assert!((st.risk.correlated_exposure - 40_000.0).abs() < 1.0, "{}", st.risk.correlated_exposure);
    assert!((st.risk.correlated_exposure_pct - 40.0).abs() < 0.01);

    let idx = strategy_idx(&e);
    let m = market(&e, CRYPTO[8]);
    e.place_from_intent(idx, &m, &buy_intent(CRYPTO[8]));
    assert!(!e.positions.contains_key(CRYPTO[8]), "a ninth correlated long must not open");
    let o = &e.orders[0];
    assert_eq!(o.status, OrderStatus::Rejected);
    assert!(o.reject_reason.as_deref().unwrap_or("").starts_with("correlated exposure cap"), "{:?}", o.reject_reason);
    assert!(e.journal.iter().any(|j| j.kind == JournalKind::Reject && j.message.contains("correlated exposure cap")));
}

#[test]
fn the_same_book_of_unrelated_markets_still_has_room() {
    let mut e = crypto_book(0.0, 1.0);
    let st = e.state();
    assert!(
        st.risk.correlated_exposure < 25_000.0,
        "eight unrelated 5k positions should count well under their 40k gross, got {}",
        st.risk.correlated_exposure
    );
    let idx = strategy_idx(&e);
    let m = market(&e, CRYPTO[8]);
    e.place_from_intent(idx, &m, &buy_intent(CRYPTO[8]));
    assert!(e.positions.contains_key(CRYPTO[8]), "{:?}", e.orders.first().and_then(|o| o.reject_reason.clone()));
}

#[test]
fn a_save_from_before_the_correlation_cap_loads_with_the_default() {
    let mut v = serde_json::to_value(RiskLimits::default()).unwrap();
    v.as_object_mut().unwrap().remove("maxCorrelatedExposurePct");
    let limits: RiskLimits = serde_json::from_value(v).unwrap();
    assert_eq!(limits.max_correlated_exposure_pct, 40.0);
}
