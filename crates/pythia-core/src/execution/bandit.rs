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
//! the engine reliably knows. Spread and top-of-book depth are the features that
//! would make this genuinely sharp, and they need quote data the market feed does
//! not yet carry. Adding them later is a change to [`ExecContext`] and nothing
//! else.

use serde::{Deserialize, Serialize};
use std::collections::HashMap;

use crate::connectors::{Side, Venue};

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
        let cost = match filled_price {
            Some(p) if arrival > 0.0 && p > 0.0 => {
                let raw = (p - arrival) / arrival * 10_000.0;
                match side {
                    Side::Buy => raw,
                    Side::Sell => -raw,
                }
            }
            // Never filled. The trade did not happen, and that is not free.
            _ => NO_FILL_PENALTY_BPS,
        };
        self.stats
            .entry(ctx.key())
            .or_default()
            .entry(arm.as_str().to_string())
            .or_default()
            .observe(cost, filled_price.is_some());
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
    fn a_zero_or_negative_arrival_price_cannot_produce_a_nonsense_cost() {
        let mut p = ExecPolicy::new(true);
        p.observe(&ctx(), ExecStyle::Cross, Side::Buy, 0.0, Some(100.0));
        let s = p.stat(&ctx(), ExecStyle::Cross);
        assert!(s.mean_cost_bps.is_finite(), "got {}", s.mean_cost_bps);
    }
}
