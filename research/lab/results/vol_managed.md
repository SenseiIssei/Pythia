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

<!-- generated below by lab.experiments.vol_managed; edit above this line only -->
