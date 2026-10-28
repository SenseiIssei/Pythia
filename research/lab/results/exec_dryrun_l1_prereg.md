# L1: the order path for a 50 EUR execution trial, dry run only. Pre-registration

Registered 2026-10-28 and committed before the first order, count, fee or tracking number was computed. Brief L1 of
the training plan of 2026-10-28, on the review of 2026-10-27 (`results/review_2026-10-27.md`, sections 2 and 3),
R5's registry (`metrics.trial_pool`, `<data>/trials/registry.jsonl`) and R6's windows. Step 5 of the readiness
ladder (`lab.ops.ladder`) is an execution trial with at most 50 EUR; before any book gets there this shows whether
50 EUR can be traded cleanly on Kraken spot at all. Paper only: no key, no account, no order sent; nothing a live
bot, a wallet or the engine reads changes.

## What was seen before this file

Only the venue's rules, no order: Kraken's public AssetPairs answer of 2026-10-28 carries `ordermin`, `costmin`,
`lot_decimals` and `pair_decimals` for every pair but empty `fees` and `fees_maker` lists; its public fee page
(kraken.com/features/fee-schedule, read 2026-10-28) lists spot tier 1 (30-day volume from 0 USD) at 0.40 % maker
and 0.80 % taker, twice the 0.40 % taker S1 assumed. SPYx (S2's SPY) is a tokenized asset with a USD pair only;
PAXG has an EUR pair. The books' journals were opened for their columns only (`date`, `weights`).

## The books

The small-account books of S1 and S2 (`small50_tsmom1`, `small100_breakout_sol3`, `small40_spy_trend`,
`small40_vol_target`), the tsmom books (`tsmom`, `tsmom_regime`, `tsmom_top20`, `tsmom_tranches`,
`tsmom_tranches_lowkr`, `tsmom_tranches_lowmax`) and L1's on-chain tsmom1 (`onchain_longterm`). Their target
weights are the `weights` column of `<data>/paper/<book>/journal.csv` (a share of the book's equity per coin, cash
the rest), the row of each day. Every book gets the same 50 EUR wallet whatever its own size.

## The venue

- Pairs: a coin's EUR pair (`<coin>/EUR`, online); without one its USD pair (also the tokenized assets), the
  order then also pays the EUR to USD conversion at the published FX rate (0.20 %). Names: BTC is XBT, DOGE is
  XDG, GOLD is PAXG, SPY is SPYx. No pair: the order cannot be placed (reason `no pair`).
- Fee: the pair's `fees` / `fees_maker` tiers from AssetPairs when Kraken fills them, else the published spot
  schedule above (12 tiers, 0.80 % taker at 0 USD down to 0.10 % from 10M USD), the tier by the account's own
  placed volume over the last 30 days in USD. Orders are market orders (taker); the maker fee is reported next to it.
- The answers are cached in `<data>/exec/kraken_pairs.json` (AssetPairs of both asset classes, Ticker; refreshed
  after 20 hours, the stale cache used and said when Kraken does not answer) and daily closes in
  `<data>/exec/kraken_ohlc.json` (Kraken's public OHLC, interval 1440).

## The order rule

For one order: EUR to trade = target weight x wallet value - held value. Units before rounding = EUR / price;
after rounding = rounded down to `lot_decimals` (a sell never more than held); the limit price rounded to
`pair_decimals`. It cannot be placed when it rounds to 0 (`rounds to 0`), when units < `ordermin` (`below
ordermin`) or units x price < `costmin` (`below costmin`), checked in that order; a buy is cut to the cash left
after its fee. Fee = units x price x tier rate (plus the FX rate on a USD pair). Drift = the coin's weight after
the order minus its target.

- **Today's orders** (`dryrun.orders`): a fresh 50 EUR wallet, all cash, buying the latest journal row's
  targets at Kraken's ask (sells at the bid).
- **The replay** (`dryrun.replay`): the journal's days of the last 30 days, a 50 EUR wallet from the first; on
  each day a book order exists for every coin whose target changed from the day before (on the first day every
  target above 0); the account trades that coin to its target (sells first) at Kraken's daily close of the bar
  ending at the day's 00:00 UTC. A coin the book does not trade that day is left where it is.

## The numbers, per book

Orders and how many a 50 EUR account could not place (by reason, share of all); the tracking error that costs:
the mean weight left off target (sum over coins of |held - target| after each day's orders), the daily return gap
held minus target on the next day's closes annualised (standard deviation x sqrt(365), and the mean x 365, the
cost); fees as a share of the 50 EUR wallet a month (fees over the replay / days x 30), taker and maker. A
measurement of the order path, no Sharpe, no DSR, no pass or fail. The replay's days are paper forward days after
2026-07-01 (R6's lockbox), but the gap is the account against its own book, not a rule's return: no lockbox look.

## Reports and trials

`python -m lab.exec.dryrun` writes `reports/exec_dryrun/latest.md` and `.json` (daily job `exec-dryrun` after the
books). One trial per book in R5's registry, family small, counted only, registered before the first number:
`small:l1:exec_dryrun_<book>` (11 trials). The module has no code path that signs or sends: only public GET
requests to `api.kraken.com/0/public/`; a test reads its source for that.
