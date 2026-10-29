# EQ2: single-stock day trading at 50 EUR, new signals under the real rules. Pre-registration

Registered 2026-10-29 and committed before any number below was computed (while scoping, one look at which symbols
and months the lab's bar cache holds and at the news tags' dates and topics, no return). Brief EQ2 of the training
plan of 2026-10-28, on the review of 2026-10-27 (`results/review_2026-10-27.md`, sections 2 and 3), R5's registry
(`metrics.trial_pool`, `<data>/trials/registry.jsonl`) and R6's windows (`results/factory_lockbox_r6.md`). It does not
repeat W4 (`results/intraday_equities.md`: 46 intraday trials on 5 minute bars, ORB, gap, VWAP reversion, end of day
momentum on 1/N books, nothing passes, deflated p 0.00). Code: `lab.experiments.daytrade_eq2` (written after this
file). Results: `results/daytrade_eq2.md` and `.json`. Nothing here may change once a result exists. Paper only:
nothing a live bot, a wallet or the engine reads changes.

## Question

Can a 50 EUR Alpaca account that day trades one large cap at a time (fractional shares, flat every night) earn
anything after the costs and the rules such an account really has, with signals the lab has not tried: a stock in
play picked by unusual relative volume at the open, or a learned intraday pattern classifier? Against doing nothing
and against holding SPY.

## Data and universe

- Alpaca historical 5 minute bars, SIP feed, adjustment all, the regular session 09:30 to 16:00 New York, as W4
  cached them (`<data>/intraday/alpaca-sip/<SYM>/<YYYY-MM>.parquet`, read only, no download). The calendar, the
  filled bars and the daily features are W4's (`intraday_equities.frame_to_blocks`, `assemble`, `features`): a market
  day is a full SPY session (half days left out), a symbol counts on a day with at least 39 bars.
- **Universe: W4's 41 large caps** (AAPL MSFT NVDA AMZN GOOGL META TSLA AVGO AMD NFLX JPM BAC XOM UNH LLY V MA COST
  WMT ORCL CRM ADBE INTC CSCO QCOM PEP KO PG JNJ HD MRK ABBV CVX WFC C DIS PYPL BA PLTR MU), each on every day it has
  a valid session and 20 valid days before it. The list is chosen today, so it leans on survivors (said in every
  table). SPY is the benchmark and the classifier's market input, never traded by a signal book.
- **News tags: not testable, no trial.** `<data>/ai/news_tags` holds four days (from 2026-10-26) of crypto RSS
  headlines; `<data>/ai/news` starts 2025-12-29 with crypto sources only. Nothing tags a single large cap in the in
  sample or the validation window. The family is dropped here and says so in the results.

## Windows (R6)

In sample 2016-01-01 to 2023-12-31, validation 2024-01-01 to 2026-06-30. Every bar after 2026-06-30 is dropped at
load before anything is computed: the lockbox is never read. Each window starts a fresh wallet on its first session.
PBO and the classifier's in-sample numbers start 2018-01-01 (the classifier's first walk-forward test quarter).

## The account and its rules (as Alpaca executes them)

- **Orders.** Fractional market orders, regular hours, day orders, notional from 1 USD; long only (Alpaca does not
  short fractional shares, and a cash account cannot short). Zero commission. On every sell the SEC fee (27.80 USD
  per million) and the FINRA TAF (0.000166 USD a share), as W4.
- **Timing: one bar late.** A rule decides at the close of 5 minute bar k from bars up to k. Its market order fills
  at the open of bar k + 2 (the engine polls every 300 s off the bar clock, so the next open is optimistic); the next
  bar's open (k + 1) is reported beside it, not judged. Every position is closed at the open of the 15:55 bar (a
  forced exit is never late). An entry whose fill would be at 15:55 or later is not made; a stop exit whose fill
  would be is the forced exit.
- **Spread and slippage (no quotes in the bars, a conservative model):** per side the larger of 5 bps and one cent
  over the price, doubled for fills at the opens of the first three bars (09:30 to 09:40, when spreads are widest).
  Stress: all of it doubled (fees not doubled).
- **One position at a time.** The book holds at most one stock and makes at most one round trip a session, with
  its whole buying power.
- **EUR to USD.** The account is in USD. 50 EUR is converted on the first session at the ECB's reference rate of
  that day or before (`results/etf_books_eq1_eurusd.csv`) less 0.5 %, and back at the window's end less 0.5 % (a
  conservative retail conversion). Bank wire fees are not in the gates (a 15 EUR wire would be 30 % of the account;
  reported as information). Taxes are left out.
- **Two account types, the book pre-registered on the cash account.**
  - `cash`: no pattern day trader rule. A buy may use settled cash only; a sale's proceeds settle T+1 (the next
    session) and are usable from it. **This is the judged book.**
  - `margin`: an Alpaca margin account under 25,000 USD, the pattern day trader rule: at most 3 day trades in any 5
    sessions. A signal is not taken when the sessions before it in the last 5 already hold 3 day trades (each round
    trip here is a day trade). Unsettled cash may be used. Reported and counted, not judged.

## The signal families (two)

### F1 `rvol_orb`: opening range breakout on unusual relative volume (8 trials)

- The opening range is the first m minutes (m 5: bar 0; m 15: bars 0 to 2). Its relative volume (RVOL) is its volume
  over the mean volume of the same bars in the symbol's previous 14 valid sessions (all 14 needed).
- At the close of the range's last bar, a stock is in play when its RVOL is at least r and the range closed up
  (its last close above bar 0's open). The book picks the one with the highest RVOL; none in play, no trade.
- Entry: the first bar close after the range above the range's high, decided at the latest at the 15:30 close
  (bar 71). Stop: a bar close below the range's low exits. Else flat at 15:55.
- Grid: m in {5, 15} x r in {1.5, 3.0}: 4 rules x 2 account types = 8 trials.

### F2 `pattern_clf`: a learned intraday pattern classifier (8 trials)

- Decision at the close of bar k: 10:00 (k 5) or 12:00 (k 29). Per stock and session, from bars up to k and the
  daily features W4 makes (all known at that bar): the return from the open to the close of bar k, the last 15
  minutes' return, the gap, the previous day's return, the range so far, the close's place in it, the distance to
  the session VWAP (all over the stock's 20-day daily vol), the log relative volume so far against the same bars of
  the previous 14 sessions, the same open-to-k return and gap of SPY, and the stock's open-to-k return minus SPY's.
- Label: 1 when the stock's return from the open of bar k + 2 to the 15:55 open beats the round trip cost model.
- Model: `logit` (L2 logistic regression, C 1.0 on standardised features, numpy and scipy) or `gbm` (LightGBM, the
  lab image's, 100 trees, 15 leaves, learning rate 0.05, min 200 rows a leaf, seed 7, one thread).
- Walk-forward, purged (`cv.walk_forward`): quarterly test folds from 2018Q1 to 2026Q2, each model trained on every
  row whose label ended before the fold starts, with a one day embargo (expanding window). No row from after
  2026-06-30 exists.
- Trade: each session the stock with the highest predicted probability, if it is at least 0.55; buy at bar k + 2,
  flat at 15:55, no stop.
- Grid: model in {logit, gbm} x k in {10:00, 12:00}: 4 rules x 2 account types = 8 trials.
- **Leak harness (T1, `lab.leak.check`)** on the classifier's whole path (features, walk-forward training,
  predictions) with the bars flattened to one time axis of (session, bar), so that a value from a later bar of the
  same session counts as the future; run on a slice of the real bars in the study and on synthetic bars in the
  tests. A leak fails every F2 trial.

## Benchmarks

- **Doing nothing:** the 50 EUR converted and back, nothing else (the conversion costs only).
- **Holding SPY:** the same account buys SPY with all of it at the first session's close (one side of the cost
  model), held to the window's end on Alpaca's adjusted closes (dividends in), the same two conversions.

## Measures

Per rule and account type, in sample and validation, one bar late and at the next bar: the USD equity per session,
the daily return on calendar days (0 on days without a session, times sqrt(365) for a Sharpe, the registry's
convention), CAGR, max drawdown, trades, days skipped by the PDT rule, the share of winning trades, mean return a
trade, the end value in EUR after the conversions; the daily excess over holding SPY; the same with costs doubled.

## Trials (16)

Each a line of R5's registry (family `small`, source this file) with the in-sample Sharpe (2016 to 2023 for F1,
2018 to 2023 for F2, one bar late) of its daily return, registered before any validation number:
`small:eq2:<rvol_orb_m5_r1.5|rvol_orb_m5_r3|rvol_orb_m15_r1.5|rvol_orb_m15_r3|pattern_clf_logit_1000|pattern_clf_logit_1200|pattern_clf_gbm_1000|pattern_clf_gbm_1200>:<cash|margin>`.
The registry on the server is read only in the agent's run: the run registers into a copy and writes the rows into
`results/daytrade_eq2.json`; `--register` appends them to the server's registry (by id, once).

## Pass rule (per rule on the cash account, validation, one bar late; all must hold)

1. Beats doing nothing: end value in EUR above 50 EUR's doing-nothing end value, and DSR (higher is better) of its
   daily return at least 0.95 over R5's pool of all and over the small family, each with these trials.
2. Beats holding SPY: CAGR above SPY held's over the same window and account.
3. Costs doubled: still a positive total return.
4. At least 100 trades in the validation window.
5. PBO (`metrics.cscv`, 16 blocks) of the eight cash-account rules' daily returns from 2018-01-01 to 2026-06-30
   below 0.2 (the ladder's bar).
6. F2 only: the leak harness clean.

A rule that passes gets a 50 EUR paper book on the ladder (cash account, one bar late) and R6's one lockbox look in
its own commit; neither is made in the study commit. If none passes, the results say so plainly and no book is made.
