# Buying after a market-wide deleveraging flush (survey O5): pre-registration

Registered 2026-10-21 and committed before any return below was computed.
Sketch: original idea O5 of `proposals/2026-10-21-strategy-survey.md`. Before
this file was written, only event counts were computed (how many days meet
each candidate definition per year), never a return after an event; the
counts are below and fixed the thresholds. Code: `lab.experiments.flush_long`
(written after this file). Results go to `results/flush_long.md`. Nothing
here may change once a result exists. Registered together with
`funding_carry`, `trend_shorts` and `kraken_funding_gap` (37 trials in all).

## Question

After a day on which open interest across the major perpetuals collapses,
funding turns negative and BTC has fallen hard, does buying BTC or a basket of
the most liquid coins for a few days beat random entries in the same month
and BTC regime, after perp costs and funding?

## Mechanism

When open interest falls with the price and funding turns negative, forced
sellers (liquidated longs) are done and the leverage market has reset; the
price impact of the forced selling should partly reverse. The lab used OI,
funding and the long/short ratio only as reasons to cut exposure
(`flow_overlays`), never as an entry.

## Data

- Binance USD-M metrics for the 20 coins the lake holds them for (5-minute
  open interest in contracts, 2022-01 to 2026-10-19), USD-M daily closes and
  funding.
- The sweep's survivorship-free daily panel (`fam_common`, the same rebuild
  as `trend_shorts`, cut at 2026-10-19) for the returns, the perp funding a
  long pays, the 5 most liquid coins with a live perp and BTC's 200-day
  state.

## The event (day d, everything known at its end)

- **OI collapse**: the 3-day change of open interest at constant prices,
  sum over coins of (contracts at the end of d minus contracts at the end of
  d-3) x the perp close of d-3, over the sum of contracts at d-3 x that
  close, at most minus X; at least 15 of the 20 coins present.
- **Negative funding**: the equal-weight mean over those coins of the
  funding settled during day d is below 0.
- **Large drop**: BTC's perp close-to-close return over the 3 days to d at
  most -5 %.
- **One event per flush**: a qualifying day within 6 days after a counted
  event is not counted.

X: 3 % or 5 %. Counted before registration (events per year 2022 / 2023 /
2024 / 2025 / 2026): X = 3 %: 7 / 4 / 5 / 3 / 4, 23 in all, 12 out of sample;
X = 5 %: 6 / 3 / 3 / 1 / 2, 15 in all, 6 out of sample. X = 10 % (3 / 2 / 2
/ 1 / 1, 4 out of sample) and 15 % (1 to 2 a year) were dropped as too rare
to judge; dropping the funding condition adds 0 to 2 events a year.

## The trade

Enter at the close of day d (the sweep's convention: decided and filled at
the decision close), exit at the close of d+H.

- Instrument: the BTC perpetual, or an equal-weight basket of the 5 most
  liquid coins with a live perp at the close of d (bought once, not
  rebalanced).
- H: 3 or 7 days.

Return per event: the price return minus the funding a long pays over the
hold minus costs.

## Costs

- **Judged: 10 bps a side** (Kraken Futures taker plus half-spread, see
  `funding_carry_prereg.md`) plus funding.
- Reported: Alpaca spot at 35 bps a side, no funding (the "long spot" form);
  20 bps a side; 0 bps.

## The baseline

For each event, every day in the same calendar month (year and month) with
the same BTC 200-day state at its close, not within the 7 days after any
counted event of the same definition, entered and held the same way, same
costs. Excess = the event's return minus the mean return of its matched
days. Also: the share of 4,000 random entry sets (one matched day drawn per
event, seed 20261021) whose mean return reaches the events' mean.

## Windows and the pick

In sample: events from 2022-01-04 to 2023-12-31; out of sample: events from
2024-01-01 whose exit falls on or before 2026-10-19. The pick is the variant
with the highest in-sample mean excess at 10 bps among the 8.

## Trials (8)

X {3 %, 5 %} x instrument {BTC, top-5 basket} x H {3, 7} = 8.

**Pool: 1,777** (see `funding_carry_prereg.md`). For deflation each variant
is also a daily book (in the position for H days after each event, cash
otherwise, judged costs and funding).

## Pass rule (all, for the pick, out of sample)

1. At least 6 events (fewer: "too few events to judge", whatever the mean).
2. Mean excess over the matched baseline above 0 at 10 bps.
3. The 5 % bound of an event bootstrap of the mean excess (4,000 draws, seed
   20261021) above 0.
4. Entered one close late (the close of d+1, held H days), mean excess still
   above 0.
5. Mean excess still above 0 at Alpaca spot costs (35 bps a side).

Confirmed only if the pick's daily book has a deflated p above 0.95 over the
pool.

## Kill rule

Out-of-sample mean excess at or below 0 at 10 bps: a flush is not a buy
signal in this data.

## If it passes

A lab paper book `flush_long` (long the pick's instrument for H days after
an event, cash otherwise) with signed weights for the perps demo route,
experimental unless confirmed, and a job, disabled. Nothing is deployed.

## Reported, not judged

Every variant in and out of sample: events, mean return, mean matched
return, mean excess, hit rate against the baseline, the funding earned or
paid (after a flush funding is negative, so a long is often paid to hold),
each event listed with its date, OI change, funding, BTC drop and returns.

## What could fool us

A dozen events out of sample is a small sample: one crash that keeps falling
(as in June 2022) can decide it either way, which is why the event bootstrap
is a gate and every event is listed. Entries at the decision close are
slightly optimistic; the late-entry gate checks it. OI history starts in
2022, so the selection window is two years with about ten events.

## Changes to the sketch

- OI change at constant prices (contracts), not in USD: an OI drop in USD is
  mostly the price drop itself.
- X 3 or 5 % over 3 days (not 15 or 25 %, which happen once or twice a year
  on this measure); the drop is a 5 % fall of BTC over the same 3 days; the
  long/short ratio is replaced by negative funding, as the owner's brief
  asks; holds 3 and 7 days (short holds), not 7 and 14.
- Judged at perp costs (10 bps a side plus funding), with Alpaca spot as a
  gate at 35 bps.
- Pool 1,777.
