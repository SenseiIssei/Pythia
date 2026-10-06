//! The next-hour volatility model: hourly bars, its 21 features, and the model itself.
//!
//! Every function here mirrors research/lab code line for line:
//!   `hourly_from_minutes`  ->  lab/data.py `hourly()`
//!   `features`             ->  lab/experiments/vol.py `features()` + the BTC join in `build_panel()`
//! The parity test (tests/parity.rs) holds both sides to 1e-9 on real data.
//! Change one side, change the other, regenerate the fixture.

use std::collections::HashMap;
use std::path::Path;

use serde::{Deserialize, Serialize};

use crate::card::Card;
use crate::gbdt::Gbdt;
use crate::MlError;

pub const HOUR_MS: i64 = 3_600_000;
const DAY_MS: i64 = 24 * HOUR_MS;
const EPS: f64 = 1e-10;

pub const FEATURES: [&str; 21] = [
    "har1", "har6", "har24", "har168", "lrv_l1", "lrv_l2", "absret", "negret", "ret24",
    "park", "vol_z", "trades_z", "taker", "seasonal", "hsin", "hcos", "dow",
    "btc_har1", "btc_har24", "btc_ret", "rel_har1",
];
pub type Features = [f64; 21];

/// One closed 1-minute Binance spot kline.
#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
pub struct MinuteBar {
    pub open_time_ms: i64,
    pub open: f64,
    pub high: f64,
    pub low: f64,
    pub close: f64,
    pub quote_volume: f64,
    pub taker_buy_quote_volume: f64,
    pub trades: f64,
}

/// One hour built from minutes. `ts_ms` is the start of the hour; everything in
/// it is known at `ts_ms + 1h`.
#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
pub struct HourBar {
    pub ts_ms: i64,
    pub open: f64,
    pub high: f64,
    pub low: f64,
    pub close: f64,
    /// Sum of 1-minute log returns.
    pub ret: f64,
    /// Realised variance: sum of squared 1-minute log returns.
    pub rv: f64,
    pub volume_q: f64,
    pub taker_buy_q: f64,
    pub trades: f64,
    pub minutes: u32,
}

/// Minutes (sorted, oldest first) to hours. `prev_close` is the close of the
/// minute before the first one; without it the first return is 0, as in the lab.
/// Hours with fewer than 50 minutes are dropped (the exchange was mostly down).
pub fn hourly_from_minutes(minutes: &[MinuteBar], prev_close: Option<f64>) -> Vec<HourBar> {
    let mut out: Vec<HourBar> = Vec::new();
    let mut prev = prev_close;
    let mut cur: Option<HourBar> = None;
    for m in minutes {
        let r = match prev {
            Some(p) => m.close.ln() - p.ln(),
            None => 0.0,
        };
        prev = Some(m.close);
        let hour = m.open_time_ms.div_euclid(HOUR_MS) * HOUR_MS;
        match cur.as_mut() {
            Some(h) if h.ts_ms == hour => {
                h.high = h.high.max(m.high);
                h.low = h.low.min(m.low);
                h.close = m.close;
                h.ret += r;
                h.rv += r * r;
                h.volume_q += m.quote_volume;
                h.taker_buy_q += m.taker_buy_quote_volume;
                h.trades += m.trades;
                h.minutes += 1;
            }
            _ => {
                if let Some(h) = cur.take() {
                    out.push(h);
                }
                cur = Some(HourBar {
                    ts_ms: hour,
                    open: m.open,
                    high: m.high,
                    low: m.low,
                    close: m.close,
                    ret: r,
                    rv: r * r,
                    volume_q: m.quote_volume,
                    taker_buy_q: m.taker_buy_quote_volume,
                    trades: m.trades,
                    minutes: 1,
                });
            }
        }
    }
    if let Some(h) = cur {
        out.push(h);
    }
    out.retain(|h| h.minutes >= 50);
    out
}

fn rolling_mean(x: &[f64], n: usize) -> Vec<f64> {
    let mut out = vec![f64::NAN; x.len()];
    if n == 0 {
        return out;
    }
    for i in (n - 1)..x.len() {
        let w = &x[i + 1 - n..=i];
        if w.iter().all(|v| v.is_finite()) {
            out[i] = w.iter().sum::<f64>() / n as f64;
        }
    }
    out
}

fn rolling_sum(x: &[f64], n: usize) -> Vec<f64> {
    rolling_mean(x, n).into_iter().map(|m| m * n as f64).collect()
}

fn shift(x: &[f64], k: usize) -> Vec<f64> {
    (0..x.len()).map(|i| if i >= k { x[i - k] } else { f64::NAN }).collect()
}

/// The coin's own columns, one row per hour.
struct Own {
    har1: Vec<f64>,
    har24: Vec<f64>,
    rows: Vec<[f64; 17]>,
}

fn own_features(h: &[HourBar]) -> Own {
    let rv: Vec<f64> = h.iter().map(|b| b.rv).collect();
    let ret: Vec<f64> = h.iter().map(|b| b.ret).collect();
    let lrv: Vec<f64> = rv.iter().map(|v| (v + EPS).ln()).collect();
    let lvol: Vec<f64> = h.iter().map(|b| (b.volume_q + 1.0).ln()).collect();
    let ltr: Vec<f64> = h.iter().map(|b| (b.trades + 1.0).ln()).collect();

    let ln_eps = |v: f64| (v + EPS).ln();
    let har6: Vec<f64> = rolling_mean(&rv, 6).into_iter().map(ln_eps).collect();
    let har24: Vec<f64> = rolling_mean(&rv, 24).into_iter().map(ln_eps).collect();
    let har168: Vec<f64> = rolling_mean(&rv, 168).into_iter().map(ln_eps).collect();
    let l1 = shift(&lrv, 1);
    let l2 = shift(&lrv, 2);
    let ret24 = rolling_sum(&ret, 24);
    let lvol_m = rolling_mean(&lvol, 168);
    let ltr_m = rolling_mean(&ltr, 168);
    let lags: Vec<Vec<f64>> = (1..=7).map(|k| shift(&lrv, 24 * k)).collect();

    let rows = (0..h.len())
        .map(|i| {
            let b = &h[i];
            let present: Vec<f64> = lags.iter().map(|l| l[i]).filter(|v| v.is_finite()).collect();
            let seas_mean = if present.is_empty() { f64::NAN } else { present.iter().sum::<f64>() / present.len() as f64 };
            let hour = b.ts_ms.div_euclid(HOUR_MS).rem_euclid(24) as f64;
            let ang = hour * (2.0 * std::f64::consts::PI / 24.0);
            let lhl = (b.high / b.low).ln();
            [
                lrv[i],
                har6[i],
                har24[i],
                har168[i],
                l1[i],
                l2[i],
                b.ret.abs(),
                b.ret.min(0.0),
                ret24[i],
                (lhl * lhl + EPS).ln(),
                lvol[i] - lvol_m[i],
                ltr[i] - ltr_m[i],
                b.taker_buy_q / (b.volume_q + 1e-9) - 0.5,
                seas_mean - har168[i],
                ang.sin(),
                ang.cos(),
                (b.ts_ms.div_euclid(DAY_MS) + 3).rem_euclid(7) as f64,
            ]
        })
        .collect();
    Own { har1: lrv, har24, rows }
}

/// Features for every hour of `coin`, with BTC context joined by hour. NaN marks
/// a value the lab would have as null. Pass the same slice twice for BTC itself.
pub fn features(coin: &[HourBar], btc: &[HourBar]) -> Vec<Features> {
    let own = own_features(coin);
    let b = own_features(btc);
    let btc_by_ts: HashMap<i64, (f64, f64, f64)> = btc
        .iter()
        .enumerate()
        .map(|(i, bar)| (bar.ts_ms, (b.har1[i], b.har24[i], bar.ret)))
        .collect();
    own.rows
        .iter()
        .zip(coin)
        .map(|(r, bar)| {
            let (bh1, bh24, bret) = btc_by_ts.get(&bar.ts_ms).copied().unwrap_or((f64::NAN, f64::NAN, f64::NAN));
            let mut f = [f64::NAN; 21];
            f[..17].copy_from_slice(r);
            f[17] = bh1;
            f[18] = bh24;
            f[19] = bret;
            f[20] = r[0] - bh1;
            f
        })
        .collect()
}

/// A loaded, verified volatility model.
pub struct VolModel {
    pub card: Card,
    gbdt: Gbdt,
    har_idx: [usize; 3],
}

impl VolModel {
    /// Loads `card.json` and `model.json` from `dir` and refuses the model unless
    /// its feature list is exactly ours and it reproduces every probe row.
    pub fn load(dir: &Path) -> Result<Self, MlError> {
        let read = |name: &str| {
            std::fs::read_to_string(dir.join(name)).map_err(|e| MlError::Io(format!("{}: {e}", dir.join(name).display())))
        };
        let card: Card = serde_json::from_str(&read("card.json")?).map_err(|e| MlError::Format(format!("card.json: {e}")))?;
        let gbdt = Gbdt::from_json(&read("model.json")?)?;
        Self::new(card, gbdt)
    }

    pub fn new(card: Card, gbdt: Gbdt) -> Result<Self, MlError> {
        if card.features.iter().map(String::as_str).ne(FEATURES.iter().copied()) {
            return Err(MlError::Mismatch(format!(
                "model expects features {:?}, the engine computes {:?}",
                card.features, FEATURES
            )));
        }
        if gbdt.n_features != FEATURES.len() {
            return Err(MlError::Mismatch(format!("model has {} inputs, expected {}", gbdt.n_features, FEATURES.len())));
        }
        let pos = |name: &str| FEATURES.iter().position(|f| *f == name);
        let har_idx = match card.har.features.iter().map(|f| pos(f)).collect::<Option<Vec<_>>>() {
            Some(v) if v.len() == 3 => [v[0], v[1], v[2]],
            _ => return Err(MlError::Format("HAR baseline must use three known features".into())),
        };
        let m = Self { card, gbdt, har_idx };
        m.verify_probes()?;
        Ok(m)
    }

    fn verify_probes(&self) -> Result<(), MlError> {
        if self.card.probe.x.is_empty() {
            return Err(MlError::Mismatch("model card has no probe rows to verify against".into()));
        }
        for (row, want) in self.card.probe.x.iter().zip(&self.card.probe.raw) {
            let x: Vec<f64> = row.iter().map(|v| v.unwrap_or(f64::NAN)).collect();
            let got = self.gbdt.predict(&x);
            if (got - want).abs() > 1e-9 {
                return Err(MlError::Mismatch(format!("probe output {got} differs from LightGBM's {want}")));
            }
        }
        Ok(())
    }

    pub fn n_trees(&self) -> usize {
        self.gbdt.n_trees()
    }

    /// Forecast log variance of the next hour (model output, before bias correction).
    pub fn log_var(&self, x: &Features) -> f64 {
        self.gbdt.predict(x)
    }

    /// Forecast variance of the next hour, corrected for the log-normal bias.
    pub fn var(&self, x: &Features) -> f64 {
        (self.log_var(x) + self.card.residual_var / 2.0).exp()
    }

    /// The HAR baseline the model is scored against live. NaN if any input is missing.
    pub fn har_var(&self, x: &Features) -> f64 {
        let h = &self.card.har;
        let lv = h.intercept + self.har_idx.iter().zip(&h.coef).map(|(&i, c)| c * x[i]).sum::<f64>();
        (lv + h.residual_var / 2.0).exp()
    }
}

/// Annualised volatility in percent from a one-hour variance.
pub fn annualised_pct(hour_var: f64) -> f64 {
    (hour_var * 24.0 * 365.0).sqrt() * 100.0
}

#[cfg(test)]
mod tests {
    use super::*;

    fn minute(t: i64, close: f64) -> MinuteBar {
        MinuteBar {
            open_time_ms: t,
            open: close,
            high: close * 1.001,
            low: close * 0.999,
            close,
            quote_volume: 10.0,
            taker_buy_quote_volume: 6.0,
            trades: 3.0,
        }
    }

    #[test]
    fn hours_need_fifty_minutes() {
        let mut m: Vec<MinuteBar> = (0..60).map(|i| minute(i * 60_000, 100.0 + i as f64)).collect();
        m.extend((0..30).map(|i| minute(HOUR_MS + i * 60_000, 160.0)));
        let h = hourly_from_minutes(&m, None);
        assert_eq!(h.len(), 1);
        assert_eq!(h[0].minutes, 60);
        assert!((h[0].ret - (159.0f64.ln() - 100.0f64.ln())).abs() < 1e-12);
    }

    #[test]
    fn features_line_up_with_names() {
        let hours: Vec<HourBar> = (0..200)
            .map(|i| HourBar {
                ts_ms: i * HOUR_MS,
                open: 1.0,
                high: 1.01,
                low: 0.99,
                close: 1.0,
                ret: if i % 2 == 0 { 0.001 } else { -0.001 },
                rv: 1e-5 * (1.0 + (i % 5) as f64),
                volume_q: 1000.0,
                taker_buy_q: 600.0,
                trades: 50.0,
                minutes: 60,
            })
            .collect();
        let f = features(&hours, &hours);
        let last = f.last().unwrap();
        assert!(last.iter().all(|v| v.is_finite()));
        assert_eq!(last[20], 0.0); // rel_har1 against itself
        assert!(f[0][3].is_nan()); // har168 needs 168 hours
    }
}
