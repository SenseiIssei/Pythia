# Blend and turnover study (pre-registration)

Written 2026-10-11 before any code of this study ran. The results section is
added below this one when the study has run; nothing in this section is
changed afterwards.

Subject: the two sweep candidates that run as paper books, and whether
combining them, or trading them less often, makes a book that clears the
lab's bar after costs.

- **A, `breakout_top10`**: Donchian 20/10 on the 10 most liquid coins of each
  day, no regime filter (`fam_breakout.breakout_weights`). Sweep: out-of-sample
  Sharpe 1.20 at 15 bps, 1.08 at 41 bps, drawdown 22 %, 9x turnover a year.
- **B, `tsmom_top20`**: 28-day time-series momentum on the 20 most liquid coins
  of each day, BTC 200-day regime filter, unscaled
  (`fam_volmom.base_weights(P, 20, regime=True)`). Sweep: 0.54 at 15 bps, 0.32
  at 41 bps, drawdown 24 %, 13x turnover.
- **C, the low-turnover sleeve**: Donchian 55/27 on BTC and ETH with the regime
  filter, the sweep's in-sample pick of that sub-family. Sweep: 1.07 at 15 bps,
  1.03 at 41 bps, drawdown 28 %, 4x turnover.

None of the three is re-tuned here.

## Protocol

- Same survivorship-free daily panel as the sweep and the breakout study (a
  copy of the sweep's cached panel: every USDT pair Binance ever listed, 591
  segments, delisted coins included, ending 2026-10-06), same simulator rules
  (`fam_common.simulate`), same split: in sample 2020-08 to 2023, out of sample
  from 2024-01-01.
- Costs per unit of one-way turnover, charged the next day: 15 bps (Binance
  taker plus half-spread), 41 bps (Kraken taker plus half-spread) and 80 bps
  (stress, roughly a Kraken taker round trip on every unit).
- Every variant that produces its own return series is counted in the
  deflation, together with the sweep's 100 trials and the breakout study's 54.
- Picks are made on in-sample numbers only. Out-of-sample numbers never select.

## Part 1: the blend

Sleeves are sub-accounts: each sleeve runs exactly as its own book, the blend
decides how much of the book's equity each sleeve gets. Between re-sets the
allocations drift with the sleeves' returns (no free daily rebalancing between
sleeves). Every change of a sleeve's allocation is charged as |change| times
the sleeve's exposure at that close. Positions of different sleeves in the same
coin are not netted (netting could only save costs).

Grid, 12 variants:

- sleeves: A + B, or A + B + C
- weighting, re-set every 30 days: equal capital, or inverse volatility
  (1 / root mean square of each sleeve's daily return over the last 90 days,
  as in `fam_ensemble`)
- book vol target, re-set every 7 days: none, 15 % or 25 % a year. Scale =
  target / annualised volatility of the unscaled blend over the last 60 days,
  capped at 3x and so that the book's gross exposure is at most 100 % (no
  leverage). The exposure cap is also enforced on every close in between.

The pick is the variant with the best in-sample Sharpe at 15 bps. "The blend
beats a leg" means a higher out-of-sample Sharpe at 41 bps; "clearly beats"
means the 90 % stationary-bootstrap interval of the Sharpe difference (paired
resamples, mean block 20 days, 10,000 draws) lies above 0.

## Part 2: turnover

- B: rebalance daily or weekly (every 7th day, nothing traded in between,
  regime exits included) times a no-trade band of 0, 20 %, 50 % or "entries and
  exits only". Band rule: on a rebalance day a held coin whose target is not
  zero is resized only when |target - current| > band x target; entries and
  exits always trade. 8 configurations, 7 new.
- A: the breakout signal checked daily (the base), every 3 days or weekly. On a
  check day the rule is the same (close above the previous 20-day high enters,
  close below the previous 10-day low exits); in between nothing is entered or
  exited. 3 configurations, 2 new.

Per family, the pick is the configuration with the best in-sample Sharpe at
41 bps (the cost the engine faces on Kraken). A change from the base is
recommended only if it is that pick AND beats the base out of sample at 41 bps.

## Part 3: one combined trial

If part 2 picks a configuration other than the base for A or B, the part 1
pick's blend configuration is run once more with the part 2 picks as sleeves.
One trial, counted.

## What passes

A variant is proposed as a paper book only if it is an in-sample pick and:

1. deflated p > 0.95 with the sweep's rule over the full pool (100 + 54 + every
   trial of this study), as in `families.py`;
2. out-of-sample Sharpe at 41 bps > 0 and drawdown at 41 bps below the
   equal-weight universe's;
3. Sharpe at 41 bps positive in at least 4 of the 6 calendar years 2021 to
   2026;
4. no single year carries it: dropping any one calendar year from 2020-08 on
   leaves the Sharpe at 41 bps at more than half of the full-period figure.

Also reported, not part of the rule: deflation with an effective number of
trials from the correlation of the trials' returns, the pure-noise bar, and
the bootstrap interval of the pick's own Sharpe.

If nothing passes, no paper book is added and this file records the negative
result.

<!-- generated below by lab.experiments.blend_study; edit above this line only -->
