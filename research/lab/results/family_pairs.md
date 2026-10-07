# Family: pairs

```
Family 4: mean reversion of major-pair spreads, cointegration tested out of sample.

Fourteen pairs fixed in advance from economic similarity, not from the data:
ETH/BTC, LTC/BTC, BCH/BTC, BCH/LTC, ETC/ETH, BNB/ETH, SOL/ETH, AVAX/SOL,
LINK/ETH, DOGE/BTC, ADA/XRP, DOT/ADA, AAVE/UNI, XLM/XRP.

Walk-forward, every 30 days: on the trailing W days only, fit
log(a) = alpha + beta log(b) by OLS and run an Engle-Granger test on the
residual (ADF with one lag, 5 % critical value -3.34 for two series). For the
next 30 days the spread z = (residual - its window mean) / its window std uses
those frozen numbers. Enter at |z| > z_in (short the rich leg, long the cheap
one, the b leg scaled by beta), exit at |z| < 0.5, stop at |z| > 4, and
re-decide at every refit. Each open pair carries 1/7 of capital gross, the
book is capped at 1x gross. The long leg is spot, the short leg a perpetual
with real funding. Rebalanced daily to the pair weights (the drift turnover is
charged too).

Grid (8 variants): W 90 / 180 days · z_in 1.5 / 2.0 · trade only pairs that
pass the test in their window / trade every pair.

The extra table answers the question behind the family: does a pair that
tests cointegrated in one window still test cointegrated in the next one?
```

Survivorship-free Binance spot panel (591 coin segments), in sample 2020-08 to 2023, out of sample from 2024-01-01 (1010 days). Net of 15 and 41 bps per unit of one-way turnover. Deflated over all 100 variants of the whole sweep.

## In-sample picks, judged out of sample

| sub | variant | is_sharpe_15bps | oos_sharpe_15bps | oos_sharpe_41bps | oos_cagr_41bps | oos_max_dd_41bps | turnover_yr | deflated_p | sub_positive_share | verdict |
|---|---|---|---|---|---|---|---|---|---|---|
| market-neutral | pairs · window 90d · z 1.5 · cointegrated only | -0.73 | -1.21 | -1.66 | -0.05 | 0.12 | 4.89 | 0.00 | 0.00 | fails: deflated p 0.00 <= 0.95; Sharpe at 41 bps -1.66 <= 0 |

## Benchmarks (no costs)

| variant | is_sharpe_15bps | oos_sharpe_15bps | oos_sharpe_41bps | oos_cagr_15bps | oos_cagr_41bps | oos_max_dd_15bps | oos_max_dd_41bps | turnover_yr | avg_long | avg_short | oos_sharpe_btc_above | oos_sharpe_btc_below |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| BTC buy and hold | 0.92 | 0.78 | 0.78 | 0.29 | 0.29 | 0.53 | 0.53 | 0.00 | 1.00 | 0.00 | 1.07 | 0.35 |
| equal-weight universe | 1.00 | -0.34 | -0.34 | -0.41 | -0.41 | 0.91 | 0.91 | 0.00 | 1.00 | 0.00 | -0.40 | -0.23 |

## Every variant

| sub | variant | is_sharpe_15bps | oos_sharpe_15bps | oos_sharpe_41bps | oos_cagr_15bps | oos_cagr_41bps | oos_max_dd_15bps | oos_max_dd_41bps | turnover_yr | avg_long | avg_short | oos_sharpe_btc_above | oos_sharpe_btc_below | deflated_p |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| market-neutral | pairs · window 90d · z 1.5 · cointegrated only | -0.73 | -1.21 | -1.66 | -0.03 | -0.05 | 0.09 | 0.12 | 4.89 | 0.02 | 0.03 | -1.62 | -0.37 | 0.00 |
| market-neutral | pairs · window 90d · z 2.0 · all pairs | -0.74 | -0.54 | -1.22 | -0.08 | -0.16 | 0.28 | 0.43 | 35.24 | 0.32 | 0.32 | -0.85 | 0.22 | 0.00 |
| market-neutral | pairs · window 90d · z 1.5 · all pairs | -0.77 | -0.69 | -1.47 | -0.11 | -0.20 | 0.32 | 0.50 | 45.00 | 0.38 | 0.38 | -0.84 | -0.37 | 0.00 |
| market-neutral | pairs · window 90d · z 2.0 · cointegrated only | -0.89 | -0.93 | -1.39 | -0.02 | -0.03 | 0.06 | 0.09 | 4.19 | 0.02 | 0.02 | -1.16 | -0.42 | 0.00 |
| market-neutral | pairs · window 180d · z 2.0 · all pairs | -0.93 | -1.10 | -1.57 | -0.16 | -0.22 | 0.43 | 0.53 | 27.06 | 0.36 | 0.37 | -0.97 | -1.35 | 0.00 |
| market-neutral | pairs · window 180d · z 1.5 · all pairs | -1.15 | -1.47 | -1.98 | -0.23 | -0.29 | 0.54 | 0.63 | 32.75 | 0.42 | 0.43 | -1.50 | -1.42 | 0.00 |
| market-neutral | pairs · window 180d · z 1.5 · cointegrated only | -1.21 | -1.29 | -1.60 | -0.04 | -0.05 | 0.12 | 0.15 | 4.38 | 0.02 | 0.03 | -0.87 | -2.10 | 0.00 |
| market-neutral | pairs · window 180d · z 2.0 · cointegrated only | -1.33 | -1.03 | -1.31 | -0.03 | -0.04 | 0.10 | 0.12 | 3.59 | 0.02 | 0.03 | -0.37 | -2.26 | 0.00 |

## Does cointegration persist out of sample?

Every 30 days, every pair: Engle-Granger 5 % test on the trailing window, then the same test on the next, non-overlapping window. With no persistence the conditional and unconditional rates are equal. About 5 % of windows should pass by chance alone.

| window_days | pair_windows | tested_cointegrated | still_cointegrated_next_window | cointegrated_next_window_unconditional |
|---|---|---|---|---|
| 90 | 1043 | 0.08 | 0.04 | 0.08 |
| 180 | 961 | 0.09 | 0.09 | 0.08 |
