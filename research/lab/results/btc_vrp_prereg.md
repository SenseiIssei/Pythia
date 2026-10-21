# BTC volatility risk premium from DVOL (survey #9): pre-registration

Registered 2026-10-21 and committed before any number below was computed.
Drafted from candidate 9 of `proposals/2026-10-21-strategy-survey.md`; changes
at the end. Code: `lab.experiments.btc_vrp`. Results: `results/btc_vrp.md`.
Nothing here may change once a result exists. Pool shared with `vix_carry`
(see there): 1,762 with this batch. INFORMATION ONLY: no options trading code
is written; the result is evidence for a later options sleeve on Alpaca (IBIT
options), which would need its own forward test on real quotes.

## Question

Does selling 30-day BTC volatility (a cash-secured put at the money, one 10 %
out of the money, or a covered call at the money), priced from Deribit's DVOL
minus a haircut, earn more per unit of risk than BTC and than gated BTC since
2021, and does a filter on DVOL against realised volatility help?

## Data

- Deribit BTC DVOL daily (`<data>/flow/dvol.parquet`, from 2021-03-24).
- Binance BTCUSDT daily closes (00:00 UTC) and their 30-day realised
  volatility (daily log returns, x sqrt 365).

## Synthetic options

Black-Scholes, zero rates, no dividends. Every 30 calendar days from the first
day with 30 days of realised volatility, at the 00:00 UTC close of the roll
day, one option expiring 30 days later is sold at implied volatility DVOL - h
(h = 3 vol points base, 6 stress); h stands for the spread and the skew a
seller gives up. It is marked daily at DVOL with the time left (no haircut on
the mark) and settles at intrinsic value against the Binance close at expiry;
the next one is sold at the same close.

- **P0** cash-secured put, strike at the money: capital = strike, NAV = cash +
  premium - put value.
- **P10** cash-secured put, strike 90 % of spot: same.
- **CC** covered call, strike at the money: capital = one BTC, NAV = BTC +
  premium - call value.

Filter variants (**F**): sell only when DVOL - RV30 at the roll close exceeds
its in-sample median (computed on the in-sample roll days); otherwise the put
variants hold cash and the covered call holds BTC uncovered for that month.

Returns: daily change of NAV over the capital at the previous close, compounded
from roll to roll; 365 days a year.

## Windows

In sample from the first roll (about 2021-04-23) to 2023-12-31, out of sample
2024-01-01 to the DVOL data end. Pick = best in-sample Sharpe at h = 3.

## Trials (6)

{P0, P10, CC} x {always, F}.

## Benchmarks

BTC held (Binance close to close); gated BTC (`gated_btc`'s G at k = 1: BTC
while its close is above its 200-day average, 35 bps).

## Pass rule (the pick, out of sample)

1. Sharpe above BTC's and above gated BTC's at h = 3;
2. Sharpe above 0 at h = 6;
3. maximum drawdown below BTC's;
4. positive in at least 3 of the 5 years 2022 to 2026 (2026 to date; 2022 and
   2023 are in sample, the rule is a stability check);
5. the bootstrap 5 % bound of Sharpe(pick) - Sharpe(BTC) above 0 (stationary,
   mean block 20 days, 4,000 draws, seed 20261021).

Deflated p over the pool reported; confirmed only above 0.95. A pass means
"worth a 60-day forward test on IBIT option quotes in the Alpaca paper
account", nothing more.

## Kill rule

Out-of-sample Sharpe below BTC's at h = 3.

## Also reported, not judged

The variance risk premium itself: DVOL against the realised volatility of the
next 30 days (mean, share of days positive, by year), and what IBIT's own
implied volatility would need to be for the pick to break even (DVOL - h with
h solved for a Sharpe of 0).

## What could fool us

- DVOL is a 30-day at-the-money-ish index; the 10 % put is priced off the
  skew, so P10 is the least trustworthy row.
- No transaction record exists before 2026-10-15 (the Deribit option
  snapshots); the history is a model.
- IBIT options trade US hours only, on an ETF that gaps over weekends;
  DVOL is a 24/7 index.

## Changes to the survey's sketch

- The year rule counts 2022 to 2026 (2021 is a partial first year and only
  in sample).
- A bootstrap rule against BTC is added.
