# Autopilot cost and churn: what the paper autopilots pay, and what changed

Part 1 (the audit) reads the engine's own records; part 2 (the rebalance band
study) is pre-registered below and was committed before it ran. Generated
numbers go below the marker.

## What it says (2026-10-21, six days of the six paper autopilots)

**Costs are not why the autopilots trail BTC.** Over their first six days the
five autopilots on the main Alpaca paper account paid 1.8 to 3.9 bps of their
amount a day (the memecoin experiment 19.6), 16 to 31 bps per dollar traded
against the 35 bps the backtests charge, with 72 to 94 % of the notional
filled as maker. All their costs together explain 3 to 8 % of the 2.7 to 3.9
points by which they trail BTC (26 % for the memecoin experiment, one PEPE
buy that chased the price for ten minutes and paid 240 bps). The gap is
exposure: in these six days breakout_top10 wanted 2 % of its book in coins,
tsmom_tranches 16 to 33 % and tsmom_regime 5 to 48 %, while BTC rose about
3 %. That is what the books are, not a cost to fix.

What the audit did find, and what changed:

1. **Re-pick churn (changed).** The Auto-Pick's re-pick runs every 24 hours
   from its start (12:34 UTC), eight hours after the lab signals (04:00 to
   04:15), and used to send a rebalance of its own on the signals already
   traded. Three of its ten rebalances were such re-pick rebalances: $8.37,
   40 % of everything it paid, and half of their notional ($2,555 of $5,018)
   was traded back within three days. The worst of it was a re-pick on 10-18
   that dropped breakout_top10 and tsmom_regime (their rebalancing trims read
   as "no edge" while `labEdgeFromTrades` was on; the engine of the main
   account has it off since 10-20) and added them back on 10-20. **The
   engine now nets a re-pick's new weights into the rebalance of the next lab
   signal** instead of trading them at once; a book a re-pick adds enters with
   its next signal. No book's signal changes; a re-weight arrives up to a day
   later. Test: `a_repick_adds_and_drops_lab_books_gradually_and_says_why`.
2. **Orders under the venue minimum (changed).** The safe account ($95,
   tsmom_regime) has not traded once in six days: its only order above the
   engine's $5 floor, BTC at about $5.50, was refused by Alpaca every day
   ("cost basis must be >= minimal amount of order 10", HTTP 403) and the
   engine called that an authentication failure. **Lab rebalances now use the
   route's venue minimum** (Alpaca crypto $10, from `config/costs.json`) and
   name the orders they leave out instead of sending them, and **a 403 for a
   small order is read as a refusal, not a key problem**. Tests:
   `a_small_demo_book_names_orders_under_alpacas_minimum_instead_of_sending_them`,
   `an_order_under_the_venue_minimum_is_named_not_sent`,
   `a_403_for_the_balance_or_a_wash_trade_is_a_refusal_not_a_key_problem`.
   The safe account still cannot run this book: at $95 almost every coin
   weight is under $10. It needs about $1,000 (or a one-coin book such as
   btc_gated); that is the owner's call, nothing was changed.
3. **Small resizes (studied, not changed).** Orders under 1 % of the amount
   were 23 % of tsmom_tranches' cost and 56 % of the Auto-Pick's. Part 2
   tested a wider resize band on the books' whole history: no band from
   0.5 % to 2 % cut the cost by a quarter for every book without moving the
   returns (in sample, cost down 0 to 17 % at 1 % and 0 to 40 % at 2 %;
   tracking error up to 3.2 % a year; tranches lost 0.04 to 0.22 of Sharpe).
   breakout_top10's cost does not move at all: its slots are entries and
   exits, which no band may skip. **The default band stays at 0.2 %.**
4. **Not worth an engine change.** Partial fills: 2 of 215 orders since the
   starts (and 31 cancelled: maker limits that timed out, the rest re-sent by
   the maker route), no churn.
   Cross-autopilot netting: $327 of $51,894 traded by the running autopilots
   was on opposite sides of one coin within 30 minutes; crossing it inside the
   engine would have saved at most $1.07 and would break the books' separate
   records. Maker timing: the lab rebalances already run at 04:00 to 04:16
   UTC, a quiet hour, with 72 to 94 % maker fills; the one bad fill (PEPE,
   36 % maker in that hour) was a fast market, not the hour. Skipping a
   rebalance whose expected gain is below its cost needs a per-trade edge
   the books do not have; the band study is the honest version of it.
5. **Round trips that are the signal.** tsmom_regime bought PEPE on 10-16,
   sold it 10-18, bought 10-19, sold 10-20; the memecoin rotation flipped PEPE
   in and out daily. Those are the rules crossing their thresholds, so a
   change would be a different strategy: a question for the lab, not a cost
   setting.

Also new, beyond costs:

- **Benchmark honesty.** Every crypto autopilot and portfolio is now held
  against BTC held only above its 200-day average (`results/gated_btc.md`, G
  at k = 1) as well as plain BTC: a `±G` column in the daily digest (it
  appears once the learning report has the number), a `vs BTC above 200d`
  column in the app's side-by-side table, the engine's `gatedBenchmark` on
  every status, the forward and learning reports. The forward report writes
  the gate calendar (one row per UTC day, from Binance's daily closes) into
  `reports/forward/evidence.json`; the engine computes the same return live.
- **The equity sleeve as a registered forward test** (`results/
  equity_sleeve_prereg.md`, committed before any of its code): 80 %
  breakout_top10 and 20 % SPY bought and held, back to 20 % once a month,
  against breakout_top10 alone, 90 days, pass = higher Sharpe, lower
  drawdown and the bootstrap band above zero. New: the lab book `spy_hold`
  (`lab.paper.spy_hold`, job `paper-spy-hold`), marked `explicit_only` so no
  auto pick or portfolio allocator gives it money, portfolio autopilots whose
  sleeves are chosen by hand, and the judgement `lab.paper.equity_sleeve`.
  Context only, computed after the registration and not part of it: the exact
  mix on the existing panel from 2024 made Sharpe 1.40 against 1.17 for
  breakout_top10 alone, drawdown 12.3 % against 16.0 %.

### How to start the forward test (nothing was started)

1. Deploy this engine and the lab to the server as usual, then run
   `python -m lab.paper.spy_hold` once (the job then runs each weekday at
   14:20 UTC and publishes a new signal only on the first run of a month).
   The engine reads `signals/spy_hold/latest.json` and keeps the book idle.
2. Start both autopilots within the same hour on the autopilot engine that
   trades the Alpaca paper account (`POST /api/command`, or the same JSON
   through the app's engine connection):

   ```json
   {"cmd": "autopilotStart", "confirm": false, "config": {
     "id": "ap_crypto_spy", "name": "Crypto + SPY (forward test)",
     "mode": "demo", "venue": "alpaca", "capitalUsd": 10000, "portfolio": true,
     "sleeves": [{"strategyId": "lab:breakout_top10", "weight": 0.8},
                 {"strategyId": "lab:spy_hold", "weight": 0.2}],
     "stop": {}, "flattenOnStop": true}}
   ```

   ```json
   {"cmd": "autopilotStart", "confirm": false, "config": {
     "id": "ap_breakout_alone", "name": "Breakout alone (forward control)",
     "mode": "demo", "venue": "alpaca", "assetClass": "crypto", "capitalUsd": 10000,
     "sleeves": [{"strategyId": "lab:breakout_top10", "weight": 1.0}],
     "stop": {}, "flattenOnStop": true}}
   ```

   The first answers "split as you chose it: Crypto 80 %, US shares 20 %";
   neither is ever re-picked. Together they need $20,000 of room on the paper
   account next to the running autopilots.
3. The daily forward report records both; `python -m lab.paper.equity_sleeve`
   prints the record and, from day 90, the verdict (`--reference` adds the
   backtest context).

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

## Part 1 results (generated 2026-10-21 from the engine state saved 13:35 UTC; `python -m lab.ops.autopilot_audit`)

Costs: fee and slippage against the decision price per fill (`realisedCostBps`). "vs BTC" is BTC bought and held from each start to the engine's last price; "cost share of the gap" is all costs in % of the amount over the points it trails BTC by.

### Per autopilot

| autopilot | days | amount | fills | refused | traded | turnover / day | fees | slippage | cost bps of amount / day | cost bps per unit traded | maker share | trims (< 1 %) | trim cost share | round trips (72 h) | round-trip cost share | rebalances / day | return | BTC | vs BTC | cost share of the gap |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Test · Memecoin rotation (experiment) (main) | 6.0 | 10,000 | 6 | 0 | 15,137 | 0.254 | 30.05 | 87.05 | 19.64 | 77.4 | 0.52 | 2 | 0.00 | 2 ($7,427) | 0.99 | 1.01 | -1.42 % | 3.07 % | -4.49 pts | 0.26 |
| Test · TSMOM tranches (main) | 6.0 | 10,000 | 49 | 0 | 4,273 | 0.072 | 7.59 | 5.71 | 2.23 | 31.1 | 0.72 | 39 | 0.23 | 19 ($778) | 0.37 | 1.17 | -0.01 % | 3.33 % | -3.34 pts | 0.04 |
| Test · TSMOM regime (main) | 6.0 | 10,000 | 26 | 0 | 6,277 | 0.105 | 9.77 | 1.13 | 1.83 | 17.4 | 0.94 | 1 | -0.00 | 9 ($1,777) | 0.64 | 1.01 | -0.55 % | 3.33 % | -3.88 pts | 0.03 |
| Test · BTC above 200-day (experiment) (main) | 6.0 | 10,000 | 18 | 0 | 14,690 | 0.246 | 22.99 | 0.36 | 3.92 | 15.9 | 0.94 | 1 | 0.00 | 9 ($2,330) | 0.43 | 1.17 | 0.34 % | 3.40 % | -3.05 pts | 0.08 |
| Auto-Pick (main) (main) | 6.0 | 20,000 | 80 | 0 | 11,517 | 0.097 | 18.33 | 2.75 | 1.77 | 18.3 | 0.91 | 64 | 0.56 | 51 ($4,253) | 0.75 | 1.68 | 0.48 % | 3.22 % | -2.74 pts | 0.04 |
| Safe · BTC filter momentum (autopilot-safe) | 5.8 | 95 | 0 | 5 | 0 | 0.000 | 0.00 | 0.00 | 0.00 | n/a | n/a | 0 | n/a | 0 ($0) | n/a | 0.00 | 0.00 % | 1.59 % | -1.59 pts | 0.00 |

### Rebalances a re-pick sent by itself

- Auto-Pick (main): 3 of its 10 rebalances began right after a scheduled re-pick, apart from the lab signals' own; they cost $8.37, 40 % of everything it paid.

### Maker share by UTC hour (notional)

- Test · Memecoin rotation (experiment): 04h $11,386 at 36 %, 21h $3,751 at 100 %
- Test · TSMOM tranches: 04h $4,194 at 72 %, 12h $79 at 100 %
- Test · TSMOM regime: 04h $6,277 at 94 %
- Test · BTC above 200-day (experiment): 04h $3,283 at 71 %, 12h $1,409 at 100 %, 22h $9,998 at 100 %
- Auto-Pick (main): 04h $3,313 at 85 %, 12h $8,203 at 93 %

### Refused orders

- Safe · BTC filter momentum: 5 x "authentication failed : check your keys and the paper/live endpoint (HTTP 403 on submit: a"

### Netting across autopilots, at most

- main: $51,894 traded by the running autopilots, $327 of it on opposite sides of one coin within 30 minutes; crossing it inside the engine would have saved at most $1.07.
- autopilot-safe: $0 traded by the running autopilots, $0 of it on opposite sides of one coin within 30 minutes; crossing it inside the engine would have saved at most $0.00.


## Part 2 results (`python -m lab.experiments.rebalance_band`)

### Rebalance band (panel to 2026-10-11)

**No band passes in sample for every book; the default stays at 0.2 %.**

- 2 % fails in sample: breakout_top10: cost 174 bps a year against 174; tsmom_regime: cost 229 bps a year against 242; tsmom_regime: tracking error 3.18 %; tsmom_top20: cost 148 bps a year against 158; tsmom_top20: tracking error 2.36 %; tsmom_tranches: Sharpe 1.620 against 1.841; tsmom_tranches: tracking error 3.12 %
- 1 % fails in sample: breakout_top10: cost 174 bps a year against 174; tsmom_regime: cost 228 bps a year against 242; tsmom_regime: tracking error 1.65 %; tsmom_top20: cost 148 bps a year against 158; tsmom_top20: tracking error 1.25 %; tsmom_tranches: cost 52 bps a year against 63; tsmom_tranches: Sharpe 1.755 against 1.841; tsmom_tranches: tracking error 1.67 %
- 0.5 % fails in sample: breakout_top10: cost 174 bps a year against 174; tsmom_regime: cost 233 bps a year against 242; tsmom_top20: cost 151 bps a year against 158; tsmom_tranches: cost 58 bps a year against 63; tsmom_tranches: Sharpe 1.804 against 1.841

| book | band | window | sharpe | sharpe_stress | cagr | dd | turnover_yr | cost_yr | te | max_exposure |
|---|---|---|---|---|---|---|---|---|---|---|
| breakout_top10 | baseline 0.2 % | is | 1.452 | 1.359 | 28.98 % | 11.76 % | 4.958 | 1.74 % | 0.00 % | 0.660 |
| breakout_top10 | baseline 0.2 % | oos | 1.170 | 1.042 | 18.55 % | 15.99 % | 5.757 | 2.01 % | 0.00 % | 0.633 |
| breakout_top10 | 0.5 % | is | 1.452 | 1.359 | 28.98 % | 11.76 % | 4.958 | 1.74 % | 0.00 % | 0.660 |
| breakout_top10 | 0.5 % | oos | 1.170 | 1.042 | 18.55 % | 15.99 % | 5.757 | 2.01 % | 0.00 % | 0.633 |
| breakout_top10 | 1 % | is | 1.452 | 1.359 | 28.98 % | 11.76 % | 4.958 | 1.74 % | 0.00 % | 0.660 |
| breakout_top10 | 1 % | oos | 1.170 | 1.042 | 18.55 % | 15.99 % | 5.757 | 2.01 % | 0.00 % | 0.633 |
| breakout_top10 | 2 % | is | 1.452 | 1.359 | 28.98 % | 11.76 % | 4.958 | 1.74 % | 0.00 % | 0.660 |
| breakout_top10 | 2 % | oos | 1.170 | 1.042 | 18.55 % | 15.99 % | 5.757 | 2.01 % | 0.00 % | 0.633 |
| tsmom_top20 | baseline 0.2 % | is | 1.710 | 1.530 | 15.67 % | 6.68 % | 4.512 | 1.58 % | 0.00 % | 0.413 |
| tsmom_top20 | baseline 0.2 % | oos | 0.661 | 0.431 | 5.45 % | 8.89 % | 5.649 | 1.98 % | 0.00 % | 0.381 |
| tsmom_top20 | 0.5 % | is | 1.711 | 1.544 | 16.11 % | 6.69 % | 4.315 | 1.51 % | 0.52 % | 0.423 |
| tsmom_top20 | 0.5 % | oos | 0.712 | 0.495 | 6.03 % | 8.77 % | 5.434 | 1.90 % | 0.53 % | 0.385 |
| tsmom_top20 | 1 % | is | 1.737 | 1.582 | 17.38 % | 6.47 % | 4.219 | 1.48 % | 1.25 % | 0.432 |
| tsmom_top20 | 1 % | oos | 0.695 | 0.487 | 6.06 % | 9.87 % | 5.375 | 1.88 % | 0.97 % | 0.391 |
| tsmom_top20 | 2 % | is | 1.740 | 1.599 | 19.25 % | 7.24 % | 4.222 | 1.48 % | 2.36 % | 0.462 |
| tsmom_top20 | 2 % | oos | 0.763 | 0.574 | 7.30 % | 10.10 % | 5.345 | 1.87 % | 1.91 % | 0.391 |
| tsmom_tranches | baseline 0.2 % | is | 1.841 | 1.776 | 18.56 % | 6.55 % | 1.803 | 0.63 % | 0.00 % | 0.390 |
| tsmom_tranches | baseline 0.2 % | oos | 0.719 | 0.631 | 6.54 % | 8.94 % | 2.359 | 0.83 % | 0.00 % | 0.342 |
| tsmom_tranches | 0.5 % | is | 1.804 | 1.744 | 18.50 % | 6.86 % | 1.656 | 0.58 % | 0.68 % | 0.399 |
| tsmom_tranches | 0.5 % | oos | 0.702 | 0.620 | 6.46 % | 8.84 % | 2.236 | 0.78 % | 0.52 % | 0.343 |
| tsmom_tranches | 1 % | is | 1.755 | 1.702 | 17.72 % | 7.16 % | 1.475 | 0.52 % | 1.67 % | 0.415 |
| tsmom_tranches | 1 % | oos | 0.749 | 0.677 | 6.87 % | 8.79 % | 1.955 | 0.68 % | 1.27 % | 0.343 |
| tsmom_tranches | 2 % | is | 1.620 | 1.578 | 15.15 % | 8.30 % | 1.087 | 0.38 % | 3.12 % | 0.387 |
| tsmom_tranches | 2 % | oos | 0.639 | 0.582 | 5.56 % | 8.59 % | 1.503 | 0.53 % | 2.72 % | 0.338 |
| tsmom_regime | baseline 0.2 % | is | 1.850 | 1.668 | 26.46 % | 8.05 % | 6.922 | 2.42 % | 0.00 % | 0.544 |
| tsmom_regime | baseline 0.2 % | oos | 0.738 | 0.494 | 9.29 % | 16.21 % | 9.224 | 3.23 % | 0.00 % | 0.604 |
| tsmom_regime | 0.5 % | is | 1.875 | 1.705 | 27.61 % | 8.09 % | 6.649 | 2.33 % | 0.74 % | 0.570 |
| tsmom_regime | 0.5 % | oos | 0.771 | 0.539 | 9.97 % | 16.38 % | 8.952 | 3.13 % | 0.64 % | 0.610 |
| tsmom_regime | 1 % | is | 1.910 | 1.752 | 29.80 % | 8.10 % | 6.517 | 2.28 % | 1.65 % | 0.581 |
| tsmom_regime | 1 % | oos | 0.790 | 0.571 | 10.74 % | 16.74 % | 8.908 | 3.12 % | 1.56 % | 0.622 |
| tsmom_regime | 2 % | is | 1.849 | 1.703 | 31.69 % | 9.57 % | 6.532 | 2.29 % | 3.18 % | 0.628 |
| tsmom_regime | 2 % | oos | 0.842 | 0.640 | 12.51 % | 17.25 % | 8.891 | 3.11 % | 3.02 % | 0.650 |
