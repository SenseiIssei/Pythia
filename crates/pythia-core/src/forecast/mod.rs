//! Forecasting — turning opinions into a probability that has earned the right
//! to move money.
//!
//! ```text
//!   market price ──────────────────────────────────────┐  (the baseline)
//!   stat:longshot ─┐                                   │
//!   stat:momentum ─┤                                   ▼
//!   stat:drift    ─┼─► recalibrate ─► weight by ─► pool ─► shrink toward ─► ensemble
//!   llm:anthropic ─┤     (learned)     track record   (log-odds)  market      │
//!   llm:openai    ─┤                                                          ▼
//!   llm:…         ─┘                                          edge − costs ─► Kelly ─► action
//! ```
//!
//! Four properties matter more than any individual model in that diagram:
//!
//! 1. **The market price is the default answer.** Every source has to earn a
//!    deviation from it. A source with no track record moves the ensemble
//!    almost nothing, so on day one Pythia's forecast ≈ the market's, the edge
//!    ≈ 0, and it does not trade. That is correct behaviour, not a bug.
//! 2. **Weight comes from a scoreboard, not from confidence.** A model that
//!    says "0.95, high confidence" and is wrong gets quieter automatically. See
//!    [`calibration::trust`].
//! 3. **Forecasts are recorded before they are scored**, and scored against the
//!    market on the *same* questions. See [`track::ForecastStore`].
//! 4. **Edge is net of costs.** A 3-point edge on a market with a 5-point
//!    spread is a losing trade, and the action here says so.

pub mod aggregate;
pub mod calibration;
pub mod coherence;
pub mod statistical;
pub mod track;

use aggregate::{disagreement, effective_n, kelly_binary, logistic, logit, pool, shrink_toward};
use serde::{Deserialize, Serialize};
use track::{ForecastKind, ForecastStore};

/// Tunables for the whole forecasting stack. Every default here is deliberately
/// timid — the failure mode of a forecasting bot is confidence, not caution.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ForecastConfig {
    /// Bars ahead for a directional forecast, and the matching wall-clock
    /// horizon used to resolve it.
    pub horizon_bars: usize,
    pub horizon_ms: i64,
    /// Favourite–longshot stretch. 1.0 disables the hypothesis.
    pub longshot_k: f64,
    /// How much recent odds drift is extrapolated. Small on purpose.
    pub momentum_beta: f64,
    /// How much of an estimated price drift is believed. 0 disables it.
    pub drift_trust: f64,
    /// Extremizing factor for the pool. 1.0 = off, which is the right default
    /// for a pool of correlated language models — see [`aggregate`].
    pub sharpen: f64,
    /// Weight an unproven source is allowed before it has a track record.
    /// 0.0 is strict mode: nothing untested can move the forecast at all.
    pub bootstrap_trust: f64,
    /// Fraction of full Kelly to stake.
    pub kelly_fraction: f64,
    /// Round-trip cost of a position, in basis points: fees plus the half-spread
    /// on both sides. Prediction markets are wide — this is usually the reason a
    /// promising edge is not a trade.
    pub cost_bps: f64,
    /// Edge below this (after costs) is not worth acting on.
    pub min_edge_bps: f64,
}

impl Default for ForecastConfig {
    fn default() -> Self {
        Self {
            horizon_bars: 40,
            horizon_ms: 3_600_000, // 1h
            longshot_k: 1.08,
            momentum_beta: 0.15,
            drift_trust: 0.5,
            sharpen: 1.0,
            bootstrap_trust: 0.10,
            kelly_fraction: 0.25,
            cost_bps: 150.0, // 1.5% round trip — realistic for a prediction market
            min_edge_bps: 100.0,
        }
    }
}

/// What one source thinks, and how much that counts.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SourceView {
    pub source: String,
    /// What the source actually said.
    pub raw_p: f64,
    /// After its learned recalibration is applied.
    pub p: f64,
    /// Weight in the pool — this is `trust`, floored at the bootstrap value.
    pub weight: f64,
    /// Measured trust from the track record. 0 means "unproven".
    pub trust: f64,
    /// Resolved forecasts behind that number.
    pub n: usize,
    pub rationale: String,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum Action {
    Buy,
    Sell,
    Hold,
}

/// The full picture for one market: who said what, what came out, and whether
/// that is worth a trade.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct MarketForecast {
    pub market_id: String,
    pub symbol: String,
    pub kind: ForecastKind,
    /// The market's own view: implied probability for an event market, 0.5 for
    /// a price market (a random walk's honest answer to "will it be higher?").
    pub market_p: f64,
    pub sources: Vec<SourceView>,
    /// Pooled view of the sources, before shrinking toward the market.
    pub model_p: f64,
    /// The number Pythia actually uses.
    pub ensemble_p: f64,
    /// How far the pool was allowed to pull away from the market, 0..1.
    pub trust: f64,
    /// Spread of opinion in log-odds. High means the sources see different
    /// things — worth reading before acting.
    pub disagreement: f64,
    /// Kish effective number of sources. Ten models that all agree is not ten
    /// pieces of evidence.
    pub effective_sources: f64,
    pub edge: f64,
    pub edge_bps: f64,
    pub cost_bps: f64,
    pub net_edge_bps: f64,
    /// Fraction of bankroll, signed. Negative means the edge is on the short side.
    pub kelly: f64,
    pub action: Action,
    /// Why. Shown verbatim in the UI, because "Hold" without a reason is useless.
    pub reason: String,
    pub ts: i64,
}

/// Everything needed to forecast one market.
pub struct ForecastInput<'a> {
    pub market_id: &'a str,
    pub symbol: &'a str,
    /// Prediction markets: the implied probability. Price markets: the last price.
    pub price: f64,
    pub is_prediction: bool,
    /// Recent closes (price markets) or recent implied probabilities (event markets).
    pub history: &'a [f64],
    pub liquidity: Option<f64>,
    pub days_to_resolution: Option<f64>,
    /// Already-fetched LLM opinions, if any. Fetching them is the caller's job:
    /// this function is synchronous and never touches the network.
    pub llm: &'a [crate::llm::Signal],
    pub now: i64,
}

/// A level view converted into a directional one.
///
/// If you think YES is more likely than the market does, you think the odds are
/// going up. `logistic(logit(model) − logit(market))` is exactly 0.5 when the
/// two agree and moves monotonically with the edge — which makes it a real,
/// falsifiable forecast that resolves on a timer instead of on election night.
pub fn direction_from_edge(model_p: f64, market_p: f64) -> f64 {
    logistic(logit(model_p) - logit(market_p))
}

/// Build the forecast for one market. Pure and synchronous.
pub fn build(input: &ForecastInput, store: &ForecastStore, cfg: &ForecastConfig) -> MarketForecast {
    let kind = if input.is_prediction { ForecastKind::Outcome } else { ForecastKind::Direction };
    // A price market's "market forecast" for *will this be higher* is 0.5: under
    // a random walk that is the correct answer, and it is what a source has to beat.
    let market_p = if input.is_prediction { input.price.clamp(0.001, 0.999) } else { 0.5 };

    let mut raw: Vec<(String, f64, String)> = Vec::new();

    if input.is_prediction {
        let k = cfg.longshot_k;
        if (k - 1.0).abs() > 1e-9 {
            raw.push((
                "stat:longshot".into(),
                statistical::longshot_correction(market_p, k),
                format!("favourite–longshot stretch k={k:.2}"),
            ));
        }
        if let Some(p) = statistical::odds_momentum(input.history, cfg.momentum_beta, input.days_to_resolution) {
            raw.push(("stat:momentum".into(), p, "recent drift in the odds, damped".into()));
        }
    } else if let Some(p) = statistical::price_up_probability(input.history, cfg.horizon_bars, cfg.drift_trust) {
        let vol = statistical::bar_volatility(input.history).unwrap_or(0.0);
        raw.push((
            "stat:drift".into(),
            p,
            format!("shrunk drift over {} bars, σ={:.3}%/bar", cfg.horizon_bars, vol * 100.0),
        ));
    }

    for s in input.llm {
        raw.push((
            format!("llm:{}", s.provider),
            s.probability.clamp(0.0, 1.0),
            s.rationale.clone(),
        ));
    }

    // Recalibrate each source with its own learned curve, then weight it by what
    // its track record has earned.
    let mut sources: Vec<SourceView> = Vec::new();
    for (name, raw_p, rationale) in raw {
        let recal = store.recalibration_of(&name, kind);
        let trust = store.trust_of(&name, kind);
        let n = store.track(&name, kind).score.n;
        sources.push(SourceView {
            p: recal.apply(raw_p),
            raw_p,
            weight: trust.max(cfg.bootstrap_trust),
            trust,
            n,
            source: name,
            rationale,
        });
    }

    let components: Vec<(f64, f64)> = sources.iter().map(|s| (s.p, s.weight)).collect();
    let weights: Vec<f64> = sources.iter().map(|s| s.weight).collect();
    let model_p = pool(&components, cfg.sharpen).unwrap_or(market_p);

    // How far the pool may pull away from the market: saturating in the total
    // weight, so one timid source barely moves it and five proven ones move it a
    // lot — but never all the way.
    let total_w: f64 = weights.iter().sum();
    let trust = (total_w / (total_w + 1.0)).clamp(0.0, 0.9);
    let ensemble_p = shrink_toward(model_p, market_p, trust);

    let edge = ensemble_p - market_p;
    let edge_bps = edge.abs() * 10_000.0;
    let net_edge_bps = edge_bps - cfg.cost_bps;
    let kelly = kelly_binary(ensemble_p, market_p, cfg.kelly_fraction);

    let (action, reason) = decide(&sources, net_edge_bps, edge, cfg);

    MarketForecast {
        market_id: input.market_id.to_string(),
        symbol: input.symbol.to_string(),
        kind,
        market_p,
        disagreement: disagreement(&components),
        effective_sources: effective_n(&weights),
        sources,
        model_p,
        ensemble_p,
        trust,
        edge,
        edge_bps,
        cost_bps: cfg.cost_bps,
        net_edge_bps,
        kelly,
        action,
        reason,
        ts: input.now,
    }
}

/// Turn an edge into an action, with the reason spelled out. Every `Hold` here
/// is a specific refusal, not a shrug.
fn decide(sources: &[SourceView], net_edge_bps: f64, edge: f64, cfg: &ForecastConfig) -> (Action, String) {
    if sources.is_empty() {
        return (Action::Hold, "no forecaster produced an opinion".into());
    }
    if sources.iter().all(|s| s.weight <= 0.0) {
        return (
            Action::Hold,
            "no source has earned any weight yet — forecasts are being recorded and scored, \
             but none may move an order until it beats the market on its own track record"
                .into(),
        );
    }
    if net_edge_bps <= 0.0 {
        return (
            Action::Hold,
            format!(
                "edge {:.0}bps does not cover the {:.0}bps round-trip cost",
                edge.abs() * 10_000.0,
                cfg.cost_bps
            ),
        );
    }
    if net_edge_bps < cfg.min_edge_bps {
        return (
            Action::Hold,
            format!(
                "net edge {net_edge_bps:.0}bps is below the {:.0}bps minimum",
                cfg.min_edge_bps
            ),
        );
    }
    let side = if edge > 0.0 { Action::Buy } else { Action::Sell };
    let proven = sources.iter().filter(|s| s.trust > 0.0).count();
    (
        side,
        format!(
            "net edge {net_edge_bps:.0}bps after {:.0}bps costs, from {} source(s) ({proven} with a track record)",
            cfg.cost_bps,
            sources.len()
        ),
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::llm::{Direction, Signal};

    fn signal(provider: &str, p: f64) -> Signal {
        Signal {
            probability: p,
            direction: Direction::Neutral,
            confidence: 0.5,
            rationale: "test".into(),
            base_rate: None,
            key_drivers: vec![],
            evidence_for: vec![],
            evidence_against: vec![],
            provider: provider.into(),
            model: "m".into(),
        }
    }

    fn prediction_input<'a>(price: f64, llm: &'a [Signal], history: &'a [f64]) -> ForecastInput<'a> {
        ForecastInput {
            market_id: "polymarket:x",
            symbol: "Will X happen?",
            price,
            is_prediction: true,
            history,
            liquidity: Some(100_000.0),
            days_to_resolution: Some(30.0),
            llm,
            now: 0,
        }
    }

    /// The property that matters most: a fresh install does not trade on
    /// forecasts, because nothing has earned the right to disagree with the price.
    #[test]
    fn with_strict_mode_an_untested_ensemble_cannot_move_the_forecast_or_trade() {
        let store = ForecastStore::default();
        let cfg = ForecastConfig { bootstrap_trust: 0.0, ..Default::default() };
        let llm = vec![signal("anthropic", 0.9), signal("openai", 0.88)];
        let f = build(&prediction_input(0.5, &llm, &[]), &store, &cfg);

        assert!((f.ensemble_p - f.market_p).abs() < 1e-9, "must equal the market price");
        assert_eq!(f.action, Action::Hold);
        assert!(f.reason.contains("track record"), "{}", f.reason);
        assert_eq!(f.kelly, 0.0);
        // The opinions are still shown — silenced, not hidden.
        assert_eq!(f.sources.len(), 3, "two models plus the longshot hypothesis");
        assert!(f.sources.iter().all(|s| s.trust == 0.0));
    }

    #[test]
    fn the_bootstrap_weight_lets_an_unproven_source_nudge_but_not_shout() {
        let store = ForecastStore::default();
        let cfg = ForecastConfig { bootstrap_trust: 0.10, longshot_k: 1.0, ..Default::default() };
        let llm = vec![signal("anthropic", 0.95)];
        let f = build(&prediction_input(0.50, &llm, &[]), &store, &cfg);

        assert!(f.ensemble_p > f.market_p, "an opinion should move something");
        assert!(
            f.ensemble_p < 0.60,
            "0.95 from an unproven model must not become a 0.95 forecast — got {}",
            f.ensemble_p
        );
        assert!(f.trust < 0.15);
    }

    #[test]
    fn a_proven_source_is_allowed_to_disagree_with_the_market() {
        // Give llm:anthropic a real Direction track record, then check it earns
        // weight on that question type.
        let mut store = ForecastStore::default();
        for i in 0..300 {
            store.record(0, "m", "llm:anthropic", ForecastKind::Direction, 0.9, 0.5, 100.0, 1000);
            let prices = std::collections::HashMap::from([(
                "m".to_string(),
                if i < 270 { 101.0 } else { 99.0 },
            )]);
            store.auto_resolve(2000, &prices);
        }
        let trust = store.trust_of("llm:anthropic", ForecastKind::Direction);
        assert!(trust > 0.4, "a 300-question record of skill, got {trust}");

        let cfg = ForecastConfig { bootstrap_trust: 0.0, drift_trust: 0.0, ..Default::default() };
        let history: Vec<f64> = (0..100).map(|i| 100.0 + i as f64).collect();
        let llm = vec![signal("anthropic", 0.9)];
        let input = ForecastInput {
            market_id: "crypto:BTC/USD",
            symbol: "BTC/USD",
            price: 100.0,
            is_prediction: false,
            history: &history,
            liquidity: None,
            days_to_resolution: None,
            llm: &llm,
            now: 0,
        };
        let f = build(&input, &store, &cfg);
        assert!(f.trust > 0.2, "proven sources get room, got {}", f.trust);
        assert!(f.ensemble_p > 0.55, "and can actually move the number, got {}", f.ensemble_p);
    }

    #[test]
    fn a_price_market_is_measured_against_a_coin_flip_not_against_its_price() {
        let store = ForecastStore::default();
        let cfg = ForecastConfig::default();
        let history: Vec<f64> = (0..200).map(|i| 30_000.0 * 1.001_f64.powi(i)).collect();
        let input = ForecastInput {
            market_id: "crypto:BTC/USD",
            symbol: "BTC/USD",
            price: 36_000.0,
            is_prediction: false,
            history: &history,
            liquidity: None,
            days_to_resolution: None,
            llm: &[],
            now: 0,
        };
        let f = build(&input, &store, &cfg);
        assert_eq!(f.market_p, 0.5, "the baseline for 'will it be higher' is a coin flip");
        assert_eq!(f.kind, ForecastKind::Direction);
        assert!(f.sources.iter().any(|s| s.source == "stat:drift"));
    }

    #[test]
    fn an_edge_that_does_not_clear_the_spread_is_not_a_trade() {
        let store = ForecastStore::default();
        // Wide market: 400bps round trip. A 2-point edge is 200bps.
        let cfg = ForecastConfig {
            bootstrap_trust: 1.0,
            longshot_k: 1.0,
            cost_bps: 400.0,
            min_edge_bps: 50.0,
            ..Default::default()
        };
        let llm = vec![signal("anthropic", 0.52)];
        let f = build(&prediction_input(0.50, &llm, &[]), &store, &cfg);
        assert_eq!(f.action, Action::Hold);
        assert!(f.reason.contains("cost"), "{}", f.reason);
        assert!(f.net_edge_bps < 0.0);
    }

    #[test]
    fn a_large_edge_from_a_trusted_pool_produces_a_sized_trade() {
        let store = ForecastStore::default();
        let cfg = ForecastConfig {
            bootstrap_trust: 1.0, // pretend everything is proven
            longshot_k: 1.0,
            cost_bps: 100.0,
            min_edge_bps: 100.0,
            ..Default::default()
        };
        let llm = vec![signal("a", 0.90), signal("b", 0.88), signal("c", 0.92)];
        let f = build(&prediction_input(0.40, &llm, &[]), &store, &cfg);
        assert_eq!(f.action, Action::Buy);
        assert!(f.kelly > 0.0);
        assert!(f.net_edge_bps > 100.0);
        assert!(f.effective_sources > 2.5, "three equally weighted sources");
    }

    #[test]
    fn the_short_side_is_identified_when_the_market_is_too_rich() {
        let store = ForecastStore::default();
        let cfg = ForecastConfig { bootstrap_trust: 1.0, longshot_k: 1.0, cost_bps: 50.0, min_edge_bps: 50.0, ..Default::default() };
        let llm = vec![signal("a", 0.20), signal("b", 0.18)];
        let f = build(&prediction_input(0.70, &llm, &[]), &store, &cfg);
        assert_eq!(f.action, Action::Sell);
        assert!(f.kelly < 0.0, "a negative Kelly is the short side");
    }

    #[test]
    fn disagreement_and_effective_count_expose_a_fake_consensus() {
        let store = ForecastStore::default();
        let cfg = ForecastConfig { bootstrap_trust: 1.0, longshot_k: 1.0, ..Default::default() };

        let agree = vec![signal("a", 0.7), signal("b", 0.7), signal("c", 0.7)];
        let split = vec![signal("a", 0.2), signal("b", 0.5), signal("c", 0.9)];
        let f_agree = build(&prediction_input(0.5, &agree, &[]), &store, &cfg);
        let f_split = build(&prediction_input(0.5, &split, &[]), &store, &cfg);

        assert!(f_agree.disagreement < 0.01);
        assert!(f_split.disagreement > 1.0, "a real split must be visible");
        // Both are three sources; disagreement is what distinguishes them.
        assert!((f_agree.effective_sources - f_split.effective_sources).abs() < 1e-9);
    }

    #[test]
    fn with_no_sources_at_all_the_forecast_is_the_market_and_the_reason_says_so() {
        let store = ForecastStore::default();
        let cfg = ForecastConfig { longshot_k: 1.0, ..Default::default() };
        let f = build(&prediction_input(0.42, &[], &[]), &store, &cfg);
        assert!(f.sources.is_empty());
        assert!((f.ensemble_p - 0.42).abs() < 1e-9);
        assert_eq!(f.action, Action::Hold);
        assert!(f.reason.contains("no forecaster"));
    }

    #[test]
    fn the_derived_direction_forecast_is_a_coin_flip_when_there_is_no_edge() {
        assert!((direction_from_edge(0.6, 0.6) - 0.5).abs() < 1e-9);
        assert!(direction_from_edge(0.8, 0.6) > 0.5, "bullish edge → expect odds to rise");
        assert!(direction_from_edge(0.4, 0.6) < 0.5);
        // It stays a probability at the extremes.
        let p = direction_from_edge(0.999_9, 0.000_1);
        assert!((0.0..=1.0).contains(&p));
    }

    #[test]
    fn extreme_market_prices_do_not_produce_infinities() {
        let store = ForecastStore::default();
        let cfg = ForecastConfig { bootstrap_trust: 1.0, ..Default::default() };
        for price in [0.0, 0.0001, 0.9999, 1.0] {
            let llm = vec![signal("a", 0.5)];
            let f = build(&prediction_input(price, &llm, &[]), &store, &cfg);
            assert!(f.ensemble_p.is_finite() && (0.0..=1.0).contains(&f.ensemble_p), "price {price}");
            assert!(f.kelly.is_finite(), "price {price}");
        }
    }
}
