# pump.fun, the shape of a coin's first minutes (Y17): result (2026-10-27)

Pre-registered in `results/pumpfun_shapes_y17_prereg.md` (committed before any sequence was built; the `peak` and
`exit_s` definitions clarified with the code before the first run). Code `lab/pumpfun_rt/shapes17.py`, tests
`tests/test_pumpfun_shapes_y17.py`. Reproduce: `python -m lab.pumpfun_rt.shapes17 build --out DIR`, then `run --out
DIR` (about 35 minutes on the lab server's CPU, under the heavy lock). Paper only. The live bot is off and stays off;
no paper book, no model the books read and nothing live changes.

## The answer

- **The shape of the first 10 to 120 s does not tell more than where the coin already is.** The CNN beats Y10's early
  model on `rug` at every H and, at 120 s only, on `mig`, `peak` and `exit_s` (Holm over 32 comparisons). But one
  number does as well or better: the log price at H alone ranks `rug` at AUC 0.991 to 0.992 (CNN 0.987 to 0.989) and
  the curve's progress alone ranks `mig` at 0.953 to 0.979 (CNN 0.931 to 0.970), on all coins and on the coins that
  moved. The labels are mostly "has it run already": half the test coins never rose 5 % by 10 s and none of them
  rugged. The baseline's calibrated scores (isotonic steps, ties) lose some AUC against both.
- **Where the shape helps a little: the peak of coins that moved, at 120 s.** On the coins up 5 % or more at H the CNN
  and the analog search rank the 1 h peak at Spearman 0.54 against the baseline's 0.49 and the price level's 0.47
  (not registered, no band). At 10 to 60 s the baseline ranks it better (0.49 to 0.56 against 0.42 to 0.53).
- **The best exit second cannot be timed.** Selling at the second any model predicts gets less than selling at once
  at H (mean log price -0.008 to -0.044 against 0); holding 600 s gets -0.06 to -0.13. The analog search "wins" the
  registered measure (mean absolute error) because its prediction is a median and the CNN and LightGBM fit a mean:
  a flaw of the measure, not an edge.
- **The twins: no.** Every entry of R2's pick `P_pool5_top30t_sw10o3n` comes before a 10 s shape exists (the coins
  migrate within seconds of their creation and the creation is often received after the migration), so its twins
  are the base itself. On `P_pool0_wait_norug` 58 of 223 entries have a shape; V1 (P(rug) in the top 20 %) skips 55
  of them, 19 winners among them, skipped P&L -0.275 SOL at 0.1 SOL a trade with a band of -0.640 to +0.094: it
  fails (3) of R2's bar. V2 skips nothing (a migrating coin's predicted peak is never in the bottom 20 %). V1 is in
  effect "skip coins older than 30 s at the migration", an age rule rather than a shape.

## Setup

86,968 coins created 2026-10-20 to 2026-10-27 (86,725 with an early row at 10 s, the rest the base books' coins),
12 channels a second from the curve trades as received. Test days 2026-10-22 to 2026-10-26, 11,274 to 13,478 coins
a day, trained on 19,472 to 68,941 coins of the days before whose label window had closed. Base rates on the coins
with a row: `mig` 0.6 to 0.8 %, `rug` 3.2 to 5.7 %, mean `peak` 0.05 to 0.12 (log), mean `exit_s` 35 to 43 s. The
baseline is Y10's early model (`exitpol.trend_features`, `model.fit`) on the same coins' early rows; at 120 s it reads
the 60 s row, the latest there is.

## 1. The models against Y10's early model (registered)

Measures on the test coins every model predicted; bands from 1,000 hour-block draws; "beats" needs Holm and the band
above zero.

| H | label | measure | test coins | rate | CNN | analog | baseline (Y10 early) | CNN - base | band | beats | analog - base | band | beats |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 10 | mig | AUC | 61,177 | 0.008 | 0.931 | 0.857 | 0.933 | -0.002 | -0.011 to +0.007 | no | -0.076 | -0.091 to -0.062 | no |
| 10 | rug | AUC | 61,186 | 0.059 | 0.987 | 0.984 | 0.978 | +0.009 | +0.008 to +0.011 | yes | +0.006 | +0.004 to +0.008 | yes |
| 10 | peak | Spearman | 61,186 |  | 0.553 | 0.551 | 0.575 | -0.021 | -0.025 to -0.018 | no | -0.024 | -0.027 to -0.020 | no |
| 10 | exit_s | minus MAE (s) | 61,186 |  | -58.002 | -43.400 | -57.028 | -0.974 | -1.513 to -0.466 | no | +13.628 | +13.188 to +14.038 | yes |
| 30 | mig | AUC | 61,153 | 0.008 | 0.949 | 0.903 | 0.937 | +0.012 | +0.005 to +0.021 | no | -0.034 | -0.047 to -0.022 | no |
| 30 | rug | AUC | 61,186 | 0.055 | 0.988 | 0.983 | 0.977 | +0.011 | +0.009 to +0.013 | yes | +0.006 | +0.004 to +0.008 | yes |
| 30 | peak | Spearman | 61,186 |  | 0.497 | 0.525 | 0.533 | -0.036 | -0.042 to -0.030 | no | -0.008 | -0.012 to -0.004 | no |
| 30 | exit_s | minus MAE (s) | 61,186 |  | -56.644 | -41.624 | -55.631 | -1.013 | -1.557 to -0.457 | no | +14.008 | +13.543 to +14.452 | yes |
| 60 | mig | AUC | 61,108 | 0.007 | 0.958 | 0.925 | 0.945 | +0.013 | +0.004 to +0.022 | no | -0.020 | -0.032 to -0.008 | no |
| 60 | rug | AUC | 61,186 | 0.045 | 0.988 | 0.986 | 0.966 | +0.022 | +0.019 to +0.026 | yes | +0.020 | +0.016 to +0.024 | yes |
| 60 | peak | Spearman | 61,186 |  | 0.461 | 0.499 | 0.501 | -0.040 | -0.048 to -0.031 | no | -0.002 | -0.008 to +0.004 | no |
| 60 | exit_s | minus MAE (s) | 61,186 |  | -56.724 | -39.512 | -54.230 | -2.494 | -3.091 to -1.901 | no | +14.719 | +14.102 to +15.250 | yes |
| 120 | mig | AUC | 61,025 | 0.006 | 0.970 | 0.937 | 0.951 | +0.019 | +0.009 to +0.030 | yes | -0.014 | -0.027 to -0.000 | no |
| 120 | rug | AUC | 61,186 | 0.034 | 0.989 | 0.987 | 0.969 | +0.020 | +0.018 to +0.022 | yes | +0.018 | +0.016 to +0.020 | yes |
| 120 | peak | Spearman | 61,186 |  | 0.441 | 0.459 | 0.412 | +0.029 | +0.021 to +0.039 | yes | +0.048 | +0.041 to +0.054 | yes |
| 120 | exit_s | minus MAE (s) | 61,186 |  | -50.527 | -34.948 | -51.390 | +0.863 | +0.347 to +1.405 | yes | +16.442 | +15.927 to +16.938 | yes |


## 2. One number against the models (not registered)

| H | label | coins | n | rate | one number | CNN | analog | baseline |
|---|---|---|---|---|---|---|---|---|
| 10 | mig | all | 61,177 | 0.008 | 0.953 | 0.931 | 0.857 | 0.933 |
| 10 | mig | moved | 30,337 | 0.017 | 0.914 | 0.885 | 0.835 | 0.890 |
| 10 | rug | all | 61,186 | 0.059 | 0.992 | 0.987 | 0.984 | 0.978 |
| 10 | rug | moved | 30,346 | 0.119 | 0.982 | 0.972 | 0.968 | 0.956 |
| 10 | peak | all | 61,186 | n/a | 0.530 | 0.553 | 0.551 | 0.575 |
| 10 | peak | moved | 30,346 | n/a | 0.367 | 0.450 | 0.422 | 0.491 |
| 30 | mig | all | 61,153 | 0.008 | 0.967 | 0.949 | 0.903 | 0.937 |
| 30 | mig | moved | 26,468 | 0.018 | 0.935 | 0.909 | 0.882 | 0.892 |
| 30 | rug | all | 61,186 | 0.055 | 0.991 | 0.988 | 0.983 | 0.977 |
| 30 | rug | moved | 26,501 | 0.126 | 0.979 | 0.971 | 0.963 | 0.954 |
| 30 | peak | all | 61,186 | n/a | 0.523 | 0.497 | 0.525 | 0.533 |
| 30 | peak | moved | 26,501 | n/a | 0.422 | 0.509 | 0.478 | 0.526 |
| 60 | mig | all | 61,108 | 0.007 | 0.972 | 0.958 | 0.925 | 0.945 |
| 60 | mig | moved | 22,755 | 0.019 | 0.947 | 0.914 | 0.905 | 0.907 |
| 60 | rug | all | 61,186 | 0.045 | 0.991 | 0.988 | 0.986 | 0.966 |
| 60 | rug | moved | 22,833 | 0.121 | 0.974 | 0.966 | 0.963 | 0.941 |
| 60 | peak | all | 61,186 | n/a | 0.506 | 0.461 | 0.499 | 0.501 |
| 60 | peak | moved | 22,833 | n/a | 0.456 | 0.533 | 0.523 | 0.562 |
| 120 | mig | all | 61,025 | 0.006 | 0.979 | 0.970 | 0.937 | 0.951 |
| 120 | mig | moved | 19,147 | 0.018 | 0.955 | 0.925 | 0.919 | 0.904 |
| 120 | rug | all | 61,186 | 0.034 | 0.992 | 0.989 | 0.987 | 0.969 |
| 120 | rug | moved | 19,308 | 0.107 | 0.971 | 0.963 | 0.963 | 0.920 |
| 120 | peak | all | 61,186 | n/a | 0.471 | 0.441 | 0.459 | 0.412 |
| 120 | peak | moved | 19,308 | n/a | 0.468 | 0.541 | 0.544 | 0.489 |


## 3. Selling at the predicted second (registered, descriptive)

Mean log price over the price at H when selling at each model's predicted second (on a 10 s grid), at the median best
second of the coins before the test days (0 s: most coins only fall after H) and at the true best second (the
ceiling).

| H | best second (ceiling) | CNN | analog | baseline | median second of the days before | hold 600 s |
|---|---|---|---|---|---|---|
| 10 | +0.067 | -0.044 | -0.012 | -0.037 | +0.000 (0 s) | -0.126 |
| 30 | +0.052 | -0.034 | -0.011 | -0.027 | +0.000 (0 s) | -0.101 |
| 60 | +0.041 | -0.022 | -0.009 | -0.019 | +0.000 (0 s) | -0.079 |
| 120 | +0.029 | -0.015 | -0.008 | -0.009 | +0.000 (0 s) | -0.059 |


## 4. Realistic paper twins (registered), R2's bar

The base books' trades from the paper ledger, signalled 2026-10-24 to 2026-10-26: R1's realistic execution on the
live stream (the live bot's measured latency drawn per trade, its fees and Sender tip, its bounds), closed trades at
their return on the book's own stake, failed buys at their fee. Each closed trade's pool SOL at the buy and the sale
from the record, so the wallet bootstrap scales the impact and caps the stake at 2 % of the pool as R2 does; 2,000
paths of 30 days over the three days, 0.55 SOL, 10 % a trade, 3 open, brake off. The twin is the base less what it
skips; a freed slot is not refilled.

| book | entries | skipped | no shape | winners skipped | mean P&L per entry at 0.1 SOL | band | skipped P&L SOL | its band | 30-day median wallet | mean | ruin | passes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| P_pool5_top30t_sw10o3n | 128 | | | | -0.0007 | -0.004 to +0.004 | | | 0.07 | 0.18 | 75 % | base |
| P_pool5_top30t_sw10o3n V1 | 128 | 0 | 128 | 0 | -0.0007 | -0.004 to +0.004 | +0.000 | n/a | 0.07 | 0.18 | 75 % | no |
| P_pool5_top30t_sw10o3n V2 | 128 | 0 | 128 | 0 | -0.0007 | -0.004 to +0.004 | +0.000 | n/a | 0.07 | 0.18 | 75 % | no |
| P_pool0_wait_norug | 223 | | | | +0.0208 | +0.011 to +0.032 | | | 529.73 | 527.26 | 0 % | base |
| P_pool0_wait_norug V1 | 168 | 55 | 165 | 19 | +0.0292 | +0.017 to +0.043 | -0.275 | -0.640 to +0.094 | 600.86 | 599.79 | 0 % | no |
| P_pool0_wait_norug V2 | 223 | 0 | 165 | 0 | +0.0208 | +0.011 to +0.032 | +0.000 | n/a | 529.73 | 527.26 | 0 % | no |


Shapes at the signal (the largest H not after the coin's age, counted from the creation's receipt):
`P_pool5_top30t_sw10o3n` none of 128; `P_pool0_wait_norug` 3 at 30 s, 4 at 60 s, 51 at 120 s, 165 none.

The wallets are three days repeated ten times. `P_pool0_wait_norug`'s +22.6 % per closed trade on those days
compounds to a median of 530 SOL at the 2 % pool cap; R2's two days had the same family negative. They are not a
forecast. `P_pool5_top30t_sw10o3n` was flat on these days (-0.0007 SOL per entry at 0.1 SOL) and is ruined on 75 % of
the paths at this sizing.

## Limits

- Five test days; the twins three days and 58 entries with a shape.
- Receive time is what we knew then. It makes the shapes late against the chain (the creation is received a median
  1.5 s after the signal on `P_pool5_top30t`'s coins, and the signal comes 5 s after the migration), so a slot-timed
  shape would exist for more entries. It would also be a little optimistic.
- The CNN is small (two convolutions, 6 epochs, no tuning) and runs in numpy because the image has no torch; there
  was no GPU worker. A bigger model was not tried. Nothing above says it would get past the one-number references.
- The `rug` label is half the price gone within 10 minutes. On the curve that mostly happens to coins that have
  already risen, which is why the price level ranks it so well.

## What it means

Nothing changes. The sequence adds no information a book could use beyond the price and progress the engine already
has. The one lead is the 120 s peak ranking on coins that moved; it would need its own pre-registered curve-entry
book, and Y13 and the `P_early` books lost on the curve at our latency.
