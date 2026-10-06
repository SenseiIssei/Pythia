//! Train/serve parity against the research lab (fixture: lab/export/parity.py).
//!
//! If one of these fails, the engine would feed the model inputs it was never
//! trained on. Fix the side that changed, then regenerate the fixture:
//!   python -m lab.export.parity   (on the VPS, then copy fixtures/vol_parity.json here)

use pythia_ml::{features, hourly_from_minutes, Gbdt, HourBar, MinuteBar, VolModel, FEATURES};
use serde_json::Value;

fn fixture() -> Value {
    serde_json::from_str(include_str!("fixtures/vol_parity.json")).unwrap()
}

fn f(v: &Value) -> f64 {
    v.as_f64().unwrap_or(f64::NAN)
}

fn hours(v: &Value) -> Vec<HourBar> {
    v.as_array()
        .unwrap()
        .iter()
        .map(|r| {
            let r = r.as_array().unwrap();
            HourBar {
                ts_ms: (f(&r[0]) / 1000.0) as i64,
                open: f(&r[1]),
                high: f(&r[2]),
                low: f(&r[3]),
                close: f(&r[4]),
                ret: f(&r[5]),
                rv: f(&r[6]),
                volume_q: f(&r[7]),
                taker_buy_q: f(&r[8]),
                trades: f(&r[9]),
                minutes: 60,
            }
        })
        .collect()
}

fn close(a: f64, b: f64, tol: f64) -> bool {
    (a.is_nan() && b.is_nan()) || (a - b).abs() <= tol * (1.0 + b.abs())
}

#[test]
fn feature_names_match_the_lab() {
    let fx = fixture();
    let names: Vec<&str> = fx["feature_names"].as_array().unwrap().iter().map(|v| v.as_str().unwrap()).collect();
    assert_eq!(names, FEATURES.to_vec());
}

#[test]
fn minutes_to_hours_match_the_lab() {
    let fx = fixture();
    let minutes: Vec<MinuteBar> = fx["minutes"]
        .as_array()
        .unwrap()
        .iter()
        .map(|r| {
            let r = r.as_array().unwrap();
            MinuteBar {
                open_time_ms: (f(&r[0]) / 1000.0) as i64,
                open: f(&r[1]),
                high: f(&r[2]),
                low: f(&r[3]),
                close: f(&r[4]),
                quote_volume: f(&r[5]),
                taker_buy_quote_volume: f(&r[6]),
                trades: f(&r[7]),
            }
        })
        .collect();
    let got = hourly_from_minutes(&minutes, None);
    let want = fx["minute_hours"].as_array().unwrap();
    assert_eq!(got.len(), want.len());
    for (g, w) in got.iter().zip(want) {
        let w = w.as_array().unwrap();
        assert_eq!(g.ts_ms, (f(&w[0]) / 1000.0) as i64);
        let pairs = [
            (g.open, f(&w[1])),
            (g.high, f(&w[2])),
            (g.low, f(&w[3])),
            (g.close, f(&w[4])),
            (g.ret, f(&w[5])),
            (g.rv, f(&w[6])),
            (g.volume_q, f(&w[7])),
            (g.taker_buy_q, f(&w[8])),
            (g.trades, f(&w[9])),
            (g.minutes as f64, f(&w[10])),
        ];
        for (i, (a, b)) in pairs.iter().enumerate() {
            assert!(close(*a, *b, 1e-9), "hour {} field {i}: rust {a} lab {b}", g.ts_ms);
        }
    }
}

#[test]
fn features_match_the_lab() {
    let fx = fixture();
    let eth = hours(&fx["eth_hours"]);
    let btc = hours(&fx["btc_hours"]);
    let got = features(&eth, &btc);
    let want = fx["eth_features"].as_array().unwrap();
    assert_eq!(got.len(), want.len());
    let mut checked = 0;
    for (row, (g, w)) in got.iter().zip(want).enumerate() {
        for (j, (a, b)) in g.iter().zip(w.as_array().unwrap()).enumerate() {
            let b = f(b);
            assert!(close(*a, b, 1e-9), "row {row} {}: rust {a} lab {b}", FEATURES[j]);
            checked += 1;
        }
    }
    assert_eq!(checked, want.len() * FEATURES.len());
}

#[test]
fn tree_walker_matches_lightgbm() {
    let fx = fixture();
    let model = Gbdt::from_value(&fx["model"]).unwrap();
    let want: Vec<f64> = fx["pred"].as_array().unwrap().iter().map(f).collect();
    let x: Vec<Vec<f64>> =
        fx["eth_features"].as_array().unwrap().iter().map(|r| r.as_array().unwrap().iter().map(f).collect()).collect();
    assert!(x.iter().any(|r| r.iter().any(|v| v.is_nan())), "fixture should exercise missing values");
    for (i, (row, w)) in x.iter().zip(&want).enumerate() {
        let got = model.predict(row);
        assert!((got - w).abs() < 1e-9, "row {i}: rust {got} lightgbm {w}");
    }
}

#[test]
fn end_to_end_from_hours_to_forecast() {
    // Rust-built features into the tree walker land on LightGBM's answers too.
    let fx = fixture();
    let model = Gbdt::from_value(&fx["model"]).unwrap();
    let got = features(&hours(&fx["eth_hours"]), &hours(&fx["btc_hours"]));
    let want: Vec<f64> = fx["pred"].as_array().unwrap().iter().map(f).collect();
    let worst = got.iter().zip(&want).map(|(x, w)| (model.predict(x) - w).abs()).fold(0.0, f64::max);
    assert!(worst < 1e-9, "worst deviation {worst}");
}

/// The production model, when one is available locally (`PYTHIA_MODELS=...`).
/// Loading runs the probe check; this makes sure a real 500-tree model passes it.
#[test]
fn production_model_loads_if_present() {
    let Ok(dir) = std::env::var("PYTHIA_MODELS") else { return };
    let Some(v) = pythia_ml::latest_version(std::path::Path::new(&dir), "vol_1h") else { return };
    let m = VolModel::load(&v).unwrap_or_else(|e| panic!("{}: {e}", v.display()));
    assert!(m.n_trees() > 100);
    eprintln!("verified {} trees and {} probe rows from {}", m.n_trees(), m.card.probe.raw.len(), v.display());
}
