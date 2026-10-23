# P_pool0_wait with a free ride after a fast spike (Y15): pre-registration (2026-10-23)

Written and committed before any replay below was computed. Code: `lab/pumpfun_rt/pipeline.py` (`Exits.free`,
`_build_y15`, `Pipeline._free`, `_free_start`, `_free_mark`, `_free_check`, `_free_end`, a branch in `check`, `sold`,
`sell_failed`, `_time_stop`, the free ride's fields in a closed trade), `lab/pumpfun_rt/free15.py` (the run), tests
`tests/test_pumpfun_freeride_y15.py`. Paper only: nothing here holds a wallet, reads a key, signs or sends anything;
the live service, its executor, its sizing and its confirmation file are not touched. A change to anything below
after the first result is a new trial with a new name.

## Why

The live bot trades `P_pool0_wait`: buy the PumpSwap pool at the migration, or up to 5 s later at the pool's first
trade, sell everything at +30 %, stop -20 %, time stop 300 s after the landing. The owner wants: when a coin shoots
through +30 % fast, sell only what brings the stake and the fees back, let the rest ride at no risk to the stake and
sell it as soon as it turns down. Earlier runner exits lost (Y7 P_pool0_half_trail -9.9 % per entry, Y11's rests
after the time stop lost 94 % when stopped at our latency), but they did not condition on the speed of the rise and
did not free the stake first: Y15's rest starts in profit with the stake already back.

## What was looked at before this plan

Disclosed: Y7's to Y12's reports and pre-registrations; the record's list of days (2026-10-20 to 2026-10-23); the
measured live latency as Y9 to Y12 registered it (buy median about 10 s from signal to landing, sale about 4 s). The
code change was checked on synthetic records in the tests and by replaying every rule and every strategy that existed
before it on the recorded 2026-10-20 with the code before and after (section 2); only the equality and the count of
the new books' trades were looked at, no return of any book. No variant below was replayed on the record.

## 1. The variants

All four: family E, entry at the migration or up to 5 s later at the pool's first trade (`wait_pool_s` 5), no
filter, stake 0.1 SOL, no dev-sell, pull, trail, press, runner, lock or risk-model exit. **Until the mark first
reaches +30 % the four are exactly P_pool0_wait** (the -20 % stop sells all, min_out 0; the time stop sells all 300 s
after the landing).

| book | strategy | +30 % first reached within | the rest's trail under its high | hard stop |
|---|---|---|---|---|
| X0 | `P_pool0_wait` (unchanged) | | | |
| V10 | `P_pool0_wait_free10` | 10 s of the landing | 20 % | 30 min after the landing |
| V30 | `P_pool0_wait_free30` | 30 s | 20 % | 30 min |
| VA | `P_pool0_wait_free_any` | any time (no speed condition) | 20 % | 30 min |
| V10T | `P_pool0_wait_free10_tight` | 10 s | 10 % | 30 min |

`Exits.free = (window s or None, trail gap, hard stop s)`: V10 (10, 0.20, 1800), V30 (30, 0.20, 1800), VA (None,
0.20, 1800), V10T (10, 0.10, 1800); `None`, the default, changes nothing.

- **The mark** is the measure the stop and the take profit already use: what selling the tokens still held would
  bring now after the pool's fee, over their share of the buy's cost (the transaction fees not in it), checked on
  every trade of the token while no sale is in flight.
- **The spike rule**: the first check that sees the mark at or over +30 % notes its time. If that is at most the
  window after the landing, the take profit sells only the share whose expected proceeds (the mark's value, pro rata)
  bring back the buy's cost, the buy's fee and this sale's fee (about 78 % of the tokens at exactly +30 %, rounded
  up), with P_pool0_wait's take profit min_out (half the expected). If it is later, the take profit sells all as
  P_pool0_wait does. The first time decides for good: a failed partial sale leaves the +30 % due, as a failed take,
  and the next check over +30 % sends the partial sale again whatever the time.
- **The rest**, from the partial sale's landing: its high counts from the partial sale's signal (marks of the
  tokens that will remain, also while the sale is in flight); it is sold all (min_out 0, sent again at once if it
  fails, as every protective exit) when its mark is at or under its high less the trail gap (`free_trail`), or at or
  under the partial sale's own price over the entry's price, both after the pool's fee (`free_floor`; checked
  first), or 30 min after the landing (`free_time`). The -20 % stop, the +30 % and the 300 s time stop no longer
  apply to it; a 300 s time stop that came due while the partial sale was in flight is dropped when it lands.
- **Fields**: a closed trade of a Y15 book where the +30 % was seen carries `free_first_s` (seconds from the landing);
  where the partial sale landed also `free_ms`, `free_part_sol` (its proceeds less its fee), `free_floor`,
  `free_high`, `rest_cost_sol`, `rest_pnl_sol` (the rest's proceeds less its fees and its share of the cost) and
  `rest_vs_take_sol` (the same against selling the rest at the partial sale's price per token). No other trade gains
  a field.

## 2. Code changes and the equality check

`Exits.free`, `_build_y15`, the `_free*` methods, one branch each in `check`, `sold`, `sell_failed`, `_time_stop`,
`_close`, `strategies.FREE_Y15_TRIALS`. The 38 strategies before Y15 and the 22 rules were replayed in one shared
paper book with the label book, the select and trend trackers and the server's models on the recorded 2026-10-20,
with the code before the change and after it (the new books in the same book): 18,707 closed trades and
1,036 failed buys, identical field for field (the pid aside, as Y9 to Y12), the 99 skip counts too. Printed besides
the equality: the new books' 160 closed trades that day, the +30 % seen in 75 of them, a partial sale in 36; no
return. The tests do the same on a synthetic record.

## 3. Record, latency, costs, limits

- **Record**: every recorded day from the record's start (2026-10-20) up to the cutoff **2026-10-23 17:00 UTC** (the
  last complete UTC hour at registration). Entries until 35 minutes before the cutoff (a rest is held at most 30 min
  after the landing, plus the 5 s wait and a buy and a sale of at most 60 s each), so every position closes inside
  the record. The split is Y5's to Y12's: the middle of the record's time span; out of sample after it (by signal
  time). Nothing is fitted; the in-sample half is only reported.
- **Latency, two models, both judged**: **A**, the paper engine's own (`curve.Costs`: lognormal, median 1 s, 0.4 to
  3 s); **B**, the measured live latency, Y9's (the live executor's Sender fills, buy median about 10 s from signal to
  landing, sale about 4 s: exits land later than they are decided), as Y10 to Y12. Same failure model as the paper
  books (`PaperExecutor`).
- **Fee**: 0.001005 SOL per transaction (a free ride pays one more, its second sale); a failed buy pays it.
- **Draws**: every book draws with P_pool0's key (mint, leg): a migration's buy lands at the same moment in all five
  books of one latency.
- **Limits**: at most 4 positions, exposure cap 0.6 SOL, under two daily loss limits, both judged: **L25, 0.25 SOL**
  (the live bot's) and **L100, 1.0 SOL** (the code's cap). A rest holds its slot and its share of the cost in the
  exposure until it is sold.
- **Gapped trades** kept (Y8's rule); with them left out is a robustness line.

## 4. Reported, per book, latency and limit (out of sample)

Entries (closed trades plus failed buys), the hours they fall in, mean and median return per entry over the stake
after every cost, win rate, total P&L in SOL, the hour-block 90 % band of the mean, the maximum drawdown, the exits,
the skips. For V10 to V10T: how often the +30 % was seen and its median time after the landing, **how often the spike
rule fired** (share of the closed trades), **what the rests made** over their cost (median, best, worst, share above
zero, P&L in SOL), **what the rests gave up** against selling them with the partial sale (sum of `rest_vs_take_sol`,
share above zero), and the whole trades against X0's trade on the same migration (X0 sold all at +30 % there: its
mean, its P&L, the share where the free ride did better). Each variant against X0: the difference of the means with
its band, the P&L difference, and on the migrations both entered (not judged). Every number at A and at B side by
side. The in-sample half.

## 5. Verdict

Y8's rule, per latency and limit: a variant is **better than X0** (out of sample, gapped trades kept) only if both
hold:

1. the difference of its mean return per entry against X0's has an hour-block bootstrap 90 % band above zero
   (`study.boot_diff`, 5,000 draws, the same hours drawn for both, each book's mean over all its own entries, failed
   buys included); with fewer than 10 hours of entries in either book the band is n/a and the answer is no;
2. its total P&L is higher.

A variant **beats P_pool0_wait at a latency** only if it is better than X0 under both limits at that latency; the
answer for the live bot is the one at **B**. Every book is reported, whatever the answer. **Trials**: four books, two
limits, two latencies, `strategies.FREE_Y15_TRIALS = 16`, added to `strategies.N_TRIALS`.

## 6. Paper forward test

V10 to V10T join `pipeline.STRATEGIES` (`_build_y15`), 0.1 SOL each, and run in the paper engine from the deploy on,
at least two weeks before anything about the live bot is decided, whatever this replay says. Nothing goes live: the
live executor trades the strategy its confirmation file names, and moving the live book to a variant is the owner's
decision.

## 7. Too early

About three and a half days of record, out of sample under two days, under the 0.25 SOL limit a few hours per book
(Y11, Y12: 4 or 5 entries). A spike to +30 % within 10 s is a fraction of the take profits; the rests will be few.
The verdict says what this record shows; the paper books are where the evidence has to come from.
