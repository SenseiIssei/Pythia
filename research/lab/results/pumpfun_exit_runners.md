# P_pool0's exits for runners (Y7)

PAPER ONLY. Nothing here holds a wallet, reads a key, signs or sends
anything; the live service, its executor and its confirmation file were not
touched. The live executor's files were only read.

Pre-registration: `results/pumpfun_exit_runners_prereg.md` (6 trials,
committed before the first replay). Code: `lab/pumpfun_rt/exitlab.py`, the
strategies in `lab/pumpfun_rt/pipeline.py` (`_build_y7`); tests:
`tests/test_pumpfun_exit_runners.py`. Data: the server's record, 2026-10-20
16:40 UTC to the registered cutoff 2026-10-23 00:00 UTC, entries to
2026-10-22 22:30 UTC (90 minutes before the cutoff, so every position and
peak window closes inside the record), split at 2026-10-21 20:19 UTC; out of
sample is the 26 hours of entries after the split (27 hour blocks).

## Short answer

**No variant is better than P_pool0.** At the latency measured since the
Sender path, out of sample, every one of the five has a lower mean per
entry than X0 on the migrations both entered and a lower total P&L. Two are
worse with a band entirely below zero (X1 half and trail, X4 the same with
the guard exits); X2 and X3 have too few paired hours for a band; X5 (half
and trail, 300 s until the half has sold) comes closest, -0.9 points, band
-2.4 to +0.7. X0 itself is about break-even: +0.6 % per entry, band -4.9 %
to +6.3 %, +0.083 SOL over 132 entries.

The runs the owner wants exist: about a quarter of the migrations X0 enters
are worth more than twice the stake at some point in the hour after the
landing, and the pool still pays that 5 s later. None of the exits catches
them: P_pool0 keeps 5 % of the peak on those entries, the trailing exits 2
to 13 %. Holding longer to wait for a run costs more on the ordinary trades
(rugs, slow stops, and the daily loss limit then blocking new entries) than
the runs bring back.

Two caveats change how much the registered numbers say about the long-hold
variants, both found after the first result and reported below as
unregistered: the replay leaves out every trade open across a gap in the
record (as every study here does), and the record has about 24 short gaps
an hour, so most long holds drop out; and the daily loss limit (1.0 SOL)
binds for every variant but X0. With the gapped trades kept, the order is
the same and still nothing passes, but X5 moves just above X0 (+1.2 points,
band -3.5 to +5.7).

## 1. The latency model

The live executor's P_pool0 fills since 2026-10-22 21:41 UTC up to the
cutoff, as registered: six buys and six sales (a landing logged before its
signal set to the 1 s floor, one 104.8 s buy to the 60 s cap). Y5's kernel
density in log space; with six widely spread points Silverman's bandwidth is
1.1 for both sides, far above the 0.25 floor, so the model is wide:

| scenario | buy, median (10 to 90 %) | sale, median (10 to 90 %) | fee per transaction |
|---|---|---|---|
| (b) measured since the Sender path | 11.3 s (1.0 to 60.0) | 4.4 s (1.0 to 60.0) | 0.001010 SOL |
| (c) 1.5 s send path | 1.5 s (1.2 to 1.9) | 1.5 s (1.2 to 1.9) | 0.001010 SOL |

The fee is 0.001005 SOL plus the 0.000005 SOL Sender tip. Every book draws
with P_pool0's key, so a migration lands at the same moment in all six.

## 2. Every book, out of sample, at (b) (registered)

Entries are closed trades plus failed buys. Stake 0.1 SOL, at most 4 open
per book. Band: the hour-block bootstrap 90 % band of the mean (n/a under 10
hours). Max DD: the largest fall of the cumulative P&L. Top 5 %: the P&L of
the best 5 % of entries and its share of the total (n/a when the total is
not positive). Runners: entries whose peak after entry (the best sale value
of all the tokens within an hour of the landing, over the cost) exceeded
+100 % or +500 %; capture: their summed realised return over their summed
peak return.

| book | strategy | entries | failed buys | mean | median | win | P&L SOL | band of mean | max DD SOL | top 5 % SOL | peak > +100 % | capture | peak > +500 % | capture |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| X0 | P_pool0 | 132 | 15 | +0.6 % | -1.0 % | 45 % | +0.083 | -4.9 % to +6.3 % | 0.368 | +0.658 (790 %) | 45 | 5 % | 8 | 3 % |
| X1 | P_pool0_half_trail | 67 | 10 | -14.5 % | -16.7 % | 22 % | -0.974 | -23.0 % to -7.3 % | 0.974 | +0.350 | 17 | 2 % | 1 | 1 % |
| X2 | P_pool0_ladder3 | 29 | 6 | -22.4 % | -17.3 % | 17 % | -0.649 | n/a | 0.649 | +0.068 | 5 | 6 % | 0 | n/a |
| X3 | P_pool0_trail | 23 | 6 | -17.2 % | -8.7 % | 17 % | -0.395 | n/a | 0.405 | +0.182 | 3 | 13 % | 0 | n/a |
| X4 | P_pool0_half_trail_guard | 75 | 10 | -15.0 % | -15.0 % | 20 % | -1.122 | -22.8 % to -7.9 % | 1.122 | +0.345 | 19 | 2 % | 1 | 1 % |
| X5 | P_pool0_half_trail_ext | 95 | 12 | -7.6 % | -1.8 % | 35 % | -0.726 | -14.7 % to -1.7 % | 0.751 | +0.336 | 27 | 3 % | 1 | 1 % |

Median capture per entry on the +100 % runners: X0 8 %, X1 0 %, X2 6 %, X3
1 %, X4 0 %, X5 5 %. X0's P&L is carried by its best seven entries (+0.658
SOL against +0.083 in all).

Migrations skipped out of sample (the same 220 without a pool state and 249
not plain SOL pools in every book): for want of a slot X1 2, X2 6, X3 2, X4
2, X0 and X5 none; for the daily loss limit X1 58, X2 129, X3 154, X4 50, X5
27, X0 none. The four slots hardly bind; the losses do.

Exits: X0 take 39, stop 51, time 27; X1 trail 11, stop 43, time 3; X2 trail
4, stop 19; X3 trail 4, stop 11, time 2; X4 trail 8, stop 33, pull 16, dev
sell 5, time 3; X5 trail 14, stop 43, time 26 (failed buys apart).

**The verdict, against X0, paired by migration (registered):**

| book | migrations both entered | mean difference | 90 % band | P&L difference SOL | total P&L higher | better than X0 |
|---|---|---|---|---|---|---|
| X1 | 67 | -3.5 % | -6.1 % to -0.4 % | -0.236 | no | no |
| X2 | 29 | -11.8 % | n/a (under 10 hours) | -0.343 | no | no |
| X3 | 23 | -12.0 % | n/a (under 10 hours) | -0.276 | no | no |
| X4 | 74 | -3.9 % | -6.9 % to -0.7 % | -0.291 | no | no |
| X5 | 95 | -0.9 % | -2.4 % to +0.7 % | -0.090 | no | no |

## 3. The 1.5 s send path (robustness line, registered)

| book | entries | mean | P&L SOL | band of mean | max DD SOL | peak > +100 % | capture | vs X0 | band |
|---|---|---|---|---|---|---|---|---|---|
| X0 | 142 | +5.1 % | +0.718 | -1.3 % to +11.6 % | 0.705 | 53 | 10 % | | |
| X1 | 99 | -12.7 % | -1.259 | -19.7 % to -6.5 % | 1.360 | 27 | 11 % | -6.6 % | -10.3 % to -2.6 % |
| X2 | 84 | -24.1 % | -2.024 | -30.5 % to -17.8 % | 2.091 | 20 | 5 % | -11.4 % | -16.1 % to -6.6 % |
| X3 | 105 | -10.3 % | -1.083 | -17.8 % to -3.5 % | 1.189 | 31 | 13 % | -6.1 % | -12.6 % to +0.5 % |
| X4 | 103 | -10.2 % | -1.054 | -16.6 % to -4.2 % | 1.188 | 29 | 13 % | -6.3 % | -10.3 % to -2.2 % |
| X5 | 121 | -7.6 % | -0.920 | -13.5 % to -2.3 % | 1.056 | 36 | 9 % | -4.3 % | -6.7 % to -1.4 % |

A faster path helps X0 most (+5.1 % per entry, band still from below zero)
and changes no ranking: every variant is worse than X0 here too.

In sample (not judged) the order is the same: X0 +10.7 % per entry over 141
entries, the variants -7.7 % to -19.3 % at (b).

## 4. After the first result, not registered

Found after the first replay and reported, not judged; the verdict above
stands as registered. The replay code was changed after the first result
only to mark gapped trades instead of dropping them and to add the held
peak; the registered tables came out identical in the second run.

**Trades open across a gap.** The engine drops every trade open across a
gap in the record (Y5 and every study here do the same). This record has
1,352 gaps in 2.3 days, a median of 5 s each, about 24 an hour, so a 30 or
60 minute hold almost always crosses one, a 300 s hold often does. The drop
selects on the outcome: a variant's quick losses stay in, its long holds
(where its runners are) drop out; X0 lost 71 of its 203 out-of-sample entries to
it, X1 76 of 143, X5 81 of 176. Kept:

| book (b), gapped kept | entries | mean | median | P&L SOL | band of mean | max DD SOL | held peak > +100 % | capture | vs X0 | band |
|---|---|---|---|---|---|---|---|---|---|---|
| X0 | 203 | -0.1 % | -1.0 % | -0.019 | -4.3 % to +4.5 % | 0.383 | 56 | 7 % | | |
| X1 | 143 | -6.5 % | -17.3 % | -0.925 | -11.1 % to -1.1 % | 1.005 | 42 | 9 % | -4.9 % | -10.5 % to +0.8 % |
| X2 | 68 | -13.1 % | -18.2 % | -0.890 | n/a | 0.935 | 16 | 21 % | -11.4 % | n/a |
| X3 | 47 | -18.6 % | -16.5 % | -0.875 | n/a | 0.979 | 9 | 22 % | -16.2 % | n/a |
| X4 | 151 | -5.8 % | -15.5 % | -0.883 | -10.9 % to -0.1 % | 0.963 | 43 | 10 % | -4.6 % | -10.5 % to +1.4 % |
| X5 | 176 | +1.5 % | -1.0 % | +0.266 | -3.7 % to +6.6 % | 0.395 | 51 | 8 % | +1.2 % | -3.5 % to +5.7 % |

At (c) with gapped trades kept: X0 +3.0 % (+0.618 SOL), X5 +2.5 % (+0.512),
X4 -2.1 %, X1 -2.6 %, X2 -3.3 %, X3 -6.9 %; every paired difference is
negative (X5 -0.5 points, band -4.6 to +3.6).

So the gap rule makes the long-hold variants look worse than they are, but
it does not hide a winner: X1 to X4 lose with or without it, and X5 is level
with X0 within a wide band either way. A clean test of long holds needs a
record without the gaps (a second feed for the collector) or a rule that
drops by migration for every book alike, registered before it runs.

**The held peak.** A peak counted only where the pool still paid it 5 s
later (a spike inside one slot, a sandwich, does not count). It changes
little: X0 at (b), registered set, 41 entries above +100 % instead of 45
and 8 above +500 %, capture 6 % and 3 %. Out of sample with gapped trades
kept, X0's entries reach a held peak of +42 % at the median, +132 % at the
75th percentile and +257 % at the 90th, within an hour of landing. Of the
56 X0 entries that more than doubled, 30 were sold by the +30 % take
profit, 14 by the 300 s time stop and 12 by the stop before the run.

**Why the exits lose** (gapped trades kept). The stop at -20 % fills, at
this latency, at a median -26 % (X0) and far worse where the position was held longer: X3's
stops lost a median 77 % (rugs: no pull exit, and an hour to wait for one),
X1's 31 %. Each partial sale costs another 0.00101 SOL. The trail arms at
+20 or +30 % and sells on the first fall of 25 to 35 % from the peak so
far; the capture ratios say that comes long before the hour's peak. And the losses trip the daily loss limit, which then
blocks the next migrations, the runners among them.

**The daily loss limit.** Registered at the code's hard cap, 1.0 SOL
(realised loss plus what is at risk plus the new buy). The live test's
confirmation file may set a lower one (its cap is 0.5 SOL), which would bind
more, not less.

## 5. The live P_pool0 trades in the replay (descriptive)

Of the six live P_pool0 trades in the Sender era, four were signalled after
the replay's last entry (22:30 UTC). KIMCHINU (live +45.5 %, take profit)
was entered by X0 at both latencies and lost 25.1 % on its stop: the
replay's buy and sale landed at other moments than the live fills. MrBeast (live +16.5 %,
time stop) was not entered by the replay.

## 6. What runs on paper

The five variants are pipeline strategies (`_build_y7`), 0.1 SOL each, and
run on paper once the owner deploys the lab code; the daily study reports
them with every pipeline strategy's readiness rule. Y5's twelve registered
strategies (`STRATEGIES[:PIPELINE_TRIALS]`) did not move, and the 13
strategies before Y7 trade identically before and after the change (3,260
closed trades and failed buys on a synthetic record, field for field).
Trials: 6 (`strategies.EXIT_RUNNER_TRIALS`).

## 7. Too early

Under three days of record, 26 hours out of sample, a latency model from
six buys and six sales; the runners rest on dozens of entries, the +500 %
ones on eight. The registered answer is "no", and the unregistered look does
not turn it into a "yes"; whether X5 (or any way to keep a run) is worth
anything has to come from the paper books and a clean registered test.
