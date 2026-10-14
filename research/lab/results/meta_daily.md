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
