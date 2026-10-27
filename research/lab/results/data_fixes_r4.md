# R4: data fixes under every short-leg result (2026-10-27)

Brief R4 of `results/review_2026-10-27.md`. Four fixes, then the M4 and families short-leg books rerun once
against their published numbers.

## What changed

- `lab/experiments/fam_common.py`
  - `panel_from` reads the perp cache through `perp_daily_for`: rebuilt when it ends before the price panel and
    the perp archive (daily bars, funding) got a file after the cache was written. The lab cache ended
    2026-10-06 while the price panel ran to 2026-10-26, so every short after 2026-10-06 was closed and paid no
    funding. A rebuild takes about 50 s.
  - A perp bar without volume does not count as tradable (no `perp_ok`, no funding). Dead perps keep printing
    flat zero-volume bars: 57,210 base-days in the cache, 132 perps on 2026-10-20 alone.
- `research/recorder/recorder/backfill.py`
  - The funding top-up takes every contract type that ends in PERPETUAL (`perpetuals`), not only
    `PERPETUAL`. On 2026-10-20, 212 trading perps (gold, the stock perps) had no October funding.
  - A month file that stops before the last day of its month is fetched again on each later night: the monthly
    archive if there is one, otherwise the missing daily archives, which are appended. This lasts until the
    file covers the last day, for at most 40 days (a pair delisted in mid-month never covers it). Today all 20
    metrics files for 2026-09 stop at 09-29 23:55. The next nightly run tops them up.

## Families sweep (100 variants, the short-leg ones below)

Same code, same 100 variants, same in-sample picks in every run. A = the published setup (perp cache ending
2026-10-06, zero-volume bars shortable, prices to 2026-10-06; it reproduces the published tables within 0.02).
B = the fixed rules on the same window (fresh perps, zero-volume bars not shortable). C = as B with prices to
2026-10-26. Out-of-sample Sharpe at 15 / 41 bps from 2024-01-01.

| family | variant | published | A | B (fixed, same window) | C (fixed, to 10-26) |
|---|---|---|---|---|---|
| lowvol | vol 60d · top 50 · beta-neutral BAB (pick) | 2.11 / 1.91 | 2.10 / 1.91 | 2.04 / 1.84 | 2.13 / 1.94 |
| lowvol | vol 60d · top 100 · beta-neutral BAB | 2.00 / 1.79 | 1.98 / 1.77 | 1.83 / 1.62 | 1.91 / 1.70 |
| lowvol | vol 60d · top 100 · dollar-neutral | 2.08 / 1.87 | 2.06 / 1.86 | 1.89 / 1.68 | 1.93 / 1.73 |
| lowvol | vol 60d · top 50 · dollar-neutral | 1.95 / 1.78 | 1.95 / 1.77 | 1.88 / 1.71 | 1.95 / 1.77 |
| lowvol | beta 90d · top 100 · beta-neutral BAB | -1.58 / -1.79 | -1.58 / -1.79 | -1.60 / -1.82 | -1.71 / -1.92 |
| lowvol | beta 90d · top 50 · beta-neutral BAB | -1.79 / -1.97 | -1.79 / -1.97 | -1.79 / -1.97 | -1.88 / -2.06 |
| lowvol | beta 90d · top 100 · dollar-neutral | -1.04 / -1.26 | -1.04 / -1.26 | -1.09 / -1.31 | -1.07 / -1.29 |
| lowvol | beta 90d · top 50 · dollar-neutral | -1.05 / -1.24 | -1.05 / -1.24 | -1.07 / -1.25 | -1.05 / -1.24 |
| reversal | 7d losers · all eligible · market-neutral (pick) | -1.18 / -2.07 | -1.18 / -2.08 | -1.21 / -2.11 | -1.25 / -2.15 |
| reversal | 3d losers · all eligible · market-neutral | -1.84 / -4.12 | -1.84 / -4.12 | -1.96 / -4.22 | -1.98 / -4.24 |
| reversal | 1d losers · all eligible · market-neutral | -4.37 / -11.71 | -4.38 / -11.71 | -4.50 / -11.82 | -4.42 / -11.74 |
| reversal | 7d / 3d / 1d losers · top 50 liquid (change against published) | -0.38 / -1.07 (7d) | within 0.01 | -0.04 to +0.01 | -0.07 to +0.04 |
| blend | XS momentum 28d · top 50 · quintiles (pick) | -0.63 / -1.01 | -0.63 / -1.01 | -0.69 / -1.07 | -0.81 / -1.20 |
| blend | XS momentum 56d · top 50 · quintiles | -1.07 / -1.37 | -1.07 / -1.37 | -1.08 / -1.38 | -1.13 / -1.43 |
| pairs | 8 variants (pick: 90d, z 1.5, cointegrated; change against published) | -1.21 / -1.66 (pick) | within 0.01 | within 0.01 | -0.05 to +0.18 |
| ensemble | risk parity · all 16 picks | 0.30 / -0.35 | 0.31 / -0.35 | 0.29 / -0.36 | 0.11 / -0.54 |

- The zero-volume fix (A to B) removes 14,263 shortable coin-days (2.9 %). It costs the low-vol books 0.07 to
  0.19 of Sharpe and makes the losers-short reversal books slightly worse. Pairs and the beta books hardly
  move. The flattering the review suspected is real, but small next to the 2.6 deflation bar.
- In sample, the low-vol pick is now close: the top 100 BAB book makes 0.48 (was 0.40) against 0.49 for top 50,
  so the pick stays the same by 0.01.
- The low-vol pick's deflated p: 0.21 published, 0.19 in B, 0.25 in C. The best of 100 noise variants is
  expected at 2.58 / 2.56 / 2.53. **Passing: none, in every run, as published.**

## M4 (m4_residual: reg7n and low vol, 10/10 of 100 perps, buffer 50 %)

Rebuilt from the 2026-10-07 xs_daily cache (the cache check matches to 1e-16). The fixed rule: a perp with no
volume that day is out of the liquid set, so it is neither entered nor held. 9,152 coin-days had a 28-day
volume but no volume that day, 7,536 of them in the holdout. Holdout 2024-01-01 to 2026-09-28. The funding
and month-end fixes do not reach this window (it ends before October; the metrics features are fitted on a
cache that cannot be refetched here).

| at 41 bps (15 bps) | published | fixed |
|---|---|---|
| reg7n holdout Sharpe | 2.02 (2.17) | 1.97 (2.12) |
| low-vol holdout Sharpe | 1.81 (1.88) | 1.85 (1.91) |
| reg7n 2022-23 Sharpe | 0.93 (1.13) | 0.81 (1.00) |
| residual R, holdout Sharpe | 0.96 (1.08) | 0.76 (0.88) |
| R bootstrap 5 % to 95 % | 0.16 to 1.77 | -0.02 to 1.56 |
| beta on low vol (fit) | 0.71 | 0.73 |

M4's own book loses only 0.05, but the residual beyond low vol loses 0.2. Its bootstrap 5 % now lies below 0,
so check 2 of the pre-registration ("bootstrap 5 % above 0") fails on the fixed data. The m4_residual pass
("pass as registered, not confirmed") no longer holds: it is inconclusive at best. Nothing is wired to it.

## Trials

Counted as new trials: 100 variants in B, 100 in C, plus M4's reg7n book and its residual under the fixed
rule: 202. A and the published M4 rebuild only reproduce what was already counted. Nothing passes, so no count
changes a verdict here. The central registry (R5) should add them.

Scripts were run once from scratch output and are not part of the repository (the families code itself is
unchanged; A is the old rule rebuilt in memory, B and C use the new `panel_from`).
