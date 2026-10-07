//! A read-only view of the research lab for the Lab page.
//!
//! The lab runs on the VPS and writes plain files: paper journals under
//! `paper/<book>/journal.csv` (+ `state.json`), experiment reports under
//! `reports/<name>/latest.json`. The desktop app reads the synced copy, the
//! server its own data folder. Nothing here writes anything.
//!
//! Where: `PYTHIA_DATA`, else the parent of `PYTHIA_MODELS` (the lab keeps
//! models, paper books and reports under one root).

use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

use serde::Serialize;
use serde_json::Value;

pub fn data_dir() -> Option<PathBuf> {
    if let Ok(d) = std::env::var("PYTHIA_DATA") {
        return Some(d.into());
    }
    let models = std::env::var("PYTHIA_MODELS").ok()?;
    Path::new(&models).parent().map(Path::to_path_buf)
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct PaperBook {
    pub name: String,
    pub variant: String,
    pub started: String,
    pub days: usize,
    pub equity: Vec<f64>,
    pub dates: Vec<String>,
    pub return_pct: f64,
    /// The last journal row that changed the book (rebalance), column -> value.
    pub last_rebalance: BTreeMap<String, String>,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct LabReport {
    pub name: String,
    pub updated_ms: i64,
    pub verdict: String,
}

#[derive(Debug, Clone, Default, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct LabStatus {
    pub found: bool,
    pub dir: String,
    pub books: Vec<PaperBook>,
    pub reports: Vec<LabReport>,
}

/// One CSV line, honouring double quotes (the weights column holds JSON with commas).
fn split_csv(line: &str) -> Vec<String> {
    let mut out = vec![];
    let mut cur = String::new();
    let mut quoted = false;
    let mut chars = line.chars().peekable();
    while let Some(c) = chars.next() {
        match c {
            '"' if quoted && chars.peek() == Some(&'"') => {
                cur.push('"');
                chars.next();
            }
            '"' => quoted = !quoted,
            ',' if !quoted => out.push(std::mem::take(&mut cur)),
            _ => cur.push(c),
        }
    }
    out.push(cur);
    out
}

fn read_book(dir: &Path) -> Option<PaperBook> {
    let text = std::fs::read_to_string(dir.join("journal.csv")).ok()?;
    let mut lines = text.lines().filter(|l| !l.trim().is_empty());
    let header = split_csv(lines.next()?);
    let rows: Vec<BTreeMap<String, String>> =
        lines.map(|l| header.iter().cloned().zip(split_csv(l)).collect()).collect();
    if rows.is_empty() {
        return None;
    }
    let equity: Vec<f64> = rows.iter().filter_map(|r| r.get("equity")?.parse().ok()).collect();
    let dates: Vec<String> = rows.iter().filter_map(|r| r.get("date").cloned()).collect();
    let state: Value = std::fs::read_to_string(dir.join("state.json"))
        .ok()
        .and_then(|t| serde_json::from_str(&t).ok())
        .unwrap_or(Value::Null);
    let changed = |r: &&BTreeMap<String, String>| {
        r.get("rebalanced").map(|v| v == "True" || v == "true").unwrap_or(false)
            || r.get("turnover").and_then(|v| v.parse::<f64>().ok()).map(|t| t > 0.01).unwrap_or(false)
    };
    // Every lab paper book starts at 10,000 (START_EQUITY in lab/paper).
    let start = 10_000.0;
    Some(PaperBook {
        name: dir.file_name()?.to_string_lossy().into_owned(),
        variant: state.get("variant").and_then(Value::as_str).unwrap_or_default().to_string(),
        started: state.get("started").and_then(Value::as_str).unwrap_or_default().chars().take(10).collect(),
        days: rows.len(),
        return_pct: equity.last().map(|e| (e / start - 1.0) * 100.0).unwrap_or(0.0),
        last_rebalance: rows.iter().rev().find(changed).cloned().unwrap_or_default(),
        equity,
        dates,
    })
}

fn verdict_of(name: &str, v: &Value) -> String {
    if let Some(s) = v.get("verdict").and_then(Value::as_str) {
        return s.replace("**", "");
    }
    let f = |v: &Value, k: &str| v.get(k).and_then(Value::as_f64).unwrap_or(f64::NAN);
    match name {
        "carry" => {
            let c = v.get("chosen").cloned().unwrap_or(Value::Null);
            format!(
                "Picked in-sample: {}. Out of sample {:.1} % a year on capital, Sharpe {:.1}. Too thin to build perpetuals for.",
                c.get("variant").and_then(Value::as_str).unwrap_or("?"),
                f(&c, "oos_apr") * 100.0,
                f(&c, "oos_sharpe")
            )
        }
        "momentum2" => v
            .get("details")
            .and_then(Value::as_array)
            .map(|ds| {
                ds.iter()
                    .map(|d| {
                        format!(
                            "{}: out of sample Sharpe {:.2}, drawdown {:.0} %, deflated p {:.2}.",
                            d.get("pick").and_then(Value::as_str).unwrap_or("?"),
                            f(d, "oos_sharpe"),
                            f(d, "oos_max_dd") * 100.0,
                            f(d, "deflated_p")
                        )
                    })
                    .collect::<Vec<_>>()
                    .join(" ")
            })
            .unwrap_or_default(),
        "paper_review" => v
            .get("books")
            .and_then(Value::as_array)
            .map(|bs| {
                bs.iter()
                    .map(|b| {
                        format!(
                            "{}: paper {:+.2} % vs backtest {:+.2} %, gate 7 {}.",
                            b.get("book").and_then(Value::as_str).unwrap_or("?"),
                            f(b, "paper_return_pct"),
                            f(b, "backtest_return_pct"),
                            b.get("gate7").and_then(Value::as_str).unwrap_or("?")
                        )
                    })
                    .collect::<Vec<_>>()
                    .join(" ")
            })
            .unwrap_or_default(),
        n if n.starts_with("pythia_net") => format!(
            "Rank-IC {:.3} out of sample (t {:.1}); M2 reaches 0.142.",
            f(v, "rank_ic"),
            f(v, "rank_ic_t")
        ),
        "vol_1h" => format!(
            "LGBM {} HAR by {:.1} % QLIKE out of sample (DM p {:.2e}).",
            if v.get("passed").and_then(Value::as_bool) == Some(true) { "beats" } else { "does not clearly beat" },
            v.get("qlike_gain").and_then(Value::as_f64).unwrap_or(0.0) * 100.0,
            v.get("dm_p").and_then(Value::as_f64).unwrap_or(1.0)
        ),
        _ => "See the report on the lab machine.".into(),
    }
}

pub fn status() -> LabStatus {
    let Some(root) = data_dir() else { return LabStatus::default() };
    let mut out = LabStatus { found: root.exists(), dir: root.display().to_string(), ..Default::default() };
    if let Ok(entries) = std::fs::read_dir(root.join("paper")) {
        let mut books: Vec<PaperBook> = entries.flatten().filter_map(|e| read_book(&e.path())).collect();
        books.sort_by(|a, b| a.name.cmp(&b.name));
        out.books = books;
    }
    if let Ok(entries) = std::fs::read_dir(root.join("reports")) {
        for e in entries.flatten() {
            let p = e.path().join("latest.json");
            let Ok(text) = std::fs::read_to_string(&p) else { continue };
            let Ok(v) = serde_json::from_str::<Value>(&text) else { continue };
            let name = e.file_name().to_string_lossy().into_owned();
            let updated_ms = std::fs::metadata(&p)
                .and_then(|m| m.modified())
                .ok()
                .and_then(|t| t.duration_since(std::time::UNIX_EPOCH).ok())
                .map(|d| d.as_millis() as i64)
                .unwrap_or(0);
            out.reports.push(LabReport { verdict: verdict_of(&name, &v), name, updated_ms });
        }
        out.reports.sort_by(|a, b| b.updated_ms.cmp(&a.updated_ms));
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn csv_keeps_quoted_commas() {
        let row = split_csv(r#"2026-10-06,9993.51,"{""BTC"": 0.05, ""ETH"": 0.04}",20"#);
        assert_eq!(row.len(), 4);
        assert_eq!(row[2], r#"{"BTC": 0.05, "ETH": 0.04}"#);
    }

    #[test]
    fn reads_a_book_and_its_last_rebalance() {
        let dir = std::env::temp_dir().join(format!("pythia-labview-{}", std::process::id()));
        let book = dir.join("paper").join("demo");
        std::fs::create_dir_all(&book).unwrap();
        std::fs::write(
            book.join("journal.csv"),
            "date,equity,rebalanced,turnover,longs\n2026-10-07,9990.0,True,1.0,BTCUSDT ETHUSDT\n2026-10-08,10050.0,False,0.0,\n",
        )
        .unwrap();
        std::fs::write(book.join("state.json"), r#"{"variant":"demo book","started":"2026-10-07T05:30:00+00:00","equity":10050.0}"#).unwrap();
        let b = read_book(&book).unwrap();
        assert_eq!(b.days, 2);
        assert_eq!(b.equity, vec![9990.0, 10050.0]);
        assert!((b.return_pct - 0.5).abs() < 1e-9);
        assert_eq!(b.last_rebalance.get("longs").map(String::as_str), Some("BTCUSDT ETHUSDT"));
        assert_eq!(b.started, "2026-10-07");
        let _ = std::fs::remove_dir_all(&dir);
    }
}
