# m4_perps forward record audit (2026-11-23)

Pre-registered in `results/m4_perps_forward_audit_prereg.md` (its own commit, before any number). Code:
`lab.paper.m4_perps_audit`; machine output: `results/m4_perps_forward_audit_run.md`. Read only; nothing a live bot,
a wallet or the engine reads was changed. No trial: R5's registry does not change.

## Verdict

The record is right; two of its labels were not. The equity of every row adds up (check 1: 0 rows off), the marks are
Binance mids (check 4: every coin-day off the hour bars is inside them, Binance's minute bars agree to a median 9 bps,
no frozen mark) and the funding is Binance's to the hundredth of a bp (check 5). The rebuilt targets miss on 8.2 % of
coin-days (check 3, over the 5 % rule), and each miss is the replay's, not the book's: on the one day whose model the
server kept, that model gives the booked targets exactly. So nothing is frozen. Wrong were the cost ratio (0.15: the
journal booked m4_residual's 41 bps as the model, the band assumed 8.8), the day count (30: three runs on 2026-10-21
counted as three days) and the weekly capital line (six zero steps for days the book did not run). All three are fixed
in code with tests that fail before the fix, and the series is restated below.

## Old and corrected, through 2026-11-22

| | old (`reports/forward/latest.json`, weekly page of 2026-11-22) | corrected |
|---|---|---|
| return | +15.91 % | +15.91 % (the equity is right) |
| max drawdown | 0.93 % | 0.93 % on the 28 recorded days; with the 5 missing days estimated from Binance spot at the run minute (the 11-04 target held) still 0.93 %, the deepest dip inside the gap -0.89 % (11-06 to 11-07) |
| days of record | 30 (rows) | 28 (dates with a run; 33 calendar days, 5 missing) |
| gate 7 | 30 of 30 days, 16 of 30 rebalances | 28 of 30 days, 16 of 30 rebalances |
| paper costs against the model | 0.2376 % against 1.5845 %: 0.15x | 0.2376 % against 0.3401 %: 0.70x |
| forward band (30 days, 910 days of the frozen M4L series) | -13.5 % to +17.4 %, median +2.1 %: inside | unchanged: inside (it depends on the elapsed days, 32) |
| W2 lower band a month (dated reports through 11-22) | +4.99 % (32 points, 6 of 31 steps zero) | +5.39 % (26 points, no zero step) |
| W2 capital for 180 EUR a month | 3,608.56 EUR | none on 2026-11-22: 28 days of record, under W2's 30. From 30 days (2026-11-24 on) a figure again; on the corrected points it is 3,337 EUR with the reports through 11-22 and 4,343 EUR with 11-23's -0.63 % added |

The corrected band is a little wider and higher, not narrower: the zero days pulled the mean down more than they
shrank the spread. The figure the page printed was not too low because of stale marks; it should not have been
printed yet.

## Per day

All 30 journal rows through 2026-11-22. gross rebuilt: the previous target times Binance spot's hourly bars
interpolated at the run's end time; coin-days off: pinned coin returns more than 75 bps from that, in brackets those
explained (Binance's minute bars within 75 bps, or the booked return inside what prices inside the two hour bars
allow, 10 bps of slack for the perp's basis and the journal's 4 decimals); targets off: mismatched coin-days of the
rebuild (0.01). The band model is 8.8 bps per unit traded.

| date | equity | gross booked | gross rebuilt (spot) | diff bps | coin-days off 75 bps (explained) | funding booked / Binance bps | turnover | paper / model 41 / band model bps | targets off | verdict |
|---|---|---|---|---|---|---|---|---|---|---|
| 2026-10-21 | 10,000.00 | +0.0000 % |  | | | | 0.0000 | 0.00 / 0.00 / 0.00 | | no day of record: empty book |
| 2026-10-21 | 10,000.00 | +0.0000 % |  | | | | 0.0000 | 0.00 / 0.00 / 0.00 | | no day of record: empty book, re-run |
| 2026-10-21 | 9,994.35 | +0.0000 % |  | | | | 1.0000 | 5.65 / 41.00 / 8.80 | 4/22 | re-run, the day's record; targets: refit drift (model not kept) |
| 2026-10-22 | 10,070.87 | +0.7685 % | +0.6863 % | +8.2 | 1 (1) | -0.29 / -0.29 | 0.0000 | 0.00 / 0.00 / 0.00 | 0/20 | matched |
| 2026-10-23 | 10,167.40 | +0.9559 % | +1.0779 % | -12.2 | 6 (6) | +0.26 / +0.26 | 0.0000 | 0.00 / 0.00 / 0.00 | 0/20 | matched |
| 2026-10-24 | 10,335.57 | +1.6566 % | +1.5279 % | +12.9 | 4 (4) | -0.26 / -0.26 | 0.0000 | 0.00 / 0.00 / 0.00 | 0/20 | matched |
| 2026-10-25 | 10,438.69 | +1.0018 % | +1.1419 % | -14.0 | 2 (2) | +0.19 / +0.20 | 0.0929 | 0.60 / 3.81 / 0.82 | 0/20 | matched |
| 2026-10-26 | 10,413.94 | -0.2359 % | -0.2330 % | -0.3 | 0 (0) | -0.12 / -0.12 | 0.0000 | 0.00 / 0.00 / 0.00 | 0/20 | matched |
| 2026-10-27 | 10,386.14 | -0.2641 % | -0.2941 % | +3.0 | 3 (3) | -0.29 / -0.29 | 0.0000 | 0.00 / 0.00 / 0.00 | 0/20 | matched |
| 2026-10-28 | 10,404.73 | +0.1865 % | +0.0696 % | +11.7 | 1 (1) | -0.75 / -0.75 | 0.0000 | 0.00 / 0.00 / 0.00 | 0/20 | matched |
| 2026-10-29 | 10,450.86 | +0.4545 % | +0.7854 % | -33.1 | 10 (10) | -0.51 / -0.51 | 0.0904 | 0.61 / 3.71 / 0.80 | 0/20 | gross off the interpolated bars, inside their range |
| 2026-10-30 | 10,645.80 | +1.8570 % | +1.7697 % | +8.7 | 5 (5) | +0.83 / +0.84 | 0.0000 | 0.00 / 0.00 / 0.00 | 0/20 | matched |
| 2026-10-31 | 10,597.28 | -0.4459 % | -0.7066 % | +26.1 | 5 (5) | +0.22 / +0.22 | 0.1904 | 1.21 / 7.81 / 1.68 | 2/21 | gross off the interpolated bars, inside their range; targets: refit drift (model not kept) |
| 2026-11-01 | 10,603.26 | +0.0347 % | +0.3530 % | -31.8 | 2 (2) | +2.65 / +2.64 | 0.0859 | 0.48 / 3.52 / 0.76 | 0/20 | gross off the interpolated bars, inside their range |
| 2026-11-02 | 10,706.01 | +0.9631 % | +0.8087 % | +15.4 | 2 (2) | +0.59 / +0.59 | 0.0000 | 0.00 / 0.00 / 0.00 | 0/20 | matched |
| 2026-11-03 | 10,884.05 | +1.6737 % | +1.6110 % | +6.3 | 1 (1) | +0.27 / +0.27 | 0.1790 | 1.31 / 7.34 / 1.58 | 2/21 | targets: refit drift (model not kept) |
| 2026-11-04 | 10,782.48 | -0.9332 % | -0.8581 % | -7.5 | 0 (0) | -0.01 / -0.01 | 0.0000 | 0.00 / 0.00 / 0.00 | 0/20 | matched |
| 2026-11-10 | 10,896.79 | +1.0402 % | +1.1056 % | -6.5 | 1 (1) | +2.56 / +2.56 | 0.0995 | 0.56 / 4.08 / 0.88 | 2/21 | spans 6.18 days: 11-05 to 11-09 missing (job skipped, heavy lock busy); targets: refit drift (model not kept) |
| 2026-11-11 | 10,914.20 | +0.1590 % | +0.0535 % | +10.5 | 1 (1) | +0.08 / +0.08 | 0.0000 | 0.00 / 0.00 / 0.00 | 0/20 | matched |
| 2026-11-12 | 11,052.49 | +1.2749 % | +1.3837 % | -10.9 | 0 (0) | -0.16 / -0.16 | 0.0882 | 0.61 / 3.61 / 0.78 | 0/20 | matched |
| 2026-11-13 | 11,039.18 | -0.1175 % | -0.0289 % | -8.9 | 3 (3) | +0.23 / +0.23 | 0.0775 | 0.53 / 3.18 / 0.68 | 0/20 | matched |
| 2026-11-14 | 11,048.35 | +0.0841 % | -0.1343 % | +21.8 | 6 (6) | +0.61 / +0.61 | 0.0963 | 0.70 / 3.95 / 0.85 | 2/21 | gross off the interpolated bars, inside their range; targets: refit drift (model not kept) |
| 2026-11-15 | 11,205.05 | +1.4138 % | +1.5315 % | -11.8 | 1 (1) | +0.95 / +0.95 | 0.0884 | 0.49 / 3.62 / 0.78 | 2/21 | targets: refit drift (model not kept) |
| 2026-11-16 | 11,276.42 | +0.6616 % | +0.5103 % | +15.1 | 3 (3) | +0.58 / +0.58 | 0.4892 | 3.03 / 20.06 / 4.30 | 10/25 | targets: refit drift (model not kept) |
| 2026-11-17 | 11,196.98 | -0.5795 % | -0.4239 % | -15.6 | 3 (3) | -10.62 / -10.62 | 0.2799 | 1.89 / 11.47 / 2.46 | 2/21 | targets: refit drift (model not kept) |
| 2026-11-18 | 11,319.65 | +1.1703 % | +1.1663 % | +0.4 | 3 (3) | -7.46 / -7.46 | 0.0000 | 0.00 / 0.00 / 0.00 | 0/20 | matched |
| 2026-11-19 | 11,283.39 | -0.2247 % | -0.1658 % | -5.9 | 1 (1) | -5.10 / -5.10 | 0.7216 | 4.48 / 29.58 / 6.35 | 14/27 | targets: the run had 70 liquid candidates (51 listed), as m4_hl_small that morning |
| 2026-11-20 | 11,526.35 | +2.1533 % | +2.1208 % | +3.2 | 0 (0) | -0.00 / -0.00 | 0.0000 | 0.00 / 0.00 / 0.00 | 0/20 | matched |
| 2026-11-21 | 11,665.35 | +1.2038 % | +1.2129 % | -0.9 | 4 (4) | +0.74 / +0.74 | 0.0939 | 0.53 / 3.85 / 0.83 | 0/20 | matched |
| 2026-11-22 | 11,591.50 | -0.6253 % | -0.6118 % | -1.3 | 9 (9) | +0.29 / +0.29 | 0.1917 | 1.08 / 7.86 / 1.69 | 8/24 | targets: refit drift, the kept model matches 0 off |

## 1 and 2. Arithmetic and calendar

Every row's equity is the previous one times (1 + gross + funding) times (1 - paper cost), within 1 bp: 0 rows off.
33 calendar days from 2026-10-21 to 11-22, 28 with a run. 10-21 has three rows: two runs at 15:47 and 15:48 (they
overlapped) with an empty book and the first real entry at 16:00; the forward report counted all three. No run from
2026-11-05 to 11-09: the row of 11-10 carries 6.18 days of moves in one step (+1.04 % gross, +2.56 bps funding).

## The flat days 2026-11-04 to 11-10: a job outage (check 2)

The dated forward reports show +7.82 % from 11-04 to 11-10 because the journal has no row in between, not because
marks stood still. `<data>/_ops/runs/2026-11.jsonl`: `paper-m4-perps` started at 05:15 on 11-05, 11-06, 11-07, 11-08,
11-09 and 11-10 and gave up each time after 2 h, `"status": "skipped", "reason": "lock heavy busy"`;
`pumpfun-rt-study` (03:30, 13,262 to 15,225 s) held the heavy lock until 07:11 to 07:43 each morning. The same lock
skipped `paper-funding-carry` and `paper-m4-hl-small` (or they failed at its timeout), which is why those froze on the
same days. The book ran again at 09:38 on 11-10, outside its schedule; lane 12036 found the cause and the study had been moved to
18:30 (`reports/lanes/12036-care-paper-m4-perps.json`). Since 11-11 every 05:15 run is ok. The missing days are now
counted as missing: the forward report counts dates with a run, and W2 takes no point from a dated report whose book
did not run since the one before; the next run's step covers all its days.

The equity carried across the gap is right: the 11-10 row's gross against the spot path is -6.5 bps off, and the
target held through the gap, marked at the run minute on each missing day, makes 10,901.69 against the booked
10,896.79 (funding and the 11-10 rebalance account for the rest).

## 3. Targets

The frozen panel the band names (sha256 36774aa37afa) is cut at 2026-06-30 and holds no forward day, so the targets
were rebuilt from today's xs_daily panel, cut at each decision day, with reg7n refit at each `model_trained` day.
The decision day is not D - 1: Binance's daily perp archive of day X lands at X + 2 03:35 UTC (the files' times), so
at 05:15 the book's own lag rule (`MAX_LAG_DAYS`, `MIN_SCOREABLE`) decides on D - 2, as m4_hl_small's orders say
(`decision_day` 2 days back on most mornings). Replayed that way: 48 mismatched coin-days of 584, 8.2 %.

- 2026-11-22, 8 coin-days: the refit's target; the model the server kept (trained for 2026-11-17, the only one it
  keeps) gives the booked target with 0 mismatches. The refit and the kept model rank the same day's candidates with
  a correlation of 0.977 and share 17 of the 20 end names; the refit trains on 560,157 rows, the kept one on 559,972
  (the panel has been revised since).
- 2026-11-19, 14: the run had 70 liquid candidates (51 listed and 19 dropped as unlisted) where today's panel has 100;
  m4_hl_small's run that morning shows the same 51. The kept model does not remove them (14): an input of the run.
- 26 on eight other days (one or two names a day, five on 11-16's large rebalance): days whose models the server no
  longer has, refit like 11-22's. Without 11-19 and 11-22: 26 of 533 coin-days, 4.9 %.

The record's equity follows from its booked weights (checks 1, 4, 5); the replay cannot tell a refit's drift from a
code error on days without the model, and on the one day it can, the book is right. The pre-registration counts
mismatches from revised data as revisions; this audit freezes nothing. What would settle it: keep each week's model
next to the book (care work, not a trial).

## 4. Marks

508 coin-days are pinned by the journal (held in both rows, under the cap, not traded). Against the hour bars
interpolated at the run, 77 are more than 75 bps off (15.2 %, over the 5 % rule): the hour bar is coarser than the
prediction assumed. Where Binance's minute bars exist (169 coin-days, the majors) the booked returns are a median
9.0 bps from them; ETH from 11-20 to 11-21 is booked -9.02 %, the minute bars say -8.99 % while the hour bar's
interpolation says -9.80 %. All 77 off coin-days are explained: 12 by the minute bars, 65 by lying inside what
prices inside the two hour bars allow. Kraken Futures' marks (189 coin-days) are 24 bps from the book in the median,
like the hour bars. Two coin-days book a return under 1 bp while the interpolated bar moved over 50 bps (ETHFI on
10-29, INJ on 11-18). Both are inside their hour bars (ETHFI's 05:00 bar on 10-29 ran from 0.6583 to 0.6702 around
the day before's 0.6678; INJ's from 7.236 to 7.419 around 7.378), and the code has no way to hold a mark: every run
reads all of Binance's bookTicker afresh and a coin without a quote is closed, not carried (`m4_perps.mark`). A pinned
return carries about 20 bps of the journal's rounding (weights to 4 decimals), so two near zero in 508 say nothing. Per row, 27 rows are
fully priced: 4 are more than 20 bps off (10-29 -33.1, 10-31 +26.1, 11-01 -31.8, 11-14 +21.8), each inside the
bounds of its hour bars; the sum is -17.2 bps (tolerance 50).

## 5. Funding

The booked funding is minus the previous target times Binance's settlements since the previous run's start, on every
row: -0.1452 % booked, -0.1451 % from `<data>/hist/binance_um/funding`, -0.01 bps apart over the record. Kraken's
hourly funding on the coins it covers (a quarter to a third of the gross) would have been -0.11 %: the book books the
funding of the venue it marks on, not of the one its signal routes to.

## 6. The cost ratio of 0.15

The paper fill charges Binance USD-M's taker, 5 bps (`m4_ls.TAKER_UM`), plus Binance's quoted half spread at the run
(`(ask - bid) / mid / 2` from bookTicker), 1.15 bps per unit traded on average, on 3.8648 units over 16 rebalances:
0.2376 %. No impact, no Kraken spread. The model column booked `MODEL_COST = xs.COSTS["41bps"]`, the cost m4_residual's
evidence is quoted at, on the same turnover: 1.5845 %. Every row fits both identities within 0.02 bps. The band this record
is held against is M4L's series (`m4l_series.json`, book m4_perps): Kraken's taker 5 bps plus DT1's spread proxy
3.77 bps per unit traded, 8.77 bps. M4L fixed the same mislabel for m4_hl_small (`MODEL_SLIP`), not for m4_perps.
Against the band's cost the ratio is 0.70: the paper fill is cheaper than the backtest because the most liquid Binance
perps quote about 1 bp half spreads at 05:15, below DT1's proxy, and the fill charges no impact. It says nothing about
Kraken's book, where the signal would trade. Fixed: `m4_perps.MODEL_COST` is 5 + 3.8 bps, and the forward report
restates every older row booked at 41 bps to 8.8 bps (`forward_report.MODEL_RESTATED`; the journal is not rewritten).

## 7. The 12-point gap to m4_hl_small

m4_perps +15.91 %, m4_hl_small +3.94 % through 2026-11-22: +11.97 points. On the twin's own days (its first run at
18:12 on 2026-10-30 to 11-22) m4_perps made +8.88 %. Additive per pair of the twin's runs, at Binance spot's prices:

| part | points | what |
|---|---|---|
| timing | +4.10 | +6.46 m4_perps made before the twin started; -2.36 the run hours (05:15 against 06:00) and the twin's skipped and late runs of 11-05 to 11-10, on the twin's positions |
| funding | +2.21 | m4_perps paid -0.15 % at Binance's rates, the twin -2.35 % at Hyperliquid's hourly rates (-0.73 % and -0.61 % on 11-11 and 11-12 alone) |
| costs | +0.28 | the twin's paper costs 0.45 % (its 230 USD orders walk Hyperliquid's book) against m4_perps' 0.17 % on the twin's days |
| universe | -0.71 | coins only one venue lists, one or two names a book: BAT, KAVA, MOVR, MUBARAK, NIGHT, QNT, XAUT held by m4_perps; ALT, CHIP, INIT, LUNC, MEGA, MET, NIL, SOPH by the twin |
| fills | +5.00 | +5.00 different weights on coins both list: each book ranks among its own list (70 against 74 listed coins a day) and buffers from its own start, so they share 13 of 20 names on the same side on average; the booked marks against spot add -0.02 (m4_perps) and +0.03 (the twin's Hyperliquid mids, whole units) |
| residual | +1.10 | compounding (+6.46 % then +8.88 % is +15.91 %, not +15.34 %) |

Most of the gap is when the books started and which names each one's list let it hold; Hyperliquid's funding is the
largest cost difference. Execution is not: both books' marks sit on the market within 3 bps of gross over the period.

## Fixes (each with a test that fails before it)

- `lab.paper.m4_perps`: `MODEL_COST` is the band's cost (5 bps taker plus DT1's proxy 3.8 bps), was 41 bps.
- `lab.paper.forward_report`: `days` and gate 7 count the dates a book ran on (a re-run is one day); `MODEL_RESTATED`
  restates m4_perps' rows booked at 41 bps at 8.8 bps.
- `lab.ops.weekly` (W2): a dated forward report whose book did not run since the one before is no point; a forward
  book's days of record are at most the days it ran on.
- Tests: `tests/test_m4_perps_audit.py` (the checks on synthetic journals, bars and files; the three fixes),
  `tests/test_weekly.py` (two cases).

## What could fool us

The minute bars cover 21 coins, the majors; the other coins' explanation is a bound (inside the hour bars), not a
match. Today's panel and Kraken listing are not the ones the runs saw. A 30-day record catches bugs, not edge: the
book is inside its band, and +15.9 % against a backtest median of +2.1 % over the same days is more likely luck than
the 0.71 Sharpe the series has (review, section 3).
