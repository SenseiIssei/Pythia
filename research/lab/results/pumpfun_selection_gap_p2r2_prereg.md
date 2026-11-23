# P2R2: P2's paper minus live gap on the realistic era only. Pre-registration

Registered 2026-11-23 and committed before any gap, part, mean or band of this study was computed. On P2
(`results/pumpfun_selection_gap_p2_prereg.md`, `results/pumpfun_selection_gap_p2.md`), G1
(`results/pumpfun_gap_reconcile_g1.md`: P2's same-coin part comes mostly from the ideal paper era, +23.4 points on
34 pairs), the pool state fix (`results/pumpfun_pool_state_fix.md`), P3's gate (`results/ten_eur_p3_prereg.md`, a gap
under 2 points), R5's registry (`metrics.trial_pool`, `<data>/trials/registry.jsonl`), R6's windows (all of it lies in
the lockbox, from 2026-07-01) and R7's day-clustered band. Paper only and read only on everything live: nothing a live
bot, its sizing, a wallet or the engine reads changes; no live trade is asked for.

Numbers seen before this file: P2's daily line in `reports/pumpfun_rt/realistic.md` (+8.8 points a trade, band +1.9
to +15.5, 696 paper signals, 186 live trades; selection -5.3, same coins +14.0, live's own trades +0.2), G1's (12 of
37 live trades after the cut with a paper row and a twin, paper minus live +9.3 on them), the pool fix's, and the
count of live closed trades signalled after the cut: 37, all P_pool0, on two UTC days (2026-10-29: 34, 2026-10-30:
3). The live bot is off (`reports/pumpfun_rt/live_status.json`), its last trade 2026-10-30.

## What is measured

P2's method and decomposition unchanged (`lab.pumpfun_rt.selection_p2`: the runs, the paper signals, the live
outcome of each, the live trades without a paper twin, the reasons), on a narrower sample:

- Live: the closed trades (test or full) of the three rules signalled at or after 2026-10-28 19:40 UTC (P1's cut,
  `realistic.FIX_MS`, as G1).
- Paper: the first row of a rule and coin (ledger or failed buy) of P_pool0, P_pool0_wait, P_cmig_model signalled at
  or after the cut while a live run of the rule was on. All of it is on the realistic model (`realistic_since`
  2026-10-24 01:43 UTC). With the pool state fix: the ledger rows on which G1's stale fill holds
  (`realistic.stale`, the keys of `results/pumpfun_pool_state_fix_rows.json`) are left out and counted, as P1's
  tainted rows and the restart rows, which is how `realistic.md`'s P3 table and the ladder read the ledger since the
  fix. A paper twin left out so is named in the live-only table ("paper row on a stale pool state").
- The numbers: P_all, P_m, L_m, L_all; paper minus live on all live signals P_all - L_all, in points a trade, and its
  exact split into selection (P_all - P_m), same coins (P_m - L_m) and live's own trades (L_m - L_all); the
  selection part by reason, (n_r / n) (mean_r - P_m).
- Shown with it: the live trades, the paper signals, the matched pairs and the UTC days it rests on.

## The band

R7's: the standard error clustered by UTC day (the sandwich with G / (G - 1), G the UTC days with a paper signal or
a live trade of the sample) and the 95 % band with Student's t on G - 1 degrees of freedom. Every number above is a
smooth function of means, so each paper signal and each live trade gets its influence on it (the linearization;
a matched pair's live return goes with its paper signal), summed per UTC day of its signal. Under two days no band.
Next to it, for the comparison with P2's line only, P2's own band (95 % percentile bootstrap, 2,000 draws, seed 0,
paper and live drawn independently).

## Too few to judge

Below 30 live trades or below 5 UTC days with a live trade the result reads "too few to judge": the number and its
band are shown, no pass or fail is said. 30 trades: under it a mean of returns this skewed (a live trade
runs from -100 % to several times its stake) has no standard error worth reading. 5 days: with fewer clusters the t
factor (12.7 at two days, 2.8 at five) and a standard error from so few days give no usable width.

## The trades still needed

From the R7 band: with n live trades on G days and the gap's clustered standard error se, the smallest N with
2 t(0.975, G_N - 1) se sqrt(n / N) under 2 points, G_N = ceil(N G / n) (the days grow at the rate the sample had
while the bot ran, n / G trades a day; the paper signals grow in proportion). Reported: N - n more live trades, the
days of running at n / G a day, and at today's rate (the bot off: no trade since 2026-10-30) never. Arithmetic on
the band, not a trial.

## The lines

- `reports/pumpfun_rt/realistic.md` (`realistic.daily`, `realistic.json` key `selection_r2`): one line under P2's,
  daily from the ledgers: the gap, its R7 band, n live trades on G days, the three parts and "too few to judge" when
  so. P2's line and `realistic.json`'s `selection` stay as they are.
- The ladder (`lab.ops.ladder`, step 5 of the pump.fun rules): the P2R2 number next to P2's in the condition's text.
  The gate keeps reading P2's `selection`; whether P3's gate should read this line instead is the owner's decision,
  and the result says so.

## Trials

Five in R5's registry, family hand as P2's, counted only, registered before the first number:
`hand:p2r2:paper_minus_live`, `hand:p2r2:selection`, `hand:p2r2:same_coins`, `hand:p2r2:reasons` and
`hand:p2r2:stale_kept` (a sensitivity: the same gap with the stale rows kept, the paper as it was before the fix).
No Sharpe, no DSR. `trial_audit` declares the study (5, hand). The report:
`python -m lab.pumpfun_rt.selection_p2r2` writes `results/pumpfun_selection_gap_p2r2.md`.
