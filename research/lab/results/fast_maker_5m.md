# Fast trades with maker orders only, on the 33 Alpaca coins (W15), 5-minute bars

`python -m lab.experiments.fast_maker --bars 5m`

The registered run. The pre-registration, its addendum and the 1h run are in `results/fast_maker.md`.


## Results, 5m bars (generated 2026-10-15, data to 2026-10-14)

**Verdict: nothing passes, no paper book.** Out of sample (2024-01-01 to 2026-10-14) 19 of 44 variants have a Sharpe above 0 in the base case (maker fills, 15 bps, 3 bps haircut), 20 make money per round trip after costs, 16 are positive with every order filled at the close at 35 bps a side and 32 before any cost. The best base case out of sample, picked after the fact, is B Donchian 55/27 · p 1.0 · W 1h · BTC gate at 1.39. The quarterly walk-forward pick makes 0.76 (drawdown 43 %). BTC buy and hold over the same days: Sharpe 0.74, 27 % a year, drawdown 53 %. Across the grid the maker fee a side at which the average round trip would net zero has a median of 7.3 bps (best 220.7); Alpaca charges 15. Deflation pool 841 trials, noise bar Sharpe 2.73 (registered pool 430, bar 2.82: fewer trials, but this study's own spread of Sharpes is wide, so its bar is not lower).

**The question asked: holds under two days.** 24 variants hold under 48 hours on average (families A and C, D's hours of day); 3 of them are positive out of sample in the base case and 0 at taker cost. Their filled round trip earns a median -2 bps before costs (best 69) against 36 bps for two resting legs; the maker fee a side at which the median one breaks even is -3.9 bps (below zero: it would need a rebate), and 4 of 24 clear Alpaca's 15. Against the same rules filled at the close, the resting fills change the gross per round trip by a median -14 bps: the fee saved is real, but a limit fills when the price comes to it, and the trades it misses are not the bad ones. The best of them out of sample (after the fact) is A drop k 5 · e 0.0 · hold 12h at 0.21, 33 bps net per round trip. The 20 variants that hold longer are not fast trades: family B (4h trend, pullback entries) holds a median 8 days and 16 of its 16 variants are positive in the base case (median 0.71, at taker cost 0.57); D's weekday and weekend windows hold 2 to 5 days.

### The picks against the pass rule

Per family the best in-sample Sharpe in the base case. `rt_day` counts round trips across all coins per day out of sample, `fill_rate_orders` the share of entry orders with any fill, `net_bps_rt` the average round trip after the haircut, fees and fallback costs (weighted by the filled share), `fee_needed_bps` the maker fee a side at which it would be zero. `twin_oos` is the survivorship-free twin, `late_oos` the pick decided and priced one bar late. The band is a stationary bootstrap (blocks of 20 days) of the base case Sharpe.

| variant | is_base | oos_base | oos_taker | oos_gross | rt_day | fill_rate_orders | net_bps_rt | fee_needed_bps | dd_base | y2024 | y2025 | y2026 | deflated_p | deflated_p_430 | boot_p05 | boot_p95 | twin_oos | late_oos | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A drop k 5 · e 0.5 · hold 4h | 0.51 | -0.56 | -1.23 | 0.24 | 1.65 | 0.75 | -14.72 | 7.65 | 0.32 | 0.24 | -1.37 | -0.23 | 0.00 | 0.00 | -1.35 | 0.43 | -0.39 | -0.76 | fails: Sharpe -0.56 <= 0; net -15 bps per round trip; deflated p 0.00 <= 0.95; twin -0.39; one bar late -0.76; positive in 1 of 3 years |
| B EMA 24/96 · p 0.5 · W 1h · BTC gate | 1.86 | 0.71 | 0.51 | 0.80 | 0.62 | 0.18 | 242 | 135 | 0.44 | 1.71 | -0.93 | 1.11 | 0.00 | 0.00 | -0.70 | 1.92 | 0.40 | 0.56 | fails: deflated p 0.00 <= 0.95 |
| C squeeze q 0.5 · e 0.5 · hold 12h | -2.99 | -3.54 | -5.16 | -1.77 | 1.28 | 0.34 | -75.87 | -23.01 | 0.32 | -5.27 | -2.66 | -2.98 | 0.00 | 0.00 | -4.30 | -2.79 | -2.92 | -3.70 | fails: Sharpe -3.54 <= 0; net -76 bps per round trip; deflated p 0.00 <= 0.95; twin -2.92; one bar late -3.70; positive in 0 of 3 years |
| D weekdays · N 60m | 0.32 | -0.22 | -0.41 | 0.08 | 2.75 | 0.96 | -46.01 | -8.01 | 0.76 | 0.45 | -0.88 | -0.15 | 0.00 | 0.00 | -1.19 | 0.79 | -0.55 | -0.26 | fails: Sharpe -0.22 <= 0; net -46 bps per round trip; deflated p 0.00 <= 0.95; twin -0.55; one bar late -0.26; positive in 1 of 3 years |

### Against BTC buy and hold (out of sample)

| book | Sharpe | CAGR | max drawdown | 2024 | 2025 | 2026 |
|---|---|---|---|---|---|---|
| BTC buy and hold, no cost | 0.74 | 27 % | 53 % | 1.76 | 0.05 | 0.03 |
| A drop k 5 · e 0.5 · hold 4h, maker base | -0.56 | -9 % | 32 % | 0.24 | -1.37 | -0.23 |
| A drop k 5 · e 0.5 · hold 4h, taker at the close | -1.23 | -20 % | 49 % | | | |
| B EMA 24/96 · p 0.5 · W 1h · BTC gate, maker base | 0.71 | 22 % | 44 % | 1.71 | -0.93 | 1.11 |
| B EMA 24/96 · p 0.5 · W 1h · BTC gate, taker at the close | 0.51 | 13 % | 47 % | | | |
| C squeeze q 0.5 · e 0.5 · hold 12h, maker base | -3.54 | -13 % | 32 % | -5.27 | -2.66 | -2.98 |
| C squeeze q 0.5 · e 0.5 · hold 12h, taker at the close | -5.16 | -30 % | 63 % | | | |
| D weekdays · N 60m, maker base | -0.22 | -25 % | 76 % | 0.45 | -0.88 | -0.15 |
| D weekdays · N 60m, taker at the close | -0.41 | -34 % | 83 % | | | |
| walk-forward pick by quarter, maker base | 0.76 | 23 % | 43 % | 1.69 | -0.92 | 0.85 |

### Sensitivity of the picks to the haircut (not trials)

| variant | oos_haircut 0 | oos_base | oos_haircut 10 |
|---|---|---|---|
| A drop k 5 · e 0.5 · hold 4h | -0.43 | -0.56 | -0.87 |
| B EMA 24/96 · p 0.5 · W 1h · BTC gate | 0.72 | 0.71 | 0.67 |
| C squeeze q 0.5 · e 0.5 · hold 12h | -3.26 | -3.54 | -4.18 |
| D weekdays · N 60m | -0.17 | -0.22 | -0.33 |

### What a round trip earns, by holding time (all 44 variants, out of sample)

A maker round trip costs 36 bps when both legs rest (2 x 15 fee + 2 x 3 haircut); at taker cost it is 70.

| hold | variants | median_gross_bps | best_gross_bps | median_net_bps | median_fee_needed | median_fill_rate | positive_base |
|---|---|---|---|---|---|---|---|
| 0 to 6 h | 16 | -1.72 | 22.93 | -37.71 | -3.86 | 0.94 | 0 |
| 6 to 24 h | 8 | 14.10 | 69.47 | -21.94 | 4.02 | 0.84 | 3 |
| 48 h and more | 20 | 152 | 457 | 116 | 72.51 | 0.22 | 16 |

### Walk-forward pick by quarter

- 2024Q1: B EMA 24/96 · p 0.5 · W 1h · BTC gate
- 2024Q2: B EMA 24/96 · p 0.5 · W 1h · BTC gate
- 2024Q3: B EMA 24/96 · p 0.5 · W 1h
- 2024Q4: B EMA 24/96 · p 0.5 · W 1h
- 2025Q1: B EMA 24/96 · p 1.0 · W 1h · BTC gate
- 2025Q2: B EMA 24/96 · p 1.0 · W 1h · BTC gate
- 2025Q3: B EMA 24/96 · p 1.0 · W 1h · BTC gate
- 2025Q4: B EMA 24/96 · p 1.0 · W 1h · BTC gate
- 2026Q1: B EMA 24/96 · p 1.0 · W 1h · BTC gate
- 2026Q2: B EMA 24/96 · p 1.0 · W 1h · BTC gate
- 2026Q3: B EMA 24/96 · p 1.0 · W 1h · BTC gate
- 2026Q4: B EMA 24/96 · p 1.0 · W 1h · BTC gate

### All 44 variants (out of sample unless marked is_)

`entries_day` entry orders and `orders_day` entry plus exit orders per day across all coins; `fill_rate_qty` the average filled share of an entry order; `maker_exit_share` the share of exit quantity sold as maker; `fallback_share` the share of round trips that needed the 24-hour taker fallback; `taker_gross_bps_rt` the same rules' round trip filled at the close; `skipped` entries (whole period) the 100 % limit refused.

| variant | is_base | oos_gross | oos_base | oos_taker | cagr_base | dd_base | entries_day | orders_day | rt_day | fill_rate_orders | fill_rate_qty | maker_exit_share | fallback_share | hold_h | gross_bps_rt | net_bps_rt | fee_needed_bps | taker_gross_bps_rt | y2024 | y2025 | y2026 | skipped |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A drop k 3 · e 0.0 · hold 12h | -0.27 | 1.28 | -0.06 | -0.86 | -0.08 | 0.64 | 7.69 | 21.72 | 7.40 | 0.96 | 0.94 | 1.00 | 0.00 | 12.35 | 44.17 | 8.06 | 19.02 | 58.66 | 1.85 | -1.33 | -0.74 | 1541 |
| A drop k 3 · e 0.0 · hold 1h | -2.68 | 0.63 | -3.10 | -4.85 | -0.46 | 0.82 | 11.84 | 28.38 | 11.40 | 0.96 | 0.94 | 1.00 | 0.00 | 1.23 | 10.16 | -25.86 | 2.08 | 25.44 | -2.23 | -2.50 | -6.20 | 1706 |
| A drop k 3 · e 0.0 · hold 4h | -1.08 | 0.63 | -1.64 | -2.95 | -0.37 | 0.76 | 9.78 | 25.56 | 9.39 | 0.96 | 0.94 | 1.00 | 0.00 | 4.29 | 14.17 | -21.86 | 4.08 | 28.11 | 0.03 | -2.21 | -3.13 | 1633 |
| A drop k 3 · e 0.5 · hold 12h | -0.23 | 1.31 | 0.13 | -0.86 | -0.01 | 0.55 | 8.20 | 19.25 | 5.90 | 0.72 | 0.70 | 1.00 | 0.00 | 12.34 | 51.78 | 15.65 | 22.81 | 58.66 | 2.01 | -1.07 | -0.48 | 1533 |
| A drop k 3 · e 0.5 · hold 1h | -2.08 | 0.62 | -2.47 | -4.85 | -0.36 | 0.71 | 11.70 | 23.84 | 8.44 | 0.72 | 0.70 | 1.00 | 0.00 | 1.22 | 11.55 | -24.48 | 2.77 | 25.44 | -1.74 | -2.20 | -5.39 | 1714 |
| A drop k 3 · e 0.5 · hold 4h | -0.79 | 0.85 | -1.07 | -2.95 | -0.24 | 0.63 | 10.02 | 22.12 | 7.20 | 0.72 | 0.70 | 1.00 | 0.00 | 4.29 | 22.93 | -13.11 | 8.45 | 28.11 | 0.61 | -1.91 | -2.24 | 1631 |
| A drop k 5 · e 0.0 · hold 12h | 0.44 | 0.84 | 0.21 | -0.21 | 0.02 | 0.31 | 1.92 | 5.23 | 1.86 | 0.97 | 0.95 | 1.00 | 0.00 | 12.32 | 68.77 | 32.64 | 31.27 | 80.17 | 0.97 | -0.38 | 0.24 | 478 |
| A drop k 5 · e 0.0 · hold 1h | 0.17 | 0.38 | -0.92 | -1.48 | -0.12 | 0.31 | 2.46 | 5.56 | 2.38 | 0.97 | 0.95 | 1.00 | 0.00 | 1.18 | 15.92 | -20.11 | 4.95 | 42.56 | -0.93 | -0.92 | -1.08 | 504 |
| A drop k 5 · e 0.0 · hold 4h | 0.42 | 0.28 | -0.61 | -1.23 | -0.11 | 0.35 | 2.18 | 5.48 | 2.11 | 0.97 | 0.95 | 1.00 | 0.00 | 4.26 | 20.04 | -16.00 | 7.01 | 28.55 | 0.16 | -1.23 | -0.61 | 493 |
| A drop k 5 · e 0.5 · hold 12h | 0.38 | 0.73 | 0.17 | -0.21 | 0.01 | 0.25 | 1.99 | 4.54 | 1.46 | 0.73 | 0.72 | 1.00 | 0.00 | 12.31 | 69.47 | 33.35 | 31.62 | 80.17 | 0.64 | -0.42 | 0.40 | 493 |
| A drop k 5 · e 0.5 · hold 1h | 0.08 | 0.09 | -0.96 | -1.48 | -0.12 | 0.33 | 2.43 | 4.79 | 1.84 | 0.76 | 0.74 | 1.00 | 0.00 | 1.18 | 8.07 | -27.95 | 1.03 | 42.56 | -0.79 | -1.51 | -0.15 | 506 |
| A drop k 5 · e 0.5 · hold 4h | 0.51 | 0.24 | -0.56 | -1.23 | -0.09 | 0.32 | 2.21 | 4.74 | 1.65 | 0.75 | 0.73 | 1.00 | 0.00 | 4.25 | 21.32 | -14.72 | 7.65 | 28.55 | 0.24 | -1.37 | -0.23 | 496 |
| B Donchian 55/27 · p 0.5 · W 1h | 1.25 | 0.90 | 0.71 | 0.62 | 0.21 | 0.57 | 5.46 | 7.54 | 1.11 | 0.20 | 0.19 | 1.00 | 0.00 | 157 | 155 | 118 | 73.70 | 157 | 2.64 | -1.00 | -0.56 | 1035 |
| B Donchian 55/27 · p 0.5 · W 1h · BTC gate | 1.27 | 1.23 | 1.09 | 0.84 | 0.35 | 0.43 | 4.19 | 5.53 | 0.80 | 0.19 | 0.17 | 1.00 | 0.00 | 145 | 278 | 242 | 134 | 229 | 2.56 | -0.90 | 1.04 | 825 |
| B Donchian 55/27 · p 0.5 · W 4h | 1.17 | 0.91 | 0.72 | 0.62 | 0.22 | 0.57 | 2.06 | 4.16 | 1.11 | 0.54 | 0.52 | 1.00 | 0.00 | 164 | 139 | 103 | 66.20 | 157 | 2.56 | -1.01 | -0.22 | 534 |
| B Donchian 55/27 · p 0.5 · W 4h · BTC gate | 1.19 | 1.13 | 0.98 | 0.84 | 0.31 | 0.46 | 1.61 | 2.98 | 0.82 | 0.51 | 0.49 | 1.00 | 0.00 | 149 | 231 | 195 | 111 | 229 | 2.34 | -0.87 | 1.04 | 395 |
| B Donchian 55/27 · p 1.0 · W 1h | 1.31 | 1.13 | 0.94 | 0.62 | 0.28 | 0.51 | 19.40 | 20.89 | 0.87 | 0.04 | 0.04 | 1.00 | 0.00 | 137 | 253 | 217 | 122 | 157 | 2.87 | -0.88 | -1.02 | 3594 |
| B Donchian 55/27 · p 1.0 · W 1h · BTC gate | 1.19 | 1.53 | 1.39 | 0.84 | 0.43 | 0.29 | 12.97 | 13.90 | 0.60 | 0.05 | 0.04 | 1.00 | 0.00 | 138 | 457 | 420 | 221 | 229 | 2.79 | -0.80 | 1.04 | 2860 |
| B Donchian 55/27 · p 1.0 · W 4h | 1.16 | 0.91 | 0.71 | 0.62 | 0.21 | 0.57 | 4.99 | 7.07 | 1.09 | 0.22 | 0.21 | 1.00 | 0.00 | 147 | 150 | 113 | 71.32 | 157 | 2.55 | -0.94 | -0.50 | 1020 |
| B Donchian 55/27 · p 1.0 · W 4h · BTC gate | 1.09 | 1.23 | 1.09 | 0.84 | 0.36 | 0.43 | 3.55 | 4.82 | 0.76 | 0.21 | 0.20 | 1.00 | 0.00 | 142 | 288 | 251 | 139 | 229 | 2.45 | -0.75 | 1.03 | 775 |
| B EMA 24/96 · p 0.5 · W 1h | 1.86 | 0.54 | 0.41 | 0.26 | 0.09 | 0.58 | 4.46 | 6.31 | 0.83 | 0.19 | 0.17 | 1.00 | 0.01 | 259 | 128 | 91.20 | 60.42 | 105 | 1.71 | -1.14 | 0.05 | 954 |
| B EMA 24/96 · p 0.5 · W 1h · BTC gate | 1.86 | 0.80 | 0.71 | 0.51 | 0.22 | 0.44 | 3.41 | 4.54 | 0.62 | 0.18 | 0.17 | 0.99 | 0.00 | 237 | 279 | 242 | 135 | 209 | 1.71 | -0.93 | 1.11 | 807 |
| B EMA 24/96 · p 0.5 · W 4h | 1.76 | 0.45 | 0.32 | 0.26 | 0.05 | 0.62 | 1.69 | 3.78 | 0.85 | 0.51 | 0.48 | 1.00 | 0.01 | 255 | 36.59 | 0.42 | 15.21 | 105 | 1.52 | -1.28 | 0.30 | 535 |
| B EMA 24/96 · p 0.5 · W 4h · BTC gate | 1.80 | 0.65 | 0.54 | 0.51 | 0.14 | 0.46 | 1.33 | 2.61 | 0.63 | 0.48 | 0.45 | 0.99 | 0.01 | 238 | 125 | 88.17 | 58.99 | 209 | 1.48 | -1.08 | 1.21 | 446 |
| B EMA 24/96 · p 1.0 · W 1h | 1.78 | 0.64 | 0.52 | 0.26 | 0.13 | 0.54 | 14.86 | 16.11 | 0.65 | 0.04 | 0.04 | 0.99 | 0.01 | 264 | 222 | 185 | 107 | 105 | 1.96 | -1.06 | -0.38 | 3591 |
| B EMA 24/96 · p 1.0 · W 1h · BTC gate | 1.86 | 0.94 | 0.85 | 0.51 | 0.25 | 0.36 | 10.12 | 10.87 | 0.47 | 0.05 | 0.04 | 0.99 | 0.01 | 260 | 432 | 395 | 209 | 209 | 1.97 | -0.92 | 0.85 | 2922 |
| B EMA 24/96 · p 1.0 · W 4h | 1.78 | 0.50 | 0.37 | 0.26 | 0.07 | 0.58 | 3.73 | 5.77 | 0.82 | 0.22 | 0.21 | 1.00 | 0.00 | 243 | 76.92 | 40.72 | 35.32 | 105 | 1.50 | -1.27 | 0.48 | 1029 |
| B EMA 24/96 · p 1.0 · W 4h · BTC gate | 1.71 | 0.66 | 0.56 | 0.51 | 0.15 | 0.45 | 2.79 | 4.03 | 0.61 | 0.22 | 0.21 | 0.99 | 0.01 | 229 | 172 | 136 | 82.49 | 209 | 1.56 | -1.13 | 1.06 | 805 |
| C squeeze q 0.5 · e 0.0 · hold 12h | -3.16 | -1.33 | -3.50 | -5.16 | -0.20 | 0.46 | 2.43 | 8.78 | 2.30 | 0.94 | 0.88 | 1.00 | 0.00 | 12.58 | -24.92 | -60.87 | -15.47 | -14.18 | -4.71 | -2.61 | -3.22 | 11 |
| C squeeze q 0.5 · e 0.0 · hold 4h | -6.44 | -1.92 | -6.54 | -8.43 | -0.22 | 0.50 | 3.23 | 12.53 | 3.06 | 0.95 | 0.88 | 1.00 | 0.00 | 4.66 | -14.17 | -50.15 | -10.09 | -2.02 | -7.04 | -5.57 | -7.27 | 5 |
| C squeeze q 0.5 · e 0.5 · hold 12h | -2.99 | -1.77 | -3.54 | -5.16 | -0.13 | 0.32 | 3.75 | 7.11 | 1.28 | 0.34 | 0.29 | 1.00 | 0.00 | 12.55 | -39.95 | -75.87 | -23.01 | -14.18 | -5.27 | -2.66 | -2.98 | 4 |
| C squeeze q 0.5 · e 0.5 · hold 4h | -4.36 | -1.97 | -5.54 | -8.43 | -0.11 | 0.27 | 4.20 | 8.44 | 1.43 | 0.34 | 0.29 | 1.00 | 0.00 | 4.64 | -18.43 | -54.40 | -12.22 | -2.02 | -6.04 | -4.90 | -5.67 | 2 |
| C squeeze q 0.7 · e 0.0 · hold 12h | -4.04 | -0.92 | -3.60 | -5.42 | -0.43 | 0.79 | 7.20 | 24.31 | 6.81 | 0.95 | 0.89 | 1.00 | 0.00 | 12.52 | -15.96 | -51.93 | -10.99 | -1.89 | -5.41 | -2.90 | -2.75 | 213 |
| C squeeze q 0.7 · e 0.0 · hold 4h | -8.89 | -1.77 | -7.90 | -11.18 | -0.52 | 0.87 | 10.17 | 34.99 | 9.64 | 0.95 | 0.89 | 1.00 | 0.00 | 4.54 | -11.50 | -47.48 | -8.75 | 1.87 | -9.11 | -6.87 | -8.36 | 98 |
| C squeeze q 0.7 · e 0.5 · hold 12h | -3.45 | -0.95 | -3.47 | -5.42 | -0.30 | 0.64 | 10.73 | 22.13 | 4.62 | 0.43 | 0.38 | 1.00 | 0.00 | 12.51 | -17.61 | -53.57 | -11.81 | -1.89 | -5.12 | -3.34 | -2.17 | 62 |
| C squeeze q 0.7 · e 0.5 · hold 4h | -7.20 | -1.92 | -7.35 | -11.18 | -0.34 | 0.69 | 12.89 | 26.86 | 5.57 | 0.43 | 0.38 | 1.00 | 0.00 | 4.52 | -14.70 | -50.67 | -10.36 | 1.87 | -8.21 | -6.88 | -7.13 | 38 |
| D best 2 hours · N 15m | -11.91 | -4.85 | -15.87 | -25.34 | -0.95 | 1.00 | 40.73 | 98.11 | 37.68 | 0.93 | 0.83 | 1.00 | 0.00 | 1.16 | -15.34 | -51.32 | -10.68 | -1.35 | -14.98 | -16.18 | -17.07 | 28024 |
| D best 2 hours · N 30m | -12.73 | -5.10 | -16.65 | -25.34 | -0.96 | 1.00 | 40.73 | 101 | 38.46 | 0.94 | 0.88 | 1.00 | 0.00 | 1.16 | -15.51 | -51.49 | -10.76 | -1.35 | -15.58 | -16.60 | -18.76 | 28001 |
| D best 4 hours · N 15m | -15.97 | -6.29 | -21.30 | -34.04 | -1.00 | 1.00 | 81.38 | 193 | 75.60 | 0.93 | 0.84 | 1.00 | 0.00 | 1.15 | -15.11 | -51.09 | -10.56 | -1.36 | -20.56 | -21.64 | -22.50 | 54856 |
| D best 4 hours · N 30m | -16.83 | -6.55 | -22.16 | -34.04 | -1.00 | 1.00 | 81.32 | 198 | 77.09 | 0.95 | 0.89 | 1.00 | 0.00 | 1.15 | -15.25 | -51.23 | -10.63 | -1.36 | -21.25 | -22.14 | -24.19 | 54139 |
| D weekdays · N 15m | 0.31 | 0.14 | -0.15 | -0.41 | -0.21 | 0.70 | 2.88 | 9.23 | 2.68 | 0.93 | 0.87 | 1.00 | 0.01 | 120 | -2.38 | -38.38 | -4.19 | 8.61 | 0.65 | -0.77 | -0.39 | 2043 |
| D weekdays · N 60m | 0.32 | 0.08 | -0.22 | -0.41 | -0.25 | 0.76 | 2.88 | 9.39 | 2.75 | 0.96 | 0.93 | 1.00 | 0.01 | 120 | -10.02 | -46.01 | -8.01 | 8.61 | 0.45 | -0.88 | -0.15 | 2043 |
| D weekend · N 15m | 0.17 | 0.15 | -0.39 | -0.94 | -0.13 | 0.48 | 2.91 | 6.57 | 2.69 | 0.92 | 0.83 | 1.00 | 0.00 | 48.12 | 8.51 | -27.51 | 1.25 | 12.12 | 0.39 | -0.63 | -1.67 | 1994 |
| D weekend · N 60m | 0.13 | 0.07 | -0.50 | -0.94 | -0.17 | 0.52 | 2.91 | 6.78 | 2.79 | 0.96 | 0.92 | 1.00 | 0.00 | 48.11 | 3.94 | -32.07 | -1.03 | 12.12 | 0.33 | -0.65 | -2.00 | 1994 |

### Checks on the picks (twin from 2024 only)

| variant | is_base | oos_gross | oos_base | oos_taker | cagr_base | dd_base | entries_day | orders_day | rt_day | fill_rate_orders | fill_rate_qty | maker_exit_share | fallback_share | hold_h | gross_bps_rt | net_bps_rt | fee_needed_bps | taker_gross_bps_rt | y2024 | y2025 | y2026 | skipped |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A drop k 5 · e 0.5 · hold 4h · survivorship-free twin | n/a | 0.44 | -0.39 | -1.00 | -0.05 | 0.29 | 2.08 | 4.01 | 1.55 | 0.75 | 0.73 | 1.00 | 0.00 | 4.17 | 32.53 | -3.53 | 13.24 | 39.85 | 1.13 | -1.43 | -0.80 | 222 |
| A drop k 5 · e 0.5 · hold 4h · one bar late | 0.22 | 0.02 | -0.76 | -1.56 | -0.12 | 0.43 | 2.19 | 4.87 | 1.70 | 0.78 | 0.76 | 1.00 | 0.00 | 4.27 | 0.30 | -35.70 | -2.85 | 10.98 | 0.01 | -1.61 | -0.21 | 495 |
| B EMA 24/96 · p 0.5 · W 1h · BTC gate · survivorship-free twin | n/a | 0.51 | 0.40 | 0.17 | 0.08 | 0.44 | 4.31 | 5.25 | 0.74 | 0.17 | 0.16 | 0.99 | 0.01 | 238 | -20.89 | -57.00 | -13.65 | -61.73 | 1.08 | -0.92 | 1.16 | 805 |
| B EMA 24/96 · p 0.5 · W 1h · BTC gate · one bar late | 1.82 | 0.66 | 0.56 | 0.49 | 0.15 | 0.43 | 3.38 | 4.58 | 0.62 | 0.18 | 0.17 | 0.99 | 0.00 | 241 | 163 | 126 | 77.91 | 201 | 1.46 | -0.86 | 0.94 | 749 |
| C squeeze q 0.5 · e 0.5 · hold 12h · survivorship-free twin | n/a | -1.07 | -2.92 | -5.22 | -0.12 | 0.29 | 4.88 | 7.95 | 1.65 | 0.34 | 0.30 | 1.00 | 0.00 | 12.34 | -27.66 | -63.61 | -16.85 | -21.26 | -4.16 | -2.00 | -2.67 | 0 |
| C squeeze q 0.5 · e 0.5 · hold 12h · one bar late | -2.98 | -2.01 | -3.70 | -5.01 | -0.14 | 0.34 | 3.72 | 7.09 | 1.25 | 0.34 | 0.29 | 1.00 | 0.00 | 12.57 | -46.93 | -82.84 | -26.52 | -11.90 | -5.46 | -2.48 | -3.00 | 5 |
| D weekdays · N 60m · survivorship-free twin | n/a | -0.25 | -0.55 | -0.71 | -0.38 | 0.84 | 3.21 | 8.46 | 3.10 | 0.97 | 0.94 | 1.00 | 0.00 | 120 | -88.98 | -125 | -47.72 | -65.36 | -0.12 | -1.05 | -0.50 | 1518 |
| D weekdays · N 60m · one bar late | 0.23 | 0.05 | -0.26 | -0.38 | -0.26 | 0.77 | 2.88 | 9.64 | 2.76 | 0.96 | 0.92 | 1.00 | 0.01 | 120 | -15.24 | -51.21 | -10.63 | 11.72 | 0.58 | -0.98 | -0.40 | 2043 |

### Deflation pool

488 hand trials with the variance backed out of the published bar (2.43 over 377), the factory's 300 with the variance of their in-sample Sharpes, and this study's 53 (base case, out of sample, clipped at +-3): bar 2.73 over 841. The registered pool (430: 377 plus this study) has a bar of 2.82.

Family D's hours, ranked in sample (best first, UTC): 5, 13, 15, 0, 10, 23, 6, 7, 22, 21, 1, 4, 16, 20, 12, 18, 9, 19, 11, 17, 8, 14, 3, 2.

Trials counted here: A drop k 3 · e 0.0 · hold 1h; A drop k 3 · e 0.0 · hold 4h; A drop k 3 · e 0.0 · hold 12h; A drop k 3 · e 0.5 · hold 1h; A drop k 3 · e 0.5 · hold 4h; A drop k 3 · e 0.5 · hold 12h; A drop k 5 · e 0.0 · hold 1h; A drop k 5 · e 0.0 · hold 4h; A drop k 5 · e 0.0 · hold 12h; A drop k 5 · e 0.5 · hold 1h; A drop k 5 · e 0.5 · hold 4h; A drop k 5 · e 0.5 · hold 12h; B EMA 24/96 · p 0.5 · W 1h; B EMA 24/96 · p 0.5 · W 1h · BTC gate; B EMA 24/96 · p 0.5 · W 4h; B EMA 24/96 · p 0.5 · W 4h · BTC gate; B EMA 24/96 · p 1.0 · W 1h; B EMA 24/96 · p 1.0 · W 1h · BTC gate; B EMA 24/96 · p 1.0 · W 4h; B EMA 24/96 · p 1.0 · W 4h · BTC gate; B Donchian 55/27 · p 0.5 · W 1h; B Donchian 55/27 · p 0.5 · W 1h · BTC gate; B Donchian 55/27 · p 0.5 · W 4h; B Donchian 55/27 · p 0.5 · W 4h · BTC gate; B Donchian 55/27 · p 1.0 · W 1h; B Donchian 55/27 · p 1.0 · W 1h · BTC gate; B Donchian 55/27 · p 1.0 · W 4h; B Donchian 55/27 · p 1.0 · W 4h · BTC gate; C squeeze q 0.5 · e 0.0 · hold 4h; C squeeze q 0.5 · e 0.0 · hold 12h; C squeeze q 0.5 · e 0.5 · hold 4h; C squeeze q 0.5 · e 0.5 · hold 12h; C squeeze q 0.7 · e 0.0 · hold 4h; C squeeze q 0.7 · e 0.0 · hold 12h; C squeeze q 0.7 · e 0.5 · hold 4h; C squeeze q 0.7 · e 0.5 · hold 12h; D best 2 hours · N 15m; D best 2 hours · N 30m; D best 4 hours · N 15m; D best 4 hours · N 30m; D weekend · N 15m; D weekend · N 60m; D weekdays · N 15m; D weekdays · N 60m; A drop k 5 · e 0.5 · hold 4h · survivorship-free twin; A drop k 5 · e 0.5 · hold 4h · one bar late; B EMA 24/96 · p 0.5 · W 1h · BTC gate · survivorship-free twin; B EMA 24/96 · p 0.5 · W 1h · BTC gate · one bar late; C squeeze q 0.5 · e 0.5 · hold 12h · survivorship-free twin; C squeeze q 0.5 · e 0.5 · hold 12h · one bar late; D weekdays · N 60m · survivorship-free twin; D weekdays · N 60m · one bar late; walk-forward pick by quarter.

## Check of the fill model against aggTrades (generated 2026-10-15)

1314 family A and C entry orders on BTC, DOGE, PEPE, WIF (5-minute bars). Bars and trades agree on 1288 (98 %); the bars fill where the trades do not in 24, the trades fill where the bars do not in 2.
