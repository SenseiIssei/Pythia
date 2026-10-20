# Forward record audit (2026-10-20)

Do the paper books trade their own backtests, and does every figure the
forward reports print add up? Pre-registered in `forward_audit_prereg.md`
before any number below was computed; the numbers are in
`forward_audit_run.md` (`python -m lab.paper.forward_audit`, run on the data
mirror as of 2026-10-20, 23:10 UTC). No Sharpe trial, nothing added to the pool.

## Verdict

| Book | 1. coin-days off the backtest | 2. percentile of the forward return (35 bps) | Rule |
|---|---|---|---|
| tsmom | 0 of 225 | 2nd (forward -6.27 %, the backtest on the same days -6.79 %) | fails the pass rule, not the kill rule |
| tsmom_regime | 0 of 205 | 3rd (-4.54 %, backtest -6.26 %) | fails the pass rule, not the kill rule |
| tsmom_top20 | 0 of 222 | 4th (-4.37 %, backtest -6.79 %) | fails the pass rule, not the kill rule |
| breakout_top10 | **3 of 15 (20 %)** | 34th (-0.81 %, backtest -2.18 %) | **kill rule: record frozen through 2026-10-20** |
| tsmom_tranches | 0 of 166 | 11th (-2.00 %, backtest -1.02 %) | passes |
| memes_rotation | 0 of 4 | 19th (-1.09 %, backtest -0.98 %) | passes |
| memes_tsmom | 0 of 11 | 21st (-0.49 %, backtest -0.58 %) | passes |
| m4_ls, picks_ls, picks_ls_v2, trend4h_pullback | not replayed (below) | | no verdict |
| pumpfun_migration, pumpfun_filtered, pumpfun_filtered_quick | no backtest signal exists | | figures only (check 4) |

3. Realised cost: 178 filled autopilot orders (2026-10-15 to 2026-10-20, all
lab books), median **1.2 bps** against the arrival price, 90th percentile 30
bps. Under the 10 bps the 35 bps base assumes: passes; the base stays.

4. Every impossible figure the draft names is traced below, and each has a
fix committed with a test.

Read the three momentum books with the draft's own warning: 13 to 14 days
carry almost no information, and the backtest run over the same days lost as
much or more (-6.3 to -6.8 %). The books track their rule; the rule had two
bad weeks. They fail the pass rule and keep running; nothing about them is
invalid.

## 1. Signal reconciliation

Every journal row against what the book's own weight function and simulator
(`families.targets` with `alpaca_universe.simulate`, `tsmom.target_weights`,
`memecoins.rotation` and `trend`) hold after the decision close before the
run, rerun from the history files. Six books match on every coin-day.

**breakout_top10**: the first two runs (2026-10-07, 2026-10-08) held NEAR at
0.0329 and SUI at 0.0420 where the backtest held 0.0512 and 0.0564. Cause in
`lab.paper.families`: a new book was started from `held_now`, each coin's
weight on its entry day, while breakout positions drift after entry and the
backtest (and the engine signal, `backtest_weights`) holds the drifted weight.
NEAR had risen about 55 % since its entry, so the book started a third light
on it. From 2026-10-09 on the book matches the backtest exactly.

- Fix: every families book starts from `backtest_weights` (the drifted
  weights); `held_now` is gone. Test:
  `test_a_new_breakout_book_starts_with_the_weights_the_backtest_holds_not_its_entry_weights`.
- Kill rule: 3 of 15 coin-days is 20 %, past the 5 % line, so the record is
  frozen. `forward_report.FROZEN` holds it through 2026-10-20: those 14 days
  count toward no forward gate and no readiness rule, and the fresh record
  starts with the run of 2026-10-21, measured from the equity at the cut
  (`fresh_record`; the report and `evidence.json` say so, with the reason).

Not replayed, as the pre-registration allows:

- `m4_ls`: M4 is retrained weekly on the server against the perps that trade
  at run time; the mirror keeps only the newest model.
- `picks_ls`, `picks_ls_v2`: M2 is retrained on all history at each
  rebalance against the live perp list; neither is kept as of those days.
- `trend4h_pullback`: hourly decisions filled as resting limits on live 1h
  bars; its own `trades.csv` is the record and the study's fill model the
  backtest, with no daily target to compare.

## 2. Percentile

The paper books trade the whole universe at Binance quotes, so each is placed
among its own rule's out-of-sample windows on that universe (from 2024-01-01
to the day before its record started), at 35 and 70 bps. The draft asked for
the Alpaca cash-left variants; those are what the autopilots run, not what
these journals hold, and the pre-registration says so. No book is below the
1st percentile; the three momentum books sit between the 2nd and 4th.

## 3. Realised cost

From every engine state backup on the mirror, each filled autopilot order
once. The engine's `realisedSlippageBps` is the fill against the arrival
price, positive when it cost. Per coin the medians run from -0.4 bps (BCH) to
11 bps (DOT, AAVE); BTC and SOL fill at the touch. The maker route keeps most
fills inside the spread; the 90th percentile of 30 bps is the fallbacks that
crossed. Fees are not in these numbers. The engine keeps only recent orders,
so the sample starts 2026-10-15.

## 4. The impossible figures

### pumpfun_migration at -965 % (-1,096.6 % by 2026-10-20)

A long-only book cannot lose more than it has. Three faults in
`lab.paper.pumpfun`:

1. **No cash check.** Every graduation bought $100 whatever the book held.
   Cash went to -$108,059, so "equity" was $10,000 plus the dollar result of
   every trade: a sum of per-trade results presented as a book return.
2. **Tokens bought more than once.** A graduation can show up as several
   PumpSwap pools in one run; each pool was a buy. 395 of the 1,789
   migration buys (22 %) were a second to fourth buy of a token the rule
   already held.
3. **Exposure divided by a near-zero or negative equity** (4.5e12 in the journal).

Fix: a rule buys a token once; a buy without the $100 stake in cash is
followed as an **unfunded** position (its marks, exit and return are kept, so
the per-token record the study exists for stays complete) but moves no cash
and is not in the book's equity; exposure is 0 for an empty book. The report
shows the book (equity against $10,000) and the trades (each against its own
$100) apart. `python -m lab.paper.pumpfun --rebuild` replays the ledger under
these rules and rewrites the journals and the state; on the mirror's ledger
it gives:

| | before | after the rebuild |
|---|---|---|
| migration book on 2026-10-20 | -$99,657 (-1,096.6 %) | $54.55 (-99.5 %), out of cash from 2026-10-18 |
| tokens funded | 1,789 buys | 183 of 1,394 tokens |
| per trade, every token once | | 1,369 closed: mean -64.9 %, median -96.4 %, 9.6 % winners, 58 % at -90 % or worse |
| filtered, filtered_quick | -1.73 %, +0.06 % | unchanged (two trades each, never short of cash) |

The migration rule, as registered, would have emptied a $10,000 book in two
and a half days. Tests: `test_a_token_is_bought_once_however_many_pools_a_run_sees`,
`test_a_book_without_the_stake_follows_the_token_unfunded_and_never_goes_below_zero`,
`test_replay_keeps_one_buy_per_token_and_only_spends_the_cash_the_book_has`.

### ap_29742: worst drawdown 81.91 %, -10.0 % in 3 days, fees 0.73 %

ap_29742 started on 2026-10-12 with $99,500. On 2026-10-15 at 12:30 and
12:32 UTC its amount was cut to about $50,000 and then $20,000, and it was
stopped at 12:33. The rescale of the curve on an amount change
(`autopilot_update`) was committed at 12:36, so its saved curve still held
$99,500 to $97,612 and then $48,117 and $18,001 a minute apart. All three
figures are that one cut:

- **81.91 %** is the fall from the $99,500 point to $18,001: two amount
  changes, not a loss.
- **-10.0 %** (-9.95 %) is the -$1,966 it lost on about $99,500 over the new
  amount of $20,000. On the amount it worked with it is **-1.98 %** (BTC over
  the same window: -1.61 %).
- **0.73 %** is $145.67 of fees over $20,000; on the amount it worked with it
  is **0.15 %**. It is still above the 0.05 % of the running autopilots
  because it built a $34,441 book with 11 market orders at the 25 bps taker
  fee before the maker route existed ($85.36 in its first 41 minutes), and the
  others hold 20 to 50 %
  of $10,000 to $20,000 filled mostly as maker.

Fix in the engine: each autopilot keeps an amount log (`capital_log`) and
reports the time-weighted amount it worked with (`avgCapital`); the forward
report and the Autopilot page's comparison measure return and fees on it, and
read a rescaled curve from its own first point. A save from before the log is
repaired once at the restore (`repair_curve`): a step of more than 25 % between
points minutes apart is an amount change, the curve before it is scaled by
the step (as the rescale does today), and the earlier amounts are estimated
from the steps ($99,487, $49,992, $20,000). Points at the start above the peak
the engine keeps are an earlier amount too (ap_test_breakout_top10 began at
$11,000 and was cut to $10,000 the same way: 10.79 % read as a drawdown). The
status carries a `curveNote` that says what was done; the comparison marks the
drawdown with it. On the mirror's state the repair gives ap_29742 a worst
drawdown of **2.15 %** and ap_test_breakout_top10 **1.87 %**; no other
autopilot changes. Tests: `a_curve_saved_before_amounts_rescaled_it_is_repaired_from_its_steps`,
`a_first_point_on_an_earlier_amount_is_brought_to_the_current_one`,
`an_old_save_gets_its_curve_repaired_once_and_says_so`,
`a_return_and_a_fee_share_are_measured_on_the_amount_it_worked_with`, and the
forward report and compare tests.

### "15 real position(s) could not be closed" on a demo autopilot

`ap_halt` sorted positions it could not close into three bins: at the venue,
waiting for a fresh price, and everything else, which it called "real
positions ... live routing is not available". A demo position never needs
live routing: it closes on the demo route, and when its exit does not go out
it waits for something on that route. ap_29742 was stopped two to three
minutes after four test autopilots started buying the same coins on the same
paper account, and a demo exit next to another book's working buy in the
same symbol waits (Alpaca refuses two orders of one account that could meet
as a wash trade). The journal of those minutes is gone: `close_position` wrote
"Exit ... stopped" at every tick for every waiting close whether or not an
order went out (476 times each for XRP and AVAX in ten minutes), which pushed
everything else out of the 1,000-line journal.

Fix: a position still open after the stop is now classed by what holds it:
live routing (real positions only), another book's order in the symbol, a
refusal being waited out, or a retry at the next tick, each with its own
sentence in English and German. `close_position` claims an exit only when an
order went out or the position moved. Test: the wash-trade case in
`an_order_of_another_book_on_the_other_side_of_the_symbol_waits_for_it` now
checks the sentence and that no "Exit" is written while it waits.

### "after 13 days since 2026-10-17" on 2026-10-20

`lab.ai.weekly.evidence_lines` (the research director's and the weekly
review's input) wrote the status, the return, the record's length and the
date the status last changed in one run of words. tsmom_regime's record
started 2026-10-07 (13 days by 2026-10-20) and turned "below" on 2026-10-17.
Neither number was wrong; the sentence was. It now reads
"book:tsmom_regime: below since 2026-10-17 (forward record -4.5 % over 13 days)".
Test: `test_an_evidence_line_keeps_the_status_date_apart_from_the_records_length`.

### The repeated venue quantity corrections

Several autopilots share one Alpaca paper account, and Alpaca keeps a buy's
fee in the coin bought. The paper reconcile compares Alpaca's quantity with
the sum over every book. When the sum was short, `take_alpaca_fee_gap` split
the gap over every buy still waiting for its posted fee, in proportion to its
size, including buys of books that had since sold everything. A share
charged to a book that holds nothing moves no position and left the main
book's cash, so ten minutes later the same gap was found again, a little
smaller, and booked again as a fee (PEPE on 2026-10-18: 60,300, 51,431,
43,866, ... coins, every ten minutes for hours). Every round was a fee: the
fees of ap_29614, stopped on 2026-10-12 after five minutes of trading, stood
at $8.68 until 2026-10-15 and at $84.11 on 2026-10-20 (0.84 % of its
$10,000). When Alpaca posted the fee a day later, the books that had
absorbed other books' shares had their own buys' coins taken a second time
(46 of 138 postings took coins "from the position now"), and the next
reconcile corrected them back up: 69 corrections, every one with the venue
holding more than the book. Each correction also set every book's entry
price to Alpaca's account-wide average, moving open P&L from one autopilot to
another (+$6.34 and -$6.34 on FIL on 2026-10-16).

Fix: a gap in the account's sum is taken only from buys whose book still
holds the coin, no more than that book holds, newest buy first (the venue
takes a buy's fee from the coins it credits, so the gap the reconcile finds
is the fee of the buys since the last one), in one pass; a correction of
several books keeps each book's own entry price. Tests:
`a_shared_fee_gap_is_taken_once_from_the_newest_buy_of_a_book_that_holds_the_coin`
(three runs later: no second fee, no correction),
`a_fee_gap_bigger_than_what_the_holders_can_owe_is_a_correction_once`,
`books_that_share_a_pair_keep_their_own_entry_price_when_corrected`.

Left as it is: when one book sells its whole position before a reconcile and
another book holds the same coin, the account sells the first book's fee
coins out of the second book's holding. The posting then charges the first
book, and the second is corrected once. Rare, and booked once, not in a loop.

## After the deploy

- The engine repairs the two curves and starts the amount logs at its next
  start, and says so in the journal.
- Run `python -m lab.paper.pumpfun --rebuild` once on the server; the
  watcher then keeps the books under the new rules.
- The forward report treats breakout_top10's record through 2026-10-20 as
  frozen from its next run.
- `python -m lab.paper.forward_audit` reruns checks 1 to 3 at any time.

## What could fool us

Two weeks of forward data say almost nothing about a rule, and all of these
books are long BTC-led crypto. Matching coin-days show that a book holds what
its code says, not that the code makes money. The slippage sample is five
days of paper fills simulated against Alpaca's quotes, which can look cheaper
than real fills.
