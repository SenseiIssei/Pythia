# S1: the lab's strategies with 50, 100 and 500 EUR. Pre-registration

Registered 2026-10-23 and committed before any number below was computed. Code:
`lab.experiments.smallaccount` (written after this file). Results go to
`results/smallaccount_s1.md`. Nothing here may change once a result exists.

## Question

The lab judges its strategies at 15 and 41 bps per unit of turnover, as if any
order of any size could be filled. The owner has 50 to 100 EUR. At 50, 100 and
500 EUR, with what the venues really charge and the orders they refuse:

1. what does a trade cost on Kraken spot and on Jupiter (Solana), and what part
   of a rebalance is never traded because of the minimums;
2. what is left of each candidate's out-of-sample result, also with slower
   rebalancing and fewer coins;
3. what is worth running at 50 and 100 EUR, and what capital each candidate
   needs before costs and minimums stop dominating?

## Costs, from data recorded for this study

Everything in USD is converted to EUR at one rate, Kraken's EUR/USD mid of the
snapshot below, for the whole history (exchange rate moves are not modelled).

**Kraken spot, a new account.** Kraken Pro's lowest tier: taker 40 bps, maker
25 bps (config/costs.json; a new account trades far below the 10,000 USD of
monthly volume of the next tier, so the tier never changes). The orders go on
the coin's EUR pair. From one snapshot of Kraken's public API taken for this
study (`AssetPairs` and `Ticker`, written to `results/smallaccount_kraken_pairs.csv`):
per EUR pair `ordermin` (base units), `costmin` (EUR), `lot_decimals` and the
best bid and ask. Per order:

- the units are rounded down to `lot_decimals`;
- an order below the minimum, max(ordermin x today's snapshot price, costmin)
  in EUR, held fixed over the history (Kraken resets ordermin to keep it near a
  few dollars), is not sent;
- taker: fee 40 bps of the notional plus the half spread of the snapshot
  (ask minus bid over twice the mid); maker (sensitivity only): fee 25 bps, no
  spread, every order filled (optimistic);
- a coin without a Kraken EUR pair is held as cash.

**Jupiter on Solana.** A USDC wallet. A quote ladder recorded for this study
from Jupiter's public quote API (`lab.onchain.jupiter`, the client the
on-chain books use), USDC to the coin and straight back at 5, 10, 25, 50, 100,
250 and 500 USD, for every coin of `lab.onchain.mints`, written to
`results/smallaccount_jupiter_quotes.csv`; the 100 USD round trips the
on-chain paper book recorded in data/paper/onchain_breakout_top10_live/probes.csv
are printed next to it. Per swap:

- route cost: half the recorded round trip at that size (route fees, price
  impact, the pools' spread), interpolated in log size between the ladder's
  rungs, flat below 5 USD, growing with the square root of size above 500 USD;
- network fee: the base fee 5,000 lamports plus the on-chain book's priority
  fee 0.0001 SOL (`lab.onchain.paper`), at the day's SOL price from the panel;
- MIN_TRADE 5 USDC as in `lab.onchain.book`: a smaller change is not sent;
- the SOL reserve: 0.01 SOL for fees plus 0.00204 SOL of rent per token
  account the variant can hold (USDC and each coin slot), bought at the start
  and held idle (counted as cash that earns nothing, valued at the start);
- getting there once: EUR to USDC on Kraken at the taker fee (40 bps) plus an
  assumed 1 USDC to withdraw to Solana (not measured; Kraken's withdrawal fee
  needs a login);
- a coin without a mint in `lab.onchain.mints` is held as cash.

Costs measured today are applied to every past day. Coins Kraken or Jupiter do
not list today are cash in the past too (today's survivors for the venue; the
signals themselves keep the survivorship-free panel).

## Candidates (8, from the best existing out-of-sample evidence)

All long-only spot, the weight functions as the lab already runs them, on the
sweep's survivorship-free daily panel (`fam_common.load_panel`), cut at
**2026-10-21**:

| key | rule | evidence |
|---|---|---|
| btc_hold | BTC bought once and held (reference, never a pick) | sweep benchmark, 0.78 |
| btc_gated | BTC at full weight above its 200-day average, cash below | gated_btc, 0.79 / 0.71 at 15 / 41 bps |
| breakout_btceth | Donchian 55/27 on BTC and ETH, BTC regime | sweep pick, 1.07 / 1.03 |
| breakout_top10 | Donchian 20/10 on the 10 most liquid coins (the live twin's rule) | sweep pick, 1.20 / 1.08 |
| breakout_sol | the same rule among the coins with a Solana mint (onchain_breakout_sol) | paper only |
| tsmom_top20 | 28d momentum, 20 most liquid, regime, 40 % vol | sweep pick, 0.54 / 0.32 |
| trend_carry | the same, without coins crowded by funding | sweep pick, 0.71 / 0.37 |
| memes_rotation | the best of the six Alpaca memecoins by 28-day return, BTC gate | W7, 1.15 at 35 bps |

tsmom_tranches is tsmom_top20 rebalanced weekly in tranches; the weekly
variant of tsmom_top20 below stands for it. The market-neutral books (M2, M4,
the low-vol BAB) need shorts and are not candidates.

## Variants

- **Cadence:** daily, every 3 days, weekly (calendar days since 2020-01-01
  modulo 1, 3 or 7). On a rebalance day a coin whose target changed since the
  last rebalance is traded to its new target, every other coin is left to
  drift; between rebalance days nothing trades. Daily is the rule as the lab
  runs it.
- **Coins:** the candidates that choose among a universe also run on the 1, 3
  and 5 most liquid coins of that universe (slots = the number of coins):
  breakout_top10, breakout_sol, tsmom_top20 and trend_carry (1, 3, 5 and the
  original), breakout_btceth (BTC alone, and both). The single-coin rules run
  once.
- **Venue:** Kraken taker and Jupiter. Kraken maker is a sensitivity row for
  the two picks.
- **Capital:** 50, 100 and 500 EUR, and the ladder 25, 250, 1,000, 2,500 and
  10,000 EUR for the capital question.

Every variant and capital is reported; none is dropped.

## Simulation

Cash and coin units, in EUR, day by day. A target decided at the close of day
t is traded at that close (the panel's close, plus the costs above) and earns
day t+1, the lab's convention. Sales go first, then buys out of the cash they
freed; buys are scaled down when the cash is short. A trade below the minimum
is not sent. A sale that would leave less than the minimum sells the whole
position; a position below the minimum cannot be sold and stays as dust. A coin
whose series ends is sold at its last close (as the sweep does). The wallet
starts in cash at the first day of the window.

In sample 2020-08-01 to 2023-12-31, out of sample 2024-01-01 to 2026-10-21.

Per variant and capital, out of sample: annual return (CAGR), max drawdown,
Sharpe (daily, x sqrt 365), the costs paid in EUR and as a share of the return
before costs (costs / (profit + costs); "costs dominate" at 50 % or more), the
number of orders a year, the orders not sent for the minimum, and the same rule
at the sweep's 41 bps without minimums ("ideal") for comparison.

## Decisions, fixed now

- **Worth running at a capital:** out-of-sample CAGR above 0, Sharpe above
  btc_hold's at the same capital and venue, cost share below 50 %. Otherwise
  the answer is: nothing of it, or BTC bought and held.
- **Capital needed:** per candidate, at its best cadence and coin count by
  in-sample Sharpe at 10,000 EUR on Kraken taker: the smallest ladder capital
  from which, at it and every larger rung, the cost share is below 50 % and the
  out-of-sample CAGR is within 2 percentage points of the 10,000 EUR run's;
  "never" when no rung qualifies.
- **The two paper books:** book A is the variant (any candidate but btc_hold,
  any cadence, coins and venue) with the best **in-sample** Sharpe at 50 EUR;
  book B the best in-sample at 100 EUR among the other candidates. They run
  from the deploy with their own paper wallets of 50 and 100 EUR and the costs
  above (live Kraken EUR prices on Kraken, the cost model on Jupiter's), in the
  daily forward report (equity on the lab's 10,000 basis, as the on-chain books
  do) and in their own daily report in EUR. Picked in sample, judged out of
  sample: no number seen after 2023 picks them.
- Trials: 8 candidates; the grid is a description, not a search, and nothing
  here goes live. The owner decides; the on-chain trading wallet stays off.
