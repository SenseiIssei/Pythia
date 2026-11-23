# m4_perps forward record audit, the numbers (2026-11-23)

Machine output of `python -m lab.paper.m4_perps_audit`; checks and tolerances in `m4_perps_forward_audit_prereg.md`, findings and fixes in `m4_perps_forward_audit.md`.

Journal rows through 2026-11-22: 30. Calendar days 33, dates with a run 28, days of record (a book held) 28, empty-book rows 2, re-run dates 2026-10-21.

## Per day

| date | run | equity | arith | gross | ref | gross_diff_bps | coins_off | funding_bps | binance_bps | turnover | paper_bps | model_bps | targets | note |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2026-10-21 | 15:48 | 10,000 | ok | +0.00 % |  |  |  | 0.00 |  | 0.000 | 0.000 | 0.000 |  | empty book |
| 2026-10-21 | 15:49 | 10,000 | ok | +0.00 % |  |  |  | 0.00 |  | 0.000 | 0.000 | 0.000 |  | empty book, re-run |
| 2026-10-21 | 16:01 | 9,994 | ok | +0.00 % |  |  |  | 0.00 |  | 1.000 | 5.650 | 41.000 | 4/22 | re-run |
| 2026-10-22 | 05:15 | 10,071 | ok | +0.77 % | +0.69 % | 8.2 | 1 | -0.29 | -0.29 | 0.000 | 0.000 | 0.000 | 0/20 |  |
| 2026-10-23 | 05:15 | 10,167 | ok | +0.96 % | +1.08 % | -12.2 | 6 | 0.26 | 0.26 | 0.000 | 0.000 | 0.000 | 0/20 |  |
| 2026-10-24 | 05:15 | 10,336 | ok | +1.66 % | +1.53 % | 12.9 | 4 | -0.26 | -0.26 | 0.000 | 0.000 | 0.000 | 0/20 |  |
| 2026-10-25 | 05:15 | 10,439 | ok | +1.00 % | +1.14 % | -14.0 | 2 | 0.19 | 0.20 | 0.093 | 0.600 | 3.810 | 0/20 |  |
| 2026-10-26 | 05:15 | 10,414 | ok | -0.24 % | -0.23 % | -0.3 | 0 | -0.12 | -0.12 | 0.000 | 0.000 | 0.000 | 0/20 |  |
| 2026-10-27 | 05:15 | 10,386 | ok | -0.26 % | -0.29 % | 3.0 | 3 | -0.29 | -0.29 | 0.000 | 0.000 | 0.000 | 0/20 |  |
| 2026-10-28 | 05:15 | 10,405 | ok | +0.19 % | +0.07 % | 11.7 | 1 | -0.75 | -0.75 | 0.000 | 0.000 | 0.000 | 0/20 |  |
| 2026-10-29 | 05:15 | 10,451 | ok | +0.45 % | +0.79 % | -33.1 | 10 | -0.51 | -0.51 | 0.090 | 0.610 | 3.710 | 0/20 |  |
| 2026-10-30 | 05:15 | 10,646 | ok | +1.86 % | +1.77 % | 8.7 | 5 | 0.83 | 0.84 | 0.000 | 0.000 | 0.000 | 0/20 |  |
| 2026-10-31 | 05:15 | 10,597 | ok | -0.45 % | -0.71 % | 26.1 | 5 | 0.22 | 0.22 | 0.190 | 1.210 | 7.810 | 2/21 |  |
| 2026-11-01 | 05:15 | 10,603 | ok | +0.03 % | +0.35 % | -31.8 | 2 | 2.65 | 2.64 | 0.086 | 0.480 | 3.520 | 0/20 |  |
| 2026-11-02 | 05:27 | 10,706 | ok | +0.96 % | +0.81 % | 15.4 | 2 | 0.59 | 0.59 | 0.000 | 0.000 | 0.000 | 0/20 |  |
| 2026-11-03 | 05:15 | 10,884 | ok | +1.67 % | +1.61 % | 6.3 | 1 | 0.27 | 0.27 | 0.179 | 1.310 | 7.340 | 2/21 |  |
| 2026-11-04 | 05:16 | 10,782 | ok | -0.93 % | -0.86 % | -7.5 | 0 | -0.01 | -0.01 | 0.000 | 0.000 | 0.000 | 0/20 |  |
| 2026-11-10 | 09:39 | 10,897 | ok | +1.04 % | +1.11 % | -6.5 | 1 | 2.56 | 2.56 | 0.100 | 0.560 | 4.080 | 2/21 | spans missing days |
| 2026-11-11 | 05:16 | 10,914 | ok | +0.16 % | +0.05 % | 10.5 | 1 | 0.08 | 0.08 | 0.000 | 0.000 | 0.000 | 0/20 |  |
| 2026-11-12 | 05:15 | 11,052 | ok | +1.27 % | +1.38 % | -10.9 | 0 | -0.16 | -0.16 | 0.088 | 0.610 | 3.610 | 0/20 |  |
| 2026-11-13 | 05:15 | 11,039 | ok | -0.12 % | -0.03 % | -8.9 | 3 | 0.23 | 0.23 | 0.077 | 0.530 | 3.180 | 0/20 |  |
| 2026-11-14 | 05:15 | 11,048 | ok | +0.08 % | -0.13 % | 21.8 | 6 | 0.61 | 0.61 | 0.096 | 0.700 | 3.950 | 2/21 |  |
| 2026-11-15 | 05:15 | 11,205 | ok | +1.41 % | +1.53 % | -11.8 | 1 | 0.95 | 0.95 | 0.088 | 0.490 | 3.620 | 2/21 |  |
| 2026-11-16 | 05:15 | 11,276 | ok | +0.66 % | +0.51 % | 15.1 | 3 | 0.58 | 0.58 | 0.489 | 3.030 | 20.060 | 10/25 |  |
| 2026-11-17 | 05:15 | 11,197 | ok | -0.58 % | -0.42 % | -15.6 | 3 | -10.62 | -10.62 | 0.280 | 1.890 | 11.470 | 2/21 |  |
| 2026-11-18 | 05:16 | 11,320 | ok | +1.17 % | +1.17 % | 0.4 | 3 | -7.46 | -7.46 | 0.000 | 0.000 | 0.000 | 0/20 |  |
| 2026-11-19 | 05:15 | 11,283 | ok | -0.22 % | -0.17 % | -5.9 | 1 | -5.10 | -5.10 | 0.722 | 4.480 | 29.580 | 14/27 |  |
| 2026-11-20 | 05:15 | 11,526 | ok | +2.15 % | +2.12 % | 3.2 | 0 | -0.00 | -0.00 | 0.000 | 0.000 | 0.000 | 0/20 |  |
| 2026-11-21 | 05:15 | 11,665 | ok | +1.20 % | +1.21 % | -0.9 | 4 | 0.74 | 0.74 | 0.094 | 0.530 | 3.850 | 0/20 |  |
| 2026-11-22 | 05:15 | 11,592 | ok | -0.63 % | -0.61 % | -1.3 | 9 | 0.29 | 0.29 | 0.192 | 1.080 | 7.860 | 8/24 | the kept model: 0 mismatches |


gross_diff_bps: booked gross minus the previous target times Binance spot's interpolated returns (in brackets where a coin has no spot bars). coins_off: pinned coin returns more than 75 bps off. targets: mismatched coin-days of the rebuilt target.

## 1. Arithmetic

0 rows off by more than 1 bp of equity.

## 2. Calendar

Missing days (no run): 2026-11-05, 2026-11-06, 2026-11-07, 2026-11-08, 2026-11-09.
- 2026-11-10: one row spans 6.18 days, gross +1.0402 %.

## 3. Targets

48 mismatched coin-days of 584 (8.2 %): fails (under 5 %).

Per run date with a mismatch: the decision day the book's lag rule takes on the archive the run had, the mismatches one day further back, and with the model the server kept (trained 2026-11-17) where the row used it.

| run date | decision day | listed (rebuilt / booked) | coin | booked | rebuilt | one day back | kept model |
|---|---|---|---|---|---|---|---|
| 2026-10-21 | 2026-10-19 | 76 / 76 | 1000SHIBUSDT | 0.0000 | 0.0500 |  |  |
| 2026-10-21 | 2026-10-19 | 76 / 76 | CRVUSDT | -0.0500 | 0.0000 |  |  |
| 2026-10-21 | 2026-10-19 | 76 / 76 | SOLUSDT | 0.0500 | 0.0000 |  |  |
| 2026-10-21 | 2026-10-19 | 76 / 76 | ZROUSDT | 0.0000 | -0.0500 |  |  |
| 2026-10-31 | 2026-10-29 | 75 / 75 | PAXGUSDT | 0.0000 | 0.0446 |  |  |
| 2026-10-31 | 2026-10-29 | 75 / 75 | RSRUSDT | 0.0500 | 0.0000 |  |  |
| 2026-11-03 | 2026-11-01 | 72 / 72 | MOVRUSDT | -0.0500 | 0.0000 |  |  |
| 2026-11-03 | 2026-11-01 | 72 / 72 | TRUMPUSDT | 0.0000 | -0.0500 |  |  |
| 2026-11-10 | 2026-11-09 | 70 / 70 | ARBUSDT | -0.0500 | 0.0000 |  |  |
| 2026-11-10 | 2026-11-09 | 70 / 70 | RSRUSDT | 0.0000 | -0.0500 |  |  |
| 2026-11-14 | 2026-11-12 | 70 / 70 | LTCUSDT | 0.0500 | 0.0000 |  |  |
| 2026-11-14 | 2026-11-12 | 70 / 70 | PAXGUSDT | 0.0000 | 0.0500 |  |  |
| 2026-11-15 | 2026-11-13 | 70 / 70 | BATUSDT | -0.0233 | 0.0000 |  |  |
| 2026-11-15 | 2026-11-13 | 70 / 70 | TAOUSDT | 0.0000 | -0.0500 |  |  |
| 2026-11-16 | 2026-11-14 | 70 / 70 | 1000FLOKIUSDT | 0.0500 | 0.0000 |  |  |
| 2026-11-16 | 2026-11-14 | 70 / 70 | DOTUSDT | 0.0500 | 0.0000 |  |  |
| 2026-11-16 | 2026-11-14 | 70 / 70 | OPUSDT | 0.0500 | 0.0000 |  |  |
| 2026-11-16 | 2026-11-14 | 70 / 70 | PAXGUSDT | -0.0500 | 0.0000 |  |  |
| 2026-11-16 | 2026-11-14 | 70 / 70 | PUMPUSDT | 0.0000 | -0.0260 |  |  |
| 2026-11-16 | 2026-11-14 | 70 / 70 | SAGAUSDT | -0.0500 | 0.0000 |  |  |
| 2026-11-16 | 2026-11-14 | 70 / 70 | SANDUSDT | 0.0000 | 0.0500 |  |  |
| 2026-11-16 | 2026-11-14 | 70 / 70 | TRXUSDT | 0.0000 | 0.0405 |  |  |
| 2026-11-16 | 2026-11-14 | 70 / 70 | XLMUSDT | 0.0000 | 0.0333 |  |  |
| 2026-11-16 | 2026-11-14 | 70 / 70 | XPLUSDT | 0.0000 | -0.0252 |  |  |
| 2026-11-17 | 2026-11-15 | 70 / 70 | ENAUSDT | 0.0000 | -0.0277 |  |  |
| 2026-11-17 | 2026-11-15 | 70 / 70 | NIGHTUSDT | -0.0500 | 0.0000 |  |  |
| 2026-11-19 | 2026-11-17 | 68 / 51 | AAVEUSDT | -0.0500 | 0.0000 |  | 14 |
| 2026-11-19 | 2026-11-17 | 68 / 51 | ASTERUSDT | 0.0000 | -0.0449 |  | 14 |
| 2026-11-19 | 2026-11-17 | 68 / 51 | DASHUSDT | -0.0500 | 0.0000 |  | 14 |
| 2026-11-19 | 2026-11-17 | 68 / 51 | ETHFIUSDT | 0.0000 | -0.0315 |  | 14 |
| 2026-11-19 | 2026-11-17 | 68 / 51 | NEARUSDT | -0.0500 | 0.0000 |  | 14 |
| 2026-11-19 | 2026-11-17 | 68 / 51 | NIGHTUSDT | 0.0000 | -0.0457 |  | 14 |
| 2026-11-19 | 2026-11-17 | 68 / 51 | OPUSDT | 0.0000 | 0.0472 |  | 14 |
| 2026-11-19 | 2026-11-17 | 68 / 51 | QNTUSDT | -0.0500 | 0.0000 |  | 14 |
| 2026-11-19 | 2026-11-17 | 68 / 51 | RENDERUSDT | 0.0000 | -0.0451 |  | 14 |
| 2026-11-19 | 2026-11-17 | 68 / 51 | RUNEUSDT | -0.0500 | 0.0000 |  | 14 |
| 2026-11-19 | 2026-11-17 | 68 / 51 | STRKUSDT | 0.0000 | -0.0230 |  | 14 |
| 2026-11-19 | 2026-11-17 | 68 / 51 | STXUSDT | -0.0500 | 0.0000 |  | 14 |
| 2026-11-19 | 2026-11-17 | 68 / 51 | TRXUSDT | 0.0500 | 0.0000 |  | 14 |
| 2026-11-19 | 2026-11-17 | 68 / 51 | ZROUSDT | 0.0000 | -0.0355 |  | 14 |
| 2026-11-22 | 2026-11-20 | 65 / 65 | BCHUSDT | 0.0500 | 0.0000 | 4 | 0 |
| 2026-11-22 | 2026-11-20 | 65 / 65 | NEARUSDT | -0.0410 | 0.0000 | 4 | 0 |
| 2026-11-22 | 2026-11-20 | 65 / 65 | OPUSDT | 0.0000 | 0.0500 | 4 | 0 |
| 2026-11-22 | 2026-11-20 | 65 / 65 | RSRUSDT | 0.0000 | -0.0500 | 4 | 0 |
| 2026-11-22 | 2026-11-20 | 65 / 65 | STXUSDT | -0.0436 | 0.0000 | 4 | 0 |
| 2026-11-22 | 2026-11-20 | 65 / 65 | WLFIUSDT | 0.0000 | -0.0500 | 4 | 0 |
| 2026-11-22 | 2026-11-20 | 65 / 65 | XAUTUSDT | 0.0000 | -0.0500 | 4 | 0 |
| 2026-11-22 | 2026-11-20 | 65 / 65 | ZECUSDT | -0.0401 | 0.0000 | 4 | 0 |

The refit against the model the server kept, on decision day 2026-11-16: score rank correlation 0.977, 17 of the 20 end names shared; trained on 560157 rows against 559972 (today's panel is revised).

## 4. Marks

Pinned coin-days 508, with spot bars 508: 77 more than 75 bps off (15.2 %), median gap 28.5 bps; stale marks 2. Against Kraken Futures' marks (189 coin-days): median gap 24.2 bps. Against Binance spot's minute bars (169 coin-days): median gap 9.0 bps.
Rows fully priced 27: 4 more than 20 bps off; booked minus rebuilt over them -17.2 bps (tolerance 50). Fails the pre-registered rule. Off coin-days not explained: 0; off rows not explained: 0.

| date | perp | booked | spot (hour bar) | minute bars | kraken | why |
|---|---|---|---|---|---|---|
| 2026-10-22 | CRVUSDT | -2.86 % | -1.64 % |  | -1.70 % | inside the hour bars |
| 2026-10-23 | ADAUSDT | -1.17 % | -2.08 % |  | -2.09 % | inside the hour bars |
| 2026-10-23 | CRVUSDT | -3.44 % | -4.97 % |  | -5.06 % | inside the hour bars |
| 2026-10-23 | ETHFIUSDT | -4.15 % | -5.63 % |  |  | inside the hour bars |
| 2026-10-23 | QNTUSDT | -3.73 % | -4.98 % |  |  | inside the hour bars |
| 2026-10-23 | SAGAUSDT | +0.54 % | -0.52 % |  |  | inside the hour bars |
| 2026-10-23 | XLMUSDT | -0.31 % | -1.13 % |  |  | inside the hour bars |
| 2026-10-24 | BATUSDT | -7.17 % | -5.99 % |  | -5.71 % | inside the hour bars |
| 2026-10-24 | ETHFIUSDT | -1.05 % | -0.25 % |  |  | inside the hour bars |
| 2026-10-24 | PUMPUSDT | -8.25 % | -7.35 % |  |  | inside the hour bars |
| 2026-10-24 | TIAUSDT | -1.85 % | -1.01 % |  |  | inside the hour bars |
| 2026-10-25 | BATUSDT | -2.04 % | -3.39 % |  | -3.44 % | inside the hour bars |
| 2026-10-25 | STRKUSDT | -4.31 % | -5.23 % |  |  | inside the hour bars |
| 2026-10-27 | ENAUSDT | +1.04 % | +0.08 % |  |  | inside the hour bars |
| 2026-10-27 | QNTUSDT | +3.77 % | +4.53 % |  |  | inside the hour bars |
| 2026-10-27 | TIAUSDT | -1.75 % | -0.91 % |  |  | inside the hour bars |
| 2026-10-28 | BATUSDT | +0.19 % | +1.16 % |  | +1.26 % | inside the hour bars |
| 2026-10-29 | ADAUSDT | -2.79 % | -3.57 % | -2.76 % | -3.54 % | minute bars |
| 2026-10-29 | BATUSDT | -6.38 % | -7.60 % |  | -7.46 % | inside the hour bars |
| 2026-10-29 | ENAUSDT | -2.01 % | -3.32 % |  |  | inside the hour bars |
| 2026-10-29 | ETHFIUSDT | +0.00 % | -1.36 % |  |  | inside the hour bars |
| 2026-10-29 | MUBARAKUSDT | -1.55 % | -2.56 % |  |  | inside the hour bars |
| 2026-10-29 | PUMPUSDT | -0.74 % | -1.87 % |  |  | inside the hour bars |
| 2026-10-29 | QNTUSDT | -1.62 % | -2.69 % |  |  | inside the hour bars |
| 2026-10-29 | STRKUSDT | +1.02 % | -0.44 % |  |  | inside the hour bars |
| 2026-10-29 | TIAUSDT | +0.95 % | -1.36 % |  |  | inside the hour bars |
| 2026-10-29 | WLDUSDT | -3.12 % | -4.20 % |  |  | inside the hour bars |
| 2026-10-30 | ENAUSDT | -6.04 % | -5.17 % |  |  | inside the hour bars |
| 2026-10-30 | ETHFIUSDT | -8.49 % | -7.58 % |  |  | inside the hour bars |
| 2026-10-30 | QNTUSDT | -3.09 % | -1.99 % |  |  | inside the hour bars |
| 2026-10-30 | STRKUSDT | -7.53 % | -6.38 % |  |  | inside the hour bars |
| 2026-10-30 | TIAUSDT | -15.20 % | -13.53 % |  |  | inside the hour bars |
| 2026-10-31 | ADAUSDT | -0.94 % | -0.18 % | -0.75 % | -0.09 % | minute bars |
| 2026-10-31 | BATUSDT | -1.62 % | +0.12 % |  | +0.20 % | inside the hour bars |
| 2026-10-31 | ENAUSDT | +0.39 % | +1.41 % |  |  | inside the hour bars |
| 2026-10-31 | PUMPUSDT | -1.71 % | -0.23 % |  |  | inside the hour bars |
| 2026-10-31 | WLDUSDT | -0.45 % | +0.41 % |  |  | inside the hour bars |
| 2026-11-01 | RSRUSDT | +10.64 % | +13.15 % |  |  | inside the hour bars |
| 2026-11-01 | XPLUSDT | -9.57 % | -11.31 % |  |  | inside the hour bars |
| 2026-11-02 | RSRUSDT | -6.70 % | -8.11 % |  |  | inside the hour bars |
| 2026-11-02 | XPLUSDT | -3.06 % | -1.29 % |  |  | inside the hour bars |
| 2026-11-03 | XPLUSDT | -11.21 % | -10.40 % |  |  | inside the hour bars |
| 2026-11-10 | BATUSDT | +1.34 % | +0.46 % |  | +0.64 % | inside the hour bars |
| 2026-11-11 | BATUSDT | -5.24 % | -4.45 % |  | -4.70 % | inside the hour bars |
| 2026-11-13 | BATUSDT | +1.92 % | +0.43 % |  | +0.41 % | inside the hour bars |
| 2026-11-13 | PUMPUSDT | -4.54 % | -5.40 % |  |  | inside the hour bars |
| 2026-11-13 | ZROUSDT | -1.13 % | -2.43 % |  |  | inside the hour bars |
| 2026-11-14 | BATUSDT | -11.93 % | -10.86 % |  | -11.04 % | inside the hour bars |
| 2026-11-14 | ICPUSDT | -5.52 % | -4.44 % |  |  | inside the hour bars |
| 2026-11-14 | PUMPUSDT | +3.07 % | +4.02 % |  |  | inside the hour bars |
| 2026-11-14 | STRKUSDT | +1.24 % | +2.46 % |  |  | inside the hour bars |
| 2026-11-14 | XPLUSDT | +0.78 % | +1.58 % |  |  | inside the hour bars |
| 2026-11-14 | ZROUSDT | +2.91 % | +4.21 % |  |  | inside the hour bars |
| 2026-11-15 | STRKUSDT | -2.06 % | -3.31 % |  |  | inside the hour bars |
| 2026-11-16 | ENAUSDT | -1.10 % | -0.29 % |  |  | inside the hour bars |
| 2026-11-16 | INJUSDT | -4.37 % | -2.66 % |  |  | inside the hour bars |
| 2026-11-16 | STRKUSDT | -3.30 % | -2.47 % |  |  | inside the hour bars |
| 2026-11-17 | ADAUSDT | +0.09 % | +0.85 % | +0.42 % | +0.90 % | minute bars |
| 2026-11-17 | KAVAUSDT | -10.52 % | -12.78 % |  |  | inside the hour bars |
| 2026-11-17 | OPUSDT | -2.37 % | -1.21 % |  |  | inside the hour bars |
| 2026-11-18 | INJUSDT | -0.01 % | -1.30 % |  |  | inside the hour bars |
| 2026-11-18 | KAVAUSDT | +6.34 % | +4.36 % |  |  | inside the hour bars |
| 2026-11-18 | OPUSDT | -2.33 % | -3.75 % |  |  | inside the hour bars |
| 2026-11-19 | INJUSDT | -4.53 % | -3.64 % |  |  | inside the hour bars |
| 2026-11-21 | ADAUSDT | -7.53 % | -8.67 % | -7.78 % | -8.77 % | minute bars |
| 2026-11-21 | ETHUSDT | -9.02 % | -9.80 % | -9.08 % | -9.88 % | minute bars |
| 2026-11-21 | LTCUSDT | -6.56 % | -7.33 % | -6.64 % | -7.40 % | minute bars |
| 2026-11-21 | SOLUSDT | -7.96 % | -8.82 % | -8.10 % | -8.93 % | minute bars |
| 2026-11-22 | ADAUSDT | +4.07 % | +4.85 % | +4.25 % | +4.81 % | minute bars |
| 2026-11-22 | BNBUSDT | +4.44 % | +5.58 % |  |  | inside the hour bars |
| 2026-11-22 | BTCUSDT | +4.60 % | +5.42 % | +4.61 % | +5.38 % | minute bars |
| 2026-11-22 | ETHUSDT | +5.70 % | +6.47 % | +5.72 % | +6.45 % | minute bars |
| 2026-11-22 | ICPUSDT | -0.06 % | -0.89 % |  |  | inside the hour bars |
| 2026-11-22 | SOLUSDT | +4.32 % | +5.16 % | +4.42 % | +5.16 % | minute bars |
| 2026-11-22 | XPLUSDT | -1.02 % | +0.11 % |  |  | inside the hour bars |
| 2026-11-22 | XRPUSDT | +4.12 % | +5.10 % | +4.35 % | +5.07 % | minute bars |
| 2026-11-22 | ZECUSDT | +9.48 % | +10.75 % |  |  | inside the hour bars |

Rows off: 2026-10-29 (-33.1 bps, inside the hour bars), 2026-10-31 (+26.1 bps, inside the hour bars), 2026-11-01 (-31.8 bps, inside the hour bars), 2026-11-14 (+21.8 bps, inside the hour bars).

## 5. Funding

0 rows more than 0.5 bp off Binance's settlements; booked minus Binance over the record -0.01 bps (tolerance 2). Passes. Booked -0.1452 %, Binance -0.1451 %, Kraken on the coins it lists -0.1087 %.

## 6. Costs

Rebalance rows 16, turnover 3.8648. Paper 0.2376 % = taker 5.0 bps + half spread 1.15 bps per unit traded; model column 1.5845 % (41 bps per unit). Ratio 0.150. Rows off the identities: none.
Against the band's cost (8.77 bps per unit, m4l_series.json): model 0.3388 %, ratio 0.701.

## 7. The gap to m4_hl_small

m4_perps +15.91 % through 2026-11-22, m4_hl_small +3.94 %: gap +11.97 points. m4_perps on the twin's days (2026-10-30 to 2026-11-22): +8.88 %.

| part | points |
|---|---|
| timing | +4.10 |
| funding | +2.21 |
| costs | +0.28 |
| universe | -0.71 |
| fills | +5.00 |
| residual | +1.10 |

| of which | points |
|---|---|
| timing: before the twin's first run | +6.46 |
| timing: run hours | -2.36 |
| fills: weights on common coins | +5.00 |
| fills: m4_perps' marks against spot | -0.02 |
| fills: m4_hl_small's marks against spot | +0.03 |

The twin's weight without spot bars (summed over 20 steps): 0.000.
