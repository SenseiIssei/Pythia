# I1: calendar and lead-lag on the hourly panel, as inputs for every strategy: pre-registration

Registered 2026-10-27 and committed before any number below was computed.
Code: `lab.experiments.market_structure_i1`. Results: `results/market_structure_i1.md`.
Nothing here may change once a result exists.

Changed after the review of 2026-10-27: the regime part (an HMM and a Bayesian
online change point detector on BTC's daily return, vol and funding, as a gate
in the strategy factory and an input of the zoo's allocator) is dropped. Regimes
failed twice already (M5 `regime`, M7 `regime_hmm` in the lab README); a third
try would mostly add trials. What is left: the calendar re-tested on the long
hourly history with costs, and lead-lag on the hourly panel only (no 5-minute
tests).

## Data

- Binance spot 1h klines (`<data>/hist/binance_spot/klines_1h`) of the lab's 20
  coins (`lab.data.UNIVERSE`), each coin's latest continuous segment
  (`picks.hourly_segments`), from 2020-01-01 to the last complete UTC day.
  Today's 20 liquid coins: survivorship is accepted for a timing study and
  named in the report.
- The alt basket: the equal-weight mean of the hourly log returns of the 18
  coins other than BTC and ETH that have that hour.
- Funding: Binance USD-M settled rates (`lab.data.funding`, from 2020), known
  at the settlement time. Open interest: the 5-minute metrics archive, the last
  value of each hour (`lab.data.open_interest_hourly`, from 2022), known at the
  end of the hour.
- US index hours: Yahoo 1h bars of SPY and QQQ from the candle store (about two
  years, from 2024-10; the cash ETFs stand for the index futures, which the lab
  has no history of). Bars open at :30 New York; a bar is known at its open
  plus one hour.
- FOMC and CPI days: `lab/collect/macro_calendar.json` (D2), scheduled FOMC
  meetings only (an unscheduled one is not known in advance).

## Halves

Discovery 2020-01-01 to 2023-12-31, holdout 2024-01-01 to the end. Open
interest tests: 2022 to 2023 and 2024 on. SPY and QQQ tests: their first and
second half of bars.

## Calendar tests (44 per asset; BTC, ETH, the alt basket: 132)

Hourly log returns inside a window against those outside it, Welch t over the
whole period. Windows (UTC unless named):

- hour of day: each of the 24 hours (24);
- weekday: each of the 7 days, all 24 hours of it (7); the weekend (1);
- US cash open: the hours starting 09:00 and 10:00 New York, Monday to
  Friday (US holidays not removed); US cash close: 15:00 and 16:00 New York;
  Asian open: 00:00 and 01:00 UTC (Tokyo 09:00), Monday to Friday (3);
- turn of month: the last day and the first three days (1);
- Deribit monthly expiry (the last Friday of the month, 08:00 UTC): the 24
  hours before it and the 24 hours after it (2);
- Binance funding (00, 08, 16 UTC): the hour before a settlement and the hour
  after it (2);
- FOMC: the statement day (New York) and the hours starting 14:00 and 15:00 New
  York on it; CPI: the release day and the hours starting 08:00 and 09:00 New
  York on it (4).

Cost check of a calendar test: each occurrence of the window (a run of
consecutive window hours) is one trade, in for the window and out after it (or,
for a negative effect, out for the window and back after it). Its holdout mean
log return per occurrence, in the sign of the whole-period t, must exceed a round
trip of 30 bps (15 bps a side, Binance taker plus half the spread, the lab's
crypto convention).

## Lead-lag tests (172)

At every hour boundary T (the decision), a predictor known by T and a target
return from T over the next h hours, h in {1, 4}:

- BTC leads alts: x = BTC's log return over the hour before T; y = the alt's
  log return over [T, T+h) minus BTC's (the catch-up). Each of the 19 other
  coins and the alt basket (40).
- US index hours lead crypto: x = the open to close log return of the newest
  SPY (or QQQ) 1h bar known by T and not older than an hour (the next Binance
  hour starts 30 minutes after the bar's nominal end: a purge gap); y = BTC's,
  ETH's or the basket's log return over [T, T+h) (12).
- Funding and open interest lead price, per coin (20): x = the newest settled
  funding rate known by T, the log change of open interest over the hour before
  T, and over the 4 hours before T; y = the coin's log return over [T, T+h) (120).

Statistic: the rank IC with a purge gap of D2 (`data_free_d2.purged_ic`): the
decision hours are split into h + 1 interleaved subsamples so that no two
target windows of a subsample touch, the IC and t are their means, p two-sided.

Cost check of a lead-lag test: the deciles of x from the discovery half; in the
holdout every hour with x in the top decile is a trade in the sign of the
whole-period IC (bottom decile: the opposite sign) over [T, T+h); its mean
log return must exceed a round trip, 30 bps for one coin, 60 bps for the alt
against BTC (two legs).

## Pass rule

A test passes if all three hold:

1. Holm-adjusted p at most 0.05 over all 304 tests of this study together;
2. the same sign of the statistic (Welch t or IC) in both halves;
3. its cost check.

A calendar or lead-lag variable that passes becomes a feature in `lab.features`
(known at the hour it describes, by the same function the study used). A test
that passes 1 and 2 but not 3 is reported as real but too small to trade alone,
and is not added. Nothing else is added: no paper book, no gate, no job.

## Trials

No Sharpe trial (no strategy is selected or backtested); 304 tests counted,
Holm over all of them. The global trial pool is unchanged.
