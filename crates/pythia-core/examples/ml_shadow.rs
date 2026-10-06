//! Runs the volatility shadow service on its own and prints what it sees.
//!
//!   PYTHIA_MODELS=/path/to/models cargo run --release -p pythia-core --example ml_shadow

use std::time::Duration;

#[tokio::main]
async fn main() {
    let ml = pythia_core::ml::spawn();
    loop {
        tokio::time::sleep(Duration::from_secs(10)).await;
        let s = ml.read().unwrap().clone();
        println!("{:?}: {}", s.state, s.message);
        if matches!(s.state, pythia_core::ml::MlState::Live | pythia_core::ml::MlState::NoModel | pythia_core::ml::MlState::Rejected) {
            println!("{}", serde_json::to_string_pretty(&serde_json::json!({
                "model": s.model, "coins": s.coins, "shadow": s.shadow, "drift": s.drift
            })).unwrap());
            break;
        }
    }
}
