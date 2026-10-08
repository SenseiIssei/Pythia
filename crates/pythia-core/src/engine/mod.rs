//! Engine core (Phase 1). A persistent portfolio + sovereign risk manager +
//! strategy runtime that ticks on the Tokio runtime and pushes a full
//! [`EngineState`] snapshot to the UI each tick. This is the Rust owner of the
//! same model the browser build runs in TypeScript.

pub mod autopilot;
#[cfg(test)]
mod autopilot_tests;
pub mod composed;
#[cfg(test)]
mod feed_engine_tests;
pub mod indicators;
pub mod risk;
#[cfg(test)]
mod risk_engine_tests;
pub mod strategies;

use crate::connectors::{BrokerOrderStatus, BrokerPosition, OrderType, Side, Venue};
use crate::costs::{self, CostModel, CostVenue};
use crate::execution::bandit;
pub use crate::execution::bandit::FillRoute;
use crate::feeds::{self, DataKind, FeedConfig, FeedSource};
use crate::forecast::{self, calibration, coherence, track};
use crate::validation;
use crate::marketdata::{BarSeries, Ohlc, RealCrypto, RealEquity, RealPrediction};
use crate::orderbook::{BookQuote, BookSnapshot, CostSource, ExecCost};
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
    /// Orders go to the venue's demo environment (`RouteIntent::Demo`): real
    /// API round trips, virtual money. Needs demo keys, not the live arm and
    /// not a green passport.
    Demo,
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
    /// Target weights decided in the research lab and executed here (see `crate::lab`).
    LabTargets,
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
    /// Held via a demo-venue fill (virtual money). Its exits route to the
    /// same demo environment.
    #[serde(default)]
    pub demo: bool,
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
    /// Fill price against the arrival (signal) price, in bps, signed so
    /// positive means it cost us. Live and demo fills once the order is done,
    /// paper fills at once.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub realised_slippage_bps: Option<f64>,
    /// What the cost model expected that to be.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub modelled_slippage_bps: Option<f64>,
    /// Where the fill came from: Pythia's simulator (`paper`), a venue's demo
    /// environment (`demo`, virtual money, never taxed) or a real venue
    /// (`live`). Rows saved before routes existed load as paper.
    #[serde(default = "paper_route")]
    pub route: FillRoute,
    /// Whether the modelled cost (and, for paper, the fill itself) used a
    /// fresh live book or the calibrated default.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub cost_source: Option<CostSource>,
    /// The book's mid against the signal price when the order was priced, in
    /// bps, positive when the market had moved against the order.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub drift_bps: Option<f64>,
    /// A paper fill that outgrew the 20 book levels; the rest was priced by
    /// the impact model.
    #[serde(default, skip_serializing_if = "std::ops::Not::not")]
    pub book_exhausted: bool,
}

fn paper_route() -> FillRoute {
    FillRoute::Paper
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
    /// What this strategy has paid to trade, and the forward-test evidence the
    /// Strategy Passport is judged on.
    #[serde(default)]
    pub ledger: StrategyLedger,
}

/// Costs and forward-test record for one strategy.
///
/// `StrategyConfig::pnl` is realised P&L at the actual fill prices, so it
/// already has slippage in it and no fees taken out. The engine also tracks
/// every position at reference prices (the quote before execution costs), so
/// the strategy can be shown as gross, costs and net that describe the same
/// closed trades (see [`StrategyLedger::breakdown`]).
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct StrategyLedger {
    /// Fees paid, in quote currency.
    pub fees: f64,
    /// Slippage paid against the reference price on every fill so far, open
    /// positions included, in quote currency. Live fills can make this go
    /// down: a fill better than arrival is negative slippage.
    pub slippage: f64,
    /// Realised P&L of the same trades at reference prices: what they would
    /// have made with no fees, spread or impact.
    #[serde(default)]
    pub gross: f64,
    /// Gross, costs and net in quote currency, kept in step with `fees`,
    /// `slippage` and the strategy's realised P&L.
    pub pnl: crate::costs::PnlBreakdown,
    /// When the paper forward test started (epoch ms). Set the first time the
    /// strategy runs in paper or live, never reset.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub paper_since: Option<i64>,
    /// Closed paper trades on markets with real prices. Trades on the demo
    /// simulator are not evidence of anything and are not counted.
    pub forward_trades: u32,
    /// Closed trades filled for real at a venue (paper endpoint included).
    pub live_trades: u32,
    /// Closed trades filled by a venue's demo environment. Also counted in
    /// `forward_trades`: they are forward-test evidence on real prices.
    #[serde(default)]
    pub demo_trades: u32,
    /// Win rate and payoff in net returns on notional, which entries are
    /// sized on once there are 30 trades (see [`risk::edge_sizing`]).
    #[serde(default)]
    pub edge: risk::EdgeRecord,
}

impl StrategyLedger {
    /// Gross, costs and net for a realised P&L at fill prices.
    ///
    /// `gross` is the closed trades at reference prices, `net` is the realised
    /// P&L at fill prices minus every fee paid, and costs are the difference:
    /// the slippage on closed trades plus fees. Fees are booked when paid, so an
    /// open position's entry fee shows up before its P&L does.
    pub fn breakdown(&self, realised_pnl: f64) -> crate::costs::PnlBreakdown {
        let net = realised_pnl - self.fees;
        crate::costs::PnlBreakdown::new(self.gross, self.gross - net)
    }
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
    /// Cap on correlation-adjusted exposure, `sqrt(w' C w)`, in % of equity
    /// (0 = off). See [`risk::correlated_exposure`]. Defaulted so saves from
    /// before it existed still load.
    #[serde(default = "default_max_correlated_exposure_pct")]
    pub max_correlated_exposure_pct: f64,
    /// Ceiling on the whole book's volatility: one standard deviation of a
    /// year's P&L, in % of equity (0 = off). See [`risk::portfolio_vol`].
    #[serde(default = "default_portfolio_vol_target_pct")]
    pub portfolio_vol_target_pct: f64,
    /// Trim the whole book back to `portfolio_vol_target_pct` once its
    /// volatility has stayed above this many times the target for 30 minutes
    /// (0 = off). Closing only. See [`risk::VolSpikeGuard`].
    #[serde(default)]
    pub vol_spike_trim_mult: f64,
}

fn default_max_correlated_exposure_pct() -> f64 {
    40.0
}

fn default_portfolio_vol_target_pct() -> f64 {
    30.0
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
            // Below the 70% gross cap on purpose: a book that moves as one
            // stops at 40%, an uncorrelated one is held by the gross cap.
            max_correlated_exposure_pct: default_max_correlated_exposure_pct(),
            // A crypto book swings 60-90 % a year; 30 % keeps a bad month
            // (two standard deviations) near 17 % of equity. Above the
            // lab books' own share of that, so it does not fight them.
            portfolio_vol_target_pct: default_portfolio_vol_target_pct(),
            // Off: selling into a spike is a decision with a cost (it sells
            // after the move), so it is the operator's to switch on.
            vol_spike_trim_mult: 0.0,
        }
    }
}

#[derive(Debug, Clone)]
pub struct RiskDecision {
    pub approved: bool,
    pub qty: f64,
    pub reason: Option<String>,
}

/// What the broker says about the session and the account, refreshed by the
/// daemon. The engine is synchronous and does no I/O, so it cannot ask — but it
/// must not route a live order without an answer, so a stale or absent status
/// blocks live routing rather than defaulting to "probably fine".
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct BrokerStatus {
    pub market_open: bool,
    /// Inside the pre-market / after-hours session (typically 04:00–20:00 ET).
    /// Always true during regular hours.
    #[serde(default)]
    pub extended_open: bool,
    /// Exchange-local end of today's extended session, when one is running.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub session_end: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub next_open: Option<String>,
    /// FINRA pattern-day-trader ceiling reached (3 day trades in 5 sessions
    /// under $25k of equity). A 4th flags the account and locks it for 90 days.
    pub day_trade_limit_reached: bool,
    /// Set when the account itself refuses orders (blocked, not yet active…).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub restricted: Option<String>,
    pub equity: f64,
    pub buying_power: f64,
    /// Epoch millis of the last successful refresh.
    pub checked_at: i64,
}

/// How old a [`BrokerStatus`] may be before live routing refuses to trust it.
const BROKER_STATUS_MAX_AGE_MS: i64 = 5 * 60 * 1000;

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
    /// Allow Alpaca entries during the pre-market / after-hours session. Off by
    /// default: those sessions are thin, spreads are wide, and a strategy
    /// validated on regular-hours candles has no evidence behind it there.
    /// Only takes effect when the broker itself reports a session running.
    #[serde(default)]
    pub extended_hours: bool,
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
            extended_hours: false,
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
    /// Allow Alpaca entries during the pre-market / after-hours session.
    pub extended_hours: bool,
    /// Kept for the existing UI: Alpaca specifically has keys.
    pub alpaca_connected: bool,
    /// Live orders currently awaiting a broker response.
    pub pending: usize,
    /// Positions currently held via a real venue fill. These cannot be closed
    /// by the simulator, so the UI has to make them obvious.
    pub live_positions: usize,
    /// Last Alpaca session/account snapshot, if one has been fetched.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub broker: Option<BrokerStatus>,
    /// Why live routing would refuse an Alpaca equity entry right now; `None`
    /// when the path is clear. Surfaced so the UI can explain an idle armed
    /// engine.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub blocked_reason: Option<String>,
    /// Venues whose demo environment has keys. Demo routing needs only this,
    /// not `armed`.
    #[serde(default)]
    pub demo_venues: Vec<Venue>,
    /// The exchange crypto demo orders go to.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub demo_exchange: Option<CostVenue>,
    /// Open positions opened by demo fills.
    #[serde(default)]
    pub demo_positions: usize,
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
    /// Send it to the venue's DEMO environment: the real connector path
    /// (signing, sizing rules, preflight, rejects, latency, partial fills,
    /// status polling) against virtual money. Booked in the paper ledger at
    /// the price the venue reported, marked demo on the order and position,
    /// never in the tax record. Needs demo keys for the venue (see
    /// [`Engine::set_demo_venues`]); does NOT need the live arm. Still passes
    /// the risk manager like every other order. Exits of a demo position use
    /// this intent too. See `docs/DEMO.md` for how other modules send one
    /// ([`Engine::place_order`]).
    Demo,
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
    /// This order reduces or closes an existing position; it must not flip it.
    /// The connector also needs it to tell a legitimate fractional *exit* from
    /// an illegal fractional *short entry*, which Alpaca refuses.
    pub reduce_only: bool,
    /// How hard to push, chosen by the execution policy.
    pub style: bandit::ExecStyle,
    /// How far inside the arrival price a passive order rests.
    pub patience_bps: f64,
    /// Snapshot of the arm config at enqueue time.
    pub paper: bool,
    pub dry_run: bool,
    /// Submit into the pre-market / after-hours session. Forces a whole-share
    /// limit order — the only shape Alpaca accepts outside regular hours.
    pub extended_hours: bool,
    /// Route to the venue's demo environment with its demo keys
    /// ([`RouteIntent::Demo`]). The daemon builds the demo connector from
    /// this flag alone; `paper` and `dry_run` belong to the live arm.
    #[serde(default)]
    pub demo: bool,
}

// ── AI overlay ──────────────────────────────────────────────────────────────
//
// The hard rule, and the reason this is a multiplier rather than a strategy:
// **a model may shrink or veto a trade, never create one.** Every order still
// originates from a rule that can be backtested, and still passes the risk
// manager. An LLM cannot be walk-forward validated, its output is not
// stationary across model versions, and it will produce a confident answer to a
// question it has no edge on. Letting one pull the trigger would mean trading
// an unmeasurable, unreproducible signal with real money.

/// One model's view of one market, with the timestamp that decides its decay.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct AiView {
    pub market_id: String,
    /// "long" | "short" | "neutral"
    pub direction: String,
    pub probability: f64,
    pub confidence: f64,
    pub rationale: String,
    pub model: String,
    pub ts: i64,
    pub latency_ms: u64,
}

/// How much authority the overlay is granted. Off by default.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct AiPolicy {
    pub enabled: bool,
    /// A view older than this is ignored outright. Opinions about a market go
    /// stale faster than most people expect.
    pub ttl_sec: u64,
    /// Confidence at or above which active disagreement blocks the entry.
    pub veto_confidence: f64,
    /// Ceiling on the size multiplier when the model agrees. Deliberately
    /// modest — an agreeing model is weak evidence, not a green light.
    pub max_boost: f64,
}

impl Default for AiPolicy {
    fn default() -> Self {
        Self { enabled: false, ttl_sec: 900, veto_confidence: 0.7, max_boost: 1.25 }
    }
}

/// Per-market answer to "why hasn't this traded?".
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct MarketDiag {
    pub market_id: String,
    pub symbol: String,
    pub price: f64,
    /// Candles available to the indicators.
    pub bars: usize,
    pub bar_backed: bool,
    /// Seconds since the last real quote. The risk manager rejects orders on
    /// data older than `max_data_staleness_sec`.
    pub quote_age_sec: u64,
    pub has_position: bool,
    /// Strategies whose universe includes this market.
    pub watchers: Vec<String>,
    /// How many of those are actually in the Live state.
    pub live_watchers: usize,
    /// What a live strategy would do right now, if anything.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub signal: Option<String>,
    /// The first gate that would stop an order. `None` means the path is clear.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub suppressed: Option<String>,
}

/// Running cost of the overlay, so the bill is visible in the cockpit rather
/// than discovered on an invoice.
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct AiSpend {
    pub calls: u64,
    pub input_tokens: u64,
    pub output_tokens: u64,
    pub errors: u64,
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
    /// Ask the demo environment, with the demo keys.
    #[serde(default)]
    pub demo: bool,
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
///
/// Saved with the engine state: an order resting at a broker outlives the
/// process, and a restart that forgot it left its row "Pending" for good and
/// never booked a fill that landed while Pythia was down. Restored entries are
/// polled like any other (see [`Engine::apply_persisted`]).
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct InFlight {
    market_id: String,
    symbol: String,
    venue: Venue,
    side: Side,
    strategy_id: String,
    /// `None` until the venue acknowledges the submission.
    broker_id: Option<String>,
    /// The id the order was sent under, so a person can find it at the venue
    /// when it was never acknowledged. Empty in saves from before it was kept.
    #[serde(default)]
    client_order_id: String,
    submitted_at: i64,
    /// How much of the venue's cumulative fill we have already booked. The
    /// difference against a fresh report is exactly what still needs settling,
    /// which is what makes partial fills safe to apply repeatedly.
    booked_qty: f64,
    booked_fee: f64,
    paper: bool,
    cancel_sent: bool,
    /// Price at the moment the execution style was chosen. Realised slippage is
    /// measured against this, not against the fill — otherwise every order looks
    /// perfectly executed.
    arrival: f64,
    style: bandit::ExecStyle,
    exec_ctx: bandit::ExecContext,
    /// Whose costs apply, and what the cost model expected this order's
    /// slippage to be. Compared against the realised number when it finishes.
    cost_venue: CostVenue,
    modelled_bps: f64,
    /// Whether `modelled_bps` used a live book; kept with the fill record.
    cost_source: CostSource,
    /// Sent to the venue's demo environment (`RouteIntent::Demo`).
    #[serde(default)]
    demo: bool,
    /// The book's mid against the arrival price when the order was sent, in
    /// bps signed against us; `None` without a fresh book.
    #[serde(default)]
    drift_bps: Option<f64>,
}

impl InFlight {
    /// What this order's fills are, for every label and record: demo when
    /// sent to a demo environment or to Alpaca's paper endpoint (both are
    /// virtual money), live otherwise.
    fn route(&self) -> FillRoute {
        if self.demo || self.paper {
            FillRoute::Demo
        } else {
            FillRoute::Live
        }
    }
}

/// The full state pushed to the UI every tick.
///
/// camelCase like every other DTO here. Most fields are single words so the
/// rename is invisible, but `forecast_stats`, `bar_backed`, `ai_views` and the
/// like are not, and without this they would reach the frontend under names
/// the TypeScript type does not have.
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
    /// Bar open times for the closes in `history`, for bar-backed markets
    /// only, so the Correlation page aligns candles on time the way the risk
    /// manager does (see [`risk::PriceSeries`]). A market missing here is on ticks.
    #[serde(default)]
    pub history_ts: HashMap<String, Vec<i64>>,
    pub live: LiveStatus,
    /// Market ids whose indicators run on real candles rather than the simulator.
    #[serde(default)]
    pub bar_backed: Vec<String>,
    #[serde(default)]
    pub ai_views: Vec<AiView>,
    #[serde(default)]
    pub ai_policy: AiPolicy,
    #[serde(default)]
    pub ai_spend: AiSpend,
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
    /// What adaptive execution has learned, per (venue+urgency, style).
    #[serde(default)]
    pub execution: Vec<bandit::PolicyRow>,
    #[serde(default)]
    pub adaptive_execution: bool,
    /// Realised against modelled slippage per venue, once there are live fills.
    #[serde(default)]
    pub slippage: Vec<bandit::SlippageRow>,
    /// Whose costs `Venue::Crypto` is charged.
    #[serde(default = "default_crypto_venue")]
    pub crypto_cost_venue: CostVenue,
    /// The Strategy Passport of every strategy: the eight validation gates.
    #[serde(default)]
    pub passports: Vec<validation::Passport>,
    /// Correlation-adjusted exposure, drawdown de-risking and how each
    /// strategy is being sized, for the Risk page.
    #[serde(default)]
    pub risk: risk::RiskStatus,
    /// Which source each kind of crypto data comes from, how fresh it is,
    /// failovers and stale markets (see [`crate::feeds`]).
    #[serde(default)]
    pub data_health: Option<feeds::DataHealth>,
    /// Every autopilot: running, paused, and the most recent stopped ones.
    #[serde(default)]
    pub autopilots: Vec<autopilot::AutopilotStatus>,
}

fn default_crypto_venue() -> CostVenue {
    CostVenue::Kraken
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
    /// Opened with a demo-venue fill; its exits go back to the demo venue.
    #[serde(default)]
    pub demo: bool,
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
    /// Which lab signal each lab book was last rebalanced to, so a restart does
    /// not trade the same decision twice.
    #[serde(default)]
    pub lab_done: HashMap<String, i64>,
    #[serde(default)]
    pub forecast_cfg: Option<forecast::ForecastConfig>,
    /// What the execution policy has learned. A bandit that forgets on restart
    /// never gets past exploring.
    #[serde(default)]
    pub exec_policy: bandit::ExecPolicy,
    /// Cached validation gates 1 to 6 per strategy.
    #[serde(default)]
    pub research: HashMap<String, validation::ResearchVerdict>,
    /// Reference-price entry per open position, for the gross line.
    #[serde(default)]
    pub ref_prices: HashMap<String, f64>,
    /// The id counter. Without it every restart handed out `ord_1`, `j_1` and
    /// so on again, next to the restored orders and journal that already had them.
    #[serde(default)]
    pub seq: u64,
    /// The drawdown breaker's peak and the UTC day the daily counters belong
    /// to. Without them a restart measured the drawdown from the starting
    /// balance and skipped the daily reset when it fell on a new day.
    #[serde(default)]
    pub peak_equity: f64,
    #[serde(default)]
    pub day: i64,
    /// Last price and its time (epoch ms) per market with a real feed. Markets
    /// are re-seeded on load; without this a position was valued, and its stop
    /// checked, at the seed price until the first feed refresh.
    #[serde(default)]
    pub prices: HashMap<String, (f64, i64)>,
    /// Live orders not finished yet, by engine order id: the ones the venue
    /// acknowledged are polled again after a restart until they fill, cancel
    /// or are rejected. Orders still waiting for submission are saved here
    /// too (no broker id) so the restart can close their rows honestly.
    #[serde(default)]
    pub inflight: Vec<(String, InFlight)>,
    /// Autopilots with their peak, floor and owned positions, so a restart
    /// can never reset a stop rule.
    #[serde(default)]
    pub autopilots: Vec<autopilot::Autopilot>,
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
    demo: bool,     // opened via a demo-venue fill: its exits route to the same demo world
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

/// A lab rebalance with refused orders is tried again this often, at most
/// `LAB_RETRY_MAX` times in all: six attempts over 1 h 40 min, well inside a
/// signal's 36-hour validity, then the rest waits for the next signal.
const LAB_RETRY_EVERY_MS: i64 = 20 * 60_000;
const LAB_RETRY_MAX: u32 = 6;

pub struct Engine {
    markets: Vec<Market>,
    sim: HashMap<String, SimParam>,
    history: HashMap<String, Vec<f64>>, // rolling close-price history per market
    /// Real candles per market, oldest first. Present only for markets fed by a
    /// live bar feed; the source of truth for indicators on those markets.
    ohlc: HashMap<String, Vec<Ohlc>>,
    /// Markets whose `history` is real candles rather than the tick simulator.
    /// The tick loop must never append to these — mixing a 1.5s random walk into
    /// a 5-minute candle series produces indicators that measure nothing.
    bar_backed: std::collections::HashSet<String>,
    /// Open time of the newest *closed* bar per market, for new-bar detection.
    last_bar_ts: HashMap<String, i64>,
    /// Bar we last emitted a signal on, per market — throttles bar-backed
    /// strategies to at most one entry per candle.
    signalled_bar: HashMap<String, i64>,
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
    broker: Option<BrokerStatus>,        // Alpaca session/account snapshot from the daemon
    ai: HashMap<String, AiView>,         // latest model view per market
    ai_policy: AiPolicy,
    ai_spend: AiSpend,
    /// Venues whose demo environment has keys, set by the host from its
    /// credentials. Demo routing needs this and nothing from `live`.
    demo_venues: HashSet<Venue>,
    /// The exchange `Venue::Crypto` demo orders go to (its costs price the
    /// modelled side of a demo fill), and whether it documents real prices.
    crypto_demo_venue: Option<CostVenue>,
    crypto_demo_real_prices: bool,
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
    /// Pairwise error correlation between sources. Same cache key — it can only
    /// change when something resolves.
    correlations: track::ErrorCorrelations,
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
    /// Learns how hard to push on each order from its own realised slippage.
    /// Ships disabled — every order crosses until the operator turns it on.
    exec_policy: bandit::ExecPolicy,
    /// Which exchange's costs apply to `Venue::Crypto`. The engine is
    /// exchange-agnostic; the host says which one executes.
    crypto_venue: CostVenue,
    /// Latest top-20 book per bar-backed crypto market, from whichever
    /// exchange the host polled. Used for a fill's spread and depth only while
    /// fresh and from the exchange that executes (see [`crate::orderbook`]).
    books: HashMap<String, BookQuote>,
    /// Validation gates 1 to 6 per strategy, computed on request by the host
    /// (they need candle history) and kept against the parameters they judged.
    research: HashMap<String, validation::ResearchVerdict>,
    /// The latest lab signal per lab strategy id, and which signal each book
    /// has already been rebalanced to (by `generated_ms`).
    lab_signals: HashMap<String, crate::lab::LabSignal>,
    lab_done: HashMap<String, i64>,
    /// A rebalance with refused orders, per lab strategy: (signal, attempts so
    /// far, time of the last one). Not saved; a restart simply tries again.
    lab_retry: HashMap<String, (i64, u32, i64)>,
    /// Lab notes already journaled, so a stale signal is said once, not every tick.
    lab_notes: HashSet<String>,
    /// Real fills not yet handed to the host for the tax record (see `crate::tax`).
    fill_records: Vec<crate::tax::FillRecord>,
    /// Average entry per open position at reference prices (before execution
    /// costs), for the gross line. Missing means "same as the fill price".
    ref_prices: HashMap<String, f64>,
    /// The sizing mode last announced per strategy, so a switch to measured
    /// edge or to "no edge" is journaled once, not on every signal.
    sizing_noted: HashMap<String, risk::SizingMode>,
    /// The volatility spike trim's clock and rate limit.
    vol_spike: risk::VolSpikeGuard,
    /// Which source each crypto market's quotes, candles and books come from,
    /// and the sanity check that keeps a bad tick off the mark.
    feeds: feeds::FeedHealth,
    /// Markets whose stop check is waiting for a fresh price, or whose latest
    /// quote was refused, so each is journaled once per episode.
    feed_noted: HashSet<String>,
    /// Capital sleeves that trade on their own (see [`autopilot`]).
    autopilots: Vec<autopilot::Autopilot>,
    tick_count: u64,
    seq: u64,
    /// Random per process, part of every client order id sent to a venue. The
    /// id counter alone repeats after a crash that lost the last save, and a
    /// venue that sees a known client id (Alpaca) hands back the old order.
    boot_tag: String,
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
            ohlc: HashMap::new(),
            bar_backed: Default::default(),
            last_bar_ts: HashMap::new(),
            signalled_bar: HashMap::new(),
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
            broker: None,
            ai: HashMap::new(),
            ai_policy: AiPolicy::default(),
            ai_spend: AiSpend::default(),
            demo_venues: HashSet::new(),
            crypto_demo_venue: None,
            crypto_demo_real_prices: false,
            pending_live: Vec::new(),
            inflight: HashMap::new(),
            in_flight_markets: HashSet::new(),
            live_warned_at: HashMap::new(),
            live_backoff_until: HashMap::new(),
            feeds_logged: HashSet::new(),
            forecast_cfg: forecast::ForecastConfig::default(),
            forecast_store: track::ForecastStore::default(),
            source_stats: track::SourceStats::default(),
            correlations: track::ErrorCorrelations::default(),
            track_cache: Vec::new(),
            scored_version: None,
            forecasts: Vec::new(),
            coherence: Vec::new(),
            llm_opinions: HashMap::new(),
            actionable: HashSet::new(),
            exec_policy: bandit::ExecPolicy::default(),
            crypto_venue: CostVenue::Kraken,
            books: HashMap::new(),
            research: HashMap::new(),
            lab_signals: HashMap::new(),
            lab_done: HashMap::new(),
            lab_retry: HashMap::new(),
            lab_notes: HashSet::new(),
            fill_records: Vec::new(),
            ref_prices: HashMap::new(),
            sizing_noted: HashMap::new(),
            vol_spike: risk::VolSpikeGuard::default(),
            feeds: feeds::FeedHealth::default(),
            feed_noted: HashSet::new(),
            autopilots: Vec::new(),
            tick_count: 0,
            seq: 0,
            boot_tag: uuid::Uuid::new_v4().simple().to_string()[..8].to_string(),
            rng: 0x9E3779B97F4A7C15,
        };
        let now = e.now();
        for s in e.strategies.iter_mut() {
            if s.state != StrategyState::Paused {
                s.ledger.paper_since = Some(now);
            }
        }
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
            self.log(JournalKind::System, format!("Alpaca feed · {} live quotes", feed.len()), None, None);
        }
    }

    /// Install real candle history for a set of markets.
    ///
    /// **The final bar is dropped.** Both Alpaca and Kraken include the current,
    /// still-forming candle at the end of the series. Signalling on it means
    /// acting on a partial bar whose high, low and close all still move — the
    /// classic way to build a backtest that cannot be reproduced live. Only
    /// completed candles reach the indicators.
    pub fn apply_bars(&mut self, series: &[BarSeries]) {
        let mut fresh = 0usize;
        for s in series {
            if s.bars.len() < 2 {
                continue; // nothing usable once the forming bar is dropped
            }
            if self.install_bars(&s.id, &s.bars[..s.bars.len() - 1]) {
                fresh += 1;
            }
        }
        self.log_new_bars(fresh);
    }

    /// Make `closed` the market's whole candle series. True when its newest
    /// bar is one the engine had not seen.
    fn install_bars(&mut self, id: &str, closed: &[Ohlc]) -> bool {
        let Some(newest) = closed.last().map(|b| b.ts) else { return false };
        let fresh = self.last_bar_ts.get(id) != Some(&newest);
        self.last_bar_ts.insert(id.to_string(), newest);
        self.history.insert(id.to_string(), closed.iter().map(|b| b.close).collect());
        self.ohlc.insert(id.to_string(), closed.to_vec());
        self.bar_backed.insert(id.to_string());
        fresh
    }

    fn log_new_bars(&mut self, fresh: usize) {
        if fresh > 0 {
            self.log(
                JournalKind::System,
                format!("Candle feed · {fresh} market(s) advanced to a new bar"),
                None,
                None,
            );
        }
    }

    /// True once a market's indicators are computed from real candles rather
    /// than the simulator. The UI badges this so nobody mistakes a simulated
    /// equity curve for a real one.
    pub fn is_bar_backed(&self, market_id: &str) -> bool {
        self.bar_backed.contains(market_id)
    }

    /// Keep the latest order book of each bar-backed crypto market. A book for
    /// a market still on the simulator is dropped: its price is invented, and
    /// a real spread around an invented price prices nothing.
    pub fn apply_books(&mut self, books: &[BookSnapshot]) {
        let mut kept = 0usize;
        for b in books {
            let crypto = self.markets.iter().any(|m| m.id == b.id && m.venue == Venue::Crypto);
            if crypto && self.bar_backed.contains(&b.id) {
                self.books.insert(b.id.clone(), b.quote);
                kept += 1;
            }
        }
        if kept > 0 && self.feeds_logged.insert("books") {
            let venue = books.first().map(|b| b.quote.venue.id()).unwrap_or("?");
            self.log(
                JournalKind::System,
                format!("Order book feed · {kept} {venue} books now price crypto spread and depth"),
                None,
                None,
            );
        }
    }

    // ── live feeds with failover (see crate::feeds) ─────────────────────────
    //
    // The host's feed loops (`feeds::runner`) fetch; everything they bring
    // passes through here, where the sanity check and the source choice are
    // made and journaled. Only a value from a market's current source moves
    // the engine.

    /// A host has started the feed loops with this configuration.
    pub fn start_feeds(&mut self, cfg: FeedConfig) {
        let now = self.now();
        self.feeds.set_config(cfg);
        self.feeds.set_book_sources(FeedSource::for_books(self.crypto_venue));
        self.feeds.start(now);
    }

    /// The crypto markets the feeds serve: the shared universe, where the
    /// engine has a market for it.
    pub fn feed_markets(&self) -> Vec<String> {
        feeds::sources::universe_ids().into_iter().filter(|id| self.markets.iter().any(|m| &m.id == id)).collect()
    }

    pub fn feed_priority(&self, kind: DataKind) -> Vec<FeedSource> {
        self.feeds.priority(kind)
    }

    pub fn feed_needs_poll(&self, kind: DataKind, src: FeedSource) -> bool {
        self.feeds.needs_poll(kind, src, &self.feed_markets(), self.now())
    }

    /// The markets to ask `src` about this round (empty: skip it).
    pub fn feed_wanted(&self, kind: DataKind, src: FeedSource) -> Vec<String> {
        self.feeds.wanted(kind, src, &self.feed_markets(), self.now())
    }

    pub fn feed_needs_failover(&self, kind: DataKind) -> bool {
        self.feeds.needs_failover(kind, &self.feed_markets(), self.now())
    }

    /// The other venue to poll for the quote sanity check, when one is due.
    pub fn take_feed_reference(&mut self) -> Option<FeedSource> {
        let ids = self.feed_markets();
        let now = self.now();
        self.feeds.take_reference(&ids, now)
    }

    /// One quote poll (or the stream's latest prices), seen at `observed_at`.
    /// Every price goes through the sanity check; a refused one never becomes
    /// the mark, so the market keeps its last good price and ages, and the
    /// risk manager and the stop checks treat it as stale.
    pub fn apply_feed_quotes(&mut self, src: FeedSource, res: Result<Vec<RealCrypto>, String>, observed_at: i64) {
        let now = self.now();
        let ids = self.feed_markets();
        let rows = match res {
            Ok(rows) => rows,
            Err(e) => {
                self.feeds.poll_failed(DataKind::Quotes, src, &e);
                let sw = self.feeds.reselect(DataKind::Quotes, &ids, now);
                self.journal_switches(DataKind::Quotes, sw);
                return;
            }
        };
        self.feeds.poll_ok(DataKind::Quotes, src, now);
        let (mut good, mut refused) = (Vec::new(), Vec::new());
        for r in rows.into_iter().filter(|r| ids.contains(&r.id)) {
            match self.feeds.check_quote(src, &r.id, r.price, observed_at) {
                Ok(()) => {
                    self.feeds.observe(DataKind::Quotes, src, &r.id, observed_at);
                    good.push(r);
                }
                Err(why) => refused.push((r.id.clone(), why)),
            }
        }
        let sw = self.feeds.reselect(DataKind::Quotes, &ids, now);
        for r in good {
            self.feed_noted.remove(&format!("refused:{}", r.id));
            if self.feeds.current(DataKind::Quotes, &r.id) != Some(src) {
                continue;
            }
            if let Some(m) = self.markets.iter_mut().find(|m| m.id == r.id) {
                // Never step back in time: a slow REST answer must not undo a
                // newer price the stream already delivered.
                if observed_at >= m.updated_at || !self.real_ids.contains(&r.id) {
                    m.price = r.price;
                    m.change24h = r.change24h;
                    m.updated_at = observed_at;
                }
                self.real_ids.insert(r.id.clone());
                self.feeds.mark_updated(DataKind::Quotes, &r.id, observed_at);
            }
        }
        self.journal_switches(DataKind::Quotes, sw);
        let fresh: Vec<(String, String)> =
            refused.into_iter().filter(|(id, _)| self.feed_noted.insert(format!("refused:{id}"))).collect();
        if !fresh.is_empty() {
            let ids: Vec<String> = fresh.iter().map(|(id, _)| id.clone()).collect();
            let msg = format!(
                "{} quote refused for {}: {}. The last good price stays the mark; nothing trades or stops on the refused one",
                src.label(),
                feeds::list_markets(&ids),
                fresh[0].1
            );
            self.log(JournalKind::System, msg, None, (ids.len() == 1).then(|| ids[0].clone()));
        }
    }

    /// The stream's latest state, handed over by the drain loop. A dead or
    /// silent stream counts as a failed poll, so its markets fail over within
    /// a few seconds.
    pub fn apply_stream(&mut self, snap: feeds::ws::Snapshot) {
        let now = self.now();
        let silent_for = snap.status.last_message.map(|t| now - t);
        self.feeds.set_stream(snap.status.clone());
        let push_stale = self.feeds.config().push_stale_ms;
        if !snap.status.connected || silent_for.is_none_or(|s| s > push_stale) {
            let why = if snap.status.connected {
                format!("silent for {} s", silent_for.unwrap_or(0) / 1000)
            } else {
                snap.status.last_error.clone().unwrap_or_else(|| "not connected".into())
            };
            self.apply_feed_quotes(FeedSource::KrakenWs, Err(why), now);
            return;
        }
        if snap.quotes.is_empty() {
            return; // connected, waiting for the first snapshot
        }
        let rows = snap
            .quotes
            .into_iter()
            .map(|(sym, (price, change))| RealCrypto { id: format!("crypto:{sym}"), symbol: sym, price, change24h: change })
            .collect();
        // Prices are as of the last frame: the stream sends every trade and a
        // heartbeat each second, so an unchanged price is a confirmed one.
        let at = snap.status.last_message.unwrap_or(now).min(now);
        self.apply_feed_quotes(FeedSource::KrakenWs, Ok(rows), at);
    }

    /// One candle poll of `src` at `minutes` per bar. A series is checked as
    /// a whole (long enough, not behind, its last close near the live price)
    /// and installed whole: a market's candles always come from one venue.
    /// When that venue changes the new series replaces the old one outright,
    /// which is journaled, and no entry is taken on the switch bar.
    pub fn apply_feed_candles(&mut self, src: FeedSource, res: Result<Vec<BarSeries>, String>, minutes: u32) {
        let now = self.now();
        let ids = self.feed_markets();
        let iv = minutes.max(1) as i64 * 60_000;
        self.feeds.set_candle_interval_ms(iv);
        let series = match res {
            Ok(s) => s,
            Err(e) => {
                self.feeds.poll_failed(DataKind::Candles, src, &e);
                let sw = self.feeds.reselect(DataKind::Candles, &ids, now);
                self.journal_switches(DataKind::Candles, sw);
                return;
            }
        };
        self.feeds.poll_ok(DataKind::Candles, src, now);
        let mut good: Vec<(String, Vec<Ohlc>)> = Vec::new();
        for s in series.into_iter().filter(|s| ids.contains(&s.id)) {
            // Closed bars only, by the clock: venues differ on whether the
            // forming bar is included.
            let closed: Vec<Ohlc> = s.bars.into_iter().filter(|b| b.ts + iv <= now).collect();
            match self.check_series(&s.id, &closed, iv, now) {
                Ok(()) => {
                    self.feeds.observe(DataKind::Candles, src, &s.id, now);
                    good.push((s.id, closed));
                }
                Err(why) => self.feeds.reject(DataKind::Candles, src, &s.id, now, &why),
            }
        }
        let sw = self.feeds.reselect(DataKind::Candles, &ids, now);
        let mut fresh = 0;
        for (id, closed) in good {
            if self.feeds.current(DataKind::Candles, &id) == Some(src) {
                if self.install_bars(&id, &closed) {
                    fresh += 1;
                }
                self.feeds.mark_updated(DataKind::Candles, &id, now);
            }
        }
        // A venue switch is a new series, not a new bar: whatever its
        // indicators say on the bar it arrived with, no entry is taken on it.
        for s in sw.iter().filter(|s| s.from.is_some()) {
            if let Some(ts) = self.last_bar_ts.get(&s.market).copied() {
                self.signalled_bar.insert(s.market.clone(), ts);
            }
        }
        self.log_new_bars(fresh);
        self.journal_switches(DataKind::Candles, sw);
    }

    /// Whether a candle series may be installed for `id`.
    fn check_series(&self, id: &str, closed: &[Ohlc], iv: i64, now: i64) -> Result<(), String> {
        if closed.len() < 2 {
            return Err("fewer than two closed bars".into());
        }
        let last = closed[closed.len() - 1];
        let behind = now - last.ts;
        if behind > 3 * iv + 120_000 {
            return Err(format!("behind: the newest closed bar is {} min old", behind / 60_000));
        }
        // Against the live mark, on intraday bars where the last close is minutes old.
        if iv <= 3_600_000 {
            if let Some(price) = self.trusted_price(id, now) {
                let off = (last.close / price - 1.0).abs();
                if off > 2.0 * self.feeds.config().max_deviation {
                    return Err(format!("last close {:.1}% away from the live price", off * 100.0));
                }
            }
        }
        Ok(())
    }

    /// The market's price when it is real and fresh, for cross-checks.
    fn trusted_price(&self, id: &str, now: i64) -> Option<f64> {
        let limit = self.limits.max_data_staleness_sec as i64 * 1000;
        self.markets
            .iter()
            .find(|m| m.id == id)
            .filter(|m| self.real_ids.contains(id) && now - m.updated_at <= limit && m.price > 0.0)
            .map(|m| m.price)
    }

    /// One book poll. A book whose mid is far from the live price is refused;
    /// the rest go through [`Engine::apply_books`] when `src` is the market's
    /// current book source.
    pub fn apply_feed_books(&mut self, src: FeedSource, res: Result<Vec<BookSnapshot>, String>) {
        let now = self.now();
        let ids = self.feed_markets();
        let books = match res {
            Ok(b) => b,
            Err(e) => {
                self.feeds.poll_failed(DataKind::Books, src, &e);
                let sw = self.feeds.reselect(DataKind::Books, &ids, now);
                self.journal_switches(DataKind::Books, sw);
                return;
            }
        };
        self.feeds.poll_ok(DataKind::Books, src, now);
        let tol = self.feeds.config().max_deviation;
        let mut good = Vec::new();
        for b in books.into_iter().filter(|b| ids.contains(&b.id)) {
            if let Some(p) = self.trusted_price(&b.id, now) {
                let off = (b.quote.mid / p - 1.0).abs();
                if off > tol {
                    let why = format!("mid {:.1}% away from the live price", off * 100.0);
                    self.feeds.reject(DataKind::Books, src, &b.id, now, &why);
                    continue;
                }
            }
            self.feeds.observe(DataKind::Books, src, &b.id, now);
            good.push(b);
        }
        let sw = self.feeds.reselect(DataKind::Books, &ids, now);
        let current: Vec<BookSnapshot> =
            good.into_iter().filter(|b| self.feeds.current(DataKind::Books, &b.id) == Some(src)).collect();
        for b in &current {
            self.feeds.mark_updated(DataKind::Books, &b.id, now);
        }
        self.apply_books(&current);
        self.journal_switches(DataKind::Books, sw);
    }

    /// One journal line per group of markets that moved together.
    fn journal_switches(&mut self, kind: DataKind, sw: Vec<feeds::Switch>) {
        if sw.is_empty() {
            return;
        }
        let pri = self.feeds.priority(kind);
        let mut groups: Vec<((Option<FeedSource>, FeedSource), Vec<String>)> = Vec::new();
        for s in sw {
            match groups.iter_mut().find(|(k, _)| *k == (s.from, s.to)) {
                Some((_, ids)) => ids.push(s.market),
                None => groups.push(((s.from, s.to), vec![s.market])),
            }
        }
        for ((from, to), ids) in groups {
            let what = feeds::list_markets(&ids);
            let msg = match from {
                None => format!("{}: {what} on {}", kind.label(), to.label()),
                Some(f) if (feeds::Switch { market: String::new(), from, to }).is_failover(&pri) => {
                    let why = match self.feeds.last_error(kind, f) {
                        Some(e) => format!(" ({} failed: {e})", f.label()),
                        None => format!(" ({} went stale)", f.label()),
                    };
                    let series = if kind == DataKind::Candles {
                        ". A different venue's candles are a different series: they replace the old one whole, \
                         and no entry is taken on the switch bar"
                    } else {
                        ""
                    };
                    format!("{}: {what} failed over from {} to {}{why}{series}", kind.label(), f.label(), to.label())
                }
                Some(f) => format!("{}: {what} back on {} after {}", kind.label(), to.label(), f.label()),
            };
            self.log(JournalKind::System, msg, None, (ids.len() == 1).then(|| ids[0].clone()));
        }
    }

    /// Stale markets per kind, while a host runs the feeds: quotes older than
    /// the risk manager's staleness limit, candles not refreshed or behind,
    /// books past their age limit.
    fn stale_markets(&self, now: i64) -> (Vec<String>, Vec<String>, Vec<String>) {
        let Some(started) = self.feeds.started_at() else { return Default::default() };
        let ids = self.feed_markets();
        let limit = self.limits.max_data_staleness_sec as i64 * 1000;
        let quotes = ids
            .iter()
            .filter(|id| match self.markets.iter().find(|m| &m.id == *id) {
                Some(m) if self.real_ids.contains(*id) => now - m.updated_at > limit,
                _ => now - started > limit,
            })
            .cloned()
            .collect();
        let cfg = self.feeds.config();
        let iv = self.feeds.candle_interval_ms();
        let candles = ids
            .iter()
            .filter(|id| match self.feeds.updated(DataKind::Candles, id) {
                None => now - started > cfg.candle_stale_ms,
                Some(t) => {
                    now - t > cfg.candle_stale_ms
                        || self.last_bar_ts.get(*id).is_none_or(|ts| now - ts > 3 * iv + 120_000)
                }
            })
            .cloned()
            .collect();
        let books = if self.feeds.priority(DataKind::Books).is_empty() {
            vec![]
        } else {
            ids.iter()
                .filter(|id| self.bar_backed.contains(*id))
                .filter(|id| match self.books.get(*id) {
                    Some(b) => !b.is_fresh(now),
                    None => now - started > cfg.book_stale_ms,
                })
                .cloned()
                .collect()
        };
        (quotes, candles, books)
    }

    /// Once per tick: tell the webhook (through a Risk journal line) when
    /// quotes or candles have been stale for the alert time, and again when
    /// they recover. Short blips stay in the health report only.
    fn check_data_alert(&mut self, now: i64) {
        if self.feeds.started_at().is_none() {
            return;
        }
        let (quotes, candles, _) = self.stale_markets(now);
        let since = self.feeds.stale_since();
        match self.feeds.track_episode(!quotes.is_empty() || !candles.is_empty(), now) {
            Some(true) => {
                let mut parts = Vec::new();
                if !quotes.is_empty() {
                    parts.push(format!("quotes for {}", feeds::list_markets(&quotes)));
                }
                if !candles.is_empty() {
                    parts.push(format!("candles for {}", feeds::list_markets(&candles)));
                }
                let mins = since.map_or(0, |s| (now - s) / 60_000);
                self.log(
                    JournalKind::Risk,
                    format!(
                        "Market data stale for {mins} min: {}. Entries are refused and stops wait for a fresh price",
                        parts.join(", ")
                    ),
                    None,
                    None,
                );
            }
            Some(false) => {
                let mins = since.map_or(0, |s| (now - s) / 60_000);
                let ids = self.feed_markets();
                let on = |k: DataKind| self.feeds.active(k, &ids).map_or("no source", FeedSource::label);
                let msg = format!(
                    "Market data recovered after {mins} min: quotes on {}, candles on {}",
                    on(DataKind::Quotes),
                    on(DataKind::Candles)
                );
                self.log(JournalKind::Risk, msg, None, None);
            }
            None => {}
        }
    }

    /// The `dataHealth` section of the state.
    pub fn data_health(&self) -> feeds::DataHealth {
        let now = self.now();
        let ids = self.feed_markets();
        let (q, c, b) = self.stale_markets(now);
        let kinds = vec![
            self.feeds.kind_health(DataKind::Quotes, &ids, q, now),
            self.feeds.kind_health(DataKind::Candles, &ids, c, now),
            self.feeds.kind_health(DataKind::Books, &ids, b, now),
        ];
        self.feeds.report(kinds, &ids)
    }

    /// Why a stop or trim must not act on this market's price right now: it
    /// is a real feed's price and older than the staleness limit. A refused
    /// quote never becomes the price, so it ages into this too.
    fn exit_price_stale(&self, id: &str, now: i64) -> Option<i64> {
        if !self.real_ids.contains(id) {
            return None; // the simulator's own price is always current
        }
        let m = self.markets.iter().find(|m| m.id == id)?;
        let age = now - m.updated_at;
        (age > self.limits.max_data_staleness_sec as i64 * 1000).then_some(age)
    }

    /// Journal once that `id`'s exit checks wait for a fresh price.
    fn note_exit_held(&mut self, id: &str, age_ms: i64, what: &str) {
        if self.feed_noted.insert(format!("exit:{id}")) {
            let why = self.feeds.suspect(id).map(|s| format!(" (latest quote refused, {s})")).unwrap_or_default();
            self.log(
                JournalKind::System,
                format!(
                    "{what} on {id} held: its price is {} s old, over the {} s limit{why}. \
                     A stale or refused price never triggers an exit; checks resume with the next fresh price",
                    age_ms / 1000,
                    self.limits.max_data_staleness_sec
                ),
                None,
                Some(id.to_string()),
            );
        }
    }

    /// The cost inputs for one order: the calibrated model, with the live
    /// half-spread and the live depth of the side taken when a fresh book
    /// from the executing exchange exists.
    fn exec_cost(&self, m: &Market, side: Side) -> ExecCost {
        ExecCost::for_order(self.cost_model(m), self.cost_venue(m), self.books.get(&m.id), side, self.now())
    }

    /// Record the broker's session/account snapshot. Live equity routing is
    /// blocked while this is absent or stale — see [`Engine::live_block_reason`].
    pub fn set_broker_status(&mut self, status: BrokerStatus) {
        let was_open = self.broker.as_ref().map(|b| b.market_open);
        if was_open == Some(false) && status.market_open {
            self.log(JournalKind::System, "US equity market OPEN".into(), None, None);
        } else if was_open == Some(true) && !status.market_open {
            self.log(JournalKind::System, "US equity market CLOSED".into(), None, None);
        }
        if let Some(why) = &status.restricted {
            self.log(JournalKind::Risk, format!("Alpaca account restricted: {why}"), None, None);
        }
        self.broker = Some(status);
    }

    /// [`Engine::live_block_reason`] for one Alpaca market. Alpaca's crypto book
    /// trades around the clock and is outside the pattern-day-trader rule, so
    /// only the account checks apply to it; equities get the full session gate.
    pub fn live_block_reason_for(&self, m: &Market) -> Option<String> {
        if m.kind != MarketKind::Crypto {
            return self.live_block_reason();
        }
        let Some(b) = &self.broker else {
            return Some("broker status unknown, waiting for the first account check".into());
        };
        if self.now() - b.checked_at > BROKER_STATUS_MAX_AGE_MS {
            return Some("broker status is stale, cannot confirm the account is usable".into());
        }
        b.restricted.as_ref().map(|why| format!("Alpaca account restricted: {why}"))
    }

    /// Why a live *equity entry* would be refused right now, or `None` when the
    /// path is clear. Exits are deliberately exempt from the day-trade and
    /// session checks below — being unable to close a position you already hold
    /// is far more dangerous than being unable to open one.
    pub fn live_block_reason(&self) -> Option<String> {
        let Some(b) = &self.broker else {
            return Some("broker status unknown — waiting for the first account check".into());
        };
        if self.now() - b.checked_at > BROKER_STATUS_MAX_AGE_MS {
            return Some("broker status is stale — cannot confirm the market is open".into());
        }
        if let Some(why) = &b.restricted {
            return Some(format!("Alpaca account restricted: {why}"));
        }
        if !b.market_open {
            // Extended hours are a deliberate opt-in, not a fallback.
            if self.live.extended_hours && b.extended_open {
                // Trading the thin session — allowed, and journaled as such.
            } else {
                let hint = if b.extended_open && !self.live.extended_hours {
                    " — extended-hours session is open; enable it on the Live page to trade it"
                } else {
                    ""
                };
                return Some(match &b.next_open {
                    Some(t) => format!("US equity market closed (next open {t}){hint}"),
                    None => format!("US equity market closed{hint}"),
                });
            }
        }
        if b.day_trade_limit_reached {
            return Some(
                "pattern-day-trader limit reached (3 day trades / 5 sessions under $25k) — new entries blocked".into(),
            );
        }
        None
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

        // Advance the simulator — and ONLY the simulator.
        //
        // Real-fed markets used to random-walk between fetches to keep the UI
        // lively. That invents price action: it drifts the mark away from the
        // real quote, prints P&L that never happened, and trips ATR stops on
        // moves the market did not make. A real feed that looks frozen between
        // refreshes is telling the truth.
        //
        // Done in three passes rather than one loop with a lookup: the old
        // version cloned every market id and then linear-searched the market
        // list for each one, which is quadratic and allocates a String per
        // market per tick.
        //
        // Pass 1 reads the sim parameters (immutable borrow of markets + sim),
        // pass 2 draws the shocks (needs `&mut self` for the PRNG), pass 3
        // applies them by index (mutable borrow of markets alone). `None` marks
        // a real-fed market, which is left exactly where the feed put it.
        let plan: Vec<Option<(f64, f64, Option<f64>)>> = (0..self.markets.len())
            .map(|i| {
                let id = &self.markets[i].id;
                if self.real_ids.contains(id) {
                    return None;
                }
                let p = self.sim.get(id);
                let (drift, vol) = p.map(|p| (p.drift, p.vol)).unwrap_or((0.0, 0.0015));
                Some((drift, vol, p.map(|p| p.base)))
            })
            .collect();
        let plan: Vec<Option<(f64, Option<f64>)>> = plan
            .into_iter()
            .map(|step| step.map(|(drift, vol, base)| (drift + vol * self.gaussian(), base)))
            .collect();

        for (m, step) in self.markets.iter_mut().zip(plan) {
            let Some((shock, base)) = step else { continue };
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

        // Append the new close to each SIMULATED market's rolling history.
        // Bar-backed markets own their series outright (see `apply_bars`) —
        // appending a tick to a 5-minute candle series would make every
        // indicator measure the tick loop instead of the market.
        let sim_ids: Vec<(String, f64)> = self
            .markets
            .iter()
            .filter(|m| !self.bar_backed.contains(&m.id))
            .map(|m| (m.id.clone(), m.price))
            .collect();
        for (id, price) in sim_ids {
            let h = self.history.entry(id).or_default();
            h.push(price);
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

        // Stale market data for minutes goes to the webhook, once, and so does its end.
        self.check_data_alert(now);

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

        // Trim the book back to its volatility target after a sustained spike
        // (off unless volSpikeTrimMult is set).
        self.check_vol_spike(now);

        // Autopilots: live gates, stop rules and history, before anything new
        // is opened this tick.
        self.autopilot_step(now);

        // Lab books rebalance once per new signal, on their own pass.
        if self.tick_count % 5 == 0 {
            self.run_lab_books();
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
                    // An autopilot's strategies trade only its markets, only
                    // while it runs; everyone else stays off the markets it reserved.
                    if !self.autopilot_entry_allowed(&self.strategies[idx].id, &intent.market_id) {
                        continue;
                    }
                    // On a bar-backed market, act at most once per closed candle.
                    // The tick loop runs every 1.5s but the data only changes when
                    // a bar closes — re-firing in between is the same signal
                    // resubmitted, and it is how a "signal" turns into a fee bill.
                    if let Some(bar_ts) = self.last_bar_ts.get(&intent.market_id).copied() {
                        if self.signalled_bar.get(&intent.market_id) == Some(&bar_ts) {
                            continue;
                        }
                        self.signalled_bar.insert(intent.market_id.clone(), bar_ts);
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
        self.correlations = self.forecast_store.error_correlations();
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
            let category = market_category(m.kind);
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
                    category,
                    history: &history,
                    liquidity: m.liquidity,
                    days_to_resolution: days,
                    llm: &llm,
                    now,
                },
                &self.source_stats,
                &self.correlations,
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
            let Some(market) = snapshot.iter().find(|m| m.id == market_id) else { continue };
            let (ref_price, category) = (market.price, market_category(market.kind));

            if f.kind == track::ForecastKind::Outcome {
                // The level view, which settles when the event does...
                self.forecast_store.record(
                    now, &market_id, "ensemble", track::ForecastKind::Outcome, category,
                    f.ensemble_p, f.market_p, ref_price, cfg.horizon_ms,
                );
                for s in &f.sources {
                    self.forecast_store.record(
                        now, &market_id, &s.source, track::ForecastKind::Outcome, category,
                        s.p, f.market_p, ref_price, cfg.horizon_ms,
                    );
                }
                // ...and the derived directional view, which settles on a timer.
                // Without this, an election market yields no calibration data
                // for months, and every source stays unweighted forever.
                self.forecast_store.record(
                    now, &market_id, "ensemble", track::ForecastKind::Direction, category,
                    forecast::direction_from_edge(f.ensemble_p, f.market_p),
                    0.5, ref_price, cfg.horizon_ms,
                );
                for s in &f.sources {
                    self.forecast_store.record(
                        now, &market_id, &s.source, track::ForecastKind::Direction, category,
                        forecast::direction_from_edge(s.p, f.market_p),
                        0.5, ref_price, cfg.horizon_ms,
                    );
                }
            } else {
                self.forecast_store.record(
                    now, &market_id, "ensemble", track::ForecastKind::Direction, category,
                    f.ensemble_p, f.market_p, ref_price, cfg.horizon_ms,
                );
                for s in &f.sources {
                    self.forecast_store.record(
                        now, &market_id, &s.source, track::ForecastKind::Direction, category,
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
        // Lab books keep the budget they were given: the lab tested them on
        // that capital, and steering it by a few days of P&L would make the
        // forward test a different strategy from the one judged. Their share
        // comes off the pool so the total stays where it was.
        let lab_budget: f64 = self
            .strategies
            .iter()
            .filter(|s| s.kind == StrategyKind::LabTargets && s.state != StrategyState::Paused)
            .map(|s| s.budget_pct)
            .sum();
        let pool = (80.0 - lab_budget).max(0.0);
        let idxs: Vec<usize> = self
            .strategies
            .iter()
            .enumerate()
            .filter(|(_, s)| s.state != StrategyState::Paused && s.id != "manual" && s.kind != StrategyKind::LabTargets)
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
            self.strategies[i].budget_pct = ((shifted[j] / sum) * pool).clamp(3.0, 35.0);
        }
        self.log(JournalKind::System, "Adaptive allocation rebalanced by recent performance".into(), None, None);
    }

    /// Auto-exit positions whose stop-loss/take-profit/trailing level is hit.
    fn check_position_exits(&mut self) {
        let prices: HashMap<String, f64> =
            self.markets.iter().map(|m| (m.id.clone(), m.price)).collect();
        let trail_mult = self.limits.trailing_atr_mult;
        let mut to_close: Vec<(String, String)> = Vec::new();
        // A stale price neither trips a stop nor ratchets a trailing one: it
        // is not where the market is. Refused quotes never become the price,
        // so a bad tick lands here too once the last good one ages out.
        let now = self.now();
        let stale: HashMap<String, i64> = self
            .positions
            .keys()
            .filter_map(|id| self.exit_price_stale(id, now).map(|age| (id.clone(), age)))
            .collect();
        let mut held: Vec<(String, i64)> = Vec::new();

        for (id, pos) in self.positions.iter_mut() {
            let price = *prices.get(id).unwrap_or(&0.0);
            if price <= 0.0 || pos.qty == 0.0 || pos.stop <= 0.0 && pos.target <= 0.0 {
                continue;
            }
            if let Some(age) = stale.get(id) {
                held.push((id.clone(), *age));
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

        for (id, age) in held {
            self.note_exit_held(&id, age, "Stop check");
        }
        // Fresh again: the next hold is a new episode and is journaled anew.
        let resumed: Vec<String> = self
            .feed_noted
            .iter()
            .filter_map(|k| k.strip_prefix("exit:"))
            .filter(|id| !stale.contains_key(*id))
            .map(String::from)
            .collect();
        for id in resumed {
            self.feed_noted.remove(&format!("exit:{id}"));
            if self.positions.contains_key(&id) {
                self.log(JournalKind::System, format!("Stop check on {id} resumed with a fresh price"), None, Some(id));
            }
        }

        for (id, reason) in to_close {
            self.close_position(&id, &reason);
        }
    }

    /// Close a position attributing the fill to its owning strategy.
    fn close_position(&mut self, id: &str, reason: &str) {
        let (qty, side, sid, live, intent) = match self.positions.get(id) {
            Some(p) if p.qty != 0.0 => (
                p.qty.abs(),
                if p.qty > 0.0 { Side::Sell } else { Side::Buy },
                p.strategy_id.clone(),
                p.live,
                Self::exit_intent(p),
            ),
            _ => return,
        };
        let Some(m) = self.markets.iter().find(|m| m.id == id).cloned() else { return };
        let idx = self
            .strategies
            .iter()
            .position(|s| s.id == sid)
            .unwrap_or_else(|| self.ensure_manual_strategy());
        self.route_fill(idx, &m, side, qty, m.price, intent);
        // Only claim the exit happened if it actually did. A live exit that
        // could not route leaves the position open, and `route_fill` has
        // already explained why.
        if !live || self.live_routable(m.venue) {
            self.log(JournalKind::System, format!("Exit {id}: {reason}"), Some(sid), Some(id.to_string()));
        }
    }

    /// Cut every open position to the same fraction once the book's
    /// volatility has stayed far over its target. See [`risk::VolSpikeGuard`]
    /// for the trigger, the hysteresis and the rate limit; `now` is passed in
    /// so the clock can be driven in tests.
    fn check_vol_spike(&mut self, now: i64) {
        let equity = self.equity();
        let vol_pct = if equity > 0.0 { self.book_vol() / equity * 100.0 } else { 0.0 };
        let (target, k) = (self.limits.portfolio_vol_target_pct, self.limits.vol_spike_trim_mult);
        let Some(keep) = self.vol_spike.update(vol_pct, target, k, now) else { return };
        let mut ids: Vec<String> = self.positions.keys().cloned().collect();
        ids.sort();
        self.log(
            JournalKind::Risk,
            format!(
                "Volatility spike: the book has swung about {vol_pct:.0}% a year for over {} minutes, more than \
                 {k}x its {target:.0}% target. Every position is cut by {:.0}% to bring it back to the target",
                risk::VOL_SPIKE_SUSTAIN_MS / 60_000,
                (1.0 - keep) * 100.0
            ),
            None,
            None,
        );
        for id in ids {
            self.trim_position(&id, keep, "volatility spike trim");
        }
    }

    /// Reduce a position to `keep` of its size, never past flat: a long is
    /// sold and a short bought back. A real position is reduced at its venue
    /// or not at all, like any other exit.
    fn trim_position(&mut self, id: &str, keep: f64, reason: &str) {
        let keep = keep.clamp(0.0, 1.0);
        let (qty, side, sid, live, intent) = match self.positions.get(id) {
            Some(p) if p.qty != 0.0 => (
                p.qty.abs() * (1.0 - keep),
                if p.qty > 0.0 { Side::Sell } else { Side::Buy },
                p.strategy_id.clone(),
                p.live,
                Self::exit_intent(p),
            ),
            _ => return,
        };
        if qty <= 0.0 {
            return;
        }
        if let Some(age) = self.exit_price_stale(id, self.now()) {
            self.note_exit_held(id, age, "Trim");
            return;
        }
        let Some(m) = self.markets.iter().find(|m| m.id == id).cloned() else { return };
        let idx = self
            .strategies
            .iter()
            .position(|s| s.id == sid)
            .unwrap_or_else(|| self.ensure_manual_strategy());
        self.route_fill(idx, &m, side, qty, m.price, intent);
        if !live || self.live_routable(m.venue) {
            self.log(
                JournalKind::System,
                format!("Trim {id} by {:.0}%: {reason}", (1.0 - keep) * 100.0),
                Some(sid),
                Some(id.to_string()),
            );
        }
    }

    /// Volatility-based stop-loss / take-profit for a new position (price units).
    fn compute_stops(&self, m: &Market, side: Side, entry: f64) -> (f64, f64) {
        if m.kind == MarketKind::Prediction {
            return (0.0, 0.0); // ATR stops don't apply to 0..1 probabilities
        }
        // Prefer true ATR from real candles — it accounts for overnight gaps,
        // which a close-to-close proxy cannot see and which are exactly what
        // sweeps an equity stop that looked comfortable at yesterday's close.
        let atr = self
            .ohlc
            .get(&m.id)
            .and_then(|bars| indicators::atr(bars, 14))
            .or_else(|| self.history.get(&m.id).and_then(|h| indicators::atr_proxy(h, 14)))
            .unwrap_or(0.0);
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
        // A strategy inside an autopilot is sized from the autopilot's
        // capital: its sleeve's share of it, over the sleeve's own markets.
        let sleeve = self.autopilot_sizing(&sid);
        let budget = match &sleeve {
            Some(s) => s.capital,
            None => (self.strategies[strat_idx].budget_pct / 100.0) * equity,
        };
        // Spread the budget across the universe → many small positions, so the
        // trend's edge shows through with low variance (not 2-3 concentrated
        // bets). Risk caps still bound the total.
        let universe_n = match &sleeve {
            Some(s) => s.slots,
            None => self.strategies[strat_idx].universe.len().max(1) as f64,
        };
        let strength = intent.size.max(intent.confidence).clamp(0.3, 1.0);
        let full = (budget / universe_n) * 1.5 * (self.limits.kelly_fraction / 0.25).clamp(0.25, 3.0);
        let kelly_equity = sleeve.as_ref().map_or(equity, |s| s.equity);
        // Under 30 closed trades the signal strength sizes the entry. After
        // that the strategy's own record does, never above full strength.
        let deploy = match self.edge_sizing(strat_idx) {
            (risk::SizingMode::Measured, Some(k)) => {
                full.min(risk::kelly_notional(&k, kelly_equity, self.limits.kelly_fraction, universe_n))
            }
            (risk::SizingMode::NoEdge, _) => return,
            _ => full * strength,
        };
        // In a drawdown, smaller: half size at half the drawdown limit.
        let deploy = deploy * risk::derisk_factor(self.drawdown_pct(), self.limits.max_drawdown_pct);
        // AI overlay: shrink, boost slightly, or veto — applied to a trade the
        // rules already decided to make.
        let (ai_mult, ai_note) = self.ai_multiplier(&m.id, intent.side);
        if let Some(note) = ai_note {
            self.log(JournalKind::Signal, note, Some(sid.clone()), Some(m.id.clone()));
        }
        if ai_mult <= 0.0 {
            return;
        }
        let deploy = deploy * ai_mult;

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
        // Never past the sleeve's budget, and never more exposure than the
        // autopilot's equity.
        if let Some(s) = &sleeve {
            qty_wanted = qty_wanted.min(s.room / price);
            if qty_wanted * price < autopilot::MIN_ENTRY_USD {
                return;
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
        // Inside an autopilot its mode decides the route, not the strategy's switch.
        let route = self
            .autopilot_route(&sid)
            .unwrap_or_else(|| Self::entry_intent(self.strategies[strat_idx].state));
        self.route_fill(strat_idx, m, intent.side, decision.qty, price, route);
    }

    /// How a strategy in `state` routes a new entry.
    fn entry_intent(state: StrategyState) -> RouteIntent {
        match state {
            StrategyState::Live => RouteIntent::Live,
            StrategyState::Demo => RouteIntent::Demo,
            StrategyState::Paper | StrategyState::Paused => RouteIntent::Paper,
        }
    }

    /// How this strategy's next entry is sized, journaling a change of mode
    /// once: switching to its measured edge, or finding it has none.
    fn edge_sizing(&mut self, strat_idx: usize) -> (risk::SizingMode, Option<risk::KellyEstimate>) {
        let s = &self.strategies[strat_idx];
        let (mode, est) = risk::edge_sizing(&s.ledger.edge);
        if self.sizing_noted.get(&s.id) == Some(&mode) {
            return (mode, est);
        }
        let (id, name) = (s.id.clone(), s.name.clone());
        self.sizing_noted.insert(id.clone(), mode);
        let Some(k) = est else { return (mode, est) };
        let payoff = k.payoff.map_or("no losses yet".to_string(), |b| format!("payoff {b:.2}"));
        let record = format!("{} trades, {:.0}% won, {payoff}, Kelly {:.3}", k.trades, k.win_rate * 100.0, k.raw);
        match mode {
            risk::SizingMode::Measured => self.log(
                JournalKind::Risk,
                format!("{name}: now sized on its measured edge ({record}, {:.3} after shrinking)", k.shrunk),
                Some(id),
                None,
            ),
            risk::SizingMode::NoEdge => self.log(
                JournalKind::Risk,
                format!("{name}: no measured edge ({record}). New entries are sized to zero"),
                Some(id),
                None,
            ),
            risk::SizingMode::Confidence => {}
        }
        (mode, est)
    }

    /// The cost venue for a market: its own venue, or for crypto the exchange
    /// the host says executes.
    fn cost_venue(&self, m: &Market) -> CostVenue {
        CostVenue::for_venue(m.venue, Some(self.crypto_venue))
    }

    /// The cost model for one market, from `config/costs.json`.
    pub fn cost_model(&self, m: &Market) -> CostModel {
        costs::model_for(self.cost_venue(m), &m.symbol)
    }

    /// Paper fill: cross the spread and pay the taker fee the cost model says
    /// this venue charges, then settle. Spread and depth come from a live book
    /// when a fresh one exists.
    ///
    /// With a fresh top-20 book from the executing exchange, a crypto order
    /// walks it level by level ([`paper_fill_detail`]). On a market with a
    /// real price the fill is also kept in the slippage record as a `paper`
    /// row: realised against the signal price, next to what the model
    /// expected, with the drift between signal and book.
    fn fill(&mut self, strat_idx: usize, m: &Market, side: Side, qty: f64, price: f64) {
        let pf = paper_fill_detail(&self.exec_cost(m, side), m.kind, side, qty, price);
        self.settle_fill(strat_idx, m, side, qty, pf.price, pf.fee, price, false, true);
        if let Some(o) = self.orders.first_mut().filter(|o| o.market_id == m.id && o.status == OrderStatus::Filled) {
            o.route = FillRoute::Paper;
            o.cost_source = Some(pf.source);
            o.drift_bps = pf.drift_bps;
            o.book_exhausted = pf.exhausted;
            o.modelled_slippage_bps = Some(pf.modelled_bps);
            o.realised_slippage_bps = bandit::realised_cost_bps(side, price, pf.price);
        }
        let real_price = self.real_ids.contains(&m.id) || self.bar_backed.contains(&m.id);
        if real_price {
            if let Some(realised) = bandit::realised_cost_bps(side, price, pf.price) {
                let mut rec = bandit::FillRecord::new(realised, pf.modelled_bps, self.now(), pf.source, FillRoute::Paper);
                rec.drift_bps = pf.drift_bps;
                rec.book_exhausted = pf.exhausted;
                self.exec_policy.record_fill(self.cost_venue(m).id(), rec);
            }
        }
        if pf.exhausted {
            let sid = self.strategies[strat_idx].id.clone();
            self.log(
                JournalKind::System,
                format!(
                    "Paper fill on {} outgrew the 20 book levels ({} used); the rest was priced with the impact model",
                    m.symbol, pf.levels_used
                ),
                Some(sid),
                Some(m.id.clone()),
            );
        }
    }

    /// Apply a fill (paper or live) to positions, cash, P&L and strategy stats.
    /// `live` marks a real fill — its position's exits must also route live.
    /// `emit_order` inserts a fresh Filled order (the paper path); live fills
    /// instead update their existing pending order in [`Engine::apply_live_update`].
    /// `reference` is the price before execution costs: the quote a paper fill
    /// slipped from, or a live order's arrival price. The same position is
    /// tracked at reference prices alongside the real one, which is what makes
    /// the strategy's gross line (see [`StrategyLedger`]).
    #[allow(clippy::too_many_arguments)]
    fn settle_fill(
        &mut self,
        strat_idx: usize,
        m: &Market,
        side: Side,
        qty: f64,
        fill_price: f64,
        fee: f64,
        reference: f64,
        live: bool,
        emit_order: bool,
    ) {
        self.settle_fill_on(strat_idx, m, side, qty, fill_price, fee, reference, live, false, emit_order)
    }

    /// [`Engine::settle_fill`] that can also mark the position as opened by a
    /// demo-venue fill (`demo`): booked in the same ledger as paper, flagged so
    /// its exits go back to the demo venue and the UI says what it is.
    #[allow(clippy::too_many_arguments)]
    fn settle_fill_on(
        &mut self,
        strat_idx: usize,
        m: &Market,
        side: Side,
        qty: f64,
        fill_price: f64,
        fee: f64,
        reference: f64,
        live: bool,
        demo: bool,
        emit_order: bool,
    ) {
        let sid = self.strategies[strat_idx].id.clone();
        let signed = if side == Side::Buy { qty } else { -qty };
        {
            // Positive when the fill was worse than the reference price.
            let l = &mut self.strategies[strat_idx].ledger;
            l.fees += fee.max(0.0);
            l.slippage += signed * (fill_price - reference);
        }
        // A closed trade on a real price is forward-test evidence; one on the
        // demo simulator is not evidence of anything.
        let real_price = self.real_ids.contains(&m.id) || self.bar_backed.contains(&m.id);
        // Alpaca paper fills against the real NBBO; a crypto demo venue only
        // counts when it documents real prices (see `docs/DEMO.md`).
        let demo_real = m.venue != Venue::Crypto || self.crypto_demo_real_prices;
        let (new_stop, new_target) = self.compute_stops(m, side, fill_price);

        // update / open position, realizing P&L on reductions
        let key = m.id.clone();
        let mut realized = 0.0;
        // (qty, entry notional) of the part of a position this fill closed.
        let mut closed: Option<(f64, f64)> = None;
        // The same position at reference prices, for the gross line.
        let ref_avg = self.ref_prices.get(&key).copied();
        if let Some(pos) = self.positions.get(&key) {
            let (q, avg, gross) = apply_fill(pos.qty, ref_avg.unwrap_or(pos.avg_price), signed, reference);
            self.strategies[strat_idx].ledger.gross += gross;
            if q.abs() < 1e-9 {
                self.ref_prices.remove(&key);
            } else {
                self.ref_prices.insert(key.clone(), avg);
            }
        } else {
            self.ref_prices.insert(key.clone(), reference);
        }
        let existed = self.positions.contains_key(&key);
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
                        demo,
                    },
                );
            }
            Some(pos) => {
                let was = pos.qty;
                if was != 0.0 && signed.signum() != was.signum() {
                    let q = signed.abs().min(was.abs());
                    closed = Some((q, q * pos.avg_price));
                }
                let (new_qty, new_avg, r) = apply_fill(pos.qty, pos.avg_price, signed, fill_price);
                realized = r;
                pos.avg_price = new_avg;
                if new_qty.abs() < 1e-9 {
                    self.positions.remove(&key);
                } else {
                    pos.qty = new_qty;
                    // Flipped through zero: the remainder is a new position at
                    // this fill, and the old stops belonged to the other side.
                    if was != 0.0 && new_qty.signum() != was.signum() {
                        pos.stop = new_stop;
                        pos.target = new_target;
                        pos.trail_ref = fill_price;
                    }
                }
            }
        }

        if realized != 0.0 {
            self.realized_pnl += realized;
        }
        self.cash -= signed * fill_price + fee;
        // The autopilot that owns this position, or that just opened it, books it.
        let open_after = self.positions.contains_key(&key);
        self.autopilot_on_fill(&sid, &key, realized, fee, existed, open_after);
        // The measured edge: net return on the closed notional. The entry fee
        // is not tracked per position, so the round trip is estimated as twice
        // this fill's fee on the closed quantity.
        if let Some((q, entry_notional)) = closed.filter(|c| c.1 > 0.0 && qty > 0.0) {
            let round_trip_fee = 2.0 * fee.max(0.0) * q / qty;
            self.strategies[strat_idx].ledger.edge.record((realized - round_trip_fee) / entry_notional);
        }

        // strategy stats + risk streak tracking
        if realized != 0.0 {
            {
                let s = &mut self.strategies[strat_idx];
                s.pnl += realized;
                s.trades += 1;
                let wins = s.win_rate * (s.trades - 1) as f64 + if realized >= 0.0 { 1.0 } else { 0.0 };
                s.win_rate = wins / s.trades as f64;
                if live {
                    s.ledger.live_trades += 1;
                } else if demo {
                    s.ledger.demo_trades += 1;
                    // Forward evidence only where the demo venue documents
                    // real prices; an own demo book is not the market.
                    if real_price && demo_real {
                        s.ledger.forward_trades += 1;
                    }
                } else if real_price {
                    s.ledger.forward_trades += 1;
                }
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
        {
            let s = &mut self.strategies[strat_idx];
            s.ledger.pnl = s.ledger.breakdown(s.pnl);
        }
        if !self.positions.contains_key(&key) {
            self.ref_prices.remove(&key);
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
        let demo = intent == RouteIntent::Demo;
        // One position per market: real, demo and paper fills must never be
        // booked into each other's position. Exits are never refused here.
        if let Some(why) = self.mixed_book_reason(m, intent) {
            self.refuse_mixed(strat_idx, m, &why);
            return;
        }
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
        if demo {
            if let Some(reason) = self.demo_block_reason(m) {
                let sid = self.strategies[strat_idx].id.clone();
                // Closing a demo position whose demo keys are gone: no money
                // is at stake, and a position nothing can ever close is
                // worse than a simulated exit that says what it is.
                let closes_demo = self
                    .positions
                    .get(&m.id)
                    .is_some_and(|p| p.demo && p.qty != 0.0 && (p.qty > 0.0) == (side == Side::Sell));
                if closes_demo {
                    self.log(
                        JournalKind::Risk,
                        format!(
                            "{}: demo route unavailable ({reason}). The exit is SIMULATED; the demo account may \
                             still hold the position",
                            m.symbol
                        ),
                        Some(sid),
                        Some(m.id.clone()),
                    );
                    if let Some(p) = self.positions.get_mut(&m.id) {
                        p.demo = false;
                    }
                    return self.fill(strat_idx, m, side, qty, price);
                }
                let mut order = self.build_order(&sid, m, side, qty, OrderStatus::Rejected, Some(reason.clone()));
                order.route = FillRoute::Demo;
                self.orders.insert(0, order);
                self.live_backoff_until.insert(m.id.clone(), self.now() + LIVE_REJECT_BACKOFF_MS);
                self.log(JournalKind::Reject, format!("DEMO order refused for {}: {reason}", m.symbol), Some(sid), Some(m.id.clone()));
                return;
            }
        }

        // Session / account gate (Alpaca only: the broker status describes the
        // US equity session and the Alpaca account, and crypto trades 24/7).
        // An *entry* into a closed or restricted market is refused outright; a
        // reduction of an existing position is always allowed through, because
        // refusing to let a position close is the more dangerous failure.
        // `dry_run` bypasses the gate — nothing is sent, and being able to
        // rehearse outside market hours is the point of dry-run.
        // Only a *real* position can be reduced at the venue; a paper one
        // there is invisible to the broker.
        // A demo position is reduced at the demo venue, a real one at the
        // real venue; a paper one is invisible to both.
        let reduces = intent == RouteIntent::LiveExit
            || self
                .positions
                .get(&m.id)
                .map(|p| (if demo { p.demo } else { p.live }) && p.qty != 0.0 && (p.qty > 0.0) == (side == Side::Sell))
                .unwrap_or(false);
        // Demo orders face the same session gate: an equity order queued
        // overnight is a gamble on the gap whether the money is real or not,
        // and the demo record should say what a live order would have met.
        // `dry_run` belongs to the live arm and never skips it for demo.
        let dry_run = self.live.dry_run && !demo;
        if m.venue == Venue::Alpaca && !dry_run && !reduces {
            if let Some(reason) = self.live_block_reason_for(m) {
                let sid = self.strategies[strat_idx].id.clone();
                let mut order = self.build_order(&sid, m, side, qty, OrderStatus::Rejected, Some(reason.clone()));
                if demo {
                    order.route = FillRoute::Demo;
                }
                self.orders.insert(0, order);
                self.log(
                    JournalKind::Reject,
                    format!("{} entry blocked for {}: {reason}", if demo { "DEMO" } else { "Live" }, m.symbol),
                    Some(sid),
                    Some(m.id.clone()),
                );
                return;
            }
        }

        let sid = self.strategies[strat_idx].id.clone();
        // How hard to push. An exit is urgent by definition: not filling leaves
        // a real position exposed, which is a cost the policy has to weigh.
        let exec_ctx = bandit::ExecContext {
            venue: m.venue,
            urgent: intent == RouteIntent::LiveExit,
        };
        // Demo always crosses: its fills never teach the policy (a demo book
        // says little about how a resting order would do at the real venue),
        // so it must not spend the policy's exploration either.
        let style = if demo { bandit::ExecStyle::Cross } else { self.exec_policy.choose(&exec_ctx) };
        let patience_bps = self.exec_policy.patience_bps();
        // What the cost model expects this order to lose against arrival. A
        // resting order is not expected to pay the spread at all. A demo
        // order is priced with the costs of the demo exchange.
        let cost_venue = if demo { self.demo_cost_venue(m) } else { self.cost_venue(m) };
        let cost = self.exec_cost_at(m, side, cost_venue);
        let (modelled_bps, cost_source) = match style {
            bandit::ExecStyle::Cross => (cost.slippage_bps(qty * price), cost.source),
            bandit::ExecStyle::Join | bandit::ExecStyle::Passive => (0.0, CostSource::Default),
        };
        let drift_bps = cost.book.and_then(|b| b.drift_bps(side, price));

        let mut order = self.build_order(&sid, m, side, qty, OrderStatus::Pending, None);
        order.route = if demo || self.live.paper { FillRoute::Demo } else { FillRoute::Live };
        order.cost_source = Some(cost_source);
        order.drift_bps = drift_bps;
        let order_id = order.id.clone();
        let client_order_id = format!("pythia-{}-{order_id}", self.boot_tag);
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
                client_order_id: client_order_id.clone(),
                submitted_at: self.now(),
                booked_qty: 0.0,
                booked_fee: 0.0,
                // The live arm's endpoint choice; a demo order has its own
                // world and ignores it.
                paper: self.live.paper && !demo,
                cancel_sent: false,
                arrival: price,
                style,
                exec_ctx,
                cost_venue,
                modelled_bps,
                cost_source,
                demo,
                drift_bps,
            },
        );
        self.pending_live.push(LiveOrderOut {
            client_order_id,
            order_id,
            venue: m.venue,
            market_id: m.id.clone(),
            symbol: m.symbol.clone(),
            side,
            qty,
            ref_price: price,
            strategy_id: sid.clone(),
            reduce_only: reduces,
            style,
            patience_bps,
            paper: self.live.paper && !demo,
            dry_run,
            // Only when the broker actually reports an extended session running
            // — never inferred from the local clock. Equities only.
            extended_hours: m.venue == Venue::Alpaca
                && m.kind == MarketKind::Equity
                && self.live.extended_hours
                && self.broker.as_ref().map(|b| !b.market_open && b.extended_open).unwrap_or(false),
            demo,
        });
        let dest = if demo { "DEMO" } else { self.live_dest() };
        self.log(
            JournalKind::Order,
            format!("{dest} submit {side:?} {qty:.4} {} @ ~{price:.2}", m.symbol),
            Some(sid),
            Some(m.id.clone()),
        );
    }

    /// Why an order with `intent` would mix books in `m`, or `None`. The
    /// engine keeps one position per market, so a demo fill booked into a
    /// paper position (or a paper fill into a demo one, or anything into a
    /// real one) would leave a position that is neither. An order on the
    /// position's own route (which is how its exits are sent) never mixes.
    fn mixed_book_reason(&self, m: &Market, intent: RouteIntent) -> Option<String> {
        let p = self.positions.get(&m.id).filter(|p| p.qty.abs() > 1e-12)?;
        let held = if p.live {
            "a REAL position"
        } else if p.demo {
            "a demo position"
        } else {
            "a paper position"
        };
        let mixes = match intent {
            // A demo order may only touch a demo position (or open one).
            RouteIntent::Demo => !p.demo,
            // A paper fill may not touch a demo position; an exit of one is
            // routed demo by `exit_intent`. (A paper fill next to a real
            // position keeps the rules it always had.)
            RouteIntent::Paper => p.demo,
            // Live and live exits keep their existing rules, except that a
            // demo position is never fed with or closed by real money.
            RouteIntent::Live | RouteIntent::LiveExit => p.demo,
        };
        mixes.then(|| {
            format!(
                "{} holds {held}; a {} order may not be booked into it. One position per market: close it \
                 first, or trade another market",
                m.symbol,
                match intent {
                    RouteIntent::Demo => "demo",
                    RouteIntent::Paper => "paper",
                    _ => "live",
                }
            )
        })
    }

    /// Say once a minute per market that an order was refused for mixing
    /// books. A strategy that keeps signalling must not flood the journal.
    fn refuse_mixed(&mut self, strat_idx: usize, m: &Market, why: &str) {
        let now = self.now();
        let key = format!("mix:{}", m.id);
        if self.live_warned_at.get(&key).is_some_and(|&t| now - t < 60_000) {
            return;
        }
        self.live_warned_at.insert(key, now);
        let sid = self.strategies[strat_idx].id.clone();
        self.log(JournalKind::Reject, format!("Order refused: {why}"), Some(sid), Some(m.id.clone()));
    }

    /// The route that closes or trims a position: back to the world it came
    /// from.
    fn exit_intent(p: &PositionInternal) -> RouteIntent {
        if p.live {
            RouteIntent::LiveExit
        } else if p.demo {
            RouteIntent::Demo
        } else {
            RouteIntent::Paper
        }
    }

    /// Why a demo order on `m` cannot be sent right now, or `None`.
    fn demo_block_reason(&self, m: &Market) -> Option<String> {
        if m.venue == Venue::Polymarket {
            return Some("Polymarket has no demo environment".into());
        }
        if !self.demo_venues.contains(&m.venue) {
            return Some(match m.venue {
                Venue::Alpaca => "no Alpaca paper keys: demo on Alpaca is the paper account".into(),
                _ => "no demo exchange keys: add Bybit, OKX or Binance demo keys in Settings → Exchanges".into(),
            });
        }
        None
    }

    /// Whose costs a demo order on `m` is modelled with: the demo exchange for
    /// crypto, the venue itself otherwise.
    fn demo_cost_venue(&self, m: &Market) -> CostVenue {
        match m.venue {
            Venue::Crypto => self.crypto_demo_venue.unwrap_or(self.crypto_venue),
            v => CostVenue::for_venue(v, None),
        }
    }

    /// [`Engine::exec_cost`] for an explicit cost venue.
    fn exec_cost_at(&self, m: &Market, side: Side, venue: CostVenue) -> ExecCost {
        ExecCost::for_order(costs::model_for(venue, &m.symbol), venue, self.books.get(&m.id), side, self.now())
    }

    /// Tell the engine which venues have demo keys, which exchange crypto demo
    /// orders go to, and whether that exchange documents real prices. Hosts
    /// call this whenever credentials change, next to `set_connected`.
    pub fn set_demo_venues(&mut self, venues: HashSet<Venue>, crypto: Option<CostVenue>, crypto_real_prices: bool) {
        let changed = venues != self.demo_venues || crypto != self.crypto_demo_venue;
        self.demo_venues = venues;
        self.crypto_demo_venue = crypto;
        self.crypto_demo_real_prices = crypto_real_prices;
        if changed && !self.demo_venues.is_empty() {
            let mut names: Vec<String> = self
                .demo_venues
                .iter()
                .map(|v| match (v, crypto) {
                    (Venue::Crypto, Some(c)) => format!("{} demo", c.id()),
                    (Venue::Alpaca, _) => "Alpaca paper".to_string(),
                    (v, _) => format!("{v:?} demo"),
                })
                .collect();
            names.sort();
            self.log(JournalKind::System, format!("Demo route ready: {}", names.join(", ")), None, None);
        }
    }

    /// Venues the demo route can reach.
    pub fn demo_venues(&self) -> Vec<Venue> {
        let mut v: Vec<Venue> = self.demo_venues.iter().copied().collect();
        v.sort_by_key(|v| format!("{v:?}"));
        v
    }

    /// Place one order on behalf of `strategy_id` through the risk manager and
    /// the router. This is the entry point for code outside the engine's own
    /// strategy loop (the Autopilot): `RouteIntent::Paper` simulates it,
    /// `RouteIntent::Demo` sends it to the venue's demo environment. Live is
    /// deliberately not accepted here: real money moves only for a strategy
    /// whose state is Live (green passport) or the connection test.
    ///
    /// `notional` is in quote currency at the current price. Returns the
    /// approved quantity, or why nothing was routed. "Routed" is not "filled":
    /// a demo order fills when the venue says so, and its row and journal
    /// lines say what happened.
    pub fn place_order(
        &mut self,
        strategy_id: &str,
        market_id: &str,
        side: Side,
        notional: f64,
        intent: RouteIntent,
    ) -> Result<f64, String> {
        if !matches!(intent, RouteIntent::Paper | RouteIntent::Demo) {
            return Err("place_order routes paper or demo only; live goes through a Live strategy".into());
        }
        let idx = self
            .strategies
            .iter()
            .position(|s| s.id == strategy_id)
            .ok_or_else(|| format!("unknown strategy {strategy_id}"))?;
        let m = self.markets.iter().find(|m| m.id == market_id).cloned().ok_or_else(|| format!("unknown market {market_id}"))?;
        if !(m.price > 0.0) || !(notional > 0.0) || !notional.is_finite() {
            return Err(format!("nothing to size: price {} notional {notional}", m.price));
        }
        if intent == RouteIntent::Demo {
            if let Some(why) = self.demo_block_reason(&m) {
                return Err(why);
            }
            if self.in_flight_markets.contains(&m.id) {
                return Err(format!("{} already has an order in flight", m.symbol));
            }
            if self.live_backoff_until.get(&m.id).is_some_and(|&until| self.now() < until) {
                return Err(format!("{} was refused by the venue a moment ago; backing off", m.symbol));
            }
        }
        if let Some(why) = self.mixed_book_reason(&m, intent) {
            return Err(why);
        }
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
        let ctx = self.risk_ctx(&m.id, strategy_id, m.price);
        let decision = risk::evaluate(&req, m.price, &self.limits, &ctx);
        if !decision.approved {
            let reason = decision.reason.unwrap_or_default();
            let mut order = self.build_order(strategy_id, &m, side, qty, OrderStatus::Rejected, Some(reason.clone()));
            if intent == RouteIntent::Demo {
                order.route = FillRoute::Demo;
            }
            self.orders.insert(0, order);
            self.log(JournalKind::Reject, format!("Rejected {}: {reason}", m.symbol), Some(strategy_id.into()), Some(m.id.clone()));
            return Err(reason);
        }
        self.route_fill(idx, &m, side, decision.qty, m.price, intent);
        Ok(decision.qty)
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

    /// Walk the live-routing chain for every Alpaca market and report where it
    /// stops.
    ///
    /// The engine already knows why it isn't trading — the information was just
    /// scattered across a rejection in the journal, a strategy's state field, a
    /// bar timestamp and a risk check that runs too late to see. This assembles
    /// the same answer up front, per market, so "nothing is happening" becomes
    /// a specific sentence instead of a guess.
    pub fn live_diagnostics(&self) -> Vec<MarketDiag> {
        let now = self.now();
        let snapshot: HashMap<String, Market> =
            self.markets.iter().map(|m| (m.id.clone(), m.clone())).collect();

        self.markets
            .iter()
            .filter(|m| m.venue == Venue::Alpaca)
            .map(|m| {
                let watchers: Vec<&StrategyConfig> =
                    self.strategies.iter().filter(|s| s.universe.contains(&m.id)).collect();
                let live_watchers: Vec<&StrategyConfig> =
                    watchers.iter().copied().filter(|s| s.state == StrategyState::Live).collect();
                let bars = self.history.get(&m.id).map(|h| h.len()).unwrap_or(0);

                // Ask the live strategies what they'd do right now.
                let mut signal = None;
                for s in &live_watchers {
                    if let Some(i) = strategies::run_strategy(s, &snapshot, &self.history).into_iter().next() {
                        signal = Some(format!("{}: {:?} — {}", s.name, i.side, i.reason));
                        break;
                    }
                }

                // Walk the same gates `tick` applies, in the same order.
                let suppressed = if watchers.is_empty() {
                    Some("no strategy watches this market".into())
                } else if live_watchers.is_empty() {
                    Some(format!(
                        "{} — set it Live to route entries",
                        watchers
                            .iter()
                            .map(|s| format!("{} is {:?}", s.name, s.state).to_lowercase())
                            .collect::<Vec<_>>()
                            .join(", ")
                    ))
                } else if !self.bar_backed.contains(&m.id) {
                    Some("no real candles yet — signals need a live bar feed".into())
                } else if bars < 30 {
                    Some(format!("only {bars} candles; strategies need at least 30"))
                } else if self.positions.contains_key(&m.id) {
                    Some("already holding — entries only open when flat".into())
                } else if self
                    .last_bar_ts
                    .get(&m.id)
                    .is_some_and(|t| self.signalled_bar.get(&m.id) == Some(t))
                {
                    Some("already acted on this candle — waits for the next one".into())
                } else if signal.is_none() {
                    Some("no strategy signal right now (conditions not met)".into())
                } else if let Some(lt) = self.history.get(&m.id).and_then(|h| indicators::roc(h, 60)) {
                    // The trend filter only blocks a signal that fights it.
                    let side = if signal.as_deref().is_some_and(|s| s.contains("Buy")) {
                        Side::Buy
                    } else {
                        Side::Sell
                    };
                    if (lt > 0.01 && side == Side::Sell) || (lt < -0.01 && side == Side::Buy) {
                        Some(format!("signal fights the 60-bar trend ({:+.1}%)", lt * 100.0))
                    } else {
                        self.live_block_reason_for(m)
                    }
                } else {
                    self.live_block_reason_for(m)
                };

                MarketDiag {
                    market_id: m.id.clone(),
                    symbol: m.symbol.clone(),
                    price: m.price,
                    bars,
                    bar_backed: self.bar_backed.contains(&m.id),
                    quote_age_sec: ((now - m.updated_at) / 1000).max(0) as u64,
                    has_position: self.positions.contains_key(&m.id),
                    watchers: watchers.iter().map(|s| s.name.clone()).collect(),
                    live_watchers: live_watchers.len(),
                    signal,
                    suppressed,
                }
            })
            .collect()
    }

    /// Why a one-click test order on `market_id` would not reach its venue
    /// right now, or `None` when it would. Walks the same gates `route_fill`
    /// applies, so the button refuses with a reason instead of silently
    /// paper-filling.
    /// Size of the one-click connection test: twice the venue's minimum order
    /// from the cost model (so rounding cannot push it under), at least $5.
    /// The test proves the pipeline, not a strategy, so it should risk as
    /// little as the venue allows.
    pub fn connection_test_notional(&self, market_id: &str) -> f64 {
        self.markets
            .iter()
            .find(|m| m.id == market_id)
            .map(|m| (self.cost_model(m).min_notional * 2.0).max(5.0))
            .unwrap_or(5.0)
    }

    pub fn test_order_block(&self, market_id: &str) -> Option<String> {
        let Some(m) = self.markets.iter().find(|m| m.id == market_id) else {
            return Some(format!("unknown market {market_id}"));
        };
        if !self.live.armed {
            return Some("live execution is disarmed: arm it first".into());
        }
        if !self.live.venues.contains(&m.venue) {
            return Some(format!("{:?} is not enabled for live routing", m.venue));
        }
        if self.in_flight_markets.contains(&m.id) {
            return Some(format!("{} already has a live order in flight", m.symbol));
        }
        if m.venue == Venue::Alpaca && !self.live.dry_run {
            return self.live_block_reason_for(m);
        }
        None
    }

    // ── AI overlay ──────────────────────────────────────────────────────────

    pub fn set_ai_policy(&mut self, policy: AiPolicy) {
        let on = policy.enabled;
        self.ai_policy = policy;
        self.log(
            JournalKind::System,
            if on {
                "AI overlay ENABLED — model views may shrink or veto entries (never create them)".into()
            } else {
                "AI overlay disabled".to_string()
            },
            None,
            None,
        );
    }

    /// Record a fresh model view and its cost.
    pub fn apply_ai_view(&mut self, view: AiView, input_tokens: u64, output_tokens: u64) {
        self.ai_spend.calls += 1;
        self.ai_spend.input_tokens += input_tokens;
        self.ai_spend.output_tokens += output_tokens;
        let msg = format!(
            "AI {} · {} p={:.2} conf={:.2} ({}ms): {}",
            view.model,
            view.direction,
            view.probability,
            view.confidence,
            view.latency_ms,
            view.rationale.chars().take(160).collect::<String>()
        );
        let mid = view.market_id.clone();
        self.ai.insert(mid.clone(), view);
        self.log(JournalKind::Signal, msg, None, Some(mid));
    }

    /// Note a failed model call so a silently broken overlay is visible.
    pub fn record_ai_error(&mut self, why: &str) {
        self.ai_spend.errors += 1;
        self.log(JournalKind::System, format!("AI overlay error: {why}"), None, None);
    }

    /// The size multiplier the overlay applies to an entry, plus a reason to
    /// journal when it is not 1.0. Returns 0.0 for a veto.
    fn ai_multiplier(&self, market_id: &str, side: Side) -> (f64, Option<String>) {
        if !self.ai_policy.enabled {
            return (1.0, None);
        }
        let Some(v) = self.ai.get(market_id) else { return (1.0, None) };
        if self.now() - v.ts > (self.ai_policy.ttl_sec as i64) * 1000 {
            return (1.0, None); // an opinion past its shelf life is not an opinion
        }
        let agrees = match (v.direction.as_str(), side) {
            ("long", Side::Buy) | ("short", Side::Sell) => Some(true),
            ("long", Side::Sell) | ("short", Side::Buy) => Some(false),
            _ => None, // neutral — no view worth acting on either way
        };
        match agrees {
            None => (1.0, None),
            Some(true) => {
                let boost = 1.0 + (self.ai_policy.max_boost - 1.0) * v.confidence.clamp(0.0, 1.0);
                (boost, Some(format!("AI agrees (conf {:.2}) — size ×{boost:.2}", v.confidence)))
            }
            Some(false) if v.confidence >= self.ai_policy.veto_confidence => (
                0.0,
                Some(format!("AI vetoes: {} at conf {:.2} — {}", v.direction, v.confidence, v.rationale)),
            ),
            Some(false) => {
                let cut = (1.0 - 0.5 * v.confidence.clamp(0.0, 1.0)).max(0.1);
                (cut, Some(format!("AI disagrees (conf {:.2}) — size ×{cut:.2}", v.confidence)))
            }
        }
    }

    /// Build the compact market brief handed to a model. Lives here so the
    /// desktop and server ask identical questions, and so the model only ever
    /// sees real candle-derived numbers — never simulator noise.
    pub fn ai_context(&self, market_id: &str) -> Option<String> {
        let m = self.markets.iter().find(|m| m.id == market_id)?;
        let h = self.history.get(market_id)?;
        if h.len() < 30 {
            return None;
        }
        let mut out = String::new();
        out.push_str(&format!("Market: {} ({:?} on {:?})\n", m.symbol, m.kind, m.venue));
        out.push_str(&format!("Last price: {:.4}\n", m.price));
        out.push_str(&format!("24h change: {:+.2}%\n", m.change24h * 100.0));
        if let Some(r) = m.regime {
            out.push_str(&format!(
                "Regime: {:?} (efficiency ratio {:.2})\n",
                r,
                m.trend_strength.unwrap_or(0.0)
            ));
        }
        out.push_str(&format!(
            "Data source: {}\n",
            if self.bar_backed.contains(market_id) { "real exchange candles" } else { "SIMULATED — treat with suspicion" }
        ));
        for (label, v) in [
            ("RSI(14)", indicators::rsi(h, 14)),
            ("EMA(9)", indicators::ema(h, 9)),
            ("EMA(21)", indicators::ema(h, 21)),
            ("ROC(20)", indicators::roc(h, 20).map(|r| r * 100.0)),
            ("Z-score(20)", indicators::zscore(h, 20)),
        ] {
            if let Some(v) = v {
                out.push_str(&format!("{label}: {v:.4}\n"));
            }
        }
        let recent: Vec<String> =
            h.iter().rev().take(20).rev().map(|c| format!("{c:.4}")).collect();
        out.push_str(&format!("Last 20 closes (oldest→newest): {}\n", recent.join(", ")));
        if let Some(p) = self.positions.get(market_id) {
            out.push_str(&format!(
                "Current position: {:+.4} @ {:.4} (unrealized {:+.2})\n",
                p.qty,
                p.avg_price,
                (m.price - p.avg_price) * p.qty
            ));
        } else {
            out.push_str("Current position: flat\n");
        }
        Some(out)
    }

    /// Markets worth spending a model call on: tradable, bar-backed, and with
    /// enough history to describe. Ordered so the daemon can round-robin.
    pub fn ai_candidates(&self) -> Vec<String> {
        self.markets
            .iter()
            .filter(|m| m.kind != MarketKind::Prediction)
            .filter(|m| self.bar_backed.contains(&m.id))
            .filter(|m| self.history.get(&m.id).map(|h| h.len() >= 30).unwrap_or(false))
            .map(|m| m.id.clone())
            .collect()
    }

    pub fn ai_enabled(&self) -> bool {
        self.ai_policy.enabled
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
        let session = if cfg.extended_hours { " · extended hours enabled" } else { "" };
        let armed = cfg.armed;
        let live_open = self.live_position_count();
        self.live = cfg;

        if armed {
            self.log(JournalKind::Risk, format!("LIVE ARMED — {venues} route to {dest}{session}"), None, None);
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

    /// Turn adaptive execution on or off.
    ///
    /// Off (the default) means every order crosses the spread, exactly as
    /// before. On, the policy may rest orders inside the spread — cheaper when
    /// they fill, and a signal acted on late or not at all when they do not.
    /// That trade-off is the operator's to make, so it is never on by default.
    pub fn set_adaptive_execution(&mut self, on: bool) {
        if self.exec_policy.enabled == on {
            return;
        }
        self.exec_policy.enabled = on;
        self.log(
            JournalKind::System,
            if on {
                "Adaptive execution ON — orders may rest inside the spread and learn from what they cost".into()
            } else {
                "Adaptive execution OFF — every order crosses".to_string()
            },
            None,
            None,
        );
    }

    pub fn adaptive_execution(&self) -> bool {
        self.exec_policy.enabled
    }

    /// Tell the engine which exchange executes `Venue::Crypto`, so paper fills
    /// and the cost comparison use that exchange's fees. `None` keeps Kraken.
    pub fn set_crypto_cost_venue(&mut self, venue: Option<CostVenue>) {
        self.crypto_venue = venue.unwrap_or(CostVenue::Kraken);
        // Books describe the executing exchange's fills, so they follow it.
        self.feeds.set_book_sources(FeedSource::for_books(self.crypto_venue));
    }

    pub fn crypto_cost_venue(&self) -> CostVenue {
        self.crypto_venue
    }

    /// Realised against modelled slippage, per venue with live fills.
    pub fn slippage_report(&self) -> Vec<bandit::SlippageRow> {
        self.exec_policy.slippage_report()
    }

    /// One strategy's configuration, for research runs off the engine lock.
    pub fn strategy_config(&self, id: &str) -> Option<StrategyConfig> {
        self.strategies.iter().find(|s| s.id == id).cloned()
    }

    /// The backtest settings a strategy is researched with: its venue's costs,
    /// its calendar, and the regime filter exactly as the engine applies it.
    pub fn research_bt(&self, cfg: &StrategyConfig) -> crate::research::backtest::BacktestConfig {
        crate::research::bt_for(cfg, self.crypto_venue, self.limits.regime_filter)
    }

    /// Keep freshly computed validation gates 1 to 6 for a strategy.
    pub fn store_research(&mut self, verdict: validation::ResearchVerdict) {
        let id = verdict.strategy_id.clone();
        let passed = verdict.gates.iter().filter(|g| g.passed()).count();
        self.research.insert(id.clone(), verdict);
        self.log(
            JournalKind::System,
            format!("Validation checks for {id}: {passed} of 6 research gates passed"),
            Some(id),
            None,
        );
    }

    /// The Strategy Passport for one strategy.
    pub fn passport(&self, id: &str) -> Option<validation::Passport> {
        self.strategies.iter().find(|s| s.id == id).map(|s| self.passport_for(s))
    }

    fn passport_for(&self, s: &StrategyConfig) -> validation::Passport {
        let venue = CostVenue::for_venue(s.venue_class, Some(self.crypto_venue));
        let slippage = self.exec_policy.slippage_for(venue.id());
        let forward = validation::ForwardRecord {
            paper_since: s.ledger.paper_since,
            trades: s.ledger.forward_trades,
            equities: s.venue_class == Venue::Alpaca,
            now: self.now(),
            slippage: slippage.clone(),
        };
        let live = validation::LiveRecord { trades: s.ledger.live_trades, slippage };
        validation::passport(s, self.research.get(&s.id), &forward, &live)
    }

    /// What the execution policy has learned so far.
    pub fn execution_report(&self) -> Vec<bandit::PolicyRow> {
        self.exec_policy.report()
    }

    fn live_position_count(&self) -> usize {
        self.positions.values().filter(|p| p.live && p.qty.abs() > 1e-9).count()
    }

    /// Real fills since the last call, for the host to append to the tax record.
    pub fn drain_fill_records(&mut self) -> Vec<crate::tax::FillRecord> {
        std::mem::take(&mut self.fill_records)
    }

    /// Put back fills the host could not write, oldest first.
    pub fn requeue_fill_records(&mut self, mut fills: Vec<crate::tax::FillRecord>) {
        fills.append(&mut self.fill_records);
        self.fill_records = fills;
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
                    demo: f.demo,
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
                    // Reference is the arrival price, so a fill better than
                    // arrival books negative slippage.
                    // emit_order = false: the pending order row already exists
                    // and is updated below rather than duplicated.
                    let reference = if f.arrival > 0.0 { f.arrival } else { price };
                    // A demo fill is booked like a paper one (no `live` flag,
                    // so the reconciler and the real-money guards ignore it)
                    // and marks its position demo.
                    self.settle_fill_on(idx, &m, f.side, delta, price, fee_delta, reference, !f.demo, f.demo, false);
                    // The tax record: every REAL fill, for the host to append
                    // to fills.jsonl. Never a demo fill, and never one from
                    // Alpaca's paper endpoint: both are virtual money.
                    if f.route() == FillRoute::Live {
                        self.fill_records.push(crate::tax::FillRecord {
                            ts: chrono::Utc::now().timestamp_millis(),
                            venue: m.venue,
                            market_id: m.id.clone(),
                            symbol: m.symbol.clone(),
                            side: f.side,
                            qty: delta,
                            price,
                            fee: fee_delta,
                            strategy_id: f.strategy_id.clone(),
                            order_id: order_id.to_string(),
                        });
                    }
                    self.log(
                        JournalKind::Fill,
                        format!(
                            "{} FILL {:?} {delta:.6} {} @ {price:.4}",
                            if f.demo { "DEMO" } else { "LIVE" },
                            f.side,
                            m.symbol
                        ),
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
            // A demo order stays in the paper book; its route says demo.
            ord.mode = if f.demo { Mode::Paper } else { Mode::Live };
            ord.route = f.route();
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

        // Tell the execution policy what that choice actually cost. This is the
        // only feedback it gets, and it is the reason the whole thing works:
        // realised slippage against the price at decision time, or a penalty
        // when nothing filled.
        let realised = update.avg_price.filter(|p| *p > 0.0 && update.filled_qty > 0.0);
        // The same observation also lands in the realised-versus-modelled
        // slippage record, next to what the cost model expected.
        let now = self.now();
        let realised_bps = if f.demo {
            // A demo fill is kept for the comparison but never teaches the
            // execution policy, which learns for the real venue.
            let r = realised.and_then(|p| bandit::realised_cost_bps(f.side, f.arrival, p));
            if let Some(bps) = r {
                let mut rec = bandit::FillRecord::new(bps, f.modelled_bps, now, f.cost_source, FillRoute::Demo);
                rec.drift_bps = f.drift_bps;
                self.exec_policy.record_fill(f.cost_venue.id(), rec);
            }
            r
        } else {
            self.exec_policy.observe_against_model(
                &f.exec_ctx,
                f.style,
                f.side,
                f.arrival,
                realised,
                f.cost_venue.id(),
                f.modelled_bps,
                f.cost_source,
                now,
            )
        };
        if let (Some(bps), Some(ord)) = (realised_bps, self.orders.iter_mut().find(|x| x.id == order_id)) {
            ord.realised_slippage_bps = Some(bps);
            ord.modelled_slippage_bps = Some(f.modelled_bps);
        }

        if update.filled_qty <= 0.0 {
            let reason = format!("{} ({})", update.status_word(), update.raw_status);
            if let Some(ord) = self.orders.iter_mut().find(|x| x.id == order_id) {
                ord.reject_reason = Some(reason.clone());
            }
            self.log(
                JournalKind::Reject,
                format!("{} order {} {}: nothing filled", if f.demo { "DEMO" } else { "LIVE" }, f.symbol, reason),
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
        let what = if f.as_ref().is_some_and(|f| f.demo) { "DEMO" } else { "LIVE" };
        self.log(
            JournalKind::Reject,
            format!("{what} order not sent{}: {reason}", if symbol.is_empty() { String::new() } else { format!(" ({symbol})") }),
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
    ///
    /// Returns how many positions changed, so a host can log it.
    pub fn reconcile_positions(&mut self, venue: Venue, broker: &[BrokerPosition], adopt_unknown: bool) -> usize {
        let mut changes = 0usize;
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
            // An order still out in this market may already be (partly) in the
            // venue's position but not yet in our book. Setting the book to the
            // venue now and then booking the order's fill report would count
            // that fill twice. The order's own report settles it; the next
            // reconciliation after it is done checks the result.
            if self.in_flight_markets.contains(&market_id) {
                continue;
            }
            // A demo position belongs to the demo account. Alpaca's paper
            // account can be both the demo route and the live arm's paper
            // endpoint, and its holdings must never turn a demo position into
            // a "real" one.
            if self.positions.get(&market_id).is_some_and(|p| p.demo) {
                continue;
            }
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
                    // Stops were sized for the old quantity; recompute on the
                    // next tick rather than trusting stale levels.
                    p.stop = 0.0;
                    p.target = 0.0;
                    p.trail_ref = avg;
                    // The broker's average is the only entry we know now.
                    self.ref_prices.remove(&market_id);
                    changes += 1;
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
                            demo: false,
                        },
                    );
                    changes += 1;
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
            .filter(|(id, p)| p.venue == venue && p.live && !seen.contains(*id) && !self.in_flight_markets.contains(*id))
            .map(|(id, _)| id.clone())
            .collect();
        for id in vanished {
            self.positions.remove(&id);
            self.ref_prices.remove(&id);
            changes += 1;
            self.log(
                JournalKind::Risk,
                format!("{id} is no longer held at {venue:?} — dropped from the book"),
                None,
                Some(id.clone()),
            );
        }

        if changes > 0 {
            self.pending_alerts
                .push(format!("⚠ Pythia reconciled {changes} position difference(s) with {venue:?}"));
        }
        changes
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
            extended_hours: self.live.extended_hours,
            alpaca_connected: self.connected.contains(&Venue::Alpaca),
            connected,
            pending: self.inflight.len(),
            live_positions: self.live_position_count(),
            broker: self.broker.clone(),
            // Only meaningful once Alpaca is armed; before that the answer is
            // always "nothing is going live there anyway".
            blocked_reason: if self.live_routable(Venue::Alpaca) { self.live_block_reason() } else { None },
            demo_venues: self.demo_venues(),
            demo_exchange: self.demo_venues.contains(&Venue::Crypto).then_some(self.crypto_demo_venue).flatten(),
            demo_positions: self.positions.values().filter(|p| p.demo && p.qty.abs() > 1e-9).count(),
        }
    }

    // ── manual actions (from the UI) ────────────────────────────────────────

    /// A Buy/Sell click. Practice only: it never reaches a real venue.
    ///
    /// Real money moves for two reasons and no others: a strategy whose Strategy
    /// Passport is green, or the one-click connection test. A hand-placed order
    /// has no passport, so on a venue that is armed for live routing it is
    /// refused with the reason in the journal. It is deliberately not turned
    /// into a paper fill there: next to a red "real money" banner, a filled
    /// order would read as a real one. Disarmed, it paper-trades as before.
    /// Closing a position (`flatten`) is never blocked.
    pub fn manual_order(&mut self, market_id: &str, side: Side, notional: f64) {
        let Some(m) = self.markets.iter().find(|m| m.id == market_id).cloned() else { return };
        if self.live_routable(m.venue) {
            let reason = "manual orders never go live: only a strategy with a green Strategy Passport, \
                          or the connection test, may send a real order. Disarm to practise by hand"
                .to_string();
            let qty = notional / m.price;
            let order = self.build_order("manual", &m, side, qty, OrderStatus::Rejected, Some(reason.clone()));
            self.orders.insert(0, order);
            self.log(JournalKind::Reject, format!("Manual order refused: {reason}"), Some("manual".into()), Some(m.id.clone()));
            return;
        }
        self.place_manual(&m, side, notional, RouteIntent::Paper);
    }

    /// The one-click connection test: the smallest order the venue accepts, sent
    /// live to prove the pipeline. The only order without a passport that may
    /// reach a real venue, and only when `test_order_block` has nothing against it.
    pub fn connection_test_order(&mut self, market_id: &str, notional: f64) -> Result<(), String> {
        if let Some(why) = self.test_order_block(market_id) {
            return Err(why);
        }
        let Some(m) = self.markets.iter().find(|m| m.id == market_id).cloned() else {
            return Err(format!("unknown market {market_id}"));
        };
        self.log(
            JournalKind::System,
            format!("Connection test: {} for ${notional:.2}, the venue minimum, not a strategy", m.symbol),
            Some("manual".into()),
            Some(m.id.clone()),
        );
        self.place_manual(&m, Side::Buy, notional, RouteIntent::Live);
        Ok(())
    }

    /// Why a demo connection test on `market_id` would not reach the demo
    /// venue right now, or `None`. Needs demo keys, not the live arm.
    pub fn demo_test_block(&self, market_id: &str) -> Option<String> {
        let Some(m) = self.markets.iter().find(|m| m.id == market_id) else {
            return Some(format!("unknown market {market_id}"));
        };
        if let Some(why) = self.demo_block_reason(m) {
            return Some(why);
        }
        if self.in_flight_markets.contains(&m.id) {
            return Some(format!("{} already has an order in flight", m.symbol));
        }
        if let Some(why) = self.mixed_book_reason(m, RouteIntent::Demo) {
            return Some(why);
        }
        if m.venue == Venue::Alpaca {
            return self.live_block_reason_for(m);
        }
        None
    }

    /// [`Engine::connection_test_notional`] on the demo exchange's minimum.
    pub fn demo_test_notional(&self, market_id: &str) -> f64 {
        self.markets
            .iter()
            .find(|m| m.id == market_id)
            .map(|m| (costs::model_for(self.demo_cost_venue(m), &m.symbol).min_notional * 2.0).max(5.0))
            .unwrap_or(5.0)
    }

    /// The connection test against a venue's demo environment: one buy at the
    /// venue minimum through the full demo path (keys, signing, preflight,
    /// submit, poll, fill), with virtual money. Passes the risk manager like
    /// any order. Proves the demo pipeline before a strategy relies on it.
    pub fn demo_connection_test_order(&mut self, market_id: &str, notional: f64) -> Result<(), String> {
        if let Some(why) = self.demo_test_block(market_id) {
            return Err(why);
        }
        let Some(m) = self.markets.iter().find(|m| m.id == market_id).cloned() else {
            return Err(format!("unknown market {market_id}"));
        };
        self.log(
            JournalKind::System,
            format!("DEMO connection test: {} for ${notional:.2} with virtual money", m.symbol),
            Some("manual".into()),
            Some(m.id.clone()),
        );
        self.place_manual(&m, Side::Buy, notional, RouteIntent::Demo);
        Ok(())
    }

    /// Engine-internal tests drive the live-routing machinery through this, now
    /// that a manual click no longer can.
    #[cfg(test)]
    pub(crate) fn live_order_for_test(&mut self, market_id: &str, side: Side, notional: f64) {
        let Some(m) = self.markets.iter().find(|m| m.id == market_id).cloned() else { return };
        self.place_manual(&m, side, notional, RouteIntent::Live);
    }

    fn place_manual(&mut self, m: &Market, side: Side, notional: f64, intent: RouteIntent) {
        let m = m.clone();
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
        self.route_fill(idx, &m, side, decision.qty, m.price, intent);
    }

    // ── lab strategies: Python decides, Rust executes (see crate::lab) ──────

    /// Install the latest signal for a lab strategy. The first signal creates
    /// the strategy in Paper; its gates 1 to 6 come from the lab's evidence,
    /// gate 7 from its paper record here, like every other strategy.
    pub fn apply_lab_signal(&mut self, sig: crate::lab::LabSignal) {
        let id = format!("lab:{}", sig.strategy);
        if !self.strategies.iter().any(|s| s.id == id) {
            let universe = self.markets.iter().filter(|m| m.venue == Venue::Crypto).map(|m| m.id.clone()).collect();
            self.strategies.push(StrategyConfig {
                id: id.clone(),
                name: format!("Lab · {}", sig.variant),
                kind: StrategyKind::LabTargets,
                venue_class: Venue::Crypto,
                state: StrategyState::Paper,
                universe,
                params: vec![],
                budget_pct: 30.0,
                pnl: 0.0,
                trades: 0,
                win_rate: 0.0,
                max_drawdown: 0.0,
                profit_factor: 0.0,
                equity_curve: vec![0.0],
                rules: None,
                ledger: StrategyLedger::default(),
            });
            self.log(
                JournalKind::System,
                format!("Lab strategy {} added in Paper: target weights from the research lab, executed here", sig.variant),
                Some(id.clone()),
                None,
            );
        }
        let verdict = crate::lab::verdict(&id, vec![], &sig.evidence, self.now());
        self.research.insert(id.clone(), verdict);
        self.lab_signals.insert(id, sig);
    }

    /// Move every lab book to its latest targets, once per signal.
    fn run_lab_books(&mut self) {
        let now = self.now();
        let ids: Vec<(usize, String)> = self
            .strategies
            .iter()
            .enumerate()
            .filter(|(_, s)| s.kind == StrategyKind::LabTargets && s.state != StrategyState::Paused)
            .map(|(i, s)| (i, s.id.clone()))
            .collect();
        for (idx, sid) in ids {
            let Some(sig) = self.lab_signals.get(&sid).cloned() else { continue };
            if self.lab_done.get(&sid) == Some(&sig.generated_ms) {
                continue;
            }
            // Inside an autopilot: its capital, its positions, and nothing
            // while it is paused.
            let scope = self.autopilot_lab_scope(&sid);
            if scope.as_ref().is_some_and(|s| !s.running) {
                continue;
            }
            let attempt = match self.lab_retry.get(&sid) {
                Some(&(g, n, last)) if g == sig.generated_ms => {
                    if now - last < LAB_RETRY_EVERY_MS {
                        continue;
                    }
                    n + 1
                }
                _ => 1,
            };
            if !sig.is_fresh(now) {
                if self.lab_notes.insert(format!("stale:{sid}:{}", sig.generated_ms)) {
                    self.log(
                        JournalKind::System,
                        "Lab signal is past its validity window; holding positions as they are until a fresh one arrives".into(),
                        Some(sid.clone()),
                        None,
                    );
                }
                continue;
            }
            // Only real prices: a rebalance against the simulator is no evidence of anything.
            let crypto: Vec<Market> = self.markets.iter().filter(|m| m.venue == Venue::Crypto).cloned().collect();
            if !crypto.iter().any(|m| self.real_ids.contains(&m.id)) {
                if self.lab_notes.insert(format!("noprices:{sid}")) {
                    self.log(JournalKind::System, "Lab book waits for real crypto prices".into(), Some(sid.clone()), None);
                }
                continue;
            }
            let mut owned_elsewhere = vec![];
            let mut prices = HashMap::new();
            // A position is this book's when the strategy holds it and, inside
            // an autopilot, the autopilot owns it.
            let mine = |id: &str, p: &PositionInternal| {
                p.strategy_id == sid && scope.as_ref().is_none_or(|s| s.owned.contains(id))
            };
            for m in &crypto {
                match self.positions.get(&m.id) {
                    Some(p) if !mine(&m.id, p) && p.qty.abs() > 1e-12 => owned_elsewhere.push(m.symbol.clone()),
                    // A market an autopilot reserved for someone else.
                    None if !self.autopilot_entry_allowed(&sid, &m.id) => owned_elsewhere.push(m.symbol.clone()),
                    _ if self.real_ids.contains(&m.id) => {
                        prices.insert(m.id.clone(), m.price);
                    }
                    _ => {}
                }
            }
            let holdings: HashMap<String, (f64, f64)> = self
                .positions
                .iter()
                .filter(|(k, p)| mine(k, p))
                .map(|(k, p)| (k.clone(), (p.qty, p.avg_price)))
                .collect();
            let capital = match &scope {
                Some(s) => s.capital,
                None => self.strategies[idx].budget_pct / 100.0 * self.equity(),
            };
            let has_market = |coin: &str| -> Option<String> { Some(format!("crypto:{coin}/USD")) };
            let (orders, mut untradable) =
                crate::lab::rebalance(&sig.weights, has_market, &holdings, &prices, capital, 5.0, 0.002);
            // A coin held by another strategy is reported as that, not as missing.
            untradable.retain(|c| !owned_elsewhere.iter().any(|s| s == &format!("{c}/USD")));
            let n = orders.len();
            let mut refused = 0;
            for o in orders {
                let Some(m) = crypto.iter().find(|m| m.id == o.market_id).cloned() else { continue };
                if !self.place_lab_order(idx, &m, o.side, o.notional) {
                    refused += 1;
                }
            }
            let day = chrono::DateTime::from_timestamp_millis(sig.as_of_ms)
                .map(|d| d.format("%Y-%m-%d").to_string())
                .unwrap_or_default();
            // A refused order is often passing trouble (stale data for a few
            // seconds, the order rate limit). Losing a whole day's rebalance to
            // it would make the forward test drift from the lab book, so try
            // again later while the signal is still valid. The next attempt is
            // computed from the holdings as they are then, so whatever did fill
            // is not ordered twice.
            if refused > 0 && attempt < LAB_RETRY_MAX {
                self.lab_retry.insert(sid.clone(), (sig.generated_ms, attempt, now));
                self.log(
                    JournalKind::Risk,
                    format!(
                        "Rebalance toward the lab's weights of {day}: {refused} of {n} orders refused, trying again in {} minutes (attempt {attempt} of {LAB_RETRY_MAX})",
                        LAB_RETRY_EVERY_MS / 60_000
                    ),
                    Some(sid),
                    None,
                );
                continue;
            }
            self.lab_retry.remove(&sid);
            self.lab_done.insert(sid.clone(), sig.generated_ms);
            let mut note = format!(
                "Rebalanced toward the lab's weights of {day}: {n} orders, {:.0} % of the book invested",
                sig.weights.values().sum::<f64>() * 100.0
            );
            if refused > 0 {
                note.push_str(&format!("; {refused} still refused after {attempt} attempts, left until the next signal"));
            }
            if !untradable.is_empty() {
                note.push_str(&format!("; no market here for {}", untradable.join(", ")));
            }
            if !owned_elsewhere.is_empty() {
                note.push_str(&format!("; left alone because another strategy holds them: {}", owned_elsewhere.join(", ")));
            }
            self.log(JournalKind::Signal, note, Some(sid), None);
        }
    }

    /// One rebalance order for a lab book: the same risk check and routing as any
    /// strategy (Live only if the strategy is Live, which needs its passport).
    /// Lab positions carry no ATR stops: the backtest had none, and a stop the
    /// lab never tested would make this a different strategy from the one judged.
    /// `false` when the order did not go out (no price, or the risk check refused it).
    fn place_lab_order(&mut self, idx: usize, m: &Market, side: Side, notional: f64) -> bool {
        if m.price <= 0.0 {
            return false;
        }
        let sid = self.strategies[idx].id.clone();
        let qty = notional / m.price;
        let req = crate::connectors::OrderRequest {
            symbol: m.symbol.clone(),
            side,
            order_type: OrderType::Market,
            qty,
            limit_price: None,
            ref_price: Some(m.price),
            client_order_id: None,
            reduce_only: side == Side::Sell,
        };
        let ctx = self.risk_ctx(&m.id, &sid, m.price);
        let decision = risk::evaluate(&req, m.price, &self.limits, &ctx);
        if !decision.approved {
            let reason = decision.reason.unwrap_or_default();
            let order = self.build_order(&sid, m, side, qty, OrderStatus::Rejected, Some(reason.clone()));
            self.orders.insert(0, order);
            self.log(JournalKind::Reject, format!("Rejected {}: {reason}", m.symbol), Some(sid), Some(m.id.clone()));
            return false;
        }
        let route = self
            .autopilot_route(&sid)
            .unwrap_or_else(|| Self::entry_intent(self.strategies[idx].state));
        self.route_fill(idx, m, side, decision.qty, m.price, route);
        if let Some(p) = self.positions.get_mut(&m.id) {
            if p.strategy_id == sid {
                p.stop = 0.0;
                p.target = 0.0;
            }
        }
        true
    }

    pub fn flatten(&mut self, market_id: &str) {
        let Some(pos) = self.positions.get(market_id) else { return };
        let qty = pos.qty.abs();
        let side = if pos.qty > 0.0 { Side::Sell } else { Side::Buy };
        let live = pos.live; // a live-opened position must be closed live too
        let intent = Self::exit_intent(pos); // and a demo one at the demo venue
        let Some(m) = self.markets.iter().find(|m| m.id == market_id).cloned() else { return };
        let idx = self.ensure_manual_strategy();
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
            ledger: StrategyLedger::default(),
        });
        self.strategies.len() - 1
    }

    /// Add a strategy at runtime (e.g. a composed strategy deployed from the UI).
    pub fn add_strategy(&mut self, mut cfg: StrategyConfig) {
        if self.strategies.iter().any(|s| s.id == cfg.id) {
            return;
        }
        // A deployed strategy starts with a clean record, whatever the caller
        // sent: costs and forward-test evidence are earned here, not imported.
        cfg.ledger = StrategyLedger::default();
        // A new strategy has no passport, so it cannot arrive live.
        if cfg.state == StrategyState::Live {
            cfg.state = StrategyState::Paper;
        }
        if cfg.state != StrategyState::Paused {
            cfg.ledger.paper_since = Some(self.now());
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
    /// Pause, paper-trade or arm a strategy.
    ///
    /// Live is refused until the strategy's passport shows gates 1 to 7 green
    /// (`PROFIT-PLAN.md` §2), and the refusal says which gate and why. The
    /// one-click connection test on the Live page is not a strategy and does
    /// not go through here.
    pub fn set_strategy_state(&mut self, id: &str, state: StrategyState) -> Result<(), String> {
        // While an autopilot runs a strategy, the autopilot sets its state.
        if let Some(ap) = self.autopilot_claimant(id) {
            let name = self.strategies.iter().find(|s| s.id == id).map(|s| s.name.clone()).unwrap_or_else(|| id.to_string());
            return Err(format!("{name} runs in the autopilot \"{ap}\", which sets its state. Pause the autopilot to hold it, or stop it to change the strategy."));
        }
        // Demo needs no passport (no money moves) but does need a demo
        // environment for the strategy's venue, or every signal would be a
        // refusal.
        if state == StrategyState::Demo {
            let Some(s) = self.strategies.iter().find(|s| s.id == id) else {
                return Err(format!("unknown strategy {id}"));
            };
            let venue = s.venue_class;
            let why = match venue {
                Venue::Polymarket => Some("Polymarket has no demo environment".to_string()),
                v if !self.demo_venues.contains(&v) => Some(format!(
                    "no demo keys for {v:?}: add {} in Settings first",
                    if v == Venue::Alpaca { "Alpaca paper keys" } else { "Bybit, OKX or Binance demo keys" }
                )),
                _ => None,
            };
            if let Some(why) = why {
                let name = s.name.clone();
                self.log(JournalKind::Reject, format!("{name} cannot demo-trade: {why}"), Some(id.to_string()), None);
                return Err(why);
            }
        }
        if state == StrategyState::Live {
            let Some(s) = self.strategies.iter().find(|s| s.id == id) else {
                return Err(format!("unknown strategy {id}"));
            };
            let pp = self.passport_for(s);
            if !pp.live_ready {
                let why = pp.blocked_reason.unwrap_or_else(|| "the validation gates are not green".into());
                let name = s.name.clone();
                self.log(JournalKind::Reject, format!("{name} stays off live. {why}"), Some(id.to_string()), None);
                return Err(why);
            }
        }
        self.apply_strategy_state(id, state);
        Ok(())
    }

    /// The state change itself, after any gate has been checked.
    fn apply_strategy_state(&mut self, id: &str, state: StrategyState) {
        let now = self.now();
        if let Some(s) = self.strategies.iter_mut().find(|s| s.id == id) {
            s.state = state;
            if state != StrategyState::Paused && s.ledger.paper_since.is_none() {
                s.ledger.paper_since = Some(now);
            }
            let name = s.name.clone();
            self.log(JournalKind::System, format!("Strategy {name} → {state:?}"), Some(id.to_string()), None);
        }
    }
    /// Change one parameter. Different parameters are a different strategy as
    /// far as the evidence goes, so this is also the one trigger that starts
    /// the edge record over (the passport's research gates go stale on the
    /// same comparison), and the only way back for a strategy sized to zero
    /// for no edge: see the comment above [`risk::MIN_EDGE_TRADES`].
    pub fn set_strategy_param(&mut self, id: &str, key: &str, value: f64) {
        let Some(idx) = self.strategies.iter().position(|s| s.id == id) else { return };
        let Some(p) = self.strategies[idx].params.iter_mut().find(|p| p.key == key) else { return };
        // A slider sends every step; the same value again changes nothing.
        if (p.value - value).abs() < 1e-12 {
            return;
        }
        p.value = value;
        let now = self.now();
        self.restart_edge_record(idx, key, now);
    }

    /// Start a strategy's edge record over after a parameter change, saying
    /// what was dropped, and take a live strategy back to paper: its research
    /// gates judged the old parameters, so its passport no longer holds.
    fn restart_edge_record(&mut self, idx: usize, key: &str, now: i64) {
        let old = std::mem::replace(&mut self.strategies[idx].ledger.edge, risk::EdgeRecord::fresh(now));
        let (sid, name) = (self.strategies[idx].id.clone(), self.strategies[idx].name.clone());
        self.sizing_noted.remove(&sid);
        // Dragging a slider through ten values would otherwise say this ten
        // times; an empty record has nothing to report.
        if old.trades() > 0 {
            let (mode, est) = risk::edge_sizing(&old);
            let won = est.map_or(0.0, |k| k.win_rate * 100.0);
            let was = match mode {
                risk::SizingMode::NoEdge => " It was sized to zero for no measured edge; the new parameters trade again on \
                                             signal strength.",
                risk::SizingMode::Measured => " It was sized on that record; the new parameters go back to signal strength.",
                risk::SizingMode::Confidence => "",
            };
            self.log(
                JournalKind::Risk,
                format!(
                    "{name}: parameter {key} changed, so its edge record ({} trades, {won:.0}% won) no longer describes \
                     it and starts again.{was} Sized on its own record again after {} new closed trades",
                    old.trades(),
                    risk::MIN_EDGE_TRADES
                ),
                Some(sid.clone()),
                None,
            );
        }
        if self.strategies[idx].state == StrategyState::Live && !self.passport_for(&self.strategies[idx]).live_ready {
            self.strategies[idx].state = StrategyState::Paper;
            self.log(
                JournalKind::Risk,
                format!("{name} back to PAPER: its parameters changed since its checks. Run them again to go live"),
                Some(sid),
                None,
            );
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
    /// Signed notional per open position (short is negative), for the
    /// correlation-adjusted exposure.
    fn exposure_book(&self) -> Vec<(String, f64)> {
        self.positions.iter().map(|(id, p)| (id.clone(), p.qty * self.price_of(id))).collect()
    }
    /// Peak-to-now equity drawdown in %, against the same peak the breaker
    /// in `tick` uses.
    fn drawdown_pct(&self) -> f64 {
        if self.peak_equity <= 0.0 {
            return 0.0;
        }
        ((self.peak_equity - self.equity()) / self.peak_equity * 100.0).max(0.0)
    }
    /// Annual volatility per market, measured from real candles. Markets
    /// without them are left out, and the risk layer assumes
    /// [`risk::unknown_annual_vol`] for them.
    fn annual_vols<'a>(&self, ids: impl Iterator<Item = &'a str>) -> HashMap<String, f64> {
        ids.filter(|id| self.bar_backed.contains(*id))
            .filter_map(|id| {
                let always_open = self.markets.iter().find(|m| m.id == id).map_or(true, |m| m.kind != MarketKind::Equity);
                let vol = risk::annual_vol(self.ohlc.get(id)?, always_open)?;
                Some((id.to_string(), vol))
            })
            .collect()
    }
    /// Price history for correlations: candles for bar-backed markets (aligned
    /// on bar times), closes for the rest. See [`risk::PriceSeries`].
    fn prices(&self) -> risk::PriceSeries<'_> {
        risk::PriceSeries::new(&self.history, &self.ohlc)
    }
    /// One standard deviation of the open book's annual P&L.
    fn book_vol(&self) -> f64 {
        let book = self.exposure_book();
        let vols = self.annual_vols(book.iter().map(|(id, _)| id.as_str()));
        risk::portfolio_vol(&book, &vols, &self.prices())
    }
    /// The risk manager's live numbers for the Risk page.
    fn risk_status(&self) -> risk::RiskStatus {
        let equity = self.equity();
        let book = self.exposure_book();
        let prices = self.prices();
        let corr = risk::correlated_exposure(&book, &prices);
        let vols = self.annual_vols(book.iter().map(|(id, _)| id.as_str()));
        let pvol = risk::portfolio_vol(&book, &vols, &prices);
        let drawdown_pct = self.drawdown_pct();
        risk::RiskStatus {
            unaligned_pairs: risk::unaligned_pairs(&book, &prices),
            vol_spike_since: self.vol_spike.above_since,
            last_vol_trim: self.vol_spike.last_trim,
            portfolio_vol: pvol,
            portfolio_vol_pct: if equity > 0.0 { pvol / equity * 100.0 } else { 0.0 },
            vol_assumed: book.iter().filter(|(id, _)| !vols.contains_key(id)).map(|(id, _)| id.clone()).collect(),
            drawdown_pct,
            derisk_factor: risk::derisk_factor(drawdown_pct, self.limits.max_drawdown_pct),
            correlated_exposure: corr,
            correlated_exposure_pct: if equity > 0.0 { corr / equity * 100.0 } else { 0.0 },
            sizing: self
                .strategies
                .iter()
                .filter(|s| s.id != "manual")
                .map(|s| risk::StrategySizing::of(&s.id, &s.ledger.edge))
                .collect(),
        }
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
        let book = self.exposure_book();
        let vols = self.annual_vols(book.iter().map(|(id, _)| id.as_str()).chain(std::iter::once(market_id)));
        let weighted = risk::vol_weighted(&book, &vols);
        let prices = self.prices();
        let corr = risk::correlation_loading(&book, market_id, &prices);
        let vol = risk::correlation_loading(&weighted, market_id, &prices);
        risk::RiskContext {
            corr_exposure: risk::correlated_exposure(&book, &prices),
            corr_loading: corr.measured,
            corr_unmeasured: corr.unmeasured,
            vol_exposure: risk::correlated_exposure(&weighted, &prices),
            vol_loading: vol.measured,
            vol_unmeasured: vol.unmeasured,
            market_vol: vols.get(market_id).copied().unwrap_or_else(risk::unknown_annual_vol),
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
                            demo: p.demo,
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
            lab_done: self.lab_done.clone(),
            forecast_cfg: Some(self.forecast_cfg.clone()),
            exec_policy: self.exec_policy.clone(),
            research: self.research.clone(),
            ref_prices: self.ref_prices.clone(),
            seq: self.seq,
            peak_equity: self.peak_equity,
            day: self.day,
            prices: self
                .markets
                .iter()
                .filter(|m| self.real_ids.contains(&m.id))
                .map(|m| (m.id.clone(), (m.price, m.updated_at)))
                .collect(),
            inflight: self.inflight.iter().map(|(id, f)| (id.clone(), f.clone())).collect(),
            autopilots: self.autopilots.clone(),
        }
    }

    /// Live orders from before a restart. An order the venue acknowledged is
    /// followed again: back in flight, its market blocked for new orders, and
    /// the daemon's next poll (`live_polls`) reads its status and books
    /// whatever filled meanwhile, cancelling it first if it is past the
    /// timeout. One without a broker id never got an answer, so its fate is
    /// unknown here; its row is closed as rejected with the client id to look
    /// for at the venue, and reconciliation corrects any position it opened.
    /// A "Pending" row with no saved state at all (a save from before in-flight
    /// orders were kept) is closed the same way rather than left pending forever.
    fn restore_inflight(&mut self, saved: Vec<(String, InFlight)>) {
        let mut followed = 0usize;
        for (order_id, f) in saved {
            if f.broker_id.is_some() {
                self.in_flight_markets.insert(f.market_id.clone());
                self.inflight.insert(order_id, f);
                followed += 1;
                continue;
            }
            let at = if f.client_order_id.is_empty() { String::new() } else { format!(" (client id {})", f.client_order_id) };
            let reason = format!(
                "status unknown: Pythia restarted before {:?} acknowledged it{at}. Check the venue; \
                 reconciliation corrects the position if it filled",
                f.venue
            );
            if let Some(ord) = self.orders.iter_mut().find(|o| o.id == order_id) {
                ord.status = OrderStatus::Rejected;
                ord.reject_reason = Some(reason.clone());
            }
            self.log(
                JournalKind::Risk,
                format!("LIVE order {} {:?} {}: {reason}", order_id, f.side, f.symbol),
                Some(f.strategy_id),
                Some(f.market_id),
            );
        }
        let orphans: Vec<String> = self
            .orders
            .iter()
            .filter(|o| o.status == OrderStatus::Pending && !self.inflight.contains_key(&o.id))
            .map(|o| o.id.clone())
            .collect();
        for id in &orphans {
            if let Some(ord) = self.orders.iter_mut().find(|o| &o.id == id) {
                ord.status = OrderStatus::Rejected;
                ord.reject_reason = Some(
                    "status unknown: saved as pending without its venue state. Check the venue; \
                     reconciliation corrects the position if it filled"
                        .into(),
                );
            }
        }
        if !orphans.is_empty() {
            self.log(
                JournalKind::Risk,
                format!("{} pending order(s) from an older save could not be followed and were closed", orphans.len()),
                None,
                None,
            );
        }
        if followed > 0 {
            self.log(
                JournalKind::System,
                format!("Following {followed} live order(s) from before the restart until the venue reports them done"),
                None,
                None,
            );
        }
    }

    pub fn apply_persisted(&mut self, p: Persisted) {
        // Ids continue after the highest one restored. Saves from before the
        // counter was kept still carry their ids in the orders and journal.
        let suffix = |id: &str| id.rsplit('_').next().and_then(|n| n.parse::<u64>().ok());
        let highest = p.orders.iter().map(|o| &o.id).chain(p.journal.iter().map(|j| &j.id)).filter_map(|id| suffix(id)).max();
        self.seq = self.seq.max(p.seq).max(highest.unwrap_or(0));
        self.cash = p.cash;
        self.realized_pnl = p.realized_pnl;
        self.day_start_equity = p.day_start_equity;
        // A save from before these were kept: the day's start is the best peak
        // known, and the first tick moves it up if equity is higher.
        self.peak_equity = if p.peak_equity > 0.0 { p.peak_equity } else { p.day_start_equity };
        if p.day > 0 {
            // A save from an earlier day gets its daily reset on the first tick.
            self.day = p.day;
        }
        for (id, (price, at)) in &p.prices {
            if let Some(m) = self.markets.iter_mut().find(|m| &m.id == id).filter(|_| price.is_finite() && *price > 0.0) {
                m.price = *price;
                // The saved time, not now: the risk check's staleness limit
                // keeps entries off until the feed has confirmed the price.
                m.updated_at = *at;
            }
        }
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
                        demo: pp.demo,
                    },
                )
            })
            .collect();
        if !p.strategies.is_empty() {
            self.strategies = p.strategies;
        }
        // A save from before the forward-test clock existed starts it now:
        // there is no record of how long it ran before, and guessing would be
        // crediting time that was never observed.
        let now = self.now();
        for s in self.strategies.iter_mut() {
            if s.state != StrategyState::Paused && s.ledger.paper_since.is_none() {
                s.ledger.paper_since = Some(now);
            }
            s.ledger.pnl = s.ledger.breakdown(s.pnl);
        }
        self.orders = p.orders;
        self.journal = p.journal;
        self.restore_inflight(p.inflight);
        self.limits = p.limits;
        self.real_ids = p.real_ids.into_iter().collect();
        let resolved = p.forecast_store.resolved_count();
        self.forecast_store = p.forecast_store;
        self.lab_done = p.lab_done;
        // A restored ledger has a resolution counter of its own; force a refit
        // rather than trusting a version number from a different process.
        self.scored_version = None;
        self.rescore_if_needed();
        if let Some(cfg) = p.forecast_cfg {
            self.forecast_cfg = cfg;
        }
        self.exec_policy = p.exec_policy;
        self.research = p.research;
        self.ref_prices = p.ref_prices;
        self.log(JournalKind::System, "Restored saved state from disk".into(), None, None);
        self.rebuild_edge_records();
        // A strategy saved as Live keeps that switch only if its passport still
        // allows it. Saves from before the gates existed, or a strategy whose
        // parameters changed since its checks, go back to paper and say why.
        let demote: Vec<(String, String)> = self
            .strategies
            .iter()
            .filter(|s| s.state == StrategyState::Live)
            .filter_map(|s| {
                let pp = self.passport_for(s);
                (!pp.live_ready).then(|| (s.id.clone(), pp.blocked_reason.unwrap_or_default()))
            })
            .collect();
        for (id, why) in demote {
            if let Some(s) = self.strategies.iter_mut().find(|s| s.id == id) {
                s.state = StrategyState::Paper;
            }
            self.log(JournalKind::Risk, format!("{id} restored as PAPER, not live. {why}"), Some(id.clone()), None);
        }
        self.autopilots = p.autopilots;
        self.autopilots_after_restore();
        if resolved > 0 {
            self.log(
                JournalKind::System,
                format!("Forecast track record restored — {resolved} scored prediction(s)"),
                None,
                None,
            );
        }
    }

    /// Give a strategy restored with an empty edge record the closed trades
    /// the saved orders still show (see `risk::replay_closed_trades`). A save
    /// from before the record existed would otherwise size a strategy with a
    /// long history on signal strength for another 30 trades. Only trades
    /// closed since the record last started over count, so this never undoes
    /// a reset by a parameter change. A strategy with nothing to rebuild from
    /// is left empty.
    fn rebuild_edge_records(&mut self) {
        let empty: Vec<usize> =
            (0..self.strategies.len()).filter(|&i| self.strategies[i].ledger.edge.trades() == 0).collect();
        if empty.is_empty() {
            return;
        }
        let fills: Vec<risk::PastFill> = self
            .orders
            .iter()
            .rev() // newest first on the book, oldest first for the replay
            .filter(|o| o.status != OrderStatus::Rejected && o.filled_qty > 0.0)
            .filter_map(|o| {
                let price = o.avg_fill_price?;
                let symbol = self
                    .markets
                    .iter()
                    .find(|m| m.id == o.market_id)
                    .map(|m| m.symbol.clone())
                    .unwrap_or_else(|| o.market_id.split(':').nth(1).unwrap_or(&o.market_id).to_string());
                let model = costs::model_for(CostVenue::for_venue(o.venue, Some(self.crypto_venue)), &symbol);
                Some(risk::PastFill {
                    ts: o.ts,
                    market_id: o.market_id.clone(),
                    strategy_id: o.strategy_id.clone(),
                    signed_qty: if o.side == Side::Buy { o.filled_qty } else { -o.filled_qty },
                    price,
                    fee_rate: model.taker_bps / 10_000.0,
                })
            })
            .collect();
        let held: HashMap<String, f64> = self.positions.iter().map(|(id, p)| (id.clone(), p.qty)).collect();
        let trades = risk::replay_closed_trades(&fills, &held);
        for idx in empty {
            let s = &mut self.strategies[idx];
            // Strictly after: a trade stamped in the same millisecond as the
            // reset may have closed before it, and leaving one out is the
            // cheaper mistake.
            let since = s.ledger.edge.since.unwrap_or(i64::MIN);
            let mine: Vec<f64> =
                trades.iter().filter(|t| t.strategy_id == s.id && t.ts > since).map(|t| t.net_return).collect();
            if mine.is_empty() {
                continue;
            }
            mine.iter().for_each(|r| s.ledger.edge.record(*r));
            let (sid, name, n) = (s.id.clone(), s.name.clone(), mine.len());
            self.log(
                JournalKind::Risk,
                format!(
                    "{name}: edge record rebuilt from {n} closed trade(s) in the saved order history (fees estimated at \
                     the venue's taker rate)"
                ),
                Some(sid),
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
                    demo: p.demo,
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
            history_ts: self
                .ohlc
                .iter()
                .filter(|(id, _)| self.history.contains_key(*id))
                .map(|(id, bars)| (id.clone(), bars.iter().skip(bars.len().saturating_sub(60)).map(|b| b.ts).collect()))
                .collect(),
            live: self.live_status(),
            bar_backed: self.bar_backed.iter().cloned().collect(),
            ai_views: self.ai.values().cloned().collect(),
            ai_policy: self.ai_policy.clone(),
            ai_spend: self.ai_spend.clone(),
            forecasts: self.forecasts.clone(),
            // Only scored sources are worth showing; an all-zero row for
            // something that has never resolved is noise.
            tracks: self.track_cache.iter().filter(|t| t.score.n > 0).cloned().collect(),
            coherence: self.coherence.clone(),
            forecast_stats: ForecastStats {
                recorded: self.forecast_store.len(),
                resolved: self.forecast_store.resolved_count(),
                pending: self.forecast_store.pending_count(),
                // Counted off the cached scoreboard rather than re-scoring the
                // ledger — `state()` runs on every tick.
                trusted_sources: self.track_cache.iter().filter(|t| t.trust > 0.0).count(),
            },
            execution: self.exec_policy.report(),
            adaptive_execution: self.exec_policy.enabled,
            slippage: self.exec_policy.slippage_report(),
            crypto_cost_venue: self.crypto_venue,
            passports: self.strategies.iter().filter(|s| s.id != "manual").map(|s| self.passport_for(s)).collect(),
            risk: self.risk_status(),
            data_health: Some(self.data_health()),
            autopilots: self.autopilot_statuses(),
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
            realised_slippage_bps: None,
            modelled_slippage_bps: None,
            route: FillRoute::Paper,
            cost_source: None,
            drift_bps: None,
            book_exhausted: false,
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

/// Market class for the calibration hierarchy. Deliberately coarse: these are
/// the three groups where a forecaster's competence genuinely differs, and
/// splitting further would starve every bucket of evidence.
fn market_category(kind: MarketKind) -> &'static str {
    match kind {
        MarketKind::Prediction => "prediction",
        MarketKind::Crypto => "crypto",
        MarketKind::Equity => "equity",
    }
}

/// Apply a signed fill to a position. Returns `(new_qty, new_avg_price,
/// realised_pnl)`.
///
/// Whether a fill adds or reduces is decided by the fill's own sign against
/// the position's, not by the sign of the result. The earlier test compared
/// `pos.qty.signum()` with `new_qty.signum()`, and since `0.0_f64.signum()` is
/// `1.0` a long closed to exactly zero looked like an add, booked no realised
/// P&L, and never counted as a trade. A partial reduction looked like an add
/// too, and dragged the average price toward the exit price.
pub fn apply_fill(qty: f64, avg: f64, signed: f64, fill: f64) -> (f64, f64, f64) {
    let new_qty = qty + signed;
    if qty == 0.0 || qty.signum() == signed.signum() {
        let total = avg * qty.abs() + fill * signed.abs();
        let new_avg = if new_qty.abs() > 0.0 { total / new_qty.abs() } else { fill };
        return (new_qty, new_avg, 0.0);
    }
    let closed = signed.abs().min(qty.abs());
    let dir = qty.signum();
    let realised = (fill - avg) * closed * dir;
    // A reduction keeps the entry price of what is left; a flip starts the
    // remainder fresh at this fill.
    let flipped = new_qty.abs() > 1e-12 && new_qty.signum() != qty.signum();
    (new_qty, if flipped { fill } else { avg }, realised)
}

/// A simulated fill: the price after crossing the half-spread and paying
/// impact, and the taker fee in quote currency. Both come from the cost model,
/// so a paper fill on Kraken pays Kraken's costs and one on Binance pays
/// Binance's. `cost` carries a live book's spread and depth when the engine
/// has a fresh one. Prediction-market prices are probabilities and stay inside
/// (0, 1).
pub fn paper_fill(cost: &ExecCost, kind: MarketKind, side: Side, qty: f64, price: f64) -> (f64, f64) {
    let f = paper_fill_detail(cost, kind, side, qty, price);
    (f.price, f.fee)
}

/// A simulated fill and how it was priced.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct PaperFill {
    /// Average fill price.
    pub price: f64,
    /// Taker fee, quote currency.
    pub fee: f64,
    /// What the cost model expected the price slippage to be, in bps
    /// (half-spread plus impact), on the same book the fill used.
    pub modelled_bps: f64,
    /// Whether spread and depth came from a fresh live book.
    pub source: CostSource,
    /// The book's mid against the signal price, signed so positive costs us.
    /// `None` without a live book.
    pub drift_bps: Option<f64>,
    /// The fill walked the live book level by level (otherwise: priced by
    /// the model around the signal price).
    pub walked: bool,
    /// Levels the walk touched.
    pub levels_used: usize,
    /// The order was bigger than the 20 levels; the rest was priced with the
    /// impact model.
    pub exhausted: bool,
}

/// [`paper_fill`] with its working shown.
///
/// With a fresh top-20 book from the executing venue (`cost.book`), a crypto
/// market order is filled the way the venue's matching engine would fill it:
/// level by level from the best price, at the volume-weighted average of what
/// it consumed. That price is in the book's own frame, so it also carries any
/// drift between the signal price and the book (recorded in `drift_bps`). If
/// the order outgrows the 20 levels, the remainder is priced at the book's mid
/// plus the modelled half-spread and impact for the whole order, never better
/// than the last level, and the fill says so (`exhausted`).
///
/// Without a usable book it is the cost model around the signal price, as
/// before: half-spread plus square-root impact against the calibrated depth.
/// Either way the taker fee is charged on the fill's notional.
pub fn paper_fill_detail(cost: &ExecCost, kind: MarketKind, side: Side, qty: f64, price: f64) -> PaperFill {
    let qty = qty.abs();
    let model = &cost.model;
    let modelled_bps = cost.slippage_bps(qty * price);
    let slip = modelled_bps / 10_000.0;
    let shift = |p: f64| match side {
        Side::Buy => p * (1.0 + slip),
        Side::Sell => p * (1.0 - slip),
    };
    let walked = if kind == MarketKind::Crypto {
        cost.book.and_then(|b| b.walk(side, qty).map(|w| (b, w)))
    } else {
        None
    };
    let (px, drift_bps, levels_used, exhausted) = match walked {
        Some((b, w)) => (w.average_price(qty, side, shift(b.mid)), b.drift_bps(side, price), w.levels_used, w.exhausted),
        None => {
            let mut px = shift(price);
            if kind == MarketKind::Prediction {
                px = px.clamp(0.001, 0.999);
            }
            (px, None, 0, false)
        }
    };
    PaperFill {
        price: px,
        fee: px * qty * model.taker_bps / 10_000.0,
        modelled_bps,
        source: cost.source,
        drift_bps,
        walked: walked.is_some(),
        levels_used,
        exhausted,
    }
}

/// Regime filter: mean-reversion strategies are blocked in trending markets,
/// trend strategies are blocked in ranging (choppy) markets.
pub(crate) fn strategy_regime_ok(kind: StrategyKind, regime: Option<Regime>) -> bool {
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
        // The rest of the research lab's 20-coin universe, so lab strategies can
        // run the portfolio they were tested on. Seed prices from Kraken, Oct 2026.
        mk("crypto:DOGE/USD", Venue::Crypto, "DOGE/USD", MarketKind::Crypto, 0.0934, 0.0, None, 300_000.0),
        mk("crypto:BCH/USD", Venue::Crypto, "BCH/USD", MarketKind::Crypto, 310.4, 0.0, None, 150_000.0),
        mk("crypto:TRX/USD", Venue::Crypto, "TRX/USD", MarketKind::Crypto, 0.3357, 0.0, None, 100_000.0),
        mk("crypto:SUI/USD", Venue::Crypto, "SUI/USD", MarketKind::Crypto, 1.18, 0.0, None, 150_000.0),
        mk("crypto:NEAR/USD", Venue::Crypto, "NEAR/USD", MarketKind::Crypto, 5.11, 0.0, None, 100_000.0),
        mk("crypto:ATOM/USD", Venue::Crypto, "ATOM/USD", MarketKind::Crypto, 1.79, 0.0, None, 100_000.0),
        mk("crypto:UNI/USD", Venue::Crypto, "UNI/USD", MarketKind::Crypto, 8.55, 0.0, None, 100_000.0),
        mk("crypto:AAVE/USD", Venue::Crypto, "AAVE/USD", MarketKind::Crypto, 180.0, 0.0, None, 100_000.0),
        mk("crypto:XLM/USD", Venue::Crypto, "XLM/USD", MarketKind::Crypto, 0.2126, 0.0, None, 100_000.0),
        mk("crypto:PEPE/USD", Venue::Crypto, "PEPE/USD", MarketKind::Crypto, 0.000004266, 0.0, None, 100_000.0),
        mk("crypto:FIL/USD", Venue::Crypto, "FIL/USD", MarketKind::Crypto, 1.159, 0.0, None, 100_000.0),
        mk("alpaca:AAPL", Venue::Alpaca, "AAPL", MarketKind::Equity, 227.1, 0.006, None, 1_500_000.0),
        mk("alpaca:NVDA", Venue::Alpaca, "NVDA", MarketKind::Equity, 138.9, 0.021, None, 3_300_000.0),
        mk("alpaca:MSFT", Venue::Alpaca, "MSFT", MarketKind::Equity, 428.0, 0.004, None, 1_200_000.0),
        mk("alpaca:AMZN", Venue::Alpaca, "AMZN", MarketKind::Equity, 186.4, 0.009, None, 1_800_000.0),
        mk("alpaca:TSLA", Venue::Alpaca, "TSLA", MarketKind::Equity, 248.5, -0.012, None, 2_600_000.0),
        // Alpaca's own crypto book: the same keys as the equities, open on a
        // weekend, so the connection test can prove the broker any day. No
        // strategy trades these by default. Seed prices from Alpaca, Oct 2026.
        mk("alpaca:BTC/USD", Venue::Alpaca, "BTC/USD", MarketKind::Crypto, 83_150.0, 0.0, None, 1_000_000.0),
        mk("alpaca:ETH/USD", Venue::Alpaca, "ETH/USD", MarketKind::Crypto, 2_566.0, 0.0, None, 1_000_000.0),
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
    for (id, base) in [
        ("crypto:DOGE/USD", 0.0934),
        ("crypto:BCH/USD", 310.4),
        ("crypto:TRX/USD", 0.3357),
        ("crypto:SUI/USD", 1.18),
        ("crypto:NEAR/USD", 5.11),
        ("crypto:ATOM/USD", 1.79),
        ("crypto:UNI/USD", 8.55),
        ("crypto:AAVE/USD", 180.0),
        ("crypto:XLM/USD", 0.2126),
        ("crypto:PEPE/USD", 0.000004266),
        ("crypto:FIL/USD", 1.159),
    ] {
        sim.insert(id.into(), SimParam { drift: 0.00030, vol: 0.0032, base });
    }
    sim.insert("alpaca:AAPL".into(), SimParam { drift: 0.000005, vol: 0.0009, base: 225.7 });
    sim.insert("alpaca:NVDA".into(), SimParam { drift: 0.00003, vol: 0.0016, base: 136.0 });
    sim.insert("alpaca:MSFT".into(), SimParam { drift: 0.000006, vol: 0.0008, base: 426.0 });
    sim.insert("alpaca:AMZN".into(), SimParam { drift: 0.00001, vol: 0.0011, base: 185.0 });
    sim.insert("alpaca:TSLA".into(), SimParam { drift: 0.000004, vol: 0.0022, base: 250.0 });
    sim.insert("alpaca:BTC/USD".into(), SimParam { drift: 0.00030, vol: 0.0022, base: 83_150.0 });
    sim.insert("alpaca:ETH/USD".into(), SimParam { drift: 0.00030, vol: 0.0024, base: 2_566.0 });
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
                demo: false,
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

    fn restored(e: &Engine) -> Engine {
        let json = serde_json::to_string(&e.to_persisted()).unwrap();
        let mut back = Engine::new();
        back.apply_persisted(serde_json::from_str(&json).unwrap());
        back
    }

    #[test]
    fn ids_are_not_handed_out_twice_across_a_restart() {
        let num = |id: &str| id.rsplit('_').next().unwrap().parse::<u64>().unwrap();
        let mut e = Engine::new();
        for _ in 0..5 {
            e.manual_order("crypto:BTC/USD", Side::Buy, 100.0);
        }
        let saved_max = e.orders.iter().map(|o| num(&o.id)).chain(e.journal.iter().map(|j| num(&j.id))).max().unwrap();
        assert!(saved_max >= 10);

        let mut back = restored(&e);
        back.manual_order("crypto:ETH/USD", Side::Buy, 100.0);
        assert!(num(&back.orders[0].id) > saved_max, "{} was handed out before the restart", back.orders[0].id);
        assert!(num(&back.journal[0].id) > saved_max, "{} was handed out before the restart", back.journal[0].id);

        // A save without the counter (older format) still continues after its ids.
        let mut old = e.to_persisted();
        old.seq = 0;
        let mut back = Engine::new();
        back.apply_persisted(old);
        back.manual_order("crypto:ETH/USD", Side::Buy, 100.0);
        assert!(num(&back.orders[0].id) > saved_max, "{}", back.orders[0].id);
    }

    #[test]
    fn a_client_order_id_is_never_reused_by_the_next_process() {
        // The same engine order id in two processes (a crash that lost the last
        // save) must not reach the venue as the same client id: Alpaca answers a
        // known one with the old order, which would then be booked as this one.
        let send = || {
            let mut e = engine_with_open_market();
            e.set_live(armed_alpaca());
            e.live_order_for_test("alpaca:AAPL", Side::Buy, 1_000.0);
            e.drain_live_orders().remove(0)
        };
        let (a, b) = (send(), send());
        assert_ne!(a.client_order_id, "", "kept for the restart path too");
        assert_eq!(a.order_id, b.order_id, "same counter in both runs");
        assert_ne!(a.client_order_id, b.client_order_id);
        assert!(a.client_order_id.len() <= 32, "fits every venue's limit: {}", a.client_order_id);
    }

    /// An armed engine with one Alpaca buy out at the venue, acknowledged as `broker_id`.
    fn with_live_order(broker_id: Option<&str>) -> (Engine, LiveOrderOut) {
        let mut e = engine_with_open_market();
        e.set_live(armed_alpaca());
        e.live_order_for_test("alpaca:AAPL", Side::Buy, 1_000.0);
        let o = e.drain_live_orders().remove(0);
        if let Some(b) = broker_id {
            e.apply_live_ack(&o.order_id, b);
        }
        (e, o)
    }

    fn row<'a>(e: &'a Engine, id: &str) -> &'a Order {
        e.orders.iter().find(|x| x.id == id).expect("the order row")
    }

    #[test]
    fn an_acknowledged_live_order_is_polled_again_after_a_restart_and_its_fill_booked() {
        let (e, o) = with_live_order(Some("broker-7"));
        let mut back = restored(&e);
        assert_eq!(row(&back, &o.order_id).status, OrderStatus::Pending);
        let polls = back.live_polls();
        assert_eq!(polls.len(), 1);
        assert_eq!((polls[0].order_id.as_str(), polls[0].broker_id.as_str()), (o.order_id.as_str(), "broker-7"));
        assert_eq!((polls[0].venue, polls[0].symbol.as_str(), polls[0].paper, polls[0].cancel), (Venue::Alpaca, "AAPL", true, false));
        assert!(back.in_flight_markets.contains("alpaca:AAPL"), "no second order into that market meanwhile");
        assert!(back.journal.iter().any(|j| j.message.contains("Following 1 live order")));

        // It filled while Pythia was down: the first poll books it, once.
        back.apply_live_update(&o.order_id, update(BrokerOrderStatus::Filled, o.qty, 228.0));
        let r = row(&back, &o.order_id);
        assert_eq!((r.status, r.filled_qty, r.avg_fill_price), (OrderStatus::Filled, o.qty, Some(228.0)));
        let p = back.positions.get("alpaca:AAPL").expect("the fill opened the position");
        assert!(p.live && (p.qty - o.qty).abs() < 1e-9);
        // Armed against Alpaca's PAPER endpoint: virtual money, so the fill is
        // labelled demo and stays out of the tax record.
        assert_eq!(r.route, FillRoute::Demo);
        assert!(back.drain_fill_records().is_empty(), "a paper-endpoint fill is never taxed");
        assert!(back.live_polls().is_empty());
        assert!(!back.in_flight_markets.contains("alpaca:AAPL"));
        // A second restart has nothing left to follow.
        assert!(restored(&back).live_polls().is_empty());
    }

    #[test]
    fn a_restored_order_ends_cancelled_or_rejected_when_the_venue_says_so() {
        // Past its timeout across the restart: the poll cancels first, then reads.
        let (mut e, o) = with_live_order(Some("broker-8"));
        e.inflight.get_mut(&o.order_id).unwrap().submitted_at -= 10 * 60_000;
        let mut back = restored(&e);
        let polls = back.live_polls();
        assert!(polls[0].cancel, "120 s timeout, ten minutes old");
        back.mark_cancel_sent(&o.order_id);
        assert!(!back.live_polls()[0].cancel, "the cancel is sent once");
        back.apply_live_update(&o.order_id, update(BrokerOrderStatus::Canceled, 0.0, 0.0));
        assert_eq!(row(&back, &o.order_id).status, OrderStatus::Cancelled);
        assert!(back.live_polls().is_empty() && back.positions.is_empty());

        let (e, o) = with_live_order(Some("broker-9"));
        let mut back = restored(&e);
        back.apply_live_update(&o.order_id, update(BrokerOrderStatus::Rejected, 0.0, 0.0));
        assert_eq!(row(&back, &o.order_id).status, OrderStatus::Rejected);
        assert!(back.live_polls().is_empty() && !back.in_flight_markets.contains("alpaca:AAPL"));
    }

    #[test]
    fn an_order_the_venue_never_acknowledged_is_closed_at_the_restart_not_left_pending() {
        let (e, o) = with_live_order(None);
        let back = restored(&e);
        let r = row(&back, &o.order_id);
        assert_eq!(r.status, OrderStatus::Rejected);
        let why = r.reject_reason.clone().unwrap();
        assert!(why.contains("restarted before") && why.contains(&o.client_order_id), "{why}");
        assert!(back.live_polls().is_empty(), "nothing to ask the venue by");
        assert!(!back.in_flight_markets.contains("alpaca:AAPL"));
        assert!(back.journal.iter().any(|j| j.kind == JournalKind::Risk && j.message.contains(&o.order_id)));
    }

    #[test]
    fn a_pending_row_from_a_save_without_inflight_orders_is_closed() {
        let (e, o) = with_live_order(Some("broker-10"));
        let mut v = serde_json::to_value(e.to_persisted()).unwrap();
        v.as_object_mut().unwrap().remove("inflight");
        let mut back = Engine::new();
        back.apply_persisted(serde_json::from_value(v).unwrap());
        let r = row(&back, &o.order_id);
        assert_eq!(r.status, OrderStatus::Rejected);
        assert!(r.reject_reason.as_deref().unwrap().contains("status unknown"));
        assert!(back.orders.iter().all(|x| x.status != OrderStatus::Pending));
    }

    #[test]
    fn reconciliation_waits_for_an_order_in_flight_instead_of_counting_its_fill_twice() {
        // 1 share held, a buy out for more; it filled at the venue while Pythia was down.
        let (mut e, first) = with_live_order(Some("b-1"));
        e.apply_live_update(&first.order_id, update(BrokerOrderStatus::Filled, first.qty, 228.0));
        e.live_order_for_test("alpaca:AAPL", Side::Buy, 1_000.0);
        let second = e.drain_live_orders().remove(0);
        e.apply_live_ack(&second.order_id, "b-2");
        let mut back = restored(&e);
        let total = first.qty + second.qty;
        let venue = [BrokerPosition { symbol: "AAPL".into(), qty: total, avg_price: 228.0, market_value: total * 228.0 }];

        assert_eq!(back.reconcile_positions(Venue::Alpaca, &venue, false), 0, "left to the order's own report");
        assert!((back.positions["alpaca:AAPL"].qty - first.qty).abs() < 1e-9);
        // And not dropped either, while the order is out.
        assert_eq!(back.reconcile_positions(Venue::Alpaca, &[], false), 0);
        back.apply_live_update(&second.order_id, update(BrokerOrderStatus::Filled, second.qty, 228.0));
        assert!((back.positions["alpaca:AAPL"].qty - total).abs() < 1e-9);
        assert_eq!(back.reconcile_positions(Venue::Alpaca, &venue, false), 0, "book and venue agree");
    }

    #[test]
    fn a_restart_does_not_measure_the_drawdown_from_the_starting_balance() {
        // Down to 80 000 on earlier days, flat today: no drawdown today.
        let mut e = Engine::new();
        e.cash = 80_000.0;
        e.day_start_equity = 80_000.0;
        e.peak_equity = 80_000.0;
        let mut back = restored(&e);
        back.tick();
        assert!(!back.limits.kill_switch, "the breaker tripped on a loss from before today");
        assert!(back.drawdown_pct() < 1.0, "drawdown {}", back.drawdown_pct());
    }

    #[test]
    fn a_save_from_yesterday_gets_its_daily_reset_after_the_restart() {
        let mut e = Engine::new();
        e.day -= 1;
        e.day_start_equity = 120_000.0; // yesterday's start, nothing to do with today
        let mut back = restored(&e);
        back.tick();
        assert!((back.day_start_equity - back.equity()).abs() < 1e-6 * back.equity().max(1.0));
        assert!(back.journal.iter().any(|j| j.message.starts_with("New UTC day")));
    }

    #[test]
    fn a_restored_position_keeps_its_last_real_price_until_the_feed_answers() {
        let mut e = Engine::new();
        e.apply_kraken(&[RealCrypto { id: "crypto:BTC/USD".into(), symbol: "BTC/USD".into(), price: 120_000.0, change24h: 0.0 }]);
        e.positions.insert(
            "crypto:BTC/USD".into(),
            PositionInternal {
                venue: Venue::Crypto,
                symbol: "BTC/USD".into(),
                qty: 0.1,
                avg_price: 118_000.0,
                strategy_id: "ema-cross-1".into(),
                stop: 110_000.0,
                target: 0.0,
                trail_ref: 118_000.0,
                live: false,
                demo: false,
            },
        );
        let mut back = restored(&e);
        // The first feed refresh failed: the seed price (67 250) is under the stop.
        back.tick();
        assert!(back.positions.contains_key("crypto:BTC/USD"), "stopped out at the seed price");
        assert_eq!(back.price_of("crypto:BTC/USD"), 120_000.0);
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
                demo: false,
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
            ledger: StrategyLedger::default(),
        });
        assert_eq!(e.strategies.len(), n0 + 1);
    }

    #[test]
    fn closing_a_long_to_exactly_zero_books_the_trade() {
        // 0.0_f64.signum() is 1.0, so the old add/reduce test treated a full
        // close of a long as an add: no realised P&L, no trade counted.
        let (q, _, r) = apply_fill(2.0, 100.0, -2.0, 110.0);
        assert_eq!(q, 0.0);
        assert!((r - 20.0).abs() < 1e-12);
        // Short side, for symmetry.
        let (q, _, r) = apply_fill(-2.0, 100.0, 2.0, 90.0);
        assert_eq!(q, 0.0);
        assert!((r - 20.0).abs() < 1e-12);
    }

    #[test]
    fn a_partial_reduction_realises_and_keeps_the_entry_price() {
        let (q, avg, r) = apply_fill(4.0, 100.0, -1.0, 120.0);
        assert_eq!(q, 3.0);
        assert_eq!(avg, 100.0, "what is left was still bought at 100");
        assert!((r - 20.0).abs() < 1e-12);
        // Adding averages in.
        let (q, avg, r) = apply_fill(1.0, 100.0, 1.0, 110.0);
        assert_eq!((q, r), (2.0, 0.0));
        assert!((avg - 105.0).abs() < 1e-12);
        // A flip realises the closed part and restarts at the fill.
        let (q, avg, r) = apply_fill(1.0, 100.0, -3.0, 90.0);
        assert_eq!(q, -2.0);
        assert_eq!(avg, 90.0);
        assert!((r + 10.0).abs() < 1e-12);
    }

    #[test]
    fn a_closed_long_shows_up_in_the_strategy_stats() {
        let mut e = Engine::new();
        e.live_order_for_test("alpaca:MSFT", Side::Buy, 2_000.0);
        e.flatten("alpaca:MSFT");
        let s = e.strategies.iter().find(|s| s.id == "manual").unwrap();
        assert_eq!(s.trades, 1, "a round trip is a trade");
        assert!(s.pnl < 0.0, "in and out at the same price loses the spread");
    }

    #[test]
    fn a_paper_fill_pays_the_cost_model_not_a_flat_guess() {
        let mut e = Engine::new();
        let px = e.price_of("crypto:BTC/USD");
        e.live_order_for_test("crypto:BTC/USD", Side::Buy, 1_000.0);
        let (qty, avg) = {
            let pos = e.positions.get("crypto:BTC/USD").expect("a paper buy fills");
            (pos.qty, pos.avg_price)
        };
        let m = e.markets.iter().find(|m| m.id == "crypto:BTC/USD").cloned().unwrap();
        let model = e.cost_model(&m);
        assert_eq!(model.taker_bps, 40.0, "crypto defaults to Kraken's costs");
        let expected = px * (1.0 + model.slippage_bps(qty * px, None) / 10_000.0);
        assert!((avg - expected).abs() < 1e-9 * px, "fill {avg} vs modelled {expected}");

        let l = e.strategies.iter().find(|s| s.id == "manual").unwrap().ledger.clone();
        assert!((l.fees - avg * qty * 0.004).abs() < 1e-6, "40 bps taker fee, got {}", l.fees);
        assert!(l.slippage > 0.0);
        // Nothing has closed yet: no gross, and the only cost so far is the fee.
        assert_eq!(l.pnl.gross, 0.0);
        assert!((l.pnl.net + l.fees).abs() < 1e-9);
        assert!((l.pnl.costs - l.fees).abs() < 1e-9);
    }

    #[test]
    fn gross_is_the_same_trades_at_the_quoted_price() {
        let mut e = Engine::new();
        e.live_order_for_test("crypto:BTC/USD", Side::Buy, 2_000.0);
        // The market moves up 5 % before the exit.
        let px = e.price_of("crypto:BTC/USD");
        if let Some(m) = e.markets.iter_mut().find(|m| m.id == "crypto:BTC/USD") {
            m.price = px * 1.05;
            m.updated_at = chrono::Utc::now().timestamp_millis();
        }
        e.flatten("crypto:BTC/USD");
        let s = e.strategy_config("manual").unwrap();
        let qty = 2_000.0 / px;
        let p = s.ledger.pnl;
        assert!((p.gross - qty * px * 0.05).abs() < 1e-6, "gross {} is the 5 % move at quoted prices", p.gross);
        assert!(p.net < p.gross, "costs are taken out");
        assert!((p.gross - p.costs - p.net).abs() < 1e-9);
        assert!((p.net - (s.pnl - s.ledger.fees)).abs() < 1e-9);
        assert!(!p.cost_heavy, "a 5 % winner on Kraken BTC is not eaten by costs");
    }

    #[test]
    fn the_configured_exchange_decides_what_crypto_costs() {
        let mut kraken = Engine::new();
        let mut binance = Engine::new();
        binance.set_crypto_cost_venue(Some(CostVenue::Binance));
        for e in [&mut kraken, &mut binance] {
            e.live_order_for_test("crypto:ETH/USD", Side::Buy, 2_000.0);
        }
        let fees = |e: &Engine| e.strategies.iter().find(|s| s.id == "manual").unwrap().ledger.fees;
        assert!(fees(&kraken) > 3.0 * fees(&binance), "40 bps vs 10 bps taker");
        assert_eq!(binance.state().crypto_cost_venue, CostVenue::Binance);
    }

    // ── live order books in the cost model ──

    /// Real candles for one market, so it counts as bar-backed.
    fn with_bars(e: &mut Engine, id: &str) {
        let bars: Vec<Ohlc> = (0..5)
            .map(|i| Ohlc { ts: i * 300_000, open: 100.0, high: 101.0, low: 99.0, close: 100.0, volume: 1.0 })
            .collect();
        e.apply_bars(&[BarSeries { id: id.into(), bars }]);
    }

    /// A 20-level book around `mid` with `half_bps` of half-spread and
    /// `per_level` quote currency on every level of both sides.
    fn book(e: &Engine, venue: CostVenue, mid: f64, half_bps: f64, per_level: f64, age_ms: i64) -> BookQuote {
        let half = mid * half_bps / 10_000.0;
        let bids: Vec<_> = (0..20).map(|i| (mid - half - i as f64 * 0.01, per_level / (mid - half))).collect();
        let asks: Vec<_> = (0..20).map(|i| (mid + half + i as f64 * 0.01, per_level / (mid + half))).collect();
        BookQuote::from_levels(venue, &bids, &asks, e.now() - age_ms).unwrap()
    }

    /// What a 5k paper buy of BTC pays against the quote, in bps, given
    /// whatever book the engine holds.
    fn btc_buy_fill(e: &mut Engine) -> f64 {
        let px = e.price_of("crypto:BTC/USD");
        e.live_order_for_test("crypto:BTC/USD", Side::Buy, 5_000.0);
        let avg = e.positions.get("crypto:BTC/USD").expect("a paper buy fills").avg_price;
        e.flatten("crypto:BTC/USD");
        (avg / px - 1.0) * 10_000.0
    }

    #[test]
    fn a_thin_live_book_makes_a_paper_fill_dearer_and_a_deep_one_cheaper() {
        let mut calibrated = Engine::new();
        with_bars(&mut calibrated, "crypto:BTC/USD");
        let base = btc_buy_fill(&mut calibrated);

        let mut thin = Engine::new();
        with_bars(&mut thin, "crypto:BTC/USD");
        // 20 levels of 500 USD and a 5 bp half-spread: a weekend night. The
        // book sits on the quote, so there is no drift in the number.
        let mid = thin.price_of("crypto:BTC/USD");
        let q = book(&thin, CostVenue::Kraken, mid, 5.0, 500.0, 0);
        thin.apply_books(&[BookSnapshot { id: "crypto:BTC/USD".into(), quote: q }]);
        let thin_bps = btc_buy_fill(&mut thin);

        let mut deep = Engine::new();
        with_bars(&mut deep, "crypto:BTC/USD");
        // 20 levels of 1M each, a one-tick spread: far deeper than the median.
        let q = book(&deep, CostVenue::Kraken, mid, 0.001, 1_000_000.0, 0);
        deep.apply_books(&[BookSnapshot { id: "crypto:BTC/USD".into(), quote: q }]);
        let deep_bps = btc_buy_fill(&mut deep);

        assert!(thin_bps > base, "thin book {thin_bps} bps vs calibrated {base}");
        assert!(deep_bps < base, "deep book {deep_bps} bps vs calibrated {base}");
        // The thin fill walked ten 500-dollar levels a cent apart from the 5 bp
        // ask: 5 bps plus 4.5 cents, not the square-root model's 5 bps plus
        // impact of 5k against 10k.
        let walked = 5.0 + 0.045 / mid * 10_000.0;
        assert!((thin_bps - walked).abs() < 0.01, "{thin_bps} vs {walked}");
        let m = thin.markets.iter().find(|m| m.id == "crypto:BTC/USD").cloned().unwrap();
        let modelled = thin.cost_model(&m).impact_bps(5_000.0, Some(10_000.0)) + 5.0;
        assert!(thin_bps < modelled, "the levels held enough: {thin_bps} vs model {modelled}");
    }

    /// A fixture book: asks 100.0, 100.5, 101.0 (2, 2, 2 coins), bids 99.5,
    /// 99.0, 98.5 (1, 1, 1), on Kraken, fresh.
    fn fixture_book(e: &Engine) -> BookQuote {
        let bids = [(99.5, 1.0), (99.0, 1.0), (98.5, 1.0)];
        let asks = [(100.0, 2.0), (100.5, 2.0), (101.0, 2.0)];
        BookQuote::from_levels(CostVenue::Kraken, &bids, &asks, e.now()).unwrap()
    }

    /// An engine whose BTC market is real (bar-backed), priced at `price`,
    /// with the fixture book installed.
    fn engine_on_fixture(price: f64) -> Engine {
        let mut e = Engine::new();
        with_bars(&mut e, "crypto:BTC/USD");
        if let Some(m) = e.markets.iter_mut().find(|m| m.id == "crypto:BTC/USD") {
            m.price = price;
        }
        let q = fixture_book(&e);
        e.apply_books(&[BookSnapshot { id: "crypto:BTC/USD".into(), quote: q }]);
        e
    }

    #[test]
    fn a_paper_market_buy_walks_the_book_and_pays_the_vwap_plus_the_taker_fee() {
        let mut e = engine_on_fixture(100.0);
        let sid = e.ensure_manual_strategy();
        let m = e.markets.iter().find(|m| m.id == "crypto:BTC/USD").cloned().unwrap();
        // 3 coins: 2 at 100.0 and 1 at 100.5.
        e.fill(sid, &m, Side::Buy, 3.0, 100.0);
        let want_px = (2.0 * 100.0 + 1.0 * 100.5) / 3.0;
        let p = e.positions.get("crypto:BTC/USD").unwrap();
        assert!((p.avg_price - want_px).abs() < 1e-9, "{} vs {want_px}", p.avg_price);
        // Kraken's 40 bps taker fee on the notional actually paid.
        let fees = e.strategies[sid].ledger.fees;
        assert!((fees - want_px * 3.0 * 0.004).abs() < 1e-9, "{fees}");
        let o = &e.orders[0];
        assert_eq!(o.route, FillRoute::Paper);
        assert_eq!(o.cost_source, Some(CostSource::Live));
        assert!(!o.book_exhausted);
        // Realised against the signal price, next to what the model expected.
        let realised = o.realised_slippage_bps.unwrap();
        assert!((realised - (want_px / 100.0 - 1.0) * 10_000.0).abs() < 1e-6);
        assert!(o.modelled_slippage_bps.is_some());
        // Mid is 99.75 against a signal of 100: the market had moved 25 bps in
        // the buyer's favour, which is negative drift.
        assert!((o.drift_bps.unwrap() + 25.0).abs() < 1e-9, "{:?}", o.drift_bps);
        // The record keeps a paper row for the venue, and nothing for tax.
        let row = e.slippage_report().into_iter().find(|r| r.route == FillRoute::Paper).unwrap();
        assert_eq!((row.venue.as_str(), row.fills, row.live_fills), ("kraken", 1, 1));
        assert!(e.drain_fill_records().is_empty());
    }

    #[test]
    fn a_paper_sell_walks_the_bids_and_an_order_bigger_than_the_book_is_flagged() {
        let mut e = engine_on_fixture(99.75);
        let sid = e.ensure_manual_strategy();
        let m = e.markets.iter().find(|m| m.id == "crypto:BTC/USD").cloned().unwrap();
        // The bids hold 3 coins; selling 5 runs out after 98.5.
        e.fill(sid, &m, Side::Sell, 5.0, 99.75);
        let o = e.orders[0].clone();
        assert!(o.book_exhausted, "past the listed levels must be flagged");
        let px = o.avg_fill_price.unwrap();
        // The walked part averages 99.0; the rest is never better than 98.5.
        assert!(px <= (99.5 + 99.0 + 98.5 + 2.0 * 98.5) / 5.0 + 1e-9, "{px}");
        assert!(px < 99.0);
        assert!(e.journal.iter().any(|j| j.message.contains("outgrew the 20 book levels")));
        let row = e.slippage_report().into_iter().find(|r| r.route == FillRoute::Paper).unwrap();
        assert_eq!(row.exhausted, 1);
    }

    #[test]
    fn without_a_fresh_book_a_paper_fill_stays_on_the_model_and_says_so() {
        let mut e = Engine::new();
        with_bars(&mut e, "crypto:BTC/USD");
        let sid = e.ensure_manual_strategy();
        let m = e.markets.iter().find(|m| m.id == "crypto:BTC/USD").cloned().unwrap();
        e.fill(sid, &m, Side::Buy, 0.01, m.price);
        let o = &e.orders[0];
        assert_eq!(o.cost_source, Some(CostSource::Default));
        assert_eq!(o.drift_bps, None);
        let (r, md) = (o.realised_slippage_bps.unwrap(), o.modelled_slippage_bps.unwrap());
        assert!((r - md).abs() < 1e-6, "on the model, realised is the model: {r} vs {md}");
    }

    // ── demo routing ──

    /// An engine whose crypto demo route (Bybit demo) has keys. Nothing armed.
    fn demo_engine() -> (Engine, String) {
        let mut e = Engine::new();
        e.set_demo_venues([Venue::Crypto].into_iter().collect(), Some(CostVenue::Bybit), true);
        let idx = e.ensure_manual_strategy();
        let sid = e.strategies[idx].id.clone();
        (e, sid)
    }

    /// Send a 1k demo buy of BTC and let the venue fill it at `px`.
    fn demo_fill(e: &mut Engine, sid: &str, px: f64) -> LiveOrderOut {
        e.place_order(sid, "crypto:BTC/USD", Side::Buy, 1_000.0, RouteIntent::Demo).expect("routed");
        let o = e.drain_live_orders().pop().expect("a demo order reached the outbox");
        e.apply_live_ack(&o.order_id, "demo-1");
        e.apply_live_update(&o.order_id, update(BrokerOrderStatus::Filled, o.qty, px));
        o
    }

    #[test]
    fn a_demo_order_goes_out_without_the_live_arm_and_is_booked_as_demo_not_taxed() {
        let (mut e, sid) = demo_engine();
        assert!(!e.live_config().armed, "demo must not need the live arm");
        e.place_order(&sid, "crypto:BTC/USD", Side::Buy, 1_000.0, RouteIntent::Demo).unwrap();
        let o = e.drain_live_orders().pop().expect("a demo order reached the outbox");
        assert!(o.demo && !o.paper && !o.dry_run, "{o:?}");
        let row = e.orders.iter().find(|x| x.id == o.order_id).unwrap();
        assert_eq!((row.route, row.status), (FillRoute::Demo, OrderStatus::Pending));
        assert!(e.journal.iter().any(|j| j.message.starts_with("DEMO submit")));
        assert!(e.positions.get("crypto:BTC/USD").is_none(), "nothing is booked before the venue answers");

        e.apply_live_ack(&o.order_id, "demo-1");
        let polls = e.live_polls();
        assert!(polls[0].demo && !polls[0].paper, "the poll asks the demo world");
        // The venue fills it in two parts.
        e.apply_live_update(&o.order_id, update(BrokerOrderStatus::PartiallyFilled, o.qty / 2.0, 67_300.0));
        e.apply_live_update(&o.order_id, update(BrokerOrderStatus::Filled, o.qty, 67_300.0));

        let p = e.positions.get("crypto:BTC/USD").expect("the demo fill opened a position");
        assert!(p.demo && !p.live, "demo, never real");
        assert!((p.qty - o.qty).abs() < 1e-12, "partial fills book once each");
        let view = e.state().positions.into_iter().find(|v| v.market_id == "crypto:BTC/USD").unwrap();
        assert!(view.demo && !view.live && view.mode == Mode::Paper);
        let row = e.orders.iter().find(|x| x.id == o.order_id).unwrap();
        assert_eq!((row.route, row.mode, row.status), (FillRoute::Demo, Mode::Paper, OrderStatus::Filled));
        assert!(row.realised_slippage_bps.is_some() && row.modelled_slippage_bps.is_some());
        assert!(e.drain_fill_records().is_empty(), "a demo fill never enters the tax record");
        assert!(e.journal.iter().any(|j| j.message.starts_with("DEMO FILL")));
        // Its slippage is kept under the demo exchange, as a demo row, and
        // the execution policy (which learns for real venues) is untouched.
        let r = e.slippage_report();
        assert!(r.iter().any(|x| x.venue == "bybit" && x.route == FillRoute::Demo && x.fills == 1), "{r:?}");
        assert!(e.execution_report().is_empty());
        let live = e.state().live;
        assert_eq!((live.demo_positions, live.live_positions), (1, 0));
        assert_eq!(live.demo_exchange, Some(CostVenue::Bybit));
    }

    #[test]
    fn demo_needs_demo_keys_and_still_answers_to_the_risk_manager() {
        let mut e = Engine::new();
        let idx = e.ensure_manual_strategy();
        let sid = e.strategies[idx].id.clone();
        let err = e.place_order(&sid, "crypto:BTC/USD", Side::Buy, 1_000.0, RouteIntent::Demo).unwrap_err();
        assert!(err.contains("demo"), "{err}");
        assert!(e.set_strategy_state("ema-cross-1", StrategyState::Demo).is_err());
        assert!(e.drain_live_orders().is_empty());

        let (mut e, sid) = demo_engine();
        e.toggle_kill();
        assert!(e.place_order(&sid, "crypto:BTC/USD", Side::Buy, 1_000.0, RouteIntent::Demo).is_err());
        assert!(e.drain_live_orders().is_empty(), "the kill switch stops demo orders too");
        // Live is never reachable through this entry point.
        e.toggle_kill();
        assert!(e.place_order(&sid, "crypto:BTC/USD", Side::Buy, 1_000.0, RouteIntent::Live).is_err());
        assert!(e.drain_live_orders().is_empty());
        // Polymarket has no demo world.
        assert!(e.demo_test_block("polymarket:fed-cut-2026").is_some());
    }

    #[test]
    fn a_demo_strategy_routes_its_entries_demo() {
        let (mut e, _) = demo_engine();
        e.set_strategy_state("ema-cross-1", StrategyState::Demo).unwrap();
        assert_eq!(Engine::entry_intent(StrategyState::Demo), RouteIntent::Demo);
        assert_eq!(Engine::entry_intent(StrategyState::Live), RouteIntent::Live);
        assert_eq!(Engine::entry_intent(StrategyState::Paper), RouteIntent::Paper);
        // No passport needed: nothing real is at stake.
        assert_eq!(e.strategy_config("ema-cross-1").unwrap().state, StrategyState::Demo);
    }

    #[test]
    fn a_demo_position_exits_at_the_demo_venue_and_never_mixes_with_paper() {
        let (mut e, sid) = demo_engine();
        demo_fill(&mut e, &sid, 67_300.0);
        // A paper order into the same market is refused, not merged.
        let err = e.place_order(&sid, "crypto:BTC/USD", Side::Buy, 500.0, RouteIntent::Paper).unwrap_err();
        assert!(err.contains("demo position"), "{err}");
        let before = e.positions.get("crypto:BTC/USD").unwrap().qty;
        assert!(e.drain_live_orders().is_empty());

        e.flatten("crypto:BTC/USD");
        let exit = e.drain_live_orders().pop().expect("the exit goes to the demo venue");
        assert!(exit.demo && exit.reduce_only && exit.side == Side::Sell);
        assert!((exit.qty - before).abs() < 1e-12);
        e.apply_live_ack(&exit.order_id, "demo-2");
        e.apply_live_update(&exit.order_id, update(BrokerOrderStatus::Filled, exit.qty, 67_400.0));
        assert!(e.positions.get("crypto:BTC/USD").is_none());
        assert_eq!(e.strategy_config(&sid).unwrap().ledger.demo_trades, 1);
        assert_eq!(e.strategy_config(&sid).unwrap().ledger.live_trades, 0);
        assert!(e.drain_fill_records().is_empty());
    }

    #[test]
    fn a_demo_exit_without_demo_keys_is_simulated_and_says_so() {
        let (mut e, sid) = demo_engine();
        demo_fill(&mut e, &sid, 67_300.0);
        e.set_demo_venues(HashSet::new(), None, false);
        e.flatten("crypto:BTC/USD");
        assert!(e.drain_live_orders().is_empty());
        assert!(e.positions.get("crypto:BTC/USD").is_none(), "no position nothing could ever close");
        assert!(e.journal.iter().any(|j| j.message.contains("SIMULATED")));
    }

    #[test]
    fn reconciliation_never_turns_a_demo_position_real() {
        let mut e = Engine::new();
        e.set_demo_venues([Venue::Alpaca].into_iter().collect(), None, true);
        e.set_broker_status(open_market(&e));
        let idx = e.ensure_manual_strategy();
        let sid = e.strategies[idx].id.clone();
        e.place_order(&sid, "alpaca:AAPL", Side::Buy, 1_000.0, RouteIntent::Demo).unwrap();
        let o = e.drain_live_orders().pop().unwrap();
        assert!(o.demo);
        e.apply_live_ack(&o.order_id, "p-1");
        e.apply_live_update(&o.order_id, update(BrokerOrderStatus::Filled, o.qty, 228.0));
        let held = BrokerPosition { symbol: "AAPL".into(), qty: o.qty + 5.0, avg_price: 228.0, market_value: 0.0 };
        assert_eq!(e.reconcile_positions(Venue::Alpaca, &[held], true), 0);
        let p = e.positions.get("alpaca:AAPL").unwrap();
        assert!(p.demo && !p.live && (p.qty - o.qty).abs() < 1e-12);
    }

    #[test]
    fn a_demo_order_in_flight_and_a_demo_position_survive_a_restart() {
        let (mut e, sid) = demo_engine();
        demo_fill(&mut e, &sid, 67_300.0);
        e.place_order(&sid, "crypto:ETH/USD", Side::Buy, 1_000.0, RouteIntent::Demo).unwrap();
        let o = e.drain_live_orders().pop().unwrap();
        e.apply_live_ack(&o.order_id, "demo-9");
        let back = restored(&e);
        assert!(back.positions.get("crypto:BTC/USD").unwrap().demo);
        let polls = back.live_polls();
        assert_eq!(polls.len(), 1);
        assert!(polls[0].demo, "a restored demo order is still asked of the demo world");
    }

    #[test]
    fn a_real_money_fill_is_taxed_and_labelled_live() {
        let mut e = engine_with_open_market();
        e.set_live(LiveConfig { paper: false, ..armed_alpaca() });
        e.live_order_for_test("alpaca:AAPL", Side::Buy, 1_000.0);
        let o = e.drain_live_orders().pop().unwrap();
        assert!(!o.demo && !o.paper);
        e.apply_live_ack(&o.order_id, "real-1");
        e.apply_live_update(&o.order_id, update(BrokerOrderStatus::Filled, o.qty, 228.0));
        assert_eq!(e.drain_fill_records().len(), 1, "one tax record for the real fill");
        assert_eq!(e.orders.iter().find(|x| x.id == o.order_id).unwrap().route, FillRoute::Live);
        assert!(e.positions.get("alpaca:AAPL").unwrap().live);
    }

    #[test]
    fn the_demo_connection_test_needs_demo_keys_not_the_arm() {
        let mut e = Engine::new();
        assert!(e.demo_connection_test_order("crypto:BTC/USD", 10.0).is_err());
        let (mut e2, _) = demo_engine();
        e2.demo_connection_test_order("crypto:BTC/USD", e2.demo_test_notional("crypto:BTC/USD")).unwrap();
        let o = e2.drain_live_orders().pop().expect("the test order went out");
        assert!(o.demo && o.side == Side::Buy);
        // And it must not have touched the live path.
        assert!(e.test_order_block("crypto:BTC/USD").is_some());
    }

    #[test]
    fn a_stale_or_foreign_book_falls_back_to_the_calibrated_default() {
        let mut calibrated = Engine::new();
        with_bars(&mut calibrated, "crypto:BTC/USD");
        let base = btc_buy_fill(&mut calibrated);

        let mut stale = Engine::new();
        with_bars(&mut stale, "crypto:BTC/USD");
        let q = book(&stale, CostVenue::Kraken, 67_000.0, 5.0, 500.0, crate::orderbook::MAX_BOOK_AGE_MS + 5_000);
        stale.apply_books(&[BookSnapshot { id: "crypto:BTC/USD".into(), quote: q }]);
        assert!((btc_buy_fill(&mut stale) - base).abs() < 1e-6, "a book older than a minute is not used");

        // A Kraken book while Binance executes says nothing about Binance.
        let mut binance_base = Engine::new();
        binance_base.set_crypto_cost_venue(Some(CostVenue::Binance));
        with_bars(&mut binance_base, "crypto:BTC/USD");
        let b_base = btc_buy_fill(&mut binance_base);
        let mut foreign = Engine::new();
        foreign.set_crypto_cost_venue(Some(CostVenue::Binance));
        with_bars(&mut foreign, "crypto:BTC/USD");
        let q = book(&foreign, CostVenue::Kraken, 67_000.0, 5.0, 500.0, 0);
        foreign.apply_books(&[BookSnapshot { id: "crypto:BTC/USD".into(), quote: q }]);
        assert!((btc_buy_fill(&mut foreign) - b_base).abs() < 1e-6);
    }

    #[test]
    fn books_are_kept_only_for_bar_backed_crypto_markets() {
        let mut e = Engine::new();
        with_bars(&mut e, "crypto:BTC/USD");
        let q = book(&e, CostVenue::Kraken, 100.0, 1.0, 1_000.0, 0);
        e.apply_books(&[
            BookSnapshot { id: "crypto:BTC/USD".into(), quote: q },
            // Still on the simulator: no real price for the book to sit around.
            BookSnapshot { id: "crypto:ETH/USD".into(), quote: q },
            // Not a crypto market, and not one at all.
            BookSnapshot { id: "alpaca:AAPL".into(), quote: q },
            BookSnapshot { id: "crypto:NOPE/USD".into(), quote: q },
        ]);
        assert_eq!(e.books.len(), 1);
        assert!(e.books.contains_key("crypto:BTC/USD"));
        assert!(e.journal.iter().any(|j| j.message.contains("Order book feed")));
    }

    #[test]
    fn a_live_crypto_fill_records_that_its_model_came_from_the_live_book() {
        let mut e = Engine::new();
        e.set_live(LiveConfig { venues: vec![Venue::Crypto], ..armed_alpaca() });
        with_bars(&mut e, "crypto:BTC/USD");
        let q = book(&e, CostVenue::Kraken, 67_000.0, 3.0, 2_000.0, 0);
        e.apply_books(&[BookSnapshot { id: "crypto:BTC/USD".into(), quote: q }]);

        e.live_order_for_test("crypto:BTC/USD", Side::Buy, 1_000.0);
        let o = e.drain_live_orders().pop().expect("an order went out");
        let m = e.markets.iter().find(|m| m.id == "crypto:BTC/USD").cloned().unwrap();
        let want = ExecCost::for_order(e.cost_model(&m), CostVenue::Kraken, Some(&q), Side::Buy, e.now())
            .slippage_bps(o.qty * o.ref_price);
        e.apply_live_ack(&o.order_id, "k1");
        e.apply_live_update(&o.order_id, update(BrokerOrderStatus::Filled, o.qty, o.ref_price * 1.0005));

        let row = e.slippage_report().into_iter().find(|r| r.venue == "kraken").expect("a kraken row");
        assert_eq!((row.fills, row.live_fills), (1, 1));
        assert!((row.median_modelled_bps - want).abs() < 1e-9, "{} vs {want}", row.median_modelled_bps);
        assert!(want > 3.0, "the live 3 bp half-spread, not the calibrated 0.01");
        let v = serde_json::to_value(e.state()).unwrap();
        assert_eq!(v["slippage"][0]["liveFills"], 1, "the UI sees how many fills used a live book");
    }

    #[test]
    fn a_round_trip_reports_gross_costs_and_net_that_add_up() {
        let mut e = Engine::new();
        e.live_order_for_test("alpaca:AAPL", Side::Buy, 5_000.0);
        assert!(e.positions.contains_key("alpaca:AAPL"));
        e.flatten("alpaca:AAPL");
        assert!(!e.positions.contains_key("alpaca:AAPL"));
        let s = e.strategies.iter().find(|s| s.id == "manual").unwrap().clone();
        let p = s.ledger.pnl;
        assert!((p.gross - p.costs - p.net).abs() < 1e-9);
        assert!((p.net - (s.pnl - s.ledger.fees)).abs() < 1e-9);
        // Same price in and out: gross is roughly zero, the loss is all costs.
        assert!(p.gross.abs() < 1e-6, "gross {}", p.gross);
        assert!(p.costs > 0.0);
        assert_eq!(s.ledger.fees, 0.0, "Alpaca charges no commission");
        assert!(p.cost_heavy, "costs on no gross profit are flagged");
    }

    #[test]
    fn risk_kill_switch_blocks_buys() {
        let mut e = Engine::new();
        e.limits.kill_switch = true;
        e.live_order_for_test("crypto:BTC/USD", Side::Buy, 1_000.0);
        // a buy under kill switch must not open a position
        assert!(e.positions.get("crypto:BTC/USD").is_none());
        // and it should be journaled as a rejection
        assert!(e.orders.iter().any(|o| o.status == OrderStatus::Rejected));
    }

    /// Arm helper: Alpaca only, paper endpoint, real submission.
    fn armed_alpaca() -> LiveConfig {
        LiveConfig {
            armed: true,
            paper: true,
            dry_run: false,
            venues: vec![Venue::Alpaca],
            timeout_sec: 120,
            extended_hours: false,
        }
    }

    /// Arm helper with the extended-hours opt-in set.
    fn armed_alpaca_ext(extended_hours: bool) -> LiveConfig {
        LiveConfig { extended_hours, ..armed_alpaca() }
    }

    fn update(status: BrokerOrderStatus, filled: f64, price: f64) -> LiveUpdate {
        LiveUpdate { status, filled_qty: filled, avg_price: Some(price), fee: 0.0, raw_status: format!("{status:?}") }
    }

    /// An engine whose Alpaca session gate is open: a fresh broker snapshot
    /// saying the market is open and the account healthy. Live Alpaca entries
    /// are refused without one, so every routing test starts here.
    fn engine_with_open_market() -> Engine {
        let mut e = Engine::new();
        let status = open_market(&e);
        e.set_broker_status(status);
        e
    }

    /// A permissive broker snapshot: market open, account healthy, just checked.
    fn open_market(e: &Engine) -> BrokerStatus {
        BrokerStatus {
            market_open: true,
            extended_open: true,
            session_end: None,
            next_open: None,
            day_trade_limit_reached: false,
            restricted: None,
            equity: 100_000.0,
            buying_power: 200_000.0,
            checked_at: e.now(),
        }
    }

    #[test]
    fn live_routing_needs_both_the_arm_and_the_venue() {
        let mut e = Engine::new();

        // Disarmed: a manual Alpaca order fills as paper immediately, nothing queued.
        e.live_order_for_test("alpaca:AAPL", Side::Buy, 1_000.0);
        assert!(e.drain_live_orders().is_empty());
        assert!(e.positions.contains_key("alpaca:AAPL"));
        e.flatten("alpaca:AAPL");
        assert!(e.drain_live_orders().is_empty(), "paper position flattens paper even later");

        // Arm live (paper endpoint). A manual Alpaca order now routes to the outbox
        // and does NOT open a position until the broker confirms.
        e.set_live(armed_alpaca());
        let status = open_market(&e);
        e.set_broker_status(status);
        e.live_order_for_test("alpaca:AAPL", Side::Buy, 1_000.0);
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
        e.live_order_for_test("crypto:BTC/USD", Side::Buy, 1_000.0);
        assert!(e.drain_live_orders().is_empty());
        assert!(e.positions.contains_key("crypto:BTC/USD"));
    }

    #[test]
    fn crypto_routes_live_once_its_venue_is_armed() {
        let mut e = Engine::new();
        e.set_live(LiveConfig {
            armed: true,
            paper: false,
            dry_run: false,
            venues: vec![Venue::Crypto],
            timeout_sec: 60,
            extended_hours: false,
        });
        e.live_order_for_test("crypto:BTC/USD", Side::Buy, 1_000.0);
        let out = e.drain_live_orders();
        assert_eq!(out.len(), 1, "crypto must route when Crypto is armed");
        assert_eq!(out[0].venue, Venue::Crypto);
        assert_eq!(out[0].symbol, "BTC/USD");
        // ...and Alpaca must not, because it is not in the list.
        e.live_order_for_test("alpaca:AAPL", Side::Buy, 1_000.0);
        assert!(e.drain_live_orders().is_empty());
    }

    #[test]
    fn partial_fills_book_once_each_not_once_per_poll() {
        let mut e = engine_with_open_market();
        e.set_live(armed_alpaca());
        e.live_order_for_test("alpaca:AAPL", Side::Buy, 10_000.0);
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
        let mut e = engine_with_open_market();
        e.set_live(armed_alpaca());
        e.live_order_for_test("alpaca:NVDA", Side::Buy, 5_000.0);
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
        let mut e = engine_with_open_market();
        e.set_live(armed_alpaca());
        e.live_order_for_test("alpaca:AAPL", Side::Buy, 1_000.0);
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
                demo: false,
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
        let mut e = engine_with_open_market();
        e.set_live(LiveConfig { timeout_sec: 15, ..armed_alpaca() });
        e.live_order_for_test("alpaca:MSFT", Side::Buy, 1_000.0);
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
        let mut e = engine_with_open_market();
        e.set_live(armed_alpaca());
        e.live_order_for_test("alpaca:TSLA", Side::Buy, 1_000.0);
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
    fn adaptive_execution_is_off_until_asked_and_then_learns_from_its_own_fills() {
        let mut e = engine_with_open_market();
        assert!(!e.adaptive_execution(), "resting orders inside the spread is opt-in");

        // Off: every order crosses, exactly as before.
        e.set_live(armed_alpaca());
        e.live_order_for_test("alpaca:AAPL", Side::Buy, 1_000.0);
        let o = e.drain_live_orders().remove(0);
        assert_eq!(o.style, bandit::ExecStyle::Cross);

        // Complete it worse than arrival — that is a cost, and the policy must
        // be told even while it is disabled, or turning it on starts blind.
        e.apply_live_ack(&o.order_id, "b1");
        let filled = o.ref_price * 1.002; // 20bps of slippage
        e.apply_live_update(&o.order_id, update(BrokerOrderStatus::Filled, o.qty, filled));

        let rows = e.execution_report();
        let cross = rows.iter().find(|r| r.style == "cross").expect("the fill should be recorded");
        assert_eq!(cross.fills, 1);
        assert!(cross.mean_cost_bps > 8.0, "20bps of slippage should raise the estimate: {}", cross.mean_cost_bps);
    }

    #[test]
    fn an_order_that_never_fills_teaches_the_policy_that_waiting_is_not_free() {
        let mut e = engine_with_open_market();
        e.set_adaptive_execution(true);
        e.set_live(armed_alpaca());
        e.live_order_for_test("alpaca:NVDA", Side::Buy, 1_000.0);
        let o = e.drain_live_orders().remove(0);
        e.apply_live_ack(&o.order_id, "b2");
        // Timed out and cancelled with nothing done.
        e.apply_live_update(&o.order_id, update(BrokerOrderStatus::Canceled, 0.0, 0.0));

        let row = e
            .execution_report()
            .into_iter()
            .find(|r| r.misses > 0)
            .expect("a miss must be recorded, not silently ignored");
        assert!(row.mean_cost_bps > 8.0, "missing a trade is a real cost: {}", row.mean_cost_bps);
        assert!(e.journal.iter().any(|j| j.message.contains("Adaptive execution ON")));
    }

    #[test]
    fn what_the_execution_policy_learned_survives_a_restart() {
        let mut e = engine_with_open_market();
        e.set_adaptive_execution(true);
        e.set_live(armed_alpaca());
        e.live_order_for_test("alpaca:AAPL", Side::Buy, 1_000.0);
        let o = e.drain_live_orders().remove(0);
        e.apply_live_ack(&o.order_id, "b3");
        e.apply_live_update(&o.order_id, update(BrokerOrderStatus::Filled, o.qty, o.ref_price));

        let json = serde_json::to_string(&e.to_persisted()).unwrap();
        let mut e2 = Engine::new();
        e2.apply_persisted(serde_json::from_str(&json).unwrap());
        assert!(e2.adaptive_execution());
        assert_eq!(
            e2.execution_report().len(),
            e.execution_report().len(),
            "a bandit that forgets on restart never gets past exploring"
        );
    }

    #[test]
    fn a_refused_market_backs_off_instead_of_retrying_every_tick() {
        let mut e = engine_with_open_market();
        e.set_live(armed_alpaca());
        e.live_order_for_test("alpaca:TSLA", Side::Buy, 1_000.0);
        let o = e.drain_live_orders().remove(0);
        e.apply_live_reject(&o.order_id, "US market closed");

        // The same signal fires again immediately — it must not resend.
        e.live_order_for_test("alpaca:TSLA", Side::Buy, 1_000.0);
        assert!(e.drain_live_orders().is_empty(), "a closed market must not get one order per tick");

        // A different market is unaffected.
        e.live_order_for_test("alpaca:AAPL", Side::Buy, 1_000.0);
        assert_eq!(e.drain_live_orders().len(), 1);

        // Once the backoff expires it tries again — the market may have opened.
        e.live_backoff_until.insert("alpaca:TSLA".into(), 0);
        e.live_order_for_test("alpaca:TSLA", Side::Buy, 1_000.0);
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
        // LiveStatus carries fields from both the multi-venue and the Alpaca
        // session work; the Live page reads every one of them by these names.
        for key in ["venues", "timeoutSec", "connected", "extendedHours", "alpacaConnected", "pending", "livePositions"] {
            assert!(v["live"].get(key).is_some(), "LiveStatus is missing `{key}` on the wire");
        }
        assert!(v["forecastStats"]["trustedSources"].is_number());
        assert!(v["forecastStats"]["recorded"].as_u64().unwrap() > 0);

        // Honest numbers: the cost ledger per strategy, the realised-slippage
        // table and the crypto cost venue all reach the UI under these names.
        for key in ["slippage", "cryptoCostVenue"] {
            assert!(obj.contains_key(key), "EngineState is missing `{key}` on the wire");
        }
        assert_eq!(v["cryptoCostVenue"], "kraken");
        let ledger = &v["strategies"][0]["ledger"];
        for key in ["fees", "slippage", "gross", "pnl", "forwardTrades", "liveTrades", "paperSince"] {
            assert!(ledger.get(key).is_some(), "StrategyLedger is missing `{key}` on the wire");
        }
        for key in ["gross", "costs", "net", "costHeavy"] {
            assert!(ledger["pnl"].get(key).is_some(), "PnlBreakdown is missing `{key}` on the wire");
        }
        assert!(ledger.get("forward_trades").is_none(), "snake_case must not leak to the UI");

        // Portfolio risk layer: the new limit and the Risk page's live numbers.
        assert!(v["limits"]["maxCorrelatedExposurePct"].is_number(), "RiskLimits is missing maxCorrelatedExposurePct");
        assert!(v["limits"]["portfolioVolTargetPct"].is_number(), "RiskLimits is missing portfolioVolTargetPct");
        for key in [
            "correlatedExposure",
            "correlatedExposurePct",
            "sizing",
            "drawdownPct",
            "deriskFactor",
            "portfolioVol",
            "portfolioVolPct",
            "volAssumed",
        ] {
            assert!(v["risk"].get(key).is_some(), "RiskStatus is missing `{key}` on the wire");
        }
        for key in ["strategyId", "mode", "trades"] {
            assert!(v["risk"]["sizing"][0].get(key).is_some(), "StrategySizing is missing `{key}` on the wire");
        }
        assert_eq!(v["risk"]["sizing"][0]["mode"], "confidence");
        for key in ["wins", "losses", "winReturnSum", "lossReturnSum"] {
            assert!(ledger["edge"].get(key).is_some(), "EdgeRecord is missing `{key}` on the wire");
        }
    }

    #[test]
    fn a_live_fill_reaches_the_wire_with_its_realised_and_modelled_slippage() {
        let mut e = engine_with_open_market();
        e.set_live(armed_alpaca());
        e.live_order_for_test("alpaca:AAPL", Side::Buy, 1_000.0);
        let o = e.drain_live_orders().pop().expect("an order went out");
        e.apply_live_ack(&o.order_id, "b1");
        e.apply_live_update(&o.order_id, update(BrokerOrderStatus::Filled, o.qty, o.ref_price * 1.0005));

        let v = serde_json::to_value(e.state()).unwrap();
        let row = &v["slippage"][0];
        assert_eq!(row["venue"], "alpaca");
        assert_eq!(row["fills"], 1);
        assert!((row["medianRealisedBps"].as_f64().unwrap() - 5.0).abs() < 1e-6);
        assert!(row["medianModelledBps"].as_f64().unwrap() > 0.0);
        assert!(row.get("ratio").is_some());
        assert_eq!(row["enough"], false);
        let ord = v["orders"].as_array().unwrap().iter().find(|x| x["id"] == o.order_id.as_str()).unwrap();
        assert!((ord["realisedSlippageBps"].as_f64().unwrap() - 5.0).abs() < 1e-6);
        assert!(ord["modelledSlippageBps"].is_number());
        // The live fill's slippage is also in the strategy's cost ledger.
        let manual = e.strategies.iter().find(|s| s.id == "manual").unwrap();
        assert!(manual.ledger.slippage > 0.0);
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
            latency_ms: 0,
            input_tokens: 0,
            output_tokens: 0,
            served_by: String::new(),
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
            latency_ms: 0, input_tokens: 0, output_tokens: 0, served_by: String::new(),
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
                strategy_id: "manual".into(), stop: 0.0, target: 0.0, trail_ref: 220.0, live: true, demo: false,
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
        e.live_order_for_test("alpaca:AAPL", Side::Buy, 1_000.0); // paper fill
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
        e.set_live(LiveConfig { venues: vec![], timeout_sec: 60, ..armed_alpaca() });
        e.live_order_for_test("alpaca:AAPL", Side::Buy, 1_000.0);
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
                strategy_id: "manual".into(), stop: 0.0, target: 0.0, trail_ref: 227.0, live: true, demo: false,
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

    #[test]
    fn live_entries_need_a_fresh_broker_status() {
        let mut e = Engine::new();
        e.set_live(armed_alpaca());

        // Never checked → refuse. "Probably open" is not a risk control.
        assert!(e.live_block_reason().is_some());
        e.live_order_for_test("alpaca:AAPL", Side::Buy, 1_000.0);
        assert!(e.drain_live_orders().is_empty(), "no order may leave without a session check");
        assert!(e.orders.iter().any(|o| o.status == OrderStatus::Rejected));

        // Checked, but hours ago → still refuse.
        let mut stale = open_market(&e);
        stale.checked_at = e.now() - 30 * 60 * 1000;
        e.set_broker_status(stale);
        assert!(e.live_block_reason().unwrap().contains("stale"));

        // Fresh and open → through.
        let ok = open_market(&e);
        e.set_broker_status(ok);
        assert!(e.live_block_reason().is_none());
        e.live_order_for_test("alpaca:AAPL", Side::Buy, 1_000.0);
        assert_eq!(e.drain_live_orders().len(), 1);
    }

    #[test]
    fn a_closed_market_blocks_entries_but_never_exits() {
        let mut e = Engine::new();
        e.set_live(armed_alpaca());
        let mut closed = open_market(&e);
        closed.market_open = false;
        closed.next_open = Some("2026-07-27T13:30:00Z".into());
        e.set_broker_status(closed);

        // Entry refused, with a reason a human can act on.
        e.live_order_for_test("alpaca:AAPL", Side::Buy, 1_000.0);
        assert!(e.drain_live_orders().is_empty());
        assert!(e
            .journal
            .iter()
            .any(|j| j.message.contains("market closed") && j.message.contains("2026-07-27")));

        // But an existing live position can still be closed — being stuck long
        // through a halt is worse than the order being late.
        e.positions.insert(
            "alpaca:AAPL".into(),
            PositionInternal {
                venue: Venue::Alpaca,
                symbol: "AAPL".into(),
                qty: 5.0,
                avg_price: 220.0,
                strategy_id: "manual".into(),
                stop: 0.0,
                target: 0.0,
                trail_ref: 220.0,
                live: true,
                demo: false,
            },
        );
        e.flatten("alpaca:AAPL");
        assert_eq!(e.drain_live_orders().len(), 1, "exits must not be gated by the session check");
    }

    #[test]
    fn extended_hours_is_opt_in_and_only_on_a_real_session() {
        let mut e = Engine::new();
        e.set_live(armed_alpaca()); // armed, extended hours OFF
        let mut after_hours = open_market(&e);
        after_hours.market_open = false;
        after_hours.extended_open = true;
        after_hours.session_end = Some("20:00".into());
        e.set_broker_status(after_hours.clone());

        // Off by default — and the block says the session is available.
        let why = e.live_block_reason().expect("blocked");
        assert!(why.contains("closed"), "got: {why}");
        assert!(why.contains("extended-hours session is open"), "got: {why}");

        // Opted in → the same session is tradable.
        e.set_live(armed_alpaca_ext(true));
        assert!(e.live_block_reason().is_none());

        // Opted in, but the broker says no session is running → still blocked.
        let mut overnight = after_hours;
        overnight.extended_open = false;
        e.set_broker_status(overnight);
        assert!(
            e.live_block_reason().is_some(),
            "opting in must not override the broker saying the market is shut"
        );
    }

    #[test]
    fn extended_hours_orders_are_flagged_for_the_connector() {
        let mut e = Engine::new();
        e.set_live(armed_alpaca_ext(true));
        let mut after_hours = open_market(&e);
        after_hours.market_open = false;
        after_hours.extended_open = true;
        e.set_broker_status(after_hours);

        e.live_order_for_test("alpaca:AAPL", Side::Buy, 1_000.0);
        let out = e.drain_live_orders();
        assert_eq!(out.len(), 1);
        assert!(out[0].extended_hours, "the connector needs this to send a limit order");

        // During regular hours the flag comes off, so entries go back to the
        // cheaper notional path.
        let mut e2 = Engine::new();
        e2.set_live(armed_alpaca_ext(true));
        let status = open_market(&e2);
        e2.set_broker_status(status);
        e2.live_order_for_test("alpaca:AAPL", Side::Buy, 1_000.0);
        let out2 = e2.drain_live_orders();
        assert_eq!(out2.len(), 1);
        assert!(!out2[0].extended_hours);
    }

    /// Give a strategy what it needs to go live: research gates 1 to 6 green
    /// for its current parameters and a finished paper forward test.
    fn make_live_ready(e: &mut Engine, id: &str) {
        let s = e.strategy_config(id).unwrap();
        e.store_research(validation::ResearchVerdict {
            strategy_id: id.into(),
            params: s.params.iter().map(|p| (p.key.clone(), p.value)).collect(),
            checked_at: e.now(),
            markets: 1,
            bars: 700,
            cost_venue: CostVenue::Alpaca,
            gates: (1..=6).map(|g| validation::Gate::new(g, validation::GateStatus::Pass, "test", Some(1.0))).collect(),
        });
        let now = e.now();
        let s = e.strategies.iter_mut().find(|s| s.id == id).unwrap();
        s.ledger.paper_since = Some(now - 60 * 86_400_000);
        s.ledger.forward_trades = 40;
    }

    #[test]
    fn live_is_refused_until_the_passport_is_green_and_says_why() {
        let mut e = Engine::new();
        let err = e.set_strategy_state("ema-cross-1", StrategyState::Live).unwrap_err();
        assert!(err.contains("gate 1"), "names the first open gate: {err}");
        assert_eq!(e.strategy_config("ema-cross-1").unwrap().state, StrategyState::Paper);
        assert!(e.journal.iter().any(|j| j.kind == JournalKind::Reject && j.message.contains("stays off live")));
        // Paper and pause are never gated.
        e.set_strategy_state("ema-cross-1", StrategyState::Paused).unwrap();
        e.set_strategy_state("ema-cross-1", StrategyState::Paper).unwrap();

        make_live_ready(&mut e, "ema-cross-1");
        e.set_strategy_state("ema-cross-1", StrategyState::Live).unwrap();
        assert_eq!(e.strategy_config("ema-cross-1").unwrap().state, StrategyState::Live);
    }

    #[test]
    fn changing_a_parameter_invalidates_the_checks() {
        let mut e = Engine::new();
        make_live_ready(&mut e, "ema-cross-1");
        assert!(e.passport("ema-cross-1").unwrap().live_ready);
        e.set_strategy_param("ema-cross-1", "fast", 13.0);
        let pp = e.passport("ema-cross-1").unwrap();
        assert!(pp.stale);
        assert!(!pp.live_ready);
        assert!(e.set_strategy_state("ema-cross-1", StrategyState::Live).is_err());
    }

    #[test]
    fn a_saved_live_strategy_without_a_green_passport_restores_as_paper() {
        let mut e = Engine::new();
        make_live_ready(&mut e, "ema-cross-1");
        e.set_strategy_state("ema-cross-1", StrategyState::Live).unwrap();
        let mut saved = e.to_persisted();
        // The checks survive the restart, so it stays live...
        let mut back = Engine::new();
        back.apply_persisted(saved.clone());
        assert_eq!(back.strategy_config("ema-cross-1").unwrap().state, StrategyState::Live);
        // ...but a save with no checks (or from before the gates) does not.
        saved.research.clear();
        let mut bare = Engine::new();
        bare.apply_persisted(saved);
        assert_eq!(bare.strategy_config("ema-cross-1").unwrap().state, StrategyState::Paper);
        assert!(bare.journal.iter().any(|j| j.message.contains("restored as PAPER")));
    }

    #[test]
    fn a_deployed_strategy_cannot_arrive_live() {
        let mut e = Engine::new();
        let mut cfg = e.strategy_config("ema-cross-1").unwrap();
        cfg.id = "copy".into();
        cfg.state = StrategyState::Live;
        cfg.ledger.forward_trades = 999; // imported evidence is not evidence
        e.add_strategy(cfg);
        let s = e.strategy_config("copy").unwrap();
        assert_eq!(s.state, StrategyState::Paper);
        assert_eq!(s.ledger.forward_trades, 0);
    }

    #[test]
    fn every_strategy_has_a_passport_on_the_wire() {
        let e = Engine::new();
        let v = serde_json::to_value(e.state()).unwrap();
        let pps = v["passports"].as_array().unwrap();
        assert_eq!(pps.len(), e.strategies.iter().filter(|s| s.id != "manual").count());
        let pp = &pps[0];
        assert_eq!(pp["gates"].as_array().unwrap().len(), 8);
        assert_eq!(pp["liveReady"], false);
        assert!(pp["blockedReason"].as_str().unwrap().contains("Not ready"));
    }

    /// End-to-end reproduction of a fully configured live setup: keys in, real
    /// equity candles loaded, armed on the paper endpoint, the equities
    /// strategy set Live, market open. An order must reach the outbox.
    #[test]
    fn a_fully_configured_setup_actually_emits_an_alpaca_order() {
        let mut e = Engine::new();

        // Real candles for the equity universe, ending on a fresh 20-bar high
        // so Donchian Breakout has something to fire on.
        let bars: Vec<Ohlc> = (0..120)
            .map(|i| {
                let c = 200.0 + i as f64 * 0.25;
                Ohlc { ts: i as i64 * 300_000, open: c, high: c + 0.5, low: c - 0.5, close: c, volume: 1000.0 }
            })
            .collect();
        e.apply_bars(&[BarSeries { id: "alpaca:AAPL".into(), bars }]);

        // A live quote above the channel high.
        e.apply_alpaca(&[RealEquity {
            id: "alpaca:AAPL".into(),
            symbol: "AAPL".into(),
            price: 260.0,
            change24h: 0.01,
        }]);

        make_live_ready(&mut e, "breakout-1");
        e.set_strategy_state("breakout-1", StrategyState::Live).expect("a green passport may go live");
        e.set_live(armed_alpaca());
        let status = open_market(&e);
        e.set_broker_status(status);

        // Tick past the strategy cadence.
        for _ in 0..12 {
            e.tick();
        }

        let out = e.drain_live_orders();
        assert!(
            !out.is_empty(),
            "a fully configured setup produced no live order. Journal:\n{}",
            e.journal
                .iter()
                .take(15)
                .map(|j| format!("  [{:?}] {}", j.kind, j.message))
                .collect::<Vec<_>>()
                .join("\n")
        );
        assert_eq!(out[0].symbol, "AAPL");
    }

    #[test]
    fn pdt_ceiling_blocks_new_entries() {
        let mut e = Engine::new();
        e.set_live(armed_alpaca());
        let mut pdt = open_market(&e);
        pdt.day_trade_limit_reached = true;
        e.set_broker_status(pdt);
        assert!(e.live_block_reason().unwrap().contains("pattern-day-trader"));
    }

    // ── Alpaca crypto ──

    #[test]
    fn alpaca_crypto_is_seeded_and_pays_alpaca_crypto_fees_not_equity_ones() {
        let e = Engine::new();
        for id in ["alpaca:BTC/USD", "alpaca:ETH/USD"] {
            let m = e.markets.iter().find(|m| m.id == id).expect("seeded");
            assert_eq!((m.venue, m.kind), (Venue::Alpaca, MarketKind::Crypto));
            assert!(e.sim.contains_key(id), "{id} needs simulator parameters until a real quote arrives");
            let c = e.cost_model(m);
            assert_eq!((c.taker_bps, c.maker_bps), (25.0, 15.0), "Alpaca crypto lowest tier");
            assert_eq!(c.borrow_bps_yr, 0.0, "crypto on Alpaca cannot be shorted, so nothing to borrow");
        }
        // Equities on the same venue stay commission-free.
        let aapl = e.markets.iter().find(|m| m.id == "alpaca:AAPL").unwrap();
        assert_eq!(e.cost_model(aapl).taker_bps, 0.0);
        // No default strategy trades them: they exist for the connection test
        // and manual orders.
        assert!(e.strategies.iter().all(|s| !s.universe.iter().any(|u| u.starts_with("alpaca:") && u.contains('/'))));
    }

    #[test]
    fn alpaca_crypto_ignores_the_equity_session_and_the_day_trade_rule() {
        let mut e = Engine::new();
        e.set_live(armed_alpaca());
        let mut closed = open_market(&e);
        closed.market_open = false;
        closed.extended_open = false;
        closed.day_trade_limit_reached = true;
        e.set_broker_status(closed.clone());

        assert!(e.test_order_block("alpaca:AAPL").unwrap().contains("closed"));
        assert_eq!(e.test_order_block("alpaca:BTC/USD"), None, "crypto trades on a Sunday");

        // The account checks still apply to crypto.
        closed.restricted = Some("trading blocked".into());
        e.set_broker_status(closed);
        assert!(e.test_order_block("alpaca:BTC/USD").unwrap().contains("restricted"));
        let mut fresh = Engine::new();
        fresh.set_live(armed_alpaca());
        assert!(fresh.test_order_block("alpaca:BTC/USD").unwrap().contains("unknown"));
    }

    #[test]
    fn the_connection_test_reaches_alpaca_crypto_while_equities_are_closed() {
        let mut e = Engine::new();
        // Extended hours opted in and running: an equity order would carry the
        // flag, a crypto one must not.
        e.set_live(armed_alpaca_ext(true));
        let mut closed = open_market(&e);
        closed.market_open = false;
        closed.extended_open = true;
        e.set_broker_status(closed);

        let n = e.connection_test_notional("alpaca:BTC/USD");
        assert_eq!(n, 20.0, "twice Alpaca's ~$10 crypto minimum");
        e.connection_test_order("alpaca:BTC/USD", n).expect("routes");
        let o = e.drain_live_orders().pop().expect("an order went out");
        assert_eq!((o.venue, o.symbol.as_str(), o.side), (Venue::Alpaca, "BTC/USD", Side::Buy));
        assert!(!o.extended_hours, "crypto never goes out as an extended-hours order");
    }

    #[test]
    fn an_alpaca_crypto_position_reconciles_onto_the_alpaca_market_not_the_kraken_one() {
        let mut e = Engine::new();
        let held = [BrokerPosition { symbol: "BTC/USD".into(), qty: 0.001, avg_price: 83_000.0, market_value: 83.0 }];
        assert_eq!(e.reconcile_positions(Venue::Alpaca, &held, true), 1);
        assert!(e.positions.get("alpaca:BTC/USD").is_some_and(|p| p.live && (p.qty - 0.001).abs() < 1e-12));
        assert!(!e.positions.contains_key("crypto:BTC/USD"));
    }

    #[test]
    fn bars_replace_tick_history_and_drop_the_forming_candle() {
        let mut e = Engine::new();
        let bars: Vec<Ohlc> = (0..30)
            .map(|i| {
                let c = 100.0 + i as f64;
                Ohlc { ts: i as i64 * 300_000, open: c - 0.5, high: c + 1.0, low: c - 1.0, close: c, volume: 10.0 }
            })
            .collect();
        e.apply_bars(&[BarSeries { id: "crypto:BTC/USD".into(), bars: bars.clone() }]);

        let h = e.history.get("crypto:BTC/USD").unwrap();
        assert_eq!(h.len(), 29, "the still-forming final candle is not tradable data");
        assert_eq!(*h.last().unwrap(), 128.0);
        assert!(e.is_bar_backed("crypto:BTC/USD"));

        // Ticking must not contaminate the candle series.
        e.tick();
        let after = e.history.get("crypto:BTC/USD").unwrap();
        assert_eq!(after.len(), 29, "the tick loop must never append to a bar-backed series");
        assert_eq!(*after.last().unwrap(), 128.0);
    }

    #[test]
    fn real_fed_prices_do_not_drift_between_refreshes() {
        let mut e = Engine::new();
        e.apply_kraken(&[RealCrypto {
            id: "crypto:BTC/USD".into(),
            symbol: "BTC/USD".into(),
            price: 67_000.0,
            change24h: 0.01,
        }]);
        for _ in 0..20 {
            e.tick();
        }
        let px = e.markets.iter().find(|m| m.id == "crypto:BTC/USD").unwrap().price;
        assert_eq!(px, 67_000.0, "a real quote must stay put until the feed says otherwise");

        // A market with no real feed still simulates, so the demo build works.
        let sim = e.markets.iter().find(|m| m.id == "crypto:SOL/USD").unwrap().price;
        assert_ne!(sim, 168.4);
    }

    #[test]
    fn reconciliation_treats_the_broker_as_truth() {
        let mut e = Engine::new();
        // Engine thinks it holds 10 AAPL and 3 MSFT.
        for (sym, qty) in [("AAPL", 10.0), ("MSFT", 3.0)] {
            e.positions.insert(
                format!("alpaca:{sym}"),
                PositionInternal {
                    venue: Venue::Alpaca,
                    symbol: sym.into(),
                    qty,
                    avg_price: 100.0,
                    strategy_id: "manual".into(),
                    stop: 90.0,
                    target: 0.0,
                    trail_ref: 100.0,
                    live: true,
                    demo: false,
                },
            );
        }

        // Broker: 4 AAPL (partial fill we missed), no MSFT, plus a surprise NVDA.
        // Adoption is opted into here, as for an account dedicated to the bot.
        let broker = [
            BrokerPosition { symbol: "AAPL".into(), qty: 4.0, avg_price: 101.0, market_value: 404.0 },
            BrokerPosition { symbol: "NVDA".into(), qty: 2.0, avg_price: 130.0, market_value: 260.0 },
        ];
        let changes = e.reconcile_positions(Venue::Alpaca, &broker, true);

        assert_eq!(e.positions.get("alpaca:AAPL").unwrap().qty, 4.0);
        assert_eq!(
            e.positions.get("alpaca:AAPL").unwrap().stop,
            0.0,
            "a stop sized for 10 shares is meaningless on 4 — recompute rather than trust it"
        );
        assert!(e.positions.get("alpaca:MSFT").is_none(), "a position the broker denies is not ours");
        assert_eq!(e.positions.get("alpaca:NVDA").unwrap().qty, 2.0);
        assert!(e.positions.get("alpaca:NVDA").unwrap().live);
        assert_eq!(changes, 3);
        assert!(e.journal.iter().any(|j| j.message.contains("Reconciled")));
        assert!(
            e.pending_alerts.iter().any(|a| a.contains("reconciled 3 position difference")),
            "a changed book is worth a webhook, not just a journal line"
        );
    }

    fn view(e: &Engine, market: &str, direction: &str, confidence: f64) -> AiView {
        AiView {
            market_id: market.into(),
            direction: direction.into(),
            probability: 0.6,
            confidence,
            rationale: "test".into(),
            model: "claude-opus-5".into(),
            ts: e.now(),
            latency_ms: 900,
        }
    }

    #[test]
    fn ai_overlay_is_inert_until_enabled() {
        let mut e = Engine::new();
        let v = view(&e, "crypto:BTC/USD", "short", 0.99);
        e.apply_ai_view(v, 100, 50);
        // Disabled by default: even a maximally confident contrary view changes nothing.
        assert_eq!(e.ai_multiplier("crypto:BTC/USD", Side::Buy).0, 1.0);
        assert_eq!(e.ai_spend.calls, 1, "cost is still tracked while disabled");
    }

    #[test]
    fn ai_vetoes_only_on_confident_disagreement() {
        let mut e = Engine::new();
        e.set_ai_policy(AiPolicy { enabled: true, ..AiPolicy::default() });

        // Confident disagreement → veto.
        let v = view(&e, "crypto:BTC/USD", "short", 0.9);
        e.apply_ai_view(v, 0, 0);
        assert_eq!(e.ai_multiplier("crypto:BTC/USD", Side::Buy).0, 0.0);

        // Mild disagreement → shrink, not block.
        let v = view(&e, "crypto:BTC/USD", "short", 0.4);
        e.apply_ai_view(v, 0, 0);
        let (m, note) = e.ai_multiplier("crypto:BTC/USD", Side::Buy);
        assert!(m > 0.0 && m < 1.0, "got {m}");
        assert!(note.unwrap().contains("disagrees"));

        // Agreement → a bounded boost, never a blank cheque.
        let v = view(&e, "crypto:BTC/USD", "long", 1.0);
        e.apply_ai_view(v, 0, 0);
        assert_eq!(e.ai_multiplier("crypto:BTC/USD", Side::Buy).0, e.ai_policy.max_boost);

        // Neutral → no opinion, no effect.
        let v = view(&e, "crypto:BTC/USD", "neutral", 1.0);
        e.apply_ai_view(v, 0, 0);
        assert_eq!(e.ai_multiplier("crypto:BTC/USD", Side::Buy).0, 1.0);
    }

    #[test]
    fn stale_ai_views_are_ignored() {
        let mut e = Engine::new();
        e.set_ai_policy(AiPolicy { enabled: true, ttl_sec: 60, ..AiPolicy::default() });
        let mut v = view(&e, "crypto:BTC/USD", "short", 0.95);
        v.ts = e.now() - 10 * 60 * 1000; // ten minutes old
        e.apply_ai_view(v, 0, 0);
        assert_eq!(
            e.ai_multiplier("crypto:BTC/USD", Side::Buy).0,
            1.0,
            "an opinion past its TTL must not veto"
        );
    }

    #[test]
    fn ai_cannot_open_a_trade_on_its_own() {
        // The overlay is a multiplier on an existing intent. With every strategy
        // paused there is no intent to multiply, so no amount of model
        // conviction can produce an order.
        let mut e = Engine::new();
        e.set_ai_policy(AiPolicy { enabled: true, ..AiPolicy::default() });
        for s in &mut e.strategies {
            s.state = StrategyState::Paused;
        }
        let v = view(&e, "crypto:BTC/USD", "long", 1.0);
        e.apply_ai_view(v, 0, 0);
        for _ in 0..30 {
            e.tick();
        }
        assert!(e.positions.is_empty(), "the overlay must never originate a position");
    }

    #[test]
    fn ai_context_only_offers_markets_with_real_bars() {
        let mut e = Engine::new();
        assert!(e.ai_candidates().is_empty(), "the simulator is not worth a model call");

        let bars: Vec<Ohlc> = (0..40)
            .map(|i| {
                let c = 100.0 + i as f64;
                Ohlc { ts: i as i64 * 300_000, open: c, high: c + 1.0, low: c - 1.0, close: c, volume: 1.0 }
            })
            .collect();
        e.apply_bars(&[BarSeries { id: "crypto:BTC/USD".into(), bars }]);

        assert_eq!(e.ai_candidates(), vec!["crypto:BTC/USD".to_string()]);
        let ctx = e.ai_context("crypto:BTC/USD").expect("context");
        assert!(ctx.contains("real exchange candles"));
        assert!(ctx.contains("RSI(14)"));
        assert!(ctx.contains("Current position: flat"));
    }

    #[test]
    fn engine_state_serializes_camel_case_for_the_ui() {
        // The TypeScript client reads these by camelCase name. A snake_case key
        // here does not fail loudly — the UI silently falls back to its default
        // and every market renders as "simulated" while real bars are loaded.
        let e = Engine::new();
        let json = serde_json::to_value(e.state()).unwrap();
        let keys: Vec<&str> = json.as_object().unwrap().keys().map(|k| k.as_str()).collect();
        for expected in ["barBacked", "aiViews", "aiPolicy", "aiSpend"] {
            assert!(keys.contains(&expected), "missing {expected} in {keys:?}");
        }
        // Pre-existing single-word keys are untouched by the rename.
        for expected in ["portfolio", "markets", "positions", "orders", "journal", "history", "live"] {
            assert!(keys.contains(&expected), "renamed an existing key: {expected}");
        }
    }

    #[test]
    fn live_flag_survives_a_restart() {
        let mut e = Engine::new();
        e.positions.insert(
            "alpaca:AAPL".into(),
            PositionInternal {
                venue: Venue::Alpaca,
                symbol: "AAPL".into(),
                qty: 5.0,
                avg_price: 220.0,
                strategy_id: "manual".into(),
                stop: 200.0,
                target: 0.0,
                trail_ref: 220.0,
                live: true,
                demo: false,
            },
        );
        let json = serde_json::to_string(&e.to_persisted()).unwrap();
        let mut e2 = Engine::new();
        e2.apply_persisted(serde_json::from_str(&json).unwrap());
        assert!(
            e2.positions.get("alpaca:AAPL").unwrap().live,
            "a restart must not downgrade real shares to a paper position"
        );
    }

    fn lab_signal(generated_ms: i64, weights: &[(&str, f64)], deflated_p: f64) -> crate::lab::LabSignal {
        crate::lab::LabSignal {
            strategy: "tsmom_regime".into(),
            variant: "28d daily vol 40% regime".into(),
            as_of_ms: generated_ms - 4 * 3_600_000,
            generated_ms,
            valid_until_ms: generated_ms + 36 * 3_600_000,
            quote: "USD".into(),
            weights: weights.iter().map(|(k, v)| (k.to_string(), *v)).collect(),
            regime_on: Some(true),
            evidence: crate::lab::LabEvidence {
                report: "momentum2".into(),
                is_sharpe: Some(1.97),
                oos_sharpe: Some(1.05),
                deflated_p: Some(deflated_p),
                sharpe_2x_cost: Some(0.93),
                variants_tried: Some(50),
                plateau_share: Some(1.0),
                regime_sharpes: [("BTC above 200d average".to_string(), 1.56)].into_iter().collect(),
                regime_filter: true,
                ..Default::default()
            },
        }
    }

    #[test]
    fn a_lab_book_moves_to_its_targets_once_per_signal_and_stays_off_live_without_gate_6() {
        let mut e = Engine::new();
        let price = |e: &Engine, id: &str| e.markets.iter().find(|m| m.id == id).unwrap().price;
        let feed: Vec<RealCrypto> = ["BTC", "ETH"]
            .iter()
            .map(|c| {
                let id = format!("crypto:{c}/USD");
                RealCrypto { price: price(&e, &id), id, symbol: format!("{c}/USD"), change24h: 0.0 }
            })
            .collect();
        e.apply_kraken(&feed);
        let now = e.now();

        e.apply_lab_signal(lab_signal(now, &[("BTC", 0.10), ("ETH", 0.05), ("PEPE", 0.02)], 0.86));
        e.run_lab_books();
        let btc = e.positions.get("crypto:BTC/USD").expect("bought BTC");
        assert_eq!(btc.strategy_id, "lab:tsmom_regime");
        assert_eq!((btc.stop, btc.target), (0.0, 0.0), "no stops the lab never tested");
        assert!(e.positions.contains_key("crypto:ETH/USD"));
        assert!(!e.positions.contains_key("crypto:PEPE/USD"), "no real PEPE price here, so no trade");
        assert!(e.journal.iter().any(|j| j.message.contains("no market here for PEPE")));

        // The same signal again: nothing new.
        let n_orders = e.orders.len();
        e.run_lab_books();
        assert_eq!(e.orders.len(), n_orders);

        // A new day drops BTC from the targets: it is sold.
        e.apply_lab_signal(lab_signal(now + 1, &[("ETH", 0.05)], 0.86));
        e.run_lab_books();
        assert!(e.positions.get("crypto:BTC/USD").map(|p| p.qty.abs() < 1e-9).unwrap_or(true));

        // Gate 6 is red (deflated p 0.86): Live is refused.
        assert!(e.set_strategy_state("lab:tsmom_regime", StrategyState::Live).is_err());
    }

    #[test]
    fn a_stale_lab_signal_is_not_traded() {
        let mut e = Engine::new();
        let feed = [RealCrypto { id: "crypto:BTC/USD".into(), symbol: "BTC/USD".into(), price: 67_000.0, change24h: 0.0 }];
        e.apply_kraken(&feed);
        let old = e.now() - 48 * 3_600_000;
        e.apply_lab_signal(lab_signal(old, &[("BTC", 0.10)], 0.86));
        e.run_lab_books();
        assert!(!e.positions.contains_key("crypto:BTC/USD"));
        assert!(e.journal.iter().any(|j| j.message.contains("past its validity window")));
    }

    /// BTC and ETH on real prices, BTC's quote too old to trade on.
    fn lab_engine_with_stale_btc() -> Engine {
        let mut e = Engine::new();
        let feed: Vec<RealCrypto> = ["BTC", "ETH"]
            .iter()
            .map(|c| {
                let id = format!("crypto:{c}/USD");
                let price = e.markets.iter().find(|m| m.id == id).unwrap().price;
                RealCrypto { price, id, symbol: format!("{c}/USD"), change24h: 0.0 }
            })
            .collect();
        e.apply_kraken(&feed);
        let old = e.now() - 120_000;
        e.markets.iter_mut().find(|m| m.id == "crypto:BTC/USD").unwrap().updated_at = old;
        e
    }

    /// Pretend the last attempt was long enough ago for the next one.
    fn age_lab_retry(e: &mut Engine) {
        for v in e.lab_retry.values_mut() {
            v.2 -= LAB_RETRY_EVERY_MS + 1;
        }
    }

    #[test]
    fn a_refused_lab_order_is_tried_again_later_and_only_what_is_missing_is_ordered() {
        let mut e = lab_engine_with_stale_btc();
        let now = e.now();
        e.apply_lab_signal(lab_signal(now, &[("BTC", 0.10), ("ETH", 0.05)], 0.86));
        e.run_lab_books();
        assert!(e.positions.contains_key("crypto:ETH/USD"), "ETH had a fresh price");
        assert!(!e.positions.contains_key("crypto:BTC/USD"), "BTC's price was stale");
        assert!(e.journal.iter().any(|j| j.message.contains("1 of 2 orders refused, trying again in 20 minutes")));
        assert!(!e.lab_done.contains_key("lab:tsmom_regime"), "the day is not done yet");

        // Too soon: nothing happens.
        let n = e.orders.len();
        e.run_lab_books();
        assert_eq!(e.orders.len(), n);

        // Later, with a fresh BTC price: only BTC is bought, ETH is not ordered again.
        let eth_qty = e.positions["crypto:ETH/USD"].qty;
        e.markets.iter_mut().find(|m| m.id == "crypto:BTC/USD").unwrap().updated_at = now;
        age_lab_retry(&mut e);
        e.run_lab_books();
        assert!(e.positions.contains_key("crypto:BTC/USD"));
        assert!((e.positions["crypto:ETH/USD"].qty - eth_qty).abs() < 1e-12);
        assert_eq!(e.lab_done.get("lab:tsmom_regime"), Some(&now));
    }

    #[test]
    fn a_lab_rebalance_gives_up_after_six_attempts_and_says_so() {
        let mut e = lab_engine_with_stale_btc();
        let now = e.now();
        e.apply_lab_signal(lab_signal(now, &[("BTC", 0.10)], 0.86));
        for _ in 0..LAB_RETRY_MAX {
            e.run_lab_books();
            age_lab_retry(&mut e);
        }
        assert_eq!(e.lab_done.get("lab:tsmom_regime"), Some(&now));
        assert!(e.journal.iter().any(|j| j.message.contains("1 still refused after 6 attempts")));
        let n = e.orders.len();
        e.run_lab_books();
        assert_eq!(e.orders.len(), n, "done means done until the next signal");
    }

    #[test]
    fn adaptive_allocation_leaves_lab_books_at_their_tested_budget() {
        let mut e = Engine::new();
        let now = e.now();
        e.apply_lab_signal(lab_signal(now, &[("BTC", 0.10)], 0.86));
        let lab = e.strategies.iter().position(|s| s.id == "lab:tsmom_regime").unwrap();
        e.strategies[lab].budget_pct = 25.0;
        e.strategies[lab].equity_curve = vec![0.0, -5_000.0];
        e.rebalance_allocations();
        assert_eq!(e.strategies[lab].budget_pct, 25.0, "a losing week does not shrink a lab book");
        let others: f64 = e
            .strategies
            .iter()
            .filter(|s| s.state != StrategyState::Paused && s.id != "manual" && s.kind != StrategyKind::LabTargets)
            .map(|s| s.budget_pct)
            .sum();
        let floors = 3.0 * e.strategies.iter().filter(|s| s.state != StrategyState::Paused).count() as f64;
        assert!(others <= 55.0 + floors, "the lab book's share comes off the pool: {others}");
    }

    #[test]
    fn a_manual_click_never_reaches_a_real_venue() {
        let mut e = Engine::new();

        // Disarmed: practising by hand works as before.
        e.manual_order("alpaca:AAPL", Side::Buy, 1_000.0);
        assert!(e.drain_live_orders().is_empty());
        assert!(e.positions.contains_key("alpaca:AAPL"));
        e.flatten("alpaca:AAPL");

        // Armed: refused with a reason. No outbox entry, and no paper fill
        // either, which next to the real-money banner would read as a real order.
        e.set_live(armed_alpaca());
        let status = open_market(&e);
        e.set_broker_status(status);
        e.manual_order("alpaca:MSFT", Side::Buy, 1_000.0);
        assert!(e.drain_live_orders().is_empty());
        assert!(!e.positions.contains_key("alpaca:MSFT"));
        assert_eq!(e.orders[0].status, OrderStatus::Rejected);
        assert!(e.state().journal.iter().any(|j| j.message.contains("never go live")));

        // A venue that is not armed still practises.
        e.manual_order("crypto:BTC/USD", Side::Buy, 1_000.0);
        assert!(e.drain_live_orders().is_empty());
        assert!(e.positions.contains_key("crypto:BTC/USD"));
    }

    #[test]
    fn the_connection_test_is_the_one_order_that_goes_live_without_a_passport() {
        let mut e = Engine::new();
        assert!(e.connection_test_order("alpaca:AAPL", 10.0).is_err(), "disarmed: nothing to test");

        e.set_live(armed_alpaca());
        let status = open_market(&e);
        e.set_broker_status(status);
        e.connection_test_order("alpaca:AAPL", 10.0).unwrap();
        let out = e.drain_live_orders();
        assert_eq!(out.len(), 1);
        assert_eq!(out[0].venue, Venue::Alpaca);
        assert!(e.connection_test_order("alpaca:AAPL", 10.0).is_err(), "one in flight is enough");
    }

    #[test]
    fn closing_a_real_position_is_never_blocked() {
        let mut e = Engine::new();
        e.set_live(armed_alpaca());
        let status = open_market(&e);
        e.set_broker_status(status);
        e.live_order_for_test("alpaca:AAPL", Side::Buy, 1_000.0);
        let out = e.drain_live_orders();
        e.apply_live_ack(&out[0].order_id, "broker-1");
        e.apply_live_update(&out[0].order_id, update(BrokerOrderStatus::Filled, out[0].qty, 228.0));
        assert!(e.positions.get("alpaca:AAPL").map(|p| p.live).unwrap_or(false));

        e.flatten("alpaca:AAPL");
        let exit = e.drain_live_orders();
        assert_eq!(exit.len(), 1, "the exit must go to the broker");
        assert_eq!(exit[0].side, Side::Sell);
    }
}
