# Post-earnings drift from XBRL earnings surprises: pre-registration

Registered 2026-10-21 and committed before any surprise or return below was
computed. Code: `lab.experiments.pead_xbrl` (written after this file).
Results go to `results/pead_xbrl.md`. Nothing here may change once a result
exists. Registered together with `positioning_xs`, `taker_imbalance_xs` and
`hedged_breakout` (24 trials in all, see `positioning_xs_prereg.md`).

## Question

Post-earnings announcement drift (Ball and Brown 1968; Bernard and Thomas
1989, 1990): shares with the largest standardised unexpected earnings keep
outperforming for weeks. X16 (`equities_training`) tried it with the
two-day abnormal return as the surprise and failed (0.54 against 0.78 for its
universe). Here the surprise is the accounting one, from the EPS the
companies file in XBRL. Does a long-only book of the top decile of S&P 500
members by SUE, bought on the second session after the filing, beat the
equal weight of its universe out of sample from 2018 after costs, and does
the top decile minus the bottom decile pay?

The literature says to expect little: the drift has shrunk sharply in
large, liquid US shares since the mid-2000s (Chordia, Goyal, Sadka, Sadka
and Shivakumar 2009; Martineau 2022, "Rest in peace post-earnings
announcement drift"). The study is run because XBRL makes the classic
measure cheap and point in time, and because the long-only form is the one
thing the Alpaca paper account could trade.

## Data

- **Members and prices**: the lab's point-in-time S&P 500 (M9's public
  dataset with dead names, `lab.equities.panel`, sessions to 2026-10-16),
  open-to-open returns and next-open fills (`survey_equities.wsim`), as the
  equity survey. Members must have a CIK (the EDGAR map of
  `equities_training`, 624 CIKs) and 252 sessions of history
  (`survey_equities`' `ok`).
- **EPS**: the SEC company facts `quality_issuance` cached (fetched
  2026-10-21, gzipped, every concept kept), us-gaap
  `EarningsPerShareDiluted`, else `EarningsPerShareBasicAndDiluted`, else
  `EarningsPerShareBasic`, unit USD/shares.
- **Filing dates**: each company's EDGAR submissions index (cached by
  `equities_training`): every original 10-Q and 10-K (amendments ignored)
  with its accession number, filing date and period of report.

Run on the PC against the synced data mirror (read only; reports and the
EPS table written elsewhere), where the equity caches are, as the equity
survey was. Nothing is downloaded.

## Earnings and surprise (point in time)

Company facts list a value once per distinct value and keep the latest
filing that reported it, so the filing date of a fact is not when it became
known. The announcement is therefore the original 10-Q or 10-K for the
period (from the submissions index), and the values are read as follows:

- Durations: a quarter is 70 to 110 days, nine months 250 to 290, a fiscal
  year 340 to 390.
- EPS_q of the period ending e (the filing's period of report): the quarter
  value ending e reported in that filing (same accession) if present, else
  the earliest-filed quarter value ending e. For a 10-K without a quarter
  value: the fiscal-year value ending e minus the nine-month value ending
  about three months before e (each read the same way), i.e. Q4 derived.
- EPS_{q-4}: the value for the quarter ending e minus one year (plus or
  minus 20 days) reported in the same filing (the comparative, on the same
  share basis after splits) if present, else the latest one filed on or
  before the filing date; Q4 derived the same way.
- D_q = EPS_q - EPS_{q-4} (seasonal random walk, Foster, Olsen and Shevlin
  1984). SUE_q = D_q / standard deviation of D over the company's previous
  8 quarters (at least 6, each D as computed at its own filing), when that
  is above 0.

## Events, deciles and timing

- The filing date is the announcement date. Session f is the first session
  on or after it; the member must be in the index and `ok` on f.
- Top decile: SUE above the 90th percentile of the SUEs of all universe
  events filed in the 365 days before (at least 100 events); bottom decile:
  below the 10th. Point in time, no look-ahead into the quarter.
- Entry at the open of session f+2 (decided at the close of f+1), exit at
  the open of session f+2+H, H = 20 or 60 sessions.

## Books

- **Long-only (top decile)**: each session, equal weight over the active
  positions, each at most 10 % of the book (fewer than 10 names: the rest in
  cash). Weights reset to that rule on the sessions the set changes, drift in
  between.
- **Long/short (top minus bottom decile)**: the same long book minus the same
  book built on the bottom decile (`survey_equities.ls_series`, the short leg
  borrowing at 0.3 % a year).

Costs: **5 bps a side** on every trade plus the SEC fee and FINRA TAF on
sales (`wsim`); stress 10 bps.

## Trials (4)

Long-only H = 20 and H = 60; long/short H = 20 and H = 60. For each form the
pick is the H with the higher selection-window IR (long-only, against the
universe) or Sharpe (long/short); both H are counted.

## Windows

Selection: sessions 2011-01-01 to 2017-12-31 (XBRL from 2009 to 2011 for most
members, eight prior quarters of D needed). Out of sample from 2018-01-01 to
the last session where an exit can still be taken (for the books, the
panel's end; open positions are marked).

## Benchmarks

The equal weight of the members with a CIK and `ok`, rebalanced monthly at
5 bps (`survey_equities.equal_weight` on the CIK columns), and SPY. The
long-only book's active return a session is its net return minus its
invested share times the equal weight's net return (the cash part is not
benchmarked); IR = the annualised Sharpe of that series (252 sessions).

## Pass rules (out of sample, for each form's pick)

**Long-only** (all):
1. IR above 0.3.
2. Stationary bootstrap of the IR (block 20 sessions, 4,000 draws, seed
   20261021): 5 % bound above 0.
3. IR above 0 with costs doubled, and above 0 a day late (entry at f+3).
4. Active return positive in more than half of the out-of-sample years.
5. The book's Sharpe above the equal weight's.

**Long/short** (all):
1. Sharpe above 0.5 at 5 bps and above 0 at 10 bps.
2. Bootstrap 5 % bound of the Sharpe above 0.
3. Positive in more than half of the out-of-sample years.
4. A day late above 0.

Confirmed only with a deflated p above 0.95 over the pool. **Kill:** the
long-only pick's IR below 0.1.

## If it passes

A long-only lab paper book under `lab/paper/` marked EXPERIMENT (the paper
account can only trade the long side), fed by a daily EDGAR filing and XBRL
refresh, and a job added disabled. Nothing wired into an autopilot.

## Reported, not judged

All four trials in and out of sample at 5 and 10 bps; mean excess return
(against the equal weight, open to open) per SUE decile at 20 and 60
sessions, by period; the rank IC of SUE with those excess returns; events
per year and coverage (members with a SUE); the share of Q4 surprises that
had to be derived; the median days from period end to filing.

## What could fool us

The 10-Q is filed days to weeks after the earnings release (8-K item 2.02),
so most of the immediate reaction and part of the drift happen before entry;
the registered date is the filing because it carries the numbers. Diluted
EPS includes one-off items, so a "surprise" can be an accounting charge the
market saw coming. Members without a CIK (mostly names that left the index)
are missing, which flatters the universe. The out-of-sample window holds
under nine years and two very different markets (2020, 2022).
