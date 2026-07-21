//! Engine core (Phase 1). A persistent portfolio + sovereign risk manager +
//! strategy runtime that ticks on the Tokio runtime and pushes a full
//! [`EngineState`] snapshot to the UI each tick. This is the Rust owner of the
//! same model the browser build runs in TypeScript.

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
    ProbEdge,
    Momentum,
    MeanRevert,
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
    pub equity_curve: Vec<f64>,
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
}

impl Default for RiskLimits {
    fn default() -> Self {
        Self {
            kill_switch: false,
            max_daily_loss_pct: 5.0,
            max_position_pct: 15.0,
            max_gross_exposure_pct: 60.0,
            per_strategy_budget_pct: 20.0,
            kelly_fraction: 0.25,
            max_orders_per_min: 10,
            max_data_staleness_sec: 30,
        }
    }
}

#[derive(Debug, Clone)]
pub struct RiskDecision {
    pub approved: bool,
    pub qty: f64,
    pub reason: Option<String>,
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
}

// ── persistence (survive restarts) ─────────────────────────────────────────
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PersistedPosition {
    pub venue: Venue,
    pub symbol: String,
    pub qty: f64,
    pub avg_price: f64,
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
    real_ids: std::collections::HashSet<String>, // markets whose price came from a live feed
    positions: HashMap<String, PositionInternal>,
    orders: Vec<Order>,
    journal: Vec<JournalEntry>,
    strategies: Vec<StrategyConfig>,
    limits: RiskLimits,
    cash: f64,
    realized_pnl: f64,
    day_start_equity: f64,
    equity_curve: Vec<f64>,
    connected: std::collections::HashSet<Venue>,
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
        let mut e = Engine {
            markets,
            sim,
            real_ids: Default::default(),
            positions: HashMap::new(),
            orders: Vec::new(),
            journal: Vec::new(),
            strategies: strategies::default_strategies(),
            limits: RiskLimits::default(),
            cash: STARTING_CASH,
            realized_pnl: 0.0,
            day_start_equity: STARTING_CASH,
            equity_curve: vec![STARTING_CASH],
            connected: std::collections::HashSet::new(),
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

        // run strategies every 3rd tick
        if self.tick_count % 3 == 0 {
            let snapshot: HashMap<String, Market> =
                self.markets.iter().map(|m| (m.id.clone(), m.clone())).collect();
            let mut fires: Vec<(usize, strategies::SignalIntent)> = Vec::new();
            for (idx, strat) in self.strategies.iter().enumerate() {
                for intent in strategies::run_strategy(strat, &snapshot) {
                    fires.push((idx, intent));
                }
            }
            for (idx, intent) in fires {
                if let Some(m) = snapshot.get(&intent.market_id).cloned() {
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

        let eq = self.equity();
        self.equity_curve.push(eq);
        if self.equity_curve.len() > 300 {
            self.equity_curve.remove(0);
        }
    }

    fn place_from_intent(&mut self, strat_idx: usize, m: &Market, intent: &strategies::SignalIntent) {
        let price = m.price;
        let equity = self.equity();
        let sid = self.strategies[strat_idx].id.clone();
        let budget = (self.strategies[strat_idx].budget_pct / 100.0) * equity;
        let kelly = risk::kelly_size(intent.confidence, price, budget, &self.limits);
        let qty_wanted = (kelly * intent.size).max(0.0);
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
        self.fill(strat_idx, m, intent.side, decision.qty, price);
    }

    fn fill(&mut self, strat_idx: usize, m: &Market, side: Side, qty: f64, price: f64) {
        let sid = self.strategies[strat_idx].id.clone();
        let slip = if side == Side::Buy { 1.0008 } else { 0.9992 };
        let fill_price = price * slip;
        let fee = fill_price * qty * 0.0006;
        let signed = if side == Side::Buy { qty } else { -qty };

        // update / open position, realizing P&L on reductions
        let key = m.id.clone();
        let mut realized = 0.0;
        match self.positions.get_mut(&key) {
            None => {
                self.positions.insert(
                    key.clone(),
                    PositionInternal { venue: m.venue, symbol: m.symbol.clone(), qty: signed, avg_price: fill_price },
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

        // strategy stats
        {
            let s = &mut self.strategies[strat_idx];
            if realized != 0.0 {
                s.pnl += realized;
                s.trades += 1;
                let wins = s.win_rate * (s.trades - 1) as f64 + if realized >= 0.0 { 1.0 } else { 0.0 };
                s.win_rate = wins / s.trades as f64;
            }
            s.equity_curve.push(s.pnl);
            if s.equity_curve.len() > 200 {
                s.equity_curve.remove(0);
            }
        }

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
        self.fill(idx, &m, side, decision.qty, m.price);
    }

    pub fn flatten(&mut self, market_id: &str) {
        let Some(pos) = self.positions.get(market_id) else { return };
        let qty = pos.qty.abs();
        let side = if pos.qty > 0.0 { Side::Sell } else { Side::Buy };
        let Some(m) = self.markets.iter().find(|m| m.id == market_id).cloned() else { return };
        let idx = self.ensure_manual_strategy();
        self.fill(idx, &m, side, qty, m.price);
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
            equity_curve: vec![0.0],
        });
        self.strategies.len() - 1
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
        let orders_last_min = self.orders.iter().filter(|o| o.strategy_id == strategy_id && o.ts > cutoff).count() as u32;
        let strategy_exposure: f64 = self
            .orders
            .iter()
            .filter(|o| o.strategy_id == strategy_id && o.status == OrderStatus::Filled && o.ts > cutoff)
            .map(|o| o.avg_fill_price.unwrap_or(0.0) * o.filled_qty)
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
                    (id.clone(), PersistedPosition { venue: p.venue, symbol: p.symbol.clone(), qty: p.qty, avg_price: p.avg_price })
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
            .map(|(id, pp)| (id, PositionInternal { venue: pp.venue, symbol: pp.symbol, qty: pp.qty, avg_price: pp.avg_price }))
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
        let id = self.next_id("j");
        let mode = self.mode();
        self.journal.insert(0, JournalEntry { id, ts: self.now(), kind, strategy_id, market_id, message, mode });
        if self.journal.len() > 1000 {
            self.journal.pop();
        }
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
        updated_at: now,
    };
    let markets = vec![
        mk("crypto:BTC/USD", Venue::Crypto, "BTC/USD", MarketKind::Crypto, 67250.0, 0.018, None, 4_200_000.0),
        mk("crypto:ETH/USD", Venue::Crypto, "ETH/USD", MarketKind::Crypto, 3520.0, -0.012, None, 2_100_000.0),
        mk("crypto:SOL/USD", Venue::Crypto, "SOL/USD", MarketKind::Crypto, 168.4, 0.043, None, 900_000.0),
        mk("alpaca:AAPL", Venue::Alpaca, "AAPL", MarketKind::Equity, 227.1, 0.006, None, 1_500_000.0),
        mk("alpaca:NVDA", Venue::Alpaca, "NVDA", MarketKind::Equity, 138.9, 0.021, None, 3_300_000.0),
        mk("polymarket:fed-cut-2026", Venue::Polymarket, "Fed cuts rates before Sep 2026?", MarketKind::Prediction, 0.62, 0.03, Some(0.71), 320_000.0),
        mk("polymarket:btc-100k-2026", Venue::Polymarket, "BTC above $100k in 2026?", MarketKind::Prediction, 0.44, -0.02, Some(0.52), 510_000.0),
    ];
    let mut sim = HashMap::new();
    sim.insert("crypto:BTC/USD".into(), SimParam { drift: 0.00002, vol: 0.0018, base: 66000.0 });
    sim.insert("crypto:ETH/USD".into(), SimParam { drift: 0.00001, vol: 0.0022, base: 3560.0 });
    sim.insert("crypto:SOL/USD".into(), SimParam { drift: 0.00004, vol: 0.0035, base: 161.0 });
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
            PositionInternal { venue: Venue::Crypto, symbol: "BTC/USD".into(), qty: 0.5, avg_price: 60_000.0 },
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
    fn risk_kill_switch_blocks_buys() {
        let mut e = Engine::new();
        e.limits.kill_switch = true;
        e.manual_order("crypto:BTC/USD", Side::Buy, 1_000.0);
        // a buy under kill switch must not open a position
        assert!(e.positions.get("crypto:BTC/USD").is_none());
        // and it should be journaled as a rejection
        assert!(e.orders.iter().any(|o| o.status == OrderStatus::Rejected));
    }
}
