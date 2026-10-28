# W1: one weekly page of what matters, pre-registration

Pre-registered 2026-10-28, before the page's first run. From the training plan of 2026-10-28 (review
`results/review_2026-10-27.md`, sections 2 and 3; R5's registry; R6's windows).

## What it is

`lab.ops.weekly`, Sunday 18:00 UTC: one page in German, at most about 40 lines, in `<data>/reports/weekly/<date>.md`
and `latest.md`, a short version through `lab.ops.notify` (category "studies"). It reads only reports that exist
and names the file behind every line; a missing report is a line "fehlt: <file>". It never arms, changes or sends
anything but the page.

Sources: `reports/ladder/latest.json` (steps, the registry's count and noise bar), `reports/pumpfun_rt/realistic.json`
(the calibration line, P2's gap, R2's and P3's books), `reports/pumpfun_rt/live_status.json` and `live_trades.json`
(the live bot's P&L), `reports/paper_review/latest.json`, the paper books (`lab.ops.paper_books`),
`reports/lanes/*.json` of the week, `_health/jobs.json`, `_ops/disk/latest.json`. With no ladder report the
registry's count and bar come from `metrics.trial_pool()` (`trials/registry.jsonl`).

## The only arithmetic it does

- A week is the 7 days up to the run. Moves on the ladder, the books' week, the live bot's week and jobs green again
  are the difference to the page's own snapshot of the week before (`reports/weekly/<date>.json`); without one the
  page says so. The live bot's week without a snapshot: the sum of `pnl_sol` of the report's trades closed in the week.
- SOL in EUR at `realistic.json`'s `sol_eur`; USDC and % books are not converted.
- The owner's goal, 180 EUR net profit a month: a week's P&L times 30/7 is "a month"; the distance is 180 less that.
- A candidate's monthly net return: its paper book's return since its start times 30 over its days (simple, not
  compounded), paper only (no candidate on the ladder has a live record yet). The capital it would need is 180 EUR
  over that return; none when the return is not above zero or under one day old.

## Trials

None. The page tests nothing, picks nothing among variants and measures no new statistic: it restates the reports'
numbers and the arithmetic above. R5's registry does not change. Plain numbers, no advice.
