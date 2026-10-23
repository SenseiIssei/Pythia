# The bombers (Y13): pre-registration (2026-10-23)

Written and committed before any number below was computed. Code: `lab/pumpfun_rt/bombers13.py`, tests
`tests/test_pumpfun_bombers_y13.py`. Paper only: nothing here holds a wallet, reads a key, signs or sends anything. No
existing module changes: the live service, its executor, its sizing, the pipeline, the engine, the strategies and
every paper book are untouched; the books below are the run's own and do not join the paper engine. A change to
anything below after the first result is a new trial with a new name.

## Why

The owner sees pump.fun coins run +10,000 % to +59,000 %, often with big early buys, and wants the bot to catch
them. Earlier work: early detection of a 10x is weak (X14, AUC 0.78, precision 1.5 % in the top 5 %), the sniper
shadow book P_snipe_cmig lost 6.5 SOL over 1,337 trades, live buys land a median 9 s after the signal (the public
stream lags a median 8.7 s behind the chain). Three questions: how many coins go 50x, 100x, 1000x and how much of
the run is left at our speed; what the first seconds show for them; and whether paper books with a runner exit pay
at 1, 3 and 10 s or at the measured live latency.

## What was looked at before this plan

Disclosed: the reports and pre-registrations of X14, Y3, Y5, Y7 to Y15; the record's days (2026-10-20 16:39 UTC to
2026-10-23) and row counts; that the record has about 43,700 plain SOL curves, 2,763 migrations and gaps on both
streams; that the PumpSwap rows all belong to the pool of the token's migration. While testing the code on
2026-10-20: a handful of tokens whose creation transaction or slot buys the whole curve (the pool opens at once, so
such a coin is "50x" from its first trade within a second), and that a paper position in a coin that goes quiet
stays open (the stop only fires on a trade). The run's code was executed on the whole record only to time it and to
count rows and picks (G3 355, G10 386, W10 2,813, R 1,410 tokens); no label rate, score, precision or return of any
book was looked at.

## 1. Record, tokens, prices, labels

- **Record**: every recorded day up to the cutoff **2026-10-23 18:00 UTC**. Every row is timed by its slot
  (`store.slot_times`, per day as `sim.day_events`), not by its receive time.
- **Tokens**: plain SOL curves (no other quote, no mayhem flag) with at least one curve trade.
- **p0**: the curve's price after the token's first curve trade (the dev's buy where the creation carries one).
- **Path**: the curve's price after every curve trade, then the pool's price before every trade of the token's
  PumpSwap pool (effective quote reserves), in chain time.
- **Labels**: `b50`, `b100`, `b1000`: the highest price within **6 h** of creation is at least 50, 100, 1000 times
  p0; only tokens with their 6 h in the record. Part 1 also counts 24 h (tokens with 24 h in the record).

## 2. Part 1: how many, how fast, how much is left

For 50x, 100x, 1000x: the count within 6 h and 24 h, per day, the rate, the median and quartile time from creation
to the first price at the multiple; the multiple of p0 already reached 1, 3, 10, 30, 60 s after creation (the last
state at or before) and the multiple still ahead to the 6 h peak (median, lower quartile, share with 10x or more
still ahead), for the coins of each group and the median for all tokens.

## 3. Part 2: what the first seconds show

- **Rows**: every plain token whose first 60 s do not overlap a gap of the curve stream, at **creation + 3 s** and
  **creation + 10 s**, from every trade timed at or before the decision.
- **Features** (`FEATURES`): the dev's (creator's or the creation's payer's) buy SOL and its net share of the
  supply, whether it sold; buys, sells, unique buyers, buy and sell SOL, net SOL, the largest single buy, the top 3,
  the number of buys of at least 1, 3 and 10 SOL (everyone but the dev); unique buyers and their SOL in the creation
  slot, the most unique buyers in any one slot (bundles); the multiple of p0 and the curve's progress; the creator's
  earlier coins in the record, those that migrated and those that reached 50x before the decision, its coins in the
  last hour; the early buyers' history (each wallet that bought within 10 s of an earlier creation: the mean number of
  such coins, how many of the decision's buyers had one that migrated, how many one that reached 50x, each counted
  only from the moment it happened); name and symbol (lengths, upper case, digits, words, an ipfs uri, coins with the
  same symbol or name in the last hour); Y10's trend tracker (`trendfeat.Tracker`, every curve and pool trade, its 18
  features at the decision).
- **Walk-forward**: test blocks by creation time starting 2026-10-21 12:00, 2026-10-22 00:00, 2026-10-22 12:00,
  2026-10-23 00:00, 2026-10-23 12:00 (the last ends at 17:00, the books' entry end); each trained on the tokens
  created before its start less 6 h (the label's horizon, purged), a block only with at least 5 positives.
  LightGBM with Y9's parameters (`selmodel.PARAMS`) and the logistic baseline (`model.logistic`) on **`b50`**.
- **Reported out of sample** (rows with their 6 h in the record): for 50x, 100x and 1000x the base rate, both
  models' AUC and precision in the top 0.1 % and the top 1 % (taken within each block, pooled); the G books' rule
  (below); seven fixed flags (any buy of 1, 3, 10 SOL or more within the window, 3 or more buyers in the creation
  slot, a dev buy of 1 SOL or more, a creator with an earlier migration, an early buyer with an earlier 50x), each
  with its share of tokens and precision; the medians and means of the features for the 100x coins against the rest
  and each feature's AUC alone; the last block's gain importance.
- **Separates**: a model separates the bombers if, out of sample at 10 s, its AUC for 100x is at least 0.75 and its
  top 1 % precision for 100x at least 10 times the base rate with at least 3 hits.

## 4. Part 3: paper books

- **Signals** (entries for tokens created from 2026-10-21 12:00 to 17:00 on the cutoff day):
  `G3` and `G10`, the LightGBM score at 3 s or 10 s at or over the 99th percentile of the scores the block's model
  gives its own training rows; `W10`, the owner's whale rule: a single buy of 3 SOL or more by anyone but the dev
  within 10 s; `R`, the reference: one plain token in 20 by its mint's hash, at 10 s (not a trial).
- **Entry**: a pipeline checkpoint strategy at creation + 3 or 10 s that buys its picks (`BomberStrategy`), on the
  curve, through `pipeline.PaperExecutor` and `sim.Engine` as every paper book: the token's fee, 0.001005 SOL per
  transaction, a buy that fails above the 30 % slippage tolerance or after the curve completed, a sale that takes
  what the curve or the pool pays when it lands. **0.05 SOL a trade.**
- **Exit** (`EXITS`): a third of the tokens at 3x (the sale value over the cost, +200 %), a third at 10x, the rest
  (and everything before) on a trail of 50 % under the highest mark since the landing, a stop at -50 %, a time stop
  24 h after the landing; no dev-sell or pull exit. A position still open at the cutoff is valued at its mark then
  (what selling the rest would bring, less one transaction).
- **Latency**, four: **L1** the paper model (`curve.Costs`: lognormal, median 1 s, 0.4 to 3 s), **L3** and **L10**
  the same scaled 3 and 10 times (buys and sales), **B** Y9's measured live latency (buy median about 10 s from the
  signal, sale about 4 s, as Y10 to Y15). Every book draws its latency with one key per token and leg.
- **Two ways to run the books**, both with the code's caps (5 open, 0.6 SOL exposure, 1.0 SOL daily loss):
  **U**, every pick on its own (an engine per 5 picked tokens: no cap can bind), judged; **C**, all picks of a
  signal in one book, as a bot with the caps would have traded them, reported.
- **Reported**, per signal and latency: entries and per day, failed buys, still open at the cutoff, mean and median
  return per entry over the stake, win rate, P&L, the hour-block 90 % band of the mean (`study.boot_mean`, at least
  10 hours), SOL per day (P&L over the days of the entry window), the exits; trades on 100x coins (`b100`) with their
  mean P&L, the other trades' mean P&L and **how many losers one 100x coin pays for** (the first mean over the
  second's loss).
- **Pays**: a U book pays at a latency if its band is above zero and its P&L above zero.
- **Headline signal**: of G3, G10 and W10, the one with the highest out-of-sample precision for 100x at its book's
  rule (ties to G10). **What speed would make it pay**: the slowest of L1, L3, L10 and B at which the headline's U
  book pays; if it pays at none, the answer is that not even 1 s pays on this record.
- **Trials**: three signals at four latencies, 12.

## 5. Equality

No existing module is changed. As Y11 to Y15, every strategy and rule is replayed in one shared paper book on the
recorded 2026-10-20 with the code before and after this study's commits; the closed trades, the failed buys and the
skip counts must be identical.

## 6. Too early

Three days of record, labels for tokens of under three days, a few dozen 100x coins at most, a test window of two
days. Everything here is a first reading; nothing goes to the live bot or the paper engine from it.
