# Crypto plus a SPY sleeve, forward on Alpaca paper: pre-registration

Registered 2026-10-21, committed before the forward test exists, before any
forward day and before any code for it was written. Nothing in this file may
change once the first forward day is recorded; a change of the mix, the
schedule or the rule restarts the 90 days and is listed at the end with its
date.

## The finding this tests

`results/book_portfolio.md` (X7 B) failed its registered pick, and then counted
after the fact: with an equity sleeve, 22 of 24 mixes beat the best single
book, breakout_top10, on both Sharpe and drawdown out of sample (2024-01-01 to
2026-10-11; median Sharpe 1.31 against 1.17, median drawdown 9.3 % against
16.0 %). SPY bought and held was 0.17 correlated with the crypto books. An
after-the-fact count is a hypothesis, not evidence. This test asks the same
question on data nobody has seen yet.

## Hypothesis

H: a portfolio of **80 % breakout_top10 and 20 % SPY bought and held**, run on
the Alpaca paper account by the engine exactly as the autopilots run today, has
a higher Sharpe and a lower maximum drawdown than breakout_top10 alone over the
same 90 days, with the bootstrap band of the Sharpe difference above zero.

Why this mix: it is the simplest one in the family. One crypto book (the one
the X7 B mixes were measured against, and the only Alpaca book with a plausible
edge over gated BTC in `results/gated_btc.md`), the smaller of the two sleeve
sizes tried (20 %), and buy and hold, so the equity sleeve has no signal of its
own to overfit. It was not one of the 30 X7 B trials (those mixed four crypto
books); it is chosen for simplicity, not for its backtest. A backtest of this
exact mix on the existing panel may be reported next to the forward result as
context; it is not part of the judgement.

## The two autopilots (paper only, Alpaca paper account, demo mode)

| | Treatment | Control |
|---|---|---|
| name | Crypto + SPY (forward test) | Breakout alone (forward control) |
| kind | portfolio autopilot (crypto and US shares in one book) | one asset class, crypto |
| sleeves | `lab:breakout_top10` 80 %, `lab:spy_hold` 20 %, chosen explicitly | `lab:breakout_top10` 100 %, chosen explicitly |
| amount | $10,000 | $10,000 |
| re-pick | none (explicit sleeves are never re-picked) | none |
| stop rules | none (a stop would cut the drawdown being measured) | none |
| started | within the same hour | within the same hour |

- **Crypto sleeve.** breakout_top10's daily lab signal, netted and rebalanced
  by the engine as in every autopilot (coins Alpaca does not list held as
  cash). Its capital at each rebalance is 80 % of the portfolio's equity,
  never more than what the SPY sleeve leaves free.
- **SPY sleeve, rebalanced monthly.** `lab:spy_hold` is a lab book of US
  shares whose signal is always 100 % SPY. Its job publishes a new signal once
  per calendar month (the first run in the month) and the engine trades it at
  the first regular US session after it: the SPY position goes back to 20 % of
  the portfolio's equity. Between those dates SPY drifts with the market.
- `lab:spy_hold` can only be run by naming it as a sleeve: the auto pick (and
  the portfolio allocator behind it) never picks it, so no other autopilot
  gets SPY because of this test.

## Measurement

- Each autopilot's equity once a day as the daily forward report records it
  (`reports/forward/<day>.json`, written about 06:15 UTC; the engine's own
  equity history is thinned and is not used). Point 0 is the first report
  after both have run at least 24 hours; the test ends at the report 90 days
  later. A day without a report merges into the next return (the gap is
  named), nothing is filled in.
- Daily returns between consecutive points. Sharpe = mean / standard deviation
  of the daily returns x sqrt(365). Maximum drawdown on the daily equity
  points.
- Bootstrap: stationary block bootstrap of the paired daily returns (the same
  days for both), mean block 10 days, 4,000 draws, seed 20261021; statistic
  Sharpe(treatment) minus Sharpe(control).
- Costs are whatever the paper fills cost: both autopilots trade the same
  account with the same routes, so the comparison carries no cost model.

## Pass rule (all three, after 90 days)

1. Sharpe(treatment) > Sharpe(control)
2. max drawdown(treatment) < max drawdown(control)
3. the bootstrap's 5 % quantile of Sharpe(treatment) minus Sharpe(control) is
   above 0

Reported next to it, not judged: both against BTC bought and held, against BTC
held only above its 200-day average (`results/gated_btc.md`'s G at k = 1), and
the treatment against its own blend benchmark (80 % BTC, 20 % SPY).

What the result is allowed to mean:

- **Pass**: the equity sleeve is shown forward. The report may propose (not
  deploy) an explicit SPY sleeve in the main autopilot.
- **1 and 2 hold, 3 fails**: "consistent with X7 B, not shown". Nothing changes.
  With 90 days this is the most likely good outcome: the band of a Sharpe
  difference over 90 days is wide.
- **1 or 2 fails**: X7 B's after-the-fact count did not hold forward. The
  test stops and the autopilots are left as they are.

## Invalidation and bookkeeping

- If either autopilot stops, is restarted or changes its sleeves, the days
  after that are not comparable: the test restarts from the next full day both
  run, and this file says so below.
- If the SPY sleeve was not traded for more than five regular sessions after a
  monthly signal (session queue, refused orders), the report names the days.
- Evaluation code: `lab.paper.equity_sleeve` (written after this file; it
  implements the rules above and nothing else).

## Changes after registration

None.
