# T6b: lead A with order book depth. Pre-registration

Registered 2026-10-29 and committed before any number below was computed (while scoping, one look at which inputs
exist on the data folder: T4's hourly depth files for 431 perps from 2023-01-01, `<data>/book_depth/estimate.json`,
T4's delisting table with 353 rows, no xs_daily score cache; no performance number). Brief T6b of the training plan
of 2026-10-28, on the review of 2026-10-27 (`results/review_2026-10-27.md`, sections 2 and 3), R5's registry
(`metrics.trial_pool`, `<data>/trials/registry.jsonl`), R6's windows (`results/factory_lockbox_r6.md`) and T6
(`results/two_leads_t6_prereg.md`, `results/two_leads_t6.md`). Code: `lab.experiments.two_leads_t6b` (written
after this file). Nothing here may change once a result exists. Paper only: no book, gate, engine setting, live
path or wallet changes.

## Question

T6 judged lead A (the perps_neutral portfolio) with T5's half-spread tiers because T4's depth was not on the data
folder. With the depth there: does lead A hold up when each perp leg pays what the order book of its fill hour
charged, and at what size does that cost halve its Sharpe?

## What changes: the cost model only

Everything of T6's rule for lead A stays: the three books (M4 reg7n, carry F7, low vol on PIT50), one close late,
ERC monthly, book reweights 10 bps, the six PBO candidates, the windows, conditions A1 to A7, the pass rule, the
lockbox rule and the ladder. Lead B is not rerun (spot and on-chain legs, no depth).

The cost per unit of one-way turnover of a perp leg traded at the close of day t (one close late, as in T6):

- **The USD-M taker fee, 5 bps**, plus
- **the depth cost of a market order of the leg's notional L** (1k, 10k and 100k USD a leg) from T4's hourly row
  (`<data>/book_depth/hourly`) nearest the fill: the fill is the close at 00:00 UTC ending day t, so the latest
  hour of day t in the coin's file (the 23:00 hour when present; known before the fill). One perp per coin as
  `lab.features.book` keeps it (the deeper book of the hour). 10k and 100k: the hour's `cost10k` / `cost100k`
  (the mean over its snapshots, buy and sell averaged, bps from mid). 1k: the collector's model (linear in price
  from mid through the 0.2 % and 1 % levels, the straight line to 1 % before the 0.2 % level exists) on the
  hour's mean notional at those levels, buy and sell averaged. The depth cost replaces T5's half spread (it is
  measured from mid).
- **A day without a depth file** for the coin (no hour of that UTC day): T5's tier as in T6 (the half spread by the
  coin's volume that day). Counted in the report per book and window: the days with a leg at the tier and the
  share of the charged turnover at the tier. In sample (from 2022-03-01) runs mostly on tiers, the files start
  2023-01-01.
- **A size the hour cannot price** (beyond its recorded depth, while the file exists): 500 bps (the 5 % level),
  counted.
- Every trade of a leg is charged as if it traded the leg's whole notional L (a partial reweight pays the price
  of the full size; conservative).

**Judged**: L = 10k USD a leg (T6's pre-registration named T4's 10k cost). 1k and 100k are reported beside it.

**Capacity**: the leg notional at which the depth cost halves the ERC's validation Sharpe, against the ERC with the
taker fee only (no spread, no depth): linear in log10 L between 1k, 10k and 100k; "below 1k" or "above 100k (not
measured)" outside.

## Inputs that differ from T6's run (not its rule)

- **M4's scores.** The 2026-10-07 xs_daily cache T6 read is not on the data folder. reg7n's walk-forward scores
  are refit with `xs_daily.fit_net_scores`' folds, embargo and parameters (reg7n only) on the lab cache's
  xs_daily panel cut at 2026-06-30 before the labels are built (no label reads the lockbox).
- **T4's delisting table is present**, so the low-vol leg's PIT50 drops a coin from its announcement day (T6's
  rule: the flag when the table is there).
- So the depth effect is read against **T6's tiers rerun on these same inputs** (ERC at the tiers), not against
  T6's published 1.74.

## Trials (10)

Each a line of R5's registry (family hand) with its in-sample Sharpe, registered before any validation number:
`hand:t6b:a:<M4|Carry|LowVol|EW|IV|ERC>` (at 10k, the judged ones), `hand:t6b:a:ERC@1k`, `hand:t6b:a:ERC@100k`,
`hand:t6b:a:ERC@tier`, `hand:t6b:a:ERC@fee`. DSR over R5's pool of all and the hand family as in T6.

## T5's point-in-time universe with T4's delisting table

T5's study (`lab.experiments.pit_universe_t5`, `results/pit_universe_t5_prereg.md`) rerun unchanged except: LAB20
through `lab.universe.tradable` (a coin leaves from the UTC day its spot or perp delisting was announced), PIT20 and
PIT50 with T4's delisting flag (T5's rule when the table is there). Same rules, windows, late fill and costs. 18
trials `hand:t5_pit_dl:<rule>:<universe>`, registered with their in-sample Sharpes before the validation numbers.
Reported: one line per rule in `results/pit_universe_t5.md`: the validation Sharpe on LAB20, PIT20 and PIT50, the
validation Sharpe gap against PIT20 with its band and the material flag (T5's rule), T5's gap beside it.

## Reported

A section "T6b: with order book depth" in `results/two_leads_t6.md`, above T6's generated part (its numbers between
their own markers): the validation Sharpe, CAGR and drawdown at 1k, 10k and 100k a leg and at the tiers and the fee
only, conditions A1 to A7 at 10k (DSR over all and the family, PBO, CPCV, leak, paper record), the capacity, the
days at the tier and beyond the depth, the lockbox line (no look unless validation passes) and the ladder step.
Nothing reaches a book, the engine or a wallet.
