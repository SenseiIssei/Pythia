# vix_carry (survey #2) · VIX term-structure short-volatility sleeve

Pre-registered in `results/vix_carry_prereg.md` (committed before any number
was computed). Code: `lab.experiments.vix_carry`. Run on the PC with
`PYTHIA_DATA=F:/PythiaData PYTHIA_AGENT_OUT=<elsewhere> PYTHIA_REPORTS=<elsewhere>`.

**Summary.** Killed by its own rule. The term-structure switch does what it
promises in the tails (it was out of the market through February 2018 and
March 2020, where holding the product lost 53 % and 51 %), but the premium it
keeps after 2018 is small: the in-sample pick makes Sharpe 0.23 out of sample
against SPY 0.81 and 60/40 0.84. The rebuilt pre-2011 index missed its
registered correlation check by a hair (0.949 against 0.95, because the
futures settle 15 minutes after the ETFs close), so selection used 2011-10 to
2017 only. As a 10 or 20 % sleeve next to the crypto books it lowers their
Sharpe (0.78 and 0.65 against 0.88 for the crypto mix alone); SPY as the
sleeve does better (1.04, 1.19). No book, no job.

<!-- generated below by lab.experiments.vix_carry; edit above this line only -->

## Results (generated 2026-10-21, in sample 2011-10-05 to 2017-12-31, out of sample 2018-01-01 to 2026-10-14)

**Killed.** The in-sample pick is **E3 q<60d mean · S1 fixed** (in-sample Sharpe 1.12). Out of sample it makes Sharpe 0.23, 2.7 % a year, drawdown 42.0 %, worst day -16.9 %, against SPY 0.81 / 14.6 % / 33.7 % and 60/40 0.84 / 9.2 % / 21.2 %. A day late 0.31, at 26 bps 0.03, filled at the next open 0.00. Bootstrap 90 % band of Sharpe(pick) - Sharpe(SPY) -1.19 to -0.01 (5 % of draws above 0). Deflated p 0.00 over 1,762 trials (noise bar about 2.72).

Kill rule hit: Sharpe below 60/40's.
Pass rules failed: Sharpe above SPY's; drawdown below SPY's; bootstrap 5 % of Sharpe - SPY's above 0.

Holding the -0.5x product always (no switch) makes 0.26, drawdown 76.7 % out of sample; in sample 1.13 against SPY 1.31.

### The six rules (13 bps per unit of turnover, fills at the next close)

| rule | is_sharpe | is_dd | oos_sharpe | oos_cagr | oos_dd | oos_stress | oos_late | oos_open | time_in | turnover_yr | worst_day |
|---|---|---|---|---|---|---|---|---|---|---|---|
| E1 q<1.00 · S1 fixed | 0.96 | 0.41 | 0.26 | 0.03 | 0.59 | 0.21 | 0.30 | 0.49 | 0.92 | 12.78 | -0.22 |
| E1 q<1.00 · S2 inverse vol | 0.79 | 0.29 | 0.11 | -0.00 | 0.47 | 0.04 | 0.06 | 0.26 | 0.92 | 11.60 | -0.15 |
| E2 q<0.95 · S1 fixed | 1.10 | 0.29 | 0.03 | -0.03 | 0.55 | -0.08 | 0.10 | 0.23 | 0.78 | 22.14 | -0.17 |
| E2 q<0.95 · S2 inverse vol | 0.85 | 0.25 | -0.02 | -0.02 | 0.49 | -0.13 | 0.00 | 0.07 | 0.78 | 16.79 | -0.15 |
| E3 q<60d mean · S1 fixed | 1.12 | 0.21 | 0.23 | 0.03 | 0.42 | 0.03 | 0.31 | 0.00 | 0.55 | 32.76 | -0.17 |
| E3 q<60d mean · S2 inverse vol | 1.00 | 0.18 | 0.14 | 0.01 | 0.30 | -0.09 | 0.29 | -0.08 | 0.55 | 25.82 | -0.09 |

The pick per year out of sample: 2018 0.40, 2019 0.39, 2020 0.15, 2021 0.05, 2022 0.06, 2023 2.32, 2024 -1.92, 2025 0.84, 2026 0.41.

### Stress windows (cumulative return)

| window | pick | always | spy |
|---|---|---|---|
| 2018-02 (Volmageddon) | 0.000 | -0.531 | -0.036 |
| 2020-02-20 to 2020-04-30 (Covid) | 0.022 | -0.510 | -0.136 |
| 2024-08-01 to 2024-08-15 (yen carry) | -0.001 | -0.095 | 0.004 |
| 2025-04-01 to 2025-04-30 (tariffs) | -0.008 | -0.182 | -0.009 |

### The pick's ten worst days out of sample

| day | net | q_prior_close | weight_held | instrument |
|---|---|---|---|---|
| 2020-06-11 | -0.169 | 0.932 | 1.000 | -0.169 |
| 2021-01-27 | -0.105 | 0.856 | 1.000 | -0.105 |
| 2024-09-03 | -0.101 | 0.861 | 1.000 | -0.101 |
| 2024-12-18 | -0.087 | 0.875 | 1.000 | -0.087 |
| 2019-05-07 | -0.083 | 0.941 | 1.000 | -0.082 |
| 2021-02-25 | -0.082 | 0.824 | 1.000 | -0.082 |
| 2021-07-19 | -0.072 | 0.836 | 1.000 | -0.071 |
| 2020-09-03 | -0.068 | 0.813 | 1.000 | -0.068 |
| 2022-02-11 | -0.067 | 0.917 | 1.000 | -0.066 |
| 2019-08-23 | -0.061 | 0.915 | 1.000 | -0.061 |

### Sleeve next to the four crypto books (equal weight, 35 bps, out of sample from 2024)

Yardstick: breakout_top10 alone, Sharpe 1.17, 18.5 % a year, drawdown 16.0 %; per year 2024 2.19, 2025 0.32, 2026 -0.02. The equal-weight crypto mix without a sleeve: 0.88, drawdown 10.6 %. Correlation of the sleeve with the crypto mix: 0.16.

| sleeve | sharpe | cagr | max_dd | years | band_vs_best | band_vs_ew | spy_instead | deflated_p | verdict |
|---|---|---|---|---|---|---|---|---|---|
| 10 % | 0.78 | 0.08 | 0.12 | 1.51 / 0.03 / 0.60 | -0.87 to 0.18 | -0.28 to 0.10 | 1.04 | 0.00 | fails: Sharpe above the best book's, 2 of 3 years on Sharpe and on drawdown, bootstrap 5 % of the difference above 0 |
| 20 % | 0.65 | 0.06 | 0.14 | 1.05 / 0.21 / 0.63 | -1.11 to 0.17 | -0.60 to 0.18 | 1.19 | 0.00 | fails: Sharpe above the best book's, 2 of 3 years on Sharpe and on drawdown, bootstrap 5 % of the difference above 0 |

### Rebuild checks

250 VX contracts; the rebuilt index starts 2006-06-21. Correlation with VIXY 0.949 over 3967 days (VIXY minus index -3.7 % a year, its fee and the 16:00 / 16:15 timing), with -SVXY before the switch 0.737. SVXY / index return ratio: median -0.99 in the 60 days before 2018-02-28 and -0.50 after, so the leverage change sits where the series puts it. Rebuild FAILS its registered check (both correlations above 0.95), so the in-sample window starts 2011-10-05. Diagnosis: without February 2018 the correlation with -SVXY is 0.947; rank correlations 0.966 (VIXY) and 0.938 (-SVXY). The rebuild settles at 16:15 and the ETFs close at 16:00, which on a few days (2018-02-05 and 06, 2012-12-28 and 31, 2014-10-15, 2016-06-28) puts the two series 10 to 60 percentage points of daily return apart.
