# E2: entry filters for P_pool0 against farmed completions, linked wallets, wash trading and bad regimes: pre-registration (2026-10-29)

Written and committed before any replay, feature or filter below was computed. Code (next commit):
`lab/pumpfun_rt/entry_e2.py` (the replay, the features at the signal, the filters, the evaluation), tests
`tests/test_pumpfun_entry_e2.py`. Paper only: nothing here holds a wallet, reads a key, signs or sends anything; the
live service, its executor, its exits, its sizing, its confirmation file and everything in `denied.re` are not
touched; the live executor's files (`measured.jsonl`) are only read, never a key or the wallet. A change to anything
below after the first result is a new trial with a new name.

## Why

The owner asked (2026-10-29) for entry signals the lab has not tested, from a literature pass:

- **MemeTrans** (arXiv 2602.13480): 60 % of migrated tokens fall under 20 % of their migration price within 20
  minutes; grouping wallets by same transaction, same funder and same bundle raises the top-10 share much more for
  high-risk tokens than for the rest.
- **Meme Coin Factories** (arXiv 2609.10246): creator groups; wash trading doubles the graduation rate.
- **"The 17.6 SOL ghost"** (onchaindivers.substack.com, a BOOST write-up): wallets buy out curves that stalled at 50 to
  70 SOL, trigger the migration and sell into the boosted pool together with snipers.
- **Owner note, second wave** (Budish, Cramton and Shim 2015, "The High-Frequency Trading Arms Race"): at 1 to 2 s we
  lose every race at t0, so enter later, once the snipers have sold.

Already tested and not repeated: Y16 (rug model, the first five outside buyers' share, dev sells), Y9 and Y10's select
and trend filters (Y9's curve windows of 60/300/900 s, top-10 and dev share at the completion), Y13's bombers
(creator history, slot-0 buyers), the category gate. Mayhem coins are already skipped (P_pool0 takes plain SOL pools
only). The pump.fun factory F3 searched the entry delay (migration + 0 to 60 s) together with its model, heat and pool
filters, never with a condition on the snipers.

## What was looked at before this plan

Disclosed: Y16's, Y13's, X14 r2's and the live twin's reports and code (`rug16.py`, `bombers13.py`, `selfeat.py`,
`flowexit.py`, `live_twin.py`); the record's schema; the live executor's `measured.jsonl` since 2026-10-29 00:00 UTC
(the latencies and fees below; all its P_pool0 fills are from 13:28 to 18:29 UTC). Nothing else: no feature, filter or
book of this plan was computed.

## 1. Record, latency, entries

- **Record**: every recorded UTC day from the start (2026-10-20 16:40 UTC) to the cutoff **2026-10-29 19:30 UTC**;
  P_pool0 signals until 19:18 UTC (12 minutes before), so every position, also one entered 120 s late, closes inside
  the record. **In sample**: the UTC days 2026-10-20 to 23; **out of sample**: 2026-10-24 to the cutoff (6 days). R6's
  windows (in sample to 2023-12-31, validation to 2026-06-30, lockbox from 2026-07-01) are for market data; the
  pump.fun record begins inside R6's lockbox period, so as every pump.fun study since R6 the split is by UTC day inside
  the record, and nothing else of R6's lockbox is looked at.
- **Latency** (judged, the only scenario): Y5's kernel density in log space (`reallat.LogKDE`) of the live executor's
  P_pool0 fills, `measured.jsonl`, what = fill, mode test, logged from 2026-10-29 00:00 UTC to the cutoff, buys and
  sales apart, clipped to 0.2 to 60 s (as X14 r2):

  | side | lat_ms as logged |
  |---|---|
  | buys (34) | 1036, 2177, 1065, 1395, 1778, 1205, 588, 3672, 1127, 659, 1721, 1375, 1666, 2928, 1353, 1586, 722, 2851, 1353, 2966, 4420, 754, 823, 1088, 1565, 1221, 2669, 1219, 3717, 5125, 1341, 3278, 1992, -59 |
  | sales (34) | 600, 1553, 411, 458, 788, -17, 130, 648, 635, 607, -812, 3449, 546, 407, 7825, 1005, 416, 377, 906, 546, 644, 407, 1505, 579, 429, -477, 2030, 645, 761, 538, 5599, 590, 813, 461 |

  Fee per transaction: the mean of the window's 66 `fee` rows, 108,938 lamports.
- **Entries, the full replay** (X14 r2's, `flowexit.FlowPipe` and `EveryEntry`): every P_pool0 signal
  (`pipeline.BY_NAME["P_pool0"]`, its checks unchanged: a plain SOL pool, the pool state known), at 0.05 SOL, no book
  limit. The buy lands one draw of the buy latency after the signal (key P_pool0, mint, buy) and fills as the paper
  executor does; a failed buy is an entry that lost its transaction fee. For every entry the pool's path from the
  signal to the landing + 600 s (also for an entry whose buy failed, from the signal), with the snipers' holdings at
  every point. **X0** is P_pool0 as it is (+30 % sells all, -20 % stop, 300 s time stop) on these paths, as X14 r2's
  X0 (which matched the pipeline's own P_pool0 on 100.0 % of entries). Every filter below is judged **paired by
  migration** against X0 on the same signals: a filter keeps or skips each P_pool0 signal; what it keeps trades X0's
  trade (F5: its own, later trade on the same migration).

## 2. Features at the signal (only what the record holds at that moment)

The engine keeps, per coin on its curve, the transaction (`tx`, the collector's running number; trades of one
transaction share it), slot and wallet of every trade. **The record holds no fee payer and no funder**: a curve
trade's `user` is the trader; the creation's payer is the dev (`tokens.Token.devs`), already in the dev's group; the
transfer table exists only from 2026-10-29 and only after a migration, so no funder before the signal. Same fee payer
and same funder are therefore not used. A coin created before the record began is never signalled in the replay (the
engine does not know it); counted as such.

- **F1 farmed completion.** The completing transaction: the last curve transaction before the completion. `idle_s`:
  the seconds from the previous curve trade of another transaction to the completing transaction's first trade (from
  the creation when there is none); unknown when a stream gap overlaps that interval (then F1's idle part does not
  fire; counted). `done_share`: the SOL the completing transaction bought over the curve's real SOL after it.
- **F2 linked wallets.** The early buyers: every wallet that bought on the curve within 30 s of the creation (devs
  included). Two early buyers are linked when one of their early buys shares a transaction or a slot (union-find over
  both). A group is two or more linked wallets; H its wallets' tokens at the signal (curve and pool, the engine's
  holdings); x the pool's token reserve at the signal. `link_drop` = 1 - (x / (x + H))^2 of the group with the largest
  H, the price drop if it sold everything into the pool at once; 0 without a group.
- **F3 wash trading.** A wash transaction: a wallet that bought and sold on the curve within one transaction, the two
  SOL amounts within 10 % of the larger. `wash_n`: their number on the coin's curve up to the signal.
- **F4 regime**: per signal, the migrations of the last 60 minutes (every `migrate` row of the record, all coins),
  and the stop rate of the last N X0 entries closed before the signal (all P_pool0 paper entries, kept or not).
- **F5 snipers.** The snipers of a coin: early.py's sniper book, the non-dev wallets that bought within 2 s of the
  creation (`early.SNIPE_MS`). `snipe_share`: their tokens (curve and pool, the engine's holdings) over the supply, at
  every point of the path.

## 3. The candidates (one trial each, F5 every cell)

| id | skips the signal when (or enters) | fitted in sample (the in-sample days) |
|---|---|---|
| F1 | `idle_s` at or above I, or `done_share` at or above S | I in 60, 300, 1800 s, off; S in 0.05, 0.10, 0.20, 0.30, off; both off excluded (19 cells) |
| F2 | `link_drop` above 0.20 (worse than the stop) | none |
| F3 | `wash_n` at or above k | k in 1, 2, 5, 10, 25 |
| F4 | the stop rate of the last N closed X0 entries above L (a pause) | N in 10, 20, 40; L in 0.4, 0.5, 0.6; only if the outcomes cluster (below) |
| F5_d{d}_q{q} | enters at the migration + d s, only when `snipe_share` then is at or under T_q; else skips | none per cell; the pick in sample over the 18 cells |
| F5_d{d}_all | enters at the migration + d s, no sniper condition (a diagnostic of the delay alone) | none; never picked |

d in 0, 5, 15, 30, 60, 120 s; T_q the 25th, 50th and 75th percentile (q 25, 50, 75) of `snipe_share` at the signal over
the in-sample P_pool0 entries. F5's late entry: at the migration + d the pool's state then gives the expected tokens;
the buy lands one draw of the buy latency later (the same draw as X0's, key P_pool0, mint, buy), fills at the state
then and fails (its fee lost) under the expected tokens over 1 + `curve.SLIP_TOL`, as the paper executor; then P_pool0's
exits (+30 %, -20 %, 300 s from that landing), the same sale draws as X0. d 0 with no sniper condition is X0.

**F4's test first** (in sample, X0's entries in signal order), the outcomes cluster when either holds: a Wald-Wolfowitz
runs test on win/loss (return above 0 or not) finds fewer runs than chance, one-sided p < 0.05; or the Spearman
correlation of an entry's return with the stop rate of the last 20 X0 entries closed before its signal is negative with
p < 0.05. Reported, not part of the gate: the mean return after the last k = 1, 2, 3 closed entries were all losses
against the mean after the rest; the correlation with the migrations of the last 60 minutes; the same on the
out-of-sample days. If they do not cluster, F4's pause rule is not fitted or run, and that is its result.

Each fitted value is the in-sample cell with the highest mean return per entry among the cells that keep at least 30 %
of the in-sample entries (ties: the earlier in the list); with none, the filter has no fit and fails. F5's pick is
the same rule over its 18 cells; the 6 `_all` cells are never picked.

## 4. Verdict

Judged out of sample, per entry, on the full replay. A filter (and F5's pick) **passes** only if all three hold:

1. its mean return per entry over the entries it keeps (after every cost, failed buys included) is higher than X0's
   over all P_pool0 entries of the same days;
2. the day-block bootstrap 90 % band of that difference (whole UTC days resampled, both means on the same drawn days,
   5,000 draws, seed 11) lies above 0; with fewer than 5 out-of-sample days with entries, n/a and no;
3. it keeps at least 30 % of X0's out-of-sample entries.

Trades open across a gap in the record are kept (the same for X0); without them, a robustness line. If more than one
passes, the highest out-of-sample mean is the pick.

## 5. Reported (out of sample; in sample the same, not judged)

Per filter: entries kept and their share, failed buys, mean and median per entry, win rate, total P&L (SOL) and its
difference to X0, the exits by kind, the stops' mean, the mean of what it skipped (X0's trades on those signals), the
difference and its band, the fitted value and the in-sample grid. Per feature: how many signals it could be computed
on and why not (F1's idle gaps, coins without early buyers). **Books at two sizings** on the kept entries in entry
order (`flowexit.book`, `pipeline.Risk` with the limits; at 0.1 SOL an entry's result is twice its result at 0.05 plus
one more fee per transaction): the live one, **0.05 SOL, 1 open, 0.12 SOL a day**, and **0.1 SOL, 4 open, 1.0 SOL a
day**; per book entries, mean, total, maximum drawdown. Reported, not judged. The F5 table has all 24 cells.

## 6. Trials

In R5's registry, family pumpfun, before the first number (`entry_e2.trials()`): `pumpfun:entry_e2:{F1,F2,F3}`,
`pumpfun:entry_e2:F4_test` and `pumpfun:entry_e2:F4` (counted whether or not it runs), the 18
`pumpfun:entry_e2:F5_d{d}_q{q}` and the 6 `pumpfun:entry_e2:F5_d{d}_all`. 29 in all, no Sharpe. The lab's data folder
is read only where this first run is made: the run registers into a copy of the registry and the server's registry
gets the same 29 lines by `python -m lab.pumpfun_rt.entry_e2 --register-only` (one line per id, never twice).

## 7. If one passes

It becomes a paper shadow strategy in `pipeline.STRATEGIES` next to P_pool0 (`P_pool0_<id>`, 0.05 SOL, PAPER ONLY).
The live bot, its exits, its files and everything in `denied.re` stay unchanged; whether it goes live is the owner's
call after the shadow. If none passes, nothing is added.

## 8. Too early, in any case

Nine days of record, six out of sample, a latency from 34 live fills over five hours. A pass here is a reason for a
shadow, not for money.
