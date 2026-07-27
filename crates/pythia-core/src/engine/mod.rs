//! Engine core (Phase 1). A persistent portfolio + sovereign risk manager +
//! strategy runtime that ticks on the Tokio runtime and pushes a full
//! [`EngineState`] snapshot to the UI each tick. This is the Rust owner of the
//! same model the browser build runs in TypeScript.

pub mod composed;
pub mod indicators;
pub mod risk;
pub mod strategies;

use crate::connectors::{BrokerOrderStatus, BrokerPosition, OrderType, Side, Venue};
use crate::forecast::{self, calibration, coherence, track};
use crate::marketdata::{RealCrypto, RealEquity, RealPrediction};
use serde::{Deserialize, Serialize};
use std::collections::{HashMap, HashSet};

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
    /// Prediction markets: the NO price, when the venue quotes it. YES + NO
    /// should be 1; a gap is a model-free arbitrage.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub no_price: Option<f64>,
    /// Prediction markets: resolution time in epoch millis, when known.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub resolves_at: Option<i64>,
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
    /// Held via a real venue fill — closing it needs live routing.
    pub live: bool,
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

/// Live-execution configuration. Everything here is off until the user arms it
/// with a typed confirmation, and each venue must be enabled individually — one
/// arm action can never light up a venue the user did not choose.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct LiveConfig {
    /// Master arm. When false, everything simulates — no order leaves the machine.
    pub armed: bool,
    /// Route to the broker's PAPER endpoint (real API, no real money).
    pub paper: bool,
    /// Log intended orders but don't submit them anywhere.
    pub dry_run: bool,
    /// Venues allowed to route live. Empty means nothing routes, whatever
    /// `armed` says.
    pub venues: Vec<Venue>,
    /// How long a working order may sit before the engine cancels it at the
    /// venue and reconciles whatever filled. Never 0 — see [`LiveConfig::clamped`].
    pub timeout_sec: u64,
}

impl Default for LiveConfig {
    fn default() -> Self {
        Self {
            armed: false,
            paper: true,
            dry_run: false,
            venues: vec![Venue::Alpaca],
            // Two minutes: long enough for a market order to work through a thin
            // open, short enough that a stuck order does not tie up the market
            // for a whole session.
            timeout_sec: 120,
        }
    }
}

impl LiveConfig {
    /// Reject nonsense before it becomes a stuck order. A 0s timeout would
    /// cancel every order before it could fill; a 1h one would hide a problem
    /// for an hour.
    fn clamped(mut self) -> Self {
        self.timeout_sec = self.timeout_sec.clamp(15, 900);
        self.venues.sort_by_key(|v| format!("{v:?}"));
        self.venues.dedup();
        self
    }
}

/// Live-execution status surfaced to the UI.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct LiveStatus {
    pub armed: bool,
    pub paper: bool,
    pub dry_run: bool,
    pub venues: Vec<Venue>,
    pub timeout_sec: u64,
    /// Venues that have credentials available (vault or env).
    pub connected: Vec<Venue>,
    /// Kept for the existing UI: Alpaca specifically has keys.
    pub alpaca_connected: bool,
    /// Live orders currently awaiting a broker response.
    pub pending: usize,
    /// Positions currently held via a real venue fill. These cannot be closed
    /// by the simulator, so the UI has to make them obvious.
    pub live_positions: usize,
}

/// Why an order is being routed — and therefore what is allowed to happen to it
/// if live routing is unavailable.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RouteIntent {
    /// A paper strategy. Always simulates.
    Paper,
    /// A live strategy opening or adding. Simulates when disarmed — no harm, the
    /// engine simply keeps paper-trading until the user arms.
    Live,
    /// Closing a position that was opened with a *real* fill. This must reach the
    /// venue or not happen at all: simulating it would tell the user they are
    /// flat while real shares sit at the broker.
    LiveExit,
}

/// One live order handed to the async daemon to submit. The daemon is the only
/// place that touches the network; the engine stays synchronous.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct LiveOrderOut {
    pub order_id: String,
    /// Stable id echoed to the venue so a lost response can be recovered.
    pub client_order_id: String,
    pub venue: Venue,
    pub market_id: String,
    /// Venue ticker (e.g. "AAPL", "BTC/USD") — what the broker expects.
    pub symbol: String,
    pub side: Side,
    pub qty: f64,
    pub ref_price: f64,
    pub strategy_id: String,
    /// This order closes an existing position; it must not flip it.
    pub reduce_only: bool,
    /// Snapshot of the arm config at enqueue time.
    pub paper: bool,
    pub dry_run: bool,
}

/// An in-flight order the daemon should poll. Produced by
/// [`Engine::live_polls`]; the daemon fetches each one's status and feeds the
/// answer back through [`Engine::apply_live_update`].
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct LivePoll {
    pub order_id: String,
    pub broker_id: String,
    pub venue: Venue,
    pub market_id: String,
    pub symbol: String,
    pub paper: bool,
    pub age_ms: i64,
    /// This order has outlived the timeout: cancel it at the venue first, then
    /// report whatever ended up filled.
    pub cancel: bool,
}

/// What a venue says about one of our orders, normalised.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct LiveUpdate {
    pub status: BrokerOrderStatus,
    /// Cumulative filled quantity, as the venue reports it.
    pub filled_qty: f64,
    pub avg_price: Option<f64>,
    /// Cumulative fees so far.
    pub fee: f64,
    /// The venue's own status word, for the journal.
    pub raw_status: String,
}

impl LiveUpdate {
    fn status_word(&self) -> &'static str {
        match self.status {
            BrokerOrderStatus::Filled => "filled",
            BrokerOrderStatus::PartiallyFilled => "partially filled",
            BrokerOrderStatus::Working => "working",
            BrokerOrderStatus::Canceled => "cancelled",
            BrokerOrderStatus::Rejected => "rejected by the venue",
            BrokerOrderStatus::Expired => "expired",
        }
    }
}

/// An order the engine has sent to a venue and not yet finished with.
#[derive(Debug, Clone)]
struct InFlight {
    market_id: String,
    symbol: String,
    venue: Venue,
    side: Side,
    strategy_id: String,
    /// `None` until the venue acknowledges the submission.
    broker_id: Option<String>,
    submitted_at: i64,
    /// How much of the venue's cumulative fill we have already booked. The
    /// difference against a fresh report is exactly what still needs settling,
    /// which is what makes partial fills safe to apply repeatedly.
    booked_qty: f64,
    booked_fee: f64,
    paper: bool,
    cancel_sent: bool,
}

/// The full state pushed to the UI every tick.
///
/// camelCase like every other DTO here. Most fields are single words so the
/// rename is invisible — but `forecast_stats` is not, and without this it would
/// reach the frontend under a name the TypeScript type does not have.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
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
    /// The forecasting layer's current view of each market.
    #[serde(default)]
    pub forecasts: Vec<forecast::MarketForecast>,
    /// Scoreboard per forecasting source — what actually earns weight.
    #[serde(default)]
    pub tracks: Vec<calibration::Track>,
    /// Markets whose own outcomes do not price to 1.
    #[serde(default)]
    pub coherence: Vec<coherence::CoherenceBreak>,
    #[serde(default)]
    pub forecast_stats: ForecastStats,
}

/// Headline numbers for the forecasting layer.
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ForecastStats {
    pub recorded: usize,
    pub resolved: usize,
    pub pending: usize,
    /// Sources that have earned non-zero weight. Zero here means the ensemble
    /// is currently advisory only, which is the honest starting state.
    pub trusted_sources: usize,
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
    /// Opened with a real venue fill. This MUST survive a restart: forgetting it
    /// would let the simulator "close" shares that are really sitting at a broker.
    #[serde(default)]
    pub live: bool,
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
    /// The forecast ledger. Losing this on restart would reset every source's
    /// track record to "unproven" and silence the whole ensemble, so it is
    /// persisted with everything else.
    #[serde(default)]
    pub forecast_store: track::ForecastStore,
    #[serde(default)]
    pub forecast_cfg: Option<forecast::ForecastConfig>,
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

/// How long a market is skipped for live routing after the venue refused an
/// order. Long enough to stop a per-tick retry storm, short enough that the
/// engine reacts within a minute of the condition clearing (a market opening,
/// cash settling).
const LIVE_REJECT_BACKOFF_MS: i64 = 60_000;

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
    // ── live execution (OFF by default) ──
    live: LiveConfig,
    pending_live: Vec<LiveOrderOut>,     // outbox drained by the async daemon
    inflight: HashMap<String, InFlight>, // engine order id → its state at the venue
    in_flight_markets: HashSet<String>,  // one live order per market at a time
    /// Last time we complained that a live position cannot be closed, per market.
    /// Stops a stop-loss that keeps re-triggering from flooding the journal.
    live_warned_at: HashMap<String, i64>,
    /// Per-market backoff after a live order was refused. A breakout signal fires
    /// every few seconds while the condition holds; without this, a closed market
    /// produces one identical rejection per tick until it opens.
    live_backoff_until: HashMap<String, i64>,
    /// Feeds we have already announced, so the journal is not a 12-second
    /// heartbeat with the occasional fill hidden in it.
    feeds_logged: HashSet<&'static str>,
    // ── forecasting ──
    forecast_cfg: forecast::ForecastConfig,
    /// Every prediction ever made, and how it turned out. This is what turns
    /// opinions into weights — see [`forecast::calibration`].
    forecast_store: track::ForecastStore,
    /// Per-source trust and recalibration, and the full scorecards. Both are
    /// derived from the ledger and only change when a forecast *resolves*, so
    /// they are cached against `forecast_store.resolution_version()` rather
    /// than refitted every tick.
    source_stats: track::SourceStats,
    track_cache: Vec<calibration::Track>,
    scored_version: Option<u64>,
    /// Latest forecast per market, rebuilt on a schedule.
    forecasts: Vec<forecast::MarketForecast>,
    coherence: Vec<coherence::CoherenceBreak>,
    /// Cached LLM opinions per market, with the time they were fetched. The
    /// engine is synchronous and never calls a model itself; the daemon pushes
    /// them in through [`Engine::apply_llm_opinions`].
    llm_opinions: HashMap<String, (i64, Vec<crate::llm::Signal>)>,
    /// Markets whose forecast currently clears its costs. Prediction-market
    /// signals are dropped unless their market is in here.
    actionable: HashSet<String>,
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
            live: LiveConfig::default(),
            pending_live: Vec::new(),
            inflight: HashMap::new(),
            in_flight_markets: HashSet::new(),
            live_warned_at: HashMap::new(),
            live_backoff_until: HashMap::new(),
            feeds_logged: HashSet::new(),
            forecast_cfg: forecast::ForecastConfig::default(),
            forecast_store: track::ForecastStore::default(),
            source_stats: track::SourceStats::default(),
            track_cache: Vec::new(),
            scored_version: None,
            forecasts: Vec::new(),
            coherence: Vec::new(),
            llm_opinions: HashMap::new(),
            actionable: HashSet::new(),
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
        // Logged once, not every refresh: during a live run the journal is how
        // you watch orders, and a heartbeat every 12s buries them.
        if !feed.is_empty() && self.feeds_logged.insert("kraken") {
            self.log(JournalKind::System, format!("Kraken feed · {} live crypto prices", feed.len()), None, None);
        }
    }

    /// Overlay real Alpaca equity quotes onto the seeded equity markets. Same
    /// shape as [`Engine::apply_kraken`] — prices become real, so a Live
    /// equities strategy trades on genuine quotes instead of the simulator.
    pub fn apply_alpaca(&mut self, feed: &[RealEquity]) {
        let now = self.now();
        for r in feed {
            if let Some(m) = self.markets.iter_mut().find(|m| m.id == r.id) {
                m.price = r.price;
                m.change24h = r.change24h;
                m.updated_at = now;
                self.real_ids.insert(r.id.clone());
            }
        }
        if !feed.is_empty() && self.feeds_logged.insert("alpaca") {
            self.log(JournalKind::System, format!("Alpaca feed · {} live equity quotes", feed.len()), None, None);
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
                m.no_price = r.no_price;
                m.resolves_at = r.end_at;
                m.updated_at = now;
            } else {
                self.markets.push(Market {
                    id: r.id.clone(),
                    venue: Venue::Polymarket,
                    symbol: r.symbol.clone(),
                    kind: MarketKind::Prediction,
                    price: r.price,
                    change24h: 0.0,
                    // Filled by the forecasting layer once it has an ensemble
                    // view; until then there is no model and no auto-betting.
                    model_prob: None,
                    liquidity: Some(r.liquidity),
                    regime: None,
                    trend_strength: None,
                    no_price: r.no_price,
                    resolves_at: r.end_at,
                    updated_at: now,
                });
            }
        }
        if self.feeds_logged.insert("polymarket") {
            self.log(JournalKind::System, format!("Polymarket feed · {} live markets", feed.len()), None, None);
        }
    }

    // ── main tick ───────────────────────────────────────────────────────────
    pub fn tick(&mut self) {
        self.tick_count += 1;
        let now = self.now();

        // Advance simulated markets (real-fed markets random-walk gently between
        // fetches). Done in three passes rather than one loop with a lookup:
        // the old version cloned every market id and then linear-searched the
        // market list for each one, which is quadratic and allocates a String
        // per market per tick.
        //
        // Pass 1 reads the sim parameters (immutable borrow of markets + sim),
        // pass 2 draws the shocks (needs `&mut self` for the PRNG), pass 3
        // applies them by index (mutable borrow of markets alone).
        let plan: Vec<(f64, f64, Option<f64>)> = (0..self.markets.len())
            .map(|i| {
                let id = &self.markets[i].id;
                let p = self.sim.get(id);
                let (drift, vol) = p.map(|p| (p.drift, p.vol)).unwrap_or((0.0, 0.0015));
                // A market fed by a real price feed keeps the venue's own 24h
                // change; only simulated ones derive it from the sim base.
                let base = p.map(|p| p.base).filter(|_| !self.real_ids.contains(id));
                (drift, vol, base)
            })
            .collect();
        let plan: Vec<(f64, Option<f64>)> = plan
            .into_iter()
            .map(|(drift, vol, base)| (drift + vol * self.gaussian(), base))
            .collect();

        for (m, (shock, base)) in self.markets.iter_mut().zip(plan) {
            if m.kind == MarketKind::Prediction {
                m.price = (m.price + shock).clamp(0.02, 0.98);
            } else {
                m.price *= 1.0 + shock;
            }
            if let Some(base) = base.filter(|b| *b != 0.0) {
                m.change24h = (m.price - base) / base;
            }
            m.updated_at = now;
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

        // Rebuild the forecasting layer periodically (~every 15s). It is pure
        // computation over data already in hand — no network, no model calls.
        if self.tick_count % 10 == 1 {
            self.update_forecasts();
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
                    // A prediction-market bet is only taken when the forecasting
                    // layer says the edge survives the spread. The strategy's own
                    // threshold is about the signal; this is about the cost of
                    // acting on it, and both have to pass.
                    if m.kind == MarketKind::Prediction && !self.actionable.contains(&intent.market_id) {
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

    // ── forecasting ─────────────────────────────────────────────────────────
    /// How long an LLM opinion stays usable. Models are asked about slow-moving
    /// questions, but a view formed before a 20% move is not a view about the
    /// current market.
    const LLM_TTL_MS: i64 = 6 * 3_600_000;

    /// Push a batch of model opinions for one market. Called by the daemon after
    /// an ensemble run; the engine itself never touches the network.
    pub fn apply_llm_opinions(&mut self, market_id: &str, signals: Vec<crate::llm::Signal>) {
        if signals.is_empty() {
            return;
        }
        let n = signals.len();
        let symbol = self
            .markets
            .iter()
            .find(|m| m.id == market_id)
            .map(|m| m.symbol.clone())
            .unwrap_or_else(|| market_id.to_string());
        self.llm_opinions.insert(market_id.to_string(), (self.now(), signals));
        self.log(
            JournalKind::Signal,
            format!("Ensemble: {n} model opinion(s) on {symbol}"),
            None,
            Some(market_id.to_string()),
        );
        // Fold them in immediately rather than waiting for the next sweep.
        self.update_forecasts();
    }

    pub fn forecast_config(&self) -> forecast::ForecastConfig {
        self.forecast_cfg.clone()
    }

    pub fn set_forecast_config(&mut self, cfg: forecast::ForecastConfig) {
        self.forecast_cfg = cfg;
        self.log(JournalKind::System, "Forecast settings updated".into(), None, None);
        self.update_forecasts();
    }

    /// Every scored source, for the calibration view. Served from the cache —
    /// see [`Engine::rescore_if_needed`].
    pub fn forecast_tracks(&self) -> Vec<calibration::Track> {
        self.track_cache.clone()
    }

    /// Refit per-source trust and recalibration, but only when a forecast has
    /// actually resolved since the last fit.
    ///
    /// Recording a forecast cannot change any score, and forecasts are recorded
    /// constantly while resolutions arrive on the order of hours. Keying the
    /// cache on the resolution counter turns a per-tick logistic regression per
    /// source per market into one pass, occasionally.
    fn rescore_if_needed(&mut self) {
        let version = self.forecast_store.resolution_version();
        if self.scored_version == Some(version) {
            return;
        }
        self.source_stats = self.forecast_store.source_stats();
        self.track_cache = self.forecast_store.tracks();
        self.scored_version = Some(version);
    }

    /// Score, resolve and rebuild every market's forecast.
    ///
    /// Order matters: resolution happens **before** new forecasts are built, so
    /// a source's weight always reflects everything already known. Building
    /// first would let a source be weighted by a track record that excludes the
    /// question it just answered.
    fn update_forecasts(&mut self) {
        let now = self.now();
        let prices: HashMap<String, f64> =
            self.markets.iter().map(|m| (m.id.clone(), m.price)).collect();

        // 1 · Reality check: settle what can be settled.
        let resolved = self.forecast_store.auto_resolve(now, &prices);
        let pred_prices: HashMap<String, f64> = self
            .markets
            .iter()
            .filter(|m| m.kind == MarketKind::Prediction)
            .map(|m| (m.id.clone(), m.price))
            .collect();
        let settled = self.forecast_store.resolve_settled(now, &pred_prices);
        if settled > 0 {
            self.log(
                JournalKind::System,
                format!("{settled} outcome forecast(s) settled — track records updated"),
                None,
                None,
            );
        }
        let _ = resolved; // scored silently; the journal would be noise

        // 2 · Refit the scoreboard if anything resolved, then rebuild each
        // market's forecast from the sources available now.
        self.rescore_if_needed();
        let cfg = self.forecast_cfg.clone();
        let snapshot: Vec<Market> = self.markets.clone();
        let mut out: Vec<forecast::MarketForecast> = Vec::new();
        let mut actionable: HashSet<String> = HashSet::new();

        for m in &snapshot {
            let is_prediction = m.kind == MarketKind::Prediction;
            let history = self.history.get(&m.id).cloned().unwrap_or_default();
            let llm: Vec<crate::llm::Signal> = self
                .llm_opinions
                .get(&m.id)
                .filter(|(at, _)| now - *at < Self::LLM_TTL_MS)
                .map(|(_, s)| s.clone())
                .unwrap_or_default();

            let days = m
                .resolves_at
                .map(|end| ((end - now) as f64 / 86_400_000.0).max(0.0));

            let f = forecast::build(
                &forecast::ForecastInput {
                    market_id: &m.id,
                    symbol: &m.symbol,
                    price: m.price,
                    is_prediction,
                    history: &history,
                    liquidity: m.liquidity,
                    days_to_resolution: days,
                    llm: &llm,
                    now,
                },
                &self.source_stats,
                &cfg,
            );
            if f.action != forecast::Action::Hold {
                actionable.insert(m.id.clone());
            }
            out.push(f);
        }

        // 3 · Write down what was predicted, so it can be scored later.
        for f in &out {
            let market_id = f.market_id.clone();
            let ref_price = snapshot
                .iter()
                .find(|m| m.id == market_id)
                .map(|m| m.price)
                .unwrap_or(0.0);

            if f.kind == track::ForecastKind::Outcome {
                // The level view, which settles when the event does...
                self.forecast_store.record(
                    now, &market_id, "ensemble", track::ForecastKind::Outcome,
                    f.ensemble_p, f.market_p, ref_price, cfg.horizon_ms,
                );
                for s in &f.sources {
                    self.forecast_store.record(
                        now, &market_id, &s.source, track::ForecastKind::Outcome,
                        s.p, f.market_p, ref_price, cfg.horizon_ms,
                    );
                }
                // ...and the derived directional view, which settles on a timer.
                // Without this, an election market yields no calibration data
                // for months, and every source stays unweighted forever.
                self.forecast_store.record(
                    now, &market_id, "ensemble", track::ForecastKind::Direction,
                    forecast::direction_from_edge(f.ensemble_p, f.market_p),
                    0.5, ref_price, cfg.horizon_ms,
                );
                for s in &f.sources {
                    self.forecast_store.record(
                        now, &market_id, &s.source, track::ForecastKind::Direction,
                        forecast::direction_from_edge(s.p, f.market_p),
                        0.5, ref_price, cfg.horizon_ms,
                    );
                }
            } else {
                self.forecast_store.record(
                    now, &market_id, "ensemble", track::ForecastKind::Direction,
                    f.ensemble_p, f.market_p, ref_price, cfg.horizon_ms,
                );
                for s in &f.sources {
                    self.forecast_store.record(
                        now, &market_id, &s.source, track::ForecastKind::Direction,
                        s.p, f.market_p, ref_price, cfg.horizon_ms,
                    );
                }
            }
        }

        // 4 · The ensemble becomes the market's model probability, so the UI and
        // the Prob-Edge strategy see the same number the forecaster produced.
        for f in &out {
            if f.kind == track::ForecastKind::Outcome {
                if let Some(m) = self.markets.iter_mut().find(|m| m.id == f.market_id) {
                    m.model_prob = Some(f.ensemble_p.clamp(0.001, 0.999));
                }
            }
        }

        // 5 · Coherence: does the market even agree with itself?
        let sets: Vec<coherence::OutcomeSet> = snapshot
            .iter()
            .filter(|m| m.kind == MarketKind::Prediction)
            .filter_map(|m| {
                let no = m.no_price?;
                Some(coherence::binary_set(&m.id, &m.symbol, &m.id, m.price, no))
            })
            .collect();
        let breaks = coherence::check(&sets, cfg.cost_bps / 2.0);
        for b in &breaks {
            if b.actionable && !self.coherence.iter().any(|old| old.event_id == b.event_id) {
                self.log(
                    JournalKind::Signal,
                    format!(
                        "Coherence break on {}: outcomes sum to {:.4} — {:.0}bps after costs",
                        b.title, b.sum, b.net_bps
                    ),
                    None,
                    Some(b.event_id.clone()),
                );
            }
        }
        self.coherence = breaks;
        self.actionable = actionable;
        self.forecasts = out;
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
        let intent = if live { RouteIntent::LiveExit } else { RouteIntent::Paper };
        self.route_fill(idx, &m, side, qty, m.price, intent);
        // Only claim the exit happened if it actually did. A live exit that
        // could not route leaves the position open, and `route_fill` has
        // already explained why.
        if !live || self.live_routable(m.venue) {
            self.log(JournalKind::System, format!("Exit {id}: {reason}"), Some(sid), Some(id.to_string()));
        }
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
            symbol: m.symbol.clone(),
            side: intent.side,
            order_type: OrderType::Market,
            qty: qty_wanted,
            limit_price: None,
            ref_price: Some(price),
            client_order_id: None,
            reduce_only: false,
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
        let route = if self.strategies[strat_idx].state == StrategyState::Live {
            RouteIntent::Live
        } else {
            RouteIntent::Paper
        };
        self.route_fill(strat_idx, m, intent.side, decision.qty, price, route);
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

    /// True when this venue may currently send orders to a real market.
    fn live_routable(&self, venue: Venue) -> bool {
        self.live.armed && self.live.venues.contains(&venue)
    }

    /// Decide whether an approved order simulates (paper) or routes to a real
    /// venue.
    ///
    /// The one case that must never silently fall back to simulation is
    /// [`RouteIntent::LiveExit`]: those shares exist at a broker, and booking a
    /// fake exit would leave Pythia showing flat while the real position runs
    /// unmanaged. When it cannot route, it refuses and says so.
    fn route_fill(&mut self, strat_idx: usize, m: &Market, side: Side, qty: f64, price: f64, intent: RouteIntent) {
        let routable = self.live_routable(m.venue);
        match intent {
            RouteIntent::Paper => return self.fill(strat_idx, m, side, qty, price),
            RouteIntent::Live if !routable => return self.fill(strat_idx, m, side, qty, price),
            RouteIntent::LiveExit if !routable => {
                self.warn_stuck_live_position(m);
                return;
            }
            _ => {}
        }

        // One live order per market at a time — never double-send while a prior
        // order is still awaiting a broker response.
        if self.in_flight_markets.contains(&m.id) {
            return;
        }
        // Still backing off from a refusal (market closed, no buying power).
        // Re-sending the identical order every tick would achieve nothing except
        // an unreadable journal.
        if self.live_backoff_until.get(&m.id).is_some_and(|&until| self.now() < until) {
            return;
        }
        let sid = self.strategies[strat_idx].id.clone();
        let order = self.build_order(&sid, m, side, qty, OrderStatus::Pending, None);
        let order_id = order.id.clone();
        self.orders.insert(0, order);
        self.in_flight_markets.insert(m.id.clone());
        self.inflight.insert(
            order_id.clone(),
            InFlight {
                market_id: m.id.clone(),
                symbol: m.symbol.clone(),
                venue: m.venue,
                side,
                strategy_id: sid.clone(),
                broker_id: None,
                submitted_at: self.now(),
                booked_qty: 0.0,
                booked_fee: 0.0,
                paper: self.live.paper,
                cancel_sent: false,
            },
        );
        self.pending_live.push(LiveOrderOut {
            client_order_id: format!("pythia-{order_id}"),
            order_id,
            venue: m.venue,
            market_id: m.id.clone(),
            symbol: m.symbol.clone(),
            side,
            qty,
            ref_price: price,
            strategy_id: sid.clone(),
            reduce_only: intent == RouteIntent::LiveExit,
            paper: self.live.paper,
            dry_run: self.live.dry_run,
        });
        self.log(
            JournalKind::Order,
            format!("{} submit {side:?} {qty:.4} {} @ ~{price:.2}", self.live_dest(), m.symbol),
            Some(sid),
            Some(m.id.clone()),
        );
    }

    fn live_dest(&self) -> &'static str {
        if self.live.dry_run {
            "DRY-RUN"
        } else if self.live.paper {
            "PAPER-LIVE"
        } else {
            "REAL-LIVE"
        }
    }

    /// A live-opened position wanted to close but live routing is unavailable.
    /// Say so loudly — but only once a minute per market, because the stop-loss
    /// that triggered it will keep triggering every tick.
    fn warn_stuck_live_position(&mut self, m: &Market) {
        let now = self.now();
        if let Some(&last) = self.live_warned_at.get(&m.id) {
            if now - last < 60_000 {
                return;
            }
        }
        self.live_warned_at.insert(m.id.clone(), now);
        let msg = format!(
            "{} holds a REAL position that wants to close, but live routing is off for {:?}. \
             It is NOT closed. Re-arm to exit, or flatten it in the broker's own dashboard.",
            m.symbol, m.venue
        );
        self.log(JournalKind::Risk, msg.clone(), None, Some(m.id.clone()));
        self.pending_alerts.push(format!("⚠ {msg}"));
    }

    // ── live execution control ──────────────────────────────────────────────
    /// Arm/disarm real order routing. Arming is a deliberate, logged, alerted
    /// action; disarming stops new live orders (in-flight ones still reconcile).
    pub fn set_live(&mut self, cfg: LiveConfig) {
        let was = self.live.armed;
        let cfg = cfg.clamped();
        let dest = if cfg.dry_run {
            "dry-run (nothing sent)".to_string()
        } else if cfg.paper {
            "the PAPER endpoint (no real money)".to_string()
        } else {
            "REAL MONEY".to_string()
        };
        let venues = if cfg.venues.is_empty() {
            "no venues (nothing will route)".to_string()
        } else {
            cfg.venues.iter().map(|v| format!("{v:?}")).collect::<Vec<_>>().join(", ")
        };
        let armed = cfg.armed;
        let live_open = self.live_position_count();
        self.live = cfg;

        if armed {
            self.log(JournalKind::Risk, format!("LIVE ARMED — {venues} route to {dest}"), None, None);
            self.pending_alerts.push(format!("⚠ Pythia LIVE ARMED → {venues} → {dest}"));
        } else if was {
            self.log(JournalKind::Risk, "LIVE DISARMED — new orders simulate again".into(), None, None);
            self.pending_alerts.push("Pythia live disarmed".into());
            if live_open > 0 {
                // Disarming does not flatten anything. Saying so here is the
                // difference between "I stopped it" and an unmanaged position.
                let msg = format!(
                    "{live_open} real position(s) are still open at their venue — disarming does not close them. \
                     Flatten from Positions while armed, or in the broker's dashboard."
                );
                self.log(JournalKind::Risk, msg.clone(), None, None);
                self.pending_alerts.push(format!("⚠ {msg}"));
            }
        }
    }

    pub fn live_config(&self) -> LiveConfig {
        self.live.clone()
    }

    fn live_position_count(&self) -> usize {
        self.positions.values().filter(|p| p.live && p.qty.abs() > 1e-9).count()
    }

    /// Hand the async daemon every live order awaiting submission.
    pub fn drain_live_orders(&mut self) -> Vec<LiveOrderOut> {
        std::mem::take(&mut self.pending_live)
    }

    /// The venue accepted our submission. From here the order has a life of its
    /// own at the broker, and the only safe thing to do is keep asking about it.
    pub fn apply_live_ack(&mut self, order_id: &str, broker_id: &str) {
        if let Some(f) = self.inflight.get_mut(order_id) {
            f.broker_id = Some(broker_id.to_string());
            f.submitted_at = chrono::Utc::now().timestamp_millis();
        }
    }

    /// Every in-flight order the daemon should ask the venue about this tick.
    pub fn live_polls(&self) -> Vec<LivePoll> {
        let now = chrono::Utc::now().timestamp_millis();
        let timeout_ms = (self.live.timeout_sec as i64) * 1000;
        self.inflight
            .iter()
            .filter_map(|(order_id, f)| {
                let broker_id = f.broker_id.clone()?;
                let age = now - f.submitted_at;
                Some(LivePoll {
                    order_id: order_id.clone(),
                    broker_id,
                    venue: f.venue,
                    market_id: f.market_id.clone(),
                    symbol: f.symbol.clone(),
                    paper: f.paper,
                    age_ms: age,
                    cancel: age > timeout_ms && !f.cancel_sent,
                })
            })
            .collect()
    }

    /// Note that a cancel has been sent, so we do not send it every tick while
    /// the venue works through it.
    pub fn mark_cancel_sent(&mut self, order_id: &str) {
        if let Some(f) = self.inflight.get_mut(order_id) {
            f.cancel_sent = true;
        }
    }

    /// Apply the venue's view of one of our orders.
    ///
    /// `update.filled_qty` is cumulative, so the amount that still needs
    /// booking is the difference against what we already settled. That makes
    /// this safe to call repeatedly with the same numbers — a partial fill
    /// reported three times books once.
    pub fn apply_live_update(&mut self, order_id: &str, update: LiveUpdate) {
        let Some(f) = self.inflight.get(order_id).cloned() else { return };
        let delta = update.filled_qty - f.booked_qty;

        if delta > 1e-9 {
            if let Some(price) = update.avg_price.filter(|p| *p > 0.0) {
                if let Some(m) = self.markets.iter().find(|mm| mm.id == f.market_id).cloned() {
                    let idx = self
                        .strategies
                        .iter()
                        .position(|s| s.id == f.strategy_id)
                        .unwrap_or_else(|| self.ensure_manual_strategy());
                    let fee_delta = (update.fee - f.booked_fee).max(0.0);
                    // emit_order = false: the pending order row already exists
                    // and is updated below rather than duplicated.
                    self.settle_fill(idx, &m, f.side, delta, price, fee_delta, true, false);
                    self.log(
                        JournalKind::Fill,
                        format!("LIVE FILL {:?} {delta:.6} {} @ {price:.4}", f.side, m.symbol),
                        Some(f.strategy_id.clone()),
                        Some(f.market_id.clone()),
                    );
                    if let Some(g) = self.inflight.get_mut(order_id) {
                        g.booked_qty = update.filled_qty;
                        g.booked_fee = update.fee;
                    }
                }
            }
        }

        // Reflect the venue's state on the order row.
        if let Some(ord) = self.orders.iter_mut().find(|x| x.id == order_id) {
            ord.filled_qty = update.filled_qty;
            ord.avg_fill_price = update.avg_price;
            ord.mode = Mode::Live;
            ord.status = match update.status {
                BrokerOrderStatus::Filled => OrderStatus::Filled,
                BrokerOrderStatus::PartiallyFilled => OrderStatus::Partial,
                BrokerOrderStatus::Working => OrderStatus::Pending,
                BrokerOrderStatus::Rejected => OrderStatus::Rejected,
                BrokerOrderStatus::Canceled | BrokerOrderStatus::Expired => {
                    // A cancel that caught a partial fill is a partial, not a
                    // cancel: something real happened and the ledger must say so.
                    if update.filled_qty > 0.0 { OrderStatus::Partial } else { OrderStatus::Cancelled }
                }
            };
        }

        if update.status.is_terminal() {
            self.finish_live_order(order_id, &update);
        }
    }

    fn finish_live_order(&mut self, order_id: &str, update: &LiveUpdate) {
        let Some(f) = self.inflight.remove(order_id) else { return };
        self.in_flight_markets.remove(&f.market_id);
        if update.filled_qty <= 0.0 {
            let reason = format!("{} ({})", update.status_word(), update.raw_status);
            if let Some(ord) = self.orders.iter_mut().find(|x| x.id == order_id) {
                ord.reject_reason = Some(reason.clone());
            }
            self.log(
                JournalKind::Reject,
                format!("LIVE order {} {} — nothing filled", f.symbol, reason),
                Some(f.strategy_id),
                Some(f.market_id),
            );
        }
    }

    /// The order never reached the venue (dry-run, missing keys, preflight
    /// refusal, network failure). Nothing is resting anywhere, so we can drop it.
    pub fn apply_live_reject(&mut self, order_id: &str, reason: &str) {
        let f = self.inflight.remove(order_id);
        if let Some(f) = &f {
            self.in_flight_markets.remove(&f.market_id);
            self.live_backoff_until.insert(f.market_id.clone(), self.now() + LIVE_REJECT_BACKOFF_MS);
        }
        if let Some(ord) = self.orders.iter_mut().find(|x| x.id == order_id) {
            ord.status = OrderStatus::Rejected;
            ord.reject_reason = Some(reason.to_string());
        }
        let symbol = f.as_ref().map(|f| f.symbol.clone()).unwrap_or_default();
        self.log(
            JournalKind::Reject,
            format!("LIVE order not sent{}: {reason}", if symbol.is_empty() { String::new() } else { format!(" ({symbol})") }),
            f.as_ref().map(|f| f.strategy_id.clone()),
            f.as_ref().map(|f| f.market_id.clone()),
        );
    }

    /// Reconcile against what the venue actually holds. The broker is always
    /// right: if the two disagree, Pythia's book is what changes.
    ///
    /// Only *live* positions in markets the engine knows about are touched —
    /// paper positions and unrelated venue holdings are left alone.
    ///
    /// `adopt_unknown` decides what happens to a venue position Pythia has no
    /// record of. The daemon passes `false`: a user's own long-held AAPL is not
    /// Pythia's to manage, and adopting it would put a stop-loss under someone's
    /// retirement account. Set it only when the caller knows the account is
    /// dedicated to the bot.
    pub fn reconcile_positions(&mut self, venue: Venue, broker: &[BrokerPosition], adopt_unknown: bool) {
        let known: HashMap<String, (String, f64)> = self
            .markets
            .iter()
            .filter(|m| m.venue == venue)
            .map(|m| (m.symbol.clone(), (m.id.clone(), m.price)))
            .collect();

        let mut seen: HashSet<String> = HashSet::new();
        for bp in broker {
            let Some((market_id, price)) = known.get(&bp.symbol).cloned() else { continue };
            seen.insert(market_id.clone());
            let avg = if bp.avg_price > 0.0 { bp.avg_price } else { price };
            match self.positions.get_mut(&market_id) {
                Some(p) if (p.qty - bp.qty).abs() < 1e-6 => {
                    p.live = true; // agrees — just make sure it is flagged live
                }
                Some(p) => {
                    let was = p.qty;
                    p.qty = bp.qty;
                    p.avg_price = avg;
                    p.live = true;
                    self.log(
                        JournalKind::Risk,
                        format!("Reconciled {}: book had {was:.6}, {venue:?} has {:.6} — broker wins", bp.symbol, bp.qty),
                        None,
                        Some(market_id),
                    );
                }
                None if adopt_unknown => {
                    self.positions.insert(
                        market_id.clone(),
                        PositionInternal {
                            venue,
                            symbol: bp.symbol.clone(),
                            qty: bp.qty,
                            avg_price: avg,
                            strategy_id: "manual".into(),
                            stop: 0.0,
                            target: 0.0,
                            trail_ref: avg,
                            live: true,
                        },
                    );
                    self.log(
                        JournalKind::Risk,
                        format!("Adopted untracked {venue:?} position: {:.6} {}", bp.qty, bp.symbol),
                        None,
                        Some(market_id),
                    );
                }
                // Someone else's position in a market we happen to watch. Not
                // ours to manage — leave it entirely alone.
                None => {}
            }
        }

        // A live position the venue does not report was closed elsewhere.
        let vanished: Vec<String> = self
            .positions
            .iter()
            .filter(|(id, p)| p.venue == venue && p.live && !seen.contains(*id))
            .map(|(id, _)| id.clone())
            .collect();
        for id in vanished {
            self.positions.remove(&id);
            self.log(
                JournalKind::Risk,
                format!("{id} is no longer held at {venue:?} — dropped from the book"),
                None,
                Some(id.clone()),
            );
        }
    }

    fn live_status(&self) -> LiveStatus {
        let mut connected: Vec<Venue> = self.connected.iter().copied().collect();
        connected.sort_by_key(|v| format!("{v:?}"));
        LiveStatus {
            armed: self.live.armed,
            paper: self.live.paper,
            dry_run: self.live.dry_run,
            venues: self.live.venues.clone(),
            timeout_sec: self.live.timeout_sec,
            alpaca_connected: self.connected.contains(&Venue::Alpaca),
            connected,
            pending: self.inflight.len(),
            live_positions: self.live_position_count(),
        }
    }

    // ── manual actions (from the UI) ────────────────────────────────────────
    pub fn manual_order(&mut self, market_id: &str, side: Side, notional: f64) {
        let Some(m) = self.markets.iter().find(|m| m.id == market_id).cloned() else { return };
        let qty = notional / m.price;
        let req = crate::connectors::OrderRequest {
            symbol: m.symbol.clone(),
            side,
            order_type: OrderType::Market,
            qty,
            limit_price: None,
            ref_price: Some(m.price),
            client_order_id: None,
            reduce_only: false,
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
        // A manual click on a live-enabled venue while armed is an intentional
        // live order — that is the whole point of the button.
        self.route_fill(idx, &m, side, decision.qty, m.price, RouteIntent::Live);
    }

    pub fn flatten(&mut self, market_id: &str) {
        let Some(pos) = self.positions.get(market_id) else { return };
        let qty = pos.qty.abs();
        let side = if pos.qty > 0.0 { Side::Sell } else { Side::Buy };
        let live = pos.live; // a live-opened position must be closed live too
        let Some(m) = self.markets.iter().find(|m| m.id == market_id).cloned() else { return };
        let idx = self.ensure_manual_strategy();
        let intent = if live { RouteIntent::LiveExit } else { RouteIntent::Paper };
        self.route_fill(idx, &m, side, qty, m.price, intent);
        if !live || self.live_routable(m.venue) {
            self.log(JournalKind::System, format!("Flattened {market_id}"), Some("manual".into()), Some(market_id.to_string()));
        }
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
                            live: p.live,
                        },
                    )
                })
                .collect(),
            strategies: self.strategies.clone(),
            orders: self.orders.clone(),
            journal: self.journal.clone(),
            limits: self.limits.clone(),
            real_ids: self.real_ids.iter().cloned().collect(),
            forecast_store: self.forecast_store.clone(),
            forecast_cfg: Some(self.forecast_cfg.clone()),
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
                        // Restored exactly as saved: a real position stays real.
                        // The daemon reconciles it against the venue on boot.
                        live: pp.live,
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
        let resolved = p.forecast_store.resolved_count();
        self.forecast_store = p.forecast_store;
        // A restored ledger has a resolution counter of its own; force a refit
        // rather than trusting a version number from a different process.
        self.scored_version = None;
        self.rescore_if_needed();
        if let Some(cfg) = p.forecast_cfg {
            self.forecast_cfg = cfg;
        }
        self.log(JournalKind::System, "Restored saved state from disk".into(), None, None);
        if resolved > 0 {
            self.log(
                JournalKind::System,
                format!("Forecast track record restored — {resolved} scored prediction(s)"),
                None,
                None,
            );
        }
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
                    // Per-position truth, not the global mode: a paper position
                    // and a real one can coexist and must look different.
                    mode: if p.live { Mode::Live } else { Mode::Paper },
                    live: p.live,
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
            forecasts: self.forecasts.clone(),
            // Only scored sources are worth showing; an all-zero row for
            // something that has never resolved is noise.
            tracks: self.track_cache.iter().filter(|t| t.score.n > 0).cloned().collect(),
            coherence: self.coherence.clone(),
            forecast_stats: ForecastStats {
                recorded: self.forecast_store.len(),
                resolved: self.forecast_store.resolved_count(),
                pending: self.forecast_store.pending_count(),
                trusted_sources: self
                    .forecast_store
                    .source_kinds()
                    .into_iter()
                    .filter(|(s, k)| self.forecast_store.trust_of(s, *k) > 0.0)
                    .count(),
            },
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
        no_price: None,
        resolves_at: None,
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
        mk("alpaca:MSFT", Venue::Alpaca, "MSFT", MarketKind::Equity, 428.0, 0.004, None, 1_200_000.0),
        mk("alpaca:AMZN", Venue::Alpaca, "AMZN", MarketKind::Equity, 186.4, 0.009, None, 1_800_000.0),
        mk("alpaca:TSLA", Venue::Alpaca, "TSLA", MarketKind::Equity, 248.5, -0.012, None, 2_600_000.0),
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
    sim.insert("alpaca:MSFT".into(), SimParam { drift: 0.000006, vol: 0.0008, base: 426.0 });
    sim.insert("alpaca:AMZN".into(), SimParam { drift: 0.00001, vol: 0.0011, base: 185.0 });
    sim.insert("alpaca:TSLA".into(), SimParam { drift: 0.000004, vol: 0.0022, base: 250.0 });
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

    /// Arm helper: Alpaca only, paper endpoint, real submission.
    fn armed_alpaca() -> LiveConfig {
        LiveConfig { armed: true, paper: true, dry_run: false, venues: vec![Venue::Alpaca], timeout_sec: 120 }
    }

    fn update(status: BrokerOrderStatus, filled: f64, price: f64) -> LiveUpdate {
        LiveUpdate { status, filled_qty: filled, avg_price: Some(price), fee: 0.0, raw_status: format!("{status:?}") }
    }

    #[test]
    fn live_routing_needs_both_the_arm_and_the_venue() {
        let mut e = Engine::new();

        // Disarmed: a manual Alpaca order fills as paper immediately, nothing queued.
        e.manual_order("alpaca:AAPL", Side::Buy, 1_000.0);
        assert!(e.drain_live_orders().is_empty());
        assert!(e.positions.contains_key("alpaca:AAPL"));
        e.flatten("alpaca:AAPL");
        assert!(e.drain_live_orders().is_empty(), "paper position flattens paper even later");

        // Arm live (paper endpoint). A manual Alpaca order now routes to the outbox
        // and does NOT open a position until the broker confirms.
        e.set_live(armed_alpaca());
        e.manual_order("alpaca:AAPL", Side::Buy, 1_000.0);
        let out = e.drain_live_orders();
        assert_eq!(out.len(), 1);
        assert_eq!(out[0].symbol, "AAPL");
        assert_eq!(out[0].venue, Venue::Alpaca);
        assert!(out[0].paper, "should target the paper endpoint");
        assert!(e.in_flight_markets.contains("alpaca:AAPL"));
        assert!(!e.positions.contains_key("alpaca:AAPL"), "no position until fill confirmed");

        // Broker acknowledges, then fills → position opens and is marked live.
        e.apply_live_ack(&out[0].order_id, "broker-1");
        e.apply_live_update(&out[0].order_id, update(BrokerOrderStatus::Filled, out[0].qty, 228.0));
        assert!(e.positions.get("alpaca:AAPL").map(|p| p.live).unwrap_or(false));
        assert!(!e.in_flight_markets.contains("alpaca:AAPL"));

        // Crypto is not in the armed venue list, so it still simulates.
        e.manual_order("crypto:BTC/USD", Side::Buy, 1_000.0);
        assert!(e.drain_live_orders().is_empty());
        assert!(e.positions.contains_key("crypto:BTC/USD"));
    }

    #[test]
    fn crypto_routes_live_once_its_venue_is_armed() {
        let mut e = Engine::new();
        e.set_live(LiveConfig { armed: true, paper: false, dry_run: false, venues: vec![Venue::Crypto], timeout_sec: 60 });
        e.manual_order("crypto:BTC/USD", Side::Buy, 1_000.0);
        let out = e.drain_live_orders();
        assert_eq!(out.len(), 1, "crypto must route when Crypto is armed");
        assert_eq!(out[0].venue, Venue::Crypto);
        assert_eq!(out[0].symbol, "BTC/USD");
        // ...and Alpaca must not, because it is not in the list.
        e.manual_order("alpaca:AAPL", Side::Buy, 1_000.0);
        assert!(e.drain_live_orders().is_empty());
    }

    #[test]
    fn partial_fills_book_once_each_not_once_per_poll() {
        let mut e = Engine::new();
        e.set_live(armed_alpaca());
        e.manual_order("alpaca:AAPL", Side::Buy, 10_000.0);
        let o = e.drain_live_orders().remove(0);
        e.apply_live_ack(&o.order_id, "b1");

        // 40% fills.
        e.apply_live_update(&o.order_id, update(BrokerOrderStatus::PartiallyFilled, o.qty * 0.4, 100.0));
        let after_first = e.positions.get("alpaca:AAPL").map(|p| p.qty).unwrap_or(0.0);
        assert!((after_first - o.qty * 0.4).abs() < 1e-9);

        // The same report arrives again (polling is repeated on purpose).
        e.apply_live_update(&o.order_id, update(BrokerOrderStatus::PartiallyFilled, o.qty * 0.4, 100.0));
        assert!(
            (e.positions.get("alpaca:AAPL").unwrap().qty - after_first).abs() < 1e-9,
            "a repeated cumulative report must not double-book"
        );

        // The rest fills; only the delta is settled.
        e.apply_live_update(&o.order_id, update(BrokerOrderStatus::Filled, o.qty, 100.0));
        assert!((e.positions.get("alpaca:AAPL").unwrap().qty - o.qty).abs() < 1e-9);
        assert!(!e.in_flight_markets.contains("alpaca:AAPL"), "terminal order frees the market");
    }

    #[test]
    fn a_cancelled_order_that_partially_filled_keeps_what_filled() {
        let mut e = Engine::new();
        e.set_live(armed_alpaca());
        e.manual_order("alpaca:NVDA", Side::Buy, 5_000.0);
        let o = e.drain_live_orders().remove(0);
        e.apply_live_ack(&o.order_id, "b2");
        e.apply_live_update(&o.order_id, update(BrokerOrderStatus::PartiallyFilled, o.qty * 0.3, 140.0));
        // Timed out → cancelled at the venue, but 30% is real.
        e.apply_live_update(&o.order_id, update(BrokerOrderStatus::Canceled, o.qty * 0.3, 140.0));

        let pos = e.positions.get("alpaca:NVDA").expect("the filled 30% is a real position");
        assert!((pos.qty - o.qty * 0.3).abs() < 1e-9);
        let ord = e.orders.iter().find(|x| x.id == o.order_id).unwrap();
        assert_eq!(ord.status, OrderStatus::Partial, "not 'cancelled' — something did fill");
    }

    #[test]
    fn a_live_position_is_never_closed_by_the_simulator() {
        let mut e = Engine::new();
        e.set_live(armed_alpaca());
        e.manual_order("alpaca:AAPL", Side::Buy, 1_000.0);
        let o = e.drain_live_orders().remove(0);
        e.apply_live_ack(&o.order_id, "b3");
        e.apply_live_update(&o.order_id, update(BrokerOrderStatus::Filled, o.qty, 228.0));
        assert!(e.positions.contains_key("alpaca:AAPL"));

        // Disarm — the shares are still at the broker.
        e.set_live(LiveConfig { armed: false, ..armed_alpaca() });
        e.flatten("alpaca:AAPL");
        assert!(
            e.positions.contains_key("alpaca:AAPL"),
            "flattening a real position while disarmed must NOT book a fake exit"
        );
        assert!(e.drain_live_orders().is_empty(), "and must not send anything either");
        assert!(
            e.journal.iter().any(|j| j.kind == JournalKind::Risk && j.message.contains("REAL position")),
            "the user has to be told why nothing happened"
        );

        // Re-arm and it exits for real.
        e.set_live(armed_alpaca());
        e.flatten("alpaca:AAPL");
        let out = e.drain_live_orders();
        assert_eq!(out.len(), 1);
        assert_eq!(out[0].side, Side::Sell);
        assert!(out[0].reduce_only, "an exit must be marked reduce-only");
    }

    #[test]
    fn a_live_stop_loss_does_not_spam_the_journal_while_disarmed() {
        let mut e = Engine::new();
        e.positions.insert(
            "alpaca:AAPL".into(),
            PositionInternal {
                venue: Venue::Alpaca,
                symbol: "AAPL".into(),
                qty: 5.0,
                avg_price: 227.0,
                strategy_id: "breakout-1".into(),
                stop: 999_999.0, // always triggering
                target: 0.0,
                trail_ref: 227.0,
                live: true,
            },
        );
        for _ in 0..5 {
            e.check_position_exits();
        }
        let warnings = e
            .journal
            .iter()
            .filter(|j| j.message.contains("REAL position"))
            .count();
        assert_eq!(warnings, 1, "one warning per minute, not one per tick");
        assert!(e.positions.contains_key("alpaca:AAPL"), "and the position stays open");
    }

    #[test]
    fn poll_list_asks_for_a_cancel_once_the_timeout_passes() {
        let mut e = Engine::new();
        e.set_live(LiveConfig { timeout_sec: 15, ..armed_alpaca() });
        e.manual_order("alpaca:MSFT", Side::Buy, 1_000.0);
        let o = e.drain_live_orders().remove(0);

        // Nothing to poll until the venue acknowledges it.
        assert!(e.live_polls().is_empty());
        e.apply_live_ack(&o.order_id, "b4");

        let polls = e.live_polls();
        assert_eq!(polls.len(), 1);
        assert!(!polls[0].cancel, "a fresh order is not overdue");
        assert_eq!(polls[0].broker_id, "b4");

        // Age it past the timeout.
        e.inflight.get_mut(&o.order_id).unwrap().submitted_at -= 20_000;
        assert!(e.live_polls()[0].cancel, "an overdue order must be cancelled at the venue");

        // Once the cancel is out we stop re-sending it.
        e.mark_cancel_sent(&o.order_id);
        assert!(!e.live_polls()[0].cancel);
    }

    #[test]
    fn a_rejected_submission_frees_the_market_for_the_next_signal() {
        let mut e = Engine::new();
        e.set_live(armed_alpaca());
        e.manual_order("alpaca:TSLA", Side::Buy, 1_000.0);
        let o = e.drain_live_orders().remove(0);
        assert!(e.in_flight_markets.contains("alpaca:TSLA"));

        e.apply_live_reject(&o.order_id, "US market closed — next open 2026-07-27T13:30:00Z");
        assert!(!e.in_flight_markets.contains("alpaca:TSLA"));
        assert!(e.live_polls().is_empty());
        assert!(!e.positions.contains_key("alpaca:TSLA"), "a refused order is not a position");
        let ord = e.orders.iter().find(|x| x.id == o.order_id).unwrap();
        assert_eq!(ord.status, OrderStatus::Rejected);
        assert!(ord.reject_reason.as_deref().unwrap().contains("market closed"));
    }

    #[test]
    fn a_refused_market_backs_off_instead_of_retrying_every_tick() {
        let mut e = Engine::new();
        e.set_live(armed_alpaca());
        e.manual_order("alpaca:TSLA", Side::Buy, 1_000.0);
        let o = e.drain_live_orders().remove(0);
        e.apply_live_reject(&o.order_id, "US market closed");

        // The same signal fires again immediately — it must not resend.
        e.manual_order("alpaca:TSLA", Side::Buy, 1_000.0);
        assert!(e.drain_live_orders().is_empty(), "a closed market must not get one order per tick");

        // A different market is unaffected.
        e.manual_order("alpaca:AAPL", Side::Buy, 1_000.0);
        assert_eq!(e.drain_live_orders().len(), 1);

        // Once the backoff expires it tries again — the market may have opened.
        e.live_backoff_until.insert("alpaca:TSLA".into(), 0);
        e.manual_order("alpaca:TSLA", Side::Buy, 1_000.0);
        assert_eq!(e.drain_live_orders().len(), 1, "backoff must expire, not latch");
    }

    #[test]
    fn every_market_gets_a_forecast_and_it_starts_equal_to_the_market() {
        let mut e = Engine::new();
        e.update_forecasts();
        assert_eq!(e.forecasts.len(), e.markets.len());

        // With no track record, no source may pull away from the price.
        for f in &e.forecasts {
            assert_eq!(f.action, forecast::Action::Hold, "{} should not trade on day one", f.market_id);
            assert!(f.trust < 0.3, "{} trust {}", f.market_id, f.trust);
        }
        // Prediction markets get a model probability; price markets do not.
        let pred = e.markets.iter().find(|m| m.kind == MarketKind::Prediction).unwrap();
        assert!(pred.model_prob.is_some());
    }

    #[test]
    fn forecasts_are_recorded_so_they_can_be_scored_later() {
        let mut e = Engine::new();
        e.update_forecasts();
        let st = e.state();
        assert!(st.forecast_stats.recorded > 0, "nothing recorded means nothing can be learned");
        assert_eq!(st.forecast_stats.resolved, 0, "nothing has had time to resolve");
        assert_eq!(st.forecast_stats.trusted_sources, 0, "and nothing is trusted yet");
    }

    /// Not a correctness test — a stopwatch on the hot path, kept so the cost of
    /// a forecast sweep stays visible. Run it with:
    /// `cargo test --release -p pythia-core -- --ignored --nocapture bench_`
    #[test]
    #[ignore]
    fn bench_forecast_sweep() {
        let mut e = Engine::new();
        // Build a realistic ledger: a few thousand resolved forecasts.
        for _ in 0..40 {
            e.update_forecasts();
            let horizon = e.forecast_cfg.horizon_ms;
            for r in e.forecast_store.records_mut() {
                r.resolve_at -= horizon * 2;
            }
        }
        e.update_forecasts();
        println!(
            "ledger: {} records, {} resolved, {} scored sources",
            e.forecast_store.len(),
            e.forecast_store.resolved_count(),
            e.track_cache.len()
        );

        let t = std::time::Instant::now();
        for _ in 0..20 {
            e.update_forecasts();
        }
        println!("20 sweeps, nothing resolving: {:?}", t.elapsed());

        let t = std::time::Instant::now();
        for _ in 0..20 {
            e.scored_version = None; // force the refit the cache normally avoids
            e.update_forecasts();
        }
        println!("20 sweeps, refitting every time: {:?}", t.elapsed());

        let t = std::time::Instant::now();
        for _ in 0..100 {
            let _ = e.state();
        }
        println!("100 state() snapshots: {:?}", t.elapsed());
    }

    #[test]
    fn the_scoreboard_is_not_refitted_when_nothing_has_resolved() {
        // Forecasts are recorded on every sweep; resolutions arrive on the order
        // of hours. Refitting a logistic regression per source per market per
        // tick for numbers that cannot have changed was the one real hotspot.
        let mut e = Engine::new();
        e.update_forecasts();
        let v = e.scored_version;
        assert!(v.is_some(), "the first pass must score");

        for _ in 0..5 {
            e.update_forecasts();
        }
        assert_eq!(e.scored_version, v, "no resolutions → no refit");

        // Age the ledger past the horizon so something actually resolves.
        let horizon = e.forecast_cfg.horizon_ms;
        for r in e.forecast_store.records_mut() {
            r.resolve_at -= horizon * 2;
        }
        e.update_forecasts();
        assert_ne!(e.scored_version, v, "a resolution must trigger a refit");
    }

    /// The wire contract the whole frontend depends on. A field that serialises
    /// under the wrong name is invisible in Rust and silently `undefined` in the
    /// UI, which is the worst combination available.
    #[test]
    fn engine_state_serialises_in_the_camel_case_the_frontend_expects() {
        let mut e = Engine::new();
        e.update_forecasts();
        let v = serde_json::to_value(e.state()).unwrap();
        let obj = v.as_object().unwrap();
        for key in ["portfolio", "markets", "positions", "orders", "journal", "strategies",
                    "limits", "history", "live", "forecasts", "tracks", "coherence", "forecastStats"] {
            assert!(obj.contains_key(key), "EngineState is missing `{key}` on the wire");
        }
        assert!(!obj.contains_key("forecast_stats"), "snake_case must not leak to the UI");
        assert!(v["forecastStats"]["trustedSources"].is_number());
        assert!(v["forecastStats"]["recorded"].as_u64().unwrap() > 0);
    }

    #[test]
    fn a_prediction_market_signal_is_dropped_when_the_edge_does_not_clear_costs() {
        let mut e = Engine::new();
        e.update_forecasts();
        // Nothing is actionable on a fresh engine, so Prob-Edge cannot fire even
        // though the seeded markets carry a model probability.
        assert!(e.actionable.is_empty());

        // Force a market to be actionable and the gate opens.
        e.actionable.insert("polymarket:fed-cut-2026".into());
        assert!(e.actionable.contains("polymarket:fed-cut-2026"));
    }

    #[test]
    fn model_opinions_flow_into_the_forecast_and_are_journaled() {
        let mut e = Engine::new();
        let sig = crate::llm::Signal {
            probability: 0.85,
            direction: crate::llm::Direction::Long,
            confidence: 0.7,
            rationale: "test".into(),
            base_rate: Some(0.3),
            key_drivers: vec!["rates".into()],
            evidence_for: vec![],
            evidence_against: vec![],
            provider: "anthropic".into(),
            model: "claude-opus-4-8".into(),
        };
        e.apply_llm_opinions("polymarket:fed-cut-2026", vec![sig]);

        let f = e
            .forecasts
            .iter()
            .find(|f| f.market_id == "polymarket:fed-cut-2026")
            .expect("forecast rebuilt on the spot");
        assert!(f.sources.iter().any(|s| s.source == "llm:anthropic"));
        assert!(e.journal.iter().any(|j| j.message.contains("model opinion")));
    }

    #[test]
    fn stale_model_opinions_are_dropped_rather_than_used() {
        let mut e = Engine::new();
        let sig = crate::llm::Signal {
            probability: 0.85, direction: crate::llm::Direction::Long, confidence: 0.7,
            rationale: "old".into(), base_rate: None, key_drivers: vec![],
            evidence_for: vec![], evidence_against: vec![],
            provider: "anthropic".into(), model: "m".into(),
        };
        e.apply_llm_opinions("polymarket:fed-cut-2026", vec![sig]);
        // Backdate it past the TTL.
        if let Some(entry) = e.llm_opinions.get_mut("polymarket:fed-cut-2026") {
            entry.0 -= Engine::LLM_TTL_MS + 1;
        }
        e.update_forecasts();

        let f = e.forecasts.iter().find(|f| f.market_id == "polymarket:fed-cut-2026").unwrap();
        assert!(
            !f.sources.iter().any(|s| s.source == "llm:anthropic"),
            "a view formed before the market moved is not a view about this market"
        );
    }

    #[test]
    fn the_forecast_track_record_survives_a_restart() {
        let mut e = Engine::new();
        e.update_forecasts();
        let recorded = e.forecast_store.len();
        assert!(recorded > 0);

        let json = serde_json::to_string(&e.to_persisted()).unwrap();
        let mut e2 = Engine::new();
        e2.apply_persisted(serde_json::from_str(&json).unwrap());
        assert_eq!(
            e2.forecast_store.len(),
            recorded,
            "losing the ledger would silence every source back to unproven"
        );
    }

    #[test]
    fn a_coherence_break_is_detected_on_a_binary_market_that_does_not_sum_to_one() {
        let mut e = Engine::new();
        // Give the seeded prediction market a NO price that leaves a 4-point gap.
        if let Some(m) = e.markets.iter_mut().find(|m| m.id == "polymarket:fed-cut-2026") {
            m.price = 0.60;
            m.no_price = Some(0.36);
        }
        e.update_forecasts();
        let b = e
            .coherence
            .iter()
            .find(|b| b.event_id == "polymarket:fed-cut-2026")
            .expect("0.60 + 0.36 = 0.96 is a 400bps gap");
        assert!(b.actionable, "buying both sides needs no shorting");
        assert!(e.journal.iter().any(|j| j.message.contains("Coherence break")));
    }

    #[test]
    fn a_repeated_feed_refresh_is_announced_once() {
        let mut e = Engine::new();
        let feed = [crate::marketdata::RealCrypto {
            id: "crypto:BTC/USD".into(),
            symbol: "BTC/USD".into(),
            price: 67_000.0,
            change24h: 0.01,
        }];
        for _ in 0..5 {
            e.apply_kraken(&feed);
        }
        let notices = e.journal.iter().filter(|j| j.message.contains("Kraken feed")).count();
        assert_eq!(notices, 1, "a 12-second heartbeat would bury the fills");
    }

    #[test]
    fn reconciliation_lets_the_broker_win() {
        let mut e = Engine::new();
        // Book says 10 AAPL live; broker says 4.
        e.positions.insert(
            "alpaca:AAPL".into(),
            PositionInternal {
                venue: Venue::Alpaca, symbol: "AAPL".into(), qty: 10.0, avg_price: 220.0,
                strategy_id: "manual".into(), stop: 0.0, target: 0.0, trail_ref: 220.0, live: true,
            },
        );
        e.reconcile_positions(
            Venue::Alpaca,
            &[BrokerPosition { symbol: "AAPL".into(), qty: 4.0, avg_price: 225.0, market_value: 900.0 }],
            false,
        );
        let p = e.positions.get("alpaca:AAPL").unwrap();
        assert_eq!(p.qty, 4.0);
        assert_eq!(p.avg_price, 225.0);

        // And one the broker no longer has is dropped.
        e.reconcile_positions(Venue::Alpaca, &[], false);
        assert!(e.positions.is_empty());
    }

    #[test]
    fn reconciliation_does_not_adopt_someone_elses_position_by_default() {
        let mut e = Engine::new();
        let held = [BrokerPosition { symbol: "NVDA".into(), qty: 500.0, avg_price: 90.0, market_value: 69_000.0 }];

        // The user's own long-term NVDA is not Pythia's to put a stop under.
        e.reconcile_positions(Venue::Alpaca, &held, false);
        assert!(e.positions.is_empty(), "untracked broker positions stay untracked");

        // Opt in explicitly and it is taken over.
        e.reconcile_positions(Venue::Alpaca, &held, true);
        assert_eq!(e.positions.get("alpaca:NVDA").map(|p| p.qty), Some(500.0));
    }

    #[test]
    fn reconciliation_leaves_paper_positions_alone() {
        let mut e = Engine::new();
        e.manual_order("alpaca:AAPL", Side::Buy, 1_000.0); // paper fill
        assert!(e.positions.contains_key("alpaca:AAPL"));
        // The broker reports nothing — which is correct, this was never real.
        e.reconcile_positions(Venue::Alpaca, &[], false);
        assert!(
            e.positions.contains_key("alpaca:AAPL"),
            "a simulated position must not be wiped by broker reconciliation"
        );
    }

    #[test]
    fn arming_with_no_venues_routes_nothing() {
        let mut e = Engine::new();
        e.set_live(LiveConfig { armed: true, paper: true, dry_run: false, venues: vec![], timeout_sec: 60 });
        e.manual_order("alpaca:AAPL", Side::Buy, 1_000.0);
        assert!(e.drain_live_orders().is_empty(), "armed but with no venue enabled is still safe");
        assert!(e.positions.contains_key("alpaca:AAPL"), "it simulates instead");
    }

    #[test]
    fn the_order_timeout_is_clamped_to_something_workable() {
        let mut e = Engine::new();
        e.set_live(LiveConfig { timeout_sec: 0, ..armed_alpaca() });
        assert!(e.live_config().timeout_sec >= 15, "0s would cancel every order before it could fill");
        e.set_live(LiveConfig { timeout_sec: 99_999, ..armed_alpaca() });
        assert!(e.live_config().timeout_sec <= 900);
    }

    #[test]
    fn the_live_flag_survives_a_save_and_reload() {
        let mut e = Engine::new();
        e.positions.insert(
            "alpaca:AAPL".into(),
            PositionInternal {
                venue: Venue::Alpaca, symbol: "AAPL".into(), qty: 3.0, avg_price: 227.0,
                strategy_id: "manual".into(), stop: 0.0, target: 0.0, trail_ref: 227.0, live: true,
            },
        );
        let json = serde_json::to_string(&e.to_persisted()).unwrap();
        let mut e2 = Engine::new();
        e2.apply_persisted(serde_json::from_str(&json).unwrap());
        assert!(
            e2.positions.get("alpaca:AAPL").map(|p| p.live).unwrap_or(false),
            "forgetting this across a restart would let the simulator close real shares"
        );
    }
}
