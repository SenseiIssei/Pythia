# A1: an adaptive model zoo and strategy allocator for pump.fun: pre-registration (2026-10-26)

Written and committed before the first run of the study. Paper only; the live bot is unchanged. Code:
`lab/pumpfun_rt/zoo.py` (the members), `selector.py` (the selector), `allocator.py` (the bandit),
`adaptive_a1.py` (this study); tests `tests/test_pumpfun_adaptive_a1.py`.

## The question

The owner wants the system to pick the best prediction models and strategies by itself as conditions change. Two
questions, each answered out of sample only, deflated for the number of comparisons:

1. Does the selector (per label, every day the model or a stacked blend with the lowest recent out-of-sample log
   loss, under an evidence rule, calibrated out of fold) beat the best single model of the zoo out of sample?
2. Does the allocator (Thompson sampling over the registered strategies) beat the best single strategy on realistic
   paper at the live bot's measured latency?

## The zoo (one interface: fit, predict_proba, explain; MEMBERS in zoo.py)

| member | what |
|---|---|
| lgb | LightGBM as the daily retrain has it today: decision labels with model.params_for (F3's adopted settings, the factory's tuning reused, not repeated), select labels as selmodel.fit |
| logit | logistic regression on every feature (median fill, 1/99 % clip, standardised): the baseline |
| hgb | scikit-learn's histogram gradient boosting, the second boosting library in the image (no XGBoost or CatBoost in it; requirements unchanged) |
| online | online logistic regression (SGD, log loss) fed in time order; in the walk-forward it learns hour by hour every row whose label has become known |
| hazard | discrete-time competing risks over the holding time (intervals 0, 10, 30, 60, 120, 300 s and after): exit at a loss ("dump") or at a gain first; only for the select win labels, whose rows carry the label book's exit time and return |

Not built: the sequence model on the first seconds of trades. The lab image has no torch and the rows have no
per-second sequences; the member slot stays open.

## The labels (R2's, realistic entry and exit)

`win30`, `win300` on the study's decision rows (`rows/latest.parquet`, the `_r` columns); `win0t`, `rug0t`, `win5t`,
`rug5t` on the select rows (`rows/select.parquet`, Y10's trend features), with a new feature `rug_share_1h` (the share
of rugs among the migrations whose 60 s rug window ended in the hour before, from the rows' own labels).

## The selector (selector.py)

- Walk-forward by UTC day: each member trained on the rows whose label was known before the day (purged by the
  label's horizon, the newest 300,000 at most) predicts the day.
- Candidates: the members and the blend (non-negative weights summing to one, minimising the log loss of the members'
  out-of-sample predictions of the 7 days before).
- Pick per day from the days before it: incumbent first `lgb`; a challenger takes over only when its log loss was
  lower than the incumbent's by more than one standard error of the per-row differences on each of the last 5 days
  (among several, the lowest 7-day loss); a member worse than `logit` on each of the last 7 days is retired (a
  retired incumbent is replaced by the lowest 7-day loss).
- The pick's probabilities calibrated by isotonic regression on its own out-of-sample predictions of the 7 days
  before (at least 200 rows with both classes), bounded to [0.01, 0.99]. The bound was set after a smoke run of the
  walk-forward on the four select labels (before this file was committed) showed unbounded isotonic steps at 0 and 1
  costing the selector more log loss than the calibration gained; it is the only change made after that run.

Regimes: per select row a heat score, the mean of the percentiles (among the training rows) of new pools per 15 min,
buy volume per 15 min and `rug_share_1h`; cold, normal, hot at the training rows' terciles. Decision rows: new coins
in 10 min (`market_10m`). Reported: per regime the candidate with the lowest log loss. The features are in the
members; the split is reported, it does not pick.

## Test 1: selector against the best single model

Rows as written by the study of 2026-10-26 (days 2026-10-20 to 2026-10-26). Test days: the full UTC days from the
second with at least 200 (decision rows: 500) training rows and 50 test rows, before 2026-10-26. Scored days: the
test days from the second on (the first has no out-of-fold day for the blend or the calibration). The best single
model: the member with the lowest pooled log loss over the scored days, chosen in hindsight (favours the members).

Statistic per label: the per-row log loss of the best member less the selector's, averaged per hour of decision
time; the Sharpe of those hourly means; deflated (metrics.deflated_sharpe) with the number of trials = every
(label, member) comparison of this study (4 or 5 members a label, 26 in all) and the variance of their Sharpes. The
selector beats the best model on a label when the deflated probability is at least 0.95 (deflated p at most 0.05).
**Yes** for question 1 only if it does so on at least 4 of the 6 labels.

## The allocator (allocator.py)

Arms (registered): `P_pool0_wait` (the live bot's), `P_pool0_wait_lock` and `P_pool5_top30t` (R2's two strategies
with an edge). Y16 found no rug filter that held out of sample: no rug-filtered arm. A day's reward: the log growth
of a wallet putting 10 % of itself into each trade closed that day, sum(log(1 + 0.1 x return)), 0 without a trade.
Posterior: normal-inverse-gamma on the daily rewards, prior mean 0, the days weighted with a half-life of 7 days;
P(best) from 10,000 draws. Floor 5 % for each arm not guarded; guard: an arm 30 % or more under its 14-day peak
gets no weight (all guarded: stay out). Choice: one draw from the weights, seeded by the day.

## Test 2: allocator against the best single strategy

Realistic replay of the record to 2026-10-26 00:00 UTC (smallwallet.replay: R1's model fitted to the live bot's
orders of the 7 days to the cutoff, every candidate a realistic book at 0.1 SOL without limits, the select models
trained day by day), the three arms' entries with every cost and failed buys at their fee. Test days: R2's
out-of-sample rule, the full days on which every arm has its models. Each day the allocator decides from the days
before it only (the first from its prior) and earns its pick's reward. The best single strategy: the arm with the
highest total reward over the test days, chosen in hindsight. Statistic: the daily reward of the allocator less the
best arm's, its Sharpe per day, deflated with 3 trials (one per arm) and the variance of the three comparisons'
Sharpes. **Yes** for question 2 only with a deflated probability of at least 0.95 and at least 10 test days; with
fewer days the answer is "not shown", whatever the numbers.

The forward check: the same allocator on the collector's realistic paper books since they started (2026-10-24
01:43 UTC), reported, not tested.

## What follows

- The daily retrain runs the zoo and the selector from the deploy (`reports/pumpfun_rt/zoo.md`) and the allocator
  (`reports/pumpfun_rt/allocator.{json,md}`, a line on the daily card). Nothing a paper book or the live bot reads
  changes: the paper books keep LightGBM until a later run of Test 1 says yes; the allocator only reports which
  strategy it would pick and why. The live bot keeps the owner's strategy.
- The smoke run named above saw the select labels' member losses; nothing else was looked at before the commit.
- Trials: 26 model comparisons and 3 strategy comparisons, this study's own count, written in the result.
