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

// ── Kelly on measured edge ──────────────────────────────────────────────────

fn set_price(e: &mut Engine, id: &str, price: f64) {
    e.markets.iter_mut().find(|m| m.id == id).unwrap().price = price;
}

fn ema_cross(e: &Engine) -> usize {
    e.strategies.iter().position(|s| s.id == "ema-cross-1").unwrap()
}

fn edge(wins: u32, win: f64, losses: u32, loss: f64) -> risk::EdgeRecord {
    let mut r = risk::EdgeRecord::default();
    (0..wins).for_each(|_| r.record(win));
    (0..losses).for_each(|_| r.record(-loss));
    r
}

fn intent_with(market: &str, confidence: f64) -> strategies::SignalIntent {
    strategies::SignalIntent { size: 0.0, confidence, ..buy_intent(market) }
}

/// Notional the strategy opened on BTC after one entry.
fn entry_notional(e: &mut Engine, confidence: f64) -> f64 {
    let idx = ema_cross(e);
    let m = market(e, "crypto:BTC/USD");
    e.place_from_intent(idx, &m, &intent_with("crypto:BTC/USD", confidence));
    e.positions.get("crypto:BTC/USD").map(|p| p.qty * m.price).unwrap_or(0.0)
}

#[test]
fn a_closed_round_trip_lands_on_the_edge_record_net_of_fees() {
    let mut e = Engine::new();
    let idx = ema_cross(&e);
    let id = "crypto:BTC/USD";
    let m = market(&e, id);
    e.fill(idx, &m, Side::Buy, 0.1, 60_000.0);
    set_price(&mut e, id, 66_000.0);
    let m = market(&e, id);
    e.fill(idx, &m, Side::Sell, 0.1, 66_000.0);
    let r = &e.strategies[idx].ledger.edge;
    assert_eq!((r.wins, r.losses), (1, 0));
    // +10% on the quote, less spread and fees: positive but below 10%.
    assert!(r.win_return_sum > 0.05 && r.win_return_sum < 0.10, "{}", r.win_return_sum);

    let m = market(&e, id);
    e.fill(idx, &m, Side::Buy, 0.1, 66_000.0);
    set_price(&mut e, id, 60_000.0);
    let m = market(&e, id);
    e.fill(idx, &m, Side::Sell, 0.1, 60_000.0);
    let r = &e.strategies[idx].ledger.edge;
    assert_eq!((r.wins, r.losses), (1, 1));
    assert!(r.loss_return_sum > 0.09, "a 9% drop plus costs, got {}", r.loss_return_sum);
}

#[test]
fn under_thirty_trades_the_signal_strength_still_sizes() {
    let mut weak = Engine::new();
    let mut strong = Engine::new();
    let idx = ema_cross(&weak);
    weak.strategies[idx].ledger.edge = edge(17, 0.04, 12, 0.02);
    strong.strategies[idx].ledger.edge = edge(17, 0.04, 12, 0.02);
    let (w, s) = (entry_notional(&mut weak, 0.3), entry_notional(&mut strong, 1.0));
    assert!(w > 0.0 && s > 0.0);
    assert!((w / s - 0.3).abs() < 1e-6, "29 trades: confidence 0.3 vs 1.0 should size 0.3x, got {w} vs {s}");
}

#[test]
fn from_thirty_trades_the_record_sizes_and_confidence_no_longer_matters() {
    // Thin edge: 16 of 30 won, wins and losses both 5%. Kelly 1/15, shrunk
    // to 1/30; a quarter of that on 100k is 833 at risk, / 5% / 9 markets =
    // 1852, under the 3000 that full confidence would deploy.
    let mut low = Engine::new();
    let mut high = Engine::new();
    let idx = ema_cross(&low);
    low.strategies[idx].ledger.edge = edge(16, 0.05, 14, 0.05);
    high.strategies[idx].ledger.edge = edge(16, 0.05, 14, 0.05);
    let (l, h) = (entry_notional(&mut low, 0.3), entry_notional(&mut high, 1.0));
    let want = 0.25 * (1.0 / 30.0) * 100_000.0 / 0.05 / 9.0;
    assert!((h - want).abs() < want * 0.01, "got {h}, want about {want}");
    assert!((l - h).abs() < 1e-6, "confidence must not matter once the record decides");
    assert!(high.journal.iter().any(|j| j.message.contains("now sized on its measured edge")));
}

#[test]
fn a_strong_record_is_never_sized_above_full_confidence() {
    let mut plain = Engine::new();
    let mut proven = Engine::new();
    let idx = ema_cross(&plain);
    proven.strategies[idx].ledger.edge = edge(25, 0.05, 5, 0.01);
    let (p, q) = (entry_notional(&mut plain, 1.0), entry_notional(&mut proven, 1.0));
    assert!((p - q).abs() < 1e-6, "full-confidence size is the ceiling: {p} vs {q}");
}

#[test]
fn no_measured_edge_sizes_to_zero_and_says_so_once() {
    let mut e = Engine::new();
    let idx = ema_cross(&e);
    e.strategies[idx].ledger.edge = edge(12, 0.02, 18, 0.02);
    for _ in 0..3 {
        assert_eq!(entry_notional(&mut e, 1.0), 0.0);
    }
    let said = e.journal.iter().filter(|j| j.message.contains("no measured edge")).count();
    assert_eq!(said, 1, "journal once, not on every signal");
    let sizing = e.state().risk.sizing;
    let row = sizing.iter().find(|s| s.strategy_id == "ema-cross-1").unwrap();
    assert_eq!(row.mode, risk::SizingMode::NoEdge);
    assert!(row.kelly.unwrap() < 0.0);
}

#[test]
fn the_edge_record_survives_a_restart() {
    let mut e = Engine::new();
    let idx = ema_cross(&e);
    e.strategies[idx].ledger.edge = edge(20, 0.03, 10, 0.02);
    let json = serde_json::to_string(&e.to_persisted()).unwrap();
    let mut back = Engine::new();
    back.apply_persisted(serde_json::from_str(&json).unwrap());
    let (a, b) = (&back.strategies[idx].ledger.edge, &e.strategies[idx].ledger.edge);
    assert_eq!((a.wins, a.losses), (b.wins, b.losses));
    assert!((a.win_return_sum - b.win_return_sum).abs() < 1e-12);
    assert!((a.loss_return_sum - b.loss_return_sum).abs() < 1e-12);
}

// ── drawdown de-risking ─────────────────────────────────────────────────────

#[test]
fn half_way_to_the_drawdown_breaker_entries_are_half_size() {
    // Both books hold 92.5k; one of them came down from a 100k peak, which is
    // 7.5% drawdown, half of the 15% limit.
    let mut flat = Engine::new();
    let mut down = Engine::new();
    for e in [&mut flat, &mut down] {
        e.cash = 92_500.0;
    }
    flat.peak_equity = 92_500.0;
    down.peak_equity = 100_000.0;

    let st = down.state().risk;
    assert!((st.drawdown_pct - 7.5).abs() < 1e-9);
    assert!((st.derisk_factor - 0.5).abs() < 1e-9);
    assert_eq!(flat.state().risk.derisk_factor, 1.0);

    let (f, d) = (entry_notional(&mut flat, 1.0), entry_notional(&mut down, 1.0));
    assert!(f > 0.0);
    assert!((d / f - 0.5).abs() < 1e-9, "got {d} vs {f}");
}

#[test]
fn at_the_breaker_no_new_entry_is_sized() {
    let mut e = Engine::new();
    e.cash = 85_000.0;
    e.peak_equity = 100_000.0;
    assert_eq!(e.state().risk.derisk_factor, 0.0);
    assert_eq!(entry_notional(&mut e, 1.0), 0.0);
}

#[test]
fn a_save_from_before_the_correlation_cap_loads_with_the_default() {
    let mut v = serde_json::to_value(RiskLimits::default()).unwrap();
    v.as_object_mut().unwrap().remove("maxCorrelatedExposurePct");
    let limits: RiskLimits = serde_json::from_value(v).unwrap();
    assert_eq!(limits.max_correlated_exposure_pct, 40.0);
}
