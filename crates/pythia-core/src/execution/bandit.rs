//! Execution policy — learning how hard to push, from your own fills.
//!
//! `PROFIT-PLAN.md` §4 establishes that execution is the only *guaranteed*
//! alpha: it does not require being right about the market. Ten basis points
//! saved per round trip on a strategy doing 20 round trips a month is 24 points
//! a year, and unlike a forecast it does not depend on anyone's opinion.
//!
//! The question is one decision, made on every order: **how much of the spread
//! am I willing to pay to be sure of a fill?**
//!
//! ```text
//!   Passive  rest inside the spread   cheapest, may not fill
//!   Join     sit at the touch         middling
//!   Cross    take the offer           certain, most expensive
//! ```
//!
//! There is no universally right answer — it depends on the venue, on whether
//! the order is an exit that *must* happen, and on conditions that change. So
//! rather than hard-coding a rule, this learns one: a contextual bandit over the
//! three arms, rewarded by realised slippage against the price at the moment the
//! decision was made.
//!
//! ## Why Thompson sampling
//!
//! The alternative — always pick the arm with the best average so far — stops
//! exploring the moment one arm gets lucky early, and never discovers it was
//! luck. Thompson sampling draws each arm's reward from its posterior and picks
//! the winner of that draw, so an arm with few observations keeps getting tried
//! in proportion to how plausible it is that it is best. Exploration falls off
//! by itself as the estimates sharpen; there is no schedule to tune.
//!
//! ## What it cannot do yet
//!
//! The context is deliberately coarse — venue and urgency — because that is what
//! the engine reliably knows. Spread and depth are the features that would make
//! this genuinely sharp. The engine now has them for bar-backed crypto markets
//! (`crate::orderbook`), and they already price the cross arm's expected cost,
//! but they are not context yet: each extra dimension splits evidence the
//! bandit does not have, and it has no live fills at all so far. Adding them is
//! a change to [`ExecContext`] and nothing else.

use serde::{Deserialize, Serialize};
use std::collections::HashMap;

use crate::connectors::{Side, Venue};
use crate::orderbook::CostSource;

/// How aggressively to work one order.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum ExecStyle {
    /// Rest inside the spread and wait. Cheapest when it fills, nothing when it
    /// does not.
    Passive,
    /// Sit at the touch — fills on any move toward us.
    Join,
    /// Take what is offered. Certain, and pays the full spread.
    Cross,
}

impl ExecStyle {
    pub const ALL: [ExecStyle; 3] = [ExecStyle::Passive, ExecStyle::Join, ExecStyle::Cross];

    pub fn as_str(self) -> &'static str {
        match self {
            ExecStyle::Passive => "passive",
            ExecStyle::Join => "join",
            ExecStyle::Cross => "cross",
        }
    }

    /// Limit price for this style, or `None` for a market order.
    ///
    /// `patience_bps` is how far inside the arrival price a passive order rests.
    /// A buy wants to pay *less*, a sell wants to receive *more*, so the sign
    /// follows the side.
    pub fn limit_price(self, side: Side, arrival: f64, patience_bps: f64) -> Option<f64> {
        let edge = patience_bps / 10_000.0;
        match self {
            ExecStyle::Cross => None,
            ExecStyle::Join => Some(arrival),
            ExecStyle::Passive => Some(match side {
                Side::Buy => arrival * (1.0 - edge),
                Side::Sell => arrival * (1.0 + edge),
            }),
        }
    }
}

/// The situation a decision is made in.
///
/// Kept small on purpose: every extra dimension splits the evidence, and a
/// bandit with 200 contexts and 300 fills has learned nothing about any of them.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ExecContext {
    pub venue: Venue,
    /// This order closes a position. Not filling is a real cost — the position
    /// stays on, exposed — so the bandit should learn to pay up here.
    pub urgent: bool,
}

impl ExecContext {
    pub fn key(&self) -> String {
        format!("{:?}:{}", self.venue, if self.urgent { "urgent" } else { "normal" })
    }
}

/// Cost charged to an order that never filled, in basis points.
///
/// This number is the whole character of the policy. Too low and it learns that
/// resting passively forever is free; too high and it crosses everything. 40 bps
/// says: missing a trade is roughly as bad as paying a wide spread — which is
/// about right for a signal that was worth acting on at all.
const NO_FILL_PENALTY_BPS: f64 = 40.0;

/// Prior mean reward, in basis points of cost. Starting at "this will cost about
/// 8 bps" rather than 0 keeps a single lucky first fill from convincing the
/// bandit that an arm is free.
const PRIOR_COST_BPS: f64 = 8.0;

/// Weight of that prior, in pseudo-observations.
const PRIOR_STRENGTH: f64 = 3.0;

/// Assumed spread of per-fill costs. Used as the posterior scale, so the
/// exploration rate is sane before any variance has been observed.
const REWARD_SIGMA_BPS: f64 = 25.0;

/// Running estimate for one (context, arm).
#[derive(Debug, Clone, Copy, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ArmStat {
    /// Observations, including the prior's pseudo-count.
    pub n: f64,
    /// Mean cost in basis points. Lower is better.
    pub mean_cost_bps: f64,
    /// Real fills only — what the UI should show as evidence.
    pub fills: u32,
    /// How many of those never filled and took the penalty.
    pub misses: u32,
}

impl Default for ArmStat {
    fn default() -> Self {
        ArmStat { n: PRIOR_STRENGTH, mean_cost_bps: PRIOR_COST_BPS, fills: 0, misses: 0 }
    }
}

impl ArmStat {
    fn observe(&mut self, cost_bps: f64, filled: bool) {
        self.n += 1.0;
        self.mean_cost_bps += (cost_bps - self.mean_cost_bps) / self.n;
        if filled {
            self.fills += 1;
        } else {
            self.misses += 1;
        }
    }

    /// Posterior standard error of the mean. Shrinks as evidence accumulates,
    /// which is what makes exploration taper off on its own.
    fn stderr(&self) -> f64 {
        REWARD_SIGMA_BPS / self.n.sqrt()
    }

    /// Observations excluding the prior.
    pub fn observations(&self) -> u32 {
        self.fills + self.misses
    }
}

/// The learner. Persisted with the engine — a bandit that forgets on restart
/// never gets past exploring.
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct ExecPolicy {
    /// `"Alpaca:normal" → { passive, join, cross }`
    stats: HashMap<String, HashMap<String, ArmStat>>,
    /// How far inside the arrival price a passive order rests.
    #[serde(default = "default_patience")]
    patience_bps: f64,
    /// Off by default — every order crosses, exactly as before. Turning it on is
    /// a deliberate choice, because a passive order that does not fill is a
    /// signal acted on late or not at all.
    #[serde(default)]
    pub enabled: bool,
    #[serde(default = "default_seed")]
    rng: u64,
    /// Realised slippage per filled live order, next to what the cost model
    /// expected, keyed by cost venue (`kraken`, `alpaca`…). The arm statistics
    /// above keep only running means; comparing realised against modelled
    /// needs the individual fills, so the medians are robust to one bad print.
    #[serde(default)]
    fills: HashMap<String, Vec<FillRecord>>,
    /// Paper and demo fills, keyed `"{route}:{venue}"`, bounded separately
    /// from the live ones above. They never teach the bandit: a demo book or
    /// Pythia's own book walk says nothing about how a resting order would
    /// have done at the real venue.
    #[serde(default)]
    route_fills: HashMap<String, Vec<FillRecord>>,
}

/// Where a fill's price came from. The one label every fill record, order row
/// and slippage row carries, so paper, demo and live can be compared per
/// strategy and per venue.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum FillRoute {
    /// Simulated by Pythia: the live book walked, or the cost model.
    Paper,
    /// A venue's demo or paper environment answered: real API round trip,
    /// virtual money. Never in the tax record.
    Demo,
    /// A real fill with real money.
    Live,
}

impl FillRoute {
    pub fn as_str(self) -> &'static str {
        match self {
            FillRoute::Paper => "paper",
            FillRoute::Demo => "demo",
            FillRoute::Live => "live",
        }
    }
}

/// Records from before routes existed were all live-path fills.
fn live_route() -> FillRoute {
    FillRoute::Live
}

/// One fill's execution cost: what it paid against the arrival (signal)
/// price, and what the cost model said it would.
#[derive(Debug, Clone, Copy, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct FillRecord {
    /// Signed bps against arrival; positive means it cost us.
    pub realised_bps: f64,
    /// The model's half-spread plus impact for this order, in bps.
    pub modelled_bps: f64,
    pub ts: i64,
    /// Whether `modelled_bps` came from a live book or the calibrated default.
    /// Records from before live books existed were all modelled on the default.
    #[serde(default)]
    pub source: CostSource,
    /// Paper, demo or live.
    #[serde(default = "live_route")]
    pub route: FillRoute,
    /// How far the book's mid had moved from the signal price when the order
    /// was priced, signed like `realised_bps` (positive: the market moved
    /// against us before we traded). `None` without a fresh book.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub drift_bps: Option<f64>,
    /// A paper fill that ran past the 20 book levels and priced the rest with
    /// the impact model.
    #[serde(default, skip_serializing_if = "std::ops::Not::not")]
    pub book_exhausted: bool,
}

impl FillRecord {
    /// A record with no drift and no exhausted book, the shape of every live
    /// fill so far.
    pub fn new(realised_bps: f64, modelled_bps: f64, ts: i64, source: CostSource, route: FillRoute) -> Self {
        FillRecord { realised_bps, modelled_bps, ts, source, route, drift_bps: None, book_exhausted: false }
    }
}

/// Fills kept per venue and route. Old enough fills describe a market that
/// has moved on, and paper fills, which come every few seconds, must never
/// push the rare live ones out.
const MAX_FILLS_PER_VENUE: usize = 1000;

/// Below this many fills the realised/modelled comparison is shown but not
/// trusted (`PROFIT-PLAN.md` §1: "after 30 fills").
pub const MIN_FILLS_FOR_VERDICT: usize = 30;

/// Realised cost of a fill against the arrival price, in bps, signed so that
/// positive always means it cost us. `None` for a price that cannot be priced.
pub fn realised_cost_bps(side: Side, arrival: f64, filled: f64) -> Option<f64> {
    if !(arrival > 0.0 && filled > 0.0) {
        return None;
    }
    let raw = (filled - arrival) / arrival * 10_000.0;
    Some(match side {
        Side::Buy => raw,
        Side::Sell => -raw,
    })
}

fn median(xs: &mut [f64]) -> f64 {
    if xs.is_empty() {
        return 0.0;
    }
    xs.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
    let m = xs.len() / 2;
    if xs.len() % 2 == 1 {
        xs[m]
    } else {
        (xs[m - 1] + xs[m]) / 2.0
    }
}

/// Per-venue realised-versus-modelled slippage.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SlippageRow {
    /// Cost venue key, e.g. `kraken` or `alpaca`.
    pub venue: String,
    pub fills: usize,
    pub median_realised_bps: f64,
    pub median_modelled_bps: f64,
    /// Realised over modelled. `None` when the model expected nothing, which
    /// makes a ratio meaningless.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub ratio: Option<f64>,
    /// At least [`MIN_FILLS_FOR_VERDICT`] fills behind the medians.
    pub enough: bool,
    /// How many of `fills` were modelled on a fresh live book rather than the
    /// calibrated default. Each fill is compared against the model it was
    /// actually given, so the medians mix both; this says in what proportion.
    #[serde(default)]
    pub live_fills: usize,
    /// Which fills this row is about. Saves and clients from before routes
    /// existed only ever had live rows.
    #[serde(default = "live_route")]
    pub route: FillRoute,
    /// Median drift between the signal price and the book's mid when the
    /// order was priced, over the fills that had a fresh book.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub median_drift_bps: Option<f64>,
    /// Paper fills that ran past the 20 book levels.
    #[serde(default)]
    pub exhausted: usize,
}

/// One row from a set of fill records; `None` when there are none.
fn slippage_row(venue: &str, route: FillRoute, f: &[&FillRecord]) -> Option<SlippageRow> {
    if f.is_empty() {
        return None;
    }
    let mut realised: Vec<f64> = f.iter().map(|r| r.realised_bps).collect();
    let mut modelled: Vec<f64> = f.iter().map(|r| r.modelled_bps).collect();
    let mut drift: Vec<f64> = f.iter().filter_map(|r| r.drift_bps).collect();
    let mr = median(&mut realised);
    let mm = median(&mut modelled);
    Some(SlippageRow {
        venue: venue.to_string(),
        fills: f.len(),
        median_realised_bps: mr,
        median_modelled_bps: mm,
        ratio: (mm > 1e-9).then(|| mr / mm),
        enough: f.len() >= MIN_FILLS_FOR_VERDICT,
        live_fills: f.iter().filter(|r| r.source == CostSource::Live).count(),
        route,
        median_drift_bps: (!drift.is_empty()).then(|| median(&mut drift)),
        exhausted: f.iter().filter(|r| r.book_exhausted).count(),
    })
}

fn default_patience() -> f64 {
    12.0
}
fn default_seed() -> u64 {
    0x2545_F491_4F6C_DD1D
}

impl ExecPolicy {
    pub fn new(enabled: bool) -> Self {
        ExecPolicy { enabled, patience_bps: default_patience(), rng: default_seed(), ..Default::default() }
    }

    pub fn patience_bps(&self) -> f64 {
        self.patience_bps
    }

    /// xorshift64* — deterministic, seeded, and enough for Thompson draws.
    fn next_f64(&mut self) -> f64 {
        let mut x = self.rng;
        x ^= x >> 12;
        x ^= x << 25;
        x ^= x >> 27;
        self.rng = x;
        (x.wrapping_mul(0x2545_F491_4F6C_DD1D) >> 11) as f64 / (1u64 << 53) as f64
    }

    /// Standard normal via Box–Muller.
    fn gaussian(&mut self) -> f64 {
        let u1 = self.next_f64().max(1e-12);
        let u2 = self.next_f64();
        (-2.0 * u1.ln()).sqrt() * (2.0 * std::f64::consts::PI * u2).cos()
    }

    pub fn stat(&self, ctx: &ExecContext, arm: ExecStyle) -> ArmStat {
        self.stats
            .get(&ctx.key())
            .and_then(|m| m.get(arm.as_str()))
            .copied()
            .unwrap_or_default()
    }

    /// Pick a style by Thompson sampling: draw each arm's plausible cost from
    /// its posterior and take the cheapest draw.
    pub fn choose(&mut self, ctx: &ExecContext) -> ExecStyle {
        if !self.enabled {
            return ExecStyle::Cross;
        }
        let mut best = ExecStyle::Cross;
        let mut best_draw = f64::INFINITY;
        for arm in ExecStyle::ALL {
            let s = self.stat(ctx, arm);
            let draw = s.mean_cost_bps + self.gaussian() * s.stderr();
            if draw < best_draw {
                best_draw = draw;
                best = arm;
            }
        }
        best
    }

    /// Feed back what an order actually cost.
    ///
    /// `arrival` is the price when the decision was made, `filled_price` what we
    /// got. Cost is signed so that paying more than arrival is positive for a
    /// buy and receiving less than arrival is positive for a sell — in both
    /// cases, positive means it cost us.
    pub fn observe(
        &mut self,
        ctx: &ExecContext,
        arm: ExecStyle,
        side: Side,
        arrival: f64,
        filled_price: Option<f64>,
    ) {
        let cost = match filled_price.and_then(|p| realised_cost_bps(side, arrival, p)) {
            Some(c) => c,
            // Never filled. The trade did not happen, and that is not free.
            None => NO_FILL_PENALTY_BPS,
        };
        self.stats
            .entry(ctx.key())
            .or_default()
            .entry(arm.as_str().to_string())
            .or_default()
            .observe(cost, filled_price.is_some());
    }

    /// [`ExecPolicy::observe`], plus keep the fill for the realised-versus-
    /// modelled comparison. `venue` is the cost venue key, `modelled_bps` the
    /// cost model's expected slippage for this order and `source` whether that
    /// expectation came from a live book. Orders that never filled teach the
    /// bandit but are not slippage: there was no fill price.
    #[allow(clippy::too_many_arguments)]
    pub fn observe_against_model(
        &mut self,
        ctx: &ExecContext,
        arm: ExecStyle,
        side: Side,
        arrival: f64,
        filled_price: Option<f64>,
        venue: &str,
        modelled_bps: f64,
        source: CostSource,
        ts: i64,
    ) -> Option<f64> {
        self.observe(ctx, arm, side, arrival, filled_price);
        let realised = filled_price.and_then(|p| realised_cost_bps(side, arrival, p))?;
        let list = self.fills.entry(venue.to_string()).or_default();
        list.push(FillRecord::new(realised, modelled_bps, ts, source, FillRoute::Live));
        if list.len() > MAX_FILLS_PER_VENUE {
            let excess = list.len() - MAX_FILLS_PER_VENUE;
            list.drain(..excess);
        }
        Some(realised)
    }

    /// Keep a paper or demo fill for the comparison, without teaching the
    /// bandit. A record marked live goes to the live list, which is what
    /// [`ExecPolicy::observe_against_model`] fills; prefer that for live.
    pub fn record_fill(&mut self, venue: &str, rec: FillRecord) {
        let list = match rec.route {
            FillRoute::Live => self.fills.entry(venue.to_string()).or_default(),
            r => self.route_fills.entry(format!("{}:{venue}", r.as_str())).or_default(),
        };
        list.push(rec);
        if list.len() > MAX_FILLS_PER_VENUE {
            let excess = list.len() - MAX_FILLS_PER_VENUE;
            list.drain(..excess);
        }
    }

    /// Realised against modelled slippage, one row per venue and route with
    /// fills, live rows first within a venue.
    pub fn slippage_report(&self) -> Vec<SlippageRow> {
        let live = self.fills.iter().map(|(venue, f)| (venue.clone(), FillRoute::Live, f.iter().collect::<Vec<_>>()));
        let other = self.route_fills.iter().filter_map(|(key, f)| {
            let (route, venue) = key.split_once(':')?;
            let route = match route {
                "paper" => FillRoute::Paper,
                "demo" => FillRoute::Demo,
                _ => return None,
            };
            Some((venue.to_string(), route, f.iter().collect::<Vec<_>>()))
        });
        let mut out: Vec<SlippageRow> =
            live.chain(other).filter_map(|(venue, route, f)| slippage_row(&venue, route, &f)).collect();
        let rank = |r: FillRoute| match r {
            FillRoute::Live => 0,
            FillRoute::Demo => 1,
            FillRoute::Paper => 2,
        };
        out.sort_by(|a, b| a.venue.cmp(&b.venue).then(rank(a.route).cmp(&rank(b.route))));
        out
    }

    /// The evidence the Strategy Passport judges slippage on for one venue:
    /// every fill a venue actually reported, live and demo together. Paper
    /// fills are Pythia's own arithmetic and never count here.
    pub fn slippage_for(&self, venue: &str) -> Option<SlippageRow> {
        let mut recs: Vec<&FillRecord> = self.fills.get(venue).map(|f| f.iter().collect()).unwrap_or_default();
        if let Some(d) = self.route_fills.get(&format!("demo:{venue}")) {
            recs.extend(d.iter());
        }
        slippage_row(venue, FillRoute::Live, &recs)
    }

    /// Everything learned so far, for the UI.
    pub fn report(&self) -> Vec<PolicyRow> {
        let mut out: Vec<PolicyRow> = self
            .stats
            .iter()
            .flat_map(|(ctx, arms)| {
                arms.iter().map(move |(arm, s)| PolicyRow {
                    context: ctx.clone(),
                    style: arm.clone(),
                    mean_cost_bps: s.mean_cost_bps,
                    fills: s.fills,
                    misses: s.misses,
                })
            })
            .filter(|r| r.fills + r.misses > 0)
            .collect();
        out.sort_by(|a, b| {
            a.context
                .cmp(&b.context)
                .then(a.mean_cost_bps.partial_cmp(&b.mean_cost_bps).unwrap_or(std::cmp::Ordering::Equal))
        });
        out
    }
}

/// One learned (context, style) row.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct PolicyRow {
    pub context: String,
    pub style: String,
    pub mean_cost_bps: f64,
    pub fills: u32,
    pub misses: u32,
}

#[cfg(test)]
mod tests {
    use super::*;

    fn ctx() -> ExecContext {
        ExecContext { venue: Venue::Alpaca, urgent: false }
    }

    #[test]
    fn a_passive_buy_bids_below_arrival_and_a_passive_sell_offers_above() {
        let buy = ExecStyle::Passive.limit_price(Side::Buy, 100.0, 20.0).unwrap();
        let sell = ExecStyle::Passive.limit_price(Side::Sell, 100.0, 20.0).unwrap();
        assert!((buy - 99.8).abs() < 1e-9, "a buyer wants to pay less: {buy}");
        assert!((sell - 100.2).abs() < 1e-9, "a seller wants to receive more: {sell}");

        assert_eq!(ExecStyle::Join.limit_price(Side::Buy, 100.0, 20.0), Some(100.0));
        assert_eq!(ExecStyle::Cross.limit_price(Side::Buy, 100.0, 20.0), None, "crossing is a market order");
    }

    #[test]
    fn cost_is_positive_whenever_the_fill_was_worse_than_arrival() {
        let mut p = ExecPolicy::new(true);
        // Bought above arrival — that cost us.
        p.observe(&ctx(), ExecStyle::Cross, Side::Buy, 100.0, Some(100.1));
        assert!(p.stat(&ctx(), ExecStyle::Cross).mean_cost_bps > PRIOR_COST_BPS);

        // Sold above arrival — that earned us.
        let mut q = ExecPolicy::new(true);
        q.observe(&ctx(), ExecStyle::Cross, Side::Sell, 100.0, Some(100.1));
        assert!(q.stat(&ctx(), ExecStyle::Cross).mean_cost_bps < PRIOR_COST_BPS);
    }

    #[test]
    fn not_filling_is_charged_rather_than_ignored() {
        let mut p = ExecPolicy::new(true);
        p.observe(&ctx(), ExecStyle::Passive, Side::Buy, 100.0, None);
        let s = p.stat(&ctx(), ExecStyle::Passive);
        assert_eq!(s.misses, 1);
        assert_eq!(s.fills, 0);
        assert!(
            s.mean_cost_bps > PRIOR_COST_BPS,
            "a miss must look expensive, or resting forever looks free: {}",
            s.mean_cost_bps
        );
    }

    #[test]
    fn the_policy_learns_which_arm_is_cheaper() {
        let mut p = ExecPolicy::new(true);
        // All three tried, so the choice is about what was learned rather than
        // about an arm nobody has data on. Passive fills 2bps better than
        // arrival, joining costs 5, crossing costs 15.
        for _ in 0..200 {
            p.observe(&ctx(), ExecStyle::Passive, Side::Buy, 100.0, Some(99.98));
            p.observe(&ctx(), ExecStyle::Join, Side::Buy, 100.0, Some(100.05));
            p.observe(&ctx(), ExecStyle::Cross, Side::Buy, 100.0, Some(100.15));
        }
        assert!(p.stat(&ctx(), ExecStyle::Passive).mean_cost_bps < 0.0);
        assert!(p.stat(&ctx(), ExecStyle::Cross).mean_cost_bps > 10.0);

        let picks = (0..200).filter(|_| p.choose(&ctx()) == ExecStyle::Passive).count();
        assert!(picks > 180, "with all arms measured it should settle, got {picks}/200");
    }

    /// The flip side of the test above, and the reason Thompson sampling is
    /// worth the trouble: an arm nobody has tried keeps a wide posterior, so it
    /// keeps getting sampled even when another arm looks good. A greedy policy
    /// would never find out whether the untried one was better.
    #[test]
    fn an_untried_arm_keeps_being_sampled_even_against_a_measured_winner() {
        let mut p = ExecPolicy::new(true);
        for _ in 0..200 {
            p.observe(&ctx(), ExecStyle::Passive, Side::Buy, 100.0, Some(99.98));
            p.observe(&ctx(), ExecStyle::Cross, Side::Buy, 100.0, Some(100.15));
        }
        // `Join` has never been tried. It should still get a real share.
        let joins = (0..200).filter(|_| p.choose(&ctx()) == ExecStyle::Join).count();
        assert!(joins > 10, "an untried arm must still be explored, got {joins}/200");
        assert!(joins < 100, "but not preferred over a measured winner, got {joins}/200");
    }

    #[test]
    fn an_arm_that_never_fills_is_abandoned_even_though_it_never_paid_a_spread() {
        let mut p = ExecPolicy::new(true);
        for _ in 0..200 {
            p.observe(&ctx(), ExecStyle::Passive, Side::Buy, 100.0, None); // never fills
            p.observe(&ctx(), ExecStyle::Cross, Side::Buy, 100.0, Some(100.10));
        }
        let picks = (0..200).filter(|_| p.choose(&ctx()) == ExecStyle::Passive).count();
        assert!(picks < 40, "a limit that never fills is not cheap, got {picks}/200");
    }

    #[test]
    fn it_keeps_exploring_while_the_evidence_is_thin() {
        // The failure mode of greedy selection: one lucky early fill locks it in.
        let mut p = ExecPolicy::new(true);
        p.observe(&ctx(), ExecStyle::Join, Side::Buy, 100.0, Some(99.99));
        let mut seen = std::collections::HashSet::new();
        for _ in 0..200 {
            seen.insert(p.choose(&ctx()));
        }
        assert!(seen.len() >= 2, "one observation must not end exploration");
    }

    #[test]
    fn contexts_are_learned_separately() {
        let urgent = ExecContext { venue: Venue::Alpaca, urgent: true };
        let mut p = ExecPolicy::new(true);
        for _ in 0..100 {
            p.observe(&ctx(), ExecStyle::Passive, Side::Buy, 100.0, Some(99.95));
            p.observe(&urgent, ExecStyle::Passive, Side::Buy, 100.0, None);
        }
        assert!(p.stat(&ctx(), ExecStyle::Passive).mean_cost_bps < 0.0);
        assert!(
            p.stat(&urgent, ExecStyle::Passive).mean_cost_bps > 20.0,
            "an exit that will not fill is a different problem from an entry that will"
        );
        // A venue nobody has traded starts fresh rather than inheriting.
        let other = ExecContext { venue: Venue::Crypto, urgent: false };
        assert_eq!(p.stat(&other, ExecStyle::Passive).observations(), 0);
    }

    #[test]
    fn disabled_is_exactly_the_old_behaviour() {
        let mut p = ExecPolicy::new(false);
        for _ in 0..50 {
            assert_eq!(p.choose(&ctx()), ExecStyle::Cross, "off means market orders, as before");
        }
    }

    #[test]
    fn what_it_learned_survives_a_restart() {
        let mut p = ExecPolicy::new(true);
        for _ in 0..100 {
            p.observe(&ctx(), ExecStyle::Passive, Side::Buy, 100.0, Some(99.98));
        }
        let json = serde_json::to_string(&p).unwrap();
        let back: ExecPolicy = serde_json::from_str(&json).unwrap();
        assert_eq!(
            back.stat(&ctx(), ExecStyle::Passive).fills,
            100,
            "a bandit that forgets on restart never gets past exploring"
        );
        assert!(back.enabled);
    }

    #[test]
    fn the_report_lists_only_arms_with_real_evidence() {
        let mut p = ExecPolicy::new(true);
        assert!(p.report().is_empty(), "priors are not evidence");
        p.observe(&ctx(), ExecStyle::Cross, Side::Buy, 100.0, Some(100.1));
        let r = p.report();
        assert_eq!(r.len(), 1);
        assert_eq!(r[0].style, "cross");
        assert_eq!(r[0].fills, 1);
    }

    #[test]
    fn realised_slippage_is_kept_per_venue_next_to_the_model() {
        let mut p = ExecPolicy::new(false);
        assert!(p.slippage_report().is_empty(), "no fills, no row");
        // Three Kraken buys at 5, 10 and 30 bps worse than arrival; the model
        // expected 4 each time.
        // The middle one was modelled on a live book.
        for (i, px) in [100.05, 100.10, 100.30].into_iter().enumerate() {
            let src = if i == 1 { CostSource::Live } else { CostSource::Default };
            let got = p.observe_against_model(&ctx(), ExecStyle::Cross, Side::Buy, 100.0, Some(px), "kraken", 4.0, src, i as i64);
            assert!(got.is_some());
        }
        // A sell that received more than arrival is negative slippage.
        p.observe_against_model(&ctx(), ExecStyle::Cross, Side::Sell, 100.0, Some(100.02), "alpaca", 1.0, CostSource::Default, 9);
        // A miss teaches the bandit but is not a slippage observation.
        let miss = p.observe_against_model(&ctx(), ExecStyle::Passive, Side::Buy, 100.0, None, "kraken", 4.0, CostSource::Live, 10);
        assert!(miss.is_none());

        let r = p.slippage_report();
        assert_eq!(r.len(), 2);
        let k = r.iter().find(|x| x.venue == "kraken").unwrap();
        assert_eq!(k.fills, 3);
        assert!((k.median_realised_bps - 10.0).abs() < 1e-6, "median, not mean: {}", k.median_realised_bps);
        assert!((k.median_modelled_bps - 4.0).abs() < 1e-12);
        assert!((k.ratio.unwrap() - 2.5).abs() < 1e-6);
        assert!(!k.enough, "three fills is not a verdict");
        assert_eq!(k.live_fills, 1, "only the fill priced on a live book counts, not the miss");
        let a = r.iter().find(|x| x.venue == "alpaca").unwrap();
        assert!(a.median_realised_bps < 0.0);
        assert_eq!(a.live_fills, 0);
        // The bandit itself still learned from all five.
        assert_eq!(p.stat(&ctx(), ExecStyle::Cross).fills, 4);
        assert_eq!(p.stat(&ctx(), ExecStyle::Passive).misses, 1);
    }

    #[test]
    fn the_fill_record_survives_a_restart_and_stays_bounded() {
        let mut p = ExecPolicy::new(false);
        for i in 0..(MAX_FILLS_PER_VENUE + 50) {
            p.observe_against_model(&ctx(), ExecStyle::Cross, Side::Buy, 100.0, Some(100.01), "binance", 2.0, CostSource::Live, i as i64);
        }
        let back: ExecPolicy = serde_json::from_str(&serde_json::to_string(&p).unwrap()).unwrap();
        let row = back.slippage_for("binance").unwrap();
        assert_eq!(row.fills, MAX_FILLS_PER_VENUE);
        assert_eq!(row.live_fills, MAX_FILLS_PER_VENUE, "the source survives a restart");
        assert!(row.enough);
        // An old save with no fill record still loads.
        let old: ExecPolicy = serde_json::from_str(r#"{"stats":{},"enabled":false}"#).unwrap();
        assert!(old.slippage_report().is_empty());
        // Fill records from before live books load as modelled on the default.
        let older: ExecPolicy = serde_json::from_str(
            r#"{"stats":{},"enabled":false,"fills":{"kraken":[{"realisedBps":3.0,"modelledBps":2.0,"ts":1}]}}"#,
        )
        .unwrap();
        let k = older.slippage_for("kraken").unwrap();
        assert_eq!((k.fills, k.live_fills), (1, 0));
    }

    #[test]
    fn paper_and_demo_fills_get_their_own_rows_and_never_push_live_ones_out() {
        let mut p = ExecPolicy::new(true);
        p.observe_against_model(&ctx(), ExecStyle::Cross, Side::Buy, 100.0, Some(100.05), "bybit", 2.0, CostSource::Default, 1);
        // A flood of paper fills, far past the per-list cap.
        for i in 0..(MAX_FILLS_PER_VENUE + 10) {
            let mut r = FillRecord::new(3.0, 2.0, i as i64, CostSource::Live, FillRoute::Paper);
            r.drift_bps = Some(1.0);
            r.book_exhausted = i % 2 == 0;
            p.record_fill("bybit", r);
        }
        p.record_fill("bybit", FillRecord::new(8.0, 2.0, 5, CostSource::Default, FillRoute::Demo));

        let rows = p.slippage_report();
        let routes: Vec<FillRoute> = rows.iter().filter(|r| r.venue == "bybit").map(|r| r.route).collect();
        assert_eq!(routes, vec![FillRoute::Live, FillRoute::Demo, FillRoute::Paper], "live first, then demo, then paper");
        let live = rows.iter().find(|r| r.route == FillRoute::Live).unwrap();
        assert_eq!(live.fills, 1, "paper fills never evict the live record");
        let paper = rows.iter().find(|r| r.route == FillRoute::Paper).unwrap();
        assert_eq!(paper.fills, MAX_FILLS_PER_VENUE);
        assert_eq!(paper.median_drift_bps, Some(1.0));
        assert_eq!(paper.exhausted, MAX_FILLS_PER_VENUE / 2);

        // The passport sees what venues reported (live and demo), never paper.
        let judged = p.slippage_for("bybit").unwrap();
        assert_eq!(judged.fills, 2);
        // Paper and demo fills do not teach the bandit.
        assert_eq!(p.stat(&ctx(), ExecStyle::Cross).fills, 1);

        // Round trip, and an old save without routes still loads as live.
        let back: ExecPolicy = serde_json::from_str(&serde_json::to_string(&p).unwrap()).unwrap();
        assert_eq!(back.slippage_report().len(), 3);
        let old: ExecPolicy = serde_json::from_str(
            r#"{"stats":{},"enabled":false,"fills":{"kraken":[{"realisedBps":3.0,"modelledBps":2.0,"ts":1}]}}"#,
        )
        .unwrap();
        assert_eq!(old.slippage_report()[0].route, FillRoute::Live);
    }

    #[test]
    fn a_zero_or_negative_arrival_price_cannot_produce_a_nonsense_cost() {
        let mut p = ExecPolicy::new(true);
        p.observe(&ctx(), ExecStyle::Cross, Side::Buy, 0.0, Some(100.0));
        let s = p.stat(&ctx(), ExecStyle::Cross);
        assert!(s.mean_cost_bps.is_finite(), "got {}", s.mean_cost_bps);
    }
}
