# P_pool0_wait with a ratcheting profit floor (Y12): pre-registration (2026-10-23)

Written and committed before any replay below was computed. Code: `lab/pumpfun_rt/pipeline.py` (`Exits.lock`,
`_build_y12`, `Pipeline._lock`, `_lock_sell`, a branch in `check`, `sold` and `sell_failed`, the floor's fields in a
closed trade), `lab/pumpfun_rt/lock12.py` (the run), tests `tests/test_pumpfun_lock_y12.py`. Paper only: nothing
here holds a wallet, reads a key, signs or sends anything; the live service, its executor, its sizing and its
confirmation file are not touched. A change to anything below after the first result is a new trial with a new name.

## Why

The live bot trades `P_pool0_wait`: buy the PumpSwap pool at the migration, or up to 5 s later at the pool's first
trade, sell everything at +30 %, stop -20 %, time stop 300 s after the landing. The owner sees it rise +10 to +20 %,
fall back and end at the time stop or the stop. Y7's trails (P_pool0_trail, half_trail, ladder3) armed late and
lost; Y12 asks whether a ratcheting profit floor inside the same 300 s catches the way down.

## What was looked at before this plan

Disclosed: Y7's to Y11's reports and pre-registrations; the record's list of days and its last trade (2026-10-23
about 16:48 UTC); the live executor's measured file, only the latencies of its fills (P_pool0 28 buys, median
10.0 s, 28 sales, median 3.7 s: Y9's registered points; P_pool0_wait 10 buys, median 18.6 s, 9 sales, median 0.6 s,
too few to change the model, not used). The code change was checked on synthetic records in the tests and by
replaying every rule and every strategy that existed before it on the recorded 2026-10-20 with the code before and
after (section 2); only the equality was looked at, no return of any book. No variant below was replayed on the
record.

## 1. The variants

All four: family E, entry at the migration or up to 5 s later at the pool's first trade (`wait_pool_s` 5), no
filter, stake 0.1 SOL, no dev-sell, pull, trail, press, runner or risk-model exit; +30 % sells the whole position
(min_out half the expected proceeds), the -20 % stop sells it all (min_out 0), the time stop sells all 300 s after
the landing. **Until a floor fires the three are exactly P_pool0_wait.**

| book | strategy | first arm, floor | second arm, floor | at the first floor | at the second |
|---|---|---|---|---|---|
| X0 | `P_pool0_wait` (unchanged) | | | | |
| F1 | `P_pool0_wait_lock` | +10 %, +2 % | +20 %, +10 % | sell all | sell all |
| F2 | `P_pool0_wait_lock_tight` | +8 %, +3 % | +15 %, +9 % | sell all | sell all |
| F3 | `P_pool0_wait_lock_half` | +10 %, +2 % | +20 %, +10 % | sell half | sell the rest |

`Exits.lock = ((arm, floor, cumulative share sold), ...)`, arms rising: F1 ((0.10, 0.02, 1.0), (0.20, 0.10, 1.0)),
F2 ((0.08, 0.03, 1.0), (0.15, 0.09, 1.0)), F3 ((0.10, 0.02, 0.5), (0.20, 0.10, 1.0)); `None`, the default, changes
nothing.

- **The mark** is the measure the stop and the take profit already use: what selling the tokens still held would
  bring now after the pool's fee, over their share of the buy's cost (the transaction fees not in it), checked on
  every trade of the token while no sale is in flight. **The peak** is the highest mark since the landing (the
  pipeline's `peak`).
- **The floor**: the highest arm the peak has reached decides; a mark at or under its floor sells down to its share,
  min_out 0, as every protective exit. Checked after the -20 % stop (a fall through both in one trade is a stop) and
  before the take profit. A whole sale is a protective exit (`lock`): if it fails it is sent again at once. F3's
  half (`lock_part`, half the tokens bought, rounded down) is sent again at once too if it fails; the rest keeps
  every exit (+30 %, -20 %, the time stop, the second floor). The first floor never sells twice. If F3's second arm
  is reached before its first floor fired, its floor (+10 %) sells everything.
- **Fields**: a closed trade where a floor fired carries `lock_ms` (the first floor's signal), `lock_sales` and
  `peak`; no other trade gains a field.

## 2. Code changes and the equality check

`Exits.lock`, `_build_y12`, `Pipeline._lock`, `_lock_sell`, one line each in `check`, `sold`, `sell_failed`, `_close`,
`strategies.LOCK_Y12_TRIALS`. The 35 strategies before Y12 and the 22 rules were replayed in one shared paper book
with the label book, the select and trend trackers and the server's models on the recorded 2026-10-20, with the code
before the change and after it (the new books in the same book): 18,573 closed trades and 1,028 failed buys,
identical field for field (the pid aside, as Y9 to Y11), the 93 skip counts too. Printed besides the equality: the
new books' 134 closed trades that day, 31 of them with a floor; no return. The tests do the same on a synthetic
record.

## 3. Record, latency, costs, limits

- **Record**: every recorded day from the record's start (2026-10-20) up to the cutoff **2026-10-23 16:00 UTC** (the
  last complete UTC hour at registration). Entries until 15 minutes before the cutoff (a hold is at most 300 s plus
  the 5 s wait and a buy and a sale of at most 60 s each), so every position closes inside the record. The split is
  Y5's to Y11's: the middle of the record's time span; out of sample after it (by signal time). Nothing is fitted;
  the in-sample half is only reported.
- **Latency, two models, both judged**: **A**, the paper engine's own (`curve.Costs`: lognormal, median 1 s, 0.4 to
  3 s, the model every paper book trades on); **B**, the measured live latency, Y9's (Y5's kernel density in log space
  on the live executor's 28 P_pool0 buys and 28 sales since the Sender path, buy median about 10 s from signal to
  landing, sale about 4 s), as Y10 and Y11. Same failure model as the paper books (`PaperExecutor`).
- **Fee**: 0.001005 SOL per transaction (F3 pays one more when it sells twice); a failed buy pays it.
- **Draws**: every book draws with P_pool0's key (mint, leg): a migration's buy lands at the same moment in all four
  books of one latency.
- **Limits**: at most 4 positions, exposure cap 0.6 SOL, under two daily loss limits, both judged: **L25, 0.25 SOL**
  (the live bot's) and **L100, 1.0 SOL** (the code's cap), as Y9 to Y11.
- **Gapped trades** kept (Y8's rule); with them left out is a robustness line.

## 4. Reported, per book, latency and limit (out of sample)

Entries (closed trades plus failed buys), the hours they fall in, mean and median return per entry over the stake
after every cost, win rate, total P&L in SOL, the hour-block 90 % band of the mean, the maximum drawdown, the exits,
the skips. For F1 to F3: **the share of closed trades where a floor fired**, their mean and P&L, and **what those
trades did without it**: X0's trade on the same migration (same latency and limit, paired by mint and signal), its
mean, its P&L, its exits, and the share where the floor did better. F1 to F3 against X0: the difference of the means
with its band, the P&L difference, and on the migrations both entered (not judged). The effect of the latency: every
number at A and at B side by side. The in-sample half.

## 5. Verdict

Y8's rule, per latency and limit: F1 (F2, F3) is **better than X0** (out of sample, gapped trades kept) only if both
hold:

1. the difference of its mean return per entry against X0's has an hour-block bootstrap 90 % band above zero
   (`study.boot_diff`, 5,000 draws, the same hours drawn for both, each book's mean over all its own entries, failed
   buys included); with fewer than 10 hours of entries in either book the band is n/a and the answer is no;
2. its total P&L is higher.

A variant **beats P_pool0_wait at a latency** only if it is better than X0 under both limits at that latency; the
answer for the live bot is the one at **B**. Every book is reported, whatever the answer. **Trials**: three books,
two limits, two latencies, `strategies.LOCK_Y12_TRIALS = 12`, added to `strategies.N_TRIALS`.

## 6. Paper forward test

F1 to F3 join `pipeline.STRATEGIES` (`_build_y12`), 0.1 SOL each, and run in the paper engine from the deploy on, at
least two weeks before anything about the live bot is decided, whatever this replay says. Nothing goes live: the
live executor trades the strategy its confirmation file names, and moving the live book to a variant is the owner's
decision.

## 7. Too early

About three and a half days of record, out of sample under two days, under the 0.25 SOL limit a few hours per book
(Y11: 4 or 5 entries). The verdict says what this record shows; the paper books are where the evidence has to come
from.
