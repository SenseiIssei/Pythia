# Live twin: every live pump.fun trade replayed through the realistic executor

Pre-registration `results/pumpfun_live_twin_prereg.md`. Read only: `<data>/live/pumpfun_rt` (ledger, orders, measured) and the recorded stream `<data>/pumpfun_rt`. Each live trade signalled again at its signal_ms with its rule and the stake it sent, through `realistic.RealExecutor` on the leave-one-day-out fit. Points a trade (live return less twin return, x 100). Bands: day-clustered 95 % percentile bootstrap, 2,000 draws, seed 0, over 3 days. Five trials in R5's registry, family pumpfun, counted only (`pumpfun:live_twin:*`); no Sharpe, no DSR.

Beyond the pre-registration, fixed after two earlier runs (the first: 30 twins, most misses "coin not recorded", live minus twin +2.1 points; the second, with the lag below: 66 twins, -2.5 points, the latency and entry price parts +76.7 and -76.6 from one trade): the record lags the live feed (a migration reaches the collector up to 25 s after the live bot signalled on it), so a coin the record does not hold yet at the live signal (a pool rule: not migrated yet) is asked again every 100 ms up to 120 s and the twin signals when the record has it, every live time moved by that lag onto the record's clock; P_pool0_wait keeps its 5 s wait for the pool's first trade on the record's clock (the record has no pool reads on these days, so without it every such coin would be "no pool state"); m(t) is the state at the end of the slot of the first trade at or after t (a slot's rows share its time; the first trades of a fresh pool's slot carry states up to 20 times off, KIMCHICAT 2026-10-24, which put +2,140 points into one trade's latency part and -2,141 into its entry price).

## The answer

- Twins: 66 of 149 live trades; every miss named below.
- Live minus twin: mean -2.5 points a trade (day band -4.0 to -0.3), median +0.5; live -5.4 %, twin -3.0 % on the same trades.
- Parts (mean points a trade): entry latency -0.3 (-1.2 to +6.4), entry price +0.4 (-0.1 to +1.7), exit decision time +1.8 (-6.7 to +10.5), exit price -0.7 (-5.9 to +7.2), fees -2.5 (-8.9 to -0.6), failed buys -1.1 (-2.6 to +0.0); their sum -2.5 against the total -2.5.
- The day band excludes 0: paper books would need a haircut of 2.5 points a trade (live minus twin -2.5: each paper trade's return -2.5 points; proposed only, no book, gate or live file reads it).

## Live minus twin

| | twins | live | twin | live minus twin: mean | median | day band | entry latency | entry price | exit decision time | exit price | fees | failed buys | sum of parts |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| all | 66 | -5.4 % | -3.0 % | -2.5 | +0.5 | -4.0 to -0.3 | -0.3 | +0.4 | +1.8 | -0.7 | -2.5 | -1.1 | -2.5 |
| no gap in the window (check) | 49 | -1.5 % | -2.4 % | +0.9 | +1.0 | -3.0 to +6.9 | +0.5 | +1.3 | +0.9 | +1.0 | -3.3 | +0.5 | +0.9 |

By day (UTC, the signal's):

| | twins | live | twin | live minus twin: mean | median | day band | entry latency | entry price | exit decision time | exit price | fees | failed buys | sum of parts |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2026-10-22 | 7 | -1.3 % | -0.9 % | -0.3 | -4.7 | one day | +6.4 | +1.7 | -6.7 | +7.2 | -8.9 | +0.0 | -0.3 |
| 2026-10-23 | 29 | -11.6 % | -10.2 % | -1.4 | +0.5 | one day | -1.2 | +0.6 | +10.5 | -5.9 | -2.9 | -2.6 | -1.4 |
| 2026-10-24 | 30 | -0.4 % | +3.6 % | -4.0 | -0.4 | one day | -1.1 | -0.1 | -4.6 | +2.4 | -0.6 | +0.0 | -4.0 |

By rule:

| | twins | live | twin | live minus twin: mean | median | day band | entry latency | entry price | exit decision time | exit price | fees | failed buys | sum of parts |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| P_pool0_wait | 49 | -5.3 % | -0.5 % | -4.8 | +0.5 | -6.2 to -4.0 | -1.3 | +0.6 | -2.2 | +0.5 | -0.4 | -2.0 | -4.8 |
| P_cmig_model | 5 | -16.9 % | -11.5 % | -5.4 | -9.5 | one day | +12.5 | -1.5 | -6.4 | +3.1 | -13.1 | +0.0 | -5.4 |
| P_pool0 | 12 | -1.2 % | -9.5 % | +8.3 | +3.0 | +7.6 to +12.3 | -1.8 | +0.5 | +21.4 | -7.2 | -6.5 | +1.9 | +8.3 |

The record's lag: 36 of 66 twins signalled after the live signal, median 0.1 s, at most 25.1 s.

Twin outcomes: bought 63, buy failed 3; stakes from the ledger 1, the order 148.

## Live trades without a twin

83 of 149. Coin not recorded: no creation row of it in the replayed days (the engine knows a coin only from its creation; the paper books miss it alike). No pool state in the record: no recorded pool trade within the rule's wait (P_pool0: at the signal) and no pool read on these days, where the live bot had its own. Stream gap: a gap of the trade's program over a moment the replay needs or 10 % of its window.

| rule | reason | trades |
|---|---|---|
| P_cmig_model | coin not recorded | 2 |
| P_pool0 | no pool state in the record | 12 |
| P_pool0 | stream gap | 3 |
| P_pool0 | coin not recorded | 1 |
| P_pool0_wait | no pool state in the record | 40 |
| P_pool0_wait | coin not recorded | 17 |
| P_pool0_wait | stream gap | 8 |

## The leave-one-day-out fits

| judged day | buy fills | sell fills | buy median s | sell median s | source |
|---|---|---|---|---|---|
| 2026-10-22 | 136 | 136 | 5.9 | 0.6 | buy live, fail live, sell live, send live |
| 2026-10-23 | 61 | 61 | 3.1 | 0.5 | buy live, fail live, sell live, send live |
| 2026-10-24 | 97 | 95 | 8.8 | 0.6 | buy live, fail live, sell live, send live |

## Reading (written 2026-10-29, after the numbers above)

- 66 of 149 live trades have a twin; the judge's 120 is not reached, and every miss is named: 52 "no pool state in
  the record" (no recorded pool trade within the rule's wait, and the record has no pool reads on 2026-10-22 to 24,
  where the live bot read the pool itself), 20 "coin not recorded" (no creation row: the engine never knows the coin,
  the paper books miss it alike), 11 "stream gap". No miss is a P1 taint or a twin open at the end.
- Out of fit, the realistic executor overstates live by about 2.5 points a trade on exactly the trades live made
  (mean -2.5, day band -4.0 to -0.3; median +0.5). That is far under P2's +18.9 (the ideal model and the selection)
  but over the ladder's 2 points.
- Where it comes from: fees and what the prices do not explain -2.5 (median -0.6; the tail is the small stakes of
  2026-10-22 and 23, P_cmig_model at 0.01 to 0.04 SOL and P_pool0 at 0.1 SOL, where live paid about 1,000,000
  lamports a transaction, far over the fit's median fee: -6 to -35 points each) and failed buys -1.1. The latency model holds on days it did not
  see: entry latency -0.3, entry price +0.4, exit decision time +1.8, exit price -0.7, every band across 0.
- By rule: P_pool0_wait -4.8 (49 trades), P_cmig_model -5.4 (5), P_pool0 +8.3 (12, live better than its twin).
- Fragile: the band is over 3 days (at most 10 distinct day draws), and on the 49 trades with no gap at all in
  their window the sign turns (+0.9, band -3.0 to +6.9). The proposed haircut of 2.5 points a trade is a hint, not
  a calibration; it is not wired into any book.
