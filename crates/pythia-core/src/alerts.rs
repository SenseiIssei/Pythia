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
        }
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
}

impl AlertFormat {
    pub fn parse(s: &str) -> Option<Self> {
        match s.trim().to_ascii_lowercase().as_str() {
            "discord" | "content" => Some(AlertFormat::Discord),
            "slack" | "text" => Some(AlertFormat::Slack),
            _ => None,
        }
    }
    /// Discord caps a message at 2000 characters; Slack takes far more, but a
    /// phone notification is no place for a wall of text either.
    fn limit(self) -> usize {
        match self {
            AlertFormat::Discord => 1900,
            AlertFormat::Slack => 3000,
        }
    }
    pub fn body(self, content: &str) -> serde_json::Value {
        let c = truncate(content, self.limit());
        match self {
            AlertFormat::Discord => serde_json::json!({ "content": c }),
            AlertFormat::Slack => serde_json::json!({ "text": c }),
        }
    }
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
        }
    }

    /// `PYTHIA_ALERT_WEBHOOK` (required, else `None`), `PYTHIA_ALERT_FORMAT`
    /// (`discord`, the default, or `slack`), `PYTHIA_ALERT_DEDUP_MIN` (30),
    /// `PYTHIA_ALERT_MAX_PER_HOUR` (20), `PYTHIA_ALERT_PREFIX` (`Pythia`).
    pub fn from_env() -> Option<Self> {
        Self::from_lookup(|k| std::env::var(k).ok())
    }

    pub fn from_lookup(get: impl Fn(&str) -> Option<String>) -> Option<Self> {
        let url = get("PYTHIA_ALERT_WEBHOOK").map(|u| u.trim().to_string()).filter(|u| !u.is_empty())?;
        let format = match get("PYTHIA_ALERT_FORMAT").filter(|s| !s.trim().is_empty()) {
            None => AlertFormat::Discord,
            Some(s) => match AlertFormat::parse(&s) {
                Some(f) => f,
                None => {
                    tracing::warn!("PYTHIA_ALERT_FORMAT={s} is not discord or slack; using discord");
                    AlertFormat::Discord
                }
            },
        };
        let mut c = Self::new(url, format);
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
        Some(c)
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

/// The engine's handle on the sender. Cloning is cheap; sending never waits.
#[derive(Clone)]
pub struct AlertSink {
    tx: mpsc::Sender<AlertEvent>,
    full_logged: std::sync::Arc<std::sync::atomic::AtomicBool>,
}

impl AlertSink {
    /// Start the sender on the current tokio runtime.
    pub fn spawn(cfg: AlertConfig) -> Self {
        let (tx, rx) = mpsc::channel(cfg.queue.max(1));
        tokio::spawn(run(cfg, rx));
        Self { tx, full_logged: Default::default() }
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

async fn run(cfg: AlertConfig, mut rx: mpsc::Receiver<AlertEvent>) {
    let client = reqwest::Client::builder().timeout(cfg.timeout).build().unwrap_or_default();
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
        let fresh: Vec<AlertEvent> = batch.into_iter().filter(|e| throttle.fresh(&e.key, now)).collect();
        if fresh.is_empty() {
            continue;
        }
        if !throttle.may_post(now) {
            throttle.suppressed += fresh.len();
            continue;
        }
        let content = compose(&cfg, &fresh, throttle.suppressed);
        throttle.suppressed = 0;
        match deliver(&client, &cfg, &content).await {
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

/// The text of one post.
pub fn compose(cfg: &AlertConfig, events: &[AlertEvent], suppressed: usize) -> String {
    let mut lines: Vec<String> = Vec::new();
    if !cfg.prefix.is_empty() {
        lines.push(match cfg.format {
            AlertFormat::Discord => format!("**{}**", cfg.prefix),
            AlertFormat::Slack => format!("*{}*", cfg.prefix),
        });
    }
    lines.extend(events.iter().map(|e| e.line(cfg.format)));
    if suppressed > 0 {
        lines.push(format!("({suppressed} more alert(s) held back by the hourly limit; see the journal)"));
    }
    lines.join("\n")
}

/// One POST. The error never carries the URL.
async fn deliver(client: &reqwest::Client, cfg: &AlertConfig, content: &str) -> Result<(), String> {
    let resp = client
        .post(&cfg.url)
        .json(&cfg.format.body(content))
        .send()
        .await
        .map_err(|e| e.without_url().to_string())?;
    let status = resp.status();
    if status.is_success() {
        Ok(())
    } else {
        Err(format!("HTTP {}", status.as_u16()))
    }
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
