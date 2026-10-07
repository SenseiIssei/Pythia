# Family: blend

```
Family 8: dual momentum, trend + carry, and plain cross-sectional momentum.

  dual momentum   (Antonacci) each week, among the 50 most liquid coins, hold the
                  K with the best L-day return, but only those whose return is
                  positive (absolute momentum) AND above BTC's over the same
                  L days (relative momentum), while BTC is above its 200-day
                  average. Each coin sized to 40 % vol over K, capped at 100 %.
                  K 5 / 10 x L 28 / 56: 4 variants, spot long-only.
  trend + carry   the volmom base book (28-day trend, 20 most liquid, vol-sized,
                  daily) without the coins whose 7-day funding is in the top
                  third of the universe that day: trend where the longs are not
                  already crowded. With and without the regime filter: 2
                  variants, spot long-only.
  XS momentum L/S the no-model baseline for the market-neutral ranking book:
                  long the top quintile of the 50 most liquid coins by L-day
                  return, short the bottom quintile on perpetuals, weekly, half
                  the capital per side. L 28 / 56: 2 variants.
```

Survivorship-free Binance spot panel (591 coin segments), in sample 2020-08 to 2023, out of sample from 2024-01-01 (1010 days). Net of 15 and 41 bps per unit of one-way turnover. Deflated over all 100 variants of the whole sweep.

## In-sample picks, judged out of sample

| sub | variant | is_sharpe_15bps | oos_sharpe_15bps | oos_sharpe_41bps | oos_cagr_41bps | oos_max_dd_41bps | turnover_yr | deflated_p | sub_positive_share | verdict |
|---|---|---|---|---|---|---|---|---|---|---|
| XS momentum L/S | XS momentum 28d · top 50 · quintiles · weekly | 0.19 | -0.63 | -1.01 | -0.32 | 0.68 | 48.57 | 0.00 | 0.00 | fails: deflated p 0.00 <= 0.95; Sharpe at 41 bps -1.01 <= 0 |
| dual momentum | dual momentum · top 10 by 28d · top 50 · regime | 1.08 | 0.07 | -0.05 | -0.02 | 0.31 | 8.22 | 0.00 | 0.25 | fails: deflated p 0.00 <= 0.95; Sharpe at 41 bps -0.05 <= 0 |
| trend + carry | tsmom 28d · top 20 · not crowded by funding · regime | 1.48 | 0.71 | 0.37 | 0.03 | 0.17 | 13.56 | 0.00 | 1.00 | fails: deflated p 0.00 <= 0.95 |

## Benchmarks (no costs)

| variant | is_sharpe_15bps | oos_sharpe_15bps | oos_sharpe_41bps | oos_cagr_15bps | oos_cagr_41bps | oos_max_dd_15bps | oos_max_dd_41bps | turnover_yr | avg_long | avg_short | oos_sharpe_btc_above | oos_sharpe_btc_below |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| BTC buy and hold | 0.92 | 0.78 | 0.78 | 0.29 | 0.29 | 0.53 | 0.53 | 0.00 | 1.00 | 0.00 | 1.07 | 0.35 |
| equal-weight universe | 1.00 | -0.34 | -0.34 | -0.41 | -0.41 | 0.91 | 0.91 | 0.00 | 1.00 | 0.00 | -0.40 | -0.23 |

## Every variant

| sub | variant | is_sharpe_15bps | oos_sharpe_15bps | oos_sharpe_41bps | oos_cagr_15bps | oos_cagr_41bps | oos_max_dd_15bps | oos_max_dd_41bps | turnover_yr | avg_long | avg_short | oos_sharpe_btc_above | oos_sharpe_btc_below | deflated_p |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| XS momentum L/S | XS momentum 28d · top 50 · quintiles · weekly | 0.19 | -0.63 | -1.01 | -0.23 | -0.32 | 0.58 | 0.68 | 48.57 | 0.50 | 0.50 | 0.59 | -2.48 | 0.00 |
| XS momentum L/S | XS momentum 56d · top 50 · quintiles · weekly | -0.79 | -1.07 | -1.37 | -0.34 | -0.40 | 0.71 | 0.78 | 38.30 | 0.50 | 0.50 | 0.21 | -2.92 | 0.00 |
| dual momentum | dual momentum · top 10 by 28d · top 50 · regime | 1.08 | 0.07 | -0.05 | -0.00 | -0.02 | 0.28 | 0.31 | 8.22 | 0.15 | 0.00 | 0.07 | 0.11 | 0.00 |
| dual momentum | dual momentum · top 10 by 56d · top 50 · regime | 0.78 | -0.24 | -0.33 | -0.06 | -0.08 | 0.38 | 0.41 | 6.81 | 0.15 | 0.00 | -0.36 | 0.30 | 0.00 |
| dual momentum | dual momentum · top 5 by 28d · top 50 · regime | 0.69 | -0.14 | -0.25 | -0.04 | -0.06 | 0.33 | 0.34 | 7.89 | 0.14 | 0.00 | -0.20 | 0.14 | 0.00 |
| dual momentum | dual momentum · top 5 by 56d · top 50 · regime | 0.16 | -0.67 | -0.77 | -0.14 | -0.15 | 0.45 | 0.47 | 7.22 | 0.15 | 0.00 | -0.89 | -0.03 | 0.00 |
| trend + carry | tsmom 28d · top 20 · not crowded by funding · regime | 1.48 | 0.71 | 0.37 | 0.07 | 0.03 | 0.15 | 0.17 | 13.56 | 0.12 | 0.00 | 0.93 | -2.24 | 0.00 |
| trend + carry | tsmom 28d · top 20 · not crowded by funding | 1.20 | 0.48 | 0.01 | 0.05 | -0.01 | 0.12 | 0.20 | 20.80 | 0.18 | 0.00 | 0.93 | -0.55 | 0.00 |
