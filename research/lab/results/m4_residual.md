# Does the funding-aware M4 long/short earn anything beyond low vol and BTC?

Run 2026-10-21 as registered in `results/m4_residual_prereg.md` (committed
first). Code: `lab.experiments.m4_residual`. The tables below the marker are
generated.

## What it says

**Pass as registered, not confirmed, and not tradable where the lab trades.**
reg7n (10/10 of the 100 most liquid perps, rank buffer 50 %) leans heavily on
the low-vol book of the same shape (beta 0.71, R² 0.51 in 2022-2023) and not
on BTC (beta 0.01). With those betas frozen, the residual R keeps:

- a holdout Sharpe of **0.96 at 41 bps** (1.08 at 15), about 26 % a year;
- a bootstrap band of **0.16 to 1.77** (98 % of draws above zero);
- a positive Sharpe in every year: 2024 1.08, 2025 1.13, 2026 0.65 (to
  2026-09-28), and 0.76 in 2023 inside the fit window, the year low vol lost
  (-0.51).

What tempers it:

- Deflated p over the pool of 1,724 is 0.0020, so the pass is not confirmed;
  it is one holdout, the same one that favoured the low-vol bet.
- The low-vol exposure moves: the rolling one-year beta fell from 0.7 to about 0.5
  from late 2024 through 2025 and rose to 0.73 to 0.84 in 2026, when R was weakest. Refitted on
  the holdout (information only) the alpha is about 30 % a year at 41 bps
  with a t of 1.8.
- The books need perpetuals. Alpaca has none and the lab has no perp venue,
  so nothing here can trade. The lab's M4 shadow book `m4_ls` runs rank3
  held 3 days, not reg7n, so its forward record does not test this result.

The kill rule did not fire, so M4 is not recorded as "low vol plus funding
avoidance": the funding-aware model earns something beyond the factor and BTC
out of sample, by about a Sharpe of 1 at 41 bps. Nothing is wired; a reg7n
forward shadow judged against the low-vol book would be the next registration
if the owner wants one.

<!-- generated below by lab.experiments.m4_residual; edit above this line only -->

# M4 reg7n beyond the low-vol factor and BTC: results

Generated 2026-10-20T22:07:20+00:00. Registered in `results/m4_residual_prereg.md` before the run.

Fit 2022-01-01 to 2023-12-31, holdout 2024-01-01 to 2026-09-28 (1002 days). Both books 10/10 of the 100 most liquid perps, rank buffer 50 %, funding charged; the rebuilt reg7n book matches xs_daily's cached pick series (largest difference 0.0e+00).

## Verdict

**Pass.** reg7n earns beyond the low-vol factor and BTC.

- 1 holdout Sharpe above 0.5: yes
- 2 bootstrap 5 % above 0: yes
- 3 positive in 2024, 2025 and 2026: yes
- 4 positive in 2023 (in the fit window): yes

Deflated p of R over the pool: 0.0020.

## Frozen betas and the residual

| cost | alpha_fit_ann | se_alpha_fit_ann | b_lowvol | se_b_lowvol | b_btc | se_b_btc | r2_fit | r2_hold_frozen | corr_fit | corr_hold |
|---|---|---|---|---|---|---|---|---|---|---|
| 15bps | 0.320 | 0.148 | 0.706 | 0.028 | 0.009 | 0.015 | 0.513 | 0.317 | 0.716 | 0.571 |
| 41bps | 0.275 | 0.148 | 0.707 | 0.028 | 0.009 | 0.015 | 0.513 | 0.317 | 0.716 | 0.571 |


| cost | reg7n_fit | lowvol_fit | btc_fit | reg7n_hold | lowvol_hold | btc_hold | R_hold | R_hold_mean_ann | boot_p05 | boot_p95 | boot_above0 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 15bps | 1.13 | 0.08 | 0.23 | 2.17 | 1.88 | 0.72 | 1.08 | 0.29 | 0.28 | 1.91 | 0.99 |
| 41bps | 0.93 | 0.01 | 0.23 | 2.02 | 1.81 | 0.72 | 0.96 | 0.26 | 0.16 | 1.77 | 0.98 |

R = reg7n - b_lowvol x lowvol - b_btc x BTC with the betas from the fit window (intercept kept in R). Bootstrap: stationary, mean block 20 days, 4000 draws, seed 20261020, 5 % and 95 % of R's annual Sharpe. `alpha_fit_ann` and `R_hold_mean_ann` are daily means x 365.


## By year (Sharpe; 2022 and 2023 are the fit window)

| cost | year | reg7n | lowvol | R | R_mean_ann |
|---|---|---|---|---|---|
| 15bps | 2022 | 2.21 | 0.77 | 2.15 | 0.46 |
| 15bps | 2023 | 0.23 | -0.45 | 0.86 | 0.18 |
| 15bps | 2024 | 1.88 | 1.02 | 1.26 | 0.33 |
| 15bps | 2025 | 2.56 | 2.36 | 1.24 | 0.31 |
| 15bps | 2026 | 2.03 | 2.57 | 0.72 | 0.22 |
| 41bps | 2022 | 1.91 | 0.69 | 1.84 | 0.40 |
| 41bps | 2023 | 0.12 | -0.51 | 0.76 | 0.15 |
| 41bps | 2024 | 1.67 | 0.95 | 1.08 | 0.28 |
| 41bps | 2025 | 2.43 | 2.30 | 1.13 | 0.28 |
| 41bps | 2026 | 1.92 | 2.48 | 0.65 | 0.20 |

## Refitted on the holdout (information only, not judged)

| cost | refit_alpha_ann | refit_se_alpha_ann | refit_alpha_t | refit_b_lowvol | refit_b_btc | refit_r2 |
|---|---|---|---|---|---|---|
| 15bps | 0.336 | 0.164 | 2.053 | 0.616 | 0.040 | 0.329 |
| 41bps | 0.301 | 0.164 | 1.838 | 0.616 | 0.040 | 0.329 |

## Rolling one-year betas at 41 bps (information only)

| to | alpha_ann | b_lowvol | b_btc |
|---|---|---|---|
| 2022-12-31 | 0.410 | 0.639 | 0.012 |
| 2023-04-01 | 0.286 | 0.714 | 0.020 |
| 2023-07-01 | 0.220 | 0.753 | 0.056 |
| 2023-09-30 | 0.080 | 0.791 | 0.043 |
| 2023-12-30 | 0.169 | 0.741 | 0.004 |
| 2024-03-30 | 0.202 | 0.703 | -0.075 |
| 2024-06-29 | 0.148 | 0.672 | -0.063 |
| 2024-09-28 | 0.448 | 0.620 | -0.057 |
| 2024-12-28 | 0.409 | 0.492 | -0.047 |
| 2025-03-29 | 0.317 | 0.503 | 0.054 |
| 2025-06-28 | 0.413 | 0.531 | 0.095 |
| 2025-09-27 | 0.255 | 0.563 | 0.127 |
| 2025-12-27 | 0.241 | 0.730 | 0.158 |
| 2026-03-28 | 0.256 | 0.727 | 0.062 |
| 2026-06-27 | 0.018 | 0.836 | 0.031 |
| 2026-09-26 | 0.159 | 0.745 | 0.027 |

## Pool

1,724 trials (1,115 hand, 600 factory, 9 registered today); the best noise trial sits at an annual Sharpe of about 2.73.
