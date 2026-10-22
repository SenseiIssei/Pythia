//! The pump.fun wallet page: what the lab's live service reports, the owner's
//! lower limits, and the kill switch.
//!
//! The live service (`research/lab/lab/pumpfun_rt/live_service.py`, started by
//! the owner by hand, docs/PUMPFUN-LIVE.md) writes under
//! `<data>/reports/pumpfun_rt/`:
//!
//! - `live_status.json`: mode, on or off and why, the wallet's public address,
//!   its SOL balance, token holdings, open positions, today's and the total P&L,
//!   the confirmation file's limits, the effective limits, the stops;
//! - `live_trades.json`: the newest closed live trades;
//! - `execution.json`: measured latency, slippage and fees against the paper model.
//!
//! The owner's wallet tool writes `wallet.json` (the public address only) when
//! it makes the wallet, so the page can show where to send SOL before the
//! service ever ran. Nothing here reads a key or moves money; there is no
//! withdraw or transfer anywhere in Pythia.
//!
//! Two writes, both of which can only make the live book safer:
//!
//! - `live_settings.json`: limits the owner sets in the app. Each must be a
//!   positive number at or below what the confirmation file allows (and the
//!   hard maxima in code); the lab takes the lowest of them again.
//! - `KILL`: the kill switch. The live book stops buying and sells what is open.
//!   Nothing here deletes it: allowing buys again means deleting the file on the
//!   server by hand.

use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};

use crate::labview::data_dir;

/// Hard maxima of the live test, the same numbers as the lab's `live_exec.TEST_MAX_*`.
pub const TEST_MAX_TOTAL_SOL: f64 = 2.0;
pub const TEST_MAX_DAILY_LOSS_SOL: f64 = 0.5;
pub const TEST_MAX_TRADE_SOL: f64 = 0.1;
/// The full (readiness) mode's caps, the lab's `pipeline.HARD_*`.
pub const FULL_MAX_DAILY_LOSS_SOL: f64 = 1.0;
pub const FULL_MAX_TRADE_SOL: f64 = 0.1;
pub const MAX_OPEN: u32 = 5;
/// The service writes its status every 30 s; older than this, it is not running.
pub const STALE_MS: i64 = 120_000;

fn dir_in(root: &Path) -> PathBuf {
    root.join("reports").join("pumpfun_rt")
}

/// The file whose presence stops the live book (the lab's `live_exec.live_kill_paths`).
pub fn kill_path_in(root: &Path) -> PathBuf {
    dir_in(root).join("KILL")
}

fn read<T: for<'de> Deserialize<'de>>(p: &Path) -> Option<T> {
    serde_json::from_str(&std::fs::read_to_string(p).ok()?).ok()
}

// ── what the live service writes (snake_case on disk, camelCase to the app) ──

#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq)]
#[serde(default, rename_all(serialize = "camelCase", deserialize = "snake_case"))]
pub struct AckView {
    /// "test" or "full"; null when the confirmation file is missing.
    pub mode: Option<String>,
    pub strategy: Option<String>,
    pub max_total_sol: Option<f64>,
    pub max_daily_loss_sol: Option<f64>,
    pub max_trade_sol: Option<f64>,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq)]
#[serde(default, rename_all(serialize = "camelCase", deserialize = "snake_case"))]
pub struct Limits {
    pub max_trade_sol: Option<f64>,
    pub max_open: Option<u32>,
    pub max_exposure_sol: Option<f64>,
    pub max_daily_loss_sol: Option<f64>,
    pub max_total_sol: Option<f64>,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq)]
#[serde(default, rename_all(serialize = "camelCase", deserialize = "snake_case"))]
pub struct Position {
    pub pid: Option<i64>,
    pub mint: String,
    pub symbol: Option<String>,
    pub name: Option<String>,
    pub venue: Option<String>,
    pub state: Option<String>,
    pub tokens: Option<f64>,
    pub cost_sol: Option<f64>,
    pub mark_sol: Option<f64>,
    pub signal_ms: Option<i64>,
    pub land_ms: Option<i64>,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq)]
#[serde(default, rename_all(serialize = "camelCase", deserialize = "snake_case"))]
pub struct Holding {
    pub mint: String,
    /// Raw token units.
    pub amount: f64,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq)]
#[serde(default, rename_all(serialize = "camelCase", deserialize = "snake_case"))]
pub struct Stops {
    pub daily: bool,
    pub total: bool,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq)]
#[serde(default, rename_all(serialize = "camelCase", deserialize = "snake_case"))]
pub struct Simulation {
    pub t: Option<i64>,
    pub ok: Option<bool>,
    pub venue: Option<String>,
    pub mint: Option<String>,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq)]
#[serde(default, rename_all(serialize = "camelCase", deserialize = "snake_case"))]
pub struct LiveStatus {
    pub t: i64,
    pub running: bool,
    pub on: bool,
    pub mode: Option<String>,
    pub rule: Option<String>,
    pub address: Option<String>,
    pub balance_sol: Option<f64>,
    pub balance_t: Option<i64>,
    pub holdings: Vec<Holding>,
    pub positions: Vec<Position>,
    pub leftovers: Vec<serde_json::Value>,
    pub pnl_today_sol: f64,
    pub trades_today: u32,
    pub wins_today: u32,
    pub pnl_total_sol: f64,
    pub trades_total: u32,
    pub since_ms: Option<i64>,
    /// Every reason the book does not trade (empty when it may).
    pub gate: Vec<String>,
    pub refusing: Option<String>,
    pub ack: AckView,
    pub limits: Option<Limits>,
    pub stops: Stops,
    pub kill: bool,
    pub simulate: Option<Simulation>,
    pub exposure_sol: f64,
    pub skipped: std::collections::BTreeMap<String, u64>,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq)]
#[serde(default, rename_all(serialize = "camelCase", deserialize = "snake_case"))]
pub struct LiveTrade {
    pub mode: Option<String>,
    pub rule: Option<String>,
    pub mint: Option<String>,
    pub name: Option<String>,
    pub symbol: Option<String>,
    pub signal_ms: Option<f64>,
    pub land_ms: Option<f64>,
    pub exit_ms: Option<f64>,
    pub exit_why: Option<String>,
    pub stake_sol: Option<f64>,
    pub proceeds_sol: Option<f64>,
    pub pnl_sol: Option<f64>,
    pub ret: Option<f64>,
    pub hold_s: Option<f64>,
    pub lat_buy_ms: Option<f64>,
    pub slip: Option<f64>,
}

#[derive(Debug, Clone, Default, Deserialize)]
#[serde(default)]
struct TradesFile {
    trades: Vec<LiveTrade>,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq)]
#[serde(default, rename_all(serialize = "camelCase", deserialize = "snake_case"))]
pub struct Dist {
    pub n: u32,
    pub median: Option<f64>,
    pub p10: Option<f64>,
    pub p90: Option<f64>,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq)]
#[serde(default, rename_all(serialize = "camelCase", deserialize = "snake_case"))]
pub struct Assumed {
    pub lat_median_ms: Option<f64>,
    pub lat_lo_ms: Option<f64>,
    pub lat_hi_ms: Option<f64>,
    pub tx_fee_sol: Option<f64>,
    pub slip_tol: Option<f64>,
}

/// Measured execution against the paper model (the lab's `measure.py`).
#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq)]
#[serde(default, rename_all(serialize = "camelCase", deserialize = "snake_case"))]
pub struct Execution {
    pub verdict: String,
    pub fills: u32,
    pub failed: u32,
    pub lat_buy_ms: Dist,
    pub send_to_land_ms: Dist,
    pub slip_buy: Dist,
    pub paper_slip: Dist,
    pub fee_sol: Dist,
    pub assumed: Assumed,
    pub lat_ratio: Option<f64>,
}

#[derive(Debug, Clone, Default, Deserialize)]
#[serde(default)]
struct WalletFile {
    address: Option<String>,
}

/// The hard maxima, for the page's help text.
#[derive(Debug, Clone, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct Hard {
    pub test_max_total_sol: f64,
    pub test_max_daily_loss_sol: f64,
    pub test_max_trade_sol: f64,
    pub full_max_daily_loss_sol: f64,
    pub full_max_trade_sol: f64,
    pub max_open: u32,
}

impl Default for Hard {
    fn default() -> Self {
        Hard {
            test_max_total_sol: TEST_MAX_TOTAL_SOL,
            test_max_daily_loss_sol: TEST_MAX_DAILY_LOSS_SOL,
            test_max_trade_sol: TEST_MAX_TRADE_SOL,
            full_max_daily_loss_sol: FULL_MAX_DAILY_LOSS_SOL,
            full_max_trade_sol: FULL_MAX_TRADE_SOL,
            max_open: MAX_OPEN,
        }
    }
}

/// Everything the page shows, in one answer.
#[derive(Debug, Clone, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct LiveView {
    /// The service wrote its status within `STALE_MS` and did not say it stopped.
    pub running: bool,
    pub status: Option<LiveStatus>,
    /// The wallet's public address: from the service, else from the wallet tool's file.
    pub address: Option<String>,
    pub settings: LiveSettings,
    /// The app's kill file is there (only deleting it on the server allows buys again).
    pub kill_file: bool,
    pub trades: Vec<LiveTrade>,
    pub execution: Option<Execution>,
    pub hard: Hard,
    pub now_ms: i64,
    /// SOL in euro right now, for the page's euro figures; none when the ticker
    /// could not be read (the page then shows SOL only).
    pub sol_eur: Option<SolEur>,
}

/// The price of one SOL in euro from Kraken's public ticker (pair SOLEUR, no key).
#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct SolEur {
    /// The last trade.
    pub price: f64,
    /// Today's opening price (00:00 UTC), for the change since.
    pub open: f64,
    /// When it was read (ms).
    pub t: i64,
}

const SOL_EUR_URL: &str = "https://api.kraken.com/0/public/Ticker?pair=SOLEUR";
/// Read the ticker at most this often; the page refreshes every 15 s.
const SOL_EUR_TTL_MS: i64 = 15_000;
/// Keep showing the last good price this long when a read fails, then show none.
const SOL_EUR_KEEP_MS: i64 = 600_000;

/// The SOLEUR entry of a Kraken ticker answer: `c[0]` is the last trade, `o` today's open.
pub fn parse_sol_eur(body: &serde_json::Value, now_ms: i64) -> Option<SolEur> {
    let t = body.get("result")?.as_object()?.values().next()?;
    let num = |v: &serde_json::Value| v.as_str().and_then(|s| s.parse::<f64>().ok()).filter(|x| x.is_finite() && *x > 0.0);
    Some(SolEur { price: num(t.get("c")?.get(0)?)?, open: num(t.get("o")?)?, t: now_ms })
}

/// SOL in euro, from a 15 s cache in front of Kraken's public ticker. A failed read
/// keeps the last good price for ten minutes, so one hiccup does not blank the page.
pub async fn sol_eur(now_ms: i64) -> Option<SolEur> {
    use std::sync::{Mutex, OnceLock};
    static CACHE: OnceLock<Mutex<Option<SolEur>>> = OnceLock::new();
    let cache = CACHE.get_or_init(|| Mutex::new(None));
    let last = cache.lock().ok().and_then(|c| c.clone());
    if let Some(p) = &last {
        if now_ms - p.t < SOL_EUR_TTL_MS {
            return last;
        }
    }
    let client = reqwest::Client::builder().timeout(std::time::Duration::from_secs(5)).build().ok()?;
    let fresh = match client.get(SOL_EUR_URL).send().await {
        Ok(r) => r.json::<serde_json::Value>().await.ok().and_then(|b| parse_sol_eur(&b, now_ms)),
        Err(_) => None,
    };
    match fresh {
        Some(p) => {
            if let Ok(mut c) = cache.lock() {
                *c = Some(p.clone());
            }
            Some(p)
        }
        None => last.filter(|p| now_ms - p.t < SOL_EUR_KEEP_MS),
    }
}

/// What the page shows, read from `root` (the lab's data folder).
pub fn view_in(root: &Path, now_ms: i64) -> LiveView {
    let d = dir_in(root);
    let status: Option<LiveStatus> = read(&d.join("live_status.json"));
    let running = status.as_ref().is_some_and(|s| s.running && now_ms - s.t <= STALE_MS);
    let address = status
        .as_ref()
        .and_then(|s| s.address.clone())
        .or_else(|| read::<WalletFile>(&d.join("wallet.json")).and_then(|w| w.address))
        .filter(|a| is_address(a));
    LiveView {
        running,
        status,
        address,
        settings: settings_in(root),
        kill_file: kill_path_in(root).exists(),
        trades: read::<TradesFile>(&d.join("live_trades.json")).map(|f| f.trades).unwrap_or_default(),
        execution: read(&d.join("execution.json")),
        hard: Hard::default(),
        now_ms,
        sol_eur: None,
    }
}

/// The live chart's feed (`live_feed.json`, the lab's `live_feed.py`): the coins the bot holds or
/// just closed, with every trade on them. Passed on as written; the page reads its fields.
pub fn feed_in(root: &Path) -> Option<serde_json::Value> {
    read(&dir_in(root).join("live_feed.json"))
}

/// When the files behind the view and behind the feed last changed: the live socket pushes a
/// new view or a new feed when its stamp moves.
pub fn stamps_in(root: &Path) -> (Vec<Option<std::time::SystemTime>>, Option<std::time::SystemTime>) {
    let d = dir_in(root);
    let m = |p: PathBuf| std::fs::metadata(p).and_then(|m| m.modified()).ok();
    let view = ["live_status.json", "live_trades.json", "execution.json", "live_settings.json", "KILL"]
        .into_iter()
        .map(|f| m(d.join(f)))
        .collect();
    (view, m(d.join("live_feed.json")))
}

/// The view from the lab's data folder (`PYTHIA_DATA`), or an empty one without it.
pub fn view() -> LiveView {
    let now = chrono::Utc::now().timestamp_millis();
    match data_dir() {
        Some(root) => view_in(&root, now),
        None => LiveView {
            running: false,
            status: None,
            address: None,
            settings: LiveSettings::default(),
            kill_file: false,
            trades: Vec::new(),
            execution: None,
            hard: Hard::default(),
            now_ms: now,
            sol_eur: None,
        },
    }
}

/// The newest closed live trades.
pub fn trades() -> Vec<LiveTrade> {
    data_dir()
        .and_then(|root| read::<TradesFile>(&dir_in(&root).join("live_trades.json")))
        .map(|f| f.trades)
        .unwrap_or_default()
}

/// A Solana address as text: base58, 32 to 44 characters. Anything else is not shown.
pub fn is_address(s: &str) -> bool {
    (32..=44).contains(&s.len())
        && s.chars().all(|c| c.is_ascii_alphanumeric() && !matches!(c, '0' | 'O' | 'I' | 'l'))
}

// ── the owner's lower limits ──

#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq)]
#[serde(default, rename_all(serialize = "camelCase", deserialize = "snake_case"))]
pub struct LiveSettings {
    pub max_total_sol: Option<f64>,
    pub max_daily_loss_sol: Option<f64>,
    pub max_trade_sol: Option<f64>,
    pub max_open: Option<u32>,
    pub updated_ms: i64,
}

/// What the app posts. A missing or null field means "no lower limit of mine":
/// the confirmation file's value applies.
#[derive(Debug, Clone, Default, Deserialize)]
#[serde(default, rename_all = "camelCase", deny_unknown_fields)]
pub struct SettingsPatch {
    pub max_total_sol: Option<f64>,
    pub max_daily_loss_sol: Option<f64>,
    pub max_trade_sol: Option<f64>,
    pub max_open: Option<u32>,
}

#[derive(Serialize)]
struct SettingsFile {
    max_total_sol: Option<f64>,
    max_daily_loss_sol: Option<f64>,
    max_trade_sol: Option<f64>,
    max_open: Option<u32>,
    updated_ms: i64,
}

fn settings_path_in(root: &Path) -> PathBuf {
    dir_in(root).join("live_settings.json")
}

pub fn settings_in(root: &Path) -> LiveSettings {
    read(&settings_path_in(root)).unwrap_or_default()
}

/// The ceilings a setting must stay under: the confirmation file's values as the
/// live service last reported them, never above the hard maxima of its mode.
#[derive(Debug, Clone, PartialEq)]
pub struct Ceilings {
    pub max_total_sol: Option<f64>,
    pub max_daily_loss_sol: f64,
    pub max_trade_sol: f64,
}

pub fn ceilings(ack: &AckView) -> Result<Ceilings, String> {
    let low = |a: Option<f64>, hard: f64| a.filter(|v| v.is_finite() && *v > 0.0).map_or(hard, |v| v.min(hard));
    match ack.mode.as_deref() {
        Some("test") => Ok(Ceilings {
            max_total_sol: Some(low(ack.max_total_sol, TEST_MAX_TOTAL_SOL)),
            max_daily_loss_sol: low(ack.max_daily_loss_sol, TEST_MAX_DAILY_LOSS_SOL),
            max_trade_sol: low(ack.max_trade_sol, TEST_MAX_TRADE_SOL),
        }),
        Some("full") => Ok(Ceilings {
            max_total_sol: None,
            max_daily_loss_sol: low(ack.max_daily_loss_sol, FULL_MAX_DAILY_LOSS_SOL),
            max_trade_sol: FULL_MAX_TRADE_SOL,
        }),
        _ => Err("The live service has not reported a confirmation file yet. Write the file and start the live \
                  service first; limits can only be set below what it allows."
            .into()),
    }
}

fn check(name: &str, v: Option<f64>, ceiling: Option<f64>) -> Result<(), String> {
    let Some(v) = v else { return Ok(()) };
    if !v.is_finite() || v <= 0.0 {
        return Err(format!("{name} must be a positive number of SOL."));
    }
    if let Some(c) = ceiling {
        if v > c + 1e-12 {
            return Err(format!("{name} can only be lowered: at most {c} SOL (the confirmation file and the code's maximum)."));
        }
    }
    Ok(())
}

/// Save new lower limits under `root`, all or nothing (temp file, then rename).
pub fn write_settings_in(root: &Path, patch: SettingsPatch, now_ms: i64) -> Result<LiveSettings, String> {
    let ack = read::<LiveStatus>(&dir_in(root).join("live_status.json")).map(|s| s.ack).unwrap_or_default();
    let c = ceilings(&ack)?;
    // Full mode has no total budget of its own: any positive one only adds a stop.
    check("The total budget", patch.max_total_sol, c.max_total_sol)?;
    check("The daily loss limit", patch.max_daily_loss_sol, Some(c.max_daily_loss_sol))?;
    check("The amount per trade", patch.max_trade_sol, Some(c.max_trade_sol))?;
    if let Some(n) = patch.max_open {
        if !(1..=MAX_OPEN).contains(&n) {
            return Err(format!("Open positions must be between 1 and {MAX_OPEN}."));
        }
    }
    let file = SettingsFile {
        max_total_sol: patch.max_total_sol,
        max_daily_loss_sol: patch.max_daily_loss_sol,
        max_trade_sol: patch.max_trade_sol,
        max_open: patch.max_open,
        updated_ms: now_ms,
    };
    let p = settings_path_in(root);
    let dir = p.parent().expect("settings path has a folder");
    let body = serde_json::to_vec_pretty(&file).map_err(|e| e.to_string())?;
    let write = || -> std::io::Result<()> {
        std::fs::create_dir_all(dir)?;
        let tmp = dir.join("live_settings.json.tmp");
        std::fs::write(&tmp, &body)?;
        std::fs::rename(&tmp, &p)
    };
    write().map_err(|e| format!("The limits could not be saved: {e}"))?;
    Ok(settings_in(root))
}

pub fn write_settings(patch: SettingsPatch) -> Result<LiveSettings, String> {
    let root = data_dir().ok_or_else(|| "No lab data folder is set (PYTHIA_DATA).".to_string())?;
    write_settings_in(&root, patch, chrono::Utc::now().timestamp_millis())
}

// ── the kill switch ──

#[derive(Debug, Clone, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct KillState {
    pub kill_file: bool,
    pub path: String,
    pub already: bool,
}

/// Create the kill file under `root` (kept as it is when it is already there).
/// There is no way back through the API: delete the file on the server.
pub fn kill_in(root: &Path, now_ms: i64) -> Result<KillState, String> {
    let p = kill_path_in(root);
    let already = p.exists();
    if !already {
        let when = chrono::DateTime::from_timestamp_millis(now_ms).map(|t| t.to_rfc3339()).unwrap_or_default();
        let text = format!(
            "Kill switch set from the app at {when}.\nThe live pump.fun book buys nothing and sells what is open while this file exists.\nDelete it on the server to allow buys again (docs/PUMPFUN-LIVE.md).\n"
        );
        std::fs::create_dir_all(p.parent().expect("kill path has a folder"))
            .and_then(|_| std::fs::write(&p, text))
            .map_err(|e| format!("The kill file could not be written: {e}"))?;
    }
    Ok(KillState { kill_file: true, path: "reports/pumpfun_rt/KILL".into(), already })
}

pub fn kill() -> Result<KillState, String> {
    let root = data_dir().ok_or_else(|| "No lab data folder is set (PYTHIA_DATA).".to_string())?;
    kill_in(&root, chrono::Utc::now().timestamp_millis())
}

#[cfg(test)]
#[path = "pumpfun_live_tests.rs"]
mod tests;
