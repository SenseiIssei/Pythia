# G1: P2's same-coin gap against the live twin, trade by trade

Pre-registration `results/pumpfun_gap_reconcile_g1_prereg.md`. Read only: `<data>/live/pumpfun_rt`, `<data>/paper/pumpfun_rt` and the recorded stream. Live trades signalled at or after 2026-10-28 19:40 UTC (P1's cut) with a P2 paper row (`selection_p2.compute`, unchanged) and a twin (`live_twin`, unchanged, these trades only). Points a trade, each side's return on its own stake. Bands: trade bootstrap, 2,000 draws, seed 0. Four trials in R5's registry, family pumpfun, counted only (`pumpfun:gap_g1:*`); no Sharpe, no DSR.

## The answer

- Sample: 12 of 37 live trades after the cut (every one left out named below).
- Paper minus twin (P - T): +19.5 points a trade (band -0.8 to +51.4), median -0.1; paper +1.3 %, twin -18.2 %, live -8.0 %.
- Paper minus live (P - L, P2's same-coin difference on these trades) +9.3 (band -15.2 to +44.9); live minus twin (L - T) +10.2 (band -1.8 to +24.8); check: +9.3 = +19.5 - (+10.2).
- Parts of P - T (mean points a trade): signal time -3.1 (-11.1 to +2.1), entry latency +0.0 (+0.0 to +0.0), entry size (curve impact) +0.0 (+0.0 to +0.0), entry price +27.5 (+0.1 to +75.0), exit rule +0.0 (+0.0 to +0.0), exit time -4.5 (-25.2 to +13.3), exit price -0.5 (-1.8 to +0.4), stake size (fixed fees) +0.0 (+0.0 to +0.0), fees and rent -0.0 (-0.1 to -0.0), failed buys +0.0 (+0.0 to +0.0); their sum +19.5 against the total +19.5 (within 0.5 points).
- Largest part: entry price (+27.5).

## The bridge to the headline numbers

P2's same-coin part (paper minus live on its matched pairs) by the era of the paper signal; the twin's -2.5 is 2026-10-22 to 24, no trade after the cut.

| era | matched pairs | paper minus live, mean points |
|---|---|---|
| ideal paper | 34 | +23.4 |
| realistic, before the cut | 14 | -2.7 |
| from the cut | 14 | +7.9 |

## Paper fills on a stale pool state (added after the first run)

Every paper row of P_pool0, P_pool0_wait signalled from the cut, P1's tainted and restart rows out. Stale: the coin's first pool read came after a pool trade of an older slot (the engine, `sim.Engine.pool_state`, drops a read once the stream has given a pool trade) and before the landing, and no pool trade came between the read and the fill, so the buy filled on the older trade's state. One trial more, `pumpfun:gap_g1:stale_reads`, counted.

| rule | rows | mean | stale: rows | stale: mean | the rest: rows | the rest: mean |
|---|---|---|---|---|---|---|
| P_pool0 | 641 | +4.7 % | 52 | +26.1 % | 589 | +2.8 % |
| P_pool0_wait | 770 | +2.2 % | 54 | +39.4 % | 716 | -0.6 % |

## Three records a trade

Times in s on the record's clock (live moved by the twin's offset), from the twin's signal; prices in SOL per 1e9 token units (x 1e9); returns in %.

| coin | day | offset s | paper signal | live / paper / twin landing | stake L / P / T SOL | Q SOL | entry L / P / T | exit why L / P / T | exit decision L / P / T | exit L / P / T | ret L / P / T | P - T | largest part | paper fill on a stale pool state |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| SOLCAT | 10-29 13:36:55 | +0.0 | -6.4 | +1.1 / -5.3 / +0.8 | 0.050 / 0.050 / 0.050 | 88 | 503.25 / 465.22 / 498.53 | take / take / take | +233.7 / +191.9 / +243.9 | 666.19 / 611.71 / 685.37 | +28.9 / +30.6 / +36.6 | -6.0 | signal time +9.1 | no |
| PillPad | 10-29 13:52:06 | +0.0 | +7.7 | +1.4 / +30.8 / +23.1 | 0.050 / 0.050 / 0.050 | 87 | 407.94 / 431.84 / 431.24 | take / take / take | +16.6 / +72.6 / +72.6 | 508.94 / 613.64 / 613.64 | +21.4 / +41.2 / +41.5 | -0.2 | signal time -43.7 | no |
| THEPM | 10-29 14:42:33 | +0.0 | -0.2 | +1.1 / +6.5 / +8.0 | 0.050 / 0.050 / 0.050 | 91 | 438.87 / 474.23 / 436.12 | stop / stop / stop | +37.8 / +28.9 / +62.8 | 343.88 / 365.98 / 99.82 | -22.3 / -23.7 / -78.0 | +54.3 | exit time +56.1 | no |
| GTA6 | 10-29 15:02:23 | +0.0 | -28.8 | +1.4 / -26.2 / +2.7 | 0.050 / 0.050 / 0.050 | 5038 | 1446559.46 / 1444921.25 / 1445267.66 | time / time / time | +301.4 / +273.8 / +302.7 | 1452804.73 / 1446783.20 / 1448437.21 | -0.9 / -0.7 / -0.6 | -0.1 | signal time +0.1 | no |
| WIFIO | 10-29 15:18:32 | +0.0 | -0.3 | +1.7 / +2.5 / +2.8 | 0.050 / 0.050 / 0.050 | 83 | 451.84 / 438.87 / 438.87 | stop / stop / stop | +18.6 / +69.8 / +69.8 | 367.07 / 60.80 / 60.80 | -20.0 / -87.0 / -87.0 | -0.0 | fees and rent -0.0 | yes |
| MCDOGE | 10-29 15:59:18 | +0.0 | -8.1 | +0.7 / +4.0 / +12.9 | 0.050 / 0.050 / 0.050 | 85 | 438.78 / 414.62 / 438.19 | stop / stop / stop | +20.5 / +54.0 / +22.4 | 337.02 / 340.80 / 331.88 | -23.5 / -18.7 / -25.1 | +6.4 | entry price +4.3 | no |
| USWR | 10-29 16:24:01 | +0.0 | -19.8 | +4.4 / -14.6 / +5.1 | 0.050 / 0.050 / 0.050 | 819 | 38281.49 / 38305.82 / 38097.74 | time / time / time | +304.4 / +285.4 / +305.1 | 39464.94 / 39189.63 / 39258.56 | +2.1 / +1.5 / +2.2 | -0.8 | entry price -0.6 | no |
| KATT | 10-29 16:34:38 | +0.0 | +19.4 | +0.8 / +20.8 / +2.0 | 0.050 / 0.050 / 0.050 | 83 | 375.78 / 398.62 / 392.05 | stop / stop / stop | +48.1 / +67.4 / +67.4 | 307.54 / 253.28 / 253.27 | -18.7 / -37.3 / -36.2 | -1.1 | signal time -2.8 | no |
| HEXN | 10-29 16:57:10 | +0.0 | -40.4 | +1.2 / -33.9 / +4.9 | 0.050 / 0.050 / 0.050 | 187 | 2042.89 / 634.15 / 2022.69 | take / take / take | +26.6 / -10.9 / +98.8 | 2743.17 / 1967.60 / 2608.66 | +30.8 / +209.4 / +28.1 | +181.3 | entry price +282.1 | yes |
| XTO | 10-29 17:03:24 | +0.0 | -6.9 | +2.7 / +5.8 / +12.5 | 0.050 / 0.050 / 0.050 | 670 | 25774.47 / 25889.34 / 25889.34 | time / time / time | +302.7 / +305.8 / +312.5 | 26732.18 / 26353.65 / 26353.65 | +2.7 / +0.9 / +1.0 | -0.0 | fees and rent -0.0 | no |
| NODF | 10-29 17:57:34 | +0.0 | -12.9 | +2.0 / -1.0 / +11.3 | 0.050 / 0.050 / 0.050 | 5630 | 1860861.64 / 1804365.63 / 1806183.31 | time / time / time | +302.0 / +299.0 / +311.3 | 1820194.02 / 1811824.55 / 1814700.04 | +0.3 / -0.4 / -0.4 | -0.1 | exit price -0.2 | no |
| USDF | 10-30 01:12:40 | +0.0 | -24.5 | +2.5 / -21.3 / +3.1 | 0.050 / 0.050 / 0.050 | 4041 | 930598.56 / 938479.09 / 938479.09 | stop / stop / stop | +100.7 / +154.7 / +154.7 | 1614.06 / 1650.28 / 1650.28 | -97.2 / -100.7 / -100.5 | -0.2 | fees and rent -0.2 | no |

Parts of each trade (points):

| coin | signal time | entry latency | entry size (curve impact) | entry price | exit rule | exit time | exit price | stake size (fixed fees) | fees and rent | failed buys | sum | P - T |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| SOLCAT 13:36:55 | +9.1 | +0.0 | +0.0 | +0.8 | +0.0 | -8.9 | -6.9 | +0.0 | -0.0 | +0.0 | -6.0 | -6.0 |
| PillPad 13:52:06 | -43.7 | +0.0 | +0.0 | +43.5 | +0.0 | +0.0 | +0.0 | +0.0 | -0.0 | +0.0 | -0.2 | -0.2 |
| THEPM 14:42:33 | +0.0 | +0.0 | +0.0 | -1.8 | +0.0 | +56.1 | +0.0 | +0.0 | -0.0 | +0.0 | +54.3 | +54.3 |
| GTA6 15:02:23 | +0.1 | +0.0 | +0.0 | -0.1 | +0.0 | -0.1 | -0.0 | +0.0 | -0.0 | +0.0 | -0.1 | -0.1 |
| WIFIO 15:18:32 | +0.0 | +0.0 | +0.0 | +0.0 | +0.0 | +0.0 | +0.0 | +0.0 | -0.0 | +0.0 | -0.0 | -0.0 |
| MCDOGE 15:59:18 | +0.0 | +0.0 | +0.0 | +4.3 | +0.0 | +0.4 | +1.8 | +0.0 | -0.0 | +0.0 | +6.4 | +6.4 |
| USWR 16:24:01 | +0.0 | +0.0 | +0.0 | -0.6 | +0.0 | +0.0 | -0.2 | +0.0 | -0.0 | +0.0 | -0.8 | -0.8 |
| KATT 16:34:38 | -2.8 | +0.0 | +0.0 | +1.8 | +0.0 | +0.0 | +0.0 | +0.0 | -0.0 | +0.0 | -1.1 | -1.1 |
| HEXN 16:57:10 | +0.3 | +0.0 | +0.0 | +282.1 | +0.0 | -100.9 | -0.1 | +0.0 | -0.0 | +0.0 | +181.3 | +181.3 |
| XTO 17:03:24 | +0.0 | +0.0 | +0.0 | +0.0 | +0.0 | +0.0 | -0.0 | +0.0 | -0.0 | +0.0 | -0.0 | -0.0 |
| NODF 17:57:34 | +0.1 | +0.0 | +0.0 | -0.0 | +0.0 | -0.0 | -0.2 | +0.0 | -0.0 | +0.0 | -0.1 | -0.1 |
| USDF 01:12:40 | +0.0 | +0.0 | +0.0 | +0.0 | +0.0 | +0.0 | +0.0 | +0.0 | -0.2 | +0.0 | -0.2 | -0.2 |

## Live trades after the cut left out

| why | trades |
|---|---|
| no P2 paper row: no paper record (the collector had the coin) | 17 |
| no P2 paper row: no paper record | 4 |
| no P2 paper row: paper buy failed | 2 |
| no twin: no pool state in the record | 2 |

## Reading (written 2026-11-02, after the numbers above)

- **The P3 gate should read P2's paper minus live (on the realistic paper from the cut), not the twin's -2.5,
  because on the same 12 trades the gap sits in the paper books' own fills (paper minus twin +19.5 points a trade,
  over the 2 points of rule 3), which the twin, signalled at live's time with live's inputs, never sees.**
- Why the two numbers disagree: first, they are not on the same trades. P2's +14.0 on the same coins is mostly
  its ideal-paper pairs (34 pairs, +23.4 points); on realistic paper before the cut it was -2.7 (14 pairs), from the
  cut +7.9 (14). The twin's -2.5 is 2026-10-22 to 24, before the cut, and has no trade after it. On the common sample
  (12 of 37 live trades after the cut) the identity holds: P - L +9.3 = P - T +19.5 - (L - T +10.2).
- Largest part of P - T: entry price, +27.5 points a trade, of which one trade carries +23.5: HEXN (2026-10-29
  16:56 UTC) was created and completed in one slot and migrated; the stream gave one pool trade in the migration
  slot, the collector's pool read of 81 slots later (186 SOL of effective quote against 105 after that trade)
  was in the record 0.15 s after it,
  and no further pool trade reached the stream for 30 s. `sim.Engine.pool_state` drops a pool read once the stream
  has given any pool trade ("a trade's state is as fresh or fresher"), so the paper buy landing 6 s later filled on
  the first trade's state at 634 against about 1,970 by the read (2,023 at the twin's fill) (paper +209 %, live +31 %, twin +28 %). Without
  HEXN, P - T is +4.8 on 11 trades, P - L -6.1. The next largest: THEPM +54.3 (exit time +56.1), a real difference:
  the paper's own latency fit landed it 1.5 s before the twin at a price 9 % higher, its -20 % stop fired at 29 s,
  the twin's at 63 s after a dump (twin -78 %, paper -24 %, live -22 %). Median P - T -0.1: the other ten agree
  within a few points.
- The defect is not one trade. Over every paper row from the cut, P_pool0 filled 52 of 641 on such a stale state
  (+26.1 % against +2.8 % for the rest; book mean +4.7 %), P_pool0_wait 54 of 770 (+39.4 % against -0.6 %; book
  mean +2.2 %). Counted as one more trial, found after the first run, not pre-registered.
- Decision rule 1 asks for a fix, but the defect is in `sim.py` (the engine's pool read), outside the files this
  study may change: no fix ships here, no book changes. The proposed fix: take a read whose slot is later than the
  token's last pool trade (`tok.amm_slot`). A strict xfail test pins the defect
  (`tests/test_pumpfun_gap_reconcile_g1.py`) and turns red once the engine is fixed. P_pool0's mean a trade on a fixed
  ledger is therefore not restated; the rows without a stale fill (+2.8 %) are only a hint, since a fixed engine
  would fill those 52 at the fresh price rather than drop them.
- Fragile: 12 trades on two days, band of P - T -0.8 to +51.4; live minus twin after the cut is +10.2 (band -1.8 to
  +24.8), not the -2.5 of 2026-10-22 to 24. 25 live trades after the cut fell out: 23 without a P2 paper row (21 no
  paper record, 2 paper buy failed), 2 without a twin (no pool state in the record).
