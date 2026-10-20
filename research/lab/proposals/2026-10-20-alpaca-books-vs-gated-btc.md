# Do the Alpaca books beat BTC held only above its 200-day average, at the same risk?: pre-registration draft (2026-10-20)

*Draft by the research director (claude-opus-5-5, 2026-10-20). Nothing runs it. To start it, the owner fixes every number below before any result exists, commits it as the study's pre-registration in `results/` and counts its trials into the pool.*

## Question

Does at least one of the four Alpaca long-only books beat a volatility-matched BTC holding gated by the 200-day average, out of sample at 35 bps, with a bootstrap 90 % band of the difference above zero?

## Why now

Every book the autopilots run depends on the BTC gate. breakout_study finds 1.67 with BTC above its 200-day average and -0.74 below it; tsmom_tranches 0.76 and -0.81. fast_strategies says every 4h pick leans on the gate. In regime (M5), the 200-day switch alone on BTC makes 0.79 / 0.71 at 15 / 41 bps with a 32 % drawdown, against 53 % for plain holding. The studies compare the books with ungated BTC (0.74), which is the weaker benchmark. The weekly review calls the autopilots one bet on BTC trend. No study has yet tested the books against the gate on its own.

## Data

The fam_common survivorship-free daily panel with data to 2026-10-14, as in alpaca36 and alpaca_universe, which also supplies BTC's daily closes. The books are taken exactly as they run on Alpaca: breakout_top10, tsmom_top20 and tsmom_tranches with non-Alpaca coins held as cash (the C rows of alpaca_universe), and trend4h_pullback from lab.experiments.fast_maker at its maker base. If fast_maker does not store the pick's daily returns, the pick alone is rerun; that adds no trial. No new data is needed.

## Design

In sample 2020-08-01 to 2023-12-31 (trend4h_pullback uses its own study's in-sample period). Out of sample 2024-01-01 to 2026-10-14. The benchmark G holds BTC at weight k while BTC's daily close at t is above its 200-day average, and cash otherwise, earning day t+1. For each book, k is the ratio of the book's in-sample daily vol to the in-sample daily vol of G at unit weight. It is fixed before any out-of-sample number is seen and capped at 1. D is the book's daily net return minus G's on the same days. The study reports Sharpe and drawdown for each book and for G, D's Sharpe overall and per year, and a stationary bootstrap of D's Sharpe with blocks of 20 days.

## Trials (4)

- Difference series, 4 books x 1 benchmark: 4
- Benchmark G itself, already counted in regime (M5): 0

## Costs

35 bps per unit of one-way turnover on the books and on the gate's own switches, with 70 bps as stress. trend4h_pullback uses its fast_maker base (15 bps maker plus a 3 bps haircut, with the taker fallback) and is also run with every order taken at the close at 35 bps.

## Pass rule

A book beats the gate when all of these hold. D's Sharpe is above 0 at 35 bps, and positive in at least 2 of 2024, 2025 and 2026. The bootstrap 90 % lower bound of D's Sharpe is above 0. D's Sharpe is above 0 at 70 bps. The book's drawdown is at most G's plus 5 percentage points. The book counts as confirmed only if D's deflated p is above 0.95 over 981 trials (977 plus these 4, noise bar about 2.56).

## Kill rule

A book whose D has a Sharpe at or below 0 at 35 bps is written up as 'no better than gated BTC at the same risk', and the owner takes it out of Auto-Pick's candidates. If all four books fail this way, the lab records that its Alpaca book set is gated BTC exposure and stops adding trend variants on Alpaca coins.

## Effort

Under an hour of compute. About two hours of the owner's time.

## What could fool us

The vol-matching ratio is set in sample. If the books' volatility shifted out of sample, G is over- or under-sized and D carries a hidden BTC beta bet, so the out-of-sample vol ratio is reported next to the result. A pass by breakout alone could also rest on 2024, the year that carries it (breakout_study: its Sharpe halves without 2024).

## Built on

`regime`, `alpaca_universe`, `tsmom_tranches`, `breakout_study`, `fast_maker_5m`, `fast_strategies`
