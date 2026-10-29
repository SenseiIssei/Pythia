# OS1: a least-squares Monte Carlo exit and a conditional GPD crash exit for P_pool0

PAPER ONLY. Nothing here holds a wallet, reads a key, signs or sends anything; the live service, its executor, its
exits, its sizing and its confirmation file were not touched.

Pre-registration: `results/pumpfun_os1_prereg.md` (2 trials in R5's registry, committed before the first run). Code:
`lab/pumpfun_rt/os1.py`; tests: `tests/test_pumpfun_os1.py`. Data: the server's record, 2026-10-20 16:40 UTC to E2's
cutoff 2026-10-29 19:30 UTC, signals to 19:20 UTC; in sample the UTC days 2026-10-20 to 23, out of sample 2026-10-24 to
the cutoff (6 days). E2's latency (the live executor's 34 P_pool0 buys and sales since 2026-10-29 00:00 UTC, sales a
median 0.6 s; L = 595 ms). Every P_pool0 signal entered at 0.05 SOL, every exit on the same entries with the same
latency draws (paired by entry). Built on 12007 (X14 r2): its replay (`flowexit.FlowPipe`), its paths and its X0;
none of X14 r2's exits passed, so the only base is P_pool0 as it is (X0).

## Short answer

**No. Neither model beats P_pool0's exits.**

- **E1, optimal stopping by least-squares Monte Carlo** (Longstaff and Schwartz; the take and the 300 s time stop as
  caps, no -20 % stop, the sale one latency later): **-1.4 points per entry** against X0 (band -2.3 to -0.5, DSR 0.000).
  It does what it was built for on the losers: on X0's 457 stopped trades it is +12.1 points better (no stop exits at
  all, and losses are cut earlier). It pays that back and more on the rest (-9.0 points): it sells 1,063 of 1,270
  positions on its own, 575 of them above the entry, and lets only 193 reach the +30 % take (X0: 381). The value of
  holding is estimated as lower than selling far too often, because the expected continuation from a state is the
  average over paths that end in a dump about a third of the time (X0 stops 36 % of its entries).
- **E2, conditional peaks over threshold** (McNeil and Frey; the largest fall in the 10 s after L, a generalised Pareto
  tail whose scale and exceedance probability depend on the state): the level fitted in sample, lambda 0.10, **never
  fires**, in sample or out of sample. The model never puts P(fall > 30 %) above 4.6 % for any second out of sample
  (median 1.75 %, the base rate 1.75 %). So E2 is X0 (+0.0 points). At lambda 0.05 it sold 461 seconds in sample and
  lost 0.4 points; at 0.02 it sells almost everything (+0.5 % against +13.0 %).
- **The tail itself is modelled well, but the state hardly moves it.** The shortfall backtest holds: F is above the
  model's 95 % VaR on 5.0 % of the out-of-sample seconds (5 % expected), and on those the mean fall is 32.4 % against a
  predicted ES of 34.9 %. The shape is heavy and steady (xi +0.27 to +0.40 by day, threshold u about 0.10). But the
  ranking is weak (AUC 0.60, Brier skill +0.002 against a constant hazard): before X0's stops it gave a 30 % crash
  2.2 % on average, about the base rate of 1.8 %. The crash is a matter of the heavy tail, not of the state we can see.

Nothing is added to the pipeline (section 6).

## 1. Record and entries

1,915 entries (19 failed buys), 1,270 out of sample (11 failed buys), 108,938 lamports a transaction. The path
simulator here (`os1.simulate`, flowexit's with own signal times and the stop optional) reproduces flowexit's X0 on
100.0 % of the entries. Out of sample X0 makes +7.8 % per entry on paper (E2 found the same, +7.8 % on 1,270): the level
is paper; the comparison is paired, so it cancels.

## 2. The exits out of sample (judged)

Mean and P&L per entry over 0.05 SOL after every cost; band: day-block 90 % band of the paired difference (6 days);
DSR: the paired differences' Sharpe per entry (on its day-clustered effective entries) deflated against 3,762 trials
(R5's registry with these two, and F3's 525), F3's 299 per-entry Sharpes as the noise (the bar: a Sharpe per entry of
1.12).

| exit | entries | mean | median | win | P&L SOL | stops: n, mean | exits | vs X0 | band | DSR | passes |
|---|---|---|---|---|---|---|---|---|---|---|---|
| X0 (P_pool0) | 1,270 | +7.8 % | +4.7 % | 57 % | +4.941 | 457, -36.0 % | stop 457, take 381, time 421 | | | | |
| E1 (LSM) | 1,270 | +6.4 % | +2.7 % | 60 % | +4.053 | none | own 1,063, take 193, time 3 | -1.4 | -2.3 to -0.5 | 0.000 | no |
| E2 (GPD, lambda 0.10) | 1,270 | +7.8 % | +4.7 % | 57 % | +4.941 | 457, -36.0 % | stop 457, take 381, time 421 | +0.0 | +0.0 to +0.0 | 0.000 | no |

11 failed buys in each. Without the trades open across a gap in the record: E1 -1.4 (band -2.5 to -0.4), E2 +0.0. In
sample (the days with a fit): X0 +13.0 %, E1 +12.7 % (-0.4), E2 +13.0 %.

## 3. E1, the stopping rule

- Fits: from 2026-10-22 on every one of the 59 decision times (g = landing + 5 to 295 s) had a regression; the training
  set grew from 220 paths (2026-10-22) to 1,755 (2026-10-29). The first two days had none: X0's trades.
- What it does: it sells where the regression of "hold on" minus "sell now" on the state (the mark and its square and
  cube, dump-at-risk, the buyback running, the pool's sales of the last 10 s, and their products with the mark) is below
  0. On X0's stopped trades +12.1 points (they land better than -36 %), on the others -9.0 points: it cuts the trades that
  would have run to +30 %, because on the same state a later dump is likely enough to make the average continuation
  worse than selling.
- Reported, not judged (books): at the live sizing it reaches more entries (420 against 351) and makes +1.498 SOL against
  +0.753 (max drawdown 0.209 against 0.252 SOL), since its positions are short and the daily loss limit binds less; at
  0.1 SOL, 4 open, 1.0 SOL a day it makes +6.405 against +8.295 SOL on the same entries. As in X14 r2 (DAR), the live
  book's edge comes from which entries it reaches, not from its exits, which lose on the same entries.

## 4. E2, the tail model

- Models from 2026-10-21 on (2026-10-20 had none): u 0.096 to 0.116 (the 90 % quantile of the 10 s fall after L), xi
  +0.27 to +0.40, 1,376 to 52,475 exceedances; the training seconds' rate of a 30 % fall in 10 s after L 1.8 % to 2.7 %.
- In-sample grid (mean per entry): lambda 0.02 +0.5 %, 0.05 +12.6 %, 0.10 to 0.50 +13.0 % (no sale). Seconds above the
  level: 0.02: 110,597 in sample, 116,788 out of sample (1,258 positions); 0.05: 461 and 0; 0.10 and up: none. The
  pick is the first of the equal best, 0.10: no sale.
- Out-of-sample P(F > 30 %) at the 50/90/99/99.9/100 % quantiles: 1.75 %, 2.58 %, 3.39 %, 3.98 %, 4.59 %.
- **Calibration** (376,441 seconds out of sample, rate 1.75 %): Brier 0.01712 against 0.01716 for the constant hazard,
  skill +0.002, AUC 0.604. By fifths of the prediction (predicted, observed): 1.24 % 0.89 %; 1.57 % 1.22 %; 1.75 %
  1.97 %; 2.06 % 2.11 %; 2.69 % 2.53 %. Calibrated in level, almost no spread.
- **Expected shortfall**: (a) VaR 95 % defined on 363,750 of the seconds; F above it on 5.0 % of them, there a mean F
  of 32.4 % against a mean ES of 34.9 % (slightly conservative). (b) X0's 449 out-of-sample stops with a model second
  before the signal: P(F > 30 %) 2.2 % on average, ES 37.9 %; what the stops lost from that second + L to the landing
  11.3 % on average, median 0.0 % (section 5).

## 5. Disclosed after the first run (no change of a trial)

- The pre-registration counts E1's basis as 13 columns; the terms it lists (1, r, r^2, r^3, dar, dar r, bb, bb r, the
  three sell dummies and r times each) are 14, and those 14 were used.
- The first evaluation held E1's positions without the stop also on the two in-sample days without a fit (2026-10-20
  and 21), against the registered "a day without any fit is X0's trade"; fixed, which moved E1's in-sample difference
  from +0.4 to -0.4 points and changed nothing out of sample.
- Added after the first run, descriptive only: the paired difference on X0's stops and on the rest, the seconds above
  each lambda and the quantiles of E2's probability.
- E2's stop comparison (b) as registered measures from the last whole second g before the stop's signal plus L; g + L
  is often already past the trade that crossed -20 % (72 % of the stops are one transaction, X14 r2), so the median
  loss counted from there is 0. The mean 11.3 % is the part of the fall after g + L. The ES at that second (37.9 %) is a
  tail mean, not a forecast of this loss.

## 6. What runs on paper

Nothing new: neither exit passes, so nothing joins `pipeline.STRATEGIES`. The live bot, its exits and its files are
unchanged. The trial lines are in a copy of the registry; the server's registry gets them by
`python -m lab.pumpfun_rt.os1 --register-only`.

## 7. Too early, in any case

Nine days of record, six out of sample, 1,270 paired entries, a latency from 34 live sales. What the two models say on
this record: the -20 % stop is not the problem by itself (E1 saves 12 points on the stopped trades); the problem is that
from what the record shows while a position is held, a dump is not predictable enough to sell before it without also
selling the trades that would reach +30 %. The heavy tail (xi about 0.35) is real and steady, its timing is not.

Sources: Longstaff and Schwartz (2001), "Valuing American options by simulation: a simple least-squares approach",
Review of Financial Studies 14(1); McNeil and Frey (2000), "Estimation of tail-related risk measures for heteroscedastic
financial time series: an extreme value approach", Journal of Empirical Finance 7(3-4).
