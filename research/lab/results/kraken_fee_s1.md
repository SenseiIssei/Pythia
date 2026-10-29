# Kraken's new-account fee in R10's S1 rows, the S1 books and the dry run

Pre-registered in `results/kraken_fee_s1_prereg.md` (committed before this run).
`python -m lab.experiments.smallaccount_r10 --kraken-fee`, 2026-10-29, on the lab's daily panel, R10's inputs, the
validation window 2024-01-01 to 2026-06-30 only (the lockbox stays shut). 8 counted trials in R5's registry
(`small:kraken_fee_s1:<rule>@<EUR>:<fill>`, family small). Paper only: no key, no account, no order.

## The one fee source

`lab.exec.kraken_fee.kraken_fee(vol_usd, maker, stable)`: Kraken's published schedule as text in the repo
(https://www.kraken.com/features/fee-schedule, read 2026-10-28). Spot pairs, a new account (under 2,500 USD in 30
days): 0.80 % taker, 0.40 % maker. Stablecoin and FX pairs (USDC/EUR): 0.20 %. The dry run (`fee_rate`), S1's paper
books (the way there, `lab.paper.smallaccount.s1_venue`), R10's cost model (`kraken_costs`, `CEX_TAKER`) and the
ladder's era line for S1 all read it; a test checks they agree at every volume.

## What it says

- **R10's Kraken leg was half the real price, the way in and back twice it.** Before an asset was on chain (BTC
  until cbBTC on 2024-11-07 inside the window) a trade now pays 0.80 % plus the half spread, not 0.40 %; the way
  in and back is EUR to USDC, a stablecoin pair, 0.20 % plus the half spread (20.6 bps), not 40.
- **Both S1 rules lose, neither passes.** Late at 40 / 100 EUR, against R10's published rows at 0.40 %:

  | rule | late CAGR at 0.40 % | late CAGR at 0.80 % | late Sharpe | late DSR all / small |
  |---|---|---|---|---|
  | tsmom1 | 14.3 % / 15.8 % | 10.3 % / 11.5 % | 0.62 to 0.49 (40 EUR) | 0.000 / 0.001 |
  | breakout_sol3 | 4.6 % / 6.2 % | 4.1 % / 5.7 % | 0.32 to 0.30 (40 EUR) | 0.000 / 0.000 |

  tsmom1 rebalances BTC daily to its volatility target, so the doubled fee on its Kraken era costs it about 4
  points a year; breakout_sol3 trades rarely and loses half a point. Both still beat the BTC/ETH wallet's Sharpe
  (0.20) and fail on the DSR, as before. Nothing moves nearer to real money.
- **The S1 paper books' cost goes down, not up.** Their only Kraken cost is the way there, EUR to USDC: 0.20 %, not
  the 0.40 % they paid. On their next run `small50_tsmom1` and `small50_tsmom1_wk` get 0.10 EUR back and
  `small100_breakout_sol3` 0.20 EUR, once, written into their state (`restated`); `reports/smallaccount/latest.md`
  names the fee and its source. S2's books go there by a SOL swap and do not change.

The ladder's S1 rows now come from this rerun (`reports/kraken_fee_s1/latest.json` once the server has run it,
else R10's table) and their "costs of their era" line names the 0.80 % and its source. The stablecoin fee is the
first tier L1 read off the same page; confirm it there before money moves.

<!-- generated below by lab.experiments.smallaccount_r10 --kraken-fee; edit above this line only -->

Generated 2026-10-29T13:39:40+00:00. Validation 2024-01-01 to 2026-06-30 only (no in-sample number, the lockbox shut). Fees: spot taker 0.80 % (Kraken's published fee schedule, spot pairs, new-account tier: https://www.kraken.com/features/fee-schedule, read 2026-10-28); the way in and back 20.6 bps (the stablecoin fee 0.20 % plus USDC/EUR's half spread). Kraken before the asset was on chain: BTC 80.0 bps, ETH 80.0 bps, SOL 80.5 bps.

| rule | EUR | on time CAGR / DD / Sharpe / end | late CAGR / DD / Sharpe / end | benchmark CAGR / DD / Sharpe / end | late DSR, pass at 0.95 or more (all / small) | passes late |
|---|---|---|---|---|---|---|
| S1 tsmom1 | 40 | 13.5 % / 27.6 % / 0.60 / 54.91 | 10.3 % / 27.1 % / 0.49 / 51.16 | -2.7 % / 56.5 % / 0.20 / 37.35 | 0.000 / 0.001 | no |
| S1 tsmom1 | 100 | 14.7 % / 27.9 % / 0.64 / 140.99 | 11.5 % / 27.9 % / 0.52 / 131.13 | -2.1 % / 57.0 % / 0.22 / 94.84 | 0.000 / 0.001 | no |
| S1 breakout_sol3 | 40 | 10.7 % / 20.4 % / 0.59 / 51.60 | 4.1 % / 24.4 % / 0.30 / 44.23 | -2.7 % / 56.5 % / 0.20 / 37.35 | 0.000 / 0.000 | no |
| S1 breakout_sol3 | 100 | 12.5 % / 20.5 % / 0.66 / 134.10 | 5.7 % / 24.1 % / 0.36 / 114.73 | -2.1 % / 57.0 % / 0.22 / 94.84 | 0.000 / 0.000 | no |

Benchmark: half BTC and half ETH held, the wallet's costs. DSR over R5's registry with this rerun's 8 trials: all 3,174 trials (noise bar 2.84 a year), small 377 (2.04); higher is better.

