//! The on-chain wallet on the Real money page: what the lab's locked real-money
//! Solana trader reports, the owner's conversions between the allowed coins,
//! and the kill switch.
//!
//! The trader (the lab's on-chain live service, armed by the owner by hand,
//! docs/ONCHAIN-STAGE2.md) writes under `<data>/reports/onchain_live/`:
//!
//! - `status.json`: on or off and every reason why not, the wallet's public
//!   address, its balances in USD, today's figures, the confirmation file, the
//!   hard caps, the effective limits, the allowed coins, the stops;
//! - `trades.json`: the newest swaps and conversions;
//! - `convert/<id>.proposal.json` and `convert/<id>.result.json`: its quote for a
//!   conversion the owner asked for, and what became of it.
//!
//! The wallet tool writes `wallet.json` (the public address only), so the page
//! can show where to send SOL before the trader ever ran. Nothing here reads a
//! key, signs, sends or moves money; there is no withdraw or transfer anywhere
//! in Pythia.
//!
//! Three writes, none of which can move money by itself:
//!
//! - `convert/<id>.request.json`: the owner asks for a quote. The trader answers
//!   with a proposal (or refuses), checked again by its own guard.
//! - `convert/<id>.confirm.json`: the owner accepts that proposal, only while it
//!   is fresh. It names the proposal and its minimum out, so the trader can only
//!   carry out exactly what was shown.
//! - `KILL`: the kill switch. Nothing here deletes it: allowing trades again
//!   means deleting the file on the server by hand.

use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};

use crate::labview::data_dir;
use crate::pumpfun_live::{is_address, KillState, SolEur};

/// The trader writes its status every 30 s; older than this, it is not running.
pub const STALE_MS: i64 = 120_000;
/// The page shows this many trades and conversions.
pub const MAX_TRADES: usize = 100;
pub const MAX_CONVERTS: usize = 20;
/// Requests without a result at once; more are refused until the trader answers.
pub const MAX_OPEN_REQUESTS: usize = 3;

fn dir_in(root: &Path) -> PathBuf {
    root.join("reports").join("onchain_live")
}

fn convert_dir_in(root: &Path) -> PathBuf {
    dir_in(root).join("convert")
}

/// The file whose presence stops the trader.
pub fn kill_path_in(root: &Path) -> PathBuf {
    dir_in(root).join("KILL")
}

fn read<T: for<'de> Deserialize<'de>>(p: &Path) -> Option<T> {
    serde_json::from_str(&std::fs::read_to_string(p).ok()?).ok()
}

// ── what the trader writes (snake_case on disk, camelCase to the app) ──

#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq)]
#[serde(default, rename_all(serialize = "camelCase", deserialize = "snake_case"))]
pub struct Balance {
    pub coin: String,
    pub symbol: Option<String>,
    pub mint: Option<String>,
    pub amount: Option<f64>,
    pub usd: Option<f64>,
    pub price_usd: Option<f64>,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq)]
#[serde(default, rename_all(serialize = "camelCase", deserialize = "snake_case"))]
pub struct Day {
    pub start_usd: Option<f64>,
    pub pnl_usd: Option<f64>,
    pub swaps: Option<u32>,
    pub converts: Option<u32>,
    pub convert_usd: Option<f64>,
}

/// The owner's confirmation file as the trader read it; every field may be missing.
#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq)]
#[serde(default, rename_all(serialize = "camelCase", deserialize = "snake_case"))]
pub struct Ack {
    pub mode: Option<String>,
    pub books: Option<Vec<String>>,
    pub mints: Option<Vec<String>>,
    pub book_usd: Option<f64>,
    pub max_total_usd: Option<f64>,
    pub max_trade_usd: Option<f64>,
    pub max_daily_loss_usd: Option<f64>,
    pub max_convert_usd: Option<f64>,
    pub expires: Option<String>,
    pub on_kill: Option<String>,
}

/// The caps in the trader's code.
#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq)]
#[serde(default, rename_all(serialize = "camelCase", deserialize = "snake_case"))]
pub struct Hard {
    pub max_total_usd: Option<f64>,
    pub max_trade_usd: Option<f64>,
    pub max_daily_loss_usd: Option<f64>,
    pub max_convert_usd: Option<f64>,
    pub reserve_sol: Option<f64>,
    pub max_converts: Option<u32>,
    pub confirm_s: Option<f64>,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq)]
#[serde(default, rename_all(serialize = "camelCase", deserialize = "snake_case"))]
pub struct Limits {
    pub max_total_usd: Option<f64>,
    pub max_trade_usd: Option<f64>,
    pub max_daily_loss_usd: Option<f64>,
    pub max_convert_usd: Option<f64>,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq)]
#[serde(default, rename_all(serialize = "camelCase", deserialize = "snake_case"))]
pub struct Coin {
    pub coin: String,
    pub symbol: Option<String>,
    pub mint: Option<String>,
    pub decimals: Option<u32>,
    pub allowed: bool,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq)]
#[serde(default, rename_all(serialize = "camelCase", deserialize = "snake_case"))]
pub struct Simulation {
    pub t: Option<i64>,
    pub ok: Option<bool>,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq)]
#[serde(default, rename_all(serialize = "camelCase", deserialize = "snake_case"))]
pub struct BookState {
    pub book: String,
    pub allowed: bool,
    pub why: Option<String>,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq)]
#[serde(default, rename_all(serialize = "camelCase", deserialize = "snake_case"))]
pub struct Reconcile {
    pub t: Option<i64>,
    pub ok: Option<bool>,
    pub diffs: Vec<String>,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq)]
#[serde(default, rename_all(serialize = "camelCase", deserialize = "snake_case"))]
pub struct Stops {
    pub daily: bool,
    pub total: bool,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq)]
#[serde(default, rename_all(serialize = "camelCase", deserialize = "snake_case"))]
pub struct Status {
    pub t: i64,
    pub running: bool,
    pub on: bool,
    pub mode: Option<String>,
    /// Every reason the trader does not trade (empty when it may).
    pub gate: Vec<String>,
    pub address: Option<String>,
    pub sol_lamports: Option<u64>,
    pub balances: Vec<Balance>,
    pub total_usd: Option<f64>,
    pub day: Option<Day>,
    pub ack: Option<Ack>,
    pub hard: Option<Hard>,
    pub limits: Option<Limits>,
    pub coins: Vec<Coin>,
    pub kill: bool,
    pub simulate: Option<Simulation>,
    pub books: Vec<BookState>,
    pub reconcile: Option<Reconcile>,
    pub stops: Stops,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq)]
#[serde(default, rename_all(serialize = "camelCase", deserialize = "snake_case"))]
pub struct Trade {
    pub t: Option<f64>,
    /// "convert" or "book".
    pub kind: Option<String>,
    pub book: Option<String>,
    pub from: Option<String>,
    pub to: Option<String>,
    pub in_amount: Option<f64>,
    pub out_amount: Option<f64>,
    pub in_usd: Option<f64>,
    pub out_usd: Option<f64>,
    pub fee_sol: Option<f64>,
    pub sig: Option<String>,
    /// "filled" or "failed".
    pub status: Option<String>,
    pub why: Option<String>,
}

/// Each trade is read on its own, so one odd line does not hide the others.
#[derive(Debug, Clone, Default, Deserialize)]
#[serde(default)]
struct TradesFile {
    trades: Vec<serde_json::Value>,
}

#[derive(Debug, Clone, Default, Deserialize)]
#[serde(default)]
struct WalletFile {
    address: Option<String>,
}

// ── the conversion files (convert/<id>.<part>.json) ──

/// What the app writes to ask for a quote.
#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq)]
#[serde(default)]
struct Request {
    id: String,
    from: String,
    to: String,
    amount: f64,
    t: i64,
}

/// The trader's quote, or its refusal.
#[derive(Debug, Clone, Default, Deserialize, PartialEq)]
#[serde(default)]
struct Proposal {
    id: String,
    from: Option<String>,
    to: Option<String>,
    amount: Option<f64>,
    expected_out: Option<f64>,
    min_out: Option<f64>,
    /// Passed back in the confirm exactly as written.
    min_out_raw: Option<serde_json::Value>,
    cost_bps: Option<f64>,
    in_usd: Option<f64>,
    route: Vec<String>,
    t: Option<i64>,
    expires_ms: Option<i64>,
    /// "proposed" or "refused".
    status: Option<String>,
    why: Option<String>,
}

/// What the app writes to accept a proposal.
#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq)]
#[serde(default)]
struct Confirm {
    id: String,
    proposal_t: i64,
    min_out_raw: serde_json::Value,
    t: i64,
}

#[derive(Debug, Clone, Default, Deserialize, PartialEq)]
#[serde(default)]
struct Outcome {
    id: String,
    /// "filled", "failed", "refused" or "expired".
    status: Option<String>,
    why: Option<String>,
    sig: Option<String>,
    out_amount: Option<f64>,
    t: Option<i64>,
}

#[derive(Debug, Clone, Default)]
struct Parts {
    request: Option<Request>,
    proposal: Option<Proposal>,
    confirm: Option<Confirm>,
    result: Option<Outcome>,
}

/// One conversion as the page shows it: request, proposal, confirm and result in one.
#[derive(Debug, Clone, Default, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct Convert {
    pub id: String,
    /// waiting, proposed, refused, confirmed, filled, failed or expired.
    pub state: String,
    pub from: Option<String>,
    pub to: Option<String>,
    pub amount: Option<f64>,
    pub requested_ms: Option<i64>,
    pub expected_out: Option<f64>,
    pub min_out: Option<f64>,
    pub cost_bps: Option<f64>,
    pub in_usd: Option<f64>,
    pub route: Vec<String>,
    pub proposed_ms: Option<i64>,
    pub expires_ms: Option<i64>,
    pub confirmed_ms: Option<i64>,
    pub done_ms: Option<i64>,
    pub sig: Option<String>,
    pub out_amount: Option<f64>,
    pub why: Option<String>,
}

/// A conversion id as the app makes it: `c`, 13 digits of ms, `-`, 4 lowercase hex.
/// Anything else (a path, a dot, another length) is not a conversion.
pub fn is_id(id: &str) -> bool {
    let b = id.as_bytes();
    b.len() == 19
        && b[0] == b'c'
        && b[1..14].iter().all(u8::is_ascii_digit)
        && b[14] == b'-'
        && b[15..].iter().all(|&c| matches!(c, b'0'..=b'9' | b'a'..=b'f'))
}

/// Every conversion's files, by id. Files with another name are passed over.
fn parts_in(root: &Path) -> BTreeMap<String, Parts> {
    let mut m: BTreeMap<String, Parts> = BTreeMap::new();
    let Ok(rd) = std::fs::read_dir(convert_dir_in(root)) else { return m };
    for e in rd.flatten() {
        let name = e.file_name().to_string_lossy().into_owned();
        let Some((id, part)) = name.strip_suffix(".json").and_then(|s| s.split_once('.')) else { continue };
        if !is_id(id) || !matches!(part, "request" | "proposal" | "confirm" | "result") {
            continue;
        }
        let p = e.path();
        let slot = m.entry(id.to_string()).or_default();
        // A file whose own id is another one's is passed over.
        match part {
            "request" => slot.request = read::<Request>(&p).filter(|r| r.id == id),
            "proposal" => slot.proposal = read::<Proposal>(&p).filter(|r| r.id == id),
            "confirm" => slot.confirm = read::<Confirm>(&p).filter(|r| r.id == id),
            _ => slot.result = read::<Outcome>(&p).filter(|r| r.id == id),
        }
    }
    m
}

fn merge(id: String, p: Parts, now_ms: i64) -> Convert {
    let state = if let Some(r) = &p.result {
        match r.status.as_deref() {
            Some("filled") => "filled",
            Some("refused") => "refused",
            Some("expired") => "expired",
            _ => "failed",
        }
    } else if p.confirm.is_some() {
        "confirmed"
    } else if let Some(q) = &p.proposal {
        match q.status.as_deref() {
            Some("proposed") if q.expires_ms.is_some_and(|e| now_ms < e) => "proposed",
            Some("proposed") => "expired",
            _ => "refused",
        }
    } else {
        "waiting"
    };
    let (rq, pr, cf, rs) = (p.request.as_ref(), p.proposal.as_ref(), p.confirm.as_ref(), p.result.as_ref());
    Convert {
        state: state.into(),
        from: rq.map(|r| r.from.clone()).or_else(|| pr.and_then(|q| q.from.clone())),
        to: rq.map(|r| r.to.clone()).or_else(|| pr.and_then(|q| q.to.clone())),
        amount: rq.map(|r| r.amount).or_else(|| pr.and_then(|q| q.amount)),
        requested_ms: rq.map(|r| r.t),
        expected_out: pr.and_then(|q| q.expected_out),
        min_out: pr.and_then(|q| q.min_out),
        cost_bps: pr.and_then(|q| q.cost_bps),
        in_usd: pr.and_then(|q| q.in_usd),
        route: pr.map(|q| q.route.clone()).unwrap_or_default(),
        proposed_ms: pr.and_then(|q| q.t),
        expires_ms: pr.and_then(|q| q.expires_ms),
        confirmed_ms: cf.map(|c| c.t),
        done_ms: rs.and_then(|r| r.t),
        sig: rs.and_then(|r| r.sig.clone()),
        out_amount: rs.and_then(|r| r.out_amount),
        why: rs.and_then(|r| r.why.clone()).or_else(|| pr.and_then(|q| q.why.clone())),
        id,
    }
}

/// The newest conversions (the id starts with the ms of the request), merged.
pub fn converts_in(root: &Path, now_ms: i64) -> Vec<Convert> {
    parts_in(root)
        .into_iter()
        .rev()
        .filter(|(_, p)| p.request.is_some() || p.proposal.is_some() || p.confirm.is_some() || p.result.is_some())
        .take(MAX_CONVERTS)
        .map(|(id, p)| merge(id, p, now_ms))
        .collect()
}

/// Everything the section shows, in one answer.
#[derive(Debug, Clone, Default, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct OnchainView {
    /// The trader wrote its status within `STALE_MS` and did not say it stopped.
    pub running: bool,
    pub status: Option<Status>,
    /// The wallet's public address: from the trader, else from the wallet tool's file.
    pub address: Option<String>,
    /// Newest first, at most `MAX_TRADES`.
    pub trades: Vec<Trade>,
    /// Newest first, at most `MAX_CONVERTS`.
    pub converts: Vec<Convert>,
    /// The app's kill file is there (only deleting it on the server allows trades again).
    pub kill_file: bool,
    pub now_ms: i64,
    /// One euro in US dollars (Kraken's EURUSD), filled in by the server; none when it could not be read.
    pub eur_usd: Option<SolEur>,
}

fn fresh(s: &Status, now_ms: i64) -> bool {
    s.running && (now_ms - s.t).abs() <= STALE_MS
}

/// What the section shows, read from `root` (the lab's data folder).
pub fn view_in(root: &Path, now_ms: i64) -> OnchainView {
    let d = dir_in(root);
    let status: Option<Status> = read(&d.join("status.json"));
    let running = status.as_ref().is_some_and(|s| fresh(s, now_ms));
    let address = status
        .as_ref()
        .and_then(|s| s.address.clone())
        .or_else(|| read::<WalletFile>(&d.join("wallet.json")).and_then(|w| w.address))
        .filter(|a| is_address(a));
    let mut trades: Vec<Trade> = read::<TradesFile>(&d.join("trades.json"))
        .map(|f| f.trades.into_iter().filter_map(|v| serde_json::from_value(v).ok()).collect())
        .unwrap_or_default();
    trades.sort_by(|a, b| b.t.unwrap_or(0.0).total_cmp(&a.t.unwrap_or(0.0)));
    trades.truncate(MAX_TRADES);
    OnchainView {
        running,
        status,
        address,
        trades,
        converts: converts_in(root, now_ms),
        kill_file: kill_path_in(root).exists(),
        now_ms,
        eur_usd: None,
    }
}

/// The view from the lab's data folder (`PYTHIA_DATA`), or an empty one without it.
pub fn view() -> OnchainView {
    let now = chrono::Utc::now().timestamp_millis();
    match data_dir() {
        Some(root) => view_in(&root, now),
        None => OnchainView { now_ms: now, ..OnchainView::default() },
    }
}

// ── the owner's conversions ──

/// What the app posts to ask for a quote: `amount` in units of `from`.
#[derive(Debug, Clone, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ConvertAsk {
    pub from: String,
    pub to: String,
    pub amount: f64,
}

/// What the app posts to accept a proposal.
#[derive(Debug, Clone, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ConfirmAsk {
    pub id: String,
}

/// Temp file, then rename: the trader never reads half a file.
fn write_atomic(p: &Path, body: &[u8]) -> std::io::Result<()> {
    let dir = p.parent().ok_or_else(|| std::io::Error::other("no folder"))?;
    std::fs::create_dir_all(dir)?;
    let tmp = p.with_extension("json.tmp");
    std::fs::write(&tmp, body)?;
    std::fs::rename(&tmp, p)
}

fn new_id(now_ms: i64) -> String {
    let hex = uuid::Uuid::new_v4().simple().to_string();
    format!("c{now_ms:013}-{}", &hex[..4])
}

/// Ask the trader for a quote: writes `convert/<id>.request.json` and returns the id.
/// Refused unless the trader runs, both coins are allowed and differ, the amount is
/// positive, no kill file is set and fewer than `MAX_OPEN_REQUESTS` wait for a result.
pub fn convert_in(root: &Path, from: &str, to: &str, amount: f64, now_ms: i64) -> Result<String, String> {
    let s = read::<Status>(&dir_in(root).join("status.json"))
        .ok_or_else(|| "The on-chain trader is not running (no status yet): conversions need it running.".to_string())?;
    if !fresh(&s, now_ms) {
        return Err("The on-chain trader is not running (its status is old or says stopped): conversions need it running.".into());
    }
    if s.kill || kill_path_in(root).exists() {
        return Err("The kill switch is on: no conversions until the kill file is deleted on the server.".into());
    }
    if from == to {
        return Err("From and to must be different coins.".into());
    }
    let allowed = |c: &str| s.coins.iter().any(|x| x.coin == c && x.allowed);
    for c in [from, to] {
        if !allowed(c) {
            let shown: String = c.chars().take(16).collect();
            return Err(format!("{shown} is not a coin the trader may convert."));
        }
    }
    if !amount.is_finite() || amount <= 0.0 {
        return Err("The amount must be a positive number.".into());
    }
    let open = parts_in(root).values().filter(|p| p.request.is_some() && p.result.is_none()).count();
    if open >= MAX_OPEN_REQUESTS {
        return Err(format!("{open} conversions are still waiting for the trader; wait for them first."));
    }
    let dir = convert_dir_in(root);
    let id = (0..16)
        .map(|_| new_id(now_ms))
        .find(|id| is_id(id) && !dir.join(format!("{id}.request.json")).exists())
        .ok_or_else(|| "No free id for the request; try again.".to_string())?;
    let req = Request { id: id.clone(), from: from.into(), to: to.into(), amount, t: now_ms };
    let body = serde_json::to_vec_pretty(&req).map_err(|e| e.to_string())?;
    write_atomic(&dir.join(format!("{id}.request.json")), &body).map_err(|e| format!("The request could not be written: {e}"))?;
    Ok(id)
}

/// Accept the trader's proposal `id`: writes `convert/<id>.confirm.json` with the
/// proposal's time and minimum out. Only while it is proposed, not expired, and
/// neither confirmed nor answered yet.
pub fn confirm_in(root: &Path, id: &str, now_ms: i64) -> Result<(), String> {
    if !is_id(id) {
        return Err("Not a conversion id.".into());
    }
    if kill_path_in(root).exists() {
        return Err("The kill switch is on: no conversions until the kill file is deleted on the server.".into());
    }
    let dir = convert_dir_in(root);
    let q: Proposal = read::<Proposal>(&dir.join(format!("{id}.proposal.json")))
        .filter(|q| q.id == id)
        .ok_or_else(|| "There is no proposal for this conversion yet.".to_string())?;
    if q.status.as_deref() != Some("proposed") {
        return Err(format!("The trader refused this conversion{}.", q.why.map(|w| format!(": {w}")).unwrap_or_default()));
    }
    if !q.expires_ms.is_some_and(|e| now_ms < e) {
        return Err("The proposal has expired; ask for a new quote.".into());
    }
    if dir.join(format!("{id}.confirm.json")).exists() {
        return Err("This conversion is already confirmed.".into());
    }
    if dir.join(format!("{id}.result.json")).exists() {
        return Err("This conversion already has a result.".into());
    }
    let (Some(proposal_t), Some(min_out_raw)) = (q.t, q.min_out_raw) else {
        return Err("The proposal is incomplete (no time or minimum out); ask for a new quote.".into());
    };
    let c = Confirm { id: id.into(), proposal_t, min_out_raw, t: now_ms };
    let body = serde_json::to_vec_pretty(&c).map_err(|e| e.to_string())?;
    write_atomic(&dir.join(format!("{id}.confirm.json")), &body).map_err(|e| format!("The confirmation could not be written: {e}"))
}

// ── the kill switch ──

/// Create the kill file under `root` (kept as it is when it is already there).
/// There is no way back through the API: delete the file on the server.
pub fn kill_in(root: &Path, now_ms: i64) -> Result<KillState, String> {
    let p = kill_path_in(root);
    let already = p.exists();
    if !already {
        let when = chrono::DateTime::from_timestamp_millis(now_ms).map(|t| t.to_rfc3339()).unwrap_or_default();
        let text = format!(
            "Kill switch set from the app at {when}.\nThe on-chain trader makes no swap and no conversion while this file exists.\nDelete it on the server to allow trades again (docs/ONCHAIN-STAGE2.md).\n"
        );
        std::fs::create_dir_all(p.parent().expect("kill path has a folder"))
            .and_then(|_| std::fs::write(&p, text))
            .map_err(|e| format!("The kill file could not be written: {e}"))?;
    }
    Ok(KillState { kill_file: true, path: "reports/onchain_live/KILL".into(), already })
}

#[cfg(test)]
#[path = "onchain_live_tests.rs"]
mod tests;
