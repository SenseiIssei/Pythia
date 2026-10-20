# Is the factory's shadow low-vol genome anything more than its two BTC gates?: pre-registration draft (2026-10-20)

*Draft by the research director (claude-opus-5-5, 2026-10-20). Nothing runs it. To start it, the owner fixes every number below before any result exists, commits it as the study's pre-registration in `results/` and counts its trials into the pool.*

## Question

Does genome 44444c97ba5e beat both the same rule with its signal removed and BTC under the same two gates, on the factory's held-back data at 35 bps?

## Why now

The ledger shows 44444c97ba5e as the only genome that passed every held-back gate (0.88 at 35 bps, 0.69 at 70) and it now sits in shadow. Its deflated p is 0.0043 over 677 trials, yet its rule says it needs 0.95 by the end of its forward month, which one month of returns cannot deliver. Every other held-back check of 2026-10-18 came in between -0.20 and -0.02 at 35 bps, with drawdowns of 60 to 77 %, while their in-sample halves fell from about 3.7 to 1.2. In the hand sweep (family_lowvol), long-only low vol made only 0.50 and 0.28 at 15 bps, with drawdowns of 66 to 75 %. The genome's two BTC gates (BTC 28d up, BTC > MA200) are therefore the likely source of its result, and among the top 20 coins the 5 with the lowest vol are mostly the majors.

## Data

The factory's genome evaluator and its held-back window. The material names neither the module nor the held-back dates, so the owner takes both from the factory code and writes them into this draft before the run. The data is the panel as the factory uses it. Nothing else is needed.

## Design

Use the held-back window exactly as the factory's check did, and the genome exactly as it was checked. Null A is the same genome with its signal replaced by liquidity (the best 5 of the top 20 by 28-day dollar volume), everything else unchanged. Null B is BTC alone at full weight while both gates are on, checked every 3 days with the same 50 % band. D_A is the genome's daily net return minus A's, and D_B the genome's minus B's. The study reports Sharpes, drawdowns, per-year results, a bootstrap with blocks of 20 days, and the share of days on which the genome holds the same coins as null A.

## Trials (4)

- Null A and null B: 2
- Difference series D_A and D_B: 2

## Costs

35 bps per unit of one-way turnover, with 70 bps as stress.

## Pass rule

Both D_A and D_B have a Sharpe above 0 at 35 bps and at 70 bps, with bootstrap 90 % lower bounds above 0. Then the signal adds to the gates, and the genome stays in shadow under a new fixed forward rule: 90 days, Sharpe above 0, drawdown under its held-back drawdown. It counts as confirmed only with a deflated p above 0.95 over 981 trials (977 plus these 4), which its current 0.0043 makes very unlikely.

## Kill rule

If D_A or D_B has a Sharpe at or below 0 at 35 bps, the genome is retired from shadow, and the lab records that the factory's only low-vol pass is an effect of the gates.

## Effort

Minutes of compute. About an hour of the owner's time, mostly finding the held-back window and the evaluator.

## What could fool us

Ranking by liquidity and ranking by low vol pick nearly the same majors, so D_A is small and noisy whatever the truth. A pass driven by D_B alone would only be a pass on coin choice among the majors, in one held-back window.

## Built on

`family_lowvol`, `regime`
