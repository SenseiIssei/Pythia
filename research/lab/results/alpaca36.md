# alpaca36 (W3)

Breakout and momentum on everything the Alpaca paper account trades, with the
memecoins as a separate sleeve. Pre-registered here before the study code
existed; nothing below the generated marker was known when this was written.

## Question

The engine now quotes every pair Alpaca lists (32 coins without stablecoins
and gold, `pythia-core` `coins.rs`), and crypto demo orders go to Alpaca. The
daily books today trade the 15 lab coins Alpaca lists and keep the rest in
cash (C16, `alpaca_universe.md`). Do breakout and momentum earn more when they
may choose among all 32, and does a small memecoin sleeve add anything, at
Alpaca's costs?

## Data

The sweep's survivorship-free daily panel of every Binance USDT pair
(`experiments/fam_common.py`). A coin is its current Binance ticker; renamed
coins are not bridged (POL is not MATIC, RENDER is not RNDR, SKY is not MKR).
Coins without Binance USDT history (expected: HYPE, ONDO, SKY) cannot be
tested and are named in the coverage table. A coin with less than 365
eligible days before 2024-01-01 is marked "short history": it can be chosen
out of sample as soon as the panel's eligibility rule allows (60 days old,
1 M USD a day), but it shaped no in-sample choice. In sample 2020-08-01 to
2023-12-31, out of sample from 2024-01-01, as in every family study.

## Universes

- A15: the 15 lab coins Alpaca lists (`universe.ALPACA15`), today's live set
- A32: every non-stable coin Alpaca lists (`universe.ALPACA`)
- CORE: A32 without the six memecoins (26 coins)
- MEMES: BONK, SHIB, WIF, PEPE, TRUMP, DOGE

## Books

Reference, not counted (C16 already did): R15, the three paper books
(`breakout_top10`, `tsmom_top20`, `tsmom_tranches`) exactly as defined, with
every coin outside A15 held as cash.

Counted (21 trials, all long-only, all through the paper books' own weight
functions and simulators):

1. C32 (3): the three books exactly as defined, every coin outside A32 in
   cash. What switching the engine to the extended universe does alone.
2. X (8): the rules choosing only among CORE, the top K by 28-day volume each
   day, K 10 and 15: Donchian N 20 and 55 (exit N/2, slots K, no regime),
   tsmom 28d daily (regime), tsmom 28d in seven weekly tranches (regime).
3. M (3): the meme sleeve on its own, choosing among every eligible
   memecoin (slots 6): Donchian 20/10, Donchian 55/27, tsmom 28d (regime).
4. S (3): each family's X pick with the M pick as a sleeve: 90 % of capital
   in the core book, 10 % in the meme sleeve (the sleeve's risk budget, not
   tuned), mixed daily at the return level. The sleeves' rebalancing back to
   90/10 is not charged; at a 10 % sleeve it is small and it flatters S.
5. L (4): every pick (three X picks, the M pick) filled one day late.

Picks: per family the X variant with the best in-sample Sharpe at 35 bps;
for the sleeve the M variant with the best in-sample Sharpe at 35 bps.

## Costs

35 bps per unit of one-way turnover (Alpaca taker 25 bps plus half-spread and
slippage), the judging cost. Also 15 bps (maker) and 70 bps (stress).

## Pass rule (fixed before any number was seen)

A pick, or a pick plus sleeve, passes if, against the R15 book of the same
family, out of sample at 35 bps:

1. its Sharpe is higher, and higher in at least 2 of the 3 years 2024, 2025,
   2026 (to date);
2. the stationary-bootstrap 90 % band of the Sharpe difference (same days,
   block 20) lies above 0;
3. its Sharpe at 70 bps is above 0;
4. its maximum drawdown is at most the reference's plus 5 percentage points;
5. filled one day late its Sharpe is above 0 (for S: both the core pick and
   the meme pick late);
6. for S only: the meme sleeve on its own has a Sharpe above 0.

Deflated Sharpe is computed over the pooled trials (prior pool 377 at a bar
of 2.43 from `alpaca_universe.md`, plus these 21) and reported. A pick that
passes 1 to 6 becomes a paper book (forward evidence) under the name
`a36_<family>` or `a36_<family>_memes`; with a deflated p at or below 0.95 it
carries the same "fails deflation, forward evidence only" label as the
existing paper books. Only a deflated p above 0.95 as well would make it
"confirmed", the lab's bar for anything beyond paper.

Nothing fails silently: if no pick passes, no book is added and the study
says which rule each one broke.

<!-- generated below by lab.experiments.alpaca36; edit above this line only -->
