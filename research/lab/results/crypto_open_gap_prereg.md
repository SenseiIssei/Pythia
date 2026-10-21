# Does the overnight BTC move predict COIN and MSTR after the open gap? (survey O6): pre-registration

Registered 2026-10-21 and committed before any number below was computed.
Drafted from idea O6 of `proposals/2026-10-21-strategy-survey.md`; changes at
the end. Code: `lab.experiments.crypto_open_gap`. Results:
`results/crypto_open_gap.md`. Nothing here may change once a result exists.
Pool shared with `vix_carry` (see there): 1,762 with this batch.

## Question

COIN and MSTR close at 16:00 New York while BTC keeps trading. Their opening
gap prices the overnight BTC move. If the gap under- or over-reacts, does the
rest of the session (open to close) drift to correct it, enough to trade?

## Data

- Yahoo daily: split-adjusted open and close of COIN (from 2021-04-14) and
  MSTR; cached under `<data>/agent-s3/yahoo/`.
- Binance BTCUSDT 1-minute klines (the lake): BTC at the 16:00 New York close
  (the close of the minute ending 16:00) and at the 09:30 open (the open of
  the 09:30 minute), daylight saving handled by the New York time zone.
- Yahoo 1-hour bars for the "an hour late" fill (Yahoo keeps 730 days, so
  from about 2024-10).

## Variables (session t, everything up to the open of t)

- x_t = BTC(09:30, t) / BTC(16:00, t-1) - 1, the overnight BTC move (weekends
  and holidays included);
- g_t = open_t / close_{t-1} - 1, the stock's gap;
- beta_t = OLS slope of the stock's close-to-close return on BTC's
  16:00-to-16:00 return over the 120 sessions through t-1;
- u_t = g_t - beta_t x_t, the gap's surprise against BTC (negative: the gap
  under-reacted to a BTC rise);
- s_t = close_t / open_t - 1, the session return.

## Tests

Per stock: OLS s_t = a + b u_t with heteroskedasticity-robust (HC1) standard
errors. In sample: MSTR 2021-03-01 (120 sessions after its first purchase in
August 2020) to 2022-12-31, COIN 2021-10-01 (120 sessions after listing) to
2022-12-31. Out of sample 2023-01-01 to the data end. The sign of b is fixed
in sample; the out-of-sample t must exceed 2 in that sign.

## Rule (one per stock)

At the open of t, predicted session move m_t = b_IS u_t (the in-sample slope,
intercept left out). If |m_t| exceeds the round trip (10 bps), go long (m > 0)
or short (m < 0) at the open and close the position at the close; flat
otherwise. Costs 5 bps a side, stress 10; shorts pay 3 % a year borrow per day
held (1/252 each). Two fills:

- **at the open** (Yahoo's official open). Optimistic: u_t needs the opening
  print itself. Reported over the whole out-of-sample window.
- **an hour late** (judged): the same decision, entered at the open of the
  10:30 hourly bar, out at the close. Only where Yahoo's hourly bars exist.

## Trials

2 Sharpe trials (the rule on COIN and on MSTR) and 2 slope tests.

## Pass rule (per stock)

1. out-of-sample slope t above 2 in the in-sample sign;
2. the rule's out-of-sample Sharpe (x sqrt 252) above 0 at 5 bps entered an
   hour late;
3. still above 0 at 10 bps an hour late.

Deflated p over the pool is reported; a pass on 1 to 3 without deflation is
written up as an experiment candidate, with the note that the engine cannot
run it (below).

## Kill rule

Out-of-sample slope t below 1 in the in-sample sign.

## What the engine could do with it

Nothing as it stands: lab signals are daily weights traded in the regular
session, not an open-to-close day trade with an exit at the close. A pass
would need an intraday lab book in the engine (the same gap `intraday_equities`
noted); no book is proposed by this study either way.

## What could fool us

- The opening print is noisy and sometimes stale (`overnight` drops
  symbol-years with too many stale opens); the hour-late fill avoids it.
- MSTR's link to BTC grew over the window (leverage, issuance), so beta is
  rolling.
- Only two stocks, about 900 out-of-sample sessions each.

## Changes to the survey's sketch

- The survey's Alpaca 5-minute bars from 2016 are not reachable from the PC;
  daily opens and closes test the slope, Yahoo's hourly bars the late fill.
- In sample starts 2021 (MSTR became a BTC proxy in August 2020, COIN listed
  in April 2021) rather than 2016.
- The miners and the spot ETFs are left out (the owner asked for COIN and
  MSTR).
