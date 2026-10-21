# breakout_top10 with its BTC beta hedged: pre-registration

Registered 2026-10-21 and committed before any return below was computed.
Code: `lab.experiments.hedged_breakout` (written after this file). Results
go to `results/hedged_breakout.md`. Nothing here may change once a result
exists. Registered together with `positioning_xs`, `taker_imbalance_xs` and
`pead_xbrl` (24 trials in all, see `positioning_xs_prereg.md`).

## Question

`breakout_top10` is the lab's most robust long-only book (the sweep, the
breakout study, every gate but deflation), but a long-only trend book in
crypto is mostly BTC exposure. With its BTC beta hedged by a short in the BTC
perpetual, what is left: does the alpha alone have a Sharpe worth having,
how does it correlate with the market-neutral perp book `perps_neutral`, and
does holding both at equal risk beat `perps_neutral` alone?

## The book (as it runs)

`breakout_top10` exactly as `lab/paper/families.py` builds it:
`fam_breakout.breakout_weights(P, cols, top10, 20, 10, regime=False)`
(Donchian 20/10 on the 10 most liquid coins of each day, each entry sized to
40 % annual vol over 10 slots, capped at 1/10, left to drift until its exit),
simulated from day 60 with `alpaca_universe.sim_daily` (the sweep's
simulator, which also returns the weights held after every close). Panel:
the sweep's survivorship-free daily panel as the paper jobs built it on
2026-10-21 (copied unchanged into a study folder), to its last day.

## The hedge

At the close of day t, with w_i the book's weights after that close and
beta_i coin i's beta to BTC from the daily returns of days t-59 to t (OLS
slope, at least 40 days, BTC's own beta 1; a coin without 40 days gets the
book's median beta that day, or 1 when none has one), the hedge is a BTC
perpetual position of

    h(t) = - sum_i w_i(t) beta_i(t)

of book equity, held to the next close. It earns h x (BTC's return - BTC
perp funding of that day), so a short receives positive funding and pays
negative funding (the panel's funding, as `trend_shorts.gate_btc`). Hedge
turnover is |h(t) - h(t-1) drifted| a day. The book's own beta (holdings,
not the trailing return of the book) is used because the book is often in
cash and a trailing book-return beta would lag every entry by up to 60 days;
the trailing book-return beta hedge is reported, not judged.

## Costs (per unit of one-way turnover)

- **Judged: long leg 35 bps** (Alpaca taker plus slippage, how the lab has
  judged this book since C16), **hedge 10 bps** (Kraken Futures BTC perp
  taker plus half-spread, `perps_common`).
- Stress: 70 bps and 20 bps.
- Reported: 15 bps and 10 bps (the paper book's own modelled Binance cost).

Margin for the short is not charged (the hedge needs collateral on the perp
venue; the return is on book equity).

## Windows

In sample 2020-08-01 to 2023-12-31 (reported only: no parameter is chosen).
Out of sample from 2024-01-01 to the panel's last day. The combination's
window is `perps_neutral_portfolio`'s holdout (return days 2024-01-02 to
2026-09-29), where `perps_neutral` exists.

## `perps_neutral`

`perps_neutral_portfolio`'s pick (ERC of M4 reg7n, funding carry and the
low-vol beta-neutral book, reweighted monthly) at 10 bps, rebuilt by that
study's own functions from the same inputs: the 2026-10-07 `xs_daily` cache
(copied unchanged from the PC into a study folder and removed after) and the
sweep panel. The rebuild must reproduce that study's holdout Sharpe (2.47)
to two decimals, or this study stops.

## Trials (2)

1. **H**: the hedged book, net of both legs' costs and the hedge's funding.
2. **C**: H and `perps_neutral` held at equal risk: weights proportional to
   1 / trailing 90-day volatility of each (at least 60 days), set on the
   first return day of each month and drifting in between
   (`perps_neutral_portfolio.combine`, method IV, which for two books is
   equal risk contribution), reweight trades charged at 35 bps (stress 70).
   Each sleeve at its own judged cost (H at 35/10, `perps_neutral` at 10 bps).

## Pass rules (out of sample)

**H** (all, at the judged cost):
1. Sharpe above 0.5, and above 0 at the stress cost.
2. Positive in at least 2 of 2024, 2025 and 2026.
3. Stationary bootstrap of the Sharpe (mean block 20, 4,000 draws, seed
   20261021): 5 % bound above 0.
4. Correlation of daily returns with BTC between -0.3 and 0.3.
5. One day late (book and hedge both decided a close later) above 0.

**C** (all, on the combination window):
1. Sharpe above `perps_neutral`'s alone AND maximum drawdown not above its
   (point estimates; the bootstrap band of the difference is reported).
2. Sharpe above 0.5, and above 0 at the stress cost.
3. Positive in at least 2 of 2024, 2025 and 2026.
4. Bootstrap 5 % bound of the Sharpe above 0.
5. Correlation with BTC between -0.3 and 0.3.

A pass without a deflated p above 0.95 over the pool is experimental.
**Kill** for H: Sharpe at or below 0 at the judged cost.

## If something passes

A lab paper book under `lab/paper/` (marked EXPERIMENT unless confirmed)
that adds the BTC perp hedge to `breakout_top10`'s targets in the signed
format of the perps route, and a job in `research/ops/jobs.yaml` added
disabled. Nothing wired into an autopilot, no engine restarted.

## Reported, not judged

The unhedged book (in and out of sample, each cost), its alpha and beta to
BTC by OLS on daily returns in each window (alpha a year with its t); H in
sample; the hedge ratio over time (mean, range) and the funding it earned or
paid; H with the trailing 60-day book-return beta instead; H on the coins
Alpaca lists (the rest in cash, how the autopilot runs it); the correlation
of H with `perps_neutral` and with each of its three books; C's weights.

## What could fool us

The book's edge was carried by 2024 and a few trades (`breakout_study`); a
hedged book keeps that concentration and loses the beta that made 2024
look good. Betas estimated on 60 days lag regime changes, and a breakout
entry is often a coin whose beta is about to change. The correlation with
`perps_neutral` is measured over under three years in which both were
running in their favourable regime.
