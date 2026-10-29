# RF1: does a forecast of tomorrow's range help the daily books as a filter?

Pre-registered in `results/range_forecast_rf1_prereg.md` (committed before the first run). Code:
`lab.experiments.range_forecast_rf1`, tests `tests/test_range_forecast_rf1.py`. Paper only: nothing a live bot, a
wallet or the engine reads changed.

Run 2026-10-29 as registered, the lockbox not read. 12 trials in R5's registry (hand family, counted without a
Sharpe; written to a copy in the agent run, the server's registry gets them from it). The leak check is clean.

## Reading

**Nothing passes, so Part B does not run and makes no number.** A range forecast does not earn a place as a filter,
and the friend's indicator does not do what it claims.

- **As forecasts, the models are good.** Every challenger beats all three baselines on QLIKE in both groups and in
  every year from 2018. HAR-PK is best on the coins: 14.5 % below the 20-day average and 9.0 % below EWMA 0.94 on
  validation, DM p 0.000. On the ETFs HAR-GK is 19 % and 16 % better. GARCH, the friend's model, is the weakest
  challenger: on the coins it does not beat EWMA 0.94 (p 0.18). CARR and the range-based HAR do better because they
  use the range, not only the close.
- **As the friend's "good day" call, they lose to doing nothing clever.** "Tomorrow is good if today was" is right
  64.5 % of the time on the coins' validation and 60.5 % on the ETFs'. The models score 57 to 62 % on the coins
  (GARCH 57.2 %) and 56 to 63 % on the ETFs (GARCH 55.7 %). Not one beats persistence with significance; on the
  ETFs HAR-PK and HAR-GK come closest (62.4 % and 62.6 %, p 0.06 and 0.05 against a bar of 0.0083). On the coins,
  always saying "not good" is right 61.1 % of the time, already better than GARCH.
- **Why.** A good day is TR above its 20-day average, and that happens on 39 % of coin days and 43 % of ETF days. A
  forecast of the expected range sits near that average and calls 55 to 62 % of coin days good. This is the
  pre-registered rule (one QLIKE scale, f > ATR20), not tuned afterwards. A threshold fitted to the call would be a
  new trial and a new study.
- **The 72 % on 32 days is luck-sized.** Its 95 % band is 53 % to 86 %. On validation, 19 % of the coins' 32-day
  windows (414 windows) and 11 % of the ETFs' (57) reach 72 % with GARCH, and persistence gets there in 29 % and
  12 %. Thirty-two days cannot tell the indicator from a coin flip with a lean.
- **Coverage.** The sector ETFs (XLK, XLF, XLV, XLE) have only closes in `<data>/etf/daily`, so they have no range
  and were dropped as registered. On the coins the true range and the high-low range differ only after a missing
  bar, so their tables are almost the same. A coin enters once it has a year of history, so PEPE only from 2024.

No paper book, no change to breakout_top10, W4's rules, the engine or a wallet. If the owner wants a range forecast
for anything, sizing is M6's question (its answer: the 30-day mean was best for the books). HAR-PK is the forecast
to use if another study needs one.

<!-- generated below by lab.experiments.range_forecast_rf1; edit above this line only -->

Generated 2026-10-29T21:11:40+00:00. Data to 2026-06-30 (rows from 2026-07-01 dropped at load); walk-forward by quarter from 2018, validation 2024-01-01 to 2026-06-30. Trials: hand:rf1:fc:GARCH:tr, hand:rf1:fc:GARCH:hl, hand:rf1:fc:CARR:tr, hand:rf1:fc:CARR:hl, hand:rf1:fc:HAR-PK:tr, hand:rf1:fc:HAR-PK:hl, hand:rf1:fc:HAR-GK:tr, hand:rf1:fc:HAR-GK:hl, hand:rf1:fc:HAR-RS:tr, hand:rf1:fc:HAR-RS:hl, hand:rf1:fc:HAR-YZ:tr, hand:rf1:fc:HAR-YZ:hl, .

The friend's claim, 72 % on 32 days (23 of 32): its 95 % binomial band is 53 % to 86 %.

Leak check (T1's harness on the TR forecasts of BTC and ETH, every value after four cuts shuffled or missing, and the data cut): no leak (12 runs).

## Part A, coins (AAVE, ADA, AVAX, BCH, BTC, DOGE, DOT, ETH, FIL, LINK, LTC, PEPE, SOL, UNI, XRP)

### Target true range (judged)

| model | qlike 2018-2023 | qlike validation | gain vs RW1 % | p vs RW1 | gain vs MA20 % | p vs MA20 | gain vs EWMA % | p vs EWMA | acc 2018-2023 | acc validation | p acc | good share validation | pass |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| GARCH | 0.144 | 0.131 | 24.735 | 0.000 | 8.082 | 0.001 | 2.192 | 0.175 | 0.537 | 0.572 | 1.000 | 0.623 | no |
| CARR | 0.129 | 0.123 | 29.084 | 0.000 | 13.393 | 0.000 | 7.844 | 0.001 | 0.595 | 0.613 | 1.000 | 0.567 | no |
| HAR-PK | 0.129 | 0.122 | 29.989 | 0.000 | 14.498 | 0.000 | 9.020 | 0.000 | 0.599 | 0.621 | 0.999 | 0.553 | no |
| HAR-GK | 0.131 | 0.124 | 28.735 | 0.000 | 12.966 | 0.000 | 7.390 | 0.000 | 0.596 | 0.617 | 0.999 | 0.557 | no |
| HAR-RS | 0.135 | 0.127 | 26.774 | 0.000 | 10.572 | 0.000 | 4.842 | 0.007 | 0.582 | 0.606 | 1.000 | 0.569 | no |
| HAR-YZ | 0.131 | 0.125 | 28.391 | 0.000 | 12.547 | 0.000 | 6.944 | 0.000 | 0.593 | 0.615 | 1.000 | 0.560 | no |
| RW1 | 0.178 | 0.174 | n/a | n/a | -22.126 | 1.000 | -29.951 | 1.000 | 0.602 | 0.614 | 1.000 | 0.529 | n/a |
| MA20 | 0.148 | 0.142 | 18.117 | 0.000 | n/a | n/a | -6.407 | 1.000 | 0.547 | 0.549 | 1.000 | 0.571 | n/a |
| EWMA | 0.140 | 0.134 | 23.048 | 0.000 | 6.021 | 0.000 | n/a | n/a | 0.582 | 0.598 | 1.000 | 0.538 | n/a |
| persistence | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | 0.642 | 0.645 | n/a | 0.392 | n/a |

Rows on validation: 13,483 asset-days. Good days that happened (TR above the 20-day average): 38.2 % in 2018-2023, 38.9 % on validation, so always saying "not good" is right 61.1 % of the time. p: one-sided DM (Newey-West, 10 lags) on the per-day mean over assets; the bar is 0.0083 (0.05 over 6).

QLIKE by year:

| model | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---|---|---|---|---|---|---|---|---|
| GARCH | 0.251 | 0.175 | 0.143 | 0.126 | 0.128 | 0.161 | 0.129 | 0.135 | 0.126 |
| CARR | 0.224 | 0.153 | 0.135 | 0.116 | 0.113 | 0.143 | 0.121 | 0.129 | 0.116 |
| HAR-PK | 0.222 | 0.150 | 0.132 | 0.116 | 0.114 | 0.143 | 0.120 | 0.128 | 0.114 |
| HAR-GK | 0.223 | 0.155 | 0.135 | 0.118 | 0.115 | 0.146 | 0.122 | 0.129 | 0.116 |
| HAR-RS | 0.225 | 0.160 | 0.139 | 0.122 | 0.118 | 0.150 | 0.126 | 0.132 | 0.120 |
| HAR-YZ | 0.220 | 0.154 | 0.135 | 0.119 | 0.115 | 0.147 | 0.123 | 0.130 | 0.117 |
| RW1 | 0.288 | 0.222 | 0.196 | 0.162 | 0.156 | 0.197 | 0.171 | 0.182 | 0.162 |
| MA20 | 0.283 | 0.182 | 0.161 | 0.133 | 0.136 | 0.156 | 0.141 | 0.151 | 0.127 |
| EWMA | 0.266 | 0.168 | 0.154 | 0.128 | 0.128 | 0.148 | 0.136 | 0.138 | 0.121 |

The friend's test on validation: 32-day windows (non-overlapping, per asset) with 72 % or more right: GARCH 19 % of 414 (5 % to 95 % of the windows' accuracy 34 to 78 %), persistence 29 % (47 to 81 %), MA20 14 %.

### Target high-low range (reported)

| model | qlike 2018-2023 | qlike validation | gain vs RW1 % | p vs RW1 | gain vs MA20 % | p vs MA20 | gain vs EWMA % | p vs EWMA | acc 2018-2023 | acc validation | p acc | good share validation |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| GARCH | 0.144 | 0.131 | 24.736 | 0.000 | 8.087 | 0.001 | 2.198 | 0.175 | 0.537 | 0.572 | 1.000 | 0.623 |
| CARR | 0.129 | 0.123 | 29.082 | 0.000 | 13.394 | 0.000 | 7.845 | 0.001 | 0.596 | 0.613 | 1.000 | 0.567 |
| HAR-PK | 0.129 | 0.122 | 29.989 | 0.000 | 14.502 | 0.000 | 9.023 | 0.000 | 0.599 | 0.621 | 0.998 | 0.552 |
| HAR-GK | 0.131 | 0.124 | 28.734 | 0.000 | 12.970 | 0.000 | 7.393 | 0.000 | 0.596 | 0.617 | 0.999 | 0.557 |
| HAR-RS | 0.134 | 0.127 | 26.774 | 0.000 | 10.576 | 0.000 | 4.846 | 0.007 | 0.582 | 0.607 | 1.000 | 0.569 |
| HAR-YZ | 0.131 | 0.125 | 28.391 | 0.000 | 12.551 | 0.000 | 6.947 | 0.000 | 0.593 | 0.615 | 1.000 | 0.560 |
| RW1 | 0.178 | 0.174 | n/a | n/a | -22.120 | 1.000 | -29.946 | 1.000 | 0.602 | 0.614 | 1.000 | 0.529 |
| MA20 | 0.148 | 0.142 | 18.113 | 0.000 | n/a | n/a | -6.408 | 1.000 | 0.547 | 0.549 | 1.000 | 0.571 |
| EWMA | 0.140 | 0.134 | 23.045 | 0.000 | 6.022 | 0.000 | n/a | n/a | 0.582 | 0.598 | 1.000 | 0.538 |
| persistence | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | 0.642 | 0.645 | n/a | 0.392 |

Rows on validation: 13,483 asset-days. Good days that happened (TR above the 20-day average): 38.2 % in 2018-2023, 38.9 % on validation, so always saying "not good" is right 61.1 % of the time. p: one-sided DM (Newey-West, 10 lags) on the per-day mean over assets; the bar is 0.0083 (0.05 over 6).

QLIKE by year:

| model | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---|---|---|---|---|---|---|---|---|
| GARCH | 0.251 | 0.175 | 0.142 | 0.126 | 0.128 | 0.161 | 0.129 | 0.135 | 0.126 |
| CARR | 0.224 | 0.153 | 0.135 | 0.116 | 0.113 | 0.143 | 0.121 | 0.129 | 0.116 |
| HAR-PK | 0.222 | 0.150 | 0.132 | 0.116 | 0.114 | 0.143 | 0.120 | 0.128 | 0.114 |
| HAR-GK | 0.223 | 0.155 | 0.135 | 0.118 | 0.115 | 0.146 | 0.122 | 0.129 | 0.116 |
| HAR-RS | 0.225 | 0.160 | 0.139 | 0.122 | 0.118 | 0.150 | 0.126 | 0.132 | 0.120 |
| HAR-YZ | 0.220 | 0.154 | 0.135 | 0.119 | 0.115 | 0.147 | 0.123 | 0.130 | 0.117 |
| RW1 | 0.288 | 0.222 | 0.195 | 0.162 | 0.156 | 0.197 | 0.171 | 0.182 | 0.162 |
| MA20 | 0.283 | 0.182 | 0.161 | 0.133 | 0.136 | 0.156 | 0.141 | 0.151 | 0.127 |
| EWMA | 0.266 | 0.168 | 0.154 | 0.128 | 0.128 | 0.148 | 0.136 | 0.138 | 0.121 |

The friend's test on validation: 32-day windows (non-overlapping, per asset) with 72 % or more right: GARCH 19 % of 414 (5 % to 95 % of the windows' accuracy 34 to 78 %), persistence 29 % (47 to 81 %), MA20 14 %.

**Part B forecast for coins:** none passes, so no Part B for this group.

## Part A, etfs (SPY, QQQ, IWM)

### Target true range (judged)

| model | qlike 2018-2023 | qlike validation | gain vs RW1 % | p vs RW1 | gain vs MA20 % | p vs MA20 | gain vs EWMA % | p vs EWMA | acc 2018-2023 | acc validation | p acc | good share validation | pass |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| GARCH | 0.099 | 0.105 | 25.327 | 0.000 | 8.501 | 0.017 | 5.425 | 0.074 | 0.598 | 0.557 | 0.991 | 0.496 | no |
| CARR | 0.087 | 0.095 | 32.604 | 0.000 | 17.418 | 0.000 | 14.642 | 0.002 | 0.641 | 0.588 | 0.883 | 0.529 | no |
| HAR-PK | 0.088 | 0.093 | 33.641 | 0.000 | 18.688 | 0.000 | 15.955 | 0.001 | 0.651 | 0.624 | 0.064 | 0.498 | no |
| HAR-GK | 0.087 | 0.093 | 33.956 | 0.000 | 19.074 | 0.000 | 16.353 | 0.000 | 0.647 | 0.626 | 0.054 | 0.507 | no |
| HAR-RS | 0.091 | 0.096 | 31.651 | 0.000 | 16.249 | 0.000 | 13.434 | 0.001 | 0.648 | 0.617 | 0.221 | 0.526 | no |
| HAR-YZ | 0.091 | 0.098 | 30.146 | 0.000 | 14.406 | 0.005 | 11.529 | 0.019 | 0.630 | 0.580 | 0.970 | 0.562 | no |
| RW1 | 0.129 | 0.141 | n/a | n/a | -22.533 | 0.997 | -26.652 | 0.999 | 0.588 | 0.576 | 0.999 | 0.568 | n/a |
| MA20 | 0.110 | 0.115 | 18.389 | 0.003 | n/a | n/a | -3.362 | 0.911 | 0.383 | 0.404 | 1.000 | 0.886 | n/a |
| EWMA | 0.107 | 0.111 | 21.044 | 0.001 | 3.252 | 0.089 | n/a | n/a | 0.509 | 0.515 | 1.000 | 0.609 | n/a |
| persistence | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | 0.612 | 0.605 | n/a | 0.433 | n/a |

Rows on validation: 1,872 asset-days. Good days that happened (TR above the 20-day average): 42.4 % in 2018-2023, 43.4 % on validation, so always saying "not good" is right 56.6 % of the time. p: one-sided DM (Newey-West, 10 lags) on the per-day mean over assets; the bar is 0.0083 (0.05 over 6).

QLIKE by year:

| model | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---|---|---|---|---|---|---|---|---|
| GARCH | 0.108 | 0.102 | 0.109 | 0.107 | 0.089 | 0.077 | 0.104 | 0.112 | 0.093 |
| CARR | 0.098 | 0.088 | 0.102 | 0.087 | 0.078 | 0.072 | 0.099 | 0.098 | 0.081 |
| HAR-PK | 0.099 | 0.084 | 0.109 | 0.083 | 0.082 | 0.071 | 0.099 | 0.092 | 0.084 |
| HAR-GK | 0.100 | 0.083 | 0.106 | 0.082 | 0.081 | 0.070 | 0.097 | 0.093 | 0.085 |
| HAR-RS | 0.107 | 0.086 | 0.112 | 0.085 | 0.084 | 0.071 | 0.099 | 0.098 | 0.086 |
| HAR-YZ | 0.103 | 0.090 | 0.107 | 0.087 | 0.087 | 0.073 | 0.104 | 0.100 | 0.084 |
| RW1 | 0.141 | 0.140 | 0.128 | 0.126 | 0.126 | 0.115 | 0.149 | 0.137 | 0.130 |
| MA20 | 0.125 | 0.121 | 0.145 | 0.114 | 0.081 | 0.075 | 0.113 | 0.130 | 0.088 |
| EWMA | 0.126 | 0.113 | 0.149 | 0.107 | 0.077 | 0.072 | 0.106 | 0.128 | 0.086 |

The friend's test on validation: 32-day windows (non-overlapping, per asset) with 72 % or more right: GARCH 11 % of 57 (5 % to 95 % of the windows' accuracy 38 to 76 %), persistence 12 % (44 to 75 %), MA20 0 %.

### Target high-low range (reported)

| model | qlike 2018-2023 | qlike validation | gain vs RW1 % | p vs RW1 | gain vs MA20 % | p vs MA20 | gain vs EWMA % | p vs EWMA | acc 2018-2023 | acc validation | p acc | good share validation |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| GARCH | 0.096 | 0.097 | 24.206 | 0.000 | 10.310 | 0.023 | 6.891 | 0.082 | 0.615 | 0.577 | 0.881 | 0.225 |
| CARR | 0.084 | 0.087 | 31.729 | 0.000 | 19.213 | 0.001 | 16.133 | 0.002 | 0.660 | 0.628 | 0.060 | 0.274 |
| HAR-PK | 0.086 | 0.089 | 30.749 | 0.000 | 18.052 | 0.002 | 14.928 | 0.006 | 0.656 | 0.632 | 0.021 | 0.280 |
| HAR-GK | 0.086 | 0.088 | 31.143 | 0.000 | 18.519 | 0.002 | 15.413 | 0.004 | 0.665 | 0.624 | 0.077 | 0.300 |
| HAR-RS | 0.090 | 0.091 | 29.246 | 0.000 | 16.274 | 0.002 | 13.082 | 0.006 | 0.658 | 0.623 | 0.121 | 0.301 |
| HAR-YZ | 0.090 | 0.092 | 28.060 | 0.000 | 14.871 | 0.015 | 11.625 | 0.039 | 0.639 | 0.606 | 0.467 | 0.348 |
| RW1 | 0.118 | 0.128 | n/a | n/a | -18.334 | 0.977 | -22.845 | 0.995 | 0.632 | 0.624 | 0.045 | 0.428 |
| MA20 | 0.107 | 0.108 | 15.493 | 0.023 | n/a | n/a | -3.812 | 0.936 | 0.560 | 0.560 | 0.943 | 0.018 |
| EWMA | 0.105 | 0.104 | 18.597 | 0.005 | 3.672 | 0.064 | n/a | n/a | 0.554 | 0.532 | 0.996 | 0.166 |
| persistence | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | 0.612 | 0.605 | n/a | 0.433 |

Rows on validation: 1,872 asset-days. Good days that happened (TR above the 20-day average): 42.4 % in 2018-2023, 43.4 % on validation, so always saying "not good" is right 56.6 % of the time. p: one-sided DM (Newey-West, 10 lags) on the per-day mean over assets; the bar is 0.0083 (0.05 over 6).

QLIKE by year:

| model | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---|---|---|---|---|---|---|---|---|
| GARCH | 0.115 | 0.100 | 0.101 | 0.099 | 0.088 | 0.074 | 0.091 | 0.106 | 0.091 |
| CARR | 0.099 | 0.084 | 0.097 | 0.078 | 0.076 | 0.068 | 0.087 | 0.090 | 0.083 |
| HAR-PK | 0.104 | 0.085 | 0.096 | 0.080 | 0.080 | 0.069 | 0.089 | 0.088 | 0.089 |
| HAR-GK | 0.106 | 0.085 | 0.095 | 0.080 | 0.081 | 0.069 | 0.087 | 0.088 | 0.090 |
| HAR-RS | 0.116 | 0.087 | 0.101 | 0.083 | 0.085 | 0.071 | 0.089 | 0.093 | 0.090 |
| HAR-YZ | 0.110 | 0.092 | 0.096 | 0.084 | 0.086 | 0.072 | 0.093 | 0.096 | 0.084 |
| RW1 | 0.131 | 0.124 | 0.112 | 0.110 | 0.119 | 0.110 | 0.135 | 0.119 | 0.134 |
| MA20 | 0.133 | 0.115 | 0.140 | 0.103 | 0.079 | 0.073 | 0.099 | 0.128 | 0.088 |
| EWMA | 0.134 | 0.109 | 0.143 | 0.098 | 0.075 | 0.068 | 0.093 | 0.124 | 0.087 |

The friend's test on validation: 32-day windows (non-overlapping, per asset) with 72 % or more right: GARCH 21 % of 57 (5 % to 95 % of the windows' accuracy 34 to 76 %), persistence 12 % (44 to 75 %), MA20 14 %.

**Part B forecast for etfs:** none passes, so no Part B for this group.
