//! What the owner wants on the phone: one switch per category, quiet hours,
//! and the size of a move that counts as big. Saved with the engine state
//! (`PersistedState::alert_settings`) and written for the lab as
//! `reports/notify/settings.json`, so the engine's alerts and the lab's
//! digests follow the same switches.

use std::collections::BTreeMap;

use chrono::{TimeZone, Timelike, Utc};
use serde::{Deserialize, Serialize};

use super::i18n::Lang;

/// What an alert is about, for the switches in Settings.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum AlertCategory {
    Trades,
    Rebalances,
    DailyPnl,
    BigMoves,
    Autopilot,
    Risk,
    Venue,
    Models,
    Studies,
    Listings,
    Trending,
    Cs2,
    Pokemon,
    Weekly,
}

impl AlertCategory {
    pub const ALL: [AlertCategory; 14] = [
        AlertCategory::Trades,
        AlertCategory::Rebalances,
        AlertCategory::DailyPnl,
        AlertCategory::BigMoves,
        AlertCategory::Autopilot,
        AlertCategory::Risk,
        AlertCategory::Venue,
        AlertCategory::Models,
        AlertCategory::Studies,
        AlertCategory::Listings,
        AlertCategory::Trending,
        AlertCategory::Cs2,
        AlertCategory::Pokemon,
        AlertCategory::Weekly,
    ];

    /// The id in the API, the settings file and the lab (`notify.py`).
    pub fn id(self) -> &'static str {
        match self {
            AlertCategory::Trades => "trades",
            AlertCategory::Rebalances => "rebalances",
            AlertCategory::DailyPnl => "dailyPnl",
            AlertCategory::BigMoves => "bigMoves",
            AlertCategory::Autopilot => "autopilot",
            AlertCategory::Risk => "risk",
            AlertCategory::Venue => "venue",
            AlertCategory::Models => "models",
            AlertCategory::Studies => "studies",
            AlertCategory::Listings => "listings",
            AlertCategory::Trending => "trending",
            AlertCategory::Cs2 => "cs2",
            AlertCategory::Pokemon => "pokemon",
            AlertCategory::Weekly => "weekly",
        }
    }

    /// An id, case and `_` or `-` ignored (`daily_pnl` is `dailyPnl`).
    pub fn parse(s: &str) -> Option<Self> {
        let k: String = s.chars().filter(|c| *c != '_' && *c != '-').collect::<String>().to_ascii_lowercase();
        Self::ALL.into_iter().find(|c| c.id().to_ascii_lowercase() == k)
    }

    pub fn label(self) -> &'static str {
        match self {
            AlertCategory::Trades => "Trades",
            AlertCategory::Rebalances => "Rebalances",
            AlertCategory::DailyPnl => "Daily P&L",
            AlertCategory::BigMoves => "Big moves",
            AlertCategory::Autopilot => "Autopilot events",
            AlertCategory::Risk => "Risk",
            AlertCategory::Venue => "Venue and data problems",
            AlertCategory::Models => "Models",
            AlertCategory::Studies => "Studies and factory",
            AlertCategory::Listings => "Listings",
            AlertCategory::Trending => "Trending",
            AlertCategory::Cs2 => "CS2",
            AlertCategory::Pokemon => "Pokemon",
            AlertCategory::Weekly => "Weekly report",
        }
    }

    /// The leading emoji of its cards.
    pub fn emoji(self) -> &'static str {
        match self {
            AlertCategory::Trades => "💱",
            AlertCategory::Rebalances => "🔁",
            AlertCategory::DailyPnl => "📊",
            AlertCategory::BigMoves => "🌊",
            AlertCategory::Autopilot => "🤖",
            AlertCategory::Risk => "🛡️",
            AlertCategory::Venue => "📡",
            AlertCategory::Models => "🧠",
            AlertCategory::Studies => "🧪",
            AlertCategory::Listings => "🆕",
            AlertCategory::Trending => "🔥",
            AlertCategory::Cs2 => "🎮",
            AlertCategory::Pokemon => "🃏",
            AlertCategory::Weekly => "🗓️",
        }
    }

    /// One sentence for the switch in Settings.
    pub fn about(self) -> &'static str {
        match self {
            AlertCategory::Trades => "Each fill of an autopilot outside a rebalance.",
            AlertCategory::Rebalances => "The fills of one rebalance in one message, as a small table.",
            AlertCategory::DailyPnl => "The morning digest with the equity chart.",
            AlertCategory::BigMoves => "A held coin or an autopilot's equity moving more than the set % in an hour or a day.",
            AlertCategory::Autopilot => "An autopilot started, stopped or reached a stop rule.",
            AlertCategory::Risk => "Floor, kill switch, daily loss brake, orders refused again and again.",
            AlertCategory::Venue => "Reconcile mismatches, late market data, the health check.",
            AlertCategory::Models => "A model muted by drift, retrained or promoted.",
            AlertCategory::Studies => "Study and strategy factory results.",
            AlertCategory::Listings => "New coins listed on a venue.",
            AlertCategory::Trending => "Volume surges and the trending watchlist.",
            AlertCategory::Cs2 => "CS2 skin market findings.",
            AlertCategory::Pokemon => "Pokemon card market findings.",
            AlertCategory::Weekly => "Sunday 18:00: the week in one chart and a few numbers.",
        }
    }

    /// Who sends it: the engine itself, or a lab job.
    pub fn source(self) -> &'static str {
        match self {
            AlertCategory::Trades
            | AlertCategory::Rebalances
            | AlertCategory::BigMoves
            | AlertCategory::Autopilot
            | AlertCategory::Risk
            | AlertCategory::Venue
            | AlertCategory::Models => "engine",
            _ => "lab",
        }
    }
}

/// When only urgent alerts go out.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", default)]
pub struct QuietHours {
    pub enabled: bool,
    /// `HH:MM`, local time in `timezone`.
    pub start: String,
    pub end: String,
    /// An IANA name such as `Europe/Berlin`.
    pub timezone: String,
}

impl Default for QuietHours {
    fn default() -> Self {
        Self { enabled: true, start: "23:00".into(), end: "07:00".into(), timezone: "Europe/Berlin".into() }
    }
}

/// `HH:MM` as minutes after midnight.
pub fn parse_hhmm(s: &str) -> Option<u32> {
    let (h, m) = s.trim().split_once(':')?;
    let (h, m): (u32, u32) = (h.parse().ok()?, m.parse().ok()?);
    (h < 24 && m < 60).then_some(h * 60 + m)
}

impl QuietHours {
    fn tz(&self) -> chrono_tz::Tz {
        self.timezone.parse().unwrap_or(chrono_tz::Europe::Berlin)
    }

    /// Whether `now_ms` falls inside the quiet hours. The window may run over
    /// midnight (23:00 to 07:00); a start equal to its end is no window.
    pub fn contains(&self, now_ms: i64) -> bool {
        if !self.enabled {
            return false;
        }
        let (Some(s), Some(e)) = (parse_hhmm(&self.start), parse_hhmm(&self.end)) else { return false };
        if s == e {
            return false;
        }
        let Some(t) = Utc.timestamp_millis_opt(now_ms).single() else { return false };
        let local = t.with_timezone(&self.tz());
        let m = local.hour() * 60 + local.minute();
        if s < e {
            s <= m && m < e
        } else {
            m >= s || m < e
        }
    }

    fn check(&self) -> Result<(), String> {
        if parse_hhmm(&self.start).is_none() || parse_hhmm(&self.end).is_none() {
            return Err("quiet hours: start and end are HH:MM, 00:00 to 23:59".into());
        }
        if self.timezone.parse::<chrono_tz::Tz>().is_err() {
            return Err(format!("quiet hours: unknown time zone {}", self.timezone));
        }
        Ok(())
    }
}

/// How large a move must be to count as big.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", default)]
pub struct BigMoves {
    /// Within one hour, in %.
    pub hour_pct: f64,
    /// Within 24 hours, in %.
    pub day_pct: f64,
}

impl Default for BigMoves {
    fn default() -> Self {
        Self { hour_pct: 3.0, day_pct: 8.0 }
    }
}

/// The owner's alert settings.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, Default)]
#[serde(rename_all = "camelCase", default)]
pub struct AlertSettings {
    /// Category id to on or off. A category not listed is on.
    pub categories: BTreeMap<String, bool>,
    pub quiet_hours: QuietHours,
    pub big_moves: BigMoves,
    /// The language of the messages to the chat (`en` or `de`). The app
    /// stays in English. `PYTHIA_ALERT_LANG` overrides it.
    pub language: Lang,
}

/// A change to the settings: what is left out stays.
#[derive(Debug, Clone, Default, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct AlertSettingsPatch {
    #[serde(default)]
    pub categories: Option<BTreeMap<String, bool>>,
    #[serde(default)]
    pub quiet_hours: Option<QuietHoursPatch>,
    #[serde(default)]
    pub big_moves: Option<BigMovesPatch>,
    /// `en` or `de`.
    #[serde(default)]
    pub language: Option<String>,
}

#[derive(Debug, Clone, Default, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct QuietHoursPatch {
    pub enabled: Option<bool>,
    pub start: Option<String>,
    pub end: Option<String>,
    pub timezone: Option<String>,
}

#[derive(Debug, Clone, Default, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct BigMovesPatch {
    pub hour_pct: Option<f64>,
    pub day_pct: Option<f64>,
}

impl AlertSettings {
    pub fn enabled(&self, c: AlertCategory) -> bool {
        self.categories.get(c.id()).copied().unwrap_or(true)
    }

    /// Apply a change, all or nothing. The error says what is wrong.
    pub fn apply(&mut self, p: AlertSettingsPatch) -> Result<(), String> {
        let mut next = self.clone();
        if let Some(cats) = p.categories {
            for (k, on) in cats {
                let c = AlertCategory::parse(&k).ok_or_else(|| format!("unknown category {k}"))?;
                next.categories.insert(c.id().to_string(), on);
            }
        }
        if let Some(q) = p.quiet_hours {
            if let Some(v) = q.enabled {
                next.quiet_hours.enabled = v;
            }
            if let Some(v) = q.start {
                next.quiet_hours.start = v.trim().to_string();
            }
            if let Some(v) = q.end {
                next.quiet_hours.end = v.trim().to_string();
            }
            if let Some(v) = q.timezone {
                next.quiet_hours.timezone = v.trim().to_string();
            }
            next.quiet_hours.check()?;
        }
        if let Some(b) = p.big_moves {
            if let Some(v) = b.hour_pct {
                if !(0.5..=50.0).contains(&v) {
                    return Err("bigMoves.hourPct must be 0.5 to 50".into());
                }
                next.big_moves.hour_pct = v;
            }
            if let Some(v) = b.day_pct {
                if !(1.0..=90.0).contains(&v) {
                    return Err("bigMoves.dayPct must be 1 to 90".into());
                }
                next.big_moves.day_pct = v;
            }
        }
        if let Some(l) = p.language {
            next.language = Lang::parse(&l).ok_or_else(|| format!("language must be en or de, not {l}"))?;
        }
        // Only known ids are kept, so an old save never carries a stray key.
        next.categories.retain(|k, _| AlertCategory::parse(k).is_some());
        *self = next;
        Ok(())
    }

    /// The language the messages go out in: `PYTHIA_ALERT_LANG` when it is
    /// set (`env`), else the setting.
    pub fn lang(&self, env: Option<Lang>) -> Lang {
        env.unwrap_or(self.language)
    }

    /// What `GET /api/alerts/settings` answers and the lab reads: every
    /// category with its label, emoji, sentence, source and switch, and the
    /// language (with `languageEnv` when the environment overrides it).
    pub fn view(&self, now_ms: i64) -> serde_json::Value {
        self.view_with(now_ms, Lang::from_env())
    }

    /// [`AlertSettings::view`] with the environment's language given.
    pub fn view_with(&self, now_ms: i64, env: Option<Lang>) -> serde_json::Value {
        let cats: Vec<serde_json::Value> = AlertCategory::ALL
            .iter()
            .map(|c| {
                serde_json::json!({
                    "id": c.id(),
                    "label": c.label(),
                    "emoji": c.emoji(),
                    "about": c.about(),
                    "source": c.source(),
                    "on": self.enabled(*c),
                })
            })
            .collect();
        serde_json::json!({
            "categories": cats,
            "quietHours": self.quiet_hours,
            "bigMoves": self.big_moves,
            "quietNow": self.quiet_hours.contains(now_ms),
            "language": self.language,
            "languageEnv": env,
            "languages": Lang::ALL.iter().map(|l| serde_json::json!({"id": l.id(), "label": l.label()})).collect::<Vec<_>>(),
        })
    }
}
