# D1: the small-account rules on the long history, from 2018

Code `lab.history` (the data) and `lab.experiments.smallaccount_d1` (the re-run), run 2026-10-26. S1 and S2 had
seen 2020-08 to 2026 only. Here the same pre-registered candidates, wallets and costs (no new candidate, nothing
tuned) run from the close of 2017-12-31 to 2026-10-09: S2's eight at 40 EUR, S1's eight (daily, Jupiter, 50 EUR)
and its two paper picks. The tables below are generated.

## Answer

- **Data.** BTC and ETH daily from 2017-08-17 (Binance's archive), SOL from 2020-08-12, PAXG from 2020-08-28 (for
  the check only; the gold token stays GLD with S2's drift, as in S2), SPY and QQQ from 2000 and GLD from 2004 were
  already in `etf/daily`. 99 pairs have bars before 2020-04, delisted ones included. No close of the overlaps is
  more than 0.5 % apart: Binance daily against the panel (2020 to 2026), Kraken against Binance (the last 695 days,
  at most 0.41 %, PAXG), Yahoo against the lab's ETF copy.
- **The check that nothing else moved:** from 2024 the long panel gives S2's numbers exactly (SPYx 20.4 % a year,
  drawdown 18.1 %; tsmom1 28.5 %, 17.8 %) and S1's within 1 point (the end date differs).
- **S2's verdict holds only in part.** Over 2018 to 2026 nothing passes S2's bar (drawdown under 20 %, at most
  1 point behind SPYx). tsmom1 makes 39.1 % a year against 14.6 % for SPYx (its lead's band 3.6 to 49.4 points,
  above 0 now), was in USDC through March 2020 and all of 2022 and lost 12.2 % in 2018, but its deepest fall is
  23.0 % (2019-06-26 to 2020-08-01, 402 days): 3 points too deep. Holding SPYx is still the benchmark but not safe
  either: 32.5 % down in 2020 (170 days), -17.5 % in 2022. The safe ETF rules stay safe and stay behind: spy_trend
  10.7 %, drawdown 19.6 % (752 days); vol_target 10.6 %, 15.6 %. dual_mom, 60/40 and trend_mix fall 32 to 67 %.
- **S1's paper picks** were not tested on a crash before and hold up in return, not in drawdown:
  `small50_tsmom1` 39.6 % a year, drawdown 24.2 % (482 days), 2018 -14.2 %; `small100_breakout_sol3` 38.4 %,
  26.3 % (447 days), 2022 -19.6 %. breakout_btceth 38.6 %, 36.3 %; BTC gated 26.2 %, 62.9 %; BTC held 22.0 %,
  78.9 % (1,046 days). The 10 and 20 coin rules still hardly trade at 50 EUR (the minimum).
- **For the owner's wallet:** the one rule S2 let through still earns far more than SPYx with a smaller fall, but
  "fairly safe" (under 20 %) did not hold in 2019 to 2020. Nothing to switch on or off from this; the paper books
  run as they are.
- **Factories:** the weekly factory and F2 search in sample from 2018-01-01 now (2018, March 2020 and 2022 in it),
  held back from 2024 as before. Rows scored on the old window (2020-08) stay trials in the pool, but are not bred
  from or held back again.

## Notes

- Warm-up: the panel starts 2017-08-17, so BTC's 200-day average exists from 2018-03-04 and 365-day returns from
  2018-08-17; rules that need them hold USDC until then (tsmom1 bought BTC on that day at about 11,500 USD).
- Costs are today's (S1's and S2's recorded Jupiter ladders, fee, minimum, reserve) applied to every year; a
  wallet like this did not exist in 2018. Before SOL's listing the network fee is 0 and the SOL reserve is priced
  at 100 EUR a SOL, as S1's and S2's code does (a fraction of a cent a swap either way).
- Closes are USDT taken as USD, as everywhere in the lab; Kraken's keyless OHLC reaches back 720 days only, so
  the 2018 closes are checked against the panel and not against a second venue.
- The pre-2020 bars are daily, so their realised variance is the day's range (Parkinson) instead of the sum of
  hourly returns. Data: `python -m lab.history fetch` (once, resumable; the weekly factory runs it on its own).

<!-- generated below by lab.experiments.smallaccount_d1; edit above this line only -->

Generated 2026-10-26T20:46:57+00:00. One wallet per candidate from the close of 2017-12-31 to 2026-10-09, EUR/USD 1.1194, S2's drift a year: SPY +0.34 %, GOLD +0.98 %.

## 1. The data

| series | first | last | days |
|---|---|---|---|
| BTCUSDT | 2017-08-17 | 2026-10-11 | 3342 |
| ETHUSDT | 2017-08-17 | 2026-10-11 | 3342 |
| SOLUSDT | 2020-08-12 | 2026-10-11 | 2252 |
| SPY (etf/daily) | 2000-01-03 | 2026-10-09 |  |
| QQQ (etf/daily) | 2000-01-03 | 2026-10-09 |  |
| GLD (etf/daily) | 2004-11-18 | 2026-10-09 |  |
| PAXGUSDT (Binance, checks only) | 2020-08-28 |  |  |

88 pair segments have daily bars before 2020 (delisted pairs included).

## 2. Overlaps (closes more than 0.5 % apart)

| check | series | days | from | to | over 0.5 % | largest |
|---|---|---|---|---|---|---|
| Binance daily vs the panel | BTCUSDT | 2464 | 2020-01-01 | 2026-09-30 | 0 | 0.00 % |
| Binance daily vs the panel | ETHUSDT | 2464 | 2020-01-01 | 2026-09-30 | 0 | 0.00 % |
| Binance daily vs the panel | SOLUSDT | 2241 | 2020-08-12 | 2026-09-30 | 0 | 0.00 % |
| Kraken USD vs Binance USDT | BTCUSDT | 695 | 2024-11-05 | 2026-09-30 | 0 | 0.22 % |
| Kraken USD vs Binance USDT | ETHUSDT | 695 | 2024-11-05 | 2026-09-30 | 0 | 0.25 % |
| Kraken USD vs Binance USDT | SOLUSDT | 695 | 2024-11-05 | 2026-09-30 | 0 | 0.24 % |
| Kraken USD vs Binance USDT | PAXGUSDT | 695 | 2024-11-05 | 2026-09-30 | 0 | 0.41 % |
| Yahoo now vs etf/daily | SPY | 6733 | 2000-01-03 | 2026-10-09 | 0 | 0.00 % |
| Yahoo now vs etf/daily | QQQ | 6733 | 2000-01-03 | 2026-10-09 | 0 | 0.00 % |
| Yahoo now vs etf/daily | GLD | 5507 | 2004-11-18 | 2026-10-09 | 0 | 0.00 % |
| Binance daily vs the panel | 93 other pairs, 2020-01 to 03 | 7852 |  |  | 0 | 0.00 % |

PAXG against GLD (2020-08-28 to 2026-09-30, 1529 days): tracking error 8.0 % a year, largest gap around the median ratio 4.6 %, 37 days over 2 %.

## 3. S2's candidates at 40 EUR (S2's wallet, Jupiter, Sender tip, 5 USDC minimum)

| candidate | 2018 | 2020-03 | 2022 | CAGR | Sharpe | deepest drawdown | end EUR | bar | S2's window (2024 on) |
|---|---|---|---|---|---|---|---|---|---|
| spy_hold | -4.1 % (DD 18 %) | -12.0 % (DD 27 %) | -17.5 % (DD 24 %) | 14.6 % | 0.84 | 32.5 %, 2020-02-19 to 2020-08-07 (170 days) | 132.82 | reference | 20.4 % / 18.1 % |
| btc_hold | -69.8 % (DD 78 %) | -23.1 % (DD 44 %) | -63.3 % (DD 66 %) | 22.2 % | 0.64 | 78.2 %, 2018-01-06 to 2020-11-17 (1046 days) | 231.82 | reference | 24.3 % / 52.1 % |
| spy_trend | -0.5 % (DD 10 %) | -5.9 % (DD 6 %) | -14.8 % (DD 15 %) | 10.7 % | 0.90 | 19.6 %, 2022-01-03 to 2024-01-25 (752 days) | 97.66 | behind | 16.4 % / 9.9 % |
| dual_mom | -6.7 % (DD 19 %) | -23.1 % (DD 44 %) | -26.5 % (DD 31 %) | 26.1 % | 0.74 | 66.5 %, 2019-06-26 to 2020-12-17 (540 days) | 306.58 | too deep | 35.8 % / 25.4 % |
| mix_6040 | -34.8 % (DD 43 %) | -17.1 % (DD 30 %) | -38.8 % (DD 41 %) | 22.0 % | 0.82 | 47.8 %, 2021-11-08 to 2024-02-14 (828 days) | 230.02 | too deep | 25.1 % / 23.1 % |
| trend_mix | -13.2 % (DD 18 %) | -7.3 % (DD 7 %) | -9.5 % (DD 10 %) | 19.8 % | 1.00 | 32.4 %, 2021-04-15 to 2023-12-21 (980 days) | 195.41 | too deep | 18.4 % / 18.0 % |
| tsmom1 | -12.2 % (DD 12 %) | 0.0 % (DD 0 %) | 0.0 % (DD 0 %) | 39.1 % | 1.45 | 23.0 %, 2019-06-26 to 2020-08-01 (402 days) | 725.01 | too deep | 28.5 % / 17.8 % |
| vol_target | -2.6 % (DD 9 %) | -5.8 % (DD 11 %) | -10.6 % (DD 16 %) | 10.6 % | 1.14 | 15.6 %, 2022-03-27 to 2023-11-15 (598 days) | 96.59 | behind | 14.4 % / 10.0 % |

Each period: the return from the close before it, in brackets the drawdown inside it. Bar: drawdown under 20 % and CAGR at least holding SPYx's minus 1 point over the whole run. S2's window: CAGR / drawdown from 2024 as S2 measured it, on the long panel.

| candidate | CAGR minus SPYx | band 5 to 95 % | draws above |
|---|---|---|---|
| btc_hold | 7.5 % | -25.7 % to 58.4 % | 63 % |
| spy_trend | -3.9 % | -11.2 % to 3.1 % | 19 % |
| dual_mom | 11.5 % | -14.5 % to 47.9 % | 75 % |
| mix_6040 | 7.4 % | -7.5 % to 26.0 % | 78 % |
| trend_mix | 5.2 % | -8.1 % to 20.6 % | 74 % |
| tsmom1 | 24.4 % | 3.6 % to 49.4 % | 98 % |
| vol_target | -4.1 % | -11.9 % to 3.4 % | 21 % |

## 4. S1's candidates (daily, Jupiter, 50 EUR, and the two paper picks)

| candidate | 2018 | 2020-03 | 2022 | CAGR | Sharpe | deepest drawdown | end EUR | costs | S1's bar | S1's window (2024 on) |
|---|---|---|---|---|---|---|---|---|---|---|
| btc_hold · 1 coin · daily · 50 EUR | -71.1 % (DD 79 %) | -23.4 % (DD 45 %) | -63.5 % (DD 66 %) | 22.0 % | 0.63 | 78.9 %, 2018-01-06 to 2020-11-17 (1046 days) | 285.91 | 0.5 % | reference | 23.5 % / 52.2 % |
| btc_gated · 1 coin · daily · 50 EUR | -35.0 % (DD 35 %) | -9.6 % (DD 12 %) | 0.0 % (DD 0 %) | 26.2 % | 0.77 | 62.9 %, 2021-04-13 to 2024-02-28 (1051 days) | 386.17 | 0.5 % | yes | 20.7 % / 30.6 % |
| breakout_btceth · 2 coins · daily · 50 EUR | -2.2 % (DD 2 %) | 0.0 % (DD 0 %) | 0.0 % (DD 0 %) | 38.6 % | 1.17 | 36.3 %, 2021-05-11 to 2024-02-14 (1009 days) | 879.87 | 0.2 % | yes | 23.3 % / 26.7 % |
| breakout_top10 · 10 coins · daily · 50 EUR | -2.2 % (DD 2 %) | 0.0 % (DD 0 %) | 0.0 % (DD 0 %) | 3.2 % | 0.94 | 3.8 %, 2024-03-11 to 2024-11-11 (245 days) | 65.79 | 10.4 % | yes | 1.4 % / 2.6 % |
| breakout_sol · 10 coins · daily · 50 EUR | -2.2 % (DD 2 %) | 0.0 % (DD 0 %) | 0.0 % (DD 0 %) | 3.1 % | 0.90 | 3.8 %, 2024-03-11 to 2024-11-11 (245 days) | 65.63 | 10.8 % | yes | 1.4 % / 2.6 % |
| tsmom_top20 · 20 coins · daily · 50 EUR | -2.2 % (DD 2 %) | 0.0 % (DD 0 %) | 0.0 % (DD 0 %) | -0.3 % | -0.34 | 0.0 %, 2017-12-31 to not yet (3204 days) | 48.91 | n/a | no | -0.8 % / 0.0 % |
| trend_carry · 20 coins · daily · 50 EUR | -2.2 % (DD 2 %) | 0.0 % (DD 0 %) | 0.0 % (DD 0 %) | -0.3 % | -0.34 | 0.0 %, 2017-12-31 to not yet (3204 days) | 48.91 | n/a | no | -0.8 % / 0.0 % |
| memes_rotation · 1 coin · daily · 50 EUR | -2.2 % (DD 2 %) | 0.0 % (DD 0 %) | 0.0 % (DD 0 %) | 2.3 % | 0.27 | 18.5 %, 2024-07-21 to 2025-05-12 (295 days) | 60.86 | 20.2 % | no | 7.3 % / 18.5 % |
| tsmom_top20 · 1 coin · daily · 50 EUR | -14.2 % (DD 14 %) | 0.0 % (DD 0 %) | 0.0 % (DD 0 %) | 39.6 % | 1.46 | 24.2 %, 2019-06-26 to 2020-10-20 (482 days) | 935.15 | 0.8 % | yes | 29.6 % / 17.2 % |
| breakout_sol · 3 coins · daily · 100 EUR | -3.1 % (DD 11 %) | 0.0 % (DD 0 %) | -19.6 % (DD 24 %) | 38.4 % | 1.48 | 26.3 %, 2021-11-08 to 2023-01-29 (447 days) | 1736.18 | 0.3 % | yes | 18.4 % / 20.3 % |

S1's bar over the whole run: CAGR above 0, Sharpe above BTC held, costs under half the gain before costs. Coins without a Solana mint are cash, as in S1.

