# DT1: day trading on every liquid listed coin (no rug risk), flat by the day's end. Pre-registration

Registered 2026-10-30 and committed before any number below was computed. While scoping I looked only at which
folders and symbols the lab holds (`<data>/hist/binance_um/klines_1d`: 900 perps, delisted ones included;
`<data>/free/perps_all`: Hyperliquid's and Kraken Futures' listings; `<data>/hist/binance_um/metrics`: 20 symbols;
`<data>/binance/book20`: from 2026-09-30), at one file's columns and at whether data.binance.vision and Hyperliquid's
public API answer. I computed no volume rank, count, return, range or Sharpe.

Asked by the owner on 2026-10-30, after the live pump.fun test lost about 11 EUR to three one-transaction rugs in 37
trades (that bot is off). He wants one format from now on: day trading on as many coins as possible, with no rug
risk, and to know before he funds anything whether any day-trading rule earns money after the costs of a venue he
can reach. If none does, the results say so plainly.

Builds on the review of 2026-10-27 (`results/review_2026-10-27.md`, sections 2 and 3), R5's registry
(`metrics.trial_pool`, `<data>/trials/registry.jsonl`), R6's lockbox (from 2026-07-01, never read) and the readiness
ladder (`lab.ops.ladder`: a pass here is only the first rung, a paper book). It does not repeat `intraday_tsmom`
(hourly momentum of the day so far, gone since 2024), `fast_maker` / `fast_maker_5m` (holds under two days on 1h and
5-minute bars with resting limits on the Alpaca coins: nothing passed; their trade-through fill model is reused
here), `breakout_study`, `crypto_open_gap`, `daytrade_eq2` (equities), `book_depth_t4`, `reachable_venues_t12`
(Hyperliquid and Kraken Futures are the reachable perp venues), `kraken_fee_s1` (Kraken spot at 0.80 % a side rules
spot out at this horizon) or `range_forecast_rf1` (HAR-PK is the range forecast to use; no "good day" call beats
persistence). What is new: 1-minute bars of every liquid perp, point in time, the whole day-trading format (entry the
minute after the signal, flat by 23:55 UTC, a cap on positions, equal risk), and costs of the venues the owner can
reach.

Code: `lab.experiments.daytrade_dt1`, written after this file; tests `tests/test_daytrade_dt1.py`. Results:
`results/daytrade_dt1.md` and a README row. Nothing in this file may change once a result exists. Paper only:
nothing a live bot, a wallet or the engine reads changes; no key, no account, no order.

## Windows

In sample 2022-01-01 to 2024-12-31, out of sample 2025-01-01 to 2026-06-30 (judged). Minute bars after 2026-06-30
are never downloaded or loaded: the lockbox is untouched. 2024 is in R6's validation window and other studies have
looked at it with other rules; here it is in sample, as the task sets it, and only 2025-01 on is judged. The one
exception is the price check against Hyperliquid (below): its public API gives 1-minute candles only for the last
few days, so that check uses late October 2026; it compares prices only and makes no rule's number.

## Universe: "no rug risk", point in time

From `<data>/hist/binance_um/klines_1d` (every USDT-M perpetual Binance ever listed, delisted ones included). A
symbol's history is cut into segments at any gap of more than 30 days without a bar (a reused ticker starts again).
A coin is in the universe on UTC day d when, using days before d only:

- its segment's first daily bar is at least 180 days before d;
- the mean quote volume of days d-30 to d-1 (missing days as 0) is at least 50 M USD (the counts at 20 M and 100 M
  are reported, nothing is run on them);
- it is not excluded by name: stablecoins and fiat (the `fast_maker.STABLE` list plus USDC, BUSD, TUSD, FDUSD, USDP,
  DAI, USDE and the like), commodity-backed tokens and commodity or equity perps (PAXG, XAUT, XAU, XAG and any perp
  on a stock, share or ETF), index products (BTCDOM, DEFI, FOOTBALL, BLUEBIRD and any other `*DOM` or index perp),
  leveraged tokens (an UP, DOWN, BULL or BEAR suffix). Memecoins stay in when they pass the same bars; a token that
  only trades on one DEX pool is never a Binance perp and never qualifies.

Delisted coins stay in for every day they qualified: the universe is survivorship free. Its counts per quarter (20 M,
50 M, 100 M, and 50 M listed on Hyperliquid) are reported, and so is the "rug-like" tail that remains inside it: the
worst and best single 1-minute and single-day moves of a qualifying coin on a qualifying day, with coin and date
(delistings, hacks, LUNA in May 2022).

**The venue check: listed on Hyperliquid.** Hyperliquid's listing history comes from T12b's collector
(`<data>/free/perps_all/hyperliquid/listings.json`): a coin is listed from the day after its first funding record
until its last (delisted coins included, 56 of 235). Funding history starts 2023-05-12, so before that day the
history is unknown and Hyperliquid had no perps worth the name; the Hyperliquid universe is empty before then.
Tickers map as Hyperliquid's `kX` to Binance's `1000XUSDT`, otherwise `XUSDT`. The judged universe is the 50 M
universe restricted to coins listed on Hyperliquid that day. Kraken Futures' listings (`opening_us` in the same
collector) are reported as a share of trades, not used to cut the book.

**Prices.** Binance USD-M 1-minute klines from data.binance.vision (open, high, low, close, volume, quote volume,
trade count, taker buy volume and quote volume), downloaded for every month in which a symbol qualifies on any day
and the month before it, 2021-12 to 2026-06, into the agent's own folder. A minute without a bar has no return; a
price after a gap is the last close. **Price check:** for the 20 coins with the highest volume of the last 30 days
that Hyperliquid lists today, Hyperliquid's public `candleSnapshot` 1-minute closes against Binance's on the days
both have (late October 2026): the median and 99th percentile absolute gap in bps and the correlation of 1-minute
returns. Not judged; it says whether Binance minutes stand in for Hyperliquid's.

**Optional features, where they exist.** `<data>/binance/book20` starts 2026-09-30, inside the lockbox: not used.
`<data>/hist/binance_um/metrics` (5-minute open interest) holds 20 symbols from 2023-05: too few coins and no 2022,
not used. Funding (`<data>/hist/binance_um/funding`, Hyperliquid's in `<data>/free/perps_all/hyperliquid/funding`)
is used for costs only.

## Shared definitions

- **Minute sigma** sigma_1m(t): the root mean square of the coin's 1-minute log returns over the 1,440 minutes before
  minute t (t itself excluded), at least 1,000 of them present. z(t) = r(t) / sigma_1m(t).
- **Expected range ER(d)**: HAR-PK as in RF1 (the next day's sqrt Parkinson volatility on its means over 1, 7 and 30
  days, one QLIKE scale c = mean(y / g) on the training rows, y = (H - L) / previous close), but one pooled fit over
  every Binance perp in the universe file per quarter (refitted at each quarter start on all rows before it, from
  2020-01-01), so a coin with 180 days of history has a forecast. ER(d) is made at 00:00 UTC of d from daily bars to
  d-1, as a fraction of the previous close; in price, ER(d) x C(d-1).
- **Volume z**: log(1 + quote volume) of the minute against the mean and standard deviation of the previous 1,440
  minutes. **Taker-buy share**: taker buy quote volume over quote volume of the minute.

## The day-trading format (every rule)

- A signal is known at the close of minute t. The entry fills at the open of minute t+1 (base) and, as the second
  case, at the open of t+2 (one more minute of latency).
- Every position is closed by the open of 23:55 UTC at the latest; no entry at or after 23:55; nothing is held across
  the day's end. Days are independent books.
- **At most N = 5 positions at once**, one per coin at a time. Candidates are taken in time order; several in the
  same minute by priority (S: |z| larger first; lead-lag: the alt's 30-day volume; D: 30-day volume; P: predicted move
  over cost); a candidate finding five open positions or its coin already held is dropped.
- **Equal risk per trade**: every trade has a protective stop and risks 0.25 % of equity at it: notional = 0.0025 /
  stop distance (as a return), capped at 1x equity per position (so at most 5x gross). S and P stops sit at 3 x
  sigma_1m x sqrt(H) from the entry (a bracket's stop at its own distance, below); D stops at 0.5 x ER, which is the
  same idea on the day's scale. A stop fills at the stop price or at the minute's open when the open is already
  beyond it; a minute that touches both the stop and the take counts as the stop.
- Book: daily return = the sum over the day's trades of notional x net return. Sharpe over every day of the window
  (flat days as 0), annualised with 365.

## Costs (per side, on notional)

- **Hyperliquid taker (base): 4.5 bps fee plus 1 bp slippage** for the day's top 20 coins by 30-day volume. For the
  rest the slippage adds half the excess of the coin's spread proxy over the top 20's: slip = 1 bp + max(0, (S_i -
  S_top20) / 2), capped at 50 bps, where S_i is Abdi and Ranaldo's (2017) spread estimate from the coin's 1-minute
  close, high and low over the 30 days before d (sqrt of the mean of 4 (c_t - eta_t)(c_t - eta_t+1), log prices,
  eta the mid-range, negative means as 0) and S_top20 its median over the top 20.
- **Kraken Futures taker: 5 bps fee** plus the same slippage, on the same trades.
- **Maker case: 1.5 bps** (Hyperliquid's base maker), with `fast_maker`'s trade-through fill model on 1-minute bars:
  the entry is a limit at the signal minute's close placed at the entry minute and resting 3 minutes; it fills only
  where a low (a buy) or high (a sell) trades 1 bp or more through it, the filled share growing linearly to the whole
  order at 10 bps through (the most reached in the 3 minutes), at most 10 % of the minutes' quote volume; a missed
  entry stays missed and takes no slot. A time exit is a limit at the exit minute's open resting 3 minutes, the rest
  at taker cost at the next open; a take level rests as a limit and fills at maker when traded 1 bp through; stops and
  the 23:55 close are taker. fast_maker's 3 bps adverse-selection haircut is shown as a sensitivity, not judged.
- **Funding at its real rate**: a position open across a settlement pays or receives side x rate x notional at each
  one (Hyperliquid's hourly rates for the Hyperliquid cases; Binance's own settlements for the Binance universe).
- **Break-even fee**: for every rule, the fee a side at which its mean net per trade is zero:
  (mean gross - 2 x mean slippage - mean funding) / 2.

## Families (every cell a trial)

**S, minute spikes (144 rules).**
- S-own: a 1-minute |z| beyond k, k in {3, 4, 6}; confirmation none, volume z above 3, or the taker-buy share above
  0.7 for an up spike / below 0.3 for a down spike; continuation (trade with the spike) or fade (against it); exit
  after H in {1, 5, 15, 30, 60, 240} minutes with the 3 sigma sqrt(H) stop (108 rules), or a bracket: take at 2 x
  sigma_1m x sqrt(60), stop at 1 x sigma_1m x sqrt(60), else out after 60 minutes (18 rules).
- S-lead: "BTC spiked, the alt not yet": BTCUSDT's 1-minute |z| beyond k in {3, 4, 6} while the alt's |z| in the same
  minute is below 1; every such alt in the universe is traded in BTC's direction, exit after H in {1, 5, 15, 30, 60,
  240} (18 rules).

**D, day patterns (12 rules).** One trade per coin, rule and day (the first signal).
- Opening range breakout: the range of the first 30 or 60 minutes of the UTC day, or of the US cash session from
  13:30 UTC (30 or 60 minutes); the first minute closing above its high goes long, below its low short, entries until
  23:00.
- Yesterday's high / low breakout: the first minute of the day closing above yesterday's high (long) or below its low
  (short).
- Exits for both: (A) stop 0.5 ER, else the 23:55 close; (B) the same stop and a take where the day's range reaches
  its forecast (long: the day's low so far plus ER; short: the high so far minus ER), skipped when that is not beyond
  the entry. ER is the scale and the target here, not a call on the day.
- VWAP reversion: from 01:00 UTC, when the close is beyond the day's VWAP by m x ER, m in {0.25, 0.5}, fade it; take
  at the VWAP of the signal minute, stop 0.5 ER beyond the entry, else the 23:55 close.
- That is ORB 4 windows x 2 exits, yesterday 2 exits, VWAP 2 (12).

**P, prediction (8 rules): LightGBM regression**, fixed settings (300 trees, learning rate 0.05, 31 leaves, at least
2,000 rows a leaf, feature and row fraction 0.8 and 0.5, L2 10, seed 7, deterministic, 4 threads). Decision points
every 15 minutes per coin in the universe. Target: the return from the open of t+1 to the open of t+1+H over sigma_1m
x sqrt(H), clipped at +-6, H in {15, 60}. Features (all known at the close of t): the coin's returns over the last 1,
5, 15 and 60 minutes and its high-low ranges over 15 and 60 minutes, in its sigma units; volume z of the last minute
and of the last 15; the taker-buy share of the last 5 and 60 minutes; minute of the day; BTC's returns over 1, 5, 15
and 60 minutes in its sigma units; the day's range so far over ER; where the close sits in the day's range; the
distance to the day's VWAP over ER. Walk-forward by quarter: refitted at each quarter start from 2022Q3 on every
earlier decision point (at most 3 M rows, a seeded sample), with a one-day embargo before the quarter. A trade when
the predicted move |pred| x sigma_1m x sqrt(H) is above the coin's round trip (2 x (4.5 bps + slip)) plus a margin m
in {0, 5, 10, 20} bps, in the predicted direction, exit after H with the 3 sigma sqrt(H) stop. H x m is 8 rules; the
margin "fitted in sample" is the one with the best in-sample (2022Q3 to 2024Q4, all walk-forward predictions) mean
net per trade, reported as the P pick per H; all 8 are judged and counted.

## Cases and trials (R5's registry, family hand, source this file)

Every rule (164) runs in four cases: Hyperliquid taker (the base), the same one minute late, the maker case, Kraken
Futures taker. Each (rule, case) is a trial `hand:dt1:<rule>:<case>`, registered with its in-sample annual Sharpe
(Binance universe, 2022 to 2024, the case's costs) before any out-of-sample number is computed: 656 trials. The
universe count, the tail and the price check are not trials.

## Pass (per rule and case; all must hold out of sample, 2025-01-01 to 2026-06-30)

On the Hyperliquid universe:
1. mean net per trade above 0, and the 5 % quantile of a day-block bootstrap of it above 0 (the stationary bootstrap
   over days, mean block 5 days, 2,000 draws, seed 7; per draw the sum of net over the sum of trades);
2. at least 100 trades;
3. the book's Sharpe above 0 and above BTC buy and hold's (BTCUSDT perp, close to close, no cost) on the same days;
4. one minute late (for the taker cases) the mean net per trade still above 0;
5. deflated against the registry: DSR of the book's daily returns at least 0.95 over R5's pool of all, this study's
   trials included.
And on the whole survivorship-free Binance 50 M universe, the same rule and case: Sharpe above 0.

A pass becomes a paper book on Hyperliquid's public data in its own later commit (PAPER ONLY: no key, no account,
nothing sent), and goes up the readiness ladder from there. No live trading without the owner's yes, and then within
his 50 EUR limit. Without a pass nothing reaches a book, the engine or a wallet, and the results say plainly that no
day-trading rule earns money after costs at a venue he can reach.

## Reported

`results/daytrade_dt1.md`: the universe per quarter (20 M, 50 M, 100 M, Hyperliquid), the tail, the price check;
per rule and case the trades, trades a day, hold, gross and net bps per trade, the bootstrap band, the break-even fee
a side, Sharpe in and out of sample, BTC's Sharpe on the same days, the Binance-universe Sharpe, the late case, the
DSR and the verdict; the P picks and their margins; the maker haircut sensitivity; a README row.
