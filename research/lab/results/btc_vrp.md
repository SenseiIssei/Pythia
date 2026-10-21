<!-- generated below by lab.experiments.btc_vrp; edit above this line only -->

## Results (generated 2026-10-21, first roll 2021-04-23, in sample to 2023-12-31, out of sample 2024-01-01 to 2026-10-19)

**Killed.** The in-sample pick is **CC F** (in-sample Sharpe 0.59). Out of sample at a 3-point haircut it makes Sharpe 0.60, 18.3 % a year, volatility 45.5 %, drawdown 53.0 %; at 6 points 0.59. BTC 0.74 / 26.6 % / 53.0 %, gated BTC 0.68 / 19.8 % / 33.3 %. Bootstrap 90 % band of Sharpe(pick) - Sharpe(BTC) -0.48 to 0.10. The pick stays above 0 at every haircut up to 40 vol points (a covered call sold for nothing is BTC itself), so a break-even haircut does not exist for it. Deflated p 0.00 over 1,762.

Failed: Sharpe above BTC's and gated BTC's at 3 points; bootstrap 5 % of Sharpe - BTC's above 0.

Per year (Sharpe): 2022 -0.69, 2023 1.96, 2024 1.46, 2025 0.05, 2026 0.04.

### The six variants (3-point haircut; the filter sells when DVOL - RV30 exceeds 16.5 points)

| variant | is_sharpe | is_dd | oos_sharpe | oos_cagr | oos_vol | oos_dd | oos_h6 | sold_share | worst_month_pct |
|---|---|---|---|---|---|---|---|---|---|
| P0 | 0.40 | 0.41 | 0.63 | 0.14 | 0.27 | 0.33 | 0.47 | 1.00 | -22.71 |
| P0 F | -0.01 | 0.38 | 0.51 | 0.03 | 0.06 | 0.09 | 0.47 | 0.27 | -22.37 |
| P10 | 0.54 | 0.33 | 0.31 | 0.04 | 0.19 | 0.25 | 0.15 | 1.00 | -18.92 |
| P10 F | 0.26 | 0.23 | 0.58 | 0.02 | 0.04 | 0.05 | 0.52 | 0.27 | -18.92 |
| CC | 0.40 | 0.41 | 0.63 | 0.14 | 0.27 | 0.33 | 0.47 | 1.00 | -22.71 |
| CC F | 0.59 | 0.52 | 0.60 | 0.18 | 0.45 | 0.53 | 0.59 | 0.27 | -29.62 |

In sample BTC 0.19, gated BTC -0.02. P0 and CC are the same position: with zero rates and the strike at spot, a cash-secured put equals a covered call (put-call parity), so their rows match; the filtered rows differ because a filtered month holds cash (P0 F) or BTC (CC F).

### The premium: DVOL minus the next 30 days' realised volatility

| year | mean_pts | share_pos |
|---|---|---|
| 2021 | 18.02 | 0.88 |
| 2022 | 12.17 | 0.67 |
| 2023 | 6.61 | 0.73 |
| 2024 | 7.18 | 0.73 |
| 2025 | 6.45 | 0.71 |
| 2026 | -0.38 | 0.59 |
| all | 8.39 | 0.72 |
