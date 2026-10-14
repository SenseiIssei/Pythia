# C16: what the books earn on the coins Alpaca lists

`python -m lab.experiments.alpaca_universe`

## Pre-registration (written and committed before the first run)

**Question.** The money trades on the Alpaca paper account, which lists 15 of
the lab's coins: BTC ETH SOL XRP DOGE ADA AVAX LINK LTC DOT BCH UNI AAVE PEPE
FIL. The three daily books (breakout_top10, tsmom_top20, tsmom_tranches) pick
from every coin Binance lists, so part of what they pick (NEAR, SUI, TRX, new
listings) cannot be bought there and the autopilot leaves that share in cash.
What do the books really earn that way, and does the same rule choosing only
among the 15 Alpaca coins do better? If nothing passes the lab bar, the
numbers are written up and no paper book is added.

**Data.** The sweep's survivorship-free daily panel (`fam_common.load_panel`:
every USDT spot pair Binance ever listed, delisted ones included, reused
tickers split into segments), rebuilt from the data.binance.vision 1h archives
to 2026-09-30, plus the USD-M archives the panel loader reads (only short legs
use them; every book here is long-only spot). Day t's close is the last hourly
close of the UTC day; a weight decided at the close of day t earns day t+1.

**The Alpaca coins.** A panel column is an Alpaca coin when its base is one of
the 15 and it is the current segment of its ticker (no `~` segment: a dead
earlier asset under a reused name cannot be bought today). Reported: for each
of the 15, the first day it is eligible (alive, traded, 60 days old, 1 M USD a
day), and how many were eligible at 2020-08-01, 2024-01-01 and on every day of
the test window.

**Books and variants.** All long-only, the paper books' own weight functions
(fam_breakout.breakout_weights, fam_volmom.base_weights, tsmom_tranches.simulate).

| group | what | variants |
|---|---|---|
| O, original (reference, already in the pool) | breakout_top10 (Donchian 20/10, top 10 by 28-day volume of each day among all eligible coins, no regime), tsmom_top20 daily (28d, top 20, BTC 200-day regime, 40 % vol per coin over the slots), tsmom_tranches (tsmom_top20's targets, seven weekly tranches, band 50 %) | 3, not counted again |
| C, cash-left | the original targets with every non-Alpaca column set to 0 and the rest unchanged (not rescaled): what the autopilot does today | 3 |
| R, restricted | the same rules choosing only among the Alpaca coins: each day the top K Alpaca coins by 28-day volume among the eligible ones, K in {5, 8, 10, 15}. Breakout: Donchian N/(N/2) with N in {20, 55, 100} (the sweep's grid), K slots, no regime, entry only while in the top K, exit on its own signal. tsmom daily and tsmom tranches: 28d, regime, 40 % vol per coin over the day's universe count, as the originals | 12 + 4 + 4 = 20 |
| T, survivorship-free twin of every R | the Alpaca list is today's list, chosen with hindsight. The twin replaces it with a list chosen point in time: at the first close of each calendar year (and at the panel's first eligible day), the 15 eligible coins with the highest 28-day volume, frozen for that year (a coin that dies leaves it; nothing is added during the year). The same R rule then picks the top K by volume among that year's list | 20 |
| L, one day late | each book's pick (below) with its targets filled one close later (W[t] decided at t is executed at t+1) | 3 |
| benchmarks (not counted) | BTC buy and hold; equal-weight buy and hold of the eligible Alpaca coins, rebalanced daily, no costs | |

**Counted trials.** 3 + 20 + 20 + 3 = **46 here; the pool is 331 + 46 = 377.**
The prior's variance is backed out of the published bar (2.55 over 331,
`results/regime_hmm.md`) and pooled with the variance of this study's 46
trial Sharpes (annual, clipped at +-3), as in regime_hmm.

**Split and costs.** In sample 2020-08-01 to 2023-12-31, out of sample
2024-01-01 to 2026-09-30. Costs per unit of one-way turnover: **35 bps (Alpaca
taker 25 bps plus about 10 bps slippage), the base**; 15 bps (Alpaca maker,
optimistic); 70 bps (stress). Sharpe annualised with 365 days.

**Picks.** Per book (breakout, tsmom daily, tsmom tranches) the R variant
with the best in-sample Sharpe at 35 bps.

**Reported** for every O, C, R, T, L row and the benchmarks: Sharpe at 15 /
35 / 70 bps in and out of sample, CAGR and maximum drawdown at 35 bps,
average exposure, turnover per year, trades per month (a trade is a coin's
weight going from 0 to above 0 or back, out of sample) and orders per month
(any coin-level weight change of more than 0.1 % of the book), Sharpe per year
2021 to 2026 at 35 bps, deflated p over 377 trials (at 35 bps), and the
stationary-bootstrap 90 % band (block 20 days) of the out-of-sample Sharpe at
35 bps. For O: the share of exposure out of sample in non-Alpaca coins and the
coins that carry it. For each pick: the difference series pick minus C (same
book, daily net at 35 bps), its Sharpe and bootstrap band, and the Sharpe
difference per out-of-sample year.

**Pass rule** for adding a pick as a paper book (all must hold):

1. The lab bar: out-of-sample Sharpe above 0 at 35 bps and at 70 bps, maximum
   drawdown at 35 bps below BTC buy and hold's, and deflated p above 0.95
   over all 377 trials.
2. It beats the cash-left version of the same book: higher out-of-sample
   Sharpe at 35 bps, and higher in at least 2 of the 3 out-of-sample years
   (2026 partial).
3. Its survivorship-free twin (T) and its one-day-late fill (L) have an
   out-of-sample Sharpe above 0 at 35 bps.

If a pick passes: a paper book in lab/paper/families.py (autopilot_only, its
evidence() with the survivorship-free twin's numbers and the caveat that the
list is today's, the forward report band, a health check entry) with tests.
Otherwise this file carries the numbers and nothing is added.

<!-- generated below by lab.experiments.alpaca_universe; edit above this line only -->
