# Family: volmom

```
Family 2: time-series momentum on the survivorship-free universe, with and without
volatility management of the whole book.

The base book is the existing candidate's rule (tsmom.py: hold a coin while its
28-day return is positive, each held coin sized to 40 % annual vol over the
number of slots, total capped at 100 %, daily) moved from today's 20 survivors
to the N most liquid coins OF EACH DAY. That alone answers whether the
candidate's edge was survivorship. Lookback and per-coin vol target are
carried over from the earlier lab rounds, not tuned again.

Vol management (Barroso and Santa-Clara 2015, Moreira and Muir 2017): scale the
whole book by its own recent volatility, measured on the unscaled book's daily
returns up to the decision close.
  invvol L   scale = 25 % / (book vol over the last L days), L = 20 or 60
  invvar     scale = c / (book variance over the last 20 days), c fitted in sample
             so the average scale over 2020 to 2023 is 1
Scale capped at 3x and the book at 100 % invested (no leverage).

Grid (16 variants): universe top 20 / top 50 · regime filter off / on ·
scaling none / invvol 20 / invvol 60 / invvar.
```

Survivorship-free Binance spot panel (591 coin segments), in sample 2020-08 to 2023, out of sample from 2024-01-01 (1010 days). Net of 15 and 41 bps per unit of one-way turnover. Deflated over all 100 variants of the whole sweep.

## In-sample picks, judged out of sample

| sub | variant | is_sharpe_15bps | oos_sharpe_15bps | oos_sharpe_41bps | oos_cagr_41bps | oos_max_dd_41bps | turnover_yr | deflated_p | sub_positive_share | verdict |
|---|---|---|---|---|---|---|---|---|---|---|
| spot long-only | tsmom 28d · top 20 · regime · none | 1.44 | 0.54 | 0.32 | 0.04 | 0.24 | 12.87 | 0.00 | 0.56 | fails: deflated p 0.00 <= 0.95 |

## Benchmarks (no costs)

| variant | is_sharpe_15bps | oos_sharpe_15bps | oos_sharpe_41bps | oos_cagr_15bps | oos_cagr_41bps | oos_max_dd_15bps | oos_max_dd_41bps | turnover_yr | avg_long | avg_short | oos_sharpe_btc_above | oos_sharpe_btc_below |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| BTC buy and hold | 0.92 | 0.78 | 0.78 | 0.29 | 0.29 | 0.53 | 0.53 | 0.00 | 1.00 | 0.00 | 1.07 | 0.35 |
| equal-weight universe | 1.00 | -0.34 | -0.34 | -0.41 | -0.41 | 0.91 | 0.91 | 0.00 | 1.00 | 0.00 | -0.40 | -0.23 |

## Every variant

| sub | variant | is_sharpe_15bps | oos_sharpe_15bps | oos_sharpe_41bps | oos_cagr_15bps | oos_cagr_41bps | oos_max_dd_15bps | oos_max_dd_41bps | turnover_yr | avg_long | avg_short | oos_sharpe_btc_above | oos_sharpe_btc_below | deflated_p |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| spot long-only | tsmom 28d · top 20 · regime · none | 1.44 | 0.54 | 0.32 | 0.07 | 0.04 | 0.22 | 0.24 | 12.87 | 0.17 | 0.00 | 0.70 | -2.29 | 0.00 |
| spot long-only | tsmom 28d · top 50 · regime · none | 1.35 | 0.33 | 0.11 | 0.04 | 0.01 | 0.22 | 0.24 | 11.46 | 0.13 | 0.00 | 0.44 | -2.33 | 0.00 |
| spot long-only | tsmom 28d · top 20 · regime · invvol 20 | 1.33 | 0.34 | 0.04 | 0.05 | -0.01 | 0.39 | 0.44 | 25.46 | 0.24 | 0.00 | 0.45 | -2.33 | 0.00 |
| spot long-only | tsmom 28d · top 20 · regime · invvol 60 | 1.29 | 0.39 | 0.15 | 0.07 | 0.01 | 0.39 | 0.41 | 21.20 | 0.24 | 0.00 | 0.51 | -2.30 | 0.00 |
| spot long-only | tsmom 28d · top 50 · regime · invvol 60 | 1.23 | 0.32 | 0.08 | 0.05 | -0.01 | 0.42 | 0.45 | 22.27 | 0.23 | 0.00 | 0.43 | -2.43 | 0.00 |
| spot long-only | tsmom 28d · top 50 · regime · invvol 20 | 1.23 | 0.14 | -0.15 | 0.01 | -0.06 | 0.41 | 0.47 | 24.95 | 0.23 | 0.00 | 0.20 | -2.45 | 0.00 |
| spot long-only | tsmom 28d · top 20 · none | 1.12 | 0.17 | -0.13 | 0.02 | -0.04 | 0.25 | 0.34 | 20.16 | 0.26 | 0.00 | 0.71 | -1.07 | 0.00 |
| spot long-only | tsmom 28d · top 50 · none | 1.06 | -0.03 | -0.32 | -0.01 | -0.06 | 0.31 | 0.36 | 17.05 | 0.20 | 0.00 | 0.44 | -1.14 | 0.00 |
| spot long-only | tsmom 28d · top 20 · regime · invvar 20 | 1.00 | 0.29 | -0.02 | 0.03 | -0.01 | 0.31 | 0.34 | 16.67 | 0.11 | 0.00 | 0.39 | -2.06 | 0.00 |
| spot long-only | tsmom 28d · top 20 · invvol 60 | 0.99 | -0.10 | -0.47 | -0.06 | -0.15 | 0.48 | 0.59 | 36.99 | 0.41 | 0.00 | 0.46 | -1.17 | 0.00 |
| spot long-only | tsmom 28d · top 50 · invvol 60 | 0.91 | -0.21 | -0.54 | -0.09 | -0.17 | 0.55 | 0.64 | 35.02 | 0.38 | 0.00 | 0.35 | -1.26 | 0.00 |
| spot long-only | tsmom 28d · top 50 · invvol 20 | 0.90 | -0.18 | -0.56 | -0.08 | -0.16 | 0.52 | 0.62 | 38.39 | 0.37 | 0.00 | 0.32 | -1.14 | 0.00 |
| spot long-only | tsmom 28d · top 50 · regime · invvar 20 | 0.90 | 0.32 | -0.00 | 0.03 | -0.01 | 0.25 | 0.28 | 14.98 | 0.09 | 0.00 | 0.43 | -2.19 | 0.00 |
| spot long-only | tsmom 28d · top 20 · invvol 20 | 0.88 | -0.01 | -0.43 | -0.03 | -0.13 | 0.44 | 0.56 | 41.78 | 0.41 | 0.00 | 0.55 | -1.10 | 0.00 |
| spot long-only | tsmom 28d · top 20 · invvar 20 | -0.32 | -0.60 | -1.04 | -0.05 | -0.08 | 0.22 | 0.28 | 13.98 | 0.09 | 0.00 | -0.22 | -1.25 | 0.00 |
| spot long-only | tsmom 28d · top 50 · invvar 20 | -0.73 | -0.55 | -0.96 | -0.03 | -0.05 | 0.15 | 0.19 | 9.07 | 0.05 | 0.00 | -0.35 | -0.83 | 0.00 |
