//! The language of what goes to the owner's chat.
//!
//! The app, the journal and the API stay in English; only the cards posted to
//! Telegram (or the alert webhook) follow [`Lang`]. The setting lives in the
//! alert settings (`language`, saved with the engine state and written for the
//! lab as `reports/notify/settings.json`); `PYTHIA_ALERT_LANG` overrides it.
//!
//! Every engine message is a [`Msg`]: the numbers and names it needs, rendered
//! per language by the catalog below ([`Msg::text`] and [`Msg::card_text`]).
//! A new message is one more variant and one arm per language. Numbers shown
//! to the owner follow the language too: `$1,234.56` and `+3.20 %` in English,
//! `1.234,56 $` and `+3,20 %` in German; dates as `Thu 15 Oct` or `Do 15. Okt`,
//! times in Europe/Berlin.

use chrono::{Datelike, TimeZone, Timelike};
use serde::{Deserialize, Serialize};

use super::card::{self, Row, Table};
use super::{AlertCategory, AlertKind};

/// The variable that overrides the language in the settings.
pub const LANG_ENV: &str = "PYTHIA_ALERT_LANG";

/// The language of the messages to the owner's chat.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Default, Serialize)]
#[serde(rename_all = "lowercase")]
pub enum Lang {
    #[default]
    En,
    De,
}

impl<'de> Deserialize<'de> for Lang {
    /// Lenient: an unknown value is English, so an old or hand-edited save
    /// never loses the rest of the settings.
    fn deserialize<D: serde::Deserializer<'de>>(d: D) -> Result<Self, D::Error> {
        let s = String::deserialize(d)?;
        Ok(Lang::parse(&s).unwrap_or_default())
    }
}

impl Lang {
    pub const ALL: [Lang; 2] = [Lang::En, Lang::De];

    /// The id in the API, the settings file and the lab.
    pub fn id(self) -> &'static str {
        match self {
            Lang::En => "en",
            Lang::De => "de",
        }
    }

    /// Its name in its own language, for the switch in Settings.
    pub fn label(self) -> &'static str {
        match self {
            Lang::En => "English",
            Lang::De => "Deutsch",
        }
    }

    /// `en`, `de`, `english`, `deutsch`, `german`, `de-DE`; case ignored.
    pub fn parse(s: &str) -> Option<Self> {
        let k = s.trim().to_ascii_lowercase();
        let k = k.split(['-', '_']).next().unwrap_or_default();
        match k {
            "en" | "english" | "englisch" => Some(Lang::En),
            "de" | "deutsch" | "german" => Some(Lang::De),
            _ => None,
        }
    }

    /// `PYTHIA_ALERT_LANG`, when it names a language.
    pub fn from_env() -> Option<Self> {
        Self::from_lookup(|k| std::env::var(k).ok())
    }

    pub fn from_lookup(get: impl Fn(&str) -> Option<String>) -> Option<Self> {
        get(LANG_ENV).and_then(|v| Lang::parse(&v))
    }
}

// ── numbers and dates ───────────────────────────────────────────────────────

/// An English number in German: `1,234.56` as `1.234,56`, `n/a` as `k. A.`.
fn de_digits(s: &str) -> String {
    if s == "n/a" {
        return "k. A.".into();
    }
    s.chars()
        .map(|c| match c {
            ',' => '.',
            '.' => ',',
            c => c,
        })
        .collect::<String>()
        .replace("n/a", "k. A.")
}

/// An English amount (`-$1,234.56`, `+$12.30`) in German: `-1.234,56 $`.
fn de_money(en: &str) -> String {
    if en == "n/a" {
        return "k. A.".into();
    }
    let (sign, rest) = match en.chars().next() {
        Some(c @ ('-' | '+')) => (c.to_string(), &en[1..]),
        _ => (String::new(), en),
    };
    format!("{sign}{} $", de_digits(rest.trim_start_matches('$')))
}

/// `12345.678` with `dp` decimals and thousands separators.
pub fn num(lang: Lang, v: f64, dp: usize) -> String {
    let t = card::thousands(v, dp);
    match lang {
        Lang::En => t,
        Lang::De => de_digits(&t),
    }
}

/// An amount with `dp` decimals: `$12,345.68` or `12.345,68 $`.
pub fn money(lang: Lang, v: f64, dp: usize) -> String {
    let t = card::money(v, dp);
    match lang {
        Lang::En => t,
        Lang::De => de_money(&t),
    }
}

/// An amount with cents.
pub fn usd(lang: Lang, v: f64) -> String {
    money(lang, v, 2)
}

/// `+$12.30` or `+12,30 $`.
pub fn signed_usd(lang: Lang, v: f64) -> String {
    let t = card::signed_usd(v);
    match lang {
        Lang::En => t,
        Lang::De => de_money(&t),
    }
}

/// `+1.20 %` or `+1,20 %`.
pub fn signed_pct(lang: Lang, v: f64, dp: usize) -> String {
    let t = card::signed_pct(v, dp);
    match lang {
        Lang::En => t,
        Lang::De => de_digits(&t),
    }
}

/// A price, fewer decimals the larger it is.
pub fn price(lang: Lang, v: f64) -> String {
    let t = card::price(v);
    match lang {
        Lang::En => t,
        Lang::De => de_money(&t),
    }
}

/// A coin amount without trailing zeros.
pub fn qty(lang: Lang, v: f64) -> String {
    let t = card::qty(v);
    match lang {
        Lang::En => t,
        Lang::De => de_digits(&t),
    }
}

/// Points against a benchmark: `+1.23 pts` or `+1,23 Pkt.`.
pub fn pts(lang: Lang, v: f64) -> String {
    match lang {
        Lang::En => format!("{v:+.2} pts"),
        Lang::De => format!("{} Pkt.", de_digits(&format!("{v:+.2}"))),
    }
}

/// A plain number with `dp` decimals and no grouping: `2.5` or `2,5`.
pub fn plain(lang: Lang, v: f64, dp: usize) -> String {
    let t = format!("{v:.dp$}");
    match lang {
        Lang::En => t,
        Lang::De => t.replace('.', ","),
    }
}

/// A % as the engine writes it in its rules, without trailing zeros: `2.5`,
/// `10`, never `-0`.
pub fn short_pct(lang: Lang, x: f64) -> String {
    let x = if x.abs() < 0.005 { 0.0 } else { x };
    let t = format!("{x:.2}");
    let t = t.trim_end_matches('0').trim_end_matches('.').to_string();
    match lang {
        Lang::En => t,
        Lang::De => t.replace('.', ","),
    }
}

/// Dollars rounded to the cent as the engine writes them in its rules and
/// reasons: `$1,234.50`, never `-$0.00`.
pub fn cents(lang: Lang, x: f64) -> String {
    let c = (x.abs() * 100.0).round() as u128;
    let neg = x < 0.0 && c > 0;
    let (whole, frac) = (c / 100, c % 100);
    let digits = whole.to_string();
    let mut grouped = String::new();
    for (k, ch) in digits.chars().enumerate() {
        if k > 0 && (digits.len() - k) % 3 == 0 {
            grouped.push(',');
        }
        grouped.push(ch);
    }
    let en = format!("{}${grouped}.{frac:02}", if neg { "-" } else { "" });
    match lang {
        Lang::En => en,
        Lang::De => de_money(&en),
    }
}

const WEEKDAYS_EN: [&str; 7] = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const WEEKDAYS_DE: [&str; 7] = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"];
const MONTHS_EN: [&str; 12] = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const MONTHS_DE: [&str; 12] = ["Jan", "Feb", "Mär", "Apr", "Mai", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"];

/// A day as the owner reads it: `Thu 15 Oct` or `Do 15. Okt`.
pub fn day_label<T: Datelike>(lang: Lang, d: &T) -> String {
    let wd = d.weekday().num_days_from_monday() as usize;
    let m = d.month0() as usize;
    match lang {
        Lang::En => format!("{} {} {}", WEEKDAYS_EN[wd], d.day(), MONTHS_EN[m]),
        Lang::De => format!("{} {}. {}", WEEKDAYS_DE[wd], d.day(), MONTHS_DE[m]),
    }
}

/// A moment for a German message: `Do 15. Okt, 16:00` in Europe/Berlin.
pub fn berlin_when(lang: Lang, ms: i64) -> String {
    let Some(t) = chrono::Utc.timestamp_millis_opt(ms).single() else { return String::new() };
    let local = t.with_timezone(&chrono_tz::Europe::Berlin);
    format!("{}, {:02}:{:02}", day_label(lang, &local), local.hour(), local.minute())
}

/// `1 position` or `3 positions` in the language's words.
fn count(n: u64, one: &str, many: &str) -> String {
    format!("{n} {}", if n == 1 { one } else { many })
}

// ── words ───────────────────────────────────────────────────────────────────

/// The title of an alert kind's card when the message gives none.
pub fn kind_label(kind: AlertKind, lang: Lang) -> &'static str {
    match lang {
        Lang::En => kind.label(),
        Lang::De => match kind {
            AlertKind::AutopilotStarted => "Autopilot gestartet",
            AlertKind::AutopilotStopped => "Autopilot gestoppt",
            AlertKind::StopRuleHit => "Stop-Regel erreicht",
            AlertKind::FloorHit => "Untergrenze erreicht",
            AlertKind::KillSwitch => "Not-Aus",
            AlertKind::DailyLossBrake => "Tagesverlust-Bremse",
            AlertKind::OrderRejects => "Orders abgelehnt",
            AlertKind::ReconcileMismatch => "Abgleich weicht ab",
            AlertKind::DataStale => "Marktdaten veraltet",
            AlertKind::ModelDrift => "Modell-Drift",
            AlertKind::Trade => "Ausführung",
            AlertKind::BigMove => "Starke Bewegung",
            AlertKind::Event => "Labor",
            AlertKind::Overnight => "Ruhezeit vorbei",
            AlertKind::Test => "Test",
        },
    }
}

/// The small words of the cards and posts.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Word {
    Bought,
    Sold,
    Buy,
    Sell,
    Amount,
    Price,
    /// The average price of several fills.
    AvgPrice,
    Value,
    Fee,
    Fees,
    Realised,
    Side,
    Coin,
    Rebalance,
    Time,
    Alert,
    /// An experimental lab book (failed the lab's deflation test).
    Experiment,
    /// The same, short, after a coin in a rebalance table.
    ExperimentShort,
}

pub fn word(w: Word, lang: Lang) -> &'static str {
    match (lang, w) {
        (Lang::En, Word::Bought) => "bought",
        (Lang::En, Word::Sold) => "sold",
        (Lang::En, Word::Buy) => "Buy",
        (Lang::En, Word::Sell) => "Sell",
        (Lang::En, Word::Amount) => "Amount",
        (Lang::En, Word::Price) => "Price",
        (Lang::En, Word::AvgPrice) => "Avg price",
        (Lang::De, Word::AvgPrice) => "Ø Preis",
        (Lang::En, Word::Value) => "Value",
        (Lang::En, Word::Fee) => "Fee",
        (Lang::En, Word::Fees) => "Fees",
        (Lang::En, Word::Realised) => "Realised",
        (Lang::En, Word::Side) => "Side",
        (Lang::En, Word::Coin) => "Coin",
        (Lang::En, Word::Rebalance) => "Rebalance",
        (Lang::En, Word::Time) => "Time",
        (Lang::En, Word::Alert) => "Alert",
        (Lang::De, Word::Bought) => "kaufte",
        (Lang::De, Word::Sold) => "verkaufte",
        (Lang::De, Word::Buy) => "Kauf",
        (Lang::De, Word::Sell) => "Verkauf",
        (Lang::De, Word::Amount) => "Menge",
        (Lang::De, Word::Price) => "Preis",
        (Lang::De, Word::Value) => "Wert",
        (Lang::De, Word::Fee) => "Gebühr",
        (Lang::De, Word::Fees) => "Gebühren",
        (Lang::De, Word::Realised) => "Realisiert",
        (Lang::De, Word::Side) => "Richtung",
        (Lang::De, Word::Coin) => "Coin",
        (Lang::De, Word::Rebalance) => "Umschichtung",
        (Lang::De, Word::Time) => "Zeit",
        (Lang::De, Word::Alert) => "Meldung",
        (Lang::En, Word::Experiment) => "experiment",
        (Lang::En, Word::ExperimentShort) => "exp",
        (Lang::De, Word::Experiment) => "Experiment",
        (Lang::De, Word::ExperimentShort) => "Exp.",
    }
}

/// The footer of a trade card for an experimental lab book: the mode, then
/// what an experiment is.
pub fn experiment_footer(mode: &str, lang: Lang) -> String {
    let m = mode_footer(mode, lang);
    match lang {
        Lang::En => format!("{m} · experiment: a rule that failed the lab's deflation test"),
        Lang::De => format!("{m} · Experiment: eine Regel, die den Deflationstest des Labors nicht bestanden hat"),
    }
}

/// The trading mode under a trade card.
pub fn mode_footer(mode: &str, lang: Lang) -> String {
    match (lang, mode) {
        (Lang::En, "live") => "Live: real money".into(),
        (Lang::En, "live test") => "LIVE TEST: real money, capped, unproven strategy".into(),
        (Lang::De, "live test") => "LIVE TEST: echtes Geld, gedeckelt, unbewiesene Strategie".into(),
        (Lang::En, "demo") => "Demo: virtual money at the venue".into(),
        (Lang::En, "paper") => "Paper".into(),
        (Lang::De, "live") => "Live: echtes Geld".into(),
        (Lang::De, "demo") => "Demo: virtuelles Geld beim Handelsplatz".into(),
        (Lang::De, "paper") => "Paper".into(),
        (_, other) => other.to_string(),
    }
}

/// `3 fills in 2 coins: bought $1,200.00, sold $800.00.` for a batch of fills
/// (`coins` the lines of its table: one per coin and side).
pub fn fills_summary(lang: Lang, n: usize, coins: usize, bought: f64, sold: f64) -> String {
    let mut parts = Vec::new();
    match lang {
        Lang::En => {
            if bought > 0.0 {
                parts.push(format!("bought {}", usd(lang, bought)));
            }
            if sold > 0.0 {
                parts.push(format!("sold {}", usd(lang, sold)));
            }
            let lines = if coins < n { format!(" in {coins} lines") } else { String::new() };
            format!("{n} {}{lines}: {}.", if n == 1 { "fill" } else { "fills" }, parts.join(", "))
        }
        Lang::De => {
            if bought > 0.0 {
                parts.push(format!("gekauft für {}", usd(lang, bought)));
            }
            if sold > 0.0 {
                parts.push(format!("verkauft für {}", usd(lang, sold)));
            }
            let lines = if coins < n { format!(" in {coins} Zeilen") } else { String::new() };
            format!("{}{lines}: {}.", count(n as u64, "Ausführung", "Ausführungen"), parts.join(", "))
        }
    }
}

/// The title of a batch of fills that is not a rebalance.
pub fn fills_title(lang: Lang, n: usize, book: &str) -> String {
    match lang {
        Lang::En => format!("{n} fills · {book}"),
        Lang::De => format!("{n} Ausführungen · {book}"),
    }
}

/// How many alerts a morning note stands for: every fill and every other alert.
pub fn overnight_count(fills: &[HeldFills], others: &[HeldGroup]) -> usize {
    fills.iter().map(|f| f.buys + f.sells).sum::<usize>() + others.iter().map(|g| g.n).sum::<usize>()
}

/// A switch in Settings by its name in the language, for the morning note.
pub fn category_label(c: AlertCategory, lang: Lang) -> &'static str {
    match lang {
        Lang::En => c.label(),
        Lang::De => match c {
            AlertCategory::Trades => "Trades",
            AlertCategory::Rebalances => "Umschichtungen",
            AlertCategory::DailyPnl => "Tagesbericht",
            AlertCategory::BigMoves => "Starke Bewegungen",
            AlertCategory::Autopilot => "Autopilot-Ereignisse",
            AlertCategory::Risk => "Risiko",
            AlertCategory::Venue => "Handelsplatz und Daten",
            AlertCategory::Models => "Modelle",
            AlertCategory::Studies => "Studien und Fabrik",
            AlertCategory::Listings => "Neue Listungen",
            AlertCategory::Trending => "Trends",
            AlertCategory::Cs2 => "CS2",
            AlertCategory::Pokemon => "Pokémon",
            AlertCategory::Weekly => "Wochenbericht",
        },
    }
}

/// The fills of one autopilot that quiet hours held back, added up.
#[derive(Debug, Clone, Default, PartialEq)]
pub struct HeldFills {
    /// The autopilot's name.
    pub book: String,
    /// Some of them were part of a rebalance.
    pub rebalance: bool,
    pub buys: usize,
    pub sells: usize,
    /// What the buys cost and the sells brought, in $.
    pub bought: f64,
    pub sold: f64,
    pub fees: f64,
    pub realized: f64,
}

impl HeldFills {
    /// `Momentum: rebalance, 9 sells, 3 buys, sold $1,234, bought $567, fees $2.10`.
    pub fn line(&self, lang: Lang) -> String {
        let mut parts: Vec<String> = Vec::new();
        if self.rebalance {
            parts.push(match lang {
                Lang::En => "rebalance".into(),
                Lang::De => "Umschichtung".into(),
            });
        }
        let (sells, buys) = match lang {
            Lang::En => (count(self.sells as u64, "sell", "sells"), count(self.buys as u64, "buy", "buys")),
            Lang::De => (count(self.sells as u64, "Verkauf", "Verkäufe"), count(self.buys as u64, "Kauf", "Käufe")),
        };
        if self.sells > 0 {
            parts.push(sells);
        }
        if self.buys > 0 {
            parts.push(buys);
        }
        let (sold, bought, fees, realised) = match lang {
            Lang::En => ("sold", "bought", "fees", "realised"),
            Lang::De => ("verkauft", "gekauft", "Gebühren", "realisiert"),
        };
        if self.sells > 0 {
            parts.push(format!("{sold} {}", money(lang, self.sold, 0)));
        }
        if self.buys > 0 {
            parts.push(format!("{bought} {}", money(lang, self.bought, 0)));
        }
        if self.fees > 0.0 {
            parts.push(format!("{fees} {}", usd(lang, self.fees)));
        }
        if self.realized.abs() > 1e-9 {
            parts.push(format!("{realised} {}", signed_usd(lang, self.realized)));
        }
        format!("{}: {}", self.book, parts.join(", "))
    }
}

/// Other alerts quiet hours held back, of one kind (a lab post: of one
/// switch): how many, and the title of the newest.
#[derive(Debug, Clone, PartialEq)]
pub struct HeldGroup {
    pub kind: AlertKind,
    pub category: Option<AlertCategory>,
    pub n: usize,
    pub last: String,
}

impl HeldGroup {
    /// `Big move: 3, the last BTC +4.1 % in 1 h` or `Autopilot started: Momentum`.
    pub fn line(&self, lang: Lang) -> String {
        let label = match (self.kind, self.category) {
            (AlertKind::Event, Some(c)) => category_label(c, lang),
            (k, _) => kind_label(k, lang),
        };
        if self.n == 1 {
            return format!("{label}: {}", self.last);
        }
        match lang {
            Lang::En => format!("{label}: {}, the last {}", self.n, self.last),
            Lang::De => format!("{label}: {}, zuletzt {}", self.n, self.last),
        }
    }
}

/// What a post adds when it had to leave cards out.
pub fn more_alerts(lang: Lang, n: usize) -> String {
    match lang {
        Lang::En => format!("+{n} more alert(s) in the app"),
        Lang::De => format!("+{n} weitere in der App"),
    }
}

/// Under a table that had to be shortened.
pub fn more_rows(lang: Lang, n: usize) -> String {
    match lang {
        Lang::En => format!("+{n} more"),
        Lang::De => format!("+{n} weitere"),
    }
}

/// The footer note on what the hourly limit held back.
pub fn held_by_limit(lang: Lang, n: usize) -> String {
    match lang {
        Lang::En => format!("{n} more held back by the hourly limit"),
        Lang::De => format!("{n} weitere vom Stundenlimit zurückgehalten"),
    }
}

// ── the engine's messages ───────────────────────────────────────────────────

/// An autopilot's trading mode.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ApMode {
    Paper,
    Demo,
    Live,
    /// A capped real-money test with an unproven strategy.
    LiveTest,
}

impl ApMode {
    pub fn word(self, lang: Lang) -> &'static str {
        match (lang, self) {
            (Lang::En, ApMode::Paper) => "paper",
            (Lang::En, ApMode::Demo) => "demo",
            (_, ApMode::Live) => "LIVE",
            (Lang::En, ApMode::LiveTest) => "LIVE TEST (real money, capped)",
            (Lang::De, ApMode::LiveTest) => "LIVE TEST (echtes Geld, gedeckelt)",
            (Lang::De, ApMode::Paper) => "Paper",
            (Lang::De, ApMode::Demo) => "Demo",
        }
    }
}

/// An asset class in a portfolio's split.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum AssetClass {
    Crypto,
    UsShares,
    Predictions,
    /// Perpetual futures, long and short (demo or paper only).
    Perps,
}

impl AssetClass {
    /// As a heading: `Crypto`, `US shares`.
    pub fn label(self, lang: Lang) -> &'static str {
        match (lang, self) {
            (Lang::En, AssetClass::Crypto) => "Crypto",
            (Lang::En, AssetClass::UsShares) => "US shares",
            (Lang::En, AssetClass::Predictions) => "Prediction markets",
            (Lang::En, AssetClass::Perps) => "Perps (long and short)",
            (Lang::De, AssetClass::Crypto) => "Krypto",
            (Lang::De, AssetClass::UsShares) => "US-Aktien",
            (Lang::De, AssetClass::Predictions) => "Prognosemärkte",
            (Lang::De, AssetClass::Perps) => "Perps (long und short)",
        }
    }
}

/// Where an autopilot trades.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Place {
    /// Across asset classes.
    Portfolio,
    /// One venue, by its name (`Kraken`, `Alpaca`).
    Venue(String),
}

impl Place {
    pub fn text(&self, lang: Lang) -> String {
        match (lang, self) {
            (Lang::En, Place::Portfolio) => "crypto and US shares".into(),
            (Lang::De, Place::Portfolio) => "Krypto und US-Aktien".into(),
            (_, Place::Venue(v)) => v.clone(),
        }
    }
}

/// An autopilot's stop rules.
#[derive(Debug, Clone, PartialEq, Default)]
pub struct Rules {
    pub capital: f64,
    pub max_loss_pct: Option<f64>,
    pub max_loss_usd: Option<f64>,
    pub trailing_pct: Option<f64>,
    pub take_profit_pct: Option<f64>,
    /// At take profit: lock in half the gain and keep going (else finish).
    pub lock: bool,
    pub end_ms: Option<i64>,
}

impl Rules {
    /// The rules in plain words, `; ` between them.
    pub fn text(&self, lang: Lang) -> String {
        let x = self.capital;
        let (p, u) = (|v: f64| short_pct(lang, v), |v: f64| cents(lang, v));
        let mut parts: Vec<String> = Vec::new();
        if let Some(pc) = self.max_loss_pct {
            let eq = u(x * (1.0 - pc / 100.0));
            parts.push(match lang {
                Lang::En => format!("stops at a loss of {} % (equity {eq})", p(pc)),
                Lang::De => format!("stoppt bei {} % Verlust (Wert {eq})", p(pc)),
            });
        }
        if let Some(l) = self.max_loss_usd {
            parts.push(match lang {
                Lang::En => format!("stops at a loss of {} (equity {})", u(l), u(x - l)),
                Lang::De => format!("stoppt bei {} Verlust (Wert {})", u(l), u(x - l)),
            });
        }
        if let Some(pc) = self.trailing_pct {
            parts.push(match lang {
                Lang::En => format!("gives back at most {} % from its peak", p(pc)),
                Lang::De => format!("gibt höchstens {} % vom Höchststand ab", p(pc)),
            });
        }
        if let Some(pc) = self.take_profit_pct {
            let eq = u(x * (1.0 + pc / 100.0));
            parts.push(match (lang, self.lock) {
                (Lang::En, false) => format!("finishes at a profit of {} % (equity {eq})", p(pc)),
                (Lang::En, true) => {
                    format!("locks in half the gain at every {} % of profit (first at equity {eq}) and keeps going", p(pc))
                }
                (Lang::De, false) => format!("endet bei {} % Gewinn (Wert {eq})", p(pc)),
                (Lang::De, true) => {
                    format!("sichert bei jeweils {} % Gewinn die Hälfte (zuerst bei Wert {eq}) und läuft weiter", p(pc))
                }
            });
        }
        match self.end_ms {
            Some(ms) => match lang {
                Lang::En => {
                    if let Some(t) = chrono::DateTime::from_timestamp_millis(ms) {
                        parts.push(format!("ends {}", t.format("%Y-%m-%d %H:%M UTC")));
                    }
                }
                Lang::De => parts.push(format!("endet {}", berlin_when(lang, ms))),
            },
            None if self.take_profit_pct.is_none() || self.lock => parts.push(
                match lang {
                    Lang::En => "otherwise runs until you stop it",
                    Lang::De => "läuft sonst, bis du ihn stoppst",
                }
                .into(),
            ),
            None => {}
        }
        parts.join("; ")
    }
}

/// Why an autopilot stopped or finished.
#[derive(Debug, Clone, PartialEq)]
pub enum StopWhy {
    ByYou,
    TakeProfit { pct: f64, equity: f64, target: f64 },
    MaxLossPct { pct: f64, equity: f64, floor: f64 },
    MaxLossUsd { usd: f64, equity: f64, floor: f64 },
    Trailing { equity: f64, pct: f64, peak: f64, floor: f64 },
    LockedProfit { equity: f64, floor: f64 },
    EndTime,
}

impl StopWhy {
    /// The reason as a clause: `max loss of 5 % reached (equity …, floor …)`.
    pub fn text(&self, lang: Lang) -> String {
        let (p, u) = (|v: f64| short_pct(lang, v), |v: f64| cents(lang, v));
        match (lang, self) {
            (Lang::En, StopWhy::ByYou) => "stopped by you".into(),
            (Lang::En, StopWhy::TakeProfit { pct, equity, target }) => {
                format!("take profit of {} % reached (equity {}, target {})", p(*pct), u(*equity), u(*target))
            }
            (Lang::En, StopWhy::MaxLossPct { pct, equity, floor }) => {
                format!("max loss of {} % reached (equity {}, floor {})", p(*pct), u(*equity), u(*floor))
            }
            (Lang::En, StopWhy::MaxLossUsd { usd, equity, floor }) => {
                format!("max loss of {} reached (equity {}, floor {})", u(*usd), u(*equity), u(*floor))
            }
            (Lang::En, StopWhy::Trailing { equity, pct, peak, floor }) => format!(
                "trailing floor reached: equity {} gave back {} % from its peak of {} (floor {})",
                u(*equity),
                p(*pct),
                u(*peak),
                u(*floor)
            ),
            (Lang::En, StopWhy::LockedProfit { equity, floor }) => {
                format!("locked-in profit floor reached (equity {}, floor {})", u(*equity), u(*floor))
            }
            (Lang::En, StopWhy::EndTime) => "end time reached".into(),
            (Lang::De, StopWhy::ByYou) => "von dir gestoppt".into(),
            (Lang::De, StopWhy::TakeProfit { pct, equity, target }) => {
                format!("Take-Profit von {} % erreicht (Wert {}, Ziel {})", p(*pct), u(*equity), u(*target))
            }
            (Lang::De, StopWhy::MaxLossPct { pct, equity, floor }) => {
                format!("Höchstverlust von {} % erreicht (Wert {}, Untergrenze {})", p(*pct), u(*equity), u(*floor))
            }
            (Lang::De, StopWhy::MaxLossUsd { usd, equity, floor }) => {
                format!("Höchstverlust von {} erreicht (Wert {}, Untergrenze {})", u(*usd), u(*equity), u(*floor))
            }
            (Lang::De, StopWhy::Trailing { equity, pct, peak, floor }) => format!(
                "nachgezogene Untergrenze erreicht: Wert {} hat {} % vom Höchststand {} abgegeben (Untergrenze {})",
                u(*equity),
                p(*pct),
                u(*peak),
                u(*floor)
            ),
            (Lang::De, StopWhy::LockedProfit { equity, floor }) => {
                format!("Untergrenze für den gesicherten Gewinn erreicht (Wert {}, Untergrenze {})", u(*equity), u(*floor))
            }
            (Lang::De, StopWhy::EndTime) => "Endzeit erreicht".into(),
        }
    }
}

/// What happened to a stopped autopilot's positions and strategies: the first
/// thing said, as the card's footer.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum HaltFoot {
    Closed(u64),
    AtVenue(u64),
    WaitPrice(u64),
    /// Real positions, and live routing is not available.
    Stuck(u64),
    /// Demo or real positions whose exit waits for another book's order on
    /// the other side of the same symbol (a wash-trade guard).
    WaitOtherBook(u64),
    /// Positions whose route is waiting out a refusal from the venue.
    Refused(u64),
    /// Positions whose exit did not go out this tick for another reason.
    Retrying(u64),
    LeftOpen(u64),
    Paused(Vec<String>),
    Still(Vec<String>),
    Idle(Vec<String>),
}

impl HaltFoot {
    pub fn text(&self, lang: Lang) -> String {
        match (lang, self) {
            (Lang::En, HaltFoot::Closed(n)) => format!("Closed its {n} position(s)."),
            (Lang::En, HaltFoot::AtVenue(n)) => format!(
                "{n} close order(s) are at the venue; their fills are booked to the autopilot when the venue reports them."
            ),
            (Lang::En, HaltFoot::WaitPrice(n)) => format!(
                "{n} paper position(s) wait for a fresh price before they are closed: a stale price is not where the market is."
            ),
            (Lang::En, HaltFoot::Stuck(n)) => format!(
                "{n} real position(s) could not be closed yet because live routing is not available; they stay with the autopilot and are closed as soon as it is."
            ),
            (Lang::En, HaltFoot::WaitOtherBook(n)) => format!(
                "{n} position(s) wait for another autopilot's order in the same coin to finish (two orders on opposite sides of one account could meet as a wash trade); their exits go out as soon as it is done."
            ),
            (Lang::En, HaltFoot::Refused(n)) => format!(
                "{n} position(s) wait out a refusal from the venue before their exits are sent again; they stay with the autopilot until they are closed."
            ),
            (Lang::En, HaltFoot::Retrying(n)) => format!(
                "{n} position(s) are not closed yet; their exits are sent again at the next tick and booked to the autopilot when they fill."
            ),
            (Lang::En, HaltFoot::LeftOpen(n)) => format!(
                "Left its {n} position(s) open, now managed by their strategies' stops; its P&L counts them at their price now."
            ),
            (Lang::En, HaltFoot::Paused(l)) => format!("Paused its strategies: {}.", l.join(", ")),
            (Lang::En, HaltFoot::Still(l)) => {
                format!("Still running for the other autopilots, which are untouched: {}.", l.join(", "))
            }
            (Lang::En, HaltFoot::Idle(l)) => format!(
                "Idle again, waiting for the next autopilot: {} (it keeps receiving the lab's signal and trades only inside an autopilot).",
                l.join(", ")
            ),
            (Lang::De, HaltFoot::Closed(n)) => format!("{} geschlossen.", count(*n, "Position", "Positionen")),
            (Lang::De, HaltFoot::AtVenue(n)) => format!(
                "{} beim Handelsplatz; ihre Ausführungen werden dem Autopiloten gebucht, sobald der Handelsplatz sie meldet.",
                count(*n, "Schließorder liegt", "Schließorders liegen")
            ),
            (Lang::De, HaltFoot::WaitPrice(n)) => format!(
                "{} auf einen frischen Preis, bevor geschlossen wird: ein veralteter Preis ist nicht der Markt.",
                count(*n, "Paper-Position wartet", "Paper-Positionen warten")
            ),
            (Lang::De, HaltFoot::Stuck(n)) => format!(
                "{} noch nicht geschlossen werden, weil die Live-Anbindung nicht verfügbar ist; der Autopilot behält sie und schließt sie, sobald es geht.",
                count(*n, "echte Position konnte", "echte Positionen konnten")
            ),
            (Lang::De, HaltFoot::WaitOtherBook(n)) => format!(
                "{} auf die Order eines anderen Autopiloten in derselben Münze (zwei Orders auf entgegengesetzten Seiten eines Kontos könnten sich als Scheingeschäft treffen); ihre Ausstiege gehen raus, sobald sie fertig ist.",
                count(*n, "Position wartet", "Positionen warten")
            ),
            (Lang::De, HaltFoot::Refused(n)) => format!(
                "{} eine Ablehnung des Handelsplatzes ab, bevor ihre Ausstiege erneut gesendet werden; sie bleiben beim Autopiloten, bis sie geschlossen sind.",
                count(*n, "Position wartet", "Positionen warten")
            ),
            (Lang::De, HaltFoot::Retrying(n)) => format!(
                "{} noch nicht geschlossen; ihre Ausstiege werden beim nächsten Takt erneut gesendet und dem Autopiloten gebucht, sobald sie ausgeführt sind.",
                count(*n, "Position ist", "Positionen sind")
            ),
            (Lang::De, HaltFoot::LeftOpen(n)) => format!(
                "{} offen gelassen, jetzt unter den Stops ihrer Strategien; die GuV rechnet sie zum aktuellen Preis.",
                count(*n, "Position", "Positionen")
            ),
            (Lang::De, HaltFoot::Paused(l)) => format!("Strategien pausiert: {}.", l.join(", ")),
            (Lang::De, HaltFoot::Still(l)) => {
                format!("Laufen für die anderen Autopiloten unverändert weiter: {}.", l.join(", "))
            }
            (Lang::De, HaltFoot::Idle(l)) => format!(
                "Wieder in Wartestellung bis zum nächsten Autopiloten: {} (bekommt weiter das Signal des Labors und handelt nur in einem Autopiloten).",
                l.join(", ")
            ),
        }
    }
}

/// A shadow model the drift watch can mute.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DriftModel {
    Vol,
    Picks,
}

impl DriftModel {
    /// Lower case, to follow other words: `volatility model`.
    pub fn label(self, lang: Lang) -> &'static str {
        match (lang, self) {
            (Lang::En, DriftModel::Vol) => "volatility model",
            (Lang::En, DriftModel::Picks) => "M2 coin ranking",
            (Lang::De, DriftModel::Vol) => "Volatilitätsmodell",
            (Lang::De, DriftModel::Picks) => "M2-Coin-Rangliste",
        }
    }
}

/// What a big move is about.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum MoveOf {
    Coin,
    Equity,
}

/// One of the engine's messages, with what it needs to be said in any
/// language.
#[derive(Debug, Clone, PartialEq)]
pub enum Msg {
    AutopilotStarted {
        name: String,
        mode: ApMode,
        place: Place,
        capital: f64,
        /// A portfolio's split: each class and its share (0 to 1).
        split: Option<Vec<(AssetClass, f64)>>,
        books: Vec<String>,
        rules: Rules,
    },
    AutopilotHalted {
        name: String,
        finished: bool,
        why: StopWhy,
        equity: f64,
        pnl: f64,
        pnl_pct: f64,
        vs_btc: Option<f64>,
        trades: u64,
        fees: f64,
        foot: Option<HaltFoot>,
    },
    DataStale { mins: i64, quotes: Option<String>, candles: Option<String> },
    DataFresh,
    DailyLoss { loss_pct: f64, limit_pct: f64 },
    KillDrawdown { equity: f64, dd_pct: f64, limit_pct: f64 },
    KillByHand,
    KillReleased,
    Reconcile { venue: String, changes: usize },
    ReconcileDemo { mismatches: usize },
    OrderRejects { n: u32, demo: bool, symbol: String, reason: String },
    DriftOn { model: DriftModel, total: usize, hits: Vec<(String, f64)> },
    DriftOff { model: DriftModel },
    BigMove { of: MoveOf, label: String, held_by: String, window: &'static str, now: f64, then: f64, pct: f64 },
    Test { on: usize, total: usize, quiet: Option<(String, String)>, hour_pct: f64, day_pct: f64 },
    /// What quiet hours held back: the fills per autopilot, every other kind
    /// with its count.
    Overnight { fills: Vec<HeldFills>, others: Vec<HeldGroup>, start: String, end: String, timezone: String },
}

/// What a message puts on its card. `None` falls back: the title to the kind's
/// label, the summary to [`Msg::text`].
#[derive(Debug, Clone, Default, PartialEq)]
pub struct CardText {
    pub title: Option<String>,
    pub summary: Option<String>,
    pub lines: Vec<String>,
    pub rows: Vec<Row>,
    pub table: Option<Table>,
    pub footer: Option<String>,
}

/// The first letter in upper case.
pub fn sentence(s: &str) -> String {
    let mut c = s.chars();
    match c.next() {
        Some(f) => f.to_uppercase().collect::<String>() + c.as_str(),
        None => String::new(),
    }
}

fn stale_parts(lang: Lang, quotes: &Option<String>, candles: &Option<String>) -> String {
    let mut parts = Vec::new();
    if let Some(q) = quotes {
        parts.push(match lang {
            Lang::En => format!("quotes for {q}"),
            Lang::De => format!("Kurse für {q}"),
        });
    }
    if let Some(c) = candles {
        parts.push(match lang {
            Lang::En => format!("candles for {c}"),
            Lang::De => format!("Kerzen für {c}"),
        });
    }
    parts.join(", ")
}

impl Msg {
    /// The kind of alert it goes out as.
    pub fn kind(&self) -> AlertKind {
        match self {
            Msg::AutopilotStarted { .. } => AlertKind::AutopilotStarted,
            Msg::AutopilotHalted { why: StopWhy::ByYou, .. } => AlertKind::AutopilotStopped,
            Msg::AutopilotHalted { why: StopWhy::TakeProfit { .. } | StopWhy::EndTime, .. } => AlertKind::StopRuleHit,
            Msg::AutopilotHalted { .. } => AlertKind::FloorHit,
            Msg::DataStale { .. } | Msg::DataFresh => AlertKind::DataStale,
            Msg::DailyLoss { .. } => AlertKind::DailyLossBrake,
            Msg::KillDrawdown { .. } | Msg::KillByHand | Msg::KillReleased => AlertKind::KillSwitch,
            Msg::Reconcile { .. } | Msg::ReconcileDemo { .. } => AlertKind::ReconcileMismatch,
            Msg::OrderRejects { .. } => AlertKind::OrderRejects,
            Msg::DriftOn { .. } | Msg::DriftOff { .. } => AlertKind::ModelDrift,
            Msg::BigMove { .. } => AlertKind::BigMove,
            Msg::Test { .. } => AlertKind::Test,
            Msg::Overnight { .. } => AlertKind::Overnight,
        }
    }

    /// The whole message in a sentence or more (the journal keeps the English).
    pub fn text(&self, lang: Lang) -> String {
        match (lang, self) {
            (Lang::En, Msg::AutopilotStarted { name, .. }) => format!("Autopilot \"{name}\" started."),
            (Lang::De, Msg::AutopilotStarted { name, .. }) => format!("Autopilot \"{name}\" gestartet."),
            (_, Msg::AutopilotHalted { .. }) => {
                let c = self.card_text(lang);
                format!("{}: {}", c.title.unwrap_or_default(), c.summary.unwrap_or_default())
            }
            (Lang::En, Msg::DataStale { mins, quotes, candles }) => format!(
                "for {mins} min: {}. Entries are refused and stops wait for a fresh price.",
                stale_parts(lang, quotes, candles)
            ),
            (Lang::De, Msg::DataStale { mins, quotes, candles }) => format!(
                "seit {mins} min: {}. Einstiege werden abgelehnt, Stops warten auf einen frischen Preis.",
                stale_parts(lang, quotes, candles)
            ),
            (Lang::En, Msg::DataFresh) => "market data is fresh again.".into(),
            (Lang::De, Msg::DataFresh) => "Marktdaten sind wieder aktuell.".into(),
            (Lang::En, Msg::DailyLoss { loss_pct, limit_pct }) => format!(
                "the book is down {loss_pct:.1} % today, limit {limit_pct:.1} %. New entries are refused until the next UTC day."
            ),
            (Lang::De, Msg::DailyLoss { loss_pct, limit_pct }) => format!(
                "das Buch liegt heute {} % im Minus, Grenze {} %. Neue Einstiege werden bis zum nächsten UTC-Tag abgelehnt.",
                plain(lang, *loss_pct, 1),
                plain(lang, *limit_pct, 1)
            ),
            (Lang::En, Msg::KillDrawdown { equity, dd_pct, limit_pct }) => format!(
                "tripped by the drawdown brake: equity {equity:.2} is {dd_pct:.1} % below its peak, limit {limit_pct:.1} %. Only closing orders pass until it is released."
            ),
            (Lang::De, Msg::KillDrawdown { equity, dd_pct, limit_pct }) => format!(
                "von der Drawdown-Bremse ausgelöst: Wert {} liegt {} % unter dem Höchststand, Grenze {} %. Bis zur Freigabe gehen nur schließende Orders durch.",
                usd(lang, *equity),
                plain(lang, *dd_pct, 1),
                plain(lang, *limit_pct, 1)
            ),
            (Lang::En, Msg::KillByHand) => "engaged by hand. Only closing orders pass until it is released.".into(),
            (Lang::De, Msg::KillByHand) => {
                "von Hand ausgelöst. Bis zur Freigabe gehen nur schließende Orders durch.".into()
            }
            (Lang::En, Msg::KillReleased) => "released by hand.".into(),
            (Lang::De, Msg::KillReleased) => "von Hand aufgehoben.".into(),
            (Lang::En, Msg::Reconcile { venue, changes }) => format!(
                "{venue} and Pythia's book differed in {changes} position(s); Pythia took the venue's numbers. See the journal."
            ),
            (Lang::De, Msg::Reconcile { venue, changes }) => format!(
                "{venue} und Pythias Buch wichen bei {} ab; Pythia hat die Zahlen des Handelsplatzes übernommen. Mehr im Journal.",
                count(*changes as u64, "Position", "Positionen")
            ),
            (Lang::En, Msg::ReconcileDemo { mismatches }) => format!(
                "the Alpaca paper account and Pythia's demo book differ in {mismatches} pair(s); see the Live page."
            ),
            (Lang::De, Msg::ReconcileDemo { mismatches }) => format!(
                "das Alpaca-Paper-Konto und Pythias Demo-Buch weichen bei {} ab; siehe Seite Live.",
                count(*mismatches as u64, "Paar", "Paaren")
            ),
            (Lang::En, Msg::OrderRejects { n, demo, symbol, reason }) => {
                let on = if symbol.is_empty() { String::new() } else { format!(" (last: {symbol})") };
                format!("{n} {} orders refused in a row{on}: {reason}", if *demo { "demo" } else { "live" })
            }
            (Lang::De, Msg::OrderRejects { n, demo, symbol, reason }) => {
                let on = if symbol.is_empty() { String::new() } else { format!(" (zuletzt: {symbol})") };
                format!("{n} {}-Orders in Folge abgelehnt{on}: {reason}", if *demo { "Demo" } else { "Live" })
            }
            (Lang::En, Msg::DriftOn { model, total, hits }) => {
                let list: Vec<String> = hits.iter().take(4).map(|(f, p)| format!("{f} {p:.0} % outside")).collect();
                format!(
                    "{} muted: {} of {total} inputs outside the trained range ({}). Its forecasts are not to be trusted until they are back in range or it is retrained.",
                    model.label(lang),
                    hits.len(),
                    list.join(", ")
                )
            }
            (Lang::De, Msg::DriftOn { model, total, hits }) => {
                let list: Vec<String> = hits.iter().take(4).map(|(f, p)| format!("{f} {p:.0} % außerhalb")).collect();
                format!(
                    "{} stummgeschaltet: {} von {total} Eingaben außerhalb des Trainingsbereichs ({}). Seinen Prognosen ist nicht zu trauen, bis sie wieder im Bereich sind oder neu trainiert wurde.",
                    model.label(lang),
                    hits.len(),
                    list.join(", ")
                )
            }
            (Lang::En, Msg::DriftOff { model }) => format!("{} inputs are back in the trained range.", model.label(lang)),
            (Lang::De, Msg::DriftOff { model }) => {
                format!("{}: Eingaben wieder im Trainingsbereich.", model.label(lang))
            }
            (_, Msg::BigMove { .. }) => {
                let c = self.card_text(lang);
                format!("{}. {}", c.title.unwrap_or_default(), c.summary.unwrap_or_default()).trim().to_string()
            }
            (Lang::En, Msg::Test { .. }) => "test message from the engine: alerts reach this destination.".into(),
            (Lang::De, Msg::Test { .. }) => "Testnachricht von Pythia: Meldungen kommen hier an.".into(),
            (Lang::En, Msg::Overnight { fills, others, .. }) => {
                format!("{} alert(s) were held back in quiet hours.", overnight_count(fills, others))
            }
            (Lang::De, Msg::Overnight { fills, others, .. }) => format!(
                "{} in der Ruhezeit zurückgehalten.",
                count(overnight_count(fills, others) as u64, "Meldung", "Meldungen")
            ),
        }
    }

    /// What goes on the card besides the emoji.
    pub fn card_text(&self, lang: Lang) -> CardText {
        let mut c = CardText::default();
        match self {
            Msg::AutopilotStarted { name, mode, place, capital, split, books, rules } => {
                let l = |en: &str, de: &str| if lang == Lang::En { en.to_string() } else { de.to_string() };
                c.title = Some(match lang {
                    Lang::En => format!("{name} started"),
                    Lang::De => format!("{name} gestartet"),
                });
                c.summary = Some(match lang {
                    Lang::En => format!("Rules: {}.", rules.text(lang)),
                    Lang::De => format!("Regeln: {}.", rules.text(lang)),
                });
                c.rows = vec![
                    Row::new(l("Capital", "Kapital"), usd(lang, *capital)),
                    Row::new(l("Mode", "Modus"), mode.word(lang)),
                    Row::new(l("Venue", "Handelsplatz"), place.text(lang)),
                ];
                if let Some(sp) = split {
                    let words: Vec<String> =
                        sp.iter().map(|(cl, b)| format!("{} {:.0} %", cl.label(lang), b * 100.0)).collect();
                    c.rows.push(Row::new(l("Split", "Aufteilung"), words.join(", ")));
                }
                if !books.is_empty() {
                    c.rows.push(Row::new(l("Books", "Bücher"), books.join(", ")));
                }
            }
            Msg::AutopilotHalted { name, finished, why, equity, pnl, pnl_pct, vs_btc, trades, fees, foot } => {
                let l = |en: &str, de: &str| if lang == Lang::En { en.to_string() } else { de.to_string() };
                let w = match (lang, finished) {
                    (Lang::En, true) => "finished",
                    (Lang::En, false) => "stopped",
                    (Lang::De, true) => "beendet",
                    (Lang::De, false) => "gestoppt",
                };
                c.title = Some(format!("{name} {w}"));
                c.summary = Some(format!("{}.", why.text(lang).trim_end_matches('.')));
                c.rows = vec![
                    Row::new(l("Equity", "Wert"), usd(lang, *equity)),
                    Row::toned(
                        l("P&L since start", "GuV seit Start"),
                        format!("{} {}", signed_usd(lang, *pnl), signed_pct(lang, *pnl_pct, 2)),
                        *pnl,
                    ),
                ];
                if let Some(b) = vs_btc {
                    c.rows.push(Row::toned(l("vs BTC since start", "ggü. BTC seit Start"), pts(lang, pnl_pct - b), pnl_pct - b));
                }
                // Closed positions, not fills: fees are paid on every fill,
                // so "0 trades, fees $11" would read as a contradiction.
                c.rows.push(Row::new(l("Closed so far", "Bisher geschlossen"), trades.to_string()));
                c.rows.push(Row::new(l("Fees", "Gebühren"), usd(lang, *fees)));
                c.footer = foot.as_ref().map(|f| f.text(lang));
            }
            Msg::DataFresh => {
                c.title = Some(
                    match lang {
                        Lang::En => "Market data is fresh again",
                        Lang::De => "Marktdaten wieder aktuell",
                    }
                    .into(),
                );
                c.summary = Some(
                    match lang {
                        Lang::En => "Entries and stops work on live prices again.",
                        Lang::De => "Einstiege und Stops arbeiten wieder mit aktuellen Preisen.",
                    }
                    .into(),
                );
            }
            Msg::KillReleased => {
                c.title = Some(
                    match lang {
                        Lang::En => "Kill switch released",
                        Lang::De => "Not-Aus aufgehoben",
                    }
                    .into(),
                );
            }
            Msg::DriftOn { model, total, hits } => {
                c.title = Some(match lang {
                    Lang::En => format!("{} muted", sentence(model.label(lang))),
                    Lang::De => format!("{} stummgeschaltet", model.label(lang)),
                });
                c.summary = Some(
                    match lang {
                        Lang::En => "Inputs outside the range it was trained on: not to be trusted until back in range or retrained.",
                        Lang::De => "Eingaben außerhalb des Trainingsbereichs: nicht verlässlich, bis sie zurück sind oder neu trainiert wurde.",
                    }
                    .into(),
                );
                let (outside, of) = match lang {
                    Lang::En => ("Inputs outside", "of"),
                    Lang::De => ("Eingaben außerhalb", "von"),
                };
                c.rows = vec![Row::new(outside, format!("{} {of} {total}", hits.len()))];
                c.rows.extend(hits.iter().take(4).map(|(f, p)| {
                    Row::new(
                        f.clone(),
                        match lang {
                            Lang::En => format!("{p:.0} % outside"),
                            Lang::De => format!("{p:.0} % außerhalb"),
                        },
                    )
                }));
            }
            Msg::DriftOff { model } => {
                c.title = Some(match lang {
                    Lang::En => format!("{} back in range", sentence(model.label(lang))),
                    Lang::De => format!("{} wieder im Bereich", model.label(lang)),
                });
            }
            Msg::BigMove { of, label, held_by, window, now, then, pct } => {
                let ago = match lang {
                    Lang::En => format!("{window} ago"),
                    Lang::De => format!("vor {window}"),
                };
                let change = match lang {
                    Lang::En => "Change",
                    Lang::De => "Änderung",
                };
                match of {
                    MoveOf::Coin => {
                        c.title = Some(format!("{label} {} in {window}", signed_pct(lang, *pct, 1)));
                        c.summary = Some(if held_by.is_empty() {
                            String::new()
                        } else {
                            match lang {
                                Lang::En => format!("Held by {held_by}."),
                                Lang::De => format!("Gehalten von {held_by}."),
                            }
                        });
                        c.rows = vec![
                            Row::new(if lang == Lang::En { "Now" } else { "Jetzt" }, price(lang, *now)),
                            Row::new(ago, price(lang, *then)),
                            Row::toned(change, signed_pct(lang, *pct, 2), *pct),
                        ];
                    }
                    MoveOf::Equity => {
                        c.title = Some(match lang {
                            Lang::En => format!("{label} equity {} in {window}", signed_pct(lang, *pct, 1)),
                            Lang::De => format!("{label}: Wert {} in {window}", signed_pct(lang, *pct, 1)),
                        });
                        c.summary = Some(
                            match lang {
                                Lang::En => "The autopilot's equity, positions at their price now.",
                                Lang::De => "Der Wert des Autopiloten, Positionen zum aktuellen Preis.",
                            }
                            .into(),
                        );
                        c.rows = vec![
                            Row::new(if lang == Lang::En { "Equity" } else { "Wert" }, usd(lang, *now)),
                            Row::new(ago, usd(lang, *then)),
                            Row::toned(
                                change,
                                format!("{} {}", signed_usd(lang, now - then), signed_pct(lang, *pct, 2)),
                                *pct,
                            ),
                        ];
                    }
                }
            }
            Msg::Test { on, total, quiet, hour_pct, day_pct } => {
                let l = |en: &str, de: &str| if lang == Lang::En { en.to_string() } else { de.to_string() };
                c.title = Some(l("Test message", "Testnachricht"));
                c.summary = Some(l("Alerts from the engine reach this chat.", "Meldungen von Pythia kommen in diesem Chat an."));
                let quiet_text = match (quiet, lang) {
                    (Some((s, e)), Lang::En) => format!("{s} to {e}"),
                    (Some((s, e)), Lang::De) => format!("{s} bis {e}"),
                    (None, Lang::En) => "off".into(),
                    (None, Lang::De) => "aus".into(),
                };
                let (hp, dp) = match lang {
                    Lang::En => (hour_pct.to_string(), day_pct.to_string()),
                    Lang::De => (hour_pct.to_string().replace('.', ","), day_pct.to_string().replace('.', ",")),
                };
                c.rows = vec![
                    Row::new(
                        l("Categories on", "Kategorien an"),
                        match lang {
                            Lang::En => format!("{on} of {total}"),
                            Lang::De => format!("{on} von {total}"),
                        },
                    ),
                    Row::new(l("Quiet hours", "Ruhezeit"), quiet_text),
                    Row::new(l("Big move", "Starke Bewegung"), format!("{hp} % / 1 h, {dp} % / 24 h")),
                    Row::toned(
                        l("Example gain", "Beispiel Gewinn"),
                        format!("{} {}", signed_usd(lang, 1234.5), signed_pct(lang, 1.23, 2)),
                        1.0,
                    ),
                    Row::toned(
                        l("Example loss", "Beispiel Verlust"),
                        format!("{} {}", signed_usd(lang, -87.65), signed_pct(lang, -0.42, 2)),
                        -1.0,
                    ),
                ];
            }
            Msg::Overnight { fills, others, start, end, .. } => {
                let n = overnight_count(fills, others);
                c.title = Some(kind_label(AlertKind::Overnight, lang).into());
                c.summary = Some(match lang {
                    Lang::En => format!(
                        "{n} {} held back from {start} to {end}. Urgent ones went out at once.",
                        if n == 1 { "alert was" } else { "alerts were" }
                    ),
                    Lang::De => format!(
                        "{} von {start} bis {end} zurückgehalten. Dringende gingen sofort raus.",
                        count(n as u64, "Meldung wurde", "Meldungen wurden")
                    ),
                });
                // One line per autopilot for its fills, one per other kind.
                c.lines = fills.iter().map(|f| f.line(lang)).chain(others.iter().map(|g| g.line(lang))).collect();
            }
            Msg::DataStale { .. }
            | Msg::DailyLoss { .. }
            | Msg::KillDrawdown { .. }
            | Msg::KillByHand
            | Msg::Reconcile { .. }
            | Msg::ReconcileDemo { .. }
            | Msg::OrderRejects { .. } => {}
        }
        c
    }
}
