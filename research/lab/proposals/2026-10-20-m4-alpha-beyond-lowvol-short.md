# Does the funding-aware M4 long/short earn anything beyond the low-vol factor and BTC?: pre-registration draft (2026-10-20)

*Draft by the research director (claude-opus-5-5, 2026-10-20). Nothing runs it. To start it, the owner fixes every number below before any result exists, commits it as the study's pre-registration in `results/` and counts its trials into the pool.*

## Question

After removing its 2022-2023 exposure to the low-vol book and to BTC, does the reg7n book keep a holdout Sharpe above 0.5 at 41 bps, with a bootstrap band above zero?

## Why now

In m4_funding, the reg7n pick makes 2.15 / 2.00 in the holdout at 15 / 41 bps, with deflated p 0.39 / 0.09: the lab's best number, and the m4_ls shadow book runs it (-1.5 % after 12 days). The same write-up puts its margin over the plain low-vol book (1.87 / 1.80) at 0.2 to 0.8 of Sharpe, on one holdout that favoured exactly that bet. It also finds that the selection rule does not select (rank correlation -0.14). family_lowvol shows that shorting high-vol coins carried 2022 and 2024 to 2026, but lost or earned nothing in 2020 and 2023. Whether the model earns anything independent of the factor has not been tested.

## Data

The xs_daily round-three walk-forward predictions and book return series, with funding complete to decision day 2026-09-28 (the archive gap ends the holdout there). The low-vol book of the same shape and BTC daily returns come from the same run. No new data is needed to run the study. A pass still could not be traded where the lab trades: the books need perpetuals, Alpaca offers none, and the lab has no perp venue.

## Design

Fit on 2022-2023, where the model's predictions are already walk-forward: an OLS of reg7n's daily net returns at 41 bps (10/10 of 100 liquid perps, buffer 50 %) on the low-vol book (low 28d vol 10/10 of 100, buffer 50 %, same costs and funding) and on BTC's daily return, with an intercept. The betas are then frozen. In the holdout, 2024-01-01 to 2026-09-28, the residual is R = reg7n - b1 x lowvol - b2 x BTC. The study reports R's Sharpe overall and per year, with a stationary bootstrap using blocks of 20 days. A regression refitted on the holdout is shown for information only and is not judged. R is compared with zero.

## Trials (1)

- Residual series R with frozen betas: 1

## Costs

15 and 41 bps per unit of one-way turnover, as the M4 perp studies use, judged at 41. Historical funding is charged on both books.

## Pass rule

All of these: R's holdout Sharpe above 0.5 at 41 bps; a bootstrap 90 % lower bound above 0; R positive in each of 2024, 2025 and 2026; and R positive in 2023, the year in the fit window when low vol lost. The book counts as confirmed only with a deflated p above 0.95 over 978 trials (977 plus this 1).

## Kill rule

R's holdout Sharpe at or below 0.25 at 41 bps, or R negative in 2 of the 3 holdout years. Then the lab records M4 as the low-vol factor plus funding avoidance, and m4_ls is judged forward against the low-vol book rather than against zero.

## Effort

Minutes of compute. About an hour of the owner's time.

## What could fool us

The betas are fitted on 2022-2023, a window with little funding. If the book's exposure to the low-vol factor grew in 2025-2026, R still carries low-vol return and looks like alpha.

## Built on

`m4_funding`, `xs_daily`, `family_lowvol`
