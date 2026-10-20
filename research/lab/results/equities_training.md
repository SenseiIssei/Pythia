# X16 equities training

<!-- generated below by lab.experiments.equities_training; edit above this line only -->

## Results (generated 2026-10-20, data 1996-01-02 to 2026-10-16)
Point-in-time S&P 500, 1228 names ever in the index from 1996; ETFs SPY, XLB, XLC, XLE, XLF, XLI, XLK, XLP, XLRE, XLU, XLV, XLY. EDGAR: 628 companies, 67474 earnings events, 64769 reaction windows. Selection 2000 to 2015 (PEAD 2005 to 2015), out of sample from 2016-01-01. Costs 5 bps a side for stocks, 2 for ETFs, plus the SEC fee on sells; next-open fills.
Pool: 1668 trials (948 hand, 600 factory, 93 equity trials here, 27 crypto trials of B2 in `exit_overlays.md`); the best noise trial sits at an annual Sharpe of about 2.19 on trading days (2.64 on calendar days).
### Benchmarks
| benchmark | Sharpe 2000-15 | Sharpe OOS | CAGR | max DD | alpha vs SPY |
|---|---|---|---|---|---|
| SPY | 0.29 | 0.92 | 15.2 % | 32.0 % | 0.0 % |
| equal weight | 0.52 | 0.75 | 12.3 % | 37.7 % | -1.7 % |
| equal weight, CIK members | 0.57 | 0.78 | 12.7 % | 37.8 % | -1.3 % |
| equal-weight sectors | 0.39 | 0.85 | 12.9 % | 34.1 % | -0.4 % |

### Part A: the family picks
**A1: A1 breakout 55d, volume 2.5x, time 40, regime** (fails). Selection Sharpe 0.73, out of sample 0.48 (doubled costs 0.45), CAGR 6.2 %, drawdown 24.6 %, alpha -2.8 % (beta 0.63), exposure 82.2 %, turnover 10.4 a year, 2905 trades, fills at the close 0.0 %. A day late: Sharpe 0.43, alpha -3.5 %. Benchmarks: SPY 0.92, equal weight 0.75. Bootstrap: Sharpe minus SPY's -0.80 to -0.08, 2.1 % above 0. Deflated p: pool 0.000, this study's 57 0.242.
Failed: 1 Sharpe above SPY and equal weight, 3 alpha > 0 at doubled costs, 4 a day late, alpha > 0, 5 bootstrap: Sharpe above SPY's in >= 90 %, 6 alpha positive in more than half the years, 7 deflated p > 0.95 over the pool.
| year | book | SPY | alpha | beta | Sharpe |
|---|---|---|---|---|---|
| 2016 | 8.4 % | 14.7 % | 1.5 % | 0.49 | 0.84 |
| 2017 | 10.9 % | 21.3 % | -8.4 % | 0.97 | 1.38 |
| 2018 | -3.6 % | -6.4 % | 1.3 % | 0.76 | -0.17 |
| 2019 | 10.6 % | 34.0 % | -11.5 % | 0.74 | 1.04 |
| 2020 | 0.0 % | 18.2 % | -11.9 % | 0.73 | 0.13 |
| 2021 | 19.2 % | 28.6 % | -8.0 % | 1.04 | 1.18 |
| 2022 | -15.7 % | -18.0 % | -12.0 % | 0.27 | -1.55 |
| 2023 | 5.3 % | 24.7 % | -13.1 % | 0.83 | 0.44 |
| 2024 | 13.3 % | 26.4 % | -7.4 % | 0.86 | 1.00 |
| 2025 | 3.7 % | 17.7 % | -4.9 % | 0.53 | 0.32 |
| 2026 | 20.1 % | 13.6 % | 13.3 % | 0.68 | 1.39 |
**A2: A2 gap 2%, time 20** (fails). Selection Sharpe 0.59, out of sample 0.38 (doubled costs 0.33), CAGR 5.5 %, drawdown 43.9 %, alpha -5.9 % (beta 0.84), exposure 77.1 %, turnover 19.5 a year, 5861 trades, fills at the close 0.0 %. A day late: Sharpe 0.49, alpha -4.1 %. Benchmarks: SPY 0.92, equal weight 0.75. Bootstrap: Sharpe minus SPY's -0.87 to -0.20, 0.6 % above 0. Deflated p: pool 0.000, this study's 57 0.152.
Failed: 1 Sharpe above SPY and equal weight, 3 alpha > 0 at doubled costs, 4 a day late, alpha > 0, 5 bootstrap: Sharpe above SPY's in >= 90 %, 6 alpha positive in more than half the years, 7 deflated p > 0.95 over the pool.
| year | book | SPY | alpha | beta | Sharpe |
|---|---|---|---|---|---|
| 2016 | 9.5 % | 14.7 % | -3.4 % | 0.96 | 0.64 |
| 2017 | 10.2 % | 21.3 % | -5.3 % | 0.78 | 1.42 |
| 2018 | -19.3 % | -6.4 % | -16.4 % | 0.76 | -1.35 |
| 2019 | 15.7 % | 34.0 % | -11.0 % | 0.88 | 1.28 |
| 2020 | -24.4 % | 18.2 % | -43.0 % | 1.10 | -0.50 |
| 2021 | 11.9 % | 28.6 % | -11.7 % | 0.93 | 0.80 |
| 2022 | 9.7 % | -18.0 % | 22.0 % | 0.65 | 0.59 |
| 2023 | 10.7 % | 24.7 % | -6.5 % | 0.76 | 0.85 |
| 2024 | 19.3 % | 26.4 % | -1.9 % | 0.85 | 1.33 |
| 2025 | 23.0 % | 17.7 % | 11.1 % | 0.60 | 1.33 |
| 2026 | 5.4 % | 13.6 % | -5.7 % | 0.83 | 0.44 |
**A3: A3 PEAD z 1, volume 2x, time 20** (fails). Selection Sharpe 0.72, out of sample 0.54 (doubled costs 0.48), CAGR 5.9 %, drawdown 36.5 %, alpha -1.8 % (beta 0.53), exposure 58.7 %, turnover 14.8 a year, 3252 trades, fills at the close 0.0 %. A day late: Sharpe 0.50, alpha -2.4 %. Benchmarks: SPY 0.92, equal weight 0.75, equal weight, CIK members 0.78. Bootstrap: Sharpe minus SPY's -0.74 to -0.01, 4.5 % above 0. Deflated p: pool 0.000, this study's 57 0.311.
Failed: 1 Sharpe above SPY and equal weight, 3 alpha > 0 at doubled costs, 4 a day late, alpha > 0, 5 bootstrap: Sharpe above SPY's in >= 90 %, 6 alpha positive in more than half the years, 7 deflated p > 0.95 over the pool.
| year | book | SPY | alpha | beta | Sharpe |
|---|---|---|---|---|---|
| 2016 | 1.5 % | 14.7 % | -6.6 % | 0.60 | 0.20 |
| 2017 | 9.2 % | 21.3 % | -5.5 % | 0.74 | 1.36 |
| 2018 | -4.4 % | -6.4 % | -0.7 % | 0.60 | -0.29 |
| 2019 | 19.1 % | 34.0 % | -1.1 % | 0.64 | 1.96 |
| 2020 | -10.3 % | 18.2 % | -21.6 % | 0.64 | -0.35 |
| 2021 | 14.0 % | 28.6 % | 0.1 % | 0.52 | 1.56 |
| 2022 | 0.1 % | -18.0 % | 9.3 % | 0.48 | 0.08 |
| 2023 | 10.6 % | 24.7 % | -1.7 % | 0.53 | 1.14 |
| 2024 | 20.5 % | 26.4 % | 4.9 % | 0.59 | 1.85 |
| 2025 | 3.0 % | 17.7 % | -2.0 % | 0.29 | 0.37 |
| 2026 | 5.0 % | 13.6 % | 0.6 % | 0.35 | 0.72 |
**A4: A4 52-week high top 50, regime** (fails). Selection Sharpe 0.87, out of sample 0.44 (doubled costs 0.38), CAGR 4.7 %, drawdown 21.9 %, alpha -1.2 % (beta 0.42), exposure 82.1 %, turnover 15.6 a year, 10522 trades, fills at the close 11.7 %. A day late: Sharpe 0.43, alpha -1.4 %. Benchmarks: SPY 0.92, equal weight 0.75. Bootstrap: Sharpe minus SPY's -0.92 to -0.09, 2.2 % above 0. Deflated p: pool 0.000, this study's 57 0.203.
Failed: 1 Sharpe above SPY and equal weight, 3 alpha > 0 at doubled costs, 4 a day late, alpha > 0, 5 bootstrap: Sharpe above SPY's in >= 90 %, 6 alpha positive in more than half the years, 7 deflated p > 0.95 over the pool.
| year | book | SPY | alpha | beta | Sharpe |
|---|---|---|---|---|---|
| 2016 | 0.9 % | 14.7 % | -4.7 % | 0.42 | 0.14 |
| 2017 | 11.1 % | 21.3 % | -6.3 % | 0.87 | 1.54 |
| 2018 | -7.0 % | -6.4 % | -2.3 % | 0.74 | -0.41 |
| 2019 | 4.4 % | 34.0 % | -12.2 % | 0.56 | 0.53 |
| 2020 | 9.7 % | 18.2 % | 3.7 % | 0.33 | 0.63 |
| 2021 | 25.6 % | 28.6 % | -0.2 % | 0.92 | 1.72 |
| 2022 | -11.2 % | -18.0 % | -9.5 % | 0.12 | -1.38 |
| 2023 | -5.4 % | 24.7 % | -21.6 % | 0.72 | -0.38 |
| 2024 | 19.3 % | 26.4 % | 0.9 % | 0.72 | 1.57 |
| 2025 | 7.5 % | 17.7 % | 3.6 % | 0.23 | 0.69 |
| 2026 | 1.5 % | 13.6 % | -5.9 % | 0.51 | 0.20 |
**A5: A5 sectors 126d top 3, regime** (fails). Selection Sharpe 0.70, out of sample 0.59 (doubled costs 0.58), CAGR 7.3 %, drawdown 23.3 %, alpha 0.3 % (beta 0.50), exposure 82.3 %, turnover 7.5 a year, 257 trades, fills at the close 0.0 %. A day late: Sharpe 0.58, alpha 0.2 %. Benchmarks: SPY 0.92, equal-weight sectors 0.85. Bootstrap: Sharpe minus SPY's -0.76 to 0.04, 7.5 % above 0. Deflated p: pool 0.000, this study's 57 0.361.
Failed: 1 Sharpe above SPY and equal weight, 5 bootstrap: Sharpe above SPY's in >= 90 %, 6 alpha positive in more than half the years, 7 deflated p > 0.95 over the pool.
| year | book | SPY | alpha | beta | Sharpe |
|---|---|---|---|---|---|
| 2016 | 16.1 % | 14.7 % | 9.8 % | 0.39 | 1.62 |
| 2017 | 13.8 % | 21.3 % | -9.4 % | 1.16 | 1.57 |
| 2018 | -6.7 % | -6.4 % | -1.2 % | 0.84 | -0.33 |
| 2019 | 2.1 % | 34.0 % | -14.7 % | 0.58 | 0.26 |
| 2020 | 19.7 % | 18.2 % | 11.0 % | 0.43 | 0.98 |
| 2021 | 19.9 % | 28.6 % | -8.2 % | 1.08 | 1.13 |
| 2022 | -10.6 % | -18.0 % | -8.0 % | 0.17 | -1.10 |
| 2023 | 1.7 % | 24.7 % | -19.4 % | 0.97 | 0.19 |
| 2024 | 15.7 % | 26.4 % | -2.3 % | 0.73 | 1.27 |
| 2025 | 6.8 % | 17.7 % | 1.2 % | 0.34 | 0.58 |
| 2026 | 5.5 % | 13.6 % | 1.5 % | 0.35 | 0.68 |

### Part A: every trial
| variant | sel | OOS | OOS 2x | CAGR | max DD | alpha | beta | exposure | turnover/yr | trades | defl. p pool | defl. p 57 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A1 breakout 20d, volume 1.5x, time 10 | 0.33 | 0.26 | 0.11 | 2.9 % | 28.4 % | -7.2 % | 0.74 | 94.5 % | 47.87 | 14256 | 0.000 | 0.075 |
| A1 breakout 20d, volume 1.5x, time 10, regime | 0.48 | 0.30 | 0.15 | 3.3 % | 25.3 % | -3.6 % | 0.51 | 82.7 % | 41.85 | 11541 | 0.000 | 0.097 |
| A1 breakout 20d, volume 1.5x, time 40 | 0.40 | 0.48 | 0.45 | 7.0 % | 27.2 % | -4.7 % | 0.82 | 98.5 % | 12.55 | 3725 | 0.000 | 0.245 |
| A1 breakout 20d, volume 1.5x, time 40, regime | 0.58 | 0.41 | 0.37 | 5.6 % | 30.8 % | -4.2 % | 0.71 | 89.4 % | 11.31 | 3131 | 0.000 | 0.172 |
| A1 breakout 20d, volume 2.5x, time 10 | 0.36 | 0.02 | -0.11 | -0.6 % | 38.8 % | -7.6 % | 0.50 | 68.9 % | 34.87 | 10477 | 0.000 | 0.013 |
| A1 breakout 20d, volume 2.5x, time 10, regime | 0.51 | -0.06 | -0.20 | -1.4 % | 35.9 % | -6.6 % | 0.37 | 61.8 % | 31.26 | 8735 | 0.000 | 0.006 |
| A1 breakout 20d, volume 2.5x, time 40 | 0.50 | 0.38 | 0.34 | 5.1 % | 31.6 % | -6.5 % | 0.83 | 94.6 % | 12.08 | 3588 | 0.000 | 0.151 |
| A1 breakout 20d, volume 2.5x, time 40, regime | 0.73 | 0.22 | 0.18 | 2.2 % | 39.7 % | -7.5 % | 0.70 | 84.9 % | 10.79 | 2987 | 0.000 | 0.059 |
| A1 breakout 55d, volume 1.5x, time 10 | 0.32 | 0.24 | 0.09 | 2.5 % | 37.2 % | -6.3 % | 0.65 | 90.4 % | 45.73 | 13575 | 0.000 | 0.067 |
| A1 breakout 55d, volume 1.5x, time 10, regime | 0.48 | 0.32 | 0.18 | 3.6 % | 22.7 % | -3.1 % | 0.49 | 80.5 % | 40.70 | 11232 | 0.000 | 0.112 |
| A1 breakout 55d, volume 1.5x, time 40 | 0.55 | 0.39 | 0.35 | 5.3 % | 33.8 % | -5.9 % | 0.80 | 98.1 % | 12.50 | 3693 | 0.000 | 0.160 |
| A1 breakout 55d, volume 1.5x, time 40, regime | 0.63 | 0.45 | 0.42 | 6.3 % | 29.3 % | -3.1 % | 0.68 | 88.3 % | 11.18 | 3103 | 0.000 | 0.216 |
| A1 breakout 55d, volume 2.5x, time 10 | 0.40 | 0.26 | 0.12 | 2.3 % | 31.3 % | -3.2 % | 0.40 | 60.1 % | 30.43 | 9138 | 0.000 | 0.074 |
| A1 breakout 55d, volume 2.5x, time 10, regime | 0.49 | 0.24 | 0.11 | 2.1 % | 30.7 % | -2.5 % | 0.33 | 55.0 % | 27.80 | 7814 | 0.000 | 0.068 |
| A1 breakout 55d, volume 2.5x, time 40 | 0.48 | 0.60 | 0.56 | 8.6 % | 29.1 % | -2.0 % | 0.74 | 91.3 % | 11.67 | 3464 | 0.000 | 0.374 |
| A1 breakout 55d, volume 2.5x, time 40, regime | 0.73 | 0.48 | 0.45 | 6.2 % | 24.6 % | -2.8 % | 0.63 | 82.2 % | 10.44 | 2905 | 0.000 | 0.242 |
| A2 gap 2%, time 5 | 0.28 | -0.36 | -0.50 | -5.4 % | 60.8 % | -11.0 % | 0.40 | 34.1 % | 34.41 | 9652 | 0.000 | 0.000 |
| A2 gap 2%, time 5, regime | 0.45 | -0.21 | -0.35 | -2.7 % | 42.3 % | -5.9 % | 0.24 | 29.0 % | 29.20 | 7468 | 0.000 | 0.001 |
| A2 gap 2%, time 20 | 0.59 | 0.38 | 0.33 | 5.5 % | 43.9 % | -5.9 % | 0.84 | 77.1 % | 19.49 | 5861 | 0.000 | 0.152 |
| A2 gap 2%, time 20, regime | 0.55 | 0.20 | 0.15 | 2.0 % | 39.3 % | -6.1 % | 0.61 | 67.1 % | 16.95 | 4655 | 0.000 | 0.053 |
| A2 gap 4%, time 5 | 0.10 | -0.45 | -0.54 | -5.3 % | 55.1 % | -9.1 % | 0.27 | 18.3 % | 18.44 | 4711 | 0.000 | 0.000 |
| A2 gap 4%, time 5, regime | 0.22 | -0.32 | -0.41 | -2.9 % | 35.6 % | -4.8 % | 0.14 | 15.2 % | 15.36 | 3510 | 0.000 | 0.000 |
| A2 gap 4%, time 20 | 0.54 | 0.19 | 0.15 | 1.8 % | 44.4 % | -7.6 % | 0.71 | 54.4 % | 13.75 | 3775 | 0.000 | 0.049 |
| A2 gap 4%, time 20, regime | 0.47 | 0.05 | 0.01 | -0.3 % | 38.4 % | -6.2 % | 0.45 | 47.2 % | 11.91 | 2934 | 0.000 | 0.017 |
| A3 PEAD z 1, time 20 | 0.63 | 0.54 | 0.48 | 6.5 % | 32.8 % | -2.4 % | 0.62 | 70.2 % | 17.70 | 4495 | 0.000 | 0.308 |
| A3 PEAD z 1, time 60 | 0.43 | 0.63 | 0.61 | 10.5 % | 41.8 % | -3.0 % | 0.94 | 95.2 % | 8.04 | 2248 | 0.000 | 0.415 |
| A3 PEAD z 1, volume 2x, time 20 | 0.72 | 0.54 | 0.48 | 5.9 % | 36.5 % | -1.8 % | 0.53 | 58.7 % | 14.79 | 3252 | 0.000 | 0.311 |
| A3 PEAD z 1, volume 2x, time 60 | 0.55 | 0.65 | 0.63 | 10.5 % | 42.2 % | -3.0 % | 0.93 | 93.7 % | 7.88 | 1867 | 0.000 | 0.439 |
| A3 PEAD z 2, time 20 | 0.62 | 0.49 | 0.43 | 5.1 % | 35.0 % | -2.2 % | 0.50 | 56.2 % | 14.17 | 3175 | 0.000 | 0.253 |
| A3 PEAD z 2, time 60 | 0.40 | 0.68 | 0.66 | 10.8 % | 40.4 % | -2.1 % | 0.89 | 93.5 % | 7.85 | 1904 | 0.000 | 0.480 |
| A3 PEAD z 2, volume 2x, time 20 | 0.71 | 0.49 | 0.43 | 4.6 % | 28.5 % | -1.6 % | 0.43 | 49.7 % | 12.51 | 2722 | 0.000 | 0.256 |
| A3 PEAD z 2, volume 2x, time 60 | 0.65 | 0.54 | 0.51 | 8.0 % | 38.9 % | -4.7 % | 0.89 | 91.5 % | 7.67 | 1765 | 0.000 | 0.301 |
| A4 52-week high top 20 | 0.22 | 0.44 | 0.38 | 6.3 % | 29.0 % | -3.2 % | 0.69 | 99.6 % | 20.85 | 5990 | 0.000 | 0.207 |
| A4 52-week high top 20, regime | 0.58 | 0.39 | 0.33 | 4.7 % | 28.4 % | -1.4 % | 0.45 | 82.0 % | 17.76 | 4827 | 0.000 | 0.158 |
| A4 52-week high top 50 | 0.41 | 0.56 | 0.50 | 7.4 % | 26.7 % | -2.3 % | 0.67 | 99.7 % | 17.27 | 12438 | 0.000 | 0.325 |
| A4 52-week high top 50, regime | 0.87 | 0.44 | 0.38 | 4.7 % | 21.9 % | -1.2 % | 0.42 | 82.1 % | 15.58 | 10522 | 0.000 | 0.203 |
| A5 sectors 63d top 2 | 0.25 | 0.83 | 0.82 | 15.0 % | 31.5 % | 2.4 % | 0.86 | 100.0 % | 12.16 | 324 | 0.000 | 0.669 |
| A5 sectors 63d top 2, regime | 0.51 | 0.77 | 0.75 | 11.1 % | 20.9 % | 3.8 % | 0.50 | 82.3 % | 11.29 | 266 | 0.000 | 0.590 |
| A5 sectors 63d top 3 | 0.31 | 0.83 | 0.82 | 13.9 % | 31.1 % | 1.2 % | 0.85 | 100.0 % | 10.38 | 404 | 0.000 | 0.670 |
| A5 sectors 63d top 3, regime | 0.63 | 0.73 | 0.72 | 9.6 % | 22.4 % | 2.3 % | 0.50 | 82.3 % | 9.73 | 336 | 0.000 | 0.545 |
| A5 sectors 126d top 2 | 0.34 | 0.68 | 0.67 | 11.6 % | 29.8 % | -0.7 % | 0.86 | 100.0 % | 9.20 | 237 | 0.000 | 0.483 |
| A5 sectors 126d top 2, regime | 0.62 | 0.43 | 0.42 | 5.5 % | 31.3 % | -1.4 % | 0.50 | 82.3 % | 9.26 | 208 | 0.000 | 0.193 |
| A5 sectors 126d top 3 | 0.36 | 0.80 | 0.79 | 12.9 % | 28.6 % | 0.4 % | 0.85 | 100.0 % | 7.30 | 282 | 0.000 | 0.625 |
| A5 sectors 126d top 3, regime | 0.70 | 0.59 | 0.58 | 7.3 % | 23.3 % | 0.3 % | 0.50 | 82.3 % | 7.51 | 257 | 0.000 | 0.361 |
| A5 sectors 252d top 2 | 0.38 | 0.89 | 0.89 | 16.0 % | 31.5 % | 3.0 % | 0.87 | 100.0 % | 6.28 | 172 | 0.000 | 0.735 |
| A5 sectors 252d top 2, regime | 0.62 | 0.71 | 0.70 | 9.8 % | 23.2 % | 2.5 % | 0.51 | 82.3 % | 6.88 | 160 | 0.000 | 0.514 |
| A5 sectors 252d top 3 | 0.35 | 0.82 | 0.81 | 13.5 % | 30.9 % | 0.4 % | 0.88 | 100.0 % | 5.94 | 230 | 0.000 | 0.652 |
| A5 sectors 252d top 3, regime | 0.65 | 0.64 | 0.63 | 8.1 % | 22.9 % | 0.8 % | 0.51 | 82.3 % | 6.63 | 216 | 0.000 | 0.429 |
| A5 sectors blend top 2 | 0.33 | 0.71 | 0.70 | 12.1 % | 30.9 % | -0.4 % | 0.87 | 100.0 % | 9.75 | 242 | 0.000 | 0.519 |
| A5 sectors blend top 2, regime | 0.63 | 0.52 | 0.51 | 6.8 % | 23.1 % | -0.4 % | 0.52 | 82.3 % | 9.43 | 205 | 0.000 | 0.282 |
| A5 sectors blend top 3 | 0.31 | 0.85 | 0.84 | 14.0 % | 30.9 % | 1.2 % | 0.86 | 100.0 % | 7.24 | 278 | 0.000 | 0.690 |
| A5 sectors blend top 3, regime | 0.59 | 0.70 | 0.69 | 9.0 % | 24.1 % | 1.7 % | 0.51 | 82.3 % | 7.26 | 243 | 0.000 | 0.506 |
| A1 breakout 55d, volume 2.5x, time 40, regime · a day late | 0.73 | 0.43 | 0.39 | 5.4 % | 30.4 % | -3.5 % | 0.63 | 82.1 % | 10.10 | 2833 | 0.000 | 0.190 |
| A2 gap 2%, time 20 · a day late | 0.47 | 0.49 | 0.44 | 7.9 % | 37.3 % | -4.1 % | 0.87 | 78.7 % | 18.89 | 5683 | 0.000 | 0.253 |
| A3 PEAD z 1, volume 2x, time 20 · a day late | 0.63 | 0.50 | 0.44 | 5.4 % | 34.7 % | -2.4 % | 0.54 | 60.1 % | 14.43 | 3172 | 0.000 | 0.265 |
| A4 52-week high top 50, regime · a day late | 0.89 | 0.43 | 0.37 | 4.6 % | 20.3 % | -1.4 % | 0.42 | 82.1 % | 15.58 | 10520 | 0.000 | 0.196 |
| A5 sectors 126d top 3, regime · a day late | 0.67 | 0.58 | 0.57 | 7.3 % | 21.9 % | 0.2 % | 0.50 | 82.3 % | 7.52 | 257 | 0.000 | 0.356 |

### Part B: capture of the picks' current exits
Per closed trade: realised return, MFE (the highest close held over the entry fill), capture (realised / MFE where MFE > 0), give-back (MFE minus realised), left on the table (the highest close in the 20 days after the exit over the exit price). 25th, 50th and 75th percentiles.
| book | trades | realised | MFE | capture | give-back | left on table | gain lost |
|---|---|---|---|---|---|---|---|
| A1 A1 breakout 55d, volume 2.5x, time 40, regime | 2905 | -4.7/1.9/8.1 % | 2.7/6.6/11.7 % | -0.71/0.45/0.86 | 1.3/4.4/9.8 % | 1.6/4.3/8.3 % | 33.8 % |
| A2 A2 gap 2%, time 20 | 5861 | -4.1/1.2/6.3 % | 1.8/4.9/9.5 % | -0.75/0.46/0.87 | 1.1/3.6/7.9 % | 1.7/4.7/9.3 % | 32.2 % |
| A3 A3 PEAD z 1, volume 2x, time 20 | 3252 | -2.6/1.4/5.4 % | 1.6/4.1/7.5 % | -0.50/0.54/0.90 | 0.6/2.5/5.7 % | 1.6/4.0/7.3 % | 30.3 % |
| A4 A4 52-week high top 50, regime | 10522 | -3.5/0.6/4.9 % | 1.4/4.0/8.3 % | -1.01/0.33/0.78 | 1.5/3.5/6.9 % | 1.4/3.8/7.2 % | 35.7 % |
| A5 A5 sectors 126d top 3, regime | 257 | -2.5/1.4/5.9 % | 1.5/3.9/9.1 % | -1.16/0.37/0.82 | 1.1/3.3/6.9 % | 1.1/3.0/4.5 % | 36.6 % |
| A1 with exit target 1, time 40 | 3252 | -4.5/2.4/8.6 % | 2.7/6.4/10.4 % | -0.71/0.59/0.98 | 0.3/2.9/8.1 % | 1.6/4.2/8.2 % | 32.0 % |
| A2 with exit target 1, time 20 | 6260 | -3.9/1.5/6.9 % | 1.8/4.9/8.9 % | -0.67/0.57/0.96 | 0.4/2.7/6.9 % | 1.6/4.7/9.2 % | 31.0 % |
| A3 with exit model, cap 80 | 2783 | -3.6/1.2/6.9 % | 1.3/4.7/9.1 % | -0.68/0.65/0.96 | 0.3/2.0/7.1 % | 1.8/4.4/7.9 % | 30.5 % |
| A4 with exit ATR 3 | 11066 | -4.0/-0.1/4.2 % | 1.1/3.6/7.7 % | -1.20/0.21/0.73 | 1.8/4.1/6.7 % | 1.5/3.8/7.2 % | 38.2 % |
| A5 with exit ATR 3 | 436 | -3.2/-0.5/3.5 % | 1.2/3.4/7.0 % | -1.38/0.02/0.63 | 2.7/4.2/5.8 % | 1.4/3.3/5.4 % | 44.5 % |

### Part B1: exits on the picks
- **A1**: exit pick target 1, time 40: OOS Sharpe 0.42 against 0.48 with the base exit (selection 0.88 vs 0.73), drawdown 30.2 % vs 24.6 %, better in 4 of 11 years, bootstrap of the difference -0.22 to 0.11, a day late 0.41, deflated p of the improvement 0.004. Fails: 1 Sharpe higher, and in more than half the years, 2 drawdown not higher, 3 bootstrap 5 % of the difference above 0, 4 a day late still higher, 5 still higher at doubled costs, 6 deflated p of the improvement > 0.95.
- **A2**: exit pick target 1, time 20: OOS Sharpe 0.44 against 0.38 with the base exit (selection 0.68 vs 0.59), drawdown 43.0 % vs 43.9 %, better in 7 of 11 years, bootstrap of the difference -0.04 to 0.15, a day late 0.54, deflated p of the improvement 0.105. Fails: 3 bootstrap 5 % of the difference above 0, 6 deflated p of the improvement > 0.95.
- **A3**: exit pick model, cap 80: OOS Sharpe 0.57 against 0.54 with the base exit (selection 0.80 vs 0.72), drawdown 29.5 % vs 36.5 %, better in 6 of 11 years, bootstrap of the difference -0.30 to 0.32, a day late 0.59, deflated p of the improvement 0.047. Fails: 3 bootstrap 5 % of the difference above 0, 6 deflated p of the improvement > 0.95.
- **A4**: exit pick ATR 3: OOS Sharpe 0.42 against 0.44 with the base exit (selection 0.64 vs 0.87), drawdown 19.6 % vs 21.9 %, better in 5 of 11 years, bootstrap of the difference -0.17 to 0.12, a day late 0.40, deflated p of the improvement 0.002. Fails: 1 Sharpe higher, and in more than half the years, 3 bootstrap 5 % of the difference above 0, 4 a day late still higher, 5 still higher at doubled costs, 6 deflated p of the improvement > 0.95.
- **A5**: exit pick ATR 3: OOS Sharpe 0.50 against 0.59 with the base exit (selection 0.40 vs 0.70), drawdown 18.2 % vs 23.3 %, better in 3 of 11 years, bootstrap of the difference -0.32 to 0.14, a day late 0.45, deflated p of the improvement 0.001. Fails: 1 Sharpe higher, and in more than half the years, 3 bootstrap 5 % of the difference above 0, 4 a day late still higher, 5 still higher at doubled costs, 6 deflated p of the improvement > 0.95.

| variant | sel | OOS | OOS 2x | CAGR | max DD | alpha | beta | exposure | turnover/yr | trades | defl. p pool |
|---|---|---|---|---|---|---|---|---|---|---|---|
| A1 breakout 55d, volume 2.5x, time 40, regime · exit time 20 | 0.49 | 0.15 | 0.09 | 1.2 % | 40.4 % | -5.7 % | 0.50 | 73.0 % | 18.52 | 5134 | 0.000 |
| A1 breakout 55d, volume 2.5x, time 40, regime · exit time 80 | 0.75 | 0.39 | 0.38 | 5.2 % | 27.2 % | -5.1 % | 0.74 | 88.9 % | 5.75 | 1558 | 0.000 |
| A1 breakout 55d, volume 2.5x, time 40, regime · exit ATR 2, cap 160 | 0.37 | 0.37 | 0.30 | 3.8 % | 22.1 % | -1.3 % | 0.37 | 72.5 % | 16.76 | 4698 | 0.000 |
| A1 breakout 55d, volume 2.5x, time 40, regime · exit ATR 3, cap 160 | 0.49 | 0.48 | 0.44 | 5.7 % | 24.2 % | -0.8 % | 0.46 | 80.8 % | 10.27 | 2862 | 0.000 |
| A1 breakout 55d, volume 2.5x, time 40, regime · exit target 1, time 40 | 0.88 | 0.42 | 0.38 | 5.2 % | 30.2 % | -3.4 % | 0.62 | 81.6 % | 11.54 | 3252 | 0.000 |
| A1 breakout 55d, volume 2.5x, time 40, regime · exit target 2, time 40 | 0.79 | 0.47 | 0.44 | 6.1 % | 29.0 % | -2.8 % | 0.63 | 82.2 % | 10.58 | 2947 | 0.000 |
| A1 breakout 55d, volume 2.5x, time 40, regime · exit model, cap 160 | 0.63 | 0.60 | 0.55 | 7.1 % | 29.9 % | -0.9 % | 0.56 | 81.7 % | 12.53 | 3342 | 0.000 |
| A2 gap 2%, time 20 · exit time 10 | 0.41 | 0.14 | 0.05 | 0.9 % | 48.5 % | -7.5 % | 0.62 | 55.1 % | 27.82 | 8118 | 0.000 |
| A2 gap 2%, time 20 · exit time 40 | 0.42 | 0.40 | 0.37 | 6.2 % | 39.7 % | -7.4 % | 0.99 | 90.9 % | 11.49 | 3460 | 0.000 |
| A2 gap 2%, time 20 · exit ATR 2, cap 80 | 0.30 | 0.33 | 0.27 | 4.2 % | 37.4 % | -5.5 % | 0.70 | 80.6 % | 18.64 | 5548 | 0.000 |
| A2 gap 2%, time 20 · exit ATR 3, cap 80 | 0.42 | 0.59 | 0.55 | 9.4 % | 38.0 % | -2.2 % | 0.82 | 90.1 % | 12.37 | 3737 | 0.000 |
| A2 gap 2%, time 20 · exit target 1, time 20 | 0.68 | 0.44 | 0.38 | 6.7 % | 43.0 % | -4.8 % | 0.84 | 75.4 % | 20.96 | 6260 | 0.000 |
| A2 gap 2%, time 20 · exit target 2, time 20 | 0.61 | 0.42 | 0.36 | 6.2 % | 44.0 % | -5.4 % | 0.85 | 77.1 % | 19.66 | 5908 | 0.000 |
| A2 gap 2%, time 20 · exit model, cap 80 | 0.64 | 0.46 | 0.41 | 6.9 % | 44.3 % | -4.1 % | 0.80 | 82.9 % | 17.86 | 5716 | 0.000 |
| A3 PEAD z 1, volume 2x, time 20 · exit time 10 | 0.48 | 0.52 | 0.41 | 4.6 % | 17.6 % | -0.4 % | 0.34 | 40.8 % | 20.55 | 4371 | 0.000 |
| A3 PEAD z 1, volume 2x, time 20 · exit time 40 | 0.70 | 0.60 | 0.57 | 8.0 % | 34.6 % | -2.5 % | 0.72 | 77.2 % | 9.72 | 2280 | 0.000 |
| A3 PEAD z 1, volume 2x, time 20 · exit ATR 2, cap 80 | 0.52 | 0.79 | 0.73 | 8.5 % | 14.2 % | 1.8 % | 0.45 | 67.7 % | 14.57 | 3241 | 0.000 |
| A3 PEAD z 1, volume 2x, time 20 · exit ATR 3, cap 80 | 0.58 | 0.77 | 0.72 | 9.7 % | 19.9 % | 0.7 % | 0.60 | 81.7 % | 10.65 | 2409 | 0.000 |
| A3 PEAD z 1, volume 2x, time 20 · exit target 1, time 20 | 0.75 | 0.59 | 0.52 | 6.4 % | 33.0 % | -1.2 % | 0.52 | 56.9 % | 15.78 | 3472 | 0.000 |
| A3 PEAD z 1, volume 2x, time 20 · exit target 2, time 20 | 0.72 | 0.58 | 0.51 | 6.2 % | 33.5 % | -1.3 % | 0.52 | 58.6 % | 14.91 | 3270 | 0.000 |
| A3 PEAD z 1, volume 2x, time 20 · exit model, cap 80 | 0.80 | 0.57 | 0.52 | 6.7 % | 29.5 % | -1.9 % | 0.59 | 75.5 % | 12.44 | 2783 | 0.000 |
| A4 52-week high top 50, regime · exit ATR 2 | 0.40 | 0.34 | 0.24 | 2.5 % | 15.5 % | -0.8 % | 0.24 | 54.9 % | 17.15 | 11976 | 0.000 |
| A4 52-week high top 50, regime · exit ATR 3 | 0.64 | 0.42 | 0.34 | 3.7 % | 19.6 % | -0.8 % | 0.32 | 69.1 % | 15.97 | 11066 | 0.000 |
| A5 sectors 126d top 3, regime · exit ATR 2 | 0.27 | 0.58 | 0.55 | 5.3 % | 18.0 % | 1.7 % | 0.25 | 53.8 % | 14.94 | 560 | 0.000 |
| A5 sectors 126d top 3, regime · exit ATR 3 | 0.40 | 0.50 | 0.48 | 5.0 % | 18.2 % | 0.4 % | 0.32 | 65.8 % | 12.07 | 436 | 0.000 |
| A1 breakout 55d, volume 2.5x, time 40, regime · exit target 1, time 40 · a day late | 0.83 | 0.41 | 0.37 | 5.0 % | 31.2 % | -3.7 % | 0.62 | 82.2 % | 11.27 | 3174 | 0.000 |
| A2 gap 2%, time 20 · exit target 1, time 20 · a day late | 0.54 | 0.54 | 0.49 | 9.0 % | 39.7 % | -3.3 % | 0.88 | 77.2 % | 20.12 | 6043 | 0.000 |
| A3 PEAD z 1, volume 2x, time 20 · exit model, cap 80 · a day late | 0.74 | 0.59 | 0.55 | 7.2 % | 34.6 % | -1.8 % | 0.62 | 76.6 % | 12.07 | 2733 | 0.000 |
| A4 52-week high top 50, regime · exit ATR 3 · a day late | 0.77 | 0.40 | 0.32 | 3.6 % | 19.3 % | -1.1 % | 0.33 | 70.4 % | 15.93 | 11011 | 0.000 |
| A5 sectors 126d top 3, regime · exit ATR 3 · a day late | 0.40 | 0.45 | 0.43 | 4.5 % | 20.0 % | -0.2 % | 0.33 | 66.4 % | 12.02 | 432 | 0.000 |

### Part C: M13 ranks and filters the candidates
- **A1**: OOS Sharpe 0.68 against 0.48 without M13 (selection 0.82 vs 0.73), a day late 0.67, bootstrap of the difference -0.06 to 0.47, deflated p 0.465. Fails: 2 drawdown not higher, 3 bootstrap 5 % of the difference above 0, 6 deflated p of the improvement > 0.95.
- **A2**: OOS Sharpe 0.71 against 0.38 without M13 (selection 0.56 vs 0.59), a day late 0.67, bootstrap of the difference 0.02 to 0.63, deflated p 0.299. Fails: 6 deflated p of the improvement > 0.95.
- **A3**: OOS Sharpe 0.52 against 0.54 without M13 (selection 0.70 vs 0.72), a day late 0.53, bootstrap of the difference -0.21 to 0.16, deflated p 0.085. Fails: 1 Sharpe higher, and in more than half the years, 3 bootstrap 5 % of the difference above 0, 4 a day late still higher, 5 still higher at doubled costs, 6 deflated p of the improvement > 0.95.

### The models
- **M13**: squared error 0.7920 vs 0.7771 for the baseline (1.9 % higher), DM p 0.0135, 40 of 107 quarters better, 105016 out-of-fold rows; zoo gate failed, Holm over the three failed. Rank IC (pooled) 0.039, daily mean 0.021 (t 4.36); from 2016 0.035. Importance stability over 107 fits: mean 0.99, min 0.97 (stable; consecutive expanding fits share most rows, so also: fits 20 quarters apart 0.98, first against last 0.91). Largest gain shares: spy_vol21 21 %, spy_mom21 12 %, size 11 %, vol63 9 %, mom252 8 %.
- **M15**: squared error 0.8208 vs 0.8113 for the baseline (1.2 % higher), DM p 0.0000, 34 of 108 quarters better, 273311 out-of-fold rows; zoo gate failed, Holm over the three failed. Rank IC (pooled) 0.026, daily mean 0.042 (t 15.02); from 2016 0.015. Importance stability over 108 fits: mean 0.98, min 0.94 (stable; consecutive expanding fits share most rows, so also: fits 20 quarters apart 0.95, first against last 0.97). Largest gain shares: spy_mom21 24 %, vol21 21 %, mom63 10 %, dist52 10 %, ret_entry 6 %.

Holm inputs (DM p, 1.0 where the model is not lower): {'M13': 1.0, 'M15': 1.0, 'M14': 1.0}.

### Coverage
| year | members without volume | member days without an open | members with a CIK |
|---|---|---|---|
| 1997 | 50.6 % | 50.6 % | 39.8 % |
| 1998 | 46.4 % | 46.4 % | 42.6 % |
| 1999 | 42.2 % | 42.2 % | 45.3 % |
| 2000 | 38.5 % | 38.5 % | 47.2 % |
| 2001 | 33.7 % | 33.7 % | 49.8 % |
| 2002 | 30.9 % | 30.9 % | 51.6 % |
| 2003 | 29.1 % | 29.1 % | 53.5 % |
| 2004 | 28.0 % | 28.0 % | 54.4 % |
| 2005 | 26.1 % | 26.1 % | 55.4 % |
| 2006 | 21.6 % | 21.6 % | 58.0 % |
| 2007 | 14.1 % | 14.1 % | 60.3 % |
| 2008 | 9.6 % | 9.6 % | 63.3 % |
| 2009 | 6.9 % | 6.9 % | 65.7 % |
| 2010 | 4.7 % | 4.7 % | 67.9 % |
| 2011 | 3.2 % | 3.2 % | 69.7 % |
| 2012 | 1.7 % | 1.7 % | 72.2 % |
| 2013 | 0.9 % | 0.9 % | 74.5 % |
| 2014 | 0.5 % | 0.5 % | 76.1 % |
| 2015 | 0.2 % | 0.2 % | 77.9 % |
| 2016 | 0.2 % | 0.1 % | 81.5 % |
| 2017 | 0.0 % | 0.0 % | 84.9 % |
| 2018 | 0.0 % | 0.0 % | 87.1 % |
| 2019 | 0.0 % | 0.0 % | 89.5 % |
| 2020 | 0.0 % | 0.0 % | 91.5 % |
| 2021 | 0.0 % | 0.0 % | 92.7 % |
| 2022 | 0.0 % | 0.0 % | 94.2 % |
| 2023 | 0.0 % | 0.0 % | 95.8 % |
| 2024 | 0.0 % | 0.0 % | 96.8 % |
| 2025 | 0.0 % | 0.0 % | 98.1 % |
| 2026 | 0.0 % | 0.0 % | 99.5 % |
