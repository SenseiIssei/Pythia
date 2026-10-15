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

<!-- generated below by lab.experiments.memecoins; edit above this line only -->
