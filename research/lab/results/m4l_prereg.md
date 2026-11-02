# M4L: the backtest bands of the M4 paper books, and the fill cost of m4_hl_small. Pre-registration

Registered 2026-11-02 and committed before any number of this study was computed. Asked by the owner on 2026-11-02
("mach weiter mit M4"). Code: `lab.experiments.m4h` (`--export-series`), `lab.paper.forward_report`
(`export_backtests`), `lab.paper.m4_hl_small` (the fill), `lab.paper.hl_live` (the executor, unarmed). Results:
`results/m4l.md`. Paper only: nothing a live bot, a wallet or the engine reads changes; no order is sent.

## Question

1. The forward report judges a paper book only against its backtest's range. `m4_hl_small` and `m4_perps` have
   none (status early or unknown). Which out-of-sample daily net series is each book's backtest, and where does
   each book stand inside its band on the day of the run?
2. After 3 days the forward report says `m4_hl_small`'s fills cost 1.9x what the backtest assumes. Is the paper
   fill wrong, the journal's model of the backtest's cost, or both?

## The two series (R6's windows, the lockbox never read)

Both from M4H's machinery unchanged (`lab.experiments.m4h.build`: xs_daily's panel cut at 2026-06-30, reg7n's
walk-forward refit of T6b, the 100 most liquid perps of each decision day, the 50 % rank buffer, fills at 01:00
UTC, DT1's spread proxy a side on top of the taker fee). In sample 2022-01-01 to 2023-12-31 on the Binance universe
with Binance's funding (as M4H); out of sample, the series the band is drawn from, 2024-01-01 to 2026-06-28
(decision days; the last holding ends 2026-06-30).

- **`m4_hl_small`**: M4H's judged cell `230usd:k10:g1:base:taker`, as registered there: a 230 USD account with
  Hyperliquid's size decimals and 10 USD minimum, the coins Hyperliquid lists on the fill day, taker 4.5 bps plus
  the proxy, Hyperliquid's hourly funding (Binance's where it has no record). Its daily net returns go to
  `<data>/lab-cache/m4h_judged.parquet`.
- **`m4_perps`**: reg7n 10/10, gross 1x, the ideal account (the paper book is an index on 10,000 with no
  minimum), on the coins Kraken Futures lists: a coin from the UTC day after its `openingDate` in T12b's listing
  (`<data>/free/perps_all/kraken_futures/listings.json`), a delisted one until its last settlement; Kraken's base
  taker 5 bps (DT1's `FEE_KF`) plus the same proxy; Binance's funding, as the paper book books it. Its daily net
  returns go to `<data>/lab-cache/m4_perps_kraken.parquet`. Kraken's listing holds today's perps and the ones
  the collector saw close: a perp Kraken delisted before 2025-10 is missing (survivorship, said in the results).

The forward report's existing `bootstrap_band` (stationary blocks over the series) makes each band; a book's
position is `inside`, `above` or `below` as for every other book. No rule of the report changes.

## Trials (R5)

Two, family `small`, each with its in-sample Sharpe, registered before any out-of-sample number:
`small:m4l:hl_judged_rebuild` (the M4H cell rebuilt on today's panel: a new number of an old cell, counted again)
and `small:m4l:m4_perps_kraken`. The DSR of each over the registry is reported; neither is judged for a pass.
This study makes no pick and moves no book up the ladder.

## The fill cost

- The journal's paper cost of the first days against the orders of `orders/<date>.json`: the taker fee, the
  half spread the paper fill charges (half of `impactPxs`, which Hyperliquid computes at its impact notional, far
  above an 11.5 USD order), and what the same orders cost walking Hyperliquid's public `l2Book` at their size,
  measured once on the day of the run.
- The journal's `model_cost_bps` against the judged cell's cost per unit traded (taker plus its mean proxy slip
  per traded USD, from the rebuild).
- Rule: whichever side differs from what it claims to be is fixed. The paper fill walks the order book at the
  order's size (the impact spread when the book cannot be read, journaled); the model is the judged cell's fee
  plus its mean slip per unit traded. No change to the book's targets, sizes, limits or the dry-run executor.

## The executor (no number)

`lab.paper.hl_live`: Hyperliquid's L1 action signing checked against the published test vectors of the official
Python SDK 0.24.0, read-only reconciliation from the public info endpoint, a send path behind every gate of the
brief. No job, cron or container runs it; it is not armed. The owner arms it, never this study.

## Addendum (registered 2026-11-02, before any code or run of it): the frozen panel and the ladder

M4L's own results file says the judged cell rebuilt on the panel of 2026-11-02 makes a Sharpe of 1.20, where M4H
made 1.79 on the panel of 2026-10-30: same code and windows, a different build of xs_daily's panel under reg7n's
walk-forward refit. A band drawn from a series nobody can rebuild is not a fixed yardstick. So:

- **Frozen panel.** `--export-series` cuts the panel at 2026-06-30 once, stores that cut as
  `<data>/lab-cache/m4l_panel.parquet` with its stamp (the panel file's build date, its last day, the cut's
  rows and a sha256 over its sorted columns), and every later export reads the frozen cut (and a reg7n score
  cache keyed by its hash) instead of today's panel. The stamp goes into `m4l_series.json` and into each book's
  `reports/forward/backtest/<book>.json`; the forward report names it as the band's source. A rebuild whose cut's
  hash differs from the stored one is said, never silent.
- **No new number.** The stamp is no score. Building the frozen cut and the series on the server is the owner's
  run (heavy); it registers the same two trials as above, nothing more. The band, the in-band rule, the horizon
  (each book's elapsed days) and the fill comparison stay as registered above.
- **Ladder.** m4_hl_small runs M4H's judged cell, registered in `results/m4h_prereg.md` as amended by
  `results/m4h2_prereg.md` (results `results/m4h.md`); m4_perps runs m4_residual's registered pick reg7n
  (`results/m4_residual_prereg.md`, results `results/m4_residual.md`). The ladder maps them so; step 1 is then
  judged by its own rule (its own commit, before the results' commit). No rule of the ladder changes.
