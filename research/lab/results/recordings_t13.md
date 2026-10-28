# T13: use or stop the recordings

Run 2026-10-28 as registered in `results/recordings_t13_prereg.md` (committed first). Code `lab.ops.recordings`, tests
`tests/test_recordings.py` (a fake data folder and a fake code tree: a reader by its path, by a loader's name, by a
loader with string arguments, a collector's own look, a test file, a folder outside the table), weekly job
`recordings` (Mondays 07:30 UTC), report `reports/recordings/latest.md` and `.json`. An inventory: no performance
number, no trial in R5's registry. It stops nothing.

This run: the data folder of the lab server (read only) and the whole repo (381 Python files, 261 TypeScript, Rust
and shell files, 444 jobs, services and studies), disk history from 2026-10-15 (13 days, so the "30 days" are 13).
195 rows: 46 datasets and folders, 149 parts.

## What the lab records and who reads it

| verdict | datasets and folders | GB a month |
|---|--:|--:|
| read by a book or job | 37 | 114.4 |
| read by a study only | 5 | 1.2 |
| read by nobody | 4 | 1.8 |

Almost all of the growth is read. The big ones: `book_depth` 91 GB a month while T4's backfill runs (21 GB now, 16 GB
left, about 38 GB when done, then about 15 GB a year), `pumpfun_rt` 9.4 (the collector holds it under 40 GB by
itself), the five order-book recorders 1.4 to 2.2 each (8.6 together). Of the book recorders only Binance's and
Kraken's have a reader besides the weekly cost calibration (`job:costs`): Bybit, OKX and Coinbase (5.0 GB a month
together) are read by that job alone. Read by a study only: `spread` (the Kraken/Binance logger, 0.11 GB a month; the
README said it would run to 30 days, it still runs), `free` (D2's feeds, read by `data_free_d2` and
`market_structure_i1`), `autopilot-safe`, `fixtures`, `intraday`.

## The proposal for each "read by nobody"

By the pre-registered order (backup, under 1 GB a month, a study in the last 90 days, a study before that, else stop):

| what | GB now | GB a month | proposal | what stopping would lose |
|---|--:|--:|---|---|
| `agent-r2` (a research round's scratch, `PYTHIA_AGENT_OUT`) | 0.54 | ≤ 1.12 | stop | nothing a job reads: xs_daily panels of 2026-10-07 and 2026-10-21, written once on 2026-10-21; the "growth" is that one write inside the window, so stopping means deleting the folder |
| `engine` (the engine's state and its `.bak` copies) | 0.26 | ≤ 0.71 | keep | in the backup; read by the engine itself through `PYTHIA_STATE_FILE`, which a scan of paths cannot see |
| `job-runs` (`_ops/runs`) | 0.01 | 0.02 | keep | the runner's records; `jobs.py` reads them through its table's paths, which the scan does not follow |
| `xstocks` (`free/xstocks`, T10) | 0.00 | 0.00 | keep | T10's record, started this week; its study reads it later (`results/xstocks_t10.md`) |

One part of a read dataset is read by nobody and costs real disk: **`book_depth/raw`** (21.0 GB, ≤ 89.9 GB a month
during the backfill), rule: **stop**. Only the collector itself reads it (`save_month` merges new snapshots into the
month and rebuilds `book_depth/hourly` from it); every study and the feature store read `hourly`. Stopping raw
outright would make a month's hours impossible to rebuild after a fix; the cheaper form is to thin it out: keep raw
for the open month only and delete a month's raw once its hours are written (`hourly` is 0.16 GB today against
21 GB of raw). The other unread parts cost under 0.2 GB a month each (`lab-cache/cache`, the pokemon caches,
`kraken_futures/*`, `polymarket/paper/*`, `models/pumpfun_rt/ideal`, report subfolders): keep.

Nothing is stopped or deleted here. The owner decides; the weekly report shows the same table every Monday.

## How far the scan can be trusted

- A reader is found by its path (a `/` chain from the data root, `join`, an f-string, a string with a `/`) or by
  calling a loader that builds one, through the caller's imports; string arguments continue a path that stopped at
  a variable (`live("binance_um", "premium")`, `_hist("funding", ...)`, `live(source, "book20")` as `*/book20`, which
  matches every venue that has a `book20`). Paths read from settings or environment variables only (the engines'
  `PYTHIA_STATE_FILE`, the runner's table paths) are invisible: `engine`, `autopilot*` and `_ops` look less read than
  they are.
- On the server the job sees only the lab code (`/app`) and the ops folder (`/opt/pythia-ops`, mounted read only);
  the app, server, engine and recorder are not there. Against this run's whole repo that changes one row
  (`pokemon/ui`, read by the app); the report says which code it saw.
- Deviations from the pre-registration, all found before the first table was read: (1) an entry uses what any
  function of its module uses with the calls followed, plus the module level of the modules of its own package it
  imports, not everything of its whole import closure (that made every loader of `lab.data` a read of every job);
  (2) "a writer's own reads do not count" holds for collectors only (`lab.collect`, `*collect*` jobs, the recorder):
  loaders that cache what they fetch (`etf_trend.load_csv`) both write and read, and dropping their reads hid real
  readers; (3) folders with more than 20 sibling folders or a name of six or more digits (symbols, model versions)
  are no parts; (4) a private write helper (`_write`) counts as a write call; (5) a function that returns the data
  root itself (`notify.data_root()`) is a loader too; (6) this inventory's own `results/recordings_*.md` is no study.
