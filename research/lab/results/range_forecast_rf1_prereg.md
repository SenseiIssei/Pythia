# RF1: does a forecast of tomorrow's range help the daily books as a filter? Pre-registration

Registered 2026-10-29 and committed before any number below was computed. While scoping I looked only at the
columns and date ranges of the data files: `<data>/etf/daily` has closes only, W4's 5-minute cache has OHLC, and the
panel caches have close, high and low. I computed no range, loss, return or Sharpe. The owner asked for this on
2026-10-29: a friend's TradingView indicator (from a TikTok video) forecasts tomorrow's true range with GARCH(1,1) and
calls a day "good" when the forecast is above the 20-day average true range. It claims 72 % accuracy on 32 days.

This study builds on the review of 2026-10-27 (`results/review_2026-10-27.md`, sections 2 and 3), R5's registry
(`metrics.trial_pool`, `<data>/trials/registry.jsonl`) and R6's windows (`results/factory_lockbox_r6.md`). It does
not repeat M1 (`vol`), M6 (`vol_daily`: the 30-day mean beats faster forecasts for sizing), C11 (`vol_managed`),
`breakout_study`, W4 (`intraday_equities`), X16 (`equities_training`) or X11 (`model_upgrades`). None of those asked
whether a range forecast works as a filter on entries.

Code: `lab.experiments.range_forecast_rf1`, written after this file. Results: `results/range_forecast_rf1.md`. Nothing
in this file may change once a result exists. Paper only: nothing a live bot, a wallet or the engine reads changes.

## Data (the lockbox untouched: every row from 2026-07-01 on is dropped at load)

- **Coins.** The 15 Alpaca coins (`alpaca_universe.ALPACA`), each in its current segment of the sweep's daily panel
  with the daily bars before 2020 in front (`lab.history.long_frame`). The daily bars close at 00:00 UTC and come
  from hourly bars. A crypto day's open is the previous close (the market trades around the clock), so its true
  range equals its high-low range: TR = max(H, C[t-1]) - min(L, C[t-1]). Both targets are reported, but for coins
  they differ only on a day that follows a missing bar.
- **ETFs.** SPY, QQQ and IWM come from W4's cached 5-minute SIP bars (split and dividend adjusted, from 2016-01). The
  regular session gives each day's OHLC: the 09:30 bar's open, the session high and low, and the 15:55 bar's close.
  The calendar is W4's (full sessions only; half days are dropped).
- **Sector ETFs are dropped.** `<data>/etf/daily` holds only closes for XLK, XLF, XLV and XLE. Without a high and a
  low there is no range, and no other source is fetched for this study.
- **Targets**, as a fraction of the close of day t: y_TR = TR[t+1] / C[t] (the friend's target and the judged one)
  and y_HL = (H[t+1] - L[t+1]) / C[t] (reported).

## Forecasts of y at the close of day t (known at that close)

Challengers (6), each fitted per asset:

| Key | Model |
|---|---|
| GARCH | GARCH(1,1) by Gaussian QMLE on demeaned close-to-close log returns. Its one-day-ahead sigma is the raw forecast. |
| CARR | CARR(1,1) (Chou 2005): lambda[t+1] = w + a R[t] + b lambda[t] on the target's own range R, fitted by exponential QMLE. |
| HAR-PK, HAR-GK, HAR-RS, HAR-YZ | HAR by OLS: the next day's daily volatility estimate sqrt(v[t+1]) on its means over 1, 5 and 22 days (ETFs) or 1, 7 and 30 days (coins, as M6). v is Parkinson ln(H/L)^2 / (4 ln 2), Garman-Klass 0.5 ln(H/L)^2 - (2 ln 2 - 1) ln(C/O)^2, Rogers-Satchell ln(H/C) ln(H/O) + ln(L/C) ln(L/O), or the daily Yang-Zhang term ln(O/C[t-1])^2 + k ln(C/O)^2 + (1 - k) RS with k = 0.34 / (1.34 + 23 / 21). A forecast is floored at 1e-6. |

Baselines (3): yesterday's range (R[t]), the 20-day average (the mean of R over t-19..t, the friend's yardstick),
and EWMA 0.94 on the range (e[t] = 0.94 e[t-1] + 0.06 R[t], started at the first 20-day mean). R is the target's own
range.

**One scale per model.** Each raw forecast g (GARCH's sigma, HAR's volatility, CARR's range, a baseline's range) is
multiplied by one factor per asset, model and target, fitted on the fold's training rows: c = mean(y / g). This is
the factor that minimises QLIKE in training. The baselines get it too, so no forecast wins because of its units, and
every forecast becomes a forecast of E[y].

**Walk-forward by quarter.** Every parameter and scale is refitted at each quarter start on all rows of the asset
before it and then held fixed through the quarter. A fold for an asset starts at the first quarter from 2018Q1 with
at least 365 days of the asset's ranges before it. That is 2018 for SPY, QQQ, IWM, BTC and ETH, and later for the
rest; PEPE starts in 2024. The last quarter ends 2026-06-30.

## Part A: the forecast (no money)

Loss: QLIKE on the range, L = y / f - ln(y / f) - 1 (Patton's form, minimised at f = E[y]), per asset and day.

"Good day" (the friend's rule): f[t+1] > ATR20[t], with ATR20[t] the mean of TR over t-19..t. It is right when
TR[t+1] > ATR20[t] holds or fails with it. The persistence rule: tomorrow is good if TR[t] > ATR20[t]. Reported for
each model are the accuracy, the share of good days, the friend's GARCH rule as he uses it, and the 95 % binomial
band of 72 % on 32 days.

Two groups are judged on their own: coins (15) and ETFs (3). The windows are R6's: 2018-2023 as in sample, where
the forecasts are still out of sample by the walk-forward and are reported per year, and validation from 2024-01-01
to 2026-06-30, which is judged.

**Pass (per model, group and target TR; all must hold on validation):**

1. Its mean QLIKE is below each of the three baselines'. The Diebold-Mariano test on the per-day cross-asset mean
   loss difference (Newey-West, 10 lags) must have a one-sided p below 0.05 / 6 against each baseline.
2. Its good-day accuracy is above the persistence rule's, with the same DM test on the 0/1 loss also below
   0.05 / 6.
3. The leak check is clean: T1's harness (`lab.leak.check`) on the forecast function over BTC and ETH's arrays
   finds nothing.

The HL target is reported the same way but not judged. **The forecast that goes to Part B**, per group, is the one
with the lowest 2018-2023 QLIKE on TR among the models that pass. If none passes in a group, that group's Part B
does not run and makes no number.

## Part B: the filter (only for a forecast that passes A)

The books, as they run:

- **breakout_top10** on Alpaca: `alpaca_universe.originals`, with every non-Alpaca coin's weight left as cash
  (`cash_left`), simulated by `alpaca_universe.sim_daily` (filled at the signal close). Judged at 35 bps a side,
  with 15 bps shown.
- **W4's ETF rules as they are:** the four long-only family picks of W4's Alpaca run (ORB 15m long, Gap go 1.5 long,
  VWAP k 2.0 long, EOD momentum first long), on SPY, QQQ and IWM only. They use W4's code (`targets`, `simulate`,
  `book`) and W4's costs (2 / 2 / 3 bps a side, SEC fee and TAF).

The filters act on entries only; exits and held positions are untouched. f is the group's Part B forecast of
y_TR made at the close before the entry (for a daily breakout, the close of the signal day; for an intraday rule,
the previous session's close). An asset without a forecast takes no entry under any filter.

1. **Good days:** enter only when f > ATR20 at that close.
2. **Range covers costs:** skip an entry when f x sqrt(h) is below three times the round trip (6 x the cost a
   side: 210 bps for the coins, 12 / 12 / 18 bps for SPY / QQQ / IWM). h is the rule's median hold, measured on the
   unfiltered book's in-sample entries: in days for breakout_top10, and as a share of the 78-bar session for the
   ETF rules.
3. **After a compression** (breakouts only: breakout_top10 and ORB 15m long): enter only if, at one of the five
   closes before the entry's, f was in the lowest fifth of the asset's own previous 250 forecasts (at least 120).

breakout_top10's filtered book re-runs `fam_breakout.breakout_weights`'s loop with the filter as an extra condition
on an entry, so a blocked breakout can still enter on a later close where it holds. With every filter open the loop
equals the book as it runs (tested).

**Pass (each filtered book against its own unfiltered book, validation 2024-01-01 to 2026-06-30; all must hold):**

1. The certainty-equivalent return is up: CE = annual mean - (3 / 2) x annual variance of daily simple returns
   (365 days for the coins, 252 for the ETFs).
2. The maximum drawdown is not worse (filtered <= unfiltered).
3. A stationary block bootstrap (mean block 20 days, 2,000 draws, seed 7) of CE(filtered) - CE(unfiltered) on the
   same resampled days has its 5 % quantile above 0.
4. Deflated by the registry: the DSR of the daily difference (filtered - unfiltered) is at least 0.95 over R5's pool
   of all, with this study's trials (the benchmark-relative deflation of R6).

A pass becomes a paper book (`rf1_<book>_<filter>`) in its own later commit. Otherwise nothing reaches a book, the
engine or a wallet.

## Trials (R5's registry, family hand, source this file)

Each trial is registered before any validation number exists:

- Part A, 12 trials: `hand:rf1:fc:<model>:<tr|hl>`, counted without a Sharpe.
- Part B, only for a group that runs, 17 trials at most: `hand:rf1:<book>:<base|good|cost|squeeze>`, each with its
  in-sample annual Sharpe. For the coins that is breakout_top10's base and three filters (4). For the ETFs it is
  four bases, four with filter 1, four with filter 2 and ORB with filter 3 (13).

The unfiltered books count as trials because their ETF-leg numbers are new.

## Reported

`results/range_forecast_rf1.md` will hold:

- per group, target and model: QLIKE (2018-2023 and validation), the gain against each baseline, the DM statistic
  and p, the good-day accuracy against persistence, and QLIKE by year;
- the friend's rule as he uses it, next to the binomial band of his 72 % on 32 days;
- the leak check;
- the verdict per model, then Part B (or why it did not run) with every filtered book's CE, Sharpe, CAGR, drawdown,
  trades and the share of entries blocked, the bootstrap band and the DSR;
- a README row.
