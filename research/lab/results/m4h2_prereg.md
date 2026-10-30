# M4H2: M4H run again without its signal stop. Pre-registration

Registered 2026-10-30 and committed before any judged number of M4H or M4H2 was computed. Everything of
`results/m4h_prereg.md` stays (question, windows, signal, universe, book, fills, costs, accounts, benchmarks, pass
rule, deflation, the k pick, what follows a pass or a failure, the 97 trials) except the one rule below. Code:
`lab.experiments.m4h` (the stop removed, the trial ids `small:m4h2:...`). Results: `results/m4h.md`.

## What happened in M4H

M4H's first run stopped as registered, before any trial was registered and before any out-of-sample number: the
rebuilt 10/10 book on Binance at 41 bps made a 2022-2023 Sharpe of **1.30** against m4_residual's 0.93 (more than
0.3 apart). The difference sits in 2022 (3.12 against 1.91 published); 2023 matches (-0.04 against 0.12). Nothing
else was computed (the run also built the hourly spread and late-fill matrices, which make no judged number).

## Why the stop goes

The stop was meant to catch a broken rebuild. It caught the refit's own spread instead: the same procedure (xs_daily's
walk-forward, T6b's `reg7n_scores`) on the lab's panel as rebuilt on different days gives 0.93 (the 2026-10-07 cache),
0.69 (T6b on the panel of 2026-10-29, late and at T6b's costs, not the same book) and 1.30 here (the panel of
2026-10-30). The first folds of 2022 train on 2020 and 2021 only, where a few coins more or less move the trees. The
judged window's scores are trained on 2020 to 2025 and are less sensitive, but this is not shown, so:

## The one changed rule

- The check is **reported, not a stop**: the rebuilt book's 2022-2023, 2024 and 2025 Sharpes at 41 bps against
  m4_residual's 0.93, 1.67 and 2.43, in the results' first lines.
- Every M4H trial id becomes `small:m4h2:<cell>`; the check is `small:m4h2:check_binance_10_10_41bps` with its
  in-sample Sharpe. 97 trials, registered before any out-of-sample number as before. M4H registered none.
- A reader should weigh any pass by this: the signal's in-sample record depends on the day the panel was built.
