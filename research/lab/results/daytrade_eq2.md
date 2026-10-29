# EQ2: single-stock day trading at 50 EUR, new signals under the real rules

Pre-registered in `results/daytrade_eq2_prereg.md` (committed before the first run). Code:
`lab.experiments.daytrade_eq2`, tests `tests/test_daytrade_eq2.py`. Paper only: nothing a live bot, a wallet or the
engine reads changed.

## Reading (2026-10-29)

**Nothing passes. No paper book, no lockbox look.** A 50 EUR Alpaca account that day trades one large cap at a time
earned nothing a rule could be told apart from luck with, and every rule lost to simply holding SPY.

- **Holding SPY** made 21.5 % a year in USD over the validation window (2024-01 to 2026-06; 77.40 EUR at the end
  from 50 EUR, after both conversions). The best day book made 4.1 % (52.65 EUR). Doing nothing ends at 47.60 EUR:
  the dollar fell against the euro, and that hits every book in a USD account.
- **F1, opening range on relative volume (new: the stock in play, one at a time):** in sample every cell loses
  (-6.8 % to -18.2 % a year, drawdowns 56 to 84 %). In validation the four cells range from -8.2 % to +3.4 % a year,
  and three of them lose 23 to 29 % in total with costs doubled. Win rate 40 to 49 %. The cell that would pay (m 15,
  r 3) earns 0.09 % a trade after costs on 117 trades, loses 3.4 % in total with costs doubled, and lost 6.8 % a
  year in sample.
- **F2, learned classifier (walk-forward purged, the leak harness clean on all four):** the logistic model rarely
  clears 0.55 (8 and 4 trades in validation, under the 100-trade gate). LightGBM at 10:00 makes 3.4 % a year on 67
  trades (in sample 0.9 %, Sharpe 0.15). At 12:00 it loses in both windows. DSR 0.000 over 3,155 trials.
- **The account rules:** the cash account never ran short of settled cash (one round trip a session, settled T+1 by
  the next open), so the T+1 rule costs this book nothing. Under the pattern day trader rule the margin account skipped
  up to 181 in-sample signals (59 in validation). In the margin account the ORB cells fare no better.
- **Not tested:** the news tags (crypto RSS from 2026-10-26 only, nothing on a single large cap). Wire fees (a
  15 EUR bank wire would cost 30 % of the account) and taxes are left out and would only make it worse.

For this owner at 50 EUR the answer stays the long-term index fund of EQ1. Day trading single shares adds cost,
the conversion and the dollar's swing, and no edge was found.

<!-- generated below by lab.experiments.daytrade_eq2; edit above this line only -->

Generated 2026-10-29T10:56:13+00:00. 2635 full sessions to 2026-06-30. In sample 2016-01-04 to 2023-12-29 (2010 sessions; the classifier from 2018-01-01), validation 2024-01-02 to 2026-06-30 (625), every bar after 2026-06-30 dropped at load (the lockbox not read). W4's 41 large caps (today's list, survivors). One stock a session with all buying power, filled one bar late (decided at the close of bar k, bought at the open of bar k + 2), flat at the 15:55 open; per side the larger of 5 bps and a cent, doubled in the first 3 bars; EUR to USD 0.5 % each way; wire fees and taxes left out. News tags: not testable (crypto headlines from 2026-10-26 only), no trial.

## 1. Validation, one bar late (CAGR / max DD / Sharpe, USD; end value in EUR after both conversions)

| rule | account | validation | end EUR | trades (PDT skips) | win | per trade | next bar | costs doubled | excess Sharpe over SPY | DSR all / small | passes |
|---|---|---|---|---|---|---|---|---|---|---|---|
| rvol_orb_m5_r1.5 | cash | 2.9 % / 29.8 % / 0.25 | 51.16 | 332 (0) | 45 % | 0.03 % | -1.3 % / 32.3 % / 0.03 | -22.9 % total | -0.74 | 0.000 / 0.002 | no |
| rvol_orb_m5_r1.5 | margin | 1.3 % / 32.6 % / 0.16 | 49.15 | 273 (59) | 46 % | 0.02 % | -2.3 % / 33.9 % / -0.04 | -21.4 % total | -0.86 | 0.000 / 0.001 | not judged |
| rvol_orb_m5_r3 | cash | -8.2 % / 33.0 % / -0.69 | 38.41 | 121 (0) | 40 % | -0.16 % | -9.0 % / 35.0 % / -0.67 | -28.5 % total | -1.55 | 0.000 / 0.000 | no |
| rvol_orb_m5_r3 | margin | -7.6 % / 32.7 % / -0.65 | 39.10 | 116 (5) | 41 % | -0.16 % | -8.0 % / 34.6 % / -0.61 | -26.9 % total | -1.51 | 0.000 / 0.000 | not judged |
| rvol_orb_m15_r1.5 | cash | 1.5 % / 32.8 % / 0.18 | 49.46 | 319 (0) | 48 % | 0.03 % | -3.3 % / 33.0 % / -0.07 | -24.5 % total | -0.78 | 0.000 / 0.002 | no |
| rvol_orb_m15_r1.5 | margin | 2.1 % / 28.3 % / 0.21 | 50.10 | 264 (55) | 49 % | 0.03 % | -1.4 % / 27.8 % / 0.01 | -19.2 % total | -0.82 | 0.000 / 0.002 | not judged |
| rvol_orb_m15_r3 | cash | 3.4 % / 21.4 % / 0.33 | 51.68 | 117 (0) | 49 % | 0.09 % | -0.6 % / 23.5 % / 0.01 | -3.4 % total | -0.86 | 0.000 / 0.003 | no |
| rvol_orb_m15_r3 | margin | 3.5 % / 21.4 % / 0.34 | 51.83 | 116 (1) | 49 % | 0.09 % | -0.2 % / 23.5 % / 0.05 | -3.0 % total | -0.86 | 0.000 / 0.003 | not judged |
| pattern_clf_logit_1000 | cash | 4.1 % / 4.3 % / 0.74 | 52.65 | 8 (0) | 62 % | 1.31 % | 4.9 % / 4.5 % / 0.77 | 9.7 % total | -1.00 | 0.000 / 0.008 | no |
| pattern_clf_logit_1000 | margin | 4.1 % / 4.3 % / 0.74 | 52.65 | 8 (0) | 62 % | 1.31 % | 4.9 % / 4.5 % / 0.77 | 9.7 % total | -1.00 | 0.000 / 0.008 | not judged |
| pattern_clf_logit_1200 | cash | -0.3 % / 2.0 % / -0.13 | 47.29 | 4 (0) | 25 % | -0.15 % | 0.1 % / 1.5 % / 0.06 | -1.0 % total | -1.35 | 0.000 / 0.000 | no |
| pattern_clf_logit_1200 | margin | -0.3 % / 2.0 % / -0.13 | 47.29 | 4 (0) | 25 % | -0.15 % | 0.1 % / 1.5 % / 0.06 | -1.0 % total | -1.35 | 0.000 / 0.000 | not judged |
| pattern_clf_gbm_1000 | cash | 3.4 % / 7.3 % / 0.46 | 51.71 | 67 (0) | 52 % | 0.14 % | 5.3 % / 6.8 % / 0.62 | 1.6 % total | -1.01 | 0.000 / 0.005 | no |
| pattern_clf_gbm_1000 | margin | 3.0 % / 7.4 % / 0.41 | 51.22 | 66 (1) | 52 % | 0.12 % | 4.9 % / 7.1 % / 0.58 | 0.7 % total | -1.04 | 0.000 / 0.004 | not judged |
| pattern_clf_gbm_1200 | cash | -4.3 % / 10.4 % / -1.31 | 42.65 | 36 (0) | 36 % | -0.30 % | -4.3 % / 10.3 % / -1.35 | -13.6 % total | -1.59 | 0.000 / 0.000 | no |
| pattern_clf_gbm_1200 | margin | -4.3 % / 10.4 % / -1.31 | 42.65 | 36 (0) | 36 % | -0.30 % | -4.3 % / 10.3 % / -1.35 | -13.6 % total | -1.59 | 0.000 / 0.000 | not judged |
| doing nothing | | 0.0 % / 0.0 % / 0.00 | 47.60 | | | | | | | | |
| SPY held | | 21.5 % / 18.7 % / 1.34 | 77.40 | | | | | | | | |

DSR of the daily return (higher is better, pass at 0.95) on calendar days over R5's pool of all (3,155 trials, noise bar 2.84 a year) and the small family (369, 2.04). PBO of the eight cash-account rules from 2018-01-01: 0.20 over 12,870 splits.

## 2. In sample, one bar late (same columns)

| rule | account | in sample | registered Sharpe | trades (PDT skips) | win | per trade | next bar |
|---|---|---|---|---|---|---|---|
| rvol_orb_m5_r1.5 | cash | -10.0 % / 63.7 % / -0.38 | -0.38 | 1037 (0) | 44 % | -0.06 % | -12.5 % / 72.5 % / -0.47 |
| rvol_orb_m5_r1.5 | margin | -9.8 % / 60.8 % / -0.42 | -0.42 | 856 (181) | 44 % | -0.08 % | -12.7 % / 71.5 % / -0.55 |
| rvol_orb_m5_r3 | cash | -8.4 % / 59.1 % / -0.51 | -0.51 | 369 (0) | 44 % | -0.17 % | -9.6 % / 65.7 % / -0.55 |
| rvol_orb_m5_r3 | margin | -8.0 % / 58.1 % / -0.48 | -0.48 | 356 (13) | 44 % | -0.16 % | -8.9 % / 64.4 % / -0.52 |
| rvol_orb_m15_r1.5 | cash | -18.2 % / 84.0 % / -0.90 | -0.90 | 1035 (0) | 43 % | -0.14 % | -19.6 % / 85.5 % / -0.96 |
| rvol_orb_m15_r1.5 | margin | -16.9 % / 81.9 % / -0.94 | -0.94 | 855 (180) | 44 % | -0.16 % | -18.0 % / 83.2 % / -0.99 |
| rvol_orb_m15_r3 | cash | -6.8 % / 55.9 % / -0.43 | -0.43 | 372 (0) | 44 % | -0.13 % | -7.5 % / 58.0 % / -0.47 |
| rvol_orb_m15_r3 | margin | -6.7 % / 55.6 % / -0.42 | -0.42 | 362 (10) | 45 % | -0.13 % | -7.2 % / 57.7 % / -0.45 |
| pattern_clf_logit_1000 | cash | -0.2 % / 12.6 % / -0.05 | -0.06 | 32 (0) | 47 % | -0.04 % | -0.8 % / 14.6 % / -0.23 |
| pattern_clf_logit_1000 | margin | -0.1 % / 11.7 % / -0.01 | -0.01 | 31 (1) | 48 % | -0.01 % | -0.5 % / 12.7 % / -0.15 |
| pattern_clf_logit_1200 | cash | 0.7 % / 11.5 % / 0.21 | 0.25 | 31 (0) | 48 % | 0.20 % | 0.9 % / 10.5 % / 0.27 |
| pattern_clf_logit_1200 | margin | 1.0 % / 9.5 % / 0.29 | 0.34 | 30 (1) | 50 % | 0.28 % | 1.3 % / 8.6 % / 0.38 |
| pattern_clf_gbm_1000 | cash | 0.9 % / 19.7 % / 0.15 | 0.17 | 258 (0) | 51 % | 0.04 % | 1.5 % / 16.8 % / 0.21 |
| pattern_clf_gbm_1000 | margin | 1.0 % / 20.1 % / 0.15 | 0.17 | 250 (8) | 52 % | 0.04 % | 1.5 % / 17.1 % / 0.21 |
| pattern_clf_gbm_1200 | cash | -2.6 % / 21.6 % / -0.39 | -0.45 | 188 (0) | 45 % | -0.11 % | -3.1 % / 25.2 % / -0.46 |
| pattern_clf_gbm_1200 | margin | -1.9 % / 18.6 % / -0.27 | -0.31 | 184 (4) | 46 % | -0.07 % | -2.4 % / 21.5 % / -0.35 |
| SPY held | | 13.2 % / 33.8 % / 0.76 | | | | | |

## 3. The leak harness on the classifier (session and bar on one time axis)

- `logit:5`: clean, 8 runs, cuts 2018-01-03, 2019-06-27
- `logit:29`: clean, 8 runs, cuts 2018-01-03, 2019-06-27
- `gbm:5`: clean, 8 runs, cuts 2018-01-03, 2019-06-27
- `gbm:29`: clean, 8 runs, cuts 2018-01-03, 2019-06-27

## 4. The verdict

Passed: none. Failed conditions over the eight cash-account rules: DSR all >= 0.95 8, DSR small >= 0.95 8, CAGR > SPY held 8, costs doubled > 0 6, beats nothing (end EUR) 3, >= 100 trades 4.

Trials (R5's registry, family small, before the validation numbers): 16, `small:eq2:<rule>:<cash|margin>`.
