<!-- generated below by lab.experiments.xs_factors; edit above this line only -->

# Cross-sectional crypto factors as book filters and tilts: results

Generated 2026-10-21T15:32:31+00:00. Registered in `results/crypto_own_prereg.md` before the run. Panel to 2026-10-20; out of sample from 2024-01-01; books at 35 bps, coins Alpaca does not list in cash; factors ranked among the 50 most liquid eligible coins each day, higher = worse.

## Verdict per factor

- **ivol**: killed (below the book in all three). breakout_top10 filter 1.14 vs 1.17; tsmom_top20 filter 0.50 vs 0.53; tsmom_tranches filter 0.63 vs 0.65.
- **max**: passes on tsmom_tranches (pass, experimental). breakout_top10 tilt 1.19 vs 1.17; tsmom_top20 tilt 0.54 vs 0.53; tsmom_tranches filter 0.85 vs 0.65.
- **skew**: fails. breakout_top10 tilt 1.23 vs 1.17; tsmom_top20 tilt 0.53 vs 0.53; tsmom_tranches filter 0.84 vs 0.65.
- **vshock**: fails. breakout_top10 tilt 1.19 vs 1.17; tsmom_top20 tilt 0.38 vs 0.53; tsmom_tranches tilt 0.64 vs 0.65.
- **size**: fails. breakout_top10 tilt 1.18 vs 1.17; tsmom_top20 tilt 0.48 vs 0.53; tsmom_tranches tilt 0.65 vs 0.65.
- **rev7**: fails. breakout_top10 tilt 1.20 vs 1.17; tsmom_top20 tilt 0.33 vs 0.53; tsmom_tranches tilt 0.63 vs 0.65.

1 of 18 factor-book picks pass gates 1 to 5 and 7.

## Gates per pick

- **breakout_top10 · ivol filter**: fail. Sharpe 1.14 against the book's 1.17 (difference band -0.26 to 0.19), a day late 1.17, twin 1.21 against 1.06, drawdown 15 % against 16 %, minus gated BTC 0.38 (the book alone 0.53). Failed: 1 Sharpe and 2 of 3 years, 3 band above 0, 6 deflated improvement.
- **tsmom_top20 · ivol filter**: fail. Sharpe 0.50 against the book's 0.53 (difference band -0.13 to 0.08), a day late 0.49, twin 0.49 against 0.21, drawdown 8 % against 9 %, minus gated BTC -0.13 (the book alone -0.06). Failed: 1 Sharpe and 2 of 3 years, 3 band above 0, 4 one day late, 6 deflated improvement, 7 beats gated BTC.
- **tsmom_tranches · ivol filter**: fail. Sharpe 0.63 against the book's 0.65 (difference band -0.10 to 0.07), a day late 0.64, twin 0.61 against 0.39, drawdown 8 % against 9 %, minus gated BTC 0.05 (the book alone 0.11). Failed: 1 Sharpe and 2 of 3 years, 3 band above 0, 4 one day late, 6 deflated improvement.
- **breakout_top10 · max tilt**: fail. Sharpe 1.19 against the book's 1.17 (difference band -0.03 to 0.07), a day late 1.20, twin 1.09 against 1.06, drawdown 16 % against 16 %, minus gated BTC 0.55 (the book alone 0.53). Failed: 2 drawdown, 3 band above 0, 6 deflated improvement.
- **tsmom_top20 · max tilt**: fail. Sharpe 0.54 against the book's 0.53 (difference band -0.05 to 0.07), a day late 0.54, twin 0.33 against 0.21, drawdown 8 % against 9 %, minus gated BTC -0.08 (the book alone -0.06). Failed: 3 band above 0, 6 deflated improvement, 7 beats gated BTC.
- **tsmom_tranches · max filter**: pass, experimental. Sharpe 0.85 against the book's 0.65 (difference band 0.05 to 0.35), a day late 0.83, twin 0.76 against 0.39, drawdown 8 % against 9 %, minus gated BTC 0.26 (the book alone 0.11). Failed: 6 deflated improvement.
- **breakout_top10 · skew tilt**: fail. Sharpe 1.23 against the book's 1.17 (difference band -0.02 to 0.13), a day late 1.22, twin 1.11 against 1.06, drawdown 16 % against 16 %, minus gated BTC 0.62 (the book alone 0.53). Failed: 2 drawdown, 3 band above 0, 6 deflated improvement.
- **tsmom_top20 · skew tilt**: fail. Sharpe 0.53 against the book's 0.53 (difference band -0.07 to 0.08), a day late 0.54, twin 0.23 against 0.21, drawdown 9 % against 9 %, minus gated BTC -0.05 (the book alone -0.06). Failed: 2 drawdown, 3 band above 0, 6 deflated improvement, 7 beats gated BTC.
- **tsmom_tranches · skew filter**: fail. Sharpe 0.84 against the book's 0.65 (difference band -0.02 to 0.35), a day late 0.87, twin 0.61 against 0.39, drawdown 6 % against 9 %, minus gated BTC 0.12 (the book alone 0.11). Failed: 3 band above 0, 6 deflated improvement.
- **breakout_top10 · vshock tilt**: fail. Sharpe 1.19 against the book's 1.17 (difference band -0.05 to 0.08), a day late 1.18, twin 1.07 against 1.06, drawdown 16 % against 16 %, minus gated BTC 0.57 (the book alone 0.53). Failed: 1 Sharpe and 2 of 3 years, 2 drawdown, 3 band above 0, 6 deflated improvement.
- **tsmom_top20 · vshock tilt**: fail. Sharpe 0.38 against the book's 0.53 (difference band -0.22 to -0.07), a day late 0.40, twin 0.06 against 0.21, drawdown 9 % against 9 %, minus gated BTC -0.28 (the book alone -0.06). Failed: 1 Sharpe and 2 of 3 years, 2 drawdown, 3 band above 0, 4 one day late, 5 twin, 6 deflated improvement, 7 beats gated BTC.
- **tsmom_tranches · vshock tilt**: fail. Sharpe 0.64 against the book's 0.65 (difference band -0.10 to 0.09), a day late 0.66, twin 0.34 against 0.39, drawdown 8 % against 9 %, minus gated BTC 0.03 (the book alone 0.11). Failed: 1 Sharpe and 2 of 3 years, 3 band above 0, 5 twin, 6 deflated improvement.
- **breakout_top10 · size tilt**: fail. Sharpe 1.18 against the book's 1.17 (difference band -0.02 to 0.04), a day late 1.18, twin 1.07 against 1.06, drawdown 16 % against 16 %, minus gated BTC 0.56 (the book alone 0.53). Failed: 3 band above 0, 6 deflated improvement.
- **tsmom_top20 · size tilt**: fail. Sharpe 0.48 against the book's 0.53 (difference band -0.08 to -0.01), a day late 0.48, twin 0.11 against 0.21, drawdown 9 % against 9 %, minus gated BTC -0.10 (the book alone -0.06). Failed: 1 Sharpe and 2 of 3 years, 2 drawdown, 3 band above 0, 4 one day late, 5 twin, 6 deflated improvement, 7 beats gated BTC.
- **tsmom_tranches · size tilt**: fail. Sharpe 0.65 against the book's 0.65 (difference band -0.05 to 0.04), a day late 0.65, twin 0.33 against 0.39, drawdown 9 % against 9 %, minus gated BTC 0.13 (the book alone 0.11). Failed: 1 Sharpe and 2 of 3 years, 2 drawdown, 3 band above 0, 4 one day late, 5 twin, 6 deflated improvement.
- **breakout_top10 · rev7 tilt**: fail. Sharpe 1.20 against the book's 1.17 (difference band -0.04 to 0.08), a day late 1.15, twin 1.10 against 1.06, drawdown 16 % against 16 %, minus gated BTC 0.57 (the book alone 0.53). Failed: 2 drawdown, 3 band above 0, 4 one day late, 6 deflated improvement.
- **tsmom_top20 · rev7 tilt**: fail. Sharpe 0.33 against the book's 0.53 (difference band -0.29 to -0.10), a day late 0.37, twin -0.08 against 0.21, drawdown 9 % against 9 %, minus gated BTC -0.33 (the book alone -0.06). Failed: 1 Sharpe and 2 of 3 years, 2 drawdown, 3 band above 0, 4 one day late, 5 twin, 6 deflated improvement, 7 beats gated BTC.
- **tsmom_tranches · rev7 tilt**: fail. Sharpe 0.63 against the book's 0.65 (difference band -0.11 to 0.06), a day late 0.67, twin 0.26 against 0.39, drawdown 8 % against 9 %, minus gated BTC -0.00 (the book alone 0.11). Failed: 1 Sharpe and 2 of 3 years, 3 band above 0, 5 twin, 6 deflated improvement, 7 beats gated BTC.

| book | variant | is | book_is | oos | book_oos | oos70 | book_oos70 | cagr_pct | dd_pct | book_dd_pct | years_better | band_lo | band_hi | late | twin | twin_book | deflated_diff | deflated_pool | dg | dg_lo | dg_hi | dg_book | days_changed_pct | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| breakout_top10 | ivol filter | 1.52 | 1.45 | 1.14 | 1.17 | 1.00 | 1.04 | 15.61 | 15.28 | 15.99 | 3 | -0.26 | 0.19 | 1.17 | 1.21 | 1.06 | 0.00 | 0.00 | 0.38 | -0.65 | 1.46 | 0.53 | 27.44 | fail |
| tsmom_top20 | ivol filter | 1.64 | 1.68 | 0.50 | 0.53 | 0.24 | 0.27 | 3.90 | 7.86 | 8.99 | 1 | -0.13 | 0.08 | 0.49 | 0.49 | 0.21 | 0.00 | 0.00 | -0.13 | -1.19 | 0.87 | -0.06 | 26.95 | fail |
| tsmom_tranches | ivol filter | 1.85 | 1.85 | 0.63 | 0.65 | 0.54 | 0.56 | 5.44 | 7.90 | 8.79 | 1 | -0.10 | 0.07 | 0.64 | 0.61 | 0.39 | 0.00 | 0.00 | 0.05 | -1.00 | 1.12 | 0.11 | 55.27 | fail |
| breakout_top10 | max tilt | 1.40 | 1.45 | 1.19 | 1.17 | 1.07 | 1.04 | 19.00 | 16.25 | 15.99 | 2 | -0.03 | 0.07 | 1.20 | 1.09 | 1.06 | 0.01 | 0.01 | 0.55 | -0.52 | 1.59 | 0.53 | 48.24 | fail |
| tsmom_top20 | max tilt | 1.59 | 1.68 | 0.54 | 0.53 | 0.25 | 0.27 | 4.22 | 8.41 | 8.99 | 2 | -0.05 | 0.07 | 0.54 | 0.33 | 0.21 | 0.00 | 0.00 | -0.08 | -1.13 | 0.90 | -0.06 | 50.78 | fail |
| tsmom_tranches | max filter | 1.88 | 1.85 | 0.85 | 0.65 | 0.75 | 0.56 | 6.83 | 7.77 | 8.79 | 3 | 0.05 | 0.35 | 0.83 | 0.76 | 0.39 | 0.01 | 0.00 | 0.26 | -0.81 | 1.34 | 0.11 | 58.59 | pass, experimental |
| breakout_top10 | skew tilt | 1.43 | 1.45 | 1.23 | 1.17 | 1.11 | 1.04 | 20.48 | 16.10 | 15.99 | 2 | -0.02 | 0.13 | 1.22 | 1.11 | 1.06 | 0.05 | 0.01 | 0.62 | -0.48 | 1.68 | 0.53 | 48.24 | fail |
| tsmom_top20 | skew tilt | 1.63 | 1.68 | 0.53 | 0.53 | 0.25 | 0.27 | 4.33 | 9.06 | 8.99 | 2 | -0.07 | 0.08 | 0.54 | 0.23 | 0.21 | 0.00 | 0.00 | -0.05 | -1.10 | 0.94 | -0.06 | 50.78 | fail |
| tsmom_tranches | skew filter | 2.03 | 1.85 | 0.84 | 0.65 | 0.73 | 0.56 | 5.99 | 5.99 | 8.79 | 2 | -0.02 | 0.35 | 0.87 | 0.61 | 0.39 | 0.00 | 0.00 | 0.12 | -0.90 | 1.09 | 0.11 | 58.59 | fail |
| breakout_top10 | vshock tilt | 1.45 | 1.45 | 1.19 | 1.17 | 1.06 | 1.04 | 19.29 | 16.34 | 15.99 | 1 | -0.05 | 0.08 | 1.18 | 1.07 | 1.06 | 0.01 | 0.01 | 0.57 | -0.54 | 1.62 | 0.53 | 48.24 | fail |
| tsmom_top20 | vshock tilt | 1.58 | 1.68 | 0.38 | 0.53 | 0.06 | 0.27 | 2.93 | 9.06 | 8.99 | 1 | -0.22 | -0.07 | 0.40 | 0.06 | 0.21 | 0.00 | 0.00 | -0.28 | -1.35 | 0.73 | -0.06 | 50.78 | fail |
| tsmom_tranches | vshock tilt | 1.84 | 1.85 | 0.64 | 0.65 | 0.54 | 0.56 | 5.30 | 8.33 | 8.79 | 2 | -0.10 | 0.09 | 0.66 | 0.34 | 0.39 | 0.00 | 0.00 | 0.03 | -1.03 | 1.08 | 0.11 | 62.30 | fail |
| breakout_top10 | size tilt | 1.47 | 1.45 | 1.18 | 1.17 | 1.05 | 1.04 | 19.12 | 15.97 | 15.99 | 3 | -0.02 | 0.04 | 1.18 | 1.07 | 1.06 | 0.04 | 0.01 | 0.56 | -0.51 | 1.60 | 0.53 | 48.24 | fail |
| tsmom_top20 | size tilt | 1.70 | 1.68 | 0.48 | 0.53 | 0.21 | 0.27 | 3.96 | 9.38 | 8.99 | 0 | -0.08 | -0.01 | 0.48 | 0.11 | 0.21 | 0.00 | 0.00 | -0.10 | -1.15 | 0.89 | -0.06 | 50.78 | fail |
| tsmom_tranches | size tilt | 1.89 | 1.85 | 0.65 | 0.65 | 0.55 | 0.56 | 5.95 | 9.30 | 8.79 | 1 | -0.05 | 0.04 | 0.65 | 0.33 | 0.39 | 0.00 | 0.00 | 0.13 | -0.94 | 1.19 | 0.11 | 62.30 | fail |
| breakout_top10 | rev7 tilt | 1.42 | 1.45 | 1.20 | 1.17 | 1.07 | 1.04 | 19.26 | 16.33 | 15.99 | 2 | -0.04 | 0.08 | 1.15 | 1.10 | 1.06 | 0.01 | 0.01 | 0.57 | -0.52 | 1.61 | 0.53 | 48.24 | fail |
| tsmom_top20 | rev7 tilt | 1.45 | 1.68 | 0.33 | 0.53 | -0.03 | 0.27 | 2.52 | 9.17 | 8.99 | 1 | -0.29 | -0.10 | 0.37 | -0.08 | 0.21 | 0.00 | 0.00 | -0.33 | -1.40 | 0.65 | -0.06 | 50.78 | fail |
| tsmom_tranches | rev7 tilt | 1.80 | 1.85 | 0.63 | 0.65 | 0.52 | 0.56 | 5.10 | 8.10 | 8.79 | 1 | -0.11 | 0.06 | 0.67 | 0.26 | 0.39 | 0.00 | 0.00 | -0.00 | -1.04 | 1.03 | 0.11 | 62.30 | fail |

## Every form (35 bps)

| factor | book | form | is | book_is | oos | book_oos |
|---|---|---|---|---|---|---|
| ivol | breakout_top10 | filter | 1.52 | 1.45 | 1.14 | 1.17 |
| ivol | breakout_top10 | tilt | 1.43 | 1.45 | 1.17 | 1.17 |
| ivol | tsmom_top20 | filter | 1.64 | 1.68 | 0.50 | 0.53 |
| ivol | tsmom_top20 | tilt | 1.59 | 1.68 | 0.52 | 0.53 |
| ivol | tsmom_tranches | filter | 1.85 | 1.85 | 0.63 | 0.65 |
| ivol | tsmom_tranches | tilt | 1.82 | 1.85 | 0.69 | 0.65 |
| max | breakout_top10 | filter | 1.10 | 1.45 | 1.14 | 1.17 |
| max | breakout_top10 | tilt | 1.40 | 1.45 | 1.19 | 1.17 |
| max | tsmom_top20 | filter | 1.44 | 1.68 | 0.70 | 0.53 |
| max | tsmom_top20 | tilt | 1.59 | 1.68 | 0.54 | 0.53 |
| max | tsmom_tranches | filter | 1.88 | 1.85 | 0.85 | 0.65 |
| max | tsmom_tranches | tilt | 1.86 | 1.85 | 0.74 | 0.65 |
| skew | breakout_top10 | filter | 0.92 | 1.45 | 1.38 | 1.17 |
| skew | breakout_top10 | tilt | 1.43 | 1.45 | 1.23 | 1.17 |
| skew | tsmom_top20 | filter | 1.50 | 1.68 | 0.68 | 0.53 |
| skew | tsmom_top20 | tilt | 1.63 | 1.68 | 0.53 | 0.53 |
| skew | tsmom_tranches | filter | 2.03 | 1.85 | 0.84 | 0.65 |
| skew | tsmom_tranches | tilt | 1.87 | 1.85 | 0.74 | 0.65 |
| vshock | breakout_top10 | filter | 0.52 | 1.45 | 0.67 | 1.17 |
| vshock | breakout_top10 | tilt | 1.45 | 1.45 | 1.19 | 1.17 |
| vshock | tsmom_top20 | filter | 1.23 | 1.68 | 0.09 | 0.53 |
| vshock | tsmom_top20 | tilt | 1.58 | 1.68 | 0.38 | 0.53 |
| vshock | tsmom_tranches | filter | 1.55 | 1.85 | 0.54 | 0.65 |
| vshock | tsmom_tranches | tilt | 1.84 | 1.85 | 0.64 | 0.65 |
| size | breakout_top10 | filter | 0.00 | 1.45 | 0.00 | 1.17 |
| size | breakout_top10 | tilt | 1.47 | 1.45 | 1.18 | 1.17 |
| size | tsmom_top20 | filter | 0.98 | 1.68 | -0.17 | 0.53 |
| size | tsmom_top20 | tilt | 1.70 | 1.68 | 0.48 | 0.53 |
| size | tsmom_tranches | filter | 1.28 | 1.85 | 0.30 | 0.65 |
| size | tsmom_tranches | tilt | 1.89 | 1.85 | 0.65 | 0.65 |
| rev7 | breakout_top10 | filter | 1.03 | 1.45 | 0.42 | 1.17 |
| rev7 | breakout_top10 | tilt | 1.42 | 1.45 | 1.20 | 1.17 |
| rev7 | tsmom_top20 | filter | 0.64 | 1.68 | -0.17 | 0.53 |
| rev7 | tsmom_top20 | tilt | 1.45 | 1.68 | 0.33 | 0.53 |
| rev7 | tsmom_tranches | filter | 1.44 | 1.85 | 0.45 | 0.65 |
| rev7 | tsmom_tranches | tilt | 1.80 | 1.85 | 0.63 | 0.65 |

How often the books held a coin in a factor's worst third, and the share of their weight the factor ranks at all (out of sample, days with any position):

| factor | book | days_holding_worst_third_pct | held_weight_ranked_pct |
|---|---|---|---|
| ivol | breakout_top10 | 26.71 | 100.00 |
| ivol | tsmom_top20 | 44.66 | 100.00 |
| ivol | tsmom_tranches | 47.15 | 100.00 |
| max | breakout_top10 | 32.43 | 100.00 |
| max | tsmom_top20 | 70.64 | 100.00 |
| max | tsmom_tranches | 72.31 | 100.00 |
| skew | breakout_top10 | 51.51 | 100.00 |
| skew | tsmom_top20 | 76.51 | 100.00 |
| skew | tsmom_tranches | 83.70 | 100.00 |
| vshock | breakout_top10 | 80.76 | 100.00 |
| vshock | tsmom_top20 | 94.48 | 100.00 |
| vshock | tsmom_tranches | 94.94 | 100.00 |
| size | breakout_top10 | 100.00 | 100.00 |
| size | tsmom_top20 | 99.47 | 100.00 |
| size | tsmom_tranches | 100.00 | 100.00 |
| rev7 | breakout_top10 | 84.26 | 100.00 |
| rev7 | tsmom_top20 | 92.35 | 100.00 |
| rev7 | tsmom_tranches | 92.25 | 100.00 |

The books alone and gated BTC:

| book | is | oos | cagr_pct | dd_pct | twin_oos | g_k | g_oos | minus_g |
|---|---|---|---|---|---|---|---|---|
| breakout_top10 | 1.45 | 1.17 | 18.38 | 15.99 | 1.06 | 0.40 | 0.71 | 0.53 |
| tsmom_top20 | 1.68 | 0.53 | 4.28 | 8.99 | 0.21 | 0.19 | 0.70 | -0.06 |
| tsmom_tranches | 1.85 | 0.65 | 5.83 | 8.79 | 0.39 | 0.20 | 0.72 | 0.11 |

Pool: 1,836 trials (1,140 hand before this registration, 600 factory, 96 registered on 2026-10-21 with O9's 2 forward trials); the best noise trial sits at an annual Sharpe of about 2.69. Gate 6 deflates each improvement over the 94 trials of the registration at the variance of the 94 trial difference Sharpes computed in this run.
