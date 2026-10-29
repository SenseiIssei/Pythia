# EQ3: the equity books' orders on Alpaca's paper account, fills against the model. Pre-registration

Registered 2026-10-29 and committed before the first order was sent and before any fill, slippage or latency number
was computed. Brief EQ3 of the training plan of 2026-10-28, on the review of 2026-10-27 (`results/review_2026-10-27.md`,
sections 2 and 3), R5's registry (`metrics.trial_pool`, `<data>/trials/registry.jsonl`) and R6's windows
(`results/factory_lockbox_r6.md`). Before real money the lab must know how its equity orders fill, as it measured
pump.fun's (the calibration line in `reports/pumpfun_rt/realistic.md`). Paper only: orders go to Alpaca's paper
account (no money), nothing a live bot, a wallet or the engine reads changes.

## What was seen before this file

No order, no quote. The books' journals were opened for their columns only (`date`, `weights`): the S2 books hold
`SPY`, `GOLD` and `BTC` targets. EQ2's cost model (`lab.experiments.daytrade_eq2.cost`: 5 bps or a cent a side,
doubled in the first three 5 minute bars, SEC fee and TAF on sells) and Alpaca's published rules (fractional market
orders from 1 USD, time in force `day`, regular hours only) were read. EQ2 has no paper book (it passed nothing).

## The books

The lab's paper books that trade US shares Alpaca carries: S2's `small40_spy_trend`, `small40_vol_target` and their
weekly twins `small40_spy_trend_wk`, `small40_vol_target_wk`. Their legs: `SPY` traded as SPY, `GOLD` as GLD (the
closes S2 prices gold by); `BTC` is a coin, not a share, and is left out (listed as dropped, its weight stays cash).
EQ2's book joins the list if it ever gets one. Targets: the latest row of `<data>/paper/<book>/journal.csv`.

## The account and the orders

- Every book has its own virtual wallet of 50 EUR in USD (EUR/USD the mid of Kraken's EUR/USD ticker in the
  dry run's cache `<data>/exec/kraken_pairs.json`, else the last ECB fixing of `results/etf_books_eq1_eurusd.csv`),
  converted once at the start; its cash and shares are the module's own ledger (`<data>/exec/alpaca_paper/`), not
  the account's positions (one paper account for all books).
- An order for a leg whose target weight differs from the one last traded (the first run: every target above 0):
  USD = target x (cash + held at the mid) - held at the mid; sells first (the shares, fractional, at most what the
  book and the account hold), then buys (notional USD, rounded down to the cent, at most the book's cash). Under 1 USD:
  not sent (`below 1 USD`). The asset must be tradable and fractionable when the size is fractional, else not sent.
- Market orders, time in force `day`, regular hours only: the job runs on weekdays at 15:00 UTC and sends nothing
  when Alpaca's clock says the market is closed. Base URL `https://paper-api.alpaca.markets` only, quotes from
  `data.alpaca.markets` (IEX feed); the module refuses any other base URL and has no code path for the live one.
  No transfer, no account setting, no cancel.
- Sent once: each order carries a client order id `eq3-<book>-<day>-<symbol>-<side>`; an id already in the ledger
  is never sent again. A send that dies without an answer is looked up by that id, not resent.

## The numbers, per order and per book

Per order: sent (time), the quote at send (bid, ask, mid), status, filled quantity and average price, the
acknowledgement time (send to answer) and the fill latency (send to `filled_at`), rejections and their reason. An
order not filled when the job ends is looked at again on the next run.

- Paper cost a side, bps: side x (fill / mid at send - 1) x 10^4 (buy +1, sell -1); price improvement is negative.
- The model's cost a side, bps: EQ2's half spread and slippage at the mid and the 5 minute bar of the send (the
  larger of 5 bps and a cent, doubled in the first three bars). The SEC fee and TAF are the model's on sells and are
  listed apart: the paper account does not charge them, so they are not part of the comparison.
- Per book and per day: orders, filled, rejected, the notional weighted paper and model costs in bps and their
  difference. Per book over all days: the ratio paper / model (notional weighted).
- **The ladder line** (step 5's cost condition at 1.5x for this venue): `fills within 1.5x the model's costs` holds
  for a book when at least 10 orders are filled and the ratio is at most 1.5; fewer than 10 fills is open. It is
  written into `reports/exec_alpaca/latest.json` (`books.<book>.ladder`); the ladder reads it when it gets a book of
  this venue. A measurement of the order path: no Sharpe, no DSR, no pass for a strategy. Every order is on a
  forward day after 2026-07-01, but it measures the account against a quote, not a rule's return: no lockbox look.

What a paper fill can not show: Alpaca's paper account fills against the quote without market impact, queue or
partial fills a 50 EUR order would not cause anyway; a ratio near 1 confirms the model's spread, not real fills.

## Reports and trials

`python -m lab.exec.alpaca_paper` (daily job `exec-alpaca`, weekdays 15:00 UTC) writes
`reports/exec_alpaca/latest.md` and `.json`. One trial per book in R5's registry, family small, counted only,
registered before the first order: `small:eq3:exec_alpaca_<book>` (4 trials). The keys come from
`APCA_API_KEY_ID` and `APCA_API_SECRET_KEY` in the environment; they are never logged, written or printed.
