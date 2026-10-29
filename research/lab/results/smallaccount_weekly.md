# S1w: the small-account books traded weekly

Pre-registered in `results/smallaccount_weekly_prereg.md` (committed before any number). Code
`lab/experiments/smallaccount_weekly.py` (`python -m lab.experiments.smallaccount_weekly`, heavy lock), tests
`tests/test_smallaccount_weekly.py`. Validation 2024-01-01 to 2026-06-30, filled one close late, R10's costs of their
era, in EUR after the way back. Paper only: nothing a live bot, a wallet or the engine reads changed.

**Verdict: weekly with the band is followed for three of the four books** (`small50_tsmom1_wk`,
`small40_spy_trend_wk`, `small40_vol_target_wk`, paper books beside the as-run ones from the deploy, same wallet).
small100_breakout_sol3 stays daily only.

- **tsmom1 (50 EUR)** pays much less to trade: 2.48 EUR over the 2.5 years instead of 6.33 (2.0 % of the wallet a
  year instead of 5.1 %, turnover 8.4x instead of 19x, 14 orders a year instead of 31 plus 107 too small to send),
  for 14.2 % a year instead of 14.9 % and a Sharpe of 0.60 instead of 0.63, drawdown the same (25 %).
- **spy_trend (40 EUR)**: 0.65 EUR instead of 1.08, and slightly better (11.4 % / 0.73 against 10.5 % / 0.68). It
  trades two or three times a year either way.
- **vol_target (40 EUR)**, already weekly: the band cuts 0.84 EUR to 0.58, and the 145 orders a year under the
  5 USDC minimum to 5; 12.9 % / 0.96 against 9.6 % / 0.75. One book, one band: a lead, not proof.
- **breakout_sol3 (100 EUR)** fails: its trades are the breakouts and exits themselves, so weekly barely saves
  (3.06 against 3.29 EUR) and enters and leaves late (4.5 % a year against 6.2 %).
- **What the owner saw in the first four days does not change.** The 1.09 and 1.29 EUR were the way in (Kraken's fee
  to USDC and 1 USDC to withdraw, here 1.07 to 1.31 EUR) with no order yet; the way back costs another 0.3 to 0.6
  EUR. For the S2 books the way in and back together (about 1.4 EUR) cost more than all their trading over 2.5
  years. A new `_wk` book pays its own way in once more (paper).
- **The band hardly binds weekly** for tsmom1 and spy_trend (weekly and weekly_band almost the same numbers); a
  weekly change is mostly more than 10 points or an exit.
- **No deflation passes.** DSR over R5's pool of all at most 0.002, over the small family at most 0.24 (pass at
  0.95); the excess of a weekly variant over its as-run book at most 0.48 (vol_target). PBO of picking a variant
  by in-sample Sharpe 0.55 over all eleven (spy_trend's 1.00 only says its two weekly variants tie). Weekly is
  cheaper, not shown to be better. R10's bar for real money is untouched and still passed by nothing.
- **No leak** (T1's harness, 12 runs per book), and every weekly wallet trades only at Wednesday's close (Thursday's
  when late) after its first close.
- Side rows: with today's quotes back to 2024 tsmom1's trading costs are 1.68 against 0.71 EUR; on time (not late)
  daily tsmom1 looks better (0.76 against 0.51), so its daily edge is mostly the fill at the signal's own close.

Notes: the study's wallets make their first trade at the window's first close even when it is not a Wednesday
(S2's wallet convention); the paper books wait for the first Wednesday. S1's two books reproduce R10 exactly
(breakout_sol3 at 100 EUR late 6.2 % / 24.1 % / 0.39 / 116.15); spy_trend at 40 EUR is 10.5 % here against R10's
11.2 %, probably because the ETF closes in `<data>/etf/daily` were downloaded again on 2026-10-28 after R10 (not
checked further). Full numbers: `reports/smallaccount_weekly/latest.json`.

<!-- generated below by lab.experiments.smallaccount_weekly; edit above this line only -->

Generated 2026-10-29T00:14:39+00:00. Validation 2024-01-01 to 2026-06-30, late (filled one close after the close its targets read) unless a column says otherwise; each book at its own wallet, in EUR after the way back. Weekly: Wednesday's close (late: Thursday's); band 10 points of the trading equity, exits always trade. Costs in EUR at the day's EUR/USD.

## 1. Return, drawdown and costs (validation, late)

| book | variant | CAGR | max DD | Sharpe | end EUR | trading costs EUR | way in / back EUR | all costs, share of wallet | trading a year, share of wallet | turnover a year | orders / not sent a year |
|---|---|---|---|---|---|---|---|---|---|---|---|
| small50_tsmom1 | as_run | 14.9 % | 24.9 % | 0.63 | 70.73 | 6.33 | 1.11 / 0.38 | 7.82 (15.6 %) | 5.07 % | 19.0x | 31 / 107 |
| small50_tsmom1 | weekly | 14.1 % | 24.7 % | 0.59 | 69.45 | 2.50 | 1.11 / 0.37 | 3.98 (8.0 %) | 2.00 % | 8.4x | 14 / 9 |
| small50_tsmom1 | weekly_band | 14.2 % | 24.5 % | 0.60 | 69.72 | 2.48 | 1.11 / 0.37 | 3.96 (7.9 %) | 1.98 % | 8.4x | 14 / 0 |
| small100_breakout_sol3 | as_run | 6.2 % | 24.1 % | 0.39 | 116.15 | 3.29 | 1.31 / 0.57 | 5.17 (5.2 %) | 1.32 % | 9.8x | 44 / 0 |
| small100_breakout_sol3 | weekly | 4.6 % | 24.7 % | 0.31 | 111.90 | 3.08 | 1.31 / 0.55 | 4.94 (4.9 %) | 1.23 % | 9.3x | 42 / 2 |
| small100_breakout_sol3 | weekly_band | 4.5 % | 24.8 % | 0.31 | 111.56 | 3.06 | 1.31 / 0.54 | 4.91 (4.9 %) | 1.22 % | 9.3x | 42 / 0 |
| small40_spy_trend | as_run | 10.5 % | 20.7 % | 0.68 | 51.34 | 1.08 | 1.07 / 0.32 | 2.47 (6.2 %) | 1.08 % | 2.6x | 3 / 0 |
| small40_spy_trend | weekly | 11.4 % | 18.9 % | 0.73 | 52.36 | 0.65 | 1.07 / 0.32 | 2.04 (5.1 %) | 0.66 % | 1.8x | 2 / 0 |
| small40_spy_trend | weekly_band | 11.4 % | 18.9 % | 0.73 | 52.36 | 0.65 | 1.07 / 0.32 | 2.04 (5.1 %) | 0.66 % | 1.8x | 2 / 0 |
| small40_vol_target | as_run | 9.6 % | 13.4 % | 0.75 | 50.27 | 0.84 | 1.07 / 0.34 | 2.25 (5.6 %) | 0.84 % | 1.3x | 10 / 145 |
| small40_vol_target | weekly_band | 12.9 % | 13.9 % | 0.96 | 54.11 | 0.58 | 1.07 / 0.35 | 2.00 (5.0 %) | 0.58 % | 1.0x | 6 / 5 |

## 2. On time against late, today's quotes, in sample (Sharpe; CAGR / trading costs EUR)

| book | variant | in sample, late | on time | late | late, today's quotes back to 2024 |
|---|---|---|---|---|---|
| small50_tsmom1 | as_run | 1.39 | 0.76; 18.6 % / 6.15 | 0.63; 14.9 % / 6.33 | 0.75; 18.6 % / 1.68 |
| small50_tsmom1 | weekly | 1.60 | 0.50; 10.9 % / 2.39 | 0.59; 14.1 % / 2.50 | 0.64; 15.6 % / 0.76 |
| small50_tsmom1 | weekly_band | 1.64 | 0.51; 11.2 % / 2.39 | 0.60; 14.2 % / 2.48 | 0.65; 15.8 % / 0.71 |
| small100_breakout_sol3 | as_run | 1.81 | 0.68; 13.0 % / 3.30 | 0.39; 6.2 % / 3.29 | 0.41; 6.8 % / 1.77 |
| small100_breakout_sol3 | weekly | 1.67 | 0.55; 10.4 % / 3.18 | 0.31; 4.6 % / 3.08 | 0.34; 5.2 % / 1.66 |
| small100_breakout_sol3 | weekly_band | 1.49 | 0.55; 10.4 % / 3.15 | 0.31; 4.5 % / 3.06 | 0.33; 5.1 % / 1.64 |
| small40_spy_trend | as_run | 0.54 | 0.77; 12.2 % / 1.10 | 0.68; 10.5 % / 1.08 | 0.74; 11.4 % / 0.18 |
| small40_spy_trend | weekly | 0.58 | 0.83; 13.2 % / 0.66 | 0.73; 11.4 % / 0.65 | 0.76; 11.9 % / 0.12 |
| small40_spy_trend | weekly_band | 0.58 | 0.83; 13.2 % / 0.66 | 0.73; 11.4 % / 0.65 | 0.76; 11.9 % / 0.12 |
| small40_vol_target | as_run | 0.51 | 0.78; 10.3 % / 0.92 | 0.75; 9.6 % / 0.84 | 0.75; 9.8 % / 0.80 |
| small40_vol_target | weekly_band | 0.51 | 1.00; 13.9 % / 0.57 | 0.96; 12.9 % / 0.58 | 0.96; 13.4 % / 0.47 |

## 3. Deflation and overfitting

| book | variant | DSR (all / small) | DSR of the excess over as run (all / small) |
|---|---|---|---|
| small50_tsmom1 | as_run | 0.000 / 0.107 |  |
| small50_tsmom1 | weekly | 0.000 / 0.096 | 0.000 / 0.012 |
| small50_tsmom1 | weekly_band | 0.000 / 0.097 | 0.000 / 0.012 |
| small100_breakout_sol3 | as_run | 0.000 / 0.052 |  |
| small100_breakout_sol3 | weekly | 0.000 / 0.041 | 0.000 / 0.008 |
| small100_breakout_sol3 | weekly_band | 0.000 / 0.040 | 0.000 / 0.008 |
| small40_spy_trend | as_run | 0.000 / 0.127 |  |
| small40_spy_trend | weekly | 0.001 / 0.144 | 0.000 / 0.048 |
| small40_spy_trend | weekly_band | 0.001 / 0.144 | 0.000 / 0.048 |
| small40_vol_target | as_run | 0.001 / 0.150 |  |
| small40_vol_target | weekly_band | 0.002 / 0.240 | 0.010 / 0.475 |

DSR (higher is better, pass at 0.95 or more) of the late validation daily returns in EUR over R5's registry, the pool of all (3,013 trials, noise bar 2.79 a year) and the small family (268 trials, 1.41). PBO (CSCV, 16 blocks, by Sharpe, one late wallet from 2020-08-01 to the end of validation): small50_tsmom1 0.62, small100_breakout_sol3 0.56, small40_spy_trend 1.00, small40_vol_target 0.40, all 0.55.

## 4. The pre-registered rule: follow weekly_band?

| book | leak (T1) | follow | fails on |
|---|---|---|---|
| small50_tsmom1 | no leak (12 runs at 2023-04-01, 2024-09-15, 2026-03-03) | yes |  |
| small100_breakout_sol3 | no leak (12 runs at 2023-04-01, 2024-09-15, 2026-03-03) | no | CAGR >= as run - 1 pt |
| small40_spy_trend | no leak (12 runs at 2023-04-01, 2024-09-15, 2026-03-03) | yes |  |
| small40_vol_target | no leak (12 runs at 2023-04-01, 2024-09-15, 2026-03-03) | yes |  |

Trials registered (small family): small:s1w:small50_tsmom1:weekly, small:s1w:small50_tsmom1:weekly_band, small:s1w:small100_breakout_sol3:weekly, small:s1w:small100_breakout_sol3:weekly_band, small:s1w:small40_spy_trend:weekly, small:s1w:small40_spy_trend:weekly_band, small:s1w:small40_vol_target:weekly_band.

