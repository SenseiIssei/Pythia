<!-- generated below by lab.experiments.delist_hazard; edit above this line only -->

# Delisting hazard (survey O3): results

Generated 2026-10-21T15:32:31+00:00. Registered in `results/crypto_own_prereg.md` before the run. Panel to 2026-10-20; out of sample from 2024-01-01; books at 35 bps, coins Alpaca does not list in cash.

## Verdict

The model passes. No book improves by the gates. Useful as a filter: no.

- Out of sample (labelled rows from 2024, 351,549 coin-days, 8,095 within 60 days of an event): AUC 0.727 against the baseline's 0.648, difference +0.079, day-bootstrap band +0.046 to +0.108 (pass needs +0.050 and a band above 0).
- In sample (2022-23, also walk-forward): 0.435 against 0.597. 30-day label from 2024: 0.755 against 0.643. With the Coinbase and Kraken flags (information, leaks survival): 0.755.
- The top 5 % each day: 12.9 % of flagged coin-days are within 60 days of an event, against a base rate of 2.30 %. Their next 60 days: mean -12.2 % (median -19.5 %) against -6.4 % (median -14.2 %) for the other scored coins.

## The books

- **breakout_top10 · hazard top 5 % excluded**: fail. Sharpe 1.17 against the book's 1.17 (difference band 0.00 to 0.00), a day late 1.17, twin 1.06 against 1.06, drawdown 16 % against 16 %, minus gated BTC 0.53 (the book alone 0.53). Failed: 1 Sharpe and 2 of 3 years, 2 drawdown, 3 band above 0, 4 one day late, 6 deflated improvement.
- **tsmom_top20 · hazard top 5 % excluded**: fail. Sharpe 0.53 against the book's 0.53 (difference band 0.00 to 0.00), a day late 0.53, twin 0.21 against 0.21, drawdown 9 % against 9 %, minus gated BTC -0.06 (the book alone -0.06). Failed: 1 Sharpe and 2 of 3 years, 2 drawdown, 3 band above 0, 4 one day late, 5 twin, 6 deflated improvement, 7 beats gated BTC.
- **tsmom_tranches · hazard top 5 % excluded**: fail. Sharpe 0.65 against the book's 0.65 (difference band 0.00 to 0.00), a day late 0.65, twin 0.39 against 0.39, drawdown 9 % against 9 %, minus gated BTC 0.11 (the book alone 0.11). Failed: 1 Sharpe and 2 of 3 years, 2 drawdown, 3 band above 0, 4 one day late, 6 deflated improvement.

| book | variant | is | book_is | oos | book_oos | oos70 | book_oos70 | cagr_pct | dd_pct | book_dd_pct | years_better | band_lo | band_hi | late | twin | twin_book | deflated_diff | deflated_pool | dg | dg_lo | dg_hi | dg_book | days_changed_pct | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| breakout_top10 | hazard top 5 % excluded | 1.45 | 1.45 | 1.17 | 1.17 | 1.04 | 1.04 | 18.38 | 15.99 | 15.99 | 0 | 0.00 | 0.00 | 1.17 | 1.06 | 1.06 | 0.00 | 0.00 | 0.53 | -0.52 | 1.55 | 0.53 | 0.00 | fail |
| tsmom_top20 | hazard top 5 % excluded | 1.68 | 1.68 | 0.53 | 0.53 | 0.27 | 0.27 | 4.28 | 8.99 | 8.99 | 0 | 0.00 | 0.00 | 0.53 | 0.21 | 0.21 | 0.00 | 0.00 | -0.06 | -1.11 | 0.93 | -0.06 | 0.00 | fail |
| tsmom_tranches | hazard top 5 % excluded | 1.85 | 1.85 | 0.65 | 0.65 | 0.56 | 0.56 | 5.83 | 8.79 | 8.79 | 0 | 0.00 | 0.00 | 0.65 | 0.39 | 0.39 | 0.00 | 0.00 | 0.11 | -0.95 | 1.17 | 0.11 | 0.00 | fail |

How often the books held a flagged coin (out of sample, days with any position):

| book | version | book_days_holding_flagged_pct | weight_in_flagged_pct |
|---|---|---|---|
| breakout_top10 | live | 0.00 | 0.00 |
| breakout_top10 | twin | 0.00 | 0.00 |
| tsmom_top20 | live | 0.00 | 0.00 |
| tsmom_top20 | twin | 0.49 | 0.00 |
| tsmom_tranches | live | 0.00 | 0.00 |
| tsmom_tranches | twin | 1.49 | 0.00 |

The books alone and gated BTC (35 bps, out of sample from 2024):

| book | is | oos | cagr_pct | dd_pct | twin_oos | g_k | g_oos | minus_g |
|---|---|---|---|---|---|---|---|---|
| breakout_top10 | 1.45 | 1.17 | 18.38 | 15.99 | 1.06 | 0.40 | 0.71 | 0.53 |
| tsmom_top20 | 1.68 | 0.53 | 4.28 | 8.99 | 0.21 | 0.19 | 0.70 | -0.06 |
| tsmom_tranches | 1.85 | 0.65 | 5.83 | 8.79 | 0.39 | 0.20 | 0.72 | 0.11 |

## The model

189 events (2020: 6, 2021: 3, 2022: 26, 2023: 14, 2024: 40, 2025: 51, 2026: 49); 714,802 coin-days; first scored day 2022-01-01.

| year | rows | positives | model | baseline |
|---|---|---|---|---|
| 2022 | 112011 | 1542 | 0.530 | 0.626 |
| 2023 | 119147 | 777 | 0.429 | 0.637 |
| 2024 | 131002 | 2516 | 0.648 | 0.643 |
| 2025 | 137954 | 3064 | 0.751 | 0.608 |
| 2026 | 82593 | 2515 | 0.795 | 0.698 |

Gain importance of a model fit on every labelled row (information):

| feature | gain_pct |
|---|---|
| log_age | 16.0 |
| dd_ath | 15.5 |
| log_price | 13.9 |
| vol30 | 12.1 |
| log_amihud | 11.2 |
| r90 | 8.3 |
| adv_rank | 5.9 |
| log_adv28 | 4.8 |
| vol_28_90 | 4.4 |
| funding7 | 4.1 |
| perp | 2.1 |
| hours28 | 0.9 |
| vol_7_28 | 0.9 |
| perp_removed | 0.0 |

The most liquid events (swaps and rebrands among them):

| coin | last_day | adv28_musd_30d_before |
|---|---|---|
| FTMUSDT | 2025-01-12 | 146.11 |
| BTTUSDT | 2022-01-16 | 84.24 |
| BNXUSDT | 2025-03-17 | 62.13 |
| TONUSDT | 2026-06-29 | 61.66 |
| RNDRUSDT | 2024-07-21 | 51.56 |
| EOSUSDT | 2025-05-25 | 45.55 |
| NPXSUSDT | 2021-04-04 | 31.84 |
| MATICUSDT | 2024-09-09 | 30.86 |
| LENDUSDT | 2020-10-11 | 26.29 |
| COCOSUSDT | 2023-05-28 | 21.35 |
| AGIXUSDT | 2024-06-30 | 21.04 |
| ERDUSDT | 2020-08-30 | 18.28 |
| XMRUSDT | 2024-02-19 | 14.21 |
| HNTUSDT | 2022-10-13 | 12.76 |
| BZRXUSDT | 2021-12-19 | 11.66 |
| KEEPUSDT | 2022-02-15 | 11.57 |
| MKRUSDT | 2025-09-14 | 11.30 |
| EPSUSDT | 2022-05-08 | 10.42 |
| DEGOUSDT | 2026-04-27 | 8.56 |
| OMNIUSDT | 2025-09-28 | 8.24 |

Pool: 1,836 trials (1,140 hand before this registration, 600 factory, 96 registered on 2026-10-21 with O9's 2 forward trials); the best noise trial sits at an annual Sharpe of about 2.69. Gate 6 deflates each improvement over the 94 trials of the registration at the variance of the 94 trial difference Sharpes computed in this run.
