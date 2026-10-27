# pump.fun, the shape of a coin's first minutes (Y17): pre-registration (2026-10-27)

Written and committed before any number below was computed. Code: `lab/pumpfun_rt/shapes17.py` (the sequences, the
labels, the analog search, the sequence model, the twins), tests `tests/test_pumpfun_shapes_y17.py`. Paper only:
nothing here holds a wallet, reads a key, signs or sends anything; no paper book, no model the books read and not the
live bot (switched off, it stays off) changes. A change to anything below after the first result is a new trial with
a new name.

## Why

X14 (`early.py`) and Y10 (`et_<label>`) describe a coin's first seconds by numbers at one moment (buys in the last
5 s, curve speed, holders, the top-10 share, the trend ranks). Y9 to Y16 decide at the migration on the curve's last
minutes as sums. None looks at the path itself: a coin that rises in steps with many small buyers and one that jumps
on one wallet and drifts can end with the same sums. Y17 asks whether the shape of the first 10, 30, 60 and 120 s,
as a sequence, tells more than those numbers.

## What was looked at before this plan

Disclosed: the reports of X14, Y9 to Y16, R1, R2, F3 and A1; the schemas and row counts of the record (2026-10-20 to
2026-10-27) and of `rows/early.parquet` (about 103,000 coins with rows at 5 to 60 s); the paper ledger's realistic
books since 2026-10-24 by total P&L, mean and median return per trade (P_pool0_wait_norug +20.7 % a trade over 242,
P_pool5_top30t_sw10o3n -1.0 % over 155). No sequence was built, no label of this plan computed, no model fitted.

## 1. The sequences

For every coin with an early row at 10 s (`rows/early.parquet`, not dropped for a gap) and every coin a twin's base
book signalled, one value per second s = 0 .. H-1 for H = 10, 30, 60 and 120, from the curve trades the collector had
**received** by the end of second s after the creation was received (receive time, not slot time: what we knew
then; a trade delivered late counts in the second it arrived, the price is the state of the latest slot received):
log price over the curve's starting price, log(1 + buys), log(1 + sells), log(1 + buy SOL), log(1 + sell SOL) in the
second, log(1 + unique buyers so far), log(1 + the creator's buy SOL) and log(1 + its sell SOL) in the second,
log(1 + sell SOL of the five largest holders other than the creator, as they were at the start of the second), their
share of the supply and the creator's at the end of the second, the curve's progress. 12 channels, nothing else.

## 2. The labels (from the decision at H, the price there the last known)

- `mig`: the curve completes within 1 h of the creation (rows whose curve completed before H are left out).
- `rug`: within 10 minutes after H the price (curve or pool) falls to half the price at H or below.
- `peak`: log of the highest price within 1 h after H over the price at H, the price at H included (so at least
  0; 0 without a later trade).
- `exit_s`: the second after H (0 to 600) of the highest price within 10 minutes (0 when none is above the price
  at H). Both clarified before the first run, with the code.

## 3. The models, walk-forward by UTC day

Test days 2026-10-22 to 2026-10-26; for each, everything trained on the coins of the days before whose label window
(H + 1 h) closed before the day's start (the embargo by time). Per H:

- **Analog**: each channel standardised on the training coins, block means to at most 20 points, PCA to 16 dims,
  the 50 nearest training coins by Euclidean distance; the prediction is their mean (`mig`, `rug`, `peak`) and median
  (`exit_s`).
- **CNN**: a 1D convolutional network in numpy (CPU; no torch in the image): two convolutions of 16 filters (width 5,
  the second dilated 2) with ReLU, the mean, max and last value over time, a dense layer of 32, four heads (two
  logistic, two squared error on standardised targets), Adam, batch 512, 6 epochs, seed fixed.
- **Baseline**: Y10's early model as the daily retrain fits it (`exitpol.fit_trend`'s features and `model.fit`'s
  LightGBM with isotonic; the same parameters as a regressor for `peak` and `exit_s`), on the early row of the same
  coin at the same H (at 120 s the 60 s row, the latest there is), on the same coins and the same training days.

Measures: AUC (`mig`, `rug`), Spearman (`peak`), mean absolute error and Spearman (`exit_s`), and the mean log price
reached when selling at the predicted exit second against the training median second. A model beats the baseline on
a label at an H when its difference has a 90 % band above zero (block bootstrap by UTC hour of the creation, 1,000
draws): 4 labels x 4 H x 2 models = 32 comparisons, Holm over them.

## 4. Realistic paper twins

Base books, from the paper ledger (R1's realistic execution on the live stream: the live bot's measured latency drawn
per trade, its fees and Sender tip, the live bounds), full UTC days 2026-10-24 to 2026-10-26, closed trades and
failed buys: (a) R2's pick `P_pool5_top30t_sw10o3n` and (b) the realistic book with the highest mean return per trade
among those with 100 trades or more (`P_pool0_wait_norug`, carrying Y16's rug model). Each twin skips an entry where
the CNN of that day (trained on the days before) at the largest H not after the coin's age at the signal says
**V1**: P(rug) above the 80th percentile of its training coins' predictions at that H, or **V2**: the predicted peak
below their 20th percentile. A coin younger than 10 s at the signal keeps its entry. 4 trials. The twin is the base's
trades less the skipped (a freed slot is not refilled, stated as a limit).

Judged by R2's bar: (1) the mean P&L per entry at 0.1 SOL (failed buys included) has a 90 % day-bootstrap band above
zero; (2) the mean wallet after 30 days of R2's bootstrap (2,000 paths over the three days, 0.55 SOL, 10 % a trade,
3 open, brake off, `smallwallet.simulate`) above the start; and against its base (3) the skipped entries' P&L at
0.1 SOL has a 90 % band (hour blocks) below zero and (4) the median wallet after 30 days is above the base's. All
four or no.

The report `results/pumpfun_shapes_y17.md` says what passes and what does not; nothing goes live either way.
