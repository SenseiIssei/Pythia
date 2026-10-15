//! Big moves: a coin an autopilot holds, or an autopilot's equity, moving more
//! than the set % within an hour or a day.
//!
//! The host samples prices and equities about once a minute and hands them to
//! [`MoveWatch::check`]. A move is measured against the value one hour (or 24
//! hours) ago, and only once that much history exists, so a restart never
//! reads the first minutes as a move. The same move is said once per window;
//! it is said again only when it grew by another full threshold.

use std::collections::{HashMap, VecDeque};

use super::card::{price, signed_pct, usd, Row};
use super::{AlertCategory, AlertEvent, AlertKind};

const HOUR_MS: i64 = 3_600_000;
const DAY_MS: i64 = 24 * HOUR_MS;
/// History kept per subject: a day and a bit.
const KEEP_MS: i64 = DAY_MS + 2 * HOUR_MS;
/// Samples closer together than this are one sample.
const MIN_STEP_MS: i64 = 30_000;
/// The oldest sample may be this much younger than the window and still count.
const SLACK_MS: i64 = 10 * 60_000;
/// A subject not seen for this long is forgotten.
const FORGET_MS: i64 = 2 * HOUR_MS;

/// What moved.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum MoveSubject {
    /// A coin an autopilot holds; `value` is its price.
    Coin,
    /// An autopilot's equity; `value` is in $.
    Equity,
}

/// One sample handed in by the host.
#[derive(Debug, Clone, PartialEq)]
pub struct MoveInput {
    /// Stable id: the market id, or `ap:<id>` for an autopilot.
    pub key: String,
    /// What the card calls it: `BTC`, or the autopilot's name.
    pub label: String,
    /// For a coin, who holds it (the autopilot names).
    pub held_by: String,
    pub subject: MoveSubject,
    pub value: f64,
}

#[derive(Debug, Default)]
pub struct MoveWatch {
    series: HashMap<String, VecDeque<(i64, f64)>>,
    seen: HashMap<String, i64>,
    /// (key, window) to (when, % said).
    said: HashMap<(String, &'static str), (i64, f64)>,
}

impl MoveWatch {
    /// The value at or just before `at`, if the history reaches back that far.
    fn value_at(s: &VecDeque<(i64, f64)>, at: i64) -> Option<f64> {
        let first = s.front()?;
        if first.0 > at + SLACK_MS {
            return None;
        }
        s.iter().take_while(|(t, _)| *t <= at).last().or(Some(first)).map(|(_, v)| *v)
    }

    /// Record the samples and return an alert for each move past its threshold.
    pub fn check(&mut self, inputs: &[MoveInput], hour_pct: f64, day_pct: f64, now: i64) -> Vec<AlertEvent> {
        let mut out = Vec::new();
        for inp in inputs {
            if !(inp.value.is_finite() && inp.value > 0.0) {
                continue;
            }
            self.seen.insert(inp.key.clone(), now);
            let s = self.series.entry(inp.key.clone()).or_default();
            if s.back().is_none_or(|(t, _)| now - t >= MIN_STEP_MS) {
                s.push_back((now, inp.value));
            }
            while s.front().is_some_and(|(t, _)| now - t > KEEP_MS) {
                s.pop_front();
            }
            for (window, span, threshold) in [("1 h", HOUR_MS, hour_pct), ("24 h", DAY_MS, day_pct)] {
                if threshold <= 0.0 {
                    continue;
                }
                let Some(then) = Self::value_at(s, now - span) else { continue };
                if then <= 0.0 {
                    continue;
                }
                let pct = (inp.value / then - 1.0) * 100.0;
                if pct.abs() < threshold {
                    continue;
                }
                let slot = (inp.key.clone(), window);
                if let Some((t, last)) = self.said.get(&slot) {
                    let same_way = last.signum() == pct.signum();
                    if now - t < span && same_way && pct.abs() < last.abs() + threshold {
                        continue;
                    }
                }
                self.said.insert(slot, (now, pct));
                out.push(move_event(inp, window, then, pct, threshold));
            }
        }
        // Forget what is no longer held or running.
        let gone: Vec<String> = self.seen.iter().filter(|(_, t)| now - **t > FORGET_MS).map(|(k, _)| k.clone()).collect();
        for k in gone {
            self.seen.remove(&k);
            self.series.remove(&k);
            self.said.retain(|(key, _), _| *key != k);
        }
        out
    }
}

fn move_event(inp: &MoveInput, window: &'static str, then: f64, pct: f64, threshold: f64) -> AlertEvent {
    let up = pct > 0.0;
    let emoji = if up { "📈" } else { "📉" };
    let (title, summary, rows) = match inp.subject {
        MoveSubject::Coin => (
            format!("{} {} in {window}", inp.label, signed_pct(pct, 1)),
            if inp.held_by.is_empty() { String::new() } else { format!("Held by {}.", inp.held_by) },
            vec![
                Row::new("Now", price(inp.value)),
                Row::new(format!("{window} ago"), price(then)),
                Row::toned("Change", signed_pct(pct, 2), pct),
            ],
        ),
        MoveSubject::Equity => (
            format!("{} equity {} in {window}", inp.label, signed_pct(pct, 1)),
            "The autopilot's equity, positions at their price now.".to_string(),
            vec![
                Row::new("Equity", usd(inp.value)),
                Row::new(format!("{window} ago"), usd(then)),
                Row::toned("Change", format!("{} {}", super::card::signed_usd(inp.value - then), signed_pct(pct, 2)), pct),
            ],
        ),
    };
    let text = format!("{title}. {summary}").trim().to_string();
    let mut ev = AlertEvent::new(AlertKind::BigMove, format!("move:{}:{window}:{}", inp.key, if up { "up" } else { "down" }), text)
        .titled(title)
        .with_summary(summary)
        .with_rows(rows)
        .in_category(AlertCategory::BigMoves)
        .with_emoji(emoji);
    // An autopilot's equity moving twice the threshold is worth waking up for.
    if inp.subject == MoveSubject::Equity && pct.abs() >= 2.0 * threshold {
        ev = ev.urgent();
    }
    ev
}
