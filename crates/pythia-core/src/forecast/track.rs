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

use super::calibration::{fit_recalibration, reliability, trust, Score, Track};
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
    /// Resolved forecasts behind those numbers.
    pub n: usize,
}

/// Precomputed [`SourceStat`] for every (source, question type) seen.
#[derive(Debug, Clone, Default)]
pub struct SourceStats {
    map: HashMap<(String, ForecastKind), SourceStat>,
}

impl SourceStats {
    /// An unseen source is unproven: no trust, no recalibration, no history.
    pub fn get(&self, source: &str, kind: ForecastKind) -> SourceStat {
        self.map.get(&(source.to_string(), kind)).copied().unwrap_or_default()
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
        let mut map = HashMap::new();
        for (key, (mine, market)) in self.grouped_samples() {
            let score = Score::of(&mine);
            let market_score = Score::of(&market);
            map.insert(
                key,
                SourceStat {
                    trust: trust(&score, &market_score),
                    recalibration: fit_recalibration(&mine),
                    n: score.n,
                },
            );
        }
        SourceStats { map }
    }

    /// Full scorecards, one per (source, kind). Same single pass as
    /// [`ForecastStore::source_stats`], plus the reliability diagram.
    pub fn tracks(&self) -> Vec<Track> {
        let mut out: Vec<Track> = self
            .grouped_samples()
            .into_iter()
            .map(|((source, kind), (mine, market))| {
                let score = Score::of(&mine);
                let market_score = Score::of(&market);
                Track {
                    source,
                    kind: kind.as_str().to_string(),
                    brier_skill: super::calibration::brier_skill(&score, &market_score),
                    trust: trust(&score, &market_score),
                    recalibration: fit_recalibration(&mine),
                    reliability: reliability(&mine, 10),
                    score,
                    market_score,
                }
            })
            .collect();
        out.sort_by(|a, b| a.source.cmp(&b.source).then(a.kind.cmp(&b.kind)));
        out
    }

    /// Group every *resolved* record by (source, kind) into the source's own
    /// samples and the market's samples on the very same questions.
    #[allow(clippy::type_complexity)]
    fn grouped_samples(
        &self,
    ) -> HashMap<(String, ForecastKind), (Vec<(f64, bool)>, Vec<(f64, bool)>)> {
        let mut grouped: HashMap<(String, ForecastKind), (Vec<(f64, bool)>, Vec<(f64, bool)>)> =
            HashMap::new();
        for r in &self.records {
            let Some(y) = r.outcome else { continue };
            let e = grouped.entry((r.source.clone(), r.kind)).or_default();
            e.0.push((r.p, y));
            e.1.push((r.market_p, y));
        }
        grouped
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

    /// Full scorecard for one source on one question type.
    pub fn track(&self, source: &str, kind: ForecastKind) -> Track {
        let samples = self.samples(source, kind);
        let market = Score::of(&self.market_samples(source, kind));
        let score = Score::of(&samples);
        Track {
            source: source.to_string(),
            kind: kind.as_str().to_string(),
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
    /// market price. Zero until it has proven skill *on that question type*.
    pub fn trust_of(&self, source: &str, kind: ForecastKind) -> f64 {
        let score = Score::of(&self.samples(source, kind));
        if score.n == 0 {
            return 0.0;
        }
        trust(&score, &Score::of(&self.market_samples(source, kind)))
    }

    /// Learned recalibration for a source, or the identity map when there is not
    /// yet enough evidence to fit one.
    pub fn recalibration_of(&self, source: &str, kind: ForecastKind) -> super::calibration::Recalibration {
        fit_recalibration(&self.samples(source, kind))
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
            s.record(0, "m", source, ForecastKind::Direction, p, 0.5, 100.0, HOUR);
            let mut prices = HashMap::new();
            prices.insert("m".to_string(), if up { 101.0 } else { 99.0 });
            s.auto_resolve(HOUR + 1, &prices);
        }
        s
    }

    #[test]
    fn a_direction_forecast_resolves_against_the_price_after_its_horizon() {
        let mut s = ForecastStore::default();
        s.record(0, "crypto:BTC/USD", "stat:drift", ForecastKind::Direction, 0.6, 0.5, 100.0, HOUR);
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
        s.record(0, "m", "x", ForecastKind::Direction, 0.9, 0.5, 100.0, HOUR);
        let prices = HashMap::from([("m".to_string(), 95.0)]);
        s.auto_resolve(HOUR + 1, &prices);
        assert_eq!(s.records()[0].outcome, Some(false));
    }

    #[test]
    fn a_missing_price_leaves_the_forecast_pending_rather_than_guessing() {
        let mut s = ForecastStore::default();
        s.record(0, "gone", "x", ForecastKind::Direction, 0.6, 0.5, 100.0, HOUR);
        assert_eq!(s.auto_resolve(HOUR + 1, &HashMap::new()), 0);
        assert_eq!(s.pending_count(), 1, "an unanswerable question stays open");
    }

    #[test]
    fn outcome_forecasts_ignore_the_horizon_and_wait_for_settlement() {
        let mut s = ForecastStore::default();
        s.record(0, "poly:x", "llm:anthropic", ForecastKind::Outcome, 0.7, 0.6, 0.6, HOUR);
        let prices = HashMap::from([("poly:x".to_string(), 0.65)]);
        assert_eq!(s.auto_resolve(HOUR * 100, &prices), 0, "an election does not resolve on a timer");

        assert_eq!(s.resolve_market(1, "poly:x", true), 1);
        assert_eq!(s.records()[0].outcome, Some(true));
    }

    #[test]
    fn a_market_pinned_at_one_is_treated_as_settled_yes() {
        let mut s = ForecastStore::default();
        s.record(0, "poly:yes", "llm", ForecastKind::Outcome, 0.7, 0.6, 0.6, HOUR);
        s.record(0, "poly:no", "llm", ForecastKind::Outcome, 0.7, 0.6, 0.6, HOUR);
        s.record(0, "poly:open", "llm", ForecastKind::Outcome, 0.7, 0.6, 0.6, HOUR);
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
        assert_eq!(s.trust_of("llm:anthropic", ForecastKind::Direction), 0.0);
        // ...and one lucky call is still nothing.
        let one = store_with_direction_history("llm:x", 0.9, 1, 1);
        assert!(one.trust_of("llm:x", ForecastKind::Direction) < 0.05);
    }

    #[test]
    fn a_source_that_beats_the_market_earns_trust_a_coin_flipper_does_not() {
        // Says 0.9 and is right 90% of the time, over 200 questions, while the
        // recorded market price was a flat 0.5 on all of them.
        let good = store_with_direction_history("good", 0.9, 180, 200);
        let t_good = good.trust_of("good", ForecastKind::Direction);
        assert!(t_good > 0.4, "a genuinely skilled source should be heard, got {t_good}");

        // Says 0.9 and is right half the time — worse than the market.
        let bad = store_with_direction_history("bad", 0.9, 100, 200);
        assert_eq!(bad.trust_of("bad", ForecastKind::Direction), 0.0);
    }

    #[test]
    fn trust_is_tracked_separately_per_question_type() {
        let mut s = ForecastStore::default();
        // Skilled on Direction...
        for i in 0..200 {
            s.record(0, "m", "llm", ForecastKind::Direction, 0.9, 0.5, 100.0, HOUR);
            let prices = HashMap::from([("m".to_string(), if i < 180 { 101.0 } else { 99.0 })]);
            s.auto_resolve(HOUR + 1, &prices);
        }
        assert!(s.trust_of("llm", ForecastKind::Direction) > 0.4);
        // ...says nothing about Outcome, where it has no record.
        assert_eq!(
            s.trust_of("llm", ForecastKind::Outcome),
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
        s.record(0, "m", "b", ForecastKind::Direction, 0.5, 0.5, 1.0, HOUR);
        s.record(0, "m", "a", ForecastKind::Outcome, 0.5, 0.5, 1.0, HOUR);
        s.record(0, "m", "b", ForecastKind::Direction, 0.5, 0.5, 1.0, HOUR);
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
        let stat = stats.get("src", ForecastKind::Direction);

        assert_eq!(stat.trust, s.trust_of("src", ForecastKind::Direction));
        assert_eq!(stat.n, s.track("src", ForecastKind::Direction).score.n);
        let slow = s.recalibration_of("src", ForecastKind::Direction);
        assert!((stat.recalibration.slope - slow.slope).abs() < 1e-12);
        assert!((stat.recalibration.intercept - slow.intercept).abs() < 1e-12);
    }

    #[test]
    fn an_unseen_source_is_unproven_rather_than_missing() {
        let stats = ForecastStore::default().source_stats();
        let stat = stats.get("llm:nobody", ForecastKind::Outcome);
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
            s.record(0, "m", "src", ForecastKind::Direction, 0.7, 0.5, 100.0, HOUR);
        }
        assert_eq!(s.resolution_version(), v0, "recording changes no score");

        let prices = HashMap::from([("m".to_string(), 101.0)]);
        let n = s.auto_resolve(HOUR + 1, &prices);
        assert_eq!(n, 50);
        assert_eq!(s.resolution_version(), v0 + 50);

        // Settling an outcome market counts too.
        s.record(0, "poly", "src", ForecastKind::Outcome, 0.7, 0.5, 0.5, HOUR);
        let before = s.resolution_version();
        s.resolve_market(1, "poly", true);
        assert_eq!(s.resolution_version(), before + 1);
    }

    #[test]
    fn tracks_are_sorted_and_cover_every_scored_source() {
        let mut s = store_with_direction_history("zeta", 0.8, 30, 40);
        for i in 0..40 {
            s.record(0, "m", "alpha", ForecastKind::Direction, 0.6, 0.5, 100.0, HOUR);
            let prices = HashMap::from([("m".to_string(), if i < 25 { 101.0 } else { 99.0 })]);
            s.auto_resolve(HOUR + 1, &prices);
        }
        let tracks = s.tracks();
        assert_eq!(tracks.len(), 2);
        assert_eq!(tracks[0].source, "alpha", "stable ordering for the UI");
        assert!(tracks.iter().all(|t| t.score.n > 0 && t.kind == "direction"));
    }

    #[test]
    fn the_store_survives_a_serialisation_round_trip() {
        let s = store_with_direction_history("src", 0.8, 30, 40);
        let json = serde_json::to_string(&s).unwrap();
        let back: ForecastStore = serde_json::from_str(&json).unwrap();
        assert_eq!(back.len(), s.len());
        assert_eq!(back.resolved_count(), s.resolved_count());
        assert_eq!(
            back.trust_of("src", ForecastKind::Direction),
            s.trust_of("src", ForecastKind::Direction),
            "a restart must not reset the track record"
        );
    }
}
