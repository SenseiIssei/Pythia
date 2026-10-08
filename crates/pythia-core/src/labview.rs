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

use serde::{Deserialize, Serialize};
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
    /// The VPS's hourly look at every lab job (`_health/system.json`), as written.
    pub health: Option<Value>,
    /// The daily forward report (`reports/forward/latest.json`): every paper
    /// book and autopilot against its backtest. `None` until the job has run.
    pub forward: Option<ForwardReport>,
}

// ── forward report ──────────────────────────────────────────────────────────
// Written by `lab.paper.forward_report` in snake_case, served in camelCase like
// everything else here. Every field has a default and every row is parsed on
// its own, so a newer or older report, or one malformed row, loses that much
// and no more.

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
#[serde(rename_all(serialize = "camelCase", deserialize = "snake_case"), default)]
pub struct ForwardBand {
    pub median_pct: f64,
    pub low_pct: f64,
    pub high_pct: f64,
    /// 95 % of the backtest's stretches of this length had a smaller worst dip.
    pub dd_p95_pct: Option<f64>,
    /// "bootstrap" (from the backtest's own days) or "approximate" (growth and volatility only).
    pub method: String,
    pub source: String,
    pub backtest_max_dd_pct: Option<f64>,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
#[serde(rename_all(serialize = "camelCase", deserialize = "snake_case"), default)]
pub struct ForwardGate {
    pub days: f64,
    pub days_needed: f64,
    pub trades: f64,
    pub trades_needed: f64,
    /// "rebalances" for a paper book, "closed trades" for an autopilot.
    pub trades_label: String,
    /// 0..1, the slower of the two.
    pub progress: f64,
    pub ready: bool,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
#[serde(rename_all(serialize = "camelCase", deserialize = "snake_case"), default)]
pub struct ForwardCosts {
    /// What the paper fills paid, % of capital, summed over the journal.
    pub paper_pct: f64,
    /// What the backtest's cost model says the same trades cost.
    pub model_pct: f64,
    pub ratio: Option<f64>,
    /// The book books the modelled cost as its fill cost, so the two agree by construction.
    pub modelled_only: bool,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
#[serde(rename_all(serialize = "camelCase", deserialize = "snake_case"), default)]
pub struct ForwardSlippage {
    pub route: String,
    pub fills: f64,
    pub median_realised_bps: Option<f64>,
    pub median_modelled_bps: Option<f64>,
    pub ratio: Option<f64>,
}

/// One paper book or autopilot. The autopilot-only fields stay empty for books.
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
#[serde(rename_all(serialize = "camelCase", deserialize = "snake_case"), default)]
pub struct ForwardRow {
    /// "book" or "autopilot".
    pub kind: String,
    pub name: String,
    pub label: String,
    pub variant: String,
    pub since: Option<String>,
    pub days: f64,
    pub elapsed_days: f64,
    pub return_pct: Option<f64>,
    pub max_dd_pct: Option<f64>,
    pub turnover: Option<f64>,
    pub costs: Option<ForwardCosts>,
    pub funding_pct: Option<f64>,
    pub expected: Option<ForwardBand>,
    /// "below", "inside" or "above" the band.
    pub position: Option<String>,
    pub gate7: ForwardGate,
    /// none · early · watch · ahead · on_track · unknown · stopped
    pub status: String,
    pub sentence: String,
    pub mode: Option<String>,
    pub state: Option<String>,
    pub start_equity: Option<f64>,
    pub equity: Option<f64>,
    pub floor_equity: Option<f64>,
    pub btc_return_pct: Option<f64>,
    pub fees: Option<f64>,
    pub fees_share_of_gross: Option<f64>,
    pub fees_pct_of_capital: Option<f64>,
    pub trades_per_day: Option<f64>,
    pub slippage: Vec<ForwardSlippage>,
    pub lab_book: Option<String>,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
#[serde(rename_all(serialize = "camelCase", deserialize = "snake_case"), default)]
pub struct ForwardEngine {
    pub url: String,
    pub reachable: bool,
    pub error: Option<String>,
}

#[derive(Debug, Clone, Default, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ForwardReport {
    pub generated: String,
    pub generated_ms: i64,
    pub verdict: String,
    pub books: Vec<ForwardRow>,
    pub autopilots: Vec<ForwardRow>,
    pub engine: Option<ForwardEngine>,
}

/// The forward report as the lab wrote it; `None` when there is none or it is
/// not JSON at all. Rows that do not parse are skipped, not fatal.
pub fn parse_forward(text: &str) -> Option<ForwardReport> {
    let v: Value = serde_json::from_str(text).ok()?;
    if !v.is_object() {
        return None;
    }
    let rows = |k: &str| -> Vec<ForwardRow> {
        v.get(k)
            .and_then(Value::as_array)
            .map(|a| a.iter().filter_map(|r| serde_json::from_value(r.clone()).ok()).collect())
            .unwrap_or_default()
    };
    Some(ForwardReport {
        generated: v.get("generated").and_then(Value::as_str).unwrap_or_default().to_string(),
        generated_ms: v.get("generated_ms").and_then(Value::as_i64).unwrap_or(0),
        verdict: v.get("verdict").and_then(Value::as_str).unwrap_or_default().to_string(),
        books: rows("books"),
        autopilots: rows("autopilots"),
        engine: v.get("engine").and_then(|e| serde_json::from_value(e.clone()).ok()),
    })
}

fn read_forward(root: &Path) -> Option<ForwardReport> {
    parse_forward(&std::fs::read_to_string(root.join("reports").join("forward").join("latest.json")).ok()?)
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
    out.health = std::fs::read_to_string(root.join("_health").join("system.json"))
        .ok()
        .and_then(|t| serde_json::from_str(&t).ok());
    out.forward = read_forward(&root);
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

    const FORWARD: &str = r#"{
      "generated": "2026-10-08 06:15 UTC", "generated_ms": 1791440100000,
      "verdict": "7 paper books: 6 too early, 1 worth watching. No autopilot running.",
      "books": [
        {"kind": "book", "name": "tsmom", "label": "Momentum, 20 coins", "days": 3, "elapsed_days": 2.0,
         "return_pct": -2.62, "max_dd_pct": 2.62, "turnover": 0.739,
         "costs": {"paper_pct": 0.084, "model_pct": 0.111, "ratio": 0.76, "modelled_only": false},
         "expected": {"median_pct": 0.1, "low_pct": -2.12, "high_pct": 2.56, "dd_p95_pct": 3.1,
                      "method": "bootstrap", "source": "momentum backtest, 1011 out-of-sample days"},
         "position": "below",
         "gate7": {"days": 3, "days_needed": 30, "trades": 2, "trades_needed": 30,
                   "trades_label": "rebalances", "progress": 0.0667, "ready": false},
         "status": "watch", "sentence": "Below the backtest's range after 2 days, worth watching.",
         "some_future_field": [1, 2, 3]},
        {"kind": "book", "name": "broken", "days": "three"},
        {"kind": "book", "name": "m4_ls", "days": 1, "status": "early", "sentence": "Too early to say.",
         "expected": null, "costs": null}
      ],
      "autopilots": [
        {"kind": "autopilot", "name": "ap_1649", "label": "Practice autopilot", "mode": "paper",
         "state": "running", "days": 0, "elapsed_days": 0.12, "return_pct": -0.56, "btc_return_pct": -1.99,
         "floor_equity": 8500.0, "equity": 9944.08, "start_equity": 10000.0, "fees_share_of_gross": null,
         "slippage": [{"route": "paper", "fills": 1, "median_realised_bps": 9.1,
                       "median_modelled_bps": 3.6, "ratio": 2.5}],
         "gate7": {"days": 0, "days_needed": 30, "trades": 0, "trades_needed": 30,
                   "trades_label": "closed trades", "progress": 0, "ready": false},
         "status": "early", "sentence": "Too early to say: 3 hours running."}
      ],
      "engine": {"url": "http://127.0.0.1:8788/api/state", "reachable": true, "error": null, "slippage": []}
    }"#;

    #[test]
    fn parses_the_forward_report_and_skips_broken_rows() {
        let f = parse_forward(FORWARD).unwrap();
        assert_eq!(f.verdict, "7 paper books: 6 too early, 1 worth watching. No autopilot running.");
        assert_eq!(f.books.len(), 2, "the row with days = \"three\" is dropped, the rest stays");
        let ts = &f.books[0];
        assert_eq!(ts.position.as_deref(), Some("below"));
        assert_eq!(ts.expected.as_ref().map(|e| e.low_pct), Some(-2.12));
        assert_eq!(ts.gate7.trades_label, "rebalances");
        assert!(f.books[1].expected.is_none() && f.books[1].costs.is_none());
        let ap = &f.autopilots[0];
        assert_eq!(ap.slippage[0].ratio, Some(2.5));
        assert_eq!(ap.floor_equity, Some(8500.0));
        assert!(f.engine.as_ref().unwrap().reachable);
        // Served in camelCase like the rest of the lab view.
        let out = serde_json::to_value(&f).unwrap();
        assert_eq!(out["books"][0]["gate7"]["daysNeeded"], 30.0);
        assert_eq!(out["autopilots"][0]["btcReturnPct"], -1.99);
        assert_eq!(out["generatedMs"], 1791440100000i64);
    }

    #[test]
    fn a_missing_or_broken_forward_report_degrades_to_none() {
        assert!(parse_forward("").is_none());
        assert!(parse_forward("{\"books\": [NaN]}").is_none());
        assert!(parse_forward("[1, 2]").is_none());
        let bare = parse_forward("{}").unwrap();
        assert!(bare.books.is_empty() && bare.autopilots.is_empty() && bare.engine.is_none());

        let dir = std::env::temp_dir().join(format!("pythia-labview-fwd-{}", std::process::id()));
        std::fs::create_dir_all(dir.join("reports")).unwrap();
        assert!(read_forward(&dir).is_none(), "no forward report yet");
        std::fs::create_dir_all(dir.join("reports").join("forward")).unwrap();
        std::fs::write(dir.join("reports").join("forward").join("latest.json"), FORWARD).unwrap();
        assert_eq!(read_forward(&dir).map(|f| f.books.len()), Some(2));
        let _ = std::fs::remove_dir_all(&dir);
    }
}
