# T1b: the lowkr leak and the ladder candidates T1 never checks. Pre-registration

Registered 2026-11-16 and committed before the leak check ran on the new book list. On T1
(`results/leak_harness_prereg.md`, whose rules hold unchanged), the review of 2026-10-27
(`results/review_2026-10-27.md`, sections 2 and 3), R5's trial registry (`metrics.trial_pool`,
`<data>/trials/registry.jsonl`), R6's windows (in sample to 2023-12-31, validation 2024-01-01 to 2026-06-30,
lockbox from 2026-07-01) and the readiness ladder (`lab.ops.ladder`). Paper only: nothing a live bot, a wallet or the
engine reads changes. Code: `lab.leak`, `lab.experiments.kr_premium_xs`, `lab.ops.ladder`, `lab.ops.jobs`,
`lab.ops.weekly`, `lab.paper.forward_report`. Results: `results/leak_coverage.md`.

Seen before this file: the weekly leak report of 2026-11-15 (134 checked, 1 red: tranches_filtered
tsmom_tranches_lowkr, "ARBUSDT at 2023-06-08 moves when the data after 2023-06-08 changes (shift, shuffle)"), those
of 2026-11-01 and 2026-11-08 (0 red, cuts 2023-06-01 and 2023-06-03), the ladder of 2026-11-16 (25 candidates
"not checked (... is not in T1's book list)") and one reproduction of the red on the lab's panel at the cut
2023-06-08 (red before the fix below, no leak after it, on the same cut and on the default cuts).

## 1. The red on tsmom_tranches_lowkr

Cause: `kr_premium_xs.signal`'s ticker clash guard dropped a coin's whole premium column when the median |premium|
of its first 30 Upbit days was over 10 %. On a day inside those 30 days that reads up to 29 days ahead. GRT's Upbit
days start a few days before 2023-06-08; with the data after the cut changed its column is kept or dropped
differently, which moves the cross-sectional rank of the other coins (ARB) on the cut day. The cuts of 2026-11-01
and 2026-11-08 (2023-06-01, 2023-06-03) fell before GRT had the five Upbit days its 7-day mean needs, so
nothing at or before them moved: the panel grew a week, the
cut moved past it. The Upbit file did not change the result.

Fix: the guard point in time. Each day judges the coin on the median |premium| of its first 30 Upbit days known by
then (fewer until it has 30); from the 31st on, as before. A test plants a coin that is calm on its first Upbit days
and clashes after: red on the old guard, green on the new.

The paper record of tsmom_tranches_lowkr through 2026-11-16 (its last journal row before the fix) is frozen the
way the forward audit froze breakout_top10 (`forward_report.FROZEN`): it counts toward no forward gate and no
readiness rule, a fresh record starts with the next run, and reports/forward says so. The study's own numbers
(`results/kr_premium_xs.md`) are not rerun here; it was forward evidence only and stays an experiment.

## 2. The 25 candidates

Each gets its signal builder into T1's book list (`lab.leak.checks`, the weekly job), run as T1 runs a book (n
cuts between the 50 % and 95 % quantiles, shuffle, shift, missing, the recursive cut), or, where there is none, a
line in the ladder that names the check that applies instead and why.

- **EQ1's ten ETF books** (`eq1_<rule>_<once|plus50>`): `etf_books_eq1.targets` per rule on the closes the paper
  book reads (`etf_books_eq1.load(to=None)`), every close's targets compared as held. One check per rule
  (`etf_books <rule>`, five); both variants share it, the monthly top-up does not change a target.
- **small40_spy_trend, small40_vol_target** (S2): `smallaccount_s2.candidate` on the market the paper book builds
  (`smallaccount_s2.market` on the fam_common panel and SPY's and GLD's closes in `<data>/etf/daily`), targets
  compared as held (`smallaccount small40_<rule>`).
- **funding_carry, m4_perps, m4_hl_small**: from the xs_daily panel the books read (the lab cache, its newest 400
  days, rows known at the day's end), `xs_daily.ranked` and then each book's daily choice: funding_carry's
  candidates and tranche, M4's candidates with the book's cached model and its rank buffer day by day. The model is
  held as the book holds it (trained on labels known by its decision day); the check is on the features and the
  choice, the retrain itself is not rerun per cut. Every perp counts as listed and trading (the listing is read at
  run time, not from the history).
- **Not applicable, stated in the ladder:** the pump.fun books (P3's P_*_10eur, R2's P_pool5_*, and the other
  pump.fun paper books) are event rules on the live pump.fun stream, decided when a trade arrives; T1 needs a
  function of a panel or of rows with a known-at time, which they are not. The check that applies is P1's taint
  rule on their paper ledger (a fill before its signal or an exit decided before the landing is out,
  `pumpfun_rt.realistic.tainted`), which the ladder already applies; the line passes when the ledger was read.
  The onchain_meme books decide on the live snapshot of each run and fill at a live Jupiter quote: there is no
  history their rules read, so nothing after a decision can reach it; their record is forward only and the line
  says so.

## 3. Health and the weekly page

A red leak was already a red line in the health check (`jobs.leak_lines`, `_health/system.json`), but not in
`_health/jobs.json`, which the weekly page reads, so the page said all jobs were green. Now `_health/jobs.json`
carries the red leak lines (`leaks`), and the weekly page's red section lists every red line of
`reports/leak/latest.json` with its reason, and its short version counts them.

## Trials

None. The leak check answers yes or no per function and makes no performance number; it looks at no window's
returns. Nothing here registers a trial in `<data>/trials/registry.jsonl`; the frozen record and the fix change no
number already registered.

## Run

The weekly job's book part on the new list once into `/out` (`PYTHIA_REPORTS`), with the counts in
`results/leak_coverage.md`.
