# Is the factory's shadow low-vol genome more than its BTC gates?

Run 2026-10-21 as registered in `results/genome_gates_prereg.md` (committed
first). Code: `lab.experiments.genome_gates`. The tables below the marker are
generated.

## What it says

**Kill. The factory's only held-back pass is an effect of its gates.** The
run reproduced the factory's numbers exactly (0.876 at 35 bps, 0.689 at 70),
then:

- **Null A** (the same genome choosing its 5 by liquidity, not low vol) makes
  0.81 at 35 bps with a higher CAGR (26 % against 25 %). D_A is -0.21 at
  35 bps and -0.24 at 70; its band runs from -1.22 to 1.01. The low-vol
  ranking adds nothing over picking the 5 biggest coins under the same
  gates; the two pick the same set on only 17 % of days but share 3.4 of 5
  coins on average, and the genome's weight sits in BTC, BNB, ETH, XRP, SOL
  and TRX (91 %).
- **Null B** (BTC alone under the same three filters) makes 0.68 with a
  27 % drawdown against the genome's 35 %. D_B is 0.47 (band -0.47 to 1.44):
  holding five majors instead of BTC may help, but it is not shown.
- The book is in cash on 61 % of held-back days; whatever it earns, it earns
  on the days both BTC gates are on.

As registered, the write-up recommends that the owner retire 44444c97ba5e from
the factory's shadow and records that the factory's only low-vol pass is a
gate effect. This study does not touch the factory's state. Its deflated p
over the pool of 1,724 is 0.0010.

<!-- generated below by lab.experiments.genome_gates; edit above this line only -->

# Genome 44444c97ba5e against its gates: results

Generated 2026-10-20T22:07:11+00:00. Registered in `results/genome_gates_prereg.md` before the run.

Genome: low vol · top 20 · BTC 28d up · BTC > MA200 · vol < 120 % · best 5 by signal · equal full · every 3d band 50 %. Null A: low vol · top 20 · BTC 28d up · BTC > MA200 · vol < 120 % · best 5 by liquidity · equal full · every 3d band 50 %. Null B: BTC alone at full weight while the same three filters let it in, same cadence and band.

Held back 2024-01-01 to 2026-10-14 (1018 days). Reproduced: 0.876 at 35 bps and 0.689 at 70 (factory 0.876 / 0.689). BTC bought and held: Sharpe 0.74, drawdown 53 %.

## Verdict

**Kill.** The genome's held-back result is an effect of its gates.

## The genome and the nulls

| book | sharpe_35bps | sharpe_70bps | cagr_35bps_pct | dd_35bps_pct | y2024 | y2025 | y2026 | exposure_pct | cash_days_pct | turnover_yr | deflated_p |
|---|---|---|---|---|---|---|---|---|---|---|---|
| genome 44444c97ba5e | 0.88 | 0.69 | 25.36 | 34.56 | 1.49 | 0.31 | 0.60 | 38.33 | 60.71 | 16.61 | 0.00 |
| null A: same genome, best 5 by liquidity | 0.81 | 0.66 | 26.47 | 37.19 | 1.92 | -0.29 | 0.65 | 38.25 | 60.71 | 15.30 | 0.00 |
| null B: BTC alone under the same filters | 0.68 | 0.52 | 16.78 | 27.10 | 1.27 | -0.36 | 0.88 | 39.29 | 60.71 | 12.91 | 0.00 |

## The differences

| difference | sharpe_35bps | sharpe_70bps | mean_ann_35bps | boot_p05 | boot_p95 | boot_above0 | y2024 | y2025 | y2026 | corr | deflated_p |
|---|---|---|---|---|---|---|---|---|---|---|---|
| D_A (genome minus null A) | -0.21 | -0.24 | -0.03 | -1.22 | 1.01 | 0.42 | -1.50 | 1.45 | -0.51 | 0.93 | 0.00 |
| D_B (genome minus null B) | 0.47 | 0.39 | 0.08 | -0.47 | 1.44 | 0.79 | 0.37 | 1.08 | -0.66 | 0.85 | 0.00 |

Bootstrap: stationary, mean block 20 days, 4000 draws, seed 20261020, 5 % and 95 % of the Sharpe of the daily difference at 35 bps.


Overlap with null A: the two target sets are identical on 17 % of the 406 held-back days on which either holds anything; they share 3.4 coins on average.


The genome's held-back target weight by coin: BTCUSDT 20 %, BNBUSDT 20 %, ETHUSDT 18 %, XRPUSDT 12 %, SOLUSDT 11 %, TRXUSDT 10 %, DOGEUSDT 2 %, LTCUSDT 2 %, AVAXUSDT 1 %, SHIBUSDT 1 %.


## Pool

1,724 trials (1,115 hand, 600 factory, 9 registered today); the best noise trial sits at an annual Sharpe of about 2.72. The genome's deflated p over it: 0.0010.
