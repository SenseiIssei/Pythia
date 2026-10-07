//! M2 in shadow mode: each weekly ranking is written down when it is made and
//! scored seven days later against how the coins actually did. Nothing here
//! trades. The live Rank-IC is what decides whether M2 may ever move money.

use std::collections::HashMap;

use serde::{Deserialize, Serialize};

use crate::drift::DriftLevel;
use crate::picks::{spearman, DAY_MS, HORIZON_DAYS};

/// Rankings kept: two years of weeks.
const KEEP: usize = 104;
/// Weeks in the "recent" Rank-IC.
pub const RECENT_WEEKS: usize = 8;

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Pick {
    pub symbol: String,
    pub score: f64,
    /// Daily close on the ranking day, the start of the realised return.
    pub close: f64,
    /// The coin had a perpetual that day (its perp inputs were not missing).
    #[serde(default)]
    pub perp: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct RawDrift {
    pub feature: String,
    pub psi: f64,
    pub outside_pct: f64,
    pub level: DriftLevel,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Realised {
    /// Spearman correlation of score and realised 7-day log return.
    pub rank_ic: f64,
    pub coins: usize,
    /// Ranked coins whose return could not be fetched (left out of the IC).
    pub missing: usize,
    /// Mean 7-day return of the top and bottom tenth of the ranking, in percent.
    pub top_pct: f64,
    pub bottom_pct: f64,
    pub realised_ms: i64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Ranking {
    /// The UTC day whose closes the ranking uses; realised at the close of `day_ms + 7d`.
    pub day_ms: i64,
    pub made_ms: i64,
    pub version: String,
    /// Best first.
    pub picks: Vec<Pick>,
    #[serde(default)]
    pub drift: Vec<RawDrift>,
    /// What this run could not see the way the lab does (approximated ages, ties).
    #[serde(default)]
    pub notes: Vec<String>,
    #[serde(default)]
    pub realised: Option<Realised>,
}

impl Ranking {
    /// The day whose close ends the realised return.
    pub fn realise_day_ms(&self) -> i64 {
        self.day_ms + HORIZON_DAYS * DAY_MS
    }
}

#[derive(Debug, Clone, Default, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct WeekScore {
    pub day_ms: i64,
    pub rank_ic: f64,
    pub coins: usize,
    pub top_pct: f64,
    pub bottom_pct: f64,
}

#[derive(Debug, Clone, Default, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct PicksShadowSummary {
    pub rankings: usize,
    /// Rankings whose week is over and scored.
    pub weeks: usize,
    pub since_ms: Option<i64>,
    /// Mean weekly Rank-IC so far.
    pub rank_ic: Option<f64>,
    /// Mean of the last `RECENT_WEEKS` weeks.
    pub rank_ic_recent: Option<f64>,
    /// t-statistic of the mean (needs three weeks).
    pub rank_ic_t: Option<f64>,
    /// Share of weeks with a positive Rank-IC.
    pub hit_rate: Option<f64>,
    /// Newest first.
    pub history: Vec<WeekScore>,
}

#[derive(Debug, Default)]
pub struct PicksBook {
    rankings: Vec<Ranking>,
}

impl PicksBook {
    pub fn restore(mut rankings: Vec<Ranking>) -> Self {
        rankings.sort_by_key(|r| r.day_ms);
        rankings.dedup_by_key(|r| r.day_ms);
        let mut b = Self { rankings };
        b.trim();
        b
    }

    fn trim(&mut self) {
        if self.rankings.len() > KEEP {
            let cut = self.rankings.len() - KEEP;
            self.rankings.drain(..cut);
        }
    }

    pub fn rankings(&self) -> &[Ranking] {
        &self.rankings
    }

    pub fn latest(&self) -> Option<&Ranking> {
        self.rankings.last()
    }

    /// Records a ranking; a second one for the same day replaces the first
    /// unless that one is already scored.
    pub fn record(&mut self, r: Ranking) {
        match self.rankings.iter().position(|x| x.day_ms == r.day_ms) {
            Some(i) if self.rankings[i].realised.is_none() => self.rankings[i] = r,
            Some(_) => {}
            None => {
                self.rankings.push(r);
                self.rankings.sort_by_key(|x| x.day_ms);
            }
        }
        self.trim();
    }

    /// Is a new weekly ranking due for `day_ms` (the latest complete day)?
    pub fn ranking_due(&self, day_ms: i64) -> bool {
        self.latest().map_or(true, |r| day_ms - r.day_ms >= HORIZON_DAYS * DAY_MS)
    }

    /// Days of rankings whose week has closed by the end of `day_ms` and that are not scored yet.
    pub fn due_for_scoring(&self, day_ms: i64) -> Vec<i64> {
        self.rankings
            .iter()
            .filter(|r| r.realised.is_none() && r.realise_day_ms() <= day_ms)
            .map(|r| r.day_ms)
            .collect()
    }

    /// Scores the ranking made on `day_ms`. `closes` holds, per symbol, the
    /// close of `day_ms + 7d` (or the last close of a coin delisted before it).
    pub fn score(&mut self, day_ms: i64, closes: &HashMap<String, f64>, now_ms: i64) -> Option<&Realised> {
        let r = self.rankings.iter_mut().find(|r| r.day_ms == day_ms && r.realised.is_none())?;
        let mut scores = Vec::new();
        let mut fwd = Vec::new();
        let mut missing = 0;
        for p in &r.picks {
            match closes.get(&p.symbol) {
                Some(c) if *c > 0.0 && p.close > 0.0 => {
                    scores.push(p.score);
                    fwd.push(c.ln() - p.close.ln());
                }
                _ => missing += 1,
            }
        }
        let ic = spearman(&scores, &fwd)?;
        // Top and bottom tenth by score (picks are best first; keep that order among the scored).
        let tenth = (fwd.len() / 10).max(1);
        let mut order: Vec<usize> = (0..fwd.len()).collect();
        order.sort_by(|&a, &b| scores[b].total_cmp(&scores[a]));
        let avg = |ix: &[usize]| ix.iter().map(|&i| fwd[i].exp_m1()).sum::<f64>() / ix.len() as f64 * 100.0;
        r.realised = Some(Realised {
            rank_ic: ic,
            coins: fwd.len(),
            missing,
            top_pct: avg(&order[..tenth]),
            bottom_pct: avg(&order[order.len() - tenth..]),
            realised_ms: now_ms,
        });
        r.realised.as_ref()
    }

    pub fn summary(&self) -> PicksShadowSummary {
        let scored: Vec<(&Ranking, &Realised)> =
            self.rankings.iter().filter_map(|r| r.realised.as_ref().map(|x| (r, x))).collect();
        let ics: Vec<f64> = scored.iter().map(|(_, x)| x.rank_ic).collect();
        let n = ics.len();
        let mean = |v: &[f64]| (!v.is_empty()).then(|| v.iter().sum::<f64>() / v.len() as f64);
        let m = mean(&ics);
        let t = match m {
            Some(m) if n >= 3 => {
                let sd = (ics.iter().map(|x| (x - m).powi(2)).sum::<f64>() / (n - 1) as f64).sqrt();
                (sd > 0.0).then(|| m / (sd / (n as f64).sqrt()))
            }
            _ => None,
        };
        PicksShadowSummary {
            rankings: self.rankings.len(),
            weeks: n,
            since_ms: scored.first().map(|(r, _)| r.day_ms),
            rank_ic: m,
            rank_ic_recent: mean(&ics[n.saturating_sub(RECENT_WEEKS)..]),
            rank_ic_t: t,
            hit_rate: (n > 0).then(|| ics.iter().filter(|x| **x > 0.0).count() as f64 / n as f64),
            history: scored
                .iter()
                .rev()
                .take(26)
                .map(|(r, x)| WeekScore {
                    day_ms: r.day_ms,
                    rank_ic: x.rank_ic,
                    coins: x.coins,
                    top_pct: x.top_pct,
                    bottom_pct: x.bottom_pct,
                })
                .collect(),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn ranking(day: i64, n: usize) -> Ranking {
        Ranking {
            day_ms: day * DAY_MS,
            made_ms: 0,
            version: "t".into(),
            picks: (0..n)
                .map(|i| Pick { symbol: format!("C{i}USDT"), score: (n - i) as f64, close: 100.0, perp: true })
                .collect(),
            drift: vec![],
            notes: vec![],
            realised: None,
        }
    }

    #[test]
    fn weekly_cadence() {
        let mut b = PicksBook::default();
        assert!(b.ranking_due(100 * DAY_MS));
        b.record(ranking(100, 30));
        assert!(!b.ranking_due(106 * DAY_MS));
        assert!(b.ranking_due(107 * DAY_MS));
        assert!(b.due_for_scoring(106 * DAY_MS).is_empty());
        assert_eq!(b.due_for_scoring(107 * DAY_MS), vec![100 * DAY_MS]);
    }

    #[test]
    fn a_ranking_that_was_right_scores_one() {
        let mut b = PicksBook::default();
        b.record(ranking(100, 30));
        // C0 had the best score and does best, and so on down.
        let closes: HashMap<String, f64> = (0..30).map(|i| (format!("C{i}USDT"), 130.0 - i as f64)).collect();
        let r = b.score(100 * DAY_MS, &closes, 1).unwrap();
        assert!((r.rank_ic - 1.0).abs() < 1e-12);
        assert!(r.top_pct > r.bottom_pct);
        assert_eq!(r.missing, 0);
        assert!(b.score(100 * DAY_MS, &closes, 2).is_none(), "scored once");
        let s = b.summary();
        assert_eq!(s.weeks, 1);
        assert!((s.rank_ic.unwrap() - 1.0).abs() < 1e-12);
    }

    #[test]
    fn missing_coins_are_counted_not_guessed() {
        let mut b = PicksBook::default();
        b.record(ranking(100, 30));
        let closes: HashMap<String, f64> = (0..25).map(|i| (format!("C{i}USDT"), 100.0 + i as f64)).collect();
        let r = b.score(100 * DAY_MS, &closes, 1).unwrap();
        assert_eq!(r.coins, 25);
        assert_eq!(r.missing, 5);
        assert!(r.rank_ic < 0.0);
    }

    #[test]
    fn a_scored_ranking_is_not_replaced() {
        let mut b = PicksBook::default();
        b.record(ranking(100, 30));
        let closes: HashMap<String, f64> = (0..30).map(|i| (format!("C{i}USDT"), 100.0 + i as f64)).collect();
        b.score(100 * DAY_MS, &closes, 1);
        b.record(ranking(100, 10));
        assert_eq!(b.latest().unwrap().picks.len(), 30);
    }
}
