# Breakout robustness study (pre-registration)

Written 2026-10-08 before any code of this study ran. The results section is
added below this one when the study has run; nothing in this section is
changed afterwards.

Subject: the sweep's Donchian breakout, 20/10 on the 10 most liquid coins of
each day, long-only, no regime filter, each entry sized to 40 % annual vol over
10 slots (`fam_breakout.breakout_weights`). Sweep result: out-of-sample Sharpe
1.20 at 15 bps, 1.08 at 41 bps, drawdown 22 %, deflated p 0.01 over 100
variants. The aim is to find out whether the edge is robust, not to tune it.

## Protocol

- Same survivorship-free daily panel as the sweep (a copy of its cached panel,
  591 segments, ending 2026-10-06), same simulator (`fam_common.simulate`),
  same split: in sample 2020-08 to 2023, out of sample from 2024-01-01.
- Every variant that produces its own return series is counted, also the ones
  that can only make the result worse (execution and cost stress tests).
- Costs per unit of one-way turnover, charged the next day as in the sweep.

## Questions and what will count as an answer

1. **Parameter neighbourhood.** Entry N in {10, 15, 20, 30, 40, 55}, exit N/2
   and N/3 (integer division), universe top 5 / 10 / 20 / 30 (slots = universe
   size): 48 configurations. Report the share positive at 41 bps and heat maps
   of the in-sample Sharpe (15 bps) and the out-of-sample Sharpe (41 bps).
   *Plateau* if the base's neighbours (one step in N, the other exit ratio,
   one step in universe size) have a median out-of-sample Sharpe at 41 bps of
   at least 0.75 times the base's and none is negative; otherwise *peak*.
   Also: which configuration the grid would pick in sample, and how that pick
   does out of sample.
2. **Stability over time.** Rolling 365-day Sharpe, Sharpe per calendar year
   2021 to 2026 (2021 to 2023 are in sample), and the BTC 200-day regime split.
   A year *carries* the result if dropping it halves the out-of-sample Sharpe.
3. **Dependence on a few trades.** Sharpe and CAGR with the best 1 % and 5 % of
   out-of-sample days removed, next to BTC buy-and-hold treated the same way
   (any trend book loses most of its Sharpe this way; the question is whether
   it loses more than the market). Share of out-of-sample P&L from the 10 best
   trades; P&L per coin and the Sharpe without each of the largest coins.
   *One-coin book* if a single coin makes more than 40 % of the P&L or its
   removal takes the Sharpe at 41 bps below 0.5.
4. **Costs and execution.** 15, 41 and 80 bps. Fills after the signal close
   from hourly bars: the next day's open, one hour, four hours and twelve hours
   after the close, and a full day late (the next close). Slippage on breakout
   days: spread estimated from hourly highs, lows and closes (Abdi and Ranaldo)
   in the hours around each entry against the coin's ordinary hours, charged on
   the entry turnover above the 5 bps half-spread the 15 bps model already has.
   *Fragile to execution* if any of these at 41 bps falls below half the
   base's Sharpe at 41 bps.
5. **Deflation for the question asked.** Deflated Sharpe over the original
   100-variant pool and over that pool plus every variant of this study, both
   with the sweep's rule (`fam_common.deflate`) and with an effective number of
   independent trials from the correlation of the trials' out-of-sample
   returns. Stationary bootstrap (Politis and Romano, mean block 20 days, also
   5 and 60 as a check, 10,000 draws) of the out-of-sample Sharpe at 15 and
   41 bps: 90 % and 95 % intervals and the share of draws above 0.
   *Robust* if the lower end of the 90 % interval at 41 bps is above 0.
6. **One improvement, tested once.** Volume confirmation: enter only when the
   breakout day's quote volume is at least 1.5 times the mean of the 20 days
   before it. Reasoning: a breakout that new money drives comes with
   participation; a breakout on thin volume is more often a drift through a
   level that reverts and costs a round trip. Base configuration otherwise.
   No other threshold is tried.

Recommendation rule: a different configuration is recommended only if it is
the grid's in-sample pick or sits in the middle of a plateau, AND beats the
base out of sample at 41 bps. Out-of-sample numbers alone never select. The
running paper book and the engine signal are not changed by this study.

## Answers (written after the run, 2026-10-08)

**Verdict: a real family, an unproven number.** Breakouts on the most liquid
coins make money in every corner of the grid and survive late fills and
doubled costs, so the sign of the edge looks robust. The size of it does not:
20/10 top 10 is the second-best of 48 configurations out of sample, the grid's
median is 0.48 at 41 bps, the 90 % bootstrap interval of its own Sharpe
includes zero, 2024 and ten trades carry it, and no deflation passes. Plan for
a forward Sharpe nearer 0.5 than 1.1. Nothing better founded than the base
came out of this study, so no change is recommended; the paper book and the
autopilot signal stay as they are.

1. **Neighbourhood: a plateau by the pre-registered rule, on an out-of-sample
   ridge the in-sample data did not show.** All 48 configurations are positive
   at 41 bps (83 % at 80 bps). The base's five neighbours make 0.52 to 1.11 at
   41 bps, median 0.86 against the 0.81 the rule needs. But the in-sample
   surface is flat (1.07 to 1.46, median 1.23; the base ranks 5th), while out
   of sample N = 20 is the best row in every universe column and top 10 the
   best column in nearly every row. Selection inside this wider grid would not
   have found it: the in-sample pick (30/15 top 5) makes 0.51 at 41 bps, the
   in-sample plateau centre (10/3 top 20) 0.12. The sweep's coarser grid
   happened to land on the ridge.
2. **Time: 2024 carries it, the regime split is stark.** Out-of-sample years
   at 41 bps: 2024 1.82, 2025 0.43, 2026 (to October) 0.51; positive every
   year and ahead of BTC in the two flat years. Without 2024 the
   out-of-sample Sharpe is 0.46, less than half, which is the pre-registered
   "carries" test. Rolling one-year Sharpe out of sample: median 0.93, range
   -1.89 to 2.18, positive in 80 % of windows, 0.19 for the latest year. With
   BTC above its 200-day average 1.67, below it -0.74 (in sample 1.76 and
   0.45). In sample 2022 was -0.86.
3. **Few days, few trades, not one coin.** Zeroing the best 1 % of
   out-of-sample days takes the Sharpe at 41 bps from 1.08 to 0.19 (BTC: 0.78
   to 0.04); the best 5 %, to -2.19 (BTC -2.00). It leans on its best days
   about as much as the market does. 226 trades, 41 % winners; the 10 best
   make 96 % of the gross P&L, the best one (XRP, November to December 2024)
   32 %, and three of the top ten sit in the same 2024 rally. XRP makes 37 % of
   the P&L, under the 40 % one-coin line; without its trades the Sharpe at
   41 bps is 0.76. No other coin moves it below 0.94.
4. **Costs and execution: robust.** 1.20 / 1.08 / 0.90 at 15 / 41 / 80 bps.
   Next open is the close in a 24-hour market (identical); filled 1 h, 4 h and
   12 h after the close 1.07, 1.11 and 0.99 at 41 bps; a full day late 0.82,
   above the 0.54 fragility line. Hourly bars give no sign of wider spreads on
   breakout days (Abdi-Ranaldo half-spread median 4.5 bps at entries against
   9.3 on the same hours before; volume 1.5 times normal); charging the
   pessimistic estimate costs 42 bps a year and 0.02 of Sharpe.
5. **Deflation: fails under every pool that counts trials as the sweep does.**
   54 new variants with their own return series, 154 trials with the sweep.
   Deflated p: 0.01 over the original 100, 0.01 over all 154, 0.02 to 0.03
   with the effective trial count from the mean correlation (75 of 100, 97 of
   154). Lenient ends: 0.24 to 0.33 with the pure-noise variance, 0.47 to 0.68
   if the trials are counted by eigenvalues (5 and 4 effective trials, an
   undercount driven by the market factor). The deflation failure is not the
   fat tails: with skew 0 and kurtosis 3 the p is the same 0.01. It fails
   because the bar, the best of 100 to 154 noise trials, is a Sharpe of about
   2.5. Probabilistic Sharpe against 0 (one trial): 0.98. Stationary bootstrap
   (block 20): 90 % interval -0.04 to 2.26 at 15 bps, -0.14 to 2.15 at 41 bps;
   95 % -0.39 to 2.33 at 41 bps; 93 to 96 % of draws above 0 for blocks 5, 20
   and 60. By the pre-registered rule (lower end of the 90 % interval at 41 bps
   above 0) it is not robust.
6. **Volume confirmation: no improvement, not adopted.** In sample 1.35 (base
   1.40), out of sample 1.20 / 1.10 (base 1.20 / 1.08), drawdown 24 % (22 %),
   turnover 7.2 a year (9.3). It trades less for the same result, and
   breakout days already run at a median 1.5 times normal volume, so the
   filter mostly removes trades at random.

Failures written down: the in-sample pick and the in-sample plateau centre of
the wider grid both lose most of the base's out-of-sample Sharpe (0.51 and
0.12 at 41 bps); the volume filter adds nothing; 2025 to 2026 are weak
(0.43, 0.51) and the latest rolling year is 0.19.

<!-- generated below by lab.experiments.breakout_study; edit above this line only -->

## Results (generated)

Panel: the sweep's cached panel, 591 segments, to 2026-10-06; out of sample from 2024-01-01 (1010 days). The base reproduces the sweep exactly (asserted).

### 1. Parameter neighbourhood

Cells: exit N/2 / exit N/3. Bold: the base (20/10, top 10).

In-sample Sharpe at 15 bps (2020-08 to 2023):

| entry N | top 5 | top 10 | top 20 | top 30 |
|---|---|---|---|---|
| 10 | 0.89 / 1.16 | 1.19 / 1.45 | 1.12 / 1.44 | 1.15 / 1.45 |
| 15 | 1.09 / 1.08 | 1.25 / 1.29 | 1.13 / 1.15 | 1.18 / 1.18 |
| 20 | 1.35 / 1.22 | **1.40** / 1.29 | 1.30 / 1.10 | 1.21 / 1.07 |
| 30 | 1.46 / 1.37 | 1.33 / 1.37 | 1.28 / 1.35 | 1.15 / 1.23 |
| 40 | 1.38 / 1.35 | 1.34 / 1.32 | 1.27 / 1.29 | 1.19 / 1.23 |
| 55 | 1.20 / 1.29 | 1.09 / 1.20 | 1.13 / 1.27 | 1.09 / 1.17 |

Out-of-sample Sharpe at 41 bps (2024-01 on):

| entry N | top 5 | top 10 | top 20 | top 30 |
|---|---|---|---|---|
| 10 | 0.51 / 0.44 | 0.73 / 0.67 | 0.18 / 0.12 | 0.06 / 0.03 |
| 15 | 0.55 / 0.62 | 0.86 / 0.89 | 0.25 / 0.39 | 0.18 / 0.28 |
| 20 | 0.93 / 1.00 | **1.08** / 1.11 | 0.52 / 0.53 | 0.47 / 0.46 |
| 30 | 0.51 / 0.74 | 0.78 / 1.00 | 0.32 / 0.46 | 0.36 / 0.48 |
| 40 | 0.28 / 0.63 | 0.58 / 0.82 | 0.19 / 0.39 | 0.23 / 0.40 |
| 55 | 0.55 / 0.41 | 0.56 / 0.57 | 0.23 / 0.22 | 0.18 / 0.24 |

Out-of-sample Sharpe at 15 bps:

| entry N | top 5 | top 10 | top 20 | top 30 |
|---|---|---|---|---|
| 10 | 0.77 / 0.80 | 0.98 / 1.04 | 0.42 / 0.47 | 0.30 / 0.40 |
| 15 | 0.74 / 0.86 | 1.04 / 1.11 | 0.43 / 0.60 | 0.35 / 0.49 |
| 20 | 1.05 / 1.17 | **1.20** / 1.29 | 0.64 / 0.70 | 0.58 / 0.63 |
| 30 | 0.60 / 0.86 | 0.86 / 1.10 | 0.39 / 0.56 | 0.43 / 0.59 |
| 40 | 0.35 / 0.72 | 0.65 / 0.90 | 0.25 / 0.47 | 0.29 / 0.47 |
| 55 | 0.59 / 0.47 | 0.61 / 0.63 | 0.27 / 0.28 | 0.22 / 0.30 |

Share of the 48 configurations positive out of sample: 100 % at 41 bps, 83 % at 80 bps. Grid median: in sample 1.23, out of sample 0.60 / 0.48 at 15 / 41 bps. The base ranks 5 of 48 in sample and 2 of 48 out of sample at 41 bps. Base neighbours (Donchian 15/7 · top 10, Donchian 30/15 · top 10, Donchian 20/6 · top 10, Donchian 20/10 · top 5, Donchian 20/10 · top 20) at 41 bps: 0.86, 0.78, 1.11, 0.93, 0.52; median 0.86 against the base's 1.08 (rule: at least 0.81, none negative): **plateau**.

The grid's in-sample pick: Donchian 30/15 · top 5 (in sample 1.46), out of sample 0.60 / 0.51 at 15 / 41 bps. The in-sample plateau centre (best median in-sample Sharpe of itself and its neighbours, 1.44): Donchian 10/3 · top 20, out of sample 0.47 / 0.12.

<details><summary>All 48 configurations</summary>

| entry | exit | top | is_15bps | oos_15bps | oos_41bps | oos_80bps | cagr_41bps | dd_41bps | turnover_yr | expo | nbhd_is_median | nbhd_oos41_median | in_sweep |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 10 | 5 | 5 | 0.89 | 0.77 | 0.51 | 0.11 | 0.08 | 0.30 | 20.09 | 0.24 | 1.13 | 0.53 | no |
| 10 | 5 | 10 | 1.19 | 0.98 | 0.73 | 0.36 | 0.13 | 0.27 | 17.77 | 0.22 | 1.19 | 0.67 | no |
| 10 | 5 | 20 | 1.12 | 0.42 | 0.18 | -0.17 | 0.02 | 0.33 | 15.15 | 0.18 | 1.15 | 0.18 | no |
| 10 | 5 | 30 | 1.15 | 0.30 | 0.06 | -0.31 | -0.00 | 0.37 | 14.48 | 0.17 | 1.16 | 0.12 | no |
| 15 | 7 | 5 | 1.09 | 0.74 | 0.55 | 0.26 | 0.09 | 0.29 | 14.43 | 0.24 | 1.09 | 0.62 | no |
| 15 | 7 | 10 | 1.25 | 1.04 | 0.86 | 0.59 | 0.16 | 0.26 | 12.97 | 0.22 | 1.22 | 0.79 | no |
| 15 | 7 | 20 | 1.13 | 0.43 | 0.25 | -0.00 | 0.03 | 0.30 | 10.91 | 0.17 | 1.17 | 0.32 | no |
| 15 | 7 | 30 | 1.18 | 0.35 | 0.18 | -0.08 | 0.02 | 0.31 | 10.20 | 0.16 | 1.18 | 0.25 | no |
| 20 | 10 | 5 | 1.35 | 1.05 | 0.93 | 0.75 | 0.19 | 0.27 | 10.12 | 0.25 | 1.35 | 0.93 | no |
| 20 | 10 | 10 | 1.40 | 1.20 | 1.08 | 0.90 | 0.22 | 0.22 | 9.27 | 0.24 | 1.31 | 0.90 | yes |
| 20 | 10 | 20 | 1.30 | 0.64 | 0.52 | 0.35 | 0.08 | 0.24 | 8.11 | 0.20 | 1.24 | 0.49 | no |
| 20 | 10 | 30 | 1.21 | 0.58 | 0.47 | 0.29 | 0.07 | 0.26 | 7.49 | 0.18 | 1.18 | 0.46 | no |
| 30 | 15 | 5 | 1.46 | 0.60 | 0.51 | 0.38 | 0.10 | 0.33 | 7.89 | 0.27 | 1.37 | 0.74 | no |
| 30 | 15 | 10 | 1.33 | 0.86 | 0.78 | 0.66 | 0.16 | 0.24 | 6.91 | 0.26 | 1.35 | 0.68 | no |
| 30 | 15 | 20 | 1.28 | 0.39 | 0.32 | 0.20 | 0.04 | 0.28 | 5.75 | 0.20 | 1.29 | 0.41 | no |
| 30 | 15 | 30 | 1.15 | 0.43 | 0.36 | 0.25 | 0.05 | 0.29 | 5.20 | 0.18 | 1.21 | 0.36 | no |
| 40 | 20 | 5 | 1.38 | 0.35 | 0.28 | 0.18 | 0.04 | 0.38 | 6.64 | 0.30 | 1.35 | 0.55 | no |
| 40 | 20 | 10 | 1.34 | 0.65 | 0.58 | 0.49 | 0.11 | 0.28 | 5.58 | 0.27 | 1.32 | 0.57 | no |
| 40 | 20 | 20 | 1.27 | 0.25 | 0.19 | 0.10 | 0.02 | 0.29 | 4.64 | 0.21 | 1.27 | 0.27 | no |
| 40 | 20 | 30 | 1.19 | 0.29 | 0.23 | 0.15 | 0.03 | 0.31 | 4.20 | 0.19 | 1.19 | 0.23 | no |
| 55 | 27 | 5 | 1.20 | 0.59 | 0.55 | 0.49 | 0.12 | 0.34 | 4.69 | 0.31 | 1.25 | 0.48 | no |
| 55 | 27 | 10 | 1.09 | 0.61 | 0.56 | 0.50 | 0.12 | 0.30 | 4.21 | 0.28 | 1.20 | 0.56 | yes |
| 55 | 27 | 20 | 1.13 | 0.27 | 0.23 | 0.17 | 0.03 | 0.33 | 3.53 | 0.23 | 1.13 | 0.22 | no |
| 55 | 27 | 30 | 1.09 | 0.22 | 0.18 | 0.13 | 0.02 | 0.34 | 3.23 | 0.21 | 1.15 | 0.23 | no |
| 10 | 3 | 5 | 1.16 | 0.80 | 0.44 | -0.11 | 0.06 | 0.30 | 24.51 | 0.19 | 1.12 | 0.56 | no |
| 10 | 3 | 10 | 1.45 | 1.04 | 0.67 | 0.12 | 0.09 | 0.24 | 21.39 | 0.17 | 1.29 | 0.67 | no |
| 10 | 3 | 20 | 1.44 | 0.47 | 0.12 | -0.41 | 0.01 | 0.27 | 18.29 | 0.14 | 1.44 | 0.18 | no |
| 10 | 3 | 30 | 1.45 | 0.40 | 0.03 | -0.51 | -0.00 | 0.30 | 17.44 | 0.13 | 1.31 | 0.09 | no |
| 15 | 5 | 5 | 1.08 | 0.86 | 0.62 | 0.27 | 0.10 | 0.25 | 16.55 | 0.20 | 1.16 | 0.62 | no |
| 15 | 5 | 10 | 1.29 | 1.11 | 0.89 | 0.57 | 0.15 | 0.23 | 14.54 | 0.18 | 1.27 | 0.77 | no |
| 15 | 5 | 20 | 1.15 | 0.60 | 0.39 | 0.08 | 0.05 | 0.24 | 12.03 | 0.15 | 1.17 | 0.34 | no |
| 15 | 5 | 30 | 1.18 | 0.49 | 0.28 | -0.04 | 0.03 | 0.28 | 11.34 | 0.14 | 1.18 | 0.28 | no |
| 20 | 6 | 5 | 1.22 | 1.17 | 1.00 | 0.73 | 0.18 | 0.24 | 12.28 | 0.19 | 1.29 | 0.93 | no |
| 20 | 6 | 10 | 1.29 | 1.29 | 1.11 | 0.84 | 0.19 | 0.21 | 11.54 | 0.18 | 1.29 | 1.00 | no |
| 20 | 6 | 20 | 1.10 | 0.70 | 0.53 | 0.27 | 0.07 | 0.22 | 9.71 | 0.14 | 1.22 | 0.49 | no |
| 20 | 6 | 30 | 1.07 | 0.63 | 0.46 | 0.21 | 0.06 | 0.24 | 9.03 | 0.13 | 1.18 | 0.47 | no |
| 30 | 10 | 5 | 1.37 | 0.86 | 0.74 | 0.56 | 0.13 | 0.28 | 9.15 | 0.21 | 1.37 | 0.74 | no |
| 30 | 10 | 10 | 1.37 | 1.10 | 1.00 | 0.83 | 0.19 | 0.21 | 8.03 | 0.21 | 1.34 | 0.80 | no |
| 30 | 10 | 20 | 1.35 | 0.56 | 0.46 | 0.30 | 0.06 | 0.22 | 6.59 | 0.16 | 1.28 | 0.47 | no |
| 30 | 10 | 30 | 1.23 | 0.59 | 0.48 | 0.33 | 0.06 | 0.23 | 5.99 | 0.15 | 1.23 | 0.46 | no |
| 40 | 13 | 5 | 1.35 | 0.72 | 0.63 | 0.49 | 0.12 | 0.30 | 7.31 | 0.23 | 1.35 | 0.63 | no |
| 40 | 13 | 10 | 1.32 | 0.90 | 0.82 | 0.69 | 0.15 | 0.20 | 6.23 | 0.21 | 1.33 | 0.61 | no |
| 40 | 13 | 20 | 1.29 | 0.47 | 0.39 | 0.27 | 0.05 | 0.21 | 5.11 | 0.16 | 1.28 | 0.39 | no |
| 40 | 13 | 30 | 1.23 | 0.47 | 0.40 | 0.29 | 0.05 | 0.23 | 4.67 | 0.15 | 1.23 | 0.39 | no |
| 55 | 18 | 5 | 1.29 | 0.47 | 0.41 | 0.31 | 0.07 | 0.32 | 5.76 | 0.24 | 1.25 | 0.56 | no |
| 55 | 18 | 10 | 1.20 | 0.63 | 0.57 | 0.48 | 0.10 | 0.27 | 5.02 | 0.22 | 1.27 | 0.56 | no |
| 55 | 18 | 20 | 1.27 | 0.28 | 0.22 | 0.14 | 0.02 | 0.27 | 4.05 | 0.17 | 1.20 | 0.24 | no |
| 55 | 18 | 30 | 1.17 | 0.30 | 0.24 | 0.16 | 0.03 | 0.29 | 3.71 | 0.16 | 1.20 | 0.23 | no |

</details>

### 2. Stability over time

| year | sample | days | sharpe_15 | sharpe_41 | ret_41 | dd_41 | expo | btc_sharpe | btc_ret |
|---|---|---|---|---|---|---|---|---|---|
| 2021 | in | 365 | 2.46 | 2.42 | 1.08 | 0.12 | 0.22 | 0.98 | 0.60 |
| 2022 | in | 365 | -0.78 | -0.86 | -0.15 | 0.18 | 0.12 | -1.29 | -0.64 |
| 2023 | in | 365 | 1.81 | 1.70 | 0.48 | 0.20 | 0.31 | 2.35 | 1.56 |
| 2024 | out | 366 | 1.92 | 1.82 | 0.56 | 0.18 | 0.27 | 1.76 | 1.21 |
| 2025 | out | 365 | 0.56 | 0.43 | 0.05 | 0.11 | 0.19 | 0.05 | -0.06 |
| 2026 | out | 279 | 0.67 | 0.51 | 0.06 | 0.16 | 0.27 | 0.16 | -0.02 |

Out-of-sample Sharpe with one year left out:

| without | sharpe_15 | sharpe_41 |
|---|---|---|
| 2024 | 0.61 | 0.46 |
| 2025 | 1.45 | 1.34 |
| 2026 | 1.38 | 1.28 |

Rolling 365-day Sharpe at 41 bps, windows fully out of sample (646): min -1.89, median 0.93, max 2.18, positive in 80 %. Over the whole history from 2021-08 (1894 windows): min -1.89, median 1.04, positive in 85 %.

| end | sharpe_41 | btc |
|---|---|---|
| 2024-12-31 | 1.74 | 1.68 |
| 2025-03-31 | 1.07 | 0.54 |
| 2025-06-30 | 1.45 | 1.33 |
| 2025-09-30 | 1.87 | 1.57 |
| 2025-12-31 | 0.43 | 0.05 |
| 2026-03-31 | 0.30 | -0.21 |
| 2026-06-30 | -0.31 | -1.19 |
| 2026-09-30 | 0.34 | -0.47 |
| 2026-10-06 | 0.19 | -0.62 |

BTC 200-day regime (state at the close the position was set):

| period | state | days | sharpe_15 | sharpe_41 | expo | btc_sharpe |
|---|---|---|---|---|---|---|
| in sample | BTC above 200d | 705 | 1.83 | 1.76 | 0.31 | 1.46 |
| in sample | BTC below 200d | 543 | 0.55 | 0.45 | 0.12 | 0.25 |
| out of sample | BTC above 200d | 609 | 1.78 | 1.67 | 0.30 | 1.07 |
| out of sample | BTC below 200d | 401 | -0.55 | -0.74 | 0.15 | 0.35 |

### 3. Dependence on a few days, trades and coins

Out of sample, the best 1 % / 5 % of days set to zero:

| series | sharpe_drop0 | sharpe_drop1 | sharpe_drop5 | cagr_drop0 | cagr_drop1 | cagr_drop5 |
|---|---|---|---|---|---|---|
| breakout 41 bps | 1.08 | 0.19 | -2.19 | 0.22 | 0.02 | -0.29 |
| breakout 15 bps | 1.20 | 0.32 | -2.04 | 0.25 | 0.04 | -0.27 |
| BTC buy and hold | 0.78 | 0.04 | -2.00 | 0.29 | -0.07 | -0.56 |
| equal-weight universe | -0.34 | -0.93 | -2.63 | -0.41 | -0.60 | -0.85 |

226 trades touch the out-of-sample period; win rate 41 %, median holding 13 days, average win 138 bps of book, average loss -42 bps. The 10 best trades make 96 % of the gross P&L (the best one 32 %); without them the sum of the rest is 3.1 % of book against 71.8 %.

| coin | entry | exit | days | pnl | coin_ret |
|---|---|---|---|---|---|
| XRPUSDT | 2024-11-07 | 2024-12-21 | 44 | 0.23 | 3.03 |
| ZECUSDT | 2026-08-17 | 2026-09-29 | 43 | 0.10 | 1.76 |
| DOGEUSDT | 2024-10-17 | 2024-12-10 | 54 | 0.10 | 2.04 |
| BNBUSDT | 2024-02-08 | 2024-04-02 | 54 | 0.06 | 0.73 |
| BTCUSDT | 2024-10-14 | 2024-12-21 | 68 | 0.04 | 0.47 |
| BTCUSDT | 2024-02-07 | 2024-03-16 | 38 | 0.04 | 0.47 |
| ETHUSDT | 2024-02-09 | 2024-03-16 | 36 | 0.04 | 0.42 |
| SOLUSDT | 2026-08-18 | 2026-09-10 | 23 | 0.03 | 0.28 |
| XRPUSDT | 2025-07-03 | 2025-07-28 | 25 | 0.03 | 0.38 |
| PEPEUSDT | 2024-11-07 | 2024-11-26 | 19 | 0.02 | 0.66 |

P&L per coin (37 coins held out of sample; largest twelve by size; Sharpe at 41 bps with that coin's trades left in cash):

| coin | pnl_share | pnl | days_held | sharpe_41_without |
|---|---|---|---|---|
| XRPUSDT | 0.37 | 0.26 | 270 | 0.76 |
| ZECUSDT | 0.15 | 0.11 | 146 | 0.94 |
| DOGEUSDT | 0.14 | 0.10 | 262 | 1.03 |
| BTCUSDT | 0.12 | 0.08 | 403 | 1.04 |
| SOLUSDT | 0.10 | 0.07 | 354 | 1.04 |
| PEPEUSDT | 0.06 | 0.05 | 219 | 1.06 |
| BNBUSDT | 0.06 | 0.04 | 445 | 1.13 |
| SUIUSDT | 0.05 | 0.04 | 232 | 1.05 |
| TRXUSDT | 0.05 | 0.03 | 215 | 1.05 |
| ADAUSDT | -0.04 | -0.03 | 110 | 1.15 |
| ETHUSDT | 0.03 | 0.02 | 368 | 1.15 |
| 1000SATSUSDT | -0.02 | -0.01 | 32 | 1.11 |

### 4. Costs and execution

| case | oos_15bps | oos_41bps | oos_80bps | cagr_41bps | dd_41bps | turnover_yr |
|---|---|---|---|---|---|---|
| close (the sweep) | 1.20 | 1.08 | 0.90 | 0.22 | 0.22 | 9.27 |
| fill at next open | 1.20 | 1.08 | 0.90 | 0.22 | 0.22 | 9.27 |
| fill at close + 1h | 1.18 | 1.07 | 0.89 | 0.22 | 0.22 | 9.27 |
| fill at close + 4h | 1.23 | 1.11 | 0.94 | 0.23 | 0.22 | 9.27 |
| fill at close + 12h | 1.10 | 0.99 | 0.81 | 0.20 | 0.24 | 9.26 |
| fill a day late (next close) | 0.94 | 0.82 | 0.65 | 0.16 | 0.24 | 9.26 |
| close + breakout-day spread | 1.18 | 1.06 | 0.88 | 0.22 | 0.22 | 9.27 |

Move from the decision close to the fill on out-of-sample entries (positive: the fill is dearer):

| fill | mean_bps | median_bps |
|---|---|---|
| next open | 0.01 | 0.00 |
| close + 1h | 4.17 | -7.20 |
| close + 4h | 19.26 | -20.07 |
| close + 12h | 43.04 | 1.05 |

Breakout-day spread: 221 out-of-sample entries. Abdi-Ranaldo half-spread over the six hourly bars around the entry close: median 4.5 bps (mean 14.1), against median 9.3 (mean 11.0) bps for the same coin and hours over the 30 days before, a ratio of means of 1.28; exits 5.1 bps (not charged). Breakout-day volume is a median 1.51 times the 20 days before. Charging every entry the estimate above the model's 5 bps costs 42 bps a year. The estimator reads hourly ranges, so it is far above the quoted spreads `costs` measures (one tick to 2 bps); that makes this line a pessimistic bound.

### 5. Deflation and bootstrap

Variants of this study with their own return series: **54** (46 new grid cells; the other 2 of the 48 were already sweep trials; 7 execution and cost cases, 1 improvement). With the sweep: 154 trials. Effective independent trials from the correlation of their daily out-of-sample returns: mean correlation 0.25 gives 75 of 100 (0.37, 97 of 154); the eigenvalue participation ratio gives 5.2 and 3.5, pulled down by the common market factor, so it is the lenient end.

| pool | trials | sr0_annual | p | p_normal | p_null |
|---|---|---|---|---|---|
| sweep 100, sweep rule | 100 | 2.58 | 0.01 | 0.01 | 0.29 |
| sweep 100 + study 54, sweep rule | 154 | 2.52 | 0.01 | 0.01 | 0.24 |
| sweep 100, effective trials (mean correlation) | 74.92 | 2.48 | 0.02 | 0.02 | 0.33 |
| sweep 100 + study, effective trials (mean correlation) | 97.28 | 2.37 | 0.02 | 0.03 | 0.30 |
| sweep 100, effective trials (eigenvalues) | 5.23 | 1.24 | 0.47 | 0.47 | 0.78 |
| sweep 100 + study, effective trials (eigenvalues) | 3.55 | 0.91 | 0.68 | 0.68 | 0.85 |
| breakout family 12 + study, sweep rule | 66 | 0.73 | 0.79 | 0.78 | 0.35 |
| one trial (probabilistic Sharpe vs 0) | 1 | 0.00 | 0.98 | 0.98 | 0.98 |

p: the sweep's rule (winsorised variance of the trials' Sharpes, own skew and kurtosis). p_normal: the same with skew 0 and kurtosis 3. p_null: the variance a pure-noise trial would have (1/T). sr0: the annual Sharpe the best of that many noise trials would show.

Stationary bootstrap of the out-of-sample Sharpe (10,000 draws):

| block | cost | sharpe | p2_5 | p05 | p95 | p97_5 | share_above_0 |
|---|---|---|---|---|---|---|---|
| 5 | 15bps | 1.20 | -0.10 | 0.10 | 2.25 | 2.45 | 0.96 |
| 5 | 41bps | 1.08 | -0.24 | -0.04 | 2.13 | 2.32 | 0.94 |
| 20 | 15bps | 1.20 | -0.27 | -0.04 | 2.26 | 2.46 | 0.95 |
| 20 | 41bps | 1.08 | -0.39 | -0.14 | 2.15 | 2.33 | 0.93 |
| 60 | 15bps | 1.20 | -0.28 | 0.00 | 2.15 | 2.31 | 0.95 |
| 60 | 41bps | 1.08 | -0.39 | -0.14 | 2.04 | 2.21 | 0.93 |

### 6. Volume confirmation (pre-registered, tested once)

Entries only on at least 1.5x the 20-day mean quote volume: in sample 1.35, out of sample 1.20 / 1.10 at 15 / 41 bps, drawdown 24 %, turnover 7.2, exposure 0.19 (base: 1.40, 1.20 / 1.08, 22 %, 9.3, 0.24).

Every counted study variant: Donchian 10/5 · top 5; Donchian 10/5 · top 10; Donchian 10/5 · top 20; Donchian 10/5 · top 30; Donchian 10/3 · top 5; Donchian 10/3 · top 10; Donchian 10/3 · top 20; Donchian 10/3 · top 30; Donchian 15/7 · top 5; Donchian 15/7 · top 10; Donchian 15/7 · top 20; Donchian 15/7 · top 30; Donchian 15/5 · top 5; Donchian 15/5 · top 10; Donchian 15/5 · top 20; Donchian 15/5 · top 30; Donchian 20/10 · top 5; Donchian 20/10 · top 20; Donchian 20/10 · top 30; Donchian 20/6 · top 5; Donchian 20/6 · top 10; Donchian 20/6 · top 20; Donchian 20/6 · top 30; Donchian 30/15 · top 5; Donchian 30/15 · top 10; Donchian 30/15 · top 20; Donchian 30/15 · top 30; Donchian 30/10 · top 5; Donchian 30/10 · top 10; Donchian 30/10 · top 20; Donchian 30/10 · top 30; Donchian 40/20 · top 5; Donchian 40/20 · top 10; Donchian 40/20 · top 20; Donchian 40/20 · top 30; Donchian 40/13 · top 5; Donchian 40/13 · top 10; Donchian 40/13 · top 20; Donchian 40/13 · top 30; Donchian 55/27 · top 5; Donchian 55/27 · top 20; Donchian 55/27 · top 30; Donchian 55/18 · top 5; Donchian 55/18 · top 10; Donchian 55/18 · top 20; Donchian 55/18 · top 30; base · fill at next open; base · fill at close + 1h; base · fill at close + 4h; base · fill at close + 12h; base · a day late; base · 80 bps; base · breakout-day spread; base · volume confirmed 1.5x 20d.
