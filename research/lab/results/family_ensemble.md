# Family: ensemble

```
Family 9: risk-parity ensembles of the other families' in-sample picks.

The sleeves are fixed by in-sample information only: in every sub-family of
families 1 to 8, the variant with the best 2020-2023 Sharpe at 15 bps (the
same pick the sweep judges). Nothing out of sample decides what goes in.

Weights are re-set every 30 days, proportional to 1 / (each sleeve's daily
volatility over the last 90 days), summing to 1, known at the decision close.
Each sleeve keeps its own costs; moving capital between sleeves is charged as
|change in sleeve weight| x the sleeve's gross exposure.

Variants (4):
  all picks, risk parity
  picks with in-sample Sharpe > 0.5, risk parity
  picks with in-sample Sharpe > 0.5, equal weight
  spot long-only picks with in-sample Sharpe > 0.5, risk parity (executable by the engine)
```

Survivorship-free Binance spot panel (591 coin segments), in sample 2020-08 to 2023, out of sample from 2024-01-01 (1010 days). Net of 15 and 41 bps per unit of one-way turnover. Deflated over all 100 variants of the whole sweep.

## In-sample picks, judged out of sample

| sub | variant | is_sharpe_15bps | oos_sharpe_15bps | oos_sharpe_41bps | oos_cagr_41bps | oos_max_dd_41bps | turnover_yr | deflated_p | sub_positive_share | verdict |
|---|---|---|---|---|---|---|---|---|---|---|
| spot long-only | risk parity · 10 spot picks with IS Sharpe > 0.5 | 1.49 | 0.42 | 0.11 | 0.01 | 0.23 | 14.88 | 0.00 | 1.00 | fails: deflated p 0.00 <= 0.95 |
| with market-neutral sleeves | risk parity · all 16 picks | 1.62 | 0.30 | -0.35 | -0.03 | 0.15 | 16.53 | 0.00 | 1.00 | fails: deflated p 0.00 <= 0.95; Sharpe at 41 bps -0.35 <= 0 |

## Benchmarks (no costs)

| variant | is_sharpe_15bps | oos_sharpe_15bps | oos_sharpe_41bps | oos_cagr_15bps | oos_cagr_41bps | oos_max_dd_15bps | oos_max_dd_41bps | turnover_yr | avg_long | avg_short | oos_sharpe_btc_above | oos_sharpe_btc_below |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| BTC buy and hold | 0.92 | 0.78 | 0.78 | 0.29 | 0.29 | 0.53 | 0.53 | 0.00 | 1.00 | 0.00 | 1.07 | 0.35 |
| equal-weight universe | 1.00 | -0.34 | -0.34 | -0.41 | -0.41 | 0.91 | 0.91 | 0.00 | 1.00 | 0.00 | -0.40 | -0.23 |

## Every variant

| sub | variant | is_sharpe_15bps | oos_sharpe_15bps | oos_sharpe_41bps | oos_cagr_15bps | oos_cagr_41bps | oos_max_dd_15bps | oos_max_dd_41bps | turnover_yr | avg_long | avg_short | oos_sharpe_btc_above | oos_sharpe_btc_below | deflated_p |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| spot long-only | risk parity · 10 spot picks with IS Sharpe > 0.5 | 1.49 | 0.42 | 0.11 | 0.05 | 0.01 | 0.18 | 0.23 | 14.88 | 0.16 | 0.00 | 0.69 | -0.50 | 0.00 |
| with market-neutral sleeves | risk parity · all 16 picks | 1.62 | 0.30 | -0.35 | 0.02 | -0.03 | 0.10 | 0.15 | 16.53 | 0.14 | 0.04 | 0.58 | -0.71 | 0.00 |
| with market-neutral sleeves | risk parity · 11 picks with IS Sharpe > 0.5 | 1.61 | 0.67 | 0.34 | 0.08 | 0.03 | 0.14 | 0.19 | 15.35 | 0.18 | 0.02 | 0.91 | -0.02 | 0.00 |
| with market-neutral sleeves | equal weight · 11 picks with IS Sharpe > 0.5 | 1.27 | 0.27 | -0.12 | 0.04 | -0.05 | 0.33 | 0.42 | 32.45 | 0.38 | 0.04 | 0.47 | -0.14 | 0.00 |
