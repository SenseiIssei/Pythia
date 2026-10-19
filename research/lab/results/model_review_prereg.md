# X9 model review: pre-registration

Written and committed on 2026-10-20 before any of the numbers below were
computed. What was known when this was written: the zoo report of 2026-10-19
(only M8q beats its baseline, every zoo model shows drift "shift"), the
forward report of 2026-10-19 (13 days), the published results of C6
`m2_longonly` (70 trials) and `momentum_m2` (4 trials), both of which already
tested M2 as a loser filter on long-only books and found it worse than the
book alone. Nothing in this file is changed after the first result exists;
anything added later goes into `model_review_studies.md` and says so.

## The pool

Hand-study trials before this study: 377 (to C16, at their published bar
2.43) + 231 counted in parallel (listings 16, memecoins 50, equities 45,
fast_maker 53, intraday_equities 46, alpaca36 21) + 198 (X6 flow overlays)
+ 39 (X7 A overnight) + 30 (X7 B book portfolio) = **875**, plus every genome
in the factory ledger at run time (600 on the PC on 2026-10-20). This study
adds the Sharpe trials counted below (**29**). Deflation as in X6: pooled
variance of daily Sharpes (prior at the variance backed out of the published
bar, the factory at its own, this study at its own). The model studies that
are not Sharpe trials (drift, IC) are corrected inside the study (Bonferroni)
and listed here so they are not run twice.

Common to every money study: the sweep's survivorship-free daily panel, the
books as the autopilot runs them on Alpaca (coins Alpaca does not list stay
cash, `alpaca_universe.cash_left`), judged out of sample from 2024-01-01 at
**35 bps** per unit of one-way turnover (Alpaca taker plus slippage), 15 and
70 bps reported. A weight decided at the close of day t earns day t+1. The
three books are X6's: `breakout_top10`, `tsmom_top20` (daily) and
`tsmom_tranches`. `tsmom` and `tsmom_regime` (fixed list of 20, older paper
books) are not rebuilt here; `tsmom_regime` is `tsmom_top20`'s rule on a
fixed list.

The six gates (X6's, unchanged), each against the same book alone:
1. Sharpe at 35 bps above the book's, and better in 2 of 2024, 2025, 2026;
2. max drawdown below the book's;
3. moving-block bootstrap (20-day blocks, 5,000 draws) 90 % band of the daily
   Sharpe difference above 0;
4. still above the book's Sharpe when the overlay or filter acts a day late;
5. on the survivorship-free twin (the original book, unlisted coins
   included) at least the twin book's Sharpe;
6. deflated p of the improvement (daily difference series) above 0.95 over
   this study's 29 trials.

## a. M8q as a risk tool (18 trials)

M8q's out-of-sample predictions come from its own purged quarterly
walk-forward (`lab.models.core.evaluate`, first test quarter 2021-Q1),
re-run on the PC with the code as it is; no parameter of M8q is touched.

- **Signal.** D_t = minus the mean over the Alpaca coins with a forecast that
  day of M8q's 10 % quantile for day t+1 (features at the close of t). The
  **control** is the same from M8q's own baseline quantile (the training
  window's 10 % quantile of the vol-scaled return times today's 30-day vol),
  that is plain vol targeting; M8q has to add something over it.
- **Rules.** (i) *scale*: S_t = min(1, M_t / D_t), M_t the trailing 365-day
  median of D (at least 180 values, S = 1 before); (ii) *cap*: S_t = 0.5
  when D_t is above its trailing 365-day 80th percentile, else 1. Exposure
  changes trade the book proportionally (turnover |dS| x exposure), as in X6.
- **Trials.** 2 rules x 2 sources (M8q, control) x 3 books = 12; the
  in-sample pick per book (better 35 bps Sharpe of the two M8q rules on
  2021-07 to 2023-12, the days with a signal) gets a day-late and a twin run:
  6. Total 18.
- **Pass.** All six gates, and **7**: the pick's out-of-sample Sharpe at 35
  bps above the control with the same rule on the same book.
- **Prior.** `vol_managed` found RW30 overlays hurt both books (1.05 vs 1.11,
  0.27 vs 0.52). A failure is the expected outcome.

## b. M2 bottom third as a long-only filter (9 trials)

C6 already showed the filter hurting (tsmom on the 15: 0.70 vs 0.86, share
of bootstrap draws above the book 0.01; breakout 0.77 vs 0.87). This is one
confirmatory run on the books as they run today, with the cut fixed in
advance (`momentum_m2`'s original: bottom third), no search.

- **M2 scores.** C6's cache (`m2_longonly_scores.parquet`): LambdaRank
  retrained monthly point in time on the whole survivorship-free universe,
  scores from 2022-01-01; percentile within each day's whole scored
  universe.
- **Rule.** A coin whose M2 percentile is below 1/3 that day is dropped from
  `tsmom_top20` (its slot stays empty, the book is not re-levered), cannot be
  entered by `breakout_top10` (held positions follow the book's own exit),
  and is dropped from the tranche targets of `tsmom_tranches`. A coin
  without a score is never filtered.
- **Trials.** 3 books x (filter, day late, twin) = 9.
- **Pass.** Gates 1 to 6.
- **Diagnostics (not trials).** Spearman correlation between M2's score and
  28-day momentum inside each book's universe; M2's 7-day rank IC inside the
  top 20 by liquidity against the whole universe, from 2024.

## c. Drift (no trial)

Question: is "shift" on every zoo model a property of the inputs or of the
test? Measured on M8/M8q's panel (the 15 Alpaca coins), M10's and, where its
data loads, M12's:

1. **False-alarm rate.** Bins from training rows before 2024-01-01; the
   current rule (`core.drift_check`, per feature shift at PSI > 0.25 or more
   than 2 % outside the 0.5 to 99.5 % range, drift above 5 %; the model takes
   its worst feature) applied to every 30-day window (step 7 days) before
   2024 (in sample: the bins have seen these days) and from 2024 (out of
   sample). Miscalibrated if more than 50 % of the in-sample windows say
   "shift" for a model.
2. **If miscalibrated, the fix**, decided now: per feature, cuts at the 99th
   percentile of that feature's PSI and outside share over the training
   windows (never below today's 0.25 and 2 %); per model, "shift" only when
   at least k features exceed their cuts, k the smallest count that at most
   5 % of training windows reach. Stored on the card as
   `drift_calibration`; a card without it keeps today's rule, and so does
   the engine (`pythia-ml` reads only M1 and M2 cards). "drift" (more than
   5 % outside the trained range) is reported with its false-alarm rate but
   not changed unless that rate is above 10 %.
3. **Accept the fix** when, on the out-of-sample windows (bins and cuts from
   before 2024), its shift rate is at most 20 % for every model, and it still
   flags a synthetic shift (one input moved by one training standard
   deviation for a whole window) in at least 90 % of windows.

## d. Auto-pick evidence (2 trials)

1. **Descriptive.** Each live book's score under `Evidence::score` with the
   signals' own evidence, against its forward return to 2026-10-19. The
   question is whether the scoring ranked the books that then did worst
   first. Thirteen days are not evidence of skill either way; this only
   decides whether a recalibration is even suggested.
2. **The forward penalty, historically.** The auto pick as the engine runs it
   on the three books: the top 3 by score, weights proportional to score,
   re-picked daily, 35 bps on the reallocation. Forward record: each quarter
   from 2024 is a new paper start; a book is "below" when its return since
   the quarter's start, after at least 10 days, is under the 5 % quantile of
   its in-sample (2020-08 to 2023) block bootstrap over the same number of
   days, and its score is then halved (`FORWARD_BELOW_FACTOR` 0.5). Trials:
   with the penalty (today) and without (factor 1.0) = 2.
3. **Change only if** removing (or changing) the penalty passes gates 1 to 3
   and 6 against today's rule; then as an engine setting defaulting to
   today's 0.5, with tests. Otherwise documented, no engine change.

## e. Ensembling (no Sharpe trial, 3 IC tests)

Signals, all on the coin-days M2 scored (whole survivorship-free universe):
M2's out-of-sample score; 28-day momentum; low vol (minus 30-day realised
vol, the factory survivor's signal). Label M2's own: the 7-day forward
return. Daily Spearman IC.

- **Entry.** A signal joins M2 only if its mean daily IC on 2022-01-01 to
  2023-12-31 is positive with a Newey-West t (lag 7) above 2.
- **Ensembles.** The mean of the daily percentile ranks: M2 + momentum, M2 +
  low vol, M2 + both, each only if its members entered. At most 3.
- **Pass** (judged from 2024-01-01): mean daily IC above M2's, the paired
  daily IC difference with a Newey-West t (lag 7) above 2.39 (two-sided 0.05
  over 3 tests), higher in at least 2 of 2024, 2025, 2026, and the bottom
  decile's mean 7-day return relative to the day's mean not less negative
  than M2's (M2's value is the short side).
- **If one passes**, it is wired as a shadow score next to M2 (off by
  default), never as a book.

## What passes, and what happens then

Anything that passes is wired as a shadow signal or a setting, off by
default, with the switch described in `model_review.md`. Nothing reaches the
engine's live behaviour by default.
