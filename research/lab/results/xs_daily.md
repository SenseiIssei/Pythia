# M4 · Daily cross-sectional ranking

467,362 eligible coin-days out of sample from 2022, 584 coins (dead ones included), 51 features. Entry one hour after the features are known. Variant choice on 2022-2023, holdout from 2024 (1009 days). Costs 15 and 41 bps per unit of one-way turnover. Took 3 min.

Best signal: reg3 on 3-day returns, Rank-IC 0.148 (t 47.4).

- **long-only**, picked on 2022-2023: *reg1 top 10 of 100 liquid, hold 3d · regime*. Holdout 2024 on: Sharpe 0.04 at 15 bps (-12 % a year, drawdown 64 %), -0.36 at 41 bps; gross 0.28; turnover 84x a year; deflated p 0.00 over 100 variants. Does not pass.
- **long/short**, picked on 2022-2023: *rank3 10/10 of 100 liquid perps, hold 3d*. Holdout 2024 on: Sharpe 1.19 at 15 bps (43 % a year, drawdown 23 %), 0.33 at 41 bps; gross 1.68; turnover 117x a year; deflated p 0.03 over 100 variants. Does not pass.
- **long/short, funding-aware**, picked on 2022-2023: *reg7n 10/10 of 100 liquid perps, buffer 50 % (round 3)*. Holdout 2024 on: Sharpe 2.15 at 15 bps (91 % a year, drawdown 15 %), 2.00 at 41 bps; gross 2.23; turnover 18x a year; deflated p 0.39 over 100 variants. Does not pass.
- **slower long/short books (paper book)**, picked on 2022-2023: *rank3 10/10 of 100 liquid perps, hold 3d*. Holdout 2024 on: Sharpe 1.19 at 15 bps (43 % a year, drawdown 23 %), 0.33 at 41 bps; gross 1.68; turnover 117x a year; deflated p 0.03 over 100 variants. Does not pass.
- The 38 model long/short books held longer than one day: median holdout Sharpe 1.42 at 15 bps and 0.83 at 41 bps; 100 % and 100 % of them positive.
- The 18 funding-aware books: median holdout Sharpe 2.10 at 15 bps and 1.69 at 41 bps; 100 % and 100 % of them positive.

## Signal quality out of sample (Rank-IC per day, averaged)

| score | horizon_d | rank_ic | t_stat | rank_ic_top100_liquid |
|---|---|---|---|---|
| reg1 | 1 | 0.139 | 43.250 | 0.135 |
| reg1 | 3 | 0.145 | 46.741 | 0.150 |
| reg3 | 1 | 0.135 | 41.784 | 0.131 |
| reg3 | 3 | 0.148 | 47.398 | 0.153 |
| rank3 | 1 | 0.127 | 40.087 | 0.121 |
| rank3 | 3 | 0.139 | 46.348 | 0.144 |
| 1-day reversal | 1 | 0.050 | 13.880 | None |
| 1-day reversal | 3 | 0.039 | 11.176 | None |
| 28-day momentum | 1 | -0.046 | -11.805 | None |
| 28-day momentum | 3 | -0.045 | -11.401 | None |

## Round three: gross and funding-net labels (Rank-IC per day, net labels end 2026-09-28)

| score | horizon_d | rank_ic_gross | t_gross | rank_ic_net | t_net |
|---|---|---|---|---|---|
| reg3 | 3 | 0.148 | 47.398 | 0.143 | 45.505 |
| reg3 | 5 | 0.156 | 49.630 | 0.149 | 47.321 |
| reg3 | 7 | 0.160 | 51.199 | 0.153 | 48.755 |
| rank3 | 3 | 0.139 | 46.348 | 0.135 | 44.739 |
| rank3 | 5 | 0.146 | 48.430 | 0.141 | 46.498 |
| rank3 | 7 | 0.151 | 50.513 | 0.145 | 48.471 |
| reg3n | 3 | 0.146 | 47.019 | 0.144 | 45.895 |
| reg3n | 5 | 0.155 | 49.334 | 0.151 | 47.965 |
| reg3n | 7 | 0.159 | 51.179 | 0.155 | 49.755 |
| reg5n | 3 | 0.144 | 45.411 | 0.141 | 44.490 |
| reg5n | 5 | 0.153 | 48.085 | 0.150 | 46.922 |
| reg5n | 7 | 0.159 | 50.346 | 0.156 | 49.152 |
| reg7n | 3 | 0.139 | 43.528 | 0.137 | 42.737 |
| reg7n | 5 | 0.150 | 46.886 | 0.147 | 45.832 |
| reg7n | 7 | 0.157 | 49.377 | 0.154 | 48.297 |

## Round three against its twins in the same book (holdout Sharpe 15 / 41 bps; funding_sum = holdout funding P&L as a fraction of capital, negative = paid)

| funding-aware variant | sel_15 | hold_15 | hold_41 | turnover_yr | funding_sum | reg3 gross label hold_15 / 41 | reg3 funding_sum | low vol hold_15 / 41 |
|---|---|---|---|---|---|---|---|---|
| reg3n 10/10 of 50 liquid perps, hold 3d | 0.319 | 1.816 | 1.036 | 94.601 | -0.864 | 1.58 / 0.84 | -1.033 |  |
| reg3n 10/10 of 50 liquid perps, buffer 30 % | 0.637 | 1.336 | 0.722 | 87.996 | -0.923 | 1.29 / 0.73 | -1.067 |  |
| reg3n 10/10 of 50 liquid perps, buffer 50 % | 0.406 | 1.785 | 1.545 | 31.096 | -0.739 | 1.67 / 1.45 | -0.846 | 0.77 / 0.69 |
| reg3n 10/10 of 100 liquid perps, hold 3d | 0.748 | 1.715 | 0.806 | 124 | -1.000 | 1.48 / 0.62 | -1.295 |  |
| reg3n 10/10 of 100 liquid perps, buffer 30 % | 1.101 | 2.196 | 1.777 | 62.856 | -0.926 | 1.58 / 1.20 | -1.228 |  |
| reg3n 10/10 of 100 liquid perps, buffer 50 % | 0.563 | 2.712 | 2.474 | 29.716 | -0.713 | 2.67 / 2.46 | -0.891 | 1.87 / 1.80 |
| reg5n 10/10 of 50 liquid perps, hold 5d | 0.259 | 1.853 | 1.358 | 58.337 | -0.753 | 1.69 / 1.16 | -0.933 |  |
| reg5n 10/10 of 50 liquid perps, buffer 30 % | 0.941 | 1.614 | 1.113 | 68.954 | -0.866 | 1.29 / 0.73 | -1.067 |  |
| reg5n 10/10 of 50 liquid perps, buffer 50 % | 0.289 | 2.157 | 1.966 | 23.127 | -0.589 | 1.67 / 1.45 | -0.846 | 0.77 / 0.69 |
| reg5n 10/10 of 100 liquid perps, hold 5d | 0.802 | 2.057 | 1.486 | 74.152 | -0.813 | 1.89 / 1.27 | -1.141 |  |
| reg5n 10/10 of 100 liquid perps, buffer 30 % | 0.599 | 2.230 | 1.899 | 46.041 | -0.824 | 1.58 / 1.20 | -1.228 |  |
| reg5n 10/10 of 100 liquid perps, buffer 50 % | 0.552 | 2.397 | 2.225 | 21.404 | -0.550 | 2.67 / 2.46 | -0.891 | 1.87 / 1.80 |
| reg7n 10/10 of 50 liquid perps, hold 7d | 0.572 | 1.986 | 1.602 | 43.404 | -0.699 | 1.74 / 1.31 | -0.864 | 1.66 / 1.45 |
| reg7n 10/10 of 50 liquid perps, buffer 30 % | 0.880 | 1.350 | 0.944 | 58.453 | -0.853 | 1.29 / 0.73 | -1.067 |  |
| reg7n 10/10 of 50 liquid perps, buffer 50 % | 0.688 | 2.328 | 2.178 | 19.135 | -0.613 | 1.67 / 1.45 | -0.846 | 0.77 / 0.69 |
| reg7n 10/10 of 100 liquid perps, hold 7d | 0.782 | 2.326 | 1.884 | 54.310 | -0.742 | 1.91 / 1.43 | -1.015 | 1.65 / 1.45 |
| reg7n 10/10 of 100 liquid perps, buffer 30 % | 0.918 | 2.308 | 2.034 | 38.793 | -0.785 | 1.58 / 1.20 | -1.228 |  |
| reg7n 10/10 of 100 liquid perps, buffer 50 % | 1.126 | 2.148 | 2.002 | 18.293 | -0.616 | 2.67 / 2.46 | -0.891 | 1.87 / 1.80 |

## Funding data gap: holdout cut at the last day with complete funding (2026-09-28, 7 holdout days after it book no funding)

| variant | hold_sharpe_15bps | hold_sharpe_15bps_funded | hold_sharpe_41bps | hold_sharpe_41bps_funded |
|---|---|---|---|---|
| reg1 top 10 of 100 liquid, hold 3d · regime | 0.044 | 0.032 | -0.360 | -0.370 |
| rank3 10/10 of 100 liquid perps, hold 3d | 1.187 | 1.148 | 0.326 | 0.287 |
| reg7n 10/10 of 100 liquid perps, buffer 50 % (round 3) | 2.148 | 2.170 | 2.002 | 2.023 |
| low 28-day vol 10/10 of 100 liquid perps, hold 7d | 1.647 | 1.650 | 1.454 | 1.458 |
| low 28-day vol 10/10 of 100 liquid perps, buffer 50 % | 1.868 | 1.881 | 1.801 | 1.815 |

## Next-day return by reg1 decile (10 = best score), all eligible coins

| decile | mean_fwd1_bps | coin_days |
|---|---|---|
| 1 | -129 | 47517 |
| 2 | -37.571 | 46629 |
| 3 | -27.229 | 46799 |
| 4 | -18.504 | 46606 |
| 5 | -16.798 | 46448 |
| 6 | -13.324 | 47007 |
| 7 | -8.043 | 46766 |
| 8 | -9.381 | 46639 |
| 9 | -4.592 | 46789 |
| 10 | 5.383 | 45936 |

## Baselines

| baseline | sel_sharpe | hold_sharpe | hold_cagr | hold_max_dd |
|---|---|---|---|---|
| equal-weight 100 most liquid (daily rebalance, no costs) | -0.390 | -0.479 | -0.484 | 0.930 |
| BTC buy and hold | 0.226 | 0.736 | 0.263 | 0.531 |
| BTC with 200-day regime switch (no costs) | 1.311 | 0.833 | 0.260 | 0.289 |

## All 100 books (sel = 2022-2023, hold = 2024 on)

| family | variant | sel_sharpe_15bps | hold_sharpe_15bps | hold_sharpe_41bps | hold_gross_sharpe | hold_cagr_15bps | hold_max_dd_15bps | turnover_yr | deflated_p_15bps | deflated_p_41bps |
|---|---|---|---|---|---|---|---|---|---|---|
| baseline | M2 v2 score 10/10 of 50 liquid perps, buffer 50 % | 1.172 | 1.312 | 1.172 | 1.393 | 0.456 | 0.302 | 17.654 | 0.048 | 0.003 |
| baseline | M2 v2 score 10/10 of 100 liquid perps, buffer 50 % | 1.145 | 0.418 | 0.317 | 0.477 | 0.090 | 0.472 | 14.975 | 0.001 | 0.000 |
| baseline | M2 v2 score 10/10 of 50 liquid perps, hold 7d | 0.624 | 1.286 | 0.906 | 1.505 | 0.402 | 0.251 | 43.404 | 0.043 | 0.001 |
| baseline | M2 v2 score 10/10 of 100 liquid perps, hold 7d | 0.516 | 1.082 | 0.640 | 1.337 | 0.345 | 0.319 | 54.784 | 0.020 | 0.000 |
| baseline | 28-day momentum top 10 of 100 liquid, hold 3d · regime | 0.320 | -0.921 | -1.097 | -0.819 | -0.611 | 0.964 | 49.669 | 0.000 | 0.000 |
| baseline | low 28-day vol 10/10 of 50 liquid perps, buffer 50 % | 0.108 | 0.768 | 0.685 | 0.815 | 0.225 | 0.293 | 10.789 | 0.005 | 0.000 |
| baseline | low 28-day vol 10/10 of 50 liquid perps, hold 7d | 0.108 | 1.660 | 1.446 | 1.783 | 0.610 | 0.197 | 26.056 | 0.138 | 0.011 |
| baseline | low 28-day vol 10/10 of 100 liquid perps, buffer 50 % | 0.078 | 1.868 | 1.801 | 1.906 | 0.705 | 0.177 | 8.058 | 0.228 | 0.045 |
| baseline | low 28-day vol 10/10 of 100 liquid perps, hold 7d | 0.055 | 1.647 | 1.454 | 1.758 | 0.723 | 0.346 | 27.818 | 0.133 | 0.011 |
| baseline | 28-day momentum 10/10 of 50 liquid perps, hold 3d | -0.033 | -0.533 | -1.118 | -0.195 | -0.209 | 0.574 | 75.355 | 0.000 | 0.000 |
| baseline | 1-day reversal top 10 of 100 liquid, hold 3d · regime | -0.084 | -1.212 | -1.682 | -0.940 | -0.660 | 0.966 | 125 | 0.000 | 0.000 |
| baseline | 1-day reversal 10/10 of 50 liquid perps, hold 3d | -0.544 | -0.856 | -3.360 | 0.591 | -0.171 | 0.470 | 189 | 0.000 | 0.000 |
| baseline | 28-day momentum top 10 of 100 liquid, hold 3d | -0.680 | -1.626 | -1.841 | -1.501 | -0.852 | 0.997 | 75.771 | 0.000 | 0.000 |
| baseline | 1-day reversal top 10 of 100 liquid, hold 3d | -0.815 | -1.436 | -2.077 | -1.067 | -0.787 | 0.991 | 205 | 0.000 | 0.000 |
| long-only | reg1 top 10 of 100 liquid, hold 3d · regime | 0.896 | 0.044 | -0.360 | 0.276 | -0.118 | 0.639 | 84.134 | 0.000 | 0.000 |
| long-only | reg1 top 20 of 100 liquid, hold 3d · regime | 0.825 | -0.193 | -0.508 | -0.011 | -0.240 | 0.777 | 68.968 | 0.000 | 0.000 |
| long-only | reg1 top 10 of 100 liquid, hold 1d · regime | 0.811 | 0.125 | -0.859 | 0.693 | -0.083 | 0.583 | 211 | 0.000 | 0.000 |
| long-only | reg3 top 10 of 100 liquid, hold 3d · regime | 0.808 | 0.103 | -0.231 | 0.295 | -0.070 | 0.633 | 63.337 | 0.000 | 0.000 |
| long-only | reg3 top 20 of 100 liquid, hold 1d · regime | 0.802 | 0.136 | -0.447 | 0.471 | -0.075 | 0.647 | 123 | 0.000 | 0.000 |
| long-only | reg1 top 20 of 100 liquid, hold 1d · regime | 0.799 | -0.058 | -0.812 | 0.377 | -0.184 | 0.737 | 168 | 0.000 | 0.000 |
| long-only | reg3 top 20 of 100 liquid, hold 3d · regime | 0.797 | -0.033 | -0.294 | 0.118 | -0.156 | 0.706 | 55.036 | 0.000 | 0.000 |
| long-only | reg3 top 10 of 100 liquid, hold 1d · regime | 0.754 | 0.312 | -0.424 | 0.737 | 0.028 | 0.589 | 144 | 0.000 | 0.000 |
| long-only | rank3 top 20 of 100 liquid, hold 3d · regime | 0.745 | -0.019 | -0.215 | 0.094 | -0.139 | 0.678 | 39.509 | 0.000 | 0.000 |
| long-only | rank3 top 20 of 100 liquid, hold 1d · regime | 0.697 | 0.098 | -0.336 | 0.348 | -0.083 | 0.620 | 87.067 | 0.000 | 0.000 |
| long-only | rank3 top 10 of 100 liquid, hold 3d · regime | 0.688 | 0.218 | -0.046 | 0.370 | -0.007 | 0.552 | 46.810 | 0.000 | 0.000 |
| long-only | rank3 top 10 of 100 liquid, hold 1d · regime | 0.570 | 0.225 | -0.374 | 0.571 | -0.003 | 0.561 | 105 | 0.000 | 0.000 |
| long-only | reg3 top 10 of 100 liquid, hold 3d | -0.057 | 0.347 | -0.070 | 0.588 | 0.026 | 0.629 | 97.676 | 0.001 | 0.000 |
| long-only | reg1 top 10 of 100 liquid, hold 3d | -0.058 | 0.176 | -0.379 | 0.496 | -0.100 | 0.760 | 142 | 0.000 | 0.000 |
| long-only | reg3 top 20 of 100 liquid, hold 1d | -0.140 | 0.125 | -0.606 | 0.546 | -0.130 | 0.771 | 186 | 0.000 | 0.000 |
| long-only | reg1 top 10 of 100 liquid, hold 1d | -0.154 | -0.019 | -1.378 | 0.766 | -0.219 | 0.792 | 356 | 0.000 | 0.000 |
| long-only | reg1 top 20 of 100 liquid, hold 3d | -0.164 | -0.003 | -0.427 | 0.242 | -0.218 | 0.828 | 113 | 0.000 | 0.000 |
| long-only | reg3 top 20 of 100 liquid, hold 3d | -0.166 | 0.185 | -0.134 | 0.370 | -0.094 | 0.757 | 81.514 | 0.000 | 0.000 |
| long-only | reg1 top 20 of 100 liquid, hold 1d | -0.185 | -0.119 | -1.148 | 0.475 | -0.285 | 0.852 | 279 | 0.000 | 0.000 |
| long-only | reg3 top 10 of 100 liquid, hold 1d | -0.194 | 0.321 | -0.627 | 0.868 | 0.005 | 0.651 | 227 | 0.000 | 0.000 |
| long-only | rank3 top 10 of 100 liquid, hold 3d | -0.230 | 0.388 | 0.063 | 0.575 | 0.060 | 0.629 | 70.748 | 0.001 | 0.000 |
| long-only | rank3 top 20 of 100 liquid, hold 3d | -0.270 | 0.218 | -0.011 | 0.350 | -0.063 | 0.730 | 55.815 | 0.000 | 0.000 |
| long-only | rank3 top 20 of 100 liquid, hold 1d | -0.326 | 0.077 | -0.445 | 0.378 | -0.142 | 0.768 | 127 | 0.000 | 0.000 |
| long-only | rank3 top 10 of 100 liquid, hold 1d | -0.373 | 0.122 | -0.623 | 0.552 | -0.089 | 0.706 | 162 | 0.000 | 0.000 |
| long/short | rank3 10/10 of 100 liquid perps, hold 3d | 1.542 | 1.187 | 0.326 | 1.684 | 0.429 | 0.230 | 117 | 0.030 | 0.000 |
| long/short | reg3 10/10 of 100 liquid perps, buffer 30 % · no paying shorts (round 2) | 1.524 | 0.997 | 0.418 | 1.331 | 0.350 | 0.349 | 82.469 | 0.014 | 0.000 |
| long/short | rank3 10/10 of 100 liquid perps, hold 7d (round 2) | 1.515 | 1.749 | 1.245 | 2.039 | 0.620 | 0.232 | 58.535 | 0.173 | 0.004 |
| long/short | rank3 10/10 of 100 liquid perps, hold 7d · no paying shorts (round 2) | 1.503 | 1.061 | 0.519 | 1.373 | 0.285 | 0.284 | 56.567 | 0.018 | 0.000 |
| long/short | rank3 10/10 of 100 liquid perps, hold 5d (round 2) | 1.471 | 1.569 | 0.948 | 1.927 | 0.565 | 0.231 | 76.005 | 0.107 | 0.001 |
| long/short | rank3 10/10 of 100 liquid perps, hold 5d · no paying shorts (round 2) | 1.431 | 1.157 | 0.476 | 1.550 | 0.328 | 0.271 | 73.114 | 0.027 | 0.000 |
| long/short | reg3 10/10 of 100 liquid perps, hold 5d · no paying shorts (round 2) | 1.204 | 1.404 | 0.640 | 1.844 | 0.405 | 0.262 | 78.822 | 0.065 | 0.000 |
| long/short | rank3 10/10 of 100 liquid perps, hold 1d | 1.203 | 0.244 | -1.386 | 1.187 | 0.012 | 0.353 | 267 | 0.000 | 0.000 |
| long/short | rank3 10/10 of 100 liquid perps, buffer 30 % (round 2) | 1.197 | 1.550 | 1.238 | 1.730 | 0.701 | 0.347 | 47.074 | 0.101 | 0.004 |
| long/short | reg3 10/10 of 100 liquid perps, hold 7d · no paying shorts (round 2) | 1.144 | 1.352 | 0.741 | 1.704 | 0.371 | 0.268 | 60.630 | 0.055 | 0.000 |
| long/short | reg3 10/10 of 100 liquid perps, buffer 30 % (round 2) | 1.094 | 1.576 | 1.196 | 1.795 | 0.732 | 0.330 | 58.423 | 0.109 | 0.003 |
| long/short | rank3 10/10 of 100 liquid perps, buffer 30 % · no paying shorts (round 2) | 0.994 | 1.160 | 0.684 | 1.435 | 0.433 | 0.319 | 67.709 | 0.027 | 0.000 |
| long/short | reg3 10/10 of 100 liquid perps, buffer 50 % · no paying shorts (round 2) | 0.985 | 1.332 | 1.077 | 1.479 | 0.478 | 0.329 | 32.850 | 0.051 | 0.002 |
| long/short | rank3 10/10 of 50 liquid perps, buffer 30 % (round 2) | 0.971 | 1.902 | 1.361 | 2.213 | 0.774 | 0.287 | 68.629 | 0.245 | 0.008 |
| long/short | reg3 10/10 of 100 liquid perps, hold 7d (round 2) | 0.930 | 1.914 | 1.431 | 2.193 | 0.773 | 0.326 | 61.021 | 0.252 | 0.010 |
| long/short | rank3 10/10 of 100 liquid perps, buffer 50 % (round 2) | 0.925 | 2.037 | 1.884 | 2.125 | 0.840 | 0.247 | 19.243 | 0.321 | 0.060 |
| long/short | rank3 10/10 of 50 liquid perps, hold 3d | 0.822 | 1.655 | 0.924 | 2.076 | 0.587 | 0.257 | 86.564 | 0.136 | 0.001 |
| long/short | reg3 10/10 of 50 liquid perps, buffer 30 % · no paying shorts (round 2) | 0.809 | 0.928 | 0.021 | 1.452 | 0.282 | 0.373 | 113 | 0.011 | 0.000 |
| long/short | rank3 10/10 of 50 liquid perps, hold 5d · no paying shorts (round 2) | 0.799 | 1.112 | 0.539 | 1.443 | 0.287 | 0.248 | 56.515 | 0.023 | 0.000 |
| long/short | rank3 10/10 of 50 liquid perps, hold 5d (round 2) | 0.785 | 1.826 | 1.310 | 2.123 | 0.639 | 0.241 | 58.430 | 0.208 | 0.006 |
| long/short | reg3 10/10 of 100 liquid perps, hold 5d (round 2) | 0.785 | 1.887 | 1.268 | 2.244 | 0.770 | 0.310 | 79.023 | 0.238 | 0.005 |
| long/short | rank3 10/10 of 50 liquid perps, buffer 50 % (round 2) | 0.764 | 1.439 | 1.270 | 1.536 | 0.482 | 0.302 | 19.847 | 0.072 | 0.005 |
| long/short | reg3 10/10 of 100 liquid perps, hold 3d | 0.744 | 1.478 | 0.621 | 1.972 | 0.605 | 0.345 | 121 | 0.082 | 0.000 |
| long/short | reg3 10/10 of 50 liquid perps, buffer 30 % (round 2) | 0.741 | 1.292 | 0.728 | 1.618 | 0.510 | 0.391 | 81.103 | 0.044 | 0.000 |
| long/short | reg3 10/10 of 100 liquid perps, buffer 50 % (round 2) | 0.738 | 2.668 | 2.458 | 2.789 | 1.287 | 0.187 | 26.663 | 0.719 | 0.272 |
| long/short | rank3 10/10 of 50 liquid perps, hold 7d (round 2) | 0.677 | 1.894 | 1.472 | 2.137 | 0.644 | 0.248 | 46.031 | 0.241 | 0.012 |
| long/short | rank3 10/10 of 50 liquid perps, hold 7d · no paying shorts (round 2) | 0.674 | 1.167 | 0.701 | 1.436 | 0.300 | 0.251 | 45.174 | 0.028 | 0.000 |
| long/short | rank3 10/10 of 50 liquid perps, hold 1d | 0.633 | 0.728 | -0.719 | 1.563 | 0.210 | 0.263 | 191 | 0.004 | 0.000 |
| long/short | rank3 10/10 of 100 liquid perps, buffer 50 % · no paying shorts (round 2) | 0.614 | 1.003 | 0.818 | 1.110 | 0.324 | 0.372 | 24.017 | 0.015 | 0.000 |
| long/short | rank3 10/10 of 50 liquid perps, buffer 30 % · no paying shorts (round 2) | 0.559 | 1.099 | 0.332 | 1.542 | 0.341 | 0.302 | 91.802 | 0.022 | 0.000 |
| long/short | reg3 10/10 of 100 liquid perps, hold 1d | 0.539 | 1.006 | -0.699 | 1.992 | 0.393 | 0.303 | 274 | 0.015 | 0.000 |
| long/short | reg3 10/10 of 50 liquid perps, hold 5d · no paying shorts (round 2) | 0.536 | 1.312 | 0.655 | 1.691 | 0.346 | 0.239 | 63.346 | 0.048 | 0.000 |
| long/short | reg3 10/10 of 50 liquid perps, hold 7d · no paying shorts (round 2) | 0.479 | 1.341 | 0.815 | 1.645 | 0.347 | 0.235 | 49.428 | 0.053 | 0.000 |
| long/short | rank3 10/10 of 50 liquid perps, buffer 50 % · no paying shorts (round 2) | 0.461 | 1.111 | 0.873 | 1.247 | 0.328 | 0.329 | 26.861 | 0.023 | 0.001 |
| long/short | reg3 10/10 of 50 liquid perps, hold 1d | 0.444 | 0.833 | -0.641 | 1.684 | 0.261 | 0.312 | 201 | 0.007 | 0.000 |
| long/short | reg1 10/10 of 100 liquid perps, hold 3d | 0.420 | 1.247 | 0.159 | 1.874 | 0.457 | 0.354 | 147 | 0.038 | 0.000 |
| long/short | reg1 10/10 of 50 liquid perps, hold 1d | 0.419 | 0.553 | -1.444 | 1.708 | 0.142 | 0.349 | 273 | 0.002 | 0.000 |
| long/short | reg3 10/10 of 50 liquid perps, buffer 50 % · no paying shorts (round 2) | 0.418 | 1.128 | 0.819 | 1.306 | 0.375 | 0.391 | 39.284 | 0.024 | 0.000 |
| long/short | reg3 10/10 of 50 liquid perps, hold 3d | 0.345 | 1.580 | 0.839 | 2.008 | 0.573 | 0.267 | 90.958 | 0.111 | 0.000 |
| long/short | reg3 10/10 of 50 liquid perps, hold 5d (round 2) | 0.334 | 1.689 | 1.165 | 1.992 | 0.600 | 0.236 | 61.803 | 0.149 | 0.003 |
| long/short | reg3 10/10 of 50 liquid perps, hold 7d (round 2) | 0.318 | 1.744 | 1.315 | 1.992 | 0.596 | 0.229 | 48.377 | 0.171 | 0.006 |
| long/short | reg1 10/10 of 50 liquid perps, hold 3d | 0.255 | 1.511 | 0.560 | 2.060 | 0.521 | 0.257 | 113 | 0.090 | 0.000 |
| long/short | reg1 10/10 of 100 liquid perps, hold 1d | 0.202 | 0.475 | -1.807 | 1.793 | 0.115 | 0.384 | 365 | 0.001 | 0.000 |
| long/short | reg3 10/10 of 50 liquid perps, buffer 50 % (round 2) | 0.157 | 1.669 | 1.450 | 1.796 | 0.666 | 0.299 | 28.750 | 0.141 | 0.011 |
| long/short, funding-aware | reg7n 10/10 of 100 liquid perps, buffer 50 % (round 3) | 1.126 | 2.148 | 2.002 | 2.233 | 0.913 | 0.153 | 18.293 | 0.390 | 0.086 |
| long/short, funding-aware | reg3n 10/10 of 100 liquid perps, buffer 30 % (round 3) | 1.101 | 2.196 | 1.777 | 2.438 | 1.188 | 0.381 | 62.856 | 0.420 | 0.041 |
| long/short, funding-aware | reg5n 10/10 of 50 liquid perps, buffer 30 % (round 3) | 0.941 | 1.614 | 1.113 | 1.902 | 0.671 | 0.268 | 68.954 | 0.122 | 0.002 |
| long/short, funding-aware | reg7n 10/10 of 100 liquid perps, buffer 30 % (round 3) | 0.918 | 2.308 | 2.034 | 2.466 | 1.185 | 0.191 | 38.793 | 0.494 | 0.095 |
| long/short, funding-aware | reg7n 10/10 of 50 liquid perps, buffer 30 % (round 3) | 0.880 | 1.350 | 0.944 | 1.585 | 0.545 | 0.316 | 58.453 | 0.054 | 0.001 |
| long/short, funding-aware | reg5n 10/10 of 100 liquid perps, hold 5d (round 3) | 0.802 | 2.057 | 1.486 | 2.387 | 0.890 | 0.246 | 74.152 | 0.333 | 0.013 |
| long/short, funding-aware | reg7n 10/10 of 100 liquid perps, hold 7d (round 3) | 0.782 | 2.326 | 1.884 | 2.582 | 0.997 | 0.221 | 54.310 | 0.506 | 0.060 |
| long/short, funding-aware | reg3n 10/10 of 100 liquid perps, hold 3d (round 3) | 0.748 | 1.715 | 0.806 | 2.239 | 0.724 | 0.346 | 124 | 0.159 | 0.000 |
| long/short, funding-aware | reg7n 10/10 of 50 liquid perps, buffer 50 % (round 3) | 0.688 | 2.328 | 2.178 | 2.414 | 1.052 | 0.232 | 19.135 | 0.507 | 0.142 |
| long/short, funding-aware | reg3n 10/10 of 50 liquid perps, buffer 30 % (round 3) | 0.637 | 1.336 | 0.722 | 1.691 | 0.533 | 0.412 | 87.996 | 0.052 | 0.000 |
| long/short, funding-aware | reg5n 10/10 of 100 liquid perps, buffer 30 % (round 3) | 0.599 | 2.230 | 1.899 | 2.421 | 1.106 | 0.225 | 46.041 | 0.443 | 0.063 |
| long/short, funding-aware | reg7n 10/10 of 50 liquid perps, hold 7d (round 3) | 0.572 | 1.986 | 1.602 | 2.208 | 0.716 | 0.252 | 43.404 | 0.292 | 0.021 |
| long/short, funding-aware | reg3n 10/10 of 100 liquid perps, buffer 50 % (round 3) | 0.563 | 2.712 | 2.474 | 2.849 | 1.298 | 0.233 | 29.716 | 0.743 | 0.281 |
| long/short, funding-aware | reg5n 10/10 of 100 liquid perps, buffer 50 % (round 3) | 0.552 | 2.397 | 2.225 | 2.495 | 1.072 | 0.255 | 21.404 | 0.552 | 0.161 |
| long/short, funding-aware | reg3n 10/10 of 50 liquid perps, buffer 50 % (round 3) | 0.406 | 1.785 | 1.545 | 1.923 | 0.722 | 0.296 | 31.096 | 0.189 | 0.017 |
| long/short, funding-aware | reg3n 10/10 of 50 liquid perps, hold 3d (round 3) | 0.319 | 1.816 | 1.036 | 2.266 | 0.686 | 0.283 | 94.601 | 0.203 | 0.001 |
| long/short, funding-aware | reg5n 10/10 of 50 liquid perps, buffer 50 % (round 3) | 0.289 | 2.157 | 1.966 | 2.266 | 0.885 | 0.260 | 23.127 | 0.395 | 0.078 |
| long/short, funding-aware | reg5n 10/10 of 50 liquid perps, hold 5d (round 3) | 0.259 | 1.853 | 1.358 | 2.138 | 0.683 | 0.253 | 58.337 | 0.220 | 0.007 |

## The picks year by year (sums of daily contributions)

| pick | year | days | gross_sum | funding_sum | cost_sum_15bps | sharpe_15bps | sharpe_41bps |
|---|---|---|---|---|---|---|---|
| reg1 top 10 of 100 liquid, hold 3d · regime | 2022 | 365 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| reg1 top 10 of 100 liquid, hold 3d · regime | 2023 | 365 | 0.706 | 0.000 | 0.134 | 1.268 | 0.751 |
| reg1 top 10 of 100 liquid, hold 3d · regime | 2024 | 366 | 0.427 | 0.000 | 0.175 | 0.398 | -0.082 |
| reg1 top 10 of 100 liquid, hold 3d · regime | 2025 | 365 | -0.294 | 0.000 | 0.151 | -0.720 | -1.142 |
| reg1 top 10 of 100 liquid, hold 3d · regime | 2026 | 278 | 0.281 | 0.000 | 0.023 | 1.704 | 1.449 |
| rank3 10/10 of 100 liquid perps, hold 3d | 2022 | 365 | 0.789 | -0.007 | 0.193 | 2.443 | 1.052 |
| rank3 10/10 of 100 liquid perps, hold 3d | 2023 | 365 | 0.469 | -0.078 | 0.176 | 0.772 | -0.326 |
| rank3 10/10 of 100 liquid perps, hold 3d | 2024 | 366 | 0.451 | -0.026 | 0.181 | 0.851 | -0.246 |
| rank3 10/10 of 100 liquid perps, hold 3d | 2025 | 365 | 1.235 | -0.386 | 0.173 | 1.855 | 1.034 |
| rank3 10/10 of 100 liquid perps, hold 3d | 2026 | 278 | 0.987 | -0.613 | 0.132 | 0.764 | 0.039 |
| reg7n 10/10 of 100 liquid perps, buffer 50 % (round 3) | 2022 | 365 | 0.646 | 0.001 | 0.048 | 2.214 | 1.906 |
| reg7n 10/10 of 100 liquid perps, buffer 50 % (round 3) | 2023 | 365 | 0.189 | -0.092 | 0.021 | 0.233 | 0.120 |
| reg7n 10/10 of 100 liquid perps, buffer 50 % (round 3) | 2024 | 366 | 0.598 | 0.012 | 0.036 | 1.880 | 1.674 |
| reg7n 10/10 of 100 liquid perps, buffer 50 % (round 3) | 2025 | 365 | 1.109 | -0.238 | 0.023 | 2.557 | 2.433 |
| reg7n 10/10 of 100 liquid perps, buffer 50 % (round 3) | 2026 | 278 | 0.928 | -0.390 | 0.016 | 1.960 | 1.852 |

## Walk-forward folds

| model | fold | ic_oos | ic_is_last180d |
|---|---|---|---|
| reg1 | 2022Q1 | 0.175 | 0.263 |
| reg1 | 2022Q2 | 0.151 | 0.273 |
| reg1 | 2022Q3 | 0.178 | 0.280 |
| reg1 | 2022Q4 | 0.155 | 0.274 |
| reg1 | 2023Q1 | 0.135 | 0.253 |
| reg1 | 2023Q2 | 0.162 | 0.223 |
| reg1 | 2023Q3 | 0.131 | 0.226 |
| reg1 | 2023Q4 | 0.136 | 0.216 |
| reg1 | 2024Q1 | 0.156 | 0.196 |
| reg1 | 2024Q2 | 0.104 | 0.204 |
| reg1 | 2024Q3 | 0.117 | 0.191 |
| reg1 | 2024Q4 | 0.153 | 0.175 |
| reg1 | 2025Q1 | 0.113 | 0.191 |
| reg1 | 2025Q2 | 0.114 | 0.196 |
| reg1 | 2025Q3 | 0.163 | 0.178 |
| reg1 | 2025Q4 | 0.125 | 0.193 |
| reg1 | 2026Q1 | 0.114 | 0.190 |
| reg1 | 2026Q2 | 0.128 | 0.167 |
| reg1 | 2026Q3 | 0.135 | 0.162 |
| reg1 | 2026Q4 | 0.151 | 0.165 |
| reg3 | 2022Q1 | 0.189 | 0.303 |
| reg3 | 2022Q2 | 0.147 | 0.325 |
| reg3 | 2022Q3 | 0.185 | 0.335 |
| reg3 | 2022Q4 | 0.155 | 0.318 |
| reg3 | 2023Q1 | 0.117 | 0.296 |
| reg3 | 2023Q2 | 0.163 | 0.252 |
| reg3 | 2023Q3 | 0.119 | 0.254 |
| reg3 | 2023Q4 | 0.128 | 0.241 |
| reg3 | 2024Q1 | 0.148 | 0.217 |
| reg3 | 2024Q2 | 0.113 | 0.225 |
| reg3 | 2024Q3 | 0.148 | 0.220 |
| reg3 | 2024Q4 | 0.165 | 0.228 |
| reg3 | 2025Q1 | 0.140 | 0.235 |
| reg3 | 2025Q2 | 0.135 | 0.247 |
| reg3 | 2025Q3 | 0.163 | 0.231 |
| reg3 | 2025Q4 | 0.140 | 0.220 |
| reg3 | 2026Q1 | 0.131 | 0.218 |
| reg3 | 2026Q2 | 0.159 | 0.204 |
| reg3 | 2026Q3 | 0.162 | 0.199 |
| reg3 | 2026Q4 | 0.065 | 0.205 |
| rank3 | 2022Q1 | 0.181 | 0.214 |
| rank3 | 2022Q2 | 0.125 | 0.228 |
| rank3 | 2022Q3 | 0.157 | 0.226 |
| rank3 | 2022Q4 | 0.151 | 0.218 |
| rank3 | 2023Q1 | 0.117 | 0.211 |
| rank3 | 2023Q2 | 0.150 | 0.187 |
| rank3 | 2023Q3 | 0.108 | 0.194 |
| rank3 | 2023Q4 | 0.128 | 0.179 |
| rank3 | 2024Q1 | 0.134 | 0.159 |
| rank3 | 2024Q2 | 0.120 | 0.164 |
| rank3 | 2024Q3 | 0.130 | 0.155 |
| rank3 | 2024Q4 | 0.154 | 0.161 |
| rank3 | 2025Q1 | 0.143 | 0.173 |
| rank3 | 2025Q2 | 0.117 | 0.182 |
| rank3 | 2025Q3 | 0.152 | 0.165 |
| rank3 | 2025Q4 | 0.147 | 0.160 |
| rank3 | 2026Q1 | 0.131 | 0.173 |
| rank3 | 2026Q2 | 0.144 | 0.166 |
| rank3 | 2026Q3 | 0.153 | 0.165 |
| rank3 | 2026Q4 | 0.063 | 0.177 |
| reg3n | 2022Q1 | 0.188 | 0.301 |
| reg3n | 2022Q2 | 0.150 | 0.324 |
| reg3n | 2022Q3 | 0.186 | 0.332 |
| reg3n | 2022Q4 | 0.154 | 0.319 |
| reg3n | 2023Q1 | 0.115 | 0.293 |
| reg3n | 2023Q2 | 0.159 | 0.250 |
| reg3n | 2023Q3 | 0.112 | 0.253 |
| reg3n | 2023Q4 | 0.128 | 0.237 |
| reg3n | 2024Q1 | 0.151 | 0.216 |
| reg3n | 2024Q2 | 0.113 | 0.225 |
| reg3n | 2024Q3 | 0.149 | 0.223 |
| reg3n | 2024Q4 | 0.166 | 0.226 |
| reg3n | 2025Q1 | 0.143 | 0.236 |
| reg3n | 2025Q2 | 0.127 | 0.245 |
| reg3n | 2025Q3 | 0.152 | 0.224 |
| reg3n | 2025Q4 | 0.132 | 0.212 |
| reg3n | 2026Q1 | 0.116 | 0.210 |
| reg3n | 2026Q2 | 0.144 | 0.195 |
| reg3n | 2026Q3 | 0.143 | 0.189 |
| reg3n | 2026Q4 | None | 0.192 |
| reg5n | 2022Q1 | 0.186 | 0.326 |
| reg5n | 2022Q2 | 0.157 | 0.349 |
| reg5n | 2022Q3 | 0.191 | 0.368 |
| reg5n | 2022Q4 | 0.156 | 0.350 |
| reg5n | 2023Q1 | 0.095 | 0.319 |
| reg5n | 2023Q2 | 0.172 | 0.280 |
| reg5n | 2023Q3 | 0.116 | 0.281 |
| reg5n | 2023Q4 | 0.122 | 0.273 |
| reg5n | 2024Q1 | 0.146 | 0.246 |
| reg5n | 2024Q2 | 0.123 | 0.242 |
| reg5n | 2024Q3 | 0.155 | 0.246 |
| reg5n | 2024Q4 | 0.183 | 0.261 |
| reg5n | 2025Q1 | 0.153 | 0.267 |
| reg5n | 2025Q2 | 0.161 | 0.286 |
| reg5n | 2025Q3 | 0.153 | 0.270 |
| reg5n | 2025Q4 | 0.147 | 0.242 |
| reg5n | 2026Q1 | 0.133 | 0.232 |
| reg5n | 2026Q2 | 0.145 | 0.221 |
| reg5n | 2026Q3 | 0.152 | 0.209 |
| reg5n | 2026Q4 | None | 0.210 |
| reg7n | 2022Q1 | 0.190 | 0.350 |
| reg7n | 2022Q2 | 0.168 | 0.378 |
| reg7n | 2022Q3 | 0.193 | 0.406 |
| reg7n | 2022Q4 | 0.163 | 0.382 |
| reg7n | 2023Q1 | 0.090 | 0.343 |
| reg7n | 2023Q2 | 0.179 | 0.300 |
| reg7n | 2023Q3 | 0.119 | 0.301 |
| reg7n | 2023Q4 | 0.118 | 0.304 |
| reg7n | 2024Q1 | 0.135 | 0.269 |
| reg7n | 2024Q2 | 0.125 | 0.258 |
| reg7n | 2024Q3 | 0.168 | 0.264 |
| reg7n | 2024Q4 | 0.189 | 0.287 |
| reg7n | 2025Q1 | 0.154 | 0.292 |
| reg7n | 2025Q2 | 0.172 | 0.303 |
| reg7n | 2025Q3 | 0.158 | 0.291 |
| reg7n | 2025Q4 | 0.152 | 0.259 |
| reg7n | 2026Q1 | 0.145 | 0.247 |
| reg7n | 2026Q2 | 0.140 | 0.236 |
| reg7n | 2026Q3 | 0.173 | 0.227 |
| reg7n | 2026Q4 | None | 0.231 |
