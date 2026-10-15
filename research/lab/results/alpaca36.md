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

## Results (generated 2026-10-15, data to 2026-10-14)

**Verdict: nothing passes, no paper book is added.** a36_breakout: 1 higher Sharpe, 2 of 3 years; 2 band above 0; 4 drawdown within +5 pp. a36_breakout_memes: 1 higher Sharpe, 2 of 3 years; 2 band above 0; 4 drawdown within +5 pp. a36_tsmom: 2 band above 0; 4 drawdown within +5 pp. a36_tsmom_memes: 2 band above 0; 4 drawdown within +5 pp. a36_tranches: 2 band above 0; 4 drawdown within +5 pp. a36_tranches_memes: 2 band above 0; 4 drawdown within +5 pp. Picks: breakout Donchian 20/10 · CORE top 10; tsmom tsmom 28d · CORE top 10 · regime · daily; tranches tsmom 28d · CORE top 10 · regime · seven weekly tranches; sleeve tsmom 28d · memes · slots 6 · regime. Deflation pool 398 trials (prior 377, here 21); the best noise trial is expected at an annual Sharpe of about 2.38. Panel: 591 coin segments, out of sample 1018 days.

### Coverage of the 32 Alpaca coins

No Binance USDT history (cannot be tested): HYPE. Short history (chosen out of sample only): ARB, BONK, ONDO, PEPE, POL, RENDER, SKY, TRUMP, WIF. Eligible CORE coins on out-of-sample days: min 19, median 22, max 25; eligible memecoins: 3 / 6 / 6.

| coin | in_panel | first_bar | first_eligible | eligible_days_is | history |
|---|---|---|---|---|---|
| AAVE | yes | 2020-10-15 | 2020-12-14 | 1113 | long |
| ADA | yes | 2020-01-01 | 2020-03-01 | 1401 | long |
| ARB | yes | 2023-03-24 | 2023-05-23 | 223 | short |
| AVAX | yes | 2020-09-23 | 2020-11-22 | 1135 | long |
| BAT | yes | 2020-01-01 | 2020-03-01 | 1319 | long |
| BCH | yes | 2020-01-01 | 2020-03-01 | 1401 | long |
| BONK | yes | 2023-12-16 | 2024-02-14 | 0 | short |
| BTC | yes | 2020-01-01 | 2020-03-01 | 1401 | long |
| CRV | yes | 2020-08-15 | 2020-10-14 | 1174 | long |
| DOGE | yes | 2020-01-01 | 2020-03-01 | 1275 | long |
| DOT | yes | 2020-08-19 | 2020-10-18 | 1170 | long |
| ETH | yes | 2020-01-01 | 2020-03-01 | 1401 | long |
| FIL | yes | 2020-10-16 | 2020-12-15 | 1112 | long |
| GRT | yes | 2020-12-18 | 2021-02-16 | 1049 | long |
| HYPE | no | - | - | 0 | none |
| LDO | yes | 2022-05-10 | 2022-07-09 | 541 | long |
| LINK | yes | 2020-01-01 | 2020-03-01 | 1401 | long |
| LTC | yes | 2020-01-01 | 2020-03-01 | 1401 | long |
| ONDO | yes | 2025-04-12 | 2025-06-11 | 0 | short |
| PEPE | yes | 2023-05-06 | 2023-07-05 | 180 | short |
| POL | yes | 2024-09-14 | 2024-11-13 | 0 | short |
| RENDER | yes | 2024-07-27 | 2024-09-25 | 0 | short |
| SHIB | yes | 2021-05-11 | 2021-07-10 | 905 | long |
| SKY | yes | 2025-09-18 | 2025-11-17 | 0 | short |
| SOL | yes | 2020-08-12 | 2020-10-11 | 1177 | long |
| SUSHI | yes | 2020-09-02 | 2020-11-01 | 1156 | long |
| TRUMP | yes | 2025-01-20 | 2025-03-21 | 0 | short |
| UNI | yes | 2020-09-17 | 2020-11-16 | 1141 | long |
| WIF | yes | 2024-03-06 | 2024-05-05 | 0 | short |
| XRP | yes | 2020-01-01 | 2020-03-01 | 1401 | long |
| XTZ | yes | 2020-01-01 | 2020-03-01 | 1392 | long |
| YFI | yes | 2020-08-11 | 2020-10-10 | 1171 | long |

### Each candidate against its R15 reference (out of sample, 35 bps)

`sr_diff_*` is the stationary-bootstrap 90 % band of the Sharpe difference on the same days; `better_years` counts 2024 to 2026 with a higher Sharpe; `failed` names the broken rules.

| book | candidate | oos_35 | ref_oos_35 | better_years | sr_diff_p05 | sr_diff_p95 | oos_70 | dd | ref_dd | late_oos_35 | meme_oos_35 | deflated_p | failed | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| a36_breakout | Donchian 20/10 · CORE top 10 | 0.71 | 1.17 | 0 | -0.91 | -0.06 | 0.56 | 0.31 | 0.16 | 0.44 | None | 0.00 | 1 higher Sharpe, 2 of 3 years; 2 band above 0; 4 drawdown within +5 pp | fails the pass rule, no book |
| a36_breakout_memes | 90 % Donchian 20/10 · CORE top 10 + 10 % tsmom 28d · memes · slots 6 · regime | 0.74 | 1.17 | 0 | -0.88 | -0.05 | 0.58 | 0.30 | 0.16 | 0.48 | 0.68 | 0.00 | 1 higher Sharpe, 2 of 3 years; 2 band above 0; 4 drawdown within +5 pp | fails the pass rule, no book |
| a36_tsmom | tsmom 28d · CORE top 10 · regime · daily | 0.64 | 0.54 | 2 | -0.34 | 0.47 | 0.36 | 0.26 | 0.09 | 0.38 | None | 0.00 | 2 band above 0; 4 drawdown within +5 pp | fails the pass rule, no book |
| a36_tsmom_memes | 90 % tsmom 28d · CORE top 10 · regime · daily + 10 % tsmom 28d · memes · slots 6 · regime | 0.66 | 0.54 | 2 | -0.30 | 0.45 | 0.39 | 0.24 | 0.09 | 0.43 | 0.68 | 0.00 | 2 band above 0; 4 drawdown within +5 pp | fails the pass rule, no book |
| a36_tranches | tsmom 28d · CORE top 10 · regime · seven weekly tranches | 0.72 | 0.65 | 2 | -0.33 | 0.43 | 0.63 | 0.24 | 0.09 | 0.67 | None | 0.00 | 2 band above 0; 4 drawdown within +5 pp | fails the pass rule, no book |
| a36_tranches_memes | 90 % tsmom 28d · CORE top 10 · regime · seven weekly tranches + 10 % tsmom 28d · memes · slots 6 · regime | 0.75 | 0.65 | 2 | -0.26 | 0.41 | 0.64 | 0.23 | 0.09 | 0.69 | 0.68 | 0.00 | 2 band above 0; 4 drawdown within +5 pp | fails the pass rule, no book |

### Every run (in sample 2020-08 to 2023, out of sample from 2024)

R15 reference (not counted), C32 cash-left on the 32, X CORE only, M meme sleeve alone, S 90/10 core plus sleeve, L one day late. Sharpe at 15 / 35 / 70 bps; CAGR, drawdown and the bootstrap band at 35 bps; deflated p over the whole pool.

| group | book | variant | counted | is_taker 35bps | oos_maker 15bps | oos_taker 35bps | oos_stress 70bps | cagr_35 | dd_35 | expo | turnover_yr | trades_month | coins_held | deflated_p | boot35_p05 | boot35_p95 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| R15 | breakout | breakout_top10 · outside A15 in cash | no | 1.45 | 1.24 | 1.17 | 1.04 | 0.18 | 0.16 | 0.15 | 5.74 | 7.71 | 2.08 | 0.02 | -0.11 | 2.29 |
| R15 | tsmom_daily | tsmom_top20 · outside A15 in cash | no | 1.68 | 0.68 | 0.54 | 0.29 | 0.04 | 0.09 | 0.09 | 6.17 | 15.93 | 3.35 | 0.00 | -0.64 | 1.62 |
| R15 | tsmom_tranches | tsmom_tranches · outside A15 in cash | no | 1.85 | 0.70 | 0.65 | 0.56 | 0.06 | 0.09 | 0.09 | 2.39 | 7.71 | 4.39 | 0.00 | -0.53 | 1.80 |
| C32 | breakout | breakout_top10 · outside A32 in cash | yes | 1.41 | 1.19 | 1.12 | 0.99 | 0.19 | 0.16 | 0.15 | 6.04 | 8.49 | 2.28 | 0.02 | -0.21 | 2.23 |
| C32 | tsmom_daily | tsmom_top20 · outside A32 in cash | yes | 1.67 | 0.59 | 0.45 | 0.20 | 0.04 | 0.11 | 0.10 | 7.11 | 19.81 | 4.03 | 0.00 | -0.75 | 1.53 |
| C32 | tsmom_tranches | tsmom_tranches · outside A32 in cash | yes | 1.87 | 0.53 | 0.48 | 0.39 | 0.05 | 0.11 | 0.10 | 2.76 | 9.83 | 5.34 | 0.00 | -0.67 | 1.56 |
| X | breakout | Donchian 20/10 · CORE top 10 | yes | 1.28 | 0.80 | 0.71 | 0.56 | 0.14 | 0.31 | 0.22 | 9.47 | 13.45 | 3.34 | 0.00 | -0.72 | 1.88 |
| X | breakout | Donchian 20/10 · CORE top 15 | yes | 1.23 | 0.68 | 0.60 | 0.45 | 0.11 | 0.30 | 0.21 | 9.11 | 20.11 | 4.98 | 0.00 | -0.73 | 1.71 |
| X | breakout | Donchian 55/27 · CORE top 10 | yes | 1.21 | 0.33 | 0.30 | 0.25 | 0.05 | 0.33 | 0.25 | 3.73 | 5.20 | 3.83 | 0.00 | -0.85 | 1.35 |
| X | breakout | Donchian 55/27 · CORE top 15 | yes | 1.15 | 0.27 | 0.24 | 0.20 | 0.03 | 0.33 | 0.23 | 3.40 | 7.23 | 5.33 | 0.00 | -0.80 | 1.20 |
| X | tsmom_daily | tsmom 28d · CORE top 10 · regime · daily | yes | 1.50 | 0.79 | 0.64 | 0.36 | 0.10 | 0.26 | 0.19 | 14.22 | 18.41 | 3.56 | 0.00 | -0.65 | 1.74 |
| X | tsmom_tranches | tsmom 28d · CORE top 10 · regime · seven weekly tranches | yes | 1.74 | 0.78 | 0.72 | 0.63 | 0.13 | 0.24 | 0.20 | 5.35 | 9.02 | 4.76 | 0.00 | -0.45 | 1.80 |
| X | tsmom_daily | tsmom 28d · CORE top 15 · regime · daily | yes | 1.40 | 0.71 | 0.56 | 0.29 | 0.09 | 0.23 | 0.17 | 13.54 | 26.89 | 5.10 | 0.00 | -0.65 | 1.62 |
| X | tsmom_tranches | tsmom 28d · CORE top 15 · regime · seven weekly tranches | yes | 1.64 | 0.78 | 0.73 | 0.64 | 0.13 | 0.22 | 0.18 | 4.96 | 12.31 | 6.86 | 0.00 | -0.41 | 1.76 |
| M | memes | Donchian 20/10 · memes · slots 6 | yes | 0.71 | 0.97 | 0.94 | 0.87 | 0.26 | 0.27 | 0.14 | 5.35 | 5.86 | 1.60 | 0.00 | -0.39 | 1.89 |
| M | memes | Donchian 55/27 · memes · slots 6 | yes | 1.17 | 0.55 | 0.54 | 0.51 | 0.12 | 0.32 | 0.14 | 2.05 | 2.15 | 1.43 | 0.00 | -0.66 | 1.44 |
| M | memes | tsmom 28d · memes · slots 6 · regime | yes | 1.67 | 0.78 | 0.68 | 0.52 | 0.11 | 0.18 | 0.10 | 8.32 | 8.43 | 1.57 | 0.00 | -0.61 | 1.81 |
| S | breakout | 90 % Donchian 20/10 · CORE top 10 + 10 % tsmom 28d · memes · slots 6 · regime | yes | 1.33 | 0.83 | 0.74 | 0.58 | 0.14 | 0.30 | 0.20 | 9.36 | 21.87 | 4.92 | 0.00 | -0.64 | 1.93 |
| S | tsmom_daily | 90 % tsmom 28d · CORE top 10 · regime · daily + 10 % tsmom 28d · memes · slots 6 · regime | yes | 1.56 | 0.81 | 0.66 | 0.39 | 0.11 | 0.24 | 0.18 | 13.63 | 26.83 | 5.13 | 0.00 | -0.54 | 1.81 |
| S | tsmom_tranches | 90 % tsmom 28d · CORE top 10 · regime · seven weekly tranches + 10 % tsmom 28d · memes · slots 6 · regime | yes | 1.79 | 0.81 | 0.75 | 0.64 | 0.13 | 0.23 | 0.19 | 5.64 | 17.45 | 6.34 | 0.00 | -0.41 | 1.83 |
| L | breakout | Donchian 20/10 · CORE top 10 · one day late | yes | 1.20 | 0.53 | 0.44 | 0.29 | 0.07 | 0.34 | 0.21 | 9.46 | 13.45 | 3.35 | 0.00 | -0.96 | 1.55 |
| L | tsmom_daily | tsmom 28d · CORE top 10 · regime · daily · one day late | yes | 1.63 | 0.54 | 0.38 | 0.11 | 0.05 | 0.27 | 0.19 | 14.27 | 18.41 | 3.56 | 0.00 | -0.79 | 1.44 |
| L | tsmom_tranches | tsmom 28d · CORE top 10 · regime · seven weekly tranches · one day late | yes | 1.71 | 0.72 | 0.67 | 0.57 | 0.12 | 0.24 | 0.20 | 5.35 | 9.02 | 4.76 | 0.00 | -0.49 | 1.74 |
| L | memes | tsmom 28d · memes · slots 6 · regime · one day late | yes | 1.53 | 0.82 | 0.73 | 0.57 | 0.12 | 0.17 | 0.10 | 8.40 | 8.40 | 1.57 | 0.00 | -0.56 | 1.86 |

### Per year (Sharpe at 35 bps)

| group | book | variant | y2021 | y2022 | y2023 | y2024 | y2025 | y2026 |
|---|---|---|---|---|---|---|---|---|
| R15 | breakout | breakout_top10 · outside A15 in cash | 2.38 | -0.61 | 1.93 | 2.19 | 0.32 | -0.02 |
| R15 | tsmom_daily | tsmom_top20 · outside A15 in cash | 1.99 | 0.00 | 1.68 | 1.56 | -0.35 | 0.49 |
| R15 | tsmom_tranches | tsmom_tranches · outside A15 in cash | 2.51 | 0.84 | 1.52 | 1.67 | -0.08 | 0.25 |
| C32 | breakout | breakout_top10 · outside A32 in cash | 2.41 | -0.77 | 1.86 | 2.07 | 0.28 | -0.02 |
| C32 | tsmom_daily | tsmom_top20 · outside A32 in cash | 2.18 | 0.00 | 1.51 | 1.26 | -0.33 | 0.43 |
| C32 | tsmom_tranches | tsmom_tranches · outside A32 in cash | 2.69 | 0.84 | 1.45 | 1.26 | -0.11 | 0.18 |
| X | breakout | Donchian 20/10 · CORE top 10 | 2.27 | -1.20 | 1.78 | 1.66 | -0.22 | -0.16 |
| X | breakout | Donchian 20/10 · CORE top 15 | 2.36 | -1.14 | 1.54 | 1.53 | -0.19 | -0.40 |
| X | breakout | Donchian 55/27 · CORE top 10 | 1.75 | -2.16 | 1.74 | 0.62 | -0.27 | 0.39 |
| X | breakout | Donchian 55/27 · CORE top 15 | 1.71 | -2.17 | 1.67 | 0.57 | -0.41 | 0.32 |
| X | tsmom_daily | tsmom 28d · CORE top 10 · regime · daily | 1.66 | 0.00 | 1.67 | 0.87 | -0.07 | 1.24 |
| X | tsmom_tranches | tsmom 28d · CORE top 10 · regime · seven weekly tranches | 2.08 | 0.84 | 1.77 | 1.09 | 0.20 | 0.96 |
| X | tsmom_daily | tsmom 28d · CORE top 15 · regime · daily | 1.59 | 0.00 | 1.57 | 0.90 | -0.31 | 1.21 |
| X | tsmom_tranches | tsmom 28d · CORE top 15 · regime · seven weekly tranches | 2.10 | 0.81 | 1.59 | 1.14 | 0.06 | 1.05 |
| M | memes | Donchian 20/10 · memes · slots 6 | 1.39 | -0.33 | 0.33 | 2.08 | 0.14 | -0.77 |
| M | memes | Donchian 55/27 · memes · slots 6 | 2.12 | -0.39 | 0.66 | 1.38 | -0.59 | -0.32 |
| M | memes | tsmom 28d · memes · slots 6 · regime | 2.43 | 0.00 | 1.55 | 1.79 | -0.31 | 0.34 |
| S | breakout | 90 % Donchian 20/10 · CORE top 10 + 10 % tsmom 28d · memes · slots 6 · regime | 2.37 | -1.20 | 1.81 | 1.73 | -0.24 | -0.12 |
| S | tsmom_daily | 90 % tsmom 28d · CORE top 10 · regime · daily + 10 % tsmom 28d · memes · slots 6 · regime | 1.79 | 0.00 | 1.69 | 1.00 | -0.10 | 1.16 |
| S | tsmom_tranches | 90 % tsmom 28d · CORE top 10 · regime · seven weekly tranches + 10 % tsmom 28d · memes · slots 6 · regime | 2.20 | 0.84 | 1.79 | 1.20 | 0.16 | 0.91 |
| L | breakout | Donchian 20/10 · CORE top 10 · one day late | 2.14 | -1.31 | 2.13 | 1.46 | -0.73 | -0.52 |
| L | tsmom_daily | tsmom 28d · CORE top 10 · regime · daily · one day late | 1.91 | 0.00 | 1.60 | 0.62 | -0.20 | 0.90 |
| L | tsmom_tranches | tsmom 28d · CORE top 10 · regime · seven weekly tranches · one day late | 2.13 | 0.52 | 1.64 | 1.06 | 0.14 | 0.85 |
| L | memes | tsmom 28d · memes · slots 6 · regime · one day late | 2.44 | 0.00 | 1.16 | 1.67 | -0.19 | 0.43 |

### Deflation

Prior: 377 trials, variance backed out of the published bar (2.43 over 377); here 21 trials at 35 bps. Pooled bar 2.38 over 398.
