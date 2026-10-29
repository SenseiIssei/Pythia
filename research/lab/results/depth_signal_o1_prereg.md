# O1: order book depth as a signal. Pre-registration

Registered 2026-10-29 and committed before any number below was computed (while scoping, one look at the columns of
one of T4's hourly files; no return, IC or Sharpe). Brief O1 of the training plan of 2026-10-28, on the review of
2026-10-27 (`results/review_2026-10-27.md`, sections 2 and 3), R5's registry (`metrics.trial_pool`,
`<data>/trials/registry.jsonl`), R6's windows (`results/factory_lockbox_r6.md`), T1's leak harness, T4's depth
(`results/book_depth_t4.md`), T5's point-in-time universe and T6b's depth costs. Code: `lab.experiments.depth_signal_o1`
and two features in `lab.features.book` (written after this file). Results: `results/depth_signal_o1.md`. Nothing here
may change once a result exists. Paper only: nothing a live bot, a wallet or the engine reads changes.

## Question

T4's hourly book depth of Binance's USD-M perps (from 2023) has so far only priced trades. Does it carry information
about returns: the imbalance of bid and ask depth, depth falling ahead of moves, the cost of 100k as a liquidity
measure across coins?

## Data and timing

- **Depth.** `<data>/book_depth/hourly` through the feature store only (`lab.features`, group `book_depth`, daily
  rows: the hours weighted by snapshots, at least 12 hours), asked with `registry.frame` at the close of day t (00:00
  UTC ending day t). A daily row is known at its bucket's end; the archive publishes a day 7 to 10 h later, which the
  one close late below covers. One perp per coin as the group keeps it. Rows from 2026-07-01 on are dropped before
  anything is computed.
- **Prices, funding, universe.** The sweep's daily panel (`fam_common.load_panel`) cut at 2026-06-30; T5's PIT50
  (`lab.universe.pit(P, 50)` with T4's delisting table) intersected with: the coin's perp traded that day and its
  signal known at the close. A day with fewer than 20 such coins holds no new positions (the book keeps what it holds
  until its next rebalance; a held coin that dies is closed as `t5.simulate` does).
- **Late.** Weights from the close of day t are traded at the close of day t+1 (`t5.late`), every leg on its perp
  (`t5.simulate`, both legs, funding paid and received).
- **Costs, T4's own.** Per unit of one-way turnover: the USD-M taker 5 bps plus the cost of a market order of 10k USD
  a leg from T4's hour nearest the fill (T6b's `cost_matrices`, the judged 10k), T5's tier on a day without a depth
  file, 500 bps beyond the hour's depth.
- **Windows (R6).** In sample 2023-01-01 to 2023-12-31 (the depth files start 2023-01-01), validation 2024-01-01 to
  2026-06-30, the lockbox from 2026-07-01 not read.

## Signals (three, declared here; known at the close of day t)

| Signal | Feature | Score (long the high) | Prior | Horizon |
|---|---|---|---|---|
| IMB | `bd_imb1`: (bid - ask) / (bid + ask) within 1 % of mid | + | more resting bids, the price rises (Cao, Hansch and Wang 2009; Cont, Kukanov and Stoikov 2014) | 1 day |
| DCHG | `bd_depth1_chg`: depth within 1 % today against yesterday | + | depth withdrawn ahead of falls, added ahead of rises | 1 day |
| ILLIQ | `bd_cost100k_bps`: the cost of a 100k market order (log) | + | the illiquidity premium (Amihud 2002) | 7 days |

Two constructions per signal, both at the signal's horizon:

- **XS (cross-sectional).** Each rebalance day rank the universe by the score: long the top fifth, short the bottom
  fifth (k = n // 5 a side, n the day's coins), half the capital a side, equal weights.
- **TS (time-series).** Each coin against its own history: IMB `bd_imb1_dev30` (the day's imbalance minus its mean
  over the 30 daily rows before, at least 20), DCHG the change itself, ILLIQ `bd_cost100k_dev30` (log cost minus its
  mean over the 30 daily rows before, at least 20). Long a coin above 0, short below, 1/n each.
- **Horizon.** 1 day: the whole book re-picked every day. 7 days: seven daily tranches, each re-picked every 7 days
  and held, the book their mean.

## Tests (validation, each in its declared direction)

- **XS:** the rank IC: per day the Spearman correlation of the score with the late forward return of the horizon
  (close t+1 to close t+1+h, the universe's coins), its mean, t with Newey-West errors (lags max(10, 2h)).
- **TS:** the t of the TS book's mean daily gross return (Newey-West, 10 lags).
- **Depth falling ahead of moves (information, no book):** per day across the universe, OLS of rank(|r(t+1)| / s30)
  on rank(-DCHG) and rank(|r(t)| / s30), s30 the mean |r| of days t-29 to t (at least 20), r close to close; the
  coefficient on -DCHG, its mean and Newey-West t (10 lags). Prior positive: a coin whose depth fell moves more the
  next day than its own volatility and today's move say. Known at the close of day t, so no lateness is needed for an
  information test.

## Trials (7)

Each a line of R5's registry (family hand, source this file), registered before any validation number:
`hand:o1:<imb|dchg|illiq>:<xs|ts>` with the book's in-sample Sharpe (net, judged costs), and `hand:o1:dchg:vol`
counted without a Sharpe. DSR over R5's pool of all (the factory ledgers counted with it, as T6) and over the hand
family, each with these trials.

## Pass rule (per book; all must hold)

1. Validation Sharpe (net, judged costs) above 0.5 and positive in at least 2 of 2024, 2025, 2026.
2. Its test t at least 2 in the declared direction.
3. DSR over all at least 0.95, and over the hand family at least 0.95.
4. PBO (`metrics.cscv`, 16 blocks) of the six books over in sample and validation below 0.5.
5. Leak: T1's harness on the book's weight function (the depth features as panel arrays, every value after t
   changed) finds nothing, and the features used pass `lab.leak.checks.feature` at 1d.

The depth-falling test is reported with its t, judged at |t| >= 2 in the prior's direction, but no book follows from
it alone.

## Reported

`results/depth_signal_o1.md`: per book the in-sample and validation Sharpe, CAGR, drawdown, cost drag and the
Sharpe by year, the test's statistic and t, DSR over all and the family with the pool's size and noise bar, the PBO,
the leak results, the depth coverage of the universe (share of universe coin-days with each signal), the
depth-falling test, the lockbox line (no look unless a book passes). A paper book only if a book passes:
`depth_o1_<signal>_<xs|ts>`, the passing book's rule unchanged at 10k a leg, in its own later commit. Nothing reaches
a book, the engine or a wallet otherwise.
