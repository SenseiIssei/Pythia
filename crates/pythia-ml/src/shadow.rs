//! Shadow mode: every forecast is written down before the hour happens and
//! scored when it has. Nothing here trades. The scores decide whether the
//! model is ever allowed to.

use std::collections::{HashMap, VecDeque};

use serde::{Deserialize, Serialize};

/// Scored hours kept, across all coins (30 days of 20 coins).
const KEEP: usize = 30 * 24 * 20;

/// Patton's QLIKE. 0 is perfect, lower is better.
pub fn qlike(realised: f64, forecast: f64) -> f64 {
    let r = realised / forecast;
    r - r.ln() - 1.0
}

#[derive(Debug, Clone, Copy)]
struct Pending {
    hour_ms: i64,
    model: f64,
    har: f64,
    naive: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Scored {
    pub symbol: String,
    pub hour_ms: i64,
    pub realised: f64,
    pub model: f64,
    pub har: f64,
    pub qlike_model: f64,
    pub qlike_har: f64,
    pub qlike_naive: f64,
}

#[derive(Debug, Clone, Default, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ShadowSummary {
    pub scored: usize,
    pub since_ms: Option<i64>,
    pub qlike_model: Option<f64>,
    pub qlike_har: Option<f64>,
    pub qlike_naive: Option<f64>,
    /// Percent lower QLIKE than HAR; positive means the model is better.
    pub gain_vs_har_pct: Option<f64>,
    /// Share of scored hours where the model beat HAR.
    pub win_rate: Option<f64>,
}

#[derive(Debug, Default)]
pub struct ShadowBook {
    pending: HashMap<String, Pending>,
    scored: VecDeque<Scored>,
}

impl ShadowBook {
    /// Records the forecast for `hour_ms` (the start of the hour being forecast).
    pub fn forecast(&mut self, symbol: &str, hour_ms: i64, model: f64, har: f64, naive: f64) {
        if model.is_finite() && har.is_finite() && model > 0.0 && har > 0.0 {
            self.pending.insert(symbol.to_string(), Pending { hour_ms, model, har, naive });
        }
    }

    /// The hour `hour_ms` closed with realised variance `realised`. Scores the
    /// forecast made for it, if there was one.
    pub fn realise(&mut self, symbol: &str, hour_ms: i64, realised: f64) -> Option<&Scored> {
        let p = *self.pending.get(symbol)?;
        if p.hour_ms != hour_ms || !(realised > 0.0) {
            if p.hour_ms <= hour_ms {
                self.pending.remove(symbol);
            }
            return None;
        }
        self.pending.remove(symbol);
        let naive = if p.naive > 0.0 { qlike(realised, p.naive) } else { f64::NAN };
        self.scored.push_back(Scored {
            symbol: symbol.to_string(),
            hour_ms,
            realised,
            model: p.model,
            har: p.har,
            qlike_model: qlike(realised, p.model),
            qlike_har: qlike(realised, p.har),
            qlike_naive: naive,
        });
        while self.scored.len() > KEEP {
            self.scored.pop_front();
        }
        self.scored.back()
    }

    pub fn summary(&self) -> ShadowSummary {
        let n = self.scored.len();
        if n == 0 {
            return ShadowSummary::default();
        }
        let mean = |f: fn(&Scored) -> f64| {
            let v: Vec<f64> = self.scored.iter().map(f).filter(|x| x.is_finite()).collect();
            (!v.is_empty()).then(|| v.iter().sum::<f64>() / v.len() as f64)
        };
        let qm = mean(|s| s.qlike_model);
        let qh = mean(|s| s.qlike_har);
        let wins = self.scored.iter().filter(|s| s.qlike_model < s.qlike_har).count();
        ShadowSummary {
            scored: n,
            since_ms: self.scored.front().map(|s| s.hour_ms),
            qlike_model: qm,
            qlike_har: qh,
            qlike_naive: mean(|s| s.qlike_naive),
            gain_vs_har_pct: match (qm, qh) {
                (Some(m), Some(h)) if h > 0.0 => Some((1.0 - m / h) * 100.0),
                _ => None,
            },
            win_rate: Some(wins as f64 / n as f64),
        }
    }

    /// The scored history, for persisting across restarts. Pending forecasts are
    /// not kept: an hour forecast before a restart is simply not scored.
    pub fn history(&self) -> Vec<Scored> {
        self.scored.iter().cloned().collect()
    }

    pub fn restore(history: Vec<Scored>) -> Self {
        let mut scored: VecDeque<Scored> = history.into();
        while scored.len() > KEEP {
            scored.pop_front();
        }
        Self { pending: HashMap::new(), scored }
    }

    pub fn recent(&self, n: usize) -> Vec<Scored> {
        self.scored.iter().rev().take(n).cloned().collect()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn perfect_forecast_scores_zero() {
        assert!(qlike(2.0, 2.0).abs() < 1e-15);
        assert!(qlike(2.0, 1.0) > 0.0 && qlike(1.0, 2.0) > 0.0);
    }

    #[test]
    fn scores_only_the_hour_that_was_forecast() {
        let mut b = ShadowBook::default();
        b.forecast("BTC", 3600, 1e-5, 2e-5, 1e-5);
        assert!(b.realise("BTC", 0, 1e-5).is_none()); // an earlier hour: forecast stays pending
        let s = b.realise("BTC", 3600, 1e-5).unwrap();
        assert!(s.qlike_model < s.qlike_har);
        assert!(b.realise("BTC", 3600, 1e-5).is_none()); // scored once
        let sum = b.summary();
        assert_eq!(sum.scored, 1);
        assert!(sum.gain_vs_har_pct.unwrap() > 0.0);
    }

    #[test]
    fn a_skipped_hour_drops_the_stale_forecast() {
        let mut b = ShadowBook::default();
        b.forecast("ETH", 3600, 1e-5, 1e-5, 1e-5);
        assert!(b.realise("ETH", 7200, 1e-5).is_none());
        assert!(b.realise("ETH", 3600, 1e-5).is_none());
        assert_eq!(b.summary().scored, 0);
    }
}
