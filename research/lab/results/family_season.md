# Family: season

```
Family 5: calendar seasonality in BTC and ETH, with multiple-testing control.

66 hypotheses, tested on 2020-08 to 2023 only, on hourly closes:
  hour of day     24 per coin: is the mean return in this UTC hour different from the rest?
  day of week     7 per coin, on daily returns
  weekend         Saturday and Sunday against weekdays
  turn of month   the last day and the first three days of a month against the rest
Welch t-tests; Benjamini-Hochberg at a 5 % false discovery rate and Holm at 5 %
over all 66 together. The full table, with the same statistics out of sample,
is printed below the variants.

Tradable rules (12 variants), long the coin only inside the chosen windows,
flat (cash) otherwise. Turnover is two units each time a window opens and
closes, charged on the day it happens:
  hours BH        the hours that are positive and significant after BH (none: flat)
  hours top 3     the 3 hours with the highest in-sample t, no correction (the naive way)
  weekdays BH     the weekdays positive and significant after BH
  weekdays top 2  the 2 best weekdays in sample, no correction
  weekdays only   long Monday to Friday, flat at weekends (fixed in advance)
  turn of month   long the last day and the first three days of each month (fixed in advance)
```

Survivorship-free Binance spot panel (591 coin segments), in sample 2020-08 to 2023, out of sample from 2024-01-01 (1010 days). Net of 15 and 41 bps per unit of one-way turnover. Deflated over all 100 variants of the whole sweep.

## In-sample picks, judged out of sample

| sub | variant | is_sharpe_15bps | oos_sharpe_15bps | oos_sharpe_41bps | oos_cagr_41bps | oos_max_dd_41bps | turnover_yr | deflated_p | sub_positive_share | verdict |
|---|---|---|---|---|---|---|---|---|---|---|
| BTC | weekdays top 2 · BTC | 0.47 | -0.32 | -1.30 | -0.33 | 0.70 | 104 | 0.00 | 0.17 | fails: deflated p 0.00 <= 0.95; Sharpe at 41 bps -1.30 <= 0; drawdown 70 % not below BTC buy and hold 53 % |
| ETH | turn of month · ETH | 1.44 | -0.86 | -1.10 | -0.27 | 0.63 | 24.21 | 0.00 | 0.17 | fails: deflated p 0.00 <= 0.95; Sharpe at 41 bps -1.10 <= 0; drawdown 63 % not below BTC buy and hold 53 % |

## Benchmarks (no costs)

| variant | is_sharpe_15bps | oos_sharpe_15bps | oos_sharpe_41bps | oos_cagr_15bps | oos_cagr_41bps | oos_max_dd_15bps | oos_max_dd_41bps | turnover_yr | avg_long | avg_short | oos_sharpe_btc_above | oos_sharpe_btc_below |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| BTC buy and hold | 0.92 | 0.78 | 0.78 | 0.29 | 0.29 | 0.53 | 0.53 | 0.00 | 1.00 | 0.00 | 1.07 | 0.35 |
| equal-weight universe | 1.00 | -0.34 | -0.34 | -0.41 | -0.41 | 0.91 | 0.91 | 0.00 | 1.00 | 0.00 | -0.40 | -0.23 |

## Every variant

| sub | variant | is_sharpe_15bps | oos_sharpe_15bps | oos_sharpe_41bps | oos_cagr_15bps | oos_cagr_41bps | oos_max_dd_15bps | oos_max_dd_41bps | turnover_yr | avg_long | avg_short | oos_sharpe_btc_above | oos_sharpe_btc_below | deflated_p |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| BTC | weekdays top 2 · BTC | 0.47 | -0.32 | -1.30 | -0.12 | -0.33 | 0.42 | 0.70 | 104 | 0.29 | 0.00 | -0.43 | -0.16 | 0.00 |
| BTC | weekdays only · BTC | 0.43 | 0.31 | -0.31 | 0.04 | -0.21 | 0.59 | 0.73 | 104 | 0.71 | 0.00 | 0.29 | 0.35 | 0.00 |
| BTC | turn of month · BTC | 0.34 | -0.52 | -0.86 | -0.11 | -0.16 | 0.37 | 0.47 | 24.21 | 0.13 | 0.00 | -0.30 | -0.89 | 0.00 |
| BTC | hours BH · BTC | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| BTC | weekdays BH · BTC | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| BTC | hours top 3 · BTC | -12.66 | -19.38 | -53.12 | -0.96 | -1.00 | 1.00 | 1.00 | 2,188 | 0.12 | 0.00 | -18.98 | -20.12 | 0.00 |
| ETH | turn of month · ETH | 1.44 | -0.86 | -1.10 | -0.22 | -0.27 | 0.57 | 0.63 | 24.21 | 0.13 | 0.00 | -0.96 | -0.69 | 0.00 |
| ETH | weekdays only · ETH | 0.44 | -0.01 | -0.45 | -0.18 | -0.37 | 0.76 | 0.87 | 104 | 0.71 | 0.00 | 0.07 | -0.13 | 0.00 |
| ETH | weekdays top 2 · ETH | 0.41 | 0.22 | -1.25 | 0.02 | -0.41 | 0.53 | 0.83 | 208 | 0.29 | 0.00 | 1.19 | -1.11 | 0.00 |
| ETH | hours BH · ETH | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| ETH | weekdays BH · ETH | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| ETH | hours top 3 · ETH | -8.91 | -13.79 | -36.03 | -0.97 | -1.00 | 1.00 | 1.00 | 2,188 | 0.12 | 0.00 | -15.66 | -11.79 | 0.00 |

## The 66 calendar hypotheses

1 survive Benjamini-Hochberg at 5 %, 1 survive Holm at 5 %. 4 have a raw in-sample p below 0.05 (3.3 expected by chance). Those, with their out-of-sample mean and t:

| coin | test | is_mean_bps | is_t | is_p | bh_5pct | holm_5pct | oos_mean_bps | oos_t |
|---|---|---|---|---|---|---|---|---|
| ETH | hour 02 UTC | -6.92 | -3.64 | 0.00 | yes | yes | 0.68 | 0.19 |
| BTC | hour 02 UTC | -4.52 | -3.01 | 0.00 | no | no | 1.05 | 0.43 |
| ETH | hour 03 UTC | -4.80 | -2.53 | 0.01 | no | no | 3.46 | 1.81 |
| ETH | turn of month | 105 | 2.42 | 0.02 | no | no | -37.80 | -1.56 |
