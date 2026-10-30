# DT1: day trading on every liquid listed coin (no rug risk), flat by 23:55 UTC

Pre-registered in `results/daytrade_dt1_prereg.md` (committed before the first run). Code:
`lab.experiments.daytrade_dt1`, tests `tests/test_daytrade_dt1.py`. Paper only: nothing a live bot, a wallet or the
engine reads changed.

Run 2026-10-30 as registered, the lockbox not read (minutes to 2026-06-30; the price check alone uses late October
2026, prices only). 656 trials in R5's registry (hand family, with their in-sample Sharpes; written to a copy in the
agent run, the server's registry gets them from it), registered before any out-of-sample number. Data: 5,245 months
of Binance USD-M 1-minute klines of 379 perps (delisted ones included) from data.binance.vision, cached in the
agent's folder, not in `<data>`.

## Reading

**No. Not one of 164 day-trading rules earns money after the costs of a venue the owner can reach, in any of the
four cases. Do not fund a day-trading bot on these rules.**

- **The edge before costs is about zero.** Out of sample on the coins Hyperliquid lists, the median rule makes
  +1 bp gross per trade (spikes), -0.8 bp (opening ranges), +2 bps (VWAP), +6 bps (the model). A Hyperliquid taker
  round trip costs about 12 bps (2 x 4.5 fee plus about 1.4 bps slippage a side), so the median rule nets -10.7 bps a
  trade and the median break-even fee is -0.8 bps a side: it would need a rebate. Minute spikes have no
  continuation and no reversal worth trading (Sharpe -13 median); trading them at 1 to 5 minutes loses 11 to 13 bps
  on every trade, hundreds of trades a day.
- **Maker orders do not rescue it.** At 1.5 bps with the trade-through fill model the median rule still nets
  -9.6 bps per filled trade: the limit fills when the price comes back, the trades it misses are the good ones
  (fast_maker found the same on 5-minute bars). Kraken Futures (5 bps) is worse than Hyperliquid by construction.
- **The closest call is noise.** The model at 15 minutes with the largest margin (`P-gbm:H15:m20`, the in-sample
  pick for H15) makes +13.3 bps net per trade out of sample (Sharpe 1.16, 4 trades a day), but its day-block
  bootstrap band reaches -4.0 bps, one minute late it is -0.6 bps, on the whole Binance universe its Sharpe is
  -0.09, in sample it lost 7.0 bps a trade (Sharpe -1.41), and its DSR is 0.007 against a noise bar of 3.14 over
  3,906 trials. The US-session opening range (`D-orb:us30:A`) is the only family near zero on both universes
  (gross +10 bps, net -1.8 bps, Sharpe -0.02).
- **"No rug risk" holds only in the narrow sense.** The universe (50 to 85 coins a day at 50 M, 35 to 70 of them on
  Hyperliquid) has no one-transaction rugs, but it is not tail free: on 2025-10-10 at 21:19 UTC liquid coins fell
  45 to 62 % within one minute (IP, TRUMP, ETHFI, TON, ENA) and rebounded as fast; LUNA lost 99 % over
  2022-05-11/12, OM 84 % on 2025-04-13, FTT's low was -89 % on 2022-11-08. A stop does not fill at its price in such a
  minute; the simulation fills it at the next open, which is what a real stop gets.
- **Binance minutes stand in for Hyperliquid's** on the majors (median gap 1 to 3 bps, return correlation 0.92 to
  0.97 for BTC, ETH, SOL, XRP); HYPE (11 bps) and BNB (9 bps) differ more, and smaller coins' minute returns agree
  less (0.64 to 0.86), so a rule living on single-minute moves of mid caps would be worse on Hyperliquid than here.

What the owner can do: nothing to fund. Day trading on these coins at these costs is a hobby budget, not an edge.
In fast_maker the only family that paid after costs held for about 8 days, and it did not pass either.

<!-- generated below by lab.experiments.daytrade_dt1; edit above this line only -->

Generated 2026-10-30T03:20:41+00:00. Binance USD-M 1-minute klines 2022-01-01 to 2026-06-30 (no minute after it downloaded or read: the lockbox untouched); in sample 2022-01-01 to 2024-12-31, judged out of sample 2025-01-01 to 2026-06-30 (546 days) on the coins Hyperliquid listed each day. 164 rules in 4 cases, 656 trials in R5's registry (hand family, each with its in-sample Sharpe, registered before any out-of-sample number); pool of all 3906 trials, noise bar 3.14 a year.

## Verdict

**No day-trading rule passes. None earns money after the costs of a venue the owner can reach with the significance the pass rule asks for, so nothing reaches a paper book.**

- Hyperliquid taker, out of sample: 5 of 164 rules make more than 0 bps net per trade (at least 100 trades); 2 have a Sharpe above 0; BTC buy and hold on the same days -0.49.
- Median break-even fee a side (Hyperliquid's taker is 4.5 bps): -0.8 bps; best 11.1 bps.
- Maker case: 4 of 164 rules net positive per filled trade; Kraken Futures: 2.
- P picks (margin fitted in sample): H15: P-gbm:H15:m20, H60: P-gbm:H60:m10.

## Universe (point in time, survivorship free)

Coins a day by quarter: Binance USDT-M perps listed 180 days with the 30-day mean quote volume at the bar (stablecoins, fiat, commodity, equity, index and leveraged products out); `hl` the 50 M coins Hyperliquid listed that day (its listing history starts 2023-05-12); `ever` the coins in the 50 M universe on any day of the quarter.

| quarter | 20 M | 50 M | 50 M most | 100 M | hl | ever 50 M |
|---|---|---|---|---|---|---|
| 2022Q1 | 103.6 | 64.3 | 78 | 39.7 | 0.0 | 96 |
| 2022Q2 | 113.0 | 70.8 | 83 | 45.6 | 0.0 | 106 |
| 2022Q3 | 99.0 | 55.7 | 67 | 36.6 | 0.0 | 85 |
| 2022Q4 | 85.9 | 48.6 | 59 | 33.1 | 0.0 | 74 |
| 2023Q1 | 102.1 | 57.1 | 75 | 34.3 | 0.0 | 92 |
| 2023Q2 | 96.1 | 54.5 | 61 | 32.6 | 9.0 | 85 |
| 2023Q3 | 92.4 | 55.7 | 63 | 34.3 | 25.1 | 91 |
| 2023Q4 | 108.2 | 61.9 | 81 | 40.0 | 39.6 | 106 |
| 2024Q1 | 138.0 | 83.3 | 113 | 52.5 | 52.7 | 141 |
| 2024Q2 | 138.5 | 80.6 | 113 | 50.2 | 53.7 | 143 |
| 2024Q3 | 105.0 | 60.8 | 67 | 37.4 | 50.5 | 100 |
| 2024Q4 | 148.9 | 86.4 | 119 | 54.6 | 69.6 | 143 |
| 2025Q1 | 129.5 | 77.8 | 113 | 49.3 | 65.0 | 134 |
| 2025Q2 | 114.0 | 64.3 | 69 | 39.0 | 55.1 | 113 |
| 2025Q3 | 131.1 | 70.6 | 76 | 48.6 | 62.4 | 116 |
| 2025Q4 | 120.6 | 66.0 | 77 | 41.9 | 57.4 | 118 |
| 2026Q1 | 95.2 | 50.9 | 59 | 27.2 | 42.3 | 98 |
| 2026Q2 | 106.2 | 51.5 | 60 | 26.4 | 35.2 | 108 |

## The rug-like tail inside the universe

Worst and best single minutes (log return of a 1-minute close) of a universe coin on a universe day:

| coin | minute (UTC) | % |
|---|---|---|
| IPUSDT | 2025-10-10T21:18 | -62.1 |
| TRUMPUSDT | 2025-10-10T21:19 | -58.5 |
| FORMUSDT | 2025-10-10T21:26 | -58.1 |
| ETHFIUSDT | 2025-10-10T21:19 | -57.7 |
| TUTUSDT | 2025-10-10T21:21 | -57.7 |
| TONUSDT | 2025-10-10T21:19 | -50.8 |
| TSTUSDT | 2025-10-10T21:20 | -47.0 |
| IPUSDT | 2025-10-10T21:19 | -46.6 |
| TUTUSDT | 2025-10-10T21:20 | -46.0 |
| ENAUSDT | 2025-10-10T21:19 | -45.6 |
| SUIUSDT | 2025-10-10T21:21 | 61.4 |
| ENAUSDT | 2025-10-10T21:21 | 64.6 |
| FORMUSDT | 2025-10-10T21:23 | 69.1 |
| AXSUSDT | 2022-11-13T13:40 | 70.0 |
| OMNIUSDT | 2025-07-29T08:50 | 87.1 |
| TRUMPUSDT | 2025-10-10T21:21 | 90.4 |
| LUNAUSDT | 2022-05-12T14:48 | 93.9 |
| FARTCOINUSDT | 2025-10-10T21:21 | 97.4 |
| TAOUSDT | 2025-10-10T21:21 | 99.6 |
| FORMUSDT | 2025-10-10T21:27 | 108.3 |

Worst and best days (close to close) and the deepest lows against the previous close:

| coin | day | close % |
|---|---|---|
| LUNAUSDT | 2022-05-12 | -99.3 |
| LUNAUSDT | 2022-05-11 | -93.8 |
| BULLAUSDT | 2026-02-01 | -93.0 |
| HUSDT | 2026-06-08 | -89.4 |
| ARIAUSDT | 2026-04-14 | -85.1 |
| OMUSDT | 2025-04-13 | -83.9 |
| VIDTUSDT | 2025-04-12 | -82.3 |
| ESPORTSUSDT | 2026-06-13 | -79.0 |
| HIPPOUSDT | 2025-11-14 | -78.1 |
| ESPORTSUSDT | 2026-06-18 | -76.8 |
| PIPPINUSDT | 2025-11-24 | 131.3 |
| ESPORTSUSDT | 2026-06-11 | 135.3 |
| SIRENUSDT | 2026-03-22 | 145.0 |
| SIRENUSDT | 2026-04-16 | 151.6 |
| ALPACAUSDT | 2025-04-25 | 163.3 |
| ESPORTSUSDT | 2026-06-17 | 169.4 |
| JELLYJELLYUSDT | 2025-11-03 | 234.0 |
| SIRENUSDT | 2026-04-04 | 268.6 |
| UNFIUSDT | 2022-06-07 | 450.0 |
| ALPACAUSDT | 2025-04-30 | 520.2 |

| coin | day | low % |
|---|---|---|
| LUNAUSDT | 2022-05-12 | -99.7 |
| LUNAUSDT | 2022-05-11 | -97.3 |
| BULLAUSDT | 2026-02-01 | -95.0 |
| OMUSDT | 2025-04-13 | -94.1 |
| ARIAUSDT | 2026-04-09 | -91.5 |
| TUTUSDT | 2025-10-10 | -90.2 |
| TSTUSDT | 2025-10-10 | -89.6 |
| HUSDT | 2026-06-08 | -89.5 |
| FTTUSDT | 2022-11-08 | -88.7 |
| IPUSDT | 2025-10-10 | -88.5 |

## Binance minutes against Hyperliquid's

Hyperliquid's public `candleSnapshot` 1-minute closes against Binance's on 2026-10-25, 2026-10-26, 2026-10-27 (the only days its API gives; prices only, no rule's number):

| coin | minutes | median gap bps | p99 gap bps | corr of 1m returns |
|---|---|---|---|---|
| BTC | 1910 | 1.18 | 3.5 | 0.973 |
| ETH | 1910 | 0.97 | 3.7 | 0.972 |
| SOL | 1910 | 1.00 | 5.0 | 0.938 |
| ZEC | 1910 | 4.55 | 11.7 | 0.967 |
| HYPE | 1910 | 11.31 | 16.0 | 0.981 |
| XRP | 1910 | 1.55 | 8.3 | 0.917 |
| WLD | 1910 | 2.75 | 11.2 | 0.932 |
| BNB | 1910 | 9.18 | 15.2 | 0.807 |
| DOGE | 1910 | 1.68 | 10.0 | 0.742 |
| NEAR | 1910 | 3.70 | 13.0 | 0.968 |
| kPEPE | 1910 | 3.75 | 15.6 | 0.852 |
| ADA | 1910 | 3.41 | 14.2 | 0.644 |
| XLM | 1910 | 2.38 | 13.1 | 0.659 |
| SUI | 1910 | 2.20 | 11.1 | 0.856 |
| ENA | 1910 | 4.36 | 15.0 | 0.947 |
| TAO | 1910 | 3.97 | 17.0 | 0.719 |
| AVAX | 1910 | 2.50 | 12.1 | 0.719 |
| FIL | 1910 | 3.35 | 20.8 | 0.670 |
| BCH | 1910 | 2.75 | 18.0 | 0.764 |
| LINK | 1910 | 2.61 | 11.4 | 0.764 |

## Every rule, Hyperliquid taker (the base case)

Out of sample on the Hyperliquid universe unless marked: trades, trades a day, the mean hold, gross and net bps of notional per trade, the 5 % quantile of the day-block bootstrap of the net, the fee a side at which the net is zero, Sharpe in sample (Binance universe) and out of sample, the same rule on the whole Binance universe, one minute late, the DSR.

| rule | trades | a day | hold min | gross bps | net bps | band 5 % | break-even fee | Sharpe IS | Sharpe OOS | Binance univ. | late net bps | DSR | fails |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| S-own:k3:none:cont:H1 | 299054 | 547.7 | 1 | -0.7 | -12.6 | -13.0 | -1.8 | -41.47 | -38.88 | -41.73 | -11.8 | 0.000 | net -12.6 bps; Sharpe -38.88; late -11.8 bps; DSR 0.00; Binance universe -41.73 |
| S-own:k3:none:cont:H5 | 200619 | 367.4 | 5 | -1.0 | -13.0 | -13.4 | -2.0 | -36.54 | -36.39 | -39.03 | -12.2 | 0.000 | net -13.0 bps; Sharpe -36.39; late -12.2 bps; DSR 0.00; Binance universe -39.03 |
| S-own:k3:none:cont:H15 | 128092 | 234.6 | 15 | -1.4 | -13.4 | -14.2 | -2.2 | -31.10 | -29.14 | -34.19 | -12.8 | 0.000 | net -13.4 bps; Sharpe -29.14; late -12.8 bps; DSR 0.00; Binance universe -34.19 |
| S-own:k3:none:cont:H30 | 86575 | 158.6 | 29 | -1.1 | -13.2 | -14.4 | -2.1 | -25.08 | -20.82 | -22.07 | -12.6 | 0.000 | net -13.2 bps; Sharpe -20.82; late -12.6 bps; DSR 0.00; Binance universe -22.07 |
| S-own:k3:none:cont:H60 | 53359 | 97.7 | 58 | -2.0 | -14.1 | -15.5 | -2.6 | -16.30 | -17.07 | -15.07 | -13.0 | 0.000 | net -14.1 bps; Sharpe -17.07; late -13.0 bps; DSR 0.00; Binance universe -15.07 |
| S-own:k3:none:cont:H240 | 16464 | 30.2 | 224 | 1.9 | -10.3 | -14.9 | -0.7 | -7.38 | -4.58 | -3.47 | -11.4 | 0.000 | net -10.3 bps; Sharpe -4.58; late -11.4 bps; DSR 0.00; Binance universe -3.47 |
| S-own:k3:none:cont:bracket | 74433 | 136.3 | 41 | -1.3 | -13.4 | -14.5 | -2.2 | -25.11 | -24.42 | -24.39 | -12.4 | 0.000 | net -13.4 bps; Sharpe -24.42; late -12.4 bps; DSR 0.00; Binance universe -24.39 |
| S-own:k3:none:fade:H1 | 299054 | 547.7 | 1 | 1.1 | -10.8 | -11.0 | -0.9 | -38.25 | -37.39 | -40.64 | -11.7 | 0.000 | net -10.8 bps; Sharpe -37.39; late -11.7 bps; DSR 0.00; Binance universe -40.64 |
| S-own:k3:none:fade:H5 | 205588 | 376.5 | 5 | 1.4 | -10.6 | -10.9 | -0.8 | -33.44 | -32.53 | -35.50 | -11.6 | 0.000 | net -10.6 bps; Sharpe -32.53; late -11.6 bps; DSR 0.00; Binance universe -35.50 |
| S-own:k3:none:fade:H15 | 130940 | 239.8 | 14 | 2.2 | -9.9 | -10.5 | -0.4 | -27.88 | -27.67 | -30.69 | -10.6 | 0.000 | net -9.9 bps; Sharpe -27.67; late -10.6 bps; DSR 0.00; Binance universe -30.69 |
| S-own:k3:none:fade:H30 | 88282 | 161.7 | 29 | 1.7 | -10.3 | -11.3 | -0.7 | -22.69 | -23.61 | -23.87 | -11.0 | 0.000 | net -10.3 bps; Sharpe -23.61; late -11.0 bps; DSR 0.00; Binance universe -23.87 |
| S-own:k3:none:fade:H60 | 54191 | 99.3 | 57 | 2.0 | -10.1 | -11.7 | -0.5 | -14.34 | -15.62 | -14.65 | -8.9 | 0.000 | net -10.1 bps; Sharpe -15.62; late -8.9 bps; DSR 0.00; Binance universe -14.65 |
| S-own:k3:none:fade:H240 | 16632 | 30.5 | 221 | 2.8 | -9.2 | -14.5 | -0.1 | -3.67 | -4.85 | -4.24 | -7.7 | 0.000 | net -9.2 bps; Sharpe -4.85; late -7.7 bps; DSR 0.00; Binance universe -4.24 |
| S-own:k3:none:fade:bracket | 75600 | 138.5 | 41 | 1.5 | -10.5 | -11.4 | -0.7 | -19.84 | -20.72 | -21.55 | -11.9 | 0.000 | net -10.5 bps; Sharpe -20.72; late -11.9 bps; DSR 0.00; Binance universe -21.55 |
| S-own:k3:vol:cont:H1 | 74499 | 136.4 | 1 | -0.5 | -12.2 | -12.9 | -1.6 | -33.57 | -30.34 | -32.77 | -11.2 | 0.000 | net -12.2 bps; Sharpe -30.34; late -11.2 bps; DSR 0.00; Binance universe -32.77 |
| S-own:k3:vol:cont:H5 | 56330 | 103.2 | 5 | -0.6 | -12.2 | -13.4 | -1.6 | -23.11 | -20.05 | -20.92 | -11.3 | 0.000 | net -12.2 bps; Sharpe -20.05; late -11.3 bps; DSR 0.00; Binance universe -20.92 |
| S-own:k3:vol:cont:H15 | 44862 | 82.2 | 14 | -1.6 | -13.2 | -14.5 | -2.1 | -16.73 | -15.53 | -16.03 | -12.1 | 0.000 | net -13.2 bps; Sharpe -15.53; late -12.1 bps; DSR 0.00; Binance universe -16.03 |
| S-own:k3:vol:cont:H30 | 37681 | 69.0 | 29 | -0.3 | -12.0 | -14.1 | -1.5 | -12.91 | -9.35 | -10.04 | -10.9 | 0.000 | net -12.0 bps; Sharpe -9.35; late -10.9 bps; DSR 0.00; Binance universe -10.04 |
| S-own:k3:vol:cont:H60 | 29669 | 54.3 | 58 | -0.4 | -12.1 | -14.5 | -1.5 | -9.63 | -8.31 | -8.69 | -11.5 | 0.000 | net -12.1 bps; Sharpe -8.31; late -11.5 bps; DSR 0.00; Binance universe -8.69 |
| S-own:k3:vol:cont:H240 | 13703 | 25.1 | 221 | 2.3 | -9.4 | -13.9 | -0.2 | -4.80 | -3.90 | -4.35 | -8.9 | 0.000 | net -9.4 bps; Sharpe -3.90; late -8.9 bps; DSR 0.00; Binance universe -4.35 |
| S-own:k3:vol:cont:bracket | 41279 | 75.6 | 36 | -0.4 | -12.1 | -13.8 | -1.6 | -16.97 | -15.27 | -15.22 | -11.0 | 0.000 | net -12.1 bps; Sharpe -15.27; late -11.0 bps; DSR 0.00; Binance universe -15.22 |
| S-own:k3:vol:fade:H1 | 74499 | 136.4 | 1 | 1.8 | -9.8 | -10.3 | -0.4 | -29.96 | -28.85 | -31.51 | -10.7 | 0.000 | net -9.8 bps; Sharpe -28.85; late -10.7 bps; DSR 0.00; Binance universe -31.51 |
| S-own:k3:vol:fade:H5 | 59912 | 109.7 | 5 | 2.1 | -9.5 | -10.4 | -0.3 | -22.40 | -20.91 | -22.25 | -10.8 | 0.000 | net -9.5 bps; Sharpe -20.91; late -10.8 bps; DSR 0.00; Binance universe -22.25 |
| S-own:k3:vol:fade:H15 | 47583 | 87.1 | 14 | 2.9 | -8.7 | -10.2 | 0.1 | -16.48 | -15.99 | -16.65 | -10.0 | 0.000 | net -8.7 bps; Sharpe -15.99; late -10.0 bps; DSR 0.00; Binance universe -16.65 |
| S-own:k3:vol:fade:H30 | 39542 | 72.4 | 28 | 2.2 | -9.5 | -11.1 | -0.2 | -13.43 | -12.85 | -13.26 | -10.4 | 0.000 | net -9.5 bps; Sharpe -12.85; late -10.4 bps; DSR 0.00; Binance universe -13.26 |
| S-own:k3:vol:fade:H60 | 30837 | 56.5 | 56 | 2.4 | -9.3 | -11.7 | -0.1 | -9.67 | -9.97 | -9.40 | -7.6 | 0.000 | net -9.3 bps; Sharpe -9.97; late -7.6 bps; DSR 0.00; Binance universe -9.40 |
| S-own:k3:vol:fade:H240 | 14009 | 25.7 | 216 | 1.8 | -9.9 | -16.5 | -0.4 | -3.54 | -5.77 | -4.60 | -7.4 | 0.000 | net -9.9 bps; Sharpe -5.77; late -7.4 bps; DSR 0.00; Binance universe -4.60 |
| S-own:k3:vol:fade:bracket | 44137 | 80.8 | 37 | 1.0 | -10.6 | -11.8 | -0.8 | -14.88 | -14.56 | -15.36 | -12.0 | 0.000 | net -10.6 bps; Sharpe -14.56; late -12.0 bps; DSR 0.00; Binance universe -15.36 |
| S-own:k3:taker:cont:H1 | 179088 | 328.0 | 1 | -0.5 | -12.6 | -12.9 | -1.8 | -35.08 | -35.88 | -37.83 | -11.8 | 0.000 | net -12.6 bps; Sharpe -35.88; late -11.8 bps; DSR 0.00; Binance universe -37.83 |
| S-own:k3:taker:cont:H5 | 142434 | 260.9 | 5 | -0.9 | -12.9 | -13.4 | -2.0 | -31.64 | -33.45 | -35.32 | -12.2 | 0.000 | net -12.9 bps; Sharpe -33.45; late -12.2 bps; DSR 0.00; Binance universe -35.32 |
| S-own:k3:taker:cont:H15 | 102083 | 187.0 | 15 | -1.3 | -13.4 | -14.0 | -2.2 | -28.86 | -29.92 | -32.25 | -12.7 | 0.000 | net -13.4 bps; Sharpe -29.92; late -12.7 bps; DSR 0.00; Binance universe -32.25 |
| S-own:k3:taker:cont:H30 | 73726 | 135.0 | 29 | -0.8 | -12.9 | -13.9 | -2.0 | -23.51 | -23.35 | -23.89 | -12.3 | 0.000 | net -12.9 bps; Sharpe -23.35; late -12.3 bps; DSR 0.00; Binance universe -23.89 |
| S-own:k3:taker:cont:H60 | 48133 | 88.2 | 59 | -1.2 | -13.3 | -14.6 | -2.2 | -16.92 | -15.96 | -16.90 | -12.9 | 0.000 | net -13.3 bps; Sharpe -15.96; late -12.9 bps; DSR 0.00; Binance universe -16.90 |
| S-own:k3:taker:cont:H240 | 16090 | 29.5 | 221 | -0.1 | -12.3 | -16.1 | -1.7 | -6.70 | -5.16 | -3.97 | -11.7 | 0.000 | net -12.3 bps; Sharpe -5.16; late -11.7 bps; DSR 0.00; Binance universe -3.97 |
| S-own:k3:taker:cont:bracket | 62501 | 114.5 | 43 | -0.6 | -12.7 | -13.7 | -1.8 | -24.60 | -23.17 | -25.09 | -12.3 | 0.000 | net -12.7 bps; Sharpe -23.17; late -12.3 bps; DSR 0.00; Binance universe -25.09 |
| S-own:k3:taker:fade:H1 | 179088 | 328.0 | 1 | 0.9 | -11.2 | -11.4 | -1.1 | -34.42 | -34.82 | -36.42 | -12.0 | 0.000 | net -11.2 bps; Sharpe -34.82; late -12.0 bps; DSR 0.00; Binance universe -36.42 |
| S-own:k3:taker:fade:H5 | 144828 | 265.3 | 5 | 1.1 | -11.0 | -11.3 | -1.0 | -29.34 | -29.61 | -31.64 | -11.6 | 0.000 | net -11.0 bps; Sharpe -29.61; late -11.6 bps; DSR 0.00; Binance universe -31.64 |
| S-own:k3:taker:fade:H15 | 103705 | 189.9 | 15 | 1.3 | -10.7 | -11.3 | -0.9 | -26.21 | -27.07 | -29.20 | -11.4 | 0.000 | net -10.7 bps; Sharpe -27.07; late -11.4 bps; DSR 0.00; Binance universe -29.20 |
| S-own:k3:taker:fade:H30 | 74766 | 136.9 | 29 | 1.3 | -10.8 | -11.5 | -0.9 | -22.17 | -23.02 | -24.58 | -10.9 | 0.000 | net -10.8 bps; Sharpe -23.02; late -10.9 bps; DSR 0.00; Binance universe -24.58 |
| S-own:k3:taker:fade:H60 | 48733 | 89.3 | 58 | 2.3 | -9.9 | -11.3 | -0.4 | -15.78 | -16.83 | -16.29 | -9.6 | 0.000 | net -9.9 bps; Sharpe -16.83; late -9.6 bps; DSR 0.00; Binance universe -16.29 |
| S-own:k3:taker:fade:H240 | 16189 | 29.7 | 220 | 2.8 | -9.3 | -13.8 | -0.2 | -5.66 | -5.98 | -6.92 | -5.3 | 0.000 | net -9.3 bps; Sharpe -5.98; late -5.3 bps; DSR 0.00; Binance universe -6.92 |
| S-own:k3:taker:fade:bracket | 63215 | 115.8 | 43 | 0.7 | -11.4 | -12.2 | -1.2 | -20.77 | -22.00 | -22.08 | -12.1 | 0.000 | net -11.4 bps; Sharpe -22.00; late -12.1 bps; DSR 0.00; Binance universe -22.08 |
| S-own:k4:none:cont:H1 | 114061 | 208.9 | 1 | -0.8 | -12.7 | -13.3 | -1.8 | -36.69 | -31.43 | -34.18 | -11.4 | 0.000 | net -12.7 bps; Sharpe -31.43; late -11.4 bps; DSR 0.00; Binance universe -34.18 |
| S-own:k4:none:cont:H5 | 86445 | 158.3 | 5 | -1.2 | -13.1 | -14.0 | -2.0 | -28.13 | -24.69 | -26.13 | -11.9 | 0.000 | net -13.1 bps; Sharpe -24.69; late -11.9 bps; DSR 0.00; Binance universe -26.13 |
| S-own:k4:none:cont:H15 | 64442 | 118.0 | 15 | -1.4 | -13.3 | -14.5 | -2.2 | -22.25 | -19.83 | -20.47 | -12.1 | 0.000 | net -13.3 bps; Sharpe -19.83; late -12.1 bps; DSR 0.00; Binance universe -20.47 |
| S-own:k4:none:cont:H30 | 50427 | 92.4 | 29 | -1.5 | -13.5 | -15.3 | -2.2 | -16.99 | -13.71 | -15.57 | -12.4 | 0.000 | net -13.5 bps; Sharpe -13.71; late -12.4 bps; DSR 0.00; Binance universe -15.57 |
| S-own:k4:none:cont:H60 | 36669 | 67.2 | 58 | -2.3 | -14.2 | -16.1 | -2.6 | -11.94 | -12.35 | -11.04 | -13.2 | 0.000 | net -14.2 bps; Sharpe -12.35; late -13.2 bps; DSR 0.00; Binance universe -11.04 |
| S-own:k4:none:cont:H240 | 14801 | 27.1 | 220 | 3.3 | -8.7 | -13.3 | 0.2 | -4.76 | -4.25 | -4.10 | -8.3 | 0.000 | net -8.7 bps; Sharpe -4.25; late -8.3 bps; DSR 0.00; Binance universe -4.10 |
| S-own:k4:none:cont:bracket | 52479 | 96.1 | 37 | -2.0 | -13.9 | -15.3 | -2.5 | -21.90 | -19.98 | -19.67 | -12.2 | 0.000 | net -13.9 bps; Sharpe -19.98; late -12.2 bps; DSR 0.00; Binance universe -19.67 |
| S-own:k4:none:fade:H1 | 114061 | 208.9 | 1 | 1.9 | -10.0 | -10.4 | -0.5 | -30.85 | -29.68 | -32.73 | -11.2 | 0.000 | net -10.0 bps; Sharpe -29.68; late -11.2 bps; DSR 0.00; Binance universe -32.73 |
| S-own:k4:none:fade:H5 | 89908 | 164.7 | 5 | 2.2 | -9.7 | -10.3 | -0.3 | -24.82 | -22.86 | -25.25 | -11.2 | 0.000 | net -9.7 bps; Sharpe -22.86; late -11.2 bps; DSR 0.00; Binance universe -25.25 |
| S-own:k4:none:fade:H15 | 67142 | 123.0 | 14 | 2.5 | -9.4 | -10.4 | -0.2 | -19.15 | -20.09 | -22.44 | -10.4 | 0.000 | net -9.4 bps; Sharpe -20.09; late -10.4 bps; DSR 0.00; Binance universe -22.44 |
| S-own:k4:none:fade:H30 | 52170 | 95.5 | 28 | 2.9 | -9.0 | -10.4 | 0.0 | -15.73 | -15.74 | -17.55 | -10.7 | 0.000 | net -9.0 bps; Sharpe -15.74; late -10.7 bps; DSR 0.00; Binance universe -17.55 |
| S-own:k4:none:fade:H60 | 37708 | 69.1 | 57 | 3.1 | -8.9 | -10.8 | 0.1 | -11.29 | -11.45 | -12.01 | -8.5 | 0.000 | net -8.9 bps; Sharpe -11.45; late -8.5 bps; DSR 0.00; Binance universe -12.01 |
| S-own:k4:none:fade:H240 | 15040 | 27.5 | 216 | 3.6 | -8.3 | -15.6 | 0.3 | -3.47 | -5.28 | -4.27 | -7.7 | 0.000 | net -8.3 bps; Sharpe -5.28; late -7.7 bps; DSR 0.00; Binance universe -4.27 |
| S-own:k4:none:fade:bracket | 54228 | 99.3 | 37 | 1.3 | -10.6 | -11.8 | -0.8 | -16.28 | -16.24 | -17.52 | -11.6 | 0.000 | net -10.6 bps; Sharpe -16.24; late -11.6 bps; DSR 0.00; Binance universe -17.52 |
| S-own:k4:vol:cont:H1 | 49954 | 91.5 | 1 | -0.6 | -12.3 | -13.2 | -1.6 | -30.10 | -25.26 | -27.91 | -10.9 | 0.000 | net -12.3 bps; Sharpe -25.26; late -10.9 bps; DSR 0.00; Binance universe -27.91 |
| S-own:k4:vol:cont:H5 | 39278 | 71.9 | 5 | -0.7 | -12.4 | -14.1 | -1.7 | -19.20 | -15.88 | -16.71 | -11.0 | 0.000 | net -12.4 bps; Sharpe -15.88; late -11.0 bps; DSR 0.00; Binance universe -16.71 |
| S-own:k4:vol:cont:H15 | 32082 | 58.8 | 14 | -1.9 | -13.6 | -15.2 | -2.3 | -13.55 | -12.72 | -12.87 | -12.0 | 0.000 | net -13.6 bps; Sharpe -12.72; late -12.0 bps; DSR 0.00; Binance universe -12.87 |
| S-own:k4:vol:cont:H30 | 27729 | 50.8 | 29 | -0.3 | -12.0 | -14.8 | -1.5 | -10.99 | -7.22 | -7.75 | -10.3 | 0.000 | net -12.0 bps; Sharpe -7.22; late -10.3 bps; DSR 0.00; Binance universe -7.75 |
| S-own:k4:vol:cont:H60 | 22914 | 42.0 | 58 | -0.2 | -11.9 | -14.7 | -1.4 | -8.14 | -6.67 | -7.01 | -11.1 | 0.000 | net -11.9 bps; Sharpe -6.67; late -11.1 bps; DSR 0.00; Binance universe -7.01 |
| S-own:k4:vol:cont:H240 | 12165 | 22.3 | 220 | -1.0 | -12.8 | -18.1 | -1.9 | -4.49 | -3.42 | -3.21 | -12.9 | 0.000 | net -12.8 bps; Sharpe -3.42; late -12.9 bps; DSR 0.00; Binance universe -3.21 |
| S-own:k4:vol:cont:bracket | 32151 | 58.9 | 34 | -0.2 | -11.9 | -13.7 | -1.4 | -15.24 | -13.33 | -13.76 | -10.6 | 0.000 | net -11.9 bps; Sharpe -13.33; late -10.6 bps; DSR 0.00; Binance universe -13.76 |
| S-own:k4:vol:fade:H1 | 49954 | 91.5 | 1 | 2.4 | -9.2 | -9.9 | -0.1 | -25.98 | -23.21 | -25.76 | -10.5 | 0.000 | net -9.2 bps; Sharpe -23.21; late -10.5 bps; DSR 0.00; Binance universe -25.76 |
| S-own:k4:vol:fade:H5 | 42022 | 77.0 | 4 | 2.8 | -8.8 | -10.0 | 0.1 | -19.17 | -16.65 | -17.81 | -10.3 | 0.000 | net -8.8 bps; Sharpe -16.65; late -10.3 bps; DSR 0.00; Binance universe -17.81 |
| S-own:k4:vol:fade:H15 | 34496 | 63.2 | 14 | 4.1 | -7.6 | -9.4 | 0.7 | -13.66 | -13.13 | -13.91 | -9.4 | 0.000 | net -7.6 bps; Sharpe -13.13; late -9.4 bps; DSR 0.00; Binance universe -13.91 |
| S-own:k4:vol:fade:H30 | 29436 | 53.9 | 28 | 3.0 | -8.7 | -11.6 | 0.1 | -11.16 | -10.78 | -11.22 | -10.5 | 0.000 | net -8.7 bps; Sharpe -10.78; late -10.5 bps; DSR 0.00; Binance universe -11.22 |
| S-own:k4:vol:fade:H60 | 24077 | 44.1 | 56 | 1.8 | -9.9 | -13.0 | -0.5 | -8.77 | -9.09 | -8.71 | -7.3 | 0.000 | net -9.9 bps; Sharpe -9.09; late -7.3 bps; DSR 0.00; Binance universe -8.71 |
| S-own:k4:vol:fade:H240 | 12491 | 22.9 | 215 | 3.6 | -8.2 | -14.7 | 0.4 | -3.25 | -4.48 | -4.24 | -4.4 | 0.000 | net -8.2 bps; Sharpe -4.48; late -4.4 bps; DSR 0.00; Binance universe -4.24 |
| S-own:k4:vol:fade:bracket | 34411 | 63.0 | 34 | 0.8 | -10.9 | -12.6 | -0.9 | -13.24 | -12.65 | -13.73 | -12.4 | 0.000 | net -10.9 bps; Sharpe -12.65; late -12.4 bps; DSR 0.00; Binance universe -13.73 |
| S-own:k4:taker:cont:H1 | 61376 | 112.4 | 1 | -0.5 | -12.4 | -13.2 | -1.7 | -29.89 | -28.30 | -30.13 | -11.6 | 0.000 | net -12.4 bps; Sharpe -28.30; late -11.6 bps; DSR 0.00; Binance universe -30.13 |
| S-own:k4:taker:cont:H5 | 53771 | 98.5 | 5 | -1.3 | -13.2 | -14.0 | -2.1 | -24.44 | -24.16 | -24.99 | -11.9 | 0.000 | net -13.2 bps; Sharpe -24.16; late -11.9 bps; DSR 0.00; Binance universe -24.99 |
| S-own:k4:taker:cont:H15 | 44609 | 81.7 | 15 | -1.3 | -13.2 | -14.2 | -2.1 | -19.83 | -19.66 | -21.04 | -12.2 | 0.000 | net -13.2 bps; Sharpe -19.66; late -12.2 bps; DSR 0.00; Binance universe -21.04 |
| S-own:k4:taker:cont:H30 | 37215 | 68.2 | 29 | -1.1 | -13.0 | -14.6 | -2.0 | -15.45 | -15.03 | -16.08 | -12.2 | 0.000 | net -13.0 bps; Sharpe -15.03; late -12.2 bps; DSR 0.00; Binance universe -16.08 |
| S-own:k4:taker:cont:H60 | 28837 | 52.8 | 58 | -0.9 | -12.9 | -14.6 | -1.9 | -11.51 | -12.30 | -12.89 | -12.6 | 0.000 | net -12.9 bps; Sharpe -12.30; late -12.6 bps; DSR 0.00; Binance universe -12.89 |
| S-own:k4:taker:cont:H240 | 13355 | 24.5 | 220 | -1.1 | -13.1 | -17.4 | -2.1 | -5.91 | -5.53 | -4.65 | -12.8 | 0.000 | net -13.1 bps; Sharpe -5.53; late -12.8 bps; DSR 0.00; Binance universe -4.65 |
| S-own:k4:taker:cont:bracket | 37317 | 68.3 | 40 | -0.6 | -12.5 | -14.0 | -1.8 | -18.78 | -17.29 | -18.68 | -12.0 | 0.000 | net -12.5 bps; Sharpe -17.29; late -12.0 bps; DSR 0.00; Binance universe -18.68 |
| S-own:k4:taker:fade:H1 | 61376 | 112.4 | 1 | 1.5 | -10.5 | -10.8 | -0.7 | -27.70 | -27.17 | -28.71 | -11.6 | 0.000 | net -10.5 bps; Sharpe -27.17; late -11.6 bps; DSR 0.00; Binance universe -28.71 |
| S-own:k4:taker:fade:H5 | 55126 | 101.0 | 5 | 1.7 | -10.2 | -10.8 | -0.6 | -21.63 | -21.01 | -22.66 | -11.1 | 0.000 | net -10.2 bps; Sharpe -21.01; late -11.1 bps; DSR 0.00; Binance universe -22.66 |
| S-own:k4:taker:fade:H15 | 45845 | 84.0 | 14 | 1.2 | -10.7 | -11.5 | -0.8 | -17.22 | -18.64 | -20.36 | -11.2 | 0.000 | net -10.7 bps; Sharpe -18.64; late -11.2 bps; DSR 0.00; Binance universe -20.36 |
| S-own:k4:taker:fade:H30 | 38111 | 69.8 | 29 | 1.5 | -10.4 | -11.6 | -0.7 | -14.23 | -15.46 | -16.82 | -10.1 | 0.000 | net -10.4 bps; Sharpe -15.46; late -10.1 bps; DSR 0.00; Binance universe -16.82 |
| S-own:k4:taker:fade:H60 | 29456 | 53.9 | 57 | 2.2 | -9.8 | -11.8 | -0.4 | -11.41 | -12.13 | -13.06 | -8.7 | 0.000 | net -9.8 bps; Sharpe -12.13; late -8.7 bps; DSR 0.00; Binance universe -13.06 |
| S-own:k4:taker:fade:H240 | 13479 | 24.7 | 218 | 4.9 | -6.9 | -12.0 | 1.0 | -4.40 | -4.78 | -5.74 | -7.3 | 0.000 | net -6.9 bps; Sharpe -4.78; late -7.3 bps; DSR 0.00; Binance universe -5.74 |
| S-own:k4:taker:fade:bracket | 38291 | 70.1 | 40 | 0.8 | -11.1 | -12.3 | -1.1 | -15.42 | -15.59 | -16.60 | -12.0 | 0.000 | net -11.1 bps; Sharpe -15.59; late -12.0 bps; DSR 0.00; Binance universe -16.60 |
| S-own:k6:none:cont:H1 | 28703 | 52.6 | 1 | 0.0 | -11.8 | -14.0 | -1.4 | -24.26 | -16.93 | -20.04 | -10.2 | 0.000 | net -11.8 bps; Sharpe -16.93; late -10.2 bps; DSR 0.00; Binance universe -20.04 |
| S-own:k6:none:cont:H5 | 23987 | 43.9 | 5 | -1.4 | -13.3 | -15.4 | -2.1 | -14.79 | -12.20 | -13.29 | -11.1 | 0.000 | net -13.3 bps; Sharpe -12.20; late -11.1 bps; DSR 0.00; Binance universe -13.29 |
| S-own:k6:none:cont:H15 | 19959 | 36.6 | 14 | -2.8 | -14.6 | -16.9 | -2.8 | -10.85 | -9.77 | -10.29 | -11.8 | 0.000 | net -14.6 bps; Sharpe -9.77; late -11.8 bps; DSR 0.00; Binance universe -10.29 |
| S-own:k6:none:cont:H30 | 17601 | 32.2 | 29 | 0.5 | -11.3 | -15.7 | -1.2 | -9.07 | -4.85 | -5.34 | -8.9 | 0.000 | net -11.3 bps; Sharpe -4.85; late -8.9 bps; DSR 0.00; Binance universe -5.34 |
| S-own:k6:none:cont:H60 | 15079 | 27.6 | 58 | -0.2 | -12.1 | -15.7 | -1.5 | -6.63 | -4.56 | -4.58 | -10.2 | 0.000 | net -12.1 bps; Sharpe -4.56; late -10.2 bps; DSR 0.00; Binance universe -4.58 |
| S-own:k6:none:cont:H240 | 9453 | 17.3 | 219 | 0.8 | -11.1 | -17.5 | -1.0 | -3.70 | -2.09 | -2.00 | -10.1 | 0.000 | net -11.1 bps; Sharpe -2.09; late -10.1 bps; DSR 0.00; Binance universe -2.00 |
| S-own:k6:none:cont:bracket | 21732 | 39.8 | 29 | -0.8 | -12.6 | -15.2 | -1.8 | -13.95 | -11.51 | -11.70 | -10.1 | 0.000 | net -12.6 bps; Sharpe -11.51; late -10.1 bps; DSR 0.00; Binance universe -11.70 |
| S-own:k6:none:fade:H1 | 28703 | 52.6 | 1 | 3.8 | -8.0 | -8.8 | 0.5 | -18.61 | -16.14 | -18.61 | -10.0 | 0.000 | net -8.0 bps; Sharpe -16.14; late -10.0 bps; DSR 0.00; Binance universe -18.61 |
| S-own:k6:none:fade:H5 | 25333 | 46.4 | 4 | 4.8 | -7.0 | -8.7 | 1.0 | -13.36 | -11.00 | -12.61 | -10.2 | 0.000 | net -7.0 bps; Sharpe -11.00; late -10.2 bps; DSR 0.00; Binance universe -12.61 |
| S-own:k6:none:fade:H15 | 21617 | 39.6 | 13 | 5.1 | -6.7 | -9.5 | 1.2 | -9.72 | -9.70 | -11.03 | -10.0 | 0.000 | net -6.7 bps; Sharpe -9.70; late -10.0 bps; DSR 0.00; Binance universe -11.03 |
| S-own:k6:none:fade:H30 | 18928 | 34.7 | 27 | 3.4 | -8.4 | -12.0 | 0.3 | -8.08 | -8.74 | -10.02 | -11.5 | 0.000 | net -8.4 bps; Sharpe -8.74; late -11.5 bps; DSR 0.00; Binance universe -10.02 |
| S-own:k6:none:fade:H60 | 16059 | 29.4 | 54 | 1.0 | -10.8 | -14.6 | -0.9 | -6.50 | -7.87 | -8.71 | -7.6 | 0.000 | net -10.8 bps; Sharpe -7.87; late -7.6 bps; DSR 0.00; Binance universe -8.71 |
| S-own:k6:none:fade:H240 | 9782 | 17.9 | 213 | 5.8 | -6.1 | -14.5 | 1.5 | -2.26 | -3.74 | -4.24 | -4.7 | 0.000 | net -6.1 bps; Sharpe -3.74; late -4.7 bps; DSR 0.00; Binance universe -4.24 |
| S-own:k6:none:fade:bracket | 22505 | 41.2 | 30 | 0.4 | -11.4 | -13.6 | -1.2 | -10.08 | -9.92 | -11.64 | -13.3 | 0.000 | net -11.4 bps; Sharpe -9.92; late -13.3 bps; DSR 0.00; Binance universe -11.64 |
| S-own:k6:vol:cont:H1 | 21644 | 39.6 | 1 | -0.3 | -12.0 | -14.2 | -1.5 | -20.68 | -15.55 | -18.24 | -10.0 | 0.000 | net -12.0 bps; Sharpe -15.55; late -10.0 bps; DSR 0.00; Binance universe -18.24 |
| S-own:k6:vol:cont:H5 | 18130 | 33.2 | 4 | -1.4 | -13.1 | -16.0 | -2.1 | -12.47 | -8.65 | -9.92 | -10.8 | 0.000 | net -13.1 bps; Sharpe -8.65; late -10.8 bps; DSR 0.00; Binance universe -9.92 |
| S-own:k6:vol:cont:H15 | 15357 | 28.1 | 14 | -3.1 | -14.8 | -17.8 | -2.9 | -8.73 | -7.20 | -7.45 | -11.8 | 0.000 | net -14.8 bps; Sharpe -7.20; late -11.8 bps; DSR 0.00; Binance universe -7.45 |
| S-own:k6:vol:cont:H30 | 13811 | 25.3 | 28 | 1.3 | -10.5 | -16.2 | -0.7 | -7.29 | -3.74 | -4.12 | -8.6 | 0.000 | net -10.5 bps; Sharpe -3.74; late -8.6 bps; DSR 0.00; Binance universe -4.12 |
| S-own:k6:vol:cont:H60 | 12230 | 22.4 | 57 | -0.2 | -12.0 | -16.3 | -1.5 | -5.40 | -3.75 | -3.75 | -9.8 | 0.000 | net -12.0 bps; Sharpe -3.75; late -9.8 bps; DSR 0.00; Binance universe -3.75 |
| S-own:k6:vol:cont:H240 | 8392 | 15.4 | 219 | -0.5 | -12.2 | -19.5 | -1.6 | -3.42 | -2.06 | -2.01 | -9.8 | 0.000 | net -12.2 bps; Sharpe -2.06; late -9.8 bps; DSR 0.00; Binance universe -2.01 |
| S-own:k6:vol:cont:bracket | 17310 | 31.7 | 27 | -0.8 | -12.5 | -15.3 | -1.8 | -11.66 | -9.91 | -10.06 | -10.0 | 0.000 | net -12.5 bps; Sharpe -9.91; late -10.0 bps; DSR 0.00; Binance universe -10.06 |
| S-own:k6:vol:fade:H1 | 21644 | 39.6 | 1 | 4.2 | -7.5 | -8.5 | 0.8 | -16.78 | -13.71 | -15.65 | -9.6 | 0.000 | net -7.5 bps; Sharpe -13.71; late -9.6 bps; DSR 0.00; Binance universe -15.65 |
| S-own:k6:vol:fade:H5 | 19358 | 35.5 | 4 | 5.6 | -6.1 | -8.3 | 1.5 | -12.06 | -9.12 | -10.23 | -9.0 | 0.000 | net -6.1 bps; Sharpe -9.12; late -9.0 bps; DSR 0.00; Binance universe -10.23 |
| S-own:k6:vol:fade:H15 | 16914 | 31.0 | 13 | 6.8 | -4.9 | -8.1 | 2.1 | -8.35 | -7.40 | -8.24 | -8.7 | 0.000 | net -4.9 bps; Sharpe -7.40; late -8.7 bps; DSR 0.00; Binance universe -8.24 |
| S-own:k6:vol:fade:H30 | 15097 | 27.7 | 26 | 5.5 | -6.2 | -11.1 | 1.4 | -6.93 | -6.92 | -7.48 | -10.2 | 0.000 | net -6.2 bps; Sharpe -6.92; late -10.2 bps; DSR 0.00; Binance universe -7.48 |
| S-own:k6:vol:fade:H60 | 13132 | 24.1 | 54 | 3.5 | -8.2 | -13.1 | 0.4 | -5.72 | -6.14 | -6.80 | -5.2 | 0.000 | net -8.2 bps; Sharpe -6.14; late -5.2 bps; DSR 0.00; Binance universe -6.80 |
| S-own:k6:vol:fade:H240 | 8690 | 15.9 | 212 | 5.5 | -6.3 | -14.5 | 1.4 | -2.29 | -3.30 | -3.41 | -2.4 | 0.000 | net -6.3 bps; Sharpe -3.30; late -2.4 bps; DSR 0.00; Binance universe -3.41 |
| S-own:k6:vol:fade:bracket | 18111 | 33.2 | 29 | 1.6 | -10.1 | -12.5 | -0.6 | -8.92 | -8.66 | -10.20 | -13.1 | 0.000 | net -10.1 bps; Sharpe -8.66; late -13.1 bps; DSR 0.00; Binance universe -10.20 |
| S-own:k6:taker:cont:H1 | 12731 | 23.3 | 1 | 1.3 | -10.6 | -13.7 | -0.8 | -16.21 | -13.34 | -14.29 | -10.0 | 0.000 | net -10.6 bps; Sharpe -13.34; late -10.0 bps; DSR 0.00; Binance universe -14.29 |
| S-own:k6:taker:cont:H5 | 11933 | 21.9 | 5 | -0.7 | -12.6 | -15.0 | -1.8 | -11.22 | -10.15 | -12.01 | -10.2 | 0.000 | net -12.6 bps; Sharpe -10.15; late -10.2 bps; DSR 0.00; Binance universe -12.01 |
| S-own:k6:taker:cont:H15 | 10972 | 20.1 | 14 | -2.0 | -13.8 | -16.1 | -2.4 | -8.94 | -8.07 | -9.61 | -12.0 | 0.000 | net -13.8 bps; Sharpe -8.07; late -12.0 bps; DSR 0.00; Binance universe -9.61 |
| S-own:k6:taker:cont:H30 | 10187 | 18.7 | 29 | 2.5 | -9.4 | -14.3 | -0.2 | -6.86 | -4.56 | -5.22 | -7.3 | 0.000 | net -9.4 bps; Sharpe -4.56; late -7.3 bps; DSR 0.00; Binance universe -5.22 |
| S-own:k6:taker:cont:H60 | 9240 | 16.9 | 58 | 1.6 | -10.3 | -14.6 | -0.6 | -5.16 | -3.83 | -4.37 | -10.0 | 0.000 | net -10.3 bps; Sharpe -3.83; late -10.0 bps; DSR 0.00; Binance universe -4.37 |
| S-own:k6:taker:cont:H240 | 6713 | 12.3 | 218 | -5.6 | -17.5 | -24.1 | -4.3 | -3.05 | -2.42 | -2.67 | -15.9 | 0.000 | net -17.5 bps; Sharpe -2.42; late -15.9 bps; DSR 0.00; Binance universe -2.67 |
| S-own:k6:taker:cont:bracket | 11228 | 20.6 | 32 | 1.2 | -10.7 | -14.1 | -0.8 | -9.92 | -8.18 | -9.32 | -10.4 | 0.000 | net -10.7 bps; Sharpe -8.18; late -10.4 bps; DSR 0.00; Binance universe -9.32 |
| S-own:k6:taker:fade:H1 | 12731 | 23.3 | 1 | 2.9 | -8.9 | -9.9 | 0.0 | -14.11 | -14.48 | -15.54 | -11.5 | 0.000 | net -8.9 bps; Sharpe -14.48; late -11.5 bps; DSR 0.00; Binance universe -15.54 |
| S-own:k6:taker:fade:H5 | 12348 | 22.6 | 4 | 3.5 | -8.3 | -10.2 | 0.3 | -11.37 | -10.30 | -10.87 | -9.5 | 0.000 | net -8.3 bps; Sharpe -10.30; late -9.5 bps; DSR 0.00; Binance universe -10.87 |
| S-own:k6:taker:fade:H15 | 11510 | 21.1 | 13 | 2.6 | -9.2 | -11.0 | -0.1 | -7.61 | -9.50 | -9.94 | -9.7 | 0.000 | net -9.2 bps; Sharpe -9.50; late -9.7 bps; DSR 0.00; Binance universe -9.94 |
| S-own:k6:taker:fade:H30 | 10655 | 19.5 | 27 | 1.9 | -10.0 | -12.6 | -0.5 | -6.40 | -8.14 | -8.43 | -7.2 | 0.000 | net -10.0 bps; Sharpe -8.14; late -7.2 bps; DSR 0.00; Binance universe -8.43 |
| S-own:k6:taker:fade:H60 | 9638 | 17.7 | 55 | 4.0 | -7.8 | -12.6 | 0.6 | -5.74 | -6.52 | -6.81 | -3.8 | 0.000 | net -7.8 bps; Sharpe -6.52; late -3.8 bps; DSR 0.00; Binance universe -6.81 |
| S-own:k6:taker:fade:H240 | 6852 | 12.5 | 213 | 12.0 | 0.3 | -9.3 | 4.6 | -2.78 | -3.12 | -3.27 | 2.6 | 0.000 | band 5 % -9.3 bps; Sharpe -3.12; DSR 0.00; Binance universe -3.27 |
| S-own:k6:taker:fade:bracket | 11556 | 21.2 | 33 | -0.4 | -12.3 | -14.6 | -1.6 | -8.26 | -9.28 | -9.46 | -14.4 | 0.000 | net -12.3 bps; Sharpe -9.28; late -14.4 bps; DSR 0.00; Binance universe -9.46 |
| S-lead:k3:H1 | 45446 | 83.2 | 1 | 0.9 | -11.7 | -12.2 | -1.3 | -20.76 | -20.45 | -21.73 | -12.6 | 0.000 | net -11.7 bps; Sharpe -20.45; late -12.6 bps; DSR 0.00; Binance universe -21.73 |
| S-lead:k3:H5 | 35697 | 65.4 | 5 | 1.1 | -11.6 | -13.1 | -1.3 | -15.75 | -18.30 | -18.33 | -13.3 | 0.000 | net -11.6 bps; Sharpe -18.30; late -13.3 bps; DSR 0.00; Binance universe -18.33 |
| S-lead:k3:H15 | 27036 | 49.5 | 15 | 2.2 | -10.4 | -12.8 | -0.7 | -11.11 | -11.68 | -11.38 | -11.6 | 0.000 | net -10.4 bps; Sharpe -11.68; late -11.6 bps; DSR 0.00; Binance universe -11.38 |
| S-lead:k3:H30 | 21651 | 39.7 | 30 | 1.9 | -10.8 | -13.5 | -0.9 | -7.82 | -8.73 | -9.00 | -11.9 | 0.000 | net -10.8 bps; Sharpe -8.73; late -11.9 bps; DSR 0.00; Binance universe -9.00 |
| S-lead:k3:H60 | 16421 | 30.1 | 59 | -2.0 | -14.7 | -17.8 | -2.8 | -5.81 | -7.04 | -7.08 | -15.4 | 0.000 | net -14.7 bps; Sharpe -7.04; late -15.4 bps; DSR 0.00; Binance universe -7.08 |
| S-lead:k3:H240 | 8538 | 15.6 | 221 | -3.1 | -15.9 | -23.1 | -3.5 | -1.84 | -3.05 | -2.36 | -16.7 | 0.000 | net -15.9 bps; Sharpe -3.05; late -16.7 bps; DSR 0.00; Binance universe -2.36 |
| S-lead:k4:H1 | 14441 | 26.4 | 1 | 2.2 | -10.7 | -12.0 | -0.8 | -13.93 | -13.85 | -15.23 | -11.9 | 0.000 | net -10.7 bps; Sharpe -13.85; late -11.9 bps; DSR 0.00; Binance universe -15.23 |
| S-lead:k4:H5 | 12163 | 22.3 | 5 | 5.2 | -7.7 | -11.7 | 0.7 | -10.57 | -9.28 | -8.69 | -11.5 | 0.000 | net -7.7 bps; Sharpe -9.28; late -11.5 bps; DSR 0.00; Binance universe -8.69 |
| S-lead:k4:H15 | 10222 | 18.7 | 15 | 5.1 | -7.8 | -13.0 | 0.6 | -6.17 | -5.20 | -4.93 | -9.7 | 0.000 | net -7.8 bps; Sharpe -5.20; late -9.7 bps; DSR 0.00; Binance universe -4.93 |
| S-lead:k4:H30 | 8854 | 16.2 | 29 | 2.5 | -10.4 | -16.1 | -0.7 | -4.41 | -4.23 | -3.28 | -11.9 | 0.000 | net -10.4 bps; Sharpe -4.23; late -11.9 bps; DSR 0.00; Binance universe -3.28 |
| S-lead:k4:H60 | 7505 | 13.7 | 58 | -0.8 | -13.7 | -18.4 | -2.4 | -3.38 | -3.84 | -3.62 | -15.4 | 0.000 | net -13.7 bps; Sharpe -3.84; late -15.4 bps; DSR 0.00; Binance universe -3.62 |
| S-lead:k4:H240 | 5032 | 9.2 | 218 | -1.2 | -14.3 | -25.6 | -2.6 | -1.29 | -1.60 | -0.66 | -18.2 | 0.000 | net -14.3 bps; Sharpe -1.60; late -18.2 bps; DSR 0.00; Binance universe -0.66 |
| S-lead:k6:H1 | 2329 | 4.3 | 1 | 4.3 | -8.6 | -12.4 | 0.2 | -6.56 | -6.04 | -7.00 | -12.2 | 0.000 | net -8.6 bps; Sharpe -6.04; late -12.2 bps; DSR 0.00; Binance universe -7.00 |
| S-lead:k6:H5 | 2066 | 3.8 | 5 | 13.2 | 0.3 | -11.8 | 4.7 | -5.62 | -2.25 | -1.96 | -3.9 | 0.000 | band 5 % -11.8 bps; Sharpe -2.25; late -3.9 bps; DSR 0.00; Binance universe -1.96 |
| S-lead:k6:H15 | 1883 | 3.4 | 15 | 13.3 | 0.4 | -14.1 | 4.7 | -3.09 | -1.71 | -1.80 | 3.6 | 0.000 | band 5 % -14.1 bps; Sharpe -1.71; DSR 0.00; Binance universe -1.80 |
| S-lead:k6:H30 | 1766 | 3.2 | 29 | 11.9 | -1.0 | -19.8 | 4.0 | -2.09 | -1.39 | -0.91 | 0.7 | 0.000 | net -1.0 bps; Sharpe -1.39; DSR 0.00; Binance universe -0.91 |
| S-lead:k6:H60 | 1636 | 3.0 | 58 | 9.6 | -3.3 | -15.3 | 2.8 | -1.97 | -0.37 | -0.89 | -1.6 | 0.000 | net -3.3 bps; Sharpe -0.37; late -1.6 bps; DSR 0.00; Binance universe -0.89 |
| S-lead:k6:H240 | 1390 | 2.5 | 211 | 4.9 | -8.1 | -33.5 | 0.4 | -1.04 | 0.68 | 0.29 | -9.7 | 0.001 | net -8.1 bps; late -9.7 bps; DSR 0.00 |
| D-orb:utc30:A | 2802 | 5.1 | 1126 | -7.3 | -18.4 | -39.9 | -4.7 | -2.93 | -0.94 | -0.16 | -15.4 | 0.000 | net -18.4 bps; Sharpe -0.94; late -15.4 bps; DSR 0.00; Binance universe -0.16 |
| D-orb:utc30:B | 2829 | 5.2 | 1028 | -0.5 | -12.0 | -32.3 | -1.5 | -2.36 | -0.76 | -0.33 | -11.3 | 0.000 | net -12.0 bps; Sharpe -0.76; late -11.3 bps; DSR 0.00; Binance universe -0.33 |
| D-orb:utc60:A | 2888 | 5.3 | 1079 | -23.8 | -35.9 | -54.8 | -13.5 | -2.70 | -2.07 | -2.25 | -36.6 | 0.000 | net -35.9 bps; Sharpe -2.07; late -36.6 bps; DSR 0.00; Binance universe -2.25 |
| D-orb:utc60:B | 2967 | 5.4 | 957 | -24.5 | -37.0 | -51.2 | -14.0 | -2.48 | -2.98 | -2.99 | -37.8 | 0.000 | net -37.0 bps; Sharpe -2.98; late -37.8 bps; DSR 0.00; Binance universe -2.99 |
| D-orb:us30:A | 2821 | 5.2 | 519 | 10.2 | -1.8 | -21.1 | 3.6 | -0.85 | -0.02 | 0.20 | 0.2 | 0.000 | net -1.8 bps; Sharpe -0.02; DSR 0.00 |
| D-orb:us30:B | 3030 | 5.5 | 429 | 3.3 | -8.6 | -23.9 | 0.2 | -1.50 | -1.06 | -1.32 | -7.0 | 0.000 | net -8.6 bps; Sharpe -1.06; late -7.0 bps; DSR 0.00; Binance universe -1.32 |
| D-orb:us60:A | 2877 | 5.3 | 492 | 9.0 | -2.9 | -19.9 | 3.0 | -1.24 | -0.02 | 0.16 | -2.2 | 0.000 | net -2.9 bps; Sharpe -0.02; late -2.2 bps; DSR 0.00 |
| D-orb:us60:B | 3202 | 5.9 | 397 | -1.1 | -13.0 | -24.2 | -2.0 | -1.60 | -1.36 | -1.08 | -11.5 | 0.000 | net -13.0 bps; Sharpe -1.36; late -11.5 bps; DSR 0.00; Binance universe -1.08 |
| D-prev:A | 3840 | 7.0 | 922 | -9.0 | -22.0 | -40.1 | -6.5 | -1.89 | -1.39 | -1.14 | -22.2 | 0.000 | net -22.0 bps; Sharpe -1.39; late -22.2 bps; DSR 0.00; Binance universe -1.14 |
| D-prev:B | 4709 | 8.6 | 686 | -11.3 | -24.3 | -36.5 | -7.6 | -2.10 | -2.13 | -2.07 | -22.7 | 0.000 | net -24.3 bps; Sharpe -2.13; late -22.7 bps; DSR 0.00; Binance universe -2.07 |
| D-vwap:m0.25 | 7143 | 13.1 | 366 | 0.7 | -11.4 | -19.8 | -1.2 | -1.84 | -2.58 | -2.46 | -13.6 | 0.000 | net -11.4 bps; Sharpe -2.58; late -13.6 bps; DSR 0.00; Binance universe -2.46 |
| D-vwap:m0.5 | 4427 | 8.1 | 353 | 3.3 | -9.2 | -20.7 | -0.1 | -1.62 | -1.41 | -2.18 | -12.9 | 0.000 | net -9.2 bps; Sharpe -1.41; late -12.9 bps; DSR 0.00; Binance universe -2.18 |
| P-gbm:H15:m0 | 22335 | 40.9 | 15 | 3.9 | -7.6 | -10.4 | 0.7 | -8.67 | -5.74 | -7.33 | -10.5 | 0.000 | net -7.6 bps; Sharpe -5.74; late -10.5 bps; DSR 0.00; Binance universe -7.33 |
| P-gbm:H15:m5 | 10920 | 20.0 | 15 | 6.7 | -4.9 | -9.6 | 2.1 | -5.70 | -3.01 | -4.14 | -9.2 | 0.000 | net -4.9 bps; Sharpe -3.01; late -9.2 bps; DSR 0.00; Binance universe -4.14 |
| P-gbm:H15:m10 | 6117 | 11.2 | 15 | 13.3 | 1.6 | -6.0 | 5.3 | -3.94 | -0.80 | -2.54 | -5.2 | 0.000 | band 5 % -6.0 bps; Sharpe -0.80; late -5.2 bps; DSR 0.00; Binance universe -2.54 |
| P-gbm:H15:m20 | 2376 | 4.4 | 14 | 25.1 | 13.3 | -4.0 | 11.1 | -1.41 | 1.16 | -0.09 | -0.6 | 0.007 | band 5 % -4.0 bps; late -0.6 bps; DSR 0.01; Binance universe -0.09 |
| P-gbm:H60:m0 | 36793 | 67.4 | 58 | 3.5 | -8.2 | -10.9 | 0.4 | -6.41 | -4.83 | -4.56 | -8.3 | 0.000 | net -8.2 bps; Sharpe -4.83; late -8.3 bps; DSR 0.00; Binance universe -4.56 |
| P-gbm:H60:m5 | 24985 | 45.8 | 58 | 5.1 | -6.7 | -10.3 | 1.2 | -4.81 | -3.56 | -3.64 | -6.8 | 0.000 | net -6.7 bps; Sharpe -3.56; late -6.8 bps; DSR 0.00; Binance universe -3.64 |
| P-gbm:H60:m10 | 17417 | 31.9 | 58 | 5.2 | -6.7 | -11.1 | 1.1 | -3.84 | -2.99 | -3.42 | -6.8 | 0.000 | net -6.7 bps; Sharpe -2.99; late -6.8 bps; DSR 0.00; Binance universe -3.42 |
| P-gbm:H60:m20 | 8877 | 16.3 | 58 | 8.5 | -3.6 | -11.0 | 2.7 | -2.81 | -2.34 | -3.30 | -3.6 | 0.000 | net -3.6 bps; Sharpe -2.34; late -3.6 bps; DSR 0.00; Binance universe -3.30 |

## Maker case (1.5 bps, trade-through fills; missed entries stay missed)

| rule | trades | net bps | band 5 % | break-even fee | Sharpe OOS | Binance univ. | DSR | fails |
|---|---|---|---|---|---|---|---|---|
| S-own:k3:none:cont:H1 | 257216 | -11.2 | -11.5 | -3.6 | -39.94 | -43.59 | 0.000 | net -11.2 bps; Sharpe -39.94; DSR 0.00; Binance universe -43.59 |
| S-own:k3:none:cont:H5 | 183239 | -11.8 | -12.3 | -3.9 | -37.88 | -39.07 | 0.000 | net -11.8 bps; Sharpe -37.88; DSR 0.00; Binance universe -39.07 |
| S-own:k3:none:cont:H15 | 120463 | -12.1 | -12.9 | -4.0 | -26.35 | -29.83 | 0.000 | net -12.1 bps; Sharpe -26.35; DSR 0.00; Binance universe -29.83 |
| S-own:k3:none:cont:H30 | 82997 | -12.2 | -13.4 | -4.1 | -18.63 | -19.66 | 0.000 | net -12.2 bps; Sharpe -18.63; DSR 0.00; Binance universe -19.66 |
| S-own:k3:none:cont:H60 | 51952 | -12.2 | -13.7 | -4.1 | -14.94 | -15.08 | 0.000 | net -12.2 bps; Sharpe -14.94; DSR 0.00; Binance universe -15.08 |
| S-own:k3:none:cont:H240 | 16431 | -11.1 | -15.4 | -3.4 | -5.85 | -4.91 | 0.000 | net -11.1 bps; Sharpe -5.85; DSR 0.00; Binance universe -4.91 |
| S-own:k3:none:cont:bracket | 72683 | -11.3 | -12.5 | -3.3 | -21.01 | -20.13 | 0.000 | net -11.3 bps; Sharpe -21.01; DSR 0.00; Binance universe -20.13 |
| S-own:k3:none:fade:H1 | 247358 | -9.1 | -9.3 | -2.5 | -39.23 | -45.46 | 0.000 | net -9.1 bps; Sharpe -39.23; DSR 0.00; Binance universe -45.46 |
| S-own:k3:none:fade:H5 | 181054 | -9.5 | -9.9 | -2.7 | -35.74 | -40.34 | 0.000 | net -9.5 bps; Sharpe -35.74; DSR 0.00; Binance universe -40.34 |
| S-own:k3:none:fade:H15 | 119449 | -8.7 | -9.3 | -2.3 | -29.48 | -32.45 | 0.000 | net -8.7 bps; Sharpe -29.48; DSR 0.00; Binance universe -32.45 |
| S-own:k3:none:fade:H30 | 82504 | -9.7 | -10.8 | -2.8 | -24.39 | -24.32 | 0.000 | net -9.7 bps; Sharpe -24.39; DSR 0.00; Binance universe -24.32 |
| S-own:k3:none:fade:H60 | 51944 | -8.0 | -10.0 | -1.9 | -15.15 | -14.61 | 0.000 | net -8.0 bps; Sharpe -15.15; DSR 0.00; Binance universe -14.61 |
| S-own:k3:none:fade:H240 | 16536 | -8.0 | -12.5 | -1.9 | -5.13 | -4.76 | 0.000 | net -8.0 bps; Sharpe -5.13; DSR 0.00; Binance universe -4.76 |
| S-own:k3:none:fade:bracket | 73229 | -8.9 | -9.9 | -2.0 | -20.51 | -20.85 | 0.000 | net -8.9 bps; Sharpe -20.51; DSR 0.00; Binance universe -20.85 |
| S-own:k3:vol:cont:H1 | 68878 | -11.0 | -11.9 | -3.4 | -28.33 | -30.21 | 0.000 | net -11.0 bps; Sharpe -28.33; DSR 0.00; Binance universe -30.21 |
| S-own:k3:vol:cont:H5 | 53964 | -11.6 | -12.7 | -3.8 | -20.91 | -20.84 | 0.000 | net -11.6 bps; Sharpe -20.91; DSR 0.00; Binance universe -20.84 |
| S-own:k3:vol:cont:H15 | 43355 | -12.2 | -13.5 | -4.1 | -16.86 | -16.97 | 0.000 | net -12.2 bps; Sharpe -16.86; DSR 0.00; Binance universe -16.97 |
| S-own:k3:vol:cont:H30 | 36576 | -10.8 | -12.9 | -3.4 | -9.86 | -10.45 | 0.000 | net -10.8 bps; Sharpe -9.86; DSR 0.00; Binance universe -10.45 |
| S-own:k3:vol:cont:H60 | 28916 | -10.7 | -13.0 | -3.3 | -8.88 | -9.61 | 0.000 | net -10.7 bps; Sharpe -8.88; DSR 0.00; Binance universe -9.61 |
| S-own:k3:vol:cont:H240 | 13545 | -9.8 | -14.3 | -2.8 | -4.92 | -5.17 | 0.000 | net -9.8 bps; Sharpe -4.92; DSR 0.00; Binance universe -5.17 |
| S-own:k3:vol:cont:bracket | 40283 | -9.9 | -11.6 | -2.5 | -14.51 | -13.85 | 0.000 | net -9.9 bps; Sharpe -14.51; DSR 0.00; Binance universe -13.85 |
| S-own:k3:vol:fade:H1 | 65994 | -9.0 | -9.4 | -2.4 | -29.90 | -33.57 | 0.000 | net -9.0 bps; Sharpe -29.90; DSR 0.00; Binance universe -33.57 |
| S-own:k3:vol:fade:H5 | 54677 | -9.3 | -10.2 | -2.5 | -23.82 | -25.88 | 0.000 | net -9.3 bps; Sharpe -23.82; DSR 0.00; Binance universe -25.88 |
| S-own:k3:vol:fade:H15 | 43847 | -8.6 | -10.0 | -2.2 | -18.00 | -19.18 | 0.000 | net -8.6 bps; Sharpe -18.00; DSR 0.00; Binance universe -19.18 |
| S-own:k3:vol:fade:H30 | 36674 | -10.1 | -11.9 | -2.9 | -14.11 | -14.96 | 0.000 | net -10.1 bps; Sharpe -14.11; DSR 0.00; Binance universe -14.96 |
| S-own:k3:vol:fade:H60 | 28984 | -9.6 | -12.8 | -2.7 | -11.91 | -11.12 | 0.000 | net -9.6 bps; Sharpe -11.91; DSR 0.00; Binance universe -11.12 |
| S-own:k3:vol:fade:H240 | 13602 | -11.3 | -18.3 | -3.5 | -6.69 | -5.65 | 0.000 | net -11.3 bps; Sharpe -6.69; DSR 0.00; Binance universe -5.65 |
| S-own:k3:vol:fade:bracket | 41692 | -9.8 | -11.0 | -2.4 | -15.78 | -17.07 | 0.000 | net -9.8 bps; Sharpe -15.78; DSR 0.00; Binance universe -17.07 |
| S-own:k3:taker:cont:H1 | 159382 | -11.2 | -11.5 | -3.6 | -39.18 | -41.01 | 0.000 | net -11.2 bps; Sharpe -39.18; DSR 0.00; Binance universe -41.01 |
| S-own:k3:taker:cont:H5 | 130461 | -11.8 | -12.2 | -3.8 | -36.23 | -36.18 | 0.000 | net -11.8 bps; Sharpe -36.23; DSR 0.00; Binance universe -36.18 |
| S-own:k3:taker:cont:H15 | 95638 | -12.1 | -12.8 | -4.0 | -30.71 | -30.74 | 0.000 | net -12.1 bps; Sharpe -30.71; DSR 0.00; Binance universe -30.74 |
| S-own:k3:taker:cont:H30 | 70239 | -11.4 | -12.6 | -3.6 | -22.32 | -21.59 | 0.000 | net -11.4 bps; Sharpe -22.32; DSR 0.00; Binance universe -21.59 |
| S-own:k3:taker:cont:H60 | 46559 | -12.2 | -13.5 | -4.0 | -15.82 | -16.17 | 0.000 | net -12.2 bps; Sharpe -15.82; DSR 0.00; Binance universe -16.17 |
| S-own:k3:taker:cont:H240 | 15985 | -9.3 | -13.2 | -2.5 | -5.82 | -4.55 | 0.000 | net -9.3 bps; Sharpe -5.82; DSR 0.00; Binance universe -4.55 |
| S-own:k3:taker:cont:bracket | 60789 | -10.3 | -11.3 | -2.7 | -19.18 | -19.54 | 0.000 | net -10.3 bps; Sharpe -19.18; DSR 0.00; Binance universe -19.54 |
| S-own:k3:taker:fade:H1 | 151652 | -9.2 | -9.4 | -2.5 | -37.38 | -39.80 | 0.000 | net -9.2 bps; Sharpe -37.38; DSR 0.00; Binance universe -39.80 |
| S-own:k3:taker:fade:H5 | 126452 | -9.6 | -9.9 | -2.7 | -33.22 | -36.08 | 0.000 | net -9.6 bps; Sharpe -33.22; DSR 0.00; Binance universe -36.08 |
| S-own:k3:taker:fade:H15 | 93367 | -9.6 | -10.1 | -2.7 | -28.44 | -31.35 | 0.000 | net -9.6 bps; Sharpe -28.44; DSR 0.00; Binance universe -31.35 |
| S-own:k3:taker:fade:H30 | 68957 | -10.0 | -10.8 | -2.9 | -22.88 | -24.56 | 0.000 | net -10.0 bps; Sharpe -22.88; DSR 0.00; Binance universe -24.56 |
| S-own:k3:taker:fade:H60 | 46112 | -8.4 | -10.0 | -2.1 | -15.63 | -15.30 | 0.000 | net -8.4 bps; Sharpe -15.63; DSR 0.00; Binance universe -15.30 |
| S-own:k3:taker:fade:H240 | 15996 | -7.1 | -12.6 | -1.4 | -5.89 | -6.25 | 0.000 | net -7.1 bps; Sharpe -5.89; DSR 0.00; Binance universe -6.25 |
| S-own:k3:taker:fade:bracket | 60499 | -9.6 | -10.3 | -2.3 | -21.01 | -21.80 | 0.000 | net -9.6 bps; Sharpe -21.01; DSR 0.00; Binance universe -21.80 |
| S-own:k4:none:cont:H1 | 104372 | -11.4 | -12.1 | -3.6 | -30.01 | -32.65 | 0.000 | net -11.4 bps; Sharpe -30.01; DSR 0.00; Binance universe -32.65 |
| S-own:k4:none:cont:H5 | 81654 | -12.1 | -13.0 | -4.0 | -25.25 | -25.57 | 0.000 | net -12.1 bps; Sharpe -25.25; DSR 0.00; Binance universe -25.57 |
| S-own:k4:none:cont:H15 | 61739 | -12.1 | -13.3 | -4.0 | -20.03 | -19.92 | 0.000 | net -12.1 bps; Sharpe -20.03; DSR 0.00; Binance universe -19.92 |
| S-own:k4:none:cont:H30 | 48688 | -12.2 | -14.0 | -4.1 | -12.99 | -14.02 | 0.000 | net -12.2 bps; Sharpe -12.99; DSR 0.00; Binance universe -14.02 |
| S-own:k4:none:cont:H60 | 35659 | -12.5 | -14.5 | -4.2 | -11.81 | -10.46 | 0.000 | net -12.5 bps; Sharpe -11.81; DSR 0.00; Binance universe -10.46 |
| S-own:k4:none:cont:H240 | 14661 | -7.7 | -12.5 | -1.7 | -4.19 | -3.76 | 0.000 | net -7.7 bps; Sharpe -4.19; DSR 0.00; Binance universe -3.76 |
| S-own:k4:none:cont:bracket | 51229 | -11.5 | -12.9 | -3.3 | -18.66 | -17.42 | 0.000 | net -11.5 bps; Sharpe -18.66; DSR 0.00; Binance universe -17.42 |
| S-own:k4:none:fade:H1 | 100196 | -8.7 | -9.1 | -2.2 | -30.79 | -35.58 | 0.000 | net -8.7 bps; Sharpe -30.79; DSR 0.00; Binance universe -35.58 |
| S-own:k4:none:fade:H5 | 81450 | -9.0 | -9.6 | -2.4 | -25.27 | -28.21 | 0.000 | net -9.0 bps; Sharpe -25.27; DSR 0.00; Binance universe -28.21 |
| S-own:k4:none:fade:H15 | 61774 | -8.6 | -9.5 | -2.2 | -21.80 | -24.24 | 0.000 | net -8.6 bps; Sharpe -21.80; DSR 0.00; Binance universe -24.24 |
| S-own:k4:none:fade:H30 | 48527 | -8.7 | -10.3 | -2.3 | -16.37 | -18.42 | 0.000 | net -8.7 bps; Sharpe -16.37; DSR 0.00; Binance universe -18.42 |
| S-own:k4:none:fade:H60 | 35647 | -8.5 | -11.5 | -2.2 | -12.61 | -13.29 | 0.000 | net -8.5 bps; Sharpe -12.61; DSR 0.00; Binance universe -13.29 |
| S-own:k4:none:fade:H240 | 14736 | -6.9 | -13.6 | -1.3 | -5.74 | -4.83 | 0.000 | net -6.9 bps; Sharpe -5.74; DSR 0.00; Binance universe -4.83 |
| S-own:k4:none:fade:bracket | 51689 | -9.1 | -10.3 | -2.1 | -16.78 | -17.84 | 0.000 | net -9.1 bps; Sharpe -16.78; DSR 0.00; Binance universe -17.84 |
| S-own:k4:vol:cont:H1 | 46820 | -11.2 | -12.4 | -3.5 | -23.51 | -25.59 | 0.000 | net -11.2 bps; Sharpe -23.51; DSR 0.00; Binance universe -25.59 |
| S-own:k4:vol:cont:H5 | 37871 | -12.1 | -13.4 | -4.0 | -17.09 | -17.22 | 0.000 | net -12.1 bps; Sharpe -17.09; DSR 0.00; Binance universe -17.22 |
| S-own:k4:vol:cont:H15 | 31142 | -12.6 | -14.3 | -4.3 | -13.83 | -13.75 | 0.000 | net -12.6 bps; Sharpe -13.83; DSR 0.00; Binance universe -13.75 |
| S-own:k4:vol:cont:H30 | 26993 | -11.1 | -13.9 | -3.5 | -7.77 | -8.28 | 0.000 | net -11.1 bps; Sharpe -7.77; DSR 0.00; Binance universe -8.28 |
| S-own:k4:vol:cont:H60 | 22365 | -10.9 | -13.9 | -3.4 | -7.25 | -7.79 | 0.000 | net -10.9 bps; Sharpe -7.25; DSR 0.00; Binance universe -7.79 |
| S-own:k4:vol:cont:H240 | 12004 | -12.9 | -18.5 | -4.3 | -4.32 | -4.06 | 0.000 | net -12.9 bps; Sharpe -4.32; DSR 0.00; Binance universe -4.06 |
| S-own:k4:vol:cont:bracket | 31429 | -10.0 | -11.9 | -2.6 | -13.15 | -12.55 | 0.000 | net -10.0 bps; Sharpe -13.15; DSR 0.00; Binance universe -12.55 |
| S-own:k4:vol:fade:H1 | 44989 | -8.6 | -9.2 | -2.1 | -25.27 | -28.65 | 0.000 | net -8.6 bps; Sharpe -25.27; DSR 0.00; Binance universe -28.65 |
| S-own:k4:vol:fade:H5 | 38702 | -8.9 | -10.1 | -2.3 | -19.63 | -21.46 | 0.000 | net -8.9 bps; Sharpe -19.63; DSR 0.00; Binance universe -21.46 |
| S-own:k4:vol:fade:H15 | 32051 | -7.6 | -9.4 | -1.7 | -14.99 | -16.20 | 0.000 | net -7.6 bps; Sharpe -14.99; DSR 0.00; Binance universe -16.20 |
| S-own:k4:vol:fade:H30 | 27453 | -9.3 | -12.2 | -2.5 | -11.89 | -12.77 | 0.000 | net -9.3 bps; Sharpe -11.89; DSR 0.00; Binance universe -12.77 |
| S-own:k4:vol:fade:H60 | 22667 | -8.9 | -13.0 | -2.3 | -10.07 | -9.94 | 0.000 | net -8.9 bps; Sharpe -10.07; DSR 0.00; Binance universe -9.94 |
| S-own:k4:vol:fade:H240 | 12097 | -8.9 | -15.2 | -2.3 | -5.25 | -5.30 | 0.000 | net -8.9 bps; Sharpe -5.25; DSR 0.00; Binance universe -5.30 |
| S-own:k4:vol:fade:bracket | 32485 | -10.0 | -11.8 | -2.5 | -14.14 | -15.53 | 0.000 | net -10.0 bps; Sharpe -14.14; DSR 0.00; Binance universe -15.53 |
| S-own:k4:taker:cont:H1 | 56989 | -11.5 | -12.1 | -3.7 | -28.27 | -29.70 | 0.000 | net -11.5 bps; Sharpe -28.27; DSR 0.00; Binance universe -29.70 |
| S-own:k4:taker:cont:H5 | 50625 | -12.0 | -13.0 | -3.9 | -22.13 | -22.21 | 0.000 | net -12.0 bps; Sharpe -22.13; DSR 0.00; Binance universe -22.21 |
| S-own:k4:taker:cont:H15 | 42448 | -12.0 | -13.0 | -3.9 | -19.16 | -20.30 | 0.000 | net -12.0 bps; Sharpe -19.16; DSR 0.00; Binance universe -20.30 |
| S-own:k4:taker:cont:H30 | 35675 | -10.7 | -13.0 | -3.3 | -13.37 | -14.32 | 0.000 | net -10.7 bps; Sharpe -13.37; DSR 0.00; Binance universe -14.32 |
| S-own:k4:taker:cont:H60 | 27910 | -11.8 | -13.6 | -3.8 | -12.15 | -12.23 | 0.000 | net -11.8 bps; Sharpe -12.15; DSR 0.00; Binance universe -12.23 |
| S-own:k4:taker:cont:H240 | 13156 | -12.5 | -16.7 | -4.1 | -5.82 | -4.86 | 0.000 | net -12.5 bps; Sharpe -5.82; DSR 0.00; Binance universe -4.86 |
| S-own:k4:taker:cont:bracket | 36057 | -10.2 | -11.6 | -2.7 | -15.32 | -15.97 | 0.000 | net -10.2 bps; Sharpe -15.32; DSR 0.00; Binance universe -15.97 |
| S-own:k4:taker:fade:H1 | 54239 | -8.8 | -9.1 | -2.3 | -27.80 | -29.71 | 0.000 | net -8.8 bps; Sharpe -27.80; DSR 0.00; Binance universe -29.71 |
| S-own:k4:taker:fade:H5 | 49304 | -9.3 | -9.9 | -2.5 | -22.94 | -24.72 | 0.000 | net -9.3 bps; Sharpe -22.94; DSR 0.00; Binance universe -24.72 |
| S-own:k4:taker:fade:H15 | 41504 | -9.8 | -10.7 | -2.8 | -19.87 | -21.90 | 0.000 | net -9.8 bps; Sharpe -19.87; DSR 0.00; Binance universe -21.90 |
| S-own:k4:taker:fade:H30 | 34926 | -9.9 | -11.1 | -2.9 | -15.70 | -17.28 | 0.000 | net -9.9 bps; Sharpe -15.70; DSR 0.00; Binance universe -17.28 |
| S-own:k4:taker:fade:H60 | 27411 | -8.9 | -11.0 | -2.4 | -11.75 | -12.81 | 0.000 | net -8.9 bps; Sharpe -11.75; DSR 0.00; Binance universe -12.81 |
| S-own:k4:taker:fade:H240 | 13061 | -7.5 | -12.5 | -1.6 | -5.38 | -6.04 | 0.000 | net -7.5 bps; Sharpe -5.38; DSR 0.00; Binance universe -6.04 |
| S-own:k4:taker:fade:bracket | 35880 | -9.3 | -10.4 | -2.2 | -15.65 | -17.10 | 0.000 | net -9.3 bps; Sharpe -15.65; DSR 0.00; Binance universe -17.10 |
| S-own:k6:none:cont:H1 | 27284 | -10.6 | -13.1 | -3.1 | -15.69 | -17.40 | 0.000 | net -10.6 bps; Sharpe -15.69; DSR 0.00; Binance universe -17.40 |
| S-own:k6:none:cont:H5 | 23130 | -12.4 | -14.9 | -4.1 | -11.49 | -13.32 | 0.000 | net -12.4 bps; Sharpe -11.49; DSR 0.00; Binance universe -13.32 |
| S-own:k6:none:cont:H15 | 19379 | -13.4 | -16.0 | -4.7 | -10.27 | -10.90 | 0.000 | net -13.4 bps; Sharpe -10.27; DSR 0.00; Binance universe -10.90 |
| S-own:k6:none:cont:H30 | 17112 | -10.5 | -14.7 | -3.2 | -5.18 | -5.69 | 0.000 | net -10.5 bps; Sharpe -5.18; DSR 0.00; Binance universe -5.69 |
| S-own:k6:none:cont:H60 | 14690 | -10.9 | -14.7 | -3.4 | -5.10 | -4.89 | 0.000 | net -10.9 bps; Sharpe -5.10; DSR 0.00; Binance universe -4.89 |
| S-own:k6:none:cont:H240 | 9314 | -11.6 | -18.2 | -3.7 | -2.44 | -2.53 | 0.000 | net -11.6 bps; Sharpe -2.44; DSR 0.00; Binance universe -2.53 |
| S-own:k6:none:cont:bracket | 21197 | -10.4 | -12.9 | -2.8 | -11.06 | -10.60 | 0.000 | net -10.4 bps; Sharpe -11.06; DSR 0.00; Binance universe -10.60 |
| S-own:k6:none:fade:H1 | 26394 | -7.5 | -8.2 | -1.5 | -18.65 | -21.89 | 0.000 | net -7.5 bps; Sharpe -18.65; DSR 0.00; Binance universe -21.89 |
| S-own:k6:none:fade:H5 | 23601 | -7.1 | -8.7 | -1.3 | -13.78 | -16.01 | 0.000 | net -7.1 bps; Sharpe -13.78; DSR 0.00; Binance universe -16.01 |
| S-own:k6:none:fade:H15 | 20290 | -6.4 | -9.3 | -1.1 | -11.55 | -13.10 | 0.000 | net -6.4 bps; Sharpe -11.55; DSR 0.00; Binance universe -13.10 |
| S-own:k6:none:fade:H30 | 17811 | -8.5 | -12.3 | -2.1 | -9.79 | -11.48 | 0.000 | net -8.5 bps; Sharpe -9.79; DSR 0.00; Binance universe -11.48 |
| S-own:k6:none:fade:H60 | 15188 | -8.1 | -14.2 | -1.9 | -8.65 | -9.52 | 0.000 | net -8.1 bps; Sharpe -8.65; DSR 0.00; Binance universe -9.52 |
| S-own:k6:none:fade:H240 | 9411 | -5.1 | -13.7 | -0.4 | -3.97 | -5.23 | 0.000 | net -5.1 bps; Sharpe -3.97; DSR 0.00; Binance universe -5.23 |
| S-own:k6:none:fade:bracket | 21332 | -10.0 | -12.2 | -2.5 | -11.52 | -13.63 | 0.000 | net -10.0 bps; Sharpe -11.52; DSR 0.00; Binance universe -13.63 |
| S-own:k6:vol:cont:H1 | 20658 | -11.0 | -13.7 | -3.2 | -14.69 | -16.65 | 0.000 | net -11.0 bps; Sharpe -14.69; DSR 0.00; Binance universe -16.65 |
| S-own:k6:vol:cont:H5 | 17561 | -12.5 | -15.6 | -4.1 | -9.91 | -11.47 | 0.000 | net -12.5 bps; Sharpe -9.91; DSR 0.00; Binance universe -11.47 |
| S-own:k6:vol:cont:H15 | 14983 | -13.9 | -16.9 | -4.9 | -8.70 | -8.98 | 0.000 | net -13.9 bps; Sharpe -8.70; DSR 0.00; Binance universe -8.98 |
| S-own:k6:vol:cont:H30 | 13485 | -10.4 | -15.4 | -3.2 | -4.33 | -4.71 | 0.000 | net -10.4 bps; Sharpe -4.33; DSR 0.00; Binance universe -4.71 |
| S-own:k6:vol:cont:H60 | 11966 | -11.0 | -15.2 | -3.5 | -4.43 | -4.43 | 0.000 | net -11.0 bps; Sharpe -4.43; DSR 0.00; Binance universe -4.43 |
| S-own:k6:vol:cont:H240 | 8255 | -12.2 | -19.5 | -3.9 | -2.58 | -2.48 | 0.000 | net -12.2 bps; Sharpe -2.58; DSR 0.00; Binance universe -2.48 |
| S-own:k6:vol:cont:bracket | 16895 | -10.5 | -13.1 | -2.8 | -9.88 | -9.56 | 0.000 | net -10.5 bps; Sharpe -9.88; DSR 0.00; Binance universe -9.56 |
| S-own:k6:vol:fade:H1 | 19936 | -7.4 | -8.2 | -1.5 | -17.11 | -19.77 | 0.000 | net -7.4 bps; Sharpe -17.11; DSR 0.00; Binance universe -19.77 |
| S-own:k6:vol:fade:H5 | 18073 | -6.4 | -8.3 | -1.0 | -12.18 | -13.91 | 0.000 | net -6.4 bps; Sharpe -12.18; DSR 0.00; Binance universe -13.91 |
| S-own:k6:vol:fade:H15 | 15873 | -5.2 | -8.4 | -0.5 | -9.40 | -10.50 | 0.000 | net -5.2 bps; Sharpe -9.40; DSR 0.00; Binance universe -10.50 |
| S-own:k6:vol:fade:H30 | 14189 | -7.2 | -12.2 | -1.5 | -8.34 | -9.18 | 0.000 | net -7.2 bps; Sharpe -8.34; DSR 0.00; Binance universe -9.18 |
| S-own:k6:vol:fade:H60 | 12385 | -6.3 | -13.2 | -1.0 | -6.89 | -7.80 | 0.000 | net -6.3 bps; Sharpe -6.89; DSR 0.00; Binance universe -7.80 |
| S-own:k6:vol:fade:H240 | 8324 | -7.5 | -16.8 | -1.6 | -3.98 | -5.04 | 0.000 | net -7.5 bps; Sharpe -3.98; DSR 0.00; Binance universe -5.04 |
| S-own:k6:vol:fade:bracket | 17099 | -9.6 | -12.0 | -2.3 | -10.48 | -12.44 | 0.000 | net -9.6 bps; Sharpe -10.48; DSR 0.00; Binance universe -12.44 |
| S-own:k6:taker:cont:H1 | 12137 | -10.3 | -12.7 | -2.9 | -15.21 | -15.61 | 0.000 | net -10.3 bps; Sharpe -15.21; DSR 0.00; Binance universe -15.61 |
| S-own:k6:taker:cont:H5 | 11438 | -10.5 | -14.8 | -3.1 | -8.43 | -8.21 | 0.000 | net -10.5 bps; Sharpe -8.43; DSR 0.00; Binance universe -8.21 |
| S-own:k6:taker:cont:H15 | 10574 | -12.4 | -14.9 | -4.1 | -8.06 | -9.27 | 0.000 | net -12.4 bps; Sharpe -8.06; DSR 0.00; Binance universe -9.27 |
| S-own:k6:taker:cont:H30 | 9819 | -5.7 | -12.9 | -0.8 | -4.45 | -4.97 | 0.000 | net -5.7 bps; Sharpe -4.45; DSR 0.00; Binance universe -4.97 |
| S-own:k6:taker:cont:H60 | 8935 | -8.8 | -13.2 | -2.3 | -3.93 | -4.44 | 0.000 | net -8.8 bps; Sharpe -3.93; DSR 0.00; Binance universe -4.44 |
| S-own:k6:taker:cont:H240 | 6541 | -15.8 | -22.6 | -5.7 | -2.40 | -2.69 | 0.000 | net -15.8 bps; Sharpe -2.40; DSR 0.00; Binance universe -2.69 |
| S-own:k6:taker:cont:bracket | 10833 | -8.1 | -11.5 | -1.6 | -7.28 | -7.62 | 0.000 | net -8.1 bps; Sharpe -7.28; DSR 0.00; Binance universe -7.62 |
| S-own:k6:taker:fade:H1 | 11684 | -7.5 | -8.4 | -1.5 | -15.72 | -16.52 | 0.000 | net -7.5 bps; Sharpe -15.72; DSR 0.00; Binance universe -16.52 |
| S-own:k6:taker:fade:H5 | 11342 | -7.4 | -9.4 | -1.5 | -11.11 | -11.91 | 0.000 | net -7.4 bps; Sharpe -11.11; DSR 0.00; Binance universe -11.91 |
| S-own:k6:taker:fade:H15 | 10608 | -8.4 | -10.3 | -2.0 | -10.11 | -10.98 | 0.000 | net -8.4 bps; Sharpe -10.11; DSR 0.00; Binance universe -10.98 |
| S-own:k6:taker:fade:H30 | 9880 | -9.4 | -12.3 | -2.6 | -8.39 | -9.06 | 0.000 | net -9.4 bps; Sharpe -8.39; DSR 0.00; Binance universe -9.06 |
| S-own:k6:taker:fade:H60 | 8979 | -6.9 | -12.0 | -1.3 | -6.73 | -7.02 | 0.000 | net -6.9 bps; Sharpe -6.73; DSR 0.00; Binance universe -7.02 |
| S-own:k6:taker:fade:H240 | 6512 | -0.7 | -11.1 | 1.9 | -3.73 | -4.00 | 0.000 | net -0.7 bps; Sharpe -3.73; DSR 0.00; Binance universe -4.00 |
| S-own:k6:taker:fade:bracket | 10748 | -10.4 | -12.7 | -2.7 | -9.60 | -10.14 | 0.000 | net -10.4 bps; Sharpe -9.60; DSR 0.00; Binance universe -10.14 |
| S-lead:k3:H1 | 42490 | -9.6 | -10.1 | -2.9 | -19.49 | -21.04 | 0.000 | net -9.6 bps; Sharpe -19.49; DSR 0.00; Binance universe -21.04 |
| S-lead:k3:H5 | 33270 | -9.7 | -11.8 | -2.9 | -17.36 | -17.10 | 0.000 | net -9.7 bps; Sharpe -17.36; DSR 0.00; Binance universe -17.10 |
| S-lead:k3:H15 | 25796 | -8.8 | -12.0 | -2.5 | -10.96 | -11.10 | 0.000 | net -8.8 bps; Sharpe -10.96; DSR 0.00; Binance universe -11.10 |
| S-lead:k3:H30 | 20824 | -10.2 | -13.0 | -3.2 | -8.47 | -9.17 | 0.000 | net -10.2 bps; Sharpe -8.47; DSR 0.00; Binance universe -9.17 |
| S-lead:k3:H60 | 15937 | -13.4 | -16.5 | -4.8 | -6.74 | -7.97 | 0.000 | net -13.4 bps; Sharpe -6.74; DSR 0.00; Binance universe -7.97 |
| S-lead:k3:H240 | 8380 | -12.2 | -19.8 | -4.0 | -2.87 | -2.71 | 0.000 | net -12.2 bps; Sharpe -2.87; DSR 0.00; Binance universe -2.71 |
| S-lead:k4:H1 | 13554 | -8.7 | -10.0 | -2.4 | -12.88 | -13.97 | 0.000 | net -8.7 bps; Sharpe -12.88; DSR 0.00; Binance universe -13.97 |
| S-lead:k4:H5 | 11364 | -4.8 | -10.4 | -0.5 | -8.24 | -7.89 | 0.000 | net -4.8 bps; Sharpe -8.24; DSR 0.00; Binance universe -7.89 |
| S-lead:k4:H15 | 9716 | -5.5 | -13.0 | -0.8 | -4.79 | -4.76 | 0.000 | net -5.5 bps; Sharpe -4.79; DSR 0.00; Binance universe -4.76 |
| S-lead:k4:H30 | 8460 | -9.4 | -15.3 | -2.8 | -4.20 | -4.29 | 0.000 | net -9.4 bps; Sharpe -4.20; DSR 0.00; Binance universe -4.29 |
| S-lead:k4:H60 | 7226 | -13.0 | -18.0 | -4.5 | -3.94 | -4.26 | 0.000 | net -13.0 bps; Sharpe -3.94; DSR 0.00; Binance universe -4.26 |
| S-lead:k4:H240 | 4890 | -15.7 | -27.2 | -5.7 | -2.09 | -1.19 | 0.000 | net -15.7 bps; Sharpe -2.09; DSR 0.00; Binance universe -1.19 |
| S-lead:k6:H1 | 2206 | -9.0 | -11.8 | -2.6 | -5.26 | -5.84 | 0.000 | net -9.0 bps; Sharpe -5.26; DSR 0.00; Binance universe -5.84 |
| S-lead:k6:H5 | 1936 | -5.2 | -12.7 | -0.6 | -3.32 | -2.11 | 0.000 | net -5.2 bps; Sharpe -3.32; DSR 0.00; Binance universe -2.11 |
| S-lead:k6:H15 | 1765 | -0.1 | -15.6 | 1.9 | -1.87 | -1.95 | 0.000 | net -0.1 bps; Sharpe -1.87; DSR 0.00; Binance universe -1.95 |
| S-lead:k6:H30 | 1662 | -1.1 | -19.7 | 1.4 | -1.46 | -1.74 | 0.000 | net -1.1 bps; Sharpe -1.46; DSR 0.00; Binance universe -1.74 |
| S-lead:k6:H60 | 1536 | 5.0 | -13.3 | 4.5 | -0.66 | -1.70 | 0.000 | band 5 % -13.3 bps; Sharpe -0.66; DSR 0.00; Binance universe -1.70 |
| S-lead:k6:H240 | 1311 | -0.6 | -33.0 | 1.9 | 0.21 | -0.51 | 0.000 | net -0.6 bps; DSR 0.00; Binance universe -0.51 |
| D-orb:utc30:A | 2802 | -16.8 | -37.7 | -5.4 | -1.29 | -0.40 | 0.000 | net -16.8 bps; Sharpe -1.29; DSR 0.00; Binance universe -0.40 |
| D-orb:utc30:B | 2831 | -12.8 | -32.3 | -3.6 | -1.20 | -0.68 | 0.000 | net -12.8 bps; Sharpe -1.20; DSR 0.00; Binance universe -0.68 |
| D-orb:utc60:A | 2885 | -36.3 | -55.6 | -15.2 | -2.73 | -2.78 | 0.000 | net -36.3 bps; Sharpe -2.73; DSR 0.00; Binance universe -2.78 |
| D-orb:utc60:B | 2959 | -38.7 | -54.3 | -16.6 | -3.59 | -3.23 | 0.000 | net -38.7 bps; Sharpe -3.59; DSR 0.00; Binance universe -3.23 |
| D-orb:us30:A | 2824 | 0.5 | -18.8 | 3.3 | -0.02 | 0.37 | 0.000 | band 5 % -18.8 bps; Sharpe -0.02; DSR 0.00 |
| D-orb:us30:B | 3024 | -6.6 | -22.0 | -0.7 | -1.13 | -1.34 | 0.000 | net -6.6 bps; Sharpe -1.13; DSR 0.00; Binance universe -1.34 |
| D-orb:us60:A | 2876 | 0.6 | -16.4 | 3.3 | 0.21 | 0.52 | 0.000 | band 5 % -16.4 bps; DSR 0.00 |
| D-orb:us60:B | 3201 | -9.5 | -21.1 | -2.1 | -1.03 | -0.73 | 0.000 | net -9.5 bps; Sharpe -1.03; DSR 0.00; Binance universe -0.73 |
| D-prev:A | 3850 | -19.3 | -37.5 | -6.7 | -1.41 | -1.30 | 0.000 | net -19.3 bps; Sharpe -1.41; DSR 0.00; Binance universe -1.30 |
| D-prev:B | 4720 | -17.0 | -29.0 | -6.0 | -1.84 | -1.86 | 0.000 | net -17.0 bps; Sharpe -1.84; DSR 0.00; Binance universe -1.86 |
| D-vwap:m0.25 | 6938 | -5.3 | -14.0 | -0.5 | -2.20 | -2.17 | 0.000 | net -5.3 bps; Sharpe -2.20; DSR 0.00; Binance universe -2.17 |
| D-vwap:m0.5 | 4298 | -4.4 | -16.8 | 0.4 | -1.19 | -2.01 | 0.000 | net -4.4 bps; Sharpe -1.19; DSR 0.00; Binance universe -2.01 |
| P-gbm:H15:m0 | 20496 | -8.9 | -11.7 | -2.6 | -8.57 | -10.77 | 0.000 | net -8.9 bps; Sharpe -8.57; DSR 0.00; Binance universe -10.77 |
| P-gbm:H15:m5 | 10230 | -6.4 | -11.1 | -1.4 | -5.11 | -6.38 | 0.000 | net -6.4 bps; Sharpe -5.11; DSR 0.00; Binance universe -6.38 |
| P-gbm:H15:m10 | 5793 | -0.9 | -8.2 | 1.3 | -2.63 | -4.36 | 0.000 | net -0.9 bps; Sharpe -2.63; DSR 0.00; Binance universe -4.36 |
| P-gbm:H15:m20 | 2279 | 10.5 | -8.0 | 7.0 | -0.08 | -1.48 | 0.000 | band 5 % -8.0 bps; Sharpe -0.08; DSR 0.00; Binance universe -1.48 |
| P-gbm:H60:m0 | 34851 | -7.2 | -9.9 | -1.8 | -6.26 | -6.87 | 0.000 | net -7.2 bps; Sharpe -6.26; DSR 0.00; Binance universe -6.87 |
| P-gbm:H60:m5 | 23846 | -6.3 | -9.9 | -1.3 | -4.81 | -5.02 | 0.000 | net -6.3 bps; Sharpe -4.81; DSR 0.00; Binance universe -5.02 |
| P-gbm:H60:m10 | 16682 | -5.5 | -10.1 | -0.9 | -3.51 | -4.51 | 0.000 | net -5.5 bps; Sharpe -3.51; DSR 0.00; Binance universe -4.51 |
| P-gbm:H60:m20 | 8561 | -4.2 | -11.7 | -0.3 | -3.06 | -4.07 | 0.000 | net -4.2 bps; Sharpe -3.06; DSR 0.00; Binance universe -4.07 |

Maker sensitivity (not judged): with fast_maker's 3 bps adverse-selection haircut on every maker leg, 1 rules stay net positive.

## Kraken Futures taker (5 bps)

| rule | trades | net bps | band 5 % | break-even fee | Sharpe OOS | Binance univ. | DSR | fails |
|---|---|---|---|---|---|---|---|---|
| S-own:k3:none:cont:H1 | 299054 | -13.6 | -14.0 | -1.8 | -39.06 | -41.93 | 0.000 | net -13.6 bps; Sharpe -39.06; late -12.8 bps; DSR 0.00; Binance universe -41.93 |
| S-own:k3:none:cont:H5 | 200619 | -14.0 | -14.4 | -2.0 | -37.00 | -39.70 | 0.000 | net -14.0 bps; Sharpe -37.00; late -13.2 bps; DSR 0.00; Binance universe -39.70 |
| S-own:k3:none:cont:H15 | 128092 | -14.4 | -15.2 | -2.2 | -30.49 | -35.60 | 0.000 | net -14.4 bps; Sharpe -30.49; late -13.8 bps; DSR 0.00; Binance universe -35.60 |
| S-own:k3:none:cont:H30 | 86575 | -14.2 | -15.4 | -2.1 | -22.20 | -23.59 | 0.000 | net -14.2 bps; Sharpe -22.20; late -13.6 bps; DSR 0.00; Binance universe -23.59 |
| S-own:k3:none:cont:H60 | 53359 | -15.1 | -16.5 | -2.6 | -18.27 | -16.22 | 0.000 | net -15.1 bps; Sharpe -18.27; late -14.0 bps; DSR 0.00; Binance universe -16.22 |
| S-own:k3:none:cont:H240 | 16464 | -11.3 | -15.9 | -0.7 | -4.98 | -3.82 | 0.000 | net -11.3 bps; Sharpe -4.98; late -12.4 bps; DSR 0.00; Binance universe -3.82 |
| S-own:k3:none:cont:bracket | 74433 | -14.4 | -15.5 | -2.2 | -25.94 | -25.96 | 0.000 | net -14.4 bps; Sharpe -25.94; late -13.4 bps; DSR 0.00; Binance universe -25.96 |
| S-own:k3:none:fade:H1 | 299054 | -11.8 | -12.0 | -0.9 | -37.68 | -40.93 | 0.000 | net -11.8 bps; Sharpe -37.68; late -12.7 bps; DSR 0.00; Binance universe -40.93 |
| S-own:k3:none:fade:H5 | 205588 | -11.6 | -11.9 | -0.8 | -33.20 | -36.21 | 0.000 | net -11.6 bps; Sharpe -33.20; late -12.6 bps; DSR 0.00; Binance universe -36.21 |
| S-own:k3:none:fade:H15 | 130940 | -10.9 | -11.5 | -0.4 | -28.89 | -32.03 | 0.000 | net -10.9 bps; Sharpe -28.89; late -11.6 bps; DSR 0.00; Binance universe -32.03 |
| S-own:k3:none:fade:H30 | 88282 | -11.3 | -12.3 | -0.7 | -25.03 | -25.39 | 0.000 | net -11.3 bps; Sharpe -25.03; late -12.0 bps; DSR 0.00; Binance universe -25.39 |
| S-own:k3:none:fade:H60 | 54191 | -11.1 | -12.7 | -0.5 | -16.88 | -15.87 | 0.000 | net -11.1 bps; Sharpe -16.88; late -9.9 bps; DSR 0.00; Binance universe -15.87 |
| S-own:k3:none:fade:H240 | 16632 | -10.2 | -15.5 | -0.1 | -5.30 | -4.63 | 0.000 | net -10.2 bps; Sharpe -5.30; late -8.7 bps; DSR 0.00; Binance universe -4.63 |
| S-own:k3:none:fade:bracket | 75600 | -11.5 | -12.4 | -0.7 | -22.17 | -23.04 | 0.000 | net -11.5 bps; Sharpe -22.17; late -12.9 bps; DSR 0.00; Binance universe -23.04 |
| S-own:k3:vol:cont:H1 | 74499 | -13.2 | -13.9 | -1.6 | -31.20 | -33.69 | 0.000 | net -13.2 bps; Sharpe -31.20; late -12.2 bps; DSR 0.00; Binance universe -33.69 |
| S-own:k3:vol:cont:H5 | 56330 | -13.2 | -14.4 | -1.6 | -21.25 | -22.21 | 0.000 | net -13.2 bps; Sharpe -21.25; late -12.3 bps; DSR 0.00; Binance universe -22.21 |
| S-own:k3:vol:cont:H15 | 44862 | -14.2 | -15.5 | -2.1 | -16.63 | -17.18 | 0.000 | net -14.2 bps; Sharpe -16.63; late -13.1 bps; DSR 0.00; Binance universe -17.18 |
| S-own:k3:vol:cont:H30 | 37681 | -13.0 | -15.1 | -1.5 | -10.11 | -10.85 | 0.000 | net -13.0 bps; Sharpe -10.11; late -11.9 bps; DSR 0.00; Binance universe -10.85 |
| S-own:k3:vol:cont:H60 | 29669 | -13.1 | -15.5 | -1.5 | -9.03 | -9.43 | 0.000 | net -13.1 bps; Sharpe -9.03; late -12.5 bps; DSR 0.00; Binance universe -9.43 |
| S-own:k3:vol:cont:H240 | 13703 | -10.4 | -14.9 | -0.2 | -4.33 | -4.72 | 0.000 | net -10.4 bps; Sharpe -4.33; late -9.9 bps; DSR 0.00; Binance universe -4.72 |
| S-own:k3:vol:cont:bracket | 41279 | -13.1 | -14.8 | -1.6 | -16.40 | -16.40 | 0.000 | net -13.1 bps; Sharpe -16.40; late -12.0 bps; DSR 0.00; Binance universe -16.40 |
| S-own:k3:vol:fade:H1 | 74499 | -10.8 | -11.3 | -0.4 | -29.84 | -32.59 | 0.000 | net -10.8 bps; Sharpe -29.84; late -11.7 bps; DSR 0.00; Binance universe -32.59 |
| S-own:k3:vol:fade:H5 | 59912 | -10.5 | -11.4 | -0.3 | -22.02 | -23.44 | 0.000 | net -10.5 bps; Sharpe -22.02; late -11.8 bps; DSR 0.00; Binance universe -23.44 |
| S-own:k3:vol:fade:H15 | 47583 | -9.7 | -11.2 | 0.1 | -17.09 | -17.81 | 0.000 | net -9.7 bps; Sharpe -17.09; late -11.0 bps; DSR 0.00; Binance universe -17.81 |
| S-own:k3:vol:fade:H30 | 39542 | -10.5 | -12.1 | -0.2 | -13.82 | -14.27 | 0.000 | net -10.5 bps; Sharpe -13.82; late -11.4 bps; DSR 0.00; Binance universe -14.27 |
| S-own:k3:vol:fade:H60 | 30837 | -10.3 | -12.7 | -0.1 | -10.78 | -10.20 | 0.000 | net -10.3 bps; Sharpe -10.78; late -8.6 bps; DSR 0.00; Binance universe -10.20 |
| S-own:k3:vol:fade:H240 | 14009 | -10.9 | -17.5 | -0.4 | -6.18 | -4.97 | 0.000 | net -10.9 bps; Sharpe -6.18; late -8.4 bps; DSR 0.00; Binance universe -4.97 |
| S-own:k3:vol:fade:bracket | 44137 | -11.6 | -12.8 | -0.8 | -15.63 | -16.48 | 0.000 | net -11.6 bps; Sharpe -15.63; late -13.0 bps; DSR 0.00; Binance universe -16.48 |
| S-own:k3:taker:cont:H1 | 179088 | -13.6 | -13.9 | -1.8 | -36.05 | -37.99 | 0.000 | net -13.6 bps; Sharpe -36.05; late -12.8 bps; DSR 0.00; Binance universe -37.99 |
| S-own:k3:taker:cont:H5 | 142434 | -13.9 | -14.4 | -2.0 | -33.88 | -35.76 | 0.000 | net -13.9 bps; Sharpe -33.88; late -13.2 bps; DSR 0.00; Binance universe -35.76 |
| S-own:k3:taker:cont:H15 | 102083 | -14.4 | -15.0 | -2.2 | -30.94 | -33.31 | 0.000 | net -14.4 bps; Sharpe -30.94; late -13.7 bps; DSR 0.00; Binance universe -33.31 |
| S-own:k3:taker:cont:H30 | 73726 | -13.9 | -14.9 | -2.0 | -24.72 | -25.37 | 0.000 | net -13.9 bps; Sharpe -24.72; late -13.3 bps; DSR 0.00; Binance universe -25.37 |
| S-own:k3:taker:cont:H60 | 48133 | -14.3 | -15.6 | -2.2 | -17.12 | -18.11 | 0.000 | net -14.3 bps; Sharpe -17.12; late -13.9 bps; DSR 0.00; Binance universe -18.11 |
| S-own:k3:taker:cont:H240 | 16090 | -13.3 | -17.1 | -1.7 | -5.63 | -4.40 | 0.000 | net -13.3 bps; Sharpe -5.63; late -12.7 bps; DSR 0.00; Binance universe -4.40 |
| S-own:k3:taker:cont:bracket | 62501 | -13.7 | -14.7 | -1.8 | -24.66 | -26.64 | 0.000 | net -13.7 bps; Sharpe -24.66; late -13.3 bps; DSR 0.00; Binance universe -26.64 |
| S-own:k3:taker:fade:H1 | 179088 | -12.2 | -12.4 | -1.1 | -35.08 | -36.67 | 0.000 | net -12.2 bps; Sharpe -35.08; late -13.0 bps; DSR 0.00; Binance universe -36.67 |
| S-own:k3:taker:fade:H5 | 144828 | -12.0 | -12.3 | -1.0 | -30.19 | -32.20 | 0.000 | net -12.0 bps; Sharpe -30.19; late -12.6 bps; DSR 0.00; Binance universe -32.20 |
| S-own:k3:taker:fade:H15 | 103705 | -11.7 | -12.3 | -0.9 | -28.07 | -30.26 | 0.000 | net -11.7 bps; Sharpe -28.07; late -12.4 bps; DSR 0.00; Binance universe -30.26 |
| S-own:k3:taker:fade:H30 | 74766 | -11.8 | -12.5 | -0.9 | -24.33 | -25.97 | 0.000 | net -11.8 bps; Sharpe -24.33; late -11.9 bps; DSR 0.00; Binance universe -25.97 |
| S-own:k3:taker:fade:H60 | 48733 | -10.9 | -12.3 | -0.4 | -18.15 | -17.62 | 0.000 | net -10.9 bps; Sharpe -18.15; late -10.6 bps; DSR 0.00; Binance universe -17.62 |
| S-own:k3:taker:fade:H240 | 16189 | -10.3 | -14.8 | -0.2 | -6.51 | -7.42 | 0.000 | net -10.3 bps; Sharpe -6.51; late -6.3 bps; DSR 0.00; Binance universe -7.42 |
| S-own:k3:taker:fade:bracket | 63215 | -12.4 | -13.2 | -1.2 | -23.38 | -23.52 | 0.000 | net -12.4 bps; Sharpe -23.38; late -13.1 bps; DSR 0.00; Binance universe -23.52 |
| S-own:k4:none:cont:H1 | 114061 | -13.7 | -14.3 | -1.8 | -32.00 | -34.76 | 0.000 | net -13.7 bps; Sharpe -32.00; late -12.4 bps; DSR 0.00; Binance universe -34.76 |
| S-own:k4:none:cont:H5 | 86445 | -14.1 | -15.0 | -2.0 | -25.70 | -27.22 | 0.000 | net -14.1 bps; Sharpe -25.70; late -12.9 bps; DSR 0.00; Binance universe -27.22 |
| S-own:k4:none:cont:H15 | 64442 | -14.3 | -15.5 | -2.2 | -21.00 | -21.70 | 0.000 | net -14.3 bps; Sharpe -21.00; late -13.1 bps; DSR 0.00; Binance universe -21.70 |
| S-own:k4:none:cont:H30 | 50427 | -14.5 | -16.3 | -2.2 | -14.69 | -16.68 | 0.000 | net -14.5 bps; Sharpe -14.69; late -13.4 bps; DSR 0.00; Binance universe -16.68 |
| S-own:k4:none:cont:H60 | 36669 | -15.2 | -17.1 | -2.6 | -13.23 | -11.94 | 0.000 | net -15.2 bps; Sharpe -13.23; late -14.2 bps; DSR 0.00; Binance universe -11.94 |
| S-own:k4:none:cont:H240 | 14801 | -9.7 | -14.3 | 0.2 | -4.70 | -4.50 | 0.000 | net -9.7 bps; Sharpe -4.70; late -9.3 bps; DSR 0.00; Binance universe -4.50 |
| S-own:k4:none:cont:bracket | 52479 | -14.9 | -16.3 | -2.5 | -21.18 | -20.96 | 0.000 | net -14.9 bps; Sharpe -21.18; late -13.2 bps; DSR 0.00; Binance universe -20.96 |
| S-own:k4:none:fade:H1 | 114061 | -11.0 | -11.4 | -0.5 | -30.40 | -33.45 | 0.000 | net -11.0 bps; Sharpe -30.40; late -12.2 bps; DSR 0.00; Binance universe -33.45 |
| S-own:k4:none:fade:H5 | 89908 | -10.7 | -11.3 | -0.3 | -23.78 | -26.20 | 0.000 | net -10.7 bps; Sharpe -23.78; late -12.2 bps; DSR 0.00; Binance universe -26.20 |
| S-own:k4:none:fade:H15 | 67142 | -10.4 | -11.4 | -0.2 | -21.13 | -23.57 | 0.000 | net -10.4 bps; Sharpe -21.13; late -11.4 bps; DSR 0.00; Binance universe -23.57 |
| S-own:k4:none:fade:H30 | 52170 | -10.0 | -11.4 | 0.0 | -16.86 | -18.75 | 0.000 | net -10.0 bps; Sharpe -16.86; late -11.7 bps; DSR 0.00; Binance universe -18.75 |
| S-own:k4:none:fade:H60 | 37708 | -9.9 | -11.8 | 0.1 | -12.47 | -12.96 | 0.000 | net -9.9 bps; Sharpe -12.47; late -9.5 bps; DSR 0.00; Binance universe -12.96 |
| S-own:k4:none:fade:H240 | 15040 | -9.3 | -16.6 | 0.3 | -5.72 | -4.66 | 0.000 | net -9.3 bps; Sharpe -5.72; late -8.7 bps; DSR 0.00; Binance universe -4.66 |
| S-own:k4:none:fade:bracket | 54228 | -11.6 | -12.8 | -0.8 | -17.41 | -18.75 | 0.000 | net -11.6 bps; Sharpe -17.41; late -12.6 bps; DSR 0.00; Binance universe -18.75 |
| S-own:k4:vol:cont:H1 | 49954 | -13.3 | -14.2 | -1.6 | -26.32 | -29.03 | 0.000 | net -13.3 bps; Sharpe -26.32; late -11.9 bps; DSR 0.00; Binance universe -29.03 |
| S-own:k4:vol:cont:H5 | 39278 | -13.4 | -15.1 | -1.7 | -16.94 | -17.84 | 0.000 | net -13.4 bps; Sharpe -16.94; late -12.0 bps; DSR 0.00; Binance universe -17.84 |
| S-own:k4:vol:cont:H15 | 32082 | -14.6 | -16.2 | -2.3 | -13.66 | -13.85 | 0.000 | net -14.6 bps; Sharpe -13.66; late -13.0 bps; DSR 0.00; Binance universe -13.85 |
| S-own:k4:vol:cont:H30 | 27729 | -13.0 | -15.8 | -1.5 | -7.84 | -8.40 | 0.000 | net -13.0 bps; Sharpe -7.84; late -11.3 bps; DSR 0.00; Binance universe -8.40 |
| S-own:k4:vol:cont:H60 | 22914 | -12.9 | -15.7 | -1.4 | -7.28 | -7.64 | 0.000 | net -12.9 bps; Sharpe -7.28; late -12.1 bps; DSR 0.00; Binance universe -7.64 |
| S-own:k4:vol:cont:H240 | 12165 | -13.8 | -19.1 | -1.9 | -3.76 | -3.53 | 0.000 | net -13.8 bps; Sharpe -3.76; late -13.9 bps; DSR 0.00; Binance universe -3.53 |
| S-own:k4:vol:cont:bracket | 32151 | -12.9 | -14.7 | -1.4 | -14.34 | -14.84 | 0.000 | net -12.9 bps; Sharpe -14.34; late -11.6 bps; DSR 0.00; Binance universe -14.84 |
| S-own:k4:vol:fade:H1 | 49954 | -10.2 | -10.9 | -0.1 | -24.43 | -27.06 | 0.000 | net -10.2 bps; Sharpe -24.43; late -11.5 bps; DSR 0.00; Binance universe -27.06 |
| S-own:k4:vol:fade:H5 | 42022 | -9.8 | -11.0 | 0.1 | -17.71 | -18.91 | 0.000 | net -9.8 bps; Sharpe -17.71; late -11.3 bps; DSR 0.00; Binance universe -18.91 |
| S-own:k4:vol:fade:H15 | 34496 | -8.6 | -10.4 | 0.7 | -14.11 | -14.92 | 0.000 | net -8.6 bps; Sharpe -14.11; late -10.4 bps; DSR 0.00; Binance universe -14.92 |
| S-own:k4:vol:fade:H30 | 29436 | -9.7 | -12.6 | 0.1 | -11.59 | -12.06 | 0.000 | net -9.7 bps; Sharpe -11.59; late -11.5 bps; DSR 0.00; Binance universe -12.06 |
| S-own:k4:vol:fade:H60 | 24077 | -10.9 | -14.0 | -0.5 | -9.77 | -9.40 | 0.000 | net -10.9 bps; Sharpe -9.77; late -8.3 bps; DSR 0.00; Binance universe -9.40 |
| S-own:k4:vol:fade:H240 | 12491 | -9.2 | -15.7 | 0.4 | -4.83 | -4.56 | 0.000 | net -9.2 bps; Sharpe -4.83; late -5.4 bps; DSR 0.00; Binance universe -4.56 |
| S-own:k4:vol:fade:bracket | 34411 | -11.9 | -13.6 | -0.9 | -13.56 | -14.69 | 0.000 | net -11.9 bps; Sharpe -13.56; late -13.4 bps; DSR 0.00; Binance universe -14.69 |
| S-own:k4:taker:cont:H1 | 61376 | -13.4 | -14.2 | -1.7 | -28.83 | -30.65 | 0.000 | net -13.4 bps; Sharpe -28.83; late -12.6 bps; DSR 0.00; Binance universe -30.65 |
| S-own:k4:taker:cont:H5 | 53771 | -14.2 | -15.0 | -2.1 | -24.96 | -25.82 | 0.000 | net -14.2 bps; Sharpe -24.96; late -12.9 bps; DSR 0.00; Binance universe -25.82 |
| S-own:k4:taker:cont:H15 | 44609 | -14.2 | -15.2 | -2.1 | -20.69 | -22.07 | 0.000 | net -14.2 bps; Sharpe -20.69; late -13.2 bps; DSR 0.00; Binance universe -22.07 |
| S-own:k4:taker:cont:H30 | 37215 | -14.0 | -15.6 | -2.0 | -15.99 | -17.10 | 0.000 | net -14.0 bps; Sharpe -15.99; late -13.2 bps; DSR 0.00; Binance universe -17.10 |
| S-own:k4:taker:cont:H60 | 28837 | -13.9 | -15.6 | -1.9 | -13.19 | -13.81 | 0.000 | net -13.9 bps; Sharpe -13.19; late -13.6 bps; DSR 0.00; Binance universe -13.81 |
| S-own:k4:taker:cont:H240 | 13355 | -14.1 | -18.4 | -2.1 | -5.96 | -5.07 | 0.000 | net -14.1 bps; Sharpe -5.96; late -13.8 bps; DSR 0.00; Binance universe -5.07 |
| S-own:k4:taker:cont:bracket | 37317 | -13.5 | -15.0 | -1.8 | -18.41 | -19.83 | 0.000 | net -13.5 bps; Sharpe -18.41; late -13.0 bps; DSR 0.00; Binance universe -19.83 |
| S-own:k4:taker:fade:H1 | 61376 | -11.5 | -11.8 | -0.7 | -27.78 | -29.30 | 0.000 | net -11.5 bps; Sharpe -27.78; late -12.6 bps; DSR 0.00; Binance universe -29.30 |
| S-own:k4:taker:fade:H5 | 55126 | -11.2 | -11.8 | -0.6 | -21.80 | -23.47 | 0.000 | net -11.2 bps; Sharpe -21.80; late -12.1 bps; DSR 0.00; Binance universe -23.47 |
| S-own:k4:taker:fade:H15 | 45845 | -11.7 | -12.5 | -0.8 | -19.53 | -21.33 | 0.000 | net -11.7 bps; Sharpe -19.53; late -12.2 bps; DSR 0.00; Binance universe -21.33 |
| S-own:k4:taker:fade:H30 | 38111 | -11.4 | -12.6 | -0.7 | -16.48 | -17.91 | 0.000 | net -11.4 bps; Sharpe -16.48; late -11.1 bps; DSR 0.00; Binance universe -17.91 |
| S-own:k4:taker:fade:H60 | 29456 | -10.8 | -12.8 | -0.4 | -13.11 | -14.09 | 0.000 | net -10.8 bps; Sharpe -13.11; late -9.7 bps; DSR 0.00; Binance universe -14.09 |
| S-own:k4:taker:fade:H240 | 13479 | -7.9 | -13.0 | 1.0 | -5.27 | -6.21 | 0.000 | net -7.9 bps; Sharpe -5.27; late -8.3 bps; DSR 0.00; Binance universe -6.21 |
| S-own:k4:taker:fade:bracket | 38291 | -12.1 | -13.3 | -1.1 | -16.64 | -17.76 | 0.000 | net -12.1 bps; Sharpe -16.64; late -13.0 bps; DSR 0.00; Binance universe -17.76 |
| S-own:k6:none:cont:H1 | 28703 | -12.8 | -15.0 | -1.4 | -17.86 | -21.06 | 0.000 | net -12.8 bps; Sharpe -17.86; late -11.2 bps; DSR 0.00; Binance universe -21.06 |
| S-own:k6:none:cont:H5 | 23987 | -14.3 | -16.4 | -2.1 | -13.01 | -14.21 | 0.000 | net -14.3 bps; Sharpe -13.01; late -12.1 bps; DSR 0.00; Binance universe -14.21 |
| S-own:k6:none:cont:H15 | 19959 | -15.6 | -17.9 | -2.8 | -10.47 | -11.05 | 0.000 | net -15.6 bps; Sharpe -10.47; late -12.8 bps; DSR 0.00; Binance universe -11.05 |
| S-own:k6:none:cont:H30 | 17601 | -12.3 | -16.7 | -1.2 | -5.30 | -5.85 | 0.000 | net -12.3 bps; Sharpe -5.30; late -9.9 bps; DSR 0.00; Binance universe -5.85 |
| S-own:k6:none:cont:H60 | 15079 | -13.1 | -16.7 | -1.5 | -5.04 | -5.08 | 0.000 | net -13.1 bps; Sharpe -5.04; late -11.2 bps; DSR 0.00; Binance universe -5.08 |
| S-own:k6:none:cont:H240 | 9453 | -12.1 | -18.5 | -1.0 | -2.36 | -2.27 | 0.000 | net -12.1 bps; Sharpe -2.36; late -11.1 bps; DSR 0.00; Binance universe -2.27 |
| S-own:k6:none:cont:bracket | 21732 | -13.6 | -16.2 | -1.8 | -12.34 | -12.62 | 0.000 | net -13.6 bps; Sharpe -12.34; late -11.1 bps; DSR 0.00; Binance universe -12.62 |
| S-own:k6:none:fade:H1 | 28703 | -9.0 | -9.8 | 0.5 | -17.28 | -19.81 | 0.000 | net -9.0 bps; Sharpe -17.28; late -11.0 bps; DSR 0.00; Binance universe -19.81 |
| S-own:k6:none:fade:H5 | 25333 | -8.0 | -9.7 | 1.0 | -11.87 | -13.50 | 0.000 | net -8.0 bps; Sharpe -11.87; late -11.2 bps; DSR 0.00; Binance universe -13.50 |
| S-own:k6:none:fade:H15 | 21617 | -7.7 | -10.5 | 1.2 | -10.45 | -11.81 | 0.000 | net -7.7 bps; Sharpe -10.45; late -11.0 bps; DSR 0.00; Binance universe -11.81 |
| S-own:k6:none:fade:H30 | 18928 | -9.4 | -13.0 | 0.3 | -9.35 | -10.68 | 0.000 | net -9.4 bps; Sharpe -9.35; late -12.5 bps; DSR 0.00; Binance universe -10.68 |
| S-own:k6:none:fade:H60 | 16059 | -11.8 | -15.6 | -0.9 | -8.38 | -9.23 | 0.000 | net -11.8 bps; Sharpe -8.38; late -8.6 bps; DSR 0.00; Binance universe -9.23 |
| S-own:k6:none:fade:H240 | 9782 | -7.1 | -15.5 | 1.5 | -4.02 | -4.52 | 0.000 | net -7.1 bps; Sharpe -4.02; late -5.7 bps; DSR 0.00; Binance universe -4.52 |
| S-own:k6:none:fade:bracket | 22505 | -12.4 | -14.6 | -1.2 | -10.61 | -12.41 | 0.000 | net -12.4 bps; Sharpe -10.61; late -14.3 bps; DSR 0.00; Binance universe -12.41 |
| S-own:k6:vol:cont:H1 | 21644 | -13.0 | -15.2 | -1.5 | -16.49 | -19.27 | 0.000 | net -13.0 bps; Sharpe -16.49; late -11.0 bps; DSR 0.00; Binance universe -19.27 |
| S-own:k6:vol:cont:H5 | 18130 | -14.1 | -17.0 | -2.1 | -9.29 | -10.66 | 0.000 | net -14.1 bps; Sharpe -9.29; late -11.8 bps; DSR 0.00; Binance universe -10.66 |
| S-own:k6:vol:cont:H15 | 15357 | -15.8 | -18.8 | -2.9 | -7.75 | -8.03 | 0.000 | net -15.8 bps; Sharpe -7.75; late -12.8 bps; DSR 0.00; Binance universe -8.03 |
| S-own:k6:vol:cont:H30 | 13811 | -11.5 | -17.2 | -0.7 | -4.09 | -4.51 | 0.000 | net -11.5 bps; Sharpe -4.09; late -9.6 bps; DSR 0.00; Binance universe -4.51 |
| S-own:k6:vol:cont:H60 | 12230 | -13.0 | -17.3 | -1.5 | -4.13 | -4.16 | 0.000 | net -13.0 bps; Sharpe -4.13; late -10.8 bps; DSR 0.00; Binance universe -4.16 |
| S-own:k6:vol:cont:H240 | 8392 | -13.2 | -20.5 | -1.6 | -2.29 | -2.24 | 0.000 | net -13.2 bps; Sharpe -2.29; late -10.8 bps; DSR 0.00; Binance universe -2.24 |
| S-own:k6:vol:cont:bracket | 17310 | -13.5 | -16.3 | -1.8 | -10.66 | -10.88 | 0.000 | net -13.5 bps; Sharpe -10.66; late -11.0 bps; DSR 0.00; Binance universe -10.88 |
| S-own:k6:vol:fade:H1 | 21644 | -8.5 | -9.5 | 0.8 | -14.92 | -16.94 | 0.000 | net -8.5 bps; Sharpe -14.92; late -10.6 bps; DSR 0.00; Binance universe -16.94 |
| S-own:k6:vol:fade:H5 | 19358 | -7.1 | -9.3 | 1.5 | -9.96 | -11.09 | 0.000 | net -7.1 bps; Sharpe -9.96; late -10.0 bps; DSR 0.00; Binance universe -11.09 |
| S-own:k6:vol:fade:H15 | 16914 | -5.9 | -9.1 | 2.1 | -8.09 | -8.95 | 0.000 | net -5.9 bps; Sharpe -8.09; late -9.7 bps; DSR 0.00; Binance universe -8.95 |
| S-own:k6:vol:fade:H30 | 15097 | -7.2 | -12.1 | 1.4 | -7.47 | -8.05 | 0.000 | net -7.2 bps; Sharpe -7.47; late -11.2 bps; DSR 0.00; Binance universe -8.05 |
| S-own:k6:vol:fade:H60 | 13132 | -9.2 | -14.1 | 0.4 | -6.57 | -7.23 | 0.000 | net -9.2 bps; Sharpe -6.57; late -6.2 bps; DSR 0.00; Binance universe -7.23 |
| S-own:k6:vol:fade:H240 | 8690 | -7.3 | -15.5 | 1.4 | -3.55 | -3.65 | 0.000 | net -7.3 bps; Sharpe -3.55; late -3.4 bps; DSR 0.00; Binance universe -3.65 |
| S-own:k6:vol:fade:bracket | 18111 | -11.1 | -13.5 | -0.6 | -9.33 | -10.90 | 0.000 | net -11.1 bps; Sharpe -9.33; late -14.1 bps; DSR 0.00; Binance universe -10.90 |
| S-own:k6:taker:cont:H1 | 12731 | -11.6 | -14.7 | -0.8 | -14.13 | -15.14 | 0.000 | net -11.6 bps; Sharpe -14.13; late -11.0 bps; DSR 0.00; Binance universe -15.14 |
| S-own:k6:taker:cont:H5 | 11933 | -13.6 | -16.0 | -1.8 | -10.86 | -12.77 | 0.000 | net -13.6 bps; Sharpe -10.86; late -11.2 bps; DSR 0.00; Binance universe -12.77 |
| S-own:k6:taker:cont:H15 | 10972 | -14.8 | -17.1 | -2.4 | -8.67 | -10.25 | 0.000 | net -14.8 bps; Sharpe -8.67; late -13.0 bps; DSR 0.00; Binance universe -10.25 |
| S-own:k6:taker:cont:H30 | 10187 | -10.4 | -15.3 | -0.2 | -5.01 | -5.69 | 0.000 | net -10.4 bps; Sharpe -5.01; late -8.3 bps; DSR 0.00; Binance universe -5.69 |
| S-own:k6:taker:cont:H60 | 9240 | -11.3 | -15.6 | -0.6 | -4.24 | -4.80 | 0.000 | net -11.3 bps; Sharpe -4.24; late -11.0 bps; DSR 0.00; Binance universe -4.80 |
| S-own:k6:taker:cont:H240 | 6713 | -18.5 | -25.1 | -4.3 | -2.65 | -2.91 | 0.000 | net -18.5 bps; Sharpe -2.65; late -16.9 bps; DSR 0.00; Binance universe -2.91 |
| S-own:k6:taker:cont:bracket | 11228 | -11.7 | -15.1 | -0.8 | -8.86 | -10.03 | 0.000 | net -11.7 bps; Sharpe -8.86; late -11.4 bps; DSR 0.00; Binance universe -10.03 |
| S-own:k6:taker:fade:H1 | 12731 | -9.9 | -10.9 | 0.0 | -15.35 | -16.43 | 0.000 | net -9.9 bps; Sharpe -15.35; late -12.5 bps; DSR 0.00; Binance universe -16.43 |
| S-own:k6:taker:fade:H5 | 12348 | -9.3 | -11.2 | 0.3 | -11.01 | -11.63 | 0.000 | net -9.3 bps; Sharpe -11.01; late -10.5 bps; DSR 0.00; Binance universe -11.63 |
| S-own:k6:taker:fade:H15 | 11510 | -10.2 | -12.0 | -0.1 | -10.13 | -10.65 | 0.000 | net -10.2 bps; Sharpe -10.13; late -10.7 bps; DSR 0.00; Binance universe -10.65 |
| S-own:k6:taker:fade:H30 | 10655 | -11.0 | -13.6 | -0.5 | -8.68 | -9.02 | 0.000 | net -11.0 bps; Sharpe -8.68; late -8.2 bps; DSR 0.00; Binance universe -9.02 |
| S-own:k6:taker:fade:H60 | 9638 | -8.8 | -13.6 | 0.6 | -6.98 | -7.30 | 0.000 | net -8.8 bps; Sharpe -6.98; late -4.8 bps; DSR 0.00; Binance universe -7.30 |
| S-own:k6:taker:fade:H240 | 6852 | -0.7 | -10.3 | 4.6 | -3.38 | -3.54 | 0.000 | net -0.7 bps; Sharpe -3.38; DSR 0.00; Binance universe -3.54 |
| S-own:k6:taker:fade:bracket | 11556 | -13.3 | -15.6 | -1.6 | -9.85 | -10.09 | 0.000 | net -13.3 bps; Sharpe -9.85; late -15.4 bps; DSR 0.00; Binance universe -10.09 |
| S-lead:k3:H1 | 45446 | -12.7 | -13.2 | -1.3 | -20.67 | -21.95 | 0.000 | net -12.7 bps; Sharpe -20.67; late -13.6 bps; DSR 0.00; Binance universe -21.95 |
| S-lead:k3:H5 | 35697 | -12.6 | -14.1 | -1.3 | -18.87 | -18.97 | 0.000 | net -12.6 bps; Sharpe -18.87; late -14.3 bps; DSR 0.00; Binance universe -18.97 |
| S-lead:k3:H15 | 27036 | -11.4 | -13.8 | -0.7 | -12.58 | -12.22 | 0.000 | net -11.4 bps; Sharpe -12.58; late -12.6 bps; DSR 0.00; Binance universe -12.22 |
| S-lead:k3:H30 | 21651 | -11.8 | -14.5 | -0.9 | -9.51 | -9.71 | 0.000 | net -11.8 bps; Sharpe -9.51; late -12.9 bps; DSR 0.00; Binance universe -9.71 |
| S-lead:k3:H60 | 16421 | -15.7 | -18.8 | -2.8 | -7.63 | -7.63 | 0.000 | net -15.7 bps; Sharpe -7.63; late -16.4 bps; DSR 0.00; Binance universe -7.63 |
| S-lead:k3:H240 | 8538 | -16.9 | -24.1 | -3.5 | -3.29 | -2.57 | 0.000 | net -16.9 bps; Sharpe -3.29; late -17.7 bps; DSR 0.00; Binance universe -2.57 |
| S-lead:k4:H1 | 14441 | -11.7 | -13.0 | -0.8 | -14.22 | -15.63 | 0.000 | net -11.7 bps; Sharpe -14.22; late -12.9 bps; DSR 0.00; Binance universe -15.63 |
| S-lead:k4:H5 | 12163 | -8.7 | -12.7 | 0.7 | -9.92 | -9.35 | 0.000 | net -8.7 bps; Sharpe -9.92; late -12.5 bps; DSR 0.00; Binance universe -9.35 |
| S-lead:k4:H15 | 10222 | -8.8 | -14.0 | 0.6 | -5.73 | -5.43 | 0.000 | net -8.8 bps; Sharpe -5.73; late -10.7 bps; DSR 0.00; Binance universe -5.43 |
| S-lead:k4:H30 | 8854 | -11.4 | -17.1 | -0.7 | -4.65 | -3.63 | 0.000 | net -11.4 bps; Sharpe -4.65; late -12.9 bps; DSR 0.00; Binance universe -3.63 |
| S-lead:k4:H60 | 7505 | -14.7 | -19.4 | -2.4 | -4.23 | -3.98 | 0.000 | net -14.7 bps; Sharpe -4.23; late -16.4 bps; DSR 0.00; Binance universe -3.98 |
| S-lead:k4:H240 | 5032 | -15.3 | -26.6 | -2.6 | -1.78 | -0.82 | 0.000 | net -15.3 bps; Sharpe -1.78; late -19.2 bps; DSR 0.00; Binance universe -0.82 |
| S-lead:k6:H1 | 2329 | -9.6 | -13.4 | 0.2 | -6.46 | -7.44 | 0.000 | net -9.6 bps; Sharpe -6.46; late -13.2 bps; DSR 0.00; Binance universe -7.44 |
| S-lead:k6:H5 | 2066 | -0.7 | -12.8 | 4.7 | -2.61 | -2.23 | 0.000 | net -0.7 bps; Sharpe -2.61; late -4.9 bps; DSR 0.00; Binance universe -2.23 |
| S-lead:k6:H15 | 1883 | -0.6 | -15.1 | 4.7 | -1.97 | -2.05 | 0.000 | net -0.6 bps; Sharpe -1.97; DSR 0.00; Binance universe -2.05 |
| S-lead:k6:H30 | 1766 | -2.0 | -20.8 | 4.0 | -1.54 | -1.01 | 0.000 | net -2.0 bps; Sharpe -1.54; late -0.3 bps; DSR 0.00; Binance universe -1.01 |
| S-lead:k6:H60 | 1636 | -4.3 | -16.3 | 2.8 | -0.53 | -1.02 | 0.000 | net -4.3 bps; Sharpe -0.53; late -2.6 bps; DSR 0.00; Binance universe -1.02 |
| S-lead:k6:H240 | 1390 | -9.1 | -34.5 | 0.4 | 0.60 | 0.21 | 0.001 | net -9.1 bps; late -10.7 bps; DSR 0.00 |
| D-orb:utc30:A | 2802 | -19.4 | -40.9 | -4.7 | -1.01 | -0.23 | 0.000 | net -19.4 bps; Sharpe -1.01; late -16.4 bps; DSR 0.00; Binance universe -0.23 |
| D-orb:utc30:B | 2829 | -13.0 | -33.3 | -1.5 | -0.85 | -0.41 | 0.000 | net -13.0 bps; Sharpe -0.85; late -12.3 bps; DSR 0.00; Binance universe -0.41 |
| D-orb:utc60:A | 2888 | -36.9 | -55.8 | -13.5 | -2.14 | -2.32 | 0.000 | net -36.9 bps; Sharpe -2.14; late -37.6 bps; DSR 0.00; Binance universe -2.32 |
| D-orb:utc60:B | 2967 | -38.0 | -52.2 | -14.0 | -3.07 | -3.07 | 0.000 | net -38.0 bps; Sharpe -3.07; late -38.8 bps; DSR 0.00; Binance universe -3.07 |
| D-orb:us30:A | 2821 | -2.8 | -22.1 | 3.6 | -0.11 | 0.11 | 0.000 | net -2.8 bps; Sharpe -0.11; late -0.8 bps; DSR 0.00 |
| D-orb:us30:B | 3030 | -9.6 | -24.9 | 0.2 | -1.18 | -1.44 | 0.000 | net -9.6 bps; Sharpe -1.18; late -8.0 bps; DSR 0.00; Binance universe -1.44 |
| D-orb:us60:A | 2877 | -3.9 | -20.9 | 3.0 | -0.10 | 0.08 | 0.000 | net -3.9 bps; Sharpe -0.10; late -3.2 bps; DSR 0.00 |
| D-orb:us60:B | 3202 | -14.0 | -25.2 | -2.0 | -1.49 | -1.21 | 0.000 | net -14.0 bps; Sharpe -1.49; late -12.5 bps; DSR 0.00; Binance universe -1.21 |
| D-prev:A | 3840 | -23.0 | -41.1 | -6.5 | -1.47 | -1.22 | 0.000 | net -23.0 bps; Sharpe -1.47; late -23.2 bps; DSR 0.00; Binance universe -1.22 |
| D-prev:B | 4709 | -25.3 | -37.5 | -7.6 | -2.24 | -2.19 | 0.000 | net -25.3 bps; Sharpe -2.24; late -23.7 bps; DSR 0.00; Binance universe -2.19 |
| D-vwap:m0.25 | 7143 | -12.4 | -20.8 | -1.2 | -2.77 | -2.65 | 0.000 | net -12.4 bps; Sharpe -2.77; late -14.6 bps; DSR 0.00; Binance universe -2.65 |
| D-vwap:m0.5 | 4427 | -10.2 | -21.7 | -0.1 | -1.52 | -2.30 | 0.000 | net -10.2 bps; Sharpe -1.52; late -13.9 bps; DSR 0.00; Binance universe -2.30 |
| P-gbm:H15:m0 | 22335 | -8.6 | -11.4 | 0.7 | -6.32 | -8.04 | 0.000 | net -8.6 bps; Sharpe -6.32; late -11.5 bps; DSR 0.00; Binance universe -8.04 |
| P-gbm:H15:m5 | 10920 | -5.9 | -10.6 | 2.1 | -3.40 | -4.61 | 0.000 | net -5.9 bps; Sharpe -3.40; late -10.2 bps; DSR 0.00; Binance universe -4.61 |
| P-gbm:H15:m10 | 6117 | 0.6 | -7.0 | 5.3 | -1.06 | -2.88 | 0.000 | band 5 % -7.0 bps; Sharpe -1.06; late -6.2 bps; DSR 0.00; Binance universe -2.88 |
| P-gbm:H15:m20 | 2376 | 12.3 | -5.0 | 11.1 | 1.01 | -0.31 | 0.004 | band 5 % -5.0 bps; late -1.6 bps; DSR 0.00; Binance universe -0.31 |
| P-gbm:H60:m0 | 36793 | -9.2 | -11.9 | 0.4 | -5.41 | -5.14 | 0.000 | net -9.2 bps; Sharpe -5.41; late -9.3 bps; DSR 0.00; Binance universe -5.14 |
| P-gbm:H60:m5 | 24985 | -7.7 | -11.3 | 1.2 | -4.00 | -4.11 | 0.000 | net -7.7 bps; Sharpe -4.00; late -7.8 bps; DSR 0.00; Binance universe -4.11 |
| P-gbm:H60:m10 | 17417 | -7.7 | -12.1 | 1.1 | -3.32 | -3.79 | 0.000 | net -7.7 bps; Sharpe -3.32; late -7.8 bps; DSR 0.00; Binance universe -3.79 |
| P-gbm:H60:m20 | 8877 | -4.6 | -12.0 | 2.7 | -2.57 | -3.55 | 0.000 | net -4.6 bps; Sharpe -2.57; late -4.6 bps; DSR 0.00; Binance universe -3.55 |

## One minute late (Hyperliquid taker)

| rule | trades | net bps | band 5 % | break-even fee | Sharpe OOS | Binance univ. | DSR | fails |
|---|---|---|---|---|---|---|---|---|
| S-own:k3:none:cont:H1 | 299025 | -11.8 | -12.0 | -1.4 | -38.38 | -41.36 | 0.000 | net -11.8 bps; Sharpe -38.38; DSR 0.00; Binance universe -41.36 |
| S-own:k3:none:cont:H5 | 200169 | -12.2 | -12.7 | -1.6 | -35.46 | -38.73 | 0.000 | net -12.2 bps; Sharpe -35.46; DSR 0.00; Binance universe -38.73 |
| S-own:k3:none:cont:H15 | 127943 | -12.8 | -13.6 | -1.9 | -30.50 | -34.22 | 0.000 | net -12.8 bps; Sharpe -30.50; DSR 0.00; Binance universe -34.22 |
| S-own:k3:none:cont:H30 | 86528 | -12.6 | -13.8 | -1.8 | -21.02 | -22.32 | 0.000 | net -12.6 bps; Sharpe -21.02; DSR 0.00; Binance universe -22.32 |
| S-own:k3:none:cont:H60 | 53341 | -13.0 | -14.4 | -2.0 | -17.13 | -15.83 | 0.000 | net -13.0 bps; Sharpe -17.13; DSR 0.00; Binance universe -15.83 |
| S-own:k3:none:cont:H240 | 16469 | -11.4 | -15.4 | -1.2 | -4.77 | -3.29 | 0.000 | net -11.4 bps; Sharpe -4.77; DSR 0.00; Binance universe -3.29 |
| S-own:k3:none:cont:bracket | 73160 | -12.4 | -13.4 | -1.7 | -23.15 | -22.49 | 0.000 | net -12.4 bps; Sharpe -23.15; DSR 0.00; Binance universe -22.49 |
| S-own:k3:none:fade:H1 | 299025 | -11.7 | -11.9 | -1.3 | -38.52 | -41.66 | 0.000 | net -11.7 bps; Sharpe -38.52; DSR 0.00; Binance universe -41.66 |
| S-own:k3:none:fade:H5 | 202884 | -11.6 | -12.0 | -1.3 | -33.60 | -36.57 | 0.000 | net -11.6 bps; Sharpe -33.60; DSR 0.00; Binance universe -36.57 |
| S-own:k3:none:fade:H15 | 130039 | -10.6 | -11.3 | -0.8 | -28.84 | -31.23 | 0.000 | net -10.6 bps; Sharpe -28.84; DSR 0.00; Binance universe -31.23 |
| S-own:k3:none:fade:H30 | 87896 | -11.0 | -12.0 | -1.0 | -24.15 | -24.46 | 0.000 | net -11.0 bps; Sharpe -24.15; DSR 0.00; Binance universe -24.46 |
| S-own:k3:none:fade:H60 | 54028 | -8.9 | -11.6 | 0.1 | -15.57 | -13.90 | 0.000 | net -8.9 bps; Sharpe -15.57; DSR 0.00; Binance universe -13.90 |
| S-own:k3:none:fade:H240 | 16607 | -7.7 | -14.1 | 0.6 | -4.77 | -4.28 | 0.000 | net -7.7 bps; Sharpe -4.77; DSR 0.00; Binance universe -4.28 |
| S-own:k3:none:fade:bracket | 74320 | -11.9 | -13.0 | -1.4 | -21.20 | -21.22 | 0.000 | net -11.9 bps; Sharpe -21.20; DSR 0.00; Binance universe -21.22 |
| S-own:k3:vol:cont:H1 | 74496 | -11.2 | -11.9 | -1.1 | -27.65 | -29.93 | 0.000 | net -11.2 bps; Sharpe -27.65; DSR 0.00; Binance universe -29.93 |
| S-own:k3:vol:cont:H5 | 56114 | -11.3 | -12.5 | -1.1 | -19.52 | -20.77 | 0.000 | net -11.3 bps; Sharpe -19.52; DSR 0.00; Binance universe -20.77 |
| S-own:k3:vol:cont:H15 | 44859 | -12.1 | -13.5 | -1.5 | -16.58 | -17.11 | 0.000 | net -12.1 bps; Sharpe -16.58; DSR 0.00; Binance universe -17.11 |
| S-own:k3:vol:cont:H30 | 37643 | -10.9 | -13.0 | -0.9 | -9.00 | -9.59 | 0.000 | net -10.9 bps; Sharpe -9.00; DSR 0.00; Binance universe -9.59 |
| S-own:k3:vol:cont:H60 | 29678 | -11.5 | -13.7 | -1.2 | -8.48 | -8.63 | 0.000 | net -11.5 bps; Sharpe -8.48; DSR 0.00; Binance universe -8.63 |
| S-own:k3:vol:cont:H240 | 13709 | -8.9 | -13.5 | 0.1 | -3.72 | -4.18 | 0.000 | net -8.9 bps; Sharpe -3.72; DSR 0.00; Binance universe -4.18 |
| S-own:k3:vol:cont:bracket | 40404 | -11.0 | -12.5 | -1.0 | -14.22 | -14.60 | 0.000 | net -11.0 bps; Sharpe -14.22; DSR 0.00; Binance universe -14.60 |
| S-own:k3:vol:fade:H1 | 74496 | -10.7 | -11.1 | -0.8 | -31.43 | -33.39 | 0.000 | net -10.7 bps; Sharpe -31.43; DSR 0.00; Binance universe -33.39 |
| S-own:k3:vol:fade:H5 | 57821 | -10.8 | -11.7 | -0.9 | -22.88 | -23.73 | 0.000 | net -10.8 bps; Sharpe -22.88; DSR 0.00; Binance universe -23.73 |
| S-own:k3:vol:fade:H15 | 46851 | -10.0 | -11.4 | -0.5 | -17.35 | -17.92 | 0.000 | net -10.0 bps; Sharpe -17.35; DSR 0.00; Binance universe -17.92 |
| S-own:k3:vol:fade:H30 | 39206 | -10.4 | -12.2 | -0.7 | -13.67 | -13.71 | 0.000 | net -10.4 bps; Sharpe -13.67; DSR 0.00; Binance universe -13.71 |
| S-own:k3:vol:fade:H60 | 30695 | -7.6 | -11.9 | 0.7 | -9.95 | -9.70 | 0.000 | net -7.6 bps; Sharpe -9.95; DSR 0.00; Binance universe -9.70 |
| S-own:k3:vol:fade:H240 | 13971 | -7.4 | -16.3 | 0.8 | -5.56 | -3.98 | 0.000 | net -7.4 bps; Sharpe -5.56; DSR 0.00; Binance universe -3.98 |
| S-own:k3:vol:fade:bracket | 42861 | -12.0 | -13.3 | -1.5 | -14.85 | -15.76 | 0.000 | net -12.0 bps; Sharpe -14.85; DSR 0.00; Binance universe -15.76 |
| S-own:k3:taker:cont:H1 | 179074 | -11.8 | -12.1 | -1.4 | -35.61 | -37.45 | 0.000 | net -11.8 bps; Sharpe -35.61; DSR 0.00; Binance universe -37.45 |
| S-own:k3:taker:cont:H5 | 142457 | -12.2 | -12.6 | -1.6 | -33.80 | -35.69 | 0.000 | net -12.2 bps; Sharpe -33.80; DSR 0.00; Binance universe -35.69 |
| S-own:k3:taker:cont:H15 | 102057 | -12.7 | -13.3 | -1.9 | -30.72 | -32.71 | 0.000 | net -12.7 bps; Sharpe -30.72; DSR 0.00; Binance universe -32.71 |
| S-own:k3:taker:cont:H30 | 73708 | -12.3 | -13.2 | -1.6 | -23.57 | -23.89 | 0.000 | net -12.3 bps; Sharpe -23.57; DSR 0.00; Binance universe -23.89 |
| S-own:k3:taker:cont:H60 | 48159 | -12.9 | -14.2 | -2.0 | -15.87 | -18.02 | 0.000 | net -12.9 bps; Sharpe -15.87; DSR 0.00; Binance universe -18.02 |
| S-own:k3:taker:cont:H240 | 16085 | -11.7 | -15.3 | -1.3 | -4.92 | -3.54 | 0.000 | net -11.7 bps; Sharpe -4.92; DSR 0.00; Binance universe -3.54 |
| S-own:k3:taker:cont:bracket | 62096 | -12.3 | -13.2 | -1.6 | -23.22 | -24.21 | 0.000 | net -12.3 bps; Sharpe -23.22; DSR 0.00; Binance universe -24.21 |
| S-own:k3:taker:fade:H1 | 179074 | -12.0 | -12.2 | -1.5 | -35.95 | -37.75 | 0.000 | net -12.0 bps; Sharpe -35.95; DSR 0.00; Binance universe -37.75 |
| S-own:k3:taker:fade:H5 | 143882 | -11.6 | -12.0 | -1.3 | -30.38 | -32.49 | 0.000 | net -11.6 bps; Sharpe -30.38; DSR 0.00; Binance universe -32.49 |
| S-own:k3:taker:fade:H15 | 103371 | -11.4 | -12.1 | -1.2 | -27.79 | -30.14 | 0.000 | net -11.4 bps; Sharpe -27.79; DSR 0.00; Binance universe -30.14 |
| S-own:k3:taker:fade:H30 | 74590 | -10.9 | -12.1 | -0.9 | -23.69 | -25.21 | 0.000 | net -10.9 bps; Sharpe -23.69; DSR 0.00; Binance universe -25.21 |
| S-own:k3:taker:fade:H60 | 48637 | -9.6 | -12.0 | -0.3 | -17.12 | -16.13 | 0.000 | net -9.6 bps; Sharpe -17.12; DSR 0.00; Binance universe -16.13 |
| S-own:k3:taker:fade:H240 | 16176 | -5.3 | -13.2 | 1.8 | -5.58 | -6.11 | 0.000 | net -5.3 bps; Sharpe -5.58; DSR 0.00; Binance universe -6.11 |
| S-own:k3:taker:fade:bracket | 63015 | -12.1 | -12.9 | -1.6 | -23.06 | -23.07 | 0.000 | net -12.1 bps; Sharpe -23.06; DSR 0.00; Binance universe -23.07 |
| S-own:k4:none:cont:H1 | 114051 | -11.4 | -11.9 | -1.2 | -30.07 | -32.94 | 0.000 | net -11.4 bps; Sharpe -30.07; DSR 0.00; Binance universe -32.94 |
| S-own:k4:none:cont:H5 | 86130 | -11.9 | -12.8 | -1.5 | -25.18 | -28.34 | 0.000 | net -11.9 bps; Sharpe -25.18; DSR 0.00; Binance universe -28.34 |
| S-own:k4:none:cont:H15 | 64396 | -12.1 | -13.3 | -1.6 | -20.91 | -21.76 | 0.000 | net -12.1 bps; Sharpe -20.91; DSR 0.00; Binance universe -21.76 |
| S-own:k4:none:cont:H30 | 50406 | -12.4 | -14.2 | -1.7 | -13.32 | -15.24 | 0.000 | net -12.4 bps; Sharpe -13.32; DSR 0.00; Binance universe -15.24 |
| S-own:k4:none:cont:H60 | 36655 | -13.2 | -15.1 | -2.1 | -12.38 | -10.73 | 0.000 | net -13.2 bps; Sharpe -12.38; DSR 0.00; Binance universe -10.73 |
| S-own:k4:none:cont:H240 | 14796 | -8.3 | -13.3 | 0.3 | -3.81 | -3.68 | 0.000 | net -8.3 bps; Sharpe -3.81; DSR 0.00; Binance universe -3.68 |
| S-own:k4:none:cont:bracket | 51549 | -12.2 | -13.4 | -1.6 | -18.42 | -17.75 | 0.000 | net -12.2 bps; Sharpe -18.42; DSR 0.00; Binance universe -17.75 |
| S-own:k4:none:fade:H1 | 114051 | -11.2 | -11.6 | -1.1 | -33.09 | -35.60 | 0.000 | net -11.2 bps; Sharpe -33.09; DSR 0.00; Binance universe -35.60 |
| S-own:k4:none:fade:H5 | 87986 | -11.2 | -11.8 | -1.1 | -25.16 | -27.39 | 0.000 | net -11.2 bps; Sharpe -25.16; DSR 0.00; Binance universe -27.39 |
| S-own:k4:none:fade:H15 | 66374 | -10.4 | -11.5 | -0.7 | -21.09 | -23.31 | 0.000 | net -10.4 bps; Sharpe -21.09; DSR 0.00; Binance universe -23.31 |
| S-own:k4:none:fade:H30 | 51875 | -10.7 | -12.0 | -0.8 | -16.90 | -18.07 | 0.000 | net -10.7 bps; Sharpe -16.90; DSR 0.00; Binance universe -18.07 |
| S-own:k4:none:fade:H60 | 37545 | -8.5 | -12.1 | 0.2 | -11.22 | -12.22 | 0.000 | net -8.5 bps; Sharpe -11.22; DSR 0.00; Binance universe -12.22 |
| S-own:k4:none:fade:H240 | 15022 | -7.7 | -16.8 | 0.7 | -5.50 | -4.22 | 0.000 | net -7.7 bps; Sharpe -5.50; DSR 0.00; Binance universe -4.22 |
| S-own:k4:none:fade:bracket | 53019 | -11.6 | -12.9 | -1.3 | -16.80 | -17.64 | 0.000 | net -11.6 bps; Sharpe -16.80; DSR 0.00; Binance universe -17.64 |
| S-own:k4:vol:cont:H1 | 49950 | -10.9 | -11.9 | -0.9 | -21.40 | -23.76 | 0.000 | net -10.9 bps; Sharpe -21.40; DSR 0.00; Binance universe -23.76 |
| S-own:k4:vol:cont:H5 | 39002 | -11.0 | -12.7 | -1.0 | -15.03 | -16.30 | 0.000 | net -11.0 bps; Sharpe -15.03; DSR 0.00; Binance universe -16.30 |
| S-own:k4:vol:cont:H15 | 32094 | -12.0 | -13.9 | -1.5 | -13.22 | -13.49 | 0.000 | net -12.0 bps; Sharpe -13.22; DSR 0.00; Binance universe -13.49 |
| S-own:k4:vol:cont:H30 | 27714 | -10.3 | -13.1 | -0.7 | -6.75 | -7.16 | 0.000 | net -10.3 bps; Sharpe -6.75; DSR 0.00; Binance universe -7.16 |
| S-own:k4:vol:cont:H60 | 22925 | -11.1 | -13.8 | -1.0 | -6.71 | -6.84 | 0.000 | net -11.1 bps; Sharpe -6.71; DSR 0.00; Binance universe -6.84 |
| S-own:k4:vol:cont:H240 | 12163 | -12.9 | -18.2 | -2.0 | -3.15 | -3.25 | 0.000 | net -12.9 bps; Sharpe -3.15; DSR 0.00; Binance universe -3.25 |
| S-own:k4:vol:cont:bracket | 31367 | -10.6 | -12.5 | -0.8 | -11.80 | -12.02 | 0.000 | net -10.6 bps; Sharpe -11.80; DSR 0.00; Binance universe -12.02 |
| S-own:k4:vol:fade:H1 | 49950 | -10.5 | -11.1 | -0.7 | -28.39 | -29.84 | 0.000 | net -10.5 bps; Sharpe -28.39; DSR 0.00; Binance universe -29.84 |
| S-own:k4:vol:fade:H5 | 40368 | -10.3 | -11.5 | -0.7 | -18.99 | -19.63 | 0.000 | net -10.3 bps; Sharpe -18.99; DSR 0.00; Binance universe -19.63 |
| S-own:k4:vol:fade:H15 | 33862 | -9.4 | -11.3 | -0.2 | -14.67 | -15.31 | 0.000 | net -9.4 bps; Sharpe -14.67; DSR 0.00; Binance universe -15.31 |
| S-own:k4:vol:fade:H30 | 29103 | -10.5 | -12.8 | -0.7 | -11.62 | -11.81 | 0.000 | net -10.5 bps; Sharpe -11.62; DSR 0.00; Binance universe -11.81 |
| S-own:k4:vol:fade:H60 | 23903 | -7.3 | -12.8 | 0.9 | -8.56 | -8.54 | 0.000 | net -7.3 bps; Sharpe -8.56; DSR 0.00; Binance universe -8.54 |
| S-own:k4:vol:fade:H240 | 12465 | -4.4 | -14.3 | 2.3 | -4.57 | -4.07 | 0.000 | net -4.4 bps; Sharpe -4.57; DSR 0.00; Binance universe -4.07 |
| S-own:k4:vol:fade:bracket | 33368 | -12.4 | -14.1 | -1.7 | -13.20 | -14.03 | 0.000 | net -12.4 bps; Sharpe -13.20; DSR 0.00; Binance universe -14.03 |
| S-own:k4:taker:cont:H1 | 61370 | -11.6 | -12.1 | -1.3 | -28.82 | -30.57 | 0.000 | net -11.6 bps; Sharpe -28.82; DSR 0.00; Binance universe -30.57 |
| S-own:k4:taker:cont:H5 | 53802 | -11.9 | -12.8 | -1.4 | -23.99 | -25.14 | 0.000 | net -11.9 bps; Sharpe -23.99; DSR 0.00; Binance universe -25.14 |
| S-own:k4:taker:cont:H15 | 44632 | -12.2 | -13.1 | -1.6 | -21.09 | -22.48 | 0.000 | net -12.2 bps; Sharpe -21.09; DSR 0.00; Binance universe -22.48 |
| S-own:k4:taker:cont:H30 | 37217 | -12.2 | -13.8 | -1.6 | -15.77 | -16.70 | 0.000 | net -12.2 bps; Sharpe -15.77; DSR 0.00; Binance universe -16.70 |
| S-own:k4:taker:cont:H60 | 28858 | -12.6 | -14.2 | -1.8 | -12.93 | -13.27 | 0.000 | net -12.6 bps; Sharpe -12.93; DSR 0.00; Binance universe -13.27 |
| S-own:k4:taker:cont:H240 | 13347 | -12.8 | -17.1 | -1.9 | -5.46 | -4.61 | 0.000 | net -12.8 bps; Sharpe -5.46; DSR 0.00; Binance universe -4.61 |
| S-own:k4:taker:cont:bracket | 37068 | -12.0 | -13.3 | -1.5 | -17.99 | -18.72 | 0.000 | net -12.0 bps; Sharpe -17.99; DSR 0.00; Binance universe -18.72 |
| S-own:k4:taker:fade:H1 | 61370 | -11.6 | -11.9 | -1.3 | -29.54 | -31.13 | 0.000 | net -11.6 bps; Sharpe -29.54; DSR 0.00; Binance universe -31.13 |
| S-own:k4:taker:fade:H5 | 54604 | -11.1 | -11.8 | -1.0 | -23.04 | -24.67 | 0.000 | net -11.1 bps; Sharpe -23.04; DSR 0.00; Binance universe -24.67 |
| S-own:k4:taker:fade:H15 | 45613 | -11.2 | -12.4 | -1.1 | -20.07 | -21.78 | 0.000 | net -11.2 bps; Sharpe -20.07; DSR 0.00; Binance universe -21.78 |
| S-own:k4:taker:fade:H30 | 37986 | -10.1 | -12.4 | -0.5 | -16.45 | -17.74 | 0.000 | net -10.1 bps; Sharpe -16.45; DSR 0.00; Binance universe -17.74 |
| S-own:k4:taker:fade:H60 | 29380 | -8.7 | -12.6 | 0.1 | -11.73 | -12.74 | 0.000 | net -8.7 bps; Sharpe -11.73; DSR 0.00; Binance universe -12.74 |
| S-own:k4:taker:fade:H240 | 13460 | -7.3 | -12.6 | 0.8 | -4.91 | -5.53 | 0.000 | net -7.3 bps; Sharpe -4.91; DSR 0.00; Binance universe -5.53 |
| S-own:k4:taker:fade:bracket | 38158 | -12.0 | -13.1 | -1.5 | -16.35 | -17.48 | 0.000 | net -12.0 bps; Sharpe -16.35; DSR 0.00; Binance universe -17.48 |
| S-own:k6:none:cont:H1 | 28701 | -10.2 | -12.1 | -0.6 | -13.15 | -15.37 | 0.001 | net -10.2 bps; Sharpe -13.15; DSR 0.00; Binance universe -15.37 |
| S-own:k6:none:cont:H5 | 23707 | -11.1 | -13.2 | -1.1 | -11.63 | -13.29 | 0.000 | net -11.1 bps; Sharpe -11.63; DSR 0.00; Binance universe -13.29 |
| S-own:k6:none:cont:H15 | 19947 | -11.8 | -14.3 | -1.4 | -9.58 | -10.26 | 0.000 | net -11.8 bps; Sharpe -9.58; DSR 0.00; Binance universe -10.26 |
| S-own:k6:none:cont:H30 | 17584 | -8.9 | -13.1 | 0.0 | -4.50 | -4.88 | 0.000 | net -8.9 bps; Sharpe -4.50; DSR 0.00; Binance universe -4.88 |
| S-own:k6:none:cont:H60 | 15066 | -10.2 | -13.7 | -0.6 | -4.45 | -4.12 | 0.000 | net -10.2 bps; Sharpe -4.45; DSR 0.00; Binance universe -4.12 |
| S-own:k6:none:cont:H240 | 9455 | -10.1 | -16.3 | -0.6 | -1.88 | -1.88 | 0.000 | net -10.1 bps; Sharpe -1.88; DSR 0.00; Binance universe -1.88 |
| S-own:k6:none:cont:bracket | 21134 | -10.1 | -12.4 | -0.5 | -9.34 | -10.29 | 0.000 | net -10.1 bps; Sharpe -9.34; DSR 0.00; Binance universe -10.29 |
| S-own:k6:none:fade:H1 | 28701 | -10.0 | -11.1 | -0.5 | -21.59 | -23.31 | 0.000 | net -10.0 bps; Sharpe -21.59; DSR 0.00; Binance universe -23.31 |
| S-own:k6:none:fade:H5 | 24348 | -10.2 | -11.7 | -0.6 | -14.29 | -15.48 | 0.000 | net -10.2 bps; Sharpe -14.29; DSR 0.00; Binance universe -15.48 |
| S-own:k6:none:fade:H15 | 21157 | -10.0 | -12.5 | -0.5 | -12.00 | -13.06 | 0.000 | net -10.0 bps; Sharpe -12.00; DSR 0.00; Binance universe -13.06 |
| S-own:k6:none:fade:H30 | 18691 | -11.5 | -14.8 | -1.2 | -10.36 | -11.46 | 0.000 | net -11.5 bps; Sharpe -10.36; DSR 0.00; Binance universe -11.46 |
| S-own:k6:none:fade:H60 | 15921 | -7.6 | -15.3 | 0.7 | -7.97 | -9.61 | 0.000 | net -7.6 bps; Sharpe -7.97; DSR 0.00; Binance universe -9.61 |
| S-own:k6:none:fade:H240 | 9765 | -4.7 | -15.6 | 2.1 | -3.97 | -4.28 | 0.000 | net -4.7 bps; Sharpe -3.97; DSR 0.00; Binance universe -4.28 |
| S-own:k6:none:fade:bracket | 21679 | -13.3 | -15.5 | -2.1 | -11.42 | -12.87 | 0.000 | net -13.3 bps; Sharpe -11.42; DSR 0.00; Binance universe -12.87 |
| S-own:k6:vol:cont:H1 | 21644 | -10.0 | -12.1 | -0.5 | -10.90 | -12.67 | 0.001 | net -10.0 bps; Sharpe -10.90; DSR 0.00; Binance universe -12.67 |
| S-own:k6:vol:cont:H5 | 17893 | -10.8 | -13.6 | -0.9 | -8.56 | -9.35 | 0.000 | net -10.8 bps; Sharpe -8.56; DSR 0.00; Binance universe -9.35 |
| S-own:k6:vol:cont:H15 | 15345 | -11.8 | -14.8 | -1.4 | -7.12 | -7.58 | 0.000 | net -11.8 bps; Sharpe -7.12; DSR 0.00; Binance universe -7.58 |
| S-own:k6:vol:cont:H30 | 13808 | -8.6 | -13.3 | 0.2 | -3.31 | -3.67 | 0.000 | net -8.6 bps; Sharpe -3.31; DSR 0.00; Binance universe -3.67 |
| S-own:k6:vol:cont:H60 | 12222 | -9.8 | -13.7 | -0.4 | -3.72 | -3.51 | 0.000 | net -9.8 bps; Sharpe -3.72; DSR 0.00; Binance universe -3.51 |
| S-own:k6:vol:cont:H240 | 8397 | -9.8 | -16.8 | -0.4 | -1.62 | -1.49 | 0.000 | net -9.8 bps; Sharpe -1.62; DSR 0.00; Binance universe -1.49 |
| S-own:k6:vol:cont:bracket | 16759 | -10.0 | -12.7 | -0.5 | -8.27 | -8.31 | 0.000 | net -10.0 bps; Sharpe -8.27; DSR 0.00; Binance universe -8.31 |
| S-own:k6:vol:fade:H1 | 21644 | -9.6 | -10.8 | -0.3 | -19.65 | -20.65 | 0.000 | net -9.6 bps; Sharpe -19.65; DSR 0.00; Binance universe -20.65 |
| S-own:k6:vol:fade:H5 | 18493 | -9.0 | -11.2 | -0.0 | -11.81 | -12.32 | 0.000 | net -9.0 bps; Sharpe -11.81; DSR 0.00; Binance universe -12.32 |
| S-own:k6:vol:fade:H15 | 16491 | -8.7 | -11.9 | 0.2 | -9.78 | -10.24 | 0.000 | net -8.7 bps; Sharpe -9.78; DSR 0.00; Binance universe -10.24 |
| S-own:k6:vol:fade:H30 | 14896 | -10.2 | -13.8 | -0.6 | -8.16 | -8.47 | 0.000 | net -10.2 bps; Sharpe -8.16; DSR 0.00; Binance universe -8.47 |
| S-own:k6:vol:fade:H60 | 13032 | -5.2 | -14.8 | 1.9 | -6.39 | -7.13 | 0.000 | net -5.2 bps; Sharpe -6.39; DSR 0.00; Binance universe -7.13 |
| S-own:k6:vol:fade:H240 | 8666 | -2.4 | -14.7 | 3.3 | -3.08 | -3.75 | 0.000 | net -2.4 bps; Sharpe -3.08; DSR 0.00; Binance universe -3.75 |
| S-own:k6:vol:fade:bracket | 17350 | -13.1 | -15.4 | -2.0 | -9.85 | -10.69 | 0.000 | net -13.1 bps; Sharpe -9.85; DSR 0.00; Binance universe -10.69 |
| S-own:k6:taker:cont:H1 | 12731 | -10.0 | -12.0 | -0.5 | -13.20 | -14.82 | 0.000 | net -10.0 bps; Sharpe -13.20; DSR 0.00; Binance universe -14.82 |
| S-own:k6:taker:cont:H5 | 11951 | -10.2 | -13.3 | -0.6 | -9.57 | -10.59 | 0.000 | net -10.2 bps; Sharpe -9.57; DSR 0.00; Binance universe -10.59 |
| S-own:k6:taker:cont:H15 | 10981 | -12.0 | -14.2 | -1.5 | -8.81 | -9.92 | 0.000 | net -12.0 bps; Sharpe -8.81; DSR 0.00; Binance universe -9.92 |
| S-own:k6:taker:cont:H30 | 10194 | -7.3 | -12.0 | 0.8 | -4.45 | -5.00 | 0.000 | net -7.3 bps; Sharpe -4.45; DSR 0.00; Binance universe -5.00 |
| S-own:k6:taker:cont:H60 | 9254 | -10.0 | -13.8 | -0.5 | -4.29 | -4.74 | 0.000 | net -10.0 bps; Sharpe -4.29; DSR 0.00; Binance universe -4.74 |
| S-own:k6:taker:cont:H240 | 6719 | -15.9 | -22.8 | -3.4 | -2.27 | -2.47 | 0.000 | net -15.9 bps; Sharpe -2.27; DSR 0.00; Binance universe -2.47 |
| S-own:k6:taker:cont:bracket | 11172 | -10.4 | -13.2 | -0.7 | -7.92 | -8.76 | 0.000 | net -10.4 bps; Sharpe -7.92; DSR 0.00; Binance universe -8.76 |
| S-own:k6:taker:fade:H1 | 12731 | -11.5 | -12.2 | -1.3 | -18.44 | -19.54 | 0.000 | net -11.5 bps; Sharpe -18.44; DSR 0.00; Binance universe -19.54 |
| S-own:k6:taker:fade:H5 | 12144 | -9.5 | -12.1 | -0.3 | -12.14 | -12.99 | 0.000 | net -9.5 bps; Sharpe -12.14; DSR 0.00; Binance universe -12.99 |
| S-own:k6:taker:fade:H15 | 11394 | -9.7 | -12.9 | -0.4 | -10.66 | -11.28 | 0.000 | net -9.7 bps; Sharpe -10.66; DSR 0.00; Binance universe -11.28 |
| S-own:k6:taker:fade:H30 | 10636 | -7.2 | -14.3 | 0.9 | -9.11 | -9.43 | 0.000 | net -7.2 bps; Sharpe -9.11; DSR 0.00; Binance universe -9.43 |
| S-own:k6:taker:fade:H60 | 9606 | -3.8 | -14.3 | 2.6 | -6.66 | -7.27 | 0.000 | net -3.8 bps; Sharpe -6.66; DSR 0.00; Binance universe -7.27 |
| S-own:k6:taker:fade:H240 | 6831 | 2.6 | -10.1 | 5.8 | -3.03 | -3.21 | 0.000 | band 5 % -10.1 bps; Sharpe -3.03; DSR 0.00; Binance universe -3.21 |
| S-own:k6:taker:fade:bracket | 11411 | -14.4 | -16.5 | -2.7 | -10.39 | -10.84 | 0.000 | net -14.4 bps; Sharpe -10.39; DSR 0.00; Binance universe -10.84 |
| S-lead:k3:H1 | 45421 | -12.6 | -13.1 | -1.8 | -21.61 | -22.74 | 0.000 | net -12.6 bps; Sharpe -21.61; DSR 0.00; Binance universe -22.74 |
| S-lead:k3:H5 | 35715 | -13.3 | -14.4 | -2.1 | -19.71 | -19.15 | 0.000 | net -13.3 bps; Sharpe -19.71; DSR 0.00; Binance universe -19.15 |
| S-lead:k3:H15 | 27041 | -11.6 | -14.1 | -1.3 | -13.17 | -12.52 | 0.000 | net -11.6 bps; Sharpe -13.17; DSR 0.00; Binance universe -12.52 |
| S-lead:k3:H30 | 21645 | -11.9 | -14.7 | -1.4 | -9.45 | -8.24 | 0.000 | net -11.9 bps; Sharpe -9.45; DSR 0.00; Binance universe -8.24 |
| S-lead:k3:H60 | 16425 | -15.4 | -18.5 | -3.2 | -7.25 | -7.31 | 0.000 | net -15.4 bps; Sharpe -7.25; DSR 0.00; Binance universe -7.31 |
| S-lead:k3:H240 | 8539 | -16.7 | -23.9 | -3.8 | -3.23 | -2.42 | 0.000 | net -16.7 bps; Sharpe -3.23; DSR 0.00; Binance universe -2.42 |
| S-lead:k4:H1 | 14436 | -11.9 | -12.9 | -1.5 | -15.40 | -16.13 | 0.000 | net -11.9 bps; Sharpe -15.40; DSR 0.00; Binance universe -16.13 |
| S-lead:k4:H5 | 12194 | -11.5 | -13.7 | -1.3 | -11.51 | -10.08 | 0.000 | net -11.5 bps; Sharpe -11.51; DSR 0.00; Binance universe -10.08 |
| S-lead:k4:H15 | 10228 | -9.7 | -15.6 | -0.4 | -6.59 | -5.77 | 0.000 | net -9.7 bps; Sharpe -6.59; DSR 0.00; Binance universe -5.77 |
| S-lead:k4:H30 | 8860 | -11.9 | -17.5 | -1.5 | -5.08 | -3.71 | 0.000 | net -11.9 bps; Sharpe -5.08; DSR 0.00; Binance universe -3.71 |
| S-lead:k4:H60 | 7507 | -15.4 | -20.1 | -3.2 | -4.37 | -4.05 | 0.000 | net -15.4 bps; Sharpe -4.37; DSR 0.00; Binance universe -4.05 |
| S-lead:k4:H240 | 5032 | -18.2 | -29.4 | -4.6 | -2.16 | -1.07 | 0.000 | net -18.2 bps; Sharpe -2.16; DSR 0.00; Binance universe -1.07 |
| S-lead:k6:H1 | 2328 | -12.2 | -14.1 | -1.6 | -7.44 | -7.74 | 0.000 | net -12.2 bps; Sharpe -7.44; DSR 0.00; Binance universe -7.74 |
| S-lead:k6:H5 | 2078 | -3.9 | -14.1 | 2.5 | -4.38 | -2.78 | 0.000 | net -3.9 bps; Sharpe -4.38; DSR 0.00; Binance universe -2.78 |
| S-lead:k6:H15 | 1877 | 3.6 | -14.2 | 6.3 | -2.88 | -2.54 | 0.000 | band 5 % -14.2 bps; Sharpe -2.88; DSR 0.00; Binance universe -2.54 |
| S-lead:k6:H30 | 1761 | 0.7 | -17.6 | 4.9 | -1.82 | -0.96 | 0.000 | band 5 % -17.6 bps; Sharpe -1.82; DSR 0.00; Binance universe -0.96 |
| S-lead:k6:H60 | 1630 | -1.6 | -13.2 | 3.7 | -0.69 | -1.17 | 0.000 | net -1.6 bps; Sharpe -0.69; DSR 0.00; Binance universe -1.17 |
| S-lead:k6:H240 | 1388 | -9.7 | -34.8 | -0.3 | 0.50 | 0.17 | 0.000 | net -9.7 bps; DSR 0.00 |
| D-orb:utc30:A | 2798 | -15.4 | -36.4 | -3.2 | -0.80 | -0.13 | 0.000 | net -15.4 bps; Sharpe -0.80; DSR 0.00; Binance universe -0.13 |
| D-orb:utc30:B | 2829 | -11.3 | -31.0 | -1.1 | -0.73 | -0.41 | 0.000 | net -11.3 bps; Sharpe -0.73; DSR 0.00; Binance universe -0.41 |
| D-orb:utc60:A | 2892 | -36.6 | -55.1 | -13.8 | -2.14 | -2.36 | 0.000 | net -36.6 bps; Sharpe -2.14; DSR 0.00; Binance universe -2.36 |
| D-orb:utc60:B | 2973 | -37.8 | -51.8 | -14.4 | -3.11 | -3.26 | 0.000 | net -37.8 bps; Sharpe -3.11; DSR 0.00; Binance universe -3.26 |
| D-orb:us30:A | 2819 | 0.2 | -18.5 | 4.6 | 0.13 | 0.30 | 0.000 | band 5 % -18.5 bps; DSR 0.00 |
| D-orb:us30:B | 3037 | -7.0 | -21.9 | 1.0 | -0.89 | -1.18 | 0.000 | net -7.0 bps; Sharpe -0.89; DSR 0.00; Binance universe -1.18 |
| D-orb:us60:A | 2879 | -2.2 | -19.5 | 3.4 | 0.07 | 0.28 | 0.000 | net -2.2 bps; DSR 0.00 |
| D-orb:us60:B | 3214 | -11.5 | -22.8 | -1.2 | -1.20 | -1.08 | 0.000 | net -11.5 bps; Sharpe -1.20; DSR 0.00; Binance universe -1.08 |
| D-prev:A | 3837 | -22.2 | -40.5 | -6.6 | -1.47 | -1.38 | 0.000 | net -22.2 bps; Sharpe -1.47; DSR 0.00; Binance universe -1.38 |
| D-prev:B | 4702 | -22.7 | -34.6 | -6.8 | -2.07 | -1.98 | 0.000 | net -22.7 bps; Sharpe -2.07; DSR 0.00; Binance universe -1.98 |
| D-vwap:m0.25 | 7178 | -13.6 | -22.1 | -2.3 | -2.88 | -2.83 | 0.000 | net -13.6 bps; Sharpe -2.88; DSR 0.00; Binance universe -2.83 |
| D-vwap:m0.5 | 4448 | -12.9 | -24.6 | -2.0 | -1.80 | -2.56 | 0.000 | net -12.9 bps; Sharpe -1.80; DSR 0.00; Binance universe -2.56 |
| P-gbm:H15:m0 | 22335 | -10.5 | -13.5 | -0.8 | -7.11 | -8.47 | 0.000 | net -10.5 bps; Sharpe -7.11; DSR 0.00; Binance universe -8.47 |
| P-gbm:H15:m5 | 10920 | -9.2 | -13.9 | -0.1 | -4.26 | -5.00 | 0.000 | net -9.2 bps; Sharpe -4.26; DSR 0.00; Binance universe -5.00 |
| P-gbm:H15:m10 | 6117 | -5.2 | -12.5 | 1.9 | -2.38 | -3.52 | 0.000 | net -5.2 bps; Sharpe -2.38; DSR 0.00; Binance universe -3.52 |
| P-gbm:H15:m20 | 2376 | -0.6 | -18.2 | 4.2 | -0.74 | -1.33 | 0.000 | net -0.6 bps; Sharpe -0.74; DSR 0.00; Binance universe -1.33 |
| P-gbm:H60:m0 | 36791 | -8.3 | -11.2 | 0.3 | -4.87 | -4.65 | 0.000 | net -8.3 bps; Sharpe -4.87; DSR 0.00; Binance universe -4.65 |
| P-gbm:H60:m5 | 24981 | -6.8 | -10.5 | 1.1 | -3.73 | -3.45 | 0.000 | net -6.8 bps; Sharpe -3.73; DSR 0.00; Binance universe -3.45 |
| P-gbm:H60:m10 | 17410 | -6.8 | -11.4 | 1.1 | -3.13 | -3.33 | 0.000 | net -6.8 bps; Sharpe -3.13; DSR 0.00; Binance universe -3.33 |
| P-gbm:H60:m20 | 8868 | -3.6 | -11.3 | 2.7 | -2.27 | -3.49 | 0.000 | net -3.6 bps; Sharpe -2.27; DSR 0.00; Binance universe -3.49 |

## Notes

- Equal risk: 0.25 % of equity at the stop, at most 1x equity a position and 5 positions; a book's Sharpe is over every day of the window, flat days as 0.
- Slippage: 1 bp for the day's top 20 by 30-day volume, more by the Abdi-Ranaldo spread proxy for the rest (median over traded rules 1.4 bps a side).
- Funding at its settlements (Hyperliquid's hourly rates on the Hyperliquid universe, Binance's on the Binance universe); intraday it is small: 0.8 bps per trade at most among the base-case rules.
- Optional features: `book20` starts 2026-09-30 (inside the lockbox) and `um_metrics` holds 20 symbols from 2023-05: neither used.
- Kraken Futures listing (opening time, today's list): 88 % median share of the Hyperliquid trades in coins Kraken Futures lists.
