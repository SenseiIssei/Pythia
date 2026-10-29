# O1: order book depth as a signal

Pre-registered in `results/depth_signal_o1_prereg.md` (committed before the first run). Code:
`lab.experiments.depth_signal_o1`, the features in `lab.features.book` (`bd_imb1`, `bd_depth1_chg`,
`bd_cost100k_bps`, and O1's `bd_imb1_dev30`, `bd_cost100k_dev30`). Paper only: nothing a live bot, a wallet or the
engine reads changed.

**Reading (2026-10-29).** No. None of the six books passes, no paper book follows, the lockbox stays closed. The
imbalance and the daily change of depth carry nothing usable one close late: their ICs are within noise (t +1.60
and -0.86) and the daily books lose 17 to 45 % a year to costs. Depth falling does not announce a bigger move than
the coin's own volatility and today's move say (t -0.76). The one strong number points against its prior: the cost
of 100k ranks the next 7 days' returns with an IC of -0.145 (t -8.2), so across PIT50 the liquid coins beat the
illiquid ones, the opposite of the illiquidity premium declared. That direction was not registered and is not
traded here; it overlaps with the size and liquidity effects of the existing books and would need its own
pre-registration (and its trial) before any book. The time-series cost book (long a coin whose cost rose above its
30 days) clears the Sharpe bar (0.64) but not its t (1.25) nor the DSR (bar 2.79 over 3,103 trials). PBO 0.01 only
says the in-sample order of six mostly losing books held out of sample.

<!-- generated below by lab.experiments.depth_signal_o1; edit above this line only -->

Generated 2026-10-29T03:46:00+00:00. Validation 2024-01-01 to 2026-06-30, in sample 2023-01-01 to 2023-12-31, every series and the depth table cut before 2026-07-01 (the lockbox not read). Universe: T5's PIT50 with T4's delisting table (353 rows), the perp traded and the signal known, at least 20 coins. Late: weights of close t traded at close t+1 on the perps, funding both ways. Costs: the USD-M taker 5 bps plus the cost of a 10k USD market order from T4's hour nearest the fill (T6b's matrix; T5's tier on a day without a depth file, 500 bps beyond the depth).

| Book | in sample Sharpe | validation Sharpe / CAGR / DD | by year | cost drag a year | test (validation) | DSR all / family | coins a day, coverage | passes |
|---|---|---|---|---|---|---|---|---|
| imb:xs | -2.01 | -0.72 / -16.6 % / 41.6 % | 2024 -1.32, 2025 -0.54, 2026 0.47 | 21.9 % | rank IC, 1-day late return +0.0081, t +1.60 (909 days) | 0.000 / 0.000 | 49, 98.6 % | fail |
| imb:ts | -2.06 | -0.99 / -31.0 % / 64.8 % | 2024 -1.98, 2025 -0.21, 2026 -0.17 | 16.7 % | mean daily gross return -4.15 bps a day, t -0.76 (912 days) | 0.000 / 0.000 | 47, 96.0 % | fail |
| dchg:xs | -1.43 | -1.84 / -37.5 % / 70.0 % | 2024 -1.84, 2025 -1.82, 2026 -1.94 | 45.2 % | rank IC, 1-day late return -0.0048, t -0.86 (877 days) | 0.000 / 0.000 | 49, 98.3 % | fail |
| dchg:ts | -1.57 | -1.23 / -48.9 % / 84.7 % | 2024 0.26, 2025 -2.82, 2026 -2.06 | 29.4 % | mean daily gross return -7.39 bps a day, t -1.00 (912 days) | 0.000 / 0.000 | 49, 98.3 % | fail |
| illiq:xs | -1.02 | -1.87 / -43.3 % / 78.2 % | 2024 -2.15, 2025 -2.06, 2026 -0.69 | 2.5 % | rank IC, 7-day late return -0.1447, t -8.20 (901 days) | 0.000 / 0.000 | 49, 98.3 % | fail |
| illiq:ts | 0.26 | 0.64 / 20.0 % / 38.6 % | 2024 1.24, 2025 0.84, 2026 -1.13 | 2.8 % | mean daily gross return +8.26 bps a day, t +1.25 (912 days) | 0.000 / 0.000 | 47, 95.7 % | fail |

DSR over 3,103 trials (noise bar 2.79 a year) and the hand family's 1,545 (2.78); pass at 0.95 or more. PBO of the six books: 0.01 over 12,870 splits.
Coverage: the universe's coin-days with the signal against PIT50's with a traded perp (validation).

| book | 1 Sharpe and years | 2 test t | 3 DSR all and family | 4 PBO | 5 leak | leak run |
|---|---|---|---|---|---|---|
| imb:xs | fail | fail | fail | pass | pass | no leak (12 runs) |
| imb:ts | fail | fail | fail | pass | pass | no leak (12 runs) |
| dchg:xs | fail | fail | fail | pass | pass | no leak (12 runs) |
| dchg:ts | fail | fail | fail | pass | pass | no leak (12 runs) |
| illiq:xs | fail | fail | fail | pass | pass | no leak (12 runs) |
| illiq:ts | pass | fail | fail | pass | pass | no leak (12 runs) |

Features through T1's harness (`lab.leak.checks.feature`, 1d, real rows): `bd_imb1` ok, `bd_imb1_dev30` ok, `bd_depth1_chg` ok, `bd_cost100k_bps` ok, `bd_cost100k_dev30` ok.

Depth falling ahead of moves (information): per day across the universe, rank(|r(t+1)| / s30) on rank(-DCHG) and rank(|r(t)| / s30): mean coefficient -0.0049, t -0.76 over 909 validation days (not shown at t 2 in the prior's direction).

Passed: none. Lockbox: no look (no book passes validation). Paper book: none (no book passes).

Trials (R5's registry, before the validation numbers): hand:o1:imb:xs, hand:o1:imb:ts, hand:o1:dchg:xs, hand:o1:dchg:ts, hand:o1:illiq:xs, hand:o1:illiq:ts, hand:o1:dchg:vol.
