# The Trends measures in our models and strategies (Y10)

PAPER ONLY. Nothing here holds a wallet, reads a key, signs or sends anything; the live service, its executor, its
sizing and its confirmation file were not touched. The live executor's files were only read.

Pre-registration: `results/pumpfun_trends_y10_prereg.md` (10 trials, committed before the first replay). Code:
`lab/pumpfun_rt/trendfeat.py` (the trend features and triggers), `trends10.py` (the run), the strategies in
`pipeline._build_y10`, the models with the trend features in `selmodel.py` and `exitpol.py`; tests:
`tests/test_pumpfun_trends_y10.py`. Data: the server's record, 2026-10-20 16:40 UTC to the registered cutoff
2026-10-23 14:00 UTC, entries to 13:45 UTC. One replay, about 25 minutes. Latency Y9's (no new executor fill since).

## Short answer

**No book is better than P_pool0 under both daily loss limits, so nothing is recommended for the live bot, and the
trend features do not improve the Y9 filters by the registered rule.** Out of sample is 2026-10-22 00:00 to 2026-10-23
13:45 UTC (the first day with every model), about 38 hours and 333 migrations P_pool0 could enter.

- Under the live limit of 0.25 SOL X0 again stopped for the day after its first stops (8 entries in 2 hours, -40.6 %
  per entry): no band of a difference exists, so every answer is no.
- Under 1.0 SOL two books pass the rule: **A2** (`P_pool5_top30t`, Y9's +5 s filter on the model with the trend
  features) +7.2 % per entry over 134 entries against X0's -2.8 % (difference +10.0 points, band +5.1 to +14.9, +1.86
  SOL more), and **T1** (`P_hot5`, a curve in the hot-now top 5 with rising buyers and P(alive 5 min) at least its base
  rate) +5.8 % over 25 entries in 11 hours (difference +8.7 points, band +0.4 to +15.7); T1 enters curves, nearly never
  the coins X0 enters, and its median entry loses (-5.1 %, 32 % winners): a few large winners carry it.
- (a) A2 against Y9's S4: +3.2 points under 1.0 SOL (band -0.9 to +7.1), +1.3 under 0.25 SOL (band -5.0 to +7.5):
  leaning better, not passing. A1 (`P_pool0_top30t`) is worse than Y9's S2 (-6.4 points under 1.0 SOL, band -14.2 to
  +1.1, and less P&L). The trend columns lift the rug models' AUC (rug0 0.638 to 0.675, rug5 0.622 to 0.650) and leave
  the win models where they were (win0 0.657 to 0.652, win5 0.684 to 0.686); the early models do not move (alive5m
  0.924 both, peak3x 0.826 and 0.825).
- (b) T2 (`P_fresh3`, a fresh pool in the top 3 two to ten minutes after its migration) loses clearly: -13.8 % per
  entry under 1.0 SOL (band -25.0 to -4.1), -1.85 SOL, and it hits the daily loss limit (387 skips). T3
  (`P_pool0_heat`, P_pool0 only while the market is hot) is P_pool0 with a third of its entries removed and the same
  mean (+0.4 points, band -2.7 to +3.8).

The five run as paper strategies from the deploy on; the meme module's new rule `trend_top` uses the Trends ranks on
paper. A2 and T1 are the two to watch: if their lean holds on paper for two weeks under both limits, a new
pre-registered check can ask the live question.

## 1. The models with and without the trend features, walk-forward

| Y9 model | with trends | rows tested | AUC | AUC with trends | logistic AUC | logistic with trends | Brier skill | with trends | mean return of its top 30 % | with trends |
|---|---|---|---|---|---|---|---|---|---|---|
| win0 | win0t | 333 | 0.657 | 0.652 | 0.652 | 0.634 | +0.062 | +0.050 | +6.4 % (67) | -0.1 % (86) |
| rug0 | rug0t | 333 | 0.638 | 0.675 | 0.676 | 0.698 | -0.088 | -0.029 | +0.1 % (166) | -1.5 % (156) |
| win5 | win5t | 424 | 0.684 | 0.686 | 0.675 | 0.645 | +0.095 | +0.097 | +4.0 % (89) | +7.2 % (134) |
| rug5 | rug5t | 424 | 0.622 | 0.650 | 0.673 | 0.711 | -0.040 | -0.001 | -0.3 % (122) | -8.8 % (131) |

| early label | rows | folds | AUC e_ | AUC et_ (with trends) | Brier skill e_ | Brier skill et_ |
|---|---|---|---|---|---|---|
| alive5m | 216033 | 5 | 0.924 | 0.924 | +0.566 | +0.571 |
| peak3x | 213697 | 5 | 0.826 | 0.825 | +0.035 | +0.037 |

### Every select model, by day (each day tested by models trained on the days before)

| label | rows tested | rate | AUC | logistic AUC | Brier skill | logistic Brier skill | mean return, all | top 30 % | under the base rate |
|---|---|---|---|---|---|---|---|---|---|
| win0 | 333 | 53.2 % | 0.657 | 0.652 | +0.062 | +0.025 | -2.8 % | +6.4 % (67) | -6.6 % (168) |
| rug0 | 333 | 7.5 % | 0.638 | 0.676 | -0.088 | -0.315 | -2.8 % | +0.1 % (166) | -2.3 % (261) |
| win5 | 424 | 52.4 % | 0.684 | 0.675 | +0.095 | +0.065 | -3.2 % | +4.0 % (89) | -8.8 % (233) |
| rug5 | 424 | 7.1 % | 0.622 | 0.673 | -0.040 | -0.227 | -3.2 % | -0.3 % (122) | -2.9 % (375) |
| win0t | 333 | 53.2 % | 0.652 | 0.634 | +0.050 | -0.044 | -2.8 % | -0.1 % (86) | -8.9 % (145) |
| rug0t | 333 | 7.5 % | 0.675 | 0.698 | -0.029 | -0.362 | -2.8 % | -1.5 % (156) | -3.5 % (259) |
| win5t | 424 | 52.4 % | 0.686 | 0.645 | +0.097 | -0.007 | -3.2 % | +7.2 % (134) | -8.3 % (209) |
| rug5t | 424 | 7.1 % | 0.650 | 0.711 | -0.001 | -0.299 | -3.2 % | -8.8 % (131) | -2.5 % (384) |

| label | day | trained on | tested | AUC | logistic AUC | rate | base | top threshold |
|---|---|---|---|---|---|---|---|---|
| win0 | 2026-10-20 | 0 | 52 | no model | | | | |
| win0 | 2026-10-21 | 48 | 173 | no model | | | | |
| win0 | 2026-10-22 | 223 | 189 | 0.694 | 0.661 | 51.3 % | 52.0 % | 0.705 |
| win0 | 2026-10-23 | 413 | 144 | 0.621 | 0.622 | 55.6 % | 51.3 % | 0.663 |
| rug0 | 2026-10-20 | 0 | 52 | no model | | | | |
| rug0 | 2026-10-21 | 48 | 173 | no model | | | | |
| rug0 | 2026-10-22 | 223 | 189 | 0.573 | 0.660 | 6.9 % | 9.9 % | 0.037 |
| rug0 | 2026-10-23 | 413 | 144 | 0.727 | 0.707 | 8.3 % | 8.5 % | 0.028 |
| win5 | 2026-10-20 | 0 | 69 | no model | | | | |
| win5 | 2026-10-21 | 65 | 216 | no model | | | | |
| win5 | 2026-10-22 | 283 | 233 | 0.667 | 0.643 | 51.5 % | 48.8 % | 0.673 |
| win5 | 2026-10-23 | 517 | 191 | 0.712 | 0.714 | 53.4 % | 49.7 % | 0.651 |
| rug5 | 2026-10-20 | 0 | 69 | no model | | | | |
| rug5 | 2026-10-21 | 65 | 216 | no model | | | | |
| rug5 | 2026-10-22 | 283 | 233 | 0.640 | 0.665 | 6.9 % | 8.5 % | 0.047 |
| rug5 | 2026-10-23 | 517 | 191 | 0.615 | 0.691 | 7.3 % | 7.7 % | 0.027 |
| win0t | 2026-10-20 | 0 | 52 | no model | | | | |
| win0t | 2026-10-21 | 48 | 173 | no model | | | | |
| win0t | 2026-10-22 | 223 | 189 | 0.677 | 0.644 | 51.3 % | 52.0 % | 0.725 |
| win0t | 2026-10-23 | 413 | 144 | 0.619 | 0.596 | 55.6 % | 51.3 % | 0.653 |
| rug0t | 2026-10-20 | 0 | 52 | no model | | | | |
| rug0t | 2026-10-21 | 48 | 173 | no model | | | | |
| rug0t | 2026-10-22 | 223 | 189 | 0.607 | 0.691 | 6.9 % | 9.9 % | 0.044 |
| rug0t | 2026-10-23 | 413 | 144 | 0.768 | 0.737 | 8.3 % | 8.5 % | 0.027 |
| win5t | 2026-10-20 | 0 | 69 | no model | | | | |
| win5t | 2026-10-21 | 65 | 216 | no model | | | | |
| win5t | 2026-10-22 | 283 | 233 | 0.662 | 0.615 | 51.5 % | 48.8 % | 0.616 |
| win5t | 2026-10-23 | 517 | 191 | 0.714 | 0.682 | 53.4 % | 49.7 % | 0.616 |
| rug5t | 2026-10-20 | 0 | 69 | no model | | | | |
| rug5t | 2026-10-21 | 65 | 216 | no model | | | | |
| rug5t | 2026-10-22 | 283 | 233 | 0.728 | 0.726 | 6.9 % | 8.5 % | 0.046 |
| rug5t | 2026-10-23 | 517 | 191 | 0.609 | 0.704 | 7.3 % | 7.7 % | 0.020 |

## 2. Out of sample, daily loss limit 0.25 SOL (live, judged)

| book | strategy | entries | hours | failed buys | mean | median | win | P&L SOL | band of mean | max DD SOL | no model | filtered out | no pool state | daily loss limit |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| X0 | P_pool0 | 8 | 2 | 0 | -40.6 % | -44.4 % | 12 % | -0.324 | n/a to n/a | 0.324 | 0 | 0 | 365 | 325 |
| S2 | P_pool0_top30 | 37 | 15 | 0 | +7.7 % | +18.5 % | 81 % | +0.286 | -6.5 % to +19.1 % | 0.284 | 0 | 266 | 365 | 30 |
| S4 | P_pool5_top30 | 87 | 34 | 0 | +3.6 % | +15.7 % | 78 % | +0.310 | -2.2 % to +9.6 % | 0.291 | 0 | 335 | 274 | 2 |
| A1 | P_pool0_top30t | 52 | 21 | 0 | +1.8 % | +18.1 % | 73 % | +0.093 | -8.3 % to +11.7 % | 0.296 | 0 | 247 | 365 | 34 |
| A2 | P_pool5_top30t | 71 | 21 | 0 | +4.9 % | +17.1 % | 70 % | +0.345 | -2.4 % to +11.9 % | 0.213 | 0 | 290 | 274 | 63 |
| T1 | P_hot5 | 24 | 11 | 0 | +3.6 % | -5.1 % | 29 % | +0.086 | -3.4 % to +9.2 % | 0.044 | 0 | 953 | 0 | 1 |
| T2 | P_fresh3 | 14 | 2 | 0 | -19.8 % | -10.9 % | 36 % | -0.277 | n/a to n/a | 0.277 | 0 | 0 | 0 | 507 |
| T3 | P_pool0_heat | 40 | 8 | 0 | -7.9 % | -2.0 % | 45 % | -0.317 | n/a to n/a | 0.568 | 0 | 128 | 365 | 165 |

| book against X0 | mean difference | band (hours paired) | P&L difference SOL | total P&L higher | better | coins both entered | their difference | band |
|---|---|---|---|---|---|---|---|---|
| A1 vs X0 | +42.3 % | n/a to n/a | +0.417 | yes | no | 1 | +0.0 % | n/a to n/a |
| A2 vs X0 | +45.4 % | n/a to n/a | +0.670 | yes | no | 2 | +0.0 % | n/a to n/a |
| T1 vs X0 | +44.1 % | n/a to n/a | +0.410 | yes | no | 0 | n/a | n/a to n/a |
| T2 vs X0 | +20.7 % | n/a to n/a | +0.047 | yes | no | 6 | +18.9 % | n/a to n/a |
| T3 vs X0 | +32.6 % | n/a to n/a | +0.008 | yes | no | 4 | +0.0 % | n/a to n/a |

| book against the Y9 filter | mean difference | band (hours paired) | P&L difference SOL | total P&L higher | better | coins both entered | their difference | band |
|---|---|---|---|---|---|---|---|---|
| A1 vs S2 | -6.0 % | -18.5 % to +7.3 % | -0.194 | no | no | 27 | +0.0 % | +0.0 % to +0.0 % |
| A2 vs S4 | +1.3 % | -5.0 % to +7.5 % | +0.036 | yes | no | 43 | +0.0 % | +0.0 % to +0.0 % |

Exits: X0 stop 6, time 2; S2 stop 7, take 5, time 25; S4 stop 19, take 8, time 60; A1 stop 12, take 7, time 33; A2 stop 18, take 9, time 44; T1 stop 2, take 5, time 17; T2 stop 6, take 1, time 7; T3 stop 18, take 11, time 11

## 3. Out of sample, daily loss limit 1.0 SOL (the code's cap, judged)

| book | strategy | entries | hours | failed buys | mean | median | win | P&L SOL | band of mean | max DD SOL | no model | filtered out | no pool state | daily loss limit |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| X0 | P_pool0 | 319 | 38 | 12 | -2.8 % | +9.3 % | 53 % | -0.902 | -6.7 % to +1.1 % | 1.144 | 0 | 0 | 365 | 14 |
| S2 | P_pool0_top30 | 67 | 26 | 0 | +6.4 % | +17.7 % | 82 % | +0.427 | -2.3 % to +15.0 % | 0.302 | 0 | 266 | 365 | 0 |
| S4 | P_pool5_top30 | 89 | 34 | 0 | +4.0 % | +15.7 % | 79 % | +0.352 | -1.6 % to +9.6 % | 0.291 | 0 | 335 | 274 | 0 |
| A1 | P_pool0_top30t | 86 | 28 | 0 | -0.1 % | +16.4 % | 72 % | -0.006 | -6.9 % to +7.4 % | 0.433 | 0 | 247 | 365 | 0 |
| A2 | P_pool5_top30t | 134 | 34 | 0 | +7.2 % | +16.1 % | 76 % | +0.958 | +2.4 % to +11.9 % | 0.213 | 0 | 290 | 274 | 0 |
| T1 | P_hot5 | 25 | 11 | 0 | +5.8 % | -5.1 % | 32 % | +0.146 | -1.1 % to +11.2 % | 0.044 | 0 | 953 | 0 | 0 |
| T2 | P_fresh3 | 134 | 10 | 2 | -13.8 % | -1.0 % | 49 % | -1.847 | -25.0 % to -4.1 % | 1.847 | 0 | 0 | 0 | 387 |
| T3 | P_pool0_heat | 204 | 34 | 10 | -2.4 % | +8.0 % | 51 % | -0.498 | -7.7 % to +2.9 % | 1.229 | 0 | 128 | 365 | 1 |

| book against X0 | mean difference | band (hours paired) | P&L difference SOL | total P&L higher | better | coins both entered | their difference | band |
|---|---|---|---|---|---|---|---|---|
| A1 vs X0 | +2.8 % | -3.8 % to +9.5 % | +0.896 | yes | no | 82 | +0.0 % | +0.0 % to +0.0 % |
| A2 vs X0 | +10.0 % | +5.1 % to +14.9 % | +1.860 | yes | yes | 106 | -1.6 % | -3.6 % to +0.3 % |
| T1 vs X0 | +8.7 % | +0.4 % to +15.7 % | +1.047 | yes | yes | 2 | +81.5 % | n/a to n/a |
| T2 vs X0 | -11.0 % | -22.2 % to -1.4 % | -0.945 | no | no | 70 | -10.7 % | -17.4 % to -4.0 % |
| T3 vs X0 | +0.4 % | -2.7 % to +3.8 % | +0.404 | yes | no | 197 | +0.0 % | +0.0 % to +0.0 % |

| book against the Y9 filter | mean difference | band (hours paired) | P&L difference SOL | total P&L higher | better | coins both entered | their difference | band |
|---|---|---|---|---|---|---|---|---|
| A1 vs S2 | -6.4 % | -14.2 % to +1.1 % | -0.432 | no | no | 54 | +0.0 % | +0.0 % to +0.0 % |
| A2 vs S4 | +3.2 % | -0.9 % to +7.1 % | +0.606 | yes | no | 79 | +0.0 % | +0.0 % to +0.0 % |

Exits: X0 failed buy 12, stop 118, take 82, time 107; S2 stop 12, take 8, time 47; S4 stop 19, take 8, time 62; A1 stop 20, take 10, time 56; A2 stop 30, take 19, time 85; T1 stop 2, take 6, time 17; T2 failed buy 2, stop 57, take 30, time 45; T3 failed buy 10, stop 75, take 58, time 61

## 4. In sample (not judged)

| book | entries L25 | mean L25 | P&L SOL L25 | entries L100 | mean L100 | P&L SOL L100 |
|---|---|---|---|---|---|---|
| X0 | 38 | -7.0 % | -0.267 | 225 | +18.1 % | +4.064 |
| S2 | 0 | n/a | +0.000 | 0 | n/a | +0.000 |
| S4 | 0 | n/a | +0.000 | 0 | n/a | +0.000 |
| A1 | 0 | n/a | +0.000 | 0 | n/a | +0.000 |
| A2 | 0 | n/a | +0.000 | 0 | n/a | +0.000 |
| T1 | 38 | -1.3 % | -0.048 | 41 | -1.9 % | -0.076 |
| T2 | 26 | -18.1 % | -0.374 | 222 | -8.4 % | -1.774 |
| T3 | 17 | +42.6 % | +0.724 | 100 | -0.3 % | -0.029 |

Deflated probability of the daily P&L out of sample (n/a under 5 days): X0@L25 n/a, S2@L25 n/a, S4@L25 n/a, A1@L25 n/a, A2@L25 n/a, T1@L25 n/a, T2@L25 n/a, T3@L25 n/a, X0@L100 n/a, S2@L100 n/a, S4@L100 n/a, A1@L100 n/a, A2@L100 n/a, T1@L100 n/a, T2@L100 n/a, T3@L100 n/a

Models per day: 2026-10-21 ['et_alive5m'] (rows {'win0': 48, 'rug0': 48, 'win5': 65, 'rug5': 65, 'win0t': 48, 'rug0t': 48, 'win5t': 65, 'rug5t': 65}); 2026-10-22 ['win0', 'rug0', 'win5', 'rug5', 'win0t', 'rug0t', 'win5t', 'rug5t', 'et_alive5m'] (rows {'win0': 223, 'rug0': 223, 'win5': 283, 'rug5': 283, 'win0t': 223, 'rug0t': 223, 'win5t': 283, 'rug5t': 283}); 2026-10-23 ['win0', 'rug0', 'win5', 'rug5', 'win0t', 'rug0t', 'win5t', 'rug5t', 'et_alive5m'] (rows {'win0': 413, 'rug0': 413, 'win5': 517, 'rug5': 517, 'win0t': 413, 'rug0t': 413, 'win5t': 517, 'rug5t': 517}); 2026-10-24 ['win0', 'rug0', 'win5', 'rug5', 'win0t', 'rug0t', 'win5t', 'rug5t', 'et_alive5m'] (rows {'win0': 558, 'rug0': 558, 'win5': 709, 'rug5': 709, 'win0t': 558, 'rug0t': 558, 'win5t': 709, 'rug5t': 709})

## 5. What runs on paper

The five strategies are pipeline strategies (`_build_y10`), 0.1 SOL each, in the paper engine (its engine now has the
trend tracker) once the owner deploys the lab code. The daily study's two passes carry the tracker, so the label rows
(`rows/select.parquet`) and the early rows (`rows/early.parquet`) get the trend columns; the daily retrain then trains
`sel_win0t`, `sel_rug0t`, `sel_win5t`, `sel_rug5t` and `et_mig1h`, `et_peak3x`, `et_peak10x`, `et_alive5m` next to the
unchanged Y9 and X14 models (rows from before the change train no trend model). Until the first retrain after the
first study with the tracker, A1, A2 and T1 skip "no model"; T2 trades at once; T3 waits for 3 hours of the engine's
own heat history after every collector restart. Every strategy and rule that existed before trades exactly as before
(the recorded 2026-10-20: 18,440 closed trades and 1,022 failed buys identical field for field; and the synthetic
test). The live service builds its engine without the tracker and is unchanged. Trials: 10
(`strategies.TRENDS_Y10_TRIALS`).

The meme module (`lab/onchain/meme.py`): every candidate from our Trends file now carries its ranks (the place in the
hot list and in the fresh list), and the new paper rule `trend_top` buys a migrated coin ranked 5 or better in the hot
list or 3 or better in the fresh list, 5 minutes or more after its migration, without a `win_low` or `rug_risk` badge,
after the safety check (+30 %, -20 %, a 20 % trailing stop once +20 %, 1 h). It is judged by the meme module's own
pre-registered proof and counts as its fourth trial there; the three earlier rules spend the run's safety checks first
and trade as before.

## 6. Too early

Three days of record, 38 hours out of sample, models trained on 223 and 413 rows; deflated probabilities are n/a
(under 5 days). Under the live limit no book has ten hours of entries next to X0. A2 and T1 passing under the larger
limit is one look at one stretch of 38 hours among ten new trials, not evidence that they work.
