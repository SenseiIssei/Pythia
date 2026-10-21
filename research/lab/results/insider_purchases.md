# Opportunistic insider purchases: not run (2026-10-21)

Registered as study 6 of `results/survey_equities_prereg.md` (6 trials) and
deferred there. Nothing was computed and no trial is counted; the pool stays
at 1,773 until it runs.

## Why it did not run

The study needs SEC's Insider Transactions Data Sets (quarterly Form 345
files from 2006, about 80 zip files). They are served from `www.sec.gov`,
which refuses every request whose User-Agent carries no contact: on
2026-10-21 the data set page, a quarterly file and `company_tickers.json`
all answered 403 to the lab's default User-Agent, while `data.sec.gov` (the
XBRL company facts that `quality_issuance` uses) answered normally. SEC's
fair access policy asks for a name and a contact in the User-Agent; the lab
reads it from `PYTHIA_SEC_UA` and never writes one into the code, and the
variable was not set where this ran. Single Form 4 filings live on
`www.sec.gov/Archives` too, so there is no keyless way around it.

## What running it takes

1. Set `PYTHIA_SEC_UA` to a name and a contact address where the lab runs.
2. Fetch the quarterly files once (2006q1 on) into their own folder, at most
   5 requests a second, and keep only non-derivative transactions with code
   P (open-market purchases) of issuers whose CIK is in the events map: filing
   date, issuer CIK, reporting owner, shares, price.
3. Run the registered design unchanged: signal {all purchases, opportunistic
   only (no trade by that insider in the same calendar month in each of the
   three prior years), cluster buys (2 or more insiders within 30 days)} x hold
   {21, 63 sessions}, bought at the open after the filing date, equal weight
   across live positions, selection 2006 to 2015, out of sample from 2016,
   the registered gates and kill rule. The event-book machinery of
   `index_deletions` (`survey_equities.del_positions`, `event_excess`) fits
   it as it is.

## Prior

Cohen, Malloy and Pomorski report 82 bps a month for opportunistic insiders,
value weighted, over all US stocks. The other four equity studies registered
with it failed in the S&P 500 (`earnings_premium` only before costs, the rest
outright), and the insider effect is reported weaker in large caps, so the
prior for this one is low as well.
