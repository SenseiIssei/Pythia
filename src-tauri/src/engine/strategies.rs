//! Strategy runtime. Each strategy consumes market data + per-market price
//! history and emits [`SignalIntent`]s (desired exposure). It never touches a
//! venue. Signals are computed from real technical indicators (see
//! [`super::indicators`]) and mirrored 1:1 by the TypeScript engine.

use super::indicators as ind;
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

fn clamp01(x: f64) -> f64 {
    x.clamp(0.0, 1.0)
}

pub fn run_strategy(
    cfg: &StrategyConfig,
    markets: &HashMap<String, Market>,
    history: &HashMap<String, Vec<f64>>,
) -> Vec<SignalIntent> {
    if cfg.state == StrategyState::Paused {
        return vec![];
    }
    match cfg.kind {
        StrategyKind::EmaCross => ema_cross(cfg, markets, history),
        StrategyKind::Bollinger => bollinger(cfg, markets, history),
        StrategyKind::RsiReversal => rsi_reversal(cfg, markets, history),
        StrategyKind::MacdTrend => macd_trend(cfg, markets, history),
        StrategyKind::Breakout => breakout(cfg, markets, history),
        StrategyKind::MultiTf => multi_tf(cfg, markets, history),
        StrategyKind::Pairs => pairs(cfg, markets, history),
        StrategyKind::ProbEdge => prob_edge(cfg, markets),
        StrategyKind::Arb | StrategyKind::Manual => vec![],
    }
}

/// Multi-timeframe momentum: an EMA cross confirmed by a higher-timeframe trend
/// (long-horizon ROC). Only trades when both agree.
fn multi_tf(cfg: &StrategyConfig, markets: &HashMap<String, Market>, history: &HashMap<String, Vec<f64>>) -> Vec<SignalIntent> {
    let fast = param(cfg, "fast", 9.0) as usize;
    let slow = param(cfg, "slow", 21.0) as usize;
    let htf = param(cfg, "htf", 50.0) as usize;
    let mut out = Vec::new();
    for (id, _m, h) in series(cfg, markets, history) {
        let (Some(f), Some(s), Some(trend)) = (ind::ema(h, fast), ind::ema(h, slow), ind::roc(h, htf)) else { continue };
        if s == 0.0 {
            continue;
        }
        let spread = (f - s) / s;
        let strength = clamp01(spread.abs() / 0.02) * clamp01(trend.abs() / 0.03);
        if strength < 0.1 {
            continue;
        }
        if f > s && trend > 0.0 {
            out.push(SignalIntent { market_id: id.clone(), side: Side::Buy, size: strength, confidence: strength, reason: format!("MTF up: EMA{fast}>{slow} & HTF {:+.1}%", trend * 100.0) });
        } else if f < s && trend < 0.0 {
            out.push(SignalIntent { market_id: id.clone(), side: Side::Sell, size: strength, confidence: strength, reason: format!("MTF down: EMA{fast}<{slow} & HTF {:+.1}%", trend * 100.0) });
        }
    }
    out
}

/// Pairs / statistical arbitrage: trade the spread (price ratio) between two
/// correlated assets when its z-score is stretched. Emits an intent on each leg.
fn pairs(cfg: &StrategyConfig, _markets: &HashMap<String, Market>, history: &HashMap<String, Vec<f64>>) -> Vec<SignalIntent> {
    if cfg.universe.len() < 2 {
        return vec![];
    }
    let period = param(cfg, "period", 30.0) as usize;
    let k = param(cfg, "k", 2.0);
    let a = &cfg.universe[0];
    let b = &cfg.universe[1];
    let (Some(ha), Some(hb)) = (history.get(a), history.get(b)) else { return vec![] };
    let n = ha.len().min(hb.len());
    if n < period + 1 {
        return vec![];
    }
    let ratio: Vec<f64> = (0..n)
        .map(|i| {
            let eb = hb[hb.len() - n + i];
            if eb == 0.0 { 1.0 } else { ha[ha.len() - n + i] / eb }
        })
        .collect();
    let Some(z) = ind::zscore(&ratio, period) else { return vec![] };
    if z.abs() <= k {
        return vec![];
    }
    let strength = clamp01((z.abs() - k) / k);
    // ratio high (z>0) → A rich vs B → short A, long B
    let (side_a, side_b) = if z > 0.0 { (Side::Sell, Side::Buy) } else { (Side::Buy, Side::Sell) };
    vec![
        SignalIntent { market_id: a.clone(), side: side_a, size: strength, confidence: strength, reason: format!("pairs z={z:+.2} — leg A") },
        SignalIntent { market_id: b.clone(), side: side_b, size: strength, confidence: strength, reason: format!("pairs z={z:+.2} — leg B") },
    ]
}

/// Only trade tradable (non-prediction) markets that have enough history.
fn series<'a>(
    cfg: &'a StrategyConfig,
    markets: &'a HashMap<String, Market>,
    history: &'a HashMap<String, Vec<f64>>,
) -> impl Iterator<Item = (&'a String, &'a Market, &'a Vec<f64>)> {
    cfg.universe.iter().filter_map(move |id| {
        let m = markets.get(id)?;
        if m.kind == MarketKind::Prediction {
            return None;
        }
        let h = history.get(id)?;
        Some((id, m, h))
    })
}

fn ema_cross(cfg: &StrategyConfig, markets: &HashMap<String, Market>, history: &HashMap<String, Vec<f64>>) -> Vec<SignalIntent> {
    let fast = param(cfg, "fast", 9.0) as usize;
    let slow = param(cfg, "slow", 21.0) as usize;
    let mut out = Vec::new();
    for (id, _m, h) in series(cfg, markets, history) {
        let (Some(f), Some(s)) = (ind::ema(h, fast), ind::ema(h, slow)) else { continue };
        if s == 0.0 {
            continue;
        }
        let spread = (f - s) / s;
        let strength = clamp01(spread.abs() / 0.02);
        if strength < 0.15 {
            continue;
        }
        out.push(SignalIntent {
            market_id: id.clone(),
            side: if f > s { Side::Buy } else { Side::Sell },
            size: strength,
            confidence: strength,
            reason: format!("EMA{fast}/{slow} spread {:+.2}%", spread * 100.0),
        });
    }
    out
}

fn bollinger(cfg: &StrategyConfig, markets: &HashMap<String, Market>, history: &HashMap<String, Vec<f64>>) -> Vec<SignalIntent> {
    let period = param(cfg, "period", 20.0) as usize;
    let k = param(cfg, "k", 2.0);
    let mut out = Vec::new();
    for (id, _m, h) in series(cfg, markets, history) {
        let Some(z) = ind::zscore(h, period) else { continue };
        if z.abs() <= k {
            continue;
        }
        let strength = clamp01((z.abs() - k) / k);
        out.push(SignalIntent {
            market_id: id.clone(),
            // mean reversion: fade the stretch
            side: if z > 0.0 { Side::Sell } else { Side::Buy },
            size: strength,
            confidence: strength,
            reason: format!("Bollinger z={z:+.2} (>{k:.1}σ)"),
        });
    }
    out
}

fn rsi_reversal(cfg: &StrategyConfig, markets: &HashMap<String, Market>, history: &HashMap<String, Vec<f64>>) -> Vec<SignalIntent> {
    let period = param(cfg, "period", 14.0) as usize;
    let os = param(cfg, "oversold", 30.0);
    let ob = param(cfg, "overbought", 70.0);
    let mut out = Vec::new();
    for (id, _m, h) in series(cfg, markets, history) {
        let Some(r) = ind::rsi(h, period) else { continue };
        if r < os {
            out.push(SignalIntent {
                market_id: id.clone(),
                side: Side::Buy,
                size: clamp01((os - r) / os),
                confidence: clamp01((os - r) / os),
                reason: format!("RSI {r:.0} < {os:.0} (oversold)"),
            });
        } else if r > ob {
            out.push(SignalIntent {
                market_id: id.clone(),
                side: Side::Sell,
                size: clamp01((r - ob) / (100.0 - ob)),
                confidence: clamp01((r - ob) / (100.0 - ob)),
                reason: format!("RSI {r:.0} > {ob:.0} (overbought)"),
            });
        }
    }
    out
}

fn macd_trend(cfg: &StrategyConfig, markets: &HashMap<String, Market>, history: &HashMap<String, Vec<f64>>) -> Vec<SignalIntent> {
    let mut out = Vec::new();
    for (id, m, h) in series(cfg, markets, history) {
        let Some((line, signal)) = ind::macd(h) else { continue };
        let hist = line - signal;
        let strength = clamp01((hist.abs() / m.price) / 0.001);
        if strength < 0.2 {
            continue;
        }
        if line > signal && line > 0.0 {
            out.push(SignalIntent { market_id: id.clone(), side: Side::Buy, size: strength, confidence: strength, reason: format!("MACD {line:+.4} > signal {signal:+.4}") });
        } else if line < signal && line < 0.0 {
            out.push(SignalIntent { market_id: id.clone(), side: Side::Sell, size: strength, confidence: strength, reason: format!("MACD {line:+.4} < signal {signal:+.4}") });
        }
    }
    out
}

fn breakout(cfg: &StrategyConfig, markets: &HashMap<String, Market>, history: &HashMap<String, Vec<f64>>) -> Vec<SignalIntent> {
    let period = param(cfg, "period", 20.0) as usize;
    let mut out = Vec::new();
    for (id, m, h) in series(cfg, markets, history) {
        if h.len() < period + 1 {
            continue;
        }
        // channel over the bars BEFORE the current one
        let prior = &h[..h.len() - 1];
        let (Some(hi), Some(lo)) = (ind::donchian_high(prior, period), ind::donchian_low(prior, period)) else { continue };
        if m.price > hi {
            out.push(SignalIntent { market_id: id.clone(), side: Side::Buy, size: 0.8, confidence: 0.6, reason: format!("breakout > {period}-bar high {hi:.2}") });
        } else if m.price < lo {
            out.push(SignalIntent { market_id: id.clone(), side: Side::Sell, size: 0.8, confidence: 0.6, reason: format!("breakdown < {period}-bar low {lo:.2}") });
        }
    }
    out
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
            size: clamp01(edge.abs() / 0.2),
            confidence: clamp01(edge.abs() / 0.15),
            reason: format!("model {:.0}% vs mkt {:.0}% (edge {:+.1}pp)", model * 100.0, m.price * 100.0, edge * 100.0),
        });
    }
    out
}

// ── default strategy set ────────────────────────────────────────────────────
fn p(key: &str, label: &str, value: f64, min: f64, max: f64, step: f64) -> StrategyParam {
    StrategyParam { key: key.into(), label: label.into(), value, min, max, step }
}

fn strat(id: &str, name: &str, kind: StrategyKind, venue: Venue, state: StrategyState, universe: &[&str], params: Vec<StrategyParam>, budget: f64) -> StrategyConfig {
    StrategyConfig {
        id: id.into(),
        name: name.into(),
        kind,
        venue_class: venue,
        state,
        universe: universe.iter().map(|s| s.to_string()).collect(),
        params,
        budget_pct: budget,
        pnl: 0.0,
        trades: 0,
        win_rate: 0.0,
        max_drawdown: 0.0,
        profit_factor: 0.0,
        equity_curve: vec![0.0],
    }
}

pub fn default_strategies() -> Vec<StrategyConfig> {
    let crypto = &[
        "crypto:BTC/USD", "crypto:ETH/USD", "crypto:SOL/USD", "crypto:ADA/USD",
        "crypto:DOT/USD", "crypto:LINK/USD", "crypto:AVAX/USD", "crypto:XRP/USD", "crypto:LTC/USD",
    ][..];
    let equities = &["alpaca:AAPL", "alpaca:NVDA"][..];
    vec![
        strat("ema-cross-1", "EMA Cross · Crypto", StrategyKind::EmaCross, Venue::Crypto, StrategyState::Paper, crypto,
            vec![p("fast", "Fast EMA", 9.0, 3.0, 30.0, 1.0), p("slow", "Slow EMA", 21.0, 10.0, 100.0, 1.0)], 18.0),
        strat("bollinger-1", "Bollinger Revert · Crypto", StrategyKind::Bollinger, Venue::Crypto, StrategyState::Paper, crypto,
            vec![p("period", "Period", 20.0, 5.0, 60.0, 1.0), p("k", "Band σ", 2.0, 1.0, 3.5, 0.1)], 15.0),
        strat("rsi-1", "RSI Reversal · Crypto", StrategyKind::RsiReversal, Venue::Crypto, StrategyState::Paper, crypto,
            vec![p("period", "Period", 14.0, 5.0, 30.0, 1.0), p("oversold", "Oversold", 30.0, 10.0, 45.0, 1.0), p("overbought", "Overbought", 70.0, 55.0, 90.0, 1.0)], 15.0),
        strat("macd-1", "MACD Trend · Crypto", StrategyKind::MacdTrend, Venue::Crypto, StrategyState::Paused, crypto,
            vec![], 15.0),
        strat("breakout-1", "Donchian Breakout · Equities", StrategyKind::Breakout, Venue::Alpaca, StrategyState::Paused, equities,
            vec![p("period", "Channel", 20.0, 5.0, 60.0, 1.0)], 12.0),
        strat("multi-tf-1", "Multi-TF Momentum · Crypto", StrategyKind::MultiTf, Venue::Crypto, StrategyState::Paused, crypto,
            vec![p("fast", "Fast EMA", 9.0, 3.0, 30.0, 1.0), p("slow", "Slow EMA", 21.0, 10.0, 100.0, 1.0), p("htf", "HTF ROC", 50.0, 20.0, 150.0, 5.0)], 15.0),
        strat("pairs-1", "Pairs · BTC/ETH", StrategyKind::Pairs, Venue::Crypto, StrategyState::Paused, &["crypto:BTC/USD", "crypto:ETH/USD"],
            vec![p("period", "Z period", 30.0, 10.0, 90.0, 5.0), p("k", "Z entry σ", 2.0, 1.0, 3.5, 0.1)], 12.0),
        strat("prob-edge-1", "Prob-Edge · Polymarket", StrategyKind::ProbEdge, Venue::Polymarket, StrategyState::Paper, &["polymarket:fed-cut-2026", "polymarket:btc-100k-2026"],
            vec![p("edgeThreshold", "Min edge (pp)", 0.05, 0.01, 0.3, 0.01)], 15.0),
    ]
}
