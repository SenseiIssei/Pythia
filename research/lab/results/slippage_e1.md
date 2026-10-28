# E1: slippage bounds for pump.fun buys and sales, on realistic paper

Pre-registration `results/slippage_e1_prereg.md`. Code `lab/pumpfun_rt/slippage_e1.py`, the hooks in `realistic.RealExecutor`. Replay of the record 2026-10-20 to 2026-10-28 (2026-10-20 16:39 to 2026-10-28 20:55 UTC) through `sim`; the fit: buy 6.2 s, sale 0.6 s median, fee 0.000209 + tip 0.000005 SOL, 147 live buys. C books: 0.1 SOL on every signal; P&L per signal in points of the stake (closed trades and failed buys' fees over all signals); returns after every fee. Bands: 95 % percentile bootstrap, 2,000 draws, seed 0, coins drawn. 60 trials in R5's registry, counted only (`hand:e1:*`); no Sharpe, no DSR. Paper only: the live bounds are the owner's and nothing here changes them.

## The answer

- P_pool0_wait, none view, buy bound: best b05, +1.17 points per signal against b60 (band +0.48 to +1.85): **propose b05**.
- P_pool0_wait, none view, sale bound: best b60: **keep the live bound**.
- P_pool0_wait, sandwich view, buy bound: best b05, +1.33 points per signal against b60 (band +0.62 to +2.04): **propose b05**.
- P_pool0_wait, sandwich view, sale bound: best s05, +0.11 points per signal against b60 (band -0.32 to +0.49): **keep the live bound**.

## What it says

- **The buy bound is the lever, the sale bound is not.** On P_pool0_wait (the live rule) every buy bound from 0.02 to
  0.30 beats the live 0.60 per signal, in both views; b05 is the best (+1.17 points per signal without sandwiches,
  +1.33 with, both bands above 0), which by the pre-registered rule is the proposal. b02, b05 and b10 share the
  day-by-day wins (3, 2 and 3 of 9 days); 0.60 wins no day. P_pool0 points the same way (b02 +0.84, b05 +0.56 points,
  bands across 0), P_cmig_model's curve cap too (b02 +1.16, band +0.68 to +1.59). Loosening to 1.00 changes nothing.
- **Why: what the tight bound refuses loses money.** At 0.60 a quarter of the pool buys (25 %) fill more than 2 % worse
  than the signal's quote: the price ran in the 6 s to the landing and the bot bought after the run. At 0.05 the
  share is 10.5 % and those buys fail instead: 88 6040s (0.022 SOL in fees) and 290 pre-send skips (no fee) against
  2 and 37 at 0.60. Fees for the failures are tiny next to what the refused late buys lose; the mean a trade goes
  from +5.0 % to +7.6 %.
- **Sale bounds only cost.** s05, s15 and s30 add 29 to 280 failed sales on P_pool0_wait (each pays its fee and waits
  the backoff); none beats the live sales with a band above 0 (s05 +0.11, band -0.32 to +0.49, in the sandwich view;
  negative without). Keep the live sales (protective exits without a floor).
- **Sandwiches at 0.1 SOL barely happen.** With the coin's own fee (about 1.25 % a side early, 0.3 % on older pools) a
  sandwich pays only once the order is a sizeable share of the pool: 2 buys and 8 sales of 1,978 at b60. With the
  live sizing (W books: the owner's 50 % share, no ceiling in paper, wallets growing to several SOL) the sandwich view
  takes most of the paper profit (P_pool0_wait b60 +6.7 SOL to +1.0 SOL), and there a tight buy bound and a sale
  bound help (b02 +1.8, s05 +1.8 SOL). The W counts are not broken down by sandwich in this run; the reading is that
  stakes far above the live cap (0.25 SOL a trade) are what a sandwich eats. The W books trade one coin at a time,
  so their order of coins differs by bound and their single numbers are noisy (no band).
- **P2's gap hardly moves with the bound**: paper minus live on the live signals +3.0 points at b60, +2.5 at b05,
  bands of about +-8 points on 149 live trades (the realistic engine over the whole record; P2's +18.9 used the
  shadow ledger with the ideal model before 2026-10-24).
- **Caveats.** One replay of 9 days, the fit of the last 7 days' live orders (buy 6.2 s median) on all of them;
  P_cmig_model's model filter uses today's model files (in sample, the same for every bound). The sandwich view is
  the worst case for an attacker who pays fees, not a measured rate. 60 trials counted.

## Proposal for the live bounds (the owner decides; nothing here changes them)

- Pool buys: `PYTHIA_PUMPFUN_BUY_TOL=0.05` instead of 0.60 (any value from 0.02 to 0.10 is about as good; tighter
  than 0.02 was not tried). Expect about one signal in five to fail or be skipped instead of one in 27 (6040s and
  pre-send skips 378 against 39 of 1,978), 0.0002 SOL a 6040, nothing for a skip.
- Sales: no change. Curve buys: the curve cap (SLIP_TOL 0.30) would gain from 0.02 to 0.05 as well, but it is not an
  owner setting; it needs a code change in the live executor and its own review.
- Before a restart: the forward books `P_pool0_wait@e1_<pair>` in the shadow (realistic.md, daily) should show the
  same order over at least 7 days.

## Every rule pooled

### none

| pair | buy bound | sale bound | signals | trades | 6040 (fees SOL) | pre-send skips | other buy failures (fees SOL) | failed sales (fees SOL) | given up | mean a trade | median | P&L per signal, points | worse than the signal by > 2 % | sandwiched buys / sales (SOL) | vs b60, points per signal (band) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| b02 | 0.02 | live | 8923 | 6379 | 267 (0.0665) | 829 | 1448 (0.2717) | 7 (0.0015) | 0 | -0.2 % | -3.5 % | -0.17 | +0.0 % | 0 / 0 (0.0000) | +1.05 (+0.63 to +1.46) |
| b05 | 0.05 | live | 8923 | 7092 | 159 (0.0396) | 532 | 1140 (0.2073) | 9 (0.0019) | 0 | -0.5 % | -3.5 % | -0.40 | +9.0 % | 0 / 0 (0.0000) | +0.83 (+0.50 to +1.14) |
| b10 | 0.1 | live | 8923 | 7578 | 91 (0.0227) | 339 | 915 (0.1603) | 9 (0.0019) | 0 | -0.8 % | -3.5 % | -0.68 | +14.6 % | 0 / 0 (0.0000) | +0.55 (+0.28 to +0.81) |
| b20 | 0.2 | live | 8923 | 8051 | 35 (0.0087) | 195 | 642 (0.1032) | 9 (0.0019) | 0 | -1.0 % | -3.6 % | -0.92 | +19.5 % | 0 / 0 (0.0000) | +0.30 (+0.18 to +0.42) |
| b30 | 0.3 | live | 8923 | 8235 | 24 (0.0060) | 136 | 528 (0.0794) | 9 (0.0019) | 0 | -1.2 % | -3.8 % | -1.16 | +21.2 % | 0 / 0 (0.0000) | +0.06 (-0.00 to +0.13) |
| **b60** | 0.6 | live | 8923 | 8311 | 9 (0.0022) | 75 | 528 (0.0794) | 9 (0.0019) | 0 | -1.3 % | -3.8 % | -1.22 | +21.9 % | 0 / 0 (0.0000) | reference |
| b100 | 1 | live | 8923 | 8326 | 7 (0.0017) | 62 | 528 (0.0794) | 9 (0.0019) | 0 | -1.3 % | -3.8 % | -1.22 | +22.1 % | 0 / 0 (0.0000) | +0.01 (-0.04 to +0.05) |
| s05 | 0.6 | 0.05 | 8923 | 8311 | 9 (0.0022) | 75 | 528 (0.0794) | 2020 (0.4221) | 3 | -1.5 % | -3.8 % | -1.37 | +21.9 % | 0 / 0 (0.0000) | -0.15 (-0.30 to -0.00) |
| s15 | 0.6 | 0.15 | 8923 | 8311 | 9 (0.0022) | 75 | 528 (0.0794) | 722 (0.1509) | 0 | -1.3 % | -3.8 % | -1.26 | +21.9 % | 0 / 0 (0.0000) | -0.04 (-0.13 to +0.05) |
| s30 | 0.6 | 0.3 | 8923 | 8311 | 9 (0.0022) | 75 | 528 (0.0794) | 322 (0.0673) | 0 | -1.3 % | -3.8 % | -1.25 | +21.9 % | 0 / 0 (0.0000) | -0.03 (-0.07 to +0.01) |

### sandwich

| pair | buy bound | sale bound | signals | trades | 6040 (fees SOL) | pre-send skips | other buy failures (fees SOL) | failed sales (fees SOL) | given up | mean a trade | median | P&L per signal, points | worse than the signal by > 2 % | sandwiched buys / sales (SOL) | vs b60, points per signal (band) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| b02 | 0.02 | live | 8923 | 6379 | 267 (0.0665) | 829 | 1448 (0.2717) | 7 (0.0015) | 0 | -0.2 % | -3.5 % | -0.20 | +0.0 % | 0 / 4 (0.2944) | +1.11 (+0.70 to +1.51) |
| b05 | 0.05 | live | 8923 | 7092 | 159 (0.0396) | 532 | 1140 (0.2073) | 9 (0.0019) | 0 | -0.5 % | -3.5 % | -0.44 | +9.0 % | 0 / 5 (0.3829) | +0.87 (+0.54 to +1.19) |
| b10 | 0.1 | live | 8923 | 7578 | 91 (0.0227) | 339 | 915 (0.1603) | 9 (0.0019) | 0 | -0.8 % | -3.5 % | -0.72 | +14.6 % | 1 / 5 (0.3838) | +0.59 (+0.32 to +0.85) |
| b20 | 0.2 | live | 8923 | 8051 | 35 (0.0087) | 195 | 642 (0.1032) | 9 (0.0019) | 0 | -1.1 % | -3.7 % | -0.99 | +19.5 % | 1 / 8 (0.6272) | +0.32 (+0.20 to +0.44) |
| b30 | 0.3 | live | 8923 | 8235 | 24 (0.0060) | 136 | 528 (0.0794) | 9 (0.0019) | 0 | -1.3 % | -3.8 % | -1.24 | +21.2 % | 2 / 9 (0.7164) | +0.07 (+0.01 to +0.14) |
| **b60** | 0.6 | live | 8923 | 8311 | 9 (0.0022) | 75 | 528 (0.0794) | 9 (0.0019) | 0 | -1.4 % | -3.8 % | -1.31 | +21.9 % | 2 / 11 (0.8341) | reference |
| b100 | 1 | live | 8923 | 8326 | 7 (0.0017) | 62 | 528 (0.0794) | 9 (0.0019) | 0 | -1.4 % | -3.8 % | -1.32 | +22.1 % | 2 / 13 (0.9892) | -0.01 (-0.06 to +0.03) |
| s05 | 0.6 | 0.05 | 8923 | 8311 | 9 (0.0022) | 75 | 528 (0.0794) | 2020 (0.4221) | 3 | -1.5 % | -3.8 % | -1.39 | +21.9 % | 2 / 11 (0.1899) | -0.08 (-0.23 to +0.08) |
| s15 | 0.6 | 0.15 | 8923 | 8311 | 9 (0.0022) | 75 | 528 (0.0794) | 722 (0.1509) | 0 | -1.4 % | -3.8 % | -1.29 | +21.9 % | 2 / 11 (0.2953) | +0.02 (-0.08 to +0.12) |
| s30 | 0.6 | 0.3 | 8923 | 8311 | 9 (0.0022) | 75 | 528 (0.0794) | 322 (0.0673) | 0 | -1.4 % | -3.8 % | -1.29 | +21.9 % | 2 / 11 (0.4238) | +0.02 (-0.03 to +0.07) |

## P_pool0

### none

| pair | buy bound | sale bound | signals | trades | 6040 (fees SOL) | pre-send skips | other buy failures (fees SOL) | failed sales (fees SOL) | given up | mean a trade | median | P&L per signal, points | worse than the signal by > 2 % | sandwiched buys / sales (SOL) | vs b60, points per signal (band) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| b02 | 0.02 | live | 1749 | 1205 | 124 (0.0309) | 389 | 31 (0.0000) | 0 (0.0000) | 0 | +10.4 % | +10.2 % | +7.17 | +0.0 % | 0 / 0 (0.0000) | +0.84 (-0.21 to +1.88) |
| b05 | 0.05 | live | 1749 | 1405 | 71 (0.0177) | 242 | 31 (0.0000) | 0 (0.0000) | 0 | +8.6 % | +11.0 % | +6.88 | +11.8 % | 0 / 0 (0.0000) | +0.56 (-0.32 to +1.35) |
| b10 | 0.1 | live | 1749 | 1516 | 43 (0.0107) | 159 | 31 (0.0000) | 0 (0.0000) | 0 | +7.4 % | +10.7 % | +6.45 | +17.9 % | 0 / 0 (0.0000) | +0.12 (-0.63 to +0.76) |
| b20 | 0.2 | live | 1749 | 1614 | 17 (0.0042) | 87 | 31 (0.0000) | 0 (0.0000) | 0 | +7.0 % | +9.2 % | +6.42 | +22.6 % | 0 / 0 (0.0000) | +0.09 (-0.23 to +0.41) |
| b30 | 0.3 | live | 1749 | 1641 | 13 (0.0032) | 64 | 31 (0.0000) | 0 (0.0000) | 0 | +6.8 % | +8.2 % | +6.35 | +23.8 % | 0 / 0 (0.0000) | +0.02 (-0.23 to +0.25) |
| **b60** | 0.6 | live | 1749 | 1673 | 7 (0.0017) | 38 | 31 (0.0000) | 0 (0.0000) | 0 | +6.6 % | +6.8 % | +6.33 | +25.2 % | 0 / 0 (0.0000) | reference |
| b100 | 1 | live | 1749 | 1680 | 5 (0.0012) | 33 | 31 (0.0000) | 0 (0.0000) | 0 | +6.6 % | +6.6 % | +6.30 | +25.5 % | 0 / 0 (0.0000) | -0.03 (-0.19 to +0.11) |
| s05 | 0.6 | 0.05 | 1749 | 1673 | 7 (0.0017) | 38 | 31 (0.0000) | 236 (0.0493) | 0 | +6.8 % | +6.0 % | +6.48 | +25.2 % | 0 / 0 (0.0000) | +0.16 (-0.21 to +0.51) |
| s15 | 0.6 | 0.15 | 1749 | 1673 | 7 (0.0017) | 38 | 31 (0.0000) | 56 (0.0117) | 0 | +6.7 % | +6.9 % | +6.39 | +25.2 % | 0 / 0 (0.0000) | +0.06 (-0.17 to +0.32) |
| s30 | 0.6 | 0.3 | 1749 | 1673 | 7 (0.0017) | 38 | 31 (0.0000) | 29 (0.0061) | 0 | +6.5 % | +6.9 % | +6.26 | +25.2 % | 0 / 0 (0.0000) | -0.07 (-0.19 to +0.03) |

Best buy bound by day (days won): b05 4, b02 2, b60 1, b20 1, b10 1.

### sandwich

| pair | buy bound | sale bound | signals | trades | 6040 (fees SOL) | pre-send skips | other buy failures (fees SOL) | failed sales (fees SOL) | given up | mean a trade | median | P&L per signal, points | worse than the signal by > 2 % | sandwiched buys / sales (SOL) | vs b60, points per signal (band) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| b02 | 0.02 | live | 1749 | 1205 | 124 (0.0309) | 389 | 31 (0.0000) | 0 (0.0000) | 0 | +10.3 % | +9.9 % | +7.08 | +0.0 % | 0 / 2 (0.1496) | +0.89 (-0.16 to +1.92) |
| b05 | 0.05 | live | 1749 | 1405 | 71 (0.0177) | 242 | 31 (0.0000) | 0 (0.0000) | 0 | +8.5 % | +11.0 % | +6.80 | +11.8 % | 0 / 2 (0.1496) | +0.61 (-0.29 to +1.41) |
| b10 | 0.1 | live | 1749 | 1516 | 43 (0.0107) | 159 | 31 (0.0000) | 0 (0.0000) | 0 | +7.3 % | +10.7 % | +6.36 | +17.9 % | 0 / 2 (0.1496) | +0.17 (-0.58 to +0.82) |
| b20 | 0.2 | live | 1749 | 1614 | 17 (0.0042) | 87 | 31 (0.0000) | 0 (0.0000) | 0 | +6.8 % | +8.6 % | +6.28 | +22.6 % | 0 / 3 (0.2420) | +0.09 (-0.23 to +0.41) |
| b30 | 0.3 | live | 1749 | 1641 | 13 (0.0032) | 64 | 31 (0.0000) | 0 (0.0000) | 0 | +6.6 % | +7.9 % | +6.21 | +23.8 % | 0 / 3 (0.2420) | +0.02 (-0.23 to +0.25) |
| **b60** | 0.6 | live | 1749 | 1673 | 7 (0.0017) | 38 | 31 (0.0000) | 0 (0.0000) | 0 | +6.5 % | +6.5 % | +6.19 | +25.2 % | 0 / 3 (0.2420) | reference |
| b100 | 1 | live | 1749 | 1680 | 5 (0.0012) | 33 | 31 (0.0000) | 0 (0.0000) | 0 | +6.4 % | +6.4 % | +6.16 | +25.5 % | 0 / 3 (0.2420) | -0.03 (-0.19 to +0.11) |
| s05 | 0.6 | 0.05 | 1749 | 1673 | 7 (0.0017) | 38 | 31 (0.0000) | 236 (0.0493) | 0 | +6.7 % | +6.0 % | +6.45 | +25.2 % | 0 / 4 (0.0546) | +0.26 (-0.11 to +0.65) |
| s15 | 0.6 | 0.15 | 1749 | 1673 | 7 (0.0017) | 38 | 31 (0.0000) | 56 (0.0117) | 0 | +6.6 % | +6.9 % | +6.34 | +25.2 % | 0 / 3 (0.0831) | +0.15 (-0.10 to +0.43) |
| s30 | 0.6 | 0.3 | 1749 | 1673 | 7 (0.0017) | 38 | 31 (0.0000) | 29 (0.0061) | 0 | +6.5 % | +6.6 % | +6.19 | +25.2 % | 0 / 3 (0.1190) | +0.00 (-0.13 to +0.14) |

Best buy bound by day (days won): b05 4, b02 2, b60 1, b20 1, b10 1.

## P_pool0_wait

### none

| pair | buy bound | sale bound | signals | trades | 6040 (fees SOL) | pre-send skips | other buy failures (fees SOL) | failed sales (fees SOL) | given up | mean a trade | median | P&L per signal, points | worse than the signal by > 2 % | sandwiched buys / sales (SOL) | vs b60, points per signal (band) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| b02 | 0.02 | live | 1978 | 1361 | 143 (0.0356) | 440 | 34 (0.0000) | 0 (0.0000) | 0 | +8.4 % | +7.7 % | +5.77 | +0.0 % | 0 / 0 (0.0000) | +0.96 (-0.22 to +1.96) |
| b05 | 0.05 | live | 1978 | 1566 | 88 (0.0219) | 290 | 34 (0.0000) | 0 (0.0000) | 0 | +7.6 % | +9.9 % | +5.98 | +10.5 % | 0 / 0 (0.0000) | +1.17 (+0.48 to +1.85) |
| b10 | 0.1 | live | 1978 | 1716 | 48 (0.0120) | 180 | 34 (0.0000) | 0 (0.0000) | 0 | +6.5 % | +6.6 % | +5.63 | +17.4 % | 0 / 0 (0.0000) | +0.82 (+0.35 to +1.29) |
| b20 | 0.2 | live | 1978 | 1818 | 18 (0.0045) | 108 | 34 (0.0000) | 0 (0.0000) | 0 | +5.8 % | +5.7 % | +5.35 | +21.9 % | 0 / 0 (0.0000) | +0.54 (+0.23 to +0.85) |
| b30 | 0.3 | live | 1978 | 1861 | 11 (0.0027) | 72 | 34 (0.0000) | 0 (0.0000) | 0 | +5.4 % | +4.7 % | +5.08 | +23.5 % | 0 / 0 (0.0000) | +0.27 (+0.08 to +0.47) |
| **b60** | 0.6 | live | 1978 | 1905 | 2 (0.0005) | 37 | 34 (0.0000) | 0 (0.0000) | 0 | +5.0 % | +3.4 % | +4.81 | +25.2 % | 0 / 0 (0.0000) | reference |
| b100 | 1 | live | 1978 | 1913 | 2 (0.0005) | 29 | 34 (0.0000) | 0 (0.0000) | 0 | +5.0 % | +3.4 % | +4.86 | +25.5 % | 0 / 0 (0.0000) | +0.05 (-0.10 to +0.20) |
| s05 | 0.6 | 0.05 | 1978 | 1905 | 2 (0.0005) | 37 | 34 (0.0000) | 280 (0.0585) | 1 | +4.9 % | +2.0 % | +4.69 | +25.2 % | 0 / 0 (0.0000) | -0.12 (-0.50 to +0.23) |
| s15 | 0.6 | 0.15 | 1978 | 1905 | 2 (0.0005) | 37 | 34 (0.0000) | 73 (0.0153) | 0 | +4.9 % | +2.9 % | +4.71 | +25.2 % | 0 / 0 (0.0000) | -0.10 (-0.32 to +0.12) |
| s30 | 0.6 | 0.3 | 1978 | 1905 | 2 (0.0005) | 37 | 34 (0.0000) | 29 (0.0061) | 0 | +5.0 % | +3.3 % | +4.77 | +25.2 % | 0 / 0 (0.0000) | -0.04 (-0.09 to +0.00) |

Best buy bound by day (days won): b10 3, b02 3, b05 2, b20 1.

### sandwich

| pair | buy bound | sale bound | signals | trades | 6040 (fees SOL) | pre-send skips | other buy failures (fees SOL) | failed sales (fees SOL) | given up | mean a trade | median | P&L per signal, points | worse than the signal by > 2 % | sandwiched buys / sales (SOL) | vs b60, points per signal (band) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| b02 | 0.02 | live | 1978 | 1361 | 143 (0.0356) | 440 | 34 (0.0000) | 0 (0.0000) | 0 | +8.3 % | +6.7 % | +5.69 | +0.0 % | 0 / 2 (0.1448) | +1.16 (-0.03 to +2.16) |
| b05 | 0.05 | live | 1978 | 1566 | 88 (0.0219) | 290 | 34 (0.0000) | 0 (0.0000) | 0 | +7.4 % | +9.6 % | +5.86 | +10.5 % | 0 / 3 (0.2334) | +1.33 (+0.62 to +2.04) |
| b10 | 0.1 | live | 1978 | 1716 | 48 (0.0120) | 180 | 34 (0.0000) | 0 (0.0000) | 0 | +6.4 % | +6.5 % | +5.51 | +17.4 % | 1 / 3 (0.2342) | +0.98 (+0.51 to +1.45) |
| b20 | 0.2 | live | 1978 | 1818 | 18 (0.0045) | 108 | 34 (0.0000) | 0 (0.0000) | 0 | +5.6 % | +5.4 % | +5.16 | +21.9 % | 1 / 5 (0.3852) | +0.63 (+0.32 to +0.97) |
| b30 | 0.3 | live | 1978 | 1861 | 11 (0.0027) | 72 | 34 (0.0000) | 0 (0.0000) | 0 | +5.2 % | +3.7 % | +4.85 | +23.5 % | 2 / 6 (0.4743) | +0.32 (+0.11 to +0.53) |
| **b60** | 0.6 | live | 1978 | 1905 | 2 (0.0005) | 37 | 34 (0.0000) | 0 (0.0000) | 0 | +4.7 % | +3.0 % | +4.53 | +25.2 % | 2 / 8 (0.5921) | reference |
| b100 | 1 | live | 1978 | 1913 | 2 (0.0005) | 29 | 34 (0.0000) | 0 (0.0000) | 0 | +4.7 % | +2.9 % | +4.51 | +25.5 % | 2 / 10 (0.7472) | -0.03 (-0.17 to +0.11) |
| s05 | 0.6 | 0.05 | 1978 | 1905 | 2 (0.0005) | 37 | 34 (0.0000) | 280 (0.0585) | 1 | +4.8 % | +2.0 % | +4.64 | +25.2 % | 2 / 7 (0.1353) | +0.11 (-0.32 to +0.49) |
| s15 | 0.6 | 0.15 | 1978 | 1905 | 2 (0.0005) | 37 | 34 (0.0000) | 73 (0.0153) | 0 | +4.8 % | +2.9 % | +4.62 | +25.2 % | 2 / 8 (0.2122) | +0.09 (-0.16 to +0.34) |
| s30 | 0.6 | 0.3 | 1978 | 1905 | 2 (0.0005) | 37 | 34 (0.0000) | 29 (0.0061) | 0 | +4.8 % | +3.0 % | +4.64 | +25.2 % | 2 / 8 (0.3048) | +0.11 (+0.00 to +0.23) |

Best buy bound by day (days won): b10 3, b02 3, b05 2, b20 1.

## P_cmig_model

### none

| pair | buy bound | sale bound | signals | trades | 6040 (fees SOL) | pre-send skips | other buy failures (fees SOL) | failed sales (fees SOL) | given up | mean a trade | median | P&L per signal, points | worse than the signal by > 2 % | sandwiched buys / sales (SOL) | vs b60, points per signal (band) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| b02 | 0.02 | live | 5196 | 3813 | 0 (0.0000) | 0 | 1383 (0.2717) | 7 (0.0015) | 0 | -6.6 % | -4.7 % | -4.90 | +0.0 % | 0 / 0 (0.0000) | +1.16 (+0.68 to +1.59) |
| b05 | 0.05 | live | 5196 | 4121 | 0 (0.0000) | 0 | 1075 (0.2073) | 9 (0.0019) | 0 | -6.6 % | -4.9 % | -5.28 | +7.5 % | 0 / 0 (0.0000) | +0.78 (+0.37 to +1.16) |
| b10 | 0.1 | live | 5196 | 4346 | 0 (0.0000) | 0 | 850 (0.1603) | 9 (0.0019) | 0 | -6.5 % | -5.0 % | -5.47 | +12.3 % | 0 / 0 (0.0000) | +0.59 (+0.21 to +0.92) |
| b20 | 0.2 | live | 5196 | 4619 | 0 (0.0000) | 0 | 577 (0.1032) | 9 (0.0019) | 0 | -6.5 % | -5.2 % | -5.78 | +17.4 % | 0 / 0 (0.0000) | +0.28 (+0.14 to +0.41) |
| b30 | 0.3 | live | 5196 | 4733 | 0 (0.0000) | 0 | 463 (0.0794) | 9 (0.0019) | 0 | -6.6 % | -5.3 % | -6.06 | +19.4 % | 0 / 0 (0.0000) | +0.00 (+0.00 to +0.00) |
| **b60** | 0.6 | live | 5196 | 4733 | 0 (0.0000) | 0 | 463 (0.0794) | 9 (0.0019) | 0 | -6.6 % | -5.3 % | -6.06 | +19.4 % | 0 / 0 (0.0000) | reference |
| b100 | 1 | live | 5196 | 4733 | 0 (0.0000) | 0 | 463 (0.0794) | 9 (0.0019) | 0 | -6.6 % | -5.3 % | -6.06 | +19.4 % | 0 / 0 (0.0000) | +0.00 (+0.00 to +0.00) |
| s05 | 0.6 | 0.05 | 5196 | 4733 | 0 (0.0000) | 0 | 463 (0.0794) | 1504 (0.3143) | 2 | -6.9 % | -5.1 % | -6.33 | +19.4 % | 0 / 0 (0.0000) | -0.27 (-0.44 to -0.10) |
| s15 | 0.6 | 0.15 | 5196 | 4733 | 0 (0.0000) | 0 | 463 (0.0794) | 593 (0.1239) | 0 | -6.7 % | -5.3 % | -6.11 | +19.4 % | 0 / 0 (0.0000) | -0.06 (-0.15 to +0.05) |
| s30 | 0.6 | 0.3 | 5196 | 4733 | 0 (0.0000) | 0 | 463 (0.0794) | 264 (0.0552) | 0 | -6.6 % | -5.3 % | -6.07 | +19.4 % | 0 / 0 (0.0000) | -0.01 (-0.07 to +0.05) |

Best buy bound by day (days won): b02 8, b20 1.

### sandwich

| pair | buy bound | sale bound | signals | trades | 6040 (fees SOL) | pre-send skips | other buy failures (fees SOL) | failed sales (fees SOL) | given up | mean a trade | median | P&L per signal, points | worse than the signal by > 2 % | sandwiched buys / sales (SOL) | vs b60, points per signal (band) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| b02 | 0.02 | live | 5196 | 3813 | 0 (0.0000) | 0 | 1383 (0.2717) | 7 (0.0015) | 0 | -6.6 % | -4.7 % | -4.90 | +0.0 % | 0 / 0 (0.0000) | +1.16 (+0.68 to +1.59) |
| b05 | 0.05 | live | 5196 | 4121 | 0 (0.0000) | 0 | 1075 (0.2073) | 9 (0.0019) | 0 | -6.6 % | -4.9 % | -5.28 | +7.5 % | 0 / 0 (0.0000) | +0.78 (+0.37 to +1.16) |
| b10 | 0.1 | live | 5196 | 4346 | 0 (0.0000) | 0 | 850 (0.1603) | 9 (0.0019) | 0 | -6.5 % | -5.0 % | -5.47 | +12.3 % | 0 / 0 (0.0000) | +0.59 (+0.21 to +0.92) |
| b20 | 0.2 | live | 5196 | 4619 | 0 (0.0000) | 0 | 577 (0.1032) | 9 (0.0019) | 0 | -6.5 % | -5.2 % | -5.78 | +17.4 % | 0 / 0 (0.0000) | +0.28 (+0.14 to +0.41) |
| b30 | 0.3 | live | 5196 | 4733 | 0 (0.0000) | 0 | 463 (0.0794) | 9 (0.0019) | 0 | -6.6 % | -5.3 % | -6.06 | +19.4 % | 0 / 0 (0.0000) | +0.00 (+0.00 to +0.00) |
| **b60** | 0.6 | live | 5196 | 4733 | 0 (0.0000) | 0 | 463 (0.0794) | 9 (0.0019) | 0 | -6.6 % | -5.3 % | -6.06 | +19.4 % | 0 / 0 (0.0000) | reference |
| b100 | 1 | live | 5196 | 4733 | 0 (0.0000) | 0 | 463 (0.0794) | 9 (0.0019) | 0 | -6.6 % | -5.3 % | -6.06 | +19.4 % | 0 / 0 (0.0000) | +0.00 (+0.00 to +0.00) |
| s05 | 0.6 | 0.05 | 5196 | 4733 | 0 (0.0000) | 0 | 463 (0.0794) | 1504 (0.3143) | 2 | -6.9 % | -5.1 % | -6.33 | +19.4 % | 0 / 0 (0.0000) | -0.27 (-0.44 to -0.10) |
| s15 | 0.6 | 0.15 | 5196 | 4733 | 0 (0.0000) | 0 | 463 (0.0794) | 593 (0.1239) | 0 | -6.7 % | -5.3 % | -6.11 | +19.4 % | 0 / 0 (0.0000) | -0.06 (-0.15 to +0.05) |
| s30 | 0.6 | 0.3 | 5196 | 4733 | 0 (0.0000) | 0 | 463 (0.0794) | 264 (0.0552) | 0 | -6.6 % | -5.3 % | -6.07 | +19.4 % | 0 / 0 (0.0000) | -0.01 (-0.07 to +0.05) |

Best buy bound by day (days won): b02 8, b20 1.

## The live sizing (W books, 0.55 SOL paper wallets)

| rule | view | pair | trades | P&L SOL | top-ups | failed sales | given up |
|---|---|---|---|---|---|---|---|
| P_pool0 | none | b02 | 878 | +7.127 | 0 | 1 | 0 |
| P_pool0 | none | b05 | 984 | +9.676 | 0 | 1 | 0 |
| P_pool0 | none | b10 | 1052 | +8.266 | 1 | 1 | 0 |
| P_pool0 | none | b20 | 1100 | +11.382 | 0 | 1 | 0 |
| P_pool0 | none | b30 | 1115 | +9.207 | 0 | 1 | 0 |
| P_pool0 | none | b60 | 1132 | +8.985 | 0 | 1 | 0 |
| P_pool0 | none | b100 | 1139 | +8.900 | 0 | 1 | 0 |
| P_pool0 | none | s05 | 1129 | +9.662 | 0 | 175 | 0 |
| P_pool0 | none | s15 | 1133 | +11.494 | 0 | 39 | 0 |
| P_pool0 | none | s30 | 1132 | +8.924 | 0 | 18 | 0 |
| P_pool0 | sandwich | b02 | 877 | +1.452 | 0 | 1 | 0 |
| P_pool0 | sandwich | b05 | 984 | +1.191 | 0 | 1 | 0 |
| P_pool0 | sandwich | b10 | 1051 | +1.564 | 1 | 1 | 0 |
| P_pool0 | sandwich | b20 | 1102 | +1.671 | 0 | 1 | 0 |
| P_pool0 | sandwich | b30 | 1116 | +1.915 | 0 | 1 | 0 |
| P_pool0 | sandwich | b60 | 1133 | +1.908 | 0 | 1 | 0 |
| P_pool0 | sandwich | b100 | 1142 | +2.636 | 0 | 1 | 0 |
| P_pool0 | sandwich | s05 | 1130 | +2.849 | 0 | 172 | 0 |
| P_pool0 | sandwich | s15 | 1133 | +2.103 | 0 | 40 | 0 |
| P_pool0 | sandwich | s30 | 1133 | +1.791 | 0 | 18 | 0 |
| P_pool0_wait | none | b02 | 974 | +5.536 | 0 | 0 | 0 |
| P_pool0_wait | none | b05 | 1071 | +6.019 | 0 | 0 | 0 |
| P_pool0_wait | none | b10 | 1158 | +7.193 | 0 | 0 | 0 |
| P_pool0_wait | none | b20 | 1225 | +9.554 | 0 | 0 | 0 |
| P_pool0_wait | none | b30 | 1248 | +6.804 | 0 | 0 | 0 |
| P_pool0_wait | none | b60 | 1270 | +6.666 | 0 | 0 | 0 |
| P_pool0_wait | none | b100 | 1276 | +6.705 | 0 | 0 | 0 |
| P_pool0_wait | none | s05 | 1265 | +6.698 | 0 | 172 | 0 |
| P_pool0_wait | none | s15 | 1268 | +6.766 | 0 | 44 | 0 |
| P_pool0_wait | none | s30 | 1270 | +6.655 | 0 | 18 | 0 |
| P_pool0_wait | sandwich | b02 | 975 | +1.760 | 0 | 0 | 0 |
| P_pool0_wait | sandwich | b05 | 1071 | +1.407 | 0 | 0 | 0 |
| P_pool0_wait | sandwich | b10 | 1158 | +1.139 | 0 | 0 | 0 |
| P_pool0_wait | sandwich | b20 | 1227 | +1.746 | 0 | 0 | 0 |
| P_pool0_wait | sandwich | b30 | 1248 | +0.849 | 0 | 0 | 0 |
| P_pool0_wait | sandwich | b60 | 1270 | +0.962 | 0 | 0 | 0 |
| P_pool0_wait | sandwich | b100 | 1276 | +0.878 | 0 | 0 | 0 |
| P_pool0_wait | sandwich | s05 | 1266 | +1.761 | 0 | 170 | 0 |
| P_pool0_wait | sandwich | s15 | 1269 | +1.520 | 0 | 44 | 0 |
| P_pool0_wait | sandwich | s30 | 1270 | +0.715 | 0 | 18 | 0 |
| P_cmig_model | none | b02 | 2675 | -9.221 | 30 | 7 | 0 |
| P_cmig_model | none | b05 | 2875 | -10.033 | 32 | 7 | 0 |
| P_cmig_model | none | b10 | 3004 | -10.506 | 34 | 7 | 0 |
| P_cmig_model | none | b20 | 3186 | -10.800 | 35 | 7 | 0 |
| P_cmig_model | none | b30 | 3256 | -11.214 | 36 | 7 | 0 |
| P_cmig_model | none | b60 | 3256 | -11.214 | 36 | 7 | 0 |
| P_cmig_model | none | b100 | 3256 | -11.214 | 36 | 7 | 0 |
| P_cmig_model | none | s05 | 3208 | -12.141 | 39 | 1063 | 1 |
| P_cmig_model | none | s15 | 3237 | -11.347 | 36 | 415 | 0 |
| P_cmig_model | none | s30 | 3246 | -11.276 | 36 | 176 | 0 |
| P_cmig_model | sandwich | b02 | 2675 | -9.221 | 30 | 7 | 0 |
| P_cmig_model | sandwich | b05 | 2875 | -10.033 | 32 | 7 | 0 |
| P_cmig_model | sandwich | b10 | 3004 | -10.506 | 34 | 7 | 0 |
| P_cmig_model | sandwich | b20 | 3186 | -10.800 | 35 | 7 | 0 |
| P_cmig_model | sandwich | b30 | 3256 | -11.214 | 36 | 7 | 0 |
| P_cmig_model | sandwich | b60 | 3256 | -11.214 | 36 | 7 | 0 |
| P_cmig_model | sandwich | b100 | 3256 | -11.214 | 36 | 7 | 0 |
| P_cmig_model | sandwich | s05 | 3208 | -12.141 | 39 | 1063 | 1 |
| P_cmig_model | sandwich | s15 | 3237 | -11.347 | 36 | 415 | 0 |
| P_cmig_model | sandwich | s30 | 3246 | -11.276 | 36 | 176 | 0 |

## P2's selection gap by bound

P2's paper side replaced by the C books of each pair (the three rules), against the live bot's trades in its runs (`selection_p2.compute`); points a trade.

| view | pair | paper signals | live trades | matched | paper minus live (band) | selection | same coins | live's own |
|---|---|---|---|---|---|---|---|---|
| none | b02 | 269 | 149 | 47 | +2.64 (-6.39 to +11.61) | +4.06 | +3.15 | -4.57 |
| none | b05 | 304 | 149 | 54 | +2.54 (-5.70 to +10.91) | +3.43 | +3.68 | -4.57 |
| none | b10 | 333 | 149 | 63 | +3.48 (-4.37 to +11.99) | +2.56 | +3.46 | -2.55 |
| none | b20 | 355 | 149 | 68 | +3.58 (-3.98 to +11.24) | +1.86 | +4.17 | -2.45 |
| none | b30 | 363 | 149 | 71 | +3.39 (-3.98 to +11.03) | +2.71 | +2.64 | -1.97 |
| none | b60 | 370 | 149 | 72 | +3.00 (-4.17 to +10.68) | +2.78 | +2.21 | -1.99 |
| none | b100 | 371 | 149 | 72 | +3.09 (-4.76 to +10.68) | +2.87 | +2.21 | -1.99 |
| none | s05 | 370 | 149 | 72 | +2.53 (-4.69 to +10.13) | +2.67 | +1.85 | -1.99 |
| none | s15 | 370 | 149 | 72 | +2.37 (-4.95 to +10.06) | +2.78 | +1.57 | -1.99 |
| none | s30 | 370 | 149 | 72 | +2.99 (-4.21 to +10.61) | +2.71 | +2.27 | -1.99 |
| sandwich | b02 | 269 | 149 | 47 | +2.64 (-6.39 to +11.61) | +4.06 | +3.15 | -4.57 |
| sandwich | b05 | 304 | 149 | 54 | +2.54 (-5.70 to +10.91) | +3.43 | +3.68 | -4.57 |
| sandwich | b10 | 333 | 149 | 63 | +3.48 (-4.37 to +11.99) | +2.56 | +3.46 | -2.55 |
| sandwich | b20 | 355 | 149 | 68 | +3.58 (-3.98 to +11.24) | +1.86 | +4.17 | -2.45 |
| sandwich | b30 | 363 | 149 | 71 | +3.39 (-3.98 to +11.03) | +2.71 | +2.64 | -1.97 |
| sandwich | b60 | 370 | 149 | 72 | +3.00 (-4.17 to +10.68) | +2.78 | +2.21 | -1.99 |
| sandwich | b100 | 371 | 149 | 72 | +3.09 (-4.76 to +10.68) | +2.87 | +2.21 | -1.99 |
| sandwich | s05 | 370 | 149 | 72 | +2.53 (-4.69 to +10.13) | +2.67 | +1.85 | -1.99 |
| sandwich | s15 | 370 | 149 | 72 | +2.37 (-4.95 to +10.06) | +2.78 | +1.57 | -1.99 |
| sandwich | s30 | 370 | 149 | 72 | +2.99 (-4.21 to +10.61) | +2.71 | +2.27 | -1.99 |

## Forward

E1 slippage bounds (results/slippage_e1.md): no forward trades of the `@e1_` books yet.

