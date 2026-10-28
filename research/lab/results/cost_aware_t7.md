# T7: train on what pays

Pre-registered in `results/cost_aware_t7_prereg.md` (committed first). Code: `lab.models.factory` (section T7, the
net target `net1` and `ridge_net`), `lab.models.metalabel` (`sized`, the late label at the era's round trip),
`lab.experiments.cost_aware_t7`. 39 new trials in R5's registry (`factory:t7_net:<key>`,
`factory:t7_net:plain_signal`, `hand:t7_meta:<rule>:<filter|size>`; the plain rules under T5's ids). In sample and
validation only; the lockbox was not read. Paper only: no book, engine setting or wallet changes, no shadow.

## What it says

- **Net-trained models do not beat the plain signal.** In the screen 2021-23 every one of the 32 ridge_net specs is
  positive after costs (0.15 to 1.28), but the sign of the 30-day return in the same long/short book makes 1.36,
  so none passes the screen and none got a validation look. Training on the net helps inside the family: with the
  turnover penalty (kappa 1 and 4) the median net Sharpe is 1.12 and 1.16 against 0.49 for the plain ridge on the
  return (kappa 0), at less turnover (95x to 123x a year against 135x); kappa 16 overdoes it (0.58). The plain
  signal still trades less (56x) and earns more. PBO of the family 0.88.
- **Meta sizing does not pass.** breakout_top10: size 1.00 against the plain rule's 0.64 in validation (band of the
  difference +0.04 to +0.60, drawdown 9 % against 22 %), but the plain filter makes 1.43, in sample both lose to
  the plain rule (1.17 and 0.85 against 1.34), the classifier's AUC is 0.46 in sample, and the DSR is 0.002
  (bar 2.78 a year over 2,865 trials). Donchian 100/50 on coins: 0.11 against 0.10, band across 0. tsmom1: 51
  trades, too few before 2020 for the 40 a model needs, so no trade got a probability and all three variants
  are the plain rule.
- The plain rules reproduce T5's PIT20 numbers (breakout_top10 0.64, Donchian 0.10, tsmom1 0.89 in validation).
- Nothing passed, so nothing joined G2's shadows. The registry lines were written to a copy in the agent run; the
  server's registry gets them when the study runs there (the ids are fixed, a rerun is a no-op).

<!-- generated below by lab.experiments.cost_aware_t7; edit above this line only -->

Generated 2026-10-28T03:42:36+00:00. In sample to 2023-12-31, validation 2024-01-01 to 2026-06-30; the lockbox not read. Costs: part A the USD-M taker 5 bps plus T5's half-spread tiers (1 to 50 bps by the coin's 30-day median dollar volume) per unit of one-way turnover, filled at the close; part B the spot taker 10 bps plus the same tiers, one close late; T4's delisting table not present.

## A. The net target (G2, net1)

Screen 2021-01-01 to 2023-12-31, purged quarterly walk-forward: the plain signal (sign of the 30-day return, same book and costs) makes net Sharpe 1.36 at 56x turnover a year.

| turnover penalty kappa | specs | median net Sharpe | median gross Sharpe | median turnover a year | screen passes |
|---|---|---|---|---|---|
| 0 | 5 | 0.49 | 0.76 | 135x | 0 |
| 1 | 8 | 1.12 | 1.38 | 123x | 0 |
| 4 | 14 | 1.16 | 1.29 | 95x | 0 |
| 16 | 5 | 0.58 | 0.81 | 105x | 0 |

Best five by screen net Sharpe:

| spec | what | net Sharpe | gross | turnover a year | screen |
|---|---|---|---|---|---|
| f342fef5e142 | ridge_net (alpha 0.1, kappa 4.0) on 8 inputs, all history | 1.28 | 1.49 | 114x | fail |
| dcfeebbf4a0a | ridge_net (alpha 1.0, kappa 16.0) on 12 inputs, last 1095 days | 1.28 | 1.49 | 105x | fail |
| 7d86b7c8a4ce | ridge_net (alpha 0.01, kappa 4.0) on 8 inputs, all history | 1.27 | 1.49 | 121x | fail |
| 19520108fc8c | ridge_net (alpha 0.1, kappa 1.0) on 8 inputs, all history | 1.26 | 1.49 | 121x | fail |
| 64f222572225 | ridge_net (alpha 0.1, kappa 4.0) on 3 inputs, all history | 1.25 | 1.31 | 30x | fail |

32 specs (0 errors), 0 screen passes (net Sharpe above 0 and above the plain signal). PBO of the family's screen nets 0.88 over 32 specs (CSCV, 16 blocks).

No validation look: no screen pass.


Shadows admitted: none. Trials: 33 (`factory:t7_net:<key>` and `factory:t7_net:plain_signal`).

## B. Meta-labelling as a size (PIT20, late, costs of their era)

| rule | trades (labelled, with p) | AUC in sample / validation | in sample plain / filter / size | validation plain / filter / size | validation DD plain / size | mean size | size - plain, 90 % band | DSR size | verdict |
|---|---|---|---|---|---|---|---|---|---|
| tsmom1 | 51 (51, 0) | n/a / n/a | 1.51 / 1.51 / 1.51 | 0.89 / 0.89 / 0.89 | 23.1 % / 23.1 % | 1.00 | +0.00 to +0.00 | 0.001 | fail |
| breakout_top10 | 496 (495, 415) | 0.46 / 0.58 | 1.34 / 0.85 / 1.17 | 0.64 / 1.43 / 1.00 | 21.9 % / 9.0 % | 0.41 | +0.04 to +0.60 | 0.002 | fail |
| donchian_100_50 | 114 (113, 63) | 0.44 / 0.55 | -0.39 / -0.58 / -0.53 | 0.10 / 0.00 / 0.11 | 28.2 % / 15.2 % | 0.50 | -0.19 to +0.21 | 0.000 | fail |

Sizing passes with a validation Sharpe above the plain rule and the plain filter, the bootstrap band of size minus plain above 0 at 5 % and a DSR of 0.95 or more over the registry's pool of all (2,865 trials, noise bar 2.78 a year). Highest scale of a rule's weight: 1.00 (never above 1).
