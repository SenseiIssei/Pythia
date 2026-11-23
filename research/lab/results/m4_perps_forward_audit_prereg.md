# m4_perps forward record audit: pre-registration

Registered 2026-11-23, before any reconciliation, mark, funding, cost or gap figure of this audit was computed. Pattern:
`results/forward_audit_prereg.md` and `results/forward_audit_run.md`. Context: `results/review_2026-10-27.md`
(sections 2 and 3), R5's registry, R6's windows, the readiness ladder (`lab.ops.ladder`), W2's capital line
(`results/weekly_capital_line_prereg.md`). Code: `lab.paper.m4_perps_audit`. Machine output:
`results/m4_perps_forward_audit_run.md`; write-up: `results/m4_perps_forward_audit.md`. Nothing below may change once
the first number is in the write-up; a change is a new registration with a new name.

## Question

Is the m4_perps forward record (`reports/forward/latest.json` of 2026-11-22: +15.9 % in 30 days, max drawdown 0.93 %,
paper costs 0.15x the model, 16 of 30 rebalances) what the book's own rule, the market's prices and funding make of
it, and why is it 12 points ahead of its Hyperliquid twin m4_hl_small (+3.9 %, drawdown 5.9 %, costs 1.49x)?

## Inputs (all read only)

- The book: `<data>/paper/m4_perps/journal.csv` (every row through 2026-11-22, the forward report's last day), its
  `state.json`; the twin's `<data>/paper/m4_hl_small/journal.csv` and `orders/<date>.json`.
- When each run fetched its prices: the job log `<data>/_ops/runs/2026-1{0,1}.jsonl` (job `paper-m4-perps`, status
  ok, its end time; a row without a logged run uses its `entry_hour_utc` at minute 30).
- Prices: Binance spot hourly bars `<data>/hist/binance_spot/klines_1h` (the panel's own source, every coin the book
  held), the price at a run time interpolated linearly inside the hour bar between its open and close; Kraken
  Futures' hourly marks `<data>/kraken_futures/mark_1h` (31 coins) for the same check on the venue the signal routes
  to, reported beside it, not judged.
- Funding: Binance's settlements `<data>/hist/binance_um/funding` (what the book books); Kraken Futures' hourly rates
  `<data>/kraken_futures/funding` reported beside it.
- Targets: the book's expected.source names the frozen M4L panel (sha256 36774aa37afa). That panel is cut at
  2026-06-30 (`m4l_panel.json`: `cut`), so it holds no forward day: it is the band's input, not the book's. The
  targets are rebuilt from today's xs_daily panel `<data>/lab-cache/xs_daily_panel.parquet`, cut at each decision
  day, with reg7n retrained on that cut at each `model_trained` day of the journal exactly as `m4_ls.model_for`
  does, the Kraken listing of the day from `<data>/free/perps_all/kraken_futures/listings.json` (`first_day` on or
  before the run, not delisted). A bar revised after the run shows up as a mismatch that is a data revision and is
  reported as such.
- The band's cost: `<data>/lab-cache/m4l_series.json`, book `m4_perps`: `fee_bps` plus `slip_bps` per unit traded.

## The checks and their tolerances

1. **Record arithmetic.** Every row: equity = previous equity x (1 + gross + funding) x (1 - paper cost). Tolerance
   **1 bp of equity** a row (the journal rounds to cents and 4 decimals).
2. **Calendar.** Every calendar day from the first to the last row: one run, a re-run on the same date, or none.
   A day without a run is **missing**, never a zero return day; a row whose marks span more than 1.5 days carries
   the missing days' moves in one step and is named. Rows with an empty book (`held` 0) are no day of record.
3. **Targets.** Per run, the rebuilt target (the drifted weights of the previous booked target, drifted with the
   reference prices of check 4, through `m4_ls.buffer_target` on the rebuilt candidates cut to the listed coins)
   against the journal's `weights`. A coin-day is every coin either side holds; it is a mismatch when the weights
   differ by more than **0.01** or have opposite signs. Pass: under **5 %** of coin-days.
4. **Marks.** (a) Per coin-day where the journal pins the coin's booked return (held in both rows, under the 1/k cap,
   not traded: r = w_t / w_t-1 x (1 + gross) - 1), against the reference price's return between the two runs.
   A coin-day is off beyond **75 bps**; pass: under **5 %** of judged coin-days off. A **stale mark** is a booked
   coin return under 1 bp in size while the reference moved 50 bps or more; any stale mark fails the check. (b) Per
   row, the booked gross against the previous target times the reference returns: within **20 bps of the book** on
   every row, and the sum over the record within **50 bps**.
5. **Funding.** Per row, the booked funding against minus the previous target times Binance's settlements in
   (previous run, this run]: within **0.5 bp of the book** a row and **2 bps** over the record. Kraken's funding on
   the same positions is reported, not judged.
6. **Costs.** Per row: paper cost = turnover x Binance's taker (5 bps) + the half spread it charged (the rest, which
   must be 0 to 10 bps per unit traded), model cost = turnover x 41 bps; both within 0.02 bps. The ratio is then
   restated against the band's cost per unit traded (check inputs), the cost the forward report's band assumes.
7. **The gap to m4_hl_small.** On the twin's dates (its first row 2026-10-30 to 2026-11-22), additive in points of
   return: **timing** (m4_perps' return before the twin's first run, and the run hour, 05:15 against 06:00, on the
   twin's positions), **funding** (Binance's against Hyperliquid's on each book's own positions), **costs** (each
   book's paper costs), **universe** (gross from coins one venue lists and the other does not), **fills** (gross
   from different weights on coins both list: the buffer's path, whole units, the 250 USD sizing, and each book's
   booked marks against the reference); the compounding remainder is printed as the residual.

## What counts as wrong, and what follows

- A booked **equity** is wrong when check 1, 4 or 5 fails on a row and the cause is in the book's code, or check 3
  is at 5 % or more. Then the book is fixed in lab code with a test that fails before the fix, the series is
  restated, and the rows through the last bad date are frozen in `forward_report.FROZEN` the way
  tsmom_tranches_lowkr was (lane 12043): they count toward no forward gate and no readiness rule.
- A wrong **label** (a cost column, a day count) with right equity is restated in code with a test, not frozen.
- Missing days are counted as missing in the forward report and in W2's capital line (no step between two dated
  reports that show the same run), and the weekly page's capital line is recomputed from that.

## Side by side

Old against corrected: return, max drawdown, days of record, rebalances, the cost ratio, and W2's lower band and
capital figure for m4_perps.

## Trials

None. Nothing is selected and no Sharpe is tested: the audit reproduces a record with its own rule. R5's registry
(`trials/registry.jsonl`) does not change. No new strategy variant, parameter or trial (owner rule of 2026-11-17).

## What could fool us

Binance spot is not Binance's perp mid (a basis of a few bps, larger on funding spikes); the interpolated hour bar
misses the minute the mid was read; the journal rounds weights to 4 decimals (about 10 bps of a 5 % weight). Today's
panel and listing are not the ones the runs saw. Kraken's marks cover 31 coins only. A 30-day record catches bugs,
not edge (review, section 3).
