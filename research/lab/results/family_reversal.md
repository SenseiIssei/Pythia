# Family: reversal

```
Family 1: short-term cross-sectional reversal.

Idea (Jegadeesh 1990, Lehmann 1990; in crypto e.g. Liu, Tsyvinski and Wu 2022
find weekly reversal among small coins): last k days' losers bounce, winners
give some back. Rebalanced every k days.

Grid (12 variants):
  lookback k     1, 3, 7 days (holding = k days)
  universe       every eligible coin (60 days old, 1 M USD a day), or the 50 most liquid
  book           long-only: the bottom quintile, equal weight, fully invested (spot)
                 market-neutral: long the bottom quintile, short the top quintile on
                 perpetuals, half the capital per side (needs perps)
```

Survivorship-free Binance spot panel (591 coin segments), in sample 2020-08 to 2023, out of sample from 2024-01-01 (1010 days). Net of 15 and 41 bps per unit of one-way turnover. Deflated over all 100 variants of the whole sweep.

## In-sample picks, judged out of sample

| sub | variant | is_sharpe_15bps | oos_sharpe_15bps | oos_sharpe_41bps | oos_cagr_41bps | oos_max_dd_41bps | turnover_yr | deflated_p | sub_positive_share | verdict |
|---|---|---|---|---|---|---|---|---|---|---|
| long-only | 3d losers · all eligible · long-only | 0.86 | -0.91 | -1.56 | -0.78 | 0.99 | 193 | 0.00 | 0.00 | fails: deflated p 0.00 <= 0.95; Sharpe at 41 bps -1.56 <= 0; drawdown 99 % not below equal-weight universe 91 % |
| market-neutral | 7d losers · all eligible · market-neutral | 0.11 | -1.18 | -2.07 | -0.40 | 0.78 | 82.58 | 0.00 | 0.00 | fails: deflated p 0.00 <= 0.95; Sharpe at 41 bps -2.07 <= 0 |

## Benchmarks (no costs)

| variant | is_sharpe_15bps | oos_sharpe_15bps | oos_sharpe_41bps | oos_cagr_15bps | oos_cagr_41bps | oos_max_dd_15bps | oos_max_dd_41bps | turnover_yr | avg_long | avg_short | oos_sharpe_btc_above | oos_sharpe_btc_below |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| BTC buy and hold | 0.92 | 0.78 | 0.78 | 0.29 | 0.29 | 0.53 | 0.53 | 0.00 | 1.00 | 0.00 | 1.07 | 0.35 |
| equal-weight universe | 1.00 | -0.34 | -0.34 | -0.41 | -0.41 | 0.91 | 0.91 | 0.00 | 1.00 | 0.00 | -0.40 | -0.23 |

## Every variant

| sub | variant | is_sharpe_15bps | oos_sharpe_15bps | oos_sharpe_41bps | oos_cagr_15bps | oos_cagr_41bps | oos_max_dd_15bps | oos_max_dd_41bps | turnover_yr | avg_long | avg_short | oos_sharpe_btc_above | oos_sharpe_btc_below | deflated_p |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| long-only | 3d losers · all eligible · long-only | 0.86 | -0.91 | -1.56 | -0.63 | -0.78 | 0.97 | 0.99 | 193 | 1.00 | 0.00 | -0.83 | -1.06 | 0.00 |
| long-only | 7d losers · all eligible · long-only | 0.74 | -0.78 | -1.05 | -0.61 | -0.68 | 0.97 | 0.98 | 83.56 | 1.00 | 0.00 | -0.81 | -0.73 | 0.00 |
| long-only | 7d losers · top 50 liquid · long-only | 0.08 | -0.82 | -1.07 | -0.66 | -0.73 | 0.98 | 0.99 | 83.58 | 1.00 | 0.00 | -1.00 | -0.51 | 0.00 |
| long-only | 3d losers · top 50 liquid · long-only | 0.05 | -0.93 | -1.51 | -0.69 | -0.81 | 0.98 | 0.99 | 191 | 1.00 | 0.00 | -0.76 | -1.23 | 0.00 |
| long-only | 1d losers · all eligible · long-only | -0.15 | -1.58 | -3.47 | -0.78 | -0.95 | 0.99 | 1.00 | 559 | 1.00 | 0.00 | -1.51 | -1.72 | 0.00 |
| long-only | 1d losers · top 50 liquid · long-only | -0.69 | -1.92 | -3.55 | -0.88 | -0.97 | 1.00 | 1.00 | 553 | 1.00 | 0.00 | -1.83 | -2.08 | 0.00 |
| market-neutral | 7d losers · all eligible · market-neutral | 0.11 | -1.18 | -2.07 | -0.26 | -0.40 | 0.62 | 0.78 | 82.58 | 0.50 | 0.50 | -1.12 | -1.26 | 0.00 |
| market-neutral | 3d losers · all eligible · market-neutral | -0.48 | -1.84 | -4.12 | -0.33 | -0.59 | 0.68 | 0.92 | 190 | 0.50 | 0.50 | -1.74 | -1.98 | 0.00 |
| market-neutral | 7d losers · top 50 liquid · market-neutral | -0.77 | -0.38 | -1.07 | -0.15 | -0.31 | 0.51 | 0.69 | 82.36 | 0.50 | 0.50 | -0.72 | 0.21 | 0.00 |
| market-neutral | 3d losers · top 50 liquid · market-neutral | -1.83 | -1.07 | -2.51 | -0.34 | -0.60 | 0.71 | 0.92 | 190 | 0.50 | 0.50 | -1.08 | -1.07 | 0.00 |
| market-neutral | 1d losers · all eligible · market-neutral | -2.55 | -4.37 | -11.71 | -0.59 | -0.91 | 0.92 | 1.00 | 563 | 0.50 | 0.50 | -4.69 | -4.03 | 0.00 |
| market-neutral | 1d losers · top 50 liquid · market-neutral | -2.77 | -3.28 | -7.88 | -0.66 | -0.92 | 0.95 | 1.00 | 556 | 0.50 | 0.50 | -3.13 | -3.50 | 0.00 |
