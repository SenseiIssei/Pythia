//! A tax record of every real fill.
//!
//! The engine keeps only the last few hundred orders, which is fine for a
//! screen and useless for a tax return. Every real (live) fill is therefore
//! also handed to the host, which appends it to `fills.jsonl` and never
//! rewrites it. From that file:
//!
//! * `cointracking_csv` writes the CoinTracking import format, which Blockpit,
//!   CoinTracking and most German tax tools read. Those tools do the euro
//!   conversion at each trade's own rate and the lot matching their users'
//!   tax office expects; Pythia's job is a complete and exact record.
//! * `fifo_summary` is a preview in the quote currency: first-in, first-out
//!   lots per asset, gains split by whether the lot was held for more than a
//!   year (for crypto in Germany, § 23 EStG: gains on lots held over a year
//!   are tax-free, shorter ones count against a 1,000 EUR yearly exemption
//!   limit). A preview, not tax advice; the tax tool's numbers are the ones
//!   that count.
//!
//! Paper fills are never written here.

use std::collections::{BTreeMap, HashMap, VecDeque};
use std::io::Write;
use std::path::Path;

use serde::{Deserialize, Serialize};

use crate::connectors::{Side, Venue};

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct FillRecord {
    /// Epoch millis of the fill.
    pub ts: i64,
    pub venue: Venue,
    pub market_id: String,
    /// "BTC/USD" for crypto, the ticker for equities.
    pub symbol: String,
    pub side: Side,
    pub qty: f64,
    pub price: f64,
    /// In the quote currency.
    pub fee: f64,
    pub strategy_id: String,
    pub order_id: String,
}

impl FillRecord {
    /// (asset, quote currency). Equities are quoted in USD.
    pub fn assets(&self) -> (String, String) {
        match self.symbol.split_once('/') {
            Some((b, q)) => (b.to_string(), q.to_string()),
            None => (self.symbol.clone(), "USD".to_string()),
        }
    }
}

/// Append fills to the record. One JSON object per line; never rewritten.
pub fn append(path: &Path, fills: &[FillRecord]) -> std::io::Result<()> {
    if fills.is_empty() {
        return Ok(());
    }
    if let Some(dir) = path.parent() {
        std::fs::create_dir_all(dir)?;
    }
    let mut f = std::fs::OpenOptions::new().create(true).append(true).open(path)?;
    for r in fills {
        writeln!(f, "{}", serde_json::to_string(r).map_err(std::io::Error::other)?)?;
    }
    f.sync_all()
}

/// Hand the engine's new real fills to the record. Hosts call this every tick;
/// a failed write puts them back so the next tick retries rather than losing them.
pub fn flush(engine: &std::sync::Mutex<crate::engine::Engine>, path: &Path) {
    let fills = { engine.lock().unwrap().drain_fill_records() };
    if fills.is_empty() {
        return;
    }
    if let Err(e) = append(path, &fills) {
        tracing::error!("tax record {} not written, will retry: {e}", path.display());
        engine.lock().unwrap().requeue_fill_records(fills);
    }
}

/// Every fill in the record, oldest first. A damaged line is skipped and
/// counted, never silently dropped. A line that parses but cannot be a fill
/// (no quantity, a price that is not a number) counts as damaged too: one zero
/// quantity divides to NaN and turns every later gain on that asset into NaN.
pub fn read_all(path: &Path) -> (Vec<FillRecord>, usize) {
    let Ok(text) = std::fs::read_to_string(path) else { return (vec![], 0) };
    let mut bad = 0;
    let usable = |r: &FillRecord| r.qty.is_finite() && r.qty > 0.0 && r.price.is_finite() && r.price >= 0.0 && r.fee.is_finite();
    let mut out: Vec<FillRecord> = text
        .lines()
        .filter(|l| !l.trim().is_empty())
        .filter_map(|l| serde_json::from_str::<FillRecord>(l).ok().filter(usable).or_else(|| {
            bad += 1;
            None
        }))
        .collect();
    out.sort_by_key(|r| r.ts);
    (out, bad)
}

/// Up to 10 decimals, trailing zeros dropped: exact enough for any coin, no float noise.
fn num(x: f64) -> String {
    let s = format!("{x:.10}");
    let s = s.trim_end_matches('0').trim_end_matches('.');
    if s.is_empty() || s == "-" { "0".into() } else { s.to_string() }
}

fn exchange_name(v: Venue, crypto_exchange: &str) -> String {
    match v {
        Venue::Alpaca => "Alpaca".into(),
        Venue::Polymarket => "Polymarket".into(),
        _ => crypto_exchange.to_string(),
    }
}

/// The CoinTracking CSV import format, one "Trade" row per fill.
pub fn cointracking_csv(fills: &[FillRecord], crypto_exchange: &str) -> String {
    let mut s = String::from(
        "\"Type\",\"Buy Amount\",\"Buy Currency\",\"Sell Amount\",\"Sell Currency\",\"Fee\",\"Fee Currency\",\
         \"Exchange\",\"Trade-Group\",\"Comment\",\"Date\"\n",
    );
    for r in fills {
        let (asset, quote) = r.assets();
        let notional = r.qty * r.price;
        let (buy_amt, buy_cur, sell_amt, sell_cur) = match r.side {
            Side::Buy => (r.qty, asset.clone(), notional, quote.clone()),
            Side::Sell => (notional, quote.clone(), r.qty, asset.clone()),
        };
        let date = chrono::DateTime::from_timestamp_millis(r.ts)
            .map(|d| d.format("%Y-%m-%d %H:%M:%S").to_string())
            .unwrap_or_default();
        s.push_str(&format!(
            "\"Trade\",\"{}\",\"{buy_cur}\",\"{}\",\"{sell_cur}\",\"{}\",\"{quote}\",\"{}\",\"{}\",\"{}\",\"{date}\"\n",
            num(buy_amt),
            num(sell_amt),
            num(r.fee),
            exchange_name(r.venue, crypto_exchange),
            r.strategy_id,
            r.order_id,
        ));
    }
    s
}

#[derive(Debug, Clone, Default, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct YearSummary {
    pub year: i32,
    /// Gains and losses on lots held one year or less, in the quote currency, fees included.
    pub short_term: f64,
    /// On lots held longer than a year (tax-free for crypto in Germany).
    pub long_term: f64,
    pub disposals: usize,
    pub fees: f64,
}

#[derive(Debug, Clone, Default, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct TaxSummary {
    pub years: Vec<YearSummary>,
    /// Quantity still held per asset, from the record alone.
    pub open: BTreeMap<String, f64>,
    /// Sells that found no matching buy in the record (bought before Pythia
    /// or elsewhere). Their cost basis is unknown, so they are not in the gains.
    pub unmatched_sells: usize,
    pub fills: usize,
}

/// Held for more than a year: sold after the same calendar date one year
/// later (§ 23 EStG with § 188 BGB; a lot bought on 29 February has its year
/// end on 28 February). Counting 365 days instead called a sale on the
/// anniversary tax-free whenever the year held a 29 February. Dates are UTC.
fn held_over_a_year(bought_ms: i64, sold_ms: i64) -> bool {
    let date = |ms: i64| chrono::DateTime::from_timestamp_millis(ms).map(|d| d.date_naive());
    match (date(bought_ms), date(sold_ms)) {
        (Some(b), Some(s)) => b.checked_add_months(chrono::Months::new(12)).is_some_and(|end| s > end),
        _ => false,
    }
}

/// FIFO lots per asset, gains split by holding period. A preview in the quote currency.
pub fn fifo_summary(fills: &[FillRecord]) -> TaxSummary {
    struct Lot {
        qty: f64,
        cost_per_unit: f64,
        ts: i64,
    }
    let mut lots: HashMap<String, VecDeque<Lot>> = HashMap::new();
    let mut years: BTreeMap<i32, YearSummary> = BTreeMap::new();
    let mut unmatched = 0;
    for r in fills {
        let (asset, _) = r.assets();
        let year = chrono::DateTime::from_timestamp_millis(r.ts).map(|d| {
            use chrono::Datelike;
            d.year()
        });
        let y = years.entry(year.unwrap_or(0)).or_insert_with(|| YearSummary { year: year.unwrap_or(0), ..Default::default() });
        y.fees += r.fee;
        let q = lots.entry(asset).or_default();
        match r.side {
            Side::Buy => q.push_back(Lot { qty: r.qty, cost_per_unit: (r.qty * r.price + r.fee) / r.qty, ts: r.ts }),
            Side::Sell => {
                let proceeds_per_unit = (r.qty * r.price - r.fee) / r.qty;
                let mut left = r.qty;
                y.disposals += 1;
                while left > 1e-12 {
                    let Some(lot) = q.front_mut() else {
                        unmatched += 1;
                        break;
                    };
                    let take = left.min(lot.qty);
                    let gain = take * (proceeds_per_unit - lot.cost_per_unit);
                    if held_over_a_year(lot.ts, r.ts) {
                        y.long_term += gain;
                    } else {
                        y.short_term += gain;
                    }
                    lot.qty -= take;
                    left -= take;
                    if lot.qty <= 1e-12 {
                        q.pop_front();
                    }
                }
            }
        }
    }
    let open = lots
        .into_iter()
        .map(|(a, q)| (a, q.iter().map(|l| l.qty).sum::<f64>()))
        .filter(|(_, v)| *v > 1e-12)
        .collect();
    TaxSummary { years: years.into_values().collect(), open, unmatched_sells: unmatched, fills: fills.len() }
}

#[cfg(test)]
mod tests {
    use super::*;

    const DAY: i64 = 24 * 3_600_000;

    fn fill(ts: i64, side: Side, qty: f64, price: f64, fee: f64) -> FillRecord {
        FillRecord {
            ts,
            venue: Venue::Crypto,
            market_id: "crypto:BTC/USD".into(),
            symbol: "BTC/USD".into(),
            side,
            qty,
            price,
            fee,
            strategy_id: "lab:tsmom_regime".into(),
            order_id: format!("o{ts}"),
        }
    }

    // 2026-01-01T00:00:00Z
    const T0: i64 = 1_767_225_600_000;

    #[test]
    fn fifo_splits_gains_by_holding_period_and_counts_fees() {
        let fills = vec![
            fill(T0, Side::Buy, 1.0, 100.0, 1.0),               // cost 101 per unit
            fill(T0 + 10 * DAY, Side::Buy, 1.0, 200.0, 0.0),     // cost 200
            fill(T0 + 400 * DAY, Side::Sell, 1.5, 300.0, 3.0),   // proceeds 298 per unit
        ];
        let s = fifo_summary(&fills);
        let y = s.years.iter().find(|y| y.year == 2027).unwrap();
        // First lot (held 400 days): 1.0 * (298 - 101) = 197. Half of the second
        // (held 390 days): 0.5 * (298 - 200) = 49. Both over a year: long-term.
        assert!((y.long_term - 246.0).abs() < 1e-9, "{y:?}");
        assert_eq!(y.short_term, 0.0);
        assert_eq!(s.open.get("BTC").copied(), Some(0.5));
        assert_eq!(s.unmatched_sells, 0);
    }

    #[test]
    fn short_holds_are_short_term_and_unknown_cost_is_flagged() {
        let fills = vec![
            fill(T0, Side::Buy, 1.0, 100.0, 0.0),
            fill(T0 + 30 * DAY, Side::Sell, 2.0, 90.0, 0.0),
        ];
        let s = fifo_summary(&fills);
        assert!((s.years[0].short_term + 10.0).abs() < 1e-9);
        assert_eq!(s.unmatched_sells, 1, "the second BTC was bought outside the record");
    }

    fn at(date: &str) -> i64 {
        chrono::NaiveDate::parse_from_str(date, "%Y-%m-%d").unwrap().and_hms_opt(12, 0, 0).unwrap().and_utc().timestamp_millis()
    }

    #[test]
    fn the_year_is_a_calendar_year_even_when_it_holds_a_29_february() {
        // 2027-03-01 to 2028-03-01 is 366 days but still inside the year: taxable.
        let s = fifo_summary(&[fill(at("2027-03-01"), Side::Buy, 1.0, 100.0, 0.0), fill(at("2028-03-01"), Side::Sell, 1.0, 150.0, 0.0)]);
        assert_eq!((s.years[1].short_term, s.years[1].long_term), (50.0, 0.0), "{s:?}");
        // The day after, it is over a year.
        let s = fifo_summary(&[fill(at("2027-03-01"), Side::Buy, 1.0, 100.0, 0.0), fill(at("2028-03-02"), Side::Sell, 1.0, 150.0, 0.0)]);
        assert_eq!((s.years[1].short_term, s.years[1].long_term), (0.0, 50.0));
        // Bought on 29 February: the year ends on 28 February.
        assert!(!held_over_a_year(at("2028-02-29"), at("2029-02-28")));
        assert!(held_over_a_year(at("2028-02-29"), at("2029-03-01")));
    }

    #[test]
    fn a_fill_without_quantity_is_damaged_not_a_nan_in_every_later_gain() {
        let dir = std::env::temp_dir().join(format!("pythia-tax-nan-{}", std::process::id()));
        let path = dir.join("fills.jsonl");
        let _ = std::fs::remove_file(&path);
        append(&path, &[fill(T0, Side::Buy, 0.0, 100.0, 0.1), fill(T0 + DAY, Side::Buy, 1.0, 100.0, 0.0)]).unwrap();
        append(&path, &[fill(T0 + 2 * DAY, Side::Sell, 1.0, 110.0, 0.0)]).unwrap();
        let (fills, bad) = read_all(&path);
        assert_eq!((fills.len(), bad), (2, 1));
        let s = fifo_summary(&fills);
        assert!((s.years[0].short_term - 10.0).abs() < 1e-9, "{s:?}");
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn cointracking_rows_have_the_right_direction() {
        let csv = cointracking_csv(&[fill(T0, Side::Buy, 0.5, 100.0, 0.2), fill(T0 + DAY, Side::Sell, 0.5, 110.0, 0.2)], "Kraken");
        let lines: Vec<&str> = csv.lines().collect();
        assert!(lines[0].starts_with("\"Type\""));
        assert!(lines[1].starts_with("\"Trade\",\"0.5\",\"BTC\",\"50\",\"USD\""));
        assert!(lines[2].starts_with("\"Trade\",\"55\",\"USD\",\"0.5\",\"BTC\",\"0.2\""), "{}", lines[2]);
        assert!(lines[1].contains("\"Kraken\"") && lines[1].contains("2026-01-01 00:00:00"));
    }

    #[test]
    fn the_record_is_append_only_and_survives_a_bad_line() {
        let dir = std::env::temp_dir().join(format!("pythia-tax-{}", std::process::id()));
        let path = dir.join("fills.jsonl");
        let _ = std::fs::remove_file(&path);
        append(&path, &[fill(T0, Side::Buy, 1.0, 100.0, 0.0)]).unwrap();
        std::fs::OpenOptions::new().append(true).open(&path).unwrap().write_all(b"not json\n").unwrap();
        append(&path, &[fill(T0 + DAY, Side::Sell, 1.0, 110.0, 0.0)]).unwrap();
        let (fills, bad) = read_all(&path);
        assert_eq!(fills.len(), 2);
        assert_eq!(bad, 1);
        let _ = std::fs::remove_dir_all(&dir);
    }
}
