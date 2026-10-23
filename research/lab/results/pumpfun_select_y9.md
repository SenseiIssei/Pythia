# Which coins to buy at the migration (Y9)

PAPER ONLY. Nothing here holds a wallet, reads a key, signs or sends anything; the live service, its executor, its
sizing and its confirmation file were not touched. The live executor's files were only read.

Pre-registration: `results/pumpfun_select_y9_prereg.md` (10 trials, committed before the first replay). Code:
`lab/pumpfun_rt/select9.py` (the run), `selfeat.py` (decision features, label book), `selmodel.py` (models), the
strategies in `pipeline._build_y9`; tests: `tests/test_pumpfun_select_y9.py`. Data: the server's record,
2026-10-20 16:40 UTC to the registered cutoff 2026-10-23 08:00 UTC, entries to 07:45 UTC. One replay, 291 s.

## Short answer

**No filter is better than P_pool0 by the registered rule, under either daily loss limit.** The models were first
allowed on 2026-10-22 (the first day with 200 training rows), so out of sample is 2026-10-22 00:00 to 2026-10-23
07:45 UTC, about 32 hours and 259 migrations P_pool0 could enter.

- Under the live limit of 0.25 SOL X0 stopped for the day after its first stops (8 entries in 2 hours, -40.6 % per
  entry): no band of the difference exists (under 10 hours of X0 entries), so the answer is no by the rule. The
  filters lost less or won (S2 +7.7 %, S3 +8.5 %, S4 +4.1 % per entry, +0.25 to +0.29 SOL), mostly because they
  enter rarely and so do not hit the limit early.
- Under 1.0 SOL (registered, also judged) the three "top 30 %" filters lean the right way but do not pass: S2
  (P(win) in the top 30 %) +6.5 % per entry against X0's -2.0 % (difference +8.5 points, band -1.7 to +18.1), S3
  +8.8 points (band -2.3 to +20.0), S4 (5 s after the migration) +6.1 points (band -0.7 to +13.0). S1 (P(rug) under
  its base rate) is X0 with a fifth of its entries removed and the same mean (-0.3 points). S5 (two smart early
  buyers) leans negative (-3.5 points).
- The models rank somewhat: walk-forward AUC 0.66 (win0), 0.67 (win5), 0.61 to 0.64 (rug); the logistic baseline is
  as good on win and better on rug (0.70). The rug probabilities are badly calibrated (Brier skill below zero), so
  "under the base rate" removes few rugs. A rug within 60 s is rare at the pool's first state (7 %).

Nothing is recommended for the live bot. The five run as paper strategies from the deploy on. The top-30 %
filters' bands reach about 10 points either side of their difference with about 50 entries in 32 hours; if the
lean held, a few more days of paper would decide it, and two weeks would show whether it holds at all.

## 1. The models, walk-forward by day

Each day tested by models trained on the days before (rows decided 15 minutes before the day's start). Mean return
columns: the label book's P_pool0 return of every tested row, of those the filter would let through (top 30 % of
P(win), or P(rug) under the base rate), with no slot or loss limit.

| label | rows tested | rate | AUC | logistic AUC | Brier skill | logistic Brier skill | mean return, all | top 30 % | under the base rate |
|---|---|---|---|---|---|---|---|---|---|
| win0 | 259 | 52.1 % | 0.664 | 0.675 | +0.066 | +0.054 | -2.0 % | +6.5 % (51) | -7.5 % (126) |
| rug0 | 259 | 6.9 % | 0.611 | 0.697 | -0.137 | -0.458 | -2.0 % | +3.8 % (127) | -2.3 % (201) |
| win5 | 330 | 52.1 % | 0.674 | 0.669 | +0.076 | +0.054 | -2.3 % | +4.1 % (67) | -7.6 % (179) |
| rug5 | 330 | 6.7 % | 0.638 | 0.670 | -0.041 | -0.307 | -2.3 % | +4.1 % (96) | -2.3 % (288) |

| label | day | trained on | tested | AUC | logistic AUC | rate | base | top threshold |
|---|---|---|---|---|---|---|---|---|
| win0 | 2026-10-20 | 0 | 52 | no model | | | | |
| win0 | 2026-10-21 | 48 | 173 | no model | | | | |
| win0 | 2026-10-22 | 223 | 189 | 0.694 | 0.661 | 51.3 % | 52.0 % | 0.705 |
| win0 | 2026-10-23 | 413 | 70 | 0.601 | 0.697 | 54.3 % | 51.3 % | 0.663 |
| rug0 | 2026-10-20 | 0 | 52 | no model | | | | |
| rug0 | 2026-10-21 | 48 | 173 | no model | | | | |
| rug0 | 2026-10-22 | 223 | 189 | 0.573 | 0.660 | 6.9 % | 9.9 % | 0.037 |
| rug0 | 2026-10-23 | 413 | 70 | 0.726 | 0.852 | 7.1 % | 8.5 % | 0.028 |
| win5 | 2026-10-20 | 0 | 69 | no model | | | | |
| win5 | 2026-10-21 | 65 | 216 | no model | | | | |
| win5 | 2026-10-22 | 283 | 233 | 0.667 | 0.643 | 51.5 % | 48.8 % | 0.673 |
| win5 | 2026-10-23 | 517 | 97 | 0.694 | 0.723 | 53.6 % | 49.7 % | 0.651 |
| rug5 | 2026-10-20 | 0 | 69 | no model | | | | |
| rug5 | 2026-10-21 | 65 | 216 | no model | | | | |
| rug5 | 2026-10-22 | 283 | 233 | 0.640 | 0.665 | 6.9 % | 8.5 % | 0.047 |
| rug5 | 2026-10-23 | 517 | 97 | 0.650 | 0.701 | 6.2 % | 7.7 % | 0.027 |

## 2. Out of sample, daily loss limit 0.25 SOL (live, judged)

Latency buy 9.8 s median (1.0 to 38.0), sale 3.9 s (1.0 to 30.0), 0.001005 SOL per transaction, 0.1 SOL, 4 slots,
trades open across a gap kept. "Filtered out": the model (or smart-wallet) filter said no; "no pool state": no pool
trade seen at the signal.

| book | strategy | entries | hours | failed buys | mean | median | win | P&L SOL | band of mean | max DD SOL | no model | filtered out | no pool state | daily loss limit |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| X0 | P_pool0 | 8 | 2 | 0 | -40.6 % | -44.4 % | 12 % | -0.324 | n/a to n/a | 0.324 | 0 | 0 | 297 | 251 |
| S1 | P_pool0_norug | 29 | 7 | 4 | -10.0 % | -1.0 % | 38 % | -0.291 | n/a to n/a | 0.401 | 0 | 58 | 297 | 172 |
| S2 | P_pool0_top30 | 37 | 15 | 0 | +7.7 % | +18.5 % | 81 % | +0.286 | -6.5 % to +19.1 % | 0.284 | 0 | 208 | 297 | 14 |
| S3 | P_pool0_norug_top30 | 29 | 12 | 0 | +8.5 % | +17.8 % | 79 % | +0.248 | -7.8 % to +22.1 % | 0.273 | 0 | 216 | 297 | 14 |
| S4 | P_pool5_top30 | 67 | 28 | 0 | +4.1 % | +15.8 % | 79 % | +0.273 | -2.8 % to +11.1 % | 0.291 | 0 | 263 | 226 | 0 |
| S5 | P_pool0_smart2 | 10 | 7 | 0 | -30.0 % | -39.0 % | 30 % | -0.300 | n/a to n/a | 0.300 | 0 | 207 | 297 | 42 |

| book | mean difference vs X0 | band (hours paired) | P&L difference SOL | total P&L higher | better than X0 | migrations both entered | their difference | band |
|---|---|---|---|---|---|---|---|---|
| S1 | +30.5 % | n/a to n/a | +0.034 | yes | no | 6 | +0.0 % | n/a to n/a |
| S2 | +48.3 % | n/a to n/a | +0.611 | yes | no | 1 | +0.0 % | n/a to n/a |
| S3 | +49.1 % | n/a to n/a | +0.572 | yes | no | 1 | +0.0 % | n/a to n/a |
| S4 | +44.6 % | n/a to n/a | +0.597 | yes | no | 1 | -0.3 % | n/a to n/a |
| S5 | +10.6 % | n/a to n/a | +0.025 | yes | no | 1 | +0.0 % | n/a to n/a |

Exits: X0 stop 6, time 2; S1 failed buy 4, stop 11, take 5, time 9; S2 stop 7, take 5, time 25; S3 stop 6, take 5, time 18; S4 stop 13, take 7, time 47; S5 stop 7, take 3

## 3. Out of sample, daily loss limit 1.0 SOL (the code's cap, judged)

| book | strategy | entries | hours | failed buys | mean | median | win | P&L SOL | band of mean | max DD SOL | no model | filtered out | no pool state | daily loss limit |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| X0 | P_pool0 | 259 | 32 | 12 | -2.0 % | +9.3 % | 52 % | -0.520 | -6.4 % to +2.5 % | 0.842 | 0 | 0 | 297 | 0 |
| S1 | P_pool0_norug | 201 | 32 | 10 | -2.3 % | +6.1 % | 52 % | -0.461 | -6.5 % to +1.9 % | 0.785 | 0 | 58 | 297 | 0 |
| S2 | P_pool0_top30 | 51 | 21 | 0 | +6.5 % | +17.8 % | 82 % | +0.333 | -4.6 % to +16.6 % | 0.302 | 0 | 208 | 297 | 0 |
| S3 | P_pool0_norug_top30 | 43 | 18 | 0 | +6.8 % | +17.4 % | 81 % | +0.294 | -5.1 % to +18.5 % | 0.291 | 0 | 216 | 297 | 0 |
| S4 | P_pool5_top30 | 67 | 28 | 0 | +4.1 % | +15.8 % | 79 % | +0.273 | -2.8 % to +11.1 % | 0.291 | 0 | 263 | 226 | 0 |
| S5 | P_pool0_smart2 | 52 | 21 | 3 | -5.5 % | -1.0 % | 48 % | -0.286 | -15.1 % to +3.6 % | 0.288 | 0 | 207 | 297 | 0 |

| book | mean difference vs X0 | band (hours paired) | P&L difference SOL | total P&L higher | better than X0 | migrations both entered | their difference | band |
|---|---|---|---|---|---|---|---|---|
| S1 | -0.3 % | -3.4 % to +2.7 % | +0.059 | yes | no | 201 | +0.0 % | +0.0 % to +0.0 % |
| S2 | +8.5 % | -1.7 % to +18.1 % | +0.853 | yes | no | 51 | +0.0 % | +0.0 % to +0.0 % |
| S3 | +8.8 % | -2.3 % to +20.0 % | +0.814 | yes | no | 43 | +0.0 % | +0.0 % to +0.0 % |
| S4 | +6.1 % | -0.7 % to +13.0 % | +0.793 | yes | no | 57 | -1.3 % | -3.0 % to -0.2 % |
| S5 | -3.5 % | -13.0 % to +5.0 % | +0.234 | yes | no | 52 | +0.0 % | +0.0 % to +0.0 % |

Exits: X0 failed buy 12, stop 93, take 66, time 88; S1 failed buy 10, stop 69, take 44, time 78; S2 stop 9, take 6, time 36; S3 stop 8, take 6, time 29; S4 stop 13, take 7, time 47; S5 failed buy 3, stop 25, take 24

On the migrations both entered the filters take exactly X0's trade (difference 0, as the label book was built to
do); S4 enters 5 s later and loses 1.3 points on those, made up by entering migrations X0 skipped for want of a pool
state (226 skips against 297) and by its choice.

## 4. In sample (not judged)

| book | entries L25 | mean L25 | P&L SOL L25 | entries L100 | mean L100 | P&L SOL L100 |
|---|---|---|---|---|---|---|
| X0 | 38 | -7.0 % | -0.267 | 225 | +18.1 % | +4.064 |
| S1 | 0 | n/a | +0.000 | 0 | n/a | +0.000 |
| S2 | 0 | n/a | +0.000 | 0 | n/a | +0.000 |
| S3 | 0 | n/a | +0.000 | 0 | n/a | +0.000 |
| S4 | 0 | n/a | +0.000 | 0 | n/a | +0.000 |
| S5 | 16 | -5.0 % | -0.081 | 23 | -5.3 % | -0.121 |

S1 to S4 have no in-sample entries (no model before 2026-10-22). X0's in-sample half at 1.0 SOL was +18.1 % per
entry; the out-of-sample half -2.0 %: the plain strategy's edge did not hold, which is the reason for Y9.

## 5. What runs on paper

The five strategies are pipeline strategies (`_build_y9`), 0.1 SOL each, and run on paper once the owner deploys the
lab code. The daily study (`pumpfun-rt-study`) now writes the label rows of its record (`rows/select.parquet`) and
trains in-sample select models for its own judgement; the daily retrain (`pumpfun-rt-retrain`) trains the four models
on every row and saves them where the paper books read them (`models/pumpfun_rt/sel_*.json`), with the walk-forward
report in `reports/pumpfun_rt/select.md`. Until the first retrain after the deploy, S1 to S4 skip "no model". Every
strategy and rule that existed before trades exactly as before (the recorded 2026-10-20, 18,205 closed trades and
1,013 failed buys identical field for field, and the synthetic test). Trials: 10 (`strategies.SELECT_Y9_TRIALS`).

## 6. Too early

Two and a half days of record, 32 hours out of sample, models trained on 223 and 413 rows. Deflated probabilities
are n/a (under 5 days). The lean of the top-30 % filters is the one number worth watching on paper.
