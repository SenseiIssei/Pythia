# P_pool0: a -10 % stop, a sell-pressure exit, waiting for the pool (Y8)

PAPER ONLY. Nothing here holds a wallet, reads a key, signs or sends anything; the live service, its executor, its
sizing and its confirmation file were not touched. The live executor's files were only read.

Pre-registration: `results/pumpfun_exits_y8_prereg.md` (5 trials, committed before the first replay). Code:
`lab/pumpfun_rt/exits8.py` on Y7's replay (`exitlab.run`), the strategies in `lab/pumpfun_rt/pipeline.py`
(`_build_y8`, `Exits.press_exit`, `p["wait_pool_s"]`); tests: `tests/test_pumpfun_exits_y8.py`. Data: the
server's record, 2026-10-20 16:40 UTC to the registered cutoff 2026-10-23 06:00 UTC, entries to 05:45 UTC, split
at 2026-10-21 23:19 UTC.

## Short answer

**No variant is better than P_pool0, and the registered test has almost nothing to judge.** With the registered
daily loss limit of 0.25 SOL every book stops for the UTC day after its first few losses: out of sample each book
made 8 to 16 entries, all between 00:06 and 01:58 UTC on two days (2 to 3 hours), so no band exists (under 10
hours) and the answer is "no" by the rule. X0 lost -40.6 % per entry (-0.325 SOL); the variants -21.5 % to -35.5 %.

After the first result, not registered: the same replay at the code's hard cap of 1.0 SOL a day (Y7's setting)
gives 245 to 307 entries per book out of sample. Still nothing passes: every band of the difference against X0
straddles zero. The best, X5 (wait plus -10 % stop), is +0.4 % per entry against X0's -0.8 % (difference +1.2
points, band -1.5 to +4.0, +0.130 SOL against -0.195). In sample the -10 % stop was much worse than X0 (+2.1 %
against +18.3 % per entry): it cuts the trades that dip before they run.

**A -10 % stop is not a 10 % maximum loss.** At the measured latency a sale lands a median 4 s and up to 30 s and
more after its signal, and a fresh pool falls far in that time. In the larger unregistered run the -10 % stops
landed at a mean of -27 % (after the two fees), the -20 % stops at -43 %; in the registered one at -48 % and -58 %.
The live P_pool0 stops in the same window landed at -23 % (12 stops). No
exit tested here caps the loss; only a faster sale would come closer.

## 1. The latency model

The live executor's P_pool0 fills from the Sender path (2026-10-22 21:41 UTC) to the cutoff, 26 buys and 26
sales, as registered:

| scenario | buy, median (10 to 90 %) | sale, median (10 to 90 %) | fee per transaction |
|---|---|---|---|
| (b) measured since the Sender path | 10.0 s (1.0 to 39.1) | 4.2 s (1.0 to 31.9) | 0.001005 SOL |
| (c) 1.5 s send path | 1.5 s (1.2 to 1.9) | 1.5 s (1.2 to 1.9) | 0.001005 SOL |

## 2. Every book, out of sample, at (b) (registered)

Daily loss limit 0.25 SOL, at most 4 open, 0.1 SOL, trades open across a gap kept. Stop mean: the mean return of
the stop exits after every cost; below: how far that lies below the trigger, in points of the stake. Skipped: for
want of a pool state, and for the daily loss limit.

| book | strategy | entries | failed buys | mean | median | win | P&L SOL | max DD SOL | stops | stop mean | below | press exits | no pool state | daily loss limit |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| X0 | P_pool0 | 8 | 0 | -40.6 % | -44.6 % | 12 % | -0.325 | 0.325 | 6 | -58.1 % | -38.1 | 0 | 270 | 237 |
| X1 | P_pool0_sl10 | 16 | 1 | -21.5 % | -15.8 % | 19 % | -0.344 | 0.392 | 11 | -48.2 % | -38.2 | 0 | 270 | 229 |
| X2 | P_pool0_press | 12 | 1 | -22.3 % | -25.7 % | 17 % | -0.268 | 0.316 | 5 | -72.9 % | -52.9 | 3 | 270 | 233 |
| X3 | P_pool0_wait | 9 | 0 | -35.5 % | -28.6 % | 22 % | -0.319 | 0.319 | 5 | -71.0 % | -51.0 | 0 | 208 | 298 |
| X4 | P_pool0_wait_press | 11 | 0 | -23.4 % | -16.2 % | 27 % | -0.257 | 0.305 | 5 | -83.5 % | -63.5 | 1 | 208 | 296 |
| X5 | P_pool0_wait_sl10 | 11 | 0 | -23.4 % | -16.2 % | 27 % | -0.257 | 0.305 | 6 | -72.3 % | -62.3 | 0 | 208 | 296 |

The band of every mean is n/a (2 to 3 hours of entries).

**The verdict, against X0 (registered):**

| book | mean difference | 90 % band (hours paired) | P&L difference SOL | total P&L higher | better than X0 |
|---|---|---|---|---|---|
| X1 | +19.1 % | n/a | -0.019 | no | no |
| X2 | +18.3 % | n/a | +0.057 | yes | no |
| X3 | +5.1 % | n/a | +0.005 | yes | no |
| X4 | +17.2 % | n/a | +0.068 | yes | no |
| X5 | +17.2 % | n/a | +0.068 | yes | no |

On the migrations both entered (6 to 8, not judged) the differences are +9.1 % (X1), +2.1 % (X2, X4, X5) and 0
(X3). The wait variants skipped 208 migrations for want of a pool state against X0's 270: the wait finds a state
within 5 s for about a quarter of them.

**(c) 1.5 s send path (robustness, registered):** X0 12 entries, -25.3 %, -0.303 SOL. The variants that lose
less early keep trading: X1 189 entries +1.9 % (+0.360 SOL), X2 187 +1.6 % (+0.299), X4 223 +2.3 % (+0.519), X5
226 +2.5 % (+0.558), X3 10 -27.7 %. Every band is n/a for want of X0's hours (12 entries); X0's day stopped early.
That is the daily loss limit's path dependence, not an exit's edge: the in-sample half at (c) has X0 at +32.0 %
per entry and X1, X2 at +30.9 %, +31.2 %.

**Gapped trades left out (robustness, registered):** the same picture, X0 7 entries -42.3 %, the variants -9.1 %
to -33.0 %, every band n/a.

## 3. After the first result, not registered: the daily loss limit at 1.0 SOL

Found with the first result: the pipeline counts the day's realised loss plus everything at risk plus the new
buy's limit (0.13 SOL) against the daily loss limit, so at 0.25 SOL a book takes no new position once the UTC day
has lost 0.12 SOL; at (b), with stops landing at -40 to -80 %, that is two or three stops after midnight. To see
the exits rather than the limit, the same replay was run with the limit at the code's hard cap, 1.0 SOL (Y7's);
the code was changed only to take the limit as an argument. Not judged, not counted as trials.

| book (b), 1.0 SOL a day | entries | mean | median | win | P&L SOL | band of mean | max DD SOL | stops | stop mean | below | press | no pool state | vs X0 | band | P&L higher |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| X0 | 245 | -0.8 % | +6.1 % | 52 % | -0.195 | -4.9 % to +3.8 % | 0.450 | 89 | -43.3 % | -23.3 | 0 | 270 | | | |
| X1 | 242 | -0.0 % | -1.0 % | 46 % | -0.008 | -3.7 % to +3.8 % | 0.454 | 116 | -27.3 % | -17.3 | 0 | 270 | +0.8 % | -1.2 % to +2.7 % | yes |
| X2 | 245 | -1.3 % | -1.0 % | 49 % | -0.321 | -5.1 % to +2.9 % | 0.498 | 63 | -48.6 % | -28.6 | 38 | 270 | -0.5 % | -1.4 % to +0.3 % | no |
| X3 | 303 | -0.0 % | +11.8 % | 53 % | -0.009 | -3.9 % to +4.0 % | 0.541 | 104 | -42.9 % | -22.9 | 0 | 208 | +0.8 % | -1.0 % to +2.5 % | yes |
| X4 | 303 | -0.4 % | +0.6 % | 50 % | -0.119 | -3.8 % to +3.2 % | 0.532 | 72 | -49.3 % | -29.3 | 44 | 208 | +0.4 % | -1.5 % to +2.3 % | yes |
| X5 | 304 | +0.4 % | -1.0 % | 47 % | +0.130 | -3.0 % to +3.9 % | 0.430 | 136 | -27.8 % | -17.8 | 0 | 208 | +1.2 % | -1.5 % to +4.0 % | yes |

None would pass the registered rule here either. At (c): X0 -0.3 %, X1 +0.4 %, X2 -0.5 %, X3 +0.5 %, X4 +0.3 %,
X5 +0.9 % (difference +1.1 points, band -0.7 to +3.0). With gapped trades left out the order holds (X5 +0.9
points, band -2.4 to +4.3; X2 the only band below zero, -0.9 points, -1.9 to -0.1).

In sample at (b) the order is the other way round: X0 +18.3 % per entry (+4.06 SOL over 222), X2 +17.9 %, X1
+2.1 %, X3 +1.2 %, X4 +0.1 %, X5 +1.9 %. The -10 % stop sells many trades that dip and then reach +30 %; out of
sample it saved a little more on the losers than it cost on those. The wait's extra migrations (about 60 out of
sample) are worth about nothing either way. Not an edge in either half.

**What each change does.** The -10 % stop fires about a third more often and its stops land at -27 % instead of
-43 %; the take profits fall from 64 to 45. The sell-pressure exit fires on about one entry in six and those
sales land at a mean -16 %, better than a stop, but the stops it leaves land worse (-49 %), it sells some trades
that would have recovered (take profits 54 against 64), and it is the only change whose difference leans
negative. The wait turns about a quarter of the "no pool state" skips into entries.

## 4. The live P_pool0 trades (descriptive)

From the Sender path to the cutoff the live book made 26 P_pool0 trades, mean +2.2 %, +0.048 SOL, 12 stop exits
at a mean -23.1 %. With the 0.25 SOL limit the replay's X0 entered one of them (it had stopped for the day); with
1.0 SOL it entered 13 and matched the live exit on 9; the replay draws other latencies than the live fills had.

## 5. What runs on paper

The five variants are pipeline strategies (`_build_y8`), 0.1 SOL each, and run on paper once the owner deploys
the lab code. The 18 strategies before Y8 and the 22 rules trade identically before and after the change
(synthetic record and the recorded 2026-10-20, field for field). Trials: 5 (`strategies.EXITS_Y8_TRIALS`).

## 6. Too early

Under three days of record, 30 hours out of sample, a latency model from 26 buys and 26 sales. The registered test
saw 2 to 3 hours per book; the unregistered one shows differences of about a point per entry against a band four
or five points wide. Whether the -10 % stop or the wait is worth anything has to come from the paper books.
