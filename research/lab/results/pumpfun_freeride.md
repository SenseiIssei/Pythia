# P_pool0_wait with a free ride after a fast spike (Y15): result (2026-10-23)

Pre-registered in `results/pumpfun_freeride_prereg.md` (committed before the replay). Code `lab/pumpfun_rt/free15.py`,
`pipeline._build_y15`, `Exits.free`. Paper only.

## The answer

**No.** No free ride beats P_pool0_wait, neither at the paper model's latency (A, median 1 s) nor at the measured
live latency (B, buy median 9.8 s, sale 3.9 s). Under the 1.0 SOL daily loss limit every difference is within 0.3
points of zero with a band across it; under the live 0.25 SOL limit all five books made the same 5 entries in one
hour and stopped for the day: no band, so no by the rule. A fast spike is rare (+30 % within 10 s of the landing on 7
trades out of sample, 2 % of the closed ones; the median +30 % comes 57 s after the landing at A, 71 s at B), and
most rests fall straight back to the partial sale's price: the ride rarely runs. Nothing changes for the live bot.

## Setup

Record 2026-10-20 to the cutoff 2026-10-23 17:00 UTC, entries to 16:25 UTC, split 2026-10-22 04:49 UTC (out of sample
after it, about 36 hours). One replay, five books under two latencies and two limits, 0.1 SOL a trade, at most 4
open, 0.001005 SOL a transaction, every book on P_pool0's latency key, trades open across a gap kept.

| book | strategy | partial sale (stake and fees back) when +30 % within | the rest's trail |
|---|---|---|---|
| X0 | `P_pool0_wait` | never, all at +30 % | |
| V10 | `P_pool0_wait_free10` | 10 s | 20 % under its high |
| V30 | `P_pool0_wait_free30` | 30 s | 20 % |
| VA | `P_pool0_wait_free_any` | always | 20 % |
| V10T | `P_pool0_wait_free10_tight` | 10 s | 10 % |

## Out of sample, daily loss limit 1.0 SOL

| latency | book | entries | mean per entry | P&L SOL | difference vs X0 | band | P&L difference SOL | better |
|---|---|---|---|---|---|---|---|---|
| A | X0 | 304 | -2.3 % | -0.711 | | | | |
| A | V10 | 304 | -2.4 % | -0.720 | -0.0 points | -0.1 to +0.0 | -0.009 | no |
| A | V30 | 305 | -2.3 % | -0.704 | +0.0 | -0.1 to +0.3 | +0.007 | no |
| A | VA | 304 | -2.2 % | -0.682 | +0.1 | -0.3 to +0.5 | +0.028 | no |
| A | V10T | 304 | -2.4 % | -0.720 | -0.0 | -0.1 to +0.0 | -0.009 | no |
| B | X0 | 322 | -1.8 % | -0.593 | | | | |
| B | V10 | 373 | -1.8 % | -0.683 | +0.0 | -1.6 to +1.5 | -0.090 | no |
| B | V30 | 360 | -1.6 % | -0.560 | +0.3 | -1.0 to +1.4 | +0.032 | no |
| B | VA | 364 | -1.6 % | -0.587 | +0.2 | -1.3 to +1.6 | +0.006 | no |
| B | V10T | 373 | -1.8 % | -0.683 | +0.0 | -1.6 to +1.5 | -0.090 | no |

At B the free rides took 40 to 50 more entries than X0 because they hit the daily loss limit less often (28 to 41
skips against 79), a path effect of one loss limit; on the migrations both entered the differences are -0.3 to +0.1
points, every band across zero.

The free rides (the rests are valued over their share of the entry's cost, so a rest sold at the partial sale's price
already shows about +30 %; "against the partial" is what holding it added over selling it with the partial sale):

| latency | book | +30 % seen | spike rule fired | rest median | best | worst | above zero | rests against the partial SOL | rest did better | exits of the rests | X0 vs the ride, same coins (X0 all at +30 %) | ride better |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A | V10 | 66 | 7 (2 %) | +50.7 % | +222 % | +14.8 % | 100 % | -0.010 | 14 % | floor 7 | +82.0 % vs +80.7 % | 29 % |
| A | V30 | 66 | 20 (7 %) | +43.0 % | +297 % | +14.8 % | 100 % | +0.021 | 20 % | floor 19, trail 1 | +67.0 % vs +68.1 % | 30 % |
| A | VA | 66 | 66 (22 %) | +29.1 % | +297 % | -104 % | 95 % | +0.024 | 21 % | floor 59, trail 6, 30 min 1 | +42.6 % vs +43.0 % | 24 % |
| A | V10T | 66 | 7 (2 %) | +53.5 % | +222 % | +12.8 % | 100 % | -0.010 | 14 % | floor 5, trail 2 | +82.0 % vs +80.8 % | 29 % |
| B | V10 | 95 | 7 (2 %) | +31.4 % | +180 % | +12.9 % | 100 % | -0.017 | 29 % | floor 7 | +59.2 % vs +54.2 % | 33 % |
| B | V30 | 91 | 23 (7 %) | +36.8 % | +311 % | +12.9 % | 100 % | +0.021 | 43 % | floor 20, trail 3 | +60.5 % vs +58.7 % | 48 % |
| B | VA | 94 | 94 (26 %) | +27.5 % | +311 % | -104 % | 89 % | -0.176 | 23 % | floor 82, trail 9, 30 min 3 | +41.2 % vs +38.3 % | 26 % |
| B | V10T | 95 | 7 (2 %) | +31.4 % | +180 % | +12.9 % | 100 % | -0.017 | 29 % | floor 4, trail 3 | +59.2 % vs +54.2 % | 33 % |

About nine rests in ten ended at the partial sale's price (VA: 59 of 66 at A, 82 of 94 at B): the coin turns at
about the moment it crosses +30 %.
The few that ran made up for that at A (V30 and VA +0.02 SOL), at the live latency a rest's sale lands about 4 s
after its signal and below its floor on a fast fall, and VA's rests gave up 0.176 SOL, among them a rug that took a
whole rest (-104 % of its cost with its fee). Once the partial sale landed the stake was back (0.101 SOL in the median),
but the rests added nothing.

## Out of sample, daily loss limit 0.25 SOL (the live bot's)

At A and at B all five books made the same 5 entries in one hour (-26.5 % and -26.7 % per entry), none reached +30 %,
then the day's loss stop: no band, no by the rule.

## Robustness and in sample (not judged)

With the trades open across a gap left out, 1.0 SOL: A -0.2 to -0.8 points (VA's band -1.3 to -0.2, below zero), B
+0.1 to +0.5, every band across zero, P&L -0.15 to +0.01 SOL. In sample under 1.0 SOL at A X0 +18.3 %, the rides +17.6
to +18.2 %; at B X0 -0.5 %, the rides -0.3 to -0.4 %.

## What it means

The spike that would carry a free ride is rare, and when it comes it mostly ends right there. Trials: 16
(`strategies.FREE_Y15_TRIALS`). The live bot, P_pool0_wait and every other paper book trade exactly as before
(2026-10-20 replayed before and after the change: 18,707 closed trades and 1,036 failed buys identical field for
field, the 99 skip counts too). V10, V30, VA and V10T run on paper at 0.1 SOL; after two weeks of paper record they
can be looked at again.
