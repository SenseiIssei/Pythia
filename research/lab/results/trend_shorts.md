<!-- generated below by lab.experiments.trend_shorts; edit above this line only -->

# Trend following with a short leg on perpetuals: results

Generated 2026-10-21T14:45:17+00:00. Registered in `results/trend_shorts_prereg.md` before the run.

In sample 2020-08-01 to 2023-12-31, out of sample 2024-01-01 to 2026-10-19 (1023 days). Every leg a USDT perpetual (longs pay funding, shorts receive it), judged at 10 bps per unit of one-way turnover.

## Verdict per book

- **tsmom_top20**, pick V4 always 50: kill: the short leg alone loses. Out of sample 0.27 against 0.31 long-only on perps (band of the difference -0.55 to 0.52), drawdown 23 % against 23 %, a close late 0.20, at 20 bps 0.13 against 0.23, short leg alone -0.04, deflated improvement p 0.0000. Against gated BTC (k 0.34, G 0.56): D -0.17, band -1.06 to 0.69, does not beat it. The book as it runs on spot at 35 bps: 0.21.
  - gate 1 higher Sharpe, and in 2 of 3 years: no
  - gate 2 drawdown not above long-only's: no
  - gate 3 bootstrap band of the difference above 0: no
  - gate 4 a close late still above long-only: no
  - gate 5 at 20 bps still above long-only: no
  - gate 6 improvement deflated above 0.95: no
- **breakout_top10**, pick V2 bear 50: fails. Out of sample 1.12 against 1.13 long-only on perps (band of the difference -0.25 to 0.28), drawdown 19 % against 20 %, a close late 0.81, at 20 bps 1.06 against 1.08, short leg alone 0.12, deflated improvement p 0.0000. Against gated BTC (k 0.56, G 0.49): D 0.61, band -0.25 to 1.44, does not beat it. The book as it runs on spot at 35 bps: 1.06.
  - gate 1 higher Sharpe, and in 2 of 3 years: no
  - gate 2 drawdown not above long-only's: yes
  - gate 3 bootstrap band of the difference above 0: no
  - gate 4 a close late still above long-only: no
  - gate 5 at 20 bps still above long-only: no
  - gate 6 improvement deflated above 0.95: no

## tsmom_top20: every variant

| variant | is_10bps | oos_0bps | oos_10bps | oos_20bps | oos_41bps | oos_cagr_pct | oos_dd_pct | y2024 | y2025 | y2026 | d_oos | short_is | short_oos | short_fund_oos_ann | avg_long | avg_short | turnover_yr | sr_on | sr_off |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| long-only (perps) | 1.27 | 0.40 | 0.31 | 0.23 | 0.05 | 3.74 | 22.60 | 0.41 | -0.08 | 0.75 |  |  |  |  | 0.17 | 0.00 | 13.05 | 0.41 | -2.27 |
| V1 bear 100 | 0.89 | 0.15 | 0.03 | -0.09 | -0.35 | -1.59 | 33.46 | -0.25 | -0.19 | 0.54 | -0.30 | -0.04 | -0.30 | -0.00 | 0.17 | 0.12 | 26.01 | 0.39 | -0.47 |
| V2 bear 50 | 1.13 | 0.27 | 0.16 | 0.05 | -0.19 | 1.30 | 27.15 | 0.05 | -0.15 | 0.69 | -0.30 | -0.04 | -0.30 | -0.00 | 0.17 | 0.06 | 19.45 | 0.40 | -0.48 |
| V3 always 100 | 1.00 | 0.33 | 0.18 | 0.03 | -0.30 | 1.56 | 30.87 | -0.23 | 0.44 | 0.32 | -0.04 | 0.09 | -0.04 | -0.00 | 0.17 | 0.23 | 34.20 | 0.61 | -0.46 |
| V4 always 50 | 1.26 | 0.42 | 0.27 | 0.13 | -0.17 | 3.17 | 23.29 | 0.07 | 0.27 | 0.54 | -0.04 | 0.09 | -0.04 | -0.00 | 0.17 | 0.12 | 23.48 | 0.56 | -0.46 |
| V5 dollar-neutral | 0.91 | 0.88 | -0.04 | -0.95 | -2.82 | -0.25 | 7.07 | -0.27 | 0.90 | -0.75 | -0.31 | 0.16 | 0.26 | -0.00 | 0.10 | 0.10 | 38.01 | 0.58 | -0.72 |

### tsmom_top20: the pick's legs by year (10 bps; 2020 to 2023 in sample)

| year | short_sharpe | short_ret_pct | short_fund_pct | long_ret_pct |
|---|---|---|---|---|
| 2020 | -1.26 | -9.33 | 0.83 | 24.52 |
| 2021 | -0.45 | -3.11 | 0.77 | 34.72 |
| 2022 | 0.98 | 12.41 | -1.11 | 0.00 |
| 2023 | -0.29 | -2.42 | 0.30 | 28.30 |
| 2024 | -0.67 | -5.78 | 0.47 | 8.60 |
| 2025 | 0.51 | 5.59 | -0.03 | 0.29 |
| 2026 | -0.12 | -1.23 | -0.80 | 10.54 |

## breakout_top10: every variant

| variant | is_10bps | oos_0bps | oos_10bps | oos_20bps | oos_41bps | oos_cagr_pct | oos_dd_pct | y2024 | y2025 | y2026 | d_oos | short_is | short_oos | short_fund_oos_ann | avg_long | avg_short | turnover_yr | sr_on | sr_off |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| long-only (perps) | 1.24 | 1.17 | 1.13 | 1.08 | 0.99 | 23.38 | 20.26 | 1.89 | 0.53 | 0.50 |  |  |  |  | 0.24 | 0.00 | 9.25 | 1.61 | -0.31 |
| V1 bear 100 | 1.19 | 1.09 | 1.03 | 0.98 | 0.85 | 24.68 | 22.14 | 1.47 | 0.44 | 1.00 | 0.14 | 0.14 | 0.13 | -0.00 | 0.24 | 0.10 | 14.46 | 1.61 | 0.07 |
| V2 bear 50 | 1.25 | 1.18 | 1.12 | 1.06 | 0.95 | 24.18 | 19.29 | 1.70 | 0.50 | 0.85 | 0.12 | 0.15 | 0.12 | -0.00 | 0.24 | 0.05 | 11.86 | 1.61 | -0.07 |
| V3 always 100 | 1.02 | 0.80 | 0.73 | 0.66 | 0.51 | 16.66 | 22.68 | 1.45 | -0.37 | 0.87 | -0.25 | -0.16 | -0.27 | 0.00 | 0.24 | 0.19 | 18.65 | 1.20 | -0.13 |
| V4 always 50 | 1.17 | 1.03 | 0.97 | 0.90 | 0.77 | 20.26 | 17.31 | 1.72 | -0.02 | 0.77 | -0.26 | -0.16 | -0.28 | 0.00 | 0.24 | 0.10 | 13.94 | 1.45 | -0.23 |
| V5 dollar-neutral | 0.85 | 1.01 | 0.71 | 0.40 | -0.24 | 2.63 | 4.44 | 1.43 | 0.41 | 0.31 | -1.00 | -0.21 | -0.14 | 0.00 | 0.05 | 0.05 | 11.54 | 1.21 | -0.13 |

### breakout_top10: the pick's legs by year (10 bps; 2020 to 2023 in sample)

| year | short_sharpe | short_ret_pct | short_fund_pct | long_ret_pct |
|---|---|---|---|---|
| 2020 | 0.00 | 0.00 | 0.00 | 29.49 |
| 2021 | -0.90 | -4.52 | 0.03 | 70.16 |
| 2022 | 1.15 | 13.13 | -1.11 | -12.08 |
| 2023 | -1.99 | -5.19 | -0.06 | 46.90 |
| 2024 | -0.71 | -3.98 | 0.05 | 50.71 |
| 2025 | 0.00 | 0.02 | -0.00 | 8.19 |
| 2026 | 0.81 | 7.77 | -0.26 | 10.53 |

Sharpe = daily mean over sd x sqrt 365. `d_oos`: Sharpe of the daily difference against the long-only perp book. `short_*`: the short leg alone (its price return, funding and its share of costs); `short_fund_oos_ann`: funding the short leg received a year. `sr_on` / `sr_off`: Sharpe on days the BTC gate was on / off at the previous close. Bootstrap: stationary, mean block 20 days, 4000 draws, seed 20261021.


## Pool

1,777 trials (1,140 hand, 600 factory, 37 registered today); the best noise trial sits at an annual Sharpe of about 2.71.
