# T2: overfitting yardsticks. Pre-registration

Registered 2026-10-28 and committed before any of the yardsticks below ran on
real data. Brief T2 of the training plan of 2026-10-28, on the review of
2026-10-27 (`results/review_2026-10-27.md`, sections 2 and 3: the zoo churns,
the README says "purged" while `cv.py` only embargoes, `cv.py`,
`deflated_sharpe` and `labels.py` need tests), R5's trial registry and R6's
windows (in sample to 2023-12-31, validation 2024-01-01 to 2026-06-30, lockbox
from 2026-07-01). Code written after this file: `lab/metrics.py` (CSCV, the
stationary bootstrap, SPA, MCS), `lab/cv.py` (the purge, CPCV),
`lab/factory/evaluate.py` and `run.py`, `small.py` (F2), `lab/models/factory.py`
(G2), `lab/ops/registry.py` and `lab/models/train.py` (the zoo),
`lab/experiments/xs_daily.py` (M4). Nothing here may change once a result
exists. Paper only: vol_1h and picks_7d (the models the engine loads) keep
their rule; nothing a live bot or a wallet reads changes.

## Question

Does a pass mean something? Four yardsticks that measure how much of a
result the search made, each on the factories' own trials:

1. **PBO by CSCV** (Bailey, Borwein, Lopez de Prado, Zhu). The days cut into
   16 blocks, every one of the C(16, 8) = 12,870 halves in sample and the rest
   out; per split the in-sample best (by Sharpe; for G2 by mean loss) and its
   relative rank out of sample, w; the logit log(w / (1 - w)) per split. PBO is
   the share of logits at or below 0. Reported per family with the logits'
   5, 25, 50, 75 and 95 % quantiles and their histogram (bins of width 1 from
   -3 to 3, open at both ends).
   - weekly factory: every genome of the current in-sample window in its
     ledger, one per behaviour, at most the 2,000 best by fitness, on its
     in-sample returns at 35 bps (R6's existing `evaluate.pbo`, extended);
   - F2: the same on its ledger, the 40 EUR wallet's in-sample returns;
   - G2: per target, the specs screened in the run, on minus their per-day
     mean loss in the screen window (2021 to 2023).
2. **Combinatorial purged CV** (Lopez de Prado, AFML ch. 12; skfolio's
   `CombinatorialPurgedCV` as the reference, written with numpy). The times
   cut into N contiguous groups, every choice of k as the test set; a training
   row whose label reaches into a test group is purged, one within the
   embargo after a test group is dropped. Each group's test values are put
   together into C(N-1, k-1) paths, each path one out-of-sample series over
   every time. For every candidate that reaches validation:
   - weekly factory and F2 (rules without fitted parameters): N 12, k 3 (220
     splits, 55 paths) over the in-sample window, purge 1 day, embargo 1 % of
     the days. On each split the candidate and its near variants (the family's
     genomes whose in-sample returns correlate above 0.5 with it) are ranked
     by training Sharpe and the best one's test days go into the paths, so the
     paths measure picking in this region of the search the way the search
     picks. A candidate without variants has one path repeated (said so).
     Reported: the median and the 10th percentile of the paths' annual Sharpe.
   - G2: N 6, k 2 (15 splits, 5 paths) over the screen window, purge the
     target's purge days, embargo 1 % of the days, the spec and the baseline
     refitted on every split; reported the median and the 10th percentile of
     the paths' loss gain over the baseline in %.
   - `cv.walk_forward` gets the purge too: a training row whose label (its time
     plus the horizon, or a given label end) ends at or after the test start is
     dropped, on top of the embargo.
3. **Hansen's SPA test and the model confidence set** (Hansen 2005; Hansen,
   Lunde, Nason 2011; `arch` as the reference, written with numpy). Loss
   differences against a benchmark, the stationary bootstrap of Politis and
   Romano (mean block 10 periods, 1,000 draws, seed 7), the studentised
   maximum, the consistent p-value (lower and upper reported next to it). MCS:
   the T-max statistic, eliminating the worst model while the set is rejected
   at 10 %, MCS p-values as the running maximum.
   - The zoo (M8, M8q, M8u, M10, M11, M12): each candidate's SPA p against its
     baseline on the per-period walk-forward losses, on its card next to the
     Diebold-Mariano gate (the gate itself is unchanged).
   - **Zoo promotion.** A challenger that passes its gate replaces the
     champion only when SPA, with the champion as the benchmark, rejects "no
     better than the champion" at 5 % (consistent p under 0.05) on the
     per-period losses of the rows the champion never saw (the window minimum
     stays). The fixed margin no longer decides for zoo models. The decision
     record also holds the MCS at 10 % of challenger, champion and baseline.
   - **Zoo retraining.** A zoo model with no champion whose last challenger
     failed its own gate is not retrained on schedule while no book reads it
     (its `used_by` is empty); `--force` still retrains it.
   - M4 (`xs_daily`): SPA per family on the validation window only (2024-01-01
     to 2026-06-30, never the lockbox), loss minus the daily net return at
     15 bps: the long-only model books against the equal-weight 100 most
     liquid coins, the long/short and funding-aware model books against the
     low 28-day vol book (10/10 of 100 liquid perps, buffer 50 %). MCS over
     every book and baseline book.
4. **One line per candidate** in the weekly factory's and F2's reports: the
   DSR of the excess (higher is better, pass at 0.95 or more), the family's
   PBO, the CPCV median and 10th percentile; in G2's report the same line with
   the DM p of the look (lower is better) instead of the DSR.

## Pass and fail on synthetic data (the tests)

- Families of pure noise: PBO between 0.35 and 0.65 (the mean over seeds near
  0.5); SPA at 5 % rejects in at most 10 % of noise draws; the CPCV median of a
  noise candidate within 1 Sharpe of 0.
- A planted edge (one strategy with a true annual Sharpe of 3 to 4 among noise,
  or a model with a lower true loss): PBO under 0.1, SPA rejects, the MCS keeps
  it and drops a clearly worse model, the CPCV 10th percentile above 0.
- The purge: no training row's label overlaps a test group, the embargo
  holds, every time is tested once per path.

## The replay on the lab's data

The zoo's last 30 days (2026-09-28 to 2026-10-28) replayed: for each zoo model
every pair of consecutive candidates in its registry folder (the older as the
incumbent), compared on their common walk-forward rows by the margin rule and
by the SPA rule; and every scheduled retrain in the decision logs that the
retraining rule would have skipped. Expected: the SPA rule swaps no more often
than the margin rule, and only where the gain is real; the retrains of the
models that failed their gates (M8, M10, M11, M12) are skipped. Written to
`results/overfit_yardsticks.md`.

## Trials

PBO and CPCV are measured on trials already in their ledgers and in R5's
registry, in sample only (no new variant, no look at validation or the
lockbox): they add no trial and move no bar. M4's SPA and MCS are one new look
at books already counted: registered as one trial of the hand family
(`hand:t2_m4_spa`) when it first runs. The zoo's and G2's comparisons are
model losses, not daily Sharpes, and stay out of the registry as G2's trials
already do (`lab/models/factory.py`), written down in each model's
`decisions.jsonl` and in G2's ledger instead.
