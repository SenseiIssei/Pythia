# Family: lowvol

```
Family 7: low volatility and betting against beta in the crypto cross-section.

Frazzini and Pedersen (2014): leverage-constrained investors overpay for high
beta, so low-beta assets earn more per unit of risk. Tested on the most liquid
coins of each day, ranked weekly by
  vol 60d    realised volatility over the last 60 days (from hourly returns)
  beta 90d   beta to BTC over the last 90 daily returns
Books, rebalanced every 7 days:
  long-only         the lowest quintile, equal weight, fully invested (spot)
  dollar-neutral    long the lowest quintile, short the highest on perpetuals,
                    half the capital per side
  beta-neutral BAB  the same legs, each scaled by 1 / its average beta and then
                    normalised to 1x gross: net long in dollars, flat in beta

Grid (12 variants): measure vol / beta x universe top 50 / top 100 x 3 books.
```

Survivorship-free Binance spot panel (591 coin segments), in sample 2020-08 to 2023, out of sample from 2024-01-01 (1010 days). Net of 15 and 41 bps per unit of one-way turnover. Deflated over all 100 variants of the whole sweep.

## In-sample picks, judged out of sample

| sub | variant | is_sharpe_15bps | oos_sharpe_15bps | oos_sharpe_41bps | oos_cagr_41bps | oos_max_dd_41bps | turnover_yr | deflated_p | sub_positive_share | verdict |
|---|---|---|---|---|---|---|---|---|---|---|
| market-neutral | vol 60d · top 50 · beta-neutral BAB | 0.54 | 2.11 | 1.91 | 0.72 | 0.17 | 22.90 | 0.21 | 0.50 | fails: deflated p 0.21 <= 0.95 |
| spot long-only | vol 60d · top 100 · long-only | 0.98 | 0.28 | 0.23 | -0.05 | 0.75 | 11.56 | 0.00 | 0.50 | fails: deflated p 0.00 <= 0.95 |

## Benchmarks (no costs)

| variant | is_sharpe_15bps | oos_sharpe_15bps | oos_sharpe_41bps | oos_cagr_15bps | oos_cagr_41bps | oos_max_dd_15bps | oos_max_dd_41bps | turnover_yr | avg_long | avg_short | oos_sharpe_btc_above | oos_sharpe_btc_below |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| BTC buy and hold | 0.92 | 0.78 | 0.78 | 0.29 | 0.29 | 0.53 | 0.53 | 0.00 | 1.00 | 0.00 | 1.07 | 0.35 |
| equal-weight universe | 1.00 | -0.34 | -0.34 | -0.41 | -0.41 | 0.91 | 0.91 | 0.00 | 1.00 | 0.00 | -0.40 | -0.23 |

## Every variant

| sub | variant | is_sharpe_15bps | oos_sharpe_15bps | oos_sharpe_41bps | oos_cagr_15bps | oos_cagr_41bps | oos_max_dd_15bps | oos_max_dd_41bps | turnover_yr | avg_long | avg_short | oos_sharpe_btc_above | oos_sharpe_btc_below | deflated_p |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| market-neutral | vol 60d · top 50 · beta-neutral BAB | 0.54 | 2.11 | 1.91 | 0.83 | 0.72 | 0.17 | 0.17 | 22.90 | 0.57 | 0.42 | 2.38 | 1.78 | 0.21 |
| market-neutral | beta 90d · top 100 · beta-neutral BAB | 0.44 | -1.58 | -1.79 | -0.44 | -0.48 | 0.81 | 0.84 | 27.88 | 0.71 | 0.29 | -1.25 | -2.13 | 0.00 |
| market-neutral | beta 90d · top 50 · beta-neutral BAB | 0.42 | -1.79 | -1.97 | -0.52 | -0.55 | 0.87 | 0.89 | 26.42 | 0.71 | 0.29 | -1.00 | -3.01 | 0.00 |
| market-neutral | vol 60d · top 100 · beta-neutral BAB | 0.40 | 2.00 | 1.79 | 0.62 | 0.53 | 0.19 | 0.19 | 20.69 | 0.53 | 0.46 | 2.38 | 1.53 | 0.16 |
| market-neutral | vol 60d · top 50 · dollar-neutral | 0.38 | 1.95 | 1.78 | 0.86 | 0.75 | 0.18 | 0.18 | 23.32 | 0.50 | 0.49 | 2.20 | 1.57 | 0.15 |
| market-neutral | vol 60d · top 100 · dollar-neutral | 0.31 | 2.08 | 1.87 | 0.68 | 0.59 | 0.16 | 0.17 | 20.96 | 0.50 | 0.49 | 2.61 | 1.32 | 0.20 |
| market-neutral | beta 90d · top 50 · dollar-neutral | -0.16 | -1.05 | -1.24 | -0.35 | -0.39 | 0.70 | 0.75 | 25.03 | 0.50 | 0.50 | -0.27 | -2.25 | 0.00 |
| market-neutral | beta 90d · top 100 · dollar-neutral | -0.31 | -1.04 | -1.26 | -0.29 | -0.34 | 0.63 | 0.69 | 24.97 | 0.50 | 0.50 | -0.57 | -1.76 | 0.00 |
| spot long-only | vol 60d · top 100 · long-only | 0.98 | 0.28 | 0.23 | -0.02 | -0.05 | 0.74 | 0.75 | 11.56 | 1.00 | 0.00 | 0.35 | 0.14 | 0.00 |
| spot long-only | vol 60d · top 50 · long-only | 0.92 | 0.50 | 0.44 | 0.13 | 0.09 | 0.66 | 0.68 | 13.63 | 1.00 | 0.00 | 0.67 | 0.21 | 0.00 |
| spot long-only | beta 90d · top 100 · long-only | 0.61 | -1.20 | -1.30 | -0.62 | -0.64 | 0.95 | 0.96 | 24.65 | 1.00 | 0.00 | -1.07 | -1.43 | 0.00 |
| spot long-only | beta 90d · top 50 · long-only | 0.50 | -1.42 | -1.51 | -0.67 | -0.69 | 0.96 | 0.97 | 23.73 | 1.00 | 0.00 | -0.90 | -2.29 | 0.00 |

## Market-neutral vol books by year (top 50, 15 bps, sums of daily contributions)

The book is a bet that high-volatility coins (mostly recent listings) fall against the low-volatility majors. It pays when altcoins bleed (2022, 2024 to 2026: the short leg carries it) and loses or earns nothing when they rally (2020, 2023: the short leg gives back what the long leg makes). Funding is a heavy and growing drag: those shorts are crowded, so the shorts pay. In-sample Sharpe 0.3 to 0.5 against 2 out of sample says the out-of-sample years were the kind this bet likes, not that the bet got better.

| book | year | long_leg_pct | short_leg_pct | funding_pct | costs_pct | net_pct | sharpe |
|---|---|---|---|---|---|---|---|
| vol 60d · top 50 · dollar-neutral | 2020 | 70.84 | -74.23 | 6.74 | -2.79 | 0.55 | 0.01 |
| vol 60d · top 50 · dollar-neutral | 2021 | 88.61 | -81.83 | 24.06 | -3.97 | 26.87 | 0.52 |
| vol 60d · top 50 · dollar-neutral | 2022 | -33.62 | 116 | -11.12 | -4.01 | 66.84 | 1.78 |
| vol 60d · top 50 · dollar-neutral | 2023 | 32.07 | -22.64 | -26.14 | -3.54 | -20.25 | -0.58 |
| vol 60d · top 50 · dollar-neutral | 2024 | 47.38 | 5.20 | 6.93 | -3.46 | 56.05 | 1.58 |
| vol 60d · top 50 · dollar-neutral | 2025 | -15.17 | 104 | -21.55 | -3.42 | 64.15 | 1.88 |
| vol 60d · top 50 · dollar-neutral | 2026 | 7.52 | 113 | -50.04 | -2.80 | 67.74 | 2.55 |
| vol 60d · top 50 · beta-neutral BAB | 2020 | 87.46 | -78.96 | 8.25 | -3.21 | 13.55 | 0.24 |
| vol 60d · top 50 · beta-neutral BAB | 2021 | 102 | -75.40 | 21.49 | -3.85 | 43.81 | 0.87 |
| vol 60d · top 50 · beta-neutral BAB | 2022 | -36.87 | 102 | -8.94 | -3.81 | 52.68 | 1.68 |
| vol 60d · top 50 · beta-neutral BAB | 2023 | 40.41 | -18.73 | -21.61 | -3.20 | -3.13 | -0.12 |
| vol 60d · top 50 · beta-neutral BAB | 2024 | 59.14 | 2.80 | 5.00 | -3.16 | 63.78 | 2.32 |
| vol 60d · top 50 · beta-neutral BAB | 2025 | -13.00 | 90.07 | -17.92 | -3.22 | 55.92 | 2.03 |
| vol 60d · top 50 · beta-neutral BAB | 2026 | 0.97 | 117 | -54.33 | -3.13 | 60.39 | 2.06 |
