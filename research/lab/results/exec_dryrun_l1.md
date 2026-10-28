# L1: 50 EUR on Kraken spot, dry run. First run

Pre-registered in `results/exec_dryrun_l1_prereg.md` (committed before this run). `python -m lab.exec.dryrun`,
2026-10-28, on the lab's paper journals and Kraken's public answers of that evening; the daily job `exec-dryrun`
writes the same report to `reports/exec_dryrun/`. No key, no account, no order sent. 11 counted trials in R5's
registry (`small:l1:exec_dryrun_<book>`, family small).

## What it says

- **Fees.** Kraken's AssetPairs carries no fee tiers any more; the published spot schedule charges a new account
  0.80 % taker and 0.40 % maker (tier 1, under 2,500 USD in 30 days), twice the 0.40 % taker S1 and S2 costed.
  A 50 EUR account never leaves tier 1. SPYx trades only against USD on Kraken, so S2's SPY pays the FX leg too
  (0.99 % a buy).
- **The tsmom books cannot be traded with 50 EUR.** 99 to 100 % of their orders fall under Kraken's ordermin
  (933 of 935 over the window): their weights are 0.2 to 2 % of the book, 0.07 to 1.1 EUR at 50 EUR, while an
  order needs about 3.5 to 5 EUR. The account stays 3 to 26 % off target on average; the return gap that costs is
  2.8 to 22.8 % a year in tracking error on 8 to 23 days (too few days for its mean, 26 to 132 % a year, to mean
  anything).
- **The small-account books can.** Their few orders over the window (S2's spy_trend: one buy of 49.50 EUR SPYx)
  were all placeable; the fee and the lot leave about 1 % of the wallet in cash. Their monthly fee share is
  the first buy-in over the window's 4 days (7.4 % taker for spy_trend) and says nothing yet; S1's two books and L1's
  onchain_longterm held no coin in the window.

Next: the report runs daily; the fee share a month means something once a book has 30 days in its window.

## The report

Pre-registered in `results/exec_dryrun_l1_prereg.md`. No key, no account, no order sent. Kraken's public answers of 2026-10-28T22:35:38+00:00; fee: Kraken's published spot schedule (AssetPairs' fee lists are empty), taker 0.80 %, maker 0.40 % at the account's tier; EUR/USD 1.1147. A wallet of 50 EUR for every book.

## Per book, the replay

The journal's last 30 days: an order for every coin whose target changed, at Kraken's daily close. Off target: the mean of the summed |held - target| weights after each day. Gap: held minus target on the next day's closes, a year (fees apart). Fees: a share of the wallet a month, the first day's buy-in included (on a few days it dominates).

| book | study | days | orders | not placed | why | off target | tracking error | gap | fees taker | fees maker |
|---|---|---|---|---|---|---|---|---|---|---|
| small50_tsmom1 | S1 | 5 | 0 | 0 (n/a) | - | 0.0 % | n/a | n/a | 0.00 % | 0.00 % |
| small100_breakout_sol3 | S1 | 5 | 0 | 0 (n/a) | - | 0.0 % | n/a | n/a | 0.00 % | 0.00 % |
| small40_spy_trend | S2 | 4 | 1 | 0 (0 %) | - | 0.0 % | 0.0 % | -0.0 % | 7.43 % | 4.46 % |
| small40_vol_target | S2 | 4 | 0 | 0 (n/a) | - | 0.0 % | 0.0 % | 0.0 % | 0.00 % | 0.00 % |
| tsmom | tsmom | 23 | 205 | 203 (99 %) | below ordermin 203 | 25.3 % | 18.7 % | 119.1 % | 0.21 % | 0.11 % |
| tsmom_regime | tsmom | 22 | 188 | 188 (100 %) | below ordermin 188 | 24.3 % | 19.5 % | 118.6 % | 0.00 % | 0.00 % |
| tsmom_top20 | tsmom | 22 | 206 | 206 (100 %) | below ordermin 206 | 26.3 % | 22.8 % | 132.2 % | 0.00 % | 0.00 % |
| tsmom_tranches | tsmom | 16 | 249 | 249 (100 %) | below ordermin 249 | 25.5 % | 12.3 % | 35.4 % | 0.00 % | 0.00 % |
| tsmom_tranches_lowkr | tsmom | 8 | 60 | 60 (100 %) | below ordermin 60 | 6.8 % | 5.6 % | 46.9 % | 0.00 % | 0.00 % |
| tsmom_tranches_lowmax | tsmom | 8 | 27 | 27 (100 %) | below ordermin 27 | 3.2 % | 2.8 % | 26.0 % | 0.00 % | 0.00 % |
| onchain_longterm | L1 | 3 | 0 | 0 (n/a) | - | 0.0 % | n/a | n/a | 0.00 % | 0.00 % |

## Today's orders from a fresh wallet

The latest journal row's targets bought at the ask; units before and after rounding down to the lot.

**small50_tsmom1** (2026-10-28): no target above 0.

**small100_breakout_sol3** (2026-10-28): no target above 0.

**small40_spy_trend** (2026-10-28): 

| coin | pair | target | EUR | units | rounded | ordermin | limit | placed | fee EUR | drift |
|---|---|---|---|---|---|---|---|---|---|---|
| SPY | SPYx/USD | 100.00 % | 50.00 | 0.072379032 | 0.0716624 | 1e-08 | 770.04 | yes | 0.4950 | -0.99 % |

**small40_vol_target** (2026-10-28): no target above 0.

**tsmom** (2026-10-28): 

| coin | pair | target | EUR | units | rounded | ordermin | limit | placed | fee EUR | drift |
|---|---|---|---|---|---|---|---|---|---|---|
| PEPE | PEPE/EUR | 1.43 % | 0.71 | 158080.92 | 158080.92 | 1100000 | 4.523e-06 | below ordermin | 0.0000 | -1.43 % |

**tsmom_regime** (2026-10-28): 

| coin | pair | target | EUR | units | rounded | ordermin | limit | placed | fee EUR | drift |
|---|---|---|---|---|---|---|---|---|---|---|
| PEPE | PEPE/EUR | 1.43 % | 0.71 | 158080.92 | 158080.92 | 1100000 | 4.523e-06 | below ordermin | 0.0000 | -1.43 % |

**tsmom_top20** (2026-10-28): 

| coin | pair | target | EUR | units | rounded | ordermin | limit | placed | fee EUR | drift |
|---|---|---|---|---|---|---|---|---|---|---|
| PEPE | PEPE/EUR | 2.16 % | 1.08 | 238779.57 | 238779.57 | 1100000 | 4.523e-06 | below ordermin | 0.0000 | -2.16 % |
| STRK | STRK/EUR | 0.91 % | 0.46 | 10.66823 | 10.66822 | 110 | 0.04265 | below ordermin | 0.0000 | -0.91 % |

**tsmom_tranches** (2026-10-28): 

| coin | pair | target | EUR | units | rounded | ordermin | limit | placed | fee EUR | drift |
|---|---|---|---|---|---|---|---|---|---|---|
| PEPE | PEPE/EUR | 1.69 % | 0.84 | 186822.91 | 186822.91 | 1100000 | 4.523e-06 | below ordermin | 0.0000 | -1.69 % |
| PUMP | PUMP/EUR | 0.47 % | 0.24 | 57.317073 | 57.31707 | 900 | 0.0041 | below ordermin | 0.0000 | -0.47 % |
| NEAR | NEAR/EUR | 0.44 % | 0.22 | 0.0516893 | 0.0516893 | 1 | 4.2562 | below ordermin | 0.0000 | -0.44 % |
| WLD | WLD/EUR | 0.42 % | 0.21 | 0.53231939 | 0.53231 | 9 | 0.3945 | below ordermin | 0.0000 | -0.42 % |
| QNT | QNT/EUR | 0.38 % | 0.19 | 0.0010547938 | 0.00105479 | 0.02 | 180.13 | below ordermin | 0.0000 | -0.38 % |
| LINK | LINK/EUR | 0.36 % | 0.18 | 0.016946536 | 0.01694653 | 0.35 | 10.62164 | below ordermin | 0.0000 | -0.36 % |
| SUI | SUI/EUR | 0.24 % | 0.12 | 0.14129283 | 0.14129 | 5 | 0.8493 | below ordermin | 0.0000 | -0.24 % |
| ONDO | ONDO/EUR | 0.23 % | 0.11 | 0.30321407 | 0.30321 | 10 | 0.37927 | below ordermin | 0.0000 | -0.23 % |
| ENA | ENA/EUR | 0.19 % | 0.10 | 0.5026455 | 0.50264 | 20 | 0.189 | below ordermin | 0.0000 | -0.19 % |
| STRK | STRK/EUR | 0.13 % | 0.07 | 1.5240328 | 1.52403 | 110 | 0.04265 | below ordermin | 0.0000 | -0.13 % |

**tsmom_tranches_lowkr** (2026-10-28): 

| coin | pair | target | EUR | units | rounded | ordermin | limit | placed | fee EUR | drift |
|---|---|---|---|---|---|---|---|---|---|---|
| PEPE | PEPE/EUR | 1.66 % | 0.83 | 183506.52 | 183506.52 | 1100000 | 4.523e-06 | below ordermin | 0.0000 | -1.66 % |
| PUMP | PUMP/EUR | 0.47 % | 0.24 | 57.317073 | 57.31707 | 900 | 0.0041 | below ordermin | 0.0000 | -0.47 % |
| WLD | WLD/EUR | 0.43 % | 0.21 | 0.54499366 | 0.54499 | 9 | 0.3945 | below ordermin | 0.0000 | -0.43 % |
| NEAR | NEAR/EUR | 0.42 % | 0.21 | 0.049339787 | 0.04933978 | 1 | 4.2562 | below ordermin | 0.0000 | -0.42 % |
| LINK | LINK/EUR | 0.37 % | 0.18 | 0.017417273 | 0.01741727 | 0.35 | 10.62164 | below ordermin | 0.0000 | -0.37 % |
| QNT | QNT/EUR | 0.37 % | 0.18 | 0.001027036 | 0.00102703 | 0.02 | 180.13 | below ordermin | 0.0000 | -0.37 % |
| SUI | SUI/EUR | 0.32 % | 0.16 | 0.18839044 | 0.18839 | 5 | 0.8493 | below ordermin | 0.0000 | -0.32 % |
| ONDO | ONDO/EUR | 0.22 % | 0.11 | 0.29003085 | 0.29003 | 10 | 0.37927 | below ordermin | 0.0000 | -0.22 % |
| STRK | STRK/EUR | 0.13 % | 0.07 | 1.5240328 | 1.52403 | 110 | 0.04265 | below ordermin | 0.0000 | -0.13 % |

**tsmom_tranches_lowmax** (2026-10-28): 

| coin | pair | target | EUR | units | rounded | ordermin | limit | placed | fee EUR | drift |
|---|---|---|---|---|---|---|---|---|---|---|
| PEPE | PEPE/EUR | 1.65 % | 0.83 | 182401.06 | 182401.06 | 1100000 | 4.523e-06 | below ordermin | 0.0000 | -1.65 % |
| NEAR | NEAR/EUR | 0.41 % | 0.21 | 0.04816503 | 0.04816502 | 1 | 4.2562 | below ordermin | 0.0000 | -0.41 % |
| LINK | LINK/EUR | 0.36 % | 0.18 | 0.016946536 | 0.01694653 | 0.35 | 10.62164 | below ordermin | 0.0000 | -0.36 % |
| WLD | WLD/EUR | 0.21 % | 0.10 | 0.2661597 | 0.26615 | 9 | 0.3945 | below ordermin | 0.0000 | -0.21 % |

**onchain_longterm** (2026-10-28): no target above 0.

