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

Code: `lab/experiments/intraday_equities.py`, tests
`tests/test_intraday_equities.py` (synthetic bars). Each run writes its own
section below (proxy, alpaca) and leaves everything above as it was.

### Implementation choices (made before the first real run; none adds a trial)

The pre-registration left these open; they were fixed in the code and tested
on synthetic bars before any real bar was loaded.

- **Long-only ORB** is the long/short rule with the shorts dropped: the first
  close outside the range decides the day either way, so a first break down
  leaves the long-only book in cash for the day.
- **Gap entries** need the gap still open at the first bar's close (a fade is
  not entered when bar 0 has already closed through the previous close, a go
  not when it has already failed). Exits are checked from the second bar on.
- **VWAP** uses the bar's own VWAP times volume where the source has it
  (Alpaca's `vw`), else (high + low + close) / 3 times volume (the proxy's tick
  count). A long exited on a VWAP cross may flip short on the same close when
  the short rule fires.
- **Positions** are measured from their own entry price (shares bought once);
  costs are charged on each change of position at the pre-registered rate per
  side. Fees on every sell (a long exit or a short entry): SEC 27.80 USD per
  million sold and FINRA TAF 0.000166 USD per share without its per-trade cap
  (both conservative); on the proxy the share price is the index divided by
  10 (SPX, RUT) or 40 (NDX). Fees are not doubled in the stress case.
- **Fills one bar later** delays every entry and stop exit by one bar; the
  forced exit stays at the 15:55 open.
- **Alpaca calendar:** a market day is a SPY session with at least 70 bars and
  one at 15:55. Half days (13:00 close) are left out entirely, as on the
  proxy; a symbol counts on a day with at least 39 bars (missing bars repeat
  the last close with zero volume).
- **Proxy calendar:** a market day is a day on which at least one of the
  three CFDs passes the minutes and volume rule. Oanda's SPX500 feed is thin
  in some years (2017: 164 of 257 days with 300 session minutes, against 249
  for the other two), so SPX alone would have dropped days the others trade.
  Seen in the bar counts, before any strategy number.
- **Universe:** on the first market day of each month, the 20 candidates with
  the highest mean session dollar volume over the previous 20 market days
  (at least 15 of them traded), held for the month.
- **Deflation pool.** Gate 1 is over this study's 46 trials as registered.
  The pooled figure is reported twice: with the 377 hand-study trials the
  pre-registration named (published bar 2.43) and with the 677 of the global
  ledger now (bar 2.45, `factory_first_run.md`), the prior variance backed out
  of the published bar as `alpaca_universe` does. Studies that ran alongside
  this one (memecoins, listings, equities_ranking) are not in the 677; adding
  them only raises the bar.
- **From 2024.** The out-of-sample windows stay as registered (proxy from
  2014, Alpaca from 2021). The Sharpe from 2024 on is reported beside them
  for the Alpaca run, as information, not as a gate.

### Run it on the server (Alpaca data)

The Alpaca keys exist only on the server. With the paper pair in
`/etc/pythia/alpaca-paper.env` (as for `lab.experiments.listings`):

```bash
docker run --rm --cpus 4 --memory 8g --env-file /etc/pythia/alpaca-paper.env -v /srv/pythia-data:/data -v /opt/pythia-lab:/app pythia-lab python -m lab.experiments.intraday_equities --source alpaca
```

It reads `APCA_API_KEY_ID` and `APCA_API_SECRET_KEY` from the environment
and nothing else, fetches 5-minute SIP bars from 2016 (about 5,600 requests,
one per symbol and month, paced under 200 a minute, so about an hour the
first time and seconds after that; `--feed iex`
if the plan refuses SIP), caches them under
`/srv/pythia-data/intraday/alpaca-sip/<SYM>/<YYYY-MM>.parquet`, replaces the
alpaca section below, and writes
`/srv/pythia-data/reports/intraday_equities/alpaca-latest.{md,json}`. Copy the
updated `results/intraday_equities.md` back into the repo. `--event-days
FILE.csv` (one date per line) adds FOMC and CPI days to the macro filter.

The keyless proxy runs anywhere:

```bash
PYTHIA_DATA=F:/PythiaData PYTHIA_INTRADAY_DATA=F:/PythiaData/agent-intraday/bars PYTHIA_REPORTS=F:/PythiaData/agent-intraday/reports python -m lab.experiments.intraday_equities --source proxy
```

### What a day book would need in the engine (note, no engine change)

The engine can already trade a lab book of US shares on Alpaca in the regular
session: `asset_class: "us_equity"` signals map to `alpaca:<SYM>`
(`crates/pythia-core/src/lab.rs`), equity orders go out as `day` market or
marketable limit orders, and lab books trade only while the broker clock says
the market is open. A book that must be flat by the close is not supported
yet. It would need:

1. **A 5-minute signal cycle.** `lab_loop` reads `signals/*/latest.json`
   every 300 s on a timer not aligned to bar closes, so a decision can wait up
   to five minutes. Read every 15 to 30 s, or right after each bar close, and
   let the lab writer run every five minutes (a cron or a small loop next to
   the recorder).
2. **Short validity.** The lab writers set `valid_until_ms` 36 hours ahead;
   a day book's signal must expire within one bar (about 6 minutes), so a
   stalled writer leaves the book flat instead of holding a stale intraday
   position.
3. **A forced flat time.** Nothing in the engine closes a position at a time
   of day. Alpaca's clock gives `next_close` (parsed in `connectors/alpaca.rs`
   but not passed on); a day book needs "flat at next_close minus 5 minutes",
   which also covers half days (13:00 close), plus a check that refuses new
   entries after the last entry time. Relying on the lab to publish zero
   weights for the 15:55 bar is not enough: a late or missing signal would
   carry the position overnight.
4. **Shorts, only if a long/short rule were picked.** `lab::rebalance` clamps
   weights at zero and caps sells at the holding, and Alpaca shorts are off by
   default (`allow_shorts`) and need whole, shortable shares. The registered
   rule is that only a long-only pick becomes a book, so this is not needed.
5. **Pattern day trading.** Under 25,000 USD of equity a margin account may
   make at most three day trades in five sessions; a day book makes one or
   more a day per symbol. The engine already reads `day_trade_limit_reached`
   from the account; the book must stop opening positions when it is set,
   and the paper account should carry at least 25,000 USD.
6. **Order size and the rebalance band.** `lab::rebalance` skips any
   difference below the larger of 5 USD and 0.2 % of capital, a full exit
   included, so a remnant under that size would stay overnight. The flat-time
   exit must close the whole position whatever its size, and fills should be
   logged against the bar open they were meant for, so realised and modelled
   cost can be compared.

### Reading of the proxy run (2026-10-15)

**Nothing passes on the proxy; no paper book, and nothing is pending.** The
proxy covers only the ETF leg (S&P 500, Nasdaq 100 and Russell 2000 CFDs,
2005 to 2020-05, out of sample from 2014); the registered verdict on Alpaca
bars, with the stock leg and 2021 onwards, needs the server run above.

- The in-sample pick, gap fade at 1.5 with shorts, makes Sharpe 0.31 in
  sample and 0.05 out of sample, -0.08 with costs doubled and -0.20 filled a
  bar late; it trades 0.03 times a day per index, is positive in 2 of 7
  out-of-sample years, and its bootstrap band is -0.75 to 0.64. Every one of
  the six gates fails, for it and for each family's pick.
- 8 of 46 trials are positive in sample, 5 out of sample, none above 0.36.
  Deflated p is 0.00 over the 46 (noise bar 1.94) and over the pooled 723
  (bar 2.48). SPY bought and held makes 0.47 over the same years (price
  only, the CFD pays no dividends).
- **The spread is the whole story for the frequent rules.** Holding the
  session itself (open to 15:55) earns Sharpe 0.22 before costs and -0.72
  after 2 to 3 bps a side. ORB loses even before costs (-0.08 for the
  15-minute long pick: index breakouts did not continue intraday from 2014).
  End-of-day momentum (the first half hour predicting the last) is positive
  before costs in its long variants (0.28 to 0.44) but earns under 1 bp a trade against about 5
  bps of round trip. VWAP reversion at k 2 long is 0.49 before costs and
  -0.18 after.
- At zero cost the best of the 46 is gap go 0.5 long at 0.89 out of sample,
  but it was -0.18 in sample, so no honest rule would have picked it, and the
  best of 46 noise books reaches 1.94. The registered 2 bps for SPY is above
  its real half spread (about a cent on 400 to 600 USD, a fraction of a bp),
  so the server run may see lower costs in practice, but even the gross
  numbers here would not clear the bar.
- The long-only candidate a book would need (gap fade 1.5 long) makes 0.23
  out of sample on about 12 trades a year across the three indices: too few
  to be told from luck (deflated p 0.00).

<!-- generated below by lab.experiments.intraday_equities --source proxy; do not edit -->

## Proxy run (Oanda index CFDs as SPY, QQQ, IWM; no single stocks)

Generated 2026-10-15T13:00:49+00:00. Data 2005-01-03 to 2020-05-13 (3827 sessions), in sample from 2005-01-01 (2244 days), out of sample from 2014-01-01 (1583 days), 3.0 symbols a day on average. SPY as SPX500_USD: 3556 valid days of 3967 with session quotes. QQQ as NAS100_USD: 3731 valid days of 3965 with session quotes. IWM as US2000_USD: 3787 valid days of 3957 with session quotes.

**Verdict: nothing passes on the proxy (a pass here only marks it pending the Alpaca run).** Pick by in-sample Sharpe: Gap fade 1.5 L/S, out of sample Sharpe 0.05 (-0.08 with costs doubled, -0.20 filled a bar late), in sample 0.31; deflated p 0.00 over 46 trials.

### Every trial (base cost; Sharpe from daily book returns, x sqrt 252)

`oos_sharpe_gross` is before spread and fees (information, never judged); `trades_per_day` entries per symbol slot; `net_bps_per_trade` net P&L per entry on the slot's capital; `expo` mean share of the session in a position.

| name | is_sharpe | oos_sharpe | oos_sharpe_2x | oos_sharpe_gross | oos_cagr | oos_max_dd | trades_per_day | net_bps_per_trade | expo | deflated_p |
|---|---|---|---|---|---|---|---|---|---|---|
| ORB 5m long | -0.395 | -0.570 | -1.331 | 0.241 | -0.044 | 0.287 | 0.481 | -3.470 | 0.460 | 0.000 |
| ORB 5m long stop | -0.564 | -1.181 | -2.177 | -0.114 | -0.066 | 0.368 | 0.481 | -5.466 | 0.269 | 0.000 |
| ORB 5m L/S | -0.655 | -1.112 | -2.173 | 0.014 | -0.117 | 0.590 | 0.957 | -4.905 | 0.915 | 0.000 |
| ORB 5m L/S stop | -0.850 | -1.882 | -3.182 | -0.502 | -0.154 | 0.672 | 0.957 | -6.773 | 0.527 | 0.000 |
| ORB 15m long | -0.390 | -0.932 | -1.731 | -0.081 | -0.066 | 0.364 | 0.484 | -5.414 | 0.433 | 0.000 |
| ORB 15m long stop | -0.592 | -1.266 | -2.225 | -0.242 | -0.074 | 0.399 | 0.484 | -6.112 | 0.319 | 0.000 |
| ORB 15m L/S | -0.715 | -1.601 | -2.670 | -0.465 | -0.159 | 0.681 | 0.952 | -6.995 | 0.853 | 0.000 |
| ORB 15m L/S stop | -0.953 | -1.889 | -3.110 | -0.592 | -0.163 | 0.691 | 0.952 | -7.229 | 0.618 | 0.000 |
| ORB 30m long | -0.658 | -1.445 | -2.225 | -0.611 | -0.104 | 0.501 | 0.495 | -8.538 | 0.405 | 0.000 |
| ORB 30m long stop | -0.796 | -1.668 | -2.574 | -0.697 | -0.102 | 0.499 | 0.495 | -8.465 | 0.331 | 0.000 |
| ORB 30m L/S | -1.003 | -2.014 | -3.083 | -0.877 | -0.192 | 0.747 | 0.938 | -8.790 | 0.772 | 0.000 |
| ORB 30m L/S stop | -1.165 | -2.153 | -3.352 | -0.879 | -0.183 | 0.731 | 0.938 | -8.384 | 0.628 | 0.000 |
| Gap fade 0.5 long | 0.056 | -0.201 | -0.544 | 0.165 | -0.011 | 0.126 | 0.140 | -2.695 | 0.107 | 0.000 |
| Gap fade 0.5 L/S | -0.268 | -1.101 | -1.683 | -0.475 | -0.070 | 0.382 | 0.327 | -8.525 | 0.257 | 0.000 |
| Gap go 0.5 long | -0.184 | 0.354 | -0.154 | 0.889 | 0.014 | 0.042 | 0.187 | 3.169 | 0.151 | 0.000 |
| Gap go 0.5 L/S | -0.537 | -0.165 | -0.757 | 0.466 | -0.012 | 0.207 | 0.327 | -1.269 | 0.258 | 0.000 |
| Gap fade 1.0 long | 0.037 | -0.072 | -0.237 | 0.104 | -0.003 | 0.065 | 0.047 | -1.964 | 0.041 | 0.000 |
| Gap fade 1.0 L/S | -0.177 | -0.284 | -0.551 | 0.003 | -0.011 | 0.097 | 0.088 | -4.765 | 0.079 | 0.000 |
| Gap go 1.0 long | 0.057 | -0.098 | -0.354 | 0.174 | -0.002 | 0.040 | 0.041 | -1.746 | 0.038 | 0.000 |
| Gap go 1.0 L/S | -0.175 | -0.295 | -0.564 | -0.008 | -0.012 | 0.118 | 0.088 | -4.951 | 0.079 | 0.000 |
| Gap fade 1.5 long | 0.268 | 0.226 | 0.140 | 0.316 | 0.005 | 0.031 | 0.016 | 11.828 | 0.015 | 0.000 |
| Gap fade 1.5 L/S | 0.314 | 0.053 | -0.080 | 0.193 | 0.001 | 0.080 | 0.030 | 1.802 | 0.028 | 0.000 |
| Gap go 1.5 long | -0.395 | 0.005 | -0.102 | 0.120 | -0.000 | 0.028 | 0.014 | 0.199 | 0.013 | 0.000 |
| Gap go 1.5 L/S | -0.499 | -0.331 | -0.460 | -0.193 | -0.009 | 0.090 | 0.030 | -11.392 | 0.028 | 0.000 |
| VWAP k 1.0 long | -1.354 | -1.415 | -2.669 | -0.058 | -0.083 | 0.446 | 0.649 | -5.201 | 0.212 | 0.000 |
| VWAP k 1.0 L/S | -2.149 | -2.034 | -3.905 | -0.098 | -0.158 | 0.726 | 1.272 | -5.251 | 0.453 | 0.000 |
| VWAP k 1.5 long | -0.619 | -0.781 | -1.675 | 0.188 | -0.040 | 0.273 | 0.385 | -4.029 | 0.139 | 0.000 |
| VWAP k 1.5 L/S | -1.204 | -1.073 | -2.309 | 0.226 | -0.074 | 0.499 | 0.720 | -4.121 | 0.274 | 0.000 |
| VWAP k 2.0 long | -0.038 | -0.184 | -0.815 | 0.493 | -0.009 | 0.137 | 0.231 | -1.357 | 0.086 | 0.000 |
| VWAP k 2.0 L/S | -0.434 | -0.599 | -1.470 | 0.320 | -0.035 | 0.324 | 0.411 | -3.243 | 0.156 | 0.000 |
| EOD momentum first long | -1.289 | -2.024 | -4.260 | 0.436 | -0.051 | 0.334 | 0.507 | -4.082 | 0.033 | 0.000 |
| EOD momentum first L/S | -1.657 | -2.766 | -5.676 | 0.326 | -0.102 | 0.531 | 0.955 | -4.445 | 0.062 | 0.000 |
| EOD momentum first+12th long | -1.188 | -2.169 | -4.392 | 0.282 | -0.056 | 0.348 | 0.518 | -4.381 | 0.034 | 0.000 |
| EOD momentum first+12th L/S | -1.628 | -2.888 | -5.730 | 0.133 | -0.109 | 0.542 | 0.958 | -4.749 | 0.062 | 0.000 |

Robustness on each family's pick (counted):

| name | is_sharpe | oos_sharpe | oos_sharpe_2x | oos_sharpe_gross | oos_cagr | oos_max_dd | trades_per_day | net_bps_per_trade | expo | deflated_p |
|---|---|---|---|---|---|---|---|---|---|---|
| ORB 15m long · one bar later | -0.487 | -0.976 | -1.786 | -0.114 | -0.068 | 0.378 | 0.484 | -5.594 | 0.427 | 0.000 |
| ORB 15m long · macro-day filter | -0.295 | -1.077 | -1.857 | -0.245 | -0.074 | 0.400 | 0.460 | -6.404 | 0.411 | 0.000 |
| ORB 15m long · abnormal-open filter | -0.426 | -0.953 | -1.785 | -0.066 | -0.064 | 0.353 | 0.476 | -5.311 | 0.425 | 0.000 |
| Gap fade 1.5 L/S · one bar later | 0.214 | -0.201 | -0.343 | -0.050 | -0.005 | 0.101 | 0.030 | -6.363 | 0.028 | 0.000 |
| Gap fade 1.5 L/S · macro-day filter | 0.362 | 0.052 | -0.075 | 0.186 | 0.001 | 0.080 | 0.029 | 1.831 | 0.027 | 0.000 |
| Gap fade 1.5 L/S · abnormal-open filter | 0.164 | -0.463 | -0.614 | -0.297 | -0.007 | 0.079 | 0.022 | -13.135 | 0.021 | 0.000 |
| VWAP k 2.0 long · one bar later | -0.149 | -0.207 | -0.814 | 0.444 | -0.010 | 0.164 | 0.231 | -1.587 | 0.084 | 0.000 |
| VWAP k 2.0 long · macro-day filter | -0.147 | -0.136 | -0.752 | 0.524 | -0.007 | 0.126 | 0.220 | -1.029 | 0.081 | 0.000 |
| VWAP k 2.0 long · abnormal-open filter | -0.131 | -0.434 | -1.069 | 0.256 | -0.018 | 0.162 | 0.221 | -3.142 | 0.083 | 0.000 |
| EOD momentum first+12th long · one bar later | -1.377 | -1.939 | -4.031 | 0.353 | -0.054 | 0.346 | 0.518 | -4.189 | 0.027 | 0.000 |
| EOD momentum first+12th long · macro-day filter | -1.260 | -2.057 | -4.189 | 0.295 | -0.053 | 0.334 | 0.494 | -4.326 | 0.032 | 0.000 |
| EOD momentum first+12th long · abnormal-open filter | -1.274 | -2.477 | -4.950 | 0.289 | -0.056 | 0.344 | 0.513 | -4.435 | 0.033 | 0.000 |

46 trials in this study; the best of that many noise books would show an annual Sharpe of about 1.94. Pooled with the lab's earlier trials: hand studies (pre-registered) 423 trials, bar 2.47, deflated p 0.00; global ledger now 723 trials, bar 2.48, deflated p 0.00.

### Benchmarks (out of sample)

| book | is_sharpe | oos_sharpe | oos_cagr | oos_vol | oos_max_dd | recent_sharpe |
|---|---|---|---|---|---|---|
| session drift (open to 15:55, same symbols and costs) | -0.687 | -0.715 | -0.095 | 0.129 | 0.500 | n/a |
| session drift before costs (information) | -0.010 | 0.218 | 0.020 | 0.129 | 0.234 | n/a |
| SPY buy and hold (S&P 500 CFD, no dividends) | 0.329 | 0.474 | 0.071 | 0.180 | 0.348 | n/a |

The pick's daily returns correlate -0.06 with SPY's. The pick on the ETF leg alone (information, not a trial): out of sample Sharpe 0.05. Best long-only variant in sample (only a long-only pick can become a book): Gap fade 1.5 long, out of sample 0.23 (0.14 doubled), deflated p 0.00.

### Gates, per pick

| pick | trial | 1 | 2 | 3 | 4 | 5 | 6 | boot 5 % | boot 95 % | minus SPY 5 to 95 % | from 2024 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| overall | Gap fade 1.5 L/S | FAIL | FAIL | FAIL | FAIL | FAIL | FAIL | -0.746 | 0.638 | -1.42 to 0.37 | n/a |
| ORB | ORB 15m long | FAIL | FAIL | FAIL | FAIL | FAIL | FAIL | -1.457 | -0.379 | -2.01 to -0.88 | n/a |
| Gap | Gap fade 1.5 L/S | FAIL | FAIL | FAIL | FAIL | FAIL | FAIL | -0.746 | 0.638 | -1.42 to 0.37 | n/a |
| VWAP | VWAP k 2.0 long | FAIL | FAIL | FAIL | FAIL | FAIL | FAIL | -0.738 | 0.413 | -1.59 to 0.23 | n/a |
| Momentum | EOD momentum first+12th long | FAIL | FAIL | FAIL | FAIL | FAIL | FAIL | -3.664 | -1.089 | -4.56 to -1.22 | n/a |

Gates: 1 deflated p > 0.95 over this study's trials; 2 OOS Sharpe >= half the in-sample one; 3 Sharpe > 0 with costs doubled; 4 bootstrap 90 % lower bound > 0; 5 positive in >= 60 % of OOS years; 6 Sharpe > 0 with fills one bar later.
Bootstrap: stationary, mean block 10 days, 5,000 draws, of the out-of-sample Sharpe.

### The overall pick by year (out of sample, return at base cost)

| year | return |
|---|---|
| 2014 | 0.023 |
| 2015 | 0.053 |
| 2016 | -0.013 |
| 2017 | -0.018 |
| 2018 | -0.003 |
| 2019 | -0.019 |
| 2020 | -0.014 |

<!-- end of the generated proxy section -->
