# Intraday time-series momentum in BTC, ETH and the top-10 perps: pre-registration

Registered 2026-10-21 and committed before any return below was computed.
Code: `lab.experiments.intraday_tsmom` (written after this file). Results go
to `results/intraday_tsmom.md`. Nothing here may change once a result
exists. Registered together with `perps_neutral_portfolio` and
`attention_wiki` (25 trials in all).

## Question

Gao, Han, Li and Zhou (2018) found that the S&P 500's first half hour
predicts its last half hour. Several 2020 to 2023 papers report the crypto
version: the return over most of the UTC day predicts the last hour or two.
Does the return from the UTC day start (or over the previous 24 hours) up to
22:00 UTC predict the return to 24:00 in BTC, ETH and the ten most liquid
perps, and does trading it pay after perp costs?

## Data

- Binance spot hourly bars (`hist/binance_spot/klines_1h`, segmented by
  `picks.hourly_segments`), 2020-01-01 to 2026-10-20. Prices are spot; the
  trade would be on perps (basis ignored). The position is closed before the
  00:00 funding settlement, so no funding is booked.
- Top 10: each day the 10 coins with the highest 28-day volume among
  eligible coins with a live USDT perp at the previous close
  (`fam_common.Panel.top_liquid(10, need_perp=True)`, survivorship-free),
  equal weight, each coin traded on its own signal.
- Minute bars (`hist/binance_spot/klines_1m`, 20 coins) only for the
  late-entry check.

Prices for UTC day D: P0 the close of the 23:00 bar of D-1 (00:00 of D),
P22 the close of the 21:00 bar (22:00), P23 the close of the 22:00 bar,
P24 the close of the 23:00 bar of D. A day with any of the needed bars
missing is not traded for that coin.

## Rules (position = sign of the signal, size 1, flat otherwise)

- **A, day start to 22:00**: signal P22 / P0 - 1, held 22:00 to 24:00.
- **B, previous 24 hours**: signal P22(D) / P22(D-1) - 1, held 22:00 to 24:00.
- **C, day start to 23:00**: signal P23 / P0 - 1, held 23:00 to 24:00.

Every traded day costs a round trip (enter and exit): 2 x cost per unit
traded.

## Costs (per side)

- **Judged: taker.** BTC and ETH 5 bps (perp taker fee; both quote one tick,
  under 0.5 bps); top 10 10 bps (`perps_common.JUDGED`, taker plus
  half-spread).
- Maker: 2 bps for all (maker fee, every order filled, no adverse
  selection; an upper bound).
- 0 bps reported to show the predictability before costs.

## Trials (9)

3 rules x 3 assets (BTC, ETH, top 10). The pick per asset: the rule with the
highest in-sample Sharpe at the judged cost, 2020-01-01 to 2023-12-31 (top 10
from 2020-02, when 28-day volume exists). Out of sample from 2024-01-01.

**Pool.** 1,328 hand trials before this registration (see
`perps_neutral_portfolio_prereg.md`), the factory ledger as read at run
time, and the 25 trials registered together. Daily returns, flat days
included as zero, annualised with 365.

## Pass rule (all, per asset's pick, out of sample)

1. Sharpe above 0.5 at the taker cost.
2. Positive in at least 2 of 2024, 2025, 2026 at the taker cost.
3. Entered five minutes late (the 22:05 or 23:05 minute close; the top 10
   only for the coins with minute bars) still above 0 at the taker cost.
4. The 5 % bound of a stationary bootstrap of the Sharpe at the taker cost
   (mean block 20 days, 4,000 draws, seed 20261021) above 0.

Confirmed only with a deflated p above 0.95 over the pool. Kill: the pick's
out-of-sample Sharpe at 0 bps at or below 0 (no predictability even before
costs).

## If something passes

A lab paper book under `lab/paper/` marked EXPERIMENT and a job added
disabled. Nothing wired into an autopilot.

## Reported, not judged

All 9 trials at 0, 2 and taker cost, in and out of sample, per year; the
slope of the held return on the signal with a Newey-West t (BTC, ETH, and
the basket's pooled coin-days); hit rate; the mean held return per traded
day in bps against the round-trip cost; "always long in the last hours"
(the hour-of-day drift) as a control; the five-minute-late numbers.

## What could fool us

The last two hours of the UTC day hold the US afternoon; a drift there, or
the funding settlement at 00:00, can look like momentum. A two-hour hold
earns a few basis points at best against 10 to 20 bps of round trip, so
costs decide; the maker level assumes fills that a resting order gets only
when the price comes to it (`fast_maker` measured that as a cost of its own).
The day boundary is arbitrary for a market that never closes.
