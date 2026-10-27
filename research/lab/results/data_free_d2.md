# D2: free data, collected around the clock, point in time

Code `lab.collect.pit` (the point-in-time store), the collectors `lab.collect.deribit_vol`, `hyperliquid`,
`defillama`, `fear_greed`, `macro` (with `macro_calendar.json`) and the study `lab.experiments.data_free_d2`,
run 2026-10-27 on a fresh backfill of every source. A measurement, not a strategy: nothing live, no paper book
changed, no engine signal.

## Answer

- **Returns: no.** 144 tests of next-day and next-week log returns of BTC, ETH and SPYx (SPY's close for the
  token). One has p under 0.05 (DVOL's 7-day change and BTC's next day, IC +0.08, t 2.37), about seven would by
  chance; none survives Benjamini-Hochberg (q 0.29) or Holm. Stablecoin growth, DEX volume, Solana TVL, Fear and
  Greed, yields, the curve, the dollar, gold, Hyperliquid funding and premium and the FOMC and CPI dates carried
  nothing measurable about the direction of the next day or week.
- **Volatility: a little, mostly what the asset's own volatility already says.** The target is the realized
  volatility of the next 1 or 7 days (5 for SPY) over the trailing 30 (21), so persistence alone does not score;
  the asset's own 7 over 30-day realized vol (`rv_7_30`) is the benchmark and is itself the strongest
  crypto feature (ETH next day IC +0.155, t 5.6). Beyond it ("IC net of rv", its ranks regressed out):
  - a rising VIX (7-day change) for SPYx: IC +0.21 next day, +0.31 next week, net of rv +0.16 (t 4.8) and +0.23
    (t 4.0), in both halves. The only result that is clearly new information, and it is about SPY's own options
    market, not crypto.
  - a rising DVOL for BTC and ETH next day: IC +0.11 and +0.13 (BH q 0.04 and 0.01), net of rv +0.08 (t 2.3) and
    +0.07 (t 2.0), smaller in 2023-2025 than in 2021-2022.
  - Fear and Greed for ETH's next week (+0.16, q 0.09, net +0.15) and DEX volume 7 over 30 days for ETH (q 0.01 and
    0.09, net of rv t 1.3 and 1.6): weak, two thirds of it in 2019-2022, not to be built on.
- **No history, not tested:** Deribit's ATM IV at 7, 30 and 90 days, the 25-delta risk reversals and put/call open
  interest, and Hyperliquid's open interest and mark/oracle premium. Deribit and Hyperliquid serve no free history
  of these, so they accumulate from the first run of the collectors (hourly); a test needs at least a year.
- **What follows:** nothing goes live. The collectors keep running and the health check watches them. If anything
  deserves a registered study it is VIX and DVOL changes as volatility inputs (M10, the vol targets of the small
  account books), judged out of sample against `rv_7_30`; the return question is answered for these series.

## Data and point in time

| Source | Series | History | Job |
|---|---|---|---|
| Deribit public API | BTC and ETH DVOL hourly | from 2021-03-24 (backfilled) | `free-deribit`, hourly :05 |
| | ATM IV 7/30/90 d, 25-delta risk reversal 7/30/90 d, put/call open interest | none, from the first run | |
| Hyperliquid info API | funding and premium per settlement, 33 of the engine's 37 coins | from 2023-05-12 (hourly from mid 2023, backfilled) | `free-hyperliquid`, hourly :15 |
| | snapshot: funding, open interest, mark, oracle, mid, premium, day volume | none, from the first run | |
| DefiLlama | stablecoins all, USDT, USDC and their daily change; DEX volume total and Solana; Solana TVL | 2017-11 (stables), 2021 (Solana) | `free-defillama`, 01:20 |
| alternative.me | Crypto Fear and Greed | from 2018-02-01 | `free-feargreed`, 00:20 |
| FRED CSV, Yahoo chart | US 2y, 10y, VIX (FRED); dollar index, gold, VIX (Yahoo) | from 2017 | `free-macro`, 00:40 |
| `macro_calendar.json` | FOMC statements (scheduled, unscheduled, cancelled) and CPI releases 2017 to 2027 | fixed file | |

Every row is stored with the time it describes (`ts_us`), when it was collected (`collected_us`), when it
became known (`known_us`) and whether it came from a backfill (`backfilled`). Stored rows are never replaced (the
first value seen wins). For backfilled rows `known_us` is the conservative publication time: an hourly candle or
a funding settlement at its time, a DefiLlama day 2 hours after it closed, Fear and Greed 1 hour into its day,
FRED the next weekday at 22:00 UTC, Yahoo the next day at 00:00 UTC. The study reads a feature only from rows with
`known_us` at or before the decision (00:00 UTC after the day for the coins, 20:00 UTC on the trading day for
SPY). FOMC dates: federalreserve.gov's calendars; CPI dates: ALFRED's release dates of the CPI (the February
seasonal factor revisions left out, none for October 2025, which was not published) and the BLS schedule for
2026-11 to 2027.

Limits. A backfill is today's view of the history: DefiLlama revises its days and adds protocols after the fact,
so its history is cleaner than it looked at the time, which only flatters it; nothing scored on returns anyway.
SPY's close stands for SPYx (S2's drift and premium are not modelled here). The Hyperliquid funding history
starts in May 2023, so its tests have about 950 days and no first half.

## Method

Rank IC with a purge gap: the decision days are split into h + 1 interleaved subsamples, each with one free bar
between consecutive target windows (no overlapping targets), the Spearman correlation and its t computed on
each; the IC is their mean and the t is the mean of their t (each valid alone, the mean conservative); p two
sided. Weekly changes are taken between the values known at the two decisions. 24 features (2 DVOL, 2
Hyperliquid, 5 stablecoin, 2 DEX, 1 TVL, 2 Fear and Greed, 7 macro, 2 calendar, the rv benchmark) times 3 assets
times 2 horizons times 2 targets: 288 tests, all counted, Holm and Benjamini-Hochberg over all of them. The IC in
2019-2022 and 2023-2025 is shown for each; a half with fewer than 100 observations per subsample is left blank.

    PYTHIA_FREE=<lake> python -m lab.experiments.data_free_d2

<!-- generated below by lab.experiments.data_free_d2; edit above this line only -->

Generated 2026-10-27T00:40:41+00:00, decision days 2019-01-01 to 2025-12-31, 288 tests counted.

### Coverage (first and last decision day with a value, in the window)

| Feature | BTC | ETH | SPYx |
|---|---|---|---|
| dvol | 2021-03-24 to 2025-12-24 | 2021-03-24 to 2025-12-24 | 2021-03-24 to 2025-12-24 |
| dvol_chg7 | 2021-03-31 to 2025-12-24 | 2021-03-31 to 2025-12-24 | 2021-03-31 to 2025-12-24 |
| hl_funding_24h | 2023-05-12 to 2025-12-24 | 2023-05-12 to 2025-12-24 | 2023-05-12 to 2025-12-24 |
| hl_premium_24h | 2023-05-12 to 2025-12-24 | 2023-05-12 to 2025-12-24 | 2023-05-12 to 2025-12-24 |
| stables_total_growth7 | 2019-01-01 to 2025-12-24 | 2019-01-01 to 2025-12-24 | 2019-01-02 to 2025-12-24 |
| stables_total_growth30 | 2019-01-01 to 2025-12-24 | 2019-01-01 to 2025-12-24 | 2019-01-02 to 2025-12-24 |
| usdt_growth7 | 2019-01-01 to 2025-12-24 | 2019-01-01 to 2025-12-24 | 2019-01-02 to 2025-12-24 |
| usdc_growth7 | 2019-01-01 to 2025-12-24 | 2019-01-01 to 2025-12-24 | 2019-01-02 to 2025-12-24 |
| stables_total_chg1 | 2019-01-01 to 2025-12-24 | 2019-01-01 to 2025-12-24 | 2019-01-02 to 2025-12-24 |
| dex_volume_7_30 | 2019-01-01 to 2025-12-24 | 2019-01-01 to 2025-12-24 | 2019-01-02 to 2025-12-24 |
| dex_volume_solana_7_30 | 2021-11-01 to 2025-12-24 | 2021-11-01 to 2025-12-24 | 2021-11-01 to 2025-12-24 |
| tvl_solana_chg7 | 2021-03-25 to 2025-12-24 | 2021-03-25 to 2025-12-24 | 2021-03-25 to 2025-12-24 |
| fear_greed | 2019-01-01 to 2025-12-24 | 2019-01-01 to 2025-12-24 | 2019-01-02 to 2025-12-24 |
| fear_greed_chg7 | 2019-01-01 to 2025-12-24 | 2019-01-01 to 2025-12-24 | 2019-01-02 to 2025-12-24 |
| us2y_chg7 | 2019-01-01 to 2025-12-24 | 2019-01-01 to 2025-12-24 | 2019-01-02 to 2025-12-24 |
| us10y_chg7 | 2019-01-01 to 2025-12-24 | 2019-01-01 to 2025-12-24 | 2019-01-02 to 2025-12-24 |
| curve_10y_2y | 2019-01-01 to 2025-12-24 | 2019-01-01 to 2025-12-24 | 2019-01-02 to 2025-12-24 |
| vix | 2019-01-01 to 2025-12-24 | 2019-01-01 to 2025-12-24 | 2019-01-02 to 2025-12-24 |
| vix_chg7 | 2019-01-01 to 2025-12-24 | 2019-01-01 to 2025-12-24 | 2019-01-02 to 2025-12-24 |
| dxy_chg7 | 2019-01-01 to 2025-12-24 | 2019-01-01 to 2025-12-24 | 2019-01-02 to 2025-12-24 |
| gold_chg7 | 2019-01-01 to 2025-12-24 | 2019-01-01 to 2025-12-24 | 2019-01-02 to 2025-12-24 |
| fomc_ahead | 2019-01-01 to 2025-12-24 | 2019-01-01 to 2025-12-24 | 2019-01-02 to 2025-12-24 |
| cpi_ahead | 2019-01-01 to 2025-12-24 | 2019-01-01 to 2025-12-24 | 2019-01-02 to 2025-12-24 |
| rv_7_30 | 2019-01-01 to 2025-12-24 | 2019-01-01 to 2025-12-24 | 2019-01-02 to 2025-12-24 |

### Tests that survive Benjamini-Hochberg at 10 %

| Feature | Asset | h | Target | IC | t | p | Holm | BH q | IC 2019-22 | IC 2023-25 | IC net of rv (t) | n |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| vix_chg7 | SPYx | 1 | vol | +0.205 | +6.20 | 0.0000 | 0.000 | 0.000 | +0.213 | +0.190 | +0.159 (+4.76) | 1756 |
| vix_chg7 | SPYx | 5 | vol | +0.312 | +5.62 | 0.0000 | 0.000 | 0.000 | +0.352 | +0.238 | +0.229 (+4.02) | 1756 |
| rv_7_30 | ETH | 1 | vol | +0.155 | +5.61 | 0.0000 | 0.000 | 0.000 | +0.181 | +0.123 |  | 2556 |
| rv_7_30 | SPYx | 5 | vol | +0.269 | +4.78 | 0.0000 | 0.000 | 0.000 | +0.297 | +0.218 |  | 1756 |
| rv_7_30 | SPYx | 1 | vol | +0.150 | +4.49 | 0.0000 | 0.002 | 0.000 | +0.201 | +0.078 |  | 1756 |
| dvol_chg7 | ETH | 1 | vol | +0.127 | +3.76 | 0.0002 | 0.049 | 0.008 | +0.165 | +0.108 | +0.067 (+1.98) | 1736 |
| dex_volume_7_30 | ETH | 1 | vol | +0.102 | +3.66 | 0.0003 | 0.071 | 0.010 | +0.134 | +0.052 | +0.035 (+1.25) | 2556 |
| rv_7_30 | BTC | 1 | vol | +0.093 | +3.35 | 0.0008 | 0.230 | 0.030 | +0.104 | +0.080 |  | 2556 |
| rv_7_30 | ETH | 7 | vol | +0.181 | +3.28 | 0.0010 | 0.289 | 0.033 | +0.235 | +0.109 |  | 2550 |
| dvol_chg7 | BTC | 1 | vol | +0.107 | +3.18 | 0.0015 | 0.410 | 0.042 | +0.164 | +0.077 | +0.077 (+2.27) | 1736 |
| fear_greed | ETH | 7 | vol | +0.162 | +2.91 | 0.0036 | 0.991 | 0.089 | +0.212 | +0.061 | +0.153 (+2.75) | 2550 |
| dex_volume_7_30 | ETH | 7 | vol | +0.161 | +2.90 | 0.0037 | 1.000 | 0.089 | +0.230 | +0.057 | +0.089 (+1.59) | 2550 |

### Every test

| Feature | Asset | h | Target | IC | t | p | BH q | IC 2019-22 | IC 2023-25 | IC net of rv |
|---|---|---|---|---|---|---|---|---|---|---|
| cpi_ahead | BTC | 1 | ret | +0.020 | +0.71 | 0.475 | 0.97 | +0.013 | +0.026 |  |
| cpi_ahead | BTC | 1 | vol | +0.034 | +1.21 | 0.226 | 0.87 | +0.043 | +0.021 | +0.033 |
| cpi_ahead | BTC | 7 | ret | +0.025 | +0.45 | 0.655 | 0.98 | -0.056 | +0.148 |  |
| cpi_ahead | BTC | 7 | vol | +0.016 | +0.28 | 0.781 | 0.98 | -0.012 | +0.052 | +0.014 |
| cpi_ahead | ETH | 1 | ret | +0.010 | +0.36 | 0.719 | 0.98 | -0.014 | +0.045 |  |
| cpi_ahead | ETH | 1 | vol | +0.021 | +0.73 | 0.463 | 0.96 | +0.026 | +0.015 | +0.019 |
| cpi_ahead | ETH | 7 | ret | +0.011 | +0.19 | 0.846 | 0.98 | -0.076 | +0.141 |  |
| cpi_ahead | ETH | 7 | vol | +0.046 | +0.81 | 0.416 | 0.94 | +0.017 | +0.087 | +0.045 |
| cpi_ahead | SPYx | 1 | ret | +0.012 | +0.36 | 0.719 | 0.98 | -0.022 | +0.071 |  |
| cpi_ahead | SPYx | 1 | vol | +0.025 | +0.75 | 0.453 | 0.95 | -0.004 | +0.066 | +0.027 |
| cpi_ahead | SPYx | 5 | ret | +0.075 | +1.28 | 0.201 | 0.87 | -0.002 | +0.189 |  |
| cpi_ahead | SPYx | 5 | vol | +0.003 | +0.04 | 0.965 | 0.98 | -0.005 | +0.004 | -0.010 |
| curve_10y_2y | BTC | 1 | ret | +0.015 | +0.54 | 0.593 | 0.98 | +0.038 | -0.016 |  |
| curve_10y_2y | BTC | 1 | vol | +0.065 | +2.32 | 0.020 | 0.30 | +0.101 | +0.052 | +0.058 |
| curve_10y_2y | BTC | 7 | ret | +0.027 | +0.49 | 0.626 | 0.98 | +0.093 | -0.038 |  |
| curve_10y_2y | BTC | 7 | vol | +0.076 | +1.37 | 0.172 | 0.85 | +0.183 | -0.010 | +0.064 |
| curve_10y_2y | ETH | 1 | ret | +0.032 | +1.15 | 0.249 | 0.87 | +0.053 | -0.013 |  |
| curve_10y_2y | ETH | 1 | vol | +0.052 | +1.86 | 0.063 | 0.50 | +0.103 | -0.019 | +0.047 |
| curve_10y_2y | ETH | 7 | ret | +0.067 | +1.20 | 0.229 | 0.87 | +0.120 | -0.027 |  |
| curve_10y_2y | ETH | 7 | vol | +0.030 | +0.53 | 0.598 | 0.98 | +0.127 | -0.062 | +0.022 |
| curve_10y_2y | SPYx | 1 | ret | +0.029 | +0.85 | 0.394 | 0.94 | +0.035 | +0.038 |  |
| curve_10y_2y | SPYx | 1 | vol | -0.004 | -0.10 | 0.916 | 0.98 | +0.010 | -0.043 | +0.005 |
| curve_10y_2y | SPYx | 5 | ret | +0.024 | +0.42 | 0.677 | 0.98 | +0.036 | +0.035 |  |
| curve_10y_2y | SPYx | 5 | vol | -0.062 | -1.06 | 0.288 | 0.87 | +0.002 | -0.134 | -0.050 |
| dex_volume_7_30 | BTC | 1 | ret | +0.022 | +0.79 | 0.427 | 0.94 | +0.007 | +0.047 |  |
| dex_volume_7_30 | BTC | 1 | vol | +0.073 | +2.61 | 0.009 | 0.18 | +0.104 | +0.028 | +0.040 |
| dex_volume_7_30 | BTC | 7 | ret | +0.047 | +0.84 | 0.400 | 0.94 | +0.007 | +0.129 |  |
| dex_volume_7_30 | BTC | 7 | vol | +0.118 | +2.12 | 0.034 | 0.31 | +0.205 | -0.021 | +0.065 |
| dex_volume_7_30 | ETH | 1 | ret | +0.037 | +1.31 | 0.189 | 0.87 | +0.045 | +0.020 |  |
| dex_volume_7_30 | ETH | 1 | vol | +0.102 | +3.66 | 0.000 | 0.01 | +0.134 | +0.052 | +0.035 |
| dex_volume_7_30 | ETH | 7 | ret | +0.074 | +1.32 | 0.186 | 0.87 | +0.069 | +0.088 |  |
| dex_volume_7_30 | ETH | 7 | vol | +0.161 | +2.90 | 0.004 | 0.09 | +0.230 | +0.057 | +0.089 |
| dex_volume_7_30 | SPYx | 1 | ret | +0.004 | +0.13 | 0.894 | 0.98 | -0.008 | +0.022 |  |
| dex_volume_7_30 | SPYx | 1 | vol | +0.030 | +0.90 | 0.369 | 0.94 | +0.026 | +0.036 | +0.022 |
| dex_volume_7_30 | SPYx | 5 | ret | +0.021 | +0.35 | 0.723 | 0.98 | -0.039 | +0.133 |  |
| dex_volume_7_30 | SPYx | 5 | vol | +0.021 | +0.36 | 0.716 | 0.98 | +0.038 | -0.018 | +0.005 |
| dex_volume_solana_7_30 | BTC | 1 | ret | +0.012 | +0.33 | 0.739 | 0.98 | -0.059 | +0.047 |  |
| dex_volume_solana_7_30 | BTC | 1 | vol | +0.016 | +0.45 | 0.652 | 0.98 | +0.050 | +0.001 | +0.003 |
| dex_volume_solana_7_30 | BTC | 7 | ret | +0.057 | +0.79 | 0.430 | 0.94 |  | +0.133 |  |
| dex_volume_solana_7_30 | BTC | 7 | vol | -0.009 | -0.12 | 0.902 | 0.98 |  | -0.038 | -0.026 |
| dex_volume_solana_7_30 | ETH | 1 | ret | +0.006 | +0.18 | 0.859 | 0.98 | -0.049 | +0.040 |  |
| dex_volume_solana_7_30 | ETH | 1 | vol | +0.024 | +0.66 | 0.512 | 0.98 | +0.048 | +0.017 | -0.012 |
| dex_volume_solana_7_30 | ETH | 7 | ret | +0.028 | +0.39 | 0.698 | 0.98 |  | +0.117 |  |
| dex_volume_solana_7_30 | ETH | 7 | vol | +0.037 | +0.51 | 0.609 | 0.98 |  | +0.012 | +0.001 |
| dex_volume_solana_7_30 | SPYx | 1 | ret | +0.036 | +0.83 | 0.408 | 0.94 | -0.034 | +0.085 |  |
| dex_volume_solana_7_30 | SPYx | 1 | vol | -0.048 | -1.10 | 0.270 | 0.87 | -0.031 | -0.052 | -0.052 |
| dex_volume_solana_7_30 | SPYx | 5 | ret | +0.086 | +1.14 | 0.253 | 0.87 |  | +0.204 |  |
| dex_volume_solana_7_30 | SPYx | 5 | vol | -0.099 | -1.30 | 0.193 | 0.87 |  | -0.188 | -0.110 |
| dvol | BTC | 1 | ret | -0.003 | -0.08 | 0.935 | 0.98 | +0.073 | +0.035 |  |
| dvol | BTC | 1 | vol | +0.047 | +1.39 | 0.164 | 0.85 | +0.078 | +0.058 | +0.037 |
| dvol | BTC | 7 | ret | -0.036 | -0.53 | 0.595 | 0.98 |  | +0.072 |  |
| dvol | BTC | 7 | vol | -0.026 | -0.38 | 0.707 | 0.98 |  | -0.051 | -0.041 |
| dvol | ETH | 1 | ret | +0.014 | +0.41 | 0.685 | 0.98 | +0.060 | -0.011 |  |
| dvol | ETH | 1 | vol | +0.052 | +1.53 | 0.125 | 0.79 | +0.008 | +0.034 | +0.034 |
| dvol | ETH | 7 | ret | -0.008 | -0.11 | 0.909 | 0.98 |  | -0.048 |  |
| dvol | ETH | 7 | vol | -0.052 | -0.76 | 0.448 | 0.95 |  | -0.077 | -0.073 |
| dvol | SPYx | 1 | ret | -0.005 | -0.11 | 0.910 | 0.98 | +0.147 | +0.011 |  |
| dvol | SPYx | 1 | vol | +0.021 | +0.52 | 0.602 | 0.98 | -0.084 | +0.019 | +0.017 |
| dvol | SPYx | 5 | ret | +0.010 | +0.15 | 0.883 | 0.98 |  | +0.068 |  |
| dvol | SPYx | 5 | vol | +0.013 | +0.19 | 0.851 | 0.98 |  | +0.036 | +0.003 |
| dvol_chg7 | BTC | 1 | ret | +0.080 | +2.37 | 0.018 | 0.29 | +0.089 | +0.062 |  |
| dvol_chg7 | BTC | 1 | vol | +0.107 | +3.18 | 0.001 | 0.04 | +0.164 | +0.077 | +0.077 |
| dvol_chg7 | BTC | 7 | ret | +0.091 | +1.34 | 0.179 | 0.87 |  | +0.091 |  |
| dvol_chg7 | BTC | 7 | vol | +0.147 | +2.17 | 0.030 | 0.31 |  | +0.039 | +0.098 |
| dvol_chg7 | ETH | 1 | ret | +0.059 | +1.75 | 0.080 | 0.56 | +0.063 | +0.057 |  |
| dvol_chg7 | ETH | 1 | vol | +0.127 | +3.76 | 0.000 | 0.01 | +0.165 | +0.108 | +0.067 |
| dvol_chg7 | ETH | 7 | ret | +0.101 | +1.49 | 0.135 | 0.80 |  | +0.086 |  |
| dvol_chg7 | ETH | 7 | vol | +0.173 | +2.58 | 0.010 | 0.19 |  | +0.058 | +0.106 |
| dvol_chg7 | SPYx | 1 | ret | +0.023 | +0.56 | 0.572 | 0.98 | +0.071 | -0.025 |  |
| dvol_chg7 | SPYx | 1 | vol | +0.094 | +2.29 | 0.022 | 0.30 | +0.072 | +0.123 | +0.080 |
| dvol_chg7 | SPYx | 5 | ret | +0.035 | +0.49 | 0.621 | 0.98 |  | +0.021 |  |
| dvol_chg7 | SPYx | 5 | vol | +0.162 | +2.31 | 0.021 | 0.30 |  | +0.180 | +0.132 |
| dxy_chg7 | BTC | 1 | ret | +0.012 | +0.44 | 0.658 | 0.98 | +0.042 | -0.032 |  |
| dxy_chg7 | BTC | 1 | vol | -0.015 | -0.55 | 0.582 | 0.98 | -0.007 | -0.027 | -0.013 |
| dxy_chg7 | BTC | 7 | ret | +0.002 | +0.03 | 0.972 | 0.98 | +0.049 | -0.070 |  |
| dxy_chg7 | BTC | 7 | vol | -0.004 | -0.08 | 0.936 | 0.98 | -0.009 | +0.002 | +0.000 |
| dxy_chg7 | ETH | 1 | ret | +0.009 | +0.33 | 0.739 | 0.98 | +0.030 | -0.026 |  |
| dxy_chg7 | ETH | 1 | vol | +0.009 | +0.32 | 0.751 | 0.98 | -0.000 | +0.019 | +0.011 |
| dxy_chg7 | ETH | 7 | ret | +0.024 | +0.42 | 0.673 | 0.98 | +0.061 | -0.043 |  |
| dxy_chg7 | ETH | 7 | vol | -0.021 | -0.37 | 0.712 | 0.98 | -0.028 | -0.008 | -0.018 |
| dxy_chg7 | SPYx | 1 | ret | +0.019 | +0.57 | 0.569 | 0.98 | +0.027 | +0.008 |  |
| dxy_chg7 | SPYx | 1 | vol | +0.059 | +1.75 | 0.080 | 0.56 | +0.060 | +0.058 | +0.056 |
| dxy_chg7 | SPYx | 5 | ret | -0.003 | -0.06 | 0.951 | 0.98 | +0.006 | -0.008 |  |
| dxy_chg7 | SPYx | 5 | vol | +0.140 | +2.42 | 0.015 | 0.26 | +0.156 | +0.117 | +0.140 |
| fear_greed | BTC | 1 | ret | +0.029 | +1.05 | 0.296 | 0.89 | +0.051 | -0.028 |  |
| fear_greed | BTC | 1 | vol | +0.049 | +1.74 | 0.082 | 0.56 | +0.085 | -0.020 | +0.041 |
| fear_greed | BTC | 7 | ret | +0.050 | +0.90 | 0.371 | 0.94 | +0.091 | -0.063 |  |
| fear_greed | BTC | 7 | vol | +0.124 | +2.22 | 0.027 | 0.31 | +0.199 | -0.052 | +0.113 |
| fear_greed | ETH | 1 | ret | +0.040 | +1.44 | 0.149 | 0.81 | +0.064 | +0.007 |  |
| fear_greed | ETH | 1 | vol | +0.060 | +2.16 | 0.031 | 0.31 | +0.077 | +0.045 | +0.050 |
| fear_greed | ETH | 7 | ret | +0.078 | +1.39 | 0.164 | 0.85 | +0.117 | +0.026 |  |
| fear_greed | ETH | 7 | vol | +0.162 | +2.91 | 0.004 | 0.09 | +0.212 | +0.061 | +0.153 |
| fear_greed | SPYx | 1 | ret | +0.021 | +0.62 | 0.534 | 0.98 | +0.045 | -0.034 |  |
| fear_greed | SPYx | 1 | vol | -0.048 | -1.44 | 0.149 | 0.81 | -0.031 | -0.059 | -0.036 |
| fear_greed | SPYx | 5 | ret | +0.029 | +0.50 | 0.617 | 0.98 | +0.042 | -0.017 |  |
| fear_greed | SPYx | 5 | vol | -0.053 | -0.91 | 0.364 | 0.94 | -0.044 | -0.078 | -0.033 |
| fear_greed_chg7 | BTC | 1 | ret | -0.009 | -0.32 | 0.748 | 0.98 | +0.008 | -0.041 |  |
| fear_greed_chg7 | BTC | 1 | vol | -0.054 | -1.94 | 0.052 | 0.47 | -0.048 | -0.060 | -0.053 |
| fear_greed_chg7 | BTC | 7 | ret | +0.003 | +0.06 | 0.951 | 0.98 | +0.037 | -0.041 |  |
| fear_greed_chg7 | BTC | 7 | vol | -0.044 | -0.78 | 0.433 | 0.94 | +0.008 | -0.119 | -0.043 |
| fear_greed_chg7 | ETH | 1 | ret | -0.007 | -0.26 | 0.795 | 0.98 | -0.002 | -0.018 |  |
| fear_greed_chg7 | ETH | 1 | vol | -0.034 | -1.21 | 0.225 | 0.87 | -0.060 | +0.002 | -0.018 |
| fear_greed_chg7 | ETH | 7 | ret | -0.000 | -0.00 | 0.996 | 1.00 | +0.011 | -0.017 |  |
| fear_greed_chg7 | ETH | 7 | vol | -0.023 | -0.41 | 0.680 | 0.98 | -0.041 | -0.002 | -0.004 |
| fear_greed_chg7 | SPYx | 1 | ret | +0.021 | +0.61 | 0.543 | 0.98 | +0.062 | -0.046 |  |
| fear_greed_chg7 | SPYx | 1 | vol | -0.075 | -2.24 | 0.025 | 0.31 | -0.074 | -0.079 | -0.065 |
| fear_greed_chg7 | SPYx | 5 | ret | +0.014 | +0.24 | 0.814 | 0.98 | +0.089 | -0.107 |  |
| fear_greed_chg7 | SPYx | 5 | vol | -0.125 | -2.16 | 0.031 | 0.31 | -0.127 | -0.121 | -0.111 |
| fomc_ahead | BTC | 1 | ret | +0.042 | +1.51 | 0.131 | 0.80 | +0.065 | +0.007 |  |
| fomc_ahead | BTC | 1 | vol | +0.024 | +0.87 | 0.382 | 0.94 | +0.020 | +0.031 | +0.027 |
| fomc_ahead | BTC | 7 | ret | +0.025 | +0.44 | 0.662 | 0.98 | +0.092 | -0.077 |  |
| fomc_ahead | BTC | 7 | vol | -0.008 | -0.13 | 0.893 | 0.98 | +0.034 | -0.066 | -0.005 |
| fomc_ahead | ETH | 1 | ret | +0.035 | +1.25 | 0.210 | 0.87 | +0.042 | +0.020 |  |
| fomc_ahead | ETH | 1 | vol | +0.016 | +0.57 | 0.567 | 0.98 | +0.003 | +0.032 | +0.021 |
| fomc_ahead | ETH | 7 | ret | +0.008 | +0.15 | 0.882 | 0.98 | +0.058 | -0.076 |  |
| fomc_ahead | ETH | 7 | vol | -0.015 | -0.27 | 0.786 | 0.98 | -0.023 | -0.005 | -0.009 |
| fomc_ahead | SPYx | 1 | ret | +0.009 | +0.25 | 0.799 | 0.98 | +0.015 | +0.006 |  |
| fomc_ahead | SPYx | 1 | vol | +0.039 | +1.17 | 0.242 | 0.87 | +0.044 | +0.033 | +0.041 |
| fomc_ahead | SPYx | 5 | ret | -0.021 | -0.36 | 0.721 | 0.98 | -0.083 | +0.081 |  |
| fomc_ahead | SPYx | 5 | vol | +0.105 | +1.80 | 0.072 | 0.53 | +0.089 | +0.129 | +0.097 |
| gold_chg7 | BTC | 1 | ret | -0.017 | -0.60 | 0.552 | 0.98 | -0.061 | +0.048 |  |
| gold_chg7 | BTC | 1 | vol | +0.031 | +1.09 | 0.274 | 0.87 | +0.028 | +0.032 | +0.029 |
| gold_chg7 | BTC | 7 | ret | -0.011 | -0.20 | 0.841 | 0.98 | -0.102 | +0.121 |  |
| gold_chg7 | BTC | 7 | vol | +0.011 | +0.20 | 0.843 | 0.98 | +0.006 | +0.005 | +0.008 |
| gold_chg7 | ETH | 1 | ret | -0.015 | -0.52 | 0.601 | 0.98 | -0.055 | +0.052 |  |
| gold_chg7 | ETH | 1 | vol | -0.008 | -0.29 | 0.768 | 0.98 | -0.003 | -0.012 | -0.005 |
| gold_chg7 | ETH | 7 | ret | -0.019 | -0.34 | 0.732 | 0.98 | -0.100 | +0.108 |  |
| gold_chg7 | ETH | 7 | vol | -0.006 | -0.12 | 0.908 | 0.98 | +0.005 | -0.026 | -0.003 |
| gold_chg7 | SPYx | 1 | ret | -0.019 | -0.57 | 0.571 | 0.98 | -0.016 | -0.027 |  |
| gold_chg7 | SPYx | 1 | vol | -0.020 | -0.60 | 0.550 | 0.98 | -0.004 | -0.032 | -0.022 |
| gold_chg7 | SPYx | 5 | ret | +0.003 | +0.05 | 0.958 | 0.98 | +0.002 | -0.005 |  |
| gold_chg7 | SPYx | 5 | vol | -0.084 | -1.45 | 0.148 | 0.81 | -0.049 | -0.130 | -0.090 |
| hl_funding_24h | BTC | 1 | ret | -0.025 | -0.54 | 0.589 | 0.98 |  | -0.025 |  |
| hl_funding_24h | BTC | 1 | vol | +0.042 | +0.91 | 0.362 | 0.94 |  | +0.042 | +0.040 |
| hl_funding_24h | BTC | 7 | ret | -0.027 | -0.29 | 0.772 | 0.98 |  | -0.027 |  |
| hl_funding_24h | BTC | 7 | vol | +0.017 | +0.19 | 0.850 | 0.98 |  | +0.017 | +0.019 |
| hl_funding_24h | ETH | 1 | ret | +0.015 | +0.34 | 0.736 | 0.98 |  | +0.015 |  |
| hl_funding_24h | ETH | 1 | vol | +0.053 | +1.17 | 0.244 | 0.87 |  | +0.053 | +0.043 |
| hl_funding_24h | ETH | 7 | ret | -0.015 | -0.16 | 0.873 | 0.98 |  | -0.015 |  |
| hl_funding_24h | ETH | 7 | vol | +0.113 | +1.24 | 0.217 | 0.87 |  | +0.113 | +0.104 |
| hl_funding_24h | SPYx | 1 | ret | -0.012 | -0.22 | 0.830 | 0.98 |  | -0.012 |  |
| hl_funding_24h | SPYx | 1 | vol | -0.042 | -0.77 | 0.443 | 0.94 |  | -0.042 | -0.038 |
| hl_funding_24h | SPYx | 5 | ret | -0.008 | -0.08 | 0.936 | 0.98 |  | -0.008 |  |
| hl_funding_24h | SPYx | 5 | vol | -0.024 | -0.25 | 0.806 | 0.98 |  | -0.024 | -0.014 |
| hl_premium_24h | BTC | 1 | ret | -0.018 | -0.39 | 0.698 | 0.98 |  | -0.018 |  |
| hl_premium_24h | BTC | 1 | vol | +0.042 | +0.91 | 0.361 | 0.94 |  | +0.042 | +0.039 |
| hl_premium_24h | BTC | 7 | ret | -0.035 | -0.38 | 0.701 | 0.98 |  | -0.035 |  |
| hl_premium_24h | BTC | 7 | vol | +0.044 | +0.48 | 0.632 | 0.98 |  | +0.044 | +0.044 |
| hl_premium_24h | ETH | 1 | ret | +0.007 | +0.15 | 0.880 | 0.98 |  | +0.007 |  |
| hl_premium_24h | ETH | 1 | vol | +0.068 | +1.49 | 0.135 | 0.80 |  | +0.068 | +0.055 |
| hl_premium_24h | ETH | 7 | ret | -0.021 | -0.23 | 0.818 | 0.98 |  | -0.021 |  |
| hl_premium_24h | ETH | 7 | vol | +0.104 | +1.14 | 0.254 | 0.87 |  | +0.104 | +0.094 |
| hl_premium_24h | SPYx | 1 | ret | -0.034 | -0.61 | 0.539 | 0.98 |  | -0.034 |  |
| hl_premium_24h | SPYx | 1 | vol | -0.043 | -0.78 | 0.435 | 0.94 |  | -0.043 | -0.038 |
| hl_premium_24h | SPYx | 5 | ret | -0.049 | -0.51 | 0.608 | 0.98 |  | -0.049 |  |
| hl_premium_24h | SPYx | 5 | vol | +0.008 | +0.08 | 0.937 | 0.98 |  | +0.008 | +0.021 |
| rv_7_30 | BTC | 1 | ret | +0.014 | +0.50 | 0.618 | 0.98 | +0.010 | +0.017 |  |
| rv_7_30 | BTC | 1 | vol | +0.093 | +3.35 | 0.001 | 0.03 | +0.104 | +0.080 |  |
| rv_7_30 | BTC | 7 | ret | -0.014 | -0.26 | 0.799 | 0.98 | -0.028 | +0.013 |  |
| rv_7_30 | BTC | 7 | vol | +0.154 | +2.78 | 0.005 | 0.12 | +0.206 | +0.083 |  |
| rv_7_30 | ETH | 1 | ret | +0.026 | +0.93 | 0.350 | 0.94 | +0.041 | -0.001 |  |
| rv_7_30 | ETH | 1 | vol | +0.155 | +5.61 | 0.000 | 0.00 | +0.181 | +0.123 |  |
| rv_7_30 | ETH | 7 | ret | +0.006 | +0.10 | 0.921 | 0.98 | +0.018 | -0.013 |  |
| rv_7_30 | ETH | 7 | vol | +0.181 | +3.28 | 0.001 | 0.03 | +0.235 | +0.109 |  |
| rv_7_30 | SPYx | 1 | ret | -0.007 | -0.20 | 0.842 | 0.98 | -0.014 | -0.003 |  |
| rv_7_30 | SPYx | 1 | vol | +0.150 | +4.49 | 0.000 | 0.00 | +0.201 | +0.078 |  |
| rv_7_30 | SPYx | 5 | ret | -0.013 | -0.22 | 0.823 | 0.98 | +0.004 | -0.040 |  |
| rv_7_30 | SPYx | 5 | vol | +0.269 | +4.78 | 0.000 | 0.00 | +0.297 | +0.218 |  |
| stables_total_chg1 | BTC | 1 | ret | +0.038 | +1.37 | 0.170 | 0.85 | +0.051 | +0.018 |  |
| stables_total_chg1 | BTC | 1 | vol | +0.015 | +0.54 | 0.592 | 0.98 | +0.041 | -0.017 | +0.008 |
| stables_total_chg1 | BTC | 7 | ret | +0.063 | +1.13 | 0.257 | 0.87 | +0.092 | +0.013 |  |
| stables_total_chg1 | BTC | 7 | vol | +0.007 | +0.12 | 0.904 | 0.98 | +0.034 | -0.028 | -0.004 |
| stables_total_chg1 | ETH | 1 | ret | +0.041 | +1.48 | 0.140 | 0.80 | +0.044 | +0.030 |  |
| stables_total_chg1 | ETH | 1 | vol | +0.008 | +0.27 | 0.786 | 0.98 | +0.006 | +0.008 | -0.001 |
| stables_total_chg1 | ETH | 7 | ret | +0.063 | +1.12 | 0.263 | 0.87 | +0.054 | +0.063 |  |
| stables_total_chg1 | ETH | 7 | vol | -0.005 | -0.09 | 0.930 | 0.98 | -0.001 | +0.012 | -0.014 |
| stables_total_chg1 | SPYx | 1 | ret | +0.009 | +0.28 | 0.780 | 0.98 | +0.033 | -0.030 |  |
| stables_total_chg1 | SPYx | 1 | vol | -0.021 | -0.63 | 0.531 | 0.98 | +0.010 | -0.081 | -0.018 |
| stables_total_chg1 | SPYx | 5 | ret | +0.005 | +0.09 | 0.929 | 0.98 | -0.003 | +0.026 |  |
| stables_total_chg1 | SPYx | 5 | vol | -0.018 | -0.31 | 0.759 | 0.98 | +0.011 | -0.073 | -0.012 |
| stables_total_growth30 | BTC | 1 | ret | +0.022 | +0.77 | 0.440 | 0.94 | +0.038 | -0.020 |  |
| stables_total_growth30 | BTC | 1 | vol | +0.032 | +1.13 | 0.260 | 0.87 | +0.027 | +0.052 | +0.031 |
| stables_total_growth30 | BTC | 7 | ret | +0.045 | +0.81 | 0.420 | 0.94 | +0.106 | -0.093 |  |
| stables_total_growth30 | BTC | 7 | vol | +0.026 | +0.46 | 0.647 | 0.98 | +0.054 | +0.005 | +0.026 |
| stables_total_growth30 | ETH | 1 | ret | +0.022 | +0.79 | 0.429 | 0.94 | +0.028 | -0.025 |  |
| stables_total_growth30 | ETH | 1 | vol | +0.022 | +0.79 | 0.430 | 0.94 | +0.001 | +0.018 | +0.024 |
| stables_total_growth30 | ETH | 7 | ret | +0.055 | +0.98 | 0.329 | 0.94 | +0.083 | -0.082 |  |
| stables_total_growth30 | ETH | 7 | vol | -0.007 | -0.13 | 0.894 | 0.98 | +0.003 | -0.011 | -0.004 |
| stables_total_growth30 | SPYx | 1 | ret | +0.038 | +1.14 | 0.255 | 0.87 | +0.064 | -0.022 |  |
| stables_total_growth30 | SPYx | 1 | vol | -0.005 | -0.14 | 0.887 | 0.98 | -0.011 | -0.026 | +0.005 |
| stables_total_growth30 | SPYx | 5 | ret | +0.038 | +0.64 | 0.520 | 0.98 | +0.084 | -0.053 |  |
| stables_total_growth30 | SPYx | 5 | vol | -0.049 | -0.83 | 0.408 | 0.94 | -0.045 | -0.049 | -0.033 |
| stables_total_growth7 | BTC | 1 | ret | +0.036 | +1.29 | 0.195 | 0.87 | +0.054 | -0.001 |  |
| stables_total_growth7 | BTC | 1 | vol | +0.018 | +0.65 | 0.515 | 0.98 | +0.033 | +0.006 | +0.014 |
| stables_total_growth7 | BTC | 7 | ret | +0.054 | +0.96 | 0.336 | 0.94 | +0.098 | -0.041 |  |
| stables_total_growth7 | BTC | 7 | vol | +0.002 | +0.04 | 0.972 | 0.98 | +0.046 | -0.056 | -0.005 |
| stables_total_growth7 | ETH | 1 | ret | +0.034 | +1.21 | 0.225 | 0.87 | +0.031 | +0.021 |  |
| stables_total_growth7 | ETH | 1 | vol | +0.013 | +0.45 | 0.652 | 0.98 | +0.005 | +0.012 | +0.011 |
| stables_total_growth7 | ETH | 7 | ret | +0.062 | +1.12 | 0.265 | 0.87 | +0.051 | +0.042 |  |
| stables_total_growth7 | ETH | 7 | vol | -0.010 | -0.17 | 0.862 | 0.98 | +0.002 | +0.003 | -0.012 |
| stables_total_growth7 | SPYx | 1 | ret | +0.030 | +0.88 | 0.380 | 0.94 | +0.050 | -0.010 |  |
| stables_total_growth7 | SPYx | 1 | vol | -0.040 | -1.18 | 0.239 | 0.87 | -0.039 | -0.096 | -0.021 |
| stables_total_growth7 | SPYx | 5 | ret | +0.062 | +1.06 | 0.287 | 0.87 | +0.089 | +0.014 |  |
| stables_total_growth7 | SPYx | 5 | vol | -0.111 | -1.90 | 0.057 | 0.47 | -0.101 | -0.157 | -0.081 |
| tvl_solana_chg7 | BTC | 1 | ret | +0.037 | +1.09 | 0.277 | 0.87 | +0.054 | +0.008 |  |
| tvl_solana_chg7 | BTC | 1 | vol | -0.017 | -0.52 | 0.606 | 0.98 | +0.020 | -0.042 | -0.013 |
| tvl_solana_chg7 | BTC | 7 | ret | +0.043 | +0.63 | 0.532 | 0.98 |  | +0.010 |  |
| tvl_solana_chg7 | BTC | 7 | vol | -0.004 | -0.07 | 0.947 | 0.98 |  | -0.106 | +0.004 |
| tvl_solana_chg7 | ETH | 1 | ret | +0.042 | +1.23 | 0.218 | 0.87 | +0.087 | -0.005 |  |
| tvl_solana_chg7 | ETH | 1 | vol | -0.002 | -0.06 | 0.950 | 0.98 | +0.028 | -0.006 | +0.003 |
| tvl_solana_chg7 | ETH | 7 | ret | +0.054 | +0.79 | 0.429 | 0.94 |  | -0.005 |  |
| tvl_solana_chg7 | ETH | 7 | vol | +0.086 | +1.27 | 0.204 | 0.87 |  | +0.042 | +0.093 |
| tvl_solana_chg7 | SPYx | 1 | ret | +0.027 | +0.65 | 0.515 | 0.98 | +0.043 | -0.005 |  |
| tvl_solana_chg7 | SPYx | 1 | vol | -0.042 | -1.04 | 0.299 | 0.89 | +0.044 | -0.090 | -0.030 |
| tvl_solana_chg7 | SPYx | 5 | ret | +0.019 | +0.28 | 0.783 | 0.98 |  | -0.001 |  |
| tvl_solana_chg7 | SPYx | 5 | vol | -0.110 | -1.57 | 0.117 | 0.75 |  | -0.131 | -0.087 |
| us10y_chg7 | BTC | 1 | ret | -0.035 | -1.24 | 0.215 | 0.87 | -0.031 | -0.040 |  |
| us10y_chg7 | BTC | 1 | vol | +0.028 | +0.99 | 0.324 | 0.93 | +0.040 | +0.012 | +0.029 |
| us10y_chg7 | BTC | 7 | ret | -0.048 | -0.86 | 0.387 | 0.94 | -0.043 | -0.054 |  |
| us10y_chg7 | BTC | 7 | vol | -0.005 | -0.09 | 0.929 | 0.98 | +0.013 | -0.033 | -0.003 |
| us10y_chg7 | ETH | 1 | ret | -0.019 | -0.67 | 0.501 | 0.98 | -0.022 | -0.018 |  |
| us10y_chg7 | ETH | 1 | vol | +0.051 | +1.83 | 0.067 | 0.52 | +0.059 | +0.040 | +0.054 |
| us10y_chg7 | ETH | 7 | ret | -0.028 | -0.49 | 0.622 | 0.98 | -0.046 | +0.000 |  |
| us10y_chg7 | ETH | 7 | vol | +0.018 | +0.32 | 0.751 | 0.98 | +0.048 | -0.028 | +0.020 |
| us10y_chg7 | SPYx | 1 | ret | -0.047 | -1.41 | 0.160 | 0.85 | -0.038 | -0.059 |  |
| us10y_chg7 | SPYx | 1 | vol | -0.035 | -1.03 | 0.303 | 0.89 | -0.060 | -0.003 | -0.023 |
| us10y_chg7 | SPYx | 5 | ret | -0.070 | -1.19 | 0.232 | 0.87 | -0.066 | -0.088 |  |
| us10y_chg7 | SPYx | 5 | vol | +0.053 | +0.91 | 0.365 | 0.94 | +0.002 | +0.128 | +0.078 |
| us2y_chg7 | BTC | 1 | ret | -0.030 | -1.08 | 0.281 | 0.87 | -0.043 | -0.017 |  |
| us2y_chg7 | BTC | 1 | vol | +0.006 | +0.22 | 0.828 | 0.98 | +0.013 | -0.009 | +0.013 |
| us2y_chg7 | BTC | 7 | ret | -0.024 | -0.43 | 0.664 | 0.98 | -0.081 | +0.042 |  |
| us2y_chg7 | BTC | 7 | vol | +0.021 | +0.38 | 0.704 | 0.98 | +0.022 | +0.017 | +0.034 |
| us2y_chg7 | ETH | 1 | ret | -0.009 | -0.31 | 0.756 | 0.98 | -0.024 | +0.003 |  |
| us2y_chg7 | ETH | 1 | vol | +0.054 | +1.93 | 0.054 | 0.47 | +0.043 | +0.055 | +0.058 |
| us2y_chg7 | ETH | 7 | ret | +0.025 | +0.45 | 0.654 | 0.98 | -0.038 | +0.098 |  |
| us2y_chg7 | ETH | 7 | vol | +0.053 | +0.95 | 0.343 | 0.94 | +0.092 | +0.011 | +0.059 |
| us2y_chg7 | SPYx | 1 | ret | -0.034 | -1.00 | 0.316 | 0.92 | -0.035 | -0.042 |  |
| us2y_chg7 | SPYx | 1 | vol | -0.040 | -1.20 | 0.230 | 0.87 | -0.052 | -0.024 | -0.030 |
| us2y_chg7 | SPYx | 5 | ret | -0.024 | -0.41 | 0.678 | 0.98 | -0.012 | -0.053 |  |
| us2y_chg7 | SPYx | 5 | vol | +0.017 | +0.28 | 0.777 | 0.98 | -0.002 | +0.052 | +0.037 |
| usdc_growth7 | BTC | 1 | ret | +0.017 | +0.59 | 0.553 | 0.98 | +0.033 | -0.028 |  |
| usdc_growth7 | BTC | 1 | vol | +0.030 | +1.07 | 0.285 | 0.87 | +0.042 | +0.007 | +0.021 |
| usdc_growth7 | BTC | 7 | ret | +0.050 | +0.88 | 0.377 | 0.94 | +0.100 | -0.066 |  |
| usdc_growth7 | BTC | 7 | vol | +0.003 | +0.06 | 0.953 | 0.98 | +0.014 | -0.021 | -0.011 |
| usdc_growth7 | ETH | 1 | ret | +0.023 | +0.84 | 0.401 | 0.94 | +0.032 | -0.007 |  |
| usdc_growth7 | ETH | 1 | vol | +0.021 | +0.73 | 0.464 | 0.96 | +0.012 | +0.019 | +0.014 |
| usdc_growth7 | ETH | 7 | ret | +0.044 | +0.79 | 0.430 | 0.94 | +0.058 | -0.011 |  |
| usdc_growth7 | ETH | 7 | vol | -0.031 | -0.55 | 0.579 | 0.98 | -0.047 | +0.009 | -0.039 |
| usdc_growth7 | SPYx | 1 | ret | -0.024 | -0.72 | 0.471 | 0.97 | -0.015 | -0.044 |  |
| usdc_growth7 | SPYx | 1 | vol | +0.017 | +0.51 | 0.609 | 0.98 | +0.065 | -0.069 | +0.017 |
| usdc_growth7 | SPYx | 5 | ret | -0.002 | -0.04 | 0.967 | 0.98 | +0.027 | -0.061 |  |
| usdc_growth7 | SPYx | 5 | vol | -0.010 | -0.17 | 0.862 | 0.98 | +0.043 | -0.096 | -0.011 |
| usdt_growth7 | BTC | 1 | ret | +0.012 | +0.42 | 0.676 | 0.98 | +0.020 | -0.006 |  |
| usdt_growth7 | BTC | 1 | vol | +0.004 | +0.16 | 0.875 | 0.98 | +0.024 | -0.022 | +0.001 |
| usdt_growth7 | BTC | 7 | ret | +0.005 | +0.09 | 0.925 | 0.98 | +0.024 | -0.059 |  |
| usdt_growth7 | BTC | 7 | vol | -0.015 | -0.27 | 0.785 | 0.98 | +0.037 | -0.112 | -0.022 |
| usdt_growth7 | ETH | 1 | ret | +0.016 | +0.57 | 0.571 | 0.98 | +0.010 | +0.017 |  |
| usdt_growth7 | ETH | 1 | vol | +0.007 | +0.25 | 0.802 | 0.98 | +0.009 | -0.006 | +0.001 |
| usdt_growth7 | ETH | 7 | ret | +0.018 | +0.32 | 0.745 | 0.98 | -0.001 | +0.033 |  |
| usdt_growth7 | ETH | 7 | vol | -0.013 | -0.23 | 0.816 | 0.98 | +0.016 | -0.056 | -0.020 |
| usdt_growth7 | SPYx | 1 | ret | +0.037 | +1.09 | 0.274 | 0.87 | +0.046 | +0.003 |  |
| usdt_growth7 | SPYx | 1 | vol | -0.072 | -2.14 | 0.032 | 0.31 | -0.070 | -0.086 | -0.050 |
| usdt_growth7 | SPYx | 5 | ret | +0.065 | +1.11 | 0.266 | 0.87 | +0.063 | +0.071 |  |
| usdt_growth7 | SPYx | 5 | vol | -0.126 | -2.17 | 0.030 | 0.31 | -0.125 | -0.126 | -0.090 |
| vix | BTC | 1 | ret | +0.014 | +0.49 | 0.623 | 0.98 | +0.014 | +0.012 |  |
| vix | BTC | 1 | vol | +0.015 | +0.54 | 0.589 | 0.98 | +0.007 | +0.032 | +0.011 |
| vix | BTC | 7 | ret | +0.048 | +0.85 | 0.393 | 0.94 | +0.044 | +0.069 |  |
| vix | BTC | 7 | vol | +0.010 | +0.17 | 0.863 | 0.98 | -0.000 | +0.058 | +0.003 |
| vix | ETH | 1 | ret | +0.019 | +0.67 | 0.504 | 0.98 | +0.006 | +0.018 |  |
| vix | ETH | 1 | vol | +0.023 | +0.81 | 0.418 | 0.94 | +0.008 | +0.025 | +0.019 |
| vix | ETH | 7 | ret | +0.054 | +0.97 | 0.333 | 0.94 | +0.030 | +0.048 |  |
| vix | ETH | 7 | vol | -0.009 | -0.16 | 0.870 | 0.98 | -0.020 | +0.037 | -0.013 |
| vix | SPYx | 1 | ret | +0.057 | +1.70 | 0.090 | 0.60 | +0.050 | +0.090 |  |
| vix | SPYx | 1 | vol | +0.065 | +1.92 | 0.055 | 0.47 | +0.085 | +0.032 | +0.042 |
| vix | SPYx | 5 | ret | +0.106 | +1.81 | 0.070 | 0.53 | +0.104 | +0.141 |  |
| vix | SPYx | 5 | vol | -0.025 | -0.43 | 0.667 | 0.98 | +0.012 | -0.041 | -0.070 |
| vix_chg7 | BTC | 1 | ret | -0.000 | -0.00 | 0.997 | 1.00 | -0.004 | +0.007 |  |
| vix_chg7 | BTC | 1 | vol | +0.063 | +2.27 | 0.023 | 0.30 | +0.058 | +0.068 | +0.052 |
| vix_chg7 | BTC | 7 | ret | -0.035 | -0.63 | 0.529 | 0.98 | -0.032 | -0.046 |  |
| vix_chg7 | BTC | 7 | vol | +0.135 | +2.43 | 0.015 | 0.26 | +0.148 | +0.112 | +0.117 |
| vix_chg7 | ETH | 1 | ret | -0.005 | -0.17 | 0.869 | 0.98 | -0.015 | +0.019 |  |
| vix_chg7 | ETH | 1 | vol | +0.062 | +2.21 | 0.027 | 0.31 | +0.042 | +0.089 | +0.045 |
| vix_chg7 | ETH | 7 | ret | -0.039 | -0.69 | 0.488 | 0.98 | -0.044 | -0.023 |  |
| vix_chg7 | ETH | 7 | vol | +0.089 | +1.59 | 0.112 | 0.73 | +0.093 | +0.092 | +0.071 |
| vix_chg7 | SPYx | 1 | ret | +0.028 | +0.83 | 0.409 | 0.94 | +0.022 | +0.031 |  |
| vix_chg7 | SPYx | 1 | vol | +0.205 | +6.20 | 0.000 | 0.00 | +0.213 | +0.190 | +0.159 |
| vix_chg7 | SPYx | 5 | ret | -0.003 | -0.04 | 0.965 | 0.98 | -0.025 | +0.039 |  |
| vix_chg7 | SPYx | 5 | vol | +0.312 | +5.62 | 0.000 | 0.00 | +0.352 | +0.238 | +0.229 |
