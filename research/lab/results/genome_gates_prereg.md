# Is the factory's shadow low-vol genome anything more than its BTC gates? Pre-registration

Registered 2026-10-21 and committed before any number below was computed.
Drafted by the lab's research director job
(`proposals/2026-10-20-lowvol-genome-against-its-gates.md`); every number and
data reference was checked against the factory's code and ledger before this
file was committed, and the corrections are listed at the end. Code:
`lab.experiments.genome_gates` (written after this file). Results go to
`results/genome_gates.md`. Nothing here may change once a result exists.

## Question

Does genome 44444c97ba5e beat both the same rule with its signal removed
(null A) and BTC under the same filters (null B), on the factory's held-back
window at 35 bps?

## The genome

"low vol · top 20 · BTC 28d up · BTC > MA200 · vol < 120 % · best 5 by signal
· equal full · every 3d band 50 %" (`results/factory_seed/shadow/44444c97ba5e.json`):
the 20 most liquid eligible coins of each day, each "on" whenever its 30-day
vol is known (the low-vol signal turns every coin on and only ranks), three
filters (BTC's 28-day return above 0 and BTC above its 200-day average, else
the whole book is cash; the coin's annualised vol below 120 %), the 5 with the
lowest vol, equal weights over what is held, rebalanced every 3rd calendar day
with a 50 % no-trade band.

## Why now

The factory's ledger shows 44444c97ba5e as the only genome that passed every
held-back gate (0.88 at 35 bps, 0.69 at 70, drawdown 35 % against BTC's 53 %)
and it now runs as a forward shadow book. Its deflated p is 0.0043 over 677
trials, and promotion needs 0.95 at the end of its 30 shadow days, which one
month of returns cannot deliver. The six held-back checks of the factory's
second run (2026-10-18) came in between -0.20 and 0.18 at 35 bps (five of six
at or below -0.02), with drawdowns of 52 to 77 %, while their in-sample halves
fell from 2.9 to 3.8 to 1.2 to 2.0. In the hand sweep (family_lowvol),
long-only low vol made only 0.50 and 0.28 at 15 bps (top 50 and top 100), with
drawdowns of 66 to 75 %. So the genome's BTC gates are the likely source of
its result, and among the top 20 coins the 5 calmest are mostly the majors.

## Data

The factory's own code: genome weights from `lab.factory.build.weights`, the
simulator `lab.factory.build.simulate` (every 3 days, band 50 %), costs from
`build.net`, on the sweep's survivorship-free daily panel
(`fam_common.load_panel`) rebuilt from the hourly history on the PC. The
held-back window is the factory check's: **2024-01-01 to 2026-10-14** (1,018
days, `lab.factory.evaluate.windows`, `oos_to` in
`results/factory_seed/holdout.jsonl`); the panel's later days are dropped.
Before the nulls are computed, the run reproduces the genome's held-back
numbers (0.88 at 35 bps, 0.69 at 70); if it misses 0.88 by more than 0.03 the
study stops and reports why.

## Design

- **Null A**, signal removed: the same genome with selection by liquidity
  instead of the signal (`select.rank = "liquidity"`: the 5 with the highest
  28-day mean quote volume among the same candidates). Everything else
  unchanged, the vol cap included.
- **Null B**, BTC under the same filters: BTC alone at full weight on the
  closes where both BTC gates are on and BTC's annualised vol is below 120 %,
  cash otherwise, through the same simulator (every 3 days, band 50 %).
- **D_A** = the genome's daily net return minus null A's, **D_B** = the
  genome's minus null B's, same days, same cost.
- Reported: Sharpe (daily, x sqrt 365), CAGR and drawdown of the genome and
  both nulls at 35 and 70 bps; Sharpe of D_A and D_B at 35 and 70 bps, in
  2024, 2025 and 2026; a stationary bootstrap of each D's Sharpe (mean block
  20 days, 4,000 draws, seed 20261020, 5 % and 95 %); the share of days on
  which the genome holds exactly the same coins as null A (among days on
  which either holds anything), and the share of days in cash.

## Costs

35 bps per unit of one-way turnover, 70 bps as stress (`build.COSTS`).

## Trials (4)

- Null A and null B: 2.
- D_A and D_B: 2.

**Pool.** 1,115 hand trials after X15 and X16, 600 genomes in the factory
ledger, and the 9 trials of the three studies registered together today
(`gated_btc` 4, this one 4, `m4_residual` 1): **1,724** trials, noise bar
about 2.73. Deflated as in the other studies (hand trials at the published
bar's variance, factory in-sample Sharpes, this study's trials).

## Pass rule

D_A and D_B both have a Sharpe above 0 at 35 bps and at 70 bps, and both
bootstrap 5 % bounds (at 35 bps) are above 0. Then the signal adds to the
gates, and the write-up recommends a new fixed forward rule for the shadow:
90 days, Sharpe above 0, drawdown under its held-back 35 %. The genome counts
as confirmed only with a deflated p above 0.95 over the pool of 1,724, which
its 0.0043 over 677 makes very unlikely.

## Kill rule

If D_A or D_B has a Sharpe at or below 0 at 35 bps, the lab records that the
factory's only low-vol pass is an effect of its gates, and the write-up
recommends retiring the genome from shadow. Anything between pass and kill is
"not shown to add to its gates", and the shadow runs on under its own rule.
This study changes no factory state; the recommendation goes to the owner.

## What could fool us

Ranking by liquidity and ranking by low vol pick nearly the same majors, so
D_A is small and noisy whatever the truth; the overlap share is reported for
that reason. A pass driven by D_B alone would only be a pass on coin choice
among the majors, in one held-back window. The window is one regime path:
2024 to 2026 with BTC above its average most of the time.

## Corrections to the draft

- The genome has three filters, not two: besides the two BTC gates it caps
  each coin's annualised vol at 120 %. Null A keeps the cap; null B applies it
  to BTC.
- Evaluator and window, which the draft left open: `lab.factory.build` and
  `lab.factory.evaluate`, 2024-01-01 to 2026-10-14 (1,018 days).
- The 2026-10-18 held-back checks: -0.20 to 0.18 at 35 bps (the draft said
  -0.20 to -0.02, missing 0b555e9d3992 at 0.18), drawdowns 52 to 77 % (draft
  60 to 77 %), in-sample halves 2.9 to 3.8 then 1.2 to 2.0 (draft "about 3.7
  to 1.2").
- Pool: 1,724 (the draft's 981 left out 738 hand trials counted since the
  factory's seed of 377).
- Bootstrap draws and seed fixed; the inconclusive middle case named; the pass
  and kill consequences are recommendations, since this study does not touch
  the factory's state.
