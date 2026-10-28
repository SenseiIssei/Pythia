# P1: the realistic pump.fun ledger without the trades the late-row bug made. Pre-registration

Registered 2026-10-28 and committed before any count, mean or median of tainted rows was computed. Brief P1 of the
training plan of 2026-10-28, on the review of 2026-10-27 (`results/review_2026-10-27.md`, sections 2 and 3), R5's
registry (`metrics.trial_pool`, `<data>/trials/registry.jsonl`) and R6's windows. Paper only: nothing a live bot, a
wallet or the engine reads changes, and nothing rewrites `<data>/paper/pumpfun_rt/ledger.csv`.

## The bug

Until d84b252 (deployed 2026-10-28 19:40 UTC) the pump.fun engine took a pool trade the collector handed over late
(held until its pool's migration was known) at its old slot time. Realistic paper books then filled pending buys
before they landed and sold on spikes from before the entry. The commit message counts 19 of 713 P_pool0_wait trades
with an exit before the landing (that count is the only number seen before this file).

## The rule, fixed now

`realistic.tainted(row)`: a ledger row is tainted when any of

1. it closed before the deploy (`exit_ms` before 2026-10-28 19:40 UTC, `FIX_MS`) and `hold_s < 0`;
2. `exit_signal_ms < land_ms` (the exit was decided before the buy landed);
3. `land_ms < signal_ms` (the buy landed before its signal).

A field that is empty or not a number leaves its condition false. Rows closed at or after the deploy are never
tainted by condition 1; conditions 2 and 3 hold at any time (after the fix they can only come from a new bug). The
rule applies to every book in the ledger (realistic, `_ideal` twins, R2 and F3), since the bug sat in the engine.

Fills on a late row before the landing (a buy filled at a pool state older than its landing, a negative `slip` far
below the signal price) cannot all be told apart from the ledger alone: a real dump between the signal and the
landing gives the same row. They are not in the rule. Reported next to it only, never used by a reader: the
stricter rule, the chosen one or (closed before the deploy and `slip < -0.5`, a fill at under half the signal
price).

## What reads the rule

Every reader of the realistic ledger skips tainted rows and says how many it skipped: the allocator (A1's
`allocator.paper_trades`, used by A1's daily run, `adaptive_a1.forward` and T9), the calibration line
(`realistic.calibrate`), the readiness ladder (through `realistic.json`'s small and factory books and
`lab.ops.paper_books`), the paper review (`lab.ops.paper_books`), the pump.fun reports (the study's readiness
`study.shadow_stats`, the daily card `card.shadow_yesterday`, `measure.paper_slip`, S17's `shapes17.ledger_entries`).

## The numbers

`python -m lab.pumpfun_rt.taint_p1` reads the ledger once and writes `results/pumpfun_ledger_taint_p1.md`: per book
(`rule` column) and per rule (chosen, stricter), the trades, mean and median return per trade with and without the
tainted rows, before and after the deploy, and the count of rows each condition flags. A measurement, no Sharpe, no
DSR, no pass or fail. Two trials in R5's registry, family hand, counted only, registered before the first number:
`hand:p1:ledger_taint` (the chosen rule) and `hand:p1:ledger_taint_strict` (the stricter one).
