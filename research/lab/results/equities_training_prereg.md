# X16 equities training: pre-registration

Written and committed on 2026-10-20 before any number below was computed.
What was known when this was written: M9 (`equities_ranking.md`: weekly
LambdaRank on the point-in-time S&P 500 does not beat the index; 12-1
momentum top 50 Sharpe 0.72, low vol 0.76 to 0.83, "52-week high, closest"
weekly loses), `etf_trend.md` (weekly ETF trend loses to SPY and 60/40),
`intraday_equities.md` and `overnight.md` (no day or night book), the crypto
exit and overlay studies (`flow_overlays.md`, `m8_trim.md`,
`breakout_study.md`: no overlay has improved the long-only books so far), and
coverage of the data only, no outcome:

- the point-in-time S&P 500 dataset M9 reads (github.com/Johnbrick123/sp500-data,
  release "data", 2026-10-16): opens, highs, lows and volume are missing on
  the CRSP rows, about 44 % of member rows in 1996, 23 % in 2005, 9 % in
  2010 and under 4 % from 2013 (none from 2025); the 11 SPDR sector ETFs and
  SPY are complete (XLRE from 2015-10, XLC from 2018-06);
- SEC EDGAR: `company_tickers.json` plus the dataset's `renames.csv` give a
  CIK for 55 % of the index members on 2005-01-02, 67 % in 2010, 79 % in
  2016, 91 % in 2020 and 100 % today (the names missing are the ones that
  left: acquired, renamed without a record, or dead). 8-K item codes are in
  the submissions JSON from the 1990s; item 2.02 (results of operations)
  exists from 2004-08-23, item 12 before it.

Nothing in this file is changed after the first result exists; anything
added later goes into `equities_training.md` and says so.

## The questions

1. **Early detection** (part A): do daily, long-only rules that buy early in
   a move (breakouts on volume, gap and go, post-earnings drift, 52-week-high
   momentum, sector ETF rotation) beat SPY out of sample, with next-open fills
   and realistic costs?
2. **Exit timing** (part B): for each strategy's trades, how much of the best
   achievable move does the current exit capture, and does any exit rule
   (time stop, ATR trailing, volatility-scaled target, a model of the
   expected remaining return) beat the current exit, for the equity picks of
   part A (B1) and for the live crypto books (B2)?
3. **More training** (part C and the models): an event model on the equity
   candidates (M13) and two remaining-return models (M14 crypto, M15
   equities), purged walk-forward, a gate each like the zoo's, feature
   importance stability, and a daily retrain for whatever passes.

## The pool

Sharpe trials before this study: 948 hand trials (930 before X11 plus its 18,
as published in `model_upgrades.md`) at the variance backed out of the
published bar, and every genome in the factory ledger at run time. Studies
registered in parallel and not yet merged add their own count when they are.
This study adds **120** Sharpe trials: part A 57, B1 30, B2 27, C 6. Deflation
as in X6, X9 and X11: the pooled variance of per-observation Sharpes, each
group at its own variance. Equity trials enter the pool as per-trading-day
Sharpes (annual over the square root of 252), crypto trials per calendar day
(over the square root of 365), as each series is observed.

The three model gates (M13, M14, M15) are not Sharpe trials; they are
corrected among themselves with Holm at 0.05.

## Data, fills and costs (every equity part)

- **Universe.** S&P 500 members on the signal day (point in time, dead names
  included with their final prices), with 252 days of history. Prices from
  1996-01-01: the split and dividend adjusted close; the open, high and low
  adjusted by the same day's factor (adjusted close over close); volume as
  reported, dollar volume = close x volume. The 11 SPDR sector ETFs (XLB,
  XLC, XLE, XLF, XLI, XLK, XLP, XLRE, XLU, XLV, XLY) and SPY from the same
  dataset; Yahoo's chart API (`overnight.download_yahoo`) only for an ETF the
  dataset lacks.
- **Fills.** Decided at the close of day t, filled at the open of t+1. Where
  a name's open is unknown that day (CRSP rows), the fill is that day's
  close; the share of such fills is reported. Positions earn open-to-open
  returns; a name whose series ends is closed at its last price.
- **Costs.** Stocks 5 bps a side (half spread and impact at the open; Alpaca
  charges no commission), ETFs 2 bps, plus the SEC fee on sells (27.8 per
  million). "Doubled": 10 and 4 bps.
- **Windows.** Selection (every pick in this study) 2000-01-01 to 2015-12-31,
  for PEAD 2005-01-01 to 2015-12-31. Out of sample from 2016-01-01 to the
  data's last day. Nothing out of sample is looked at before every pick is
  fixed by the code.
- **Benchmarks.** SPY bought and held; the equal-weight point-in-time index,
  rebalanced monthly at 5 bps; for the sector book the equal weight of the
  sector ETFs that exist, monthly at 2 bps; for PEAD also the equal weight of
  the members that have a CIK (the same survivorship as its events).
- **Regime filter** (where a variant has it): SPY's close above its 200-day
  average at the decision close. Off means no new entries (event books;
  positions run to their exit) or cash (rebalanced books).

## Part A: early detection (57 trials)

Event books hold up to **K = 20 slots of 5 %**. A signal is a buy for the
next open; when there are more signals than free slots the strongest go
first (the ranking named below); a name already held is not bought again and
its exit clock is not reset; free slots and an entry's shortfall (cash below
5 %) stay in cash. The base exit is a time stop: sold at the open after H
trading days held.

| | Family | Signal at the close of t | Ranking | Grid | Trials |
|---|---|---|---|---|---|
| A1 | Breakout on volume | close above the highest close of the N days before t; dollar volume of t at least k times its mean over the 50 days before t | volume ratio | N 20, 55 x k 1.5, 2.5 x H 10, 40 x regime off, on | 16 |
| A2 | Gap and go | open of t at least (1 + g) x the close of t-1; close at or above the open; dollar volume at least 2 x its 50-day mean | gap | g 2 %, 4 % x H 5, 20 x regime off, on | 8 |
| A3 | PEAD | an earnings event E (below); reaction window = the first trading day on or after E's filing date and the next one; AR = the name's return over the window minus SPY's; z = AR / (63-day daily vol before the window x sqrt 2); AV = mean dollar volume over the window / its mean over the 50 days before; long when z >= z_min (and AV >= 2 with the volume filter); decided at the window's last close | z | z_min 1, 2 x volume filter off, on x H 20, 60 | 8 |
| A4 | 52-week-high momentum | monthly (last trading day of the month): the K names with the highest close / highest close of the past 252 days (ties by 12-month return), equal weight | ratio | K 20, 50 x regime off, on | 4 |
| A5 | Sector rotation | monthly: the M sector ETFs with the strongest relative strength (total return over L days; "blend" = the mean of the 63, 126 and 252-day ranks), equal weight; an ETF needs L days of history | strength | L 63, 126, 252, blend x M 2, 3 x regime off, on | 16 |

**Earnings events (A3).** From EDGAR's submissions JSON (data.sec.gov, a
descriptive User-Agent with a contact address, at most 5 requests a second,
cached): every 8-K with item 2.02 (item 12 before 2004-08-23) is an event on
its filing date. A 10-Q or 10-K with no such 8-K in the 60 days before it is
an event on its own filing date. Ticker to CIK: SEC's `company_tickers.json`,
the dataset's renames; members without a CIK have no events (coverage per
year is reported).

**Per family pick:** the variant with the best selection-window Sharpe at
5 bps (2 bps for A5). Each pick also runs **filled a day late** (the open of
t+2): 5 trials.

**Gates**, all out of sample at base costs; a pick passes only if all hold:

1. Sharpe above SPY's and above the equal-weight benchmark's (A5: the
   equal-weight sectors; A3: also the CIK equal weight);
2. out-of-sample Sharpe at least half the selection window's, which is above 0;
3. alpha against SPY (daily OLS intercept, annualised) above 0 at doubled costs;
4. filled a day late, alpha above 0;
5. stationary block bootstrap (20-day blocks, 4,000 draws): the pick's Sharpe
   above SPY's in at least 90 % of draws;
6. alpha positive in more than half the calendar years;
7. deflated p above 0.95 over the whole pool.

Also reported, not gates: the deflated p over this study's own trials,
turnover, the share of fills at the close, A3's coverage, and for A1 and A2
the share of member-days without volume (those names cannot signal, and they
are mostly names that later left the index, a survivorship lean).

## Part B: exit timing

**Capture (every book, no trials).** Per trade (a holding spell from its
entry fill to its exit fill): realised return; the best achievable inside the
trade (MFE, the highest close over the entry price); capture = realised / MFE
where MFE > 0; give-back = MFE minus realised; left on the table = the
highest close in the 20 trading days after the exit over the exit price.
Medians and quartiles per book, for the part A picks and for the crypto
books below.

**Exit rules** (decided on closes; equities sold at the next open, crypto at
the book's own close, as the books trade):

- *time* stop at H/2 or 2H trading days (equities), 20 or 40 days (crypto);
- *ATR* trailing: out when the close is below the highest close since entry
  minus k x ATR(14), k = 2 or 3 (ATR from high, low and the previous close;
  |close change| where high or low is unknown); equities keep a cap of 4H days;
- *target*: out when the close reaches the entry price x (1 + m x daily vol x
  sqrt(H)), with the 63-day vol at entry and m = 1 or 2 (equities, the time
  stop H stays as the fallback); crypto with the 30-day vol, sqrt(20) and
  m = 2 or 3;
- *model*: out when the remaining-return model (M15 equities, M14 crypto)
  predicts a 10-day log return below minus a round trip of costs (10 bps
  equities, 70 bps crypto); equities keep the 4H cap.

**B1, the equity picks (30 trials).** A1, A2 and A3's picks: time H/2, time
2H, ATR 2, ATR 3, target 1, target 2, model = 7 each, 21; A4 and A5's picks
(rebalanced books): ATR 2 and 3 between rebalances (a stopped name sits in
cash until the next rebalance picks it), 4. Per family the exit with the best
selection-window Sharpe is its exit pick; each exit pick is also run a day
late: 5. Gates, out of sample, against the same pick with its base exit:
(1) Sharpe higher and higher in more than half the calendar years, (2)
drawdown not higher, (3) the 5 % bootstrap quantile of the Sharpe difference
above 0, (4) a day late still higher, (5) still higher at doubled costs, (6)
the improvement's deflated p above 0.95 over B1's 30 trials. An exit that
passes makes its family pick (with that exit) face part A's seven gates
again; it becomes a paper book only through them.

**B2, the crypto books (27 trials).** `breakout_top10`, `tsmom_top20` and
`tsmom_tranches` as the autopilot runs them on Alpaca (the 15 Alpaca coins,
the rest in cash), 35 bps per unit of turnover, from X6 (`fo.run_books`). A
spell is a run of days the book holds a coin. An exit cuts the coin from the
day it fires to the end of that spell (it comes back only when the book's own
rule enters it again); the freed weight stays in cash. Implementation: the
book's post-trade weights after each close with the cut coins at 0, run
through the same daily simulator; the reference is the same machinery
without cuts. Per book: time 20, time 40, ATR 2, ATR 3, target 2, target 3,
model = 7, 21; the in-sample pick per book (best 35 bps Sharpe 2020-08-01 to
2023-12-31) also a day late and on the twin (the original books, every coin):
6. Gates: X6's six (Sharpe at 35 bps above the book's and better in 2 of
2024, 2025, 2026; drawdown below the book's; the bootstrap band of the
difference above 0; a day late above the book; the twin at least the twin
book's; the improvement's deflated p above 0.95 over B2's 27 trials). The
deflated p over the pool is reported. If a pick passes it becomes an exit
overlay setting for the paper books, **off by default**.

## Part C and the models

**M13, equity event model.** Rows: every candidate of the loosest variant of
A1 (N 20, k 1.5), A2 (g 2 %) and A3 (z 1, no volume filter), no regime
filter, at the decision close. Features: family, the family's strength, the
volume ratio, the gap, z and AV (missing outside A3), 1/3/6/12-month
momentum, 21 and 63-day vol, distance to the 52-week high, log 63-day dollar
volume, SPY's 21-day return, 21-day vol and its 200-day state. Target: the
log return from the fill open to the open 20 trading days later minus SPY's,
over (63-day daily vol x sqrt 20), clipped at +-5. LightGBM regression (fixed
parameters), baseline the training mean per family, loss squared error.

**M15, equity remaining return.** Rows: every day a name is held by the A1,
A2 or A3 pick with its base exit. Features: days held, log return since the
entry fill, log distance below the highest close since entry and that over
the 21-day vol, 5/21/63-day momentum, 21-day vol, distance to the 52-week
high, SPY's 21-day return and 200-day state, family. Target: the log return
from the next open to the open 10 trading days later over (21-day daily vol x
sqrt 10), clipped at +-5. Same model, baseline and loss.

**M14, crypto remaining return.** Rows: every coin-day held after the close
by the original `breakout_top10` or `tsmom_top20` (every coin), from
2020-08-01. Features: days held (the longer spell), log return since entry,
log distance below the spell's highest close and that in ATR(14) units, 7 and
28-day momentum, 30-day vol, 7 over 30-day vol, log distance to the 50-day
average, 7 over 28-day quote volume, BTC's 28-day return and 200-day state.
Target: the next 10 days' log return over (30-day vol x sqrt 10), clipped at
+-5. Same model, baseline and loss.

**Walk-forward.** The zoo's own (`core.evaluate`): quarterly folds, purged,
with an embargo of the label horizon in calendar days (M13 30, M15 16, M14
11); first test quarter 2000-Q1 for M13 and M15 (training from 1997),
2021-Q1 for M14. **Gate**: lower squared error than the baseline with a
Diebold-Mariano p (lag the horizon) that passes Holm at 0.05 over the three.
Reported: rank IC of forecast and target, the gain per fold, and **feature
importance stability**, the Spearman correlation of each fit's gain ranks
with the previous fit's (mean and minimum; below 0.5 on average the card
says "unstable").

**C, M13 used (6 trials).** On A1, A2 and A3's picks: the candidates ranked
by M13's out-of-fold forecast instead of the family's strength, and a
candidate skipped when the forecast is below 0: 3; each a day late: 3. Gates
B1's six against the pick without M13, deflation over C's 6.

**A model that passes its gate** becomes a zoo module with a daily retrain
(`every_days` 1, the `models` job) and a daily shadow; one that fails is
listed in the zoo as a record with its gate, like M7, and nothing reads it.
M2 retrains weekly in the learning loop already; nothing changes there.

## What passing changes

- A part A pick that passes (alone, with an exit that passed B1, or with M13
  that passed C) becomes a paper book with an engine signal of asset class
  `us_equity`, autopilot-only (the engine rebalances it in the regular
  session), a job in `research/ops/jobs.yaml`, and its evidence from this
  study.
- A B2 pick that passes becomes an exit overlay setting for the crypto paper
  books, off by default.
- Nothing else changes live behaviour. Prior: every overlay and every equity
  book tried so far has failed, and the pool's noise bar is near an annual
  Sharpe of 2.7.
