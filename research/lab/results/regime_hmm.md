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

## Findings (written after the run, 2026-10-14)

Data: the survivorship-free daily panel rebuilt from the data.binance.vision
1h archives (683 USDT pairs listed, 590 coin segments, to 2026-09-30) and the
USD-M archives (900 perpetuals) for funding. The rebuilt panel reproduces
tsmom_tranches' published numbers exactly (0.58 / 0.52 / 0.41 at 15 / 35 / 70
bps). Out of sample is 1004 days (2024-01-01 to 2026-09-30).

1. **Nothing passes; no gate is added to fam_common and no paper book is
   added.** The cross-book pick, a 3-state HMM on all five features with the
   0.6 / 0.4 switch, beats the 200-day overlay in 3 of 4 books (the three
   momentum books) and the difference is positive in 2024 and 2025, so rules
   1 and 4 hold. Rules 2 and 3 fail everywhere: the difference series' Sharpe
   is 0.12 to 0.28 on the momentum books (deflated p 0.07 to 0.11 over 331
   trials, bootstrap 90 % bands about -0.8 to +1.3) and -0.52 on
   breakout_top10.
2. **Out of sample at 35 bps**, 200d overlay against the pick: breakout_top10
   1.30 against 1.07 (none 1.11); tsmom_top20 0.36 against 0.53 (none -0.07);
   tsmom_tranches 0.59 against 0.67 (none 0.35); tsmom_regime 0.90 against
   0.97 (none 0.50). Drawdowns are about the same (18 to 21 % against 21 to
   24 %). The pick's edge on momentum is 2025 (it was out for most of the
   year's chop, P(bull) averaged 0.27) and it gives back in 2026, when it
   was out of the rebound the 200d rule caught (diff -0.13 to -0.16 per book).
   Applied one day late it keeps most of that (0.46 / 0.61 / 0.86 on the
   momentum books, 0.99 on breakout).
3. **Either gate beats none on the momentum books; neither helps breakout.**
   Every gate cuts tsmom_top20's no-gate drawdown (32 %) and turnover. On
   breakout_top10, the 200d rule is the only gate above "none" out of sample
   (1.30 against 1.11); 10 of the 12 HMM gates are below "none".
4. **The grid is not a plateau.** Out of sample on tsmom_top20 the 12 HMM
   gates run from -0.03 to 0.53; three clear the 200d rule's 0.36 there (the
   two 3-state full-feature gates and the 2-state price soft gate, 0.39). Four states and the price-only 3-state model
   are worse than no gate on some books. The selection window picked the best
   out-of-sample cell, which looks good but is one cell of twelve.
5. **State stability.** Refits agree with the previous fit on 93 to 98 % of
   the following month; P(bull) is almost never undecided (1 to 2 % of days
   between 0.4 and 0.6), so the hysteresis band rarely binds. The switch
   gates change 10 to 13 times a year against 9 for the 200d rule; the most
   likely state lasts 14 to 30 days on average (the 200d state 38). Soft
   gates are not smoother in practice: the probabilities jump.
6. **The 2022 bear is the weak spot.** The HMM gates lost in 2022 (pick
   -0.87 on tsmom_top20) while the 200d rule sat flat (0.00). The first fits
   (from 2021-03) were trained on a year of bull market only, so every state
   had a positive mean return and P(bull) was 1 for all of 2021 by the
   registered labelling rule; the model learned a bear state only during the
   2022 fall. Any expanding-window regime model starting in 2020 has this
   handicap, which is part of the honest answer.
7. **Unverified.** Fills at the decision close on Binance prices stand in for
   Alpaca's book; the 10 bps slippage was not re-measured. The tranche book is
   measured on its net book-level trades (as the paper book trades), so its
   rows differ a little from tsmom_tranches.md (0.59 against 0.52 for the
   200d rule; the native row is that book). The tsmom_regime core is rebuilt
   on the daily panel's 20 current segments with hourly realised variance,
   not the paper book's 1m-based vol, and is survivorship-biased. The prior
   pool's variance is backed out of the fast strategies' published bar.
   Funding comes from the monthly archives only (no REST top-up), which
   covers the whole window. hmmlearn prints harmless "not converging" notes
   when EM's last step moves the likelihood by less than 0.01.

<!-- generated below by lab.experiments.regime_hmm; edit above this line only -->

## Results (generated 2026-10-14, data to 2026-09-30)

**Verdict: nothing passes.** Cross-book pick (best average selection-window Sharpe at 35 bps): **HMM 3 states · full · switch**. Pass rule: 1 beats 200d in 3 of 4 incl. tsmom_top20: yes; 2 difference deflated p > 0.95 in 3 of 4: no; 3 bootstrap band above 0 in 3 of 4: no; 4 difference positive in 2 of 3 years in 3 of 4: yes. Deflation pool 331 trials (prior 265, here 66); the best noise trial is expected at an annual Sharpe of about 2.55.

### The cross-book pick against the 200-day rule (out of sample, 35 bps)

`diff_*` is the pick-gated book minus the 200d-gated book, daily net returns; `diff_2024` to `diff_2026` are its summed returns per year; `book_deflated_p` is the gated book's own deflated p over the whole pool.

| book | oos_none | oos_200d | oos_pick | dd_200d | dd_pick | diff_sharpe | diff_deflated_p | diff_boot_p05 | diff_boot_p95 | diff_2024 | diff_2025 | diff_2026 | book_deflated_p |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| breakout_top10 | 1.11 | 1.30 | 1.07 | 0.21 | 0.21 | -0.52 | 0.01 | -1.42 | 0.44 | -0.03 | 0.02 | -0.11 | 0.01 |
| tsmom_top20 | -0.07 | 0.36 | 0.53 | 0.24 | 0.21 | 0.28 | 0.11 | -0.77 | 1.30 | 0.11 | 0.13 | -0.16 | 0.00 |
| tsmom_tranches | 0.35 | 0.59 | 0.67 | 0.22 | 0.18 | 0.12 | 0.07 | -0.88 | 1.05 | 0.06 | 0.10 | -0.13 | 0.00 |
| tsmom_regime | 0.50 | 0.90 | 0.97 | 0.22 | 0.21 | 0.19 | 0.09 | -0.78 | 1.15 | 0.05 | 0.16 | -0.16 | 0.00 |

### Every book and gate (selection window 2021-07 to 2023, out of sample from 2024)

| book | gate | sel_taker 35bps | oos_maker 15bps | oos_taker 35bps | cagr_taker 35bps | dd_taker 35bps | turnover_yr | expo |
|---|---|---|---|---|---|---|---|---|
| breakout_top10 | 200d | 0.84 | 1.37 | 1.30 | 0.26 | 0.21 | 7.62 | 0.18 |
| breakout_top10 | 200d (native) | 0.91 | 1.38 | 1.31 | 0.26 | 0.19 | 7.33 | 0.17 |
| breakout_top10 | HMM 2 states · full · soft | 0.78 | 0.85 | 0.76 | 0.13 | 0.20 | 8.18 | 0.15 |
| breakout_top10 | HMM 2 states · full · switch | 0.77 | 0.82 | 0.74 | 0.12 | 0.20 | 7.70 | 0.15 |
| breakout_top10 | HMM 2 states · price · soft | 0.90 | 1.05 | 0.96 | 0.18 | 0.22 | 8.99 | 0.19 |
| breakout_top10 | HMM 2 states · price · switch | 0.87 | 1.05 | 0.96 | 0.18 | 0.22 | 9.03 | 0.19 |
| breakout_top10 | HMM 3 states · full · soft | 1.03 | 1.12 | 1.03 | 0.20 | 0.22 | 8.97 | 0.19 |
| breakout_top10 | HMM 3 states · full · switch | 1.01 | 1.15 | 1.07 | 0.21 | 0.21 | 8.69 | 0.19 |
| breakout_top10 | HMM 3 states · price · soft | 0.92 | 1.17 | 1.07 | 0.22 | 0.22 | 9.33 | 0.22 |
| breakout_top10 | HMM 3 states · price · switch | 0.90 | 1.14 | 1.04 | 0.21 | 0.23 | 9.34 | 0.22 |
| breakout_top10 | HMM 4 states · full · soft | 0.83 | 0.97 | 0.88 | 0.16 | 0.18 | 9.42 | 0.17 |
| breakout_top10 | HMM 4 states · full · switch | 0.80 | 0.90 | 0.80 | 0.14 | 0.19 | 9.36 | 0.17 |
| breakout_top10 | HMM 4 states · price · soft | 0.88 | 1.25 | 1.16 | 0.24 | 0.22 | 9.03 | 0.22 |
| breakout_top10 | HMM 4 states · price · switch | 0.83 | 1.28 | 1.19 | 0.25 | 0.22 | 8.86 | 0.22 |
| breakout_top10 | none | 0.92 | 1.20 | 1.11 | 0.23 | 0.22 | 9.27 | 0.24 |
| tsmom_regime | 200d | 1.01 | 1.06 | 0.90 | 0.15 | 0.22 | 14.28 | 0.18 |
| tsmom_regime | HMM 2 states · full · soft | 0.56 | 0.91 | 0.77 | 0.11 | 0.19 | 10.61 | 0.14 |
| tsmom_regime | HMM 2 states · full · switch | 0.53 | 0.83 | 0.69 | 0.10 | 0.21 | 10.32 | 0.14 |
| tsmom_regime | HMM 2 states · price · soft | 0.72 | 1.06 | 0.89 | 0.15 | 0.20 | 14.62 | 0.19 |
| tsmom_regime | HMM 2 states · price · switch | 0.74 | 1.01 | 0.84 | 0.14 | 0.21 | 15.15 | 0.19 |
| tsmom_regime | HMM 3 states · full · soft | 0.98 | 1.08 | 0.91 | 0.16 | 0.22 | 14.85 | 0.20 |
| tsmom_regime | HMM 3 states · full · switch | 1.01 | 1.13 | 0.97 | 0.17 | 0.21 | 14.51 | 0.20 |
| tsmom_regime | HMM 3 states · price · soft | 0.88 | 0.84 | 0.64 | 0.11 | 0.26 | 18.05 | 0.24 |
| tsmom_regime | HMM 3 states · price · switch | 0.84 | 0.81 | 0.61 | 0.10 | 0.26 | 18.14 | 0.24 |
| tsmom_regime | HMM 4 states · full · soft | 0.79 | 0.71 | 0.52 | 0.08 | 0.28 | 15.41 | 0.18 |
| tsmom_regime | HMM 4 states · full · switch | 0.77 | 0.61 | 0.42 | 0.06 | 0.29 | 15.51 | 0.18 |
| tsmom_regime | HMM 4 states · price · soft | 0.76 | 0.87 | 0.67 | 0.11 | 0.25 | 19.23 | 0.25 |
| tsmom_regime | HMM 4 states · price · switch | 0.74 | 0.89 | 0.68 | 0.12 | 0.24 | 19.22 | 0.25 |
| tsmom_regime | none | 0.76 | 0.73 | 0.50 | 0.08 | 0.31 | 22.00 | 0.28 |
| tsmom_top20 | 200d | 0.74 | 0.53 | 0.36 | 0.05 | 0.24 | 12.89 | 0.16 |
| tsmom_top20 | HMM 2 states · full · soft | 0.51 | 0.41 | 0.26 | 0.03 | 0.18 | 9.72 | 0.12 |
| tsmom_top20 | HMM 2 states · full · switch | 0.47 | 0.33 | 0.18 | 0.02 | 0.19 | 9.53 | 0.12 |
| tsmom_top20 | HMM 2 states · price · soft | 0.64 | 0.56 | 0.39 | 0.05 | 0.20 | 13.08 | 0.17 |
| tsmom_top20 | HMM 2 states · price · switch | 0.66 | 0.53 | 0.35 | 0.04 | 0.20 | 13.57 | 0.17 |
| tsmom_top20 | HMM 3 states · full · soft | 0.82 | 0.62 | 0.45 | 0.06 | 0.22 | 13.24 | 0.18 |
| tsmom_top20 | HMM 3 states · full · switch | 0.86 | 0.69 | 0.53 | 0.07 | 0.21 | 12.98 | 0.18 |
| tsmom_top20 | HMM 3 states · price · soft | 0.62 | 0.39 | 0.20 | 0.02 | 0.24 | 16.25 | 0.22 |
| tsmom_top20 | HMM 3 states · price · switch | 0.56 | 0.34 | 0.15 | 0.01 | 0.24 | 16.31 | 0.22 |
| tsmom_top20 | HMM 4 states · full · soft | 0.62 | 0.26 | 0.07 | -0.00 | 0.27 | 14.27 | 0.17 |
| tsmom_top20 | HMM 4 states · full · switch | 0.61 | 0.17 | -0.03 | -0.01 | 0.28 | 14.34 | 0.17 |
| tsmom_top20 | HMM 4 states · price · soft | 0.50 | 0.39 | 0.18 | 0.02 | 0.23 | 17.51 | 0.23 |
| tsmom_top20 | HMM 4 states · price · switch | 0.46 | 0.43 | 0.22 | 0.02 | 0.22 | 17.59 | 0.23 |
| tsmom_top20 | none | 0.40 | 0.16 | -0.07 | -0.03 | 0.32 | 20.23 | 0.26 |
| tsmom_tranches | 200d | 0.78 | 0.65 | 0.59 | 0.09 | 0.22 | 5.54 | 0.17 |
| tsmom_tranches | 200d (native) | 0.90 | 0.58 | 0.52 | 0.07 | 0.23 | 4.99 | 0.17 |
| tsmom_tranches | HMM 2 states · full · soft | 0.61 | 0.50 | 0.41 | 0.05 | 0.17 | 6.49 | 0.13 |
| tsmom_tranches | HMM 2 states · full · switch | 0.60 | 0.41 | 0.32 | 0.04 | 0.17 | 6.27 | 0.13 |
| tsmom_tranches | HMM 2 states · price · soft | 0.77 | 0.62 | 0.53 | 0.07 | 0.18 | 7.48 | 0.17 |
| tsmom_tranches | HMM 2 states · price · switch | 0.81 | 0.62 | 0.52 | 0.07 | 0.17 | 7.78 | 0.17 |
| tsmom_tranches | HMM 3 states · full · soft | 0.82 | 0.69 | 0.60 | 0.09 | 0.19 | 7.23 | 0.18 |
| tsmom_tranches | HMM 3 states · full · switch | 0.87 | 0.75 | 0.67 | 0.10 | 0.18 | 6.86 | 0.18 |
| tsmom_tranches | HMM 3 states · price · soft | 0.67 | 0.44 | 0.36 | 0.05 | 0.24 | 7.51 | 0.22 |
| tsmom_tranches | HMM 3 states · price · switch | 0.60 | 0.36 | 0.27 | 0.03 | 0.25 | 7.67 | 0.22 |
| tsmom_tranches | HMM 4 states · full · soft | 0.67 | 0.36 | 0.25 | 0.03 | 0.21 | 7.76 | 0.17 |
| tsmom_tranches | HMM 4 states · full · switch | 0.68 | 0.24 | 0.14 | 0.01 | 0.24 | 7.79 | 0.17 |
| tsmom_tranches | HMM 4 states · price · soft | 0.52 | 0.57 | 0.49 | 0.07 | 0.22 | 7.12 | 0.23 |
| tsmom_tranches | HMM 4 states · price · switch | 0.43 | 0.60 | 0.52 | 0.08 | 0.22 | 7.12 | 0.23 |
| tsmom_tranches | none | 0.56 | 0.43 | 0.35 | 0.05 | 0.25 | 7.44 | 0.26 |

### Per year (Sharpe at 35 bps; 2021 from July)

| book | gate | y2021 | y2022 | y2023 | y2024 | y2025 | y2026 |
|---|---|---|---|---|---|---|---|
| breakout_top10 | 200d | 0.33 | 0.00 | 1.37 | 1.75 | 0.41 | 1.57 |
| breakout_top10 | 200d (native) | 0.53 | 0.00 | 1.41 | 1.82 | 0.38 | 1.52 |
| breakout_top10 | HMM 2 states · full · soft | 2.04 | -0.95 | 1.31 | 1.40 | 0.00 | 0.25 |
| breakout_top10 | HMM 2 states · full · switch | 2.04 | -0.95 | 1.30 | 1.36 | -0.10 | 0.36 |
| breakout_top10 | HMM 2 states · price · soft | 1.80 | -0.58 | 1.48 | 1.48 | 0.56 | 0.51 |
| breakout_top10 | HMM 2 states · price · switch | 1.89 | -0.63 | 1.42 | 1.46 | 0.65 | 0.47 |
| breakout_top10 | HMM 3 states · full · soft | 2.04 | -0.46 | 1.60 | 1.62 | 0.55 | 0.53 |
| breakout_top10 | HMM 3 states · full · switch | 2.04 | -0.51 | 1.60 | 1.65 | 0.65 | 0.54 |
| breakout_top10 | HMM 3 states · price · soft | 1.99 | -0.81 | 1.67 | 1.57 | 0.67 | 0.70 |
| breakout_top10 | HMM 3 states · price · switch | 2.00 | -0.88 | 1.69 | 1.50 | 0.67 | 0.70 |
| breakout_top10 | HMM 4 states · full · soft | 2.01 | -1.29 | 1.55 | 1.36 | 0.23 | 0.70 |
| breakout_top10 | HMM 4 states · full · switch | 2.00 | -1.41 | 1.55 | 1.21 | 0.19 | 0.70 |
| breakout_top10 | HMM 4 states · price · soft | 1.82 | -0.76 | 1.64 | 1.67 | 0.83 | 0.70 |
| breakout_top10 | HMM 4 states · price · switch | 1.76 | -0.88 | 1.67 | 1.68 | 0.89 | 0.74 |
| breakout_top10 | none | 2.04 | -0.84 | 1.72 | 1.84 | 0.46 | 0.56 |
| tsmom_regime | 200d | 0.18 | 0.00 | 1.78 | 1.61 | -0.39 | 1.59 |
| tsmom_regime | HMM 2 states · full · soft | 1.97 | -1.14 | 1.09 | 1.76 | -0.59 | 0.70 |
| tsmom_regime | HMM 2 states · full · switch | 1.97 | -1.18 | 1.05 | 1.68 | -0.82 | 0.79 |
| tsmom_regime | HMM 2 states · price · soft | 1.41 | -0.73 | 1.46 | 1.64 | 0.55 | 0.27 |
| tsmom_regime | HMM 2 states · price · switch | 1.51 | -0.61 | 1.38 | 1.53 | 0.63 | 0.18 |
| tsmom_regime | HMM 3 states · full · soft | 1.97 | -0.70 | 1.71 | 1.80 | 0.49 | 0.19 |
| tsmom_regime | HMM 3 states · full · switch | 1.97 | -0.67 | 1.76 | 1.86 | 0.63 | 0.15 |
| tsmom_regime | HMM 3 states · price · soft | 1.91 | -0.91 | 1.70 | 1.52 | 0.01 | 0.15 |
| tsmom_regime | HMM 3 states · price · switch | 1.89 | -0.99 | 1.69 | 1.43 | 0.04 | 0.13 |
| tsmom_regime | HMM 4 states · full · soft | 1.84 | -0.94 | 1.50 | 1.67 | -0.62 | 0.14 |
| tsmom_regime | HMM 4 states · full · switch | 1.86 | -0.95 | 1.47 | 1.43 | -0.62 | 0.13 |
| tsmom_regime | HMM 4 states · price · soft | 1.84 | -1.11 | 1.70 | 1.63 | -0.07 | 0.17 |
| tsmom_regime | HMM 4 states · price · switch | 1.82 | -1.20 | 1.74 | 1.62 | -0.07 | 0.23 |
| tsmom_regime | none | 1.97 | -1.44 | 1.89 | 1.71 | -0.63 | 0.08 |
| tsmom_top20 | 200d | 0.35 | 0.00 | 1.22 | 0.37 | -0.29 | 1.50 |
| tsmom_top20 | HMM 2 states · full · soft | 2.08 | -1.32 | 1.03 | 0.67 | -0.64 | 0.73 |
| tsmom_top20 | HMM 2 states · full · switch | 2.08 | -1.37 | 0.99 | 0.59 | -0.89 | 0.86 |
| tsmom_top20 | HMM 2 states · price · soft | 1.32 | -0.71 | 1.31 | 0.62 | 0.53 | -0.07 |
| tsmom_top20 | HMM 2 states · price · switch | 1.42 | -0.60 | 1.25 | 0.49 | 0.62 | -0.11 |
| tsmom_top20 | HMM 3 states · full · soft | 2.08 | -0.91 | 1.49 | 0.92 | 0.47 | -0.18 |
| tsmom_top20 | HMM 3 states · full · switch | 2.08 | -0.87 | 1.56 | 1.01 | 0.63 | -0.22 |
| tsmom_top20 | HMM 3 states · price · soft | 1.87 | -1.21 | 1.42 | 0.51 | 0.14 | -0.14 |
| tsmom_top20 | HMM 3 states · price · switch | 1.85 | -1.31 | 1.40 | 0.38 | 0.15 | -0.16 |
| tsmom_top20 | HMM 4 states · full · soft | 1.60 | -1.22 | 1.40 | 0.71 | -0.53 | -0.15 |
| tsmom_top20 | HMM 4 states · full · switch | 1.58 | -1.24 | 1.39 | 0.50 | -0.55 | -0.16 |
| tsmom_top20 | HMM 4 states · price · soft | 1.52 | -1.31 | 1.48 | 0.50 | 0.04 | -0.08 |
| tsmom_top20 | HMM 4 states · price · switch | 1.48 | -1.41 | 1.53 | 0.52 | 0.07 | -0.02 |
| tsmom_top20 | none | 2.08 | -1.68 | 1.31 | 0.50 | -0.58 | -0.23 |
| tsmom_tranches | 200d | 0.24 | 0.00 | 1.33 | 0.68 | 0.05 | 1.48 |
| tsmom_tranches | 200d (native) | 0.84 | 0.89 | 1.30 | 0.59 | 0.08 | 1.31 |
| tsmom_tranches | HMM 2 states · full · soft | 2.01 | -1.34 | 1.26 | 0.64 | -0.49 | 1.13 |
| tsmom_tranches | HMM 2 states · full · switch | 2.01 | -1.36 | 1.24 | 0.57 | -0.76 | 1.24 |
| tsmom_tranches | HMM 2 states · price · soft | 1.63 | -0.77 | 1.46 | 0.67 | 0.62 | 0.21 |
| tsmom_tranches | HMM 2 states · price · switch | 1.72 | -0.63 | 1.42 | 0.58 | 0.73 | 0.20 |
| tsmom_tranches | HMM 3 states · full · soft | 2.01 | -1.09 | 1.62 | 0.94 | 0.58 | 0.12 |
| tsmom_tranches | HMM 3 states · full · switch | 2.01 | -1.02 | 1.68 | 1.06 | 0.73 | 0.04 |
| tsmom_tranches | HMM 3 states · price · soft | 1.86 | -1.33 | 1.60 | 0.66 | 0.19 | 0.14 |
| tsmom_tranches | HMM 3 states · price · switch | 1.86 | -1.43 | 1.62 | 0.53 | 0.15 | 0.07 |
| tsmom_tranches | HMM 4 states · full · soft | 1.53 | -1.32 | 1.55 | 0.62 | -0.13 | 0.13 |
| tsmom_tranches | HMM 4 states · full · switch | 1.56 | -1.33 | 1.56 | 0.40 | -0.14 | 0.07 |
| tsmom_tranches | HMM 4 states · price · soft | 1.35 | -1.38 | 1.63 | 0.74 | 0.41 | 0.23 |
| tsmom_tranches | HMM 4 states · price · switch | 1.29 | -1.52 | 1.66 | 0.76 | 0.45 | 0.26 |
| tsmom_tranches | none | 2.01 | -1.31 | 1.52 | 0.90 | -0.03 | 0.01 |

### State stability

`switches_yr`: gate changes a year from 2021-07 (soft: days the scale moves by more than 0.25); `mean_run_days`: mean run of the most likely state; `exp_duration_days`: median over fits of the mean expected state duration from the transition matrix; `undecided_share`: out-of-sample days with P(bull) between 0.4 and 0.6; `refit_agreement`: on the month after each refit, the share of days the new and the previous fit make the same bull call.

| gate | fits | switches_yr | mean_run_days | exp_duration_days | undecided_share | refit_agreement | bull_share_oos |
|---|---|---|---|---|---|---|---|
| HMM 2 states · price · soft | 66 | 19.60 | 28.21 | 49.30 | 0.01 | 0.95 | 0.42 |
| HMM 2 states · price · switch | 66 | 12.75 | 28.21 | 49.30 | 0.01 | 0.95 | 0.42 |
| HMM 3 states · price · soft | 66 | 15.03 | 17.60 | 27.66 | 0.01 | 0.96 | 0.60 |
| HMM 3 states · price · switch | 66 | 10.85 | 17.60 | 27.66 | 0.01 | 0.96 | 0.60 |
| HMM 4 states · price · soft | 66 | 17.32 | 13.90 | 22.70 | 0.00 | 0.93 | 0.70 |
| HMM 4 states · price · switch | 66 | 11.61 | 13.90 | 22.70 | 0.00 | 0.93 | 0.70 |
| HMM 2 states · full · soft | 66 | 13.70 | 29.97 | 51.31 | 0.01 | 0.98 | 0.31 |
| HMM 2 states · full · switch | 66 | 10.28 | 29.97 | 51.31 | 0.01 | 0.98 | 0.31 |
| HMM 3 states · full · soft | 66 | 18.27 | 22.56 | 32.15 | 0.01 | 0.98 | 0.44 |
| HMM 3 states · full · switch | 66 | 11.42 | 22.56 | 32.15 | 0.01 | 0.98 | 0.44 |
| HMM 4 states · full · soft | 66 | 17.51 | 14.98 | 24.63 | 0.02 | 0.93 | 0.46 |
| HMM 4 states · full · switch | 66 | 11.61 | 14.98 | 24.63 | 0.02 | 0.93 | 0.46 |
| 200d | 0 | 9.32 | 38.36 | n/a | 0.00 | n/a | 0.60 |

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
| breakout_top10 | 1.05 | 0.21 |
| tsmom_top20 | 0.53 | 0.21 |
| tsmom_tranches | 0.67 | 0.18 |
| tsmom_regime | 0.97 | 0.21 |

The pick applied one day late:

| book | gate | sel_taker 35bps | oos_maker 15bps | oos_taker 35bps | cagr_taker 35bps | dd_taker 35bps | turnover_yr | expo |
|---|---|---|---|---|---|---|---|---|
| breakout_top10 | HMM 3 states · full · switch · one day late | 0.96 | 1.08 | 0.99 | 0.19 | 0.25 | 8.77 | 0.19 |
| tsmom_top20 | HMM 3 states · full · switch · one day late | 0.81 | 0.62 | 0.46 | 0.06 | 0.23 | 12.76 | 0.18 |
| tsmom_tranches | HMM 3 states · full · switch · one day late | 0.74 | 0.69 | 0.61 | 0.09 | 0.19 | 6.86 | 0.18 |
| tsmom_regime | HMM 3 states · full · switch · one day late | 0.96 | 1.02 | 0.86 | 0.15 | 0.24 | 14.33 | 0.20 |

P(bull) of the pick, mean per year: 2021 1.00, 2022 0.34, 2023 0.61, 2024 0.52, 2025 0.27, 2026 0.57.

### Deflation

Prior: 265 trials, variance backed out of the fast strategies' bar (2.74 over 265); here 66 trials at 35 bps. Pooled bar 2.55 over 331. The difference test uses the variance of the 48 HMM difference series' Sharpes (daily 3.27e-04) with the same 331 trials.

Trials counted here: breakout_top10 · none; breakout_top10 · 200d; breakout_top10 · HMM 2 states · price · soft; breakout_top10 · HMM 2 states · price · switch; breakout_top10 · HMM 3 states · price · soft; breakout_top10 · HMM 3 states · price · switch; breakout_top10 · HMM 4 states · price · soft; breakout_top10 · HMM 4 states · price · switch; breakout_top10 · HMM 2 states · full · soft; breakout_top10 · HMM 2 states · full · switch; breakout_top10 · HMM 3 states · full · soft; breakout_top10 · HMM 3 states · full · switch; breakout_top10 · HMM 4 states · full · soft; breakout_top10 · HMM 4 states · full · switch; tsmom_top20 · none; tsmom_top20 · 200d; tsmom_top20 · HMM 2 states · price · soft; tsmom_top20 · HMM 2 states · price · switch; tsmom_top20 · HMM 3 states · price · soft; tsmom_top20 · HMM 3 states · price · switch; tsmom_top20 · HMM 4 states · price · soft; tsmom_top20 · HMM 4 states · price · switch; tsmom_top20 · HMM 2 states · full · soft; tsmom_top20 · HMM 2 states · full · switch; tsmom_top20 · HMM 3 states · full · soft; tsmom_top20 · HMM 3 states · full · switch; tsmom_top20 · HMM 4 states · full · soft; tsmom_top20 · HMM 4 states · full · switch; tsmom_tranches · none; tsmom_tranches · 200d; tsmom_tranches · HMM 2 states · price · soft; tsmom_tranches · HMM 2 states · price · switch; tsmom_tranches · HMM 3 states · price · soft; tsmom_tranches · HMM 3 states · price · switch; tsmom_tranches · HMM 4 states · price · soft; tsmom_tranches · HMM 4 states · price · switch; tsmom_tranches · HMM 2 states · full · soft; tsmom_tranches · HMM 2 states · full · switch; tsmom_tranches · HMM 3 states · full · soft; tsmom_tranches · HMM 3 states · full · switch; tsmom_tranches · HMM 4 states · full · soft; tsmom_tranches · HMM 4 states · full · switch; tsmom_regime · none; tsmom_regime · 200d; tsmom_regime · HMM 2 states · price · soft; tsmom_regime · HMM 2 states · price · switch; tsmom_regime · HMM 3 states · price · soft; tsmom_regime · HMM 3 states · price · switch; tsmom_regime · HMM 4 states · price · soft; tsmom_regime · HMM 4 states · price · switch; tsmom_regime · HMM 2 states · full · soft; tsmom_regime · HMM 2 states · full · switch; tsmom_regime · HMM 3 states · full · soft; tsmom_regime · HMM 3 states · full · switch; tsmom_regime · HMM 4 states · full · soft; tsmom_regime · HMM 4 states · full · switch; breakout_top10 · 200d (native); tsmom_tranches · 200d (native); breakout_top10 · walk-forward HMM gate; breakout_top10 · HMM 3 states · full · switch · one day late; tsmom_top20 · walk-forward HMM gate; tsmom_top20 · HMM 3 states · full · switch · one day late; tsmom_tranches · walk-forward HMM gate; tsmom_tranches · HMM 3 states · full · switch · one day late; tsmom_regime · walk-forward HMM gate; tsmom_regime · HMM 3 states · full · switch · one day late.
