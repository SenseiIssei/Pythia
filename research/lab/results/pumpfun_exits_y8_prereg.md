# P_pool0: a -10 % stop, a sell-pressure exit, waiting for the pool (Y8): pre-registration (2026-10-23)

Written and committed before any replay below was computed. Code: `lab/pumpfun_rt/exits8.py` (the run, on Y7's
replay `exitlab.run`), `lab/pumpfun_rt/pipeline.py` (`_build_y8`, `Exits.press_exit`, the strategy parameter
`wait_pool_s`), tests `tests/test_pumpfun_exits_y8.py`. Paper only: nothing here holds a wallet, reads a key, signs
or sends anything; the live service, its executor, its sizing and its confirmation file are not touched, and the
live executor's files are only read. A change to anything below after the first result is a new trial with a new
name.

## Why

The live bot trades `P_pool0` (Y6): buy the PumpSwap pool at the migration, sell everything at +30 %, stop -20 %,
time stop 300 s. Last night 19 live trades lost 0.109 SOL; 11 stops triggered at -20 % but landed at -39 % on
average, because a sale lands 5 to 20 s after its signal while a fresh pool collapses; and 75 migrations were
skipped as "no pool state" (no pool trade seen yet at the migration). The owner wants a maximum loss of 10 %,
the take profit at 30 %, and the strategy optimised. Five variants test the owner's stop, an exit that reacts to
the selling itself rather than to the price, and an entry that does not skip a migration only because its pool
has not traded yet.

## What was looked at before this plan

Disclosed: Y5's and Y7's reports and pre-registrations, the live numbers above (from the owner's brief), and the
live executor's measured file: the latency of each P_pool0 fill from 2026-10-22 21:41 UTC to the cutoff (section
3). The code change was checked by replaying every strategy that existed before it on a synthetic record and on
the recorded day 2026-10-20 before and after the change, and comparing the closed trades and failed buys field by
field (identical); only the equality was looked at, no return of any book. No variant below was replayed on the
record.

## 1. The variants

All six: family E, entry at the migration (`delay_s` 0), no filter, stake 0.1 SOL, take profit +30 % (the whole
position, one sale), time stop 300 s after the landing, no dev-sell, pull, trail or risk-model exit.

| book | strategy | stop | sell-pressure exit | entry when the pool state is not known at the migration |
|---|---|---|---|---|
| X0 | `P_pool0` (unchanged) | -20 % | no | skipped ("no pool state") |
| X1 | `P_pool0_sl10` | -10 % | no | skipped |
| X2 | `P_pool0_press` | -20 % | (5 s, 8 %) | skipped |
| X3 | `P_pool0_wait` | -20 % | no | waits up to 5 s |
| X4 | `P_pool0_wait_press` | -20 % | (5 s, 8 %) | waits up to 5 s |
| X5 | `P_pool0_wait_sl10` | -10 % | no | waits up to 5 s |

The stop is the pipeline's: on every trade of the token, the sale value of the position (after the pool's fee)
over its cost at or under 1 - stop sells everything (min_out 0); the sale lands one latency draw later at what the
pool then pays. That is why a stop lands below its trigger, and why -10 % is a trigger, not a maximum loss: the
realised loss is whatever the pool pays when the sale lands, plus the two transaction fees (about 2 points of a
0.1 SOL stake).

**The sell-pressure exit** (`Exits.press_exit = (5.0, 0.08)`, X2 and X4). Checked on every trade of the token
(and at the landing), after the stop and before the take profit: sell everything (min_out 0, exit "press") when
the pool's net SOL outflow over (t - 5 s, t] exceeds 8 % of the reference. Net outflow: over the pool trades the
engine sees in that window at or after our landing, the sum of each trade's quote reserves before it minus after
it (sales count positive, buys negative), on the pool's effective quote reserves as the engine keeps them
(`tokens.Token.amm_win`). Reference: the pool's effective quote reserves at our landing (after every trade before
it). Trades before our landing do not count, so a dump the buy already landed into does not sell us at once.
While a sale is in flight nothing more is sent (as for the price exits; P_pool0's only sale sells everything).
`None`, the default, changes nothing.

**The wait** (strategy parameter `p["wait_pool_s"] = 5`, X3 to X5). At the migration signal, if the pool has no
state yet (no pool trade seen), the signal is not skipped but waits: at the first pool trade of that token that
brings a state, at most 5 s after the signal (5 s included), the signal is given again at that trade's time and
every check runs again (a plain SOL pool, the risk limits, depth); the buy then lands one latency draw after that
time. If no pool trade comes within 5 s, the migration is skipped as "no pool state" at the end of the wait. No
slot is held while waiting. Absent, nothing changes; with the state known at the migration a wait variant enters
exactly as P_pool0 does.

## 2. Code changes the variants need

`Exits.press_exit` (default `None`), `pipeline.press_trigger`, the wait (`Pipeline.waiting`, `_wait_pool`,
`_wait_over`, a check at the top of `Pipeline.on_trade`), and `_strategy` takes an explicit stake (0.1 for the
five). Y7's replay gets optional books, limits and entry tail (`exitlab.run`), a fee argument
(`exitlab.scenarios`), and its book counts a wait in vain as one "no pool state" skip at the end of the wait. The
18 strategies before Y8 and the 22 rules were replayed before and after the change, in one shared paper book and
each in its own book of 4 slots, on a synthetic record with curves, pools with the state known and pools whose
first trade comes 0 to 8 s after the migration (1,622 and 206 closed trades and failed buys) and on the recorded
2026-10-20 (19,005 and 580): identical field for field, skip counts included.

## 3. Record, latency, costs, limits

- **Record**: every recorded day from the record's start (2026-10-20) up to the cutoff **2026-10-23 06:00 UTC**
  (the last complete UTC hour at registration). Entries are taken until 15 minutes before the cutoff (a hold is
  at most 300 s plus a buy and a sale of at most 60 s each, plus the 5 s wait), so every position closes inside
  the record. The split is Y5's and Y7's: the middle of the record's time span; out of sample after (by signal
  time). Nothing is fitted; the in-sample half is only reported.
- **(b) measured, judged**: Y5's model (`reallat.LogKDE`, a lognormal kernel on each point in log space,
  Silverman bandwidth with a floor of 0.25, draws clipped to 1 to 60 s), rebuilt from the live executor's
  P_pool0 fills only: rows of `measured.jsonl` with what = fill, lat_ms set, mode test, rule P_pool0, logged from
  2026-10-22 21:41 UTC (the Sender path) to the cutoff; buys and sales apart; a value under 1 s set to 1 s, over
  60 s to 60 s. 26 buys and 26 sales:

  | side | lat_ms as logged |
  |---|---|
  | buys (26) | 472, 21,423, 10,827, -255, 29,589, 104,798, 8,209, 18,924, 984, 28,867, 970, 12,866, 19,353, 6,217, 12,696, 37,275, 17,472, 296, 19,655, 9,074, 13,064, 433, 6,476, 8,973, 2,867, 9,215 |
  | sales (26) | 38,000, -73, 1,000, 10,589, 1,000, 27,313, 2,916, 928, 12,852, 0, -420, 6,158, 8,030, 13,321, 17,593, 3,537, -241, 2,330, 37,000, 10,020, 2,905, 38,000, 5,205, 5,317, 1,890, -387 |

  The model's draws: buys median 10.0 s (10 to 90 %: 1.0 to 39.1 s), sales median 4.2 s (1.0 to 31.9 s).
- **(c) 1.5 s send path, robustness line**: Y5's (lognormal median 1.5 s, sigma 0.175, clipped to 1 to 2 s).
- **Fee**: 0.001005 SOL per transaction (as measured, the tip not added), both scenarios; a failed buy pays it.
- **Draws**: every book draws with P_pool0's key (mint, leg), one uniform per key: a migration's buy is the same
  draw in all six books (in a wait variant counted from the later signal), and the sale of that position the same
  draw.
- **Limits, as live**: each book is one pipeline with one Risk: at most 4 positions open or pending, exposure cap
  0.6 SOL, **daily loss limit 0.25 SOL**. The pipeline counts the day's realised loss plus everything at risk
  plus the new buy's limit (0.13 SOL at a 30 % slippage tolerance) against it, so at 0.1 SOL at most two positions
  are open at once, none is opened once the UTC day's realised loss passes 0.12 SOL, and the book stops for the
  day at 0.25. A variant that loses faster loses entries to this; the skips are counted and reported.

## 4. Gapped trades

Y7 found, after its result, that leaving out every trade open across a gap in the record (about 24 short gaps an
hour) drops a third of P_pool0's entries, selected on the outcome. Registered here: **the judged numbers keep
them** (every variant holds at most about 6 minutes, and the stop variants exit earlier, so a drop would select
differently per variant). The numbers with them left out are a robustness line.

## 5. Reported, per book and scenario (out of sample)

Entries (closed trades plus failed buys, each failed buy an entry that lost its fee), mean and median return per
entry over the stake after every cost, total P&L in SOL, win rate (P&L above zero), the stop exits (number, their
mean and median return after every cost, and how far that mean lies below the trigger: mean + stop, in points of
the stake), the press exits (number, mean), the maximum drawdown of the cumulative P&L (entries in the order
realised, the high starting at 0), the hour-block 90 % band of the mean (`study.boot_mean`), the exits, and the
migrations skipped for "no pool state" and for the daily loss limit. The live P_pool0 trades from the Sender path
to the cutoff are listed next to X0's replay (descriptive), with the live stop exits' mean.

## 6. Verdict

A variant is **better than X0** (at (b), out of sample, gapped trades kept) only if both hold:

1. the difference of its mean return per entry against X0's has an hour-block bootstrap 90 % band above zero
   (`study.boot_diff`, 5,000 draws, the same hours drawn for both books), each book's mean over all its own
   entries (failed buys included). Paired by hour, not by migration, because the wait variants' point is the
   migrations X0 does not enter; with fewer than 10 hours of entries in either book the band is n/a and the
   answer is no;
2. its total P&L is higher than X0's.

The difference on the migrations both entered (Y7's pairing) is reported, not judged. Every variant is reported,
whatever the answer, including if none wins. (c) and the gapped-dropped line are robustness lines: nothing is
chosen on them.

**Trials**: the five new books at (b), `strategies.EXITS_Y8_TRIALS = 5`, added to `strategies.N_TRIALS`.

## 7. Paper forward test

The five strategies join `pipeline.STRATEGIES` (`_build_y8`, after Y7's), stake 0.1 SOL, so the paper engine runs
them once the owner deploys the lab code; the daily study reports them with every pipeline strategy's readiness
rule. Nothing goes live: the live executor trades the strategy its confirmation file names, and moving the live
book to a variant is the owner's decision.

## 8. Too early

Under three days of record, out of sample about a day and a half, a latency model from 26 buys and 26 sales.
The verdict says what this record shows; the paper books are where the evidence has to come from.
