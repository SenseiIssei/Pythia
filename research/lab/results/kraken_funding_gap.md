<!-- generated below by lab.experiments.kraken_funding_gap; edit above this line only -->

# Kraken against Binance funding gaps: results

Generated 2026-10-21T15:16:29+00:00. Registered in `results/kraken_funding_gap_prereg.md` before the run.

30 Alpaca coins with Kraken Futures funding and marks, Binance funding and Binance spot: AAVE, ADA, ARB, AVAX, BAT, BCH, BONK, BTC, CRV, DOGE, DOT, ETH, FIL, GRT, LDO, LINK, LTC, ONDO, PEPE, POL, RENDER, SHIB, SOL, SUSHI, TRUMP, UNI, WIF, XRP, XTZ, YFI. In sample 2025-10-18 to 2026-03-31, out of sample 2026-04-01 to 2026-10-19 (hourly). Short the Kraken perp, long spot, 8 % notional a position, at most 10; 35 bps a side on spot and 10 bps on the perp.

## Verdict

Pick **gap >= 50 % · 72 h**: **fails**. Out of sample 33 entries, net carry 16.3 % a year on deployed capital (funding 70.9 %, basis 7.1 %, costs -61.7 %), 1.2 % a year on all capital, 0.7 positions on average, Sharpe 1.06 (band -2.01 to 3.21), worst week -0.3 %, deflated p 0.0826. Maker on both legs (information): 57.4 % on deployed capital, Sharpe 3.81.

- 1 at least 10 entries: yes
- 2 net carry above 5 % a year on deployed capital: yes
- 3 worst week above -2 %: yes
- 4 Sharpe above 0, bootstrap 5 % above 0: no

## Every variant

| variant | is_entries | is_ret_capital_ann_pct | is_carry_deployed_ann_pct | is_sharpe | oos_entries | oos_ret_capital_ann_pct | oos_carry_deployed_ann_pct | oos_funding_deployed_ann_pct | oos_basis_deployed_ann_pct | oos_cost_deployed_ann_pct | oos_avg_positions | oos_sharpe | oos_worst_week_pct |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| gap >= 20 % · 24 h | 114 | -13.06 | -111.64 | -7.20 | 299 | -25.87 | -108.45 | 38.22 | 16.37 | -163.04 | 2.39 | -14.62 | -1.20 |
| gap >= 20 % · 72 h | 34 | -2.26 | -24.06 | -1.53 | 88 | -3.57 | -20.59 | 36.30 | 9.50 | -66.39 | 1.73 | -2.69 | -0.58 |
| gap >= 50 % · 24 h | 30 | -1.75 | -76.47 | -1.06 | 95 | -3.19 | -36.78 | 81.96 | 23.76 | -142.49 | 0.87 | -2.49 | -0.47 |
| gap >= 50 % · 72 h | 14 | -0.38 | -14.11 | -0.31 | 33 | 1.15 | 16.32 | 70.90 | 7.10 | -61.67 | 0.71 | 1.06 | -0.31 |

Returns a year: on all capital, and on deployed capital (10 % a position incl. perp margin), split into Kraken funding received, basis (spot minus perp mark) and costs.


## Kraken against Binance funding per coin, the whole window (information only)

| coin | kraken_ann_pct | binance_ann_pct | gap_ann_pct | share_gap_above_20 | share_gap_above_50 |
|---|---|---|---|---|---|
| RENDER | 4.69 | 0.76 | 3.93 | 0.19 | 0.03 |
| ETH | 3.49 | 2.50 | 0.99 | 0.00 | 0.00 |
| SOL | 0.46 | -0.45 | 0.92 | 0.02 | 0.00 |
| XRP | 0.65 | -0.04 | 0.69 | 0.01 | 0.00 |
| BTC | 3.26 | 3.34 | -0.08 | 0.00 | 0.00 |
| TRUMP | -23.75 | -23.66 | -0.09 | 0.16 | 0.04 |
| DOGE | 2.25 | 3.00 | -0.76 | 0.00 | 0.00 |
| BCH | -5.28 | -4.52 | -0.77 | 0.08 | 0.00 |
| PEPE | -1.94 | -0.77 | -1.17 | 0.04 | 0.01 |
| AVAX | -3.00 | -0.30 | -2.70 | 0.01 | 0.00 |
| ONDO | -2.70 | 0.14 | -2.84 | 0.06 | 0.01 |
| DOT | -8.10 | -5.19 | -2.90 | 0.03 | 0.01 |
| ARB | -1.52 | 1.89 | -3.41 | 0.04 | 0.01 |
| LINK | 1.04 | 4.57 | -3.53 | 0.00 | 0.00 |
| ADA | -1.85 | 1.91 | -3.75 | 0.00 | 0.00 |
| LDO | -0.52 | 3.57 | -4.09 | 0.02 | 0.00 |
| SHIB | -5.42 | -1.14 | -4.28 | 0.01 | 0.00 |
| LTC | -1.26 | 3.09 | -4.35 | 0.00 | 0.00 |
| AAVE | -1.60 | 2.84 | -4.44 | 0.00 | 0.00 |
| UNI | -0.44 | 4.42 | -4.85 | 0.02 | 0.01 |
| POL | -13.81 | -8.58 | -5.23 | 0.05 | 0.01 |
| FIL | -7.00 | -1.58 | -5.42 | 0.03 | 0.01 |
| WIF | -8.34 | -2.79 | -5.55 | 0.07 | 0.02 |
| CRV | -1.66 | 5.01 | -6.66 | 0.05 | 0.01 |
| BONK | -13.53 | -6.40 | -7.13 | 0.12 | 0.07 |
| SUSHI | -7.31 | 4.82 | -12.13 | 0.04 | 0.01 |
| XTZ | -19.66 | -6.10 | -13.56 | 0.05 | 0.02 |
| BAT | -22.86 | 1.12 | -23.98 | 0.13 | 0.09 |
| GRT | -23.03 | 1.05 | -24.08 | 0.10 | 0.04 |
| YFI | -50.16 | 1.98 | -52.14 | 0.14 | 0.10 |

Mean funding a year a long pays (%), and the share of hours the 24-hour gap was at least 20 % / 50 % a year.


## Pool

1,777 trials (1,140 hand, 600 factory, 37 registered today); the best noise trial sits at an annual Sharpe of about 2.83.
