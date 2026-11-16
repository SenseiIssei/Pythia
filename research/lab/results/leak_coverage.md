# T1b: the lowkr leak and the ladder candidates T1 never checks. Result

Pre-registered in `results/leak_coverage_prereg.md` (its own commit before this run). Run 2026-11-16 in the
research container on the lab's data (read only), the weekly job's every part (`python -m lab.leak`) written to a
scratch reports folder. No trial, no performance number: the check answers yes or no per function and looks at no
window's returns. Nothing a live bot, a wallet or the engine reads changed.

## 1. The red on tsmom_tranches_lowkr

Reproduced on the lab's panel at the report's cut 2023-06-08: "ARBUSDT at 2023-06-08 moves when the data after
2023-06-08 changes (shift, shuffle)". The cause was `kr_premium_xs.signal`'s ticker clash guard: a coin's whole
premium column was dropped when the median |premium| of its first 30 Upbit days was over 10 %, so on a day inside
those 30 days it read days still to come. GRT is on Upbit from 2023-06-01; with the days after the cut changed its
column was kept or dropped differently, which moved ARB's rank among the coins on both venues on the cut day. The Upbit file
did not cause the change of week: the cuts of 2026-11-01 and 2026-11-08 (2023-06-01, 2023-06-03) came before GRT had
the five Upbit days its 7-day mean needs; the panel grew a week and the cut moved past them.

Fixed: each day judges the coin on the median of its first 30 Upbit days known by then (fewer until it has 30),
from the 31st on as before. `tests/test_crypto_own.py::test_lowkr_guard_judges_a_new_upbit_coin_on_its_days_so_far_not_on_the_ones_after`
plants a coin calm on its first Upbit days that clashes after: red on the old guard ("CCCUSDT at 2024-09-13 moves
when the data after 2024-09-17 changes (nan, recursive, shuffle)"), green on the new. On the lab's panel after the
fix: no leak at 2023-06-08 and none at the default cuts.

The paper book ran its targets each day from the panel up to the day before, so its own decisions saw only Upbit
days so far; its rule still changes for a coin's first 30 Upbit days. As pre-registered its record through
2026-11-16 is frozen (`forward_report.FROZEN`, like breakout_top10's) and counts toward no forward gate or readiness
rule; from its next run reports/forward says "Fresh record since 2026-11-16 (the one before is frozen: ...)".

## 2. The 25 candidates

The run: **144 checked, 0 red** (the 134 of the weekly list plus 10 new book checks; features, candles, zoo and
specs as before).

| candidates | check | result |
|---|---|---|
| eq1_hold_sp500, eq1_hold_world, eq1_dual_mom, eq1_trend_sp500, eq1_voltarget_sp500 (once and plus50 each, 10 books) | `etf_books <rule>`: the rule's targets on the closes the paper book reads, at every close | pass (12 runs at 2018-08-13, 2022-05-06, 2026-01-19) |
| small40_spy_trend, small40_vol_target | `smallaccount small40_<rule>`: S2's targets on the market built from the panel and SPY's and GLD's closes | pass (12 runs at 2023-05-22, 2024-11-29, 2026-06-09) |
| funding_carry | xs_daily's newest 400 days: `ranked`, then the day's candidates and tranche | pass (12 runs at 2026-04-30, 2026-07-29, 2026-10-27) |
| m4_perps, m4_hl_small | the same panel, `ranked`, M4's candidates with the book's cached model (labels through 2026-11-02 and 2026-11-05, decided 2026-11-10 and 2026-11-13) and the rank buffer day after day | pass (same cuts) |
| P_cmig_model_10eur, P_pool0_10eur, P_pool0_wait_10eur, P_pool5_top30t_sw10o1n, o2n, o3n | not applicable: event rules on the live pump.fun stream; instead P1's taint rule on their paper ledger | the ladder line passes when the ledger was read |
| onchain_meme_fresh_win, momentum_trail, organic_trend, trend_top | not applicable: decided on each run's live snapshot, filled at a live Jupiter quote, no history read | the ladder line says so and passes |

Read against this run's report, the ladder's leak line of all 25 is now "pass" or "not applicable: ..." (none
"not checked"); they stay on step 1 for their other conditions.

Not covered, named: the xs_daily panel's per-coin features are read from the lab cache, not rebuilt per cut
(`xs_daily.build_panel` reads the hourly files itself), and EQ1's closes come from `etf_books_eq1.build`, whose spike
filter (`drop_spikes`) judges a close by the next one (a print more than 15 % off and back the next day); the paper
book's newest close can never be dropped by it, the study's could. Neither is fixed here.

## 3. Health and the weekly page

`_health/jobs.json` now carries the leak check's red lines (`leaks`, the same as the health check's
`leak <kind> <name>`), and the weekly page lists every red line of `reports/leak/latest.json` with its reason under
"Rot" and counts them in its short version ("Lecks: n rot"). Before, only `_health/system.json` had the line and the
page said "Alle Jobs grün".
