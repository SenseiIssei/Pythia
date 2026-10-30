# SW1: the lab's swing rules and a short hold grid on the rug-free coin universe, at Hyperliquid's costs

Pre-registered in `results/swing_sw1_prereg.md` (committed before the first run). Code: `lab.experiments.swing_sw1`,
tests `tests/test_swing_sw1.py`. Paper only: nothing a live bot, a wallet or the engine reads changed.

Run 2026-10-30 as registered, the lockbox not read. 222 trials in R5's registry (small family, with their in-sample
Sharpes; written to a copy in the agent run, the server's registry gets them from it), registered before any
out-of-sample number. Data: Binance's daily klines of the perps from `<data>`, and 6,107 months of Binance USD-M
1-hour klines of 382 perps (delisted ones included) from data.binance.vision for the realised variance, cached in the
agent's folder, not in `<data>` (DT1's minute cache was gone; the 1-hour bars match the daily klines' closes on 100 %
of 184,906 coin-days). Funding out of sample: Hyperliquid's own hourly rates on every coin-day held.

## Reading

**No. No swing rule passes at 50 EUR or at 200 EUR, on time or one day late. Do not fund a swing bot on these
rules.** Nothing goes onto the ladder as a step-2 candidate, no paper book, no forward shadow.

- **At 50 EUR the 10 USD minimum decides most rules, not the market.** breakout_top10, breakout_sol10, tsmom_top20 and
  both long/short forms never send a single order: their positions are 1/10 or 1/20 of 57 USD, under 10 USD, so 100 %
  of their entries are skipped (108 to 371 a rule out of sample). The H grid sends 5 to 24 % of its entries (76 to
  95 % skipped). Only the one- and two-coin rules trade normally (tsmom1, breakout_btceth, btc_gated,
  memes_rotation, breakout_sol3 with 23 % skipped). The position cap almost never binds; the minimum does.
- **The out-of-sample window was a BTC bear market**: BTC held lost 26.8 % a year (Sharpe -0.49, drawdown 53 %). Every
  book that mostly sat in cash "beats BTC" on Sharpe, but no excess over BTC has a bootstrap band above 0 (the best
  lower end is memes_rotation's -11.4 % a year), and no DSR comes near 0.95 (best 0.019, noise bar 3.08 a year over
  4,178 trials).
- **The closest calls are small and fragile.** memes_rotation at 57 USD: Sharpe 0.83, +19.9 % a year, drawdown 17 %,
  one day late 0.35, 21 trades; band -11.4 %, DSR 0.002. tsmom_top20_ls at 228 USD shows Sharpe 1.37 on 4 entries
  (99 % skipped, 3 % a year). H:N10:D5:K5 at 57 USD shows 0.79 on 22 trades and is -0.69 one day late. Every H
  cell, at every account size, is negative one day late.
- **The rules themselves (ideal account, no minimum) did not work out of sample either**: breakout_top10 -0.23 (in
  sample 1.00), tsmom_top20 0.08, btc_gated -0.52, tsmom1 0.20, the best H cell 0.67 and -0.22 late. The in-sample
  edge of 2022 to 2024 (Sharpe 0.6 to 1.6 for the R rules) did not carry into 2025 and 2026.
- **Hyperliquid's fees are not the problem; its funding is larger.** Taker fees plus slippage cost 0.1 to 1.3 % of the
  account a year at these turnovers, funding up to 5.5 % (2 to 4 % for the one- and two-coin rules). Cheap fees remove the cost wall that sank S1 and
  R10 on Kraken; what is left is a rule with no proven edge.

What would change the answer: a larger account (the ten-coin rules need about 100 USD a position, so 1,000 USD and
more to run as designed), or a rule that is still positive in a falling market. Neither is shown here.

<!-- generated below by lab.experiments.swing_sw1; edit above this line only -->

Generated 2026-10-30T12:59:00+00:00. Binance USD-M daily klines (and 1-hour klines for the realised variance) to 2026-06-30, nothing after it read (the lockbox untouched); in sample 2022-01-01 to 2024-12-31 on the whole Binance universe, judged out of sample 2025-01-01 to 2026-06-30 (546 days) on the coins Hyperliquid listed each day. 37 rules, 3 accounts, 2 fills: 222 trials in R5's registry (small family, each with its in-sample Sharpe, registered before any out-of-sample number); pool of all 4178 trials, noise bar 3.08 a year (small family 652, 1.87). BTC held (perp, open to open, no cost) out of sample: Sharpe -0.49, CAGR -26.8 %, drawdown 53.0 %.

Passed: none.

## Out of sample at 50 EUR (57 USD), on time

Sharpe and CAGR of the account; late: one day late; band: 5 % quantile of the bootstrap of the mean daily excess over BTC, a year; entries: the rule's entries out of sample, sent, and the share the 10 USD minimum or the position cap skipped.

| rule | Sharpe | CAGR | max DD | end USD | late | excess | band | DSR | DSR excess | entries | sent | skipped | costs/yr | funding/yr | IS Sharpe | fails |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| breakout_top10 | 0.00 | 0.0 % | 0.0 % | 57.00 | 0.00 | 21.5 % | -32.3 % | 0.000 | 0.001 | 108 | 0 | 100.0 % | 0.0 % | 0.0 % | 0.00 | late 0.00; band -32.3 %; DSR 0.000; 0 entries |
| breakout_btceth | 0.18 | 1.5 % | 15.1 % | 58.31 | 0.14 | 24.1 % | -26.8 % | 0.000 | 0.001 | 6 | 6 | 0.0 % | 0.2 % | 2.5 % | 0.87 | band -26.8 %; DSR 0.000; 6 entries |
| tsmom1 | 0.14 | 0.8 % | 13.7 % | 57.71 | -0.02 | 24.5 % | -26.5 % | 0.000 | 0.001 | 13 | 13 | 0.0 % | 0.7 % | 3.6 % | 1.57 | late -0.02; band -26.5 %; DSR 0.000 |
| tsmom_top20 | 0.00 | 0.0 % | 0.0 % | 57.00 | 0.00 | 21.5 % | -32.3 % | 0.000 | 0.001 | 269 | 0 | 100.0 % | 0.0 % | 0.0 % | 0.00 | late 0.00; band -32.3 %; DSR 0.000; 0 entries |
| breakout_sol3 | -0.03 | -1.5 % | 18.6 % | 55.77 | -0.41 | 21.1 % | -28.1 % | 0.000 | 0.001 | 30 | 23 | 23.3 % | 0.4 % | 2.3 % | 1.24 | late -0.41; band -28.1 %; DSR 0.000 |
| breakout_sol10 | 0.00 | 0.0 % | 0.0 % | 57.00 | 0.00 | 21.5 % | -32.3 % | 0.000 | 0.001 | 61 | 0 | 100.0 % | 0.0 % | 0.0 % | 0.00 | late 0.00; band -32.3 %; DSR 0.000; 0 entries |
| btc_gated | -0.52 | -17.0 % | 32.7 % | 43.12 | -0.51 | 6.8 % | -37.1 % | 0.000 | 0.000 | 9 | 9 | 0.0 % | 0.5 % | 5.5 % | 1.14 | Sharpe -0.52 vs BTC -0.49; late -0.51; band -37.1 %; DSR 0.000; 9 entries |
| memes_rotation | 0.83 | 19.9 % | 17.0 % | 74.73 | 0.35 | 42.7 % | -11.4 % | 0.002 | 0.004 | 21 | 21 | 0.0 % | 0.7 % | 2.4 % | 1.51 | band -11.4 %; DSR 0.002 |
| breakout_top10_ls | 0.00 | 0.0 % | 0.0 % | 57.00 | 0.00 | 21.5 % | -32.3 % | 0.000 | 0.001 | 190 | 0 | 100.0 % | 0.0 % | 0.0 % | 0.00 | late 0.00; band -32.3 %; DSR 0.000; 0 entries |
| tsmom_top20_ls | 0.00 | 0.0 % | 0.0 % | 57.00 | 0.00 | 21.5 % | -32.3 % | 0.000 | 0.001 | 371 | 0 | 100.0 % | 0.0 % | 0.0 % | 0.00 | late 0.00; band -32.3 %; DSR 0.000; 0 entries |
| H:N10:D5:K5 | 0.79 | 2.2 % | 2.0 % | 58.87 | -0.69 | 23.6 % | -29.4 % | 0.002 | 0.001 | 135 | 22 | 83.7 % | 0.3 % | 0.5 % | 0.67 | late -0.69; band -29.4 %; DSR 0.002 |
| H:N10:D5:K10 | -0.05 | -0.3 % | 5.3 % | 56.74 | -1.63 | 21.2 % | -31.3 % | 0.000 | 0.001 | 268 | 35 | 86.9 % | 0.5 % | 0.6 % | 0.73 | late -1.63; band -31.3 %; DSR 0.000 |
| H:N10:D5:K20 | 0.24 | 0.8 % | 5.0 % | 57.72 | -1.01 | 22.4 % | -29.5 % | 0.000 | 0.001 | 533 | 31 | 94.2 % | 0.4 % | 0.6 % | 1.22 | late -1.01; band -29.5 %; DSR 0.000 |
| H:N10:D10:K5 | -0.51 | -1.5 % | 3.2 % | 55.70 | -0.48 | 20.0 % | -33.0 % | 0.000 | 0.001 | 120 | 17 | 85.8 % | 0.2 % | 0.5 % | 1.03 | Sharpe -0.51 vs BTC -0.49; late -0.48; band -33.0 %; DSR 0.000 |
| H:N10:D10:K10 | -1.33 | -6.5 % | 10.1 % | 51.57 | -1.77 | 14.9 % | -37.1 % | 0.000 | 0.000 | 237 | 23 | 90.3 % | 0.3 % | 0.6 % | 1.50 | Sharpe -1.33 vs BTC -0.49; late -1.77; band -37.1 %; DSR 0.000 |
| H:N10:D10:K20 | -0.62 | -3.1 % | 8.7 % | 54.35 | -1.23 | 18.4 % | -33.5 % | 0.000 | 0.001 | 491 | 26 | 94.7 % | 0.4 % | 0.5 % | 1.91 | Sharpe -0.62 vs BTC -0.49; late -1.23; band -33.5 %; DSR 0.000 |
| H:N10:D20:K5 | -0.28 | -0.9 % | 3.9 % | 56.19 | -0.39 | 20.6 % | -32.1 % | 0.000 | 0.001 | 117 | 17 | 85.5 % | 0.2 % | 0.6 % | 0.88 | late -0.39; band -32.1 %; DSR 0.000 |
| H:N10:D20:K10 | -1.02 | -5.2 % | 9.9 % | 52.60 | -1.63 | 16.2 % | -35.8 % | 0.000 | 0.000 | 228 | 23 | 89.9 % | 0.3 % | 0.7 % | 1.24 | Sharpe -1.02 vs BTC -0.49; late -1.63; band -35.8 %; DSR 0.000 |
| H:N10:D20:K20 | -0.54 | -2.9 % | 9.0 % | 54.53 | -1.90 | 18.6 % | -32.8 % | 0.000 | 0.001 | 471 | 23 | 95.1 % | 0.3 % | 0.6 % | 1.73 | Sharpe -0.54 vs BTC -0.49; late -1.90; band -32.8 %; DSR 0.000 |
| H:N20:D5:K5 | -0.41 | -1.3 % | 4.5 % | 55.88 | -1.34 | 20.2 % | -32.3 % | 0.000 | 0.001 | 81 | 16 | 80.2 % | 0.2 % | 0.4 % | 0.86 | late -1.34; band -32.3 %; DSR 0.000 |
| H:N20:D5:K10 | -0.53 | -2.6 % | 7.7 % | 54.77 | -1.63 | 18.9 % | -32.9 % | 0.000 | 0.001 | 156 | 27 | 82.7 % | 0.4 % | 0.6 % | 0.94 | Sharpe -0.53 vs BTC -0.49; late -1.63; band -32.9 %; DSR 0.000 |
| H:N20:D5:K20 | -0.25 | -1.3 % | 5.8 % | 55.90 | -1.15 | 20.3 % | -32.2 % | 0.000 | 0.001 | 313 | 27 | 91.4 % | 0.4 % | 0.5 % | 1.41 | late -1.15; band -32.2 %; DSR 0.000 |
| H:N20:D10:K5 | -0.49 | -2.1 % | 6.2 % | 55.23 | -0.54 | 19.4 % | -33.8 % | 0.000 | 0.001 | 67 | 11 | 83.6 % | 0.2 % | 0.4 % | 1.46 | Sharpe -0.49 vs BTC -0.49; late -0.54; band -33.8 %; DSR 0.000 |
| H:N20:D10:K10 | -0.27 | -2.3 % | 7.7 % | 55.05 | -1.29 | 19.4 % | -32.6 % | 0.000 | 0.001 | 131 | 22 | 83.2 % | 0.3 % | 0.6 % | 1.48 | late -1.29; band -32.6 %; DSR 0.000 |
| H:N20:D10:K20 | 0.72 | 4.1 % | 5.0 % | 60.55 | -0.42 | 25.7 % | -26.5 % | 0.003 | 0.001 | 268 | 18 | 93.3 % | 0.3 % | 0.6 % | 1.57 | late -0.42; band -26.5 %; DSR 0.003 |
| H:N20:D20:K5 | -0.77 | -3.2 % | 6.4 % | 54.32 | -1.10 | 18.3 % | -34.9 % | 0.000 | 0.001 | 60 | 8 | 86.7 % | 0.1 % | 0.4 % | 1.19 | Sharpe -0.77 vs BTC -0.49; late -1.10; band -34.9 %; DSR 0.000; 8 entries |
| H:N20:D20:K10 | -0.30 | -2.3 % | 9.9 % | 55.01 | -0.96 | 19.3 % | -31.8 % | 0.000 | 0.001 | 116 | 17 | 85.3 % | 0.2 % | 0.7 % | 0.90 | late -0.96; band -31.8 %; DSR 0.000 |
| H:N20:D20:K20 | -0.32 | -1.9 % | 8.1 % | 55.41 | -0.96 | 19.7 % | -32.1 % | 0.000 | 0.001 | 238 | 16 | 93.3 % | 0.2 % | 0.6 % | 1.15 | late -0.96; band -32.1 %; DSR 0.000 |
| H:N55:D5:K5 | -0.72 | -1.8 % | 4.6 % | 55.44 | -1.03 | 19.6 % | -33.7 % | 0.000 | 0.001 | 45 | 11 | 75.6 % | 0.2 % | 0.3 % | 0.95 | Sharpe -0.72 vs BTC -0.49; late -1.03; band -33.7 %; DSR 0.000 |
| H:N55:D5:K10 | -1.16 | -4.5 % | 8.0 % | 53.17 | -2.21 | 16.9 % | -35.2 % | 0.000 | 0.001 | 82 | 18 | 78.0 % | 0.3 % | 0.4 % | 1.61 | Sharpe -1.16 vs BTC -0.49; late -2.21; band -35.2 %; DSR 0.000 |
| H:N55:D5:K20 | -0.84 | -3.8 % | 8.0 % | 53.80 | -1.85 | 17.7 % | -33.9 % | 0.000 | 0.001 | 157 | 22 | 86.0 % | 0.3 % | 0.5 % | 1.65 | Sharpe -0.84 vs BTC -0.49; late -1.85; band -33.9 %; DSR 0.000 |
| H:N55:D10:K5 | -1.03 | -2.9 % | 7.6 % | 54.54 | -1.82 | 18.5 % | -34.7 % | 0.000 | 0.001 | 40 | 9 | 77.5 % | 0.1 % | 0.4 % | 1.62 | Sharpe -1.03 vs BTC -0.49; late -1.82; band -34.7 %; DSR 0.000; 9 entries |
| H:N55:D10:K10 | -1.93 | -7.6 % | 12.2 % | 50.67 | -2.33 | 13.7 % | -38.2 % | 0.000 | 0.000 | 76 | 15 | 80.3 % | 0.2 % | 0.5 % | 1.76 | Sharpe -1.93 vs BTC -0.49; late -2.33; band -38.2 %; DSR 0.000 |
| H:N55:D10:K20 | -0.53 | -3.5 % | 9.0 % | 54.01 | -1.02 | 18.1 % | -33.1 % | 0.000 | 0.001 | 141 | 20 | 85.8 % | 0.3 % | 0.7 % | 1.90 | Sharpe -0.53 vs BTC -0.49; late -1.02; band -33.1 %; DSR 0.000 |
| H:N55:D20:K5 | -1.64 | -4.6 % | 7.9 % | 53.10 | -1.72 | 16.8 % | -36.2 % | 0.000 | 0.001 | 34 | 7 | 79.4 % | 0.1 % | 0.4 % | 1.58 | Sharpe -1.64 vs BTC -0.49; late -1.72; band -36.2 %; DSR 0.000; 7 entries |
| H:N55:D20:K10 | -0.69 | -4.4 % | 10.7 % | 53.26 | -1.02 | 17.1 % | -34.5 % | 0.000 | 0.001 | 63 | 11 | 82.5 % | 0.2 % | 0.6 % | 1.50 | Sharpe -0.69 vs BTC -0.49; late -1.02; band -34.5 %; DSR 0.000 |
| H:N55:D20:K20 | -0.54 | -2.4 % | 7.1 % | 54.95 | -0.64 | 19.1 % | -33.7 % | 0.000 | 0.001 | 116 | 10 | 91.4 % | 0.1 % | 0.4 % | 0.86 | Sharpe -0.54 vs BTC -0.49; late -0.64; band -33.7 %; DSR 0.000 |

## Out of sample at 200 EUR (228 USD), on time

| rule | Sharpe | CAGR | max DD | end USD | late | excess | band | DSR | DSR excess | entries | sent | skipped | costs/yr | funding/yr | IS Sharpe | fails |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| breakout_top10 | 0.04 | -0.3 % | 15.5 % | 227.06 | -0.31 | 21.9 % | -27.4 % | 0.000 | 0.001 | 108 | 71 | 34.3 % | 0.4 % | 1.8 % | 1.16 | late -0.31; band -27.4 %; DSR 0.000 |
| breakout_btceth | 0.18 | 1.5 % | 15.1 % | 233.24 | 0.14 | 24.1 % | -26.8 % | 0.000 | 0.001 | 6 | 6 | 0.0 % | 0.2 % | 2.5 % | 0.87 | band -26.8 %; DSR 0.000; 6 entries |
| tsmom1 | 0.22 | 2.5 % | 12.4 % | 236.49 | 0.01 | 25.9 % | -24.6 % | 0.000 | 0.001 | 13 | 13 | 0.0 % | 0.8 % | 3.6 % | 1.59 | band -24.6 %; DSR 0.000 |
| tsmom_top20 | 0.95 | 2.3 % | 1.9 % | 235.90 | 0.28 | 23.8 % | -29.4 % | 0.006 | 0.001 | 269 | 20 | 92.6 % | 0.1 % | 0.4 % | 1.61 | band -29.4 %; DSR 0.006 |
| breakout_sol3 | 0.06 | -0.4 % | 21.8 % | 226.67 | -0.27 | 22.5 % | -23.7 % | 0.000 | 0.001 | 30 | 30 | 0.0 % | 0.5 % | 2.6 % | 1.13 | late -0.27; band -23.7 %; DSR 0.000 |
| breakout_sol10 | -0.29 | -2.1 % | 10.6 % | 220.98 | -0.80 | 19.6 % | -31.6 % | 0.000 | 0.001 | 61 | 37 | 39.3 % | 0.2 % | 0.8 % | 1.06 | late -0.80; band -31.6 %; DSR 0.000 |
| btc_gated | -0.52 | -17.0 % | 32.7 % | 172.50 | -0.51 | 6.8 % | -37.1 % | 0.000 | 0.000 | 9 | 9 | 0.0 % | 0.5 % | 5.5 % | 1.14 | Sharpe -0.52 vs BTC -0.49; late -0.51; band -37.1 %; DSR 0.000; 9 entries |
| memes_rotation | 0.73 | 15.3 % | 16.9 % | 282.05 | 0.45 | 38.3 % | -13.3 % | 0.001 | 0.003 | 21 | 21 | 0.0 % | 0.7 % | 2.2 % | 1.41 | band -13.3 %; DSR 0.001 |
| breakout_top10_ls | 0.38 | 3.9 % | 12.2 % | 241.50 | 0.04 | 26.0 % | -26.0 % | 0.001 | 0.001 | 190 | 81 | 57.4 % | 0.4 % | 1.8 % | 1.14 | band -26.0 %; DSR 0.001 |
| tsmom_top20_ls | 1.37 | 3.1 % | 1.4 % | 238.75 | 0.35 | 24.6 % | -29.1 % | 0.019 | 0.001 | 371 | 4 | 98.9 % | 0.1 % | 0.3 % | 1.33 | band -29.1 %; DSR 0.019; 4 entries |
| H:N10:D5:K5 | 0.37 | 3.8 % | 11.5 % | 241.14 | -0.51 | 26.0 % | -23.2 % | 0.000 | 0.001 | 135 | 133 | 1.5 % | 1.3 % | 1.7 % | 0.83 | late -0.51; band -23.2 %; DSR 0.000 |
| H:N10:D5:K10 | 0.44 | 3.4 % | 7.7 % | 239.68 | -0.16 | 25.1 % | -26.0 % | 0.001 | 0.001 | 268 | 175 | 34.7 % | 0.9 % | 1.1 % | 0.88 | late -0.16; band -26.0 %; DSR 0.001 |
| H:N10:D5:K20 | 0.81 | 1.1 % | 1.4 % | 231.77 | -1.08 | 22.6 % | -30.5 % | 0.003 | 0.001 | 533 | 43 | 91.9 % | 0.2 % | 0.2 % | 0.89 | late -1.08; band -30.5 %; DSR 0.003 |
| H:N10:D10:K5 | -0.58 | -9.1 % | 17.4 % | 197.58 | -0.99 | 13.0 % | -36.0 % | 0.000 | 0.000 | 120 | 117 | 2.5 % | 1.0 % | 1.9 % | 1.12 | Sharpe -0.58 vs BTC -0.49; late -0.99; band -36.0 %; DSR 0.000 |
| H:N10:D10:K10 | -0.23 | -2.6 % | 11.5 % | 219.11 | -0.59 | 19.3 % | -32.3 % | 0.000 | 0.001 | 237 | 143 | 39.7 % | 0.7 % | 1.3 % | 1.00 | late -0.59; band -32.3 %; DSR 0.000 |
| H:N10:D10:K20 | -0.81 | -1.3 % | 2.7 % | 223.60 | -1.19 | 20.2 % | -33.3 % | 0.000 | 0.001 | 491 | 33 | 93.3 % | 0.1 % | 0.2 % | 1.58 | Sharpe -0.81 vs BTC -0.49; late -1.19; band -33.3 %; DSR 0.000 |
| H:N10:D20:K5 | -0.28 | -5.5 % | 19.8 % | 209.40 | -0.64 | 17.0 % | -31.0 % | 0.000 | 0.001 | 117 | 114 | 2.6 % | 1.0 % | 2.4 % | 0.82 | late -0.64; band -31.0 %; DSR 0.000 |
| H:N10:D20:K10 | 0.24 | 2.1 % | 12.4 % | 235.21 | -0.33 | 24.1 % | -26.6 % | 0.000 | 0.001 | 228 | 143 | 37.3 % | 0.7 % | 1.7 % | 1.27 | late -0.33; band -26.6 %; DSR 0.000 |
| H:N10:D20:K20 | -0.32 | -0.6 % | 2.5 % | 226.12 | -1.05 | 20.9 % | -32.3 % | 0.000 | 0.001 | 471 | 32 | 93.2 % | 0.1 % | 0.3 % | 1.57 | late -1.05; band -32.3 %; DSR 0.000 |
| H:N20:D5:K5 | 0.68 | 6.6 % | 11.8 % | 250.79 | -0.17 | 28.3 % | -20.1 % | 0.002 | 0.002 | 81 | 80 | 1.2 % | 0.9 % | 1.3 % | 1.04 | late -0.17; band -20.1 %; DSR 0.002 |
| H:N20:D5:K10 | 0.73 | 5.0 % | 8.3 % | 245.38 | -0.29 | 26.6 % | -24.5 % | 0.002 | 0.001 | 156 | 111 | 28.8 % | 0.6 % | 0.9 % | 0.77 | late -0.29; band -24.5 %; DSR 0.002 |
| H:N20:D5:K20 | -0.13 | -0.2 % | 2.0 % | 227.37 | -1.29 | 21.3 % | -32.0 % | 0.000 | 0.001 | 313 | 33 | 89.5 % | 0.1 % | 0.2 % | 1.08 | late -1.29; band -32.0 %; DSR 0.000 |
| H:N20:D10:K5 | 0.21 | 1.8 % | 14.7 % | 234.23 | -0.37 | 24.0 % | -25.6 % | 0.000 | 0.001 | 67 | 66 | 1.5 % | 0.6 % | 1.7 % | 1.35 | late -0.37; band -25.6 %; DSR 0.000 |
| H:N20:D10:K10 | 0.57 | 4.8 % | 6.3 % | 244.42 | -0.03 | 26.5 % | -24.3 % | 0.001 | 0.001 | 131 | 90 | 31.3 % | 0.5 % | 1.2 % | 0.89 | late -0.03; band -24.3 %; DSR 0.001 |
| H:N20:D10:K20 | 0.32 | 0.6 % | 1.9 % | 230.14 | -0.39 | 22.1 % | -31.1 % | 0.001 | 0.001 | 268 | 25 | 90.7 % | 0.1 % | 0.2 % | 1.39 | late -0.39; band -31.1 %; DSR 0.001 |
| H:N20:D20:K5 | -0.31 | -5.7 % | 25.3 % | 208.87 | -0.58 | 16.8 % | -30.9 % | 0.000 | 0.001 | 60 | 59 | 1.7 % | 0.5 % | 2.3 % | 1.09 | late -0.58; band -30.9 %; DSR 0.000 |
| H:N20:D20:K10 | 0.18 | 1.4 % | 16.5 % | 232.83 | -0.30 | 23.5 % | -26.8 % | 0.000 | 0.001 | 116 | 79 | 31.9 % | 0.4 % | 1.6 % | 0.95 | late -0.30; band -26.8 %; DSR 0.000 |
| H:N20:D20:K20 | -0.23 | -0.4 % | 2.4 % | 226.65 | -0.82 | 21.1 % | -32.1 % | 0.000 | 0.001 | 238 | 19 | 92.0 % | 0.1 % | 0.2 % | 1.62 | late -0.82; band -32.1 %; DSR 0.000 |
| H:N55:D5:K5 | -0.02 | -0.4 % | 8.5 % | 226.71 | -0.50 | 21.3 % | -30.3 % | 0.000 | 0.001 | 45 | 44 | 2.2 % | 0.4 % | 0.9 % | 1.55 | late -0.50; band -30.3 %; DSR 0.000 |
| H:N55:D5:K10 | 0.14 | 0.5 % | 4.7 % | 229.85 | -0.65 | 22.1 % | -30.6 % | 0.000 | 0.001 | 82 | 54 | 34.1 % | 0.3 % | 0.6 % | 1.13 | late -0.65; band -30.6 %; DSR 0.000 |
| H:N55:D5:K20 | -0.85 | -0.9 % | 2.1 % | 224.77 | -1.78 | 20.5 % | -32.9 % | 0.000 | 0.001 | 157 | 22 | 86.0 % | 0.1 % | 0.1 % | 1.35 | Sharpe -0.85 vs BTC -0.49; late -1.78; band -32.9 %; DSR 0.000 |
| H:N55:D10:K5 | -0.54 | -5.4 % | 16.9 % | 209.70 | -0.94 | 16.3 % | -34.1 % | 0.000 | 0.001 | 40 | 39 | 2.5 % | 0.4 % | 1.3 % | 1.31 | Sharpe -0.54 vs BTC -0.49; late -0.94; band -34.1 %; DSR 0.000 |
| H:N55:D10:K10 | -0.29 | -2.1 % | 8.5 % | 220.93 | -0.62 | 19.6 % | -32.1 % | 0.000 | 0.001 | 76 | 48 | 36.8 % | 0.3 % | 0.8 % | 1.17 | late -0.62; band -32.1 %; DSR 0.000 |
| H:N55:D10:K20 | -0.60 | -1.0 % | 2.5 % | 224.52 | -1.33 | 20.4 % | -32.8 % | 0.000 | 0.001 | 141 | 20 | 85.8 % | 0.1 % | 0.2 % | 1.67 | Sharpe -0.60 vs BTC -0.49; late -1.33; band -32.8 %; DSR 0.000 |
| H:N55:D20:K5 | -1.15 | -13.6 % | 24.3 % | 183.22 | -1.19 | 7.6 % | -41.5 % | 0.000 | 0.000 | 34 | 33 | 2.9 % | 0.3 % | 1.7 % | 1.29 | Sharpe -1.15 vs BTC -0.49; late -1.19; band -41.5 %; DSR 0.000 |
| H:N55:D20:K10 | -0.52 | -4.8 % | 13.8 % | 211.85 | -0.69 | 16.9 % | -34.0 % | 0.000 | 0.001 | 63 | 41 | 34.9 % | 0.2 % | 1.2 % | 1.38 | Sharpe -0.52 vs BTC -0.49; late -0.69; band -34.0 %; DSR 0.000 |
| H:N55:D20:K20 | -0.80 | -1.2 % | 3.2 % | 223.93 | -1.03 | 20.3 % | -33.2 % | 0.000 | 0.001 | 116 | 14 | 87.9 % | 0.1 % | 0.2 % | 1.49 | Sharpe -0.80 vs BTC -0.49; late -1.03; band -33.2 %; DSR 0.000 |

## The ideal account (any size, no minimum, no position cap): the rules themselves, end as a multiple of the start

| rule | Sharpe | CAGR | max DD | end USD | late | excess | band | DSR | DSR excess | entries | sent | skipped | costs/yr | funding/yr | IS Sharpe | fails |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| breakout_top10 | -0.23 | -4.3 % | 19.6 % | 0.94 | -0.57 | 18.1 % | -30.4 % | 0.000 | 0.001 | 108 | 108 | 0.0 % | 0.4 % | 2.1 % | 1.00 | reference, not judged |
| breakout_btceth | 0.18 | 1.5 % | 15.1 % | 1.02 | 0.14 | 24.1 % | -26.8 % | 0.000 | 0.001 | 6 | 6 | 0.0 % | 0.2 % | 2.5 % | 0.87 | reference, not judged |
| tsmom1 | 0.20 | 2.0 % | 12.6 % | 1.03 | 0.03 | 25.5 % | -25.2 % | 0.000 | 0.001 | 13 | 13 | 0.0 % | 0.8 % | 3.6 % | 1.58 | reference, not judged |
| tsmom_top20 | 0.08 | 0.2 % | 10.0 % | 1.00 | 0.01 | 22.5 % | -28.8 % | 0.000 | 0.001 | 269 | 269 | 0.0 % | 0.6 % | 1.6 % | 0.58 | reference, not judged |
| breakout_sol3 | 0.06 | -0.4 % | 21.8 % | 0.99 | -0.27 | 22.5 % | -23.7 % | 0.000 | 0.001 | 30 | 30 | 0.0 % | 0.5 % | 2.6 % | 1.13 | reference, not judged |
| breakout_sol10 | -0.09 | -1.4 % | 16.0 % | 0.98 | -0.61 | 20.6 % | -29.1 % | 0.000 | 0.001 | 61 | 61 | 0.0 % | 0.3 % | 1.2 % | 0.98 | reference, not judged |
| btc_gated | -0.52 | -17.0 % | 32.7 % | 0.76 | -0.51 | 6.8 % | -37.1 % | 0.000 | 0.000 | 9 | 9 | 0.0 % | 0.5 % | 5.5 % | 1.14 | reference, not judged |
| memes_rotation | 0.72 | 15.1 % | 16.8 % | 1.23 | 0.43 | 38.2 % | -13.2 % | 0.001 | 0.003 | 21 | 21 | 0.0 % | 0.8 % | 2.2 % | 1.44 | reference, not judged |
| breakout_top10_ls | 0.08 | 0.0 % | 14.5 % | 1.00 | -0.22 | 22.8 % | -33.8 % | 0.000 | 0.001 | 190 | 190 | 0.0 % | 0.6 % | 2.0 % | 1.02 | reference, not judged |
| tsmom_top20_ls | 0.60 | 8.3 % | 11.5 % | 1.13 | 0.55 | 30.6 % | -31.1 % | 0.001 | 0.001 | 371 | 371 | 0.0 % | 1.2 % | 1.3 % | 0.61 | reference, not judged |
| H:N10:D5:K5 | 0.34 | 3.5 % | 12.0 % | 1.05 | -0.60 | 25.6 % | -23.4 % | 0.000 | 0.001 | 135 | 135 | 0.0 % | 1.3 % | 1.7 % | 0.85 | reference, not judged |
| H:N10:D5:K10 | -0.15 | -2.2 % | 10.2 % | 0.97 | -0.57 | 19.8 % | -29.4 % | 0.000 | 0.001 | 268 | 268 | 0.0 % | 1.1 % | 1.3 % | 0.83 | reference, not judged |
| H:N10:D5:K20 | -0.58 | -6.1 % | 13.4 % | 0.91 | -0.82 | 15.6 % | -34.2 % | 0.000 | 0.000 | 533 | 533 | 0.0 % | 1.0 % | 0.9 % | 0.64 | reference, not judged |
| H:N10:D10:K5 | -0.64 | -10.0 % | 18.2 % | 0.85 | -1.07 | 12.0 % | -36.8 % | 0.000 | 0.000 | 120 | 120 | 0.0 % | 1.0 % | 1.9 % | 1.16 | reference, not judged |
| H:N10:D10:K10 | -0.53 | -7.4 % | 13.7 % | 0.89 | -0.74 | 14.6 % | -34.1 % | 0.000 | 0.000 | 237 | 237 | 0.0 % | 0.9 % | 1.6 % | 0.83 | reference, not judged |
| H:N10:D10:K20 | -1.20 | -14.3 % | 21.4 % | 0.79 | -1.19 | 6.8 % | -42.1 % | 0.000 | 0.000 | 491 | 491 | 0.0 % | 0.8 % | 1.2 % | 0.68 | reference, not judged |
| H:N10:D20:K5 | -0.34 | -6.4 % | 20.9 % | 0.91 | -0.72 | 16.1 % | -31.5 % | 0.000 | 0.001 | 117 | 117 | 0.0 % | 1.0 % | 2.4 % | 0.86 | reference, not judged |
| H:N10:D20:K10 | -0.28 | -4.9 % | 16.4 % | 0.93 | -0.46 | 17.5 % | -31.0 % | 0.000 | 0.001 | 228 | 228 | 0.0 % | 0.9 % | 2.0 % | 1.02 | reference, not judged |
| H:N10:D20:K20 | -0.92 | -12.1 % | 21.2 % | 0.82 | -0.94 | 9.4 % | -39.9 % | 0.000 | 0.000 | 471 | 471 | 0.0 % | 0.8 % | 1.5 % | 0.67 | reference, not judged |
| H:N20:D5:K5 | 0.67 | 6.5 % | 11.9 % | 1.10 | -0.22 | 28.3 % | -19.9 % | 0.002 | 0.002 | 81 | 81 | 0.0 % | 0.9 % | 1.3 % | 1.08 | reference, not judged |
| H:N20:D5:K10 | 0.44 | 3.4 % | 8.9 % | 1.05 | -0.38 | 25.1 % | -23.5 % | 0.001 | 0.001 | 156 | 156 | 0.0 % | 0.7 % | 1.0 % | 0.70 | reference, not judged |
| H:N20:D5:K20 | 0.02 | -0.1 % | 11.1 % | 1.00 | -0.88 | 21.6 % | -27.8 % | 0.000 | 0.001 | 313 | 313 | 0.0 % | 0.7 % | 0.7 % | 0.50 | reference, not judged |
| H:N20:D10:K5 | 0.16 | 1.3 % | 15.4 % | 1.02 | -0.41 | 23.5 % | -25.8 % | 0.000 | 0.001 | 67 | 67 | 0.0 % | 0.6 % | 1.7 % | 1.45 | reference, not judged |
| H:N20:D10:K10 | 0.31 | 2.7 % | 8.7 % | 1.04 | -0.23 | 24.7 % | -25.0 % | 0.000 | 0.001 | 131 | 131 | 0.0 % | 0.6 % | 1.4 % | 0.90 | reference, not judged |
| H:N20:D10:K20 | -0.33 | -3.5 % | 13.4 % | 0.95 | -0.86 | 18.3 % | -32.0 % | 0.000 | 0.001 | 268 | 268 | 0.0 % | 0.5 % | 0.8 % | 0.63 | reference, not judged |
| H:N20:D20:K5 | -0.34 | -6.2 % | 25.9 % | 0.91 | -0.62 | 16.2 % | -31.5 % | 0.000 | 0.001 | 60 | 60 | 0.0 % | 0.5 % | 2.2 % | 1.14 | reference, not judged |
| H:N20:D20:K10 | -0.03 | -1.3 % | 19.2 % | 0.98 | -0.51 | 21.1 % | -28.2 % | 0.000 | 0.001 | 116 | 116 | 0.0 % | 0.5 % | 1.9 % | 0.93 | reference, not judged |
| H:N20:D20:K20 | -0.36 | -5.0 % | 20.6 % | 0.93 | -0.89 | 17.0 % | -33.0 % | 0.000 | 0.001 | 238 | 238 | 0.0 % | 0.5 % | 1.3 % | 0.76 | reference, not judged |
| H:N55:D5:K5 | -0.02 | -0.4 % | 8.6 % | 0.99 | -0.57 | 21.3 % | -30.3 % | 0.000 | 0.001 | 45 | 45 | 0.0 % | 0.4 % | 0.9 % | 1.59 | reference, not judged |
| H:N55:D5:K10 | -0.07 | -0.5 % | 5.8 % | 0.99 | -0.74 | 21.1 % | -30.8 % | 0.000 | 0.001 | 82 | 82 | 0.0 % | 0.3 % | 0.7 % | 1.23 | reference, not judged |
| H:N55:D5:K20 | -0.13 | -0.8 % | 7.2 % | 0.99 | -0.81 | 20.8 % | -31.2 % | 0.000 | 0.001 | 157 | 157 | 0.0 % | 0.3 % | 0.4 % | 0.91 | reference, not judged |
| H:N55:D10:K5 | -0.60 | -6.0 % | 17.6 % | 0.91 | -1.00 | 15.8 % | -34.7 % | 0.000 | 0.000 | 40 | 40 | 0.0 % | 0.4 % | 1.3 % | 1.43 | reference, not judged |
| H:N55:D10:K10 | -0.63 | -5.3 % | 11.7 % | 0.92 | -0.91 | 16.3 % | -35.1 % | 0.000 | 0.001 | 76 | 76 | 0.0 % | 0.3 % | 1.0 % | 1.09 | reference, not judged |
| H:N55:D10:K20 | -0.57 | -4.3 % | 10.6 % | 0.94 | -0.78 | 17.4 % | -34.6 % | 0.000 | 0.001 | 141 | 141 | 0.0 % | 0.3 % | 0.6 % | 1.03 | reference, not judged |
| H:N55:D20:K5 | -1.22 | -14.3 % | 25.2 % | 0.79 | -1.28 | 6.7 % | -42.3 % | 0.000 | 0.000 | 34 | 34 | 0.0 % | 0.3 % | 1.7 % | 1.37 | reference, not judged |
| H:N55:D20:K10 | -0.69 | -7.8 % | 15.0 % | 0.89 | -0.84 | 13.9 % | -37.1 % | 0.000 | 0.000 | 63 | 63 | 0.0 % | 0.3 % | 1.4 % | 1.21 | reference, not judged |
| H:N55:D20:K20 | -0.53 | -5.6 % | 14.8 % | 0.92 | -0.71 | 16.2 % | -35.4 % | 0.000 | 0.001 | 116 | 116 | 0.0 % | 0.2 % | 0.9 % | 0.96 | reference, not judged |

## The universe (DT1's rule), coins a day per quarter

| quarter | 50 M mean | 50 M max | on Hyperliquid mean | on Hyperliquid max |
|---|---|---|---|---|
| 2022Q1 | 64.3 | 78 | 0.0 | 0 |
| 2022Q2 | 70.8 | 83 | 0.0 | 0 |
| 2022Q3 | 55.7 | 67 | 0.0 | 0 |
| 2022Q4 | 48.6 | 59 | 0.0 | 0 |
| 2023Q1 | 57.1 | 75 | 0.0 | 0 |
| 2023Q2 | 54.5 | 61 | 9.0 | 18 |
| 2023Q3 | 55.7 | 63 | 25.1 | 29 |
| 2023Q4 | 61.9 | 81 | 39.6 | 48 |
| 2024Q1 | 83.3 | 113 | 52.7 | 60 |
| 2024Q2 | 80.6 | 113 | 53.7 | 59 |
| 2024Q3 | 60.8 | 67 | 50.5 | 54 |
| 2024Q4 | 86.4 | 119 | 69.6 | 89 |
| 2025Q1 | 77.8 | 113 | 65.0 | 83 |
| 2025Q2 | 64.3 | 69 | 55.1 | 61 |
| 2025Q3 | 70.6 | 76 | 62.4 | 70 |
| 2025Q4 | 66.0 | 77 | 57.4 | 66 |
| 2026Q1 | 50.9 | 59 | 42.3 | 49 |
| 2026Q2 | 51.5 | 60 | 35.2 | 42 |

## Checks

- 1-hour bars against the daily klines: 184906 coin-days, close within 0.1 % on 100.0 %, quote volume on 99.9 %.
- Funding out of sample on the judged universe: Hyperliquid's hourly rates on 100.0 % of the coin-days the rules held (ideal account), Binance's on the rest.
