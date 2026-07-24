//! User preferences — the non-secret settings that sit alongside the keys.
//!
//! These live in the same OS keychain blob as the credentials purely because
//! that store is already there and already survives restarts; nothing here is
//! sensitive. They exist so the desktop app is configurable from its own
//! Settings page rather than from environment variables it never reads.
//!
//! Everything is validated on the way in. A preference is user input, and a
//! typo'd effort level or a one-second poll interval should be corrected to
//! something sane rather than silently breaking the daemon.

use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;

/// Vault entry name. Not a venue — just reuses the same storage.
pub const VAULT_KEY: &str = "prefs";

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Prefs {
    /// Alpaca market-data feed: `iex` (free) or `sip` (paid subscription).
    pub alpaca_feed: String,
    /// Candle size every indicator runs on.
    pub bar_timeframe: String,
    /// Provider id the background AI overlay polls with.
    pub ai_provider: String,
    /// Empty → that provider's default model.
    pub ai_model: String,
    /// Thinking depth: low | medium | high | xhigh | max.
    pub ai_effort: String,
    /// Seconds between overlay calls. One market is polled per pass, so this is
    /// also the cost dial.
    pub ai_interval_sec: u64,
}

impl Default for Prefs {
    fn default() -> Self {
        Self {
            alpaca_feed: "iex".into(),
            bar_timeframe: "5Min".into(),
            ai_provider: "anthropic".into(),
            ai_model: String::new(),
            ai_effort: "low".into(),
            ai_interval_sec: 120,
        }
    }
}

/// Timeframes both venues can serve. Kraken takes minutes, Alpaca takes these
/// strings directly, so the pair is kept together rather than derived twice.
pub const TIMEFRAMES: [(&str, u32); 6] =
    [("1Min", 1), ("5Min", 5), ("15Min", 15), ("30Min", 30), ("1Hour", 60), ("1Day", 1440)];

impl Prefs {
    /// Correct anything out of range instead of trusting it.
    pub fn sanitized(mut self) -> Self {
        let d = Prefs::default();
        if !matches!(self.alpaca_feed.as_str(), "iex" | "sip") {
            self.alpaca_feed = d.alpaca_feed;
        }
        if !TIMEFRAMES.iter().any(|(t, _)| *t == self.bar_timeframe) {
            self.bar_timeframe = d.bar_timeframe;
        }
        if crate::llm::Provider::parse(&self.ai_provider).is_none() {
            self.ai_provider = d.ai_provider;
        }
        if !matches!(self.ai_effort.as_str(), "low" | "medium" | "high" | "xhigh" | "max") {
            self.ai_effort = d.ai_effort;
        }
        // A 5-second poll would burn money without learning anything new — the
        // underlying bar hasn't changed. Ceiling is a day.
        self.ai_interval_sec = self.ai_interval_sec.clamp(30, 86_400);
        self.ai_model = self.ai_model.trim().to_string();
        self
    }

    /// Kraken's OHLC interval, in minutes, for the configured timeframe.
    pub fn kraken_interval(&self) -> u32 {
        TIMEFRAMES
            .iter()
            .find(|(t, _)| *t == self.bar_timeframe)
            .map(|(_, m)| *m)
            .unwrap_or(5)
    }

    pub fn effort(&self) -> crate::llm::Effort {
        match self.ai_effort.as_str() {
            "medium" => crate::llm::Effort::Medium,
            "high" => crate::llm::Effort::High,
            "xhigh" => crate::llm::Effort::Xhigh,
            "max" => crate::llm::Effort::Max,
            _ => crate::llm::Effort::Low,
        }
    }

    pub fn provider(&self) -> crate::llm::Provider {
        crate::llm::Provider::parse(&self.ai_provider).unwrap_or(crate::llm::Provider::Anthropic)
    }

    /// The vault stores flat string maps, so round-trip through one.
    pub fn to_map(&self) -> BTreeMap<String, String> {
        BTreeMap::from([
            ("alpacaFeed".into(), self.alpaca_feed.clone()),
            ("barTimeframe".into(), self.bar_timeframe.clone()),
            ("aiProvider".into(), self.ai_provider.clone()),
            ("aiModel".into(), self.ai_model.clone()),
            ("aiEffort".into(), self.ai_effort.clone()),
            ("aiIntervalSec".into(), self.ai_interval_sec.to_string()),
        ])
    }

    /// Missing or unparseable fields fall back to the default, so a blob
    /// written by an older version still loads.
    pub fn from_map(m: &BTreeMap<String, String>) -> Self {
        let d = Prefs::default();
        let s = |k: &str, fallback: String| m.get(k).cloned().filter(|v| !v.is_empty()).unwrap_or(fallback);
        Prefs {
            alpaca_feed: s("alpacaFeed", d.alpaca_feed),
            bar_timeframe: s("barTimeframe", d.bar_timeframe),
            ai_provider: s("aiProvider", d.ai_provider),
            // The model is legitimately empty (= provider default), so it can't
            // use the non-empty filter above.
            ai_model: m.get("aiModel").cloned().unwrap_or_default(),
            ai_effort: s("aiEffort", d.ai_effort),
            ai_interval_sec: m
                .get("aiIntervalSec")
                .and_then(|v| v.parse().ok())
                .unwrap_or(d.ai_interval_sec),
        }
        .sanitized()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn round_trips_through_the_flat_vault_map() {
        let p = Prefs {
            alpaca_feed: "sip".into(),
            bar_timeframe: "1Hour".into(),
            ai_provider: "openai".into(),
            ai_model: "gpt-5.6".into(),
            ai_effort: "high".into(),
            ai_interval_sec: 300,
        };
        assert_eq!(Prefs::from_map(&p.to_map()), p);
    }

    #[test]
    fn an_empty_model_survives_the_round_trip() {
        // Empty means "use the provider's default" — a real setting, not a
        // missing one, so it must not be replaced by a fallback.
        let p = Prefs { ai_model: String::new(), ..Prefs::default() };
        assert_eq!(Prefs::from_map(&p.to_map()).ai_model, "");
    }

    #[test]
    fn garbage_is_corrected_rather_than_trusted() {
        let p = Prefs {
            alpaca_feed: "nasdaq-direct".into(),
            bar_timeframe: "3Min".into(),
            ai_provider: "not-a-provider".into(),
            ai_model: "  spaced  ".into(),
            ai_effort: "ludicrous".into(),
            ai_interval_sec: 1,
        }
        .sanitized();

        let d = Prefs::default();
        assert_eq!(p.alpaca_feed, d.alpaca_feed);
        assert_eq!(p.bar_timeframe, d.bar_timeframe);
        assert_eq!(p.ai_provider, d.ai_provider);
        assert_eq!(p.ai_effort, d.ai_effort);
        assert_eq!(p.ai_model, "spaced");
        assert_eq!(p.ai_interval_sec, 30, "a 1s poll spends money to re-read the same bar");
    }

    #[test]
    fn an_older_blob_missing_fields_still_loads() {
        let m = BTreeMap::from([("alpacaFeed".to_string(), "sip".to_string())]);
        let p = Prefs::from_map(&m);
        assert_eq!(p.alpaca_feed, "sip");
        assert_eq!(p.bar_timeframe, Prefs::default().bar_timeframe);
        assert_eq!(p.ai_interval_sec, Prefs::default().ai_interval_sec);
    }

    #[test]
    fn timeframe_maps_to_the_kraken_interval() {
        for (label, minutes) in TIMEFRAMES {
            let p = Prefs { bar_timeframe: label.into(), ..Prefs::default() };
            assert_eq!(p.kraken_interval(), minutes, "{label}");
        }
    }

    #[test]
    fn survives_a_real_trip_through_the_os_keychain() {
        // The whole promise of the settings page is "save it once and it comes
        // back on every start". That promise runs through the OS credential
        // store, so exercise the actual store rather than a map in memory.
        let slot = "prefs-test-ci-throwaway";
        let _ = crate::vault::clear(slot);

        let saved = Prefs {
            alpaca_feed: "sip".into(),
            bar_timeframe: "15Min".into(),
            ai_provider: "anthropic".into(),
            ai_model: "claude-opus-5".into(),
            ai_effort: "high".into(),
            ai_interval_sec: 600,
        };
        crate::vault::save(slot, &saved.to_map()).expect("save");

        let loaded = Prefs::from_map(&crate::vault::get(slot).expect("get"));
        assert_eq!(loaded, saved);
        assert_eq!(loaded.kraken_interval(), 15);
        assert_eq!(loaded.effort(), crate::llm::Effort::High);

        crate::vault::clear(slot).expect("clear");
        // A cleared slot must fall back to defaults, not to the last value.
        assert!(crate::vault::get(slot).is_none());
    }

    #[test]
    fn effort_and_provider_resolve() {
        let p = Prefs { ai_effort: "xhigh".into(), ai_provider: "claude".into(), ..Prefs::default() };
        assert_eq!(p.effort(), crate::llm::Effort::Xhigh);
        assert_eq!(p.provider(), crate::llm::Provider::Anthropic);
    }
}
