# M1: current model techniques as candidates, judged by the same bar

The owner asked whether newer technology can improve the models. Six techniques went in as learners and tools
that the model factory and the existing models can use, and each was judged by the bar its incumbent already
faces. In short: **none of them beats its incumbent under that bar**. Two things pass a bar but have nothing that
uses them yet: the foundation models' next-day volume forecast, and the conformal intervals, which give the
coverage they promise. Nothing is live and no book changes. This is paper only.

Code: `lab/models/factory.py` (the learners, the bar, the loan to the pump.fun zoo), `lab/models/fm.py`
(Chronos-Bolt, TimesFM, cache, time budget), `lab/models/conformal.py`, `lab/models/metalabel.py`, the study
`lab/experiments/modern_m1.py`, tests `tests/test_modern_m1.py` (tiny fakes, no network, no torch). The image is
`research/lab/Dockerfile.ml`: the lab image plus torch's CPU wheels, every package pinned. Only the job
`modern-models` uses it (monthly, off until the image is built). The weights are pinned by revision and
downloaded once into `<data>/models/hub`. Forecasts are cached in `<data>/models/fm_cache`.

The run: 2026-10-27, in the agent container on the lab server (the VPS, 8 CPUs; the models were given 3 threads),
on the server's data folder read only. The runtimes and the memory below are this machine's. TimesFM ran while
the tabular part ran beside it, so its runtime is an upper bound.

## Licences

| model | revision | licence | used |
|---|---|---|---|
| Amazon Chronos-Bolt small (`amazon/chronos-bolt-small`) | `772f3d25` | Apache-2.0 | yes |
| Google TimesFM 2.5 200M PyTorch (`google/timesfm-2.5-200m-pytorch`) | `1d952420` | Apache-2.0 | yes: the newest open checkpoint that runs on CPU |
| Google TimesFM 3.0 (`google/timesfm-3.0-pytorch`, 2026-09) | `43046b85` | TimesFM Non-Commercial License v1.0 (no production use, results not to be used in commercial decisions) | no |
| TabPFN v2 classifier (`Prior-Labs/TabPFN-v2-clf`, file `tabpfn-v2-classifier-finetuned-zk73skhh.ckpt`) | `f851f2a3` | **Prior Labs License 1.1** (Apache 2.0 with an added attribution clause; commercial use allowed) | yes |
| TabPFN 2.5, 2.6, 3 and 3.5 (`Prior-Labs/tabpfn_2_5` to `tabpfn_3_5`) | | TABPFN-2.5/2.6/3/3.5 License v1.0 or v1.1: non-commercial and non-production only, and "not available to consumers within the meaning of Section 13 BGB" | no |
| `tabpfn` package 9.2.0 (code) | | Apache-2.0 | yes |
| CatBoost 1.2.10 | | Apache-2.0 | yes |

TabPFN's licence allows this private, non-commercial research use. The newer TabPFN releases would not: as a
private person the owner is a consumer under section 13 BGB, and their terms exclude consumers outright. The
Prior Labs License's attribution clause applies only when the weights or a product containing them are passed on.
Internal benchmarking is excluded from it. The weights are not in this repository. Built with PriorLabs-TabPFN.

## 1. Time-series foundation models, zero shot

The bar is the zoo's gate (`core.evaluate`, here `factory.gate`): a lower mean loss than the other forecast on the
same rows, with a Diebold-Mariano p under 0.05 on the per-day means. Every row is out of sample for both sides.
The zoo's incumbents are scored by their newest quarterly walk-forward holdout in the registry (M8q and M10,
version 20261025T0715). The foundation models get each coin's own values up to and including that day, at most
512 of them, and nothing later. The test replaces every later value and gets the same forecast.

| model | target (rows from 2024-01-01) | loss | incumbent | baseline | vs baseline | vs incumbent |
|---|---|---|---|---|---|---|
| Chronos-Bolt small | next-day return q10/q50/q90, pinball (bps), 15 coins, 15,405 rows | 105.2 | M8q 103.9 | 105.5 | fails (p 0.39) | fails, worse (p 0.022) |
| TimesFM 2.5 | the same | 105.8 | M8q 103.9 | 105.5 | fails, worse (p 0.65) | fails, worse (p 0.005) |
| Chronos-Bolt small | next-day realised variance, QLIKE, 20 coins, 20,540 rows | 0.406 | M10 0.326 | HAR 0.390 | fails, worse (p 0.54) | fails (p 0.15) |
| TimesFM 2.5 | the same | 0.377 | M10 0.326 | HAR 0.390 | fails, 3.4 % lower but p 0.14 | fails (p 0.16) |
| Chronos-Bolt small | next-day log quote volume, squared error, 20,520 rows | 0.190 | none in the zoo | 7-day mean 0.279; today's 0.261 | **passes** (p 1e-47; 1e-25) | n/a |
| TimesFM 2.5 | the same | 0.176 | none in the zoo | 7-day mean 0.279; today's 0.261 | **passes** (p 1e-48; 3e-32) | n/a |

The return quantiles are close to the baseline's and worse than M8q's. Their own coverage is fair (q10 12.5 %
and 11.2 %, q90 88.6 % and 88.5 %), but they know nothing about volatility regimes beyond the coin's own past. The
variance forecasts lose to M10. TimesFM is a little better than HAR, but not significantly (p 0.14). The variance
is the exponential of the forecast median of log RV with the lognormal correction from the 10-90 % spread. Volume
is the one target where both models clearly beat naive forecasts. No zoo model and no book forecasts volume, so
there is no incumbent and nothing to replace. A HAR-style regression on log volume, a stronger baseline, was not
tried. Before anything used the volume forecast, it would need a study of its own (liquidity sizing, slippage).

Runtime: Chronos-Bolt took 10.3 ms a series (589 s for 56,485 forecasts, peak 1.2 GB). TimesFM 2.5 took 104 ms
a series (5,853 s, peak 2.3 GB). The budget per run is `--budget-min`, and the cache makes a rerun free (4 s).

### As inputs to the incumbents

Chronos-Bolt's forecasts were added as features from 2021-03: the forecast median and the 10-90 % spread of log RV
for M10, and the three return quantiles over the coin's 30-day vol for M8q. The bar is each incumbent's own
LightGBM, refitted on the same quarterly folds from 2023-01-01 with and without those inputs, under the same gate.

| incumbent | with | without | rows | folds won | DM p | verdict |
|---|---|---|---|---|---|---|
| M10 (QLIKE) | 0.3264 | 0.3298 | 27,436 | 9 of 16 | 0.33 | fails (1.0 % lower) |
| M8q (pinball) | 0.01006 | 0.01007 | 20,677 | 10 of 16 | 0.24 | fails (0.1 % lower) |

389 s, of which 338 s were the 33,512 new Chronos forecasts. TimesFM was not tried as an input, because a
forecast for every training row since 2021 would cost about 3 hours.

## 2. TabPFN v2 for the small tabular problems

**pump.fun selection.** TabPFN v2 was lent to the A1 model zoo's walk-forward (`selector.walk`, trained on the
rows whose label was known before each UTC day, purged by the label's horizon). It ran next to LightGBM (the
incumbent, with F3's settings), the logistic baseline, the histogram boosting and CatBoost, on R2's select labels
over 5 test days (2026-10-22 to 26, 1,005 to 1,238 rows). The decision labels win30 and win300 have 172,492
training rows, over the CPU cap of 3,000 (`PYTHIA_TABPFN_MAX_ROWS`), so TabPFN skipped them and said so. The bar
is A1's: the hourly mean of the log-loss difference, deflated (`metrics.deflated_sharpe`) over every comparison of
the part (20). It passes at p 0.95 with a positive mean.

| label | rows | lgb (incumbent) | logit (baseline) | hgb | CatBoost | TabPFN v2 |
|---|---|---|---|---|---|---|
| win30 | 129,037 | 0.1542 | 0.1586 | 0.1541 | 0.1541 | skipped (rows) |
| win300 | 128,865 | 0.1523 | 0.1528 | 0.1494 | **0.1482** | skipped (rows) |
| win0t | 1,005 | 0.6666 | 0.7147 | 0.6818 | **0.6593** | 0.6877 |
| rug0t | 1,006 | 0.2460 | 0.2782 | 0.2349 | 0.2292 | **0.2219** |
| win5t | 1,237 | 0.6686 | 0.7113 | 0.6564 | 0.6473 | **0.6316** |
| rug5t | 1,238 | 0.2229 | 0.2671 | 0.2213 | **0.2101** | 0.2174 |

In raw log loss TabPFN is the best on two of the four select labels, and CatBoost is the best on three labels
(and on win0t, where TabPFN is behind LightGBM). Against LightGBM, none of the 10 comparisons passes the bar: the
deflated p is between 0.00 and 0.05 on 4 to 5 days. Against the logistic baseline only CatBoost on win30 passes
(p 1.00), and LightGBM already does that. This is the same situation A1 was in: too few scored days. It is a lead
for the daily zoo once it has a few weeks of days, not a result. TabPFN on CPU: 2 estimators. A select day took 17 to 133 s with all five members (270 to
408 s a label), and the peak was 2.3 GB.

**Small-account regime choice.** Each day from 2018: is BTC up over the next 7 days? There are 14 inputs from
closes up to that day (BTC's, the S&P's and gold's returns, vol, distances to the 100 and 200-day means, ETH
against BTC, breadth of the six assets). Every learner was walked forward by calendar year from 2020 (trained on
the labels known before the year). The incumbent is S2/F2's rule (BTC above its 200-day mean), as a probability.
The bar for the classifier is the zoo's gate on log loss (lag 7 days). For the wallet it is F2's held-back bar: a
40 and a 100 EUR BTC wallet with F2's costs, open when p > 0.5, decided weekly, 2024-01-01 to 2026-10-11, with a
drawdown under 20 %, above holding SPYx at both sizes, positive filled a close late, deflated p above 0.95 over
F2's pool (143 trials). It also has to beat the rule's own wallet in 95 % of paired bootstrap draws.

| gate | log loss (2,469 days, base 0.6942) | 40 EUR CAGR | drawdown | Sharpe | above SPYx | deflated p | Sharpe above the rule's |
|---|---|---|---|---|---|---|---|
| rule (incumbent) | 0.6949 | 22.0 % | 32.4 % | 0.74 | yes | 0.16 | n/a |
| logit | 0.7287 | -2.3 % | 56.2 % | 0.13 | no | 0.02 | 0.12 |
| LightGBM | 0.7367 | -7.4 % | 58.1 % | -0.03 | no | 0.01 | 0.07 |
| hgb | 0.7771 | -3.2 % | 50.9 % | 0.08 | no | 0.02 | 0.12 |
| CatBoost | 0.8133 | 10.5 % | 51.6 % | 0.46 | no | 0.07 | 0.31 |
| TabPFN v2 | 0.7856 | 11.2 % | 43.6 % | 0.48 | no | 0.08 | 0.29 |

No learner forecasts a week of BTC better than the base rate, the rule included. Every learner's wallet does
worse than the 200-day rule's. TabPFN is the least bad of them (drawdown 43.6 %) and still fails every gate but
the late fill. The rule's own wallet fails F2's bar too: a drawdown of 32.4 % and a deflated p of 0.16. SPYx held
made 20.0 % with a drawdown of 23.0 %, and BTC held 24.7 % with a drawdown of 51.9 %. 204 s, of which TabPFN took
198 s.

## 3. CatBoost next to LightGBM

CatBoost (300 trees, depth 4, l2 10, ordered boosting) is in the factory's learner list next to LightGBM, and it
ran in every part above. It is the best raw log loss on win300, win0t and rug5t in the pump.fun zoo, without
passing A1's bar against LightGBM. It is the worst learner on the regime choice (0.8133) and on meta-labelling
(below). It is cheap: a day with 172,000 training rows took 23 to 45 s for all four members together.

## 4. Conformal prediction

The method is rolling split conformal, 80 % intervals (alpha 0.2). For day d the calibration set is the scores of
the 180 days before d whose outcome was known before d, and with fewer than 100 scores there is no interval. The
score is conformalised quantile regression's, max(lo - y, y - hi) (Romano, Patterson and Candes 2019). The bar is
coverage within a point or two of 80 % on the held-back days, and for the sizing, the factories' bar.

| model | raw coverage | conformal coverage | width | per coin |
|---|---|---|---|---|
| M8q's 10-90 % range, from 2024 | 77.4 % (width 9.34 %) | **79.9 %** | 9.93 % | 77.1 to 83.4 % |
| M10's variance (point forecast, interval on log RV), from 2024 | none | **80.3 %** | 1.22 log units | |

The intervals do what they promise. M8q's range was 2.6 points too narrow, and conformal widens it by 0.6 of a
point of return. **Sizing variant**: a 15-coin trend book (a coin at 1/15 while its 30-day return and its distance
to its 200-day mean are both positive), daily, 35 bps a unit of turnover, held back from 2024. The same book was
then scaled per coin by the median width of the past 180 days over today's width (0.25 to 1, never above full
size). Unscaled: Sharpe 0.43, drawdown 47.9 %. Scaled: Sharpe 0.25, drawdown 39.7 %. The scaled Sharpe is higher
in 9 % of the bootstrap draws, with a deflated p of 0.00 over the weekly factory's 1,279 trials. **It fails**:
shrinking the book when the interval widens cut the drawdown but also cut the rebounds. 1 s.

## 5. Meta-labelling of the factory survivors

A trade is a run of days a survivor holds an asset. Its label is whether the log return from the entry close to
the exit close beats the round trip: 1 % for a small wallet, 2 x 35 bps for the weekly factory. A second model
uses 11 inputs known at the entry (the asset's returns and vol, distances to its means, BTC's trend, the book's
size that day, the trade's weight, days since its last trade). It was walked forward by year from 2020 on trades
closed before each year, and as a paper filter it drops a trade under p 0.5 (the slot stays cash). The bar for
the classifier is the zoo's gate against the base rate. For the filtered book it is that factory's held-back bar,
with the factory's pool plus this part's trials, and a Sharpe above the unfiltered book in 95 % of the paired
bootstrap draws.

| survivor | trades (pay after costs) | unfiltered held back | logit | LightGBM | CatBoost | TabPFN v2 |
|---|---|---|---|---|---|---|
| F2 `07493e8a8adb` Donchian 100/50 on the six (the seed's shadow) | 138 (42 %) | Sharpe 0.96, drawdown 19.2 %, deflated p 0.27 | -0.74 | 0.83 | 0.14 | -0.60 |
| weekly `44444c97ba5e` low vol top 20 (the server's shadow) | 379 (49 %) | Sharpe 0.93 at 35 bps, deflated p 0.00 | 0.93 | 0.90 | 0.78 | 0.94 |

The table shows the filtered book's held-back Sharpe. No meta model forecasts the trades better than their base
rate: the log losses are 0.68 to 0.81 against 0.677 and 0.710. Only TabPFN on the weekly survivor is lower
(0.7092 against 0.7102), and not significantly, so every gate fails. On the F2 survivor every filter
makes the book worse, mostly by sitting out the trades that paid. On the weekly survivor they change little: the
best is TabPFN at 0.94 against 0.93, better in 49 % of the draws. **Meta-labelling fails for both.** This agrees
with C14 (`meta_daily.md`, AUC 0.45). 37 s, peak 1.0 GB.

## Runtime and memory on the VPS

| part | seconds | peak memory |
|---|---|---|
| fm: Chronos-Bolt, 56,485 forecasts (first run) | 589 | 1.2 GB |
| fm: TimesFM 2.5, 56,485 forecasts | 5,853 | 2.3 GB |
| features (33,512 more Chronos forecasts, 2 x 16 LightGBM folds twice) | 389 | 2.3 GB |
| tabular (pump.fun zoo, 6 labels, 5 members) | 1,498 | 2.3 GB |
| regime | 204 | 2.3 GB |
| conformal | 1 | 0.2 GB |
| meta | 37 | 1.0 GB |

All of it fits into the job's 3 CPUs and 6 GB. A monthly run with a warm cache takes about 40 minutes: TimesFM
pays only for the new days, and the pump.fun part and TabPFN dominate.

## What did not help, plainly

- Chronos-Bolt and TimesFM for return quantiles: worse than M8q. For variance: worse than M10, and not
  significantly better than HAR.
- Chronos's forecasts as inputs to M10 and M8q: 1.0 % and 0.1 % lower loss, not significant.
- TabPFN v2 and CatBoost in the pump.fun zoo: better raw log loss on several labels, but no comparison passes A1's
  bar against LightGBM on 5 days. TabPFN cannot take the decision labels on CPU.
- Every learner on the small account's regime choice: none beats the base rate, and none of their wallets beats
  the 200-day rule.
- The conformal sizing variant: lower Sharpe than the unscaled book.
- Meta-labelling of both factory survivors: no better than the base rate, and no filter beats the unfiltered book.

What passed a bar: the foundation models' next-day volume forecast against naive baselines, and the conformal
intervals' coverage. Neither is used by anything. A volume model would be a new zoo model (spec, shadow, gate
against a HAR-style baseline) in a study of its own.
