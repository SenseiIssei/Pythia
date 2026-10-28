# T7: train on what pays. Pre-registration

Registered 2026-10-28 and committed before any number on the lab's data was computed (the code was written and
tested on synthetic panels only; while scoping, one look at which inputs exist on the data folder: the daily sweep
panel cache, the 1-minute history of the 15 Alpaca coins, R5's registry, no T4 delisting table; no performance
number). Brief T7 of the training plan of 2026-10-28, on the review of 2026-10-27 (`results/review_2026-10-27.md`,
sections 2 and 3), R5's registry (`metrics.trial_pool`, `<data>/trials/registry.jsonl`) and R6's windows
(`results/factory_lockbox_r6.md`). Code: `lab.models.factory` (the net target, section T7), `lab.models.metalabel`
(`sized`, the late label), `lab.experiments.cost_aware_t7`. Results go to `results/cost_aware_t7.md`. Nothing here
may change once a result exists. Paper only: no book, gate, engine setting, live path or wallet changes.

## Question

Do models trained on the return after costs and turnover beat their plain baselines after the registry's
deflation, where models trained on hit rates did not (M8's direction, C14's meta filter)?

- **A. A net target for G2.** Does a model fitted on the net objective trade better than the plain signal it
  competes with?
- **B. Meta-labelling as a size.** Does M1's meta model, used to scale a rule's positions by its probability
  instead of cutting trades, beat the plain rule and the plain filter?

## Windows (R6)

In sample to 2023-12-31, validation 2024-01-01 to 2026-06-30. The lockbox from 2026-07-01 is not read: part A
scores nothing after 2026-06-30 (G2's held-back end, `HOLD_TO` 2026-07-01 exclusive), part B cuts its panel at
2026-06-30 before anything is computed.

## A. The net target (`net1`)

- **Panel.** G2's coin panel (`m8_direction.coins_panel`, the 15 coins the Alpaca paper account lists, one row a
  coin and UTC day, everything known at the day's close). The target of a row is the next UTC day's simple return.
  The universe is today's list (T5: today's lists flatter rules); the baseline shares it, so the comparison is fair,
  the level is not.
- **Position.** A forecast f becomes pos = clip(f / s, -1, 1), s the std of the model's forecasts on its training
  rows (sign and a size capped at 1). The day's book holds w = pos / N of each coin, N the coins with a position
  that day (gross at most 1, long and short, as perps).
- **Net result.** Each day sum(w r) less sum(c |w - w the day before|), c the coin's one-way cost of its era: the
  USD-M taker 5 bps plus T5's half-spread tier (1 to 50 bps) of its 30-day median dollar volume known that day. In
  and out is one round trip. A coin without a row trades out at the highest tier. Filled at the close of the
  forecast day (the target's definition); no funding.
- **Learner, ridge_net** (a ridge on the net target, simpler than a LightGBM objective and in closed form): on the
  standardised inputs with an unpenalised intercept, minimise sum((y - f)^2) + kappa sum(c / sd(y) df^2) + alpha n
  |b|^2, which is maximising the gross P&L sum(f y) less a quadratic risk term, less kappa times the quadratic bound
  of the cost c |df| at a change of one sd of y (df a coin's change of forecast from one day to the next). kappa 0
  is the plain ridge on the return (the gross twin, inside the family). The net Sharpe is always measured with the
  true c |dw|.
- **Space.** 3 to 12 of G2's daily inputs (M8's and M10's builders), alpha in {0.01, 0.1, 1}, kappa in
  {0, 1, 4, 16}, the training window all history or the last 365, 730 or 1,095 days. No G1 trees.
- **Search.** 32 specs by G2's own draw (`net_draw`, seeded "t7"): the first 16 at random, then 16 mutations of one
  of the five best by fitness so far. A spec drawn before is never a new trial.
- **Screen.** G2's quarterly walk-forward 2021-01-01 to 2023-12-31, expanding, purged (a training row's next day is
  known before the block starts). **Fitness** is the annual net Sharpe of the screen's days. **Baseline** the plain
  signal: pos = sign of the 30-day return in the same book at the same costs on the same rows. A screen pass: net
  Sharpe above 0 and above the plain signal's.
- **Validation look.** The 2 best screen passes, each first through T1's leak harness (`lab.leak.checks.spec`), then
  written to `net_holdout.jsonl` before it is scored over 2024-01-01 to 2026-06-30 (the same walk). **Pass:** net
  Sharpe above the plain signal's and a DSR over R5's pool of all (with the factory ledgers, these trials included)
  of 0.95 or more. Reported with it: the stationary bootstrap band of the difference to the plain signal, T2's
  CPCV of the screen (6 groups, 2 tested, each path's net Sharpe less the plain signal's), PBO by CSCV of the
  32 specs' daily screen nets, and the family by kappa (median net and gross Sharpe and turnover).
- **A pass** joins G2's shadows (`shadows.json`; its positions logged each day before the outcome, scored and
  retired by the day's net against the plain signal, G2's eligibility and retirement days). Nothing else: no book,
  no allocator pick, nothing live. The daily G2 job never draws a net spec by itself.

## B. Meta-labelling as a size

- **Rules.** T5's definitions on T5's PIT20 (the 20 coins with the highest 30-day median dollar volume each day,
  from the sweep panel with dead coins): tsmom1, breakout_top10, F2's Donchian 100/50 run on coins. Each filled one
  close late (T5's `late`) at the spot costs of its era (taker 10 bps plus the half-spread tier), T5's simulator.
- **Trades and labels** (M1's `lab.models.metalabel`). A trade is a run of days a coin is held by the targets in
  force; its label is 1 when the late trade (close after entry to close after exit) less the round trip of its era
  (entry plus exit cost) is above 0, known at the late exit's close. Features M1's eleven, at the decision close.
- **Meta model.** The factory's LightGBM (`factory.LGB`), an expanding yearly walk from 2020 (a block trained on
  the trades whose label was known before it starts, at least 40), a trade still open at the end from the trades
  closed before it opened. A trade without a probability keeps its full weight in every variant.
- **Variants.** plain (the rule as T5 ran it); filter (a trade with probability under 0.5 left out, M1's
  `filtered`); size (each of the trade's weights times its probability, clipped to 0 to 1, so never above the
  rule's weight).
- **Pass (size):** validation Sharpe above the plain rule's and the plain filter's, the stationary bootstrap's 5 %
  of size minus plain above 0, and a DSR over R5's pool of all of 0.95 or more. Reported with it: AUC in sample and
  in validation, the mean size, drawdowns, the needed Sharpe. A pass is written in the report as a candidate for a
  shadow; G2's shadow path takes model specs only, so a meta book's shadow needs its own brief. Nothing else.

## Trials (39 new)

Each a line of R5's registry with its in-sample Sharpe, registered before any validation number is computed:
`factory:t7_net:<key>` for the 32 specs (family factory, the screen net Sharpe; an error only counts) and
`factory:t7_net:plain_signal` (the plain signal's screen Sharpe); `hand:t7_meta:<rule>:<filter|size>` for the
6 meta variants (family hand, in sample 2020-08-01 to 2023-12-31). The plain rules are T5's trials
`hand:t5_pit:<rule>:PIT20`, the same specification, registered under their id (a no-op where T5's line exists).

## Reported

`results/cost_aware_t7.md`: per part whether the net-trained models or the meta sizing beat their baselines after
the registry's deflation, with the numbers above and the needed Sharpe. A verdict is no unless every pass condition
holds.
