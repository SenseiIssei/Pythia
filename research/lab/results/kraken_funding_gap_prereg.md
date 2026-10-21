# Kraken against Binance funding gaps (survey O7): pre-registration

Registered 2026-10-21 and committed before any return below was computed.
Sketch: original idea O7 of `proposals/2026-10-21-strategy-survey.md`. The
owner's brief: run it only if Kraken's funding history can be had without a
key. It can, but only for about a year (below). Code:
`lab.collect.kraken_futures` (collector) and
`lab.experiments.kraken_funding_gap` (study), both written after this file.
Results go to `results/kraken_funding_gap.md`. Nothing here may change once a
result exists. Registered together with `funding_carry`, `trend_shorts` and
`flush_long` (37 trials in all).

## Question

When a coin's funding on Kraken Futures runs well above its funding on
Binance, does shorting the Kraken perpetual against a spot long (the spot leg
on Alpaca) collect enough funding, after both venues' costs and the basis
moving against us, to be worth running?

## Data (checked on 2026-10-21)

- **Kraken funding**: the public endpoint
  `futures.kraken.com/derivatives/api/v4/historicalfundingrates?symbol=PF_<X>USD`
  answers without a key, with hourly rates (`relativeFundingRate`, a share of
  the price per hour; positive means longs pay shorts) from
  **2025-10-15 08:00 UTC** only (8,903 hours for PF_XBTUSD and the same start
  for PF_SOLUSD). Nothing older is offered, so the study has one year.
- **Kraken prices**: the public charts endpoint
  `futures.kraken.com/api/charts/v1/mark/PF_<X>USD/1h` (hourly mark price
  candles, no key).
- **Binance**: USD-M funding from the lake (to 2026-10-20) and spot hourly
  closes from the lake as the spot leg's price (Alpaca quotes the same coins
  within a few bps; its fee is charged below).
- **Coins**: the 32 Alpaca coins (`lab.universe.ALPACA`). Kraken lists 31 as
  PF perpetuals today (not SKY); coins without Binance spot history in the
  window (HYPE, expected) drop out. The collector writes to
  `<data>/kraken_futures/` (parquet per symbol), 6 requests a second at most.

## Signal and trade (hourly, everything known at the decision hour)

- K = Kraken's mean relative funding over the last W hours x 8,760
  (annualised); B = Binance funding settled over the last W hours x 8,760 / W
  (annualised). Gap = K - B.
- **Enter** a coin when gap >= theta and K > 0: short the Kraken perpetual
  and buy the same notional of spot.
- **Exit** when gap <= 0 or K <= 0.
- At most 10 positions at a time, the largest gaps first; each position's
  notional is 8 % of capital, so 10 positions use 80 % in spot and 20 % as
  perp margin (capital per position 10 %, "deployed capital").
- Hourly P&L of a position: notional x (spot return - perp return + the
  Kraken funding rate of that hour, received by the short).

W: 24 or 72 hours. theta: 20 % or 50 % a year.

## Costs (per side, each leg)

- **Judged**: spot 35 bps (Alpaca taker plus slippage, as every Alpaca book)
  and perp 10 bps (Kraken Futures taker 5 bps plus half-spread), so a round
  trip costs 90 bps of notional.
- Reported, not judged: maker on both legs (Alpaca 15 bps, Kraken 0).

## Windows and the pick

In sample 2025-10-18 (after the 72-hour warm-up) to 2026-03-31; out of sample
2026-04-01 to 2026-10-19. The pick is the variant with the highest in-sample
net return on capital at the judged costs among the 4.

## Trials (4)

theta {20 %, 50 %} x W {24 h, 72 h} = 4. **Pool: 1,777** (see
`funding_carry_prereg.md`); the book's daily return on capital is deflated.

## Pass rule (all, for the pick, out of sample)

1. At least 10 entries (the sketch's 20 a year, for 6.6 months).
2. Net carry on deployed capital (net P&L over the average capital in open
   positions, annualised) above 5 % a year.
3. The worst calendar week of the book above -2 % of capital.
4. The book's Sharpe on capital above 0, with the 5 % bound of a stationary
   bootstrap (mean block 20 days, 4,000 draws, seed 20261021) above 0.

Confirmed only with a deflated p above 0.95 over the pool.

## Kill rule

Fewer than 10 entries out of sample, or net carry below 2 % a year on
deployed capital.

## If it passes

A proposal only: the trade needs two venues (Alpaca spot and Kraken perps),
which no single demo route trades, so no engine signal is written. A
forward-only collector job is proposed in any case, so the history grows.

## Reported, not judged

Kraken minus Binance funding per coin (mean, share of hours above zero),
every variant in and out of sample, entries, average hold, funding collected
against basis P&L against costs, the maker case.

## What could fool us

One year of history and one regime. The basis between the Kraken mark and
Binance spot is noisy hour to hour and the spot leg is priced at Binance, not
Alpaca. Kraken's funding is computed from its own premium, so a high Kraken
funding may come with a perp trading rich, whose convergence is part of the
P&L (it is in the hourly basis term).

## Changes to the sketch

- Out of sample from 2026-04-01, not 2025: Kraken's keyless history starts
  2025-10-15.
- Entries need 10 out of sample, not 20 a year, for the shorter window.
- Alpaca spot at 35 bps (the lab's Alpaca taker cost) instead of 25 bps, and
  Kraken at 10 bps.
- Pool 1,777.
