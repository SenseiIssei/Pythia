# Meta-labeling the daily breakout book (C14)

`python -m lab.experiments.meta_daily`

## Pre-registration (written before the first run)

**Question.** The hourly meta-label failed (AUC 0.52, `meta`). The daily
breakout book `breakout_top10` (Donchian 20/10 on the 10 most liquid coins of
each day, no regime) is the lab's most robust family but its number is
unproven, and ten trades carry most of its P&L. Can a classifier, using only
what is known at the entry close, tell the entries that end profitable after
costs from the ones that do not, well enough that skipping or sizing entries
by its probability improves the book out of sample?

**Panel.** The sweep's survivorship-free daily panel (`fam_common`), rebuilt
from Binance 1h archives of every USDT pair ever listed, delisted ones
included, reused tickers split into segments. The book is the sweep's own
weight function and simulator; with no filter it must reproduce
`fam_breakout.breakout_weights` exactly (asserted).

**Events.** A breakout signal on day t for coin j: close above the highest
close of the previous 20 days, coin eligible and among the **30** most liquid
coins of that day (a wider set than the book's 10, so the model sees more
events of the same rule). Training events are taken per coin with the book's
state machine on that wider set (no new event while the coin's previous
breakout is still open), so training labels do not overlap within a coin.
Predictions are made for every signal cell (any day the rule fires on a top-30
coin), because a filtered book may skip a signal and see the coin fire again
the next day.

**Label.** The book's own exit: the trade enters at the close of day t and
exits at the first later close below the lowest close of the previous 10 days
(or at the coin's last close if its series ends). Label 1 when the trade's
return minus a 70 bps round trip (Alpaca taker 25 bps plus about 10 bps
slippage, per side) is above 0. Trades still open at the data's end have no
label and are never trained on. No triple barrier: the book's exit is what
the book earns, and one label keeps the trial count down.

**Features** (all known at the close of day t; 21):

- M2: the out-of-sample LambdaRank score of `picks.py` (same features and
  parameters, quarterly walk-forward from 2020-10 with the 7-day embargo,
  trained on all eligible coins) and its percentile rank among that day's
  eligible coins. Missing before 2020-10.
- Volatility: daily vol from 30 days of realised variance, 7-day over 30-day
  vol, today's realised vol over the 30-day level, and a HAR-style forecast
  (the mean of the 1, 7 and 30-day realised variance, as a vol). The hourly
  M1 model is not used: it is trained on 1-minute bars of today's 20 coins and
  does not exist for the delisted half of this panel.
- Breakout strength: log distance of the close above the 20-day high, in units
  of daily vol; position of the close in the 20-day range below it; today's
  return in vol units; 7 and 28-day returns; volume surge (today's quote volume
  over the mean of the 20 days before).
- Market: BTC close over its 200-day average, BTC 28-day return; breadth (share
  of the 50 most liquid coins above their 50-day average, share of the 30 most
  liquid firing a breakout the same day).
- Funding: the coin's perpetual funding summed over 7 days (missing where
  there is no perpetual) and the mean of that across the 20 most liquid coins.
- Coin: age in days, log 28-day mean quote volume, liquidity rank that day.

**Model.** LightGBM binary classifier, small and fixed before the run:
200 trees, learning rate 0.03, 7 leaves, at least 30 events per leaf,
subsample 0.8, column sample 0.8, L2 5. No tuning.

**Walk-forward.** Quarterly, first test quarter 2021-07. Purged: a fold
starting at s trains only on events whose exit (the label's end) is at least
10 days before s; embargo 10 days. Test: every signal cell inside the quarter.

**Calibration.** Isotonic regression fitted, per fold, on all earlier
out-of-sample predictions of training events whose labels were resolved 10
days before the fold starts (at least 100, else the raw probability is used).
Reported: Brier score against the training base rate, and a reliability table
by predicted decile.

**Uses (3 variants of the book, decided before the run).** p is the
calibrated probability, pbar the base rate of the fold's training events.

- **S1 skip below average:** take an entry only when p >= pbar.
- **S2 skip the worst quarter:** take an entry only when p is above the 25th
  percentile of the calibration set's calibrated predictions.
- **Z size by probability:** entry size times clip(p / pbar, 0, 1.5), size cap
  1.5 times the book's 1/10.

Everything else (exits, the 40 % vol sizing, top 10 by volume, no regime) is
the book's own.

**Measured.** Out of sample is **2024-01-01 to the data's end** (the lab's
split; the book's parameters were picked on 2020-08 to 2023). 2022 and 2023
are shown as well (the meta-model is walk-forward there too, but the book was
picked on them). Costs per unit of one-way turnover: 15 bps (Alpaca maker),
**35 bps (Alpaca taker plus slippage, the base)**, 41 bps (the lab's
pessimistic case). Per variant: Sharpe, CAGR, max drawdown, turnover, per-year
Sharpe; AUC on all out-of-sample events and on the book's actual entries, with
a 90 % event-block bootstrap band; random-skip null (the same skip rate drawn
at random 1000 times; for Z, the sizes shuffled among the same entries).

**Counted trials: 10 new**: S1, S2 and Z; for each of them a twin on the 15
coins Alpaca lists (top 10 of those by volume each day) and a fill a day late;
and the unfiltered book on the Alpaca coins, the twins' baseline. The pool is
the 265 before this study plus these 10: **275**. The prior's variance is
backed out of the fast-strategy study's bar (2.74 over 265) and pooled with
this study's Sharpes at 35 bps, as that study did.

**Pass rule.** Gate A, the filter is real (all must hold):

1. AUC on the out-of-sample events (2022 on) > 0.55, and the lower end of its
   90 % bootstrap band > 0.50;
2. the variant's Sharpe at 35 bps from 2024 is above the unfiltered book's,
   and a paired stationary bootstrap (block 20 days) puts the difference above
   0 in at least 90 % of draws;
3. the variant beats 95 % of its random null;
4. the variant is at least as good as the unfiltered book in 2 of the 3
   out-of-sample years (2026 partial);
5. on the 15 Alpaca coins the variant is not worse than the unfiltered book
   on them (Sharpe at 35 bps from 2024).

Gate B is the lab's deflation bar: deflated p > 0.95 over 275 trials. The
unfiltered book fails it (0.01 over 100), so a filter cannot be expected to
clear it alone; it is reported either way. If Gate A holds for one variant
(S1, S2 or Z, the best Sharpe at 35 bps from 2024 among those that hold), it
becomes a paper book variant marked autopilot-only with its deflation
failure in the evidence, as the existing books are; else no book, and this
file records the negative result. Not done here: the `tsmom_top20` entries
(left for a later study; not counted).

<!-- generated below by lab.experiments.meta_daily; edit above this line only -->

## Results (generated 2026-10-14, data to 2026-10-13, 591 coin segments)

**Verdict: negative. No use of the classifier passes gate A; no paper book.** Out of sample the classifier ranks the trades worse than chance (AUC 0.45 on the events from 2022, band 0.39 to 0.53; 0.40 on the book's own entries). From 2024 at 35 bps the unfiltered book makes Sharpe 1.06; S1 0.00, S2 -0.11, Z 1.05. Every gate fails for every use, and deflated p is 0.00 at best over 275 trials.

Events: 68,333 breakout cells on the panel, 1,602 training events on the top 30 (1,600 with a known exit; 36 % clear the 70 bps round trip), 7,355 cells predicted (top 30 plus the Alpaca top 10). M2 scores on 562,936 coin-days.

### The classifier (out-of-sample events from 2022)

| set | n | hit_rate | auc_raw | auc_cal | auc_p05 | auc_p95 | brier | brier_base |
|---|---|---|---|---|---|---|---|---|
| events | 1124 | 0.31 | 0.45 | 0.39 | 0.39 | 0.53 | 0.23 | 0.22 |
| book entries | 370 | 0.37 | 0.40 | 0.37 | 0.34 | 0.47 | 0.25 | 0.24 |

`auc_p05`/`auc_p95`: 90 % band from a bootstrap of whole months of events. `brier_base`: predicting each fold's training base rate. Book entries: mean trade return 10.6 % below the median probability, -2.4 % above it.

Reliability on the events (calibrated probability deciles):

| decile | mean_p | hit_rate | events |
|---|---|---|---|
| 1 | 0.10 | 0.54 | 41 |
| 2 | 0.31 | 0.41 | 131 |
| 3 | 0.32 | 0.38 | 116 |
| 4 | 0.32 | 0.38 | 142 |
| 5 | 0.34 | 0.36 | 112 |
| 6 | 0.34 | 0.09 | 69 |
| 7 | 0.34 | 0.32 | 165 |
| 8 | 0.35 | 0.22 | 77 |
| 9 | 0.36 | 0.17 | 140 |
| 10 | 0.48 | 0.27 | 131 |

Per fold (AUC on that quarter's events, raw scores):

| fold | train_events | base_rate | cal_events | calibrated | test_events | auc | s2_cut |
|---|---|---|---|---|---|---|---|
| 2021Q3 | 345 | 0.48 | 0 | no | 62 | 0.65 | 0.28 |
| 2021Q4 | 404 | 0.48 | 58 | no | 68 | 0.57 | 0.28 |
| 2022Q1 | 459 | 0.47 | 113 | yes | 56 | 0.55 | 0.47 |
| 2022Q2 | 498 | 0.45 | 152 | yes | 11 | n/a | 0.41 |
| 2022Q3 | 540 | 0.44 | 194 | yes | 65 | 0.58 | 0.41 |
| 2022Q4 | 604 | 0.42 | 258 | yes | 56 | 0.33 | 0.37 |
| 2023Q1 | 664 | 0.39 | 318 | yes | 71 | 0.23 | 0.32 |
| 2023Q2 | 717 | 0.41 | 371 | yes | 57 | 0.40 | 0.34 |
| 2023Q3 | 781 | 0.38 | 435 | yes | 55 | 0.57 | 0.31 |
| 2023Q4 | 826 | 0.38 | 480 | yes | 84 | 0.50 | 0.30 |
| 2024Q1 | 906 | 0.38 | 560 | yes | 67 | 0.50 | 0.32 |
| 2024Q2 | 986 | 0.40 | 640 | yes | 42 | 0.36 | 0.35 |
| 2024Q3 | 1040 | 0.40 | 694 | yes | 85 | 0.38 | 0.35 |
| 2024Q4 | 1094 | 0.38 | 748 | yes | 62 | 0.72 | 0.34 |
| 2025Q1 | 1183 | 0.39 | 837 | yes | 39 | 0.53 | 0.35 |
| 2025Q2 | 1214 | 0.38 | 868 | yes | 59 | 0.54 | 0.35 |
| 2025Q3 | 1282 | 0.38 | 936 | yes | 74 | 0.37 | 0.34 |
| 2025Q4 | 1346 | 0.38 | 1000 | yes | 30 | 0.73 | 0.35 |
| 2026Q1 | 1385 | 0.37 | 1039 | yes | 71 | 0.39 | 0.34 |
| 2026Q2 | 1453 | 0.36 | 1107 | yes | 56 | 0.69 | 0.32 |
| 2026Q3 | 1508 | 0.35 | 1162 | yes | 83 | 0.40 | 0.31 |
| 2026Q4 | 1568 | 0.35 | 1222 | yes | 1 | n/a | 0.31 |

Feature importance (share of total gain, all folds):

| feature | gain_share |
|---|---|
| btc_ma200 | 0.15 |
| btc_r28 | 0.14 |
| breadth50 | 0.08 |
| fund7_mkt | 0.06 |
| age | 0.06 |
| fund7 | 0.06 |
| m2_rank | 0.05 |
| m2_score | 0.05 |
| r28 | 0.05 |
| rv1_30 | 0.04 |
| vol7_30 | 0.04 |
| har_vol | 0.03 |
| vol30 | 0.03 |
| log_adv28 | 0.03 |
| r7 | 0.02 |
| breadth_bo | 0.02 |
| vol_surge | 0.02 |
| ret_vol | 0.02 |
| bo_dist | 0.02 |
| liq_rank | 0.02 |
| range_pos | 0.01 |

### The registered gates (out of sample from 2024, 35 bps)

| use | sharpe_unfiltered | sharpe | dd_unfiltered | dd | boot_share | diff_p05 | diff_p95 | years_ok | null_share | alpaca_unfiltered | alpaca | 1 | 2 | 3 | 4 | 5 | gate_a | deflated_p | gate_b |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| S1 | 1.06 | 0.00 | 0.22 | 0.00 | 0.09 | -2.09 | 0.19 | 0 | 0.28 | 0.94 | 0.00 | no | no | no | no | no | no | 0.00 | no |
| S2 | 1.06 | -0.11 | 0.22 | 0.07 | 0.05 | -2.33 | 0.01 | 0 | 0.05 | 0.94 | -0.49 | no | no | no | no | no | no | 0.00 | no |
| Z | 1.06 | 1.05 | 0.22 | 0.20 | 0.10 | -0.04 | 0.00 | 0 | 0.37 | 0.94 | 0.91 | no | no | no | no | no | no | 0.00 | no |

Gate A: 1 AUC on events > 0.55 and band low > 0.50; 2 Sharpe above the unfiltered book and the paired stationary bootstrap (block 20) above 0 in 90 % of draws; 3 beats 95 % of its random null; 4 at least as good as the unfiltered book in 2 of 2024, 2025, 2026; 5 the Alpaca twin not worse than the unfiltered book on the Alpaca coins. Gate B: deflated p > 0.95 over 275 trials.

Entries and nulls (from 2021-07, the filter's first quarter):

| use | candidates | entered | skip_rate | mean_mult_entered | null_median | null_p95 | share_beaten |
|---|---|---|---|---|---|---|---|
| S1 | 1910 | 34 | 0.98 | 1.00 | 0.32 | 1.15 | 0.28 |
| S2 | 1631 | 92 | 0.94 | 1.00 | 0.65 | 1.26 | 0.05 |
| Z | 414 | 409 | 0.01 | 0.86 | 1.06 | 1.14 | 0.37 |

S1 and S2: the same skip rate drawn at random over the predicted cells, 1000 times; Z: its multipliers shuffled among its own entries.

### Every book (out of sample from 2024)

| variant | oos_maker 15bps | oos_taker 35bps | oos_41bps | cagr_taker 35bps | dd_taker 35bps | turnover_yr | expo | boot_p05 | boot_p95 | deflated_p |
|---|---|---|---|---|---|---|---|---|---|---|
| unfiltered | 1.15 | 1.06 | 1.04 | 0.22 | 0.22 | 9.34 | 0.24 | -0.16 | 2.14 | 0.00 |
| unfiltered · Alpaca coins | 1.02 | 0.94 | 0.91 | 0.21 | 0.26 | 9.31 | 0.22 | -0.42 | 2.09 | 0.00 |
| S1 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| S1 · Alpaca coins | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| S1 · a day late | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| S2 | -0.05 | -0.11 | -0.12 | -0.00 | 0.07 | 1.09 | 0.03 | -1.19 | 0.77 | 0.00 |
| S2 · Alpaca coins | -0.44 | -0.49 | -0.51 | -0.01 | 0.04 | 0.67 | 0.01 | -1.17 | 0.27 | 0.00 |
| S2 · a day late | -0.07 | -0.13 | -0.15 | -0.01 | 0.07 | 1.09 | 0.03 | -1.18 | 0.79 | 0.00 |
| Z | 1.14 | 1.05 | 1.02 | 0.19 | 0.20 | 8.31 | 0.21 | -0.20 | 2.14 | 0.00 |
| Z · Alpaca coins | 0.99 | 0.91 | 0.89 | 0.18 | 0.24 | 8.29 | 0.20 | -0.50 | 2.05 | 0.00 |
| Z · a day late | 0.87 | 0.78 | 0.75 | 0.13 | 0.22 | 8.29 | 0.21 | -0.56 | 1.84 | 0.00 |
| unfiltered · a day late (reference) | 0.89 | 0.80 | 0.77 | 0.15 | 0.24 | 9.32 | 0.24 | -0.44 | 1.90 | 0.00 |

`boot_*`: 90 % stationary-bootstrap band of the Sharpe at 35 bps. Per year, Sharpe at 35 bps (2022 and 2023 are walk-forward for the classifier but the book was picked on them):

| variant | 2022_23 | y2022 | y2023 | y2024 | y2025 | y2026 |
|---|---|---|---|---|---|---|
| unfiltered | 0.67 | -0.84 | 1.72 | 1.84 | 0.46 | 0.39 |
| unfiltered · Alpaca coins | 0.58 | -1.10 | 1.74 | 2.06 | -0.19 | -0.11 |
| S1 | -0.49 | -0.21 | -1.22 | 0.00 | 0.00 | 0.00 |
| S1 · Alpaca coins | -0.67 | -0.49 | -1.15 | 0.00 | 0.00 | 0.00 |
| S1 · a day late | -0.49 | -0.25 | -1.16 | 0.00 | 0.00 | 0.00 |
| S2 | -0.14 | -0.35 | 0.01 | -0.08 | -0.16 | -0.07 |
| S2 · Alpaca coins | -0.28 | -0.43 | -0.12 | -1.43 | -0.35 | -0.20 |
| S2 · a day late | -0.03 | -0.41 | 0.25 | 0.06 | -0.13 | -0.60 |
| Z | 0.54 | -0.74 | 1.60 | 1.82 | 0.45 | 0.38 |
| Z · Alpaca coins | 0.42 | -1.07 | 1.64 | 2.02 | -0.20 | -0.12 |
| Z · a day late | 0.47 | -0.85 | 1.75 | 1.60 | 0.11 | 0.04 |
| unfiltered · a day late (reference) | 0.64 | -0.91 | 1.90 | 1.62 | 0.11 | 0.06 |

### Unregistered diagnostic (not counted, not gated)

S1 and S2 skip far more than half and a quarter of the entries. Two mechanisms: isotonic calibration of a score with no out-of-sample skill flattens the calibrated probability near the recent hit rate, which is below the training base rate (that includes 2020-21's 47 %), and many cells tie at the S2 cut; and a skipped coin that keeps closing above its 20-day high is a new candidate every day, so a filter that skips a share of cells skips a larger share of decisions. To check that the negative result is not only the first mechanism, the same book skips the cells whose raw score falls in the bottom half or bottom quarter of the calibration set's raw scores (no ties). Looked at after the registered run; one look, not a candidate:

| variant | skip_rate | oos_taker 35bps | dd_taker 35bps | 2022_23 | y2024 | y2025 | y2026 |
|---|---|---|---|---|---|---|---|
| raw half (diagnostic) | 0.73 | 1.09 | 0.16 | 0.32 | 1.94 | 0.37 | 0.32 |
| raw quarter (diagnostic) | 0.40 | 0.95 | 0.20 | 0.60 | 1.77 | 0.31 | 0.18 |

### Deflation

Prior: 265 trials, variance backed out of the fast strategies' bar (2.74 over 265); here 10 trials at 35 bps. Pooled bar 2.72 over 275. Trials counted here: unfiltered · Alpaca coins; S1; S1 · Alpaca coins; S1 · a day late; S2; S2 · Alpaca coins; S2 · a day late; Z; Z · Alpaca coins; Z · a day late.

Took 10 min.
