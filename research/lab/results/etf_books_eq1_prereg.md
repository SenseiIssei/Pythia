# EQ1: long-term ETF paper books at 50 EUR, as a German retail investor can trade them. Pre-registration

Registered 2026-10-29 and committed before any number below was computed (while scoping, one look at Yahoo's
listing of each fund: its name, currency, first and last date, no return). Brief EQ1 of the training plan of
2026-10-28, on the review of 2026-10-27 (`results/review_2026-10-27.md`, sections 2 and 3), R5's registry
(`metrics.trial_pool`, `<data>/trials/registry.jsonl`), R6's windows (`results/factory_lockbox_r6.md`), R10
(`results/smallaccount_r10.md`: SXR8 in EUR made 18.4 % a year at 40 EUR, dual momentum beat it with a 28.7 %
drawdown), `etf_trend` (dual momentum 252 days top 3 on US ETFs, the only near-pass) and the failed stock picking
(`results/equities_training.md`, `results/equities_ranking.md`). Code: `lab.experiments.etf_books_eq1` (the study),
`lab.paper.etf_books` (the paper books), the UCITS closes through `lab.collect.etf_daily` (written after this file).
Results: `results/etf_books_eq1.md`. Nothing here may change once a result exists. Paper only: nothing a live bot, a
wallet or the engine reads changes.

## Question

Which long-term ETF book should the owner follow with 50 EUR (once, or plus 50 EUR a month), with the orders a
German retail investor can actually place, and does any active book beat simply holding a UCITS S&P 500 fund?

## Universe (UCITS, in EUR, Xetra, Yahoo's `.DE` listing)

A German retail investor cannot buy US-domiciled ETFs (PRIIPs, no KID). Eight funds, Yahoo's adjusted closes in EUR
(distributions reinvested, as an investor who reinvests them; splits adjusted):

| Role | Symbol | Fund | Yahoo history from |
|---|---|---|---|
| world | EUNL.DE | iShares Core MSCI World UCITS ETF USD (Acc) | 2009-09 |
| S&P 500 | SXR8.DE | iShares Core S&P 500 UCITS ETF USD (Acc) | 2010-05 |
| Europe | EXSA.DE | iShares STOXX Europe 600 UCITS ETF (DE), distributing | 2008-01 |
| emerging | EUNM.DE | iShares MSCI EM UCITS ETF USD (Acc) | 2009-10 |
| small caps | IUSN.DE | iShares MSCI World Small Cap UCITS ETF USD (Acc) | 2018-04 |
| bonds | EUNH.DE | iShares Core EUR Govt Bond UCITS ETF, distributing | 2009-04 |
| gold | 4GLD.DE | Xetra-Gold (an exchange-traded commodity backed by gold, not a UCITS fund; tradable for German retail) | 2009-11 |
| cash | XEON.DE | Xtrackers II EUR Overnight Rate Swap UCITS ETF 1C | 2008-01 |

- **US twin only where short.** Only IUSN's series is short: before its first close the small-cap leg is IWM (the
  lab's `etf/daily/IWM.csv`, Russell 2000, US small caps only, a rough twin of MSCI World Small Cap) in EUR at the
  ECB's daily reference rate, joined to IUSN's first close. Said so in every table. Every other fund is its own series.
- **Collected** by `lab.collect.etf_daily` (job `etf-daily`, weekdays 22:30 UTC) into `<data>/etf/daily/<SYM>.csv`,
  Yahoo only (Stooq is down since 2026-10-28, `etf_trend.STOOQ_DOWN`, and has no `.DE` listing in its US URL). The
  ECB's rates for the twin are recorded once into `results/etf_books_eq1_eurusd.csv` (`--snapshot`).
- **Bad prints.** A close more than 15 % from the close before and more than 15 % back the next close (the other
  direction) is dropped and the day marked at the close before. The count is reported.
- **Calendar.** SXR8's trading days (Xetra). A fund without its own close that day is marked at its last close and is
  not traded that day.

## Windows (R6)

In sample 2011-06-01 to 2023-12-31 (SXR8 needs a year of closes first), validation 2024-01-01 to 2026-06-30. Every
close after 2026-06-30 is dropped before anything is computed: the lockbox is never read here. Each window starts a
fresh wallet on its first day; the rules read the history before it.

## Timing: one close late

A rule decides at the close of day t from closes up to t. Its orders fill at the close of the next Xetra day t+1 at
that close plus the half spread, sized against the wallet at t+1. The wallet starts in cash on the window's first
day (day 0, a decision day for every rule); the first orders go out at the close of day 1.

## The books (five rules)

| Book | Rule | Decides |
|---|---|---|
| `hold_sp500` | 100 % SXR8. **The benchmark every other book must beat.** | last Xetra day of each month |
| `hold_world` | 100 % EUNL | last Xetra day of each month |
| `dual_mom` | `etf_trend`'s near-pass ported: the eight funds' 252-day return (close t over close t-252), a fund only with 253 closes; the top 3 with a return above 0 at 1/3 each, an empty slot cash | last Xetra day of each week |
| `trend_sp500` | SXR8 while its close is above the mean of its last 200 closes, else XEON | last Xetra day of each month |
| `voltarget_sp500` | SXR8 at min(1, 15 % / its vol), vol the standard deviation of its last 63 daily returns times sqrt(252); the rest XEON | last Xetra day of each month |

Each book in two variants: `once` (50 EUR on day 0, nothing more) and `plus50` (50 EUR on day 0 and 50 EUR on the
first Xetra day of every month after).

**The order rule (every book, every broker).** At a fill close each fund's gap is target weight times equity minus
its value. A fund trades when the gap is at least 10 points of equity (S1w's band), when its target is 0 and it is
held (an exit, the whole position, fractions too), or when its target is above 0 and nothing is held (an entry).
Sells first, then buys from the cash there is (scaled down when short, the fee paid out of it). An order is **not
sent** when it is under the broker's minimum: under one unit where the broker trades whole units (rounded down,
0 units is not sent), under 1 EUR at a fractional broker, or under 10 EUR for a one-off buy or a partial sell (the
fee would be 10 % or more of it; the lab's own minimum, MIN_ORDER_EUR). An exit is always sent. Not-sent orders are
counted, nothing waits for the next day.

**The top-up.** 50 EUR is booked on its day (the first Xetra day of the month) as cash at that close. Where the
broker has a savings plan (Trade Republic, Scalable), a plan invests it the same close, free and in fractions, by
the book's targets of its last decision (known before the day), each plan line at least 1 EUR (a smaller line stays
cash), at the half spread; then the order rule runs if it is an order day. At Interactive Brokers the cash waits for
the book's next order day. The hold books' first 50 EUR go in through the plan on day 1 where there is one.

## Costs per broker, as they state them

Read from the brokers' price lists as the owner's brief gives them; the brokers' pages did not answer this run, so
the details (fractional one-off orders, minimums) are assumptions the owner checks before step 5:

| Broker | One-off order | Fractions | Savings plan |
|---|---|---|---|
| `tr` Trade Republic | 1.00 EUR an order (buy or sell) | one-off orders by amount, from 1 EUR | free, fractional, from 1 EUR |
| `scalable` Scalable Capital, free broker tier | 0.99 EUR an order | whole units only for one-off orders; plan fractions can be sold whole | free, fractional, from 1 EUR |
| `ibkr` Interactive Brokers (IBKR Pro tiered, Xetra) | 0.05 % of the order, at least 1.25 EUR (exchange and clearing fees of a few cents left out) | whole units only | none modelled (the only one with an API for UCITS ETFs) |

Half spread on every fill, plans included: 5 bps for SXR8, EUNL, EUNH, XEON; 10 bps for EXSA, EUNM, IUSN, 4GLD
(assumed, R10 used 5 bps for SXR8). No interest on broker cash. **Taxes are left out** (Abgeltungsteuer,
Vorabpauschale, Sparerpauschbetrag): every number is before tax. The final sale is not deducted (one order per held
fund would cost 1 to 1.25 EUR more each).

## Measures

Per book, variant and broker, late, in sample and validation: CAGR and max drawdown of the time-weighted
(cash-flow-adjusted) equity, the longest spell under water in months (calendar days from a peak to the day it is
regained or the window ends, over 30.44), Sharpe on calendar days (zero on days without a session, times sqrt(365),
the registry's convention), the end value, what was paid in, the money-weighted return for `plus50`, orders sent and
not sent, fees paid. Against the benchmark book (`hold_sp500`, same broker and variant): the CAGR difference, the
share of months it beat it, and the daily time-weighted excess return.

## Trials (30)

5 books x 2 variants x 3 brokers, each a line of R5's registry (family `small`, source this file), registered before
any validation number: `small:eq1:<book>:<once|plus50>:<tr|scalable|ibkr>`, with the in-sample Sharpe of its daily
excess over the benchmark book; the six `hold_sp500` lines counted without a Sharpe (they are the benchmark).

## Pass rule (per book, variant and broker other than the benchmark; all must hold, validation, late)

1. CAGR above the benchmark book's.
2. Max drawdown at most 5 points deeper than the benchmark book's.
3. DSR (higher is better) of the daily excess over the benchmark book at least 0.95 over R5's pool of all and over
   the small family, each with these trials.
4. PBO (`metrics.cscv`, 16 blocks) of the eight non-benchmark Trade Republic configurations (four books, two
   variants) on their daily excess over in sample and validation below 0.2 (the ladder's bar).

A configuration that passes gets R6's one lockbox look in its own commit; none is made here.

## Paper books

All ten (book x variant) in the lab's daily paper run (`lab.paper.etf_books`, job `paper-etf-books` after
`etf-daily`), `eq1_<book>_<once|plus50>`, each with three wallets (one per broker) of 50 EUR from its first run,
the same order rule, one close late on the lab's closes, the top-up on its day. The ladder (`lab.ops.ladder`) lists
them as candidates of study EQ1 against a UCITS S&P 500 fund in EUR, judged on the Trade Republic wallet (the broker
with fractional one-off orders), with the study's CAGR, drawdown, months under water and the difference to the
benchmark book. Nothing trades real money; the ladder only proposes.
