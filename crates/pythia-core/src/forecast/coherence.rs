//! Coherence — the only edge on a prediction market that needs no forecast.
//!
//! Every other source in this module tries to be *smarter* than the market,
//! which is hard and usually fails. Coherence asks a different question: is the
//! market even consistent with **itself**?
//!
//! The outcomes of one event are mutually exclusive and exhaustive, so their
//! prices must sum to 1. When they sum to 0.94, buying every outcome costs 94
//! cents and pays exactly 1 dollar whatever happens. No opinion about the world
//! is involved — it is arithmetic, and it is the reason this check is worth more
//! than any number of clever models.
//!
//! It is also where the honesty lives: these gaps are usually smaller than the
//! spread you would cross to capture them. So every break is reported **net of
//! costs**, and a break that does not clear costs is reported as `actionable:
//! false` rather than quietly dropped — seeing near-misses is how you learn
//! whether the opportunity exists at your size at all.

use serde::{Deserialize, Serialize};

/// One leg of a coherence check: an outcome of an event and its current price.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Leg {
    pub market_id: String,
    pub outcome: String,
    /// Implied probability, 0..1.
    pub price: f64,
}

/// A set of mutually exclusive, exhaustive outcomes that must price to 1.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct OutcomeSet {
    pub event_id: String,
    pub title: String,
    pub legs: Vec<Leg>,
}

/// Which side of the inconsistency the money is on.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum BreakKind {
    /// Prices sum below 1 — buying every outcome locks in the difference.
    /// Requires only the ability to buy, which every venue allows.
    Underpriced,
    /// Prices sum above 1 — the profitable side is selling every outcome, which
    /// needs shorting. Reported for information; usually not actionable.
    Overpriced,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct CoherenceBreak {
    pub event_id: String,
    pub title: String,
    pub kind: BreakKind,
    /// What the outcomes actually sum to.
    pub sum: f64,
    /// Gross gap from 1, in basis points.
    pub gap_bps: f64,
    /// Gap remaining after the round-trip cost of every leg.
    pub net_bps: f64,
    /// True only when the net gap is positive *and* the direction is tradable.
    pub actionable: bool,
    pub legs: Vec<Leg>,
}

/// Check every outcome set for a sum that is not 1.
///
/// `cost_bps` is the round-trip cost of **one** leg (fee + half-spread). An
/// N-outcome event needs N legs, so the total cost scales with the number of
/// legs — which is exactly why three-way and four-way events almost never pay
/// even when the raw gap looks generous.
pub fn check(sets: &[OutcomeSet], cost_bps: f64) -> Vec<CoherenceBreak> {
    let mut out = Vec::new();
    for set in sets {
        // Fewer than two legs is not a coherence question, and a leg with an
        // out-of-range price is bad data rather than an opportunity.
        if set.legs.len() < 2 || set.legs.iter().any(|l| !(0.0..=1.0).contains(&l.price)) {
            continue;
        }
        let sum: f64 = set.legs.iter().map(|l| l.price).sum();
        let gap_bps = (1.0 - sum).abs() * 10_000.0;
        let total_cost = cost_bps * set.legs.len() as f64;
        let net_bps = gap_bps - total_cost;

        let kind = if sum < 1.0 { BreakKind::Underpriced } else { BreakKind::Overpriced };
        // Only the underpriced side is reachable without shorting.
        let actionable = net_bps > 0.0 && kind == BreakKind::Underpriced;

        // Report anything with a real gap, actionable or not — the near-misses
        // are the data that tells you whether this edge exists at your size.
        if gap_bps > 1.0 {
            out.push(CoherenceBreak {
                event_id: set.event_id.clone(),
                title: set.title.clone(),
                kind,
                sum,
                gap_bps,
                net_bps,
                actionable,
                legs: set.legs.clone(),
            });
        }
    }
    // Biggest net opportunity first.
    out.sort_by(|a, b| b.net_bps.partial_cmp(&a.net_bps).unwrap_or(std::cmp::Ordering::Equal));
    out
}

/// Build the outcome set for a plain binary market from its YES and NO prices.
/// Polymarket quotes both, and they are the most common place a gap shows up.
pub fn binary_set(event_id: &str, title: &str, market_id: &str, yes: f64, no: f64) -> OutcomeSet {
    OutcomeSet {
        event_id: event_id.to_string(),
        title: title.to_string(),
        legs: vec![
            Leg { market_id: market_id.to_string(), outcome: "YES".into(), price: yes },
            Leg { market_id: market_id.to_string(), outcome: "NO".into(), price: no },
        ],
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn set(id: &str, prices: &[f64]) -> OutcomeSet {
        OutcomeSet {
            event_id: id.into(),
            title: format!("event {id}"),
            legs: prices
                .iter()
                .enumerate()
                .map(|(i, p)| Leg { market_id: format!("{id}-{i}"), outcome: format!("O{i}"), price: *p })
                .collect(),
        }
    }

    #[test]
    fn a_coherent_market_produces_nothing() {
        let breaks = check(&[set("e1", &[0.6, 0.4])], 20.0);
        assert!(breaks.is_empty(), "0.6 + 0.4 = 1 is not an opportunity");
    }

    #[test]
    fn buying_every_outcome_below_one_is_the_actionable_case() {
        // 0.55 + 0.40 = 0.95 → 500 bps gross, 2 legs × 20 bps = 40 bps cost.
        let breaks = check(&[set("e1", &[0.55, 0.40])], 20.0);
        assert_eq!(breaks.len(), 1);
        let b = &breaks[0];
        assert_eq!(b.kind, BreakKind::Underpriced);
        assert!((b.gap_bps - 500.0).abs() < 1e-6);
        assert!((b.net_bps - 460.0).abs() < 1e-6);
        assert!(b.actionable, "buying all legs needs no shorting");
    }

    #[test]
    fn the_overpriced_side_is_reported_but_not_actionable() {
        // Selling every leg would be the trade, and spot cannot short.
        let breaks = check(&[set("e1", &[0.65, 0.45])], 20.0);
        assert_eq!(breaks[0].kind, BreakKind::Overpriced);
        assert!(breaks[0].net_bps > 0.0, "the gap is real");
        assert!(!breaks[0].actionable, "but it is not reachable");
    }

    #[test]
    fn a_gap_smaller_than_costs_is_shown_as_a_near_miss_not_hidden() {
        // 30 bps gross against 2 × 20 bps of cost.
        let breaks = check(&[set("e1", &[0.60, 0.397])], 20.0);
        assert_eq!(breaks.len(), 1, "near-misses must stay visible");
        assert!(breaks[0].net_bps < 0.0);
        assert!(!breaks[0].actionable);
    }

    #[test]
    fn cost_scales_with_the_number_of_legs() {
        // The same 200 bps gross gap, two legs vs. eight, at 25 bps per leg.
        let two = check(&[set("e1", &[0.58, 0.40])], 25.0); // cost 50 → net +150
        let eight_prices: Vec<f64> = std::iter::repeat(0.1225).take(8).collect(); // sums to 0.98
        let eight = check(&[set("e2", &eight_prices)], 25.0); // cost 200 → net 0

        assert!((two[0].gap_bps - eight[0].gap_bps).abs() < 1.0, "same gross gap");
        assert!(two[0].net_bps > eight[0].net_bps + 100.0, "more legs, more cost");
        assert!(two[0].actionable);
        assert!(!eight[0].actionable, "8 legs × 25bps eats a 200bps gap entirely");
    }

    #[test]
    fn results_are_ordered_by_the_net_opportunity() {
        let breaks = check(
            &[set("small", &[0.58, 0.41]), set("big", &[0.50, 0.40])],
            10.0,
        );
        assert_eq!(breaks[0].event_id, "big", "best net first");
    }

    #[test]
    fn malformed_sets_are_skipped_rather_than_reported_as_free_money() {
        // A single leg is not a coherence question.
        assert!(check(&[set("one", &[0.5])], 10.0).is_empty());
        // A price outside 0..1 is bad data, and 1.5 + 0.4 would look like a
        // spectacular short opportunity if we trusted it.
        assert!(check(&[set("bad", &[1.5, 0.4])], 10.0).is_empty());
        assert!(check(&[set("neg", &[-0.1, 0.9])], 10.0).is_empty());
        assert!(check(&[], 10.0).is_empty());
    }

    #[test]
    fn a_binary_market_with_a_yes_no_gap_is_caught() {
        let s = binary_set("evt", "Will X happen?", "polymarket:x", 0.62, 0.35);
        let breaks = check(&[s], 15.0);
        assert_eq!(breaks.len(), 1);
        assert_eq!(breaks[0].kind, BreakKind::Underpriced);
        assert!((breaks[0].sum - 0.97).abs() < 1e-9);
        assert!(breaks[0].actionable);
    }
}
