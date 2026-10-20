# Audit of the forward records: do the paper books trade their backtests, and do their numbers add up?: pre-registration draft (2026-10-20)

*Draft by the research director (claude-opus-5-5, 2026-10-20). Nothing runs it. To start it, the owner fixes every number below before any result exists, commits it as the study's pre-registration in `results/` and counts its trials into the pool.*

## Question

Do all running paper books match their own backtest signals on at least 95 % of coin-days, sit above the 5th percentile of their backtest's same-length windows, and have every impossible figure explained?

## Why now

Forward evidence is the only out-of-sample data the lab has not yet seen, and the experiments write-up makes 90 forward days the route back for every failed rule. The Forward tests report marks tsmom (-6.3 %), tsmom_regime (-4.5 %) and tsmom_top20 (-4.4 %) as below. Several figures cannot be right. The long-only paper book pumpfun_migration shows -965.4 % (the pump.fun watcher shows -969.1 %). The stopped Alpaca demo Auto-Pick (main) shows a worst drawdown of 81.91 % against a P&L of -9.95 %, and fees of 0.73 % of capital against 0.05 % on the other autopilots. A demo account reports '15 real position(s) could not be closed' because live routing is not available. Several books read 'after 13 days since 2026-10-17' on 2026-10-20. ap_29742 shows -10.0 % in 3 days. The autopilots also log repeated venue quantity corrections. The weekly review's second proposal points the same way.

## Data

The paper books' daily positions and P&L and the autopilots' order and fill logs. The engine stores these, but the material does not name the table or file, so the owner has to locate them first. Backtest daily returns from 2024-01-01 come from each book's own module: fam_breakout.breakout_weights, fam_volmom.base_weights, tsmom_tranches.simulate, lab.experiments.fast_maker for trend4h_pullback, lab/paper/memes.py and lab/paper/m4_ls.py. Forward windows are 0 to 14 days long. Alpaca paper fills are simulated against Alpaca's quotes, so they measure spread and timing, not depth. Nothing else is missing.

## Design

Four checks; no new strategy is tested. (1) Signal reconciliation. For each book, recompute the target weights from its own weight function on the data available at each decision close of its forward period, and compare them with the positions actually held. A coin-day is a mismatch when the held weight differs from the target by more than 1 % of the book, or when the holding's sign differs. (2) Percentile. Place the book's forward cumulative return among all rolling windows of the same length in its out-of-sample backtest at 35 bps. Breakout and tsmom books use the Alpaca cash-left variants from alpaca_universe. (3) Realised cost. For every filled order, compare the fill price with the decision-close price in bps, and report the median and 90th percentile per coin. (4) Trace each impossible figure named in whyNow to its cause in code or data, and write it up. The comparison is the backtest itself.

## Trials (0)

- No Sharpe trial (reconciliation, percentiles and cost measurement only): 0

## Costs

Backtests at 35 bps per unit of one-way turnover, 70 bps as stress for the percentile check. Measured fill slippage is reported against the 10 bps that the 35 bps base assumes on top of the 25 bps taker fee.

## Pass rule

All of the following, for every book. Signal mismatch under 5 % of coin-days. Forward return above the 5th percentile of its same-length backtest windows at 35 bps. Median measured slippage of at most 10 bps on the daily books. Every impossible figure explained, with a fix committed. No deflated p applies, because no Sharpe trial is run.

## Kill rule

A book with a mismatch of 5 % or more, or with a forward return below the 1st percentile, has its forward record frozen and marked invalid. Its days then count toward no forward gate and no Real money readiness rule until the cause is fixed and a fresh record starts. If median measured slippage is above 20 bps, the 35 bps base is raised for every Alpaca study, and the running books are re-judged at the new cost.

## Effort

Under an hour of compute. Three to four hours of the owner's time, mostly spent finding the logs and tracing the impossible figures.

## What could fool us

With 3 to 14 forward days the percentile check has almost no power, and all books share BTC exposure. 'Inside the band' therefore means not yet distinguishable, not working. Alpaca paper fills are simulated against quotes and can look cheaper than real fills.

## Built on

`experiments`, `breakout_study`, `tsmom_tranches`, `alpaca_universe`, `m4_funding`, `fast_maker_5m`
