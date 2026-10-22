# P_pool0, Y5's least-bad rule as a pipeline strategy (Y6): pre-registration (2026-10-22)

Written and committed before the strategy traded once, on paper or live. Code:
`lab/pumpfun_rt/pipeline.py` (`_build_y6`). A change to anything below is a new
trial with a new name.

## Why

Y5 (`results/pumpfun_real_latency.md`) found no rule positive after costs at
the measured latency. The least-bad one, `E_d0_x1` (buy the PumpSwap pool at
the migration; +30 % take profit, -20 % stop, 300 s), lost 4.6 % a trade at a
0.03 SOL stake, band -6.5 % to -2.5 %. Two transactions at 0.001005 SOL each
are 6.7 % of 0.03 SOL but 2.0 % of 0.1 SOL, so before the fixed fees the rule
made about +2 % a trade. At 0.1 SOL that is about +0.1 % after them, band
roughly -1.8 % to +2.2 %: break-even, not an edge. The owner chose to run it,
on paper and in his capped live test, at 0.1 SOL a trade.

## The strategy

`P_pool0`: family E, entry at the migration (`delay_s` 0), the rule's exits and
nothing else: sell all at +30 %, stop at -20 %, time stop 300 s; no trail, no
dev-sell or pull exit, no model filter. Stake 0.1 SOL (`pipeline.HARD_STAKE_SOL`).
One trial (`strategies.POOL0_TRIALS`), counted in the global pool.

The live test's per-trade ceiling (`live_exec.TEST_MAX_TRADE_SOL`, and the
app's copy) goes from 0.05 to 0.1 SOL, the full mode's cap. Every other cap
stays.

## How it is judged

On the study's daily report (`pumpfun-rt-study`), the same readiness rule as
every pipeline strategy: 14 days, 300 trades out of sample, positive with and
without broken slots. Live trades are measured by the executor (latency,
slippage, fees, failed buys) and reconciled against the wallet (`chain_pnl`).

Stop rule, decided now: after 50 live trades, or once the live test's total
budget is spent, the owner gets the live mean per trade with its bootstrap
band and the paper book's mean over the same days. A live mean below -2 % a
trade with the band's top below zero means the strategy loses at this stake,
and the recommendation is to stop.
