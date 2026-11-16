# Trial register audit: the trials studies declared against what R5 holds. Pre-registration

Registered 2026-11-16 and committed before any number of this audit was computed. On the review of 2026-10-27
(`results/review_2026-10-27.md`, sections 2 and 3: trial counts spread over constants and reset per mode), R5's
registry (`metrics.trial_pool`, `<data>/trials/registry.jsonl`, append only, the first id wins), R6's windows (in
sample to 2023-12-31, validation 2024-01-01 to 2026-06-30, lockbox from 2026-07-01; the audit reads counts only and
makes no look at any window), T14's merge (`lanes.py trials`: a run's registry copy `/out/trials/registry.jsonl`
appended by id into `<data>/trials/registry.jsonl`) and the readiness ladder (`lab.ops.ladder`). Paper only: nothing
a live bot, a wallet or the engine reads changes.

Numbers seen before this file: the task's statement (R5 holds 4,600 rows, 6,035 trials: hand 2,242, factory 2,134,
small 1,602, pumpfun 57; the ladder deflates pump.fun rules over 7,120, the weekly page prints 5,983) and today's
registry by family and source (4,647 rows, 6,124 trials, pumpfun 146), the ladder's 7,204 and its P_pool0 DSR
(0.000), the factory report of 2026-11-15 (pool 5,983). No declared count was read against R5 yet.

## What counts as a trial

A trial is one configuration (a rule, a parameter set, a book, a model, a cost view, a universe) whose performance
number a study computed on data and could have chosen or reported: what the study itself calls a trial. Checks
that compute no performance number (an audit of clocks, a page, a data repair, a leak harness) count 0 when the
study says it makes no trial. A study that ran only part of what it pre-registered counts what its result says it ran; a study without a
result counts what its pre-registration declared (an unfinished run may still have looked).

## Where a study's declared count is read

For every `results/<name>_prereg.md`: its result `results/<name>.md` when that exists and states the count, else
the pre-registration. Each declared count is kept in `lab.ops.trial_audit` with the file it was read from and a
verbatim quote of the sentence; the audit checks that the quote is still in that file (a quote gone fails the row).
The family is the one the study declared, else its module's (pump.fun studies `pumpfun`, the small account `small`,
the factories `factory`, the rest `hand`).

## What R5 holds for a study

Every registry line whose `source` names the study's pre-registration or result (with or without the
`research/lab/` prefix), plus the seed blocks of `metrics.TRIAL_SEED` that name it. Studies a seed block counts
together form one group: the group's declared sum against the block's n. The factory and small ledgers' genomes
(`source` "factory ledger", "small ledger") are each factory's own count and are not audited here. F3's pump.fun
genomes live in their own ledger (`<data>/pumpfun_rt/factory/ledger.jsonl`, per-entry Sharpes, outside R5 by
design): the audit states how many there are and how the ladder adds them (R5 plus F3's ledger, all and pumpfun).

## Duplicates and the missing rows

Matched by id, the first id wins (`metrics.register`, as T14 merges). Missing = declared less registered, at least
0; registered above declared is shown, never removed. Each missing count is appended through `metrics.register`
into the run's registry copy as one counted-only block, id `audit:<study>`, the study's family, `n` the missing
count, `sharpe` and `var` null (it raises N and leaves the variance alone), `source` the file the count was read
from. No Sharpe is invented: where a study stored a per-trial series of daily Sharpes in R5's convention it is
used, else the block only counts. A later run of the audit sees its own block as registered and appends nothing.

## The one total

The ladder and the weekly page print the same total: R5's registry (every family) plus F3's ledger, with one line
naming both registers and their counts; the weekly page takes it from the ladder's report.

## What is reported

`results/trial_audit.md`: study, declared, registered, missing, family, source. Then today's DSR of P_pool0 (per
entry, over R5 plus F3, all and pumpfun) and of the best genome of the weekly factory's held-back check (2026-11-15)
before and after the appended rows; both can only fall. The two recomputed DSRs are 2 trials, counted only
(`audit:recheck:P_pool0`, family pumpfun; `audit:recheck:genome`, family factory).
