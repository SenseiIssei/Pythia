# Six equity candidates from the strategy survey: pre-registration

Registered 2026-10-21 and committed before any number below was computed.
Source: `proposals/2026-10-21-strategy-survey.md`, candidates 3 (earnings
announcement premium), 4 (S&P 500 discretionary deletions), 6 (same-month
seasonality), 7 (gross profitability plus net share issuance), 8 (turn of the
month and pre-holiday) and 10 (opportunistic insider purchases). The survey's
sketches are drafts; this file fixes every number, and the corrections are
listed at the end. Code: `lab.experiments.survey_equities` and
`lab.equities.xbrl` (written after this file).
Results go to `results/<study>.md` per study. Nothing here may change once a
result exists; anything added later goes into the results file and says so.

What was known when this was written (coverage only, no outcome): the
point-in-time S&P 500 panel (`lab.equities.panel`, 1,305 names, 1996-01-02 to
2026-10-16, dead names with their final prices, no delisting returns); SEC
EDGAR earnings events (`equities/edgar/events.parquet`, 628 tickers with a
CIK: 55 % of the members in 2005, 79 % in 2016, 100 % today; about 2,500
8-K item 2.02 events a year from 2010); 758 membership ends inside the panel,
of which 189 (1996 to 2012) and 163 (2013 on) still trade five sessions later
outside the index; 470 and 290 additions over the same windows; Yahoo's daily
chart API answers (SPY from 1993); `data.sec.gov` answers the XBRL company
facts without a contact in the User-Agent, `www.sec.gov` (where the Form 345
data sets live) refuses such requests with 403.

## Common rules

- **Universe.** S&P 500 members on the decision day (point in time), with 252
  sessions of history (`books.base_ok`). Studies that need a CIK also require
  one, and are judged against the equal weight of the members that have one
  (the same survivorship: members that left the index before SEC's ticker
  list existed have no CIK).
- **Fills.** Decided at the close of day t, filled at the open of t+1 (the
  panel's `fill`: that day's close where the open is unknown), positions earn
  open to open (`Panel.r_oo`). "A day late" fills at the open of t+2. The
  turn-of-month study (5) trades ETFs at the close (Alpaca market-on-close
  orders) and earns close to close.
- **Costs.** Alpaca charges no commission. Stocks 5 bps a side for spread and
  impact (10 bps for names just deleted from the index, which are mid caps),
  ETFs 2 bps; on every sale the SEC fee (27.80 USD per million) and FINRA's
  TAF (0.000166 USD per share, at the adjusted close as the share price, which
  overstates it in early years). Shorts (long/short books only) pay a borrow
  fee of 0.30 % a year on the short gross. "Doubled": the per-side bps twice.
- **Benchmarks.** SPY bought and held (open to open on the stock calendar, so
  both series cover the same days); the equal-weight point-in-time index
  (members with 252 sessions of history, rebalanced at month ends, 5 bps).
- **Windows.** Each study names its selection window; out of sample runs to
  the data's last day. Every pick is fixed by code from the selection window
  before an out-of-sample number is printed.
- **Bootstrap.** Stationary bootstrap, mean block 20 sessions, 4,000 draws,
  seed 20261021, 5 % and 95 % quantiles; event studies resample events.
- **Deflation.** Per-trading-day Sharpes. The pool: 1,140 hand trials (after
  Polymarket's 16, `results/polymarket.md`) at the variance backed out of the
  published bar (377 trials at 2.43, as every hand study since C16), the
  factory ledger (600 genomes on the PC) at its own variance, and the 33
  trials registered here at their own variance: **1,773** trials (the 6
  insider trials join only if that study runs: 1,779). Studies registered in
  parallel add their own count when they are merged. A study's confirmation
  needs a deflated p above 0.95 over the whole pool.
- **What passing changes.** A pick that passes every gate of its study
  becomes a lab paper book with an engine signal of asset class `us_equity`
  (autopilot-only, the engine rebalances it in the regular session), a job in
  `research/ops/jobs.yaml` added disabled, and its evidence from the study. A
  pick that passes every gate except deflation becomes the same book marked
  **experimental** (`lab.paper.experimental`). Nothing else changes; nothing
  is deployed.

## 1. Earnings announcement premium (`earnings_premium`, 6 trials)

**Question.** Do members bought a few sessions before their expected earnings
date and sold just after it beat the equal-weight index, after costs, when
the date is predicted from the company's own filing cadence?

**Events.** Only 8-K filings with item 2.02 (item 12 before 2004-08-23) from
`events.parquet`; the 10-Q/10-K-only events are not used (their filing date
lags the press release). **Expected date E**: for every 8-K event filed on
calendar day d, the candidate E is the first session on or after d + 364
days. At the close of day t a name has an expected date E when a candidate
lies in the next sessions the rule needs and no 8-K event of the name was
filed in the 45 calendar days before E's calendar date up to t (an
announcement that already came early consumes the expectation). Candidates
less than 30 days apart are one (the earliest). Only events filed up to t
are used.

**Holding.** A name is bought at the open of session E - e and sold at the
open of session E + x: it earns the open-to-open returns in between, which
include the announcement reaction (before the open of E or after the close of
E, the 8-K filing day). e in {5, 2}, x in {1, 3}: 4 trials. **Volume filter**
(Frazzini and Lamont): a name qualifies only if its mean abnormal dollar
volume over its last 4 announcements (mean dollar volume of the event's first
two sessions over the mean of the 50 sessions before) is at or above the
median of that score among members that day; on the selection pick's e with
x in {1, 3}: 2 trials. Total 6.

**Books.** *Tilt book T*: each name in its window gets 1/20 of the book (when
more than 20 are in the window, all get 1/n), the rest is held in the
equal-weight index of CIK members (so a day with no window names is the
index). *Long-only book L*: the same, with the rest in SPY. Both daily, next
open fills, costs on every weight change.

**Measures.** Active return = T minus the CIK equal-weight index (both net).
Information ratio (IR) = its annual Sharpe (x sqrt 252). Alpha = annualised
OLS intercept of T on the index. Selection 2005-01-01 to 2015-12-31, out of
sample from 2016-01-01. **Pick**: the trial with the best selection-window IR
at 5 bps. Trial Sharpe for deflation: the active series' daily Sharpe.

**Pass rule (the pick, out of sample).**
1. Alpha against the CIK equal weight above 0, and the bootstrap 5 % bound of
   the IR above 0.
2. IR above 0.3.
3. IR above 0 with the entry a day late.
4. IR above 0 with costs doubled.
5. Book L's Sharpe above SPY's over the same sessions.
Confirmed only with deflated p above 0.95 over the pool. **Kill**: IR below
0.1 out of sample. Also reported: the share of events whose actual 8-K came
within two sessions of E (how good the prediction is), names in the window
per day, turnover, IR per year, IR against the all-member equal weight.

## 2. S&P 500 discretionary deletions (`index_deletions`, 5 trials)

**Question.** Do names removed from the S&P 500 while they keep trading beat
the equal-weight index over the following 3, 6 or 12 months, and does
deletions minus additions pay?

**Events.** A deletion is the end of a membership interval (day R, the first
session the name is no longer a member). It is *discretionary* when the name
still has a price row on session R + 5 and is not a member again in R to R + 5
(a takeover target stops trading at or before its removal). Known at the
close of R + 5, so the position is bought at the open of R + 6. An addition is
the start of a membership interval (day A) with a price row on A + 5; bought
(shorted, in the long/short book) at the open of A + 6. Events from 1996-03
(20 sessions of panel first).

**Holding.** H sessions after the entry fill, H in {63, 126, 252} (3, 6, 12
months), sold at the open after H sessions or when the series ends. **Delisting
haircut**: a held name whose series ends before the data's last day at a last
close under 5 USD (split-adjusted, dividends not) loses another 30 % on its
last day (performance delistings; the panel has no delisting returns).

**Books.** *Long deletions D(H)*: equal weight across live deletion
positions, rebalanced daily to equal weight; cash when none is live. *D minus
A (H)*: the same for additions, short; daily return = D's minus A's on days
both have a live position, 0 otherwise; the short pays the borrow fee.
Deleted names trade at 10 bps a side, additions at 5.

**Trials (5).** D(63), D(126), D(252), D-A(126), D-A(252). Selection: events
entered 1996-03-01 to 2012-12-31; out of sample: entered from 2013-01-01
(the D(H) daily series counts only out-of-sample entries from 2013). **Picks**:
the D trial with the best selection-window event-mean excess return over the
equal weight (per event, entry fill to exit fill, both net), and the better of
the two D-A trials by the same measure (deletion events minus addition events
averaged over the same window). Trial Sharpe for deflation: the book's
daily Sharpe (for D, its active series against the equal weight on days with
a live position).

**Pass rule (each pick, out of sample).**
1. Mean excess over the equal weight per event above 0, with the event
   bootstrap 5 % bound above 0 (for D-A: deletions' mean excess minus
   additions').
2. Positive mean excess in at least 2 of the 3 out-of-sample entry periods
   2013-2017, 2018-2021, 2022 on.
3. The book's Sharpe above the equal weight's over the days it holds a
   position (D-A: Sharpe above 0).
4. Mean excess above 0 with costs doubled and with entry a day later (open of
   R + 7).
Confirmed only with deflated p above 0.95. **Kill**: mean excess below 0 out
of sample. Also reported: events per year, the excess by year of entry, the
five events that move the mean most, how many held names hit the delisting
haircut, and the result without it.

## 3. Same-calendar-month seasonality (`seasonality`, 6 trials)

**Question.** Does a member's average return in the coming calendar month
over past years predict its return this month (Heston and Sadka)?

**Signal.** At the last session of month m-1 (the decision close), for each
member: the mean of its monthly returns (month-end adjusted close to
month-end adjusted close) in the same calendar month as m, over lag years
L in {1-5, 1-10, 1-20}. A name needs at least 3 of the years for 1-5 and 5 for
1-10 and 1-20 (all available up to 20). Signals start 2001-01.

**Books.** *Top 50*: the 50 members with the highest signal, equal weight.
*Decile long/short*: top decile minus bottom decile of members with a signal,
equal weight each, borrow fee on the short. Both rebalance at the first open
of the month in full. 3 lag sets x 2 books = 6 trials. Selection 2001-01-01
to 2015-12-31, out of sample from 2016-01-01. **Pick**: the lag set whose
long/short book has the best selection-window Sharpe at 5 bps; both books of
that lag set are judged.

**Rank IC.** Spearman's correlation across members between the signal and the
month's open-to-open return from the fill to the next month's fill; t = mean
/ standard deviation x sqrt(months), one value a month (non-overlapping).

**Pass rule (the pick's lag set, out of sample).**
1. Rank IC t above 2.
2. Long/short Sharpe above 0.3 at 5 bps a side.
3. Top 50: IR against the equal weight above 0, bootstrap 5 % bound above 0.
4. Top 50: IR above 0 with costs doubled and with fills a day late.
5. Top 50: active return positive in more than half the calendar years.
Confirmed only with deflated p above 0.95 (for the long-only book's active
series and for the long/short book). **Kill**: rank IC t below 1. A paper book
would be the top 50 (long-only); the long/short book is evidence only.

## 4. Gross profitability plus net share issuance (`quality_issuance`, 6 trials)

**Question.** Does a ranking on gross profit to assets and one-year net share
issuance, point in time by EDGAR filing date, pick members that beat the
equal weight of the members it ranks?

**Data.** SEC XBRL company facts (`data.sec.gov/api/xbrl/companyfacts`,
keyless; User-Agent from `PYTHIA_SEC_UA`; at most 5 requests a second; each
company fetched once and cached gzipped, then reduced to the few concepts
below) for every member with a CIK in the events map.
- **GP/A**: from the latest 10-K (form 10-K or 10-K/A, a fiscal-year value
  of 350 to 380 days) filed before the decision day and at most 15 months
  old: gross profit (`GrossProfit`; else revenue minus cost of revenue, from
  `Revenues`, `RevenueFromContractWithCustomerExcludingAssessedTax`,
  `SalesRevenueNet` and `CostOfRevenue`, `CostOfGoodsAndServicesSold`,
  `CostOfGoodsSold`) over `Assets` at that fiscal year end, both as filed in
  the same 10-K. Names without a gross profit (most banks and insurers) have
  no GP/A.
- **Net share issuance (NSI)**: log of the shares outstanding now over the
  shares a year earlier, split-adjusted. Shares: `dei:EntityCommonStockSharesOutstanding`
  of a 10-K or 10-Q (summed over share classes of one filing), known from its
  filing date. "Now": the latest filing before the decision day, at most 6
  months old; "a year earlier": the latest filing before the decision day
  minus 365 days, at most 6 months older than that. Splits between the two
  cover dates from the price file's split column. Low NSI ranks high (buyers
  of their own stock).
- **Composite**: the mean of the cross-sectional percentile ranks of GP/A
  (high is good) and of -NSI, on members with both.

**Books.** Month ends, filled at the next open. *Top 50*: the 50 best-ranked,
equal weight. *Quintile long/short*: top quintile minus bottom quintile,
equal weight, borrow fee. {GP/A, NSI, composite} x {top 50, long/short} = 6
trials. Benchmark: the equal weight of the members that have the signal that
month (the ranked universe), monthly at 5 bps. Selection 2011-01-01 to
2017-12-31, out of sample from 2018-01-01 (under nine years; said so).
**Pick**: the signal whose top 50 has the best selection-window IR against
its universe's equal weight; its long/short book is reported with it.

**Pass rule (the pick's top 50, out of sample).**
1. IR above 0.3 against its universe's equal weight.
2. Bootstrap 5 % bound of the IR above 0.
3. IR above that of a 12-1 momentum top 50 on the same universe and days
   (computed here as a baseline, not a trial; M9 counted it).
4. IR above 0 with costs doubled and with fills a day late.
5. Sharpe above the equal weight's and active return positive in more than
   half the calendar years.
Confirmed only with deflated p above 0.95. **Kill**: IR below 0.1. Also
reported: coverage per year (members with GP/A, with NSI, with both), the
rank IC of each signal against the next month's return.

## 5. Turn of the month and pre-holiday in index ETFs (`turn_of_month`, 10 trials)

**Question.** Does holding SPY, QQQ or IWM only over the turn of the month
(or the session before a market holiday) earn the index premium with a
fraction of the exposure?

**Data.** Yahoo daily OHLC with adjusted closes (`overnight`'s loader and its
cache format) for SPY (from 1993), QQQ (1999-03) and IWM (2000-05); the
session calendar is SPY's. Returns close to close on adjusted closes.

**Rules.** Session -1 is the last session of a month, +1 the first of the
next. A window [-a, +b] holds the ETF over the close-to-close returns of
sessions -a to +b: bought at the close of session -a-1, sold at the close of
+b (market-on-close orders). Windows {[-1, +3], [-2, +3], [-1, +1]} x ETF
{SPY, QQQ, IWM} = 9 trials. **Pre-holiday** on SPY: held over the return of
the last session before a weekday without a session (bought at the close of
the session before it), except the closures nobody knew of the evening before
(2001-09-11 to 14 and 2012-10-29 to 30): 1 trial. Total 10. Cash earns 0.
Costs: 2 bps a side plus the SEC fee and TAF on sells; doubled 4 bps.
Selection 1993-02-01 to 2015-12-31 (QQQ and IWM from their first full year),
out of sample from 2016-01-01. **Pick**: the best selection-window Sharpe of
the 10.

**Pass rule (the pick, out of sample).**
1. Mean return on window sessions above the mean on other sessions of the
   same ETF, Welch t above 2.
2. Sharpe above the ETF's own Sharpe bought and held, and above SPY's.
3. Bootstrap: Sharpe above SPY's in at least 90 % of draws.
4. Sharpe above 0 with the window shifted one session later and with costs
   doubled.
5. As a 20 % sleeve with the crypto books, `book_portfolio`'s rule (higher
   Sharpe and lower drawdown than the best crypto book alone from 2024, in 2
   of 3 years, bootstrap band of the difference above 0); run only if 1 to 4
   hold.
Confirmed only with deflated p above 0.95. **Kill**: window sessions not above
other sessions out of sample. Also reported: exposure (share of sessions
held), the mean by session of the window (-2 to +3) out of sample, per year.

## 6. Opportunistic insider purchases (`insider_purchases`, 6 trials, deferred)

**Question.** Do open-market purchases (Form 4, transaction code P) by
insiders who are not routine traders, filed in the last 30 days, predict 1
and 3-month returns of S&P 500 members?

**Data.** SEC's Insider Transactions Data Sets (quarterly Form 345 files from
2006). Opportunistic: an insider who did not trade in the same calendar month
in each of the three prior years (Cohen, Malloy and Pomorski); a cluster: 2 or
more distinct insiders buying within 30 days. Known from the filing date.

**Design.** Signal {all purchases, opportunistic only, cluster buys} x hold
{21, 63 sessions} = 6 trials; bought at the open after the filing date,
equal weight across live positions; selection 2006 to 2015, out of sample
from 2016. **Pass**: mean excess over the equal weight per event above 0 with
the event bootstrap 5 % bound above 0, positive in 2 of the 3 out-of-sample
periods (as study 2), the book's Sharpe above the equal weight's over its
days, a day late above 0; deflated. **Kill**: excess below 0.

**Deferred.** The data sets are on `www.sec.gov`, which refuses requests
without a contact in the User-Agent. This study runs only when
`PYTHIA_SEC_UA` names one; until then it is documented, not run, and its 6
trials are not counted.

## Corrections to the survey's sketches

- Pool: the survey counted 1,724; Polymarket's 16 came since, so the pool
  starts at 1,740 and is 1,773 with these 33 trials.
- Earnings premium: the sketch's "window within 5 or 10 days x entry 5 or 2
  days before" is made concrete as entry e sessions before and exit x
  sessions after the expected date; expected dates use 8-K events only, for
  the base too; the long-only book's cash is SPY, the judged tilt book's is
  the CIK equal weight.
- Deletions: "still priced 60 sessions after removal" would decide the event
  with 60 days of future data; the class is decided on R + 5 and the entry
  waits for it. A delisting haircut is added because the panel has no
  delisting returns. Deleted names pay 10 bps a side.
- Seasonality: "all available up to 20" needs at least 5 years; IC on the
  open-to-open month the books earn.
- Quality: the definitions of GP/A and NSI, the filing-date rule and the
  split adjustment are fixed here; the benchmark is the ranked universe's
  equal weight; the momentum baseline is recomputed on that universe.
- Turn of the month: close-to-close with market-on-close fills (the effect
  sits on the first session, which a next-open fill would skip half of);
  every ETF pays 2 bps a side; the sleeve test runs only if the rest passes.
- Insider purchases: deferred until the User-Agent carries a contact.
