# pump.fun real-time lab (2026-10-20)

Paper only: no wallet, no key, no transaction. Fills are modelled with latency; real snipers are faster.

Paper only. 2 day(s) of record: 3,459 tokens (1,495 on plain SOL curves), 315,357 curve trades, 76 completed curves. Too early to judge (the bar needs 14 days and 300 out-of-sample trades). Out of sample the pick B_w10_x1 made 42 trades, mean -11.4 % per trade, -0.48 SOL; 0 of 23 rules pass the bar. The model beats its baselines on 0 of 4 labels.

## Record

| day | tokens | plain SOL | curve trades | completed | migrated | gaps | gap min |
|---|---|---|---|---|---|---|---|
| 2026-10-19 | 1,613 | 708 | 152,546 | 38 | 39 | 11 | 0.8 |
| 2026-10-20 | 1,846 | 787 | 162,811 | 38 | 44 | 14 | 4.8 |

Completeness: 94,804 trades on 1,495 plain curves; 1,093 slots did not chain up (a trade the stream missed), 31% of the curves have at least one. A trade whose hold spans one is marked; their share is the "broken" column.

Split at 2026-10-20 00:11 UTC; pick B_w10_x1 (in-sample mean).

## Rules out of sample

| rule | trades | failed | hit | mean | median | 5 % | 95 % | worst | best | at -90 % | dev dumped | broken | mean, unbroken | P&L SOL | band of mean | lat 2x | prio 3x | in-sample mean (n) | passes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A_all_x1 | 600 | 20 | +12.0 % | -4.8 % | -5.1 % | -28.2 % | +20.0 % | -58.1 % | +136.7 % | 0 | +23.5 % | +3.3 % | -5.2 % | -2.882 | n/a to n/a | -4.5 % | -8.8 % | -5.9 % (764) | no |
| A_all_x2 | 536 | 21 | +8.8 % | -8.7 % | -5.1 % | -41.6 % | +10.6 % | -70.3 % | +165.5 % | 0 | +36.4 % | +4.5 % | -9.6 % | -4.690 | n/a to n/a | -8.2 % | -12.7 % | -6.8 % (662) | no |
| A_dev_x1 | 295 | 3 | +19.7 % | -5.1 % | -5.3 % | -35.7 % | +45.3 % | -58.1 % | +123.5 % | 0 | +41.4 % | +5.8 % | -5.8 % | -1.502 | n/a to n/a | -5.6 % | -9.1 % | -6.1 % (323) | no |
| A_dev_x2 | 265 | 3 | +11.3 % | -12.7 % | -13.7 % | -46.8 % | +47.4 % | -70.3 % | +148.7 % | 0 | +57.7 % | +7.5 % | -14.7 % | -3.369 | n/a to n/a | -12.8 % | -16.7 % | -7.5 % (287) | no |
| A_cmig_x1 | 8 | 0 | +37.5 % | +7.9 % | -5.0 % | -12.6 % | +52.0 % | -13.0 % | +67.3 % | 0 | +25.0 % | +0.0 % | +7.9 % | +0.063 | n/a to n/a | +11.1 % | +3.9 % | +12.7 % (3) | no |
| A_cmig_x2 | 7 | 0 | +14.3 % | -9.2 % | -18.7 % | -30.8 % | +35.1 % | -33.5 % | +52.6 % | 0 | +71.4 % | +14.3 % | -9.8 % | -0.065 | n/a to n/a | -6.7 % | -13.2 % | +23.1 % (3) | no |
| B_w3_x1 | 107 | 6 | +19.6 % | -9.0 % | -11.9 % | -40.3 % | +41.8 % | -60.1 % | +121.6 % | 0 | +53.3 % | +6.5 % | -11.3 % | -0.970 | n/a to n/a | -9.2 % | -13.0 % | -7.2 % (139) | no |
| B_w3_x2 | 96 | 4 | +16.7 % | -9.3 % | -21.0 % | -51.9 % | +135.1 % | -61.1 % | +184.3 % | 0 | +64.6 % | +16.7 % | -19.7 % | -0.901 | n/a to n/a | -9.8 % | -13.3 % | -13.3 % (99) | no |
| B_w10_x1 | 42 | 0 | +31.0 % | -11.4 % | -13.7 % | -53.6 % | +48.4 % | -58.8 % | +102.4 % | 0 | +38.1 % | +9.5 % | -11.8 % | -0.477 | n/a to n/a | -12.7 % | -15.4 % | -2.7 % (73) | no |
| B_w10_x2 | 37 | 0 | +21.6 % | -15.6 % | -25.9 % | -54.2 % | +41.3 % | -61.3 % | +160.8 % | 0 | +51.4 % | +18.9 % | -20.2 % | -0.577 | n/a to n/a | -18.1 % | -19.6 % | -11.6 % (53) | no |
| C_20in60_x1 | 41 | 0 | +22.0 % | -14.3 % | -27.0 % | -46.3 % | +91.4 % | -60.2 % | +101.3 % | 0 | +53.7 % | +19.5 % | -16.8 % | -0.585 | n/a to n/a | -14.0 % | -18.3 % | -10.5 % (35) | no |
| C_20in60_x2 | 34 | 0 | +5.9 % | -30.1 % | -40.1 % | -56.2 % | +28.6 % | -61.1 % | +101.6 % | 0 | +67.6 % | +29.4 % | -32.6 % | -1.024 | n/a to n/a | -30.2 % | -34.1 % | -27.5 % (21) | no |
| C_50in300_x1 | 11 | 1 | +9.1 % | -32.0 % | -40.6 % | -52.6 % | +3.1 % | -58.8 % | +19.3 % | 0 | +54.5 % | +18.2 % | -31.0 % | -0.353 | n/a to n/a | -32.2 % | -36.0 % | -14.5 % (19) | no |
| C_50in300_x2 | 9 | 1 | +0.0 % | -46.6 % | -46.1 % | -56.9 % | -40.1 % | -58.8 % | -39.8 % | 0 | +66.7 % | +22.2 % | -47.6 % | -0.420 | n/a to n/a | -46.9 % | -50.6 % | -26.6 % (11) | no |
| D_p80_x1 | 7 | 16 | +14.3 % | -13.8 % | -24.6 % | -29.9 % | +23.4 % | -31.1 % | +33.5 % | 0 | +0.0 % | +14.3 % | -11.6 % | -0.113 | n/a to n/a | -8.9 % | -17.8 % | -1.4 % (15) | no |
| D_p80_x2 | 7 | 16 | +28.6 % | -5.8 % | -31.1 % | -37.2 % | +64.6 % | -37.8 % | +69.3 % | 0 | +0.0 % | +14.3 % | -0.8 % | -0.056 | n/a to n/a | -3.1 % | -9.8 % | -12.5 % (13) | no |
| D_p90_x1 | 4 | 16 | +75.0 % | +11.6 % | +20.0 % | -18.1 % | +29.6 % | -23.8 % | +30.2 % | 0 | +0.0 % | +25.0 % | +23.4 % | +0.030 | n/a to n/a | +13.8 % | +7.6 % | +15.9 % (8) | no |
| D_p90_x2 | 2 | 16 | +100.0 % | +61.3 % | +61.3 % | +54.4 % | +68.2 % | +53.7 % | +68.9 % | 0 | +0.0 % | +0.0 % | +61.3 % | +0.107 | n/a to n/a | +60.4 % | +57.3 % | +18.4 % (6) | no |
| E_d0_x1 | 7 | 11 | +28.6 % | -16.0 % | -0.3 % | -74.8 % | +23.5 % | -85.9 % | +28.9 % | 0 | +0.0 % | +0.0 % | -16.0 % | -0.123 | n/a to n/a | -14.4 % | -20.0 % | -9.4 % (6) | no |
| E_d0_x2 | 3 | 11 | +33.3 % | +5.9 % | -48.8 % | -82.2 % | +132.4 % | -85.9 % | +152.6 % | 0 | +0.0 % | +0.0 % | +5.9 % | +0.007 | n/a to n/a | +8.0 % | +1.9 % | -43.2 % (1) | no |
| E_d60_x1 | 12 | 1 | +50.0 % | -2.3 % | +1.4 % | -77.9 % | +52.4 % | -86.5 % | +61.5 % | 0 | +0.0 % | +0.0 % | -2.3 % | -0.029 | n/a to n/a | +0.3 % | -6.3 % | +3.0 % (8) | no |
| E_d60_x2 | 6 | 1 | +16.7 % | -36.3 % | -53.4 % | -82.6 % | +56.0 % | -86.5 % | +88.8 % | 0 | +0.0 % | +0.0 % | -36.3 % | -0.219 | n/a to n/a | -36.5 % | -40.3 % | -46.4 % (3) | no |
| B_w10_x1+model | 42 | 0 | +31.0 % | -11.4 % | -13.7 % | -53.6 % | +48.4 % | -58.8 % | +102.4 % | 0 | +38.1 % | +9.5 % | -11.8 % | -0.477 | n/a to n/a | n/a | n/a | -2.6 % (69) | no |

Gates (out of sample): g1 mean and its hour-block band above 0; g2 300+ trades over 14+ days; g3 above 0 at doubled latency and tripled priority fee; g4 best five under half the P&L and 60 % of days positive; g5 deflated p above 0.95; g6 (model) beats the pick, band of the difference above 0.

- A_all_x1: fails g1_mean_band, g2_size, g3_stress, g4_breadth, g5_deflated; deflated p n/a (under 5 days)
- A_all_x2: fails g1_mean_band, g2_size, g3_stress, g4_breadth, g5_deflated; deflated p n/a (under 5 days)
- A_dev_x1: fails g1_mean_band, g2_size, g3_stress, g4_breadth, g5_deflated; deflated p n/a (under 5 days)
- A_dev_x2: fails g1_mean_band, g2_size, g3_stress, g4_breadth, g5_deflated; deflated p n/a (under 5 days)
- A_cmig_x1: fails g1_mean_band, g2_size, g4_breadth, g5_deflated; deflated p n/a (under 5 days)
- A_cmig_x2: fails g1_mean_band, g2_size, g3_stress, g4_breadth, g5_deflated; deflated p n/a (under 5 days)
- B_w3_x1: fails g1_mean_band, g2_size, g3_stress, g4_breadth, g5_deflated; deflated p n/a (under 5 days)
- B_w3_x2: fails g1_mean_band, g2_size, g3_stress, g4_breadth, g5_deflated; deflated p n/a (under 5 days)
- B_w10_x1: fails g1_mean_band, g2_size, g3_stress, g4_breadth, g5_deflated; deflated p n/a (under 5 days)
- B_w10_x2: fails g1_mean_band, g2_size, g3_stress, g4_breadth, g5_deflated; deflated p n/a (under 5 days)
- C_20in60_x1: fails g1_mean_band, g2_size, g3_stress, g4_breadth, g5_deflated; deflated p n/a (under 5 days)
- C_20in60_x2: fails g1_mean_band, g2_size, g3_stress, g4_breadth, g5_deflated; deflated p n/a (under 5 days)
- C_50in300_x1: fails g1_mean_band, g2_size, g3_stress, g4_breadth, g5_deflated; deflated p n/a (under 5 days)
- C_50in300_x2: fails g1_mean_band, g2_size, g3_stress, g4_breadth, g5_deflated; deflated p n/a (under 5 days)
- D_p80_x1: fails g1_mean_band, g2_size, g3_stress, g4_breadth, g5_deflated; deflated p n/a (under 5 days)
- D_p80_x2: fails g1_mean_band, g2_size, g3_stress, g4_breadth, g5_deflated; deflated p n/a (under 5 days)
- D_p90_x1: fails g1_mean_band, g2_size, g4_breadth, g5_deflated; deflated p n/a (under 5 days)
- D_p90_x2: fails g1_mean_band, g2_size, g4_breadth, g5_deflated; deflated p n/a (under 5 days)
- E_d0_x1: fails g1_mean_band, g2_size, g3_stress, g4_breadth, g5_deflated; deflated p n/a (under 5 days)
- E_d0_x2: fails g1_mean_band, g2_size, g4_breadth, g5_deflated; deflated p n/a (under 5 days)
- E_d60_x1: fails g1_mean_band, g2_size, g3_stress, g4_breadth, g5_deflated; deflated p n/a (under 5 days)
- E_d60_x2: fails g1_mean_band, g2_size, g3_stress, g4_breadth, g5_deflated; deflated p n/a (under 5 days)
- B_w10_x1+model: fails g1_mean_band, g2_size, g3_stress, g4_breadth, g5_deflated, g6_model_beats_pick; deflated p n/a (under 5 days)

Deflation pool: 1230 trials (907 hand, 300 factory, 23 here); the best of that many noise strategies shows an annual Sharpe of about 2.85.

Failed buys: curve completed before the buy landed 162, slippage 61, no pool state 38

## Model

| label | rows | folds | model AUC | Brier skill | ECE | logistic AUC | base rate | verdict |
|---|---|---|---|---|---|---|---|---|
| dump60 | 1455 | 3 | 0.755 | +0.191 | 0.062 | 0.721 | 0.268 | not useful: AUC 0.755, Brier skill +0.191, beats the logistic baseline in 1 of 3 folds |
| win30 | 2527 | 4 | 0.708 | -0.097 | 0.022 | 0.782 | 0.046 | not useful: AUC 0.708, Brier skill -0.097, beats the logistic baseline in 2 of 4 folds |
| win300 | 2517 | 4 | 0.643 | -0.001 | 0.017 | 0.688 | 0.038 | not useful: AUC 0.643, Brier skill -0.001, beats the logistic baseline in 2 of 4 folds |
| mig | 12 | 0 | nan | +nan | nan | nan | nan | too few labelled rows (12) |

dump60 top features (gain): net_sol_10s 0.19, uri_ipfs 0.11, dev_buy_sol 0.09, first5_share 0.08, creator_dump_rate 0.06, creator_log_since 0.06, dev_hold_share 0.05, market_10m 0.05

win30 top features (gain): progress 0.12, dev_buy_sol 0.09, market_10m 0.09, top5_share 0.07, secs_since_trade 0.06, net_sol_10s 0.05, top1_share 0.05, buy_sol 0.04

win300 top features (gain): market_10m 0.13, first5_share 0.09, top1_share 0.09, dev_buy_sol 0.08, name_len 0.08, from_peak 0.05, progress 0.05, buy_sol 0.04
