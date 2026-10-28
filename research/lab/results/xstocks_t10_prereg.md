# T10: record xStocks daily. Pre-registration

Registered 2026-10-28 and committed before the collector made its first record and before any premium was computed
from one. Brief T10 of the training plan of 2026-10-28, on the review of 2026-10-27 (`results/review_2026-10-27.md`,
section 2: "SPYx is priced at SPY's close, which is 3 to 4 hours stale at the 00:00 UTC decision and stale all
weekend"; build item 10: the small path's main asset has no point-in-time NAV record), R5's registry
(`metrics.trial_pool`) and R10 (`results/smallaccount_r10.md`, its series `results/smallaccount_r10_tokens_0000.csv`
and S2's cleaned premiums `results/smallaccount_s2_premiums.csv`). Code: `lab/collect/xstocks.py`; tests
`tests/test_xstocks_t10.py` on recorded answers (`tests/fixtures/xstocks`). Result: `results/xstocks_t10.md`. Paper
only: no paper book, live bot, wallet or engine reads anything here.

While scoping, one look at xStocks' published API description (docs.xstocks.fi, `/_bundle/apis/@v2/openapi.yaml`)
and one answer of each public endpoint below for SPYx, recorded as the fixtures. No premium was computed from them.

## What is recorded

The xStocks tokens the small books use: S2's picks of family `xstocks` in `results/smallaccount_s2_snapshot.json`
(today SPYx on SPY; PAXG, the gold pick, is Paxos's and has no xStocks record). Keyless public API
`https://api.xstocks.fi/api/v2/public`, at most two requests a second. Through D2's `lab.collect.pit` (ts_us,
collected_us, known_us, backfilled; the first value of a key wins), into `<data>/free/xstocks/`:

- **quotes** (one row per token and run, ts_us the run's hour): `price-data` (the issuer's indicative price of one
  token in USD; the API names its Pyth and Chainlink feeds but serves no oracle value without a key, and Pyth's
  Hermes asks for one too, so this quote is the oracle-side price recorded), `multiplier` on Solana (shares of the
  underlying one token stands for, the next one, its activation and reason) and `system/status` (trading halted).
- **reserves** (one row per token and run): `proof-of-reserves/{symbol}`: shares held, circulating supply, the
  source's timestamp, the custodians as JSON.
- **oracles**: the feeds `oracles/{symbol}?network=Solana` names (provider, feed id), first seen kept.
- **actions**: `corporate-actions/history` and `/upcoming` per token, one row per event, version and status;
  ts_us the record's creation, known_us the run that saw it, or its creation plus one hour for one first seen more
  than 30 hours later (backfilled).

A missing field leaves its value empty (a quote without a price is no row and an error); an error page or an
`{"error"}` answer fails that part only; every part failing fails the job. Job `xstocks-collect` at 00:00 UTC (the
small books' decision time) and 12:00 UTC; dataset `xstocks` (`free/xstocks`, max_age_h 14); feed row `xstocks`
over quotes and reserves.

## The one number: the premium

For each quote row, the underlying's last close known at its time (the close of day d counts from d 21:00 UTC;
`<data>/etf/daily`): raw = quote / close - 1 in bps (R10's `dev_bps` convention, which does not divide by the
multiplier) and to NAV = quote / (multiplier x close) - 1. Shown per token for the 00:00 UTC rows and all rows
(count, mean, sd, the newest), next to R10's 00:00 UTC deviations (cleaned with `s2.clean`, US days and days without
a US close) and S2's cleaned premiums at the US close, and the reserve cover shares held / (circulating supply x
multiplier). The report is `<data>/reports/xstocks/latest.{md,json}`, written each run.

It is a measurement, not a rule: no Sharpe, no DSR, no pass or fail. It is one trial in R5's registry
(`small:t10:xstocks_premium`, family small, counted only, registered before the first premium). The weeks of records
that follow may later replace R10's drawn deviations in the small-account studies; that change is its own
pre-registered study.
