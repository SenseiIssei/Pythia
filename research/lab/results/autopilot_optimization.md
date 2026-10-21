# Autopilot cost and churn: what the paper autopilots pay, and what changed

Part 1 (the audit) reads the engine's own records; part 2 (the rebalance band
study) is pre-registered below and was committed before it ran. Generated
numbers go below the marker.

## Part 1: the audit, from the engine state

Source: the engine's saved state (`autopilot/state.json`, `autopilot-safe/
state.json`): every order and fill with its book, route, maker and taker
quantity, realised cost against the decision price, the fee, and every
autopilot's equity history. Code: `lab.ops.autopilot_audit` (read only).

Per running autopilot: days, fills, cancelled and partial orders, refused
orders, notional traded, turnover per day (traded / amount / days), fees and
slippage in dollars and in bps of the amount per day, realised cost per unit
traded against the 35 bps the backtests charge, the share of orders under 1 %
of the amount ("trims") and their share of the cost, round trips (a coin
bought and sold, or sold and bought, in the same book within 72 hours), and
the cost of the costs: the dollars against the gap to BTC over the same days.

## Part 2: a resize band for lab rebalances (pre-registered 2026-10-21)

### Question

The engine rebalances a lab book by trading every coin whose difference to its
target is at least 0.2 % of the capital (and $5). The daily books resize most
held coins every day by a few tenths of a percent. Does a wider band on
resizes cut the cost without changing which coins a book holds or what it
earns?

### Rule tested

At each close, per coin, the engine compares the drifted holding h with the
signal's target w (both as fractions of the book's capital):

- an **entry** (h = 0, w > 0) and an **exit** (w = 0, h > 0) always trade, as
  long as the order clears the venue minimum;
- a **resize** (h > 0 and w > 0) trades only when |w - h| >= b, and then all
  the way to w.

Baseline (today's engine): every difference, entries and exits included,
trades when it is at least 0.2 % of capital. b in {0.5 %, 1 %, 2 %}.

### Books and data

breakout_top10, tsmom_top20 and tsmom_tranches as the autopilots run them on
Alpaca (`alpaca_universe` C rows: the paper books' own targets, coins Alpaca
does not list held as cash; tsmom_tranches' targets are the book its own
simulator holds after each close), and tsmom_regime (`book_portfolio`'s
regime book: 28 days, daily, 40 % vol per coin, flat below BTC's 200-day
average). The sweep's daily panel to its last day; 35 bps per unit of
turnover (stress 70). In sample 2020-08-01 to 2023-12-31, out of sample
2024-01-01 on. 3 bands x 4 books = 12 trials beyond the baseline.

### Pick and confirmation

Pick the largest b for which, **in sample, for every book**:

1. turnover cost at least 25 % below the baseline's,
2. Sharpe at 35 bps not lower than the baseline's by more than 0.02,
3. annualised tracking error of the daily net returns against the baseline at
   most 1.0 %.

Then confirm the same three conditions out of sample for every book. If the
confirmation holds, the engine's default resize band becomes b; if not, the
default stays and the band is only a setting. The coin set held on any day is
the same as the baseline's by construction, so the band never changes which
coins a book holds, only how often a held coin is resized.

<!-- generated below by lab.ops.autopilot_audit and lab.experiments.rebalance_band; edit above this line only -->
