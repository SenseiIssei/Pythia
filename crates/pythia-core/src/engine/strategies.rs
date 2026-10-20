//! Strategy runtime. Each strategy consumes market data + per-market price
//! history and emits [`SignalIntent`]s (desired exposure). It never touches a
//! venue. Signals are computed from real technical indicators (see
//! [`super::indicators`]) and mirrored 1:1 by the TypeScript engine.

use super::candles::{self, CandleCtx, CandleParams, Pattern};
use super::indicators as ind;
use super::{Market, MarketKind, StrategyConfig, StrategyKind, StrategyParam, StrategyState};
use crate::connectors::{Side, Venue};
use crate::marketdata::Ohlc;
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

/// Run a strategy on closes only. Kinds that need whole candles
/// ([`StrategyKind::Candles`]) emit nothing here; the engine calls
/// [`run_strategy_with_candles`] with its candle store.
pub fn run_strategy(
    cfg: &StrategyConfig,
    markets: &HashMap<String, Market>,
    history: &HashMap<String, Vec<f64>>,
) -> Vec<SignalIntent> {
    run_strategy_with_candles(cfg, markets, history, &HashMap::new())
}

/// Run a strategy with the engine's closed candles per market (`ohlc`, oldest
/// first, the forming bar already dropped) next to the close history.
pub fn run_strategy_with_candles(
    cfg: &StrategyConfig,
    markets: &HashMap<String, Market>,
    history: &HashMap<String, Vec<f64>>,
    ohlc: &HashMap<String, Vec<Ohlc>>,
) -> Vec<SignalIntent> {
    if cfg.state == StrategyState::Paused {
        return vec![];
    }
    match cfg.kind {
        StrategyKind::Candles => candle_patterns(cfg, markets, ohlc),
        StrategyKind::EmaCross => ema_cross(cfg, markets, history),
        StrategyKind::Bollinger => bollinger(cfg, markets, history),
        StrategyKind::RsiReversal => rsi_reversal(cfg, markets, history),
        StrategyKind::MacdTrend => macd_trend(cfg, markets, history),
        StrategyKind::Breakout => breakout(cfg, markets, history),
        StrategyKind::MultiTf => multi_tf(cfg, markets, history),
        StrategyKind::Pairs => pairs(cfg, markets, history),
        StrategyKind::ProbEdge => prob_edge(cfg, markets),
        StrategyKind::Composed => composed_strategy(cfg, markets, history),
        // Lab books trade on the engine's rebalance pass, not on per-tick signals.
        StrategyKind::Arb | StrategyKind::Manual | StrategyKind::LabTargets => vec![],
    }
}

/// User-composed rule strategy: evaluate the rules on each market in the universe.
fn composed_strategy(cfg: &StrategyConfig, markets: &HashMap<String, Market>, history: &HashMap<String, Vec<f64>>) -> Vec<SignalIntent> {
    let Some(rules) = &cfg.rules else { return vec![] };
    let mut out = Vec::new();
    for (id, m, h) in series(cfg, markets, history) {
        if let Some(side) = super::composed::eval_composed(rules, h, m.price) {
            out.push(SignalIntent {
                market_id: id.clone(),
                side,
                size: 0.8,
                confidence: 0.6,
                reason: format!("composed {:?} rules met", rules.direction),
            });
        }
    }
    out
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
        let strength = (clamp01(spread.abs() / 0.02) * clamp01(trend.abs() / 0.03)).sqrt();
        if strength < 0.05 {
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
        if strength < 0.05 {
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
        if strength < 0.1 {
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

/// Prefix of the parameters that switch single patterns on: `pat.hammer` with
/// value 1 lets a hammer count towards an entry, 0 leaves it out.
pub const CANDLE_PATTERN_PREFIX: &str = "pat.";

/// The bullish patterns this strategy's parameters switch on, in registry order.
/// Bearish and neutral names, and names the registry does not know, are ignored.
pub fn candle_selection(cfg: &StrategyConfig) -> Vec<&'static Pattern> {
    candles::bullish()
        .filter(|p| {
            cfg.params
                .iter()
                .any(|q| q.value >= 0.5 && q.key.strip_prefix(CANDLE_PATTERN_PREFIX) == Some(p.name))
        })
        .collect()
}

/// Candlestick patterns, long only. A research strategy with no edge shown yet.
///
/// Goes long a market when, on its last closed candle (or, with `holdBars` > 1,
/// on one of that many most recent closed candles), at least `minBull` of the
/// switched-on bullish patterns fire, and:
///
/// * `noBear` = 1: no bearish pattern fires on that candle;
/// * `atSupport` = 1: one of the firing patterns sits at support (its low
///   within `sr_near` x A of the 20-bar low before it, see
///   [`CandleCtx::at_support`]);
/// * `volume` = 1: that candle's volume is at least 1.5 x the 20-bar mean
///   before it;
/// * `exitOnBear` = 1: no bearish pattern has fired on a later candle.
///
/// Emits nothing otherwise (flat), nothing for a market without real candles
/// and nothing when no pattern is switched on. Exits are the engine's stops and
/// targets, as for every strategy: the engine only opens when flat.
fn candle_patterns(cfg: &StrategyConfig, markets: &HashMap<String, Market>, ohlc: &HashMap<String, Vec<Ohlc>>) -> Vec<SignalIntent> {
    let selected = candle_selection(cfg);
    if selected.is_empty() {
        return vec![];
    }
    let min_bull = param(cfg, "minBull", 1.0).max(1.0) as usize;
    let no_bear = param(cfg, "noBear", 1.0) >= 0.5;
    let need_support = param(cfg, "atSupport", 0.0) >= 0.5;
    let need_volume = param(cfg, "volume", 0.0) >= 0.5;
    let hold = param(cfg, "holdBars", 1.0).max(1.0) as usize;
    let exit_on_bear = param(cfg, "exitOnBear", 1.0) >= 0.5;

    let any_bear = |x: &CandleCtx, t: usize| candles::bearish().any(|p| x.fires(p, t));
    let entry = |x: &CandleCtx, t: usize| -> Option<Vec<&'static str>> {
        let fired: Vec<&'static Pattern> = selected.iter().copied().filter(|p| x.fires(p, t)).collect();
        if fired.len() < min_bull
            || (no_bear && any_bear(x, t))
            || (need_support && !fired.iter().any(|p| x.at_support(t, p.bars)))
            || (need_volume && !x.volume_confirmed(t))
        {
            return None;
        }
        Some(fired.iter().map(|p| p.name).collect())
    };

    let mut out = Vec::new();
    for id in &cfg.universe {
        let Some(m) = markets.get(id) else { continue };
        if m.kind == MarketKind::Prediction {
            continue;
        }
        let Some(bars) = ohlc.get(id).filter(|b| !b.is_empty()) else { continue };
        let x = CandleCtx::from_ohlc(bars, CandleParams::default());
        let last = x.len() - 1;
        let first = last + 1 - hold.min(x.len());
        let Some((t, names)) = (first..=last).rev().find_map(|t| entry(&x, t).map(|n| (t, n))) else { continue };
        if exit_on_bear && (t + 1..=last).any(|u| any_bear(&x, u)) {
            continue;
        }
        let when = match last - t {
            0 => "on the last closed candle".to_string(),
            1 => "1 candle ago".to_string(),
            k => format!("{k} candles ago"),
        };
        out.push(SignalIntent {
            market_id: id.clone(),
            side: Side::Buy,
            size: 0.8,
            confidence: 0.5,
            reason: format!("candles: {} {when}", names.join(" + ")),
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
        rules: None,
        ledger: Default::default(),
    }
}

pub fn default_strategies() -> Vec<StrategyConfig> {
    let crypto = &[
        "crypto:BTC/USD", "crypto:ETH/USD", "crypto:SOL/USD", "crypto:ADA/USD",
        "crypto:DOT/USD", "crypto:LINK/USD", "crypto:AVAX/USD", "crypto:XRP/USD", "crypto:LTC/USD",
    ][..];
    let equities = &["alpaca:AAPL", "alpaca:NVDA", "alpaca:MSFT", "alpaca:AMZN", "alpaca:TSLA"][..];
    vec![
        strat("ema-cross-1", "EMA Cross · Crypto", StrategyKind::EmaCross, Venue::Crypto, StrategyState::Paper, crypto,
            vec![p("fast", "Fast EMA", 9.0, 3.0, 30.0, 1.0), p("slow", "Slow EMA", 21.0, 10.0, 100.0, 1.0)], 18.0),
        strat("multi-tf-1", "Multi-TF Momentum · Crypto", StrategyKind::MultiTf, Venue::Crypto, StrategyState::Paper, crypto,
            vec![p("fast", "Fast EMA", 9.0, 3.0, 30.0, 1.0), p("slow", "Slow EMA", 21.0, 10.0, 100.0, 1.0), p("htf", "HTF ROC", 50.0, 20.0, 150.0, 5.0)], 15.0),
        // Ships PAUSED on the evidence. Walk-forward validation on two years of
        // daily Kraken candles (9 markets, 4 out-of-sample folds, 6bps fee +
        // 8bps slippage per side) returned −10.0% out-of-sample over 56 trades
        // with a 44.6% win rate — and a 98% deflated Sharpe, meaning that loss
        // is not a fluke of the search either. It has no parameters to tune, so
        // there is nothing to re-fit. Re-run `npm run validate` before enabling.
        strat("macd-1", "MACD Trend · Crypto", StrategyKind::MacdTrend, Venue::Crypto, StrategyState::Paused, crypto,
            vec![], 15.0),
        strat("bollinger-1", "Bollinger Revert · Crypto", StrategyKind::Bollinger, Venue::Crypto, StrategyState::Paused, crypto,
            vec![p("period", "Period", 20.0, 5.0, 60.0, 1.0), p("k", "Band σ", 2.0, 1.0, 3.5, 0.1)], 15.0),
        strat("rsi-1", "RSI Reversal · Crypto", StrategyKind::RsiReversal, Venue::Crypto, StrategyState::Paused, crypto,
            vec![p("period", "Period", 14.0, 5.0, 30.0, 1.0), p("oversold", "Oversold", 30.0, 10.0, 45.0, 1.0), p("overbought", "Overbought", 70.0, 55.0, 90.0, 1.0)], 15.0),
        strat("breakout-1", "Donchian Breakout · Equities", StrategyKind::Breakout, Venue::Alpaca, StrategyState::Paused, equities,
            vec![p("period", "Channel", 20.0, 5.0, 60.0, 1.0)], 12.0),
        strat("pairs-1", "Pairs · BTC/ETH", StrategyKind::Pairs, Venue::Crypto, StrategyState::Paused, &["crypto:BTC/USD", "crypto:ETH/USD"],
            vec![p("period", "Z period", 30.0, 10.0, 90.0, 5.0), p("k", "Z entry σ", 2.0, 1.0, 3.5, 0.1)], 12.0),
        strat("prob-edge-1", "Prob-Edge · Polymarket", StrategyKind::ProbEdge, Venue::Polymarket, StrategyState::Paper, &["polymarket:fed-cut-2026", "polymarket:btc-100k-2026"],
            vec![p("edgeThreshold", "Min edge (pp)", 0.05, 0.01, 0.3, 0.01)], 15.0),
        // Ships PAUSED: a research strategy. The lab's candlestick study has
        // shown no edge for these patterns yet; this is here so the engine can
        // forward-test a pattern set on paper once someone switches it on.
        strat("candles-1", "Candlestick Patterns · Crypto (research, no edge yet)", StrategyKind::Candles, Venue::Crypto, StrategyState::Paused, crypto,
            candle_params(), 10.0),
    ]
}

/// The bullish patterns the default candle strategy starts with: the classic
/// reversals. Every other bullish pattern is listed too, switched off.
const DEFAULT_CANDLE_PATTERNS: [&str; 8] = [
    "hammer", "engulfing_bull", "piercing", "morning_star", "morning_doji_star",
    "three_white_soldiers", "three_inside_up", "three_outside_up",
];

fn candle_params() -> Vec<StrategyParam> {
    let mut out = vec![
        p("minBull", "Bullish patterns needed", 1.0, 1.0, 5.0, 1.0),
        p("noBear", "No bearish pattern on the candle (1 = on)", 1.0, 0.0, 1.0, 1.0),
        p("atSupport", "Only at support (1 = on)", 0.0, 0.0, 1.0, 1.0),
        p("volume", "Only on high volume (1 = on)", 0.0, 0.0, 1.0, 1.0),
        p("holdBars", "Signal stays on for candles", 1.0, 1.0, 20.0, 1.0),
        p("exitOnBear", "Signal off after a bearish pattern (1 = on)", 1.0, 0.0, 1.0, 1.0),
    ];
    for pat in candles::bullish() {
        let on = if DEFAULT_CANDLE_PATTERNS.contains(&pat.name) { 1.0 } else { 0.0 };
        let key = format!("{CANDLE_PATTERN_PREFIX}{}", pat.name);
        out.push(p(&key, &format!("Pattern: {}", pat.name.replace('_', " ")), on, 0.0, 1.0, 1.0));
    }
    out
}
