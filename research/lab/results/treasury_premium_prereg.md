# BTC treasury-company premium reversion (survey O2): pre-registration

Registered 2026-10-21 and committed before any number below was computed.
Drafted from idea O2 of `proposals/2026-10-21-strategy-survey.md`; changes at
the end. Code: `lab.experiments.treasury_premium`. Results:
`results/treasury_premium.md`. Nothing here may change once a result exists.
Pool shared with `vix_carry` (see there): 1,762 with this batch.

## Question

MSTR trades at a multiple of the BTC it holds (mNAV). Does that multiple
mean-revert in a way that pays: hold MSTR instead of BTC when it is cheap,
short it against BTC when it is dear?

## Feasibility, decided before any return is computed

- **Holdings.** Every 8-K MSTR filed from 2020-08-01 (SEC EDGAR, the
  submissions index and each filing's primary document and exhibits, the
  module's polite client, the User-Agent from `PYTHIA_SEC_UA`, the module's
  default when that is unset), parsed for the aggregate BTC held ("held an
  aggregate of approximately N bitcoin" and its variants). A holding is known
  from its filing date. Quarterly 10-Q and 10-K figures fill the gaps the same
  way.
- **Shares.** `dei:EntityCommonStockSharesOutstanding` from XBRL company facts
  (class A plus class B, as of each filing's cover date, known from its filing
  date). MSTR sold shares through at-the-market programmes between filings
  from 2021 on, so the last cover count understates shares there; when an 8-K
  reports ATM shares sold, they are added from its filing date. If fewer than
  80 % of the out-of-sample weeks have a holdings figure no older than 14
  days, the study stops at feasibility and says why.
- **Peers.** Other US-listed holders (miners, the newer treasury companies)
  either mine (holdings move daily) or have under two years of filings; they
  are listed with their first holdings filing and left out of the test.

## Variables

- Market cap_t = unadjusted close_t x shares known at t (Yahoo, splits undone
  for the 10:1 split of 2024-08-08).
- NAV_t = BTC held (known at t) x BTC at 16:00 New York (Binance 1-minute).
- mNAV_t = market cap / NAV (equity over coins; debt and preferred left out,
  which the report notes).
- z_t = (log mNAV_t - its 252-session mean) / its 252-session standard
  deviation, both through t.

## Rules (decided at the close of t, traded at the close of t+1)

- **L (long-only switch):** hold MSTR instead of BTC while z < -1, BTC
  otherwise, both at full weight. Costs 35 bps per unit of BTC traded (Alpaca
  crypto), 5 bps per unit of MSTR.
- **LS (long/short):** while z > +1, short MSTR and hold BTC at equal dollar
  amounts (each half the capital), flat otherwise. Costs as above plus 3 % a
  year borrow on the short.

Daily returns on US sessions (BTC from one 16:00 New York to the next, so a
weekend lands on Monday). In sample to 2023-12-31 (from the first day z
exists), out of sample 2024-01-01 to the data end.

## Trials (2)

L and LS.

## Pass rule

- LS: out-of-sample Sharpe (x sqrt 252) above 0.5, positive in at least 2 of
  2024, 2025, 2026, still above 0 traded a day later.
- L: out-of-sample Sharpe above BTC's (held on the same sessions), drawdown
  not more than 5 points above BTC's.

Deflated p over the pool reported; confirmed only above 0.95.

## Kill rule

LS out-of-sample Sharpe at or below 0.

## If it passes, or passes all but deflation

L would be a lab book of two asset classes (MSTR in the US session, BTC
around the clock), which no lab signal carries today (a signal is either
coins or US equities); it would run as two experimental signals switched
together, and the write-up says what the engine would need. LS needs a stock
short and a crypto long in one book: the same. Jobs only if a book is built.

## What could fool us

- Dilution and conversions move mNAV mechanically; the filing date is the
  information date, and share counts lag between filings.
- One company. Its multiple's history is a handful of long swings, so even a
  year rule is weak evidence.

## Changes to the survey's sketch

- MSTR only; the peers are listed, not tested.
- Equity mNAV (market cap over coins), not enterprise value.
