# T6: the two leads to the end. Pre-registration

Registered 2026-10-28 and committed before any number below was computed (while scoping, one look at the size of
R5's registry, 2,823 trials with the factory ledgers, and at which inputs exist on the data folder: no T4 depth
files, no T4 delisting table, the 2026-10-07 xs_daily cache, the perps_neutral journal; no performance number).
Brief T6 of the training plan of 2026-10-28, on the review of 2026-10-27 (`results/review_2026-10-27.md`,
sections 2 and 3), R5's registry (`metrics.trial_pool`, `<data>/trials/registry.jsonl`) and R6's windows
(`results/factory_lockbox_r6.md`). Code: `lab.experiments.two_leads_t6` (written after this file). Results go to
`results/two_leads_t6.md`. Nothing here may change once a result exists. Paper only: no book, gate, engine setting,
live path or wallet changes.

## Question

For each of the lab's two leads, yes or no: does it hold up filled a close late at the costs of its era, deflated
over R5's whole registry and its family, with PBO, CPCV paths and the leak harness, and does its paper record so far
sit inside its validated distribution?

- **Lead A**: the market-neutral perp portfolio (`perps_neutral_portfolio`: M4 reg7n, funding carry F7, low-vol
  beta-neutral; ERC, monthly). Published: from 2024 Sharpe 2.47 at 10 bps, deflated p 0.32 then. Paper book
  `lab.paper.perps_neutral` since 2026-10-21.
- **Lead B**: F2's lost survivor 07493e8a8adb (Donchian 100/50 on BTC, ETH, SOL, SPY, QQQ, GOLD, the asset above its
  100-day average, the best 1 by 90-day return, 20 % vol, weekly). R10: late 22.5 % / 17.7 % drawdown at 40 EUR,
  DSR 0.000 over all, 0.03 / 0.05 in the small family.

## Windows (R6)

In sample to 2023-12-31 (A: 2022-03-01 on, the study's selection window; B: R10's 2020-08-01 on), validation
2024-01-01 to 2026-06-30. Every series is cut at 2026-06-30 before anything is computed. The lockbox from
2026-07-01 is not read by this study (below). The paper record (A's journal from 2026-10-21) is the book's own
forward record, read only after the validation verdict is fixed in the output, and selects nothing.

## Lead A: how it is run

- **The books as they exist.** M4 reg7n from the 2026-10-07 cache (`m4_residual`'s rebuild, the score
  `reg7n`, `xs_daily.book_buffer` 10/10 of the 100 most liquid perps, buffer 50 %); carry `funding_carry`'s F7
  (`xs_daily.book`, 10/10, three 3-day tranches); low vol `fam_lowvol.weights(vol 60d, beta-neutral BAB)` weekly
  with both legs on perps. Combined by ERC on the trailing 90 days, monthly (`perps_neutral_portfolio.combine`).
- **One close late.** M4 and carry: the score known on day d is used on day d+1 (`funding_carry.late`). Low vol: the
  targets known at close t traded at close t+1 (T5's `late`).
- **Costs of their era**, per unit of one-way turnover in each coin on the day of the trade: USD-M taker 5 bps plus
  T5's half-spread tiers (1 bp at 1 B USD a day or more, 3 from 100 M, 10 from 10 M, 25 from 1 M, 50 below) on the
  coin's own volume then (M4 and carry: xs_daily's 28-day mean perp dollar volume; low vol: T5's 30-day median).
  `xs_daily.book` and `book_buffer` get an optional per-coin cost matrix for this (without it nothing changes).
  Book reweights are charged 10 bps (the study's judged cost).
- **Slippage from T4's depth**: where T4's daily `cost10k` (the mean cost of a 10k USD market order, bps from mid)
  exists for a coin and day, it replaces the tier's half spread. If no depth file is on the data folder the
  report says that the tiers above were used.
- **Point-in-time universe (T5).** M4 and carry already pick each day from the 100 most liquid perps of the day
  among every perp the xs_daily panel holds. The low-vol leg runs on T5's PIT50 (`lab.universe.pit`, eligibility
  intersected, n 50), with T5's delisting flag when T4's table is present.
- **The candidates for PBO**: the three books alone and the three combinations (EW, IV, ERC) the study chose from,
  all late at era costs.

## Lead B: how it is run

- R10's machinery unchanged (`smallaccount_r10.load`, `run_f2`): F2's 40 and 100 EUR wallets in USD valued in EUR
  at the ECB's rate, the way in and back, on-chain quotes only from the day each asset could be swapped on chain,
  Kraken's taker fee and half spread before, the ETF tokens at 00:00 UTC with the measured deviations; filled one
  close late. Benchmark: the UCITS S&P 500 fund in EUR (SXR8.DE), as R10 judged a rule that holds tokens.
- No T4 depth for these assets (spot and on-chain): R10's cost model, said so.
- **Point in time**: the six assets cannot be chosen point in time. T5 measured the rule on coins (validation
  Sharpe 0.98 on today's 20, 0.10 on PIT20); quoted, not rerun, not a gate.

## Conditions (each pass or fail in the report)

Lead A, on the ERC combination late at era costs over validation:
1. **A1 gates**: Sharpe above 0.5; positive in 2 of 2024, 2025, 2026 to June; the stationary bootstrap's 5 % above
   0 (`director_common.boot_band`); correlation with BTC within +-0.3.
2. **A2 DSR all**: DSR over R5's pool of all (the factory ledgers counted once by id, these trials included), 0.95
   or more (higher is better).
3. **A3 DSR family**: the same over the hand family.
4. **A4 PBO**: CSCV (`metrics.cscv`, 16 blocks) over the six candidates on in sample plus validation, below 0.5.
5. **A5 CPCV**: `factory.evaluate.cpcv` on the ERC's in-sample series with the other five as near variants
   (correlation above 0.90), the 10th percentile of the paths' Sharpes above 0.
6. **A6 leak**: T1's harness (`leak.checks.book`) on the low-vol weight function on the cut panel finds no leak.
   M4's cached walk-forward scores and xs_daily's features have no T1 check; reported as not covered, not a pass.
7. **A7 paper record**: the journal's compounded return over its days (from 2026-10-22, the first marked day) at or
   above the 5th percentile of the validation series' rolling returns over the same number of days. Also shown:
   its percentile, and each sub-book's.

Lead B, late at 40 and 100 EUR over validation:
1. **B1 gates** (R10's safe-path bar): drawdown under 20 % and CAGR at least SXR8's minus 1 point at both sizes.
2. **B2 DSR all**: DSR of the daily excess over SXR8 in EUR at 40 EUR over the pool of all, 0.95 or more.
3. **B3 DSR family**: the same over the small family.
4. **B4 PBO**: F2's family PBO from its newest nightly run (`<data>/factory/small/runs/`), below 0.5. Read, not
   recomputed.
5. **B5 CPCV**: `factory.evaluate.cpcv` on the late 40 EUR in-sample returns on F2's in-sample window with F2's
   family series (`small.family_series` on its own costs) as variants, the 10th percentile above 0.
6. **B6 leak**: T1's harness on the genome (`leak.checks.genome(..., small=True)`) finds no leak.
7. **B7 paper record**: F2 lost it before a shadow wallet ran; no record is "not met".

**Validation passes** for a lead when conditions 1 to 6 all pass.

## The lockbox

Only if a lead's validation passes, and only through `run.lockbox_step` (R6: once per behaviour, logged before
use). This study never reads a price after 2026-06-30 and never writes R6's lockbox log: a pass is written as
"lockbox look due" with what the weekly run needs (B: a held-back line of F2 with its excess passed, which
`small.lockbox_step` picks up; A: `run.lockbox_step` has no path for a hand book, so a pass needs that path first,
its own brief). A fail is written as "no look".

## The ladder

T3's ladder is not on main (its run was stopped), so the step is given on this provisional ladder, the same order
as T3's description: 0 a backtest; 1 passes its registered gates late at era costs (A1 / B1); 2 plus deflation over
all and its family, PBO, CPCV and the leak harness (validation passes); 3 plus the lockbox look at R6's bar; 4 plus
90 paper days inside the validated band; 5 a small real-money record (the owner's decision); 6 larger (the owner
only).

## Trials (9)

Each a line of R5's registry with its in-sample Sharpe, registered before the validation numbers are computed:
`hand:t6:a:<M4|Carry|LowVol|EW|IV|ERC>` (family hand, 6) and `small:t6:07493e8a8adb:late@<40|100>` plus
`small:t6:07493e8a8adb:cpcv` (family small, 3). The reproduction on time at 10 bps of A's published number is a
check, not a trial.

## Reported

`results/two_leads_t6.md`: per lead each condition pass or fail with its number; the validation Sharpe, CAGR,
drawdown; the lockbox line; the step on the ladder; what would change the answer (the validation Sharpe the DSR bar
needs on this pool, and the paper days needed). Nothing reaches a book, the engine or a wallet.
