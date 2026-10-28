# T10: record xStocks daily. Result

Pre-registered in `results/xstocks_t10_prereg.md` (committed first). Code `lab/collect/xstocks.py`, tests
`tests/test_xstocks_t10.py` on recorded answers of 2026-10-28 (`tests/fixtures/xstocks`: SPYx's seven endpoints, two
splits, an error page). Job `xstocks-collect` (00:00 and 12:00 UTC), dataset `xstocks` (`free/xstocks`, max_age_h
14), feed row `xstocks` (quotes and reserves, max_age 14h). Paper only: nothing a book, bot, wallet or engine reads
changed. One trial in R5's registry (`small:t10:xstocks_premium`, counted only): the pool becomes 2,524 in all and
247 in the small family.

## What is recorded

SPYx only: S2's two picks are SPYx (xStocks) and PAXG (Paxos, not on this API). Per run and token: the issuer's
indicative quote, the multiplier (current, next, activation, reason), the halt flag, proof of reserves (shares held,
circulating supply, custodians, the source's timestamp), the oracle feeds (Pyth and Chainlink ids) and every
corporate action record (history and upcoming, per event, version and status; the six of SPYx are dividends from
2025, all stored as backfilled, known an hour after their creation).

The API names its oracles but serves no oracle value without a key, and Pyth's Hermes now answers 401. The quote of
`price-data` is the oracle-side price recorded. A missing field is empty; a quote without a price, an error page or
an `{"error"}` answer fails its part only (tested).

## A deviation from the pre-registration: the multiplier

SPYx is a token-2022 token with a scaled UI amount: a wallet shows raw units x multiplier, and Jupiter's answer for
the mint carries the same multiplier (`scaledUiConfig`) next to a price of 769.60, about one SPY share. The issuer's
quote (769.95 at 05:00 UTC, SPY closed at 769.66) is per shown unit too. The pre-registration divided by the
multiplier ("to NAV = quote / (multiplier x close) - 1"), which would print -53 bps for a token trading at its NAV.
The code instead reports:

- **to NAV** = quote / close - 1 (the pre-registration's "raw"), and
- **a raw unit** = quote x multiplier / close - 1 (one unscaled unit is worth multiplier shares).

## R10's and S2's series measured mostly the multiplier

Their means follow SPYx's multiplier history (1.0010, then 1.0026 from 2026-01-30, 1.0039 from 05-01 and 1.0057
from 06-18). This is a check of the unit, made after the pre-registration and counted in the same trial:

| series | n (cleaned) | mean bps | the multiplier on its days, bps | difference | sd raw | sd less the multiplier |
|---|---|---|---|---|---|---|
| S2, at the US close | 123 | 49.8 | 51.3 | -1.5 | 24.5 | 23.7 |
| R10, 00:00 UTC after a US close | 251 | 28.5 | 34.6 | -6.2 | 34.7 | 27.2 |

So the token trades close to its NAV, and CoinGecko's price was per raw unit. R10's draws take each deviation less
its mean, so the level never entered its wallets. Its spread did: about a fifth of R10's US-day sd is the multiplier
stepping, which makes R10's premium noise somewhat too wide, never too narrow. S2's drift has its own definition and
is not checked here. Replacing R10's draws with this record is a separate pre-registered study, once weeks of 00:00
rows exist.

## The first record

One run at 05:21 UTC on 2026-10-28 into a scratch lake (not 00:00, so no 00:00 UTC row yet): SPYx 769.95 against
SPY's close of 2026-10-27 at 769.66, **+3.7 bps to NAV**, a raw unit +60.9 bps, not halted; reserves 89,779.00 SPY
at Alpaca against a supply of 88,888.35 x 1.005715 = 89,396.3 shares, **cover 1.0043**. On the server the record
starts with the job's first run; `<data>/reports/xstocks/latest.md` shows the 00:00 UTC rows next to R10's and S2's
series each run.
