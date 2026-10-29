# E2: entry filters for P_pool0 against farmed completions, linked wallets, wash trading and bad regimes

PAPER ONLY. Nothing here holds a wallet, reads a key, signs or sends anything; the live service, its executor, its
exits, its sizing, its confirmation file and everything in `denied.re` were not touched. The live executor's
`measured.jsonl` was only read (its fill latencies and fees), never its key or its wallet.

Pre-registration: `results/pumpfun_entry_e2_prereg.md` (29 trials, committed before the first run). Code:
`lab/pumpfun_rt/entry_e2.py`; tests: `tests/test_pumpfun_entry_e2.py`. Data: the server's record, 2026-10-20 16:40
UTC to the registered cutoff 2026-10-29 19:30 UTC, signals to 19:18 UTC; in sample the UTC days 2026-10-20 to 23, out
of sample 2026-10-24 to the cutoff (6 days). Every P_pool0 signal entered at 0.05 SOL at the live executor's latency
since 2026-10-29 (34 buys, median 1.4 s; 34 sales, median 0.6 s; 108,938 lamports a transaction); each filter keeps
or skips a signal and is judged against P_pool0 (X0) on the same migrations.

Sources: MemeTrans (arXiv 2602.13480), Meme Coin Factories (arXiv 2609.10246), "The 17.6 SOL ghost"
(onchaindivers.substack.com), Budish, Cramton and Shim (2015) for F5.

## Short answer

**No. None of the five candidates beats P_pool0 by the registered rule, and three of them point the wrong way: on
this record the coins the literature flags as risky are P_pool0's better coins.**

- **F1 farmed completion**: the pattern of the "17.6 SOL ghost" (a curve idle for a while, then bought out) does
  not occur among P_pool0's entries: 1 of 1,915 completions had no curve trade for 60 s before the completing
  transaction (82 for 1 s; 4 not known because of a stream gap). Large completing buys are common, and they are the
  good coins: 32 % of the entries had a completing transaction that bought 99 % or more of the curve's SOL, and every
  in-sample cell that skips large completing buys made -0.4 % to -1.3 % per entry against X0's +13.0 %. The fit
  picked "idle 60 s", which skips that one coin: +0.03 points out of sample, band +0.0 to +0.1, not above 0.
- **F2 linked wallets**: 68 % of the entries have a group of early wallets linked by a shared transaction or slot,
  and on 64 % its sale would drop the pool more than the stop. Skipping those keeps 34 % of the entries, at +1.6 %
  per entry against X0's +7.8 % (-6.2 points, band -8.7 to -3.7); what it skipped made +11.0 %.
- **F3 wash trading**: a wallet buying and selling about the same SOL in one curve transaction is rare: 21 of 1,915
  coins, never more than one such transaction. Skipping them: +0.3 points (band -0.0 to +0.7), not above 0.
- **F4 regime pause**: the outcomes do not cluster (in sample runs test p 0.074, correlation with the stop rate of
  the last 20 closed entries +0.03, p 0.48), so the pause was not fitted or run, as registered.
- **F5 enter later once the snipers hold little**: every delay costs, the longer the more (no sniper condition: -1.6
  points at 5 s, -5.4 at 15 s, -8.7 at 30 s, -11.4 at 60 s, -15.5 at 120 s, every band below 0), and the sniper
  condition makes it worse: the coins whose snipers hold little are worse coins. The in-sample pick (at the
  migration, snipers at most 4.15 % of the supply, 43 % kept) made +1.9 % per entry against +7.8 % (-5.8 points,
  band -9.6 to -1.7).

Nothing is added to the pipeline; the live bot is unchanged.

## 1. Record, entries, what the record can show

1,915 P_pool0 entries (19 failed buys), 645 in sample and 1,270 out of sample. 1,412 migrations were skipped for
"no pool state" and 2,172 as not a plain SOL pool, by P_pool0's own checks. X0 here is X14 r2's path simulator on
this replay; the late-entry code at delay 0 without a condition reproduces it on 100.0 % of the 1,915 entries.

The replay's level is paper: X0 makes +7.8 % per entry out of sample (median +4.7 %, 57 % won, +4.941 SOL on 1,270
entries at 0.05 SOL). The live P_pool0 is far below that (P2 and the live twin); the comparison here is on the same
migrations, so the level cancels.

What the record holds and what not:
- **Every curve was seen from its creation**: a coin created before the record began is never signalled in the
  replay (the engine does not know it), so all 1,915 have their curve's trades. The idle time before the completing
  transaction is not known on 4 (a stream gap across it); F1's idle part never fires on those.
- **No fee payer, no funder**: a curve trade's wallet is the trader; the transfer table starts on 2026-10-29 and
  covers only the 30 minutes after a migration. F2 therefore links wallets by shared transaction and shared slot
  only (MemeTrans' same-funder link cannot be built from this record).
- **The snipers' share is known on every entry** (early.py's sniper book, non-dev buyers within 2 s of the creation;
  37 % of entries have none holding at the migration, the median holds 10.4 % of the supply).

Feature quantiles over the 1,915 entries (10/25/50/75/90 %): idle 0, 0, 0, 0, 0.18 s; completing transaction's
share of the curve's SOL 0.005, 0.015, 0.09, 1, 1; wash transactions 0 to the 90th percentile (max 1); F2's drop
0, 0, 0.65, 0.96, 0.97 (the largest linked group's tokens 0, 0, 14 %, 78 %, 79 % of the supply).

## 2. F4's test first

| window | entries | runs | expected | z | p (fewer runs) | rho with the stop rate of the last 20 | p | rho with migrations of the last hour | p |
|---|---|---|---|---|---|---|---|---|---|
| in sample (the gate) | 645 | 301 | 319.1 | -1.45 | 0.074 | +0.028 | 0.48 | -0.024 | 0.54 |
| out of sample | 1,270 | 612 | 624.9 | -0.74 | 0.23 | -0.014 | 0.63 | +0.049 | 0.08 |

The mean after the last k closed entries were all losses, in sample: k 1 +17.6 % (290 entries; the rest +9.2 %), k 2
+5.8 % (145; +15.1 %), k 3 +3.4 % (63; +14.0 %); out of sample k 1 +4.6 % (540; +10.1 %), k 2 +8.9 % (252; +7.5 %),
k 3 +4.3 % (116; +8.1 %). No sign that losses come in runs that a pause could step around: the gate is not met, and
the pause rule (`pumpfun:entry_e2:F4`, counted) was not fitted or run.

## 3. The filters out of sample (judged)

Mean and P&L per entry over 0.05 SOL after every cost, failed buys included. "vs X0": the filter's mean over what it
keeps minus X0's mean over all 1,270 entries; band: day-block 90 % band of that difference (6 days). Books: the kept
entries in entry order, live sizing (0.05 SOL, 1 open, 0.12 SOL a day) and wide (0.1 SOL, 4 open, 1.0 SOL a day),
reported, not judged.

| filter | fitted in sample | kept | share | mean | median | win | P&L SOL | X0 on the skipped | vs X0 | band | passes | live book: n, mean, P&L | wide book: n, mean, P&L |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| X0 (P_pool0) | | 1,270 | 100 % | +7.8 % | +4.7 % | 57 % | +4.941 | | | | | 351, +4.3 %, +0.753 | 1,129, +7.3 %, +8.295 |
| F1 farmed completion | idle 60 s | 1,269 | 100 % | +7.8 % | +5.0 % | 57 % | +4.958 | -33.6 % (1) | +0.0 | +0.0 to +0.1 | no | 350, +4.4 %, +0.770 | 1,128, +7.4 %, +8.328 |
| F2 linked wallets | drop above 20 % (fixed) | 437 | 34 % | +1.6 % | +13.7 % | 73 % | +0.354 | +11.0 % | -6.2 | -8.7 to -3.7 | no | 216, +1.4 %, +0.155 | 436, +1.8 %, +0.802 |
| F3 wash trading | 1 wash transaction | 1,255 | 99 % | +8.1 % | +5.7 % | 57 % | +5.065 | -16.5 % (15) | +0.3 | -0.0 to +0.7 | no | 348, +4.4 %, +0.759 | 1,115, +7.7 %, +8.568 |
| F4 regime pause | not run (no clustering) | | | | | | | | | | no | | |

F1 skips one entry, F3 fifteen; both raise the mean a little, neither band is above zero (F1's lower end is exactly
0: five of the six days have nothing skipped). F2 keeps the coins without a large linked group, and those make
+13.7 % in the median but crash more often (79 stops at a mean of -59 % against X0's 457 at -36 %): its kept set is
worse, not safer. Without the trades open across a gap: F1 +0.0 (+0.0 to +0.1), F2 -5.6 (-7.8 to -3.0), F3 +0.1
(-0.1 to +0.3).

In sample (645 entries, X0 +13.0 %): F1's 19 cells, the 3 idle-only cells +13.0 % (100 % kept), the 16 cells with a
completing-buy share -0.4 % to -1.3 % (43 % to 51 % kept); F2 -0.2 % (39 % kept); F3 k 1 +13.2 % (99 %), k 2 to 25
+13.0 % (100 %).

## 4. F5: a later entry once the snipers hold little

Thresholds: the in-sample quartiles of the snipers' share of the supply at the migration, q25 0.0 % (no sniper
holding), q50 4.15 %, q75 73.6 %. A cell enters at the migration + d s when the snipers then hold at most the
threshold, else it skips that migration; `_all` cells enter at + d s without a condition (a diagnostic of the
delay). The pick in sample: F5_d0_q50 (+7.4 % in sample on 50 % kept, the best of the 18 cells with 30 % kept).

| cell | in sample: mean, kept | kept | share | mean | median | win | P&L SOL | X0 on the skipped | vs X0 | band | live book: n, mean, P&L | wide book: n, mean, P&L |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| d0 q25 | -0.1 %, 40 % | 455 | 36 % | -0.1 % | +12.4 % | 69 % | -0.014 | +12.2 % | -7.8 | -10.9 to -5.1 | 151, -1.6 %, -0.119 | 453, +0.1 %, +0.041 |
| **d0 q50 (pick)** | +7.4 %, 50 % | 550 | 43 % | +1.9 % | +11.7 % | 66 % | +0.533 | +12.2 % | -5.8 | -9.6 to -1.7 | 142, -1.9 %, -0.138 | 548, +2.1 %, +1.155 |
| d0 q75 | +5.3 %, 75 % | 851 | 67 % | +1.0 % | +3.6 % | 58 % | +0.421 | +21.6 % | -6.8 | -9.6 to -4.3 | 118, -6.2 %, -0.368 | 848, +1.2 %, +0.977 |
| d0 all (= X0) | +13.0 %, 100 % | 1,270 | 100 % | +7.8 % | +4.7 % | 57 % | +4.941 | | +0.0 | | 351, +4.3 %, +0.753 | 1,129, +7.3 %, +8.295 |
| d5 q25 | -1.5 %, 40 % | 457 | 36 % | -0.2 % | +12.7 % | 69 % | -0.037 | +12.3 % | -7.9 | -10.2 to -6.1 | 154, -2.1 %, -0.162 | 455, -0.0 %, -0.005 |
| d5 q50 | +7.0 %, 50 % | 552 | 43 % | +1.9 % | +11.4 % | 66 % | +0.515 | +12.3 % | -5.9 | -9.1 to -2.2 | 224, -1.1 %, -0.125 | 550, +2.0 %, +1.119 |
| d5 q75 | +4.5 %, 76 % | 853 | 67 % | +0.8 % | +2.9 % | 58 % | +0.338 | +21.8 % | -7.0 | -9.5 to -4.8 | 273, -1.6 %, -0.220 | 851, +1.0 %, +0.831 |
| d5 all | +8.5 %, 100 % | 1,270 | 100 % | +6.2 % | +3.7 % | 56 % | +3.941 | | -1.6 | -2.4 to -0.9 | 354, +3.2 %, +0.571 | 1,132, +6.0 %, +6.836 |
| d15 q25 | -3.6 %, 40 % | 457 | 36 % | -0.1 % | +13.0 % | 68 % | -0.032 | +12.2 % | -7.9 | -10.7 to -5.6 | 153, -1.2 %, -0.092 | 455, +0.0 %, +0.005 |
| d15 q50 | +7.0 %, 50 % | 554 | 44 % | +0.7 % | +11.4 % | 65 % | +0.198 | +12.3 % | -7.1 | -9.2 to -4.9 | 212, -0.3 %, -0.031 | 552, +0.9 %, +0.487 |
| d15 q75 | +4.4 %, 77 % | 859 | 68 % | -0.1 % | +2.2 % | 56 % | -0.043 | +22.2 % | -7.9 | -10.0 to -5.6 | 286, -0.9 %, -0.135 | 857, +0.1 %, +0.070 |
| d15 all | +6.4 %, 100 % | 1,270 | 100 % | +2.4 % | +1.9 % | 54 % | +1.506 | | -5.4 | -6.6 to -4.1 | 367, +1.4 %, +0.256 | 1,113, +2.1 %, +2.315 |
| d30 q25 | -2.3 %, 40 % | 457 | 36 % | -1.6 % | +12.2 % | 67 % | -0.357 | +12.2 % | -9.3 | -11.8 to -7.4 | 153, -3.2 %, -0.241 | 455, -1.4 %, -0.644 |
| d30 q50 | +7.3 %, 50 % | 554 | 44 % | -0.6 % | +9.4 % | 64 % | -0.174 | +12.3 % | -8.4 | -10.7 to -6.1 | 216, -0.5 %, -0.051 | 551, -0.5 %, -0.280 |
| d30 q75 | +4.9 %, 77 % | 863 | 68 % | -0.8 % | +2.5 % | 57 % | -0.346 | +22.6 % | -8.6 | -11.0 to -6.1 | 236, +0.2 %, +0.022 | 856, -0.5 %, -0.429 |
| d30 all | +3.8 %, 100 % | 1,270 | 100 % | -0.9 % | +1.7 % | 53 % | -0.576 | | -8.7 | -11.5 to -6.6 | 362, +0.6 %, +0.112 | 1,077, -1.1 %, -1.227 |
| d60 q25 | -4.3 %, 40 % | 457 | 36 % | -1.8 % | +12.2 % | 67 % | -0.406 | +12.2 % | -9.6 | -11.8 to -7.6 | 142, -3.9 %, -0.275 | 455, -1.6 %, -0.743 |
| d60 q50 | -3.1 %, 50 % | 557 | 44 % | -0.8 % | +10.6 % | 64 % | -0.229 | +12.3 % | -8.6 | -11.1 to -6.2 | 228, -1.3 %, -0.145 | 555, -0.7 %, -0.367 |
| d60 q75 | -1.1 %, 78 % | 882 | 69 % | -0.7 % | +3.8 % | 58 % | -0.322 | +23.5 % | -8.5 | -11.8 to -5.0 | 326, -1.1 %, -0.177 | 858, -0.6 %, -0.498 |
| d60 all | -2.7 %, 100 % | 1,270 | 100 % | -3.7 % | +0.3 % | 51 % | -2.321 | | -11.4 | -14.6 to -8.1 | 333, -2.1 %, -0.358 | 977, -2.9 %, -2.861 |
| d120 q25 | -7.2 %, 40 % | 458 | 36 % | -3.7 % | +5.6 % | 64 % | -0.852 | +12.2 % | -11.5 | -15.6 to -6.9 | 111, -2.8 %, -0.157 | 455, -3.6 %, -1.644 |
| d120 q50 | -5.8 %, 50 % | 560 | 44 % | -4.2 % | +2.3 % | 60 % | -1.185 | +12.5 % | -12.0 | -15.9 to -7.9 | 129, -1.7 %, -0.110 | 553, -4.0 %, -2.226 |
| d120 q75 | -1.6 %, 80 % | 943 | 74 % | -5.7 % | +0.5 % | 52 % | -2.687 | +20.9 % | -13.5 | -16.9 to -10.4 | 57, -14.1 %, -0.403 | 779, -5.3 %, -4.160 |
| d120 all | -3.7 %, 100 % | 1,270 | 100 % | -7.7 % | -0.5 % | 48 % | -4.874 | | -15.5 | -19.4 to -11.6 | 70, -12.4 %, -0.434 | 808, -6.1 %, -4.945 |

Every cell's band is below zero except X0 itself. Without the trades open across a gap the pick is -4.0 points (band
-6.7 to -1.2).

**How F5 differs from F3's delay search.** The pump.fun factory F3 drew the delay (migration + 0 to 60 s) as one
gene among its model, heat, pool and exit genes and scored whole strategies on a wallet bootstrap over two days; it
never conditioned on the snipers and never showed the delay on its own. F5 holds P_pool0's exits fixed, isolates the
delay (the `_all` cells, out to 120 s) and adds the snipers' share as the only condition, paired on the same
migrations. The answer is clean on both parts: waiting is paid for at every delay, and "the snipers have sold" marks
the weaker coins, not the safer ones. At our latency the first seconds after the migration are where P_pool0 earns.

## 5. What the record says about the hypotheses (not a trial)

The signals of farming, bundling and sniping (a completing transaction that buys the whole curve, a large group of
early wallets in one transaction or slot, snipers holding much of the supply) all mark the coins on which P_pool0,
in at the migration and out within 300 s, does best. A reading consistent with X14 r2's buyback measurement (an
inferred BOOST buyer on 1,861 of 1,883 entered pools, buying until a median 332 s after the migration): the
organised launches support their pool for the first minutes, and P_pool0 sells before that support ends. The papers'
risk (MemeTrans' collapse within 20 minutes) is real for a holder; a 300-s trade is out before it. This is an
interpretation, not tested here.

## 6. Disclosed after the first run (no change of a trial)

- A code check before the full run: the replay and evaluation on the first 5 hours of 2026-10-20 (35 entries, in
  sample; their numbers were seen).
- The report's formatting was changed after the full run (the F4 line, a no-gap line for F5's pick); the report was
  then written again from the same replay with the committed code. No number changed.
- The lab's data folder was read only where the run was made: the 29 trials were registered into a copy of R5's
  registry before the first number; the server's registry gets them by `python -m lab.pumpfun_rt.entry_e2
  --register-only` (one line per id, never twice).

## 7. What runs on paper

Nothing new: no filter passes, so no strategy joins `pipeline.STRATEGIES`. The live bot, its exits and its files are
unchanged.

## 8. Too early, in any case

Nine days of record, six out of sample, 1,270 paired entries, a latency from 34 live fills over five hours. On this
record the answer is plain: the entry filters from the literature remove P_pool0's winners, and a later entry pays
for waiting.
