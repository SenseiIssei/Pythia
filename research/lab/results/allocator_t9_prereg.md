# T9: the allocator weighted by posterior. Pre-registration

Registered 2026-10-28 and committed before any number on the lab's data was computed (the code is written and tested
on simulated days only; while scoping, one look at the allocator's report of 2026-10-27 and at which inputs exist: the
collector's paper ledger since 2026-10-24 01:43 UTC, no saved replay of A1). Brief T9 of the training plan of
2026-10-28, on the review of 2026-10-27 (`results/review_2026-10-27.md`, section 3: "the A1 allocator draws at random
although every arm runs as paper ... the posteriors ignore that the arms share 1,311 entries, and the deflated p 0.97
in its report reads backwards"), R5's registry (`metrics.trial_pool`) and A1 (`results/pumpfun_adaptive_a1.md`).
Code: `lab/pumpfun_rt/allocator.py` (the daily allocator), `lab/pumpfun_rt/allocator_t9.py` (the study); tests
`tests/test_allocator_t9.py`. Result: `results/allocator_t9.md`. Nothing here may change once a result exists. Paper
only: no paper book, live bot, wallet or engine setting changes; the live bot keeps the owner's strategy.

## What changes in the allocator

- **Weights, not a draw.** Every arm runs as a paper book, so every reward is seen whatever is picked. The paper
  wallet is split by the weights: floor 5 % for each arm not under its drawdown guard, the rest by its posterior
  probability of being best (A1's formula, unchanged). The day's log growth of the split wallet is
  log(sum w exp(reward)), each part trading its arm at 10 % a trade. `choice` (the card's and briefing's "would
  pick") is the arm with the largest weight. Floor, drawdown guard (30 % in 14 days), half-life (7 days), prior and
  reward are A1's.
- **P(best) exact.** By quadrature over each arm's Student t marginal of the mean (normal-inverse-gamma posterior),
  not 10,000 draws: arms with the same posterior get the same P(best) to rounding.
- **Shared entries: counted once, weight 1 over k.** An entry (a mint on a UTC day) held by k arms counts 1 / k in
  each arm's posterior; a day's weight in the posterior is multiplied by the mean of 1 / k over the arm's entries
  that day (1 on a day without one). P_pool0_wait and its lock share all their entries, so each counts half of its
  days. The correlation is not modelled: the posteriors stay independent, which makes P(best) between two correlated
  arms conservative (their difference is less noisy than independence assumes), while the 1 / k weight stops a pair of
  clones from counting their common evidence twice against a third arm.
- **A1's mode stays callable** (`mode="drawn"`: draws, no sharing, one seeded draw) as the comparison.
- **R5's convention.** A1's report printed p = 1 - DSR as "deflated p" ("0.97 for the allocator is better"). It
  prints the DSR from now on (higher is better, pass at 0.95); `results/pumpfun_adaptive_a1.md` is corrected (0.03,
  and the selector table's column, 0.000 on every label).

## The replay

Two recorded histories, each day decided on the days before it only:

1. **replay**: R2's realistic replay of the record to 2026-10-28 00:00 UTC at the live latency
   (`smallwallet.replay`, as A1 ran it, R1's model fitted to the live orders of the 7 days to the cutoff), A1's test
   days (from the first day every arm has its models, `adaptive_a1.alloc_days`), the arms' entries at 0.1 SOL without
   limits. Main history.
2. **paper**: the collector's realistic paper books of the three arms since `realistic_since`, the full UTC days
   before 2026-10-28. Reported next to it.

Policies on the same daily rewards: **weighted** (the new allocator), **drawn** (A1 as it ran, seeded by the day;
its spread over 1,000 other seeds with the same weights shown as well), **equal** (a third each, no guard). The best
single arm in hindsight is shown, not tested.

Bands: 90 % of the sum over 10,000 resamples of the days (seed 9), for each policy's total and for the daily
differences weighted less drawn and weighted less equal. DSR of each difference series in R5's convention, over the
registry's pool of all with this study's trials and over the study's 4 comparisons.

**Verdict** (weighted beats drawn), per history: at least 10 days (A1's rule), DSR over the pool of all 0.95 or more
and the band of the difference above 0. With the days the record holds (about 6 in the replay, 3 on paper) the
answer is no by the day count whatever the numbers; they are reported as they are. The daily allocator switches to
weights anyway: with every arm paper and every reward seen, a draw only adds noise to the paper wallet, and the
decision does not touch any book or the live bot.

## Trials

4 comparisons (weighted against drawn and against equal, in each history), registered in R5's registry before any
number (`hand:t9:<history>:weighted_vs_<policy>`, family hand, counted only: no Sharpe pooled, pump.fun's daily log
growth is not a book's return).
