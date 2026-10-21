<!-- generated below by lab.experiments.survey_equities (turn_of_month); edit above this line only -->

# Turn of the month and pre-holiday: results (2026-10-21)

**Verdict: FAIL.** Pick (best selection-window Sharpe): SPY [-2, +3]. Out of sample from 2016: Sharpe 0.65 (5.1 % a year, drawdown 15 %, invested 24 % of sessions) against the ETF bought and held 0.88 and SPY 0.88; window sessions 9.7 bps a day against 5.0 on the others (Welch t 0.96); a session later 0.44, costs doubled 0.59; Sharpe above SPY's in 23 % of bootstrap draws. Deflated p 0.000.

## Gates (the pick, out of sample)

- fail: 1 window sessions above other sessions, Welch t above 2
- fail: 2 Sharpe above the ETF's own buy and hold and above SPY's
- fail: 3 bootstrap: Sharpe above SPY's in at least 90 % of draws
- PASS: 4 Sharpe above 0 a session later and with costs doubled
- not run: 5 as a 20 % sleeve, book_portfolio's rule (run only if 1 to 4 hold)

Kill rule (window sessions not above the others): not hit.

## All trials

| trial | Sharpe selection | Sharpe OOS | buy and hold OOS | invested | CAGR OOS | drawdown OOS | deflated p |
|---|---|---|---|---|---|---|---|
| SPY [-1, +3] | 0.43 | 0.41 | 0.88 | 0.19 | 0.03 | 0.10 | 0.00 |
| QQQ [-1, +3] | 0.27 | 0.47 | 0.92 | 0.19 | 0.04 | 0.15 | 0.00 |
| IWM [-1, +3] | 0.10 | 0.05 | 0.54 | 0.19 | 0.00 | 0.25 | 0.00 |
| SPY [-2, +3] | 0.46 | 0.65 | 0.88 | 0.24 | 0.05 | 0.15 | 0.00 |
| QQQ [-2, +3] | 0.28 | 0.63 | 0.92 | 0.24 | 0.06 | 0.17 | 0.00 |
| IWM [-2, +3] | 0.21 | 0.30 | 0.54 | 0.24 | 0.03 | 0.24 | 0.00 |
| SPY [-1, +1] | 0.30 | 0.26 | 0.88 | 0.10 | 0.01 | 0.11 | 0.00 |
| QQQ [-1, +1] | 0.19 | 0.48 | 0.92 | 0.10 | 0.03 | 0.10 | 0.00 |
| IWM [-1, +1] | 0.08 | -0.03 | 0.54 | 0.10 | -0.00 | 0.21 | 0.00 |
| SPY pre-holiday | 0.07 | 0.41 | 0.88 | 0.04 | 0.01 | 0.06 | 0.00 |

Mean return by session of the month, out of sample (pick's ETF): -2 19.2 bps (n 130), -1 1.1 bps (n 130), +1 13.6 bps (n 130), +2 9.1 bps (n 130), +3 5.5 bps (n 130), other 5.0 bps (n 2066).

Pick's Sharpe by year: 2016 -0.09, 2017 1.04, 2018 -0.23, 2019 0.81, 2020 1.47, 2021 0.48, 2022 0.72, 2023 1.74, 2024 -0.99, 2025 -0.07, 2026 3.02.

Pool: 1,140 hand trials, 600 factory genomes and the 33 trials registered with this study (10 of them run so far, standing for all): 1,773 trials; the best noise trial sits at an annual Sharpe of about 2.26 on trading days.
