# Trend following with a short leg on perpetuals (survey #5): pre-registration

Registered 2026-10-21 and committed before any return below was computed.
Sketch: candidate 5 of `proposals/2026-10-21-strategy-survey.md`, checked
against `fam_volmom`, `fam_breakout`, `lab.paper.families` and `gated_btc`;
the changes to the sketch are listed at the end. Code:
`lab.experiments.trend_shorts` (written after this file). Results go to
`results/trend_shorts.md`. Nothing here may change once a result exists.
Registered together with `funding_carry`, `flush_long` and
`kraken_funding_gap` (37 trials in all).

## Question

If `tsmom_top20` and `breakout_top10` also short the coins in a downtrend,
on perpetuals, net of funding and Kraken Futures costs, do they beat the same
books long-only on perpetuals out of sample from 2024, and do they beat BTC
held only above its 200-day average?

## Mechanism and why now

Time-series momentum is symmetric in futures markets (Moskowitz, Ooi and
Pedersen 2012; Hurst, Ooi and Pedersen 2017). The lab's books are long-only
and sit in cash in bear markets; `gated_btc` found that the BTC gate carries
them (every book loses on gate-off days). A short leg asks whether the trend
also persists downwards. Kraken Futures makes shorting possible.

## Data

- The sweep's survivorship-free daily panel (`fam_common.load_panel`: every
  USDT pair Binance ever listed, delisted coins included, reused tickers
  split), rebuilt from the PC's hourly history (to 2026-10-20) into a
  separate folder (`PYTHIA_AGENT_OUT`) and cut at **2026-10-19**.
- Perpetual legs: a coin can be held long or short on day t only if its USDT
  perpetual traded that day (`Panel.perp_ok`). Funding `Panel.funding`
  (summed over the day): a long pays it, a short receives it. Prices are the
  spot closes (basis ignored), as in every sweep book.

## Books

The base books are the paper books' rules, moved to perpetuals:

- **tsmom_top20**: hold a coin of the day's 20 most liquid coins with a live
  perp while its 28-day return is positive, each held coin at 40 % annual vol
  over 20 slots, total capped at 1, the long leg flat while BTC closes below
  its 200-day average (`fam_volmom.base_weights` with the perp restriction).
- **breakout_top10**: Donchian 20/10 on the coins that are ever in the day's
  10 most liquid coins with a live perp, entries only while in that top 10,
  40 % vol over 10 slots capped at 1/10 a coin, held until the exit, no
  regime (`fam_breakout.breakout_weights` with the perp restriction).

The short leg mirrors the long rule on the same universe and slots:

- tsmom: short a coin of the top 20 while its 28-day return is negative,
  sized like a long.
- breakout: short when the close is below the lowest close of the previous
  20 days (while in the top 10), cover when it is above the highest close of
  the previous 10 days, sized like a long.

Each side is capped at a gross of 1 (book gross at most 2).

## Variants (per base book)

- **V1 bear 100**: the short leg only while BTC closes below its 200-day
  average (every short covered when it closes above), full size.
- **V2 bear 50**: as V1 at half size.
- **V3 always 100**: the short leg at all times, full size.
- **V4 always 50**: as V3 at half size.
- **V5 dollar-neutral**: long and short legs both without any BTC gate, each
  day the larger side scaled down to the smaller side's gross (flat when one
  side is empty).

V1 and V2 make the gated tsmom book net short in bear markets; V5 is the
market-neutral form.

## Costs (per unit of one-way turnover)

- **Judged: 10 bps** (Kraken Futures taker 5 bps plus 5 bps half-spread; see
  `funding_carry_prereg.md` for the measured spreads). Funding charged.
- Stress: 20 bps. Reported, not judged: 0 bps (zero-fee maker, upper bound)
  and 41 bps. The long-only books on spot at 35 bps (as they run on Alpaca's
  coins) are reported as the reference they replace.

## Windows and the picks

In sample 2020-08-01 to 2023-12-31, out of sample 2024-01-01 to 2026-10-19.
One pick per base book: the variant with the highest in-sample Sharpe at
10 bps among V1 to V5.

## Trials (12)

5 variants x 2 books = 10, plus the difference D of each pick against gated
BTC = 2. The long-only perp books are the paper books at another cost and
venue, and the short leg alone is a component of a variant: neither is a new
trial.

**Pool: 1,777** (1,140 hand trials after `polymarket`, 600 factory genomes,
the 37 registered today; see `funding_carry_prereg.md`).

## Pass rule (per pick, against its long-only perp book, out of sample at 10 bps)

1. Sharpe higher than the long-only book, and higher in at least 2 of 2024,
   2025 and 2026.
2. Maximum drawdown not above the long-only book's.
3. The 90 % band of a stationary bootstrap (mean block 20 days, 4,000 draws,
   seed 20261021) of the Sharpe difference (pick minus long-only) above 0.
4. Filled one close late, still a higher Sharpe than the long-only book on
   time.
5. At 20 bps still a higher Sharpe than the long-only book at 20 bps.
6. The improvement deflated: the daily return difference (pick minus
   long-only) has a deflated p above 0.95 over the pool.

Gates 1 to 5 passed with 6 failed: an experimental book. All six: a
confirmed one.

**Against gated BTC** (reported with every pick, part of the verdict, not a
gate for the book): G holds the BTC perpetual at weight k while BTC closes
above its 200-day average, k = the pick's in-sample vol over G's at k = 1
(capped at 1), at 10 bps plus the funding a long pays; D = pick minus G, its
Sharpe and bootstrap band. "Beats gated BTC" needs D above 0 and the band's
5 % bound above 0.

## Kill rule

The pick's short leg alone (the short weights only, their funding and their
share of the costs) has a Sharpe at or below 0 out of sample at 10 bps:
"shorting the trend on perps does not pay here", and the lab stops on it.

## If a pick passes gates 1 to 5

A lab paper book `<book>_ls` with signed weights for the perps demo route,
experimental unless gate 6 holds, and a job in `research/ops/jobs.yaml`,
disabled until the route is deployed. Nothing is deployed.

## Reported, not judged

Every variant in and out of sample at 0, 10, 20 and 41 bps, per year, the
short leg's return and funding by year (2022 alone may carry it in sample),
average long and short exposure, turnover, Sharpe by the BTC gate's state.

## What could fool us

2022, one long bear market, sits in sample and will flatter every short leg;
the pick may be chosen by it. Short squeezes on small coins are fat-tailed,
and perp funding on crowded shorts can be large and negative for the short.
The perp restriction changes the long-only books slightly (coins without a
perp leave the universe), which is why the comparison is against the
long-only book on the same perps, not against the spot paper books.

## Changes to the sketch

- Pool 1,777, not 1,724.
- Judged at 10 bps instead of 15 / 41 bps; 20 bps stress.
- The dollar-neutral variant (V5) added because the owner asked for a
  market-neutral form next to the net-short ones; the two gated-BTC
  differences counted.
- flow_overlays' twin gate is replaced by the 20 bps gate: the universe is
  already the survivorship-free top N of each day.
