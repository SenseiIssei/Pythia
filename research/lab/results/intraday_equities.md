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
and nothing else, fetches 5-minute SIP bars from 2016 (about 5,000 requests,
paced at 200 a minute, so roughly half an hour the first time; `--feed iex`
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
