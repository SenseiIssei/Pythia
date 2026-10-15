# W7: memecoin strategies on the coins Alpaca lists

`python -m lab.experiments.memecoins`

## Pre-registration (written and committed before the first run)

**Question.** The Alpaca paper account lists six memecoins: BONK, SHIB, WIF,
PEPE, TRUMP and DOGE (0.25 % taker, 0.15 % maker, about 10 bps slippage). Is
there a daily rule on them, with a small dedicated risk budget, that earns its
risk out of sample after costs, against BTC and against the main books? The
markets are dominated by pumps, rug pulls and wash trading, so the bar is the
lab's usual one and drawdowns are reported in full. If nothing passes, the
numbers are written up and no paper book is added.

**Data.** Binance USDT spot daily klines from the data.binance.vision archive
(`lab/klines_daily.py`: monthly 1d zips plus daily zips for the running month),
to the last full UTC day before the run (2026-10-14 expected). Columns used:
close, quote volume and trade count. Delisted pairs stay in the archive. Day
t's close is the 1d kline close; a weight decided at the close of day t earns
day t+1. A coin whose series ends is closed at its last close.

**Universes.**

- **A, the Alpaca memecoins**: DOGE SHIB PEPE BONK WIF TRUMP. First Binance
  days: DOGE 2019-07, SHIB 2021-05, PEPE 2023-05, BONK 2023-12, WIF 2024-03,
  TRUMP 2025-01. Binance lists a memecoin after its first pump, so the
  history starts after the run-up that made it famous. The list is today's
  survivors, chosen with hindsight.
- **M, the survivorship-free twin**: every memecoin with a Binance USDT spot
  archive, chosen by what it is and not by how it did, 24 coins: DOGE SHIB PEPE
  BONK WIF TRUMP FLOKI BOME MEME PEOPLE 1000SATS TURBO NEIRO 1MBABYDOGE PNUT
  ACT DOGS PENGU BROCCOLI714 MUBARAK TST 1000CAT BANANAS31 PUMP. Each day the
  twin's universe is the 6 eligible members with the highest 28-day quote
  volume (point in time). Many of these lost 80 to 99 %.
- Eligible: inside its series, traded that day, at least 60 days since its
  first bar, 28-day mean quote volume of at least 1 M USD.

**Sizing (the risk budget).** Every book is long-only spot, a sleeve sized
for 6 coins: a held coin gets 40 % annual vol over 6 slots (weight =
0.40 / (sigma * sqrt(365)) / 6, at most 1/6), sigma the standard deviation of
the last 30 daily log returns (at least 20). A sleeve fully invested in six
coins therefore runs at about 40 % vol, its exposure 0 to 100 %, the rest cash.
Rotation books (F3) size over their k slots instead. The sleeve is meant as a
small dedicated budget of the account (10 % is the working assumption): the
report gives the sleeve's own numbers and what its worst drawdown would cost
an account holding 10 % in it.

**Families and variants** (each on A; each also on M as its twin):

| family | rule | variants |
|---|---|---|
| F1 breakout | Donchian N/(N/2) on closes (`fam_breakout.breakout_weights`): enter when the close is above the highest close of the previous N days, exit below the lowest of the previous N/2; N in {20, 55}; BTC 200-day gate off or on | 4 |
| F2 trend | time-series momentum: hold while the L-day return is above 0, L in {14, 28, 56}; BTC gate off or on; rebalanced daily | 6 |
| F3 rotation | the top k by 28-day return among the universe, only if that return is above 0, k in {1, 2}, size 0.40 / vol / k; BTC gate on | 2 |
| F4 attention, volume | a volume surge: quote volume of the day at least s times its median over the previous 28 days, s in {2, 3}, and the day closes up; hold h days from the last signal, h in {3, 7}; no gate | 4 |
| F5 attention, trades | the same with Binance's trade count instead of quote volume | 4 |
| F6 hype filters | (a) F2 with L 28 and the gate, but a coin is not held while its volume surge ratio was at least 3 on any of the last 3 days (fade the hype); (b) F1 20/10 with entries only on a volume surge of at least 2 (attention plus trend), no gate | 2 |

22 on A plus their 22 twins.

**Picks.** Per family, the A variant with the best in-sample Sharpe at 35 bps.
The overall pick is the best of the six family picks by the same measure.
Each family pick is also run filled one day late (L, counted).

**Counted trials.** 22 + 22 + 6 = **50 here; the pool is 377 + 50 = 427**
(377 after C16, `results/alpaca_universe.md`, bar 2.43). The prior's variance
is backed out of the published bar (2.43 over 377) and pooled with this
study's 50 trial Sharpes (annual, clipped at +-3), as in C16.

**Split and costs.** In sample 2020-08-01 to 2023-12-31 (thin: DOGE all of
it, SHIB from mid 2021, PEPE from mid 2023; the twin adds FLOKI, PEOPLE, MEME
and 1000SATS), out of sample 2024-01-01 to the data end. Costs per unit of
one-way turnover: **35 bps (Alpaca taker 25 bps plus about 10 bps slippage),
the base**; 15 bps (maker, optimistic); 70 bps (stress). Sharpe annualised
with 365 days.

**Benchmarks (not counted).** BTC buy and hold; BTC with its own 200-day gate
at 35 bps; DOGE buy and hold; the A memecoins and the M twin universe equal
weight, buy and hold, rebalanced daily, no costs. The main books are quoted
from C16 (cash-left on Alpaca, out of sample from 2024 at 35 bps): they are not
re-run here.

**Reported** for every row: Sharpe at 15 / 35 / 70 bps in and out of sample,
CAGR, maximum drawdown, worst month and the longest time under water at 35
bps, average exposure, turnover per year, trades per month, Sharpe per year
2021 to 2026, correlation of daily returns with BTC out of sample, deflated p
over 427 trials and the stationary-bootstrap 90 % band (block 20 days) of the
out-of-sample Sharpe at 35 bps. For each family pick: its share of P&L by coin
out of sample.

**Pass rule** for a paper book (all must hold, for the overall pick):

1. Out-of-sample Sharpe above 0 at 35 bps and at 70 bps, and positive in at
   least 2 of the 3 out-of-sample years (2026 partial).
2. It earns its risk against BTC: out-of-sample Sharpe at 35 bps above BTC
   buy and hold's, and a maximum drawdown at 35 bps below 50 % and below the
   A basket's.
3. Deflated p above 0.95 over all 427 trials.
4. Its twin (M) and its one-day-late fill (L) have an out-of-sample Sharpe
   above 0 at 35 bps.

If the pick passes: a paper book `memes` in lab/paper/families.py
(autopilot_only, a 10 % risk budget in its signal, its evidence() with the
twin's numbers and the caveat that the list is today's and the in-sample
period is DOGE-heavy) with tests. Otherwise this file carries the numbers and
nothing is added.

## Reading (written after the run, 2026-10-15)

**Nothing passes; no paper book.** The pre-registered pick (F2, tsmom 28d
with the BTC gate) makes Sharpe 0.67 out of sample at 35 bps with a 19 %
drawdown: below BTC buy and hold (0.74, drawdown 53 %), deflated p 0.00.

- **Memecoins as such lose.** Every one of the 24 is 43 to 99 % below its
  peak today; the six Alpaca memecoins held equal weight lost 11 % a year from
  2024 with a 91 % drawdown, the 24-coin twin 33 % a year (95 %). DOGE alone:
  85 %.
- **Rules that sit out most of the time are what work.** Every A rule except
  the hype filter is positive out of sample at 35 bps (0.27 to 1.16), with
  drawdowns of 12 to 47 % against 91 % for holding, because the sleeve holds
  on average 4 to 16 % of its capital in memecoins. The twin (24 coins,
  crashed ones included) gives nearly the same numbers, so this is not only
  survivorship of the six.
- **The near miss is F3, top 1 by 28-day return with the BTC gate**: 1.15 at
  35 bps, 0.94 at 70, drawdown 27 %, positive in 2024, 2025 and 2026, twin
  1.11, one day late 1.06. It lost the in-sample pick to F2 by 0.006 Sharpe
  and would have failed anyway on deflation (p 0.01; the bar over 427 trials
  is about 2.35), and its bootstrap band at 35 bps is -0.24 to 2.27. 52 % of
  its P&L is PEPE. Forward evidence would be the honest next step, not money.
- **Attention.** Buying volume or trade-count surges (x2, up day, hold a
  week) makes 0.93 and 0.99 out of sample, but nearly all of it in 2024
  (Sharpe 2.3); 2025 and 2026 are negative. Trade count adds nothing over
  quote volume. Fading the hype (no trend position after a x3 surge) is the
  only negative family (-0.61): the surge days are where the trend money is.
- **Drawdowns at a 10 % budget.** The picks' worst drawdowns (19 to 33 %)
  cost an account holding 10 % in them 2 to 3 %. The worst calendar month of
  a pick was -17 % (F1), the longest time under water 15 to 22 months (29
  for the hype filter).
- **Against the main books** (C16, cash-left on Alpaca, same window): the
  best memecoin rule (F3, 1.15) is level with breakout_top10 (1.17, drawdown
  15 %) at almost twice the drawdown; the pick (0.67) is level with
  tsmom_tranches (0.65, drawdown 9 %) at twice the drawdown.
- **Caveats.** In sample is thin (DOGE alone until mid 2021, at most 3
  memecoins before 2024); Binance lists a memecoin after its first pump, so
  no rule here could have bought the run-up; costs are Alpaca's and do not
  include the wider spreads of thin memecoin books in a crash.

<!-- generated below by lab.experiments.memecoins; edit above this line only -->

## Results (generated 2026-10-15, data to 2026-10-14)

**Verdict: nothing passes, no paper book.** Overall pick (F2 trend): tsmom 28d · BTC gate, out of sample Sharpe 0.67 at 35 bps (15 bps 0.77, 70 bps 0.50), drawdown 19 %; Sharpe 0.67 not above BTC's 0.74; deflated p 0.00 <= 0.95. BTC buy and hold over the same days: Sharpe 0.74. Deflation pool 427 trials (prior 377, here 50); the best noise trial is expected at an annual Sharpe of about 2.35. Out of sample 1018 days, in sample 1248 days with 1 to 3 eligible Alpaca memecoins (3 to 6 out of sample).

### Family picks (A, best in-sample Sharpe at 35 bps)

`account_dd_at_10pct` is what the pick's worst drawdown costs an account holding 10 % in it. `years_pos` counts 2024, 2025, 2026 with a positive Sharpe.

| family | pick | pick_is_35 | pick_oos_15 | pick_oos_35 | pick_oos_70 | pick_dd | account_dd_at_10pct | pick_deflated_p | twin_oos_35 | late_oos_35 | years_pos | passes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| F1 breakout | Donchian 55/27 · BTC gate | 1.22 | 0.65 | 0.63 | 0.61 | 0.24 | 0.02 | 0.00 | 0.66 | 0.28 | 2 | no |
| F2 trend | tsmom 28d · BTC gate | 1.67 | 0.77 | 0.67 | 0.50 | 0.19 | 0.02 | 0.00 | 0.75 | 0.75 | 2 | no |
| F3 rotation | top 1 by 28d return · BTC gate | 1.67 | 1.27 | 1.15 | 0.94 | 0.27 | 0.03 | 0.01 | 1.11 | 1.06 | 3 | no |
| F4 attention, volume | volume surge x2 · up day · hold 7d | 1.02 | 0.98 | 0.93 | 0.84 | 0.33 | 0.03 | 0.00 | 0.92 | 0.86 | 1 | no |
| F5 attention, trades | trades surge x2 · up day · hold 7d | 1.00 | 1.03 | 0.99 | 0.91 | 0.27 | 0.03 | 0.01 | 0.92 | 0.84 | 1 | no |
| F6 hype filters | tsmom 28d · BTC gate · skip after a x3 volume surge | 1.12 | -0.45 | -0.61 | -0.88 | 0.28 | 0.03 | 0.00 | -0.71 | -0.09 | 0 | no |

- F1 breakout: Sharpe 0.63 not above BTC's 0.74; deflated p 0.00 <= 0.95. P&L by coin out of sample: DOGE +22 %, PEPE +17 %, SHIB +16 %, WIF -1 %, BONK -1 %, TRUMP +0 %
- F2 trend: Sharpe 0.67 not above BTC's 0.74; deflated p 0.00 <= 0.95. P&L by coin out of sample: PEPE +13 %, DOGE +13 %, SHIB +8 %, BONK +7 %, WIF +3 %, TRUMP -2 %
- F3 rotation: deflated p 0.01 <= 0.95. P&L by coin out of sample: PEPE +52 %, DOGE +30 %, BONK +15 %, WIF +13 %, SHIB +10 %, TRUMP -5 %
- F4 attention, volume: positive in 1 of 3 years; deflated p 0.00 <= 0.95. P&L by coin out of sample: PEPE +37 %, DOGE +26 %, SHIB +22 %, BONK +12 %, TRUMP -10 %, WIF +4 %
- F5 attention, trades: positive in 1 of 3 years; deflated p 0.01 <= 0.95. P&L by coin out of sample: PEPE +38 %, SHIB +27 %, DOGE +20 %, BONK +9 %, TRUMP -7 %, WIF +5 %
- F6 hype filters: Sharpe not above 0 at 35 and 70 bps; positive in 0 of 3 years; Sharpe -0.61 not above BTC's 0.74; deflated p 0.00 <= 0.95; twin -0.71 / late -0.09. P&L by coin out of sample: BONK -4 %, TRUMP -4 %, WIF -4 %, PEPE -2 %, SHIB +1 %, DOGE +0 %

### Against BTC and the main books (out of sample from 2024, 35 bps)

| book | Sharpe | max drawdown |
|---|---|---|
| BTC buy and hold | 0.74 | 53 % |
| BTC 200-day gate (35 bps) | 0.68 | 33 % |
| DOGE buy and hold | 0.41 | 85 % |
| A memecoins, equal weight | 0.38 | 91 % |
| M twin universe, equal weight | 0.13 | 95 % |
| breakout_top10 (cash-left), from C16 (data to 2026-09-30) | 1.17 | 15 % |
| tsmom_top20 (cash-left), from C16 (data to 2026-09-30) | 0.54 | 9 % |
| tsmom_tranches (cash-left), from C16 (data to 2026-09-30) | 0.65 | 9 % |
| memecoin pick: tsmom 28d · BTC gate | 0.67 | 19 % |

### Every book (in sample 2020-08 to 2023, out of sample from 2024)

A on the six Alpaca memecoins, M its survivorship-free twin (the 6 most liquid of 24 Binance memecoins each day), L a family pick filled one day late. Sharpe at 15 / 35 / 70 bps; CAGR, drawdown, worst calendar month, longest time under water (days), vol and the bootstrap band at 35 bps; benchmarks without costs except the BTC gate.

| universe | family | variant | is_taker 35bps | oos_maker 15bps | oos_taker 35bps | oos_stress 70bps | cagr_35 | dd_35 | worst_month | underwater_days | vol_35 | expo | turnover_yr | trades_month | corr_btc | deflated_p | boot35_p05 | boot35_p95 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| - | benchmark | BTC buy and hold | 0.92 | 0.74 | 0.74 | 0.74 | 0.27 | 0.53 | -0.20 | 373 | 0.47 | None | None | None | 1.00 | None | -0.23 | 1.73 |
| - | benchmark | BTC 200-day gate (35 bps) | 1.04 | 0.68 | 0.68 | 0.68 | 0.20 | 0.33 | -0.18 | 631 | 0.36 | None | None | None | 0.77 | None | -0.43 | 1.70 |
| - | benchmark | DOGE buy and hold | 1.00 | 0.41 | 0.41 | 0.41 | -0.03 | 0.85 | -0.39 | 675 | 0.90 | None | None | None | 0.78 | None | -0.70 | 1.53 |
| - | benchmark | A memecoins, equal weight | 1.09 | 0.38 | 0.38 | 0.38 | -0.11 | 0.91 | -0.39 | 675 | 1.00 | None | None | None | 0.76 | None | -0.76 | 1.48 |
| - | benchmark | M twin universe, equal weight | 1.10 | 0.13 | 0.13 | 0.13 | -0.33 | 0.95 | -0.36 | 944 | 1.04 | None | None | None | 0.73 | None | -0.92 | 1.24 |
| A | F1 breakout | Donchian 20/10 | 0.70 | 1.00 | 0.97 | 0.90 | 0.28 | 0.28 | -0.05 | 449 | 0.30 | 0.14 | 5.45 | 5.92 | 0.34 | 0.00 | -0.41 | 1.95 |
| A | F1 breakout | Donchian 20/10 · BTC gate | 0.66 | 1.19 | 1.16 | 1.11 | 0.34 | 0.20 | -0.04 | 449 | 0.28 | 0.10 | 4.21 | 4.84 | 0.30 | 0.01 | -0.19 | 2.07 |
| A | F1 breakout | Donchian 55/27 | 1.18 | 0.58 | 0.57 | 0.54 | 0.14 | 0.31 | -0.17 | 675 | 0.30 | 0.14 | 2.10 | 2.15 | 0.41 | 0.00 | -0.64 | 1.50 |
| A | F1 breakout | Donchian 55/27 · BTC gate | 1.22 | 0.65 | 0.63 | 0.61 | 0.15 | 0.24 | -0.17 | 675 | 0.29 | 0.11 | 1.84 | 1.97 | 0.39 | 0.00 | -0.56 | 1.52 |
| A | F2 trend | tsmom 14d | 1.23 | 0.44 | 0.27 | -0.02 | 0.04 | 0.47 | -0.15 | 449 | 0.23 | 0.16 | 19.26 | 18.85 | 0.45 | 0.00 | -1.06 | 1.56 |
| A | F2 trend | tsmom 14d · BTC gate | 1.26 | 0.71 | 0.60 | 0.40 | 0.10 | 0.32 | -0.15 | 449 | 0.20 | 0.10 | 10.82 | 11.74 | 0.38 | 0.00 | -0.82 | 1.90 |
| A | F2 trend | tsmom 28d | 1.53 | 0.45 | 0.32 | 0.08 | 0.05 | 0.35 | -0.09 | 449 | 0.21 | 0.15 | 13.78 | 12.79 | 0.44 | 0.00 | -1.02 | 1.48 |
| A | F2 trend | tsmom 28d · BTC gate | 1.67 | 0.77 | 0.67 | 0.50 | 0.11 | 0.19 | -0.07 | 449 | 0.18 | 0.10 | 8.80 | 8.43 | 0.38 | 0.00 | -0.70 | 1.84 |
| A | F2 trend | tsmom 56d | 0.85 | 0.48 | 0.39 | 0.24 | 0.06 | 0.34 | -0.06 | 510 | 0.20 | 0.13 | 8.85 | 7.38 | 0.49 | 0.00 | -0.92 | 1.54 |
| A | F2 trend | tsmom 56d · BTC gate | 0.91 | 0.79 | 0.73 | 0.61 | 0.13 | 0.21 | -0.06 | 510 | 0.19 | 0.10 | 6.08 | 5.29 | 0.46 | 0.00 | -0.54 | 1.81 |
| A | F3 rotation | top 1 by 28d return · BTC gate | 1.67 | 1.27 | 1.15 | 0.94 | 0.35 | 0.27 | -0.12 | 455 | 0.30 | 0.13 | 18.47 | 4.12 | 0.38 | 0.01 | -0.24 | 2.27 |
| A | F3 rotation | top 2 by 28d return · BTC gate | 1.66 | 0.61 | 0.46 | 0.19 | 0.09 | 0.27 | -0.11 | 449 | 0.25 | 0.12 | 18.97 | 7.47 | 0.41 | 0.00 | -0.84 | 1.56 |
| A | F4 attention, volume | volume surge x2 · up day · hold 3d | 0.90 | 1.08 | 1.01 | 0.88 | 0.27 | 0.28 | -0.07 | 449 | 0.27 | 0.08 | 9.93 | 10.58 | 0.30 | 0.00 | -0.50 | 1.98 |
| A | F4 attention, volume | volume surge x2 · up day · hold 7d | 1.02 | 0.98 | 0.93 | 0.84 | 0.28 | 0.33 | -0.05 | 449 | 0.32 | 0.14 | 7.76 | 8.01 | 0.39 | 0.00 | -0.42 | 1.93 |
| A | F4 attention, volume | volume surge x3 · up day · hold 3d | 0.60 | 1.13 | 1.08 | 0.98 | 0.23 | 0.12 | -0.05 | 449 | 0.21 | 0.05 | 5.80 | 6.21 | 0.23 | 0.00 | -0.14 | 1.84 |
| A | F4 attention, volume | volume surge x3 · up day · hold 7d | 0.76 | 0.96 | 0.92 | 0.85 | 0.23 | 0.17 | -0.05 | 449 | 0.25 | 0.08 | 5.04 | 5.14 | 0.30 | 0.00 | -0.26 | 1.75 |
| A | F5 attention, trades | trades surge x2 · up day · hold 3d | 0.69 | 1.14 | 1.07 | 0.96 | 0.28 | 0.19 | -0.06 | 449 | 0.26 | 0.07 | 8.57 | 9.38 | 0.29 | 0.00 | -0.36 | 1.99 |
| A | F5 attention, trades | trades surge x2 · up day · hold 7d | 1.00 | 1.03 | 0.99 | 0.91 | 0.30 | 0.27 | -0.05 | 449 | 0.31 | 0.12 | 6.86 | 7.17 | 0.38 | 0.01 | -0.27 | 1.92 |
| A | F5 attention, trades | trades surge x3 · up day · hold 3d | 0.53 | 1.06 | 1.02 | 0.95 | 0.20 | 0.14 | -0.02 | 450 | 0.20 | 0.04 | 4.26 | 4.72 | 0.23 | 0.00 | -0.38 | 1.83 |
| A | F5 attention, trades | trades surge x3 · up day · hold 7d | 0.70 | 0.87 | 0.84 | 0.78 | 0.19 | 0.19 | -0.02 | 449 | 0.24 | 0.06 | 3.78 | 4.06 | 0.29 | 0.00 | -0.39 | 1.62 |
| A | F6 hype filters | tsmom 28d · BTC gate · skip after a x3 volume surge | 1.12 | -0.45 | -0.61 | -0.88 | -0.08 | 0.28 | -0.07 | 869 | 0.12 | 0.07 | 9.71 | 10.52 | 0.34 | 0.00 | -1.60 | 0.27 |
| A | F6 hype filters | Donchian 20/10 · entry on a x2 volume surge | 0.73 | 1.00 | 0.97 | 0.91 | 0.27 | 0.26 | -0.05 | 449 | 0.29 | 0.12 | 4.59 | 4.72 | 0.32 | 0.00 | -0.46 | 1.94 |
| M | F1 breakout | Donchian 20/10 | 0.64 | 0.94 | 0.91 | 0.84 | 0.28 | 0.30 | -0.07 | 493 | 0.33 | 0.15 | 5.99 | 7.77 | 0.34 | 0.00 | -0.45 | 1.84 |
| M | F1 breakout | Donchian 20/10 · BTC gate | 0.63 | 1.09 | 1.06 | 1.00 | 0.33 | 0.28 | -0.05 | 492 | 0.31 | 0.11 | 4.80 | 6.39 | 0.30 | 0.01 | -0.30 | 2.01 |
| M | F1 breakout | Donchian 55/27 | 1.17 | 0.65 | 0.63 | 0.61 | 0.17 | 0.31 | -0.19 | 675 | 0.34 | 0.16 | 2.31 | 3.02 | 0.41 | 0.00 | -0.48 | 1.50 |
| M | F1 breakout | Donchian 55/27 · BTC gate | 1.22 | 0.67 | 0.66 | 0.64 | 0.18 | 0.28 | -0.19 | 675 | 0.33 | 0.13 | 2.07 | 2.60 | 0.39 | 0.00 | -0.44 | 1.54 |
| M | F2 trend | tsmom 14d | 0.94 | 0.54 | 0.35 | 0.04 | 0.06 | 0.41 | -0.14 | 449 | 0.24 | 0.16 | 21.31 | 23.78 | 0.47 | 0.00 | -1.04 | 1.58 |
| M | F2 trend | tsmom 14d · BTC gate | 0.96 | 0.76 | 0.64 | 0.43 | 0.12 | 0.29 | -0.14 | 485 | 0.21 | 0.10 | 12.50 | 15.24 | 0.40 | 0.00 | -0.81 | 1.92 |
| M | F2 trend | tsmom 28d | 1.32 | 0.62 | 0.48 | 0.25 | 0.08 | 0.31 | -0.09 | 449 | 0.22 | 0.15 | 14.59 | 15.57 | 0.47 | 0.00 | -0.87 | 1.62 |
| M | F2 trend | tsmom 28d · BTC gate | 1.55 | 0.84 | 0.75 | 0.58 | 0.14 | 0.23 | -0.09 | 449 | 0.20 | 0.10 | 9.58 | 10.67 | 0.40 | 0.00 | -0.68 | 1.86 |
| M | F2 trend | tsmom 56d | 0.72 | 0.53 | 0.44 | 0.26 | 0.07 | 0.30 | -0.08 | 675 | 0.22 | 0.14 | 10.69 | 10.64 | 0.52 | 0.00 | -0.88 | 1.55 |
| M | F2 trend | tsmom 56d · BTC gate | 0.80 | 0.80 | 0.73 | 0.60 | 0.14 | 0.19 | -0.07 | 622 | 0.21 | 0.11 | 7.70 | 8.01 | 0.48 | 0.00 | -0.48 | 1.78 |
| M | F3 rotation | top 1 by 28d return · BTC gate | 1.61 | 1.23 | 1.11 | 0.89 | 0.33 | 0.35 | -0.13 | 674 | 0.30 | 0.12 | 18.12 | 4.66 | 0.35 | 0.01 | -0.18 | 2.15 |
| M | F3 rotation | top 2 by 28d return · BTC gate | 1.61 | 0.82 | 0.67 | 0.40 | 0.14 | 0.30 | -0.11 | 869 | 0.24 | 0.11 | 18.36 | 8.84 | 0.38 | 0.00 | -0.72 | 1.83 |
| M | F4 attention, volume | volume surge x2 · up day · hold 3d | 0.73 | 1.00 | 0.93 | 0.81 | 0.25 | 0.27 | -0.05 | 698 | 0.28 | 0.08 | 10.17 | 13.09 | 0.30 | 0.00 | -0.78 | 1.88 |
| M | F4 attention, volume | volume surge x2 · up day · hold 7d | 0.92 | 0.96 | 0.92 | 0.84 | 0.29 | 0.28 | -0.06 | 449 | 0.34 | 0.14 | 7.92 | 10.07 | 0.39 | 0.00 | -0.54 | 1.85 |
| M | F4 attention, volume | volume surge x3 · up day · hold 3d | 0.61 | 1.10 | 1.05 | 0.95 | 0.24 | 0.13 | -0.04 | 396 | 0.23 | 0.05 | 6.27 | 8.19 | 0.24 | 0.00 | -0.24 | 1.82 |
| M | F4 attention, volume | volume surge x3 · up day · hold 7d | 0.78 | 0.98 | 0.95 | 0.88 | 0.25 | 0.19 | -0.05 | 449 | 0.28 | 0.09 | 5.09 | 6.33 | 0.31 | 0.00 | -0.28 | 1.78 |
| M | F5 attention, trades | trades surge x2 · up day · hold 3d | 0.72 | 1.01 | 0.94 | 0.82 | 0.25 | 0.21 | -0.04 | 944 | 0.28 | 0.07 | 9.27 | 12.31 | 0.30 | 0.00 | -0.62 | 1.86 |
| M | F5 attention, trades | trades surge x2 · up day · hold 7d | 1.02 | 0.96 | 0.92 | 0.84 | 0.29 | 0.25 | -0.06 | 698 | 0.34 | 0.13 | 7.24 | 9.35 | 0.38 | 0.00 | -0.41 | 1.83 |
| M | F5 attention, trades | trades surge x3 · up day · hold 3d | 0.56 | 0.96 | 0.92 | 0.85 | 0.20 | 0.17 | -0.03 | 449 | 0.22 | 0.04 | 4.76 | 6.63 | 0.23 | 0.00 | -0.66 | 1.75 |
| M | F5 attention, trades | trades surge x3 · up day · hold 7d | 0.72 | 0.85 | 0.82 | 0.77 | 0.20 | 0.20 | -0.03 | 492 | 0.26 | 0.07 | 4.06 | 5.44 | 0.29 | 0.00 | -0.39 | 1.62 |
| M | F6 hype filters | tsmom 28d · BTC gate · skip after a x3 volume surge | 0.96 | -0.55 | -0.71 | -0.99 | -0.09 | 0.32 | -0.09 | 869 | 0.13 | 0.07 | 10.20 | 12.46 | 0.36 | 0.00 | -1.69 | 0.19 |
| M | F6 hype filters | Donchian 20/10 · entry on a x2 volume surge | 0.70 | 0.95 | 0.92 | 0.87 | 0.27 | 0.30 | -0.05 | 494 | 0.31 | 0.13 | 4.86 | 6.04 | 0.31 | 0.00 | -0.54 | 1.87 |
| L | F1 breakout | Donchian 55/27 · BTC gate · one day late | 1.25 | 0.29 | 0.28 | 0.25 | 0.04 | 0.30 | -0.18 | 675 | 0.27 | 0.11 | 1.85 | 1.97 | 0.38 | 0.00 | -0.90 | 1.18 |
| L | F2 trend | tsmom 28d · BTC gate · one day late | 1.53 | 0.84 | 0.75 | 0.59 | 0.13 | 0.17 | -0.08 | 449 | 0.19 | 0.10 | 8.94 | 8.40 | 0.40 | 0.00 | -0.70 | 1.92 |
| L | F3 rotation | top 1 by 28d return · BTC gate · one day late | 1.67 | 1.17 | 1.06 | 0.86 | 0.34 | 0.27 | -0.12 | 455 | 0.32 | 0.13 | 18.29 | 4.06 | 0.40 | 0.01 | -0.34 | 2.22 |
| L | F4 attention, volume | volume surge x2 · up day · hold 7d · one day late | 0.96 | 0.90 | 0.86 | 0.77 | 0.25 | 0.33 | -0.05 | 449 | 0.31 | 0.14 | 7.75 | 8.01 | 0.38 | 0.00 | -0.56 | 1.87 |
| L | F5 attention, trades | trades surge x2 · up day · hold 7d · one day late | 0.89 | 0.89 | 0.84 | 0.76 | 0.24 | 0.26 | -0.04 | 449 | 0.30 | 0.12 | 6.83 | 7.17 | 0.37 | 0.00 | -0.50 | 1.73 |
| L | F6 hype filters | tsmom 28d · BTC gate · skip after a x3 volume surge · one day late | 0.91 | 0.05 | -0.09 | -0.34 | -0.02 | 0.23 | -0.08 | 869 | 0.14 | 0.07 | 9.86 | 10.49 | 0.39 | 0.00 | -1.25 | 0.91 |

### Per year (Sharpe at 35 bps)

| universe | family | variant | y2021 | y2022 | y2023 | y2024 | y2025 | y2026 |
|---|---|---|---|---|---|---|---|---|
| - | benchmark | BTC buy and hold | 0.98 | -1.29 | 2.35 | 1.76 | 0.05 | 0.03 |
| - | benchmark | BTC 200-day gate (35 bps) | -0.08 | 0.00 | 1.78 | 1.44 | -0.52 | 1.19 |
| - | benchmark | DOGE buy and hold | 1.79 | -0.30 | 0.70 | 1.73 | -0.60 | -0.36 |
| - | benchmark | A memecoins, equal weight | 2.04 | -0.56 | 0.53 | 1.77 | -0.85 | -0.29 |
| - | benchmark | M twin universe, equal weight | 2.04 | -0.34 | 0.36 | 1.31 | -1.08 | -0.00 |
| A | F1 breakout | Donchian 20/10 | 1.40 | -0.39 | 0.31 | 2.10 | 0.10 | -0.93 |
| A | F1 breakout | Donchian 20/10 · BTC gate | 1.14 | 0.00 | 0.27 | 2.08 | 0.26 | -0.06 |
| A | F1 breakout | Donchian 55/27 | 2.13 | -0.46 | 0.63 | 1.39 | -0.60 | -0.38 |
| A | F1 breakout | Donchian 55/27 · BTC gate | 2.18 | 0.00 | 0.58 | 1.31 | -0.49 | 0.14 |
| A | F2 trend | tsmom 14d | 2.49 | 0.58 | 0.91 | 2.10 | -0.70 | -0.90 |
| A | F2 trend | tsmom 14d · BTC gate | 2.36 | 0.00 | 0.97 | 2.01 | -0.74 | 0.59 |
| A | F2 trend | tsmom 28d | 2.34 | 0.22 | 1.63 | 1.94 | -0.63 | -0.98 |
| A | F2 trend | tsmom 28d · BTC gate | 2.30 | 0.00 | 1.68 | 1.83 | -0.43 | 0.23 |
| A | F2 trend | tsmom 56d | 1.86 | -0.05 | 0.16 | 1.70 | -0.64 | -0.40 |
| A | F2 trend | tsmom 56d · BTC gate | 1.80 | 0.00 | 0.10 | 1.77 | -0.60 | 0.72 |
| A | F3 rotation | top 1 by 28d return · BTC gate | 2.43 | 0.00 | 1.35 | 2.05 | 0.56 | 0.20 |
| A | F3 rotation | top 2 by 28d return · BTC gate | 2.30 | 0.00 | 1.57 | 1.19 | -0.28 | -0.01 |
| A | F4 attention, volume | volume surge x2 · up day · hold 3d | 1.43 | 0.19 | 0.96 | 2.33 | -0.88 | -0.24 |
| A | F4 attention, volume | volume surge x2 · up day · hold 7d | 1.97 | -0.36 | 0.94 | 2.33 | -0.97 | -0.65 |
| A | F4 attention, volume | volume surge x3 · up day · hold 3d | 1.03 | 0.42 | 0.37 | 1.99 | -0.07 | 0.19 |
| A | F4 attention, volume | volume surge x3 · up day · hold 7d | 1.56 | -0.18 | 0.34 | 1.89 | -0.05 | -0.39 |
| A | F5 attention, trades | trades surge x2 · up day · hold 3d | 1.35 | 0.14 | 0.38 | 2.04 | -0.02 | 0.03 |
| A | F5 attention, trades | trades surge x2 · up day · hold 7d | 2.03 | -0.34 | 0.75 | 2.20 | -0.45 | -0.51 |
| A | F5 attention, trades | trades surge x3 · up day · hold 3d | 1.06 | -0.04 | -0.02 | 1.95 | -0.13 | -0.20 |
| A | F5 attention, trades | trades surge x3 · up day · hold 7d | 1.69 | -0.53 | 0.19 | 1.67 | -0.30 | -0.23 |
| A | F6 hype filters | tsmom 28d · BTC gate · skip after a x3 volume surge | 1.20 | 0.00 | 1.62 | -0.35 | -0.98 | -0.43 |
| A | F6 hype filters | Donchian 20/10 · entry on a x2 volume surge | 1.44 | -0.63 | 0.43 | 2.16 | -0.07 | -0.93 |
| M | F1 breakout | Donchian 20/10 | 1.40 | -0.51 | 0.21 | 1.76 | -0.26 | 0.08 |
| M | F1 breakout | Donchian 20/10 · BTC gate | 1.14 | 0.00 | 0.19 | 1.84 | -0.04 | 0.38 |
| M | F1 breakout | Donchian 55/27 | 2.13 | -0.69 | 0.51 | 1.22 | -0.32 | 0.19 |
| M | F1 breakout | Donchian 55/27 · BTC gate | 2.18 | 0.00 | 0.47 | 1.14 | -0.21 | 0.46 |
| M | F2 trend | tsmom 14d | 2.49 | 0.32 | 0.61 | 1.67 | -0.88 | -0.20 |
| M | F2 trend | tsmom 14d · BTC gate | 2.36 | 0.00 | 0.63 | 1.72 | -0.83 | 0.92 |
| M | F2 trend | tsmom 28d | 2.34 | -0.17 | 1.45 | 1.71 | -0.50 | -0.62 |
| M | F2 trend | tsmom 28d · BTC gate | 2.30 | 0.00 | 1.52 | 1.59 | -0.29 | 0.41 |
| M | F2 trend | tsmom 56d | 1.86 | -0.38 | 0.31 | 1.25 | -0.27 | -0.19 |
| M | F2 trend | tsmom 56d · BTC gate | 1.80 | 0.00 | 0.17 | 1.22 | -0.22 | 1.04 |
| M | F3 rotation | top 1 by 28d return · BTC gate | 2.43 | 0.00 | 1.11 | 2.18 | -0.40 | 0.93 |
| M | F3 rotation | top 2 by 28d return · BTC gate | 2.30 | 0.00 | 1.43 | 1.40 | -0.21 | 0.33 |
| M | F4 attention, volume | volume surge x2 · up day · hold 3d | 1.43 | 0.01 | 0.48 | 2.11 | -1.02 | -0.30 |
| M | F4 attention, volume | volume surge x2 · up day · hold 7d | 1.97 | -0.32 | 0.49 | 2.06 | -0.93 | -0.31 |
| M | F4 attention, volume | volume surge x3 · up day · hold 3d | 1.03 | 0.26 | 0.60 | 1.92 | -0.05 | 0.04 |
| M | F4 attention, volume | volume surge x3 · up day · hold 7d | 1.56 | -0.17 | 0.54 | 1.85 | 0.05 | -0.42 |
| M | F5 attention, trades | trades surge x2 · up day · hold 3d | 1.35 | -0.00 | 0.73 | 1.89 | -0.29 | -0.13 |
| M | F5 attention, trades | trades surge x2 · up day · hold 7d | 2.03 | -0.26 | 0.80 | 2.01 | -0.74 | -0.31 |
| M | F5 attention, trades | trades surge x3 · up day · hold 3d | 1.06 | -0.22 | 0.52 | 1.84 | -0.23 | -0.44 |
| M | F5 attention, trades | trades surge x3 · up day · hold 7d | 1.69 | -0.38 | 0.44 | 1.61 | -0.17 | -0.33 |
| M | F6 hype filters | tsmom 28d · BTC gate · skip after a x3 volume surge | 1.20 | 0.00 | 1.18 | -0.59 | -0.92 | -0.68 |
| M | F6 hype filters | Donchian 20/10 · entry on a x2 volume surge | 1.44 | -0.68 | 0.40 | 1.76 | -0.14 | -0.01 |
| L | F1 breakout | Donchian 55/27 · BTC gate · one day late | 2.25 | 0.00 | 0.35 | 0.80 | -0.54 | -0.29 |
| L | F2 trend | tsmom 28d · BTC gate · one day late | 2.41 | 0.00 | 1.23 | 1.79 | -0.26 | 0.19 |
| L | F3 rotation | top 1 by 28d return · BTC gate · one day late | 2.59 | 0.00 | 1.30 | 2.17 | 0.19 | -0.05 |
| L | F4 attention, volume | volume surge x2 · up day · hold 7d · one day late | 1.73 | -0.34 | 1.02 | 2.25 | -1.00 | -1.00 |
| L | F5 attention, trades | trades surge x2 · up day · hold 7d · one day late | 1.77 | -0.32 | 0.72 | 2.02 | -0.70 | -0.74 |
| L | F6 hype filters | tsmom 28d · BTC gate · skip after a x3 volume surge · one day late | 1.37 | 0.00 | 0.95 | 0.20 | -0.51 | 0.10 |

### The coins

| coin | first bar | first eligible | last bar | down from its peak |
|---|---|---|---|---|
| DOGE (Alpaca) | 2019-07-05 | 2020-02-25 | 2026-10-14 | 88 % |
| SHIB (Alpaca) | 2021-05-10 | 2021-07-09 | 2026-10-14 | 94 % |
| PEPE (Alpaca) | 2023-05-05 | 2023-07-04 | 2026-10-14 | 85 % |
| BONK (Alpaca) | 2023-12-15 | 2024-02-13 | 2026-10-14 | 94 % |
| WIF (Alpaca) | 2024-03-05 | 2024-05-04 | 2026-10-14 | 96 % |
| TRUMP (Alpaca) | 2025-01-19 | 2025-03-20 | 2026-10-14 | 96 % |
| FLOKI | 2023-05-05 | 2023-07-04 | 2026-10-14 | 92 % |
| BOME | 2024-03-16 | 2024-05-15 | 2026-10-14 | 97 % |
| MEME | 2023-11-03 | 2024-01-02 | 2026-10-14 | 99 % |
| PEOPLE | 2021-12-23 | 2022-02-21 | 2026-10-14 | 95 % |
| 1000SATS | 2023-12-12 | 2024-02-10 | 2026-10-14 | 99 % |
| TURBO | 2024-09-16 | 2024-11-15 | 2026-10-14 | 93 % |
| NEIRO | 2024-09-16 | 2024-11-15 | 2026-10-14 | 97 % |
| 1MBABYDOGE | 2024-09-16 | 2024-11-15 | 2026-10-14 | 93 % |
| PNUT | 2024-11-11 | 2025-01-10 | 2026-10-14 | 97 % |
| ACT | 2024-11-11 | 2025-01-10 | 2026-10-14 | 99 % |
| DOGS | 2024-08-26 | 2024-10-25 | 2026-10-14 | 97 % |
| PENGU | 2024-12-17 | 2025-02-15 | 2026-10-14 | 82 % |
| BROCCOLI714 | 2025-03-27 | 2025-05-26 | 2026-10-14 | 69 % |
| MUBARAK | 2025-03-27 | 2025-05-26 | 2026-10-14 | 43 % |
| TST | 2025-02-09 | 2025-04-10 | 2026-10-14 | 93 % |
| 1000CAT | 2024-12-17 | 2025-02-15 | 2026-10-14 | 96 % |
| BANANAS31 | 2025-03-27 | 2025-05-26 | 2026-10-14 | 82 % |
| PUMP | 2025-09-11 | 2025-11-10 | 2026-10-14 | 45 % |

### Deflation

Prior: 377 trials, variance backed out of the published bar (2.43 over 377); here 50 trials at 35 bps. Pooled bar 2.35 over 427.
