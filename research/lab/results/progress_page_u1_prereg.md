# U1: a progress page in the cockpit, pre-registration

Pre-registered 2026-10-28, before the page's first run. From the training plan of 2026-10-28 (review
`results/review_2026-10-27.md`, sections 2 and 3; R5's registry; R6's windows).

## What it is

`lab.ops.progress`, every 15 minutes: one JSON file `<data>/reports/progress/latest.json` for the app's page
`progress` (`?page=progress&embed=1` on the phone, also in the DevPanel). The server serves it unchanged as
`GET /api/lab/progress` with `found`, behind the same guard as the other lab routes, and computes nothing. It reads
only reports that exist and names the file behind every section; a missing report is `found: false` and the page says
"fehlt". It never arms, changes or sends anything.

Sections, in this order (how far Pythia is from real money):

- the readiness ladder (`reports/ladder/latest.json`): per candidate its step and what is missing next, the highest
  step first; the registry's count and noise bar as the ladder states them;
- P3's 10 EUR pump.fun books (`reports/pumpfun_rt/realistic.json`, `ten`): wallet, trades, mean and band, days and
  the gate; "nicht gestartet" while no book has started;
- paper minus live (the same file): the calibration line (`calibration`) and P2's gap (`selection`);
- the tsmom books' gate 7 (`reports/paper_review/latest.json`): days and rebalances against 30 and 30;
- the newest weekly page (`reports/weekly/latest.md`, W1), its first lines, once it exists.

## Age

Every section carries the time of its source: the report's own `updated_ms` (or `generated_ms`), else the file's
modification time, and the age after which it counts as stale (the source's schedule plus slack: 36 hours for the
daily reports, 8 days for the weekly page). The page shows each age next to its numbers and marks a stale section
in red as "veraltet", so an old number never looks current. The file's own age is shown on top.

## The only arithmetic it does

None beyond copying: steps, counts and gates are the reports' own. Ages are now minus the source's time. Candidates
are sorted by step, then name. The weekly page's first lines are cut at 12 lines.

## Trials

None. The page tests nothing, picks nothing among variants and measures no new statistic: it restates the reports'
numbers. R5's registry does not change.
