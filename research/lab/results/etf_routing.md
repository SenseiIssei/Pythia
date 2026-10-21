# etf_routing (survey O1) · BTC and ETH legs through IBIT and ETHA

Pre-registered in `results/etf_routing_prereg.md` (committed before any
number was computed). Code: `lab.experiments.etf_routing`.

**Summary.** No book passes, so no design note for an engine routing option.
The fee saving is real but small next to the noise of filling hours later:
breakout_top10 saves 72 bps of book equity a year in fees and gives back 7 in
timing, weekend gaps and tracking (net +64 bps, band -48 to +173), the
momentum books net +12 and +25 bps with bands across zero, and the ETFs track
spot at 2.8 to 3.0 % a year by the registered measure (above the 2 % rule;
much of that is the 16:00 print against a Binance minute). For btc_gated,
which is all BTC and switches about five times a year, waiting for the US
open costs far more than the fee saves (-426 bps a year, Sharpe 0.46 against
0.60): every switch waits for the next US open (a weekend one until Monday),
and the BTC move in that wait decides the result (per year -1,796, +926,
-446 bps). Routing would make sense only as a fee-only change for slow books, and
the evidence does not show it pays even there.

<!-- generated below by lab.experiments.etf_routing; edit above this line only -->

## Results (generated 2026-10-21, 2024-01-11 to 2026-10-14, 1008 days)

**Verdict: no book passes.**

- **breakout_top10**: fails: mean above 0 and bootstrap 5 % of D's Sharpe above 0; tracking error below 2 % a year. D +64 bps of book equity a year (fee saved +72, timing, weekend gap and tracking -7); mean band -48 to +173 bps; D's Sharpe 0.23, band -0.17 to 0.62; stress +36 bps; per year +113 / +57 / +13. Book Sharpe 1.23 with crypto fills, 1.29 with ETF fills; BTC and ETH are 42 % of its turnover.
- **tsmom_top20**: fails: mean above 0 and bootstrap 5 % of D's Sharpe above 0; mean above 0 with B 5 bps and A 25 bps; tracking error below 2 % a year; no year negative. D +12 bps of book equity a year (fee saved +59, timing, weekend gap and tracking -47); mean band -94 to +99 bps; D's Sharpe 0.08, band -0.51 to 0.72; stress -10 bps; per year -84 / +120 / -7. Book Sharpe 0.55 with crypto fills, 0.58 with ETF fills; BTC and ETH are 33 % of its turnover.
- **tsmom_tranches**: fails: mean above 0 and bootstrap 5 % of D's Sharpe above 0; tracking error below 2 % a year; no year negative. D +25 bps of book equity a year (fee saved +21, timing, weekend gap and tracking +4); mean band -13 to +66 bps; D's Sharpe 0.19, band -0.10 to 0.48; stress +17 bps; per year +64 / +14 / -10. Book Sharpe 0.68 with crypto fills, 0.73 with ETF fills; BTC and ETH are 32 % of its turnover.
- **btc_gated**: killed. D -426 bps of book equity a year (fee saved +338, timing, weekend gap and tracking -764); mean band -1907 to +754 bps; D's Sharpe -0.15, band -0.61 to 0.29; stress -554 bps; per year -1796 / +926 / -446. Book Sharpe 0.60 with crypto fills, 0.46 with ETF fills; BTC and ETH are 100 % of its turnover.

### Per book

| book | d_bps_yr | fee_saved_bps_yr | rest_bps_yr | d_sharpe | boot_p05 | boot_p95 | d_stress_bps_yr | d_a25_bps_yr | d_maker_bps_yr | d2024_bps | d2025_bps | d2026_bps | deflated_p |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| breakout_top10 | 64.45 | 71.65 | -7.20 | 0.23 | -0.17 | 0.62 | 36.21 | 42.74 | 21.02 | 113.47 | 56.95 | 13.19 | 0.00 |
| tsmom_top20 | 12.01 | 58.80 | -46.79 | 0.08 | -0.51 | 0.72 | -10.10 | -5.64 | -23.29 | -83.69 | 120.20 | -6.87 | 0.00 |
| tsmom_tranches | 25.10 | 21.28 | 3.82 | 0.19 | -0.10 | 0.48 | 16.73 | 18.65 | 12.21 | 64.37 | 14.30 | -9.87 | 0.00 |
| btc_gated | -426.23 | 337.51 | -763.75 | -0.15 | -0.61 | 0.29 | -553.64 | -527.62 | -629.01 | -1796.39 | 925.53 | -445.80 | 0.00 |

### The books both ways (from 2024-01-11)

| book | bt_sharpe | book_a_sharpe | book_b_sharpe | book_a_cagr | book_b_cagr | book_a_dd | book_b_dd | tov_yr | btc_eth_tov_share | avg_btc_eth_weight |
|---|---|---|---|---|---|---|---|---|---|---|
| breakout_top10 | 1.193 | 1.227 | 1.294 | 0.195 | 0.203 | 0.158 | 0.145 | 5.637 | 0.422 | 0.062 |
| tsmom_top20 | 0.568 | 0.554 | 0.583 | 0.045 | 0.047 | 0.091 | 0.093 | 6.060 | 0.326 | 0.031 |
| tsmom_tranches | 0.676 | 0.677 | 0.727 | 0.060 | 0.063 | 0.088 | 0.088 | 2.349 | 0.316 | 0.032 |
| btc_gated | 0.588 | 0.605 | 0.457 | 0.165 | 0.106 | 0.303 | 0.424 | 10.139 | 1.000 | 0.602 |

`bt_sharpe` is the backtest's own convention (filled at the 00:00 UTC close at 35 bps); `book_a` fills the BTC and ETH legs at 04:15 UTC as the engine does, `book_b` through the ETFs.

### Tracking against spot (16:00 New York)

| etf | days | te | shortfall_yr | corr |
|---|---|---|---|---|
| IBIT | 691 | 0.0281 | -0.0019 | 0.9985 |
| ETHA | 559 | 0.0300 | 0.0042 | 0.9992 |

Pool 1,762 trials; noise bar about 2.72.
