# T3: the readiness ladder. Its rules (2026-10-29)

Written 2026-10-29, after the code. `lab.ops.ladder` (T3) has cited this file since it was written, but the file was
never committed; an audit on 2026-10-29 found that and found that the ladder let candidates climb on missing or stale
evidence. This file is not back-dated. It states the rules the code implements as of the commit that fixes the audit's
findings (the commit after this one), and nothing was promoted under the old rules: on the lab's data every candidate
stood on step 0 or 1 before the fix and stands there after it (24 on step 0, 14 on step 1, 2026-10-29). Background:
the review of 2026-10-27 (`results/review_2026-10-27.md`, sections 2 and 3), R5's registry (`metrics.trial_pool`,
`<data>/trials/registry.jsonl`), R6's windows (`results/factory_lockbox_r6.md`: in sample to 2023-12-31, validation
2024-01-01 to 2026-06-30, lockbox from 2026-07-01). Paper only: the ladder proposes, it never arms, changes or sends
anything, and no live bot, wallet or the engine reads it.

## What the ladder is

One row per candidate: every paper book (`lab.ops.paper_books`), every survivor of the weekly factory and F2
(`<data>/factory/holdout.jsonl`, `factory/small/holdout.jsonl`, a decision other than stopped), every active shadow
(the weekly factory's `<data>/factory/shadow/*.json`, F2's and G2's reports). Each step requires the one before. It
reads only, writes only `reports/ladder/latest.json` and `.md`, and computes no performance number of its own: it makes
no trial. Recomputing a stored DSR against today's registry (step 2) is the same candidate deflated again, not a new
trial.

## The conditions

A condition passes, fails or is open. **Open is allowed on step 1 only** (the pre-registration's commit date when there
is no git and no date in its title). **From step 2 on everything fails closed**: missing evidence fails, and `climb()`
treats an open condition on step 2 or above as a fail.

1. **idea.** A pre-registration known for the candidate's study exists, and was committed on or before its first
   number (its results file's commit, a different commit; else its first day).
2. **tested.** All of:
   - **leak (T1).** A positive record. A genome: a clean check in `<data>/factory/leak_passed.jsonl` (F2:
     `factory/small/leak_passed.jsonl`), which `run.leak_screen` writes for every genome that passes the leak harness
     before its held-back look; a rejection in `leaks.jsonl` fails. The day a genome was held back proves nothing. A
     book: a passing row under its name in T1's weekly report `reports/leak/latest.json`; no report, or the book not
     in its list, fails.
   - **late.** Filled one close late still positive (R10's late CAGR, the worse of 40 and 100 EUR; the weekly
     factory's late Sharpe at 35 bps; F2's late CAGR).
   - **era.** Costs of their era (R10's rows; the weekly factory's 70 bps stress; F2's genomes fail: today's Jupiter
     quotes back to 2018).
   - **dsr_all, dsr_family.** DSR (higher is better) at least 0.95 over R5's whole registry and over the candidate's
     family **as of today**. A held-back row with its excess series stored (`oos_excess_returns`, written by
     `factory.evaluate.holdout` from 2026-10-29) is recomputed: N today's `metrics.trial_pool()` of all and of the
     family, the variance the family's in-sample excess one (`ledger.pool`, `ledger.deflated_excess`). Without the
     series the row's own DSR counts only while the trial count it was deflated over is at least 90 % of today's
     (`DSR_STALE`); below that it fails as stale. A DSR only falls as N grows, so a stale pass is never trusted and a
     stale fail stays a fail. No count, no reported value, or an unreadable registry fails. R10's rows are taken from
     its report as published.
   - **pbo (T2).** The PBO of the candidate's run's family below 0.2. Not measured fails: the paper books and G2 have
     no PBO today and stay on step 1 until a study measures one for them.
3. **shadow.** 30 days logged, counted as unique dates of the journal or shadow CSV (a rerun's second row of a day is
   not a second day), and **before (T8)**: a passing row for the candidate in `reports/shadow/latest.json`. No T8 report
   fails.
4. **lockbox.** R6's one look made (`<data>/factory/lockbox.jsonl`, by key or behaviour), against the right benchmark
   (crypto BTC and ETH held, small accounts a UCITS S&P 500 fund in EUR, neutral books 0), its DSR over every look at
   least 0.5.
5. **execution.** At most 50 EUR, no top-up in the first 90 days, no reconciliation mismatch, never 2 failed swaps in a
   row, costs at most 2x the model over the last 10 swaps, at most 1 % drift from the paper twin, 90 days judged
   (`reports/execution/latest.json`). P3's 10 EUR pump.fun books: the gate for real money of
   `results/ten_eur_p3_prereg.md` instead.
6. **larger.** Only the owner; the ladder never sets it.

## What changed in the code with these rules

- `climb()` fails closed from step 2; leak, PBO and T8 without evidence fail instead of being open.
- `run.leak_screen` logs clean checks as positive records (`leak_passed.jsonl`, next to `leaks.jsonl`, which the
  picks keep reading for rejections only).
- `factory.evaluate.holdout` writes `dsr_family`, `family_trials` and `oos_excess_returns` (until now only F2 wrote
  `dsr_family`, so every weekly genome failed it as "not reported").
- Shadow days are unique dates, not journal rows.
- Not the ladder, from the same audit: `lab.experiments.modern_m1` judges on validation only (to 2026-06-30) and
  registers its judged books as trials in R5's registry; its job stays off.

## What it means today

The weekly factory's one shadow (44444c97ba5e) was deflated over 677 trials against 2,803 in the registry today; it
has no stored series, so its DSR is refused as stale, and it has no clean leak record and no PBO for its run. It
stands on step 0 regardless (R6 was registered after its first number). No number is computed for this file.
