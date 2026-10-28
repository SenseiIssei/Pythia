# T4: order book depth and delistings. Pre-registration

Registered 2026-10-28 and committed before the collector, the features or the
open interest check ran on the archive (while scoping, one look at BTCUSDT's
metrics against its 5-minute klines from 2026-06-11 to 07-08 and at a few
bookDepth files, to learn the formats; no performance number). Brief T4 of the
training plan of 2026-10-28, on the review of 2026-10-27
(`results/review_2026-10-27.md`, sections 2, 3 and 8), R5's trial registry and
R6's windows. Code: `lab.collect.book_depth`, `lab.features.book`,
`lab.universe.tradable`, `lab.collect.um_metrics --check-shift` (all written
after this file). Report: `results/book_depth_t4.md`. Nothing here may change
once a result exists.

## Question

New information instead of re-mined prices: three years of order book depth
for the lab's perpetuals from Binance's public archive, a point-in-time history
of delistings, and an answer to the review's open question whether Binance's
metrics files shifted `create_time` by one period on 2026-06-25.

## Data

- **Universe.** The perpetuals of `lab.collect.um_metrics` (every USDT perp
  that ranked among the 120 most liquid of the `xs_daily` panel on some day
  since 2021-12, from 100 days before to its last such day), each over the
  days its metrics file covers, from 2023-01-01, plus the 20 lab coins' perps.
- **bookDepth.** `data/futures/um/daily/bookDepth/<SYMBOL>/<SYMBOL>-bookDepth-<day>.zip`
  and its `.CHECKSUM` (sha256). A file whose checksum fails is not stored and
  is fetched again next run. Per snapshot (about every 30 s) the cumulative
  notional in USD within 1 to 5 % of mid per side, and within 0.2 % where the
  file has it. Stored point in time (`ts_us` the snapshot, `collected_us`,
  `known_us` = the snapshot time, as D2 does for market data that was public
  when it was stamped, `backfilled`, and `published_us`, the file's time in the
  archive, for a use that must only see what the archive had).
- **Size rule.** Before the backfill the collector lists the archive, sums the
  zip sizes of every day it would fetch and scales them by the stored size per
  zip byte measured on a sample. If the full history would exceed 40 GB it logs
  the estimate, fetches nothing and the report says so.
- **Daily job** for the new days and the rest of the backfill (resumable by
  symbol and month).

## Features (lab.features, group book_depth, hourly and daily)

From the snapshots in each UTC hour (daily: the hours' mean weighted by
snapshots, at least 12 hours):
- `bd_depth02_usd`, `bd_depth1_usd`: bid plus ask notional within 0.2 % and 1 %.
- `bd_imb02`, `bd_imb1`: (bid - ask) / (bid + ask) at 0.2 % and 1 %.
- `bd_depth02_chg`, `bd_depth1_chg`: change over the bucket; `bd_depth1_chg_24h`
  (hourly) over 24 hours. None across a gap.
- `bd_cost10k_bps`, `bd_cost100k_bps`: the mean slippage from mid of a 10k and
  a 100k USD market order, buy and sell averaged, with the cumulative notional
  linear between the levels (0 at mid); none when the size exceeds the 5 %
  depth. Before the file has the 0.2 % level the first segment runs from mid
  to 1 %; the report states the date the 0.2 % level starts.
Every feature passes T1's leak check (`lab.leak`) on synthetic and real tables.

## Delistings

Binance's announcement list (keyless JSON behind binance.com/en/support/announcement,
the delisting catalogue and, for the monitoring tag, the news catalogue):
spot coin delistings, USD-M perp delistings (an article body read when the
title does not name the symbols) and monitoring tags, each (symbol, base, kind,
announced, delisted). Where no announcement names a perp that stopped, the
archive itself: delisted the day after its last bookDepth file, announced
unknown. `lab.universe.tradable(P, coins, drop_delisting=True)` removes a coin
from the UTC day its delisting (spot or perp) was announced; the decision at
that day's close knows an announcement made during it. Off by default where
nothing asks for it: no paper book or live bot changes.

## Open interest check

For BTCUSDT, ETHUSDT and SOLUSDT, the 14 days before and after 2026-06-25: the
taker buy/sell volume ratio of each metrics row against the ratio from the
5-minute kline opening at the row's `create_time` shifted by -2 to +2 periods,
correlation of the logs per day. A shift is real if the best lag differs before
and after the date for any of the three; then `um_metrics.day_row` is fixed
and the stored days after the date rebuilt. Also reported: the open interest of
each row against the recorder's 60 s open interest (from 2026-09-30), which
minute it matches.

## Trials

Nothing here makes a performance number: coverage, sizes, a lag and a yes or
no. No trial goes into `<data>/trials/registry.jsonl`; no return of the
validation (2024-01-01 to 2026-06-30) or lockbox (from 2026-07-01) window is
looked at. A later study that uses the features registers its own trials.
