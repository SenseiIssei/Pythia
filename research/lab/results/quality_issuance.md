# Gross profitability and net share issuance from XBRL (survey candidate 7)

Pre-registered as study 4 of `results/survey_equities_prereg.md` (6 trials).
Code: `python -m lab.experiments.survey_equities quality_issuance`; the data
come from `lab.equities.xbrl` (SEC company facts for the 624 CIKs of the
events map, 117 requests on the last pass, cached gzipped, 417,985 facts
kept), point in time by each value's filing date.

**Verdict: fails (IR 0.15, the bar is 0.3; kill bar 0.1 not hit).** The
selection window (2011 to 2017) picks net share issuance alone: its top 50
(the members that shrank their share count most over a year) made IR 0.71
against the ranked universe's equal weight there. From 2018 the same book
makes IR 0.15 (bootstrap band -0.34 to 0.65), Sharpe 0.64 against 0.68 for
its universe's equal weight and 0.84 for SPY, and it trails the 12-1
momentum top 50 on the same universe (IR 0.26). Gross profit to assets ranks
in the right direction (rank IC 0.02, t 1.34) but its top 50 loses (IR -0.28);
the composite makes 0.19. No long/short book is above 0.03. Coverage limits
the test: gross profit is reported by about 200 to 290 members a month
(banks, insurers and firms that do not tag a gross profit drop out), shares
outstanding by 300 to 450, both by about 180 to 270; the out-of-sample window
is under nine years. 352 name-months show a one-year share change above
e (a factor of 2.7), mostly units errors in cover-page tags; they sit at the
extremes of the ranking and were left in as registered. No paper book.

<!-- generated below by lab.experiments.survey_equities (quality_issuance); edit above this line only -->

# Gross profitability and net share issuance: results (2026-10-21)

**Verdict: FAIL.** Pick (best selection-window IR of the top 50): NSI. Out of sample from 2018: top 50 Sharpe 0.64 (11.9 % a year, drawdown 43 %) against its universe's equal weight 0.68 and SPY 0.84; IR 0.15 (bootstrap 90 % band -0.34 to 0.65), 0.12 with costs doubled, 0.19 a day late; 12-1 momentum on the same universe IR 0.26; quintile long/short Sharpe -0.03. Deflated p 0.000.

## Gates (the pick's top 50, out of sample)

- fail: 1 IR above 0.3 against its universe's equal weight
- fail: 2 bootstrap 5 % bound of the IR above 0
- fail: 3 IR above the 12-1 momentum top 50 on the same universe
- PASS: 4 IR above 0 with costs doubled and a day late
- fail: 5 Sharpe above the equal weight's and active return positive in more than half the years

Kill rule (IR below 0.1): not hit.

## All trials

| trial | IR / Sharpe 2011-17 | IR / Sharpe OOS | IC 2011-17 | IC OOS | IC t OOS | deflated p |
|---|---|---|---|---|---|---|
| GP/A, top 50 | -0.20 | -0.28 | 0.01 | 0.02 | 1.34 | 0.00 |
| GP/A, quintile long/short | -0.20 | 0.01 | 0.01 | 0.02 | 1.34 | 0.00 |
| NSI, top 50 | 0.71 | 0.15 | 0.03 | 0.01 | 0.96 | 0.00 |
| NSI, quintile long/short | 0.64 | -0.03 | 0.03 | 0.01 | 0.96 | 0.00 |
| composite, top 50 | 0.10 | 0.19 | 0.02 | 0.01 | 1.22 | 0.00 |
| composite, quintile long/short | -0.11 | -0.03 | 0.02 | 0.01 | 1.22 | 0.00 |

Top 50 rows show the IR against the ranked universe's equal weight, long/short rows the book's Sharpe.

Members ranked per month (mean): GP/A: 2010 139, 2012 196, 2016 227, 2020 282, 2024 286, 2026 289; NSI: 2010 175, 2012 314, 2016 364, 2020 414, 2024 442, 2026 446; composite: 2010 94, 2012 181, 2016 208, 2020 260, 2024 267, 2026 266.

Name-months with |NSI| above 1 (log; likely a units error in the filing): 352.

Top 50 active return by year: 2018 -4.8 %, 2019 -0.2 %, 2020 -5.8 %, 2021 3.6 %, 2022 -3.0 %, 2023 4.2 %, 2024 4.1 %, 2025 8.5 %, 2026 0.4 %.

Pool: 1,140 hand trials, 600 factory genomes and the 33 trials registered with this study (33 of them run so far, standing for all): 1,773 trials; the best noise trial sits at an annual Sharpe of about 2.26 on trading days.
