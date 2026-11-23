# Search pause: what the factories and the small ledger delivered, and the rule's verdict

Pre-registration: `results/search_pause_prereg.md` (committed before this code and its first run). Code:
`lab.ops.search_pause` (reads only); numbers: `results/search_pause.json`, made 2026-11-23 from the server's data of
that day. Five trials in R5's registry, family hand, counted only (`hand:search_pause:*`), registered before the
numbers. Paper only: nothing a live bot, a wallet or the engine reads changes.

## The rule

A search job with no candidate of its own on the ladder's step 2 (tested) in the 6 weeks before the day of judgement
(2026-10-12 to 2026-11-22, judged 2026-11-23) stops generating new trials through its existing flag in
`research/ops/jobs.yaml`. It keeps re-scoring what it holds, its shadows and the paper books. It restarts when a
candidate of its own reaches step 2, or on the owner's word.

## Per job

Trials from each job's own ledger by run day (one per behaviour for the weekly factory and F2, as R5 counts; F3's
trial lines by night; G2's lines by run). Candidates: the job's ladder ids at the highest step they reached in the
ladder's report of today and the weekly page snapshots of 2026-11-01, -08, -15 and -22. Hours from the job runner's
records (`_ops/runs`), the wait for the lock left out; CPU hours are the heavy-lock hours times the job's `cpus`, an
upper bound. B_day: R5's daily noise bar a year (every family pooled; what the ladder's daily candidates are deflated
against), today against the registry without the job's lines, and in brackets by N alone at today's variance.
B_entry: the pump.fun rules' bar per entry (F3's variance at R5's N plus F3's ledger), today against N without the
job's trials.

| job | trials ever | in the window | a week (last 4) | candidates by step (0/1/2+) | verdict | runs | run h | heavy-lock h | CPU h (cap) | B_day today / without (N only) | B_entry today / without |
|---|---:|---:|---:|---|---|---:|---:|---:|---:|---|---|
| factory-weekly | 2,391 | 2,091 | 298 | 4/8/0 | pause | 6 | 0.9 | 0.5 | 2.0 | 3.077 / 3.155 (2.997) | 0.9128 / 0.8935 |
| factory-small (F2) | 1,451 | 1,405 | 351 | 0/0/0 | pause | 27 | 2.2 | 0.6 | 0.6 | 3.077 / 3.221 (3.033) | 0.9128 / 0.9019 |
| pumpfun-factory (F3) | 1,233 | 1,208 | 302 | 0/0/0 | pause | 27 | 44.5 | 44.2 | 132.6 | 3.077 / 3.077 (3.077) | 0.9128 / 0.9037 |
| model-factory (G2) | 61,622 | 61,622 | 15,406 | 0/0/0 | pause | 25 | 10.6 | 10.2 | 30.6 | 3.077 / 3.077 (3.077) | 0.9128 / 0.9128 |

Trials by week (Monday), 2026-10-12 to 2026-11-16:

| job | 10-12 | 10-19 | 10-26 | 11-02 | 11-09 | 11-16 |
|---|---:|---:|---:|---:|---:|---:|
| factory-weekly | 600 | 300 | 298 | 300 | 297 | 296 |
| factory-small | 0 | 0 | 379 | 342 | 357 | 327 |
| pumpfun-factory | 0 | 0 | 750 | 234 | 84 | 140 |
| model-factory | 0 | 0 | 16,025 | 15,046 | 15,313 | 15,238 |

G2's own bar (a DM p of 0.05 over its trials, in no other bar): p under 8.1e-07 today; G2 started inside the window
(2026-10-27, its committed seed run included), so there is no bar at the window's start.

What it delivered: the weekly factory has 12 candidates on the ladder, 8 on step 1 and 4 on step 0, none ever on step
2 (the eight on step 1 each miss the DSR over the registry and over the family and the family's PBO; the four
on step 0 the pre-registration before their first number). F2, F3 and G2 have no candidate on
the ladder at all: F2's 115 held-back looks all stopped, F3 has no paper book (`books.json` empty), G2's 50 held-back
looks passed none (46 beat the baseline, none the incumbent) and it runs no shadow. The F3 search held the `heavy` lock
44.2 h in the window, about 1.6 h a night; G2 about 25 minutes a day.

## The rule's verdict

All four: **pause**. None has a candidate of its own on step 2 in the window, and none has one now.

| job | flag in `research/ops/jobs.yaml` | before | what keeps running |
|---|---|---|---|
| factory-weekly | `command: python -m lab.factory --notify --budget 0` | 300 (`search.BUDGET`) | held-back looks at genomes already in the ledger, the lockbox step, shadow update and review, the digest |
| factory-small | `PYTHIA_FACTORY_SMALL_BUDGET: "0"` | 60 | held-back looks at its ledger's genomes, the 40 EUR shadow wallets, the report |
| pumpfun-factory | `PYTHIA_PF_FACTORY_TRIALS: "0"` | 300 | the factory paper books' night step, the LightGBM settings search for the retrain (no bar counts it), the report |
| model-factory | `PYTHIA_MODEL_FACTORY_BUDGET: "0"` | 1500 | the shadow step, held-back looks at specs already screened, admissions, the report |

Schedules, locks, timeouts and every other job stay as they were; `factory-shadow`, the paper books and every shadow
keep running; nothing is deleted, and every trial already in R5 or a ledger stays counted. Each job with its flag at
0 was run in the tests (`test_factory.py`, `test_factory_small.py`, `test_pumpfun_factory_f3.py`,
`test_model_factory_g2.py`): no new ledger line, the rest of the run and its report as before. Restart: the flag back
to its value before, by a commit, once one of the job's own ladder ids (`weekly:*`, `F2:*`, `book:F3_*`, `G2:*`)
stands on step 2, or on the owner's word; `python -m lab.ops.search_pause --print` shows the condition per job.

## In 8 weeks (to 2027-01-18), with and without the pause

Without the pause each job adds 8 times its weekly rate (mean of 2026-10-26 to 2026-11-22); with it the paused jobs add
0. Hand and pump.fun studies are held at today's count in both cases.

| | R5 trials | F3 trials | B_day (N only) | B_entry | G2 trials | G2 bar p |
|---|---:|---:|---:|---:|---:|---:|
| today | 7,400 | 1,233 | 3.077 (3.077) | 0.9128 | 61,622 | 8.1e-07 |
| without the pause | 12,592 | 3,649 | 2.949 (3.183) | 0.9493 | 184,866 | 2.7e-07 |
| with the pause | 7,400 | 1,233 | 3.077 (3.077) | 0.9128 | 61,622 | 8.1e-07 |

## Reading it

- **By N, every factory trial raises the bar.** At today's pooled variance R5's daily bar would go from 3.08 to 3.18
  a year in 8 weeks without the pause; the pump.fun rules' bar per entry from 0.913 to 0.949, the step 2 the five
  rules on the ladder have to clear; G2's own p bar would fall to a third.
- **The pooled B_day falls instead (2.95 without the pause), and that is not good news.** R5 pools the families'
  trial variances by weight. The weekly factory's and F2's in-sample Sharpes vary less than the hand studies', so
  thousands of them pull the pooled variance down more than their N pushes the bar up: without the weekly factory's
  lines today's B_day would be 3.16, without F2's 3.22. A large, cheap search thins the bar for everyone else's
  candidates through the variance. This is R5's pooling as written, measured here, not changed; whether a family
  should weigh by its trials is a question for the owner (no change without a pre-registration).
- **The heavy lock.** F3's search was 44 of the 56 heavy-lock hours the four jobs held in the window. With its trials
  at 0 the night keeps the LightGBM settings search (at most 25 minutes) and the books' step, so the lock is free
  an hour or more earlier each night. The jobs behind it waited: F2 ran 2.2 h in the window and held the lock 0.6 h,
  the rest was waiting, as the features job did before it moved to 00:20 (lane 12016).
- **What is not measured.** CPU hours are the docker cap times the lock hours (the records carry no CPU time). The
  job logs under `/var/log/pythia` are not on the data mount; the runner's records hold the start, end and status the
  measures need. G2's count includes its committed seed run (1,017 specs on 2026-10-27).

Five trials added: R5 7,395 to 7,400 (`hand:search_pause:weekly`, `:f2`, `:f3`, `:g2`, `:projection`).
