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
