# Investor attention from Wikipedia page views

Run 2026-10-21 on the server as registered in
`results/attention_wiki_prereg.md` (committed before the page views were
downloaded). Page views from `lab.collect.wiki` (55 coins, 52 articles, 317
titles with their redirects, history from 2015-07-01; job `wiki-collect`
keeps it daily). Code: `lab.experiments.attention_wiki`. The tables below
the marker are generated.

## What it says

**No (killed for the cross-section, nothing passes).**

- The cross-sectional rank IC of abnormal attention with the next 7 days is
  zero out of sample: +0.006 (t -0.29, 145 weeks; kill above -1). In sample
  it pointed the other way from the prior (+0.037, t 2.0: hot coins kept
  rising for a week in 2020 to 2023), and that did not last either.
- The weekly quintile long/short on perps (long the quiet fifth, short the
  hot fifth) loses: **-0.70 at 10 bps** (-0.58 at the 2 bps maker level,
  -0.85 at 20), -25 % a year, drawdown 73 %, correlation with BTC -0.05,
  negative in every year; deflated p 0.00.
- As a filter it hurts every Alpaca book: breakout_top10 0.70 against 1.17,
  tsmom_top20 0.22 against 0.53, tsmom_tranches 0.41 against 0.65 (35 bps).
  The books hold a flagged coin on 75 to 92 % of days: a momentum book buys
  exactly the coins whose attention is rising, so removing the hot third
  removes its winners. The drawdowns fall (8 against 16 %) only because the
  books sit in cash more.
- As a BTC switch it loses too: BTC out of the market on attention spikes
  0.57 against 0.75 held (drawdown 43 % against 53 %), on top of the 200-day
  gate 0.32 against 0.69. Stepping out on a Bitcoin attention spike (22 %
  of days) missed more gains than it avoided losses.

Data notes: views of day d are used from the close of d+1. The mapping is
today's (articles exist for coins that became notable), the redirect list
is today's, and the "user" agent filter lets some bots through. A few
articles are thin (Aave has views on 523 days in eight years and is ranked
only briefly). None of this can turn an IC of zero into a signal.

<!-- generated below by lab.experiments.attention_wiki; edit above this line only -->

# Investor attention from Wikipedia page views: results

Generated 2026-10-21T19:24:22+00:00. Registered in `results/attention_wiki_prereg.md` before the page views were downloaded. Panel to 2026-10-20; out of sample from 2024-01-01. 55 coins mapped (52 in the panel), 317 titles (articles and their redirects). A decision at the close of day t uses views up to day t-1.

## Verdict

Cross-section killed: the out-of-sample 7-day rank IC t is -0.29 (kill above -1). No trial passes its gates.

- Rank IC with the next 7 days: in sample +0.037 (t 2.00, 178 weeks), out of sample +0.006 (t -0.29, 145 weeks); by year 2024 +0.025 (t 0.64), 2025 -0.015 (t -0.36), 2026 +0.009 (t -0.93). 28 days: in sample +0.056 (t 0.89), out of sample -0.037 (t -0.81).
- Long/short on perps (long the quiet fifth, short the hot fifth, weekly): out of sample -0.70 at 10 bps (2 bps -0.58, 20 bps -0.85, 41 bps -1.16), -24.6 % a year, drawdown 73 %, correlation with BTC -0.05, years -0.31 / -0.51 / -1.41, a day late -0.43, bootstrap band -1.73 to 0.38, deflated p 0.0000; in sample -0.46. Gates failed: 1 Sharpe above 0.5 at 10 bps and above 0 at 20 bps, 2 positive in 2 of 2024, 2025, 2026, 3 one day late above 0, 4 bootstrap 5 % above 0.
  Legs from 2024 (% of capital a year): long price 16.1, short price -32.1, long funding -2.2, short funding 0.1; turnover 48x a year.

## The filter on the three books (35 bps, coins Alpaca does not list in cash)

- **breakout_top10 · attention filter**: fail. Sharpe 0.70 against the book's 1.17 (difference band -0.99 to 0.09), a day late 0.73, twin 0.50 against 1.06, drawdown 8 % against 16 %, minus gated BTC -0.43 (the book alone 0.53). Failed: 1 Sharpe and 2 of 3 years, 3 band above 0, 4 one day late, 5 twin, 6 deflated improvement, 7 beats gated BTC.
- **tsmom_top20 · attention filter**: fail. Sharpe 0.22 against the book's 0.53 (difference band -0.63 to 0.03), a day late 0.11, twin -0.10 against 0.21, drawdown 8 % against 9 %, minus gated BTC -0.63 (the book alone -0.06). Failed: 1 Sharpe and 2 of 3 years, 3 band above 0, 4 one day late, 5 twin, 6 deflated improvement, 7 beats gated BTC.
- **tsmom_tranches · attention filter**: fail. Sharpe 0.41 against the book's 0.65 (difference band -0.56 to 0.06), a day late 0.40, twin 0.15 against 0.39, drawdown 6 % against 9 %, minus gated BTC -0.46 (the book alone 0.11). Failed: 1 Sharpe and 2 of 3 years, 3 band above 0, 4 one day late, 5 twin, 6 deflated improvement, 7 beats gated BTC.

| book | variant | is | book_is | oos | book_oos | oos70 | book_oos70 | cagr_pct | dd_pct | book_dd_pct | years_better | band_lo | band_hi | late | twin | twin_book | deflated_diff | deflated_pool | dg | dg_lo | dg_hi | dg_book | days_changed_pct | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| breakout_top10 | attention filter | 1.30 | 1.45 | 0.70 | 1.17 | 0.48 | 1.04 | 4.61 | 8.48 | 15.99 | 1 | -0.99 | 0.09 | 0.73 | 0.50 | 1.06 | 0.01 | 0.00 | -0.43 | -1.33 | 0.52 | 0.53 | 54.30 | fail |
| tsmom_top20 | attention filter | 1.65 | 1.68 | 0.22 | 0.53 | -0.16 | 0.27 | 1.15 | 7.62 | 8.99 | 0 | -0.63 | 0.03 | 0.11 | -0.10 | 0.21 | 0.02 | 0.00 | -0.63 | -1.61 | 0.37 | -0.06 | 50.68 | fail |
| tsmom_tranches | attention filter | 1.87 | 1.85 | 0.41 | 0.65 | 0.27 | 0.56 | 2.38 | 6.25 | 8.79 | 0 | -0.56 | 0.06 | 0.40 | 0.15 | 0.39 | 0.02 | 0.00 | -0.46 | -1.45 | 0.50 | 0.11 | 61.43 | fail |

How often the books held a flagged coin, and the share of their weight that is ranked at all (out of sample, days with any position):

| book | days_holding_flagged_pct | held_weight_ranked_pct |
|---|---|---|
| breakout_top10 | 75.36 | 93.72 |
| tsmom_top20 | 86.83 | 88.01 |
| tsmom_tranches | 92.09 | 87.89 |

## BTC switches (35 bps)

- **BTC unless spike** against BTC held: 0.57 vs 0.75, drawdown 43 % vs 53 %, 15.5 % vs 27.2 % a year, band of the difference -0.82 to 0.39, a day late 0.47, better in 2 of 3 years; in cash 22 % of days from 2024 (22 % before); improvement deflated p 0.080. Failed: 1 Sharpe above the benchmark, 2 of 3 years, 3 band of the difference above 0, 4 a day late above the benchmark.
- **gated BTC unless spike** against gated BTC: 0.32 vs 0.69, drawdown 46 % vs 33 %, 5.2 % vs 20.4 % a year, band of the difference -1.08 to 0.27, a day late 0.25, better in 2 of 3 years; in cash 22 % of days from 2024 (22 % before); improvement deflated p 0.033. Failed: 1 Sharpe above the benchmark, 2 of 3 years, 2 drawdown not above the benchmark's, 3 band of the difference above 0, 4 a day late above the benchmark.

## Every trial

| key | book | is | oos |
|---|---|---|---|
| attention quintile long/short, perps, 10 bps |  | -0.46 | -0.70 |
| attention long/short one day late |  | -0.52 | -0.43 |
| attention filter | breakout_top10 | 1.30 | 0.70 |
| attention filter · late | breakout_top10 | 1.48 | 0.73 |
| attention filter · twin | breakout_top10 | 1.17 | 0.50 |
| attention filter | tsmom_top20 | 1.65 | 0.22 |
| attention filter · late | tsmom_top20 | 1.62 | 0.11 |
| attention filter · twin | tsmom_top20 | 1.29 | -0.10 |
| attention filter | tsmom_tranches | 1.87 | 0.41 |
| attention filter · late | tsmom_tranches | 1.87 | 0.40 |
| attention filter · twin | tsmom_tranches | 1.53 | 0.15 |
| BTC unless spike |  | 0.42 | 0.57 |
| gated BTC unless spike |  | 0.45 | 0.32 |

## Coverage

| year | median_ranked | days_ranked |
|---|---|---|
| 2020 | 16.00 | 269 |
| 2021 | 22.00 | 365 |
| 2022 | 24.00 | 365 |
| 2023 | 19.00 | 365 |
| 2024 | 19.00 | 366 |
| 2025 | 21.00 | 365 |
| 2026 | 15.00 | 293 |

The Alpaca coins (att = log of the 7-day over the 90-day mean views):

| coin | first_ranked | mean_att_oos |
|---|---|---|
| AAVE | 2025-01-26 | -2.72 |
| ADA | 2020-11-04 | -0.11 |
| AVAX | 2021-11-27 | -0.07 |
| BCH | 2020-04-07 | -0.07 |
| BTC | 2020-04-07 | -0.07 |
| DOGE | 2020-07-08 | -0.11 |
| DOT | 2021-04-10 | -0.05 |
| ETH | 2020-04-07 | -0.05 |
| FIL | 2021-01-21 | -0.09 |
| LINK | 2021-07-25 | -0.12 |
| LTC | 2020-04-07 | -0.05 |
| PEPE | never | n/a |
| SOL | 2021-11-20 | -0.06 |
| UNI | 2021-03-05 | -0.08 |
| XRP | 2020-04-07 | -0.07 |

## Pool

Pool: 1,953 trials (1,328 hand before this registration, 600 factory as read now, 25 registered together on 2026-10-21: perps_neutral_portfolio 3, attention_wiki 13, intraday_tsmom 9); the best noise trial sits at an annual Sharpe of about 2.75. The next study starts from 1,353 hand trials. Gate 6 deflates each improvement over the 13 trials at the variance of this study's 11 improvements.
