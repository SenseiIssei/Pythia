# overnight (X7 A) · The overnight drift on US ETFs and large caps

Pre-registered 2026-10-15, before any number of this study was computed.
Everything above the generated marker is fixed; anything tried beyond it is
added to the trial count.

## Question

Most of the US equity premium is said to come close to open: buy at the
closing auction, sell at the next opening auction, hold cash during the day.
Stock and ETF trades on the Alpaca paper account carry no commission, only the
spread and the SEC and FINRA fees on sells. Does a close-to-open book, plain
or filtered, beat buying and holding after those costs, and can Alpaca fill it
at the auctions at all?

## Data

- **Main source (keyless):** Yahoo's daily chart API (the fallback
  `etf_trend` already uses), open, high, low, close and adjusted close from
  1993, cached as `<data>/etf/ohlc/<SYM>.csv`. Yahoo's open and close are split
  adjusted, the adjusted close also for dividends. The day's factor
  f = adjclose / close adjusts that day's open too, so the overnight return
  n(t) = f(t) open(t) / (f(t-1) close(t-1)) - 1 carries the dividend on its
  ex-date (the price drops at the open, the holder of the night is paid), and
  the day return d(t) = close(t) / open(t) - 1. (1 + n)(1 + d) is the total
  return of the day.
- **Stale opens.** Old vendor data often sets the open to the previous close.
  A symbol's calendar year is used only when under 5 % of its days have an
  unadjusted open exactly equal to the previous unadjusted close; the share
  per symbol and year is reported.
- **Cross-check and fill source:** Alpaca SIP 5-minute bars (adjustment all,
  regular session), the W4 cache `<data>/intraday/alpaca-sip/<SYM>/` from
  2016, for SPY, QQQ, IWM and the large caps W4 cached. On the server
  `--source alpaca` fetches them again with `APCA_API_KEY_ID` and
  `APCA_API_SECRET_KEY` from the environment (never written anywhere). Used for
  the agreement of the two sources' overnight returns and for the fill checks
  below, not for the grid.
- **Windows.** In sample 2001-01-01 (decimal quotes; earlier spreads are not
  comparable) to 2017-12-31, out of sample 2018-01-01 to the last close.
  Filters need 252 days of history before a symbol counts.

## Universe

- SPY, QQQ, IWM
- the nine original Select Sector SPDRs: XLB XLE XLF XLI XLK XLP XLU XLV XLY
- 20 large caps: AAPL MSFT NVDA AMZN GOOGL META AVGO TSLA BRK-B JPM LLY V WMT
  ORCL MA XOM NFLX COST JNJ HD. This is today's list of the largest US
  companies, so it is a list of survivors; each one joins when its Yahoo
  history starts. The bias inflates the stocks' buy and hold as much as their
  nights, so the comparison with buy and hold is fairer than the level.

## Sleeves (U) and rules (R)

Each sleeve gives every available symbol 1/N; a symbol whose rule says no
for a night holds cash for it (its share is not spread over the others).

| | Sleeve |
|---|---|
| U1 | SPY |
| U2 | QQQ |
| U3 | IWM |
| U4 | SPY, QQQ, IWM equal weight |
| U5 | the nine sector ETFs equal weight |
| U6 | the 20 large caps equal weight |

| | Rule: hold the night from the close of t-1 to the open of t only when |
|---|---|
| R0 | always |
| R1 | trend: the symbol's adjusted close at t-1 is above its 200-day average |
| R2 | calm: its 20-day close-to-close vol at t-1 is below its median of the last 252 days |
| R3 | stormy: that vol is at or above the median |
| R4 | turn of month: t is the last trading day of its month or one of the first three of the next |
| R5 | holiday: at least one weekday without a session lies between t-1 and t (an exchange holiday) |

The rules read the close; the engine would decide a few minutes before it (a
closing-auction order must be in by 15:50 New York). The difference matters
only on the rare days a filter flips in the last ten minutes and is ignored.
The exchange calendar behind R4 and R5 is published a year ahead.

**36 trials** (6 sleeves x 6 rules).

## Costs

Every night held trades twice: a buy at the close of t-1 and a sell at the
open of t, also on consecutive nights (the point is cash during the day).

- Spread and slippage per side: SPY and QQQ 1 bp, IWM and the sector ETFs
  2 bps, large caps 3 bps. **Stress:** doubled.
- SEC fee 27.80 USD per million sold, FINRA TAF 0.000166 USD per share sold
  (on the unadjusted price, the per-trade cap ignored). Fees are not doubled.

## Can Alpaca fill it?

What Alpaca documents (docs.alpaca.markets, "Orders at Alpaca"; forum answers
by Alpaca staff 2021-05, 2021-10 and 2026-06):

- `time_in_force: cls` is a market-on-close (or limit-on-close) order, eligible
  only in the closing auction, to be submitted before 15:50 New York;
  `time_in_force: opg` is market-on-open, only in the opening auction, to be
  submitted after 19:00 the evening before and before 09:28. Whole shares
  only: fractional orders cannot use either. Not in extended hours, not for
  crypto. Live, MOC orders are said to need the "elite" smart router.
- **Paper does not simulate the auctions:** an `opg` or `cls` order fills like
  a market order at the current bid or ask when it is handled, not at the
  auction price, with random partial fills (a `cls` remainder can expire at
  the close). Paper does not simulate dividends either, so the paper book
  will miss the dividend the backtest's nights earn on ex-dates.
- Pythia's engine sends only `day` (equities) and `gtc`/`ioc` (crypto) orders
  today (`connectors/alpaca.rs`), and its equity lab books rebalance once in
  the regular session to a daily target; a book that is flat every day and
  long every night needs two rebalances a day at set times.

So the backtest is also run with fills the paper account can actually get,
from the 5-minute bars (2018 onward, the out-of-sample years W4 cached):

- **F1** buy at the close of the 15:45 bar (the 15:50 cut-off, a market order
  then), sell at the close of the 09:30 bar (09:35, after the opening quotes
  settle);
- **F2** buy at the close of the 15:55 bar (last trade before 16:00), sell at
  the open of the 09:30 bar (first trade).

Both at the base costs on top. Symbols W4 did not cache (the sector ETFs,
BRK-B) need the server run (`--source alpaca`); a PC run judges the fill
checks on the symbols it has and says which are missing. Each is counted for the pick (2 trials), and
the pick at stress costs is counted too (1 trial). **39 trials in all.**

## Judgement

- Pick: the best in-sample Sharpe at base costs among the 36 (annualised
  over 252 sessions, cash earns nothing, as on the paper account).
- References, not trials: each sleeve's buy and hold, SPY buy and hold, and
  each sleeve's day session (open to close) at the same costs, to show where
  the return comes from.
- Stationary block bootstrap, block 20 days, 4,000 draws.
- Deflation over the lab's pool: 908 earlier trials (the 841 of
  `fast_maker.md` with its published bar 2.73, plus W4's 46 and W3's 21 that
  pool did not include, at the same variance) and these 39.

The pick passes only if, out of sample from 2018:

1. Sharpe > 0 at base and at stress costs
2. Sharpe above SPY buy and hold's and above its own sleeve's buy and hold's
3. max drawdown below SPY buy and hold's
4. Sharpe > 0 with both fill models F1 and F2 (Alpaca bars, 2018 onward)
5. deflated p > 0.95 over the pool
6. the bootstrap's 5 % quantile of its Sharpe above 0

If it passes, a paper book is proposed (an equity lab signal with
`asset_class: us_equity`, plus what the engine would need for two rebalances
a day and auction orders), but nothing is deployed. If it fails, the overnight
pick still enters `book_portfolio` as a counted candidate sleeve, but it
cannot be proposed there either.

Run: `python -m lab.experiments.overnight` (`--refresh` downloads again,
`--source alpaca` refetches the 5-minute bars with keys).

<!-- generated below by lab.experiments.overnight; edit above this line only -->

## Results (generated 2026-10-15, data 1993-01-29 to 2026-10-15)

**Verdict: fails (2 of 6 gates), no paper book.** The in-sample pick is U2 QQQ · R1 trend (in-sample Sharpe 0.69 from 2001-01-02). Out of sample (2018-01-02 to 2026-10-15) it makes Sharpe 0.86, 9.1 % a year, drawdown 19.6 % at base costs (0.48 at stress), held 81.7 % of the nights; SPY bought and held 0.81, 14.6 %, drawdown 33.7 %; its own sleeve held 0.88, 19.9 %, drawdown 35.1 %. Deflated p 0.00 over 947 trials (noise bar about 2.26 on 252 sessions).

Failed: Sharpe above SPY's and its own sleeve's buy and hold; deflated p > 0.95.

### Where the return comes from (out of sample, gross, equal weight)

Each sleeve's nights and days before any cost, against holding it, and the day session at base costs.

| sleeve | from | nights, gross CAGR | days, gross CAGR | buy and hold Sharpe | buy and hold CAGR | buy and hold DD | day session net Sharpe |
|---|---|---|---|---|---|---|---|
| U1 SPY | 2018-01-02 | 10.5 % | 3.7 % | 0.812 | 14.6 % | 33.7 % | -0.077 |
| U2 QQQ | 2018-01-02 | 13.0 % | 6.1 % | 0.884 | 19.9 % | 35.1 % | 0.105 |
| U3 IWM | 2018-01-02 | 16.7 % | -7.3 % | 0.448 | 8.2 % | 41.1 % | -0.886 |
| U4 SPY+QQQ+IWM | 2018-01-02 | 13.5 % | 0.9 % | 0.745 | 14.4 % | 34.2 % | -0.325 |
| U5 sectors | 2018-01-02 | 9.7 % | 2.5 % | 0.741 | 12.4 % | 36.9 % | -0.571 |
| U6 large caps | 2018-01-02 | 15.8 % | 9.4 % | 1.233 | 26.5 % | 28.8 % | -0.350 |


### The 36 trials

Sharpe over 252 sessions, net of spread, SEC fee and TAF; stress doubles the spread.

| variant | IS Sharpe | OOS Sharpe | OOS stress | OOS CAGR | OOS DD | nights held | deflated p |
|---|---|---|---|---|---|---|---|
| U1 SPY · R0 always | -0.132 | 0.407 | -0.006 | 4.3 % | 29.8 % | 100.0 % | 0.000 |
| U1 SPY · R1 trend | 0.156 | 0.792 | 0.254 | 6.0 % | 18.6 % | 81.8 % | 0.000 |
| U1 SPY · R2 calm | -0.264 | 0.240 | -0.255 | 1.1 % | 11.0 % | 50.6 % | 0.000 |
| U1 SPY · R3 stormy | 0.004 | 0.337 | 0.112 | 3.2 % | 29.8 % | 49.4 % | 0.000 |
| U1 SPY · R4 turn of month | 0.007 | -0.232 | -0.434 | -1.2 % | 23.2 % | 19.2 % | 0.000 |
| U1 SPY · R5 holiday | -0.129 | -0.453 | -0.540 | -1.0 % | 10.2 % | 3.8 % | 0.000 |
| U2 QQQ · R0 always | 0.282 | 0.515 | 0.169 | 6.6 % | 31.4 % | 100.0 % | 0.000 |
| U2 QQQ · R1 trend | 0.689 | 0.858 | 0.478 | 9.1 % | 19.6 % | 81.7 % | 0.000 |
| U2 QQQ · R2 calm | 0.130 | 0.295 | -0.058 | 1.8 % | 15.3 % | 48.8 % | 0.000 |
| U2 QQQ · R3 stormy | 0.259 | 0.425 | 0.224 | 4.7 % | 27.8 % | 51.2 % | 0.000 |
| U2 QQQ · R4 turn of month | 0.269 | -0.162 | -0.317 | -1.2 % | 27.0 % | 19.2 % | 0.000 |
| U2 QQQ · R5 holiday | -0.059 | -0.415 | -0.482 | -1.2 % | 13.6 % | 3.8 % | 0.000 |
| U3 IWM · R0 always | -0.000 | 0.383 | -0.282 | 4.8 % | 30.3 % | 100.0 % | 0.000 |
| U3 IWM · R1 trend | 0.172 | 0.443 | -0.262 | 3.9 % | 25.2 % | 67.0 % | 0.000 |
| U3 IWM · R2 calm | 0.045 | 0.353 | -0.312 | 2.4 % | 19.2 % | 49.7 % | 0.000 |
| U3 IWM · R3 stormy | -0.028 | 0.239 | -0.146 | 2.3 % | 29.9 % | 50.3 % | 0.000 |
| U3 IWM · R4 turn of month | 0.344 | -0.395 | -0.704 | -2.6 % | 32.9 % | 19.2 % | 0.000 |
| U3 IWM · R5 holiday | 0.106 | -0.319 | -0.450 | -1.0 % | 12.0 % | 3.8 % | 0.000 |
| U4 SPY+QQQ+IWM · R0 always | 0.028 | 0.453 | -0.047 | 5.3 % | 28.9 % | 100.0 % | 0.000 |
| U4 SPY+QQQ+IWM · R1 trend | 0.396 | 0.779 | 0.184 | 6.4 % | 16.3 % | 76.8 % | 0.000 |
| U4 SPY+QQQ+IWM · R2 calm | -0.065 | 0.340 | -0.232 | 1.8 % | 13.0 % | 49.7 % | 0.000 |
| U4 SPY+QQQ+IWM · R3 stormy | 0.081 | 0.351 | 0.062 | 3.5 % | 28.9 % | 50.3 % | 0.000 |
| U4 SPY+QQQ+IWM · R4 turn of month | 0.209 | -0.278 | -0.512 | -1.7 % | 27.6 % | 19.2 % | 0.000 |
| U4 SPY+QQQ+IWM · R5 holiday | -0.075 | -0.408 | -0.508 | -1.1 % | 11.2 % | 3.8 % | 0.000 |
| U5 sectors · R0 always | -0.079 | -0.069 | -0.919 | -1.5 % | 35.0 % | 100.0 % | 0.000 |
| U5 sectors · R1 trend | 0.187 | -0.013 | -1.277 | -0.3 % | 21.7 % | 73.8 % | 0.000 |
| U5 sectors · R2 calm | -0.161 | -0.465 | -1.622 | -2.0 % | 19.9 % | 48.9 % | 0.000 |
| U5 sectors · R3 stormy | 0.002 | 0.109 | -0.376 | 0.6 % | 32.4 % | 51.1 % | 0.000 |
| U5 sectors · R4 turn of month | 0.099 | -0.421 | -0.873 | -1.9 % | 23.3 % | 19.2 % | 0.000 |
| U5 sectors · R5 holiday | -0.129 | -0.481 | -0.664 | -1.0 % | 9.3 % | 3.8 % | 0.000 |
| U6 large caps · R0 always | -0.209 | -0.024 | -1.164 | -1.2 % | 36.5 % | 100.0 % | 0.000 |
| U6 large caps · R1 trend | -0.283 | 0.239 | -1.132 | 1.6 % | 21.8 % | 73.6 % | 0.000 |
| U6 large caps · R2 calm | -0.150 | 0.015 | -1.386 | -0.1 % | 15.4 % | 48.1 % | 0.000 |
| U6 large caps · R3 stormy | -0.181 | -0.036 | -0.741 | -1.0 % | 28.5 % | 51.9 % | 0.000 |
| U6 large caps · R4 turn of month | -0.201 | -0.315 | -0.836 | -1.9 % | 28.6 % | 19.2 % | 0.000 |
| U6 large caps · R5 holiday | 0.020 | -0.631 | -0.853 | -1.6 % | 13.8 % | 3.8 % | 0.000 |


19 of 36 are positive out of sample at base costs; 1 beat SPY's buy and hold Sharpe.

### Can Alpaca fill it? The pick on 5-minute bars

Symbols with bars: QQQ. Window 2018-01-03 to 2026-10-14, base costs.

| fill | sharpe | cagr | max_dd | days |
|---|---|---|---|---|
| official open and close (Yahoo, the backtest) | 0.881 | 9.4 % | 19.6 % | 2205 |
| F1: buy at 15:50, sell at 09:35 | 0.993 | 10.6 % | 15.0 % | 2205 |
| F2: buy at the last trade before 16:00, sell at the first trade | 0.922 | 9.8 % | 20.0 % | 2205 |


The fills against the official prices, per symbol (mean per night, 2018 on; a night more than 5% away from Yahoo's is dropped as a data error):

| symbol | nights | dropped | corr_f2 | f2_minus_yahoo_bps | f1_minus_yahoo_bps |
|---|---|---|---|---|---|
| SPY | 2207 | 0 | 0.999 | 0.070 | 0.587 |
| QQQ | 2205 | 0 | 0.999 | 0.033 | 1.100 |
| IWM | 2207 | 0 | 0.997 | -0.377 | -0.074 |
| AAPL | 2205 | 0 | 0.998 | 0.007 | 6.735 |
| MSFT | 2204 | 1 | 0.998 | -0.106 | -0.414 |
| NVDA | 2204 | 1 | 0.999 | 0.125 | 3.750 |
| AMZN | 2205 | 0 | 0.998 | 0.111 | -0.345 |
| GOOGL | 2205 | 0 | 0.998 | -0.120 | 3.766 |
| META | 2205 | 0 | 0.999 | 0.012 | 1.653 |
| AVGO | 2203 | 2 | 0.998 | -0.179 | -4.183 |
| TSLA | 2203 | 2 | 0.999 | 0.695 | 2.966 |
| JPM | 2205 | 0 | 0.997 | 0.156 | 2.531 |
| LLY | 2198 | 1 | 0.998 | -0.204 | -2.485 |
| V | 2203 | 1 | 0.998 | -0.349 | 2.621 |
| WMT | 2205 | 0 | 0.998 | -0.064 | 4.113 |
| ORCL | 2203 | 2 | 0.999 | -0.134 | 1.196 |
| MA | 2204 | 1 | 0.995 | -0.220 | 2.713 |
| XOM | 2202 | 3 | 0.998 | -0.023 | 1.197 |
| NFLX | 2206 | 0 | 0.998 | 0.334 | 2.274 |
| COST | 2206 | 0 | 0.993 | 0.114 | -1.433 |
| JNJ | 2204 | 0 | 0.990 | -0.085 | -2.879 |
| HD | 2205 | 0 | 0.998 | -0.312 | 1.219 |


### Pick: bootstrap and years

Stationary bootstrap (block 20, 4000 draws): Sharpe 90 % band 0.26 to 1.45, 99% of draws above 0; minus SPY's -0.44 to 0.49. Correlation with SPY's daily return 0.41.

| year | pick | pick Sharpe | SPY | SPY Sharpe |
|---|---|---|---|---|
| 2018 | 2.6 % | 0.345 | -4.6 % | -0.190 |
| 2019 | 10.6 % | 1.161 | 31.2 % | 2.236 |
| 2020 | 18.7 % | 1.077 | 18.3 % | 0.670 |
| 2021 | 9.8 % | 0.963 | 28.7 % | 2.010 |
| 2022 | -6.6 % | -1.503 | -18.2 % | -0.710 |
| 2023 | 4.8 % | 0.529 | 26.2 % | 1.858 |
| 2024 | 24.8 % | 1.982 | 24.9 % | 1.832 |
| 2025 | 17.5 % | 1.718 | 17.7 % | 0.940 |
| 2026 | 1.1 % | 0.171 | 13.7 % | 1.328 |


### Gates

- pass: Sharpe > 0 at base and stress costs
- FAIL: Sharpe above SPY's and its own sleeve's buy and hold
- pass: drawdown below SPY's
- pass: Sharpe > 0 with fill models F1 and F2
- FAIL: deflated p > 0.95
- pass: bootstrap 5 % of Sharpe above 0

### Deflation pool

908 earlier trials at the variance backed out of the published bar (2.73 over 841) and this study's 39 (out of sample, clipped at an annual +-3): 947 trials. Equity Sharpes are per session, the crypto pool's per calendar day; pooling them is an approximation.

Counted beyond the grid: U2 QQQ · R1 trend · fill F1; U2 QQQ · R1 trend · fill F2; U2 QQQ · R1 trend · stress costs.

### Data

First valid close per symbol: SPY 1993-01-29, QQQ 1999-03-10, IWM 2000-05-26, XLB 1998-12-22, XLE 1998-12-22, XLF 1998-12-22, XLI 1998-12-22, XLK 1998-12-22, XLP 1998-12-22, XLU 1998-12-22, XLV 1998-12-22, XLY 1998-12-22, AAPL 1993-01-29, MSFT 1993-01-29, NVDA 1999-01-22, AMZN 1997-05-15, GOOGL 2004-08-19, META 2012-05-18, AVGO 2009-08-06, TSLA 2010-06-29, BRK-B 1996-05-09, JPM 1993-01-29, LLY 1993-01-29, V 2008-03-19, WMT 1993-01-29, ORCL 1993-01-29, MA 2006-05-25, XOM 1993-01-29, NFLX 2002-05-23, COST 1993-01-29, JNJ 1993-01-29, HD 1993-01-29.
Years left out for stale opens (share of opens equal to the previous close at or above 5 %): SPY 1993, 1994, 2017; IWM 2001, 2002; XLB 1999, 2000, 2001, 2003, 2005; XLE 1999, 2000, 2003, 2004; XLF 1998, 1999, 2003, 2004, 2005, 2006, 2013, 2017, 2019; XLI 1998, 1999, 2000, 2001, 2002, 2003, 2006; XLK 1998, 1999, 2000, 2005, 2006, 2017; XLP 1998, 1999, 2000, 2001, 2003, 2004, 2005, 2006, 2007, 2008, 2014; XLU 1999, 2001, 2002, 2003, 2006, 2007, 2009, 2013, 2014, 2019; XLV 1998, 2001, 2003, 2004, 2005, 2006, 2009, 2010; XLY 1998, 2004, 2005, 2006; AAPL 1993, 1994, 1995, 1996, 1997, 1998, 2003; MSFT 1993, 1994, 1995, 1996, 1997; NVDA 1999, 2009, 2012, 2013, 2014, 2015; AMZN 1997; TSLA 2011, 2012; BRK-B 1996, 1997, 1998, 1999, 2000, 2001, 2002, 2003, 2004, 2005, 2006, 2007, 2008; JPM 1993, 1994, 1995, 1996, 1997, 1998, 1999, 2000, 2001, 2002, 2003, 2004, 2005, 2006; LLY 1993, 1994, 1995, 1996, 1997, 1998, 1999, 2000, 2001, 2002, 2003, 2004, 2005, 2006, 2010, 2013; WMT 1993, 1994, 1995, 1996, 1997, 1998, 1999, 2000, 2001, 2002, 2003, 2004, 2005, 2006, 2016; ORCL 1993, 1994, 1995, 1996, 1997, 1998, 2005, 2017; MA 2006; XOM 1993, 1994, 1995, 1996, 1997, 1998, 1999, 2000, 2001, 2002, 2003, 2004, 2005, 2006; NFLX 2002, 2005, 2006; COST 1993, 1994, 1995, 1996, 1997, 1998, 1999, 2000, 2001; JNJ 1993, 1994, 1995, 1996, 1997, 1998, 1999, 2000, 2001, 2002, 2003, 2004, 2005, 2007; HD 1993, 1994, 1995, 1996, 1997, 1998, 1999, 2000, 2001, 2002, 2003, 2004, 2005, 2006.
Missing 5-minute bars: XLB, XLE, XLF, XLI, XLK, XLP, XLU, XLV, XLY, BRK-B.
