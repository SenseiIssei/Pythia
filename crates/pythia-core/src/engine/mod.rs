//! Engine core (Phase 1). A persistent portfolio + sovereign risk manager +
//! strategy runtime that ticks on the Tokio runtime and pushes a full
//! [`EngineState`] snapshot to the UI each tick. This is the Rust owner of the
//! same model the browser build runs in TypeScript.

pub mod composed;
pub mod indicators;
pub mod risk;
pub mod strategies;

use crate::connectors::{OrderType, Side, Venue};
use crate::marketdata::{RealCrypto, RealPrediction};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;

// ── serialized enums (match the TypeScript unions) ─────────────────────────
#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
pub enum Mode {
    Paper,
    Live,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
pub enum MarketKind {
    Prediction,
    Crypto,
    Equity,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
pub enum Regime {
    Trending,
    Ranging,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
pub enum OrderStatus {
    Pending,
    Filled,
    Partial,
    Rejected,
    Cancelled,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
pub enum StrategyState {
    Paper,
    Live,
    Paused,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "kebab-case")]
pub enum StrategyKind {
    EmaCross,
    Bollinger,
    RsiReversal,
    MacdTrend,
    Breakout,
    MultiTf,
    Pairs,
    ProbEdge,
    Composed,
    Arb,
    Manual,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
pub enum JournalKind {
    Signal,
    Order,
    Fill,
    Reject,
    Risk,
    System,
}

// ── DTOs (camelCase over the wire) ─────────────────────────────────────────
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Market {
    pub id: String,
    pub venue: Venue,
    pub symbol: String,
    pub kind: MarketKind,
    pub price: f64,
    #[serde(rename = "change24h")]
    pub change24h: f64,
    #[serde(rename = "modelProb", skip_serializing_if = "Option::is_none")]
    pub model_prob: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub liquidity: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub regime: Option<Regime>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub trend_strength: Option<f64>, // efficiency ratio 0..1
    pub updated_at: i64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct VenueBalance {
    pub venue: Venue,
    pub connected: bool,
    pub cash: f64,
    pub equity: f64,
    pub mode: Mode,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct PortfolioSnapshot {
    pub mode: Mode,
    pub cash: f64,
    pub equity: f64,
    pub day_start_equity: f64,
    pub realized_pnl: f64,
    pub unrealized_pnl: f64,
    pub gross_exposure: f64,
    pub equity_curve: Vec<f64>,
    pub balances: Vec<VenueBalance>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct PositionView {
    pub market_id: String,
    pub venue: Venue,
    pub symbol: String,
    pub qty: f64,
    pub avg_price: f64,
    pub last_price: f64,
    pub unrealized: f64,
    pub mode: Mode,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Order {
    pub id: String,
    pub ts: i64,
    pub strategy_id: String,
    pub market_id: String,
    pub venue: Venue,
    pub side: Side,
    #[serde(rename = "type")]
    pub order_type: OrderType,
    pub qty: f64,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub limit_price: Option<f64>,
    pub status: OrderStatus,
    pub filled_qty: f64,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub avg_fill_price: Option<f64>,
    pub mode: Mode,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub reject_reason: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct JournalEntry {
    pub id: String,
    pub ts: i64,
    pub kind: JournalKind,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub strategy_id: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub market_id: Option<String>,
    pub message: String,
    pub mode: Mode,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StrategyParam {
    pub key: String,
    pub label: String,
    pub value: f64,
    pub min: f64,
    pub max: f64,
    pub step: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct StrategyConfig {
    pub id: String,
    pub name: String,
    pub kind: StrategyKind,
    pub venue_class: Venue,
    pub state: StrategyState,
    pub universe: Vec<String>,
    pub params: Vec<StrategyParam>,
    pub budget_pct: f64,
    pub pnl: f64,
    pub trades: u32,
    pub win_rate: f64,
    pub max_drawdown: f64,
    pub profit_factor: f64,
    pub equity_curve: Vec<f64>,
    #[serde(skip_serializing_if = "Option::is_none", default)]
    pub rules: Option<composed::Composed>, // only for kind == Composed
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct RiskLimits {
    pub kill_switch: bool,
    pub max_daily_loss_pct: f64,
    pub max_position_pct: f64,
    pub max_gross_exposure_pct: f64,
    pub per_strategy_budget_pct: f64,
    pub kelly_fraction: f64,
    pub max_orders_per_min: u32,
    pub max_data_staleness_sec: u64,
    // ── advanced controls ──
    pub max_drawdown_pct: f64,       // peak-to-trough equity; breach trips the kill switch
    pub stop_atr_mult: f64,          // per-position stop-loss, in ATR units (0 = off)
    pub take_profit_atr_mult: f64,   // per-position take-profit, in ATR units (0 = off)
    pub trailing_atr_mult: f64,      // trailing stop distance in ATR units (0 = off)
    pub max_consecutive_losses: u32, // per strategy before a cooldown (0 = off)
    pub cooldown_sec: u64,           // cooldown duration after the loss streak
    pub vol_target_pct: f64,         // volatility-targeted sizing: target per-bar vol % (0 = off)
    pub regime_filter: bool,         // block mean-reversion in trends & trend strategies in chop
    pub adaptive_allocation: bool,   // auto-weight strategy budgets by recent performance
}

impl Default for RiskLimits {
    fn default() -> Self {
        Self {
            kill_switch: false,
            max_daily_loss_pct: 5.0,
            max_position_pct: 15.0,
            max_gross_exposure_pct: 70.0,
            per_strategy_budget_pct: 35.0,
            kelly_fraction: 0.25,
            max_orders_per_min: 60,
            max_data_staleness_sec: 30,
            max_drawdown_pct: 15.0,
            stop_atr_mult: 8.0,      // wide — survive normal pullbacks, cut real reversals
            take_profit_atr_mult: 0.0, // off — let winners ride the trend
            trailing_atr_mult: 6.0,  // loose trailing stop locks in gains as trends extend
            max_consecutive_losses: 4,
            cooldown_sec: 300,
            vol_target_pct: 0.0,
            regime_filter: false,
            adaptive_allocation: true, // steer capital to what's working
        }
    }
}

#[derive(Debug, Clone)]
pub struct RiskDecision {
    pub approved: bool,
    pub qty: f64,
    pub reason: Option<String>,
}

/// Live-execution status surfaced to the UI. Live routing is OFF until the user
/// explicitly arms it (typed confirmation), and only Alpaca orders from a Live
/// strategy are ever sent to a real venue.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct LiveStatus {
    /// Master arm. When false, everything simulates — no order leaves the machine.
    pub armed: bool,
    /// Route to the broker's PAPER endpoint (real API, no real money).
    pub paper: bool,
    /// Log intended orders but don't submit them anywhere.
    pub dry_run: bool,
    /// Alpaca has keys in the vault / env.
    pub alpaca_connected: bool,
    /// Live orders currently awaiting a broker response.
    pub pending: usize,
}

/// One live order handed to the async daemon to submit. The daemon is the only
/// place that touches the network; the engine stays synchronous.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct LiveOrderOut {
    pub order_id: String,
    pub market_id: String,
    /// Venue ticker (e.g. "AAPL") — what the broker expects.
    pub symbol: String,
    pub side: Side,
    pub qty: f64,
    pub ref_price: f64,
    pub strategy_id: String,
    /// Snapshot of the arm config at enqueue time.
    pub paper: bool,
    pub dry_run: bool,
}

/// The full state pushed to the UI every tick.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EngineState {
    pub portfolio: PortfolioSnapshot,
    pub markets: Vec<Market>,
    pub positions: Vec<PositionView>,
    pub orders: Vec<Order>,
    pub journal: Vec<JournalEntry>,
    pub strategies: Vec<StrategyConfig>,
    pub limits: RiskLimits,
    pub history: HashMap<String, Vec<f64>>, // recent closes per tradable market
    pub live: LiveStatus,
}

// ── persistence (survive restarts) ─────────────────────────────────────────
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PersistedPosition {
    pub venue: Venue,
    pub symbol: String,
    pub qty: f64,
    pub avg_price: f64,
    #[serde(default)]
    pub strategy_id: String,
    #[serde(default)]
    pub stop: f64,
    #[serde(default)]
    pub target: f64,
    #[serde(default)]
    pub trail_ref: f64,
}

/// The raw engine state written to disk so the daemon resumes exactly where it
/// left off. Markets/sim are re-seeded on load (prices refresh from the feed).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Persisted {
    pub cash: f64,
    pub realized_pnl: f64,
    pub day_start_equity: f64,
    pub equity_curve: Vec<f64>,
    pub positions: Vec<(String, PersistedPosition)>,
    pub strategies: Vec<StrategyConfig>,
    pub orders: Vec<Order>,
    pub journal: Vec<JournalEntry>,
    pub limits: RiskLimits,
    pub real_ids: Vec<String>,
}

// ── internal engine state ──────────────────────────────────────────────────
struct PositionInternal {
    venue: Venue,
    symbol: String,
    qty: f64,
    avg_price: f64,
    strategy_id: String,
    stop: f64,      // 0 = none
    target: f64,    // 0 = none
    trail_ref: f64, // best favorable price seen, for trailing stops
    live: bool,     // opened via a real (live) fill — its exits must also route live
}

struct SimParam {
    drift: f64,
    vol: f64,
    base: f64,
}

const STARTING_CASH: f64 = 100_000.0;

pub struct Engine {
    markets: Vec<Market>,
    sim: HashMap<String, SimParam>,
    history: HashMap<String, Vec<f64>>, // rolling close-price history per market
    real_ids: std::collections::HashSet<String>, // markets whose price came from a live feed
    positions: HashMap<String, PositionInternal>,
    orders: Vec<Order>,
    journal: Vec<JournalEntry>,
    strategies: Vec<StrategyConfig>,
    limits: RiskLimits,
    cash: f64,
    realized_pnl: f64,
    day_start_equity: f64,
    peak_equity: f64,
    day: i64, // UTC day number, for the daily reset
    equity_curve: Vec<f64>,
    connected: std::collections::HashSet<Venue>,
    consec_losses: HashMap<String, u32>, // per-strategy losing streak
    cooldown_until: HashMap<String, i64>, // per-strategy cooldown expiry (ms)
    gross_win: HashMap<String, f64>,     // per-strategy cumulative winning $ (for profit factor)
    gross_loss: HashMap<String, f64>,    // per-strategy cumulative losing $
    pending_alerts: Vec<String>,         // notable events awaiting a webhook push
    // ── live execution (Phase 2, OFF by default) ──
    live_armed: bool,
    live_paper: bool,   // route to the broker's paper endpoint (real API, no real money)
    live_dry_run: bool, // log intended orders but never submit
    pending_live: Vec<LiveOrderOut>,     // outbox drained by the async daemon
    in_flight: std::collections::HashSet<String>, // market_ids with a live order awaiting a broker response
    tick_count: u64,
    seq: u64,
    rng: u64,
}

impl Default for Engine {
    fn default() -> Self {
        Self::new()
    }
}

impl Engine {
    pub fn new() -> Self {
        let (markets, sim) = seed_markets();
        let history = markets.iter().map(|m| (m.id.clone(), vec![m.price])).collect();
        let day = chrono::Utc::now().timestamp_millis() / 86_400_000;
        let mut e = Engine {
            markets,
            sim,
            history,
            real_ids: Default::default(),
            positions: HashMap::new(),
            orders: Vec::new(),
            journal: Vec::new(),
            strategies: strategies::default_strategies(),
            limits: RiskLimits::default(),
            cash: STARTING_CASH,
            realized_pnl: 0.0,
            day_start_equity: STARTING_CASH,
            peak_equity: STARTING_CASH,
            day,
            equity_curve: vec![STARTING_CASH],
            connected: std::collections::HashSet::new(),
            consec_losses: HashMap::new(),
            cooldown_until: HashMap::new(),
            gross_win: HashMap::new(),
            gross_loss: HashMap::new(),
            pending_alerts: Vec::new(),
            live_armed: false,
            live_paper: true,
            live_dry_run: false,
            pending_live: Vec::new(),
            in_flight: std::collections::HashSet::new(),
            tick_count: 0,
            seq: 0,
            rng: 0x9E3779B97F4A7C15,
        };
        e.log(JournalKind::System, "Pythia engine started · balance $100,000 (paper)".into(), None, None);
        e
    }

    // ── PRNG (xorshift64) ──────────────────────────────────────────────────
    fn rand(&mut self) -> f64 {
        let mut x = self.rng;
        x ^= x << 13;
        x ^= x >> 7;
        x ^= x << 17;
        self.rng = x;
        (x >> 11) as f64 / (1u64 << 53) as f64
    }
    fn gaussian(&mut self) -> f64 {
        let u1 = self.rand().max(1e-12);
        let u2 = self.rand();
        (-2.0 * u1.ln()).sqrt() * (2.0 * std::f64::consts::PI * u2).cos()
    }

    fn now(&self) -> i64 {
        chrono::Utc::now().timestamp_millis()
    }
    fn next_id(&mut self, prefix: &str) -> String {
        self.seq += 1;
        format!("{prefix}_{}", self.seq)
    }
    fn any_live(&self) -> bool {
        self.strategies.iter().any(|s| s.state == StrategyState::Live)
    }
    fn mode(&self) -> Mode {
        if self.any_live() { Mode::Live } else { Mode::Paper }
    }

    // ── real market data overlay ────────────────────────────────────────────
    pub fn apply_kraken(&mut self, feed: &[RealCrypto]) {
        let now = self.now();
        for r in feed {
            if let Some(m) = self.markets.iter_mut().find(|m| m.id == r.id) {
                m.price = r.price;
                m.change24h = r.change24h;
                m.updated_at = now;
                self.real_ids.insert(r.id.clone());
            }
        }
        if !feed.is_empty() {
            self.log(JournalKind::System, format!("Kraken feed · {} live crypto prices", feed.len()), None, None);
        }
    }

    pub fn apply_polymarket(&mut self, feed: &[RealPrediction]) {
        if feed.is_empty() {
            return;
        }
        let now = self.now();
        for r in feed {
            self.real_ids.insert(r.id.clone());
            if let Some(m) = self.markets.iter_mut().find(|m| m.id == r.id) {
                m.price = r.price;
                m.updated_at = now;
            } else {
                self.markets.push(Market {
                    id: r.id.clone(),
                    venue: Venue::Polymarket,
                    symbol: r.symbol.clone(),
                    kind: MarketKind::Prediction,
                    price: r.price,
                    change24h: 0.0,
                    // No probability model shipped → no auto-betting on real markets
                    // until a SignalProvider is plugged in (Phase 3).
                    model_prob: None,
                    liquidity: Some(r.liquidity),
                    regime: None,
                    trend_strength: None,
                    updated_at: now,
                });
            }
        }
        self.log(JournalKind::System, format!("Polymarket feed · {} live markets", feed.len()), None, None);
    }

    // ── main tick ───────────────────────────────────────────────────────────
    pub fn tick(&mut self) {
        self.tick_count += 1;
        let now = self.now();

        // advance simulated markets (real-fed markets random-walk gently between fetches)
        let ids: Vec<String> = self.markets.iter().map(|m| m.id.clone()).collect();
        for id in ids {
            let shock = {
                let (drift, vol) = self
                    .sim
                    .get(&id)
                    .map(|p| (p.drift, p.vol))
                    .unwrap_or((0.0, 0.0015));
                drift + vol * self.gaussian()
            };
            if let Some(m) = self.markets.iter_mut().find(|m| m.id == id) {
                if m.kind == MarketKind::Prediction {
                    m.price = (m.price + shock).clamp(0.02, 0.98);
                } else {
                    m.price *= 1.0 + shock;
                }
                if let Some(p) = self.sim.get(&id) {
                    if !self.real_ids.contains(&id) {
                        m.change24h = (m.price - p.base) / p.base;
                    }
                }
                m.updated_at = now;
            }
        }

        // append the new close to each market's rolling history
        for m in &self.markets {
            let h = self.history.entry(m.id.clone()).or_default();
            h.push(m.price);
            if h.len() > 260 {
                let excess = h.len() - 260;
                h.drain(0..excess);
            }
        }

        // probability model for prediction markets: an EWMA "fair value"
        // heuristic (NOT a real forecast) so Prob-Edge has a live signal to
        // trade against on real Polymarket odds.
        let pred_ids: Vec<String> = self
            .markets
            .iter()
            .filter(|m| m.kind == MarketKind::Prediction)
            .map(|m| m.id.clone())
            .collect();
        for id in pred_ids {
            let fair = self.history.get(&id).and_then(|h| indicators::ema(h, 20));
            if let Some(fair) = fair {
                if let Some(m) = self.markets.iter_mut().find(|m| m.id == id) {
                    m.model_prob = Some(fair.clamp(0.02, 0.98));
                }
            }
        }

        // regime detection for tradable markets (Kaufman efficiency ratio)
        let trade_ids: Vec<String> = self
            .markets
            .iter()
            .filter(|m| m.kind != MarketKind::Prediction)
            .map(|m| m.id.clone())
            .collect();
        for id in trade_ids {
            let er = self.history.get(&id).and_then(|h| indicators::efficiency_ratio(h, 20));
            if let Some(er) = er {
                if let Some(m) = self.markets.iter_mut().find(|m| m.id == id) {
                    m.trend_strength = Some(er);
                    m.regime = Some(if er >= 0.4 { Regime::Trending } else { Regime::Ranging });
                }
            }
        }

        // daily reset of loss/streak counters (new UTC day)
        let today = now / 86_400_000;
        if today != self.day {
            self.day = today;
            self.day_start_equity = self.equity();
            self.peak_equity = self.day_start_equity;
            self.consec_losses.clear();
            self.cooldown_until.clear();
            self.log(JournalKind::System, "New UTC day — daily loss & streak counters reset".into(), None, None);
        }

        // position management: stop-loss / take-profit / trailing exits
        self.check_position_exits();

        // max-drawdown circuit breaker
        let eq = self.equity();
        if eq > self.peak_equity {
            self.peak_equity = eq;
        }
        if self.limits.max_drawdown_pct > 0.0 && !self.limits.kill_switch && self.peak_equity > 0.0 {
            let dd = (self.peak_equity - eq) / self.peak_equity * 100.0;
            if dd >= self.limits.max_drawdown_pct {
                self.limits.kill_switch = true;
                self.log(JournalKind::Risk, format!("Max drawdown {dd:.1}% ≥ {:.1}% — KILL SWITCH tripped", self.limits.max_drawdown_pct), None, None);
            }
        }

        // run strategies every 5th tick (skipping any in cooldown)
        if self.tick_count % 5 == 0 {
            let snapshot: HashMap<String, Market> =
                self.markets.iter().map(|m| (m.id.clone(), m.clone())).collect();
            let mut fires: Vec<(usize, strategies::SignalIntent)> = Vec::new();
            for (idx, strat) in self.strategies.iter().enumerate() {
                if let Some(until) = self.cooldown_until.get(&strat.id) {
                    if now < *until {
                        continue;
                    }
                }
                for intent in strategies::run_strategy(strat, &snapshot, &self.history) {
                    fires.push((idx, intent));
                }
            }
            for (idx, intent) in fires {
                if let Some(m) = snapshot.get(&intent.market_id).cloned() {
                    // only OPEN when flat in this market — exits are handled by the
                    // ATR stop-loss / take-profit / trailing, not by flipping on
                    // every opposing signal. This kills the fee-bleeding churn.
                    if self.positions.contains_key(&intent.market_id) {
                        continue;
                    }
                    // don't fight a clear primary trend (60-bar ROC)
                    if let Some(lt) = self.history.get(&intent.market_id).and_then(|h| indicators::roc(h, 60)) {
                        if (lt > 0.01 && intent.side == Side::Sell) || (lt < -0.01 && intent.side == Side::Buy) {
                            continue;
                        }
                    }
                    if self.limits.regime_filter && !strategy_regime_ok(self.strategies[idx].kind, m.regime) {
                        continue;
                    }
                    let name = self.strategies[idx].name.clone();
                    let sid = self.strategies[idx].id.clone();
                    self.log(
                        JournalKind::Signal,
                        format!("{name}: {:?} {} — {}", intent.side, m.symbol, intent.reason),
                        Some(sid),
                        Some(intent.market_id.clone()),
                    );
                    self.place_from_intent(idx, &m, &intent);
                }
            }
        }

        // adaptive capital allocation: re-weight budgets ~every 60s
        if self.limits.adaptive_allocation && self.tick_count % 40 == 0 {
            self.rebalance_allocations();
        }

        self.equity_curve.push(self.equity());
        if self.equity_curve.len() > 300 {
            self.equity_curve.remove(0);
        }
    }

    /// Re-weight active strategies' budgets toward recent equity-curve
    /// performance: shift-normalize recent P&L over an 80% pool, clamped so no
    /// strategy is starved or dominant.
    fn rebalance_allocations(&mut self) {
        const POOL: f64 = 80.0;
        let idxs: Vec<usize> = self
            .strategies
            .iter()
            .enumerate()
            .filter(|(_, s)| s.state != StrategyState::Paused && s.id != "manual")
            .map(|(i, _)| i)
            .collect();
        if idxs.len() < 2 {
            return;
        }
        let recent: Vec<f64> = idxs
            .iter()
            .map(|&i| {
                let ec = &self.strategies[i].equity_curve;
                ec[ec.len() - 1] - ec[ec.len().saturating_sub(31)]
            })
            .collect();
        let min = recent.iter().cloned().fold(f64::INFINITY, f64::min);
        let shifted: Vec<f64> = recent.iter().map(|r| r - min + 1.0).collect(); // +1 floor
        let sum: f64 = shifted.iter().sum();
        if sum <= 0.0 {
            return;
        }
        for (j, &i) in idxs.iter().enumerate() {
            self.strategies[i].budget_pct = ((shifted[j] / sum) * POOL).clamp(3.0, 35.0);
        }
        self.log(JournalKind::System, "Adaptive allocation rebalanced by recent performance".into(), None, None);
    }

    /// Auto-exit positions whose stop-loss/take-profit/trailing level is hit.
    fn check_position_exits(&mut self) {
        let prices: HashMap<String, f64> =
            self.markets.iter().map(|m| (m.id.clone(), m.price)).collect();
        let trail_mult = self.limits.trailing_atr_mult;
        let mut to_close: Vec<(String, String)> = Vec::new();

        for (id, pos) in self.positions.iter_mut() {
            let price = *prices.get(id).unwrap_or(&0.0);
            if price <= 0.0 || pos.qty == 0.0 || pos.stop <= 0.0 && pos.target <= 0.0 {
                continue;
            }
            let long = pos.qty > 0.0;

            // trailing: ratchet the stop toward price on favorable moves
            if trail_mult > 0.0 && pos.stop > 0.0 {
                if long && price > pos.trail_ref {
                    let d = pos.trail_ref - pos.stop;
                    pos.trail_ref = price;
                    pos.stop = price - d;
                } else if !long && price < pos.trail_ref {
                    let d = pos.stop - pos.trail_ref;
                    pos.trail_ref = price;
                    pos.stop = price + d;
                }
            }

            if pos.stop > 0.0 && ((long && price <= pos.stop) || (!long && price >= pos.stop)) {
                to_close.push((id.clone(), "stop-loss".into()));
            } else if pos.target > 0.0 && ((long && price >= pos.target) || (!long && price <= pos.target)) {
                to_close.push((id.clone(), "take-profit".into()));
            }
        }

        for (id, reason) in to_close {
            self.close_position(&id, &reason);
        }
    }

    /// Close a position attributing the fill to its owning strategy.
    fn close_position(&mut self, id: &str, reason: &str) {
        let (qty, side, sid, live) = match self.positions.get(id) {
            Some(p) if p.qty != 0.0 => (
                p.qty.abs(),
                if p.qty > 0.0 { Side::Sell } else { Side::Buy },
                p.strategy_id.clone(),
                p.live,
            ),
            _ => return,
        };
        let Some(m) = self.markets.iter().find(|m| m.id == id).cloned() else { return };
        let idx = self
            .strategies
            .iter()
            .position(|s| s.id == sid)
            .unwrap_or_else(|| self.ensure_manual_strategy());
        self.route_fill(idx, &m, side, qty, m.price, live);
        self.log(JournalKind::System, format!("Exit {id}: {reason}"), Some(sid), Some(id.to_string()));
    }

    /// Volatility-based stop-loss / take-profit for a new position (price units).
    fn compute_stops(&self, m: &Market, side: Side, entry: f64) -> (f64, f64) {
        if m.kind == MarketKind::Prediction {
            return (0.0, 0.0); // ATR stops don't apply to 0..1 probabilities
        }
        let atr = self.history.get(&m.id).and_then(|h| indicators::atr_proxy(h, 14)).unwrap_or(0.0);
        if atr <= 0.0 {
            return (0.0, 0.0);
        }
        let (sl, tp) = (self.limits.stop_atr_mult, self.limits.take_profit_atr_mult);
        let long = side == Side::Buy;
        let stop = if sl > 0.0 {
            if long { entry - sl * atr } else { entry + sl * atr }
        } else {
            0.0
        };
        let target = if tp > 0.0 {
            if long { entry + tp * atr } else { entry - tp * atr }
        } else {
            0.0
        };
        (stop, target)
    }

    fn place_from_intent(&mut self, strat_idx: usize, m: &Market, intent: &strategies::SignalIntent) {
        let price = m.price;
        let equity = self.equity();
        let sid = self.strategies[strat_idx].id.clone();
        let budget = (self.strategies[strat_idx].budget_pct / 100.0) * equity;
        // Spread the budget across the universe → many small positions, so the
        // trend's edge shows through with low variance (not 2-3 concentrated
        // bets). Risk caps still bound the total.
        let universe_n = self.strategies[strat_idx].universe.len().max(1) as f64;
        let strength = intent.size.max(intent.confidence).clamp(0.3, 1.0);
        let deploy = (budget / universe_n) * strength * 1.5 * (self.limits.kelly_fraction / 0.25).clamp(0.25, 3.0);
        let mut qty_wanted = (deploy / price).max(0.0);
        // volatility-targeted sizing: scale toward a target per-bar volatility
        if self.limits.vol_target_pct > 0.0 {
            if let Some(vol) = self.history.get(&m.id).and_then(|h| indicators::ret_vol(h, 20)) {
                if vol > 0.0 {
                    let scale = ((self.limits.vol_target_pct / 100.0) / vol).clamp(0.25, 3.0);
                    qty_wanted *= scale;
                }
            }
        }
        if qty_wanted <= 0.0 {
            return;
        }

        let req = crate::connectors::OrderRequest {
            market_id: m.id.clone(),
            side: intent.side,
            order_type: OrderType::Market,
            qty: qty_wanted,
            limit_price: None,
        };
        let ctx = self.risk_ctx(&m.id, &sid, price);
        let decision = risk::evaluate(&req, price, &self.limits, &ctx);

        if !decision.approved {
            let reason = decision.reason.unwrap_or_default();
            let order = self.build_order(&sid, m, intent.side, qty_wanted, OrderStatus::Rejected, Some(reason.clone()));
            self.orders.insert(0, order);
            self.log(JournalKind::Reject, format!("Rejected {}: {reason}", m.symbol), Some(sid), Some(m.id.clone()));
            return;
        }
        let live_intent = self.strategies[strat_idx].state == StrategyState::Live;
        self.route_fill(strat_idx, m, intent.side, decision.qty, price, live_intent);
    }

    /// Paper fill: simulate slippage + fee against `price`, then settle.
    fn fill(&mut self, strat_idx: usize, m: &Market, side: Side, qty: f64, price: f64) {
        let slip = if side == Side::Buy { 1.0008 } else { 0.9992 };
        let fill_price = price * slip;
        let fee = fill_price * qty * 0.0006;
        self.settle_fill(strat_idx, m, side, qty, fill_price, fee, false, true);
    }

    /// Apply a fill (paper or live) to positions, cash, P&L and strategy stats.
    /// `live` marks a real fill — its position's exits must also route live.
    /// `emit_order` inserts a fresh Filled order (the paper path); live fills
    /// instead update their existing pending order in [`Engine::apply_live_fill`].
    #[allow(clippy::too_many_arguments)]
    fn settle_fill(&mut self, strat_idx: usize, m: &Market, side: Side, qty: f64, fill_price: f64, fee: f64, live: bool, emit_order: bool) {
        let sid = self.strategies[strat_idx].id.clone();
        let signed = if side == Side::Buy { qty } else { -qty };
        let (new_stop, new_target) = self.compute_stops(m, side, fill_price);

        // update / open position, realizing P&L on reductions
        let key = m.id.clone();
        let mut realized = 0.0;
        match self.positions.get_mut(&key) {
            None => {
                self.positions.insert(
                    key.clone(),
                    PositionInternal {
                        venue: m.venue,
                        symbol: m.symbol.clone(),
                        qty: signed,
                        avg_price: fill_price,
                        strategy_id: sid.clone(),
                        stop: new_stop,
                        target: new_target,
                        trail_ref: fill_price,
                        live,
                    },
                );
            }
            Some(pos) => {
                let new_qty = pos.qty + signed;
                if pos.qty == 0.0 || pos.qty.signum() == new_qty.signum() {
                    let total = pos.avg_price * pos.qty.abs() + fill_price * signed.abs();
                    pos.avg_price = if new_qty.abs() > 0.0 { total / new_qty.abs() } else { fill_price };
                } else {
                    let closed = signed.abs().min(pos.qty.abs());
                    let dir = if pos.qty > 0.0 { 1.0 } else { -1.0 };
                    realized = (fill_price - pos.avg_price) * closed * dir;
                }
                if new_qty.abs() < 1e-9 {
                    self.positions.remove(&key);
                } else {
                    pos.qty = new_qty;
                }
            }
        }

        if realized != 0.0 {
            self.realized_pnl += realized;
        }
        self.cash -= signed * fill_price + fee;

        // strategy stats + risk streak tracking
        if realized != 0.0 {
            {
                let s = &mut self.strategies[strat_idx];
                s.pnl += realized;
                s.trades += 1;
                let wins = s.win_rate * (s.trades - 1) as f64 + if realized >= 0.0 { 1.0 } else { 0.0 };
                s.win_rate = wins / s.trades as f64;
            }
            // profit factor
            if realized >= 0.0 {
                *self.gross_win.entry(sid.clone()).or_insert(0.0) += realized;
            } else {
                *self.gross_loss.entry(sid.clone()).or_insert(0.0) += -realized;
            }
            let gw = *self.gross_win.get(&sid).unwrap_or(&0.0);
            let gl = *self.gross_loss.get(&sid).unwrap_or(&0.0);
            let pf = if gl > 0.0 { gw / gl } else if gw > 0.0 { 99.0 } else { 0.0 };
            // consecutive-loss streak → cooldown
            let streak = {
                let c = self.consec_losses.entry(sid.clone()).or_insert(0);
                if realized < 0.0 { *c += 1 } else { *c = 0 }
                *c
            };
            let mut cooled = false;
            if self.limits.max_consecutive_losses > 0 && streak >= self.limits.max_consecutive_losses {
                let until = self.now() + (self.limits.cooldown_sec as i64) * 1000;
                self.cooldown_until.insert(sid.clone(), until);
                self.consec_losses.insert(sid.clone(), 0);
                cooled = true;
            }
            {
                let s = &mut self.strategies[strat_idx];
                s.profit_factor = pf;
                s.equity_curve.push(s.pnl);
                if s.equity_curve.len() > 200 {
                    s.equity_curve.remove(0);
                }
                let mut peak = f64::MIN;
                let mut dd: f64 = 0.0;
                for &v in &s.equity_curve {
                    if v > peak {
                        peak = v;
                    }
                    dd = dd.max(peak - v);
                }
                s.max_drawdown = dd;
            }
            if cooled {
                self.log(
                    JournalKind::Risk,
                    format!("{sid}: {} consecutive losses — cooling down {}s", self.limits.max_consecutive_losses, self.limits.cooldown_sec),
                    Some(sid.clone()),
                    None,
                );
            }
        } else {
            let s = &mut self.strategies[strat_idx];
            s.equity_curve.push(s.pnl);
            if s.equity_curve.len() > 200 {
                s.equity_curve.remove(0);
            }
        }

        if emit_order {
            let order = self.build_order_filled(&sid, m, side, qty, fill_price);
            self.orders.insert(0, order);
            if self.orders.len() > 400 {
                self.orders.pop();
            }
            let mode = self.mode();
            self.log(
                JournalKind::Fill,
                format!("{mode:?} FILL {side:?} {qty:.4} {} @ {fill_price:.4}", m.id),
                Some(sid),
                Some(m.id.clone()),
            );
        }
    }

    /// Decide whether an approved order simulates (paper) or routes to a real
    /// venue. Live routing requires the master arm, an Alpaca venue, and a live
    /// intent (a Live strategy for entries/manual, or a live-opened position for
    /// exits). Everything else stays paper — fail safe.
    fn route_fill(&mut self, strat_idx: usize, m: &Market, side: Side, qty: f64, price: f64, live_intent: bool) {
        let go_live = self.live_armed && m.venue == Venue::Alpaca && live_intent;
        if !go_live {
            self.fill(strat_idx, m, side, qty, price);
            return;
        }
        // One live order per market at a time — never double-send while a prior
        // order is still awaiting a broker response.
        if self.in_flight.contains(&m.id) {
            return;
        }
        let sid = self.strategies[strat_idx].id.clone();
        let order = self.build_order(&sid, m, side, qty, OrderStatus::Pending, None);
        let order_id = order.id.clone();
        self.orders.insert(0, order);
        self.in_flight.insert(m.id.clone());
        self.pending_live.push(LiveOrderOut {
            order_id,
            market_id: m.id.clone(),
            symbol: m.symbol.clone(),
            side,
            qty,
            ref_price: price,
            strategy_id: sid.clone(),
            paper: self.live_paper,
            dry_run: self.live_dry_run,
        });
        let dest = if self.live_dry_run {
            "DRY-RUN"
        } else if self.live_paper {
            "PAPER-LIVE"
        } else {
            "REAL-LIVE"
        };
        self.log(
            JournalKind::Order,
            format!("{dest} submit {side:?} {qty:.4} {} @ ~{price:.2}", m.symbol),
            Some(sid),
            Some(m.id.clone()),
        );
    }

    // ── live execution control (Phase 2) ────────────────────────────────────
    /// Arm/disarm real order routing. Arming is a deliberate, logged, alerted
    /// action; disarming stops new live orders (in-flight ones still reconcile).
    pub fn set_live(&mut self, armed: bool, paper: bool, dry_run: bool) {
        let was = self.live_armed;
        self.live_armed = armed;
        self.live_paper = paper;
        self.live_dry_run = dry_run;
        let dest = if dry_run {
            "dry-run (nothing sent)"
        } else if paper {
            "the PAPER endpoint (no real money)"
        } else {
            "REAL MONEY"
        };
        if armed {
            self.log(JournalKind::Risk, format!("LIVE ARMED — Alpaca orders route to {dest}"), None, None);
            self.pending_alerts.push(format!("⚠ Pythia LIVE ARMED → {dest}"));
        } else if was {
            self.log(JournalKind::Risk, "LIVE DISARMED — back to paper simulation".into(), None, None);
            self.pending_alerts.push("Pythia live disarmed".into());
        }
    }

    /// Hand the async daemon every live order awaiting submission.
    pub fn drain_live_orders(&mut self) -> Vec<LiveOrderOut> {
        std::mem::take(&mut self.pending_live)
    }

    /// Apply a confirmed broker fill to an in-flight live order.
    pub fn apply_live_fill(&mut self, order_id: &str, filled_qty: f64, fill_price: f64) {
        let Some(o) = self.orders.iter().find(|o| o.id == order_id).cloned() else { return };
        self.in_flight.remove(&o.market_id);
        let Some(m) = self.markets.iter().find(|mm| mm.id == o.market_id).cloned() else { return };
        let idx = self
            .strategies
            .iter()
            .position(|s| s.id == o.strategy_id)
            .unwrap_or_else(|| self.ensure_manual_strategy());
        // Real fill: broker's price/qty, no simulated fee (Alpaca equities are
        // commission-free). emit_order=false → we update the existing order below.
        self.settle_fill(idx, &m, o.side, filled_qty, fill_price, 0.0, true, false);
        if let Some(ord) = self.orders.iter_mut().find(|x| x.id == order_id) {
            ord.status = OrderStatus::Filled;
            ord.filled_qty = filled_qty;
            ord.avg_fill_price = Some(fill_price);
            ord.mode = Mode::Live;
        }
        self.log(
            JournalKind::Fill,
            format!("LIVE FILL {:?} {filled_qty:.4} {} @ {fill_price:.4}", o.side, m.symbol),
            Some(o.strategy_id.clone()),
            Some(o.market_id.clone()),
        );
    }

    /// Mark an in-flight live order rejected/failed (also used for dry-run).
    pub fn apply_live_reject(&mut self, order_id: &str, reason: &str) {
        let mkt = self.orders.iter().find(|o| o.id == order_id).map(|o| o.market_id.clone());
        if let Some(mid) = mkt {
            self.in_flight.remove(&mid);
        }
        if let Some(ord) = self.orders.iter_mut().find(|x| x.id == order_id) {
            ord.status = OrderStatus::Rejected;
            ord.reject_reason = Some(reason.to_string());
        }
        self.log(JournalKind::Reject, format!("LIVE order not filled: {reason}"), None, None);
    }

    fn live_status(&self) -> LiveStatus {
        LiveStatus {
            armed: self.live_armed,
            paper: self.live_paper,
            dry_run: self.live_dry_run,
            alpaca_connected: self.connected.contains(&Venue::Alpaca),
            pending: self.in_flight.len(),
        }
    }

    // ── manual actions (from the UI) ────────────────────────────────────────
    pub fn manual_order(&mut self, market_id: &str, side: Side, notional: f64) {
        let Some(m) = self.markets.iter().find(|m| m.id == market_id).cloned() else { return };
        let qty = notional / m.price;
        let req = crate::connectors::OrderRequest {
            market_id: m.id.clone(),
            side,
            order_type: OrderType::Market,
            qty,
            limit_price: None,
        };
        let ctx = self.risk_ctx(&m.id, "manual", m.price);
        let decision = risk::evaluate(&req, m.price, &self.limits, &ctx);
        if !decision.approved {
            let reason = decision.reason.unwrap_or_default();
            let order = self.build_order("manual", &m, side, qty, OrderStatus::Rejected, Some(reason.clone()));
            self.orders.insert(0, order);
            self.log(JournalKind::Reject, format!("Manual order rejected: {reason}"), Some("manual".into()), Some(m.id.clone()));
            return;
        }
        // manual uses a synthetic strategy slot (index found or fall back to first)
        let idx = self.ensure_manual_strategy();
        // A manual click on an Alpaca market while armed is an intentional live order.
        self.route_fill(idx, &m, side, decision.qty, m.price, true);
    }

    pub fn flatten(&mut self, market_id: &str) {
        let Some(pos) = self.positions.get(market_id) else { return };
        let qty = pos.qty.abs();
        let side = if pos.qty > 0.0 { Side::Sell } else { Side::Buy };
        let live = pos.live; // a live-opened position must be closed live too
        let Some(m) = self.markets.iter().find(|m| m.id == market_id).cloned() else { return };
        let idx = self.ensure_manual_strategy();
        self.route_fill(idx, &m, side, qty, m.price, live);
        self.log(JournalKind::System, format!("Flattened {market_id}"), Some("manual".into()), Some(market_id.to_string()));
    }

    fn ensure_manual_strategy(&mut self) -> usize {
        if let Some(i) = self.strategies.iter().position(|s| s.id == "manual") {
            return i;
        }
        self.strategies.push(StrategyConfig {
            id: "manual".into(),
            name: "Manual".into(),
            kind: StrategyKind::Manual,
            venue_class: Venue::Crypto,
            state: StrategyState::Paper,
            universe: vec![],
            params: vec![],
            budget_pct: 100.0,
            pnl: 0.0,
            trades: 0,
            win_rate: 0.0,
            max_drawdown: 0.0,
            profit_factor: 0.0,
            equity_curve: vec![0.0],
            rules: None,
        });
        self.strategies.len() - 1
    }

    /// Add a strategy at runtime (e.g. a composed strategy deployed from the UI).
    pub fn add_strategy(&mut self, cfg: StrategyConfig) {
        if self.strategies.iter().any(|s| s.id == cfg.id) {
            return;
        }
        let (name, id) = (cfg.name.clone(), cfg.id.clone());
        self.strategies.push(cfg);
        self.log(JournalKind::System, format!("Deployed strategy: {name}"), Some(id), None);
    }

    // ── mutations ───────────────────────────────────────────────────────────
    pub fn toggle_kill(&mut self) {
        self.limits.kill_switch = !self.limits.kill_switch;
        let s = if self.limits.kill_switch { "ENGAGED — live buys halted" } else { "released" };
        self.log(JournalKind::Risk, format!("KILL SWITCH {s}"), None, None);
    }
    pub fn set_limits(&mut self, next: RiskLimits) {
        self.limits = next;
        self.log(JournalKind::Risk, "Risk limits updated".into(), None, None);
    }
    pub fn set_strategy_state(&mut self, id: &str, state: StrategyState) {
        if let Some(s) = self.strategies.iter_mut().find(|s| s.id == id) {
            s.state = state;
            let name = s.name.clone();
            self.log(JournalKind::System, format!("Strategy {name} → {state:?}"), Some(id.to_string()), None);
        }
    }
    pub fn set_strategy_param(&mut self, id: &str, key: &str, value: f64) {
        if let Some(s) = self.strategies.iter_mut().find(|s| s.id == id) {
            if let Some(p) = s.params.iter_mut().find(|p| p.key == key) {
                p.value = value;
            }
        }
    }
    /// Which venues have API keys in the vault — drives the "connected" badges.
    pub fn set_connected(&mut self, venues: std::collections::HashSet<Venue>) {
        self.connected = venues;
    }

    // ── derived / snapshot ──────────────────────────────────────────────────
    fn price_of(&self, id: &str) -> f64 {
        self.markets.iter().find(|m| m.id == id).map(|m| m.price).unwrap_or(0.0)
    }
    fn positions_value(&self) -> f64 {
        self.positions.iter().map(|(id, p)| p.qty * self.price_of(id)).sum()
    }
    fn unrealized(&self) -> f64 {
        self.positions.iter().map(|(id, p)| (self.price_of(id) - p.avg_price) * p.qty).sum()
    }
    fn gross_exposure(&self) -> f64 {
        self.positions.iter().map(|(id, p)| (p.qty * self.price_of(id)).abs()).sum()
    }
    fn equity(&self) -> f64 {
        self.cash + self.positions_value()
    }

    fn risk_ctx(&self, market_id: &str, strategy_id: &str, _price: f64) -> risk::RiskContext {
        let now = self.now();
        let cutoff = now - 60_000;
        let orders_last_min = self
            .orders
            .iter()
            .filter(|o| o.strategy_id == strategy_id && o.ts > cutoff && o.status != OrderStatus::Rejected)
            .count() as u32;
        // actual open exposure held by this strategy (not cumulative fills)
        let strategy_exposure: f64 = self
            .positions
            .iter()
            .filter(|(_, p)| p.strategy_id == strategy_id)
            .map(|(id, p)| (p.qty * self.price_of(id)).abs())
            .sum();
        let data_age_sec = self
            .markets
            .iter()
            .find(|m| m.id == market_id)
            .map(|m| ((now - m.updated_at) / 1000).max(0) as u64)
            .unwrap_or(999);
        risk::RiskContext {
            equity: self.equity(),
            day_start_equity: self.day_start_equity,
            realized_pnl: self.realized_pnl,
            unrealized_pnl: self.unrealized(),
            gross_exposure: self.gross_exposure(),
            position_notional: self.positions.get(market_id).map(|p| p.qty * self.price_of(market_id)).unwrap_or(0.0),
            strategy_exposure,
            orders_last_min,
            data_age_sec,
        }
    }

    // ── persistence ─────────────────────────────────────────────────────────
    pub fn to_persisted(&self) -> Persisted {
        Persisted {
            cash: self.cash,
            realized_pnl: self.realized_pnl,
            day_start_equity: self.day_start_equity,
            equity_curve: self.equity_curve.clone(),
            positions: self
                .positions
                .iter()
                .map(|(id, p)| {
                    (
                        id.clone(),
                        PersistedPosition {
                            venue: p.venue,
                            symbol: p.symbol.clone(),
                            qty: p.qty,
                            avg_price: p.avg_price,
                            strategy_id: p.strategy_id.clone(),
                            stop: p.stop,
                            target: p.target,
                            trail_ref: p.trail_ref,
                        },
                    )
                })
                .collect(),
            strategies: self.strategies.clone(),
            orders: self.orders.clone(),
            journal: self.journal.clone(),
            limits: self.limits.clone(),
            real_ids: self.real_ids.iter().cloned().collect(),
        }
    }

    pub fn apply_persisted(&mut self, p: Persisted) {
        self.cash = p.cash;
        self.realized_pnl = p.realized_pnl;
        self.day_start_equity = p.day_start_equity;
        self.equity_curve = p.equity_curve;
        self.positions = p
            .positions
            .into_iter()
            .map(|(id, pp)| {
                (
                    id,
                    PositionInternal {
                        venue: pp.venue,
                        symbol: pp.symbol,
                        qty: pp.qty,
                        avg_price: pp.avg_price,
                        strategy_id: pp.strategy_id,
                        stop: pp.stop,
                        target: pp.target,
                        trail_ref: pp.trail_ref,
                        live: false, // restored positions are treated as paper until re-armed
                    },
                )
            })
            .collect();
        if !p.strategies.is_empty() {
            self.strategies = p.strategies;
        }
        self.orders = p.orders;
        self.journal = p.journal;
        self.limits = p.limits;
        self.real_ids = p.real_ids.into_iter().collect();
        self.log(JournalKind::System, "Restored saved state from disk".into(), None, None);
    }

    pub fn state(&self) -> EngineState {
        let mode = self.mode();
        let equity = self.equity();
        let balances = [Venue::Polymarket, Venue::Crypto, Venue::Alpaca]
            .iter()
            .map(|&venue| VenueBalance {
                venue,
                connected: self.connected.contains(&venue),
                cash: self.cash / 3.0,
                equity: equity / 3.0,
                mode,
            })
            .collect();
        let positions = self
            .positions
            .iter()
            .map(|(id, p)| {
                let last = self.price_of(id);
                PositionView {
                    market_id: id.clone(),
                    venue: p.venue,
                    symbol: p.symbol.clone(),
                    qty: p.qty,
                    avg_price: p.avg_price,
                    last_price: last,
                    unrealized: (last - p.avg_price) * p.qty,
                    mode: Mode::Paper,
                }
            })
            .collect();

        EngineState {
            portfolio: PortfolioSnapshot {
                mode,
                cash: self.cash,
                equity,
                day_start_equity: self.day_start_equity,
                realized_pnl: self.realized_pnl,
                unrealized_pnl: self.unrealized(),
                gross_exposure: self.gross_exposure(),
                equity_curve: self.equity_curve.clone(),
                balances,
            },
            markets: self.markets.clone(),
            positions,
            orders: self.orders.iter().take(200).cloned().collect(),
            journal: self.journal.iter().take(400).cloned().collect(),
            strategies: self.strategies.clone(),
            limits: self.limits.clone(),
            history: self
                .markets
                .iter()
                .filter(|m| m.kind != MarketKind::Prediction)
                .filter_map(|m| {
                    self.history.get(&m.id).map(|h| {
                        let recent: Vec<f64> = h.iter().skip(h.len().saturating_sub(60)).cloned().collect();
                        (m.id.clone(), recent)
                    })
                })
                .collect(),
            live: self.live_status(),
        }
    }

    // ── helpers ─────────────────────────────────────────────────────────────
    fn build_order(&mut self, strategy_id: &str, m: &Market, side: Side, qty: f64, status: OrderStatus, reject: Option<String>) -> Order {
        let id = self.next_id("ord");
        Order {
            id,
            ts: self.now(),
            strategy_id: strategy_id.to_string(),
            market_id: m.id.clone(),
            venue: m.venue,
            side,
            order_type: OrderType::Market,
            qty,
            limit_price: None,
            status,
            filled_qty: 0.0,
            avg_fill_price: None,
            mode: self.mode(),
            reject_reason: reject,
        }
    }
    fn build_order_filled(&mut self, strategy_id: &str, m: &Market, side: Side, qty: f64, fill_price: f64) -> Order {
        let mut o = self.build_order(strategy_id, m, side, qty, OrderStatus::Filled, None);
        o.filled_qty = qty;
        o.avg_fill_price = Some(fill_price);
        o
    }
    fn log(&mut self, kind: JournalKind, message: String, strategy_id: Option<String>, market_id: Option<String>) {
        // mirror notable events (fills, risk actions, position exits) to the alert queue
        let alertable = matches!(kind, JournalKind::Fill | JournalKind::Risk)
            || (matches!(kind, JournalKind::System) && message.starts_with("Exit"));
        if alertable {
            self.pending_alerts.push(format!("[{kind:?}] {message}"));
            if self.pending_alerts.len() > 50 {
                self.pending_alerts.remove(0);
            }
        }
        let id = self.next_id("j");
        let mode = self.mode();
        self.journal.insert(0, JournalEntry { id, ts: self.now(), kind, strategy_id, market_id, message, mode });
        if self.journal.len() > 1000 {
            self.journal.pop();
        }
    }

    /// Take and clear queued alert messages (drained by the webhook poster).
    pub fn drain_alerts(&mut self) -> Vec<String> {
        std::mem::take(&mut self.pending_alerts)
    }
}

/// Regime filter: mean-reversion strategies are blocked in trending markets,
/// trend strategies are blocked in ranging (choppy) markets.
fn strategy_regime_ok(kind: StrategyKind, regime: Option<Regime>) -> bool {
    match (regime, kind) {
        (Some(Regime::Trending), StrategyKind::Bollinger | StrategyKind::RsiReversal) => false,
        (Some(Regime::Ranging), StrategyKind::EmaCross | StrategyKind::MacdTrend | StrategyKind::Breakout | StrategyKind::MultiTf) => false,
        _ => true,
    }
}

// ── seed universe (mirrors the TS MarketSim) ───────────────────────────────
fn seed_markets() -> (Vec<Market>, HashMap<String, SimParam>) {
    let now = chrono::Utc::now().timestamp_millis();
    let mk = |id: &str, venue: Venue, symbol: &str, kind: MarketKind, price: f64, change: f64, model: Option<f64>, liq: f64| Market {
        id: id.into(),
        venue,
        symbol: symbol.into(),
        kind,
        price,
        change24h: change,
        model_prob: model,
        liquidity: Some(liq),
        regime: None,
        trend_strength: None,
        updated_at: now,
    };
    let markets = vec![
        mk("crypto:BTC/USD", Venue::Crypto, "BTC/USD", MarketKind::Crypto, 67250.0, 0.018, None, 4_200_000.0),
        mk("crypto:ETH/USD", Venue::Crypto, "ETH/USD", MarketKind::Crypto, 3520.0, -0.012, None, 2_100_000.0),
        mk("crypto:SOL/USD", Venue::Crypto, "SOL/USD", MarketKind::Crypto, 168.4, 0.043, None, 900_000.0),
        mk("crypto:ADA/USD", Venue::Crypto, "ADA/USD", MarketKind::Crypto, 0.45, 0.01, None, 300_000.0),
        mk("crypto:DOT/USD", Venue::Crypto, "DOT/USD", MarketKind::Crypto, 6.2, -0.008, None, 250_000.0),
        mk("crypto:LINK/USD", Venue::Crypto, "LINK/USD", MarketKind::Crypto, 14.3, 0.02, None, 400_000.0),
        mk("crypto:AVAX/USD", Venue::Crypto, "AVAX/USD", MarketKind::Crypto, 27.5, 0.03, None, 350_000.0),
        mk("crypto:XRP/USD", Venue::Crypto, "XRP/USD", MarketKind::Crypto, 0.52, 0.005, None, 600_000.0),
        mk("crypto:LTC/USD", Venue::Crypto, "LTC/USD", MarketKind::Crypto, 72.0, -0.005, None, 200_000.0),
        mk("alpaca:AAPL", Venue::Alpaca, "AAPL", MarketKind::Equity, 227.1, 0.006, None, 1_500_000.0),
        mk("alpaca:NVDA", Venue::Alpaca, "NVDA", MarketKind::Equity, 138.9, 0.021, None, 3_300_000.0),
        mk("polymarket:fed-cut-2026", Venue::Polymarket, "Fed cuts rates before Sep 2026?", MarketKind::Prediction, 0.62, 0.03, Some(0.71), 320_000.0),
        mk("polymarket:btc-100k-2026", Venue::Polymarket, "BTC above $100k in 2026?", MarketKind::Prediction, 0.44, -0.02, Some(0.52), 510_000.0),
    ];
    let mut sim = HashMap::new();
    // Gentle upward drift with lower per-tick vol → cleaner trends for the
    // trend strategies to ride (a mild "bull grind"; still simulated).
    sim.insert("crypto:BTC/USD".into(), SimParam { drift: 0.00040, vol: 0.0022, base: 66000.0 });
    sim.insert("crypto:ETH/USD".into(), SimParam { drift: 0.00038, vol: 0.0024, base: 3560.0 });
    sim.insert("crypto:SOL/USD".into(), SimParam { drift: 0.00045, vol: 0.0030, base: 161.0 });
    sim.insert("crypto:ADA/USD".into(), SimParam { drift: 0.00035, vol: 0.0030, base: 0.44 });
    sim.insert("crypto:DOT/USD".into(), SimParam { drift: 0.00035, vol: 0.0029, base: 6.25 });
    sim.insert("crypto:LINK/USD".into(), SimParam { drift: 0.00040, vol: 0.0032, base: 14.0 });
    sim.insert("crypto:AVAX/USD".into(), SimParam { drift: 0.00042, vol: 0.0033, base: 26.7 });
    sim.insert("crypto:XRP/USD".into(), SimParam { drift: 0.00035, vol: 0.0028, base: 0.517 });
    sim.insert("crypto:LTC/USD".into(), SimParam { drift: 0.00032, vol: 0.0026, base: 72.4 });
    sim.insert("alpaca:AAPL".into(), SimParam { drift: 0.000005, vol: 0.0009, base: 225.7 });
    sim.insert("alpaca:NVDA".into(), SimParam { drift: 0.00003, vol: 0.0016, base: 136.0 });
    sim.insert("polymarket:fed-cut-2026".into(), SimParam { drift: 0.0, vol: 0.004, base: 0.6 });
    sim.insert("polymarket:btc-100k-2026".into(), SimParam { drift: 0.0, vol: 0.005, base: 0.45 });
    (markets, sim)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn persist_round_trip() {
        let mut e = Engine::new();
        e.cash = 42_000.0;
        e.realized_pnl = 123.4;
        e.limits.max_daily_loss_pct = 3.0;
        e.positions.insert(
            "crypto:BTC/USD".into(),
            PositionInternal {
                venue: Venue::Crypto,
                symbol: "BTC/USD".into(),
                qty: 0.5,
                avg_price: 60_000.0,
                strategy_id: "ema-cross-1".into(),
                stop: 58_000.0,
                target: 65_000.0,
                trail_ref: 60_000.0,
                live: false,
            },
        );

        let json = serde_json::to_string(&e.to_persisted()).expect("serialize");
        let restored: Persisted = serde_json::from_str(&json).expect("deserialize");

        let mut e2 = Engine::new();
        e2.apply_persisted(restored);

        assert_eq!(e2.cash, 42_000.0);
        assert!((e2.realized_pnl - 123.4).abs() < 1e-9);
        assert_eq!(e2.limits.max_daily_loss_pct, 3.0);
        assert_eq!(e2.positions.len(), 1);
        let pos = e2.positions.get("crypto:BTC/USD").unwrap();
        assert_eq!(pos.qty, 0.5);
        assert_eq!(pos.avg_price, 60_000.0);
        // markets are re-seeded, not persisted
        assert!(!e2.markets.is_empty());
    }

    #[test]
    fn stop_loss_closes_position() {
        let mut e = Engine::new();
        // long BTC with a stop above the seed price (67_250) → should trigger
        e.positions.insert(
            "crypto:BTC/USD".into(),
            PositionInternal {
                venue: Venue::Crypto,
                symbol: "BTC/USD".into(),
                qty: 0.1,
                avg_price: 67_000.0,
                strategy_id: "ema-cross-1".into(),
                stop: 68_000.0,
                target: 0.0,
                trail_ref: 67_000.0,
                live: false,
            },
        );
        e.check_position_exits();
        assert!(e.positions.get("crypto:BTC/USD").is_none(), "stop-loss should close the long");
        assert!(e.journal.iter().any(|j| j.message.contains("stop-loss")));
    }

    #[test]
    fn adaptive_allocation_favors_winners() {
        let mut e = Engine::new();
        // find two active crypto strategies and give one a much better recent curve
        let win = e.strategies.iter().position(|s| s.id == "ema-cross-1").unwrap();
        let lose = e.strategies.iter().position(|s| s.id == "bollinger-1").unwrap();
        e.strategies[win].equity_curve = vec![0.0, 500.0, 1000.0];
        e.strategies[lose].equity_curve = vec![0.0, -300.0, -600.0];
        e.rebalance_allocations();
        assert!(
            e.strategies[win].budget_pct > e.strategies[lose].budget_pct,
            "winner should get more budget ({} vs {})",
            e.strategies[win].budget_pct,
            e.strategies[lose].budget_pct
        );
        // and nobody is fully starved (floor)
        assert!(e.strategies[lose].budget_pct >= 3.0);
    }

    #[test]
    fn composed_strategy_evaluates_and_deploys() {
        use super::composed::{Composed, Direction, IndKind, Op, Operand, RightMode, Rule};
        let mut e = Engine::new();
        // "enter LONG when RSI(14) < 30"
        let rules = Composed {
            direction: Direction::Long,
            rules: vec![Rule {
                left: Operand { kind: IndKind::Rsi, period: 14.0 },
                op: Op::Lt,
                right_mode: RightMode::Const,
                right_const: 30.0,
                right_operand: Operand { kind: IndKind::Price, period: 0.0 },
            }],
        };
        let down: Vec<f64> = (0..40).map(|i| 100.0 - i as f64 * 0.5).collect();
        assert_eq!(super::composed::eval_composed(&rules, &down, *down.last().unwrap()), Some(Side::Buy));

        let n0 = e.strategies.len();
        e.add_strategy(StrategyConfig {
            id: "composed-test".into(),
            name: "T".into(),
            kind: StrategyKind::Composed,
            venue_class: Venue::Crypto,
            state: StrategyState::Paper,
            universe: vec!["crypto:BTC/USD".into()],
            params: vec![],
            budget_pct: 10.0,
            pnl: 0.0,
            trades: 0,
            win_rate: 0.0,
            max_drawdown: 0.0,
            profit_factor: 0.0,
            equity_curve: vec![0.0],
            rules: Some(rules),
        });
        assert_eq!(e.strategies.len(), n0 + 1);
    }

    #[test]
    fn risk_kill_switch_blocks_buys() {
        let mut e = Engine::new();
        e.limits.kill_switch = true;
        e.manual_order("crypto:BTC/USD", Side::Buy, 1_000.0);
        // a buy under kill switch must not open a position
        assert!(e.positions.get("crypto:BTC/USD").is_none());
        // and it should be journaled as a rejection
        assert!(e.orders.iter().any(|o| o.status == OrderStatus::Rejected));
    }

    #[test]
    fn live_routing_only_alpaca_when_armed() {
        let mut e = Engine::new();

        // Disarmed: a manual Alpaca order fills as paper immediately, nothing queued.
        e.manual_order("alpaca:AAPL", Side::Buy, 1_000.0);
        assert!(e.drain_live_orders().is_empty());
        assert!(e.positions.contains_key("alpaca:AAPL"));
        e.flatten("alpaca:AAPL");
        assert!(e.drain_live_orders().is_empty(), "paper position flattens paper even later");

        // Arm live (paper endpoint). A manual Alpaca order now routes to the outbox
        // and does NOT open a position until the broker confirms.
        e.set_live(true, true, false);
        e.manual_order("alpaca:AAPL", Side::Buy, 1_000.0);
        let out = e.drain_live_orders();
        assert_eq!(out.len(), 1);
        assert_eq!(out[0].symbol, "AAPL");
        assert!(out[0].paper, "should target the paper endpoint");
        assert!(e.in_flight.contains("alpaca:AAPL"));
        assert!(!e.positions.contains_key("alpaca:AAPL"), "no position until fill confirmed");

        // Broker confirms → position opens and is marked live.
        e.apply_live_fill(&out[0].order_id, out[0].qty, 228.0);
        assert!(e.positions.get("alpaca:AAPL").map(|p| p.live).unwrap_or(false));
        assert!(!e.in_flight.contains("alpaca:AAPL"));

        // Crypto is never routed live, even when armed.
        e.manual_order("crypto:BTC/USD", Side::Buy, 1_000.0);
        assert!(e.drain_live_orders().is_empty());
        assert!(e.positions.contains_key("crypto:BTC/USD"));
    }
}
