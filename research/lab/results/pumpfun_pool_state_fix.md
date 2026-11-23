# The stale pool state G1 found: the paper fix and every rule book restated

Pre-registration `results/pumpfun_pool_state_fix_prereg.md`. Replay of the record's days 2026-10-24 to 2026-11-15, signals from 2026-10-24 01:43 UTC to 2026-11-15 24:00 UTC, the engine as the shadow builds it with the realistic executor (the fit and the live sizing settings of the run's day, the shadow's models), once without `sim.Engine(fresh_pool=...)` (before: a pool read dropped once the stream gave a pool trade) and once with it (after: the newest state by slot). Entries: closed trades and failed buys (a failed buy its fee over the book's median stake). Band: R7's 95 % band clustered by UTC day. Points: after less before. Moved: entries of both runs on the same coin and signal, closed in both, whose entry price changed. 81 trials in R5's registry, family pumpfun, counted only (`pumpfun:pool_fix:*`); no Sharpe, no DSR.

## Per book

| book | entries before | mean before | band before | entries after | mean after | band after | points | moved | in one run only (before / after) |
|---|---|---|---|---|---|---|---|---|---|
| P_pool0 | 2654 | +7.3 % | +5.2 % to +9.4 % | 2651 | +6.1 % | +3.8 % to +8.5 % | -1.1 | 511 of 2585 (19.8 %) | 10 / 7 |
| P_pool0_wait | 3265 | +4.8 % | +3.1 % to +6.5 % | 3291 | +3.9 % | +1.9 % to +5.9 % | -0.9 | 463 of 3186 (14.5 %) | 22 / 48 |
| P_cmig_model | 12335 | -5.4 % | -6.1 % to -4.8 % | 12335 | -5.4 % | -6.1 % to -4.8 % | +0.0 | 0 of 11891 (0.0 %) | 0 / 0 |
| P_pool0_wait_norug_half | 2274 | +7.4 % | +5.4 % to +9.4 % | 2285 | +5.9 % | +3.6 % to +8.2 % | -1.5 | 237 of 2214 (10.7 %) | 15 / 26 |
| P_pool0_wait_10eur | 4 | -19.9 % | -19.9 % to -19.9 % | 4 | -19.9 % | -19.9 % to -19.9 % | +0.0 | 0 of 4 (0.0 %) | 0 / 0 |
| P_pool0_10eur | 3 | -21.4 % | -21.4 % to -21.4 % | 3 | -21.4 % | -21.4 % to -21.4 % | +0.0 | 0 of 3 (0.0 %) | 0 / 0 |
| P_cmig_model_10eur | 5 | -18.6 % | -18.6 % to -18.6 % | 5 | -18.6 % | -18.6 % to -18.6 % | +0.0 | 0 of 5 (0.0 %) | 0 / 0 |
| P_pool5_top30t_sw10o3n | 2106 | +8.0 % | +5.3 % to +10.7 % | 2090 | +6.2 % | +3.3 % to +9.2 % | -1.8 | 316 of 2067 (15.3 %) | 16 / 0 |
| P_pool5_top30t_sw10o2n | 2014 | +8.1 % | +5.3 % to +10.9 % | 1998 | +6.4 % | +3.3 % to +9.4 % | -1.8 | 362 of 1976 (18.3 %) | 16 / 0 |
| P_pool5_top30t_sw10o1n | 1633 | +9.4 % | +6.3 % to +12.4 % | 1613 | +7.2 % | +3.8 % to +10.5 % | -2.2 | 439 of 1592 (27.6 %) | 22 / 2 |
| P_pool0@e1_b02 | 2807 | +6.3 % | +5.0 % to +7.6 % | 2810 | +5.3 % | +3.7 % to +6.9 % | -0.9 | 569 of 1920 (29.6 %) | 4 / 7 |
| P_pool0@e1_b05 | 2703 | +6.6 % | +5.3 % to +8.0 % | 2700 | +5.5 % | +3.8 % to +7.2 % | -1.1 | 633 of 2252 (28.1 %) | 9 / 6 |
| P_pool0@e1_b10 | 2671 | +6.2 % | +4.8 % to +7.7 % | 2671 | +4.7 % | +2.9 % to +6.4 % | -1.6 | 430 of 2455 (17.5 %) | 4 / 4 |
| P_pool0@e1_b20 | 2660 | +6.7 % | +5.0 % to +8.4 % | 2657 | +5.6 % | +3.5 % to +7.6 % | -1.1 | 583 of 2563 (22.7 %) | 8 / 5 |
| P_pool0@e1_b30 | 2658 | +6.5 % | +5.0 % to +8.1 % | 2653 | +5.3 % | +3.5 % to +7.0 % | -1.3 | 509 of 2572 (19.8 %) | 10 / 5 |
| P_pool0@e1_b60 | 2654 | +6.5 % | +5.0 % to +7.9 % | 2654 | +5.3 % | +3.5 % to +7.0 % | -1.2 | 544 of 2588 (21.0 %) | 9 / 9 |
| P_pool0@e1_b100 | 2654 | +6.7 % | +5.2 % to +8.2 % | 2651 | +5.3 % | +3.5 % to +7.0 % | -1.4 | 457 of 2597 (17.6 %) | 9 / 6 |
| P_pool0@e1_s05 | 2651 | +6.7 % | +5.0 % to +8.4 % | 2639 | +5.5 % | +3.4 % to +7.6 % | -1.2 | 384 of 2575 (14.9 %) | 19 / 7 |
| P_pool0@e1_s15 | 2655 | +6.8 % | +5.2 % to +8.5 % | 2651 | +5.5 % | +3.5 % to +7.4 % | -1.4 | 318 of 2587 (12.3 %) | 10 / 6 |
| P_pool0@e1_s30 | 2656 | +6.5 % | +4.8 % to +8.2 % | 2655 | +5.2 % | +3.3 % to +7.1 % | -1.2 | 478 of 2589 (18.5 %) | 9 / 8 |
| P_pool0_wait@e1_b02 | 3472 | +4.5 % | +3.2 % to +5.7 % | 3509 | +3.5 % | +2.0 % to +5.1 % | -0.9 | 290 of 2467 (11.8 %) | 20 / 57 |
| P_pool0_wait@e1_b05 | 3326 | +4.6 % | +3.3 % to +6.0 % | 3358 | +3.6 % | +1.9 % to +5.3 % | -1.0 | 319 of 2808 (11.4 %) | 20 / 52 |
| P_pool0_wait@e1_b10 | 3298 | +4.7 % | +3.0 % to +6.5 % | 3328 | +3.7 % | +1.8 % to +5.6 % | -1.1 | 313 of 3052 (10.3 %) | 19 / 49 |
| P_pool0_wait@e1_b20 | 3270 | +4.5 % | +2.8 % to +6.2 % | 3296 | +3.7 % | +1.8 % to +5.7 % | -0.8 | 510 of 3152 (16.2 %) | 20 / 46 |
| P_pool0_wait@e1_b30 | 3263 | +4.5 % | +2.9 % to +6.1 % | 3292 | +3.8 % | +1.8 % to +5.7 % | -0.7 | 631 of 3165 (19.9 %) | 23 / 52 |
| P_pool0_wait@e1_b60 | 3264 | +4.6 % | +2.9 % to +6.2 % | 3292 | +3.5 % | +1.6 % to +5.4 % | -1.0 | 729 of 3184 (22.9 %) | 23 / 51 |
| P_pool0_wait@e1_b100 | 3264 | +4.8 % | +3.0 % to +6.5 % | 3289 | +3.6 % | +1.7 % to +5.4 % | -1.2 | 643 of 3194 (20.1 %) | 23 / 48 |
| P_pool0_wait@e1_s05 | 3252 | +4.8 % | +3.0 % to +6.6 % | 3275 | +3.8 % | +1.9 % to +5.8 % | -0.9 | 328 of 3171 (10.3 %) | 24 / 47 |
| P_pool0_wait@e1_s15 | 3263 | +4.9 % | +3.0 % to +6.8 % | 3288 | +3.9 % | +1.8 % to +5.9 % | -1.0 | 381 of 3185 (12.0 %) | 21 / 46 |
| P_pool0_wait@e1_s30 | 3266 | +4.6 % | +2.9 % to +6.3 % | 3293 | +3.8 % | +1.9 % to +5.7 % | -0.8 | 615 of 3185 (19.3 %) | 24 / 51 |
| P_cmig_model@e1_b02 | 12592 | -4.7 % | -5.3 % to -4.1 % | 12592 | -4.7 % | -5.3 % to -4.1 % | +0.0 | 0 of 9397 (0.0 %) | 0 / 0 |
| P_cmig_model@e1_b05 | 12476 | -4.9 % | -5.5 % to -4.3 % | 12476 | -4.9 % | -5.5 % to -4.3 % | +0.0 | 0 of 10246 (0.0 %) | 0 / 0 |
| P_cmig_model@e1_b10 | 12403 | -5.2 % | -5.8 % to -4.6 % | 12403 | -5.2 % | -5.8 % to -4.6 % | +0.0 | 0 of 10988 (0.0 %) | 0 / 0 |
| P_cmig_model@e1_b20 | 12345 | -5.3 % | -5.9 % to -4.7 % | 12345 | -5.3 % | -5.9 % to -4.7 % | +0.0 | 0 of 11604 (0.0 %) | 0 / 0 |
| P_cmig_model@e1_b30 | 12335 | -5.4 % | -6.1 % to -4.8 % | 12335 | -5.4 % | -6.1 % to -4.8 % | +0.0 | 0 of 11890 (0.0 %) | 0 / 0 |
| P_cmig_model@e1_b60 | 12335 | -5.4 % | -6.1 % to -4.8 % | 12335 | -5.4 % | -6.1 % to -4.8 % | +0.0 | 0 of 11890 (0.0 %) | 0 / 0 |
| P_cmig_model@e1_b100 | 12335 | -5.4 % | -6.1 % to -4.8 % | 12335 | -5.4 % | -6.1 % to -4.8 % | +0.0 | 0 of 11890 (0.0 %) | 0 / 0 |
| P_cmig_model@e1_s05 | 12168 | -5.6 % | -6.2 % to -5.0 % | 12168 | -5.6 % | -6.2 % to -5.0 % | +0.0 | 0 of 11732 (0.0 %) | 0 / 0 |
| P_cmig_model@e1_s15 | 12272 | -5.5 % | -6.1 % to -4.9 % | 12272 | -5.5 % | -6.1 % to -4.9 % | +0.0 | 0 of 11831 (0.0 %) | 0 / 0 |
| P_cmig_model@e1_s30 | 12308 | -5.4 % | -6.1 % to -4.8 % | 12308 | -5.4 % | -6.1 % to -4.8 % | +0.0 | 0 of 11865 (0.0 %) | 0 / 0 |

## The ledger

`<data>/paper/pumpfun_rt/ledger.csv` is not rewritten. Its closed rows of these books signalled from 2026-10-24 01:43 UTC to 2026-11-23 13:15 UTC (P1's tainted and restart rows out) on which G1's `stale_fill` holds: 4016; their keys (a hash of book, coin and signal time) are in `results/pumpfun_pool_state_fix_rows.json`, and `realistic.md` (P3's table, R2's wallets, E1's forward table) and the ladder skip and count them (`realistic.stale`). Rows between the run and the deploy of the fix are not checked.

| book | ledger rows | stale | stale P&L SOL |
|---|---|---|---|
| P_pool0 | 3355 | 167 | +2.4014 |
| P_pool0_wait | 4159 | 154 | +3.5566 |
| P_cmig_model | 8657 | 0 | +0.0000 |
| P_pool0_wait_norug_half | 2531 | 83 | +12.2604 |
| P_pool0_wait_10eur | 5 | 1 | +0.0055 |
| P_pool0_10eur | 2863 | 166 | +9.1008 |
| P_cmig_model_10eur | 11 | 0 | +0.0000 |
| P_pool5_top30t_sw10o3n | 2180 | 102 | +1.0082 |
| P_pool5_top30t_sw10o2n | 2077 | 97 | +0.9792 |
| P_pool5_top30t_sw10o1n | 1654 | 73 | +0.4260 |
| P_pool0@e1_b02 | 2328 | 163 | +2.7150 |
| P_pool0@e1_b05 | 2570 | 163 | +2.9339 |
| P_pool0@e1_b10 | 2716 | 165 | +3.7159 |
| P_pool0@e1_b20 | 2814 | 165 | +3.8100 |
| P_pool0@e1_b30 | 2831 | 165 | +4.1653 |
| P_pool0@e1_b60 | 2864 | 166 | +3.6992 |
| P_pool0@e1_b100 | 2870 | 165 | +5.5144 |
| P_pool0@e1_s05 | 2855 | 167 | +4.0250 |
| P_pool0@e1_s15 | 2861 | 167 | +4.3384 |
| P_pool0@e1_s30 | 2864 | 167 | +3.2720 |
| P_pool0_wait@e1_b02 | 2998 | 148 | +4.5180 |
| P_pool0_wait@e1_b05 | 3249 | 151 | +4.4457 |
| P_pool0_wait@e1_b10 | 3403 | 153 | +2.5603 |
| P_pool0_wait@e1_b20 | 3504 | 153 | +2.6281 |
| P_pool0_wait@e1_b30 | 3539 | 153 | +2.5224 |
| P_pool0_wait@e1_b60 | 3572 | 153 | +2.8681 |
| P_pool0_wait@e1_b100 | 3579 | 154 | +2.5487 |
| P_pool0_wait@e1_s05 | 3550 | 149 | +2.6434 |
| P_pool0_wait@e1_s15 | 3563 | 153 | +3.4467 |
| P_pool0_wait@e1_s30 | 3567 | 153 | +2.9000 |
| P_cmig_model@e1_b02 | 5932 | 0 | +0.0000 |
| P_cmig_model@e1_b05 | 6398 | 0 | +0.0000 |
| P_cmig_model@e1_b10 | 6806 | 0 | +0.0000 |
| P_cmig_model@e1_b20 | 7164 | 0 | +0.0000 |
| P_cmig_model@e1_b30 | 7366 | 0 | +0.0000 |
| P_cmig_model@e1_b60 | 7366 | 0 | +0.0000 |
| P_cmig_model@e1_b100 | 7366 | 0 | +0.0000 |
| P_cmig_model@e1_s05 | 7288 | 0 | +0.0000 |
| P_cmig_model@e1_s15 | 7329 | 0 | +0.0000 |
| P_cmig_model@e1_s30 | 7346 | 0 | +0.0000 |

## 12041's sensitivity

`pumpfun_realistic_fit_window.md` (12041): the fallback against the new fit, both runs with `fresh_pool` on. Against its fallback mean: this study's after run (the fix on, the run day's fit) and before run (the fix off). Survives: after less its fallback, as a share of its points.

| book | 12041 fallback | 12041 new fit | 12041 points | after | after less fallback | before | before less fallback | survives |
|---|---|---|---|---|---|---|---|---|
| P_pool0 | +1.9 % | +6.1 % | +4.3 | +6.1 % | +4.2 | +7.3 % | +5.4 | 99 % |
| P_pool0_wait | +0.7 % | +3.9 % | +3.2 | +3.9 % | +3.2 | +4.8 % | +4.1 | 99 % |

## What P3's gate and the ladder read now

| P3 book | wallet EUR, all rows | wallet EUR, stale out | trades | mean | band | stale out (SOL) | gate |
|---|---|---|---|---|---|---|---|
| P_pool0_wait_10eur | 3.89 | 3.53 | 4 (was 5) | -27.9 % (was -20.1 %) | n/a | 1 (+0.0055) | fails: 30 days, mean above 0, band above 0, P2 gap under 2 points |
| P_pool0_10eur | 346.14 | -256.80 | 2697 (was 2863) | +0.3 % (was +2.2 %) | -1.2 % to +2.1 % | 166 (+9.1008) | fails: 30 days, band above 0, P2 gap under 2 points |
| P_cmig_model_10eur | 5.20 | 5.20 | 11 (was 11) | -5.6 % (was -5.6 %) | -8.5 % to -2.3 % | 0 (+0.0000) | fails: 30 days, mean above 0, band above 0, P2 gap under 2 points |

| ladder rule | entries | mean | R7 band | with the stale rows: entries, mean, band | stale out | tainted out (P1) |
|---|---|---|---|---|---|---|
| P_pool0_wait | 4232 | -0.7 % | -2.1 % to +0.7 % | 4386, +0.4 %, -0.9 % to +1.8 % | 154 | 32 |
| P_pool0 | 3339 | +1.4 % | -0.5 % to +3.4 % | 3506, +3.0 %, +1.0 % to +4.9 % | 167 | 35 |
| P_cmig_model | 9340 | -4.7 % | -5.4 % to -4.1 % | 9340, -4.7 %, -5.4 % to -4.1 % | 0 | 321 |
| P_pool0_wait_norug_half | 2548 | -0.8 % | -2.6 % to +1.0 % | 2631, +0.3 %, -1.6 % to +2.2 % | 83 | 13 |
| E_d0_x1 | 0 | n/a | n/a | 0, n/a, n/a | 0 | 0 |

## The pre-registered steps

| step | done |
|---|---|
| pre-registration | 1dc8aa2 (2026-11-16) |
| the rule as a paper-only engine flag (`sim.Engine(fresh_pool=True)`, off by default; the live service and the twin unchanged), set by `live.Shadow` | 60f30a9 (`sim.py`, `live.py`) |
| the HEXN test, red before and green after; G1's strict xfail | 60f30a9 (`tests/test_pumpfun_pool_state_fix.py`); G1's xfail is a normal test now (the flag on: the read is the state; the default: still dropped) |
| the 40 books restated, before and after (`pool_fix.replay`) | done now: before 5,928 s, after 6,110 s, on the fit and sizing of the run day (the newest live order 2026-10-30, as 12041's) |
| the ledger's stale rows: keys in `results/pumpfun_pool_state_fix_rows.json`, skipped and counted by `realistic.md` (P3, R2, E1) and the ladder (`realistic.stale`) | the readers 60f30a9 (`realistic.py`, `slippage_e1.py`, `lab/ops/ladder.py`); the keys done now (4,016 rows) |
| trials: 41 ids, 81 trials, family pumpfun, counted only | registered 2026-11-16 06:20 UTC, each id once; `trial_audit` 81 declared, 81 registered, 0 missing; no trial added now |

## Reading (written 2026-11-23, after the numbers above)

- The fix lowers every pool book by 0.7 to 2.2 points per entry and moves 10 to 30 % of their entry prices; the band of
  every book that moves stays above 0. P_cmig_model and its E1 books do not move (no buy of theirs met a stale state, none on the ledger either). The 10 EUR books
  hold 3 to 5 entries in the replay (the wallet runs dry early) and do not move.
- 12041's sensitivity survives: its runs had the fix on, and this study's after run gives the same means (P_pool0
  +6.1 %, P_pool0_wait +3.9 %), so the +4.3 and +3.2 points are the fit's, not the stale state's. Without the fix the
  same fit would read +5.4 and +4.1 points over 12041's fallback.
- On the ledger the stale rows carried the pool books: the ladder's P_pool0 falls from +3.0 % (band +1.0 to +4.9 %)
  to +1.4 % (band -0.5 to +3.4 %), P_pool0_wait from +0.4 % to -0.7 %, P_pool0_wait_norug_half from +0.3 % to
  -0.8 %. P_pool0_10eur's paper wallet less its 166 stale rows (+9.10 SOL) goes below 0 EUR: P3's reader takes their
  P&L off the end wallet as it does P1's, while the stakes compounded on it; the wallet column is not a balance there.
- The prereg expected no stale row after the deploy of the fix. The ledger says otherwise: G1's rule still holds on
  768 rows signalled from 2026-11-16 on, at about the rate of the days before, and a look at a sample of their fill
  prices (not a number of this study) puts them on the older trade's state as before. Either the shadow does not
  run the fix or its rows reach it differently from the record; the rule keeps skipping them up to this run
  (2026-11-23 13:15 UTC), rows after it are not checked. To check on the server: the shadow's code and start.
