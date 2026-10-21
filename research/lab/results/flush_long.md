<!-- generated below by lab.experiments.flush_long; edit above this line only -->

# Buying after a deleveraging flush: results

Generated 2026-10-21T14:47:12+00:00. Registered in `results/flush_long_prereg.md` before the run.

Events from 2022-01-04; out of sample from 2024-01-01 with exits by 2026-10-19. Returns net of 10 bps a side and the funding a long pays; excess over entries on matched days (same month, same BTC 200-day state, outside event windows).

## Verdict

Pick **OI -3 % · BTC · 7 d**: **fails**. 12 events out of sample, mean excess +147 bps per trade (event bootstrap 90 % band -133 bps to +433 bps); a close late +193 bps; at Alpaca spot costs +142 bps; at 20 bps +147 bps, at 0 bps +147 bps. Share of random matched entry sets with a mean as high: 0.17. As a daily book: Sharpe 0.17, deflated p 0.0000.

- 1 at least 6 out-of-sample events: yes
- 2 mean excess above 0 at 10 bps: yes
- 3 event bootstrap 5 % above 0: no
- 4 a close late still above 0: yes
- 5 above 0 at Alpaca spot costs: yes

## Events per year

- OI -3 %: 2022 7, 2023 4, 2024 5, 2025 3, 2026 4
- OI -5 %: 2022 6, 2023 3, 2024 3, 2025 1, 2026 2

## Every variant

| variant | is_events | is_mean_ret_bps | is_mean_excess_bps | is_hit | oos_events | oos_mean_ret_bps | oos_mean_matched_bps | oos_mean_excess_bps | oos_hit | book_is | book_oos |
|---|---|---|---|---|---|---|---|---|---|---|---|
| OI -3 % · BTC · 3 d | 11 | 132.04 | 246.89 | 0.55 | 12 | 122.03 | -106.60 | 228.64 | 0.67 | 0.44 | 0.45 |
| OI -3 % · BTC · 7 d | 11 | 338.47 | 518.86 | 0.55 | 12 | 53.17 | -93.75 | 146.92 | 0.58 | 0.80 | 0.17 |
| OI -3 % · top5 · 3 d | 11 | -82.13 | 78.98 | 0.64 | 12 | 223.47 | -152.65 | 376.12 | 0.67 | -0.17 | 0.57 |
| OI -3 % · top5 · 7 d | 11 | -80.71 | 238.91 | 0.55 | 12 | 16.86 | -198.76 | 215.62 | 0.50 | -0.08 | 0.10 |
| OI -5 % · BTC · 3 d | 9 | 97.78 | 173.10 | 0.44 | 6 | 254.49 | -97.54 | 352.03 | 0.67 | 0.28 | 0.58 |
| OI -5 % · BTC · 7 d | 9 | 176.80 | 299.99 | 0.56 | 6 | 7.74 | -175.42 | 183.16 | 0.50 | 0.35 | 0.05 |
| OI -5 % · top5 · 3 d | 9 | -170.26 | -52.85 | 0.44 | 6 | 415.29 | -153.24 | 568.54 | 0.67 | -0.19 | 0.74 |
| OI -5 % · top5 · 7 d | 9 | -239.83 | 8.35 | 0.44 | 6 | 44.69 | -312.19 | 356.88 | 0.67 | -0.23 | 0.10 |

Returns per trade in bps at 10 bps a side with funding; `hit` is the share of events above their matched mean; `book_*` the Sharpe of the daily book (in the trade after each event, cash otherwise).


## The pick's events

| day | doi_pct | fund_bps | btc_r3_pct | ret_pct | matched_pct | excess_pct | n_matched |
|---|---|---|---|---|---|---|---|
| 2022-01-22 | -3.69 | -0.90 | -15.88 | 8.61 | -4.98 | 13.59 | 23 |
| 2022-05-09 | -3.37 | -2.17 | -16.50 | -0.92 | -5.68 | 4.76 | 23 |
| 2022-08-19 | -5.86 | -5.65 | -12.66 | -3.02 | -2.77 | -0.25 | 23 |
| 2022-09-13 | -10.37 | -2.83 | -6.83 | -6.70 | 0.80 | -7.50 | 15 |
| 2022-09-20 | -5.68 | -1.30 | -6.14 | 0.83 | 0.80 | 0.03 | 15 |
| 2022-11-08 | -17.36 | -12.37 | -12.94 | -8.72 | -4.77 | -3.94 | 22 |
| 2022-12-17 | -7.05 | -5.24 | -5.82 | 0.03 | -0.49 | 0.53 | 23 |
| 2023-02-10 | -4.00 | -0.06 | -6.95 | 13.25 | -3.79 | 17.04 | 20 |
| 2023-03-10 | -7.04 | -1.52 | -9.23 | 35.56 | 0.71 | 34.85 | 23 |
| 2023-08-17 | -4.39 | -3.84 | -9.55 | -1.87 | -1.53 | -0.35 | 6 |
| 2023-09-01 | -7.83 | -1.24 | -6.88 | 0.17 | 1.86 | -1.69 | 22 |
| 2024-04-15 | -16.79 | -0.09 | -5.58 | 5.07 | -3.39 | 8.46 | 22 |
| 2024-07-05 | -4.72 | -2.12 | -8.88 | 1.87 | 0.14 | 1.73 | 1 |
| 2024-08-05 | -15.59 | -2.69 | -12.17 | 9.64 | 2.09 | 7.55 | 13 |
| 2024-08-27 | -4.01 | -0.11 | -7.38 | -3.46 | 2.09 | -5.56 | 13 |
| 2024-12-19 | -3.00 | -0.32 | -8.10 | -2.11 | 0.64 | -2.75 | 23 |
| 2025-04-07 | -4.09 | -1.02 | -5.63 | 6.56 | 5.09 | 1.47 | 13 |
| 2025-10-10 | -23.57 | -2.19 | -7.07 | -5.81 | -4.19 | -1.62 | 20 |
| 2025-11-22 | -3.44 | -0.17 | -7.45 | 6.93 | -5.41 | 12.34 | 20 |
| 2026-01-31 | -7.94 | -1.76 | -11.82 | -12.15 | -4.89 | -7.27 | 30 |
| 2026-03-07 | -7.58 | -3.42 | -7.45 | 5.74 | -1.45 | 7.20 | 23 |
| 2026-06-04 | -3.69 | -2.78 | -10.56 | -0.62 | -0.99 | 0.37 | 14 |
| 2026-06-18 | -3.68 | -1.73 | -5.07 | -5.28 | -0.99 | -4.29 | 14 |

## Pool

1,777 trials (1,140 hand, 600 factory, 37 registered today); the best noise trial sits at an annual Sharpe of about 2.71.
