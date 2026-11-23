# P2R2: P2's paper minus live gap on the realistic era only

Pre-registration `results/pumpfun_selection_gap_p2r2_prereg.md`. P2's method and decomposition (`selection_p2.compute`, unchanged) on the live trades and paper signals from 2026-10-28 19:40 UTC (P1's cut), all on the realistic paper model; the paper ledger's rows on a stale pool state left out and counted (`realistic.stale`, the pool state fix). Points a trade, each side on its own stake. R7's band: the standard error clustered by UTC day, t on G - 1 degrees of freedom; P2's percentile band (2,000 draws, seed 0) next to it. Too few to judge under 30 live trades or 5 days with a live trade. Five trials in R5's registry, counted only (`hand:p2r2:*`); no Sharpe, no DSR.

## The answer

- paper minus live on the realistic era only (P2R2, live trades from 2026-10-28 19:40 UTC, stale pool state rows out): +8.1 points a trade (R7 band -1.9 to +18.0; 37 live trades on 2 days, 512 paper signals, 12 pairs; selection +10.0, same coins -0.1, live's own trades -1.9): too few to judge (under 30 live trades or 5 days); a band under 2 points needs about 1,829 live trades (1,792 more, 242 days of running at 7.4 a day; at today's rate, the bot off, never); P3's gate reads P2's line, a switch is the owner's decision, results/pumpfun_selection_gap_p2r2.md.
- Next to it, P2's line as `realistic.md` reads it today: paper minus live on all live signals (P2, every live run): +8.8 points a trade (band +1.9 to +15.5; paper +5.4 % on 696 signals, live -3.4 % on 186 trades; selection -5.3, same coins +14.0, live's own trades +0.2): fails the ladder's gate for pump.fun (under 2 points), results/pumpfun_selection_gap_p2.md.
- With the stale rows kept (the paper before the fix): +9.5 points (P2's band -1.0 to +21.5; 556 paper signals, the sample's 44 stale rows back in).

## What it rests on

37 live closed trades on 2 UTC days, 512 paper signals with a return, 12 matched pairs; the band's G: 5 days with a signal or a trade (2026-10-29, 2026-10-30, 2026-10-31, 2026-11-01, 2026-11-02). Paper rows left out: 6 tainted (P1), 16 closed by a restart, 44 on a stale pool state.

| UTC day | live trades |
|---|---|
| 2026-10-29 | 34 |
| 2026-10-30 | 3 |

## The gap and its parts

| what | % or points a trade | R7 band (by day) | P2's band (percentile) |
|---|---|---|---|
| paper, all its signals (P_all) | +1.2 | -4.1 to +6.6 | -2.0 to +5.4 |
| paper, the signals live traded (P_m) | -8.7 | -42.4 to +24.9 | -31.3 to +8.8 |
| live, the same trades (L_m) | -8.7 | -41.1 to +23.7 | -30.1 to +6.2 |
| live, all its trades (L_all) | -6.8 | -13.1 to -0.5 | -17.9 to +3.2 |
| **paper minus live on all live signals (P_all - L_all)** | +8.1 | -1.9 to +18.0 | -2.5 to +19.3 |
| selection (P_all - P_m) | +10.0 | -26.3 to +46.3 | -7.5 to +32.5 |
| same coins (P_m - L_m) | -0.1 | -1.3 to +1.2 | -4.6 to +5.0 |
| live's own trades (L_m - L_all) | -1.9 | -28.0 to +24.2 | -24.6 to +16.7 |

The selection part by reason, (n_r / n) (mean_r - P_m), points a trade:

| reason | points | R7 band | P2's band |
|---|---|---|---|
| paused | +5.6 | -15.4 to +26.6 | -4.3 to +18.1 |
| not seen by the live feed | +3.4 | -9.4 to +16.2 | -2.5 to +10.8 |
| refused by the wallet or the brake | +0.6 | -0.5 to +1.7 | -0.6 to +2.0 |
| other | +0.3 | -2.4 to +3.0 | -1.1 to +2.2 |
| buy failed | +0.1 | -0.3 to +0.6 | -0.0 to +0.5 |
| ran away before the send | -0.0 | -0.1 to +0.0 | -0.1 to +0.0 |

## The trades still needed

With n live trades on G days and the gap's clustered standard error se, the smallest N with 2 t(0.975, G_N - 1) se sqrt(n / N) under 2 points, G_N = ceil(N G / n).

n 37, G 5, se 3.6 points: N = 1,829, 1,792 live trades more, 242 days of running at 7.4 trades a day. At today's rate (the bot off, no trade since its last) never.

## Every paper signal by its live outcome

| rule | reason | signals | with a return | paper mean |
|---|---|---|---|---|
| P_pool0 | traded | 14 | 12 | -8.7 % |
| P_pool0 | buy failed | 4 | 3 | +14.2 % |
| P_pool0 | paused | 282 | 272 | +1.7 % |
| P_pool0 | refused by the wallet or the brake | 23 | 22 | +5.2 % |
| P_pool0 | ran away before the send | 1 | 1 | -25.5 % |
| P_pool0 | not seen by the live feed | 165 | 164 | +1.8 % |
| P_pool0 | other | 38 | 38 | -4.2 % |
| all | traded | 14 | 12 | -8.7 % |
| all | buy failed | 4 | 3 | +14.2 % |
| all | paused | 282 | 272 | +1.7 % |
| all | refused by the wallet or the brake | 23 | 22 | +5.2 % |
| all | ran away before the send | 1 | 1 | -25.5 % |
| all | not seen by the live feed | 165 | 164 | +1.8 % |
| all | other | 38 | 38 | -4.2 % |

By detail (every rule):

| reason | detail | signals | paper mean |
|---|---|---|---|
| buy failed | 6040 | 4 | +14.2 % |
| paused | paused by the owner | 282 | +1.7 % |
| refused by the wallet or the brake | daily loss limit | 16 | +16.9 % |
| refused by the wallet or the brake | max open positions | 6 | -23.0 % |
| refused by the wallet or the brake | refused: total budget | 1 | -0.9 % |
| ran away before the send | price ran away | 1 | -25.5 % |
| not seen by the live feed | no pool state | 91 | +1.4 % |
| not seen by the live feed | never seen by the live service | 73 | +2.2 % |
| not seen by the live feed | creation not seen | 1 | +10.1 % |
| other | live gate shut: the last simulation failed | 37 | -3.9 % |
| other | seen, no decision | 1 | -16.9 % |

## Live trades without a paper twin

25 of 37 live trades; live mean on them -5.9 %.

| rule | why paper did not take it | trades | live mean |
|---|---|---|---|
| P_pool0 | no paper record (the collector had the coin) | 17 | -8.8 % |
| P_pool0 | no paper record | 4 | +2.9 % |
| P_pool0 | paper buy failed | 2 | -9.9 % |
| P_pool0 | paper row on a stale pool state | 2 | +5.4 % |

## Reading (written 2026-11-23, after the numbers above)

- On the realistic era only, paper overstates live by +8.1 points a trade (R7 band -1.9 to +18.0). That is hardly
  below P2's +8.8 over every run, but the parts are different. P2's came from the same coins (+14.0, mostly the ideal
  paper era, as G1 found). Here the same coins are -0.1: on the 12 matched pairs paper and live agree (-8.7 % each).
  What remains is selection, +10.0 (band -26.3 to +46.3).
- The selection part is large mostly because the 12 coins live traded were poor ones (paper -8.7 % on them against
  +1.2 % on all 512 signals), not because the coins live missed were good. "Paused by the owner" (282 of 512 signals,
  paper +1.7 %) carries +5.6 and "not seen by the live feed" (165, +1.8 %) carries +3.4 of it. A gap that rests
  mostly on paused hours measures which coins live was allowed to try, not how it executes.
- Live made -6.8 % a trade on its 37 trades (R7 band -13.1 to -0.5 %), paper +1.2 % on its 512 signals.
- The pool state fix accounts for 1.4 points. With the 44 stale paper rows kept, the gap reads +9.5.
- Too few to judge: 37 live trades (over 30) but on two UTC days (under 5). The R7 bands of the parts that rest on
  the 12 pairs (same coins -1.3 to +1.2) come from two days of pairs and are too narrow to trust; P2's percentile
  band there is -4.6 to +5.0.
- A band under 2 points would take about 1,829 live trades, 1,792 more. That is about 242 days of running at the
  sample's 7.4 trades a day (37 trades over the 5 days with a signal or a trade). At today's rate (the bot off since
  2026-10-30) it never comes. The standard error behind this count comes from five days, so read it as an order of
  magnitude.
- P3's gate keeps reading P2's line (+8.8, fails). Moving it to this line is the owner's decision. Even moved, the
  gate would not pass: +8.1 points, too few to judge.
