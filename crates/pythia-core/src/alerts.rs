//! Webhook alerts.
//!
//! Two paths share this module:
//!
//! - [`post`]: the older free-text push of the engine's notable events (fills,
//!   exits, risk actions) to `PYTHIA_WEBHOOK_URL` or the desktop app's vault
//!   entry. Best-effort and time-boxed.
//! - [`AlertSink`]: typed operator alerts ([`AlertKind`]) to
//!   `PYTHIA_ALERT_WEBHOOK`, for the events an owner wants on the phone without
//!   opening the app: an autopilot started, stopped, hit a stop rule or its
//!   floor, the kill switch, the daily loss brake, demo or live orders refused
//!   again and again, a venue reconcile mismatch, market data stale for more
//!   than ten minutes, a model muted by drift. The engine only queues them
//!   ([`AlertEvent`]); a background task delivers them, so a slow or dead
//!   webhook never holds up a tick. The queue is bounded, repeats of the same
//!   event are dropped inside a window, the number of posts per hour is capped,
//!   and a failing webhook is logged once until it works again. The URL is a
//!   secret: it is read from the environment and never logged.
//!
//! Native-only: a browser cannot POST cross-origin to Discord.

use std::collections::{HashMap, VecDeque};
use std::time::Duration;

use serde::Serialize;
use tokio::sync::mpsc;

/// Char-safe truncation to keep within Discord's 2000-char content limit.
fn truncate(s: &str, max: usize) -> String {
    if s.chars().count() <= max {
        s.to_string()
    } else {
        let head: String = s.chars().take(max).collect();
        format!("{head}…")
    }
}

/// POST a message to the webhook. Best-effort, time-boxed, never panics.
pub async fn post(webhook: &str, content: &str) {
    if webhook.is_empty() || content.is_empty() {
        return;
    }
    let body = serde_json::json!({ "content": truncate(content, 1900) });
    let _ = tokio::time::timeout(Duration::from_secs(5), async {
        reqwest::Client::new().post(webhook).json(&body).send().await
    })
    .await;
}

// ── typed operator alerts ────────────────────────────────────────────────────

/// What an operator alert is about.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize)]
#[serde(rename_all = "camelCase")]
pub enum AlertKind {
    AutopilotStarted,
    /// Stopped by the operator, finished at its end time or take profit.
    AutopilotStopped,
    /// A stop rule other than the equity floor (take profit, end time).
    StopRuleHit,
    /// The equity floor: max loss, trailing or locked-in profit floor.
    FloorHit,
    KillSwitch,
    DailyLossBrake,
    OrderRejects,
    ReconcileMismatch,
    DataStale,
    ModelDrift,
    /// A test message asked for by the operator (`POST /api/alerts/test`).
    Test,
}

impl AlertKind {
    pub fn label(self) -> &'static str {
        match self {
            AlertKind::AutopilotStarted => "Autopilot started",
            AlertKind::AutopilotStopped => "Autopilot stopped",
            AlertKind::StopRuleHit => "Stop rule hit",
            AlertKind::FloorHit => "Floor hit",
            AlertKind::KillSwitch => "Kill switch",
            AlertKind::DailyLossBrake => "Daily loss brake",
            AlertKind::OrderRejects => "Orders refused",
            AlertKind::ReconcileMismatch => "Reconcile mismatch",
            AlertKind::DataStale => "Market data stale",
            AlertKind::ModelDrift => "Model drift",
            AlertKind::Test => "Test",
        }
    }

    /// Sent even while alerts are muted: the money stopped trading.
    pub fn bypasses_mute(self) -> bool {
        matches!(self, AlertKind::KillSwitch | AlertKind::FloorHit)
    }
}

/// One operator alert. `key` identifies the condition for deduplication:
/// two events with the same key inside the dedup window send once.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct AlertEvent {
    pub kind: AlertKind,
    pub key: String,
    pub text: String,
}

impl AlertEvent {
    pub fn new(kind: AlertKind, key: impl Into<String>, text: impl Into<String>) -> Self {
        Self { kind, key: key.into(), text: text.into() }
    }
    /// The line as posted: `**Kill switch** text` on Discord, `*Kill switch* text` on Slack.
    pub fn line(&self, format: AlertFormat) -> String {
        match format {
            AlertFormat::Discord => format!("**{}** {}", self.kind.label(), self.text),
            AlertFormat::Slack => format!("*{}* {}", self.kind.label(), self.text),
            AlertFormat::Telegram => format!("{}: {}", self.kind.label(), self.text),
        }
    }
}

/// The JSON shape the webhook takes.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum AlertFormat {
    /// `{"content": "..."}`
    Discord,
    /// `{"text": "..."}`
    Slack,
    /// Telegram's `sendMessage`: `{"chat_id": "...", "text": "..."}`, plain
    /// text so nothing in a message has to be escaped.
    Telegram,
}

impl AlertFormat {
    /// The destination's name as the API reports it.
    pub fn name(self) -> &'static str {
        match self {
            AlertFormat::Discord => "discord",
            AlertFormat::Slack => "slack",
            AlertFormat::Telegram => "telegram",
        }
    }

    pub fn parse(s: &str) -> Option<Self> {
        match s.trim().to_ascii_lowercase().as_str() {
            "discord" | "content" => Some(AlertFormat::Discord),
            "slack" | "text" => Some(AlertFormat::Slack),
            "telegram" => Some(AlertFormat::Telegram),
            _ => None,
        }
    }
    /// Discord caps a message at 2000 characters, Telegram at 4096; Slack takes
    /// far more, but a phone notification is no place for a wall of text either.
    fn limit(self) -> usize {
        match self {
            AlertFormat::Discord => 1900,
            AlertFormat::Slack => 3000,
            AlertFormat::Telegram => 3900,
        }
    }
    pub fn body(self, content: &str) -> serde_json::Value {
        let c = truncate(content, self.limit());
        match self {
            AlertFormat::Discord => serde_json::json!({ "content": c }),
            AlertFormat::Slack | AlertFormat::Telegram => serde_json::json!({ "text": c }),
        }
    }
}

/// The Telegram Bot API endpoint that sends a message with this bot token.
pub fn telegram_url(token: &str) -> String {
    format!("https://api.telegram.org/bot{}/sendMessage", token.trim())
}

/// How the sender behaves. All of it can be set from the environment, see
/// [`AlertConfig::from_env`].
#[derive(Clone)]
pub struct AlertConfig {
    pub url: String,
    pub format: AlertFormat,
    /// The same key is sent at most once per this window.
    pub dedup: Duration,
    /// At most this many posts per rolling hour; the rest are counted and the
    /// count rides on the next post that goes out.
    pub max_per_hour: usize,
    /// Events arriving within this time of each other go out as one post.
    pub batch_wait: Duration,
    /// Bounded queue between the engine and the sender.
    pub queue: usize,
    pub timeout: Duration,
    /// Prefix of every post, so one channel can serve several engines.
    pub prefix: String,
    /// Telegram only: the chat the bot writes to.
    pub chat_id: Option<String>,
}

impl std::fmt::Debug for AlertConfig {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        // The URL is a secret and stays out of every log line.
        f.debug_struct("AlertConfig")
            .field("url", &"<set>")
            .field("format", &self.format)
            .field("dedup", &self.dedup)
            .field("max_per_hour", &self.max_per_hour)
            .field("prefix", &self.prefix)
            .finish()
    }
}

impl AlertConfig {
    pub fn new(url: impl Into<String>, format: AlertFormat) -> Self {
        Self {
            url: url.into(),
            format,
            dedup: Duration::from_secs(30 * 60),
            max_per_hour: 20,
            batch_wait: Duration::from_secs(2),
            queue: 64,
            timeout: Duration::from_secs(10),
            prefix: "Pythia".into(),
            chat_id: None,
        }
    }

    /// `PYTHIA_ALERT_WEBHOOK` (required, else `None`), `PYTHIA_ALERT_FORMAT`
    /// (`discord`, the default, or `slack`), `PYTHIA_ALERT_DEDUP_MIN` (30),
    /// `PYTHIA_ALERT_MAX_PER_HOUR` (20), `PYTHIA_ALERT_PREFIX` (`Pythia`).
    /// Telegram instead: `PYTHIA_TELEGRAM_BOT_TOKEN` and
    /// `PYTHIA_TELEGRAM_CHAT_ID` (both required, used when no webhook is set).
    pub fn from_env() -> Option<Self> {
        Self::from_lookup(|k| std::env::var(k).ok())
    }

    /// The JSON this config posts for one message.
    pub fn body(&self, content: &str) -> serde_json::Value {
        let mut b = self.format.body(content);
        if let (AlertFormat::Telegram, Some(chat)) = (self.format, &self.chat_id) {
            b["chat_id"] = serde_json::json!(chat);
        }
        b
    }

    pub fn from_lookup(get: impl Fn(&str) -> Option<String>) -> Option<Self> {
        let nonempty = |k: &str| get(k).map(|v| v.trim().to_string()).filter(|v| !v.is_empty());
        let url = match nonempty("PYTHIA_ALERT_WEBHOOK") {
            Some(u) => u,
            None => {
                let token = nonempty("PYTHIA_TELEGRAM_BOT_TOKEN")?;
                let chat = nonempty("PYTHIA_TELEGRAM_CHAT_ID")?;
                let mut c = Self::new(telegram_url(&token), AlertFormat::Telegram);
                c.chat_id = Some(chat);
                return Some(c.tuned(&get));
            }
        };
        let format = match get("PYTHIA_ALERT_FORMAT").filter(|s| !s.trim().is_empty()) {
            None => AlertFormat::Discord,
            Some(s) => match AlertFormat::parse(&s) {
                Some(f) => f,
                None => {
                    tracing::warn!("PYTHIA_ALERT_FORMAT={s} is not discord, slack or telegram; using discord");
                    AlertFormat::Discord
                }
            },
        };
        let mut c = Self::new(url, format);
        if format == AlertFormat::Telegram {
            c.chat_id = nonempty("PYTHIA_TELEGRAM_CHAT_ID");
        }
        Some(c.tuned(&get))
    }

    /// The optional knobs shared by every destination.
    fn tuned(mut self, get: &impl Fn(&str) -> Option<String>) -> Self {
        let c = &mut self;
        let num = |k: &str| get(k).and_then(|v| v.trim().parse::<u64>().ok());
        if let Some(m) = num("PYTHIA_ALERT_DEDUP_MIN") {
            c.dedup = Duration::from_secs(m * 60);
        }
        if let Some(n) = num("PYTHIA_ALERT_MAX_PER_HOUR").filter(|n| *n > 0) {
            c.max_per_hour = n as usize;
        }
        if let Some(p) = get("PYTHIA_ALERT_PREFIX") {
            c.prefix = p.trim().to_string();
        }
        self
    }
}

/// Deduplication and the hourly cap, apart from the network so it can be
/// tested on its own. Times are milliseconds.
#[derive(Debug, Default)]
pub struct Throttle {
    dedup_ms: i64,
    max_per_hour: usize,
    seen: HashMap<String, i64>,
    sent: VecDeque<i64>,
    /// Events dropped by the hourly cap since the last post that went out.
    pub suppressed: usize,
}

impl Throttle {
    pub fn new(dedup: Duration, max_per_hour: usize) -> Self {
        Self { dedup_ms: dedup.as_millis() as i64, max_per_hour: max_per_hour.max(1), ..Default::default() }
    }

    /// Whether an event with this key is new, i.e. not seen inside the window.
    /// A new one is remembered.
    pub fn fresh(&mut self, key: &str, now: i64) -> bool {
        self.seen.retain(|_, at| now - *at < self.dedup_ms);
        if self.seen.contains_key(key) {
            return false;
        }
        self.seen.insert(key.to_string(), now);
        true
    }

    /// Whether a post may go out now. Counts it if so; otherwise the caller
    /// adds the events it holds to `suppressed`.
    pub fn may_post(&mut self, now: i64) -> bool {
        while self.sent.front().is_some_and(|&t| now - t >= 3_600_000) {
            self.sent.pop_front();
        }
        if self.sent.len() >= self.max_per_hour {
            return false;
        }
        self.sent.push_back(now);
        true
    }
}

// ── the record of what was posted ────────────────────────────────────────────

/// How many posts [`AlertLog`] keeps.
pub const RECENT_POSTS: usize = 100;
/// The longest mute the API accepts: seven days.
pub const MAX_MUTE_MINUTES: u64 = 7 * 24 * 60;

/// One post, or one batch of events held back, as the API reports it.
#[derive(Debug, Clone, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct AlertRecord {
    /// Epoch ms.
    pub ts: i64,
    pub kinds: Vec<AlertKind>,
    pub text: String,
    pub delivered: bool,
    /// Why a post failed (`HTTP 500`, a connection error). Never the URL or
    /// the token.
    pub error: Option<String>,
    /// Why nothing was posted: `muted` or `hourlyLimit`.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub reason: Option<String>,
}

/// Counts for the current UTC day.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct AlertCounts {
    /// Posts that went through.
    pub sent_today: u64,
    /// Posts the destination did not take.
    pub failed_today: u64,
    /// Events held back by the mute or the hourly limit.
    pub suppressed_today: u64,
}

/// What [`AlertLog::view`] returns.
#[derive(Debug, Clone, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct AlertLogView {
    /// 0 when not muted.
    pub muted_until_ms: i64,
    pub counts: AlertCounts,
    /// Newest first.
    pub recent: Vec<AlertRecord>,
}

#[derive(Debug, Default)]
struct LogInner {
    recent: VecDeque<AlertRecord>,
    counts: AlertCounts,
    day: i64,
    muted_until_ms: i64,
}

impl LogInner {
    fn roll(&mut self, now: i64) {
        let day = now.div_euclid(86_400_000);
        if day != self.day {
            self.day = day;
            self.counts = AlertCounts::default();
        }
    }
}

/// The last [`RECENT_POSTS`] posts, today's counts and the mute, shared by
/// the sender and the host's API. Cloning is cheap.
#[derive(Debug, Clone, Default)]
pub struct AlertLog(std::sync::Arc<std::sync::Mutex<LogInner>>);

impl AlertLog {
    fn inner(&self) -> std::sync::MutexGuard<'_, LogInner> {
        self.0.lock().unwrap_or_else(|p| p.into_inner())
    }

    /// Mute until this time (epoch ms; 0 or a past time unmutes).
    pub fn set_muted_until(&self, until_ms: i64) {
        self.inner().muted_until_ms = until_ms.max(0);
    }

    /// Until when alerts are muted, 0 when they are not (any more).
    pub fn muted_until(&self, now: i64) -> i64 {
        let m = self.inner().muted_until_ms;
        if m > now {
            m
        } else {
            0
        }
    }

    pub fn is_muted(&self, now: i64) -> bool {
        self.muted_until(now) > 0
    }

    /// Keep one record and count it: delivered as sent, with an error as
    /// failed, otherwise its events as suppressed.
    pub fn record(&self, rec: AlertRecord) {
        let mut g = self.inner();
        g.roll(rec.ts);
        if rec.delivered {
            g.counts.sent_today += 1;
        } else if rec.error.is_some() {
            g.counts.failed_today += 1;
        } else {
            g.counts.suppressed_today += rec.kinds.len().max(1) as u64;
        }
        g.recent.push_back(rec);
        while g.recent.len() > RECENT_POSTS {
            g.recent.pop_front();
        }
    }

    pub fn view(&self, now: i64) -> AlertLogView {
        let mut g = self.inner();
        g.roll(now);
        AlertLogView {
            muted_until_ms: if g.muted_until_ms > now { g.muted_until_ms } else { 0 },
            counts: g.counts,
            recent: g.recent.iter().rev().cloned().collect(),
        }
    }
}

/// The engine's handle on the sender. Cloning is cheap; sending never waits.
#[derive(Clone)]
pub struct AlertSink {
    tx: mpsc::Sender<AlertEvent>,
    full_logged: std::sync::Arc<std::sync::atomic::AtomicBool>,
    cfg: std::sync::Arc<AlertConfig>,
    client: reqwest::Client,
    log: AlertLog,
}

impl AlertSink {
    /// Start the sender on the current tokio runtime.
    pub fn spawn(cfg: AlertConfig) -> Self {
        Self::spawn_with_log(cfg, AlertLog::default())
    }

    /// Start the sender, recording every post (and the mute) in `log`.
    pub fn spawn_with_log(cfg: AlertConfig, log: AlertLog) -> Self {
        let (tx, rx) = mpsc::channel(cfg.queue.max(1));
        let client = reqwest::Client::builder().timeout(cfg.timeout).build().unwrap_or_default();
        let cfg = std::sync::Arc::new(cfg);
        tokio::spawn(run(cfg.clone(), client.clone(), log.clone(), rx));
        Self { tx, full_logged: Default::default(), cfg, client, log }
    }

    pub fn log(&self) -> &AlertLog {
        &self.log
    }

    /// Where the alerts go.
    pub fn format(&self) -> AlertFormat {
        self.cfg.format
    }

    /// Post one test message now, past the queue, the throttle and the mute
    /// (the operator asked for it), and record it.
    pub async fn test(&self) -> AlertRecord {
        let ev = AlertEvent::new(
            AlertKind::Test,
            "test",
            "test message from the engine: alerts reach this destination.",
        );
        let content = compose(&self.cfg, std::slice::from_ref(&ev), 0);
        let res = deliver(&self.client, &self.cfg, &content).await;
        let rec = AlertRecord {
            ts: now_ms(),
            kinds: vec![AlertKind::Test],
            text: content,
            delivered: res.is_ok(),
            error: res.err(),
            reason: None,
        };
        self.log.record(rec.clone());
        rec
    }

    /// Queue an alert. A full queue drops it (logged once until it drains):
    /// the engine is never held up by the webhook.
    pub fn send(&self, ev: AlertEvent) {
        use std::sync::atomic::Ordering;
        match self.tx.try_send(ev) {
            Ok(()) => self.full_logged.store(false, Ordering::Relaxed),
            Err(mpsc::error::TrySendError::Full(_)) => {
                if !self.full_logged.swap(true, Ordering::Relaxed) {
                    tracing::warn!("alert queue full: alerts are dropped until the webhook catches up");
                }
            }
            Err(mpsc::error::TrySendError::Closed(_)) => {}
        }
    }
}

fn now_ms() -> i64 {
    chrono::Utc::now().timestamp_millis()
}

async fn run(cfg: std::sync::Arc<AlertConfig>, client: reqwest::Client, log: AlertLog, mut rx: mpsc::Receiver<AlertEvent>) {
    let mut throttle = Throttle::new(cfg.dedup, cfg.max_per_hour);
    let mut failing = false;
    while let Some(first) = rx.recv().await {
        // Gather what arrives together into one post.
        let mut batch = vec![first];
        let until = tokio::time::Instant::now() + cfg.batch_wait;
        while batch.len() < 20 {
            match tokio::time::timeout_at(until, rx.recv()).await {
                Ok(Some(ev)) => batch.push(ev),
                _ => break,
            }
        }
        let now = now_ms();
        let mut fresh: Vec<AlertEvent> = batch.into_iter().filter(|e| throttle.fresh(&e.key, now)).collect();
        if log.is_muted(now) {
            // Muted: recorded, not sent. The kill switch and a floor hit still go out.
            let (urgent, held): (Vec<AlertEvent>, Vec<AlertEvent>) =
                fresh.into_iter().partition(|e| e.kind.bypasses_mute());
            if !held.is_empty() {
                log.record(held_back(&cfg, &held, now, "muted"));
            }
            fresh = urgent;
        }
        if fresh.is_empty() {
            continue;
        }
        if !throttle.may_post(now) {
            throttle.suppressed += fresh.len();
            log.record(held_back(&cfg, &fresh, now, "hourlyLimit"));
            continue;
        }
        let content = compose(&cfg, &fresh, throttle.suppressed);
        throttle.suppressed = 0;
        let res = deliver(&client, &cfg, &content).await;
        log.record(AlertRecord {
            ts: now,
            kinds: fresh.iter().map(|e| e.kind).collect(),
            text: content,
            delivered: res.is_ok(),
            error: res.clone().err(),
            reason: None,
        });
        match res {
            Ok(()) => {
                if failing {
                    tracing::info!("alert webhook works again");
                    failing = false;
                }
            }
            Err(why) => {
                if !failing {
                    tracing::warn!("alert webhook failed ({why}); further failures are not logged until it works again");
                    failing = true;
                }
            }
        }
    }
}

/// The record of events that were not posted, and why.
fn held_back(cfg: &AlertConfig, events: &[AlertEvent], now: i64, reason: &str) -> AlertRecord {
    AlertRecord {
        ts: now,
        kinds: events.iter().map(|e| e.kind).collect(),
        text: compose(cfg, events, 0),
        delivered: false,
        error: None,
        reason: Some(reason.into()),
    }
}

/// The text of one post.
pub fn compose(cfg: &AlertConfig, events: &[AlertEvent], suppressed: usize) -> String {
    let mut lines: Vec<String> = Vec::new();
    if !cfg.prefix.is_empty() {
        lines.push(match cfg.format {
            AlertFormat::Discord => format!("**{}**", cfg.prefix),
            AlertFormat::Slack => format!("*{}*", cfg.prefix),
            AlertFormat::Telegram => cfg.prefix.clone(),
        });
    }
    lines.extend(events.iter().map(|e| e.line(cfg.format)));
    if suppressed > 0 {
        lines.push(format!("({suppressed} more alert(s) held back by the hourly limit; see the journal)"));
    }
    lines.join("\n")
}

/// One POST. The error never carries the URL, the token or the chat.
async fn deliver(client: &reqwest::Client, cfg: &AlertConfig, content: &str) -> Result<(), String> {
    let resp = client
        .post(&cfg.url)
        .json(&cfg.body(content))
        .send()
        .await
        .map_err(|e| scrub(&e.without_url().to_string(), cfg))?;
    let status = resp.status();
    if status.is_success() {
        Ok(())
    } else {
        Err(format!("HTTP {}", status.as_u16()))
    }
}

/// An error message with every secret part of the destination taken out: the
/// URL, each longer piece of it (a webhook id, a bot token) and the chat id.
pub fn scrub(msg: &str, cfg: &AlertConfig) -> String {
    let mut secrets: Vec<&str> = vec![cfg.url.as_str()];
    let rest = cfg.url.split_once("://").map_or(cfg.url.as_str(), |(_, r)| r);
    secrets.extend(rest.split(['/', '?', '&', '=', '#']).filter(|p| p.len() >= 8));
    if let Some(chat) = cfg.chat_id.as_deref().filter(|c| c.len() >= 5) {
        secrets.push(chat);
    }
    secrets.sort_by_key(|s| std::cmp::Reverse(s.len()));
    let mut out = msg.to_string();
    for s in secrets.into_iter().filter(|s| !s.is_empty()) {
        out = out.replace(s, "<redacted>");
    }
    out
}

/// Watches the shadow models' input drift. A model with an input in the
/// `drift` level (more than 5 % of the last window outside the range it was
/// trained on) is muted: its forecasts are out of their depth and are not to be
/// trusted until the inputs are back in range or it is retrained. The alert
/// goes out when a model enters that state and once when it leaves it.
#[derive(Debug, Default)]
pub struct DriftWatch {
    muted: HashMap<&'static str, bool>,
}

impl DriftWatch {
    pub fn check(&mut self, status: &crate::ml::MlStatus) -> Vec<AlertEvent> {
        use pythia_ml::drift::DriftLevel;
        let vol: Vec<(String, f64)> = status
            .drift
            .iter()
            .filter(|d| d.level == DriftLevel::Drift)
            .map(|d| (d.feature.clone(), d.outside_pct))
            .collect();
        let picks: Vec<(String, f64)> = status
            .picks
            .drift
            .iter()
            .filter(|d| d.level == DriftLevel::Drift)
            .map(|d| (d.feature.clone(), d.outside_pct))
            .collect();
        let mut out = Vec::new();
        for (name, label, total, hits) in [
            ("vol", "volatility model", status.drift.len(), vol),
            ("picks", "M2 coin ranking", status.picks.drift.len(), picks),
        ] {
            let now = !hits.is_empty();
            let was = self.muted.insert(name, now).unwrap_or(false);
            if now && !was {
                let list: Vec<String> = hits.iter().take(4).map(|(f, p)| format!("{f} {p:.0} % outside")).collect();
                out.push(AlertEvent::new(
                    AlertKind::ModelDrift,
                    format!("drift:{name}:on"),
                    format!(
                        "{label} muted: {} of {total} inputs outside the trained range ({}). Its forecasts are not to be trusted until they are back in range or it is retrained.",
                        hits.len(),
                        list.join(", ")
                    ),
                ));
            } else if was && !now {
                out.push(AlertEvent::new(
                    AlertKind::ModelDrift,
                    format!("drift:{name}:off"),
                    format!("{label} inputs are back in the trained range."),
                ));
            }
        }
        out
    }
}

#[cfg(test)]
#[path = "alerts_tests.rs"]
mod tests;
