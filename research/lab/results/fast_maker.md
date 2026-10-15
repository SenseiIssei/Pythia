# Fast trades with maker orders only, on the 33 Alpaca coins (W15)

`python -m lab.experiments.fast_maker`

## Pre-registration (written before the first run)

**Question.** The fast study (results/fast_strategies.md) found that at Alpaca
taker cost (25 bps fee plus about 10 bps slippage a side) holds under about two
days do not pay, and that at maker cost (15 bps a side) holds of 12 to 48 hours
mostly would, if resting orders filled. Can trades held from one hour to about
a day pay when every entry and every exit is a resting limit order at Alpaca's
maker fee, under a fill model that only fills a limit when the price trades
through it? If not, what fee level would they need?

**Coins.** Alpaca's crypto list (36 assets, March 2026) without its three
stablecoins (USDC, USDG, USDT): AAVE ADA ARB AVAX BAT BCH BONK BTC CRV DOGE
DOT ETH FIL GRT HYPE LDO LINK LTC ONDO PAXG PEPE POL RENDER SHIB SKY SOL
SUSHI TRUMP UNI WIF XRP XTZ YFI (33, memecoins included). Prices are Binance
USDT spot 5-minute bars from data.binance.vision. Renamed tokens are spliced
(MATIC then POL, RNDR then RENDER, MKR then SKY), the older series rescaled
so the price does not jump at the switch. A coin can be entered once it has 60
days of bars and its trailing 28-day quote volume averages at least 1 M USD a
day. This list is today's survivors, so every pick is also run on a
survivorship-free twin: each day the 33 eligible USDT coins with the highest
28-day quote volume (all USDT pairs the archive ever published, delisted ones
included; stablecoins, fiat and leveraged tokens left out), a coin enterable
only while it is in that set. The twin is judged out of sample only.

**Split.** In sample 2020-08-01 to 2023-12-31, out of sample 2024-01-01 to
2026-10-14. Daily returns (UTC days), Sharpe annualised with 365 days, as
everywhere in the lab.

**Fill model** (the base case, fixed before the run):

1. Every order is a limit decided at a 5-minute close and resting from the
   next 5-minute bar on (5 minutes of latency).
2. A buy limit at L fills in a bar only if the bar's low is at least 1 bp
   below L (the price traded through it, not just touched it); a sell limit
   only if the high is at least 1 bp above L. The fill price is L.
3. Partial fills: the share filled is the depth of the trade-through over
   10 bps, capped at 1 (1 bp through fills 10 %, 10 bps or more fills all),
   the largest depth seen while the order rests, and never more than 10 % of
   the quote volume of the bars it rested through, for a 100 000 USD book.
4. Adverse selection haircut: every maker fill is booked 3 bps worse than its
   limit (on top of the trade-through rule, which already only fills orders
   the price moves against).
5. Fee 15 bps a side on every maker fill.
6. Entries: the unfilled rest is cancelled after the variant's window. No
   chasing; a missed entry is a missed trade.
7. Exits: a sell limit at the exit decision's close; the unfilled rest is
   cancelled and placed again at the current close every 15 minutes until
   done. Whatever is still open 24 hours after the exit decision is sold at
   the close at taker cost (25 bps plus 10 bps slippage), counted as a
   fallback.

**Sizing.** Each entry targets min(40 % annual vol / coin vol, 1) / 10 of the
book (coin vol: trailing 30 days of hourly returns, known at the decision),
times the share filled; it drifts until the exit. An entry whose target
would take the book's open targets above 100 % is skipped. Long only, spot.

**Grid: 44 variants in four families.** Signal bars are built from the 5-minute
bars (1h and 4h bars close on the UTC hour).

| Family | Rule | Variants |
|---|---|---|
| A drop reversion | at any 5-minute close, the coin's return over the last hour is below -k x its hourly vol (trailing 30 days, up to the hour before) and below -2 %: buy limit at close x (1 - e x hourly vol), cancelled after 60 min; exit H after the fill | k 3 or 5; e 0 or 0.5; H 1, 4 or 12 h (12) |
| B 4h trend, pullback entries | trend on 4h bars: EMA 24/96 above, or Donchian 55/27 long; at each 4h close while the trend is on and the coin is flat, buy limit at close x (1 - p x 4h vol), cancelled after W; exit when the trend ends | rule EMA or Donchian; p 0.5 or 1; W 1h or 4h; BTC 200-day gate off or on (16) |
| C expansion after compression | at an hourly close, the coin's 24h realised vol is below q x its 30-day level (up to the previous hour) and the close is above every close of the previous 24 hours: buy limit at close x (1 - e x hourly vol), cancelled after 60 min; exit H after the fill | q 0.5 or 0.7; e 0 or 0.5; H 4 or 12 h (8) |
| D seasonality | hour of day: the k UTC hours with the best mean hourly return of the equal-weight basket in sample (fixed from in-sample data only) are held, consecutive hours without a round trip; weekend: hold Saturday 00:00 to Monday 00:00 UTC, or the weekdays only. Buy limits at the close before the window, cancelled after N | hour of day k 2 or 4, N 15 or 30 min; weekend or weekdays, N 15 or 60 min (8) |

The BTC gate is the lab's: no entries, and everything sold, while BTC's daily
close is below its 200-day average (known at the previous daily close).

**Picks.** Per family, the variant with the best in-sample Sharpe in the base
case: 4 picks. Each pick is also run on the survivorship-free twin and one bar
late (every order decided and priced one 5-minute bar later). Plus one
selection-honest series: a walk-forward pick by quarter from 2024 (each
quarter trades the variant with the best base Sharpe on all data before it).
Counted trials: 44 grid + 4 twins + 4 late + 1 walk-forward = **53**. The pool
is the 377 counted so far (results/alpaca_universe.md) plus these: **430**.

**Pass rule** (all must hold, else the result is written up as negative, no
paper book is added and the fee level that would be needed is reported):

1. out-of-sample Sharpe > 0 in the base case;
2. average net return per round trip > 0 bps in the base case;
3. deflated p > 0.95 over the pool of 430 (prior variance backed out of the
   published bar of 2.43 over 377, pooled with this study's Sharpes clipped
   at +-3, as before);
4. the survivorship-free twin's out-of-sample Sharpe > 0;
5. the one-bar-late run's out-of-sample Sharpe > 0;
6. positive in at least 2 of the 3 out-of-sample years (2026 partial).

**Reported** for every variant: orders and round trips per day (all coins
together), entry fill rate (by order and by quantity), the share of exit
quantity done as maker, the fallback share, average hold, average gross and
net bps per round trip, Sharpe gross / base / at taker cost on both sides with
every order filled at the close (the earlier study's convention, as the
reference), CAGR and maximum drawdown in the base case, per-year Sharpe;
bootstrap 90 % band of the picks' Sharpe. Sensitivity (not trials): the picks
at an adverse selection haircut of 0 and 10 bps. The fee level needed: for
every variant the maker fee a side at which its out-of-sample net per round
trip is zero (gross per round trip less the haircuts, over two).

**Check of the fill model** (not a trial): on a sample of days and coins
(BTC, DOGE, PEPE, WIF; two days a quarter in 2024 and 2025), Binance aggTrades
decide each family A and C entry order instead of the bars (filled when trades
of at least the order's size print below the limit within the window); the
share of orders where bars and trades disagree, and in which direction, is
reported.

## Addendum (2026-10-15, written before the first run)

Nothing in the grid, the picks, the fill model or the pass rule changes. What
changes is where and on what bars the first run is made, and the size of the
pool, and both are stated here before any number exists.

1. **Bars.** The registered bars are 5 minutes. The machine the first run is
   made on holds Binance 1h archives for every USDT pair (683 symbols, to
   2026-10-14) but no 5-minute bars, and this study does not download them
   there. The first run therefore uses **1h bars** for all 33 coins and the
   twin (`--bars 1h`); the registered **5-minute run** is the server command
   `python -m lab.experiments.fast_maker --bars 5m` (after
   `python -m lab.experiments.vision alpaca` and `... vision twin`) and writes
   `results/fast_maker_5m.md`. On 1h bars: the latency is one bar (an hour);
   family A is checked at hourly closes only (the trailing hour's return is
   the bar's own return); entry windows under an hour round up to one bar, so
   family D's two values of N give identical variants (they are still counted,
   44 stays 44); exits are re-placed every hour, not every 15 minutes; "one
   bar late" is an hour late. For orders decided at an hour close that rest
   whole hours (families B and C, A and D at their 60-minute windows) the fill
   rule gives the same answer on 1h and on 5-minute bars, because an hour's
   low is the lowest of its twelve 5-minute lows; partial shares and the
   volume cap match too. What differs is timing inside the hour.
2. **Resolution check** (not a trial). 15 of the 33 coins have 1-minute
   history on this machine (AAVE ADA AVAX BCH BTC DOGE DOT ETH FIL LINK LTC
   PEPE SOL UNI XRP). All 44 variants are run on those 15 at 5-minute bars
   built from the 1-minute bars and at 1h bars, and the out-of-sample Sharpes
   and net bps per round trip are compared.
3. **aggTrades check.** It needs downloads, so it is left to the server
   (`python -m lab.experiments.fast_maker check-fills`). Its days are the two
   days of each quarter with the most family A and C entry orders on the four
   coins (chosen by order count, not by outcome).
4. **Pool.** The registration says 430 (377 plus 53). Since C16 other work
   was counted on the same 377 in parallel: the factory's first run (300, the
   ledger now says 677), listings (16), memecoins (50) and equities_ranking
   (45). Gate 3 is judged over all of them plus this study's 53: **841
   trials**, the stricter count (the 111 hand trials enter with the prior's
   variance, the factory's 300 with the variance of their in-sample Sharpes
   from the ledger, this study's 53 with theirs, clipped at +-3). The p over
   the registered 430 is reported next to it.
5. **Accounting details** fixed now: the book is simulated in dollars from
   100 000 USD; each entry is sized off the equity at the start of its
   decision's UTC day; an order holds its full target against the 100 % limit
   while it rests and target times the filled share until the exit is done;
   orders decided at the same bar are queued by trailing 28-day quote volume,
   largest first. A time exit is decided H after the close of the bar of the
   first entry fill. Gross means the base fills without fees, haircut or
   fallback cost. A coin is not re-entered while an exit of it is open; an
   entry skipped by the 100 % limit does not free the coin for other signals
   of the same family during the span the skipped trade would have held.
   BTC buy and hold (no cost) is reported next to every pick.

<!-- generated below by lab.experiments.fast_maker; edit above this line only -->

## Results, 1h bars (generated 2026-10-15, data to 2026-10-14)

**Verdict: nothing passes, no paper book.** Out of sample (2024-01-01 to 2026-10-14) 19 of 44 variants have a Sharpe above 0 in the base case (maker fills, 15 bps, 3 bps haircut), 18 make money per round trip after costs, 16 are positive with every order filled at the close at 35 bps a side and 26 before any cost. The best base case out of sample, picked after the fact, is B Donchian 55/27 · p 1.0 · W 1h · BTC gate at 1.40. The quarterly walk-forward pick makes 0.76 (drawdown 43 %). BTC buy and hold over the same days: Sharpe 0.74, 27 % a year, drawdown 53 %. Across the grid the maker fee a side at which the average round trip would net zero has a median of 1.0 bps (best 219.6); Alpaca charges 15. Deflation pool 841 trials, noise bar Sharpe 2.72 (registered pool 430, bar 2.80: fewer trials, but this study's own spread of Sharpes is wide, so its bar is not lower).

**The question asked: holds under two days.** 24 variants hold under 48 hours on average (families A and C, D's hours of day); 3 of them are positive out of sample in the base case and 0 at taker cost. Their filled round trip earns a median -15 bps before costs (best 122) against 36 bps for two resting legs; the maker fee a side at which the median one breaks even is -10.4 bps (below zero: it would need a rebate), and 3 of 24 clear Alpaca's 15. Against the same rules filled at the close, the resting fills change the gross per round trip by a median -14 bps: the fee saved is real, but a limit fills when the price comes to it, and the trades it misses are not the bad ones. The best of them out of sample (after the fact) is A drop k 5 · e 0.5 · hold 12h at 0.42, 86 bps net per round trip. The 20 variants that hold longer are not fast trades: family B (4h trend, pullback entries) holds a median 8 days and 16 of its 16 variants are positive in the base case (median 0.71, at taker cost 0.57); D's weekday and weekend windows hold 2 to 5 days.

### The picks against the pass rule

Per family the best in-sample Sharpe in the base case. `rt_day` counts round trips across all coins per day out of sample, `fill_rate_orders` the share of entry orders with any fill, `net_bps_rt` the average round trip after the haircut, fees and fallback costs (weighted by the filled share), `fee_needed_bps` the maker fee a side at which it would be zero. `twin_oos` is the survivorship-free twin, `late_oos` the pick decided and priced one bar late. The band is a stationary bootstrap (blocks of 20 days) of the base case Sharpe.

| variant | is_base | oos_base | oos_taker | oos_gross | rt_day | fill_rate_orders | net_bps_rt | fee_needed_bps | dd_base | y2024 | y2025 | y2026 | deflated_p | deflated_p_430 | boot_p05 | boot_p95 | twin_oos | late_oos | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A drop k 5 · e 0.5 · hold 1h | 0.71 | -0.74 | -1.81 | -0.26 | 0.71 | 0.84 | -52.55 | -11.30 | 0.25 | -0.76 | -1.01 | -0.11 | 0.00 | 0.00 | -1.44 | 0.30 | -0.63 | 0.28 | fails: Sharpe -0.74 <= 0; net -53 bps per round trip; deflated p 0.00 <= 0.95; twin -0.63; positive in 0 of 3 years |
| B EMA 24/96 · p 0.5 · W 1h · BTC gate | 1.86 | 0.71 | 0.51 | 0.81 | 0.62 | 0.18 | 243 | 135 | 0.44 | 1.70 | -0.91 | 1.12 | 0.00 | 0.00 | -0.70 | 1.92 | 0.40 | 0.52 | fails: deflated p 0.00 <= 0.95 |
| C squeeze q 0.5 · e 0.5 · hold 12h | -2.92 | -3.46 | -5.16 | -1.69 | 1.26 | 0.34 | -75.11 | -22.63 | 0.31 | -5.41 | -2.28 | -3.13 | 0.00 | 0.00 | -4.27 | -2.64 | -2.76 | -3.10 | fails: Sharpe -3.46 <= 0; net -75 bps per round trip; deflated p 0.00 <= 0.95; twin -2.76; one bar late -3.10; positive in 0 of 3 years |
| D weekdays · N 15m | 0.32 | -0.21 | -0.41 | 0.08 | 2.75 | 0.96 | -45.66 | -7.84 | 0.76 | 0.45 | -0.87 | -0.16 | 0.00 | 0.00 | -1.18 | 0.79 | -0.55 | -0.33 | fails: Sharpe -0.21 <= 0; net -46 bps per round trip; deflated p 0.00 <= 0.95; twin -0.55; one bar late -0.33; positive in 1 of 3 years |

### Against BTC buy and hold (out of sample)

| book | Sharpe | CAGR | max drawdown | 2024 | 2025 | 2026 |
|---|---|---|---|---|---|---|
| BTC buy and hold, no cost | 0.74 | 27 % | 53 % | 1.76 | 0.05 | 0.03 |
| A drop k 5 · e 0.5 · hold 1h, maker base | -0.74 | -8 % | 25 % | -0.76 | -1.01 | -0.11 |
| A drop k 5 · e 0.5 · hold 1h, taker at the close | -1.81 | -19 % | 45 % | | | |
| B EMA 24/96 · p 0.5 · W 1h · BTC gate, maker base | 0.71 | 22 % | 44 % | 1.70 | -0.91 | 1.12 |
| B EMA 24/96 · p 0.5 · W 1h · BTC gate, taker at the close | 0.51 | 13 % | 47 % | | | |
| C squeeze q 0.5 · e 0.5 · hold 12h, maker base | -3.46 | -13 % | 31 % | -5.41 | -2.28 | -3.13 |
| C squeeze q 0.5 · e 0.5 · hold 12h, taker at the close | -5.16 | -30 % | 63 % | | | |
| D weekdays · N 15m, maker base | -0.21 | -25 % | 76 % | 0.45 | -0.87 | -0.16 |
| D weekdays · N 15m, taker at the close | -0.41 | -34 % | 83 % | | | |
| walk-forward pick by quarter, maker base | 0.76 | 23 % | 43 % | 1.68 | -0.91 | 0.85 |

### Sensitivity of the picks to the haircut (not trials)

| variant | oos_haircut 0 | oos_base | oos_haircut 10 |
|---|---|---|---|
| A drop k 5 · e 0.5 · hold 1h | -0.66 | -0.74 | -0.92 |
| B EMA 24/96 · p 0.5 · W 1h · BTC gate | 0.72 | 0.71 | 0.67 |
| C squeeze q 0.5 · e 0.5 · hold 12h | -3.17 | -3.46 | -4.10 |
| D weekdays · N 15m | -0.16 | -0.21 | -0.33 |

### What a round trip earns, by holding time (all 44 variants, out of sample)

A maker round trip costs 36 bps when both legs rest (2 x 15 fee + 2 x 3 haircut); at taker cost it is 70.

| hold | variants | median_gross_bps | best_gross_bps | median_net_bps | median_fee_needed | median_fill_rate | positive_base |
|---|---|---|---|---|---|---|---|
| 0 to 6 h | 16 | -15.39 | 17.90 | -51.36 | -10.70 | 0.95 | 0 |
| 6 to 24 h | 8 | 9.93 | 122 | -26.09 | 1.95 | 0.89 | 3 |
| 48 h and more | 20 | 150 | 455 | 114 | 71.37 | 0.22 | 16 |

### Walk-forward pick by quarter

- 2024Q1: B EMA 24/96 · p 0.5 · W 1h · BTC gate
- 2024Q2: B EMA 24/96 · p 0.5 · W 1h · BTC gate
- 2024Q3: B EMA 24/96 · p 0.5 · W 1h
- 2024Q4: B EMA 24/96 · p 0.5 · W 1h
- 2025Q1: B EMA 24/96 · p 1.0 · W 1h · BTC gate
- 2025Q2: B EMA 24/96 · p 1.0 · W 1h · BTC gate
- 2025Q3: B EMA 24/96 · p 1.0 · W 1h · BTC gate
- 2025Q4: B EMA 24/96 · p 1.0 · W 1h · BTC gate
- 2026Q1: B EMA 24/96 · p 1.0 · W 1h · BTC gate
- 2026Q2: B EMA 24/96 · p 1.0 · W 1h · BTC gate
- 2026Q3: B EMA 24/96 · p 1.0 · W 1h · BTC gate
- 2026Q4: B EMA 24/96 · p 1.0 · W 1h · BTC gate

### All 44 variants (out of sample unless marked is_)

`entries_day` entry orders and `orders_day` entry plus exit orders per day across all coins; `fill_rate_qty` the average filled share of an entry order; `maker_exit_share` the share of exit quantity sold as maker; `fallback_share` the share of round trips that needed the 24-hour taker fallback; `taker_gross_bps_rt` the same rules' round trip filled at the close; `skipped` entries (whole period) the 100 % limit refused.

| variant | is_base | oos_gross | oos_base | oos_taker | cagr_base | dd_base | entries_day | orders_day | rt_day | fill_rate_orders | fill_rate_qty | maker_exit_share | fallback_share | hold_h | gross_bps_rt | net_bps_rt | fee_needed_bps | taker_gross_bps_rt | y2024 | y2025 | y2026 | skipped |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A drop k 3 · e 0.0 · hold 12h | -0.29 | 0.64 | -0.24 | -0.72 | -0.09 | 0.55 | 3.49 | 7.47 | 3.41 | 0.98 | 0.96 | 1.00 | 0.00 | 13.17 | 33.36 | -2.70 | 13.65 | 51.51 | 1.87 | -1.89 | -0.10 | 570 |
| A drop k 3 · e 0.0 · hold 1h | -1.41 | -0.57 | -2.09 | -3.65 | -0.31 | 0.64 | 4.19 | 8.73 | 4.07 | 0.97 | 0.95 | 1.00 | 0.00 | 2.12 | -12.04 | -48.02 | -9.02 | 4.19 | -2.33 | -1.89 | -2.54 | 540 |
| A drop k 3 · e 0.0 · hold 4h | -0.70 | -0.04 | -1.59 | -2.67 | -0.23 | 0.54 | 3.91 | 8.35 | 3.81 | 0.97 | 0.96 | 1.00 | 0.00 | 5.16 | 2.80 | -33.21 | -1.60 | 3.43 | -0.50 | -2.33 | -1.97 | 550 |
| A drop k 3 · e 0.5 · hold 12h | -0.32 | 0.73 | 0.00 | -0.72 | -0.03 | 0.48 | 3.61 | 6.68 | 2.63 | 0.73 | 0.71 | 1.00 | 0.00 | 13.16 | 48.43 | 12.35 | 21.16 | 51.51 | 2.25 | -1.73 | 0.03 | 565 |
| A drop k 3 · e 0.5 · hold 1h | -0.69 | -0.61 | -1.82 | -3.65 | -0.26 | 0.59 | 4.22 | 7.64 | 3.07 | 0.73 | 0.71 | 1.00 | 0.00 | 2.11 | -17.40 | -53.37 | -11.71 | 4.19 | -1.73 | -2.23 | -1.34 | 546 |
| A drop k 3 · e 0.5 · hold 4h | -0.43 | 0.10 | -1.26 | -2.67 | -0.17 | 0.43 | 3.99 | 7.36 | 2.91 | 0.73 | 0.71 | 1.00 | 0.00 | 5.16 | 8.93 | -27.09 | 1.46 | 3.43 | 0.11 | -2.54 | -1.63 | 554 |
| A drop k 5 · e 0.0 · hold 12h | 0.19 | 0.54 | 0.22 | -0.04 | 0.02 | 0.22 | 0.79 | 1.71 | 0.76 | 0.97 | 0.96 | 1.00 | 0.00 | 13.21 | 93.86 | 57.70 | 43.71 | 102 | 0.73 | -0.09 | 0.19 | 174 |
| A drop k 5 · e 0.0 · hold 1h | 0.39 | -0.36 | -0.90 | -1.81 | -0.10 | 0.27 | 0.84 | 1.74 | 0.82 | 0.97 | 0.96 | 1.00 | 0.00 | 2.11 | -18.67 | -54.64 | -12.35 | -56.65 | -1.27 | -0.79 | -0.74 | 172 |
| A drop k 5 · e 0.0 · hold 4h | 0.38 | -0.01 | -0.57 | -0.78 | -0.06 | 0.22 | 0.81 | 1.75 | 0.79 | 0.97 | 0.96 | 1.00 | 0.00 | 5.19 | 7.25 | -28.76 | 0.62 | 22.49 | -0.72 | -0.48 | -0.51 | 174 |
| A drop k 5 · e 0.5 · hold 12h | 0.44 | 0.74 | 0.42 | -0.04 | 0.05 | 0.16 | 0.79 | 1.61 | 0.66 | 0.84 | 0.82 | 1.00 | 0.00 | 13.23 | 122 | 85.58 | 57.53 | 102 | 1.06 | -0.02 | 0.23 | 175 |
| A drop k 5 · e 0.5 · hold 1h | 0.71 | -0.26 | -0.74 | -1.81 | -0.08 | 0.25 | 0.84 | 1.62 | 0.71 | 0.84 | 0.82 | 1.00 | 0.00 | 2.10 | -16.58 | -52.55 | -11.30 | -56.65 | -0.76 | -1.01 | -0.11 | 171 |
| A drop k 5 · e 0.5 · hold 4h | 0.68 | 0.13 | -0.43 | -0.78 | -0.04 | 0.18 | 0.82 | 1.64 | 0.68 | 0.84 | 0.82 | 1.00 | 0.00 | 5.19 | 17.90 | -18.14 | 5.94 | 22.49 | -0.32 | -0.53 | -0.43 | 174 |
| B Donchian 55/27 · p 0.5 · W 1h | 1.26 | 0.90 | 0.70 | 0.62 | 0.21 | 0.57 | 5.46 | 6.82 | 1.11 | 0.20 | 0.19 | 1.00 | 0.00 | 157 | 153 | 116 | 72.77 | 157 | 2.63 | -1.01 | -0.55 | 1035 |
| B Donchian 55/27 · p 0.5 · W 1h · BTC gate | 1.28 | 1.23 | 1.08 | 0.84 | 0.35 | 0.43 | 4.19 | 5.13 | 0.80 | 0.19 | 0.17 | 1.00 | 0.00 | 145 | 276 | 239 | 133 | 229 | 2.55 | -0.91 | 1.05 | 825 |
| B Donchian 55/27 · p 0.5 · W 4h | 1.17 | 0.91 | 0.72 | 0.62 | 0.22 | 0.57 | 2.06 | 3.40 | 1.11 | 0.54 | 0.52 | 1.00 | 0.00 | 164 | 139 | 102 | 65.89 | 157 | 2.56 | -1.01 | -0.21 | 534 |
| B Donchian 55/27 · p 0.5 · W 4h · BTC gate | 1.20 | 1.13 | 0.98 | 0.84 | 0.31 | 0.46 | 1.61 | 2.56 | 0.82 | 0.51 | 0.49 | 1.00 | 0.00 | 149 | 230 | 194 | 111 | 229 | 2.35 | -0.87 | 1.05 | 395 |
| B Donchian 55/27 · p 1.0 · W 1h | 1.32 | 1.13 | 0.94 | 0.62 | 0.28 | 0.51 | 19.39 | 20.43 | 0.87 | 0.04 | 0.04 | 1.00 | 0.00 | 137 | 252 | 215 | 121 | 157 | 2.87 | -0.88 | -1.02 | 3598 |
| B Donchian 55/27 · p 1.0 · W 1h · BTC gate | 1.19 | 1.53 | 1.40 | 0.84 | 0.43 | 0.30 | 12.96 | 13.66 | 0.60 | 0.05 | 0.04 | 1.00 | 0.00 | 138 | 455 | 418 | 220 | 229 | 2.80 | -0.81 | 1.05 | 2864 |
| B Donchian 55/27 · p 1.0 · W 4h | 1.17 | 0.90 | 0.71 | 0.62 | 0.21 | 0.57 | 4.99 | 6.33 | 1.09 | 0.22 | 0.21 | 1.00 | 0.00 | 148 | 147 | 111 | 69.97 | 157 | 2.54 | -0.97 | -0.50 | 1020 |
| B Donchian 55/27 · p 1.0 · W 4h · BTC gate | 1.09 | 1.22 | 1.08 | 0.84 | 0.36 | 0.43 | 3.55 | 4.44 | 0.76 | 0.21 | 0.20 | 1.00 | 0.00 | 142 | 284 | 248 | 137 | 229 | 2.45 | -0.77 | 1.03 | 775 |
| B EMA 24/96 · p 0.5 · W 1h | 1.86 | 0.54 | 0.41 | 0.26 | 0.09 | 0.58 | 4.47 | 5.54 | 0.83 | 0.19 | 0.17 | 1.00 | 0.01 | 259 | 128 | 91.35 | 60.49 | 105 | 1.70 | -1.13 | 0.04 | 961 |
| B EMA 24/96 · p 0.5 · W 1h · BTC gate | 1.86 | 0.81 | 0.71 | 0.51 | 0.22 | 0.44 | 3.42 | 4.17 | 0.62 | 0.18 | 0.17 | 0.99 | 0.01 | 238 | 279 | 243 | 135 | 209 | 1.70 | -0.91 | 1.12 | 811 |
| B EMA 24/96 · p 0.5 · W 4h | 1.75 | 0.45 | 0.31 | 0.26 | 0.05 | 0.62 | 1.69 | 2.82 | 0.85 | 0.51 | 0.48 | 1.00 | 0.01 | 255 | 35.82 | -0.34 | 14.83 | 105 | 1.51 | -1.28 | 0.29 | 538 |
| B EMA 24/96 · p 0.5 · W 4h · BTC gate | 1.80 | 0.64 | 0.54 | 0.51 | 0.14 | 0.46 | 1.33 | 2.12 | 0.63 | 0.48 | 0.45 | 0.99 | 0.01 | 237 | 123 | 86.46 | 58.13 | 209 | 1.47 | -1.08 | 1.22 | 446 |
| B EMA 24/96 · p 1.0 · W 1h | 1.78 | 0.64 | 0.52 | 0.26 | 0.13 | 0.54 | 14.86 | 15.67 | 0.65 | 0.04 | 0.04 | 0.99 | 0.01 | 264 | 222 | 186 | 107 | 105 | 1.96 | -1.05 | -0.38 | 3622 |
| B EMA 24/96 · p 1.0 · W 1h · BTC gate | 1.85 | 0.94 | 0.85 | 0.51 | 0.25 | 0.36 | 10.13 | 10.67 | 0.47 | 0.05 | 0.04 | 0.99 | 0.01 | 261 | 433 | 396 | 210 | 209 | 1.97 | -0.91 | 0.85 | 2931 |
| B EMA 24/96 · p 1.0 · W 4h | 1.78 | 0.50 | 0.37 | 0.26 | 0.07 | 0.58 | 3.73 | 4.84 | 0.82 | 0.22 | 0.21 | 1.00 | 0.01 | 244 | 76.34 | 40.14 | 35.03 | 105 | 1.49 | -1.27 | 0.48 | 1033 |
| B EMA 24/96 · p 1.0 · W 4h · BTC gate | 1.71 | 0.66 | 0.56 | 0.51 | 0.15 | 0.45 | 2.79 | 3.55 | 0.61 | 0.22 | 0.21 | 0.99 | 0.01 | 230 | 170 | 134 | 81.67 | 209 | 1.55 | -1.13 | 1.06 | 807 |
| C squeeze q 0.5 · e 0.0 · hold 12h | -2.96 | -1.26 | -3.28 | -5.16 | -0.19 | 0.45 | 2.34 | 5.43 | 2.22 | 0.95 | 0.88 | 1.00 | 0.00 | 13.39 | -25.54 | -61.49 | -15.79 | -14.31 | -4.72 | -2.20 | -3.10 | 12 |
| C squeeze q 0.5 · e 0.0 · hold 4h | -5.15 | -2.14 | -6.00 | -8.43 | -0.21 | 0.49 | 2.90 | 6.82 | 2.74 | 0.95 | 0.88 | 1.00 | 0.00 | 5.43 | -18.00 | -53.96 | -12.01 | -2.10 | -6.61 | -5.00 | -6.64 | 5 |
| C squeeze q 0.5 · e 0.5 · hold 12h | -2.92 | -1.69 | -3.46 | -5.16 | -0.13 | 0.31 | 3.70 | 5.44 | 1.26 | 0.34 | 0.29 | 1.00 | 0.00 | 13.39 | -39.18 | -75.11 | -22.63 | -14.31 | -5.41 | -2.28 | -3.13 | 4 |
| C squeeze q 0.5 · e 0.5 · hold 4h | -4.12 | -2.11 | -5.24 | -8.43 | -0.11 | 0.28 | 4.05 | 6.01 | 1.38 | 0.34 | 0.29 | 1.00 | 0.00 | 5.42 | -22.88 | -58.84 | -14.45 | -2.10 | -5.80 | -4.53 | -5.40 | 2 |
| C squeeze q 0.7 · e 0.0 · hold 12h | -3.71 | -0.69 | -3.17 | -5.42 | -0.40 | 0.76 | 6.83 | 15.55 | 6.48 | 0.95 | 0.89 | 1.00 | 0.00 | 13.35 | -13.50 | -49.47 | -9.75 | -1.91 | -5.00 | -2.56 | -2.17 | 198 |
| C squeeze q 0.7 · e 0.0 · hold 4h | -7.35 | -1.58 | -6.99 | -11.19 | -0.48 | 0.84 | 9.00 | 20.41 | 8.53 | 0.95 | 0.89 | 1.00 | 0.00 | 5.34 | -11.47 | -47.45 | -8.74 | 1.87 | -8.46 | -5.75 | -7.49 | 77 |
| C squeeze q 0.7 · e 0.5 · hold 12h | -3.22 | -0.78 | -3.17 | -5.42 | -0.29 | 0.61 | 10.44 | 16.42 | 4.47 | 0.43 | 0.37 | 1.00 | 0.00 | 13.34 | -16.66 | -52.63 | -11.34 | -1.91 | -4.69 | -3.13 | -1.82 | 57 |
| C squeeze q 0.7 · e 0.5 · hold 4h | -6.68 | -1.62 | -6.48 | -11.19 | -0.33 | 0.67 | 12.21 | 19.19 | 5.27 | 0.43 | 0.38 | 1.00 | 0.00 | 5.32 | -14.09 | -50.06 | -10.05 | 1.87 | -7.59 | -5.95 | -5.90 | 33 |
| D best 2 hours · N 15m | -13.20 | -5.18 | -17.02 | -25.34 | -0.97 | 1.00 | 40.72 | 86.91 | 39.22 | 0.96 | 0.92 | 1.00 | 0.00 | 1.18 | -15.39 | -51.36 | -10.70 | -1.35 | -15.99 | -16.83 | -19.16 | 27980 |
| D best 2 hours · N 30m | -13.20 | -5.18 | -17.02 | -25.34 | -0.97 | 1.00 | 40.72 | 86.91 | 39.22 | 0.96 | 0.92 | 1.00 | 0.00 | 1.18 | -15.39 | -51.36 | -10.70 | -1.35 | -15.99 | -16.83 | -19.16 | 27980 |
| D best 4 hours · N 15m | -15.42 | -6.54 | -21.51 | -34.04 | -0.99 | 1.00 | 62.10 | 133 | 59.79 | 0.96 | 0.92 | 1.00 | 0.00 | 1.18 | -15.98 | -51.95 | -11.00 | -1.36 | -19.66 | -21.96 | -24.42 | 41201 |
| D best 4 hours · N 30m | -15.42 | -6.54 | -21.51 | -34.04 | -0.99 | 1.00 | 62.10 | 133 | 59.79 | 0.96 | 0.92 | 1.00 | 0.00 | 1.18 | -15.98 | -51.95 | -11.00 | -1.36 | -19.66 | -21.96 | -24.42 | 41201 |
| D weekdays · N 15m | 0.32 | 0.08 | -0.21 | -0.41 | -0.25 | 0.76 | 2.88 | 6.57 | 2.75 | 0.96 | 0.93 | 1.00 | 0.00 | 120 | -9.67 | -45.66 | -7.84 | 8.57 | 0.45 | -0.87 | -0.16 | 2043 |
| D weekdays · N 60m | 0.32 | 0.08 | -0.21 | -0.41 | -0.25 | 0.76 | 2.88 | 6.57 | 2.75 | 0.96 | 0.93 | 1.00 | 0.00 | 120 | -9.67 | -45.66 | -7.84 | 8.57 | 0.45 | -0.87 | -0.16 | 2043 |
| D weekend · N 15m | 0.12 | 0.07 | -0.51 | -0.94 | -0.17 | 0.52 | 2.91 | 6.09 | 2.79 | 0.96 | 0.92 | 1.00 | 0.00 | 48.14 | 3.21 | -32.79 | -1.39 | 12.12 | 0.30 | -0.63 | -1.99 | 1994 |
| D weekend · N 60m | 0.12 | 0.07 | -0.51 | -0.94 | -0.17 | 0.52 | 2.91 | 6.09 | 2.79 | 0.96 | 0.92 | 1.00 | 0.00 | 48.14 | 3.21 | -32.79 | -1.39 | 12.12 | 0.30 | -0.63 | -1.99 | 1994 |

### Checks on the picks (twin from 2024 only)

| variant | is_base | oos_gross | oos_base | oos_taker | cagr_base | dd_base | entries_day | orders_day | rt_day | fill_rate_orders | fill_rate_qty | maker_exit_share | fallback_share | hold_h | gross_bps_rt | net_bps_rt | fee_needed_bps | taker_gross_bps_rt | y2024 | y2025 | y2026 | skipped |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A drop k 5 · e 0.5 · hold 1h · survivorship-free twin | n/a | -0.10 | -0.63 | -1.78 | -0.05 | 0.17 | 0.79 | 1.49 | 0.65 | 0.82 | 0.81 | 1.00 | 0.00 | 2.07 | 6.76 | -29.26 | 0.38 | -47.18 | -0.15 | -0.98 | -0.67 | 46 |
| A drop k 5 · e 0.5 · hold 1h · one bar late | -0.57 | 0.91 | 0.28 | -0.80 | 0.02 | 0.07 | 0.84 | 1.53 | 0.61 | 0.72 | 0.69 | 1.00 | 0.00 | 2.13 | 67.68 | 31.56 | 30.73 | 59.18 | 0.93 | -0.98 | 0.04 | 170 |
| B EMA 24/96 · p 0.5 · W 1h · BTC gate · survivorship-free twin | n/a | 0.50 | 0.40 | 0.16 | 0.08 | 0.44 | 4.31 | 5.13 | 0.74 | 0.17 | 0.16 | 0.99 | 0.01 | 238 | -21.61 | -57.74 | -14.05 | -62.80 | 1.08 | -0.92 | 1.15 | 805 |
| B EMA 24/96 · p 0.5 · W 1h · BTC gate · one bar late | 1.71 | 0.62 | 0.52 | 0.46 | 0.13 | 0.45 | 3.00 | 3.81 | 0.64 | 0.21 | 0.19 | 1.00 | 0.01 | 243 | 125 | 88.50 | 59.10 | 190 | 1.37 | -1.00 | 1.16 | 701 |
| C squeeze q 0.5 · e 0.5 · hold 12h · survivorship-free twin | n/a | -0.96 | -2.76 | -5.25 | -0.11 | 0.28 | 4.81 | 6.82 | 1.63 | 0.34 | 0.30 | 1.00 | 0.00 | 13.23 | -27.01 | -62.98 | -16.54 | -21.83 | -3.99 | -1.48 | -2.98 | 0 |
| C squeeze q 0.5 · e 0.5 · hold 12h · one bar late | -2.54 | -1.55 | -3.10 | -4.98 | -0.13 | 0.32 | 3.90 | 5.68 | 1.31 | 0.34 | 0.29 | 1.00 | 0.00 | 13.36 | -41.19 | -77.12 | -23.64 | -15.13 | -4.20 | -2.98 | -1.51 | 3 |
| D weekdays · N 15m · survivorship-free twin | n/a | -0.25 | -0.55 | -0.71 | -0.38 | 0.84 | 3.21 | 7.02 | 3.10 | 0.97 | 0.94 | 1.00 | 0.00 | 120 | -89.07 | -125 | -47.77 | -65.36 | -0.12 | -1.04 | -0.50 | 1518 |
| D weekdays · N 15m · one bar late | 0.45 | -0.02 | -0.33 | -0.32 | -0.29 | 0.77 | 2.88 | 6.69 | 2.79 | 0.97 | 0.94 | 1.00 | 0.00 | 120 | -18.62 | -54.58 | -12.32 | 19.17 | 0.37 | -0.89 | -0.53 | 2043 |

### Resolution check: 1h against 5-minute bars on the 15 coins with 1-minute history

Not trials. Same code, same 15 coins, 5-minute bars built from the 1-minute history. The base case out-of-sample Sharpe moves by +0.00 at the median (5m minus 1h; range -1.14 to +1.60); 44 of 44 variants keep their sign; 18 are positive at 5 minutes, 18 at 1h.

| variant | oos_base_1h | oos_base_5m | net_bps_1h | net_bps_5m | fill_rate_1h | fill_rate_5m | rt_day_1h | rt_day_5m | oos_taker_1h | oos_taker_5m |
|---|---|---|---|---|---|---|---|---|---|---|
| A drop k 3 · e 0.0 · hold 1h | -1.86 | -2.57 | -46.20 | -25.89 | 0.98 | 0.97 | 2.30 | 6.42 | -3.23 | -4.35 |
| A drop k 3 · e 0.0 · hold 4h | -1.53 | -1.44 | -33.82 | -21.95 | 0.98 | 0.97 | 2.16 | 5.33 | -2.32 | -2.72 |
| A drop k 3 · e 0.0 · hold 12h | -0.20 | -0.19 | 1.27 | 6.87 | 0.98 | 0.97 | 1.96 | 4.27 | -0.81 | -0.85 |
| A drop k 3 · e 0.5 · hold 1h | -1.59 | -2.14 | -49.50 | -25.17 | 0.74 | 0.73 | 1.76 | 4.78 | -3.23 | -4.35 |
| A drop k 3 · e 0.5 · hold 4h | -1.21 | -1.06 | -27.09 | -16.09 | 0.74 | 0.73 | 1.68 | 4.10 | -2.32 | -2.72 |
| A drop k 3 · e 0.5 · hold 12h | -0.05 | -0.01 | 11.43 | 13.08 | 0.74 | 0.73 | 1.53 | 3.39 | -0.81 | -0.85 |
| A drop k 5 · e 0.0 · hold 1h | -0.84 | -0.68 | -59.16 | -15.52 | 0.97 | 0.98 | 0.50 | 1.48 | -1.64 | -1.31 |
| A drop k 5 · e 0.0 · hold 4h | -0.58 | -0.31 | -39.68 | -2.84 | 0.97 | 0.98 | 0.49 | 1.33 | -0.79 | -0.88 |
| A drop k 5 · e 0.0 · hold 12h | 0.32 | 0.16 | 67.33 | 31.42 | 0.97 | 0.98 | 0.47 | 1.16 | -0.10 | -0.29 |
| A drop k 5 · e 0.5 · hold 1h | -0.71 | -0.72 | -62.46 | -23.37 | 0.83 | 0.76 | 0.43 | 1.14 | -1.64 | -1.31 |
| A drop k 5 · e 0.5 · hold 4h | -0.53 | -0.31 | -37.17 | -1.14 | 0.83 | 0.75 | 0.42 | 1.03 | -0.79 | -0.88 |
| A drop k 5 · e 0.5 · hold 12h | 0.37 | 0.14 | 80.97 | 31.07 | 0.83 | 0.73 | 0.40 | 0.91 | -0.10 | -0.29 |
| B EMA 24/96 · p 0.5 · W 1h | 0.75 | 0.75 | 288 | 288 | 0.18 | 0.18 | 0.51 | 0.51 | 0.66 | 0.66 |
| B EMA 24/96 · p 0.5 · W 1h · BTC gate | 1.04 | 1.04 | 519 | 519 | 0.17 | 0.17 | 0.39 | 0.39 | 0.89 | 0.89 |
| B EMA 24/96 · p 0.5 · W 4h | 0.69 | 0.69 | 238 | 238 | 0.50 | 0.50 | 0.54 | 0.54 | 0.66 | 0.66 |
| B EMA 24/96 · p 0.5 · W 4h · BTC gate | 0.91 | 0.91 | 418 | 418 | 0.47 | 0.47 | 0.40 | 0.40 | 0.89 | 0.89 |
| B EMA 24/96 · p 1.0 · W 1h | 0.70 | 0.70 | 334 | 333 | 0.04 | 0.04 | 0.42 | 0.42 | 0.66 | 0.66 |
| B EMA 24/96 · p 1.0 · W 1h · BTC gate | 0.97 | 0.96 | 590 | 589 | 0.05 | 0.05 | 0.30 | 0.30 | 0.89 | 0.89 |
| B EMA 24/96 · p 1.0 · W 4h | 0.67 | 0.67 | 251 | 250 | 0.22 | 0.22 | 0.53 | 0.53 | 0.66 | 0.66 |
| B EMA 24/96 · p 1.0 · W 4h · BTC gate | 0.91 | 0.91 | 461 | 461 | 0.21 | 0.21 | 0.38 | 0.38 | 0.89 | 0.89 |
| B Donchian 55/27 · p 0.5 · W 1h | 0.61 | 0.61 | 130 | 132 | 0.20 | 0.20 | 0.69 | 0.69 | 0.70 | 0.70 |
| B Donchian 55/27 · p 0.5 · W 1h · BTC gate | 1.05 | 1.05 | 276 | 279 | 0.18 | 0.18 | 0.50 | 0.50 | 0.98 | 0.98 |
| B Donchian 55/27 · p 0.5 · W 4h | 0.67 | 0.67 | 126 | 128 | 0.54 | 0.54 | 0.70 | 0.70 | 0.70 | 0.70 |
| B Donchian 55/27 · p 0.5 · W 4h · BTC gate | 0.95 | 0.95 | 231 | 234 | 0.50 | 0.50 | 0.52 | 0.52 | 0.98 | 0.98 |
| B Donchian 55/27 · p 1.0 · W 1h | 0.73 | 0.73 | 186 | 188 | 0.05 | 0.05 | 0.56 | 0.56 | 0.70 | 0.70 |
| B Donchian 55/27 · p 1.0 · W 1h · BTC gate | 1.14 | 1.13 | 366 | 370 | 0.05 | 0.05 | 0.39 | 0.39 | 0.98 | 0.98 |
| B Donchian 55/27 · p 1.0 · W 4h | 0.57 | 0.57 | 110 | 112 | 0.23 | 0.23 | 0.69 | 0.69 | 0.70 | 0.70 |
| B Donchian 55/27 · p 1.0 · W 4h · BTC gate | 0.95 | 0.95 | 244 | 247 | 0.22 | 0.22 | 0.49 | 0.49 | 0.98 | 0.98 |
| C squeeze q 0.5 · e 0.0 · hold 4h | -5.23 | -5.75 | -50.19 | -45.82 | 0.95 | 0.95 | 1.54 | 1.71 | -7.50 | -7.50 |
| C squeeze q 0.5 · e 0.0 · hold 12h | -2.72 | -2.95 | -53.07 | -54.25 | 0.96 | 0.95 | 1.24 | 1.28 | -4.45 | -4.45 |
| C squeeze q 0.5 · e 0.5 · hold 4h | -4.25 | -4.52 | -57.26 | -52.26 | 0.33 | 0.33 | 0.75 | 0.78 | -7.50 | -7.50 |
| C squeeze q 0.5 · e 0.5 · hold 12h | -2.80 | -2.96 | -66.19 | -68.66 | 0.33 | 0.33 | 0.68 | 0.69 | -4.45 | -4.45 |
| C squeeze q 0.7 · e 0.0 · hold 4h | -6.45 | -7.59 | -43.89 | -44.32 | 0.96 | 0.96 | 4.50 | 5.12 | -10.46 | -10.46 |
| C squeeze q 0.7 · e 0.0 · hold 12h | -2.93 | -3.36 | -44.76 | -47.99 | 0.96 | 0.96 | 3.46 | 3.64 | -4.96 | -4.96 |
| C squeeze q 0.7 · e 0.5 · hold 4h | -5.52 | -6.43 | -44.91 | -46.22 | 0.43 | 0.43 | 2.73 | 2.89 | -10.46 | -10.46 |
| C squeeze q 0.7 · e 0.5 · hold 12h | -2.68 | -3.00 | -43.89 | -45.98 | 0.42 | 0.42 | 2.31 | 2.39 | -4.96 | -4.96 |
| D best 2 hours · N 15m | -16.35 | -15.33 | -49.03 | -49.07 | 0.97 | 0.94 | 28.43 | 27.61 | -24.78 | -24.78 |
| D best 2 hours · N 30m | -16.35 | -15.98 | -49.03 | -48.98 | 0.97 | 0.95 | 28.43 | 28.11 | -24.78 | -24.78 |
| D best 4 hours · N 15m | -23.91 | -22.31 | -51.10 | -50.30 | 0.97 | 0.93 | 43.00 | 54.84 | -34.52 | -34.52 |
| D best 4 hours · N 30m | -23.91 | -23.26 | -51.10 | -50.31 | 0.97 | 0.95 | 43.00 | 55.83 | -34.52 | -34.52 |
| D weekend · N 15m | -0.47 | -0.35 | -24.79 | -20.40 | 0.96 | 0.93 | 2.03 | 1.96 | -0.90 | -0.90 |
| D weekend · N 60m | -0.47 | -0.47 | -24.79 | -24.47 | 0.96 | 0.96 | 2.03 | 2.03 | -0.90 | -0.90 |
| D weekdays · N 15m | -0.04 | -0.02 | -14.96 | -12.55 | 0.96 | 0.93 | 2.01 | 1.96 | -0.24 | -0.24 |
| D weekdays · N 60m | -0.04 | -0.04 | -14.96 | -14.80 | 0.96 | 0.96 | 2.01 | 2.01 | -0.24 | -0.24 |

### Deflation pool

488 hand trials with the variance backed out of the published bar (2.43 over 377), the factory's 300 with the variance of their in-sample Sharpes, and this study's 53 (base case, out of sample, clipped at +-3): bar 2.72 over 841. The registered pool (430: 377 plus this study) has a bar of 2.80.

Family D's hours, ranked in sample (best first, UTC): 5, 13, 15, 0, 10, 23, 6, 7, 22, 21, 1, 4, 16, 20, 12, 18, 9, 19, 11, 17, 8, 14, 3, 2.

Trials counted here: A drop k 3 · e 0.0 · hold 1h; A drop k 3 · e 0.0 · hold 4h; A drop k 3 · e 0.0 · hold 12h; A drop k 3 · e 0.5 · hold 1h; A drop k 3 · e 0.5 · hold 4h; A drop k 3 · e 0.5 · hold 12h; A drop k 5 · e 0.0 · hold 1h; A drop k 5 · e 0.0 · hold 4h; A drop k 5 · e 0.0 · hold 12h; A drop k 5 · e 0.5 · hold 1h; A drop k 5 · e 0.5 · hold 4h; A drop k 5 · e 0.5 · hold 12h; B EMA 24/96 · p 0.5 · W 1h; B EMA 24/96 · p 0.5 · W 1h · BTC gate; B EMA 24/96 · p 0.5 · W 4h; B EMA 24/96 · p 0.5 · W 4h · BTC gate; B EMA 24/96 · p 1.0 · W 1h; B EMA 24/96 · p 1.0 · W 1h · BTC gate; B EMA 24/96 · p 1.0 · W 4h; B EMA 24/96 · p 1.0 · W 4h · BTC gate; B Donchian 55/27 · p 0.5 · W 1h; B Donchian 55/27 · p 0.5 · W 1h · BTC gate; B Donchian 55/27 · p 0.5 · W 4h; B Donchian 55/27 · p 0.5 · W 4h · BTC gate; B Donchian 55/27 · p 1.0 · W 1h; B Donchian 55/27 · p 1.0 · W 1h · BTC gate; B Donchian 55/27 · p 1.0 · W 4h; B Donchian 55/27 · p 1.0 · W 4h · BTC gate; C squeeze q 0.5 · e 0.0 · hold 4h; C squeeze q 0.5 · e 0.0 · hold 12h; C squeeze q 0.5 · e 0.5 · hold 4h; C squeeze q 0.5 · e 0.5 · hold 12h; C squeeze q 0.7 · e 0.0 · hold 4h; C squeeze q 0.7 · e 0.0 · hold 12h; C squeeze q 0.7 · e 0.5 · hold 4h; C squeeze q 0.7 · e 0.5 · hold 12h; D best 2 hours · N 15m; D best 2 hours · N 30m; D best 4 hours · N 15m; D best 4 hours · N 30m; D weekend · N 15m; D weekend · N 60m; D weekdays · N 15m; D weekdays · N 60m; A drop k 5 · e 0.5 · hold 1h · survivorship-free twin; A drop k 5 · e 0.5 · hold 1h · one bar late; B EMA 24/96 · p 0.5 · W 1h · BTC gate · survivorship-free twin; B EMA 24/96 · p 0.5 · W 1h · BTC gate · one bar late; C squeeze q 0.5 · e 0.5 · hold 12h · survivorship-free twin; C squeeze q 0.5 · e 0.5 · hold 12h · one bar late; D weekdays · N 15m · survivorship-free twin; D weekdays · N 15m · one bar late; walk-forward pick by quarter.
