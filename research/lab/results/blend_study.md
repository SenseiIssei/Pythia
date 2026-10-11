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

## Answers (written after the run, 2026-10-11)

**Verdict: nothing passes, no paper book is added.** Blending does not beat
the breakout book on its own, and trading momentum weekly instead of daily
helps at Kraken costs, but by less than the in-sample pick shows.

1. **The blend loses to its best leg.** None of the 12 blends has a higher
   out-of-sample Sharpe at 41 bps than both A and B. The in-sample pick (A + B,
   equal capital, 15 % vol target) makes 0.78 / 0.57 / 0.24 at 15 / 41 / 80 bps
   against A's 1.20 / 1.08 / 0.90, and the paired bootstrap puts it below A in
   94 % of draws at 41 bps. The legs are 0.78 correlated out of sample (both are
   long-only trend books on the same liquid coins), so adding B mostly adds B's
   weaker Sharpe and B's costs. The vol target makes every pairing worse: it
   scales the book up in calm stretches, which adds 4 to 12 units of turnover a
   year, and calm stretches are not where trend books earn. Adding C helps
   (the best blend out of sample, A + B + C at equal capital without a target,
   makes 0.98 at 41 bps), but it ranked fourth in sample and still sits below A.
2. **Momentum: weekly is cheaper, and the pick's number is weekday luck.**
   Weekly rebalancing cuts B's turnover from 12.9 to about 5 a year and its
   cost at 41 bps from 5.3 % to 2.0 % of equity a year. The pick (weekly, 50 %
   band) makes 0.83 / 0.75 / 0.64 against the daily base's 0.54 / 0.32 / 0.00.
   The robustness check added after the pre-registration shows that most of the
   step from 0.32 to 0.75 is the choice of weekday: the same rule trading on the
   other six weekdays makes 0.36 to 0.61 at 41 bps (median of all seven 0.43),
   and the weekday-free version (seven tranches, one per weekday, 1/7 of the
   capital each) makes 0.59 / 0.51 / 0.39 with a 24 % drawdown. Every weekday
   beats the daily base at 41 and 80 bps; at 15 bps they straddle it. The real
   gain is about 0.1 to 0.2 of Sharpe at Kraken costs, from paying less, not
   from a better signal. Bands on a daily book do less (0.37 and 0.40 at 20 %
   and 50 %); "entries and exits only" reaches 0.53 by letting winners grow,
   with a higher drawdown (28 %).
3. **Breakout needs daily checks.** Checking the signal every 3 days makes 0.67
   at 41 bps, weekly 0.43, against 1.08 daily, and in sample both are worse too
   (1.34 and 1.00 against 1.40 at 15 bps). A breakout's return comes in the first days
   after the level breaks; a late entry pays for the move without catching it.
4. **Combined trial.** The blend pick rebuilt with weekly B makes 0.93 / 0.77 /
   0.54, better than the daily blend, still below A alone.
5. **Deflation.** Over 183 trials (100 sweep, 54 breakout study, 29 here) the
   best noise trial is expected at an annual Sharpe of about 2.45. Deflated p:
   A 0.02, C 0.01, every blend and every B variant 0.00. Even with the most
   lenient trial count (3.2 effective trials by eigenvalues) the p values are
   0.75 for A, 0.52 for the weekly pick, 0.36 for the weekday-free weekly book
   and 0.49 for the blend pick. Every 90 % bootstrap interval of the Sharpe at
   41 bps includes 0 (A -0.15 to 2.16, the weekday-free weekly book -0.59 to
   1.51).
6. **Years.** Every candidate is positive in at least 5 of the 6 years 2021 to
   2026 and no single year carries any of them. 2022, the bear year, is the
   loss year for everything that holds coins then (A -0.86, the blends about
   -0.3 at 41 bps); B sits it out in cash under the regime filter.

What follows for the paper books (not done by this study; the running books are
not changed, since that would break their forward record):

- Do not blend A and B. If one book gets capital, `breakout_top10` with daily
  checks remains the best founded; plan for a forward Sharpe near 0.5.
- If `tsmom_top20` keeps running, a weekly rebalance in seven daily tranches
  is the version to move to: expect about 0.5 at 41 bps instead of 0.3, from
  lower costs. Do not adopt the single-weekday pick on the strength of its
  0.75.

<!-- generated below by lab.experiments.blend_study; edit above this line only -->

## Results (generated)

Panel: 591 coin segments, ending 2026-10-06. In sample 2020-08 to 2023, out of sample from 2024-01-01 (1010 days). Sharpe annualised, net of the cost named; cagr, dd (max drawdown) and the cost drag at 41 bps (cost_41_pct_yr, % of equity a year) out of sample.

### Legs (reproduce the sweep)

| variant | is_15bps | oos_15bps | oos_41bps | oos_80bps | cagr_41bps | dd_41bps | vol | turnover_yr | cost_41_pct_yr | expo |
|---|---|---|---|---|---|---|---|---|---|---|
| A breakout_top10 (Donchian 20/10 · top 10) | 1.40 | 1.20 | 1.08 | 0.90 | 0.22 | 0.22 | 0.21 | 9.27 | 3.80 | 0.24 |
| B tsmom_top20 (28d · top 20 · regime) | 1.44 | 0.54 | 0.32 | -0.00 | 0.04 | 0.24 | 0.15 | 12.87 | 5.28 | 0.17 |
| C Donchian 55/27 · BTC+ETH · regime | 1.37 | 1.07 | 1.03 | 0.98 | 0.27 | 0.28 | 0.27 | 3.89 | 1.60 | 0.30 |

Correlation of the legs' out-of-sample daily returns at 15 bps: A-B 0.78, A-C 0.64, B-C 0.74.

### Part 1: blends

| variant | is_15bps | oos_15bps | oos_41bps | oos_80bps | cagr_41bps | dd_41bps | vol | turnover_yr | cost_41_pct_yr | expo |
|---|---|---|---|---|---|---|---|---|---|---|
| A + B · equal capital · vol target 15 % | 1.57 | 0.78 | 0.57 | 0.24 | 0.09 | 0.23 | 0.19 | 15.46 | 6.34 | 0.24 |
| A + B + C · inverse vol · vol target 15 % | 1.56 | 0.87 | 0.66 | 0.33 | 0.11 | 0.24 | 0.19 | 15.56 | 6.38 | 0.26 |
| A + B · inverse vol · vol target 15 % | 1.54 | 0.80 | 0.58 | 0.24 | 0.10 | 0.25 | 0.19 | 16.86 | 6.91 | 0.25 |
| A + B + C · equal capital · no vol target | 1.52 | 1.09 | 0.98 | 0.80 | 0.18 | 0.23 | 0.19 | 8.72 | 3.58 | 0.24 |
| A + B + C · equal capital · vol target 15 % | 1.50 | 0.85 | 0.66 | 0.38 | 0.10 | 0.24 | 0.17 | 12.74 | 5.22 | 0.23 |
| A + B · equal capital · no vol target | 1.50 | 0.97 | 0.81 | 0.55 | 0.13 | 0.21 | 0.17 | 11.09 | 4.55 | 0.20 |
| A + B + C · inverse vol · no vol target | 1.42 | 1.00 | 0.85 | 0.62 | 0.15 | 0.22 | 0.19 | 10.92 | 4.48 | 0.25 |
| A + B · inverse vol · no vol target | 1.41 | 0.88 | 0.69 | 0.41 | 0.11 | 0.21 | 0.17 | 12.52 | 5.13 | 0.22 |
| A + B · inverse vol · vol target 25 % | 1.38 | 0.85 | 0.62 | 0.26 | 0.14 | 0.33 | 0.26 | 24.26 | 9.95 | 0.36 |
| A + B + C · inverse vol · vol target 25 % | 1.37 | 0.95 | 0.74 | 0.41 | 0.16 | 0.31 | 0.25 | 20.73 | 8.50 | 0.37 |
| A + B · equal capital · vol target 25 % | 1.37 | 0.80 | 0.58 | 0.26 | 0.12 | 0.33 | 0.26 | 21.35 | 8.75 | 0.33 |
| A + B + C · equal capital · vol target 25 % | 1.35 | 0.94 | 0.76 | 0.49 | 0.16 | 0.32 | 0.23 | 16.40 | 6.73 | 0.32 |

In-sample pick: **A + B · equal capital · vol target 15 %**. Blends with a higher out-of-sample Sharpe at 41 bps than both A and B: 0 of 12.

Pick against each leg, paired stationary bootstrap of the out-of-sample Sharpe difference (pick minus leg, mean block 20 days, 10,000 draws):

| leg | cost | diff | p05 | p95 | share_above_0 |
|---|---|---|---|---|---|
| A breakout_top10 (Donchian 20/10 · top 10) | 15bps | -0.41 | -0.92 | 0.10 | 0.09 |
| A breakout_top10 (Donchian 20/10 · top 10) | 41bps | -0.51 | -1.04 | 0.01 | 0.06 |
| B tsmom_top20 (28d · top 20 · regime) | 15bps | 0.24 | -0.36 | 0.77 | 0.75 |
| B tsmom_top20 (28d · top 20 · regime) | 41bps | 0.24 | -0.37 | 0.79 | 0.75 |
| C Donchian 55/27 · BTC+ETH · regime | 15bps | -0.29 | -1.23 | 0.51 | 0.27 |
| C Donchian 55/27 · BTC+ETH · regime | 41bps | -0.47 | -1.42 | 0.35 | 0.17 |

### Part 2: turnover

B, tsmom_top20:

| rebalance | band | is_15bps | oos_15bps | oos_41bps | oos_80bps | cagr_41bps | dd_41bps | vol | turnover_yr | cost_41_pct_yr | expo |
|---|---|---|---|---|---|---|---|---|---|---|---|
| daily | 0 | 1.44 | 0.54 | 0.32 | -0.00 | 0.04 | 0.24 | 0.15 | 12.87 | 5.28 | 0.17 |
| daily | 20 % | 1.47 | 0.57 | 0.37 | 0.08 | 0.05 | 0.24 | 0.15 | 11.55 | 4.74 | 0.17 |
| daily | 50 % | 1.51 | 0.58 | 0.40 | 0.13 | 0.05 | 0.25 | 0.16 | 11.30 | 4.63 | 0.17 |
| daily | entries and exits only | 1.46 | 0.66 | 0.53 | 0.33 | 0.10 | 0.28 | 0.22 | 11.32 | 4.64 | 0.21 |
| weekly | 0 | 1.57 | 0.82 | 0.74 | 0.61 | 0.11 | 0.20 | 0.16 | 5.20 | 2.13 | 0.17 |
| weekly | 20 % | 1.58 | 0.83 | 0.75 | 0.63 | 0.11 | 0.19 | 0.16 | 4.89 | 2.00 | 0.17 |
| weekly | 50 % | 1.60 | 0.83 | 0.75 | 0.64 | 0.12 | 0.19 | 0.17 | 4.70 | 1.93 | 0.17 |
| weekly | entries and exits only | 1.42 | 0.85 | 0.79 | 0.71 | 0.16 | 0.23 | 0.22 | 4.70 | 1.93 | 0.21 |

In-sample pick at 41 bps: **B · weekly · band 50 %**; recommended over the base: yes.

A, breakout_top10:

| check | is_15bps | oos_15bps | oos_41bps | oos_80bps | cagr_41bps | dd_41bps | vol | turnover_yr | cost_41_pct_yr | expo |
|---|---|---|---|---|---|---|---|---|---|---|
| daily | 1.40 | 1.20 | 1.08 | 0.90 | 0.22 | 0.22 | 0.21 | 9.27 | 3.80 | 0.24 |
| every 3 days | 1.34 | 0.76 | 0.67 | 0.54 | 0.11 | 0.21 | 0.19 | 6.47 | 2.65 | 0.24 |
| weekly | 1.00 | 0.47 | 0.43 | 0.36 | 0.07 | 0.27 | 0.22 | 3.60 | 1.47 | 0.31 |

In-sample pick at 41 bps: **A breakout_top10 (Donchian 20/10 · top 10)**; recommended over the base: no.

### Part 3: blend of the turnover picks

| variant | is_15bps | oos_15bps | oos_41bps | oos_80bps | cagr_41bps | dd_41bps | vol | turnover_yr | cost_41_pct_yr | expo |
|---|---|---|---|---|---|---|---|---|---|---|
| A + B · equal capital · vol target 15 % · legs daily / weekly band 50 % | 1.74 | 0.93 | 0.77 | 0.54 | 0.14 | 0.22 | 0.19 | 11.42 | 4.68 | 0.24 |

### Robustness of the weekly pick (added after the pre-registration, counted)

The same rule with the weekly rebalance on each day of the week (the study's weekly grid trades on the panel's first weekday):

| weekday | is_15bps | oos_15bps | oos_41bps | oos_80bps | cagr_41bps | dd_41bps | vol | turnover_yr | cost_41_pct_yr | expo |
|---|---|---|---|---|---|---|---|---|---|---|
| Wednesday | 1.60 | 0.83 | 0.75 | 0.64 | 0.12 | 0.19 | 0.17 | 4.70 | 1.93 | 0.17 |
| Thursday | 1.46 | 0.69 | 0.61 | 0.49 | 0.09 | 0.22 | 0.17 | 5.35 | 2.19 | 0.18 |
| Friday | 1.67 | 0.44 | 0.36 | 0.24 | 0.05 | 0.26 | 0.17 | 5.22 | 2.14 | 0.17 |
| Saturday | 1.51 | 0.45 | 0.37 | 0.26 | 0.05 | 0.26 | 0.17 | 5.01 | 2.05 | 0.17 |
| Sunday | 1.54 | 0.56 | 0.48 | 0.36 | 0.07 | 0.27 | 0.17 | 5.00 | 2.05 | 0.17 |
| Monday | 1.62 | 0.49 | 0.42 | 0.30 | 0.06 | 0.22 | 0.16 | 4.68 | 1.92 | 0.17 |
| Tuesday | 1.46 | 0.51 | 0.43 | 0.31 | 0.06 | 0.22 | 0.16 | 4.96 | 2.03 | 0.17 |
| all seven, 1/7 each | 1.59 | 0.59 | 0.51 | 0.39 | 0.07 | 0.24 | 0.16 | 5.01 | 2.05 | 0.17 |

Median of the seven weekdays at 41 bps: 0.43.

Weekly pick against the daily base, paired bootstrap of the out-of-sample Sharpe difference:

| cost | diff | p05 | p95 | share_above_0 |
|---|---|---|---|---|
| 15bps | 0.29 | 0.01 | 0.59 | 0.96 |
| 41bps | 0.43 | 0.14 | 0.75 | 0.99 |
| 80bps | 0.65 | 0.34 | 1.00 | 1.00 |

### Judged against the pass rule

Pool: 100 sweep + 54 breakout study + 29 this study = **183 trials**. Effective trials from the correlation of their out-of-sample returns (sweep, the breakout grid and this study): 103 by mean correlation, 3.2 by eigenvalues.

| role | variant | oos_15bps | oos_41bps | dd_41bps | sr0 | p_pool | p_eff_corr | p_eff_eigen | p_one_trial | boot41_p05 | boot41_p95 | years_pos | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| blend pick | A + B · equal capital · vol target 15 % | 0.78 | 0.57 | 0.23 | 2.45 | 0.00 | 0.00 | 0.49 | 0.91 | -0.68 | 1.66 | 5 | fails: deflated p 0.00 <= 0.95 |
| A turnover pick | A breakout_top10 (Donchian 20/10 · top 10) | 1.20 | 1.08 | 0.22 | 2.45 | 0.02 | 0.03 | 0.75 | 0.98 | -0.15 | 2.16 | 5 | fails: deflated p 0.02 <= 0.95 |
| B turnover pick | B · weekly · band 50 % | 0.83 | 0.75 | 0.19 | 2.45 | 0.00 | 0.01 | 0.52 | 0.92 | -0.30 | 1.71 | 5 | fails: deflated p 0.00 <= 0.95 |
| part 3 | A + B · equal capital · vol target 15 % · legs daily / weekly band 50 % | 0.93 | 0.77 | 0.22 | 2.45 | 0.00 | 0.01 | 0.59 | 0.95 | -0.47 | 1.84 | 5 | fails: deflated p 0.00 <= 0.95 |
| B weekly, phase-free (check) | B · seven weekly tranches · band 50 % | 0.59 | 0.51 | 0.24 | 2.45 | 0.00 | 0.00 | 0.36 | 0.83 | -0.59 | 1.51 | 6 | fails: deflated p 0.00 <= 0.95 |
| leg A (reference) | A breakout_top10 (Donchian 20/10 · top 10) | 1.20 | 1.08 | 0.22 | 2.45 | 0.02 | 0.03 | 0.75 | 0.98 | -0.15 | 2.16 | 5 | fails: deflated p 0.02 <= 0.95 |
| leg B (reference) | B tsmom_top20 (28d · top 20 · regime) | 0.54 | 0.32 | 0.24 | 2.45 | 0.00 | 0.00 | 0.33 | 0.82 | -0.81 | 1.34 | 4 | fails: deflated p 0.00 <= 0.95 |
| leg C (reference) | C Donchian 55/27 · BTC+ETH · regime | 1.07 | 1.03 | 0.28 | 2.45 | 0.01 | 0.02 | 0.68 | 0.97 | -0.00 | 2.04 | 5 | fails: deflated p 0.01 <= 0.95 |

Sharpe at 41 bps per calendar year (2020 is 2020-08 on; 2021 to 2023 in sample), and the full-period Sharpe with that year dropped:

| variant | full | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 | w/o 2020 | w/o 2021 | w/o 2022 | w/o 2023 | w/o 2024 | w/o 2025 | w/o 2026 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A + B · equal capital · vol target 15 % | 1.05 | 1.55 | 2.62 | -0.32 | 1.78 | 1.00 | 0.28 | 0.35 | 1.01 | 0.77 | 1.29 | 0.89 | 1.07 | 1.19 | 1.16 |
| A breakout_top10 (Donchian 20/10 · top 10) | 1.22 | 1.09 | 2.42 | -0.86 | 1.70 | 1.82 | 0.43 | 0.51 | 1.24 | 0.91 | 1.51 | 1.13 | 1.10 | 1.33 | 1.31 |
| B · weekly · band 50 % | 1.20 | 1.71 | 2.28 | 0.00 | 1.48 | 0.87 | 0.09 | 1.70 | 1.15 | 0.95 | 1.31 | 1.13 | 1.27 | 1.41 | 1.15 |
| A + B · equal capital · vol target 15 % · legs daily / weekly band 50 % | 1.26 | 1.93 | 2.69 | -0.31 | 2.12 | 1.35 | 0.43 | 0.42 | 1.20 | 1.00 | 1.53 | 1.06 | 1.24 | 1.40 | 1.38 |
| B · seven weekly tranches · band 50 % | 1.08 | 1.74 | 2.40 | 0.88 | 1.28 | 0.57 | 0.06 | 1.33 | 1.01 | 0.78 | 1.18 | 1.04 | 1.19 | 1.29 | 1.06 |
| A breakout_top10 (Donchian 20/10 · top 10) | 1.22 | 1.09 | 2.42 | -0.86 | 1.70 | 1.82 | 0.43 | 0.51 | 1.24 | 0.91 | 1.51 | 1.13 | 1.10 | 1.33 | 1.31 |
| B tsmom_top20 (28d · top 20 · regime) | 0.86 | 1.06 | 2.08 | 0.00 | 1.17 | 0.31 | -0.34 | 1.50 | 0.84 | 0.57 | 0.93 | 0.79 | 0.97 | 1.09 | 0.79 |
| C Donchian 55/27 · BTC+ETH · regime | 1.21 | 2.82 | 1.50 | 0.00 | 1.10 | 1.36 | 0.33 | 1.48 | 1.04 | 1.19 | 1.33 | 1.24 | 1.19 | 1.33 | 1.22 |

Return at 41 bps per calendar year:

| variant | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---|---|---|---|---|---|---|
| A + B · equal capital · vol target 15 % | 14 % | 60 % | -7 % | 44 % | 19 % | 3 % | 4 % |
| A breakout_top10 (Donchian 20/10 · top 10) | 14 % | 108 % | -15 % | 48 % | 56 % | 5 % | 6 % |
| B · weekly · band 50 % | 19 % | 54 % | 0 % | 29 % | 16 % | 0 % | 18 % |
| A + B · equal capital · vol target 15 % · legs daily / weekly band 50 % | 20 % | 64 % | -7 % | 59 % | 28 % | 6 % | 5 % |
| B · seven weekly tranches · band 50 % | 18 % | 55 % | 0 % | 24 % | 9 % | -1 % | 12 % |
| A breakout_top10 (Donchian 20/10 · top 10) | 14 % | 108 % | -15 % | 48 % | 56 % | 5 % | 6 % |
| B tsmom_top20 (28d · top 20 · regime) | 9 % | 45 % | 0 % | 21 % | 4 % | -6 % | 14 % |
| C Donchian 55/27 · BTC+ETH · regime | 78 % | 100 % | 0 % | 33 % | 56 % | 4 % | 20 % |

Benchmarks out of sample (no costs): BTC Sharpe 0.78, drawdown 53 %; equal-weight universe Sharpe -0.34, drawdown 91 %.

Trials of this study (29): A + B · equal capital · no vol target; A + B · equal capital · vol target 15 %; A + B · equal capital · vol target 25 %; A + B · inverse vol · no vol target; A + B · inverse vol · vol target 15 %; A + B · inverse vol · vol target 25 %; A + B + C · equal capital · no vol target; A + B + C · equal capital · vol target 15 %; A + B + C · equal capital · vol target 25 %; A + B + C · inverse vol · no vol target; A + B + C · inverse vol · vol target 15 %; A + B + C · inverse vol · vol target 25 %; B · daily · band 20 %; B · daily · band 50 %; B · daily · band entries and exits only; B · weekly · band 0; B · weekly · band 20 %; B · weekly · band 50 %; B · weekly · band entries and exits only; A · signal every 3 days; A · signal weekly; A + B · equal capital · vol target 15 % · legs daily / weekly band 50 %; B · weekly on Thursday · band 50 %; B · weekly on Friday · band 50 %; B · weekly on Saturday · band 50 %; B · weekly on Sunday · band 50 %; B · weekly on Monday · band 50 %; B · weekly on Tuesday · band 50 %; B · seven weekly tranches · band 50 %.
