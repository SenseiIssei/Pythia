# listings

W6: does buying a coin when it gets listed pay, and can the Alpaca paper
account act on it? Pre-registered here before `lab.experiments.listings` ran
on any data. Everything below the marker is written by the script.

## Question

The owner wants to catch new coin listings early and join them. Alpaca is the
only venue Pythia trades on (36 crypto pairs, 15 coins with a Binance USDT
pair in the lab's panel). Two separate things are measured:

1. The listing effect itself, where there are enough events to measure it:
   first listings on Binance, and coins already trading on Binance that get
   listed on Coinbase or Kraken (the cross-venue effect).
2. What a rule like "buy at the first Alpaca listing and hold N days" would
   have made, with the honest caveat that Alpaca lists very few coins.

## Data

- A: the lake's hourly bars of every Binance USDT pair ever listed, delisted
  ones included (`hist/binance_spot/klines_1h`, from data.binance.vision,
  history from 2020-01). The first bar of a pair's first continuous segment is
  its listing time. Pairs whose history starts before 2020-02-01 are left out
  (listed before the archive starts), as are stablecoins, gold, wrapped
  duplicates and leveraged tokens. A reused ticker's later segments are not
  counted as listings. A tenfold move inside one hour in a pair's first 31
  days does not split it (opening hours move that much; a redenomination
  does not happen in the first month).
- B: the first hourly candle of each coin's USD pair on Coinbase (public
  candles; the first daily candle finds the day) and the first trade of its
  USD pair on Kraken (public Trades with since=0). Only coins with a Binance USDT pair that has traded 30 days or
  more before that date. Prices are Binance's.
- C: the first daily bar of each coin's USD pair in Alpaca's crypto market
  data (no key needed; every coin of the lake is asked for, plus Alpaca's
  asset list when the paper key pair is set, so pairs Alpaca has since
  removed are found too). Pairs whose first bar is within 45 days of the
  earliest one are the launch batch, not listings, and are left out. Prices
  are Binance's.

Known biases, stated up front: Coinbase and Kraken only return products they
still list, so coins they later removed (often the losers) are missing from
B. Alpaca's bars before its own venue opened come from its data feed, so a
first bar is a proxy for the listing date. Coinbase and Kraken usually
announce a listing before it trades; the day before is reported but cannot be
traded on the listing alert.

## Rules

- Long only (Alpaca cannot short crypto). 35 bps per side (Alpaca taker plus
  slippage), 70 bps reported as stress. Every return is per event, net, and
  judged as excess over BTC across the same window. A coin that stops
  trading before the exit (delisted) is sold at its last close, with BTC to
  the same time, so dead coins count as the losses they were.
- A: entry at the close of the first hour or of the first day after the
  listing; B and C: entry at the Binance close of the first full hour after
  the listing time. Exits after 1, 3, 7 or 30 days. Cells: A 2 x 4, B 4
  (Coinbase and Kraken pooled), C 4; 16 trials here, 393 in the pool with
  the 377 counted before.
- In sample: listings up to 2023-12-31. Out of sample: from 2024-01-01. Per
  family the pick is the in-sample cell with the highest mean net excess
  (10 events or more).
- Uncertainty: a bootstrap over listing months (10,000 draws; events of one
  month share a market). One-sided p is the share of draws with a mean at or
  below 0. Holm correction over every cell with out-of-sample events.
  Deflated Sharpe of the per-event excess returns over the whole pool.

Amended on 2026-10-15 before the first run, after reading the code against
the data sources (no result had been seen): the early tenfold moves in A
(they would have cut the wildest listings out), the Coinbase hour instead of
the day (the day's first candle starts at midnight, which would have entered
before the listing traded), Alpaca's bars asked for every coin (less
survivorship in C) and the last-close exit for dead coins (they would
otherwise drop out). Cells, split, pick and pass rule are unchanged.

## Pass rule for a paper book on Alpaca listings

A new Alpaca listing is a coin that already trades elsewhere, so family B is
the evidence; A cannot justify it (an Alpaca listing is never a coin's first).
The paper book is built only if the B pick, out of sample:

1. has 30 events or more,
2. a mean net excess above 0 with the bootstrap 95 % band above 0,
3. Holm-adjusted p below 0.05 and deflated p above 0.95,
4. is not negative in any out-of-sample year with 10 events or more,

and the Alpaca events themselves (C at the same horizon, all years) do not
contradict it: with 5 events or more their mean net return is not below 0.
The Alpaca events are too few to be evidence on their own.

If it passes: `lab.paper.listings_book` buys every new Alpaca listing the
watcher sees, $500 each (at most 4 open, a $2,000 book), at the first full
hour, and sells after the pick's horizon. If not: alerts only, and the book
stays off.

<!-- generated below by lab.experiments.listings; edit above this line only -->

## Results (generated 2026-10-15, data to 2026-10-15)

**Verdict: no rule passes; alerts only.** out-of-sample mean net excess not above 0; bootstrap 95 % band of the mean includes 0; Holm-adjusted p 1.00 over 16 cells, 0.05 needed; deflated p 0.00, 0.95 needed; negative in 2024, 2025, 2026; the 22 Alpaca listings lost on average at 3 days (-1.3 %).

Events: A 568 first Binance listings (two entries each), B 306 cross-venue listings (Coinbase 141, Kraken 165), C 22 Alpaca listings after the launch batch. Trials here 16, pool 393. Returns are per event, net of 35 bps per side, minus BTC over the same window (excess); the band is a bootstrap over listing months.

Coins that stopped trading inside the window were sold at their last close (events per horizon: 1d 0, 3d 0, 7d 0, 30d 1). 0 pairs moved tenfold within one hour in their first month and were kept as one coin.

### Every cell

| cell | pick | IS n | IS mean excess | OOS n | OOS months | OOS mean excess | OOS median | OOS hit | boot 95 % | OOS mean net | at 70 bps | Holm p | deflated p |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A · first day · 1d | yes | 316 | -4.4 % | 252 | 33 | -1.6 % | -3.1 % | 33 % | -4.7 % to +1.4 % | -1.4 % | -2.1 % | 1.00 | 0.00 |
| A · first day · 3d |  | 316 | -4.7 % | 252 | 33 | -3.9 % | -5.4 % | 36 % | -8.0 % to +0.5 % | -3.6 % | -4.2 % | 1.00 | 0.00 |
| A · first day · 7d |  | 316 | -8.1 % | 252 | 33 | -9.0 % | -10.3 % | 29 % | -13.8 % to -4.6 % | -8.1 % | -8.8 % | 1.00 | 0.00 |
| A · first day · 30d |  | 316 | -7.6 % | 252 | 33 | -15.8 % | -20.2 % | 20 % | -24.6 % to -6.6 % | -11.4 % | -12.0 % | 1.00 | 0.00 |
| A · first hour · 1d |  | 316 | -5.2 % | 252 | 33 | -3.9 % | -4.3 % | 31 % | -6.8 % to -1.3 % | -4.0 % | -4.7 % | 1.00 | 0.00 |
| A · first hour · 3d |  | 316 | -7.3 % | 252 | 33 | -5.7 % | -8.1 % | 31 % | -10.9 % to -0.2 % | -5.5 % | -6.2 % | 1.00 | 0.00 |
| A · first hour · 7d |  | 316 | -10.6 % | 252 | 33 | -10.0 % | -11.1 % | 29 % | -16.3 % to -4.2 % | -9.5 % | -10.2 % | 1.00 | 0.00 |
| A · first hour · 30d |  | 316 | -11.0 % | 252 | 33 | -18.7 % | -25.5 % | 23 % | -28.3 % to -8.8 % | -14.5 % | -15.0 % | 1.00 | 0.00 |
| B · first hour after · 1d |  | 192 | -1.5 % | 114 | 27 | -1.5 % | -1.7 % | 30 % | -2.7 % to -0.2 % | -1.5 % | -2.2 % | 1.00 | 0.00 |
| B · first hour after · 3d | yes | 192 | -1.5 % | 114 | 27 | -2.8 % | -3.3 % | 31 % | -4.5 % to -1.0 % | -2.2 % | -2.9 % | 1.00 | 0.00 |
| B · first hour after · 7d |  | 192 | -3.1 % | 114 | 27 | -3.4 % | -4.1 % | 34 % | -7.4 % to +0.9 % | -3.3 % | -4.0 % | 1.00 | 0.00 |
| B · first hour after · 30d |  | 192 | -6.4 % | 114 | 27 | -9.1 % | -13.1 % | 22 % | -16.4 % to -0.5 % | -10.9 % | -11.6 % | 1.00 | 0.00 |
| C · first hour after · 1d |  | 11 | -0.6 % | 11 | 3 | -1.0 % | -0.9 % | 27 % | -4.3 % to +3.4 % | +0.1 % | -0.6 % | 1.00 | 0.00 |
| C · first hour after · 3d |  | 11 | -1.7 % | 11 | 3 | -0.8 % | -2.8 % | 18 % | -7.4 % to +18.5 % | -1.0 % | -1.7 % | 1.00 | 0.00 |
| C · first hour after · 7d |  | 11 | -8.6 % | 11 | 3 | -5.3 % | -5.4 % | 27 % | -11.2 % to -4.2 % | -6.3 % | -6.9 % | 1.00 | 0.00 |
| C · first hour after · 30d | yes | 11 | -0.5 % | 11 | 3 | -11.1 % | -13.9 % | 9 % | -19.1 % to -9.9 % | -7.6 % | -8.2 % | 1.00 | 0.00 |

### The day before a cross-venue listing (not tradable on the alert)

| venue | n | mean excess | median excess | hit |
|---|---|---|---|---|
| coinbase | 141 | +5.3 % | +1.3 % | 59 % |
| kraken | 165 | +1.7 % | +1.1 % | 60 % |

### Buy every new Alpaca listing and hold N days

22 listings since the launch batch. Too few to test anything; this table is what it would have made, not evidence.

| coin | first Alpaca bar | net 1d | net 3d | net 7d | net 30d |
|---|---|---|---|---|---|
| AAVE | 2021-07-15 | -4.8 % | -7.4 % | -8.4 % | +48.7 % |
| GRT | 2021-07-15 | -7.4 % | -11.7 % | -15.0 % | +43.8 % |
| SUSHI | 2021-07-23 | +0.9 % | +4.9 % | -1.8 % | +64.7 % |
| AVAX | 2021-11-18 | -4.6 % | +19.2 % | +11.3 % | +2.9 % |
| YFI | 2021-12-02 | -0.9 % | -15.9 % | -21.1 % | +15.4 % |
| NEAR | 2022-01-20 | -4.6 % | -24.7 % | -30.9 % | -36.8 % |
| TRX | 2022-04-01 | -0.9 % | -4.5 % | -15.4 % | -17.3 % |
| SHIB | 2023-03-14 | +1.2 % | -6.0 % | -5.1 % | -1.6 % |
| CRV | 2023-08-18 | -0.8 % | -1.3 % | -10.7 % | -14.9 % |
| DOT | 2023-08-18 | +0.5 % | +0.7 % | -2.0 % | -7.8 % |
| XTZ | 2023-08-18 | +0.3 % | +1.2 % | -1.6 % | -4.1 % |
| XRP | 2024-01-01 | +1.8 % | -6.5 % | -6.9 % | -18.0 % |
| PEPE | 2025-01-29 | +5.7 % | +19.3 % | -14.6 % | -31.2 % |
| ADA | 2026-02-13 | +3.9 % | +6.8 % | +3.8 % | -0.7 % |
| ARB | 2026-02-16 | -0.5 % | -7.1 % | -18.6 % | -6.6 % |
| BONK | 2026-02-16 | -1.0 % | -6.6 % | -8.4 % | +0.4 % |
| FIL | 2026-02-16 | +0.1 % | -5.4 % | -5.9 % | -1.3 % |
| LDO | 2026-02-17 | -2.4 % | -6.5 % | -13.4 % | -12.5 % |
| ONDO | 2026-02-17 | -1.9 % | -5.2 % | -10.2 % | -4.3 % |
| POL | 2026-02-19 | -2.5 % | +0.5 % | +4.4 % | -9.5 % |
| RENDER | 2026-02-19 | -0.3 % | +0.6 % | +4.1 % | +20.2 % |
| WIF | 2026-02-19 | -2.0 % | -1.1 % | -3.4 % | -19.9 % |
| $1,000 per listing, total | | $-203 on 22 | $-567 on 22 | $-1,699 on 22 | $+96 on 22 |

### Out of sample by year (each pick)

| pick | year | n | mean excess | hit |
|---|---|---|---|---|
| A · first day · 1d | 2024 | 60 | +2.6 % | 37 % |
| A · first day · 1d | 2025 | 97 | -5.9 % | 19 % |
| A · first day · 1d | 2026 | 95 | +0.2 % | 46 % |
| B · first hour after · 3d | 2024 | 32 | -2.4 % | 34 % |
| B · first hour after · 3d | 2025 | 66 | -3.6 % | 26 % |
| B · first hour after · 3d | 2026 | 16 | -0.7 % | 44 % |
| C · first hour after · 30d | 2024 | 1 | -19.1 % | 0 % |
| C · first hour after · 30d | 2025 | 1 | -14.0 % | 0 % |
| C · first hour after · 30d | 2026 | 9 | -9.9 % | 11 % |
