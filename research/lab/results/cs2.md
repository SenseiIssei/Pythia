# CS2 skins market (2026-10-15, before the first collection)

**Read this first.** Paper only: nothing here buys or sells, and nothing will
(automated trading on Steam or a skin marketplace breaks their terms). History
collected so far: **0 days**. This file is the placeholder written with the
code; the daily research report (`lab.cs2.run`, or `python -m
lab.experiments.cs2` with `PYTHIA_RESULTS=results`) replaces it with real
numbers once the collector has run on the lab machine. The machine that wrote
the code could not reach Skinport or Steam, so there are no market numbers
here at all, not even a bootstrap.

**Verdict:** Not measured yet. The pipeline is built and tested on synthetic
markets (planted momentum and planted reversal are found; no planted signal
is reported as a market result).

## What the report will say, and how much to trust each part

| Section | Source | Kind of number | Usable from |
|---|---|---|---|
| 1. Spread Skinport vs Steam, net of fees | collected Steam prices joined with Skinport | observed, today and over the history | the first run (one day); drift needs 14 days |
| 2. Momentum or reversion | bootstrap: Skinport's 90-day sales windows split into disjoint buckets (days 30-90, 7-30, 0-7) | one snapshot, cross-sectional, in-sample across items | the first run |
| 3. Case age, drop pool, operations | case release dates in `lab/collect/cs2_watchlist.json`; events added there | cross-section now; event study only for events inside the history | first run; events when they happen |
| 4. 7 and 30-day forecaster | bootstrap LightGBM, 5-fold across items | NOT a time-series backtest: every fold sees the same weeks | the first run |
| 4. 7 and 30-day forecaster | walk-forward LightGBM on the collector's daily snapshots, monthly expanding refits, labels end before the test month | backtest, out of sample, after a 10 % round trip | about 52 days (7d) and 75 days (30d) of history; a meaningful number of independent periods takes months |
| 5. Paper portfolio | the model's top picks on Skinport prices and fee | forward, play money (10,000 EUR) | the first weekly look |

## Fees used

- Steam: the buyer pays the seller's price plus 5 % (Steam) and 10 % (CS2),
  each at least 0.01; the seller gets Steam wallet funds that cannot be
  withdrawn. Items bought on Steam are trade-locked for 7 days.
- Skinport: 8 % seller fee (check the current rate; high-value items may pay
  less), paid out as cash; purchases arrive with a 7-day trade protection.
- Paper hurdle: Skinport fee plus a 2 % spread allowance, 10 % a round trip.
  Skins have to move a lot to pay for one trade; most weeks the honest answer
  will be "hold cash".

## Known limits

- The bootstrap model's predictions are relative to the median item (one
  snapshot says nothing about the whole market's next move) and scaled from
  the distance between window centres to the horizon. Treat them as a
  ranking, not a price target.
- Skinport's lowest ask can be one odd listing; the reference price is the
  24 h sales median with 3 or more sales, else the 7-day median, else the ask.
- Steam prices cover the watchlist only (about 110 items, up to 100 a run).
