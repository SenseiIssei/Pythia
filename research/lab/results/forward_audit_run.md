# Forward record audit, the numbers (2026-10-20)

Machine output of `python -m lab.paper.forward_audit`; thresholds in `forward_audit_prereg.md`, findings and fixes in `forward_audit.md`.

## 1. Signal reconciliation and 2. percentile

| book | days | coin-days | mismatches | share | forward | backtest, same days (35 bps) | percentile 35 bps | 5th / median / 95th (35 bps) | percentile 70 bps | verdict |
|---|---|---|---|---|---|---|---|---|---|---|
| tsmom | 14 | 225 | 0 | 0.0 % | -6.27 % | -6.79 % | 2 | -4.9 % / -0.4 % / +10.0 % | 3 | fails the pass rule, not the kill rule |
| tsmom_regime | 13 | 205 | 0 | 0.0 % | -4.54 % | -6.26 % | 3 | -3.9 % / +0.0 % / +9.7 % | 4 | fails the pass rule, not the kill rule |
| tsmom_top20 | 13 | 222 | 0 | 0.0 % | -4.37 % | -6.79 % | 4 | -3.9 % / +0.0 % / +7.4 % | 5 | fails the pass rule, not the kill rule |
| breakout_top10 | 13 | 15 | 3 | 20.0 % | -0.81 % | -2.18 % | 34 | -4.0 % / -0.2 % / +12.7 % | 36 | frozen (kill rule) |
| tsmom_tranches | 7 | 166 | 0 | 0.0 % | -2.00 % | -1.02 % | 11 | -3.4 % / +0.0 % / +5.2 % | 11 | passes |
| memes_rotation | 5 | 4 | 0 | 0.0 % | -1.09 % | -0.98 % | 19 | -4.4 % / +0.0 % / +8.4 % | 21 | passes |
| memes_tsmom | 5 | 11 | 0 | 0.0 % | -0.49 % | -0.58 % | 21 | -3.0 % / +0.0 % / +3.5 % | 22 | passes |

Not replayed:

- `m4_ls`: M4 is retrained weekly on the server and picks among the perps that trade at run time; the mirror keeps only the newest model, so earlier days cannot be scored with the model that chose them. Forward -1.53 % over 12 days.
- `picks_ls`: M2 is retrained on all history at every rebalance against the live perp list; the mirror has no copy of either as of the rebalance days. Forward +2.42 % over 13 days.
- `picks_ls_v2`: as picks_ls, with M2 v2. Forward +6.04 % over 13 days.
- `trend4h_pullback`: hourly decisions with resting limits filled on live 1h bars; its own trades.csv is the record and the study's fill model is the backtest, so there is no daily target to compare. Forward -0.96 % over 5 days.
- `pumpfun_migration`: event book on the live pump.fun stream; no backtest signal exists. Forward -1096.57 % over 5 days.
- `pumpfun_filtered`: event book on the live pump.fun stream; no backtest signal exists. Forward -1.73 % over 5 days.
- `pumpfun_filtered_quick`: event book on the live pump.fun stream; no backtest signal exists. Forward +0.06 % over 5 days.

### Mismatched coin-days

**breakout_top10**

| run date | coin | held | backtest | difference |
|---|---|---|---|---|
| 2026-10-08 | NEAR | 0.0347 | 0.0543 | -0.0196 |
| 2026-10-07 | NEAR | 0.0329 | 0.0512 | -0.0183 |
| 2026-10-07 | SUI | 0.0420 | 0.0564 | -0.0144 |

## 3. Realised cost of autopilot fills

178 filled autopilot orders with a realised cost (2026-10-15 to 2026-10-20): median 1.2 bps, 90th percentile 30.3 bps. The lab books' fills (178): median 1.2 bps, 90th percentile 30.3 bps against the arrival price (positive is a cost), fees not included.

| market | fills | median bps | 90th percentile bps |
|---|---|---|---|
| crypto:PEPE/USD | 23 | 2.5 | 40.2 |
| crypto:SOL/USD | 17 | 0.0 | 5.9 |
| crypto:LINK/USD | 15 | 3.0 | 38.0 |
| crypto:AVAX/USD | 15 | 2.1 | 52.5 |
| crypto:ADA/USD | 15 | 9.8 | 23.4 |
| crypto:XRP/USD | 14 | 1.8 | 22.5 |
| crypto:BTC/USD | 13 | 0.0 | 0.8 |
| crypto:LTC/USD | 12 | 1.7 | 17.8 |
| crypto:DOGE/USD | 11 | 3.7 | 8.4 |
| crypto:UNI/USD | 10 | 3.5 | 13.0 |
| crypto:ETH/USD | 8 | 1.1 | 4.1 |
| crypto:FIL/USD | 7 | 0.0 | 36.0 |
| crypto:BCH/USD | 6 | -0.4 | 22.4 |
| crypto:AAVE/USD | 6 | 10.8 | 29.5 |
| crypto:DOT/USD | 6 | 11.0 | 25.6 |
