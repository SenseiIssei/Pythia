# Route the books' BTC and ETH legs through spot ETFs (survey O1): pre-registration

Registered 2026-10-21 and committed before any number below was computed.
Drafted from idea O1 of `proposals/2026-10-21-strategy-survey.md`; changes at
the end. Code: `lab.experiments.etf_routing`. Results: `results/etf_routing.md`.
Nothing here may change once a result exists. Pool shared with `vix_carry`
(see there): 1,762 with this batch.

## Question

Would filling the crypto books' BTC and ETH legs through US spot ETFs (IBIT
for BTC from 2024-01-11, ETHA for ETH from 2024-07-23) in US market hours,
instead of Alpaca crypto at its taker fee, save money net of tracking, the
expense ratio, the weekend gap and the spread? Per book.

## Books

As they run on Alpaca (coins Alpaca does not list held in cash), from
`alpaca_universe`'s simulators on the survivorship-free panel cut at the data
end: `breakout_top10`, `tsmom_top20`, `tsmom_tranches`; and the experimental
`btc_gated` (BTC at full weight above its 200-day average, `gated_btc`'s G at
k = 1), whose whole book is the BTC leg. trend4h_pullback is left out: it
decides every 4 hours around the clock, which an ETF cannot follow.

## The two ways to fill a leg

For coin c in {BTC, ETH} and every daily decision (the book's weights after
the close of UTC day t, `held[t, c]`, and the drifted weights going into it,
`pre[t, c]`):

- **A, Alpaca crypto (today).** The trade happens at 04:15 UTC of day t+1 at
  Binance's 1-minute price; until then the leg is `pre[t, c]`, from then
  `held[t, c]`. Cost 35 bps per unit traded (25 bps taker plus 10 of
  slippage, the books' judged cost). Also reported: 25 and 15 bps.
- **B, the ETF.** The trade happens at the first US regular-session open at
  or after 04:15 UTC of day t+1 (the same day on a weekday session, Monday or
  the next session otherwise), at the ETF's official opening price; decisions
  made while the market is shut are netted into that one trade. Cost 2 bps a
  side per unit traded (half the spread plus slippage on a cent-wide ETF),
  stress 5 bps. The ETF position moves only at its own prints: the gap from
  the previous close at the open, the session from the open to the close, so
  a weekend move lands on Monday's open. The expense ratio and any tracking
  difference are in the ETF's prices.

The leg's P&L per UTC day is the weight times the asset's move over each
piece of the day (crypto: Binance 1-minute prices at 00:00 and 04:15 UTC; ETF:
the official open and close inside that UTC day), weights as a share of book
equity (the intraday drift of that share is ignored for both). Before an ETF
existed the leg is filled as A in both, so the difference is zero there.

**D** = book with B legs minus book with A legs, per UTC day = leg P&L (B) -
leg P&L (A) - costs (B) + costs (A). Judged from 2024-01-11 to the data end
(expected 2026-10-14).

## Reported per book

D's annual mean in bps of book equity, split into the fee saved (turnover x
cost difference) and the rest (timing, weekend gap, tracking); D's Sharpe
(x sqrt 365) and its stationary bootstrap band (mean block 20 days, 4,000
draws, seed 20261021, 5 % and 95 %); D per year; the book's Sharpe and
drawdown both ways; the share of turnover in BTC and ETH; the ETF's tracking
error against spot (the ETF's close-to-close return against Binance's
1-minute price at the same 16:00 New York close, standard deviation x
sqrt 252) and its mean shortfall a year.

## Trials (4)

D for each of the four books.

## Pass rule (per book)

1. D's annual mean above 0 and the bootstrap 5 % bound of D's Sharpe above 0
   at the base costs (A 35 bps, B 2 bps);
2. D's annual mean still above 0 with B at 5 bps and A at 25 bps (taker only);
3. the ETF legs' tracking error against spot below 2 % a year;
4. D not negative in any calendar year (2024, 2025, 2026 to date).

## Kill rule

D's annual mean at or below 0 at the base costs.

## If it passes

A design note for an engine routing option (`docs/ETF-ROUTING.md`): which
legs, when the router fills, how a weekend decision waits, how the paper and
live accounts would see it, what it saves per book. The engine is not
changed. No new lab book: the books stay what they are, only their fills move.

## What could fool us

- The official open is not a fill. The engine trades a few minutes into the
  session; the stress cost (5 bps a side) stands for that.
- The weight drift inside a day is ignored for both ways, so D carries a
  small error of second order (weight change times return change).
- The window is short (2.8 years for BTC, 2.2 for ETH) and the ETFs' early
  spreads were wider than today's.

## Changes to the survey's sketch

- The survey's fill at the 09:35 Alpaca 5-minute bar needs Alpaca's bar API,
  which is not reachable from the PC for these symbols; the official open
  plus a stress cost replaces it.
- btc_gated is added as a fourth book (it runs as a paper experiment and is
  all BTC); trend4h_pullback is left out.
- The tracking-error rule is measured against Binance at the same 16:00 New
  York minute rather than a reference rate.
