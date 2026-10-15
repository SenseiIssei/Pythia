# alpaca_universe

<!-- generated below by lab.experiments.alpaca_universe; edit above this line only -->

## Results (generated 2026-10-15, data to 2026-10-14)

**Verdict: nothing passes.** breakout_top10: deflated p 0.00 <= 0.95; does not beat cash-left (0.49 vs 1.17, better in 1 of 3 years). tsmom_top20: deflated p 0.00 <= 0.95. tsmom_tranches: deflated p 0.01 <= 0.95. Deflation pool 377 trials (prior 331, here 46); the best noise trial is expected at an annual Sharpe of about 2.43. Panel: 591 coin segments, out of sample 1018 days.

### The Alpaca coins through time

15 of the 15 are in the panel as current segments. Eligible (alive, 60 days old, 1 M USD a day): 8 on 2020-08-01, 15 on 2024-01-01, 15 to 15 on every out-of-sample day. First eligible day: ADA 2020-03-01, BCH 2020-03-01, BTC 2020-03-01, DOGE 2020-03-01, ETH 2020-03-01, LINK 2020-03-01, LTC 2020-03-01, XRP 2020-03-01, SOL 2020-10-11, DOT 2020-10-18, UNI 2020-11-16, AVAX 2020-11-22, AAVE 2020-12-14, FIL 2020-12-15, PEPE 2023-07-05.

### Each pick against the cash-left book (out of sample, 35 bps)

`diff_*` is the pick minus the cash-left book, daily net returns; `diff_2024` to `diff_2026` are its summed returns per year; `sr_diff_*` the stationary-bootstrap 90 % band of the Sharpe difference.

| book | pick | pick_is_35 | pick_oos_35 | pick_oos_70 | pick_dd | pick_deflated_p | cash_oos_35 | twin_oos_35 | late_oos_35 | diff_sharpe | sr_diff_p05 | sr_diff_p95 | diff_2024 | diff_2025 | diff_2026 | passes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| breakout | Donchian 55/27 · top 15 · Alpaca coins | 1.39 | 0.49 | 0.45 | 0.32 | 0.00 | 1.17 | 0.34 | 0.36 | -0.29 | -1.33 | 0.12 | -0.11 | -0.12 | 0.08 | no |
| tsmom_daily | tsmom 28d · top 15 · regime · daily · Alpaca coins | 1.83 | 0.74 | 0.48 | 0.22 | 0.00 | 0.54 | 0.49 | 0.50 | 0.84 | -0.18 | 0.50 | 0.15 | -0.03 | 0.12 | no |
| tsmom_tranches | tsmom 28d · top 15 · regime · seven weekly tranches · Alpaca coins | 1.97 | 0.92 | 0.84 | 0.21 | 0.01 | 0.65 | 0.60 | 0.89 | 1.09 | -0.08 | 0.56 | 0.24 | 0.01 | 0.08 | no |

### Every book (in sample 2020-08 to 2023, out of sample from 2024)

O original (reference), C cash-left, R restricted to the Alpaca coins, T the survivorship-free twin (yearly top 15 list), L the pick one day late. Sharpe at 15 / 35 / 70 bps; CAGR, drawdown and the bootstrap band at 35 bps; trades and orders per month out of sample; `non_alpaca_share` the share of exposure in coins Alpaca does not list; deflated p over the whole pool.

| group | book | variant | is_taker 35bps | oos_maker 15bps | oos_taker 35bps | oos_stress 70bps | cagr_35 | dd_35 | expo | turnover_yr | trades_month | orders_month | coins_held | non_alpaca_share | deflated_p | boot35_p05 | boot35_p95 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| benchmark | - | BTC buy and hold | 0.92 | 0.74 | 0.74 | 0.74 | 0.27 | 0.53 | 1.00 | None | None | None | None | None | None | None | None |
| benchmark | - | Alpaca coins, equal weight, buy and hold | 1.14 | 0.42 | 0.42 | 0.42 | 0.05 | 0.76 | 1.00 | None | None | None | None | None | None | None | None |
| O | breakout | breakout_top10 | 1.35 | 1.15 | 1.06 | 0.90 | 0.22 | 0.22 | 0.24 | 9.33 | 13.39 | 13.39 | 3.61 | 0.52 | 0.01 | -0.20 | 2.12 |
| O | tsmom_daily | tsmom_top20 | 1.31 | 0.38 | 0.22 | -0.07 | 0.02 | 0.24 | 0.17 | 12.93 | 41.08 | 86.71 | 7.34 | 0.51 | 0.00 | -0.89 | 1.22 |
| O | tsmom_tranches | tsmom_tranches | 1.54 | 0.45 | 0.39 | 0.28 | 0.05 | 0.23 | 0.17 | 4.99 | 21.00 | 135 | 10.11 | 0.52 | 0.00 | -0.69 | 1.43 |
| C | breakout | breakout_top10 · non-Alpaca coins in cash | 1.45 | 1.24 | 1.17 | 1.04 | 0.18 | 0.16 | 0.15 | 5.74 | 7.71 | 7.71 | 2.08 | 0.00 | 0.02 | -0.18 | 2.35 |
| C | tsmom_daily | tsmom_top20 · non-Alpaca coins in cash | 1.68 | 0.68 | 0.54 | 0.29 | 0.04 | 0.09 | 0.09 | 6.17 | 15.93 | 40.81 | 3.35 | 0.00 | 0.00 | -0.64 | 1.61 |
| C | tsmom_tranches | tsmom_tranches · non-Alpaca coins in cash | 1.85 | 0.70 | 0.65 | 0.56 | 0.06 | 0.09 | 0.09 | 2.39 | 7.71 | 55.75 | 4.39 | 0.00 | 0.00 | -0.52 | 1.83 |
| R | breakout | Donchian 20/10 · top 5 · Alpaca coins | 1.36 | 1.01 | 0.92 | 0.76 | 0.19 | 0.23 | 0.24 | 9.66 | 6.21 | 6.21 | 1.72 | 0.00 | 0.00 | -0.22 | 1.89 |
| R | breakout | Donchian 55/27 · top 5 · Alpaca coins | 1.28 | 0.33 | 0.30 | 0.25 | 0.05 | 0.31 | 0.28 | 4.35 | 2.75 | 2.75 | 1.91 | 0.00 | 0.00 | -0.69 | 1.28 |
| R | breakout | Donchian 100/50 · top 5 · Alpaca coins | 0.84 | 0.38 | 0.36 | 0.34 | 0.07 | 0.29 | 0.30 | 2.27 | 1.49 | 1.49 | 2.18 | 0.00 | 0.00 | -0.59 | 1.37 |
| R | breakout | Donchian 20/10 · top 8 · Alpaca coins | 1.36 | 1.11 | 1.03 | 0.89 | 0.24 | 0.25 | 0.23 | 9.36 | 10.67 | 10.67 | 2.83 | 0.00 | 0.01 | -0.32 | 2.22 |
| R | breakout | Donchian 55/27 · top 8 · Alpaca coins | 1.23 | 0.46 | 0.43 | 0.38 | 0.08 | 0.36 | 0.26 | 3.98 | 4.42 | 4.42 | 3.15 | 0.00 | 0.00 | -0.71 | 1.54 |
| R | breakout | Donchian 100/50 · top 8 · Alpaca coins | 0.91 | 0.49 | 0.47 | 0.45 | 0.10 | 0.31 | 0.29 | 2.10 | 2.36 | 2.36 | 3.38 | 0.00 | 0.00 | -0.61 | 1.56 |
| R | breakout | Donchian 20/10 · top 10 · Alpaca coins | 1.30 | 1.01 | 0.94 | 0.80 | 0.21 | 0.26 | 0.22 | 9.30 | 13.30 | 13.30 | 3.42 | 0.00 | 0.01 | -0.52 | 2.06 |
| R | breakout | Donchian 55/27 · top 10 · Alpaca coins | 1.39 | 0.50 | 0.48 | 0.43 | 0.10 | 0.37 | 0.25 | 3.83 | 5.32 | 5.32 | 3.78 | 0.00 | 0.00 | -0.70 | 1.59 |
| R | breakout | Donchian 100/50 · top 10 · Alpaca coins | 0.89 | 0.50 | 0.48 | 0.46 | 0.11 | 0.31 | 0.28 | 1.99 | 2.78 | 2.78 | 4.16 | 0.00 | 0.00 | -0.54 | 1.50 |
| R | breakout | Donchian 20/10 · top 15 · Alpaca coins | 1.37 | 0.91 | 0.84 | 0.70 | 0.18 | 0.28 | 0.21 | 8.94 | 19.33 | 19.33 | 4.92 | 0.00 | 0.00 | -0.55 | 1.99 |
| R | breakout | Donchian 55/27 · top 15 · Alpaca coins | 1.39 | 0.52 | 0.49 | 0.45 | 0.10 | 0.32 | 0.23 | 3.28 | 6.63 | 6.63 | 4.96 | 0.00 | 0.00 | -0.61 | 1.56 |
| R | breakout | Donchian 100/50 · top 15 · Alpaca coins | 1.17 | 0.48 | 0.47 | 0.45 | 0.10 | 0.27 | 0.24 | 1.65 | 3.47 | 3.47 | 4.99 | 0.00 | 0.00 | -0.55 | 1.54 |
| R | tsmom_daily | tsmom 28d · top 5 · regime · daily · Alpaca coins | 1.49 | 0.91 | 0.77 | 0.50 | 0.14 | 0.16 | 0.23 | 14.94 | 8.69 | 46.52 | 1.89 | 0.00 | 0.00 | -0.39 | 1.81 |
| R | tsmom_tranches | tsmom 28d · top 5 · regime · seven weekly tranches · Alpaca coins | 1.61 | 0.82 | 0.76 | 0.67 | 0.15 | 0.19 | 0.23 | 5.83 | 4.12 | 30.66 | 2.45 | 0.00 | 0.00 | -0.31 | 1.83 |
| R | tsmom_daily | tsmom 28d · top 8 · regime · daily · Alpaca coins | 1.65 | 0.80 | 0.65 | 0.40 | 0.11 | 0.19 | 0.20 | 14.10 | 14.40 | 63.10 | 2.95 | 0.00 | 0.00 | -0.60 | 1.80 |
| R | tsmom_tranches | tsmom 28d · top 8 · regime · seven weekly tranches · Alpaca coins | 1.85 | 0.70 | 0.65 | 0.55 | 0.12 | 0.21 | 0.20 | 5.72 | 7.29 | 52.53 | 3.92 | 0.00 | 0.00 | -0.55 | 1.83 |
| R | tsmom_daily | tsmom 28d · top 10 · regime · daily · Alpaca coins | 1.63 | 0.78 | 0.62 | 0.36 | 0.10 | 0.23 | 0.19 | 14.27 | 18.58 | 70.16 | 3.62 | 0.00 | 0.00 | -0.64 | 1.76 |
| R | tsmom_tranches | tsmom 28d · top 10 · regime · seven weekly tranches · Alpaca coins | 1.89 | 0.76 | 0.71 | 0.61 | 0.13 | 0.22 | 0.20 | 5.47 | 8.84 | 63.10 | 4.83 | 0.00 | 0.00 | -0.55 | 1.88 |
| R | tsmom_daily | tsmom 28d · top 15 · regime · daily · Alpaca coins | 1.83 | 0.88 | 0.74 | 0.48 | 0.13 | 0.22 | 0.18 | 13.66 | 26.59 | 77.57 | 5.16 | 0.00 | 0.00 | -0.52 | 1.85 |
| R | tsmom_tranches | tsmom 28d · top 15 · regime · seven weekly tranches · Alpaca coins | 1.97 | 0.97 | 0.92 | 0.84 | 0.18 | 0.21 | 0.18 | 4.93 | 11.06 | 85.66 | 6.82 | 0.00 | 0.01 | -0.34 | 2.10 |
| T | breakout | Donchian 20/10 · top 5 · twin (yearly top 15 list) | 1.38 | 1.16 | 1.06 | 0.90 | 0.24 | 0.26 | 0.26 | 10.61 | 6.54 | 6.54 | 1.78 | 0.17 | 0.01 | -0.21 | 2.12 |
| T | breakout | Donchian 55/27 · top 5 · twin (yearly top 15 list) | 1.13 | 0.58 | 0.55 | 0.49 | 0.12 | 0.33 | 0.32 | 4.91 | 2.87 | 2.87 | 2.11 | 0.23 | 0.00 | -0.57 | 1.60 |
| T | breakout | Donchian 100/50 · top 5 · twin (yearly top 15 list) | 1.04 | 0.65 | 0.63 | 0.61 | 0.16 | 0.29 | 0.35 | 2.35 | 1.43 | 1.43 | 2.20 | 0.25 | 0.00 | -0.43 | 1.66 |
| T | breakout | Donchian 20/10 · top 8 · twin (yearly top 15 list) | 1.25 | 1.23 | 1.14 | 0.99 | 0.27 | 0.24 | 0.26 | 10.34 | 10.58 | 10.58 | 2.79 | 0.40 | 0.01 | -0.15 | 2.23 |
| T | breakout | Donchian 55/27 · top 8 · twin (yearly top 15 list) | 1.10 | 0.56 | 0.53 | 0.48 | 0.11 | 0.28 | 0.30 | 4.56 | 4.48 | 4.48 | 3.19 | 0.35 | 0.00 | -0.53 | 1.54 |
| T | breakout | Donchian 100/50 · top 8 · twin (yearly top 15 list) | 0.91 | 0.47 | 0.45 | 0.42 | 0.09 | 0.29 | 0.34 | 2.55 | 2.69 | 2.69 | 3.53 | 0.45 | 0.00 | -0.55 | 1.45 |
| T | breakout | Donchian 20/10 · top 10 · twin (yearly top 15 list) | 1.12 | 1.08 | 0.99 | 0.83 | 0.22 | 0.25 | 0.25 | 10.19 | 13.39 | 13.39 | 3.42 | 0.45 | 0.01 | -0.32 | 2.07 |
| T | breakout | Donchian 55/27 · top 10 · twin (yearly top 15 list) | 1.01 | 0.52 | 0.49 | 0.44 | 0.10 | 0.29 | 0.28 | 4.26 | 5.38 | 5.38 | 3.80 | 0.41 | 0.00 | -0.60 | 1.55 |
| T | breakout | Donchian 100/50 · top 10 · twin (yearly top 15 list) | 0.91 | 0.47 | 0.46 | 0.43 | 0.09 | 0.28 | 0.33 | 2.31 | 3.14 | 3.14 | 4.23 | 0.50 | 0.00 | -0.53 | 1.50 |
| T | breakout | Donchian 20/10 · top 15 · twin (yearly top 15 list) | 0.93 | 0.91 | 0.82 | 0.66 | 0.16 | 0.22 | 0.21 | 9.09 | 18.88 | 18.88 | 4.56 | 0.50 | 0.00 | -0.36 | 1.86 |
| T | breakout | Donchian 55/27 · top 15 · twin (yearly top 15 list) | 0.94 | 0.37 | 0.34 | 0.29 | 0.05 | 0.25 | 0.23 | 3.57 | 7.02 | 7.02 | 4.73 | 0.43 | 0.00 | -0.69 | 1.32 |
| T | breakout | Donchian 100/50 · top 15 · twin (yearly top 15 list) | 0.85 | 0.37 | 0.35 | 0.32 | 0.06 | 0.23 | 0.26 | 1.84 | 3.88 | 3.88 | 5.02 | 0.49 | 0.00 | -0.61 | 1.38 |
| T | tsmom_daily | tsmom 28d · top 5 · regime · daily · twin (yearly top 15 list) | 1.39 | 0.99 | 0.83 | 0.54 | 0.16 | 0.20 | 0.25 | 16.69 | 9.20 | 49.06 | 1.96 | 0.18 | 0.00 | -0.41 | 1.92 |
| T | tsmom_tranches | tsmom 28d · top 5 · regime · seven weekly tranches · twin (yearly top 15 list) | 1.52 | 0.94 | 0.88 | 0.77 | 0.18 | 0.20 | 0.25 | 6.58 | 4.36 | 32.42 | 2.56 | 0.20 | 0.00 | -0.32 | 1.98 |
| T | tsmom_daily | tsmom 28d · top 8 · regime · daily · twin (yearly top 15 list) | 1.34 | 0.88 | 0.70 | 0.40 | 0.12 | 0.22 | 0.22 | 16.16 | 15.24 | 65.17 | 2.99 | 0.33 | 0.00 | -0.50 | 1.76 |
| T | tsmom_tranches | tsmom 28d · top 8 · regime · seven weekly tranches · twin (yearly top 15 list) | 1.56 | 0.92 | 0.86 | 0.75 | 0.16 | 0.22 | 0.23 | 6.16 | 7.20 | 51.48 | 3.97 | 0.33 | 0.00 | -0.28 | 1.92 |
| T | tsmom_daily | tsmom 28d · top 10 · regime · daily · twin (yearly top 15 list) | 1.37 | 0.84 | 0.66 | 0.36 | 0.11 | 0.24 | 0.22 | 15.82 | 19.09 | 72.46 | 3.62 | 0.39 | 0.00 | -0.57 | 1.74 |
| T | tsmom_tranches | tsmom 28d · top 10 · regime · seven weekly tranches · twin (yearly top 15 list) | 1.53 | 0.85 | 0.78 | 0.67 | 0.14 | 0.23 | 0.23 | 6.15 | 8.99 | 64.24 | 4.87 | 0.40 | 0.00 | -0.36 | 1.84 |
| T | tsmom_daily | tsmom 28d · top 15 · regime · daily · twin (yearly top 15 list) | 1.34 | 0.66 | 0.49 | 0.19 | 0.07 | 0.23 | 0.19 | 14.42 | 26.92 | 76.76 | 4.84 | 0.44 | 0.00 | -0.62 | 1.48 |
| T | tsmom_tranches | tsmom 28d · top 15 · regime · seven weekly tranches · twin (yearly top 15 list) | 1.45 | 0.66 | 0.60 | 0.49 | 0.09 | 0.22 | 0.19 | 5.35 | 11.92 | 85.69 | 6.57 | 0.45 | 0.00 | -0.58 | 1.69 |
| L | breakout | Donchian 55/27 · top 15 · Alpaca coins · one day late | 1.40 | 0.39 | 0.36 | 0.32 | 0.06 | 0.33 | 0.23 | 3.28 | 6.63 | 6.63 | 4.96 | 0.00 | 0.00 | -0.72 | 1.39 |
| L | tsmom_daily | tsmom 28d · top 15 · regime · daily · Alpaca coins · one day late | 1.86 | 0.65 | 0.50 | 0.24 | 0.08 | 0.25 | 0.18 | 13.74 | 26.59 | 80.88 | 5.16 | 0.00 | 0.00 | -0.78 | 1.65 |
| L | tsmom_tranches | tsmom 28d · top 15 · regime · seven weekly tranches · Alpaca coins · one day late | 1.91 | 0.94 | 0.89 | 0.80 | 0.17 | 0.20 | 0.18 | 4.93 | 11.06 | 85.27 | 6.82 | 0.00 | 0.00 | -0.37 | 2.07 |

### Per year (Sharpe at 35 bps)

| group | book | variant | y2021 | y2022 | y2023 | y2024 | y2025 | y2026 |
|---|---|---|---|---|---|---|---|---|
| benchmark | - | BTC buy and hold | 0.98 | -1.29 | 2.35 | 1.76 | 0.05 | 0.03 |
| benchmark | - | Alpaca coins, equal weight, buy and hold | 2.53 | -1.20 | 1.86 | 1.51 | -0.33 | 0.02 |
| O | breakout | breakout_top10 | 2.43 | -0.84 | 1.72 | 1.84 | 0.46 | 0.38 |
| O | tsmom_daily | tsmom_top20 | 2.12 | 0.00 | 1.22 | 0.37 | -0.29 | 0.74 |
| O | tsmom_tranches | tsmom_tranches | 2.41 | 0.89 | 1.30 | 0.59 | 0.08 | 0.57 |
| C | breakout | breakout_top10 · non-Alpaca coins in cash | 2.38 | -0.61 | 1.93 | 2.19 | 0.32 | -0.02 |
| C | tsmom_daily | tsmom_top20 · non-Alpaca coins in cash | 1.99 | 0.00 | 1.68 | 1.56 | -0.35 | 0.49 |
| C | tsmom_tranches | tsmom_tranches · non-Alpaca coins in cash | 2.51 | 0.84 | 1.52 | 1.67 | -0.08 | 0.25 |
| R | breakout | Donchian 20/10 · top 5 · Alpaca coins | 2.07 | -0.81 | 1.82 | 1.76 | 0.37 | 0.16 |
| R | breakout | Donchian 55/27 · top 5 · Alpaca coins | 1.68 | -1.18 | 1.58 | 0.81 | -0.22 | -0.09 |
| R | breakout | Donchian 100/50 · top 5 · Alpaca coins | 1.22 | -0.85 | 0.91 | 0.92 | -0.22 | -0.20 |
| R | breakout | Donchian 20/10 · top 8 · Alpaca coins | 2.22 | -1.04 | 1.92 | 2.23 | 0.07 | -0.33 |
| R | breakout | Donchian 55/27 · top 8 · Alpaca coins | 1.71 | -1.58 | 1.71 | 1.13 | -0.37 | -0.01 |
| R | breakout | Donchian 100/50 · top 8 · Alpaca coins | 1.45 | -1.21 | 0.99 | 1.10 | -0.24 | -0.03 |
| R | breakout | Donchian 20/10 · top 10 · Alpaca coins | 2.31 | -1.10 | 1.74 | 2.06 | -0.19 | -0.11 |
| R | breakout | Donchian 55/27 · top 10 · Alpaca coins | 2.22 | -1.67 | 1.76 | 1.07 | -0.55 | 0.43 |
| R | breakout | Donchian 100/50 · top 10 · Alpaca coins | 1.42 | -0.89 | 0.98 | 1.07 | -0.27 | 0.26 |
| R | breakout | Donchian 20/10 · top 15 · Alpaca coins | 2.69 | -0.98 | 1.55 | 1.93 | -0.25 | -0.20 |
| R | breakout | Donchian 55/27 · top 15 · Alpaca coins | 2.25 | -1.75 | 1.72 | 1.04 | -0.47 | 0.45 |
| R | breakout | Donchian 100/50 · top 15 · Alpaca coins | 2.02 | -1.13 | 0.93 | 1.01 | -0.26 | 0.23 |
| R | tsmom_daily | tsmom 28d · top 5 · regime · daily · Alpaca coins | 1.49 | 0.00 | 1.35 | 1.55 | -0.00 | 0.59 |
| R | tsmom_tranches | tsmom 28d · top 5 · regime · seven weekly tranches · Alpaca coins | 1.80 | 0.84 | 1.40 | 1.48 | 0.25 | 0.24 |
| R | tsmom_daily | tsmom 28d · top 8 · regime · daily · Alpaca coins | 1.79 | 0.00 | 1.81 | 1.54 | -0.21 | 0.52 |
| R | tsmom_tranches | tsmom 28d · top 8 · regime · seven weekly tranches · Alpaca coins | 2.45 | 0.84 | 1.62 | 1.44 | 0.00 | 0.27 |
| R | tsmom_daily | tsmom 28d · top 10 · regime · daily · Alpaca coins | 1.92 | 0.00 | 1.75 | 1.28 | -0.26 | 0.86 |
| R | tsmom_tranches | tsmom 28d · top 10 · regime · seven weekly tranches · Alpaca coins | 2.53 | 0.84 | 1.71 | 1.47 | -0.04 | 0.59 |
| R | tsmom_daily | tsmom 28d · top 15 · regime · daily · Alpaca coins | 2.51 | 0.00 | 1.81 | 1.41 | -0.34 | 1.10 |
| R | tsmom_tranches | tsmom 28d · top 15 · regime · seven weekly tranches · Alpaca coins | 2.94 | 0.88 | 1.64 | 1.72 | 0.02 | 0.84 |
| T | breakout | Donchian 20/10 · top 5 · twin (yearly top 15 list) | 2.25 | -0.57 | 1.83 | 1.91 | 0.28 | 0.50 |
| T | breakout | Donchian 55/27 · top 5 · twin (yearly top 15 list) | 1.56 | -1.10 | 1.49 | 1.27 | -0.40 | 0.23 |
| T | breakout | Donchian 100/50 · top 5 · twin (yearly top 15 list) | 1.76 | -1.13 | 0.59 | 1.46 | -0.33 | 0.25 |
| T | breakout | Donchian 20/10 · top 8 · twin (yearly top 15 list) | 2.05 | -0.60 | 1.55 | 1.73 | 0.60 | 0.75 |
| T | breakout | Donchian 55/27 · top 8 · twin (yearly top 15 list) | 1.55 | -1.01 | 1.58 | 1.09 | -0.02 | 0.17 |
| T | breakout | Donchian 100/50 · top 8 · twin (yearly top 15 list) | 1.56 | -1.06 | 0.72 | 0.96 | -0.12 | 0.29 |
| T | breakout | Donchian 20/10 · top 10 · twin (yearly top 15 list) | 1.91 | -0.70 | 1.40 | 1.70 | 0.33 | 0.42 |
| T | breakout | Donchian 55/27 · top 10 · twin (yearly top 15 list) | 1.47 | -1.13 | 1.48 | 1.00 | -0.14 | 0.26 |
| T | breakout | Donchian 100/50 · top 10 · twin (yearly top 15 list) | 1.57 | -1.07 | 0.70 | 0.92 | -0.10 | 0.27 |
| T | breakout | Donchian 20/10 · top 15 · twin (yearly top 15 list) | 1.65 | -1.01 | 1.30 | 1.38 | 0.45 | 0.36 |
| T | breakout | Donchian 55/27 · top 15 · twin (yearly top 15 list) | 1.31 | -1.33 | 1.58 | 0.69 | -0.21 | 0.38 |
| T | breakout | Donchian 100/50 · top 15 · twin (yearly top 15 list) | 1.49 | -1.08 | 0.66 | 0.72 | -0.14 | 0.28 |
| T | tsmom_daily | tsmom 28d · top 5 · regime · daily · twin (yearly top 15 list) | 1.81 | 0.00 | 1.11 | 1.50 | -0.06 | 0.97 |
| T | tsmom_tranches | tsmom 28d · top 5 · regime · seven weekly tranches · twin (yearly top 15 list) | 2.04 | -1.00 | 1.17 | 1.65 | 0.10 | 0.66 |
| T | tsmom_daily | tsmom 28d · top 8 · regime · daily · twin (yearly top 15 list) | 1.55 | 0.00 | 1.39 | 1.14 | 0.07 | 0.94 |
| T | tsmom_tranches | tsmom 28d · top 8 · regime · seven weekly tranches · twin (yearly top 15 list) | 1.87 | -1.00 | 1.41 | 1.40 | 0.39 | 0.67 |
| T | tsmom_daily | tsmom 28d · top 10 · regime · daily · twin (yearly top 15 list) | 1.67 | 0.00 | 1.47 | 1.02 | 0.18 | 0.79 |
| T | tsmom_tranches | tsmom 28d · top 10 · regime · seven weekly tranches · twin (yearly top 15 list) | 2.00 | -1.00 | 1.39 | 1.22 | 0.42 | 0.58 |
| T | tsmom_daily | tsmom 28d · top 15 · regime · daily · twin (yearly top 15 list) | 1.50 | 0.00 | 1.66 | 0.62 | 0.15 | 0.77 |
| T | tsmom_tranches | tsmom 28d · top 15 · regime · seven weekly tranches · twin (yearly top 15 list) | 1.73 | 1.12 | 1.52 | 0.92 | 0.31 | 0.55 |
| L | breakout | Donchian 55/27 · top 15 · Alpaca coins · one day late | 2.27 | -1.59 | 1.70 | 0.84 | -0.48 | 0.32 |
| L | tsmom_daily | tsmom 28d · top 15 · regime · daily · Alpaca coins · one day late | 2.71 | 0.00 | 1.62 | 1.10 | -0.33 | 0.74 |
| L | tsmom_tranches | tsmom 28d · top 15 · regime · seven weekly tranches · Alpaca coins · one day late | 2.98 | 0.57 | 1.48 | 1.72 | -0.02 | 0.75 |

### Where the originals' exposure sits (out of sample)

- breakout_top10: BNB 16 % (not on Alpaca), BTC 15 %, XRP 11 %, ETH 10 %, SOL 9 %, TRX 9 % (not on Alpaca), DOGE 7 %, SUI 4 % (not on Alpaca), PEPE 4 %, ZEC 3 % (not on Alpaca), ADA 2 %, SHIB 1 % (not on Alpaca)
- tsmom_top20: BTC 11 %, BNB 11 % (not on Alpaca), TRX 7 % (not on Alpaca), ETH 7 %, SOL 6 %, XRP 5 %, DOGE 5 %, ADA 4 %, AVAX 3 %, SUI 3 % (not on Alpaca), LINK 3 %, PEPE 3 %
- tsmom_tranches: BNB 11 % (not on Alpaca), BTC 11 %, ETH 7 %, TRX 7 % (not on Alpaca), SOL 6 %, XRP 5 %, DOGE 5 %, ADA 4 %, AVAX 3 %, SUI 3 % (not on Alpaca), LINK 3 %, PEPE 3 %

### The twin's yearly lists

- 2020: BTC, ETH, BCH, XRP, BNB, EOS, LTC, ETC, LINK, TRX, XTZ, ADA, XLM, DASH, NEO
- 2021: BTC, ETH, XRP, LTC, BCH, LINK, BNB, ADA, DOT, XLM, EOS, YFI, ZIL, SUSHI, TRX
- 2022: BTC, ETH, LUNAUSDT~0, BNB, MATIC, SAND, SHIB, GALA, SOL, AVAX, XRP, DOT, ADA, DOGE, MANA
- 2023: BTC, ETH, XRP, DOGE, BNB, LTC, MATIC, SOL, ADA, LINK, SHIB, APE, TWT, TRX, FIL
- 2024: BTC, ETH, SOL, BNB, AVAX, XRP, ADA, OP, DOGE, ARB, MATIC, TIA, TRB, LINK, INJ
- 2025: BTC, ETH, XRP, DOGE, SOL, PEPE, SUI, BNB, TRX, ADA, HBAR, LINK, ENA, SHIB, NEIRO
- 2026: BTC, ETH, SOL, ZEC, BNB, XRP, DOGE, SUI, TRX, ASTER, ADA, AVAX, LUNC, LINK, BCH

### Deflation

Prior: 331 trials, variance backed out of the published bar (2.55 over 331); here 46 trials at 35 bps. Pooled bar 2.43 over 377.
