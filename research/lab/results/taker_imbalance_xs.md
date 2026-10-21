# Taker order-flow imbalance across perpetuals

Run 2026-10-21 on the server as registered in
`results/taker_imbalance_xs_prereg.md` (committed first). Code:
`lab.experiments.taker_imbalance_xs`; the `xs_daily` panel as the paper job
`paper-m4-ls` built it on 2026-10-21 (copied unchanged into a study folder,
removed after the run) and the USD-M daily klines of 469 perps already in the
lake. The tables below the marker are generated.

## What it says

**No (fails gate 1). And the registered direction was the wrong one.**

- The selection window picks A1, 10/10, weekly tranches (0.53 at 10 bps in
  2020-08 to 2023). From 2024 it makes **0.30 at 10 bps** (0.78 at the 2 bps
  maker level, -0.31 at 20, -1.58 at 41), 3 % a year, drawdown 16 %,
  correlation with BTC -0.04, 2026 negative. Gate 1 (0.5 at 10 bps, above 0
  at 20) fails; the day-late, year and residual gates pass.
- The residual (1.16, band 0.36 to 1.93) looks good only because the pick is
  short low vol (beta -0.18) and low vol made 1.69 from 2024: subtracting a
  negative low-vol loading adds the low-vol book back. It is not evidence for
  the signal.
- Every one of the 12 books is negative at 10 bps from 2024 except the pick;
  the daily A1 books trade 530 to 600x a year and make -2.11 at 10 bps.
- **The information-only IC says reversal, not continuation**, in both
  windows and for both measures: abnormal taker buying predicts a lower next
  day (A1 IC -0.014, t -5.1; A7 -0.026, t -9.2 from 2024; -0.022 and -0.028
  in 2020 to 2023) and lower 3 and 7-day funding-net returns (A7 net7 -0.028,
  t -3.7). The spot taker share agrees (A7 fwd1 -0.018, t -7.5). This is
  the price-pressure reversal of Campbell, Grossman and Wang, not the
  continuation of Chordia and Subrahmanyam. The registered books trade the
  other way, and flipping the sign now would be a new trial chosen after
  seeing the data: it needs its own registration (and, at an IC of 0.02 to
  0.03 on a daily or 3-day horizon, it would face the same turnover).
- The two registrations of this batch took opposite priors on taker flow;
  `positioning_xs` treats taker buying as crowding (contrarian), which is
  the sign the IC here supports.

<!-- generated below by lab.experiments.taker_imbalance_xs; edit above this line only -->

# Taker order-flow imbalance across perpetuals: results

Generated 2026-10-21T20:49:12+00:00. Registered in `results/taker_imbalance_xs_prereg.md` before the run.

Order flow from the USD-M daily klines of the day's perp (469 perps): the taker buy share of volume, A1 = the day's share minus its mean over the previous 90 days, A7 = the 7-day share minus the mean daily share of the 90 days before; score = +A (continuation). `s_spotA1` and `s_spotA7` in the IC table are the same from the spot hourly klines already in the panel (information only).

Selection 2020-08-01 to 2023-12-31, holdout 2024-01-01 to 2026-10-18 (1022 days); residual fitted 2022-01-01 to 2023-12-31. Books among the 100 most liquid USDT perps with a score, half the capital per side, funding paid and received, costs per unit of one-way turnover.

## Verdict

**Fail.** Not shown to earn beyond the low-vol book and BTC. Pick: **A1 · 10/10 · weekly tranches**.

- 1 holdout Sharpe above 0.5 at 10 bps and above 0 at 20 bps: no
- 2 positive in 2 of 2024, 2025, 2026: yes
- 3 one day late above 0 at 10 bps: yes
- 4 residual above 0.3, bootstrap 5 % above 0: yes

The pick from 2024: Sharpe 0.30 at 10 bps (2 bps 0.78, 20 bps -0.31, 41 bps -1.58), 3.4 % a year, drawdown 15.7 %, correlation with BTC -0.04, years 0.28 / 0.68 / -0.15, a day late 0.38. Residual R 1.16 (band 0.36 to 1.93). Deflated p of R over the pool 0.0029, of the pick itself 0.0000.

## All books

| variant | sel_2bps | sel_10bps | hold_2bps | hold_10bps | hold_20bps | hold_41bps | hold_cagr_pct | hold_dd_pct | corr_btc | y2024 | y2025 | y2026 | turnover_yr | fund_hold_pct |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A1 · 10/10 · daily | 0.44 | -1.10 | -0.28 | -2.11 | -4.40 | -9.20 | -44.33 | 81.93 | -0.04 | -2.33 | -1.54 | -2.56 | 597.55 | 6.68 |
| A1 · 10/10 · 3-day tranches | 0.81 | 0.09 | 0.42 | -0.46 | -1.57 | -3.89 | -9.90 | 29.41 | -0.03 | -0.87 | 0.31 | -0.84 | 207.16 | 4.96 |
| A1 · 10/10 · weekly tranches | 0.93 | 0.53 | 0.78 | 0.30 | -0.31 | -1.58 | 3.38 | 15.67 | -0.04 | 0.28 | 0.68 | -0.15 | 90.82 | 3.72 |
| A1 · 20/20 · daily | -0.40 | -2.30 | 0.05 | -2.11 | -4.82 | -10.49 | -35.29 | 72.10 | -0.06 | -4.01 | -0.95 | -1.58 | 532.50 | 5.68 |
| A1 · 20/20 · 3-day tranches | 0.53 | -0.35 | 0.18 | -0.90 | -2.25 | -5.08 | -12.52 | 34.87 | -0.04 | -1.76 | -0.23 | -0.64 | 186.67 | 4.42 |
| A1 · 20/20 · weekly tranches | 0.70 | 0.20 | 0.35 | -0.24 | -0.96 | -2.49 | -3.24 | 21.18 | -0.05 | -0.15 | -0.17 | -0.46 | 81.92 | 2.70 |
| A7 · 10/10 · daily | 0.48 | 0.05 | 0.09 | -0.39 | -0.99 | -2.26 | -17.97 | 56.31 | -0.06 | -0.13 | -0.28 | -0.76 | 212.51 | 21.21 |
| A7 · 10/10 · 3-day tranches | 0.53 | 0.24 | 0.18 | -0.15 | -0.56 | -1.41 | -9.02 | 45.59 | -0.07 | 0.30 | -0.52 | -0.25 | 126.38 | 17.58 |
| A7 · 10/10 · weekly tranches | 0.44 | 0.25 | -0.01 | -0.26 | -0.56 | -1.20 | -9.86 | 43.47 | -0.08 | 0.26 | -0.38 | -0.72 | 80.84 | 13.60 |
| A7 · 20/20 · daily | 0.31 | -0.23 | -0.08 | -0.73 | -1.55 | -3.25 | -17.35 | 54.22 | -0.06 | -0.22 | -1.32 | -0.65 | 184.61 | 15.26 |
| A7 · 20/20 · 3-day tranches | 0.46 | 0.10 | 0.16 | -0.27 | -0.81 | -1.94 | -7.40 | 37.12 | -0.06 | 0.37 | -0.90 | -0.34 | 110.99 | 12.52 |
| A7 · 20/20 · weekly tranches | 0.27 | 0.01 | -0.04 | -0.36 | -0.76 | -1.60 | -7.92 | 34.33 | -0.08 | 0.20 | -0.50 | -0.88 | 73.16 | 9.23 |

`sel_*` and `hold_*` are Sharpes (daily x sqrt 365) at that cost; CAGR, drawdown, correlation with BTC and the years at 10 bps; `fund_hold_pct` is the funding the book received (+) or paid (-) a year in the holdout, both legs.


## The pick against the low-vol book of its shape and BTC

| cost | alpha_fit_ann | se_alpha_fit_ann | b_lowvol | se_b_lowvol | b_btc | se_b_btc | r2_fit | corr_fit | corr_hold |
|---|---|---|---|---|---|---|---|---|---|
| 2bps | 0.020 | 0.090 | -0.184 | 0.014 | -0.020 | 0.009 | 0.189 | -0.428 | -0.301 |
| 10bps | -0.057 | 0.090 | -0.184 | 0.014 | -0.020 | 0.009 | 0.189 | -0.428 | -0.301 |
| 20bps | -0.152 | 0.090 | -0.184 | 0.014 | -0.020 | 0.009 | 0.189 | -0.429 | -0.301 |
| 41bps | -0.353 | 0.090 | -0.185 | 0.014 | -0.020 | 0.009 | 0.189 | -0.429 | -0.301 |


| cost | pick_sel | lowvol_sel | pick_hold | lowvol_hold | btc_hold | late_hold | R_hold | R_hold_mean_ann | boot_p05 | boot_p95 | boot_above0 | R2024 | R2025 | R2026 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2bps | 0.93 | -0.01 | 0.78 | 1.74 | 0.69 | 0.87 | 1.69 | 0.24 | 0.92 | 2.45 | 1.00 | 1.51 | 2.60 | 0.92 |
| 10bps | 0.53 | -0.06 | 0.30 | 1.69 | 0.69 | 0.38 | 1.16 | 0.17 | 0.36 | 1.93 | 0.99 | 1.02 | 2.02 | 0.38 |
| 20bps | 0.05 | -0.13 | -0.31 | 1.61 | 0.69 | -0.23 | 0.49 | 0.07 | -0.36 | 1.30 | 0.83 | 0.41 | 1.28 | -0.30 |
| 41bps | -0.98 | -0.27 | -1.58 | 1.45 | 0.69 | -1.50 | -0.91 | -0.13 | -1.86 | -0.02 | 0.05 | -0.86 | -0.26 | -1.72 |

R = pick - b_lowvol x lowvol - b_btc x BTC with the betas fitted at each cost and frozen (intercept kept). Bootstrap: stationary, mean block 20 days, 4000 draws, seed 20261021. `late_hold`: the pick on the previous day's scores. Judged row: 10bps.


## Where the pick's money comes from (per year, % of capital a year)

| year | long_px_pct | short_px_pct | long_fund_pct | short_fund_pct | costs_10bps_pct |
|---|---|---|---|---|---|
| 2020 | 43.9 | -0.2 | -3.9 | 7.9 | -6.5 |
| 2021 | 137.7 | -104.8 | -14.5 | 18.2 | -8.7 |
| 2022 | -49.2 | 52.6 | 3.9 | -1.3 | -8.9 |
| 2023 | 26.8 | -38.2 | 7.4 | 3.0 | -9.2 |
| 2024 | 16.8 | -5.2 | -2.8 | 4.9 | -9.1 |
| 2025 | -43.1 | 54.1 | 11.2 | -3.7 | -9.0 |
| 2026 | -8.1 | 14.2 | 13.7 | -12.7 | -9.1 |

On an average holdout day the pick's fresh long list shares 12 % of its names with the low-vol book's, the short list 9 %.


Restricted to the coins of the 209 PF perpetuals Kraken Futures lists today (not survivorship-free): selection 0.51, holdout -0.03 at 10 bps.


## Signal skill (information only)

| score | label | window | ic_mean | ic_t | days |
|---|---|---|---|---|---|
| s_A1 | fwd1 | selection | -0.022 | -6.248 | 1248 |
| s_A1 | fwd1 | holdout | -0.014 | -5.066 | 1022 |
| s_A1 | net3 | selection | -0.009 | -1.736 | 1248 |
| s_A1 | net3 | holdout | -0.011 | -2.075 | 1020 |
| s_A1 | net7 | selection | -0.001 | 0.040 | 1248 |
| s_A1 | net7 | holdout | -0.013 | -0.935 | 1016 |
| s_A7 | fwd1 | selection | -0.028 | -7.370 | 1248 |
| s_A7 | fwd1 | holdout | -0.026 | -9.172 | 1022 |
| s_A7 | net3 | selection | -0.018 | -3.209 | 1248 |
| s_A7 | net3 | holdout | -0.026 | -5.090 | 1020 |
| s_A7 | net7 | selection | -0.015 | -0.848 | 1248 |
| s_A7 | net7 | holdout | -0.028 | -3.671 | 1016 |
| s_spotA1 | fwd1 | selection | -0.018 | -5.401 | 1248 |
| s_spotA1 | fwd1 | holdout | -0.013 | -5.363 | 1022 |
| s_spotA1 | net3 | selection | -0.011 | -1.039 | 1248 |
| s_spotA1 | net3 | holdout | -0.005 | -1.527 | 1020 |
| s_spotA1 | net7 | selection | -0.004 | -0.932 | 1248 |
| s_spotA1 | net7 | holdout | -0.004 | -0.116 | 1016 |
| s_spotA7 | fwd1 | selection | -0.020 | -5.829 | 1248 |
| s_spotA7 | fwd1 | holdout | -0.018 | -7.522 | 1022 |
| s_spotA7 | net3 | selection | -0.012 | -2.411 | 1248 |
| s_spotA7 | net3 | holdout | -0.014 | -2.841 | 1020 |
| s_spotA7 | net7 | selection | -0.008 | -0.700 | 1248 |
| s_spotA7 | net7 | holdout | -0.013 | -1.951 | 1016 |

Daily Spearman IC of each score (in the direction the book trades it) with the next day's log return (`fwd1`) and the next 3 and 7 days' funding-net log return, over every eligible coin with a score; t on non-overlapping blocks of the label's length.


Scored coins per day (the pick's score):

| year | median_scored | min_scored |
|---|---|---|
| 2020 | 36.00 | 25 |
| 2021 | 105.00 | 60 |
| 2022 | 129.00 | 83 |
| 2023 | 153.00 | 107 |
| 2024 | 219.00 | 203 |
| 2025 | 259.00 | 198 |
| 2026 | 193.00 | 126 |

## Pool

Pool: 1,977 trials (1,353 hand before this registration, 600 factory as read now, 24 registered together on 2026-10-21: positioning_xs 5, taker_imbalance_xs 13, hedged_breakout 2, pead_xbrl 4); the best noise trial sits at an annual Sharpe of about 2.77. The next study starts from 1,377 hand trials.
