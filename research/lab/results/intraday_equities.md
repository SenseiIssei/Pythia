# W4 · Intraday strategies on US ETFs and large caps (pre-registration)

Written 2026-10-15, before any number of this study was seen. Everything
below is fixed; whatever is tried beyond it is added to the trial count.

## Why

Crypto on Alpaca costs 0.25 % a side, which kills holds under about two days
(`fast_strategies`). US shares and ETFs on Alpaca have zero commission; the
cost is the spread and slippage. If faster trades can work anywhere on the
account, it is here.

## Data

- **Server (the real study):** Alpaca historical bars, 5Min (1Min supported),
  SIP feed (IEX as fallback), split and dividend adjusted, regular session
  09:30 to 16:00 New York only. Keys from `APCA_API_KEY_ID` and
  `APCA_API_SECRET_KEY`. Cached to parquet per symbol and month. From
  2016-01-01. In sample 2016 to 2020, out of sample from 2021-01-01.
- **Free proxy (what can be run without keys):** Oanda minute bars for the
  S&P 500, Nasdaq 100 and Russell 2000 CFDs (public archive
  `FutureSharks/financial-data`, 2005-01 to 2020-05), resampled to 5 minutes
  inside the regular session, as stand-ins for SPY, QQQ and IWM. Volume is
  Oanda's tick count (a proxy for activity, used only for VWAP). A CFD keeps
  quoting on exchange holidays and after a half day's 13:00 close: a day counts
  only with at least 300 regular-session minutes and tick volume at least 30 %
  of its trailing 20-day median. In sample 2005 to 2013, out of sample
  2014-01 to 2020-05. No single stocks in the proxy.

## Universe

SPY, QQQ, IWM, plus each month the 20 most liquid of 40 large-cap candidates
by trailing 20-day dollar volume (point in time, from the bars themselves):
AAPL MSFT NVDA AMZN GOOGL META TSLA AVGO AMD NFLX JPM BAC XOM UNH LLY V MA
COST WMT ORCL CRM ADBE INTC CSCO QCOM PEP KO PG JNJ HD MRK ABBV CVX WFC C
DIS PYPL BA PLTR MU. The candidate list is chosen today, so the stock leg
leans on survivors; the ETF leg does not. Each symbol gets 1/N of the book
(N = symbols in the universe that day); a symbol not trading holds cash.

## Mechanics (every strategy)

- 5-minute bars, bar k covers 09:30 + 5k to 09:35 + 5k. A decision uses data
  up to the close of bar k and fills at the **open of bar k+1**.
- **Flat at the close:** every position is closed at the open of the 15:55
  bar. No new entries after the 15:30 decision.
- Rules check on bar closes, so stops are close-based and exit one bar later:
  exactly what the engine can do with a signal every five minutes. No resting
  stop orders, no fills inside a bar.
- **Costs per side** (spread plus slippage, zero commission): SPY and QQQ
  2 bps, IWM 3 bps, large caps 5 bps. Stress: doubled. Charged on every
  change of position.
- Long and short (the paper account can short) and long-only variants. The
  engine's lab books are long-only today, so only a long-only pick can become
  a book.

## Pre-registered grid (34 trials)

| Family | Rule | Grid | Trials |
|---|---|---|---|
| ORB | Opening range of the first 5, 15 or 30 minutes. First close above its high: long; below its low: short (long/short variants). One entry a day. Optional stop: a close back through the other side of the range. Else held to the close. | range 5/15/30 x side long, long/short x stop none, other side | 12 |
| Gap | Gap z = (open / previous regular close - 1) / std of the last 20 daily close-to-close returns. Fade: against a gap with abs(z) > g, exit when a close reaches the previous close (gap filled) or at the close. Go: with the gap, exit when a close falls back through the previous close (gap failed) or at the close. Decided at the first bar's close. | g 0.5/1.0/1.5 x fade, go x side long, long/short | 12 |
| VWAP reversion | z = ln(close / session VWAP) / (std of 5-minute returns over the last 20 days x sqrt(12)). Long when z < -k, short when z > k, exit when the close crosses VWAP or at the close. Entries from the 10:00 decision to 15:30. Re-entry allowed after an exit. | k 1.0/1.5/2.0 x side long, long/short | 6 |
| Intraday momentum (end of day) | Sign of the return from the previous close to 10:00 (or that plus the 15:00 to 15:30 return) sets the position from 15:30 to 15:55. | signal first half hour, first + 12th x side long, long/short | 4 |

Robustness, counted: for each family's pick, (a) one bar later fills,
(b) no-trade filter on scheduled macro days, (c) no-trade filter on abnormal
opens. **12 more trials, 46 in all.**

### No-trade filters (point in time)

- **Macro days:** the first Friday of each month (the US jobs report, by
  rule; a few releases fall on another day). FOMC and CPI dates need a
  calendar the lab does not have point in time; an `--event-days` CSV can add
  them on the server.
- **Abnormal open (news proxy):** no entries for a symbol on a day when
  abs(gap z) > 3 or its first 5-minute range is above 3x its median of the
  last 20 days. Both known at 09:35. Earnings and other single-name news show
  up this way.

## Judgement

Pick: the best in-sample Sharpe at base cost, per family and overall.
Sharpe annualised from daily book returns (252). Deflated Sharpe
(Bailey and Lopez de Prado) over the 46 trials of this study, and reported
pooled with the lab's 377 earlier trials. Stationary block bootstrap
(10 days, 5 000 draws). Benchmarks: the session drift (long the open to
15:55 every day, same symbols, same costs) and buy and hold.

The bar, all must hold for the overall pick out of sample:

1. deflated p > 0.95 over this study's 46 trials
2. out-of-sample Sharpe at least half the in-sample one
3. Sharpe > 0 with costs doubled
4. bootstrap 90 % lower bound of the Sharpe > 0
5. positive in at least 60 % of the out-of-sample calendar years
6. Sharpe > 0 with fills one bar later

A paper book (autopilot only, long-only) is added only for a pick that
passes on Alpaca data. A pass on the proxy alone marks it pending the server
run.

## Results

Pending.
