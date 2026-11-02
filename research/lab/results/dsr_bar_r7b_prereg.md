# R7b: the pump.fun DSR per entry with the trial variance net of sampling noise and an effective trial count: pre-registration (2026-11-02)

Written and committed before the code that computes any number below and before any real candidate's new DSR.
Background: the review of 2026-10-27 (`results/review_2026-10-27.md`, sections 2 and 3), R5's registry
(`metrics.trial_pool`, `<data>/trials/registry.jsonl`), R6's windows (in sample to 2023-12-31, validation 2024-01-01 to
2026-06-30, lockbox from 2026-07-01; not used here: every number is on the pump.fun record since 2026-10-22), R7's bar
(`lab/pumpfun_rt/factory.py` `bar`, `deflated`) and the ladder's pump.fun rows (`results/ladder_pumpfun_prereg.md`,
`results/ladder_pumpfun.md`). Paper only: nothing a live bot, a wallet or the engine reads changes; no candidate is
armed; the ladder proposes only.

## Why

Step 2 of the four pump.fun rules (`P_pool0`, `P_pool0_wait`, `P_pool0_wait_norug_half`, `P_cmig_model`) reads a DSR
per entry against SR0 = sd(F3's trial Sharpes) x E[max of N normals]. Two things in it are not honest:
the variance is raw, so it holds each F3 trial's own estimation noise (about 1 / entries, F3's trials have 20 to a few
hundred), which the candidate's own noise term counts once more; and N counts every Optuna trial of F3 as independent
although many are near copies. Both push the bar up. Netting them out can also push it too low, so the new bar must
first hold its false pass rate on simulated families with no edge.

## (a) The trial variance net of sampling noise

Over F3's trials with at least `MIN_ENTRIES` (20) entries, as today: V_raw = their Sharpes' variance (ddof 1). Each
trial's sampling variance is q_i / n_i, n_i its entries (not its day-clustered effective entries: the smaller noise,
so the higher bar), q_i = 1 - skew_i SR_i + (kurt_i - 1) / 4 SR_i^2 (the same fat-tail term as `metrics.deflated_sharpe`),
q_i taken as 1 where it is not above 0. M = the mean of q_i / n_i.

  V_new = max(V_raw - M, M)

The floor M: the spread of true Sharpes is never taken below one trial's average sampling variance. Under no edge
V_raw is about M, so the new bar is then about the old one; it can only fall where F3's trials really differ.

## (b) The effective number of trials

Only F3's part of N gets an effective count (R5's other trials are per-day Sharpes of daily books without return series
here; they stay counted one each). F3's trials are clustered on their stored day P&L (`day_pnl` over `days`):

- the trials with no entries are one cluster;
- a trial with entries but no stored day series, or fewer than `EFF_MIN_DAYS` = 5 days, is its own cluster;
- the rest: each series standardized over its days, the market day (the mean of the standardized series on each day)
  taken out by a least-squares slope per trial; between two trials the correlation of these residuals over their shared
  days (at least 5 shared days, else 0); average linkage on 1 - correlation, cut at 1 - `EFF_CORR`, `EFF_CORR` = 0.9
  (near copies only; R6's weekly factory uses 0.5 on years of days, here at most 8 days).

N_eff(F3) = the number of clusters. The new N over all = R5's trials (with the ladder's own) + N_eff(F3); over the
family = R5's pumpfun trials + N_eff(F3). The new bar SR0_new = sqrt(V_new) x E[max of N_new normals]
(`metrics.expected_max_sharpe`), the new DSR = `metrics.deflated_sharpe` with SR0_new on the candidate's day-clustered
effective entries, skew and kurtosis, exactly as the old.

## (c) The simulation that must pass

Synthetic F3 families with the shapes measured from the stored F3 ledger at run time: the same number of trials, nights
and days per night (each trial's series covers its night's days, trials of nights without day series have none, as in
the ledger), entries per trial resampled from F3's (zeros included), entries spread evenly over the trial's days.
A family is built from genomes: each trial is a copy of an existing genome with probability 1 - 1 / C, else a new one;
a copy shares 80 % of its entries with its genome (the same coins), the rest its own. A per-entry return is
rho e_day + sqrt(1 - rho^2) e, e_day one draw a day for the whole family, e from the tail shape.

Shapes (zero edge, every one must pass): C (mean trials per genome) in {1, 5, 25} x rho in {0, 0.1, 0.3} x tails in
{normal, F3's: minus a lognormal with sigma 0.44, standardized: skew -1.46, kurtosis about 7.2, F3's median skew -1.46
and kurtosis 7.2}, 18 shapes, plus a small family (100 trials, C 5, rho 0.1, F3 tails). 200 families a shape, seed
20261102. The candidate is the worst case: the trial with the highest Sharpe among those with at least 20 entries,
selected and judged on the same entries, its DSR against its own family's bar (N = the family's count, raw for the old,
N_eff for the new). A false pass is a DSR of 0.95 or more. **Passes if the new bar's false pass rate is at most 5 % in
every zero-edge shape.** The old bar's rate is reported beside it.

Power (reported, not a condition): (1) in sample, C 5, rho 0.1, F3 tails, one genome with a true Sharpe per entry of
0.25 or 0.5 (all its copies): how often the best trial passes and belongs to it; (2) forward, the ladder's case: a
candidate of 1,000 entries over 10 days with a true Sharpe per entry of 0.05, 0.1, 0.2 or 0.3 (F3 tails, entries
correlated within a day at rho 0.1), its DSR on its day-clustered entries against each null family's new and old bar
with today's R5 count added to N.

The test suite reproduces the false pass rate on a small simulated family (fewer trials and families, same code).

## (d) The rule for the ladder

Only if (c) passes: the ladder computes the new DSR per entry over all and over the pumpfun family for each pump.fun
rule, shows it as a column beside the old, and step 2's two DSR conditions read the new one (pass at 0.95 as before);
the days still needed to step 2's bar use SR0_new. If (c) fails: the ladder stays as it is, and the results say which
shape failed. Nothing else on step 2 changes (20 entries, 10 scored days, lat 2x, P1's taint, realistic execution).

## Trials

Four new numbers on real candidates, one per rule: `pumpfun:r7b:<rule>`, family `pumpfun`, counted in the ladder's own
pool beside `pumpfun:ladder:<rule>` and registered with the ladder's next report. The P3 10 EUR books of the rules,
where their per-trade record is readable, are shown with old and new DSR in the results as well and counted the same
way (`pumpfun:r7b:<book>`). The simulation makes no number on real data and is no trial.

## Output

`results/dsr_bar_r7b.md`: the measured F3 shapes, the simulation table (false pass old and new per shape, mean N_eff
against the true genome count, mean SR0), the power, old against new (V, N, SR0, DSR all / pumpfun) per candidate, and
the days still needed at each rule's current mean per entry under the new bar.

## Amendment (2026-11-02, after a 10-family trial run of the simulation code, before its full run and before any number on a real candidate)

In the trial run the clustering merged independent trials: a trial with fewer entries than days has P&L on its first
days only, so two such trials share the same pattern of zeros and correlate near 1. Clustered now are only trials with
at least `MIN_ENTRIES` (20) entries and at least `EFF_MIN_DAYS` (5) days with P&L; every other trial with entries is
its own cluster. This counts more trials, so the bar can only rise against the text above. Nothing else changes.
