# One book from the market-neutral perp books: pre-registration

Registered 2026-10-21 and committed before any return below was computed.
Code: `lab.experiments.perps_neutral_portfolio` (written after this file).
Results go to `results/perps_neutral_portfolio.md`. Nothing here may change
once a result exists. Registered together with `attention_wiki` and
`intraday_tsmom` (25 trials in all, see "Pool").

## Question

The lab has three market-neutral perp books that each made money out of
sample and each failed deflation: M4 reg7n (`m4_residual`), funding carry
(`funding_carry`) and the low-vol beta-neutral book of the 2026-10-07 sweep
(family 7, vol 60d, top 50). Does one book that holds all three, reweighted
monthly by a fixed rule, beat the single book a researcher would have picked
in 2022-23, with a smaller drawdown and no BTC exposure, after costs, from
2024?

## The three books (as they exist, nothing re-tuned)

- **M4**: `m4_residual.books()` unchanged: reg7n walk-forward scores of the
  2026-10-07 `xs_daily` run, 10 long / 10 short of the 100 most liquid USDT
  perps, rank buffer 50 % (`xs_daily.book_buffer`), funding paid and
  received. The rebuilt series must match the cached pick series to 1e-9, as
  in `m4_residual`.
- **Carry**: `funding_carry`'s pick: score minus 7-day funding, 10/10 of the
  100 most liquid perps, three overlapping 3-day tranches (`xs_daily.book`),
  funding both ways.
- **Low vol**: `fam_lowvol.weights(P, "vol 60d", 50, "beta-neutral BAB")`,
  rebalanced every 7 calendar days from day 100, on the sweep's
  survivorship-free daily panel. One change, because the combination is a
  perp book: both legs are perpetuals (`trend_shorts.sim`: a coin can be held
  only while its perp trades, longs pay and shorts receive funding). The
  sweep's version (spot long leg, no funding on it, `fc.simulate`) is
  reported next to it as a reproduction check.

M4 and Carry use the `xs_daily` panel cached on 2026-10-07 (the one
`m4_residual` is registered on; copied unchanged from the PC to a study
folder on the server). Low vol uses the sweep panel as the paper jobs built
it on 2026-10-21, in a separate study folder.

**Calendar.** Every series is put on the UTC day its return accrues. An
`xs_daily` decision on day d earns from 01:00 of d+1 to 01:00 of d+2, so it
is booked on day d+1; the sweep panel's day t earns close t-1 to close t.
The one-hour offset is ignored. Turnover is charged on the day its return
starts, as in both simulators.

## Costs (per unit of one-way turnover, every book)

- **Judged: 10 bps**, Kraken Futures taker plus half-spread (`perps_common`).
- Stress: 20 bps.
- Maker: 2 bps (Kraken Futures maker fee, no spread, no adverse selection,
  every order filled; an upper bound).
- Legacy: 41 bps (the lab's earlier perp cost).

## The combination

Monthly: on the first return day of each calendar month the book weights
w_i are set from the three books' daily net returns at the same cost over the
trailing 90 days (at least 60). Between reweights the weights drift with
each book's return. Book weights sum to 1 and every book runs at 1x gross
(half long, half short), so the combination has one gross target, 1x before
netting across books. The combined day return is sum_i w_i r_i; its turnover
is sum_i w_i x turnover_i plus sum_i |w_i(new) - w_i(drifted)| on reweight
days. Netting between books (a coin long in one book and short in another)
is not credited, so costs are an upper bound.

## Trials (3)

1. **EW**: w_i = 1/3.
2. **IV**: w_i proportional to 1 / trailing volatility.
3. **ERC**: equal risk contribution on the trailing covariance (each book's
   w_i x (Sigma w)_i equal), solved by fixed-point iteration.

The single books are not new trials (they are counted in their own studies).

**Pool.** 1,328 hand trials before this registration: 1,140 after
`polymarket`, plus the batches registered in parallel on 2026-10-21 that
each started from 1,140 (the four perp studies 37, the equity survey 33,
the vol/ETF batch 22, `crypto_own` 94 with O9's 2 forward trials: 96). Plus
the factory ledger as read at run time (600 in the committed seed, more on
the server after the weekly runs), plus the 25 trials registered here
(`perps_neutral_portfolio` 3, `attention_wiki` 13, `intraday_tsmom` 9), each
study's own at its own variance. Hand trials at the variance backed out of
the published bar (377 at 2.43), as every study since C16. The next study
starts from 1,353 hand trials.

## Windows and the pick

Selection: return days 2022-03-01 to 2023-12-31 (M4 scores start 2022-01;
two months of history for the first weights). Holdout: m4_residual's,
decision days 2024-01-01 to 2026-09-28, return days 2024-01-02 to
2026-09-29. The pick is the method with the highest selection-window Sharpe
at 10 bps. The **reference book** is the single book with the highest
selection-window Sharpe at 10 bps (what one would have run without
combining).

## Pass rule (all, for the pick, at 10 bps from 2024)

1. Sharpe above 0.5, and above 0 at 20 bps.
2. Positive in at least 2 of 2024, 2025, 2026.
3. Stationary bootstrap of the Sharpe (mean block 20 days, 4,000 draws, seed
   20261021): 5 % bound above 0.
4. Sharpe above the reference book's AND maximum drawdown below the
   reference book's (point estimates; the bootstrap band of the Sharpe
   difference is reported).
5. Correlation of daily returns with BTC between -0.3 and 0.3.

Confirmed only with a deflated p above 0.95 over the pool. Kill: Sharpe at
10 bps at or below 0.

## If it passes

A lab paper book `perps_neutral` under `lab/paper/` marked EXPERIMENT (or
confirmed), with the combination's monthly weights over the three books'
targets as signed weights, and a job in `research/ops/jobs.yaml` added
disabled. Nothing wired into an autopilot, no engine restarted.

## Reported, not judged

Each book alone at 2, 10, 20, 41 bps in and out of sample, per year, maximum
drawdown, turnover a year, correlation with BTC; pairwise correlations of
the three books in and out of sample; all three methods at all costs; the
weights over time (mean and range per book); the sweep's low-vol version
(spot long leg) as a reproduction check.

## What could fool us

All three books short the same hot, volatile small caps: low vol is the
common factor (`m4_residual`: beta 0.71; funding carry's residual still had
a low-vol beta of -0.17), so the books may be one bet three times and the
correlations will show it. The holdout years favoured shorting altcoins.
Trailing-vol weights put most of the money in the calmest book, which may
not be the best one. M4 and Carry are judged on a panel that ends with the
2026-10-07 cache.
