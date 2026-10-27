# T1: a leak harness. Pre-registration

Registered 2026-10-27 and committed before the harness ran on any real data.
Brief T1 of the training plan of 2026-10-28, on the review of 2026-10-27
(`results/review_2026-10-27.md`, sections 2 and 3), R5's trial registry and
R6's windows. Code: `lab.leak` (written after this file). Report:
`reports/leak/latest.md` (weekly job `leak-check`). Nothing here may change
once a result exists.

## Question

Can any number in the lab come from the future? Checked by a machine: every
function that turns data into a feature, a weight or a model input is run on
the full data and on copies where every value after a time t is replaced, for
a sample of t. Deflated Sharpe and PBO do not catch this (a deliberately leaky
rule passed both, arXiv 2608.27734), so the check is on the functions, not on
their returns.

## The test

For a function f from a panel (arrays with time on the first axis) or a frame
of rows with a known-at time column to outputs per time:

- **Look-ahead.** For each sampled t (n quantiles of the time range between
  50 % and 95 %), three copies of the input: every row after t shuffled in
  time, shifted (rolled) in time, or set missing (NaN, a flipped bool, a null).
  Any output at or before t that differs from the full run (NaN equal to NaN,
  relative tolerance 1e-9) is a leak, reported with the first t, the first
  time that moved and the column.
- **Recursive.** The input cut at t (rows after t dropped): every output at or
  before t must equal the full run's.
- An exception on a changed copy is reported as "could not check", not as a
  pass.

## What is checked

1. Every G1 genome the strategy factory (weekly and F2) sends to the
   validation window: `build.weights` on the factory's context. A failing
   genome is rejected before its held-back look and logged with the reason
   (`<data>/factory/leaks.jsonl`, `factory/small/leaks.jsonl`), never picked
   again.
2. Every feature of `lab.features` at each frequency it is defined at, through
   `registry.frame` on its group's table (the newest rows of the real table
   when there are any, else a synthetic table of the columns the feature
   reads), and C1/C2's candle windows.
3. The zoo's feature builders: M8 (and the 7-day forward target's inputs, the
   same panel) and M10 from hourly bars (and M10's funding and open interest),
   M12 from the BTC and SPY closes; G2's specs (their G1 trees on the target's
   panel, and no input a builder check found leaking) before each held-back
   look, rejected and logged in `models/factory/holdout.jsonl` as
   status "leak"; weekly, the active G2 shadows.
4. The paper books' weight functions in `lab/paper` that take a panel:
   families (tsmom_top20, breakout_top10, tsmom_tranches, and the same on the
   Alpaca universe), tranches_filtered (both), memes (both), btc_gated,
   perps_neutral's low-vol target, smallaccount's S1 books, exit_shadow's live
   books; and the panel builder they share (`fam_common.panel_from`).
5. Planted leaks the harness must catch, one per kind, in the tests: a feature
   that reads t+1, a label shifted one day used as an input, a centred rolling
   window, a genome tree that reads tomorrow, a weight function on tomorrow's
   return.

A failing feature, zoo builder or book is a red line in the health check
(`leak <kind> <name>`). A real one that fails is fixed when the fix is small,
otherwise named in the report.

## Trials

The harness makes no performance number: it answers yes or no per function,
on no window of returns. It registers no trial in `<data>/trials/registry.jsonl`
and does not look at the validation or lockbox windows' returns. A genome or
spec rejected for a leak stays the trial it already was in its ledger.
