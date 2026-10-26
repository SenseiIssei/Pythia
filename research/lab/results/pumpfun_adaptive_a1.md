# An adaptive model zoo and strategy allocator for pump.fun (A1): result (2026-10-26)

Pre-registration: `results/pumpfun_adaptive_a1_prereg.md` (committed before the first run). Code: `lab/pumpfun_rt/zoo.py`
(the members), `selector.py`, `allocator.py`, the study `adaptive_a1.py`; tests `tests/test_pumpfun_adaptive_a1.py`.
Paper only; the live bot is unchanged. Reproduce: `python -m lab.pumpfun_rt.adaptive_a1 run --out DIR` (the replay
takes about 25 minutes; `--replay FILE` reads a saved one).

## Short answer

- **Does the selector beat the best single model out of sample? No**, on 0 of 6 labels (needed 4; 26 comparisons in
  the deflation). In 3 to 4 scored days the evidence rule (5 days ahead beyond the band) could not fire, so the
  selector stayed with LightGBM every day; its isotonic calibration on a few hundred out-of-fold rows made it worse
  than raw LightGBM on 4 of 6 labels. The best single member is scikit-learn's histogram boosting (`hgb`) on all six.
- **Does the allocator beat the best single strategy on realistic paper at the live latency? No**: 4 test days
  (10 needed for a yes), the allocator's 10 % wallet +73 % in log growth against +231 % for the best single
  strategy, `P_pool0_wait_lock` (deflated p of the allocator being better 0.97, i.e. no sign of it).
- **A hint, not a result:** the stacked blend (weights fitted on the days before) had the lowest log loss on all six
  labels and in every market regime but one. It is a candidate of the selector, so it takes over by itself once it
  stays ahead beyond the band for 5 days; nothing a paper book reads changes before the study says yes.

## Test 1: the selector against the best single model

Rows as written by the study of 2026-10-26: 133,704 decision rows with a realistic label on the 4 scored days, 739
and 909 select rows (entries 0 and 5) on 3. Log loss, lower is better; "best less selector" the per-hour mean of the
per-row difference (negative: the selector is worse).

| label | rate | selector | lgb | logit | hgb | online | hazard | blend | best | best less selector | deflated p | beats |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| win30 | 0.054 | 0.1601 | 0.1593 | 0.1601 | 0.1564 | 0.1743 | | 0.1557 | hgb | -0.0040 | 1.000 | no |
| win300 | 0.044 | 0.1566 | 0.1555 | 0.1558 | 0.1532 | 0.1735 | | 0.1509 | hgb | -0.0042 | 1.000 | no |
| win0t | 0.562 | 0.6972 | 0.6674 | 0.7182 | 0.6611 | 0.6893 | 0.7262 | 0.6506 | hgb | -0.0302 | 1.000 | no |
| rug0t | 0.070 | 0.2422 | 0.2383 | 0.2404 | 0.2321 | 0.2791 | | 0.2232 | hgb | -0.0093 | 1.000 | no |
| win5t | 0.554 | 0.6567 | 0.6647 | 0.6919 | 0.6555 | 0.6959 | 0.7066 | 0.6456 | hgb | +0.0013 | 1.000 | no |
| rug5t | 0.063 | 0.2213 | 0.2204 | 0.2553 | 0.2179 | 0.2529 | | 0.2114 | hgb | -0.0012 | 1.000 | no |

- The selector picked `lgb` (the incumbent) on every test day of every label: with 4 or 5 test days no challenger
  can have the 5 days ahead the rule asks for, and no member was 7 days behind the logistic baseline.
- `hgb` beat today's LightGBM on all six labels by 0.002 to 0.009 in log loss; the blend beat `hgb` by 0.001 to 0.011.
  Neither is the registered question, and with 3 to 4 days neither is a finding.
- The online logistic regression, learning every closed trade hour by hour, was the worst member on the decision
  labels (0.174 against 0.156); the competing-risks hazard model was behind the logistic baseline on both win labels.
  Both would be retired after 7 such days.
- Calibration: the isotonic step on the pick helped on win5t and hurt on the other five (win0t +0.030). The bound to
  [0.01, 0.99] was set after a smoke run of the select labels, before the pre-registration was committed (written
  there).

Per market regime (heat from new pools and buy volume per 15 min and the share of rugs in the last hour; decision rows:
new coins in 10 min), the lowest log loss over the test days: the blend in every regime of every label, except
rug5t's normal regime (`hgb`). No regime asks for another model than the others.

## Test 2: the allocator against the best single strategy

The realistic replay of 2026-10-20 to 2026-10-25 (R1's model fitted to the live bot's orders of the 7 days to the
cutoff, each arm a realistic book at 0.1 SOL without limits; 1,311 entries of P_pool0_wait and of its lock, 401 of
P_pool5_top30t). Test days: from the first with every arm's models (2026-10-22). A day's reward: the log growth of a
wallet putting 10 % of itself into each of the day's trades (no slot limit, so an upper bound on what 10 % with 3
slots would do).

| day | allocator's pick | P_pool0_wait | P_pool0_wait_lock | P_pool5_top30t | allocator |
|---|---|---|---|---|---|
| 2026-10-22 | P_pool0_wait_lock (prior only) | -39.6 % | +50.0 % | +44.0 % | +50.0 % |
| 2026-10-23 | P_pool5_top30t | -93.9 % | -12.7 % | +5.7 % | +5.7 % |
| 2026-10-24 | P_pool5_top30t | +116.4 % | +204.9 % | +28.6 % | +28.6 % |
| 2026-10-25 | P_pool0_wait_lock | +32.4 % | -11.6 % | -29.7 % | -11.6 % |
| total | | +15.3 % | +230.7 % | +48.5 % | +72.7 % |

The allocator less the best single strategy: -39.5 points a day, deflated p 0.97 for "the allocator is better" (3
trials). The ranking of the arms changes every day; the allocator had the day's best arm on 2 of the 4 days. Spreading by the weights instead of one draw would have made +112 % (not tested).

Forward, on the collector's realistic paper books (since 2026-10-24 01:43 UTC, one full day, not tested): on
2026-10-25 P_pool0_wait made +170 % in log growth at 10 % a trade, its lock +50 %, P_pool5_top30t +16 %. The paper
P_pool0_wait's day differs from the replay's (+32 %): the paper book trades the live stream with its own slots, loss
limits and latency draws, the replay without limits; one day says nothing either way.

## What it means for the owner

Neither the model selector nor the strategy allocator has shown that it beats simply keeping the best single choice,
and with 3 to 5 days of realistic rows they could not: the rules that keep them honest (5 days of evidence, 10 test
days) need more days than the record has. Both now run every day in the retrain and report, they learn as the days
come in, and nothing they say changes a paper book or the live bot:

- `reports/pumpfun_rt/zoo.md`: per label the selector's pick, every member's and the blend's log loss over the last 7
  days, the blend's weights, retirements and the winner per regime. The history (`models/pumpfun_rt/zoo/state.json`)
  only grows; a day is tested once.
- `reports/pumpfun_rt/allocator.json` and `.md`, and a line on the daily card: which of the three strategies the
  allocator would pick, its P(best), the guard, and that the live bot keeps the owner's strategy.

The live bot keeps the owner's strategy. Re-running this study after 14 more days (10 allocator days, the evidence
rule able to fire) answers both questions with enough data; until then the honest answer is no.

Trials: 26 model comparisons and 3 strategy comparisons in this study (the deflation's counts).
