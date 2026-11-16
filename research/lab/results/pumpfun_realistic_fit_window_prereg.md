# pump.fun realistic model: the fit on the last live orders of any age. Pre-registration

Registered 2026-11-16 and committed before any number of this study was computed. On the review of 2026-10-27
(`results/review_2026-10-27.md`, sections 2 and 3), R5's registry (`metrics.trial_pool`,
`<data>/trials/registry.jsonl`), R6's windows (in sample to 2023-12-31, validation 2024-01-01 to 2026-06-30, lockbox
from 2026-07-01; this study lies wholly in the lockbox era of the pump.fun record and makes no lockbox look, it
compares two cost models on the same signals), R7's band (`factory.by_day`, as `lab.ops.ladder` reads it), P1's taint
rule (`realistic.tainted`), the pool state fix (`results/pumpfun_pool_state_fix_prereg.md`, its code landed in
60f30a9, its restated series not yet written) and the readiness ladder (`lab.ops.ladder`). Paper only: nothing a live
bot, its rules, sizing, wallet, keys or caps read changes.

Numbers seen before this file: `reports/pumpfun_rt/realistic.md` of 2026-11-16 (every field on the fallback, 0 buys
and 0 sales in the 7 days); `<data>/live/pumpfun_rt/measured.jsonl` read to choose N: 184 buy fills and 183 sale fills
from 2026-10-22 to 2026-10-30 01:14 UTC, 364 fee rows, 15 failed buys; buy signal to landing by day median 8.8 s
(10-22), 8.6 s (10-23), 2.2 s (10-24), 1.4 s (10-29), 2.5 s (10-30); the newest 30 buys median 1.6 s (from 10-29
14:27), the newest 50 median 1.5 s (from 10-24 05:46); sales median 0.6 s; coverage.md's clock offset (receive less
block, 10 to 15 s median); the paper ledger's land less signal of P_pool0 and P_pool0_wait since 2026-11-14 (median
9.7 s, the fallback's draw) and that it exceeds the drawn latency by 0 to 2 s. No replay of this study was run.

## The rule

`realistic.fit` takes, per field, the newest N = 50 live orders of any age (mode test or full, at or before the
fit's time, ordered by their time `t`):

- buy, signal to landing: the newest 50 buy fills' `lat_ms`;
- sale, decision to landing: the newest 50 sale fills' `lat_ms`;
- buy, send to landing: the newest 50 buy fills with a `send_to_land_ms`;
- network fee per transaction: the median of the newest 50 fee rows;
- buy failures drawn per buy: the newest 50 buy orders (fills and failed buys, refusals out), each kind's count over
  50, 6040 reported and not drawn as today; each kind's fee the median of its failures among them.

A field with fewer than 50 such orders takes the fixed fallback (as today's FALLBACK, FALLBACK_FEE_L,
FALLBACK_FAIL). N is fixed here and not tuned on the result. Each field states its source (live or fallback), its
count and the time and age of its newest order; `realistic.md` shows them per field and says "the newest 50 live
orders per field, of any age". The daily job, R1, the factory, R2's and E1's callers take the new rule; the live twin
keeps its leave-one-day-out window (`fit(..., days=...)`, all orders in the window, at least MIN_ORDERS, unchanged).

## The sensitivity measure

Two replays through `pool_fix.replay` (the engine as the shadow builds it, `fresh_pool` on, as the shadow runs since
the pool state fix), identical but for the fit: before, the fallback (`Fit()`); after, the new rule on
`measured.jsonl` at the run. The same live sizing settings (`LiveConfig` of the run's day) in both. The ladder's
window: signals from 2026-10-24 01:43 UTC (`ladder.PF_REAL_FROM_MS`) to 2026-11-15 24:00 UTC, entries until 15
minutes before the end. P1's cut: the replay runs today's engine, so the late-row bug does not arise; restarts out as
the ladder. Per book P_pool0 and P_pool0_wait (realistic, the live sizing on a 0.55 SOL paper wallet): entries
(closed trades and failed buys, a failed buy its fee over the book's median stake, as `ladder.pf_entries`), the mean
per entry and R7's 95 % band clustered by UTC day, under the fallback and under the new fit, and the change in points
(new less fallback). No pass or fail: the rule ships either way, it changes no live setting.

## The receive lag

The question: is the recorder's own receive lag (coverage.md, 10 to 15 s median behind block) counted once or twice
in paper's signal to landing? Checked three ways: (1) the code path (the clock of the shadow and of `sim.day_events`,
where `signal_ms` and the landing are set, which trades a landing fills on); (2) on the paper ledger, P_pool0 and
P_pool0_wait rows from the ladder's window with `lat_buy_ms`: land less signal less the drawn latency (if the lag is
not added, this is only the wait for the next recorded trade, 0 to FILL_WAIT_MS); (3) on `measured.jsonl`, what the
live bot's `lat_ms` spans (`recv_ms` less `signal_ms` where recorded). Twice means: paper adds a delay of the
recorder's lag on top of a drawn latency that already holds a receive lag. If so, the fix goes into
`realistic.py` (the paper side) and the replays above run with it; if not, the result says so and nothing changes.

## Trials

R5's registry, family pumpfun, counted only, no Sharpe, registered before the first number (through the registry
copy, `PYTHIA_TRIALS_REGISTRY`, and by `python -m lab.pumpfun_rt.realistic window`): `pumpfun:fit_window:P_pool0`
(n 2), `pumpfun:fit_window:P_pool0_wait` (n 2), `pumpfun:fit_window:recv_lag` (n 1). No DSR. Results in
`results/pumpfun_realistic_fit_window.md`.
