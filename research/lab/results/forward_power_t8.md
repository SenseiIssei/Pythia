# T8: forward evidence that can prove something

Pre-registered in `results/forward_power_t8_prereg.md` (committed first). Code `lab.paper.power`, called by
`lab.paper.forward_report` after each daily run; tests `tests/test_power.py`. 38 trials in R5's registry (32 records
and 6 families, counted only). Validation cut at 2026-06-30, the lockbox not read. Paper only: no book, gate,
engine setting, live path or wallet changes; `evidence.json` (the engine's) is unchanged.

## The answer

- **A forward record cannot prove an edge in any useful time.** At a true Sharpe of 1.0 a fixed sample needs
  2,257 days (6.2 years); the test that stays valid under daily looks needs about 4,055 days (11.1 years) for 80 %
  of records, in line with the review's 12 years. At 2.0: 564 and 938 days.
- **Today's books.** The quickest is perps_neutral at its validated 1.74 (T6, approximate): 3.6 years. m4_ls 9.9,
  picks_ls_v2 7.6, breakout_top10 12.2, the weekly factory's shadow 15.0, tsmom_regime 20.5; tsmom (0.46) and
  tsmom_top20 (0.22) more than 30 years. 17 records (the on-chain, pump.fun, small-account books, tsmom_tranches,
  funding_carry, m4_perps) have no validated Sharpe the lab can read, so they can only show an edge, never a fall
  below their band.
- **Evidence today.** No record has shown an edge (largest e-value 1.35, picks_ls_v2; 20 decides) and none is
  below its validated band (largest 1.22, tsmom_regime). Every validated record is consistent with validation.
  A 30-day record catches bugs, not edges: the forward audit stays the tool for that.
- **Pooled per family.** Short records do add up, but only as far as they are independent: momentum's 8 records
  (108 days) correlate at 0.80, so they count as about 1.2. Momentum is below its validation (pooled gap -5.4 a
  year, P below 0.84) and the meme family is clearly negative (-7.1 a year, 90 % band -10.5 to -3.6, driven by the
  pump.fun and on-chain meme books, pumpfun_migration -99 %); market-neutral +2.5 (P above 0 0.75). All bands are
  many Sharpe units wide; the pool is a Bayesian summary and moves nothing on its own.
- **Simulation checks** (tests): a true zero edge, ever rejected over 3 years of daily looks in 2,000 records:
  normal 1.9 % / 3.2 %, Student t(3) 1.4 % / 2.5 %, a skewed mix 1.6 % / 4.7 % (mixture tuned to 1.0 / 2.0 a
  year); the test on the validated mean within 5 % plus the simulation's error likewise. A true edge of 1.0 / 2.0 a year is found by the
  predicted days in 80.7 % / 77.1 % of fresh normal records and 82.2 % / 80.6 % of Student t(3) ones.
- **The ladder.** T3's ladder is not on main; `power.json` carries each record's paper half of the provisional
  ladder (90 days, never below its band) for it. No record has 90 days yet.
- **Caveats.** The pooled memes figure leans on books without a validated Sharpe (their scale is their own forward
  sd); the self-normalised e-process is exact for symmetric days and was checked, not proven, for skewed ones;
  the approximate books' validated days are normal draws from the report's growth and volatility.

<!-- generated below by lab.paper.power; edit above this line only -->


2026-10-28 04:28 UTC. 32 records: 0 with an edge shown, 0 below their validated band, 15 consistent with validation, 17 without a validated Sharpe; the quickest needs 3.6 years at 5 % and 80 % power.

Days needed: to tell the validated Sharpe from 0 at 5 % one-sided with 80 % power, from the validated days only (365 a year; validation cut at 2026-06-30); fixed sample and the sequential test used here (80 % of 1,000 simulated records found by then). e_edge: today's e-value against no edge, e_below: against the validated mean; either reaching 20 on any day decides (5 %, valid however often it is looked at). Below 1 is evidence the other way, 1 to 20 is not enough. Pre-registered in results/forward_power_t8_prereg.md.

## Records

| record | family | days | return | validated_sharpe | days_needed_fixed | days_needed_sequential | e_edge | e_below | verdict |
|---|---|---|---|---|---|---|---|---|---|
| tsmom | momentum | 23 | -6.22 % | 0.46 (series) | 10,503 days (28.8 years) | more than 30 years | 0.85 | 1.17 | consistent with validation |
| tsmom_regime | momentum | 22 | -4.50 % | 0.75 (series) | 4,056 days (11.1 years) | 7,470 days (20.5 years) | 0.81 | 1.22 | consistent with validation |
| tsmom_top20 | momentum | 22 | -4.72 % | 0.22 (series) | 44,841 days (122.9 years) | more than 30 years | 0.94 | 1.07 | consistent with validation |
| breakout_top10 | breakout | 8 | -0.10 % | 0.95 (series) | 2,513 days (6.9 years) | 4,445 days (12.2 years) | 1.00 | 1.02 | consistent with validation |
| tsmom_tranches | momentum | 16 | -2.43 % | none | n/a | n/a | 0.96 | n/a | no evidence yet |
| m4_ls | market-neutral | 20 | -1.53 % | 1.03 (series) | 2,107 days (5.8 years) | 3,628 days (9.9 years) | 0.96 | 1.10 | consistent with validation |
| picks_ls | market-neutral | 21 | +4.37 % | 1.06 (approximate) | 2,023 days (5.5 years) | 3,555 days (9.7 years) | 1.15 | 0.84 | consistent with validation |
| picks_ls_v2 | market-neutral | 21 | +7.25 % | 1.18 (approximate) | 1,617 days (4.4 years) | 2,769 days (7.6 years) | 1.35 | 0.73 | consistent with validation |
| memes_rotation | memes | 13 | -4.67 % | 1.00 (approximate) | 2,255 days (6.2 years) | 4,049 days (11.1 years) | 0.87 | 1.19 | consistent with validation |
| memes_tsmom | memes | 13 | -1.10 % | 0.58 (approximate) | 6,713 days (18.4 years) | more than 30 years | 0.97 | 1.04 | consistent with validation |
| trend4h_pullback | trend | 14 | -1.76 % | 0.71 (approximate) | 4,477 days (12.3 years) | 7,922 days (21.7 years) | 0.96 | 1.06 | consistent with validation |
| btc_gated | trend | 8 | -4.32 % | 0.68 (approximate) | 4,880 days (13.4 years) | 8,596 days (23.6 years) | 0.90 | 1.11 | consistent with validation |
| tsmom_tranches_lowmax | momentum | 8 | -0.54 % | 0.85 (approximate) | 3,123 days (8.6 years) | 5,716 days (15.7 years) | 0.95 | 1.07 | consistent with validation |
| tsmom_tranches_lowkr | momentum | 8 | -1.05 % | 0.87 (approximate) | 2,981 days (8.2 years) | 5,385 days (14.8 years) | 0.90 | 1.13 | consistent with validation |
| funding_carry | market-neutral | 7 | -2.41 % | none | n/a | n/a | n/a | n/a | no evidence yet |
| m4_perps | market-neutral | 7 | +3.86 % | none | n/a | n/a | n/a | n/a | no evidence yet |
| onchain_breakout_sol | breakout | 6 | +0.00 % | none | n/a | n/a | n/a | n/a | no evidence yet |
| onchain_breakout_top10_live | breakout | 6 | +0.00 % | none | n/a | n/a | n/a | n/a | no evidence yet |
| onchain_longterm | trend | 3 | +0.06 % | none | n/a | n/a | n/a | n/a | no evidence yet |
| onchain_meme_fresh_win | memes | 6 | +0.00 % | none | n/a | n/a | n/a | n/a | no evidence yet |
| onchain_meme_momentum_trail | memes | 6 | -24.10 % | none | n/a | n/a | n/a | n/a | no evidence yet |
| onchain_meme_organic_trend | memes | 6 | -0.78 % | none | n/a | n/a | n/a | n/a | no evidence yet |
| onchain_meme_trend_top | memes | 6 | -4.53 % | none | n/a | n/a | n/a | n/a | no evidence yet |
| perps_neutral | market-neutral | 7 | +1.83 % | 1.74 (approximate) | 745 days (2.0 years) | 1,298 days (3.6 years) | 1.17 | 0.89 | consistent with validation |
| pumpfun_filtered | memes | 14 | -6.49 % | none | n/a | n/a | 0.96 | n/a | no evidence yet |
| pumpfun_filtered_quick | memes | 14 | +0.04 % | none | n/a | n/a | 1.07 | n/a | no evidence yet |
| pumpfun_migration | memes | 14 | -99.45 % | none | n/a | n/a | 1.00 | n/a | no evidence yet |
| small100_breakout_sol3 | breakout | 5 | -1.29 % | none | n/a | n/a | n/a | n/a | no evidence yet |
| small40_spy_trend | trend | 4 | +1.57 % | none | n/a | n/a | n/a | n/a | no evidence yet |
| small40_vol_target | momentum | 4 | -0.05 % | none | n/a | n/a | n/a | n/a | no evidence yet |
| small50_tsmom1 | momentum | 5 | -2.19 % | none | n/a | n/a | n/a | n/a | no evidence yet |
| 44444c97ba5e | factory shadows | 12 | -0.66 % | 0.87 (series) | 3,015 days (8.3 years) | 5,469 days (15.0 years) | 0.98 | 1.04 | consistent with validation |

## Pooled per family

A normal hierarchical model over the family's records (Sharpe a year, 90 % band), each record's error widened by the family's mean correlation; a Bayesian summary that never moves a book on its own.

| family | members | days | corr | pooled_sharpe | p_above_0 | gap_to_validation |
|---|---|---|---|---|---|---|
| breakout | 2 | 13 | 1.00 | -3.45 (-15.85 to +8.95) | 0.32 | -1.20 (-17.02 to +14.63), P below 0.55 |
| factory shadows | 1 | 12 | 0.00 | -0.72 (-9.99 to +8.54) | 0.45 | -1.59 (-10.86 to +7.68), P below 0.61 |
| market-neutral | 6 | 83 | 0.37 | +2.45 (-3.46 to +8.36) | 0.75 | +1.76 (-4.73 to +8.25), P below 0.33 |
| memes | 8 | 86 | 0.00 | -7.07 (-10.53 to -3.61) | 0.00 | -4.30 (-10.60 to +2.01), P below 0.87 |
| momentum | 8 | 108 | 0.80 | -4.94 (-12.75 to +2.87) | 0.15 | -5.43 (-14.34 to +3.49), P below 0.84 |
| trend | 4 | 29 | 0.52 | -0.95 (-10.35 to +8.44) | 0.43 | -4.79 (-15.59 to +6.01), P below 0.77 |

T3's ladder is not on main; each row's `ladder` in power.json carries the paper half of the provisional ladder (90 days, never below its band).

