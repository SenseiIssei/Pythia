# equities_ranking (M9)

Generated 2026-10-15T11:05:19+00:00. Point-in-time S&P 500, 1185 names ever in the index (dead ones included), data 1996-01-02 to 2026-10-13. Selection window 2010-01-01 to 2016-01-01 (walk-forward predictions), out of sample from 2016-01-01; median universe out of sample 502 names. Costs 5 bps per side (10 bps doubled). Weekly, filled at the next close. IR = Sharpe of the book's daily return minus the equal-weight index's.

## Benchmarks

| book | sel_sharpe | sharpe | cagr | vol | max_dd |
|---|---|---|---|---|---|
| SPY buy and hold | 0.846 | 0.884 | 0.151 | 0.177 | 0.337 |
| equal weight | 0.841 | 0.724 | 0.124 | 0.185 | 0.401 |

## Rank IC of M9 (Spearman, weekly decision days)

| model | sel_ic | sel_t | oos_ic | oos_t | oos_share_pos |
|---|---|---|---|---|---|
| h5_price | -0.009 | -0.951 | 0.006 | 0.895 | 0.501 |
| h5_full | -0.004 | -0.428 | 0.006 | 0.874 | 0.504 |
| h10_price | -0.006 | -0.653 | 0.013 | 1.700 | 0.516 |
| h10_full | -0.002 | -0.238 | 0.011 | 1.489 | 0.512 |
| h20_price | -0.014 | -1.443 | 0.015 | 1.879 | 0.509 |
| h20_full | -0.007 | -0.711 | 0.014 | 1.818 | 0.522 |

t uses one IC per week; with 10 and 20-day labels the weeks overlap, so those t are too high.

## Every trial

| name | sel_ir_5bps | oos_ir_5bps | oos_ir_10bps | oos_sharpe_5bps | oos_cagr | oos_max_dd | oos_active_yr | oos_turnover_yr | deflated_p |
|---|---|---|---|---|---|---|---|---|---|
| M9 h5 price top 20 | -0.368 | 0.411 | 0.245 | 0.669 | 0.177 | 0.551 | 0.080 | 66.339 | 0.288 |
| M9 h5 price top 20 buffer | -0.290 | 0.431 | 0.326 | 0.678 | 0.181 | 0.566 | 0.084 | 42.579 | 0.310 |
| M9 h5 price top 50 | -0.113 | 0.289 | 0.128 | 0.610 | 0.144 | 0.559 | 0.043 | 49.353 | 0.167 |
| M9 h5 price top 50 buffer | -0.033 | 0.418 | 0.351 | 0.671 | 0.167 | 0.560 | 0.065 | 22.215 | 0.295 |
| M9 h5 full top 20 | -0.218 | 0.370 | 0.226 | 0.627 | 0.166 | 0.579 | 0.076 | 60.317 | 0.243 |
| M9 h5 full top 20 buffer | -0.463 | 0.448 | 0.368 | 0.675 | 0.187 | 0.597 | 0.095 | 35.449 | 0.330 |
| M9 h5 full top 50 | -0.281 | 0.371 | 0.235 | 0.642 | 0.159 | 0.552 | 0.059 | 44.425 | 0.244 |
| M9 h5 full top 50 buffer | -0.323 | 0.426 | 0.375 | 0.668 | 0.170 | 0.543 | 0.070 | 18.309 | 0.304 |
| M9 h10 price top 20 | -0.587 | 0.179 | 0.014 | 0.521 | 0.123 | 0.618 | 0.034 | 63.129 | 0.093 |
| M9 h10 price top 20 buffer | -0.490 | 0.245 | 0.144 | 0.557 | 0.136 | 0.640 | 0.047 | 39.833 | 0.134 |
| M9 h10 price top 50 | -0.305 | 0.215 | 0.065 | 0.566 | 0.131 | 0.559 | 0.032 | 45.747 | 0.114 |
| M9 h10 price top 50 buffer | -0.361 | 0.307 | 0.246 | 0.609 | 0.146 | 0.530 | 0.047 | 19.934 | 0.182 |
| M9 h10 full top 20 | -0.021 | -0.038 | -0.186 | 0.392 | 0.077 | 0.636 | -0.007 | 57.540 | 0.021 |
| M9 h10 full top 20 buffer | -0.052 | 0.165 | 0.083 | 0.510 | 0.119 | 0.558 | 0.032 | 33.216 | 0.086 |
| M9 h10 full top 50 | -0.072 | 0.213 | 0.076 | 0.561 | 0.130 | 0.557 | 0.032 | 42.463 | 0.113 |
| M9 h10 full top 50 buffer | -0.049 | 0.342 | 0.290 | 0.623 | 0.152 | 0.541 | 0.053 | 17.516 | 0.215 |
| M9 h20 price top 20 | -0.493 | 0.300 | 0.153 | 0.591 | 0.150 | 0.631 | 0.059 | 59.273 | 0.177 |
| M9 h20 price top 20 buffer | -0.633 | 0.353 | 0.270 | 0.623 | 0.162 | 0.655 | 0.071 | 35.089 | 0.227 |
| M9 h20 price top 50 | -0.549 | 0.230 | 0.097 | 0.566 | 0.133 | 0.578 | 0.036 | 42.889 | 0.124 |
| M9 h20 price top 50 buffer | -0.475 | 0.416 | 0.365 | 0.662 | 0.168 | 0.578 | 0.068 | 18.235 | 0.293 |
| M9 h20 full top 20 | -0.022 | 0.351 | 0.225 | 0.612 | 0.162 | 0.576 | 0.073 | 53.815 | 0.224 |
| M9 h20 full top 20 buffer | -0.296 | 0.388 | 0.322 | 0.630 | 0.171 | 0.594 | 0.084 | 30.000 | 0.261 |
| M9 h20 full top 50 | -0.125 | 0.294 | 0.174 | 0.599 | 0.145 | 0.550 | 0.047 | 39.530 | 0.172 |
| M9 h20 full top 50 buffer | -0.131 | 0.371 | 0.327 | 0.634 | 0.159 | 0.570 | 0.061 | 15.586 | 0.243 |
| momentum 12-1 top 20 | 0.319 | 0.253 | 0.216 | 0.658 | 0.160 | 0.427 | 0.057 | 18.049 | 0.141 |
| momentum 12-1 top 20 buffer | 0.315 | 0.238 | 0.224 | 0.649 | 0.155 | 0.386 | 0.052 | 7.355 | 0.131 |
| momentum 12-1 top 50 | 0.356 | 0.201 | 0.150 | 0.719 | 0.147 | 0.360 | 0.030 | 16.377 | 0.107 |
| momentum 12-1 top 50 buffer | 0.118 | 0.114 | 0.099 | 0.657 | 0.132 | 0.378 | 0.017 | 5.973 | 0.063 |
| low volatility top 20 | -0.106 | -0.211 | -0.270 | 0.791 | 0.101 | 0.300 | -0.029 | 17.428 | 0.005 |
| low volatility top 20 buffer | -0.141 | -0.177 | -0.198 | 0.823 | 0.106 | 0.287 | -0.024 | 7.260 | 0.006 |
| low volatility top 50 | -0.200 | -0.247 | -0.298 | 0.762 | 0.099 | 0.322 | -0.030 | 13.850 | 0.003 |
| low volatility top 50 buffer | -0.039 | -0.167 | -0.180 | 0.834 | 0.110 | 0.330 | -0.020 | 4.638 | 0.007 |
| reversal 1m top 20 | -0.659 | 0.298 | 0.169 | 0.605 | 0.152 | 0.639 | 0.058 | 51.855 | 0.175 |
| reversal 1m top 20 buffer | -0.629 | 0.262 | 0.169 | 0.588 | 0.145 | 0.670 | 0.051 | 37.851 | 0.148 |
| reversal 1m top 50 | -0.421 | 0.331 | 0.169 | 0.658 | 0.153 | 0.568 | 0.046 | 46.792 | 0.204 |
| reversal 1m top 50 buffer | -0.352 | 0.377 | 0.266 | 0.689 | 0.160 | 0.573 | 0.051 | 31.480 | 0.251 |
| 52-week high top 20 | -0.552 | -0.495 | -0.745 | 0.388 | 0.051 | 0.315 | -0.071 | 73.815 | 0.000 |
| 52-week high top 20 buffer | -0.487 | -0.393 | -0.582 | 0.483 | 0.066 | 0.274 | -0.057 | 56.556 | 0.001 |
| 52-week high top 50 | -0.638 | -0.525 | -0.741 | 0.455 | 0.060 | 0.324 | -0.064 | 54.401 | 0.000 |
| 52-week high top 50 buffer | -0.305 | -0.410 | -0.518 | 0.553 | 0.075 | 0.319 | -0.050 | 27.565 | 0.001 |
| M9 h10 full top 20 · Monday | -0.411 | 0.237 | 0.092 | 0.545 | 0.133 | 0.600 | 0.046 | 58.234 | 0.129 |
| M9 h10 full top 20 · Tuesday | -0.107 | 0.194 | 0.052 | 0.523 | 0.126 | 0.598 | 0.038 | 57.607 | 0.101 |
| M9 h10 full top 20 · Wednesday | -0.335 | 0.249 | 0.106 | 0.556 | 0.137 | 0.615 | 0.049 | 57.507 | 0.137 |
| M9 h10 full top 20 · Thursday | -0.117 | 0.170 | 0.023 | 0.508 | 0.119 | 0.598 | 0.033 | 58.246 | 0.088 |
| M9 h10 full top 20 · filled a day late | -0.161 | 0.026 | -0.122 | 0.430 | 0.090 | 0.588 | 0.005 | 57.531 | 0.034 |

45 trials; the best of that many noise books would show an information ratio of about 0.58.

## M9 pick: M9 h10 full top 20

| book | sharpe | cagr | vol | max_dd | turnover_yr |
|---|---|---|---|---|---|
| M9 h10 full top 20 | 0.392 | 0.077 | 0.323 | 0.636 | 57.540 |

Block bootstrap (20 days, 5000 draws): Sharpe 90 % interval -0.08 to 0.88; Sharpe minus equal weight's -0.61 to -0.10, 1% above 0.

| year | book | equal_weight | active |
|---|---|---|---|
| 2016 | 0.219 | 0.157 | 0.062 |
| 2017 | -0.077 | 0.188 | -0.265 |
| 2018 | -0.278 | -0.075 | -0.204 |
| 2019 | 0.296 | 0.301 | -0.005 |
| 2020 | 0.056 | 0.129 | -0.073 |
| 2021 | 0.337 | 0.304 | 0.033 |
| 2022 | -0.349 | -0.111 | -0.238 |
| 2023 | 0.169 | 0.143 | 0.025 |
| 2024 | 0.058 | 0.130 | -0.071 |
| 2025 | 0.408 | 0.120 | 0.288 |
| 2026 | 0.320 | 0.119 | 0.201 |

- FAIL: deflated p of the active return > 0.95
- FAIL: OOS IR >= half the selection window's (> 0)
- FAIL: IR > 0 with costs doubled
- FAIL: Sharpe above SPY and equal weight
- FAIL: bootstrap: Sharpe above equal weight in >= 90 % of draws
- FAIL: active return positive in more than half the years

Verdict: does not pass the lab bar.

## baseline pick: momentum 12-1 top 50

| book | sharpe | cagr | vol | max_dd | turnover_yr |
|---|---|---|---|---|---|
| momentum 12-1 top 50 | 0.719 | 0.147 | 0.228 | 0.360 | 16.377 |

Block bootstrap (20 days, 5000 draws): Sharpe 90 % interval 0.29 to 1.17; Sharpe minus equal weight's -0.37 to 0.31, 48% above 0.

| year | book | equal_weight | active |
|---|---|---|---|
| 2016 | 0.028 | 0.157 | -0.128 |
| 2017 | 0.197 | 0.188 | 0.009 |
| 2018 | -0.101 | -0.075 | -0.026 |
| 2019 | 0.218 | 0.301 | -0.083 |
| 2020 | 0.151 | 0.129 | 0.022 |
| 2021 | 0.120 | 0.304 | -0.184 |
| 2022 | -0.012 | -0.111 | 0.100 |
| 2023 | 0.108 | 0.143 | -0.035 |
| 2024 | 0.300 | 0.130 | 0.171 |
| 2025 | 0.183 | 0.120 | 0.063 |
| 2026 | 0.498 | 0.119 | 0.379 |

- FAIL: deflated p of the active return > 0.95
- pass: OOS IR >= half the selection window's (> 0)
- pass: IR > 0 with costs doubled
- FAIL: Sharpe above SPY and equal weight
- FAIL: bootstrap: Sharpe above equal weight in >= 90 % of draws
- pass: active return positive in more than half the years

Verdict: does not pass the lab bar.

## What the M9 pick's model uses (share of gain, mean over yearly fits)

| feature | gain_share |
|---|---|
| vol_63 | 0.098 |
| size_dv63 | 0.069 |
| vol_trend | 0.066 |
| beta_252 | 0.060 |
| vol_21 | 0.059 |
| rev_5 | 0.053 |
| rev_5_rel | 0.053 |
| vol_63_rel | 0.049 |
| mom_12_1_rel | 0.048 |
| mom_126 | 0.047 |
| dist_52wh | 0.047 |
| mom_21 | 0.047 |
| dist_52wh_rel | 0.046 |
| mom_126_rel | 0.046 |
| mom_63 | 0.046 |
| mom_21_rel | 0.046 |
| mom_63_rel | 0.045 |
| mom_12_1 | 0.037 |
| mom_252 | 0.037 |
