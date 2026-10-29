# pump.fun engine clock audit (2026-10-29): the replay check, pre-registration

Pre-registered 2026-10-29, before the replay's first run. From the training plan of 2026-10-28 (review
`results/review_2026-10-27.md`, sections 2 and 3; R5's registry; R6's windows) and the audit of 2026-10-29 on
d84b252 (the engine sees a row when it arrives).

## What changes

`lab/pumpfun_rt/sim.py`: the clock never runs backwards (`push` never before `now`, `advance` takes the max), a late
row is handled after every action due before the clock, its fills, exits and the actions it schedules are on the
clock while the token's state and the features keep its chain time; a gap row moves no clock; `day_events` never
times a pool read (`pool_state`) before its receive time. `collector.py`: metadata and pool reads are handed to the
books on the chain clock (the store keeps their receive time), the tap reader drains a rotated file, a failed
rotation keeps the tap open, the held pool trades go out once and with their signature. `tokens.py`: the creator
book's last time and a token's last trade time never go back. `early.py`: the 5 s snapshot is taken before the first
row past it when a coin's rows come late.

## The check

One recorded day, 2026-10-28 (the first day with pool reads in the store), replayed by `sim.replay` twice on the same
inputs: the code before the change (commit e068d83) and after. The engine: the registered rules (`strategies.RULES`)
and every pipeline strategy (`pipeline.STRATEGIES`) on the paper executor, default costs, the select and trend
trackers on, no warm-up, no model. Reported per book: closed trades, failed buys, the sum of P&L in SOL; the trades
that differ (rule, coin, signal, exit, P&L), each difference traced to its cause (a pool read timed at its answer,
a gap row that no longer moves the clock, an action no longer run before the clock).

What is expected: a replay feeds rows in chain order, so only the rows whose time the change moves (the day's pool
reads, the gap rows) can change a trade. Any other difference is a defect of the change and is fixed, not reported
as a result.

## Trials

None. The replay compares one engine with its corrected self on one day; it picks no rule, tunes no parameter and
judges no strategy, and its P&L sums are not a performance claim. R5's registry does not change. No live bot, wallet
or setting is touched by the check.
