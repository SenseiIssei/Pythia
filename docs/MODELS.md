# Models: from the lab to the engine

How a trained model gets into Pythia, what keeps it honest on the way, and how
to run it. Masterplan phase 5. The research side is in
[`research/lab/README.md`](../research/lab/README.md).

## The path

```
research/lab (Python, VPS)                 crates/pythia-ml (pure Rust)        crates/pythia-core/src/ml.rs
  train, walk-forward, gates     model.json  tree walker + features   ->  live Binance minutes, every hour:
  export only if it passes   ->  card.json   probe check on load          score the last forecast,
                                                                          forecast the next, check drift
```

Only one model runs today: **next-hour volatility** (`vol_1h`), LightGBM on 21
features from 1-minute Binance spot klines, 20 coins pooled. In the lab it beat
the HAR baseline in 24 of 24 quarters since 2021, 11.8 % lower QLIKE.

## What keeps it honest

| Check | Where | Fails when |
|---|---|---|
| Same features in training and live | `crates/pythia-ml/tests/parity.rs` against `lab/export/parity.py` | any of the 21 features, the minute-to-hour aggregation or the tree walker differs from the lab by more than 1e-9 |
| The file is the model the lab tested | `VolModel::load` | the card's feature list differs from the engine's, or any of the 64 probe rows does not reproduce LightGBM's output |
| A retrain is not worse | `lab/experiments/vol.py` | not better than HAR, not significant, or worse than HAR in any of the last four quarters: published to `vol_1h_rejected`, not `vol_1h` |
| It works live, not just in the lab | shadow scoring in `ml.rs` | live QLIKE against HAR, persisted in `vol_1h/shadow.json`, shown on the Models page |
| The market still looks like training | drift check in `pythia-ml/src/drift.rs` | more than 5 % of the last week of an input lies outside the 0.5 % to 99.5 % range the trees were trained on |

**Shadow mode means exactly that.** The forecasts are written down and scored.
Nothing sizes, places or blocks an order from them yet. Wiring them into the
risk manager (volatility-scaled sizes and stops) is the next step, once the
live score has matched the lab for a few weeks.

## Why a tree walker and not ONNX

The lab still writes `model.onnx`. The engine reads LightGBM's own JSON dump
instead: for tree ensembles that is exact, adds nothing native to the desktop
bundle, and fits on one screen (`gbdt.rs`). ONNX is kept for neural models.

## Running it

Set `PYTHIA_MODELS` to the folder holding `vol_1h/<date>/` (on the VPS
`/srv/pythia-data/models`, on the PC the synced `PythiaData/models`). Without
it the Models page says so and nothing else changes.

- **Desktop app:** `PYTHIA_MODELS` in the environment, then the Models page
  (advanced mode).
- **Server:** `GET /api/ml/status`. On the VPS it runs as the
  `pythia-server` container, published on `127.0.0.1:8787` only, because the
  API has no authentication:

  ```bash
  docker build -f server/Dockerfile -t pythia-server .
  ```

  ```bash
  docker run -d --name pythia-server --restart unless-stopped --memory 1g -p 127.0.0.1:8787:8787 -e PYTHIA_MODELS=/models -v /srv/pythia-data/models:/models pythia-server
  ```

- **On its own:** `cargo run --release -p pythia-core --example ml_shadow`.

The first forecast comes after about three minutes, once ten days of
1-minute klines are in. The first score comes an hour later.

## Retraining

Sundays 05:00 UTC on the VPS (`/etc/cron.d/pythia-retrain`). A model that
passes lands in `models/vol_1h/<date>/`; the engine checks every hour and
switches to it after its probe check, without a restart. The live score
carries on across versions.

When `vol.py`'s features change, regenerate the parity fixture
(`python -m lab.export.parity`, then copy `fixtures/vol_parity.json` into
`crates/pythia-ml/tests/fixtures/`) and change `pythia-ml/src/vol.rs` to match.
The parity test will not let one side move without the other.
