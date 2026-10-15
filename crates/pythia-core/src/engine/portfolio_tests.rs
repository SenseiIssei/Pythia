//! A portfolio autopilot across asset classes: one amount over crypto lab
//! books and lab books of US shares in one book, split between the classes
//! by evidence, US shares rebalanced only in the regular session, held
//! against a blend of BTC and SPY. Deterministic: prices, signals and the
//! broker's session are set by hand.

use super::autopilot::*;
use super::*;
use crate::marketdata::RealEquity;

const BTC: &str = "crypto:BTC/USD";
const ETH: &str = "crypto:ETH/USD";
const SPY: &str = "alpaca:SPY";
const IEF: &str = "alpaca:IEF";

/// Real crypto prices, real Alpaca quotes for SPY and IEF, idle lab books
/// (they trade only inside an autopilot).
fn engine() -> Engine {
    let (markets, sim) = seed_markets_with(&["SPY".to_string(), "IEF".to_string()]);
    let mut e = Engine::new();
    e.markets = markets;
    e.sim = sim;
    let now = e.now();
    let ids: Vec<String> = e.markets.iter().filter(|m| m.venue == Venue::Crypto).map(|m| m.id.clone()).collect();
    for m in e.markets.iter_mut().filter(|m| m.venue == Venue::Crypto) {
        m.updated_at = now;
    }
    e.real_ids.extend(ids);
    e.apply_alpaca(&[
        RealEquity { id: SPY.into(), symbol: "SPY".into(), price: 500.0, change24h: 0.0 },
        RealEquity { id: IEF.into(), symbol: "IEF".into(), price: 95.0, change24h: 0.0 },
    ]);
    e.set_lab_books_idle(true);
    e
}

fn session(e: &Engine, open: bool) -> BrokerStatus {
    BrokerStatus {
        market_open: open,
        extended_open: open,
        session_end: None,
        next_open: (!open).then(|| "2026-10-16T09:30:00-04:00".to_string()),
        day_trade_limit_reached: false,
        restricted: None,
        equity: 100_000.0,
        buying_power: 100_000.0,
        checked_at: e.now(),
    }
}

fn evidence(oos: Option<f64>, dd: Option<f64>) -> crate::lab::LabEvidence {
    crate::lab::LabEvidence { oos_sharpe: oos, oos_max_dd: dd, deflated_p: Some(0.97), ..Default::default() }
}

fn book(name: &str, generated: i64, weights: &[(&str, f64)], ev: crate::lab::LabEvidence, shares: bool) -> crate::lab::LabSignal {
    crate::lab::LabSignal {
        strategy: name.into(),
        variant: name.into(),
        as_of_ms: generated - 3_600_000,
        generated_ms: generated,
        // A week: a book of US shares rebalances weekly.
        valid_until_ms: generated + 7 * 86_400_000,
        quote: "USD".into(),
        weights: weights.iter().map(|(k, v)| (k.to_string(), *v)).collect(),
        regime_on: Some(true),
        evidence: ev,
        autopilot_only: false,
        dropped: vec![],
        asset_class: shares.then(|| crate::lab::US_EQUITY.to_string()),
    }
}

fn portfolio(id: &str, capital: f64) -> AutopilotConfig {
    AutopilotConfig {
        id: id.into(),
        name: format!("Portfolio {id}"),
        mode: AutopilotMode::Paper,
        venue: "alpaca".into(),
        asset_class: None,
        capital_usd: capital,
        sleeves: vec![],
        stop: StopRules::default(),
        flatten_on_stop: true,
        max_sleeves: None,
        repick_every_hours: None,
        portfolio: true,
    }
}

fn status(e: &Engine, id: &str) -> AutopilotStatus {
    e.autopilot_statuses().into_iter().find(|s| s.config.id == id).expect("the autopilot exists")
}

fn class(s: &AutopilotStatus, v: Venue) -> ClassStatus {
    s.classes.iter().find(|c| c.class == v).cloned().expect("both classes are listed")
}

fn notional(e: &Engine, book: &str, market: &str) -> f64 {
    e.positions.get(&pos_key(book, market)).map(|p| p.qty * e.price_of(market)).unwrap_or(0.0)
}

fn journal_has(e: &Engine, needle: &str) -> bool {
    e.journal.iter().any(|j| j.message.contains(needle))
}

fn set_price(e: &mut Engine, market: &str, price: f64) {
    let now = e.now();
    let m = e.markets.iter_mut().find(|m| m.id == market).unwrap();
    m.price = price;
    m.updated_at = now;
}

/// The class budget the allocator gives crypto against US shares for the
/// best book of each: evidence per unit of out-of-sample drawdown.
fn crypto_share(e: &Engine, crypto: &str, shares: &str) -> f64 {
    let (c, s) = (e.evidence(crypto), e.evidence(shares));
    let rc = c.score().unwrap() / c.lab_max_dd.unwrap();
    let rs = s.score().unwrap() / s.lab_max_dd.unwrap();
    rc / (rc + rs)
}

#[test]
fn us_shares_without_evidence_get_nothing_and_crypto_takes_the_whole_amount() {
    let mut e = engine();
    let now = e.now();
    e.apply_lab_signal(book("tsmom", now, &[("BTC", 0.5), ("ETH", 0.3)], evidence(Some(0.8), Some(0.4)), false));
    // A book of US shares the lab has no out-of-sample Sharpe for: no evidence.
    e.apply_lab_signal(book("etf_trend", now, &[("SPY", 0.6)], evidence(None, None), true));
    let id = e.autopilot_start(portfolio("p", 10_000.0), false, VenueCash::NotRead).unwrap();
    let s = status(&e, &id);
    assert!(s.config.portfolio && s.config.asset_class.is_none());
    assert_eq!(s.by_sleeve.len(), 1, "{:?}", s.by_sleeve);
    assert_eq!(s.by_sleeve[0].strategy_id, "lab:tsmom");
    assert!((s.by_sleeve[0].weight - 1.0).abs() < 1e-9);
    assert!(s.by_sleeve[0].why.contains("its class (Crypto) gets 100 % of the portfolio by evidence"), "{}", s.by_sleeve[0].why);
    let (c, u) = (class(&s, Venue::Crypto), class(&s, Venue::Alpaca));
    assert!((c.weight - 1.0).abs() < 1e-9 && u.weight == 0.0);
    assert_eq!((c.books, u.books), (1, 0));
    assert!(u.note.as_deref().unwrap().contains("gets nothing"), "{:?}", u.note);
    let msg = s.last_action.clone().unwrap();
    assert!(msg.contains("on crypto and US shares"), "{msg}");
    assert!(msg.contains("split by evidence: Crypto 100 %, US shares 0 %"), "{msg}");
    assert!(msg.contains("Nothing goes to US shares for now (no lab book of US shares has a positive out-of-sample Sharpe"), "{msg}");
    assert!(!msg.contains('\u{2014}'), "no em dash in copy");

    // Held against the blend at the same split: all BTC for now.
    let b = s.benchmark.clone().unwrap();
    assert_eq!(b.symbol, "BTC/USD+SPY");
    assert_eq!(b.legs.len(), 2);
    assert!((b.legs[0].weight - 1.0).abs() < 1e-9 && b.legs[1].weight == 0.0);
    assert_eq!(b.return_pct, Some(0.0));
    let px = e.price_of(BTC);
    set_price(&mut e, BTC, px * 1.1);
    let r = status(&e, &id).benchmark.unwrap().return_pct.unwrap();
    assert!((r - 10.0).abs() < 1e-9, "{r}");

    // A book of US shares whose out-of-sample Sharpe is negative is no evidence either.
    let mut e2 = engine();
    e2.apply_lab_signal(book("tsmom", now, &[("BTC", 0.5)], evidence(Some(0.8), Some(0.4)), false));
    e2.apply_lab_signal(book("etf_trend", now, &[("SPY", 0.6)], evidence(Some(-0.2), Some(0.1)), true));
    let id2 = e2.autopilot_start(portfolio("p2", 10_000.0), false, VenueCash::NotRead).unwrap();
    assert_eq!(class(&status(&e2, &id2), Venue::Alpaca).weight, 0.0);

    // Nothing with evidence anywhere: refused, with the reasons.
    let mut e3 = engine();
    e3.apply_lab_signal(book("etf_trend", now, &[("SPY", 0.6)], evidence(None, None), true));
    let err = e3.autopilot_start(portfolio("p3", 10_000.0), false, VenueCash::NotRead).unwrap_err();
    assert!(err.starts_with("Auto found nothing a portfolio can run"), "{err}");
}

#[test]
fn the_split_is_evidence_per_unit_of_drawdown_and_shares_trade_only_in_the_session() {
    let mut e = engine();
    let now = e.now();
    e.apply_lab_signal(book("tsmom", now, &[("BTC", 0.5), ("ETH", 0.3)], evidence(Some(0.8), Some(0.40)), false));
    e.apply_lab_signal(book("etf_trend", now, &[("SPY", 0.6), ("IEF", 0.3)], evidence(Some(0.8), Some(0.20)), true));
    let id = e.autopilot_start(portfolio("p", 10_000.0), false, VenueCash::NotRead).unwrap();
    let s = status(&e, &id);
    let wc = crypto_share(&e, "lab:tsmom", "lab:etf_trend");
    assert!(wc > 0.0 && wc < 0.5, "the same evidence at twice the drawdown gets less money: {wc}");
    let (c, u) = (class(&s, Venue::Crypto), class(&s, Venue::Alpaca));
    assert!((c.weight - wc).abs() < 1e-9 && (u.weight - (1.0 - wc)).abs() < 1e-9, "{} {}", c.weight, u.weight);
    assert_eq!(s.by_sleeve.len(), 2);
    let b = s.benchmark.unwrap();
    assert!((b.legs[0].weight - wc).abs() < 1e-9 && (b.legs[1].weight - (1.0 - wc)).abs() < 1e-9);
    assert!(b.name.contains("BTC") && b.name.contains("SPY"), "{}", b.name);

    // The US session is closed: crypto rebalances now, US shares are queued.
    e.set_broker_status(session(&e, false));
    e.run_lab_books();
    let btc = notional(&e, &id, BTC);
    assert!((btc - 10_000.0 * wc * 0.5).abs() < 10_000.0 * 0.01, "crypto's budget, not the whole amount: {btc}");
    assert!(notional(&e, &id, ETH) > 0.0);
    assert_eq!(notional(&e, &id, SPY), 0.0, "no US order outside the regular session");
    assert!(journal_has(&e, "Lab rebalance queued: US regular session closed (next open 2026-10-16"));
    let u = class(&status(&e, &id), Venue::Alpaca);
    assert!(u.note.as_deref().unwrap().contains("only in the regular session"), "{:?}", u.note);

    // The session opens: the shares go in, in the same book, crypto untouched.
    e.set_broker_status(session(&e, true));
    let orders = e.orders.len();
    e.run_lab_books();
    let spy = notional(&e, &id, SPY);
    assert!((spy - 10_000.0 * (1.0 - wc) * 0.6).abs() < 10_000.0 * 0.01, "{spy}");
    assert!(notional(&e, &id, IEF) > 0.0);
    assert!((notional(&e, &id, BTC) - btc).abs() < 1e-6, "the crypto group was not traded again");
    assert_eq!(e.orders.len(), orders + 2, "two share orders, nothing else");
    let s = status(&e, &id);
    let (c, u) = (class(&s, Venue::Crypto), class(&s, Venue::Alpaca));
    assert!(c.exposure > 0.0 && u.exposure > 0.0);
    assert!(c.exposure + u.exposure <= s.equity + 1e-6, "never more than its equity");
    assert!(((c.pnl + u.pnl) - s.pnl).abs() < 1e-6, "the classes' P&L adds up to the portfolio's");
    assert!(u.note.is_none(), "{:?}", u.note);
    assert_eq!(s.open_positions, 4);
}

#[test]
fn a_repick_moves_the_split_by_at_most_ten_points_and_the_blend_is_chain_linked() {
    let mut e = engine();
    let now = e.now();
    e.set_broker_status(session(&e, true));
    e.apply_lab_signal(book("tsmom", now, &[("BTC", 0.5)], evidence(Some(1.5), Some(0.30)), false));
    e.apply_lab_signal(book("etf_trend", now, &[("SPY", 0.6)], evidence(Some(0.3), Some(0.30)), true));
    let id = e.autopilot_start(portfolio("p", 10_000.0), false, VenueCash::NotRead).unwrap();
    let before = class(&status(&e, &id), Venue::Crypto).weight;
    assert!((before - crypto_share(&e, "lab:tsmom", "lab:etf_trend")).abs() < 1e-9);
    e.run_lab_books();

    // BTC up 10 %, SPY flat: the blend's first stretch.
    let (btc0, spy0) = (e.price_of(BTC), e.price_of(SPY));
    set_price(&mut e, BTC, btc0 * 1.1);
    let r0 = status(&e, &id).benchmark.unwrap().return_pct.unwrap();
    assert!((r0 - before * 10.0).abs() < 1e-9, "{r0}");

    // US shares' evidence gets much better: the target moves far, the split by ten points.
    e.apply_lab_signal(book("etf_trend", now + 1, &[("SPY", 0.6)], evidence(Some(2.5), Some(0.08)), true));
    let target = crypto_share(&e, "lab:tsmom", "lab:etf_trend");
    assert!(before - target > PORTFOLIO_MAX_SHIFT, "the target is more than a step away: {before} to {target}");
    let orders = e.orders.len();
    e.autopilot_step(now + 25 * 3_600_000);
    assert_eq!(e.orders.len(), orders, "a re-pick itself never trades");
    let s = status(&e, &id);
    let after = class(&s, Venue::Crypto).weight;
    assert!((before - after - PORTFOLIO_MAX_SHIFT).abs() < 1e-9, "{before} to {after}");
    assert!((class(&s, Venue::Alpaca).weight - (1.0 - after)).abs() < 1e-9);
    let msg = s.last_action.clone().unwrap();
    assert!(msg.contains("Split by evidence: Crypto") && msg.contains("(was "), "{msg}");

    // The blend keeps what it earned and goes on at the new weights.
    let b = s.benchmark.unwrap();
    assert!((b.return_pct.unwrap() - r0).abs() < 1e-9, "relinking moves nothing: {:?}", b.return_pct);
    assert!((b.legs[0].weight - after).abs() < 1e-9);
    set_price(&mut e, SPY, spy0 * 1.1);
    let r1 = status(&e, &id).benchmark.unwrap().return_pct.unwrap();
    let want = ((1.0 + r0 / 100.0) * (1.0 + (1.0 - after) * 0.1) - 1.0) * 100.0;
    assert!((r1 - want).abs() < 1e-9, "{r1} against {want}");

    // Saved and restored: the portfolio, its split and its blend come back.
    let saved = e.to_persisted();
    let mut e2 = engine();
    e2.apply_persisted(saved);
    let s2 = status(&e2, &id);
    assert!(s2.config.portfolio);
    assert!((class(&s2, Venue::Crypto).weight - after).abs() < 1e-9);
    assert_eq!(e2.autopilots[0].blend, e.autopilots[0].blend);
}

#[test]
fn a_class_that_loses_its_evidence_drops_to_zero_at_once_and_sells_in_the_session() {
    let mut e = engine();
    let now = e.now();
    e.set_broker_status(session(&e, true));
    e.apply_lab_signal(book("tsmom", now, &[("BTC", 0.5)], evidence(Some(0.8), Some(0.40)), false));
    e.apply_lab_signal(book("etf_trend", now, &[("SPY", 0.6)], evidence(Some(0.8), Some(0.20)), true));
    let id = e.autopilot_start(portfolio("p", 10_000.0), false, VenueCash::NotRead).unwrap();
    e.run_lab_books();
    assert!(notional(&e, &id, SPY) > 0.0);

    // The next week's book of US shares has a negative Sharpe: no evidence.
    e.apply_lab_signal(book("etf_trend", now + 1, &[("SPY", 0.6)], evidence(Some(-0.1), Some(0.20)), true));
    e.autopilot_step(now + 25 * 3_600_000);
    let s = status(&e, &id);
    assert_eq!(class(&s, Venue::Alpaca).weight, 0.0, "no evidence, no money, at once");
    assert!((class(&s, Venue::Crypto).weight - 1.0).abs() < 1e-9);
    assert!(s.by_sleeve.iter().any(|b| b.strategy_id == "lab:etf_trend" && b.dropped));

    // Closed: the shares wait; crypto buys only into what the shares do not hold.
    e.set_broker_status(session(&e, false));
    e.run_lab_books();
    assert!(notional(&e, &id, SPY) > 0.0, "nothing sold outside the session");
    let s = status(&e, &id);
    let (c, u) = (class(&s, Venue::Crypto), class(&s, Venue::Alpaca));
    assert!(c.exposure + u.exposure <= s.equity + 1e-6, "never more than its equity: {} + {} > {}", c.exposure, u.exposure, s.equity);

    // Open: the shares are sold.
    e.set_broker_status(session(&e, true));
    e.run_lab_books();
    assert_eq!(notional(&e, &id, SPY), 0.0);
}

#[test]
fn a_portfolio_is_paper_or_demo_only_and_its_books_are_picked_by_evidence() {
    let mut e = engine();
    let now = e.now();
    e.apply_lab_signal(book("tsmom", now, &[("BTC", 0.5)], evidence(Some(0.8), Some(0.4)), false));
    e.apply_lab_signal(book("etf_trend", now, &[("SPY", 0.6)], evidence(Some(0.8), Some(0.2)), true));

    let mut live = portfolio("l", 1_000.0);
    live.mode = AutopilotMode::Live;
    live.stop.max_loss_pct = Some(10.0);
    let err = e.autopilot_start(live, true, VenueCash::Read(5_000.0)).unwrap_err();
    assert!(err.contains("paper or demo only"), "{err}");

    let mut chosen = portfolio("c", 1_000.0);
    chosen.sleeves = vec![SleeveConfig { strategy_id: "lab:tsmom".into(), weight: 1.0 }];
    let err = e.autopilot_start(chosen, false, VenueCash::NotRead).unwrap_err();
    assert!(err.contains("leave the strategies empty"), "{err}");

    // Demo: both classes on the Alpaca paper account, or not at all.
    let mut demo = portfolio("d", 1_000.0);
    demo.mode = AutopilotMode::Demo;
    e.set_demo_venues([Venue::Alpaca].into_iter().collect(), None, true);
    let err = e.autopilot_start(demo.clone(), false, VenueCash::NotRead).unwrap_err();
    assert!(err.contains("PYTHIA_DEMO_EXCHANGE=alpaca"), "{err}");
    e.set_demo_venues([Venue::Crypto, Venue::Alpaca].into_iter().collect(), Some(CostVenue::Alpaca), true);
    e.set_maker_route(maker::ALPACA_CRYPTO_DEMO, maker::MakerSettings::default()).unwrap();
    assert!(e.autopilot_needs_paper_equity(Some(&demo), None), "the host reads the paper account first");
    let err = e.autopilot_start(demo.clone(), false, VenueCash::Read(500.0)).unwrap_err();
    assert!(err.contains("The Alpaca paper account holds"), "{err}");
    let id = e.autopilot_start(demo, false, VenueCash::Read(50_000.0)).unwrap();

    // Closed session: only the crypto demo orders go to the account.
    e.set_broker_status(session(&e, false));
    e.run_lab_books();
    let out = e.drain_live_orders();
    assert!(!out.is_empty() && out.iter().all(|o| o.demo && o.venue == Venue::Crypto), "{out:?}");
    e.set_broker_status(session(&e, true));
    e.run_lab_books();
    let out = e.drain_live_orders();
    assert_eq!(out.len(), 1, "{out:?}");
    assert!(out[0].demo && out[0].venue == Venue::Alpaca && out[0].symbol == "SPY" && !out[0].extended_hours);

    // Its strategies cannot be chosen by hand later either.
    let upd = AutopilotUpdate { sleeves: Some(vec![SleeveConfig { strategy_id: "lab:tsmom".into(), weight: 1.0 }]), ..Default::default() };
    let err = e.autopilot_update(&id, upd, false, VenueCash::NotRead).unwrap_err();
    assert!(err.contains("is a portfolio"), "{err}");
}
