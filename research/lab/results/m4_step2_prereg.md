# M4S2: step 2 of the readiness ladder for m4_perps, perps_neutral and m4_hl_small. Pre-registration

Registered 2026-11-23 and committed before any number below was computed. While scoping I looked only at which inputs
exist on the data folder (M4L's frozen panel `<data>/lab-cache/m4l_panel.parquet` with its stamp, sha256 36774aa37afa,
and reg7n's score cache under that hash; the two band series `m4_perps_kraken.parquet` and `m4h_judged.parquet` with
their 910 decision days 2024-01-01 to 2026-06-28; T4's hourly depth files for 431 perps; T12b's Kraken Futures and
Hyperliquid listings; the sweep panel; no band file for perps_neutral), at the ladder's step 2 rows of the three books
(leak passes for all three, lane 12043; late, era, both DSRs "no tested record"; PBO "not measured") and at the
registry's trial counts (7,360 in R5: hand 2,255, factory 2,431, small 1,926, pumpfun 748). I computed no return,
Sharpe, cost or PBO.

Builds on the review of 2026-10-27 (`results/review_2026-10-27.md`, sections 2 and 3), R5's registry
(`metrics.trial_pool`, `<data>/trials/registry.jsonl`), R6's windows (in sample to 2023-12-31, validation 2024-01-01
to 2026-06-30, lockbox from 2026-07-01) and the readiness ladder (`lab.ops.ladder`,
`results/readiness_ladder_prereg.md`). Code: `lab.experiments.m4_step2` (written after this file), tests
`tests/test_m4_step2.py`. Results: `results/m4_step2.md` and `results/m4_step2.json` (the stored series the ladder
reads). Nothing in this file may change once a result exists. Paper only: nothing a live bot, a wallet or the engine
reads changes; no book, gate, target or cost model of a paper book changes.

## Question

Each of the three paper books stands on step 1. Step 2 needs, for each: still positive filled one close late, still
positive at the costs of its era, DSR at least 0.95 over R5's whole registry and over its family as of the run day,
and a PBO below 0.2 for the family its rule was picked from. Does each book have that record?

This tests what is already on paper and selects nothing: no new rule, parameter, universe or cost case beyond the two
the ladder names (one close late, the era's costs), no pick, no change to any book whatever the answer.

## The rules, frozen (as the paper books run them)

- **m4_perps**: m4_residual's pick reg7n (`results/m4_residual_prereg.md`): LightGBM on the funding-net 7-day rank
  label, xs_daily's features and parameters, quarterly walk-forward from 2022Q1 with an 8-day embargo (T6b's refit),
  10 long and 10 short, the 50 % rank buffer, gross 1x. Universe as M4L registered it (`results/m4l_prereg.md`): each
  decision day the 100 scored coins with the highest 28-day perp volume, of those the ones Kraken Futures lists on the
  fill day (from the UTC day after its `openingDate`, T12b's listing, today's list only), ranked and buffered among
  them; the ideal account (an index on 10,000, no minimum); fills at 01:00 UTC (the panel's entry price); Binance's
  funding, as the paper book books it.
- **m4_hl_small**: M4H's judged cell `230usd:k10:g1:base:taker` (`results/m4h_prereg.md` as amended by
  `results/m4h2_prereg.md`): reg7n as above, 10/10 among the 100 most liquid that Hyperliquid lists on the fill day
  (T12b's listing history), a 230 USD account with Hyperliquid's size decimals and its 10 USD minimum, 01:00 fills,
  Hyperliquid's hourly funding (Binance's where it has no record).
- **perps_neutral**: perps_neutral_portfolio's pick (`results/perps_neutral_portfolio_prereg.md`): ERC on the
  trailing 90 daily returns (at least 60), reweighted on the first return day of each month, drifting between, book
  reweights at 10 bps, over three books, each on the coins Kraken Futures lists as the paper book trades them
  (`lab.paper.perps_neutral`):
  - **M4**: m4_perps' rule above, its decision day d booked on return day d + 1;
  - **Carry**: funding_carry's pick F7 (`results/funding_carry_prereg.md`): of the 100 most liquid perps Kraken
    lists, long the 10 with the lowest funding settled over 7 days, short the 10 highest, three overlapping 3-day
    tranches, Binance's funding, booked on d + 1;
  - **LowVol**: the sweep's beta-neutral low-vol book (`fam_lowvol`, vol 60d, top 50, "beta-neutral BAB", rebalanced
    every 7 days from day 100), both legs on perps (`trend_shorts.sim`'s rule), restricted to the coins Kraken lists
    with each leg scaled back to its gross (`perps_neutral.restrict_legs`), on the sweep panel.

**Inputs.** reg7n's scores, the M4 and Carry matrices from M4L's frozen panel (the cut at 2026-06-30, checked against
its hash); the sweep panel as the paper jobs built it, cut at 2026-06-30. Nothing from 2026-07-01 on is read.

**Check, not judged, before any trial.** The two M4 books rebuilt on time at the band's costs (M4L's: Kraken's 5 bps
or Hyperliquid's 4.5 bps plus DT1's spread proxy) must match their stored band series day by day to 1e-9; otherwise
the study stops and says so, before any trial is registered. perps_neutral has no band to check against.

## Windows

- **Judged**: the band's out-of-sample days, decision days 2024-01-01 to 2026-06-28 (910 days; the last holding ends
  2026-06-30); for perps_neutral the same 910 days as return days, 2024-01-02 to 2026-06-29.
- **In sample** for the registry's Sharpes and the PBO: decision days 2022-01-01 to 2023-12-31 (perps_neutral from
  2022-03-01, its selection window), on the Binance universe (no venue cut: Hyperliquid's history starts 2023-05), as
  M4H and M4L registered theirs.

## The two tested cases

1. **One close late.** The signal of decision day d acts at the fill of d + 1: the M4 books and Carry trade day
   t's book on day t - 1's scores (the lab's late rule, `funding_carry.late`, as T6 and T6b), the liquidity ranking,
   listing, marks, funding and costs of day t; LowVol's weights and rebalance flags one row later (`t5.late`). The
   combination's weights are set from the late books' returns. Judged at the costs of the era (case 2).
2. **Costs of their era**, per unit of one-way turnover, on time and late:
   - **the venue's taker fee of the period**: Kraken Futures 5 bps, its published base-tier taker (`FEE_KF`); the lab
     holds no dated Kraken Futures schedule, so the whole window takes it (a proxy, said in the results).
     Hyperliquid's base-tier taker as T11 and T12 used it: 2.5 bps to 2023-12-31, 3.5 bps 2024-01-01 to 2025-04-30,
     4.5 bps from 2025-05-01 (switch dates assumed to the quarter, said);
   - **plus the depth cost of a 1k USD market order** (T6b's smallest measured size; every order of these books is
     below it: 11.5 USD at 230 USD, about 500 USD on the 10,000 index) from T4's hourly row nearest the fill (the
     latest hour of the decision day in the coin's file, `two_leads_t6b.fill_hours` and `order_cost`), 500 bps where
     the hour cannot price it. T4 records Binance USD-M's book: it stands in for Kraken's and Hyperliquid's books
     (never measured there), said;
   - **where no depth file exists** for the coin that day (all of 2022, the files start 2023-01-01, and coin-days
     without a file): the book's own proxy, DT1's spread proxy for the M4 legs (the band's), T5's half-spread tier
     for Carry and LowVol (T6's). The results give per book and window the share of the traded turnover at depth and
     at the proxy, by year.

## Step 2's rows and the pass rule (the ladder's numbers)

Per book, each a pass or a fail with its number:

- **late**: the late case's CAGR over the judged days above 0 (Sharpe beside it).
- **era**: the on-time case at the era's costs, CAGR over the judged days above 0, with the proxy-only periods named.
- **dsr_all**, **dsr_family**: the DSR (`metrics.dsr`, higher is better) of the late case at the era's costs (the
  tested series) at least 0.95, over R5's whole registry and over the book's family, with the trial counts of
  `<data>/trials/registry.jsonl` on the run day plus this run's trials. The family: **hand** for m4_perps and
  perps_neutral (reg7n's and the combination's studies, m4_funding, m4_residual and perps_neutral_portfolio, are
  hand), **small** for m4_hl_small (M4H's and M4L's trials are small). The DSR over the other family is reported,
  not judged.
- **pbo**: below 0.2. CSCV (`metrics.cscv`, T2's tool: 16 blocks, every split, the in-sample best by Sharpe) over the
  in sample and judged days together, for each family a rule went through as its pre-registration declares it; a
  book's judged PBO is the highest of its families (each pick had to survive every stage):
  - **reg7n's family** (m4_residual's pre-registration: the pick of m4_funding's funding-aware family): the 18 books
    reg3n, reg5n and reg7n, each on the 50 and the 100 most liquid perps, held for the label's horizon in
    overlapping tranches or with the 30 % and 50 % rank buffers (`xs_daily`'s round three), Binance's universe and
    funding, at 15 bps (the cost the pick was made at). reg3n's and reg5n's scores are refit on the frozen panel with
    their own embargoes (h + 1 days). For all three books.
  - **M4H's k** (`results/m4h_prereg.md`: the passing k with the highest in-sample Sharpe): the judged cells k 3, 5
    and 10 at 230 USD, taker, 01:00, 1x, in sample on Binance's universe, judged days on Hyperliquid's. For
    m4_hl_small.
  - **perps_neutral's pick** (its pre-registration: ERC as the best method in the selection window, against the
    reference single book): M4, Carry, LowVol, EW, IV and ERC, late at the era's costs, as T6 measured it. For
    perps_neutral.

The tested series (the late case at the era's costs, the judged days) of each book goes into
`results/m4_step2.json` with its days, family and the run day's counts, so the ladder recomputes both DSRs over each
day's registry instead of keeping a number that goes stale. The ladder reads the json for these three books only; no
rule of the ladder changes (step 2 needs all five rows as before).

## Trials (30)

Each a line of R5's registry with its in-sample Sharpe, registered before any number of the judged days is computed:

- `hand:m4s2:m4_perps:late`, `hand:m4s2:m4_perps:era`, `hand:m4s2:perps_neutral:late`,
  `hand:m4s2:perps_neutral:era`, `small:m4s2:m4_hl_small:late`, `small:m4s2:m4_hl_small:era` (6);
- reg7n's family rebuilt on the frozen panel: `hand:m4s2:pbo:fa:<model>:<50|100>:<hold|buf30|buf50>` (18, new
  numbers of old configurations, counted again as M4L did);
- M4H's k 3 and k 5 cells on the frozen panel: `small:m4s2:pbo:m4h:k3`, `small:m4s2:pbo:m4h:k5` (2; k 10 is M4L's
  `small:m4l:hl_judged_rebuild`, the same numbers);
- perps_neutral's other candidates: `hand:m4s2:pbo:pn:<Carry|LowVol|EW|IV>` (4; its M4 is m4_perps' late case, its
  ERC the book's late case).

26 hand, 4 small. The run writes them to a copy of the registry (`PYTHIA_TRIALS_REGISTRY` in the run's /out), which
T14's merge appends by id into `<data>/trials/registry.jsonl`, as every agent run does; the DSRs are computed over
that copy, so they count this run's 30.

## What follows

A pass on all five rows moves a book to step 2 on the ladder (it then needs step 3's 30 days and T8); a fail keeps it
on step 1 with the failing row and its number. A fail is a valid result and is reported as plainly as a pass. No
book, job, cost model, target or gate changes either way.

## What could fool us

- The judged days are the holdout reg7n was picked on (m4_funding) and judged on (m4_residual, M4H, M4L): a pass here
  is the same window again, not fresh evidence. The DSR is the guard for that.
- The signal's record moves with the panel's build day (M4H2, M4L); the frozen panel fixes the series, not the doubt.
- Kraken's listing holds today's perps only (a perp delisted before the collector started is missing): survivorship,
  which flatters every Kraken book.
- Binance's book and prices stand in for Kraken's and Hyperliquid's; Kraken's fee history is a proxy.
