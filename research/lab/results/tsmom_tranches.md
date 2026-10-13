# tsmom_tranches (generated 2026-10-12)

`python -m lab.experiments.tsmom_tranches`. The paper book `tsmom_tranches` (lab/paper/families.py) runs this rule. Survivorship-free daily panel (590 coin segments, delisted coins included) to 2026-09-30. In sample 2020-08 to 2023, out of sample from 2024-01-01. Costs per unit of one-way turnover: Alpaca maker 15 bps (also the lab's usual figure; optimistic for Alpaca, no slippage and every order filled), Alpaca taker 25 bps plus about 10 bps measured slippage (35 bps), the lab's 41 bps, and taker doubled (70 bps).

## Out of sample

| variant | is_taker 35bps | oos_maker 15bps | oos_taker 35bps | oos_41bps | oos_taker x2 70bps | cagr_taker 35bps | dd_taker 35bps | turnover_yr | expo | deflated_p | boot35_p05 | boot35_p95 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| tsmom 28d · top 20 · regime · seven weekly tranches · band 50 % | 1.54 | 0.58 | 0.52 | 0.50 | 0.41 | 0.07 | 0.23 | 5.02 | 0.17 | 0.00 | -0.59 | 1.52 |
| tsmom_top20, daily (reference) | 1.31 | 0.53 | 0.36 | 0.31 | 0.07 | 0.05 | 0.24 | 12.89 | 0.16 | 0.00 | -0.78 | 1.35 |
| tsmom 28d · top 20 · regime · seven weekly tranches · band 50 % · Alpaca coins only (check) | 1.85 | 0.84 | 0.79 | 0.78 | 0.70 | 0.07 | 0.09 | 2.40 | 0.09 | 0.00 | -0.41 | 1.96 |

## Per year (Sharpe at 35 bps, 2021 to 2026) and by BTC regime

| variant | y2021 | y2022 | y2023 | y2024 | y2025 | y2026 | oos_btc_above | oos_btc_below |
|---|---|---|---|---|---|---|---|---|
| tsmom 28d · top 20 · regime · seven weekly tranches · band 50 % | 2.41 | 0.89 | 1.30 | 0.59 | 0.08 | 1.31 | 0.76 | -0.81 |
| tsmom_top20, daily (reference) | 2.12 | 0.00 | 1.22 | 0.37 | -0.29 | 1.50 | 0.49 | -2.29 |
| tsmom 28d · top 20 · regime · seven weekly tranches · band 50 % · Alpaca coins only (check) | 2.51 | 0.84 | 1.52 | 1.67 | -0.08 | 0.97 | 1.12 | -1.06 |

## Reading

- At Alpaca taker cost the tranche book makes an out-of-sample Sharpe of 0.52 (maker 0.58, taker doubled 0.41) with a 23 % drawdown and 5.0x turnover a year; the daily-rebalanced tsmom_top20 makes 0.36 at the same cost.
- Deflated p 0.00 over 184 trials (the blend study's 183 plus the Alpaca-only check here; bar about 2.45). It fails the lab's deflation bar. The 90 % bootstrap band of the Sharpe at 35 bps is -0.59 to 1.52.
- On average 53 % of the book's exposure out of sample sits in coins Alpaca does not list (TRX, SUI, NEAR, ATOM, XLM and coins outside the engine's 20); an autopilot on Alpaca holds that part as cash. The Alpaca-only row is that book.
- Caveat: forward evidence only. The rule was picked in the blend study as the weekday-free form of a weekly pick whose own number was weekday luck; nothing here was tuned again.
