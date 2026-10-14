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

## Results (generated 2026-10-14, data to 2026-10-13)

**Verdict: nothing passes.** Cross-book pick (best average selection-window Sharpe at 35 bps): **HMM 3 states · full · switch**. Pass rule: 1 beats 200d in 3 of 4 incl. tsmom_top20: yes; 2 difference deflated p > 0.95 in 3 of 4: no; 3 bootstrap band above 0 in 3 of 4: no; 4 difference positive in 2 of 3 years in 3 of 4: yes. Deflation pool 331 trials (prior 265, here 66); the best noise trial is expected at an annual Sharpe of about 2.55.

### The cross-book pick against the 200-day rule (out of sample, 35 bps)

`diff_*` is the pick-gated book minus the 200d-gated book, daily net returns; `diff_2024` to `diff_2026` are its summed returns per year; `book_deflated_p` is the gated book's own deflated p over the whole pool.

| book | oos_none | oos_200d | oos_pick | dd_200d | dd_pick | diff_sharpe | diff_deflated_p | diff_boot_p05 | diff_boot_p95 | diff_2024 | diff_2025 | diff_2026 | book_deflated_p |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| breakout_top10 | 1.06 | 1.24 | 1.02 | 0.21 | 0.21 | -0.51 | 0.01 | -1.41 | 0.45 | -0.03 | 0.02 | -0.11 | 0.00 |
| tsmom_top20 | -0.15 | 0.25 | 0.42 | 0.24 | 0.21 | 0.28 | 0.11 | -0.75 | 1.30 | 0.11 | 0.13 | -0.16 | 0.00 |
| tsmom_tranches | 0.26 | 0.48 | 0.56 | 0.22 | 0.18 | 0.12 | 0.07 | -0.93 | 1.06 | 0.06 | 0.10 | -0.13 | 0.00 |
| tsmom_regime | 0.42 | 0.80 | 0.87 | 0.22 | 0.21 | 0.18 | 0.09 | -0.76 | 1.13 | 0.05 | 0.16 | -0.16 | 0.00 |

### Every book and gate (selection window 2021-07 to 2023, out of sample from 2024)

| book | gate | sel_taker 35bps | oos_maker 15bps | oos_taker 35bps | cagr_taker 35bps | dd_taker 35bps | turnover_yr | expo |
|---|---|---|---|---|---|---|---|---|
| breakout_top10 | 200d | 0.84 | 1.32 | 1.24 | 0.25 | 0.21 | 7.70 | 0.18 |
| breakout_top10 | 200d (native) | 0.91 | 1.33 | 1.25 | 0.25 | 0.19 | 7.41 | 0.18 |
| breakout_top10 | HMM 2 states · full · soft | 0.78 | 0.80 | 0.71 | 0.12 | 0.20 | 8.26 | 0.15 |
| breakout_top10 | HMM 2 states · full · switch | 0.77 | 0.77 | 0.68 | 0.11 | 0.20 | 7.79 | 0.15 |
| breakout_top10 | HMM 2 states · price · soft | 0.90 | 1.00 | 0.91 | 0.17 | 0.22 | 9.06 | 0.19 |
| breakout_top10 | HMM 2 states · price · switch | 0.87 | 1.00 | 0.91 | 0.17 | 0.22 | 9.09 | 0.19 |
| breakout_top10 | HMM 3 states · full · soft | 1.03 | 1.07 | 0.98 | 0.19 | 0.22 | 9.04 | 0.19 |
| breakout_top10 | HMM 3 states · full · switch | 1.01 | 1.10 | 1.02 | 0.20 | 0.21 | 8.76 | 0.19 |
| breakout_top10 | HMM 3 states · price · soft | 0.92 | 1.12 | 1.02 | 0.20 | 0.22 | 9.39 | 0.22 |
| breakout_top10 | HMM 3 states · price · switch | 0.90 | 1.09 | 1.00 | 0.20 | 0.23 | 9.40 | 0.22 |
| breakout_top10 | HMM 4 states · full · soft | 0.83 | 0.93 | 0.82 | 0.15 | 0.18 | 9.48 | 0.17 |
| breakout_top10 | HMM 4 states · full · switch | 0.80 | 0.85 | 0.75 | 0.13 | 0.19 | 9.42 | 0.17 |
| breakout_top10 | HMM 4 states · price · soft | 0.88 | 1.20 | 1.11 | 0.23 | 0.22 | 9.10 | 0.22 |
| breakout_top10 | HMM 4 states · price · switch | 0.83 | 1.23 | 1.14 | 0.23 | 0.22 | 8.93 | 0.22 |
| breakout_top10 | none | 0.92 | 1.15 | 1.06 | 0.22 | 0.22 | 9.34 | 0.24 |
| tsmom_regime | 200d | 1.01 | 0.97 | 0.80 | 0.13 | 0.22 | 14.30 | 0.18 |
| tsmom_regime | HMM 2 states · full · soft | 0.56 | 0.80 | 0.66 | 0.09 | 0.19 | 10.68 | 0.15 |
| tsmom_regime | HMM 2 states · full · switch | 0.53 | 0.72 | 0.58 | 0.08 | 0.21 | 10.39 | 0.14 |
| tsmom_regime | HMM 2 states · price · soft | 0.72 | 0.96 | 0.80 | 0.13 | 0.20 | 14.64 | 0.19 |
| tsmom_regime | HMM 2 states · price · switch | 0.74 | 0.92 | 0.75 | 0.13 | 0.21 | 15.16 | 0.19 |
| tsmom_regime | HMM 3 states · full · soft | 0.98 | 0.98 | 0.82 | 0.14 | 0.22 | 14.86 | 0.20 |
| tsmom_regime | HMM 3 states · full · switch | 1.01 | 1.03 | 0.87 | 0.15 | 0.21 | 14.53 | 0.20 |
| tsmom_regime | HMM 3 states · price · soft | 0.88 | 0.75 | 0.56 | 0.09 | 0.26 | 18.03 | 0.24 |
| tsmom_regime | HMM 3 states · price · switch | 0.84 | 0.72 | 0.53 | 0.09 | 0.26 | 18.11 | 0.24 |
| tsmom_regime | HMM 4 states · full · soft | 0.79 | 0.62 | 0.43 | 0.06 | 0.28 | 15.42 | 0.19 |
| tsmom_regime | HMM 4 states · full · switch | 0.77 | 0.52 | 0.33 | 0.04 | 0.29 | 15.51 | 0.19 |
| tsmom_regime | HMM 4 states · price · soft | 0.76 | 0.78 | 0.58 | 0.10 | 0.25 | 19.18 | 0.26 |
| tsmom_regime | HMM 4 states · price · switch | 0.74 | 0.80 | 0.60 | 0.10 | 0.24 | 19.18 | 0.26 |
| tsmom_regime | none | 0.76 | 0.64 | 0.42 | 0.06 | 0.31 | 21.93 | 0.28 |
| tsmom_top20 | 200d | 0.74 | 0.42 | 0.25 | 0.03 | 0.24 | 12.90 | 0.17 |
| tsmom_top20 | HMM 2 states · full · soft | 0.51 | 0.28 | 0.14 | 0.01 | 0.18 | 9.77 | 0.13 |
| tsmom_top20 | HMM 2 states · full · switch | 0.47 | 0.20 | 0.06 | -0.00 | 0.19 | 9.57 | 0.13 |
| tsmom_top20 | HMM 2 states · price · soft | 0.64 | 0.44 | 0.28 | 0.03 | 0.20 | 13.08 | 0.17 |
| tsmom_top20 | HMM 2 states · price · switch | 0.66 | 0.42 | 0.25 | 0.03 | 0.20 | 13.56 | 0.17 |
| tsmom_top20 | HMM 3 states · full · soft | 0.82 | 0.51 | 0.34 | 0.04 | 0.22 | 13.24 | 0.18 |
| tsmom_top20 | HMM 3 states · full · switch | 0.86 | 0.58 | 0.42 | 0.06 | 0.21 | 12.98 | 0.18 |
| tsmom_top20 | HMM 3 states · price · soft | 0.62 | 0.30 | 0.10 | 0.00 | 0.24 | 16.21 | 0.22 |
| tsmom_top20 | HMM 3 states · price · switch | 0.56 | 0.25 | 0.05 | -0.01 | 0.24 | 16.27 | 0.22 |
| tsmom_top20 | HMM 4 states · full · soft | 0.62 | 0.15 | -0.04 | -0.02 | 0.27 | 14.25 | 0.17 |
| tsmom_top20 | HMM 4 states · full · switch | 0.61 | 0.06 | -0.13 | -0.03 | 0.28 | 14.33 | 0.17 |
| tsmom_top20 | HMM 4 states · price · soft | 0.50 | 0.29 | 0.09 | 0.00 | 0.23 | 17.45 | 0.23 |
| tsmom_top20 | HMM 4 states · price · switch | 0.46 | 0.33 | 0.12 | 0.01 | 0.22 | 17.53 | 0.23 |
| tsmom_top20 | none | 0.40 | 0.08 | -0.15 | -0.04 | 0.32 | 20.14 | 0.26 |
| tsmom_tranches | 200d | 0.78 | 0.55 | 0.48 | 0.07 | 0.22 | 5.51 | 0.17 |
| tsmom_tranches | 200d (native) | 0.90 | 0.48 | 0.42 | 0.06 | 0.23 | 4.97 | 0.17 |
| tsmom_tranches | HMM 2 states · full · soft | 0.61 | 0.39 | 0.29 | 0.03 | 0.17 | 6.46 | 0.13 |
| tsmom_tranches | HMM 2 states · full · switch | 0.60 | 0.30 | 0.21 | 0.02 | 0.17 | 6.24 | 0.13 |
| tsmom_tranches | HMM 2 states · price · soft | 0.77 | 0.51 | 0.42 | 0.06 | 0.18 | 7.43 | 0.18 |
| tsmom_tranches | HMM 2 states · price · switch | 0.81 | 0.51 | 0.42 | 0.06 | 0.17 | 7.73 | 0.18 |
| tsmom_tranches | HMM 3 states · full · soft | 0.82 | 0.58 | 0.49 | 0.07 | 0.19 | 7.19 | 0.18 |
| tsmom_tranches | HMM 3 states · full · switch | 0.87 | 0.65 | 0.56 | 0.08 | 0.18 | 6.82 | 0.19 |
| tsmom_tranches | HMM 3 states · price · soft | 0.67 | 0.35 | 0.26 | 0.03 | 0.24 | 7.46 | 0.22 |
| tsmom_tranches | HMM 3 states · price · switch | 0.60 | 0.27 | 0.18 | 0.02 | 0.25 | 7.62 | 0.22 |
| tsmom_tranches | HMM 4 states · full · soft | 0.67 | 0.25 | 0.14 | 0.01 | 0.21 | 7.70 | 0.17 |
| tsmom_tranches | HMM 4 states · full · switch | 0.68 | 0.14 | 0.04 | -0.01 | 0.24 | 7.74 | 0.17 |
| tsmom_tranches | HMM 4 states · price · soft | 0.52 | 0.48 | 0.40 | 0.06 | 0.22 | 7.07 | 0.24 |
| tsmom_tranches | HMM 4 states · price · switch | 0.43 | 0.51 | 0.43 | 0.06 | 0.22 | 7.08 | 0.24 |
| tsmom_tranches | none | 0.56 | 0.34 | 0.26 | 0.03 | 0.25 | 7.39 | 0.26 |

### Per year (Sharpe at 35 bps; 2021 from July)

| book | gate | y2021 | y2022 | y2023 | y2024 | y2025 | y2026 |
|---|---|---|---|---|---|---|---|
| breakout_top10 | 200d | 0.33 | 0.00 | 1.37 | 1.75 | 0.41 | 1.34 |
| breakout_top10 | 200d (native) | 0.53 | 0.00 | 1.41 | 1.82 | 0.38 | 1.28 |
| breakout_top10 | HMM 2 states · full · soft | 2.04 | -0.95 | 1.31 | 1.40 | 0.00 | 0.03 |
| breakout_top10 | HMM 2 states · full · switch | 2.04 | -0.95 | 1.30 | 1.36 | -0.10 | 0.13 |
| breakout_top10 | HMM 2 states · price · soft | 1.80 | -0.58 | 1.48 | 1.48 | 0.56 | 0.34 |
| breakout_top10 | HMM 2 states · price · switch | 1.89 | -0.63 | 1.42 | 1.46 | 0.65 | 0.29 |
| breakout_top10 | HMM 3 states · full · soft | 2.04 | -0.46 | 1.60 | 1.62 | 0.55 | 0.36 |
| breakout_top10 | HMM 3 states · full · switch | 2.04 | -0.51 | 1.60 | 1.65 | 0.65 | 0.36 |
| breakout_top10 | HMM 3 states · price · soft | 1.99 | -0.81 | 1.67 | 1.57 | 0.67 | 0.52 |
| breakout_top10 | HMM 3 states · price · switch | 2.00 | -0.88 | 1.69 | 1.50 | 0.67 | 0.53 |
| breakout_top10 | HMM 4 states · full · soft | 2.01 | -1.29 | 1.55 | 1.36 | 0.23 | 0.52 |
| breakout_top10 | HMM 4 states · full · switch | 2.00 | -1.41 | 1.55 | 1.21 | 0.19 | 0.53 |
| breakout_top10 | HMM 4 states · price · soft | 1.82 | -0.76 | 1.64 | 1.67 | 0.83 | 0.53 |
| breakout_top10 | HMM 4 states · price · switch | 1.76 | -0.88 | 1.67 | 1.68 | 0.89 | 0.57 |
| breakout_top10 | none | 2.04 | -0.84 | 1.72 | 1.84 | 0.46 | 0.39 |
| tsmom_regime | 200d | 0.18 | 0.00 | 1.78 | 1.61 | -0.39 | 1.14 |
| tsmom_regime | HMM 2 states · full · soft | 1.97 | -1.14 | 1.09 | 1.76 | -0.59 | 0.28 |
| tsmom_regime | HMM 2 states · full · switch | 1.97 | -1.18 | 1.05 | 1.68 | -0.82 | 0.37 |
| tsmom_regime | HMM 2 states · price · soft | 1.41 | -0.73 | 1.46 | 1.64 | 0.55 | 0.00 |
| tsmom_regime | HMM 2 states · price · switch | 1.51 | -0.61 | 1.38 | 1.53 | 0.63 | -0.08 |
| tsmom_regime | HMM 3 states · full · soft | 1.97 | -0.70 | 1.71 | 1.80 | 0.49 | -0.07 |
| tsmom_regime | HMM 3 states · full · switch | 1.97 | -0.67 | 1.76 | 1.86 | 0.63 | -0.11 |
| tsmom_regime | HMM 3 states · price · soft | 1.91 | -0.91 | 1.70 | 1.52 | 0.01 | -0.10 |
| tsmom_regime | HMM 3 states · price · switch | 1.89 | -0.99 | 1.69 | 1.43 | 0.04 | -0.11 |
| tsmom_regime | HMM 4 states · full · soft | 1.84 | -0.94 | 1.50 | 1.67 | -0.62 | -0.11 |
| tsmom_regime | HMM 4 states · full · switch | 1.86 | -0.95 | 1.47 | 1.43 | -0.62 | -0.11 |
| tsmom_regime | HMM 4 states · price · soft | 1.84 | -1.11 | 1.70 | 1.63 | -0.07 | -0.08 |
| tsmom_regime | HMM 4 states · price · switch | 1.82 | -1.20 | 1.74 | 1.62 | -0.07 | -0.02 |
| tsmom_regime | none | 1.97 | -1.44 | 1.89 | 1.71 | -0.63 | -0.17 |
| tsmom_top20 | 200d | 0.35 | 0.00 | 1.22 | 0.37 | -0.29 | 0.89 |
| tsmom_top20 | HMM 2 states · full · soft | 2.08 | -1.32 | 1.03 | 0.67 | -0.64 | 0.23 |
| tsmom_top20 | HMM 2 states · full · switch | 2.08 | -1.37 | 0.99 | 0.59 | -0.89 | 0.35 |
| tsmom_top20 | HMM 2 states · price · soft | 1.32 | -0.71 | 1.31 | 0.62 | 0.53 | -0.38 |
| tsmom_top20 | HMM 2 states · price · switch | 1.42 | -0.60 | 1.25 | 0.49 | 0.62 | -0.41 |
| tsmom_top20 | HMM 3 states · full · soft | 2.08 | -0.91 | 1.49 | 0.92 | 0.47 | -0.47 |
| tsmom_top20 | HMM 3 states · full · switch | 2.08 | -0.87 | 1.56 | 1.01 | 0.63 | -0.51 |
| tsmom_top20 | HMM 3 states · price · soft | 1.87 | -1.21 | 1.42 | 0.51 | 0.14 | -0.43 |
| tsmom_top20 | HMM 3 states · price · switch | 1.85 | -1.31 | 1.40 | 0.38 | 0.15 | -0.45 |
| tsmom_top20 | HMM 4 states · full · soft | 1.60 | -1.22 | 1.40 | 0.71 | -0.53 | -0.44 |
| tsmom_top20 | HMM 4 states · full · switch | 1.58 | -1.24 | 1.39 | 0.50 | -0.55 | -0.45 |
| tsmom_top20 | HMM 4 states · price · soft | 1.52 | -1.31 | 1.48 | 0.50 | 0.04 | -0.37 |
| tsmom_top20 | HMM 4 states · price · switch | 1.48 | -1.41 | 1.53 | 0.52 | 0.07 | -0.31 |
| tsmom_top20 | none | 2.08 | -1.68 | 1.31 | 0.50 | -0.58 | -0.51 |
| tsmom_tranches | 200d | 0.24 | 0.00 | 1.33 | 0.68 | 0.05 | 0.87 |
| tsmom_tranches | 200d (native) | 0.84 | 0.89 | 1.30 | 0.59 | 0.08 | 0.71 |
| tsmom_tranches | HMM 2 states · full · soft | 2.01 | -1.34 | 1.26 | 0.64 | -0.49 | 0.63 |
| tsmom_tranches | HMM 2 states · full · switch | 2.01 | -1.36 | 1.24 | 0.57 | -0.76 | 0.73 |
| tsmom_tranches | HMM 2 states · price · soft | 1.63 | -0.77 | 1.46 | 0.67 | 0.62 | -0.12 |
| tsmom_tranches | HMM 2 states · price · switch | 1.72 | -0.63 | 1.42 | 0.58 | 0.73 | -0.13 |
| tsmom_tranches | HMM 3 states · full · soft | 2.01 | -1.09 | 1.62 | 0.94 | 0.58 | -0.20 |
| tsmom_tranches | HMM 3 states · full · switch | 2.01 | -1.02 | 1.68 | 1.06 | 0.73 | -0.27 |
| tsmom_tranches | HMM 3 states · price · soft | 1.86 | -1.33 | 1.60 | 0.66 | 0.19 | -0.16 |
| tsmom_tranches | HMM 3 states · price · switch | 1.86 | -1.43 | 1.62 | 0.53 | 0.15 | -0.23 |
| tsmom_tranches | HMM 4 states · full · soft | 1.53 | -1.32 | 1.55 | 0.62 | -0.13 | -0.17 |
| tsmom_tranches | HMM 4 states · full · switch | 1.56 | -1.33 | 1.56 | 0.40 | -0.14 | -0.23 |
| tsmom_tranches | HMM 4 states · price · soft | 1.35 | -1.38 | 1.63 | 0.74 | 0.41 | -0.08 |
| tsmom_tranches | HMM 4 states · price · switch | 1.29 | -1.52 | 1.66 | 0.76 | 0.45 | -0.05 |
| tsmom_tranches | none | 2.01 | -1.31 | 1.52 | 0.90 | -0.03 | -0.28 |

### State stability

`switches_yr`: gate changes a year from 2021-07 (soft: days the scale moves by more than 0.25); `mean_run_days`: mean run of the most likely state; `exp_duration_days`: median over fits of the mean expected state duration from the transition matrix; `undecided_share`: out-of-sample days with P(bull) between 0.4 and 0.6; `refit_agreement`: on the month after each refit, the share of days the new and the previous fit make the same bull call.

| gate | fits | switches_yr | mean_run_days | exp_duration_days | undecided_share | refit_agreement | bull_share_oos |
|---|---|---|---|---|---|---|---|
| HMM 2 states · price · soft | 67 | 19.47 | 28.40 | 49.29 | 0.01 | 0.95 | 0.42 |
| HMM 2 states · price · switch | 67 | 12.66 | 28.40 | 49.29 | 0.01 | 0.95 | 0.42 |
| HMM 3 states · price · soft | 67 | 14.93 | 17.72 | 27.55 | 0.01 | 0.96 | 0.60 |
| HMM 3 states · price · switch | 67 | 10.77 | 17.72 | 27.55 | 0.01 | 0.96 | 0.60 |
| HMM 4 states · price · soft | 67 | 17.20 | 13.89 | 22.71 | 0.00 | 0.93 | 0.70 |
| HMM 4 states · price · switch | 67 | 11.53 | 13.89 | 22.71 | 0.00 | 0.93 | 0.70 |
| HMM 2 states · full · soft | 67 | 13.61 | 30.17 | 51.29 | 0.01 | 0.98 | 0.31 |
| HMM 2 states · full · switch | 67 | 10.21 | 30.17 | 51.29 | 0.01 | 0.98 | 0.31 |
| HMM 3 states · full · soft | 67 | 18.15 | 22.72 | 32.06 | 0.01 | 0.98 | 0.45 |
| HMM 3 states · full · switch | 67 | 11.34 | 22.72 | 32.06 | 0.01 | 0.98 | 0.45 |
| HMM 4 states · full · soft | 67 | 17.39 | 14.97 | 24.59 | 0.02 | 0.93 | 0.47 |
| HMM 4 states · full · switch | 67 | 11.53 | 14.97 | 24.59 | 0.02 | 0.93 | 0.47 |
| 200d | 0 | 9.26 | 38.62 | n/a | 0.00 | n/a | 0.61 |

### Selection details

Average selection-window Sharpe at 35 bps over the four books:

| gate | avg_sel_35 |
|---|---|
| HMM 3 states · full · switch | 0.94 |
| HMM 3 states · full · soft | 0.91 |
| HMM 3 states · price · soft | 0.77 |
| HMM 2 states · price · switch | 0.77 |
| HMM 2 states · price · soft | 0.76 |
| HMM 4 states · full · soft | 0.73 |
| HMM 3 states · price · switch | 0.72 |
| HMM 4 states · full · switch | 0.72 |
| HMM 4 states · price · soft | 0.67 |
| HMM 4 states · price · switch | 0.62 |
| HMM 2 states · full · soft | 0.61 |
| HMM 2 states · full · switch | 0.59 |

Per book, the best HMM gate in the selection window (information only): breakout_top10: HMM 3 states · full · soft; tsmom_top20: HMM 3 states · full · switch; tsmom_tranches: HMM 3 states · full · switch; tsmom_regime: HMM 3 states · full · switch.

Walk-forward HMM gate per book (each out-of-sample quarter uses the best gate so far):

| book | oos | dd |
|---|---|---|
| breakout_top10 | 1.00 | 0.21 |
| tsmom_top20 | 0.42 | 0.21 |
| tsmom_tranches | 0.56 | 0.18 |
| tsmom_regime | 0.87 | 0.21 |

The pick applied one day late:

| book | gate | sel_taker 35bps | oos_maker 15bps | oos_taker 35bps | cagr_taker 35bps | dd_taker 35bps | turnover_yr | expo |
|---|---|---|---|---|---|---|---|---|
| breakout_top10 | HMM 3 states · full · switch · one day late | 0.96 | 1.03 | 0.94 | 0.18 | 0.25 | 8.84 | 0.19 |
| tsmom_top20 | HMM 3 states · full · switch · one day late | 0.81 | 0.51 | 0.35 | 0.04 | 0.23 | 12.77 | 0.18 |
| tsmom_tranches | HMM 3 states · full · switch · one day late | 0.74 | 0.58 | 0.50 | 0.07 | 0.19 | 6.81 | 0.19 |
| tsmom_regime | HMM 3 states · full · switch · one day late | 0.96 | 0.93 | 0.77 | 0.13 | 0.24 | 14.35 | 0.20 |

P(bull) of the pick, mean per year: 2021 1.00, 2022 0.34, 2023 0.61, 2024 0.52, 2025 0.27, 2026 0.59.

### Deflation

Prior: 265 trials, variance backed out of the fast strategies' bar (2.74 over 265); here 66 trials at 35 bps. Pooled bar 2.55 over 331. The difference test uses the variance of the 48 HMM difference series' Sharpes (daily 3.23e-04) with the same 331 trials.

Trials counted here: breakout_top10 · none; breakout_top10 · 200d; breakout_top10 · HMM 2 states · price · soft; breakout_top10 · HMM 2 states · price · switch; breakout_top10 · HMM 3 states · price · soft; breakout_top10 · HMM 3 states · price · switch; breakout_top10 · HMM 4 states · price · soft; breakout_top10 · HMM 4 states · price · switch; breakout_top10 · HMM 2 states · full · soft; breakout_top10 · HMM 2 states · full · switch; breakout_top10 · HMM 3 states · full · soft; breakout_top10 · HMM 3 states · full · switch; breakout_top10 · HMM 4 states · full · soft; breakout_top10 · HMM 4 states · full · switch; tsmom_top20 · none; tsmom_top20 · 200d; tsmom_top20 · HMM 2 states · price · soft; tsmom_top20 · HMM 2 states · price · switch; tsmom_top20 · HMM 3 states · price · soft; tsmom_top20 · HMM 3 states · price · switch; tsmom_top20 · HMM 4 states · price · soft; tsmom_top20 · HMM 4 states · price · switch; tsmom_top20 · HMM 2 states · full · soft; tsmom_top20 · HMM 2 states · full · switch; tsmom_top20 · HMM 3 states · full · soft; tsmom_top20 · HMM 3 states · full · switch; tsmom_top20 · HMM 4 states · full · soft; tsmom_top20 · HMM 4 states · full · switch; tsmom_tranches · none; tsmom_tranches · 200d; tsmom_tranches · HMM 2 states · price · soft; tsmom_tranches · HMM 2 states · price · switch; tsmom_tranches · HMM 3 states · price · soft; tsmom_tranches · HMM 3 states · price · switch; tsmom_tranches · HMM 4 states · price · soft; tsmom_tranches · HMM 4 states · price · switch; tsmom_tranches · HMM 2 states · full · soft; tsmom_tranches · HMM 2 states · full · switch; tsmom_tranches · HMM 3 states · full · soft; tsmom_tranches · HMM 3 states · full · switch; tsmom_tranches · HMM 4 states · full · soft; tsmom_tranches · HMM 4 states · full · switch; tsmom_regime · none; tsmom_regime · 200d; tsmom_regime · HMM 2 states · price · soft; tsmom_regime · HMM 2 states · price · switch; tsmom_regime · HMM 3 states · price · soft; tsmom_regime · HMM 3 states · price · switch; tsmom_regime · HMM 4 states · price · soft; tsmom_regime · HMM 4 states · price · switch; tsmom_regime · HMM 2 states · full · soft; tsmom_regime · HMM 2 states · full · switch; tsmom_regime · HMM 3 states · full · soft; tsmom_regime · HMM 3 states · full · switch; tsmom_regime · HMM 4 states · full · soft; tsmom_regime · HMM 4 states · full · switch; breakout_top10 · 200d (native); tsmom_tranches · 200d (native); breakout_top10 · walk-forward HMM gate; breakout_top10 · HMM 3 states · full · switch · one day late; tsmom_top20 · walk-forward HMM gate; tsmom_top20 · HMM 3 states · full · switch · one day late; tsmom_tranches · walk-forward HMM gate; tsmom_tranches · HMM 3 states · full · switch · one day late; tsmom_regime · walk-forward HMM gate; tsmom_regime · HMM 3 states · full · switch · one day late.
