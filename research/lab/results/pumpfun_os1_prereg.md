# OS1: a least-squares Monte Carlo exit and a conditional GPD crash exit for P_pool0: pre-registration (2026-10-29)

Written and committed before any replay, state, model or exit below was computed. Code (next commit):
`lab/pumpfun_rt/os1.py` (the replay, the states, both models, the exits, the evaluation), tests `tests/test_pumpfun_os1.py`.
Paper only: nothing here holds a wallet, reads a key, signs or sends anything; the live service, its executor, its
exits, its sizing, its confirmation file and everything in `denied.re` are not touched; the live executor's files are
only read through the latencies below, never a key or the wallet. A change to anything below after the first result
is a new trial with a new name.

## Why

The owner asked (2026-10-29) for our own algorithms from first principles, tested on paper. X14 r2
(`results/pumpfun_flow_exit_x14r2.md`) found that no reactive order-flow exit beats P_pool0's exits (+30 % take,
-20 % stop, 300 s) and that 72 % of the stops are one pool transaction; its hazard exit ranked dumps (AUC 0.74 to 0.79)
but sold too often. Two models that treat the exit as a decision under uncertainty, not as a classifier with a hand
threshold:

- **E1, optimal stopping** (Longstaff and Schwartz 2001): the value of holding, V(t, s) = max(sell now, E[V(t + dt, s')]),
  where selling takes effect one measured latency later; solved by least-squares Monte Carlo on the recorded paths of
  earlier days.
- **E2, tail model** (McNeil and Frey 2000): peaks over threshold, a generalised Pareto distribution for the largest
  fall in the 10 s after the latency, its scale a function of the state (conditional EVT, pooled across coins); exit when
  P(fall > 30 %) is above a level fitted in sample.

Against 12007's best exit: none of X14 r2's exits passed, so the only base is P_pool0 as it is (X0).

## What was looked at before this plan

Disclosed: X14 r2's and E2's pre-registrations, reports and code (`flowexit.py`, `entry_e2.py`), the review of
2026-10-27 (sections 2 and 3), `metrics.py`, `ops/ladder.py` and `pumpfun_rt/factory.py` (R7's per-entry deflation).
Nothing else: no state, label, model, exit or book of this plan was computed on the record.

## 1. Record, latency, entries (E2's, unchanged)

- **Record**: every recorded UTC day from the start (2026-10-20 16:40 UTC) to E2's cutoff **2026-10-29 19:30 UTC**;
  P_pool0 signals until 19:20 UTC (10 minutes before), so every position closes inside the record. **In sample**: the
  UTC days 2026-10-20 to 23; **out of sample**: 2026-10-24 to the cutoff (6 days). R6's windows are for market data;
  the pump.fun record lies inside R6's lockbox period, so as every pump.fun study since R6 the split is by UTC day
  inside the record.
- **Latency** (judged, the only scenario): E2's, `entry_e2.costs()`: Y5's kernel density in log space of the live
  executor's 34 P_pool0 buys and 34 sales from 2026-10-29 00:00 UTC to 19:30 UTC, clipped to 0.2 to 60 s, the mean fee
  of 108,938 lamports a transaction. L, the latency a model's sale is assumed to take, is the median of the clipped
  sale points (as X14 r2's L).
- **Entries**: X14 r2's full replay (`flowexit.FlowPipe`, `EveryEntry`): every P_pool0 signal at 0.05 SOL, no book
  limit, the buy one draw of the buy latency after the signal; for every filled entry the pool's path (every pool trade
  from the signal to the landing + 480 s with the pool's state after it, side, size, signer, the grouped early wallets'
  dump-at-risk and the inferred BOOST buyer's last buy). X0 is P_pool0 on these paths (`flowexit.simulate`, which
  matched the pipeline's own P_pool0 on 100.0 % of X14 r2's entries). Every exit is judged **paired by entry**, the same
  sale draws per entry and leg (key P_pool0, mint, sell).

## 2. The state at a decision time g (only the path up to g)

- `r`: the log of the net sale value of all the position's tokens at g over its cost (the mark), clipped to -3 and
  log 1.3;
- `sell bucket`: the pool's sales in (g - 10 s, g], counted from the path: 0, 1 to 2, 3 to 5, 6 or more (three dummies);
- `dar`: the grouped early wallets' dump-at-risk at g (X14 r2's DaR, 1 - (x / (x + H))^2; missing as 0);
- `bb`: 1 while the buyback runs (the inferred buyer seen and its last buy within 45 s of g), else 0;
- `age`: (g - landing) / 300 s.

## 3. E1: least-squares Monte Carlo (one trial)

- **Exits**: the +30 % take and the 300 s time stop stay as caps, exactly as P_pool0's (a take that would land under
  `TP_FLOOR` of its expected proceeds fails and stays due); the -20 % stop is replaced by the stopping rule. Decisions at
  g_k = landing + 5 k s, k = 1 to 59.
- **Payoffs** (fractions of the cost, every sale the same fee): selling at g is worth P(g) = the value at g + L over
  the cost, minus 1; the caps' cash flow is the value at the take point + L, or at the landing + 300 s + L.
- **Backward induction** (Longstaff and Schwartz, no discounting): every training path starts with its caps' cash flow
  CF. For k = 59 down to 1, over the paths still open at g_k (no take before g_k): a ridge regression of
  CF - P(g_k) on the basis of the state at g_k; the paths whose fitted value is below 0 exercise (CF = P(g_k)). The
  sale is not known at g (it lands L later), so the rule compares two expectations: sell when the fitted continuation
  minus the fitted sale is below 0. Basis: 1, r, r^2, r^3, dar, dar r, bb, bb r, the three sell dummies and r times
  each (13 columns; the age is the regression's k). Ridge: 1e-3 times the rows, the columns but the constant
  standardised on the training rows. A k with fewer than 100 open training paths has no fit: hold.
- **Walk-forward by UTC day**: the regressions for day d come from the filled entries of the days before d whose
  landing + 300 s + L + 10 s is before d starts; d's entries are run with them. A day without any fit is X0's trade
  (this is the first day at least).
- **Out of sample**: at each g_k of an open position, the state from the path up to g_k, sell at g_k when the fitted
  value is below 0; the sale lands one draw of the sale latency later at the state then.

## 4. E2: conditional peaks over threshold (one trial)

- **Label** at a time g: F(g), the largest fall of the position's net value in (g + L, g + L + 10 s] relative to the
  value at g + L (0 to 1; no label when that value is 0). Rows: g = landing + 1, 2, ..., 299 s of every filled
  entry.
- **Model per walk-forward day d** (training rows: the days before d, label windows ending before d starts; at least
  2,000 rows and 100 exceedances, else no model that day): the threshold u = the training rows' 90 % quantile of F,
  at most 0.20. P(F > u | z) by a logistic regression (L2 1e-3) on z = (r, the three sell dummies, dar, bb, age),
  standardised on the training rows; the exceedances F - u by a generalised Pareto distribution with
  sigma(z) = exp(c0 + c z) and one shape xi (bounded to -0.95 to 0.95), by maximum likelihood, pooled across coins.
  P(F > 0.30 | z) = P(F > u | z) (1 + xi (0.30 - u) / sigma(z))^(-1 / xi) (the exponential at xi 0, 0 past the
  distribution's end).
- **Exit**: P_pool0 as it is (take, stop, time stop) plus a sale at the first g (every 1 s from the landing + 1 s)
  where P(F > 0.30 | z) is above lambda; the sale lands one draw of the sale latency later.
- **lambda fitted in sample**: lambda in 0.02, 0.05, 0.10, 0.20, 0.30, 0.50; the value with the highest mean per
  entry over the in-sample entries (days with a model; ties the earlier).
- **Calibration** (reported, out of sample rows): the Brier score of P(F > 0.30) against a constant hazard (the training
  rows' rate of F > 0.30, per day), its skill 1 - B / B0, the AUC, a table of five bins by the predicted probability.
- **Expected shortfall** (reported): at the 95 % level, the model's VaR = u + sigma / xi (((0.05) / P(F > u))^(-xi) - 1)
  and ES = (VaR + sigma - xi u) / (1 - xi) where P(F > u) is above 0.05. (a) The backtest on the out-of-sample rows: the
  share of rows with F above VaR (5 % expected) and on those the mean F against the mean ES. (b) X0's out-of-sample
  stops: at the last second g before the stop's signal, the model's ES and P(F > 0.30) against what the stop really
  lost, 1 - the value at the stop's landing over the value at g + L (the stop's landing can be more than 10 s after g:
  disclosed in the table).

## 5. Verdict

Judged out of sample, paired by entry against X0, at the live latency. An exit **passes** only if all three hold:

1. its mean return per entry (after every cost, failed buys included, the same in both) is higher than X0's on the same
   entries;
2. the day-block bootstrap 90 % band of the paired difference (whole UTC days resampled, 5,000 draws, seed 11,
   `flowexit.day_band`) lies above 0; with fewer than 5 out-of-sample days, n/a and no;
3. deflated by the registry: the Sharpe of the paired per-entry differences, on its effective entries clustered by day
   (`factory.by_day`), deflated (`factory.deflated`, as the ladder's pump.fun rows) with F3's per-entry Sharpes as the
   noise and n = every trial in R5's registry (these two included) plus F3's trials, is at least 0.95. Without F3's
   ledger no DSR: no pass.

If both pass, the higher out-of-sample mean is the pick. Trades open across a gap in the record are kept; without
them, a robustness line.

## 6. Reported (not judged)

Per exit, out of sample and in sample: entries, mean, median, win rate, total P&L (SOL), the exits by kind, the
stops' or losses' mean, the paired difference and its band, the DSR. E1: how many of its exercises were above and below
the entry, the share of days and k with a fit. E2: u, xi and the days with a model, the in-sample lambda grid.
**Books at two sizings** (`flowexit.book`, `pipeline.Risk`): the live one, **0.05 SOL, 1 open, 0.12 SOL a day**, and
**0.1 SOL, 4 open, 1.0 SOL a day**; entries, mean, P&L, maximum drawdown.

## 7. Trials

In R5's registry, family pumpfun, before the first number (`os1.trials()`): `pumpfun:os1:E1` and `pumpfun:os1:E2`
(the calibration and the shortfall are E2's report). The lab's data folder is read only where this first run is made:
the run registers into a copy of the registry and the server's registry gets the same 2 lines by
`python -m lab.pumpfun_rt.os1 --register-only` (one line per id, never twice).

## 8. If one passes

It becomes a paper shadow next to P_pool0 (PAPER ONLY); the live bot, its exits, its files and everything in
`denied.re` stay unchanged; whether it goes live is the owner's call after the shadow. If none passes, nothing is added.

## 9. Too early, in any case

Nine days of record, six out of sample, a latency from 34 live sales. A pass here is a reason for a shadow, not for
money.
