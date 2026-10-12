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

<!-- generated below by lab.experiments.fast_strategies; edit above this line only -->
