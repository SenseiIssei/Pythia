# A rug filter for P_pool0_wait (Y16): result (2026-10-24)

Pre-registered in `results/pumpfun_rugfilter_prereg.md` (committed before the replay). Code `lab/pumpfun_rt/rug16.py`,
`pipeline._build_y16`, `Pipeline.cut_ok`, `RUG_CUT`. Paper only.

## The answer

**No.** No rug rule beats P_pool0_wait under both daily loss limits, neither at the paper model's latency (A, median
1 s) nor at the measured live latency (B, buy median 9.8 s, sale 3.9 s). At B under 1.0 SOL the three twins are
within 3 points of P_pool0_wait with every band across zero; under the live 0.25 SOL limit P_pool0_wait stopped for
the day after 8 or 9 entries, so no band and no by the rule. The one pass is R3 at the paper latency under 1.0 SOL.
The rules cut crashes and winners alike: on P_pool0_wait's own entries at B the rug model at its base rate (R1) cut
17 of 60 crashes and 37 of 174 winners, and what it cut did no worse than what it kept. Nothing changes for the live
bot.

## Setup

Record 2026-10-20 to the cutoff 2026-10-23 23:00 UTC, entries to 22:45 UTC; out of sample from 2026-10-22 00:00 UTC
(the first day with a rug0t model, trained day by day in the replay on 223 and then 413 label rows). One replay,
four books under two latencies and two limits, 0.1 SOL a trade, at most 4 open, 0.001005 SOL a transaction, every
book on P_pool0's latency key, trades open across a gap kept. A crash: a loss beyond 35 % or one pool trade taking
30 % off the price while held (at B 60 of X0's 318 closed trades, 57 of them by the loss).

| book | skips the entry when |
|---|---|
| X0 | `P_pool0_wait`, never |
| R1 | `P_pool0_wait_norug`: P(rug0t) above its base rate |
| R2 | `P_pool0_wait_norug_half`: P(rug0t) above half its base rate |
| R3 | `P_pool0_wait_rugcut`: the first five outside buyers hold more than 40.8 % of the supply (`first5_share`, picked in sample out of 20 rules: +4.9 % per entry kept against +2.8 %, 29 of 145 entries cut) |

## Out of sample

| latency, limit | book | entries | mean per entry | P&L SOL | difference vs X0, band | P&L difference SOL | better | on X0's entries: cut | crashes avoided | winners lost | mean of the cut |
|---|---|---|---|---|---|---|---|---|---|---|---|
| B, 1.0 SOL | X0 | 332 | -2.7 % | -0.909 | | | | | | | |
| B, 1.0 SOL | R1 | 261 | -3.3 % | -0.849 | -0.5 (-3.4 to +2.1) | +0.060 | no | 72 | 17 of 60 | 37 of 174 | +0.2 % |
| B, 1.0 SOL | R2 | 245 | -5.3 % | -1.299 | -2.6 (-6.9 to +1.5) | -0.390 | no | 135 | 30 of 60 | 71 of 174 | -0.1 % |
| B, 1.0 SOL | R3 | 294 | -2.2 % | -0.648 | +0.5 (-3.0 to +3.9) | +0.261 | no | 89 | 24 of 60 | 36 of 174 | -7.9 % |
| B, 0.25 SOL | X0 | 8 | -40.6 % | -0.324 | | | | | | | |
| B, 0.25 SOL | R1 / R2 / R3 | 9 / 18 / 142 | -35.2 / -19.0 / +0.4 % | -0.316 / -0.342 / +0.059 | n/a (X0 2 hours) | +0.008 / -0.017 / +0.384 | no | 1 / 3 / 3 of 8 | | | |
| A, 1.0 SOL | X0 | 307 | -1.1 % | -0.339 | | | | | | | |
| A, 1.0 SOL | R1 | 259 | -0.1 % | -0.031 | +1.0 (-1.3 to +3.5) | +0.308 | no | 70 | 19 of 50 | 35 of 164 | -6.1 % |
| A, 1.0 SOL | R2 | 303 | +4.9 % | +1.477 | +6.0 (-0.9 to +13.5) | +1.816 | no | 129 | 30 of 50 | 66 of 164 | -2.2 % |
| A, 1.0 SOL | R3 | 356 | +4.6 % | +1.624 | +5.7 (+0.4 to +11.7) | +1.963 | yes | 80 | 20 of 50 | 33 of 164 | -7.3 % |
| A, 0.25 SOL | X0 | 9 | -31.7 % | -0.285 | n/a (X0 2 hours) | | no | | | | |

"On X0's entries" is the rule applied to the trades X0 made (path-free); the twins' own books also differ by the
slots and the loss limit a skipped trade frees: most of R2's and R3's extra P&L at A is entries X0 could not take
after its daily loss limit (X0 160 such skips, R3 4). The full tables are in the report the run writes
(`rug16.md`).

## What separates the crashes (X0's out-of-sample entries, 1.0 SOL)

Nothing separates them well. AUC for a crash, A / B: P(rug0t) 0.63 / 0.55, P(rug0) 0.59 / 0.54, the top ten
holders' share at the completion 0.62 / 0.59, the top holder 0.59 / 0.57, the first five buyers' share 0.55 / 0.56
(crashes 0.13 to 0.19 of the supply in the median, the rest 0.04), the outside buyers in the first slot 0.44 / 0.49,
distinct buyers 0.44 / 0.45 (crashes 6 in the median, the rest 18), the pool's SOL 0.53 / 0.54, the creator's holding,
history and dump rate 0.46 to 0.57 (a known history for 3 to 5 crashes only), the dev's sales 0.45 to 0.48 (the median
dev has sold nothing at the migration). The curve's duration is 0 s for 55 % of the entries (created and completed in
the same second, a bundled launch) with about the same crash rate as the rest (18 against 15 % at A). LP status is not
in the record: every pool is made by the migration through the pump.fun program, the same for every coin.

## The live book's trades of 2026-10-23 from 15:00 UTC

Of its crashes (loss beyond 35 %) the replay signalled SHEKEL, SpaceX AI (17:14), ROOM, TRUMP (17:38) and Apple
(18:43) with a pool state: R1 and R2 would have bought all five, R3 skipped ROOM. MrBeast, ChatGPT and DOPHIL were not
signalled with a pool state in the paper record, MITY lost 30.7 %. R1 and R2
would have skipped XOGE (-19 %), YMB (-33 %) and criminal (+20.8 %).

## What it means

At the live latency a rug rule removes about as many winners as crashes, and the crashes look like the rest at the
moment of the buy. Trials: 12 (`strategies.RUGFILTER_Y16_TRIALS`; R3's 20 candidates were chosen in sample). The live
bot, P_pool0_wait and every other paper book trade exactly as before (2026-10-20 replayed before and after the change
with the server's models: 18,872 closed trades and 1,049 failed buys identical field for field, the 109 skip counts
too). R1 to R3 run on paper at 0.1 SOL: R3 from the deploy (its rule is now `pipeline.RUG_CUT`), R1 and R2 once the
daily retrain has written `sel_rug0t` (the server's model folder has none yet). After two weeks of paper record they
can be looked at again.
