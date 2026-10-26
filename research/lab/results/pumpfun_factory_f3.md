# pump.fun factory F3: the first short search (30 trials, 2026-10-26)

The factory (`lab/pumpfun_rt/factory.py`, job `pumpfun-factory`, nightly 01:00 UTC, 300 trials) searches without any
language model: Optuna's TPE over the pipeline's building blocks, every trial a realistic book (R1's executor: the live
bot's latency, fills at landing, failures, fees) on the record, scored by a 0.55 SOL wallet bootstrap over the days its
models were trained before; the last 2 full days held back for the night's top 3. This is the proof run with 30 trials
(the R2 reference P_pool5_top30t at 10 %, 3 open, brake off as trial F3_00000), 6 model trials per label.

What it shows: on 2 scored days the search finds settings whose bootstrap compounds 0.55 SOL into 6 to 44 SOL, and all
three lose 80 % of the wallet on the 2 held-back days (P&L -0.5 to -1.9 SOL per 0.1 SOL entry stream). Nothing passed
the deflated bar (p 0.00 for every trial with 20 or more entries); no paper book was started. Two scored days are far
too few: the ledger and the bar are there so that the nights to come cannot fool us the same way. The LightGBM
settings of all five realistic labels beat the code's in 4 or 5 of 5 folds and on the held-back days (log loss
-0.001 to -0.003); in this run they went to a scratch folder, the nightly job adopts them for the daily retrain.

The report as written:

## factory.md

Night 2026-10-26: 30 strategy trials tonight, 30 in the ledger. Search days 2026-10-20, 2026-10-21, 2026-10-22, 2026-10-23 (scored: 2026-10-22, 2026-10-23), held back 2026-10-24, 2026-10-25. Every trial realistic (the live bot's latency, fills, failures, fees) on a 0.55 SOL wallet, 1,000 paths of 30 days.

The bar: a deflated Sharpe per entry with p at least 0.95 against 30 trials (the best of that many with no skill reaches 0.475), at least 20 entries and a median wallet above the start.

The night's best by the objective (median end wallet less the ruin penalty):

| trial | median after 30 days | 10 to 90 % | lost 80 % | entries | Sharpe | deflated p | strategy | sizing |
|---|---|---|---|---|---|---|---|---|
| F3_00013 | 43.961 SOL (3960.85 EUR) | 38.948 to 48.018 | 0 % | 73 | +0.073 | 0.00 | a pool in the top 3 of the fresh pools, 90 to 390 s after its migration; P(win5t) in its top 30 %; P(rug5t) at most 1.44x its base rate; pool SOL at least 103; Y16 R3 rug rule; +117 %; lock: once +21 % out at +4 %, once +41 % out at +21 %; stop -7 %, 180 s | 20 % of the wallet, at most 1 open, brake off |
| F3_00018 | 11.586 SOL (1043.91 EUR) | 3.655 to 25.496 | 0 % | 141 | +0.119 | 0.00 | PumpSwap, migration + 29 s; P(win5) in its top 30 %; P(rug5) at most 1.04x its base rate; the block list; +41 %; stop -5 %, 1058 s | 8 % of the wallet, at most 2 open, brake on |
| F3_00029 | 6.638 SOL (598.05 EUR) | 5.625 to 7.977 | 0 % | 87 | +0.079 | 0.00 | a pool in the top 4 of the fresh pools, 90 to 1110 s after its migration; P(win5) in its top 30 %; market heat at least 0.80x its 6 h median; Y16 R3 rug rule; 60 % at +11 %, the rest at +26 %; lock: once +10 % out at +2 %, once +19 % out at +10 %; stop -34 %, 485 s | 25 % of the wallet, at most 2 open, brake off |
| F3_00000 | 3.273 SOL (294.92 EUR) | 0.475 to 9.518 | 6 % | 221 | +0.034 | 0.00 | PumpSwap, migration + 5 s; P(win5t) in its top 30 %; +30 %; stop -20 %, 300 s | 10 % of the wallet, at most 3 open, brake off |
| F3_00022 | 2.749 SOL (247.64 EUR) | 1.417 to 4.634 | 0 % | 4 | +0.342 | 0.40 | PumpSwap, migration + 49 s, waiting up to 5 s for the pool's first trade; P(win5t) in its top 30 %; market heat at least 0.84x its 6 h median; 51+ distinct buyers; 55 % at +22 %, the rest at +48 %; stop -22 %, 311 s | 19 % of the wallet, at most 2 open, brake on |
| F3_00007 | 2.155 SOL (194.12 EUR) | 1.477 to 2.855 | 0 % | 1 | +0.000 | 0.00 | a pool in the top 4 of the fresh pools, 480 to 600 s after its migration; P(rug5t) at most 0.34x its base rate; market heat at least 1.53x its 6 h median; pool SOL at least 134; the block list; 41 % at +57 %, the rest at +116 %; stop -26 %, 938 s | 12 % of the wallet, at most 1 open, brake off |
| F3_00015 | 0.682 SOL (61.44 EUR) | 0.653 to 0.722 | 0 % | 1 | +0.000 | 0.00 | PumpSwap, migration + 28 s; P(win5) in its top 30 %; market heat at least 1.44x its 6 h median; 12+ distinct buyers; the block list; +25 %; lock: once +10 % out at +2 %, once +20 % out at +10 %; stop -38 %, 1719 s | 17 % of the wallet, at most 2 open, brake off |
| F3_00002 | 0.656 SOL (59.07 EUR) | 0.625 to 0.680 | 0 % | 1 | +0.000 | 0.00 | PumpSwap, migration + 0 s, waiting up to 5 s for the pool's first trade; P(win0t) in its top 30 %; P(rug0t) at most 1.24x its base rate; market heat at least 1.98x its 6 h median; pool SOL at least 79; Y16 R3 rug rule; the block list; 58 % at +35 %, the rest at +161 %; stop -40 %, 161 s | 14 % of the wallet, at most 1 open, brake off |
| F3_00014 | 0.602 SOL (54.24 EUR) | 0.589 to 0.610 | 0 % | 3 | +0.054 | 0.27 | PumpSwap, migration + 40 s; P(rug5) at most 0.34x its base rate; market heat at least 0.64x its 6 h median; pool SOL at least 105; 27+ distinct buyers; 68 % at +26 %, the rest at +125 %; stop -50 %, 1570 s | 19 % of the wallet, at most 2 open, brake on |
| F3_00001 | 0.550 SOL (49.55 EUR) | 0.550 to 0.550 | 0 % | 0 | +0.000 | 0.00 | a pool in the top 1 of the fresh pools, 450 to 1470 s after its migration; P(win5) at least 1.58x its base rate; market heat at least 1.06x its 6 h median; 38+ distinct buyers; Y16 R3 rug rule; 34 % at +20 %, the rest at +72 %; lock: once +19 % out at +4 %, once +39 % out at +19 %; stop -9 %, 366 s | 17 % of the wallet, at most 1 open, brake on |

Held back (scored once):

| trial | median after 30 days | lost 80 % | entries | P&L at 0.1 SOL |
|---|---|---|---|---|
| F3_00013 | 0.070 SOL (6.26 EUR) | 100 % | 102 | -0.535 SOL |
| F3_00018 | 0.056 SOL (5.02 EUR) | 100 % | 203 | -1.932 SOL |
| F3_00029 | 0.042 SOL (3.76 EUR) | 100 % | 135 | -0.975 SOL |

Winners tonight: none (nothing passed the bar and the held-back days).

Model settings (LightGBM, R2's realistic labels; adopted when better in 4 of 5 folds and on the held-back days):

| label | trials | log loss best | current | folds won | held back best | current | |
|---|---|---|---|---|---|---|---|
| win30 | 6 | 0.1603 | 0.1639 | 5 of 5 | 0.1536 | 0.1556 | adopted |
| win300 | 6 | 0.1582 | 0.1628 | 4 of 5 | 0.1527 | 0.1539 | adopted |
| up10 | 6 | 0.2551 | 0.2605 | 5 of 5 | 0.2475 | 0.2500 | adopted |
| up30 | 6 | 0.3192 | 0.3245 | 5 of 5 | 0.3176 | 0.3183 | adopted |
| up120 | 6 | 0.3573 | 0.3636 | 4 of 5 | 0.3543 | 0.3558 | adopted |

Adopted settings in use: win30 since 2026-10-26; win300 since 2026-10-26; up10 since 2026-10-26; up30 since 2026-10-26; up120 since 2026-10-26.

Factory paper books: none yet.

Paper only: nothing here trades real money.
