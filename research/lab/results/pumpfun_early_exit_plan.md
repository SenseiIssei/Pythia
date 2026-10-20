# pump.fun early detection and exit timing (X14): pre-registration (2026-10-20)

Written and committed before anything below was computed on recorded data. The
code is `lab/pumpfun_rt/early.py` (rows, features, labels, paths, the step
rows of the exit models), `lab/pumpfun_rt/exitpol.py` (exit policies, the
hazard and upside models, the evaluation) and the pipeline's new exit policy
and strategies. Paper only: nothing here holds a wallet, reads a key or sends
a transaction. A change to anything below is a new trial with a new name.

## Data, as it stands

The server's record started on 2026-10-20 16:40 UTC (about 3 hours 20 minutes
at the time of writing, about 6,600 tokens, 560,000 curve trades); the PC's
earlier 2 h 15 min are no longer on disk. The task said "about two days"; it
is hours. Every number of this study is therefore "too early" by the lab's bar
(14 days, 300 trades out of sample), and the report says so. The study runs
daily from now on with the retrain and the verdicts are re-read as the record
grows.

## Execution model

As the pipeline's paper executor (`pipeline.PaperExecutor`, `curve.py`): a buy
of 0.1 SOL asks for the tokens the stake buys at the signal's curve state with
a cost limit of stake x 1.30; it lands one latency draw later (lognormal,
median 1 s, 0.4 to 3 s, seeded by purpose, token, decision and leg), pays the
cost of those tokens at the curve then (the token's fee on top), fails (losing
the transaction fee) above the limit or when the curve completed first. A sale
lands one latency draw after its signal and takes what the curve, or after
migration the PumpSwap pool, pays then, fee off. Every transaction pays the
base fee and 0.001 SOL priority fee. Doubled latency is reported for every
book as a stress case.

## 1. Early detection

**Rows.** Every plain SOL curve token (as the lab defines it) at 5, 10, 20, 30
and 60 s after creation while on its curve, and at the trade that first takes
its curve progress past 25 %, 50 % and 75 % (eight decision kinds). Rows that
overlap a gap in the record are dropped.

**Features** at the decision time t, from events before t only: the lab's
token features (`tokens.FEATURES`: flow, unique buyers, dev buy and holding,
top-1 and top-5 shares, the first five buyers' share, the creator's history,
market creations in 10 minutes, name shape, metadata host, hour), the wallet
reputation of the early buyers (`wallets.WALLET_FEATURES`: smart money,
flippers, repeat dumpers), the name categories where known
(`categorize.CAT_FEATURES`, Claude Haiku 5.5 as a data provider), and these
new ones (`early.EARLY_FEATURES`):

- flow and acceleration: buys, sells and net SOL in the last 5 s; buys and net
  SOL in the last 5 s minus the 5 s before; outside buyers per second of age;
- curve velocity: progress per second of age, and progress gained in the last
  10 s;
- holders: wallets holding, the top-10 share now and at 5 s of age;
- snipers: outside wallets that bought within 2 s of the creation, and how
  many of the early buyers are known snipers (5 or more tokens bought within
  2 s of their creation, point in time);
- market: curve trades and creations of all tokens in the last 60 s,
  completions in the last hour;
- the decision kind's milestone (0 for the time rows).

**Labels.**

- `mig1h`: the curve completes within 1 hour of creation (the 6-hour label of
  X8 needs more record than exists; reported when known);
- `peak3x`, `peak10x`: a paper buy at t (the execution model above) fills, and
  the net sale value of its tokens (fee and one transaction fee off) reaches 3
  or 10 times its cost (fee and one transaction fee in) at any trade of the
  token, curve or pool, within 1 hour of the landing. A failed buy is 0: we
  could not get in. The peak ignores the latency of a sale; it is the upper
  bound;
- `alive5m`: none of the dev (creator and payer) and the top-10 holders at t
  sells half or more of what it held at t within 5 minutes.

**Models.** LightGBM with the lab's fixed parameters (`model.PARAMS`) and
isotonic calibration on the last 20 % of each training window by time
(`model.fit`); the baseline is a logistic regression on the same features
(medians for gaps, standardised), calibrated the same way. One model per
label over all decision kinds (the age and milestone are features).

**Evaluation.** Purged walk-forward over 5 folds of decision time; a training
row's label window plus 10 minutes must end before its fold starts (horizons:
`mig1h` 1 h from creation, `peak*` 1 h 3 s, `alive5m` 5 min). Pooled out of
sample: AUC, Brier skill against the training base rate, calibration error,
precision at the top 1 % and 5 % of rows by score within each test fold (per
decision kind and pooled), lift (precision over the fold's base rate). A label
is "useful" by the X8 rule: pooled AUC above 0.55, Brier skill above 0, and
the model's Brier below the logistic baseline's in 80 % of the folds.

**Paper books (16 trials).** For each label and each model (LightGBM,
logistic), at the top 1 % and the top 5 %: in each fold the threshold is that
quantile of the model's scores on its own training rows (so it is what a live
book could use), and the test rows at or above it are entered (one entry per
token, its first qualifying row), with exit E0. For `alive5m` the top is the
highest probability of staying alive. Reported out of sample: trades, failed
buys, mean and median net return per trade, hit rate, P&L in SOL, the 90 %
band of the mean by an hour-block bootstrap, the same at doubled latency.

**E0**, the registered exit of the early books: sell all on a dev sale of 10
% or more of its holding or a liquidity pull (the pipeline's definitions),
a stop at -35 %, half at +100 % and the rest at +300 %, a trailing stop 25 %
below the peak once +50 % was reached, and a time stop at 30 minutes.

## 2. Exit timing

**Positions.** Every early-detection row whose paper buy filled. In sample:
landed in the first half of the record's time span; out of sample: the rest.

**Paths.** Every trade of the token, curve or pool, for 30 minutes after the
landing, with the curve or pool state, so a sale of any amount at any time is
priced exactly, and the pipeline's dev-sell and pull triggers at each.

**Capture ratio.** Realised gain over the best possible gain afterwards: the
best is the highest net sale value of all the position's tokens at any trade
within 30 minutes of the landing, minus the cost. Reported as the ratio of
sums over positions whose best gain is above 0, the median of the per-position
ratios, and the share of positions that never reached their cost.

**Exit models.** Step rows: at the landing and then at every trade at least 1
s after the step before, up to 10 minutes after the landing (deterministic
subsampling by token if over 3 million). Step features: the position (seconds
held, log of value over cost, log of peak over cost, drawdown from the peak,
seconds since the peak) and the token then (the flow, velocity and holder
features above, the dev's holding and sales, the largest sale in the last
10 s as a share of the supply, net SOL out in the last 2 s over the curve's
SOL, on the curve or in the pool, market activity). Labels from the path:
`dump10`, the net sale value at any trade within the next 10 s at or below 75
% of the value at the step (a discrete-time hazard), and `up30`, the log of
the highest value within the next 30 s over the value at the step (at least
0). Models: LightGBM classifier (calibrated as above) for `dump10` against the
logistic baseline, LightGBM regression (same parameters, L2) for `up30`
against the training mean. L is the mean log loss of the in-sample steps that
had a dump (the log of the lowest value in the 10 s over the value at the
step).

**Policies (38 trials).** Every policy is checked at every trade of the
token (the pipeline's cadence; the model at most once a second) and sells all
or part with a sale landing one latency draw later.

| family | variants |
|---|---|
| hazard HZ(k) | sell all when predicted `up30` is below k x predicted P(`dump10`) x |L|; k in 0.5, 1, 2, 4; with and without the dev-sell and pull exits; time stop 30 min (8) |
| time | sell all at 30 s, 120 s, 600 s (3) |
| take/stop | +50 %/-30 %, +100 %/-40 %, +200 %/-50 %, time 30 min (3) |
| ladder | (+30 %: half, +80 %: all), (+50 %: half, +150 %: all), (+100 %: half, +300 %: all); stop -35 %; 30 min (3) |
| trailing | gap 15 %, 25 %, 40 % once +20 % or +50 % was reached; stop -35 %; 30 min (6) |

The 15 baselines run with and without the dev-sell and pull exits (30). The
hazard models a policy uses are trained on in-sample steps only.

**Selection and judgement.** In sample, the policy with the highest mean net
return per position is the pick; the best of the 30 baselines in sample is the
comparison. Out of sample: capture ratio, mean net return, P&L, the hour-block
band; the hazard pick is "better" only if its out-of-sample mean beats the
baseline pick's with the 90 % band of the difference (same hours resampled)
above 0. The same policies are also reported on the top 5 % entries of the
`peak3x` LightGBM book. The capture ratio of the existing pipeline strategies'
paper positions (the daily study's replay, best within 30 minutes of the
landing tracked as they run) is reported alongside.

## 3. Wired into the pipeline (paper and shadow; 4 trials)

Pre-registered now, whatever the numbers say; they are paper books that
accumulate evidence, judged by the X8 bar and the readiness gate like every
strategy:

| name | entry | filter | exits |
|---|---|---|---|
| P_early10 | creation + 10 s | P(`peak3x`) at or above the top-5 % threshold of its training scores at that age, and P(`alive5m`) at or above its base rate | HZ(k*) with the dev-sell and pull exits, 30 min |
| P_early30 | creation + 30 s | the same at 30 s | the same |
| P_press10_hz | as P_press10 | as P_press10 | HZ(k*) with the dev-sell and pull exits, 30 min |
| P_pool60_hz | as P_pool60 | none | the same |

k* is the in-sample pick among the four HZ(k) with the event exits. Without
the models (before the first retrain) the hazard exit falls back to E0's
price exits. The daily retrain (`retrain.py`) builds these models on the
study's rows, re-selects k* on the first half of the window and saves
everything where the shadow books read it. Each strategy is replayed at
doubled latency and tripled priority fee like the others.

**Telegram.** One more line on the daily card: the exits' capture ratio out of
sample (the pick and the best baseline) and the early detection's precision at
the top 5 % for `peak3x` with its lift, in English and German.

## Counting and the bar

58 new trials (16 early books, 38 exit policies, 4 strategies) join the lab's
global pool (`strategies.N_TRIALS`, which the study's deflation reads). The
bar is X8's: mean and its hour-block band above 0, 300 trades over 14 days,
positive under stress, breadth, deflated p above 0.95. Under 14 days of record
the verdict is "too early"; the numbers are shown, never acted on.
