# Breakout robustness study (pre-registration)

Written 2026-10-08 before any code of this study ran. The results section is
added below this one when the study has run; nothing in this section is
changed afterwards.

Subject: the sweep's Donchian breakout, 20/10 on the 10 most liquid coins of
each day, long-only, no regime filter, each entry sized to 40 % annual vol over
10 slots (`fam_breakout.breakout_weights`). Sweep result: out-of-sample Sharpe
1.20 at 15 bps, 1.08 at 41 bps, drawdown 22 %, deflated p 0.01 over 100
variants. The aim is to find out whether the edge is robust, not to tune it.

## Protocol

- Same survivorship-free daily panel as the sweep (a copy of its cached panel,
  591 segments, ending 2026-10-06), same simulator (`fam_common.simulate`),
  same split: in sample 2020-08 to 2023, out of sample from 2024-01-01.
- Every variant that produces its own return series is counted, also the ones
  that can only make the result worse (execution and cost stress tests).
- Costs per unit of one-way turnover, charged the next day as in the sweep.

## Questions and what will count as an answer

1. **Parameter neighbourhood.** Entry N in {10, 15, 20, 30, 40, 55}, exit N/2
   and N/3 (integer division), universe top 5 / 10 / 20 / 30 (slots = universe
   size): 48 configurations. Report the share positive at 41 bps and heat maps
   of the in-sample Sharpe (15 bps) and the out-of-sample Sharpe (41 bps).
   *Plateau* if the base's neighbours (one step in N, the other exit ratio,
   one step in universe size) have a median out-of-sample Sharpe at 41 bps of
   at least 0.75 times the base's and none is negative; otherwise *peak*.
   Also: which configuration the grid would pick in sample, and how that pick
   does out of sample.
2. **Stability over time.** Rolling 365-day Sharpe, Sharpe per calendar year
   2021 to 2026 (2021 to 2023 are in sample), and the BTC 200-day regime split.
   A year *carries* the result if dropping it halves the out-of-sample Sharpe.
3. **Dependence on a few trades.** Sharpe and CAGR with the best 1 % and 5 % of
   out-of-sample days removed, next to BTC buy-and-hold treated the same way
   (any trend book loses most of its Sharpe this way; the question is whether
   it loses more than the market). Share of out-of-sample P&L from the 10 best
   trades; P&L per coin and the Sharpe without each of the largest coins.
   *One-coin book* if a single coin makes more than 40 % of the P&L or its
   removal takes the Sharpe at 41 bps below 0.5.
4. **Costs and execution.** 15, 41 and 80 bps. Fills after the signal close
   from hourly bars: the next day's open, one hour, four hours and twelve hours
   after the close, and a full day late (the next close). Slippage on breakout
   days: spread estimated from hourly highs, lows and closes (Abdi and Ranaldo)
   in the hours around each entry against the coin's ordinary hours, charged on
   the entry turnover above the 5 bps half-spread the 15 bps model already has.
   *Fragile to execution* if any of these at 41 bps falls below half the
   base's Sharpe at 41 bps.
5. **Deflation for the question asked.** Deflated Sharpe over the original
   100-variant pool and over that pool plus every variant of this study, both
   with the sweep's rule (`fam_common.deflate`) and with an effective number of
   independent trials from the correlation of the trials' out-of-sample
   returns. Stationary bootstrap (Politis and Romano, mean block 20 days, also
   5 and 60 as a check, 10,000 draws) of the out-of-sample Sharpe at 15 and
   41 bps: 90 % and 95 % intervals and the share of draws above 0.
   *Robust* if the lower end of the 90 % interval at 41 bps is above 0.
6. **One improvement, tested once.** Volume confirmation: enter only when the
   breakout day's quote volume is at least 1.5 times the mean of the 20 days
   before it. Reasoning: a breakout that new money drives comes with
   participation; a breakout on thin volume is more often a drift through a
   level that reverts and costs a round trip. Base configuration otherwise.
   No other threshold is tried.

Recommendation rule: a different configuration is recommended only if it is
the grid's in-sample pick or sits in the middle of a plateau, AND beats the
base out of sample at 41 bps. Out-of-sample numbers alone never select. The
running paper book and the engine signal are not changed by this study.
