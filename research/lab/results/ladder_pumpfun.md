# The live bot's pump.fun rules on the readiness ladder, judged per trade (2026-10-29)

Pre-registration `results/ladder_pumpfun_prereg.md` (its own commit, before this code). Code: `lab.ops.ladder`
(`PF_RULES`, `pf_context`, `pf_record`, `pf_tested` to `pf_execution`); the ladder report `reports/ladder/latest.md`
now has one row per rule and a table "pump.fun rules per trade". Run on the lab's data folder on 2026-10-29 13:20 UTC
(paper ledger to 13:10 UTC). Five trials, counted only (`pumpfun:ladder:<rule>`, family `pumpfun`), in every DSR
below and registered by the ladder's next report. Paper only: nothing a live bot, a wallet or the engine reads changed;
the ladder proposes and arms nothing.

## Result

Every rule stands on step 1 (idea). Nothing is close to step 2, for two reasons: the realistic record has 6 scored days
of the 10 R7 asks, and R7's bar as fixed is out of reach at today's noise variance.

| rule | step | days of realistic record | entries (effective) | mean per entry | R7 day band | DSR all / pumpfun | days needed: bar / T8 power |
|---|---|---|---|---|---|---|---|
| P_pool0 | 1 | 5.5 | 606 (606) | +9.0 % | +3.4 % to +14.5 % | 0.000 / 0.000 | never at its mean / 5 |
| P_pool0_wait | 1 | 5.5 | 781 (781) | +3.5 % | -0.8 % to +7.8 % | 0.000 / 0.000 | never at its mean / 9 |
| P_pool0_wait_norug_half | 1 | 5.2 | 204 (204) | +11.3 % | -0.5 % to +23.0 % | 0.000 / 0.000 | never at its mean / 5 |
| P_cmig_model | 1 | 5.5 | 1,773 (1,110) | -5.7 % | -7.4 % to -4.0 % | 0.000 / 0.000 | never / never |
| E_d0_x1 | 1 | 0 | no realistic record | | | | |

- **What blocks step 2.** 6 of 10 scored days (all four realistic rules) and both DSRs. P_cmig_model also fails the
  late analogue (lat 2x -11.5 % a trade). E_d0_x1 has no realistic record: the collector runs it on the old paper
  model only; P_pool0 is the same rule as a realistic book, and that is the row to read.
- **The bar.** N is 3,690 over all (R5's 3,165 with these five, plus F3's 525 ledger trials) and 535 over the pumpfun
  family (5 + 5 + 525). The noise variance from F3's 299 trials with at least 20 entries is 0.096 per entry, so the
  best of 3,690 trials with no skill reaches a Sharpe of 1.12 per entry (0.95 over the family). The rules' Sharpes per
  entry are 0.1 to 0.3, so no record length passes: "never at its mean". The variance is mostly the sampling noise
  of F3's short trials (20 to a few hundred entries each), not a spread of true edges. Netting that noise out (the
  trials' variance less the mean of 1 / entries) would be the honest form, as the review asked for the weekly
  factory's excess. That change is proposed only. It needs its own pre-registration, because this one fixed the bar.
- **T8's power at 0.** At its current mean P_pool0 would show an edge above 0 at 5 % with 80 % power within the 11
  days the e-process needs before it starts testing (5 more), P_pool0_wait_norug_half too (5), P_pool0_wait in 9.
  These are fixed-sample counts; the sequential test needs at least as many. Step 3 is not yet tested on any rule
  (under 11 days with entries).
- **Step 5 when the rules get there.** P2's selection gap is +18.9 points (fails, under 2 needed). P3 has books for
  P_pool0_wait, P_pool0 and P_cmig_model. P_pool0_wait_norug_half and E_d0_x1 have none, which leaves them an open
  line that blocks.
- **P1.** 401 tainted rows of these four rules are left out (P_cmig_model 321, P_pool0 35, P_pool0_wait 32,
  P_pool0_wait_norug_half 13). Restart closes are left out too. Failed buys count as entries.

## What it means

The rules can be judged per trade. P_pool0's realistic paper record is the first pump.fun number on the ladder with a
day band above 0 (+3.4 % to +14.5 % over 6 days). Six days are one market week, and paper still runs 18.9 points above
live on the same signals (P2). The ladder rows update with every Lab Live run. The 10 scored days fall due around
2026-11-02. The DSR stays at 0 until the bar's variance is reconsidered in a new pre-registration.
