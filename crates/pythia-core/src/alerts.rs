//! Webhook alerts.
//!
//! Two paths share this module:
//!
//! - [`post`]: the older free-text push of the engine's notable events (fills,
//!   exits, risk actions) to `PYTHIA_WEBHOOK_URL` or the desktop app's vault
//!   entry. Best-effort and time-boxed.
//! - [`AlertSink`]: typed operator alerts ([`AlertKind`]) to the owner's
//!   Telegram chat (`PYTHIA_TELEGRAM_BOT_TOKEN`, `PYTHIA_TELEGRAM_CHAT_ID`) or
//!   a Discord or Slack webhook (`PYTHIA_ALERT_WEBHOOK`), for the events an
//!   owner wants on the phone without opening the app: autopilot events,
//!   trades and rebalances, big moves, the kill switch and the floors, venue
//!   and data problems, models, and whatever the lab posts through
//!   `POST /api/alerts/event`. The engine only queues them ([`AlertEvent`]); a
//!   background task delivers them, so a slow or dead destination never holds
//!   up a tick. Each alert is one card ([`card::Card`]): a bold title with one
//!   emoji, a short summary, aligned numbers. Every category has a switch
//!   ([`AlertSettings`]), quiet hours hold back all but urgent alerts and say
//!   in the morning what was held, repeats of the same event are dropped
//!   inside a window, the posts per hour are capped, and a failing destination
//!   is logged once until it works again. The URL and the bot token are
//!   secrets: read from the environment and never logged.
//!
//! Native-only: a browser cannot POST cross-origin to Discord.

use std::collections::{HashMap, VecDeque};
use std::sync::Arc;
use std::time::Duration;

use serde::Serialize;
use tokio::sync::mpsc;

#[path = "alerts_card.rs"]
pub mod card;
#[path = "alerts_i18n.rs"]
pub mod i18n;
#[path = "alerts_moves.rs"]
mod moves;
#[path = "alerts_settings.rs"]
mod settings;

pub use card::{Card, Row, Table, Tone};
pub use i18n::{HeldFills, HeldGroup, Lang, Msg};
pub use moves::{MoveInput, MoveSubject, MoveWatch};
pub use settings::{
    parse_hhmm, AlertCategory, AlertSettings, AlertSettingsPatch, BigMoves, BigMovesPatch, QuietHours, QuietHoursPatch,
};

use card::{esc, price, qty, render_post};
use i18n::{word, Word};

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
    /// A fill of an autopilot; fills that arrive together go out as one
    /// message with a small table.
    Trade,
    /// A held coin or an autopilot's equity moved more than the set %.
    BigMove,
    /// Posted by a lab job through `POST /api/alerts/event`.
    Event,
    /// What quiet hours held back, said once they are over.
    Overnight,
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
            AlertKind::Trade => "Trade",
            AlertKind::BigMove => "Big move",
            AlertKind::Event => "Lab",
            AlertKind::Overnight => "Quiet hours are over",
            AlertKind::Test => "Test",
        }
    }

    /// The leading emoji of its card.
    pub fn emoji(self) -> &'static str {
        match self {
            AlertKind::AutopilotStarted => "🚀",
            AlertKind::AutopilotStopped => "⏹️",
            AlertKind::StopRuleHit => "🏁",
            AlertKind::FloorHit => "🛑",
            AlertKind::KillSwitch => "🚨",
            AlertKind::DailyLossBrake => "🧯",
            AlertKind::OrderRejects => "⛔",
            AlertKind::ReconcileMismatch => "⚖️",
            AlertKind::DataStale => "📡",
            AlertKind::ModelDrift => "🧭",
            AlertKind::Trade => "💱",
            AlertKind::BigMove => "🌊",
            AlertKind::Event => "🔔",
            AlertKind::Overnight => "🌙",
            AlertKind::Test => "✅",
        }
    }

    /// Its switch in Settings. `None`: always sent (the test message, the
    /// morning note after quiet hours).
    pub fn category(self) -> Option<AlertCategory> {
        match self {
            AlertKind::AutopilotStarted | AlertKind::AutopilotStopped | AlertKind::StopRuleHit => Some(AlertCategory::Autopilot),
            AlertKind::FloorHit | AlertKind::KillSwitch | AlertKind::DailyLossBrake | AlertKind::OrderRejects => {
                Some(AlertCategory::Risk)
            }
            AlertKind::ReconcileMismatch | AlertKind::DataStale => Some(AlertCategory::Venue),
            AlertKind::ModelDrift => Some(AlertCategory::Models),
            AlertKind::Trade => Some(AlertCategory::Trades),
            AlertKind::BigMove => Some(AlertCategory::BigMoves),
            AlertKind::Event | AlertKind::Overnight | AlertKind::Test => None,
        }
    }

    /// Sent even while alerts are muted or in quiet hours, past the hourly
    /// limit and whatever the switches say: the money stopped trading, or
    /// the day's loss limit was reached.
    pub fn bypasses_mute(self) -> bool {
        matches!(self, AlertKind::KillSwitch | AlertKind::FloorHit | AlertKind::DailyLossBrake)
    }
}

/// One fill of an autopilot, for the trades table.
#[derive(Debug, Clone, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct TradeLine {
    /// The autopilot's name.
    pub book: String,
    pub buy: bool,
    pub symbol: String,
    pub qty: f64,
    pub price: f64,
    pub fee: f64,
    /// P&L this fill realised.
    pub realized: f64,
    /// Part of a lab book's rebalance (a netted target), not a single signal.
    pub rebalance: bool,
    /// `paper`, `demo` or `live`.
    pub mode: String,
    /// Traded for an experimental lab book (one that failed the lab's bar):
    /// the line and its card say "experiment".
    pub experiment: bool,
}

/// One operator alert. `key` identifies the condition for deduplication:
/// two events with the same key inside the dedup window send once.
#[derive(Debug, Clone, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct AlertEvent {
    pub kind: AlertKind,
    pub key: String,
    /// The whole message in one sentence or more, for the journal and for
    /// a destination that shows only text.
    pub text: String,
    /// The card's title; the kind's label when `None`.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub title: Option<String>,
    /// The card's one line under the title; `text` when `None`.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub summary: Option<String>,
    #[serde(skip_serializing_if = "Vec::is_empty")]
    pub rows: Vec<Row>,
    /// A small table under the numbers.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub table: Option<Table>,
    /// A short line under the card, in italics.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub footer: Option<String>,
    /// Overrides the kind's category (a lab event says which it is).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub category: Option<AlertCategory>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub emoji: Option<String>,
    /// Goes out in quiet hours and while muted.
    #[serde(skip_serializing_if = "std::ops::Not::not")]
    pub urgent: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub trade: Option<TradeLine>,
    /// A PNG or JPEG sent as a photo with the card as its caption (Telegram).
    #[serde(skip)]
    pub image: Option<Arc<Vec<u8>>>,
    /// The engine's message behind the card, so it can be said in the
    /// language the chat is set to. Lab events come already worded.
    #[serde(skip)]
    pub msg: Option<Box<Msg>>,
}

/// The first letter in upper case: the engine's texts were written to follow
/// a label ("Kill switch: engaged by hand.").
fn sentence(s: &str) -> String {
    i18n::sentence(s)
}

impl AlertEvent {
    pub fn new(kind: AlertKind, key: impl Into<String>, text: impl Into<String>) -> Self {
        Self {
            kind,
            key: key.into(),
            text: text.into(),
            title: None,
            summary: None,
            rows: Vec::new(),
            table: None,
            footer: None,
            category: None,
            emoji: None,
            urgent: false,
            trade: None,
            image: None,
            msg: None,
        }
    }

    /// One of the engine's messages: its kind, its English text for the
    /// journal and its card, said again in the chat's language when sent.
    pub fn from_msg(key: impl Into<String>, msg: Msg) -> Self {
        let text = msg.text(Lang::En);
        Self::new(msg.kind(), key, text).with_msg(msg)
    }

    /// Attach the message behind the card: the English card fields come from
    /// it, the text stays what was given.
    pub fn with_msg(mut self, msg: Msg) -> Self {
        let c = msg.card_text(Lang::En);
        if c.title.is_some() {
            self.title = c.title;
        }
        if let Some(s) = c.summary {
            self = self.with_summary(s);
        }
        if !c.rows.is_empty() {
            self.rows = c.rows;
        }
        if c.table.is_some() {
            self.table = c.table;
        }
        if c.footer.is_some() {
            self.footer = c.footer;
        }
        self.msg = Some(Box::new(msg));
        self
    }

    /// A fill of an autopilot. A rebalance fill counts as a rebalance, any
    /// other as a trade.
    pub fn trade(key: impl Into<String>, t: TradeLine) -> Self {
        let side = if t.buy { "bought" } else { "sold" };
        let exp = if t.experiment { " (experiment)" } else { "" };
        let text = format!("{}{exp} {side} {} {} at {}", t.book, qty(t.qty), t.symbol, price(t.price));
        let cat = if t.rebalance { AlertCategory::Rebalances } else { AlertCategory::Trades };
        let mut ev = Self::new(AlertKind::Trade, key, text).in_category(cat);
        ev.trade = Some(t);
        ev
    }

    pub fn titled(mut self, t: impl Into<String>) -> Self {
        self.title = Some(t.into());
        self
    }
    pub fn with_summary(mut self, s: impl Into<String>) -> Self {
        let s = s.into();
        self.summary = (!s.trim().is_empty()).then_some(s);
        self
    }
    pub fn with_rows(mut self, rows: Vec<Row>) -> Self {
        self.rows = rows;
        self
    }
    pub fn with_table(mut self, t: Table) -> Self {
        self.table = Some(t);
        self
    }
    pub fn with_footer(mut self, f: impl Into<String>) -> Self {
        let f = f.into();
        self.footer = (!f.trim().is_empty()).then_some(f);
        self
    }
    pub fn in_category(mut self, c: AlertCategory) -> Self {
        self.category = Some(c);
        self
    }
    pub fn with_emoji(mut self, e: impl Into<String>) -> Self {
        self.emoji = Some(e.into());
        self
    }
    pub fn urgent(mut self) -> Self {
        self.urgent = true;
        self
    }
    pub fn with_image(mut self, png: Vec<u8>) -> Self {
        self.image = Some(Arc::new(png));
        self
    }

    /// Its switch in Settings, `None` for what is always sent.
    pub fn category(&self) -> Option<AlertCategory> {
        self.category.or_else(|| self.kind.category())
    }

    /// Goes out in quiet hours, while muted and past the hourly limit.
    pub fn is_urgent(&self) -> bool {
        self.urgent || self.kind.bypasses_mute()
    }

    /// The card's title, as plain text.
    pub fn title_text(&self) -> String {
        self.title_text_in(Lang::En)
    }

    /// The card's title in a language.
    pub fn title_text_in(&self, lang: Lang) -> String {
        if let Some(t) = &self.trade {
            let side = word(if t.buy { Word::Bought } else { Word::Sold }, lang);
            return format!("{} {side} {}", t.book, t.symbol);
        }
        if let Some(m) = &self.msg {
            return m.card_text(lang).title.unwrap_or_else(|| i18n::kind_label(self.kind, lang).to_string());
        }
        self.title.clone().unwrap_or_else(|| i18n::kind_label(self.kind, lang).to_string())
    }

    /// The alert as a card, in English.
    pub fn card(&self) -> Card {
        self.card_in(Lang::En)
    }

    /// The alert as a card in a language: an engine message is worded anew,
    /// a lab event is shown as it came.
    pub fn card_in(&self, lang: Lang) -> Card {
        let emoji = self
            .emoji
            .clone()
            .or_else(|| (self.kind == AlertKind::Event).then(|| self.category().map(|c| c.emoji().to_string())).flatten())
            .unwrap_or_else(|| self.kind.emoji().to_string());
        if let Some(m) = &self.msg {
            let c = m.card_text(lang);
            let summary = c.summary.unwrap_or_else(|| m.text(lang));
            return Card {
                emoji,
                title: self.title_text_in(lang),
                summary: Some(sentence(&summary)).filter(|s| !s.trim().is_empty()),
                lines: c.lines,
                more_lines: 0,
                rows: c.rows,
                table: c.table,
                footer: c.footer,
                table_first: false,
                lang,
            };
        }
        Card {
            emoji,
            title: self.title_text_in(lang),
            summary: Some(sentence(self.summary.as_deref().unwrap_or(&self.text))).filter(|s| !s.trim().is_empty()),
            lines: Vec::new(),
            more_lines: 0,
            rows: self.rows.clone(),
            table: self.table.clone(),
            footer: self.footer.clone(),
            table_first: false,
            lang,
        }
    }

    /// The line as posted in the old one-line style, for a log or a test.
    pub fn line(&self, format: AlertFormat) -> String {
        match format {
            AlertFormat::Discord => format!("**{}** {}", self.kind.label(), self.text),
            AlertFormat::Slack => format!("*{}* {}", self.kind.label(), self.text),
            AlertFormat::Telegram => format!("{}: {}", self.kind.label(), self.text),
        }
    }
}

/// The fills of one batch as cards: one per autopilot. A single fill is a
/// short card; several (a rebalance) are one card with a table, the same coin
/// and side added up.
pub fn trade_cards(trades: &[&TradeLine]) -> Vec<Card> {
    trade_cards_in(trades, Lang::En)
}

/// [`trade_cards`] in a language.
pub fn trade_cards_in(trades: &[&TradeLine], lang: Lang) -> Vec<Card> {
    use i18n::{fills_summary, fills_title, mode_footer};
    let w = |x: Word| word(x, lang).to_string();
    let mut books: Vec<(String, Vec<&TradeLine>)> = Vec::new();
    for t in trades {
        match books.iter_mut().find(|(b, _)| *b == t.book) {
            Some((_, v)) => v.push(t),
            None => books.push((t.book.clone(), vec![t])),
        }
    }
    let mut out = Vec::new();
    for (book, fills) in books {
        // Same coin, same side: one line. A line traded for an experimental
        // lab book is marked "experiment", and so is the card.
        let mut lines: Vec<(bool, String, f64, f64)> = Vec::new(); // buy, symbol, qty, value
        let mut exp_syms: Vec<String> = Vec::new();
        for t in &fills {
            let sym = t.symbol.clone();
            if t.experiment && !exp_syms.contains(&sym) {
                exp_syms.push(sym.clone());
            }
            match lines.iter_mut().find(|(b, s, ..)| *b == t.buy && *s == sym) {
                Some(l) => {
                    l.2 += t.qty;
                    l.3 += t.qty * t.price;
                }
                None => lines.push((t.buy, sym, t.qty, t.qty * t.price)),
            }
        }
        let experiment = !exp_syms.is_empty();
        let tag = if experiment { format!(" · {}", w(Word::Experiment)) } else { String::new() };
        let fees: f64 = fills.iter().map(|t| t.fee).sum();
        let realized: f64 = fills.iter().map(|t| t.realized).sum();
        let mode = fills[0].mode.clone();
        let footer = |m: &str| if experiment { i18n::experiment_footer(m, lang) } else { mode_footer(m, lang) };
        let rebalance = fills.iter().any(|t| t.rebalance);
        if lines.len() == 1 && !rebalance {
            let (buy, sym, q, value) = lines[0].clone();
            let side = word(if buy { Word::Bought } else { Word::Sold }, lang);
            let mut c = Card::new(if buy { "🟢" } else { "🔴" }, format!("{book} {side} {sym}{tag}"))
                .row(Row::new(w(Word::Amount), format!("{} {sym}", i18n::qty(lang, q))))
                .row(Row::new(w(Word::Price), i18n::price(lang, if q > 0.0 { value / q } else { 0.0 })))
                .row(Row::new(w(Word::Value), i18n::usd(lang, value)));
            if fees > 0.0 {
                c = c.row(Row::new(w(Word::Fee), i18n::usd(lang, fees)));
            }
            if realized.abs() > 1e-9 {
                c = c.row(Row::toned(w(Word::Realised), i18n::signed_usd(lang, realized), realized));
            }
            c.lang = lang;
            out.push(c.footer(footer(&mode)));
            continue;
        }
        let bought: f64 = lines.iter().filter(|l| l.0).map(|l| l.3).sum();
        let sold: f64 = lines.iter().filter(|l| !l.0).map(|l| l.3).sum();
        let n = fills.len();
        let title = if rebalance { format!("{} · {book}{tag}", w(Word::Rebalance)) } else { format!("{}{tag}", fills_title(lang, n, &book)) };
        let mut c = Card::new(if rebalance { "🔁" } else { "💱" }, title)
            .summary(fills_summary(lang, n, lines.len(), bought, sold));
        let mut rows: Vec<(bool, Vec<String>)> = lines
            .iter()
            .map(|(buy, sym, q, v)| {
                (
                    *buy,
                    vec![
                        w(if *buy { Word::Buy } else { Word::Sell }),
                        if exp_syms.contains(sym) { format!("{sym} ({})", w(Word::ExperimentShort)) } else { sym.clone() },
                        i18n::money(lang, *v, 0),
                        i18n::price(lang, if *q > 0.0 { v / q } else { 0.0 }),
                    ],
                )
            })
            .collect();
        // Sells first, then buys, the larger first: what a rebalance did.
        rows.sort_by_key(|r| r.0);
        let rows: Vec<Vec<String>> = rows.into_iter().map(|(_, r)| r).collect();
        c.table = Some(Table {
            header: vec![w(Word::Side), w(Word::Coin), w(Word::Value), w(Word::Price)],
            rows,
            more: 0,
        });
        c.table_first = true;
        if realized.abs() > 1e-9 {
            c = c.row(Row::toned(w(Word::Realised), i18n::signed_usd(lang, realized), realized));
        }
        if fees > 0.0 {
            c = c.row(Row::new(w(Word::Fees), i18n::usd(lang, fees)));
        }
        c.lang = lang;
        out.push(c.footer(footer(&mode)));
    }
    out
}

/// The JSON shape the webhook takes.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum AlertFormat {
    /// `{"content": "..."}`
    Discord,
    /// `{"text": "..."}`
    Slack,
    /// Telegram's `sendMessage`: `{"chat_id", "text", "parse_mode": "HTML"}`,
    /// every piece of text escaped (see [`card::esc`]).
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
    pub fn limit(self) -> usize {
        match self {
            AlertFormat::Discord => 1900,
            AlertFormat::Slack => 3000,
            AlertFormat::Telegram => 4000,
        }
    }
    pub fn body(self, content: &str) -> serde_json::Value {
        match self {
            AlertFormat::Discord => serde_json::json!({ "content": truncate(content, self.limit()) }),
            AlertFormat::Slack => serde_json::json!({ "text": truncate(content, self.limit()) }),
            AlertFormat::Telegram => {
                if content.chars().count() <= self.limit() {
                    serde_json::json!({ "text": content, "parse_mode": "HTML", "disable_web_page_preview": true })
                } else {
                    // Cut HTML could leave a tag open: too long goes as plain text.
                    serde_json::json!({ "text": truncate(&card::plain(content), self.limit()), "disable_web_page_preview": true })
                }
            }
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
    /// count rides on the next post that goes out. Urgent alerts pass.
    pub max_per_hour: usize,
    /// Events arriving within this time of each other go out as one post.
    pub batch_wait: Duration,
    /// The fills of one autopilot are collected until none came for this
    /// long, then go out as one card (a rebalance's partial maker fills
    /// arrive minutes apart; each was a card of its own).
    pub fill_quiet: Duration,
    /// And at the latest this long after the first of them.
    pub fill_max: Duration,
    /// Bounded queue between the engine and the sender.
    pub queue: usize,
    pub timeout: Duration,
    /// Footer of every post, so one chat can serve several engines.
    pub prefix: String,
    /// Telegram only: the chat the bot writes to.
    pub chat_id: Option<String>,
    /// How often the sender looks whether quiet hours are over.
    pub wake: Duration,
    /// `PYTHIA_ALERT_LANG`: the language of the messages, over the setting.
    pub lang: Option<Lang>,
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
            fill_quiet: Duration::from_secs(150),
            fill_max: Duration::from_secs(600),
            queue: 256,
            timeout: Duration::from_secs(15),
            prefix: "Pythia".into(),
            chat_id: None,
            wake: Duration::from_secs(60),
            lang: None,
        }
    }

    /// The language the messages go out in: the environment's, else the
    /// setting's.
    pub fn lang_for(&self, settings: &AlertSettings) -> Lang {
        settings.lang(self.lang)
    }

    /// `PYTHIA_TELEGRAM_BOT_TOKEN` and `PYTHIA_TELEGRAM_CHAT_ID` (both needed)
    /// send to that Telegram chat. Else `PYTHIA_ALERT_WEBHOOK` with
    /// `PYTHIA_ALERT_FORMAT` (`discord`, the default, or `slack`). A webhook,
    /// when set, wins over Telegram. Neither: `None`. Optional:
    /// `PYTHIA_ALERT_DEDUP_MIN` (30), `PYTHIA_ALERT_MAX_PER_HOUR` (20),
    /// `PYTHIA_ALERT_FILL_QUIET_S` (150) and `PYTHIA_ALERT_FILL_MAX_S` (600),
    /// `PYTHIA_ALERT_PREFIX` (`Pythia`), `PYTHIA_ALERT_LANG` (`en` or `de`,
    /// over the language in the settings).
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

    /// Telegram's `sendPhoto` for this bot.
    pub fn photo_url(&self) -> String {
        match self.url.strip_suffix("/sendMessage") {
            Some(base) => format!("{base}/sendPhoto"),
            None => self.url.clone(),
        }
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
        if let Some(s) = num("PYTHIA_ALERT_FILL_QUIET_S") {
            c.fill_quiet = Duration::from_secs(s);
        }
        if let Some(s) = num("PYTHIA_ALERT_FILL_MAX_S").filter(|s| *s > 0) {
            c.fill_max = Duration::from_secs(s);
        }
        if let Some(n) = num("PYTHIA_ALERT_MAX_PER_HOUR").filter(|n| *n > 0) {
            c.max_per_hour = n as usize;
        }
        if let Some(p) = get("PYTHIA_ALERT_PREFIX") {
            c.prefix = p.trim().to_string();
        }
        c.lang = Lang::from_lookup(get);
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
        self.expire(now);
        if self.sent.len() >= self.max_per_hour {
            return false;
        }
        self.sent.push_back(now);
        true
    }

    /// Count a post that goes out whatever the cap says (an urgent one).
    pub fn count(&mut self, now: i64) {
        self.expire(now);
        self.sent.push_back(now);
    }

    fn expire(&mut self, now: i64) {
        while self.sent.front().is_some_and(|&t| now - t >= 3_600_000) {
            self.sent.pop_front();
        }
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
    /// The first card's title, plain text.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub title: Option<String>,
    /// What was posted, in the destination's markup (HTML for Telegram).
    pub text: String,
    pub delivered: bool,
    /// Why a post failed (`HTTP 500`, a connection error). Never the URL or
    /// the token.
    pub error: Option<String>,
    /// Why nothing was posted: `muted`, `quiet` or `hourlyLimit`.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub reason: Option<String>,
    /// A chart went with it as a photo.
    #[serde(skip_serializing_if = "std::ops::Not::not")]
    pub photo: bool,
}

/// Counts for the current UTC day.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct AlertCounts {
    /// Posts that went through.
    pub sent_today: u64,
    /// Posts the destination did not take.
    pub failed_today: u64,
    /// Events held back by the mute, quiet hours or the hourly limit.
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
    settings: AlertSettings,
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

/// The last [`RECENT_POSTS`] posts, today's counts, the mute and the
/// settings, shared by the sender and the host's API. Cloning is cheap.
#[derive(Debug, Clone, Default)]
pub struct AlertLog(Arc<std::sync::Mutex<LogInner>>);

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

    pub fn settings(&self) -> AlertSettings {
        self.inner().settings.clone()
    }

    pub fn set_settings(&self, s: AlertSettings) {
        self.inner().settings = s;
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
    full_logged: Arc<std::sync::atomic::AtomicBool>,
    cfg: Arc<AlertConfig>,
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
        let cfg = Arc::new(cfg);
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

    /// Post one test message now, past the queue, the throttle, the mute and
    /// quiet hours (the operator asked for it), and record it. It shows what
    /// a card looks like and what is set.
    pub async fn test(&self) -> AlertRecord {
        let s = self.log.settings();
        let lang = self.cfg.lang_for(&s);
        let ev = test_event(&s);
        let content = compose_in(&self.cfg, std::slice::from_ref(&ev), 0, lang);
        let res = deliver(&self.client, &self.cfg, &content).await;
        let rec = AlertRecord {
            ts: now_ms(),
            kinds: vec![AlertKind::Test],
            title: Some(ev.title_text_in(lang)),
            text: content,
            delivered: res.is_ok(),
            error: res.err(),
            reason: None,
            photo: false,
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

/// The test message: what a card looks like and what is set.
pub fn test_event(s: &AlertSettings) -> AlertEvent {
    let q = &s.quiet_hours;
    AlertEvent::from_msg(
        "test",
        Msg::Test {
            on: AlertCategory::ALL.iter().filter(|c| s.enabled(**c)).count(),
            total: AlertCategory::ALL.len(),
            quiet: q.enabled.then(|| (q.start.clone(), q.end.clone())),
            hour_pct: s.big_moves.hour_pct,
            day_pct: s.big_moves.day_pct,
        },
    )
}

/// Wait up to `batch_wait` for more events after the first.
async fn gather(first: AlertEvent, rx: &mut mpsc::Receiver<AlertEvent>, wait: Duration) -> Vec<AlertEvent> {
    let mut batch = vec![first];
    let until = tokio::time::Instant::now() + wait;
    while batch.len() < 100 {
        match tokio::time::timeout_at(until, rx.recv()).await {
            Ok(Some(ev)) => batch.push(ev),
            _ => break,
        }
    }
    batch
}

/// What one pass of the sender decided: what goes out now, and what is held
/// back and why. Pure, so it can be tested without a network.
#[derive(Debug, Default)]
pub struct Sorted {
    pub send: Vec<AlertEvent>,
    pub muted: Vec<AlertEvent>,
    pub quiet: Vec<AlertEvent>,
    /// Switched off in Settings: dropped, not recorded.
    pub off: usize,
}

/// Sort fresh events by the switches, the mute and quiet hours. Urgent ones
/// always go out.
pub fn sort_events(events: Vec<AlertEvent>, settings: &AlertSettings, muted: bool, now: i64) -> Sorted {
    let quiet = settings.quiet_hours.contains(now);
    let mut s = Sorted::default();
    for e in events {
        if e.is_urgent() {
            s.send.push(e);
        } else if e.category().is_some_and(|c| !settings.enabled(c)) {
            s.off += 1;
        } else if muted {
            s.muted.push(e);
        } else if quiet {
            s.quiet.push(e);
        } else {
            s.send.push(e);
        }
    }
    s
}

/// What quiet hours held back, added up for the morning note: the fills per
/// autopilot, every other alert per kind (a lab post per switch). However
/// long the night, the note stays a line per autopilot and per kind.
#[derive(Debug, Clone, Default, PartialEq)]
pub struct Overnight {
    pub fills: Vec<HeldFills>,
    pub others: Vec<HeldGroup>,
    /// When the first was held, for the note's key.
    pub first_ms: Option<i64>,
}

impl Overnight {
    pub fn is_empty(&self) -> bool {
        self.fills.is_empty() && self.others.is_empty()
    }

    /// How many alerts it holds: every fill and every other alert.
    pub fn count(&self) -> usize {
        i18n::overnight_count(&self.fills, &self.others)
    }

    /// Hold one more alert back.
    pub fn hold(&mut self, ev: &AlertEvent, now: i64, lang: Lang) {
        self.first_ms.get_or_insert(now);
        if let Some(t) = &ev.trade {
            let f = match self.fills.iter_mut().position(|f| f.book == t.book) {
                Some(i) => &mut self.fills[i],
                None => {
                    self.fills.push(HeldFills { book: t.book.clone(), ..Default::default() });
                    self.fills.last_mut().expect("just pushed")
                }
            };
            f.rebalance |= t.rebalance;
            if t.buy {
                f.buys += 1;
                f.bought += t.qty * t.price;
            } else {
                f.sells += 1;
                f.sold += t.qty * t.price;
            }
            f.fees += t.fee;
            f.realized += t.realized;
            return;
        }
        let category = (ev.kind == AlertKind::Event).then(|| ev.category()).flatten();
        let title = ev.title_text_in(lang);
        match self.others.iter_mut().find(|g| g.kind == ev.kind && g.category == category) {
            Some(g) => {
                g.n += 1;
                g.last = title;
            }
            None => self.others.push(HeldGroup { kind: ev.kind, category, n: 1, last: title }),
        }
    }
}

/// The morning note: what quiet hours held back, one line per autopilot for
/// its fills and one per other kind of alert.
pub fn overnight_event(night: &Overnight, settings: &AlertSettings) -> AlertEvent {
    AlertEvent::from_msg(
        format!("overnight:{}", night.first_ms.unwrap_or(0)),
        Msg::Overnight {
            fills: night.fills.clone(),
            others: night.others.clone(),
            start: settings.quiet_hours.start.clone(),
            end: settings.quiet_hours.end.clone(),
            timezone: settings.quiet_hours.timezone.clone(),
        },
    )
}

/// The fills of each autopilot, held until it has been quiet for a while,
/// so that a rebalance worked through many partial maker fills is one card.
/// Pure: the sender asks it what is due. Nothing is dropped: a book that
/// collects [`FILLS_MAX`] fills goes out at once.
#[derive(Debug, Default)]
pub struct FillBuffer {
    books: Vec<PendingFills>,
}

#[derive(Debug)]
struct PendingFills {
    book: String,
    first_ms: i64,
    last_ms: i64,
    events: Vec<AlertEvent>,
}

/// One autopilot's fills are posted once this many have gathered.
pub const FILLS_MAX: usize = 200;

impl FillBuffer {
    /// Whether an event waits here: a fill that is not urgent.
    pub fn takes(ev: &AlertEvent) -> bool {
        ev.trade.is_some() && !ev.is_urgent()
    }

    pub fn is_empty(&self) -> bool {
        self.books.is_empty()
    }

    /// Fills waiting, all books.
    pub fn len(&self) -> usize {
        self.books.iter().map(|b| b.events.len()).sum()
    }

    pub fn add(&mut self, ev: AlertEvent, now: i64) {
        let book = ev.trade.as_ref().map(|t| t.book.clone()).unwrap_or_default();
        match self.books.iter_mut().find(|b| b.book == book) {
            Some(b) => {
                b.last_ms = now;
                b.events.push(ev);
            }
            None => self.books.push(PendingFills { book, first_ms: now, last_ms: now, events: vec![ev] }),
        }
    }

    /// When the next book is due, epoch ms.
    pub fn next_due(&self, quiet_ms: i64, max_ms: i64) -> Option<i64> {
        self.books.iter().map(|b| (b.last_ms + quiet_ms).min(b.first_ms + max_ms)).min()
    }

    /// The fills of every book that is due: quiet for `quiet_ms`, waiting
    /// for `max_ms` since its first fill, or full. In the order they came.
    pub fn due(&mut self, now: i64, quiet_ms: i64, max_ms: i64) -> Vec<AlertEvent> {
        let mut out = Vec::new();
        let mut keep = Vec::new();
        for b in self.books.drain(..) {
            if now - b.last_ms >= quiet_ms || now - b.first_ms >= max_ms || b.events.len() >= FILLS_MAX {
                out.extend(b.events);
            } else {
                keep.push(b);
            }
        }
        self.books = keep;
        out
    }

    /// Everything waiting, due or not (the sender is shutting down).
    pub fn drain(&mut self) -> Vec<AlertEvent> {
        self.books.drain(..).flat_map(|b| b.events).collect()
    }
}

async fn run(cfg: Arc<AlertConfig>, client: reqwest::Client, log: AlertLog, mut rx: mpsc::Receiver<AlertEvent>) {
    let mut throttle = Throttle::new(cfg.dedup, cfg.max_per_hour);
    let mut failing = false;
    // Held back in quiet hours, added up for the morning note.
    let mut overnight = Overnight::default();
    // Fills wait here until their autopilot has been quiet for a while.
    let mut fills = FillBuffer::default();
    let quiet_ms = cfg.fill_quiet.as_millis() as i64;
    let max_ms = cfg.fill_max.as_millis() as i64;
    let mut wake = tokio::time::interval(cfg.wake);
    wake.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);
    let mut closing = false;
    loop {
        // Wake for the next book of fills that falls due.
        let due_in = fills.next_due(quiet_ms, max_ms).map(|t| Duration::from_millis((t - now_ms()).max(0) as u64));
        let batch = tokio::select! {
            ev = rx.recv() => match ev {
                Some(first) => gather(first, &mut rx, cfg.batch_wait).await,
                None => {
                    closing = true;
                    Vec::new()
                }
            },
            _ = wake.tick() => Vec::new(),
            _ = tokio::time::sleep(due_in.unwrap_or(Duration::from_secs(3600))), if due_in.is_some() => Vec::new(),
        };
        let now = now_ms();
        let settings = log.settings();
        let lang = cfg.lang_for(&settings);
        let muted = log.is_muted(now);
        let mut out: Vec<AlertEvent> = Vec::new();
        // Quiet hours are over: say what they held back, once.
        if !overnight.is_empty() && !settings.quiet_hours.contains(now) && !muted {
            out.push(overnight_event(&overnight, &settings));
            overnight = Overnight::default();
        }
        let mut ready: Vec<AlertEvent> = Vec::new();
        for e in batch.into_iter().filter(|e| throttle.fresh(&e.key, now)) {
            if FillBuffer::takes(&e) {
                fills.add(e, now);
            } else {
                ready.push(e);
            }
        }
        ready.extend(if closing { fills.drain() } else { fills.due(now, quiet_ms, max_ms) });
        if !ready.is_empty() {
            let sorted = sort_events(ready, &settings, muted, now);
            if !sorted.muted.is_empty() {
                log.record(held_back(&cfg, &sorted.muted, now, "muted", lang));
            }
            if !sorted.quiet.is_empty() {
                log.record(held_back(&cfg, &sorted.quiet, now, "quiet", lang));
                for e in &sorted.quiet {
                    overnight.hold(e, now, lang);
                }
            }
            out.extend(sorted.send);
        }
        if out.is_empty() {
            if closing {
                break;
            }
            continue;
        }
        if out.iter().any(AlertEvent::is_urgent) {
            throttle.count(now);
        } else if !throttle.may_post(now) {
            throttle.suppressed += out.len();
            log.record(held_back(&cfg, &out, now, "hourlyLimit", lang));
            continue;
        }
        // A picture goes as a photo of its own, its card the caption.
        let (photos, texts): (Vec<AlertEvent>, Vec<AlertEvent>) =
            out.into_iter().partition(|e| e.image.is_some() && cfg.format == AlertFormat::Telegram);
        let mut results = Vec::new();
        if !texts.is_empty() {
            let content = compose_in(&cfg, &texts, throttle.suppressed, lang);
            throttle.suppressed = 0;
            let res = deliver(&client, &cfg, &content).await;
            log.record(AlertRecord {
                ts: now,
                kinds: texts.iter().map(|e| e.kind).collect(),
                title: first_title(&texts, lang),
                text: content,
                delivered: res.is_ok(),
                error: res.clone().err(),
                reason: None,
                photo: false,
            });
            results.push(res);
        }
        for ev in &photos {
            let caption = caption_of(&cfg, ev, lang);
            let res = match &ev.image {
                Some(png) => deliver_photo(&client, &cfg, png, &caption).await,
                None => deliver(&client, &cfg, &caption).await,
            };
            log.record(AlertRecord {
                ts: now,
                kinds: vec![ev.kind],
                title: Some(ev.title_text_in(lang)),
                text: caption,
                delivered: res.is_ok(),
                error: res.clone().err(),
                reason: None,
                photo: true,
            });
            results.push(res);
        }
        for res in results {
            match res {
                Ok(()) => {
                    if failing {
                        tracing::info!("alert destination works again");
                        failing = false;
                    }
                }
                Err(why) => {
                    if !failing {
                        tracing::warn!("alert destination failed ({why}); further failures are not logged until it works again");
                        failing = true;
                    }
                }
            }
        }
    }
}

/// The record of events that were not posted, and why.
fn held_back(cfg: &AlertConfig, events: &[AlertEvent], now: i64, reason: &str, lang: Lang) -> AlertRecord {
    AlertRecord {
        ts: now,
        kinds: events.iter().map(|e| e.kind).collect(),
        title: first_title(events, lang),
        text: compose_in(cfg, events, 0, lang),
        delivered: false,
        error: None,
        reason: Some(reason.into()),
        photo: false,
    }
}

/// The title of a post's first card, as the app lists it.
fn first_title(events: &[AlertEvent], lang: Lang) -> Option<String> {
    cards_of_in(events, lang).first().map(|c| c.title.clone())
}

/// The cards of a batch: fills of the same autopilot together in one table,
/// every other event a card of its own, in the order they came.
pub fn cards_of(events: &[AlertEvent]) -> Vec<Card> {
    cards_of_in(events, Lang::En)
}

/// [`cards_of`] in a language.
pub fn cards_of_in(events: &[AlertEvent], lang: Lang) -> Vec<Card> {
    let trades: Vec<&TradeLine> = events.iter().filter_map(|e| e.trade.as_ref()).collect();
    let mut cards = Vec::new();
    let mut trades_done = false;
    for e in events {
        if e.trade.is_some() {
            if !trades_done {
                cards.extend(trade_cards_in(&trades, lang));
                trades_done = true;
            }
            continue;
        }
        cards.push(e.card_in(lang));
    }
    cards
}

/// The text of one post: the cards, the engine's name in the footer and how
/// many alerts the hourly limit held back, fitted to the destination's limit.
/// In the environment's language, else English; the sender uses
/// [`compose_in`] with the language of the settings.
pub fn compose(cfg: &AlertConfig, events: &[AlertEvent], suppressed: usize) -> String {
    compose_in(cfg, events, suppressed, cfg.lang.unwrap_or_default())
}

/// [`compose`] in a language.
pub fn compose_in(cfg: &AlertConfig, events: &[AlertEvent], suppressed: usize, lang: Lang) -> String {
    let mut cards = cards_of_in(events, lang);
    if let Some(last) = cards.last_mut() {
        let mut foot: Vec<String> = Vec::new();
        if let Some(f) = last.footer.take() {
            foot.push(f);
        }
        if suppressed > 0 {
            foot.push(i18n::held_by_limit(lang, suppressed));
        }
        if !cfg.prefix.is_empty() {
            foot.push(cfg.prefix.clone());
        }
        last.footer = (!foot.is_empty()).then(|| foot.join(" · "));
    }
    render_post(&cards, cfg.format, cfg.format.limit())
}

/// A photo's caption: its card, under Telegram's 1024 characters.
fn caption_of(cfg: &AlertConfig, ev: &AlertEvent, lang: Lang) -> String {
    let mut c = ev.card_in(lang);
    if !cfg.prefix.is_empty() {
        c.footer = Some(cfg.prefix.clone());
    }
    render_post(&[c], cfg.format, 1000)
}

/// One POST. The error never carries the URL, the token or the chat.
/// Telegram refusing the HTML (a 400) gets the same text once more as plain
/// text, so a markup slip never loses an alert.
async fn deliver(client: &reqwest::Client, cfg: &AlertConfig, content: &str) -> Result<(), String> {
    let first = post_json(client, cfg, &cfg.body(content)).await;
    match first {
        Err(e) if e == "HTTP 400" && cfg.format == AlertFormat::Telegram => {
            let mut b = serde_json::json!({ "text": truncate(&card::plain(content), cfg.format.limit()) });
            if let Some(chat) = &cfg.chat_id {
                b["chat_id"] = serde_json::json!(chat);
            }
            post_json(client, cfg, &b).await
        }
        other => other,
    }
}

async fn post_json(client: &reqwest::Client, cfg: &AlertConfig, body: &serde_json::Value) -> Result<(), String> {
    let resp = client
        .post(&cfg.url)
        .json(body)
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

/// The multipart body of a `sendPhoto`: chat, caption in HTML, the picture.
pub fn photo_body(chat: &str, caption: &str, image: &[u8], boundary: &str) -> Vec<u8> {
    let (name, mime) = if image.starts_with(&[0xFF, 0xD8]) { ("chart.jpg", "image/jpeg") } else { ("chart.png", "image/png") };
    let mut b: Vec<u8> = Vec::with_capacity(image.len() + caption.len() + 512);
    for (k, v) in [("chat_id", chat), ("caption", caption), ("parse_mode", "HTML")] {
        b.extend_from_slice(format!("--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n").as_bytes());
    }
    b.extend_from_slice(
        format!("--{boundary}\r\nContent-Disposition: form-data; name=\"photo\"; filename=\"{name}\"\r\nContent-Type: {mime}\r\n\r\n")
            .as_bytes(),
    );
    b.extend_from_slice(image);
    b.extend_from_slice(format!("\r\n--{boundary}--\r\n").as_bytes());
    b
}

/// A photo with its caption through Telegram's `sendPhoto`. A refused photo
/// (too large, not a picture) still gets its caption out as a message.
async fn deliver_photo(client: &reqwest::Client, cfg: &AlertConfig, image: &[u8], caption: &str) -> Result<(), String> {
    let boundary = format!("pythia{}", uuid::Uuid::new_v4().simple());
    let body = photo_body(cfg.chat_id.as_deref().unwrap_or_default(), caption, image, &boundary);
    let resp = client
        .post(cfg.photo_url())
        .header("content-type", format!("multipart/form-data; boundary={boundary}"))
        .body(body)
        .send()
        .await
        .map_err(|e| scrub(&e.without_url().to_string(), cfg))?;
    let status = resp.status();
    if status.is_success() {
        return Ok(());
    }
    if status.as_u16() == 400 {
        return deliver(client, cfg, caption).await.map_err(|e| format!("photo refused, caption sent instead failed: {e}"));
    }
    Err(format!("HTTP {}", status.as_u16()))
}

/// An error message with every secret part of the destination taken out: the
/// URL, each longer piece of it (a webhook id, a bot token) and the chat id.
pub fn scrub(msg: &str, cfg: &AlertConfig) -> String {
    let photo = cfg.photo_url();
    let mut secrets: Vec<&str> = vec![cfg.url.as_str(), photo.as_str()];
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
        for (name, model, total, hits) in [
            ("vol", i18n::DriftModel::Vol, status.drift.len(), vol),
            ("picks", i18n::DriftModel::Picks, status.picks.drift.len(), picks),
        ] {
            let now = !hits.is_empty();
            let was = self.muted.insert(name, now).unwrap_or(false);
            if now && !was {
                out.push(AlertEvent::from_msg(format!("drift:{name}:on"), Msg::DriftOn { model, total, hits }));
            } else if was && !now {
                out.push(AlertEvent::from_msg(format!("drift:{name}:off"), Msg::DriftOff { model }).with_emoji("✅"));
            }
        }
        out
    }
}

/// Escape for Telegram HTML; re-exported for hosts that build their own text.
pub fn escape_html(s: &str) -> String {
    esc(s)
}

#[cfg(test)]
#[path = "alerts_tests.rs"]
mod tests;

#[cfg(test)]
#[path = "alerts_card_tests.rs"]
mod card_tests;

#[cfg(test)]
#[path = "alerts_i18n_tests.rs"]
mod i18n_tests;
