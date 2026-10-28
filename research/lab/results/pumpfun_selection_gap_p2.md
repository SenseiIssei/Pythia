# P2: the selection gap between the live pump.fun bot and its paper twin

Pre-registration `results/pumpfun_selection_gap_p2_prereg.md`. Read only: `<data>/live/pumpfun_rt` (orders, ledger, skipped, seen, journal) and `<data>/paper/pumpfun_rt` (ledger, failed, skipped, state). Returns per trade on each side's own stake; a live record of the coin within 10 minutes of the paper signal is its outcome. Bands: 95 % percentile bootstrap, 2,000 draws, seed 0. Five trials in R5's registry, counted only (`hand:p2:*`); no Sharpe, no DSR.

Beyond the pre-registration, fixed after the first run and before reading any gap: a run counts from 10 minutes before its start (the unnamed first run starts at its first live signal, 2 s after the paper's signal of the same coin); a live trade of the coin within the window is traded even when its buy filled later (a buy that did not land, retried); "no paper record" says whether the paper twin had not started yet or the collector had the coin.

## The answer

- paper minus live on all live signals (P2, every live run): +18.9 points a trade (band +3.8 to +35.8; paper +16.3 % on 140 signals, live -2.6 % on 149 trades; selection +2.8, same coins +15.7, live's own trades +0.3): fails the ladder's gate for pump.fun (under 2 points), results/pumpfun_selection_gap_p2.md.
- Realistic paper only (signals and live trades from 2026-10-24 01:43 UTC): +4.3 points (band -14.6 to +25.6; paper +3.1 % on 54 signals, live -1.2 % on 41 trades).

## The live runs

20 runs with a rule (0 without one left out), 32.1 hours on.

| from (UTC) | to | rule |
|---|---|---|
| 2026-10-22 17:09 | 20:21 | P_cmig_model |
| 2026-10-22 21:45 | 22:18 | P_pool0 |
| 2026-10-22 22:22 | 23:17 | P_pool0 |
| 2026-10-22 23:25 | 23:56 | P_pool0 |
| 2026-10-22 23:58 | 05:26 | P_pool0 |
| 2026-10-23 05:32 | 06:45 | P_pool0 |
| 2026-10-23 14:55 | 15:15 | P_pool0_wait |
| 2026-10-23 16:11 | 17:06 | P_pool0_wait |
| 2026-10-23 17:08 | 17:21 | P_pool0_wait |
| 2026-10-23 17:23 | 17:55 | P_pool0_wait |
| 2026-10-23 17:59 | 18:19 | P_pool0_wait |
| 2026-10-23 18:21 | 18:26 | P_pool0_wait |
| 2026-10-23 18:28 | 18:34 | P_pool0_wait |
| 2026-10-23 18:36 | 18:51 | P_pool0_wait |
| 2026-10-23 18:53 | 18:57 | P_pool0_wait |
| 2026-10-23 18:57 | 19:09 | P_pool0_wait |
| 2026-10-23 19:10 | 21:51 | P_pool0_wait |
| 2026-10-23 21:52 | 22:12 | P_pool0_wait |
| 2026-10-23 22:12 | 23:46 | P_pool0_wait |
| 2026-10-23 23:47 | 12:22 | P_pool0_wait |

Paper rows left out: 6 tainted (P1), 7 closed by a restart.

## Every paper signal by its live outcome

| rule | reason | signals | with a return | paper mean |
|---|---|---|---|---|
| P_cmig_model | traded | 5 | 5 | -8.7 % |
| P_cmig_model | other | 10 | 8 | -15.8 % |
| P_pool0 | traded | 9 | 9 | -7.1 % |
| P_pool0 | buy failed | 1 | 1 | +35.9 % |
| P_pool0 | other | 15 | 15 | -2.5 % |
| P_pool0_wait | traded | 35 | 34 | +22.2 % |
| P_pool0_wait | buy failed | 2 | 1 | +383.7 % |
| P_pool0_wait | refused by the wallet or the brake | 21 | 15 | -2.4 % |
| P_pool0_wait | ran away before the send | 4 | 2 | +154.2 % |
| P_pool0_wait | not seen by the live feed | 51 | 42 | +23.7 % |
| P_pool0_wait | other | 10 | 8 | +13.6 % |
| all | traded | 49 | 48 | +13.5 % |
| all | buy failed | 3 | 2 | +209.8 % |
| all | refused by the wallet or the brake | 21 | 15 | -2.4 % |
| all | ran away before the send | 4 | 2 | +154.2 % |
| all | not seen by the live feed | 51 | 42 | +23.7 % |
| all | other | 35 | 31 | -1.8 % |

By detail (every rule):

| reason | detail | signals | paper mean |
|---|---|---|---|
| buy failed | 6040 | 3 | +209.8 % |
| refused by the wallet or the brake | stake paused: the wallet cannot pay one trade of 0.05 SOL | 21 | -2.4 % |
| ran away before the send | price ran away | 4 | +154.2 % |
| not seen by the live feed | no pool state | 28 | +5.0 % |
| not seen by the live feed | never seen by the live service | 11 | +73.3 % |
| not seen by the live feed | creation not seen | 8 | -6.4 % |
| not seen by the live feed | no pool state (PumpSwap stream down) | 4 | +36.8 % |
| other | no live log yet | 35 | -1.8 % |

## The gap, every live run

140 paper signals with a return, 149 live trades, 48 matched pairs.

| what | % or points a trade | 95 % band |
|---|---|---|
| paper, all its signals (P_all) | +16.3 | +2.3 to +32.4 |
| paper, the signals live traded (P_m) | +13.5 | -4.2 to +35.3 |
| live, the same trades (L_m) | -2.3 | -13.0 to +9.0 |
| live, all its trades (L_all) | -2.6 | -8.1 to +3.0 |
| **paper minus live on all live signals (P_all - L_all)** | +18.9 | +3.8 to +35.8 |
| selection (P_all - P_m) | +2.8 | -16.9 to +22.6 |
| same coins (P_m - L_m) | +15.7 | -2.4 to +37.5 |
| live's own trades (L_m - L_all) | +0.3 | -11.8 to +12.7 |

The selection part by reason, (n_r / n) (mean_r - P_m), points a trade:

| reason | points | 95 % band |
|---|---|---|
| other | -3.4 | -9.4 to +1.6 |
| not seen by the live feed | +3.1 | -8.4 to +17.2 |
| buy failed | +2.8 | +0.0 to +8.4 |
| ran away before the send | +2.0 | -0.1 to +6.4 |
| refused by the wallet or the brake | -1.7 | -5.1 to +1.2 |

## The gap, realistic paper only (from 2026-10-24 01:43 UTC)

54 paper signals with a return, 41 live trades, 14 matched pairs.

| what | % or points a trade | 95 % band |
|---|---|---|
| paper, all its signals (P_all) | +3.1 | -11.9 to +22.1 |
| paper, the signals live traded (P_m) | +10.7 | -10.7 to +29.4 |
| live, the same trades (L_m) | +13.4 | -0.4 to +26.1 |
| live, all its trades (L_all) | -1.2 | -11.6 to +8.6 |
| **paper minus live on all live signals (P_all - L_all)** | +4.3 | -14.6 to +25.6 |
| selection (P_all - P_m) | -7.5 | -27.8 to +17.6 |
| same coins (P_m - L_m) | -2.7 | -20.4 to +15.5 |
| live's own trades (L_m - L_all) | +14.6 | -2.5 to +30.9 |

The selection part by reason, (n_r / n) (mean_r - P_m), points a trade:

| reason | points | 95 % band |
|---|---|---|
| not seen by the live feed | -10.5 | -23.4 to +1.9 |
| buy failed | +6.9 | +0.0 to +21.5 |
| refused by the wallet or the brake | -4.0 | -11.5 to +3.5 |
| ran away before the send | +0.1 | -0.4 to +0.8 |

## Live trades without a paper twin

101 of 149 live trades; live mean on them -2.7 %.

| rule | why paper did not take it | trades | live mean |
|---|---|---|---|
| P_cmig_model | no paper record | 2 | -38.9 % |
| P_pool0 | no paper record (the collector had the coin) | 16 | -2.8 % |
| P_pool0 | no paper record (the paper twin not started yet) | 2 | +31.0 % |
| P_pool0 | no paper record | 1 | -64.0 % |
| P_pool0_wait | no pool state | 25 | -0.3 % |
| P_pool0_wait | creation not seen | 15 | +0.3 % |
| P_pool0_wait | no paper record (the collector had the coin) | 14 | +5.5 % |
| P_pool0_wait | no paper record | 12 | -7.4 % |
| P_pool0_wait | max open positions | 5 | +11.2 % |
| P_pool0_wait | stake paused: the wallet cannot pay one trade of 0.05 SOL | 5 | -33.7 % |
| P_pool0_wait | paper closed by a restart | 2 | +18.6 % |
| P_pool0_wait | category unknown | 1 | +22.0 % |
| P_pool0_wait | price ran away | 1 | -86.9 % |

## Reading (written 2026-10-28, after the numbers above)

- The gate fails: paper overstates live by +18.9 points a trade over every live run (band +3.8 to +35.8), far over
  2 points. No paper number of these three rules is fit for a real-money decision.
- On this record the gap is not mostly which coins each side got. Selection is +2.8 points (band -16.9 to +22.6);
  the same coins are +15.7 (band -2.4 to +37.5). Before 2026-10-24 01:43 UTC the paper books traded the ideal model
  (1 s latency), and on those coins paper did far better than live; on realistic paper alone the same-coin part is
  -2.7, in line with the calibration line.
- Realistic paper alone (54 signals, 41 live trades): +4.3 points, band -14.6 to +25.6, too few trades to pass or
  fail anything. There the largest part is live's own trades (+14.6): 27 of live's 41 trades had no paper twin, and
  they lost where the 14 matched ones made +13.4 %.
- Costliest reason (largest positive term of the selection part): over every run "not seen by the live feed" (+3.1,
  band across zero) and the buy that failed with 6040 (+2.8, band +0.0 to +8.4: three coins that made +210 % on
  paper); on realistic paper the 6040 failures (+6.9). The wallet refusals (stake paused, the wallet could not pay 0.05 SOL,
  2026-10-24 00:44 to 12:18 UTC) cost nothing: paper lost on those coins.
- 101 of 149 live trades have no paper twin. The paper's own feed missed many (no pool state 25, creation not seen
  15) and for 30 the collector had the coin under another book but the twin left no record (its skip log only
  starts 2026-10-23 18:04 UTC). The two sides' feeds disagree in both directions; the paper twin is not yet a
  faithful copy of the live bot's coin list.
