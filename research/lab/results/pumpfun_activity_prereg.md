# pump.fun activity as a memecoin gauge: forward registration

Registered 2026-10-21, before any series below exists beyond the first
partial day. Survey idea O9 (`proposals/2026-10-21-strategy-survey.md`). The
real-time record (`lab.pumpfun_rt`) started on 2026-10-20, so nothing can be
tested now: this file fixes the daily series, the questions, the pass and kill
rules and the judging day, and the series is recorded forward from today.
Code: `lab.pumpfun_rt.activity` (written after this file). Nothing here may
change once a judged number exists.

## The daily series

Per UTC day, from the record under `<data>/pumpfun_rt/` (`creates`, `trades`,
`other`):

| key | what |
|---|---|
| `creations` | tokens created |
| `completions` | bonding curves completed |
| `migrations` | tokens migrated to a pool |
| `migration_rate` | migrations / creations |
| `sol_volume` | curve trade volume in SOL, buys and sells |
| `traders` | distinct curve traders |
| `coverage` | the share of the day both programs' streams were connected (from the collector's gap rows and the first and last event of the day) |

Counts and volume are also stored divided by coverage (`*_adj`). A day is
**complete** when coverage is at least 0.9; only complete days count below.
The series lives in `<reports>/pumpfun_activity/series.csv`, merged every day
and never recomputed for days whose record partition is gone (the record
deletes its oldest days when it runs out of budget). The job
`pumpfun-activity` runs daily after the collector's day ends.

## Questions (judged after 180 complete days)

**Q1, a sentiment gauge.** Does the 7-day log change of coverage-adjusted
`sol_volume` (primary; `creations_adj` and `migration_rate` reported as
information) predict the next 7-day return of an equal-weight basket of the
six memecoins Alpaca lists (DOGE, SHIB, PEPE, BONK, WIF, TRUMP; Binance
closes)? OLS slope, t-statistic on non-overlapping weeks (every 7th complete
day). The 1-day return is reported, not judged.

**Q2, a gate.** `memes_rotation` held only while the 7-day mean of
coverage-adjusted `sol_volume` is at or above its trailing 28-day median
(known at the close), cash otherwise, against `memes_rotation` as it runs,
both replayed with W7's simulator on the forward days at 35 bps per unit of
turnover (the gate's switches pay the same).

## Pass and kill

- Q1 passes with a slope t-statistic above 2 (the expected sign is positive:
  more speculative appetite, memecoins up); killed with |t| below 1.
- Q2 passes when the gated rotation's Sharpe is above the ungated one's and
  its maximum drawdown is lower over the judged days; killed when its Sharpe
  is lower.
- Q1 and Q2 count as 2 trials in the global pool from today (pool 1,836
  with the 94 trials of `results/crypto_own_prereg.md`). A pass at 180 days
  can only make the gate an experimental shadow; anything beyond needs a
  longer record.

## Judging day

The first day with 180 complete days in the series (at the earliest
2027-04-18). Before that the series is reported daily as information only, and
no slope, gate result or "early read" is written into `results/`.

## What could fool us

180 days are 25 non-overlapping weeks: a slope with t above 2 can still be
one memecoin cycle. pump.fun activity and the six memecoins may both just
follow SOL and BTC; the judging report adds the slope with the 7-day BTC
return as a second regressor, as information. Collector outages and the
public endpoint's dropped messages lower the counts; the coverage adjustment
handles outages, not silent drops.
