# M7: a market regime model (Gaussian HMM) as a gate for the books

`python -m lab.experiments.regime_hmm`

## Pre-registration (written and committed before the first run)

**Question.** The books gate on a fixed rule: BTC's daily close above its
200-day average. Does a hidden Markov model of the market's state, fitted
point in time, gate them better out of sample, after costs and after counting
every variant tried? If not, the negative result is written up and nothing is
added to the paper books.

**Data.** The sweep's survivorship-free daily panel (`fam_common.load_panel`:
every USDT spot pair Binance ever listed, delisted ones included, rebuilt from
the data.binance.vision 1h archives), plus the USD-M perpetual archives for
funding. Panel end 2026-09-30. Day t's close is the last hourly close of the
UTC day; a decision at the close of day t earns day t+1 (the lab's convention).

**Features** (each known at the close of day t):

| name | definition |
|---|---|
| r7 | BTC 7-day log return, log(px[t] / px[t-7]) |
| vol14 | log of BTC's annualised realised vol over the last 14 days (hourly realised variance) |
| breadth | share of the day's eligible coins (alive, traded, 60 days old, 1 M USD a day) whose close is above its own 50-day average (at least 40 closes) |
| volume | log(7-day mean / 90-day mean) of the total quote volume of the eligible coins |
| funding | 7-day mean of BTC's USDT perpetual funding, summed per day |

Two feature sets: **price** (r7, vol14, breadth) and **full** (all five).

**Model.** Gaussian HMM, full covariance (floor 1e-3 on z-scored inputs), EM
up to 200 iterations. Expanding window: the first fit at the close of
2021-03-31 on every feature day before it (about a year), then a refit at
every month's last close on everything up to that close. Features are z-scored
with the training window's mean and standard deviation, frozen until the next
refit. Four starts per fit (the previous fit's parameters and three seeded
k-means starts), the highest likelihood is kept. **Filtered probabilities
only**: a forward pass with the fit's parameters from the first feature day;
the probability on day t uses features up to t and parameters fitted on data
up to the last month end on or before t. No smoother, no backward pass.

States are labelled per fit by their mean r7 (in raw units). P(bull) is the
filtered probability of the states whose mean r7 is above 0 (the top state if
none is).

**Gates.** A gate is a book-level exposure scale s[t] in [0, 1] decided at the
close of day t, applied as an overlay to the ungated book: the gated book holds
s[t] x what the ungated book holds after that close, so every book is gated by
the same mechanism and the gate's own trades are charged.

| gate | s[t] |
|---|---|
| none | 1 |
| 200d (overlay) | 1 while BTC's close is above its 200-day average, else 0 |
| HMM soft | P(bull) |
| HMM switch | hysteresis: on above 0.6, off below 0.4, else unchanged (starts on) |

HMM grid: K = 2, 3, 4 states x feature set (price, full) x mapping (soft,
switch) = **12 gates**.

**Books** (ungated cores, each with the weight function the paper books use):

| book | core |
|---|---|
| breakout_top10 | Donchian 20/10 on the 10 most liquid coins of each day (fam_breakout.breakout_weights, no regime) |
| tsmom_top20 | 28-day momentum, top 20 by volume each day, 40 % vol per coin (fam_volmom.base_weights, regime off) |
| tsmom_tranches | the same targets in the seven weekly tranches (tsmom_tranches.simulate, regime off) |
| tsmom_regime | 28-day momentum, 40 % vol per coin, on the engine's fixed 20 coins (today's survivors, so survivorship-biased; its survivorship-free twin is tsmom_top20) |

The books' native 200-day rule differs from the overlay for breakout_top10
(no entries and everything sold while BTC is below, then fresh breakouts
needed) and tsmom_tranches (each tranche's targets zeroed when it is due);
both natives are run as references.

**Split and costs.** Gate selection window 2021-07-01 to 2023-12-31 (gates
exist from 2021-04); out of sample 2024-01-01 to 2026-09-30. Costs per unit of
one-way turnover: Alpaca taker 25 bps plus about 10 bps slippage = **35 bps
(the base)**, Alpaca maker 15 bps (optimistic), 70 bps as a stress for the
pick. Sharpe annualised with 365 days.

**Picks.** The **cross-book pick**: the one HMM gate (of 12) with the best
average selection-window Sharpe at 35 bps over the four books. This is the
candidate for a reusable gate. For information, per book the best HMM gate in
the selection window, and a walk-forward pick per book (each out-of-sample
quarter uses the HMM gate with the best Sharpe at 35 bps on all gated data
before it).

**Counted trials.** 12 HMM gates x 4 books = 48; none and 200d overlay x 4 =
8; native 200d for breakout_top10 and tsmom_tranches = 2; walk-forward per
book = 4; the cross-book pick with the gate applied one day late, per book = 4.
**66 here; the pool is 265 + 66 = 331.**

**Pass rule** for the cross-book pick (all must hold, else nothing is added):

1. Out-of-sample Sharpe at 35 bps above the 200d overlay's in at least 3 of
   the 4 books, including tsmom_top20 (tsmom_regime alone is survivorship-biased).
2. The difference series (pick-gated minus 200d-gated daily net returns, same
   book, 35 bps) has a deflated p above 0.95 over 331 trials, in at least 3 of
   4 books. The variance of trial Sharpes is that of the 48 HMM difference
   series (clipped at +-3 annual).
3. The stationary-bootstrap 90 % band of the difference series' Sharpe is
   above 0 in at least 3 of 4 books.
4. The difference is positive in at least 2 of the 3 out-of-sample years
   (2026 partial) in at least 3 of 4 books.

Also reported, not part of the rule: each gated book's own deflated p over 331
trials (the lab's usual bar, about 2.7 annual Sharpe, which no book has met).

**Reported** per book and gate: Sharpe at 15 / 35 bps in and out of sample,
CAGR and maximum drawdown at 35 bps, turnover, average exposure, Sharpe per
year 2021 to 2026. **State stability** per HMM gate: switches per year of the
gate (for soft: days its scale moves by more than 0.25), mean run length of the
most likely state, expected state durations from the transition matrices
(median over fits), share of out-of-sample days with P(bull) between 0.4 and
0.6, and refit agreement (on the month after each refit, how often the new
fit's bull call, P > 0.5, matches the previous fit's).

If the pick passes: a reusable gate in fam_common, a gated paper book variant
(autopilot_only, evidence with its caveat, forward report band) with tests,
and a model card here. Otherwise this file carries the negative result.

<!-- generated below by lab.experiments.regime_hmm; edit above this line only -->
