//! Train/serve parity for M2 against the research lab (fixture: lab/export/picks_parity.py).
//!
//! If one of these fails, the engine would rank coins on inputs the model was
//! never trained on. Fix the side that changed, then regenerate the fixture:
//!   python -m lab.export.picks_parity --out <repo>/crates/pythia-ml/tests/fixtures/picks_parity.json \
//!       --model <models>/picks_7d/<date>

use std::collections::HashMap;

use pythia_ml::picks::{
    ages, attach_perp, daily_from_hourly, largest_perp_by_day, perp_days, rank_cross_section, segment_start,
    spot_features, DayBar, Funding, HourBar, PerpKline, PicksModel, Row, DAY_MS, FEATURES, FUND7,
};
use pythia_ml::Gbdt;
use serde_json::Value;

fn fixture() -> Value {
    serde_json::from_str(include_str!("fixtures/picks_parity.json")).unwrap()
}

fn f(v: &Value) -> f64 {
    v.as_f64().unwrap_or(f64::NAN)
}

fn us_to_ms(v: &Value) -> i64 {
    (f(v) / 1000.0) as i64
}

fn row(v: &Value) -> Row {
    let a = v.as_array().unwrap();
    let mut r = [f64::NAN; 19];
    for (j, x) in a.iter().enumerate() {
        r[j] = f(x);
    }
    r
}

fn close(a: f64, b: f64, tol: f64) -> bool {
    (a.is_nan() && b.is_nan()) || (a - b).abs() <= tol * (1.0 + b.abs())
}

fn hours(c: &Value) -> Vec<HourBar> {
    c["hours"]
        .as_array()
        .unwrap()
        .iter()
        .map(|r| {
            let r = r.as_array().unwrap();
            HourBar { open_time_ms: us_to_ms(&r[0]), high: f(&r[1]), low: f(&r[2]), close: f(&r[3]), quote_volume: f(&r[4]) }
        })
        .collect()
}

/// The engine's path for one coin: hours -> latest segment -> days -> 19 raw features.
fn engine_rows(c: &Value, btc_days: &[DayBar]) -> (Vec<DayBar>, Vec<Row>) {
    let h = hours(c);
    let start = segment_start(&h);
    let days = daily_from_hourly(&h[start..]);
    let a = c["anchor"].as_array().unwrap();
    let ag = ages(&days, Some((us_to_ms(&a[0]), f(&a[1]))), start > 0);
    let mut rows = spot_features(&days, btc_days, &ag);
    let perps: Vec<_> = c["perp"]
        .as_object()
        .unwrap()
        .values()
        .map(|p| {
            let k: Vec<PerpKline> = p["klines"]
                .as_array()
                .unwrap()
                .iter()
                .map(|r| PerpKline {
                    day_ms: us_to_ms(&r[0]).div_euclid(DAY_MS) * DAY_MS,
                    close: f(&r[1]),
                    quote_volume: f(&r[2]),
                })
                .collect();
            let fu: Vec<Funding> =
                p["funding"].as_array().unwrap().iter().map(|r| Funding { time_ms: us_to_ms(&r[0]), rate: f(&r[1]) }).collect();
            perp_days(&k, &fu)
        })
        .collect();
    let by_day = largest_perp_by_day(&perps);
    for (x, d) in rows.iter_mut().zip(&days) {
        attach_perp(x, d.close, d.qv, by_day.get(&d.day_ms));
    }
    (days, rows)
}

#[test]
fn feature_names_match_the_lab() {
    let fx = fixture();
    let names: Vec<&str> = fx["feature_names"].as_array().unwrap().iter().map(|v| v.as_str().unwrap()).collect();
    assert_eq!(names, FEATURES.to_vec());
}

#[test]
fn raw_features_match_the_lab() {
    let fx = fixture();
    let coins = fx["coins"].as_array().unwrap();
    let btc = coins.iter().find(|c| c["symbol"] == "BTCUSDT").unwrap();
    let btc_days = daily_from_hourly(&hours(btc)[segment_start(&hours(btc))..]);
    let fix_day = us_to_ms(&fx["day"]);
    let (mut spot, mut perp) = (0, 0);
    for c in coins {
        let sym = c["symbol"].as_str().unwrap();
        let (days, rows) = engine_rows(c, &btc_days);
        let idx: HashMap<i64, usize> = days.iter().enumerate().map(|(i, d)| (d.day_ms, i)).collect();
        for w in c["want"].as_array().unwrap() {
            let w = w.as_array().unwrap();
            let day = us_to_ms(&w[0]);
            let Some(&i) = idx.get(&day) else { panic!("{sym}: the engine has no day {day}") };
            // Compare where every lookback (56 rows) lies inside the fetched bars,
            // and the perp columns where 7 days of funding history are inside them.
            if i < 57 {
                continue;
            }
            let perp_ok = day >= fix_day - 22 * DAY_MS;
            for j in 0..19 {
                if j >= 16 && !perp_ok {
                    continue;
                }
                let (a, b) = (rows[i][j], f(&w[j + 1]));
                assert!(close(a, b, 1e-9), "{sym} day {day} {}: rust {a} lab {b}", FEATURES[j]);
                if j >= 16 {
                    perp += 1;
                } else {
                    spot += 1;
                }
            }
        }
    }
    eprintln!("raw parity: {spot} spot and {perp} perp values within 1e-9");
    assert!(spot > 500 && perp > 100, "too little compared: {spot} spot, {perp} perp");
}

/// Groups of rows that the engine ranks as one fund7 tie.
fn fund7_groups(ranked: &[Row]) -> Vec<Vec<usize>> {
    let mut by: HashMap<u64, Vec<usize>> = HashMap::new();
    for (i, r) in ranked.iter().enumerate() {
        if r[FUND7].is_finite() {
            by.entry(r[FUND7].to_bits()).or_default().push(i);
        }
    }
    by.into_values().filter(|g| g.len() > 1).collect()
}

#[test]
fn ranks_match_the_lab() {
    let fx = fixture();
    for cs in fx["cross"].as_array().unwrap() {
        let raw: Vec<Row> = cs["raw"].as_array().unwrap().iter().map(row).collect();
        let want: Vec<Row> = cs["ranked"].as_array().unwrap().iter().map(row).collect();
        let got = rank_cross_section(&raw);
        let mut exact = 0;
        for (i, (g, w)) in got.iter().zip(&want).enumerate() {
            for j in 0..19 {
                if j == FUND7 {
                    continue;
                }
                assert!(close(g[j], w[j], 1e-12), "day {} row {i} {}: rust {} lab {}", cs["day"], FEATURES[j], g[j], w[j]);
                exact += 1;
            }
        }
        // fund7: exact outside tie groups; inside one, the lab's ranks (handed out
        // in arbitrary order over float-rounding noise) average to the engine's.
        let groups = fund7_groups(&got);
        let in_group: std::collections::HashSet<usize> = groups.iter().flatten().copied().collect();
        for (i, (g, w)) in got.iter().zip(&want).enumerate() {
            if !in_group.contains(&i) {
                assert!(close(g[FUND7], w[FUND7], 1e-12), "row {i} fund7: rust {} lab {}", g[FUND7], w[FUND7]);
                exact += 1;
            }
        }
        for g in &groups {
            let lab_mean = g.iter().map(|&i| want[i][FUND7]).sum::<f64>() / g.len() as f64;
            assert!((lab_mean - got[g[0]][FUND7]).abs() < 1e-12, "fund7 tie group {g:?}");
        }
        eprintln!(
            "day {}: {} coins, {exact} ranks exact, {} fund7 ties in {} groups match on average",
            cs["day"],
            raw.len(),
            in_group.len(),
            groups.len()
        );
    }
}

#[test]
fn tree_walker_matches_lightgbm_ranker() {
    let fx = fixture();
    let model = Gbdt::from_value(&fx["tiny_model"]).unwrap();
    let mut n = 0;
    for cs in fx["cross"].as_array().unwrap() {
        let want: Vec<f64> = cs["pred_tiny"].as_array().unwrap().iter().map(f).collect();
        let x: Vec<Row> = cs["ranked"].as_array().unwrap().iter().map(row).collect();
        assert!(x.iter().any(|r| r.iter().any(|v| v.is_nan())), "fixture should exercise missing perp values");
        for (i, (r, w)) in x.iter().zip(&want).enumerate() {
            let got = model.predict(r);
            assert!((got - w).abs() < 1e-9, "row {i}: rust {got} lightgbm {w}");
            n += 1;
        }
    }
    eprintln!("tiny ranker: {n} rows within 1e-9");
}

#[test]
fn end_to_end_from_raw_to_score() {
    // Engine ranks into the tree walker. Rows whose ranks equal the lab's land on
    // LightGBM's score; the only rows allowed to differ are fund7 ties.
    let fx = fixture();
    let model = Gbdt::from_value(&fx["tiny_model"]).unwrap();
    for cs in fx["cross"].as_array().unwrap() {
        let raw: Vec<Row> = cs["raw"].as_array().unwrap().iter().map(row).collect();
        let lab: Vec<Row> = cs["ranked"].as_array().unwrap().iter().map(row).collect();
        let want: Vec<f64> = cs["pred_tiny"].as_array().unwrap().iter().map(f).collect();
        let got = rank_cross_section(&raw);
        let (mut same, mut tie, mut worst) = (0, 0, 0.0f64);
        for i in 0..got.len() {
            let d = (model.predict(&got[i]) - want[i]).abs();
            if got[i][FUND7].to_bits() == lab[i][FUND7].to_bits() || (got[i][FUND7].is_nan() && lab[i][FUND7].is_nan()) {
                assert!(d < 1e-9, "row {i}: {d}");
                same += 1;
            } else {
                tie += 1;
                worst = worst.max(d);
            }
        }
        // The real ranking: Spearman between engine and lab scores over the whole day.
        let a: Vec<f64> = got.iter().map(|r| model.predict(r)).collect();
        let rho = pythia_ml::picks::spearman(&a, &want).unwrap();
        eprintln!("day {}: {same} scores exact, {tie} fund7-tie rows off by at most {worst:.2e}, order agreement {rho:.6}", cs["day"]);
        assert!(rho > 0.999, "engine and lab order disagree: {rho}");
    }
}

/// The exported production model, when available locally (`PYTHIA_MODELS=...`):
/// it loads (probe check) and reproduces the fixture's scores from it.
#[test]
fn production_model_matches_if_present() {
    let Ok(dir) = std::env::var("PYTHIA_MODELS") else { return };
    let Some(v) = pythia_ml::latest_version(std::path::Path::new(&dir), "picks_7d") else { return };
    let m = PicksModel::load(&v).unwrap_or_else(|e| panic!("{}: {e}", v.display()));
    eprintln!("verified {} trees and {} probe rows from {}", m.n_trees(), m.card.probe.raw.len(), v.display());
    let fx = fixture();
    let version = v.file_name().unwrap().to_string_lossy().into_owned();
    if fx["model_version"].as_str() != Some(version.as_str()) {
        eprintln!("fixture was made with model {}, not {version}: skipping the score comparison", fx["model_version"]);
        return;
    }
    let mut n = 0;
    for cs in fx["cross"].as_array().unwrap() {
        let Some(want) = cs["pred_model"].as_array() else { continue };
        for (r, w) in cs["ranked"].as_array().unwrap().iter().zip(want) {
            let got = m.score(&row(r));
            assert!((got - f(w)).abs() < 1e-9, "rust {got} lightgbm {}", f(w));
            n += 1;
        }
    }
    eprintln!("production model: {n} fixture rows within 1e-9");
    assert!(n > 0);
}
