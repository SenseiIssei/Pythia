# T11: cross-venue funding, Hyperliquid against Binance. Pre-registration

Registered 2026-10-28 and committed before any number below was computed (while scoping, one look at which inputs
exist on the data folder: Hyperliquid's settled hourly funding for 33 coins from 2023-05-12, Binance USD-M funding
and daily perp klines, the spot daily panel to 2026-10-11, T4's depth files only from 2026-10-21; no return, no
gap statistic). Brief T11 of the training plan of 2026-10-28, on the review of 2026-10-27
(`results/review_2026-10-27.md`, sections 2 and 3), R5's registry (`metrics.trial_pool`,
`<data>/trials/registry.jsonl`) and R6's windows (`results/factory_lockbox_r6.md`). Code:
`lab.experiments.hl_funding_t11` (written after this file). Results go to `results/hl_funding_t11.md`. Nothing here
may change once a result exists. Paper only: no book, gate, engine setting, live path or wallet changes.

## Question

When a coin's funding on Hyperliquid and on Binance USD-M differ by a persistent margin, does holding the pair
delta neutral (long the perp where funding is lower, short where it is higher) earn, after both venues' fees and
spreads of their era, the two funding schedules, the price gap between the two perps moving at entry and exit and
a fill one hour after the decision?

## What is different from kraken_funding_gap (results/kraken_funding_gap.md)

- **Two perps, no spot leg.** Kraken's study shorted the Kraken perp against Alpaca spot at 35 bps a side: the
  spot leg's cost decided it (16 % a year on deployed capital taker, 57 % maker). Here both legs are perps
  (Binance 5 bps taker, Hyperliquid 2.5 to 4.5 bps), so a round trip of the pair costs about a third.
- **Both directions.** Kraken's funding was lower than Binance's on 26 of 30 coins, and that study only traded
  Kraken above. Here the pair is entered whichever venue is higher.
- **History.** Kraken's keyless history is one year (2025-10-15 on); Hyperliquid's is 3.4 years (2023-05-12 on),
  enough for R6's in sample and validation.
- **Funding mechanism.** Hyperliquid settles every hour on its own premium to an oracle of CEX spot prices
  (Binance spot weighted most), capped at 4 % an hour, with the same 0.01 % per 8 hours interest as Binance.
- **Universe and timing.** T5's point-in-time volume rule instead of the Alpaca list; daily fills an hour after an
  hourly signal instead of hourly fills at the signal.

## Data

- **Hyperliquid**: `<data>/free/hyperliquid/funding.parquet` (`lab.collect.hyperliquid`, D2's point-in-time
  format): `ts_us` the settlement, `funding_rate` per hour (positive: longs pay), `premium` (Hyperliquid's hourly
  premium of its perp to the oracle), `known_us`. 33 coins, `lab.universe.ENGINE` as Hyperliquid lists them today
  (kPEPE, kSHIB, kBONK are a thousand coins; the ratio terms below do not care).
- **Binance**: USD-M funding settlements from the lake (`hist/binance_um/funding`, `funding_time_us`,
  `interval_hours`, `funding_rate`; known at the settlement), daily perp klines (`hist/binance_um/klines_1d`), the
  perp found as `kraken_funding_gap.binance_perp` (plain, 1000 or 1000000 prefix). Spot: the lab's daily panel
  (`fam_common.load_panel`).
- **Prices of the two legs.** There is no history of Hyperliquid's mark price or of Binance's hourly perp price on
  the data folder. Both legs are marked once a day at 00:00 UTC: Binance's perp at its daily close; Hyperliquid's
  at Binance spot's daily close times (1 + Hyperliquid's premium of the hour ending at 00:00) (the oracle taken as
  Binance spot). The price gap between the two marks is in every day's P&L, so its move from entry to exit is
  charged in full. This is why the fills are daily.

## Universe (point in time)

On the day of a decision, a coin may be held only if all hold:

- it is in T5's PIT50 (`lab.universe.pit`, n 50, the 30-day median spot dollar volume, pegs out, T4's delisting
  flag when its table is there) as of the previous day's close (the decision is before the day's close);
- **both venues list it**: its first Hyperliquid settlement and its first Binance funding settlement are known
  before the start of the signal window, and the window has its hours (below);
- its Binance perp and spot have a daily bar on the day of the decision.

The Hyperliquid list is today's (the collector records `ENGINE`'s coins): coins Hyperliquid delisted or never
mapped are missing, a survivor bias stated in the report, not fixed.

## Signal, entry, exit (every number fixed here)

- Hourly gap g = (Hyperliquid's settled rate of the hour - Binance's rate in force that hour / its interval in
  hours) x 8,760, a share a year; Binance's rate in force is its last settled rate (the next one is not known).
- **Decision at 23:00 UTC every day**, from rows known by then (Hyperliquid rows by `known_us`, so the 23:00
  settlement stamped a few ms after the hour is not used; Binance's by its settlement time). **Fill one hour late**
  at 00:00 UTC.
- Over the last W hours (W in {8, 24}): the mean gap G and the share of the W hours whose gap has G's sign
  (hours without a row count against it).
- **Enter** when |G| >= theta (theta in {15 %, 30 %} a year) and the share is at least 75 %: if G > 0 short
  Hyperliquid and long Binance, else the reverse, the same notional on both.
- **Exit** at the next decision when G in the pair's direction is 0 or less, or the coin leaves the universe or
  loses a price or funding row the rule needs. One pair per coin; a direction change is an exit and an entry.
- **Limits**: at most 10 pairs; each leg's notional 10 % of capital; new pairs ranked by |G|, largest first.
- **Margin**: each leg at 2x (margin half its notional), so 10 pairs use all capital; the return is on all
  capital. Margin moves between the venues are not charged; the report shows the largest one-day move of a held
  coin and the days with a move of 25 % or more (a 2x leg's margin half gone, a transfer needed that day).

## Funding and P&L

- Hyperliquid pays every hour; Binance at each of its settlements (8 h, or the interval in force, 4 h or 1 h on
  some coins). A pair filled at 00:00 of day d and closed at 00:00 of day e receives the settlements stamped after
  d 00:00 up to and including e 00:00 (by the hour of their stamp), on the leg's notional: the short receives the
  rate, the long pays it.
- Price: each day the long leg's return minus the short leg's, on the marks above.
- Daily return on capital = sum over pairs of 10 % x (funding + price) less the costs of the day's fills.

## Costs of their era (per leg, per side, on the leg's notional)

- **Binance**: the USD-M taker 5 bps (T5's) plus T5's half-spread tier on the coin's 30-day median spot dollar
  volume at the previous close (1 bp at 1 B USD a day or more, 3 from 100 M, 10 from 10 M, 25 from 1 M, 50 below).
  T4's depth files start 2026-10-21, after the windows, so the tiers are used throughout (said in the report).
- **Hyperliquid**: its base-tier taker fee of the era, 2.5 bps to 2023-12-31, 3.5 bps 2024-01-01 to 2025-04-30,
  4.5 bps from 2025-05-01 (its public fee schedules; the switch dates are not on the data folder, so assumed to the
  quarter); half spread one tier wider than Binance's for the same coin (its books are thinner).
- **Capacity**: the judged size is 1k USD a leg (the costs above). At 10k USD a leg both half spreads move one
  tier wider (Binance one, Hyperliquid two). Reported next to the 1k: Hyperliquid's open interest and day volume
  from today's snapshots, and T4's measured 10k order cost of the last days against the tier rule.

## Windows (R6)

In sample from 2023-05-13 (the first full day with 24 hours of Hyperliquid funding) to 2023-12-31; validation
2024-01-01 to 2026-06-30. Every input is cut at 2026-06-30 24:00 before anything is computed; the lockbox
(2026-07-01 on) is not read.

## Trials (5, R5's registry, hand family)

theta {15 %, 30 %} x W {8 h, 24 h} at 1k a leg = 4, and the pick at 10k a leg = 1. Each is registered with its
in-sample Sharpe before any validation number is computed (ids `hand:t11:hl_funding:<theta>_<W>[:10k]`). The pick
is the variant with the highest in-sample Sharpe at 1k.

## Conditions (each pass or fail in the report, the pick at 1k, validation)

1. **Gates**: Sharpe above 0.5, the stationary bootstrap's 5 % above 0 (`director_common.boot_band`), correlation
   with BTC's daily return within +-0.3, at least 20 entries.
2. **DSR all**: DSR over R5's pool of all (factory ledgers counted once by id, these trials included), 0.95 or more
   (higher is better).
3. **DSR family**: the same over the hand family.
4. **PBO**: CSCV (`metrics.cscv`, 16 blocks) over the 4 variants at 1k on in sample plus validation, below 0.2
   (T3's bar for step 2).
5. **Leak**: T1's harness (`lab.leak.check`, frame mode, `known_us`) on the pick's decision function (Hyperliquid
   and Binance funding rows to the targets per decision) finds no leak.

All five pass: a lockbox look is due (not made here) and a paper book proposed. Otherwise nothing follows.

## Reported, not judged

Sharpe, CAGR, drawdown, correlation with BTC for every variant in sample and in validation; funding, price and cost
parts a year; entries, average pairs, average hold; the 10k case; the per-coin mean gap and the share of hours
above 15 % and 30 %; the margin check above; the bar's needed Sharpe on this pool.

## What could fool us

- The marks: Hyperliquid's oracle is not exactly Binance spot and its hourly premium is an average, not the 00:00
  mark; Binance's daily close is the last trade, not the mark. Both add noise to the daily price term; neither
  biases its mean much over a hold of days.
- Today's Hyperliquid list (survivors) and three and a half years of one venue's growth (thin books in 2023).
- The fee dates assumed to the quarter; Hyperliquid's half spread assumed, not measured.
- Binance's rate in force is the last settled one; the funding actually paid is the next one (charged as paid).
