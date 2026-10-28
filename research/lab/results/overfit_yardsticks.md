# T2: overfitting yardsticks. Results

Pre-registered in `results/overfit_yardsticks_prereg.md` (committed first). Run 2026-10-28 in the agent container on
the lab's data folder, read only. Code: `lab/metrics.py` (cscv, stationary_bootstrap, sb_variance, spa, mcs),
`lab/cv.py` (the purge in walk_forward, cpcv, cpcv_paths, assemble), `lab/factory/evaluate.py` (family_pbo, cpcv,
candidate_line), `run.py` and `small.py`, `lab/models/factory.py` (target_pbo, cpcv_spec, look_line),
`lab/ops/registry.py` (spa_judge), `lab/models/train.py` (gate_hold, replay), `lab/experiments/xs_daily.py`
(spa_tests). Tests: `tests/test_overfit_t2.py`. No new trial in the registry yet (see the end).

## On synthetic data (the tests)

| yardstick | pure noise | planted edge |
|---|---|---|
| PBO by CSCV, 30 strategies, 1,600 days, 16 blocks, all 12,870 splits | mean 0.49 over 10 seeds (0.29 to 0.76) | 0.00 (one strategy at Sharpe 3.5) |
| SPA at 5 %, 5 models, 300 periods | rejects 5.5 % of 1,000 draws (one model 5.4 %; 600 periods 6.8 %) | p under 0.05, the right model named |
| SPA on the zoo's shape: one challenger, 60 days of 5 rows | 8.5 % (block 10; block 4 gives 6 %, block 1 4 %) | |
| MCS at 10 % | keeps 3 or 4 of 4 equal models | keeps the best, drops models 0.6 and 1 worse |
| CPCV of a candidate with 11 near variants, 2,190 days, 55 paths | median Sharpe 0.20, 10th percentile 0.12 | median 3.26, 10th percentile 3.16 (Sharpe 3) |
| zoo promotion, the challenger the champion with fresh noise, 40 draws of 120 days | the margin swaps in 20, SPA in 3 | a truly lower loss is promoted, the champion leaves the MCS |
| G2 CPCV (15 splits, 5 paths) on fwd7 | median gain within 2 % of 0 | 10th percentile gain above 0 |

The SPA test is a little liberal on short windows with the pre-registered block of 10 periods (8.5 % at 60 days).
M8's and M10's windows are at least 21 days by their own minimum (M12 60); the margin rule it replaces swapped on 20 of
40 draws of pure noise.

## The zoo's last 30 days replayed (2026-09-28 to 2026-10-28)

`python -m lab.models.train --replay 30` on `<data>/models/registry`:

| model | incumbent | challenger | gate | common rows | margin would swap | SPA p | SPA would swap |
|---|---|---|---|---|---|---|---|
| M8 | 20261015T1243 | 20261025T0715 | failed | 30,750 | no | 1.000 | no |
| M8q | 20261015T1243 | 20261025T0715 | passed | 30,750 | no | 1.000 | no |
| M10 | 20261015T1243 | 20261025T0715 | failed | 40,422 | no | 1.000 | no |
| M11 | 20261015T1243 | 20261026T0715 | failed | 10 | yes | 1.000 | no |

- No champion was replaced in the window under either rule. Consecutive candidates make the same walk-forward
  predictions on the rows they share (a retrain refits the same folds), so on those rows they tie exactly; the only
  difference is the newest rows. M8q's real decision (2026-10-25) was "kept" for too few unseen rows (135 rows over
  9 days, needs 300 and 21) and stays so under SPA. M11's 10 shared rows (7 timestamps) would have passed the margin;
  SPA needs at least 10 periods and says no.
- The gate hold would have skipped 3 of the window's retrains: M8 and M10 (2026-10-25) and M11 (2026-10-26), each
  after a failed gate on 2026-10-15, none read by a book. M12 (every 28 days) was not due in the window and is held
  from now on too. M8q and M8u passed their gates and keep their schedule.

## The weekly factory's family on the lab's data

The ledger has 900 genomes, all from the in-sample window before D1 (`is_from` 2020-08-01), so the next weekly
run's "family" (the genomes of the current window) starts empty and fills as it searches. Measured here on all 900
(one per behaviour) on today's in-sample window (2018-01-01 to 2023-12-31, 35 bps), 84 s:

- PBO of the family 0.45 over 900 genomes (12,870 splits of 16 blocks); rank logits 5/25/50/75/95 %: -1.51 / -0.44 /
  0.10 / 0.90 / 2.29; histogram <-3 33, -3..-2 282, -2..-1 948, -1..0 4,577, 0..1 3,965, 1..2 1,938, 2..3 988,
  >3 139. Picking the in-sample best of this family is close to a coin flip out of sample.
- CPCV of the 16 genomes ever held back (55 paths each, in sample): medians 1.49 to 1.85, 10th percentiles 1.23 to
  1.70, against in-sample Sharpes of 1.59 to 2.05. All but one were stopped by their held-back gates (the 2024 to 2026
  window), the other became a shadow. An in-sample CPCV cannot see a change of regime: it measures how much of a
  rule's in-sample Sharpe is picking, not whether the market stays the same.

**Deviation from the pre-registration.** The pre-registration named near variants as genomes correlating above
0.5 in sample. On the real ledger that makes 649 to 755 of the 900 genomes every candidate's variants (every long
crypto book moves with BTC), so all 16 candidates got the same paths (median 1.10, 10th percentile 0.81): a number
for the whole search, not one per candidate. The code uses 0.9 instead (`evaluate.CPCV_CORR`, the factory's own
threshold for "mutually different", run.DIVERSITY_CORR); the numbers above are at 0.9 (4 to 89 variants each). The
change was made after seeing that the 0.5 lines were identical, not after seeing any pass or fail: no candidate
changes its decision, and nothing here moves a bar.

## What runs where from now on

- Weekly factory (`python -m lab.factory`, Sundays): the family's PBO and logits, a CPCV and a line per genome
  held back (`## Each candidate held back (T2)` in `reports/factory/latest.md`). About 0.17 s per genome rebuilt,
  at most 2,000: under 6 minutes.
- F2 (daily): the same on its ledger (about 0.02 s a genome).
- G2 (daily): the PBO of each target's specs screened that day and, per look, a CPCV of the screen window
  (15 refits).
- The zoo (daily): SPA p on every card next to DM; the champion changes only on SPA; failed models wait for a book.
- M4 (`python -m lab.experiments.xs_daily`, by hand): the SPA and MCS section on the validation window; its first run
  registers `hand:t2_m4_spa`. Not run here (it refits every model for about an hour).

## Trials

None registered by this run: the PBO and CPCV above are on genomes already counted, in sample only, and the zoo's
replay compares model losses (outside the registry like G2's). M4's one trial is registered by its first run on the
server.
