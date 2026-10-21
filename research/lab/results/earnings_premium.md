<!-- generated below by lab.experiments.survey_equities (earnings_premium); edit above this line only -->

# Earnings announcement premium: results (2026-10-21)

**Verdict: KILL.** Pick (best selection-window IR): entry 5 before, exit 1 after, volume filter. Out of sample from 2016: IR -0.23 against the CIK equal weight (-1.7 % a year active, alpha -2.5 %), -0.64 with costs doubled, -0.27 a day late; bootstrap 90 % band of the IR -0.79 to 0.31. Book L (SPY with the rest): Sharpe 0.76 against SPY 0.92; the tilt book 0.60 against the CIK equal weight 0.78. Deflated p 0.000.

## Gates (the pick, out of sample)

- fail: 1 alpha against the CIK equal weight above 0 and the bootstrap 5 % bound of the IR above 0
- fail: 2 IR above 0.3
- fail: 3 IR above 0 with the entry a day late
- fail: 4 IR above 0 with costs doubled
- fail: 5 book L's Sharpe above SPY's

Kill rule (IR below 0.1): hit.

## All trials

| trial | IR 2005-15 | IR OOS | IR OOS 2x cost | IR OOS before costs | active/yr before costs | alpha OOS | IR vs all-member EW | names/day | turnover/yr | deflated p |
|---|---|---|---|---|---|---|---|---|---|---|
| entry 5 before, exit 1 after | -0.24 | -0.31 | -0.85 | 0.79 | 0.06 | -0.03 | -0.26 | 42.54 | 74.97 | 0.00 |
| entry 5 before, exit 3 after | -0.14 | -0.54 | -1.03 | 0.47 | 0.03 | -0.04 | -0.49 | 56.40 | 71.15 | 0.00 |
| entry 2 before, exit 1 after | -0.48 | -0.91 | -1.62 | 0.57 | 0.04 | -0.07 | -0.85 | 20.36 | 100.35 | 0.00 |
| entry 2 before, exit 3 after | -0.28 | -0.84 | -1.36 | 0.24 | 0.02 | -0.06 | -0.78 | 33.67 | 76.52 | 0.00 |
| entry 5 before, exit 1 after, volume filter | 0.30 | -0.23 | -0.64 | 0.63 | 0.05 | -0.02 | -0.17 | 21.37 | 62.02 | 0.00 |
| entry 5 before, exit 3 after, volume filter | 0.28 | -0.41 | -0.78 | 0.36 | 0.03 | -0.04 | -0.36 | 28.34 | 59.59 | 0.00 |

## The pick by year (out of sample)

| year | IR | active return |
|---|---|---|
| 2016 | -0.18 | -0.01 |
| 2017 | 0.56 | 0.04 |
| 2018 | -3.00 | -0.19 |
| 2019 | 0.10 | 0.00 |
| 2020 | 2.08 | 0.17 |
| 2021 | -0.10 | -0.01 |
| 2022 | -1.29 | -0.10 |
| 2023 | -1.52 | -0.09 |
| 2024 | 0.50 | 0.03 |
| 2025 | -0.77 | -0.07 |
| 2026 | 0.65 | 0.05 |

Expected dates with an actual 8-K within two sessions: 65.8 % of 20844 out-of-sample candidates of the pick's entry rule.

Pool: 1,140 hand trials, 600 factory genomes and the 33 trials registered with this study (27 of them run so far, standing for all): 1,773 trials; the best noise trial sits at an annual Sharpe of about 2.26 on trading days.
