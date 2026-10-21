# Intraday time-series momentum in BTC, ETH and the top-10 perps

Run 2026-10-21 on the server as registered in
`results/intraday_tsmom_prereg.md` (committed first). Code:
`lab.experiments.intraday_tsmom`. The tables below the marker are generated
(rerun once the same evening after fixing the report column
`mean_bps_per_traded_day`, which had divided by the net position instead of
the traded size; no gate reads it).

## What it says

**No. The effect was real in 2020 to 2023 and is gone since; costs would
have eaten it anyway.**

- In sample the day so far did predict the last hours, as the papers say:
  before costs rule A (00:00 to 22:00 predicts 22:00 to 24:00) made Sharpe
  1.74 on BTC, 2.16 on ETH and 2.71 on the top 10, slope t 1.8 to 3.0.
- From 2024 the slopes are flat (t 0.25 to 0.56 for the picks) and before
  costs the picks make 0.05 (BTC), -0.46 (ETH, killed) and 0.55 (top 10):
  0.2, -2.1 and 2.1 bps per traded day.
- A round trip every day costs 10 bps on BTC and ETH at taker and 20 bps on
  the top 10; at taker the picks make **-2.97 (BTC), -2.67 (ETH), -4.61
  (top 10)**, drawdowns 65 to 84 %. Even at the 2 bps maker level (every
  order filled, no adverse selection) they lose: -1.16, -1.34, -0.48.
  Deflated p 0.00 for all.
- Holding long over the last hour of the UTC day lost about 3 bps a day out
  of sample on BTC and ETH (the hour before the 00:00 funding settlement);
  the window 22:00 to 24:00 drifted up by about half a basis point.

No paper book, no job.

<!-- generated below by lab.experiments.intraday_tsmom; edit above this line only -->

# Intraday time-series momentum in BTC, ETH and the top-10 perps: results

Generated 2026-10-21T19:25:44+00:00. Registered in `results/intraday_tsmom_prereg.md` before the run. Binance spot hourly bars to 2026-10-20; in sample 2020 to 2023, out of sample from 2024-01-01. Costs per side: taker 5 bps (BTC, ETH) and 10 bps (top 10), maker 2 bps; a round trip on every traded day. Daily returns, flat days as zero.

## Verdict

- **BTC**, pick rule A (00:00 to 22:00 predicts 22:00 to 24:00): **fail**. Out of sample Sharpe -2.97 at taker, -1.16 at maker, 0.05 before costs; years -2.19 / -3.90 / -3.05; five minutes late -3.47; band -4.16 to -1.90; drawdown 65 %; 0.2 bps per traded day before costs against a 10 bps taker round trip; slope t 0.56; deflated p 0.0000. Failed: 1 Sharpe above 0.5 at taker, 2 positive in 2 of 2024, 2025, 2026, 3 five minutes late above 0 at taker, 4 bootstrap 5 % above 0.
- **ETH**, pick rule A (00:00 to 22:00 predicts 22:00 to 24:00): **kill**. Out of sample Sharpe -2.67 at taker, -1.34 at maker, -0.46 before costs; years -0.98 / -3.34 / -3.73; five minutes late -3.29; band -3.68 to -1.74; drawdown 73 %; -2.1 bps per traded day before costs against a 10 bps taker round trip; slope t 0.25; deflated p 0.0000. Failed: 1 Sharpe above 0.5 at taker, 2 positive in 2 of 2024, 2025, 2026, 3 five minutes late above 0 at taker, 4 bootstrap 5 % above 0.
- **TOP10**, pick rule A (00:00 to 22:00 predicts 22:00 to 24:00): **fail**. Out of sample Sharpe -4.61 at taker, -0.48 at maker, 0.55 before costs; years -2.51 / -5.11 / -7.03; five minutes late -5.56; band -5.78 to -3.43; drawdown 84 %; 2.1 bps per traded day before costs against a 20 bps taker round trip; slope t 0.54; deflated p 0.0000. Failed: 1 Sharpe above 0.5 at taker, 2 positive in 2 of 2024, 2025, 2026, 3 five minutes late above 0 at taker, 4 bootstrap 5 % above 0.

## All nine trials

| asset | rule | is_0bps | is_taker | oos_0bps | oos_maker | oos_taker | late_taker | y2024 | y2025 | y2026 | oos_dd_pct | hit_pct | mean_bps_per_traded_day | traded_days_pct |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| BTC | A | 1.74 | 0.02 | 0.05 | -1.16 | -2.97 | -3.47 | -2.19 | -3.90 | -3.05 | 64.62 | 47.85 | 0.17 | 100.00 |
| BTC | B | 1.16 | -0.56 | 0.09 | -1.12 | -2.93 | -3.52 | -1.73 | -3.81 | -3.74 | 64.61 | 47.66 | 0.29 | 100.00 |
| BTC | C | 2.14 | -0.13 | 0.86 | -1.03 | -3.87 | -4.59 | -1.97 | -4.44 | -6.16 | 57.79 | 50.59 | 1.81 | 100.00 |
| ETH | A | 2.16 | 0.75 | -0.46 | -1.34 | -2.67 | -3.29 | -0.98 | -3.34 | -3.73 | 72.80 | 45.02 | -2.07 | 100.00 |
| ETH | B | 1.33 | -0.07 | -0.40 | -1.28 | -2.61 | -3.12 | -0.61 | -3.42 | -3.85 | 72.13 | 45.70 | -1.80 | 100.00 |
| ETH | C | 1.96 | 0.06 | -1.19 | -2.65 | -4.84 | -5.50 | -3.28 | -5.11 | -6.49 | 74.83 | 45.70 | -3.26 | 100.00 |
| TOP10 | A | 2.71 | -0.50 | 0.55 | -0.48 | -4.61 | -5.56 | -2.51 | -5.11 | -7.03 | 84.48 | 47.95 | 2.15 | 100.00 |
| TOP10 | B | 2.05 | -1.10 | 0.37 | -0.62 | -4.62 | -5.50 | -2.25 | -5.35 | -7.41 | 85.48 | 47.53 | 1.50 | 100.00 |
| TOP10 | C | 2.94 | -1.26 | 0.08 | -1.60 | -8.31 | -9.09 | -5.46 | -10.05 | -10.46 | 87.04 | 47.45 | 0.20 | 100.00 |

`late_taker`: entered at the 22:05 (rule C: 23:05) minute close, exit unchanged; for the top 10 only the coins with minute bars trade in that check (share of member slots: A 68 %, B 68 %, C 68 %).


Slope of the held return on the signal (Newey-West t, lag 5; the top 10 pooled over coin-days, t clustered by day):

| asset | rule | slope_is | slope_t_is | slope_oos | slope_t_oos |
|---|---|---|---|---|---|
| BTC | A | 0.052 | 1.830 | 0.006 | 0.563 |
| BTC | B | 0.039 | 1.572 | 0.004 | 0.398 |
| BTC | C | 0.047 | 1.719 | 0.008 | 1.094 |
| ETH | A | 0.061 | 2.623 | 0.003 | 0.249 |
| ETH | B | 0.044 | 2.221 | 0.002 | 0.185 |
| ETH | C | 0.043 | 2.244 | -0.002 | -0.259 |
| TOP10 | A | 0.062 | 3.041 | 0.004 | 0.539 |
| TOP10 | B | 0.050 | 2.630 | 0.005 | 0.743 |
| TOP10 | C | 0.046 | 2.519 | 0.002 | 0.342 |

## Control: always long over the window

| asset | window | cost | is | oos | mean_bps_oos |
|---|---|---|---|---|---|
| BTC | 22:00 to 24:00 | 0bps | 0.10 | 0.16 | 0.52 |
| BTC | 22:00 to 24:00 | taker | -1.62 | -2.86 | 0.52 |
| BTC | 23:00 to 24:00 | 0bps | -0.61 | -1.28 | -2.70 |
| BTC | 23:00 to 24:00 | taker | -2.88 | -6.01 | -2.70 |
| ETH | 22:00 to 24:00 | 0bps | 0.35 | 0.14 | 0.64 |
| ETH | 22:00 to 24:00 | taker | -1.05 | -2.07 | 0.64 |
| ETH | 23:00 to 24:00 | 0bps | -0.34 | -1.19 | -3.26 |
| ETH | 23:00 to 24:00 | taker | -2.24 | -4.84 | -3.26 |

Top-10 coins that were members at some point: 99.


## Pool

Pool: 1,953 trials (1,328 hand before this registration, 600 factory as read now, 25 registered together on 2026-10-21: perps_neutral_portfolio 3, attention_wiki 13, intraday_tsmom 9); the best noise trial sits at an annual Sharpe of about 2.75. The next study starts from 1,353 hand trials.
