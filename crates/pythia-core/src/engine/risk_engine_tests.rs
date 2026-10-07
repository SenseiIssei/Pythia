//! Engine-level tests for the portfolio risk layer: correlation-adjusted
//! exposure on aligned time, Kelly on measured edge (its reset and its
//! rebuild), drawdown de-risking and the volatility spike trim. Kept out of
//! the big test module in `mod.rs` so the two can change independently.

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
            demo: false,
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

// ── Portfolio volatility target ─────────────────────────────────────────────

/// Nine crypto markets on real-looking 5-minute candles that move as one,
/// each bar +-0.3 %: about 97 % a year. Eight are held at `each` notional.
fn candle_book(each: f64) -> Engine {
    let mut e = Engine::new();
    for id in CRYPTO {
        let mut p = e.price_of(id);
        let bars: Vec<Ohlc> = (0..62)
            .map(|i| {
                if i > 0 {
                    p *= if i % 2 == 1 { 1.003 } else { 0.997 };
                }
                Ohlc { ts: 1_790_000_000_000 + i * 300_000, open: p, high: p, low: p, close: p, volume: 1.0 }
            })
            .collect();
        e.apply_bars(&[crate::marketdata::BarSeries { id: id.into(), bars }]);
    }
    for id in &CRYPTO[..8] {
        hold(&mut e, id, each);
    }
    e
}

#[test]
fn the_risk_page_shows_the_book_volatility_measured_from_candles() {
    let e = candle_book(3_000.0);
    let st = e.state();
    let vol = 0.003 * 105_120f64.sqrt();
    assert!((st.risk.portfolio_vol - 24_000.0 * vol).abs() < 50.0, "{}", st.risk.portfolio_vol);
    assert!(st.risk.vol_assumed.is_empty(), "every held market has candles: {:?}", st.risk.vol_assumed);
}

#[test]
fn a_book_swinging_past_its_target_takes_no_new_correlated_long() {
    // 32k at about 97 % swings about 31k a year, over the 30k target, while
    // the correlation cap (40k) would still allow 8k more.
    let mut e = candle_book(4_000.0);
    let idx = strategy_idx(&e);
    let m = market(&e, CRYPTO[8]);
    e.place_from_intent(idx, &m, &buy_intent(CRYPTO[8]));
    assert!(!e.positions.contains_key(CRYPTO[8]));
    let why = e.orders[0].reject_reason.clone().unwrap_or_default();
    assert!(why.starts_with("volatility target"), "{why}");
}

#[test]
fn turning_the_vol_target_off_lets_the_same_long_open() {
    let mut e = candle_book(4_000.0);
    e.limits.portfolio_vol_target_pct = 0.0;
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

#[test]
fn a_save_from_before_the_vol_target_loads_with_the_default() {
    let mut v = serde_json::to_value(RiskLimits::default()).unwrap();
    v.as_object_mut().unwrap().remove("portfolioVolTargetPct");
    let limits: RiskLimits = serde_json::from_value(v).unwrap();
    assert_eq!(limits.portfolio_vol_target_pct, 30.0);
}

// ── correlation on aligned time ─────────────────────────────────────────────

#[test]
fn a_candle_market_against_a_tick_market_counts_as_one_trade_and_says_so() {
    // BTC on 5-minute candles, ETH on ticks, with the very same numbers. The
    // old tail alignment would have called them perfectly correlated, and the
    // short a perfect hedge, for the wrong reason. Now the pair is not
    // measured at all and counts as the worst case for a long and a short.
    let mut e = candle_book(0.0);
    e.positions.clear();
    e.cash = 100_000.0;
    let eth = "crypto:ETH/USD";
    let btc_closes = e.history["crypto:BTC/USD"].clone();
    e.ohlc.remove(eth);
    e.bar_backed.remove(eth);
    e.history.insert(eth.into(), btc_closes.iter().map(|c| c / 20.0).collect());
    hold(&mut e, "crypto:BTC/USD", 10_000.0);
    hold(&mut e, eth, -10_000.0);

    let st = e.state();
    assert_eq!(st.risk.unaligned_pairs, vec![("crypto:BTC/USD".to_string(), eth.to_string())]);
    // An unmeasured hedge is no hedge: the two add up to their gross.
    assert!((st.risk.correlated_exposure - 20_000.0).abs() < 1.0, "{}", st.risk.correlated_exposure);
    // The page gets bar times for the candle market only.
    assert_eq!(st.history_ts["crypto:BTC/USD"].len(), st.history["crypto:BTC/USD"].len());
    assert!(!st.history_ts.contains_key(eth));
}

#[test]
fn two_candle_markets_are_measured_on_their_shared_bars() {
    let e = candle_book(5_000.0);
    let st = e.state();
    assert!(st.risk.unaligned_pairs.is_empty(), "{:?}", st.risk.unaligned_pairs);
    // They move as one on the same bar times: E is the gross.
    assert!((st.risk.correlated_exposure - 40_000.0).abs() < 1.0, "{}", st.risk.correlated_exposure);
}

// ── edge record: reset on a parameter change ────────────────────────────────

fn ema_param(e: &Engine) -> (String, f64) {
    let p = &e.strategies[ema_cross(e)].params[0];
    (p.key.clone(), p.value)
}

#[test]
fn a_parameter_change_starts_the_edge_record_over_and_is_the_way_back_from_no_edge() {
    let mut e = Engine::new();
    let idx = ema_cross(&e);
    e.strategies[idx].ledger.edge = edge(12, 0.02, 18, 0.02);
    assert_eq!(entry_notional(&mut e, 1.0), 0.0, "no edge: size zero");

    let (key, value) = ema_param(&e);
    e.set_strategy_param("ema-cross-1", &key, value);
    assert_eq!(e.strategies[idx].ledger.edge.trades(), 30, "the same value again changes nothing");

    e.set_strategy_param("ema-cross-1", &key, value + 1.0);
    let r = &e.strategies[idx].ledger.edge;
    assert_eq!(r.trades(), 0);
    assert!(r.since.is_some());
    assert!(e.journal.iter().any(|j| j.kind == JournalKind::Risk && j.message.contains("starts again")
        && j.message.contains("sized to zero for no measured edge")));
    assert!(entry_notional(&mut e, 1.0) > 0.0, "the new parameters trade again on signal strength");

    // A second step of the slider has nothing left to reset and says nothing.
    let said = e.journal.iter().filter(|j| j.message.contains("starts again")).count();
    e.set_strategy_param("ema-cross-1", &key, value + 2.0);
    assert_eq!(e.journal.iter().filter(|j| j.message.contains("starts again")).count(), said);
}

#[test]
fn a_parameter_change_takes_a_live_strategy_back_to_paper() {
    let mut e = Engine::new();
    let s = e.strategy_config("ema-cross-1").unwrap();
    e.store_research(validation::ResearchVerdict {
        strategy_id: s.id.clone(),
        params: s.params.iter().map(|p| (p.key.clone(), p.value)).collect(),
        checked_at: 0,
        markets: 1,
        bars: 700,
        cost_venue: CostVenue::Kraken,
        gates: (1..=6).map(|g| validation::Gate::new(g, validation::GateStatus::Pass, "test", Some(1.0))).collect(),
    });
    let idx = ema_cross(&e);
    e.strategies[idx].ledger.paper_since = Some(e.now() - 60 * 86_400_000);
    e.strategies[idx].ledger.forward_trades = 40;
    e.set_strategy_state("ema-cross-1", StrategyState::Live).unwrap();

    let (key, value) = ema_param(&e);
    e.set_strategy_param("ema-cross-1", &key, value + 1.0);
    assert_eq!(e.strategies[idx].state, StrategyState::Paper);
    assert!(e.journal.iter().any(|j| j.message.contains("back to PAPER")));
}

// ── edge record: rebuilt from a save that predates it ───────────────────────

/// Close `n` round trips on BTC: wins of +5 % and losses of -3 %, alternating.
fn round_trips(e: &mut Engine, n: usize) {
    let idx = ema_cross(e);
    let id = "crypto:BTC/USD";
    for i in 0..n {
        set_price(e, id, 60_000.0);
        let m = market(e, id);
        e.fill(idx, &m, Side::Buy, 0.1, 60_000.0);
        set_price(e, id, if i % 2 == 0 { 63_000.0 } else { 58_200.0 });
        let m = market(e, id);
        e.fill(idx, &m, Side::Sell, 0.1, m.price);
    }
}

/// The save as an older build wrote it: no `edge` on any strategy's ledger.
fn without_edge_records(e: &Engine) -> Persisted {
    let mut v = serde_json::to_value(e.to_persisted()).unwrap();
    for s in v["strategies"].as_array_mut().unwrap() {
        s["ledger"].as_object_mut().unwrap().remove("edge");
    }
    serde_json::from_value(v).unwrap()
}

#[test]
fn a_save_from_before_the_edge_record_rebuilds_it_from_the_saved_fills() {
    let mut e = Engine::new();
    round_trips(&mut e, 34);
    let idx = ema_cross(&e);
    let want = e.strategies[idx].ledger.edge.clone();
    assert_eq!(want.trades(), 34);

    let mut back = Engine::new();
    back.apply_persisted(without_edge_records(&e));
    let got = &back.strategies[idx].ledger.edge;
    assert_eq!((got.wins, got.losses), (want.wins, want.losses));
    assert!((got.win_return_sum - want.win_return_sum).abs() < 1e-9, "{} vs {}", got.win_return_sum, want.win_return_sum);
    assert!((got.loss_return_sum - want.loss_return_sum).abs() < 1e-9);
    assert!(back.journal.iter().any(|j| j.message.contains("edge record rebuilt from 34 closed trade")));
    assert_eq!(back.state().risk.sizing.iter().find(|s| s.strategy_id == "ema-cross-1").unwrap().trades, 34);
}

#[test]
fn a_rebuild_never_brings_back_trades_from_before_a_parameter_change() {
    let mut e = Engine::new();
    round_trips(&mut e, 10);
    let (key, value) = ema_param(&e);
    e.set_strategy_param("ema-cross-1", &key, value + 1.0);
    let mut back = Engine::new();
    back.apply_persisted(serde_json::from_str(&serde_json::to_string(&e.to_persisted()).unwrap()).unwrap());
    let r = &back.strategies[ema_cross(&back)].ledger.edge;
    assert_eq!(r.trades(), 0, "the reset survives the restart");
    assert!(r.since.is_some());
}

#[test]
fn a_market_whose_opening_fill_fell_off_the_saved_orders_is_not_guessed_at() {
    let mut e = Engine::new();
    round_trips(&mut e, 2);
    // A long on BTC that is still open, whose buy is no longer in the saved
    // orders (the list keeps the newest 400).
    let idx = ema_cross(&e);
    let m = market(&e, "crypto:BTC/USD");
    e.fill(idx, &m, Side::Buy, 0.1, m.price);
    let mut saved = without_edge_records(&e);
    saved.orders.remove(0);
    let mut back = Engine::new();
    back.apply_persisted(saved);
    // The replay now ends flat on BTC while 0.1 is held: BTC does not reconcile.
    assert_eq!(back.strategies[ema_cross(&back)].ledger.edge.trades(), 0);
}

// ── volatility spike trim ───────────────────────────────────────────────────

const MINUTE: i64 = 60_000;

/// Eight candle-backed longs of 8k (about 62 % a year on 100k) and a 4k short
/// in the ninth, with the trim set to 1.5 x the 30 % target (trigger 45 %).
fn spiking_book() -> Engine {
    let mut e = candle_book(8_000.0);
    hold(&mut e, CRYPTO[8], -4_000.0);
    e.limits.vol_spike_trim_mult = 1.5;
    e
}

fn qtys(e: &Engine) -> HashMap<String, f64> {
    e.positions.iter().map(|(id, p)| (id.clone(), p.qty)).collect()
}

#[test]
fn a_sustained_spike_trims_every_position_alike_back_to_the_target() {
    let mut e = spiking_book();
    let before = qtys(&e);
    let vol0 = e.state().risk.portfolio_vol_pct;
    assert!(vol0 > 45.0, "{vol0}");

    let t0 = 1_800_000_000_000;
    e.check_vol_spike(t0);
    e.check_vol_spike(t0 + 29 * MINUTE);
    assert_eq!(qtys(&e), before, "not sustained long enough yet");
    assert!(e.state().risk.vol_spike_since.is_some());

    e.check_vol_spike(t0 + 30 * MINUTE);
    let keep = 30.0 / vol0;
    for (id, q) in &before {
        let now = e.positions[id].qty;
        assert_eq!(now.signum(), q.signum(), "{id} must not flip");
        assert!(now.abs() < q.abs(), "{id} must only shrink");
        assert!((now / q - keep).abs() < 1e-9, "{id}: kept {} of it, want {keep}", now / q);
    }
    let vol1 = e.state().risk.portfolio_vol_pct;
    assert!((vol1 - 30.0).abs() < 0.5, "back at the target, got {vol1}");
    assert!(e.journal.iter().any(|j| j.kind == JournalKind::Risk && j.message.starts_with("Volatility spike")));
    assert!(e.orders.iter().all(|o| {
        let held = before[&o.market_id];
        (held > 0.0) == (o.side == Side::Sell)
    }), "every trim order closes");
    assert_eq!(e.state().risk.last_vol_trim, Some(t0 + 30 * MINUTE));
}

/// Scale every position by `f`, paid for out of cash so equity stays put.
fn scale_book(e: &mut Engine, f: f64) {
    let ids: Vec<String> = e.positions.keys().cloned().collect();
    for id in ids {
        let price = e.price_of(&id);
        let p = e.positions.get_mut(&id).unwrap();
        e.cash -= p.qty * (f - 1.0) * price;
        p.qty *= f;
    }
}

#[test]
fn a_second_spike_inside_the_hour_waits_for_the_rate_limit() {
    let mut e = spiking_book();
    let t0 = 1_800_000_000_000;
    e.check_vol_spike(t0);
    e.check_vol_spike(t0 + 30 * MINUTE);
    let trimmed = e.orders.len();
    assert!(trimmed > 0);

    scale_book(&mut e, 2.5); // straight back over the trigger
    e.check_vol_spike(t0 + 31 * MINUTE);
    e.check_vol_spike(t0 + 61 * MINUTE);
    e.check_vol_spike(t0 + 89 * MINUTE);
    assert_eq!(e.orders.len(), trimmed, "sustained, but within an hour of the last trim");
    e.check_vol_spike(t0 + 90 * MINUTE);
    assert!(e.orders.len() > trimmed);
}

#[test]
fn the_trim_is_off_by_default() {
    let mut e = spiking_book();
    e.limits = RiskLimits::default();
    assert_eq!(e.limits.vol_spike_trim_mult, 0.0);
    let before = qtys(&e);
    for m in 0..300 {
        e.check_vol_spike(1_800_000_000_000 + m * MINUTE);
    }
    assert_eq!(qtys(&e), before);
    assert!(e.orders.is_empty());
}

#[test]
fn a_real_position_is_trimmed_at_its_venue_not_in_the_simulator() {
    let mut e = spiking_book();
    e.positions.get_mut("crypto:BTC/USD").unwrap().live = true;
    e.set_live(LiveConfig { armed: true, paper: true, venues: vec![Venue::Crypto], ..LiveConfig::default() });
    let held = e.positions["crypto:BTC/USD"].qty;
    let t0 = 1_800_000_000_000;
    e.check_vol_spike(t0);
    e.check_vol_spike(t0 + 30 * MINUTE);
    let out = e.drain_live_orders();
    let btc = out.iter().find(|o| o.market_id == "crypto:BTC/USD").expect("a live exit for the real position");
    assert_eq!(btc.side, Side::Sell);
    assert!(btc.reduce_only);
    assert!(btc.qty < held);
    // Booked when the venue reports the fill, not before.
    assert_eq!(e.positions["crypto:BTC/USD"].qty, held);
}
