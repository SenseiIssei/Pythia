# M4H: the M4 reg7n long/short at a 200 EUR account on Hyperliquid, automated, after every cost. Pre-registration

Registered 2026-10-30 and committed before any number below was computed. While scoping I looked only at which
folders the lab holds (`<data>/lab-cache/xs_daily_panel.parquet`, `<data>/hist/binance_spot/klines_1h`,
`<data>/free/perps_all/hyperliquid`, `<data>/etf/daily`), at the columns and date range of the panel and of one
Hyperliquid funding file, at the registry's trial counts (4,178 in all, 652 small) and at whether Hyperliquid's public
`meta` endpoint answers. I computed no score, return, universe count or Sharpe.

Asked by the owner on 2026-10-30. DT1 (`results/daytrade_dt1.md`) and SW1 (`results/swing_sw1.md`) said no; the
pump.fun bot is off. He wants one strategy that trades automatically with about 200 EUR (230 USD), or he buys an ETF.
The only rule in the lab with an out-of-sample record that survives costs and does not need a rising market is M4
reg7n (`results/m4_residual.md`: holdout Sharpe 2.02 at 41 bps, about 1 beyond the low-vol factor and BTC; fails
deflation, p 0.0020). The question: **can reg7n run at 230 USD on Hyperliquid, and what does it earn there after
fees, slippage, funding, size rounding and the 10 USD minimum, against an ETF held on the same days?**

What is new, and the only reason to run it: no study has run reg7n at a real account size. m4_residual and m4_funding
ran it as weights on the whole Binance universe at a flat cost; T12 (`results/reachable_venues_t12.md`) put it on
Hyperliquid's coins, 10/10 at the ideal size, one close late, inside an ERC portfolio (M4 alone 1.81 in validation
against 2.74 on Binance); `m4_perps` trades it on Kraken's coins in paper at 10,000 USD. None has the minimum order,
the size decimals, fewer names or leverage. Not repeated: m4_residual's residual test, m4_funding's variant search,
T12's venue comparison, SW1's swing rules.

Builds on the review of 2026-10-27 (`results/review_2026-10-27.md`, sections 2 and 3), R5's registry
(`metrics.trial_pool`, `<data>/trials/registry.jsonl`), R6's windows (in sample to 2023-12-31, validation
2024-01-01 to 2026-06-30, lockbox from 2026-07-01) and the readiness ladder (`lab.ops.ladder`, A4's route
`results/ladder_promotion_a4_prereg.md`).

Code: `lab.experiments.m4h`, written after this file; tests `tests/test_m4h.py`. Results: `results/m4h.md` and a
README row. Nothing in this file may change once a result exists. Paper only: nothing a live bot, a wallet or the
engine reads changes; no key, no account, no order.

## Windows

- **In sample** 2022-01-01 to 2023-12-31 (decision days). The scores there are walk-forward (first test quarter
  2022Q1), as in m4_residual's fit window.
- **Out of sample, judged** decision days 2024-01-01 to 2026-06-28: the last holding period ends on 2026-06-30 at
  01:00 (02:00 late) UTC. This is m4_residual's holdout cut at R6's lockbox: **nothing from 2026-07-01 on is read**
  (no price, funding rate or score; the panel's rows are cut right after loading). The review says the 2024+ window
  is no longer clean out of sample for the lab as a whole; for reg7n it is the window its pick was judged on once
  (m4_residual), so a pass here is the same holdout seen again at a new size, not fresh evidence.

## The signal, unchanged

reg7n exactly as m4_residual and `m4_perps` run it: LightGBM regression on the funding-net 7-day rank label y7n, the
xs_daily features and parameters, quarterly walk-forward from 2022Q1 with an embargo of 8 days. The 2026-10-07 score
cache is gone, so the scores are refit with T6b's `two_leads_t6b.reg7n_scores` (xs_daily's folds, embargo and
parameters, reg7n only) on xs_daily's panel (`<data>/lab-cache/xs_daily_panel.parquet`) cut at 2026-06-30, as T12 did.
No new feature, label, parameter or model.

**Check, not judged.** The rebuilt 10/10 book (100 most liquid perps, buffer 50 %, Binance universe) at 41 bps per
unit of one-way turnover with Binance funding, xs_daily's own `book_buffer`: its 2022-2023 Sharpe against
m4_residual's 0.93 and its 2024 and 2025 Sharpes against 1.67 and 2.43. If the 2022-2023 Sharpe differs from 0.93 by
more than 0.3 the study stops before any judged number and says so.

## Universe

- Each decision day: the coins with a reg7n score, the 100 with the highest 28-day perp volume (`perp_adv28`), as
  `xs_daily.book_buffer` takes them.
- **Out of sample**: of those 100, only the coins Hyperliquid lists on the fill day (decision day + 1; T12b's listing
  history `<data>/free/perps_all/hyperliquid/listings.json` read with DT1's `hl_listings`, the Binance perp symbol
  mapped by `hl_to_binance`). Ranking and the rank buffer then run among the listed coins only (as `m4_perps` does for
  Kraken). A held coin Hyperliquid no longer lists is closed at the next fill at taker cost.
- **In sample**: the 100 Binance perps without a Hyperliquid cut (Hyperliquid's history starts 2023-05-12).

## The book

k long and k short, k in {3, 5, 10} (10 is the original), xs_daily's rank buffer at 50 %: a name enters a side when it
ranks in that side's best k, leaves when it drops out of that side's best half of the (listed) liquid set; an entering
name gets G x 0.5 / k of equity, a held name drifts and is cut back to G / k when it grows past it. Gross exposure G
in {1, 2} times the account (2: Hyperliquid's cross margin at 2x; every coin's maximum leverage is 3 or more).

## Fills, prices and costs

- The signal is known at 00:00 UTC (features from bars to the end of the decision day). **Base fill**: the open of
  the next hour, 01:00 UTC, which is the panel's entry price P (Binance spot close of the first hour). **Late fill**:
  one hour later, 02:00 UTC (the close of the second hourly bar, from `<data>/hist/binance_spot/klines_1h`). Returns
  run from fill to fill. Binance prices stand in for Hyperliquid's (DT1 found them 1 to 3 bps apart on the majors).
- **Taker**: Hyperliquid's 4.5 bps a side plus a slippage by coin, DT1's spread proxy on 1-hour bars (DT1's minute
  cache is gone): per coin and day the Abdi-Ranaldo spread over the 30 days before the decision; 1 bp for the day's
  20 most liquid of the set (by perp_adv28), otherwise 1 bp plus half the excess of the coin's spread over the top
  20's median, capped at 50 bps; 50 bps without an estimate. **Maker**: 1.5 bps a side, no slippage: an optimistic
  bound that assumes every order rests and fills at the reference price (reported, not judged).
- **Funding**: Hyperliquid's own hourly rates (`<data>/free/perps_all/hyperliquid/funding`) with a time in the holding
  period (fill, next fill], a long paying a positive rate; where Hyperliquid has no record for a held coin that day,
  Binance's settlements over the same day (the panel's `fund_hold`). In sample: Binance's, both fills.

## Accounts

115, 230 and 460 USD (100, 200 and 400 EUR), and an ideal account (any size, no minimum, no rounding: the reference
for drift and correlation). Each window is a fresh account, all cash on its first day. Equity is the cash plus the
open P&L, marked at every fill. Every day each coin's target is G-scaled weight x equity, its size in coins is
rounded to Hyperliquid's size decimals (`szDecimals` from the public `meta` endpoint, today's value for every coin
including delisted ones; a coin without one: 0 decimals) at the fill price. **The 10 USD minimum**: an order that
opens, increases or reduces a position by less than 10 USD is not sent (an entry is tried again the next day if the
name is still picked; a cut-back is tried again when it is due); a full close is always sent (reduce-only). An account
at or below zero stops. A stop at -20 % from the start is not applied in the backtest; whether and when it would
have fired is reported.

Reported per cell: Sharpe (daily, x sqrt 365), CAGR, maximum drawdown, end equity, by year, worst month; entries
wanted, sent, the share the minimum skipped, cut-backs skipped; **drift**: the mean over days of half the sum of
|account weight - ideal account weight| (the same cell's ideal account), and the correlation of the daily returns
with the ideal account's; fees, slippage and funding as a share of equity a year.

## Benchmarks, the same days

BTC held (BTCUSDT's entry-to-entry return from the panel, no cost); SPY held (`<data>/etf/daily/SPY.csv`, USD); the
world ETF: ACWI and URTH are not in the lab, so EUNL.DE (iShares Core MSCI World UCITS, Xetra, EUR; the lab's world
fund in `etf_books_eq1`), close to close, a calendar day without a close earning 0. Reported as Sharpe, CAGR,
drawdown and the money 200 EUR would have made over the window; the bot's USD converted to EUR at the day's rate of
`results/etf_books_eq1_eurusd.csv`.

## Pass (judged once)

At **230 USD, taker, base fill, G = 1**, for any k, all of:

1. out-of-sample net Sharpe above 1.0;
2. the stationary day-block bootstrap of the Sharpe (director_common's: mean block 20 days, 4,000 draws, its seed)
   with its 5 % quantile above 0;
3. a positive mean daily return in each of 2024, 2025 and 2026 (to 2026-06-28);
4. maximum drawdown under 25 %;
5. correlation of the daily returns with the ideal-size book (the same k) above 0.8.

**Deflation.** The DSR (`metrics.dsr`, higher is better, pass at 0.95) of every judged cell against the registry's
pool of all trials and the small family's, this study's trials included. As in m4_residual, the study this one
extends, it decides whether a pass counts as **confirmed**; it is not one of the five checks. A pass that is not
confirmed is still an experiment.

If more than one k passes, the paper book takes the passing k with the highest in-sample Sharpe at 230 USD (taker,
base fill, G 1), never an out-of-sample number. The one-hour-late, maker, 2x, 115 and 460 USD cells are reported, not
judged.

**If it fails**, the reason is named from the cells: **minimum** (the ideal account passes 1 to 4, 230 USD does
not), **funding** (the 230 USD cell passes 1 to 4 without funding but not with it, reported as information), **no
edge** (the ideal account fails too). The smallest of 115, 230 and 460 USD that passes, or none, is the account size
that would.

## If it passes

1. A paper book `m4_hl_small` (230 USD, the passing k, G 1) on Hyperliquid's public prices, daily, written like
   `m4_perps`, and a forward shadow on the readiness ladder by A4's route. Paper only.
2. An execution module for Hyperliquid in dry run only: the exact orders it would send for the day's book (coin,
   side, size after rounding, reduce-only where it closes), with hard limits in code (account at most 250 USD, gross
   at most 2x, flat and stop at -20 % from the start, a file switch to go flat), no key, no signing, nothing sent,
   a test for every limit. Going live needs the owner's yes after at least 30 days of forward record and an API
   wallet he makes himself; never part of this study.

## Trials (97)

4 accounts (115, 230, 460 USD, ideal) x 3 k x 2 gross x 2 fills x 2 fee cases = 96 cells, plus the rebuilt 10/10
book of the check: **97**, family small, each with its in-sample Sharpe (2022-2023, the same cell on the Binance
universe), registered in R5's registry before any out-of-sample number is computed. Pool after: 4,275 in all.

## What could fool us

- The holdout is the one reg7n was picked against and judged on (above); a pass repeats it, it does not renew it.
- reg7n leans on the low-vol factor (beta 0.71 in 2022-2023, 0.5 to 0.84 rolling); at k = 3 a book is three names
  a side and carries far more single-coin risk than the tested 10.
- Binance's prices stand in for Hyperliquid's; the maker case assumes fills that DT1 showed come mostly when the
  price comes back.
- At 2x a coin that doubles against a short can take a third of the account between two daily marks; intraday
  liquidation is not modelled, so 2x results are optimistic.
- Size decimals are today's; a coin that changed them in the past is rounded with today's.
