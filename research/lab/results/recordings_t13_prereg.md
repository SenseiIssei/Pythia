# T13: use or stop the recordings. Pre-registration

Registered 2026-10-28 and committed before the first run of `lab.ops.recordings`, so before any size, growth or
verdict below exists. Brief T13 of the training plan of 2026-10-28, on the review of 2026-10-27
(`results/review_2026-10-27.md`, could explore 9: the lab records a lot and some of it is read by nobody). Code
`lab/ops/recordings.py`, tests `tests/test_recordings.py` on a fake data folder and a fake code tree, weekly job
`recordings`. An inventory, not a study: it makes no performance number, so no trial goes to R5's registry. It reads
only and writes nothing but `reports/recordings/latest.md` and `.json`. It stops nothing; the owner decides.

## What is a dataset

Every entry of `datasets` in `research/ops/jobs.yaml`, and every top-level folder of `<data>` that is neither a
dataset nor holds one. Below each, its parts down to two folder levels (`hist/binance_spot/klines_5m`,
`binance_um/premium`), a folder that is a partition (`date=...`, `symbol=...`) ends the descent.

## The numbers

- **Size**: the bytes of every file under the folder now (one walk, `lstat`, links not followed).
- **Growth a day over 7 and 30 days**: from `<data>/_ops/disk/history.jsonl` (the dataset's size against the oldest
  entry inside the window that has it, at least one day back; the span used is shown when the record is shorter
  than the window). Parts and folders without a record: the bytes of files modified inside the window divided by
  its days, marked as an upper bound (a file rewritten in place counts whole).
- **GB a month**: the 7-day growth a day times 30 (the 30-day one when there is no 7-day one), never below 0.

## Who writes and who reads, by a static scan of the code

- Python, by its syntax tree: a path is a chain of `/` from the data root (or any expression) over string segments,
  `join`/`joinpath`/`Path` with string arguments, a string holding a `/`, an f-string; it stops at the first
  variable. A function that builds such a path is a loader of it; a call of a loader (found by its name through the
  caller's imports, or in the same file) uses what the loader uses, and string arguments of the call extend a path
  that stopped at a variable (`live("binance_um", "premium")`, `_hist("funding", ...)`). A use is a write when the
  path, or a name it was assigned to, is the receiver or an argument of a write call (`write_*`, `to_parquet`,
  `sink_*`, `mkdir`, `save*`, `dump`, `append_*`, `open` in a write mode, the recorder's `table`); every other use
  is a read. A writer's own reads of what it writes do not count as reads.
- A job reads or writes what any module of its import closure (inside the scanned code) does; the job's entry is its
  `python -m` module or the script it runs. The services that run outside the job table count as jobs: the recorder,
  the pump.fun collector and live service, the chat service, the Discord bot, and the app, server and engine code
  (TypeScript, Rust and shell by a text scan of their string paths, every use a read).
- Test files are not readers.

## The verdict

- **read by a book or job**: an enabled job's or a service's closure reads it (a book is a job of `lab.paper` or
  named `paper*`).
- **read by a study only**: only modules no enabled job or service reaches read it.
- **read by nobody**: no reader.

**Last study**: the newest `results/*.md` that names the folder's path or one of its reading modules, dated by the
first date in its first five lines (else the newest date in the file not after today).

## The proposal for each "read by nobody"

In this order: **keep** when it is in the backup's include list (state that cannot be rebuilt), costs under 1 GB a
month, or a study used it in the last 90 days; **thin out** (shorter retention or a lower frequency) when a study
used it before that; **stop** otherwise. The proposals go to `results/recordings_t13.md` with a line each on what
stopping would lose. Nothing is stopped or deleted by this task.
