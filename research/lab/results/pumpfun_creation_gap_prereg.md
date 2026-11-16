# pump.fun recorder: the creations still missing after C1, and the PumpSwap gaps since 2026-11-03 (pre-registration)

Context: `results/review_2026-10-27.md` (sections 2 and 3), R5's registry (`metrics.trial_pool`,
`<data>/trials/registry.jsonl`), R6's windows (nothing here touches a window: it counts the record), C1
(`lab/pumpfun_rt/collector.py`, `poolread.py`, `coverage.py`, lane 12025). Paper only: the live service, what it reads
at start (`creates`, the tap, `pools.json`), the engine and every wallet stay as they are.

## Question

`reports/pumpfun_rt/coverage.md` shows pool reads near 100 % of migrated coins since C1 but creation rows for only
70.9 % to 85.8 %; PumpSwap gap rows rose from 94 (1,127 s) on 2026-11-02 to 275 to 603 a day since 11-03. Why, and
what in the lab's collector fixes it.

What the diagnosis before this file already saw (looked at, not yet counted as a result; the counts below are made
again by the registered run): on 2026-11-14 coverage's 3-day window misses creation rows that are on record on an
older day, and `creates_late` is partitioned by the creation's block time (rows from 2025-05 on), so the window
misses most late rows; and `poolread.creation` asks `getTransaction` with `maxSupportedTransactionVersion` 0, which
the RPC refuses (-32015) for a version 1 transaction.

## What is counted (one recorded day, 2026-11-14, then each day of coverage.md)

1. Migrated coins (coverage's set: a migration, completion or pool read that day).
2. Of them: a row in `creates` on any day of the record up to the day ("from stream"); not that but a row in
   `creates_late` on any day ("late"); neither.
3. For "neither": whether a read was ever asked (a completion or migration row on record; a coin with only a pool
   read was adopted and never asked), the mint's format (ends in "pump" or not), and, by reading each such coin once
   more with the collector's own reader (`poolread.creation`, the version-1 fix in, at most 2 calls a second, at most
   50 pages of 1,000 signatures, nothing else downloaded): read now, refused for the transaction version with the old
   reader, more than 10 pages (C1's limit), more than 50 pages, oldest transaction without the creation, RPC error or
   rate limit.
4. PumpSwap gaps a day and hour (count, seconds, median length), their overlap (2 s either side) with pump.fun gaps
   and the transfer connection's gaps, and Spearman correlations by hour with the hour's PumpSwap rows, curve trades,
   job seconds from `<data>/_ops/runs` and the PumpSwap receive lag, before (2026-10-28 to 11-02) and after (11-04 to
   11-15).

## Decision rules

- A cause found in the lab collector is fixed there, gated so that the live service's collector (which subclasses it)
  behaves as before; the creation from stream and the creation late are reported apart in coverage.md; the check
  turns red when a full day from the first full day after the deploy has under 95 % of its migrated coins with a
  creation row, stream and late together.
- A gap cause outside the repo (the public endpoint's behaviour) is named with its evidence; the collector gets what
  makes the next day's cause visible (each link's drops, short lives, silences and failed connects in the heartbeat).
- Success: the next full day after the deploy at 95 % or more creation coverage including late reads; otherwise the
  report names the remaining cause from the read log.

## Trials

Three in R5's registry, family pumpfun, counted only (no rule is chosen, no Sharpe): `pumpfun:creation_gap:split`,
`pumpfun:creation_gap:reread`, `pumpfun:creation_gap:amm_gaps`, registered before the run that makes the numbers
(through the registry copy, `PYTHIA_TRIALS_REGISTRY`). Results in `results/pumpfun_creation_gap.md`.
