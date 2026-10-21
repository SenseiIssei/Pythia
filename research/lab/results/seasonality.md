<!-- generated below by lab.experiments.survey_equities (seasonality); edit above this line only -->

# Same-calendar-month seasonality: results (2026-10-21)

**Verdict: KILL.** Pick (best selection-window long/short Sharpe): lags 1-20. Out of sample from 2016: rank IC 0.0032 (t 0.33, 128 months), decile long/short Sharpe -0.24; top 50 Sharpe 0.66 (12.4 % a year, drawdown 43 %) against the equal weight 0.75 and SPY 0.92; IR 0.10 (bootstrap 90 % band -0.30 to 0.52), -0.02 with costs doubled, -0.06 a day late; turnover 20.3 a year. Deflated p (top 50 active) 0.000.

## Gates (the pick's lag set, out of sample)

- fail: 1 rank IC t above 2
- fail: 2 long/short Sharpe above 0.3
- fail: 3 top 50 IR above 0, bootstrap 5 % bound above 0
- fail: 4 top 50 IR above 0 with costs doubled and a day late
- PASS: 5 top 50 active return positive in more than half the years

Kill rule (IC t below 1): hit.

## All trials

| trial | IR / Sharpe 2001-15 | IR / Sharpe OOS | IC 2001-15 | IC t | IC OOS | IC t OOS | deflated p |
|---|---|---|---|---|---|---|---|
| lags 1-5, top 50 | -0.09 | -0.40 | 0.00 | 0.23 | -0.01 | -0.93 | 0.00 |
| lags 1-5, decile long/short | -0.09 | -0.47 | 0.00 | 0.23 | -0.01 | -0.93 | 0.00 |
| lags 1-10, top 50 | 0.17 | -0.15 | 0.01 | 1.40 | -0.01 | -0.53 | 0.00 |
| lags 1-10, decile long/short | 0.12 | -0.35 | 0.01 | 1.40 | -0.01 | -0.53 | 0.00 |
| lags 1-20, top 50 | 0.09 | 0.10 | 0.01 | 1.85 | 0.00 | 0.33 | 0.00 |
| lags 1-20, decile long/short | 0.15 | -0.24 | 0.01 | 1.85 | 0.00 | 0.33 | 0.00 |

Top 50 rows show the IR against the equal weight, long/short rows the book's Sharpe.

Top 50 active return by year: 2016 1.0 %, 2017 2.0 %, 2018 4.4 %, 2019 3.7 %, 2020 -6.9 %, 2021 1.2 %, 2022 -7.5 %, 2023 11.9 %, 2024 8.2 %, 2025 -12.5 %, 2026 2.1 %.

Pool: 1,140 hand trials, 600 factory genomes and the 33 trials registered with this study (16 of them run so far, standing for all): 1,773 trials; the best noise trial sits at an annual Sharpe of about 2.26 on trading days.
