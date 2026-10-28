# T11: cross-venue funding, Hyperliquid against Binance

Run 2026-10-28 as registered in `results/hl_funding_t11_prereg.md` (committed first). Code
`lab.experiments.hl_funding_t11`, tests `tests/test_hl_funding_t11.py`. 5 trials in R5's registry (hand family; the
lines were written to a copy in the agent run, the server's registry gets them when the study runs there, the ids
are fixed). In sample and validation only; the lockbox was not read. Paper only: no book, gate, engine setting, live
path or wallet changes. Tables below the marker are generated.

## What it says

**Fails; nothing to trade. The gap was real and has closed.**

- Hyperliquid's funding ran above Binance's on 31 of 33 coins from 2023-05 to 2026-06 (BTC and ETH about 7 % a
  year, BONK, WIF, NEAR and PEPE 12 to 14 %); the hourly gap is at least 30 % a year either way in 8 to 25 % of
  the hours.
- The pick (gap at least 30 % a year over 24 hours) made an in-sample Sharpe of 7.3 in 2023 and loses in
  validation: Sharpe -1.26 (band -4.37 to 1.39), -1.4 % a year, drawdown 7.7 %, correlation with BTC +0.05.
  All four variants lose in validation; the faster ones lose most (turnover).
- By year the funding collected falls from 15.6 % a year on capital (2024, net +4.2 %) to 4.3 % (2025) and 1.0 %
  (2026 to June) while the costs stay near 9 to 13 %: the edge went as Hyperliquid matured, not only the costs.
- Costs decide the level: of 10.4 % a year, taker fees are 2.5 % and the assumed half spreads 8.0 % (T5's tiers on
  spot volume, Hyperliquid one tier wider). T4's measured cost of a 10k order on Binance's perp is under 1 bp for
  the five coins with depth inside the windows (AAVE, ADA, kPEPE, kBONK, kSHIB), far under the tiers; Hyperliquid's
  spread is not measured. Cheaper fills would help 2024 most; in 2026 to June the funding collected (1.0 % a year)
  is below the taker fees alone (1.4 %).
- At 10k a leg (one tier wider) Sharpe -6.35. DSR 0.000 over all 2,933 trials and the hand family; the bar needs
  about 3.8. PBO 0.00 (the in-sample best is also the least bad out of sample, among four), leak harness clean.

## What is different from kraken_funding_gap

Two perps instead of a perp against Alpaca spot at 35 bps a side (a pair round trip is about a third of that study's
90 bps); both directions; 3.4 years of history instead of one; T5's point-in-time universe instead of the Alpaca
list; daily fills an hour after the decision with both marks charged. Kraken's funding was below Binance's on 26 of
30 coins; Hyperliquid's is above on 31 of 33. Both studies end at the same place: a venue's funding gap is a fact
about the venue (for the perp books: Binance funding understates what a Hyperliquid long pays), not a trade at
taker costs.

## Deviations and limits

- The pre-registration said T4's depth files start after the windows (from a look at three coins); five coins have
  depth inside them. The registered tiers were used throughout; the measured costs are shown below, not used.
- The marks are daily (no hourly history of Hyperliquid's mark or Binance's perp price): an intraday crash such as
  2025-10-10, when the two venues' prices parted for hours, is not in the price term. Margin: 17 of 790 held days
  had a move of 25 % or more on a held coin (a transfer between the venues that day at 2x).
- Hyperliquid's list is today's 33 coins of `ENGINE` (survivors).

<!-- generated below by lab.experiments.hl_funding_t11; edit above this line only -->

Generated 2026-10-28T10:17:34+00:00. Registered in `results/hl_funding_t11_prereg.md` before the run. 33 coins on both venues: AAVE, ADA, ARB, ATOM, AVAX, BCH, BTC, CRV, DOGE, DOT, ETH, FIL, HYPE, LDO, LINK, LTC, NEAR, ONDO, POL, RENDER, SKY, SOL, SUI, SUSHI, TRUMP, TRX, UNI, WIF, XLM, XRP, kBONK, kPEPE, kSHIB. In sample 2023-05-13 to 2023-12-31, validation 2024-01-01 to 2026-06-30; inputs cut at 2026-06-30 24:00, the lockbox not read. Costs: Binance USD-M taker 5 bps, Hyperliquid's base taker 2.5 / 3.5 / 4.5 bps (to 2023, 2024 to 2025-04, from 2025-05), T5's half-spread tiers (1 to 50 bps by the coin's 30-day median spot volume), Hyperliquid one tier wider, throughout (as registered; T4's depth where it exists is shown below, not used).

## Every variant

| variant (theta % _ W h) | IS Sharpe | IS entries | val Sharpe | val CAGR | val DD | val corr BTC | val entries | avg pairs | avg hold d | funding / price / cost a year |
|---|---|---|---|---|---|---|---|---|---|---|
| 15_8 | 2.86 | 194 | -14.86 | -31.6 % | 61.3 % | 0.08 | 1593 | 7.95 | 4.55 | 11.5 % / 2.2 % / -51.5 % |
| 15_24 | 6.55 | 129 | -7.98 | -13.3 % | 32.6 % | 0.06 | 821 | 7.43 | 8.25 | 11.1 % / 1.2 % / -26.6 % |
| 30_8 | 4.65 | 162 | -7.32 | -10.0 % | 24.4 % | 0.04 | 683 | 4.12 | 5.51 | 8.7 % / 1.7 % / -20.9 % |
| 30_24 (pick) | 7.34 | 113 | -1.26 | -1.4 % | 7.7 % | 0.05 | 348 | 3.73 | 9.78 | 8.2 % / 0.8 % / -10.4 % |

Returns on all capital (10 % a leg, 2x margin a leg, at most 10 pairs); funding received net of paid, price the long leg's mark less the short's, costs both legs at entry and exit.

## The pick 30_24 in validation

Sharpe -1.26 (90 % band -4.37 to 1.39), -1.4 % a year, drawdown 7.7 %, correlation with BTC +0.05, 348 entries, 3.7 pairs on average.

Capacity: at 1k USD a leg as above; at 10k a leg (half spreads one tier wider) Sharpe -6.35, -9.8 % a year, costs -19.3 % a year against -10.4 %.

Of the costs at 1k, taker fees -2.5 % a year and half spreads -8.0 %.

The pick by year of validation (a year on all capital):

| year | Sharpe | net | funding | price | cost | entries | avg pairs |
|---|---|---|---|---|---|---|---|
| 2024 | 2.99 | 4.2 % | 15.6 % | 1.4 % | -12.8 % | 200 | 5.46 |
| 2025 | -4.21 | -3.6 % | 4.3 % | 0.6 % | -8.6 % | 112 | 3.36 |
| 2026 | -10.05 | -8.4 % | 1.0 % | -0.0 % | -9.4 % | 36 | 1.01 |

| condition | result | evidence |
|---|---|---|
| 1 gates | fail | Sharpe above 0.5 no; bootstrap 5 % above 0 no; correlation with BTC within +-0.3 yes; at least 20 entries yes |
| 2 DSR all | fail | 0.000 over 2,933 trials (noise bar 2.79 a year) |
| 3 DSR family | fail | 0.000 over the hand family's 1,448 (2.76) |
| 4 PBO | pass | 0.00 over 4 variants, 12,870 splits |
| 5 leak | pass | no leak (16 runs at 2024-12-23 21:00, 2025-06-07 21:00, 2025-11-21 03:00, 2026-05-06 09:00) |

**Fails.** The DSR bar on this pool needs a validation Sharpe of about 3.80 (all) / 3.77 (hand) on as many days.

Margin: the largest one-day move of a held coin's mark in validation 59.5 %; 17 of 790 held days with a move of 25 % or more (a 2x leg's margin half gone, a transfer between the venues needed that day).

## Hyperliquid against Binance funding per coin, in sample and validation (information only)

| coin | hours | hl_ann_pct | binance_ann_pct | gap_ann_pct | share_abs_gap_15 | share_abs_gap_30 |
|---|---|---|---|---|---|---|
| kBONK | 22832 | 23.68 | 9.34 | 14.35 | 0.37 | 0.22 |
| WIF | 21464 | 25.37 | 11.31 | 14.06 | 0.37 | 0.22 |
| NEAR | 23335 | 21.49 | 7.91 | 13.58 | 0.33 | 0.17 |
| kPEPE | 26931 | 21.94 | 9.52 | 12.41 | 0.42 | 0.25 |
| LDO | 26923 | 22.01 | 10.26 | 11.75 | 0.31 | 0.18 |
| AAVE | 25895 | 17.02 | 7.34 | 9.68 | 0.32 | 0.16 |
| DOGE | 26931 | 17.60 | 8.04 | 9.56 | 0.32 | 0.19 |
| FIL | 23036 | 16.03 | 7.81 | 8.23 | 0.25 | 0.12 |
| SOL | 26931 | 12.77 | 5.00 | 7.78 | 0.34 | 0.15 |
| LINK | 26916 | 16.03 | 8.58 | 7.45 | 0.29 | 0.16 |
| BTC | 26931 | 14.74 | 7.30 | 7.45 | 0.22 | 0.09 |
| ETH | 26931 | 14.77 | 7.54 | 7.24 | 0.22 | 0.11 |
| SKY | 6883 | -5.40 | 1.52 | -6.92 | 0.35 | 0.19 |
| RENDER | 16789 | 10.46 | 4.10 | 6.35 | 0.27 | 0.11 |
| UNI | 25296 | 14.71 | 8.82 | 5.89 | 0.28 | 0.15 |
| POL | 15642 | 4.09 | -1.39 | 5.48 | 0.32 | 0.12 |
| CRV | 26924 | 2.49 | 7.05 | -4.56 | 0.34 | 0.20 |
| LTC | 26931 | 13.09 | 8.58 | 4.51 | 0.23 | 0.11 |
| ONDO | 21416 | 10.44 | 6.00 | 4.44 | 0.39 | 0.22 |
| DOT | 24540 | 7.29 | 3.34 | 3.95 | 0.31 | 0.14 |
| HYPE | 9517 | 12.75 | 8.83 | 3.92 | 0.24 | 0.10 |
| AVAX | 26931 | 8.24 | 4.61 | 3.63 | 0.37 | 0.19 |
| ARB | 26931 | 12.09 | 9.21 | 2.88 | 0.30 | 0.13 |
| TRX | 25423 | 2.25 | -0.22 | 2.48 | 0.33 | 0.13 |
| kSHIB | 25296 | 7.89 | 5.56 | 2.32 | 0.34 | 0.15 |
| XRP | 26614 | 9.25 | 7.37 | 1.88 | 0.26 | 0.11 |
| SUI | 26931 | 7.70 | 5.85 | 1.85 | 0.34 | 0.18 |
| BCH | 26323 | -1.74 | -3.46 | 1.71 | 0.35 | 0.14 |
| SUSHI | 22952 | 10.14 | 8.62 | 1.52 | 0.26 | 0.11 |
| ADA | 23586 | 9.38 | 7.86 | 1.51 | 0.27 | 0.11 |
| TRUMP | 12681 | -16.19 | -17.40 | 1.21 | 0.38 | 0.17 |
| XLM | 14038 | -0.75 | -1.22 | 0.47 | 0.30 | 0.08 |
| ATOM | 26931 | -2.00 | -2.30 | 0.30 | 0.41 | 0.19 |

Mean funding a year a long pays (%), Binance's rate in force each hour; the share of hours with the gap at least 15 % / 30 % a year either way.

## Capacity today (information, after the windows)

| coin | hl_oi_musd | hl_day_volume_musd | depth_from | depth_days_in_windows | cost10k_in_windows_bps | cost10k_all_bps |
|---|---|---|---|---|---|---|
| BTC | 3459.83 | 1859.23 | 2026-10-21 | 0 |  | 0.00 |
| ETH | 2647.70 | 676.64 | 2026-10-21 | 0 |  | 0.00 |
| HYPE | 1718.84 | 333.69 |  |  |  |  |
| SOL | 577.39 | 99.75 | 2026-10-21 | 0 |  | 0.02 |
| NEAR | 283.17 | 107.32 | 2026-10-21 | 0 |  | 0.13 |
| XRP | 229.06 | 79.63 | 2026-10-21 | 0 |  | 0.04 |
| DOGE | 82.19 | 6.11 | 2026-10-21 | 0 |  | 0.08 |
| UNI | 81.50 | 8.36 | 2026-10-21 | 0 |  | 0.28 |
| LINK | 58.11 | 4.49 | 2026-10-21 | 0 |  | 0.28 |
| AAVE | 52.75 | 5.73 | 2023-01-01 | 1266 | 0.95 | 0.94 |
| kPEPE | 51.04 | 29.12 | 2023-05-18 | 1138 | 0.42 | 0.43 |
| SUI | 33.58 | 9.91 | 2026-10-21 | 0 |  | 0.16 |
| ADA | 30.53 | 3.07 | 2023-01-01 | 255 | 0.20 | 0.20 |
| LTC | 23.13 | 1.60 | 2026-10-21 | 0 |  | 0.26 |
| ONDO | 22.59 | 3.90 | 2026-10-21 | 0 |  | 0.42 |
| CRV | 20.73 | 3.24 | 2026-10-21 | 0 |  | 1.56 |
| AVAX | 18.03 | 2.74 | 2026-10-21 | 0 |  | 0.32 |
| ARB | 15.35 | 4.10 | 2026-10-21 | 0 |  | 0.73 |
| TRX | 11.71 | 4.36 | 2026-10-21 | 0 |  | 0.21 |
| XLM | 11.53 | 1.09 | 2026-10-21 | 0 |  | 0.36 |
| FIL | 8.84 | 0.70 | 2026-10-21 | 0 |  | 0.46 |
| LDO | 8.84 | 0.92 | 2026-10-21 | 0 |  | 2.36 |
| BCH | 8.55 | 2.55 | 2026-10-21 | 0 |  | 0.58 |
| TRUMP | 8.33 | 2.64 | 2026-10-21 | 0 |  | 0.75 |
| kBONK | 8.11 | 0.63 | 2023-12-28 | 915 | 0.82 | 1.51 |
| DOT | 6.10 | 2.24 | 2026-10-21 | 0 |  | 0.76 |
| POL | 5.85 | 0.45 | 2026-10-21 | 0 |  | 1.68 |
| WIF | 4.80 | 0.54 | 2026-10-21 | 0 |  | 1.42 |
| ATOM | 3.96 | 1.11 | 2026-10-21 | 0 |  | 1.30 |
| SKY | 3.65 | 0.85 | 2026-10-21 | 0 |  | 4.50 |
| kSHIB | 2.82 | 0.33 | 2023-01-01 | 1268 | 0.76 | 0.81 |
| RENDER | 2.44 | 0.53 | 2026-10-21 | 0 |  | 1.47 |
| SUSHI | 0.29 | 0.09 |  |  |  |  |

Hyperliquid's open interest and day volume in M USD from its newest snapshot; T4's measured cost of a 10k USD market order on Binance's perp (bps from mid): its first day, its days inside the windows and the mean there, and the mean over all its days. The registered rule charges T5's tiers (Binance one tier wider at 10k).

Trials (R5's registry, hand family, before the validation numbers): hand:t11:hl_funding:15_8, hand:t11:hl_funding:15_24, hand:t11:hl_funding:30_8, hand:t11:hl_funding:30_24, hand:t11:hl_funding:30_24:10k.
