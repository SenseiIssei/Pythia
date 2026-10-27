# R10: the small-account path, honestly costed

Pre-registered in `results/smallaccount_r10_prereg.md` (committed before any number). Code
`lab/experiments/smallaccount_r10.py` (`python -m lab.experiments.smallaccount_r10`, heavy lock; `--snapshot` records
the inputs below), tests `tests/test_smallaccount_r10.py`. Paper only: nothing here reaches a wallet.

**Verdict: no rule passes late at both wallet sizes. Nothing goes to real money.**

- **Late fills hurt the fast rules.** tsmom1's in-sample Sharpe at 40 EUR falls from 2.03 (today's quotes back to
  2020, filled at its own close, as S1 and S2 ran it) to 1.86 with the costs of their era and to 1.40 a close late;
  over the validation window from 17.5 % to 14.3 % a year at 40 EUR. breakout_sol3 halves (11.3 % to 4.6 %), the
  four crypto genomes of F2 drop to 0 to 2 % a year. L1 barely moves (16.0 % to 15.8 %): its 10 % band trades rarely.
- **Against BTC and ETH held** (half each, -2.8 % a year in EUR over 2024-01 to 2026-06, drawdown 57 %) the crypto
  rules look strong, but no DSR over R5's pool of all (2,767 trials, noise bar 2.80 a year) is above 0.000, and the
  small family's (190 trials, L1's change counted there since R5) at most 0.06 (any rule).
- **Against a UCITS S&P 500 fund in EUR** (SXR8, 18.4 % a year at 40 EUR after a 1 EUR sale, drawdown 23.3 %) the safe
  path fails: only dual_mom beats it (28.5 % late) with a 28.7 % drawdown, vol_target keeps its drawdown at 13 % but
  makes 9.6 %. The fund itself would fail the 20 % drawdown gate.
- **F2's lost survivor** (07493e8a8adb, Donchian 100/50 on all six) is the closest: late 22.5 % / 17.7 % at 40 EUR and
  28.1 % / 17.7 % at 100 EUR, above the fund and under 20 %, but DSR 0.000 over all and 0.03 / 0.05 in the small
  family; over 10 token draws its worst drawdown is 19.8 %. A lead, not evidence.
- **The inputs.** EUR/USD moved between 1.02 and 1.20 over the window (S1 to F2 used 1.1194 throughout). The way in
  and back cost about 40 bps each way plus 1 USDC and 0.09 EUR. SPYx at 00:00 UTC sits 28 bps above SPY's last close
  on average, with a spread of 35 bps after a US close and 49 bps over weekends and holidays. S2's premium series
  lost one point, SPYx's -1094 bps of 2026-08-10; S2's noise and F2's premium noise use the cleaned series from now
  on (F2's next nightly run will show slightly different SPYx benchmark numbers).

Assumptions that stay open: Jupiter-era quotes are today's (2021 to 2023 liquidity was thinner), the CEX era pays
Kraken's taker fee and today's spread, the gold token joins xStocks' date, taxes and the issuer's freeze and
redemption risk are not priced, and whether a German resident may hold SPYx this way is not answered here.

<!-- generated below by lab.experiments.smallaccount_r10; edit above this line only -->

Generated 2026-10-27T20:22:02+00:00. Validation 2024-01-01 to 2026-06-30, in sample 2020-08-01 to 2023-12-31. EUR/USD (ECB) 1.0198 to 1.1974 over the validation window (before R10 fixed at 1.1194). Every wallet in USD, valued in EUR at the day's rate; the way in (Kraken 40.6 bps and 1 USDC) and the way back (positions sold, 40.6 bps, 0.09 EUR) are in every number.

## 1. Late against on time, validation window (the bar)

| rule | EUR | on time CAGR / DD / Sharpe / end | late CAGR / DD / Sharpe / end | benchmark | benchmark CAGR / DD / Sharpe / end | late DSR, pass at 0.95 or more (all / small) | passes late |
|---|---|---|---|---|---|---|---|
| S1 tsmom1 | 40 | 17.5 % / 23.3 % / 0.73 / 59.84 | 14.3 % / 24.8 % / 0.62 / 55.91 | BTC/ETH held | -2.8 % / 56.5 % / 0.20 / 37.30 | 0.000 / 0.028 | no |
| S1 tsmom1 | 100 | 19.2 % / 23.3 % / 0.78 / 155.03 | 15.8 % / 25.6 % / 0.66 / 144.12 | BTC/ETH held | -2.2 % / 57.1 % / 0.22 / 94.71 | 0.000 / 0.028 | no |
| S1 breakout_sol3 | 40 | 11.3 % / 20.4 % / 0.61 / 52.22 | 4.6 % / 24.4 % / 0.32 / 44.76 | BTC/ETH held | -2.8 % / 56.5 % / 0.20 / 37.30 | 0.000 / 0.010 | no |
| S1 breakout_sol3 | 100 | 13.0 % / 20.5 % / 0.68 / 135.75 | 6.2 % / 24.1 % / 0.39 / 116.15 | BTC/ETH held | -2.2 % / 57.1 % / 0.22 / 94.71 | 0.000 / 0.011 | no |
| S2 spy_trend | 40 | 12.8 % / 19.3 % / 0.80 / 54.04 | 11.2 % / 21.3 % / 0.71 / 52.18 | SXR8.DE in EUR | 18.4 % / 23.3 % / 1.21 / 61.05 | 0.000 / 0.004 | no |
| S2 spy_trend | 100 | 13.8 % / 19.5 % / 0.84 / 138.13 | 12.2 % / 21.6 % / 0.76 / 133.31 | SXR8.DE in EUR | 18.9 % / 23.3 % / 1.24 / 154.11 | 0.000 / 0.004 | no |
| S2 dual_mom | 40 | 34.6 % / 28.7 % / 0.90 / 84.03 | 28.5 % / 28.7 % / 0.79 / 74.84 | SXR8.DE in EUR | 18.4 % / 23.3 % / 1.21 / 61.05 | 0.000 / 0.057 | no |
| S2 dual_mom | 100 | 36.3 % / 29.0 % / 0.92 / 216.66 | 30.0 % / 29.0 % / 0.81 / 192.72 | SXR8.DE in EUR | 18.9 % / 23.3 % / 1.24 / 154.11 | 0.000 / 0.060 | no |
| S2 mix_6040 | 40 | 16.9 % / 25.6 % / 0.73 / 59.07 | 16.7 % / 25.6 % / 0.73 / 58.86 | SXR8.DE in EUR | 18.4 % / 23.3 % / 1.21 / 61.05 | 0.000 / 0.017 | no |
| S2 mix_6040 | 100 | 17.2 % / 25.9 % / 0.75 / 148.59 | 16.7 % / 25.9 % / 0.73 / 147.04 | SXR8.DE in EUR | 18.9 % / 23.3 % / 1.24 / 154.11 | 0.000 / 0.015 | no |
| S2 trend_mix | 40 | 12.6 % / 26.8 % / 0.69 / 53.83 | 8.5 % / 26.6 % / 0.50 / 49.04 | SXR8.DE in EUR | 18.4 % / 23.3 % / 1.21 / 61.05 | 0.000 / 0.003 | no |
| S2 trend_mix | 100 | 14.0 % / 26.6 % / 0.76 / 138.71 | 10.8 % / 26.2 % / 0.61 / 129.10 | SXR8.DE in EUR | 18.9 % / 23.3 % / 1.24 / 154.11 | 0.000 / 0.004 | no |
| S2 vol_target | 40 | 10.3 % / 13.2 % / 0.77 / 51.06 | 9.6 % / 13.2 % / 0.74 / 50.31 | SXR8.DE in EUR | 18.4 % / 23.3 % / 1.21 / 61.05 | 0.000 / 0.002 | no |
| S2 vol_target | 100 | 16.3 % / 12.8 % / 1.14 / 145.95 | 15.7 % / 12.6 % / 1.10 / 143.86 | SXR8.DE in EUR | 18.9 % / 23.3 % / 1.24 / 154.11 | 0.000 / 0.008 | no |
| L1 onchain_longterm | 40 | 16.0 % / 25.4 % / 0.67 / 57.96 | 15.8 % / 25.2 % / 0.66 / 57.73 | BTC/ETH held | -2.8 % / 56.5 % / 0.20 / 37.30 | 0.000 / 0.033 | no |
| L1 onchain_longterm | 100 | 18.4 % / 24.0 % / 0.77 / 152.36 | 18.2 % / 25.3 % / 0.76 / 151.73 | BTC/ETH held | -2.2 % / 57.1 % / 0.22 / 94.71 | 0.000 / 0.033 | no |
| F2 f2 b5682877eff9 | 40 | 9.2 % / 20.8 % / 0.58 / 49.81 | 8.5 % / 21.3 % / 0.55 / 49.06 | SXR8.DE in EUR | 18.4 % / 23.3 % / 1.21 / 61.05 | 0.000 / 0.003 | no |
| F2 f2 b5682877eff9 | 100 | 11.5 % / 20.9 % / 0.70 / 131.35 | 10.8 % / 21.6 % / 0.67 / 129.24 | SXR8.DE in EUR | 18.9 % / 23.3 % / 1.24 / 154.11 | 0.000 / 0.004 | no |
| F2 f2 07493e8a8adb | 40 | 23.2 % / 17.7 % / 0.99 / 67.39 | 22.5 % / 17.7 % / 0.95 / 66.44 | SXR8.DE in EUR | 18.4 % / 23.3 % / 1.21 / 61.05 | 0.000 / 0.031 | no |
| F2 f2 07493e8a8adb | 100 | 28.9 % / 17.3 % / 1.15 / 188.58 | 28.1 % / 17.7 % / 1.11 / 185.53 | SXR8.DE in EUR | 18.9 % / 23.3 % / 1.24 / 154.11 | 0.000 / 0.052 | no |
| F2 f2 e59b67ee5a1d | 40 | 1.3 % / 23.4 % / 0.16 / 41.33 | 1.6 % / 19.4 % / 0.18 / 41.64 | SXR8.DE in EUR | 18.4 % / 23.3 % / 1.21 / 61.05 | 0.000 / 0.000 | no |
| F2 f2 e59b67ee5a1d | 100 | 2.8 % / 23.3 % / 0.26 / 107.16 | 3.1 % / 19.8 % / 0.28 / 107.90 | SXR8.DE in EUR | 18.9 % / 23.3 % / 1.24 / 154.11 | 0.000 / 0.000 | no |
| F2 f2 c0e71d553d62 | 40 | 3.2 % / 26.1 % / 0.26 / 43.33 | 4.2 % / 26.2 % / 0.31 / 44.37 | SXR8.DE in EUR | 18.4 % / 23.3 % / 1.21 / 61.05 | 0.000 / 0.001 | no |
| F2 f2 c0e71d553d62 | 100 | 6.4 % / 24.3 % / 0.40 / 116.75 | 6.6 % / 24.7 % / 0.42 / 117.28 | SXR8.DE in EUR | 18.9 % / 23.3 % / 1.24 / 154.11 | 0.000 / 0.002 | no |
| F2 f2 48a3ab94cfbf | 40 | 6.1 % / 19.7 % / 0.47 / 46.36 | 0.5 % / 27.1 % / 0.11 / 40.55 | BTC/ETH held | -2.8 % / 56.5 % / 0.20 / 37.30 | 0.000 / 0.007 | no |
| F2 f2 48a3ab94cfbf | 100 | 7.8 % / 19.0 % / 0.57 / 120.76 | 2.1 % / 26.4 % / 0.21 / 105.25 | BTC/ETH held | -2.2 % / 57.1 % / 0.22 / 94.71 | 0.000 / 0.007 | no |
| F2 f2 c4a2cb34cffe | 40 | 3.4 % / 22.6 % / 0.28 / 43.48 | 0.1 % / 25.6 % / 0.09 / 40.06 | BTC/ETH held | -2.8 % / 56.5 % / 0.20 / 37.30 | 0.000 / 0.006 | no |
| F2 f2 c4a2cb34cffe | 100 | 4.5 % / 22.7 % / 0.34 / 111.73 | 2.0 % / 25.9 % / 0.20 / 105.09 | BTC/ETH held | -2.2 % / 57.1 % / 0.22 / 94.71 | 0.000 / 0.007 | no |
| F2 f2 6b4cb30de288 | 40 | 1.7 % / 23.7 % / 0.18 / 41.68 | -3.5 % / 27.3 % / -0.12 / 36.55 | BTC/ETH held | -2.8 % / 56.5 % / 0.20 / 37.30 | 0.000 / 0.004 | no |
| F2 f2 6b4cb30de288 | 100 | 3.1 % / 22.7 % / 0.26 / 107.97 | -2.1 % / 26.0 % / -0.03 / 94.82 | BTC/ETH held | -2.2 % / 57.1 % / 0.22 / 94.71 | 0.000 / 0.004 | no |
| F2 f2 f002c52e3c72 | 40 | 4.2 % / 19.1 % / 0.35 / 44.38 | 0.3 % / 24.8 % / 0.09 / 40.29 | BTC/ETH held | -2.8 % / 56.5 % / 0.20 / 37.30 | 0.000 / 0.006 | no |
| F2 f2 f002c52e3c72 | 100 | 5.6 % / 17.5 % / 0.44 / 114.49 | 1.7 % / 23.1 % / 0.19 / 104.36 | BTC/ETH held | -2.2 % / 57.1 % / 0.22 / 94.71 | 0.000 / 0.007 | no |

DSR: of the late wallet's daily excess over its benchmark in EUR, over R5's trial registry, the pool of all (2,767 trials, noise bar 2.80 a year) and the small family (190 trials, 1.38); higher is better. `passes late`: the pre-registered bar at 40 and at 100 EUR, filled one close late.

## 2. The verdict

| rule | kind | passes on time | passes late | late fails on | late 40 EUR over 10 token draws (median CAGR / worst DD) |
|---|---|---|---|---|---|
| S1 tsmom1 | crypto | no | no | 40 EUR: DSR >= 0.95; 100 EUR: DSR >= 0.95 |  |
| S1 breakout_sol3 | crypto | no | no | 40 EUR: DSR >= 0.95; 100 EUR: DSR >= 0.95 |  |
| S2 spy_trend | safe path | no | no | 40 EUR: DD < 20 %; 40 EUR: CAGR >= fund - 1 pt; 40 EUR: DSR >= 0.95; 100 EUR: DD < 20 % ... | 11.3 % / 21.6 % |
| S2 dual_mom | safe path | no | no | 40 EUR: DD < 20 %; 40 EUR: DSR >= 0.95; 100 EUR: DD < 20 %; 100 EUR: DSR >= 0.95 | 28.2 % / 29.4 % |
| S2 mix_6040 | safe path | no | no | 40 EUR: DD < 20 %; 40 EUR: CAGR >= fund - 1 pt; 40 EUR: DSR >= 0.95; 100 EUR: DD < 20 % ... | 16.5 % / 25.9 % |
| S2 trend_mix | safe path | no | no | 40 EUR: DD < 20 %; 40 EUR: CAGR >= fund - 1 pt; 40 EUR: DSR >= 0.95; 100 EUR: DD < 20 % ... | 8.6 % / 26.7 % |
| S2 vol_target | safe path | no | no | 40 EUR: CAGR >= fund - 1 pt; 40 EUR: DSR >= 0.95; 100 EUR: CAGR >= fund - 1 pt; 100 EUR: DSR >= 0.95 | 9.6 % / 13.3 % |
| L1 onchain_longterm | crypto | no | no | 40 EUR: DSR >= 0.95; 100 EUR: DSR >= 0.95 |  |
| F2 f2 b5682877eff9 | safe path | no | no | 40 EUR: DD < 20 %; 40 EUR: CAGR >= fund - 1 pt; 40 EUR: DSR >= 0.95; 100 EUR: DD < 20 % ... | 8.8 % / 22.5 % |
| F2 f2 07493e8a8adb | safe path | no | no | 40 EUR: DSR >= 0.95; 100 EUR: DSR >= 0.95 | 22.3 % / 19.8 % |
| F2 f2 e59b67ee5a1d | safe path | no | no | 40 EUR: CAGR >= fund - 1 pt; 40 EUR: DSR >= 0.95; 100 EUR: CAGR >= fund - 1 pt; 100 EUR: DSR >= 0.95 | 2.3 % / 19.7 % |
| F2 f2 c0e71d553d62 | safe path | no | no | 40 EUR: DD < 20 %; 40 EUR: CAGR >= fund - 1 pt; 40 EUR: DSR >= 0.95; 100 EUR: DD < 20 % ... | 4.7 % / 25.8 % |
| F2 f2 48a3ab94cfbf | crypto | no | no | 40 EUR: Sharpe > BTC/ETH; 40 EUR: DSR >= 0.95; 100 EUR: Sharpe > BTC/ETH; 100 EUR: DSR >= 0.95 |  |
| F2 f2 c4a2cb34cffe | crypto | no | no | 40 EUR: Sharpe > BTC/ETH; 40 EUR: DSR >= 0.95; 100 EUR: Sharpe > BTC/ETH; 100 EUR: DSR >= 0.95 |  |
| F2 f2 6b4cb30de288 | crypto | no | no | 40 EUR: CAGR > 0; 40 EUR: Sharpe > BTC/ETH; 40 EUR: DSR >= 0.95; 100 EUR: CAGR > 0 ... |  |
| F2 f2 f002c52e3c72 | crypto | no | no | 40 EUR: Sharpe > BTC/ETH; 40 EUR: DSR >= 0.95; 100 EUR: Sharpe > BTC/ETH; 100 EUR: DSR >= 0.95 |  |

**For real money: nothing.**

## 3. In sample at 40 EUR: what the honest costs and the late fill take (Sharpe)

| rule | today's quotes back to 2020, on time (as before) | costs of their era, on time | costs of their era, late |
|---|---|---|---|
| S1 tsmom1 | 2.03 | 1.86 | 1.40 |
| S1 breakout_sol3 | 1.83 | 1.78 | 1.70 |
| S2 spy_trend | 0.79 | 0.62 | 0.58 |
| S2 dual_mom | 0.41 | 0.35 | 0.29 |
| S2 mix_6040 | 1.05 | 1.04 | 1.04 |
| S2 trend_mix | 1.25 | 1.12 | 1.17 |
| S2 vol_target | 0.69 | 0.53 | 0.50 |
| L1 onchain_longterm | 2.05 | 1.93 | 1.53 |
| F2 f2 b5682877eff9 | 2.07 | 1.94 | 1.84 |
| F2 f2 07493e8a8adb | 1.73 | 1.60 | 1.66 |
| F2 f2 e59b67ee5a1d | 1.63 | 1.37 | 1.10 |
| F2 f2 c0e71d553d62 | 1.67 | 1.17 | 1.45 |
| F2 f2 48a3ab94cfbf | 1.53 | 1.42 | 1.32 |
| F2 f2 c4a2cb34cffe | 1.67 | 1.59 | 1.47 |
| F2 f2 6b4cb30de288 | 1.28 | 1.22 | 1.13 |
| F2 f2 f002c52e3c72 | 1.35 | 1.27 | 1.15 |

## 4. The benchmarks over the validation window (CAGR / DD / Sharpe / end in EUR)

| benchmark | EUR | CAGR / DD / Sharpe / end |
|---|---|---|
| btc_eth | 40 | -2.8 % / 56.5 % / 0.20 / 37.30 |
| btc | 40 | 8.5 % / 51.2 % / 0.41 / 49.03 |
| SXR8.DE | 40 | 18.4 % / 23.3 % / 1.21 / 61.05 |
| EUNL.DE | 40 | 17.4 % / 21.7 % / 1.23 / 59.74 |
| btc_eth | 100 | -2.2 % / 57.1 % / 0.22 / 94.71 |
| btc | 100 | 9.4 % / 51.6 % / 0.43 / 125.09 |
| SXR8.DE | 100 | 18.9 % / 23.3 % / 1.24 / 154.11 |
| EUNL.DE | 100 | 17.9 % / 21.7 % / 1.26 / 150.85 |

`btc_eth`: half BTC, half ETH bought once (the wallet's costs, way in and back); `btc` BTC alone; `SXR8.DE` iShares Core S&P 500 UCITS Acc, `EUNL.DE` iShares Core MSCI World UCITS Acc, both in EUR on Xetra, bought through a free savings plan, sold at 1 EUR.

## 5. The inputs

| token | mean at 00:00 UTC (bps) | after a US close: n / sd bps | no US close: n / sd bps | dropped as bad prints |
|---|---|---|---|---|
| SPY | 28.5 | 251 / 34.7 | 114 / 49.5 | 0 |
| QQQ | 16.6 | 250 / 34.1 | 114 / 67.4 | 1 |
| GOLD | 5.5 | 250 / 51.4 | 114 / 86.7 | 1 |

Costs of their era: on chain (today's recorded quotes and network fee) from BTC 2024-11-07, SPY 2025-06-30, QQQ 2025-06-30, GOLD 2025-06-30, everything else from 2021-10-01; before that Kraken's taker fee and half spread (BTC 40.0 bps, ETH 40.0 bps, SOL 40.5 bps, 50 bps without a Kraken pair). S2's premiums at the US close cleaned of SPYx -1094 bps on 2026-08-10.

