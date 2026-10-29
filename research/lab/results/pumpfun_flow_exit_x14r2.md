# X14 r2: an order-flow exit for the live P_pool0 at today's latency

PAPER ONLY. Nothing here holds a wallet, reads a key, signs or sends anything; the live service, its executor, its
exits, its sizing and its confirmation file were not touched. The live executor's files were only read (its fills,
fees and ledger rows), never its key or its wallet.

Pre-registration: `results/pumpfun_flow_exit_x14r2_prereg.md` (11 trials in R5's registry, committed before the
first run). Code: `lab/pumpfun_rt/flowexit.py`; tests: `tests/test_pumpfun_flow_exit_x14r2.py`. Data: the server's
record, 2026-10-20 16:40 UTC to the registered cutoff 2026-10-29 18:00 UTC, signals to 17:50 UTC; in sample the UTC
days 2026-10-20 to 23, out of sample 2026-10-24 to the cutoff (6 days). Every P_pool0 signal entered at 0.05 SOL,
every exit on the same entries with the same latency draws (paired by entry).

## Short answer

**No. No order-flow exit beats P_pool0's own exits by the registered rule, and the record says why: most stops are
lost in one pool transaction.** At the latency the live executor measures since 13:26 UTC (sales a median 0.6 s
after their signal), 72 % of P_pool0's stops out of sample were one-transaction stops (77 % counted by slot): the
trade that crossed -20 % alone took the position to where the sale landed, or further. No exit that reacts to the
flow can beat those, so the room for any reactive exit is the remaining quarter.

- The hazard exit HZ(k*) (labels from t + L, L = 0.6 s, so a drop inside the latency is no label; the dump model
  ranks with an out-of-sample AUC of 0.74 to 0.79 a day but Brier skill only +0.01 to +0.04) sells too often: -0.5
  points per entry against P_pool0 (band -1.0 to +0.0).
- The two flow rules picked in sample do nothing useful: the 3-s outflow burst (F1, 8 %) -0.2 points, "dumping as the
  buy lands" (F2, 20 % under the signal price) fired on 3 of 1,258 entries.
- Dump-at-risk (DAR) is worse with a band below zero (-0.6 points, -1.2 to -0.2): the grouped early wallets hold most
  of the supply on most of these coins (median DaR at the landing 0.96), so it has almost no spread to sell on.
- The time stop at 180 s (T, best in sample of 180/240/270) +0.1 points (band -0.5 to +0.7), and the buyback exit
  (BB) +0.4 points (band -0.8 to +1.5): both lean positive, neither band is above zero.
- The live stops since 13:26 (14 to the cutoff, mean -24.8 % after every cost): the mark the stop was sent at was
  -18 % to -28 % (one at -89 %), the 0 to 1.5 s of sale latency added +1.9 points on average (from -11 to +28
  points), fees about 1 point. The -20 % to -33 % landings are the trigger trade's own jump plus a few seconds of a
  falling pool, not slow sales.
- The BOOST buyback ends a median 332 s after the migration (half between 311 and 344 s), after P_pool0's 300 s time
  stop. After it ends the typical pool is flat (median +0.2 % at 60 s) but a minority collapses (mean -33 % at 60 s).

Nothing is added to the pipeline (section 8).

## 1. Latency, record, entries

| scenario | buy, median | sale, median | fee per transaction | L (label shift) | entries | failed buys |
|---|---|---|---|---|---|---|
| (N) the live executor since 2026-10-29 13:26 UTC, judged | 1.4 s | 0.6 s | 0.000109 SOL | 0.595 s | 1,903 | 20 |
| (O) Y8's latency (2026-10-22/23), diagnostic | 10.0 s | 4.4 s | 0.001005 SOL | 4.371 s | 1,903 | 90 |

33 buys and 32 sales of the live P_pool0 from 13:26 UTC to the cutoff, as registered (clipped at 0.2 s). Every P_pool0
signal was entered (no book limit in the replay): 1,883 filled entries at (N) with 171,468 step rows, 1,258 entries
out of sample (11 failed buys). 1,405 migrations were skipped for "no pool state" and 2,162 as not a plain SOL pool,
by P_pool0's own checks. The path simulator's X0 reproduces the pipeline's own P_pool0 in the same replay on 100.0 %
of the 1,883 entries at (N) (exit and return within 1 point; 99.7 % at (O)).

The replay's level is paper: X0 makes +7.6 % per entry out of sample, while the live P_pool0 made -0.044 SOL on 33
trades in the window (the paper to live gap is P2's and the live twin's subject). The comparison here is paired on
the same entries, so the level cancels.

## 2. Measured first

**(a) One-transaction stops** (registered: the run of consecutive pool trades of the crossing's slot by its signer
took the value from above -20 % to at or under where the stop's sale landed):

| | X0 stops out of sample | one transaction | one slot | their mean landing | the rest |
|---|---|---|---|---|---|
| (N) | 451 | 72 % | 77 % | -34.7 % | -39.0 % |
| (O), diagnostic | 445 | 67 % | 67 % | -34.5 % | -42.8 % |

Over two thirds at (N): **the large majority of the stops are one transaction**. Whatever exit reads the flow, it
can act only on the stops where the pool fell in more than one step, about a quarter; the hazard model is the only
one here that tries to sell before the step, and it does not pay (section 3).

**(b) The live stops split.** The registered split needs our sale in the record. The record times every pool trade
by the collector's receive time, which runs 3 to 25 s behind the live executor's clock (its own sales appear that
much later), so a live trade can only be placed by its slot and its exact token amount (section 7). Only 2 of the
14 live stops have their sale in the record that way (5 coins have no pool trade recorded at all, 7 no pool sale of
exactly the tokens sold); on those 2 there is no same-slot sandwich and our own impact is under 0.1 point. The
executor's own records cover all 14: the mark the stop's sale was sent with (fill over 1 + its slip), so the
overshoot past -20 % at the trigger, and the move during the sale's latency, each over the buy's SOL:

| live stop | return (ledger) | fill | mark at the signal | overshoot past -20 % | during the latency | sale latency |
|---|---|---|---|---|---|---|
| GTA | -21.9 % | -20.3 % | -20.5 % | -0.5 | +0.2 | 0.6 s |
| LIDA | -32.6 % | -29.2 % | -21.8 % | -1.8 | -7.4 | 0.0 s |
| THEPM | -22.3 % | -20.7 % | -20.8 % | -0.8 | +0.2 | 0.6 s |
| WIFIO | -20.0 % | -17.7 % | -19.9 % | +0.1 | +2.1 | 0.5 s |
| MCDOGE | -23.5 % | -22.2 % | -18.9 % | +1.1 | -3.3 | 0.4 s |
| ZAIO | -27.2 % | -26.1 % | -19.4 % | +0.6 | -6.7 | 0.4 s |
| AgenC | -22.5 % | -24.4 % | -25.6 % | -5.6 | +1.2 | 0.5 s |
| bright | -16.7 % | -18.3 % | -20.5 % | -0.5 | +2.2 | 0.4 s |
| KATT | -18.7 % | -17.1 % | -19.9 % | +0.1 | +2.9 | 1.5 s |
| CATPOOP | -19.5 % | -18.0 % | -18.2 % | +1.8 | +0.1 | 0.6 s |
| WWAR | -2.3 % | +0.3 % | -27.8 % | -7.8 | +28.1 | 0.4 s |
| X | -30.4 % | -29.5 % | -18.2 % | +1.8 | -11.3 | 0.6 s |
| A1LON | -5.8 % | -3.3 % | -18.5 % | +1.5 | +15.2 | 0.5 s |
| PEPEYE | -83.5 % | -85.5 % | -88.9 % | -68.9 | +3.4 | 0.6 s |
| mean of 14 | -24.8 % | -23.7 % | | -5.6 | +1.9 | |

The slippage setting: every sale goes with min_out 0, so it refuses nothing; its part is 0 by construction. The
rest from the fill to the ledger's return is about -1.1 points (fees). Four of the 14 sales landed more than 3
points under their mark (LIDA, MCDOGE, ZAIO, X: the pool falling in the 0.4 to 0.6 s of the sale, "Zaio" -6.7
points); PEPEYE's -89 % was there in the mark the stop was sent at (one jump past every stop).

**(c) The buyback.** The inferred BOOST buyer (one signer, buys only in this pool and no other, at least 3 buys,
the first within 120 s) was found in 1,861 of the 1,883 entered pools: median 14 buys, the first 7 s after the
migration. Its last buy, seconds after the migration: 10 % 260, 25 % 311, **50 % 332**, 75 % 344, 90 % 352; 1,437
of 1,861 between 300 and 360 s. P_pool0's time stop (300 s after a landing about 1.4 s after the migration) sells
before the buyback ends on about four pools in five (1,524 of 1,861 end after 300 s). The pool's price, log change: from 30 s before the last buy
to it mean -4.0 % (median +2.4 %), after it +30 s -19.8 % (median +0.0 %), +60 s -33.1 % (+0.2 %), +120 s -33.5 %
(+2.2 %, 1,368 pools): the typical pool is flat when the buyer stops, a minority is dumped right then.

## 3. The exits at (N), out of sample (judged)

Every variant is P_pool0 (+30 % take, -20 % stop, 300 s) plus one change; the fitted value is the in-sample best.
Mean and P&L per entry over 0.05 SOL after every cost; stops: the -20 % stop exits; band: day-block 90 % band of the
paired difference (6 days).

| exit | fitted | mean | median | win | P&L SOL | stops | their mean | capture | vs X0 | band | on X0's stops | passes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| X0 (P_pool0) | | +7.6 % | +4.3 % | 57 % | +4.766 | 451 | -36.4 % | 22.1 % | | | | |
| HZ | k 0.5 | +7.1 % | -1.0 % | 46 % | +4.441 | 415 | -34.4 % | 20.8 % | -0.5 | -1.0 to +0.0 | +4.5 | no |
| F1 | 8 % in 3 s | +7.3 % | +1.8 % | 54 % | +4.620 | 329 | -39.0 % | 21.5 % | -0.2 | -0.5 to +0.1 | +4.3 | no |
| F2 | 20 % | +7.6 % | +4.3 % | 57 % | +4.760 | 449 | -36.4 % | 22.1 % | -0.0 | -0.1 to +0.1 | +0.1 | no |
| DAR | 0.994 | +7.0 % | -0.8 % | 46 % | +4.391 | 413 | -33.1 % | 20.7 % | -0.6 | -1.2 to -0.2 | +6.3 | no |
| T | 180 s | +7.7 % | +4.8 % | 58 % | +4.846 | 382 | -34.6 % | 22.2 % | +0.1 | -0.5 to +0.7 | +6.8 | no |
| BB | 45 s, 10 % | +8.0 % | +2.1 % | 57 % | +5.019 | 257 | -39.0 % | 22.7 % | +0.4 | -0.8 to +1.5 | +11.1 | no |

1,258 entries each (11 failed buys). By the rule: HZ, F1, F2 and DAR have a lower mean; T and BB a higher one but
no band above zero, and BB's stops land worse than X0's (-39.0 % against -36.4 %: it sells the mild losers early
and keeps the steep ones). HZ, DAR and T land their stops less badly, as asked, but give up more on the other
trades. Each variant sells many of X0's stopped trades better (column "on X0's stops", +4 to +11 points on those
451) and loses it again on the winners it sells too early. Without the trades open across a gap in the record the
differences are within 0.4 points of these (HZ -0.4, band -0.8 to -0.1). In sample: X0 +12.5 %, HZ +13.5 %, F1
+12.8 %, F2 +12.5 %, DAR +13.1 %, T +13.3 %, BB +13.5 % (645 entries); the in-sample edges did not hold.

Exits out of sample: X0 stop 451, take 375, time 421; HZ hazard 234, stop 415, take 360, time 238; BB its own 570,
stop 257, take 253, time 167; T time 539.

## 4. Books (reported, not judged)

| exit | live book: 0.05 SOL, 1 open, 0.12 SOL a day: entries | mean | P&L SOL | max DD | 0.1 SOL, 4 open, 1.0 a day: entries | mean | P&L SOL | max DD |
|---|---|---|---|---|---|---|---|---|
| X0 | 339 | +4.0 % | +0.679 | 0.252 | 1,118 | +7.2 % | +8.005 | 0.961 |
| HZ | 367 | +4.5 % | +0.820 | 0.252 | 1,119 | +6.5 % | +7.218 | 0.977 |
| F1 | 338 | +4.5 % | +0.755 | 0.252 | 1,122 | +6.7 % | +7.510 | 1.116 |
| F2 | 339 | +4.0 % | +0.679 | 0.252 | 1,118 | +7.1 % | +7.994 | 0.961 |
| DAR | 557 | +9.1 % | +2.533 | 0.170 | 1,120 | +6.5 % | +7.277 | 0.973 |
| T | 350 | +4.5 % | +0.789 | 0.204 | 1,121 | +7.0 % | +7.890 | 1.026 |
| BB | 367 | +4.1 % | +0.755 | 0.204 | 1,125 | +7.0 % | +7.876 | 1.049 |

The live sizing takes a quarter of the entries (one open, and the 0.12 SOL limit stops a day after two or three
stops), and which entries it takes depends on when each exit frees the slot: DAR's +2.53 SOL there comes from the
entries it happened to reach (557 against 339), not from its exits, which lose on the same entries (section 3). The
wide sizing takes almost every entry and keeps X0's order.

## 5. The old latency (diagnostic)

At Y8's latency (sales a median 4.4 s, 0.001005 SOL a transaction) X0 makes +0.0 % per entry out of sample; the
differences: HZ -0.1, F1 +0.1, F2 +0.3 (band +0.1 to +0.5), DAR -0.4 (-0.9 to -0.1), T +0.4 (-0.3 to +0.9), BB +0.7
(-0.3 to +1.4); stops land at -41.3 % for X0. Slower sales leave more room for an exit that reads the landing, but
this line is not judged.

## 6. The hazard models

Walk-forward by UTC day, each day scored by models fitted on the days before only, labels from t + L. `dump10`
(a fall of 25 % within 10 s after the sale would land): AUC 0.65 on 2026-10-22, then 0.74 to 0.79 a day from
2026-10-23 (0.750, 0.753, 0.745, 0.741, 0.789, 0.777 out of sample), Brier skill +0.007 to +0.041. A ranking, but too
little calibrated skill for an exit that must be right on most of what it sells: k* = 0.5 (the least eager in the
registered grid) still sells 234 positions out of sample, most of which would have done better held.

## 7. Disclosed after the first run (no change of a trial)

- A code check before the full run: the replay and evaluation on 6 hours of 2026-10-27 (62 entries; their numbers
  were looked at, inside what became the out-of-sample record). A test then found that the buyback's last-buy time
  was stored in 32-bit floats (about 1 minute of resolution); fixed before the full run.
- The live split: the record's pool times run behind the live executor's clock, so the registered "sale at or after
  the stop's signal" by time found none; it now places our buy and sale by exact token amount in slot order and the
  signal that many slots (0.4 s each) before the sale that the executor's sale latency spans, and adds the
  executor's own records (mark at the signal, fill) for every stop. Both are reported.
- DaR as registered (the union of devs, 2-s snipers and same-slot early buyers) is near 1 on most coins: those wallets
  hold most of the supply after a fast curve (H a median 79 % of the supply at the landing). The registered quantile
  thresholds (0.968 to 0.995) were used as they came.
- `base_supply` and `can_boost` are decoded by the collector but not stored; the buyback is inferred from its
  signer. Storing them would measure it directly (a collector and store change, the owner's call).

## 8. What runs on paper

Nothing new: no variant passes, so no strategy joins `pipeline.STRATEGIES`. The live bot, its exits and its files
are unchanged. The three that lean positive (BB, T and, at the old latency, F2) are not a reason for a shadow by the
registered rule; a later study could register a combination of the buyback's end with the time stop.

## 9. Too early, in any case

Nine days of record, six out of sample, 1,258 paired entries, a latency from 32 live sales over four and a half
hours, 14 live stops. The answer to the owner's question on this record: order flow read while a position is held
does not save P_pool0's stops, because most of them are one transaction; the losses past -20 % are the trigger's
jump and the pool's fall in the half second of the sale.
