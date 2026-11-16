# The stale pool state G1 found: the paper fix and every rule book restated. Pre-registration

Registered 2026-11-16 and committed before any number of this study was computed. On the review of 2026-10-27
(`results/review_2026-10-27.md`, sections 2 and 3), R5's registry (`metrics.trial_pool`,
`<data>/trials/registry.jsonl`), R6's windows (in sample to 2023-12-31, validation 2024-01-01 to 2026-06-30, lockbox
from 2026-07-01), R7's band (`factory.by_day`, as `lab.ops.ladder` reads it), P1's taint rule (`realistic.tainted`),
G1 (`results/pumpfun_gap_reconcile_g1.md`, `reconcile_g1.stale_fill`) and the readiness ladder (`lab.ops.ladder`).
Paper only: nothing a live bot, its rules, sizing, wallet, keys or caps read changes.

Numbers seen before this file: G1's result (HEXN 2026-10-29, paper +209 % against live +31 %; from P1's cut 52 of 641
P_pool0 rows on a stale state, +26.1 % against +2.8 %, 54 of 770 P_pool0_wait rows, +39.4 % against -0.6 %), and the
task's two lines: P_pool0_10eur's paper wallet 0.109 to 2.68 SOL, the weekly page's "4.76 EUR for 180 EUR a month".
No ledger row, report or replay of this study was read before this file.

## The defect and the rule

`sim.Engine.pool_state` takes the pool's reserves read from the chain only while the stream has given no pool trade
of the coin; a read of a later slot than that trade is dropped, so a buy landing before the next pool trade fills on
the older trade's state (HEXN: one pool trade in the migration slot, the read 81 slots later, the paper fill at a
third of the read's price).

The rule: the coin's state is the newest by slot of its pool reads and pool trades. A read counts when no pool trade
was given yet or its slot is later than the slot of the last pool trade taken (`tok.amm_slot`); a pool trade of an
older slot than the state's (read or trade) moves holdings but not the state, as today. A read without a slot counts
only while no state is known, as today. A read and a trade of the same slot: the trade's state stays (the read does
not say where in the slot it was taken).

Where: the live service imports `sim.Engine` (`live_service.load_engine`), so the rule is a flag of the engine,
`fresh_pool`, off by default; the pipeline's paper books (`live.Shadow`) and this study's after run set it. Off: the
live service, the live twin and every earlier study's replay, unchanged. If the rule could not be kept off the live
path, the study stops and reports.

## The test

A test from the HEXN case (a migration, one pool trade in its slot, a read 81 slots later with twice the quote, the
buy landing after the read with no pool trade between): with the flag the state and the fill are the read's; without
it the old state (G1's strict xfail keeps pinning the default). Red before the fix, green after.

## The books restated

P_pool0, P_pool0_wait, P_cmig_model, P_pool0_wait_norug_half (realistic, the live sizing on a 0.55 SOL paper
wallet, `realistic.books`), the three 10 EUR books P_pool0_wait_10eur, P_pool0_10eur, P_cmig_model_10eur
(`realistic.ten_books`, TenWallet), R2's three P_pool5 books (`realistic.small_books`) and E1's 30 forward books
`<rule>@e1_<pair>` (`slippage_e1.shadow_books`): 40 books.

## The window and the replay

Signals from 2026-10-24 01:43 UTC (R1's switch, the ladder's `PF_REAL_FROM_MS`) to 2026-11-15 24:00 UTC (the last
full UTC day), the record's days 2026-10-24 to 2026-11-15 through `sim.replay`, the creator, wallet and sniper books
warmed on the days before, entries until 15 minutes before the end. Two runs, identical but for the flag: before
(off, the engine as it ran) and after (on). The engine as the shadow builds it (select, trend and social trackers,
the shadow's models and the name categories as they are on the day of the run, the model filter), the books with the
realistic executor (`realistic.RealExecutor`) on the day's fit and the live sizing settings as they are on the day of
the run; the owner's block list and the category rule of the live twin left out (both runs). The replay runs today's
engine, so P1's late-row bug does not arise in it; on the ledger P1's tainted rows stay out. The models and fit are
today's, so a book's level is not out of sample; the difference between the runs is the fix alone.

## The measure

Per book and run: entries (closed trades and failed buys, a failed buy its fee over the book's median stake, as
`ladder.pf_entries`), the mean per entry and R7's 95 % band clustered by UTC day (`factory.by_day`). The change in
points (after less before). The share of entries whose entry price moved: entries of both runs matched by coin and
signal time, closed in both, the entry price differing by more than one part in a million; the entries in one run
only counted. Then what P3's gate (`realistic.ten_status`) and the ladder's pump.fun rows (`ladder.pf_context`) read
on the ledger with the rule below.

## The ledger

`<data>/paper/pumpfun_rt/ledger.csv` is not rewritten, its history stays. The rows the defect made are skipped and
counted by every reader of these books, as P1's are: a closed row of a book above, signalled from the window's start
to the ledger's end at the run, not P1-tainted and not a restart, on which G1's `stale_fill` holds (the coin's first
pool read after a pool trade of an older slot and before the landing, no pool trade between the read and the fill).
Their keys (a hash of book, coin and signal time, no address) go into `results/pumpfun_pool_state_fix_rows.json`;
`realistic.md` (the P3 table, R2's wallets, E1's forward table) and the ladder skip them and say how many, with
their P&L. From the deploy of the fix the shadow fills on the newest state and no new row is skipped; the rows
between the run and the deploy are not checked (said in the result). Failed buys are not skipped.

## Trials

R5's registry, family pumpfun, counted only, no Sharpe: `pumpfun:pool_fix:<book>` per book (n 2, before and
after), `pumpfun:pool_fix:ledger_stale` (n 1). Registered before the first number. No DSR, no pass or fail; the
fix ships either way, it changes no live setting.
