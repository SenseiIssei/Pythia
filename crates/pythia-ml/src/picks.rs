//! M2 "Picks": a weekly cross-sectional ranking of every liquid Binance coin by
//! its expected next-week return relative to the others.
//!
//! Every function here mirrors research/lab code:
//!   `latest_segment`      ->  lab/experiments/picks.py `hourly_segments()` (the last segment)
//!   `daily_from_hourly`   ->  `daily_from_hourly()`
//!   `spot_features`       ->  `features()` (the 16 spot columns, BTC joined by day)
//!   `perp_days`           ->  lab/experiments/picks_ls.py `perp_panel()` + picks.py `perp_features()`
//!   `attach_perp`         ->  the perp join in picks.py `build_raw()`
//!   `eligible`            ->  the eligibility filter in `build_raw()`
//!   `rank_cross_section`  ->  `rank_cross_section()`
//! The parity test (tests/picks_parity.rs) holds both sides together on real
//! data. Change one side, change the other, regenerate the fixture.
//!
//! Two places where the engine cannot see what the lab saw, both written into
//! the model card and shown on the Models page:
//!   * `age` counts rows since 2020 in the lab; the engine holds ~80 days of
//!     bars and continues the lab's count from the card's per-symbol anchors.
//!   * `fund7` values that differ only by float rounding (the lab sums funding
//!     in an unfixed order) are ranked as ties here, so they share the average
//!     rank the lab handed out among them in arbitrary order.

use std::collections::HashMap;
use std::path::Path;

use serde::{Deserialize, Serialize};
use serde_json::Value;

use crate::drift::Bins;
use crate::gbdt::Gbdt;
use crate::MlError;

pub const DAY_MS: i64 = 86_400_000;
pub const HOUR_MS: i64 = 3_600_000;
pub const HORIZON_DAYS: i64 = 7;
pub const MIN_HISTORY_D: f64 = 60.0;
/// A history with fewer daily rows than this is left out entirely (`MIN_HISTORY_D + 10`).
pub const MIN_HISTORY_ROWS: f64 = 70.0;
pub const MIN_ADV_USD: f64 = 1_000_000.0;
/// Days with fewer eligible coins are not ranked.
pub const MIN_COINS: usize = 20;
const GAP_SPLIT_MS: i64 = 3 * DAY_MS;

pub const SPOT_FEATURES: usize = 16;
pub const FEATURES: [&str; 19] = [
    "r1", "r3", "r7", "r14", "r28", "r56", "vol7", "vol28", "vol_ratio", "volu_trend", "adv28",
    "dist_hi28", "dist_lo28", "skew7", "resid28", "age", "fund7", "basis", "perp_share",
];
pub type Row = [f64; 19];
pub const ADV28: usize = 10;
pub const AGE: usize = 15;
pub const FUND7: usize = 16;
pub const BASIS: usize = 17;
pub const PERP_SHARE: usize = 18;
/// Funding rates carry 8 decimals, so two different 7-day sums differ by at
/// least 1e-8. Anything closer is the same number summed in another order.
const FUND7_TIE: f64 = 1e-12;

/// Not coins: the same exclusions as research/recorder/recorder/universe.py.
pub const STABLE: [&str; 31] = [
    "USDC", "BUSD", "TUSD", "FDUSD", "DAI", "PAX", "USDP", "UST", "USTC", "SUSD", "EUR", "GBP", "AUD", "TRY",
    "BRL", "RUB", "NGN", "UAH", "ZAR", "IDRT", "BIDR", "BKRW", "AEUR", "EURI", "USD1", "XUSD", "BFUSD", "USDE",
    "RLUSD", "PYUSD", "U",
];

/// Is `symbol` (e.g. "SOLUSDT") a coin the lab's universe would contain?
pub fn in_universe(symbol: &str) -> bool {
    let Some(base) = symbol.strip_suffix("USDT") else { return false };
    if base.is_empty() || STABLE.contains(&base) {
        return false;
    }
    !["UP", "DOWN", "BULL", "BEAR"].iter().any(|s| base.ends_with(s))
}

/// One closed 1-hour Binance spot kline.
#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
pub struct HourBar {
    pub open_time_ms: i64,
    pub high: f64,
    pub low: f64,
    pub close: f64,
    pub quote_volume: f64,
}

/// One UTC day built from hourly bars. Known at `day_ms + 24h`.
#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
pub struct DayBar {
    pub day_ms: i64,
    pub close: f64,
    pub high: f64,
    pub low: f64,
    /// Sum of squared hourly log returns.
    pub rv: f64,
    /// Quote volume (USDT).
    pub qv: f64,
    pub n: u32,
    /// Sum of cubed hourly log returns.
    pub skew_num: f64,
}

/// Index of the first bar of the latest continuous history in `hours` (sorted,
/// unique). A gap of more than three days or a tenfold move inside one hour
/// starts a new one: Binance reuses symbols and redenominates tokens.
pub fn segment_start(hours: &[HourBar]) -> usize {
    let jump = 10f64.ln();
    let mut start = 0;
    for i in 1..hours.len() {
        let gap = hours[i].open_time_ms - hours[i - 1].open_time_ms > GAP_SPLIT_MS;
        let mv = (hours[i].close.ln() - hours[i - 1].close.ln()).abs() > jump;
        if gap || mv {
            start = i;
        }
    }
    start
}

pub fn latest_segment(hours: &[HourBar]) -> &[HourBar] {
    &hours[segment_start(hours)..]
}

/// Hours (one segment, sorted) to days. The first hour's return is 0, as in the
/// lab. Days with fewer than 20 hourly bars are dropped.
pub fn daily_from_hourly(hours: &[HourBar]) -> Vec<DayBar> {
    let mut out: Vec<DayBar> = Vec::new();
    let mut prev: Option<f64> = None;
    for h in hours {
        let r = prev.map(|p| h.close.ln() - p.ln()).unwrap_or(0.0);
        prev = Some(h.close);
        let day = h.open_time_ms.div_euclid(DAY_MS) * DAY_MS;
        match out.last_mut() {
            Some(d) if d.day_ms == day => {
                d.close = h.close;
                d.high = d.high.max(h.high);
                d.low = d.low.min(h.low);
                d.rv += r * r;
                d.qv += h.quote_volume;
                d.n += 1;
                d.skew_num += r * r * r;
            }
            _ => out.push(DayBar {
                day_ms: day,
                close: h.close,
                high: h.high,
                low: h.low,
                rv: r * r,
                qv: h.quote_volume,
                n: 1,
                skew_num: r * r * r,
            }),
        }
    }
    out.retain(|d| d.n >= 20);
    out
}

/// The lab's age column for each day of the latest segment.
///
/// `anchor` is `(day_ms, age)` from the model card: the lab's own count on its
/// last day. `split_in_window` says the segment began inside the fetched bars
/// (a reuse or redenomination the engine saw happen), which makes the count
/// start over and the anchor stale. Without an anchor the coin is counted from
/// its first day here, which is exact for anything listed inside the window.
pub fn ages(days: &[DayBar], anchor: Option<(i64, f64)>, split_in_window: bool) -> Vec<f64> {
    let n = days.len();
    let from_zero = || (0..n).map(|i| i as f64).collect();
    let Some((aday, aage)) = anchor else { return from_zero() };
    if n == 0 || (split_in_window && days[0].day_ms > aday) {
        return from_zero();
    }
    // Last row on or before the anchor day.
    match days.iter().rposition(|d| d.day_ms <= aday) {
        Some(j) => {
            // The anchor day itself may be missing here (fewer than 20 bars):
            // count the calendar days from row j to it as rows the lab had.
            let base = aage - ((aday - days[j].day_ms) / DAY_MS) as f64;
            (0..n).map(|i| base + i as f64 - j as f64).collect()
        }
        None => {
            // The anchor is older than every bar held: one row per calendar day in between.
            let a0 = aage + ((days[0].day_ms - aday) / DAY_MS) as f64;
            (0..n).map(|i| a0 + i as f64).collect()
        }
    }
}

fn rolling(x: &[f64], n: usize, f: impl Fn(&[f64]) -> f64) -> Vec<f64> {
    (0..x.len())
        .map(|i| {
            if i + 1 < n {
                return f64::NAN;
            }
            let w = &x[i + 1 - n..=i];
            if w.iter().all(|v| v.is_finite()) {
                f(w)
            } else {
                f64::NAN
            }
        })
        .collect()
}

fn mean(w: &[f64]) -> f64 {
    w.iter().sum::<f64>() / w.len() as f64
}

fn sum(w: &[f64]) -> f64 {
    w.iter().sum()
}

/// The 16 spot features for every day of one coin; the perp columns are NaN.
/// `btc` are BTC's days (joined by day, as the lab does); `ages` from [`ages`].
pub fn spot_features(days: &[DayBar], btc: &[DayBar], ages: &[f64]) -> Vec<Row> {
    let n = days.len();
    let lc: Vec<f64> = days.iter().map(|d| d.close.ln()).collect();
    let rv: Vec<f64> = days.iter().map(|d| d.rv).collect();
    let qv: Vec<f64> = days.iter().map(|d| d.qv).collect();
    let hi: Vec<f64> = days.iter().map(|d| d.high).collect();
    let lo: Vec<f64> = days.iter().map(|d| d.low).collect();
    let sk: Vec<f64> = days.iter().map(|d| d.skew_num).collect();
    let btc_by_day: HashMap<i64, f64> = btc.iter().map(|d| (d.day_ms, d.close)).collect();
    let lbtc: Vec<f64> =
        days.iter().map(|d| btc_by_day.get(&d.day_ms).map(|c| c.ln()).unwrap_or(f64::NAN)).collect();

    let back = |x: &[f64], i: usize, k: usize| if i >= k { x[i] - x[i - k] } else { f64::NAN };
    let vol7: Vec<f64> = rolling(&rv, 7, mean).into_iter().map(f64::sqrt).collect();
    let vol28: Vec<f64> = rolling(&rv, 28, mean).into_iter().map(f64::sqrt).collect();
    let qv7 = rolling(&qv, 7, mean);
    let qv28 = rolling(&qv, 28, mean);
    let qv56 = rolling(&qv, 56, mean);
    let hi28 = rolling(&hi, 28, |w| w.iter().copied().fold(f64::NEG_INFINITY, f64::max));
    let lo28 = rolling(&lo, 28, |w| w.iter().copied().fold(f64::INFINITY, f64::min));
    let sk7 = rolling(&sk, 7, sum);
    let rv7 = rolling(&rv, 7, sum);

    (0..n)
        .map(|i| {
            let r28 = back(&lc, i, 28);
            let btc_r28 = back(&lbtc, i, 28);
            let mut x = [f64::NAN; 19];
            x[0] = back(&lc, i, 1);
            x[1] = back(&lc, i, 3);
            x[2] = back(&lc, i, 7);
            x[3] = back(&lc, i, 14);
            x[4] = r28;
            x[5] = back(&lc, i, 56);
            x[6] = vol7[i];
            x[7] = vol28[i];
            x[8] = vol7[i] / (vol28[i] + 1e-12);
            x[9] = (qv7[i] + 1.0).ln() - (qv56[i] + 1.0).ln();
            x[10] = (qv28[i] + 1.0).ln();
            x[11] = lc[i] - hi28[i].ln();
            x[12] = lc[i] - lo28[i].ln();
            x[13] = sk7[i] / (rv7[i].powf(1.5) + 1e-12);
            x[14] = r28 - btc_r28;
            x[15] = ages.get(i).copied().unwrap_or(f64::NAN);
            x
        })
        .collect()
}

/// The lab's base name of a perpetual: 1000PEPEUSDT -> PEPE.
pub fn perp_base(symbol: &str) -> &str {
    let base = &symbol[..symbol.len().saturating_sub(4)];
    for p in ["1000000", "1000", "1M"] {
        if base.len() > p.len() && base.starts_with(p) {
            return &base[p.len()..];
        }
    }
    base
}

/// One daily USD-M perpetual kline.
#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
pub struct PerpKline {
    pub day_ms: i64,
    pub close: f64,
    pub quote_volume: f64,
}

/// One settled funding payment.
#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
pub struct Funding {
    pub time_ms: i64,
    pub rate: f64,
}

#[derive(Debug, Clone, Copy, PartialEq, Serialize)]
pub struct PerpDay {
    pub day_ms: i64,
    pub close: f64,
    pub qv: f64,
    /// Funding over the last seven kline days, this one included (fewer at the start).
    pub fund7: f64,
}

/// One perpetual's days with its 7-day funding. Klines sorted by day.
pub fn perp_days(klines: &[PerpKline], funding: &[Funding]) -> Vec<PerpDay> {
    let mut per_day: HashMap<i64, f64> = HashMap::new();
    let mut seen = std::collections::HashSet::new();
    for f in funding {
        if seen.insert(f.time_ms) {
            *per_day.entry(f.time_ms.div_euclid(DAY_MS) * DAY_MS).or_default() += f.rate;
        }
    }
    let mut ks: Vec<PerpKline> = Vec::with_capacity(klines.len());
    for k in klines {
        if ks.last().map(|l: &PerpKline| l.day_ms) != Some(k.day_ms) {
            ks.push(*k);
        }
    }
    let daily: Vec<f64> = ks.iter().map(|k| per_day.get(&k.day_ms).copied().unwrap_or(0.0)).collect();
    ks.iter()
        .enumerate()
        .map(|(i, k)| PerpDay {
            day_ms: k.day_ms,
            close: k.close,
            qv: k.quote_volume,
            fund7: daily[i.saturating_sub(6)..=i].iter().sum(),
        })
        .collect()
}

/// Per day, the perpetual with the largest quote volume among `perps` (all of one base).
pub fn largest_perp_by_day(perps: &[Vec<PerpDay>]) -> HashMap<i64, PerpDay> {
    let mut out: HashMap<i64, PerpDay> = HashMap::new();
    for p in perps.iter().flatten() {
        match out.get(&p.day_ms) {
            Some(cur) if cur.qv >= p.qv => {}
            _ => {
                out.insert(p.day_ms, *p);
            }
        }
    }
    out
}

/// Fills fund7, basis and perp_share from the coin's perpetual that day.
pub fn attach_perp(x: &mut Row, spot_close: f64, spot_qv: f64, perp: Option<&PerpDay>) {
    let Some(p) = perp else {
        x[FUND7] = f64::NAN;
        x[BASIS] = f64::NAN;
        x[PERP_SHARE] = f64::NAN;
        return;
    };
    let mult = (p.close / spot_close).log10().round_ties_even();
    x[FUND7] = p.fund7;
    x[BASIS] = (p.close / (spot_close * 10f64.powf(mult))).ln();
    x[PERP_SHARE] = ((p.qv + 1.0) / (spot_qv + 1.0)).ln();
}

/// The lab's eligibility filter for one row. `history_rows` is the length of
/// the coin's continuous history up to today (the lab drops shorter ones).
pub fn eligible(x: &Row, history_rows: f64) -> bool {
    history_rows >= MIN_HISTORY_ROWS
        && x[AGE] >= MIN_HISTORY_D
        && x[ADV28] >= (MIN_ADV_USD + 1.0).ln()
        && x[..SPOT_FEATURES].iter().all(|v| v.is_finite())
}

/// Cross-sectional ranks of one day's eligible coins: `(rank - 1) / (n - 1)`
/// per feature, average rank for ties, missing stays missing, and `n` counts
/// every coin (also those whose value is missing), exactly as the lab's polars
/// `rank().over("day")` divided by `len().over("day") - 1`.
pub fn rank_cross_section(rows: &[Row]) -> Vec<Row> {
    let n = rows.len();
    let denom = (n.saturating_sub(1)).max(1) as f64;
    let mut out = vec![[f64::NAN; 19]; n];
    for j in 0..19 {
        let tol = if j == FUND7 { FUND7_TIE } else { 0.0 };
        let mut vals: Vec<(f64, usize)> =
            rows.iter().enumerate().filter(|(_, r)| r[j].is_finite()).map(|(i, r)| (r[j], i)).collect();
        vals.sort_by(|a, b| a.0.total_cmp(&b.0));
        let mut k = 0;
        while k < vals.len() {
            let mut e = k + 1;
            while e < vals.len() && vals[e].0 - vals[e - 1].0 <= tol {
                e += 1;
            }
            // Ranks k+1 ..= e share their average.
            let rank = (k + 1 + e) as f64 / 2.0;
            for &(_, i) in &vals[k..e] {
                out[i][j] = (rank - 1.0) / denom;
            }
            k = e;
        }
    }
    out
}

/// Spearman correlation (average ranks for ties); `None` below 10 pairs or without spread.
pub fn spearman(a: &[f64], b: &[f64]) -> Option<f64> {
    let pairs: Vec<(f64, f64)> = a.iter().zip(b).filter(|(x, y)| x.is_finite() && y.is_finite()).map(|(x, y)| (*x, *y)).collect();
    if pairs.len() < 10 {
        return None;
    }
    let ra = avg_ranks(&pairs.iter().map(|p| p.0).collect::<Vec<_>>());
    let rb = avg_ranks(&pairs.iter().map(|p| p.1).collect::<Vec<_>>());
    let n = ra.len() as f64;
    let (ma, mb) = (ra.iter().sum::<f64>() / n, rb.iter().sum::<f64>() / n);
    let (mut sab, mut saa, mut sbb) = (0.0, 0.0, 0.0);
    for (x, y) in ra.iter().zip(&rb) {
        sab += (x - ma) * (y - mb);
        saa += (x - ma) * (x - ma);
        sbb += (y - mb) * (y - mb);
    }
    (saa > 0.0 && sbb > 0.0).then(|| sab / (saa * sbb).sqrt())
}

fn avg_ranks(x: &[f64]) -> Vec<f64> {
    let mut idx: Vec<usize> = (0..x.len()).collect();
    idx.sort_by(|&a, &b| x[a].total_cmp(&x[b]));
    let mut out = vec![0.0; x.len()];
    let mut k = 0;
    while k < idx.len() {
        let mut e = k + 1;
        while e < idx.len() && x[idx[e]] == x[idx[k]] {
            e += 1;
        }
        let r = (k + 1 + e) as f64 / 2.0;
        for &i in &idx[k..e] {
            out[i] = r;
        }
        k = e;
    }
    out
}

/// The model card the lab writes next to M2 (lab/export/picks.py).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PicksCard {
    pub name: String,
    #[serde(default)]
    pub model: String,
    pub created: String,
    #[serde(default)]
    pub target: String,
    #[serde(default)]
    pub horizon_days: i64,
    pub features: Vec<String>,
    #[serde(default)]
    pub feature_definitions: HashMap<String, String>,
    #[serde(default)]
    pub ranking: String,
    /// Where the engine's inputs can differ from the lab's, in plain words.
    #[serde(default)]
    pub engine_notes: Vec<String>,
    pub train_from_us: i64,
    pub train_to_us: i64,
    #[serde(default)]
    pub out_of_sample: Value,
    #[serde(default)]
    pub verdict: String,
    /// Drift reference on the raw (unranked) feature values.
    #[serde(default)]
    pub raw_feature_bins: HashMap<String, Bins>,
    #[serde(default)]
    pub typical_day: Value,
    /// Per symbol: `[day_us, age]`, the lab's age count on its last day.
    #[serde(default)]
    pub age_anchors: HashMap<String, (i64, f64)>,
    pub probe: crate::card::Probe,
}

impl PicksCard {
    /// The lab's out-of-sample mean daily Rank-IC.
    pub fn lab_rank_ic(&self) -> Option<f64> {
        self.out_of_sample.get("rank_ic").and_then(Value::as_f64)
    }

    /// The anchor for `symbol` in milliseconds.
    pub fn anchor(&self, symbol: &str) -> Option<(i64, f64)> {
        self.age_anchors.get(symbol).map(|&(us, age)| (us / 1000, age))
    }
}

/// A loaded, verified M2 model.
pub struct PicksModel {
    pub card: PicksCard,
    gbdt: Gbdt,
}

impl PicksModel {
    /// Loads `card.json` and `model.json` from `dir` and refuses the model unless
    /// its feature list is exactly ours and it reproduces every probe row.
    pub fn load(dir: &Path) -> Result<Self, MlError> {
        let read = |name: &str| {
            std::fs::read_to_string(dir.join(name)).map_err(|e| MlError::Io(format!("{}: {e}", dir.join(name).display())))
        };
        let card: PicksCard =
            serde_json::from_str(&read("card.json")?).map_err(|e| MlError::Format(format!("card.json: {e}")))?;
        let gbdt = Gbdt::from_json(&read("model.json")?)?;
        Self::new(card, gbdt)
    }

    pub fn new(card: PicksCard, gbdt: Gbdt) -> Result<Self, MlError> {
        if card.features.iter().map(String::as_str).ne(FEATURES.iter().copied()) {
            return Err(MlError::Mismatch(format!(
                "model expects features {:?}, the engine computes {:?}",
                card.features, FEATURES
            )));
        }
        if gbdt.n_features != FEATURES.len() {
            return Err(MlError::Mismatch(format!("model has {} inputs, expected {}", gbdt.n_features, FEATURES.len())));
        }
        if card.probe.x.is_empty() {
            return Err(MlError::Mismatch("model card has no probe rows to verify against".into()));
        }
        for (row, want) in card.probe.x.iter().zip(&card.probe.raw) {
            let x: Vec<f64> = row.iter().map(|v| v.unwrap_or(f64::NAN)).collect();
            let got = gbdt.predict(&x);
            if (got - want).abs() > 1e-9 {
                return Err(MlError::Mismatch(format!("probe output {got} differs from LightGBM's {want}")));
            }
        }
        Ok(Self { card, gbdt })
    }

    pub fn n_trees(&self) -> usize {
        self.gbdt.n_trees()
    }

    /// Ranking score for one row of cross-sectional ranks. Higher = expected to do better.
    pub fn score(&self, ranked: &Row) -> f64 {
        self.gbdt.predict(ranked)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn hour(t: i64, close: f64) -> HourBar {
        HourBar { open_time_ms: t, high: close * 1.01, low: close * 0.99, close, quote_volume: 1e5 }
    }

    #[test]
    fn universe_filter_matches_the_recorder() {
        assert!(in_universe("SOLUSDT"));
        assert!(!in_universe("USDCUSDT"));
        assert!(!in_universe("BTCUPUSDT"));
        assert!(!in_universe("ETHBTC"));
        assert!(!in_universe("UUSDT"));
    }

    #[test]
    fn perp_base_strips_multipliers() {
        assert_eq!(perp_base("1000PEPEUSDT"), "PEPE");
        assert_eq!(perp_base("1000000MOGUSDT"), "MOG");
        assert_eq!(perp_base("1MBABYDOGEUSDT"), "BABYDOGE");
        assert_eq!(perp_base("BTCUSDT"), "BTC");
        assert_eq!(perp_base("1000USDT"), "1000");
    }

    #[test]
    fn a_gap_or_a_tenfold_hour_starts_a_new_history() {
        let mut h: Vec<HourBar> = (0..10).map(|i| hour(i * HOUR_MS, 1.0)).collect();
        assert_eq!(segment_start(&h), 0);
        h.push(hour(9 * HOUR_MS + 4 * DAY_MS, 1.0));
        assert_eq!(segment_start(&h), 10);
        h.push(hour(11 * HOUR_MS + 4 * DAY_MS, 20.0));
        assert_eq!(segment_start(&h), 11);
    }

    #[test]
    fn days_need_twenty_hours() {
        let mut h: Vec<HourBar> = (0..24).map(|i| hour(i * HOUR_MS, 100.0 + i as f64)).collect();
        h.extend((0..19).map(|i| hour(DAY_MS + i * HOUR_MS, 50.0)));
        let d = daily_from_hourly(&h);
        assert_eq!(d.len(), 1);
        assert_eq!(d[0].n, 24);
        assert_eq!(d[0].close, 123.0);
        let r: Vec<f64> = (1..24).map(|i| ((100.0 + i as f64) / (99.0 + i as f64)).ln()).collect();
        assert!((d[0].rv - r.iter().map(|x| x * x).sum::<f64>()).abs() < 1e-15);
    }

    fn day(d: i64) -> DayBar {
        DayBar { day_ms: d * DAY_MS, close: 1.0, high: 1.0, low: 1.0, rv: 0.0, qv: 0.0, n: 24, skew_num: 0.0 }
    }

    #[test]
    fn ages_continue_the_lab_count() {
        let days: Vec<DayBar> = (100..110).map(day).collect();
        // Anchor inside the window: exact.
        assert_eq!(ages(&days, Some((105 * DAY_MS, 500.0)), false)[0], 495.0);
        // Anchor before the window: one row per calendar day in between.
        assert_eq!(ages(&days, Some((90 * DAY_MS, 400.0)), false)[0], 410.0);
        // No anchor: counted from the first day held.
        assert_eq!(ages(&days, None, false)[9], 9.0);
        // A split seen after the anchor makes the count start over.
        assert_eq!(ages(&days, Some((90 * DAY_MS, 400.0)), true)[3], 3.0);
    }

    #[test]
    fn funding_sums_seven_kline_days() {
        let k: Vec<PerpKline> = (0..10).map(|d| PerpKline { day_ms: d * DAY_MS, close: 1.0, quote_volume: 1.0 }).collect();
        let f: Vec<Funding> = (0..30).map(|i| Funding { time_ms: i * 8 * HOUR_MS, rate: 0.0001 }).collect();
        let p = perp_days(&k, &f);
        assert!((p[0].fund7 - 0.0003).abs() < 1e-15);
        assert!((p[9].fund7 - 0.0021).abs() < 1e-15);
    }

    #[test]
    fn basis_undoes_the_price_multiplier() {
        let mut x = [0.0; 19];
        let p = PerpDay { day_ms: 0, close: 0.0101, qv: 9.0, fund7: 0.001 };
        attach_perp(&mut x, 0.00001, 4.0, Some(&p));
        assert!((x[BASIS] - (0.0101f64 / 0.01).ln()).abs() < 1e-12);
        assert!((x[PERP_SHARE] - 2f64.ln()).abs() < 1e-12);
        attach_perp(&mut x, 1.0, 1.0, None);
        assert!(x[FUND7].is_nan());
    }

    #[test]
    fn ranks_like_polars() {
        let mut rows = vec![[0.0; 19]; 4];
        for (i, v) in [3.0, f64::NAN, 1.0, 3.0].iter().enumerate() {
            rows[i][0] = *v;
        }
        let r = rank_cross_section(&rows);
        // polars: ranks [2.5, null, 1, 2.5], divided by n - 1 = 3 (the missing coin counts)
        assert_eq!(r[0][0], 1.5 / 3.0);
        assert!(r[1][0].is_nan());
        assert_eq!(r[2][0], 0.0);
        assert_eq!(r[3][0], 1.5 / 3.0);
    }

    #[test]
    fn fund7_rounding_noise_is_a_tie() {
        let mut rows = vec![[0.0; 19]; 3];
        rows[0][FUND7] = 0.0021;
        rows[1][FUND7] = 0.0021 + 4e-19;
        rows[2][FUND7] = 0.0022;
        let r = rank_cross_section(&rows);
        assert_eq!(r[0][FUND7], r[1][FUND7]);
        assert_eq!(r[2][FUND7], 1.0);
    }

    #[test]
    fn spearman_of_a_perfect_order_is_one() {
        let a: Vec<f64> = (0..20).map(f64::from).collect();
        let b: Vec<f64> = a.iter().map(|x| x * x).collect();
        assert!((spearman(&a, &b).unwrap() - 1.0).abs() < 1e-12);
        let c: Vec<f64> = a.iter().map(|x| -x).collect();
        assert!((spearman(&a, &c).unwrap() + 1.0).abs() < 1e-12);
        assert!(spearman(&a[..5], &b[..5]).is_none());
    }
}
