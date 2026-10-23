# P_pool0's exits for runners (Y7): pre-registration (2026-10-23)

Written and committed before any replay below was computed. Code:
`lab/pumpfun_rt/exitlab.py` (the run), `lab/pumpfun_rt/pipeline.py`
(`_build_y7`, `Exits.time_after_step_s`), tests
`tests/test_pumpfun_exit_runners.py`. Paper only: nothing here holds a
wallet, reads a key, signs or sends anything; the live service, its executor
and its confirmation file are not touched, and the live executor's files are
only read. A change to anything below after the first result is a new trial
with a new name.

## Why

The live test trades `P_pool0` (Y6, `results/pumpfun_pool0_prereg.md`): buy
the PumpSwap pool at the migration, 0.1 SOL, sell everything at +30 %, stop
-20 %, time stop 300 s. The owner wants to catch the big runs (+100 % to
+1,000 %) instead of always selling at +30 %, without losing on the many
ordinary trades. Five exits that keep part or all of a position running are
tested against `P_pool0` itself, at the latency the live executor has
measured since it sends through the Sender path, and run as paper strategies
so forward evidence starts.

## What was looked at before this plan

Disclosed, because it shaped the plan: Y5's report and its pre-registration,
Y6's pre-registration, and the live executor's measured file: the latency
and slippage of each P_pool0 fill since 2026-10-22 21:41 UTC (listed in
section 3) and one failed buy (on-chain error 6040, 23:17 UTC). No replay of
any variant or of P_pool0 at this latency was computed, and nothing about
the peaks of P_pool0's entries was looked at.

## 1. The variants

All six: family E, entry at the migration (`delay_s` 0), no filter, stake
0.1 SOL, stop -20 %. The exits as `pipeline.Exits` (time stop in s, stop,
ladder of (gain, cumulative share sold), trail_after, trail_gap, dev-sell
and pull exits):

| book | strategy | ladder | trail_after, trail_gap | time stop | dev sell, pull |
|---|---|---|---|---|---|
| X0 | `P_pool0` (unchanged) | (+30 %, all) | none | 300 s | no |
| X1 | `P_pool0_half_trail` | (+30 %, 0.5), (+5,000 %, 1.0) | 0.30, 0.30 | 1,800 s | no |
| X2 | `P_pool0_ladder3` | (+30 %, 0.34), (+100 %, 0.67), (+5,000 %, 1.0) | 0.30, 0.35 | 3,600 s | no |
| X3 | `P_pool0_trail` | (+5,000 %, 1.0), in effect none | 0.20, 0.25 | 1,800 s | no |
| X4 | `P_pool0_half_trail_guard` | as X1 | as X1 | 1,800 s | yes |
| X5 | `P_pool0_half_trail_ext` | as X1 | as X1 | 300 s until a ladder step has filled, then 3,600 s after the landing | no |

**The trail, as the pipeline defines it.** On every trade of the token the
position's mark is the sale value of the tokens still held (after the pool's
fee) over their share of the buy's cost; its peak is the highest mark so far.
`trail_after` is a gain over the entry: the trail is armed once the peak is
at or above 1 + trail_after. `trail_gap` is a fraction off the peak: armed,
it sells everything left when the mark is at or below peak x (1 -
trail_gap). "Trail 30 % below the peak, armed once the price is +30 % over
entry" is therefore trail_after 0.30, trail_gap 0.30 (X1, X4, X5); X2 is
0.30, 0.35; X3 0.20, 0.25.

**The stop until the first take profit.** The pipeline keeps the stop on for
the whole hold, but once a trail is armed it fires first: (1 + trail_after)
x (1 - trail_gap) is 0.91 (X1, X4, X5), 0.845 (X2) and 0.90 (X3), all above
the stop's 0.80, and in X1, X2, X4 and X5 the trail arms at the same +30 %
as the first ladder step. So the stop acts only before the first take
profit (X3: before the trail arms), as intended. (A single trade that moves
the mark from above the trail's level to under 0.80 is booked as "stop";
the action, sell everything left, is the same.)

**The last ladder step at +5,000 %** sells what is left; it stands for "no
further take profit" (the ladder must end at a share of 1.0).

**Every partial sale is its own transaction** and pays its own fee, and
every sale lands one latency draw after its signal, at what the pool then
pays, as in every pipeline book.

## 2. Code changes the variants need

- **`Exits.time_after_step_s`** (new, optional, default `None`): when set
  and a ladder step has filled (a sale has landed while the position is
  still open), the time stop is landing + time_after_step_s instead of
  landing + time_s. If the step's sale is in flight when the first time
  stop comes, the time stop waits for it (as before): filled, the time stop
  moves; failed, the position is sold at once. With `None` nothing changes.
- **A fix the variants need**: a dev sale or a pull that came while a sale
  was in flight was queued and acted on once the sale was back, even for a
  strategy without the dev-sell or pull exit. It is now queued only where
  the strategy has that exit. No strategy before Y7 is affected: all of
  them have both exits on except `P_pool0`, whose only step sells everything
  (the position is closed when that sale is back).

Both are covered by tests, and the 13 strategies before Y7 (with the 22
rules) were replayed on a synthetic record with curves and pools before and
after the change: 3,260 closed trades and failed buys, identical field for
field.

## 3. Record, latency, costs

- **Record**: every recorded day up to the cutoff **2026-10-23 00:00 UTC**
  (the latest complete hour at registration), from the record's start
  (2026-10-20, the days Y5 used plus everything since). Entries are taken
  until 90 minutes before the cutoff, so that every position (the longest
  hold is 3,600 s plus a sale's latency) and every peak window closes
  inside the record. The split is Y5's: the middle of the record's time
  span; in sample before, out of sample after (by signal time). Nothing is
  fitted, so the in-sample half is only reported.
- **(b) measured, judged**: Y5's model (`reallat.LogKDE`: a lognormal kernel
  on each point in log space, Silverman bandwidth with a floor of 0.25,
  draws clipped to 1 to 60 s), rebuilt from the live executor's P_pool0
  fills only: rows of `measured.jsonl` with what = fill, lat_ms set, mode
  test, rule P_pool0, logged from 2026-10-22 21:41 UTC to the cutoff; buys
  and sales apart. A lat_ms at or under zero (the landing logged before the
  signal), and any under 1 s, is set to the 1 s floor, and one over 60 s
  to the 60 s cap: the draws are clipped to 1 to 60 s anyway.

  | side | lat_ms as logged | points of the model (ms) |
  |---|---|---|
  | buys (6) | 472, 21,423, 10,827, -255, 29,589, 104,798 | 1,000, 21,423, 10,827, 1,000, 29,589, 60,000 |
  | sales (6) | 38,000, -73, 1,000, 10,589, 1,000, 27,313 | 38,000, 1,000, 1,000, 10,589, 1,000, 27,313 |

  The 104.8 s buy says the real tail is longer than the model's 60 s cap;
  as in Y5, no buy fails here for being late, so (b) flatters slow entries.

- **(c) 1.5 s send path, robustness line**: Y5's (lognormal median 1.5 s,
  sigma 0.175, clipped to 1 to 2 s).
- **Fee**: 0.001005 SOL per transaction plus the 0.000005 SOL Sender tip,
  0.001010 SOL, in both scenarios. A failed buy pays it too.
- **Draws**: every book draws with P_pool0's key (strategy, mint, leg), one
  uniform per key: a migration's buy lands at the same moment in all six
  books, and a book's n-th sale of that position draws the same latency.
  The books differ by their exits and by the slots their open positions
  hold, nothing else.
- **Capacity, as live**: each book is one pipeline with one shared Risk:
  at most 4 positions open or pending at once (the live budget, 0.4 SOL at
  0.1), exposure and daily-loss limits at the code's hard caps (0.6 SOL,
  1.0 SOL), so the four slots are what binds. A migration that finds four
  open is skipped and counted; a variant whose runners hold slots pays for
  it in missed entries.

## 4. Reported, per book and scenario (out of sample)

Entries (closed trades plus failed buys, each failed buy an entry that lost
its fee), mean and median return per entry over the stake after every cost,
total P&L in SOL, win rate (P&L above zero), the maximum drawdown of the
cumulative P&L (entries in the order they were realised, the running high
starting at 0), the P&L of the best 5 % of entries (rounded up) and its
share of the total, the hour-block bootstrap 90 % band of the mean
(`study.boot_mean`), the exits, the migrations skipped for want of a slot,
and the runners: entries whose **peak after entry** exceeded +100 % and
+500 %, with the **capture ratio** on them (their summed realised return
over their summed peak return; the median of the per-entry ratio as well).

The peak after entry: the highest sale value of all the tokens the buy got
(after the pool's fee, before the transaction fees), over the buy's cost,
from the landing to 60 minutes after it, whether the book still holds them
or not; minus 1. Failed buys have none.

The live P_pool0 trades in the Sender era are listed next to X0's replay of
the same migration (descriptive).

## 5. Verdict

A variant is **better than X0** (at (b), out of sample) only if both hold:

1. the difference of its mean return per entry against X0's, on the
   migrations both books entered (failed buys count as entries), has an
   hour-block bootstrap 90 % band (`study.boot_diff`, the same hours drawn
   for both) above zero; with fewer than 10 hours of such entries the band
   is n/a and the answer is no;
2. its total P&L over all its own entries is higher than X0's.

Every variant is reported, whatever the answer, including if none wins. (c)
is a robustness line: nothing is chosen on it.

**Trials**: the six books at (b): five new exits and P_pool0 judged again at
a latency it was not judged at, `strategies.EXIT_RUNNER_TRIALS = 6`, added to
`strategies.N_TRIALS` (the global pool the study's deflation reads). The
(c) line is descriptive, chosen on nothing, and not counted.

## 6. Paper forward test

The five new strategies join `pipeline.STRATEGIES` (`_build_y7`, after Y6's
P_pool0), stake 0.1 SOL, so the paper engine runs them once the owner
deploys the lab code; the daily study reports them with the readiness rule
every pipeline strategy has (14 days, 300 trades out of sample, positive
with and without broken slots). Y5's twelve registered strategies
(`STRATEGIES[:PIPELINE_TRIALS]`) do not move. Nothing goes live: the live
executor trades the strategy its confirmation file names.

## 7. Too early

The record is under three days; out of sample is about a day, and the
latency model rests on six buys and six sales. Runs of +100 % within an
hour of a migration are rare, so the capture ratios rest on few entries.
The verdict says what this record shows; the paper books are where the
evidence has to come from.
