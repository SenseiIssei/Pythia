# EQ1: long-term ETF books at 50 EUR, as a German retail investor can trade them

Pre-registered in `results/etf_books_eq1_prereg.md` (committed before the first run). Code:
`lab.experiments.etf_books_eq1`, the paper books `lab.paper.etf_books` (job `paper-etf-books` after `etf-daily`), the
closes `lab.collect.etf_daily` (the eight UCITS funds from Yahoo's `.DE` listings). Tests `tests/test_etf_books_eq1.py`,
`tests/test_etf_books_paper.py`. Paper only: nothing a live bot, a wallet or the engine reads changed.

**Verdict: no book beats holding the S&P 500 fund. Nothing goes to the lockbox; the best long-term book for real money
is the benchmark itself, SXR8 (or EUNL) through a free savings plan.**

- **The benchmark** (SXR8 held, validation 2024-01 to 2026-06, late, Trade Republic or Scalable through the plan):
  19.4 % a year, drawdown 23.3 %, at most 8 months under water; 50 EUR once end at 77.77 EUR, plus 50 EUR a month at
  1,864 EUR from 1,500 paid in (17.8 % money-weighted). EUNL held: 18.5 % a year, drawdown 21.7 %, 0.9 points behind.
- **Dual momentum does not port.** On the UCITS funds it makes 5.0 % a year in sample without any cost (the ideal
  daily-rebalanced book 5.6 %; a check of the same rule, no trial) against SXR8's 15.0 %; with 1 EUR an order at 50 EUR it loses (-16.6 % a year once,
  26 orders), plus 50 EUR a month 11.7 % with a 16.9 % drawdown, 7.6 points behind.
- **Trend and vol target** lower the drawdown (13.2 % and 21.9 % plus 50 EUR a month at Trade Republic) and give up
  6.6 and 2.7 points a year.
- **The broker decides more than the rule at 50 EUR.** At Scalable (whole units for one-off orders) and Interactive
  Brokers (whole units, no savings plan, 1.25 EUR at least) one SXR8 unit costs about 700 EUR and XEON 150 EUR: the
  trend and vol books never buy at 50 EUR once, IB's benchmark holds cash until a unit is affordable (3.8 % a year
  plus 50 EUR a month). IB's numbers against its own benchmark (EUNL +8.3 points) compare with a book mostly in cash.
  IB is the only broker with an API for UCITS ETFs, but only from a few hundred EUR on.
- **The deflation.** DSR of every book's daily excess over the benchmark 0.000 over all (3,139 trials) and at most
  0.109 over the small family (353); PBO of the eight Trade Republic configurations 0.11.

Open: the brokers' fractional one-off orders and minimums are taken as stated (their pages did not answer in this run;
the owner checks them before step 5), taxes are left out, the two distributing funds' distributions are reinvested in
the study and not credited in the paper wallets, IWM in EUR stands in for small caps before 2018-04-26.

<!-- generated below by lab.experiments.etf_books_eq1; edit above this line only -->

Generated 2026-10-29T08:16:06+00:00. In sample 2011-06-01 to 2023-12-31, validation 2024-01-01 to 2026-06-30, every close after 2026-06-30 dropped before anything was computed (the lockbox not read). One close late: decided at close t, filled at close t+1. 50 EUR on day 0; `plus50` adds 50 EUR on the first Xetra day of each month. Small caps: IWM in EUR at the ECB's rate before IUSN's first close (2018-04-26). Bad prints dropped: none. Taxes left out, the final sale not deducted.

## 1. Validation, late (CAGR / max DD / longest months under water / Sharpe; time-weighted)

| book | variant | broker | validation | end EUR (paid in) | money-weighted | CAGR minus benchmark | months beat | orders sent / not sent | fees EUR | DSR all / small | passes |
|---|---|---|---|---|---|---|---|---|---|---|---|
| hold_sp500 | once | tr | 19.4 % / 23.3 % / 8 / 1.26 | 77.77 (50) | 19.4 % | benchmark |  | 0 / 0 | 0.00 |  |  |
| hold_sp500 | once | scalable | 19.4 % / 23.3 % / 8 / 1.26 | 77.77 (50) | 19.4 % | benchmark |  | 0 / 0 | 0.00 |  |  |
| hold_sp500 | once | ibkr | 0.0 % / 0.0 % / 0 / 0.00 | 50.00 (50) | 0.0 % | benchmark |  | 0 / 30 | 0.00 |  |  |
| hold_sp500 | plus50 | tr | 19.3 % / 23.3 % / 8 / 1.26 | 1863.89 (1500) | 17.8 % | benchmark |  | 0 / 0 | 0.00 |  |  |
| hold_sp500 | plus50 | scalable | 19.3 % / 23.3 % / 8 / 1.26 | 1863.89 (1500) | 17.8 % | benchmark |  | 0 / 0 | 0.00 |  |  |
| hold_sp500 | plus50 | ibkr | 3.8 % / 18.6 % / 14 / 0.44 | 1671.34 (1500) | 8.6 % | benchmark |  | 2 / 26 | 2.50 |  |  |
| hold_world | once | tr | 18.5 % / 21.7 % / 7 / 1.30 | 76.35 (50) | 18.5 % | -0.9 pts | 52 % | 0 / 0 | 0.00 | 0.000 / 0.000 | no |
| hold_world | once | scalable | 18.5 % / 21.7 % / 7 / 1.30 | 76.35 (50) | 18.5 % | -0.9 pts | 52 % | 0 / 0 | 0.00 | 0.000 / 0.000 | no |
| hold_world | once | ibkr | 0.0 % / 0.0 % / 0 / 0.00 | 50.00 (50) | 0.0 % | +0.0 pts | 0 % | 0 / 30 | 0.00 | 0.000 / 0.000 | no |
| hold_world | plus50 | tr | 18.4 % / 21.7 % / 7 / 1.29 | 1861.47 (1500) | 17.7 % | -0.9 pts | 52 % | 0 / 0 | 0.00 | 0.000 / 0.000 | no |
| hold_world | plus50 | scalable | 18.4 % / 21.7 % / 7 / 1.29 | 1861.47 (1500) | 17.7 % | -0.9 pts | 52 % | 0 / 0 | 0.00 | 0.000 / 0.000 | no |
| hold_world | plus50 | ibkr | 12.1 % / 21.0 % / 8 / 0.95 | 1805.14 (1500) | 15.1 % | +8.3 pts | 69 % | 14 / 7 | 17.50 | 0.005 / 0.109 | no |
| dual_mom | once | tr | -16.6 % / 39.3 % / 16 / -0.96 | 31.80 (50) | -16.6 % | -36.0 pts | 38 % | 26 / 210 | 26.00 | 0.000 / 0.000 | no |
| dual_mom | once | scalable | -3.2 % / 7.7 % / 27 / -1.23 | 46.14 (50) | -3.2 % | -22.6 pts | 41 % | 4 / 391 | 3.96 | 0.000 / 0.000 | no |
| dual_mom | once | ibkr | -4.1 % / 9.8 % / 27 / -1.24 | 45.10 (50) | -4.1 % | -4.1 pts | 0 % | 4 / 391 | 5.00 | 0.000 / 0.000 | no |
| dual_mom | plus50 | tr | 11.7 % / 16.9 % / 11 / 0.90 | 1852.15 (1500) | 17.2 % | -7.6 pts | 45 % | 68 / 0 | 68.00 | 0.000 / 0.000 | no |
| dual_mom | plus50 | scalable | 11.2 % / 16.2 % / 11 / 0.97 | 1803.28 (1500) | 15.0 % | -8.1 pts | 41 % | 49 / 84 | 48.51 | 0.000 / 0.000 | no |
| dual_mom | plus50 | ibkr | 7.7 % / 11.1 % / 8 / 0.86 | 1745.80 (1500) | 12.2 % | +3.9 pts | 52 % | 51 / 140 | 63.75 | 0.000 / 0.007 | no |
| trend_sp500 | once | tr | 7.0 % / 17.9 % / 16 / 0.61 | 59.16 (50) | 7.0 % | -12.4 pts | 28 % | 9 / 0 | 9.00 | 0.000 / 0.000 | no |
| trend_sp500 | once | scalable | 0.0 % / 0.0 % / 0 / 0.00 | 50.00 (50) | 0.0 % | -19.4 pts | 45 % | 0 / 30 | 0.00 | 0.000 / 0.000 | no |
| trend_sp500 | once | ibkr | 0.0 % / 0.0 % / 0 / 0.00 | 50.00 (50) | 0.0 % | +0.0 pts | 0 % | 0 / 30 | 0.00 | 0.000 / 0.000 | no |
| trend_sp500 | plus50 | tr | 12.7 % / 13.2 % / 16 / 1.08 | 1676.42 (1500) | 8.9 % | -6.6 pts | 7 % | 9 / 0 | 9.00 | 0.000 / 0.000 | no |
| trend_sp500 | plus50 | scalable | 8.6 % / 12.5 % / 16 / 0.91 | 1632.97 (1500) | 6.7 % | -10.7 pts | 45 % | 8 / 16 | 7.92 | 0.000 / 0.000 | no |
| trend_sp500 | plus50 | ibkr | -0.4 % / 11.1 % / 16 / -0.02 | 1530.57 (1500) | 1.6 % | -4.2 pts | 21 % | 11 / 20 | 13.75 | 0.000 / 0.000 | no |
| voltarget_sp500 | once | tr | 13.6 % / 23.3 % / 15 / 0.94 | 68.71 (50) | 13.6 % | -5.8 pts | 34 % | 5 / 4 | 5.00 | 0.000 / 0.000 | no |
| voltarget_sp500 | once | scalable | 0.0 % / 0.0 % / 0 / 0.00 | 50.00 (50) | 0.0 % | -19.4 pts | 45 % | 0 / 36 | 0.00 | 0.000 / 0.000 | no |
| voltarget_sp500 | once | ibkr | 0.0 % / 0.0 % / 0 / 0.00 | 50.00 (50) | 0.0 % | +0.0 pts | 0 % | 0 / 36 | 0.00 | 0.000 / 0.000 | no |
| voltarget_sp500 | plus50 | tr | 16.6 % / 21.9 % / 14 / 1.18 | 1820.77 (1500) | 15.8 % | -2.7 pts | 17 % | 7 / 2 | 7.00 | 0.000 / 0.000 | no |
| voltarget_sp500 | plus50 | scalable | 14.2 % / 21.9 % / 8 / 1.06 | 1812.77 (1500) | 15.4 % | -5.1 pts | 45 % | 1 / 21 | 0.99 | 0.000 / 0.000 | no |
| voltarget_sp500 | plus50 | ibkr | 3.7 % / 18.6 % / 14 / 0.42 | 1668.36 (1500) | 8.5 % | -0.1 pts | 21 % | 5 / 29 | 6.25 | 0.000 / 0.000 | no |

DSR of the daily excess over the benchmark book (same broker and variant), on calendar days, over R5's pool of all (3,139 trials, noise bar 2.83 a year) and the small family (353, 1.96); higher is better, pass at 0.95. PBO of the eight Trade Republic configurations: 0.11 over 12,870 splits.

## 2. In sample, late (same columns)

| book | variant | broker | in sample | end EUR (paid in) | CAGR minus benchmark | orders sent / not sent | fees EUR |
|---|---|---|---|---|---|---|---|
| hold_sp500 | once | tr | 15.0 % / 33.8 % / 11 / 0.93 | 290.27 (50) | benchmark | 0 / 0 | 0.00 |
| hold_sp500 | once | scalable | 15.0 % / 33.8 % / 11 / 0.93 | 290.27 (50) | benchmark | 0 / 0 | 0.00 |
| hold_sp500 | once | ibkr | 0.0 % / 0.0 % / 0 / 0.00 | 50.00 (50) | benchmark | 0 / 151 | 0.00 |
| hold_sp500 | plus50 | tr | 15.0 % / 33.8 % / 11 / 0.93 | 19419.03 (7550) | benchmark | 0 / 0 | 0.00 |
| hold_sp500 | plus50 | scalable | 15.0 % / 33.8 % / 11 / 0.93 | 19419.03 (7550) | benchmark | 0 / 0 | 0.00 |
| hold_sp500 | plus50 | ibkr | 13.9 % / 31.1 % / 12 / 0.93 | 18638.59 (7550) | benchmark | 25 / 5 | 31.25 |
| hold_world | once | tr | 11.5 % / 33.6 % / 20 / 0.76 | 196.13 (50) | -3.5 pts | 0 / 0 | 0.00 |
| hold_world | once | scalable | 11.5 % / 33.6 % / 20 / 0.76 | 196.13 (50) | -3.5 pts | 0 / 0 | 0.00 |
| hold_world | once | ibkr | 10.3 % / 31.8 % / 20 / 0.74 | 171.33 (50) | +10.3 pts | 1 / 37 | 1.25 |
| hold_world | plus50 | tr | 11.5 % / 33.6 % / 20 / 0.76 | 15922.89 (7550) | -3.5 pts | 0 / 0 | 0.00 |
| hold_world | plus50 | scalable | 11.5 % / 33.6 % / 20 / 0.76 | 15922.89 (7550) | -3.5 pts | 0 / 0 | 0.00 |
| hold_world | plus50 | ibkr | 9.9 % / 31.7 % / 20 / 0.70 | 15227.05 (7550) | -3.9 pts | 28 / 0 | 35.00 |
| dual_mom | once | tr | -4.6 % / 45.8 % / 151 / -0.72 | 27.48 (50) | -19.7 pts | 20 / 1795 | 20.00 |
| dual_mom | once | scalable | -3.3 % / 34.5 % / 151 / -0.94 | 32.76 (50) | -18.3 pts | 16 / 1813 | 15.84 |
| dual_mom | once | ibkr | -3.6 % / 36.6 % / 151 / -0.98 | 31.72 (50) | -3.6 pts | 12 / 1827 | 15.00 |
| dual_mom | plus50 | tr | -0.7 % / 44.7 % / 125 / 0.01 | 8726.64 (7550) | -15.7 pts | 391 / 5 | 391.00 |
| dual_mom | plus50 | scalable | 1.3 % / 26.4 % / 77 / 0.17 | 8622.05 (7550) | -13.7 pts | 376 / 56 | 372.24 |
| dual_mom | plus50 | ibkr | -0.2 % / 37.0 % / 76 / 0.04 | 8581.17 (7550) | -14.1 pts | 390 / 59 | 491.89 |
| trend_sp500 | once | tr | 5.2 % / 35.6 % / 77 / 0.44 | 94.84 (50) | -9.8 pts | 47 / 0 | 47.00 |
| trend_sp500 | once | scalable | 0.0 % / 0.0 % / 0 / 0.00 | 50.00 (50) | -15.0 pts | 0 / 151 | 0.00 |
| trend_sp500 | once | ibkr | 0.0 % / 0.0 % / 0 / 0.00 | 50.00 (50) | +0.0 pts | 0 / 151 | 0.00 |
| trend_sp500 | plus50 | tr | 10.3 % / 22.9 % / 42 / 0.80 | 13454.07 (7550) | -4.7 pts | 47 / 0 | 47.00 |
| trend_sp500 | plus50 | scalable | 10.1 % / 22.6 % / 42 / 0.81 | 13248.31 (7550) | -4.8 pts | 46 / 5 | 45.54 |
| trend_sp500 | plus50 | ibkr | 9.3 % / 22.0 % / 42 / 0.77 | 12831.81 (7550) | -4.5 pts | 65 / 5 | 163.60 |
| voltarget_sp500 | once | tr | 7.0 % / 31.7 % / 24 / 0.55 | 117.28 (50) | -8.0 pts | 45 / 66 | 45.00 |
| voltarget_sp500 | once | scalable | 0.0 % / 0.0 % / 0 / 0.00 | 50.00 (50) | -15.0 pts | 0 / 211 | 0.00 |
| voltarget_sp500 | once | ibkr | 0.0 % / 0.0 % / 0 / 0.00 | 50.00 (50) | +0.0 pts | 0 / 211 | 0.00 |
| voltarget_sp500 | plus50 | tr | 11.5 % / 29.9 % / 19 / 0.84 | 15725.09 (7550) | -3.5 pts | 62 / 0 | 62.00 |
| voltarget_sp500 | plus50 | scalable | 12.2 % / 30.1 % / 19 / 0.91 | 15935.57 (7550) | -2.8 pts | 60 / 10 | 59.40 |
| voltarget_sp500 | plus50 | ibkr | 11.2 % / 29.4 % / 19 / 0.86 | 15400.52 (7550) | -2.7 pts | 77 / 16 | 97.16 |

## 3. The verdict

Passed: none. Failed conditions over the 24 configurations: cagr > benchmark 22, DSR all >= 0.95 24, DSR small >= 0.95 24, DD <= benchmark + 5 pts 2. Lockbox: no look (no configuration passes validation).

Trials (R5's registry, family small, before the validation numbers): 30, `small:eq1:<book>:<variant>:<broker>`.

First close per fund (its own or the twin's): EUNL.DE 2009-09-25, SXR8.DE 2010-05-19, EXSA.DE 2008-01-02, EUNM.DE 2009-10-20, IUSN.DE 2009-01-02, EUNH.DE 2009-04-17, 4GLD.DE 2009-11-13, XEON.DE 2008-01-02.
