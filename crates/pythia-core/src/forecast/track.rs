//! The forecast ledger — every prediction, kept and scored.
//!
//! A forecast that is never checked is entertainment. This store writes down
//! what each source said, what the market said at the same moment, and what
//! actually happened, so [`super::calibration`] can turn that into a number and
//! the pooling layer can turn that number into weight.
//!
//! ## Getting scoring data before any event resolves
//!
//! Prediction-market questions settle in weeks or months, which would mean no
//! calibration data for a very long time. So two kinds of forecast are recorded:
//!
//! - [`ForecastKind::Outcome`] — P(YES) on the event. Resolves when it settles.
//! - [`ForecastKind::Direction`] — P(price higher after a fixed horizon). These
//!   resolve on a schedule, every few minutes, on every market.
//!
//! `Direction` is a genuinely different and easier question, so its score is
//! kept separately and never used to justify trusting a source on `Outcome`.
//! What it *does* give is a fast, honest read on whether a source is calibrated
//! at all — a model that cannot beat the market on "will this be higher in an
//! hour" has earned no benefit of the doubt on "who wins the election".

use super::calibration::{
    fit_recalibration, reliability, trust, HierarchicalSkill, Score, Track,
};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum ForecastKind {
    /// P(the event resolves YES).
    Outcome,
    /// P(this market's price is higher after the forecast horizon).
    Direction,
}

impl ForecastKind {
    pub fn as_str(self) -> &'static str {
        match self {
            ForecastKind::Outcome => "outcome",
            ForecastKind::Direction => "direction",
        }
    }
}

/// One recorded prediction, awaiting reality.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ForecastRecord {
    pub id: String,
    pub ts: i64,
    pub market_id: String,
    /// Who said it: `market`, `stat:longshot`, `llm:anthropic`, `ensemble`, …
    pub source: String,
    pub kind: ForecastKind,
    /// Market class: `prediction`, `crypto`, `equity`. The third level of the
    /// calibration hierarchy — a source can be excellent at one and useless at
    /// another, and one averaged number describes neither.
    ///
    /// Defaulted so a ledger written before this existed still loads; those
    /// records simply all sit in one bucket.
    #[serde(default = "unknown_category")]
    pub category: String,
    /// The forecast itself.
    pub p: f64,
    /// What the market implied at the same instant — the baseline to beat.
    pub market_p: f64,
    /// Price when the forecast was made, for resolving a `Direction` question.
    pub ref_price: f64,
    /// When a `Direction` forecast becomes checkable. Ignored for `Outcome`.
    pub resolve_at: i64,
    /// `None` until reality arrives.
    pub outcome: Option<bool>,
    pub resolved_at: Option<i64>,
}

impl ForecastRecord {
    pub fn is_resolved(&self) -> bool {
        self.outcome.is_some()
    }
}

fn unknown_category() -> String {
    "unknown".to_string()
}

/// A prediction market this close to 0 or 1 is treated as settled. Not a real
/// settlement feed — a proxy, so `Outcome` scores start accruing rather than
/// waiting on an oracle Pythia does not have.
const SETTLED_EPS: f64 = 0.005;

/// How many records to keep. Well past what any calibration needs, and bounded
/// so a long-running daemon cannot grow without limit.
const MAX_RECORDS: usize = 20_000;

/// What one source has earned, precomputed.
///
/// Deriving this is the expensive part of the whole forecasting layer — a
/// logistic fit over the source's entire history — and it only changes when a
/// forecast *resolves*. Recording a new one cannot move any score, so callers
/// hold a [`SourceStats`] and rebuild it only when
/// [`ForecastStore::resolution_version`] changes.
#[derive(Debug, Clone, Copy, Default)]
pub struct SourceStat {
    /// How far this source may pull the forecast from the market price, 0..1.
    pub trust: f64,
    pub recalibration: super::calibration::Recalibration,
    /// Resolved forecasts behind those numbers, at the finest level.
    pub n: usize,
    /// The three-level estimate behind `trust`.
    pub skill: HierarchicalSkill,
}

/// Key: source × question type × market class. The three axes a source's skill
/// genuinely varies along.
type StatKey = (String, ForecastKind, String);

/// Common questions a pair of sources needs before their error correlation is
/// worth believing. Below this the estimate is noise, and treating noise as
/// correlation would silence a source for no reason.
const MIN_PAIR_SAMPLES: usize = 20;

/// Pairwise error correlation between sources.
///
/// [`aggregate::effective_n`](super::aggregate::effective_n) already reports
/// that five agreeing models are not five pieces of evidence. This is what acts
/// on it.
#[derive(Debug, Clone, Default)]
pub struct ErrorCorrelations {
    map: HashMap<(String, String), f64>,
}

impl ErrorCorrelations {
    /// Correlation between two sources' errors, or `None` when they have not
    /// answered enough of the same questions to say.
    pub fn get(&self, a: &str, b: &str) -> Option<f64> {
        if a == b {
            return Some(1.0);
        }
        let key = if a < b {
            (a.to_string(), b.to_string())
        } else {
            (b.to_string(), a.to_string())
        };
        self.map.get(&key).copied()
    }

    /// Redundancy-adjusted weights.
    ///
    /// A source's weight is divided by how much of it is already represented by
    /// the others:
    ///
    /// ```text
    /// wᵢ' = wᵢ / (1 + Σⱼ≠ᵢ max(ρᵢⱼ, 0) · wⱼ)
    /// ```
    ///
    /// Two sources correlated at 0.9 together count for barely more than one.
    /// A source *uncorrelated* with the rest keeps its full weight — it is
    /// adding a dimension, which is the entire reason to run an ensemble.
    ///
    /// Negative correlations are floored at zero: a source that is reliably
    /// wrong when another is right is genuine independent information, but
    /// rewarding it with extra weight would be fitting noise.
    ///
    /// Unknown pairs are treated as **correlated** (`assume`), not independent.
    /// Two language models with no shared history are far more likely to be
    /// redundant than not, and the failure mode of guessing "independent" is
    /// overconfidence — the exact thing this whole layer exists to prevent.
    pub fn adjust(&self, sources: &[(String, f64)], assume: f64) -> Vec<f64> {
        sources
            .iter()
            .map(|(name, w)| {
                let overlap: f64 = sources
                    .iter()
                    .filter(|(other, _)| other != name)
                    .map(|(other, ow)| self.get(name, other).unwrap_or(assume).max(0.0) * ow)
                    .sum();
                w / (1.0 + overlap)
            })
            .collect()
    }

    pub fn len(&self) -> usize {
        self.map.len()
    }
    pub fn is_empty(&self) -> bool {
        self.map.is_empty()
    }
}

/// Pearson correlation. `None` when either series has no variance — a source
/// whose error never changes carries no correlation information.
fn pearson(pairs: &[(f64, f64)]) -> Option<f64> {
    let n = pairs.len() as f64;
    if n < 2.0 {
        return None;
    }
    let mx = pairs.iter().map(|(x, _)| x).sum::<f64>() / n;
    let my = pairs.iter().map(|(_, y)| y).sum::<f64>() / n;
    let mut cov = 0.0;
    let mut vx = 0.0;
    let mut vy = 0.0;
    for (x, y) in pairs {
        let (dx, dy) = (x - mx, y - my);
        cov += dx * dy;
        vx += dx * dx;
        vy += dy * dy;
    }
    if vx <= 0.0 || vy <= 0.0 {
        return None;
    }
    Some((cov / (vx.sqrt() * vy.sqrt())).clamp(-1.0, 1.0))
}

/// Precomputed [`SourceStat`] for every (source, question type, market class).
#[derive(Debug, Clone, Default)]
pub struct SourceStats {
    map: HashMap<StatKey, SourceStat>,
    /// Global skill per question type — what an unseen source inherits.
    global: HashMap<ForecastKind, f64>,
}

impl SourceStats {
    /// An unseen source has no trust and no recalibration, but it does inherit
    /// the pool's global skill estimate — which is what makes a new provider a
    /// ramp rather than a wall, *if* the pool has proven anything.
    pub fn get(&self, source: &str, kind: ForecastKind, category: &str) -> SourceStat {
        if let Some(s) = self.map.get(&(source.to_string(), kind, category.to_string())) {
            return *s;
        }
        SourceStat {
            skill: HierarchicalSkill {
                global: self.global.get(&kind).copied().unwrap_or(0.0),
                ..Default::default()
            },
            ..Default::default()
        }
    }

    /// Skill of every source pooled, for this question type.
    pub fn global_skill(&self, kind: ForecastKind) -> f64 {
        self.global.get(&kind).copied().unwrap_or(0.0)
    }

    pub fn len(&self) -> usize {
        self.map.len()
    }
    pub fn is_empty(&self) -> bool {
        self.map.is_empty()
    }
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct ForecastStore {
    records: Vec<ForecastRecord>,
    #[serde(default)]
    seq: u64,
    /// Bumped once per resolved forecast. The only thing that can change a
    /// score, and therefore the only thing that invalidates a cached
    /// [`SourceStats`].
    #[serde(default)]
    resolutions: u64,
}

impl ForecastStore {
    pub fn len(&self) -> usize {
        self.records.len()
    }
    pub fn is_empty(&self) -> bool {
        self.records.is_empty()
    }
    pub fn records(&self) -> &[ForecastRecord] {
        &self.records
    }
    /// Mutable access, for tests that need to age the ledger. Not part of the
    /// normal flow — resolutions go through `auto_resolve`/`resolve_market` so
    /// the version counter stays honest.
    #[cfg(test)]
    pub fn records_mut(&mut self) -> &mut [ForecastRecord] {
        &mut self.records
    }
    pub fn resolved_count(&self) -> usize {
        self.records.iter().filter(|r| r.is_resolved()).count()
    }
    pub fn pending_count(&self) -> usize {
        self.records.len() - self.resolved_count()
    }

    /// Write down a prediction.
    #[allow(clippy::too_many_arguments)]
    pub fn record(
        &mut self,
        now: i64,
        market_id: &str,
        source: &str,
        kind: ForecastKind,
        category: &str,
        p: f64,
        market_p: f64,
        ref_price: f64,
        horizon_ms: i64,
    ) {
        self.seq += 1;
        self.records.push(ForecastRecord {
            id: format!("f{}", self.seq),
            ts: now,
            market_id: market_id.to_string(),
            source: source.to_string(),
            kind,
            category: category.to_string(),
            p: p.clamp(0.0, 1.0),
            market_p: market_p.clamp(0.0, 1.0),
            ref_price,
            resolve_at: now + horizon_ms,
            outcome: None,
            resolved_at: None,
        });
        if self.records.len() > MAX_RECORDS {
            // Drop the oldest *resolved* records first: a pending forecast is
            // still owed an answer and throwing it away would bias the score
            // toward whatever happened to resolve quickly.
            if let Some(i) = self.records.iter().position(|r| r.is_resolved()) {
                self.records.remove(i);
            } else {
                self.records.remove(0);
            }
        }
    }

    /// Resolve every `Direction` forecast whose horizon has elapsed, against the
    /// current price. Returns how many were settled.
    pub fn auto_resolve(&mut self, now: i64, prices: &HashMap<String, f64>) -> usize {
        let mut n = 0;
        for r in self.records.iter_mut() {
            if r.is_resolved() || r.kind != ForecastKind::Direction || now < r.resolve_at {
                continue;
            }
            let Some(&price) = prices.get(&r.market_id) else { continue };
            if price <= 0.0 || r.ref_price <= 0.0 {
                continue;
            }
            r.outcome = Some(price > r.ref_price);
            r.resolved_at = Some(now);
            n += 1;
        }
        self.resolutions += n as u64;
        n
    }

    /// Settle every open `Outcome` forecast on one market. Called when an event
    /// resolves — or by [`ForecastStore::resolve_settled`] as a proxy.
    pub fn resolve_market(&mut self, now: i64, market_id: &str, outcome: bool) -> usize {
        let mut n = 0;
        for r in self.records.iter_mut() {
            if r.is_resolved() || r.kind != ForecastKind::Outcome || r.market_id != market_id {
                continue;
            }
            r.outcome = Some(outcome);
            r.resolved_at = Some(now);
            n += 1;
        }
        self.resolutions += n as u64;
        n
    }

    /// Treat any prediction market pinned at ~0 or ~1 as settled, and resolve
    /// the outcome forecasts on it.
    pub fn resolve_settled(&mut self, now: i64, prices: &HashMap<String, f64>) -> usize {
        let settled: Vec<(String, bool)> = prices
            .iter()
            .filter(|(_, &p)| p >= 1.0 - SETTLED_EPS || p <= SETTLED_EPS)
            .map(|(id, &p)| (id.clone(), p >= 0.5))
            .collect();
        settled
            .into_iter()
            .map(|(id, outcome)| self.resolve_market(now, &id, outcome))
            .sum()
    }

    /// Increments once per resolved forecast. Cache key for [`SourceStats`].
    pub fn resolution_version(&self) -> u64 {
        self.resolutions
    }

    /// Score every source in **one pass** and return the result.
    ///
    /// The naive version — ask each source for its trust, then its
    /// recalibration, then its track — walks the whole ledger once per question
    /// and refits a logistic regression each time. Doing that per source per
    /// market per tick is how a forecasting layer eats a CPU core to produce
    /// numbers that did not change.
    pub fn source_stats(&self) -> SourceStats {
        let fine = self.grouped_samples();

        // Roll the finest level up into the two parent levels. One pass over the
        // groups, not a re-scan of the ledger per level.
        let mut by_source: HashMap<(String, ForecastKind), (Vec<(f64, bool)>, Vec<(f64, bool)>)> =
            HashMap::new();
        let mut by_kind: HashMap<ForecastKind, (Vec<(f64, bool)>, Vec<(f64, bool)>)> = HashMap::new();
        for ((source, kind, _), (mine, market)) in &fine {
            let s = by_source.entry((source.clone(), *kind)).or_default();
            s.0.extend_from_slice(mine);
            s.1.extend_from_slice(market);
            let k = by_kind.entry(*kind).or_default();
            k.0.extend_from_slice(mine);
            k.1.extend_from_slice(market);
        }

        let global_scores: HashMap<ForecastKind, (Score, Score)> = by_kind
            .iter()
            .map(|(k, (mine, market))| (*k, (Score::of(mine), Score::of(market))))
            .collect();
        let source_scores: HashMap<(String, ForecastKind), (Score, Score)> = by_source
            .iter()
            .map(|(k, (mine, market))| (k.clone(), (Score::of(mine), Score::of(market))))
            .collect();

        let mut map = HashMap::new();
        for ((source, kind, category), (mine, market)) in fine {
            let finest = (Score::of(&mine), Score::of(&market));
            let empty = (Score::default(), Score::default());
            let src = source_scores.get(&(source.clone(), kind)).unwrap_or(&empty);
            let glob = global_scores.get(&kind).unwrap_or(&empty);

            let skill = HierarchicalSkill::build(
                (&glob.0, &glob.1),
                (&src.0, &src.1),
                (&finest.0, &finest.1),
            );
            map.insert(
                (source, kind, category),
                SourceStat {
                    trust: skill.trust(),
                    recalibration: fit_recalibration(&mine),
                    n: finest.0.n,
                    skill,
                },
            );
        }

        let global = global_scores
            .iter()
            .map(|(k, (mine, market))| (*k, super::calibration::brier_skill(mine, market)))
            .collect();
        SourceStats { map, global }
    }

    /// Full scorecards, one per (source, kind). Same single pass as
    /// [`ForecastStore::source_stats`], plus the reliability diagram.
    pub fn tracks(&self) -> Vec<Track> {
        let stats = self.source_stats();
        let mut out: Vec<Track> = self
            .grouped_samples()
            .into_iter()
            .map(|((source, kind, category), (mine, market))| {
                let score = Score::of(&mine);
                let market_score = Score::of(&market);
                let stat = stats.get(&source, kind, &category);
                Track {
                    kind: kind.as_str().to_string(),
                    brier_skill: super::calibration::brier_skill(&score, &market_score),
                    // The pooled estimate is what actually gates orders, so it
                    // is what the scoreboard shows.
                    trust: stat.trust,
                    skill: stat.skill,
                    recalibration: fit_recalibration(&mine),
                    reliability: reliability(&mine, 10),
                    source,
                    category,
                    score,
                    market_score,
                }
            })
            .collect();
        out.sort_by(|a, b| {
            a.source
                .cmp(&b.source)
                .then(a.kind.cmp(&b.kind))
                .then(a.category.cmp(&b.category))
        });
        out
    }

    /// Group every *resolved* record by (source, kind, category) into the
    /// source's own samples and the market's samples on the very same questions.
    #[allow(clippy::type_complexity)]
    fn grouped_samples(&self) -> HashMap<StatKey, (Vec<(f64, bool)>, Vec<(f64, bool)>)> {
        let mut grouped: HashMap<StatKey, (Vec<(f64, bool)>, Vec<(f64, bool)>)> = HashMap::new();
        for r in &self.records {
            let Some(y) = r.outcome else { continue };
            let e = grouped
                .entry((r.source.clone(), r.kind, r.category.clone()))
                .or_default();
            e.0.push((r.p, y));
            e.1.push((r.market_p, y));
        }
        grouped
    }

    /// Pearson correlation between every pair of sources' **errors**.
    ///
    /// Not their forecasts — their errors. Two sources that both track the
    /// market closely will have highly correlated *forecasts* while being
    /// usefully independent; what an ensemble needs to know is whether they are
    /// wrong at the same times, in the same direction.
    ///
    /// Only questions both answered count, which is what makes this comparable:
    /// each pair is measured on its own common ground.
    pub fn error_correlations(&self) -> ErrorCorrelations {
        // A question is one (market, sweep) — every source recorded in one pass
        // shares the timestamp, so this pairs up the answers that were given to
        // the same question at the same moment.
        let mut by_question: HashMap<(String, i64, ForecastKind), Vec<(String, f64)>> = HashMap::new();
        for r in &self.records {
            let Some(y) = r.outcome else { continue };
            let err = r.p - if y { 1.0 } else { 0.0 };
            by_question
                .entry((r.market_id.clone(), r.ts, r.kind))
                .or_default()
                .push((r.source.clone(), err));
        }

        let mut pairs: HashMap<(String, String), Vec<(f64, f64)>> = HashMap::new();
        for answers in by_question.values() {
            for i in 0..answers.len() {
                for j in (i + 1)..answers.len() {
                    let (a, b) = (&answers[i], &answers[j]);
                    if a.0 == b.0 {
                        continue;
                    }
                    let key = if a.0 < b.0 {
                        (a.0.clone(), b.0.clone())
                    } else {
                        (b.0.clone(), a.0.clone())
                    };
                    let (x, y) = if a.0 < b.0 { (a.1, b.1) } else { (b.1, a.1) };
                    pairs.entry(key).or_default().push((x, y));
                }
            }
        }

        let map = pairs
            .into_iter()
            .filter(|(_, v)| v.len() >= MIN_PAIR_SAMPLES)
            .filter_map(|(k, v)| pearson(&v).map(|r| (k, r)))
            .collect();
        ErrorCorrelations { map }
    }

    /// (forecast, outcome) pairs for one source and question type.
    fn samples(&self, source: &str, kind: ForecastKind) -> Vec<(f64, bool)> {
        self.records
            .iter()
            .filter(|r| r.source == source && r.kind == kind)
            .filter_map(|r| r.outcome.map(|y| (r.p, y)))
            .collect()
    }

    /// The market's forecast on **exactly the same** resolved questions. Scoring
    /// a source against the market on a different question set would be
    /// meaningless, so this walks the same records.
    fn market_samples(&self, source: &str, kind: ForecastKind) -> Vec<(f64, bool)> {
        self.records
            .iter()
            .filter(|r| r.source == source && r.kind == kind)
            .filter_map(|r| r.outcome.map(|y| (r.market_p, y)))
            .collect()
    }

    /// Flat scorecard for one source on one question type, across every market
    /// class. The hierarchy-aware version is [`ForecastStore::tracks`]; this one
    /// is the un-pooled view, kept for tests and for the per-source rollup.
    pub fn track(&self, source: &str, kind: ForecastKind) -> Track {
        let samples = self.samples(source, kind);
        let market = Score::of(&self.market_samples(source, kind));
        let score = Score::of(&samples);
        Track {
            source: source.to_string(),
            kind: kind.as_str().to_string(),
            category: "all".into(),
            skill: HierarchicalSkill::default(),
            brier_skill: super::calibration::brier_skill(&score, &market),
            trust: trust(&score, &market),
            recalibration: fit_recalibration(&samples),
            reliability: reliability(&samples, 10),
            score,
            market_score: market,
        }
    }

    /// Every (source, kind) pair that has produced at least one forecast.
    pub fn source_kinds(&self) -> Vec<(String, ForecastKind)> {
        let mut seen: Vec<(String, ForecastKind)> = Vec::new();
        for r in &self.records {
            let key = (r.source.clone(), r.kind);
            if !seen.contains(&key) {
                seen.push(key);
            }
        }
        seen.sort_by(|a, b| a.0.cmp(&b.0).then(a.1.as_str().cmp(b.1.as_str())));
        seen
    }

    /// How much this source is allowed to move the final forecast away from the
    /// market price, on this question type and market class.
    ///
    /// Convenience over [`ForecastStore::source_stats`] — correct but O(ledger)
    /// per call, so the engine holds a cached `SourceStats` instead.
    pub fn trust_of(&self, source: &str, kind: ForecastKind, category: &str) -> f64 {
        self.source_stats().get(source, kind, category).trust
    }

    /// Learned recalibration for a source, or the identity map when there is not
    /// yet enough evidence to fit one.
    pub fn recalibration_of(
        &self,
        source: &str,
        kind: ForecastKind,
        category: &str,
    ) -> super::calibration::Recalibration {
        self.source_stats().get(source, kind, category).recalibration
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const HOUR: i64 = 3_600_000;

    fn store_with_direction_history(source: &str, p: f64, hits: usize, total: usize) -> ForecastStore {
        let mut s = ForecastStore::default();
        for i in 0..total {
            let up = i < hits;
            s.record(0, "m", source, ForecastKind::Direction, "crypto", p, 0.5, 100.0, HOUR);
            let mut prices = HashMap::new();
            prices.insert("m".to_string(), if up { 101.0 } else { 99.0 });
            s.auto_resolve(HOUR + 1, &prices);
        }
        s
    }

    #[test]
    fn a_direction_forecast_resolves_against_the_price_after_its_horizon() {
        let mut s = ForecastStore::default();
        s.record(0, "crypto:BTC/USD", "stat:drift", ForecastKind::Direction, "crypto", 0.6, 0.5, 100.0, HOUR);
        assert_eq!(s.pending_count(), 1);

        let mut prices = HashMap::new();
        prices.insert("crypto:BTC/USD".to_string(), 105.0);

        // Too early — nothing resolves.
        assert_eq!(s.auto_resolve(HOUR - 1, &prices), 0);
        assert_eq!(s.pending_count(), 1);

        assert_eq!(s.auto_resolve(HOUR + 1, &prices), 1);
        assert_eq!(s.records()[0].outcome, Some(true));
        assert_eq!(s.resolved_count(), 1);

        // Idempotent: resolving again changes nothing.
        assert_eq!(s.auto_resolve(HOUR + 2, &prices), 0);
    }

    #[test]
    fn a_price_that_fell_resolves_the_forecast_false() {
        let mut s = ForecastStore::default();
        s.record(0, "m", "x", ForecastKind::Direction, "crypto", 0.9, 0.5, 100.0, HOUR);
        let prices = HashMap::from([("m".to_string(), 95.0)]);
        s.auto_resolve(HOUR + 1, &prices);
        assert_eq!(s.records()[0].outcome, Some(false));
    }

    #[test]
    fn a_missing_price_leaves_the_forecast_pending_rather_than_guessing() {
        let mut s = ForecastStore::default();
        s.record(0, "gone", "x", ForecastKind::Direction, "crypto", 0.6, 0.5, 100.0, HOUR);
        assert_eq!(s.auto_resolve(HOUR + 1, &HashMap::new()), 0);
        assert_eq!(s.pending_count(), 1, "an unanswerable question stays open");
    }

    #[test]
    fn outcome_forecasts_ignore_the_horizon_and_wait_for_settlement() {
        let mut s = ForecastStore::default();
        s.record(0, "poly:x", "llm:anthropic", ForecastKind::Outcome, "prediction", 0.7, 0.6, 0.6, HOUR);
        let prices = HashMap::from([("poly:x".to_string(), 0.65)]);
        assert_eq!(s.auto_resolve(HOUR * 100, &prices), 0, "an election does not resolve on a timer");

        assert_eq!(s.resolve_market(1, "poly:x", true), 1);
        assert_eq!(s.records()[0].outcome, Some(true));
    }

    #[test]
    fn a_market_pinned_at_one_is_treated_as_settled_yes() {
        let mut s = ForecastStore::default();
        s.record(0, "poly:yes", "llm", ForecastKind::Outcome, "prediction", 0.7, 0.6, 0.6, HOUR);
        s.record(0, "poly:no", "llm", ForecastKind::Outcome, "prediction", 0.7, 0.6, 0.6, HOUR);
        s.record(0, "poly:open", "llm", ForecastKind::Outcome, "prediction", 0.7, 0.6, 0.6, HOUR);
        let prices = HashMap::from([
            ("poly:yes".to_string(), 0.999),
            ("poly:no".to_string(), 0.001),
            ("poly:open".to_string(), 0.55),
        ]);
        assert_eq!(s.resolve_settled(1, &prices), 2);
        assert_eq!(s.records()[0].outcome, Some(true));
        assert_eq!(s.records()[1].outcome, Some(false));
        assert_eq!(s.records()[2].outcome, None, "a live market is not settled");
    }

    #[test]
    fn an_unproven_source_gets_no_trust_at_all() {
        let s = ForecastStore::default();
        assert_eq!(s.trust_of("llm:anthropic", ForecastKind::Direction, "crypto"), 0.0);
        // ...and one lucky call is still nothing.
        let one = store_with_direction_history("llm:x", 0.9, 1, 1);
        assert!(one.trust_of("llm:x", ForecastKind::Direction, "crypto") < 0.05);
    }

    #[test]
    fn a_source_that_beats_the_market_earns_trust_a_coin_flipper_does_not() {
        // Says 0.9 and is right 90% of the time, over 200 questions, while the
        // recorded market price was a flat 0.5 on all of them.
        let good = store_with_direction_history("good", 0.9, 180, 200);
        let t_good = good.trust_of("good", ForecastKind::Direction, "crypto");
        assert!(t_good > 0.4, "a genuinely skilled source should be heard, got {t_good}");

        // Says 0.9 and is right half the time — worse than the market.
        let bad = store_with_direction_history("bad", 0.9, 100, 200);
        assert_eq!(bad.trust_of("bad", ForecastKind::Direction, "crypto"), 0.0);
    }

    #[test]
    fn trust_is_tracked_separately_per_question_type() {
        let mut s = ForecastStore::default();
        // Skilled on Direction...
        for i in 0..200 {
            s.record(0, "m", "llm", ForecastKind::Direction, "crypto", 0.9, 0.5, 100.0, HOUR);
            let prices = HashMap::from([("m".to_string(), if i < 180 { 101.0 } else { 99.0 })]);
            s.auto_resolve(HOUR + 1, &prices);
        }
        assert!(s.trust_of("llm", ForecastKind::Direction, "crypto") > 0.4);
        // ...says nothing about Outcome, where it has no record.
        assert_eq!(
            s.trust_of("llm", ForecastKind::Outcome, "prediction"),
            0.0,
            "being right about an hourly tick is not being right about an election"
        );
    }

    #[test]
    fn the_market_is_scored_on_exactly_the_same_questions() {
        let s = store_with_direction_history("src", 0.9, 180, 200);
        let t = s.track("src", ForecastKind::Direction);
        assert_eq!(t.score.n, t.market_score.n, "same question set, or the comparison is meaningless");
        assert!(t.brier_skill > 0.0);
    }

    #[test]
    fn source_kinds_lists_each_pair_once_and_sorted() {
        let mut s = ForecastStore::default();
        s.record(0, "m", "b", ForecastKind::Direction, "crypto", 0.5, 0.5, 1.0, HOUR);
        s.record(0, "m", "a", ForecastKind::Outcome, "prediction", 0.5, 0.5, 1.0, HOUR);
        s.record(0, "m", "b", ForecastKind::Direction, "crypto", 0.5, 0.5, 1.0, HOUR);
        let sk = s.source_kinds();
        assert_eq!(sk.len(), 2);
        assert_eq!(sk[0].0, "a");
    }

    #[test]
    fn the_batch_scorer_agrees_with_the_per_source_accessors() {
        // `source_stats` is the fast path; if it ever disagrees with the slow
        // one, every weight in the app is quietly wrong.
        let s = store_with_direction_history("src", 0.9, 180, 200);
        let stats = s.source_stats();
        let stat = stats.get("src", ForecastKind::Direction, "crypto");

        assert_eq!(stat.trust, s.trust_of("src", ForecastKind::Direction, "crypto"));
        assert_eq!(stat.n, s.track("src", ForecastKind::Direction).score.n);
        let slow = s.recalibration_of("src", ForecastKind::Direction, "crypto");
        assert!((stat.recalibration.slope - slow.slope).abs() < 1e-12);
        assert!((stat.recalibration.intercept - slow.intercept).abs() < 1e-12);
    }

    #[test]
    fn an_unseen_source_is_unproven_rather_than_missing() {
        let stats = ForecastStore::default().source_stats();
        let stat = stats.get("llm:nobody", ForecastKind::Outcome, "prediction");
        assert_eq!(stat.trust, 0.0);
        assert_eq!(stat.n, 0);
        assert!(stat.recalibration.is_identity(), "no evidence means no correction");
    }

    #[test]
    fn recording_does_not_bump_the_resolution_version_but_resolving_does() {
        // This is the cache key. If recording moved it, the scoreboard would be
        // refitted on every tick and the optimisation would be undone silently.
        let mut s = ForecastStore::default();
        let v0 = s.resolution_version();
        for _ in 0..50 {
            s.record(0, "m", "src", ForecastKind::Direction, "crypto", 0.7, 0.5, 100.0, HOUR);
        }
        assert_eq!(s.resolution_version(), v0, "recording changes no score");

        let prices = HashMap::from([("m".to_string(), 101.0)]);
        let n = s.auto_resolve(HOUR + 1, &prices);
        assert_eq!(n, 50);
        assert_eq!(s.resolution_version(), v0 + 50);

        // Settling an outcome market counts too.
        s.record(0, "poly", "src", ForecastKind::Outcome, "prediction", 0.7, 0.5, 0.5, HOUR);
        let before = s.resolution_version();
        s.resolve_market(1, "poly", true);
        assert_eq!(s.resolution_version(), before + 1);
    }

    #[test]
    fn tracks_are_sorted_and_cover_every_scored_source() {
        let mut s = store_with_direction_history("zeta", 0.8, 30, 40);
        for i in 0..40 {
            s.record(0, "m", "alpha", ForecastKind::Direction, "crypto", 0.6, 0.5, 100.0, HOUR);
            let prices = HashMap::from([("m".to_string(), if i < 25 { 101.0 } else { 99.0 })]);
            s.auto_resolve(HOUR + 1, &prices);
        }
        let tracks = s.tracks();
        assert_eq!(tracks.len(), 2);
        assert_eq!(tracks[0].source, "alpha", "stable ordering for the UI");
        assert!(tracks.iter().all(|t| t.score.n > 0 && t.kind == "direction"));
    }

    // ── hierarchical calibration ────────────────────────────────────────────

    /// Record `total` forecasts of `p` on one category, `hits` of which come true.
    fn add_history(s: &mut ForecastStore, source: &str, category: &str, p: f64, hits: usize, total: usize) {
        for i in 0..total {
            let market = format!("m:{category}");
            s.record(0, &market, source, ForecastKind::Direction, category, p, 0.5, 100.0, HOUR);
            let prices = HashMap::from([(market, if i < hits { 101.0 } else { 99.0 })]);
            s.auto_resolve(HOUR + 1, &prices);
        }
    }

    #[test]
    fn skill_is_tracked_per_market_class_not_averaged_across_them() {
        let mut s = ForecastStore::default();
        // Excellent on crypto, useless on equities. One averaged number would
        // describe neither.
        add_history(&mut s, "llm:x", "crypto", 0.9, 180, 200);
        add_history(&mut s, "llm:x", "equity", 0.9, 100, 200);

        let stats = s.source_stats();
        let crypto = stats.get("llm:x", ForecastKind::Direction, "crypto");
        let equity = stats.get("llm:x", ForecastKind::Direction, "equity");

        assert!(crypto.trust > equity.trust, "{} vs {}", crypto.trust, equity.trust);
        assert!(crypto.skill.raw > 0.3, "raw crypto skill {}", crypto.skill.raw);
        assert!(equity.skill.raw < 0.05, "raw equity skill {}", equity.skill.raw);
    }

    #[test]
    fn a_thin_record_on_a_new_class_leans_on_the_sources_overall_record() {
        let mut s = ForecastStore::default();
        add_history(&mut s, "llm:x", "crypto", 0.9, 270, 300); // deep and good
        add_history(&mut s, "llm:x", "equity", 0.9, 4, 5); // barely anything

        let stats = s.source_stats();
        let equity = stats.get("llm:x", ForecastKind::Direction, "equity");
        // Five questions cannot carry themselves; the 300 elsewhere do.
        assert!(
            equity.skill.pooled > 0.2,
            "a proven source should not be a stranger on a new class: {:?}",
            equity.skill
        );
        assert!(equity.trust > 0.2, "and that should count: {}", equity.trust);
        assert_eq!(equity.skill.n, 5);
        assert_eq!(equity.skill.n_source, 305, "the source level pools both classes");
    }

    #[test]
    fn an_unseen_source_inherits_the_pools_prior_but_not_its_trust() {
        let mut s = ForecastStore::default();
        add_history(&mut s, "llm:proven", "crypto", 0.9, 180, 200);

        let stats = s.source_stats();
        let stranger = stats.get("llm:brand-new", ForecastKind::Direction, "crypto");
        assert!(stranger.skill.global > 0.1, "the pool has proven something: {:?}", stranger.skill);
        assert_eq!(stranger.trust, 0.0, "inheriting a prior is not being proven");
        assert_eq!(stranger.n, 0);
    }

    // ── error correlation ───────────────────────────────────────────────────

    /// Two sources answering the same `n` questions. `f(i)` gives their two
    /// forecasts and the outcome.
    fn add_pair(s: &mut ForecastStore, n: usize, f: impl Fn(usize) -> (f64, f64, bool)) {
        for i in 0..n {
            let market = format!("m{}", i % 4);
            let ts = i as i64 * 10;
            let (pa, pb, up) = f(i);
            s.record(ts, &market, "a", ForecastKind::Direction, "crypto", pa, 0.5, 100.0, HOUR);
            s.record(ts, &market, "b", ForecastKind::Direction, "crypto", pb, 0.5, 100.0, HOUR);
            let prices = HashMap::from([(market, if up { 101.0 } else { 99.0 })]);
            s.auto_resolve(ts + HOUR + 1, &prices);
        }
    }

    #[test]
    fn two_sources_that_are_wrong_together_are_measured_as_correlated() {
        let mut s = ForecastStore::default();
        // Near-identical answers on every question, outcomes varying.
        add_pair(&mut s, 60, |i| {
            let up = i % 3 != 0;
            (if up { 0.9 } else { 0.15 }, if up { 0.85 } else { 0.2 }, up)
        });
        let rho = s.error_correlations().get("a", "b").expect("60 common questions is plenty");
        assert!(rho > 0.9, "near-identical answers → near-identical errors, got {rho}");
    }

    /// The distinction this whole measure exists to make.
    ///
    /// Two sources can *disagree loudly on every question* and still have
    /// perfectly correlated errors — if both are constant forecasters, each
    /// one's error moves only with the outcome, so they move together. What
    /// makes a source independently useful is not disagreeing about the level;
    /// it is being wrong at *different times*.
    #[test]
    fn disagreeing_on_the_level_is_not_the_same_as_being_independently_wrong() {
        let mut s = ForecastStore::default();
        // a always says 0.9, b always says 0.15 — maximal disagreement.
        add_pair(&mut s, 60, |i| (0.9, 0.15, i % 3 != 0));
        let rho = s.error_correlations().get("a", "b").unwrap();
        assert!(
            rho > 0.99,
            "constant forecasters share an error that tracks only the outcome, got {rho}"
        );
    }

    #[test]
    fn sources_that_take_turns_being_wrong_are_measured_as_opposed() {
        let mut s = ForecastStore::default();
        // Outcome fixed; a and b alternate which of them is confident. Their
        // errors move in opposite directions, which is genuine independence.
        add_pair(&mut s, 60, |i| {
            if i % 2 == 0 { (0.98, 0.5, true) } else { (0.5, 0.98, true) }
        });
        let rho = s.error_correlations().get("a", "b").unwrap();
        assert!(rho < -0.9, "taking turns being wrong is anti-correlation, got {rho}");
    }

    #[test]
    fn a_pair_with_too_little_common_ground_reports_nothing_rather_than_noise() {
        let mut s = ForecastStore::default();
        add_pair(&mut s, 5, |i| (0.9, 0.85, i % 2 == 0));
        assert_eq!(s.error_correlations().get("a", "b"), None);
        // ...and a source is trivially correlated with itself.
        assert_eq!(s.error_correlations().get("a", "a"), Some(1.0));
    }

    #[test]
    fn redundant_sources_are_down_weighted_and_independent_ones_are_not() {
        let mut c = ErrorCorrelations::default();
        c.map.insert(("a".into(), "b".into()), 0.95); // near-duplicates
        c.map.insert(("a".into(), "c".into()), 0.0); // independent
        c.map.insert(("b".into(), "c".into()), 0.0);

        let sources = vec![("a".into(), 1.0), ("b".into(), 1.0), ("c".into(), 1.0)];
        let w = c.adjust(&sources, 0.6);

        assert!(w[0] < 0.55 && w[1] < 0.55, "a and b halve each other: {w:?}");
        assert!((w[2] - 1.0).abs() < 1e-9, "c is independent and keeps its weight: {w:?}");
        assert!(w[2] > w[0] * 1.8, "independence is worth roughly double here");
    }

    #[test]
    fn an_unknown_pair_is_assumed_redundant_not_independent() {
        // The safe direction: guessing "independent" would overweight a pool of
        // models that have simply never been compared.
        let c = ErrorCorrelations::default();
        let sources = vec![("a".into(), 1.0), ("b".into(), 1.0)];
        let cautious = c.adjust(&sources, 0.6);
        let reckless = c.adjust(&sources, 0.0);
        assert!(cautious[0] < reckless[0]);
        assert!((reckless[0] - 1.0).abs() < 1e-9, "zero assumed correlation is no adjustment");
    }

    #[test]
    fn a_lone_source_is_never_penalised_for_redundancy() {
        let c = ErrorCorrelations::default();
        let w = c.adjust(&[("only".into(), 0.7)], 0.9);
        assert!((w[0] - 0.7).abs() < 1e-9, "nothing to be redundant with");
    }

    #[test]
    fn the_store_survives_a_serialisation_round_trip() {
        let s = store_with_direction_history("src", 0.8, 30, 40);
        let json = serde_json::to_string(&s).unwrap();
        let back: ForecastStore = serde_json::from_str(&json).unwrap();
        assert_eq!(back.len(), s.len());
        assert_eq!(back.resolved_count(), s.resolved_count());
        assert_eq!(
            back.trust_of("src", ForecastKind::Direction, "crypto"),
            s.trust_of("src", ForecastKind::Direction, "crypto"),
            "a restart must not reset the track record"
        );
    }
}
