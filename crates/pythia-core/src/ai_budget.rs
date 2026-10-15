//! The hard budget for paid model calls.
//!
//! Every call to the Claude API goes through [`Budget::reserve`] before a byte
//! leaves the machine, and through [`Reservation::record`] once the answer is
//! in. The first checks the persisted ledger against three caps (lifetime,
//! this calendar month, today, all UTC) and refuses when the worst case of the
//! call would cross any of them; the second appends the call to the ledger
//! with its tokens and its cost, priced from `config/ai_prices.json`.
//!
//! The ledger is one JSON object per line in `<dir>/ledger.jsonl`, appended
//! and never rewritten, so it survives restarts and a crash can at most lose
//! the line being written. Several processes may share it: each one reads the
//! lines the others appended before every check. The caps live beside it in
//! `<dir>/budget.json`, which the app's settings write; a missing or broken
//! file means the defaults, which are the low ones.
//!
//! Alerts: when a call takes the lifetime spend past 50 %, 80 % or 100 % of the
//! lifetime cap, or the first time a call is refused because the lifetime cap
//! is used up, the alert hook fires once for that step. Which steps have been
//! sent is kept in `<dir>/alerts.json`, so a restart does not repeat them.
//!
//! Without a folder (no `PYTHIA_AI_DIR`, no data folder) the budget still
//! applies, to this process's own calls, and is lost on exit.

use std::collections::{BTreeMap, VecDeque};
use std::io::{Read, Seek, SeekFrom, Write};
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex, OnceLock};

use serde::{Deserialize, Serialize};

// ── prices ──────────────────────────────────────────────────────────────────

/// The price table, compiled in so a call is never costed from a file someone
/// edited by accident on the server.
const PRICES_JSON: &str = include_str!("../../../config/ai_prices.json");

/// USD per million tokens for one model.
#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Price {
    pub input: f64,
    pub output: f64,
    pub cache_write: f64,
    pub cache_read: f64,
    /// Prompts longer than this many tokens bill at the long rates.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub long_above: Option<u64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub long_input: Option<f64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub long_output: Option<f64>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct PriceTable {
    /// The date the list prices were last checked.
    pub as_of: String,
    /// True while the rates are estimates rather than the published list.
    pub estimate: bool,
    /// Batch requests cost this share of the listed rates.
    pub batch_discount: f64,
    pub models: BTreeMap<String, Price>,
}

impl PriceTable {
    /// A model's price, and whether it is listed. An unlisted model gets the
    /// most expensive row: an unknown name must never look cheap.
    pub fn price(&self, model: &str) -> (Price, bool) {
        if let Some(p) = self.models.get(model.trim()) {
            return (*p, true);
        }
        let worst = self
            .models
            .values()
            .copied()
            .max_by(|a, b| (a.input + a.output).total_cmp(&(b.input + b.output)))
            .unwrap_or(Price {
                input: 15.0,
                output: 75.0,
                cache_write: 18.75,
                cache_read: 1.5,
                long_above: None,
                long_input: None,
                long_output: None,
            });
        (worst, false)
    }

    /// What `usage` cost on `model`, in USD.
    pub fn cost(&self, model: &str, usage: &Usage, batch: bool) -> f64 {
        let (p, _) = self.price(model);
        let prompt = usage.input_tokens + usage.cache_write_tokens + usage.cache_read_tokens;
        let long = p.long_above.is_some_and(|n| prompt > n);
        let (input, output) = if long {
            (p.long_input.unwrap_or(p.input), p.long_output.unwrap_or(p.output))
        } else {
            (p.input, p.output)
        };
        let scale = if long { input / p.input.max(1e-12) } else { 1.0 };
        let usd = (usage.input_tokens as f64 * input
            + usage.output_tokens as f64 * output
            + usage.cache_write_tokens as f64 * p.cache_write * scale
            + usage.cache_read_tokens as f64 * p.cache_read * scale)
            / 1e6;
        if batch {
            usd * self.batch_discount
        } else {
            usd
        }
    }
}

/// The compiled-in table.
pub fn prices() -> &'static PriceTable {
    static P: OnceLock<PriceTable> = OnceLock::new();
    P.get_or_init(|| serde_json::from_str(PRICES_JSON).expect("config/ai_prices.json is valid"))
}

/// Tokens one call used, as the API bills them. `input_tokens` excludes the
/// cached parts, which are counted on their own.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Usage {
    pub input_tokens: u64,
    pub output_tokens: u64,
    #[serde(default)]
    pub cache_write_tokens: u64,
    #[serde(default)]
    pub cache_read_tokens: u64,
}

impl Usage {
    /// From the `usage` object of a Messages API response.
    pub fn from_api(u: Option<&serde_json::Value>) -> Usage {
        let n = |k: &str| u.and_then(|u| u.get(k)).and_then(|v| v.as_u64()).unwrap_or(0);
        Usage {
            input_tokens: n("input_tokens"),
            output_tokens: n("output_tokens"),
            cache_write_tokens: n("cache_creation_input_tokens"),
            cache_read_tokens: n("cache_read_input_tokens"),
        }
    }
}

/// The worst case of a call before it is made: the prompt at two characters
/// a token (real text runs nearer four) and every allowed output token.
pub fn estimate(model: &str, prompt_chars: usize, max_tokens: u64, batch: bool) -> f64 {
    let usage = Usage {
        input_tokens: (prompt_chars as u64) / 2 + 64,
        output_tokens: max_tokens,
        ..Usage::default()
    };
    prices().cost(model, &usage, batch)
}

// ── caps ────────────────────────────────────────────────────────────────────

/// The three caps, in USD. The defaults fit a 100 USD credit used rarely.
#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Caps {
    pub lifetime_usd: f64,
    pub monthly_usd: f64,
    pub daily_usd: f64,
}

pub const DEFAULT_CAPS: Caps = Caps { lifetime_usd: 90.0, monthly_usd: 15.0, daily_usd: 1.5 };
/// No cap may be set above this. A typo should not unlock a fortune.
pub const MAX_CAP_USD: f64 = 1_000.0;

impl Default for Caps {
    fn default() -> Self {
        DEFAULT_CAPS
    }
}

impl Caps {
    /// Every cap finite and between 0 and [`MAX_CAP_USD`]; a missing or bad
    /// value falls back to its default.
    pub fn sanitized(self) -> Caps {
        let fix = |v: f64, d: f64| if v.is_finite() && v >= 0.0 { v.min(MAX_CAP_USD) } else { d };
        Caps {
            lifetime_usd: fix(self.lifetime_usd, DEFAULT_CAPS.lifetime_usd),
            monthly_usd: fix(self.monthly_usd, DEFAULT_CAPS.monthly_usd),
            daily_usd: fix(self.daily_usd, DEFAULT_CAPS.daily_usd),
        }
    }
}

// ── ledger ──────────────────────────────────────────────────────────────────

/// One paid call, as written to the ledger.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Entry {
    /// When the answer came back, epoch ms.
    pub ts: i64,
    /// Which process made it (`server`, `desktop`).
    #[serde(default)]
    pub source: String,
    /// What it was for (`brief`, `weekly`, `overlay`, `signal`, ...).
    #[serde(default)]
    pub job: String,
    pub model: String,
    /// The model that answered, when a fallback took over.
    #[serde(default, skip_serializing_if = "String::is_empty")]
    pub served_by: String,
    #[serde(flatten)]
    pub usage: Usage,
    #[serde(default)]
    pub batch: bool,
    pub cost_usd: f64,
    /// False when the answer was billed but not usable (refused, unreadable,
    /// a batch given up on: those are costed at their worst case).
    #[serde(default = "yes")]
    pub ok: bool,
}

fn yes() -> bool {
    true
}

/// Why a call was not made.
#[derive(Debug, Clone, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", tag = "cap")]
pub enum Refusal {
    Lifetime { spent_usd: f64, cap_usd: f64, call_usd: f64 },
    Monthly { spent_usd: f64, cap_usd: f64, call_usd: f64 },
    Daily { spent_usd: f64, cap_usd: f64, call_usd: f64 },
}

impl std::fmt::Display for Refusal {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        let (what, spent, cap, call) = match self {
            Refusal::Lifetime { spent_usd, cap_usd, call_usd } => ("lifetime", spent_usd, cap_usd, call_usd),
            Refusal::Monthly { spent_usd, cap_usd, call_usd } => ("monthly", spent_usd, cap_usd, call_usd),
            Refusal::Daily { spent_usd, cap_usd, call_usd } => ("daily", spent_usd, cap_usd, call_usd),
        };
        write!(
            f,
            "AI budget: the {what} cap of ${cap:.2} would be crossed (spent ${spent:.4}, this call up to ${call:.4}); not called"
        )
    }
}

/// Spend so far, for the app.
#[derive(Debug, Clone, Default, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Spend {
    pub lifetime_usd: f64,
    pub month_usd: f64,
    pub today_usd: f64,
    pub calls: u64,
    pub calls_today: u64,
    /// `YYYY-MM` and `YYYY-MM-DD`, UTC, the periods the two figures cover.
    pub month: String,
    pub day: String,
    /// Reserved by calls still in flight.
    pub in_flight_usd: f64,
}

/// One step of the lifetime alert.
#[derive(Debug, Clone, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct BudgetAlert {
    /// 50, 80 or 100.
    pub percent: u8,
    pub spent_usd: f64,
    pub cap_usd: f64,
    /// The step was reached by a refusal, not by spending.
    pub refused: bool,
}

impl BudgetAlert {
    pub fn text(&self) -> String {
        if self.percent >= 100 {
            format!(
                "The Claude API budget is used up: ${:.2} of the ${:.2} lifetime cap. Every further call is refused until the cap is raised in Settings.",
                self.spent_usd, self.cap_usd
            )
        } else {
            format!(
                "The Claude API has used {} % of its lifetime budget: ${:.2} of ${:.2}.",
                self.percent, self.spent_usd, self.cap_usd
            )
        }
    }
}

pub const ALERT_STEPS: [u8; 3] = [50, 80, 100];

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct AlertState {
    cap_usd: f64,
    sent: Vec<u8>,
}

type Hook = Arc<dyn Fn(&BudgetAlert) + Send + Sync>;

#[derive(Default)]
struct Inner {
    /// (path, bytes already read). The first is this process's own ledger.
    files: Vec<(PathBuf, u64)>,
    lifetime: f64,
    calls: u64,
    /// `YYYY-MM-DD` → (USD, calls).
    by_day: BTreeMap<String, (f64, u64)>,
    recent: VecDeque<Entry>,
    reserved: f64,
    /// Caps when there is no folder to keep them in.
    caps: Option<Caps>,
    alerts: AlertState,
}

/// The budget of one ledger folder.
pub struct Budget {
    dir: Option<PathBuf>,
    source: String,
    inner: Mutex<Inner>,
    hook: Mutex<Option<Hook>>,
}

const RECENT: usize = 50;

fn day_of(ms: i64) -> String {
    chrono::DateTime::from_timestamp_millis(ms)
        .unwrap_or_default()
        .format("%Y-%m-%d")
        .to_string()
}

impl Budget {
    /// The budget kept in `dir` (created on the first write), or in memory.
    pub fn open(dir: Option<PathBuf>, source: impl Into<String>) -> Budget {
        let mut inner = Inner::default();
        if let Some(d) = &dir {
            inner.files.push((d.join("ledger.jsonl"), 0));
        }
        Budget { dir, source: source.into(), inner: Mutex::new(inner), hook: Mutex::new(None) }
    }

    /// Also count the calls in another ledger, read only: the desktop app
    /// adds the server's, synced to this machine, so both stay under one cap.
    pub fn with_mirror(self, ledger: PathBuf) -> Budget {
        {
            let mut i = self.inner.lock().unwrap();
            if !i.files.iter().any(|(p, _)| *p == ledger) {
                i.files.push((ledger, 0));
            }
        }
        self
    }

    pub fn dir(&self) -> Option<&Path> {
        self.dir.as_deref()
    }

    /// Called once for each alert step, from the thread that made the call.
    pub fn set_alert_hook(&self, f: impl Fn(&BudgetAlert) + Send + Sync + 'static) {
        *self.hook.lock().unwrap() = Some(Arc::new(f));
    }

    // ── caps ──

    pub fn caps(&self) -> Caps {
        match &self.dir {
            Some(d) => std::fs::read_to_string(d.join("budget.json"))
                .ok()
                .and_then(|s| serde_json::from_str::<Caps>(&s).ok())
                .map(Caps::sanitized)
                .unwrap_or_default(),
            None => self.inner.lock().unwrap().caps.unwrap_or_default(),
        }
    }

    /// Save new caps. They apply to the next check, in every process.
    pub fn set_caps(&self, caps: Caps) -> std::io::Result<Caps> {
        let caps = caps.sanitized();
        match &self.dir {
            Some(d) => {
                std::fs::create_dir_all(d)?;
                let tmp = d.join("budget.json.tmp");
                std::fs::write(&tmp, serde_json::to_vec_pretty(&caps).unwrap_or_default())?;
                std::fs::rename(&tmp, d.join("budget.json"))?;
            }
            None => self.inner.lock().unwrap().caps = Some(caps),
        }
        Ok(caps)
    }

    // ── reading ──

    /// Read what was appended to every ledger since the last look.
    fn refresh(&self, i: &mut Inner) {
        for k in 0..i.files.len() {
            let (path, offset) = i.files[k].clone();
            let Ok(mut f) = std::fs::File::open(&path) else { continue };
            let len = f.metadata().map(|m| m.len()).unwrap_or(0);
            if len < offset {
                // Shorter than what was read: replaced. Start over, all files.
                Self::reset(i);
                return self.refresh(i);
            }
            if len == offset || f.seek(SeekFrom::Start(offset)).is_err() {
                continue;
            }
            let mut buf = Vec::new();
            if f.read_to_end(&mut buf).is_err() {
                continue;
            }
            // Only whole lines: another process may be halfway through one.
            let Some(end) = buf.iter().rposition(|&b| b == b'\n') else { continue };
            for line in buf[..=end].split(|&b| b == b'\n') {
                if line.iter().all(|b| b.is_ascii_whitespace()) {
                    continue;
                }
                match serde_json::from_slice::<Entry>(line) {
                    Ok(e) => Self::add(i, e),
                    Err(e) => tracing::warn!("AI ledger: a line in {} is unreadable ({e}); skipped", path.display()),
                }
            }
            i.files[k].1 = offset + end as u64 + 1;
        }
    }

    fn reset(i: &mut Inner) {
        for f in i.files.iter_mut() {
            f.1 = 0;
        }
        i.lifetime = 0.0;
        i.calls = 0;
        i.by_day.clear();
        i.recent.clear();
    }

    fn add(i: &mut Inner, e: Entry) {
        let cost = if e.cost_usd.is_finite() && e.cost_usd > 0.0 { e.cost_usd } else { 0.0 };
        i.lifetime += cost;
        i.calls += 1;
        let d = i.by_day.entry(day_of(e.ts)).or_default();
        d.0 += cost;
        d.1 += 1;
        i.recent.push_back(e);
        while i.recent.len() > RECENT {
            i.recent.pop_front();
        }
    }

    fn spend_of(i: &Inner, now: i64) -> Spend {
        let day = day_of(now);
        let month = day[..7].to_string();
        let (today_usd, calls_today) = i.by_day.get(&day).copied().unwrap_or_default();
        let month_usd = i.by_day.range(format!("{month}-00")..=format!("{month}-99")).map(|(_, v)| v.0).sum();
        Spend {
            lifetime_usd: i.lifetime,
            month_usd,
            today_usd,
            calls: i.calls,
            calls_today,
            month,
            day,
            in_flight_usd: i.reserved,
        }
    }

    /// Spend as of `now` (epoch ms), after reading the ledgers.
    pub fn spend(&self, now: i64) -> Spend {
        let mut i = self.inner.lock().unwrap();
        self.refresh(&mut i);
        Self::spend_of(&i, now)
    }

    /// The last calls, newest first.
    pub fn recent(&self, n: usize) -> Vec<Entry> {
        let mut i = self.inner.lock().unwrap();
        self.refresh(&mut i);
        i.recent.iter().rev().take(n).cloned().collect()
    }

    /// The cap that would refuse a call of `usd` now, if any.
    pub fn would_refuse(&self, usd: f64, now: i64) -> Option<Refusal> {
        let caps = self.caps();
        let mut i = self.inner.lock().unwrap();
        self.refresh(&mut i);
        Self::check(&i, &caps, usd, now)
    }

    fn check(i: &Inner, caps: &Caps, usd: f64, now: i64) -> Option<Refusal> {
        let s = Self::spend_of(i, now);
        let call = usd.max(0.0);
        // Lifetime first: it is the one that matters and the one that alerts.
        let over = |spent: f64, cap: f64| spent + i.reserved + call > cap + 1e-12 || spent >= cap;
        if over(s.lifetime_usd, caps.lifetime_usd) {
            return Some(Refusal::Lifetime { spent_usd: s.lifetime_usd, cap_usd: caps.lifetime_usd, call_usd: call });
        }
        if over(s.month_usd, caps.monthly_usd) {
            return Some(Refusal::Monthly { spent_usd: s.month_usd, cap_usd: caps.monthly_usd, call_usd: call });
        }
        if over(s.today_usd, caps.daily_usd) {
            return Some(Refusal::Daily { spent_usd: s.today_usd, cap_usd: caps.daily_usd, call_usd: call });
        }
        None
    }

    // ── calling ──

    /// Ask for room for a call that costs at most `usd`. Refused when any cap
    /// would be crossed. The room is held until the reservation is recorded
    /// or dropped, so two calls in flight cannot both take the last dollar.
    pub fn reserve(&self, usd: f64, now: i64) -> Result<Reservation<'_>, Refusal> {
        let caps = self.caps();
        let mut fired = Vec::new();
        let res = {
            let mut i = self.inner.lock().unwrap();
            self.refresh(&mut i);
            match Self::check(&i, &caps, usd, now) {
                Some(r) => {
                    // "Used up" only when even a one-cent call no longer fits,
                    // not when one large call does not.
                    if matches!(r, Refusal::Lifetime { .. }) && i.lifetime + i.reserved + 0.01 > caps.lifetime_usd {
                        let spent = i.lifetime;
                        fired = self.step_alerts(&mut i, &caps, spent, spent, true);
                    }
                    Err(r)
                }
                None => {
                    let usd = usd.max(0.0);
                    i.reserved += usd;
                    Ok(Reservation { budget: self, usd, done: false })
                }
            }
        };
        self.fire(fired);
        res
    }

    /// Append one line to this process's ledger. False when there is no
    /// folder or the write failed.
    fn append(&self, e: &Entry) -> bool {
        let Some(d) = &self.dir else { return false };
        let write = || -> std::io::Result<()> {
            std::fs::create_dir_all(d)?;
            let mut line = serde_json::to_vec(e).map_err(std::io::Error::other)?;
            line.push(b'\n');
            let mut f = std::fs::OpenOptions::new().create(true).append(true).open(d.join("ledger.jsonl"))?;
            // One write of one line: appends from other processes never interleave inside it.
            f.write_all(&line)?;
            f.sync_data()
        };
        match write() {
            Ok(()) => true,
            Err(err) => {
                tracing::error!("AI ledger not written ({err}); the call is counted in memory only");
                false
            }
        }
    }

    fn record_entry(&self, reserved: f64, e: Entry) -> Entry {
        let caps = self.caps();
        let fired = {
            let mut i = self.inner.lock().unwrap();
            i.reserved = (i.reserved - reserved).max(0.0);
            self.refresh(&mut i);
            let before = i.lifetime;
            if self.append(&e) {
                // Read back with whatever other processes appended meanwhile.
                self.refresh(&mut i);
            } else {
                Self::add(&mut i, e.clone());
            }
            let after = i.lifetime;
            self.step_alerts(&mut i, &caps, before, after, false)
        };
        self.fire(fired);
        e
    }

    // ── alerts ──

    fn alerts_path(&self) -> Option<PathBuf> {
        self.dir.as_ref().map(|d| d.join("alerts.json"))
    }

    /// The steps reached and not yet sent; marks them sent.
    ///
    /// `before` is the lifetime spend before this call, `spent` after it.
    fn step_alerts(&self, i: &mut Inner, caps: &Caps, before: f64, spent: f64, refused: bool) -> Vec<BudgetAlert> {
        // Read every time: another process sharing the folder may have sent one.
        if let Some(p) = self.alerts_path() {
            if let Some(s) = std::fs::read_to_string(p).ok().and_then(|s| serde_json::from_str(&s).ok()) {
                i.alerts = s;
            }
        }
        let cap = caps.lifetime_usd;
        if cap <= 0.0 {
            // A zero cap switches the API off; that is not news.
            return Vec::new();
        }
        if (i.alerts.cap_usd - cap).abs() > 1e-9 {
            // A new cap (or the first look): the steps already behind us
            // before this call are not news; the ones it crosses are.
            i.alerts = AlertState {
                cap_usd: cap,
                sent: ALERT_STEPS.iter().copied().filter(|&s| before >= cap * s as f64 / 100.0).collect(),
            };
            self.save_alerts(&i.alerts);
        }
        let mut out = Vec::new();
        for s in ALERT_STEPS {
            let reached = spent >= cap * s as f64 / 100.0 - 1e-12 || (s == 100 && refused);
            if reached && !i.alerts.sent.contains(&s) {
                i.alerts.sent.push(s);
                out.push(BudgetAlert { percent: s, spent_usd: spent, cap_usd: cap, refused: refused && s == 100 });
            }
        }
        if !out.is_empty() {
            self.save_alerts(&i.alerts);
        }
        // One message for several steps at once: the highest says it all.
        out.into_iter().max_by_key(|a| a.percent).into_iter().collect()
    }

    fn save_alerts(&self, s: &AlertState) {
        if let Some(p) = self.alerts_path() {
            let _ = std::fs::create_dir_all(p.parent().unwrap_or(Path::new(".")));
            if let Err(e) = std::fs::write(&p, serde_json::to_vec(s).unwrap_or_default()) {
                tracing::warn!("AI budget alert state not saved: {e}");
            }
        }
    }

    fn fire(&self, alerts: Vec<BudgetAlert>) {
        if alerts.is_empty() {
            return;
        }
        let hook = self.hook.lock().unwrap().clone();
        for a in alerts {
            tracing::warn!("{}", a.text());
            if let Some(h) = &hook {
                h(&a);
            }
        }
    }
}

/// Room held for one call. Record it with what the call really used; dropped
/// unrecorded (the call failed before anything was billed), it frees the room.
pub struct Reservation<'a> {
    budget: &'a Budget,
    usd: f64,
    done: bool,
}

impl std::fmt::Debug for Reservation<'_> {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "Reservation(${:.4})", self.usd)
    }
}

impl Reservation<'_> {
    /// The call's worst case, as reserved.
    pub fn usd(&self) -> f64 {
        self.usd
    }

    /// Write the billed call to the ledger. Returns the entry as written.
    #[allow(clippy::too_many_arguments)]
    pub fn record(
        mut self,
        job: &str,
        model: &str,
        served_by: &str,
        usage: Usage,
        batch: bool,
        ok: bool,
        now: i64,
    ) -> Entry {
        let t = prices();
        // A fallback model bills at its own rates: cost the dearer of the two.
        let mut cost = t.cost(model, &usage, batch);
        if !served_by.is_empty() && served_by != model {
            cost = cost.max(t.cost(served_by, &usage, batch));
        }
        self.done = true;
        let e = Entry {
            ts: now,
            source: self.budget.source.clone(),
            job: job.to_string(),
            model: model.to_string(),
            served_by: if served_by == model { String::new() } else { served_by.to_string() },
            usage,
            batch,
            cost_usd: cost,
            ok,
        };
        self.budget.record_entry(self.usd, e)
    }

    /// Record the call at its full reserved worst case: billed for an unknown
    /// amount (a batch given up on). Never undercounts.
    pub fn record_worst_case(mut self, job: &str, model: &str, batch: bool, now: i64) -> Entry {
        self.done = true;
        let e = Entry {
            ts: now,
            source: self.budget.source.clone(),
            job: job.to_string(),
            model: model.to_string(),
            served_by: String::new(),
            usage: Usage::default(),
            batch,
            cost_usd: self.usd,
            ok: false,
        };
        self.budget.record_entry(self.usd, e)
    }
}

impl Drop for Reservation<'_> {
    fn drop(&mut self) {
        if !self.done {
            let mut i = self.budget.inner.lock().unwrap();
            i.reserved = (i.reserved - self.usd).max(0.0);
        }
    }
}

// ── the process-wide budget ─────────────────────────────────────────────────

static GLOBAL: OnceLock<Budget> = OnceLock::new();

/// The folder the server keeps the ledger in: `PYTHIA_AI_DIR`, else `ai/`
/// under the data folder.
pub fn default_dir() -> Option<PathBuf> {
    if let Ok(d) = std::env::var("PYTHIA_AI_DIR") {
        if !d.trim().is_empty() {
            return Some(PathBuf::from(d.trim()));
        }
    }
    crate::labview::data_dir().map(|d| d.join("ai"))
}

/// Install the process-wide budget. Only the first call counts; returns false
/// when one was already in place (or already used).
pub fn init(budget: Budget) -> bool {
    GLOBAL.set(budget).is_ok()
}

/// The process-wide budget every Claude call goes through. Without [`init`]
/// it is the default folder's, labelled `engine`.
pub fn global() -> &'static Budget {
    GLOBAL.get_or_init(|| Budget::open(default_dir(), "engine"))
}

/// The token a local job shows the engine to have a completion run for it:
/// proof it holds the same API key, without sending the key. Hex SHA-256 of
/// `pythia-ai:<key>`; empty for an empty key, which nothing matches.
pub fn caller_token(api_key: &str) -> String {
    use sha2::{Digest, Sha256};
    let key = api_key.trim();
    if key.is_empty() {
        return String::new();
    }
    hex::encode(Sha256::digest(format!("pythia-ai:{key}").as_bytes()))
}

/// What the app shows: caps, spend, prices and the last calls.
#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct BudgetView {
    pub caps: Caps,
    pub defaults: Caps,
    pub spend: Spend,
    /// Left under each cap, never below zero.
    pub left_lifetime_usd: f64,
    pub left_month_usd: f64,
    pub left_today_usd: f64,
    /// Which cap refuses a cheap call right now, if any.
    pub refusing: Option<String>,
    pub recent: Vec<Entry>,
    pub prices_as_of: String,
    pub prices_estimate: bool,
    /// Whether the ledger is kept on disk.
    pub persisted: bool,
}

impl Budget {
    pub fn view(&self, now: i64) -> BudgetView {
        let caps = self.caps();
        let spend = self.spend(now);
        let refusing = self.would_refuse(0.0001, now).map(|r| r.to_string());
        BudgetView {
            left_lifetime_usd: (caps.lifetime_usd - spend.lifetime_usd).max(0.0),
            left_month_usd: (caps.monthly_usd - spend.month_usd).max(0.0),
            left_today_usd: (caps.daily_usd - spend.today_usd).max(0.0),
            caps,
            defaults: DEFAULT_CAPS,
            spend,
            refusing,
            recent: self.recent(20),
            prices_as_of: prices().as_of.clone(),
            prices_estimate: prices().estimate,
            persisted: self.dir.is_some(),
        }
    }
}

#[cfg(test)]
#[path = "ai_budget_tests.rs"]
mod tests;
