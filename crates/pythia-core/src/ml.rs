//! Live volatility forecasts, in shadow mode.
//!
//! Pulls closed 1-minute Binance spot klines for the 20 coins the lab trained
//! on, rebuilds the hourly features exactly as the lab does (pythia-ml, held to
//! the lab by a parity test), and after every completed hour:
//!   1. scores the forecast made an hour ago against what actually happened,
//!      next to the HAR baseline from the model card;
//!   2. forecasts the next hour.
//! Nothing here places or sizes an order. The scores are what will decide
//! whether the risk manager may ever use these numbers.
//!
//! Where models come from: `PYTHIA_MODELS` points at the lab's model folder
//! (on the VPS `/srv/pythia-data/models`, on the PC the synced copy). The
//! newest `vol_1h/<date>/` that passes its own probe check is used.

use std::collections::{HashMap, VecDeque};
use std::path::{Path, PathBuf};
use std::sync::{Arc, RwLock};
use std::time::Duration;

use pythia_ml::drift::{self, DriftLevel};
use pythia_ml::shadow::{Scored, ShadowBook, ShadowSummary};
use pythia_ml::vol::{annualised_pct, Features, HOUR_MS};
use pythia_ml::{features, hourly_from_minutes, HourBar, MinuteBar, VolModel, FEATURES};
use serde::Serialize;
use serde_json::Value;

pub const UNIVERSE: [&str; 20] = [
    "BTC", "ETH", "SOL", "XRP", "DOGE", "ADA", "AVAX", "LINK", "LTC", "DOT",
    "BCH", "TRX", "SUI", "NEAR", "ATOM", "UNI", "AAVE", "XLM", "PEPE", "FIL",
];
const MINUTE_MS: i64 = 60_000;
/// History kept per coin: 168 hours of rolling windows plus a week of seasonal lags, with margin.
const KEEP_MINUTES: usize = 10 * 24 * 60;
const DRIFT_ROWS: usize = 7 * 24 * UNIVERSE.len();

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "camelCase")]
pub enum MlState {
    /// `PYTHIA_MODELS` is not set or holds no usable model.
    NoModel,
    /// A model file exists but failed its checks; `message` says why.
    Rejected,
    /// Fetching the first ten days of minutes.
    WarmingUp,
    Live,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ModelInfo {
    pub name: String,
    pub version: String,
    pub trees: usize,
    pub train_from_ms: i64,
    pub train_to_ms: i64,
    /// What the lab measured out of sample, for comparison with the live score.
    pub lab_gain_vs_har_pct: f64,
    pub lab_dm_p: f64,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct CoinForecast {
    pub coin: String,
    /// Start of the hour being forecast.
    pub hour_ms: i64,
    /// Annualised volatility in percent, as the model sees the coming hour.
    pub model_vol_pct: f64,
    pub har_vol_pct: f64,
    /// The hour that just closed, annualised.
    pub last_hour_vol_pct: f64,
    /// The last week's average, annualised. Forecast over this > 1 means calmer than usual is ending.
    pub week_vol_pct: f64,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct FeatureDrift {
    pub feature: String,
    /// How differently the last week spreads over the training bins (informational).
    pub psi: f64,
    /// Percent of the last week outside the range the model was trained on (the alarm).
    pub outside_pct: f64,
    pub level: DriftLevel,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct MlStatus {
    pub state: MlState,
    pub message: String,
    pub model: Option<ModelInfo>,
    pub coins: Vec<CoinForecast>,
    pub shadow: ShadowSummary,
    pub recent: Vec<Scored>,
    pub drift: Vec<FeatureDrift>,
    pub updated_ms: i64,
}

impl Default for MlStatus {
    fn default() -> Self {
        Self {
            state: MlState::NoModel,
            message: "Starting".into(),
            model: None,
            coins: vec![],
            shadow: ShadowSummary::default(),
            recent: vec![],
            drift: vec![],
            updated_ms: 0,
        }
    }
}

pub type SharedMl = Arc<RwLock<MlStatus>>;

/// Starts the shadow service on the current tokio runtime and returns the
/// status handle the UI reads. Safe to call when no model is configured: the
/// status then says so and the task idles.
pub fn spawn() -> SharedMl {
    let shared = new_shared();
    tokio::spawn(run(shared.clone()));
    shared
}

/// For runtimes that spawn on their own executor (Tauri): create the handle,
/// then spawn `run(handle.clone())` there.
pub fn new_shared() -> SharedMl {
    Arc::new(RwLock::new(MlStatus::default()))
}

fn now_ms() -> i64 {
    chrono::Utc::now().timestamp_millis()
}

fn set(shared: &SharedMl, f: impl FnOnce(&mut MlStatus)) {
    if let Ok(mut s) = shared.write() {
        f(&mut s);
        s.updated_ms = now_ms();
    }
}

fn load_model() -> Result<(VolModel, PathBuf), (MlState, String)> {
    let Ok(dir) = std::env::var("PYTHIA_MODELS") else {
        return Err((
            MlState::NoModel,
            "PYTHIA_MODELS is not set. Point it at the lab's model folder (the synced PythiaData/models).".into(),
        ));
    };
    let Some(version) = pythia_ml::latest_version(Path::new(&dir), "vol_1h") else {
        return Err((MlState::NoModel, format!("No vol_1h model with card.json and model.json under {dir}.")));
    };
    VolModel::load(&version)
        .map(|m| (m, version.clone()))
        .map_err(|e| (MlState::Rejected, format!("{}: {e}", version.display())))
}

pub async fn run(shared: SharedMl) {
    let (model, version) = loop {
        match tokio::task::spawn_blocking(load_model).await {
            Ok(Ok(ok)) => break ok,
            Ok(Err((state, msg))) => {
                set(&shared, |s| {
                    s.state = state;
                    s.message = msg;
                });
            }
            Err(e) => set(&shared, |s| {
                s.state = MlState::Rejected;
                s.message = format!("model loader crashed: {e}");
            }),
        }
        // Re-check every 10 minutes: a sync may deliver the model later.
        tokio::time::sleep(Duration::from_secs(600)).await;
    };
    let shadow_file = version.parent().map(|p| p.join("shadow.json"));
    let shadow = shadow_file
        .as_deref()
        .and_then(|p| std::fs::read_to_string(p).ok())
        .and_then(|t| serde_json::from_str::<Vec<Scored>>(&t).ok())
        .map(ShadowBook::restore)
        .unwrap_or_default();

    set(&shared, |s| {
        s.state = MlState::WarmingUp;
        s.message = "Fetching ten days of 1-minute klines".into();
        s.model = Some(model_info(&model, &version));
        s.shadow = shadow.summary();
    });

    let http = reqwest::Client::builder().timeout(Duration::from_secs(15)).build().unwrap_or_default();
    let mut svc = Service {
        model,
        version,
        shadow,
        shadow_file,
        minutes: HashMap::new(),
        drift_rows: VecDeque::new(),
        last_hour: 0,
    };
    loop {
        svc.refresh(&http).await;
        svc.process(&shared);
        svc.maybe_upgrade(&shared).await;
        // Wake 20 s after the next hour closes, when Binance has the last minute.
        let now = now_ms();
        let next = (now.div_euclid(HOUR_MS) + 1) * HOUR_MS + 20_000;
        let wait = if svc.last_hour == 0 { 60_000 } else { (next - now).max(5_000) };
        tokio::time::sleep(Duration::from_millis(wait as u64)).await;
    }
}

fn model_info(model: &VolModel, version: &Path) -> ModelInfo {
    ModelInfo {
        name: model.card.name.clone(),
        version: version.file_name().map(|n| n.to_string_lossy().into_owned()).unwrap_or_default(),
        trees: model.n_trees(),
        train_from_ms: model.card.train_from_us / 1000,
        train_to_ms: model.card.train_to_us / 1000,
        lab_gain_vs_har_pct: model.card.qlike_gain_vs_har * 100.0,
        lab_dm_p: model.card.dm_p_vs_har,
    }
}

struct Service {
    model: VolModel,
    version: PathBuf,
    shadow: ShadowBook,
    shadow_file: Option<PathBuf>,
    minutes: HashMap<&'static str, Vec<MinuteBar>>,
    drift_rows: VecDeque<Features>,
    last_hour: i64,
}

impl Service {
    /// The weekly retrain publishes a new version directory. Switch to it once it
    /// passes the same probe check as at startup; a version that fails keeps the
    /// current model running and says so. The live score carries on across versions.
    async fn maybe_upgrade(&mut self, shared: &SharedMl) {
        let Ok(dir) = std::env::var("PYTHIA_MODELS") else { return };
        let Some(newest) = pythia_ml::latest_version(Path::new(&dir), "vol_1h") else { return };
        if newest == self.version {
            return;
        }
        let candidate = newest.clone();
        match tokio::task::spawn_blocking(move || VolModel::load(&candidate)).await {
            Ok(Ok(model)) => {
                let info = model_info(&model, &newest);
                tracing::info!("volatility model upgraded to {}", newest.display());
                self.model = model;
                self.version = newest;
                set(shared, |s| s.model = Some(info));
            }
            Ok(Err(e)) => {
                tracing::warn!("newer model {} refused: {e}", newest.display());
                self.version = newest; // do not retry the same broken version every hour
                set(shared, |s| s.message = format!("A newer model was refused and the current one kept: {e}"));
            }
            Err(_) => {}
        }
    }

    async fn refresh(&mut self, http: &reqwest::Client) {
        let now = now_ms();
        for coin in UNIVERSE {
            let buf = self.minutes.entry(coin).or_default();
            let mut start = buf.last().map(|m| m.open_time_ms + MINUTE_MS).unwrap_or(now - KEEP_MINUTES as i64 * MINUTE_MS);
            // Page forward; Binance returns at most 1000 klines per call.
            for _ in 0..20 {
                if start > now - MINUTE_MS {
                    break;
                }
                let Some(page) = fetch_minutes(http, coin, start).await else { break };
                let closed: Vec<MinuteBar> = page.into_iter().filter(|m| m.open_time_ms + MINUTE_MS <= now).collect();
                let Some(last) = closed.last().map(|m| m.open_time_ms) else { break };
                let have = buf_last(buf);
                buf.extend(closed.into_iter().filter(|m| m.open_time_ms > have));
                start = last + MINUTE_MS;
            }
            if buf.len() > KEEP_MINUTES {
                buf.drain(..buf.len() - KEEP_MINUTES);
            }
        }
    }

    fn process(&mut self, shared: &SharedMl) {
        let now = now_ms();
        let closed_hour = now.div_euclid(HOUR_MS) * HOUR_MS - HOUR_MS;
        let hours_of = |m: &[MinuteBar]| -> Vec<HourBar> {
            hourly_from_minutes(m, None).into_iter().filter(|h| h.ts_ms + HOUR_MS <= now).collect()
        };
        let Some(btc) = self.minutes.get("BTC").map(|m| hours_of(m)) else { return };
        if btc.len() < 170 {
            set(shared, |s| {
                s.state = MlState::WarmingUp;
                s.message = format!("{} of 170 hours of history so far", btc.len());
            });
            return;
        }
        if closed_hour <= self.last_hour {
            return;
        }

        let mut coins = vec![];
        for coin in UNIVERSE {
            let Some(mins) = self.minutes.get(coin) else { continue };
            let hours = if coin == "BTC" { btc.clone() } else { hours_of(mins) };
            let Some(last) = hours.last().copied() else { continue };
            if last.ts_ms != closed_hour || hours.len() < 170 {
                continue; // the coin missed the hour or is too new: no forecast rather than a wrong one
            }
            let all = features(&hours, &btc);
            let x = *all.last().expect("non-empty");
            if self.last_hour == 0 {
                // First pass: seed the drift check with the past week instead of
                // waiting days for enough live hours to say anything.
                let from = all.len().saturating_sub(168);
                self.drift_rows.extend(all[from..all.len() - 1].iter().copied());
            }
            self.shadow.realise(coin, closed_hour, last.rv);
            let model_var = self.model.var(&x);
            let har_var = self.model.har_var(&x);
            self.shadow.forecast(coin, closed_hour + HOUR_MS, model_var, har_var, last.rv);
            let week: f64 = hours.iter().rev().take(168).map(|h| h.rv).sum::<f64>() / 168.0;
            coins.push(CoinForecast {
                coin: coin.to_string(),
                hour_ms: closed_hour + HOUR_MS,
                model_vol_pct: annualised_pct(model_var),
                har_vol_pct: annualised_pct(har_var),
                last_hour_vol_pct: annualised_pct(last.rv),
                week_vol_pct: annualised_pct(week),
            });
            self.drift_rows.push_back(x);
        }
        while self.drift_rows.len() > DRIFT_ROWS {
            self.drift_rows.pop_front();
        }
        self.last_hour = closed_hour;

        let drift: Vec<FeatureDrift> = FEATURES
            .iter()
            .enumerate()
            .filter_map(|(i, name)| {
                let bins = self.model.card.feature_bins.get(*name)?;
                let vals: Vec<f64> = self.drift_rows.iter().map(|r| r[i]).collect();
                let c = drift::check(bins, &vals)?;
                Some(FeatureDrift { feature: name.to_string(), psi: c.psi, outside_pct: c.outside_pct, level: c.level })
            })
            .collect();

        if let Some(p) = &self.shadow_file {
            if let Ok(text) = serde_json::to_string(&self.shadow.history()) {
                let tmp = p.with_extension("json.tmp");
                if std::fs::write(&tmp, text).is_ok() {
                    let _ = std::fs::rename(&tmp, p);
                }
            }
        }
        let n = coins.len();
        set(shared, |s| {
            s.state = MlState::Live;
            s.message = format!("Forecasting {n} coins, in shadow mode: scored, never traded");
            s.coins = coins;
            s.shadow = self.shadow.summary();
            s.recent = self.shadow.recent(40);
            s.drift = drift;
        });
    }
}

fn buf_last(buf: &[MinuteBar]) -> i64 {
    buf.last().map(|m| m.open_time_ms).unwrap_or(i64::MIN)
}

async fn fetch_minutes(http: &reqwest::Client, coin: &str, start_ms: i64) -> Option<Vec<MinuteBar>> {
    let url = format!(
        "https://api.binance.com/api/v3/klines?symbol={coin}USDT&interval=1m&startTime={start_ms}&limit=1000"
    );
    let v: Value = http.get(&url).send().await.ok()?.error_for_status().ok()?.json().await.ok()?;
    parse_klines(&v)
}

/// `[[openTime, open, high, low, close, volume, closeTime, quoteVolume, trades,
///   takerBuyBase, takerBuyQuote, ignore], …]`, numbers as strings.
fn parse_klines(v: &Value) -> Option<Vec<MinuteBar>> {
    let s = |x: &Value| x.as_str().and_then(|t| t.parse::<f64>().ok()).or_else(|| x.as_f64());
    v.as_array()?
        .iter()
        .map(|row| {
            let r = row.as_array()?;
            let mut open_time = r.first()?.as_i64()?;
            if open_time > 10_i64.pow(14) {
                open_time /= 1000; // microsecond timestamps, should Binance switch the REST API too
            }
            Some(MinuteBar {
                open_time_ms: open_time,
                open: s(r.get(1)?)?,
                high: s(r.get(2)?)?,
                low: s(r.get(3)?)?,
                close: s(r.get(4)?)?,
                quote_volume: s(r.get(7)?)?,
                taker_buy_quote_volume: s(r.get(10)?)?,
                trades: r.get(8)?.as_f64()?,
            })
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_binance_klines() {
        let v: Value = serde_json::from_str(
            r#"[[1790812800000,"62887.88","62900.00","62887.87","62893.06","7.71","1790812859999","485038.09",873,"1.18","74456.29","0"]]"#,
        )
        .unwrap();
        let m = parse_klines(&v).unwrap();
        assert_eq!(m.len(), 1);
        assert_eq!(m[0].open_time_ms, 1_790_812_800_000);
        assert_eq!(m[0].close, 62893.06);
        assert_eq!(m[0].quote_volume, 485038.09);
        assert_eq!(m[0].taker_buy_quote_volume, 74456.29);
        assert_eq!(m[0].trades, 873.0);
    }

    #[test]
    fn status_serialises_camel_case() {
        let s = serde_json::to_value(MlStatus::default()).unwrap();
        assert!(s.get("updatedMs").is_some());
        assert_eq!(s["state"], "noModel");
    }
}
