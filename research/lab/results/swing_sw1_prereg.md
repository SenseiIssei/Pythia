# SW1: the lab's swing rules and a short hold grid on the rug-free coin universe, at Hyperliquid's costs, for a 50 EUR account. Pre-registration

Registered 2026-10-30 and committed before any number below was computed. While scoping I looked only at which
folders the lab holds (`<data>/hist/binance_um/klines_1d` and `funding`, `<data>/free/perps_all/hyperliquid`,
`<data>/free/hyperliquid`), at one file's columns, at the registry's trial counts by family and at whether
data.binance.vision answers. I computed no universe count, return, volatility or Sharpe.

Asked by the owner on 2026-10-30. DT1 (`results/daytrade_dt1.md`) said no to day trading: the edge before costs is
about zero and a round trip costs about 12 bps. The owner picked swing next: the same liquid coins with no rug risk,
held days to weeks, paper only. This study answers whether a swing rule is fundable for him at 50 EUR, and says
plainly if not.

What is new, and the only reason to run it: the lab's swing rules were judged on Kraken spot (0.80 % taker a side for
a new account, `kraken_fee_s1.md`, which sank `smallaccount_r10` and S1 at 40 and 100 EUR) or at Binance or Alpaca
costs, never on the venue the owner can reach with low fees: Hyperliquid perps (4.5 bps taker, 1.5 bps maker, funding
every hour, minimum order 10 USD). T12 (`reachable_venues_t12.md`) ran only the market-neutral perps book there. It
does not repeat `breakout_study`, `family_breakout` (Donchian 20/10 top 10 and 55/27 BTC+ETH: real sign, unproven
size), `hedged_breakout`, `trend_shorts` (its picks are reused as the short sides, below), `tsmom_tranches`, the
small-account studies (S1, S2, weekly, R10, the Kraken fee), `vol_daily` (M6: the 30-day mean sizing is used),
`funding_carry` or DT1.

Builds on the review of 2026-10-27 (`results/review_2026-10-27.md`, sections 2 and 3), R5's registry
(`metrics.trial_pool`, `<data>/trials/registry.jsonl`), R6's windows and lockbox and the readiness ladder
(`lab.ops.ladder`, A4's route `results/ladder_promotion_a4_prereg.md`).

Code: `lab.experiments.swing_sw1`, written after this file; tests `tests/test_swing_sw1.py`. Results:
`results/swing_sw1.md` and a README row. Nothing in this file may change once a result exists. Paper only: nothing a
live bot, a wallet or the engine reads changes; no key, no account, no order.

## Windows

In sample 2022-01-01 to 2024-12-31, out of sample 2025-01-01 to 2026-06-30 (judged). No bar, funding rate or price
after 2026-06-30 is loaded: the lockbox (from 2026-07-01) is untouched. 2024 lies in R6's validation window and other
studies have looked at it with these rules; here it is in sample, as the task sets it, and only 2025-01 on is judged.
The daily history before 2022 is read only as the rules' warm-up (channels, 28-day returns, BTC's 200-day average).

## Universe: DT1's, point in time

DT1's rule and code (`daytrade_dt1.load_daily`, `to_daily`, `qualifies`, `hl_listings`, `listed_mask`): a Binance
USDT-M perp is in on UTC day d when its segment's first daily bar is at least 180 days before d, the mean quote volume
of days d-30 to d-1 is at least 50 M USD, and it is not a stablecoin, fiat, commodity, equity, index or leveraged
product. Delisted coins are in for every day they qualified. **The judged universe** is the coins of it Hyperliquid
lists that day (T12b's listing history, from 2023-05-12; empty before). **The Binance universe** (no Hyperliquid cut)
is the in-sample one, since Hyperliquid has no history before 2023-05.

**Bars.** DT1's 1-minute cache was the agent's own folder of that run and is gone; it is not in `<data>`. The daily
bars are Binance's own UTC daily klines of the same perps (`<data>/hist/binance_um/klines_1d`: open, high, low,
close, quote volume), which are those minutes summed by UTC day. The rules' volatility (the 30-day mean of the daily
realised variance, M6's RW30, as `fam_common.Panel.sigma`) needs intraday returns: the realised variance of a day is
the sum of its squared 1-hour log returns, from Binance USD-M 1-hour klines (data.binance.vision, every month in which
a coin qualifies on any day and the two months before it, 2021-10 to 2026-06, into the agent's folder). A coin-day
without 1-hour bars has no variance; its volatility needs 20 of the last 30 days. As a check (not judged) the 1-hour
bars summed by UTC day are compared with the daily klines (the share of days whose close and quote volume agree to
0.1 %).

## Execution and costs (every rule)

- A signal is known at the close of UTC day t (from bars to day t only). It fills at the open of day t+1 (base) and,
  as the second case, at the open of t+2 (one day late). Position returns are open to open.
- **Hyperliquid taker: 4.5 bps fee a side plus slippage**: 1 bp for the day's 20 coins with the highest 30-day volume
  (DT1's top 20), 3 bps for the rest (DT1 measured a median of 1.4 bps a side over its traded coins; 3 bps sits
  above it). No maker case: a swing order at the open is a taker order.
- **Funding at its real rate**: a position held over UTC day d pays (a long, positive rate) or receives side x
  notional x the sum of day d's rates: Hyperliquid's hourly rates (`<data>/free/perps_all/hyperliquid/funding`,
  from 2023-05-12) where Hyperliquid has a record for the coin that day, Binance's settlements
  (`<data>/hist/binance_um/funding`) before or otherwise. Which source paid how much is reported.
- A coin Hyperliquid stops listing (or whose bars end) is closed at the next open (at its last close when there is no
  further bar), at taker cost. On the judged universe a coin is opened or increased only on a day Hyperliquid lists it.
- **Accounts.** 50 EUR (57 USD) and 200 EUR (228 USD) at a fixed 1.14 USD a EUR; and an ideal account (any size,
  no minimum) as the reference that separates the rule from the minimum. Equity is the margin balance plus open
  P&L, marked daily. **No leverage above 1 on the book**: when the targets' gross exceeds the equity they are scaled
  down to it. **Hyperliquid's 10 USD minimum**: an order opening, increasing or reducing a position by less than
  10 USD is not sent (the target is kept and tried again the next day); a full close is always sent (reduce-only).
  **At most floor(equity / 10 USD) positions** (5 at 57 USD, 22 at 228 USD): a new position beyond it is not
  opened. Every order not sent is counted, entries apart: the report gives the share of the rule's entries the
  minimum or the position cap skipped. A rule's target is traded only when it differs from the last target traded
  (NaN means keep, as `fam_common.simulate` reads the weight matrices): breakout positions drift, tsmom's are resized
  daily, as in the lab.
- Each window is a fresh account: all cash on the first day (2022-01-01 in sample, 2025-01-01 out of sample),
  starting from the rule's targets as they stand that day.

## R: the lab's existing swing rules, unchanged

The weight functions the lab runs (`smallaccount.candidate`, `fam_breakout.breakout_weights`,
`fam_volmom.base_weights`, `trend_shorts.tsmom_side` and `donchian_side`, `memecoins.rotation`) on a
`fam_common.Panel` built from the bars above, whose eligible coins are the universe's (judged or Binance) and whose
28-day volume, volatility and BTC 200-day filter are computed as `fam_common.panel_from` does. Only the universe and
the venue change.

1. `breakout_top10`: Donchian 20/10 among the 10 most liquid eligible coins each day, no regime.
2. `breakout_btceth`: Donchian 55/27 on BTC and ETH, with its regime (no entries and everything sold while BTC is
   below its 200-day average).
3. `tsmom1`: 28-day momentum on the most liquid coin, regime (`small50_tsmom1`).
4. `tsmom_top20`: 28-day momentum on the 20 most liquid, 40 % vol over 20 slots, regime.
5. `breakout_sol3`: Donchian 20/10 among the 3 most liquid coins with a Solana mint (`small100_breakout_sol3`).
6. `breakout_sol10`: the same among 10 (`onchain_breakout_sol`).
7. `btc_gated`: all in BTC while BTC closes above its 200-day average, cash below.
8. `memes_rotation`: the best of the six Alpaca memecoins (DOGE, SHIB, PEPE, BONK, WIF, TRUMP) by 28-day return,
   BTC gate, where they are in the universe.
9. `breakout_top10_ls`: rule 1 plus `trend_shorts`' registered pick for its short side (mirror Donchian shorts only
   while BTC is below its 200-day average, half size).
10. `tsmom_top20_ls`: rule 4 plus `trend_shorts`' pick (short every top-20 coin with a negative 28-day return,
    always, half size); its gross is capped at 1 by the account rule.

The other rules have no short side in the lab. Not run, with the reason: `tsmom_tranches` (and its `lowkr` and
`lowmax` filters): seven tranches of 57 USD are 8 USD each, under the minimum on every order, and its signal is
tsmom_top20's; `tsmom` and `tsmom_regime` trade today's 20 survivors (survivorship), their point-in-time twin is
tsmom_top20; `trend4h_pullback` is a 4-hour rule; `small40_*`, the EQ1 books (SPY, gold, ETFs) are not crypto; the
perps-neutral books (M4, carry, low vol, picks_ls) are T12's; the factory genomes have their own shadows.

## H: one small new grid

On the judged universe: enter long at the open after a close above the highest close of the N previous days (the
coin among the K with the highest 28-day volume that day), exit at the open after a close below the lowest close of
the N/2 previous days (the opposite channel, the lab's convention) or after D days held, whichever is first. N in
{10, 20, 55} (exit channel 5, 10, 27), D in {5, 10, 20}, K in {5, 10, 20}: 27 cells. Equal risk by the 30-day mean
volatility (M6): each entry gets min(0.40 / annual vol, 1) / S of the equity, S = K slots (the ideal account) or
S = min(K, floor(equity / 10 USD)) at entry (the real accounts), left to drift until its exit. A coin re-enters only
after a new breakout. Long only.

## Trials (R5's registry, family small, source this file)

37 rules (10 R, 27 H), three accounts (57 USD, 228 USD, ideal), two fills (base, one day late): 222 trials
`small:sw1:<rule>:<account>:<fill>`, each registered with its in-sample annual Sharpe (Binance universe, 2022 to
2024) before any out-of-sample number is computed. The bar check and the funding sources are not trials. The DSR is
over R5's pool of all (this study's trials in), the small family's shown next to it.

## Pass (per rule at 57 USD and at 228 USD; all must hold out of sample, 2025-01-01 to 2026-06-30, judged universe)

1. Sharpe (daily, annualised with 365) above BTC buy and hold's (BTCUSDT perp, open to open, no cost) on the same
   days;
2. one day late, Sharpe above 0;
3. the 5 % quantile of a day-block bootstrap of the mean daily excess return over BTC above 0 (the stationary
   bootstrap, mean block 10 days, 2,000 draws, seed 7);
4. DSR of the book's daily returns at least 0.95 over R5's pool of all;
5. at least 10 entries sent out of sample.
Maximum drawdown, CAGR, the end equity, the entries, the skip shares, costs and funding are reported for every row,
the ideal account and the in-sample numbers next to them, and the DSR of the excess over BTC (the review's honest
form) beside the book's.

A pass goes onto the readiness ladder as a step-2 candidate with one forward shadow (A4's route): a paper book on
Hyperliquid's public data in its own later commit, PAPER ONLY (no key, no account, nothing sent), whose ladder row
then follows A4. No live trading without the owner's yes, and then within his 50 EUR limit. Without a pass nothing
reaches a book, the engine or a wallet, and the results say plainly that no swing rule is fundable for him on these
numbers.

## Reported

`results/swing_sw1.md`: the universe per quarter (DT1's counts), the bar check, per rule and account the out-of-sample
Sharpe, CAGR, maximum drawdown and end equity on time and late, BTC on the same days, the excess band, the DSR (book
and excess), entries, the share skipped by the minimum and by the position cap, costs and funding (Hyperliquid's and
Binance's share), the in-sample Sharpe, and the verdict; a README row.
