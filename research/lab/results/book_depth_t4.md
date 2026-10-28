# T4: order book depth and delistings

Run 2026-10-28 as pre-registered in `results/book_depth_t4_prereg.md` (archive
listed through 2026-10-26). Code: `lab.collect.book_depth` (job `book-depth`,
10:30 UTC daily), `lab.features.book`, `lab.universe.tradable`,
`lab.collect.um_metrics --check-shift`. Data only: no trial, no performance
number, nothing a live bot, a wallet or the engine reads changed.

The research container mounts the data folder read only, so the backfill
itself runs on the server with the job. Here the archive was listed in full
(sizes, days, gaps, publication times), 160 files of four perps were fetched,
verified and stored in a scratch folder to measure the stored size, and the
delisting history was read into a scratch table.

## Coverage of the archive

The universe is `lab.collect.um_metrics`' 444 stored perps (433 USDT perps;
11 USDC ones are left out) over the days their metrics files cover, from
2023-01-01, plus the 20 lab coins' perps (all already in it). 431 have
bookDepth files in their window; RAYUSDT and SCUSDT have none.

| Year | Perps with files | Days (perp-days) | Zipped GB | Stored GB (0.254) |
|---|---:|---:|---:|---:|
| 2023 | 226 | 64,330 | 27.1 | 6.9 |
| 2024 | 300 | 83,581 | 35.9 | 9.1 |
| 2025 | 352 | 100,996 | 39.8 | 10.1 |
| 2026 to 10-26 | 315 | 69,877 | 34.5 | 8.8 |
| **All** | **431** | **318,784** | **137.3** | **34.9** |

- **Size rule.** Stored bytes per zip byte, measured on 160 stored days of
  BTCUSDT, ETHUSDT, DOGEUSDT (7 days each) and ARBUSDT (139 days), month files
  with their hours: 0.254 (0.232 to 0.256 per perp). The whole history comes
  to about 34.9 GB, under the 40 GB rule, so the backfill goes ahead. The
  collector starts from a ratio of 0.26 (35.7 GB) and switches to the measured
  one once 100 MB are stored; it refuses the backfill whenever the estimate
  passes 40 GB. After the backfill the store grows by about 43 MB a day (15 GB
  a year); the dataset row `book-depth` in jobs.yaml goes red past 45 GB.
- **Time.** About 0.7 s a request from the server, 16 threads, at most 20
  requests a second: the 318,784 files (each with its checksum) take about
  six runs of at most 60,000 files.
- **Gaps.** 1,627 perp-days are missing inside a perp's listed range. Most are
  whole archive days: 2023-02-08 and 09 (147 perps each), 2026-10-08 (136),
  2026-01-14 (117), 2024-04-18 (93), 2023-11-16 (39), 2023-11-01 (31).
  CVXUSDT (436) and CTKUSDT (414) were delisted and listed again. The lab
  coins miss 2 to 6 days each.
- **The 0.2 % level** starts on 2026-01-16 (BTCUSDT and ARBUSDT, the first
  file with it); before, the files have 1 to 5 % only, so `bd_depth02_usd`,
  `bd_imb02` and `bd_depth02_chg` start then, and the cost features run their
  first segment straight from mid to 1 %.
- **Publication.** Since 2026-09-01 a day's file appears 31 to 34 h after the
  day starts (median 31.8 h): 7 to 10 h after its end. The rows keep that time
  (`published_us`). Files of early 2023 were put up in July 2023.
- **Stopped perps.** 96 of the 431 have no file in the last 7 days.

The lab coins (whole window from 2023-01-01, or from listing):

| Perp | First file | Days | Gaps | Zipped GB | Stored GB |
|---|---|---:|---:|---:|---:|
| BTCUSDT | 2023-01-01 | 1,391 | 4 | 0.65 | 0.17 |
| ETHUSDT | 2023-01-01 | 1,392 | 3 | 0.68 | 0.17 |
| SOLUSDT | 2023-01-01 | 1,389 | 6 | 0.60 | 0.15 |
| XRPUSDT | 2023-01-01 | 1,390 | 5 | 0.67 | 0.17 |
| DOGEUSDT | 2023-01-01 | 1,391 | 4 | 0.66 | 0.17 |
| ADAUSDT | 2023-01-01 | 1,391 | 4 | 0.62 | 0.16 |
| AVAXUSDT | 2023-01-01 | 1,391 | 4 | 0.55 | 0.14 |
| LINKUSDT | 2023-01-01 | 1,391 | 4 | 0.65 | 0.17 |
| LTCUSDT | 2023-01-01 | 1,391 | 4 | 0.66 | 0.17 |
| DOTUSDT | 2023-01-01 | 1,391 | 4 | 0.61 | 0.16 |
| BCHUSDT | 2023-01-01 | 1,392 | 3 | 0.64 | 0.16 |
| TRXUSDT | 2023-01-01 | 1,389 | 6 | 0.63 | 0.16 |
| SUIUSDT | 2023-05-03 | 1,258 | 2 | 0.59 | 0.15 |
| NEARUSDT | 2023-01-01 | 1,390 | 5 | 0.56 | 0.14 |
| ATOMUSDT | 2023-01-01 | 1,391 | 4 | 0.64 | 0.16 |
| UNIUSDT | 2023-01-01 | 1,390 | 5 | 0.55 | 0.14 |
| AAVEUSDT | 2023-01-01 | 1,390 | 5 | 0.54 | 0.14 |
| XLMUSDT | 2023-01-01 | 1,390 | 5 | 0.63 | 0.16 |
| 1000PEPEUSDT | 2023-05-05 | 1,256 | 2 | 0.65 | 0.17 |
| FILUSDT | 2023-01-01 | 1,391 | 4 | 0.61 | 0.16 |

## Features

Nine features in `lab.features` (group `book_depth`, hourly and daily; the
24-hour change hourly only): `bd_depth02_usd`, `bd_depth1_usd`, `bd_imb02`,
`bd_imb1`, `bd_depth02_chg`, `bd_depth1_chg`, `bd_depth1_chg_24h`,
`bd_cost10k_bps`, `bd_cost100k_bps`. All pass T1's leak check on synthetic
tables, and a planted one that reads the next hour fails it (tests); the
weekly `leak-check` job runs them on the real table once it has rows.

The cost is the slippage of walking the book from mid with the cumulative
notional linear between the levels; it carries no half spread beyond what the
0.2 % level shows. On the sample's daily medians: BTCUSDT 0.002 bps for 10k and
0.018 bps for 100k, DOGEUSDT 0.08 and 0.78, ARBUSDT in 2023 (no 0.2 % level)
0.22 and 2.1 bps; BTC's depth within 1 % about 460 M USD, within 0.2 % about
117 M. These are descriptions of the data, not results.

## Delistings

Binance's announcement list is readable without a key (the JSON behind
binance.com/en/support/announcement). The delisting catalogue (446 articles,
from 2022-02-17) gives spot coin delistings and USD-M perp delistings (the
article body read when the title says "Multiple"); the news catalogue (4,467
articles) the monitoring tags. Margin, spot pair, leveraged token, option,
COIN-M only, Alpha, Earn and loan notices are skipped. Perps whose files
stopped and that no announcement names get an archive row (delisted the day
after the last file, announcement unknown, known two days after the last
file).

The scratch table on 2026-10-28 (one clean run, 353 rows):

| Kind | Source | Rows (symbols) | From | Without a delisting date |
|---|---|---:|---|---:|
| spot | announcement | 149 | 2022-03-01 | 0 |
| perp | announcement | 94 | 2022-04-04 | 26 |
| perp | archive | 26 | 2023-05-26 | 0 |
| monitoring | announcement | 84 | 2023-10-04 | 84 (a tag has none) |

Of the 433 perps in the universe, 38 have a perp delisting announcement, 65 a
spot delisting of their coin and 107 at least one row of the three delisting
sources. Of the 96 perps whose files stopped, 70 are named by an
announcement; the other 26 get the archive row. Perp titles without a date
take the first date in the body; 26 have none.

At one request every 1.5 s Binance's list answered 429 after about 70
pages; at one every 3 s (the collector's pace) the whole history came through
in one run. After a 429 the collector keeps what it read and resumes the
history at the page it stopped (`book_depth/announcements.json`).

`universe.tradable(P, coins, drop_delisting=True)` removes a coin from the UTC
day of its earliest known spot or perp delisting (the monitoring tag does not
count; an announcement before the column's first bar belongs to an older
asset of a reused ticker). Nothing calls it yet, so no book changes.

## The open interest check (create_time on 2026-06-25)

Answer: **no shift, nothing to fix.**

For BTCUSDT, ETHUSDT and SOLUSDT, 14 days on each side of 2026-06-25 (84
files of each kind): the taker buy/sell volume ratio of every metrics row
against the ratio of the 5-minute kline opening at the row's `create_time`
shifted by -2 to +2 periods, correlation of the logs per day.

| Perp | Side | Days | Best lag | Lag 0 correlation (lowest day) | Highest at lag -1 or +1 |
|---|---|---:|---:|---:|---:|
| BTCUSDT | before | 14 | 0 every day | 0.994 | 0.170 |
| BTCUSDT | after | 14 | 0 every day | 0.999 | 0.186 |
| ETHUSDT | before | 14 | 0 every day | 0.999 | 0.206 |
| ETHUSDT | after | 14 | 0 every day | 0.999 | 0.207 |
| SOLUSDT | before | 14 | 0 every day | 0.998 | 0.267 |
| SOLUSDT | after | 14 | 0 every day | 0.999 | 0.197 |

`create_time` is the open of the row's 5-minute period on both sides of the
date. Every file has 288 rows inside its day, 00:00 to 23:55; some files are
not sorted (2026-05-01, 06-01, 06-28, 08-15, 10-20), which `day_row` handles
by sorting. Against the recorder's 60 s open interest (2026-10-01 to 25, from
2026-09-30 only, so after the date), the open interest of a row stamped s
matches the recorder's at s + 5 to 6 minutes for BTCUSDT (0.80 bp median
error, 2.75 bp at s) and s + 4 to 7 for SOLUSDT; ETHUSDT's errors are flat
(6.5 to 7.9 bp at every offset). So the open interest is the snapshot at the
period's end, and the day's last row (23:55) is the open interest at the
day's close, which is what `um_metrics.day_row` and the feature store's
`oi` group assume. The check is `python -m lab.collect.um_metrics
--check-shift BTCUSDT,ETHUSDT,SOLUSDT` (exit 1 on a shift).

## Trials

None registered: coverage, sizes, a lag and a yes or no are not trials, and
no return of the validation or lockbox window was looked at. A study that
uses the features registers its own.
