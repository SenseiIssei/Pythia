# Search pause: what the factories and the small ledger delivered, and a rule to pause their trials, pre-registration

Pre-registered 2026-11-23, before the code that measures and before its first run. From the review
`results/review_2026-10-27.md` (sections 2 and 3), R5's registry (`metrics.trial_pool`, `<data>/trials/registry.jsonl`),
R6's windows (in sample to 2023-12-31, validation 2024-01-01 to 2026-06-30, lockbox from 2026-07-01), the readiness
ladder (`lab.ops.ladder`, `results/readiness_ladder_prereg.md`) and the owner's rule of 2026-11-17 (care and measuring
first, no new searches).

## Why

R5's registry grows by about 45 small-ledger trials a day and about 290 weekly-factory trials each Sunday (factory
2,391 genomes, small ledger 1,451 on 2026-11-23). Every trial raises the noise bar for every candidate, the hand
studies' and the paper books' included. The ladder's best weekly genomes stand at a DSR of 0.001 with a PBO of 0.29
to 0.36, and no candidate of any search has reached step 2. The pump.fun factory holds the `heavy` lock for about
2.5 h a night and pushed the features job aside (lane 12016).

## The rule

**A search job that has produced no candidate on the ladder's step 2 (tested) in its last 6 weeks stops generating
new trials.** It keeps re-scoring the candidates it already holds. It restarts when a candidate of its own reaches
step 2, or on the owner's word.

1. **The jobs.** The four jobs of `research/ops/jobs.yaml` that make trials every week:
   - `factory-weekly` (the strategy factory W10 with G1's trees; R5 family `factory`; ladder ids `weekly:*`),
   - `factory-small` (F2, the small ledger; R5 family `small`, the lines from its ledger; ladder ids `F2:*`),
   - `pumpfun-factory` (F3; its own ledger `pumpfun_rt/factory/ledger.jsonl`, which the ladder adds to R5's count;
     ladder ids `book:F3_*`, its winners' paper books),
   - `model-factory` (G2; its own ledger `models/factory/ledger.jsonl` and its own bar, a DM p of 0.05 over its
     trials; ladder ids `G2:*`).
   A candidate "of its own" is a ladder row with one of the job's ids; a row of the same R5 family from elsewhere (a
   hand study's book) does not count for the job.
2. **The window.** The 6 calendar weeks before the day of judgement: Monday 2026-10-12 to Sunday 2026-11-22, judged
   on 2026-11-23. A job that started inside the window is judged on what it ran there; there is no grace period.
3. **On step 2.** A candidate counts as on step 2 when the ladder put it on step 2 or higher in its report of today
   (`reports/ladder/latest.json`) or in any weekly page snapshot dated inside the window
   (`reports/weekly/<date>.json`, its `ladder` map of id to step). The ladder keeps no other history.
4. **Pause.** The job's new trials go to 0 through its existing flag in `jobs.yaml`, nothing else:
   `factory-weekly` `--budget 0`, `factory-small` `PYTHIA_FACTORY_SMALL_BUDGET` 0, `pumpfun-factory`
   `PYTHIA_PF_FACTORY_TRIALS` 0, `model-factory` `PYTHIA_MODEL_FACTORY_BUDGET` 0. Each job keeps its schedule and
   does everything else it does: held-back looks at genomes already in its ledger, the lockbox step, its shadows'
   update and review, F3's paper books and its LightGBM settings search for the daily retrain (no bar counts those:
   upkeep of the retrain, not strategy trials), G2's shadow step. `factory-shadow`, the paper books and every shadow
   keep running. Nothing is deleted; every trial already in R5 or a ledger stays counted.
5. **Restart.** By a commit setting the flag back to its value before the pause, when a candidate of the job stands
   on step 2 in the ladder's report, or on the owner's word. The measurement can be rerun at any time
   (`python -m lab.ops.search_pause --print`) and names each job's restart condition.

The 6 weeks, step 2 as the line and the four flags are fixed here before any number below is computed.

## What is measured per job

1. **Trials a week.** From the job's own ledger by its run day, Monday-based weeks inside the window: the weekly
   factory's and F2's lines one per behaviour (a line `same_as` an earlier genome is not a trial, as R5 counts), F3's
   lines of kind `trial` by `night`, G2's lines by `run`. The rate for the projection is the mean of the last 4 full
   weeks (2026-10-26 to 2026-11-22).
2. **Candidates on each step.** The job's ladder ids, each at the highest step it reached in the window (point 3).
3. **CPU hours and heavy-lock hours,** from the job runner's records (`<data>/_ops/runs/<month>.jsonl`; the job logs
   under `/var/log/pythia` are not on the data mount and add nothing the records lack). A run's duration includes its
   wait for the lock, so its heavy-lock time runs from the later of its start and the end of the last other
   `heavy` run that ended inside it, to its end; a skipped run holds nothing. CPU hours are the heavy-lock hours times
   the job's `cpus` in `jobs.yaml`: the limit docker grants, an upper bound, since the records carry no CPU time.
4. **The bar's rise attributable to it.** The expected best Sharpe of noise (`metrics.expected_max_sharpe`) at
   today's N against N without the job's trials:
   - B_day, R5's daily bar a year (`trial_pool()`'s `sr0_annual`, every family pooled, what the ladder's daily
     candidates are deflated against): today's registry against the registry without the job's lines (the weekly
     factory: family `factory`, source `factory ledger`; F2: family `small`, source `small ledger`). F3 and G2 have
     no line in R5: 0.
   - B_entry, the pump.fun rules' bar per entry (`pumpfun_rt.factory.bar` over F3's Sharpes at the ladder's N, R5
     plus F3's ledger, as `ladder.pf_context`): today against N less F3's trials, F3's variance kept (the only
     per-entry variance there is). The weekly factory and F2 move it by their count.
   - G2's own bar, 0.05 over its trials, today and at the window's start (it counts in no other bar).
5. **In 8 weeks, with and without the pause** (to 2027-01-18): without, each job adds 8 times its weekly rate; with,
   the paused jobs add 0. Every other register (hand, pumpfun) is held at today's count in both, so the difference is
   the jobs'. New trials carry today's variance of their family. B_day, B_entry and G2's bar in both cases.

## Trials

Five in R5's registry, family hand, counted only (no Sharpe, no variance): `hand:search_pause:weekly`,
`hand:search_pause:f2`, `hand:search_pause:f3`, `hand:search_pause:g2` (each job's measured row and verdict) and
`hand:search_pause:projection`. They are registered before the first number. No strategy is tested, no variant
picked, nothing fitted.

## Checks

Tests on synthetic ledgers, run records and ladder snapshots: the rule pauses a job with no candidate on step 2 in
the window and keeps one with a candidate there, a candidate on step 2 before the window does not count, the lock
time leaves the wait out, the bar falls without a job's lines, the projection with the pause is lower; `jobs.yaml`
validates with the four flags at 0, every other field of the four jobs as before, `factory-shadow` unchanged. The
ladder and the weekly page are rendered from the server's reports into a scratch folder after the change.

Paper only: nothing a live bot, a wallet or the engine reads changes.
