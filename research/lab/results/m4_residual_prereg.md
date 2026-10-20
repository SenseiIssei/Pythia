# Does the funding-aware M4 long/short earn anything beyond the low-vol factor and BTC? Pre-registration

Registered 2026-10-21 and committed before any number below was computed.
Drafted by the lab's research director job
(`proposals/2026-10-20-m4-alpha-beyond-lowvol-short.md`); every number and
data reference was checked against `xs_daily`, `m4_funding.md` and the paper
book before this file was committed, and the corrections are listed at the
end. Code: `lab.experiments.m4_residual` (written after this file). Results go
to `results/m4_residual.md`. Nothing here may change once a result exists.

## Question

After removing its 2022-2023 exposure to the low-vol book and to BTC, does
the reg7n book keep a holdout Sharpe above 0.5 at 41 bps, with a bootstrap
band above zero?

## Why now

In m4_funding, the funding-aware family's selection-window pick (reg7n,
10/10 of the 100 most liquid perps, rank buffer 50 %) makes 2.15 / 2.00 in
the holdout at 15 / 41 bps, with deflated p 0.39 / 0.09 over 100 variants:
the lab's best picked number. The same write-up puts its margin over the
plain low-vol book of the same shape (1.87 / 1.80) at 0.2 to 0.8 of Sharpe,
on one holdout that favoured exactly that bet, and finds that the selection
rule does not select (rank correlation -0.14 at 15 bps between 2022-23 and
holdout Sharpe over the 56 slower books). family_lowvol shows that its
market-neutral vol book (vol 60d, top 50) was carried by the short leg in
2022 and 2024 to 2026 and lost or earned nothing in 2020 and 2023. Whether
the model earns anything independent of the factor has not been tested.

The lab's M4 shadow book `m4_ls` does not run reg7n: it runs rank3, held 3
days in overlapping tranches, the highest 2022-23 Sharpe among the slower
books (m4_funding, "M4 shadow paper book"). It stands at -1.5 % after 13
journal days (9,847 of 10,000 on 2026-10-20). This study is about reg7n only.

## Data

The `xs_daily` round-three run of 2026-10-07 as cached on the PC
(`<reports>/_cache`: the panel, the walk-forward scores `xs_daily_scores_net`
and the cached pick series `xs_daily_pick_long_short_funding-aware`). Both
books are rebuilt from the cache with `xs_daily.book_buffer`; the rebuilt
reg7n book must match the cached pick series (gross, funding, turnover) to
1e-9 or the study stops. BTC's daily return is BTCUSDT's `R1` from the same
panel (entry to entry, the same days the books earn). Funding is complete to
decision day 2026-09-28 (the PC mirror's funding archive ends with
September), so the holdout ends there. No new data is needed. A pass still
could not be traded where the lab trades: the books need perpetuals, Alpaca
offers none, and the lab has no perp venue.

## Design

- **reg7n**: score reg7n, 10 long and 10 short of the 100 most liquid perps,
  rank buffer 50 %, daily net return = gross + funding - turnover x cost.
- **low vol**: the same book on the score -vol28 (low 28-day vol long, high
  short), same costs and funding.
- **BTC**: BTCUSDT's daily return, no costs.
- **Fit** on 2022-01-01 to 2023-12-31 (the scores are walk-forward there, the
  first test quarter is 2022Q1): OLS of reg7n's daily net return at 41 bps on
  the low-vol book's daily net return at 41 bps and BTC's, with an intercept.
  The betas b1, b2 are then frozen.
- **Holdout** 2024-01-01 to 2026-09-28: R = reg7n - b1 x lowvol - b2 x BTC
  (the intercept stays in R). Reported: R's Sharpe (daily, x sqrt 365)
  overall and in 2024, 2025 and 2026; R in 2022 and 2023 (in the fit window);
  a stationary bootstrap of R's holdout Sharpe (mean block 20 days, 4,000
  draws, seed 20261020, 5 % and 95 %); R's deflated p.
- For information only, not judged: the same at 15 bps (betas fitted at
  15 bps), a regression refitted on the holdout with its intercept as an
  annual alpha, and rolling one-year betas.

## Costs

15 and 41 bps per unit of one-way turnover, as the M4 perp studies use,
judged at 41. Historical funding is charged on both books.

## Trials (1)

- R at 41 bps with frozen betas: 1.

**Pool.** 1,115 hand trials after X15 and X16, 600 genomes in the factory
ledger, and the 9 trials of the three studies registered together today
(`gated_btc` 4, `genome_gates` 4, this one 1): **1,724** trials, noise bar
about 2.73. Deflated as in the other studies.

## Pass rule

All of these:

1. R's holdout Sharpe above 0.5 at 41 bps;
2. the bootstrap 5 % bound above 0;
3. R positive in each of 2024, 2025 and 2026 (2026 to 2026-09-28);
4. R positive in 2023, the fit year in which family_lowvol's market-neutral
   vol book lost (an in-sample check: R's mean over the whole fit window is
   its intercept).

It counts as confirmed only with a deflated p above 0.95 over the pool of
1,724.

## Kill rule

R's holdout Sharpe at or below 0.25 at 41 bps, or R negative in 2 of the 3
holdout years. Then the lab records M4's long/short as the low-vol factor plus
BTC exposure plus funding avoidance, and any forward M4 long/short evidence is
to be judged against the low-vol book of the same shape rather than against
zero (a recommendation; `m4_ls` and its report are not changed here).
Anything between is "not shown to earn beyond the factor".

## What could fool us

The betas are fitted on 2022-2023, a window with little funding. If the
book's exposure to the low-vol factor grew in 2025-2026, R still carries
low-vol return and looks like alpha; the rolling betas are reported for that
reason. The low-vol book and reg7n share their universe and costs, so their
correlation is high and b1 is estimated with error that the bootstrap of R
does not include.

## Corrections to the draft

- "the m4_ls shadow book runs it": it does not. m4_ls runs rank3 held 3 days
  (m4_funding; `lab/paper/m4_ls.py`, `CONFIG`); its -1.5 % is after 13 journal
  days, not 12. The kill rule's consequence is restated for M4 in general.
- The family_lowvol years (2020, 2023 lost or flat) are about its
  market-neutral vol-60d top-50 book, not the M4 low-vol book; pass rule 4 is
  an in-sample check and is labelled as one.
- Pool: 1,724 trials, not 978.
- Data: the cached run is the PC's of 2026-10-07; the books are rebuilt from
  the cached scores and checked against the cached pick series. Bootstrap
  draws and seed fixed; the inconclusive middle case named.
