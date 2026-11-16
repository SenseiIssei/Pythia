# pump.fun realistic model: the fit on the last live orders of any age

Pre-registration `results/pumpfun_realistic_fit_window_prereg.md`. Replay of the record's days 2026-10-24 to 2026-11-15 (`pool_fix.replay`, the engine as the shadow builds it, `fresh_pool` on as the shadow runs since the pool state fix, the realistic executor, the live sizing settings of the run's day), signals from 2026-10-24 01:43 UTC (the ladder's window) to 2026-11-15 24:00 UTC, entries until 15 minutes before the end; once on the fixed fallback, once on the new fit. The replay runs today's engine, so P1's late-row bug does not arise in it. Entries: closed trades and failed buys (a failed buy its fee over the book's median stake). Band: R7's 95 % band clustered by UTC day. Points: new less fallback. Three trials in R5's registry, family pumpfun, counted only (`pumpfun:fit_window:*`); no Sharpe, no DSR.

## The new fit

The newest 50 live orders per field, of any age, at 2026-11-16 14:38 UTC:

| what | model | source | orders | newest order |
|---|---|---|---|---|
| buy, signal to landing | 1.5 s (10 to 90 %: 0.6 s to 4.8 s) | live | 50 | 2026-10-30 01:12 UTC, 17.6 days old |
| sale, decision to landing | 0.5 s (10 to 90 %: 0.0 s to 1.8 s) | live | 50 | 2026-10-30 01:14 UTC, 17.6 days old |
| buy, send to landing | 0.6 s (10 to 90 %: 0.0 s to 0.9 s) | live | 50 | 2026-10-30 01:12 UTC, 17.6 days old |
| network fee per transaction | 0.000059 SOL | live | 50 | 2026-10-30 01:14 UTC, 17.6 days old |
| buy failures drawn per buy | none | live | 50 | 2026-10-30 01:12 UTC, 17.6 days old |

The fallback: buy 9.8 s, sale 3.9 s, send 0.5 s median (lognormal), fee 0.000215 SOL, not landed 3.0 %.

## Sensitivity

| book | entries, fallback | mean, fallback | band, fallback | entries, new fit | mean, new fit | band, new fit | points |
|---|---|---|---|---|---|---|---|
| P_pool0 | 2573 | +1.9 % | -0.1 % to +3.8 % | 2651 | +6.1 % | +3.8 % to +8.5 % | +4.3 |
| P_pool0_wait | 3147 | +0.7 % | -0.7 % to +2.1 % | 3291 | +3.9 % | +1.9 % to +5.9 % | +3.2 |

## The receive lag: once or twice

Paper ledger, P_pool0, P_pool0_wait from the ladder's window (P1's tainted rows and restarts out), 6194 rows: land less signal less the drawn latency p10 0.1 s, median 0.9 s, p90 2.0 s, max 2.0 s; 5978 of 6194 within 0 to 2 s (the wait for the next recorded trade), 216 below 0, 0 above. Live buys with a receive time (128): received a median 0.5 s after their signal time (p90 2.8 s), signal to landing median 2.2 s.


Verdict: once, not twice; nothing fixed.

- The clock. The shadow (`collector.SlotClock`) and the replay (`sim.day_events`) time every row at its slot's first
  receive time by the recorder, so that clock carries the recorder's lag behind block (coverage.md, 10 to 15 s
  median). The signal is set on it (`signal_ms`), the landing is `signal_ms` plus the drawn latency
  (`pipeline.PaperExecutor.buy`, `sim.Engine.push`), and the fill is the first recorded trade at or after the
  landing on the same clock. The lag moves the signal and the trades a landing fills on alike: it is in paper's
  clock, not in its signal to landing. The ledger agrees: no row holds more than the draw and the wait for the next
  trade.
- The draw. The live bot's `signal_ms` is its own stream's slot clock, and `lat_ms` runs from there to the landing:
  its own receive after that clock (median 0.5 s), building, sending and landing. That receive part is the one
  receive lag in paper's signal to landing; the recorder's lag is not added on top.
- The 216 rows below 0 filled on a trade stamped before the landing (a pool trade handed over late keeps its slot
  time): less time, not more. Not studied here.
- Not measurable here: the live bot's own lag behind block before its slot clock (`measured.jsonl` has no block time
  of the signal). It is the same lag paper's clock cancels, so it would matter only if the live bot reacted later in
  chain time than its clock says.

## What it means

- The fallback (buy 9.8 s, fee 0.000215 SOL, 3 % not landed) made the paper books slower and dearer than the live
  bot was since 2026-10-24. On the live bot's newest 50 orders, P_pool0 makes +6.1 % per entry (band +3.8 to +8.5 %)
  against +1.9 %, and P_pool0_wait +3.9 % (band +1.9 to +5.9 %) against +0.7 %: +4.3 and +3.2 points. Both bands
  are above 0 on the new fit; on the fallback both reach below 0. The points mix latency, fee and failures (none
  drawn against 3 %); they are not split.
- Limits: the newest live order is 17.6 days old (2026-10-30), from the live bot's feed and settings of then; 50
  orders a field; the engine's models and the fit are today's, so the levels are not out of sample, only the
  difference is the fit. The pool state fix's result is not written yet: both runs use its engine (`fresh_pool`
  on), so these are the restated series.
- From the deploy the daily job fits this way and `realistic.md` shows source, count and newest order per field.
  The calibration line keeps its 7 days and stays at 0 pairs while the live bot is idle. No live bot code, sizing,
  wallet or setting changed; the ladder reads the paper ledger as before (its rows from the deploy carry the new
  fit).
