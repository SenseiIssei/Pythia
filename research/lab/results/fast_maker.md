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
