//! How an alert looks on the phone: one card per alert.
//!
//! ```text
//! <b>🛑 Floor hit</b>                      a bold title with one leading emoji
//! Momentum stopped at its loss floor.      one short summary line
//! <pre>Equity      $9,412.30               aligned key numbers, signs,
//! P&amp;L      -$587.70 -5.88 % 🔴         thousands separators, %, and a
//! Trades             14</pre>              green or red circle for plus/minus
//! <i>Pythia</i>                            an optional footer
//! ```
//!
//! Telegram gets HTML (`parse_mode: HTML`) with every piece of text escaped;
//! Discord and Slack get the same card in their markdown. A post holds one or
//! more cards and is fitted to the destination's length limit by shortening
//! tables and, as a last resort, leaving whole cards out with a count, so a
//! tag is never cut in half.

use serde::Serialize;

use super::i18n::Lang;
use super::AlertFormat;

/// Escape text for Telegram's HTML parse mode: `&`, `<` and `>` (quotes need
/// no escaping outside attributes, and a card has none).
pub fn esc(s: &str) -> String {
    let mut out = String::with_capacity(s.len());
    for c in s.chars() {
        match c {
            '&' => out.push_str("&amp;"),
            '<' => out.push_str("&lt;"),
            '>' => out.push_str("&gt;"),
            _ => out.push(c),
        }
    }
    out
}

/// `12345.678` with `dp` decimals and thousands separators: `12,345.68`.
pub fn thousands(v: f64, dp: usize) -> String {
    if !v.is_finite() {
        return "n/a".into();
    }
    let s = format!("{:.*}", dp, v.abs());
    let (int, frac) = match s.split_once('.') {
        Some((i, f)) => (i.to_string(), Some(f.to_string())),
        None => (s.clone(), None),
    };
    let mut grouped = String::new();
    for (i, c) in int.chars().enumerate() {
        if i > 0 && (int.len() - i) % 3 == 0 {
            grouped.push(',');
        }
        grouped.push(c);
    }
    let neg = v < 0.0 && s.chars().any(|c| c.is_ascii_digit() && c != '0');
    let mut out = String::new();
    if neg {
        out.push('-');
    }
    out.push_str(&grouped);
    if let Some(f) = frac {
        out.push('.');
        out.push_str(&f);
    }
    out
}

/// Dollars with `dp` decimals: `$12,345.68`; a negative amount is `-$12.30`.
pub fn money(v: f64, dp: usize) -> String {
    let t = thousands(v, dp);
    match t.strip_prefix('-') {
        Some(rest) => format!("-${rest}"),
        None => format!("${t}"),
    }
}

/// `$12,345.68`; a negative amount is `-$12.30`.
pub fn usd(v: f64) -> String {
    money(v, 2)
}

/// `+$12.30` or `-$12.30`.
pub fn signed_usd(v: f64) -> String {
    if v < 0.0 && usd(v).starts_with('-') {
        usd(v)
    } else {
        format!("+{}", usd(v.abs()))
    }
}

/// `+1.20 %` or `-0.45 %`.
pub fn signed_pct(v: f64, dp: usize) -> String {
    if !v.is_finite() {
        return "n/a".into();
    }
    let t = thousands(v, dp);
    if t.starts_with('-') {
        format!("{t} %")
    } else {
        format!("+{t} %")
    }
}

/// A coin amount without trailing noise: up to 8 decimals for small amounts.
pub fn qty(v: f64) -> String {
    let a = v.abs();
    let dp = if a >= 1000.0 {
        0
    } else if a >= 1.0 {
        4
    } else {
        8
    };
    let s = thousands(v, dp);
    if s.contains('.') {
        s.trim_end_matches('0').trim_end_matches('.').to_string()
    } else {
        s
    }
}

/// A price: fewer decimals the larger it is.
pub fn price(v: f64) -> String {
    let a = v.abs();
    let dp = if a >= 1.0 {
        2
    } else if a >= 0.01 {
        4
    } else {
        6
    };
    money(v, dp)
}

/// Whether a number is good, bad or neither, shown as a circle.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Default)]
#[serde(rename_all = "camelCase")]
pub enum Tone {
    Up,
    Down,
    Flat,
    #[default]
    None,
}

impl Tone {
    /// Up for a positive number, down for a negative one, flat for zero.
    pub fn of(v: f64) -> Self {
        if !v.is_finite() || v.abs() < 1e-9 {
            Tone::Flat
        } else if v > 0.0 {
            Tone::Up
        } else {
            Tone::Down
        }
    }

    pub fn dot(self) -> &'static str {
        match self {
            Tone::Up => "🟢",
            Tone::Down => "🔴",
            Tone::Flat => "⚪",
            Tone::None => "",
        }
    }
}

/// One aligned line of numbers: `Equity   $9,412.30`.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct Row {
    pub label: String,
    pub value: String,
    #[serde(skip_serializing_if = "is_none_tone")]
    pub tone: Tone,
}

fn is_none_tone(t: &Tone) -> bool {
    *t == Tone::None
}

impl Row {
    pub fn new(label: impl Into<String>, value: impl Into<String>) -> Self {
        Self { label: label.into(), value: value.into(), tone: Tone::None }
    }
    /// A row with a circle for the sign of `v`.
    pub fn toned(label: impl Into<String>, value: impl Into<String>, v: f64) -> Self {
        Self { label: label.into(), value: value.into(), tone: Tone::of(v) }
    }
}

/// A small table: the first column left-aligned, the others right-aligned.
#[derive(Debug, Clone, PartialEq, Serialize, Default)]
pub struct Table {
    pub header: Vec<String>,
    pub rows: Vec<Vec<String>>,
    /// Rows left out to fit; said under the table.
    pub more: usize,
}

/// One alert as it is shown.
#[derive(Debug, Clone, PartialEq, Serialize, Default)]
pub struct Card {
    pub emoji: String,
    pub title: String,
    pub summary: Option<String>,
    pub rows: Vec<Row>,
    pub table: Option<Table>,
    pub footer: Option<String>,
    /// The table above the numbers (a rebalance: the trades, then the totals).
    #[serde(skip_serializing_if = "std::ops::Not::not")]
    pub table_first: bool,
    /// The language of its own small words ("+3 more").
    #[serde(skip)]
    pub lang: Lang,
}

/// Width in monospace cells. Emoji are two cells wide on a phone.
fn cells(s: &str) -> usize {
    s.chars().map(|c| if (c as u32) >= 0x1F000 { 2 } else { 1 }).sum()
}

fn pad_right(s: &str, w: usize) -> String {
    format!("{s}{}", " ".repeat(w.saturating_sub(cells(s))))
}

fn pad_left(s: &str, w: usize) -> String {
    format!("{}{s}", " ".repeat(w.saturating_sub(cells(s))))
}

impl Card {
    pub fn new(emoji: impl Into<String>, title: impl Into<String>) -> Self {
        Self { emoji: emoji.into(), title: title.into(), ..Default::default() }
    }
    pub fn summary(mut self, s: impl Into<String>) -> Self {
        let s = s.into();
        self.summary = (!s.trim().is_empty()).then_some(s);
        self
    }
    pub fn row(mut self, r: Row) -> Self {
        self.rows.push(r);
        self
    }
    pub fn footer(mut self, s: impl Into<String>) -> Self {
        let s = s.into();
        self.footer = (!s.trim().is_empty()).then_some(s);
        self
    }

    /// The key numbers as plain aligned lines (no markup, not escaped).
    fn rows_block(&self) -> Option<String> {
        if self.rows.is_empty() {
            return None;
        }
        let lw = self.rows.iter().map(|r| cells(&r.label)).max().unwrap_or(0);
        let vw = self.rows.iter().map(|r| cells(&r.value)).max().unwrap_or(0);
        let lines: Vec<String> = self
            .rows
            .iter()
            .map(|r| {
                let line = format!("{}  {}", pad_right(&r.label, lw), pad_left(&r.value, vw));
                match r.tone.dot() {
                    "" => line.trim_end().to_string(),
                    d => format!("{line} {d}"),
                }
            })
            .collect();
        Some(lines.join("\n"))
    }

    /// The table as plain aligned lines.
    fn table_block(&self) -> Option<String> {
        let t = self.table.as_ref().filter(|t| !t.rows.is_empty())?;
        let ncol = t.rows.iter().map(Vec::len).chain(std::iter::once(t.header.len())).max().unwrap_or(0);
        let mut w = vec![0usize; ncol];
        for r in std::iter::once(&t.header).chain(t.rows.iter()) {
            for (i, c) in r.iter().enumerate() {
                w[i] = w[i].max(cells(c));
            }
        }
        // A column of numbers is right-aligned, a column of words left-aligned.
        let numeric: Vec<bool> = (0..ncol)
            .map(|i| {
                i > 0
                    && t.rows.iter().all(|r| {
                        r.get(i).is_none_or(|c| c.is_empty() || c.starts_with(|ch: char| ch.is_ascii_digit() || "+-$".contains(ch)))
                    })
            })
            .collect();
        let line = |r: &Vec<String>| -> String {
            let cols: Vec<String> = (0..ncol)
                .map(|i| {
                    let c = r.get(i).map(String::as_str).unwrap_or("");
                    if numeric[i] {
                        pad_left(c, w[i])
                    } else {
                        pad_right(c, w[i])
                    }
                })
                .collect();
            cols.join(" ").trim_end().to_string()
        };
        let mut lines = Vec::new();
        if !t.header.is_empty() {
            lines.push(line(&t.header));
        }
        lines.extend(t.rows.iter().map(line));
        if t.more > 0 {
            lines.push(super::i18n::more_rows(self.lang, t.more));
        }
        Some(lines.join("\n"))
    }

    /// The numbers and the table, in the card's order.
    fn blocks(&self) -> Vec<String> {
        let (a, b) = (self.rows_block(), self.table_block());
        let both = if self.table_first { [b, a] } else { [a, b] };
        both.into_iter().flatten().collect()
    }

    /// The card in one destination's markup.
    pub fn render(&self, format: AlertFormat) -> String {
        let head = if self.emoji.is_empty() { self.title.clone() } else { format!("{} {}", self.emoji, self.title) };
        let mut parts: Vec<String> = Vec::new();
        match format {
            AlertFormat::Telegram => {
                parts.push(format!("<b>{}</b>", esc(&head)));
                if let Some(s) = &self.summary {
                    parts.push(esc(s));
                }
                for block in self.blocks() {
                    parts.push(format!("<pre>{}</pre>", esc(&block)));
                }
                if let Some(f) = &self.footer {
                    parts.push(format!("<i>{}</i>", esc(f)));
                }
            }
            AlertFormat::Discord => {
                parts.push(format!("**{head}**"));
                if let Some(s) = &self.summary {
                    parts.push(s.clone());
                }
                for block in self.blocks() {
                    parts.push(format!("```\n{block}\n```"));
                }
                if let Some(f) = &self.footer {
                    parts.push(format!("*{f}*"));
                }
            }
            AlertFormat::Slack => {
                parts.push(format!("*{head}*"));
                if let Some(s) = &self.summary {
                    parts.push(s.clone());
                }
                for block in self.blocks() {
                    parts.push(format!("```{block}```"));
                }
                if let Some(f) = &self.footer {
                    parts.push(format!("_{f}_"));
                }
            }
        }
        parts.join("\n")
    }
}

/// Several cards as one post, fitted under `limit` characters: tables are
/// shortened first (the rows left out are counted under them), then cards
/// are left out from the end with a line that says how many. Never cuts
/// inside a tag.
pub fn render_post(cards: &[Card], format: AlertFormat, limit: usize) -> String {
    let lang = cards.first().map(|c| c.lang).unwrap_or_default();
    let join = |cs: &[Card], dropped: usize| -> String {
        let mut s: Vec<String> = cs.iter().map(|c| c.render(format)).collect();
        if dropped > 0 {
            let line = super::i18n::more_alerts(lang, dropped);
            s.push(match format {
                AlertFormat::Telegram => format!("<i>{}</i>", esc(&line)),
                AlertFormat::Discord => format!("*{line}*"),
                AlertFormat::Slack => format!("_{line}_"),
            });
        }
        s.join("\n\n")
    };
    let mut cards: Vec<Card> = cards.to_vec();
    let fits = |s: &str| s.chars().count() <= limit;
    let mut out = join(&cards, 0);
    if fits(&out) {
        return out;
    }
    // Shorten the longest table, three rows at a time, down to three rows.
    loop {
        let longest = cards
            .iter_mut()
            .filter_map(|c| c.table.as_mut())
            .filter(|t| t.rows.len() > 3)
            .max_by_key(|t| t.rows.len());
        let Some(t) = longest else { break };
        let cut = 3.min(t.rows.len() - 3);
        for _ in 0..cut {
            t.rows.pop();
        }
        t.more += cut;
        out = join(&cards, 0);
        if fits(&out) {
            return out;
        }
    }
    // Then leave cards out from the end.
    let mut dropped = 0;
    while cards.len() > 1 {
        cards.pop();
        dropped += 1;
        out = join(&cards, dropped);
        if fits(&out) {
            return out;
        }
    }
    // One card still too long: its summary and footer go, then its rows.
    if let Some(c) = cards.first_mut() {
        c.footer = None;
        if let Some(s) = c.summary.take() {
            let short: String = s.chars().take(200).collect();
            c.summary = Some(if short.len() < s.len() { format!("{short}…") } else { short });
        }
        while !fits(&join(&cards, dropped)) && !cards[0].rows.is_empty() {
            cards[0].rows.pop();
        }
        while !fits(&join(&cards, dropped)) && cards[0].table.as_ref().is_some_and(|t| !t.rows.is_empty()) {
            if let Some(t) = cards[0].table.as_mut() {
                t.rows.pop();
                t.more += 1;
            }
        }
        if !fits(&join(&cards, dropped)) {
            cards[0].table = None;
            cards[0].summary = None;
        }
    }
    join(&cards, dropped)
}

/// A post's text without markup, for the app's list of recent alerts.
pub fn plain(text: &str) -> String {
    let mut out = String::with_capacity(text.len());
    let mut in_tag = false;
    for c in text.chars() {
        match c {
            '<' => in_tag = true,
            '>' if in_tag => in_tag = false,
            _ if !in_tag => out.push(c),
            _ => {}
        }
    }
    out.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&").replace("```", "").replace("**", "")
}
