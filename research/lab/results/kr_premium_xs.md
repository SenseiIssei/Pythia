<!-- generated below by lab.experiments.kr_premium_xs; edit above this line only -->

# Per-coin Korean premium (survey O4): results

Generated 2026-10-21T15:53:22+00:00. Registered in `results/crypto_own_prereg.md` before the run and before the Upbit history was downloaded. Panel to 2026-10-20; out of sample from 2024-01-01; books at 35 bps, coins Alpaca does not list in cash. Upbit serves only the markets it lists today, so the coins on both are today's Upbit survivors; a pass could only be experimental and forward.

## Verdict

The rank IC passes (t -2.66). At least one book passes the gates (experimental at best).

- 201 Upbit KRW markets matched a Binance coin; 13 dropped by the same-ticker guard (AIUSDT, ANKRUSDT, AXSUSDT, BTTUSDT, CVCUSDT~0, DATAUSDT, HBARUSDT, LSKUSDT, MTLUSDT, ONGUSDT, POLYXUSDT, STRAXUSDT~0). First ranked day 2020-03-01.
- Rank IC, 7 days: in sample -0.014 (t -1.81, 178 weeks), out of sample -0.031 (t -2.66, 145 weeks); by year 2024 -0.015 (t -0.95), 2025 -0.032 (t -1.53), 2026 -0.052 (t -2.24).
- Rank IC, 28 days: in sample -0.022 (t -1.17), out of sample -0.036 (t -1.05, 35 periods).
- Long/short on perps (information, never wired): in sample -0.11, out of sample -0.92 at 41 bps with funding, -14.1 % a year, drawdown 48 %; years 0.57 / -2.03 / -1.89.

## The books

- **breakout_top10 · KR premium tilt**: fail. Sharpe 1.20 against the book's 1.17 (difference band -0.02 to 0.08), a day late 1.18, twin 1.09 against 1.06, drawdown 16 % against 16 %, minus gated BTC 0.58 (the book alone 0.53). Failed: 3 band above 0, 6 deflated improvement.
- **tsmom_top20 · KR premium filter**: fail. Sharpe 0.61 against the book's 0.53 (difference band -0.03 to 0.19), a day late 0.67, twin 0.25 against 0.21, drawdown 8 % against 9 %, minus gated BTC -0.06 (the book alone -0.06). Failed: 3 band above 0, 6 deflated improvement, 7 beats gated BTC.
- **tsmom_tranches · KR premium filter**: pass, experimental. Sharpe 0.87 against the book's 0.65 (difference band 0.08 to 0.34), a day late 0.87, twin 0.55 against 0.39, drawdown 7 % against 9 %, minus gated BTC 0.28 (the book alone 0.11). Failed: 6 deflated improvement.

| book | variant | is | book_is | oos | book_oos | oos70 | book_oos70 | cagr_pct | dd_pct | book_dd_pct | years_better | band_lo | band_hi | late | twin | twin_book | deflated_diff | deflated_pool | dg | dg_lo | dg_hi | dg_book | days_changed_pct | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| breakout_top10 | KR premium tilt | 1.46 | 1.45 | 1.20 | 1.17 | 1.08 | 1.04 | 19.66 | 15.90 | 15.99 | 3 | -0.02 | 0.08 | 1.18 | 1.09 | 1.06 | 0.05 | 0.01 | 0.58 | -0.50 | 1.63 | 0.53 | 48.24 | fail |
| tsmom_top20 | KR premium filter | 1.66 | 1.68 | 0.61 | 0.53 | 0.28 | 0.27 | 4.44 | 7.58 | 8.99 | 2 | -0.03 | 0.19 | 0.67 | 0.25 | 0.21 | 0.00 | 0.00 | -0.06 | -1.13 | 0.97 | -0.06 | 33.79 | fail |
| tsmom_tranches | KR premium filter | 1.80 | 1.85 | 0.87 | 0.65 | 0.75 | 0.56 | 6.96 | 7.40 | 8.79 | 3 | 0.08 | 0.34 | 0.87 | 0.55 | 0.39 | 0.01 | 0.00 | 0.28 | -0.78 | 1.33 | 0.11 | 57.52 | pass, experimental |

Both forms per book (35 bps):

| book | form | is | book_is | oos | book_oos |
|---|---|---|---|---|---|
| breakout_top10 | filter | 1.35 | 1.45 | 1.36 | 1.17 |
| breakout_top10 | tilt | 1.46 | 1.45 | 1.20 | 1.17 |
| tsmom_top20 | filter | 1.66 | 1.68 | 0.61 | 0.53 |
| tsmom_top20 | tilt | 1.58 | 1.68 | 0.53 | 0.53 |
| tsmom_tranches | filter | 1.80 | 1.85 | 0.87 | 0.65 |
| tsmom_tranches | tilt | 1.78 | 1.85 | 0.73 | 0.65 |

How often the books held a coin in the worst third (out of sample, days with any position):

| book | days_holding_worst_third_pct |
|---|---|
| breakout_top10 | 25.76 |
| tsmom_top20 | 52.85 |
| tsmom_tranches | 57.12 |

The books alone and gated BTC:

| book | is | oos | cagr_pct | dd_pct | twin_oos | g_k | g_oos | minus_g |
|---|---|---|---|---|---|---|---|---|
| breakout_top10 | 1.45 | 1.17 | 18.38 | 15.99 | 1.06 | 0.40 | 0.71 | 0.53 |
| tsmom_top20 | 1.68 | 0.53 | 4.28 | 8.99 | 0.21 | 0.19 | 0.70 | -0.06 |
| tsmom_tranches | 1.85 | 0.65 | 5.83 | 8.79 | 0.39 | 0.20 | 0.72 | 0.11 |

## Coverage

| year | median_coins | days_ranked |
|---|---|---|
| 2020 | 21.00 | 306 |
| 2021 | 35.00 | 365 |
| 2022 | 44.00 | 365 |
| 2023 | 48.00 | 365 |
| 2024 | 69.00 | 366 |
| 2025 | 92.00 | 365 |
| 2026 | 102.00 | 293 |

The Alpaca coins (s is the coin's premium minus BTC's, 7-day mean):

| coin | first_signal | mean_s_pct_oos |
|---|---|---|
| AAVE | 2021-10-31 | 0.01 |
| ADA | 2020-03-01 | 0.03 |
| AVAX | 2022-02-12 | 0.04 |
| BCH | 2020-03-01 | 0.03 |
| BTC | none | n/a |
| DOGE | 2021-02-28 | 0.06 |
| DOT | 2020-10-18 | 0.01 |
| ETH | 2020-03-01 | 0.01 |
| FIL | 2025-04-08 | 0.03 |
| LINK | 2020-08-08 | 0.02 |
| LTC | none | n/a |
| PEPE | 2024-11-18 | 0.03 |
| SOL | 2021-10-19 | 0.02 |
| UNI | 2024-10-26 | 0.01 |
| XRP | 2020-03-01 | -0.00 |

Pool: 1,836 trials (1,140 hand before this registration, 600 factory, 96 registered on 2026-10-21 with O9's 2 forward trials); the best noise trial sits at an annual Sharpe of about 2.69. Gate 6 deflates each improvement over the 94 trials of the registration at the variance of the 93 book modifications computed in this run (the long/short trial has no book to differ from).
