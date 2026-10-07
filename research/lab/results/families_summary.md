# Strategy families: the sweep

9 families, **100 variants**, all deflated together. Survivorship-free Binance spot panel of 591 coin segments (delisted coins included, reused tickers split), daily, in sample 2020-08 to 2023, out of sample 2024-01-01 to 2026-10-06. Pick = best in-sample Sharpe at 15 bps per sub-family; pass = deflated p > 0.95, Sharpe > 0 at 41 bps, drawdown below the benchmark.

Deflation: 100 trials, variance of their daily out-of-sample Sharpes 2.85e-03 (annual Sharpes winsorised at +-3; raw 1.77e-02). The best of 100 noise strategies would be expected to show an annual Sharpe of about 2.58; a pick needs to clear that by a margin its own skew and kurtosis allow.

## Benchmarks out of sample (no costs)

| variant | is_sharpe_15bps | oos_sharpe_15bps | oos_sharpe_41bps | oos_cagr_15bps | oos_cagr_41bps | oos_max_dd_15bps | oos_max_dd_41bps | turnover_yr | avg_long | avg_short | oos_sharpe_btc_above | oos_sharpe_btc_below |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| BTC buy and hold | 0.92 | 0.78 | 0.78 | 0.29 | 0.29 | 0.53 | 0.53 | 0.00 | 1.00 | 0.00 | 1.07 | 0.35 |
| equal-weight universe | 1.00 | -0.34 | -0.34 | -0.41 | -0.41 | 0.91 | 0.91 | 0.00 | 1.00 | 0.00 | -0.40 | -0.23 |

## Every pick

| family | sub | variant | benchmark | is_sharpe_15bps | oos_sharpe_15bps | oos_sharpe_41bps | oos_cagr_15bps | oos_cagr_41bps | oos_max_dd_41bps | turnover_yr | oos_sharpe_btc_above | oos_sharpe_btc_below | deflated_p | sub_positive_share | spot_only | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| reversal | long-only | 3d losers · all eligible · long-only | ew | 0.86 | -0.91 | -1.56 | -0.63 | -0.78 | 0.99 | 193 | -0.83 | -1.06 | 0.00 | 0.00 | yes | fails: deflated p 0.00 <= 0.95; Sharpe at 41 bps -1.56 <= 0; drawdown 99 % not below equal-weight universe 91 % |
| reversal | market-neutral | 7d losers · all eligible · market-neutral | ew | 0.11 | -1.18 | -2.07 | -0.26 | -0.40 | 0.78 | 82.58 | -1.12 | -1.26 | 0.00 | 0.00 | no | fails: deflated p 0.00 <= 0.95; Sharpe at 41 bps -2.07 <= 0 |
| volmom | spot long-only | tsmom 28d · top 20 · regime · none | ew | 1.44 | 0.54 | 0.32 | 0.07 | 0.04 | 0.24 | 12.87 | 0.70 | -2.29 | 0.00 | 0.56 | yes | fails: deflated p 0.00 <= 0.95 |
| breakout | BTC+ETH | Donchian 55/27 · BTC+ETH · regime | btc | 1.37 | 1.07 | 1.03 | 0.29 | 0.27 | 0.28 | 3.89 | 1.38 | -0.96 | 0.01 | 1.00 | yes | fails: deflated p 0.01 <= 0.95 |
| breakout | top 10 liquid | Donchian 20/10 · top 10 liquid | ew | 1.40 | 1.20 | 1.08 | 0.25 | 0.22 | 0.22 | 9.27 | 1.78 | -0.55 | 0.01 | 1.00 | yes | fails: deflated p 0.01 <= 0.95 |
| pairs | market-neutral | pairs · window 90d · z 1.5 · cointegrated only | ew | -0.73 | -1.21 | -1.66 | -0.03 | -0.05 | 0.12 | 4.89 | -1.62 | -0.37 | 0.00 | 0.00 | no | fails: deflated p 0.00 <= 0.95; Sharpe at 41 bps -1.66 <= 0 |
| season | BTC | weekdays top 2 · BTC | btc | 0.47 | -0.32 | -1.30 | -0.12 | -0.33 | 0.70 | 104 | -0.43 | -0.16 | 0.00 | 0.17 | yes | fails: deflated p 0.00 <= 0.95; Sharpe at 41 bps -1.30 <= 0; drawdown 70 % not below BTC buy and hold 53 % |
| season | ETH | turn of month · ETH | btc | 1.44 | -0.86 | -1.10 | -0.22 | -0.27 | 0.63 | 24.21 | -0.96 | -0.69 | 0.00 | 0.17 | yes | fails: deflated p 0.00 <= 0.95; Sharpe at 41 bps -1.10 <= 0; drawdown 63 % not below BTC buy and hold 53 % |
| funding | funding · BTC+ETH | funding contrarian · z 90d · BTC+ETH | btc | 1.33 | 0.08 | -0.17 | 0.00 | -0.04 | 0.23 | 14.70 | -0.56 | 0.69 | 0.00 | 1.00 | yes | fails: deflated p 0.00 <= 0.95; Sharpe at 41 bps -0.17 <= 0 |
| funding | funding · top 20 with perp | funding trend · z 180d · top 20 with perp | ew | 1.12 | 0.64 | 0.42 | 0.06 | 0.04 | 0.16 | 7.86 | 1.16 | -1.05 | 0.00 | 0.33 | yes | fails: deflated p 0.00 <= 0.95 |
| funding | open interest · old 20 | OI confirm · 7d · old 20 coins | ew | 0.38 | 0.69 | 0.13 | 0.11 | 0.01 | 0.36 | 37.98 | 1.14 | -0.38 | 0.00 | 0.50 | yes | fails: deflated p 0.00 <= 0.95 |
| lowvol | market-neutral | vol 60d · top 50 · beta-neutral BAB | ew | 0.54 | 2.11 | 1.91 | 0.83 | 0.72 | 0.17 | 22.90 | 2.38 | 1.78 | 0.21 | 0.50 | no | fails: deflated p 0.21 <= 0.95 |
| lowvol | spot long-only | vol 60d · top 100 · long-only | ew | 0.98 | 0.28 | 0.23 | -0.02 | -0.05 | 0.75 | 11.56 | 0.35 | 0.14 | 0.00 | 0.50 | yes | fails: deflated p 0.00 <= 0.95 |
| blend | XS momentum L/S | XS momentum 28d · top 50 · quintiles · weekly | ew | 0.19 | -0.63 | -1.01 | -0.23 | -0.32 | 0.68 | 48.57 | 0.59 | -2.48 | 0.00 | 0.00 | no | fails: deflated p 0.00 <= 0.95; Sharpe at 41 bps -1.01 <= 0 |
| blend | dual momentum | dual momentum · top 10 by 28d · top 50 · regime | ew | 1.08 | 0.07 | -0.05 | -0.00 | -0.02 | 0.31 | 8.22 | 0.07 | 0.11 | 0.00 | 0.25 | yes | fails: deflated p 0.00 <= 0.95; Sharpe at 41 bps -0.05 <= 0 |
| blend | trend + carry | tsmom 28d · top 20 · not crowded by funding · regime | ew | 1.48 | 0.71 | 0.37 | 0.07 | 0.03 | 0.17 | 13.56 | 0.93 | -2.24 | 0.00 | 1.00 | yes | fails: deflated p 0.00 <= 0.95 |
| ensemble | spot long-only | risk parity · 10 spot picks with IS Sharpe > 0.5 | ew | 1.49 | 0.42 | 0.11 | 0.05 | 0.01 | 0.23 | 14.88 | 0.69 | -0.50 | 0.00 | 1.00 | yes | fails: deflated p 0.00 <= 0.95 |
| ensemble | with market-neutral sleeves | risk parity · all 16 picks | ew | 1.62 | 0.30 | -0.35 | 0.02 | -0.03 | 0.15 | 16.53 | 0.58 | -0.71 | 0.00 | 1.00 | no | fails: deflated p 0.00 <= 0.95; Sharpe at 41 bps -0.35 <= 0 |

**Passing:** none.

## How sensitive is the deflation verdict?

deflated_p: the rule above (all trials, winsorised variance, own skew and kurtosis). rawvar: the variance without winsorising (stricter). null: the variance a pure-noise trial would have, 1/T (the textbook bar). family: only the trials of the pick's own family (more lenient, not the rule).

| family | variant | oos_sharpe_15bps | oos_skew | oos_kurt | deflated_p | deflated_p_rawvar | deflated_p_null | deflated_p_family |
|---|---|---|---|---|---|---|---|---|
| lowvol | vol 60d · top 50 · beta-neutral BAB | 2.11 | 0.21 | 7.08 | 0.21 | 0.00 | 0.84 | 0.23 |
| breakout | Donchian 20/10 · top 10 liquid | 1.20 | 0.55 | 15.23 | 0.01 | 0.00 | 0.29 | 0.91 |
| breakout | Donchian 55/27 · BTC+ETH · regime | 1.07 | 0.97 | 15.47 | 0.01 | 0.00 | 0.22 | 0.87 |
| blend | tsmom 28d · top 20 · not crowded by funding · regime | 0.71 | 0.60 | 9.76 | 0.00 | 0.00 | 0.09 | 0.43 |
| funding | OI confirm · 7d · old 20 coins | 0.69 | 1.80 | 20.51 | 0.00 | 0.00 | 0.08 | 0.53 |
| funding | funding trend · z 180d · top 20 with perp | 0.64 | -0.18 | 16.80 | 0.00 | 0.00 | 0.07 | 0.49 |
| volmom | tsmom 28d · top 20 · regime · none | 0.54 | 0.73 | 11.28 | 0.00 | 0.00 | 0.05 | 0.47 |
| ensemble | risk parity · 10 spot picks with IS Sharpe > 0.5 | 0.42 | -0.28 | 9.93 | 0.00 | 0.00 | 0.03 | 0.66 |
| ensemble | risk parity · all 16 picks | 0.30 | -0.13 | 8.92 | 0.00 | 0.00 | 0.02 | 0.59 |
| lowvol | vol 60d · top 100 · long-only | 0.28 | -0.38 | 6.37 | 0.00 | 0.00 | 0.02 | 0.00 |
| funding | funding contrarian · z 90d · BTC+ETH | 0.08 | -0.99 | 47.87 | 0.00 | 0.00 | 0.01 | 0.17 |
| blend | dual momentum · top 10 by 28d · top 50 · regime | 0.07 | 0.07 | 9.22 | 0.00 | 0.00 | 0.01 | 0.10 |
| season | weekdays top 2 · BTC | -0.32 | 1.00 | 15.92 | 0.00 | 0.00 | 0.00 | 0.00 |
| blend | XS momentum 28d · top 50 · quintiles · weekly | -0.63 | 0.31 | 5.50 | 0.00 | 0.00 | 0.00 | 0.01 |
| season | turn of month · ETH | -0.86 | -1.49 | 39.37 | 0.00 | 0.00 | 0.00 | 0.00 |
| reversal | 3d losers · all eligible · long-only | -0.91 | -0.50 | 6.77 | 0.00 | 0.00 | 0.00 | 0.00 |
| reversal | 7d losers · all eligible · market-neutral | -1.18 | -1.31 | 22.59 | 0.00 | 0.00 | 0.00 | 0.00 |
| pairs | pairs · window 90d · z 1.5 · cointegrated only | -1.21 | -2.64 | 28.58 | 0.00 | 0.00 | 0.00 | 0.00 |

## Reference: the existing paper candidate through the same bar

Same simulator and costs, on the 20 coins of today's fixed universe (survivors). Deflated as if it were trial 101 of this sweep.

| variant | is_sharpe_15bps | oos_sharpe_15bps | oos_sharpe_41bps | oos_cagr_41bps | oos_max_dd_41bps | turnover_yr | oos_sharpe_btc_above | oos_sharpe_btc_below | deflated_p | deflated_p_null | note |
|---|---|---|---|---|---|---|---|---|---|---|---|
| tsmom 28d · daily · vol 40% · 20 survivors | 1.66 | 0.74 | 0.44 | 0.07 | 0.32 | 21.90 | 1.40 | -0.90 | 0.00 | 0.09 | reference, not counted |
| tsmom 28d · daily · vol 40% · 20 survivors · regime | 1.91 | 1.07 | 0.86 | 0.14 | 0.23 | 14.22 | 1.39 | -2.05 | 0.00 | 0.22 | reference, not counted |
