# Taker order-flow imbalance across perpetuals: pre-registration

Registered 2026-10-21 and committed before any return below was computed.
Code: `lab.experiments.taker_imbalance_xs` (written after this file).
Results go to `results/taker_imbalance_xs.md`. Nothing here may change once
a result exists. Registered together with `positioning_xs`,
`hedged_breakout` and `pead_xbrl` (24 trials in all, see
`positioning_xs_prereg.md`).

## Question

Every kline Binance publishes says how much of the volume was bought by
takers (aggressive buyers). Does a coin whose takers bought unusually much,
relative to its own last 90 days, keep outperforming over the next 1 to 7
days across the 100 most liquid perps, after funding and Kraken Futures
costs, out of sample from 2024, and beyond the low-vol book and BTC?

## Hypothesis (decided here)

**Continuation: long the most abnormal taker buying, short the most abnormal
taker selling.** Order imbalances carry information that prices absorb over
more than a day (Kyle 1985; Chordia and Subrahmanyam 2004 find that daily
order imbalances are persistent and that lagged imbalances predict the next
day's returns of individual stocks positively). The alternative is
temporary price pressure that reverses (Campbell, Grossman and Wang 1993);
then this book loses and the information-only IC shows a negative sign. Note
that `positioning_xs`, registered with this study, puts the taker ratio of
the futures metrics into a crowding composite traded the other way; the two
registrations hold opposite priors on related inputs at different speeds
(a 90-day z-score of positioning there, a daily flow share here), and the
results will say which, if either, holds.

## Data

- **Order flow**: USD-M perpetual daily klines (`hist/binance_um/klines_1d`,
  every USDT perp Binance ever listed, from the recorder's backfill):
  `taker_buy_volume` and `volume`, both in the base asset.
- **Prices, funding, universe**: the `xs_daily` panel as the paper job built
  it on 2026-10-21 (copied unchanged into a study folder, as in
  `positioning_xs`), `xs_daily.add_net_labels` unchanged. A coin's flow on a
  day is that of the panel's `perp` that day (the base's most liquid perp).
- Entry one hour after the end of the decision day (the M4 timing); returns
  `R1` between entry prices; funding `fund_hold` paid and received.

## Signals (known at the end of decision day d, per perp symbol)

- s1(d) = taker buy volume / volume of day d (days with volume only).
- s7(d) = the same over days d-6 to d (sums).
- **A1** = s1(d) minus the mean of s1 over days d-90 to d-1 (at least 60).
- **A7** = s7(d) minus the mean of s1 over days d-96 to d-7 (at least 60), the
  90 days before the 7-day window.

Score = +A (continuation).

## Books

`xs_daily.book` with `long_short=True`, unchanged (100 most liquid perps
with a score, k long and k short, half the capital per side, overlapping
tranches, funding both ways).

- Signal: A1 or A7.
- k: 10 or 20.
- Hold: 1 day (the whole book re-picked daily), three 3-day tranches, or seven
  7-day tranches.

## Costs (per unit of one-way turnover)

Judged **10 bps**, stress 20 bps; 2 bps (maker upper bound) and 41 bps
reported. As `funding_carry`.

## Windows and the pick

Selection: decision days 2020-08-01 to 2023-12-31 (as `funding_carry`).
Holdout: 2024-01-01 to the last decision day whose `fund_hold` is complete.
The pick is the book with the highest selection-window Sharpe at 10 bps of
the twelve.

## The residual

As `funding_carry`: the low-vol book of the pick's shape and BTC, OLS over
2022-01-01 to 2023-12-31 at 10 bps, betas frozen; R = pick - b1 x lowvol -
b2 x BTC in the holdout (intercept kept).

## Trials (13)

2 signals x 2 sizes x 3 holds = 12 books, plus R = 13.

## Pass rule (all, for the pick)

1. Holdout Sharpe above 0.5 at 10 bps and above 0 at 20 bps.
2. Positive in at least 2 of 2024, 2025 and 2026.
3. One day late (the score of day d-1 used on day d) above 0 at 10 bps.
4. R's holdout Sharpe above 0.3 at 10 bps and the 5 % bound of the stationary
   bootstrap (block 20, 4,000 draws, seed 20261021) above 0.

Confirmed only with R's deflated p above 0.95 over the pool. **Kill:** R at
or below 0.1.

## If it passes

A lab paper book `taker_imbalance_xs` under `lab/paper/` in the format of
`funding_carry`, marked EXPERIMENT unless confirmed, and a job added
disabled. Nothing wired into an autopilot, no engine restarted.

## Reported, not judged

All twelve books at 2, 10, 20, 41 bps in and out of sample, per year,
drawdown, turnover, funding per leg, correlation with BTC; the daily rank IC
of A1 and A7 with the next day's return (`fwd1`) and the next 3 and 7 days'
funding-net return, selection and holdout, t on non-overlapping blocks; the
same IC for the spot taker share already in the panel (`taker1`, `taker7`,
made abnormal the same way) as a check that the perp and spot flows agree;
overlap with the low-vol book.

## What could fool us

Taker volume on Binance perps is partly wash and market-maker hedging, and a
coin's taker share drifts with its venue mix, which is why only the change
against its own 90 days is used. The daily book's turnover is large: at
10 bps a book whose names all change every day pays about 70 % a year, so the 1-day books can
only pass with a very strong signal. Flow and returns of the same day are
strongly correlated by construction; entry an hour after the day ends keeps
the same-day move out of the P&L, but the first hour of the next day is
where most of any continuation would sit, and it is skipped.
