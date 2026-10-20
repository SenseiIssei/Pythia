# X15 candlestick patterns: pre-registration

Written and committed on 2026-10-20 before any number below was computed on
real data. What was known when this was written: the lab README (most
short-term and pattern ideas failed after costs: reversal, seasonality,
fast 4h and 1h rules, intraday equities, the M8 direction model), the pattern
library `lab/candles` and its tests on hand-built bars (no real bars), and
which data exist on the PC (coverage only, no outcome): hourly Binance klines
for every USDT pair to 2026-10-19, the point-in-time S&P 500 file of
`equities_ranking` (daily OHLCV and adjusted close, 1968 to 2026-10-16; rows
spliced from CRSP have no open, high or low), 25 US ETFs in the same file,
and the X11 M2 panel and v2 scores (581,663 coin-days, 2020-03 to
2026-10-19). Nothing in this file is changed after the first result exists;
anything added later goes into `candles.md` and says so.

The question: does any classic candlestick pattern, alone or in the derived
forms, predict returns after costs, out of sample from 2024 on crypto and from
2016 on US equities; and does it help M2 or the breakout book?

## The pool

Sharpe trials before this study: **948** hand trials (after X11) at the
variance backed out of the published bar, plus every genome in the factory
ledger at run time (600 on the PC today); X11 published 1,548. This study adds
at most **47** Sharpe trials (part B at most 42, part D 5). Deflation as in
X6, X9 and X11 (pooled variance of daily Sharpes, each group at its own). If a
study run in parallel publishes trials before this one is written up, the
write-up says so and adds them.

The event tests of part A and the IC tests of part C are not Sharpe trials;
they are corrected inside their parts as described there.

## The patterns

All 74 patterns of `lab/candles/patterns.py` (21 one-bar, 25 two-bar, 23
three-bar, 2 four-bar, 3 five-bar; 32 bullish, 36 bearish, 6 neutral) with
the default `Params` (A = mean range of the 10 bars before the pattern, trend
= close against its 20-bar SMA at the bar before the pattern, doji 0.1 A,
short 0.3 A, long 0.7 A, tiny shadow 0.05 A, short shadow 0.1 A, long shadow
0.5 A and 2 x body, near 0.05 A, penetration 0.3), and the six derived
signals of `lab/candles/derived.py`: `bull_confluence`, `bear_confluence`,
`bull_at_support`, `bear_at_resistance` (Donchian 20, within 0.5 A),
`bull_volume`, `bear_volume` (1.5 x the 20-bar mean volume). 80 signals. No
parameter is tuned; every definition is the same for every market and bar
size.

## Data sets

| set | bars | instruments | in sample | out of sample |
|---|---|---|---|---|
| CD crypto daily | UTC days built from Binance hourly klines (open of the first hour, high, low, close of the last, quote volume; at least 20 hours) | the 31 coins of `universe.ALPACA` with Binance history, on days the sweep's panel calls them eligible (60 days old, 1 M USD a day) | first bar to 2023-12-31 | 2024-01-01 to the last complete day |
| C4 crypto 4h | 4-hour bars on the UTC grid from the same hours (at least 3 of 4) | the same coins, eligible on the last completed UTC day | same | same |
| EF US ETFs daily | the S&P file's rows (OHLC scaled by adjusted close / close, so dividends count) | SPY QQQ IWM DIA MDY, XLB XLE XLF XLI XLK XLP XLU XLV XLY XLC XLRE, EFA EEM, TLT IEF LQD HYG, GLD SLV, VNQ (25) | 1998 to 2015 | 2016-01-01 to 2026-10-16 |
| SP S&P 500 large caps daily | same, rows with open, high and low only | point-in-time members on the pattern day | 1998 to 2015 | 2016-01-01 on |
| twins (checks only) | CD and C4 | the 30 most liquid eligible coins of each day by 28-day volume, delisted coins included | | |

## A. Event study (no Sharpe trials)

**Event**: a signal on bar t of an eligible instrument. Entry at the open of
t+1, exit at the close of t+h, h = 1, 3, 5, 10 bars (the entry bar counts).
r = close(t+h) / open(t+1) - 1; an instrument whose series ends earlier exits
at its last close; no bar at t+1, no event.

**Baselines**: the *drift* is the mean r over every eligible instrument-bar of
the same set and window; the *same-bar random entry* is the mean r over every
eligible instrument entering on the same bar (the expectation of a random
pick that day). Excess e = r - same-bar mean. Signed excess s = d x e, d = +1
for bullish signals, -1 for bearish, and for the 6 neutral patterns the sign
of their in-sample mean excess.

**Statistic**: s averaged per bar, then a Newey-West t (lag h) over bars.

**Screen (in sample)**: a cell (signal, set, horizon) is a candidate when it
has at least 100 events and t >= 3.0. 80 signals x 4 sets x 4 horizons =
1,280 cells.

**Holds out of sample** when, from the split: at least 30 events; one-sided
p of the out-of-sample t below the Holm threshold over all candidates (family
0.05); and for CD and C4 the twin's out-of-sample mean signed excess above 0.
For the candidates that hold, and for the part B picks, a permutation check:
2,000 draws of one random eligible instrument on each event's bar.

**Tradeable** (reported): a bullish cell that holds and whose out-of-sample
mean r minus the round-trip cost is above 0 and above the drift.

**Costs per side**: crypto 35 bps (Alpaca taker plus slippage); SPY and QQQ
1 bp, the other ETFs 2 bps, S&P members 5 bps, plus the SEC fee (0.28 bps)
on equity sales.

## B. Long-only rules (at most 42 Sharpe trials)

**Picks**: per set (CD, C4, EF, SP), the up to three bullish signals (bullish
patterns and the three bullish derived signals) with the highest in-sample t,
among cells with at least 100 in-sample events whose in-sample mean r minus
the round trip is above the in-sample drift; one horizon per signal (its best
in-sample t). Fewer qualify, fewer rules.

**Book**: S slots (CD 10, C4 10, EF 5, SP 20), each 1/S of equity. At the
close of bar t every eligible instrument with the signal and not held is a
candidate; free slots go to the candidates with the highest 28-bar mean
dollar volume; entry at the open of t+1, exit at the close of t+h, unused
slots in cash. Costs as in A on every entry and exit. 4h returns are
compounded into UTC days; Sharpe on daily returns.

**Trials per pick**: base; filled one bar late (entry at the open of t+2,
exit one bar later); double costs; and for CD and C4 the same rule on the
twin. 12 + 12 + 9 + 9 = 42 at most.

**Baseline book** (not a trial, a null): 200 random books with the same number
of entries on the same bars, random eligible instruments not held, the same
holding period and costs.

**Gates** (all, out of sample, at base cost): (1) Sharpe above 0; (2) above
the 95th percentile of the random books; (3) above the benchmark's Sharpe
(BTC bought and held for crypto, SPY for equities) on the same days; (4) one
bar late above 0; (5) double costs above 0; (6) the twin above 0 (crypto);
(7) positive in at least 2 of 2024, 2025, 2026 (crypto) or 7 of the 11 years
2016 to 2026 (equities); (8) deflated p above 0.95 over the pool.

## C. Features for M2 (2 IC tests)

**Group C**, per coin-day from the CD bars of the same segment, ranked within
the day like every M2 input: `c_net` (bullish minus bearish patterns ending
that day), `c_net5` (its sum over the last 5 days), `c_sr` (bull_at_support
minus bear_at_resistance), `c_vol` (bull_volume minus bear_volume),
`c_body`, `c_upper`, `c_lower` (signed body and shadows over A), plus one 0/1
indicator for each part B pick on CD. Joined to X11's M2 panel on (day,
symbol); a row without candle data keeps the inputs missing.

**v2 + C** against **v2** (X11's cached scores), the same LightGBM parameters
and quarterly walk-forward from 2022 with a 7-day embargo. Judged from
2024-01-01, mean daily Spearman IC on the 7-day label, Newey-West t (lag 7)
of the paired daily difference:

- **H1** every scored coin-day;
- **H2** among the Alpaca coins (days with at least 8).

Each passes when the difference is positive, t above 2.24 (two-sided 0.05
over two tests) and v2 + C is higher in at least 2 of 2024, 2025, 2026.
Reported, not tests: the IC of `c_net` alone, feature importance.

## D. The breakout book's entry filter (5 Sharpe trials)

`breakout_top10` as the autopilot runs it on Alpaca (unlisted coins in cash,
35 bps), entries filtered on the breakout day t (the close above the 20-day
high), with the CD candle of day t:

- **F1** no bearish pattern ends on day t;
- **F2** `net` at least 1;
- **F3** the close in the top third of the day's range.

Exits unchanged. Pick: the best in-sample Sharpe at 35 bps (2020-08 to 2023).
The pick is re-run a day late and on the survivorship-free twin (the original
book, unlisted coins included). Gates: X6 and X9's six against the book alone
(Sharpe and 2 of 3 years, drawdown, bootstrap band of the difference above 0,
a day late, twin, the improvement deflated over this part's 5 trials).

## What happens with a pass

- A part B rule that passes every gate becomes a shadow lab signal (a daily
  job writing what the rule would hold, forward record only), its job
  disabled in `jobs.yaml`; no engine signal, no paper book.
- A part C pass becomes an M2 v2 + C shadow ranking, written before the
  outcome and scored after 7 days like `m2-v3-shadow`, job disabled.
- A part D pass becomes a shadow variant of the breakout signal, off by
  default.
- The engine gets the patterns as a strategy kind either way (the patterns
  behind any pass, else the part B picks and the classic core: engulfing,
  hammer and shooting star, harami, stars, three soldiers and crows), off by
  default; without a pass it is labelled as having shown no edge.
