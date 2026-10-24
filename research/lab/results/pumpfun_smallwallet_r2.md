# pump.fun for a small wallet, under realistic execution (R2): result (2026-10-24)

Pre-registration: `results/pumpfun_smallwallet_r2_prereg.md` (committed before the first replay). Code:
`lab/pumpfun_rt/labels_r2.py` (the labels), `smallwallet.py` (the search), the paper books in `realistic.py`
(`SMALL`, `small_books`); tests `tests/test_pumpfun_smallwallet_r2.py`. Paper only; the live bot is unchanged.
Reproduce: `python -m lab.pumpfun_rt.smallwallet run --out DIR`. Record 2026-10-20 16:39 to 2026-10-24 00:00 UTC, R1's
model fitted to the live orders of the 7 days to the cutoff (buy median 8.8 s, sale 0.6 s, 97 buys, 95 sales).

## Short answer

- **Out of sample only two of the seven candidates make money per trade under realistic execution:
  `P_pool5_top30t` (+4.7 % per trade, +0.0046 SOL per entry at 0.1 SOL, band +0.0030 to +0.0057) and
  `P_pool0_wait_lock` (+1.4 %, band +0.0006 to +0.0022).** The live strategy `P_pool0_wait` loses (-1.6 % per trade,
  band -0.0022 to -0.0008 SOL per entry), and so do run20, free10_tight, the Y9 filter and P_hot5.
- **The highest median wallet and the highest chance to double are the same setting: `P_pool5_top30t` with 10 % of
  the wallet a trade, at most 3 open, brake off.** From 0.55 SOL the bootstrap's median is 6.1 SOL after 7 days and
  54 SOL after 30 (10 to 90 %: 41 to 78), 2x before -80 % on every path, 100 EUR after a median 3 days. On the two real
  days in order the same setting took 0.55 SOL to 1.03 SOL.
- **Only 23 of the 168 settings from 0.55 SOL (22 of 168 from 1.1) have a positive expectation, all of them with one
  of those two strategies.** Every `P_pool0_wait` setting is ruined within 30 days on every path; the owner's setting
  (100 %, one position, brake off) lost the 0.55 SOL wallet after 7 trades on the two real days. At 50 % or 100 % a
  trade even P_pool5_top30t is ruined on every path without the brake (with it, a median of 0.5 to 2.4 SOL): a few
  rugs in a row take the wallet.
- **These numbers are two days long.** The models a filter needs exist from 2026-10-22 on, so the registered
  out-of-sample window is 2026-10-22 and 2026-10-23; the bootstrap repeats those two days 30 times, and the picks were
  chosen among 336 settings on them. With 2026-10-21 added (not registered; the unfiltered candidates only) the
  P_pool0_wait family is positive (+3.9 % to +8.7 % per trade: 2026-10-21 alone made +3.3 to +5.3 SOL at 0.1 SOL a
  trade). The ranking depends on the day; the 30-day medians are what compounding a two-day mean does, not a forecast.

## 1. The labels at the realistic entry and exit

One replay of the record with the old and the realistic labels side by side (the same rows), base feature set,
purged walk-forward (models.md), walk-forward by day (Y9, from 2026-10-21) and X14's walk-forward.

| model | label | rate old | rate realistic | AUC old | AUC realistic |
|---|---|---|---|---|---|
| decision rows | win30 | 6.4 % | 5.3 % | 0.871 | 0.861 |
| | win300 | 4.5 % | 4.5 % | 0.816 | 0.804 |
| | up10 / up30 / up120 | 11.0 / 14.1 / 14.7 % | 9.6 / 12.4 / 13.5 % | 0.825 / 0.777 / 0.727 | 0.827 / 0.781 / 0.726 |
| Y9 select | win0 / win5 | 52.7 / 51.7 % | 51.8 / 53.0 % | 0.635 / 0.633 | 0.656 / 0.651 |
| | rug0 / rug5 | 7.9 / 7.6 % | 7.6 / 7.0 % | 0.676 / 0.647 | 0.589 / 0.568 |
| Y10 select | win5t (P_pool5_top30t's) | 51.7 % | 53.0 % | 0.646 | 0.662 |
| | rug0t / rug5t | 7.9 / 7.6 % | 7.6 / 7.0 % | 0.698 / 0.680 | 0.636 / 0.594 |
| X14 early | peak3x / peak10x | 2.1 / 0.30 % | 1.7 / 0.24 % | 0.834 / 0.766 | 0.830 / 0.766 |

A realistic buy fills later and dearer (the early rows' 0.1 SOL buy fills 94 % of the time, against 98 %), so the
win and up labels are rarer, and the win models keep or gain a little AUC. The rug labels, measured from the
realistic landing, are much harder to predict (AUC down 0.06 to 0.09): a good part of what the old rug models saw was
a crash in the seconds the live bot does not get anyway. The top 30 % of win5t's realistic scores made +7.2 % per
trade (old labels' model: +2.9 %). The daily retrain trains every such model on the realistic labels from the next
study on, and the old ones as `_ideal` in `models/pumpfun_rt/ideal/` until 2026-11-07 (`models.md`, `select.md`,
`early_exit.md` show both).

## 2. The small-wallet search

Each candidate a realistic book at 0.1 SOL without limits; the wallet with the live sizing (limits=wallet, floor 0,
2 % of the pool at most, the stake's impact rescaled), 2,000 paths of 30 days from the out-of-sample days, 1 SOL = 91
EUR. Per entry at 0.1 SOL:

| strategy | entries | mean per trade | P&L per entry SOL (90 % band) | 2026-10-22, 23 SOL |
|---|---|---|---|---|
| P_pool0_wait | 482 | -1.6 % | -0.0016 (-0.0022 to -0.0008) | -0.16, -0.59 |
| P_pool0_wait_lock | 482 | +1.4 % | +0.0013 (+0.0006 to +0.0022) | +0.46, +0.17 |
| P_pool0_wait_run20 | 482 | -2.7 % | -0.0026 (-0.0039 to -0.0009) | -0.19, -1.06 |
| P_pool0_wait_free10_tight | 482 | -2.9 % | -0.0027 (-0.0041 to -0.0017) | -0.85, -0.46 |
| P_pool0_top30 | 141 | -1.5 % | -0.0015 (-0.0041 to +0.0020) | +0.12, -0.33 |
| P_pool5_top30t | 223 | +4.7 % | +0.0046 (+0.0030 to +0.0057) | +0.26, +0.76 |
| P_hot5 | 49 | -5.4 % | -0.0050 (-0.0161 to +0.0058) | +0.14, -0.39 |

From 0.55 SOL (50 EUR), wallet after 30 days:

| strategy | share | max open | brake | median SOL | 10 to 90 % | after 7 days | 2x before -80 % | ruin | days to 100 EUR |
|---|---|---|---|---|---|---|---|---|---|
| P_pool5_top30t | 10 % | 3 | off | 54.4 | 41.1 to 78.0 | 6.1 | 100 % | 0 % | 3 |
| P_pool5_top30t | 10 % | 2 | off | 49.6 | 38.0 to 72.5 | 4.6 | 100 % | 0 % | 3 |
| P_pool5_top30t | 10 % | 1 | off | 41.1 | 38.5 to 46.5 | 2.8 | 100 % | 0 % | 3 |
| P_pool5_top30t | 25 % | 3 | off | 24.2 | 10.7 to 48.1 | | 100 % | 0 % | 2 |
| P_pool0_wait_lock | 10 % | 3 | off | 4.8 | 3.0 to 6.8 | 1.2 | 100 % | 0 % | 6 |
| P_pool5_top30t | 10 % | 3 | on | 4.6 | 3.9 to 5.4 | 1.8 | 100 % | 0 % | 3 |
| P_pool0_wait_lock | 10 % | 3 | on | 1.7 | 1.5 to 1.9 | 1.1 | 100 % | 0 % | 7 |
| P_pool0_wait | 100 % | 1 | off (the owner's) | 0.06 | 0.06 to 0.07 | 0.06 | 0 % | 100 % | never |
| P_pool0_wait, any setting | | | | 0.07 or less | | | 0 % | 100 % | never |

From 1.1 SOL (100 EUR) the order is the same: P_pool5_top30t 10 %, 3 open, brake off, median 55.8 SOL, 200 EUR after a
median 3 days; P_pool0_wait_lock's best 5.1 SOL. The full grid is in `reports/pumpfun_rt/smallwallet.md` when re-run.

What the grid says beyond the two days:

- 10 % a trade beats 25 % and far beats 50 to 100 % for every strategy with an edge; the minimum stake (0.05 SOL)
  is already 9 % of 0.55 SOL, so a smaller wallet cannot spread its risk more.
- The live brake falls to the minimum stake in a 30 % drawdown and stays there while the wallet has grown, so with an
  edge it cuts the median about tenfold; without an edge it does not prevent ruin (0.05 SOL a trade still loses the
  wallet).
- More slots help a strategy with an edge (more of its signals taken) and hurt one without.

## 3. The paper books

The registered picks (a) highest median, (b) highest chance to double, (c) lowest ruin with a median above the start,
distinct, are three settings of the same strategy: `P_pool5_top30t_sw10o3n`, `_sw10o2n` and `_sw10o1n` (10 % of the
wallet, 3, 2 or 1 open, brake off). They run from the deploy in the collector, each on its own 0.55 SOL paper wallet
with the realistic fills, next to the other paper books in `paper/pumpfun_rt/ledger.csv`; their wallets in SOL and EUR
are in `reports/pumpfun_rt/realistic.md` (daily 06:40) and on the daily card. They trade once the retrain has written
`sel_win5t` (the study after the deploy writes the select rows with the trend features).

## What it means for the owner

The live bot as set (P_pool0_wait, 100 % of the wallet, one position, brake off) is the worst corner of this grid: no
setting of P_pool0_wait survives the two out-of-sample days in the bootstrap. If the live bot trades at all, 10 % of
the wallet a trade is the share that survives, and the strategy with an edge on these days is P_pool5_top30t, not
P_pool0_wait. Two days are not enough to move real money on: the three paper books show over the next two weeks
whether P_pool5_top30t's edge holds. The live bot is unchanged; the owner decides.
