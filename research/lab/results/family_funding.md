# Family: funding

```
Family 6: perpetual funding and open interest as timing signals for spot longs.

Funding is what leveraged longs pay shorts; when it is extreme the long side is
crowded. Two opposite stories, both tested:
  contrarian   buy the coin when funding is unusually LOW (shorts crowded, z < -1)
  trend        buy when funding is unusually HIGH (z > +1): demand persists
  not crowded  hold the coin except when funding is unusually high (z < +1)
z = 7-day summed funding against its own trailing mean and std over Z days
(Z = 90 or 180), all known at the decision close.

Open interest (5-minute metrics, only the 20 coins of the old fixed universe
from 2022 on, so this part is NOT survivorship-free and its in-sample period is
only two years):
  confirm      hold when open interest AND price both rose over the last h days
  capitulation hold when both fell (positions being closed into a drop)
  h = 3 or 7 days.

Each held coin is sized to 40 % annual vol over the number of slots, total
capped at 100 %, rebalanced daily, spot long-only.

Grid (16 variants): 3 funding rules x Z 90 / 180 x coins BTC+ETH / the 20 most
liquid coins that have a perpetual, plus 2 OI rules x h 3 / 7.
```

Survivorship-free Binance spot panel (591 coin segments), in sample 2020-08 to 2023, out of sample from 2024-01-01 (1010 days). Net of 15 and 41 bps per unit of one-way turnover. Deflated over all 100 variants of the whole sweep.

## In-sample picks, judged out of sample

| sub | variant | is_sharpe_15bps | oos_sharpe_15bps | oos_sharpe_41bps | oos_cagr_41bps | oos_max_dd_41bps | turnover_yr | deflated_p | sub_positive_share | verdict |
|---|---|---|---|---|---|---|---|---|---|---|
| funding · BTC+ETH | funding contrarian · z 90d · BTC+ETH | 1.33 | 0.08 | -0.17 | -0.04 | 0.23 | 14.70 | 0.00 | 1.00 | fails: deflated p 0.00 <= 0.95; Sharpe at 41 bps -0.17 <= 0 |
| funding · top 20 with perp | funding trend · z 180d · top 20 with perp | 1.12 | 0.64 | 0.42 | 0.04 | 0.16 | 7.86 | 0.00 | 0.33 | fails: deflated p 0.00 <= 0.95 |
| open interest · old 20 | OI confirm · 7d · old 20 coins | 0.38 | 0.69 | 0.13 | 0.01 | 0.36 | 37.98 | 0.00 | 0.50 | fails: deflated p 0.00 <= 0.95 |

## Benchmarks (no costs)

| variant | is_sharpe_15bps | oos_sharpe_15bps | oos_sharpe_41bps | oos_cagr_15bps | oos_cagr_41bps | oos_max_dd_15bps | oos_max_dd_41bps | turnover_yr | avg_long | avg_short | oos_sharpe_btc_above | oos_sharpe_btc_below |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| BTC buy and hold | 0.92 | 0.78 | 0.78 | 0.29 | 0.29 | 0.53 | 0.53 | 0.00 | 1.00 | 0.00 | 1.07 | 0.35 |
| equal-weight universe | 1.00 | -0.34 | -0.34 | -0.41 | -0.41 | 0.91 | 0.91 | 0.00 | 1.00 | 0.00 | -0.40 | -0.23 |

## Every variant

| sub | variant | is_sharpe_15bps | oos_sharpe_15bps | oos_sharpe_41bps | oos_cagr_15bps | oos_cagr_41bps | oos_max_dd_15bps | oos_max_dd_41bps | turnover_yr | avg_long | avg_short | oos_sharpe_btc_above | oos_sharpe_btc_below | deflated_p |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| funding · BTC+ETH | funding contrarian · z 90d · BTC+ETH | 1.33 | 0.08 | -0.17 | 0.00 | -0.04 | 0.17 | 0.23 | 14.70 | 0.13 | 0.00 | -0.56 | 0.69 | 0.00 |
| funding · BTC+ETH | funding contrarian · z 180d · BTC+ETH | 0.95 | 0.28 | 0.09 | 0.03 | 0.00 | 0.18 | 0.21 | 10.72 | 0.12 | 0.00 | -0.90 | 1.05 | 0.00 |
| funding · BTC+ETH | funding not crowded · z 180d · BTC+ETH | 0.85 | 0.31 | 0.19 | 0.05 | 0.01 | 0.48 | 0.48 | 15.38 | 0.62 | 0.00 | 0.55 | -0.02 | 0.00 |
| funding · BTC+ETH | funding not crowded · z 90d · BTC+ETH | 0.82 | 0.51 | 0.41 | 0.12 | 0.09 | 0.46 | 0.49 | 13.25 | 0.61 | 0.00 | 0.66 | 0.29 | 0.00 |
| funding · BTC+ETH | funding trend · z 90d · BTC+ETH | 0.48 | 0.28 | 0.13 | 0.03 | 0.01 | 0.35 | 0.38 | 10.07 | 0.16 | 0.00 | 1.24 | -1.58 | 0.00 |
| funding · BTC+ETH | funding trend · z 180d · BTC+ETH | 0.33 | 0.60 | 0.43 | 0.10 | 0.07 | 0.33 | 0.36 | 12.34 | 0.16 | 0.00 | 1.28 | -0.70 | 0.00 |
| funding · top 20 with perp | funding trend · z 180d · top 20 with perp | 1.12 | 0.64 | 0.42 | 0.06 | 0.04 | 0.14 | 0.16 | 7.86 | 0.08 | 0.00 | 1.16 | -1.05 | 0.00 |
| funding · top 20 with perp | funding trend · z 90d · top 20 with perp | 0.93 | 0.66 | 0.41 | 0.06 | 0.04 | 0.14 | 0.17 | 9.32 | 0.09 | 0.00 | 1.25 | -0.79 | 0.00 |
| funding · top 20 with perp | funding not crowded · z 90d · top 20 with perp | 0.34 | -0.20 | -0.35 | -0.08 | -0.12 | 0.45 | 0.50 | 15.23 | 0.40 | 0.00 | -0.28 | -0.08 | 0.00 |
| funding · top 20 with perp | funding not crowded · z 180d · top 20 with perp | 0.31 | -0.07 | -0.21 | -0.05 | -0.08 | 0.40 | 0.43 | 14.12 | 0.40 | 0.00 | -0.10 | -0.03 | 0.00 |
| funding · top 20 with perp | funding contrarian · z 90d · top 20 with perp | 0.23 | -0.13 | -0.46 | -0.01 | -0.04 | 0.16 | 0.19 | 10.29 | 0.08 | 0.00 | -0.63 | 0.39 | 0.00 |
| funding · top 20 with perp | funding contrarian · z 180d · top 20 with perp | 0.02 | -0.43 | -0.72 | -0.03 | -0.05 | 0.16 | 0.18 | 7.83 | 0.07 | 0.00 | -1.04 | 0.08 | 0.00 |
| open interest · old 20 | OI confirm · 7d · old 20 coins | 0.38 | 0.69 | 0.13 | 0.11 | 0.01 | 0.24 | 0.36 | 37.98 | 0.22 | 0.00 | 1.14 | -0.38 | 0.00 |
| open interest · old 20 | OI confirm · 3d · old 20 coins | 0.00 | 0.35 | -0.49 | 0.05 | -0.10 | 0.33 | 0.47 | 55.67 | 0.22 | 0.00 | 0.59 | -0.17 | 0.00 |
| open interest · old 20 | OI capitulation · 7d · old 20 coins | -0.54 | -0.25 | -0.76 | -0.07 | -0.16 | 0.35 | 0.46 | 39.18 | 0.23 | 0.00 | -0.14 | -0.41 | 0.00 |
| open interest · old 20 | OI capitulation · 3d · old 20 coins | -0.67 | -0.24 | -1.04 | -0.06 | -0.20 | 0.31 | 0.51 | 59.38 | 0.22 | 0.00 | -0.21 | -0.29 | 0.00 |
