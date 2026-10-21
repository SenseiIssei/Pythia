<!-- generated below by lab.experiments.funding_carry; edit above this line only -->

# Funding carry on perpetuals: results

Generated 2026-10-21T14:40:52+00:00. Registered in `results/funding_carry_prereg.md` before the run.

Selection 2020-08-01 to 2023-12-31, holdout 2024-01-01 to 2026-10-18 (1022 days). Books among the 100 most liquid USDT perps of each day, half the capital per side, funding paid and received, costs per unit of one-way turnover.

## Verdict

**Pass.** Funding carry earns beyond the low-vol book and BTC. Pick: **F7 · 10/10 · 3-day tranches**.

- 1 holdout Sharpe above 0.5 at 10 bps and above 0 at 20 bps: yes
- 2 positive in 2 of 2024, 2025, 2026: yes
- 3 one day late above 0 at 10 bps: yes
- 4 residual above 0.3, bootstrap 5 % above 0: yes

Deflated p of the residual over the pool: 0.0026; of the pick itself: 0.0004.

## All 12 books

| variant | sel_0bps | sel_10bps | hold_0bps | hold_10bps | hold_20bps | hold_41bps | hold_cagr_pct | hold_dd_pct | y2024 | y2025 | y2026 | turnover_yr | fund_hold_pct |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| F1 · 10/10 · 3-day tranches | 2.37 | 1.81 | 1.12 | 0.59 | 0.07 | -1.03 | 13.92 | 37.93 | 1.45 | 1.34 | -0.82 | 152.10 | 72.24 |
| F1 · 10/10 · weekly tranches | 2.27 | 1.95 | 1.05 | 0.76 | 0.48 | -0.12 | 17.74 | 32.50 | 1.65 | 1.46 | -0.67 | 73.50 | 58.08 |
| F1 · 20/20 · 3-day tranches | 2.07 | 1.34 | 1.60 | 0.85 | 0.10 | -1.48 | 14.70 | 18.70 | 1.19 | 1.84 | -0.42 | 136.16 | 43.35 |
| F1 · 20/20 · weekly tranches | 1.95 | 1.56 | 1.62 | 1.21 | 0.80 | -0.06 | 20.04 | 16.07 | 1.90 | 1.85 | -0.02 | 66.30 | 35.10 |
| F7 · 10/10 · 3-day tranches | 2.52 | 2.17 | 1.01 | 0.74 | 0.46 | -0.11 | 21.38 | 34.95 | 0.75 | 1.46 | -0.06 | 93.40 | 71.18 |
| F7 · 10/10 · weekly tranches | 2.04 | 1.77 | 0.93 | 0.74 | 0.54 | 0.12 | 20.28 | 29.68 | 1.36 | 1.34 | -0.46 | 63.48 | 59.46 |
| F7 · 20/20 · 3-day tranches | 1.77 | 1.37 | 1.11 | 0.75 | 0.39 | -0.36 | 15.18 | 22.74 | 1.65 | 0.88 | -0.16 | 78.72 | 44.62 |
| F7 · 20/20 · weekly tranches | 1.62 | 1.31 | 1.17 | 0.91 | 0.64 | 0.09 | 18.13 | 21.35 | 1.95 | 0.91 | -0.02 | 54.81 | 37.96 |
| F28 · 10/10 · 3-day tranches | 1.69 | 1.48 | 0.29 | 0.13 | -0.04 | -0.38 | -0.84 | 39.99 | -0.42 | 0.86 | -0.28 | 51.00 | 61.70 |
| F28 · 10/10 · weekly tranches | 1.71 | 1.55 | 0.09 | -0.04 | -0.17 | -0.43 | -5.24 | 38.50 | -0.73 | 0.36 | 0.09 | 37.22 | 53.08 |
| F28 · 20/20 · 3-day tranches | 1.39 | 1.18 | 0.16 | -0.04 | -0.24 | -0.66 | -3.19 | 29.67 | 0.13 | 0.36 | -0.66 | 43.07 | 41.69 |
| F28 · 20/20 · weekly tranches | 1.28 | 1.12 | 0.11 | -0.05 | -0.20 | -0.52 | -3.10 | 30.15 | -0.14 | 0.09 | -0.13 | 31.86 | 36.39 |

`sel_*` and `hold_*` are Sharpes (daily x sqrt 365) at that cost; CAGR, drawdown and the years at 10 bps; `fund_hold_pct` is the funding the book received (+) or paid (-) a year in the holdout, both legs.


## The pick against the low-vol book of its shape and BTC

| cost | alpha_fit_ann | se_alpha_fit_ann | b_lowvol | se_b_lowvol | b_btc | se_b_btc | r2_fit | corr_fit | corr_hold |
|---|---|---|---|---|---|---|---|---|---|
| 0bps | 0.306 | 0.160 | -0.173 | 0.025 | -0.051 | 0.016 | 0.061 | -0.219 | -0.305 |
| 10bps | 0.205 | 0.160 | -0.173 | 0.025 | -0.051 | 0.016 | 0.061 | -0.219 | -0.304 |
| 20bps | 0.104 | 0.160 | -0.172 | 0.025 | -0.051 | 0.016 | 0.060 | -0.219 | -0.304 |
| 41bps | -0.109 | 0.160 | -0.172 | 0.025 | -0.050 | 0.016 | 0.060 | -0.218 | -0.304 |


| cost | pick_sel | lowvol_sel | pick_hold | lowvol_hold | btc_hold | late_hold | R_hold | R_hold_mean_ann | boot_p05 | boot_p95 | boot_above0 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 0bps | 2.52 | 0.08 | 1.01 | 1.32 | 0.69 | 0.86 | 1.39 | 0.45 | 0.45 | 2.34 | 0.99 |
| 10bps | 2.17 | -0.01 | 0.74 | 1.23 | 0.69 | 0.57 | 1.08 | 0.35 | 0.15 | 2.03 | 0.97 |
| 20bps | 1.82 | -0.11 | 0.46 | 1.13 | 0.69 | 0.29 | 0.77 | 0.25 | -0.16 | 1.72 | 0.92 |
| 41bps | 1.08 | -0.31 | -0.11 | 0.93 | 0.69 | -0.32 | 0.12 | 0.04 | -0.82 | 1.07 | 0.57 |

R = pick - b_lowvol x lowvol - b_btc x BTC with the betas fitted on 2022-2023 at each cost and frozen (intercept kept). Bootstrap: stationary, mean block 20 days, 4000 draws, seed 20261021. `late_hold`: the pick on the previous day's scores. Judged row: 10bps.


## By year (Sharpe; 2022 and 2023 are the fit window)

| cost | year | pick | lowvol | R |
|---|---|---|---|---|
| 10bps | 2022 | 1.26 | 0.53 | 1.26 |
| 10bps | 2023 | 0.39 | -0.63 | 0.50 |
| 10bps | 2024 | 0.75 | 1.45 | 1.24 |
| 10bps | 2025 | 1.46 | 1.65 | 1.91 |
| 10bps | 2026 | -0.06 | 0.49 | 0.03 |
| 41bps | 2022 | 0.09 | 0.21 | -0.03 |
| 41bps | 2023 | -0.98 | -0.99 | -1.01 |
| 41bps | 2024 | -0.53 | 1.10 | -0.09 |
| 41bps | 2025 | 0.66 | 1.37 | 1.00 |
| 41bps | 2026 | -0.71 | 0.21 | -0.72 |

## Where the pick's money comes from (per year, % of capital a year)

| year | long_px_pct | short_px_pct | long_fund_pct | short_fund_pct | costs_10bps_pct |
|---|---|---|---|---|---|
| 2022 | -64.1 | 81.3 | 20.7 | 2.9 | -9.4 |
| 2023 | 16.0 | -35.1 | 30.3 | 6.8 | -9.5 |
| 2024 | -1.6 | 12.0 | 7.7 | 9.5 | -9.8 |
| 2025 | -99.4 | 86.9 | 73.3 | 3.2 | -9.6 |
| 2026 | -131.1 | 4.6 | 130.0 | 2.4 | -8.4 |

Price return and funding of each leg (funding received is positive), and the costs at 10 bps.


The six coins with the most funding per leg in the holdout (sums of daily contributions, % of capital; they carry 19 % of the long leg's funding and 21 % of the short leg's):

| leg | coin | funding_pct | price_pct | total_pct |
|---|---|---|---|---|
| long | HOMEUSDT | 7.3 | -7.4 | -0.1 |
| long | ALPACAUSDT | 6.9 | 14.7 | 21.6 |
| long | LSKUSDT | 5.5 | -5.3 | 0.2 |
| long | BARDUSDT | 5.4 | -4.2 | 1.2 |
| long | ONGUSDT | 4.8 | 2.0 | 6.7 |
| long | FUNUSDT | 4.6 | 6.4 | 11.0 |
| short | TRBUSDT | 0.8 | 6.8 | 7.6 |
| short | PEPEUSDT | 0.7 | -12.1 | -11.4 |
| short | BNXUSDT | 0.4 | -2.4 | -2.0 |
| short | ARKUSDT | -0.4 | 0.8 | 0.4 |
| short | TIAUSDT | 0.4 | 2.0 | 2.4 |
| short | MEMEUSDT | 0.3 | 3.6 | 4.0 |

## Overlap and signal skill (information only)

On an average holdout day the pick's fresh long list shares 5 % of its names with the low-vol book's, the short list 17 %.

| signal | window | ic_mean | ic_t | days |
|---|---|---|---|---|
| F1 | selection | 0.029 | 4.627 | 1248 |
| F1 | holdout | 0.015 | 2.793 | 1020 |
| F7 | selection | 0.021 | 3.269 | 1248 |
| F7 | holdout | 0.006 | 1.069 | 1020 |
| F28 | selection | 0.008 | 1.214 | 1248 |
| F28 | holdout | -0.005 | -0.944 | 1020 |

Daily Spearman IC of the score (minus funding) with the next 3 days' funding-net return over all eligible perps; t on non-overlapping 3-day blocks.


Restricted to the 209 coins Kraken Futures lists today (not survivorship-free): selection 1.21, holdout 0.77 at 10 bps.


## Refitted on the holdout (information only)

| cost | refit_alpha_ann | refit_alpha_t | refit_b_lowvol | refit_b_btc | refit_r2 |
|---|---|---|---|---|---|
| 0bps | 0.527 | 2.743 | -0.285 | -0.114 | 0.116 |
| 10bps | 0.423 | 2.202 | -0.285 | -0.114 | 0.116 |
| 20bps | 0.319 | 1.661 | -0.285 | -0.114 | 0.116 |
| 41bps | 0.101 | 0.525 | -0.285 | -0.114 | 0.116 |

## Rolling one-year betas at 10 bps (information only)

| to | alpha_ann | b_lowvol | b_btc |
|---|---|---|---|
| 2022-01-20 | 1.051 | -0.152 | -0.023 |
| 2022-04-21 | 0.426 | -0.217 | -0.057 |
| 2022-07-21 | 0.435 | -0.188 | -0.038 |
| 2022-10-20 | 0.272 | -0.159 | -0.018 |
| 2023-01-19 | 0.339 | -0.192 | -0.019 |
| 2023-04-20 | 0.075 | -0.128 | -0.023 |
| 2023-07-20 | -0.211 | -0.072 | -0.041 |
| 2023-10-19 | 0.144 | -0.219 | -0.113 |
| 2024-01-18 | 0.081 | -0.149 | -0.107 |
| 2024-04-18 | 0.326 | -0.108 | -0.086 |
| 2024-07-18 | 0.271 | -0.086 | -0.062 |
| 2024-10-17 | 0.002 | 0.025 | -0.033 |
| 2025-01-16 | 0.253 | 0.055 | -0.042 |
| 2025-04-17 | 0.258 | -0.069 | -0.043 |
| 2025-07-17 | 0.903 | -0.449 | -0.116 |
| 2025-10-16 | 0.806 | -0.315 | -0.115 |
| 2026-01-15 | 0.818 | -0.377 | -0.154 |
| 2026-04-16 | 0.858 | -0.444 | -0.162 |
| 2026-07-16 | 0.306 | -0.175 | -0.128 |
| 2026-10-15 | 0.293 | -0.408 | -0.093 |

## Pool

1,777 trials (1,140 hand, 600 factory, 37 registered today); the best noise trial sits at an annual Sharpe of about 2.72.
