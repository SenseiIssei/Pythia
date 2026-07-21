//! Strategy runtime. A strategy consumes market data and emits [`SignalIntent`]s
//! (desired exposure); it never touches a venue. Mirrors the TypeScript
//! reference so paper results match across the web and native builds.

use super::{Market, MarketKind, StrategyConfig, StrategyKind, StrategyParam, StrategyState};
use crate::connectors::{Side, Venue};
use std::collections::HashMap;

pub struct SignalIntent {
    pub market_id: String,
    pub side: Side,
    pub size: f64,       // 0..1 fraction of the strategy budget to deploy
    pub confidence: f64, // 0..1, feeds Kelly sizing
    pub reason: String,
}

fn param(cfg: &StrategyConfig, key: &str, fallback: f64) -> f64 {
    cfg.params.iter().find(|p| p.key == key).map(|p| p.value).unwrap_or(fallback)
}

pub fn run_strategy(cfg: &StrategyConfig, markets: &HashMap<String, Market>) -> Vec<SignalIntent> {
    if cfg.state == StrategyState::Paused {
        return vec![];
    }
    match cfg.kind {
        StrategyKind::ProbEdge => prob_edge(cfg, markets),
        StrategyKind::Momentum => momentum(cfg, markets),
        StrategyKind::MeanRevert => mean_revert(cfg, markets),
        StrategyKind::Arb | StrategyKind::Manual => vec![],
    }
}

fn prob_edge(cfg: &StrategyConfig, markets: &HashMap<String, Market>) -> Vec<SignalIntent> {
    let threshold = param(cfg, "edgeThreshold", 0.05);
    let mut out = Vec::new();
    for id in &cfg.universe {
        let Some(m) = markets.get(id) else { continue };
        if m.kind != MarketKind::Prediction {
            continue;
        }
        let Some(model) = m.model_prob else { continue };
        let edge = model - m.price;
        if edge.abs() <= threshold {
            continue;
        }
        out.push(SignalIntent {
            market_id: id.clone(),
            side: if edge > 0.0 { Side::Buy } else { Side::Sell },
            size: (edge.abs() / 0.2).min(1.0),
            confidence: (edge.abs() / 0.15).min(1.0),
            reason: format!("model {:.0}% vs mkt {:.0}% (edge {:.1}pp)", model * 100.0, m.price * 100.0, edge * 100.0),
        });
    }
    out
}

fn momentum(cfg: &StrategyConfig, markets: &HashMap<String, Market>) -> Vec<SignalIntent> {
    let trigger = param(cfg, "trendPct", 0.015);
    let mut out = Vec::new();
    for id in &cfg.universe {
        let Some(m) = markets.get(id) else { continue };
        if m.kind == MarketKind::Prediction {
            continue;
        }
        if m.change24h > trigger {
            out.push(SignalIntent {
                market_id: id.clone(),
                side: Side::Buy,
                size: (m.change24h / (trigger * 4.0)).min(1.0),
                confidence: (m.change24h / (trigger * 3.0)).min(1.0),
                reason: format!("uptrend +{:.1}% > {:.1}%", m.change24h * 100.0, trigger * 100.0),
            });
        } else if m.change24h < -trigger {
            out.push(SignalIntent {
                market_id: id.clone(),
                side: Side::Sell,
                size: (-m.change24h / (trigger * 4.0)).min(1.0),
                confidence: (-m.change24h / (trigger * 3.0)).min(1.0),
                reason: format!("downtrend {:.1}%", m.change24h * 100.0),
            });
        }
    }
    out
}

fn mean_revert(cfg: &StrategyConfig, markets: &HashMap<String, Market>) -> Vec<SignalIntent> {
    let band = param(cfg, "bandPct", 0.03);
    let mut out = Vec::new();
    for id in &cfg.universe {
        let Some(m) = markets.get(id) else { continue };
        if m.kind == MarketKind::Prediction {
            continue;
        }
        if m.change24h > band {
            out.push(SignalIntent {
                market_id: id.clone(),
                side: Side::Sell,
                size: (m.change24h / (band * 3.0)).min(1.0),
                confidence: (m.change24h / (band * 2.0)).min(1.0),
                reason: format!("stretched +{:.1}% — fade", m.change24h * 100.0),
            });
        } else if m.change24h < -band {
            out.push(SignalIntent {
                market_id: id.clone(),
                side: Side::Buy,
                size: (-m.change24h / (band * 3.0)).min(1.0),
                confidence: (-m.change24h / (band * 2.0)).min(1.0),
                reason: format!("oversold {:.1}% — buy", m.change24h * 100.0),
            });
        }
    }
    out
}

pub fn default_strategies() -> Vec<StrategyConfig> {
    vec![
        StrategyConfig {
            id: "prob-edge-1".into(),
            name: "Prob-Edge · Polymarket".into(),
            kind: StrategyKind::ProbEdge,
            venue_class: Venue::Polymarket,
            state: StrategyState::Paper,
            universe: vec!["polymarket:fed-cut-2026".into(), "polymarket:btc-100k-2026".into()],
            params: vec![StrategyParam { key: "edgeThreshold".into(), label: "Min edge (pp)".into(), value: 0.05, min: 0.01, max: 0.3, step: 0.01 }],
            budget_pct: 20.0,
            pnl: 0.0,
            trades: 0,
            win_rate: 0.0,
            equity_curve: vec![0.0],
        },
        StrategyConfig {
            id: "momentum-1".into(),
            name: "Momentum · Crypto".into(),
            kind: StrategyKind::Momentum,
            venue_class: Venue::Crypto,
            state: StrategyState::Paper,
            universe: vec!["crypto:BTC/USD".into(), "crypto:ETH/USD".into(), "crypto:SOL/USD".into()],
            params: vec![StrategyParam { key: "trendPct".into(), label: "Trend trigger".into(), value: 0.015, min: 0.005, max: 0.1, step: 0.005 }],
            budget_pct: 20.0,
            pnl: 0.0,
            trades: 0,
            win_rate: 0.0,
            equity_curve: vec![0.0],
        },
        StrategyConfig {
            id: "mean-revert-1".into(),
            name: "Mean-Revert · Equities".into(),
            kind: StrategyKind::MeanRevert,
            venue_class: Venue::Alpaca,
            state: StrategyState::Paused,
            universe: vec!["alpaca:AAPL".into(), "alpaca:NVDA".into()],
            params: vec![StrategyParam { key: "bandPct".into(), label: "Deviation band".into(), value: 0.03, min: 0.01, max: 0.15, step: 0.005 }],
            budget_pct: 15.0,
            pnl: 0.0,
            trades: 0,
            win_rate: 0.0,
            equity_curve: vec![0.0],
        },
    ]
}
