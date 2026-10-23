# P_pool0_wait with a 20 % rest after the time stop (Y11): result (2026-10-23)

Pre-registered in `results/pumpfun_runner_prereg.md` (committed before the replay). Code `lab/pumpfun_rt/runner11.py`,
`pipeline._build_y11`, `Exits.runner`. Paper only.

## The answer

**No.** Neither variant beats P_pool0_wait. Keeping 20 % after the 300 s time stop lost money on most coins: the
rests made money on a third (R1) and a fifth (R2) of the trades that kept one, and the worst rests came back with
nothing (a rug: -105 % of the rest's cost, its sale fee included). Over all entries both books are worse than
P_pool0_wait under the 1.0 SOL daily loss limit, with a band of the difference entirely below zero. Under the live
0.25 SOL limit every book stopped for the day after 4 or 5 entries, so there is no band and the answer is no by the
rule. Nothing changes for the live bot. Both run on paper from the deploy, at least two weeks, before anything is
decided.

## Setup

Record 2026-10-20 to the cutoff 2026-10-23 15:00 UTC, entries to 13:45 UTC, split 2026-10-22 03:49 UTC (out of sample
after it, about 35 hours). One replay, the three books under both limits, 0.1 SOL a trade, at most 4 open, Y9's
measured latency (buy median 9.8 s, sale 3.9 s), 0.001005 SOL a transaction, every book on P_pool0's latency key
(a migration's buy and its time-stop sale land at the same moment in all three), trades open across a gap kept.

| book | strategy | the rest after the 300 s time stop |
|---|---|---|
| X0 | `P_pool0_wait` | none, everything sold |
| R1 | `P_pool0_wait_run20` | 20 %: out at -50 %, 30 % under its high once above the entry, or at 30 min |
| R2 | `P_pool0_wait_run20w` | 20 %: out at -70 %, 40 % under its high once above the entry, or at 60 min |

## Out of sample, daily loss limit 1.0 SOL

| book | entries | hours | mean per entry | median | win | P&L SOL | band of the mean | max DD SOL |
|---|---|---|---|---|---|---|---|---|
| X0 | 333 | 32 | -2.0 % | +11.7 % | 54 % | -0.679 | -5.6 % to +1.7 % | 1.195 |
| R1 | 235 | 28 | -6.0 % | -5.2 % | 40 % | -1.418 | -10.1 % to -1.3 % | 1.446 |
| R2 | 218 | 32 | -6.1 % | -4.7 % | 37 % | -1.331 | -9.8 % to -2.4 % | 1.467 |

| book | difference vs X0 | band (hours paired) | P&L difference SOL | better | on the migrations both entered |
|---|---|---|---|---|---|
| R1 | -4.0 points | -7.0 to -1.2 | -0.739 | no | 229, -2.1 points (band -3.4 to -0.8) |
| R2 | -4.1 points | -6.8 to -1.4 | -0.652 | no | 218, -3.5 points (band -4.9 to -1.9) |

The rests (entries that reached the time stop and kept 20 %):

| book | rests | rest made money | beat selling it at 300 s | rests' P&L SOL | against selling at 300 s | worst rest | best rest | rest exits |
|---|---|---|---|---|---|---|---|---|
| R1 | 88 | 33 % | 32 % | -0.349 | -0.547 | -0.021 SOL (-105 %) | +0.042 SOL | stop 44, 30 min 36, trail 8 |
| R2 | 75 | 20 % | 21 % | -0.568 | -0.756 | -0.021 SOL (-105 %) | +0.073 SOL | stop 49, 60 min 18, trail 8 |

The runs the owner saw exist: the rests still held at the hard stop mostly gained (R1 26 of 36, +0.495 SOL; R2 13
of 18, +0.388 SOL). The trail exits came out about flat (8 each, 3 and 2 with a gain). But the rests that hit their
stop (R1 44, R2 49) lost on average 95 % and 94 % of their cost: at this latency the stop lands far below its
trigger, two thirds of them at nearly nothing, as P_pool0's stops did in Y8. Those losses (-0.84 and -0.92 SOL) are
larger than all the gains. The longer holds also keep a slot and the position's full cost in the exposure, so the
runners took about 100 fewer entries and hit the daily loss limit more often (139 and 158 skips against 50).

## Out of sample, daily loss limit 0.25 SOL (the live bot's)

X0 5 entries, -26.7 % per entry, -0.134 SOL; R1 and R2 4 entries each, -38.6 %, -0.154 SOL; two rests each, both
stopped out (-0.039 SOL together). All in one hour: no band, so no by the rule.

## Robustness and in sample (not judged)

With the trades open across a gap left out, the order holds under 1.0 SOL: R1 -4.7 points (band -8.3 to -0.8),
R2 -5.3 (band -10.0 to -1.0). In sample under 1.0 SOL the runners also trail X0 (-1.1 % and -1.5 % against -0.1 %).
Under 0.25 SOL in sample R2 shows +8.1 % per entry over 86 entries against X0's -34.6 % over 14, because X0 hit the
daily loss stop early. That is the half of the record the verdict does not use, and it does not hold out of sample.

## What it means

At the latency we really have, a rest past the time stop is mostly a slower loss. Its upside on a pump is capped
at 20 % of 0.1 SOL, while a rug takes all of it plus a fee. Trials: 4 (`strategies.RUNNER_Y11_TRIALS`). The live
bot, P_pool0_wait and every other paper book trade exactly as before (2026-10-20 replayed before and after the
change: 18,498 closed trades and 1,022 failed buys identical field for field). R1 and R2 run on paper at 0.1 SOL;
after two weeks of paper record they can be looked at again.
