//! The allocator: evidence-weighted risk budgets, moved in bounded steps.
//!
//! A portfolio autopilot splits its one amount between asset classes
//! (crypto, US shares) with the two rules here (see `engine::autopilot`,
//! "Portfolios across asset classes").
//!
//! **A risk budget.** Every candidate has a score (its evidence, see
//! [`super::autopilot::Evidence::score`]) and a risk (a typical drawdown, as
//! a fraction). Its budget is `score / risk` over the sum of everyone's, so
//! better evidence gets more money and a riskier class gets less money for
//! the same evidence: the money each one may lose is what is weighted, not
//! the dollars. A candidate whose risk is unknown takes its asset class's
//! prior ([`class_risk_prior`]). A candidate without a positive score gets
//! nothing: no evidence, no money, never a share forced on it.
//!
//! **A bounded step.** A budget that is already in place moves toward a new
//! target by at most `max_shift` (a fraction, 0.10 is ten points) per
//! re-pick, and the steps still add up to one. A day of noisy evidence can
//! therefore never swing a portfolio from one class to the other.

/// A typical drawdown of a book in this asset class, used when its own
/// evidence measures none: crypto falls about twice as far as a diversified
/// book of US shares and ETFs.
pub fn class_risk_prior(us_equity: bool) -> f64 {
    if us_equity {
        0.20
    } else {
        0.45
    }
}

/// A drawdown used as a risk is kept inside this range: a book with a tiny
/// backtest drawdown should not take every dollar, and a broken number above
/// one is no information.
const RISK_MIN: f64 = 0.05;
const RISK_MAX: f64 = 1.0;

/// The risk of one candidate: its measured drawdown when there is one (as a
/// fraction, either sign), else the class prior.
pub fn risk_of(measured: Option<f64>, us_equity: bool) -> f64 {
    match measured.filter(|d| d.is_finite() && d.abs() > 0.0) {
        Some(d) => d.abs().clamp(RISK_MIN, RISK_MAX),
        None => class_risk_prior(us_equity),
    }
}

/// Budgets proportional to `score / risk`, adding up to one. A candidate
/// with no positive score gets nothing. All zero when nobody has a score.
pub fn risk_budgets(items: &[(f64, f64)]) -> Vec<f64> {
    let raw: Vec<f64> = items
        .iter()
        .map(|&(score, risk)| {
            let risk = if risk.is_finite() && risk > 0.0 { risk.clamp(RISK_MIN, RISK_MAX) } else { RISK_MAX };
            if score.is_finite() && score > 0.0 {
                score / risk
            } else {
                0.0
            }
        })
        .collect();
    let total: f64 = raw.iter().sum();
    if total <= 0.0 {
        return vec![0.0; items.len()];
    }
    raw.into_iter().map(|r| r / total).collect()
}

/// Move `current` toward `target` by at most `max_shift` per candidate, the
/// result still adding up to one. Both are budgets of the same candidates in
/// the same order (a new candidate is at 0 in `current`). When the moves up
/// and the moves down do not balance after clamping, the larger side is
/// scaled down to the smaller one, so no candidate ever moves by more than
/// `max_shift`. A `max_shift` of 1 or more is the target itself, and so is
/// a step from nothing in place.
pub fn bounded_step(current: &[f64], target: &[f64], max_shift: f64) -> Vec<f64> {
    assert_eq!(current.len(), target.len(), "the same candidates");
    let norm = |v: &[f64]| -> Vec<f64> {
        let s: f64 = v.iter().map(|x| x.max(0.0)).sum();
        if s > 0.0 {
            v.iter().map(|x| x.max(0.0) / s).collect()
        } else {
            vec![0.0; v.len()]
        }
    };
    let cur = norm(current);
    let tgt = norm(target);
    if cur.iter().all(|x| *x == 0.0) || tgt.iter().all(|x| *x == 0.0) || !max_shift.is_finite() || max_shift >= 1.0 {
        return tgt;
    }
    let shift = max_shift.max(0.0);
    let d: Vec<f64> = cur.iter().zip(&tgt).map(|(c, t)| (t - c).clamp(-shift, shift)).collect();
    let up: f64 = d.iter().filter(|x| **x > 0.0).sum();
    let down: f64 = -d.iter().filter(|x| **x < 0.0).sum::<f64>();
    let (k_up, k_down) = if up > down && up > 0.0 {
        (down / up, 1.0)
    } else if down > up && down > 0.0 {
        (1.0, up / down)
    } else {
        (1.0, 1.0)
    };
    cur.iter()
        .zip(&d)
        .map(|(c, x)| (c + if *x > 0.0 { x * k_up } else { x * k_down }).max(0.0))
        .collect()
}

/// The largest move of any one budget between two splits.
pub fn largest_move(a: &[f64], b: &[f64]) -> f64 {
    a.iter().zip(b).map(|(x, y)| (x - y).abs()).fold(0.0, f64::max)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn close(a: &[f64], b: &[f64]) -> bool {
        a.len() == b.len() && a.iter().zip(b).all(|(x, y)| (x - y).abs() < 1e-9)
    }

    #[test]
    fn a_risk_budget_weights_evidence_per_unit_of_risk() {
        // Same evidence, crypto twice as risky: a third and two thirds.
        let w = risk_budgets(&[(6.0, 0.40), (6.0, 0.20)]);
        assert!(close(&w, &[1.0 / 3.0, 2.0 / 3.0]), "{w:?}");
        // Same risk: by score alone.
        let w = risk_budgets(&[(3.0, 0.45), (1.0, 0.45)]);
        assert!(close(&w, &[0.75, 0.25]), "{w:?}");
        // No positive score, no money.
        let w = risk_budgets(&[(0.0, 0.2), (-1.0, 0.2), (2.0, 0.2)]);
        assert!(close(&w, &[0.0, 0.0, 1.0]), "{w:?}");
        assert!(close(&risk_budgets(&[(0.0, 0.2)]), &[0.0]));
        assert!(close(&risk_budgets(&[(f64::NAN, 0.2), (1.0, f64::NAN)]), &[0.0, 1.0]));
    }

    #[test]
    fn a_measured_drawdown_is_the_risk_and_the_class_prior_fills_in() {
        assert_eq!(risk_of(Some(0.19), false), 0.19);
        assert_eq!(risk_of(Some(-0.30), true), 0.30, "either sign");
        assert_eq!(risk_of(Some(0.001), false), RISK_MIN, "a tiny drawdown does not take every dollar");
        assert_eq!(risk_of(None, false), class_risk_prior(false));
        assert_eq!(risk_of(Some(f64::NAN), true), class_risk_prior(true));
        assert!(class_risk_prior(false) > class_risk_prior(true));
    }

    #[test]
    fn a_step_moves_no_budget_by_more_than_the_bound_and_still_adds_up() {
        let s = bounded_step(&[0.6, 0.4], &[0.2, 0.8], 0.10);
        assert!(close(&s, &[0.5, 0.5]), "{s:?}");
        // Three candidates, uneven pulls: every move within 10 points, sum 1.
        let s = bounded_step(&[0.5, 0.3, 0.2], &[0.0, 0.3, 0.7], 0.10);
        assert!((s.iter().sum::<f64>() - 1.0).abs() < 1e-12, "{s:?}");
        assert!(largest_move(&s, &[0.5, 0.3, 0.2]) <= 0.10 + 1e-12, "{s:?}");
        assert!(close(&s, &[0.4, 0.3, 0.3]), "{s:?}");
        // One pulls up 30, two pull down 5 each: the rise is cut to 10.
        let s = bounded_step(&[0.2, 0.4, 0.4], &[0.5, 0.25, 0.25], 0.10);
        assert!(close(&s, &[0.3, 0.35, 0.35]), "{s:?}");
        // A target inside the bound is reached.
        let s = bounded_step(&[0.5, 0.5], &[0.55, 0.45], 0.10);
        assert!(close(&s, &[0.55, 0.45]), "{s:?}");
        // Nothing in place yet: the target itself.
        assert!(close(&bounded_step(&[0.0, 0.0], &[0.3, 0.7], 0.1), &[0.3, 0.7]));
        // A new candidate starts at zero and grows by the bound.
        let s = bounded_step(&[1.0, 0.0], &[0.5, 0.5], 0.10);
        assert!(close(&s, &[0.9, 0.1]), "{s:?}");
    }
}
