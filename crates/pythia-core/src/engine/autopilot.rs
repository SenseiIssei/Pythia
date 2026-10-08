//! The Autopilot: an amount of money that trades itself.
//!
//! The owner gives an autopilot an amount X (`capitalUsd`) and a set of
//! strategies (sleeves, each with a weight). It runs them continuously against
//! live data until the owner stops it or one of its stop rules fires. Its
//! equity is X plus the realised and unrealised P&L of the positions it owns,
//! minus the fees it paid. A sleeve's budget is its weight times the
//! autopilot's equity, never a share of the whole account.
//!
//! # Ownership and the one-position-per-market rule
//!
//! The engine holds one position per market. Two strategies that want the
//! same coin therefore conflict, and the autopilot resolves that up front
//! instead of at fill time:
//!
//! - **Strategies are exclusive.** A strategy belongs to at most one active
//!   autopilot. While it does, it trades only for that autopilot: its entries
//!   are sized from the autopilot's capital, routed by the autopilot's mode,
//!   and its state can only be changed by pausing or stopping the autopilot.
//!   It is not cloned, so the paper record it earns inside an autopilot is
//!   the same forward-test evidence its Strategy Passport is judged on.
//! - **Markets are exclusive.** At start every market is assigned to exactly
//!   one sleeve. Strategies that trade a whole set at once (Pairs, lab books)
//!   claim their full universe first, all or nothing; the other sleeves then
//!   deal the remaining markets out in turn, highest weight first. A market
//!   already assigned to another active autopilot is not available. While an
//!   autopilot is active its markets are reserved: strategies outside it do
//!   not open positions there.
//! - **Positions belong to whoever opened them.** A fill that opens a
//!   position for a sleeve strategy on one of its markets makes the position
//!   the autopilot's; every later fill on it (the strategy's exit, an ATR
//!   stop, a flatten from the Positions page) is booked to the autopilot, and
//!   so is a broker correction from reconciliation: the quantity follows the
//!   venue and the difference is realised at the mark, journaled, so the
//!   correction itself never moves its equity past a stop unseen. A
//!   position a sleeve strategy held from before the autopilot started stays
//!   outside it: its P&L is not counted, and the autopilot trades that market
//!   once it is closed. Lab books only trade by rebalancing, so a lab book
//!   that already holds coins cannot join an autopilot: it would never start
//!   flat.
//!
//! # Stop rules
//!
//! The *floor* is the highest of: the max-loss levels (`maxLossUsd`, and
//! `maxLossPct` of X), the trailing floor (`trailingPct` below the peak
//! equity) and a floor locked in by take-profit. Equity at or below the floor
//! stops the autopilot. Equity at or above the take-profit target either
//! finishes it (`onTakeProfit: "stop"`) or locks in half of the gain and moves
//! the target up one more step (`"lock"`): with a 10 % target the floor rises
//! to +5 % at +10 %, to +10 % at +20 %, and so on. `endMs` finishes it at a
//! time. No end time and no profit target is "endless". The peak, the locked
//! floor and the number of take-profit steps are saved with the engine, so a
//! restart can never reset a stop rule. A paused autopilot opens nothing new
//! but its stop rules still apply.
//!
//! On stop it closes its positions (`flattenOnStop`, default yes) and pauses
//! its strategies. Every transition is journaled in plain words with the
//! numbers, and pushed as an alert.
//!
//! # Modes and the money
//!
//! `paper` trades virtual money at prices from live books. `demo` sends its
//! orders to a venue's demo account through the real connector (the one hook
//! is [`AutopilotMode::route_intent`]). A crypto demo autopilot trades on the
//! exchange whose demo keys are saved, and that exchange is its venue. It is
//! refused on a demo whose prices are not documented as the real market
//! (OKX, see `docs/DEMO.md`): its fills would be measured in another price
//! world than the one its stop rules watch. `live` sends real orders and is gated
//! harder than anything else: live routing must be armed for the venue, every
//! sleeve strategy needs a green Strategy Passport, X may not exceed the cash
//! the venue reports as free (minus what other live autopilots there already
//! committed), the owner must confirm, and a max-loss rule is required.
//!
//! **Nothing here can move money.** The money source is an exchange or
//! broker account the owner funded. The autopilot places orders through the
//! same path as every strategy; there is no withdrawal, transfer or deposit
//! function anywhere in Pythia, and a wallet such as Exodus stays a watched
//! treasury that Pythia can read and never move (see `SAFETY.md`).

use super::{Engine, JournalKind, RouteIntent, StrategyKind, StrategyState};
use crate::connectors::Venue;
use crate::costs::CostVenue;
use crate::validation::GateStatus;
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, HashSet};

/// Equity within a billionth of a dollar of a threshold counts as reaching it.
const EPS: f64 = 1e-9;
/// One equity point per minute in the history, at most `HISTORY_MAX` of them.
const HISTORY_EVERY_MS: i64 = 60_000;
const HISTORY_MAX: usize = 300;
/// "Auto" picks at most this many strategies.
const AUTO_MAX_SLEEVES: usize = 3;
/// Stopped autopilots kept for the record, newest first.
const KEEP_FINISHED: usize = 10;
/// A live order still working when its autopilot stopped can fill until the
/// order timeout cancels it, plus a poll or two. Its fill is still the
/// autopilot's (and closed again when it flattened).
const LATE_FILL_GRACE_MS: i64 = 120_000;
/// An entry worth less than this is not worth its fee.
pub(super) const MIN_ENTRY_USD: f64 = 1.0;

// ── the wire contract ──────────────────────────────────────────────────────

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
pub enum AutopilotMode {
    Paper,
    Demo,
    Live,
}

impl AutopilotMode {
    /// How this mode's orders are routed.
    ///
    /// Every autopilot order takes its route from this function. Demo goes to
    /// the venue's demo account through the real connector (see SAFETY.md
    /// §3d and docs/DEMO.md); the start refuses demo without demo keys.
    pub fn route_intent(self) -> RouteIntent {
        match self {
            AutopilotMode::Paper => RouteIntent::Paper,
            AutopilotMode::Demo => RouteIntent::Demo,
            AutopilotMode::Live => RouteIntent::Live,
        }
    }

    fn word(self) -> &'static str {
        match self {
            AutopilotMode::Paper => "paper",
            AutopilotMode::Demo => "demo",
            AutopilotMode::Live => "LIVE",
        }
    }
}

#[derive(Debug, Clone, Copy, Default, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
pub enum OnTakeProfit {
    /// Reaching the target finishes the autopilot.
    #[default]
    Stop,
    /// Reaching the target locks in half of the gain and moves the target up.
    Lock,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct SleeveConfig {
    pub strategy_id: String,
    pub weight: f64,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct StopRules {
    /// Stop once the loss reaches this % of X.
    #[serde(default)]
    pub max_loss_pct: Option<f64>,
    /// Stop once the loss reaches this many dollars.
    #[serde(default)]
    pub max_loss_usd: Option<f64>,
    /// Profit target in % of X.
    #[serde(default)]
    pub take_profit_pct: Option<f64>,
    #[serde(default)]
    pub on_take_profit: OnTakeProfit,
    /// Give back at most this % from the peak equity.
    #[serde(default)]
    pub trailing_pct: Option<f64>,
    /// Finish at this time (epoch ms).
    #[serde(default)]
    pub end_ms: Option<i64>,
}

fn yes() -> bool {
    true
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct AutopilotConfig {
    /// Empty: the engine assigns one.
    #[serde(default)]
    pub id: String,
    #[serde(default)]
    pub name: String,
    pub mode: AutopilotMode,
    /// A cost venue id from `config/costs.json` ("kraken", "alpaca", ...).
    pub venue: String,
    pub capital_usd: f64,
    /// Empty: "auto" picks the strategies.
    #[serde(default)]
    pub sleeves: Vec<SleeveConfig>,
    #[serde(default)]
    pub stop: StopRules,
    #[serde(default = "yes")]
    pub flatten_on_stop: bool,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
pub enum AutopilotState {
    Running,
    /// Opens nothing new; open positions and stop rules still apply.
    Paused,
    /// Stopped by the owner or by a loss rule.
    Stopped,
    /// Ended by its own plan: the end time, or a take-profit that stops.
    Finished,
}

/// One sleeve as the UI shows it.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SleeveStatus {
    pub strategy_id: String,
    pub name: String,
    /// Share of the autopilot's equity, 0..1. The weights add up to 1.
    pub weight: f64,
    /// Realised and unrealised P&L of this sleeve's positions, net of fees.
    pub pnl: f64,
    /// Closed trades.
    pub trades: u32,
    /// Why this strategy is in the autopilot, in one sentence.
    pub why: String,
    /// The markets assigned to this sleeve. No other sleeve trades them.
    pub markets: Vec<String>,
}

/// An autopilot as the UI shows it. Pushed in `EngineState::autopilots`.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct AutopilotStatus {
    pub config: AutopilotConfig,
    pub state: AutopilotState,
    pub stop_reason: Option<String>,
    /// Why it is paused, when it is.
    pub paused_reason: Option<String>,
    pub started_ms: i64,
    pub stopped_ms: Option<i64>,
    pub start_capital: f64,
    pub equity: f64,
    pub pnl: f64,
    pub pnl_pct: f64,
    pub peak_equity: f64,
    /// Below the peak, in %.
    pub drawdown_pct: f64,
    /// The equity at which it stops. `None` without a loss or trailing rule.
    pub floor_equity: Option<f64>,
    /// The next take-profit level, when there is one.
    pub target_equity: Option<f64>,
    /// Closed trades.
    pub trades: u32,
    pub fees: f64,
    /// Positions it owns right now.
    pub open_positions: usize,
    pub by_sleeve: Vec<SleeveStatus>,
    pub last_action: Option<String>,
    /// `[epoch ms, equity]`, one point a minute, thinned to at most 300.
    pub history: Vec<(i64, f64)>,
}

/// What the host read from the venue before a live start. The engine does no
/// I/O, so the host fetches the free cash and hands it in.
#[derive(Debug, Clone, PartialEq)]
pub enum VenueCash {
    /// Not read (paper and demo do not need it).
    NotRead,
    /// Free quote cash at the venue, in USD.
    Read(f64),
    /// The venue could not be read; the reason, for the refusal.
    Failed(String),
}

// ── the saved record ───────────────────────────────────────────────────────

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Sleeve {
    pub strategy_id: String,
    pub name: String,
    pub weight: f64,
    pub markets: Vec<String>,
    pub why: String,
    #[serde(default)]
    pub realized: f64,
    #[serde(default)]
    pub fees: f64,
    #[serde(default)]
    pub trades: u32,
    /// The strategy's state before the autopilot took it, for the journal.
    pub prior_state: StrategyState,
}

/// One autopilot, exactly as it is saved with the engine state.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Autopilot {
    pub config: AutopilotConfig,
    pub state: AutopilotState,
    #[serde(default)]
    pub stop_reason: Option<String>,
    #[serde(default)]
    pub paused_reason: Option<String>,
    pub started_ms: i64,
    #[serde(default)]
    pub stopped_ms: Option<i64>,
    pub start_capital: f64,
    pub peak_equity: f64,
    /// Floor locked in by take-profit.
    #[serde(default)]
    pub locked_floor: Option<f64>,
    /// Take-profit targets reached so far (lock mode).
    #[serde(default)]
    pub tp_steps: u32,
    #[serde(default)]
    pub realized: f64,
    #[serde(default)]
    pub fees: f64,
    #[serde(default)]
    pub trades: u32,
    /// Unrealised P&L of positions left open when it stopped without
    /// flattening, at their price then. They are no longer its own.
    #[serde(default)]
    pub released: f64,
    /// It stopped with flattening: a late fill is closed again.
    #[serde(default)]
    pub flatten_at_stop: bool,
    pub sleeves: Vec<Sleeve>,
    /// Market id to the strategy whose sleeve holds it.
    #[serde(default)]
    pub owned: BTreeMap<String, String>,
    #[serde(default)]
    pub last_action: Option<String>,
    #[serde(default)]
    pub history: Vec<(i64, f64)>,
}

impl Autopilot {
    pub fn is_active(&self) -> bool {
        matches!(self.state, AutopilotState::Running | AutopilotState::Paused)
    }

    fn sleeve(&self, sid: &str) -> Option<&Sleeve> {
        self.sleeves.iter().find(|s| s.strategy_id == sid)
    }

    fn sleeve_mut(&mut self, sid: &str) -> Option<&mut Sleeve> {
        self.sleeves.iter_mut().find(|s| s.strategy_id == sid)
    }

    fn has_market(&self, market: &str) -> bool {
        self.sleeves.iter().any(|s| s.markets.iter().any(|m| m == market))
    }

    fn label(&self) -> String {
        format!("Autopilot \"{}\"", self.config.name)
    }
}

// ── pure rules (tested directly) ───────────────────────────────────────────

/// The rule that sets the floor.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum FloorRule {
    MaxLossPct,
    MaxLossUsd,
    Trailing,
    LockedProfit,
}

/// The equity at which the autopilot stops, and which rule sets it: the
/// highest of the levels its rules imply. `None` when it has none.
pub fn floor_equity(stop: &StopRules, start: f64, peak: f64, locked: Option<f64>) -> Option<(f64, FloorRule)> {
    let mut levels: Vec<(f64, FloorRule)> = Vec::new();
    if let Some(pct) = stop.max_loss_pct {
        levels.push((start * (1.0 - pct / 100.0), FloorRule::MaxLossPct));
    }
    if let Some(usd) = stop.max_loss_usd {
        levels.push((start - usd, FloorRule::MaxLossUsd));
    }
    if let Some(pct) = stop.trailing_pct {
        levels.push((peak * (1.0 - pct / 100.0), FloorRule::Trailing));
    }
    if let Some(f) = locked {
        levels.push((f, FloorRule::LockedProfit));
    }
    levels.into_iter().fold(None, |best: Option<(f64, FloorRule)>, l| match best {
        Some(b) if b.0 >= l.0 => Some(b),
        _ => Some(l),
    })
}

/// The next take-profit level after `steps` targets were reached.
pub fn take_profit_target(stop: &StopRules, start: f64, steps: u32) -> Option<f64> {
    stop.take_profit_pct.map(|tp| start * (1.0 + (steps + 1) as f64 * tp / 100.0))
}

/// The floor locked in after `steps` targets: half of the gain at the last one.
pub fn locked_floor(start: f64, tp_pct: f64, steps: u32) -> f64 {
    start * (1.0 + steps as f64 * tp_pct / 200.0)
}

/// Check a config before anything happens. Plain sentences.
pub fn validate(cfg: &AutopilotConfig, now: i64) -> Result<(), String> {
    let x = cfg.capital_usd;
    if !x.is_finite() || x <= 0.0 {
        return Err("Give the autopilot an amount above zero.".into());
    }
    let s = &cfg.stop;
    if let Some(p) = s.max_loss_pct {
        if !p.is_finite() || p <= 0.0 || p > 100.0 {
            return Err(format!("The max loss in % has to be above 0 and at most 100, not {p}."));
        }
    }
    if let Some(u) = s.max_loss_usd {
        if !u.is_finite() || u <= 0.0 || u > x {
            return Err(format!("The max loss in dollars has to be above 0 and at most the amount ({}), not {}.", usd(x), usd(u)));
        }
    }
    if let Some(p) = s.take_profit_pct {
        if !p.is_finite() || p <= 0.0 || p > 10_000.0 {
            return Err(format!("The profit target has to be above 0 %, not {p} %."));
        }
    }
    if let Some(p) = s.trailing_pct {
        if !p.is_finite() || p <= 0.0 || p >= 100.0 {
            return Err(format!("The trailing floor has to be above 0 % and below 100 %, not {p} %."));
        }
    }
    if let Some(end) = s.end_ms {
        if end <= now {
            return Err("The end time is already in the past.".into());
        }
    }
    let mut seen = HashSet::new();
    for sl in &cfg.sleeves {
        if !sl.weight.is_finite() || sl.weight <= 0.0 {
            return Err(format!("The weight of {} has to be above zero.", sl.strategy_id));
        }
        if !seen.insert(sl.strategy_id.as_str()) {
            return Err(format!("{} is listed twice.", sl.strategy_id));
        }
    }
    Ok(())
}

/// What one sleeve asks for when markets are assigned.
#[derive(Debug, Clone)]
pub struct Want {
    pub weight: f64,
    /// Trades its universe as one set (Pairs, lab books): all or nothing.
    pub whole: bool,
    pub universe: Vec<String>,
}

/// Give every market to exactly one sleeve. Whole-set sleeves claim their full
/// universe first, highest weight first, and get nothing if any of it is
/// taken. The other sleeves then deal the remaining markets out in turn,
/// highest weight first, each taking its next free market. `taken` are
/// markets that belong to another active autopilot. Returns the markets per
/// sleeve, in the input order.
pub fn assign_markets(wants: &[Want], taken: &HashSet<String>) -> Vec<Vec<String>> {
    let mut order: Vec<usize> = (0..wants.len()).collect();
    // Stable: equal weights keep the order they were given in.
    order.sort_by(|&a, &b| wants[b].weight.partial_cmp(&wants[a].weight).unwrap_or(std::cmp::Ordering::Equal));
    let mut claimed: HashSet<String> = taken.clone();
    let mut out: Vec<Vec<String>> = vec![Vec::new(); wants.len()];
    for &i in order.iter().filter(|&&i| wants[i].whole) {
        let w = &wants[i];
        if !w.universe.is_empty() && w.universe.iter().all(|m| !claimed.contains(m)) {
            for m in &w.universe {
                claimed.insert(m.clone());
            }
            out[i] = w.universe.clone();
        }
    }
    let dealers: Vec<usize> = order.iter().copied().filter(|&i| !wants[i].whole).collect();
    let mut cursor: Vec<usize> = vec![0; wants.len()];
    loop {
        let mut dealt = false;
        for &i in &dealers {
            let u = &wants[i].universe;
            while cursor[i] < u.len() && claimed.contains(&u[cursor[i]]) {
                cursor[i] += 1;
            }
            if cursor[i] < u.len() {
                let m = u[cursor[i]].clone();
                claimed.insert(m.clone());
                out[i].push(m);
                cursor[i] += 1;
                dealt = true;
            }
        }
        if !dealt {
            break;
        }
    }
    out
}

/// The evidence behind one strategy, for the auto pick.
#[derive(Debug, Clone, Default)]
pub struct Evidence {
    /// Passport gates passed and failed, out of eight.
    pub passed: usize,
    pub failed: usize,
    pub live_ready: bool,
    /// Sized on its own measured edge (30+ closed trades).
    pub measured: bool,
    /// Its record says it has no edge: it would be sized to zero.
    pub no_edge: bool,
    pub kelly: f64,
    pub forward_trades: u32,
    /// Net P&L of its closed trades, fees included.
    pub net: f64,
    /// Lab books: out-of-sample Sharpe and deflated-Sharpe probability.
    pub lab_oos_sharpe: Option<f64>,
    pub lab_deflated_p: Option<f64>,
}

impl Evidence {
    /// A score for weighting, or `None` when the evidence rules it out.
    pub fn score(&self) -> Option<f64> {
        if self.no_edge {
            return None;
        }
        let mut s = 1.0 + self.passed as f64;
        if self.live_ready {
            s += 4.0;
        }
        if self.measured {
            s += 2.0 + 20.0 * self.kelly.clamp(0.0, 0.25);
        }
        if self.forward_trades >= 10 && self.net > 0.0 {
            s += 1.0;
        }
        if let Some(sh) = self.lab_oos_sharpe.filter(|v| *v > 0.0) {
            s += sh.min(2.0);
        }
        if self.lab_deflated_p.is_some_and(|p| p >= 0.95) {
            s += 1.0;
        }
        Some(s / (1.0 + self.failed as f64))
    }

    /// The evidence in a few words.
    pub fn describe(&self) -> String {
        let mut parts = vec![format!("{} of 8 gates green", self.passed)];
        if self.failed > 0 {
            parts.push(format!("{} failed", self.failed));
        }
        if self.live_ready {
            parts.push("cleared for live".into());
        }
        if self.measured {
            parts.push(format!("a measured edge (Kelly {:.3})", self.kelly));
        } else if self.forward_trades > 0 {
            parts.push(format!("{} forward trades netting {}", self.forward_trades, signed_usd(self.net)));
        } else {
            parts.push("no forward record yet".into());
        }
        if let Some(sh) = self.lab_oos_sharpe {
            let p = self.lab_deflated_p.map(|p| format!(", deflated p {p:.2}")).unwrap_or_default();
            parts.push(format!("lab out-of-sample Sharpe {sh:.2}{p}"));
        }
        parts.join(", ")
    }
}

fn usd(x: f64) -> String {
    let neg = x < 0.0;
    let cents = (x.abs() * 100.0).round() as u128;
    let (whole, frac) = (cents / 100, cents % 100);
    let digits = whole.to_string();
    let mut grouped = String::new();
    for (k, c) in digits.chars().enumerate() {
        if k > 0 && (digits.len() - k) % 3 == 0 {
            grouped.push(',');
        }
        grouped.push(c);
    }
    format!("{}${grouped}.{frac:02}", if neg { "-" } else { "" })
}

fn signed_usd(x: f64) -> String {
    if x >= 0.0 { format!("+{}", usd(x)) } else { usd(x) }
}

fn pct(x: f64) -> String {
    let t = format!("{x:.2}");
    let t = t.trim_end_matches('0').trim_end_matches('.');
    t.to_string()
}

/// The engine venue a cost venue trades on.
fn engine_venue(cv: CostVenue) -> Venue {
    match cv {
        CostVenue::Alpaca => Venue::Alpaca,
        CostVenue::Polymarket => Venue::Polymarket,
        _ => Venue::Crypto,
    }
}

pub(super) fn venue_label(cv: CostVenue) -> &'static str {
    match cv {
        CostVenue::Kraken => "Kraken",
        CostVenue::Binance => "Binance",
        CostVenue::Bybit => "Bybit",
        CostVenue::Okx => "OKX",
        CostVenue::Coinbase => "Coinbase",
        CostVenue::Alpaca => "Alpaca",
        CostVenue::Polymarket => "Polymarket",
    }
}

/// Strategies that trade their universe as one set.
fn trades_as_set(kind: StrategyKind) -> bool {
    matches!(kind, StrategyKind::Pairs | StrategyKind::LabTargets)
}

/// Strategies the engine has a runtime for.
fn runnable(kind: StrategyKind) -> bool {
    !matches!(kind, StrategyKind::Manual | StrategyKind::Arb)
}

/// The stop rules in plain words.
fn describe_rules(cfg: &AutopilotConfig) -> String {
    let x = cfg.capital_usd;
    let s = &cfg.stop;
    let mut parts: Vec<String> = Vec::new();
    if let Some(p) = s.max_loss_pct {
        parts.push(format!("stops at a loss of {} % (equity {})", pct(p), usd(x * (1.0 - p / 100.0))));
    }
    if let Some(u) = s.max_loss_usd {
        parts.push(format!("stops at a loss of {} (equity {})", usd(u), usd(x - u)));
    }
    if let Some(p) = s.trailing_pct {
        parts.push(format!("gives back at most {} % from its peak", pct(p)));
    }
    if let Some(p) = s.take_profit_pct {
        parts.push(match s.on_take_profit {
            OnTakeProfit::Stop => format!("finishes at a profit of {} % (equity {})", pct(p), usd(x * (1.0 + p / 100.0))),
            OnTakeProfit::Lock => format!(
                "locks in half the gain at every {} % of profit (first at equity {}) and keeps going",
                pct(p),
                usd(x * (1.0 + p / 100.0))
            ),
        });
    }
    match s.end_ms.and_then(chrono::DateTime::from_timestamp_millis) {
        Some(t) => parts.push(format!("ends {}", t.format("%Y-%m-%d %H:%M UTC"))),
        None if s.take_profit_pct.is_none() || s.on_take_profit == OnTakeProfit::Lock => {
            parts.push("otherwise runs until you stop it".into())
        }
        None => {}
    }
    parts.join("; ")
}

// ── the engine side ────────────────────────────────────────────────────────

/// How an autopilot sleeve sizes one entry.
pub(super) struct SleeveSizing {
    /// The sleeve's budget: its weight times the autopilot's equity.
    pub capital: f64,
    /// Markets the budget is spread over.
    pub slots: f64,
    /// The autopilot's equity.
    pub equity: f64,
    /// Notional it may still add: within the sleeve's budget and, for the
    /// autopilot as a whole, never more exposure than its equity.
    pub room: f64,
}

/// What a lab book inside an autopilot may do.
pub(super) struct LabScope {
    pub running: bool,
    pub capital: f64,
    /// Markets the autopilot owns for this book.
    pub owned: HashSet<String>,
}

impl Engine {
    fn ap_index(&self, id: &str) -> Option<usize> {
        self.autopilots.iter().position(|a| a.config.id == id)
    }

    /// The active autopilot that runs this strategy.
    fn ap_of_strategy(&self, sid: &str) -> Option<usize> {
        self.autopilots.iter().position(|a| a.is_active() && a.sleeve(sid).is_some())
    }

    fn ap_mark(&self, market: &str, avg: f64) -> f64 {
        let px = self.price_of(market);
        if px > 0.0 { px } else { avg }
    }

    fn ap_unrealized(&self, ap: &Autopilot, sleeve: Option<&str>) -> f64 {
        ap.owned
            .iter()
            .filter(|(_, sid)| sleeve.is_none_or(|s| s == sid.as_str()))
            .filter_map(|(m, _)| {
                let p = self.positions.get(m)?;
                Some((self.ap_mark(m, p.avg_price) - p.avg_price) * p.qty)
            })
            .sum()
    }

    fn ap_gross(&self, ap: &Autopilot, sleeve: Option<&str>) -> f64 {
        ap.owned
            .iter()
            .filter(|(_, sid)| sleeve.is_none_or(|s| s == sid.as_str()))
            .filter_map(|(m, _)| {
                let p = self.positions.get(m)?;
                Some((p.qty * self.ap_mark(m, p.avg_price)).abs())
            })
            .sum()
    }

    /// Notional of entries sent to a venue (demo or live) on the autopilot's
    /// markets that have not filled yet. They become positions when the venue
    /// says so; until then they still use up room, or every signal in the
    /// meantime would be sized from the same budget again.
    fn ap_pending(&self, ap: &Autopilot, sleeve: Option<&str>) -> f64 {
        self.inflight
            .values()
            .filter(|f| sleeve.is_none_or(|s| s == f.strategy_id))
            .filter(|f| ap.sleeves.iter().any(|s| s.strategy_id == f.strategy_id && s.markets.contains(&f.market_id)))
            .filter(|f| {
                // An entry, or the rest of one: not an exit of what is held.
                let buy = f.side == crate::connectors::Side::Buy;
                self.positions.get(&f.market_id).is_none_or(|p| p.qty.abs() < 1e-12 || (p.qty > 0.0) == buy)
            })
            .map(|f| {
                let left = (f.qty - f.booked_qty).max(0.0);
                let px = self.price_of(&f.market_id);
                left * if px > 0.0 { px } else { f.arrival }
            })
            .sum()
    }

    fn ap_equity(&self, ap: &Autopilot) -> f64 {
        ap.start_capital + ap.realized - ap.fees + ap.released + self.ap_unrealized(ap, None)
    }

    /// The name of the autopilot that runs this strategy, if one does.
    pub(super) fn autopilot_claimant(&self, sid: &str) -> Option<String> {
        self.ap_of_strategy(sid).map(|i| self.autopilots[i].config.name.clone())
    }

    /// May this strategy open a position in this market now? A strategy in an
    /// autopilot only on its own sleeve's markets and only while the
    /// autopilot runs; every other strategy only outside the markets an
    /// active autopilot reserved.
    pub(super) fn autopilot_entry_allowed(&self, sid: &str, market: &str) -> bool {
        if let Some(i) = self.ap_of_strategy(sid) {
            let ap = &self.autopilots[i];
            let live_ok = ap.config.mode != AutopilotMode::Live
                || CostVenue::parse(&ap.config.venue).is_some_and(|cv| self.live_routable(engine_venue(cv)));
            return ap.state == AutopilotState::Running
                && live_ok
                && ap.sleeve(sid).is_some_and(|s| s.markets.iter().any(|m| m == market));
        }
        !self.autopilots.iter().any(|a| a.is_active() && a.has_market(market))
    }

    /// Sizing for an entry by a strategy that runs in an autopilot.
    pub(super) fn autopilot_sizing(&self, sid: &str) -> Option<SleeveSizing> {
        let ap = &self.autopilots[self.ap_of_strategy(sid)?];
        let s = ap.sleeve(sid)?;
        let equity = self.ap_equity(ap).max(0.0);
        let capital = equity * s.weight;
        let used = self.ap_gross(ap, Some(sid)) + self.ap_pending(ap, Some(sid));
        let used_all = self.ap_gross(ap, None) + self.ap_pending(ap, None);
        let room = (capital - used).min(equity - used_all).max(0.0);
        Some(SleeveSizing { capital, slots: s.markets.len().max(1) as f64, equity, room })
    }

    /// The route for an order by a strategy that runs in an autopilot: the
    /// autopilot's mode decides, never the strategy's own switch.
    pub(super) fn autopilot_route(&self, sid: &str) -> Option<RouteIntent> {
        self.ap_of_strategy(sid).map(|i| self.autopilots[i].config.mode.route_intent())
    }

    pub(super) fn autopilot_lab_scope(&self, sid: &str) -> Option<LabScope> {
        let ap = &self.autopilots[self.ap_of_strategy(sid)?];
        let s = ap.sleeve(sid)?;
        Some(LabScope {
            running: ap.state == AutopilotState::Running,
            capital: self.ap_equity(ap).max(0.0) * s.weight,
            owned: ap.owned.iter().filter(|(_, o)| o.as_str() == sid).map(|(m, _)| m.clone()).collect(),
        })
    }

    /// Book a fill to the autopilot that owns the position, or that opened it.
    /// Called by `settle_fill` for every fill, paper or live. `existed` is
    /// whether the market had a position before this fill.
    pub(super) fn autopilot_on_fill(&mut self, sid: &str, market: &str, realized: f64, fee: f64, existed: bool, open_after: bool) {
        let now = self.now();
        let late = (self.live.timeout_sec as i64) * 1000 + LATE_FILL_GRACE_MS;
        let opens = |a: &Autopilot| a.sleeve(sid).is_some_and(|s| s.markets.iter().any(|m| m == market));
        let i = match self.autopilots.iter().position(|a| a.owned.contains_key(market)) {
            Some(i) => i,
            None if !existed => {
                let active = self.autopilots.iter().position(|a| a.is_active() && opens(a));
                let recent = || {
                    self.autopilots
                        .iter()
                        .position(|a| !a.is_active() && a.stopped_ms.is_some_and(|t| now - t <= late) && opens(a))
                };
                match active.or_else(recent) {
                    Some(i) => i,
                    None => return,
                }
            }
            None => return,
        };
        let ap = &mut self.autopilots[i];
        let owner = ap.owned.get(market).cloned().unwrap_or_else(|| sid.to_string());
        let fee = fee.max(0.0);
        ap.realized += realized;
        ap.fees += fee;
        let closed = realized != 0.0;
        if closed {
            ap.trades += 1;
        }
        if let Some(s) = ap.sleeve_mut(&owner) {
            s.realized += realized;
            s.fees += fee;
            if closed {
                s.trades += 1;
            }
        }
        if open_after {
            ap.owned.insert(market.to_string(), owner);
        } else {
            ap.owned.remove(market);
        }
    }

    /// Reconciliation set a position to what the venue holds. When an
    /// autopilot owns it, the difference is booked to that autopilot: the
    /// quantity follows the venue, and the P&L the changed part carried is
    /// booked as realised at the mark (and so is a change of the average
    /// price the venue reported). The autopilot's equity is the same just
    /// before and just after, so a correction can never lift it over a stop,
    /// or drop a loss its stop rules were about to see. Journaled with the
    /// numbers. `before` and `after` are (quantity, average price).
    pub(super) fn autopilot_on_correction(&mut self, market: &str, before: (f64, f64), after: (f64, f64), venue: &str) {
        let Some(i) = self.autopilots.iter().position(|a| a.owned.contains_key(market)) else { return };
        let mark = self.ap_mark(market, before.1);
        let open_after = after.0.abs() > 1e-12;
        let unreal = |(q, avg): (f64, f64)| if q.abs() > 1e-12 { (mark - avg) * q } else { 0.0 };
        let booked = unreal(before) - unreal(after);
        let symbol = self.markets.iter().find(|m| m.id == market).map(|m| m.symbol.clone()).unwrap_or_else(|| market.to_string());
        let ap = &mut self.autopilots[i];
        let owner = ap.owned.get(market).cloned().unwrap_or_default();
        ap.realized += booked;
        if let Some(s) = ap.sleeve_mut(&owner) {
            s.realized += booked;
        }
        if !open_after {
            ap.owned.remove(market);
        }
        let msg = format!(
            "{}: {symbol} corrected against {venue}: the book had {:.8}, the venue has {:.8}. Booked {} to the autopilot at the mark {} so the correction moves none of its equity and hides no stop.",
            ap.label(),
            before.0,
            after.0,
            signed_usd(booked),
            usd(mark)
        );
        ap.last_action = Some(msg.clone());
        self.log(JournalKind::Risk, msg, Some(owner), Some(market.to_string()));
    }

    // ── commands ───────────────────────────────────────────────────────────

    /// Start an autopilot. `confirm` is the owner's typed confirmation (the UI
    /// asks for it); live refuses without it. `cash` is what the host read
    /// from the venue for a live start. Returns the autopilot's id, or why it
    /// was refused in a plain sentence.
    pub fn autopilot_start(&mut self, mut cfg: AutopilotConfig, confirm: bool, cash: VenueCash) -> Result<String, String> {
        let now = self.now();
        validate(&cfg, now)?;
        cfg.name = cfg.name.trim().to_string();
        if cfg.name.is_empty() {
            cfg.name = "Autopilot".into();
        }
        cfg.id = cfg.id.trim().to_string();
        if cfg.id.is_empty() {
            cfg.id = self.next_id("ap");
        }
        if let Some(i) = self.ap_index(&cfg.id) {
            let old = &self.autopilots[i];
            if old.is_active() {
                return Err(format!("{} is already running. Stop it first, or give the new one another id.", old.label()));
            }
            if !old.owned.is_empty() {
                return Err(format!("{} is still closing its positions. Start the new one once they are closed.", old.label()));
            }
            // A stopped one under the same id is replaced once this one starts.
        }

        let Some(mut cv) = CostVenue::parse(&cfg.venue) else {
            return Err(format!("Unknown venue \"{}\". Use one from config/costs.json, for example kraken or alpaca.", cfg.venue));
        };
        let venue = engine_venue(cv);
        if cfg.mode == AutopilotMode::Demo && venue == Venue::Crypto {
            // Crypto demo orders go to the exchange whose demo keys are in
            // Settings, whatever the live exchange is. That exchange is the
            // autopilot's venue, so every label names where it trades.
            if !self.demo_venues.contains(&venue) {
                return Err(format!(
                    "A demo autopilot needs demo keys for {}: add Bybit, OKX or Binance demo keys in Settings first (docs/DEMO.md says how to get them).",
                    venue_label(cv)
                ));
            }
            let demo_cv = self.crypto_demo_venue.unwrap_or(self.crypto_venue);
            if cv != demo_cv && cv != self.crypto_venue {
                return Err(format!(
                    "Crypto demo orders go to {}, the exchange whose demo keys are in Settings. A demo autopilot on {} would trade there anyway: pick {} or save demo keys for {} first.",
                    venue_label(demo_cv),
                    venue_label(cv),
                    demo_cv.id(),
                    venue_label(cv)
                ));
            }
            if !self.crypto_demo_real_prices {
                return Err(format!(
                    "{} runs its demo account on its own prices, which it does not document as the real market. A demo autopilot there would have its fills measured in a different price world than the one its stop rules watch, so its results would mean nothing. Use Bybit or Binance demo keys (their demos trade on real prices), or run it on paper. A single strategy can still demo-trade on {} as an API test.",
                    venue_label(demo_cv),
                    venue_label(demo_cv)
                ));
            }
            cv = demo_cv;
            cfg.venue = demo_cv.id().to_string();
        } else if venue == Venue::Crypto && cv != self.crypto_venue {
            return Err(format!(
                "Crypto here executes on {}, the exchange selected in Settings. An autopilot on {} would be priced and routed there anyway: pick {} or switch the exchange first.",
                venue_label(self.crypto_venue),
                venue_label(cv),
                self.crypto_venue.id()
            ));
        }
        if venue == Venue::Polymarket && cfg.mode != AutopilotMode::Paper {
            return Err("Polymarket has no order path in Pythia: an autopilot there can only run on paper.".into());
        }
        if cfg.mode == AutopilotMode::Demo && !self.demo_venues.contains(&venue) {
            return Err(format!(
                "A demo autopilot needs demo keys for {}: add {} in Settings first (docs/DEMO.md says how to get them).",
                venue_label(cv),
                if venue == Venue::Alpaca { "Alpaca paper keys" } else { "Bybit, OKX or Binance demo keys" }
            ));
        }
        if self.limits.kill_switch {
            return Err("The kill switch is on, so every new entry would be refused. Release it first.".into());
        }

        // Strategies and markets already taken by another active autopilot.
        let busy: HashSet<String> =
            self.autopilots.iter().filter(|a| a.is_active()).flat_map(|a| a.sleeves.iter().map(|s| s.strategy_id.clone())).collect();
        let taken: HashSet<String> = self
            .autopilots
            .iter()
            .filter(|a| a.is_active())
            .flat_map(|a| a.sleeves.iter().flat_map(|s| s.markets.iter().cloned()))
            .collect();

        let auto = cfg.sleeves.is_empty();
        let picks: Vec<(String, f64, String)> = if auto {
            self.auto_pick(venue, cfg.mode, &busy)?
        } else {
            let mut out = Vec::new();
            for sl in &cfg.sleeves {
                let Some(s) = self.strategies.iter().find(|s| s.id == sl.strategy_id) else {
                    return Err(format!("There is no strategy \"{}\".", sl.strategy_id));
                };
                if let Some(why) = self.sleeve_block(s.id.as_str(), venue, cfg.mode, &busy) {
                    return Err(why);
                }
                let ev = self.evidence(&s.id);
                out.push((s.id.clone(), sl.weight, format!("Chosen by you; {}", ev.describe())));
            }
            out
        };

        // Markets, exclusively.
        let wants: Vec<Want> = picks
            .iter()
            .map(|(sid, w, _)| {
                let s = self.strategies.iter().find(|s| &s.id == sid).expect("picked strategies exist");
                let universe = if s.kind == StrategyKind::LabTargets {
                    self.markets.iter().filter(|m| m.venue == Venue::Crypto).map(|m| m.id.clone()).collect()
                } else {
                    s.universe.iter().filter(|id| self.markets.iter().any(|m| &m.id == *id)).cloned().collect()
                };
                Want { weight: *w, whole: trades_as_set(s.kind), universe }
            })
            .collect();
        let assigned = assign_markets(&wants, &taken);
        let mut chosen: Vec<(String, f64, String, Vec<String>)> = Vec::new();
        for ((sid, w, why), markets) in picks.into_iter().zip(assigned) {
            if markets.is_empty() {
                if auto {
                    continue;
                }
                let name = self.strategies.iter().find(|s| s.id == sid).map(|s| s.name.clone()).unwrap_or(sid);
                return Err(format!(
                    "{name} has no market of its own left: every market it trades already belongs to another sleeve or another autopilot. One position per market means two strategies cannot hold the same coin; drop one of them or pick strategies on different markets."
                ));
            }
            chosen.push((sid, w, why, markets));
        }
        if chosen.is_empty() {
            return Err("Auto found no strategy with a market of its own left: the others already belong to running autopilots.".into());
        }
        let total: f64 = chosen.iter().map(|c| c.1).sum();

        // Live: the hardest gate in the app.
        if cfg.mode == AutopilotMode::Live {
            if !confirm {
                return Err("Live trades real money: type the confirmation to start it.".into());
            }
            if !self.live.armed {
                return Err("Live routing is not armed. Arm it on the Live page first; the autopilot never arms anything itself.".into());
            }
            if !self.live.venues.contains(&venue) {
                return Err(format!("{} is not enabled for live routing. Enable it on the Live page first.", venue_label(cv)));
            }
            for (sid, ..) in &chosen {
                let s = self.strategies.iter().find(|s| &s.id == sid).expect("chosen strategies exist");
                let pp = self.passport_for(s);
                if !pp.live_ready {
                    let why = pp.blocked_reason.unwrap_or_else(|| "its validation gates are not green".into());
                    return Err(format!("{} is not cleared for live: {why}", s.name));
                }
            }
            if cfg.stop.max_loss_pct.is_none() && cfg.stop.max_loss_usd.is_none() {
                return Err("Live needs a max-loss rule, in % or in dollars, so there is always a level at which it stops.".into());
            }
            let free = match cash {
                VenueCash::Read(c) => c,
                VenueCash::Failed(why) => {
                    return Err(format!(
                        "Could not read the free cash at {} ({why}), so live is refused: the amount has to fit in what the account holds.",
                        venue_label(cv)
                    ))
                }
                VenueCash::NotRead => {
                    return Err(format!("The free cash at {} was not read, so live is refused.", venue_label(cv)))
                }
            };
            let committed: f64 = self
                .autopilots
                .iter()
                .filter(|a| a.is_active() && a.config.mode == AutopilotMode::Live && a.config.venue == cfg.venue)
                .map(|a| a.start_capital)
                .sum();
            let available = (free - committed).max(0.0);
            if cfg.capital_usd > available + EPS {
                let other = if committed > 0.0 { format!(", of which {} is already committed to other live autopilots", usd(committed)) } else { String::new() };
                return Err(format!(
                    "{} holds {} of free cash{other}, so {} cannot be given to the autopilot. Fund the account at the venue yourself; Pythia never moves money in or out, and a wallet such as Exodus stays read-only.",
                    venue_label(cv),
                    usd(free),
                    usd(cfg.capital_usd)
                ));
            }
        } else if cfg.mode == AutopilotMode::Paper {
            let paper = self.equity();
            if cfg.capital_usd > paper + EPS {
                return Err(format!("The paper account holds {}; a paper autopilot cannot trade more than that.", usd(paper)));
            }
        }

        // Go.
        let mut sleeves = Vec::new();
        for (sid, w, why, markets) in chosen {
            let s = self.strategies.iter().find(|s| s.id == sid).expect("chosen strategies exist");
            let weight = w / total;
            sleeves.push(Sleeve {
                strategy_id: sid.clone(),
                name: s.name.clone(),
                weight,
                why: format!("{why}; gets {:.0} % of the capital on {} market(s).", weight * 100.0, markets.len()),
                markets,
                realized: 0.0,
                fees: 0.0,
                trades: 0,
                prior_state: s.state,
            });
        }
        let id = cfg.id.clone();
        let want_state = if cfg.mode == AutopilotMode::Live { StrategyState::Live } else { StrategyState::Paper };
        for sl in &sleeves {
            if self.strategies.iter().any(|s| s.id == sl.strategy_id && s.state != want_state) {
                self.apply_strategy_state(&sl.strategy_id, want_state);
            }
            // A lab book rebalances to its targets with the autopilot's money
            // now, not on its next signal.
            self.lab_done.remove(&sl.strategy_id);
            self.lab_retry.remove(&sl.strategy_id);
        }
        // Positions the sleeve strategies held from before stay theirs.
        let outside: Vec<String> = sleeves
            .iter()
            .flat_map(|sl| sl.markets.iter())
            .filter(|m| self.positions.get(*m).is_some_and(|p| p.qty.abs() > 1e-12))
            .map(|m| self.markets.iter().find(|x| &x.id == m).map(|x| x.symbol.clone()).unwrap_or_else(|| m.clone()))
            .collect();

        let mut msg = format!(
            "Autopilot \"{}\" started in {} on {} with {}: {}.",
            cfg.name,
            cfg.mode.word(),
            venue_label(cv),
            usd(cfg.capital_usd),
            describe_rules(&cfg)
        );
        for sl in &sleeves {
            msg.push_str(&format!(" {}: {}", sl.name, sl.why));
        }
        if !outside.is_empty() {
            msg.push_str(&format!(
                " Already held from before and left outside the autopilot until closed: {}.",
                outside.join(", ")
            ));
        }
        if cfg.mode == AutopilotMode::Demo {
            msg.push_str(" Orders go to the venue's demo account: virtual money through the real API, never in the tax record.");
        }
        if cfg.mode == AutopilotMode::Live {
            if self.live.dry_run {
                msg.push_str(" Live routing is in dry-run: orders are logged, not sent.");
            } else if self.live.paper && venue == Venue::Alpaca {
                msg.push_str(" Alpaca is set to its paper endpoint: no real money moves there.");
            }
        }
        let kind = if cfg.mode == AutopilotMode::Live { JournalKind::Risk } else { JournalKind::System };
        self.log(kind, msg.clone(), None, None);
        self.pending_alerts.push(msg.clone());
        self.autopilots.retain(|a| a.config.id != id);
        self.autopilots.push(Autopilot {
            config: cfg,
            state: AutopilotState::Running,
            stop_reason: None,
            paused_reason: None,
            started_ms: now,
            stopped_ms: None,
            start_capital: 0.0,
            peak_equity: 0.0,
            locked_floor: None,
            tp_steps: 0,
            realized: 0.0,
            fees: 0.0,
            trades: 0,
            released: 0.0,
            flatten_at_stop: false,
            sleeves,
            owned: BTreeMap::new(),
            last_action: Some(msg),
            history: Vec::new(),
        });
        let i = self.autopilots.len() - 1;
        let x = self.autopilots[i].config.capital_usd;
        self.autopilots[i].start_capital = x;
        self.autopilots[i].peak_equity = x;
        self.autopilots[i].history.push((now, x));
        Ok(id)
    }

    /// Stop an autopilot now. `flatten` overrides its `flattenOnStop`.
    pub fn autopilot_stop(&mut self, id: &str, flatten: Option<bool>) -> Result<(), String> {
        let Some(i) = self.ap_index(id) else { return Err(format!("There is no autopilot \"{id}\".")) };
        if !self.autopilots[i].is_active() {
            return Err(format!("{} is already stopped.", self.autopilots[i].label()));
        }
        let flatten = flatten.unwrap_or(self.autopilots[i].config.flatten_on_stop);
        let now = self.now();
        self.ap_halt(i, AutopilotState::Stopped, "stopped by you".into(), flatten, now);
        Ok(())
    }

    /// Pause: nothing new is opened; open positions and the stop rules stay.
    pub fn autopilot_pause(&mut self, id: &str) -> Result<(), String> {
        let Some(i) = self.ap_index(id) else { return Err(format!("There is no autopilot \"{id}\".")) };
        match self.autopilots[i].state {
            AutopilotState::Running => {
                let now = self.now();
                self.ap_pause(i, "paused by you".into(), now);
                Ok(())
            }
            AutopilotState::Paused => Err(format!("{} is already paused.", self.autopilots[i].label())),
            _ => Err(format!("{} is stopped; start a new one instead.", self.autopilots[i].label())),
        }
    }

    /// Resume a paused autopilot. A live one checks its live gates again.
    pub fn autopilot_resume(&mut self, id: &str) -> Result<(), String> {
        let Some(i) = self.ap_index(id) else { return Err(format!("There is no autopilot \"{id}\".")) };
        match self.autopilots[i].state {
            AutopilotState::Paused => {}
            AutopilotState::Running => return Err(format!("{} is already running.", self.autopilots[i].label())),
            _ => return Err(format!("{} is stopped; start a new one instead.", self.autopilots[i].label())),
        }
        if self.autopilots[i].config.mode == AutopilotMode::Live {
            if let Some(why) = self.ap_live_problem(i) {
                return Err(format!("Cannot resume live: {why}"));
            }
        }
        let ap = &mut self.autopilots[i];
        ap.state = AutopilotState::Running;
        ap.paused_reason = None;
        let msg = format!("{} resumed.", ap.label());
        ap.last_action = Some(msg.clone());
        self.log(JournalKind::System, msg, None, None);
        Ok(())
    }

    /// Every autopilot as the UI shows it.
    pub fn autopilot_statuses(&self) -> Vec<AutopilotStatus> {
        self.autopilots
            .iter()
            .map(|ap| {
                let equity = self.ap_equity(ap);
                let x = ap.start_capital;
                let pnl = equity - x;
                let peak = ap.peak_equity.max(equity);
                let floor = if ap.is_active() {
                    floor_equity(&ap.config.stop, x, peak, ap.locked_floor).map(|f| f.0)
                } else {
                    None
                };
                let target = if ap.is_active() { take_profit_target(&ap.config.stop, x, ap.tp_steps) } else { None };
                AutopilotStatus {
                    config: ap.config.clone(),
                    state: ap.state,
                    stop_reason: ap.stop_reason.clone(),
                    paused_reason: ap.paused_reason.clone(),
                    started_ms: ap.started_ms,
                    stopped_ms: ap.stopped_ms,
                    start_capital: x,
                    equity,
                    pnl,
                    pnl_pct: if x > 0.0 { pnl / x * 100.0 } else { 0.0 },
                    peak_equity: peak,
                    drawdown_pct: if peak > 0.0 { ((peak - equity) / peak * 100.0).max(0.0) } else { 0.0 },
                    floor_equity: floor,
                    target_equity: target,
                    trades: ap.trades,
                    fees: ap.fees,
                    open_positions: ap.owned.len(),
                    by_sleeve: ap
                        .sleeves
                        .iter()
                        .map(|s| SleeveStatus {
                            strategy_id: s.strategy_id.clone(),
                            name: s.name.clone(),
                            weight: s.weight,
                            pnl: s.realized - s.fees + self.ap_unrealized(ap, Some(&s.strategy_id)),
                            trades: s.trades,
                            why: s.why.clone(),
                            markets: s.markets.clone(),
                        })
                        .collect(),
                    last_action: ap.last_action.clone(),
                    history: ap.history.clone(),
                }
            })
            .collect()
    }

    // ── the tick ───────────────────────────────────────────────────────────

    /// Watch every autopilot: its live gates, its stop rules, its history.
    /// Runs every tick, before strategies get to open anything.
    pub(super) fn autopilot_step(&mut self, now: i64) {
        for i in 0..self.autopilots.len() {
            self.ap_prune(i);
            if self.autopilots[i].is_active() {
                self.ap_check(i, now);
            } else if self.autopilots[i].flatten_at_stop && !self.autopilots[i].owned.is_empty() {
                // A late fill after the stop, or a real position that could
                // not be closed then: close it now.
                let name = self.autopilots[i].config.name.clone();
                let open: Vec<String> = self.autopilots[i].owned.keys().cloned().collect();
                for m in open {
                    if !self.ap_close_waits_for_price(&m) {
                        self.close_position(&m, &format!("autopilot \"{name}\" stopped"));
                    }
                }
            }
            if self.autopilots[i].is_active() || !self.autopilots[i].owned.is_empty() {
                self.ap_sample(i, now, false);
            }
        }
        // Keep the record of stopped ones short.
        let mut done: Vec<(i64, String)> = self
            .autopilots
            .iter()
            .filter(|a| !a.is_active() && a.owned.is_empty())
            .map(|a| (a.stopped_ms.unwrap_or(0), a.config.id.clone()))
            .collect();
        if done.len() > KEEP_FINISHED {
            done.sort_by(|a, b| b.0.cmp(&a.0));
            let drop: HashSet<String> = done.into_iter().skip(KEEP_FINISHED).map(|d| d.1).collect();
            self.autopilots.retain(|a| !drop.contains(&a.config.id));
        }
    }

    /// Forget positions that disappeared without a fill (reconciliation with
    /// the venue removed them): there is no P&L to book.
    fn ap_prune(&mut self, i: usize) {
        let gone: Vec<String> = self.autopilots[i]
            .owned
            .keys()
            .filter(|m| self.positions.get(*m).is_none_or(|p| p.qty.abs() < 1e-12))
            .cloned()
            .collect();
        for m in gone {
            self.autopilots[i].owned.remove(&m);
            let msg = format!(
                "{}: its position in {m} is gone without a fill it saw (corrected against the venue); that position's last P&L is not counted.",
                self.autopilots[i].label()
            );
            self.log(JournalKind::Risk, msg, None, Some(m));
        }
    }

    /// A paper position is closed by Pythia itself at the mark, so its close
    /// waits for a fresh price like every other exit does (journaled once).
    /// Demo and live closes are filled by the venue at its own price.
    /// Measured on the engine's own clock, like the stop checks.
    fn ap_close_waits_for_price(&mut self, market: &str) -> bool {
        let paper = self.positions.get(market).is_some_and(|p| !p.live && !p.demo);
        match self.exit_price_stale(market, self.now()).filter(|_| paper) {
            Some(age) => {
                self.note_exit_held(market, age, "Autopilot close");
                true
            }
            None => false,
        }
    }

    /// Why a live autopilot may not trade right now, if anything.
    fn ap_live_problem(&self, i: usize) -> Option<String> {
        let ap = &self.autopilots[i];
        let cv = CostVenue::parse(&ap.config.venue)?;
        if !self.live.armed {
            return Some("live routing is disarmed. Arm it on the Live page, then resume the autopilot.".into());
        }
        if !self.live_routable(engine_venue(cv)) {
            return Some(format!("{} is not enabled for live routing any more.", venue_label(cv)));
        }
        for sl in &ap.sleeves {
            let Some(s) = self.strategies.iter().find(|s| s.id == sl.strategy_id) else {
                return Some(format!("{} no longer exists.", sl.name));
            };
            let pp = self.passport_for(s);
            if s.state != StrategyState::Live || !pp.live_ready {
                let why = pp.blocked_reason.unwrap_or_else(|| "it is no longer set to live".into());
                return Some(format!("{} is no longer cleared for live ({why}).", sl.name));
            }
        }
        None
    }

    fn ap_check(&mut self, i: usize, now: i64) {
        if self.autopilots[i].state == AutopilotState::Running && self.autopilots[i].config.mode == AutopilotMode::Live {
            if let Some(why) = self.ap_live_problem(i) {
                self.ap_pause(i, why, now);
            }
        }
        let eq = self.ap_equity(&self.autopilots[i]);
        let flatten = self.autopilots[i].config.flatten_on_stop;
        {
            let ap = &mut self.autopilots[i];
            if eq > ap.peak_equity {
                ap.peak_equity = eq;
            }
        }
        let (stop, x, peak) = {
            let ap = &self.autopilots[i];
            (ap.config.stop.clone(), ap.start_capital, ap.peak_equity)
        };

        // Take profit.
        if let (Some(tp), Some(target)) = (stop.take_profit_pct, take_profit_target(&stop, x, self.autopilots[i].tp_steps)) {
            if eq >= target - EPS {
                match stop.on_take_profit {
                    OnTakeProfit::Stop => {
                        let reason = format!("take profit of {} % reached (equity {}, target {})", pct(tp), usd(eq), usd(target));
                        self.ap_halt(i, AutopilotState::Finished, reason, flatten, now);
                        return;
                    }
                    OnTakeProfit::Lock => {
                        let ap = &mut self.autopilots[i];
                        while take_profit_target(&stop, x, ap.tp_steps).is_some_and(|t| eq >= t - EPS) {
                            ap.tp_steps += 1;
                        }
                        let floor = locked_floor(x, tp, ap.tp_steps);
                        ap.locked_floor = Some(ap.locked_floor.map_or(floor, |f| f.max(floor)));
                        let next = take_profit_target(&stop, x, ap.tp_steps).unwrap_or(f64::INFINITY);
                        let msg = format!(
                            "{}: profit target reached at equity {} ({} %). Floor raised to {} to keep half the gain; next target {}.",
                            ap.label(),
                            usd(eq),
                            pct((eq - x) / x * 100.0),
                            usd(ap.locked_floor.unwrap_or(floor)),
                            usd(next)
                        );
                        ap.last_action = Some(msg.clone());
                        self.pending_alerts.push(msg.clone());
                        self.log(JournalKind::Risk, msg, None, None);
                        self.ap_sample(i, now, true);
                    }
                }
            }
        }

        // The floor.
        let locked = self.autopilots[i].locked_floor;
        if let Some((floor, rule)) = floor_equity(&stop, x, peak, locked) {
            if eq <= floor + EPS {
                let reason = match rule {
                    FloorRule::MaxLossPct => format!(
                        "max loss of {} % reached (equity {}, floor {})",
                        pct(stop.max_loss_pct.unwrap_or(0.0)),
                        usd(eq),
                        usd(floor)
                    ),
                    FloorRule::MaxLossUsd => format!(
                        "max loss of {} reached (equity {}, floor {})",
                        usd(stop.max_loss_usd.unwrap_or(0.0)),
                        usd(eq),
                        usd(floor)
                    ),
                    FloorRule::Trailing => format!(
                        "trailing floor reached: equity {} gave back {} % from its peak of {} (floor {})",
                        usd(eq),
                        pct(stop.trailing_pct.unwrap_or(0.0)),
                        usd(peak),
                        usd(floor)
                    ),
                    FloorRule::LockedProfit => format!(
                        "locked-in profit floor reached (equity {}, floor {})",
                        usd(eq),
                        usd(floor)
                    ),
                };
                self.ap_halt(i, AutopilotState::Stopped, reason, flatten, now);
                return;
            }
        }

        // The end time.
        if let Some(end) = stop.end_ms {
            if now >= end {
                self.ap_halt(i, AutopilotState::Finished, "end time reached".into(), flatten, now);
            }
        }
    }

    fn ap_pause(&mut self, i: usize, why: String, now: i64) {
        let ap = &mut self.autopilots[i];
        ap.state = AutopilotState::Paused;
        ap.paused_reason = Some(why.clone());
        let msg = format!(
            "{} paused: {why} It opens nothing new; its open positions keep their stops and its stop rules still apply.",
            ap.label()
        );
        ap.last_action = Some(msg.clone());
        self.pending_alerts.push(msg.clone());
        self.log(JournalKind::Risk, msg, None, None);
        self.ap_sample(i, now, true);
    }

    /// Stop or finish: close or release its positions, pause its strategies,
    /// and say so with the numbers.
    fn ap_halt(&mut self, i: usize, state: AutopilotState, reason: String, flatten: bool, now: i64) {
        {
            let ap = &mut self.autopilots[i];
            ap.state = state;
            ap.stop_reason = Some(reason.clone());
            ap.paused_reason = None;
            ap.stopped_ms = Some(now);
            ap.flatten_at_stop = flatten;
        }
        let name = self.autopilots[i].config.name.clone();
        let word = if state == AutopilotState::Finished { "finished" } else { "stopped" };
        let open: Vec<String> = self.autopilots[i].owned.keys().cloned().collect();
        let mut tail = String::new();
        if flatten {
            for m in &open {
                if !self.ap_close_waits_for_price(m) {
                    self.close_position(m, &format!("autopilot \"{name}\" {word}"));
                }
            }
            let left: Vec<String> = self.autopilots[i].owned.keys().cloned().collect();
            if left.is_empty() {
                if !open.is_empty() {
                    tail.push_str(&format!(" Closed its {} position(s).", open.len()));
                }
            } else {
                // Say why each one is still open: they have different cures.
                let (mut at_venue, mut stale, mut stuck) = (0, 0, 0);
                for m in &left {
                    if self.in_flight_markets.contains(m) {
                        at_venue += 1;
                    } else if self.ap_close_waits_for_price(m) {
                        stale += 1;
                    } else {
                        stuck += 1;
                    }
                }
                if at_venue > 0 {
                    tail.push_str(&format!(
                        " {at_venue} close order(s) are at the venue; their fills are booked to the autopilot when the venue reports them."
                    ));
                }
                if stale > 0 {
                    tail.push_str(&format!(
                        " {stale} paper position(s) wait for a fresh price before they are closed: a stale price is not where the market is."
                    ));
                }
                if stuck > 0 {
                    tail.push_str(&format!(
                        " {stuck} real position(s) could not be closed yet because live routing is not available; they stay with the autopilot and are closed as soon as it is."
                    ));
                }
            }
        } else if !open.is_empty() {
            let u = self.ap_unrealized(&self.autopilots[i], None);
            let ap = &mut self.autopilots[i];
            ap.released += u;
            ap.owned.clear();
            tail.push_str(&format!(
                " Left its {} position(s) open, now managed by their strategies' stops; its P&L counts them at their price now.",
                open.len()
            ));
        }
        let sleeves: Vec<(String, String, StrategyState)> =
            self.autopilots[i].sleeves.iter().map(|s| (s.strategy_id.clone(), s.name.clone(), s.prior_state)).collect();
        let mut paused = Vec::new();
        for (sid, sname, _) in &sleeves {
            if self.strategies.iter().any(|s| &s.id == sid && s.state != StrategyState::Paused) {
                self.apply_strategy_state(sid, StrategyState::Paused);
                paused.push(sname.clone());
            }
        }
        if !paused.is_empty() {
            tail.push_str(&format!(" Paused its strategies: {}.", paused.join(", ")));
        }
        let ap = &self.autopilots[i];
        let eq = self.ap_equity(ap);
        let x = ap.start_capital;
        let msg = format!(
            "{} {word}: {reason}. Equity {}, P&L {} ({} %), {} closed trade(s), fees {}.{tail}",
            ap.label(),
            usd(eq),
            signed_usd(eq - x),
            pct((eq - x) / x * 100.0),
            ap.trades,
            usd(ap.fees)
        );
        self.autopilots[i].last_action = Some(msg.clone());
        self.pending_alerts.push(msg.clone());
        self.log(JournalKind::Risk, msg, None, None);
        self.ap_sample(i, now, true);
    }

    fn ap_sample(&mut self, i: usize, now: i64, force: bool) {
        let eq = self.ap_equity(&self.autopilots[i]);
        let h = &mut self.autopilots[i].history;
        if !force && h.last().is_some_and(|(t, _)| now - t < HISTORY_EVERY_MS) {
            return;
        }
        h.push((now, eq));
        if h.len() > HISTORY_MAX {
            let last = h.len() - 1;
            let kept: Vec<(i64, f64)> = h.iter().enumerate().filter(|(k, _)| k % 2 == 0 || *k == last).map(|(_, p)| *p).collect();
            *h = kept;
        }
    }

    /// After a restart: a live autopilot does not trade until live routing is
    /// armed again and its strategies are still cleared, so it is paused with
    /// the reason. Its peak, floor and positions come back exactly as saved.
    pub(super) fn autopilots_after_restore(&mut self) {
        let now = self.now();
        for i in 0..self.autopilots.len() {
            let ap = &self.autopilots[i];
            if ap.state == AutopilotState::Running && ap.config.mode == AutopilotMode::Live {
                if let Some(why) = self.ap_live_problem(i) {
                    self.ap_pause(i, format!("Pythia restarted, and {why}"), now);
                }
            }
        }
        let active = self.autopilots.iter().filter(|a| a.is_active()).count();
        if active > 0 {
            self.log(
                JournalKind::System,
                format!("{active} autopilot(s) restored with their peak, floor and positions as saved"),
                None,
                None,
            );
        }
    }

    // ── strategy choice ────────────────────────────────────────────────────

    /// Why a strategy cannot be a sleeve, if it cannot.
    fn sleeve_block(&self, sid: &str, venue: Venue, mode: AutopilotMode, busy: &HashSet<String>) -> Option<String> {
        let s = self.strategies.iter().find(|s| s.id == sid)?;
        if !runnable(s.kind) {
            return Some(format!("{} is not a strategy the engine runs on its own.", s.name));
        }
        if mode != AutopilotMode::Live && s.state == StrategyState::Live {
            return Some(format!(
                "{} runs live on its own. A {} autopilot would take it off live; set it to paper yourself first if that is what you want.",
                s.name,
                mode.word()
            ));
        }
        if mode == AutopilotMode::Paper && s.state == StrategyState::Demo {
            return Some(format!(
                "{} demo-trades on its own. A paper autopilot would take it off demo; set it to paper yourself first if that is what you want, or start a demo autopilot.",
                s.name
            ));
        }
        if s.venue_class != venue {
            return Some(format!("{} trades {:?} markets, not this autopilot's venue.", s.name, s.venue_class));
        }
        if busy.contains(&s.id) {
            let other = self.autopilot_claimant(&s.id).unwrap_or_default();
            return Some(format!("{} already runs in the autopilot \"{other}\". A strategy runs for one autopilot at a time.", s.name));
        }
        if s.kind == StrategyKind::LabTargets {
            if !self.lab_signals.contains_key(&s.id) {
                return Some(format!("{} has no signal from the lab yet.", s.name));
            }
            let held = self.positions.values().any(|p| p.strategy_id == s.id && p.qty.abs() > 1e-12);
            if held {
                return Some(format!(
                    "{} still holds coins from its own run. A lab book only trades by rebalancing, so it could never start flat inside the autopilot: pause it and close its positions first.",
                    s.name
                ));
            }
        }
        None
    }

    /// The evidence behind one strategy.
    fn evidence(&self, sid: &str) -> Evidence {
        let Some(s) = self.strategies.iter().find(|s| s.id == sid) else { return Evidence::default() };
        let pp = self.passport_for(s);
        let (mode, est) = super::risk::edge_sizing(&s.ledger.edge);
        let lab = self.lab_signals.get(sid).map(|l| &l.evidence);
        Evidence {
            passed: pp.gates.iter().filter(|g| g.status == GateStatus::Pass).count(),
            failed: pp.gates.iter().filter(|g| g.status == GateStatus::Fail).count(),
            live_ready: pp.live_ready,
            measured: mode == super::risk::SizingMode::Measured,
            no_edge: mode == super::risk::SizingMode::NoEdge,
            kelly: est.map(|k| k.shrunk).unwrap_or(0.0),
            forward_trades: s.ledger.forward_trades,
            net: s.ledger.pnl.net,
            lab_oos_sharpe: lab.and_then(|e| e.oos_sharpe),
            lab_deflated_p: lab.and_then(|e| e.deflated_p),
        }
    }

    /// "Auto": the strategies the engine can run on this venue today, weighted
    /// by their evidence. Paused strategies are left out (they were paused on
    /// purpose, often on their evidence), so is any whose own record shows no
    /// edge, and live only takes strategies cleared for live.
    fn auto_pick(&self, venue: Venue, mode: AutopilotMode, busy: &HashSet<String>) -> Result<Vec<(String, f64, String)>, String> {
        let mut scored: Vec<(String, f64, Evidence)> = self
            .strategies
            .iter()
            .filter(|s| s.id != "manual" && s.state != StrategyState::Paused)
            .filter(|s| self.sleeve_block(&s.id, venue, mode, busy).is_none())
            .filter_map(|s| {
                let ev = self.evidence(&s.id);
                if mode == AutopilotMode::Live && !ev.live_ready {
                    return None;
                }
                ev.score().map(|sc| (s.id.clone(), sc, ev))
            })
            .collect();
        if scored.is_empty() {
            return Err(match mode {
                AutopilotMode::Live => "Auto found no strategy cleared for live on this venue. Live needs a green Strategy Passport; run the checks on the Strategies page or choose paper.".into(),
                _ => "Auto found no strategy it can run on this venue: every candidate is paused, already in an autopilot, or has a record that shows no edge.".into(),
            });
        }
        // Highest score first; ties keep the engine's order.
        scored.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));
        scored.truncate(AUTO_MAX_SLEEVES);
        Ok(scored.into_iter().map(|(id, sc, ev)| (id, sc, format!("Auto pick for {}", ev.describe()))).collect())
    }
}
