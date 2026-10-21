# Post-earnings drift from XBRL surprises

Run 2026-10-21 on the PC as registered in `results/pead_xbrl_prereg.md`
(committed first), against the synced data mirror read only: the point-in-time
S&P 500 panel, the EDGAR submissions index and the SEC company facts that
`equities_training` and `quality_issuance` cached; nothing was downloaded,
reports went to a scratch folder. Code: `lab.experiments.pead_xbrl`. The
tables below the marker are generated.

## What it says

**No. Both forms fail; the long-only book misses by a hair.**

- 24,721 original 10-Q and 10-K filings get a SUE (seasonal random walk on
  diluted EPS, scaled by the previous eight differences), about 1,600 to
  1,850 a year on 420 to 480 members from 2018. The values are read through
  each filing's own accession, so a later split-adjusted comparative never
  leaks into an earlier surprise; 13 % of the events needed a Q4 derived
  from the year minus nine months.
- **Long-only, top decile:** the selection window (2011 to 2017) picks 60
  sessions, but with an IR of only 0.14 (20 sessions: 0.09): there was next
  to no drift to select on. From 2018 the 60-session book makes **IR 0.49**
  against the equal weight of the CIK universe, 0.38 with costs doubled, 0.46
  a day late, active return positive in 7 of 9 years; the book itself makes
  Sharpe 0.83 (14.9 % a year, drawdown 37 %) against 0.67 for the equal
  weight and 0.84 for SPY. Four gates pass; **the bootstrap band of the IR
  (-0.00 to 1.02) touches zero**, so gate 2 fails and the trial fails as
  registered. Deflated p 0.0000 over 1,977. It never beats SPY: it is an
  equal-weight large-cap book with a small tilt.
- **Top minus bottom decile fails clearly:** 0.14 (20 sessions), -0.06 at
  10 bps, 2020 -18 % and 2025 -21 %. The bottom decile does not lag
  (+0.33 % over 20 sessions from 2018), so there is no short side to earn.
- The decile table is the honest summary: from 2018 the top decile beats the
  equal weight by about 0.5 % over 20 and 1.0 % over 60 sessions, every other
  decile sits within noise of zero, and the quarterly IC of SUE with the
  excess return is 0.01 (t 0.7 to 0.9). That is what Martineau (2022)
  describes: in large US shares the drift is mostly gone by the time a 10-Q
  is filed (a median 34 days after the quarter ends, typically weeks after
  the 8-K release).
- No paper book. Alpaca could trade the long side, but nothing here clears
  the bar, and an equal-weight top-decile book is closer to SPY than to an
  edge.

<!-- generated below by lab.experiments.pead_xbrl; edit above this line only -->

# Post-earnings drift from XBRL surprises: results

Generated 2026-10-21T21:13:06+00:00. Registered in `results/pead_xbrl_prereg.md` before the run.

Point-in-time S&P 500 members with a CIK, sessions to 2026-10-16; 24,721 10-Q and 10-K filings with a SUE (13 % with a Q4 derived from the year minus nine months); median 34 days from period end to filing. Entry at the open of the second session after the filing. Selection 2011 to 2017, out of sample from 2018. 5 bps a side plus SEC fee and TAF; the universe's equal weight makes Sharpe 0.67 out of sample, SPY 0.84.

## Long-only: **Fail.** Pick: **long top decile · 60 sessions**

- 1 IR above 0.3: yes
- 2 bootstrap 5 % bound of the IR above 0: no
- 3 IR above 0 with costs doubled and a day late: yes
- 4 active return positive in more than half the years: yes
- 5 the book's Sharpe above the equal weight's: yes

IR 0.49 out of sample (bootstrap band -0.00 to 1.02), 0.38 with costs doubled, 0.46 a day late; the book's Sharpe 0.83, 14.9 % a year, drawdown 37 %, invested on 100 % of sessions. Deflated p 0.0000. Active return by year: 2018 -4.8 %, 2019 +5.9 %, 2020 +0.5 %, 2021 +4.7 %, 2022 +3.6 %, 2023 +4.5 %, 2024 +5.8 %, 2025 -0.4 %, 2026 +7.5 %.

## Top minus bottom decile: **Fail.** Pick: **top minus bottom decile · 20 sessions**

- 1 Sharpe above 0.5 at 5 bps and above 0 at 10 bps: no
- 2 bootstrap 5 % bound above 0: no
- 3 positive in more than half the years: yes
- 4 a day late above 0: yes

Sharpe 0.14 out of sample (bootstrap band -0.33 to 0.67), -0.06 at 10 bps, 0.14 a day late, drawdown 33 %. Deflated p 0.0000. By year: 2018 +6.0 %, 2019 -0.9 %, 2020 -18.3 %, 2021 +14.4 %, 2022 +19.8 %, 2023 +2.9 %, 2024 +0.9 %, 2025 -20.5 %, 2026 +11.5 %.

## Every trial

| trial | sel | oos | oos_2x | oos_late | book_sel | book_oos | book_cagr_pct | book_dd_pct | invested_pct | turnover_yr | deflated_p |
|---|---|---|---|---|---|---|---|---|---|---|---|
| long top decile · 20 sessions | 0.09 | 0.64 | 0.43 | 0.74 | 0.83 | 0.81 | 11.38 | 36.06 | 94.43 | 28.64 | 0.00 |
| top minus bottom decile · 20 sessions | 0.16 | 0.14 | -0.06 | 0.14 | n/a | n/a | 0.92 | 33.22 | n/a | n/a | 0.00 |
| long top decile · 60 sessions | 0.14 | 0.49 | 0.38 | 0.46 | 0.98 | 0.83 | 14.94 | 36.70 | 100.00 | 15.81 | 0.00 |
| top minus bottom decile · 60 sessions | -0.16 | 0.10 | -0.03 | 0.08 | n/a | n/a | 0.40 | 29.24 | n/a | n/a | 0.00 |

Long rows: `sel` and `oos` are the IR of the active return (the book minus its invested share times the equal weight), `book_*` the book itself; long/short rows: the book's Sharpe. Annualised over 252 sessions.


## Drift by SUE decile (information only)

| H | window | events | d1 | d2 | d3 | d4 | d5 | d6 | d7 | d8 | d9 | d10 | ic | ic_t |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 20 | 2011-2017 | 9366 | -0.35 | -0.24 | -0.13 | -0.04 | -0.18 | 0.06 | -0.13 | 0.15 | 0.08 | 0.12 | 0.03 | 1.98 |
| 20 | from 2018 | 15333 | 0.33 | 0.13 | -0.02 | 0.01 | -0.33 | -0.01 | -0.01 | -0.09 | 0.02 | 0.54 | 0.01 | 0.67 |
| 60 | 2011-2017 | 9366 | -0.14 | -0.38 | 0.34 | -0.19 | -0.13 | 0.17 | 0.23 | -0.12 | 0.27 | 0.09 | 0.01 | 0.82 |
| 60 | from 2018 | 14960 | -0.25 | -0.19 | 0.20 | -0.08 | -0.62 | 0.07 | -0.05 | -0.11 | -0.00 | 0.97 | 0.01 | 0.85 |

Mean return of each decile's events from the open of f+2 over H sessions minus the equal weight's, in %; deciles by the trailing 365-day breakpoints. `ic`: mean quarterly Spearman of SUE with that excess return, t over quarters.


Coverage (filings with a SUE on a member with a CIK, by filing year):

| year | events | companies | top |
|---|---|---|---|
| 2010 | 6 | 6 | 0 |
| 2011 | 868 | 255 | 75 |
| 2012 | 1261 | 330 | 129 |
| 2013 | 1341 | 349 | 140 |
| 2014 | 1379 | 357 | 153 |
| 2015 | 1426 | 369 | 116 |
| 2016 | 1507 | 395 | 162 |
| 2017 | 1584 | 412 | 177 |
| 2018 | 1620 | 417 | 166 |
| 2019 | 1659 | 426 | 103 |
| 2020 | 1707 | 442 | 191 |
| 2021 | 1739 | 448 | 274 |
| 2022 | 1783 | 459 | 113 |
| 2023 | 1814 | 463 | 213 |
| 2024 | 1818 | 466 | 164 |
| 2025 | 1856 | 474 | 209 |
| 2026 | 1353 | 480 | 195 |

## Pool

Pool: 1,977 trials (1,353 hand before this registration, 600 factory as read now, 24 registered together on 2026-10-21: positioning_xs 5, taker_imbalance_xs 13, hedged_breakout 2, pead_xbrl 4); the best noise trial sits at an annual Sharpe of about 2.29. The next study starts from 1,377 hand trials.
