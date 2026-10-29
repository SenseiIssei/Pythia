# S1w: the small-account books traded weekly. Pre-registration

Registered 2026-10-29 and committed before any number below was computed. From the training plan of 2026-10-28, built on
the review (`results/review_2026-10-27.md`, sections 2 and 3), R5's trial registry and R6's windows. Code:
`lab.experiments.smallaccount_weekly` (written after this file). Results go to `results/smallaccount_weekly.md`. Paper
only: nothing a live bot, a wallet or the engine reads changes. Nothing here may change once a result exists.

## Question

The small-account paper books (`reports/smallaccount`) pay a large share of a tiny wallet in costs: S1's two paid
1.09 and 1.29 EUR in their first four days. Does trading them once a week, with a no-trade band, keep their signal
and cut what they pay?

Known before any number: those first costs are almost all the way in (Kraken's taker fee to USDC and 1 USDC to
withdraw, paid once at the start; the report shows 0 orders for both S1 books). No cadence changes that part. This
study is about what the books pay to trade after that, and it shows the way in and back next to it.

## The books (nothing new in their rules, nothing tuned)

| book | wallet | rule | path | cadence as it runs |
|---|---|---|---|---|
| small50_tsmom1 | 50 EUR | tsmom_top20 on the most liquid coin, regime, 40 % vol (S1) | S1's | daily |
| small100_breakout_sol3 | 100 EUR | Donchian 20/10 on the 3 most liquid coins with a Solana mint (S1) | S1's | daily |
| small40_spy_trend | 40 EUR | the S&P 500 token above SPY's 200-day average, USDC below (S2) | S2's | daily |
| small40_vol_target | 40 EUR | S&P 500 token, BTC and gold by inverse vol, 10 % vol (S2) | S2's | weekly (Wednesday) |

## The variants

- **as run**: the book as `lab.paper.smallaccount` runs it.
- **weekly**: the same targets, read and traded only at the close of the weekday; nothing trades on other days.
- **weekly_band**: weekly plus the no-trade band.

**The weekday: Wednesday.** The panel day Wednesday, its close at 00:00 UTC Thursday (`smallaccount.rebalance_day(day,
7)`: days since 2020-01-01, a Wednesday, modulo 7). It is the day S1's weekly cadence and S2's weekly rules
(vol_target, dual_mom) already use, and a US close happened on it, so SPY's close the S2 rules read is hours old, not
a weekend old.

**The band, declared now: 10 percentage points of the wallet's trading equity.** On the weekday, an asset whose
target weight differs from its weight now by less than 0.10 is not traded; it keeps its last decision and is looked
at again the next week. An exit (target 0 for an asset held) always trades. With a band of 0 the rule is `weekly`.
Everything else is the wallet code the books use (S1's minimum of 5 USDC, dust, sales first, buys scaled to the cash).

small40_vol_target already runs weekly on Wednesdays, so its `weekly` is its `as run`; it has two variants.

## Costs: each path as the books charge it, in R10's honest form

- S1's two books: S1's Jupiter quote ladder and network fee (0.000105 SOL a swap); S2's two: S2's ladder and network
  fee with the Sender tip. A swap costs the recorded quote only from the day the asset could be swapped on chain
  (R10: SOL, ETH and USDC from 2021-10-01, BTC from 2024-11-07, the S&P 500 and gold tokens from 2025-06-30); before
  that Kraken's taker fee and the half spread of its EUR pair (R10's `EraVenue`, nothing changed).
- The wallet is USDC, worth its USD value at the ECB's EUR/USD of the day; the way in (EUR to USDC at Kraken, 1 USDC to
  withdraw) and the way back at the last close (every position sold, USDC to EUR, 0.09 EUR SEPA) as in R10.
- The tokens at 00:00 UTC: R10's draw with seed 10 (the rules read the underlying).
- As a side row only: today's quotes back to the start (what the paper books charge now).

## Windows (R6)

In sample 2020-08-01 to 2023-12-31, validation 2024-01-01 to 2026-06-30. The lockbox from 2026-07-01 is never read.

## Fills

Every variant on time (traded at the close its targets read) and **one close late** (the targets known at Wednesday's
close traded at Thursday's; the band judged on the weights at the close it trades). The late fill is the one judged.

## Reported, per book and variant, at the book's wallet, validation window, on time and late

CAGR, max drawdown, Sharpe (daily, x sqrt 365), the end in EUR after the way back; costs in EUR: the trading costs,
the way in, the way back and the total, and the total and the trading costs a year as a share of the wallet;
turnover (EUR traded over the mean equity, a year); orders and orders not sent a year; the costs with today's quotes
as the side row; in sample the late Sharpe.

- **DSR** (`metrics.dsr`, higher is better, pass at 0.95 or more) over R5's registry, the pool of all (the registry
  and the factory ledgers counted once by id, as R10) and the small family: of the late validation daily returns in
  EUR, and of their daily excess over the book as run.
- **PBO** (`metrics.cscv`, 16 blocks, by Sharpe) of picking the best variant by in-sample performance: per book over
  its variants and over all eleven variants, on the late daily returns in EUR of one wallet run from 2020-08-01 to
  2026-06-30.
- **T1's leak harness** (`lab.leak.check`): each weekly_band variant's late wallet (S1's books on the panel, S2's on
  S2's market), equity at every close against copies with every value after the cut shuffled, shifted, missing, and
  cut off.

## The one to follow, fixed now

Per book, **weekly_band** is the variant to follow (`weekly` is shown for what the band adds; no variant is picked
by its numbers). It gets a paper book beside the as-run one, with the same wallet (`<book>_wk`, its own 40, 50 or 100
EUR from the deploy, the same costs, in the same EUR report), if over the validation window, filled one close late,
at the book's wallet, all three hold:

1. **costs cut**: its trading costs in EUR (without the way in and back) are below the as-run book's;
2. **signal kept**: its Sharpe is at least the as-run book's minus 0.10, and its CAGR at least the as-run book's
   minus 1 percentage point;
3. **no leak** in T1's harness.

DSR and PBO are reported and do not gate a paper book; R10's bar stays the only way to real money and is not
touched. A book that fails keeps running as it does; nothing is removed.

## Trials

Seven new rules, each one trial of R5's registry in the small family (`small:s1w:<book>:<variant>`, with its late
in-sample Sharpe at the book's wallet), registered before any validation number is computed: weekly for tsmom1,
breakout_sol3 and spy_trend, weekly_band for all four. The as-run books are S1's and S2's trials already counted
(`small:s1`, `small:s2`) and add none.
