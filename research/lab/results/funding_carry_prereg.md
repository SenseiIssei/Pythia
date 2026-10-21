# Cross-sectional funding carry on perpetuals (survey #1): pre-registration

Registered 2026-10-21 and committed before any return below was computed.
Sketch: candidate 1 of `proposals/2026-10-21-strategy-survey.md`; every number
was checked against `xs_daily`, `m4_residual` and the data on the PC before
this file was committed, and the changes to the sketch are listed at the end.
Code: `lab.experiments.funding_carry` (written after this file). Results go to
`results/funding_carry.md`. Nothing here may change once a result exists.
Registered together with `trend_shorts`, `flush_long` and
`kraken_funding_gap` (37 trials in all).

## Question

Does a market-neutral perp book long the coins with the lowest recent funding
and short the coins with the highest, net of the funding each side pays and
of Kraken Futures taker costs, earn anything out of sample from 2024 that is
not the low-vol long/short book and BTC?

## Mechanism and why now

Funding is the price of leverage that trend-chasing longs pay to scarce
arbitrage capital (Schmeling, Schrimpf and Todorov 2023; He, Manela, Ross and
von Wachter). Coins with high funding are crowded and may underperform after
funding; coins with negative funding may carry a squeeze premium. The lab
never ran carry as a stand-alone book: M4 uses fund1, fund7 and basis as
features, and `m4_residual` found that its funding-aware pick leans on the
low-vol book (beta 0.71). High funding is mostly the hot, high-vol coins, so
carry and low vol overlap; the residual test is the point of this study.
Kraken Futures (a demo connector is being added on another branch) makes a
perp book tradeable for the first time.

## Data

- The `xs_daily` panel, rebuilt from the PC's hourly Binance spot history
  and the USD-M funding archive (both to 2026-10-20) into a separate cache
  (`PYTHIA_CACHE`), with `xs_daily.build_panel` unchanged. The cached panel
  of 2026-10-07 that `m4_residual` used is not touched.
- Universe each day: coins eligible in `xs_daily` (60 days of history,
  1 M USD average daily volume) with a live USDT perpetual, cut to the 100
  with the highest 28-day perp volume (`xs_daily.book`'s rule). Dead coins
  stay in (survivorship-free); a coin whose segment ends is carried at its
  last close.
- Returns `R1` between consecutive entry prices (the first hourly close after
  the decision day), funding `fund_hold` paid while held, exactly as every M4
  book.
- The holdout ends on the last decision day whose `fund_hold` is complete
  (`xs_daily.add_net_labels`' rule; expected 2026-10-18).

## Signals (known at the end of decision day d)

- **F1**: funding settled during day d (`fund1`).
- **F7**: funding settled over the last 7 days (`fund7`).
- **F28**: funding settled over the last 28 days (rolling sum of `fund1`,
  per coin segment).

Score = minus the signal: long the lowest funding, short the highest.

## Books

`xs_daily.book` with `long_short=True`: k long and k short, half the capital
per side, equal weight, held in overlapping tranches, no "no paying shorts"
rule.

- k: 10 or 20.
- Rebalance: three overlapping 3-day tranches (hold 3), or seven overlapping
  7-day tranches (hold 7, "weekly" without a weekday choice).

Daily net = gross + funding - turnover x cost.

## Costs (per unit of one-way turnover)

- **Judged: 10 bps.** Kraken Futures taker 5 bps plus 5 bps of half-spread.
  A snapshot of Kraken's public tickers on 2026-10-21 shows median
  half-spreads of 1.9 bps for the 20 most traded PF perpetuals, 2.8 bps for
  ranks 20 to 50 and 4.5 bps for ranks 50 to 100.
- Stress: 20 bps.
- Reported, not judged: 41 bps (the lab's earlier perp cost, comparable with
  `m4_residual`) and 0 bps (a maker at zero fee, an upper bound only: no
  spread paid, no adverse selection, every order filled).

## Windows and the pick

Selection 2020-08-01 to 2023-12-31 (about 40 eligible perps in late 2020,
100 or more from 2021); holdout 2024-01-01 to the end above. The pick is the
book with the highest selection-window Sharpe at 10 bps among the 12.

## The residual

As `m4_residual`: the low-vol book of the pick's shape (score minus `vol28`,
same k, same tranches, same universe, costs and funding) and BTC (BTCUSDT's
`R1`, no costs). OLS of the pick's daily net return at 10 bps on the low-vol
book's at 10 bps and on BTC's, with an intercept, over 2022-01-01 to
2023-12-31; the betas b1, b2 are frozen. In the holdout
R = pick - b1 x lowvol - b2 x BTC (intercept kept in R).

## Trials (13)

3 signals x 2 sizes x 2 rebalances = 12 books, plus R = 13.

**Pool.** 1,140 hand trials after `polymarket` (1,124 before it plus its 16),
600 factory genomes, and the 37 trials registered together today
(`funding_carry` 13, `trend_shorts` 12, `flush_long` 8,
`kraken_funding_gap` 4): **1,777**. Registrations on other branches that are
not merged yet (the rebalance band study) are not in this number. Deflation
as in `m4_residual`: hand trials at the variance backed out of the
published bar (377 at 2.43), the factory's in-sample Sharpes, today's trials
at their own variance.

## Pass rule (all, for the pick)

1. Holdout Sharpe above 0.5 at 10 bps and above 0 at 20 bps.
2. Positive in at least 2 of 2024, 2025 and 2026.
3. One day late (the score of day d-1 used on day d) still above 0 at 10 bps.
4. R's holdout Sharpe above 0.3 at 10 bps, and the 5 % bound of a
   stationary bootstrap of R's Sharpe (mean block 20 days, 4,000 draws, seed
   20261021) above 0.

Confirmed only with R's deflated p above 0.95 over the pool of 1,777.

## Kill rule

R's holdout Sharpe at or below 0.1 at 10 bps: funding carry is recorded as a
re-labelled low-vol bet and the lab stops on it. Anything between is "not
shown to earn beyond low vol".

## If it passes

A lab paper book `funding_carry` with signed weights (longs positive, shorts
negative) in the format of the perps demo route's signal, marked
experimental if R's deflated p is not above 0.95, and a job in
`research/ops/jobs.yaml` in the same format as the others, disabled until the
perps demo route is deployed. Nothing is deployed.

## Reported, not judged

All 12 books at 0, 10, 20 and 41 bps in and out of sample; per year; the
funding each leg paid or received; the share of the pick's names that the
low-vol book also holds; the daily rank IC of each signal with the next 3
days' funding-net return; R at 0 and 20 bps; the regression refitted on the
holdout; rolling one-year betas; the pick restricted to the coins Kraken
Futures lists today (not survivorship-free, information only).

## What could fool us

High-funding coins are the volatile, hyped ones, so carry can be low vol
under another name; the frozen betas and the overlap number are there for
that. Carry decayed after 2024 in the literature, so the selection window
(2020 to 2023, with the 2021 leverage boom) may pick a variant that worked
only then. The price legs use spot entry prices, not perp prices (basis
ignored), as in every M4 book. Kraken Futures lists fewer coins and is
thinner than Binance; capacity is small.

## Changes to the sketch

- Pool 1,777 (the sketch said 1,724 after `gated_btc`; `polymarket` added
  16, today's four studies 37).
- Judged at 10 bps (Kraken Futures taker plus spread, measured), not at 41
  bps; 70 bps replaced by a 20 bps stress. 41 and 0 bps reported.
- The survivorship-free universe is the judged one; the Kraken-listed
  restriction uses today's listing, so it is information only, and the
  "twin positive" gate is replaced by the day-late gate.
- Residual betas fitted at the judged cost.
- Holdout to the funding archive's end (expected 2026-10-18) on a freshly
  built panel.
