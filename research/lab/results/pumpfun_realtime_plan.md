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

Addendum (2026-10-20, after a smoke run on the first hour of record that
picked and judged nothing): "the creator" and "the dev" mean the creator and
the wallet that paid for the creation. In about a fifth of creations a launch
tool names another creator, and the dev buy then comes from the payer.

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
   5-minute pump.fun rules; the factory's ledger; these 23; and every study
   counted since, at the time of writing X9's 29, so 907 hand trials);
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
last 10 minutes), name and symbol shape, whether the metadata uri is an IPFS
upload (pump.fun's site) or a launch tool's own host, hour. (Addendum the same
day, before any computation: metadata flags such as socials were planned, but
the public IPFS gateways answer 429 or a service-worker page, so they would be
missing for nearly every token; they are not features.)

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

## Addendum 2 (2026-10-20): the trading pipeline, exit models, wallet reputation, name categories

Written and committed before any strategy, label or feature set below was
computed on recorded data. Code: `lab/pumpfun_rt/pipeline.py` (strategies,
sizing, risk, exits, the paper executor), `wallets.py` (wallet reputation),
`categorize.py` (name categories), `model.py` (labels and feature sets),
`retrain.py` (the daily retrain), `live_exec.py` and `txbuild.py` (the locked
live executor). The 22 rules and the model filter above are unchanged.

### One pipeline for paper and live

Signal, filter, sizing, risk check, entry, exit management. The decision code
is the same object for the paper shadow book, the study's replay and a live
executor; only the executor differs (`PaperExecutor` fills by the curve
arithmetic after a latency draw; `LiveExecutor` would send the same order to
the chain and take its fill from the program's own event). Paper therefore
does what live would do, including the risk limits below.

Orders, both executors:

- Buy: the token amount the stake buys at the signal's curve or pool state,
  with a cost limit of stake x 1.30 (the 30 % tolerance of the plan); at
  landing the cost of that amount at the then state, fee included; above the
  limit the buy fails and only the transaction fee is lost. If less is left on
  the curve, what is left.
- Sell: a token amount with a floor on the proceeds: 0 for every protective
  exit (stop, trailing, dev sell, liquidity pull, risk model, time stop, kill
  switch), half the expected proceeds for a take-profit step (a step that
  would fill under that is not taken; the position stays and is checked again).
  A failed sale pays its transaction fee.
- Sizing: the strategy's stake (0.1 SOL), never more than 2 % of the curve's
  virtual SOL (or the pool's SOL) and never more than the risk limits allow.

Risk limits per book (the code's hard caps; a live owner can only lower them):
0.1 SOL a trade, 5 open positions, 0.6 SOL total exposure (open cost plus
pending cost limits), a daily loss stop of 1 SOL (realised loss of the UTC
day plus the exposure a new buy would add; once the realised loss reaches it
the book buys nothing more that day), and a kill switch file (no new buy;
every open position is sold at once).

Exits, checked on every trade of the token and acted on in the same slot
window (the sale is signalled at the slot time of the event that triggers it
and lands one latency draw later, at whatever is left then):

- take-profit ladder: steps (gain, cumulative share of the bought tokens sold);
- stop loss: the net sale value of what is left at or below (1 - sl) of its cost;
- trailing stop: once the gain reached `trail_after`, the value falls `trail_gap`
  below its peak;
- dev sell: the creator or the creation's payer sells 10 % or more of what it
  holds (on the curve or in the pool);
- liquidity pull: on the curve, net SOL out over the last 2 s at or above 15 %
  of the curve's real SOL before it, or one sale of 2 % or more of the supply by
  a top-10 holder; in the pool, its SOL down 15 % or more within 2 s, or a sale
  of 2 % or more of the supply;
- risk model (P_mom_model only): P(sell10_10) at or above twice its base rate;
- time stop.

### Strategies (8 trials)

| name | entry | filter | ladder (gain: share sold) | stop | trailing (after, gap) | time |
|---|---|---|---|---|---|---|
| P_snipe_dev | creation | dev buy 0.5 to 5 SOL | +30 %: 50 %, +80 %: all | -30 % | +20 %, 15 % | 30 s |
| P_snipe_cmig | creation | creator had a completed curve | +50 %: 50 %, +150 %: all | -35 % | +30 %, 25 % | 120 s |
| P_press10 | creation + 10 s | 10+ outside buyers, 2+ SOL net, dev not sold | +30 %: 50 %, +80 %: all | -25 % | +15 %, 15 % | 60 s |
| P_mom_model | 20 outside buyers in 60 s, curve under half, dev not sold | P(up30) at least 1.25 x base and P(sell10_10) at most its base | +30 %: 50 %, +100 %: all | -25 % | +20 %, 15 % | 120 s |
| P_p90 | curve progress crosses 90 % | none | +20 %: 50 %, +50 %: all | -20 % | +15 %, 12 % | 1800 s |
| P_p80_smart | curve progress crosses 80 % | 1+ smart early buyer | +20 %: 50 %, +50 %: all | -20 % | +15 %, 12 % | 1800 s |
| P_pool60 | PumpSwap, migration + 60 s | none | +30 %: 50 %, +100 %: all | -25 % | +20 %, 15 % | 1800 s |
| P_cmig_model | as P_snipe_cmig | P(up30) at least 1.25 x base | as P_snipe_cmig | -35 % | +30 %, 25 % | 120 s |

Every exit above applies to every strategy. The study's pool now counts 31
trials (22 rules, the model filter, these 8). The models a strategy filters by
are trained on the in-sample half only (as the registered filter is). Each is
replayed at doubled latency and tripled priority fee as the rules are.

### Wallet reputation (`wallets.py`)

Kept as the stream goes, point in time (an outcome counts from the moment it
is known): per wallet, its early buys (one of the first 20 outside buyers of a
token, within 30 s of the creation), how many of those tokens later completed
their curve, and how many it sold within 30 s of buying (a flip). Definitions:
a **smart** wallet has 3 or more early buys of which 2 or more and 20 % or more
completed; a **flipper** has 5 or more early buys and flipped 60 % or more; a
**repeat dumper** is a creator that dumped 2 or more of its tokens.
Features at t: early buyers with a history (3+ early buys), smart early
buyers, the flippers' share of early buyers, the early buyers' mean shrunk
completion rate ((completed + 0.3) / (early buys + 10)), early buyers that are
repeat dumpers, the creator's own early buys and their completions.

### Name categories (`categorize.py`, Claude Haiku 5.5 as a data provider)

Once a day, every plain token of the previous day (UTC) whose normalised name
and ticker was not classified before is sent in batches through the engine's
metered AI endpoint (its budget applies), with the 30 most traded names of
that day as the trending list, into one of: copycat of a trending token,
celebrity or political, AI or tech, animal meme, generic, likely scam
pattern. Cached per mint and per name. The category of a name is usable from
the time its batch finished, by any later token with the same normalised name
and ticker (so a replay sees exactly what the live book could have seen: a
token's own category arrives a day late, a reused name's at once). Features:
whether a category is known, and one flag per category.

### New labels (model trials)

- `sell10_10`, `sell10_30`: the creator, the creation's payer or one of the
  top-10 holders at t sells 25 % or more of what it held at t within 10 or 30 s;
- `up10`, `up30`, `up120`: the price 10 s, 30 s or 2 min after a buy at t
  would have landed (a latency draw after t) is above the price at the landing.

The rows are the registered decision rows (3, 10, 30, 60, 120, 300 s).

### Feature sets and their adoption

Every label (the 4 registered and these 5) is evaluated by the registered
purged walk-forward three times: base features, base plus wallet features,
and the adopted set plus categories. A set is adopted for a label only if its
pooled out-of-sample AUC is at least 0.005 above the set before it and its
Brier score is lower in 80 % of the folds that ran; otherwise the label's
model keeps the smaller set. 27 model evaluations a day are counted and
reported. The daily retrain (`retrain.py`) does this on the study's rows, then
trains each label's model on every row with its adopted set.

### Readiness for real money (the owner's gate, not this study's decision)

A strategy is reported as ready only if, out of sample: 14 or more days of
record; 300 or more closed trades; mean net return per trade above 0 with and
without the trades on broken slots; every registered gate (g1 to g5) passes;
and 30 or more days of the live paper shadow of the same strategy with a mean
per trade above 0 and inside the replay's 90 % band. Ready is necessary, not
sufficient: the live executor stays locked unless the owner also switches it
on and confirms the strategy and a daily loss limit in writing (see
`research/ops/README.md`).
