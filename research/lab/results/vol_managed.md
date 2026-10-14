# Volatility-managed exposure on the Alpaca coins (C11)

`python -m lab.experiments.vol_managed`

## Pre-registration (written before the first run)

**Question.** Does volatility-managed long exposure (each day hold
min(cap, target vol / forecast vol) of the asset, the rest in cash) on BTC, ETH
and an equal-weight basket of the 15 coins Alpaca lists beat buying and holding
the same asset at Alpaca costs out of sample, after counting every trial? And
does managing the whole book's volatility improve `breakout_top10` or
`tsmom_tranches` as an overlay?

**What the lab already knows.** The sweep's volmom family scaled the tsmom
book by its own trailing vol (Barroso and Santa-Clara, Moreira and Muir): every
scaled variant was worse than the unscaled one. M6 (`vol_daily`) found the
30-day mean of realised variance the best forecast for sizing books (BTC vol
target 40 %, at most 1x, daily: holdout Sharpe 0.82 at 15 bps; faster
forecasts 0.64 to 0.72). This study asks the question directly on the Alpaca
coins, at Alpaca costs, with no-trade bands, and against buy and hold.

**Coins and data.** BTC ETH SOL XRP DOGE ADA AVAX LINK LTC DOT BCH UNI AAVE PEPE
FIL. Binance USDT spot 1h archives from data.binance.vision (every USDT pair
ever listed, delisted ones included, 2020-01 to 2026-09), the sweep's daily
panel rebuilt from them (`fam_common.load_panel`). For M1, Binance 1m spot
archives of M1's 20 coins. Daily bars close at 00:00 UTC.

**Split.** In sample 2021-01-01 to 2023-12-31 (M1's walk-forward forecasts
start in 2021-01; every variant uses the same window), out of sample
2024-01-01 to the data's end. Daily returns, Sharpe annualised with 365 days.

**Forecasts** of a coin's volatility at the close of day d, all known at that
close:

| key | forecast |
|---|---|
| RW30 | square root of the mean daily realised variance of the last 30 days (daily RV = sum of squared hourly log returns): the panel's `sigma`, what the books use |
| EWMA | RiskMetrics smoother, lambda 0.94, on the same daily RV (M6's better EWMA) |
| M1 | M1 rebuilt point-in-time: `vol.py`'s features and LightGBM parameters, 20 coins pooled, walk-forward by quarter from 2021 with its 24 h embargo; each hour's out-of-sample forecast of the next hour's variance is exp(pred + resid_var / 2). Daily aggregate: 24 x the mean of the 24 one-hour-ahead forecasts issued at the hourly closes of day d. M1's target is 1m realised variance, which is on a different scale from hourly-return RV, so it is multiplied by the coin's ratio of mean hourly-return RV to mean 1m RV over the 365 days up to d (point in time). |

Annual vol = sqrt(365 x daily variance). M1 counts as reproduced if its
walk-forward QLIKE beats HAR on the same folds (the claim it was published
with). If it is not reproduced, or the 1m data cannot be had, HAR-RV on daily
RV (1, 7 and 30-day terms, pooled OLS refit each quarter) takes its slot. The
choice is made by this rule before any book is run on it.

**Asset books.** Cap 1 (Alpaca spot crypto is not marginable: no leverage).

- BTC, ETH: weight min(1, TV / forecast vol), the rest cash.
- Basket: each Alpaca coin eligible on day d (the panel's rule: 60 days old,
  1 M USD a day) gets (1 / n_d) x min(1, TV / its forecast vol), n_d the number
  of eligible Alpaca coins that day.
- No-trade band b: a held position is resized only when |target - current| >
  b x target (the blend study's rule); entries from zero and exits to zero
  always trade.
- Optional gate: everything to cash while BTC's close is below its 200-day
  average (known at the close).

**Grid: 72 asset variants** = 3 assets (BTC, ETH, basket) x 3 forecasts (RW30,
EWMA, M1) x TV (30 %, 50 %) x band (10 %, 25 %) x gate (off, on). Plus 3
gate-only books (fully invested while the gate is on), counted.

**References (not counted, nothing chosen among them).** Buy and hold BTC and
ETH; the basket held at equal weight among eligible Alpaca coins, back to equal
weight on the first day of each month and when membership changes. The
existing books at the same costs: breakout_top10, tsmom_top20, tsmom_tranches.

**Overlays: 8 variants** = 2 books (breakout_top10: Donchian 20/10, top 10
liquid, no regime; tsmom_tranches) x 2 forecasts x band (10 %, 25 %). The
forecast is of the unscaled book's own daily returns, up to the close of d:
RW30 (square root of the mean squared daily return over 30 days) or EWMA
(0.94 on squared daily returns). M1 forecasts coins, not books, so it is left
out here. Scale s_d = min(2, 1 / book exposure_d, c / forecast_d), c the median
of the forecast over the in-sample window (fitted there, applied after), so the
book is never over 100 % invested. Band on s: s moves only when |new - s| > b x
new. Held = s x the unscaled book's weights; return s x the book's return,
turnover s x the book's turnover plus |change in s| x the book's exposure.
Both books on the survivorship-free panel (590 segments, delisted included).

**Costs.** Per unit of one-way turnover: Alpaca taker 25 bps plus about 10 bps
slippage = **35 bps (the base)**; Alpaca maker 15 bps as the optimistic case;
gross. Decided at a close, filled at that close; each pick re-run filled one
day late.

**Picks.** Per asset (3) and per overlay book (2), the variant with the best
in-sample Sharpe at 35 bps: 5 picks.

**Counted trials: 91** = 72 asset variants + 3 gate-only + 8 overlays + 5
picks filled one day late + the basket pick on the survivorship-free twin (the
15 most liquid eligible coins of each day from the sweep's panel, delisted
included, same rule) + the 2 overlay picks restricted to Alpaca coins (the book
an Alpaca autopilot could hold). The pool is the 265 of
`results/fast_strategies.md` (bar 2.74) and these 91: **356**. The prior's
variance is backed out of that bar, its mean is the sweep's; this study's
Sharpes at 35 bps are clipped at +-3 and pooled with it as fast_strategies did.

**Pass rule** (all must hold, else the result is written up as negative and no
paper book is added):

1. out-of-sample Sharpe > 0 at 35 bps;
2. it beats its reference out of sample at 35 bps: asset books a higher Sharpe
   than buy and hold of the same asset and a smaller maximum drawdown;
   overlays a higher Sharpe than the unscaled book;
3. deflated p > 0.95 over the pool of 356;
4. the basket pick's survivorship-free twin and the overlay picks' Alpaca-only
   versions have Sharpe > 0 at 35 bps (BTC and ETH were the two largest coins
   throughout; no twin);
5. positive in at least 2 of the 3 out-of-sample years (2026 partial).

**Reported** for every variant: Sharpe at 0 / 15 / 35 bps in and out of sample,
CAGR, maximum drawdown and vol at 35 bps, turnover a year, average exposure,
per-year Sharpe 2021 to 2026, Sharpe with BTC above and below its 200-day
average; for the picks the stationary bootstrap 90 % band (20-day blocks) of
the Sharpe at 35 bps and the deflated p; the forecast quality of RW30, EWMA and
M1 (QLIKE on next-day RV); and how many of the variants of each asset beat
buy and hold.

## Findings (written after the run, 2026-10-14)

Data: Binance 1h archives downloaded for this study (681 ASCII USDT pairs,
delisted included, 2020-01 to 2026-09), the sweep panel rebuilt from them (590
segments);
the references reproduce the earlier studies (tsmom_tranches 0.52 and
tsmom_top20 0.36 at 35 bps, as in `tsmom_tranches.md`; breakout_top10 1.11 at
35 bps, 1.08 at 41 bps in the sweep). Out of sample is 1004 days (2024-01-01 to 2026-09-30).

1. **Nothing passes; no paper book is added.** Every pick fails the deflation
   bar (deflated p 0.00 over 356 trials, bar about 2.60), and every bootstrap
   90 % band of the picks' Sharpe at 35 bps includes 0. The two overlays also
   fail rule 2: they make their books worse.
2. **Vol management alone does about nothing for Sharpe; it cuts drawdowns.**
   Without the BTC gate the median RW30 variant makes 0.71 on BTC (buy and
   hold 0.76), 0.48 on ETH (0.42) and 0.47 on the basket (0.47) at 35 bps,
   with drawdowns of 48 to 56 % against 53 to 77 %. The literature's Sharpe
   gain does not show up here at Alpaca costs; the drawdown cut is mostly
   just holding less.
3. **The picks are the gate plus sizing.** All three asset picks use RW30 with
   the BTC gate and a 25 % band: BTC 0.81 (drawdown 20 % vs 53 %), ETH 0.85
   (26 % vs 68 %), basket 0.64 (35 % vs 77 %). Gate-only books make 0.71,
   0.59 and 0.48, so sizing adds 0.1 to 0.26 on top of the gate. They lose
   0.2 to 0.3 of Sharpe filled one day late (0.60, 0.55, 0.41) and the
   basket's survivorship-free twin makes 0.27. BTC and the basket lose
   money in 2025. They hold nothing while BTC is below its 200-day average
   (the -3.5 Sharpe there is the exit costs alone).
4. **M1 does not help sizing.** Rebuilt point in time it reproduces its
   published edge (QLIKE 11.8 % below HAR, next hour, DM p 8e-9), but its
   daily aggregate forecasts the next day's RV 7 % worse than RW30 out of
   sample (13 % better in sample: the 1m-to-hourly RV scale moves), and it
   moves the target every day: 7 to 37x turnover a year against 0.3 to 10x
   for RW30. Gross of costs M1 sizing matches RW30 on BTC and ETH (medians
   0.76 vs 0.73 and 0.50 vs 0.49 ungated) and loses on the basket (0.22 vs
   0.49); at 35 bps it loses
   everywhere (basket median 0.00). Same finding as M6: the slow forecast
   sizes best.
5. **Overlays hurt both books**, as the sweep's volmom family found for
   tsmom: breakout_top10 0.97 to 1.05 against 1.11 unscaled (the scale adds 2.5
   to 4x turnover a year), tsmom_tranches 0.12 to 0.27 against 0.52.
6. **Unverified.** Fills at the decision close on Binance prices stand in for
   Alpaca's book; Alpaca's spreads and the 10 bps slippage figure were not
   re-measured; the overlay is modelled as a scaling of the book's returns
   (the drift of a scaled book differs at second order); the deflation
   prior is backed out of fast_strategies' published bar of 2.74, so its
   variance is approximate, and this study's trial mean (0.55, most variants
   are long crypto) widens the pooled variance.

<!-- generated below by lab.experiments.vol_managed; edit above this line only -->

## Results (generated 2026-10-14, data to 2026-09-30)

**Verdict: nothing passes.** Deflation pool 356 trials (prior 265, here 91); the best noise trial is expected at an annual Sharpe of about 2.60.

M1 rebuilt on 20 coins: walk-forward QLIKE 0.2451 against HAR 0.2778 (11.8 % better, DM p 8.3e-09, 965,681 coin-hours): reproduced.

### The picks, judged against the pass rule

Per asset and overlay book, the best in-sample Sharpe at 35 bps. `ref` is buy and hold of the same asset (asset books) or the unscaled book (overlays); `twin_oos_35` the basket's survivorship-free twin or the overlay's Alpaca-only book.

| variant | oos_taker 35bps | ref_oos_35 | dd_35 | ref_dd_35 | y2024 | y2025 | y2026 | deflated_p | boot35_p05 | boot35_p95 | twin_oos_35 | late_oos_35 | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| BTC · RW30 · TV 30 % · band 25 % · BTC gate | 0.81 | 0.76 | 0.20 | 0.53 | 1.54 | -0.38 | 1.55 | 0.00 | -0.31 | 1.85 | n/a | 0.60 | fails: deflated p 0.00 <= 0.95 |
| ETH · RW30 · TV 30 % · band 25 % · BTC gate | 0.85 | 0.42 | 0.26 | 0.68 | 1.23 | 0.42 | 1.26 | 0.00 | -0.28 | 1.93 | n/a | 0.55 | fails: deflated p 0.00 <= 0.95 |
| basket · RW30 · TV 50 % · band 25 % · BTC gate | 0.64 | 0.47 | 0.35 | 0.77 | 1.28 | -0.52 | 1.97 | 0.00 | -0.52 | 1.85 | 0.27 | 0.41 | fails: deflated p 0.00 <= 0.95 |
| breakout_top10 · overlay RW30 · band 25 % | 1.01 | 1.11 | 0.23 | 0.22 | 1.85 | 0.54 | 0.39 | 0.00 | -0.27 | 2.16 | 1.21 | 0.77 | fails: Sharpe below its reference (1.01 vs 1.11); deflated p 0.00 <= 0.95 |
| tsmom_tranches · overlay RW30 · band 25 % | 0.27 | 0.52 | 0.23 | 0.23 | 0.08 | 0.16 | 0.94 | 0.00 | -0.96 | 1.36 | 0.64 | 0.28 | fails: Sharpe below its reference (0.27 vs 0.52); deflated p 0.00 <= 0.95 |

### References at the same costs

| variant | is_taker 35bps | oos_gross | oos_maker 15bps | oos_taker 35bps | cagr_35 | dd_35 | vol_35 | turnover_yr | expo |
|---|---|---|---|---|---|---|---|---|---|
| BTC · buy and hold | 0.52 | 0.76 | 0.76 | 0.76 | 0.28 | 0.53 | 0.47 | 0.00 | 1.00 |
| ETH · buy and hold | 0.87 | 0.42 | 0.42 | 0.42 | 0.06 | 0.68 | 0.68 | 0.00 | 1.00 |
| basket · buy and hold | 1.12 | 0.47 | 0.47 | 0.47 | 0.08 | 0.77 | 0.72 | 1.32 | 1.00 |
| breakout_top10 | 1.40 | 1.27 | 1.20 | 1.11 | 0.23 | 0.22 | 0.21 | 9.27 | 0.24 |
| tsmom_top20 | 1.37 | 0.66 | 0.53 | 0.36 | 0.05 | 0.24 | 0.15 | 12.89 | 0.16 |
| tsmom_tranches | 1.53 | 0.63 | 0.58 | 0.52 | 0.07 | 0.23 | 0.16 | 5.02 | 0.17 |

### How often vol management beats buy and hold (out of sample, 35 bps)

| asset | forecast | variants | beat_sharpe | beat_dd | median_is_35 | hold_is_35 | median_oos_35 | hold_oos_35 |
|---|---|---|---|---|---|---|---|---|
| BTC | RW30 | 8 | 5 | 8 | 0.54 | 0.52 | 0.80 | 0.76 |
| BTC | EWMA | 8 | 6 | 8 | 0.54 | 0.52 | 0.78 | 0.76 |
| BTC | M1 | 8 | 1 | 8 | -0.05 | 0.52 | 0.63 | 0.76 |
| ETH | RW30 | 8 | 7 | 8 | 0.88 | 0.87 | 0.66 | 0.42 |
| ETH | EWMA | 8 | 6 | 8 | 0.87 | 0.87 | 0.57 | 0.42 |
| ETH | M1 | 8 | 2 | 8 | 0.36 | 0.87 | 0.35 | 0.42 |
| basket | RW30 | 8 | 7 | 8 | 0.99 | 1.12 | 0.55 | 0.47 |
| basket | EWMA | 8 | 4 | 8 | 0.97 | 1.12 | 0.50 | 0.47 |
| basket | M1 | 8 | 0 | 8 | 0.11 | 1.12 | 0.08 | 0.47 |

### Forecast quality: QLIKE against the next day's RV, Alpaca coins

| window | forecast | coin_days | qlike | gain_vs_rw30_pct |
|---|---|---|---|---|
| in sample | RW30 | 14650 | 0.54 | 0.00 |
| in sample | EWMA | 14650 | 0.48 | 11.55 |
| in sample | M1 | 14650 | 0.47 | 13.19 |
| out of sample | RW30 | 15045 | 0.46 | 0.00 |
| out of sample | EWMA | 15045 | 0.42 | 8.39 |
| out of sample | M1 | 15045 | 0.50 | -6.98 |

### All BTC variants

| variant | is_taker 35bps | oos_gross | oos_maker 15bps | oos_taker 35bps | cagr_35 | dd_35 | vol_35 | turnover_yr | expo |
|---|---|---|---|---|---|---|---|---|---|
| BTC · RW30 · TV 30 % · band 10 % | 0.52 | 0.72 | 0.71 | 0.69 | 0.18 | 0.46 | 0.32 | 2.22 | 0.68 |
| BTC · RW30 · TV 30 % · band 10 % · BTC gate | 0.60 | 0.92 | 0.88 | 0.82 | 0.19 | 0.19 | 0.25 | 7.34 | 0.42 |
| BTC · RW30 · TV 30 % · band 25 % | 0.57 | 0.59 | 0.58 | 0.57 | 0.14 | 0.48 | 0.30 | 1.14 | 0.65 |
| BTC · RW30 · TV 30 % · band 25 % · BTC gate | 0.67 | 0.91 | 0.87 | 0.81 | 0.18 | 0.20 | 0.24 | 6.88 | 0.41 |
| BTC · RW30 · TV 50 % · band 10 % | 0.37 | 0.81 | 0.81 | 0.80 | 0.29 | 0.52 | 0.44 | 0.79 | 0.95 |
| BTC · RW30 · TV 50 % · band 10 % · BTC gate | 0.49 | 0.89 | 0.85 | 0.80 | 0.24 | 0.30 | 0.34 | 9.46 | 0.56 |
| BTC · RW30 · TV 50 % · band 25 % | 0.48 | 0.73 | 0.73 | 0.73 | 0.24 | 0.47 | 0.41 | 0.25 | 0.86 |
| BTC · RW30 · TV 50 % · band 25 % · BTC gate | 0.57 | 0.90 | 0.86 | 0.80 | 0.24 | 0.30 | 0.34 | 9.17 | 0.57 |
| BTC · EWMA · TV 30 % · band 10 % | 0.53 | 0.66 | 0.65 | 0.63 | 0.16 | 0.46 | 0.30 | 2.34 | 0.67 |
| BTC · EWMA · TV 30 % · band 10 % · BTC gate | 0.54 | 0.88 | 0.84 | 0.78 | 0.17 | 0.19 | 0.24 | 7.40 | 0.41 |
| BTC · EWMA · TV 30 % · band 25 % | 0.63 | 0.65 | 0.65 | 0.64 | 0.16 | 0.44 | 0.30 | 0.99 | 0.65 |
| BTC · EWMA · TV 30 % · band 25 % · BTC gate | 0.61 | 0.88 | 0.84 | 0.78 | 0.17 | 0.19 | 0.23 | 6.68 | 0.39 |
| BTC · EWMA · TV 50 % · band 10 % | 0.38 | 0.77 | 0.77 | 0.76 | 0.27 | 0.52 | 0.43 | 1.27 | 0.91 |
| BTC · EWMA · TV 50 % · band 10 % · BTC gate | 0.54 | 0.92 | 0.88 | 0.82 | 0.24 | 0.28 | 0.33 | 9.79 | 0.56 |
| BTC · EWMA · TV 50 % · band 25 % | 0.50 | 0.87 | 0.86 | 0.86 | 0.31 | 0.46 | 0.42 | 0.71 | 0.86 |
| BTC · EWMA · TV 50 % · band 25 % · BTC gate | 0.58 | 0.93 | 0.89 | 0.83 | 0.25 | 0.30 | 0.34 | 9.26 | 0.56 |
| BTC · M1 · TV 30 % · band 10 % | -0.14 | 0.77 | 0.61 | 0.39 | 0.08 | 0.45 | 0.33 | 36.07 | 0.76 |
| BTC · M1 · TV 30 % · band 10 % · BTC gate | -0.10 | 0.89 | 0.72 | 0.50 | 0.10 | 0.29 | 0.26 | 29.15 | 0.46 |
| BTC · M1 · TV 30 % · band 25 % | -0.06 | 0.74 | 0.62 | 0.46 | 0.10 | 0.44 | 0.32 | 25.60 | 0.72 |
| BTC · M1 · TV 30 % · band 25 % · BTC gate | -0.03 | 0.90 | 0.77 | 0.60 | 0.13 | 0.27 | 0.25 | 21.31 | 0.43 |
| BTC · M1 · TV 50 % · band 10 % | -0.06 | 0.75 | 0.71 | 0.65 | 0.21 | 0.52 | 0.42 | 11.22 | 0.94 |
| BTC · M1 · TV 50 % · band 10 % · BTC gate | 0.03 | 0.83 | 0.76 | 0.66 | 0.18 | 0.32 | 0.33 | 16.43 | 0.57 |
| BTC · M1 · TV 50 % · band 25 % | 0.07 | 0.78 | 0.76 | 0.72 | 0.23 | 0.48 | 0.40 | 6.71 | 0.88 |
| BTC · M1 · TV 50 % · band 25 % · BTC gate | 0.15 | 0.91 | 0.85 | 0.76 | 0.22 | 0.29 | 0.33 | 13.98 | 0.55 |

### All ETH variants

| variant | is_taker 35bps | oos_gross | oos_maker 15bps | oos_taker 35bps | cagr_35 | dd_35 | vol_35 | turnover_yr | expo |
|---|---|---|---|---|---|---|---|---|---|
| ETH · RW30 · TV 30 % · band 10 % | 0.76 | 0.47 | 0.46 | 0.45 | 0.10 | 0.48 | 0.33 | 2.01 | 0.49 |
| ETH · RW30 · TV 30 % · band 10 % · BTC gate | 1.00 | 0.86 | 0.83 | 0.78 | 0.18 | 0.28 | 0.25 | 5.48 | 0.29 |
| ETH · RW30 · TV 30 % · band 25 % | 0.73 | 0.56 | 0.55 | 0.54 | 0.13 | 0.47 | 0.33 | 1.27 | 0.49 |
| ETH · RW30 · TV 30 % · band 25 % · BTC gate | 1.10 | 0.92 | 0.89 | 0.85 | 0.21 | 0.26 | 0.26 | 5.10 | 0.29 |
| ETH · RW30 · TV 50 % · band 10 % | 0.73 | 0.52 | 0.51 | 0.50 | 0.14 | 0.63 | 0.53 | 1.84 | 0.79 |
| ETH · RW30 · TV 50 % · band 10 % · BTC gate | 1.06 | 0.87 | 0.84 | 0.80 | 0.28 | 0.42 | 0.42 | 8.49 | 0.48 |
| ETH · RW30 · TV 50 % · band 25 % | 0.74 | 0.36 | 0.36 | 0.35 | 0.05 | 0.64 | 0.52 | 0.89 | 0.78 |
| ETH · RW30 · TV 50 % · band 25 % · BTC gate | 1.09 | 0.83 | 0.81 | 0.77 | 0.26 | 0.42 | 0.41 | 7.59 | 0.47 |
| ETH · EWMA · TV 30 % · band 10 % | 0.79 | 0.50 | 0.49 | 0.48 | 0.11 | 0.44 | 0.32 | 2.00 | 0.48 |
| ETH · EWMA · TV 30 % · band 10 % · BTC gate | 1.01 | 0.83 | 0.79 | 0.75 | 0.17 | 0.28 | 0.25 | 5.51 | 0.28 |
| ETH · EWMA · TV 30 % · band 25 % | 0.82 | 0.42 | 0.41 | 0.40 | 0.08 | 0.46 | 0.31 | 1.12 | 0.47 |
| ETH · EWMA · TV 30 % · band 25 % · BTC gate | 0.93 | 0.88 | 0.85 | 0.82 | 0.18 | 0.27 | 0.24 | 4.75 | 0.28 |
| ETH · EWMA · TV 50 % · band 10 % | 0.79 | 0.48 | 0.47 | 0.47 | 0.11 | 0.61 | 0.52 | 2.34 | 0.78 |
| ETH · EWMA · TV 50 % · band 10 % · BTC gate | 1.04 | 0.79 | 0.76 | 0.72 | 0.24 | 0.44 | 0.41 | 8.61 | 0.47 |
| ETH · EWMA · TV 50 % · band 25 % | 0.82 | 0.42 | 0.41 | 0.41 | 0.08 | 0.61 | 0.51 | 0.81 | 0.76 |
| ETH · EWMA · TV 50 % · band 25 % · BTC gate | 1.09 | 0.73 | 0.70 | 0.66 | 0.20 | 0.43 | 0.40 | 7.94 | 0.46 |
| ETH · M1 · TV 30 % · band 10 % | 0.13 | 0.56 | 0.41 | 0.21 | 0.01 | 0.51 | 0.38 | 37.25 | 0.57 |
| ETH · M1 · TV 30 % · band 10 % · BTC gate | 0.41 | 0.69 | 0.56 | 0.38 | 0.07 | 0.44 | 0.30 | 26.47 | 0.34 |
| ETH · M1 · TV 30 % · band 25 % | 0.22 | 0.50 | 0.39 | 0.23 | 0.01 | 0.50 | 0.39 | 30.28 | 0.57 |
| ETH · M1 · TV 30 % · band 25 % · BTC gate | 0.40 | 0.64 | 0.53 | 0.38 | 0.07 | 0.41 | 0.30 | 22.25 | 0.33 |
| ETH · M1 · TV 50 % · band 10 % | 0.15 | 0.49 | 0.42 | 0.33 | 0.03 | 0.60 | 0.55 | 25.81 | 0.84 |
| ETH · M1 · TV 50 % · band 10 % · BTC gate | 0.49 | 0.62 | 0.54 | 0.43 | 0.10 | 0.55 | 0.44 | 24.24 | 0.50 |
| ETH · M1 · TV 50 % · band 25 % | 0.32 | 0.38 | 0.34 | 0.28 | 0.01 | 0.60 | 0.53 | 15.70 | 0.80 |
| ETH · M1 · TV 50 % · band 25 % · BTC gate | 0.74 | 0.64 | 0.57 | 0.49 | 0.13 | 0.53 | 0.41 | 17.11 | 0.48 |

### All basket variants

| variant | is_taker 35bps | oos_gross | oos_maker 15bps | oos_taker 35bps | cagr_35 | dd_35 | vol_35 | turnover_yr | expo |
|---|---|---|---|---|---|---|---|---|---|
| basket · RW30 · TV 30 % · band 10 % | 0.80 | 0.50 | 0.48 | 0.47 | 0.09 | 0.41 | 0.26 | 2.23 | 0.40 |
| basket · RW30 · TV 30 % · band 10 % · BTC gate | 1.12 | 0.70 | 0.66 | 0.61 | 0.11 | 0.23 | 0.21 | 4.95 | 0.23 |
| basket · RW30 · TV 30 % · band 25 % | 0.85 | 0.49 | 0.48 | 0.47 | 0.09 | 0.41 | 0.26 | 1.44 | 0.39 |
| basket · RW30 · TV 30 % · band 25 % · BTC gate | 1.16 | 0.72 | 0.69 | 0.65 | 0.12 | 0.23 | 0.20 | 4.54 | 0.22 |
| basket · RW30 · TV 50 % · band 10 % | 0.79 | 0.48 | 0.47 | 0.46 | 0.11 | 0.58 | 0.43 | 3.00 | 0.64 |
| basket · RW30 · TV 50 % · band 10 % · BTC gate | 1.14 | 0.67 | 0.64 | 0.59 | 0.15 | 0.36 | 0.34 | 7.75 | 0.37 |
| basket · RW30 · TV 50 % · band 25 % | 0.83 | 0.53 | 0.52 | 0.51 | 0.13 | 0.57 | 0.42 | 1.91 | 0.62 |
| basket · RW30 · TV 50 % · band 25 % · BTC gate | 1.19 | 0.72 | 0.69 | 0.64 | 0.17 | 0.35 | 0.33 | 7.13 | 0.36 |
| basket · EWMA · TV 30 % · band 10 % | 0.79 | 0.46 | 0.44 | 0.43 | 0.08 | 0.39 | 0.26 | 2.32 | 0.39 |
| basket · EWMA · TV 30 % · band 10 % · BTC gate | 1.11 | 0.64 | 0.60 | 0.55 | 0.10 | 0.24 | 0.20 | 5.03 | 0.22 |
| basket · EWMA · TV 30 % · band 25 % | 0.82 | 0.47 | 0.46 | 0.45 | 0.08 | 0.39 | 0.25 | 1.43 | 0.38 |
| basket · EWMA · TV 30 % · band 25 % · BTC gate | 1.17 | 0.67 | 0.64 | 0.59 | 0.10 | 0.23 | 0.20 | 4.53 | 0.22 |
| basket · EWMA · TV 50 % · band 10 % | 0.78 | 0.45 | 0.44 | 0.42 | 0.09 | 0.57 | 0.42 | 3.21 | 0.63 |
| basket · EWMA · TV 50 % · band 10 % · BTC gate | 1.13 | 0.62 | 0.59 | 0.54 | 0.13 | 0.38 | 0.33 | 7.98 | 0.36 |
| basket · EWMA · TV 50 % · band 25 % | 0.80 | 0.46 | 0.45 | 0.44 | 0.10 | 0.56 | 0.40 | 1.98 | 0.61 |
| basket · EWMA · TV 50 % · band 25 % · BTC gate | 1.17 | 0.65 | 0.61 | 0.57 | 0.14 | 0.36 | 0.32 | 7.22 | 0.35 |
| basket · M1 · TV 30 % · band 10 % | -0.16 | 0.24 | 0.11 | -0.06 | -0.06 | 0.51 | 0.30 | 26.34 | 0.48 |
| basket · M1 · TV 30 % · band 10 % · BTC gate | 0.18 | 0.39 | 0.27 | 0.10 | -0.00 | 0.35 | 0.24 | 19.65 | 0.27 |
| basket · M1 · TV 30 % · band 25 % | -0.06 | 0.21 | 0.11 | -0.02 | -0.05 | 0.50 | 0.30 | 19.62 | 0.47 |
| basket · M1 · TV 30 % · band 25 % · BTC gate | 0.21 | 0.34 | 0.24 | 0.11 | -0.00 | 0.35 | 0.24 | 15.76 | 0.26 |
| basket · M1 · TV 50 % · band 10 % | -0.09 | 0.24 | 0.15 | 0.03 | -0.09 | 0.67 | 0.47 | 27.71 | 0.72 |
| basket · M1 · TV 50 % · band 10 % · BTC gate | 0.27 | 0.34 | 0.24 | 0.11 | -0.03 | 0.52 | 0.38 | 24.87 | 0.41 |
| basket · M1 · TV 50 % · band 25 % | 0.04 | 0.20 | 0.14 | 0.06 | -0.08 | 0.65 | 0.46 | 18.45 | 0.70 |
| basket · M1 · TV 50 % · band 25 % · BTC gate | 0.35 | 0.33 | 0.26 | 0.15 | -0.01 | 0.49 | 0.37 | 19.14 | 0.40 |

### Gate only and overlays

| variant | is_taker 35bps | oos_gross | oos_maker 15bps | oos_taker 35bps | cagr_35 | dd_35 | vol_35 | turnover_yr | expo |
|---|---|---|---|---|---|---|---|---|---|
| BTC · gate only | 0.50 | 0.81 | 0.77 | 0.71 | 0.21 | 0.33 | 0.36 | 10.18 | 0.60 |
| ETH · gate only | 1.01 | 0.65 | 0.63 | 0.59 | 0.19 | 0.59 | 0.53 | 10.18 | 0.60 |
| basket · gate only | 1.49 | 0.54 | 0.51 | 0.48 | 0.11 | 0.61 | 0.59 | 11.13 | 0.60 |
| breakout_top10 · overlay RW30 · band 10 % | 1.40 | 1.23 | 1.12 | 0.97 | 0.17 | 0.22 | 0.18 | 13.54 | 0.24 |
| breakout_top10 · overlay RW30 · band 25 % | 1.44 | 1.26 | 1.16 | 1.01 | 0.18 | 0.23 | 0.18 | 12.96 | 0.24 |
| breakout_top10 · overlay EWMA · band 10 % | 1.34 | 1.27 | 1.16 | 1.00 | 0.16 | 0.20 | 0.16 | 12.92 | 0.23 |
| breakout_top10 · overlay EWMA · band 25 % | 1.40 | 1.30 | 1.19 | 1.05 | 0.17 | 0.19 | 0.16 | 11.78 | 0.22 |
| tsmom_tranches · overlay RW30 · band 10 % | 1.43 | 0.42 | 0.34 | 0.24 | 0.02 | 0.23 | 0.11 | 5.75 | 0.10 |
| tsmom_tranches · overlay RW30 · band 25 % | 1.48 | 0.45 | 0.38 | 0.27 | 0.02 | 0.23 | 0.11 | 5.63 | 0.11 |
| tsmom_tranches · overlay EWMA · band 10 % | 1.41 | 0.30 | 0.22 | 0.12 | 0.01 | 0.21 | 0.10 | 5.00 | 0.10 |
| tsmom_tranches · overlay EWMA · band 25 % | 1.42 | 0.38 | 0.31 | 0.21 | 0.02 | 0.20 | 0.10 | 4.72 | 0.10 |

### Checks on the picks

| variant | is_taker 35bps | oos_gross | oos_maker 15bps | oos_taker 35bps | cagr_35 | dd_35 | vol_35 | turnover_yr | expo |
|---|---|---|---|---|---|---|---|---|---|
| BTC · RW30 · TV 30 % · band 25 % · BTC gate · filled one day late | 0.62 | 0.70 | 0.66 | 0.60 | 0.12 | 0.25 | 0.24 | 6.87 | 0.41 |
| ETH · RW30 · TV 30 % · band 25 % · BTC gate · filled one day late | 1.05 | 0.62 | 0.59 | 0.55 | 0.11 | 0.36 | 0.26 | 4.96 | 0.29 |
| basket · RW30 · TV 50 % · band 25 % · BTC gate · filled one day late | 1.27 | 0.48 | 0.45 | 0.41 | 0.08 | 0.43 | 0.34 | 7.15 | 0.36 |
| breakout_top10 · overlay RW30 · band 25 % · filled one day late | 1.41 | 0.99 | 0.90 | 0.77 | 0.13 | 0.22 | 0.19 | 12.38 | 0.24 |
| tsmom_tranches · overlay RW30 · band 25 % · filled one day late | 1.35 | 0.44 | 0.37 | 0.28 | 0.03 | 0.23 | 0.12 | 5.39 | 0.11 |
| basket · RW30 · TV 50 % · band 25 % · BTC gate · survivorship-free top 15 | 0.90 | 0.39 | 0.34 | 0.27 | 0.04 | 0.32 | 0.28 | 9.75 | 0.33 |
| breakout_top10 · overlay RW30 · band 25 % · Alpaca coins only | 1.45 | 1.43 | 1.34 | 1.21 | 0.16 | 0.17 | 0.13 | 8.26 | 0.15 |
| tsmom_tranches · overlay RW30 · band 25 % · Alpaca coins only | 1.55 | 0.80 | 0.73 | 0.64 | 0.03 | 0.07 | 0.05 | 2.53 | 0.05 |

### Per year (Sharpe at 35 bps) and by BTC regime: picks, references, checks

| variant | y2021 | y2022 | y2023 | y2024 | y2025 | y2026 | oos_btc_above | oos_btc_below |
|---|---|---|---|---|---|---|---|---|
| BTC · RW30 · TV 30 % · band 25 % · BTC gate | -0.37 | 0.00 | 1.79 | 1.54 | -0.38 | 1.55 | 1.10 | -3.53 |
| ETH · RW30 · TV 30 % · band 25 % · BTC gate | 1.40 | 0.00 | 1.31 | 1.23 | 0.42 | 1.26 | 1.14 | -3.53 |
| basket · RW30 · TV 50 % · band 25 % · BTC gate | 1.73 | 0.00 | 1.23 | 1.28 | -0.52 | 1.97 | 0.87 | -3.56 |
| breakout_top10 · overlay RW30 · band 25 % | 2.83 | 0.05 | 1.56 | 1.85 | 0.54 | 0.39 | 1.73 | -0.39 |
| tsmom_tranches · overlay RW30 · band 25 % | 2.41 | 0.89 | 1.38 | 0.08 | 0.16 | 0.94 | 0.57 | -1.08 |
| BTC · buy and hold | 0.98 | -1.29 | 2.35 | 1.76 | 0.05 | 0.09 | 1.04 | 0.35 |
| ETH · buy and hold | 2.03 | -0.86 | 1.61 | 0.90 | 0.22 | 0.09 | 0.85 | -0.22 |
| basket · buy and hold | 2.59 | -1.18 | 1.89 | 1.57 | -0.37 | 0.14 | 0.68 | 0.09 |
| breakout_top10 | 2.43 | -0.84 | 1.72 | 1.84 | 0.46 | 0.56 | 1.71 | -0.70 |
| tsmom_top20 | 2.12 | 0.00 | 1.22 | 0.37 | -0.29 | 1.50 | 0.49 | -2.29 |
| tsmom_tranches | 2.41 | 0.89 | 1.30 | 0.59 | 0.08 | 1.31 | 0.76 | -0.81 |
| BTC · RW30 · TV 30 % · band 25 % · BTC gate · filled one day late | -0.09 | 0.00 | 1.49 | 1.23 | -0.38 | 1.20 | 0.96 | -1.23 |
| ETH · RW30 · TV 30 % · band 25 % · BTC gate · filled one day late | 1.48 | 0.00 | 1.10 | 0.75 | 0.26 | 1.05 | 1.03 | -2.03 |
| basket · RW30 · TV 50 % · band 25 % · BTC gate · filled one day late | 1.98 | 0.00 | 1.17 | 0.97 | -0.68 | 1.72 | 0.70 | -1.26 |
| breakout_top10 · overlay RW30 · band 25 % · filled one day late | 2.76 | -0.26 | 1.91 | 1.29 | 0.49 | 0.40 | 1.60 | -0.97 |
| tsmom_tranches · overlay RW30 · band 25 % · filled one day late | 2.39 | 0.79 | 1.13 | -0.05 | 0.46 | 0.56 | 0.58 | -1.01 |
| basket · RW30 · TV 50 % · band 25 % · BTC gate · survivorship-free top 15 | 1.41 | 0.00 | 0.84 | 0.60 | -0.52 | 1.66 | 0.39 | -3.60 |
| breakout_top10 · overlay RW30 · band 25 % · Alpaca coins only | 2.60 | -0.03 | 1.85 | 2.42 | 0.63 | 0.25 | 2.01 | -0.51 |
| tsmom_tranches · overlay RW30 · band 25 % · Alpaca coins only | 2.42 | 0.84 | 1.52 | 1.16 | -0.01 | 1.00 | 1.03 | -1.12 |

### M1 rebuild per quarter (QLIKE, next hour)

| fold | rows | qlike_har | qlike_m1 |
|---|---|---|---|
| 2021Q1 | 38772 | 0.25 | 0.24 |
| 2021Q2 | 39132 | 0.23 | 0.20 |
| 2021Q3 | 39582 | 0.21 | 0.18 |
| 2021Q4 | 39744 | 0.33 | 0.32 |
| 2022Q1 | 38880 | 0.21 | 0.19 |
| 2022Q2 | 39312 | 0.21 | 0.19 |
| 2022Q3 | 39744 | 0.23 | 0.22 |
| 2022Q4 | 39739 | 0.32 | 0.28 |
| 2023Q1 | 38826 | 0.32 | 0.31 |
| 2023Q2 | 41732 | 0.37 | 0.35 |
| 2023Q3 | 44158 | 0.46 | 0.44 |
| 2023Q4 | 44160 | 0.32 | 0.29 |
| 2024Q1 | 43680 | 0.28 | 0.26 |
| 2024Q2 | 43680 | 0.30 | 0.27 |
| 2024Q3 | 44160 | 0.21 | 0.18 |
| 2024Q4 | 44160 | 0.18 | 0.15 |
| 2025Q1 | 43200 | 0.21 | 0.18 |
| 2025Q2 | 43680 | 0.20 | 0.18 |
| 2025Q3 | 44160 | 0.22 | 0.18 |
| 2025Q4 | 44160 | 0.63 | 0.46 |
| 2026Q1 | 43200 | 0.25 | 0.21 |
| 2026Q2 | 43680 | 0.21 | 0.19 |
| 2026Q3 | 44140 | 0.22 | 0.18 |

### Deflation pool

Prior: fast_strategies' 265 trials, variance backed out of its bar (2.74), mean -0.08 (the sweep's 100). Here: 91 trials at 35 bps, mean 0.55, clipped at +-3. Pooled: bar 2.60 over 356.

Trials counted here: BTC · RW30 · TV 30 % · band 10 %; BTC · RW30 · TV 30 % · band 10 % · BTC gate; BTC · RW30 · TV 30 % · band 25 %; BTC · RW30 · TV 30 % · band 25 % · BTC gate; BTC · RW30 · TV 50 % · band 10 %; BTC · RW30 · TV 50 % · band 10 % · BTC gate; BTC · RW30 · TV 50 % · band 25 %; BTC · RW30 · TV 50 % · band 25 % · BTC gate; BTC · EWMA · TV 30 % · band 10 %; BTC · EWMA · TV 30 % · band 10 % · BTC gate; BTC · EWMA · TV 30 % · band 25 %; BTC · EWMA · TV 30 % · band 25 % · BTC gate; BTC · EWMA · TV 50 % · band 10 %; BTC · EWMA · TV 50 % · band 10 % · BTC gate; BTC · EWMA · TV 50 % · band 25 %; BTC · EWMA · TV 50 % · band 25 % · BTC gate; BTC · M1 · TV 30 % · band 10 %; BTC · M1 · TV 30 % · band 10 % · BTC gate; BTC · M1 · TV 30 % · band 25 %; BTC · M1 · TV 30 % · band 25 % · BTC gate; BTC · M1 · TV 50 % · band 10 %; BTC · M1 · TV 50 % · band 10 % · BTC gate; BTC · M1 · TV 50 % · band 25 %; BTC · M1 · TV 50 % · band 25 % · BTC gate; ETH · RW30 · TV 30 % · band 10 %; ETH · RW30 · TV 30 % · band 10 % · BTC gate; ETH · RW30 · TV 30 % · band 25 %; ETH · RW30 · TV 30 % · band 25 % · BTC gate; ETH · RW30 · TV 50 % · band 10 %; ETH · RW30 · TV 50 % · band 10 % · BTC gate; ETH · RW30 · TV 50 % · band 25 %; ETH · RW30 · TV 50 % · band 25 % · BTC gate; ETH · EWMA · TV 30 % · band 10 %; ETH · EWMA · TV 30 % · band 10 % · BTC gate; ETH · EWMA · TV 30 % · band 25 %; ETH · EWMA · TV 30 % · band 25 % · BTC gate; ETH · EWMA · TV 50 % · band 10 %; ETH · EWMA · TV 50 % · band 10 % · BTC gate; ETH · EWMA · TV 50 % · band 25 %; ETH · EWMA · TV 50 % · band 25 % · BTC gate; ETH · M1 · TV 30 % · band 10 %; ETH · M1 · TV 30 % · band 10 % · BTC gate; ETH · M1 · TV 30 % · band 25 %; ETH · M1 · TV 30 % · band 25 % · BTC gate; ETH · M1 · TV 50 % · band 10 %; ETH · M1 · TV 50 % · band 10 % · BTC gate; ETH · M1 · TV 50 % · band 25 %; ETH · M1 · TV 50 % · band 25 % · BTC gate; basket · RW30 · TV 30 % · band 10 %; basket · RW30 · TV 30 % · band 10 % · BTC gate; basket · RW30 · TV 30 % · band 25 %; basket · RW30 · TV 30 % · band 25 % · BTC gate; basket · RW30 · TV 50 % · band 10 %; basket · RW30 · TV 50 % · band 10 % · BTC gate; basket · RW30 · TV 50 % · band 25 %; basket · RW30 · TV 50 % · band 25 % · BTC gate; basket · EWMA · TV 30 % · band 10 %; basket · EWMA · TV 30 % · band 10 % · BTC gate; basket · EWMA · TV 30 % · band 25 %; basket · EWMA · TV 30 % · band 25 % · BTC gate; basket · EWMA · TV 50 % · band 10 %; basket · EWMA · TV 50 % · band 10 % · BTC gate; basket · EWMA · TV 50 % · band 25 %; basket · EWMA · TV 50 % · band 25 % · BTC gate; basket · M1 · TV 30 % · band 10 %; basket · M1 · TV 30 % · band 10 % · BTC gate; basket · M1 · TV 30 % · band 25 %; basket · M1 · TV 30 % · band 25 % · BTC gate; basket · M1 · TV 50 % · band 10 %; basket · M1 · TV 50 % · band 10 % · BTC gate; basket · M1 · TV 50 % · band 25 %; basket · M1 · TV 50 % · band 25 % · BTC gate; BTC · gate only; ETH · gate only; basket · gate only; breakout_top10 · overlay RW30 · band 10 %; breakout_top10 · overlay RW30 · band 25 %; breakout_top10 · overlay EWMA · band 10 %; breakout_top10 · overlay EWMA · band 25 %; tsmom_tranches · overlay RW30 · band 10 %; tsmom_tranches · overlay RW30 · band 25 %; tsmom_tranches · overlay EWMA · band 10 %; tsmom_tranches · overlay EWMA · band 25 %; BTC · RW30 · TV 30 % · band 25 % · BTC gate · filled one day late; ETH · RW30 · TV 30 % · band 25 % · BTC gate · filled one day late; basket · RW30 · TV 50 % · band 25 % · BTC gate · filled one day late; basket · RW30 · TV 50 % · band 25 % · BTC gate · survivorship-free top 15; breakout_top10 · overlay RW30 · band 25 % · filled one day late; breakout_top10 · overlay RW30 · band 25 % · Alpaca coins only; tsmom_tranches · overlay RW30 · band 25 % · filled one day late; tsmom_tranches · overlay RW30 · band 25 % · Alpaca coins only.
