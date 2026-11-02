# R7b: the pump.fun DSR per entry with the trial variance net of sampling noise and an effective trial count (2026-11-02)

Pre-registration `results/dsr_bar_r7b_prereg.md` (its own commit, then one amendment before the simulation's full run
and before any real number). Code: `lab.pumpfun_rt.dsr_r7b` (`noise_var`, `effective_trials`, `family`, `false_rate`,
`simulate`); the run's numbers in `results/dsr_bar_r7b.json` (`python -m lab.pumpfun_rt.dsr_r7b --sim --reps 200`,
F3's ledger of 2026-11-02 02:55 UTC). Paper only: nothing a live bot, a wallet or the engine reads changed; no candidate
is armed; the ladder is unchanged.

## Result

**The simulation fails, so the ladder keeps R7's bar (rule (d)).** On F3-shaped families with no edge, the new bar
passes the in-sample best trial in 2.5 to 25.0 % of the families, above 5 % in 16 of the 19 shapes. No new DSR was
computed for a real candidate, the four `pumpfun:r7b:<rule>` trials were not made, and the ladder's step 2 still reads
the old DSR per entry (0.000 for all four rules).

The old bar fails the same test with F3's tails too (10.0 to 16.0 %; with normal tails 1.5 to 7.0 %). The reason is
the candidate, not the trial pool. The best of several hundred short trials (20 to 40 entries) drawn from F3's
negatively skewed returns is usually a sample that missed the big losses. Its own skew and kurtosis then look almost
normal, so the DSR's noise term for it is too small. The raw variance's extra noise covered part of that. Netting the
noise out removes that cover, and the false pass rate rises (by 0.5 to 10 points).

## F3's shape and the two bars

| | old (R7) | new (R7b) |
|---|---|---|
| trial variance per entry | 0.0782 raw (467 trials with 20 entries) | 0.0608 = 0.0782 - 0.0174 (mean q / n; floor 0.0174 not binding) |
| F3's trials in N | 825 | 564 effective: 176 without entries (1 cluster), 484 without 20 entries on 5 days of P&L (1 each), 165 clustered into 79 |
| N over all / pumpfun | 5,562 / 882 | 5,301 / 621 |
| SR0 per entry over all / pumpfun | 1.039 / 0.900 | 0.913 / 0.769 (not adopted) |

F3's ledger: 825 trials over 7 nights (300 without day P&L, then 150, 75, 75, 75, 75, 75 with 3 to 8 days), entries
0 to 2,372 (median 30), median skew -1.46 and kurtosis 7.2 of the trials with 20 entries; R5's other trials 4,737.
These are inputs of the bar, not numbers of a candidate.

## The simulation (200 families a shape, seed 20261102 + shape)

False pass: the family's best trial by Sharpe (20 entries or more) passes its own family's DSR at 0.95, selected and
judged on the same entries. C: mean trials per genome (a copy shares 80 % of its genome's entries); rho: the market
day's weight per entry; tails F3: minus a standardized lognormal (skew -1.46, kurtosis 7.2).

| trials | C | rho | tails | true genomes | N_eff | SR0 old | SR0 new | false pass old | false pass new | new at most 5 % |
|---|---|---|---|---|---|---|---|---|---|---|
| 825 | 1 | 0.0 | normal | 825 | 567 | 0.369 | 0.347 | 4.0 % | 6.0 % | no |
| 825 | 1 | 0.0 | F3 | 825 | 565 | 0.383 | 0.351 | 12.0 % | 16.0 % | no |
| 825 | 1 | 0.1 | normal | 825 | 564 | 0.370 | 0.348 | 3.0 % | 4.5 % | yes |
| 825 | 1 | 0.1 | F3 | 825 | 564 | 0.387 | 0.349 | 13.5 % | 19.0 % | no |
| 825 | 1 | 0.3 | normal | 825 | 564 | 0.407 | 0.351 | 7.0 % | 15.5 % | no |
| 825 | 1 | 0.3 | F3 | 825 | 564 | 0.415 | 0.355 | 10.0 % | 16.0 % | no |
| 825 | 5 | 0.0 | normal | 165 | 565 | 0.366 | 0.347 | 2.0 % | 2.5 % | yes |
| 825 | 5 | 0.0 | F3 | 165 | 565 | 0.384 | 0.351 | 11.0 % | 18.5 % | no |
| 825 | 5 | 0.1 | normal | 164 | 563 | 0.371 | 0.349 | 6.0 % | 8.0 % | no |
| 825 | 5 | 0.1 | F3 | 165 | 565 | 0.387 | 0.352 | 14.0 % | 19.5 % | no |
| 825 | 5 | 0.3 | normal | 164 | 566 | 0.410 | 0.354 | 4.0 % | 7.5 % | no |
| 825 | 5 | 0.3 | F3 | 166 | 565 | 0.420 | 0.355 | 15.0 % | 25.0 % | no |
| 825 | 25 | 0.0 | normal | 34 | 563 | 0.366 | 0.348 | 1.5 % | 4.0 % | yes |
| 825 | 25 | 0.0 | F3 | 34 | 562 | 0.386 | 0.353 | 16.0 % | 19.5 % | no |
| 825 | 25 | 0.1 | normal | 34 | 563 | 0.370 | 0.348 | 6.0 % | 8.0 % | no |
| 825 | 25 | 0.1 | F3 | 34 | 561 | 0.378 | 0.351 | 10.0 % | 14.0 % | no |
| 825 | 25 | 0.3 | normal | 34 | 561 | 0.402 | 0.351 | 3.0 % | 8.0 % | no |
| 825 | 25 | 0.3 | F3 | 34 | 559 | 0.425 | 0.358 | 10.5 % | 19.0 % | no |
| 99 | 5 | 0.1 | F3 | 21 | 76 | 0.301 | 0.276 | 2.5 % | 6.0 % | no |

- **N_eff.** The clustering finds few copies: with at most 8 days of P&L and 20 % of each copy's entries its own, a copy's
  residual day P&L rarely correlates above 0.9 with its genome, and 484 of 825 trials cannot be clustered at all. N_eff
  stays near 564 whatever the true genome count (34 to 825). That errs on the side of a higher bar. The false passes
  come from the variance netting and the candidate's noise term.
- **Power, in sample** (C 5, rho 0.1, F3 tails, one genome with a true Sharpe per entry): 0.25: old 3.5 %, new 5.5 %;
  0.5: old 16.5 %, new 32.0 % (the best trial passes and is the planted genome's).
- **Power, forward** (1,000 entries over 10 days against the null families' bars with R5's 4,737 trials added): 0 % for
  both bars at a true Sharpe per entry of 0.05, 0.1, 0.2 and 0.3. At N about 5,300 even the simulated bar (0.43 to
  0.46 per entry) is above 0.3.

## Days still needed under the new bar

The ladder's rules have a Sharpe per entry of about 0.1 (P_pool0: +5.9 % per entry, day band +2.3 to +9.4 % on 1,183
entries; P_pool0_wait +2.5 %, P_pool0_wait_norug_half +4.1 %, P_cmig_model -4.8 %, from `reports/ladder/latest.json`).
Even the new bar, had it passed, is 0.91 per entry over all and 0.77 over the pumpfun family. At today's mean every rule
is still "never at its mean", under the old bar and under the new one. A shorter record does not change that: the
gap is the Sharpe per entry, not the number of entries.

## What it means

The honest answer cuts both ways. F3's raw trial variance is mostly a real spread of trial Sharpes (0.061 of 0.078
after the noise), not sampling noise, so netting the noise out lowers the bar only from 1.04 to 0.91 per entry. That
lower bar is not safe either: in-sample best trials of 20 to 40 entries pass it too often. A per-entry bar that F3's
short trials set stays out of reach for rules with a Sharpe of 0.1 per entry. The next honest step would be a bar from
the rules' own forward record (T8's e-process on the day sums, already step 3) or F3's trials held to the rules'
record length. Either needs its own pre-registration. Nothing is armed and nothing live changed.
