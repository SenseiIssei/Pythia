//! Perps in the engine: the demo route, shorts, margin, funding and the
//! reconciliation (see `engine::perps`). Deterministic: marks, fills, funding
//! and the demo account's answers are handed in.

use super::autopilot::*;
use super::perps::*;
use super::*;
use crate::connectors::perps::{FundingPoint, PerpAccount, PerpExchange, PerpInstrument, PerpTicker, KRAKEN_DEMO_GONE};
use crate::connectors::{BrokerPosition, OpenOrder};

const BTC: &str = "perp:BTC";
const ETH: &str = "perp:ETH";
const SOL: &str = "perp:SOL";
const DOGE: &str = "perp:DOGE";

fn inst(coin: &str, symbol: &str, step: f64) -> PerpInstrument {
    PerpInstrument {
        coin: coin.into(),
        symbol: symbol.into(),
        qty_step: step,
        min_qty: step,
        max_qty: None,
        tick: 0.0001,
        funding_period_ms: 3_600_000,
    }
}

fn instruments() -> Vec<PerpInstrument> {
    vec![
        inst("BTC", "PF_XBTUSD", 0.0001),
        inst("ETH", "PF_ETHUSD", 0.001),
        inst("SOL", "PF_SOLUSD", 0.01),
        inst("DOGE", "PF_DOGEUSD", 1.0),
    ]
}

fn ticker(symbol: &str, mark: f64) -> PerpTicker {
    PerpTicker { symbol: symbol.into(), mark, bid: None, ask: None, funding_rate: Some(0.00001), suspended: false }
}

fn tickers(e: &mut Engine) {
    e.apply_perp_tickers(&[
        ticker("PF_XBTUSD", 100_000.0),
        ticker("PF_ETHUSD", 4_000.0),
        ticker("PF_SOLUSD", 200.0),
        ticker("PF_DOGEUSD", 0.2),
    ]);
}

fn m4_signal(generated: i64, weights: &[(&str, f64)]) -> crate::lab::LabSignal {
    crate::lab::LabSignal {
        strategy: "m4_perps".into(),
        variant: "EXPERIMENT, failed deflation · M4 reg7n".into(),
        as_of_ms: generated - 3_600_000,
        generated_ms: generated,
        valid_until_ms: generated + 36 * 3_600_000,
        quote: "USD".into(),
        weights: weights.iter().map(|(k, v)| (k.to_string(), *v)).collect(),
        regime_on: None,
        evidence: crate::lab::LabEvidence {
            report: "m4_residual".into(),
            oos_sharpe: Some(2.02),
            deflated_p: Some(0.002),
            experimental: true,
            ..Default::default()
        },
        autopilot_only: true,
        dropped: vec![],
        asset_class: Some(crate::lab::PERP.into()),
        experimental: true,
    }
}

const NEUTRAL: [(&str, f64); 4] = [("BTC", 0.25), ("SOL", 0.25), ("ETH", -0.25), ("DOGE", -0.25)];

/// The server's setup: idle lab books, Kraken Futures as the perps venue,
/// its contracts and marks read, the M4 signal in.
fn perps_engine(demo_keys: bool) -> Engine {
    let mut e = Engine::new();
    e.set_lab_books_idle(true);
    e.set_perps_route(Some(PerpExchange::KrakenFutures), demo_keys);
    e.set_perp_instruments(instruments());
    let now = e.now();
    e.apply_lab_signal(m4_signal(now, &NEUTRAL));
    tickers(&mut e);
    if demo_keys {
        e.set_perp_account(Ok(PerpAccount { equity: 50_000.0, available_margin: 50_000.0, initial_margin: 0.0, unrealized_funding: 0.0 }));
    }
    e
}

fn config(id: &str, mode: AutopilotMode, capital: f64) -> AutopilotConfig {
    AutopilotConfig {
        id: id.into(),
        name: "M4 perps (demo)".into(),
        mode,
        venue: "kraken_futures".into(),
        asset_class: None,
        capital_usd: capital,
        sleeves: vec![SleeveConfig { strategy_id: "lab:m4_perps".into(), weight: 1.0 }],
        stop: StopRules { max_loss_pct: Some(20.0), ..Default::default() },
        flatten_on_stop: true,
        max_sleeves: None,
        repick_every_hours: None,
        portfolio: false,
        live_test: false,
    }
}

fn start(e: &mut Engine, c: AutopilotConfig) -> String {
    e.autopilot_start(c, false, VenueCash::NotRead).expect("the perps autopilot starts")
}

fn status(e: &Engine, id: &str) -> AutopilotStatus {
    e.autopilot_statuses().into_iter().find(|s| s.config.id == id).unwrap()
}

fn qty_in(e: &Engine, book: &str, market: &str) -> f64 {
    e.positions.get(&pos_key(book, market)).map(|p| p.qty).unwrap_or(0.0)
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

/// Fill every queued demo order at the engine's mark, 5 bps fee.
fn fill_all(e: &mut Engine) -> Vec<LiveOrderOut> {
    let out = e.drain_live_orders();
    for (n, o) in out.iter().enumerate() {
        e.apply_live_ack(&o.order_id, &format!("kf-{n}"));
        let px = e.price_of(&o.market_id);
        e.apply_live_update(&o.order_id, filled(o.qty, px, o.qty * px * 0.0005));
    }
    out
}

fn journal_has(e: &Engine, needle: &str) -> bool {
    e.journal.iter().any(|j| j.message.contains(needle))
}

// ── the demo route ──────────────────────────────────────────────────────────

#[test]
fn a_demo_autopilot_runs_the_m4_book_long_and_short_on_the_perps_demo_account() {
    let mut e = perps_engine(true);
    // Markets exist only for coins in play, in the venue's own symbols.
    let btc = e.markets.iter().find(|m| m.id == BTC).unwrap();
    assert_eq!((btc.venue, btc.symbol.as_str(), btc.price), (Venue::Perps, "PF_XBTUSD", 100_000.0));
    assert!(e.real_ids.contains(BTC), "a perps mark is a real price; the simulator never moves it");
    let lab = e.strategies.iter().find(|s| s.id == "lab:m4_perps").unwrap();
    assert_eq!(lab.venue_class, Venue::Perps);
    assert_eq!(lab.state, StrategyState::Paused, "experimental and autopilot-only: idle until an autopilot names it");

    let ap = start(&mut e, config("m4", AutopilotMode::Demo, 10_000.0));
    let s = status(&e, &ap);
    assert_eq!(s.config.asset_class, Some(Venue::Perps));
    e.run_lab_books();
    let out = fill_all(&mut e);
    assert_eq!(out.len(), 4, "two longs and two shorts: {out:?}");
    assert!(out.iter().all(|o| o.demo && o.venue == Venue::Perps), "demo orders on the perps venue");
    for o in &out {
        let (side, reduce) = (o.side, o.reduce_only);
        match o.market_id.as_str() {
            BTC | SOL => assert_eq!(side, Side::Buy),
            ETH | DOGE => assert_eq!((side, reduce), (Side::Sell, false), "a short is opened, not a reduce-only sell"),
            other => panic!("unexpected {other}"),
        }
    }
    let sym = |id: &str| out.iter().find(|o| o.market_id == id).unwrap().symbol.clone();
    assert_eq!(sym(BTC), "PF_XBTUSD", "the order carries the venue's symbol");
    // Sized by notional, a quarter of 10,000 each, rounded down to the step.
    assert!((qty_in(&e, &ap, BTC) - 0.025).abs() < 1e-12);
    assert!((qty_in(&e, &ap, ETH) + 0.625).abs() < 1e-12, "ETH is short: {}", qty_in(&e, &ap, ETH));
    assert_eq!(qty_in(&e, &ap, DOGE), -12_500.0);
    let s = status(&e, &ap);
    assert!((s.long_usd - 5_000.0).abs() < 1.0 && (s.short_usd - 5_000.0).abs() < 1.0, "{} {}", s.long_usd, s.short_usd);
    assert!(s.fees > 0.0);
    // The Positions page shows the side.
    let rows: Vec<PositionView> = e.state().positions.into_iter().filter(|p| p.venue == Venue::Perps).collect();
    assert_eq!(rows.len(), 4);
    assert!(rows.iter().any(|r| r.market_id == ETH && r.side == "short" && r.demo && r.funding == Some(0.0)));
    assert!(rows.iter().any(|r| r.market_id == BTC && r.side == "long"));
    let live = e.state().live.perps.unwrap();
    assert_eq!((live.longs, live.shorts, live.exchange.as_str()), (2, 2, "kraken_futures"));
    assert!(live.live.contains("switched off"));

    // A move against the shorts: ETH up 10 %, its short loses 250.
    let before = status(&e, &ap).equity;
    e.apply_perp_tickers(&[ticker("PF_ETHUSD", 4_400.0)]);
    let after = status(&e, &ap).equity;
    assert!((before - after - 250.0).abs() < 1e-6, "{before} -> {after}");

    // The next signal flips ETH long: one buy through zero, not reduce-only,
    // and the shrinking orders go out first.
    let now = e.now();
    e.apply_lab_signal(m4_signal(now + 1, &[("BTC", 0.25), ("SOL", 0.25), ("ETH", 0.25), ("DOGE", -0.25)]));
    tickers(&mut e);
    e.run_lab_books();
    let out = e.drain_live_orders();
    let eth = out.iter().find(|o| o.market_id == ETH).expect("ETH is traded");
    assert_eq!((eth.side, eth.reduce_only), (Side::Buy, false));
    // From -0.625 to a quarter of its equity now (a little under 10,000).
    assert!(eth.qty > 1.2 && eth.qty < 1.25 + 1e-9, "from -0.625 to about +0.62: {}", eth.qty);
    assert!(((eth.qty * 1000.0).round() - eth.qty * 1000.0).abs() < 1e-6, "on the 0.001 step: {}", eth.qty);
}

#[test]
fn a_paper_autopilot_runs_perps_without_keys_and_can_be_short() {
    let mut e = perps_engine(false);
    assert!(e.state().live.perps.unwrap().demo_blocked.unwrap().contains("no Kraken Futures demo keys"));
    let mut c = config("p", AutopilotMode::Demo, 10_000.0);
    assert!(e.autopilot_start(c.clone(), false, VenueCash::NotRead).unwrap_err().contains("demo keys"));
    c.mode = AutopilotMode::Paper;
    let ap = start(&mut e, c);
    e.run_lab_books();
    assert!(e.drain_live_orders().is_empty(), "paper fills at once");
    assert!(qty_in(&e, &ap, ETH) < 0.0 && qty_in(&e, &ap, DOGE) < 0.0, "paper shorts");
    assert!(qty_in(&e, &ap, BTC) > 0.0);
    assert!(e.positions.values().all(|p| !p.demo && !p.live));
}

// ── never live ──────────────────────────────────────────────────────────────

#[test]
fn real_money_perps_are_refused_everywhere_with_one_sentence() {
    let mut e = perps_engine(true);
    let why = e.set_strategy_state("lab:m4_perps", StrategyState::Live).unwrap_err();
    assert!(why.contains("autopilot") || why.contains("switched off"), "{why}");
    // The strategy-state gate itself, on a perps strategy that is not autopilot-only.
    e.set_lab_books_idle(false);
    let now = e.now();
    let mut sig = m4_signal(now, &NEUTRAL);
    sig.strategy = "perps_plain".into();
    sig.autopilot_only = false;
    sig.experimental = false;
    sig.evidence.experimental = false;
    e.apply_lab_signal(sig);
    let why = e.set_strategy_state("lab:perps_plain", StrategyState::Live).unwrap_err();
    assert!(why.contains("Real-money perpetuals are switched off"), "{why}");

    let mut c = config("live", AutopilotMode::Live, 1_000.0);
    let why = e.autopilot_start(c.clone(), true, VenueCash::Read(1_000_000.0)).unwrap_err();
    assert!(why.contains("switched off"), "{why}");
    c.mode = AutopilotMode::Demo;
    c.venue = "bybit_perps".into();
    assert!(e.autopilot_start(c, false, VenueCash::NotRead).unwrap_err().contains("Kraken Futures"), "the venue must be the configured one");

    // The arm drops perps, and a connection test on a perps market is refused.
    e.set_live(LiveConfig { armed: true, paper: false, dry_run: false, venues: vec![Venue::Perps, Venue::Alpaca], timeout_sec: 60, extended_hours: false });
    assert_eq!(e.live_config().venues, vec![Venue::Alpaca]);
    assert!(journal_has(&e, "Perps left out of the live arm"));
    assert!(e.test_order_block(BTC).unwrap().contains("switched off"));
    // And an order routed with a live intent never leaves the engine.
    let i = e.strategies.iter().position(|s| s.id == "lab:perps_plain").unwrap();
    let m = e.markets.iter().find(|m| m.id == BTC).cloned().unwrap();
    e.route_fill_in("", i, &m, Side::Sell, 0.01, 100_000.0, RouteIntent::Live);
    assert!(e.drain_live_orders().is_empty());
    assert!(e.positions.get(BTC).is_none(), "not even simulated");
    assert!(e.orders.iter().any(|o| o.market_id == BTC && o.status == OrderStatus::Rejected));

    // The connector layer has no live perps connector at all.
    let creds = crate::execution::Credentials {
        perps_demo: Some((PerpExchange::KrakenFutures, "k".into(), "s".into())),
        ..Default::default()
    };
    let live = creds.connector_env(Venue::Perps, crate::connectors::Environment::Live, false, false);
    assert!(live.err().unwrap().contains("switched off"));
    let demo = creds.connector_env(Venue::Perps, crate::connectors::Environment::Demo, false, false).unwrap();
    assert!(demo.label().contains("demo"));
    assert!(creds.demo_venues().contains(&Venue::Perps));
}

// ── margin ──────────────────────────────────────────────────────────────────

#[test]
fn orders_that_grow_a_position_need_margin_and_reductions_always_pass() {
    let mut e = perps_engine(true);
    // A thin demo account: 200 of margin covers 2,000 of notional at 10x.
    e.set_perp_account(Ok(PerpAccount { equity: 20_000.0, available_margin: 200.0, initial_margin: 0.0, unrealized_funding: 0.0 }));
    let ap = start(&mut e, config("m", AutopilotMode::Demo, 10_000.0));
    e.run_lab_books();
    let out = e.drain_live_orders();
    assert!(out.is_empty(), "every 2,500 order needs 250 of margin: {out:?}");
    assert!(e.orders.iter().any(|o| o.reject_reason.as_deref().is_some_and(|r| r.contains("available margin"))));
    assert!(journal_has(&e, "perps margin check"));

    // Enough margin, but a signal that wants 3x the autopilot's equity gross
    // is held to 2x: the orders past the cap are refused.
    let mut e = perps_engine(true);
    let ap2 = start(&mut e, config("g", AutopilotMode::Demo, 10_000.0));
    let now = e.now();
    e.apply_lab_signal(m4_signal(now + 5, &[("BTC", 0.75), ("SOL", 0.75), ("ETH", -0.75), ("DOGE", -0.75)]));
    tickers(&mut e);
    e.run_lab_books();
    let out = fill_all(&mut e);
    let gross: f64 = out.iter().map(|o| o.qty * e.price_of(&o.market_id)).sum();
    assert!(gross <= 20_000.0 + 1.0, "gross {gross} within 2x of 10,000");
    assert!(e.orders.iter().any(|o| o.reject_reason.as_deref().is_some_and(|r| r.contains("more than 2x"))));
    // Reducing is never stopped, even with no margin left at all.
    e.set_perp_account(Ok(PerpAccount { equity: 0.0, available_margin: 0.0, initial_margin: 0.0, unrealized_funding: 0.0 }));
    e.autopilot_stop(&ap2, Some(true)).unwrap();
    let closes = e.drain_live_orders();
    assert!(!closes.is_empty() && closes.iter().all(|o| o.reduce_only), "the flatten goes out reduce-only: {closes:?}");
    let _ = ap;

    // The kill switch stops a sell that would open a short.
    let mut e = perps_engine(true);
    start(&mut e, config("k", AutopilotMode::Demo, 10_000.0));
    e.toggle_kill();
    e.run_lab_books();
    let out = e.drain_live_orders();
    assert!(out.iter().all(|o| o.side != Side::Sell), "no new short under the kill switch: {out:?}");
}

#[test]
fn the_retired_kraken_demo_is_named_and_blocks_demo_starts() {
    let mut e = perps_engine(true);
    e.set_perp_account(Err(format!("connector not configured: {KRAKEN_DEMO_GONE}")));
    let why = e.autopilot_start(config("x", AutopilotMode::Demo, 1_000.0), false, VenueCash::NotRead).unwrap_err();
    assert!(why.contains("shut its futures demo"), "{why}");
    assert!(e.state().live.perps.unwrap().demo_blocked.unwrap().contains("2026-07-14"));
    // A good read later clears it.
    e.set_perp_account(Ok(PerpAccount { equity: 5_000.0, available_margin: 5_000.0, ..Default::default() }));
    assert!(e.state().live.perps.unwrap().demo_blocked.is_none());
    // And the amount must fit the demo account.
    let why = e.autopilot_start(config("y", AutopilotMode::Demo, 6_000.0), false, VenueCash::NotRead).unwrap_err();
    assert!(why.contains("demo account holds"), "{why}");
}

// ── funding ─────────────────────────────────────────────────────────────────

#[test]
fn funding_is_booked_per_position_longs_pay_and_shorts_receive() {
    let mut e = perps_engine(true);
    let ap = start(&mut e, config("f", AutopilotMode::Demo, 10_000.0));
    e.run_lab_books();
    let filled_from = e.now();
    fill_all(&mut e);
    let key_btc = pos_key(&ap, BTC);
    let t0 = e.perps.funding_cursor[&key_btc];
    assert!(t0 >= filled_from && t0 <= e.now(), "funding is owed from the fill on");
    e.clock_skew_ms += 2 * 3_600_000 + 1_800_000;
    let due = e.perp_funding_due();
    assert!(due.iter().any(|(s, since)| s == "PF_XBTUSD" && *since == t0), "{due:?}");
    // Kraken: hourly, pro rata, $ per contract. The first hour ended 30
    // minutes after the fill (half an hour owed), the second in full.
    let first = t0 + 1_800_000;
    let pts = |rate_usd: f64| {
        vec![
            FundingPoint { settled_ms: t0 - 1_800_000, period_ms: 3_600_000, rate: 1e-5, per_unit_usd: Some(rate_usd), prorated: true },
            FundingPoint { settled_ms: first, period_ms: 3_600_000, rate: 1e-5, per_unit_usd: Some(rate_usd), prorated: true },
            FundingPoint { settled_ms: first + 3_600_000, period_ms: 3_600_000, rate: 1e-5, per_unit_usd: Some(rate_usd), prorated: true },
        ]
    };
    let before = status(&e, &ap).equity;
    let paid = e.apply_perp_funding("PF_XBTUSD", &pts(1.0));
    // 0.025 BTC long, $1 per BTC per hour: 1.5 hours owed.
    assert!((paid + 0.025 * 1.5).abs() < 1e-12, "{paid}");
    let s = status(&e, &ap);
    assert!((s.funding + 0.0375).abs() < 1e-12 && (s.equity - before + 0.0375).abs() < 1e-9);
    assert_eq!(e.perps.funding_cursor[&key_btc], first + 3_600_000);
    assert_eq!(e.apply_perp_funding("PF_XBTUSD", &pts(1.0)), 0.0, "booked once");
    // A short receives a positive rate; without an absolute rate the
    // relative one is taken on the mark. Bybit: in full at the settlement.
    let key_eth = pos_key(&ap, ETH);
    let c = e.perps.funding_cursor[&key_eth];
    let got = e.apply_perp_funding(
        "PF_ETHUSD",
        &[FundingPoint { settled_ms: c + 1, period_ms: 8 * 3_600_000, rate: 0.0001, per_unit_usd: None, prorated: false }],
    );
    assert!((got - 0.625 * 4_000.0 * 0.0001).abs() < 1e-9, "{got}");
    let row = e.state().positions.into_iter().find(|p| p.key == key_eth).unwrap();
    assert!((row.funding.unwrap() - got).abs() < 1e-12);
    assert!(journal_has(&e, "Funding PF_ETHUSD: received"));
    assert!((e.state().live.perps.unwrap().funding_total - (got - 0.0375)).abs() < 1e-9);
}

// ── reconciliation ──────────────────────────────────────────────────────────

fn bp(symbol: &str, qty: f64, px: f64) -> BrokerPosition {
    BrokerPosition { symbol: symbol.into(), qty, avg_price: px, market_value: qty * px }
}

#[test]
fn the_demo_account_is_reconciled_per_symbol_and_the_venue_wins_when_it_can() {
    let mut e = perps_engine(true);
    let ap = start(&mut e, config("r", AutopilotMode::Demo, 10_000.0));
    e.run_lab_books();
    fill_all(&mut e);
    let venue = vec![
        bp("PF_XBTUSD", 0.025, 100_000.0),
        bp("PF_SOLUSD", 12.5, 200.0),
        bp("PF_ETHUSD", -0.6, 4_000.0),    // the book has -0.625
        bp("PF_DOGEUSD", 12_500.0, 0.2),   // the book is short, the venue long
        bp("PF_LTCUSD", 3.0, 80.0),        // never Pythia's
    ];
    let n = e.apply_perp_reconcile(&venue, &[]);
    let r = e.perps.reconcile.clone().unwrap();
    let st = |s: &str| r.symbols.iter().find(|c| c.symbol == s).unwrap().status;
    assert_eq!(st("PF_XBTUSD"), PerpCheckStatus::Ok);
    assert_eq!(st("PF_ETHUSD"), PerpCheckStatus::Corrected);
    assert_eq!(st("PF_DOGEUSD"), PerpCheckStatus::Mismatch);
    assert_eq!(st("PF_LTCUSD"), PerpCheckStatus::Untracked);
    assert_eq!(n, 2);
    assert!((qty_in(&e, &ap, ETH) + 0.6).abs() < 1e-12, "the venue wins");
    assert_eq!(qty_in(&e, &ap, DOGE), -12_500.0, "a sign conflict is never guessed");
    // The same finding is journaled once.
    let count = |e: &Engine| e.journal.iter().filter(|j| j.message.contains("Perps demo reconcile PF_DOGEUSD")).count();
    let once = count(&e);
    e.apply_perp_reconcile(&venue, &[]);
    assert_eq!(count(&e), once);

    // An order in flight waits for its own report; a stray open order holds the symbol back.
    let now = e.now();
    e.apply_lab_signal(m4_signal(now + 9, &[("BTC", 0.5), ("SOL", 0.25), ("ETH", -0.25), ("DOGE", -0.25)]));
    tickers(&mut e);
    e.run_lab_books();
    let _queued = e.drain_live_orders();
    let venue2 = vec![bp("PF_XBTUSD", 0.05, 100_000.0)];
    e.apply_perp_reconcile(&venue2, &[]);
    let r = e.perps.reconcile.clone().unwrap();
    assert_eq!(r.symbols.iter().find(|c| c.symbol == "PF_XBTUSD").unwrap().status, PerpCheckStatus::Pending);
    let stray = OpenOrder { order: BrokerOrder::acknowledged("someone-else", None), symbol: "PF_SOLUSD".into() };
    e.apply_perp_reconcile(&[bp("PF_SOLUSD", 1.0, 200.0)], &[stray]);
    let r = e.perps.reconcile.clone().unwrap();
    assert_eq!(r.symbols.iter().find(|c| c.symbol == "PF_SOLUSD").unwrap().status, PerpCheckStatus::StrayOrder);
    assert_eq!(r.stray_orders.len(), 1);
}

// ── restart ─────────────────────────────────────────────────────────────────

#[test]
fn a_restart_keeps_the_perps_markets_positions_and_funding_cursor() {
    let mut e = perps_engine(true);
    let ap = start(&mut e, config("s", AutopilotMode::Demo, 10_000.0));
    e.run_lab_books();
    fill_all(&mut e);
    let key = pos_key(&ap, ETH);
    let cursor = e.perps.funding_cursor[&key];
    let saved: Persisted = serde_json::from_str(&serde_json::to_string(&e.to_persisted()).unwrap()).unwrap();
    let mut r = Engine::new();
    r.apply_persisted(saved);
    let m = r.markets.iter().find(|m| m.id == ETH).expect("the perps market is back before the venue is read");
    assert_eq!((m.venue, m.symbol.as_str()), (Venue::Perps, "PF_ETHUSD"));
    assert!((m.price - 4_000.0).abs() < 1e-9, "at its saved mark");
    assert!((qty_in(&r, &ap, ETH) + 0.625).abs() < 1e-12);
    assert_eq!(r.perps.funding_cursor[&key], cursor);
    assert_eq!(r.perps_exchange(), Some(PerpExchange::KrakenFutures));
    // A save from before perps existed loads with none.
    let mut old = serde_json::to_value(e.to_persisted()).unwrap();
    old.as_object_mut().unwrap().remove("perps");
    let old: Persisted = serde_json::from_value(old).unwrap();
    assert!(old.perps.markets.is_empty());
}
