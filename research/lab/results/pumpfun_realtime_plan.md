# pump.fun in real time: pre-registration (2026-10-20)

Written and committed before any rule or model below was computed on recorded
data. The rules are in `lab/pumpfun_rt/strategies.py`; a change to one is a new
rule with a new name and one more trial, never an edit.

Paper only. Nothing in `lab.pumpfun_rt` holds a wallet, reads a key, signs or
sends anything; a test checks the package for it.

## Question

The 5-minute watcher (`lab.paper.pumpfun`) cannot see the part of pump.fun
where most of the money changes hands: most tokens are pulled within seconds
of launch. With every creation and every curve trade recorded as it happens,
is there any fast, very risky rule that makes money on paper after honest
fills, and does a model of the first seconds and minutes help?

The expected answer is no: snipers with co-located senders and bundles land
in the creation block, the creator often sells into the first buyers, and the
fee is 1.25 % a side plus a priority fee. The study exists to measure how far
from yes it is, not to find money.

## Data

The collector (`lab.pumpfun_rt.collector`) records from a public Solana RPC
websocket every pump.fun creation, curve trade, completion and migration, and
the first 24 hours of PumpSwap trading of each token that migrated while it
watched. Times are receive times in ms. Gaps in the record are rows of their
own; every trade and model row that overlaps one is dropped.

Universe: tokens whose creation was recorded, on a plain SOL curve (not mayhem
mode, no other quote mint, no fee-free trades with erratic reserves).

## Execution model (`lab/pumpfun_rt/curve.py`)

- Our order lands L after the signal, L lognormal with median 1 s, clipped to
  0.4 to 3 s (an ordinary RPC sender; no bundles), seeded per rule, token and leg.
- It fills at the curve state after every trade received before the landing,
  by the curve's own arithmetic, with the token's observed fee (protocol plus
  creator, 1.25 % at the time of writing) and a priority fee of 0.001 SOL plus
  the base fee per transaction. Our own trade does not move the recorded curve
  (price impact is paid twice, which errs against us).
- A buy fails, losing the transaction fee, if the price at landing is more than
  30 % above the price at the signal, or the curve completed first.
- A sale always fills at whatever the curve, or after completion the PumpSwap
  pool, pays at landing; a dump before it lands is ours to eat.
- Stake 0.1 SOL a trade, at most 50 open per rule, one entry per token.

## Rules (23 trials)

| family | signal | variants |
|---|---|---|
| A snipe | creation received | all tokens; dev buy 0.5 to 5 SOL; creator with an earlier completed curve. Exits +50 % / -30 % / 15 s and +100 % / -40 % / 60 s (6) |
| B pressure | creation + 3 s (5+ unique buyers, 1+ SOL net in) or + 10 s (10+, 2+ SOL), dev not sold | exits +50 % / -30 % / 30 s and +100 % / -40 % / 120 s (4) |
| C momentum | the trade that brings 20 unique buyers within 60 s, or 50 within 300 s, curve under half, dev not sold | exits +50 % / -25 % / 120 s and +100 % / -35 % / 600 s (4) |
| D pre-migration | the trade that takes curve progress past 80 % or 90 % | exits +30 % / -20 % / 300 s and +60 % / -30 % / 1800 s (4) |
| E post-migration | PumpSwap pool at migration + 0 s or + 60 s | exits +30 % / -20 % / 300 s and +100 % / -40 % / 1800 s (4) |
| model filter | the in-sample pick with the model in front | 1 |

Unique buyers never count the creator. Exits are checked on every trade of
the token; the sale lands one latency draw after the exit signal.

## What is reported per rule

Closed trades, failed buys, hit rate, mean and median net return per trade,
5 % and 95 % quantiles, best and worst, rugs (a trade at -90 % or worse), the
share of trades during which the creator dumped (sold half or more of what it
held), total paper P&L in SOL (failed buys' fees included), P&L per day, and
the daily Sharpe of the book (P&L over a 10 SOL book).

## Selection and the bar

Time-ordered halves of the record by signal time: the first half in sample,
the second out of sample. The pick is the rule with the highest in-sample mean
net return per trade among rules with 30 or more in-sample trades (else
`C_20in60_x1`, the default). Nothing is judged in sample.

A rule earns more paper time (not money) only if, out of sample:

1. the mean net return per trade is above 0 and the 90 % band of an
   hour-block bootstrap (5,000 draws) is above 0;
2. 300 or more closed trades over 14 or more days;
3. still above 0 with latency doubled (median 2 s, 0.8 to 6 s) and with the
   priority fee tripled;
4. the best five trades make under half the P&L and 60 % or more of the days
   are positive;
5. deflated p above 0.95 on the daily P&L series against the lab's global pool
   (878 hand trials at the published bar's variance: 377 to C16, 231 in
   parallel, overnight 39, book_portfolio 30, flow_overlays 198, the three
   5-minute pump.fun rules; the factory's ledger; these 23);
6. for the model filter in addition: its mean return per trade beats the pick
   without it, the bootstrap band of the difference above 0.

Then 30 days of the live shadow book with results inside the replay's range.
Until there are 14 days of record every report says it is too early; the
numbers are shown, never acted on.

## The model (`lab/pumpfun_rt/model.py`)

Rows: every plain token at 3, 10, 30, 60, 120 and 300 s after creation while
on its curve. Features at t from events received before t only: age, buys,
sells, unique buyers and traders, SOL in and out, the last 10 s of flow, curve
progress, price against launch and peak, the dev buy, dev holding and selling,
top holder shares, the first five buyers' share, the creator's earlier tokens,
completions and dumps (as of the creation), market activity (creations in the
last 10 minutes), name and symbol shape, metadata flags if known by t, hour.

Labels: `dump60` (the creator sells half or more of what it held at t within
60 s), `mig` (the curve completes within 6 h of creation), `win30` and
`win300` (a paper buy at t, filled with latency, sold at t + 30 s or 5 min,
ends above 0 after every cost), and the log price ratios `r30`, `r300`.

Method: LightGBM (300 trees, learning rate 0.05, 31 leaves, at least 200 rows a
leaf, 80 % features and rows), isotonic calibration on the last 20 % of each
training window by time; purged walk-forward over 5 folds by decision time,
training only on rows whose label window ends an embargo (the label's horizon
plus 10 minutes, 6 h 10 min for `mig`) before the fold starts. Baselines: the
training base rate, and a logistic regression on six features (unique buyers,
net SOL, progress, dev sold, age, buys in the last 10 s). Reported: AUC, Brier,
Brier skill against the base rate, log loss, calibration error (10 bins), per
fold and pooled; the model counts as useful for a label only if pooled AUC is
above 0.55, Brier skill above 0, and it beats the logistic baseline's Brier in
4 of 5 folds. Retrained daily on all rows (the newest 3 million at most).

Filter: the pick enters only when the calibrated probability of its round-trip
label (`win30` for holds up to a minute, else `win300`) is at least 1.25 times
the training base rate.

## Live shadow

The collector runs the pick and the pick with the model filter as two paper
books on the stream, by the same engine and the same fill model. Telegram: a
daily summary card, and a single closed paper trade at +200 % or better (at
most one an hour), in English or German.

## Real money

Not this study's decision. The owner's rule: real money only after active and
consistent profit on paper, and only he decides. Passing the bar above is
necessary, not sufficient.
