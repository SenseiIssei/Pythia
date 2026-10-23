# The Trends measures in our models and strategies (Y10): pre-registration (2026-10-23)

Written and committed before any replay below was computed. Code: `lab/pumpfun_rt/trendfeat.py` (the trend features
and the triggers), `lab/pumpfun_rt/trends10.py` (the run), `lab/pumpfun_rt/pipeline.py` (`_build_y10`, the filter key
`trend`, `Pipeline.trend_ok`), `lab/pumpfun_rt/sim.py` (`Engine(trend=True)`, the entry kind `trend` asked at every
10 s boundary), the trend columns of the Y9 label rows (`selfeat.py`) and of X14's early rows (`early.py`), the
models with the trend features (`selmodel.py`: `win0t`, `rug0t`, `win5t`, `rug5t`; `exitpol.py`: `et_<label>`), the
daily study and retrain (`study.py`, `retrain.py` through `selmodel.train` and `exitpol.fit_live`), the meme rule
`trend_top` (`lab/onchain/meme.py`); tests `tests/test_pumpfun_trends_y10.py`. Paper only: nothing here holds a
wallet, reads a key, signs or sends anything; the live service, its executor, its sizing and its confirmation file are
not touched (the live service builds its engine without the trend tracker, so a trend filter there would only ever
skip and a trend entry never fires), and the live executor's files are only read. A change to anything below after
the first result is a new trial with a new name.

## Why

The Trends page (`trends.py`, `reports/pumpfun_rt/trends.json`) ranks pump.fun coins live by buy volume, buyers, net
flow, curve speed and fresh pool activity. It is a view: nothing trades on it. The owner wants these measures used by
the models and the strategies. Y9 found that its models rank somewhat (walk-forward AUC 0.61 to 0.67) and that its
top-30 % filters lean the right way without passing. Y10 asks two things: (a) do the trend measures make the Y9 models
better out of sample, and the P_pool0 entries those models pick; (b) do strategies built on the trend measures beat
P_pool0.

## What was looked at before this plan

Disclosed: Y9's report and pre-registration; the Trends page's code and one of its files; the live executor's
measured file (no P_pool0 fill since Y9's cutoff, so Y9's 28 buys and 28 sales are the latency, section 6); the
record's list of days and its last trade (2026-10-23 about 14:20 UTC). The code change was checked on synthetic
records in the tests and by replaying every rule and every strategy that existed before it, in one shared paper book
with the label book, on the recorded 2026-10-20 with the code before the change and after it (the trend tracker and
the Y10 strategies next to them, the server's models): 18,440 closed trades and 1,022 failed buys identical field for
field (the pid aside, as in Y9), the skip counts too; only the equality was looked at, no return of any book. No
feature, label, model or variant below was computed on the record.

## 1. The trend features (`trendfeat.TREND_FEATURES`, what the engine knows at t, nothing after)

Kept by running counters in 10 s buckets (STEP_MS) per token over the last 15 minutes: the buy SOL (curve and pool
buys, coins quoted in SOL only), the pool's SOL traded (buys and sales), the unique buyers (curve and pool), the curve
progress at the bucket's last trade; per window (1, 5, 15 minutes) every coin's buy SOL and the market's total; the
migrations; and the market's buy SOL over 15 minutes at every boundary of the last 6 hours. **No look-ahead**: a value
asked at t is the state at B, the last 10 s boundary at or before t, from the closed buckets only, so from trades
received before B. Tested: the label and early rows of a synthetic record equal the features of the same record fed
only up to its last event before B.

- `tr_rank_1m`, `tr_rank_5m`, `tr_rank_15m`: the coin's rank in "hot now" by buy SOL over the window (1 = the most;
  ties share the better rank; a coin without a buy ranks after every coin with one; NaN for another quote coin);
- `tr_n_5m`: coins with a buy in the last 5 minutes;
- `tr_share_1m`, `tr_share_5m`: the coin's share of all buy SOL of the window; `tr_vol_5m` its buy SOL over 5 minutes;
- `tr_ubuyers_1m`, `tr_ubuyers_prev_1m`: unique buyers in the last minute and in the minute before;
- `tr_speed_pm`: curve progress gained per minute over the last 5 minutes (since the coin was first seen when later);
- `mkt_buy_sol_15m` (the market's heat: all buy SOL of 15 minutes), `mkt_pools_15m` (migrations of 15 minutes),
  `mkt_heat_rel` (the heat over the median of its values at the boundaries of the previous 6 hours; NaN with less
  than 3 hours of them);
- for pools: `fp_n` (pools migrated in the last 30 minutes, "fresh"), `fp_rank` (the coin's rank among them by the
  pool's SOL traded over 5 minutes, then the newest), `fp_vol_5m` (that SOL), `fp_rel` (that over the median of the
  other fresh pools'), `fp_age_s` (seconds since the migration).

They join every Y9 label row (both entries) and every X14 early row (5 to 60 s, 25/50/75 %). They are only read where
the engine has the tracker: the paper books in the collector, the daily study and this run.

## 2. The models with the trend features

- **Select** (Y9's labels and rows): `win0t`, `rug0t` (entry 0: Y9's entry-0 features plus the trend features),
  `win5t`, `rug5t` (entry 5: Y9's entry-5 features plus the trend features). Y9's LightGBM parameters, split, base
  rate, top-30 % threshold, 15-minute purge and 200-row minimum exactly. Y9's own models keep their features, so the
  Y9 paper books do not change. Rows without trend columns (written before this change) train no trend model.
- **Early** (X14's rows and labels): `et_<label>` for mig1h, peak3x, peak10x, alive5m: `e_<label>`'s fit (the same
  rows, the same embargo, `model.fit`) on the early features plus the trend features. The `e_` models are unchanged.
- Daily: the study's passes carry the tracker, so their rows have the trend columns; the retrain trains the trend
  models next to the others (`retrain.run_y9`, `retrain.run_x14`), saved where the paper books read them.

## 3. The books

All: P_pool0's exits exactly (+30 %, the whole position in one sale; stop -20 %; time stop 300 s after the landing; no
dev-sell, pull, trail or risk-model exit), stake 0.1 SOL, each its own pipeline book (one Risk).

| book | strategy | entry | filter |
|---|---|---|---|
| X0 | `P_pool0` (unchanged) | migration | none |
| S2 | `P_pool0_top30` (Y9, unchanged) | migration | P(win0) at or above its top-30 % threshold |
| S4 | `P_pool5_top30` (Y9, unchanged) | migration + 5 s | P(win5) at or above its top-30 % threshold |
| A1 | `P_pool0_top30t` | migration | P(win0t) at or above its top-30 % threshold |
| A2 | `P_pool5_top30t` | migration + 5 s | P(win5t) at or above its top-30 % threshold |
| T1 | `P_hot5` | a 10 s boundary B: a plain curve ranked 5 or better by buy SOL over 5 minutes among all SOL coins, with more unique buyers in the last minute than in the minute before | P(alive5m) from `et_alive5m` (the early features at the coin's last passed milestone and the trend features) at least its base rate |
| T2 | `P_fresh3` | a 10 s boundary B: a plain pool ranked 3 or better among the fresh pools (pool SOL over 5 minutes), migrated 120 to 600 s before B | none |
| T3 | `P_pool0_heat` | migration | the market's buy SOL over 15 minutes at least its median at the boundaries of the previous 6 hours (3 hours of them at least) |

A trend entry fires once per coin and strategy (the engine's rule), at the first boundary at which the coin qualifies.
The filters: the existing key `select` for A1 and A2 (no model or threshold: skipped "no model"), the new key `trend`
for T1 and T3 (`Pipeline.trend_ok`; no tracker, history or model: skipped "no model"), checked after the existing
filters, so no existing strategy is affected. A1 and A2 answer (a); T1 to T3 answer (b).

## 4. Record, latency, costs, limits

- **Record**: every recorded day from the record's start (2026-10-20) up to the cutoff **2026-10-23 14:00 UTC** (the
  last complete UTC hour at registration). Entries until 15 minutes before the cutoff. No warm-up (the record starts
  the history).
- **Walk-forward**: one replay. At the end of every UTC day the select models (Y9's four and the four trend ones) are
  trained on the label rows so far (decided 15 minutes before the next day starts) and `et_alive5m` on the early rows
  so far (labelled; decided 5 minutes plus the 10-minute embargo before it), and used for every signal of the next
  UTC day (`select9.DayModels`). **Out of sample**: from the first UTC day on which every model a book uses exists
  (`win0`, `win5`, `win0t`, `win5t`, `et_alive5m`), to the cutoff; earlier days are in sample (reported, not judged).
  X0, T2 and T3 need no model; they are judged over the same window.
- **Latency (measured)**: Y9's (Y5's kernel density in log space on the live executor's 28 P_pool0 buys and 28 sales
  since the Sender path, `select9.SENDER_BUY_MS`, `SENDER_SELL_MS`); no fill was added since.
- **Fee**: 0.001005 SOL per transaction; a failed buy pays it.
- **Draws**: every book and the label book draw with P_pool0's key (mint, leg).
- **Limits**: at most 4 positions, exposure cap 0.6 SOL, under two daily loss limits, both judged: **L25, 0.25 SOL**
  (the live bot's) and **L100, 1.0 SOL** (the code's cap), as Y9.
- **Gapped trades** kept (Y8's rule).

## 5. Reported

Per book and limit, out of sample: entries (closed trades plus failed buys), the hours they fall in, mean and median
return per entry over the stake after every cost, win rate, total P&L in SOL, the hour-block 90 % band of the mean,
the maximum drawdown, the exits, the skips; every judged book against X0, and A1 against S2, A2 against S4: the
difference of the means with its band, the P&L difference, and on the coins both entered (not judged); the in-sample
half; the deflated probability of each book's daily P&L (n/a under 5 days). The models (descriptive, not judged): the
walk-forward by UTC day of every select model, Y9's against the trend one on the same rows (AUC, the logistic
baseline, Brier skill, the mean return of its top 30 %); X14's purged walk-forward of `e_alive5m` against
`et_alive5m` and `e_peak3x` against `et_peak3x` on the run's early rows.

## 6. Verdict

Y9's rule, per limit: a book is **better than** another (out of sample, gapped trades kept) only if both hold:

1. the difference of its mean return per entry against the other's has an hour-block bootstrap 90 % band above zero
   (`study.boot_diff`, 5,000 draws, the same hours drawn for both, each book's mean over all its own entries, failed
   buys included); with fewer than 10 hours of entries in either book the band is n/a and the answer is no;
2. its total P&L is higher.

(a) The trend features **improve** a Y9 filter only if A1 is better than S2 (A2 than S4) under both limits. (b) and
(a): a book is recommended for the live bot only if it is better than X0 under both limits. Every book is reported,
whatever the answer. **Trials**: five books (A1, A2, T1, T2, T3) under two limits, `strategies.TRENDS_Y10_TRIALS = 10`,
added to `strategies.N_TRIALS`. The comparisons against S2 and S4 are on the same books and add none.

## 7. Paper forward test

The five strategies join `pipeline.STRATEGIES` (`_build_y10`), 0.1 SOL each, and run in the paper engine from the
deploy on (its engine gets the trend tracker). A1, A2 and T1 skip "no model" until the daily retrain has trained
their models on rows with the trend columns (the study after the deploy writes them, the retrain after it trains
them); T2 starts at once, T3 after 3 hours of the engine's own heat history (it starts empty at every collector
restart).

## 8. The meme module

The meme module's candidates (`lab/onchain/meme.py`) carry the trend ranks of our Trends file (the place in the hot
list, ranked by buy SOL over 5 minutes among all pump.fun coins, and in the fresh list), and one new paper rule uses
them: **`trend_top`**, a migrated coin ranked 5 or better in the hot list or 3 or better in the fresh list, its
migration 5 minutes ago or more, no `win_low` badge (and, as every meme rule, no `rug_risk` badge, not blocked, the
safety check); +30 % take profit, -20 % stop, a 20 % trailing stop once +20 %, 1 h time stop, out when its best pool
lost half its liquidity; 0.1 SOL a buy out of its own 1 SOL paper account. It is the last rule, so the three
existing rules spend the run's safety checks first and trade exactly as before. It is judged by the meme module's
own pre-registered proof (`results/onchain_meme_prereg.md`, 30 days, 100 trades, the same checks) and counts as one
more trial there (`meme.TRIALS` = `len(RULES)` = 4), not in Y10's constant; there is no record to replay it on
(Jupiter's quotes are not recorded), so Y10 does not judge it.

## 9. Too early

About three days of record; the first model needs 200 rows, so out of sample is about a day and a half at most, and
under the 0.25 SOL limit a few hours per book. The verdict says what this record shows; the paper books are where the
evidence has to come from.
