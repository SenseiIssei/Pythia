# P2: the selection gap between the live pump.fun bot and its paper twin. Pre-registration

Registered 2026-10-28 and committed before any count, mean or band of this study was computed. Brief P2 of the
training plan of 2026-10-28, on the review of 2026-10-27 (`results/review_2026-10-27.md`, sections 2, 3 and 5), R5's
registry (`metrics.trial_pool`, `<data>/trials/registry.jsonl`), R6's windows and P1's taint rule
(`realistic.tainted`). Paper only and read only on everything live: nothing a live bot, its sizing, a wallet or the
engine reads changes. Numbers seen before this file: the review's (149 live trades, mean -2.6 % a trade), the
calibration line's (14 matched trades of 41 live and 524 paper, -0.5 points), P1's (+5.9 % a trade for
P_pool0_wait over the whole ledger).

## Inputs (read only)

- Live: `<data>/live/pumpfun_rt/orders.jsonl` (buys sent, filled, failed with their `why`), `ledger.csv` (closed
  trades), `skipped.jsonl` (a coin of the live rule not bought and its first reason, written from 2026-10-23 16:13
  UTC), `seen.jsonl` (every migration the live stream handed the bot, from 2026-10-23 18:21 UTC), `journal.jsonl`.
- Paper: `<data>/paper/pumpfun_rt/ledger.csv` (closed trades), `failed.csv` (paper buys that failed),
  `skipped.jsonl` (the paper twin's skips), `state.json` (`realistic_since`).

## When the live bot was on, and which rule

A run is the records sharing a `run` id (records without one form one unnamed run). It is on from its id's start
second (the unnamed run: its first record) to its last record in orders, ledger (exit_ms), skipped, seen or
journal. Its rule is the commonest `rule` of its ledger, skipped and seen rows; a run without one is left out and
counted. Between runs the bot was off and no signal counts.

## Paper signals

A paper signal is the first row by signal time of a (rule, coin) in the paper ledger or `failed.csv` of P_pool0,
P_pool0_wait or P_cmig_model, signalled while a live run of the same rule was on. Left out and counted: rows
`realistic.tainted` flags (P1) and ledger rows closed by `restart`. A failed paper buy is a signal without a return.

## The live outcome of a paper signal

Live records of the same coin count from MATCH_MS (10 minutes, `realistic.MATCH_MS`) before to MATCH_MS after the
paper signal. In this order:

1. **traded (matched)**: a live buy of the coin filled.
2. **buy failed**: a live buy was sent and none filled; its kind by `realistic.fail_kind` of the failure's `why`
   (6040, which includes "price ran away on landing", not landed, simulation failed, other).
3. a live skip of the coin (the live rule's `skipped.jsonl`), by its reason:
   - **paused**: "paused by the owner";
   - **refused by the wallet or the brake**: "stake paused" (the wallet, its floor or the drawdown brake), "max open
     positions", "max exposure", "above the stake cap", the daily loss and total budget refusals, any "refused";
   - **ran away before the send**: "price ran away (+x %)", the pre-send check;
   - **not seen by the live feed**: "creation not seen", "no pool state" (with or without the stream down);
   - **other**: every other reason (not a plain SOL pool, the blocklist, categories, "no decision"), by name.
4. no skip: **not seen by the live feed** when `seen.jsonl` was being written (the signal at or after its first
   record) and the coin is not in it; **other (seen, no decision)** when it is; **other (no live log yet)** before
   `seen.jsonl` and `skipped.jsonl` existed.

## Live trades without a paper twin

A live closed trade whose coin has no paper signal of its run's rule within MATCH_MS: the paper twin's reason in
the paper `skipped.jsonl` (same rule, coin, window); else "paper row tainted (P1)" or "paper closed by a restart"
when the only paper rows are such; else "paper entered at another time" when a paper row of the coin and rule lies
outside the window; else "no paper record".

## The numbers

Returns per trade (`ret`, each side's own stake). Means over the signals and trades with a return.

- P_all: paper's mean on all its signals; P_m: paper's mean on the matched signals; L_m: live's mean on the same
  matched trades; L_all: live's mean on all its closed trades in the runs.
- **Paper minus live on all live signals** = P_all - L_all, in points a trade. It splits exactly into selection
  (P_all - P_m), same coins (P_m - L_m) and live's own extra trades (L_m - L_all).
- **Which reason costs the most**: the selection gap is the sum over the unmatched reasons r of
  (n_r / n) (mean_r - P_m); each reason's term in points, the largest the costliest.
- Bands: 95 % percentile bootstrap, 2,000 draws, seed 0; paper signals and live trades drawn independently, with
  their reasons and matched pairs carried along.
- All of it once over every live run and once over the signals at or after `realistic_since` (the realistic
  paper model; before it the paper books traded the ideal model).

## The gate line

One line in the calibration report (`reports/pumpfun_rt/realistic.md`, `realistic.json` key `selection`): "paper
minus live on all live signals", P_all - L_all over every live run, with its band. That is the number the readiness
ladder's gate for pump.fun reads: it passes under 2 points (paper may not overstate live by 2 points or more a
trade). No Sharpe, no DSR.

## Trials

Five in R5's registry, family hand, counted only, registered before the first number: `hand:p2:paper_minus_live`,
`hand:p2:selection`, `hand:p2:same_coins`, `hand:p2:reasons` (the per-reason terms) and
`hand:p2:paper_minus_live_realistic` (the realistic-only repeat). The report:
`python -m lab.pumpfun_rt.selection_p2` writes `results/pumpfun_selection_gap_p2.md`.
