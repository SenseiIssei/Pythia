# Which coins to buy at the migration (Y9): pre-registration (2026-10-23)

Written and committed before any replay below was computed. Code: `lab/pumpfun_rt/selfeat.py` (the decision
features and the label book), `lab/pumpfun_rt/selmodel.py` (the models), `lab/pumpfun_rt/select9.py` (the run),
`lab/pumpfun_rt/pipeline.py` (`_build_y9`, the filter key `select`, `Pipeline.select_ok`), `lab/pumpfun_rt/sim.py`
(`Engine(select=True)`), the daily study and retrain (`study.py`, `retrain.run_y9`); tests
`tests/test_pumpfun_select_y9.py`. Paper only: nothing here holds a wallet, reads a key, signs or sends anything;
the live service, its executor, its sizing and its confirmation file are not touched (the live service builds its
engine without the select tracker, so a select filter there would only ever skip), and the live executor's files are
only read. A change to anything below after the first result is a new trial with a new name.

## Why

The live bot trades `P_pool0` (buy the PumpSwap pool at the migration, +30 %, stop -20 %, 300 s). Y5, Y7 and Y8
found no exit that helps and no clear edge. The problem looks like which coins, not how to leave them: a quarter of
the entries more than double within an hour, many others are dumped within a minute. Y9 asks whether a model that
sees what the engine sees at the migration (or in the pool's first seconds) can pick the migrations worth buying.

## What was looked at before this plan

Disclosed: Y5's, Y7's and Y8's reports and pre-registrations; the live executor's measured file (the latency of
each P_pool0 fill from the Sender path, 2026-10-22 21:41 UTC, to the cutoff: 28 buys and 28 sales, section 4); the
record's list of days. The code change was checked by replaying every rule and every strategy that existed before
it, in one shared paper book, on the recorded day 2026-10-20 with the code before the change and after it (the Y9
strategies and the label book next to them): 18,205 closed trades and 1,013 failed buys, identical field for field
(the pid aside, section 9), skip counts included; and on synthetic records in the tests. Only the equality was
looked at, no return of any book. No label, model or variant below was computed on the record.

## 1. The decision rows

A row is one buy of the label book (`selfeat.LabelPipe`): every migration of a plain SOL pool (no other quote mint,
no mayhem mode, no fee-free curve with erratic reserves) whose pool state is known at the signal, bought as P_pool0
buys it (0.1 SOL, P_pool0's exits, the measured latency of section 4), at two entries:

- **entry 0**: at the migration (P_pool0's signal);
- **entry 5**: 5 s after the migration (the pool must have a state then).

The label book has no slot, exposure or loss limit (it measures every migration; only the kill switch, never set
in a replay). It runs in its own pid space and writes nothing into the engine's record, so the books next to it are
unchanged (tested). A failed buy is a row too.

## 2. The features (what the engine knows at the signal t, nothing after)

All read by one call, `selfeat.decision_features(eng, tok, t)`, which the label book and the pipeline's filter both
use:

- **the token** (`tokens.Token.features`, as every model of the lab): age, buys, sells, unique buyers and traders,
  SOL in and out, the last 10 s, price over the start and the peak, the dev's buy, holding share, share sold, time
  since its first sale, the top-1 and top-5 holders' shares, the first five buyers' share, the creator's history
  (tokens made, completed, dumped, rates, time since the last, the market's creations in 10 minutes), name, fee and
  hour;
- **the early buyers' reputation** (`wallets.EarlyBuyers`, the WalletBook point in time): known wallets, smart
  wallets (3+ early buys, 2+ and 20 %+ of them completed), flipper share, the shrunk completion rate, dumpers among
  the early buyers, the creator's own early-buy record;
- **the curve's last minutes** (`MIG_FEATURES`, taken at the completion from the curve trades before it): age at
  the completion; for the last 1, 5 and 15 minutes before it the buys, sells, SOL bought, SOL sold, net SOL and
  unique buyers; the number of wallets that ever sold; the top-10 holders' share and the dev's share at the
  completion; **trending**: the coin's share of all curve trades of all coins in the last 1 and 5 minutes before
  its completion, the market's curve trades in those 5 minutes and the completions of the hour before; seconds
  since the completion;
- **entry 5 only, the pool's first seconds** (`POOL_FEATURES`, pool trades from the completion to t): trades, buys,
  sells, net SOL in, net SOL over the pool's SOL before its first trade, the largest sale over the pool's SOL before
  it, sales of 2 % or more of the pool's SOL, the price change since the first pool trade, seconds from the
  completion to the first pool trade.

No look-ahead: the completion snapshot exists only once the curve has completed at or before t, the pool part counts
only trades at or before t, and every other feature is the engine's point-in-time state. Tested: every label row of
a synthetic record equals the features of the same record cut at the row's decision time.

## 3. Labels

- **ret**: the label book's trade return over the stake after every cost (the fill at the measured latency, the
  pool's fee, two transaction fees; a failed buy its fee); P_pool0's own trade on that migration, drawn with
  P_pool0's latency key, so it equals what an unconstrained P_pool0 book gets (tested).
- **win**: ret above zero.
- **rug**: the pool's price at any pool trade within 60 s after the signal at or under half the price at the signal.

Four labels: win0, rug0 (entry 0), win5, rug5 (entry 5).

## 4. Models (`selmodel.py`)

Per label: LightGBM (`n_estimators` 200, `learning_rate` 0.03, `num_leaves` 7, `min_child_samples` 20, `subsample`
0.8 every iteration, `colsample_bytree` 0.8, `reg_lambda` 1.0) on the oldest 80 % of its training rows by decision
time; its probabilities are used as they are (no recalibration). The base rate is the label's rate over all its
training rows; the **top-30 % threshold** is the 70th percentile of the model's predictions on the newest 20 % of its
training rows. Features: entry 0 every feature above but the pool's; entry 5 all of them. A row trains a model for
time T only if its decision was 15 minutes before T (its labels known by then). Under 200 training rows, or one class
only in the 80 %: no model.

Baseline: a logistic regression on the same features (standardised, missing values the training median,
`model.logistic`), and the training base rate. Both are scored next to the LightGBM model walk-forward by UTC day
(each day tested by the models trained on the rows before it): pooled AUC, Brier score and its skill over the base
rate, log loss, calibration error; and, descriptive, the mean label return of all tested rows, of the rows in the
top 30 % and of the rows under the base rate. Reported, not judged: the verdict is on the strategies.

## 5. The strategies

All: family E, P_pool0's exits exactly (+30 %, the whole position in one sale; stop -20 %; time stop 300 s after the
landing; no dev-sell, pull, trail or risk-model exit), stake 0.1 SOL.

| book | strategy | entry | filter |
|---|---|---|---|
| X0 | `P_pool0` (unchanged) | migration | none |
| S1 | `P_pool0_norug` | migration | P(rug0) at most its base rate |
| S2 | `P_pool0_top30` | migration | P(win0) at or above its top-30 % threshold |
| S3 | `P_pool0_norug_top30` | migration | both of S1 and S2 |
| S4 | `P_pool5_top30` | migration + 5 s | P(win5) at or above its top-30 % threshold |
| S5 | `P_pool0_smart2` | migration | 2 or more smart wallets among the early buyers (the existing `smart_min` filter, no model) |

The filters S1 to S4 are the pipeline's new key `select` (`Pipeline.select_ok`): ("max", k) needs P at most k
times the model's base rate, ("top", q) P at or above the threshold of the top q; without the engine's select
tracker, a model or its threshold the signal is skipped as "no model". Checked after the existing filters, so no
existing strategy is affected.

## 6. Record, latency, costs, limits

- **Record**: every recorded day from the record's start (2026-10-20) up to the cutoff **2026-10-23 08:00 UTC** (the
  last complete UTC hour at registration). Entries until 15 minutes before the cutoff. Warm-up as Y7/Y8 (none: the
  record starts the history).
- **Walk-forward**: one replay. At the end of every UTC day the four models are trained on the label rows so far
  (decided 15 minutes before the next day starts) and used for every signal of the next UTC day (`DayModels`, by the
  signal's own time). **Out of sample**: from the first UTC day on which all three traded models (win0, rug0, win5)
  exist, to the cutoff; earlier days are in sample (reported, not judged). X0 and S5 need no model; they are judged
  over the same out-of-sample window.
- **Latency (measured)**: Y5's model (`reallat.LogKDE`, a lognormal kernel on each point in log space, Silverman
  bandwidth with a floor of 0.25, draws clipped to 1 to 60 s) on the live executor's P_pool0 fills from the Sender
  path to the cutoff: rows of `measured.jsonl` with what = fill, lat_ms set, mode test, rule P_pool0; buys and sales
  apart; under 1 s set to 1 s, over 60 s to 60 s. 28 buys and 28 sales: Y8's 26 each plus the buys 1,165 and 14,912
  ms and the sales 3,916 and 1,000 ms (`select9.SENDER_BUY_MS`, `SENDER_SELL_MS`).
- **Fee**: 0.001005 SOL per transaction; a failed buy pays it.
- **Draws**: every book and the label book draw with P_pool0's key (mint, leg): a migration's buy is the same draw
  in all of them (at entry 5 counted from its later signal).
- **Limits**: each book is one pipeline with one Risk, at most 4 positions, exposure cap 0.6 SOL, under two daily
  loss limits, both judged: **L25, 0.25 SOL** (the live bot's) and **L100, 1.0 SOL** (the code's cap; Y8 found that
  at 0.25 SOL a book stops for the UTC day after two or three stops, and showed the larger limit after its result,
  not registered; here it is registered).
- **Gapped trades** kept (Y8's rule).

## 7. Reported, per book and limit (out of sample)

Entries (closed trades plus failed buys), the hours they fall in, mean and median return per entry over the stake
after every cost, win rate, total P&L in SOL, the hour-block 90 % band of the mean (`study.boot_mean`), the maximum
drawdown, the exits, the skips (no model, filtered out, no pool state, daily loss limit); against X0 the difference
of the means with its band and on the migrations both entered (Y7's pairing, not judged); the in-sample half; the
deflated probability of each book's daily P&L in the lab's pool (`study.deflated_p`, n/a under 5 days); the models'
walk-forward scores (section 4) and the training rows per day.

## 8. Verdict

Per limit, a filter is **better than X0** (out of sample, gapped trades kept) only if both hold, as Y8:

1. the difference of its mean return per entry against X0's has an hour-block bootstrap 90 % band above zero
   (`study.boot_diff`, 5,000 draws, the same hours drawn for both, each book's mean over all its own entries,
   failed buys included); with fewer than 10 hours of entries in either book the band is n/a and the answer is no;
2. its total P&L is higher than X0's.

A filter is recommended for the live bot only if it is better than X0 under both limits. Every filter is reported,
whatever the answer. **Trials**: five filters under two limits, `strategies.SELECT_Y9_TRIALS = 10`, added to
`strategies.N_TRIALS`.

## 9. Code changes

`selfeat.py`, `selmodel.py`, `select9.py` (new); `sim.Engine(select=False)` (the tracker only where asked: the paper
books in the collector, the daily study and this run; the live service does not ask); the filter key `select` and
`Pipeline.select_ok`; `pipeline._build_y9` appended to `pipeline.STRATEGIES`; `model.load` also reads the select
models; the daily study's two passes get the select tracker and a label book (in-sample select models for the
study's own judgement of the new strategies, and the rows of the whole record, `<data>/pumpfun_rt/rows/
select.parquet`), and the daily retrain trains the select models on those rows (`retrain.run_y9`: walk-forward
report `reports/pumpfun_rt/select.md`, the models `models/pumpfun_rt/sel_<label>.json` and `sel_policy.json`), in the
existing jobs `pumpfun-rt-study` and `pumpfun-rt-retrain`, no new job. Every strategy and rule that existed before
trades exactly as before (section "What was looked at"; the pid in a shared book shifts because the new strategies
take pids too, which also orders two sales landing in the same millisecond differently; the ledger has no pid).

## 10. Paper forward test

The five strategies join `pipeline.STRATEGIES`, 0.1 SOL each, so the paper engine runs them once the owner deploys
the lab code; their models come from the daily retrain (until its first run after the deploy, S1 to S4 skip "no
model"). Nothing goes live: the live executor trades the strategy its confirmation file names.

## 11. Too early

About two and a half days of record; the first model needs 200 rows, so the out-of-sample window is about a day
and a half at most, and under the 0.25 SOL limit a few hours per book. The verdict says what this record shows; the
paper books are where the evidence has to come from.
