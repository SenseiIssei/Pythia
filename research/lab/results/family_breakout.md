# Family: breakout

```
Family 3: Donchian / N-day breakout trend following, long-only.

The turtle rule on daily closes: enter when the close is above the highest
close of the previous N days, exit when it falls below the lowest close of the
previous N/2 days. Each entry is sized to 40 % annual vol over the number of
slots and capped at 1/slots, then left to drift until the exit (no daily
resizing, which would only add turnover).

Grid (12 variants):
  coins    BTC and ETH (benchmark BTC), or the 10 most liquid coins of each day
           (a coin can only be entered while it is in the top 10; once in, it
           stays until its own exit signal)
  N        20, 55, 100 days (exit N/2: 10, 27, 50)
  regime   off, or on: no entries and everything sold while BTC is below its
           200-day average
```

Survivorship-free Binance spot panel (591 coin segments), in sample 2020-08 to 2023, out of sample from 2024-01-01 (1010 days). Net of 15 and 41 bps per unit of one-way turnover. Deflated over all 100 variants of the whole sweep.

## In-sample picks, judged out of sample

| sub | variant | is_sharpe_15bps | oos_sharpe_15bps | oos_sharpe_41bps | oos_cagr_41bps | oos_max_dd_41bps | turnover_yr | deflated_p | sub_positive_share | verdict |
|---|---|---|---|---|---|---|---|---|---|---|
| BTC+ETH | Donchian 55/27 · BTC+ETH · regime | 1.37 | 1.07 | 1.03 | 0.27 | 0.28 | 3.89 | 0.01 | 1.00 | fails: deflated p 0.01 <= 0.95 |
| top 10 liquid | Donchian 20/10 · top 10 liquid | 1.40 | 1.20 | 1.08 | 0.22 | 0.22 | 9.27 | 0.01 | 1.00 | fails: deflated p 0.01 <= 0.95 |

## Benchmarks (no costs)

| variant | is_sharpe_15bps | oos_sharpe_15bps | oos_sharpe_41bps | oos_cagr_15bps | oos_cagr_41bps | oos_max_dd_15bps | oos_max_dd_41bps | turnover_yr | avg_long | avg_short | oos_sharpe_btc_above | oos_sharpe_btc_below |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| BTC buy and hold | 0.92 | 0.78 | 0.78 | 0.29 | 0.29 | 0.53 | 0.53 | 0.00 | 1.00 | 0.00 | 1.07 | 0.35 |
| equal-weight universe | 1.00 | -0.34 | -0.34 | -0.41 | -0.41 | 0.91 | 0.91 | 0.00 | 1.00 | 0.00 | -0.40 | -0.23 |

## Every variant

| sub | variant | is_sharpe_15bps | oos_sharpe_15bps | oos_sharpe_41bps | oos_cagr_15bps | oos_cagr_41bps | oos_max_dd_15bps | oos_max_dd_41bps | turnover_yr | avg_long | avg_short | oos_sharpe_btc_above | oos_sharpe_btc_below | deflated_p |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| BTC+ETH | Donchian 55/27 · BTC+ETH · regime | 1.37 | 1.07 | 1.03 | 0.29 | 0.27 | 0.27 | 0.28 | 3.89 | 0.30 | 0.00 | 1.38 | -0.96 | 0.01 |
| BTC+ETH | Donchian 55/27 · BTC+ETH | 1.37 | 0.87 | 0.83 | 0.22 | 0.21 | 0.26 | 0.27 | 4.78 | 0.34 | 0.00 | 1.36 | -1.02 | 0.00 |
| BTC+ETH | Donchian 20/10 · BTC+ETH · regime | 1.31 | 0.79 | 0.66 | 0.15 | 0.12 | 0.27 | 0.29 | 10.43 | 0.23 | 0.00 | 1.02 | -1.63 | 0.00 |
| BTC+ETH | Donchian 20/10 · BTC+ETH | 1.27 | 0.68 | 0.54 | 0.14 | 0.10 | 0.30 | 0.31 | 12.16 | 0.31 | 0.00 | 1.05 | -0.25 | 0.00 |
| BTC+ETH | Donchian 100/50 · BTC+ETH · regime | 1.21 | 0.80 | 0.78 | 0.20 | 0.19 | 0.22 | 0.23 | 2.59 | 0.34 | 0.00 | 1.04 | 0.00 | 0.00 |
| BTC+ETH | Donchian 100/50 · BTC+ETH | 1.03 | 0.80 | 0.78 | 0.20 | 0.19 | 0.22 | 0.23 | 2.59 | 0.34 | 0.00 | 1.04 | 0.00 | 0.00 |
| top 10 liquid | Donchian 20/10 · top 10 liquid | 1.40 | 1.20 | 1.08 | 0.25 | 0.22 | 0.20 | 0.22 | 9.27 | 0.24 | 0.00 | 1.78 | -0.55 | 0.01 |
| top 10 liquid | Donchian 20/10 · top 10 liquid · regime | 1.39 | 1.37 | 1.28 | 0.28 | 0.25 | 0.18 | 0.20 | 7.33 | 0.18 | 0.00 | 1.78 | -1.94 | 0.02 |
| top 10 liquid | Donchian 55/27 · top 10 liquid · regime | 1.21 | 0.81 | 0.77 | 0.18 | 0.17 | 0.23 | 0.23 | 3.48 | 0.23 | 0.00 | 1.04 | -1.78 | 0.00 |
| top 10 liquid | Donchian 55/27 · top 10 liquid | 1.09 | 0.61 | 0.56 | 0.13 | 0.12 | 0.28 | 0.30 | 4.21 | 0.28 | 0.00 | 1.00 | -0.98 | 0.00 |
| top 10 liquid | Donchian 100/50 · top 10 liquid · regime | 1.09 | 0.62 | 0.60 | 0.14 | 0.14 | 0.29 | 0.29 | 2.27 | 0.30 | 0.00 | 0.80 | -1.98 | 0.00 |
| top 10 liquid | Donchian 100/50 · top 10 liquid | 0.89 | 0.57 | 0.54 | 0.13 | 0.12 | 0.29 | 0.29 | 2.39 | 0.34 | 0.00 | 0.83 | -0.74 | 0.00 |
