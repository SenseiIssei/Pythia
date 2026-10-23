//! The pump.fun lab for the Lab page: the real-time study's report
//! (`reports/pumpfun_rt/latest.json`: readiness per strategy, the shadow
//! books), its measured execution (`execution.json`) and the paper books of
//! the pipeline strategies (`paper/pumpfun_rt/ledger.csv`) over the last seven
//! days. Read only, from the same root as the lab feeds.

use std::collections::BTreeMap;
use std::path::Path;

use serde::Serialize;
use serde_json::Value;

use super::{data_dir, file_ms, split_csv};

/// The paper books cover this many days back from now.
pub const PUMPFUN_BOOK_DAYS: i64 = 7;
const DAY_MS: i64 = 86_400_000;
/// Only the ledger's tail is read: it grows by thousands of rows a day.
pub const PUMPFUN_LEDGER_TAIL_BYTES: u64 = 16 << 20;
/// At most this many points per strategy's chart.
pub const PUMPFUN_CURVE_POINTS: usize = 120;
/// The newest entries listed per strategy.
pub const PUMPFUN_RECENT: usize = 10;

#[derive(Debug, Clone, Default, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct PumpfunLab {
    /// Any of the study's files was there.
    pub found: bool,
    pub updated_ms: Option<i64>,
    pub status: Option<String>,
    pub headline: Option<String>,
    pub caveat: Option<String>,
    pub pick: Option<String>,
    /// Readiness per pipeline strategy, as the study wrote it.
    pub readiness: Value,
    /// The shadow books (every strategy on the live stream), as the study wrote them.
    pub shadow: Value,
    /// `execution.json` as written: how the live orders really landed.
    pub execution: Option<Value>,
    /// The pipeline strategies' paper books, the one with the newest entry first.
    pub books: Vec<PumpfunBook>,
    pub book_days: i64,
    /// When the ledger last changed.
    pub ledger_ms: Option<i64>,
}

#[derive(Debug, Clone, Default, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct PumpfunBook {
    pub rule: String,
    pub entries: usize,
    pub wins: usize,
    /// Mean return per entry (0.05 = +5 %).
    pub mean: Option<f64>,
    pub pnl_sol: f64,
    pub last_ms: Option<i64>,
    /// One row per UTC day, newest first.
    pub days: Vec<PumpfunBookDay>,
    /// `[exit ms, running P&L in SOL]`, oldest first, thinned for the chart.
    pub curve: Vec<[f64; 2]>,
    /// The newest entries, newest first.
    pub recent: Vec<PumpfunEntry>,
}

#[derive(Debug, Clone, Default, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct PumpfunBookDay {
    pub day: String,
    pub entries: usize,
    pub mean: Option<f64>,
    pub pnl_sol: f64,
}

#[derive(Debug, Clone, Default, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct PumpfunEntry {
    pub exit_ms: i64,
    pub symbol: Option<String>,
    pub exit_why: Option<String>,
    pub ret: Option<f64>,
    pub pnl_sol: f64,
}

fn cell(f: &[String], c: Option<usize>) -> Option<&str> {
    c.and_then(|i| f.get(i)).map(|s| s.trim()).filter(|s| !s.is_empty())
}

fn day_of(ms: i64) -> String {
    chrono::DateTime::from_timestamp_millis(ms).map(|d| d.format("%Y-%m-%d").to_string()).unwrap_or_default()
}

/// Every `max`-th point or so, the first and the last always kept.
fn thin(pts: Vec<[f64; 2]>, max: usize) -> Vec<[f64; 2]> {
    if pts.len() <= max || max < 2 {
        return pts;
    }
    let step = (pts.len() - 1) as f64 / (max - 1) as f64;
    (0..max).map(|i| pts[((i as f64 * step).round() as usize).min(pts.len() - 1)]).collect()
}

fn book(rule: String, mut es: Vec<PumpfunEntry>) -> PumpfunBook {
    es.sort_by_key(|e| e.exit_ms);
    let rets: Vec<f64> = es.iter().filter_map(|e| e.ret).collect();
    let mean = if rets.is_empty() { None } else { Some(rets.iter().sum::<f64>() / rets.len() as f64) };
    // day -> (entries, P&L, sum of returns, returns)
    let mut by_day: BTreeMap<String, (usize, f64, f64, usize)> = BTreeMap::new();
    for e in &es {
        let x = by_day.entry(day_of(e.exit_ms)).or_insert((0, 0.0, 0.0, 0));
        x.0 += 1;
        x.1 += e.pnl_sol;
        if let Some(r) = e.ret {
            x.2 += r;
            x.3 += 1;
        }
    }
    let days = by_day
        .into_iter()
        .rev()
        .map(|(day, (n, pnl, rs, rn))| PumpfunBookDay { day, entries: n, mean: if rn > 0 { Some(rs / rn as f64) } else { None }, pnl_sol: pnl })
        .collect();
    let mut run = 0.0;
    let full: Vec<[f64; 2]> = es
        .iter()
        .map(|e| {
            run += e.pnl_sol;
            [e.exit_ms as f64, run]
        })
        .collect();
    PumpfunBook {
        entries: es.len(),
        wins: es.iter().filter(|e| e.pnl_sol > 0.0).count(),
        mean,
        pnl_sol: es.iter().map(|e| e.pnl_sol).sum(),
        last_ms: es.last().map(|e| e.exit_ms),
        days,
        curve: thin(full, PUMPFUN_CURVE_POINTS),
        recent: es.iter().rev().take(PUMPFUN_RECENT).cloned().collect(),
        rule,
    }
}

/// The paper books of the pipeline strategies from the ledger's text: closed
/// entries of the last `PUMPFUN_BOOK_DAYS` days. `pipeline` names the
/// strategies (the study's readiness list); empty means every `P_` rule.
pub fn pumpfun_books(text: &str, pipeline: &[String], now_ms: i64) -> Vec<PumpfunBook> {
    let mut lines = text.lines().filter(|l| !l.trim().is_empty());
    let Some(head) = lines.next() else { return vec![] };
    let head = split_csv(head);
    let col = |name: &str| head.iter().position(|h| h.trim() == name);
    let (Some(c_rule), Some(c_exit), Some(c_pnl)) = (col("rule"), col("exit_ms"), col("pnl_sol")) else { return vec![] };
    let (c_ret, c_sym, c_name, c_why) = (col("ret"), col("symbol"), col("name"), col("exit_why"));
    let since = now_ms - PUMPFUN_BOOK_DAYS * DAY_MS;
    let wanted = |rule: &str| if pipeline.is_empty() { rule.starts_with("P_") } else { pipeline.iter().any(|p| p == rule) };
    let mut rows: BTreeMap<String, Vec<PumpfunEntry>> = BTreeMap::new();
    for line in lines {
        let f = split_csv(line);
        let Some(rule) = cell(&f, Some(c_rule)) else { continue };
        if !wanted(rule) {
            continue;
        }
        let Some(exit_ms) = cell(&f, Some(c_exit)).and_then(|s| s.parse::<f64>().ok()).filter(|x| x.is_finite()).map(|x| x as i64) else { continue };
        if exit_ms < since || exit_ms > now_ms + DAY_MS {
            continue;
        }
        let Some(pnl_sol) = cell(&f, Some(c_pnl)).and_then(|s| s.parse::<f64>().ok()).filter(|x| x.is_finite()) else { continue };
        rows.entry(rule.to_string()).or_default().push(PumpfunEntry {
            exit_ms,
            symbol: cell(&f, c_sym).or(cell(&f, c_name)).map(str::to_string),
            exit_why: cell(&f, c_why).map(str::to_string),
            ret: cell(&f, c_ret).and_then(|s| s.parse::<f64>().ok()).filter(|x| x.is_finite()),
            pnl_sol,
        });
    }
    let mut books: Vec<PumpfunBook> = rows.into_iter().map(|(rule, es)| book(rule, es)).collect();
    books.sort_by(|a, b| b.last_ms.cmp(&a.last_ms).then(a.rule.cmp(&b.rule)));
    books
}

/// The ledger's header and its last `PUMPFUN_LEDGER_TAIL_BYTES`, cut at a whole line.
fn read_ledger(p: &Path) -> Option<String> {
    use std::io::{BufRead, BufReader, Read, Seek, SeekFrom};
    let f = std::fs::File::open(p).ok()?;
    let len = f.metadata().ok()?.len();
    let mut r = BufReader::new(f);
    let mut header = String::new();
    r.read_line(&mut header).ok()?;
    let tail = len > PUMPFUN_LEDGER_TAIL_BYTES;
    if tail {
        r.seek(SeekFrom::Start(len - PUMPFUN_LEDGER_TAIL_BYTES)).ok()?;
    }
    let mut buf = Vec::new();
    r.read_to_end(&mut buf).ok()?;
    let text = String::from_utf8_lossy(&buf);
    let all: &str = &text;
    let rest = if tail { all.split_once('\n').map(|(_, b)| b).unwrap_or("") } else { all };
    Some(format!("{header}{rest}"))
}

fn read_json(p: &Path) -> Option<Value> {
    std::fs::read_to_string(p).ok().and_then(|t| serde_json::from_str(&t).ok())
}

/// The pump.fun lab from `root` (the lab's data folder).
pub fn pumpfun_lab_in(root: &Path, now_ms: i64) -> PumpfunLab {
    let dir = root.join("reports").join("pumpfun_rt");
    let latest = read_json(&dir.join("latest.json")).filter(Value::is_object);
    let execution = read_json(&dir.join("execution.json")).filter(Value::is_object);
    let ledger = root.join("paper").join("pumpfun_rt").join("ledger.csv");
    let text = |k: &str| latest.as_ref().and_then(|v| v.get(k)).and_then(Value::as_str).map(str::to_string);
    let readiness = latest.as_ref().and_then(|v| v.get("readiness")).cloned().unwrap_or(Value::Null);
    let pipeline: Vec<String> = readiness.as_object().map(|o| o.keys().cloned().collect()).unwrap_or_default();
    let books = read_ledger(&ledger).map(|t| pumpfun_books(&t, &pipeline, now_ms)).unwrap_or_default();
    PumpfunLab {
        found: latest.is_some() || execution.is_some() || !books.is_empty(),
        updated_ms: latest.as_ref().and_then(|v| v.get("updated_ms").or_else(|| v.get("updatedMs"))).and_then(Value::as_i64),
        status: text("status"),
        headline: text("headline"),
        caveat: text("caveat"),
        pick: text("pick"),
        shadow: latest.as_ref().and_then(|v| v.get("shadow")).cloned().unwrap_or(Value::Null),
        readiness,
        execution,
        books,
        book_days: PUMPFUN_BOOK_DAYS,
        ledger_ms: if ledger.exists() { Some(file_ms(&ledger)) } else { None },
    }
}

/// The pump.fun lab from the lab's data folder; empty without one.
pub fn pumpfun_lab() -> PumpfunLab {
    let now = chrono::Utc::now().timestamp_millis();
    data_dir().map(|d| pumpfun_lab_in(&d, now)).unwrap_or_default()
}

#[cfg(test)]
mod tests {
    use super::*;

    const DAY: i64 = 86_400_000;
    // 2026-10-23 12:00 UTC
    const NOW: i64 = 1_792_756_800_000;
    const HEAD: &str = "rule,family,mint,name,symbol,exit_ms,exit_why,pnl_sol,ret";

    #[test]
    fn books_keep_the_pipeline_and_the_last_seven_days_newest_first() {
        let text = format!(
            "{HEAD}\n\
             P_pool0,E,M1,\"Coin, one\",ONE,{},tp,0.03,0.3\n\
             P_pool0,E,M2,Two,,{},stop,-0.01,-0.1\n\
             P_pool0,E,M3,Old,OLD,{},stop,-0.05,-0.5\n\
             C_20in60_x1,C,M4,Shadow,SH,{},time,0.5,0.5\n\
             P_press10,A,M5,Five,FIVE,{},time,-0.002,-0.02\n\
             P_press10,A,M6,Six,SIX,{},time,oops,-0.02\n",
            NOW - DAY,
            NOW - 1000,
            NOW - 8 * DAY,
            NOW - 10,
            NOW - 2 * DAY,
            NOW - 5,
        );
        let books = pumpfun_books(&text, &[], NOW);
        assert_eq!(books.iter().map(|b| b.rule.as_str()).collect::<Vec<_>>(), ["P_pool0", "P_press10"]);
        let b = &books[0];
        assert_eq!((b.entries, b.wins, b.last_ms), (2, 1, Some(NOW - 1000)));
        assert!((b.pnl_sol - 0.02).abs() < 1e-12);
        assert!((b.mean.unwrap() - 0.1).abs() < 1e-12);
        assert_eq!(b.days.iter().map(|d| d.day.as_str()).collect::<Vec<_>>(), ["2026-10-23", "2026-10-22"]);
        assert_eq!(b.recent[0].symbol.as_deref(), Some("Two"));
        assert_eq!(b.recent[1].symbol.as_deref(), Some("ONE"));
        assert_eq!(b.curve.len(), 2);
        assert!((b.curve[1][1] - 0.02).abs() < 1e-12);
        // A readiness list names the strategies instead of the prefix.
        let named = pumpfun_books(&text, &["P_press10".to_string()], NOW);
        assert_eq!(named.len(), 1);
        assert_eq!(named[0].entries, 1);
        assert!(pumpfun_books("", &[], NOW).is_empty());
        assert!(pumpfun_books("a,b\n1,2\n", &[], NOW).is_empty());
    }

    #[test]
    fn a_long_book_is_thinned_for_the_chart() {
        let mut text = format!("{HEAD}\n");
        for i in 0..500 {
            text.push_str(&format!("P_x,P,M,N,S,{},time,0.001,0.01\n", NOW - DAY + i * 1000));
        }
        let b = &pumpfun_books(&text, &[], NOW)[0];
        assert_eq!(b.entries, 500);
        assert_eq!(b.curve.len(), PUMPFUN_CURVE_POINTS);
        assert!((b.curve.last().unwrap()[1] - 0.5).abs() < 1e-9);
        assert_eq!(b.recent.len(), PUMPFUN_RECENT);
    }

    #[test]
    fn reads_the_report_the_execution_and_the_ledger_from_the_data_folder() {
        let dir = std::env::temp_dir().join(format!("pythia-labview-pumpfun-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        assert!(!pumpfun_lab_in(&dir, NOW).found);
        std::fs::create_dir_all(dir.join("reports/pumpfun_rt")).unwrap();
        std::fs::create_dir_all(dir.join("paper/pumpfun_rt")).unwrap();
        std::fs::write(
            dir.join("reports/pumpfun_rt/latest.json"),
            r#"{"title":"pump.fun real-time lab","status":"bad","headline":"Paper only.","updated_ms":5,"pick":"E_d0_x2",
                "readiness":{"P_pool0":{"days":4,"ready":false}},"shadow":{"P_pool0":{"n":17,"mean":0.13}}}"#,
        )
        .unwrap();
        std::fs::write(dir.join("reports/pumpfun_rt/execution.json"), r#"{"fills":65,"verdict":"slower than paper"}"#).unwrap();
        std::fs::write(
            dir.join("paper/pumpfun_rt/ledger.csv"),
            format!("{HEAD}\nP_pool0,E,M,N,S,{},tp,0.01,0.1\nP_press10,A,M,N,S,{},tp,0.01,0.1\n", NOW - 60_000, NOW - 60_000),
        )
        .unwrap();
        let v = pumpfun_lab_in(&dir, NOW);
        assert!(v.found);
        assert_eq!((v.updated_ms, v.status.as_deref(), v.pick.as_deref()), (Some(5), Some("bad"), Some("E_d0_x2")));
        assert_eq!(v.readiness["P_pool0"]["days"], 4);
        assert_eq!(v.shadow["P_pool0"]["n"], 17);
        assert_eq!(v.execution.as_ref().unwrap()["fills"], 65);
        // Only the strategies the readiness list names.
        assert_eq!(v.books.len(), 1);
        assert_eq!(v.books[0].rule, "P_pool0");
        assert!(v.ledger_ms.is_some());
        let json = serde_json::to_value(&v).unwrap();
        assert_eq!(json["books"][0]["pnlSol"], 0.01);
        assert_eq!(json["bookDays"], 7);
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn reads_only_the_tail_of_a_long_ledger_from_a_whole_line() {
        let dir = std::env::temp_dir().join(format!("pythia-labview-pumpfun-tail-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        let p = dir.join("ledger.csv");
        std::fs::write(&p, format!("{HEAD}\nP_a,P,M,N,S,{},tp,0.01,0.1\n", NOW)).unwrap();
        let t = read_ledger(&p).unwrap();
        assert!(t.starts_with(HEAD) && t.contains("P_a"));
        let _ = std::fs::remove_dir_all(&dir);
    }
}
