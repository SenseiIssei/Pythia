//! The Autopilot: an amount of money that trades itself.
//!
//! The owner gives an autopilot an amount X (`capitalUsd`) and a set of
//! strategies (sleeves, each with a weight). It runs them continuously against
//! live data until the owner stops it or one of its stop rules fires. Its
//! equity is X plus the realised and unrealised P&L of the positions it owns,
//! minus the fees it paid. A sleeve's budget is its weight times the
//! autopilot's equity, never a share of the whole account.
//!
//! # Every autopilot is a sub-account with a book of its own
//!
//! Several autopilots run side by side on one venue account (the Alpaca
//! paper account, say), each testing a different strategy. Each one is a
//! virtual sub-account: its positions are kept in a book of its own, under
//! `autopilot id|market` (see [`super::pos_key`]); the main book (strategies
//! no autopilot runs, manual orders) keeps its positions under the bare
//! market id. So two autopilots can hold the same coin at once, each with
//! its own quantity, average price, fills, fees, P&L, cash and equity curve.
//!
//! - **Orders and fills carry their book.** Every order an autopilot sends
//!   names its book, and every fill the venue reports for it is booked there
//!   and nowhere else, whichever strategy sent it and in whatever order the
//!   venue answers. Each autopilot sends its own orders; nothing is netted
//!   between autopilots. Two books trade one venue account, so an order on
//!   the other side of a symbol from another book waits until that one is
//!   done (the two could meet at the venue as a wash trade).
//! - **The venue holds the sum.** The reconciliation compares what the
//!   venue holds per symbol with the sum over every book; when the venue
//!   wins, each book takes its share in proportion to what it held, and each
//!   autopilot books its own difference at the mark, so a correction never
//!   moves its equity past a stop unseen (`engine::demo_reconcile`).
//! - **Strategies may be shared.** A paper or demo autopilot may run a
//!   strategy (a lab book too) that other paper or demo autopilots run: each
//!   trades it in its own book with its own money, and one signal is an
//!   entry for each of them. A live autopilot keeps its strategies to itself
//!   and takes none another autopilot runs. While any autopilot runs a
//!   strategy, its state is the autopilots' to set; stopping one autopilot
//!   pauses only the strategies no other one still runs.
//! - **Markets are exclusive inside one autopilot.** Its book has one
//!   position per market, so at start every market of its strategies is
//!   assigned to exactly one of its sleeves. Strategies that trade a whole
//!   set at once (Pairs, lab books) claim their full universe first, all or
//!   nothing; the other sleeves then deal the remaining markets out in turn,
//!   highest weight first. The one exception is lab books among themselves:
//!   they net their targets per coin (below). Other autopilots take nothing
//!   from it: their books are their own.
//! - **Positions belong to the book they are in.** Every fill in an
//!   autopilot's book (the strategy's exit, an ATR stop, a flatten from the
//!   Positions page) is booked to the autopilot, and so is a broker
//!   correction. A position a sleeve strategy holds elsewhere (the main
//!   book, another autopilot) stays where it is: the new autopilot starts
//!   with an empty book. A lab book that trades on its own and holds coins
//!   in the main book cannot be claimed (those coins would be left
//!   unmanaged); coins it holds in another autopilot's book do not matter.
//!
//! Saves from before books existed kept every position under its market id,
//! with each autopilot's `owned` naming its markets. On restore they move into
//! the autopilot's book exactly as they are, with the orders still at the
//! venue and the fees still to be posted, and nothing is traded
//! ([`Engine::migrate_to_books`]).
//!
//! # Lab books inside autopilots
//!
//! A lab book (`StrategyKind::LabTargets`) executes the research lab's daily
//! target weights. By default the first signal creates it in paper and it
//! rebalances on its own, which also means it holds coins and can never join
//! an autopilot. An engine meant for autopilots runs with
//! `PYTHIA_LAB_BOOKS=idle` instead: every lab book is created *idle*
//! (paused, holding nothing) and kept up to date with its latest signal and
//! evidence, and it trades only once an autopilot claims it, with that
//! autopilot's capital and route. When the autopilot stops, the book is
//! paused again (idle) and the autopilot's `flattenOnStop` decides what
//! happens to the coins; coins left open stay unmanaged (a lab book has no
//! stops) and keep the book out of the next autopilot until they are closed.
//! A signal can also ask for this on any engine (`autopilot_only`), which
//! the lab does for candidates that fail deflation or overlap a book that
//! already runs standalone.
//!
//! # Several lab books, netted
//!
//! The lab books of one autopilot are rebalanced as one book. Each book's
//! target weights are scaled by its sleeve weight (over the lab sleeves'
//! combined weight) and added up per coin ([`net_lab_targets`]); the netted
//! target is rebalanced with the autopilot's capital, one position per coin,
//! and only the difference is traded. Each book's share of the netted
//! target per coin is kept (`Autopilot::shares`): fills, fees, closed trades
//! and P&L on that coin are split by it, and when a new target changes the
//! shares, the position's open P&L so far stays with the books that earned
//! it (booked across at the mark, adding up to zero). A book whose signal is
//! past its window holds its last targets inside the netted book.
//!
//! An auto-pick autopilot re-runs its pick every `repickEveryHours` (24 by
//! default, 0 = never; explicit sleeves are never re-picked) and re-weights,
//! adds or drops lab books. A change is netted in at the next rebalance;
//! a dropped book stays listed at weight zero (and stays the autopilot's),
//! and its coins are sold down only where the other books do not want them.
//! A live autopilot only re-weights or drops: it never adds a strategy the
//! owner did not confirm. Built-in sleeves own their positions outright and
//! are not re-picked.
//!
//! # Changing it in place
//!
//! [`Engine::autopilot_update`] changes a running or paused autopilot
//! without a stop: its name, strategies and weights (or the auto pick), its
//! stop rules, its amount and its pick settings. Nothing is sold to make the
//! change. A new set of lab books is netted in at the next rebalance, which
//! runs at once and trades only the difference per coin, so a coin the old
//! and the new books both want is re-attributed, not sold and bought back.
//! A strategy taken out stays listed at weight zero while it holds something
//! or has a record, exactly like a book a re-pick dropped. A new amount
//! moves X, the peak and a locked floor by the difference, so the P&L so far
//! stays; a lower one brings the targets down at the next rebalance. The
//! checks are the start's, plus: a live change needs the typed confirmation,
//! a looser max-loss rule (in dollars or in % of X) needs a confirmation in
//! any mode, a live amount never goes above the venue's free cash plus what
//! the autopilot already holds there, and rules that would end it on the
//! spot are refused (that is what Stop is for). Journaled with what changed.
//!
//! When a running autopilot holds nothing, its status says it is in cash,
//! waiting for signals, with the reason when the netted target knows it.
//! Nothing is ever bought to look busy.
//!
//! # The auto pick
//!
//! "Let Pythia choose" scores every candidate on one scale
//! ([`Evidence::score`]): gates passed, cleared for live, a measured edge,
//! a positive forward record and, for lab books, the out-of-sample Sharpe,
//! the Sharpe with costs doubled and the deflated-Sharpe probability, all
//! divided by one plus the gates failed. Each pick says why in one sentence,
//! and a pick that fails the deflation test (or has no green passport) says
//! that it is the best available evidence, not a proven edge. It picks up to
//! `maxSleeves` (3 by default) with positive evidence, weighted by score.
//! Candidates are taken best first and markets stay exclusive inside the
//! autopilot: lab books claim every crypto market together (they net), so
//! built-ins only get crypto markets when they out-score every lab book.
//! Whoever is passed over for that reason is named in the start message.
//!
//! # Benchmarks and the side-by-side view
//!
//! Every autopilot is held against buying and holding: BTC for crypto, SPY
//! for US shares, from its start to now (or to its stop). An autopilot saved
//! before the comparison existed gets its start price from the nearest
//! candle at its start; with none in reach for [`BENCH_WAIT_MS`], the
//! comparison starts at the price then, and its status says so. Each status
//! also carries its own cash, its deepest drawdown and its equity history,
//! which the Autopilot page sets side by side.
//!
//! # Portfolios across asset classes
//!
//! A portfolio autopilot (`portfolio: true`) is one amount over two asset
//! classes on the Alpaca account: crypto lab books and lab books of US
//! shares and ETFs, side by side in its one book, with one equity, one set
//! of stop rules and one P&L. Paper or demo only (demo needs crypto demo
//! orders on the Alpaca paper account, `PYTHIA_DEMO_EXCHANGE=alpaca`, so
//! both classes trade the same account); a portfolio never goes live, and
//! single-class live autopilots keep every gate they had.
//!
//! - **The split between the classes is by evidence** (`engine::allocator`).
//!   Each class runs the auto pick on its own lab books, and only books with
//!   a positive out-of-sample Sharpe from the lab count. A class's budget is
//!   the score of its best book per unit of that book's out-of-sample
//!   drawdown (the class's typical drawdown when the lab measured none),
//!   over the sum of both. A class with no such book gets nothing, never a
//!   forced share: today that is usually US shares, whose books have no
//!   evidence yet, and the whole amount goes to crypto. Inside a class the
//!   books split its budget by score, as the auto pick always did. The
//!   forward report (`reports/forward/evidence.json`) lowers a book's score
//!   once its forward record falls below its backtest's band, here as in
//!   every auto pick.
//! - **Re-picks move the split in bounded steps.** Every `repickEveryHours`
//!   the pick runs again; a class budget moves by at most
//!   [`PORTFOLIO_MAX_SHIFT`] per re-pick while both classes have evidence,
//!   so noisy evidence never swings the portfolio from one class to the
//!   other. A class that loses all its evidence drops to zero at once, and
//!   one that gains evidence starts from zero and grows by the step.
//! - **Each class rebalances on its own clock.** The lab books of one class
//!   are netted into one target, as in any autopilot; the two classes are
//!   two netted groups of the same book. US shares rebalance only in the
//!   regular session (the same wait every lab book of US shares has), so
//!   their queued rebalance never holds the crypto books back, which trade
//!   at any time.
//! - **Blended benchmark.** It is held against BTC and SPY bought and held
//!   at its class budgets ([`BlendBench`]); when a re-pick moves the budgets
//!   the blend is chain-linked and continues at the new weights.
//!
//! # Capital on a shared account
//!
//! Paper autopilots share the engine's paper account: together they are
//! given no more than it holds. Demo autopilots on the Alpaca paper account
//! share that account the same way: the host reads its equity before a start
//! or a raise ([`Engine::autopilot_needs_paper_equity`]), and the amounts of
//! the demo autopilots there may not add up to more. Lowering one's amount
//! frees the difference for another.
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
use crate::alerts::AlertKind;
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
/// "Auto" picks at most this many strategies unless told otherwise.
pub const AUTO_MAX_SLEEVES: usize = 3;
/// And never more than this many, whatever it is told.
pub const AUTO_MAX_SLEEVES_LIMIT: usize = 10;
/// An auto-pick autopilot re-runs its pick this often unless told otherwise.
pub const REPICK_DEFAULT_HOURS: f64 = 24.0;
/// A re-pick that moves no weight by more than this keeps the sleeves as they
/// are: a shift of a point or two is noise in the evidence, not news.
pub const REPICK_MIN_SHIFT: f64 = 0.02;
/// Stopped autopilots kept for the record, newest first.
const KEEP_FINISHED: usize = 10;
/// An entry worth less than this is not worth its fee.
pub(super) const MIN_ENTRY_USD: f64 = 1.0;
/// The asset classes of a portfolio autopilot, in the order it lists them.
pub const PORTFOLIO_CLASSES: [Venue; 2] = [Venue::Crypto, Venue::Alpaca];
/// A portfolio's class budget moves by at most this much per re-pick while
/// both classes have evidence.
pub const PORTFOLIO_MAX_SHIFT: f64 = 0.10;

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
    /// The markets it trades, when the venue alone does not say: crypto on
    /// the Alpaca paper account is venue "alpaca" with asset class "crypto".
    /// Empty: the venue decides (alpaca is US shares, polymarket prediction
    /// markets, any other crypto). The engine fills it in at start.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub asset_class: Option<Venue>,
    pub capital_usd: f64,
    /// Empty: "auto" picks the strategies.
    #[serde(default)]
    pub sleeves: Vec<SleeveConfig>,
    #[serde(default)]
    pub stop: StopRules,
    #[serde(default = "yes")]
    pub flatten_on_stop: bool,
    /// "Auto" picks at most this many strategies. Empty: 3.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub max_sleeves: Option<usize>,
    /// Re-run the auto pick with fresh evidence every this many hours. Only
    /// for an autopilot whose strategies Pythia picks: empty means every 24
    /// hours there, 0 turns it off. Explicit sleeves are never re-picked.
    /// The engine fills it in at start.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub repick_every_hours: Option<f64>,
    /// A portfolio across asset classes: one amount over crypto lab books
    /// and lab books of US shares in one book on the Alpaca account, split
    /// between the two classes by evidence (see "Portfolios across asset
    /// classes" above). Paper or demo only, and Pythia picks the books.
    /// Off: one asset class, as before.
    #[serde(default, skip_serializing_if = "std::ops::Not::not")]
    pub portfolio: bool,
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
    /// The markets assigned to this sleeve. No other sleeve trades them,
    /// except lab books, which net their targets on the same coins.
    pub markets: Vec<String>,
    /// What this sleeve holds right now, at the mark: its share of every
    /// position the autopilot owns.
    #[serde(default)]
    pub exposure: f64,
    /// `exposure` as a % of the autopilot's equity.
    #[serde(default)]
    pub exposure_pct: f64,
    /// A re-pick took its weight to zero; it is listed for its record.
    #[serde(default)]
    pub dropped: bool,
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
    /// Closed trades, one per order however many fills it took.
    pub trades: u32,
    /// Orders that filled, buys and sells, one per order: a maker order
    /// worked through several child orders or partial fills counts once.
    #[serde(default)]
    pub orders: u32,
    pub fees: f64,
    /// Positions it owns right now.
    pub open_positions: usize,
    pub by_sleeve: Vec<SleeveStatus>,
    pub last_action: Option<String>,
    /// `[epoch ms, equity]`, one point a minute, thinned to at most 300.
    pub history: Vec<(i64, f64)>,
    /// How its forward result compares with the backtest, from the lab's
    /// daily forward report. Only for an active autopilot; `None` when the
    /// report has nothing on it.
    #[serde(default)]
    pub forward: Option<AutopilotForward>,
    /// Running and holding nothing: it is in cash, waiting for signals, and
    /// says why in plain words. It never forces a trade to look busy.
    #[serde(default)]
    pub waiting: Option<String>,
    /// When the auto pick runs again with fresh evidence, if it does.
    #[serde(default)]
    pub next_repick_ms: Option<i64>,
    /// What holding Bitcoin did over the same period, in %: the BTC price at
    /// its start against the price now (or when it stopped). `None` when no
    /// BTC price was known at the start.
    #[serde(default)]
    pub btc_return_pct: Option<f64>,
    /// Market ids it holds right now.
    #[serde(default)]
    pub held: Vec<String>,
    /// What it is held against: BTC buy and hold for crypto, SPY buy and
    /// hold for US shares, over the same period.
    #[serde(default)]
    pub benchmark: Option<BenchmarkStatus>,
    /// The cash of its own book: equity less what its positions are worth
    /// at the mark and what its orders still at the venue will cost.
    #[serde(default)]
    pub cash: f64,
    /// The deepest fall from a peak over its equity history, in %.
    #[serde(default)]
    pub max_drawdown_pct: f64,
    /// A portfolio: each asset class with its budget and its own P&L.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub classes: Vec<ClassStatus>,
}

/// One asset class of a portfolio autopilot, as the UI shows it.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct ClassStatus {
    /// "crypto" or "alpaca" (US shares), as [`Venue`] is written.
    pub class: Venue,
    /// "Crypto", "US shares".
    pub label: String,
    /// Its share of the portfolio's equity, 0..1: the sum of its books'
    /// weights. 0 when no book of the class has evidence.
    pub weight: f64,
    /// Realised and unrealised P&L of its books, net of fees.
    pub pnl: f64,
    /// What it holds now, at the mark.
    pub exposure: f64,
    /// Lab books of the class with weight.
    pub books: usize,
    /// Why it holds nothing or waits, in plain words, when it does.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub note: Option<String>,
}

/// One leg of a blended benchmark.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct BenchmarkLeg {
    pub symbol: String,
    /// Its weight in the blend now, 0..1.
    pub weight: f64,
    /// Buy and hold of this leg since the blend was last set to these
    /// weights, in %.
    pub return_pct: Option<f64>,
}

/// What an autopilot is held against, as the UI shows it.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct BenchmarkStatus {
    /// "BTC/USD" or "SPY".
    pub symbol: String,
    /// "BTC buy and hold", "SPY buy and hold".
    pub name: String,
    /// Buy and hold over the same period, in %. `None` while a start price
    /// is still being looked for.
    pub return_pct: Option<f64>,
    /// The autopilot's return less the benchmark's, in points.
    pub excess_pct: Option<f64>,
    /// When the comparison starts, if not at the autopilot's start.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub from_ms: Option<i64>,
    /// How a start price was filled in after the fact, when it was.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub note: Option<String>,
    /// A blend (a portfolio): BTC and SPY with their weights.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub legs: Vec<BenchmarkLeg>,
}

/// A portfolio's blended benchmark: BTC and SPY bought and held at the
/// portfolio's class budgets, set back to the new budgets at every change
/// of them and chain-linked, so each stretch is measured at the weights it
/// actually had. Saved with the autopilot.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct BlendBench {
    /// Growth of the stretches before this one, 1.0 at the start.
    pub index: f64,
    /// When this stretch began.
    pub since_ms: i64,
    pub w_btc: f64,
    pub w_spy: f64,
    /// The prices this stretch is measured from. `None` in the first one:
    /// the autopilot's own BTC and SPY starts are used (filled in later
    /// when no price was known at the start).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub btc_ref: Option<f64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub spy_ref: Option<f64>,
}

/// A benchmark start missing this long (no candle from the autopilot's
/// start in sight) is taken from the price now, and the status says so.
pub const BENCH_WAIT_MS: i64 = 10 * 60_000;
/// A candle this far from the start time still prices the start.
const BENCH_CANDLE_TOLERANCE_MS: i64 = 36 * 3_600_000;
const BTC_SYMBOL: &str = "BTC/USD";
/// The SPY market US shares are held against.
pub const SPY_ID: &str = "alpaca:SPY";

fn when(ms: i64) -> String {
    chrono::DateTime::from_timestamp_millis(ms).map(|t| t.format("%Y-%m-%d %H:%M UTC").to_string()).unwrap_or_default()
}

/// Buy and hold from `p0` to `p1`, in %.
fn leg_return(p0: Option<f64>, p1: Option<f64>) -> Option<f64> {
    let p0 = p0.filter(|p| *p > 0.0 && p.is_finite())?;
    let p1 = p1.filter(|p| *p > 0.0 && p.is_finite())?;
    Some((p1 / p0 - 1.0) * 100.0)
}

/// The deepest fall from a running peak over an equity history and the
/// equity now, in %.
pub fn max_drawdown_pct(history: &[(i64, f64)], now: f64) -> f64 {
    let mut peak = f64::MIN;
    let mut worst: f64 = 0.0;
    for v in history.iter().map(|h| h.1).chain(std::iter::once(now)) {
        if !v.is_finite() {
            continue;
        }
        if v > peak {
            peak = v;
        }
        if peak > 0.0 {
            worst = worst.max((peak - v) / peak * 100.0);
        }
    }
    worst
}

/// An autopilot's forward result against its backtest, for one plain line.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct AutopilotForward {
    /// early (under `lab::FORWARD_MIN_DAYS` days) · ok (inside or above the
    /// band) · watch (inside, but its dip or its floor is worth a look) ·
    /// below (under the band) · none (no band to compare with)
    pub status: String,
    pub days: f64,
    pub return_pct: Option<f64>,
    pub band_low_pct: Option<f64>,
    pub band_high_pct: Option<f64>,
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

/// A change to a running or paused autopilot, made in place. Every field is
/// optional: what is left out stays as it is.
#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct AutopilotUpdate {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub name: Option<String>,
    /// The new amount X. Lower: its targets come down at the next rebalance,
    /// nothing is sold at once. Higher: within the same checks as a start.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub capital_usd: Option<f64>,
    /// New strategies and weights. An empty list switches to the auto pick.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub sleeves: Option<Vec<SleeveConfig>>,
    /// The new stop rules, whole.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub stop: Option<StopRules>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub flatten_on_stop: Option<bool>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub max_sleeves: Option<usize>,
    /// 0 turns re-picking off.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub repick_every_hours: Option<f64>,
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
    /// A re-pick took its weight to zero at this time. It stays listed with
    /// its record, and its coins are sold down by the next netted rebalance
    /// only as far as the other books do not want them.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub dropped_ms: Option<i64>,
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
    /// Lab books are netted: for a market they hold together, each lab
    /// sleeve's share of the combined target there (the shares add up to 1).
    /// Fills, fees and P&L on that market are split by these shares. A market
    /// without an entry belongs wholly to the sleeve in `owned`.
    #[serde(default)]
    pub shares: BTreeMap<String, BTreeMap<String, f64>>,
    /// The netted lab target of the last rebalance: market to weight of the
    /// autopilot's equity.
    #[serde(default)]
    pub lab_target: BTreeMap<String, f64>,
    /// Why the last netted target holds cash, when it holds nothing.
    #[serde(default)]
    pub cash_note: Option<String>,
    /// When the auto pick last ran (the start, or the last re-pick).
    #[serde(default)]
    pub last_pick_ms: Option<i64>,
    /// The BTC price when it started, for the buy-and-hold comparison.
    #[serde(default)]
    pub btc_start: Option<f64>,
    /// The BTC price when it stopped; the comparison ends there.
    #[serde(default)]
    pub btc_end: Option<f64>,
    /// Orders that filled, one per order (see [`AutopilotStatus::orders`]).
    #[serde(default)]
    pub orders: u32,
    /// The last venue orders it booked fills of, and whether each has
    /// already counted as a closed trade, so the next fill of the same order
    /// (a partial fill, another maker child) does not count again.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub recent_orders: Vec<(String, bool)>,
    /// The SPY price when it started and when it stopped, for an autopilot
    /// of US shares.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub spy_start: Option<f64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub spy_end: Option<f64>,
    /// When the BTC (or SPY) comparison starts, if not at its start: an
    /// autopilot saved before the benchmark existed, with no candle from its
    /// start, is compared from the first price known after.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub btc_from_ms: Option<i64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub spy_from_ms: Option<i64>,
    /// How a benchmark start was filled in after the fact, in plain words.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub bench_notes: Vec<String>,
    /// Since when a benchmark start has been looked for. Not saved: a
    /// restart looks again, candles first.
    #[serde(skip)]
    pub bench_wait_ms: Option<i64>,
    /// A portfolio: its blended BTC and SPY benchmark.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub blend: Option<BlendBench>,
    /// A portfolio: why an asset class holds cash, by class ("crypto",
    /// "alpaca"), from its last netted target.
    #[serde(default, skip_serializing_if = "BTreeMap::is_empty")]
    pub class_notes: BTreeMap<String, String>,
}

/// How many venue orders an autopilot remembers for counting.
const RECENT_ORDERS: usize = 64;

impl Autopilot {
    /// Count one fill: a new order once in `orders`, and a closed trade once
    /// per order. Returns whether this fill counts as a closed trade. A
    /// paper fill (`order` is `None`) is an order of its own.
    fn count_fill(&mut self, order: Option<&str>, closed: bool) -> bool {
        let Some(id) = order else {
            self.orders += 1;
            if closed {
                self.trades += 1;
            }
            return closed;
        };
        let counts = match self.recent_orders.iter_mut().find(|(o, _)| o == id) {
            Some((_, done)) => {
                let first = closed && !*done;
                *done |= closed;
                first
            }
            None => {
                self.orders += 1;
                self.recent_orders.push((id.to_string(), closed));
                if self.recent_orders.len() > RECENT_ORDERS {
                    self.recent_orders.remove(0);
                }
                closed
            }
        };
        if counts {
            self.trades += 1;
        }
        counts
    }

    pub fn is_active(&self) -> bool {
        matches!(self.state, AutopilotState::Running | AutopilotState::Paused)
    }

    fn sleeve(&self, sid: &str) -> Option<&Sleeve> {
        self.sleeves.iter().find(|s| s.strategy_id == sid)
    }

    fn sleeve_mut(&mut self, sid: &str) -> Option<&mut Sleeve> {
        self.sleeves.iter_mut().find(|s| s.strategy_id == sid)
    }

    fn label(&self) -> String {
        format!("Autopilot \"{}\"", self.config.name)
    }

    /// This sleeve's share of the position in `market`.
    fn share(&self, market: &str, sid: &str) -> f64 {
        match self.shares.get(market).filter(|m| !m.is_empty()) {
            Some(m) => m.get(sid).copied().unwrap_or(0.0),
            None => {
                if self.owned.get(market).is_some_and(|o| o == sid) {
                    1.0
                } else {
                    0.0
                }
            }
        }
    }

    /// How an amount booked on `market` splits over the sleeves: by their
    /// shares when lab books net there, else all of it to `owner`.
    fn split(&self, market: &str, owner: &str) -> Vec<(String, f64)> {
        if let Some(m) = self.shares.get(market) {
            let total: f64 = m.values().filter(|v| v.is_finite() && **v > 0.0).sum();
            if total > EPS {
                return m.iter().filter(|(_, v)| v.is_finite() && **v > 0.0).map(|(k, v)| (k.clone(), v / total)).collect();
            }
        }
        vec![(owner.to_string(), 1.0)]
    }

    /// Book `amount` of realised P&L (and `fee`) on `market` to its sleeves.
    fn book_split(&mut self, market: &str, owner: &str, realized: f64, fee: f64, closed: bool) {
        for (sid, w) in self.split(market, owner) {
            if let Some(s) = self.sleeve_mut(&sid) {
                s.realized += realized * w;
                s.fees += fee * w;
                if closed {
                    s.trades += 1;
                }
            }
        }
    }

    /// The market is no longer its own. Its shares stay until the next netted
    /// target replaces them: a fee the venue posts later (Alpaca books crypto
    /// fees at the end of the day) is still split the way the trade was.
    pub(super) fn release(&mut self, market: &str) {
        self.owned.remove(market);
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
    if let Some(n) = cfg.max_sleeves {
        if n == 0 || n > AUTO_MAX_SLEEVES_LIMIT {
            return Err(format!("Auto can pick 1 to {AUTO_MAX_SLEEVES_LIMIT} strategies, not {n}."));
        }
    }
    if let Some(h) = cfg.repick_every_hours {
        if !h.is_finite() || h < 0.0 || (h > 0.0 && h < 1.0) {
            return Err(format!("Re-picking runs at most once an hour (or 0 for never), not every {h} hours."));
        }
        if h > 0.0 && !cfg.sleeves.is_empty() {
            return Err("Re-picking only applies when Pythia chooses the strategies; strategies you chose stay as you chose them.".into());
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

/// The most the max-loss rules let an autopilot with capital `x` lose: in
/// dollars and in % of `x`. `None` is no limit.
pub fn max_loss_allowance(stop: &StopRules, x: f64) -> (Option<f64>, Option<f64>) {
    let by_pct = stop.max_loss_pct.map(|p| x * p / 100.0);
    let usd = match (by_pct, stop.max_loss_usd) {
        (Some(a), Some(b)) => Some(a.min(b)),
        (a, b) => a.or(b),
    };
    let pct = usd.map(|u| if x > 0.0 { u / x * 100.0 } else { 0.0 });
    (usd, pct)
}

/// Does going from (`old`, `old_x`) to (`new`, `new_x`) let the autopilot
/// lose more, in dollars or in % of its amount? Removing every max-loss rule
/// does.
pub fn loosens_max_loss(old: &StopRules, old_x: f64, new: &StopRules, new_x: f64) -> bool {
    let (ou, op) = max_loss_allowance(old, old_x);
    let (nu, np) = max_loss_allowance(new, new_x);
    let more = |o: Option<f64>, n: Option<f64>| match (o, n) {
        (None, _) => false,
        (Some(_), None) => true,
        (Some(o), Some(n)) => n > o + 1e-6,
    };
    more(ou, nu) || more(op, np)
}

fn describe_allowance(stop: &StopRules, x: f64) -> String {
    match max_loss_allowance(stop, x) {
        (Some(u), Some(p)) => format!("{} ({} %)", usd(u), pct(p)),
        _ => "no limit".into(),
    }
}

/// What one sleeve asks for when markets are assigned.
#[derive(Debug, Clone)]
pub struct Want {
    pub weight: f64,
    /// Trades its universe as one set (Pairs, lab books): all or nothing.
    pub whole: bool,
    /// Nets its targets with the other netting sleeves (lab books): they
    /// share their markets with each other, never with anyone else.
    pub net: bool,
    pub universe: Vec<String>,
}

/// Give every market to exactly one sleeve. Whole-set sleeves claim their full
/// universe first, highest weight first, and get nothing if any of it is
/// taken. Netting sleeves (lab books) are the one exception: they share
/// markets with each other, because their targets are netted per coin into
/// one position, but never with any other sleeve. The other sleeves then
/// deal the remaining markets out in turn, highest weight first, each taking
/// its next free market. `taken` are markets that belong to another active
/// autopilot. Returns the markets per sleeve, in the input order.
pub fn assign_markets(wants: &[Want], taken: &HashSet<String>) -> Vec<Vec<String>> {
    let mut order: Vec<usize> = (0..wants.len()).collect();
    // Stable: equal weights keep the order they were given in.
    order.sort_by(|&a, &b| wants[b].weight.partial_cmp(&wants[a].weight).unwrap_or(std::cmp::Ordering::Equal));
    let mut claimed: HashSet<String> = taken.clone();
    // Markets netting sleeves hold: closed to everyone but other netting sleeves.
    let mut netted: HashSet<String> = HashSet::new();
    let mut out: Vec<Vec<String>> = vec![Vec::new(); wants.len()];
    for &i in order.iter().filter(|&&i| wants[i].whole) {
        let w = &wants[i];
        let free = |m: &String| !claimed.contains(m) && (w.net || !netted.contains(m));
        if !w.universe.is_empty() && w.universe.iter().all(free) {
            for m in &w.universe {
                if w.net {
                    netted.insert(m.clone());
                } else {
                    claimed.insert(m.clone());
                }
            }
            out[i] = w.universe.clone();
        }
    }
    claimed.extend(netted);
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

/// What "auto" chose: (strategy id, weight, why) per pick, and the names of
/// the candidates it passed over.
type AutoPick = (Vec<(String, f64, String)>, Vec<String>);

/// What a portfolio's pick chose (see `Engine::portfolio_pick`).
struct PortfolioPick {
    /// (strategy id, weight, why); the weights add up to one.
    picks: Vec<(String, f64, String)>,
    /// Each class's share of the amount, in [`PORTFOLIO_CLASSES`] order.
    budgets: Vec<(Venue, f64)>,
    /// The classes that got nothing, and why.
    empty: Vec<(Venue, String)>,
    passed_over: Vec<String>,
}

impl PortfolioPick {
    /// The split in words: "Crypto 70 %, US shares 30 %".
    fn split_words(&self) -> String {
        self.budgets.iter().map(|(c, b)| format!("{} {:.0} %", class_label(*c), b * 100.0)).collect::<Vec<_>>().join(", ")
    }
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
    /// A lab book: its research numbers come from the lab's report.
    pub lab: bool,
    /// Lab books: out-of-sample Sharpe, deflated-Sharpe probability over
    /// `lab_variants` variants, and the Sharpe with costs doubled (or more).
    pub lab_oos_sharpe: Option<f64>,
    pub lab_deflated_p: Option<f64>,
    pub lab_variants: Option<usize>,
    pub lab_sharpe_2x_cost: Option<f64>,
    /// Lab books: the deepest out-of-sample drawdown, as a fraction. The
    /// portfolio allocator weights evidence per unit of it.
    pub lab_max_dd: Option<f64>,
    /// A known weakness of the lab evidence (see `lab::LabEvidence::caveat`).
    pub lab_caveat: Option<String>,
    /// Lab books: the lab's own paper book against its backtest's band, from
    /// the daily forward report. Counts only from `lab::FORWARD_MIN_DAYS` on.
    pub forward: Option<crate::lab::ForwardEvidence>,
}

/// Gate 6 passes above this deflated-Sharpe probability (see `lab::verdict`).
pub const DEFLATION_PASS: f64 = 0.95;

/// A lab book whose forward return is below its backtest's band (after at
/// least `lab::FORWARD_MIN_DAYS` days) keeps this share of its score.
pub const FORWARD_BELOW_FACTOR: f64 = 0.5;

/// A forward report older than this is not used: the lab writes one a day,
/// so three days without one means the job stopped, and old numbers would
/// keep judging a book on a record that has moved on.
pub const FORWARD_STALE_MS: i64 = 3 * 86_400_000;

impl Evidence {
    /// A score for weighting, or `None` when the evidence rules it out.
    ///
    /// Every strategy, built-in or lab book, is scored on one scale:
    ///
    /// ```text
    /// ( 1 + gates passed
    ///     + 4                        cleared for live
    ///     + 2 + 20 x Kelly (<= 0.25)  a measured edge from 30+ closed trades
    ///     + 1                        10+ forward trades, net positive
    ///     + OOS Sharpe   (0 to 2)    lab books, out of sample, after costs
    ///     + 0.5 x Sharpe at 2x cost (0 to 2)
    ///     + deflated p   (0 to 1)    the probability the Sharpe is skill
    /// ) / (1 + gates failed)
    ///   x 0.5                        lab books whose forward return is below
    ///                                their backtest's band after 10+ days
    /// ```
    ///
    /// The forward record only ever lowers a score, and only once it has
    /// [`crate::lab::FORWARD_MIN_DAYS`] days: before that it changes nothing.
    ///
    /// A built-in strategy nobody has run the checks for scores 1. A lab book
    /// that fails half its gates is divided down hard, so a high Sharpe on its
    /// own does not buy a pick.
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
        if let Some(sh) = self.lab_oos_sharpe.filter(|v| v.is_finite()) {
            s += sh.clamp(0.0, 2.0);
        }
        if let Some(sh) = self.lab_sharpe_2x_cost.filter(|v| v.is_finite()) {
            s += 0.5 * sh.clamp(0.0, 2.0);
        }
        if let Some(p) = self.lab_deflated_p.filter(|v| v.is_finite()) {
            s += p.clamp(0.0, 1.0);
        }
        let mut s = s / (1.0 + self.failed as f64);
        if self.forward_below() {
            s *= FORWARD_BELOW_FACTOR;
        }
        Some(s)
    }

    /// Its forward return is below its backtest's band after enough days.
    pub fn forward_below(&self) -> bool {
        self.forward.as_ref().is_some_and(|f| f.below_band())
    }

    /// The forward record in a few words, when there is one.
    fn describe_forward(&self) -> Option<String> {
        let f = self.forward.as_ref()?;
        let days = f.days.max(0.0).floor() as i64;
        let d = if days == 1 { "1 day".to_string() } else { format!("{days} days") };
        let ret = f.return_pct.filter(|r| r.is_finite()).map(|r| format!(" at {r:+.2} %")).unwrap_or_default();
        let band = match (f.band_low_pct, f.band_high_pct) {
            (Some(lo), Some(hi)) if lo.is_finite() && hi.is_finite() => format!(" ({lo:+.2} to {hi:+.2} %)"),
            _ => String::new(),
        };
        let tail = if !f.counts() {
            format!(", too early to count ({} needed)", crate::lab::FORWARD_MIN_DAYS as i64)
        } else if f.below_band() {
            format!(", below its backtest's range{band}, so its score is halved")
        } else if f.above_band() {
            format!(", above its backtest's range{band}")
        } else if f.has_band() {
            format!(", inside its backtest's range{band}")
        } else {
            ", no backtest range to compare with".into()
        };
        Some(format!("lab paper book {d}{ret}{tail}"))
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
            let over = match (self.lab_deflated_p, self.lab_variants) {
                (Some(_), Some(n)) => format!(" over {n} variants"),
                _ => String::new(),
            };
            let cost = self.lab_sharpe_2x_cost.map(|c| format!(", Sharpe {c:.2} with costs doubled")).unwrap_or_default();
            parts.push(format!("lab out-of-sample Sharpe {sh:.2}{p}{over}{cost}"));
        }
        if let Some(f) = self.describe_forward() {
            parts.push(f);
        }
        parts.join(", ")
    }

    /// What the evidence does not prove, so that a pick is never presented
    /// as a proven edge when it is not. `None` only for a strategy cleared
    /// for live (every gate green, deflation included).
    pub fn caveat(&self) -> Option<String> {
        let forward = self
            .forward_below()
            .then_some("its forward record is below what its backtest led us to expect, so it is ranked lower");
        let joined = |base: Option<String>| -> Option<String> {
            match (base, forward) {
                (Some(b), Some(f)) => Some(format!("{b}; also, {f}")),
                (Some(b), None) => Some(b),
                (None, Some(f)) => Some(f.to_string()),
                (None, None) => None,
            }
        };
        if self.live_ready {
            return joined(self.lab_caveat.clone());
        }
        let base = match (self.lab, self.lab_deflated_p) {
            (_, Some(p)) if p <= DEFLATION_PASS => format!(
                "it fails the deflation test (deflated p {p:.2}, {DEFLATION_PASS} needed), so it is picked as the best available evidence, not as a proven edge"
            ),
            (true, None) => "its lab report gives no deflated Sharpe, so it is picked as the best available evidence, not as a proven edge".into(),
            _ => "its edge is not proven: not every gate is green, so it is picked as the best available evidence".into(),
        };
        joined(Some(match &self.lab_caveat {
            Some(c) => format!("{base}; also, {c}"),
            None => base,
        }))
    }

    /// One plain sentence on why auto picked it. `rank` 0 is the best.
    pub fn auto_why(&self, rank: usize, candidates: usize) -> String {
        let place = if candidates == 1 {
            "the only strategy it could run here".to_string()
        } else if rank == 0 {
            format!("the best evidence of the {candidates} strategies it could run here")
        } else {
            format!("number {} of {candidates} by evidence", rank + 1)
        };
        let mut s = format!("Auto pick, {place} ({})", self.describe());
        if let Some(c) = self.caveat() {
            s.push_str(&format!(": {c}"));
        }
        s
    }
}

pub(super) fn usd(x: f64) -> String {
    let cents = (x.abs() * 100.0).round() as u128;
    // A loss that rounds to nothing is "$0.00", not "-$0.00".
    let neg = x < 0.0 && cents > 0;
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

pub(super) fn pct(x: f64) -> String {
    // Anything that rounds to zero is "0", never "-0".
    let x = if x.abs() < 0.005 { 0.0 } else { x };
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

fn asset_words(v: Venue) -> &'static str {
    match v {
        Venue::Alpaca => "US shares",
        Venue::Crypto => "crypto",
        Venue::Polymarket => "prediction markets",
    }
}

/// How an asset class is written in a portfolio's records.
fn class_key(v: Venue) -> &'static str {
    match v {
        Venue::Alpaca => "alpaca",
        Venue::Crypto => "crypto",
        Venue::Polymarket => "polymarket",
    }
}

/// An asset class as a heading: "Crypto", "US shares".
fn class_label(v: Venue) -> &'static str {
    match v {
        Venue::Alpaca => "US shares",
        Venue::Crypto => "Crypto",
        Venue::Polymarket => "Prediction markets",
    }
}

/// The engine venue an autopilot trades on: its asset class, else what its
/// venue implies.
fn config_venue(cfg: &AutopilotConfig) -> Option<Venue> {
    cfg.asset_class.or_else(|| CostVenue::parse(&cfg.venue).map(engine_venue))
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

/// The lab books of one autopilot, rebalanced as one netted book. A
/// portfolio has one group per asset class.
pub(super) struct LabGroup {
    pub ap: usize,
    /// The asset class, for a portfolio's group; `None` for an autopilot of
    /// one class.
    pub class: Option<Venue>,
    pub running: bool,
    /// The autopilot's equity times the lab sleeves' combined weight.
    pub capital: f64,
    /// Every lab sleeve (dropped ones too, at scale 0) and its share of
    /// `capital`: its weight over the lab sleeves' combined weight.
    pub members: Vec<(String, f64)>,
    /// Markets the autopilot owns.
    pub owned: HashSet<String>,
}

/// Net several lab books into one target. `books` are (sleeve id, scale,
/// target weights per coin); a book's weights are scaled by its share of the
/// group. Returns the combined weight per coin and, per coin, each book's
/// share of that combined weight (adding up to 1). Weights are long-only:
/// a negative or non-finite weight counts as zero, as in `lab::rebalance`.
pub fn net_lab_targets(books: &[(String, f64, &BTreeMap<String, f64>)]) -> (BTreeMap<String, f64>, BTreeMap<String, BTreeMap<String, f64>>) {
    let mut parts: BTreeMap<String, BTreeMap<String, f64>> = BTreeMap::new();
    for (sid, scale, weights) in books {
        if !scale.is_finite() || *scale <= 0.0 {
            continue;
        }
        for (coin, w) in weights.iter() {
            let w = if w.is_finite() { w.max(0.0) } else { 0.0 };
            if w > 0.0 {
                *parts.entry(coin.clone()).or_default().entry(sid.clone()).or_insert(0.0) += scale * w;
            }
        }
    }
    let mut combined = BTreeMap::new();
    let mut shares = BTreeMap::new();
    for (coin, by) in parts {
        let total: f64 = by.values().sum();
        if total <= 0.0 {
            continue;
        }
        combined.insert(coin.clone(), total);
        shares.insert(coin, by.into_iter().map(|(k, v)| (k, v / total)).collect());
    }
    (combined, shares)
}

impl Engine {
    fn ap_index(&self, id: &str) -> Option<usize> {
        self.autopilots.iter().position(|a| a.config.id == id)
    }

    /// The active autopilots that run this strategy. Several may: each
    /// trades it in its own book.
    fn aps_of_strategy(&self, sid: &str) -> Vec<usize> {
        (0..self.autopilots.len()).filter(|&i| self.autopilots[i].is_active() && self.autopilots[i].sleeve(sid).is_some()).collect()
    }

    /// The active autopilot whose book this is.
    fn ap_of_book(&self, book: &str) -> Option<usize> {
        if book.is_empty() {
            return None;
        }
        self.autopilots.iter().position(|a| a.is_active() && a.config.id == book)
    }

    fn ap_mark(&self, market: &str, avg: f64) -> f64 {
        let px = self.price_of(market);
        if px > 0.0 { px } else { avg }
    }

    /// The position the autopilot holds in `market`, in its own book.
    fn ap_position(&self, ap: &Autopilot, market: &str) -> Option<&super::PositionInternal> {
        self.positions.get(&super::pos_key(&ap.config.id, market))
    }

    /// Unrealised P&L of what it owns, or of one sleeve's share of it.
    fn ap_unrealized(&self, ap: &Autopilot, sleeve: Option<&str>) -> f64 {
        ap.owned
            .keys()
            .filter_map(|m| {
                let p = self.ap_position(ap, m)?;
                let share = sleeve.map_or(1.0, |s| ap.share(m, s));
                Some((self.ap_mark(m, p.avg_price) - p.avg_price) * p.qty * share)
            })
            .sum()
    }

    /// Gross notional at the mark of what it owns, or of one sleeve's share.
    fn ap_gross(&self, ap: &Autopilot, sleeve: Option<&str>) -> f64 {
        ap.owned
            .keys()
            .filter_map(|m| {
                let p = self.ap_position(ap, m)?;
                let share = sleeve.map_or(1.0, |s| ap.share(m, s));
                Some((p.qty * self.ap_mark(m, p.avg_price)).abs() * share)
            })
            .sum()
    }

    /// Notional of entries sent to a venue (demo or live) for the
    /// autopilot's book that have not filled yet. They become positions when
    /// the venue says so; until then they still use up room, or every signal
    /// in the meantime would be sized from the same budget again.
    fn ap_pending(&self, ap: &Autopilot, sleeve: Option<&str>) -> f64 {
        self.inflight
            .values()
            .filter(|f| f.book == ap.config.id)
            .filter(|f| sleeve.is_none_or(|s| s == f.strategy_id))
            .filter(|f| ap.sleeves.iter().any(|s| s.strategy_id == f.strategy_id && s.markets.contains(&f.market_id)))
            .filter(|f| {
                // An entry, or the rest of one: not an exit of what is held.
                let buy = f.side == crate::connectors::Side::Buy;
                self.ap_position(ap, &f.market_id).is_none_or(|p| p.qty.abs() < 1e-12 || (p.qty > 0.0) == buy)
            })
            .map(|f| {
                let left = (f.qty - f.booked_qty).max(0.0);
                let px = self.price_of(&f.market_id);
                left * if px > 0.0 { px } else { f.arrival }
            })
            .sum()
    }

    /// The equity of the autopilot at this index.
    pub(super) fn autopilot_equity(&self, i: usize) -> f64 {
        self.ap_equity(&self.autopilots[i])
    }

    /// The BTC/USD price to hold an autopilot against: on its own venue when
    /// that venue lists BTC, else any priced BTC/USD market.
    fn ap_btc_price(&self, ap: &Autopilot) -> Option<f64> {
        // A portfolio's crypto is priced by the crypto feeds.
        let venue = if ap.config.portfolio { Some(Venue::Crypto) } else { config_venue(&ap.config) };
        let btc = |m: &&super::Market| m.symbol == "BTC/USD" && m.price > 0.0 && m.price.is_finite();
        self.markets
            .iter()
            .filter(btc)
            .find(|m| Some(m.venue) == venue)
            .or_else(|| self.markets.iter().find(btc))
            .map(|m| m.price)
    }

    /// Buy-and-hold BTC over the autopilot's run, in %.
    fn ap_btc_return_pct(&self, ap: &Autopilot) -> Option<f64> {
        let p0 = ap.btc_start.filter(|p| *p > 0.0)?;
        let p1 = if ap.is_active() { self.ap_btc_price(ap) } else { ap.btc_end }?;
        Some((p1 / p0 - 1.0) * 100.0)
    }

    fn ap_equity(&self, ap: &Autopilot) -> f64 {
        ap.start_capital + ap.realized - ap.fees + ap.released + self.ap_unrealized(ap, None)
    }

    /// The SPY price, when it comes from a real feed.
    pub(super) fn ap_spy_price(&self) -> Option<f64> {
        self.markets
            .iter()
            .find(|m| m.id == SPY_ID && m.price > 0.0 && m.price.is_finite() && self.real_ids.contains(&m.id))
            .map(|m| m.price)
    }

    /// Is it held against SPY (an autopilot of US shares)?
    fn ap_wants_spy(&self, ap: &Autopilot) -> bool {
        config_venue(&ap.config) == Some(Venue::Alpaca)
    }

    /// The candle price of a benchmark at `t`: the close of the last candle
    /// that opened at or before it, else the open of the first one after,
    /// within a day and a half. With the time of that candle.
    fn bench_candle(&self, btc: bool, t: i64) -> Option<(f64, i64)> {
        let ids: Vec<String> = if btc {
            self.markets.iter().filter(|m| m.symbol == BTC_SYMBOL).map(|m| m.id.clone()).collect()
        } else {
            vec![SPY_ID.to_string()]
        };
        let mut best: Option<(f64, i64, i64)> = None; // (price, ts, distance)
        for id in &ids {
            let Some(bars) = self.ohlc.get(id) else { continue };
            let before = bars.iter().rev().find(|b| b.ts <= t && b.close > 0.0).map(|b| (b.close, b.ts, t - b.ts));
            let after = bars.iter().find(|b| b.ts > t && b.open > 0.0).map(|b| (b.open, b.ts, b.ts - t));
            for c in [before, after].into_iter().flatten() {
                if c.2 <= BENCH_CANDLE_TOLERANCE_MS && best.is_none_or(|b| c.2 < b.2) {
                    best = Some(c);
                }
            }
        }
        best.map(|b| (b.0, b.1))
    }

    /// Fill in a benchmark start an autopilot does not have (one saved
    /// before the field existed, or started before any price was known):
    /// from the nearest candle at its start time, else, once
    /// [`BENCH_WAIT_MS`] passed without one, from the price now, and its
    /// status says so. A stopped one is only filled from candles, start and
    /// end, never guessed.
    pub(super) fn ap_bench_backfill(&mut self, i: usize, now: i64) {
        let ap = &self.autopilots[i];
        let need_btc = ap.btc_start.is_none();
        let need_spy = ap.spy_start.is_none() && self.ap_wants_spy(ap);
        if !need_btc && !need_spy {
            return;
        }
        let active = ap.is_active();
        let started = ap.started_ms;
        let stopped = ap.stopped_ms;
        let btc_now = self.ap_btc_price(ap);
        let spy_now = self.ap_spy_price();
        let wait_since = *self.autopilots[i].bench_wait_ms.get_or_insert(now);
        let waited = now - wait_since >= BENCH_WAIT_MS;
        for (btc, need) in [(true, need_btc), (false, need_spy)] {
            if !need {
                continue;
            }
            let sym = if btc { "BTC" } else { "SPY" };
            let candle = self.bench_candle(btc, started);
            let end = stopped.and_then(|t| self.bench_candle(btc, t)).map(|c| c.0);
            let label = self.autopilots[i].label();
            let ap = &mut self.autopilots[i];
            let (start, from, stop_px) =
                if btc { (&mut ap.btc_start, &mut ap.btc_from_ms, &mut ap.btc_end) } else { (&mut ap.spy_start, &mut ap.spy_from_ms, &mut ap.spy_end) };
            let note = if let Some((px, ts)) = candle {
                if !active && end.is_none() && stop_px.is_none() {
                    continue;
                }
                *start = Some(px);
                if !active && stop_px.is_none() {
                    *stop_px = end;
                }
                format!("{sym} at its start is the price of the candle of {}, filled in after the fact.", when(ts))
            } else if active && waited {
                let Some(px) = (if btc { btc_now } else { spy_now }) else { continue };
                *start = Some(px);
                *from = Some(now);
                format!(
                    "No {sym} price or candle from its start ({}) is known, so its {sym} comparison starts {}, not at its start.",
                    when(started),
                    when(now)
                )
            } else {
                continue;
            };
            ap.bench_notes.push(note.clone());
            self.log(JournalKind::System, format!("{label}: {note}"), None, None);
        }
    }

    /// What it is held against, and how that did over the same period.
    /// `equity` is its equity now; when the comparison starts after its
    /// start, its own return is measured from the same moment.
    fn ap_benchmark(&self, ap: &Autopilot, equity: f64) -> Option<BenchmarkStatus> {
        if ap.config.portfolio {
            return self.ap_blend_status(ap, equity);
        }
        let active = ap.is_active();
        let (symbol, ret, from) = if self.ap_wants_spy(ap) {
            ("SPY", leg_return(ap.spy_start, if active { self.ap_spy_price() } else { ap.spy_end }), ap.spy_from_ms)
        } else if config_venue(&ap.config) == Some(Venue::Crypto) {
            (BTC_SYMBOL, self.ap_btc_return_pct(ap), ap.btc_from_ms)
        } else {
            return None;
        };
        let base = match from {
            Some(t) => ap.history.iter().find(|h| h.0 >= t).map(|h| h.1).unwrap_or(equity),
            None => ap.start_capital,
        };
        let own = if base > 0.0 { (equity / base - 1.0) * 100.0 } else { 0.0 };
        let name = format!("{} buy and hold", symbol.split('/').next().unwrap_or(symbol));
        let note = (!ap.bench_notes.is_empty()).then(|| ap.bench_notes.join(" "));
        Some(BenchmarkStatus {
            symbol: symbol.to_string(),
            name,
            return_pct: ret,
            excess_pct: ret.map(|r| own - r),
            from_ms: from,
            note,
            legs: Vec::new(),
        })
    }

    /// The names of the active autopilots that run this strategy, if any do.
    pub(super) fn autopilot_claimant(&self, sid: &str) -> Option<String> {
        let names: Vec<String> =
            self.aps_of_strategy(sid).into_iter().map(|i| format!("\"{}\"", self.autopilots[i].config.name)).collect();
        (!names.is_empty()).then(|| names.join(", "))
    }

    /// May this strategy open a position in this market for `book` now? In
    /// an autopilot's book only on its own sleeve's markets and only while
    /// the autopilot runs. The main book is open to every strategy no
    /// autopilot runs: the books are separate, so nothing is reserved.
    pub(super) fn autopilot_entry_allowed(&self, book: &str, sid: &str, market: &str) -> bool {
        if book.is_empty() {
            return self.aps_of_strategy(sid).is_empty();
        }
        let Some(i) = self.ap_of_book(book) else { return false };
        let ap = &self.autopilots[i];
        let live_ok = ap.config.mode != AutopilotMode::Live || config_venue(&ap.config).is_some_and(|v| self.live_routable(v));
        ap.state == AutopilotState::Running && live_ok && ap.sleeve(sid).is_some_and(|s| s.markets.iter().any(|m| m == market))
    }

    /// Sizing for an entry by a strategy in an autopilot's book.
    pub(super) fn autopilot_sizing(&self, book: &str, sid: &str) -> Option<SleeveSizing> {
        let ap = &self.autopilots[self.ap_of_book(book)?];
        let s = ap.sleeve(sid)?;
        let equity = self.ap_equity(ap).max(0.0);
        let capital = equity * s.weight;
        let used = self.ap_gross(ap, Some(sid)) + self.ap_pending(ap, Some(sid));
        let used_all = self.ap_gross(ap, None) + self.ap_pending(ap, None);
        let room = (capital - used).min(equity - used_all).max(0.0);
        Some(SleeveSizing { capital, slots: s.markets.len().max(1) as f64, equity, room })
    }

    /// The route for an order in an autopilot's book: the autopilot's mode
    /// decides, never the strategy's own switch. `None` for the main book.
    pub(super) fn autopilot_route(&self, book: &str) -> Option<RouteIntent> {
        self.ap_of_book(book).map(|i| self.autopilots[i].config.mode.route_intent())
    }

    /// The lab books of the autopilot at index `i`, as netted groups: one
    /// for an autopilot of one asset class, one per class for a portfolio
    /// (crypto and US shares rebalance on their own clocks: shares only in
    /// the regular session). Empty when it is not active or runs no lab book.
    pub(super) fn autopilot_lab_groups(&self, i: usize) -> Vec<LabGroup> {
        let ap = &self.autopilots[i];
        if !ap.is_active() {
            return Vec::new();
        }
        let classes: Vec<Option<Venue>> =
            if ap.config.portfolio { PORTFOLIO_CLASSES.iter().copied().map(Some).collect() } else { vec![None] };
        let equity = self.ap_equity(ap).max(0.0);
        let mut out = Vec::new();
        for class in classes {
            let labs: Vec<&Sleeve> = ap
                .sleeves
                .iter()
                .filter(|s| self.is_lab_book(&s.strategy_id))
                .filter(|s| class.is_none_or(|c| self.strategy_class(&s.strategy_id) == Some(c)))
                .collect();
            if labs.is_empty() {
                continue;
            }
            let total: f64 = labs.iter().map(|s| s.weight.max(0.0)).sum();
            // A portfolio never holds more than its equity across both
            // classes: when the split moves while the other class waits for
            // its session to sell, this class buys only into what is free.
            let capital = match class {
                Some(c) => (equity * total).min((equity - self.ap_class_gross(ap, |v| v != c)).max(0.0)),
                None => equity * total,
            };
            out.push(LabGroup {
                ap: i,
                class,
                running: ap.state == AutopilotState::Running,
                capital,
                members: labs
                    .iter()
                    .map(|s| (s.strategy_id.clone(), if total > 0.0 { s.weight.max(0.0) / total } else { 0.0 }))
                    .collect(),
                owned: ap.owned.keys().cloned().collect(),
            });
        }
        out
    }

    /// The asset class a strategy trades.
    fn strategy_class(&self, sid: &str) -> Option<Venue> {
        self.strategies.iter().find(|s| s.id == sid).map(|s| s.venue_class)
    }

    /// The asset class (engine venue) of a market.
    fn market_class(&self, market: &str) -> Option<Venue> {
        self.markets.iter().find(|m| m.id == market).map(|m| m.venue)
    }

    /// Gross notional at the mark of what it owns in the classes `pick`
    /// accepts, plus its orders for them still at the venue.
    fn ap_class_gross(&self, ap: &Autopilot, pick: impl Fn(Venue) -> bool) -> f64 {
        let held: f64 = ap
            .owned
            .keys()
            .filter(|m| self.market_class(m).is_some_and(&pick))
            .filter_map(|m| {
                let p = self.ap_position(ap, m)?;
                Some((p.qty * self.ap_mark(m, p.avg_price)).abs())
            })
            .sum();
        let pending: f64 = self
            .inflight
            .values()
            .filter(|f| f.book == ap.config.id && self.market_class(&f.market_id).is_some_and(&pick))
            .filter(|f| {
                let buy = f.side == crate::connectors::Side::Buy;
                self.ap_position(ap, &f.market_id).is_none_or(|p| p.qty.abs() < 1e-12 || (p.qty > 0.0) == buy)
            })
            .map(|f| {
                let left = (f.qty - f.booked_qty).max(0.0);
                let px = self.price_of(&f.market_id);
                left * if px > 0.0 { px } else { f.arrival }
            })
            .sum();
        held + pending
    }

    fn is_lab_book(&self, sid: &str) -> bool {
        self.strategies.iter().any(|s| s.id == sid && s.kind == StrategyKind::LabTargets)
    }

    /// A netted rebalance is about to trade toward new targets. Each sleeve's
    /// share of a market it holds moves to its share of the new target; the
    /// unrealised P&L the position carries so far stays with the sleeves that
    /// earned it (booked across at the mark, adding up to zero), so a share
    /// change never moves P&L from one sleeve to another. A market the new
    /// target leaves out keeps its old shares until it is sold: the sale's
    /// result belongs to the sleeves that held it.
    pub(super) fn autopilot_lab_retarget(
        &mut self,
        ap_i: usize,
        targets: BTreeMap<String, f64>,
        shares: BTreeMap<String, BTreeMap<String, f64>>,
        cash_note: Option<String>,
        class: Option<Venue>,
    ) {
        // A portfolio's group sets only its own class's part of the target.
        let (targets, cash_note) = match class {
            None => (targets, cash_note),
            Some(c) => {
                let mut all: BTreeMap<String, f64> = self.autopilots[ap_i]
                    .lab_target
                    .iter()
                    .filter(|(m, _)| self.market_class(m) != Some(c))
                    .map(|(m, w)| (m.clone(), *w))
                    .collect();
                all.extend(targets);
                let notes = &mut self.autopilots[ap_i].class_notes;
                match cash_note {
                    Some(n) => notes.insert(class_key(c).to_string(), n),
                    None => notes.remove(class_key(c)),
                };
                let joined: Vec<String> = PORTFOLIO_CLASSES
                    .iter()
                    .filter_map(|v| notes.get(class_key(*v)).map(|n| format!("{}: {n}", asset_words(*v))))
                    .collect();
                (all, (!joined.is_empty()).then(|| joined.join("; ")))
            }
        };
        let marks: BTreeMap<String, f64> = self.autopilots[ap_i]
            .owned
            .keys()
            .filter_map(|m| {
                let p = self.ap_position(&self.autopilots[ap_i], m)?;
                Some((m.clone(), (self.ap_mark(m, p.avg_price) - p.avg_price) * p.qty))
            })
            .collect();
        let ap = &mut self.autopilots[ap_i];
        for (m, new) in &shares {
            if let Some(unreal) = marks.get(m) {
                let sids: Vec<String> = ap.sleeves.iter().map(|s| s.strategy_id.clone()).collect();
                for sid in sids {
                    let delta = ap.share(m, &sid) - new.get(&sid).copied().unwrap_or(0.0);
                    if delta.abs() > 1e-12 {
                        if let Some(s) = ap.sleeve_mut(&sid) {
                            s.realized += unreal * delta;
                        }
                    }
                }
            }
            ap.shares.insert(m.clone(), new.clone());
        }
        ap.lab_target = targets;
        ap.cash_note = cash_note;
    }

    /// Book a fill in an autopilot's book to that autopilot. Called by
    /// `settle_fill_on` for every fill, paper, demo or live; a fill in the
    /// main book (`book` empty) is no autopilot's. `existed` is whether the
    /// book had a position in the market before this fill. Returns the
    /// autopilot it was booked to, for the trade alert.
    ///
    /// The book says whose it is, so a fill can never land in another
    /// autopilot's P&L, whichever strategy sent it. A stopped autopilot still
    /// books what its own orders fill after the stop (an order at the venue
    /// can fill until it is cancelled); a position it handed out when it
    /// stopped without flattening is no longer its, and closing it later
    /// books nothing to it (its P&L was counted at the stop).
    #[allow(clippy::too_many_arguments)]
    pub(super) fn autopilot_on_fill(
        &mut self,
        book: &str,
        sid: &str,
        market: &str,
        realized: f64,
        fee: f64,
        existed: bool,
        open_after: bool,
    ) -> Option<usize> {
        if book.is_empty() {
            return None;
        }
        let i = self.autopilots.iter().position(|a| a.config.id == book)?;
        if !self.autopilots[i].is_active() && !self.autopilots[i].owned.contains_key(market) && existed {
            return None;
        }
        // A late fill on an autopilot that stopped and left its positions open
        // is handed out the same way: its P&L counted at the mark now, the
        // position no longer its own. Kept, it would hold the autopilot open
        // ("still closing") forever with nothing that ever closes it.
        let order = self.fill_order.clone();
        let hand_out = open_after && !self.autopilots[i].is_active() && !self.autopilots[i].flatten_at_stop;
        let unreal = if hand_out {
            self.positions
                .get(&super::pos_key(book, market))
                .map(|p| (self.ap_mark(market, p.avg_price) - p.avg_price) * p.qty)
                .unwrap_or(0.0)
        } else {
            0.0
        };
        let ap = &mut self.autopilots[i];
        let owner = ap.owned.get(market).cloned().unwrap_or_else(|| sid.to_string());
        let fee = fee.max(0.0);
        ap.realized += realized;
        ap.fees += fee;
        // A closed trade: P&L realised, or a position closed out entirely
        // (a close at exactly its entry price realises nothing and is still a trade).
        let closed = realized != 0.0 || (existed && !open_after);
        let closed = ap.count_fill(order.as_deref(), closed);
        // Netted lab books split it by their shares of the market.
        ap.book_split(market, &owner, realized, fee, closed);
        if hand_out {
            ap.released += unreal;
            ap.release(market);
            let msg = format!(
                "{}: an order still at the venue filled after it stopped without closing its positions; the position is left open like the others and its P&L counted at its price now.",
                ap.label()
            );
            self.log(JournalKind::Risk, msg, Some(owner), Some(market.to_string()));
        } else if open_after {
            ap.owned.insert(market.to_string(), owner);
        } else {
            ap.release(market);
        }
        Some(i)
    }

    /// The trade alert for one fill booked to autopilot `i`: one line of the
    /// table the sender builds from the fills that arrive together.
    #[allow(clippy::too_many_arguments)]
    pub(super) fn autopilot_trade_alert(
        &mut self,
        i: usize,
        sid: &str,
        symbol: &str,
        buy: bool,
        qty: f64,
        price: f64,
        fee: f64,
        realized: f64,
    ) {
        let Some(ap) = self.autopilots.get(i) else { return };
        let rebalance = self.strategies.iter().any(|s| s.id == sid && s.kind == StrategyKind::LabTargets);
        let mode = match ap.config.mode {
            AutopilotMode::Live => "live",
            AutopilotMode::Demo => "demo",
            AutopilotMode::Paper => "paper",
        };
        let line = crate::alerts::TradeLine {
            book: ap.config.name.clone(),
            buy,
            symbol: symbol.split('/').next().unwrap_or(symbol).to_string(),
            qty,
            price,
            fee: fee.max(0.0),
            realized,
            rebalance,
            mode: mode.into(),
        };
        let key = format!("fill:{}:{symbol}:{}:{qty}", ap.config.id, self.now());
        self.alert_event(crate::alerts::AlertEvent::trade(key, line));
    }

    /// A fee that reached the engine after its fill: Alpaca posts crypto fees
    /// at the end of the day (`engine::alpaca_fees`). The autopilot that owns
    /// the market pays it, or else the one whose sleeve `sid` trades it (the
    /// round trip may be closed, or the autopilot stopped, by then): a fee
    /// is a cost of the trade that caused it, whenever it arrives.
    /// `open_after` is whether the position is still open once the fee's
    /// coins left it. Returns the autopilot's label, for the journal.
    pub(super) fn autopilot_on_late_fee(&mut self, book: &str, sid: &str, market: &str, fee: f64, open_after: bool) -> Option<String> {
        if book.is_empty() {
            return None;
        }
        let i = self.autopilots.iter().position(|a| a.config.id == book)?;
        let ap = &mut self.autopilots[i];
        let owner = ap.owned.get(market).cloned().unwrap_or_else(|| sid.to_string());
        let fee = fee.max(0.0);
        ap.fees += fee;
        ap.book_split(market, &owner, 0.0, fee, false);
        if !open_after {
            ap.release(market);
        }
        Some(ap.label())
    }

    /// Reconciliation set a position to what the venue holds. When an
    /// autopilot owns it, the difference is booked to that autopilot: the
    /// quantity follows the venue, and the P&L the changed part carried is
    /// booked as realised at the mark (and so is a change of the average
    /// price the venue reported). The autopilot's equity is the same just
    /// before and just after, so a correction can never lift it over a stop,
    /// or drop a loss its stop rules were about to see. Journaled with the
    /// numbers. `before` and `after` are (quantity, average price).
    pub(super) fn autopilot_on_correction(&mut self, book: &str, market: &str, before: (f64, f64), after: (f64, f64), venue: &str) {
        if book.is_empty() {
            return;
        }
        let Some(i) = self.autopilots.iter().position(|a| a.config.id == book && a.owned.contains_key(market)) else { return };
        let mark = self.ap_mark(market, before.1);
        let open_after = after.0.abs() > 1e-12;
        let unreal = |(q, avg): (f64, f64)| if q.abs() > 1e-12 { (mark - avg) * q } else { 0.0 };
        let booked = unreal(before) - unreal(after);
        let symbol = self.markets.iter().find(|m| m.id == market).map(|m| m.symbol.clone()).unwrap_or_else(|| market.to_string());
        let ap = &mut self.autopilots[i];
        let owner = ap.owned.get(market).cloned().unwrap_or_default();
        ap.realized += booked;
        ap.book_split(market, &owner, booked, 0.0, false);
        if !open_after {
            ap.release(market);
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
        if cfg.portfolio {
            self.portfolio_preflight(&mut cfg)?;
        }
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
        // Its book must start empty: positions a stopped autopilot under the
        // same id left open would otherwise be mixed into the new one.
        if self.positions.values().any(|p| p.book == cfg.id) {
            return Err(format!(
                "The book \"{}\" still holds positions an earlier autopilot left open when it stopped. Close them on the Positions page first, or give the new one another id.",
                cfg.id
            ));
        }

        let Some(mut cv) = CostVenue::parse(&cfg.venue) else {
            return Err(format!("Unknown venue \"{}\". Use one from config/costs.json, for example kraken or alpaca.", cfg.venue));
        };
        // Saved under its canonical id: the live cash check below adds up
        // other autopilots by venue, and " Kraken" must be the same as "kraken".
        cfg.venue = cv.id().to_string();
        let venue = cfg.asset_class.unwrap_or_else(|| engine_venue(cv));
        // Crypto is the one asset class another venue's book can carry
        // (crypto on the Alpaca paper account); shares are only on Alpaca.
        if venue != Venue::Crypto && venue != engine_venue(cv) {
            return Err(format!("{} does not trade {} here.", venue_label(cv), asset_words(venue)));
        }
        if cfg.mode == AutopilotMode::Demo && venue == Venue::Crypto {
            // Crypto demo orders go to the exchange whose demo keys are in
            // Settings (or to the Alpaca paper account), whatever the live
            // exchange is. That venue is the autopilot's venue, so every
            // label names where it trades.
            if !self.demo_venues.contains(&venue) {
                return Err(format!(
                    "A demo autopilot needs demo keys for {}: add Bybit, OKX or Binance demo keys in Settings first, or use Alpaca paper (PYTHIA_DEMO_EXCHANGE=alpaca). docs/DEMO.md says how.",
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
        } else if venue == Venue::Crypto && cv != self.crypto_venue && engine_venue(cv) == Venue::Crypto {
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
        if venue == Venue::Crypto && engine_venue(cv) != Venue::Crypto && cfg.mode != AutopilotMode::Demo {
            return Err(format!(
                "Crypto on {} is only the demo route here (the Alpaca paper account). Paper and live crypto execute on {}, the exchange selected in Settings: pick {}.",
                venue_label(cv),
                venue_label(self.crypto_venue),
                self.crypto_venue.id()
            ));
        }
        if cfg.mode == AutopilotMode::Demo && !self.demo_venues.contains(&venue) {
            return Err(format!(
                "A demo autopilot needs demo keys for {}: add {} in Settings first (docs/DEMO.md says how to get them).",
                venue_label(cv),
                if venue == Venue::Alpaca {
                    "Alpaca paper keys"
                } else {
                    "Bybit, OKX or Binance demo keys, or use Alpaca paper (PYTHIA_DEMO_EXCHANGE=alpaca)"
                }
            ));
        }
        if !cfg.portfolio {
            cfg.asset_class = Some(venue);
        }
        if self.limits.kill_switch {
            return Err("The kill switch is on, so every new entry would be refused. Release it first.".into());
        }

        // Every autopilot trades in its own book, so markets are never taken
        // by another one, and a strategy may run in several paper and demo
        // autopilots at once. A live autopilot keeps its strategies to itself.
        let busy = self.busy_strategies(cfg.mode, None);
        let taken: HashSet<String> = HashSet::new();

        let auto = cfg.sleeves.is_empty();
        let mut passed_over: Vec<String> = Vec::new();
        let mut split: Option<PortfolioPick> = None;
        let picks: Vec<(String, f64, String)> = if cfg.portfolio {
            let max = cfg.max_sleeves.unwrap_or(AUTO_MAX_SLEEVES);
            let mut pp = self.portfolio_pick(cfg.mode, &busy, &HashSet::new(), max, None)?;
            passed_over = std::mem::take(&mut pp.passed_over);
            let picks = std::mem::take(&mut pp.picks);
            split = Some(pp);
            picks
        } else if auto {
            let max = cfg.max_sleeves.unwrap_or(AUTO_MAX_SLEEVES);
            let (picks, over) = self.auto_pick(venue, cfg.mode, &busy, &taken, &HashSet::new(), max, false).map_err(|why| {
                // "alpaca" alone means US shares; crypto there is its own choice.
                if cfg.mode == AutopilotMode::Demo && venue == Venue::Alpaca && self.crypto_demo_on_alpaca() {
                    format!("{why} Crypto on the Alpaca paper account is a separate choice: pick Crypto (asset class \"crypto\").")
                } else {
                    why
                }
            })?;
            passed_over = over;
            picks
        } else {
            let mut out = Vec::new();
            for sl in &cfg.sleeves {
                let Some(s) = self.strategies.iter().find(|s| s.id == sl.strategy_id) else {
                    return Err(format!("There is no strategy \"{}\".", sl.strategy_id));
                };
                if let Some(why) = self.sleeve_block(s.id.as_str(), venue, cfg.mode, &busy, &HashSet::new()) {
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
                Want {
                    weight: *w,
                    whole: trades_as_set(s.kind),
                    net: s.kind == StrategyKind::LabTargets,
                    universe: self.sleeve_universe(s, cfg.mode),
                }
            })
            .collect();
        let assigned = assign_markets(&wants, &taken);
        let mut chosen: Vec<(String, f64, String, Vec<String>)> = Vec::new();
        for ((sid, w, why), markets) in picks.into_iter().zip(assigned) {
            if markets.is_empty() {
                let name = self.strategies.iter().find(|s| s.id == sid).map(|s| s.name.clone()).unwrap_or(sid);
                if auto {
                    passed_over.push(name);
                    continue;
                }
                return Err(format!(
                    "{name} has no market of its own left: every market it trades already belongs to another sleeve of this autopilot. One position per market in an autopilot's book means two of its strategies cannot hold the same coin; drop one of them, pick strategies on different markets, or run the other one in an autopilot of its own."
                ));
            }
            chosen.push((sid, w, why, markets));
        }
        if chosen.is_empty() {
            return Err("Auto found no strategy with a market of its own left in this autopilot.".into());
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
                .filter(|a| a.is_active() && a.config.mode == AutopilotMode::Live && CostVenue::parse(&a.config.venue) == Some(cv))
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
            // Paper autopilots share the one paper account: what the active
            // ones were given is not there to give again, or together they
            // would trade more than the account holds.
            let paper = self.equity();
            let committed: f64 =
                self.autopilots.iter().filter(|a| a.is_active() && a.config.mode == AutopilotMode::Paper).map(|a| a.start_capital).sum();
            let available = (paper - committed).max(0.0);
            if cfg.capital_usd > available + EPS {
                if committed > 0.0 {
                    return Err(format!(
                        "The paper account holds {}, of which {} is already given to other paper autopilots, so {} is left for this one.",
                        usd(paper),
                        usd(committed),
                        usd(available)
                    ));
                }
                return Err(format!("The paper account holds {}; a paper autopilot cannot trade more than that.", usd(paper)));
            }
        } else if cfg.mode == AutopilotMode::Demo && self.on_alpaca_paper_account(&cfg) {
            // Demo autopilots on the Alpaca paper account share it: together
            // they may not be given more than it holds.
            self.paper_account_room(None, cfg.capital_usd, &cash)?;
        }

        // Go.
        let labs = chosen.iter().filter(|c| self.is_lab_book(&c.0)).count();
        let mut sleeves = Vec::new();
        for (sid, w, why, markets) in chosen {
            let s = self.strategies.iter().find(|s| s.id == sid).expect("chosen strategies exist");
            let weight = w / total;
            let netted = if s.kind == StrategyKind::LabTargets && labs > 1 {
                format!(", netted per coin with the other {} lab book(s) into one position per coin", labs - 1)
            } else {
                String::new()
            };
            sleeves.push(Sleeve {
                strategy_id: sid.clone(),
                name: s.name.clone(),
                weight,
                why: format!("{why}; gets {:.0} % of the capital on {} market(s){netted}.", weight * 100.0, markets.len()),
                markets,
                realized: 0.0,
                fees: 0.0,
                trades: 0,
                prior_state: s.state,
                dropped_ms: None,
            });
        }
        // Re-picking is for autopilots whose strategies Pythia picks.
        cfg.repick_every_hours = match cfg.repick_every_hours {
            _ if !auto => None,
            None => Some(REPICK_DEFAULT_HOURS),
            Some(h) if h > 0.0 => Some(h),
            Some(_) => None,
        };
        let id = cfg.id.clone();
        let want_state = if cfg.mode == AutopilotMode::Live { StrategyState::Live } else { StrategyState::Paper };
        for sl in &sleeves {
            if self.strategies.iter().any(|s| s.id == sl.strategy_id && s.state != want_state) {
                self.apply_strategy_state(&sl.strategy_id, want_state);
            }
            // A lab book rebalances to its targets with the autopilot's money
            // now, not on its next signal.
            self.lab_done.remove(&super::pos_key(&id, &sl.strategy_id));
            self.lab_retry.remove(&super::pos_key(&id, &sl.strategy_id));
        }
        // Positions the sleeve strategies hold elsewhere (the main book,
        // another autopilot's book) stay where they are: this one starts
        // with an empty book of its own.
        let elsewhere: Vec<String> = {
            let mine: HashSet<&str> = sleeves.iter().map(|s| s.strategy_id.as_str()).collect();
            let mut v: Vec<String> = self
                .positions
                .values()
                .filter(|p| mine.contains(p.strategy_id.as_str()) && p.qty.abs() > 1e-12)
                .map(|p| p.symbol.clone())
                .collect();
            v.sort();
            v.dedup();
            v
        };
        let sharing: Vec<String> = sleeves
            .iter()
            .filter_map(|sl| self.autopilot_claimant(&sl.strategy_id).map(|who| format!("{} (also in {who})", sl.name)))
            .collect();

        let place = if cfg.portfolio { "crypto and US shares".to_string() } else { venue_label(cv).to_string() };
        let mut msg = format!(
            "Autopilot \"{}\" started in {} on {} with {}: {}.",
            cfg.name,
            cfg.mode.word(),
            place,
            usd(cfg.capital_usd),
            describe_rules(&cfg)
        );
        let started_alert = if sleeves.is_empty() {
            msg.clone()
        } else {
            let books: Vec<&str> = sleeves.iter().map(|s| s.name.as_str()).collect();
            format!("{msg} Books: {}.", books.join(", "))
        };
        if let Some(pp) = &split {
            msg.push_str(&format!(" A portfolio across asset classes, split by evidence: {}.", pp.split_words()));
            for (c, why) in &pp.empty {
                msg.push_str(&format!(
                    " Nothing goes to {} for now ({why}); a re-pick adds them once a book has evidence, never forced.",
                    asset_words(*c)
                ));
            }
            msg.push_str(" US shares rebalance only in the regular session; crypto at any time. It is held against a blend of BTC and SPY at the same split.");
        }
        for sl in &sleeves {
            msg.push_str(&format!(" {}: {}", sl.name, sl.why));
        }
        if !passed_over.is_empty() {
            msg.push_str(&format!(
                " Auto passed over {}: the markets they need already belong to a pick with better evidence in this autopilot (one position per market in its book).",
                passed_over.join(", ")
            ));
        }
        if let Some(h) = cfg.repick_every_hours {
            msg.push_str(&format!(
                " It re-runs the pick with fresh evidence every {} h; a change is netted in at the next rebalance, never sold off at once.",
                pct(h)
            ));
        }
        msg.push_str(" It trades in a book of its own: its cash, positions, fills, fees and P&L are its alone.");
        if !sharing.is_empty() {
            msg.push_str(&format!(
                " Also running in other autopilots, each in its own book: {}.",
                sharing.join(", ")
            ));
        }
        if !elsewhere.is_empty() {
            msg.push_str(&format!(
                " Its strategies already hold {} elsewhere; those positions stay where they are and are not counted here.",
                elsewhere.join(", ")
            ));
        }
        if cfg.mode == AutopilotMode::Demo {
            msg.push_str(" Orders go to the venue's demo account: virtual money through the real API, never in the tax record.");
            if venue == Venue::Crypto && self.crypto_demo_on_alpaca() {
                msg.push_str(" Crypto demo here is the Alpaca paper account");
                let missing = self.demo_not_listed_symbols();
                if missing.is_empty() {
                    msg.push('.');
                } else {
                    msg.push_str(&format!("; Alpaca does not list {}, so no sleeve trades them.", missing.join(", ")));
                }
            }
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
        {
            use crate::alerts::{card, AlertEvent, Row};
            let mut rows = vec![
                Row::new("Capital", card::usd(cfg.capital_usd)),
                Row::new("Mode", cfg.mode.word()),
                Row::new("Venue", place.clone()),
            ];
            if let Some(pp) = &split {
                rows.push(Row::new("Split", pp.split_words()));
            }
            let books: Vec<&str> = sleeves.iter().map(|s| s.name.as_str()).collect();
            if !books.is_empty() {
                rows.push(Row::new("Books", books.join(", ")));
            }
            let rules = describe_rules(&cfg);
            self.alert_event(
                AlertEvent::new(AlertKind::AutopilotStarted, format!("start:{id}:{now}"), started_alert)
                    .titled(format!("{} started", cfg.name))
                    .with_summary(format!("Rules: {rules}."))
                    .with_rows(rows),
            );
        }
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
            shares: BTreeMap::new(),
            lab_target: BTreeMap::new(),
            cash_note: None,
            last_pick_ms: Some(now),
            btc_start: None,
            btc_end: None,
            orders: 0,
            recent_orders: Vec::new(),
            spy_start: None,
            spy_end: None,
            btc_from_ms: None,
            spy_from_ms: None,
            bench_notes: Vec::new(),
            bench_wait_ms: None,
            blend: None,
            class_notes: BTreeMap::new(),
        });
        let i = self.autopilots.len() - 1;
        let x = self.autopilots[i].config.capital_usd;
        self.autopilots[i].start_capital = x;
        self.autopilots[i].peak_equity = x;
        self.autopilots[i].history.push((now, x));
        self.autopilots[i].btc_start = self.ap_btc_price(&self.autopilots[i]);
        if self.ap_wants_spy(&self.autopilots[i]) {
            self.autopilots[i].spy_start = self.ap_spy_price();
        }
        // A portfolio's blend starts at its class split, from the same
        // BTC and SPY starts (filled in later when no price is known yet).
        self.ap_blend_relink(i, now);
        Ok(id)
    }

    /// Strategies an autopilot in `mode` may not take because another active
    /// autopilot (other than `except`) runs them. Paper and demo autopilots
    /// share strategies freely, each trading them in its own book; a live
    /// autopilot keeps its strategies to itself and takes none another one
    /// runs, so real money never trades a strategy two ways at once.
    fn busy_strategies(&self, mode: AutopilotMode, except: Option<&str>) -> HashSet<String> {
        self.autopilots
            .iter()
            .filter(|a| a.is_active() && except.is_none_or(|x| a.config.id != x))
            .filter(|a| mode == AutopilotMode::Live || a.config.mode == AutopilotMode::Live)
            .flat_map(|a| a.sleeves.iter().map(|s| s.strategy_id.clone()))
            .collect()
    }

    /// Does an autopilot with this config trade on the Alpaca paper account?
    /// Demo on US shares does, and so does crypto demo when crypto demo
    /// orders go to Alpaca.
    pub(super) fn on_alpaca_paper_account(&self, cfg: &AutopilotConfig) -> bool {
        if cfg.mode != AutopilotMode::Demo {
            return false;
        }
        match config_venue(cfg) {
            Some(Venue::Alpaca) => true,
            Some(Venue::Crypto) => self.crypto_demo_on_alpaca(),
            _ => false,
        }
    }

    /// For hosts: does a start with this config, or a change of the amount
    /// of the autopilot `id`, have to read the Alpaca paper account's equity
    /// first (see [`VenueCash`])? The host reads it with no engine lock held
    /// and passes it in as `VenueCash::Read`.
    pub fn autopilot_needs_paper_equity(&self, cfg: Option<&AutopilotConfig>, id: Option<&str>) -> bool {
        match (cfg, id) {
            (Some(c), _) => self.on_alpaca_paper_account(c),
            (None, Some(id)) => self.autopilot_config(id).is_some_and(|c| self.on_alpaca_paper_account(&c)),
            _ => false,
        }
    }

    /// The amounts given to the active demo autopilots on the Alpaca paper
    /// account, other than `except`.
    fn paper_account_committed(&self, except: Option<&str>) -> f64 {
        self.autopilots
            .iter()
            .filter(|a| a.is_active() && except.is_none_or(|x| a.config.id != x))
            .filter(|a| self.on_alpaca_paper_account(&a.config))
            .map(|a| a.config.capital_usd)
            .sum()
    }

    /// Check that an amount `x` for this demo autopilot (`except`: its own
    /// id on a change) fits in the Alpaca paper account together with what
    /// the other demo autopilots there were given. `cash` is the account's
    /// equity as the host read it; not read means the host has no way to
    /// read it, and nothing is checked.
    fn paper_account_room(&self, except: Option<&str>, x: f64, cash: &VenueCash) -> Result<(), String> {
        let equity = match cash {
            VenueCash::NotRead => return Ok(()),
            VenueCash::Failed(why) => {
                return Err(format!(
                    "Could not read the Alpaca paper account ({why}), so the amount cannot be checked against what it holds. Try again in a moment."
                ))
            }
            VenueCash::Read(c) => *c,
        };
        let committed = self.paper_account_committed(except);
        let available = (equity - committed).max(0.0);
        if x > available + EPS {
            let others = if committed > 0.0 {
                format!(", of which {} is already given to the other demo autopilots on it", usd(committed))
            } else {
                String::new()
            };
            return Err(format!(
                "The Alpaca paper account holds {}{others}, so {} is left, not {}. Lower another autopilot's amount to make room, or give this one less.",
                usd(equity),
                usd(available),
                usd(x)
            ));
        }
        Ok(())
    }

    /// Stop an autopilot now. `flatten` overrides its `flattenOnStop`.
    pub fn autopilot_stop(&mut self, id: &str, flatten: Option<bool>) -> Result<(), String> {
        let Some(i) = self.ap_index(id) else { return Err(format!("There is no autopilot \"{id}\".")) };
        if !self.autopilots[i].is_active() {
            return Err(format!("{} is already stopped.", self.autopilots[i].label()));
        }
        let flatten = flatten.unwrap_or(self.autopilots[i].config.flatten_on_stop);
        let now = self.now();
        self.ap_halt(i, AutopilotState::Stopped, "stopped by you".into(), flatten, now, AlertKind::AutopilotStopped);
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

    /// The saved config of one autopilot, for a host that has to read the
    /// venue before a change (the free cash of a live one).
    pub fn autopilot_config(&self, id: &str) -> Option<AutopilotConfig> {
        self.ap_index(id).map(|i| self.autopilots[i].config.clone())
    }

    /// Change a running or paused autopilot in place: its name, strategies
    /// and weights (or the auto pick), stop rules, amount and pick settings.
    ///
    /// Nothing is sold to make the change. Positions stay where they are:
    /// lab books net their targets per coin, so a coin the new strategies
    /// also want is re-attributed to them at the next rebalance, which trades
    /// only the difference with the route's normal execution. A strategy
    /// taken out stays listed at weight zero while it still holds something
    /// or has a record; a lower amount brings the targets down at the next
    /// rebalance. The checks are the start's: the same validation, the
    /// confirmation for any live change and for a looser max-loss rule, a
    /// live amount never above the venue's free cash, a paper amount never
    /// above what the paper account has left. Journaled with what changed.
    /// Returns that sentence.
    pub fn autopilot_update(&mut self, id: &str, upd: AutopilotUpdate, confirm: bool, cash: VenueCash) -> Result<String, String> {
        let now = self.now();
        let Some(i) = self.ap_index(id) else { return Err(format!("There is no autopilot \"{id}\".")) };
        let label = self.autopilots[i].label();
        if !self.autopilots[i].is_active() {
            return Err(format!("{label} is stopped; start a new one instead."));
        }
        let old = self.autopilots[i].config.clone();
        if old.portfolio && upd.sleeves.as_ref().is_some_and(|s| !s.is_empty()) {
            return Err(format!("{label} is a portfolio: Pythia picks its lab books by evidence, class by class, so its strategies cannot be chosen by hand."));
        }
        let mut cfg = old.clone();
        if let Some(n) = &upd.name {
            let n = n.trim();
            cfg.name = if n.is_empty() { "Autopilot".into() } else { n.to_string() };
        }
        if let Some(x) = upd.capital_usd {
            cfg.capital_usd = x;
        }
        if let Some(s) = &upd.stop {
            cfg.stop = s.clone();
        }
        if let Some(f) = upd.flatten_on_stop {
            cfg.flatten_on_stop = f;
        }
        if let Some(s) = &upd.sleeves {
            cfg.sleeves = s.clone();
        }
        if upd.max_sleeves.is_some() {
            cfg.max_sleeves = upd.max_sleeves;
        }
        let auto = cfg.sleeves.is_empty();
        cfg.repick_every_hours = match upd.repick_every_hours {
            Some(h) => Some(h),
            None if !auto => None,
            None if old.sleeves.is_empty() => old.repick_every_hours.or(Some(0.0)),
            None => Some(REPICK_DEFAULT_HOURS),
        };
        validate(&cfg, now)?;
        cfg.repick_every_hours = cfg.repick_every_hours.filter(|h| auto && *h > 0.0);

        let re_sleeve = cfg.sleeves != old.sleeves || (auto && cfg.max_sleeves != old.max_sleeves);
        let capital_changed = (cfg.capital_usd - old.capital_usd).abs() > EPS;
        if cfg == old && !re_sleeve {
            return Err(format!("Nothing to change: {label} already runs like this."));
        }
        let live = cfg.mode == AutopilotMode::Live;
        let Some(venue) = config_venue(&cfg) else { return Err(format!("{label} has an unknown venue.")) };
        let cv = CostVenue::parse(&cfg.venue).unwrap_or(CostVenue::Kraken);

        // The live gate: the owner confirms every change, and a max-loss rule stays.
        if live {
            if !confirm {
                return Err("Live trades real money: type the confirmation to change it.".into());
            }
            if cfg.stop.max_loss_pct.is_none() && cfg.stop.max_loss_usd.is_none() {
                return Err("Live needs a max-loss rule, in % or in dollars, so there is always a level at which it stops.".into());
            }
            if re_sleeve || cfg.capital_usd > old.capital_usd + EPS {
                if !self.live.armed {
                    return Err("Live routing is not armed. Arm it on the Live page first; the autopilot never arms anything itself.".into());
                }
                if !self.live.venues.contains(&venue) {
                    return Err(format!("{} is not enabled for live routing. Enable it on the Live page first.", venue_label(cv)));
                }
            }
        }
        if loosens_max_loss(&old.stop, old.capital_usd, &cfg.stop, cfg.capital_usd) && !confirm {
            return Err(format!(
                "This loosens the max-loss rule: the most it may lose goes from {} to {}. Confirm to change it.",
                describe_allowance(&old.stop, old.capital_usd),
                describe_allowance(&cfg.stop, cfg.capital_usd)
            ));
        }

        // The amount: more only from money that is there, less never below zero.
        let delta = cfg.capital_usd - old.capital_usd;
        let others = |a: &&Autopilot| a.is_active() && a.config.id != old.id;
        if delta > EPS {
            if live {
                let free = match cash {
                    VenueCash::Read(c) => c,
                    VenueCash::Failed(why) => {
                        return Err(format!(
                            "Could not read the free cash at {} ({why}), so the higher amount is refused: it has to fit in what the account holds.",
                            venue_label(cv)
                        ))
                    }
                    VenueCash::NotRead => {
                        return Err(format!("The free cash at {} was not read, so the higher amount is refused.", venue_label(cv)))
                    }
                };
                let committed: f64 = self
                    .autopilots
                    .iter()
                    .filter(others)
                    .filter(|a| a.config.mode == AutopilotMode::Live && CostVenue::parse(&a.config.venue) == Some(cv))
                    .map(|a| a.start_capital)
                    .sum();
                // What it already holds at the venue is its own, not free cash.
                let held = self.ap_gross(&self.autopilots[i], None);
                let available = (free + held - committed).max(0.0);
                if cfg.capital_usd > available + EPS {
                    let other = if committed > 0.0 { format!(", of which {} is already committed to other live autopilots", usd(committed)) } else { String::new() };
                    return Err(format!(
                        "{} holds {} of free cash{other}, and the autopilot holds {} in positions, so it can have at most {}, not {}. Fund the account at the venue yourself; Pythia never moves money in or out.",
                        venue_label(cv),
                        usd(free),
                        usd(held),
                        usd(available),
                        usd(cfg.capital_usd)
                    ));
                }
            } else if cfg.mode == AutopilotMode::Paper {
                let paper = self.equity();
                let committed: f64 =
                    self.autopilots.iter().filter(others).filter(|a| a.config.mode == AutopilotMode::Paper).map(|a| a.start_capital).sum();
                let available = (paper - committed).max(0.0);
                if cfg.capital_usd > available + EPS {
                    return Err(format!(
                        "The paper account holds {}{}, so this autopilot can have at most {}, not {}.",
                        usd(paper),
                        if committed > 0.0 { format!(", of which {} is given to other paper autopilots", usd(committed)) } else { String::new() },
                        usd(available),
                        usd(cfg.capital_usd)
                    ));
                }
            } else if self.on_alpaca_paper_account(&cfg) {
                self.paper_account_room(Some(&old.id), cfg.capital_usd, &cash)?;
            }
        }
        let eq = self.ap_equity(&self.autopilots[i]);
        if eq + delta <= EPS {
            return Err(format!(
                "{label} has an equity of {}; the amount can come down by less than that, not by {}.",
                usd(eq),
                usd(-delta)
            ));
        }
        // New rules that would end it on the spot are refused: stopping is
        // the Stop button's job, with its own choice about the positions.
        let (start, peak, locked, steps) = {
            let ap = &self.autopilots[i];
            let tp_changed = cfg.stop.take_profit_pct != old.stop.take_profit_pct || cfg.stop.on_take_profit != old.stop.on_take_profit;
            (
                ap.start_capital + delta,
                ap.peak_equity.max(eq) + delta,
                ap.locked_floor.map(|f| f + delta),
                if tp_changed { 0 } else { ap.tp_steps },
            )
        };
        if let Some((floor, _)) = floor_equity(&cfg.stop, start, peak, locked) {
            if eq + delta <= floor + EPS {
                return Err(format!(
                    "With these rules it would stop at once: its equity would be {} and the floor {}. Use Stop if that is what you want.",
                    usd(eq + delta),
                    usd(floor)
                ));
            }
        }
        if cfg.stop.on_take_profit == OnTakeProfit::Stop {
            if let Some(t) = take_profit_target(&cfg.stop, start, steps) {
                if eq + delta >= t - EPS {
                    return Err(format!(
                        "With this profit target it would finish at once: its equity would be {} and the target {}. Use Stop if that is what you want.",
                        usd(eq + delta),
                        usd(t)
                    ));
                }
            }
        }

        // The strategies, chosen with the start's checks, before anything changes.
        let mut plan: Option<Vec<(String, f64, String, Vec<String>)>> = None;
        let mut passed_over: Vec<String> = Vec::new();
        if re_sleeve {
            let ap = &self.autopilots[i];
            let own: HashSet<String> = ap.sleeves.iter().map(|s| s.strategy_id.clone()).collect();
            let busy = self.busy_strategies(cfg.mode, Some(&old.id));
            // Its own book: markets other autopilots trade are not taken.
            let mut taken: HashSet<String> = HashSet::new();
            // What it holds stays where it is: a built-in's position is its
            // own, and a lab book's coins net only with other lab books.
            let mut builtin_held: BTreeMap<String, String> = BTreeMap::new();
            let mut lab_held: Vec<String> = Vec::new();
            for (m, owner) in &ap.owned {
                if self.is_lab_book(owner) {
                    lab_held.push(m.clone());
                } else {
                    builtin_held.insert(m.clone(), owner.clone());
                }
            }
            taken.extend(builtin_held.keys().cloned());
            let picks: Vec<(String, f64, String)> = if cfg.portfolio {
                let max = cfg.max_sleeves.unwrap_or(AUTO_MAX_SLEEVES);
                let pp = self.portfolio_pick(cfg.mode, &busy, &own, max, None)?;
                passed_over = pp.passed_over;
                pp.picks
            } else if auto {
                let max = cfg.max_sleeves.unwrap_or(AUTO_MAX_SLEEVES);
                let (picks, over) = self.auto_pick(venue, cfg.mode, &busy, &taken, &own, max, false)?;
                passed_over = over;
                // Live never adds a strategy the owner has not seen: the
                // confirmation above covers what this pick shows them.
                picks
            } else {
                let mut out = Vec::new();
                for sl in &cfg.sleeves {
                    let Some(s) = self.strategies.iter().find(|s| s.id == sl.strategy_id) else {
                        return Err(format!("There is no strategy \"{}\".", sl.strategy_id));
                    };
                    if let Some(why) = self.sleeve_block(&s.id, venue, cfg.mode, &busy, &own) {
                        return Err(why);
                    }
                    out.push((s.id.clone(), sl.weight, format!("Chosen by you; {}", self.evidence(&s.id).describe())));
                }
                out
            };
            if live {
                for (sid, ..) in &picks {
                    let s = self.strategies.iter().find(|s| &s.id == sid).expect("picked strategies exist");
                    let pp = self.passport_for(s);
                    if !pp.live_ready {
                        let why = pp.blocked_reason.unwrap_or_else(|| "its validation gates are not green".into());
                        return Err(format!("{} is not cleared for live: {why}", s.name));
                    }
                }
            }
            let mut wants: Vec<Want> = picks
                .iter()
                .map(|(sid, w, _)| {
                    let s = self.strategies.iter().find(|s| &s.id == sid).expect("picked strategies exist");
                    Want {
                        weight: *w,
                        whole: trades_as_set(s.kind),
                        net: s.kind == StrategyKind::LabTargets,
                        universe: self.sleeve_universe(s, cfg.mode),
                    }
                })
                .collect();
            // Coins the lab books hold now: open to lab books, closed to the rest.
            if !lab_held.is_empty() {
                wants.push(Want { weight: f64::INFINITY, whole: true, net: true, universe: lab_held });
            }
            let mut assigned = assign_markets(&wants, &taken);
            assigned.truncate(picks.len());
            let mut chosen = Vec::new();
            for ((sid, w, why), mut markets) in picks.into_iter().zip(assigned) {
                for (m, owner) in &builtin_held {
                    if *owner == sid && !markets.contains(m) {
                        markets.push(m.clone());
                    }
                }
                let name = self.strategies.iter().find(|s| s.id == sid).map(|s| s.name.clone()).unwrap_or_else(|| sid.clone());
                if markets.is_empty() {
                    if auto {
                        passed_over.push(name);
                        continue;
                    }
                    return Err(format!(
                        "{name} has no market of its own left: every market it trades already belongs to another sleeve of this autopilot. One position per market in an autopilot's book means two of its strategies cannot hold the same coin; drop one of them, pick strategies on different markets, or run the other one in an autopilot of its own."
                    ));
                }
                chosen.push((sid, w, why, markets));
            }
            if chosen.is_empty() {
                return Err("Auto found no strategy with a market of its own left in this autopilot.".into());
            }
            plan = Some(chosen);
        }

        // Apply. The amount first: X moves by the difference, and so do the
        // peak and a locked floor, so its P&L and every stop level keep their
        // distance from the equity. The max-loss rules are measured on the
        // new X.
        let mut parts: Vec<String> = Vec::new();
        if cfg.name != old.name {
            parts.push(format!("name \"{}\" to \"{}\"", old.name, cfg.name));
        }
        {
            let ap = &mut self.autopilots[i];
            ap.start_capital = start;
            ap.peak_equity = peak;
            ap.locked_floor = locked;
            ap.tp_steps = steps;
            // The curve so far is rescaled to the new amount: a deposit or a
            // withdrawal is no return, and an unscaled curve would show the
            // cut as a crash (and a drawdown) and the raise as a gain.
            if capital_changed && eq > EPS {
                let f = (eq + delta) / eq;
                for p in ap.history.iter_mut() {
                    p.1 *= f;
                }
            }
        }
        if capital_changed {
            let mut s = format!("amount {} to {}", usd(old.capital_usd), usd(cfg.capital_usd));
            if delta < 0.0 {
                s.push_str(" (its positions come down at the next rebalance; nothing is sold at once)");
            } else {
                s.push_str(" (the extra is invested by its next rebalance or entries)");
            }
            parts.push(s);
        }
        if let Some(chosen) = plan {
            parts.push(self.ap_apply_sleeves(i, chosen, now));
            if !passed_over.is_empty() {
                parts.push(format!("auto passed over {} (their markets belong to a better pick in this autopilot)", passed_over.join(", ")));
            }
            if auto {
                self.autopilots[i].last_pick_ms = Some(now);
            }
            if cfg.portfolio {
                let split: Vec<String> = PORTFOLIO_CLASSES
                    .iter()
                    .zip(self.ap_class_weights(&self.autopilots[i]))
                    .map(|(c, w)| format!("{} {:.0} %", class_label(*c), w * 100.0))
                    .collect();
                parts.push(format!("split by evidence {}", split.join(", ")));
                self.ap_blend_relink(i, now);
            }
        }
        if cfg.stop != old.stop || capital_changed {
            let rules = describe_rules(&cfg);
            if rules.is_empty() {
                parts.push("stop rules: none".into());
            } else {
                parts.push(format!("stop rules: {rules}"));
            }
        }
        if cfg.flatten_on_stop != old.flatten_on_stop {
            parts.push(if cfg.flatten_on_stop { "closes its positions when it stops".into() } else { "leaves its positions open when it stops".into() });
        }
        if auto && cfg.max_sleeves != old.max_sleeves {
            parts.push(format!("picks at most {}", cfg.max_sleeves.unwrap_or(AUTO_MAX_SLEEVES)));
        }
        if cfg.repick_every_hours != old.repick_every_hours {
            parts.push(match cfg.repick_every_hours {
                Some(h) => format!("re-picks every {} h", pct(h)),
                None => "never re-picks".into(),
            });
        }
        if parts.is_empty() {
            parts.push("pick settings".into());
        }
        let ap = &mut self.autopilots[i];
        ap.config = cfg;
        let msg = format!("{label} changed by you: {}.", parts.join("; "));
        ap.last_action = Some(msg.clone());
        let kind = if live { JournalKind::Risk } else { JournalKind::System };
        self.log(kind, msg.clone(), None, None);
        self.pending_alerts.push(msg.clone());
        self.ap_sample(i, now, true);
        Ok(msg)
    }

    /// Put a new set of sleeves in place, keeping every position. A sleeve
    /// that stays gets its new weight and markets; a new one is claimed; one
    /// taken out stays listed at weight zero while it holds something or has
    /// a record (lab books: its coins are re-attributed by the next netted
    /// target, sold only where nobody wants them; built-ins: it opens nothing
    /// new and its positions run to their own exits), and is released
    /// otherwise. Returns the change in words.
    fn ap_apply_sleeves(&mut self, i: usize, chosen: Vec<(String, f64, String, Vec<String>)>, now: i64) -> String {
        let mode = self.autopilots[i].config.mode;
        let want_state = if mode == AutopilotMode::Live { StrategyState::Live } else { StrategyState::Paper };
        let total: f64 = chosen.iter().map(|c| c.1).sum();
        let labs = chosen.iter().filter(|c| self.is_lab_book(&c.0)).count();
        let when = chrono::DateTime::from_timestamp_millis(now).map(|t| t.format("%Y-%m-%d %H:%M UTC").to_string()).unwrap_or_default();
        let mut parts: Vec<String> = Vec::new();
        let keep: HashSet<String> = chosen.iter().map(|c| c.0.clone()).collect();
        for (sid, w, why, markets) in chosen {
            let weight = if total > 0.0 { w / total } else { 0.0 };
            let lab = self.is_lab_book(&sid);
            let netted = if lab && labs > 1 {
                format!(", netted per coin with the other {} lab book(s) into one position per coin", labs - 1)
            } else {
                String::new()
            };
            let why = format!("{why}; gets {:.0} % of the capital on {} market(s){netted}.", weight * 100.0, markets.len());
            let ap = &mut self.autopilots[i];
            if let Some(s) = ap.sleeve_mut(&sid) {
                let was = s.weight;
                s.weight = weight;
                s.why = why;
                s.markets = markets;
                s.dropped_ms = None;
                if (was - weight).abs() > 1e-9 {
                    parts.push(format!("{} {:.0} % (was {:.0} %)", s.name, weight * 100.0, was * 100.0));
                }
                continue;
            }
            let Some(s) = self.strategies.iter().find(|s| s.id == sid) else { continue };
            let (name, prior) = (s.name.clone(), s.state);
            self.autopilots[i].sleeves.push(Sleeve {
                strategy_id: sid.clone(),
                name: name.clone(),
                weight,
                why,
                markets,
                realized: 0.0,
                fees: 0.0,
                trades: 0,
                prior_state: prior,
                dropped_ms: None,
            });
            if prior != want_state {
                self.apply_strategy_state(&sid, want_state);
            }
            parts.push(format!("{name} {:.0} % (new)", weight * 100.0));
        }
        // The ones taken out.
        let out: Vec<String> =
            self.autopilots[i].sleeves.iter().filter(|s| !keep.contains(&s.strategy_id)).map(|s| s.strategy_id.clone()).collect();
        for sid in out {
            let lab = self.is_lab_book(&sid);
            let ap = &self.autopilots[i];
            let holds = ap.owned.iter().any(|(m, owner)| *owner == sid || ap.share(m, &sid) > 0.0)
                || ap.owned.keys().any(|m| self.ap_position(ap, m).is_some_and(|p| p.strategy_id == sid && p.qty.abs() > 1e-12));
            let s = ap.sleeve(&sid).expect("listed sleeves exist");
            let record = s.trades > 0 || s.realized.abs() > EPS || s.fees > EPS;
            let (name, was, dropped_before) = (s.name.clone(), s.weight, s.dropped_ms.is_some());
            if holds || record {
                let held: Vec<String> = if lab {
                    Vec::new()
                } else {
                    ap.owned.iter().filter(|(_, o)| **o == sid).map(|(m, _)| m.clone()).collect()
                };
                let s = self.autopilots[i].sleeve_mut(&sid).expect("listed sleeves exist");
                s.weight = 0.0;
                if !lab {
                    s.markets = held;
                }
                if !dropped_before {
                    s.dropped_ms = Some(now);
                    s.why = if lab {
                        format!("Taken out by you at {when}. Its coins stay: a coin the other lab books want is theirs from the next rebalance, the rest is sold by it.")
                    } else {
                        format!("Taken out by you at {when}. It opens nothing new; its open positions run to their own exits.")
                    };
                }
                if was > 0.0 {
                    parts.push(format!("{name} taken out (was {:.0} %)", was * 100.0));
                }
            } else {
                self.autopilots[i].sleeves.retain(|s| s.strategy_id != sid);
                // Paused unless another autopilot still runs it.
                if self.aps_of_strategy(&sid).is_empty() && self.strategies.iter().any(|s| s.id == sid && s.state != StrategyState::Paused) {
                    self.apply_strategy_state(&sid, StrategyState::Paused);
                }
                if was > 0.0 {
                    parts.push(format!("{name} taken out and released (it held nothing)"));
                }
            }
        }
        // The netted target changes now, so the next rebalance runs now: it
        // trades only the difference per coin.
        let members: Vec<String> = self.autopilots[i].sleeves.iter().map(|s| s.strategy_id.clone()).collect();
        let book = self.autopilots[i].config.id.clone();
        for sid in &members {
            self.lab_done.remove(&super::pos_key(&book, sid));
            self.lab_retry.remove(&super::pos_key(&book, sid));
        }
        if parts.is_empty() {
            "strategies as they were".into()
        } else {
            format!(
                "strategies {}. Its positions stay: coins the new target also wants are kept, and the next rebalance trades only the difference",
                parts.join(", ")
            )
        }
    }

    /// What the big-move watch samples (`alerts::MoveWatch`): each active
    /// autopilot's equity, and the price of each coin they hold, with who
    /// holds it.
    pub fn move_inputs(&self) -> Vec<crate::alerts::MoveInput> {
        use crate::alerts::{MoveInput, MoveSubject};
        let mut out = Vec::new();
        let mut coins: BTreeMap<String, Vec<String>> = BTreeMap::new();
        for ap in self.autopilots.iter().filter(|a| a.is_active()) {
            out.push(MoveInput {
                key: format!("ap:{}", ap.config.id),
                label: ap.config.name.clone(),
                held_by: String::new(),
                subject: MoveSubject::Equity,
                value: self.ap_equity(ap),
            });
            for m in ap.owned.keys() {
                coins.entry(m.clone()).or_default().push(ap.config.name.clone());
            }
        }
        for (id, names) in coins {
            let Some(m) = self.markets.iter().find(|m| m.id == id) else { continue };
            out.push(MoveInput {
                key: id.clone(),
                label: m.symbol.split('/').next().unwrap_or(&m.symbol).to_string(),
                held_by: names.join(", "),
                subject: MoveSubject::Coin,
                value: m.price,
            });
        }
        out
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
                    orders: ap.orders,
                    fees: ap.fees,
                    open_positions: ap.owned.len(),
                    by_sleeve: ap
                        .sleeves
                        .iter()
                        .map(|s| {
                            let exposure = self.ap_gross(ap, Some(&s.strategy_id)).max(0.0);
                            SleeveStatus {
                                strategy_id: s.strategy_id.clone(),
                                name: s.name.clone(),
                                weight: s.weight,
                                pnl: s.realized - s.fees + self.ap_unrealized(ap, Some(&s.strategy_id)),
                                trades: s.trades,
                                why: s.why.clone(),
                                markets: s.markets.clone(),
                                exposure,
                                exposure_pct: if equity > 0.0 { exposure / equity * 100.0 } else { 0.0 },
                                dropped: s.dropped_ms.is_some(),
                            }
                        })
                        .collect(),
                    last_action: ap.last_action.clone(),
                    history: ap.history.clone(),
                    forward: self.ap_forward(ap),
                    waiting: self.ap_waiting(ap),
                    next_repick_ms: ap
                        .config
                        .repick_every_hours
                        .filter(|h| ap.is_active() && *h > 0.0 && ap.config.sleeves.is_empty())
                        .map(|h| ap.last_pick_ms.unwrap_or(ap.started_ms) + (h * 3_600_000.0) as i64),
                    btc_return_pct: self.ap_btc_return_pct(ap),
                    held: ap.owned.keys().cloned().collect(),
                    benchmark: self.ap_benchmark(ap, equity),
                    cash: equity - self.ap_gross(ap, None) - self.ap_pending(ap, None),
                    max_drawdown_pct: max_drawdown_pct(&ap.history, equity),
                    classes: self.ap_class_statuses(ap),
                }
            })
            .collect()
    }

    /// A running autopilot that holds nothing and has nothing at the venue is
    /// in cash, waiting for signals. Said plainly, with the reason when the
    /// last netted target knows it; nothing is ever bought just to be busy.
    fn ap_waiting(&self, ap: &Autopilot) -> Option<String> {
        if ap.state != AutopilotState::Running || !ap.owned.is_empty() || self.ap_pending(ap, None) > 0.0 {
            return None;
        }
        let mut s = "In cash, waiting for signals".to_string();
        match &ap.cash_note {
            Some(n) => s.push_str(&format!(": {n}.")),
            None => s.push('.'),
        }
        s.push_str(" It never forces a trade; it buys when a strategy has something to buy.");
        Some(s)
    }

    /// The lab's forward report in brief (`reports/forward/evidence.json`),
    /// handed in by the host next to the signals. The auto pick and the
    /// autopilot status read it; nothing else changes.
    pub fn apply_lab_forward(&mut self, f: crate::lab::ForwardFile) {
        self.lab_forward = Some(f);
    }

    /// The forward report, when it is recent enough to use.
    fn lab_forward_fresh(&self) -> Option<&crate::lab::ForwardFile> {
        self.lab_forward.as_ref().filter(|f| self.now() - f.generated_ms <= FORWARD_STALE_MS)
    }

    /// One active autopilot against its backtest. The report's row for it
    /// when there is one (and it is this run, not an earlier one under the
    /// same id); otherwise an autopilot younger than the minimum is simply
    /// too early, and an older one has nothing to say yet.
    fn ap_forward(&self, ap: &Autopilot) -> Option<AutopilotForward> {
        if !ap.is_active() {
            return None;
        }
        let row = self
            .lab_forward_fresh()
            .and_then(|f| f.autopilots.get(&ap.config.id))
            .filter(|r| r.started_ms.is_none_or(|t| t == ap.started_ms));
        match row {
            Some(r) => {
                let status = if !r.counts() {
                    "early"
                } else if r.below_band() {
                    "below"
                } else if r.status == "watch" {
                    "watch"
                } else if r.has_band() {
                    "ok"
                } else {
                    "none"
                };
                Some(AutopilotForward {
                    status: status.into(),
                    days: r.days,
                    return_pct: r.return_pct,
                    band_low_pct: r.band_low_pct,
                    band_high_pct: r.band_high_pct,
                })
            }
            None => {
                let days = (self.now() - ap.started_ms).max(0) as f64 / 86_400_000.0;
                (days < crate::lab::FORWARD_MIN_DAYS).then(|| AutopilotForward {
                    status: "early".into(),
                    days,
                    return_pct: None,
                    band_low_pct: None,
                    band_high_pct: None,
                })
            }
        }
    }

    // ── the tick ───────────────────────────────────────────────────────────

    /// Watch every autopilot: its live gates, its stop rules, its history.
    /// Runs every tick, before strategies get to open anything.
    pub(super) fn autopilot_step(&mut self, now: i64) {
        for i in 0..self.autopilots.len() {
            self.ap_prune(i);
            self.ap_bench_backfill(i, now);
            if self.autopilots[i].is_active() {
                self.ap_check(i, now);
                self.ap_repick(i, now);
            } else if self.autopilots[i].flatten_at_stop && !self.autopilots[i].owned.is_empty() {
                // A late fill after the stop, or a real position that could
                // not be closed then: close it now.
                let name = self.autopilots[i].config.name.clone();
                let book = self.autopilots[i].config.id.clone();
                let open: Vec<String> = self.autopilots[i].owned.keys().cloned().collect();
                for m in open {
                    if !self.ap_close_waits_for_price(&book, &m) {
                        self.close_position(&super::pos_key(&book, &m), &format!("autopilot \"{name}\" stopped"));
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
            done.sort_by_key(|a| std::cmp::Reverse(a.0));
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
            .filter(|m| self.ap_position(&self.autopilots[i], m).is_none_or(|p| p.qty.abs() < 1e-12))
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
    fn ap_close_waits_for_price(&mut self, book: &str, market: &str) -> bool {
        let paper = self.positions.get(&super::pos_key(book, market)).is_some_and(|p| !p.live && !p.demo);
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
        if !config_venue(&ap.config).is_some_and(|v| self.live_routable(v)) {
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
        // A stale price never raises the peak (and with it the trailing
        // floor), locks in a profit or finishes on one: the last price of a
        // dead feed, or of the moments before a restart, is not where the
        // market is. The floor is still checked on it, so a loss rule never
        // waits for a feed.
        let marks_fresh = self.autopilots[i].owned.keys().all(|m| self.exit_price_stale(m, now).is_none());
        if marks_fresh {
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
            if marks_fresh && eq >= target - EPS {
                match stop.on_take_profit {
                    OnTakeProfit::Stop => {
                        let reason = format!("take profit of {} % reached (equity {}, target {})", pct(tp), usd(eq), usd(target));
                        self.ap_halt(i, AutopilotState::Finished, reason, flatten, now, AlertKind::StopRuleHit);
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
                self.ap_halt(i, AutopilotState::Stopped, reason, flatten, now, AlertKind::FloorHit);
                return;
            }
        }

        // The end time.
        if let Some(end) = stop.end_ms {
            if now >= end {
                self.ap_halt(i, AutopilotState::Finished, "end time reached".into(), flatten, now, AlertKind::StopRuleHit);
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
    fn ap_halt(&mut self, i: usize, state: AutopilotState, reason: String, flatten: bool, now: i64, cause: AlertKind) {
        {
            let ap = &mut self.autopilots[i];
            ap.state = state;
            ap.stop_reason = Some(reason.clone());
            ap.paused_reason = None;
            ap.stopped_ms = Some(now);
            ap.flatten_at_stop = flatten;
        }
        self.autopilots[i].btc_end = self.ap_btc_price(&self.autopilots[i]);
        if self.autopilots[i].spy_start.is_some() {
            self.autopilots[i].spy_end = self.ap_spy_price();
        }
        let name = self.autopilots[i].config.name.clone();
        let book = self.autopilots[i].config.id.clone();
        let word = if state == AutopilotState::Finished { "finished" } else { "stopped" };
        // Its maker orders resting at the venue are cancelled: a stopped
        // autopilot leaves nothing working there. Another autopilot that
        // runs the same strategies keeps its own orders.
        self.maker_stand_down_book(&book, &format!("autopilot \"{name}\" {word}"));
        let open: Vec<String> = self.autopilots[i].owned.keys().cloned().collect();
        let mut tail = String::new();
        if flatten {
            for m in &open {
                if !self.ap_close_waits_for_price(&book, m) {
                    self.close_position(&super::pos_key(&book, m), &format!("autopilot \"{name}\" {word}"));
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
                    if self.in_flight_markets.contains(&super::pos_key(&book, m)) {
                        at_venue += 1;
                    } else if self.ap_close_waits_for_price(&book, m) {
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
            let lab_open = self.autopilots[i]
                .owned
                .values()
                .filter(|sid| self.strategies.iter().any(|s| &s.id == *sid && s.kind == StrategyKind::LabTargets))
                .count();
            let u = self.ap_unrealized(&self.autopilots[i], None);
            let ap = &mut self.autopilots[i];
            ap.released += u;
            ap.owned.clear();
            tail.push_str(&format!(
                " Left its {} position(s) open, now managed by their strategies' stops; its P&L counts them at their price now.",
                open.len()
            ));
            if lab_open > 0 {
                tail.push_str(&format!(
                    " {lab_open} of them belong to a lab book, which carries no stops and does not trade on its own: close them on the Positions page. They stay in this autopilot's book, so a new autopilot under the same id waits until they are closed."
                ));
            }
        }
        let sleeves: Vec<(String, String, StrategyState)> =
            self.autopilots[i].sleeves.iter().map(|s| (s.strategy_id.clone(), s.name.clone(), s.prior_state)).collect();
        let mut paused = Vec::new();
        let mut still: Vec<String> = Vec::new();
        for (sid, sname, _) in &sleeves {
            // Another autopilot that runs the same strategy keeps it running.
            if let Some(who) = self.autopilot_claimant(sid) {
                still.push(format!("{sname} (in {who})"));
                continue;
            }
            if self.strategies.iter().any(|s| &s.id == sid && s.state != StrategyState::Paused) {
                self.apply_strategy_state(sid, StrategyState::Paused);
                paused.push(sname.clone());
            }
        }
        if !paused.is_empty() {
            tail.push_str(&format!(" Paused its strategies: {}.", paused.join(", ")));
        }
        if !still.is_empty() {
            tail.push_str(&format!(
                " Still running for the other autopilots, which are untouched: {}.",
                still.join(", ")
            ));
        }
        let idle: Vec<String> = sleeves
            .iter()
            .filter(|(sid, ..)| self.lab_book_autopilot_only(sid) && self.autopilot_claimant(sid).is_none())
            .map(|(_, n, _)| n.clone())
            .collect();
        if !idle.is_empty() {
            tail.push_str(&format!(
                " Idle again, waiting for the next autopilot: {} (it keeps receiving the lab's signal and trades only inside an autopilot).",
                idle.join(", ")
            ));
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
        let key = format!("halt:{}:{now}", self.autopilots[i].config.id);
        {
            use crate::alerts::{card, AlertEvent, Row};
            let ap = &self.autopilots[i];
            let pnl = eq - x;
            let pnl_pct = if x > 0.0 { pnl / x * 100.0 } else { 0.0 };
            let mut rows = vec![
                Row::new("Equity", card::usd(eq)),
                Row::toned("P&L", format!("{} {}", card::signed_usd(pnl), card::signed_pct(pnl_pct, 2)), pnl),
            ];
            if let Some(b) = self.ap_btc_return_pct(ap) {
                rows.push(Row::toned("vs BTC", format!("{:+.2} pts", pnl_pct - b), pnl_pct - b));
            }
            rows.push(Row::new("Trades", ap.trades.to_string()));
            rows.push(Row::new("Fees", card::usd(ap.fees)));
            // The first sentence of what happened to its positions, no more.
            let tail = tail.trim();
            let foot = tail.split_inclusive(". ").next().unwrap_or(tail).trim().to_string();
            let title = format!("{} {word}", ap.config.name);
            self.alert_event(
                AlertEvent::new(cause, key, msg.clone())
                    .titled(title)
                    .with_summary(format!("{}.", reason.trim_end_matches('.')))
                    .with_rows(rows)
                    .with_footer(foot),
            );
        }
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

    /// Move a save from before autopilots kept their own books into books.
    ///
    /// Before, every position was kept under its market in one shared book,
    /// and an autopilot owned the markets in its `owned` map. Each of those
    /// positions moves, exactly as it is (quantity, average price, stops,
    /// live and demo flags, reference price), into the book of the autopilot
    /// that owns it. Orders still at the venue, and Alpaca fees still to be
    /// posted, follow the same rule the old fill booking used: an order or
    /// fee in a market an autopilot owns is that autopilot's, and so is an
    /// entry its sleeve sent in a market it did not hold yet. A lab book's
    /// last rebalanced signal is kept for the autopilot that runs it, so the
    /// restart does not rebalance it again. Nothing is sold or bought; the
    /// cash and every P&L stay as they were. Running it on a save that is
    /// already in books changes nothing.
    pub(super) fn migrate_to_books(&mut self) {
        let mut moved_total = 0usize;
        for i in 0..self.autopilots.len() {
            let id = self.autopilots[i].config.id.clone();
            let label = self.autopilots[i].label();
            let owned: Vec<String> = self.autopilots[i].owned.keys().cloned().collect();
            let mut moved: Vec<String> = Vec::new();
            for m in &owned {
                let new_key = super::pos_key(&id, m);
                if self.positions.contains_key(&new_key) {
                    continue;
                }
                let Some(mut p) = self.positions.remove(m.as_str()) else { continue };
                p.book = id.clone();
                p.market = m.clone();
                moved.push(p.symbol.clone());
                self.positions.insert(new_key.clone(), p);
                if let Some(r) = self.ref_prices.remove(m.as_str()) {
                    self.ref_prices.insert(new_key, r);
                }
            }
            // Orders out and fees to come in the markets it owns, or entries
            // its sleeves sent while it was active.
            let active = self.autopilots[i].is_active();
            let sends = |a: &Autopilot, sid: &str, m: &str| a.sleeve(sid).is_some_and(|s| s.markets.iter().any(|x| x == m));
            let ap = &self.autopilots[i];
            let mut orders = 0usize;
            for f in self.inflight.values_mut() {
                if f.book.is_empty() && (ap.owned.contains_key(&f.market_id) || (active && sends(ap, &f.strategy_id, &f.market_id))) {
                    f.book = id.clone();
                    orders += 1;
                }
            }
            for w in self.alpaca_fees.iter_mut() {
                if w.book.is_empty() && (ap.owned.contains_key(&w.market_id) || sends(ap, &w.strategy_id, &w.market_id)) {
                    w.book = id.clone();
                }
            }
            // The order rows say whose they are too.
            let order_ids: HashSet<String> =
                self.inflight.iter().filter(|(_, f)| f.book == id).map(|(k, _)| k.clone()).collect();
            for o in self.orders.iter_mut().filter(|o| order_ids.contains(&o.id)) {
                o.book = Some(id.clone());
            }
            if active {
                let sids: Vec<String> = self.autopilots[i].sleeves.iter().map(|s| s.strategy_id.clone()).collect();
                for sid in sids {
                    let key = super::pos_key(&id, &sid);
                    if let Some(done) = self.lab_done.get(&sid).copied() {
                        self.lab_done.entry(key).or_insert(done);
                    }
                }
            }
            if !moved.is_empty() || orders > 0 {
                moved_total += moved.len();
                moved.sort();
                let msg = format!(
                    "{label} now keeps a book of its own: its {} open position(s) ({}) moved into it as they were{}. Nothing was sold or bought; its cash, P&L, peak and floor are unchanged.",
                    moved.len(),
                    moved.join(", "),
                    if orders > 0 { format!(", with {orders} order(s) still at the venue") } else { String::new() }
                );
                self.autopilots[i].last_action = Some(msg.clone());
                self.log(JournalKind::System, msg, None, None);
            }
        }
        // One venue order per market and book.
        self.in_flight_markets = self.inflight.values().map(|f| super::pos_key(&f.book, &f.market_id)).collect();
        if moved_total > 0 {
            self.log(
                JournalKind::System,
                format!("{moved_total} position(s) moved into their autopilots' own books; every autopilot is now a sub-account of its own"),
                None,
                None,
            );
        }
    }

    // ── strategy choice ────────────────────────────────────────────────────

    /// Why a strategy cannot be a sleeve, if it cannot. `own` are the sleeves
    /// of the autopilot that asks (a re-pick): coins they hold are its own.
    fn sleeve_block(&self, sid: &str, venue: Venue, mode: AutopilotMode, busy: &HashSet<String>, own: &HashSet<String>) -> Option<String> {
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
            return Some(if mode == AutopilotMode::Live {
                format!(
                    "{} already runs in the autopilot {other}. A live autopilot runs its strategies alone; stop the other one first.",
                    s.name
                )
            } else {
                format!(
                    "{} runs live in the autopilot {other}, which keeps its strategies to itself while it trades real money.",
                    s.name
                )
            });
        }
        if s.kind == StrategyKind::LabTargets && !own.contains(&s.id) {
            if !self.lab_signals.contains_key(&s.id) {
                return Some(format!("{} has no signal from the lab yet.", s.name));
            }
            // Coins it holds in the main book from a run of its own: they
            // would be left unmanaged once an autopilot claims it. Coins in
            // another autopilot's book are that autopilot's and change
            // nothing here: this one starts with an empty book.
            let held = self.positions.values().any(|p| p.strategy_id == s.id && p.book.is_empty() && p.qty.abs() > 1e-12);
            if held && self.lab_book_autopilot_only(&s.id) {
                return Some(format!(
                    "{} still holds coins, left open when an autopilot stopped without closing them (or from before it was idle). A lab book only trades by rebalancing, so it could never start flat inside the autopilot: close them on the Positions page first.",
                    s.name
                ));
            }
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
    pub(super) fn evidence(&self, sid: &str) -> Evidence {
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
            lab: s.kind == StrategyKind::LabTargets,
            // When the lab also measured the rule without survivorship, the
            // lower of the two counts: a headline that leaned on coins that
            // happened to survive must not win the pick.
            lab_oos_sharpe: lab.and_then(|e| match (e.oos_sharpe, e.oos_sharpe_survivorship_free) {
                (Some(a), Some(b)) if b.is_finite() => Some(a.min(b)),
                (a, _) => a,
            }),
            lab_deflated_p: lab.and_then(|e| e.deflated_p),
            lab_variants: lab.and_then(|e| e.variants_tried),
            lab_sharpe_2x_cost: lab.and_then(|e| e.sharpe_2x_cost),
            lab_max_dd: lab.and_then(|e| e.oos_max_dd),
            lab_caveat: lab.and_then(|e| e.caveat.clone()),
            // The lab's own paper book of the same rule, against its backtest.
            forward: if s.kind == StrategyKind::LabTargets {
                sid.strip_prefix("lab:").and_then(|b| self.lab_forward_fresh()?.books.get(b).cloned())
            } else {
                None
            },
        }
    }

    /// The markets a sleeve of this strategy would trade: a lab book every
    /// market of its asset class (every crypto market, or every Alpaca
    /// equity market for a book of US shares; its weights may name any of
    /// them), anything else the
    /// markets of its universe that exist here. In demo, only markets the
    /// demo route can trade: on the Alpaca paper account, the coins Alpaca
    /// lists (a lab book's unlisted coins stay in cash, see `run_lab_books`).
    fn sleeve_universe(&self, s: &super::StrategyConfig, mode: AutopilotMode) -> Vec<String> {
        let tradable = |m: &super::Market| mode != AutopilotMode::Demo || self.demo_lists(m);
        if s.kind == StrategyKind::LabTargets {
            self.lab_book_markets(s.venue_class == Venue::Alpaca)
                .into_iter()
                .filter(|m| tradable(m))
                .map(|m| m.id)
                .collect()
        } else {
            s.universe
                .iter()
                .filter(|id| self.markets.iter().any(|m| &m.id == *id && tradable(m)))
                .cloned()
                .collect()
        }
    }

    /// "Auto": the strategies the engine can run on this venue today, weighted
    /// by their evidence ([`Evidence::score`], one scale for built-ins and lab
    /// books), at most `max` of them. Paused strategies are left out (they
    /// were paused on purpose, often on their evidence) except idle lab
    /// books, which wait paused for exactly this; so is any whose own record
    /// shows no edge, a lab book whose signal has expired or whose lab
    /// out-of-sample Sharpe is not positive, and live only takes strategies
    /// cleared for live.
    ///
    /// Markets stay exclusive, and the evidence decides who gets them: the
    /// candidates are taken best first, and a candidate is passed over when a
    /// stronger pick already holds what it needs. Lab books are the one
    /// exception among themselves: each trades every crypto market, and the
    /// autopilot nets their targets per coin into one position, so up to
    /// `max` of them run together, weighted by score. Against everyone else a
    /// lab book still claims every crypto market as one set: it is passed
    /// over when a stronger built-in holds any crypto market, and once a lab
    /// book is in, a built-in on crypto has nothing left. On crypto that
    /// normally means: the best lab books take the crypto markets together,
    /// and built-ins only run when they out-score every lab book.
    /// `own` are the sleeves of the autopilot that re-picks.
    ///
    /// `labs_only` is a portfolio's pick of one class: lab books only, each
    /// with a positive out-of-sample Sharpe from the lab (no evidence, no
    /// money), and a book it already runs stays a candidate while its signal
    /// is past its window (it holds its last targets, as inside any netted
    /// book), so a late signal never empties a class.
    /// Returns the picks (id, weight, why) and the names passed over.
    #[allow(clippy::too_many_arguments)]
    fn auto_pick(
        &self,
        venue: Venue,
        mode: AutopilotMode,
        busy: &HashSet<String>,
        taken: &HashSet<String>,
        own: &HashSet<String>,
        max: usize,
        labs_only: bool,
    ) -> Result<AutoPick, String> {
        let now = self.now();
        let max = max.clamp(1, AUTO_MAX_SLEEVES_LIMIT);
        let mut scored: Vec<(String, f64, Evidence)> = self
            .strategies
            .iter()
            .filter(|s| s.id != "manual")
            .filter(|s| !labs_only || s.kind == StrategyKind::LabTargets)
            .filter(|s| s.state != StrategyState::Paused || self.lab_book_autopilot_only(&s.id))
            .filter(|s| {
                s.kind != StrategyKind::LabTargets
                    || self.lab_signals.get(&s.id).is_some_and(|g| g.is_fresh(now) || (labs_only && own.contains(&s.id)))
            })
            .filter(|s| self.sleeve_block(&s.id, venue, mode, busy, own).is_none())
            .filter_map(|s| {
                let ev = self.evidence(&s.id);
                if mode == AutopilotMode::Live && !ev.live_ready {
                    return None;
                }
                if labs_only && !ev.lab_oos_sharpe.is_some_and(|sh| sh.is_finite() && sh > 0.0) {
                    return None;
                }
                // Positive evidence only: a lab book whose own out-of-sample
                // Sharpe is zero or below has nothing to weight.
                if ev.lab && ev.lab_oos_sharpe.is_some_and(|sh| sh.is_nan() || sh <= 0.0) {
                    return None;
                }
                ev.score().filter(|sc| *sc > 0.0).map(|sc| (s.id.clone(), sc, ev))
            })
            .collect();
        if scored.is_empty() {
            if labs_only {
                return Err(format!(
                    "no lab book of {} has a positive out-of-sample Sharpe from the lab (or every one is paused or kept by a live autopilot)",
                    asset_words(venue)
                ));
            }
            return Err(match mode {
                AutopilotMode::Live => "Auto found no strategy cleared for live on this venue. Live needs a green Strategy Passport; run the checks on the Strategies page or choose paper.".into(),
                _ => "Auto found no strategy it can run on this venue: every candidate is paused, already in an autopilot, or has a record that shows no edge.".into(),
            });
        }
        // Highest score first; ties keep the engine's order.
        scored.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));
        let candidates = scored.len();
        let mut held: HashSet<String> = HashSet::new(); // markets a kept built-in trades
        let mut sets: HashSet<String> = taken.clone(); // markets a kept whole set claimed
        let mut netted: HashSet<String> = HashSet::new(); // markets kept lab books share
        let mut picks = Vec::new();
        let mut passed_over = Vec::new();
        for (rank, (sid, sc, ev)) in scored.into_iter().enumerate() {
            let s = self.strategies.iter().find(|s| s.id == sid).expect("scored strategies exist");
            let universe = self.sleeve_universe(s, mode);
            let lab = s.kind == StrategyKind::LabTargets;
            let fits = if lab {
                !universe.is_empty() && universe.iter().all(|m| !held.contains(m) && !sets.contains(m))
            } else if trades_as_set(s.kind) {
                !universe.is_empty() && universe.iter().all(|m| !held.contains(m) && !sets.contains(m) && !netted.contains(m))
            } else {
                universe.iter().any(|m| !sets.contains(m) && !netted.contains(m))
            };
            if !fits || picks.len() >= max {
                if !fits {
                    passed_over.push(s.name.clone());
                }
                continue;
            }
            if lab {
                netted.extend(universe);
            } else {
                if trades_as_set(s.kind) {
                    sets.extend(universe.iter().cloned());
                }
                held.extend(universe);
            }
            picks.push((sid, sc, ev.auto_why(rank, candidates)));
        }
        Ok((picks, passed_over))
    }

    /// A portfolio's pick. Each asset class runs the auto pick on its own lab
    /// books (only books with a positive out-of-sample Sharpe count), and
    /// the allocator splits the amount between the classes: the score of a
    /// class's best book per unit of that book's out-of-sample drawdown (the
    /// class prior when none was measured), over the sum of both. A class
    /// with no such book gets nothing. Inside a class the books split its
    /// budget by score. `current` is the class split in place, in
    /// [`PORTFOLIO_CLASSES`] order (a re-pick): while both classes have
    /// evidence, a budget moves toward its target by at most
    /// [`PORTFOLIO_MAX_SHIFT`]. The picks' weights add up to one.
    fn portfolio_pick(
        &self,
        mode: AutopilotMode,
        busy: &HashSet<String>,
        own: &HashSet<String>,
        max: usize,
        current: Option<&[f64]>,
    ) -> Result<PortfolioPick, String> {
        let mut per: Vec<Vec<(String, f64, String)>> = Vec::new();
        let mut raw: Vec<(f64, f64)> = Vec::new();
        let mut empty: Vec<(Venue, String)> = Vec::new();
        let mut passed_over: Vec<String> = Vec::new();
        for c in PORTFOLIO_CLASSES {
            match self.auto_pick(c, mode, busy, &HashSet::new(), own, max, true) {
                Ok((picks, over)) if !picks.is_empty() => {
                    passed_over.extend(over);
                    // The picks come best first.
                    let best = &picks[0];
                    let risk = super::allocator::risk_of(self.evidence(&best.0).lab_max_dd, c == Venue::Alpaca);
                    raw.push((best.1, risk));
                    per.push(picks);
                }
                Ok(_) => {
                    raw.push((0.0, 1.0));
                    per.push(Vec::new());
                    empty.push((c, format!("no lab book of {} is free to run", asset_words(c))));
                }
                Err(why) => {
                    raw.push((0.0, 1.0));
                    per.push(Vec::new());
                    empty.push((c, why));
                }
            }
        }
        let target = super::allocator::risk_budgets(&raw);
        if target.iter().all(|w| *w <= 0.0) {
            let why: Vec<String> = empty.iter().map(|(_, w)| w.clone()).collect();
            return Err(format!("Auto found nothing a portfolio can run: {}.", why.join("; ")));
        }
        // No evidence, no money at once; between two classes with evidence
        // the split moves in bounded steps.
        let budgets = match current {
            Some(cur) if cur.len() == target.len() && target.iter().all(|w| *w > 0.0) => {
                super::allocator::bounded_step(cur, &target, PORTFOLIO_MAX_SHIFT)
            }
            _ => target,
        };
        let mut picks = Vec::new();
        for ((c, class_picks), b) in PORTFOLIO_CLASSES.iter().zip(per).zip(&budgets) {
            let total: f64 = class_picks.iter().map(|p| p.1).sum();
            if *b <= 1e-9 || total <= 0.0 {
                continue;
            }
            for (sid, sc, why) in class_picks {
                let w = b * sc / total;
                picks.push((sid, w, format!("{why}; its class ({}) gets {:.0} % of the portfolio by evidence", class_label(*c), b * 100.0)));
            }
        }
        Ok(PortfolioPick { picks, budgets: PORTFOLIO_CLASSES.iter().copied().zip(budgets).collect(), empty, passed_over })
    }

    /// A portfolio's class split as its sleeves hold it now, in
    /// [`PORTFOLIO_CLASSES`] order.
    fn ap_class_weights(&self, ap: &Autopilot) -> Vec<f64> {
        PORTFOLIO_CLASSES
            .iter()
            .map(|c| {
                ap.sleeves
                    .iter()
                    .filter(|s| self.strategy_class(&s.strategy_id) == Some(*c))
                    .map(|s| s.weight.max(0.0))
                    .sum()
            })
            .collect()
    }

    /// The blend's growth over its current stretch at these prices, or
    /// `None` while a weighted leg has no price.
    fn blend_growth(&self, ap: &Autopilot, b: &BlendBench, btc: Option<f64>, spy: Option<f64>) -> Option<f64> {
        let mut g = 1.0;
        for (w, p0, p1) in [(b.w_btc, b.btc_ref.or(ap.btc_start), btc), (b.w_spy, b.spy_ref.or(ap.spy_start), spy)] {
            if w > 1e-9 {
                g += w * leg_return(p0, p1)? / 100.0;
            }
        }
        Some(g)
    }

    /// A portfolio's class budgets moved: close the blend's stretch at the
    /// prices now and go on at the new weights. Kept as it is (and said so)
    /// while a newly weighted leg has no price to start from.
    fn ap_blend_relink(&mut self, i: usize, now: i64) {
        let ap = &self.autopilots[i];
        if !ap.config.portfolio {
            return;
        }
        let w = self.ap_class_weights(ap);
        let (w_btc, w_spy) = (w[0], w[1]);
        let btc = self.ap_btc_price(ap);
        let spy = self.ap_spy_price();
        let Some(b) = ap.blend.clone() else {
            self.autopilots[i].blend = Some(BlendBench { index: 1.0, since_ms: now, w_btc, w_spy, btc_ref: None, spy_ref: None });
            return;
        };
        if (b.w_btc - w_btc).abs() < 1e-9 && (b.w_spy - w_spy).abs() < 1e-9 {
            return;
        }
        let growth = self.blend_growth(ap, &b, btc, spy);
        let priced = (w_btc <= 1e-9 || btc.is_some()) && (w_spy <= 1e-9 || spy.is_some());
        let Some(growth) = growth.filter(|_| priced) else {
            let msg = format!(
                "{}: its blended benchmark keeps the weights {:.0} % BTC, {:.0} % SPY for now: a price it needs is not known yet.",
                ap.label(),
                b.w_btc * 100.0,
                b.w_spy * 100.0
            );
            self.log(JournalKind::System, msg, None, None);
            return;
        };
        self.autopilots[i].blend = Some(BlendBench { index: b.index * growth, since_ms: now, w_btc, w_spy, btc_ref: btc, spy_ref: spy });
    }

    /// A portfolio's blended benchmark, as the UI shows it.
    fn ap_blend_status(&self, ap: &Autopilot, equity: f64) -> Option<BenchmarkStatus> {
        let b = ap.blend.as_ref()?;
        let active = ap.is_active();
        let btc = if active { self.ap_btc_price(ap) } else { ap.btc_end };
        let spy = if active { self.ap_spy_price() } else { ap.spy_end };
        let ret = self.blend_growth(ap, b, btc, spy).map(|g| (b.index * g - 1.0) * 100.0);
        let from = [(b.w_btc, ap.btc_from_ms), (b.w_spy, ap.spy_from_ms)]
            .into_iter()
            .filter(|(w, _)| *w > 1e-9)
            .filter_map(|(_, t)| t)
            .max();
        let base = match from {
            Some(t) => ap.history.iter().find(|h| h.0 >= t).map(|h| h.1).unwrap_or(equity),
            None => ap.start_capital,
        };
        let own = if base > 0.0 { (equity / base - 1.0) * 100.0 } else { 0.0 };
        let note = (!ap.bench_notes.is_empty()).then(|| ap.bench_notes.join(" "));
        Some(BenchmarkStatus {
            symbol: format!("{BTC_SYMBOL}+SPY"),
            name: format!("Blend of {:.0} % BTC and {:.0} % SPY, bought and held", b.w_btc * 100.0, b.w_spy * 100.0),
            return_pct: ret,
            excess_pct: ret.map(|r| own - r),
            from_ms: from,
            note,
            legs: vec![
                BenchmarkLeg { symbol: BTC_SYMBOL.into(), weight: b.w_btc, return_pct: leg_return(b.btc_ref.or(ap.btc_start), btc) },
                BenchmarkLeg { symbol: "SPY".into(), weight: b.w_spy, return_pct: leg_return(b.spy_ref.or(ap.spy_start), spy) },
            ],
        })
    }

    /// The checks only a portfolio has, before the start's own: paper or
    /// demo, picked by Pythia, both classes on the Alpaca account.
    fn portfolio_preflight(&self, cfg: &mut AutopilotConfig) -> Result<(), String> {
        if cfg.mode == AutopilotMode::Live {
            return Err("A portfolio across asset classes runs on paper or demo only. Live stays with autopilots of one asset class, behind every gate they have.".into());
        }
        if !cfg.sleeves.is_empty() {
            return Err("Pythia picks a portfolio's lab books by evidence, class by class: leave the strategies empty.".into());
        }
        if cfg.mode == AutopilotMode::Demo {
            if !self.demo_venues.contains(&Venue::Alpaca) {
                return Err("A demo portfolio trades on the Alpaca paper account: add the Alpaca paper keys first (docs/DEMO.md says how).".into());
            }
            if !self.crypto_demo_on_alpaca() {
                return Err("A demo portfolio trades both classes on the Alpaca paper account, so crypto demo orders have to go there too: set PYTHIA_DEMO_EXCHANGE=alpaca (docs/DEMO.md says how), or run the portfolio on paper.".into());
            }
        }
        // Both classes trade on the Alpaca account; crypto's prices still
        // come from the crypto feeds.
        cfg.venue = CostVenue::Alpaca.id().to_string();
        cfg.asset_class = None;
        Ok(())
    }

    /// A portfolio's asset classes, as the UI shows them.
    fn ap_class_statuses(&self, ap: &Autopilot) -> Vec<ClassStatus> {
        if !ap.config.portfolio {
            return Vec::new();
        }
        PORTFOLIO_CLASSES
            .iter()
            .map(|&c| {
                let sleeves: Vec<&Sleeve> = ap.sleeves.iter().filter(|s| self.strategy_class(&s.strategy_id) == Some(c)).collect();
                let weight: f64 = sleeves.iter().map(|s| s.weight.max(0.0)).sum();
                let pnl: f64 = sleeves.iter().map(|s| s.realized - s.fees + self.ap_unrealized(ap, Some(&s.strategy_id))).sum();
                let books = sleeves.iter().filter(|s| s.weight > 0.0).count();
                let note = if books == 0 {
                    Some(format!(
                        "No lab book of {} has evidence now, so it gets nothing; it joins at a re-pick once one does.",
                        asset_words(c)
                    ))
                } else if c == Venue::Alpaca && ap.state == AutopilotState::Running {
                    match self.lab_equity_session_wait() {
                        Some(why) => Some(format!("Rebalances only in the regular session: {why}.")),
                        None => ap.class_notes.get(class_key(c)).map(|n| format!("In cash: {n}.")),
                    }
                } else {
                    ap.class_notes.get(class_key(c)).map(|n| format!("In cash: {n}."))
                };
                ClassStatus {
                    class: c,
                    label: class_label(c).into(),
                    weight,
                    pnl,
                    exposure: self.ap_class_gross(ap, |v| v == c),
                    books,
                    note,
                }
            })
            .collect()
    }

    /// Re-run the auto pick with fresh evidence, when it is due: an
    /// auto-pick autopilot, running, `repick_every_hours` since the last pick.
    ///
    /// Only lab books are re-picked, because only they can change gradually:
    /// their targets are netted per coin, so a new weight is a new netted
    /// target that the next rebalance trades toward by the difference only.
    /// A book that drops out keeps its record at weight zero and its coins
    /// are sold down only as far as the books that stay do not want them;
    /// nothing is sold off at once. A built-in owns its positions outright,
    /// so an autopilot running built-ins keeps them as they are. Live never
    /// adds a strategy the owner did not confirm at the start; it may only
    /// re-weight or drop the ones it has. Journaled with the reasons.
    pub(super) fn ap_repick(&mut self, i: usize, now: i64) {
        let ap = &self.autopilots[i];
        if ap.state != AutopilotState::Running || !ap.config.sleeves.is_empty() {
            return;
        }
        let Some(hours) = ap.config.repick_every_hours.filter(|h| *h > 0.0) else { return };
        if now - ap.last_pick_ms.unwrap_or(ap.started_ms) < (hours * 3_600_000.0) as i64 {
            return;
        }
        self.autopilots[i].last_pick_ms = Some(now);
        let ap = &self.autopilots[i];
        let Some(venue) = config_venue(&ap.config) else { return };
        let mode = ap.config.mode;
        let label = ap.label();
        let current: Vec<(String, String, f64)> =
            ap.sleeves.iter().map(|s| (s.strategy_id.clone(), s.name.clone(), s.weight)).collect();
        if current.iter().any(|(sid, _, w)| *w > 0.0 && !self.is_lab_book(sid)) {
            return;
        }
        let own: HashSet<String> = current.iter().map(|c| c.0.clone()).collect();
        let busy = self.busy_strategies(mode, Some(&ap.config.id));
        let taken: HashSet<String> = HashSet::new();
        let max = ap.config.max_sleeves.unwrap_or(AUTO_MAX_SLEEVES);
        let portfolio = ap.config.portfolio;
        let split_before = self.ap_class_weights(ap);
        let picked = if portfolio {
            self.portfolio_pick(mode, &busy, &own, max, Some(&split_before)).map(|p| p.picks)
        } else {
            self.auto_pick(venue, mode, &busy, &taken, &own, max, false).map(|(p, _)| p)
        };
        let picks = match picked {
            Ok(p) => p,
            Err(why) => {
                let msg = format!("{label} re-ran its pick and keeps its strategies as they are: {why}");
                self.autopilots[i].last_action = Some(msg.clone());
                self.log(JournalKind::System, msg, None, None);
                return;
            }
        };
        let mut picks: Vec<(String, f64, String)> = picks.into_iter().filter(|(sid, ..)| self.is_lab_book(sid)).collect();
        if mode == AutopilotMode::Live {
            picks.retain(|(sid, ..)| own.contains(sid));
        }
        if picks.is_empty() {
            let msg = format!(
                "{label} re-ran its pick and keeps its strategies as they are: no lab book with positive evidence is free to take their place."
            );
            self.autopilots[i].last_action = Some(msg.clone());
            self.log(JournalKind::System, msg, None, None);
            return;
        }
        let total: f64 = picks.iter().map(|p| p.1).sum();
        let target: BTreeMap<String, (f64, String)> =
            picks.iter().map(|(sid, sc, why)| (sid.clone(), (sc / total, why.clone()))).collect();
        let shift = current
            .iter()
            .map(|(sid, _, w)| (target.get(sid).map_or(0.0, |t| t.0) - w).abs())
            .chain(target.iter().filter(|(sid, _)| !own.contains(*sid)).map(|(_, t)| t.0))
            .fold(0.0_f64, f64::max);
        if shift <= REPICK_MIN_SHIFT {
            let msg = format!(
                "{label} re-ran its pick with fresh evidence: the same strategies, no weight moving by more than {} points, so nothing changes.",
                pct(REPICK_MIN_SHIFT * 100.0)
            );
            self.log(JournalKind::System, msg, None, None);
            return;
        }

        // Apply: new weights, new books in, dropped books at zero.
        let mut parts: Vec<String> = Vec::new();
        let want_state = if mode == AutopilotMode::Live { StrategyState::Live } else { StrategyState::Paper };
        for (sid, name, was) in &current {
            let (w, why) = target.get(sid).cloned().unwrap_or((0.0, String::new()));
            let s = self.autopilots[i].sleeve_mut(sid).expect("current sleeves exist");
            s.weight = w;
            if w > 0.0 {
                s.dropped_ms = None;
                s.why = format!("{why}; re-picked to {:.0} % of the capital, netted per coin with the other lab books.", w * 100.0);
                parts.push(format!("{name} {:.0} % (was {:.0} %)", w * 100.0, was * 100.0));
            } else if *was > 0.0 {
                s.dropped_ms = Some(now);
                s.why = format!(
                    "Dropped at the re-pick of {}: another lab book has better evidence now. Its coins are sold down by the next netted rebalance only as far as the books that stay do not want them.",
                    chrono::DateTime::from_timestamp_millis(now).map(|t| t.format("%Y-%m-%d %H:%M UTC").to_string()).unwrap_or_default()
                );
                parts.push(format!("{name} dropped (was {:.0} %)", was * 100.0));
            }
        }
        for (sid, (w, why)) in target.iter().filter(|(sid, _)| !own.contains(*sid)) {
            let Some(s) = self.strategies.iter().find(|s| &s.id == sid) else { continue };
            let markets = self.sleeve_universe(s, mode);
            let (name, prior) = (s.name.clone(), s.state);
            self.autopilots[i].sleeves.push(Sleeve {
                strategy_id: sid.clone(),
                name: name.clone(),
                weight: *w,
                markets,
                why: format!("{why}; added at a re-pick with {:.0} % of the capital, netted per coin with the other lab books.", w * 100.0),
                realized: 0.0,
                fees: 0.0,
                trades: 0,
                prior_state: prior,
                dropped_ms: None,
            });
            if prior != want_state {
                self.apply_strategy_state(sid, want_state);
            }
            parts.push(format!("{name} {:.0} % (new)", w * 100.0));
        }
        // The netted target changes now, so the next rebalance runs now:
        // it trades only the difference per coin.
        let members: Vec<String> = self.autopilots[i].sleeves.iter().map(|s| s.strategy_id.clone()).collect();
        let book = self.autopilots[i].config.id.clone();
        for sid in &members {
            self.lab_done.remove(&super::pos_key(&book, sid));
            self.lab_retry.remove(&super::pos_key(&book, sid));
        }
        let mut msg = format!(
            "{label} re-ran its pick with fresh evidence and changed its lab books: {}. The new weights are netted into one target per coin at the next rebalance, which trades only the difference; nothing is sold off at once.",
            parts.join(", ")
        );
        if portfolio {
            let split: Vec<String> = PORTFOLIO_CLASSES
                .iter()
                .zip(self.ap_class_weights(&self.autopilots[i]).iter().zip(&split_before))
                .map(|(c, (w, was))| format!("{} {:.0} % (was {:.0} %)", class_label(*c), w * 100.0, was * 100.0))
                .collect();
            msg.push_str(&format!(
                " Split by evidence: {}; while both classes have evidence a class moves by at most {:.0} points a re-pick.",
                split.join(", "),
                PORTFOLIO_MAX_SHIFT * 100.0
            ));
            self.ap_blend_relink(i, now);
        }
        self.autopilots[i].last_action = Some(msg.clone());
        self.pending_alerts.push(msg.clone());
        self.log(JournalKind::System, msg, None, None);
    }
}
