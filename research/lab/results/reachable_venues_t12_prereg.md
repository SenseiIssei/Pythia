# T12: lead A on venues the owner can reach. Pre-registration

Registered 2026-10-28 and committed before any number below was computed (while scoping, one look at which inputs
exist: Hyperliquid's settled hourly funding for the 33 coins the lab records from 2023-05-12, Kraken Futures'
hourly funding and marks for the 31 coins it records from 2025-10-15, both venues' public instrument lists of
today, the 2026-10-07 xs_daily cache; Kraken's funding endpoint serves the same span, 2025-10-15 on, for every
symbol; no return, no Sharpe). Brief T12 of the training plan of 2026-10-28, on the review of 2026-10-27
(`results/review_2026-10-27.md`, sections 2 and 3), R5's registry (`metrics.trial_pool`,
`<data>/trials/registry.jsonl`) and R6's windows (`results/factory_lockbox_r6.md`). Code:
`lab.experiments.reachable_venues_t12` (written after this file). Results go to `results/reachable_venues_t12.md`.
Nothing here may change once a result exists. Paper only: no book, gate, engine setting, live path or wallet
changes. Nothing here is about accounts, keys or legal advice.

## Question

T6's lead A (the perps_neutral portfolio: M4 reg7n, funding carry F7, low-vol beta-neutral on PIT50, ERC monthly;
late at the costs of its era validation Sharpe 1.74, DSR 0.050) runs on Binance USD-M. How much of it is left on a
venue a retail customer living in Germany can reach, Kraken Futures or Hyperliquid, with that venue's coins, funding
and fees, over the same days?

## Which venue can be reached (as the venues state it)

The report lists, per venue, what the venue itself says about residents of Germany, each line marked UNVERIFIED
where the lab cannot check it: Binance USD-M (the training plan's premise: not open to German retail), Kraken
Futures (the instrument list names its EU platforms per contract and a `countriesBanned` field), Hyperliquid (a
decentralised venue; its terms name the restricted places). No account, key or legal opinion is involved.

## Data

- **Listings (point in time).** Hyperliquid: its public `meta` list (live and delisted perps) and each perp's
  first and last settled funding (`fundingHistory` from 2023-05-12); Kraken Futures: its public instrument list
  (`PF_` perpetuals, `openingDate`) and each symbol's first funding record. Taken once on 2026-10-28 into
  `lab/experiments/reachable_venues_t12_listings.json` (committed with the code). Kraken's list holds only today's
  contracts: one delisted between 2025-10 and 2026-06 is missing (a survivor bias, said in the report).
- **Funding.** Hyperliquid: the lab's recording (`<data>/free/hyperliquid/funding.parquet`) for its 33 coins, the
  rest fetched once from the same public endpoint for every perp Hyperliquid ever listed, to 2026-07-02. Kraken:
  the lab's recording (`<data>/kraken_futures/funding`) for its 31 coins, the rest fetched once (the endpoint's
  span, 2025-10-15 on). Both are hourly rates as a share of the price, positive when longs pay. The fetch is
  `python -m lab.experiments.reachable_venues_t12 --fetch <dir>` (public, no key) and its folder is an input of the
  run; the lab's collectors are not changed.
- **Prices and volumes.** Binance's, as in T6 (the spot entry prices one hour after the close for M4 and carry,
  the daily panel's closes for low vol; Binance's perp and spot volumes for the liquidity ranks and the cost
  tiers). Neither venue's price or volume history covers the windows on the data folder; the basis between a
  venue's perp and Binance is left out (said in the report). A coin a venue lists without Binance data (for
  example HYPE) cannot be held.

## Universe per venue and day (the tested part)

- A coin (its base: Hyperliquid's kPEPE is PEPE, Kraken's XBT is BTC) is **on a venue** on UTC day d when its
  first record there (Hyperliquid: the first settled funding; Kraken: the later of `openingDate` and the first
  funding record) falls before the start of day d, and (Hyperliquid's delisted perps) day d starts before the day
  of its last settled funding. A coin is never on a venue before its first record. Binance segments of a reused
  ticker (`~` in the name) are on no venue but Binance.
- Each leg keeps its own rule inside that set: M4 and carry the 100 most liquid by Binance perp volume among the
  coins with a score; low vol T5's PIT rule (the 50 highest 30-day median dollar volumes) among the coins on the
  venue that day, both legs held on the venue's perp.
- The decision at the close of day d uses the universe of day d; the fill is at the next close (one close late,
  T6), so a coin first listed during day d can be traded at the earliest at the close of d + 1.

## The legs and the book on a venue (everything else as T6)

- **M4 reg7n**: T6's cached scores (trained on Binance's labels; not refit) restricted to the venue's coins,
  `xs_daily.book_buffer` 10/10 of 100 liquid, buffer 50 %, late.
- **Carry F7**: the score is minus the venue's own funding summed over the 7 days known at the close (its hourly
  settlements in each UTC day), restricted to the venue's coins, `xs_daily.book` 10/10 of 100, 3-day tranches, late.
- **Low vol**: `fam_lowvol.weights` (vol 60d, beta-neutral BAB) on the venue's PIT50, `t5.run_rule`, late.
- **Funding paid**: the venue's hourly settlements, summed over the same holding windows as T6's Binance funding
  (M4 and carry: 01:00 of d + 1 to 01:00 of d + 2; low vol: the UTC day).
- **Costs per unit of one-way turnover**: the venue's base-tier taker fee of its era plus T5's half-spread tier of
  the coin's volume that day, one tier wider than Binance's (thinner books, assumed, not measured). Hyperliquid
  2.5 bps to 2023-12-31, 3.5 bps to 2025-04-30, 4.5 bps after (T11's); Kraken Futures 5 bps (its public schedule,
  UNVERIFIED for the window). Binance as T6 (5 bps plus the tiers; T4's depth where its files exist, none in the
  windows). Book reweights 10 bps (T6).
- **ERC** monthly on the trailing 90 days of the venue's three legs. Before a venue has 60 days of its own legs,
  the trailing window uses Binance's legs for the days before the venue's start (the weights are a risk estimate;
  Binance's same rules are the best proxy known then). Returns are always the venue's.

## Windows (R6)

- **Hyperliquid**: in sample from the first day all three of its legs have a return (Hyperliquid starts
  2023-05-12) to 2023-12-31; validation 2024-01-01 to 2026-06-30.
- **Kraken Futures**: its funding starts 2025-10-15, so it has no in sample. The overlap from the first day all
  three of its legs have a return to 2026-06-30, inside validation, is the only window; the report says so on every
  Kraken number.
- **Binance**: T6's late era-cost series, rebuilt here with T6's own functions (the check: its ERC validation
  Sharpe must reproduce 1.74), cut to each venue's days.
- Every input is cut at 2026-06-30 24:00 before anything is computed; the lockbox (2026-07-01 on) is not read.

## Trials (17, R5's registry, hand family)

- Hyperliquid: M4, carry, low vol, EW, IV, ERC on the venue (6), and two steps of ERC's decomposition (2): the
  venue's universe with Binance's funding and costs, then plus the venue's funding (the third step, plus its costs,
  is the full ERC). Registered with their in-sample Sharpe before any validation number is computed
  (`hand:t12:hyperliquid:<name>`).
- Kraken Futures: the same 8, counted only (no in sample, so no Sharpe in the registry; `hand:t12:kraken:<name>`).
- Binance: T6's ERC over Kraken's overlap, counted only (`hand:t12:binance:erc_kraken_days`); over Hyperliquid's
  validation it is T6's registered `hand:t6:a:ERC` on the same days, no new trial.

## What is judged (ERC, each venue against Binance on the same days)

- **Kept share**: the venue's Sharpe divided by Binance's, and the difference with the stationary bootstrap's
  90 % band on the same resampled days (`director_common.boot_band`).
- **The lead survives on a venue** when all hold over its judged window (Hyperliquid validation, Kraken overlap):
  Sharpe 1.0 or more, at least half of Binance's on the same days, the bootstrap's 5 % above 0, correlation with
  BTC within +-0.3, and (Hyperliquid) positive in 2 of 2024, 2025, 2026. **Partly** when the Sharpe is above 0.5
  and the 5 % above 0 but another condition fails; **no** otherwise. On Kraken the window is about eight months:
  a survive there is a short record, not a validation.
- DSR over R5's pool of all and of the hand family (higher is better, 0.95 to pass) is reported for each venue's
  ERC; T6's lead already fails it on Binance, so no venue can pass validation here and no lockbox look follows.
- What follows: survive on a venue means further work on lead A happens on that venue's universe and data (the
  paper book would need the venue's funding and coins); no on both means lead A is parked as not reachable.

## Reported, not judged

Per venue: the coins on it by month and the legs' eligible counts; the share of T6's Binance book (gross weight,
validation mean) in coins the venue does not list; every leg and combination in sample and in the judged window
(Sharpe, CAGR, drawdown); the decomposition's three steps; funding a year paid and received per leg; T1's leak
harness on the low-vol weight function on Hyperliquid's PIT50; the bar's needed Sharpe on this pool.

## What could fool us

- Binance's prices for a venue's perp: the basis and its moves are left out; on Hyperliquid in 2023 the books were
  thin and the basis wide.
- M4's scores are trained on Binance's labels with Binance's funding; on a venue whose funding differs the model is
  not refit (a refit would be its own study).
- Hyperliquid's list of today includes its delisted perps, Kraken's does not; a renamed coin (RNDR to RENDER, MATIC
  to POL) is matched by today's names only where the two venues share them.
- Fees assumed at the base tier; the venue's half spread assumed one tier wider than Binance's, not measured.
- Kraken's eight months fall in 2025-26, a weak period for carry on Binance (T6's years).
