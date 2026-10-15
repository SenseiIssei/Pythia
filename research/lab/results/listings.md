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
  counted as listings.
- B: the first daily candle of each coin's USD pair on Coinbase (public
  candles) and the first trade of its USD pair on Kraken (public Trades with
  since=0). Only coins with a Binance USDT pair that has traded 30 days or
  more before that date. Prices are Binance's.
- C: the first daily bar of every Alpaca crypto USD pair (market data API).
  Pairs whose first bar is within 45 days of the earliest one are the launch
  batch, not listings, and are left out. Prices are Binance's.

Known biases, stated up front: Coinbase and Alpaca only return products they
still list, so coins they later removed (often the losers) are missing from B
and C. Coinbase's first daily candle is a day-level time, so the B entry can
be up to a day late against the real listing. Coinbase and Kraken usually
announce a listing before it trades; the day before is reported but cannot be
traded on the listing alert.

## Rules

- Long only (Alpaca cannot short crypto). 35 bps per side (Alpaca taker plus
  slippage), 70 bps reported as stress. Every return is per event, net, and
  judged as excess over BTC across the same window.
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

## Results

Not run yet. The study needs the lab's lake (`hist/binance_spot/klines_1h`)
and the public APIs of Coinbase, Kraken and Alpaca, which the machine this
was written on cannot reach. Run it on the lab server:

```bash
docker run --rm --memory 4g -v /srv/pythia-data:/data -v /opt/pythia-lab:/app --env-file /etc/pythia/alpaca-paper.env pythia-lab python -m lab.experiments.listings
```

Until it has run the verdict is the default: no rule passes, alerts only.
