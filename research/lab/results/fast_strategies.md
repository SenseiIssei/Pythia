# Fast strategies on the Alpaca coins (4h and 1h bars)

`python -m lab.experiments.fast_strategies`

## Pre-registration (written before the first run)

**Question.** The owner wants faster, smaller trades. Is there a rule on 4h or
1h bars that trades the 15 coins Alpaca lists and is net positive at Alpaca's
taker cost out of sample, after counting every variant tried? If not, what
trade frequency does the fee level allow?

**Coins.** BTC ETH SOL XRP DOGE ADA AVAX LINK LTC DOT BCH UNI AAVE PEPE FIL
(Alpaca lists these 15 of the lab's 20; TRX SUI NEAR ATOM XLM are not listed).
Prices are Binance USDT spot 1h bars from data.binance.vision; 4h bars are
built from them (00, 04, ..., 20 UTC). This list is today's survivors, so every
pick is also run on a survivorship-free twin: the 15 most liquid eligible
coins of each day from the sweep's panel (all USDT pairs ever listed,
delisted ones included), a coin enterable only while it is in that set.

**Split.** In sample 2020-08-01 to 2023-12-31, out of sample from 2024-01-01 to
the data's end. Daily returns (bars compounded per UTC day), Sharpe annualised
with 365 days, as everywhere in the lab.

**Costs.** Per unit of one-way turnover: Alpaca taker 25 bps plus about 10 bps
measured slippage = **35 bps (the base)**; Alpaca maker 15 bps as the
optimistic case (no slippage, every order filled); gross for the arithmetic.
A round trip at taker cost is 70 bps.

**Execution.** Decided at a bar's close and filled at that close (the lab's
convention); each pick is re-run filled one bar later. Long-only spot.

**Sizing.** Each entry gets min(40 % annual vol / coin vol / 15, 1/15) of the
book and drifts until its exit (as the breakout family). Coin vol: trailing 30
days of bar returns, known at the decision close. A coin whose series ends is
closed at its last close.

**Grid: 64 variants** = 4 families x 4 variants x 2 bar sizes (4h, 1h) x BTC
gate (off, on). The gate: no entries, and everything sold, while BTC's daily
close is below its 200-day average (known at the previous daily close).

| Family | Rule | Variants |
|---|---|---|
| T1 Donchian trend | enter when the close is above the highest close of the previous N bars, exit below the lowest close of the previous N/2 | N 20 or 55 bars; vol filter off or on |
| T2 EMA trend | long while EMA(fast) > EMA(slow) of the close | (12, 48) or (24, 96) bars; vol filter off or on |
| R short-term reversal | enter after a bar whose return is below -k x the coin's bar vol; exit after H bars | k 2 or 3; H 6 or 24 bars |
| V volatility breakout | enter after a bar whose return is above +k x the coin's bar vol; time stop after H bars | k 2 or 3; H 6 or 24 bars |

Vol filter (trend families): no entry while the coin's trailing 24-hour
realised vol is above 1.5 x its trailing 30-day level (no entries into a spike).
Bar vol for R and V: the trailing 30-day standard deviation of bar returns up
to the previous bar (the signal bar itself is not in it).

**Picks.** Per family and bar size, the variant with the best in-sample Sharpe
at 35 bps: 8 picks. Plus one selection-honest series: a walk-forward pick by
quarter from 2024 (each quarter trades the variant with the best Sharpe at 35
bps on all data before it). Counted trials: 64 grid + 8 survivorship-free twins
+ 8 one-bar-late fills + 1 walk-forward = **81**. The pool is the blend
study's 183, the tsmom_tranches Alpaca-only check (1) and these 81: **265**.

**Pass rule** (all must hold, else the result is written up as negative and
no paper book is added):

1. out-of-sample Sharpe > 0 at 35 bps;
2. average net return per trade > 0 bps at 35 bps;
3. deflated p > 0.95 over the full pool of 265 (the 183's Sharpe variance
   backed out of the blend study's bar of 2.45, pooled with this study's
   Sharpes clipped at +-3 as fam_common.deflate does);
4. the survivorship-free twin's out-of-sample Sharpe > 0 at 35 bps;
5. positive in at least 2 of the 3 out-of-sample years (2026 partial).

**Reported** for every variant: trades per day (all coins together), average
gross and net bps per trade, average holding time, Sharpe at 0 / 15 / 35 bps,
CAGR and maximum drawdown at 35 bps, turnover, per-year Sharpe; bootstrap 90 %
band of the picks' Sharpe at 35 bps; and the fee arithmetic: the gross edge per
round trip each family delivers against the 70 bps (taker) and 30 bps (maker)
it has to clear, and the trade frequency that a book with the lab's best gross
edges could afford.

## Findings (written after the run, 2026-10-13)

Data: Binance 1h archives downloaded for this study (677 USDT pairs, delisted
included, 2020-01 to 2026-09); the rebuilt sweep panel has 590 segments
against the sweep's 591 and reproduces the blend study's momentum numbers to
0.01. Out of sample is 1004 days (2024-01-01 to 2026-09-30). BTC bought and
held makes 0.76 over it with a 53 % drawdown.

1. **Nothing passes; no paper book is added.** Every pick fails the deflation
   bar (deflated p 0.00 over 265 trials, bar about 2.74). The bootstrap 90 %
   band of every pick's Sharpe at 35 bps includes 0.
2. **4h is not dead.** The four 4h picks (all with the BTC gate) are net
   positive at taker cost out of sample: Donchian 55/27 1.10 (259 bps net per
   trade), EMA 24/96 1.05 (455 bps), 3-sigma breakout with a 24-bar stop 1.11
   (196 bps), 2-sigma reversal with a 24-bar hold 0.49 (88 bps). They survive
   a one-bar-late fill (0.95 to 1.05) and the survivorship-free twin (0.74 to
   1.21, reversal 0.38). The quarterly walk-forward pick makes 0.71 at 35 bps
   (CAGR 14 %, drawdown 27 %). But all of them lose in 2025 (-0.6 to -0.7),
   every one leans on the BTC gate, and the best of them is less than half of
   the noise bar. This is the same "real family, unproven number" position
   as daily breakout, not a new edge.
3. **1h does not pay at Alpaca's fees.** The 1h picks make 0.06 to 0.65 at
   taker cost, net -5 to +57 bps per trade, and three of four turn negative
   on the survivorship-free twin (-0.37 to 0.14). Hourly Donchian loses 5 bps
   per round trip, in line with the earlier hourly breakout's -28 bps.
4. **What the fee level allows.** A round trip at Alpaca taker cost is 70 bps.
   Out of sample, trades held under 12 hours earn a median 15 bps gross (best
   59): none clears 70. Held 12 to 48 hours, 9 of 28 variants clear it; held 2
   to 7 days, 21 of 22; held a week or more, all 6. In practice the fee level
   allows trades that hold for about two days or longer, which on these 15
   coins means about 0.5 to 1.2 round trips a day across the book (medians of
   the week-plus and 2-to-7-day buckets), one round trip per coin every one
   to four weeks, with a median gross of 1.3 % to 3.2 % per trade. At maker cost (30 bps a round trip) holds of
   12 to 48 hours mostly clear (23 of 28), so faster trading needs resting
   limit orders that actually fill, which this study cannot verify.
5. **Unverified.** Fills at the decision bar's close on Binance prices stand in
   for Alpaca's book; Alpaca's own spreads and the 10 bps slippage figure were
   not re-measured here; the maker case assumes every order fills with no
   adverse selection. The deflation pool's prior variance is backed out of the
   blend study's published bar, and its mean is the sweep's 100 trials only.

<!-- generated below by lab.experiments.fast_strategies; edit above this line only -->

## Results (generated 2026-10-13, data to 2026-09-30)

**Verdict: nothing passes.** 36 of 64 variants have an out-of-sample Sharpe above 0 at taker cost (35 bps), 36 make money per trade after it, 54 are positive at maker cost (15 bps) and 62 before any cost. The best out-of-sample variant at taker cost (vol breakout 3 sigma · stop 24 bars · 4h · BTC gate, picked after the fact) makes 1.11. The quarterly walk-forward pick makes 0.71 at 35 bps (drawdown 27 %). Deflation pool 265 trials (prior 184, here 81); the best noise trial is expected at an annual Sharpe of about 2.74.

### The picks, judged against the pass rule

Per family and bar size, the best in-sample Sharpe at 35 bps. `trades_day` counts round trips across all 15 coins per day out of sample; `net_bps_trade` is the average round trip's price return minus 70 bps. `twin_oos_35` is the survivorship-free twin, `late_oos_35` the pick filled one bar late.

| variant | trades_day | net_bps_trade | oos_taker 35bps | oos_maker 15bps | dd_taker 35bps | y2024 | y2025 | y2026 | deflated_p | boot35_p05 | boot35_p95 | twin_oos_35 | late_oos_35 | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Donchian 55/27 · 4h · BTC gate | 0.52 | 259 | 1.10 | 1.23 | 0.24 | 2.09 | -0.62 | 1.37 | 0.00 | -0.19 | 2.20 | 0.87 | 1.03 | fails: deflated p 0.00 <= 0.95 |
| EMA 24/96 · 4h · BTC gate | 0.41 | 455 | 1.05 | 1.13 | 0.30 | 1.90 | -0.67 | 1.34 | 0.00 | -0.34 | 2.19 | 0.74 | 0.95 | fails: deflated p 0.00 <= 0.95 |
| reversal 2 sigma · hold 24 bars · 4h · BTC gate | 0.81 | 87.67 | 0.49 | 0.77 | 0.24 | 1.51 | -0.72 | 2.46 | 0.00 | -0.78 | 1.92 | 0.38 | 0.53 | fails: deflated p 0.00 <= 0.95 |
| vol breakout 3 sigma · stop 24 bars · 4h · BTC gate | 0.41 | 196 | 1.11 | 1.29 | 0.11 | 2.77 | -0.72 | 1.41 | 0.00 | -0.05 | 2.16 | 1.21 | 1.05 | fails: deflated p 0.00 <= 0.95 |
| Donchian 55/27 · 1h · BTC gate | 1.83 | -4.93 | 0.15 | 0.68 | 0.25 | 0.84 | -1.16 | 1.06 | 0.00 | -1.06 | 1.20 | -0.33 | 0.09 | fails: net -5 bps per trade; deflated p 0.00 <= 0.95; survivorship-free twin -0.33 |
| EMA 24/96 · 1h · BTC gate | 1.46 | 56.35 | 0.63 | 0.97 | 0.28 | 1.73 | -1.13 | 1.34 | 0.00 | -0.76 | 1.77 | 0.14 | 0.56 | fails: deflated p 0.00 <= 0.95 |
| reversal 3 sigma · hold 24 bars · 1h · BTC gate | 1.21 | 22.92 | 0.06 | 0.61 | 0.18 | 0.93 | -1.05 | 1.25 | 0.00 | -0.80 | 1.15 | -0.37 | 0.17 | fails: deflated p 0.00 <= 0.95; survivorship-free twin -0.37 |
| vol breakout 3 sigma · stop 24 bars · 1h · BTC gate | 1.25 | 56.51 | 0.65 | 1.25 | 0.11 | 1.48 | -0.44 | 1.18 | 0.00 | -0.43 | 1.57 | 0.01 | 0.38 | fails: deflated p 0.00 <= 0.95 |

### Fee arithmetic: what a round trip earns before costs, by holding time

Across all 64 variants out of sample. A round trip has to clear 70 bps at Alpaca taker cost and 30 bps at maker cost.

| hold | variants | median_trades_day | median_gross_bps | best_gross_bps | clear_taker | clear_maker |
|---|---|---|---|---|---|---|
| 0 to 12 h | 8 | 3.41 | 14.66 | 58.74 | 0 | 2 |
| 12 to 48 h | 28 | 2.41 | 52.71 | 192 | 9 | 23 |
| 48 to 168 h | 22 | 1.16 | 126 | 329 | 21 | 22 |
| 168 h and more | 6 | 0.56 | 324 | 525 | 6 | 6 |

### Walk-forward pick by quarter

- 2024Q1: EMA 24/96 · 4h · BTC gate
- 2024Q2: EMA 24/96 · 4h · BTC gate
- 2024Q3: EMA 24/96 · 4h · BTC gate
- 2024Q4: vol breakout 3 sigma · stop 24 bars · 4h · BTC gate
- 2025Q1: vol breakout 3 sigma · stop 24 bars · 4h · BTC gate
- 2025Q2: EMA 24/96 · 4h · BTC gate
- 2025Q3: vol breakout 3 sigma · stop 24 bars · 4h · BTC gate
- 2025Q4: EMA 24/96 · 4h · BTC gate
- 2026Q1: EMA 24/96 · 4h · BTC gate
- 2026Q2: EMA 24/96 · 4h · BTC gate
- 2026Q3: EMA 24/96 · 4h · BTC gate

### All 4h variants (out of sample unless marked is_)

| variant | trades_day | hold_h | gross_bps_trade | net_bps_trade | net_bps_trade_maker | is_taker 35bps | oos_gross | oos_maker 15bps | oos_taker 35bps | dd_taker 35bps | cagr_taker 35bps | turnover_yr |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| reversal 2 sigma · hold 24 bars · 4h | 1.31 | 95.75 | 96.43 | 26.43 | 66.43 | 0.37 | 0.61 | 0.35 | -0.00 | 0.41 | -0.02 | 36.98 |
| reversal 2 sigma · hold 24 bars · 4h · BTC gate | 0.81 | 89.00 | 158 | 87.67 | 128 | 0.69 | 0.98 | 0.77 | 0.49 | 0.24 | 0.06 | 21.51 |
| reversal 2 sigma · hold 6 bars · 4h | 1.88 | 24.00 | 62.81 | -7.19 | 32.81 | -0.25 | 0.87 | 0.28 | -0.51 | 0.37 | -0.08 | 53.03 |
| reversal 2 sigma · hold 6 bars · 4h · BTC gate | 1.11 | 23.49 | 85.70 | 15.70 | 55.70 | -0.12 | 0.99 | 0.59 | 0.05 | 0.22 | -0.00 | 29.64 |
| reversal 3 sigma · hold 24 bars · 4h | 0.53 | 96.00 | 222 | 152 | 192 | 0.05 | 0.83 | 0.68 | 0.48 | 0.27 | 0.07 | 15.64 |
| reversal 3 sigma · hold 24 bars · 4h · BTC gate | 0.31 | 91.75 | 312 | 242 | 282 | 0.59 | 1.00 | 0.89 | 0.74 | 0.16 | 0.08 | 8.79 |
| reversal 3 sigma · hold 6 bars · 4h | 0.61 | 24.00 | 148 | 77.80 | 118 | -0.05 | 1.09 | 0.79 | 0.39 | 0.13 | 0.03 | 18.34 |
| reversal 3 sigma · hold 6 bars · 4h · BTC gate | 0.35 | 23.68 | 192 | 122 | 162 | 0.28 | 0.96 | 0.77 | 0.51 | 0.10 | 0.04 | 9.97 |
| Donchian 20/10 · 4h | 1.95 | 63.77 | 74.19 | 4.19 | 44.19 | 0.70 | 1.16 | 0.77 | 0.26 | 0.44 | 0.03 | 52.71 |
| Donchian 20/10 · 4h · BTC gate | 1.28 | 62.10 | 98.95 | 28.95 | 68.95 | 1.06 | 1.20 | 0.93 | 0.56 | 0.23 | 0.09 | 33.21 |
| Donchian 20/10 · vol filter · 4h | 1.83 | 62.13 | 71.07 | 1.07 | 41.07 | 0.55 | 1.17 | 0.77 | 0.24 | 0.39 | 0.03 | 49.21 |
| Donchian 20/10 · vol filter · 4h · BTC gate | 1.21 | 60.10 | 79.63 | 9.63 | 49.63 | 0.91 | 1.08 | 0.78 | 0.38 | 0.21 | 0.05 | 30.94 |
| Donchian 55/27 · 4h | 0.71 | 173 | 226 | 156 | 196 | 1.41 | 1.17 | 1.04 | 0.86 | 0.34 | 0.18 | 19.82 |
| Donchian 55/27 · 4h · BTC gate | 0.52 | 165 | 329 | 259 | 299 | 1.45 | 1.33 | 1.23 | 1.10 | 0.24 | 0.23 | 13.75 |
| Donchian 55/27 · vol filter · 4h | 0.65 | 170 | 211 | 141 | 181 | 1.25 | 1.12 | 0.98 | 0.80 | 0.29 | 0.15 | 17.63 |
| Donchian 55/27 · vol filter · 4h · BTC gate | 0.48 | 160 | 271 | 201 | 241 | 1.25 | 1.15 | 1.05 | 0.91 | 0.25 | 0.16 | 12.60 |
| EMA 12/48 · 4h | 1.17 | 140 | 127 | 56.60 | 96.60 | 1.44 | 0.98 | 0.80 | 0.56 | 0.49 | 0.12 | 31.89 |
| EMA 12/48 · 4h · BTC gate | 0.77 | 146 | 250 | 180 | 220 | 1.42 | 1.27 | 1.15 | 0.98 | 0.30 | 0.24 | 19.89 |
| EMA 12/48 · vol filter · 4h | 1.16 | 139 | 117 | 46.86 | 86.86 | 1.38 | 0.94 | 0.75 | 0.50 | 0.47 | 0.10 | 31.43 |
| EMA 12/48 · vol filter · 4h · BTC gate | 0.76 | 145 | 232 | 162 | 202 | 1.39 | 1.20 | 1.07 | 0.90 | 0.28 | 0.20 | 19.57 |
| EMA 24/96 · 4h | 0.56 | 283 | 336 | 266 | 306 | 1.71 | 1.02 | 0.94 | 0.83 | 0.37 | 0.22 | 15.50 |
| EMA 24/96 · 4h · BTC gate | 0.41 | 274 | 525 | 455 | 495 | 1.76 | 1.19 | 1.13 | 1.05 | 0.30 | 0.28 | 11.16 |
| EMA 24/96 · vol filter · 4h | 0.55 | 281 | 311 | 241 | 281 | 1.67 | 0.97 | 0.89 | 0.78 | 0.37 | 0.19 | 15.37 |
| EMA 24/96 · vol filter · 4h · BTC gate | 0.41 | 272 | 490 | 420 | 460 | 1.73 | 1.13 | 1.07 | 0.98 | 0.29 | 0.25 | 11.03 |
| vol breakout 2 sigma · stop 24 bars · 4h | 1.34 | 95.88 | 87.93 | 17.93 | 57.93 | 1.08 | 0.83 | 0.56 | 0.20 | 0.46 | 0.02 | 37.24 |
| vol breakout 2 sigma · stop 24 bars · 4h · BTC gate | 0.79 | 94.32 | 200 | 130 | 170 | 1.52 | 1.45 | 1.27 | 1.02 | 0.14 | 0.17 | 21.15 |
| vol breakout 2 sigma · stop 6 bars · 4h | 1.96 | 24.00 | 40.44 | -29.56 | 10.44 | 0.19 | 0.75 | 0.12 | -0.74 | 0.40 | -0.10 | 54.93 |
| vol breakout 2 sigma · stop 6 bars · 4h · BTC gate | 1.20 | 23.99 | 68.82 | -1.18 | 38.82 | 0.69 | 1.06 | 0.61 | -0.00 | 0.18 | -0.01 | 32.66 |
| vol breakout 3 sigma · stop 24 bars · 4h | 0.63 | 95.75 | 161 | 91.25 | 131 | 1.26 | 1.09 | 0.91 | 0.67 | 0.29 | 0.09 | 17.91 |
| vol breakout 3 sigma · stop 24 bars · 4h · BTC gate | 0.41 | 94.49 | 266 | 196 | 236 | 1.62 | 1.42 | 1.29 | 1.11 | 0.11 | 0.14 | 11.42 |
| vol breakout 3 sigma · stop 6 bars · 4h | 0.78 | 24.00 | 54.18 | -15.82 | 24.18 | 0.46 | 0.70 | 0.31 | -0.23 | 0.22 | -0.02 | 22.09 |
| vol breakout 3 sigma · stop 6 bars · 4h · BTC gate | 0.52 | 24.00 | 83.62 | 13.62 | 53.62 | 0.84 | 0.94 | 0.64 | 0.23 | 0.10 | 0.01 | 14.57 |

### All 1h variants (out of sample unless marked is_)

| variant | trades_day | hold_h | gross_bps_trade | net_bps_trade | net_bps_trade_maker | is_taker 35bps | oos_gross | oos_maker 15bps | oos_taker 35bps | dd_taker 35bps | cagr_taker 35bps | turnover_yr |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| reversal 2 sigma · hold 24 bars · 1h | 4.69 | 24.00 | 33.21 | -36.79 | 3.21 | -0.76 | 0.77 | -0.20 | -1.47 | 0.66 | -0.27 | 126 |
| reversal 2 sigma · hold 24 bars · 1h · BTC gate | 2.84 | 23.68 | 40.88 | -29.12 | 10.88 | -0.13 | 0.81 | 0.13 | -0.77 | 0.44 | -0.13 | 72.12 |
| reversal 2 sigma · hold 6 bars · 1h | 6.88 | 6.00 | 10.75 | -59.25 | -19.25 | -3.18 | 0.51 | -1.58 | -4.18 | 0.80 | -0.45 | 185 |
| reversal 2 sigma · hold 6 bars · 1h · BTC gate | 4.21 | 5.99 | 9.74 | -60.26 | -20.26 | -1.83 | 0.51 | -1.14 | -3.17 | 0.60 | -0.28 | 107 |
| reversal 3 sigma · hold 24 bars · 1h | 2.05 | 23.99 | 73.20 | 3.20 | 43.20 | -0.04 | 1.05 | 0.44 | -0.37 | 0.33 | -0.06 | 56.90 |
| reversal 3 sigma · hold 24 bars · 1h · BTC gate | 1.21 | 23.61 | 92.92 | 22.92 | 62.92 | 0.43 | 1.03 | 0.61 | 0.06 | 0.18 | -0.00 | 32.07 |
| reversal 3 sigma · hold 6 bars · 1h | 2.54 | 6.00 | 9.11 | -60.89 | -20.89 | -1.76 | -0.01 | -1.03 | -2.31 | 0.50 | -0.22 | 70.60 |
| reversal 3 sigma · hold 6 bars · 1h · BTC gate | 1.48 | 6.00 | 5.32 | -64.68 | -24.68 | -0.82 | -0.04 | -0.71 | -1.56 | 0.33 | -0.13 | 39.07 |
| Donchian 20/10 · 1h | 8.05 | 16.07 | 17.41 | -52.59 | -12.59 | -3.26 | 1.06 | -0.54 | -2.65 | 0.82 | -0.42 | 210 |
| Donchian 20/10 · 1h · BTC gate | 4.86 | 16.23 | 26.45 | -43.55 | -3.55 | -1.79 | 1.27 | 0.11 | -1.42 | 0.55 | -0.21 | 120 |
| Donchian 20/10 · vol filter · 1h | 7.73 | 15.98 | 15.04 | -54.96 | -14.96 | -3.34 | 0.99 | -0.64 | -2.77 | 0.82 | -0.42 | 202 |
| Donchian 20/10 · vol filter · 1h · BTC gate | 4.66 | 16.05 | 17.09 | -52.91 | -12.91 | -1.88 | 0.99 | -0.35 | -2.10 | 0.57 | -0.25 | 115 |
| Donchian 55/27 · 1h | 2.87 | 43.00 | 45.15 | -24.85 | 15.15 | 0.04 | 0.98 | 0.41 | -0.35 | 0.50 | -0.09 | 75.78 |
| Donchian 55/27 · 1h · BTC gate | 1.83 | 42.53 | 65.07 | -4.93 | 35.07 | 0.72 | 1.09 | 0.68 | 0.15 | 0.25 | 0.01 | 45.68 |
| Donchian 55/27 · vol filter · 1h | 2.76 | 42.41 | 51.25 | -18.75 | 21.25 | -0.00 | 1.10 | 0.53 | -0.23 | 0.47 | -0.06 | 73.04 |
| Donchian 55/27 · vol filter · 1h · BTC gate | 1.74 | 41.85 | 59.74 | -10.26 | 29.74 | 0.63 | 1.05 | 0.60 | 0.02 | 0.24 | -0.01 | 43.27 |
| EMA 12/48 · 1h | 4.60 | 37.51 | 26.13 | -43.87 | -3.87 | -0.01 | 0.84 | 0.08 | -0.91 | 0.68 | -0.22 | 119 |
| EMA 12/48 · 1h · BTC gate | 2.81 | 38.66 | 49.95 | -20.05 | 19.95 | 0.61 | 1.10 | 0.58 | -0.10 | 0.35 | -0.04 | 68.46 |
| EMA 12/48 · vol filter · 1h | 4.52 | 37.42 | 32.72 | -37.28 | 2.72 | 0.01 | 1.00 | 0.24 | -0.75 | 0.65 | -0.19 | 117 |
| EMA 12/48 · vol filter · 1h · BTC gate | 2.77 | 38.27 | 47.49 | -22.51 | 17.49 | 0.63 | 1.07 | 0.52 | -0.20 | 0.32 | -0.05 | 67.20 |
| EMA 24/96 · 1h | 2.29 | 73.49 | 69.19 | -0.81 | 39.19 | 1.04 | 0.96 | 0.58 | 0.09 | 0.55 | -0.01 | 59.67 |
| EMA 24/96 · 1h · BTC gate | 1.46 | 75.46 | 126 | 56.35 | 96.35 | 1.22 | 1.23 | 0.97 | 0.63 | 0.28 | 0.12 | 35.80 |
| EMA 24/96 · vol filter · 1h | 2.27 | 72.98 | 70.79 | 0.79 | 40.79 | 1.01 | 1.00 | 0.62 | 0.12 | 0.53 | 0.00 | 59.08 |
| EMA 24/96 · vol filter · 1h · BTC gate | 1.44 | 74.51 | 115 | 45.35 | 85.35 | 1.20 | 1.16 | 0.89 | 0.53 | 0.25 | 0.09 | 35.29 |
| vol breakout 2 sigma · stop 24 bars · 1h | 4.66 | 23.98 | 49.19 | -20.81 | 19.19 | -0.35 | 1.33 | 0.33 | -1.03 | 0.59 | -0.19 | 125 |
| vol breakout 2 sigma · stop 24 bars · 1h · BTC gate | 2.83 | 23.86 | 70.60 | 0.60 | 40.60 | 0.15 | 1.50 | 0.78 | -0.20 | 0.32 | -0.04 | 72.13 |
| vol breakout 2 sigma · stop 6 bars · 1h | 6.91 | 6.00 | 18.57 | -51.43 | -11.43 | -3.88 | 1.33 | -1.14 | -4.47 | 0.75 | -0.39 | 185 |
| vol breakout 2 sigma · stop 6 bars · 1h · BTC gate | 4.24 | 5.99 | 26.29 | -43.71 | -3.71 | -3.15 | 1.53 | -0.36 | -2.97 | 0.50 | -0.22 | 108 |
| vol breakout 3 sigma · stop 24 bars · 1h | 2.06 | 23.99 | 103 | 32.69 | 72.69 | 0.15 | 1.74 | 1.12 | 0.27 | 0.27 | 0.03 | 55.97 |
| vol breakout 3 sigma · stop 24 bars · 1h · BTC gate | 1.25 | 23.92 | 127 | 56.51 | 96.51 | 0.84 | 1.68 | 1.25 | 0.65 | 0.11 | 0.06 | 32.56 |
| vol breakout 3 sigma · stop 6 bars · 1h | 2.61 | 6.00 | 44.82 | -25.18 | 14.82 | -2.12 | 1.70 | 0.27 | -1.71 | 0.30 | -0.12 | 70.58 |
| vol breakout 3 sigma · stop 6 bars · 1h · BTC gate | 1.61 | 6.00 | 58.74 | -11.26 | 28.74 | -1.46 | 1.69 | 0.70 | -0.72 | 0.12 | -0.04 | 41.57 |

### Checks on the picks

| variant | trades_day | hold_h | gross_bps_trade | net_bps_trade | net_bps_trade_maker | is_taker 35bps | oos_gross | oos_maker 15bps | oos_taker 35bps | dd_taker 35bps | cagr_taker 35bps | turnover_yr |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Donchian 55/27 · 4h · BTC gate · survivorship-free top 15 | 0.51 | 162 | 115 | 45.00 | 85.00 | 0.99 | 1.13 | 1.02 | 0.87 | 0.22 | 0.14 | 12.13 |
| EMA 24/96 · 4h · BTC gate · survivorship-free top 15 | 0.47 | 275 | 155 | 84.98 | 125 | 1.32 | 0.91 | 0.84 | 0.74 | 0.26 | 0.15 | 10.59 |
| reversal 2 sigma · hold 24 bars · 4h · BTC gate · survivorship-free top 15 | 0.72 | 88.94 | 157 | 86.86 | 127 | 0.58 | 0.89 | 0.67 | 0.38 | 0.20 | 0.04 | 18.27 |
| vol breakout 3 sigma · stop 24 bars · 4h · BTC gate · survivorship-free top 15 | 0.35 | 94.39 | 270 | 200 | 240 | 1.25 | 1.58 | 1.42 | 1.21 | 0.05 | 0.10 | 9.21 |
| Donchian 55/27 · 1h · BTC gate · survivorship-free top 15 | 1.83 | 41.42 | 12.20 | -57.80 | -17.80 | 0.19 | 0.75 | 0.28 | -0.33 | 0.20 | -0.05 | 41.54 |
| EMA 24/96 · 1h · BTC gate · survivorship-free top 15 | 1.54 | 72.63 | 38.22 | -31.78 | 8.22 | 0.91 | 0.84 | 0.54 | 0.14 | 0.26 | 0.01 | 34.42 |
| reversal 3 sigma · hold 24 bars · 1h · BTC gate · survivorship-free top 15 | 1.04 | 23.57 | 51.72 | -18.28 | 21.72 | 0.31 | 0.74 | 0.26 | -0.37 | 0.15 | -0.04 | 27.47 |
| vol breakout 3 sigma · stop 24 bars · 1h · BTC gate · survivorship-free top 15 | 1.16 | 23.87 | 56.93 | -13.07 | 26.93 | 0.45 | 1.29 | 0.75 | 0.01 | 0.08 | -0.00 | 28.23 |
| Donchian 55/27 · 4h · BTC gate · filled one bar late | 0.52 | 165 | 307 | 237 | 277 | 1.35 | 1.26 | 1.17 | 1.03 | 0.26 | 0.21 | 13.71 |
| EMA 24/96 · 4h · BTC gate · filled one bar late | 0.41 | 274 | 494 | 424 | 464 | 1.77 | 1.09 | 1.03 | 0.95 | 0.29 | 0.25 | 11.15 |
| reversal 2 sigma · hold 24 bars · 4h · BTC gate · filled one bar late | 0.81 | 88.97 | 172 | 102 | 142 | 0.74 | 1.03 | 0.81 | 0.53 | 0.21 | 0.07 | 21.52 |
| vol breakout 3 sigma · stop 24 bars · 4h · BTC gate · filled one bar late | 0.41 | 94.46 | 242 | 172 | 212 | 1.63 | 1.37 | 1.23 | 1.05 | 0.12 | 0.13 | 11.41 |
| Donchian 55/27 · 1h · BTC gate · filled one bar late | 1.83 | 42.53 | 62.46 | -7.54 | 32.46 | 0.66 | 1.04 | 0.63 | 0.09 | 0.28 | 0.00 | 45.68 |
| EMA 24/96 · 1h · BTC gate · filled one bar late | 1.46 | 75.46 | 118 | 47.99 | 87.99 | 1.24 | 1.16 | 0.90 | 0.56 | 0.29 | 0.10 | 35.77 |
| reversal 3 sigma · hold 24 bars · 1h · BTC gate · filled one bar late | 1.21 | 23.61 | 100 | 30.03 | 70.03 | 0.11 | 1.19 | 0.75 | 0.17 | 0.20 | 0.01 | 32.10 |
| vol breakout 3 sigma · stop 24 bars · 1h · BTC gate · filled one bar late | 1.25 | 23.92 | 105 | 34.52 | 74.52 | 0.63 | 1.46 | 1.01 | 0.38 | 0.11 | 0.03 | 32.54 |

### Deflation pool

Prior: 184 trials, variance of their daily Sharpes backed out of the blend study's bar (2.45 over 183), mean -0.08 (the sweep's 100). Here: 81 trials at 35 bps, mean -0.08, clipped at +-3. Pooled: bar 2.74 over 265.

Trials counted here: Donchian 20/10 · 4h; Donchian 20/10 · 4h · BTC gate; Donchian 20/10 · vol filter · 4h; Donchian 20/10 · vol filter · 4h · BTC gate; Donchian 55/27 · 4h; Donchian 55/27 · 4h · BTC gate; Donchian 55/27 · vol filter · 4h; Donchian 55/27 · vol filter · 4h · BTC gate; EMA 12/48 · 4h; EMA 12/48 · 4h · BTC gate; EMA 12/48 · vol filter · 4h; EMA 12/48 · vol filter · 4h · BTC gate; EMA 24/96 · 4h; EMA 24/96 · 4h · BTC gate; EMA 24/96 · vol filter · 4h; EMA 24/96 · vol filter · 4h · BTC gate; reversal 2 sigma · hold 6 bars · 4h; reversal 2 sigma · hold 6 bars · 4h · BTC gate; reversal 2 sigma · hold 24 bars · 4h; reversal 2 sigma · hold 24 bars · 4h · BTC gate; reversal 3 sigma · hold 6 bars · 4h; reversal 3 sigma · hold 6 bars · 4h · BTC gate; reversal 3 sigma · hold 24 bars · 4h; reversal 3 sigma · hold 24 bars · 4h · BTC gate; vol breakout 2 sigma · stop 6 bars · 4h; vol breakout 2 sigma · stop 6 bars · 4h · BTC gate; vol breakout 2 sigma · stop 24 bars · 4h; vol breakout 2 sigma · stop 24 bars · 4h · BTC gate; vol breakout 3 sigma · stop 6 bars · 4h; vol breakout 3 sigma · stop 6 bars · 4h · BTC gate; vol breakout 3 sigma · stop 24 bars · 4h; vol breakout 3 sigma · stop 24 bars · 4h · BTC gate; Donchian 55/27 · 4h · BTC gate · survivorship-free top 15; Donchian 55/27 · 4h · BTC gate · filled one bar late; EMA 24/96 · 4h · BTC gate · survivorship-free top 15; EMA 24/96 · 4h · BTC gate · filled one bar late; reversal 2 sigma · hold 24 bars · 4h · BTC gate · survivorship-free top 15; reversal 2 sigma · hold 24 bars · 4h · BTC gate · filled one bar late; vol breakout 3 sigma · stop 24 bars · 4h · BTC gate · survivorship-free top 15; vol breakout 3 sigma · stop 24 bars · 4h · BTC gate · filled one bar late; Donchian 20/10 · 1h; Donchian 20/10 · 1h · BTC gate; Donchian 20/10 · vol filter · 1h; Donchian 20/10 · vol filter · 1h · BTC gate; Donchian 55/27 · 1h; Donchian 55/27 · 1h · BTC gate; Donchian 55/27 · vol filter · 1h; Donchian 55/27 · vol filter · 1h · BTC gate; EMA 12/48 · 1h; EMA 12/48 · 1h · BTC gate; EMA 12/48 · vol filter · 1h; EMA 12/48 · vol filter · 1h · BTC gate; EMA 24/96 · 1h; EMA 24/96 · 1h · BTC gate; EMA 24/96 · vol filter · 1h; EMA 24/96 · vol filter · 1h · BTC gate; reversal 2 sigma · hold 6 bars · 1h; reversal 2 sigma · hold 6 bars · 1h · BTC gate; reversal 2 sigma · hold 24 bars · 1h; reversal 2 sigma · hold 24 bars · 1h · BTC gate; reversal 3 sigma · hold 6 bars · 1h; reversal 3 sigma · hold 6 bars · 1h · BTC gate; reversal 3 sigma · hold 24 bars · 1h; reversal 3 sigma · hold 24 bars · 1h · BTC gate; vol breakout 2 sigma · stop 6 bars · 1h; vol breakout 2 sigma · stop 6 bars · 1h · BTC gate; vol breakout 2 sigma · stop 24 bars · 1h; vol breakout 2 sigma · stop 24 bars · 1h · BTC gate; vol breakout 3 sigma · stop 6 bars · 1h; vol breakout 3 sigma · stop 6 bars · 1h · BTC gate; vol breakout 3 sigma · stop 24 bars · 1h; vol breakout 3 sigma · stop 24 bars · 1h · BTC gate; Donchian 55/27 · 1h · BTC gate · survivorship-free top 15; Donchian 55/27 · 1h · BTC gate · filled one bar late; EMA 24/96 · 1h · BTC gate · survivorship-free top 15; EMA 24/96 · 1h · BTC gate · filled one bar late; reversal 3 sigma · hold 24 bars · 1h · BTC gate · survivorship-free top 15; reversal 3 sigma · hold 24 bars · 1h · BTC gate · filled one bar late; vol breakout 3 sigma · stop 24 bars · 1h · BTC gate · survivorship-free top 15; vol breakout 3 sigma · stop 24 bars · 1h · BTC gate · filled one bar late; walk-forward pick by quarter.
