# C2: order book snapshots of the M4 perps universes on Kraken Futures and Hyperliquid. Pre-registration

Registered 2026-11-23, committed before the collector's first stored run. While scoping, one round of every symbol
was fetched once into scratch space to learn the answers' formats and to measure the stored size per snapshot (no
cost, fill or performance figure was computed). Context: `results/review_2026-10-27.md` (sections 2 and 3), R5's
trial registry, R6's windows, the readiness ladder (`lab.ops.ladder`). Pattern: `results/book_depth_t4_prereg.md`.
Code: `lab.collect.perps_books` (written after this file). Report: `reports/perps_books/latest.md`. Nothing here may
change once a coverage figure exists; a change is a new registration.

## Question

None yet: this records data. The paper fills of m4_perps cost 0.15x their model and m4_hl_small's 1.49x
(`reports/forward/latest.json`), but `<data>/kraken_futures` holds only hourly marks and funding and no Hyperliquid
book is recorded, so neither ratio can be checked against the venue's own book. The spot recorders (Binance, Kraken,
Bybit, OKX, Coinbase book20) feed only the costs job (`reports/recordings/latest.md`). A later, separately
registered study reads these books; this task uses them in no book and no study.

## Symbols

Each book's universe as the book defines it, rebuilt once a UTC day (the day's first run):
- **Liquid set.** The 100 most liquid Binance USDT perps by `perp_adv28` on the newest day of the cached xs_daily
  panel (`<data>/lab-cache/xs_daily_panel.parquet`, the file the books write) that has perp liquidity for at least
  100 perps (the cached file's newest day often has no perp columns yet), among the perps Binance's public
  `fapi/v1/exchangeInfo` lists as PERPETUAL, TRADING, USDT: `m4_ls.candidates`' set before the score.
- **Kraken Futures (m4_perps).** That set cut to the coins Kraken Futures lists, with m4_perps' own rule
  (`m4_perps.coin_of`, `m4_perps.parse_listing` on the public instruments endpoint: PF_ flexible futures,
  tradeable, not suspended), one symbol per coin, more liquid first; plus every coin `paper/m4_perps/state.json`
  holds that is listed and fell out.
- **Hyperliquid (m4_hl_small).** The same set cut with m4_hl_small's rule (`m4_hl_small.hl_coin` on
  `metaAndAssetCtxs`, delisted coins left out; 1000PEPE as kPEPE), plus every coin
  `paper/m4_hl_small/state.json` holds that is listed and fell out.
- At most 100 symbols a venue plus the held ones (on 2026-11-23: 65 on Kraken Futures and 71 on Hyperliquid, 20
  held each). A failed rebuild keeps the last universe and says so in the health file.

## Schedule and depth

- **Every 5 minutes** (cron `*/5`), one snapshot of every symbol of both venues, **20 levels a side** (price, size,
  best first). Each snapshot belongs to the 5-minute slot of its collection time; a symbol's first snapshot in a
  slot wins. A run stops at 200 s so it never meets the next.
- **Rebalance.** The books rebalance in their paper jobs (`research/ops/jobs.yaml`): paper-m4-perps at 05:15 UTC
  (about 40 s a run), paper-m4-hl-small at 06:00 UTC. Both are on the 5-minute grid. The run at a book's minute
  takes that book's venue first; its snapshots collected within 60 s of the minute are stored with
  `rebalance = true` (about 35 s for the 65 Kraken symbols at the pace below). A book run delayed by its lock wait is
  bracketed by the grid's snapshots (at most 2.5 minutes away); its own fill minute is the later study's matter.

## Endpoints (public, no key)

- Kraken Futures: `GET https://futures.kraken.com/derivatives/api/v3/orderbook?symbol=<PF_...>` (the whole book;
  bids arrive worst first, both sides are sorted and cut to 20), `serverTime` as the book time; the listing from
  `/derivatives/api/v3/instruments`.
- Hyperliquid: `POST https://api.hyperliquid.xyz/info` with `{"type": "l2Book", "coin": ...}` (20 levels a side,
  weight 2) and once a day `metaAndAssetCtxs` (weight 20); `time` as the book time.
- Binance USD-M: `GET https://fapi.binance.com/fapi/v1/exchangeInfo`, once a day.
- **Rate limits.** One call every 0.5 s per venue: Hyperliquid at most 240 of its 1,200 weight a minute per IP (the
  other Hyperliquid jobs use at most 800 together), Kraken Futures 2 calls a second. A 429 waits Retry-After, else
  2, 4 and 8 s (at most 30 s); after the fourth 429 in a row the venue stops for this run and the health line names
  "HTTP 429 from <venue> (its rate limit)". Every 429 is counted per venue and day in the report.

## Storage

`<data>/perps_books/<venue>/<YYYY-MM-DD>.parquet`, columns `ts_us` (the venue's book time), `collected_us`,
`known_us` (= collected_us, the book was public when stamped), `backfilled` (false), `slot_us`, `symbol`, `coin`,
`rebalance`, `bid_px`, `bid_sz`, `ask_px`, `ask_sz` (lists of 20). Each run appends to the day's file through a
temporary file. `state.json` (universe per day, first day per venue, 429s) and `health.json` beside them.

**Budget: under 0.1 GB a day.** Measured on the scoping round: 30.6 kB for 65 Kraken books and 35.8 kB for 71
Hyperliquid books in a one-run file, about 0.5 kB a snapshot (a day's file compresses better, so this is an upper
estimate). Today's universes: (65 + 71) x 288 x 0.5 kB = **about 20 MB a day, 7 GB a year**; at the most the
universe can hold (2 x 120 symbols): 35 MB a day. `reports/disk/breakdown.md` of 2026-11-23: 155.4 GB of 463.9 GB
free, falling 4.21 GB a day, full in 36.9 days (the task's 26 days was an older reading); the tracked datasets grow
0.65 GB a day. 20 MB a day is 0.5 % of the daily fall and moves the full date by about 0.2 days. The health file
turns red when a finished day's two files together exceed 100 MB; the dataset `perps-books` in jobs.yaml is red over
15 GB (two years at today's size). Nothing is deleted: no retention until the study that reads it says what it needs.

## Coverage and health

The report `reports/perps_books/latest.md` (hourly and on each day's first run; `python -m lab.collect.perps_books
report` by hand), per venue and UTC day over the last 7: symbols seen of those expected (the day's universe), the
snapshots per symbol (minimum and median, at most 288), coverage = stored snapshots of the expected symbols / (symbols
x 288), missing snapshots, slots with no snapshot of the venue, the longest such gap in minutes, rebalance snapshots,
429s, MB. Today counts the slots so far; the first day of recording counts from its first slot and is never judged.

The feed `perps-books` (`jobs.py checks`) is red when the last run is older than 30 minutes; when a run lost more than
10 % of a venue's symbols (the cause named, a 429 as the venue's rate limit); when a venue has more than 12 empty
slots in 7 days; **when the last finished UTC day after the first full day of recording is under 90 % coverage**;
and over the storage budget.

## Trials

None. The collector makes no performance number, so no trial goes to R5's registry. The study that reads the books
(costs and fills of m4_perps and m4_hl_small against their models) is registered on its own, with its trials, before
it runs.
