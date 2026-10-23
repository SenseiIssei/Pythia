# P_pool0_wait with a ratcheting profit floor (Y12): result (2026-10-23)

Pre-registered in `results/pumpfun_lock_prereg.md` (committed before the replay). Code `lab/pumpfun_rt/lock12.py`,
`pipeline._build_y12`, `Exits.lock`. Paper only.

## The answer

**No.** No floor beats P_pool0_wait, neither at the paper model's latency (A, median 1 s) nor at the measured live
latency (B, buy median 9.8 s, sale 3.9 s). Under the 1.0 SOL daily loss limit every difference is within a few
tenths of a point of zero with a band across it and every total P&L is lower. Under the live 0.25 SOL limit
P_pool0_wait stopped for the day after 5 entries in one hour: no band, so no by the rule. The floors fire on a fifth
to a quarter of the trades, and on those trades P_pool0_wait itself did about as well: what a floor saves from a
stop it gives up from the +30 % take profits. Nothing changes for the live bot.

## Setup

Record 2026-10-20 to the cutoff 2026-10-23 16:00 UTC, entries to 15:45 UTC, split 2026-10-22 04:19 UTC (out of sample
after it, about 36 hours). One replay, four books under two latencies and two limits, 0.1 SOL a trade, at most 4
open, 0.001005 SOL a transaction, every book on P_pool0's latency key, trades open across a gap kept.

| book | strategy | floors (arm, floor) |
|---|---|---|
| X0 | `P_pool0_wait` | none |
| F1 | `P_pool0_wait_lock` | +10 % then +2 %, +20 % then +10 %, all |
| F2 | `P_pool0_wait_lock_tight` | +8 % then +3 %, +15 % then +9 %, all |
| F3 | `P_pool0_wait_lock_half` | as F1, half at the first floor, the rest at the second |

## Out of sample, daily loss limit 1.0 SOL

| latency | book | entries | mean per entry | P&L SOL | difference vs X0 | band | P&L difference SOL | better |
|---|---|---|---|---|---|---|---|---|
| A | X0 | 312 | -1.6 % | -0.514 | | | | |
| A | F1 | 383 | -1.5 % | -0.586 | +0.1 points | -1.8 to +1.9 | -0.072 | no |
| A | F2 | 316 | -2.0 % | -0.618 | -0.3 | -1.6 to +0.9 | -0.105 | no |
| A | F3 | 319 | -1.9 % | -0.594 | -0.2 | -1.0 to +0.5 | -0.080 | no |
| B | X0 | 330 | -1.8 % | -0.606 | | | | |
| B | F1 | 391 | -2.1 % | -0.813 | -0.2 | -2.5 to +1.8 | -0.207 | no |
| B | F2 | 399 | -2.1 % | -0.833 | -0.3 | -2.7 to +1.9 | -0.227 | no |
| B | F3 | 382 | -1.9 % | -0.737 | -0.1 | -1.9 to +1.6 | -0.131 | no |

On the migrations both entered (not judged) the floors are +0.5 to -0.2 points, every band across zero. F1 and F2
took more entries because they hit the daily loss limit less often (B: 14 and 7 skips against 75), but the extra
entries lost as much as the others.

The trades where a floor fired, against X0's trade on the same migration:

| latency | book | fired | of closed | their mean | X0 there (paired) | floor better | X0's exits there |
|---|---|---|---|---|---|---|---|
| A | F1 | 84 | 22 % | -0.0 % | -0.7 % (62) | 52 % | take 27, stop 24, time 11 |
| A | F2 | 76 | 24 % | +1.8 % | +2.5 % (73) | 47 % | take 35, stop 27, time 11 |
| A | F3 | 64 | 20 % | -1.1 % | -0.5 % (61) | 51 % | take 27, stop 24, time 10 |
| B | F1 | 85 | 22 % | +4.8 % | +4.3 % (67) | 45 % | take 33, stop 24, time 10 |
| B | F2 | 102 | 26 % | +3.7 % | +4.8 % (79) | 47 % | take 39, stop 29, time 11 |
| B | F3 | 83 | 22 % | +3.6 % | +4.3 % (67) | 48 % | take 33, stop 24, time 10 |

Of the coins that fell back to a floor, 44 to 49 % came back up to +30 %; P_pool0_wait sold those at the take profit,
the floors at +2 to +10 %. At B the floor's sale lands about 4 s after the signal, below the floor on a fast fall,
so the live latency costs the floors a little more than the paper latency (P&L difference -0.07 to -0.11 SOL at A,
-0.13 to -0.23 at B).

## Out of sample, daily loss limit 0.25 SOL (the live bot's)

At B all four books made the same 5 entries in one hour (-26.7 % per entry, -0.134 SOL; no floor fired) and then
stopped for the day: no band. At A X0 and F3 did the same; F1 and F2 had a floor sale among the first trades, missed
the day's stop and went on to 187 entries (+1.8 % and +1.3 % per entry, +0.330 and +0.238 SOL). That is the path of
one loss limit, with no band against X0, and at the paper latency only: no by the rule.

## Robustness and in sample (not judged)

With the trades open across a gap left out the picture holds (1.0 SOL: A +0.2 to -0.5 points, B +0.1 to -0.4, every
band across zero, every P&L lower). In sample under 1.0 SOL at A all four are within +0.7 points (+18.0 % to
+18.7 %); at B F1 -0.4 % against X0's -0.5 %, F2 -2.2 %.

## What it means

A floor inside the 300 s neither helps nor hurts much: it turns some stops into small gains and as many take profits
into small gains. Trials: 12 (`strategies.LOCK_Y12_TRIALS`). The live bot, P_pool0_wait and every other paper book
trade exactly as before (2026-10-20 replayed before and after the change: 18,573 closed trades and 1,028 failed buys
identical field for field). F1 to F3 run on paper at 0.1 SOL; after two weeks of paper record they can be looked at
again.
