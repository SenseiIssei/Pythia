# P_pool0_wait with a 20 % rest after the time stop (Y11): pre-registration (2026-10-23)

Written and committed before any replay below was computed. Code: `lab/pumpfun_rt/pipeline.py` (`Exits.runner`,
`_build_y11`, the pipeline's time stop and the rest's exits), `lab/pumpfun_rt/runner11.py` (the run, on Y9's books
and Y7's peak book), tests `tests/test_pumpfun_runner_y11.py`. Paper only: nothing here holds a wallet, reads a key,
signs or sends anything; the live service, its executor, its sizing and its confirmation file are not touched, and
the live executor's files are only read. A change to anything below after the first result is a new trial with a
new name.

## Why

The live bot trades `P_pool0_wait` (Y8's X3): buy the PumpSwap pool at the migration, or up to 5 s later at the
pool's first trade, sell everything at +30 %, stop -20 %, time stop 300 s after the landing. The owner saw coins pump
right after that time stop. Y11 asks whether keeping a small rest past the time stop pays.

## What was looked at before this plan

Disclosed: Y7's, Y8's, Y9's and Y10's reports and pre-registrations; the live executor's measured file, only the
number of fills per strategy since the Sender path (P_pool0 28 buys and 28 sales, Y9's points; P_pool0_wait 2 and
2); the record's list of days and its last trade (2026-10-23 about 15:25 UTC). The code change was checked on
synthetic records in the tests and by replaying every rule and every strategy that existed before it, in one shared
paper book with the label book, the select and trend trackers and the server's models, on the recorded 2026-10-20
with the code before the change and after it (section 2); only the equality was looked at, no return of any book.
No variant below was replayed on the record.

## 1. The variants

All three: family E, entry at the migration or up to 5 s later at the pool's first trade (`wait_pool_s` 5, Y8), no
filter, stake 0.1 SOL, no dev-sell, pull, trail, press or risk-model exit. **Until the time stop all three are
exactly P_pool0_wait**: +30 % sells the whole position in one sale (min_out half the expected proceeds), the -20 %
stop sells it all (min_out 0), each checked on every trade of the token as the pipeline always does.

| book | strategy | at the time stop (300 s after the landing) | the rest's stop | the rest's trail | hard stop |
|---|---|---|---|---|---|
| X0 | `P_pool0_wait` (unchanged) | sell everything | | | |
| R1 | `P_pool0_wait_run20` | sell 80 %, keep 20 % | -50 % | 30 % under its high | 30 min |
| R2 | `P_pool0_wait_run20w` | sell 80 %, keep 20 % | -70 % | 40 % under its high | 60 min |

`Exits.runner = (share kept, stop under the entry, fall from the high, hard stop s)`: R1 (0.20, 0.50, 0.30, 1800),
R2 (0.20, 0.70, 0.40, 3600); `None`, the default, changes nothing.

- **The time stop**: at landing + 300 s, if the position is still fully open, a sale of all but 20 % of the tokens
  bought (rounded down) is sent with min_out 0, as every protective exit; it lands one latency draw later at what
  the pool then pays. If that sale fails it is sent again at once. If the take-profit sale is in flight at the
  time stop, the time stop comes due when it is back, as for P_pool0_wait.
- **The rest** from then on has only its own exits (the +30 % and the -20 % no longer apply), checked on every trade
  of the token once the 80 % sale has landed. Its value is what selling the rest would bring now after the pool's
  fee, over its share of the buy's cost (the measure P_pool0_wait's stop uses). **Stop**: the value at or under
  1 - stop (R1 0.50, R2 0.30) sells the rest. **Trail**: the high is the highest value since the time stop (the
  value at the time stop, then every trade, also while the 80 % sale is in flight); once the high is above 1 (the
  rest was above its cost), a value at or under the high x (1 - fall) sells the rest. **Hard stop**: at landing +
  1800 s (R1) or + 3600 s (R2) the rest is sold whatever its value; with a sale in flight it is sent when that sale
  is back. Every sale of the rest is min_out 0. The kill switch sells the rest as anything else.
- **Slots and limits**: the rest keeps its position's slot (at most 4 per book) and the position's whole cost stays
  in the book's exposure until the rest is sold, as Y7's half-and-trail and as the live pipeline would do. A runner
  therefore can take fewer entries than X0; the skips are counted and reported.

## 2. Code changes and the equality check

`Exits.runner`, `Pipeline._time_exit` (the time stop, all or all but the rest), `_run_sell`, `_run_mark`,
`_run_check`, `_run_end`, a branch in `Pipeline.check` and in `sell_failed`, the rest's own fields in a closed trade
(only for a position that kept a rest: `run_from_ms`, `run_high`, `run_cost_sol`, `run_pnl_sol`, `run_vs_time_sol`),
`_build_y11`, `strategies.RUNNER_Y11_TRIALS`. The 33 strategies before Y11 and the 22 rules were replayed in one
shared paper book on the recorded 2026-10-20 with the code before the change and after it (18,498 closed trades and
1,022 failed buys): identical field for field (the pid aside, as Y9 and Y10), the skip counts too. The tests do the
same on a synthetic record.

## 3. Record, latency, costs, limits

- **Record**: every recorded day from the record's start (2026-10-20) up to the cutoff **2026-10-23 15:00 UTC** (the
  last complete UTC hour at registration). Entries until 75 minutes before the cutoff (a hold is at most 60 minutes
  plus the 5 s wait and a buy and a sale of at most 60 s each), so every position closes inside the record. The split
  is Y5's to Y8's: the middle of the record's time span; out of sample after it (by signal time). Nothing is fitted;
  the in-sample half is only reported.
- **Latency (measured)**: Y9's (Y5's kernel density in log space on the live executor's 28 P_pool0 buys and 28
  sales since the Sender path, `select9.SENDER_BUY_MS`, `SENDER_SELL_MS`), as Y10. P_pool0_wait's own 2 fills since
  are not added: too few to change the model, and Y10's and Y11's books stay on the same latency.
- **Fee**: 0.001005 SOL per transaction (a runner pays one more, for the rest's sale); a failed buy pays it.
- **Draws**: every book draws with P_pool0's key (mint, leg): a migration's buy lands at the same moment in all
  three books, the 80 % sale at the same moment as X0's time-stop sale, the rest's sale with its own draw (leg 1).
- **Limits**: at most 4 positions, exposure cap 0.6 SOL, under two daily loss limits, both judged: **L25, 0.25 SOL**
  (the live bot's) and **L100, 1.0 SOL** (the code's cap), as Y9 and Y10.
- **Gapped trades** kept (Y8's rule); with them left out is a robustness line. A 30 or 60 minute hold crosses more
  of the record's short gaps than X0's 5 minutes, so dropping them would select differently per book.

## 4. Reported, per book and limit (out of sample)

Entries (closed trades plus failed buys), the hours they fall in, mean and median return per entry over the stake
after every cost, win rate, total P&L in SOL, the hour-block 90 % band of the mean, the maximum drawdown, the exits,
the skips (max open positions, daily loss limit). For the rests of R1 and R2 (the entries that reached the time stop
and kept 20 %): how many; **the share whose rest made money** (the rest's sale proceeds after its own sale fee above
its share of the buy's cost); the share that beat selling the rest with the 80 % (the 80 % sale's proceeds pro rata,
so the rest's own fee counts against it); the rests' P&L in SOL and what they added against that sale; **the worst
rest loss** in SOL and over its cost; the best rest; the rests' exits. R1 and R2 against X0: the difference of the
means with its band, the P&L difference, and on the migrations both entered (not judged). The in-sample half.

## 5. Verdict

Y8's rule, per limit: R1 (R2) is **better than X0** (out of sample, gapped trades kept) only if both hold:

1. the difference of its mean return per entry against X0's has an hour-block bootstrap 90 % band above zero
   (`study.boot_diff`, 5,000 draws, the same hours drawn for both, each book's mean over all its own entries, failed
   buys included); with fewer than 10 hours of entries in either book the band is n/a and the answer is no;
2. its total P&L is higher.

A variant **beats P_pool0_wait** only if it is better than X0 under both limits. Every book is reported, whatever the
answer. **Trials**: two books under two limits, `strategies.RUNNER_Y11_TRIALS = 4`, added to `strategies.N_TRIALS`.

## 6. Paper forward test

R1 and R2 join `pipeline.STRATEGIES` (`_build_y11`), 0.1 SOL each, and run in the paper engine from the deploy on.
They run there **at least two weeks** before anything about the live bot is decided, whatever this replay says.
Nothing goes live: the live executor trades the strategy its confirmation file names, and moving the live book to
a variant is the owner's decision.

## 7. Too early

About three days of record, out of sample about a day and a half, under the 0.25 SOL limit a few hours per book; the
rest is 20 % of 0.1 SOL, so a rest moves a trade by at most a few hundredths of a SOL. The verdict says what this
record shows; the paper books are where the evidence has to come from.
