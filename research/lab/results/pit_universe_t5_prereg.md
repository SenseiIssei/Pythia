# T5: a point-in-time universe. Pre-registration

Registered 2026-10-28 and committed before any number below was computed (while scoping, one look at the
daily panel's size, its first and last day and its most traded symbols, to check that delisted segments such as
LUNAUSDT~0 and FTTUSDT~0 are in it and stablecoins are not; no performance number). Brief T5 of the training plan
of 2026-10-28, on the review of 2026-10-27 (`results/review_2026-10-27.md`, sections 2 and 3), R5's trial registry
and R6's windows. Code: `lab.universe.pit` and `lab.experiments.pit_universe_t5` (written after this file).
Results go to `results/pit_universe_t5.md`. Nothing here may change once a result exists.

## Question

Every crypto result of the lab is quoted either on today's 20 coins (`data.UNIVERSE`, which survived to 2026) or on
rankings that some studies took from today's lists. How much of each main rule's Sharpe and CAGR is the survivorship
of those 20, measured against a universe that is chosen each day from what traded then?

## The universe

`lab.universe.pit(P, n)`: for each UTC day t, the n coins with the highest 30-day median dollar volume on Binance
spot, decided at the close of day t.
- **Source.** The lab's own daily bars: the sweep's daily panel (`fam_common.load_panel`, one row per day and segment
  from the hourly klines of every USDT pair in `hist/universe.json`, delisted ones included; a reused ticker's older
  asset is its own segment, e.g. LUNAUSDT~0). Dollar volume is the day's quote volume in USDT.
- **The median.** Over the coin's bars among days t-29 to t, at least 20 bars; a day without a bar is not counted.
- **Membership needs a bar on day t.** A coin is never in the universe before its first or after its last bar
  (tested).
- **Excluded.** Stablecoins and pegged dollars or euros, gold, and wrapped or staked duplicates (fam_common's
  EXCLUDE, the universe module's NOT_TRADED, and USDC, BUSD, TUSD, USDP, PAX, FDUSD, DAI, UST, USTC, AEUR, EURI,
  EUR, GBP, AUD, WBTC, WBETH, BETH, BNSOL, STETH by base). Tokenised stocks are not in the panel.
- **Delistings.** With T4's delisting table present (`book_depth.read_delistings`), a coin leaves the universe from
  the UTC day its spot or perp delisting was announced (`universe.delisting_days`). Without the table nothing is
  dropped and the report says so.
- N = 20 (`PIT20`) and N = 50 (`PIT50`). Ties go to the panel's column order.

Against it: **today's 20** (`LAB20`, the current Binance segment of each of `data.UNIVERSE`, on every day it trades).

Each rule runs on the panel with its eligibility (alive, a bar today, 60 days old, 1 M USD a day of 28-day mean
volume) intersected with the universe of that day. Nothing else of the rule changes.

## The rules (nothing new, nothing tuned)

1. **tsmom**: tsmom.py's pick, 28-day momentum, daily, 40 % vol per coin: every coin of the universe with 120 days
   of history held when its 28-day return is positive, at 0.40 / (its 30-day vol, annual) / (coins counted), the
   sum capped at 1. No regime.
2. **tsmom1**: S1's pick, `fam_volmom.base_weights` on the 1 most liquid coin of the universe, BTC 200-day regime.
3. **breakout_top10**: Donchian 20/10 on the 10 most liquid coins of the universe, 10 slots, 40 % vol, no regime
   (`fam_breakout.breakout_weights` as `smallaccount.candidate` runs it).
4. **donchian_100_50**: F2's survivor 07493e8a8adb (Donchian 100/50, the asset above its 100-day average, the best 1
   by 90-day return, full, scaled down to 20 % vol, weekly on S1's anchor) on the universe's coins instead of F2's
   six assets, USD closes, F2's 60-day vol. The six-asset original cannot be point in time, so this measures the
   rule, not the genome.
5. **lowvol**: perps_neutral's low-vol leg, `fam_lowvol.weights(vol 60d, beta-neutral BAB)` on the whole universe
   (its quintiles), weekly, both legs on perps (`trend_shorts.sim`'s rules: a position only where the perp traded
   that day, longs pay and shorts receive funding).
6. **carry**: perps_neutral's carry leg, funding carry's F7: long the k coins with the lowest 7-day funding sum and
   short the k highest, among the universe's coins whose perp traded that day, 0.5 gross a side, k a tenth of the
   universe (2 on 20 coins, 5 on 50; the original is 10 of the 100 most liquid perps), three 3-day tranches held
   as sleeves of a third each, both legs on perps.

## Fills and costs

- **Late fill.** Every rule filled one close late: the targets known at close t are traded at close t+1 (weights and
  rebalance days shift by one day). There is no on-time run.
- **Costs of their era**, per unit of one-way turnover in a coin, from the coin's own 30-day median dollar volume on
  the day of the trade: the taker fee (Binance spot 10 bps for a spot long, USD-M 5 bps for a perp position) plus a
  half spread of 1 bp at 1 B USD a day or more, 3 bps from 100 M, 10 bps from 10 M, 25 bps from 1 M, 50 bps below
  (assumed tiers). A dying coin is charged the half spread of its own volume at that time, not today's. A position
  closed because its series ended pays its last day's cost.

## Windows

In sample 2020-08-01 to 2023-12-31, validation 2024-01-01 to 2026-06-30 (R6). The panel is cut at 2026-06-30 before
anything is computed; the lockbox from 2026-07-01 is never read.

## Trials

Six rules on three universes: 18 trials, each a line of R5's registry (`hand:t5_pit:<rule>:<universe>`, family hand,
its in-sample Sharpe), registered before the validation numbers are computed. DSR (higher is better, pass at 0.95 or
more) of each validation series over the registry's pool of all, the factory ledgers counted once by id.

## Reported

`results/pit_universe_t5.md`: per rule and universe the Sharpe, CAGR and drawdown in sample and in validation; the
gap LAB20 minus PIT20 and LAB20 minus PIT50 in Sharpe and CAGR in both windows (positive: today's 20 flatter the
rule, the survivorship premium); the 90 % stationary bootstrap band of the validation Sharpe gap LAB20 minus PIT20
(`director_common.boot_band`); the DSR. About the universe: coins ever in PIT20 and PIT50, the share of PIT20's
coin-days that are LAB20 coins, the coins in PIT20 that are delisted today, and whether the delisting table was
present.

**Reading.** A rule's survivorship premium is material when its validation Sharpe gap LAB20 minus PIT20 is above
0.20 and the band's lower end is above 0. A rule with a material premium gets a note in the README that its
published numbers on today's coins are flattered by about that much. No rule passes or fails here, nothing reaches a
paper book, the engine or a wallet.
