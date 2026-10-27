# Model factory G2: the first run (2026-10-27)

`lab.models.factory`, job `model-factory` (daily 03:50 UTC, the `heavy` lock, `PYTHIA_MODEL_FACTORY_BUDGET`).
Paper only: nothing a book, the engine or a live bot reads changes.

## What it does

A spec is a target, a feature subset, a learner and a training window; every spec is one trial in
`<data>/models/factory/ledger.jsonl`.

| Target | What | Baseline | Incumbent | Purge |
|---|---|---|---|---|
| m8 | next UTC day up, 15 Alpaca coins, log loss | training share of up days | M8 (LightGBM + Platt) | 1 day |
| m10 | next UTC day's realised variance, 20 coins, QLIKE | HAR on log 1, 7, 30-day RV | M10 (LightGBM, regime inputs) | 1 day |
| m12 | BTC and SPY correlation over the next 20 trading days (atanh), squared error | last 60 days' correlation | M12 (ridge on the change) | 32 days |
| fwd7 | the strategy factory's forward return: next 7 days' log return over the 30-day vol scaled to 7 days, less the day's cross-sectional mean, 15 Alpaca coins, squared error | 0 (no skill) | none | 7 days |

Features: M8's and M10's inputs (31 on the coin panels), M12's 10 for m12; on the coin targets up to two of G1's
expression trees (`lab.factory`, evaluated on the panel pivoted to day and coin). Learners: LightGBM (trees 100 to
400, rate 0.02 or 0.05, 3 to 15 leaves, 50 to 800 rows a leaf, L2 1 to 50), ridge (alpha 0.1 to 100) for the
numbers, logistic regression (C 0.01 to 1) for m8. No MLP: torch is not in the lab image. Window 1, 2, 3 years or all.

- Screen: quarterly walk-forward 2021-01 to 2023-12, expanding, purged (a training label ends before the test block
  starts), the baseline and the incumbent fitted in the same folds. Fitness: the smaller gain in % over the two.
- Held back: at most 2 screen passes a run (lower than both with DM p < 0.05) see 2024-01 to 2026-06; R6's lockbox
  (2026-07 on) is not looked at. Pass: lower than both with DM p < 0.05 / N, N every trial in the ledger.
- Shadows: a pass refits daily and logs its forecast before the outcome, scored against the baseline and the zoo's
  logged forecasts; 30 scored days make it eligible for the allocator (a Thompson draw per target, paper books
  only), 60 days behind the baseline or the incumbent retire it.

## The run

900 seconds of search in the agent container on the server's data (read only), 1,017 specs (none an error, 857
seconds of fitting), about 1 second a spec. The ledger is committed as `results/model_factory_seed/ledger.jsonl`;
the server's first run merges it, so these trials count there and the bar starts at 0.05 / 1,017 = 4.9e-05.

| Target | Specs | Lower loss than the baseline | Lower than the incumbent | Both | Screen passes |
|---|---|---|---|---|---|
| m8 | 267 | 26 | 90 | 26 | 0 |
| m10 | 262 | 0 | 10 | 0 | 0 |
| m12 | 242 (54 not scored) | 0 | 66 | 0 | 0 |
| fwd7 | 246 | 0 | (none) | 0 | 0 |
| all | 1,017 | 26 | 166 | 26 | 0 |

No spec passed the screen, so none was held back, none became a shadow and the allocator has nothing to pick.

- m8: the best (LightGBM, 3 leaves, 12 inputs, 3 years) has log loss 0.6912 against 0.6940 for the base rate (0.4 %
  lower, DM p 0.12) and 0.6959 for M8 (p 0.03): it beats the incumbent, which itself loses to the base rate, but not
  the base rate. 26 of 267 specs are below the base rate, none significantly. Next-day direction stays noise.
- m10: no spec beats HAR (best 0.7 % worse, the median 44 % worse). In
  2021 to 2023 M10 itself loses to HAR (QLIKE 0.250 vs 0.234); it wins 2024 to 2026-06 (0.352 vs 0.419), the zoo's
  own evaluation over both (0.288 vs 0.313) agrees. 10 specs beat M10 in the screen, none significantly.
- m12: no spec beats the last 60 days' correlation (best ridge on 3 inputs, 2 % worse); 66 beat M12 (best 22.7 %,
  p 0.14), which loses to the same baseline. 54 specs with a one-year window had fewer than the 300 training rows a
  fold needed (a year is about 250 trading days) and could not be scored; they count as trials. The minimum is 200
  rows since, so a one-year M12 spec is scored from the next run.
- fwd7: nothing beats zero. The best ridges shrink to it (gain 0.00 %), LightGBM is 0.3 to 3 % worse. The coins'
  7-day relative return is not forecastable from these inputs at this bar.
- Trees: 239 tree specs; none is the best of its target. Their median gain over the baseline is lower than the plain
  specs' on m8 (-0.66 vs -0.44 %) and a little higher on m10 (-39 vs -44 %) and fwd7 (-1.5 vs -1.6 %).

This is what was expected: most specs fail, and the ones near the top are within noise. The daily job keeps
mutating the best of each target; every spec it tries raises the bar for the next.

## Checks

`tests/test_model_factory_g2.py`: the purge (no training label reaches a test block), quarterly blocks, a leakage
test (every row after a day replaced by noise, and the labels not known by then: no forecast, baseline, incumbent
forecast, tree input or known loss before it moves; LightGBM, ridge, logistic, with and without trees), trees read
only the past, spec keys, the bar at 0.05 / N (a planted edge passes at N = 1 and fails once N makes its p
ordinary), noise does not pass, resumable runs that never repeat a trial and stop at the day's budget, the seed
merged once, a planted edge held back, admitted and logging shadow forecasts once a day, at most 2 new and 6 active
shadows, eligibility at 30 and retirement at 60 days, the allocator, the job in `jobs.yaml` and the briefing line.

Reproduce (the data folder read only, scratch output elsewhere):

```bash
PYTHIA_MODEL_FACTORY_DIR=/tmp/mf PYTHIA_MODEL_FACTORY_SEED=/tmp/none PYTHIA_REPORTS=/tmp/reports python -m lab.models.factory --budget 900
```
