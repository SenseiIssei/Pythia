# X16 B2: exit timing on the crypto books

Pre-registered in `equities_training_prereg.md` (part B2 and M14); the write-up is in `equities_training.md`.

<!-- generated below by lab.experiments.exit_overlays; edit above this line only -->

## Results (generated 2026-10-20, panel to 2026-10-19)

Out of sample from 2024-01-01 (1023 days), 35 bps per unit of turnover, books as they run on Alpaca. Pool 1668 trials (948 hand, 600 factory, 93 X16 equity trials, 27 here); noise bar about 2.64 annual on calendar days.

**Verdict: nothing passes.**

### The picks against the book

| book | pick | IS 35 | book IS | OOS 35 | book OOS | DD | book DD | years better | band | late | twin | twin book | defl. p diff | defl. p pool | failed |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| breakout_top10 | breakout_top10 · exit target 3 | 1.66 | 1.45 | 0.99 | 1.17 | 13.2 % | 16.0 % | 2 of 3 | -0.83 to 0.45 | 1.00 | 0.76 | 1.06 | 0.001 | 0.002 | 1 Sharpe and years, 3 band above 0, 4 one day late, 5 twin, 6 deflated improvement |
| tsmom_top20 | tsmom_top20 · exit ATR 2 | 1.69 | 1.68 | 0.38 | 0.53 | 7.4 % | 9.0 % | 0 of 3 | -0.51 to 0.19 | 0.31 | 0.09 | 0.21 | 0.004 | 0.000 | 1 Sharpe and years, 3 band above 0, 4 one day late, 5 twin, 6 deflated improvement |
| tsmom_tranches | tsmom_tranches · exit model | 1.88 | 1.85 | 1.64 | 0.64 | 1.5 % | 8.8 % | 2 of 3 | 0.11 to 1.76 | 1.48 | 1.34 | 0.37 | 0.021 | 0.031 | 6 deflated improvement |

### Capture of the current exits and of the picks (spells closed out of sample)

Per spell: bought at a close, sold at the first close after which it is no longer held. MFE is the highest close while held over the entry; capture = realised / MFE where MFE > 0; left on the table = the highest close in the 20 days after the sale over the sale price. 25/50/75th percentiles.

| book | spells | realised | MFE | capture | give-back | left on table | gains lost |
|---|---|---|---|---|---|---|---|
| breakout_top10 | 130 | -7.0/-1.7/8.6 % | 1.3/8.0/22.3 % | -0.85/0.12/0.49 | 8.0/11.4/16.2 % | 1.8/6.5/15.1 % | 37 % |
| tsmom_top20 | 276 | -5.2/-2.1/2.4 % | -1.3/2.5/12.6 % | -1.05/0.20/0.63 | 0.0/4.4/16.0 % | 1.5/7.1/15.9 % | 31 % |
| tsmom_tranches | 129 | -12.9/-4.3/15.1 % | 3.3/12.4/41.8 % | -1.23/-0.01/0.53 | 12.2/17.7/34.1 % | 2.8/8.0/16.4 % | 43 % |
| breakout_top10 · exit target 3 | 129 | -7.1/-1.9/7.7 % | 1.3/7.9/21.5 % | -0.85/0.11/0.51 | 6.1/10.0/14.8 % | 1.7/6.5/15.8 % | 37 % |
| tsmom_top20 · exit ATR 2 | 274 | -5.2/-1.6/2.2 % | -1.3/2.4/11.0 % | -1.09/0.12/0.58 | 0.0/4.5/13.7 % | 1.5/7.6/17.8 % | 28 % |
| tsmom_tranches · exit model | 79 | -4.1/-1.1/5.3 % | -1.3/0.8/8.3 % | -0.97/0.35/1.00 | 0.0/1.6/4.8 % | 1.8/7.7/20.3 % | 23 % |

### M14

Squared error 1.0896 vs 1.0485 for the training mean (3.9 % higher), DM p 0.2698, 8 of 23 quarters better, 16140 out-of-fold rows of 19848; zoo gate failed. Rank IC pooled 0.146, daily mean 0.027 (t 2.49); from 2024 0.181. Importance stability over 23 fits: mean 0.96, min 0.90 (first against last 0.94). Largest gain shares: btc_mom28 31 %, vol30 19 %, days_held 10 %, vol_ratio 7 %, mom28 7 %.

### The books (not counted)

| variant | is_35 | oos_35 | oos_70 | cagr | dd | expo | turnover_yr | y2024 | y2025 | y2026 |
|---|---|---|---|---|---|---|---|---|---|---|
| breakout_top10 live (its own simulator) | 1.45 | 1.17 | 1.04 | 0.18 | 0.16 | 0.14 | 5.71 | 2.19 | 0.32 | -0.02 |
| breakout_top10 twin (its own simulator) | 1.35 | 1.06 | 0.90 | 0.22 | 0.22 | 0.24 | 9.28 | 1.84 | 0.46 | 0.38 |
| tsmom_top20 live (its own simulator) | 1.68 | 0.53 | 0.28 | 0.04 | 0.09 | 0.09 | 6.27 | 1.56 | -0.35 | 0.43 |
| tsmom_top20 twin (its own simulator) | 1.31 | 0.21 | -0.09 | 0.02 | 0.24 | 0.17 | 13.06 | 0.37 | -0.29 | 0.67 |
| tsmom_tranches live (its own simulator) | 1.85 | 0.64 | 0.55 | 0.06 | 0.09 | 0.09 | 2.42 | 1.67 | -0.08 | 0.18 |
| tsmom_tranches twin (its own simulator) | 1.54 | 0.37 | 0.27 | 0.05 | 0.23 | 0.17 | 5.04 | 0.59 | 0.08 | 0.51 |
| breakout_top10 live (reference) | 1.45 | 1.17 | 1.04 | 0.18 | 0.16 | 0.14 | 5.71 | 2.19 | 0.32 | -0.02 |
| breakout_top10 twin (reference) | 1.35 | 1.06 | 0.90 | 0.22 | 0.22 | 0.24 | 9.28 | 1.84 | 0.46 | 0.38 |
| tsmom_top20 live (reference) | 1.68 | 0.53 | 0.28 | 0.04 | 0.09 | 0.09 | 6.27 | 1.56 | -0.35 | 0.43 |
| tsmom_top20 twin (reference) | 1.31 | 0.21 | -0.09 | 0.02 | 0.24 | 0.17 | 13.06 | 0.37 | -0.29 | 0.67 |
| tsmom_tranches live (reference) | 1.85 | 0.64 | 0.55 | 0.06 | 0.09 | 0.09 | 2.42 | 1.67 | -0.08 | 0.18 |
| tsmom_tranches twin (reference) | 1.54 | 0.37 | 0.27 | 0.05 | 0.23 | 0.17 | 5.02 | 0.59 | 0.08 | 0.51 |

### Every trial

| variant | is_35 | oos_35 | oos_70 | cagr | dd | expo | turnover_yr | y2024 | y2025 | y2026 | diff_sr | deflated_p_diff | deflated_p_pool | cut_share |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| breakout_top10 · exit time 20 | 1.53 | 0.98 | 0.80 | 0.11 | 0.16 | 0.11 | 5.67 | 1.93 | 0.54 | 0.16 | -0.83 | 0.00 | 0.00 | 0.18 |
| breakout_top10 · exit time 40 | 1.42 | 1.35 | 1.22 | 0.21 | 0.16 | 0.14 | 5.68 | 2.60 | 0.37 | -0.02 | 0.54 | 0.17 | 0.01 | 0.02 |
| breakout_top10 · exit ATR 2 | 1.50 | 1.18 | 1.04 | 0.18 | 0.16 | 0.13 | 5.74 | 2.18 | 0.29 | 0.15 | -0.36 | 0.01 | 0.01 | 0.09 |
| breakout_top10 · exit ATR 3 | 1.45 | 1.16 | 1.04 | 0.18 | 0.16 | 0.14 | 5.71 | 2.19 | 0.32 | -0.02 | -0.18 | 0.02 | 0.01 | 0.01 |
| breakout_top10 · exit target 2 | 1.45 | 0.97 | 0.76 | 0.09 | 0.13 | 0.10 | 5.66 | 2.06 | 0.56 | 0.18 | -0.85 | 0.00 | 0.00 | 0.19 |
| breakout_top10 · exit target 3 | 1.66 | 0.99 | 0.80 | 0.10 | 0.13 | 0.12 | 5.67 | 1.91 | 0.66 | 0.08 | -0.83 | 0.00 | 0.00 | 0.11 |
| breakout_top10 · exit model | 1.16 | 2.19 | 2.05 | 0.22 | 0.04 | 0.05 | 3.85 | 3.57 | 0.43 | 1.25 | 0.18 | 0.08 | 0.18 | 0.70 |
| tsmom_top20 · exit time 20 | 1.67 | 0.67 | 0.34 | 0.04 | 0.06 | 0.06 | 5.93 | 1.65 | -0.05 | 0.69 | -0.08 | 0.03 | 0.00 | 0.37 |
| tsmom_top20 · exit time 40 | 1.54 | 0.78 | 0.52 | 0.06 | 0.07 | 0.08 | 6.15 | 2.05 | -0.28 | 0.76 | 1.15 | 0.59 | 0.00 | 0.10 |
| tsmom_top20 · exit ATR 2 | 1.69 | 0.38 | 0.06 | 0.02 | 0.07 | 0.06 | 6.00 | 1.47 | -0.65 | 0.35 | -0.57 | 0.00 | 0.00 | 0.29 |
| tsmom_top20 · exit ATR 3 | 1.60 | 0.50 | 0.24 | 0.04 | 0.09 | 0.08 | 6.22 | 1.57 | -0.43 | 0.37 | -0.35 | 0.01 | 0.00 | 0.06 |
| tsmom_top20 · exit target 2 | 1.11 | 0.53 | 0.21 | 0.03 | 0.07 | 0.06 | 6.00 | 1.51 | -0.24 | 0.74 | -0.30 | 0.01 | 0.00 | 0.31 |
| tsmom_top20 · exit target 3 | 1.35 | 0.60 | 0.31 | 0.04 | 0.07 | 0.07 | 6.07 | 1.85 | -0.32 | 0.81 | -0.05 | 0.04 | 0.00 | 0.20 |
| tsmom_top20 · exit model | 1.62 | 1.55 | 1.22 | 0.06 | 0.04 | 0.03 | 3.47 | 2.91 | -0.63 | 1.32 | 0.17 | 0.08 | 0.02 | 0.75 |
| tsmom_tranches · exit time 20 | 1.71 | 0.77 | 0.61 | 0.04 | 0.05 | 0.04 | 2.17 | 1.37 | 0.47 | 0.47 | -0.34 | 0.01 | 0.00 | 0.53 |
| tsmom_tranches · exit time 40 | 1.53 | 1.19 | 1.09 | 0.09 | 0.07 | 0.07 | 2.31 | 2.55 | 0.07 | 0.82 | 0.94 | 0.44 | 0.01 | 0.26 |
| tsmom_tranches · exit ATR 2 | 1.75 | 0.65 | 0.52 | 0.04 | 0.07 | 0.05 | 2.20 | 1.73 | -0.21 | -0.15 | -0.41 | 0.01 | 0.00 | 0.50 |
| tsmom_tranches · exit ATR 3 | 1.60 | 0.62 | 0.52 | 0.05 | 0.08 | 0.07 | 2.32 | 1.69 | -0.34 | 0.12 | -0.40 | 0.01 | 0.00 | 0.24 |
| tsmom_tranches · exit target 2 | 1.17 | 0.76 | 0.62 | 0.04 | 0.06 | 0.05 | 2.24 | 1.81 | -0.06 | 1.05 | -0.32 | 0.01 | 0.00 | 0.39 |
| tsmom_tranches · exit target 3 | 1.59 | 0.73 | 0.61 | 0.05 | 0.07 | 0.07 | 2.31 | 1.80 | 0.01 | 0.77 | -0.23 | 0.02 | 0.00 | 0.25 |
| tsmom_tranches · exit model | 1.88 | 1.64 | 1.51 | 0.04 | 0.01 | 0.02 | 0.95 | 3.19 | -0.55 | 0.58 | -0.20 | 0.02 | 0.03 | 0.86 |
| breakout_top10 · exit target 3 · a day late | 1.56 | 1.00 | 0.81 | 0.11 | 0.13 | 0.12 | 5.67 | 1.98 | 0.62 | 0.06 | -0.82 | 0.00 | 0.00 | None |
| breakout_top10 · exit target 3 · twin | 1.32 | 0.76 | 0.54 | 0.11 | 0.17 | 0.20 | 9.30 | 1.22 | 0.96 | -0.03 | -0.98 | 0.00 | 0.00 | None |
| tsmom_top20 · exit ATR 2 · a day late | 1.72 | 0.31 | -0.00 | 0.02 | 0.08 | 0.07 | 6.05 | 1.38 | -0.73 | 0.32 | -0.73 | 0.00 | 0.00 | None |
| tsmom_top20 · exit ATR 2 · twin | 1.31 | 0.09 | -0.27 | 0.00 | 0.21 | 0.13 | 12.61 | 0.35 | -0.64 | 0.75 | -0.37 | 0.01 | 0.00 | None |
| tsmom_tranches · exit model · a day late | 1.85 | 1.48 | 1.34 | 0.04 | 0.02 | 0.02 | 1.15 | 2.85 | -0.72 | 0.75 | -0.22 | 0.02 | 0.02 | None |
| tsmom_tranches · exit model · twin | 1.73 | 1.34 | 1.18 | 0.07 | 0.04 | 0.04 | 2.12 | 2.59 | 0.43 | 0.54 | 0.02 | 0.05 | 0.01 | None |
